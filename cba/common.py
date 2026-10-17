"""Shared helpers for the Cross Border Assistant package."""
from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path

import config


def connect_db(path: str | Path | None = None) -> sqlite3.Connection:
    """Open the application sqlite database, creating parent dirs if needed."""
    db_path = Path(path) if path else Path(config.DB_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def today_iso() -> str:
    return date.today().isoformat()


def now_ts() -> int:
    return int(datetime.now().timestamp())


def month_key(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def fmt_money(amount: float, currency: str) -> str:
    """Format an amount like '1,250.50 USD'."""
    sign = "-" if amount < 0 else ""
    return f"{sign}{abs(amount):,.2f} {currency}"
