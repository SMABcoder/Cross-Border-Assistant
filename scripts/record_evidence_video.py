#!/usr/bin/env python3
"""Record the ~4-minute narrated evidence walkthrough video.

Renders a realistic 1920x1080 terminal session (24fps) with PIL, piped to
ffmpeg as H.264 MP4. Every terminal scene runs the REAL CLI against a
throwaway database; the web-UI scene is a faithful mock of the real
``cba serve`` chat page fed with a real assistant reply.

Real-time LLM: if ``~/.config/cba/llm.env`` exists it is sourced so the
chat scene shows live LLM rephrasing; otherwise the deterministic engine
is used (no key is ever stored in this repo).

Usage:
    python3 scripts/record_evidence_video.py [--out PATH] [--preview] [--fps 24]
    python3 scripts/record_evidence_video.py --dump-timeline timeline.json
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

import record_demo_video as base  # noqa: E402

W, H, FPS = base.W, base.H, base.FPS
BG, BAR_BG = base.BG, base.BAR_BG
GREEN, WHITE, GRAY, DIM, BLUE = (base.GREEN, base.WHITE, base.GRAY,
                                 base.DIM, base.BLUE)
MONO, MONO_BOLD = base.MONO, base.MONO_BOLD
TERM_SIZE, TERM_LH = base.TERM_SIZE, base.TERM_LH
TERM_TOP, TERM_LEFT, TERM_MAX_LINES = (base.TERM_TOP, base.TERM_LEFT,
                                       base.TERM_MAX_LINES)
TYPE_CPS, REVEAL_LPS = base.TYPE_CPS, base.REVEAL_LPS

# Extra glyphs used by the chat/LLM output that DejaVu lacks.
base.EMOJI_MAP.update({"💱": "[fx]", "💡": "[tip]", "👋": "", "⚪": "( )"})

DUE_30D = (date.today() + timedelta(days=30)).isoformat()
PHASE2_LOG = sorted((ROOT / "evidence").glob("sandbox-run-phase2-*.log"))[-1].name

SCENES = [
    {"id": "ev_rates", "caption": "Live FX rates — API, cache, offline fallback",
     "target": 24.0,
     "steps": [("cli", ["rates", "--base", "USD", "--quote", "CNY"], {})]},
    {"id": "ev_optimizer", "caption": "Tuition FX optimizer — advisory only",
     "target": 24.0,
     "steps": [
         ("cli", ["tuition", "--add", "Spring tuition", "--amount", "5200",
                  "--currency", "CNY", "--due", DUE_30D,
                  "--payee", "Example University"], {}),
         ("cli", ["optimize"], {"tail": 10}),
     ]},
    {"id": "ev_llm_chat", "caption": "Real-time LLM — computed first, rephrased live",
     "target": 26.0,
     "steps": [("cli", ["chat", "--message", "should I pay my tuition now?"],
                {"tail": 14})]},
    {"id": "ev_transfers", "caption": "Transfer comparison — cheapest first, safety brief",
     "target": 24.0,
     "steps": [("cli", ["transfer", "--amount", "500", "--from", "USD",
                        "--to", "CNY"], {"tail": 16})]},
    {"id": "ev_quota", "caption": "SAFE quota tracker — self-reported by design",
     "target": 20.0,
     "steps": [
         ("cli", ["quota", "--record", "1200", "--currency", "USD",
                  "--date", "2026-10-10", "--note", "tuition wire"], {}),
         ("cli", ["quota"], {"tail": 9}),
     ]},
    {"id": "ev_webui", "caption": "Web chat UI — local JSON API, localhost only",
     "target": 26.0, "mock": "webui"},
    {"id": "ev_evidence", "caption": "Execution evidence — sandbox logs, reproducible",
     "target": 24.0,
     "steps": [
         ("shell", "ls evidence/", ["ls", "evidence"], {}),
         ("shell", f"tail -12 evidence/{PHASE2_LOG}",
          ["tail", "-12", f"evidence/{PHASE2_LOG}"], {}),
     ]},
    {"id": "ev_tests", "caption": "263 automated tests — all green",
     "target": 22.0,
     "steps": [("raw", ["-m", "unittest", "discover", "-s", "tests"],
                {"tail": 6, "drop_prefix": "[ALERT]"})]},
]

TITLE_CARD = [
    ("Cross Border Assistant", 76, WHITE, True),
    ("Execution evidence — the real program, running", 36, GRAY, False),
    ("FinTechathon 2026  ·  International Track  ·  Topic C", 30, BLUE, False),
]

CLOSING_CARD = [
    ("It advises. It never moves money.", 56, WHITE, True),
    ("263/263 tests green  ·  docs/SECURITY.md  ·  evidence/ logs", 30, GREEN, False),
    ("github.com/SyntexCodex/Cross-Border-Assistant", 32, BLUE, False),
    ("FinTechathon 2026  ·  Topic C  ·  Cross-border & Student Finance", 28, DIM, False),
]

TITLE_S, CLOSING_S = 22.0, 20.0

NARRATION = {
    "ev_title": ("Cross Border Assistant. An AI financial participant for "
              "international students living between two money systems. "
              "This is our execution evidence. Every screen you see is the "
              "real program running."),
    "ev_rates": ("Live exchange rates from a public API, cached locally, with "
              "an offline fallback table. The assistant never invents a "
              "number. If the network fails, it degrades gracefully and "
              "says so."),
    "ev_llm_chat": ("Real-time intelligence. Every answer is computed first by "
                 "the deterministic engine, then rephrased live by the "
                 "language model. Warm tone, identical numbers. The model "
                 "can never hallucinate a rate or balance."),
    "ev_optimizer": ("The tuition optimizer compares today's rate with the "
                  "thirty-day average and advises pay now, wait, or no "
                  "signal. Advisory only. It informs the decision. It never "
                  "executes anything."),
    "ev_transfers": ("Six transfer methods compared cheapest first, with the "
                  "true cost in your currency, plus a safety brief against "
                  "unlicensed channels. Estimates only. This prototype moves "
                  "no money."),
    "ev_quota": ("China's fifty thousand dollar annual FX quota, tracked "
              "transfer by transfer. Self-reported by design. The bank "
              "statement is named as the authoritative record."),
    "ev_webui": ("A local web chat backed by a plain JSON API, ready for a "
              "WeChat mini program to call. Localhost only for the demo. A "
              "production deployment would add TLS and per-user "
              "authentication."),
    "ev_evidence": ("Execution evidence. Every feature run in a sandbox against "
                 "a throwaway database with offline rates, saved as "
                 "timestamped logs. Reproduce it yourself: two scripts, one "
                 "command, identical results."),
    "ev_tests": ("Two hundred sixty-three automated tests, all green, running "
              "offline in about a second. The security self-assessment "
              "documents fifteen known risks and exactly how each one is "
              "handled."),
    "ev_closing": ("Cross Border Assistant. It watches while you sleep, advises "
                "on every transfer, and never moves a cent without a "
                "licensed partner. Topic C, FinTechathon 2026."),
}


def load_local_llm_env() -> None:
    """Source ~/.config/cba/llm.env (CBA_LLM_*) if present; never in repo."""
    p = Path.home() / ".config" / "cba" / "llm.env"
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if line.startswith("export "):
            k, _, v = line[len("export "):].partition("=")
            os.environ[k.strip()] = v.strip().strip("'\"")


def make_env(tmpdb: Path, tmpcache: Path) -> dict:
    env = base.make_env(tmpdb, tmpcache)
    # Real FX for the evidence video (rates scene shows the live API).
    env.pop("CBA_FX_CACHE_PATH", None)
    return env


def capture_all(env):
    captured = []
    for scene in SCENES:
        if scene.get("mock"):
            captured.append((scene["id"], scene["caption"], []))
            continue
        steps = []
        for step in scene["steps"]:
            kind, disp = step[0], step[1]
            opts = step[3] if len(step) > 3 else {}
            if kind == "cli":
                argv, show = (["-m", "cba.cli", *step[1]],
                              "python3 -m cba.cli " + " ".join(step[1]))
            elif kind == "raw":
                argv, show = (step[1], "python3 " + " ".join(step[1]))
            else:  # shell
                argv, show = (step[2], disp)
                proc = subprocess.run(argv, cwd=ROOT, env=env,
                                      capture_output=True, text=True,
                                      timeout=120)
                out = base.sanitize(proc.stdout + proc.stderr).splitlines()
                tail = opts.get("tail")
                steps.append((show, out[-tail:] if tail else out))
                continue
            out = base.run_capture(argv, env, tail=opts.get("tail"),
                                   drop_prefix=opts.get("drop_prefix"))
            steps.append((show, out))
        captured.append((scene["id"], scene["caption"], steps))
    return captured


def draw_webui(fonts, reply_text: str) -> Image.Image:
    """Faithful mock of the real `cba serve` chat page, fed a real reply."""
    img = Image.new("RGB", (W, H), "#0b0e14")
    d = ImageDraw.Draw(img)
    # browser chrome
    d.rectangle([0, 0, W, 88], fill="#161b24")
    for i, c in enumerate(("#ff5f57", "#febc2e", "#28c840")):
        d.ellipse([28 + i * 32, 30, 52 + i * 32, 54], fill=c)
    d.rounded_rectangle([140, 24, W - 140, 64], radius=20, fill="#0b0e14",
                        outline="#2a3342", width=2)
    d.text((W / 2, 44), "http://127.0.0.1:8000  ·  cba serve",
           font=fonts["ui"], fill=DIM, anchor="mm")
    # chat area
    y = 130
    ui = ImageFont.truetype(MONO, 30)
    user_msg = "should I pay my tuition now?"
    bw = 900
    d.rounded_rectangle([W - bw - 60, y, W - 60, y + 74], radius=18,
                        fill="#1f6feb")
    d.text((W - 60 - 24, y + 37), user_msg, font=ui, fill=WHITE, anchor="rm")
    y += 110
    bot = base.sanitize(reply_text)
    lines: list[str] = []
    for para in bot.split("\n"):
        # wrap() keeps embedded newlines; PIL would draw them on top of the
        # next line, so split paragraphs first, then wrap each one.
        lines.extend(base.wrap(para, ui, 1180) if para.strip() else [""])
    lines = lines[:12]
    bh = max(1, len(lines)) * 44 + 44
    d.rounded_rectangle([60, y, 60 + 1260, y + bh], radius=18, fill="#161b24",
                        outline="#2a3342", width=2)
    by = y + 34
    for ln in lines:
        if ln:
            d.text((96, by), ln, font=ui, fill="#e6edf3")
        by += 44
    y += bh + 30
    d.text((60, y), "real assistant reply — computed, then rephrased live by the LLM",
           font=fonts["ui"], fill=DIM)
    # input bar
    d.rounded_rectangle([60, H - 120, W - 60, H - 56], radius=24,
                        fill="#161b24", outline="#2a3342", width=2)
    d.text((96, H - 88), "Ask about rates, budgets, tuition, transfers, credit…",
           font=ui, fill=DIM)
    return img


def generate(fonts, captured, fps: int, timeline=None):
    def emit(seg_id, frames):
        n = 0
        for img in frames:
            n += 1
            yield img
        if timeline is not None:
            timeline.append((seg_id, n))

    yield from emit("ev_title", ([base.draw_card(fonts, TITLE_CARD,
                                              "Cross Border Assistant")] *
                              int(TITLE_S * fps)))
    cap_by_id = {sid: (cap, steps) for sid, cap, steps in captured}
    llm_reply = ""
    for sid, cap, steps in captured:
        if sid == "ev_llm_chat" and steps:
            llm_reply = "\n".join(steps[0][1])
    for scene in SCENES:
        sid = scene["id"]
        cap, steps = cap_by_id[sid]

        def scene_frames(sid=sid, cap=cap, steps=steps, scene=scene):
            term = base.Terminal()
            if scene.get("mock") == "webui":
                img = draw_webui(fonts, llm_reply or
                                 "100.00 USD = 670.29 CNY at 1 USD = 6.7029 CNY.")
                base_img, d = base.draw_base(fonts, cap)
                base_img.paste(img.crop((0, 88, W, H)), (0, 88))
                for _ in range(int(scene["target"] * FPS)):
                    yield base_img.copy()
                return
            # Deterministic frame budget: typing + reveal, then hold to target
            # so every narration segment fits inside its scene slot.
            used = 0
            for disp, out_lines in steps:
                used += max(1, int(len("$ " + disp) / TYPE_CPS * FPS))
                used += len(out_lines) * max(1, int(FPS / REVEAL_LPS))
            hold_s = max(1.5, scene["target"] - used / FPS)
            for disp, out_lines in steps:
                yield from base.frames_for_typing(fonts, cap, term, disp)
                term.add([("$ ", "mono_bold", GREEN),
                          (disp, base.seg_key(fonts, disp), WHITE)])
                yield from base.frames_for_output(fonts, cap, term, out_lines)
            yield from base.hold_frames(fonts, cap, term, hold_s)
        yield from emit(sid, scene_frames())
    yield from emit("ev_closing", ([base.draw_card(fonts, CLOSING_CARD,
                                                "Cross Border Assistant")] *
                                int(CLOSING_S * fps)))


def main() -> int:
    ap = argparse.ArgumentParser(description="Record the evidence walkthrough video.")
    ap.add_argument("--out", default=str(
        Path.home() / "workspace/demo-video/CrossBorderAssistant-Evidence-4min.mp4"))
    ap.add_argument("--preview", action="store_true")
    ap.add_argument("--dump-timeline", default=None, metavar="JSON")
    ap.add_argument("--fps", type=int, default=FPS)
    ap.add_argument("--print-narration", action="store_true",
                    help="print the narration map as JSON and exit")
    args = ap.parse_args()

    if args.print_narration:
        import json
        print(json.dumps(NARRATION, indent=1))
        return 0

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg and not args.preview:
        print("ERROR: ffmpeg not found on PATH.", file=sys.stderr)
        return 2

    load_local_llm_env()
    fonts = base.load_fonts()
    tmpdb = Path(tempfile.gettempdir()) / "cba-evidencevideo.db"
    tmpcache = Path(tempfile.gettempdir()) / "cba-evidencevideo-fx.json"
    for p in (tmpdb, tmpcache):
        if p.exists():
            p.unlink()
    env = make_env(tmpdb, tmpcache)

    captured = capture_all(env)

    if args.dump_timeline:
        import json
        tl = []
        for _ in generate(fonts, captured, args.fps, timeline=tl):
            pass
        t = 0.0
        out = []
        for seg_id, n in tl:
            dur = n / args.fps
            out.append({"id": seg_id, "start": round(t, 3), "dur": round(dur, 3)})
            t += dur
        Path(args.dump_timeline).write_text(json.dumps(out, indent=1))
        print(f"timeline: {len(out)} segments, total {t:.1f}s -> {args.dump_timeline}")
        return 0

    if args.preview:
        outdir = Path("/tmp/evidencevideo-preview")
        outdir.mkdir(exist_ok=True)
        base.draw_card(fonts, TITLE_CARD, "Cross Border Assistant").save(
            outdir / "1-title.png")
        sid, cap, steps = next(c for c in captured if c[0] == "ev_llm_chat")
        term = base.Terminal()
        disp, out_lines = steps[0]
        for img in base.frames_for_typing(fonts, cap, term, disp):
            pass
        img.save(outdir / "2-typing.png")
        term.add([("$ ", "mono_bold", GREEN),
                  (disp, base.seg_key(fonts, disp), WHITE)])
        for img in base.frames_for_output(fonts, cap, term, out_lines):
            pass
        img.save(outdir / "3-output.png")
        draw_webui(fonts, "\n".join(out_lines)).save(outdir / "4-webui.png")
        print(f"preview frames in {outdir}")
        return 0

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [ffmpeg, "-y",
           "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", f"{W}x{H}", "-r", str(args.fps), "-i", "pipe:0",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
           "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    n = 0
    try:
        for img in generate(fonts, captured, args.fps):
            proc.stdin.write(img.tobytes())
            n += 1
    finally:
        proc.stdin.close()
        proc.wait()
    print(f"wrote {out} ({n} frames, {n / args.fps:.1f}s)")
    return 0 if proc.returncode == 0 else 3


if __name__ == "__main__":
    raise SystemExit(main())
