"""CSV bank-statement importer with auto-detected columns and rule-based categorization.

Reads an exported bank/credit-card statement (CSV), maps its columns to a
canonical schema, assigns a category to every row from configurable keyword
rules, and — only when asked — writes the rows into the ledger.

Column detection is best-effort: the importer matches header names against
:const:`HEADER_ALIASES` (case-insensitive). Explicit ``*_col`` arguments
always override detection, and detection can be switched off entirely via
``config.IMPORT_AUTO_DETECT_HEADERS`` (``CBA_IMPORT_AUTO_DETECT_HEADERS``).

Amount/kind semantics
---------------------
* **Debit/credit column pair** (e.g. ``Debit,Credit``): ``net = credit - debit``;
  ``kind`` is ``"expense"`` when ``net <= 0`` else ``"income"``, ``amount`` is
  ``abs(net)``. Empty cells count as 0.
* **Single amount column**: the sign is ambiguous across banks, so the importer
  uses a documented heuristic — negative amounts are expenses; positive
  amounts are also treated as expenses (typical card statement) **unless** the
  description contains one of :const:`INCOME_KEYWORDS` (``salary``, ``payroll``,
  ``refund``, ``deposit``, ``transfer in``), in which case the row is income.
  This is a heuristic: verify the preview before applying.
* Rows that net to exactly 0.00 are skipped (nothing to record) and counted
  in ``"skipped"``. Blank lines and unparseable rows are skipped, never fatal.

Live bank feeds are deliberately out of scope here: see
:class:`OpenBankingAdapter` / :class:`InertOpenBankingAdapter` for where a
licensed provider integration would plug in.

Stdlib only. All tunables come from ``config`` and are read inside methods so
tests can monkeypatch them.
"""
from __future__ import annotations

import csv
import re
from datetime import datetime
from typing import Protocol, runtime_checkable

import config
from cba.common import ProductionGatedError
from cba.ledger import LedgerService

__all__ = [
    "ImportError",
    "HEADER_ALIASES",
    "INCOME_KEYWORDS",
    "CsvImporter",
    "OpenBankingAdapter",
    "InertOpenBankingAdapter",
]


class ImportError(Exception):
    """Raised when a CSV statement (or a required piece of it) cannot be imported."""


#: Canonical column name -> accepted header spellings (matched case-insensitively).
HEADER_ALIASES: dict[str, set[str]] = {
    "date": {"date", "posted", "transaction date", "value date", "booking date"},
    "description": {"description", "memo", "details", "narration", "merchant", "payee"},
    "amount": {"amount", "value", "total"},
    "currency": {"currency", "ccy"},
    "debit": {"debit", "withdrawal", "paid out"},
    "credit": {"credit", "deposit", "paid in"},
}

#: Substring keywords that flip a *positive* single-column amount to income.
#: Heuristic only — see the module docstring.
INCOME_KEYWORDS: tuple[str, ...] = (
    "salary",
    "payroll",
    "refund",
    "deposit",
    "transfer in",
)


def _parse_category_rules() -> list[tuple[str, list[str]]]:
    """Parse ``config.IMPORT_CATEGORY_RULES`` into ``[(category, [keywords])]``.

    Expected format: ``"cat:kw1|kw2;cat2:kw3"``. Malformed chunks are ignored.
    Read inside the function so tests can monkeypatch ``config``.
    """
    rules: list[tuple[str, list[str]]] = []
    for chunk in str(config.IMPORT_CATEGORY_RULES).split(";"):
        chunk = chunk.strip()
        if not chunk or ":" not in chunk:
            continue
        category, _, keywords = chunk.partition(":")
        category = category.strip()
        kws = [kw.strip().lower() for kw in keywords.split("|") if kw.strip()]
        if category and kws:
            rules.append((category, kws))
    return rules


class CsvImporter:
    """Import CSV bank statements into the ledger."""

    def __init__(
        self,
        db_path: str | None = None,
        ledger: LedgerService | None = None,
    ) -> None:
        self.ledger = ledger if ledger is not None else LedgerService(db_path=db_path)

    # -- column detection -------------------------------------------------
    def detect_columns(self, header: list[str]) -> dict[str, str]:
        """Map canonical column names to the actual header names in ``header``.

        Matching is case-insensitive against :const:`HEADER_ALIASES`;
        unrecognized columns are ignored. First match wins per canonical name.
        """
        found: dict[str, str] = {}
        for canonical, aliases in HEADER_ALIASES.items():
            for name in header:
                if name is not None and name.strip().lower() in aliases:
                    found[canonical] = name
                    break
        return found

    # -- parsing ----------------------------------------------------------
    def parse_date(self, raw) -> str:
        """Parse ``raw`` using ``config.IMPORT_DATE_FORMATS``; return ISO ``YYYY-MM-DD``."""
        text = str(raw).strip() if raw is not None else ""
        for fmt in config.IMPORT_DATE_FORMATS:
            try:
                return datetime.strptime(text, fmt).date().isoformat()
            except (ValueError, TypeError):
                continue
        raise ImportError(f"unparseable date: {raw!r}")

    def parse_amount(self, raw) -> float:
        """Parse a money string to float.

        Strips whitespace, currency symbols/letters and thousands commas;
        ``"(1,234.56)"`` counts as negative. A lone comma is treated as a
        decimal comma (``"12,50"`` -> ``12.50``). Raises :class:`ImportError`
        on anything else.
        """
        text = str(raw).strip() if raw is not None else ""
        if not text:
            raise ImportError(f"unparseable amount: {raw!r}")
        negative = False
        if text.startswith("(") and text.endswith(")") and len(text) > 2:
            negative = True
            text = text[1:-1].strip()
        cleaned = re.sub(r"[^\d.,+\-]", "", text)
        if not re.search(r"\d", cleaned):
            raise ImportError(f"unparseable amount: {raw!r}")
        if "." in cleaned and "," in cleaned:
            cleaned = cleaned.replace(",", "")  # "1,234.56" -> thousands separator
        elif "," in cleaned:
            cleaned = cleaned.replace(",", ".")  # "12,50" -> decimal comma
        try:
            value = float(cleaned)
        except ValueError:
            raise ImportError(f"unparseable amount: {raw!r}") from None
        return -abs(value) if negative else value

    def categorize(self, description) -> str:
        """Return the first category whose keyword appears in ``description`` (substring).

        Rules come from ``config.IMPORT_CATEGORY_RULES`` (``"cat:kw1|kw2;..."``);
        anything unmatched is ``"other"``.
        """
        text = str(description or "").lower()
        for category, keywords in _parse_category_rules():
            if any(kw in text for kw in keywords):
                return category
        return "other"

    # -- preview / import ---------------------------------------------------
    def _resolve_columns(
        self,
        header: list[str],
        date_col,
        desc_col,
        amount_col,
        currency_col,
        debit_col,
        credit_col,
    ) -> dict[str, str | None]:
        """Resolve canonical -> actual column names, explicit args winning over detection."""
        detected = self.detect_columns(header)
        auto = config.IMPORT_AUTO_DETECT_HEADERS

        def need(canonical: str, explicit):
            if explicit:
                return explicit
            if auto and canonical in detected:
                return detected[canonical]
            raise ImportError(
                f"cannot resolve a '{canonical}' column: pass {canonical}_col "
                "explicitly or enable CBA_IMPORT_AUTO_DETECT_HEADERS"
            )

        cols: dict[str, str | None] = {
            "date": need("date", date_col),
            "description": need("description", desc_col),
            # currency is optional: falls back to the default currency later
            "currency": currency_col or (detected.get("currency") if auto else None),
        }
        if amount_col:
            cols["amount"] = amount_col
            cols["debit"] = cols["credit"] = None
        elif (
            debit_col
            or credit_col
            or (auto and "debit" in detected)
            or (auto and "credit" in detected)
        ):
            cols["amount"] = None
            cols["debit"] = debit_col or (detected.get("debit") if auto else None)
            cols["credit"] = credit_col or (detected.get("credit") if auto else None)
            if not cols["debit"] and not cols["credit"]:
                raise ImportError(
                    "debit/credit mode requested but neither column could be resolved"
                )
        else:
            cols["amount"] = need("amount", None)
            cols["debit"] = cols["credit"] = None

        for canonical, actual in cols.items():
            if actual is not None and actual not in header:
                raise ImportError(f"column {actual!r} ({canonical}) not in CSV header")
        return cols

    @staticmethod
    def _validate_currency(raw) -> str:
        ccy = str(raw).strip().upper() if raw is not None else ""
        if ccy not in config.SUPPORTED_CURRENCIES:
            raise ImportError(f"unsupported currency {ccy!r}")
        return ccy

    def _optional_amount(self, raw) -> float:
        """Parse a debit/credit cell; empty cells count as 0."""
        if raw is None or not str(raw).strip():
            return 0.0
        return self.parse_amount(raw)

    def _row_from_record(
        self,
        rec: dict,
        cols: dict[str, str | None],
        fixed_currency: str | None,
        default_currency,
    ) -> dict | None:
        """Map one CSV record to a ledger-ready row dict; ``None`` = zero-amount row.

        Raises :class:`ImportError` when the row is unusable (bad date/amount).
        """
        date_iso = self.parse_date(rec.get(cols["date"]))
        description = str(rec.get(cols["description"]) or "").strip()
        if cols["currency"]:
            # Per-row currency: blank cells fall back to the default; an
            # unsupported per-row value makes just this row unparseable.
            currency = self._validate_currency(
                rec.get(cols["currency"]) or default_currency
                or config.IMPORT_DEFAULT_CURRENCY
            )
        else:
            currency = fixed_currency  # validated up front in preview()

        if cols["amount"]:
            signed = self.parse_amount(rec.get(cols["amount"]))
            amount = round(abs(signed), 2)
            if amount == 0:
                return None
            if signed < 0:
                kind = "expense"
            else:
                lowered = description.lower()
                kind = (
                    "income"
                    if any(kw in lowered for kw in INCOME_KEYWORDS)
                    else "expense"
                )
        else:
            debit = self._optional_amount(
                rec.get(cols["debit"]) if cols["debit"] else ""
            )
            credit = self._optional_amount(
                rec.get(cols["credit"]) if cols["credit"] else ""
            )
            net = round(credit - debit, 2)
            amount = abs(net)
            if amount == 0:
                return None
            kind = "expense" if net <= 0 else "income"

        return {
            "date": date_iso,
            "kind": kind,
            "amount": amount,
            "currency": currency,
            "category": self.categorize(description),
            "description": description,
        }

    def preview(
        self,
        path: str,
        *,
        date_col: str | None = None,
        desc_col: str | None = None,
        amount_col: str | None = None,
        currency_col: str | None = None,
        debit_col: str | None = None,
        credit_col: str | None = None,
        default_currency: str | None = None,
    ) -> dict:
        """Dry-run parse of a CSV statement. Writes nothing.

        Column resolution: explicit ``*_col`` args win; the rest are
        auto-detected unless ``config.IMPORT_AUTO_DETECT_HEADERS`` is False,
        in which case every required column must be passed explicitly.

        Currency for a row comes from ``currency_col`` when resolved, else
        ``default_currency``, else ``config.IMPORT_DEFAULT_CURRENCY``
        (uppercased, validated against ``config.SUPPORTED_CURRENCIES``).
        When no currency column exists the effective currency is validated
        up front and raises :class:`ImportError` if unsupported; a bad
        per-row currency value only skips that row.

        Returns ``{"rows", "skipped", "by_category", "total", "writes": False}``.
        ``"skipped"`` counts blank lines, unparseable rows and zero-amount rows.
        """
        with open(path, "r", newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames or []
            if not header:
                raise ImportError(f"{path}: no header row found")
            cols = self._resolve_columns(
                header, date_col, desc_col, amount_col,
                currency_col, debit_col, credit_col,
            )
            fixed_currency = None
            if not cols["currency"]:
                fixed_currency = self._validate_currency(
                    default_currency or config.IMPORT_DEFAULT_CURRENCY
                )
            rows: list[dict] = []
            skipped = 0
            by_category: dict[str, int] = {}
            for rec in reader:
                if not rec or not any(
                    v is not None and str(v).strip() for v in rec.values()
                ):
                    skipped += 1  # blank line
                    continue
                try:
                    row = self._row_from_record(
                        rec, cols, fixed_currency, default_currency
                    )
                except ImportError:
                    skipped += 1  # unparseable row: counted, never fatal
                    continue
                if row is None:
                    skipped += 1  # zero-amount row: nothing to record
                    continue
                rows.append(row)
                by_category[row["category"]] = by_category.get(row["category"], 0) + 1

        return {
            "rows": rows,
            "skipped": skipped,
            "by_category": dict(sorted(by_category.items())),
            "total": len(rows),
            "writes": False,
        }

    def import_file(self, path: str, dry_run: bool = True, **kw) -> dict:
        """Import a CSV statement.

        ``dry_run=True`` (default) just returns :meth:`preview`. With
        ``dry_run=False`` every previewed row is written via
        ``ledger.add(kind, amount, currency, category, note=description, date_=date)``.

        Returns the preview dict in dry-run mode, else
        ``{"imported", "ids", "by_category", "skipped"}``.
        """
        result = self.preview(path, **kw)
        if dry_run:
            return result
        ids: list[int] = []
        for row in result["rows"]:
            ids.append(
                self.ledger.add(
                    kind=row["kind"],
                    amount=row["amount"],
                    currency=row["currency"],
                    category=row["category"],
                    note=row["description"],
                    date_=row["date"],
                )
            )
        return {
            "imported": len(ids),
            "ids": ids,
            "by_category": result["by_category"],
            "skipped": result["skipped"],
        }


@runtime_checkable
class OpenBankingAdapter(Protocol):
    """Production interface — where a live bank feed plugs in.

    A licensed provider integration implements this protocol and returns
    normalized transaction dicts with keys ``date`` (ISO), ``description``,
    ``amount`` (signed), ``currency`` and optionally ``category``.
    """

    def fetch_transactions(self, account_id: str, since: str) -> list[dict]:
        """Fetch transactions for ``account_id`` since ``since`` (ISO date)."""
        ...


class InertOpenBankingAdapter(OpenBankingAdapter):
    """Inert implementation of :class:`OpenBankingAdapter`.

    Holds no bank credentials and makes no network connections: every
    live-feed method raises :class:`ProductionGatedError`.
    """

    def fetch_transactions(self, account_id: str, since: str) -> list[dict]:
        raise ProductionGatedError(
            "Open banking feed is production-gated: this prototype handles no bank "
            "credentials and makes no live connections. Configure a licensed "
            "provider integration to enable."
        )
