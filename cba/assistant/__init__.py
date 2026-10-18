"""The friendly student finance assistant: chat in, answers out.

Rule-based and deterministic. Every number comes from FxService, the
ledger, budgets, tuition or the fee table -- never invented.
"""
from __future__ import annotations

import os
import re
from datetime import date
from pathlib import Path

import config
from cba.alerts import AlertService
from cba.assistant import i18n
from cba.assistant.guides import GuideBook
from cba.assistant.intents import Intent, IntentParser
from cba.assistant.llm import LLMProvider, OpenAICompatibleProvider
from cba.budgets import BudgetService
from cba.common import fmt_money
from cba.credit import CreditService
from cba.forecast import ForecastService
from cba.fx import FxService
from cba.importer import CsvImporter
from cba.ledger import LedgerService
from cba.optimizer import OptimizerService
from cba.quota import QuotaService
from cba.transfers import FeeEstimator
from cba.tuition import TuitionService

# Follow-up suggestion chips appended to every reply, keyed by intent.
# Values are i18n keys; an empty list means no chips for that intent.
_CHIPS: dict[str, list[str]] = {
    "convert": ["suggest_alert", "suggest_transfer"],
    "budget_status": ["suggest_forecast", "suggest_optimize"],
    "set_rate_alert": ["suggest_quota"],
    "tuition_due": ["suggest_optimize", "suggest_guide_tuition"],
    "transfer_advice": ["suggest_quota", "suggest_guide_transfer"],
    "credit_advice": ["suggest_credit"],
    "forecast": ["suggest_budget"],
    "optimize": ["suggest_alert", "suggest_quota"],
    "quota": ["suggest_transfer"],
    "import_advice": ["suggest_budget"],
    "serve_web": [],
    "guide": [],
    "help": [],
}

# Terse follow-ups like "and for food?" / "那学费呢？" resolve against the
# topic of the most recent turn.
_FOLLOWUP_RE = re.compile(r"^(and|what about|how about|for)\s+(.+)$", re.IGNORECASE)
_FOLLOWUP_ZH_RE = re.compile(r"^(那|还有)(.+)$")


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
        self.optimizer = OptimizerService(db_path=self.db_path, fx=self.fx)
        self.quota = QuotaService(db_path=self.db_path, fx=self.fx)
        self.importer = CsvImporter(db_path=self.db_path, ledger=self.ledger)
        # Multi-turn memory: recent (intent_name, entities) pairs.
        self._ctx: dict = {"history": []}
        # Default LLM wiring (BYOK): an explicit llm= wins; otherwise, when
        # LLM mode is enabled *and* an API key is configured, construct the
        # OpenAI-compatible provider automatically.
        if llm is not None:
            self.llm = llm if config.LLM_ENABLED else None
        elif config.LLM_ENABLED and config.LLM_API_KEY:
            self.llm = OpenAICompatibleProvider()
        else:
            self.llm = None

    # -- entry point ------------------------------------------------------
    def chat(self, text: str, lang: str | None = None, context: dict | None = None) -> str:
        lang = lang or self.lang
        intent = self.parser.parse(text)
        intent = self._followup_rewrite(text, intent)
        # Record this turn for multi-turn follow-ups, trimming to the
        # configured window.
        self._ctx["history"].append((intent.name, dict(intent.entities)))
        max_turns = int(config.ASSISTANT_MAX_CONTEXT_TURNS or 0)
        if max_turns > 0:
            self._ctx["history"] = self._ctx["history"][-max_turns:]
        handler = {
            "convert": self._h_convert,
            "budget_status": self._h_budget,
            "set_rate_alert": self._h_alert,
            "tuition_due": self._h_tuition,
            "transfer_advice": self._h_transfer,
            "credit_advice": self._h_credit,
            "guide": self._h_guide,
            "forecast": self._h_forecast,
            "optimize": self._h_optimize,
            "quota": self._h_quota,
            "import_advice": self._h_import_advice,
            "serve_web": self._h_serve_web,
            "help": self._h_help,
        }.get(intent.name, self._h_help)
        reply = handler(intent, lang, context or {})
        chips = _CHIPS.get(intent.name, [])
        if chips:
            reply += "\n" + i18n.t("chips_prefix", lang) + " · ".join(
                i18n.t(c, lang) for c in chips
            )
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

    # -- multi-turn context -----------------------------------------------
    def _followup_rewrite(self, text: str, intent: Intent) -> Intent:
        """Resolve terse follow-ups ("and for food?") against the last topic.

        Only budget_status and forecast carry per-category follow-ups: the
        captured category is validated against config.DEFAULT_CATEGORIES
        before the rewrite is applied.
        """
        m = _FOLLOWUP_RE.match(text.strip()) or _FOLLOWUP_ZH_RE.match(text.strip())
        if not m or not self._ctx["history"]:
            return intent
        last_name, last_entities = self._ctx["history"][-1]
        if last_name not in ("budget_status", "forecast"):
            return intent
        cat = m.group(2).strip().lower()
        if cat.startswith("for "):
            cat = cat[4:]
        cat = cat.rstrip("?!.").strip()
        if cat.endswith("s"):
            cat = cat[:-1]
        if cat in config.DEFAULT_CATEGORIES:
            return Intent(last_name, entities={**last_entities, "category": cat})
        return intent

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
        base = status["base_currency"]
        cat = intent.entities.get("category")
        if cat:
            # BudgetService.status has no category parameter: filter manually.
            per = (status.get("per_category") or {}).get(cat)
            if per is None:
                summary = self.ledger.summary(today.year, today.month, base)
                per = {
                    "limit": None,
                    "spent": round(summary["by_category"].get(cat, 0.0), 2),
                    "pct": 0.0,
                }
            if per["limit"] is not None:
                return i18n.t(
                    "budget_category_line", lang,
                    category=cat,
                    spent=fmt_money(per["spent"], base),
                    limit=fmt_money(per["limit"], base),
                    pct=per["pct"],
                )
            return i18n.t(
                "budget_category_line_no_limit", lang,
                category=cat,
                spent=fmt_money(per["spent"], base),
            )
        lines = [i18n.t("budget_header", lang, month=status["month"])]
        total = status["total"]
        if total["limit"] is not None:
            lines.append(
                i18n.t(
                    "budget_total", lang,
                    spent=fmt_money(total["spent"], base),
                    limit=fmt_money(total["limit"], base),
                    pct=total["pct"],
                )
            )
        else:
            lines.append(
                i18n.t(
                    "budget_no_limit", lang,
                    spent=fmt_money(total["spent"], base),
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
        proj = self.forecast.monthly_projection(
            today.year, today.month,
            category=intent.entities.get("category"),
        )
        return f"🔮 {proj['message']}"

    def _h_optimize(self, intent, lang, context) -> str:
        return OptimizerService.format_report(self.optimizer.optimize())

    def _h_quota(self, intent, lang, context) -> str:
        return self.quota.format_status(self.quota.status())

    def _h_import_advice(self, intent, lang, context) -> str:
        path = intent.entities.get("path")
        if path and os.path.exists(path):
            try:
                prev = self.importer.preview(path)
            except Exception:
                return i18n.t("import_help", lang)
            lines = [
                i18n.t(
                    "import_preview_header", lang,
                    path=path, total=prev["total"], skipped=prev["skipped"],
                )
            ]
            for row in prev["rows"][:5]:
                lines.append(
                    i18n.t(
                        "import_preview_row", lang,
                        date=row["date"], kind=row["kind"],
                        amount=fmt_money(row["amount"], row["currency"]),
                        category=row["category"],
                        description=row["description"],
                    )
                )
            lines.append(
                i18n.t("followup", lang, suggestion=i18n.t("suggest_budget", lang))
            )
            return "\n".join(lines)
        return i18n.t("import_help", lang)

    def _h_serve_web(self, intent, lang, context) -> str:
        return i18n.t("serve_help", lang)

    def _h_help(self, intent, lang, context) -> str:
        return i18n.t("help_text", lang)
