"""SAFE FX quota tracker (China's $50,000 annual individual FX quota).

Context: Chinese residents have an annual individual foreign-exchange
quota of USD 50,000 per calendar year for current-account transactions
(e.g. buying foreign currency at a bank for tuition, living expenses).
Transfers that exceed the quota cannot be processed by banks and are
rejected at settlement time.

This tracker is STRICTLY SELF-REPORTED: the user records transfers they
have already made through their own bank, and this module converts and
sums them against the annual quota. It never moves money, never talks
to a bank, and never claims to know the user's true quota usage.
Every user-facing string carries a reminder to cross-check with the
bank's official quota statement, which is the only authoritative
record.

Tunables are read from ``config`` inside the methods (never hardcoded)
so tests and deployers can adjust them without code changes:
``QUOTA_ANNUAL_USD``, ``QUOTA_WARN_PCT``, ``QUOTA_BREACH_PCT``.
"""
from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import config
from cba.common import connect_db, fmt_money, today_iso
from cba.fx import FxService

_SCHEMA = """
CREATE TABLE IF NOT EXISTS quota_transfers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    amount REAL NOT NULL CHECK(amount > 0),
    currency TEXT NOT NULL,
    amount_usd REAL NOT NULL,
    note TEXT NOT NULL DEFAULT ''
)
"""


def _row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "date": row["date"],
        "amount": row["amount"],
        "currency": row["currency"],
        "amount_usd": row["amount_usd"],
        "note": row["note"],
    }


class QuotaService:
    """Self-reported tracker for the annual individual FX quota.

    ``db_path`` may point at any sqlite database (tests use a temp
    copy). ``fx`` is an :class:`cba.fx.FxService`-compatible object with
    a ``convert(amount, base, quote)`` method.
    """

    def __init__(self, db_path=None, fx=None) -> None:
        self.db_path = Path(db_path) if db_path else Path(config.DB_PATH)
        self.fx = fx or FxService()

    def _db(self) -> sqlite3.Connection:
        conn = connect_db(self.db_path)
        conn.executescript(_SCHEMA)
        return conn

    # -- recording ----------------------------------------------------
    def record(self, date_, amount, currency, note="") -> dict:
        """Record one self-reported FX transfer made through the user's bank.

        The user manually records transfers they have already completed
        via their bank; this method only stores and converts them, and
        is not authoritative quota evidence. Cross-check totals against
        the bank's official quota statement.
        """
        currency = str(currency).upper()
        if currency not in config.SUPPORTED_CURRENCIES:
            raise ValueError(f"unsupported currency: {currency}")
        try:
            amount = float(amount)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"amount must be a number, got {amount!r}") from exc
        if amount <= 0:
            raise ValueError(f"amount must be > 0, got {amount}")
        date_ = date_ or today_iso()
        amount_usd = round(self.fx.convert(amount, currency, "USD"), 2)
        conn = self._db()
        try:
            cur = conn.execute(
                "INSERT INTO quota_transfers (date, amount, currency, amount_usd, note)"
                " VALUES (?, ?, ?, ?, ?)",
                (str(date_), amount, currency, amount_usd, note or ""),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM quota_transfers WHERE id = ?", (cur.lastrowid,)
            ).fetchone()
        finally:
            conn.close()
        return _row_to_dict(row)

    # -- usage / status -----------------------------------------------
    def usage(self, year: int | None = None) -> dict:
        """Sum recorded (self-reported) usage for a calendar year."""
        year = year or date.today().year
        limit = config.QUOTA_ANNUAL_USD
        conn = self._db()
        try:
            row = conn.execute(
                "SELECT COALESCE(SUM(amount_usd), 0) FROM quota_transfers"
                " WHERE date LIKE ?",
                (f"{year:04d}-%",),
            ).fetchone()
            used = float(row[0] or 0.0)
        finally:
            conn.close()
        used = round(used, 2)
        return {
            "year": year,
            "used_usd": used,
            "limit_usd": limit,
            "remaining_usd": round(limit - used, 2),
            "pct": round(used / limit * 100, 1) if limit else 0.0,
        }

    def status(self, year: int | None = None) -> dict:
        """Usage plus a verdict and human-readable warnings.

        Warnings are informational only: this tracker reflects only what
        the user recorded, so the bank's official statement is the final
        word on remaining quota.
        """
        info = self.usage(year)
        pct, limit, remaining = info["pct"], info["limit_usd"], info["remaining_usd"]
        warnings: list[str] = []
        if pct >= config.QUOTA_BREACH_PCT:
            verdict = "exceeded"
            warnings.append(
                f"You have used {pct}% of your {fmt_money(limit, 'USD')} annual FX quota —"
                " the recorded total has reached or passed the limit. Banks will reject"
                " further quota-based settlement. Cross-check with your bank's official"
                " quota statement before making any further transfers."
            )
        elif pct >= config.QUOTA_WARN_PCT:
            verdict = "warning"
            warnings.append(
                f"You have used {pct}% of your {fmt_money(limit, 'USD')} annual FX quota —"
                f" {fmt_money(remaining, 'USD')} remaining. Cross-check with your bank's"
                " official statement."
            )
        else:
            verdict = "ok"
        return {**info, "verdict": verdict, "warnings": warnings}

    # -- listing -------------------------------------------------------
    def list(self, year: int | None = None) -> list[dict]:
        """Recorded transfers, oldest first. ``year`` filters by calendar year."""
        year = year or date.today().year
        conn = self._db()
        try:
            rows = conn.execute(
                "SELECT * FROM quota_transfers WHERE date LIKE ?"
                " ORDER BY date ASC, id ASC",
                (f"{year:04d}-%",),
            ).fetchall()
        finally:
            conn.close()
        return [_row_to_dict(r) for r in rows]

    # -- presentation ---------------------------------------------------
    def format_status(self, status: dict) -> str:
        """Multi-line human report of a ``status()`` dict."""
        bar_len = 20
        filled = max(0, min(bar_len, int(status["pct"] / 100 * bar_len)))
        bar = "#" * filled + "-" * (bar_len - filled)
        lines = [
            f"FX quota usage — {status['year']} (self-reported)",
            f"Used:      {fmt_money(status['used_usd'], 'USD')} of"
            f" {fmt_money(status['limit_usd'], 'USD')} ({status['pct']}%)",
            f"Remaining: {fmt_money(status['remaining_usd'], 'USD')}",
            f"[{bar}]",
            f"Status:    {status['verdict'].upper()}",
        ]
        lines.extend(f"! {w}" for w in status["warnings"])
        lines.append(
            "Note: this tracker is self-reported — the bank's official quota"
            " statement is the authoritative record. Cross-check before acting."
        )
        return "\n".join(lines)
