# Execution Evidence — Deliverable 06

FinTechathon 2026 · International Track · Topic C (non-on-chain topic)

For non-on-chain topics the rules require **simulated-account / sandbox
operation logs and the demo video**. This directory holds ours. Every log
below was produced by running the real code — nothing is staged.

## Artifacts

| File | What it is | How it was produced |
|---|---|---|
| `demo-transcript-sample.log` | Full Phase-1 walkthrough: rates, ledger, budgets, alerts, tuition, transfers, credit, forecast, chat — against a temp DB with offline FX | `python scripts/demo.py` |
| `demo-transcript-20261018T172608Z.log` | Second Phase-1 run (same script, fresh timestamp) | `python scripts/demo.py` |
| `sandbox-run-phase2-20261018T202407Z.log` | **Phase-2 sandbox run**: tuition FX optimizer, SAFE quota tracker, CSV importer dry-run, live localhost web API calls, deterministic LLM fallback, inert rails refusal, credit estimator | `python scripts/evidence_phase2.py` |
| `test-results-263.png` | Screenshot of the full automated test suite: **263 tests, OK** | `python scripts/render_test_shot.py` (runs the real suite) |

## Demo video (≤ 5 min, required)

- `CrossBorderAssistant-Demo.mp4` — 50-second silent walkthrough, 1080p,
  generated from real CLI output (`scripts/record_demo_video.py`)
- `CrossBorderAssistant-Demo-Narrated.mp4` — same cut with voiceover

The video files live outside this repo (linkable upload for the submission
email: Google Drive / YouTube unlisted). Both were rendered from actual
program output — the evidence is reproducible, not staged.

## How to reproduce

```bash
git clone https://github.com/SyntexCodex/Cross-Border-Assistant.git
cd Cross-Border-Assistant
python scripts/demo.py            # Phase-1 evidence log -> evidence/
python scripts/evidence_phase2.py # Phase-2 evidence log -> evidence/
python -m unittest discover -s tests   # 263 tests, offline, ~1 second
```

Every script uses a temporary database and a mocked/offline FX provider:
no network, no real accounts, no real money — exactly as the security
self-assessment (`docs/SECURITY.md`) requires.
