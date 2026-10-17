"""Tests for cba.credit — checklist tracker, guide, intent, assistant, CLI wiring."""
import unittest

from cba.assistant import Assistant
from cba.assistant.guides import GuideBook
from cba.assistant.intents import IntentParser
from cba.credit import CreditService
from tests.helpers import TempDirTestCase


class TestCreditService(TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.credit = CreditService(db_path=self.db)

    def test_defaults_seeded(self):
        items = self.credit.items()
        self.assertGreaterEqual(len(items), 6)
        keys = [i["key"] for i in items]
        self.assertIn("secured_card", keys)
        self.assertTrue(all(not i["done"] for i in items))

    def test_complete_and_uncomplete(self):
        self.credit.complete("secured_card")
        items = {i["key"]: i for i in self.credit.items()}
        self.assertTrue(items["secured_card"]["done"])
        self.credit.uncomplete("secured_card")
        items = {i["key"]: i for i in self.credit.items()}
        self.assertFalse(items["secured_card"]["done"])

    def test_unknown_key_raises(self):
        with self.assertRaises(KeyError):
            self.credit.complete("nope")

    def test_progress(self):
        self.credit.complete("secured_card")
        self.credit.complete("bank_account")
        prog = self.credit.progress()
        self.assertEqual(prog["done"], 2)
        self.assertEqual(prog["total"], len(self.credit.items()))
        self.assertAlmostEqual(prog["pct"], 2 / prog["total"] * 100, places=1)
        self.assertEqual(len(prog["remaining"]), prog["total"] - 2)

    def test_progress_empty(self):
        prog = self.credit.progress()
        self.assertEqual(prog["done"], 0)
        self.assertEqual(prog["pct"], 0.0)

    def test_reset(self):
        self.credit.complete("secured_card")
        self.credit.reset()
        self.assertEqual(self.credit.progress()["done"], 0)

    def test_seed_idempotent(self):
        CreditService(db_path=self.db)  # second init must not duplicate
        self.assertEqual(len(self.credit.items()), len(CreditService(db_path=self.db).items()))

    def test_items_come_from_data_file(self):
        # Checklist labels are data-driven, not hardcoded.
        import json
        from pathlib import Path

        repo_root = Path(__file__).resolve().parent.parent
        payload = json.load(open(repo_root / "data" / "credit_checklist.json"))
        file_keys = {i["key"] for i in payload["items"]}
        service_keys = {i["key"] for i in self.credit.items()}
        self.assertEqual(file_keys, service_keys)


class TestCreditGuide(unittest.TestCase):
    def test_guide_exists_and_has_steps(self):
        guide = GuideBook().get("credit_building")
        self.assertGreaterEqual(len(guide["steps"]), 6)

    def test_guide_mentions_key_topics(self):
        text = GuideBook().render("credit_building").lower()
        for phrase in ("secured", "rent", "predatory"):
            self.assertIn(phrase, text)


class TestCreditIntent(unittest.TestCase):
    def setUp(self):
        self.parser = IntentParser()

    def test_build_credit(self):
        self.assertEqual(self.parser.parse("how do I build credit?").name, "credit_advice")

    def test_credit_score(self):
        self.assertEqual(self.parser.parse("what is a credit score").name, "credit_advice")

    def test_chinese(self):
        self.assertEqual(self.parser.parse("怎么建立信用记录").name, "credit_advice")

    def test_tuition_still_routes_to_tuition(self):
        self.assertEqual(self.parser.parse("when is my tuition due?").name, "tuition_due")

    def test_intent_in_catalog(self):
        from cba.assistant.intents import INTENTS

        self.assertIn("credit_advice", INTENTS)


class TestCreditAssistant(TempDirTestCase):
    def test_chat_returns_guide_and_progress(self):
        assistant = Assistant(db_path=self.db, fx=self.fx)
        reply = assistant.chat("how do I build credit?")
        self.assertIn("0/", reply)  # fresh checklist progress
        self.assertIn("secured", reply.lower())

    def test_chat_after_completing_item(self):
        assistant = Assistant(db_path=self.db, fx=self.fx)
        assistant.credit.complete("secured_card")
        reply = assistant.chat("credit advice")
        self.assertIn("1/", reply)

    def test_help_mentions_credit(self):
        assistant = Assistant(db_path=self.db, fx=self.fx)
        reply = assistant.chat("help")
        self.assertIn("credit", reply.lower())


if __name__ == "__main__":
    unittest.main()
