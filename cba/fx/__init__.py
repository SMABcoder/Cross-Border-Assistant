"""Target-rate alerts with per-alert cooldown and pluggable notifiers."""
from __future__ import annotations

import json
import smtplib
import urllib.request
from email.message import EmailMessage
from pathlib import Path
from typing import Protocol

import config
from cba.common import connect_db, now_ts
from cba.fx import FxService

_SCHEMA = """
CREATE TABLE IF NOT EXISTS rate_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pair TEXT NOT NULL,
    base TEXT NOT NULL,
    quote TEXT NOT NULL,
    target REAL NOT NULL CHECK (target > 0),
    direction TEXT NOT NULL CHECK (direction IN ('above', 'below')),
    note TEXT NOT NULL DEFAULT '',
    created_at INTEGER NOT NULL,
    last_triggered_at INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS alert_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_id INTEGER NOT NULL REFERENCES rate_alerts(id),
    rate REAL NOT NULL,
    triggered_at INTEGER NOT NULL
);
"""


class Notifier(Protocol):
    def notify(self, subject: str, message: str) -> bool: ...


class ConsoleNotifier:
    def notify(self, subject: str, message: str) -> bool:
        print(f"[ALERT] {subject}\n{message}")
        return True


class EmailNotifier:
    """SMTP notifier; inactive (returns False) unless SMTP is configured."""

    def __init__(self) -> None:
        self.configured = bool(config.SMTP_HOST and config.SMTP_TO)

    def notify(self, subject: str, message: str) -> bool:
        if not self.configured:
            return False
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = config.SMTP_FROM or config.SMTP_USER
        msg["To"] = config.SMTP_TO
        msg.set_content(message)
        try:
            with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=15) as s:
                s.starttls()
                if config.SMTP_USER:
                    s.login(config.SMTP_USER, config.SMTP_PASSWORD)
                s.send_message(msg)
            return True
        except Exception:
            return False


class WebhookNotifier:
    def __init__(self, url: str) -> None:
        self.url = url

    def notify(self, subject: str, message: str) -> bool:
        payload = json.dumps({"subject": subject, "message": message}).encode()
        req = urllib.request.Request(
            self.url, data=payload, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=10):
                return True
        except Exception:
            return False


class AlertService:
    """Create rate alerts and evaluate them against live rates."""

    def __init__(
        self,
        db_path: str | Path | None = None,
        fx: FxService | None = None,
        notifiers: list[Notifier] | None = None,
    ) -> None:
        self.db_path = Path(db_path) if db_path else Path(config.DB_PATH)
        self.fx = fx or FxService()
        self.notifiers = notifiers if notifiers is not None else [ConsoleNotifier()]
        conn = connect_db(self.db_path)
        try:
            conn.executescript(_SCHEMA)
            conn.commit()
        finally:
            conn.close()

    # -- CRUD -------------------------------------------------------------
    def create(
        self, pair: str, target: float, direction: str, note: str = ""
    ) -> dict:
        direction = direction.lower()
        if direction not in ("above", "below"):
            raise ValueError("direction must be 'above' or 'below'")
        target = float(target)
        if target <= 0:
            raise ValueError("target must be positive")
        base, quote = self._split_pair(pair)
        conn = connect_db(self.db_path)
        try:
            cur = conn.execute(
                "INSERT INTO rate_alerts(pair, base, quote, target, direction,"
                " note, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (f"{base}/{quote}", base, quote, target, direction, note, now_ts()),
            )
            conn.commit()
            return self.get(cur.lastrowid)
        finally:
            conn.close()

    def get(self, alert_id: int) -> dict:
        conn = connect_db(self.db_path)
        try:
            row = conn.execute(
                "SELECT * FROM rate_alerts WHERE id = ?", (alert_id,)
            ).fetchone()
        finally:
            conn.close()
        if not row:
            raise KeyError(f"alert {alert_id} not found")
        return dict(row)

    def list(self, active_only: bool = True) -> list[dict]:
        conn = connect_db(self.db_path)
        try:
            q = "SELECT * FROM rate_alerts"
            if active_only:
                q += " WHERE active = 1"
            q += " ORDER BY id"
            return [dict(r) for r in conn.execute(q)]
        finally:
            conn.close()

    def deactivate(self, alert_id: int) -> None:
        conn = connect_db(self.db_path)
        try:
            conn.execute("UPDATE rate_alerts SET active = 0 WHERE id = ?", (alert_id,))
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _split_pair(pair: str) -> tuple[str, str]:
        pair = pair.upper().replace("-", "/").replace(" ", "")
        parts = pair.split("/")
        if len(parts) != 2 or not all(parts):
            raise ValueError("pair must look like USD/CNY")
        if parts[0] not in config.SUPPORTED_CURRENCIES or parts[1] not in config.SUPPORTED_CURRENCIES:
            raise ValueError(f"unsupported currency in pair {pair}")
        return parts[0], parts[1]

    # -- evaluation -------------------------------------------------------
    def check(self, cooldown: int | None = None) -> list[dict]:
        """Evaluate all active alerts; notify for triggered ones (cooldown-aware)."""
        cooldown = config.ALERT_COOLDOWN if cooldown is None else cooldown
        triggered: list[dict] = []
        for alert in self.list():
            if now_ts() - alert["last_triggered_at"] < cooldown:
                continue
            try:
                rate = self.fx.get_rate(alert["base"], alert["quote"])
            except Exception:
                continue  # rate unavailable; try next cycle
            hit = (
                rate >= alert["target"]
                if alert["direction"] == "above"
                else rate <= alert["target"]
            )
            if not hit:
                continue
            self._record_trigger(alert["id"], rate)
            subject = (
                f"Rate alert: {alert['pair']} {alert['direction']} {alert['target']}"
            )
            message = (
                f"{alert['pair']} is now {rate:.4f}, which is {alert['direction']}"
                f" your target of {alert['target']:.4f}."
                + (f" Note: {alert['note']}" if alert["note"] else "")
            )
            sent = [n.notify(subject, message) for n in self.notifiers]
            triggered.append(
                {**alert, "rate": rate, "notified": any(sent)}
            )
        return triggered

    def _record_trigger(self, alert_id: int, rate: float) -> None:
        conn = connect_db(self.db_path)
        try:
            conn.execute(
                "UPDATE rate_alerts SET last_triggered_at = ? WHERE id = ?",
                (now_ts(), alert_id),
            )
            conn.execute(
                "INSERT INTO alert_events(alert_id, rate, triggered_at)"
                " VALUES (?, ?, ?)",
                (alert_id, rate, now_ts()),
            )
            conn.commit()
        finally:
            conn.close()

    def events(self, limit: int = 50) -> list[dict]:
        conn = connect_db(self.db_path)
        try:
            return [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM alert_events ORDER BY triggered_at DESC LIMIT ?",
                    (limit,),
                )
            ]
        finally:
            conn.close()
