"""Tests for cba.importer — CSV statement import with auto-detected columns."""
import csv
import unittest
from pathlib import Path

import config
from cba.common import ProductionGatedError
from cba.importer import (
    HEADER_ALIASES,
    INCOME_KEYWORDS,
    CsvImporter,
    ImportError,
    InertOpenBankingAdapter,
    OpenBankingAdapter,
    _parse_category_rules,
)
from cba.ledger import LedgerService
from tests.helpers import TempDirTestCase


class TestImporter(TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.ledger = LedgerService(db_path=self.db, fx=self.fx)
        self.importer = CsvImporter(ledger=self.ledger)

    def write_csv(self, name, header, rows, encoding="utf-8"):
        path = str(Path(self.tmp) / name)
        with open(path, "w", newline="", encoding=encoding) as f:
            writer = csv.writer(f)
            writer.writerow(header)
            writer.writerows(rows)
        return path

    # -- header detection -------------------------------------------------
    def test_auto_detect_clean_headers(self):
        path = self.write_csv(
            "clean.csv",
            ["Date", "Description", "Amount", "Currency"],
            [
                ["2026-10-01", "MCDONALDS #123", "-25.00", "USD"],
                ["2026-10-02", "UBER TRIP", "-8.50", "USD"],
            ],
        )
        result = self.importer.preview(path)
        self.assertEqual(result["total"], 2)
        self.assertFalse(result["writes"])
        self.assertEqual(result["rows"][0]["date"], "2026-10-01")
        self.assertEqual(result["rows"][0]["kind"], "expense")
        self.assertEqual(result["rows"][0]["amount"], 25.00)
        self.assertEqual(result["rows"][1]["currency"], "USD")

    def test_auto_detect_variant_headers(self):
        path = self.write_csv(
            "variant.csv",
            ["posted", "memo", "value", "ccy"],
            [["01/10/2026", "GROCERY STORE", "-40.00", "USD"]],
        )
        detected = self.importer.detect_columns(["posted", "memo", "value", "ccy"])
        self.assertEqual(detected["date"], "posted")
        self.assertEqual(detected["description"], "memo")
        self.assertEqual(detected["amount"], "value")
        self.assertEqual(detected["currency"], "ccy")
        result = self.importer.preview(path)
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["rows"][0]["date"], "2026-10-01")

    def test_explicit_column_overrides_detection(self):
        path = self.write_csv(
            "override.csv",
            ["Date", "Memo", "Narration", "Amount"],
            [["2026-10-01", "AUTO memo", "MANUAL narration", "10.00"]],
        )
        # auto-detect would pick "Memo" for description; explicit wins
        result = self.importer.preview(path, desc_col="Narration")
        self.assertEqual(result["rows"][0]["description"], "MANUAL narration")

    def test_auto_detect_disabled_requires_explicit_columns(self):
        config.IMPORT_AUTO_DETECT_HEADERS = False
        self.addCleanup(setattr, config, "IMPORT_AUTO_DETECT_HEADERS", True)
        path = self.write_csv(
            "noauto.csv",
            ["Date", "Description", "Amount"],
            [["2026-10-01", "COFFEE", "5.00"]],
        )
        with self.assertRaises(ImportError):
            self.importer.preview(path)
        result = self.importer.preview(
            path, date_col="Date", desc_col="Description", amount_col="Amount"
        )
        self.assertEqual(result["total"], 1)

    def test_header_aliases_cover_expected_synonyms(self):
        self.assertIn("posted", HEADER_ALIASES["date"])
        self.assertIn("narration", HEADER_ALIASES["description"])
        self.assertIn("paid in", HEADER_ALIASES["credit"])

    # -- categorization ---------------------------------------------------
    def test_categorize_known_descriptions(self):
        self.assertEqual(self.importer.categorize("MCDONALDS #123"), "food")
        self.assertEqual(self.importer.categorize("UBER TRIP"), "transport")

    def test_categorize_unknown_is_other(self):
        self.assertEqual(self.importer.categorize("SOME RANDOM THING"), "other")

    def test_parse_category_rules_format(self):
        rules = _parse_category_rules()
        self.assertTrue(rules)
        self.assertEqual(rules[0][0], "food")
        self.assertIn("mcdonald", rules[0][1])

    # -- dry-run / writes ---------------------------------------------------
    def test_preview_writes_nothing(self):
        path = self.write_csv(
            "dry.csv",
            ["Date", "Description", "Amount", "Currency"],
            [["2026-10-01", "MCDONALDS #123", "-25.00", "USD"]],
        )
        before = len(self.ledger.list(limit=1000))
        result = self.importer.preview(path)
        after = len(self.ledger.list(limit=1000))
        self.assertEqual(before, after)
        self.assertFalse(result["writes"])

    def test_import_file_writes_rows_and_returns_ids(self):
        path = self.write_csv(
            "apply.csv",
            ["Date", "Description", "Amount", "Currency"],
            [
                ["2026-10-01", "MCDONALDS #123", "-25.00", "USD"],
                ["2026-10-02", "SALARY PAYROLL", "2000.00", "USD"],
            ],
        )
        result = self.importer.import_file(path, dry_run=False)
        self.assertEqual(result["imported"], 2)
        self.assertEqual(len(result["ids"]), 2)
        stored = {r["id"]: r for r in self.ledger.list(limit=1000)}
        self.assertEqual(set(result["ids"]), set(stored))
        by_kind = {r["id"]: r["kind"] for r in stored.values()}
        self.assertEqual(by_kind[result["ids"][0]], "expense")
        self.assertEqual(by_kind[result["ids"][1]], "income")
        self.assertEqual(stored[result["ids"][0]]["note"], "MCDONALDS #123")
        self.assertEqual(stored[result["ids"][0]]["category"], "food")
        self.assertEqual(result["by_category"], {"food": 1, "other": 1})

    # -- amount / date edge cases -------------------------------------------
    def test_parenthesized_negative_is_expense(self):
        path = self.write_csv(
            "paren.csv",
            ["Date", "Description", "Amount"],
            [["2026-10-01", "BOOKSTORE", "(25.00)"]],
        )
        result = self.importer.preview(path)
        self.assertEqual(result["rows"][0]["kind"], "expense")
        self.assertEqual(result["rows"][0]["amount"], 25.00)

    def test_bad_date_and_blank_rows_are_skipped(self):
        path = self.write_csv(
            "skipped.csv",
            ["Date", "Description", "Amount"],
            [
                ["2026-10-01", "COFFEE", "5.00"],
                ["not-a-date", "BROKEN", "9.99"],
                ["", "", ""],
            ],
        )
        result = self.importer.preview(path)
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["skipped"], 2)

    def test_unsupported_currency_raises(self):
        path = self.write_csv(
            "ccy.csv",
            ["Date", "Description", "Amount"],
            [["2026-10-01", "COFFEE", "5.00"]],
        )
        with self.assertRaises(ImportError):
            self.importer.preview(path, default_currency="XXX")

    def test_single_column_positive_income_heuristic(self):
        path = self.write_csv(
            "income.csv",
            ["Date", "Description", "Amount"],
            [
                ["2026-10-01", "SALARY PAYROLL", "5000.00"],
                ["2026-10-02", "GROCERY STORE", "40.00"],
            ],
        )
        result = self.importer.preview(path)
        kinds = {r["description"]: r["kind"] for r in result["rows"]}
        self.assertEqual(kinds["SALARY PAYROLL"], "income")
        self.assertEqual(kinds["GROCERY STORE"], "expense")
        self.assertIn("salary", INCOME_KEYWORDS)

    def test_debit_credit_pair(self):
        path = self.write_csv(
            "pair.csv",
            ["Date", "Description", "Debit", "Credit"],
            [
                ["2026-10-01", "COFFEE", "3.50", ""],
                ["2026-10-02", "SALARY DEPOSIT", "", "2000"],
                ["2026-10-03", "MIXED", "10", "25"],
            ],
        )
        result = self.importer.preview(path)
        self.assertEqual(result["total"], 3)
        rows = {r["description"]: r for r in result["rows"]}
        self.assertEqual(rows["COFFEE"]["kind"], "expense")
        self.assertEqual(rows["COFFEE"]["amount"], 3.50)
        self.assertEqual(rows["COFFEE"]["category"], "food")
        self.assertEqual(rows["SALARY DEPOSIT"]["kind"], "income")
        self.assertEqual(rows["SALARY DEPOSIT"]["amount"], 2000.00)
        self.assertEqual(rows["MIXED"]["kind"], "income")
        self.assertEqual(rows["MIXED"]["amount"], 15.00)

    def test_bom_header_tolerated(self):
        path = self.write_csv(
            "bom.csv",
            ["Date", "Description", "Amount"],
            [["2026-10-01", "COFFEE", "5.00"]],
            encoding="utf-8-sig",
        )
        result = self.importer.preview(path)
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["rows"][0]["date"], "2026-10-01")

    def test_missing_header_raises(self):
        path = str(Path(self.tmp) / "empty.csv")
        Path(path).write_text("", encoding="utf-8")
        with self.assertRaises(ImportError):
            self.importer.preview(path)

    # -- inert open-banking adapter -------------------------------------------
    def test_inert_adapter_fetch_raises_production_gated(self):
        adapter = InertOpenBankingAdapter()
        self.assertIsInstance(adapter, OpenBankingAdapter)
        with self.assertRaises(ProductionGatedError) as ctx:
            adapter.fetch_transactions("acct-1", "2026-10-01")
        self.assertIn("production-gated", str(ctx.exception).lower())


if __name__ == "__main__":
    unittest.main()
