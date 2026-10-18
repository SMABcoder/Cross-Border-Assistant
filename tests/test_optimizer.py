"""Tests for the tuition FX optimizer (advisory only, offline)."""
from __future__ import annotations

import unittest
from pathlib import Path

import config
from cba.alerts import AlertService
from cba.optimizer import (
    SIGNAL_NO_SIGNAL,
    SIGNAL_PAY_NOW,
    SIGNAL_WAIT,
    OptimizerService,
)
from cba.tuition import TuitionService
from tests.helpers import TempDirTestCase, fake_fx


def _svc(testcase, **kwargs):
    tuition = kwargs.pop("tuition", None) or TuitionService(db_path=testcase.db)
    alerts = kwargs.pop("alerts", None) or AlertService(db_path=testcase.db)
    return OptimizerService(
        db_path=testcase.db,
        fx=kwargs.pop("fx", None) or testcase.fx,
        tuition=tuition,
        alerts=alerts,
        **kwargs,
    )


def _add_bill(testcase, **kwargs):
    tuition = TuitionService(db_path=testcase.db)
    params = {
        "name": "Test Tuition",
        "amount": 5000.0,
        "currency": "CNY",
        "due_date": "2026-12-31",
    }
    params.update(kwargs)
    return tuition.add(**params)


class TestOptimizer(TempDirTestCase):
    def test_pay_now_when_rate_above_average(self):
        for _ in range(3):
            self.fx.cached.store_snapshot("USD", {"USD": 1.0, "CNY": 7.0})
        _add_bill(self, name="Spring Tuition")
        self.fx.cached.store_snapshot("USD", {"USD": 1.0, "CNY": 7.5})
        results = _svc(self).optimize()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["signal"], SIGNAL_PAY_NOW)
        self.assertIn("above", results[0]["reason"])

    def test_wait_when_rate_below_average(self):
        for _ in range(3):
            self.fx.cached.store_snapshot("USD", {"USD": 1.0, "CNY": 7.5})
        _add_bill(self, name="Spring Tuition")
        self.fx.cached.store_snapshot("USD", {"USD": 1.0, "CNY": 7.0})
        results = _svc(self).optimize()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["signal"], SIGNAL_WAIT)
        self.assertIn("below", results[0]["reason"])

    def test_no_signal_without_history(self):
        # Fresh FakeProvider-based FxService: empty cache, get_rate still works.
        _add_bill(self, name="Spring Tuition")
        results = _svc(self).optimize()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["signal"], SIGNAL_NO_SIGNAL)
        self.assertIn("not enough rate history", results[0]["reason"])
        self.assertIsNone(results[0]["trailing_avg"])
        self.assertIsNone(results[0]["diff_pct"])

    def test_no_signal_same_currency(self):
        _add_bill(self, name="Local Tuition", currency=config.APP_CURRENCY)
        results = _svc(self).optimize()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["signal"], SIGNAL_NO_SIGNAL)
        self.assertIn("same currency", results[0]["reason"])

    def test_matching_alerts_surfaced(self):
        alerts = AlertService(db_path=self.db)
        alert = alerts.create("USD/CNY", target=7.0, direction="below")
        for _ in range(3):
            self.fx.cached.store_snapshot("USD", {"USD": 1.0, "CNY": 7.0})
        _add_bill(self, name="Spring Tuition")
        results = _svc(self, alerts=alerts).optimize()
        self.assertEqual(results[0]["matching_alerts"][0]["id"], alert["id"])
        self.assertIn(
            f"alert #{alert['id']}", results[0]["reason"]
        )

    def test_format_report(self):
        for _ in range(3):
            self.fx.cached.store_snapshot("USD", {"USD": 1.0, "CNY": 7.0})
        _add_bill(self, name="Spring Tuition")
        self.fx.cached.store_snapshot("USD", {"USD": 1.0, "CNY": 7.5})
        results = _svc(self).optimize()
        report = OptimizerService.format_report(results)
        self.assertIn("PAY_NOW", report)
        self.assertIn("Spring Tuition", report)
        self.assertIn("1 PAY_NOW", report)

    def test_format_report_empty(self):
        self.assertEqual(
            OptimizerService.format_report([]),
            "No unpaid tuition bills to optimize.",
        )

    def test_optimize_no_bills(self):
        self.assertEqual(_svc(self).optimize(), [])

    def test_diff_pct_math(self):
        # avg of (7.0, 7.0, 7.5) = 21.5/3; diff = (7.5-avg)/avg*100
        avg = (7.0 + 7.0 + 7.5) / 3
        for _ in range(2):
            self.fx.cached.store_snapshot("USD", {"USD": 1.0, "CNY": 7.0})
        _add_bill(self, name="Spring Tuition")
        self.fx.cached.store_snapshot("USD", {"USD": 1.0, "CNY": 7.5})
        results = _svc(self).optimize()
        self.assertAlmostEqual(results[0]["trailing_avg"], avg, places=9)
        self.assertAlmostEqual(
            results[0]["diff_pct"], (7.5 - avg) / avg * 100, places=9
        )

    def test_entry_keys(self):
        self.fx.cached.store_snapshot("USD", {"USD": 1.0, "CNY": 7.0})
        self.fx.cached.store_snapshot("USD", {"USD": 1.0, "CNY": 7.0})
        _add_bill(self, name="Spring Tuition")
        (entry,) = _svc(self).optimize()
        for key in (
            "bill", "pair", "today_rate", "trailing_avg", "lookback_days",
            "diff_pct", "signal", "reason", "matching_alerts",
        ):
            self.assertIn(key, entry)
        self.assertEqual(entry["pair"], f"{config.APP_CURRENCY}/CNY")
        self.assertEqual(entry["lookback_days"], config.OPTIMIZER_LOOKBACK_DAYS)

    def test_fx_error_per_bill_graceful(self):
        # No provider can supply USD -> get_rate raises FxError.
        from cba.fx import FxService
        from tests.helpers import FakeProvider

        broken = FakeProvider(rates={"EUR": {"EUR": 1.0, "USD": 1.08}})
        fx = FxService(
            live=broken,
            cache_path=str(Path(self.tmp) / "fx_cache.json"),
            fallback_path=str(Path(self.tmp) / "no_fallback.json"),
        )
        _add_bill(self, name="Spring Tuition")
        (entry,) = _svc(self, fx=fx).optimize()
        self.assertEqual(entry["signal"], SIGNAL_NO_SIGNAL)
        self.assertIn("rate unavailable", entry["reason"])


if __name__ == "__main__":
    unittest.main()
