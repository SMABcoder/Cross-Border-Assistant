"""Tests for cba.assistant — intents, guides, i18n (EN + ZH), chat handlers."""
import unittest
from datetime import date

from cba.assistant import Assistant, i18n
from cba.assistant.guides import GuideBook
from cba.assistant.intents import IntentParser
from tests.helpers import TempDirTestCase


class TestIntentParser(unittest.TestCase):
    def setUp(self):
        self.p = IntentParser()

    def test_convert(self):
        i = self.p.parse("convert 100 USD to CNY")
        self.assertEqual(i.name, "convert")
        self.assertEqual(i.entities["amount"], 100.0)
        self.assertEqual(i.entities["from"], "USD")
        self.assertEqual(i.entities["to"], "CNY")

    def test_convert_arrow(self):
        i = self.p.parse("50 eur -> gbp")
        self.assertEqual(i.name, "convert")
        self.assertEqual(i.entities["from"], "EUR")

    def test_budget(self):
        self.assertEqual(self.p.parse("how is my budget?").name, "budget_status")

    def test_alert(self):
        i = self.p.parse("alert me when USD/CNY above 7.3")
        self.assertEqual(i.name, "set_rate_alert")
        self.assertEqual(i.entities["direction"], "above")
        self.assertEqual(i.entities["target"], 7.3)

    def test_alert_below(self):
        i = self.p.parse("notify me if usd-cny below 7.1")
        self.assertEqual(i.name, "set_rate_alert")
        self.assertEqual(i.entities["direction"], "below")

    def test_tuition(self):
        self.assertEqual(self.p.parse("when is my tuition due?").name, "tuition_due")

    def test_transfer(self):
        i = self.p.parse("cheapest way to send 500 USD to CNY")
        self.assertEqual(i.name, "transfer_advice")
        self.assertEqual(i.entities["amount"], 500.0)

    def test_guide(self):
        i = self.p.parse("guide me through paying tuition")
        self.assertEqual(i.name, "guide")
        self.assertEqual(i.entities["guide"], "pay_tuition")

    def test_guide_unknown_lists(self):
        i = self.p.parse("show me a guide")
        self.assertEqual(i.name, "guide")
        self.assertIsNone(i.entities["guide"])

    def test_forecast(self):
        self.assertEqual(self.p.parse("will I exceed my budget?").name, "forecast")

    def test_help(self):
        self.assertEqual(self.p.parse("hello").name, "help")

    def test_fallback_help(self):
        self.assertEqual(self.p.parse("blargle wibble").name, "help")

    def test_two_currencies_fallback(self):
        i = self.p.parse("USD and CNY")
        self.assertEqual(i.name, "convert")


class TestI18n(unittest.TestCase):
    def setUp(self):
        i18n.reset_cache()

    def test_en(self):
        self.assertIn("Cross Border Assistant", i18n.t("help_text", "en"))

    def test_zh(self):
        text = i18n.t("help_text", "zh")
        self.assertIn("跨境", text)

    def test_zh_converted(self):
        text = i18n.t("converted", "zh", amount="1", result="2",
                      rate="7.25", base="USD", quote="CNY")
        self.assertIn("汇率", text)

    def test_missing_key_falls_back_to_english(self):
        i18n.reset_cache()
        # Key exists in EN but we ask in an unknown language.
        self.assertEqual(i18n.t("help_text", "xx")[:2], i18n.t("help_text", "en")[:2])

    def test_missing_everywhere_returns_key(self):
        self.assertEqual(i18n.t("no_such_key_xyz", "en"), "no_such_key_xyz")

    def test_available_languages(self):
        langs = i18n.available_languages()
        self.assertIn("en", langs)
        self.assertIn("zh", langs)

    def test_format_args(self):
        text = i18n.t("alert_created", "en", pair="USD/CNY",
                      direction="above", target="7.3000")
        self.assertIn("USD/CNY", text)


class TestGuideBook(unittest.TestCase):
    def test_list_guides(self):
        guides = GuideBook().list_guides()
        refs = [g["ref"] for g in guides]
        for ref in ("pay_tuition", "send_money_home", "first_month_budget",
                    "credit_building"):
            self.assertIn(ref, refs)

    def test_render_numbered_steps(self):
        text = GuideBook().render("pay_tuition")
        self.assertIn("1.", text)
        self.assertIn("Tips", text)

    def test_render_missing_raises(self):
        with self.assertRaises(KeyError):
            GuideBook().get("nope")


class TestAssistantChat(TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.a = Assistant(db_path=self.db, fx=self.fx)

    def test_chat_convert(self):
        reply = self.a.chat("convert 100 USD to CNY")
        self.assertIn("725.00 CNY", reply)

    def test_chat_convert_zh(self):
        reply = self.a.chat("convert 100 USD to CNY", lang="zh")
        self.assertIn("汇率", reply)

    def test_chat_budget_empty(self):
        reply = self.a.chat("how is my budget?")
        self.assertIn("Budget", reply)

    def test_chat_budget_with_data(self):
        today = date.today()
        self.a.ledger.add("expense", 100, "USD", "food",
                          date_=today.replace(day=3).isoformat())
        self.a.budgets.set_budget(today.year, today.month, 1000, "USD")
        reply = self.a.chat("how is my budget?")
        self.assertIn("100.00", reply)

    def test_chat_alert(self):
        reply = self.a.chat("alert me when USD/CNY above 7.3")
        self.assertIn("Alert set", reply)

    def test_chat_tuition_none(self):
        reply = self.a.chat("when is my tuition due?")
        self.assertIn("No tuition bills", reply)

    def test_chat_tuition_with_bill(self):
        from datetime import timedelta

        due = (date.today() + timedelta(days=7)).isoformat()
        self.a.tuition.add("Tuition", 5000, "USD", due)
        reply = self.a.chat("when is my tuition due?")
        self.assertIn("5,000.00 USD", reply)

    def test_chat_transfer(self):
        reply = self.a.chat("cheapest way to send 500 USD to CNY")
        self.assertIn("Cheapest", reply)
        self.assertIn("Wise", reply)

    def test_chat_guide(self):
        reply = self.a.chat("guide me through paying tuition")
        self.assertIn("1.", reply)

    def test_chat_help(self):
        reply = self.a.chat("help")
        self.assertIn("convert", reply.lower())

    def test_llm_disabled_by_default(self):
        self.assertIsNone(self.a.llm)

    def test_numbers_come_from_services(self):
        # The assistant must not invent rates: reply rate matches FxService.
        rate = self.fx.get_rate("USD", "CNY")
        reply = self.a.chat("convert 1 USD to CNY")
        self.assertIn(f"{rate:.4f}", reply)


if __name__ == "__main__":
    unittest.main()
