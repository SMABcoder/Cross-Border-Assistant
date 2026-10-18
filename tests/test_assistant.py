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


class TestNewIntents(unittest.TestCase):
    def setUp(self):
        self.p = IntentParser()

    def test_optimize_should_i_pay(self):
        i = self.p.parse("should I pay my tuition now?")
        self.assertEqual(i.name, "optimize")

    def test_optimize_keyword(self):
        self.assertEqual(self.p.parse("optimize my tuition FX").name, "optimize")

    def test_optimize_zh(self):
        self.assertEqual(self.p.parse("现在交学费时机好吗？").name, "optimize")

    def test_quota_en(self):
        self.assertEqual(self.p.parse("check my FX quota").name, "quota")

    def test_quota_zh(self):
        self.assertEqual(self.p.parse("我的外汇额度用了多少").name, "quota")

    def test_import_advice_with_path(self):
        i = self.p.parse("import my bank statement jan.csv")
        self.assertEqual(i.name, "import_advice")
        self.assertEqual(i.entities["path"], "jan.csv")

    def test_import_advice_no_path(self):
        i = self.p.parse("can I import a bank statement?")
        self.assertEqual(i.name, "import_advice")
        self.assertIsNone(i.entities["path"])

    def test_credit_card_statement_not_import(self):
        # "credit card statement" has no import/csv/bank-statement keyword.
        self.assertEqual(self.p.parse("credit card statement").name, "credit_advice")

    def test_serve_web(self):
        self.assertEqual(self.p.parse("open the web ui").name, "serve_web")

    def test_optimize_does_not_swallow_tuition_due(self):
        self.assertEqual(self.p.parse("when is my tuition due?").name, "tuition_due")

    def test_budget_50000_alone_not_quota(self):
        self.assertNotEqual(self.p.parse("50000").name, "quota")


class TestNewHandlers(TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.a = Assistant(db_path=self.db, fx=self.fx)

    def test_chat_optimize_empty(self):
        reply = self.a.chat("should I pay my tuition now?")
        self.assertIn("No unpaid tuition bills", reply)
        self.assertIn("💡", reply)

    def test_chat_quota_empty(self):
        reply = self.a.chat("check my quota")
        self.assertIn("50,000", reply)
        self.assertIn("💡", reply)

    def test_chat_import_help(self):
        reply = self.a.chat("help me import my statement")
        self.assertIn("CSV", reply)

    def test_chat_import_preview(self):
        import csv
        import os

        path = os.path.join(self.tmp, "stmt.csv")
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["Date", "Description", "Amount"])
            w.writerow(["2026-10-01", "Noodle shop", "-12.50"])
            w.writerow(["2026-10-02", "Bookstore", "-30.00"])
        reply = self.a.chat("import %s" % path)
        self.assertIn("Preview", reply)
        self.assertIn("Nothing was written", reply)
        # Dry run: nothing reaches the ledger.
        today = date.today()
        self.assertEqual(
            self.a.ledger.summary(today.year, today.month)["expense"], 0.0
        )

    def test_chat_serve_web(self):
        reply = self.a.chat("open the web ui")
        self.assertIn("8000", reply)

    def test_chat_chips_on_convert(self):
        reply = self.a.chat("convert 100 USD to CNY")
        self.assertIn("💡", reply)
        self.assertIn("set a rate alert", reply)

    def test_multiturn_budget_category(self):
        today = date.today()
        self.a.budgets.set_budget(today.year, today.month, 1000, "USD")
        self.a.budgets.set_budget(today.year, today.month, 500, "USD", category="food")
        self.a.ledger.add("expense", 50, "USD", "food", date_=today.isoformat())
        self.a.chat("how is my budget?")
        reply = self.a.chat("and for food?")
        self.assertIn("food", reply.lower())
        self.assertIn("50.00", reply)

    def test_multiturn_foreign_followup_isolated(self):
        # "for USD to CNY" is a conversion, not a category follow-up.
        today = date.today()
        self.a.budgets.set_budget(today.year, today.month, 1000, "USD")
        self.a.chat("how is my budget?")
        reply = self.a.chat("convert 1 USD to CNY")
        self.assertIn("CNY", reply)

    def test_context_history_trimmed(self):
        import config as _config

        old = _config.ASSISTANT_MAX_CONTEXT_TURNS
        _config.ASSISTANT_MAX_CONTEXT_TURNS = 2
        try:
            self.a.chat("hello")
            self.a.chat("hello")
            self.a.chat("hello")
            self.assertLessEqual(len(self.a._ctx["history"]), 2)
        finally:
            _config.ASSISTANT_MAX_CONTEXT_TURNS = old


class TestDefaultLLMWiring(TempDirTestCase):
    def setUp(self):
        super().setUp()
        import config as _config

        self._config = _config
        self._old_enabled = _config.LLM_ENABLED
        self._old_key = _config.LLM_API_KEY

    def tearDown(self):
        self._config.LLM_ENABLED = self._old_enabled
        self._config.LLM_API_KEY = self._old_key

    def test_llm_auto_constructed_with_key(self):
        from cba.assistant.llm import OpenAICompatibleProvider

        self._config.LLM_ENABLED = True
        self._config.LLM_API_KEY = "test-key"
        a = Assistant(db_path=self.db, fx=self.fx)
        self.assertIsInstance(a.llm, OpenAICompatibleProvider)

    def test_llm_none_without_key(self):
        self._config.LLM_ENABLED = True
        self._config.LLM_API_KEY = ""
        a = Assistant(db_path=self.db, fx=self.fx)
        self.assertIsNone(a.llm)

    def test_llm_none_when_disabled(self):
        self._config.LLM_ENABLED = False
        self._config.LLM_API_KEY = "test-key"
        a = Assistant(db_path=self.db, fx=self.fx)
        self.assertIsNone(a.llm)


class TestNewI18n(unittest.TestCase):
    def setUp(self):
        i18n.reset_cache()

    def test_zh_suggest_optimize_is_translated(self):
        self.assertNotEqual(i18n.t("suggest_optimize", "zh"), "suggest_optimize")
        self.assertIn("学费", i18n.t("suggest_optimize", "zh"))

    def test_en_serve_help(self):
        self.assertIn("8000", i18n.t("serve_help", "en"))

    def test_chips_prefix_zh(self):
        self.assertIn("试试", i18n.t("chips_prefix", "zh"))

    def test_all_chip_keys_translated(self):
        keys = ("suggest_optimize", "suggest_quota", "suggest_transfer",
                "suggest_budget", "suggest_credit", "chips_prefix",
                "import_help", "serve_help", "import_preview_header",
                "import_preview_row", "budget_category_line")
        for key in keys:
            self.assertNotEqual(i18n.t(key, "zh"), key, key)
            self.assertNotEqual(i18n.t(key, "en"), key, key)


if __name__ == "__main__":
    unittest.main()
