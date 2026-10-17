"""Seed a demo student: income, ~15 expenses, budgets, tuition bill, alerts.

Usage: python scripts/seed_demo.py [--db PATH]
Idempotent-ish: safe to run on a fresh DB; on an existing DB it just adds more.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from cba.alerts import AlertService, ConsoleNotifier
from cba.budgets import BudgetService
from cba.common import connect_db
from cba.ledger import LedgerService
from cba.tuition import TuitionService


def seed(db_path: str, today: date | None = None) -> dict:
    today = today or date.today()
    ledger = LedgerService(db_path=db_path)
    budgets = BudgetService(db_path=db_path, ledger=ledger)
    tuition = TuitionService(db_path=db_path)
    alerts = AlertService(db_path=db_path, notifiers=[ConsoleNotifier()])

    stats = {"transactions": 0, "budgets": 0, "bills": 0, "alerts": 0}

    # Monthly stipend / part-time income (this month + 2 previous for forecast)
    for back in range(3):
        y = today.year + (today.month - 1 - back) // 12
        m = (today.month - 1 - back) % 12 + 1
        day = min(today.day, 5)
        ledger.add("income", 1800, "USD", "other", note="Monthly stipend",
                   date_=date(y, m, day).isoformat())
        stats["transactions"] += 1

    # ~15 realistic expenses this month
    expenses = [
        (650, "USD", "rent", "Monthly rent"),
        (320, "USD", "tuition", "Lab fee installment"),
        (85, "USD", "food", "Groceries week 1"),
        (92, "USD", "food", "Groceries week 2"),
        (78, "USD", "food", "Groceries week 3"),
        (45, "USD", "transport", "Metro card top-up"),
        (38, "USD", "transport", "Bus pass"),
        (120, "USD", "books", "Textbooks"),
        (35, "USD", "phone", "SIM plan"),
        (60, "USD", "health", "Pharmacy"),
        (25, "USD", "entertainment", "Cinema"),
        (18, "USD", "entertainment", "Streaming"),
        (44, "USD", "clothing", "Winter jacket (sale)"),
        (22, "USD", "food", "Late-night noodles"),
        (15, "USD", "other", "Printing & stationery"),
    ]
    for i, (amt, ccy, cat, note) in enumerate(expenses):
        day = min(1 + i, 28)
        ledger.add("expense", amt, ccy, cat, note=note,
                   date_=date(today.year, today.month, day).isoformat())
        stats["transactions"] += 1

    # A couple of prior-month expenses so forecasting has history
    for back in (1, 2):
        y = today.year + (today.month - 1 - back) // 12
        m = (today.month - 1 - back) % 12 + 1
        ledger.add("expense", 1250 - back * 60, "USD", "rent", note="Rent",
                   date_=date(y, m, 3).isoformat())
        ledger.add("expense", 380 - back * 25, "USD", "food", note="Food",
                   date_=date(y, m, 15).isoformat())
        stats["transactions"] += 2

    # Budgets: total + per-category
    budgets.set_budget(today.year, today.month, 2000, "USD")
    budgets.set_budget(today.year, today.month, 400, "USD", category="food")
    budgets.set_budget(today.year, today.month, 150, "USD", category="transport")
    budgets.set_budget(today.year, today.month, 100, "USD", category="entertainment")
    stats["budgets"] = 4

    # Tuition bill due in 14 days (hits a reminder threshold)
    due = today + timedelta(days=14)
    bill = tuition.add("Spring semester tuition", 5200, "USD",
                       due.isoformat(), payee="Example University")
    stats["bills"] = 1

    # Two rate alerts (targets chosen near plausible ranges)
    alerts.create("USD/CNY", 7.30, "above", note="Tuition payment coming up")
    alerts.create("USD/CNY", 7.10, "below", note="Good time to convert")
    stats["alerts"] = 2

    return {**stats, "bill_id": bill["id"]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=config.DB_PATH)
    args = ap.parse_args()
    stats = seed(args.db)
    print(f"Seeded demo data into {args.db}: {stats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
