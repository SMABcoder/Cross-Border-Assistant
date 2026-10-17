"""Tests for cba.tuition — bills CRUD and due-date notifications."""
import unittest
from datetime import date, timedelta

from cba.tuition import TuitionService
from tests.helpers import TempDirTestCase


class TestTuition(TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.svc = TuitionService(db_path=self.db)
        self.today = date(2026, 10, 18)

    def _add(self, days_out, **kw):
        due = (self.today + timedelta(days=days_out)).isoformat()
        params = dict(name="Tuition", amount=5000, currency="USD", due_date=due)
        params.update(kw)
        return self.svc.add(**params)

    def test_add_and_get(self):
        b = self._add(14, payee="Example University")
        got = self.svc.get(b["id"])
        self.assertEqual(got["payee"], "Example University")
        self.assertEqual(got["amount"], 5000.0)

    def test_add_rejects_bad_amount(self):
        with self.assertRaises(ValueError):
            self._add(14, amount=0)

    def test_add_rejects_bad_date(self):
        with self.assertRaises(ValueError):
            self._add(14, due_date="not-a-date")

    def test_add_rejects_bad_currency(self):
        with self.assertRaises(ValueError):
            self._add(14, currency="XXX")

    def test_list_excludes_paid(self):
        b = self._add(14)
        self.svc.mark_paid(b["id"])
        self.assertEqual(self.svc.list(), [])
        self.assertEqual(len(self.svc.list(include_paid=True)), 1)

    def test_delete(self):
        b = self._add(14)
        self.svc.delete(b["id"])
        with self.assertRaises(KeyError):
            self.svc.get(b["id"])

    def test_reminder_at_each_threshold(self):
        for days in (30, 14, 7, 3, 1):
            self._add(days, name=f"Bill {days}")
        notes = self.svc.due_notifications(today=self.today)
        kinds = sorted(n["kind"] for n in notes)
        self.assertEqual(kinds, ["due_in_1", "due_in_14", "due_in_3",
                                 "due_in_30", "due_in_7"])

    def test_no_reminder_between_thresholds(self):
        self._add(10)
        self.assertEqual(self.svc.due_notifications(today=self.today), [])

    def test_due_today(self):
        self._add(0)
        notes = self.svc.due_notifications(today=self.today)
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["kind"], "due_today")
        self.assertIn("DUE TODAY", notes[0]["message"])

    def test_overdue(self):
        self._add(-5)
        notes = self.svc.due_notifications(today=self.today)
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["kind"], "overdue")
        self.assertIn("OVERDUE", notes[0]["message"])

    def test_custom_thresholds(self):
        self._add(10)
        notes = self.svc.due_notifications(today=self.today, thresholds=[10])
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["kind"], "due_in_10")

    def test_notification_carries_guide(self):
        self._add(7, guide_ref="pay_tuition")
        notes = self.svc.due_notifications(today=self.today)
        self.assertEqual(notes[0]["guide_ref"], "pay_tuition")

    def test_paid_bills_never_notify(self):
        b = self._add(7)
        self.svc.mark_paid(b["id"])
        self.assertEqual(self.svc.due_notifications(today=self.today), [])

    def test_record_sent_dedupes(self):
        b = self._add(7)
        self.assertTrue(self.svc.record_sent(b["id"], "due_in_7"))
        self.assertFalse(self.svc.record_sent(b["id"], "due_in_7"))

    def test_pending_notifications_drains_once(self):
        self._add(7)
        first = self.svc.pending_notifications(today=self.today)
        second = self.svc.pending_notifications(today=self.today)
        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])


if __name__ == "__main__":
    unittest.main()
