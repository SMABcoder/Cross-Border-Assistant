"""Rule-based intent parser for the student finance assistant."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

INTENTS = (
    "convert",
    "budget_status",
    "set_rate_alert",
    "tuition_due",
    "transfer_advice",
    "credit_advice",
    "guide",
    "forecast",
    "optimize",
    "quota",
    "import_advice",
    "serve_web",
    "help",
)

CURRENCY_RE = re.compile(
    r"\b(USD|CNY|EUR|GBP|PKR|INR|JPY|SGD|CAD|AUD|CHF|HKD|KRW|MYR|AED|SAR|THB)\b",
    re.IGNORECASE,
)

# Matches "100 usd to cny", "convert 50 eur in gbp", "100usd->cny"
CONVERT_RE = re.compile(
    r"(?:convert\s+)?(\d+(?:\.\d+)?)\s*([A-Za-z]{3})\s*(?:to|in|->|→)\s*([A-Za-z]{3})",
    re.IGNORECASE,
)

# Matches "alert me when usd/cny above 7.3", "set alert usd-cny below 7.1"
ALERT_RE = re.compile(
    r"([A-Za-z]{3})\s*[/\- ]\s*([A-Za-z]{3})\s+(above|below|over|under)\s+(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)


@dataclass
class Intent:
    name: str
    confidence: float = 1.0
    entities: dict = field(default_factory=dict)


class IntentParser:
    """Keyword/regex intent parser (deterministic, no ML needed for MVP)."""

    def parse(self, text: str) -> Intent:
        low = text.lower().strip()

        # Rate alert
        m = ALERT_RE.search(text)
        if m and any(k in low for k in ("alert", "notify", "提醒", "watch")):
            direction = m.group(3).lower()
            direction = "above" if direction in ("above", "over") else "below"
            return Intent(
                "set_rate_alert",
                entities={
                    "base": m.group(1).upper(),
                    "quote": m.group(2).upper(),
                    "direction": direction,
                    "target": float(m.group(4)),
                },
            )

        # New intents, checked early so they aren't swallowed by the
        # broader keyword matches below.
        if any(k in low for k in ("optimiz", "should i pay", "pay now", "时机")) and any(
            k in low for k in ("tuition", "fee", "学费", "bill")
        ):
            return Intent("optimize")

        if any(k in low for k in ("quota", "额度", "外汇", "safe quota")):
            return Intent("quota")

        if (
            any(k in low for k in ("import", "csv", "导入", "对账单"))
            or "bank statement" in low
        ):
            m = re.search(r"[\w\-./\\]+\.csv", text, re.IGNORECASE)
            return Intent(
                "import_advice",
                entities={"path": m.group(0) if m else None},
            )

        if any(
            k in low for k in ("serve", "web ui", "web page", "网页", "browser ui")
        ):
            return Intent("serve_web")

        if any(k in low for k in ("credit", "信用", "征信", "credit score", "credit card")):
            return Intent("credit_advice")

        if any(k in low for k in ("tuition", "学费", "due", "bill", "缴费")) and not any(
            k in low for k in ("guide", "how to", "step-by-step", "指南")
        ):
            return Intent("tuition_due")

        if any(k in low for k in ("guide", "how to", "step", "指南", "怎么")):
            guide = None
            if "tuition" in low or "学费" in low:
                guide = "pay_tuition"
            elif "home" in low or "汇" in low or "credit" in low or "信用" in low:
                guide = "credit_building" if ("credit" in low or "信用" in low) else "send_money_home"
            elif "budget" in low or "预算" in low:
                guide = "first_month_budget"
            return Intent("guide", entities={"guide": guide})

        if any(k in low for k in ("transfer", "send money", "remit", "汇款", "转账", "fee", "cheapest", "compare", "send ")):
            currs = CURRENCY_RE.findall(text)
            ents = {}
            if len(currs) >= 2:
                ents = {"from": currs[0].upper(), "to": currs[1].upper()}
            amt = re.search(r"(\d+(?:\.\d+)?)", text)
            if amt:
                ents["amount"] = float(amt.group(1))
            return Intent("transfer_advice", entities=ents)

        # Explicit conversion pattern (checked after transfer: "cheapest way
        # to send 500 USD to CNY" is transfer advice, not a conversion).
        m = CONVERT_RE.search(text)
        if m and any(
            k in low for k in ("convert", "exchange", "to", "in", "->", "→", "换", "汇率")
        ):
            return Intent(
                "convert",
                entities={
                    "amount": float(m.group(1)),
                    "from": m.group(2).upper(),
                    "to": m.group(3).upper(),
                },
            )

        if any(k in low for k in ("forecast", "predict", "projection", "预测", "will i exceed", "will i go over")):
            return Intent("forecast")

        if any(k in low for k in ("budget", "spent", "spending", "预算", "花了")):
            return Intent("budget_status")

        if any(k in low for k in ("help", "hello", "hi", "你好", "帮助", "what can you")):
            return Intent("help")

        # Fallback: two currencies mentioned -> assume conversion.
        currs = CURRENCY_RE.findall(text)
        if len(currs) >= 2:
            amt = re.search(r"(\d+(?:\.\d+)?)", text)
            return Intent(
                "convert",
                confidence=0.6,
                entities={
                    "amount": float(amt.group(1)) if amt else 1.0,
                    "from": currs[0].upper(),
                    "to": currs[1].upper(),
                },
            )
        return Intent("help", confidence=0.4)
