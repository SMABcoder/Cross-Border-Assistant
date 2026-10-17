"""Tests for cba.transfers — estimates, comparison, fee-table-driven pricing."""
import unittest
from pathlib import Path

from cba.transfers import FeeError, FeeEstimator, load_methods
from tests.helpers import TempDirTestCase, write_json


METHODS = [
    {"method": "Cheap", "fixed_fee": 1.0, "pct_fee": 0.0, "fx_margin_bps": 0,
     "eta_hours": 1, "min_amount": 1, "max_amount": 1000, "safety_notes": ""},
    {"method": "Pricey", "fixed_fee": 10.0, "pct_fee": 1.0, "fx_margin_bps": 300,
     "eta_hours": 48, "min_amount": 1, "max_amount": 1000, "safety_notes": ""},
]


class TestTransfers(TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.est = FeeEstimator(methods=METHODS, fx=self.fx)

    def test_load_methods_from_real_table(self):
        repo_root = Path(__file__).resolve().parent.parent
        methods = load_methods(repo_root / "data" / "fees.json")
        self.assertGreaterEqual(len(methods), 3)
        names = [m["method"] for m in methods]
        self.assertIn("Wise", names)

    def test_estimate_math(self):
        # 100 USD via Cheap: fee 1.0, no margin, rate 7.25 -> receive 99*7.25.
        r = self.est.estimate(100, "USD", "CNY", "Cheap")
        self.assertAlmostEqual(r["fee"], 1.0)
        self.assertAlmostEqual(r["receive"], 99 * 7.25)
        self.assertAlmostEqual(r["total_cost"], 1.0)
        self.assertEqual(r["eta"], "1h")

    def test_estimate_pct_and_margin(self):
        # 100 USD via Pricey: fee 10 + 1% = 11; margin 300bps -> rate 7.25*0.97.
        r = self.est.estimate(100, "USD", "CNY", "Pricey")
        self.assertAlmostEqual(r["fee"], 11.0)
        self.assertAlmostEqual(r["applied_rate"], 7.25 * 0.97, places=4)
        self.assertAlmostEqual(r["receive"], 89 * 7.25 * 0.97, places=1)
        self.assertGreater(r["total_cost"], 11.0)  # margin cost included

    def test_unknown_method(self):
        with self.assertRaises(FeeError):
            self.est.estimate(100, "USD", "CNY", "Nope")

    def test_amount_outside_limits(self):
        with self.assertRaises(FeeError):
            self.est.estimate(5000, "USD", "CNY", "Cheap")

    def test_nonpositive_amount(self):
        with self.assertRaises(ValueError):
            self.est.estimate(0, "USD", "CNY", "Cheap")

    def test_compare_ranks_cheapest_first(self):
        ranked = self.est.compare(100, "USD", "CNY")
        self.assertEqual(ranked[0]["method"], "Cheap")
        self.assertEqual(ranked[-1]["method"], "Pricey")

    def test_compare_skips_out_of_range_methods(self):
        ranked = self.est.compare(5000, "USD", "CNY")
        self.assertEqual(ranked, [])

    def test_fees_come_from_file_not_code(self):
        # Rewrite the fee table -> estimate must follow the file.
        path = write_json(
            Path(self.tmp) / "fees.json",
            {"methods": [
                {"method": "Custom", "fixed_fee": 42.0, "pct_fee": 0.0,
                 "fx_margin_bps": 0, "eta_hours": 2,
                 "min_amount": 1, "max_amount": 999999, "safety_notes": ""},
            ]},
        )
        est = FeeEstimator(fees_path=path, fx=self.fx)
        r = est.estimate(100, "USD", "CNY", "Custom")
        self.assertAlmostEqual(r["fee"], 42.0)

    def test_safety_brief(self):
        brief = FeeEstimator.safety_brief()
        for phrase in ("licensed", "ants moving", "receipt", "scam"):
            self.assertIn(phrase, brief.lower())

    def test_estimate_summary_readable(self):
        r = self.est.estimate(100, "USD", "CNY", "Cheap")
        self.assertIn("Cheap", r["summary"])
        self.assertIn("CNY", r["summary"])


if __name__ == "__main__":
    unittest.main()
