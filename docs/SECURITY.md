# Security Self-Assessment — Cross Border Assistant

FinTechathon 2026 · International Track · Topic C · Deliverable 05
Date: 2026-10-18 · Version: 1.0

This document is the project's security self-assessment: permission tiers
(how much each component is allowed to do), data handling, known risks with
mitigations, and a full third-party component list.

## 1. Permission tiers

The codebase is deliberately layered so that **read-only components cannot
cause side effects**, and state-changing components are narrow and local.

| Tier | Components | Allowed actions |
|------|-----------|-----------------|
| T0 — read-only queries | `cba/fx` (rate lookups), `cba/assistant` chat handlers for `convert`, `budget_status`, `tuition_due` (read), `transfer_advice` (estimates), `forecast`, `guide` | Read sqlite, read JSON data files, call the public FX API. **No writes, no network calls except the FX API.** |
| T1 — local state changes | `cba/ledger.add`, `cba/budgets.set_budget`, `cba/tuition` CRUD, `cba/credit` checklist, `cba/alerts.create/deactivate`, FX cache writes | Write to the **local sqlite database file only** (`cba.db` by default). No network, no external services. |
| T2 — outbound notifications | `EmailNotifier` (smtplib), `WebhookNotifier` (HTTPS POST), `ConsoleNotifier` (stdout) | Send **alert text the user configured**. The email notifier is **inert unless SMTP credentials are provided** via environment (`CBA_SMTP_HOST`, `CBA_SMTP_TO`, …). The webhook notifier only fires when `CBA_WEBHOOK_URL` is set. |
| T3 — explicitly absent | — | **No real money movement.** The transfer module is a fee *estimator* over a static table (`data/fees.json`); it cannot initiate, authorize, or settle any payment. **No credit-bureau integration**; the credit module is guidance + a local checklist. **No credential collection** anywhere in the code. |

Enforcement is by construction: T0 functions take no notifier/db-write
paths; the `LLMProvider` integration is disabled by default
(`CBA_LLM_ENABLED=0`) and, when enabled, only *rephrases* rule-based
answers — numbers always come from T0 services, so an LLM can never
hallucinate a rate or balance into a user-facing figure.

## 2. Data handling

- **Storage:** everything lives in a single local sqlite file
  (`cba.db`, configurable via `CBA_DB_PATH`). No cloud sync, no analytics,
  no telemetry.
- **Personal data:** the demo ships with *fictional* data
  (`scripts/seed_demo.py`). Real deployments should treat the sqlite file
  as personal financial data: keep it on the user's device, do not commit
  it (it is in `.gitignore`), and delete it when the user asks.
- **Retention:** no retention policy is enforced in code (local-first tool).
  Deleting `cba.db` erases all user data. The FX cache (`fx_cache.json`)
  holds only public exchange rates.
- **Secrets:** there are none in the repository. SMTP credentials and the
  optional webhook URL are read from environment variables at runtime and
  never logged or printed.

## 3. Known risks and mitigations

| # | Risk | Likelihood / Impact | Mitigation |
|---|------|---------------------|------------|
| R1 | FX API (`open.er-api.com`) outage or rate change breaks conversions | Medium / Medium | Three-layer chain: live → local JSON cache (TTL `CBA_FX_CACHE_TTL`) → static fallback table (`data/fallback_rates.json`). The assistant degrades gracefully and says so instead of inventing numbers. |
| R2 | Alert spam (user gets flooded with notifications) | Low / Low | Per-alert cooldown (`CBA_ALERT_COOLDOWN`, default 24h); `last_triggered_at` persisted; `check()` skips alerts inside the cooldown window. |
| R3 | Stale fallback rates mislead a transfer decision | Low / Medium | Fallback file carries a dated `_note`; `FxService.trend()` shows direction so users see movement; README tells users to refresh the table. |
| R4 | Fee table (`data/fees.json`) becomes outdated | Medium / Low | All fees live in one reviewed JSON file with a `_note` review reminder; estimates show the method name so users can verify against the provider. |
| R5 | Misinterpreted as financial advice / real transfers | Low / High | The transfer module is labeled an *estimator* in UI text, README, and code; `safety_brief()` warns against unlicensed channels and structuring; no payment rails exist in the code. |
| R6 | LLM rephrasing alters a number (if enabled) | Low / Medium | LLM is off by default; when on, it only rephrases a pre-computed draft and failures fall back to the draft. |
| R7 | Local DB file read by another user on a shared machine | Low / Medium | Documented: keep `cba.db` in a private directory; future work could add sqlite encryption (see roadmap). |

## 4. Third-party components and licenses

| Component | Use | License |
|-----------|-----|---------|
| Python 3 standard library (`sqlite3`, `urllib`, `json`, `datetime`, `argparse`, `smtplib`, `unittest`, …) | Entire core | PSF License |
| `requests` (optional) | HTTP for FX API when installed; stdlib `urllib` fallback otherwise | Apache 2.0 |
| `pytest` (dev/test only) | Test runner alternative | MIT |
| open.er-api.com free exchange-rate API | Live FX rates, no key required | Free for use; rates © their providers (attribution: ExchangeRate-API) |
| This project's code | — | MIT (see `LICENSE`) — 100% original code written for this competition |

No SDKs, no analytics, no tracking, no bundled binaries.

## 5. Compliance notes (for judges)

- **Security & compliance (30% of scoring):** permission tiers above,
  local-only data, no money movement, no PII collection, graceful
  degradation, and this self-assessment constitute the compliance story.
- **Honest limitations:** FX fallback rates can go stale; fee tables need
  quarterly review; the credit module is educational only. All are stated
  in-app and in docs rather than hidden.
