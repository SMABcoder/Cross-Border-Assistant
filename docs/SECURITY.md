# Security Self-Assessment — Cross Border Assistant

FinTechathon 2026 · International Track · Topic C · Deliverable 05
Date: 2026-10-19 · Version: 2.0 (covers Phase 2: optimizer, quota, importer,
web UI, rails adapters, BYOK LLM, credit estimator)

This document is the project's security self-assessment: what we protect,
how much each component is allowed to do (permission tiers), how the tiers
are implemented in code, data handling, known risks with mitigations, and a
full third-party component list.

## 1. Scope and threat model

**What we protect:**
- The user's financial records (`cba.db`: transactions, budgets, bills,
  alerts, quota entries) — personal data that must stay on their machine.
- Credentials the user configures (SMTP password, webhook URL, LLM API key)
  — read from environment, never stored in the repo or logs.
- The integrity of advice the system gives (rates, estimates, signals) —
  numbers must come from real computation, never invented.

**Who we defend against:**
- Another user on a shared machine reading `cba.db` (R7).
- Network failure or tampering between us and the FX API (R1) — we degrade
  to cache/fallback rather than invent numbers.
- The user mistaking simulation for reality (R5, R10) — every estimate,
  quota figure, and score is labeled as such, in-app and in docs.
- An operator exposing the demo web UI to the internet (R8, R13).
- Social-engineering of the user via transfer scams — countered with the
  safety brief, not with code.

**What is explicitly out of scope for this prototype:** live money movement,
live bank/bureau/rail integrations (all represented by inert, gated
adapters), multi-user authentication (single local user), and protection
against an attacker with root access to the user's own machine.

## 2. Permission tiers — implementation

The codebase is deliberately layered so that **read-only components cannot
cause side effects**, and state-changing components are narrow and local.

| Tier | Components | Allowed | Forbidden (by construction) |
|------|-----------|---------|------------------------------|
| T0 — read-only queries | `cba/fx` lookups, assistant handlers for `convert`, `budget_status`, `tuition_due` (read), `transfer_advice` (estimates), `forecast`, `guide`, `optimize`, `quota` (read) | Read sqlite, read JSON data files, call the public FX API | No writes, no network except the FX API. The optimizer is advisory-only: it compares rates and prints signals, never acts on them. |
| T1 — local state changes | `cba/ledger.add`, `cba/budgets.set_budget`, `cba/tuition` CRUD, `cba/credit` checklist, `cba/alerts.create/deactivate`, `cba/quota.record`, `cba/importer.import_file` (only with `--apply`), FX cache writes, `cba/web` request handlers | Write to the **local sqlite file only** (`cba.db` default) | No network, no external services. The web server binds `127.0.0.1` by default and serves only this local data; no auth by design for localhost demos — internet exposure requires a reverse proxy (TLS) + auth first (documented in `cba/web`). |
| T2 — outbound notifications | `EmailNotifier` (smtplib), `WebhookNotifier` (HTTPS POST), `ConsoleNotifier` (stdout) | Send **alert text the user configured** | Email notifier is **inert unless SMTP credentials are provided** via environment (`CBA_SMTP_HOST`, `CBA_SMTP_TO`, …). Webhook fires only when `CBA_WEBHOOK_URL` is set. |
| T3 — explicitly absent | — | — | **No real money movement.** Transfers are fee *estimates* over a static table (`data/fees.json`); the module cannot initiate, authorize, or settle any payment. The `cba/rails` adapters (CIPS / e-CNY / mBridge) are **inert by construction**: every rail-touching method raises `ProductionGatedError` while `CBA_RAILS_PRODUCTION` is unset, and `NotImplementedError` even when set (the licensed integration does not exist). `build_pain001` generates ISO 20022 message *text* only — generation is not transmission, signing, or settlement. **No credit-bureau integration** (`InertBaihangAdapter` refuses all calls). **No live bank feeds** (`InertOpenBankingAdapter` refuses all calls). **No credential collection** anywhere. |

**How enforcement works in code (not just policy):**
- T0 functions receive no notifier objects and no write-capable handles;
  e.g. `OptimizerService.optimize()` returns data — the CLI prints it.
- The double gate in `cba/rails` (`_require_production()`): gate 1 raises
  `ProductionGatedError` when `CBA_RAILS_PRODUCTION` is unset; gate 2 raises
  `NotImplementedError` even when set — there is **no configuration under
  which this prototype moves money** (R14).
- The `LLMProvider` is disabled by default (`CBA_LLM_ENABLED=0`); when
  enabled via BYOK it only *rephrases* pre-computed answers — numbers always
  come from T0 services, so a model can never hallucinate a rate or balance
  into a user-facing figure. The key is read per call, never logged, never
  printed, never in error text (dedicated leak test, R11).
- The CSV importer defaults to `--dry-run`: preview before any write (R9).
- The web API has no auth **by design for localhost demos** and refuses to
  be useful beyond the local machine unless the deployer fronts it with a
  reverse proxy + auth (R8, R13).

## 3. Data handling

- **Storage:** everything lives in a single local sqlite file
  (`cba.db`, via `CBA_DB_PATH`). No cloud sync, no analytics, no telemetry.
- **Personal data:** the demo ships with *fictional* data
  (`scripts/seed_demo.py`). Real deployments should treat the sqlite file
  as personal financial data: keep it on the user's device, do not commit
  it (it is in `.gitignore`), delete it on request.
- **Retention:** none enforced in code (local-first tool). Deleting `cba.db`
  erases all user data. The FX cache (`fx_cache.json`) holds only public
  exchange rates.
- **Secrets:** none in the repository. SMTP credentials, webhook URL, and
  the LLM key are read from environment at runtime and never logged.

## 4. Known risks and mitigations

| # | Risk | Likelihood / Impact | Mitigation | Status |
|---|------|---------------------|------------|--------|
| R1 | FX API outage breaks conversions | Medium / Medium | Live → cache → fallback chain; degrades gracefully, never invents numbers | Implemented, tested |
| R2 | Alert spam floods the user | Low / Low | Per-alert 24h cooldown (`CBA_ALERT_COOLDOWN`); `last_triggered_at` persisted | Implemented, tested |
| R3 | Stale fallback rates mislead a decision | Low / Medium | Fallback file dated; `trend()` shows direction; README says refresh | Implemented |
| R4 | Fee table becomes outdated | Medium / Low | Single reviewed `fees.json`; method names shown so users can verify | Implemented |
| R5 | Mistaken for financial advice / real transfers | Low / High | Labeled *estimator* in UI, README, code; `safety_brief()` warns against unlicensed channels and structuring; no rails exist | Implemented |
| R6 | LLM rephrasing alters a number (if enabled) | Low / Medium | Off by default; rephrase-only; failures fall back to the draft | Implemented, tested |
| R7 | Local DB read by another user on shared machine | Low / Medium | Documented: keep `cba.db` private; sqlite encryption is roadmap | Documented |
| R8 | Web UI exposed beyond localhost | Low / High | Binds `127.0.0.1`; no-auth by design for localhost only; reverse proxy + auth required before any exposure | Implemented + documented |
| R9 | CSV import mis-reads a statement | Medium / Low | `--dry-run` default; preview before `--apply`; heuristic documented in-app | Implemented, tested |
| R10 | Quota tracker mistaken for the bank record | Low / Medium | "Self-reported" on every screen; bank statement named authoritative | Implemented |
| R11 | LLM API key leaks via logs/errors | Low / High | Read per call, never logged/printed; redacted in errors; dedicated leak test | Implemented, tested |
| R12 | Optimizer timing signal treated as professional advice | Low / Medium | Signals labeled advisory-only; each shows its numbers and reason; never executes; UI + docstrings state the boundary | Implemented |
| R13 | Operator binds web UI to a public interface | Low / High | Default `127.0.0.1`; code comments + README + DEVELOPMENT.md all require reverse proxy (TLS) + per-user auth before internet exposure | Documented |
| R14 | Operator enables `CBA_RAILS_PRODUCTION` expecting live rails | Low / High | Double gate: enabled-but-unimplemented still raises `NotImplementedError`; every adapter docstring states the licensed integration does not exist | Implemented, tested |
| R15 | Prompt injection via chat text into the LLM rephraser | Low / Medium | Model receives a fixed draft + "rephrase without changing numbers"; any failure returns the original draft; LLM off by default | Implemented |

## 5. Third-party components and licenses

| Component | Use | License |
|-----------|-----|---------|
| Python 3 standard library | Entire core | PSF License |
| `requests` (optional) | FX HTTP when installed; `urllib` fallback otherwise | Apache 2.0 |
| `pytest` (dev/test only) | Test runner alternative | MIT |
| open.er-api.com free rate API | Live FX rates, no key | Free; rates © their providers |
| This project's code | — | MIT — 100% original, written for this competition |

No SDKs, no analytics, no tracking, no bundled binaries.

## 6. Residual risks (accepted)

- R7: file-level protection of `cba.db` relies on OS permissions until
  sqlite encryption lands on the roadmap.
- R3/R4: fallback rates and fee tables need periodic human review; the code
  cannot verify the real world by itself.
- The prototype has no authentication because it has no network users; any
  multi-user or hosted deployment must add auth before handling real data.

## 7. Compliance notes (for judges)

- **Security & compliance (30% of scoring):** the tiers above, local-only
  data, no money movement, no PII collection, graceful degradation, the
  R1–R15 register, and this assessment constitute the compliance story.
- **Honest limitations:** FX fallback rates can go stale; fee tables need
  quarterly review; the credit score is a labeled estimator, not a bureau
  score; the quota tracker is self-reported; the optimizer advises but never
  executes; the rails adapters are inert. All are stated in-app and in docs
  rather than hidden.
