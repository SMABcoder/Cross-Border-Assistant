"""Tests for cba.alerts — CRUD, triggering, cooldown, notifiers."""
import unittest

from cba.alerts import (
    AlertService,
    ConsoleNotifier,
    EmailNotifier,
    WebhookNotifier,
)
from tests.helpers import FakeProvider, FailingProvider, TempDirTestCase, fake_fx

class Recorder:
    def __init__(self):
        self.sent = []

    def notify(self, subject, message):
        self.sent.append((subject, message))
        return True


class TestAlerts(TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.recorder = Recorder()
        self.alerts = AlertService(db_path=self.db, fx=self.fx,
                                  notifiers=[self.recorder])

    def test_create(self):
        a = self.alerts.create("USD/CNY", 7.3, "above")
        self.assertEqual(a["pair"], "USD/CNY")
        self.assertEqual(a["direction"], "above")

    def test_create_bad_direction(self):
        with self.assertRaises(ValueError):
            self.alerts.create("USD/CNY", 7.3, "sideways")

    def test_create_bad_pair(self):
        with self.assertRaises(ValueError):
            self.alerts.create("USDCNY", 7.3, "above")

    def test_create_unsupported_currency(self):
        with self.assertRaises(ValueError):
            self.alerts.create("USD/XXX", 7.3, "above")

    def test_trigger_above(self):
        # Fake USD->CNY = 7.25, so target 7.2 above triggers.
        self.alerts.create("USD/CNY", 7.2, "above")
        triggered = self.alerts.check(cooldown=0)
        self.assertEqual(len(triggered), 1)
        self.assertEqual(len(self.recorder.sent), 1)
        self.assertIn("USD/CNY", self.recorder.sent[0][0])

    def test_trigger_below(self):
        self.alerts.create("USD/CNY", 7.3, "below")
        triggered = self.alerts.check(cooldown=0)
        self.assertEqual(len(triggered), 1)

    def test_no_trigger_when_not_hit(self):
        self.alerts.create("USD/CNY", 7.3, "above")
        triggered = self.alerts.check(cooldown=0)
        self.assertEqual(triggered, [])
        self.assertEqual(self.recorder.sent, [])

    def test_cooldown_suppresses_duplicates(self):
        self.alerts.create("USD/CNY", 7.2, "above")
        first = self.alerts.check()  # default cooldown 86400
        second = self.alerts.check()
        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])

    def test_cooldown_zero_allows_retrigger(self):
        self.alerts.create("USD/CNY", 7.2, "above")
        self.alerts.check(cooldown=0)
        again = self.alerts.check(cooldown=0)
        self.assertEqual(len(again), 1)

    def test_event_recorded(self):
        a = self.alerts.create("USD/CNY", 7.2, "above")
        self.alerts.check(cooldown=0)
        events = self.alerts.events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["alert_id"], a["id"])

    def test_deactivate(self):
        a = self.alerts.create("USD/CNY", 7.2, "above")
        self.alerts.deactivate(a["id"])
        self.assertEqual(self.alerts.list(), [])
        self.assertEqual(len(self.alerts.check(cooldown=0)), 0)

    def test_rate_unavailable_skips_gracefully(self):
        from pathlib import Path

        from cba.fx import FxService

        dead_fx = FxService(
            live=FailingProvider(),
            cache_path=str(Path(self.tmp) / "dead_cache.json"),
            fallback_path=str(Path(self.tmp) / "no_fallback.json"),
        )
        dead_fx.cached.ttl = 0  # force live attempt which fails
        dead = AlertService(db_path=self.db, fx=dead_fx,
                            notifiers=[self.recorder])
        dead.create("USD/CNY", 7.2, "above")
        self.assertEqual(dead.check(cooldown=0), [])

    def test_rate_change_triggers(self):
        # Raise the fake rate above the target.
        provider = FakeProvider(rates={"USD": {"USD": 1.0, "CNY": 7.5}})
        svc = AlertService(db_path=self.db, fx=fake_fx(self.tmp, provider),
                           notifiers=[self.recorder])
        svc.create("USD/CNY", 7.4, "above")
        self.assertEqual(len(svc.check(cooldown=0)), 1)


class TestNotifiers(TempDirTestCase):
    def test_console_returns_true(self):
        self.assertTrue(ConsoleNotifier().notify("s", "m"))

    def test_email_inactive_without_config(self):
        self.assertFalse(EmailNotifier().notify("s", "m"))

    def test_webhook_failure_returns_false(self):
        n = WebhookNotifier("http://127.0.0.1:1/nope")
        self.assertFalse(n.notify("s", "m"))


if __name__ == "__main__":
    unittest.main()
