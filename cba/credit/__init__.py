"""Forecasting: weighted moving average + trend over past months."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import config
from cba.common import connect_db, fmt_money
from cba.ledger import LedgerService


class ForecastService:
    """Project month-end spending from recent history."""

    def __init__(
        self,
        db_path: str | Path | None = None,
        ledger: LedgerService | None = None,
    ) -> None:
        self.db_path = Path(db_path) if db_path else Path(config.DB_PATH)
        self.ledger = ledger or LedgerService(db_path=self.db_path)

    def _past_months(self, year: int, month: int, n: int) -> list[tuple[int, int]]:
        months = []
        y, m = year, month
        for _ in range(n):
            m -= 1
            if m == 0:
                m, y = 12, y - 1
            months.append((y, m))
        return months

    def _monthly_expense(
        self, year: int, month: int, base_currency: str, category: str | None
    ) -> float:
        summary = self.ledger.summary(year, month, base_currency)
        if category:
            return float(summary["by_category"].get(category.lower(), 0.0))
        return float(summary["expense"])

    def monthly_projection(
        self,
        year: int | None = None,
        month: int | None = None,
        base_currency: str | None = None,
        category: str | None = None,
        months: int | None = None,
    ) -> dict:
        """Weighted projection of the current month's total expense.

        Weights recent months more heavily (``CBA_FORECAST_RECENT_WEIGHT``),
        adds a linear trend adjustment, and compares against the budget.
        """
        base_currency = (base_currency or config.APP_CURRENCY).upper()
        months = months if months is not None else config.FORECAST_MONTHS
        months = max(months, 2)
        today = date.today()
        year = year or today.year
        month = month or today.month

        history = [
            self._monthly_expense(y, m, base_currency, category)
            for y, m in self._past_months(year, month, months)
        ]
        # Most recent month first in `history`; apply geometric weights.
        w_recent = float(config.FORECAST_RECENT_WEIGHT)
        weights, remaining, w = [], 1.0, w_recent
        for _ in history:
            weights.append(w)
            remaining -= w
            w *= (1 - w_recent) if w_recent < 1 else 0.5
        # Normalize remaining weight onto the oldest month.
        if remaining > 0 and weights:
            weights[-1] += remaining

        weighted_avg = sum(h * wt for h, wt in zip(history, weights))
        # Linear trend: slope of (oldest -> newest) per month.
        slope = (history[0] - history[-1]) / max(len(history) - 1, 1)
        projected = max(weighted_avg + slope, 0.0)

        verdict = "on track"
        over_by = 0.0
        budget_limit: float | None = None
        try:
            from cba.budgets import BudgetService

            budgets = BudgetService(db_path=self.db_path, ledger=self.ledger)
            status = budgets.status(year, month, base_currency)
            if status["total"]["limit"] is not None:
                budget_limit = float(status["total"]["limit"])
                if projected > budget_limit:
                    verdict = "will exceed budget"
                    over_by = projected - budget_limit
        except Exception:
            pass

        scope = category.lower() if category else "all spending"
        return {
            "month": f"{year:04d}-{month:02d}",
            "scope": scope,
            "base_currency": base_currency,
            "history_months": months,
            "history": [round(h, 2) for h in history],
            "projected": round(projected, 2),
            "budget_limit": round(budget_limit, 2) if budget_limit else None,
            "verdict": verdict,
            "over_by": round(over_by, 2),
            "message": (
                f"Projected {scope} for {year:04d}-{month:02d}:"
                f" {fmt_money(projected, base_currency)}."
                + (
                    f" You will exceed your budget by"
                    f" {fmt_money(over_by, base_currency)}."
                    if verdict == "will exceed budget"
                    else " You are on track."
                )
            ),
        }
