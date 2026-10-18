# Cross Border Assistant — Step-by-Step Testing Guide

How to verify **every automated test** and **every feature**, in order.
No dependencies to install for testing — the core is Python stdlib only
(Python 3.10+). All commands run from the repo root.

> Data note: the CLI and scripts store demo data in `./cba.db`
> (override with the `CBA_DB_PATH` env var). Nothing leaves your machine.

---

## 0. Setup (one time)

```bash
cd cross-border-assistant
python3 --version        # expect 3.10 or newer
```

Optional, for CI parity: `pip install pytest` (the suite also runs under pytest).

To start every manual test from a clean slate:

```bash
rm -f cba.db
```

---

## Part A — Automated tests (146 tests, ~1 second)

```bash
python3 -m unittest discover -s tests
```

Expected output (last lines):

```
Ran 146 tests in 0.361s

OK
```

What each file covers:

| Test file | What it verifies |
|---|---|
| `test_fx.py` | Rate lookup, conversion math, provider → cache → offline-fallback chain, trend summary. Network is **mocked** — no live calls. |
| `test_ledger.py` | Add/list income & expenses, monthly summary, FX normalization to base currency. Uses temp DBs. |
| `test_budgets.py` | Budget set/get, per-category + total status, 80% warning / 100% breach, burn-down pace message. |
| `test_alerts.py` | Alert create/list/deactivate, above/below triggering, per-alert cooldown (no duplicate spam), notifier dispatch. |
| `test_tuition.py` | Bill CRUD, mark-paid, reminders at 30/14/7/3/1 days + due-today + overdue, guide attached to each reminder. |
| `test_transfers.py` | Fee math per method, cheapest-first ranking, ETA present, safety brief content. Fees come only from `data/fees.json`. |
| `test_credit.py` | Checklist progress %, complete/uncomplete/reset, guide content, `credit_advice` intent wiring. |
| `test_assistant.py` | All 9 intents route correctly (incl. tricky phrasings), EN + ZH replies render, guides load, unknown input → helpful fallback. |
| `test_forecast.py` | Projection math from seeded history, on-track vs will-exceed messaging. |
| `test_config.py` | Every tunable has a default and honors its `CBA_` env override. |

If anything fails, the failure names the exact module and case — fix forward,
never delete a test to make it pass.

---

## Part B — Feature tests, step by step (CLI)

Seed realistic demo data first (idempotent; safe to re-run):

```bash
python3 scripts/seed_demo.py
```

### 1. Exchange rates (`rates`)

```bash
python3 -m cba.cli rates --base USD --quote CNY
# expect: 1 USD = 6.6985 CNY  (live value varies; format is the check)

python3 -m cba.cli rates --base USD --quote CNY --trend
# expect: pair, current rate, direction (up/down/flat), change %
```

Kill the network to verify resilience: the second run should still answer
from cache, and with cache expired it falls back to `data/fallback_rates.json`.

### 2. Income & expenses (`add-expense`)

```bash
python3 -m cba.cli add-expense --income --amount 1800 --currency USD --category other --note "stipend"
# expect: Recorded income #N: $1,800.00 [other]

python3 -m cba.cli add-expense --amount 12.50 --currency USD --category food --note "lunch"
# expect: Recorded expense #N: $12.50 [food]
```

### 3. Budgets (`budget`)

```bash
python3 -m cba.cli budget --set 1500 --currency USD
python3 -m cba.cli budget --set 300 --currency USD --category food
python3 -m cba.cli budget
```

Expect: total spent/limit with %, per-category lines, `⚠️` warnings at 80%,
breach notice at 100%, and a `📈` pace line ("at this pace you will spend X
by month-end").

### 4. Target-rate alerts (`alert` + alert loop)

```bash
python3 -m cba.cli alert --create USD/CNY --target 7.30 --direction above
python3 -m cba.cli alert            # lists it
python3 -m cba.cli alert --check    # evaluates against live rate
```

Then the cron-style loop (this is what a scheduler would run every 15 min):

```bash
python3 scripts/check_alerts.py
# expect: "1 checked, 0 triggered" (or a 🔔 line if the target is hit)
```

Run `--check` twice in a row: the second run must NOT re-notify
(per-alert cooldown — check the test in `test_alerts.py`).

Deactivate: `python3 -m cba.cli alert --deactivate 1`

### 5. Tuition reminders (`tuition`)

```bash
python3 -m cba.cli tuition --add "Spring tuition" --amount 5000 --currency USD --due 2026-11-20 --payee "Example University"
python3 -m cba.cli tuition          # lists bills with [unpaid]
python3 -m cba.cli tuition --remind # reminders only fire inside 30/14/7/3/1-day windows + due-today + overdue
python3 -m cba.cli tuition --paid 1 # mark paid; --remind goes quiet for it
```

Each reminder prints a `📅` line plus `Guide:` pointing at the
step-by-step tuition guide.

### 6. Transfer comparison (`transfer`)

```bash
python3 -m cba.cli transfer --amount 500 --from USD --to CNY
```

Expect 6 methods ranked cheapest-first (Wise / Remitly / Western Union /
PayPal / Bank wire (SWIFT) / Campus partner counter), each with receive
amount, total cost, ETA.

```bash
python3 -m cba.cli transfer --amount 500 --from USD --to CNY --method Wise
python3 -m cba.cli transfer --amount 500 --from USD --to CNY --safety
```

Expect: single-method breakdown, then the safety brief (licensed channels,
verify recipient, keep receipts, never split transfers to dodge limits).

### 7. Credit building (`credit`)

```bash
python3 -m cba.cli credit
# expect: Credit-building checklist: 0/7 (0%) with 7 ⬜ items

python3 -m cba.cli credit --complete secured_card
python3 -m cba.cli credit
# expect: 1/7 (14%), secured_card now ✅
```

### 8. Forecast (`forecast`)

```bash
python3 -m cba.cli forecast
python3 -m cba.cli forecast --category food
```

Expect a `🔮` line: projected month-end total vs budget ("on track" or
"will exceed budget by X"). Needs 2+ months of history — `seed_demo.py`
provides it.

### 9. Assistant chat (`chat`, EN + ZH)

One-shot mode (best for testing):

```bash
python3 -m cba.cli chat --message "convert 100 USD to CNY"
python3 -m cba.cli chat --message "how is my budget looking?"
python3 -m cba.cli chat --message "cheapest way to send 500 USD to CNY"
python3 -m cba.cli chat --message "when is my tuition due?"
python3 -m cba.cli chat --message "guide me through paying tuition"
python3 -m cba.cli chat --message "will I exceed my budget?"
python3 -m cba.cli chat --message "how do I build credit here?"
python3 -m cba.cli chat --message "help"
```

Chinese mode:

```bash
python3 -m cba.cli chat --lang zh --message "100美元能换多少人民币"
```

Expect: friendly replies with formatted numbers, follow-up suggestions,
and a helpful fallback (not an error) for anything it doesn't understand.
Interactive mode: `python3 -m cba.cli chat` (type `quit` to exit).

---

## Part C — End-to-end demo (11 sections, ~30 seconds)

```bash
python3 scripts/demo.py
```

This walks through **every feature** in one run — rates, ledger, budgets,
alerts, tuition, transfers, credit, forecast, and chat in EN + ZH — and
writes a full transcript to `evidence/demo-transcript-<UTC-timestamp>.log`
(deliverable 06 execution evidence). A committed sample lives at
`evidence/demo-transcript-sample.log`.

---

## Part D — Alert loop as a scheduled job

```bash
# every 15 minutes via cron:
*/15 * * * * cd /path/to/cross-border-assistant && python3 scripts/check_alerts.py >> alerts.log 2>&1
```

`check_alerts.py` is a one-shot: loads active alerts, evaluates them,
dispatches notifications (console by default; SMTP/webhook only if
configured), exits. Cooldowns prevent repeat notifications.

---

## Reset

```bash
rm -f cba.db fx_cache.json
python3 scripts/seed_demo.py   # fresh demo data whenever you want it
```

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `rates` hangs or errors | No network — wait for cache/fallback path; check `CBA_FX_TIMEOUT` |
| Tests fail on FX | A test hitting the network means a mock is missing — tests must never call the live API |
| `budget` shows "no limit set" | Run `budget --set` first (budgets are per-month) |
| `forecast` looks flat | Needs 2+ months of history — run `seed_demo.py` |
| `chat` misroutes a phrase | Intent ordering is covered by `test_assistant.py` — add the phrase as a test case, then adjust `cba/assistant/intents.py` |
