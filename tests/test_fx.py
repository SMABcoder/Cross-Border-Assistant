"""Tests for cba.fx — providers, caching chain, conversion, trends."""
import time
import unittest
from pathlib import Path

from cba import fx
from cba.fx import (
    CachedProvider,
    FallbackTableProvider,
    FxError,
    FxService,
    SimpleApiProvider,
)
from tests.helpers import FakeProvider, FailingProvider, TempDirTestCase, fake_fx, write_json


class TestSimpleApiProvider(unittest.TestCase):
    def test_uses_config_endpoint(self):
        p = SimpleApiProvider()
        self.assertIn("open.er-api.com", p.api_base)


class TestFakeChain(TempDirTestCase):
    def test_get_rate(self):
        self.assertAlmostEqual(self.fx.get_rate("USD", "CNY"), 7.25)

    def test_same_currency_is_one(self):
        self.assertEqual(self.fx.get_rate("USD", "USD"), 1.0)

    def test_convert(self):
        self.assertAlmostEqual(self.fx.convert(100, "USD", "CNY"), 725.0)

    def test_unknown_pair_raises(self):
        with self.assertRaises(FxError):
            self.fx.get_rate("USD", "XXX")

    def test_live_called_then_cached(self):
        provider = FakeProvider()
        svc = fake_fx(self.tmp, provider)
        svc.get_rate("USD", "CNY")
        svc.get_rate("USD", "CNY")
        # Second lookup served from cache: only one live call.
        self.assertEqual(provider.calls, ["USD"])

    def test_cache_ttl_zero_always_refetches(self):
        provider = FakeProvider()
        svc = FxService(live=provider, cache_path=str(Path(self.tmp) / "c.json"))
        svc.cached.ttl = 0
        svc.get_rate("USD", "CNY")
        svc.get_rate("USD", "CNY")
        self.assertEqual(len(provider.calls), 2)

    def test_offline_uses_stale_cache(self):
        svc = fake_fx(self.tmp, FakeProvider())
        svc.get_rate("USD", "CNY")  # populate cache
        svc.cached.inner = FailingProvider()
        # TTL still fresh -> cached value returned despite dead inner provider.
        self.assertAlmostEqual(svc.get_rate("USD", "CNY"), 7.25)

    def test_offline_falls_back_to_table(self):
        data_dir = Path(self.tmp) / "data"
        data_dir.mkdir()
        write_json(data_dir / "fallback_rates.json",
                   {"USD": {"USD": 1.0, "CNY": 7.0}})
        svc = FxService(
            live=FailingProvider(),
            cache_path=str(Path(self.tmp) / "c.json"),
            fallback_path=str(data_dir / "fallback_rates.json"),
        )
        svc.cached.ttl = 0  # force live attempt which fails
        self.assertAlmostEqual(svc.get_rate("USD", "CNY"), 7.0)

    def test_no_provider_anywhere_raises(self):
        data_dir = Path(self.tmp) / "data"
        data_dir.mkdir()
        svc = FxService(
            live=FailingProvider(),
            cache_path=str(Path(self.tmp) / "c.json"),
            fallback_path=str(data_dir / "fallback_rates.json"),
        )
        svc.cached.ttl = 0
        with self.assertRaises(FxError):
            svc.get_rate("USD", "CNY")


class TestTrend(TempDirTestCase):
    def test_trend_from_history(self):
        svc = fake_fx(self.tmp, FakeProvider())
        svc.cached.store_snapshot("USD", {"USD": 1.0, "CNY": 7.00})
        svc.cached.store_snapshot("USD", {"USD": 1.0, "CNY": 7.25})
        info = svc.trend("USD", "CNY", days=30)
        self.assertEqual(info["pair"], "USD/CNY")
        self.assertEqual(info["direction"], "up")
        self.assertGreater(info["change_pct"], 0)

    def test_trend_flat_when_no_history(self):
        info = self.fx.trend("USD", "CNY", days=7)
        self.assertEqual(info["direction"], "flat")
        self.assertEqual(info["change_pct"], 0.0)


class TestFallbackProvider(TempDirTestCase):
    def test_missing_file_raises_fxerror(self):
        p = FallbackTableProvider(path=str(Path(self.tmp) / "nope.json"))
        with self.assertRaises(FxError):
            p.get_table("USD")

    def test_real_fallback_file_loads(self):
        repo_root = Path(fx.__file__).resolve().parent.parent.parent
        p = FallbackTableProvider(path=str(repo_root / "data" / "fallback_rates.json"))
        table = p.get_table("USD")
        self.assertGreater(table["CNY"], 0)


if __name__ == "__main__":
    unittest.main()
