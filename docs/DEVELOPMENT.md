# Development Guide — Cross Border Assistant

Step-by-step instructions for setting up, running, testing, and extending
this project. Written for a developer who has never seen the codebase.

---

## 1. Prerequisites

- **Python 3.10 or newer** (`python3 --version`)
- **No other dependencies.** The app is stdlib-only (`sqlite3`, `urllib`,
  `json`, `argparse`, `http.server`, `unittest` …). `requests` is used only
  if already installed, with a `urllib` fallback. `pytest` is optional
  (test runner alternative).

## 2. Get the code and run it (60 seconds)

```bash
git clone https://github.com/SyntexCodex/Cross-Border-Assistant.git
cd Cross-Border-Assistant

# See everything work end-to-end (uses a temp DB + offline rates;
# also writes evidence/demo-transcript-<UTC>.log)
python scripts/demo.py

# Seed a demo student into the local database
python scripts/seed_demo.py

# Try the assistant
python cba/cli.py chat --message "convert 100 USD to CNY"
python cba/cli.py chat --message "should I pay my tuition now?"
```

## 3. Project layout

```
config.py              # EVERY tunable lives here (CBA_ env overrides)
cba/
  common.py            # sqlite helper, money formatting, ProductionGatedError
  cli.py               # 13 subcommands — thin routing, no business logic
  fx/                  # exchange rates: live API → cache → offline fallback
  ledger/              # sqlite income/expense ledger
  budgets/             # monthly limits, warnings, burn-down pace
  alerts/              # target-rate alerts + cooldown + notifiers
  tuition/             # bills + reminder thresholds
  transfers/           # fee estimator (data/fees.json) + safety brief
  credit/              # checklist + score estimator + inert bureau adapter
  forecast/            # weighted projection + trend + seasonality
  optimizer/           # tuition FX timing: PAY_NOW / WAIT / NO_SIGNAL
  quota/               # self-reported SAFE $50k FX quota tracker
  importer/            # CSV statement import (dry-run default)
  rails/               # INERT CIPS / e-CNY / mBridge adapters + pain.001 builder
  web/                 # localhost JSON API + chat page (stdlib http.server)
  assistant/           # IntentParser, handlers, guides, i18n, LLM hook
data/
  fees.json            # the ONLY place transfer fees live
  i18n/en.json, zh.json
  guides/              # step-by-step guides (pay_tuition, send_money_home…)
  credit_checklist.json, fallback_rates.json
tests/                 # 263 tests, one file per module (unittest style)
scripts/               # demo.py, seed_demo.py, check_alerts.py, …
docs/                  # TECHNICAL-DOCUMENTATION.md, SECURITY.md
```

## 4. The three rules (non-negotiable)

1. **Zero hardcoded tunables.** Every threshold, URL, timeout, and window
   goes in `config.py` as a `CBA_`-prefixed env override. If you catch
   yourself writing a literal `30` or a URL in a module — move it to config.
2. **Respect the permission tiers.** Read-only code cannot write or use the
   network (except the FX API). Nothing may move money, hold bank
   credentials, or call a live rail — production-gated integrations raise
   `ProductionGatedError` instead of acting. Read `docs/SECURITY.md` first.
3. **Tests stay green.** `python -m unittest discover -s tests` must pass
   before every commit. Network is mocked, DBs are temp files.

## 5. Running the test suite

```bash
python -m unittest discover -s tests          # stdlib, no install needed
python -m pytest -q                           # alternative (pip install pytest)
```

Conventions: one `tests/test_<module>.py` per module, `unittest.TestCase`
classes, fake `RateProvider` instead of network, temp sqlite per test class.
A full run takes ~1 second and needs no internet.

## 6. Adding a new feature — step by step

Example: adding a "savings goals" module.

1. **Config first.** Add tunables to `config.py`:
   `SAVINGS_WARN_PCT = from_env("SAVINGS_WARN_PCT", 80.0)`.
2. **Create the service** at `cba/savings/__init__.py`:
   - Accept `db_path` and shared services (`fx`, `ledger`) in `__init__`
     (dependency injection — this is how tests swap fakes in).
   - Create your tables with `CREATE TABLE IF NOT EXISTS` in `_init_db`.
   - Read config values *inside methods* (not at import) so tests can
     monkeypatch them.
3. **Wire the CLI** in `cba/cli.py`: add a `cmd_savings()` function +
   a subparser. Keep handlers thin — they print, services compute.
4. **Teach the assistant** (optional): add the intent name to `INTENTS` in
   `cba/assistant/intents.py`, add the keyword/regex branch in `parse()`
   (specific patterns before broad keywords), add a `_h_<name>` handler in
   `cba/assistant/__init__.py`, and add EN + ZH strings to
   `data/i18n/en.json` and `data/i18n/zh.json`.
5. **Write tests** in `tests/test_savings.py`: happy path, validation
   errors, boundary values. Aim for the module's public API, not internals.
6. **Document**: one row in this README's feature table + `ARCHITECTURE.md`
   module map if the module is user-visible.
7. **Run everything**: `python -m unittest discover -s tests` → all green,
   then commit.

## 7. Common tasks

| Task | How |
|---|---|
| Change a threshold | Set the `CBA_` env var — no code change. `config.summary()` shows effective values |
| Add a currency | Append to `CBA_SUPPORTED_CURRENCIES` (must exist in the FX API / fallback table) |
| Add a transfer method | Edit `data/fees.json` only — never hardcode fees |
| Add a guide | New JSON in `data/guides/` + render via `GuideBook` |
| Add a language | New `data/i18n/<lang>.json` — no code changes |
| Debug the assistant | `python cba/cli.py chat --message "..." --lang en` prints the routed reply |
| Check alerts manually | `python scripts/check_alerts.py` (cron runs this every 10 min in deployment) |
| Inspect the DB | `sqlite3 cba.db ".tables"` (any sqlite client) |
| Fresh start | Delete `cba.db` (or point `CBA_DB_PATH` elsewhere) |

## 8. Deployment checklist

- [ ] Python ≥ 3.10 on the target machine
- [ ] `python scripts/demo.py` passes (writes evidence log)
- [ ] `python -m unittest discover -s tests` → OK
- [ ] Optional: `CBA_FX_API_BASE` reachable (else offline fallback covers you)
- [ ] Optional: SMTP / webhook env vars for alert notifications
- [ ] Optional cron: `*/10 * * * * cd /path/to/app && python scripts/check_alerts.py`
- [ ] `cba.db` lives in a private directory (see SECURITY.md R7)

## 9. What NOT to do

- Don't add pip dependencies without discussion (stdlib-first is a design rule).
- Don't put secrets in code, config files, or chat — env vars only.
- Don't "complete" a production integration (rails, bureau, bank feed) by
  faking it: the inert adapters are honest placeholders. Real ones need a
  licensed partner, a vault, and regulatory approval.
- Don't let the LLM compute numbers — it rephrases pre-computed answers only.
