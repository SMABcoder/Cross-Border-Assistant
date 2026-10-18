"""LLM rephrasing layer for the assistant (BYOK — bring your own key).

Two modes:

1. **Key unset (default).** :class:`Assistant` falls back to the deterministic
   rule engine and the LLM is never called. Behavior is byte-identical to a
   build without this module: no network, no tokens, no randomness.

2. **Key set.** Pass ``llm=OpenAICompatibleProvider()`` to :class:`Assistant`
   (with ``CBA_LLM_ENABLED=1``) and the assistant asks the provider to
   *rephrase* its already-computed deterministic answer. Numbers always come
   from the services (FxService, ledger, budgets, tuition, fee table) and are
   sent to the LLM inside the prompt; the LLM never computes a rate or a
   balance itself, so it cannot hallucinate one.

Configuration (env vars, ``CBA_`` prefix)::

    CBA_LLM_API_KEY      Bearer key for the provider. Unset/empty => the
                         deterministic engine is used (default).
    CBA_LLM_BASE_URL     OpenAI-compatible base URL, e.g.
                         ``https://api.openai.com/v1`` (default).
    CBA_LLM_MODEL        Model name, e.g. ``gpt-4o-mini`` (default).
    CBA_LLM_TIMEOUT      HTTP timeout in seconds (default 30).
    CBA_LLM_MAX_TOKENS   Cap on reply length (default 300).

The API key is read from config at each call (never cached), and is never
logged, printed, or interpolated into an :class:`LLMError` message.
"""
from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from typing import Protocol

import config


class LLMProvider(Protocol):
    """One-method interface any LLM backend can implement."""

    def complete(self, system: str, user: str) -> str: ...


class LLMError(Exception):
    """Raised when the LLM call cannot be completed.

    The message never contains the API key.
    """


class OpenAICompatibleProvider:
    """BYOK provider for any OpenAI-compatible ``/chat/completions`` endpoint.

    Stdlib only (``urllib``). Constructed with no arguments; every call reads
    ``config.LLM_*`` fresh so tests can monkeypatch them.
    """

    def __init__(self) -> None:
        pass

    def complete(self, system: str, user: str) -> str:
        """Rephrase ``user`` (a pre-computed deterministic answer) via the LLM."""
        key = config.LLM_API_KEY
        if not key:
            raise LLMError(
                "LLM API key not configured — set CBA_LLM_API_KEY to enable, "
                "otherwise the deterministic engine is used."
            )
        url = config.LLM_BASE_URL.rstrip("/") + "/chat/completions"
        body = {
            "model": config.LLM_MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": config.LLM_MAX_TOKENS,
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + key,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=config.LLM_TIMEOUT) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            raise LLMError(
                self._safe(key, f"LLM request failed: HTTP {exc.code} {exc.reason}")
            ) from None
        except (urllib.error.URLError, socket.timeout, TimeoutError) as exc:
            reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
            raise LLMError(
                self._safe(key, f"LLM request failed: network error: {reason}")
            ) from None
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise LLMError(
                self._safe(key, f"LLM request failed: invalid JSON response: {exc}")
            ) from None
        try:
            content = payload["choices"][0]["message"]["content"]
            return content.strip()
        except (KeyError, IndexError, TypeError, AttributeError) as exc:
            raise LLMError(
                self._safe(
                    key, f"LLM request failed: unexpected response shape: {exc}"
                )
            ) from None

    @staticmethod
    def _safe(key: str, detail: str) -> str:
        """Redact the API key from an error detail (defense in depth)."""
        return detail.replace(key, "***") if key else detail
