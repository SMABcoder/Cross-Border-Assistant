"""Transfer fee estimator + method comparison.

Fee/method data lives ONLY in ``data/fees.json`` (path configurable via
``CBA_FEES_PATH``). This module contains zero hardcoded fee values.
"""
from __future__ import annotations

import json
from pathlib import Path

import config
from cba.common import fmt_money
from cba.fx import FxService

FEES_PATH = Path(
    config.FEES_PATH if getattr(config, "FEES_PATH", "") else Path(config.DATA_DIR) / "fees.json"
)


class FeeError(Exception):
    """Raised when a corridor/method cannot be priced."""


def load_methods(path: str | Path | None = None) -> list[dict]:
    """Load transfer methods from the fees table JSON."""
    path = Path(path) if path else FEES_PATH
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FeeError(f"cannot load fee table {path}: {exc}") from exc
    methods = payload.get("methods")
    if not methods:
        raise FeeError(f"no methods in fee table {path}")
    return methods


class FeeEstimator:
    """Estimate the total cost of one transfer using the fee table."""

    def __init__(
        self,
        methods: list[dict] | None = None,
        fx: FxService | None = None,
        fees_path: str | Path | None = None,
    ) -> None:
        self.methods = methods if methods is not None else load_methods(fees_path)
        self.fx = fx or FxService()

    def get_method(self, method: str) -> dict:
        for m in self.methods:
            if m["method"].lower() == method.lower():
                return m
        raise FeeError(f"unknown method '{method}'")

    def estimate(
        self, amount: float, from_ccy: str, to_ccy: str, method: str
    ) -> dict:
        amount = float(amount)
        if amount <= 0:
            raise ValueError("amount must be positive")
        from_ccy, to_ccy, spec = from_ccy.upper(), to_ccy.upper(), self.get_method(method)

        if amount < spec.get("min_amount", 0) or amount > spec.get("max_amount", float("inf")):
            raise FeeError(
                f"amount {amount} outside {spec['method']} limits "
                f"({spec.get('min_amount')}-{spec.get('max_amount')})"
            )

        # Mid-market reference rate for this corridor.
        mid_rate = self.fx.get_rate(from_ccy, to_ccy)
        # The method's FX margin (basis points) shaves value off the rate.
        margin_bps = float(spec.get("fx_margin_bps", 0))
        applied_rate = mid_rate * (1 - margin_bps / 10_000)

        fixed_fee = float(spec.get("fixed_fee", 0))
        pct_fee = float(spec.get("pct_fee", 0))  # percent of amount
        fee = fixed_fee + amount * pct_fee / 100

        principal_after_fee = max(amount - fee, 0.0)
        receive = principal_after_fee * applied_rate
        fx_margin_cost = amount * mid_rate - amount * applied_rate  # in to_ccy
        total_cost_ccy = fee + (fx_margin_cost / mid_rate if mid_rate else 0.0)

        eta_hours = spec.get("eta_hours", "?")
        eta_text = (
            f"{eta_hours}h" if isinstance(eta_hours, (int, float)) else str(eta_hours)
        )
        return {
            "method": spec["method"],
            "amount": amount,
            "from_ccy": from_ccy,
            "to_ccy": to_ccy,
            "mid_rate": round(mid_rate, 6),
            "applied_rate": round(applied_rate, 6),
            "fx_margin_bps": margin_bps,
            "fee": round(fee, 2),
            "fee_ccy": from_ccy,
            "fx_margin_cost": round(fx_margin_cost, 2),
            "total_cost": round(total_cost_ccy, 2),
            "total_cost_ccy": from_ccy,
            "receive": round(receive, 2),
            "receive_ccy": to_ccy,
            "eta": eta_text,
            "eta_hours": eta_hours,
            "safety_notes": spec.get("safety_notes", ""),
            "summary": (
                f"Send {fmt_money(amount, from_ccy)} via {spec['method']}: "
                f"recipient gets ~{fmt_money(receive, to_ccy)} "
                f"(fee {fmt_money(fee, from_ccy)}, FX margin {margin_bps:.0f} bps,"
                f" ETA {eta_text})."
            ),
        }

    def compare(self, amount: float, from_ccy: str, to_ccy: str) -> list[dict]:
        """Rank all methods by total cost (then ETA)."""
        results = []
        for spec in self.methods:
            try:
                results.append(self.estimate(amount, from_ccy, to_ccy, spec["method"]))
            except FeeError:
                continue
        results.sort(
            key=lambda r: (
                r["total_cost"],
                r["eta_hours"] if isinstance(r["eta_hours"], (int, float)) else 1e9,
            )
        )
        return results

    @staticmethod
    def safety_brief() -> str:
        """Safety guidance for cross-border transfers."""
        return (
            "Stay safe when sending money across borders:\n"
            "1. Use licensed channels only (banks, licensed remittance apps, campus"
            " partner counters). Unlicensed 'agents' can lose your money or break"
            " the law.\n"
            "2. Verify the recipient's name, account number and bank code"
            " character-by-character before you confirm.\n"
            "3. Never split one transfer into many small ones to dodge reporting"
            " limits ('ants moving') - structuring is illegal in most countries.\n"
            "4. Keep every receipt and transaction ID until the money is confirmed"
            " received.\n"
            "5. Ignore anyone offering a 'better rate' over chat or social media -"
            " that is the most common student scam.\n"
            "6. Check your home and host country reporting thresholds before"
            " sending large amounts."
        )
