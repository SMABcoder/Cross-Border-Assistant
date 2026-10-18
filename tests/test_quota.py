"""Tests for cba.quota (SAFE FX quota tracker). Offline only."""
from __future__ import annotations

import unittest
from unittest import mock

import config
from cba.quota import QuotaService
from tests.helpers import TempDirTestCase


class QuotaServiceTest(TempDirTestCase):
    def _svc(self) -> QuotaService:
        return QuotaService(db_path=self.db, fx=self.fx)

    # -- record() ------------------------------------------------------
    def test_record_converts_cny_to_usd(self):
        svc = self._svc()
        row = svc.record("2025-03-10", 725, "CNY", note="tuition")
        self.assertEqual(row["amount_usd"], 100.00)
        self.assertEqual(row["currency"], "CNY")
        self.assertEqual(row["date"], "2025-03-10")
        self.assertEqual(row["note"], "tuition")
        self.assertEqual(row["amount"], 725.0)

    def test_record_invalid_amount_raises(self):
        svc = self._svc()
        with self.assertRaises(ValueError):
            svc.record("2025-03-10", 0, "USD")
        with self.assertRaises(ValueError):
            svc.record("2025-03-10", -5, "USD")

    def test_record_unsupported_currency_raises(self):
        svc = self._svc()
        with self.assertRaises(ValueError):
            svc.record("2025-03-10", 100, "XYZ")

    def test_record_note_defaults_to_empty(self):
        svc = self._svc()
        row = svc.record("2025-03-10", 50, "USD")
        self.assertEqual(row["note"], "")

    # -- usage() -------------------------------------------------------
    def test_usage_sums_only_requested_year(self):
        svc = self._svc()
        svc.record("2024-05-01", 1000, "USD")
        svc.record("2025-06-01", 725, "CNY")   # 100 USD
        svc.record("2025-07-01", 500, "USD")
        u24 = svc.usage(year=2024)
        u25 = svc.usage(year=2025)
        self.assertEqual(u24["used_usd"], 1000.00)
        self.assertEqual(u25["used_usd"], 600.00)
        self.assertEqual(u25["year"], 2025)

    def test_usage_empty_year_is_zeros(self):
        svc = self._svc()
        u = svc.usage(year=2030)
        self.assertEqual(u["used_usd"], 0.00)
        self.assertEqual(u["remaining_usd"], config.QUOTA_ANNUAL_USD)
        self.assertEqual(u["pct"], 0.0)

    # -- status() ------------------------------------------------------
    def test_status_ok_below_warn_threshold(self):
        svc = self._svc()
        with mock.patch.object(config, "QUOTA_ANNUAL_USD", 1000.0):
            svc.record("2025-01-01", 100, "USD")
            st = svc.status(year=2025)
            self.assertEqual(st["verdict"], "ok")
            self.assertEqual(st["warnings"], [])

    def test_status_warning_at_warn_threshold(self):
        svc = self._svc()
        with mock.patch.object(config, "QUOTA_ANNUAL_USD", 1000.0):
            svc.record("2025-01-01", 850, "USD")  # 85% >= 80% warn
            st = svc.status(year=2025)
            self.assertEqual(st["verdict"], "warning")
            self.assertTrue(any("85.0%" in w for w in st["warnings"]))

    def test_status_exceeded_at_breach_threshold(self):
        svc = self._svc()
        with mock.patch.object(config, "QUOTA_ANNUAL_USD", 1000.0):
            svc.record("2025-01-01", 1200, "USD")  # 120% >= 100% breach
            st = svc.status(year=2025)
            self.assertEqual(st["verdict"], "exceeded")
            self.assertTrue(st["warnings"])

    def test_status_exactly_at_breach_is_exceeded(self):
        svc = self._svc()
        with mock.patch.object(config, "QUOTA_ANNUAL_USD", 1000.0):
            svc.record("2025-01-01", 1000, "USD")  # exactly 100%
            st = svc.status(year=2025)
            self.assertEqual(st["verdict"], "exceeded")

    # -- format_status() ------------------------------------------------
    def test_format_status_shows_limit_and_disclaimer(self):
        svc = self._svc()
        svc.record("2025-01-01", 500, "USD")
        text = svc.format_status(svc.status(year=2025))
        self.assertIn("50,000", text)
        self.assertIn("cross-check", text.lower())

    # -- list() ---------------------------------------------------------
    def test_list_returns_rows_in_date_order(self):
        svc = self._svc()
        svc.record("2025-03-01", 100, "USD")
        svc.record("2025-01-01", 200, "USD")
        svc.record("2025-02-01", 300, "USD")
        svc.record("2024-12-01", 999, "USD")  # different year: excluded
        rows = svc.list(year=2025)
        self.assertEqual([r["date"] for r in rows],
                         ["2025-01-01", "2025-02-01", "2025-03-01"])


if __name__ == "__main__":
    unittest.main()
