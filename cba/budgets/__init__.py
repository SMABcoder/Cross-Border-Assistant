"""Tuition payment reminders with step-by-step guidance attached."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import config
from cba.common import connect_db, fmt_money, today_iso

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tuition_bills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    amount REAL NOT NULL CHECK (amount > 0),
    currency TEXT NOT NULL,
    due_date TEXT NOT NULL,
    payee TEXT NOT NULL DEFAULT '',
    guide_ref TEXT NOT NULL DEFAULT 'pay_tuition',
    paid INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tuition_notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bill_id INTEGER NOT NULL REFERENCES tuition_bills(id),
    kind TEXT NOT NULL,
    notified_on TEXT NOT NULL,
    UNIQUE (bill_id, kind, notified_on)
);
"""


class TuitionService:
    """CRUD tuition bills and compute due-date notifications."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path else Path(config.DB_PATH)
        conn = connect_db(self.db_path)
        try:
            conn.executescript(_SCHEMA)
            conn.commit()
        finally:
            conn.close()

    # -- CRUD -------------------------------------------------------------
    def add(
        self,
        name: str,
        amount: float,
        currency: str,
        due_date: str,
        payee: str = "",
        guide_ref: str = "pay_tuition",
    ) -> dict:
        amount = float(amount)
        if amount <= 0:
            raise ValueError("amount must be positive")
        date.fromisoformat(due_date)  # validate
        currency = currency.upper()
        if currency not in config.SUPPORTED_CURRENCIES:
            raise ValueError(f"unsupported currency {currency}")
        conn = connect_db(self.db_path)
        try:
            cur = conn.execute(
                "INSERT INTO tuition_bills(name, amount, currency, due_date,"
                " payee, guide_ref, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (name, amount, currency, due_date, payee, guide_ref, today_iso()),
            )
            conn.commit()
            return self.get(cur.lastrowid)
        finally:
            conn.close()

    def get(self, bill_id: int) -> dict:
        conn = connect_db(self.db_path)
        try:
            row = conn.execute(
                "SELECT * FROM tuition_bills WHERE id = ?", (bill_id,)
            ).fetchone()
        finally:
            conn.close()
        if not row:
            raise KeyError(f"bill {bill_id} not found")
        return dict(row)

    def list(self, include_paid: bool = False) -> list[dict]:
        conn = connect_db(self.db_path)
        try:
            q = "SELECT * FROM tuition_bills"
            if not include_paid:
                q += " WHERE paid = 0"
            q += " ORDER BY due_date"
            return [dict(r) for r in conn.execute(q)]
        finally:
            conn.close()

    def mark_paid(self, bill_id: int) -> None:
        conn = connect_db(self.db_path)
        try:
            conn.execute("UPDATE tuition_bills SET paid = 1 WHERE id = ?", (bill_id,))
            conn.commit()
        finally:
            conn.close()

    def delete(self, bill_id: int) -> None:
        conn = connect_db(self.db_path)
        try:
            conn.execute("DELETE FROM tuition_notifications WHERE bill_id = ?", (bill_id,))
            conn.execute("DELETE FROM tuition_bills WHERE id = ?", (bill_id,))
            conn.commit()
        finally:
            conn.close()

    # -- notifications ----------------------------------------------------
    def due_notifications(
        self,
        today: date | None = None,
        thresholds: list[int] | None = None,
    ) -> list[dict]:
        """Build the notification list for unpaid bills.

        Fires at ``thresholds`` days-before, plus due-today and overdue.
        Each notification carries a ``kind`` so a caller can de-duplicate
        (kind + date is unique per bill in the DB).
        """
        today = today or date.today()
        thresholds = (
            list(config.TUITION_REMINDER_THRESHOLDS)
            if thresholds is None
            else list(thresholds)
        )
        notifications: list[dict] = []
        for bill in self.list():
            due = date.fromisoformat(bill["due_date"])
            days_left = (due - today).days
            kind: str | None = None
            if days_left < 0:
                kind = "overdue"
            elif days_left == 0:
                kind = "due_today"
            elif days_left in thresholds:
                kind = f"due_in_{days_left}"
            if kind is None:
                continue
            notifications.append(
                {
                    "bill": bill,
                    "kind": kind,
                    "days_left": days_left,
                    "message": self._message(bill, kind, days_left),
                    "guide_ref": bill["guide_ref"] or "pay_tuition",
                }
            )
        return notifications

    @staticmethod
    def _message(bill: dict, kind: str, days_left: int) -> str:
        amount = fmt_money(bill["amount"], bill["currency"])
        who = f" to {bill['payee']}" if bill["payee"] else ""
        if kind == "overdue":
            return (
                f"OVERDUE: {bill['name']} of {amount}{who} was due"
                f" {abs(days_left)} day(s) ago ({bill['due_date']}). Pay now to"
                " avoid late fees."
            )
        if kind == "due_today":
            return f"DUE TODAY: {bill['name']} of {amount}{who}. Complete payment today."
        return (
            f"Reminder: {bill['name']} of {amount}{who} is due in"
            f" {days_left} day(s) ({bill['due_date']})."
        )

    def record_sent(self, bill_id: int, kind: str, notified_on: str | None = None) -> bool:
        """Mark a notification as sent; returns False if already recorded."""
        notified_on = notified_on or today_iso()
        conn = connect_db(self.db_path)
        try:
            cur = conn.execute(
                "INSERT OR IGNORE INTO tuition_notifications(bill_id, kind, notified_on)"
                " VALUES (?, ?, ?)",
                (bill_id, kind, notified_on),
            )
            conn.commit()
            return cur.rowcount == 1
        finally:
            conn.close()

    def pending_notifications(
        self, today: date | None = None, thresholds: list[int] | None = None
    ) -> list[dict]:
        """Notifications that have not been recorded as sent yet."""
        pending = []
        for n in self.due_notifications(today=today, thresholds=thresholds):
            if self.record_sent(n["bill"]["id"], n["kind"]):
                pending.append(n)
        return pending
