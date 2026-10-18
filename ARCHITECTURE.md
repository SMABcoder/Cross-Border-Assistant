# Architecture — Cross Border Assistant

FinTechathon 2026 · International Track · Topic C · Deliverable 01 (technical documentation)

## 1. Context

International students lose money and sleep to four problems: opaque
remittance fees, tuition deadlines in foreign currencies, starting adult life
with no local credit file, and budgeting across multiple currencies. Banks
solve these with advisors; students get apps that assume one currency and one
country. This project is a local-first, multilingual assistant that covers
all four, built so the **reliable core works before any intelligence is added**.

Design constraints (from the brief):
- **Zero hardcoded tunables** — every threshold, TTL, limit and default is
  env-overridable via `config.py` (`CBA_` prefix).
- **Stdlib-first** — `sqlite3`, `urllib`, `json`, `datetime`, `argparse`,
  `smtplib`, `unittest`. `requests` optional with `urllib` fallback. No
  numpy/pandas.
- **Offline-capable** — the assistant must answer even with no network.
- **Honest scope** — estimates, not transactions; guidance, not bureaus.

## 2. Phased plan (as built)

**Phase 1 — bulletproof core** (no ML, no network dependency):
1. `cba/fx` — rates with live → cache → fallback chain.
2. `cba/ledger` — manual income/expense tracking in sqlite, FX-normalized summaries.
3. `cba/budgets` — monthly + per-category limits, 80%/100% warnings, burn-down pace.
4. `cba/alerts` — target-rate alerts, cooldown-guarded, pluggable notifiers.
5. `cba/tuition` — bills with threshold reminders + step-by-step guides.
6. `cba/transfers` — fee estimator + cheapest-first comparison from `data/fees.json`.
7. `cba/credit` — credit-building guide + checklist tracker (added per official Appendix 2 scope).

**Phase 2 — intelligence on top:**
8. `cba/assistant` — rule-based intents (13), EN/ZH i18n, guide book,
   follow-up chips, multi-turn context, friendly chat; BYOK
   `OpenAICompatibleProvider` (stdlib urllib, disabled by default; unset
   key = deterministic engine).
9. `cba/forecast` — weighted moving average + trend vs budget, scaled by a
   monthly seasonality index (from ledger history) + per-category daily burn.

**Phase 3 — advisors & access (as built):**
10. `cba/optimizer` — advisory-only tuition FX timing (PAY_NOW / WAIT /
    NO_SIGNAL vs trailing average); never moves money.
11. `cba/quota` — self-reported SAFE annual FX quota tracker (80%/100%).
12. `cba/importer` — CSV statement import (auto-detect, rules, dry-run) +
    inert `OpenBankingAdapter` interface.
13. `cba/web` — stdlib JSON API + self-contained chat page (`cba serve`).
14. `cba/rails` — inert CIPS / e-CNY / mBridge adapters (production-gated)
    + ISO 20022 pain.001 format builder (format only, not execution).
15. `cba/credit` extensions — transparent score estimator (labeled
    ESTIMATE) + inert `BaihangCreditAdapter` interface.

## 3. Module map

| Module | Responsibility | Key public API |
|---|---|---|
| `cba/fx` | Exchange rates | `FxService.get_rate/convert/trend`; providers: `SimpleApiProvider`, `CachedProvider`, `FallbackTableProvider` |
| `cba/ledger` | Income/expense | `LedgerService.add/list/summary(year, month, base)` |
| `cba/budgets` | Budgets | `BudgetService.set_budget/status` (+ pace message) |
| `cba/alerts` | Rate alerts | `AlertService.create/list/check/deactivate`; `Console/Email/WebhookNotifier` |
| `cba/tuition` | Tuition reminders | `TuitionService.add/list/mark_paid/due_notifications/pending_notifications` |
| `cba/transfers` | Fee estimates | `FeeEstimator.estimate/compare`, `safety_brief()` |
| `cba/credit` | Credit building | `CreditService.items/complete/progress/estimate_score`; inert `BaihangCreditAdapter`; guide `credit_building` |
| `cba/assistant` | Chat | `Assistant.chat(text, lang, context)`; `IntentParser` (13 intents); `GuideBook`; `i18n.t`; chips + multi-turn context; BYOK `OpenAICompatibleProvider` |
| `cba/forecast` | Projection | `ForecastService.monthly_projection` (pace × seasonality); `category_daily_burn` |
| `cba/optimizer` | FX timing advice | `OptimizerService.optimize` → PAY_NOW/WAIT/NO_SIGNAL; `format_report` |
| `cba/quota` | SAFE quota | `QuotaService.record/usage/status/format_status` (self-reported) |
| `cba/importer` | CSV import | `CsvImporter.preview/import_file`; inert `OpenBankingAdapter` |
| `cba/web` | Web UI + API | `WebApp.run/start`; `GET /`, `/api/chat`, `/api/rates`, `/api/budget`, `/api/alerts` |
| `cba/rails` | Rails (inert) | `CipsRail`/`EcnYRail`/`MBridgeRail` (refuse); `build_pain001` (format only) |
| `cba/cli.py` | CLI | 13 subcommands (rates … credit … forecast, optimize, import, quota, serve, chat) |
| `config.py` | All tunables | `from_env(name, default)` |

## 4. Data model (sqlite)

```
transactions(id, date, kind[income|expense], amount, currency, category, note)
categories(name, kind)
budgets(month, category['__total__'|name], limit_amount, currency)
rate_alerts(id, pair, base, quote, target, direction[above|below], note,
            created_at, last_triggered_at, active)
alert_events(id, alert_id, rate, triggered_at)
tuition_bills(id, name, amount, currency, due_date, payee, guide_ref, paid, created_at)
tuition_notifications(id, bill_id, kind, notified_on)   -- UNIQUE(bill_id, kind, notified_on)
credit_checklist(item_key, label, done, sort_order)
quota_transfers(id, date, amount, currency, amount_usd, note)  -- self-reported
```

JSON data (all editable without code changes):
`data/fees.json` (transfer methods — the **only** place fees exist),
`data/fallback_rates.json`, `data/credit_checklist.json`,
`data/i18n/{en,zh}.json`, `data/guides/*.json` (pay_tuition, send_money_home,
first_month_budget, credit_building).

## 5. Alert-loop sequence

```
cron (every 10 min) → scripts/check_alerts.py
    → AlertService.check()
        for each active alert:
            rate = FxService.get_rate(base, quote)      # live→cache→fallback
            skip if now - last_triggered_at < CBA_ALERT_COOLDOWN
            if (above and rate >= target) or (below and rate <= target):
                record event + update last_triggered_at
                notify via each configured notifier (console/email/webhook)
```

The same loop powers tuition reminders: `TuitionService.pending_notifications()`
drains each (bill, kind) once via the unique constraint — safe to run on a
schedule without duplicates.

## 6. i18n strategy

Message catalogs in `data/i18n/<lang>.json`; `i18n.t(key, lang)` falls back
EN → key. Adding a language = adding one JSON file (structure ready).
Guides support per-language files (`<ref>.<lang>.json`) with fallback to the
base file. The intent parser recognizes EN and ZH keywords.

## 7. Security & privacy notes

Full self-assessment: `docs/SECURITY.md`. In short:
- **Permission tiers:** T0 read-only (no writes/network except FX API),
  T1 local sqlite writes, T2 opt-in outbound notifications, T3 (money
  movement, credential handling) deliberately absent.
- **Data:** single local sqlite file; demo data is fictional; no telemetry.
- **Known risks:** FX outage → cache/fallback; alert spam → cooldowns;
  stale tables → dated `_note` fields + refresh guidance; the tool is an
  *estimator/advisor*, never a payment rail — declared in-app and in docs.

## 8. How this maps to the official scoring criteria (40/30/30)

- **Task completion (40%)** — all four official pain points
  (remittances, tuition, credit building, multi-currency) plus budgeting,
  alerts, forecasting and the multilingual assistant are implemented,
  tested (263 tests), and demoable via `scripts/demo.py`.
- **Security & compliance (30%)** — permission tiers by construction,
  local-only data, honest limitations, no money movement, and the
  `docs/SECURITY.md` self-assessment.
- **Innovation & interaction (30%)** — bilingual conversational UX over a
  deterministic rule engine; guides for the three hardest student tasks;
  burn-down pace and forecast messaging; zero-hallucination design (LLM
  only rephrases pre-computed numbers, off by default).
- On-chain challenge bonus (+0–5): not applicable to Topic C; not claimed.

## 9. Deliberately deferred (Phase 3)

Real LLM backend (one-line `LLMProvider` swap), additional languages,
credit-bureau integration (credit module is guidance + checklist only),
sqlite encryption, scheduled digest emails, and automated refresh of the
fee/fallback tables. Deferred for reliability and honest scope — not for
lack of design.
