"""Tests for cba.forecast — weighted projection vs budget."""
import unittest
from datetime import date

from cba.budgets import BudgetService
from cba.forecast import ForecastService
from cba.ledger import LedgerService
from tests.helpers import TempDirTestCase


class TestForecast(TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.today = date.today()
        self.ledger = LedgerService(db_path=self.db, fx=self.fx)
        self.budgets = BudgetService(db_path=self.db, ledger=self.ledger)
        self.fc = ForecastService(db_path=self.db, ledger=self.ledger)
        # Three months of history, most recent first: 1200, 1100, 1000 USD.
        amounts = [1200, 1100, 1000]
        for back, amt in enumerate(amounts, start=1):
            y = self.today.year + (self.today.month - 1 - back) // 12
            m = (self.today.month - 1 - back) % 12 + 1
            self.ledger.add("expense", amt, "USD", "food",
                            date_=date(y, m, 10).isoformat())

    def test_projection_shape(self):
        proj = self.fc.monthly_projection(self.today.year, self.today.month)
        for key in ("projected", "verdict", "message", "history", "budget_limit"):
            self.assertIn(key, proj)
        self.assertEqual(len(proj["history"]), 3)

    def test_projection_follows_upward_trend(self):
        proj = self.fc.monthly_projection(self.today.year, self.today.month)
        # Weighted avg ≈ 1137 + positive slope -> above 1100.
        self.assertGreater(proj["projected"], 1100)

    def test_on_track_with_generous_budget(self):
        self.budgets.set_budget(self.today.year, self.today.month, 100000, "USD")
        proj = self.fc.monthly_projection(self.today.year, self.today.month)
        self.assertEqual(proj["verdict"], "on track")
        self.assertEqual(proj["over_by"], 0.0)

    def test_will_exceed_with_tight_budget(self):
        self.budgets.set_budget(self.today.year, self.today.month, 500, "USD")
        proj = self.fc.monthly_projection(self.today.year, self.today.month)
        self.assertEqual(proj["verdict"], "will exceed budget")
        self.assertGreater(proj["over_by"], 0)
        self.assertIn("exceed", proj["message"])

    def test_category_scope(self):
        proj = self.fc.monthly_projection(self.today.year, self.today.month,
                                          category="food")
        self.assertEqual(proj["scope"], "food")
        self.assertGreater(proj["projected"], 0)

    def test_category_no_history_zero(self):
        proj = self.fc.monthly_projection(self.today.year, self.today.month,
                                          category="books")
        self.assertEqual(proj["projected"], 0.0)

    def test_message_readable(self):
        proj = self.fc.monthly_projection(self.today.year, self.today.month)
        self.assertIn("Projected", proj["message"])
        self.assertIn("USD", proj["message"])

    def test_no_history_no_crash(self):
        empty = ForecastService(db_path=self.db,
                                ledger=LedgerService(db_path=self.db, fx=self.fx))
        # Fresh DB with no history at all.
        import tempfile, os
        from pathlib import Path

        fresh = str(Path(self.tmp) / "fresh.db")
        fc2 = ForecastService(db_path=fresh, ledger=LedgerService(db_path=fresh, fx=self.fx))
        proj = fc2.monthly_projection(self.today.year, self.today.month)
        self.assertEqual(proj["projected"], 0.0)
        self.assertEqual(proj["verdict"], "on track")


if __name__ == "__main__":
    unittest.main()
