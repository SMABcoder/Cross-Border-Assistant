# Cross Border Assistant

**FinTechathon 2026 · International Track · Topic C — Cross-border & Student Finance Assistant**

An AI-powered finance assistant for international students: cross-border payments,
currency exchange, tuition payment reminders, budgeting, **credit building**,
fee estimates, safe transfer methods, and monthly budget tracking.
Friendly, multilingual-ready (EN + ZH), and easy to use.

> **Competition deadline: 20 October 2026, 23:59 Beijing time.**

## The problem

International students face four concrete financial pain points (the official
Topic C scope): **remittances** (expensive, opaque transfer fees),
**tuition payments** (deadlines in foreign currencies, confusing channels),
**credit building** (arriving with no local credit file), and
**multi-currency management** (budgeting across two or more currencies).

## What this does

| Pain point | Feature |
|---|---|
| Remittances | Fee estimator + method comparison over an auditable fee table (`data/fees.json`), cheapest-first ranking, safety brief |
| Tuition payments | Bill tracking with reminders at 30/14/7/3/1 days + due-today + overdue, each with a step-by-step payment guide |
| Credit building | Educational step-by-step guide + sqlite checklist tracker with progress % (guidance only — no bureau integration, stated honestly) |
| Multi-currency management | Live FX (free no-key API) with cache + offline fallback, ledger normalized to a base currency, budgets with 80%/100% warnings and burn-down pace |
| Peace of mind | Target-rate alerts with per-alert cooldowns; spending forecast vs budget; bilingual chat assistant (EN/ZH) |

## Official deliverables 01–06 — where each lives

| # | Deliverable | Location |
|---|---|---|
| 01 | Technical documentation | This repo: `ARCHITECTURE.md` + `docs/` |
| 02 | Presentation deck | Produced separately (not in this repo) |
| 03 | Demo video (≤ 5 min, **required**) | Produced separately (not in this repo) |
| 04 | Source code + README + test cases (+ deployment instructions) | **This repo** — see Deployment below |
| 05 | Security self-assessment | `docs/SECURITY.md` |
| 06 | Execution evidence (sandbox logs) | `scripts/demo.py` → `evidence/demo-transcript-<UTC>.log` (one sample committed: `evidence/demo-transcript-sample.log`) |

## How this maps to the official scoring criteria

The competition scores all topics on three pillars (plus a 0–5 on-chain
challenge bonus, which does not apply to Topic C):

**1. Task completion — 40%.**
Every element of the official Topic C brief is implemented and demoable:
multi-currency exchange (`cba/fx`), personalized budgeting (`cba/budgets`),
target-based currency alerts (`cba/alerts`), tuition payment reminders
(`cba/tuition`), transfer comparisons with fee estimates and safe methods
(`cba/transfers`), credit-building guidance + checklist (`cba/credit`),
forecasting (`cba/forecast`), and the friendly multilingual assistant on top
(`cba/assistant`). Phase 1 (reliable core) was built before Phase 2
(intelligence), so the MVP works even fully offline. Run `python scripts/demo.py`
to see all of it end to end.

**2. Security & compliance — 30%.**
Permission tiers are enforced by construction: read-only query components
cannot write or reach the network (except the FX API); state changes are
confined to a local sqlite file; outbound notifications are inert unless the
user configures them; and **no real money ever moves** — transfers are
estimates over a static table, stated in-app and in docs. All data stays on
the user's machine (see `docs/SECURITY.md` for the full self-assessment:
tiers, data handling, known risks + mitigations, third-party licenses).

**3. Innovation & interaction — 30%.**
A bilingual (EN/ZH, extensible) conversational assistant with a rule-based
intent engine over nine intents, step-by-step guides for the three hardest
student tasks (paying tuition, sending money home, first-month budget) plus
credit building, burn-down pace messaging ("at this pace you will spend X"),
and a deterministic, no-hallucination design: numbers always come from the
services, never from a language model (the optional `LLMProvider` only
rephrases pre-computed answers and is off by default).

## 5-minute quickstart

Requires Python ≥ 3.10. No external services needed — the app runs fully
offline using the bundled fallback rates and fee table.

```bash
git clone <this-repo> && cd cross-border-assistant

# 1. See it all work (uses a temp DB + offline rates; also writes evidence/demo-transcript-<UTC>.log)
python scripts/demo.py

# 2. Seed a demo student into the local DB
python scripts/seed_demo.py

# 3. Exchange rates (live API, cached; offline fallback if unreachable)
python cba/cli.py rates --base USD --quote CNY
python cba/cli.py rates --base USD --quote CNY --trend

# 4. Track spending + budget
python cba/cli.py add-expense --amount 12.50 --currency USD --category food --note "lunch"
python cba/cli.py budget --set 2000 --currency USD
python cba/cli.py budget --set 400 --currency USD --category food
python cba/cli.py budget

# 5. Rate alerts (cron-friendly checker)
python cba/cli.py alert --create USD/CNY --target 7.30 --direction above
python scripts/check_alerts.py

# 6. Tuition reminders
python cba/cli.py tuition --add "Spring tuition" --amount 5200 --currency USD --due 2026-11-20 --payee "Example University"
python cba/cli.py tuition --remind

# 7. Compare transfer methods (cheapest first)
python cba/cli.py transfer --amount 500 --from USD --to CNY
python cba/cli.py transfer --amount 500 --from USD --to CNY --safety

# 8. Credit-building checklist
python cba/cli.py credit
python cba/cli.py credit --complete secured_card

# 9. Spending forecast
python cba/cli.py forecast

# 10. Chat (EN or ZH)
python cba/cli.py chat --message "convert 100 USD to CNY" --lang en
python cba/cli.py chat --message "how do I build credit?" --lang en
python cba/cli.py chat --message "convert 100 USD to CNY" --lang zh

# 11. Tests (146 tests, all offline-mocked)
python -m unittest discover -s tests
pip install pytest && python -m pytest -q
```

## Deployment

This application **runs locally with zero external services**:

- **Runtime:** Python ≥ 3.10, stdlib only (`sqlite3`, `urllib`, `json`,
  `datetime`, `argparse`, `smtplib`, `unittest`). `requests` is used only if
  already installed, with a `urllib` fallback. `pytest` is the sole dev
  dependency (test runner).
- **Storage:** one local sqlite file (`cba.db` in the project root;
  override with `CBA_DB_PATH`). Delete the file to erase all data.
- **Network (optional):** the FX layer calls the free no-key endpoint
  `https://open.er-api.com/v6/latest/{BASE}` (override with
  `CBA_FX_API_BASE`). If unreachable, it serves the local cache, then the
  bundled fallback table — the app never hard-fails for lack of network.
- **Notifications (optional):** email alerts need `CBA_SMTP_HOST`,
  `CBA_SMTP_PORT`, `CBA_SMTP_USER`, `CBA_SMTP_PASSWORD`, `CBA_SMTP_FROM`,
  `CBA_SMTP_TO`; webhook alerts need `CBA_WEBHOOK_URL`. Unset = console only.

Deploy steps (any machine with Python 3.10+):

```bash
git clone <this-repo> && cd cross-border-assistant
python scripts/seed_demo.py          # optional demo data
python scripts/demo.py               # verify everything works
# cron: check rate alerts every 10 minutes
*/10 * * * * cd /path/to/cross-border-assistant && python scripts/check_alerts.py
```

### Configuration reference (all `CBA_`-prefixed, all with defaults)

| Variable | Default | Meaning |
|---|---|---|
| `CBA_DB_PATH` | `./cba.db` | sqlite database file |
| `CBA_DATA_DIR` | `./data` | JSON data directory (fees, i18n, guides) |
| `CBA_FX_API_BASE` | `https://open.er-api.com/v6/latest` | rate API endpoint |
| `CBA_FX_CACHE_TTL` | `3600` | rate cache TTL (seconds) |
| `CBA_FX_TIMEOUT` | `10` | rate API timeout (seconds) |
| `CBA_APP_CURRENCY` | `USD` | default base currency |
| `CBA_SUPPORTED_CURRENCIES` | `USD,CNY,EUR,GBP,PKR,INR,JPY,SGD` | allowed currencies |
| `CBA_DEFAULT_CATEGORIES` | `tuition,rent,food,…` | expense categories |
| `CBA_BUDGET_WARN_PCT` | `80.0` | budget warning threshold |
| `CBA_BUDGET_BREACH_PCT` | `100.0` | budget breach threshold |
| `CBA_ALERT_COOLDOWN` | `86400` | per-alert notify cooldown (seconds) |
| `CBA_TUITION_REMINDER_THRESHOLDS` | `30,14,7,3,1` | days-before reminders |
| `CBA_FORECAST_MONTHS` | `3` | forecast history window |
| `CBA_FORECAST_RECENT_WEIGHT` | `0.5` | weight of most recent month |
| `CBA_FEES_PATH` | `./data/fees.json` | transfer fee table |
| `CBA_DEFAULT_LANG` | `en` | assistant language |
| `CBA_LLM_ENABLED` | `0` | enable LLM rephrasing (stub) |
| `CBA_SMTP_HOST/PORT/USER/PASSWORD/FROM/TO` | (empty) | email notifier |
| `CBA_WEBHOOK_URL` | (empty) | webhook notifier |

## Architecture

```
                    ┌─────────────────────────────┐
                    │        cba/cli.py           │  argparse: 9 subcommands
                    │      scripts/demo.py        │  walkthrough + evidence log
                    └──────────────┬──────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │      cba/assistant          │  Phase 2: intents, i18n (EN/ZH),
                    │  chat() · guides · LLM stub │  guides, friendly replies
                    └──────┬──────────────┬───────┘
                           │              │
        ┌──────────────────▼───┐   ┌──────▼────────────┐
        │   cba/forecast       │   │   Phase 1 core    │
        │   weighted projection│   │                   │
        └──────────────────────┘   │ fx · ledger       │
                                   │ budgets · alerts  │
                                   │ tuition · transfers│
                                   │ credit            │
                                   └──────┬────────────┘
                                          │
                    ┌─────────────────────▼────────────────────┐
                    │  sqlite (cba.db)   │  data/*.json         │
                    │  local only        │  fees · i18n · guides│
                    └──────────────────────────────────────────┘
```

Full design: [`ARCHITECTURE.md`](ARCHITECTURE.md) · Security: [`docs/SECURITY.md`](docs/SECURITY.md)

## CLI reference

| Command | Purpose |
|---|---|
| `rates` | Live rate / trend (`--base/--quote/--trend`) |
| `add-expense` | Record income/expense (`--amount/--currency/--category/--note/--date/--income`) |
| `budget` | Set (`--set/--currency/--category`) or view monthly budget |
| `alert` | Create/list/check/deactivate rate alerts |
| `tuition` | Add/list/pay tuition bills; `--remind` shows due notifications |
| `transfer` | Fee estimate (`--method`) or cheapest-first comparison; `--safety` prints the safety brief |
| `credit` | Credit-building checklist (`--complete/--uncomplete/--reset`) |
| `forecast` | Month-end spending projection (`--category/--json`) |
| `chat` | Talk to the assistant (`--message/--lang`), interactive if no message |

## Tests

146 tests mirroring every module (`tests/test_{config,fx,ledger,budgets,alerts,tuition,transfers,credit,assistant,forecast}.py`),
written as `unittest.TestCase` so they run under both runners:

```bash
python -m unittest discover -s tests   # stdlib, no install needed
python -m pytest -q                    # after pip install pytest
```

All network access is mocked (fake `RateProvider`); all DB tests use temp
sqlite files. CI (`.github/workflows/ci.yml`) runs both suites on
Python 3.10/3.11/3.12.

## Originality & licenses

- **100% original code**, written for this competition; MIT licensed (see `LICENSE`).
- No copied code, no generated boilerplate committed as-is, no plagiarized assets.
- Third-party items are listed in `docs/SECURITY.md`: Python stdlib (PSF),
  optional `requests` (Apache 2.0), `pytest` for tests (MIT), and the free
  open.er-api.com rate API (attribution: ExchangeRate-API).

## Roadmap (deliberately deferred)

- Real LLM backend behind the one-line `LLMProvider` swap (currently a stub).
- More languages: drop a new `data/i18n/<lang>.json` — no code changes.
- Optional credit-bureau integration for the credit module (currently guidance + checklist only, stated honestly).
- sqlite encryption for the local DB; push/email digest scheduling.
- Refresh cadence tooling for `data/fees.json` and `data/fallback_rates.json`.
