"""The friendly student finance assistant: chat in, answers out.

Rule-based and deterministic. Every number comes from FxService, the
ledger, budgets, tuition or the fee table -- never invented.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import config
from cba.alerts import AlertService
from cba.assistant import i18n
from cba.assistant.guides import GuideBook
from cba.assistant.intents import IntentParser
from cba.assistant.llm import LLMProvider
from cba.budgets import BudgetService
from cba.common import fmt_money
from cba.credit import CreditService
from cba.forecast import ForecastService
from cba.fx import FxService
from cba.ledger import LedgerService
from cba.transfers import FeeEstimator
from cba.tuition import TuitionService


class Assistant:
    """Conversational front-end over all Phase-1 services."""

    def __init__(
        self,
        db_path: str | Path | None = None,
        fx: FxService | None = None,
        lang: str | None = None,
        llm: LLMProvider | None = None,
    ) -> None:
        self.db_path = Path(db_path) if db_path else Path(config.DB_PATH)
        self.lang = lang or config.DEFAULT_LANG
        self.parser = IntentParser()
        self.guides = GuideBook()
        self.fx = fx or FxService()
        self.ledger = LedgerService(db_path=self.db_path, fx=self.fx)
        self.budgets = BudgetService(db_path=self.db_path, ledger=self.ledger)
        self.alerts = AlertService(db_path=self.db_path, fx=self.fx)
        self.tuition = TuitionService(db_path=self.db_path)
        self.transfers = FeeEstimator(fx=self.fx)
        self.credit = CreditService(db_path=self.db_path)
        self.forecast = ForecastService(db_path=self.db_path, ledger=self.ledger)
        self.llm = llm if config.LLM_ENABLED else None

    # -- entry point ------------------------------------------------------
    def chat(self, text: str, lang: str | None = None, context: dict | None = None) -> str:
        lang = lang or self.lang
        intent = self.parser.parse(text)
        handler = {
            "convert": self._h_convert,
            "budget_status": self._h_budget,
            "set_rate_alert": self._h_alert,
            "tuition_due": self._h_tuition,
            "transfer_advice": self._h_transfer,
            "credit_advice": self._h_credit,
            "guide": self._h_guide,
            "forecast": self._h_forecast,
            "help": self._h_help,
        }.get(intent.name, self._h_help)
        reply = handler(intent, lang, context or {})
        if self.llm is not None:
            try:
                reply = self.llm.complete(
                    "You are a friendly student finance assistant. Keep numbers exact.",
                    f"User said: {text}\nDraft answer: {reply}\n"
                    "Rephrase warmly without changing any numbers.",
                )
            except Exception:
                pass
        return reply

    # -- handlers ---------------------------------------------------------
    def _h_convert(self, intent, lang, context) -> str:
        e = intent.entities
        try:
            result = self.fx.convert(e["amount"], e["from"], e["to"])
            rate = self.fx.get_rate(e["from"], e["to"])
        except Exception as exc:
            return i18n.t("fx_unavailable", lang, error=exc)
        out = [
            i18n.t(
                "converted", lang,
                amount=fmt_money(e["amount"], e["from"]),
                result=fmt_money(result, e["to"]),
                rate=f"{rate:.4f}",
                base=e["from"], quote=e["to"],
            )
        ]
        try:
            trend = self.fx.trend(e["from"], e["to"])
            out.append(
                i18n.t(
                    "trend_note", lang,
                    direction=trend["direction"], change=trend["change_pct"],
                )
            )
        except Exception:
            pass
        out.append(i18n.t("followup", lang, suggestion=i18n.t("suggest_alert", lang)))
        return "\n".join(out)

    def _h_budget(self, intent, lang, context) -> str:
        today = date.today()
        status = self.budgets.status(today.year, today.month)
        lines = [i18n.t("budget_header", lang, month=status["month"])]
        total = status["total"]
        if total["limit"] is not None:
            lines.append(
                i18n.t(
                    "budget_total", lang,
                    spent=fmt_money(total["spent"], status["base_currency"]),
                    limit=fmt_money(total["limit"], status["base_currency"]),
                    pct=total["pct"],
                )
            )
        else:
            lines.append(
                i18n.t(
                    "budget_no_limit", lang,
                    spent=fmt_money(total["spent"], status["base_currency"]),
                )
            )
        for w in status["warnings"]:
            lines.append(f"⚠️ {w}")
        if status.get("pace"):
            lines.append(f"📈 {status['pace']['message']}")
        lines.append(i18n.t("followup", lang, suggestion=i18n.t("suggest_forecast", lang)))
        return "\n".join(lines)

    def _h_alert(self, intent, lang, context) -> str:
        e = intent.entities
        if not e.get("base"):
            return i18n.t("alert_format_help", lang)
        try:
            alert = self.alerts.create(
                f"{e['base']}/{e['quote']}", e["target"], e["direction"]
            )
        except Exception as exc:
            return i18n.t("alert_failed", lang, error=exc)
        return i18n.t(
            "alert_created", lang,
            pair=alert["pair"], direction=alert["direction"],
            target=f"{alert['target']:.4f}",
        )

    def _h_tuition(self, intent, lang, context) -> str:
        bills = self.tuition.list()
        if not bills:
            return i18n.t("tuition_none", lang)
        notes = {n["bill"]["id"]: n for n in self.tuition.due_notifications()}
        lines = [i18n.t("tuition_header", lang)]
        for b in bills:
            n = notes.get(b["id"])
            flag = f" — {n['message']}" if n else ""
            lines.append(
                f"• {b['name']}: {fmt_money(b['amount'], b['currency'])}"
                f" due {b['due_date']}{flag}"
            )
        lines.append(i18n.t("followup", lang, suggestion=i18n.t("suggest_guide_tuition", lang)))
        return "\n".join(lines)

    def _h_transfer(self, intent, lang, context) -> str:
        e = intent.entities
        if not e.get("from") or not e.get("amount"):
            return i18n.t("transfer_format_help", lang)
        try:
            ranked = self.transfers.compare(e["amount"], e["from"], e["to"])
        except Exception as exc:
            return i18n.t("transfer_failed", lang, error=exc)
        lines = [
            i18n.t(
                "transfer_header", lang,
                amount=fmt_money(e["amount"], e["from"]),
                to=e["to"],
            )
        ]
        for r in ranked[:3]:
            lines.append(
                f"• {r['method']}: {fmt_money(r['receive'], r['receive_ccy'])}"
                f" (cost {fmt_money(r['total_cost'], r['total_cost_ccy'])},"
                f" ETA {r['eta']})"
            )
        lines.append(i18n.t("followup", lang, suggestion=i18n.t("suggest_guide_transfer", lang)))
        return "\n".join(lines)

    def _h_credit(self, intent, lang, context) -> str:
        prog = self.credit.progress()
        lines = [i18n.t("credit_header", lang)]
        lines.append(
            i18n.t(
                "credit_progress", lang,
                done=prog["done"], total=prog["total"], pct=prog["pct"],
            )
        )
        for item in self.credit.items():
            mark = "✅" if item["done"] else "⬜"
            lines.append(f"{mark} {item['label']} (`{item['key']}`)")
        lines.append("")
        lines.append(self.guides.render("credit_building", lang=lang))
        lines.append(i18n.t("followup", lang, suggestion=i18n.t("suggest_credit", lang)))
        return "\n".join(lines)

    def _h_guide(self, intent, lang, context) -> str:
        ref = intent.entities.get("guide")
        if not ref:
            available = ", ".join(g["ref"] for g in self.guides.list_guides())
            return i18n.t("guide_list", lang, guides=available)
        try:
            return self.guides.render(ref, lang=lang)
        except KeyError:
            return i18n.t("guide_missing", lang, ref=ref)

    def _h_forecast(self, intent, lang, context) -> str:
        today = date.today()
        proj = self.forecast.monthly_projection(today.year, today.month)
        return f"🔮 {proj['message']}"

    def _h_help(self, intent, lang, context) -> str:
        return i18n.t("help_text", lang)
