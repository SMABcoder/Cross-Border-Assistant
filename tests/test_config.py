"""Tests for config.py: env overrides and sane defaults."""
import importlib
import os
import unittest

import config
from tests.helpers import TempDirTestCase


class TestFromEnv(unittest.TestCase):
    def setUp(self):
        self._saved = dict(os.environ)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._saved)

    def test_default_used_when_missing(self):
        os.environ.pop("CBA_FX_CACHE_TTL", None)
        self.assertEqual(config.from_env("FX_CACHE_TTL", 3600), 3600)

    def test_int_override(self):
        os.environ["CBA_FX_CACHE_TTL"] = "900"
        self.assertEqual(config.from_env("FX_CACHE_TTL", 3600), 900)

    def test_float_override(self):
        os.environ["CBA_BUDGET_WARN_PCT"] = "75.5"
        self.assertAlmostEqual(config.from_env("BUDGET_WARN_PCT", 80.0), 75.5)

    def test_bool_override(self):
        os.environ["CBA_LLM_ENABLED"] = "true"
        self.assertTrue(config.from_env("LLM_ENABLED", False))
        os.environ["CBA_LLM_ENABLED"] = "0"
        self.assertFalse(config.from_env("LLM_ENABLED", True))

    def test_str_override(self):
        os.environ["CBA_APP_CURRENCY"] = "CNY"
        self.assertEqual(config.from_env("APP_CURRENCY", "USD"), "CNY")

    def test_list_override(self):
        os.environ["CBA_SUPPORTED_CURRENCIES"] = "USD, CNY , EUR"
        self.assertEqual(
            config.from_env("SUPPORTED_CURRENCIES", ["USD"]),
            ["USD", "CNY", "EUR"],
        )


class TestModuleDefaults(TempDirTestCase):
    def test_defaults_sane(self):
        self.assertEqual(config.FX_CACHE_TTL, 3600)
        self.assertEqual(config.BUDGET_WARN_PCT, 80.0)
        self.assertEqual(config.BUDGET_BREACH_PCT, 100.0)
        self.assertEqual(config.ALERT_COOLDOWN, 86400)
        self.assertEqual(config.TUITION_REMINDER_THRESHOLDS, [30, 14, 7, 3, 1])
        self.assertIn("USD", config.SUPPORTED_CURRENCIES)
        self.assertIn("food", config.DEFAULT_CATEGORIES)
        self.assertFalse(config.LLM_ENABLED)

    def test_reload_picks_up_env(self):
        os.environ["CBA_FX_CACHE_TTL"] = "123"
        try:
            importlib.reload(config)
            self.assertEqual(config.FX_CACHE_TTL, 123)
        finally:
            del os.environ["CBA_FX_CACHE_TTL"]
            importlib.reload(config)
        self.assertEqual(config.FX_CACHE_TTL, 3600)

    def test_summary_keys(self):
        s = config.summary()
        for key in ("FX_CACHE_TTL", "APP_CURRENCY", "BUDGET_WARN_PCT",
                    "ALERT_COOLDOWN", "FORECAST_MONTHS"):
            self.assertIn(key, s)


if __name__ == "__main__":
    unittest.main()
