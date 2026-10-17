"""Full end-to-end walkthrough of every feature.

This script doubles as execution evidence for the competition (deliverable
06): it runs against a temporary database (nothing is written to the repo),
uses a fake FX provider (no network), prints each capability in order, and
saves the full transcript to ``evidence/demo-transcript-<UTC-timestamp>.log``.

Usage: python scripts/demo.py
"""
from __future__ import annotations

import sys
import tempfile
from datetime import datetime, timedelta, timezone, date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.seed_demo import seed
from cba.alerts import AlertService, ConsoleNotifier
from cba.assistant import Assistant
from cba.assistant.guides import GuideBook
from cba.budgets import BudgetService
from cba.common import fmt_money
from cba.credit import CreditService
from cba.forecast import ForecastService
from cba.fx import FxService, FallbackTableProvider
from cba.ledger import LedgerService
from cba.transfers import FeeEstimator
from cba.tuition import TuitionService


class OfflineFx(FxService):
    """FxService forced onto the fallback table (deterministic, no network)."""

    def _table(self, base: str):
        return FallbackTableProvider().get_table(base)


class Tee:
    """Write to stdout and a log file at the same time."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._file = path.open("w", encoding="utf-8")

    def write(self, text: str) -> None:
        sys.__stdout__.write(text)
        self._file.write(text)

    def flush(self) -> None:
        sys.__stdout__.flush()
        self._file.flush()

    def close(self) -> None:
        self._file.close()


def banner(title: str) -> None:
    print("\n" + "=" * 64)
    print(f"  {title}")
    print("=" * 64)


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    evidence_dir = repo_root / "evidence"
    evidence_dir.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log_path = evidence_dir / f"demo-transcript-{stamp}.log"
    tee = Tee(log_path)
    sys.stdout = tee  # noqa: E402 - intentional for evidence capture
    try:
        return run()
    finally:
        sys.stdout = sys.__stdout__
        tee.close()
        print(f"\nTranscript saved to: {log_path}")


def run() -> int:
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    db = tmp.name
    tmp.close()
    today = date.today()
    print(f"Cross Border Assistant — demo run {datetime.now(timezone.utc).isoformat()}")
    print(f"(temp database: {db}; FX: offline fallback table)")

    banner("1. Seed demo student")
    stats = seed(db, today=today)
    print(f"   transactions={stats['transactions']}, budgets={stats['budgets']}, "
          f"bills={stats['bills']}, alerts={stats['alerts']}")

    fx = OfflineFx()
    ledger = LedgerService(db_path=db, fx=fx)

    banner("2. FX rates (offline fallback table)")
    print(f"   1 USD = {fx.get_rate('USD', 'CNY'):.4f} CNY")
    print(f"   500 USD = {fmt_money(fx.convert(500, 'USD', 'CNY'), 'CNY')}")

    banner("3. Ledger summary")
    s = ledger.summary(today.year, today.month, "USD")
    print(f"   {s['month']}: income {s['formatted']['income']}, "
          f"expense {s['formatted']['expense']}, net {s['formatted']['net']}")
    for cat, amt in list(s["by_category"].items())[:5]:
        print(f"     - {cat}: {fmt_money(amt, 'USD')}")

    banner("4. Budget status + warnings + pace")
    budgets = BudgetService(db_path=db, ledger=ledger)
    st = budgets.status(today.year, today.month, "USD")
    t = st["total"]
    print(f"   Total: {fmt_money(t['spent'], 'USD')} / {fmt_money(t['limit'], 'USD')} ({t['pct']}%)")
    for w in st["warnings"]:
        print(f"   ⚠️ {w}")
    if st.get("pace"):
        print(f"   📈 {st['pace']['message']}")

    banner("5. Forecast")
    fc = ForecastService(db_path=db, ledger=ledger)
    proj = fc.monthly_projection(today.year, today.month)
    print(f"   🔮 {proj['message']}  (history: {proj['history']})")

    banner("6. Rate alerts (check loop)")
    alerts = AlertService(db_path=db, fx=fx, notifiers=[ConsoleNotifier()])
    triggered = alerts.check(cooldown=0)
    print(f"   checked {len(alerts.list())} alerts, {len(triggered)} triggered")

    banner("7. Tuition reminders")
    tuition = TuitionService(db_path=db)
    for n in tuition.due_notifications(today=today):
        print(f"   📅 [{n['kind']}] {n['message']}")
        print(f"      guide: {n['guide_ref']}")

    banner("8. Transfer comparison (fee table)")
    fees = FeeEstimator(fx=fx)
    for r in fees.compare(500, "USD", "CNY")[:3]:
        print(f"   {r['method']}: receive {fmt_money(r['receive'], 'CNY')} "
              f"| cost {fmt_money(r['total_cost'], 'USD')} | ETA {r['eta']}")

    banner("9. Credit building (checklist + guide)")
    credit = CreditService(db_path=db)
    credit.complete("secured_card")
    prog = credit.progress()
    print(f"   Checklist: {prog['done']}/{prog['total']} ({prog['pct']}%)")
    guide = GuideBook().render("credit_building")
    print("   " + "\n   ".join(guide.splitlines()[:6]) + "\n   ...")

    banner("10. Step-by-step guide")
    guide = GuideBook().render("pay_tuition")
    print("   " + "\n   ".join(guide.splitlines()[:8]) + "\n   ...")

    banner("11. Assistant chat (EN + ZH)")
    assistant = Assistant(db_path=db, fx=fx)
    for msg, lang in [
        ("convert 100 USD to CNY", "en"),
        ("how is my budget?", "en"),
        ("when is my tuition due?", "en"),
        ("cheapest way to send 500 USD to CNY", "en"),
        ("how do I build credit?", "en"),
        ("convert 100 USD to CNY", "zh"),
        ("how is my budget?", "zh"),
    ]:
        print(f"   you [{lang}]> {msg}")
        reply = assistant.chat(msg, lang=lang)
        first = reply.splitlines()[0]
        print(f"   bot> {first[:100]}{'...' if len(first) > 100 else ''}")

    banner("DONE — all 11 capabilities demonstrated")
    print("   (temp db used; nothing written to the repo database)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
