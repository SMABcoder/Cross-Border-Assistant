"""Central configuration for the Cross Border Assistant.

Every tunable in the codebase is read from here. Every value can be
overridden with an environment variable using the ``CBA_`` prefix,
e.g. ``CBA_FX_CACHE_TTL=900``.

No secrets are stored here. Paths resolve relative to this file so the
project works from any working directory.
"""
from __future__ import annotations

import os
from pathlib import Path


def from_env(name: str, default: str | int | float | list[str], *, type_: type = None):
    """Read an env var with the CBA_ prefix, falling back to ``default``.

    ``type_`` is inferred from the type of ``default`` when omitted.
    Comma-separated strings are converted to lists for list defaults.
    """
    if type_ is None:
        type_ = type(default)
    raw = os.environ.get("CBA_" + name)
    if raw is None:
        return default
    if type_ is bool:
        return raw.strip().lower() in ("1", "true", "yes", "on")
    if type_ is int:
        return int(raw)
    if type_ is float:
        return float(raw)
    if type_ is list:
        return [part.strip() for part in raw.split(",") if part.strip()]
    return raw


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = from_env("DATA_DIR", str(PROJECT_ROOT / "data"))
DB_PATH = from_env("DB_PATH", str(PROJECT_ROOT / "cba.db"))
FX_CACHE_PATH = from_env("FX_CACHE_PATH", str(PROJECT_ROOT / "fx_cache.json"))

# ---------------------------------------------------------------------------
# FX / exchange rates
# ---------------------------------------------------------------------------
FX_API_BASE = from_env(
    "FX_API_BASE", "https://open.er-api.com/v6/latest"
)
FX_CACHE_TTL = from_env("FX_CACHE_TTL", 3600)          # seconds
FX_TIMEOUT = from_env("FX_TIMEOUT", 10)               # seconds
FX_TREND_DAYS = from_env("FX_TREND_DAYS", 7)
APP_CURRENCY = from_env("APP_CURRENCY", "USD")         # base currency default
SUPPORTED_CURRENCIES = from_env(
    "SUPPORTED_CURRENCIES", ["USD", "CNY", "EUR", "GBP", "PKR", "INR", "JPY", "SGD"]
)

# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------
DEFAULT_CATEGORIES = from_env(
    "DEFAULT_CATEGORIES",
    [
        "tuition", "rent", "food", "transport", "books", "health",
        "phone", "clothing", "entertainment", "other",
    ],
)

# ---------------------------------------------------------------------------
# Budgets
# ---------------------------------------------------------------------------
BUDGET_WARN_PCT = from_env("BUDGET_WARN_PCT", 80.0)    # warn at 80% of limit
BUDGET_BREACH_PCT = from_env("BUDGET_BREACH_PCT", 100.0)

# ---------------------------------------------------------------------------
# Rate alerts
# ---------------------------------------------------------------------------
ALERT_COOLDOWN = from_env("ALERT_COOLDOWN", 86400)     # seconds per alert

# ---------------------------------------------------------------------------
# Tuition reminders
# ---------------------------------------------------------------------------
TUITION_REMINDER_THRESHOLDS = from_env(
    "TUITION_REMINDER_THRESHOLDS", [30, 14, 7, 3, 1]
)

# ---------------------------------------------------------------------------
# Forecasting
# ---------------------------------------------------------------------------
FORECAST_MONTHS = from_env("FORECAST_MONTHS", 3)       # history window
FORECAST_RECENT_WEIGHT = from_env("FORECAST_RECENT_WEIGHT", 0.5)

# ---------------------------------------------------------------------------
# Transfers
# ---------------------------------------------------------------------------
FEES_PATH = from_env("FEES_PATH", "")

# ---------------------------------------------------------------------------
# SMTP (email notifier is inert unless these are set)
# ---------------------------------------------------------------------------
SMTP_HOST = from_env("SMTP_HOST", "")
SMTP_PORT = from_env("SMTP_PORT", 587)
SMTP_USER = from_env("SMTP_USER", "")
SMTP_PASSWORD = from_env("SMTP_PASSWORD", "")
SMTP_FROM = from_env("SMTP_FROM", "")
SMTP_TO = from_env("SMTP_TO", "")

# ---------------------------------------------------------------------------
# Assistant
# ---------------------------------------------------------------------------
DEFAULT_LANG = from_env("DEFAULT_LANG", "en")
LLM_ENABLED = from_env("LLM_ENABLED", False)          # LLMProvider stub off by default


def summary() -> dict:
    """Return the effective configuration (for debugging / tests)."""
    return {
        "PROJECT_ROOT": str(PROJECT_ROOT),
        "DATA_DIR": str(DATA_DIR),
        "DB_PATH": str(DB_PATH),
        "FX_CACHE_TTL": FX_CACHE_TTL,
        "APP_CURRENCY": APP_CURRENCY,
        "SUPPORTED_CURRENCIES": SUPPORTED_CURRENCIES,
        "BUDGET_WARN_PCT": BUDGET_WARN_PCT,
        "BUDGET_BREACH_PCT": BUDGET_BREACH_PCT,
        "ALERT_COOLDOWN": ALERT_COOLDOWN,
        "TUITION_REMINDER_THRESHOLDS": TUITION_REMINDER_THRESHOLDS,
        "FORECAST_MONTHS": FORECAST_MONTHS,
        "LLM_ENABLED": LLM_ENABLED,
    }
