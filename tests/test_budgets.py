"""Tests for cba.budgets — limits, warnings, breaches, burn-down pace."""
import unittest
from datetime import date

from cba.budgets import BudgetService
from cba.ledger import LedgerService
from tests.helpers import TempDirTestCase


class TestBudgets(TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.today = date.today()
        self.y, self.m = self.today.year, self.today.month
        self.ledger = LedgerService(db_path=self.db, fx=self.fx)
        self.budgets = BudgetService(db_path=self.db, ledger=self.ledger)
        self.day = self.today.replace(day=5).isoformat()

    def _spend(self, amount, category="food", currency="USD"):
        self.ledger.add("expense", amount, currency, category, date_=self.day)

    def test_set_and_get_budget(self):
        self.budgets.set_budget(self.y, self.m, 1500, "USD")
        got = self.budgets.get_budgets(self.y, self.m)
        self.assertEqual(got["__total__"]["limit"], 1500.0)

    def test_set_category_budget(self):
        self.budgets.set_budget(self.y, self.m, 400, "USD", category="food")
        got = self.budgets.get_budgets(self.y, self.m)
        self.assertEqual(got["food"]["limit"], 400.0)

    def test_invalid_limit_rejected(self):
        with self.assertRaises(ValueError):
            self.budgets.set_budget(self.y, self.m, 0, "USD")

    def test_status_no_budget(self):
        st = self.budgets.status(self.y, self.m, "USD")
        self.assertIsNone(st["total"]["limit"])
        self.assertEqual(st["warnings"], [])

    def test_warning_at_80pct(self):
        self.budgets.set_budget(self.y, self.m, 1000, "USD")
        self._spend(850)
        st = self.budgets.status(self.y, self.m, "USD")
        self.assertAlmostEqual(st["total"]["pct"], 85.0)
        self.assertTrue(any("Warning" in w for w in st["warnings"]))

    def test_no_warning_below_threshold(self):
        self.budgets.set_budget(self.y, self.m, 1000, "USD")
        self._spend(500)
        st = self.budgets.status(self.y, self.m, "USD")
        self.assertEqual(st["warnings"], [])

    def test_breach_at_100pct(self):
        self.budgets.set_budget(self.y, self.m, 1000, "USD")
        self._spend(1100)
        st = self.budgets.status(self.y, self.m, "USD")
        self.assertTrue(any("Over budget" in w for w in st["warnings"]))

    def test_category_warning(self):
        self.budgets.set_budget(self.y, self.m, 100, "USD", category="food")
        self._spend(95, category="food")
        st = self.budgets.status(self.y, self.m, "USD")
        self.assertTrue(any("food" in w for w in st["warnings"]))

    def test_pace_message_present(self):
        self.budgets.set_budget(self.y, self.m, 1000, "USD")
        self._spend(100)
        st = self.budgets.status(self.y, self.m, "USD")
        self.assertIn("pace", st)
        self.assertIn("month-end", st["pace"]["message"])

    def test_budget_currency_converted(self):
        # 7250 CNY ≈ 1000 USD with the fake table.
        self.budgets.set_budget(self.y, self.m, 7250, "CNY")
        self._spend(900, currency="USD")
        st = self.budgets.status(self.y, self.m, "USD")
        self.assertAlmostEqual(st["total"]["limit"], 1000.0, places=1)
        self.assertTrue(any("Warning" in w for w in st["warnings"]))


if __name__ == "__main__":
    unittest.main()
