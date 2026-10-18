# Technical Documentation — Cross Border Assistant

**Project:** Cross Border Assistant — AI Cross-border & Student Finance Assistant
**Competition:** 2026 Shenzhen International FinTech Competition (FinTechathon), International Track, Topic C
**Theme:** "AI as a Financial Participant"
**Repository:** https://github.com/SyntexCodex/Cross-Border-Assistant (branch `main`)
**Version covered:** Phase 2 (263 automated tests, all passing)
**Language:** Python 3.10+ (stdlib only — no third-party runtime dependencies)

This document is deliverable **01** (technical documentation: architecture, core algorithms, security design). It is written from the shipped code, not from slides: every algorithm below names the module and function that implements it.

---

## 1. System overview

Cross Border Assistant is a personal finance agent for international students living between two financial systems. It watches exchange rates, tracks multi-currency spending, guards monthly budgets, reminds about tuition with step-by-step payment guides, compares remittance methods, coaches credit building, projects spending, times tuition payments against FX moves, and tracks China's individual FX quota — through a bilingual (English/Chinese) conversational assistant, a CLI, and a local web UI.

**The defining design decision:** the system is an *agent that acts*, not a chatbot that answers. Three autonomous loops run without the user — the rate watchdog, the tuition secretary, and the FX optimizer. And it draws a hard, honest line: **nothing in this system moves money.** Execution lives behind production-gated, inert adapters. That boundary is the security design (Section 4).

---

## 2. System architecture

### 2.1 Layered architecture

Five layers, each talking only to the one below it:

```
┌─────────────────────────────────────────────────────────────┐
│ INTERFACE        cba/cli.py — 13 commands                    │
│                  cba/web — stdlib http.server JSON API + chat│
│                  scripts/ — check_alerts, seed_demo, demo    │
├─────────────────────────────────────────────────────────────┤
│ INTELLIGENCE     cba/assistant/                              │
│                  IntentParser (13 intents, EN+ZH) → handlers │
│                  → GuideBook + i18n → reply + follow-up chips│
│                  llm.py — BYOK rephraser (off by default)   │
├─────────────────────────────────────────────────────────────┤
│ SERVICES         fx · ledger · budgets · alerts · tuition    │
│                  transfers · credit · forecast · optimizer   │
│                  quota · importer · rails (inert)            │
│                  Each owns one domain. The product works     │
│                  with no network and no LLM.                 │
├─────────────────────────────────────────────────────────────┤
│ DATA             cba.db (sqlite) — transactions, budgets,    │
│                  alerts, bills, checklist, quota records     │
│                  JSON — fees, guides, i18n EN/ZH, fallback   │
│                  rates, FX cache. No PII beyond demo data.   │
├─────────────────────────────────────────────────────────────┤
│ CONFIG           config.py — every tunable is a CBA_ env var │
│                  Zero hardcoded thresholds, URLs, timeouts.  │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 Module map

| Module | File | Responsibility |
|---|---|---|
| `config` | `config.py` | All tunables, `CBA_`-prefixed env overrides |
| `cba.common` | `cba/common.py` | sqlite helper, money formatting, `ProductionGatedError` |
| `cba.cli` | `cba/cli.py` | 13 subcommands (thin routing to services) |
| `cba.fx` | `cba/fx/__init__.py` | Rate provider chain: live → cache → fallback |
| `cba.ledger` | `cba/ledger/__init__.py` | sqlite income/expense ledger, base-currency summaries |
| `cba.budgets` | `cba/budgets/__init__.py` | Monthly limits, 80%/100% warnings, burn-down pace |
| `cba.alerts` | `cba/alerts/__init__.py` | Target-rate alerts, cooldown, pluggable notifiers |
| `cba.tuition` | `cba/tuition/__init__.py` | Bills, reminder thresholds, de-duplicated notifications |
| `cba.transfers` | `cba/transfers/__init__.py` | Fee estimator + cheapest-first comparison, safety brief |
| `cba.credit` | `cba/credit/__init__.py` | 7-step checklist, transparent score estimate, inert bureau adapter |
| `cba.forecast` | `cba/forecast/__init__.py` | Weighted projection + trend + seasonality index |
| `cba.optimizer` | `cba/optimizer/__init__.py` | PAY_NOW / WAIT / NO_SIGNAL tuition FX timing advice |
| `cba.quota` | `cba/quota/__init__.py` | Self-reported SAFE $50k annual FX quota tracker |
| `cba.importer` | `cba/importer/__init__.py` | CSV statement import, dry-run default, inert Open Banking adapter |
| `cba.rails` | `cba/rails/__init__.py` | **Inert** CIPS / e-CNY / mBridge adapters + ISO 20022 pain.001 builder |
| `cba.web` | `cba/web/__init__.py` | Localhost JSON API + chat page (stdlib http.server) |
| `cba.assistant` | `cba/assistant/` | IntentParser, handlers, GuideBook, i18n, LLM hook, conversation memory |

### 2.3 Data model (sqlite, `cba.db`)

- `transactions(id, date, kind, amount, currency, category, note)` — the ledger
- `categories(name, kind)` — seeded from config
- `budgets(month, category, limit_amount, currency)` — `__total__` = overall
- `rate_alerts(id, pair, base, quote, target, direction, note, created_at, last_triggered_at, active)`
- `alert_events(id, alert_id, rate, triggered_at)` — audit trail of firings
- `tuition_bills(id, name, amount, currency, due_date, payee, guide_ref, paid, created_at)`
- `tuition_notifications(id, bill_id, kind, notified_on)` — UNIQUE(bill_id, kind, notified_on) de-duplicates
- `credit_checklist(item_key, label, done, sort_order)`
- `quota_transfers(id, date, amount, currency, amount_usd, note)` — self-reported

### 2.4 Key flows

**Chat request** (`Assistant.chat`):
`text → IntentParser.parse → _followup_rewrite (multi-turn context) → handler → service → reply → follow-up chips → optional LLM rephrase (numbers untouched)`

**Alert loop** (`scripts/check_alerts.py`, cron every 5–15 min):
`load active alerts → for each: cooldown expired? → get_rate → target hit? → record trigger → notify (console/email/webhook) → print summary`

**Tuition optimization** (`OptimizerService.optimize`):
`unpaid bills → today's rate vs trailing average (CBA_OPTIMIZER_LOOKBACK_DAYS) → diff vs CBA_OPTIMIZER_SIGNAL_PCT → PAY_NOW / WAIT / NO_SIGNAL + reason + matching alerts`

**CSV import** (`CsvImporter.import_file`):
`auto-detect headers → parse rows → rule-based categorization → --dry-run preview (default) → --apply writes`

### 2.5 Deployment

No build step, no dependencies to install: `python3 -m cba.cli <command>`. State is one sqlite file (`CBA_DB_PATH`, default `./cba.db`). The web UI (`cba serve`) binds `127.0.0.1` by default. CI runs the 263-test suite on every push.

---

## 3. Core algorithms

### 3.1 FX provider chain (`cba/fx/__init__.py` — `FxService`)

**Problem:** rates must be available even offline; a demo that dies without Wi-Fi is a toy.

**Algorithm:** three providers chained, each catching the previous one's failure.
1. `SimpleApiProvider` — live JSON from `open.er-api.com` (free, no key; URL/timeout configurable).
2. `CachedProvider` — JSON file cache with TTL (`CBA_FX_CACHE_TTL`, default 3600s). Writes atomically (temp file + rename). Also appends up to 60 historical snapshots per base currency, which powers `trend()` offline.
3. `FallbackTableProvider` — static table from `data/fallback_rates.json`; always answers, clearly dated.

`get_rate(base, quote)` returns 1.0 for same-currency; otherwise looks up the chained table. `trend()` compares the newest vs oldest cached snapshot (±0.05% deadband → up/down/flat).

### 3.2 Intent parsing (`cba/assistant/intents.py` — `IntentParser.parse`)

**Problem:** understand free text in English and Chinese without an ML model (deterministic, testable, offline).

**Algorithm:** an ordered cascade — specific patterns first, broad keywords last:
1. Alert regex (`USD/CNY above 7.3` + alert keywords).
2. New intents: optimize ("should I pay" + tuition words), quota, import (CSV path regex), serve_web.
3. Credit, tuition, guide (with guide-topic routing: pay_tuition / send_money_home / credit_building / first_month_budget).
4. Transfer advice (currency-pair + amount extraction).
5. Explicit conversion pattern (`100 USD to CNY`).
6. Forecast, budget, help.
7. Fallback: two currencies mentioned → conversion at confidence 0.6; else help at 0.4.

Multi-turn context (`Assistant._followup_rewrite`): terse follow-ups like "and for food?" / "那学费呢？" resolve against the previous turn's topic (budget/forecast), validated against the configured category list.

### 3.3 Budget warnings and burn-down pace (`cba/budgets/__init__.py` — `BudgetService.status`)

**Algorithm:** ledger expenses for the month are converted to the base currency and compared against the stored limit (overall `__total__` key plus per-category keys):
- `pct ≥ CBA_BUDGET_WARN_PCT` (80) → warning; `≥ CBA_BUDGET_BREACH_PCT` (100) → breach.
- **Pace projection:** `projected = spent / elapsed_days × days_in_month`, reported as "at this pace you will spend X by month-end." Simple, transparent, no model to mistrust.

### 3.4 Forecasting (`cba/forecast/__init__.py` — `ForecastService.monthly_projection`)

**Algorithm (three parts, all transparent arithmetic):**
1. **Weighted moving average** over the trailing `CBA_FORECAST_MONTHS` (default 3): geometric weights favor recent months (`CBA_FORECAST_RECENT_WEIGHT`, default 0.5), remainder folded into the oldest month.
2. **Linear trend:** slope from oldest → newest month added to the average.
3. **Seasonality index:** the target calendar month's historical share = (average expense in that calendar month across the trailing 12) ÷ (overall monthly average). **Engages only with ≥180 days and ≥6 distinct months of history; otherwise the factor is exactly 1.0**, keeping short-history projections bit-identical to the plain formula.

The projection is compared against the budget limit → verdict "on track" / "will exceed budget (by X)". `category_daily_burn()` gives per-category daily spend over a trailing window.

### 3.5 Tuition FX optimizer (`cba/optimizer/__init__.py` — `OptimizerService.optimize`)

**Problem:** *when* should a student pay a foreign-currency tuition bill?

**Algorithm (advisory only):** for each unpaid bill, fetch today's rate for `APP_CURRENCY/bill_currency` and the trailing average from cached snapshots over `CBA_OPTIMIZER_LOOKBACK_DAYS` (default 30):
- Rate semantics: the pair is quoted as foreign-per-base (USD/CNY = 7.32). A **higher** rate means the foreign currency is **cheaper** — a good moment to pay.
- `diff ≥ +CBA_OPTIMIZER_SIGNAL_PCT` (1.0%) → **PAY_NOW**; `≤ −1.0%` → **WAIT**; else **NO_SIGNAL** (also for same-currency bills, missing rates, or <2 history points).
- Each result carries its numbers, a human reason, and any matching rate alerts the user already watches.

### 3.6 Transfer comparison (`cba/transfers/__init__.py` — `FeeEstimator`)

**Algorithm:** all fee data lives **only** in `data/fees.json` (zero hardcoded fees — a standing project rule). For each of the 6 methods (Wise, Remitly, Western Union, PayPal, bank wire/SWIFT, campus partner counter):
```
total_cost = fixed_fee + amount × pct_fee/100 + FX_margin
FX_margin  = amount × mid_rate × (margin_bps / 10_000)
receive    = (amount − fee) × mid_rate × (1 − margin_bps/10_000)
```
`compare()` ranks methods by total cost, then ETA. Every comparison ships with `safety_brief()`: licensed channels only, verify recipient details, never structure transfers ("ants moving"), keep receipts, ignore social-media "better rates" (the most common student scam).

### 3.7 Alert evaluation with cooldown (`cba/alerts/__init__.py` — `AlertService.check`)

**Algorithm:** for each active alert: skip if `now − last_triggered_at < CBA_ALERT_COOLDOWN` (default 24h — the anti-spam guarantee); fetch the rate (failures skip to next cycle, never crash the loop); `hit = rate ≥ target` for "above", `≤` for "below"; on hit, persist the trigger + an `alert_events` audit row, then fan out to all configured notifiers (console always; email only if SMTP configured; webhook if URL given). Returns which alerts fired and whether anyone was notified.

### 3.8 Tuition reminders (`cba/tuition/__init__.py` — `due_notifications` / `pending_notifications`)

**Algorithm:** for each unpaid bill, `days_left = due − today` → `overdue` (<0), `due_today` (0), or `due_in_N` when N ∈ `CBA_TUITION_REMINDER_THRESHOLDS` ([30, 14, 7, 3, 1]). Each notification carries a `guide_ref` (default `pay_tuition`) linking the step-by-step guide. `record_sent()` uses the UNIQUE(bill_id, kind, notified_on) constraint so a reminder is never sent twice — `pending_notifications()` returns only unsent ones.

### 3.9 CSV import (`cba/importer/__init__.py` — `CsvImporter`)

**Algorithm:** headers auto-detected against an alias map (overridable per-column, or detection off via config). Two amount semantics: debit/credit column pairs (`net = credit − debit`); single amount column uses a **documented heuristic** — negatives are expenses, positives are expenses too (typical card statement) unless the description matches income keywords (salary, refund, deposit…). Every row is categorized by configurable keyword rules (`CBA_IMPORT_CATEGORY_RULES`). **Dry-run is the default**: the user previews all rows, categories and amounts; `--apply` writes. Zero-amount and unparseable rows are skipped, never fatal.

### 3.10 Credit score estimator (`cba/credit/__init__.py` — `CreditService.estimate_score`)

**Algorithm (deliberately trivial and transparent):** `estimate = min(550 + 25 × items_done, 800)` — base, per-item points and cap all configurable. The result shows its full math and carries an explicit disclaimer: *"Rough educational estimate from checklist progress only. Not a bureau score."* Real bureau data is represented by the `BureauAdapter` protocol; `InertBaihangAdapter.fetch_report` raises `ProductionGatedError` — the prototype never contacts bureaus and handles no identity documents.

### 3.11 Quota tracking (`cba/quota/__init__.py` — `QuotaService`)

**Algorithm:** user-recorded transfers are converted to USD at record time and summed per calendar year against `CBA_QUOTA_ANNUAL_USD` (default 50,000 — China's individual FX quota). 80% → warning, 100% → exceeded. Every user-facing string states the tracker is **self-reported** and names the bank's official statement as authoritative.

### 3.12 ISO 20022 message builder (`cba/rails/__init__.py` — `build_pain001`)

**Algorithm:** constructs a `pain.001.001.03` CustomerCreditTransferInitiation XML document (group header, payment info, debtor/creditor parties and agents, amount with currency attribute, optional remittance info) via `xml.etree`. **Format generation only** — the XML is never transmitted, signed, or settled. `validate_bic()` checks ISO 9362 format (format only, not existence).

### 3.13 LLM rephrasing (`cba/assistant/llm.py` — `OpenAICompatibleProvider`)

**Design, not magic:** the provider (stdlib `urllib`, OpenAI-compatible `/chat/completions`) only *rephrases* the already-computed deterministic answer. Numbers are computed by the services and embedded in the prompt; the model never computes a rate or balance, so it cannot hallucinate one. The key is read per call, never cached, never logged — error paths redact it (dedicated leak test). Key unset (default) → byte-identical deterministic behavior, no network.

---

## 4. Security design

### 4.1 Permission tiers (enforced by construction, not by promise)

| Tier | Can do | Cannot do | Examples |
|---|---|---|---|
| **1 · Read** | Query state, compute estimates | Write anything, touch the network¹ | `rates`, `transfer` compare, `forecast`, `optimize` |
| **2 · Write** | Persist to local sqlite | Leave the machine | ledger, budgets, alerts, bills, checklist, quota |
| **3 · Network** | Read FX API; send notifications | Move money, hold credentials | `SimpleApiProvider`, notifiers |

¹ except the FX API read. The components that *think* can never be the components that *pay* — there is no code path from intent to money movement.

### 4.2 The production gate

`ProductionGatedError` (in `cba/common.py`) is raised by every integration that would require a license: payment rails (`CipsRail`, `EcnYRail`, `MBridgeRail`), the credit bureau adapter, the Open Banking adapter. The gate is double: disabled `CBA_RAILS_PRODUCTION` → `ProductionGatedError`; enabled but unimplemented → `NotImplementedError`. **There is no configuration under which this prototype moves money.**

### 4.3 Data handling

- All state is local: one sqlite file + JSON. No accounts, no cloud sync, no telemetry.
- No PII beyond user-entered demo data. No passwords, no bank credentials anywhere in code, config, or logs.
- The LLM key (BYOK) is read per call, never printed, never logged, redacted from errors.
- The web UI binds `127.0.0.1` by default with no auth — documented as localhost-demo only; any internet exposure requires a reverse proxy (TLS) + auth first.

### 4.4 Honest-simulation rules

1. Transfer output is labeled an **estimator** in UI text, README, and code.
2. The quota tracker labels itself **self-reported** on every screen.
3. The credit score is labeled an **ESTIMATE** with its math shown.
4. `build_pain001` docstrings state the XML is never transmitted or settled.
5. The safety brief teaches licensed channels and names structuring ("ants moving") as illegal.

### 4.5 Known risks and mitigations

| ID | Risk | Mitigation |
|---|---|---|
| R1 | FX API outage | Live → cache → fallback chain; degrades gracefully, never invents numbers |
| R2 | Alert spam | Per-alert 24h cooldown, persisted `last_triggered_at` |
| R3 | Stale fallback rates mislead | Fallback file dated; `trend()` shows direction; README says refresh |
| R4 | Fee table outdated | Single reviewed `fees.json`; method names shown so users can verify |
| R5 | Mistaken for real transfers / advice | Labeled estimator everywhere; safety brief; no rails exist |
| R6 | LLM alters a number | Off by default; rephrase-only; failures fall back to the draft |
| R7 | DB file readable on shared machine | Documented: keep `cba.db` private; sqlite encryption is roadmap |
| R8 | Web UI exposed beyond localhost | Binds 127.0.0.1; reverse-proxy + auth required before any exposure |
| R9 | CSV import mis-reads a statement | Dry-run default; preview before `--apply`; heuristic documented in-app |
| R10 | Quota tracker mistaken for bank record | "Self-reported" on every screen; bank statement named authoritative |
| R11 | LLM key leaks via logs/errors | Never logged/printed; redacted in errors; dedicated leak test |

### 4.6 Compliance notes (for judges)

- **Task completion (40%):** every claimed feature is runnable and tested (263 tests).
- **Security & compliance (30%):** tiered architecture, inert rails, honest simulation, safety education, no credential handling.
- **Innovation (30%):** agentic loops (not a chatbot), bilingual, China-specific features (SAFE quota, CIPS/e-CNY/mBridge path, ISO 20022 readiness).

---

## 5. Configuration reference (selected)

All values overridable via `CBA_` env vars; defaults shown.

| Variable | Default | Meaning |
|---|---|---|
| `CBA_APP_CURRENCY` | `USD` | Base currency for summaries |
| `CBA_FX_CACHE_TTL` | `3600` | FX cache lifetime (seconds) |
| `CBA_BUDGET_WARN_PCT` / `CBA_BUDGET_BREACH_PCT` | `80` / `100` | Budget warning thresholds |
| `CBA_ALERT_COOLDOWN` | `86400` | Min seconds between firings per alert |
| `CBA_TUITION_REMINDER_THRESHOLDS` | `30,14,7,3,1` | Reminder days before due date |
| `CBA_OPTIMIZER_LOOKBACK_DAYS` / `CBA_OPTIMIZER_SIGNAL_PCT` | `30` / `1.0` | Optimizer window and signal band |
| `CBA_QUOTA_ANNUAL_USD` | `50000` | SAFE individual annual FX quota |
| `CBA_LLM_API_KEY` / `CBA_LLM_BASE_URL` / `CBA_LLM_MODEL` | unset / openai / `gpt-4o-mini` | BYOK LLM (off when key unset) |
| `CBA_RAILS_PRODUCTION` | `false` | Rail gate — prototype stays inert |
| `CBA_WEB_HOST` / `CBA_WEB_PORT` | `127.0.0.1` / `8000` | Local web UI bind |

Full list: `config.py` (`config.summary()` prints the effective configuration).

---

## 6. Testing and verification

- **263 tests**, `python3 -m unittest discover -s tests` — all passing, offline (network mocked, temp DBs).
- Coverage per module: assistant 35+, credit 18+, alerts 16+, tuition 15+, fx 14+, transfers 11+, ledger 10+, budgets 10+, config 9+, forecast 8+, plus optimizer/importer/web/rails/quota/llm suites.
- Dedicated tests for the boundaries: LLM key never leaks into errors; rails raise instead of acting; quota math; optimizer signals; dry-run writes nothing.
- The demo video (`demo-video/`) is generated from real CLI output — the evidence is reproducible, not staged.

## 7. Boundaries and roadmap

**What this system will not do** (by design): move money, hold bank credentials, contact payment rails or bureaus, give regulated financial advice. The production path for real execution is: licensed bank partner → ISO 20022 messaging over SWIFT gpi → CIPS for CNY clearing → e-CNY/mBridge as those rails mature. The permission tiers, the inert adapters, and the audit-ready ledger exist so that handoff requires an adapter, not a rewrite.
