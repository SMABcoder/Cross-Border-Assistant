"""Exchange-rate layer.

Providers implement the :class:`RateProvider` protocol. :class:`FxService`
chains live provider -> cache -> fallback table so the assistant keeps
working offline.

Live data comes from the free no-key endpoint ``open.er-api.com``
(configurable via ``CBA_FX_API_BASE``). ``requests`` is used when
importable, otherwise stdlib ``urllib``.
"""
from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path
from typing import Protocol

import config

try:  # optional dependency
    import requests  # type: ignore

    _HAS_REQUESTS = True
except Exception:  # pragma: no cover - env dependent
    requests = None  # type: ignore
    _HAS_REQUESTS = False


class RateProvider(Protocol):
    """Anything that can return a rate table for a base currency."""

    def get_table(self, base: str) -> dict[str, float]: ...


class FxError(Exception):
    """Raised when no provider can supply rates."""


class SimpleApiProvider:
    """Fetch live rates from the free no-key JSON endpoint."""

    def __init__(
        self,
        api_base: str | None = None,
        timeout: int | None = None,
    ) -> None:
        self.api_base = (api_base or config.FX_API_BASE).rstrip("/")
        self.timeout = timeout if timeout is not None else config.FX_TIMEOUT

    def get_table(self, base: str) -> dict[str, float]:
        url = f"{self.api_base}/{base.upper()}"
        try:
            if _HAS_REQUESTS:
                resp = requests.get(url, timeout=self.timeout)
                resp.raise_for_status()
                payload = resp.json()
            else:
                with urllib.request.urlopen(url, timeout=self.timeout) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            raise FxError(f"live rate fetch failed for {base}: {exc}") from exc
        if payload.get("result") != "success":
            raise FxError(f"rate API error for {base}: {payload.get('error-type')}")
        rates = payload.get("rates") or {}
        return {k.upper(): float(v) for k, v in rates.items()}


class CachedProvider:
    """JSON-file cache with TTL around another provider.

    Each base currency gets a table plus a fetch timestamp; historical
    snapshots are appended so :meth:`FxService.trend` can work offline.
    """

    def __init__(
        self,
        inner: RateProvider,
        cache_path: str | Path | None = None,
        ttl: int | None = None,
    ) -> None:
        self.inner = inner
        self.cache_path = Path(cache_path) if cache_path else Path(config.FX_CACHE_PATH)
        self.ttl = ttl if ttl is not None else config.FX_CACHE_TTL

    # -- cache IO ---------------------------------------------------------
    def _load(self) -> dict:
        if not self.cache_path.exists():
            return {}
        try:
            return json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _save(self, data: dict) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.cache_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(self.cache_path)

    def store_snapshot(self, base: str, table: dict[str, float]) -> None:
        """Manually record a rate table (used by tests and seed scripts)."""
        data = self._load()
        key = base.upper()
        data.setdefault(key, {"fetched_at": 0, "table": {}, "history": []})
        entry = data[key]
        entry["fetched_at"] = int(time.time())
        entry["table"] = {k.upper(): float(v) for k, v in table.items()}
        entry["history"].append(
            {"ts": int(time.time()), "table": entry["table"]}
        )
        entry["history"] = entry["history"][-60:]  # keep last 60 snapshots
        self._save(data)

    # -- protocol ---------------------------------------------------------
    def get_table(self, base: str) -> dict[str, float]:
        base = base.upper()
        data = self._load()
        entry = data.get(base)
        now = int(time.time())
        if entry and now - entry.get("fetched_at", 0) < self.ttl:
            return dict(entry["table"])
        fresh = self.inner.get_table(base)  # may raise FxError
        self.store_snapshot(base, fresh)
        return dict(fresh)

    def history(self, base: str) -> list[dict]:
        data = self._load()
        return list(data.get(base.upper(), {}).get("history", []))


class FallbackTableProvider:
    """Static fallback rates loaded from a JSON file (data/fallback_rates.json)."""

    def __init__(self, path: str | Path | None = None) -> None:
        path = Path(path) if path else Path(config.DATA_DIR) / "fallback_rates.json"
        try:
            self.tables = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self.tables = {}

    def get_table(self, base: str) -> dict[str, float]:
        table = self.tables.get(base.upper())
        if not table:
            raise FxError(f"no fallback table for {base}")
        return {k.upper(): float(v) for k, v in table.items()}


class FxService:
    """Rate lookup with provider -> cache -> fallback chaining."""

    def __init__(
        self,
        live: RateProvider | None = None,
        cache_path: str | Path | None = None,
        fallback_path: str | Path | None = None,
    ) -> None:
        self.cached = CachedProvider(
            live or SimpleApiProvider(), cache_path=cache_path
        )
        self.fallback = FallbackTableProvider(path=fallback_path)

    def _table(self, base: str) -> dict[str, float]:
        base = base.upper()
        try:
            return self.cached.get_table(base)
        except FxError:
            return self.fallback.get_table(base)

    def get_rate(self, base: str, quote: str) -> float:
        """Units of ``quote`` per one ``base``."""
        base, quote = base.upper(), quote.upper()
        if base == quote:
            return 1.0
        table = self._table(base)
        rate = table.get(quote)
        if rate is None or rate <= 0:
            raise FxError(f"no rate for {base}->{quote}")
        return float(rate)

    def convert(self, amount: float, base: str, quote: str) -> float:
        return float(amount) * self.get_rate(base, quote)

    def trend(self, base: str, quote: str, days: int | None = None) -> dict:
        """Simple trend summary from cached history (offline-safe)."""
        days = days if days is not None else config.FX_TREND_DAYS
        base, quote = base.upper(), quote.upper()
        points = []
        for snap in self.cached.history(base)[-max(days, 1) * 4 :]:
            rate = snap["table"].get(quote)
            if rate:
                points.append({"ts": snap["ts"], "rate": float(rate)})
        if not points:
            current = self.get_rate(base, quote)
            return {
                "pair": f"{base}/{quote}",
                "current": current,
                "change_pct": 0.0,
                "direction": "flat",
                "points": [],
            }
        first, last = points[0]["rate"], points[-1]["rate"]
        change_pct = (last - first) / first * 100 if first else 0.0
        direction = "up" if change_pct > 0.05 else "down" if change_pct < -0.05 else "flat"
        return {
            "pair": f"{base}/{quote}",
            "current": self.get_rate(base, quote),
            "change_pct": round(change_pct, 2),
            "direction": direction,
            "points": points,
        }
