"""Cron-friendly one-shot alert loop.

Evaluates all active rate alerts, sends notifications through every
configured notifier, and prints a short summary. Safe to run every
5-15 minutes; per-alert cooldown prevents duplicate spam.

Usage:
    python scripts/check_alerts.py
    CBA_WEBHOOK_URL=... python scripts/check_alerts.py   # enables webhook notifier
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cba.alerts import AlertService, ConsoleNotifier, EmailNotifier, WebhookNotifier


def build_notifiers() -> list:
    notifiers: list = [ConsoleNotifier()]
    email = EmailNotifier()
    if email.configured:
        notifiers.append(email)
    webhook_url = os.environ.get("CBA_WEBHOOK_URL", "")
    if webhook_url:
        notifiers.append(WebhookNotifier(webhook_url))
    return notifiers


def main() -> int:
    service = AlertService(notifiers=build_notifiers())
    triggered = service.check()
    print(f"checked {len(service.list())} alert(s), {len(triggered)} triggered")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
