#!/usr/bin/env python3
"""Phase-2 sandbox execution evidence (deliverable 06).

Runs every Phase-2 capability against a temporary database with an
offline FX provider (no network), prints each step, and saves the full
transcript to ``evidence/sandbox-run-phase2-<UTC-timestamp>.log``.

Covers: tuition FX optimizer, SAFE quota tracker, CSV importer (dry-run),
web JSON API (in-process), LLM deterministic fallback, inert rails
adapters, credit estimator, and the new chat intents.

Usage: python scripts/evidence_phase2.py
"""
from __future__ import annotations

import io
import json
import sys
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cba.assistant import Assistant
from cba.common import ProductionGatedError
from cba.credit import CreditService
from cba.fx import FxService, FallbackTableProvider
from cba.importer import CsvImporter
from cba.optimizer import OptimizerService
from cba.quota import QuotaService
from cba.rails import CipsRail, EcnYRail, build_pain001
from cba.tuition import TuitionService
from cba.web import WebApp


class OfflineFx(FxService):
    """FxService forced onto the fallback table (deterministic, no network)."""

    def _table(self, base: str):
        return FallbackTableProvider().get_table(base)


class Tee:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._file = path.open("w", encoding="utf-8")

    def write(self, text: str) -> None:
        sys.__stdout__.write(text)
        self._file.write(text)

    def flush(self) -> None:
        sys.__stdout__.flush()
        self._file.flush()

    def close(self) -> None:
        self._file.close()


def banner(title: str) -> None:
    print("\n" + "=" * 64)
    print(title)
    print("=" * 64)


def main() -> int:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = Path(__file__).resolve().parent.parent / "evidence" / f"sandbox-run-phase2-{stamp}.log"
    out.parent.mkdir(parents=True, exist_ok=True)
    tee = Tee(out)
    sys.stdout = tee  # type: ignore
    try:
        return run()
    finally:
        sys.stdout = sys.__stdout__
        tee.close()
        print(f"\nEvidence log written to: {out}")


def run() -> int:
    tmp = tempfile.mkdtemp(prefix="cba-evidence-")
    db = str(Path(tmp) / "cba.db")
    fx = OfflineFx()
    print("Cross Border Assistant — Phase-2 sandbox execution evidence")
    print("Temp DB:", db, "| FX: offline fallback table (no network)")

    # 1. Tuition + optimizer ------------------------------------------------
    banner("1. Tuition bill + FX optimizer (advisory only)")
    tuition = TuitionService(db_path=db)
    bill = tuition.add("Spring tuition", 5200, "CNY", "2027-01-15", payee="Example University")
    print(f"Bill #{bill['id']}: {bill['name']} {bill['amount']} {bill['currency']} due {bill['due_date']}")
    opt = OptimizerService(db_path=db, fx=fx)
    print(OptimizerService.format_report(opt.optimize()))

    # 2. Quota tracker ------------------------------------------------------
    banner("2. SAFE FX quota tracker (self-reported)")
    quota = QuotaService(db_path=db, fx=fx)
    quota.record("2026-09-01", 1200, "USD", note="tuition wire")
    quota.record("2026-10-05", 8000, "CNY", note="living expenses")
    print(quota.format_status(quota.status(year=2026)))

    # 3. CSV importer (dry-run) ----------------------------------------------
    banner("3. CSV bank-statement importer (dry-run: writes nothing)")
    csv_path = Path(tmp) / "statement.csv"
    csv_path.write_text(
        "date,description,amount,currency\n"
        "2026-10-01,Noodle shop,-45,CNY\n"
        "2026-10-02,Campus supermarket,-120,CNY\n"
        "2026-10-03,Scholarship stipend,3000,CNY\n",
        encoding="utf-8",
    )
    importer = CsvImporter(db_path=db)
    prev = importer.preview(str(csv_path))
    print(f"Preview: {prev['total']} rows, {prev['skipped']} skipped (nothing written)")
    for row in prev["rows"]:
        print(f"  {row['date']} {row['kind']:7} {row['amount']:>8.2f} {row['currency']} [{row['category']}] {row['description']}")

    # 4. Web JSON API (real localhost HTTP) --------------------------------------
    banner("4. Local web JSON API (real HTTP on localhost)")
    app = WebApp(db_path=db, fx=fx)
    server, thread = app.start(port=0)
    port = server.server_address[1]
    try:
        def get(path):
            with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=10) as r:
                return r.status, r.read().decode("utf-8")

        def post(path, obj):
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}{path}",
                data=json.dumps(obj).encode("utf-8"),
                headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, r.read().decode("utf-8")

        for label, fn in [
            ("GET /api/rates?base=USD&quote=CNY", lambda: get("/api/rates?base=USD&quote=CNY")),
            ("GET /api/budget", lambda: get("/api/budget")),
            ("POST /api/chat", lambda: post("/api/chat", {"message": "convert 100 USD to CNY"})),
        ]:
            code, payload = fn()
            short = payload if len(payload) < 200 else payload[:200] + "…"
            print(f"{label} -> HTTP {code}: {short}")
    finally:
        server.shutdown()
        server.server_close()

    # 5. LLM deterministic fallback (no key) ----------------------------------
    banner("5. Assistant with no LLM key (deterministic engine)")
    assistant = Assistant(db_path=db, fx=fx)
    print("LLM active:", assistant.llm is not None)
    for msg in ["should I pay my tuition now?", "check my FX quota", "convert 100 USD to CNY"]:
        print(f"\nyou> {msg}")
        print(assistant.chat(msg))

    # 6. Inert rails ----------------------------------------------------------
    banner("6. Payment rails stay inert (production-gated)")
    for rail in (CipsRail(), EcnYRail()):
        try:
            rail.submit_payment(amount=100)
            print(f"{rail.name}: ACTED (unexpected!)")
        except ProductionGatedError as exc:
            print(f"{rail.name}: refused as designed -> {exc}")
    xml = build_pain001(
        msg_id="EVIDENCE-001", created="2026-10-19T00:00:00",
        debtor_name="Demo Student", debtor_acct="DE0000000001",
        creditor_name="Example University", creditor_acct="CN0000000002",
        creditor_agent_bic="BKCHCNBJXXX", amount=5200, currency="CNY",
        remittance_info="tuition",
    )
    print(f"pain.001 generated: {len(xml)} bytes of XML (format only — never transmitted)")

    # 7. Credit estimator ------------------------------------------------------
    banner("7. Credit checklist + transparent score estimator")
    credit = CreditService(db_path=db)
    credit.complete("secured_card")
    credit.complete("bank_account")
    prog = credit.progress()
    est = credit.estimate_score()
    print(f"Checklist: {prog['done']}/{prog['total']} done")
    print(f"Score ESTIMATE: {est['estimate']} ({est['math']})")
    print(f"Disclaimer: {est['disclaimer']}")

    banner("DONE — all Phase-2 capabilities executed in sandbox")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
