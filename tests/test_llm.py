"""Tests for the OpenAI-compatible LLM provider (BYOK).

``urllib.request.urlopen`` is always mocked — no network is touched.
"""
from __future__ import annotations

import json
import unittest
import urllib.error
from unittest import mock

import config
from cba.assistant.llm import LLMError, OpenAICompatibleProvider


class _FakeResponse:
    """Minimal urlopen stand-in: context manager with read()."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _set_config(**overrides):
    """Temporarily patch config attrs; returns an addCleanup-ready restorer."""
    old = {name: getattr(config, name) for name in overrides}
    for name, value in overrides.items():
        setattr(config, name, value)
    return old


class LlmTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.old = _set_config(
            LLM_API_KEY="test-key",
            LLM_BASE_URL="https://api.openai.com/v1",
            LLM_MODEL="gpt-4o-mini",
            LLM_TIMEOUT=30,
            LLM_MAX_TOKENS=300,
        )
        self.addCleanup(lambda: _set_config(**self.old))
        self.captured = {}

    def _fake_urlopen(self, body: bytes):
        def fake(req, timeout=None):
            self.captured["request"] = req
            self.captured["timeout"] = timeout
            return _FakeResponse(body)

        return fake

    def test_success_parses_and_strips_content(self):
        body = b'{"choices":[{"message":{"content":"  warm reply  "}}]}'
        with mock.patch("urllib.request.urlopen", self._fake_urlopen(body)):
            out = OpenAICompatibleProvider().complete("sys", "user")
        self.assertEqual(out, "warm reply")

    def test_request_shape(self):
        body = b'{"choices":[{"message":{"content":"x"}}]}'
        with mock.patch("urllib.request.urlopen", self._fake_urlopen(body)):
            OpenAICompatibleProvider().complete("system prompt", "user prompt")
        req = self.captured["request"]
        self.assertTrue(req.full_url.endswith("/chat/completions"))
        self.assertEqual(req.get_header("Authorization"), "Bearer test-key")
        self.assertEqual(req.get_header("Content-type"), "application/json")
        self.assertEqual(self.captured["timeout"], 30)
        sent = json.loads(req.data.decode("utf-8"))
        self.assertEqual(sent["model"], "gpt-4o-mini")
        self.assertEqual(
            sent["messages"],
            [
                {"role": "system", "content": "system prompt"},
                {"role": "user", "content": "user prompt"},
            ],
        )
        self.assertEqual(sent["max_tokens"], 300)

    def test_no_key_raises_and_names_env_var(self):
        config.LLM_API_KEY = ""
        with mock.patch("urllib.request.urlopen") as urlopen:
            with self.assertRaises(LLMError) as ctx:
                OpenAICompatibleProvider().complete("sys", "user")
        urlopen.assert_not_called()
        self.assertIn("CBA_LLM_API_KEY", str(ctx.exception))

    def test_http_error_raises_llmerror_without_key(self):
        config.LLM_API_KEY = "sk-secret-abc123"
        err = urllib.error.HTTPError(
            "https://api.openai.com/v1/chat/completions",
            500,
            "Server Error",
            {},
            None,
        )
        with mock.patch("urllib.request.urlopen", side_effect=err):
            with self.assertRaises(LLMError) as ctx:
                OpenAICompatibleProvider().complete("sys", "user")
        self.assertIn("500", str(ctx.exception))
        self.assertNotIn("sk-secret-abc123", str(ctx.exception))

    def test_malformed_json_raises_llmerror(self):
        with mock.patch("urllib.request.urlopen", self._fake_urlopen(b"not json")):
            with self.assertRaises(LLMError):
                OpenAICompatibleProvider().complete("sys", "user")

    def test_missing_choices_raises_llmerror(self):
        for body in (b"{}", b'{"choices": []}', b'{"choices": [{}]}'):
            with mock.patch(
                "urllib.request.urlopen", self._fake_urlopen(body)
            ), self.assertRaises(LLMError):
                OpenAICompatibleProvider().complete("sys", "user")

    def test_key_never_leaks_into_error_messages(self):
        """A backend echoing the key back must still not leak it via LLMError."""
        config.LLM_API_KEY = "sk-secret-abc123"
        leak = urllib.error.URLError("proxy refused, key was sk-secret-abc123")
        with mock.patch("urllib.request.urlopen", side_effect=leak):
            with self.assertRaises(LLMError) as ctx:
                OpenAICompatibleProvider().complete("sys", "user")
        self.assertNotIn("sk-secret-abc123", str(ctx.exception))
        self.assertIn("***", str(ctx.exception))

    def test_provider_exposes_complete(self):
        provider = OpenAICompatibleProvider()
        self.assertTrue(hasattr(provider, "complete"))
        self.assertTrue(callable(provider.complete))

    def test_custom_base_url_respected(self):
        config.LLM_BASE_URL = "https://my-proxy.example/v1/"
        body = b'{"choices":[{"message":{"content":"x"}}]}'
        with mock.patch("urllib.request.urlopen", self._fake_urlopen(body)):
            OpenAICompatibleProvider().complete("sys", "user")
        self.assertEqual(
            self.captured["request"].full_url,
            "https://my-proxy.example/v1/chat/completions",
        )


if __name__ == "__main__":
    unittest.main()
