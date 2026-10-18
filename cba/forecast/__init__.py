"""Forecasting: weighted moving average + trend over past months.

Extends the plain projection with two additions:

- **Monthly seasonality index** — the plain projection is scaled by the
  historical share of the target calendar month (average expense in that
  calendar month across the trailing ``FORECAST_SEASONALITY_MONTHS``
  months, divided by the overall average monthly expense). This is pure
  arithmetic on historical totals, not a learned model. It engages only
  when the ledger spans at least ``FORECAST_MIN_HISTORY_DAYS`` days and
  ``FORECAST_MIN_HISTORY_MONTHS`` distinct calendar months; otherwise
  the factor is exactly 1.0 and the projection is unchanged.
- **Per-category daily burn** — average daily spend for one category
  over a trailing window (``category_daily_burn``).

Config values are read inside the methods so tests can monkeypatch
them. Stdlib only.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import config
from cba.common import connect_db, fmt_money
from cba.ledger import LedgerService


class ForecastService:
    """Project month-end spending from recent history.

    The core projection is a weighted moving average plus a linear
    trend. A simple historical seasonality index can scale it when
    enough history exists. The index is arithmetic on past monthly
    totals — a transparent seasonal multiplier, not ML.
    """

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

    def _seasonality_factor(
        self,
        year: int,
        month: int,
        base_currency: str,
        category: str | None,
    ) -> float:
        """Seasonal multiplier for calendar ``month`` (1-12).

        The index for calendar month m is (average expense in month m
        across the trailing ``FORECAST_SEASONALITY_MONTHS`` months) /
        (overall average monthly expense over that window). Applies only
        when the ledger covers at least ``FORECAST_MIN_HISTORY_MONTHS``
        distinct calendar months and ``FORECAST_MIN_HISTORY_DAYS`` days;
        otherwise returns exactly 1.0. Also 1.0 when there is no
        expense at all or no data for the target calendar month.
        """
        span = int(config.FORECAST_SEASONALITY_MONTHS)
        min_days = int(config.FORECAST_MIN_HISTORY_DAYS)
        min_months = int(config.FORECAST_MIN_HISTORY_MONTHS)

        conn = connect_db(self.db_path)
        try:
            row = conn.execute(
                "SELECT min(date), max(date),"
                " count(DISTINCT substr(date, 1, 7)) FROM transactions"
            ).fetchone()
        finally:
            conn.close()
        if row is None or row[0] is None or row[1] is None:
            return 1.0
        day_span = (date.fromisoformat(row[1]) - date.fromisoformat(row[0])).days
        if int(row[2]) < min_months or day_span < min_days:
            return 1.0

        window = self._past_months(year, month, span)
        totals = [
            self._monthly_expense(y, m, base_currency, category) for y, m in window
        ]
        overall = sum(totals) / len(totals) if totals else 0.0
        if overall <= 0:
            return 1.0
        sums: dict[int, float] = {}
        counts: dict[int, int] = {}
        for (_, m), total in zip(window, totals):
            if total > 0:
                sums[m] = sums.get(m, 0.0) + total
                counts[m] = counts.get(m, 0) + 1
        if month not in sums:
            return 1.0
        return float((sums[month] / counts[month]) / overall)

    def category_daily_burn(
        self,
        category: str,
        days: int | None = None,
        base_currency: str | None = None,
    ) -> dict:
        """Average daily spend for ``category`` over the trailing ``days``.

        ``days`` defaults to ``FORECAST_MONTHS * 30``. Amounts are
        converted to ``base_currency`` (default ``APP_CURRENCY``);
        transactions that fail FX conversion are skipped, consistent
        with ledger summaries.
        """
        base_currency = (base_currency or config.APP_CURRENCY).upper()
        days = int(config.FORECAST_MONTHS * 30) if days is None else int(days)
        days = max(days, 1)
        cutoff = (date.today() - timedelta(days=days)).isoformat()
        total = 0.0
        for r in self.ledger.list(kind="expense", category=category, limit=100000):
            if r["date"] < cutoff:
                continue
            try:
                total += float(
                    self.ledger.fx.convert(r["amount"], r["currency"], base_currency)
                )
            except Exception:
                continue
        total = round(total, 2)
        return {
            "category": (category or "").lower(),
            "days": days,
            "total": total,
            "daily_burn": round(total / days, 2),
            "base_currency": base_currency,
        }

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
        adds a linear trend adjustment, scales by the historical
        seasonality index for the target calendar month (exactly 1.0
        when history is too thin), and compares against the budget.
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

        # Seasonal adjustment: scale the plain projection by the
        # historical index for this calendar month. Exactly 1.0 when
        # history is too thin, so short-history projections are
        # bit-for-bit identical to the pre-seasonality formula.
        factor = self._seasonality_factor(year, month, base_currency, category)
        projected = max(projected * factor, 0.0)

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
            "seasonality_factor": round(factor, 3),
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
