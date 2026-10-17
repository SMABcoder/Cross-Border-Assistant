"""Step-by-step guides loaded from data/guides/*.json."""
from __future__ import annotations

import json
from pathlib import Path

import config


class GuideBook:
    """Load and render how-to guides (tuition, transfers, first-month budget)."""

    def __init__(self, guides_dir: str | Path | None = None) -> None:
        self.guides_dir = (
            Path(guides_dir) if guides_dir else Path(config.DATA_DIR) / "guides"
        )

    def list_guides(self) -> list[dict]:
        guides = []
        for path in sorted(self.guides_dir.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            guides.append(
                {
                    "ref": path.stem,
                    "title": payload.get("title", path.stem),
                    "description": payload.get("description", ""),
                }
            )
        return guides

    def get(self, ref: str) -> dict:
        path = self.guides_dir / f"{ref}.json"
        if not path.exists():
            raise KeyError(f"guide '{ref}' not found")
        return json.loads(path.read_text(encoding="utf-8"))

    def render(self, ref: str, lang: str | None = None) -> str:
        """Render a guide as numbered steps. ``lang`` reserved for translated
        guide files (e.g. ``pay_tuition.zh.json``); falls back to the base file."""
        guide = None
        if lang and lang != "en":
            localized = self.guides_dir / f"{ref}.{lang}.json"
            if localized.exists():
                guide = json.loads(localized.read_text(encoding="utf-8"))
        if guide is None:
            guide = self.get(ref)
        lines = [f"📖 {guide.get('title', ref)}"]
        if guide.get("description"):
            lines.append(guide["description"])
        for i, step in enumerate(guide.get("steps", []), 1):
            lines.append(f"\n{i}. {step.get('title', '')}")
            if step.get("detail"):
                lines.append(f"   {step['detail']}")
        if guide.get("tips"):
            lines.append("\n💡 Tips:")
            for tip in guide["tips"]:
                lines.append(f"   • {tip}")
        return "\n".join(lines).strip()
