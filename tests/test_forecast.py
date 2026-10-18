"""Tests for cba.forecast — weighted projection vs budget."""
import unittest
from datetime import date, timedelta

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


class TestForecastSeasonality(TempDirTestCase):
    """Seasonality index (monthly_projection) and category_daily_burn."""

    def setUp(self):
        super().setUp()
        self.today = date.today()
        self.ledger = LedgerService(db_path=self.db, fx=self.fx)
        self.fc = ForecastService(db_path=self.db, ledger=self.ledger)

    def _seed_three_months(self):
        # Same fixture as TestForecast: 1200, 1100, 1000 USD, recent first.
        amounts = [1200, 1100, 1000]
        for back, amt in enumerate(amounts, start=1):
            y = self.today.year + (self.today.month - 1 - back) // 12
            m = (self.today.month - 1 - back) % 12 + 1
            self.ledger.add("expense", amt, "USD", "food",
                            date_=date(y, m, 10).isoformat())

    def _seed_full_year(self, target_year, target_month,
                        heavy_amount=2000.0, base_amount=1000.0,
                        category="food"):
        """Back-date 12 months of expenses; the target calendar month
        costs ``heavy_amount``, all other months ``base_amount``."""
        for back in range(1, 13):
            y = target_year + (target_month - 1 - back) // 12
            m = (target_month - 1 - back) % 12 + 1
            amt = heavy_amount if m == target_month else base_amount
            self.ledger.add("expense", amt, "USD", category,
                            date_=date(y, m, 10).isoformat())

    def test_seasonality_skipped_with_short_history(self):
        self._seed_three_months()
        proj = self.fc.monthly_projection(self.today.year, self.today.month)
        self.assertIn("seasonality_factor", proj)
        self.assertEqual(proj["seasonality_factor"], 1.0)
        # Old formula, untouched: weights [0.5, 0.25, 0.25] on
        # [1200, 1100, 1000] plus slope (1200 - 1000) / 2 = 100.
        self.assertEqual(proj["projected"], 1225.0)

    def test_seasonality_applies_with_year_history(self):
        ty, tm = self.today.year, self.today.month
        self._seed_full_year(ty, tm)
        proj = self.fc.monthly_projection(ty, tm)
        factor = proj["seasonality_factor"]
        self.assertGreater(factor, 1.5)
        self.assertLess(factor, 2.5)
        # Target calendar month costs 2000 vs 1000 elsewhere:
        # index = 2000 / (13000/12) = 24/13 -> rounds to 1.846.
        self.assertEqual(factor, 1.846)
        # Plain projection is flat 1000.0 (history all 1000, no trend).
        self.assertEqual(proj["projected"], 1846.15)

    def test_seasonality_zero_history_safe(self):
        import tempfile
        from pathlib import Path

        fresh = str(Path(self.tmp) / "fresh.db")
        fc2 = ForecastService(db_path=fresh,
                              ledger=LedgerService(db_path=fresh, fx=self.fx))
        proj = fc2.monthly_projection(self.today.year, self.today.month)
        self.assertEqual(proj["seasonality_factor"], 1.0)
        self.assertEqual(proj["projected"], 0.0)

    def test_category_daily_burn_math(self):
        self.ledger.add("expense", 100.0, "USD", "food",
                        date_=self.today.isoformat())
        self.ledger.add("expense", 200.0, "USD", "food",
                        date_=(self.today - timedelta(days=5)).isoformat())
        # Outside the 10-day window: excluded.
        self.ledger.add("expense", 999.0, "USD", "food",
                        date_=(self.today - timedelta(days=30)).isoformat())
        # Wrong category: excluded.
        self.ledger.add("expense", 50.0, "USD", "rent",
                        date_=self.today.isoformat())
        burn = self.fc.category_daily_burn("food", days=10)
        self.assertEqual(
            burn,
            {"category": "food", "days": 10, "total": 300.0,
             "daily_burn": 30.0, "base_currency": "USD"},
        )

    def test_category_daily_burn_default_window(self):
        import unittest.mock as mock

        import config

        self.ledger.add("expense", 90.0, "USD", "food",
                        date_=self.today.isoformat())
        # Proves the default (FORECAST_MONTHS * 30) is read inside the
        # method: monkeypatching changes the window to 60 days.
        with mock.patch.object(config, "FORECAST_MONTHS", 2):
            burn = self.fc.category_daily_burn("food")
        self.assertEqual(burn["days"], 60)
        self.assertEqual(burn["total"], 90.0)
        self.assertEqual(burn["daily_burn"], 1.5)

    def test_old_keys_intact(self):
        self._seed_three_months()
        proj = self.fc.monthly_projection(self.today.year, self.today.month)
        for key in ("month", "scope", "base_currency", "history_months",
                    "history", "projected", "budget_limit", "verdict",
                    "over_by", "message"):
            self.assertIn(key, proj)

    def test_seasonality_respects_category(self):
        ty, tm = self.today.year, self.today.month
        self._seed_full_year(ty, tm, category="food")
        food = self.fc.monthly_projection(ty, tm, category="food")
        self.assertGreater(food["seasonality_factor"], 1.5)
        self.assertLess(food["seasonality_factor"], 2.5)
        # "books" has no expenses: no data -> factor 1.0, projected 0.0.
        books = self.fc.monthly_projection(ty, tm, category="books")
        self.assertEqual(books["seasonality_factor"], 1.0)
        self.assertEqual(books["projected"], 0.0)


if __name__ == "__main__":
    unittest.main()
