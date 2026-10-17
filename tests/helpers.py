"""Shared test helpers: temp dirs/DBs and a fake (offline) FX provider."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

import config
from cba.fx import FxService


class FakeProvider:
    """Deterministic offline rate provider. Never touches the network."""

    USD_TABLE = {"USD": 1.0, "CNY": 7.25, "EUR": 0.92, "GBP": 0.79, "PKR": 278.0}

    @classmethod
    def _tables(cls) -> dict:
        usd = cls.USD_TABLE
        cny = {ccy: rate / usd["CNY"] for ccy, rate in usd.items()}  # exact inverses
        eur = {ccy: rate / usd["EUR"] for ccy, rate in usd.items()}
        return {"USD": dict(usd), "CNY": cny, "EUR": eur}

    def __init__(self, rates: dict | None = None) -> None:
        self.rates = rates if rates is not None else self._tables()
        self.calls: list[str] = []

    def get_table(self, base: str) -> dict[str, float]:
        self.calls.append(base.upper())
        table = self.rates.get(base.upper())
        if table is None:
            from cba.fx import FxError

            raise FxError(f"fake: no table for {base}")
        return dict(table)


class FailingProvider:
    def get_table(self, base: str):
        from cba.fx import FxError

        raise FxError("fake: offline")


def fake_fx(tmpdir: str | Path, provider=None) -> FxService:
    """FxService wired to a fake provider with cache in the temp dir."""
    return FxService(
        live=provider or FakeProvider(),
        cache_path=str(Path(tmpdir) / "fx_cache.json"),
    )


class TempDirTestCase(unittest.TestCase):
    """Base class giving each test a temp dir, temp DB, and temp cache."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="cba-test-")
        self.db = str(Path(self.tmp) / "test.db")
        self.fx = fake_fx(self.tmp)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)


def write_json(path: str | Path, payload: dict) -> str:
    path = str(path)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    return path
