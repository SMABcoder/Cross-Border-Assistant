"""Manual income/expense ledger backed by stdlib sqlite3."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import config
from cba.common import connect_db, fmt_money, today_iso
from cba.fx import FxService

_SCHEMA = """
CREATE TABLE IF NOT EXISTS categories (
    name TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('income', 'expense', 'both'))
);
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('income', 'expense')),
    amount REAL NOT NULL CHECK (amount > 0),
    currency TEXT NOT NULL,
    category TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_tx_date ON transactions(date);
CREATE INDEX IF NOT EXISTS idx_tx_kind ON transactions(kind);
CREATE INDEX IF NOT EXISTS idx_tx_cat ON transactions(category);
"""


class LedgerService:
    """Record income/expenses and produce monthly summaries in a base currency."""

    def __init__(
        self,
        db_path: str | Path | None = None,
        fx: FxService | None = None,
    ) -> None:
        self.db_path = Path(db_path) if db_path else Path(config.DB_PATH)
        self.fx = fx or FxService()
        self._init_db()

    def _init_db(self) -> None:
        conn = connect_db(self.db_path)
        try:
            conn.executescript(_SCHEMA)
            for name in config.DEFAULT_CATEGORIES:
                conn.execute(
                    "INSERT OR IGNORE INTO categories(name, kind) VALUES (?, 'both')",
                    (name,),
                )
            conn.commit()
        finally:
            conn.close()

    # -- writes -----------------------------------------------------------
    def add(
        self,
        kind: str,
        amount: float,
        currency: str,
        category: str,
        note: str = "",
        date_: str | None = None,
    ) -> int:
        kind = kind.lower()
        if kind not in ("income", "expense"):
            raise ValueError("kind must be 'income' or 'expense'")
        amount = float(amount)
        if amount <= 0:
            raise ValueError("amount must be positive")
        currency = currency.upper()
        if currency not in config.SUPPORTED_CURRENCIES:
            raise ValueError(f"unsupported currency {currency}")
        conn = connect_db(self.db_path)
        try:
            cur = conn.execute(
                "INSERT INTO transactions(date, kind, amount, currency, category, note)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (date_ or today_iso(), kind, amount, currency, category.lower(), note),
            )
            conn.commit()
            return int(cur.lastrowid)
        finally:
            conn.close()

    # -- reads ------------------------------------------------------------
    def list(
        self,
        kind: str | None = None,
        category: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        query = "SELECT * FROM transactions WHERE 1=1"
        params: list = []
        if kind:
            query += " AND kind = ?"
            params.append(kind.lower())
        if category:
            query += " AND category = ?"
            params.append(category.lower())
        query += " ORDER BY date DESC, id DESC LIMIT ?"
        params.append(limit)
        conn = connect_db(self.db_path)
        try:
            return [dict(r) for r in conn.execute(query, params)]
        finally:
            conn.close()

    def summary(self, year: int, month: int, base_currency: str | None = None) -> dict:
        """Monthly totals normalized to ``base_currency`` (default APP_CURRENCY)."""
        base_currency = (base_currency or config.APP_CURRENCY).upper()
        start = date(year, month, 1)
        end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
        conn = connect_db(self.db_path)
        try:
            rows = conn.execute(
                "SELECT kind, amount, currency, category FROM transactions"
                " WHERE date >= ? AND date < ?",
                (start.isoformat(), end.isoformat()),
            ).fetchall()
        finally:
            conn.close()

        income = expense = 0.0
        by_category: dict[str, float] = {}
        skipped: list[dict] = []
        for r in rows:
            try:
                amt = self.fx.convert(r["amount"], r["currency"], base_currency)
            except Exception:
                skipped.append(dict(r))
                continue
            if r["kind"] == "income":
                income += amt
            else:
                expense += amt
                by_category[r["category"]] = by_category.get(r["category"], 0.0) + amt

        return {
            "month": f"{year:04d}-{month:02d}",
            "base_currency": base_currency,
            "income": round(income, 2),
            "expense": round(expense, 2),
            "net": round(income - expense, 2),
            "by_category": {k: round(v, 2) for k, v in sorted(by_category.items())},
            "skipped_fx_failures": len(skipped),
            "formatted": {
                "income": fmt_money(income, base_currency),
                "expense": fmt_money(expense, base_currency),
                "net": fmt_money(income - expense, base_currency),
            },
        }
