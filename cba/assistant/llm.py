"""LLM provider protocol. Disabled by default.

To use a real LLM, implement this protocol and pass the instance to
:class:`Assistant` with ``llm=...``, then set ``CBA_LLM_ENABLED=1``.

Example (pseudocode, NOT executed)::

    from cba.assistant.llm import LLMProvider

    class MyLLM(LLMProvider):
        def complete(self, system: str, user: str) -> str:
            # call your provider's API here
            return "..."

    assistant = Assistant(..., llm=MyLLM())

The built-in rule-based intents always run first; the LLM is only asked to
rephrase / enrich when enabled. Rule-based answers remain the source of
truth for numbers so the assistant never hallucinates rates or balances.
"""
from __future__ import annotations

from typing import Protocol


class LLMProvider(Protocol):
    """One-method interface any LLM backend can implement."""

    def complete(self, system: str, user: str) -> str: ...
