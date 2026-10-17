"""Tests for cba.ledger — income/expense tracking and monthly summaries."""
import unittest
from datetime import date

from cba.ledger import LedgerService
from tests.helpers import TempDirTestCase


class TestLedger(TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.ledger = LedgerService(db_path=self.db, fx=self.fx)

    def test_add_returns_id(self):
        tx_id = self.ledger.add("expense", 12.5, "USD", "food", note="lunch")
        self.assertIsInstance(tx_id, int)

    def test_add_income(self):
        tx_id = self.ledger.add("income", 1800, "USD", "other", note="stipend")
        rows = self.ledger.list(kind="income")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], tx_id)

    def test_invalid_kind_rejected(self):
        with self.assertRaises(ValueError):
            self.ledger.add("bogus", 10, "USD", "food")

    def test_nonpositive_amount_rejected(self):
        with self.assertRaises(ValueError):
            self.ledger.add("expense", 0, "USD", "food")

    def test_unsupported_currency_rejected(self):
        with self.assertRaises(ValueError):
            self.ledger.add("expense", 10, "XXX", "food")

    def test_list_filters(self):
        self.ledger.add("expense", 10, "USD", "food")
        self.ledger.add("expense", 20, "USD", "transport")
        self.assertEqual(len(self.ledger.list(category="food")), 1)
        self.assertEqual(len(self.ledger.list()), 2)

    def test_summary_totals_and_net(self):
        today = date.today()
        d = today.replace(day=5).isoformat()
        self.ledger.add("income", 1000, "USD", "other", date_=d)
        self.ledger.add("expense", 200, "USD", "food", date_=d)
        self.ledger.add("expense", 725, "CNY", "transport", date_=d)  # = 100 USD
        s = self.ledger.summary(today.year, today.month, "USD")
        self.assertAlmostEqual(s["income"], 1000.0)
        self.assertAlmostEqual(s["expense"], 300.0)
        self.assertAlmostEqual(s["net"], 700.0)
        self.assertAlmostEqual(s["by_category"]["food"], 200.0)
        self.assertAlmostEqual(s["by_category"]["transport"], 100.0)

    def test_summary_currency_conversion(self):
        today = date.today()
        d = today.replace(day=5).isoformat()
        self.ledger.add("expense", 725, "CNY", "food", date_=d)
        s = self.ledger.summary(today.year, today.month, "USD")
        self.assertAlmostEqual(s["expense"], 100.0, places=1)

    def test_summary_excludes_other_months(self):
        today = date.today()
        prev_month = today.month - 1 or 12
        prev_year = today.year if today.month > 1 else today.year - 1
        self.ledger.add("expense", 999, "USD", "food",
                        date_=date(prev_year, prev_month, 15).isoformat())
        s = self.ledger.summary(today.year, today.month, "USD")
        self.assertAlmostEqual(s["expense"], 0.0)

    def test_summary_has_formatted(self):
        s = self.ledger.summary(date.today().year, date.today().month, "USD")
        self.assertIn("income", s["formatted"])
        self.assertTrue(s["formatted"]["income"].endswith("USD"))


if __name__ == "__main__":
    unittest.main()
