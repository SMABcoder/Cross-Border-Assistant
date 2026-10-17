"""Internationalization: message catalogs in data/i18n/<lang>.json.

Structure is ready for more languages. Missing keys fall back to English;
an unknown language falls back to the default language entirely.
"""
from __future__ import annotations

import json
from pathlib import Path

import config

_catalogs: dict[str, dict] = {}


def _load(lang: str) -> dict:
    if lang in _catalogs:
        return _catalogs[lang]
    path = Path(config.DATA_DIR) / "i18n" / f"{lang}.json"
    try:
        _catalogs[lang] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        _catalogs[lang] = {}
    return _catalogs[lang]


def available_languages() -> list[str]:
    i18n_dir = Path(config.DATA_DIR) / "i18n"
    if not i18n_dir.is_dir():
        return ["en"]
    return sorted(p.stem for p in i18n_dir.glob("*.json"))


def t(key: str, lang: str | None = None, **kwargs) -> str:
    """Translate ``key``. Falls back to English, then to the key itself."""
    lang = lang or config.DEFAULT_LANG
    text = _load(lang).get(key)
    if text is None:
        text = _load("en").get(key, key)
    try:
        return text.format(**kwargs) if kwargs else text
    except (KeyError, IndexError, ValueError):
        return text


def reset_cache() -> None:  # used by tests
    _catalogs.clear()
