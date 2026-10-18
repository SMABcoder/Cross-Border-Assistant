"""Tuition FX optimizer: advisory timing signals for unpaid tuition bills.

This module is ADVISORY ONLY. It never moves money, holds credentials, or
touches live payment rails. For each unpaid tuition bill it compares today's
FX rate against the trailing average from the local rate cache and returns a
signal:

- ``PAY_NOW`` -- the foreign currency is cheap relative to its recent
  average (rate is above the trailing average by at least
  ``config.OPTIMIZER_SIGNAL_PCT``).
- ``WAIT`` -- the foreign currency is expensive relative to its recent
  average (rate is below the trailing average by at least
  ``config.OPTIMIZER_SIGNAL_PCT``).
- ``NO_SIGNAL`` -- no timing edge, not enough history, same currency, or
  the rate is unavailable.

Rate semantics: a rate is quoted as units of foreign currency per one base
unit (e.g. USD/CNY = 7.32 means 1 USD buys 7.32 CNY). A HIGHER rate therefore
means the foreign currency is CHEAPER right now -- a good moment to pay a
bill denominated in that currency.
"""
from __future__ import annotations

import time
from pathlib import Path

import config
from cba.alerts import AlertService
from cba.common import fmt_money
from cba.fx import FxError, FxService
from cba.tuition import TuitionService

SIGNAL_PAY_NOW = "PAY_NOW"
SIGNAL_WAIT = "WAIT"
SIGNAL_NO_SIGNAL = "NO_SIGNAL"

_SIGNAL_MARKERS = {
    SIGNAL_PAY_NOW: "\u2705",  # ✅
    SIGNAL_WAIT: "\u23f3",  # ⏳
    SIGNAL_NO_SIGNAL: "\u26aa",  # ⚪
}


class OptimizerService:
    """Compute PAY_NOW / WAIT / NO_SIGNAL timing advice for tuition bills."""

    def __init__(
        self,
        db_path: str | Path | None = None,
        fx: FxService | None = None,
        tuition: TuitionService | None = None,
        alerts: AlertService | None = None,
    ) -> None:
        self.db_path = Path(db_path) if db_path else Path(config.DB_PATH)
        self.fx = fx or FxService()
        self.tuition = tuition or TuitionService(db_path=self.db_path)
        self.alerts = alerts or AlertService(db_path=self.db_path, fx=self.fx)

    # -- main entry point -------------------------------------------------
    def optimize(self) -> list[dict]:
        """Return one advisory entry per UNPAID tuition bill.

        Advisory only: no money moves, no orders are placed.
        """
        # Read config here (not at import) so tests can monkeypatch it.
        base = config.APP_CURRENCY.upper()
        lookback_days = int(config.OPTIMIZER_LOOKBACK_DAYS)
        signal_pct = float(config.OPTIMIZER_SIGNAL_PCT)
        now = time.time()
        window_start = now - lookback_days * 86400

        results = []
        for bill in self.tuition.list():  # list() defaults to unpaid only
            quote = bill["currency"].upper()
            pair = f"{base}/{quote}"
            entry = {
                "bill": bill,
                "pair": pair,
                "today_rate": None,
                "trailing_avg": None,
                "lookback_days": lookback_days,
                "diff_pct": None,
                "signal": SIGNAL_NO_SIGNAL,
                "reason": "",
                "matching_alerts": [],
            }
            if quote == base:
                entry["reason"] = (
                    "same currency \u2014 no FX timing decision needed"
                )
                results.append(entry)
                continue

            try:
                today_rate = self.fx.get_rate(base, quote)
            except FxError:
                entry["reason"] = "rate unavailable"
                results.append(entry)
                continue

            entry["today_rate"] = today_rate
            rates = self._recent_rates(base, quote, window_start)
            if len(rates) < 2:
                entry["reason"] = (
                    "not enough rate history"
                    f" (need at least {lookback_days} days of data)"
                )
                results.append(entry)
                continue

            trailing_avg = sum(rates) / len(rates)
            diff_pct = (
                (today_rate - trailing_avg) / trailing_avg * 100
                if trailing_avg
                else 0.0
            )
            entry["trailing_avg"] = trailing_avg
            entry["diff_pct"] = diff_pct
            entry["matching_alerts"] = self._matching_alerts(pair)

            if diff_pct >= signal_pct:
                entry["signal"] = SIGNAL_PAY_NOW
                entry["reason"] = (
                    f"{pair} is {today_rate:.2f}, {diff_pct:.1f}% above its"
                    f" {lookback_days}-day average of {trailing_avg:.2f} \u2014"
                    f" your {quote} tuition is cheap right now."
                )
            elif diff_pct <= -signal_pct:
                entry["signal"] = SIGNAL_WAIT
                entry["reason"] = (
                    f"{pair} is {today_rate:.2f}, {abs(diff_pct):.1f}% below its"
                    f" {lookback_days}-day average of {trailing_avg:.2f} \u2014"
                    " consider waiting for a better rate."
                )
            else:
                entry["signal"] = SIGNAL_NO_SIGNAL
                entry["reason"] = (
                    f"rate is within \u00b1{signal_pct:g}% of its"
                    f" {lookback_days}-day average \u2014 no timing edge."
                )

            if entry["matching_alerts"]:
                alert_id = entry["matching_alerts"][0]["id"]
                entry["reason"] += (
                    f" You already watch this pair with alert #{alert_id}."
                )
            results.append(entry)
        return results

    def _recent_rates(
        self, base: str, quote: str, window_start: float
    ) -> list[float]:
        """Qualifying cached rates for ``base/quote`` inside the lookback window."""
        rates: list[float] = []
        for snap in self.fx.cached.history(base):
            ts = snap.get("ts", 0)
            if ts < window_start:
                continue
            rate = (snap.get("table") or {}).get(quote)
            if rate and float(rate) > 0:
                rates.append(float(rate))
        return rates

    def _matching_alerts(self, pair: str) -> list[dict]:
        return [a for a in self.alerts.list() if a["pair"] == pair]

    # -- reporting --------------------------------------------------------
    @staticmethod
    def format_report(results: list[dict]) -> str:
        """Render a human-readable multi-line report of ``optimize()`` output."""
        if not results:
            return "No unpaid tuition bills to optimize."
        counts = {SIGNAL_PAY_NOW: 0, SIGNAL_WAIT: 0, SIGNAL_NO_SIGNAL: 0}
        for r in results:
            counts[r["signal"]] = counts.get(r["signal"], 0) + 1
        lines = [
            "Tuition FX Optimizer \u2014 "
            f"{len(results)} unpaid bill(s): "
            f"{counts[SIGNAL_PAY_NOW]} PAY_NOW, "
            f"{counts[SIGNAL_WAIT]} WAIT, "
            f"{counts[SIGNAL_NO_SIGNAL]} NO_SIGNAL."
        ]
        for r in results:
            bill = r["bill"]
            marker = _SIGNAL_MARKERS.get(r["signal"], "\u26aa")
            amount = fmt_money(bill["amount"], bill["currency"])
            lines.append("")
            lines.append(
                f"{marker} [{r['signal']}] {bill['name']} \u2014"
                f" {amount} (pair {r['pair']})"
            )
            if r["today_rate"] is not None and r["trailing_avg"] is not None:
                sign = "+" if r["diff_pct"] >= 0 else ""
                lines.append(
                    f"   Today: {r['today_rate']:.4f}"
                    f" | {r['lookback_days']}-day avg: {r['trailing_avg']:.4f}"
                    f" | diff: {sign}{r['diff_pct']:.2f}%"
                )
            lines.append(f"   {r['reason']}")
        return "\n".join(lines)
