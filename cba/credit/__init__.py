"""Credit-building guidance + checklist tracker.

Honest scope: this module provides educational guidance and a
progress checklist persisted in sqlite. It does NOT connect to any
credit bureau or lender API (see roadmap in README.md).

Score estimator: ``CreditService.estimate_score()`` is a transparent,
clearly-labeled ESTIMATE derived only from checklist progress — it shows
its math in the result dict and carries a disclaimer that it is not a
bureau score. Production bureau integrations are represented by
``BureauAdapter`` (a Protocol) with an inert placeholder
``InertBaihangAdapter`` for Baihang Credit (百行征信); ``fetch_report``
raises ``ProductionGatedError`` because this prototype never contacts
credit bureaus and handles no identity documents.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

import config
from cba.common import ProductionGatedError, connect_db

_SCHEMA = """
CREATE TABLE IF NOT EXISTS credit_checklist (
    item_key TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    done INTEGER NOT NULL DEFAULT 0,
    sort_order INTEGER NOT NULL DEFAULT 0
);
"""


class CreditService:
    """Track credit-building checklist progress."""

    def __init__(
        self,
        db_path: str | Path | None = None,
        checklist_path: str | Path | None = None,
    ) -> None:
        self.db_path = Path(db_path) if db_path else Path(config.DB_PATH)
        self.checklist_path = (
            Path(checklist_path)
            if checklist_path
            else Path(config.DATA_DIR) / "credit_checklist.json"
        )
        conn = connect_db(self.db_path)
        try:
            conn.executescript(_SCHEMA)
            conn.commit()
        finally:
            conn.close()
        self._seed_defaults()

    def _defaults(self) -> list[dict]:
        try:
            payload = json.loads(self.checklist_path.read_text(encoding="utf-8"))
            return payload.get("items", [])
        except (OSError, json.JSONDecodeError):
            return []

    def _seed_defaults(self) -> None:
        conn = connect_db(self.db_path)
        try:
            for item in self._defaults():
                conn.execute(
                    "INSERT OR IGNORE INTO credit_checklist(item_key, label, sort_order)"
                    " VALUES (?, ?, ?)",
                    (item["key"], item["label"], item.get("sort", 0)),
                )
            conn.commit()
        finally:
            conn.close()

    def items(self) -> list[dict]:
        conn = connect_db(self.db_path)
        try:
            rows = conn.execute(
                "SELECT item_key, label, done, sort_order FROM credit_checklist"
                " ORDER BY sort_order, item_key"
            ).fetchall()
        finally:
            conn.close()
        return [
            {"key": r["item_key"], "label": r["label"], "done": bool(r["done"])}
            for r in rows
        ]

    def complete(self, key: str) -> dict:
        return self._set(key, True)

    def uncomplete(self, key: str) -> dict:
        return self._set(key, False)

    def _set(self, key: str, done: bool) -> dict:
        conn = connect_db(self.db_path)
        try:
            cur = conn.execute(
                "UPDATE credit_checklist SET done = ? WHERE item_key = ?",
                (1 if done else 0, key),
            )
            conn.commit()
        finally:
            conn.close()
        if cur.rowcount == 0:
            raise KeyError(f"unknown checklist item '{key}'")
        return {"key": key, "done": done}

    def reset(self) -> None:
        conn = connect_db(self.db_path)
        try:
            conn.execute("UPDATE credit_checklist SET done = 0")
            conn.commit()
        finally:
            conn.close()

    def progress(self) -> dict:
        items = self.items()
        done = sum(1 for i in items if i["done"])
        total = len(items)
        pct = round(done / total * 100, 1) if total else 0.0
        return {
            "done": done,
            "total": total,
            "pct": pct,
            "remaining": [i for i in items if not i["done"]],
        }

    def estimate_score(self) -> dict:
        """Return a transparent, clearly-labeled checklist-progress score ESTIMATE.

        This is a rough educational estimate from checklist progress only —
        it is NOT a bureau score. The result shows its full math and carries
        an explicit disclaimer. Tunables are read from ``config`` inside this
        method so tests may monkeypatch them.
        """
        prog = self.progress()
        done = prog["done"]
        total = prog["total"]
        base = config.CREDIT_ESTIMATE_BASE
        per = config.CREDIT_ESTIMATE_PER_ITEM
        cap = config.CREDIT_ESTIMATE_MAX
        raw = base + done * per
        estimate = min(raw, cap)
        return {
            "estimate": estimate,
            "base": base,
            "points_per_item": per,
            "items_done": done,
            "items_total": total,
            "max": cap,
            "math": (
                f"{base} + {done} completed x {per} pts = {raw}"
                f" -> capped at {cap} = {estimate}"
            ),
            "disclaimer": (
                "Rough educational estimate from your checklist progress only. "
                "Not a bureau score — lenders and bureaus use their own "
                "models and data."
            ),
        }


class BureauAdapter(Protocol):
    """Production interface for bureau data — inert in this prototype."""

    def fetch_report(self, subject_id: str) -> dict:
        ...  # pragma: no cover


class InertBaihangAdapter:
    """Inert stand-in for a Baihang Credit (百行征信) integration."""

    def fetch_report(self, subject_id: str) -> dict:
        """Never contacts a bureau; raises because this is production-gated."""
        raise ProductionGatedError(
            "Baihang/bureau integration is production-gated: this prototype "
            "never contacts credit bureaus and handles no identity documents."
        )
