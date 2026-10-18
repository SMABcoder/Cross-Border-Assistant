"""Monthly budgets: totals + per-category limits, warnings and burn-down pace."""
from __future__ import annotations

import calendar
from datetime import date
from pathlib import Path

import config
from cba.common import connect_db, fmt_money, month_key
from cba.ledger import LedgerService

_SCHEMA = """
CREATE TABLE IF NOT EXISTS budgets (
    month TEXT NOT NULL,
    category TEXT NOT NULL,
    limit_amount REAL NOT NULL CHECK (limit_amount > 0),
    currency TEXT NOT NULL,
    PRIMARY KEY (month, category)
);
"""


class BudgetService:
    """Set monthly budgets and report status with warnings and pace projection."""

    TOTAL_KEY = "__total__"

    def __init__(
        self,
        db_path: str | Path | None = None,
        ledger: LedgerService | None = None,
    ) -> None:
        self.db_path = Path(db_path) if db_path else Path(config.DB_PATH)
        self.ledger = ledger or LedgerService(db_path=self.db_path)
        conn = connect_db(self.db_path)
        try:
            conn.executescript(_SCHEMA)
            conn.commit()
        finally:
            conn.close()

    # -- writes -----------------------------------------------------------
    def set_budget(
        self,
        year: int,
        month: int,
        limit_amount: float,
        currency: str | None = None,
        category: str | None = None,
    ) -> None:
        """Set the overall monthly budget, or a per-category limit."""
        limit_amount = float(limit_amount)
        if limit_amount <= 0:
            raise ValueError("budget limit must be positive")
        currency = (currency or config.APP_CURRENCY).upper()
        key = self.TOTAL_KEY if category is None else category.lower()
        conn = connect_db(self.db_path)
        try:
            conn.execute(
                "INSERT OR REPLACE INTO budgets(month, category, limit_amount, currency)"
                " VALUES (?, ?, ?, ?)",
                (month_key(year, month), key, limit_amount, currency),
            )
            conn.commit()
        finally:
            conn.close()

    def get_budgets(self, year: int, month: int) -> dict[str, dict]:
        conn = connect_db(self.db_path)
        try:
            rows = conn.execute(
                "SELECT category, limit_amount, currency FROM budgets WHERE month = ?",
                (month_key(year, month),),
            ).fetchall()
        finally:
            conn.close()
        return {
            r["category"]: {
                "limit": float(r["limit_amount"]),
                "currency": r["currency"],
            }
            for r in rows
        }

    # -- status -----------------------------------------------------------
    def status(
        self,
        year: int,
        month: int,
        base_currency: str | None = None,
        today: date | None = None,
    ) -> dict:
        base_currency = (base_currency or config.APP_CURRENCY).upper()
        budgets = self.get_budgets(year, month)
        summary = self.ledger.summary(year, month, base_currency)
        spent = summary["expense"]

        total = budgets.get(self.TOTAL_KEY)
        result: dict = {
            "month": month_key(year, month),
            "base_currency": base_currency,
            "warnings": [],
        }

        # Overall budget ----------------------------------------------
        if total:
            limit_base = self.ledger.fx.convert(
                total["limit"], total["currency"], base_currency
            )
            pct = spent / limit_base * 100 if limit_base else 0.0
            result["total"] = {
                "limit": round(limit_base, 2),
                "spent": round(spent, 2),
                "remaining": round(limit_base - spent, 2),
                "pct": round(pct, 1),
            }
            if pct >= config.BUDGET_BREACH_PCT:
                result["warnings"].append(
                    f"Over budget: spent {fmt_money(spent, base_currency)}"
                    f" of {fmt_money(limit_base, base_currency)} ({pct:.0f}%)."
                )
            elif pct >= config.BUDGET_WARN_PCT:
                result["warnings"].append(
                    f"Warning: {pct:.0f}% of monthly budget used"
                    f" ({fmt_money(spent, base_currency)} of"
                    f" {fmt_money(limit_base, base_currency)})."
                )
            # Burn-down pace -------------------------------------------
            today = today or date.today()
            days_in_month = calendar.monthrange(year, month)[1]
            elapsed = max(today.day, 1) if (today.year, today.month) == (year, month) else days_in_month
            projected = spent / elapsed * days_in_month if elapsed else spent
            result["pace"] = {
                "day": today.day if (today.year, today.month) == (year, month) else days_in_month,
                "days_in_month": days_in_month,
                "projected_month_end": round(projected, 2),
                "message": (
                    f"At this pace you will spend {fmt_money(projected, base_currency)}"
                    f" by month-end (budget {fmt_money(limit_base, base_currency)})."
                ),
            }
        else:
            result["total"] = {"limit": None, "spent": round(spent, 2),
                               "remaining": None, "pct": None}

        # Per-category limits ------------------------------------------
        per_category = {}
        for cat, b in budgets.items():
            if cat == self.TOTAL_KEY:
                continue
            limit_base = self.ledger.fx.convert(b["limit"], b["currency"], base_currency)
            cat_spent = summary["by_category"].get(cat, 0.0)
            pct = cat_spent / limit_base * 100 if limit_base else 0.0
            per_category[cat] = {
                "limit": round(limit_base, 2),
                "spent": round(cat_spent, 2),
                "pct": round(pct, 1),
            }
            if pct >= config.BUDGET_BREACH_PCT:
                result["warnings"].append(
                    f"'{cat}' over limit: {pct:.0f}% used."
                )
            elif pct >= config.BUDGET_WARN_PCT:
                result["warnings"].append(
                    f"'{cat}' at {pct:.0f}% of its limit."
                )
        result["per_category"] = per_category
        return result
