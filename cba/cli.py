"""Command-line interface for the Cross Border Assistant.

Every subcommand is demoable in seconds::

    python cba/cli.py rates --base USD --quote CNY
    python cba/cli.py add-expense --amount 12.5 --currency USD --category food --note "lunch"
    python cba/cli.py budget --set 1500 --currency USD
    python cba/cli.py alert --create USD/CNY --target 7.3 --direction above
    python cba/cli.py tuition --add "Spring tuition" --amount 5000 --currency USD --due 2026-11-20
    python cba/cli.py transfer --amount 500 --from USD --to CNY
    python cba/cli.py chat --message "convert 100 USD to CNY"
    python cba/cli.py forecast
    python cba/cli.py credit --complete secured_card
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from cba.alerts import AlertService
from cba.assistant import Assistant
from cba.budgets import BudgetService
from cba.common import fmt_money
from cba.credit import CreditService
from cba.forecast import ForecastService
from cba.fx import FxService
from cba.ledger import LedgerService
from cba.transfers import FeeEstimator
from cba.tuition import TuitionService


def cmd_rates(args) -> int:
    fx = FxService()
    if args.trend:
        info = fx.trend(args.base, args.quote)
        print(f"{info['pair']}: {info['current']:.4f} "
              f"({info['direction']}, {info['change_pct']}%)")
    else:
        rate = fx.get_rate(args.base, args.quote)
        print(f"1 {args.base.upper()} = {rate:.4f} {args.quote.upper()}")
    return 0


def cmd_add_expense(args) -> int:
    ledger = LedgerService()
    kind = "income" if args.income else "expense"
    tx_id = ledger.add(kind, args.amount, args.currency, args.category,
                       note=args.note or "", date_=args.date)
    print(f"Recorded {kind} #{tx_id}: {fmt_money(args.amount, args.currency.upper())}"
          f" [{args.category}]")
    return 0


def cmd_budget(args) -> int:
    svc = BudgetService()
    today = date.today()
    if args.set is not None:
        svc.set_budget(today.year, today.month, args.set, args.currency, args.category)
        scope = f"category '{args.category}'" if args.category else "total monthly"
        print(f"Set {scope} budget: {fmt_money(args.set, (args.currency or config.APP_CURRENCY).upper())}")
        return 0
    status = svc.status(today.year, today.month, args.currency)
    print(f"Budget status for {status['month']} ({status['base_currency']}):")
    total = status["total"]
    if total["limit"] is not None:
        print(f"  Total: {fmt_money(total['spent'], status['base_currency'])} / "
              f"{fmt_money(total['limit'], status['base_currency'])} ({total['pct']}%)")
    else:
        print(f"  Spent: {fmt_money(total['spent'], status['base_currency'])} (no limit set)")
    for cat, info in status["per_category"].items():
        print(f"  {cat}: {fmt_money(info['spent'], status['base_currency'])} / "
              f"{fmt_money(info['limit'], status['base_currency'])} ({info['pct']}%)")
    for w in status["warnings"]:
        print(f"  ⚠️ {w}")
    if status.get("pace"):
        print(f"  📈 {status['pace']['message']}")
    return 0


def cmd_alert(args) -> int:
    svc = AlertService()
    if args.create:
        alert = svc.create(args.create, args.target, args.direction, note=args.note or "")
        print(f"Alert #{alert['id']}: {alert['pair']} {alert['direction']} {alert['target']}")
        return 0
    if args.check:
        triggered = svc.check()
        if not triggered:
            print("No alerts triggered.")
        for t in triggered:
            print(f"🔔 {t['pair']} is {t['rate']:.4f} ({t['direction']} {t['target']:.4f})")
        return 0
    if args.deactivate:
        svc.deactivate(args.deactivate)
        print(f"Deactivated alert #{args.deactivate}")
        return 0
    for a in svc.list():
        print(f"#{a['id']} {a['pair']} {a['direction']} {a['target']}")
    return 0


def cmd_tuition(args) -> int:
    svc = TuitionService()
    if args.add:
        bill = svc.add(args.add, args.amount, args.currency, args.due,
                       payee=args.payee or "")
        print(f"Bill #{bill['id']}: {bill['name']} {fmt_money(bill['amount'], bill['currency'])} due {bill['due_date']}")
        return 0
    if args.paid:
        svc.mark_paid(args.paid)
        print(f"Bill #{args.paid} marked as paid.")
        return 0
    if args.remind:
        pending = svc.due_notifications()
        if not pending:
            print("No tuition reminders due right now.")
        for n in pending:
            print(f"📅 [{n['kind']}] {n['message']}")
            print(f"   Guide: {n['guide_ref']}")
        return 0
    for b in svc.list(include_paid=True):
        state = "PAID" if b["paid"] else "unpaid"
        print(f"#{b['id']} {b['name']}: {fmt_money(b['amount'], b['currency'])} due {b['due_date']} [{state}]")
    return 0


def cmd_transfer(args) -> int:
    est = FeeEstimator()
    if args.method:
        r = est.estimate(args.amount, args.from_, args.to, args.method)
        print(r["summary"])
        if r["safety_notes"]:
            print(f"Note: {r['safety_notes']}")
    else:
        ranked = est.compare(args.amount, args.from_, args.to)
        print(f"Cheapest ways to send {fmt_money(args.amount, args.from_.upper())} → {args.to.upper()}:")
        for i, r in enumerate(ranked, 1):
            print(f"  {i}. {r['method']}: receive {fmt_money(r['receive'], r['receive_ccy'])} "
                  f"| cost {fmt_money(r['total_cost'], r['total_cost_ccy'])} | ETA {r['eta']}")
    if args.safety:
        print()
        print(FeeEstimator.safety_brief())
    return 0


def cmd_chat(args) -> int:
    assistant = Assistant(lang=args.lang)
    if args.message:
        print(assistant.chat(args.message, lang=args.lang))
        return 0
    print("Cross Border Assistant — type 'quit' to exit.")
    while True:
        try:
            text = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if text.lower() in ("quit", "exit"):
            break
        if text:
            print(assistant.chat(text))
    return 0


def cmd_credit(args) -> int:
    svc = CreditService()
    if args.complete:
        svc.complete(args.complete)
        print(f"Marked '{args.complete}' as done.")
        return 0
    if args.uncomplete:
        svc.uncomplete(args.uncomplete)
        print(f"Marked '{args.uncomplete}' as not done.")
        return 0
    if args.reset:
        svc.reset()
        print("Checklist reset.")
        return 0
    prog = svc.progress()
    print(f"Credit-building checklist: {prog['done']}/{prog['total']} ({prog['pct']}%)")
    for item in svc.items():
        mark = "✅" if item["done"] else "⬜"
        print(f"  {mark} {item['label']} [{item['key']}]")
    return 0


def cmd_forecast(args) -> int:
    svc = ForecastService()
    today = date.today()
    proj = svc.monthly_projection(today.year, today.month, category=args.category)
    print(f"🔮 {proj['message']}")
    if args.json:
        print(json.dumps(proj, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="cba", description="Cross Border Assistant — student finance CLI"
    )
    sub = p.add_subparsers(dest="command", required=True)

    r = sub.add_parser("rates", help="Exchange rates")
    r.add_argument("--base", default=config.APP_CURRENCY)
    r.add_argument("--quote", default="CNY")
    r.add_argument("--trend", action="store_true", help="show trend summary")
    r.set_defaults(func=cmd_rates)

    a = sub.add_parser("add-expense", help="Record income/expense")
    a.add_argument("--amount", type=float, required=True)
    a.add_argument("--currency", default=config.APP_CURRENCY)
    a.add_argument("--category", default="other")
    a.add_argument("--note", default="")
    a.add_argument("--date", default=None)
    a.add_argument("--income", action="store_true")
    a.set_defaults(func=cmd_add_expense)

    b = sub.add_parser("budget", help="Set or view monthly budget")
    b.add_argument("--set", type=float, default=None)
    b.add_argument("--currency", default=None)
    b.add_argument("--category", default=None)
    b.set_defaults(func=cmd_budget)

    al = sub.add_parser("alert", help="Rate alerts")
    al.add_argument("--create", default=None, help="pair like USD/CNY")
    al.add_argument("--target", type=float, default=0)
    al.add_argument("--direction", default="above", choices=["above", "below"])
    al.add_argument("--note", default="")
    al.add_argument("--check", action="store_true")
    al.add_argument("--deactivate", type=int, default=None)
    al.set_defaults(func=cmd_alert)

    t = sub.add_parser("tuition", help="Tuition bills & reminders")
    t.add_argument("--add", default=None, help="bill name")
    t.add_argument("--amount", type=float, default=0)
    t.add_argument("--currency", default=config.APP_CURRENCY)
    t.add_argument("--due", default="")
    t.add_argument("--payee", default="")
    t.add_argument("--paid", type=int, default=None)
    t.add_argument("--remind", action="store_true")
    t.set_defaults(func=cmd_tuition)

    tr = sub.add_parser("transfer", help="Fee estimates & comparison")
    tr.add_argument("--amount", type=float, required=True)
    tr.add_argument("--from", dest="from_", default="USD")
    tr.add_argument("--to", default="CNY")
    tr.add_argument("--method", default=None)
    tr.add_argument("--safety", action="store_true")
    tr.set_defaults(func=cmd_transfer)

    c = sub.add_parser("chat", help="Talk to the assistant")
    c.add_argument("--message", default=None)
    c.add_argument("--lang", default=config.DEFAULT_LANG)
    c.set_defaults(func=cmd_chat)

    f = sub.add_parser("forecast", help="Month-end spending projection")
    f.add_argument("--category", default=None)
    f.add_argument("--json", action="store_true")
    f.set_defaults(func=cmd_forecast)

    cr = sub.add_parser("credit", help="Credit-building checklist")
    cr.add_argument("--complete", default=None, help="mark item key as done")
    cr.add_argument("--uncomplete", default=None, help="mark item key as not done")
    cr.add_argument("--reset", action="store_true")
    cr.set_defaults(func=cmd_credit)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
