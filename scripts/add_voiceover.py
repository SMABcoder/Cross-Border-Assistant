#!/usr/bin/env python3
"""Add a narrated voiceover track to the Cross Border Assistant demo video.

Synthesizes one narration segment per video scene (default channel voice),
fits each segment into its scene's time slot, mixes them onto a single
timeline, and muxes with the silent demo video.

Usage:
    python3 scripts/add_voiceover.py --video IN.mp4 --timeline TIMELINE.json \
        --out OUT.mp4 [--voice VOICE_ID] [--workdir DIR]

Timeline JSON comes from:
    python3 scripts/record_demo_video.py --dump-timeline timeline.json

No "..." may appear in narration text (TTS backend rejects ellipses).
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import wave
from pathlib import Path

DEFAULT_VOICE = "avocado_v2:casper"

# id -> narration (plain ASCII, no ellipses; keep each under its scene slot —
# the voice runs ~75 wpm, so roughly 0.8s per word)
NARRATION = {
    "title": "Cross Border Assistant.",
    "tests": "All tests green.",
    "rates": "Live FX rates.",
    "ledger": "Income and expenses tracked, in your currency.",
    "budget": "Budgets with warnings and pace projection.",
    "alerts": "Rate alerts watch for you.",
    "tuition": "Tuition reminders with payment guides.",
    "transfer": "Cheapest transfer comparison.",
    "credit": "Credit checklist for newcomers.",
    "forecast": "Spending forecast.",
    "chat": "Bilingual assistant, English and Chinese.",
    "closing": "Cross Border Assistant. Topic C.",
    # Evidence walkthrough video (record_evidence_video.py) — ~4 minutes.
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


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=300, **kw)


def probe_dur(path: Path) -> float:
    r = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)])
    return float(r.stdout.strip())


def synth(text: str, out: Path, voice: str, speed: int):
    """Synthesize one segment; retry once on failure."""
    for attempt in (1, 2):
        r = subprocess.run(
            ["tts", "speak", "--voice", voice, "--format", "wav",
             "--speed", str(speed), "--text-stdin", "--output", str(out)],
            input=text, capture_output=True, text=True, timeout=300)
        if r.returncode == 0 and out.exists() and out.stat().st_size > 1000:
            strip_id3(out)  # TTS prepends an ID3v2 header that breaks ffprobe
            return
        print(f"  tts attempt {attempt} failed: {r.stderr.strip()[:200]}",
              file=sys.stderr)
    raise RuntimeError(f"TTS failed for: {text[:60]}")


def strip_id3(path: Path):
    """Cut a leading ID3v2 header (file is actually RIFF/WAVE after it)."""
    data = path.read_bytes()
    i = data.find(b"RIFF")
    if i > 0:
        path.write_bytes(data[i:])


def main() -> int:
    ap = argparse.ArgumentParser(description="Add voiceover to the demo video.")
    ap.add_argument("--video", required=True)
    ap.add_argument("--timeline", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--voice", default=DEFAULT_VOICE)
    ap.add_argument("--speed", type=int, default=120,
                    help="tts speed 1-200 (default 120)")
    ap.add_argument("--workdir", default="/tmp/vo")
    args = ap.parse_args()

    if not shutil.which("tts"):
        print("ERROR: tts not found on PATH.", file=sys.stderr)
        return 2

    work = Path(args.workdir)
    work.mkdir(parents=True, exist_ok=True)
    segs = json.loads(Path(args.timeline).read_text())
    video_dur = probe_dur(Path(args.video))
    print(f"video {args.video}: {video_dur:.1f}s, {len(segs)} segments")

    # 1. synthesize + fit each segment into its slot
    normed = []
    for seg in segs:
        sid = seg["id"]
        text = NARRATION.get(sid)
        if not text:
            print(f"  [{sid}] no narration — skipping")
            continue
        raw = work / f"raw_{sid}.wav"
        norm = work / f"norm_{sid}.wav"
        print(f"  [{sid}] synthesizing ({len(text.split())} words)...")
        synth(text, raw, args.voice, args.speed)
        dur = probe_dur(raw)
        slot = seg["dur"] - 0.25  # breathing room at scene end
        tempo = dur / slot if dur > slot else 1.0
        if tempo > 1.3:
            print(f"  [{sid}] WARNING: {dur:.2f}s vs {slot:.2f}s slot even after atempo cap",
                  file=sys.stderr)
            tempo = 1.3
        filt = f"atempo={tempo:.3f}," if tempo > 1.0 else ""
        if tempo > 1.0:
            print(f"  [{sid}] {dur:.2f}s > {slot:.2f}s slot — atempo {tempo:.2f}")
        run(["ffmpeg", "-y", "-v", "error", "-i", str(raw),
             "-filter:a", f"{filt}aresample=44100,aformat=channel_layouts=mono",
             "-ar", "44100", "-ac", "1", str(norm)], check=True)
        normed.append((seg["start"], norm))

    # 2. mix onto one timeline
    import audioop
    sr = 44100
    total = int((video_dur + 0.5) * sr)
    mix = bytearray(total * 2)  # 16-bit mono
    for start, path in normed:
        with wave.open(str(path), "rb") as w:
            pcm = w.readframes(w.getnframes())
        off = int(start * sr) * 2
        end = min(off + len(pcm), len(mix))
        seg = pcm[: end - off]
        mix[off:end] = audioop.add(mix[off:end], seg, 2)
    narration = work / "narration.wav"
    with wave.open(str(narration), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(bytes(mix))

    # 3. mux with the video
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    run(["ffmpeg", "-y", "-v", "error", "-i", args.video, "-i", str(narration),
         "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
         "-movflags", "+faststart", "-shortest", str(out)], check=True)
    print(f"wrote {out} ({out.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
