"""Tests for the local web UI: stdlib http.server JSON API + chat page.

The server runs on an ephemeral 127.0.0.1 port in a background thread;
everything is exercised over real HTTP with urllib. No external network.
"""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

import config
from cba.web import WebApp
from tests.helpers import fake_fx


class WebTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.mkdtemp(prefix="cba-web-test-")
        cls.db = str(Path(cls.tmp) / "test.db")
        cls.fx = fake_fx(cls.tmp)  # FakeProvider: USD base -> CNY 7.25
        cls.app = WebApp(db_path=cls.db, fx=cls.fx)
        cls.server, cls.thread = cls.app.start(host="127.0.0.1", port=0)
        cls.base_url = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    # -- helpers ------------------------------------------------------------
    def _request(self, method: str, path: str, payload: dict | None = None,
                 raw: bytes | None = None) -> tuple[int, str, bytes]:
        body = raw if raw is not None else (
            json.dumps(payload).encode("utf-8") if payload is not None else None
        )
        req = urllib.request.Request(self.base_url + path, data=body, method=method)
        if body is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, resp.headers.get("Content-Type", ""), resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.headers.get("Content-Type", ""), exc.read()

    def _get(self, path: str) -> tuple[int, str, bytes]:
        return self._request("GET", path)

    def _post(self, path: str, payload: dict | None = None,
              raw: bytes | None = None) -> tuple[int, str, bytes]:
        return self._request("POST", path, payload=payload, raw=raw)

    # -- tests --------------------------------------------------------------
    def test_index_returns_html_chat_page(self):
        status, ctype, body = self._get("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", ctype)
        html = body.decode("utf-8")
        self.assertIn("Cross Border Assistant", html)
        self.assertIn("Demo UI", html)

    def test_rates_endpoint_returns_fake_rate(self):
        status, ctype, body = self._get("/api/rates?base=USD&quote=CNY")
        self.assertEqual(status, 200)
        self.assertIn("application/json", ctype)
        payload = json.loads(body.decode("utf-8"))
        self.assertEqual(payload["pair"], "USD/CNY")
        self.assertEqual(payload["rate"], 7.25)

    def test_rates_missing_params_is_400(self):
        status, _, body = self._get("/api/rates?base=USD")
        self.assertEqual(status, 400)
        self.assertIn("error", json.loads(body.decode("utf-8")))

    def test_rates_unknown_currency_is_400(self):
        status, _, body = self._get("/api/rates?base=USD&quote=ZZZ")
        self.assertEqual(status, 400)
        self.assertIn("error", json.loads(body.decode("utf-8")))

    def test_chat_convert_uses_fake_fx(self):
        status, _, body = self._post(
            "/api/chat", {"message": "convert 100 USD to CNY"}
        )
        self.assertEqual(status, 200)
        payload = json.loads(body.decode("utf-8"))
        reply = payload["reply"]
        # 100 * 7.25 = 725.00 -> formatted "725.00 CNY"
        self.assertIn("725", reply, reply)

    def test_chat_empty_message_is_400(self):
        for payload in ({}, {"message": ""}, {"message": "   "}):
            status, _, body = self._post("/api/chat", payload)
            self.assertEqual(status, 400, payload)
            self.assertIn("error", json.loads(body.decode("utf-8")))

    def test_chat_invalid_json_is_400(self):
        status, _, _ = self._post("/api/chat", raw=b"{not json")
        self.assertEqual(status, 400)

    def test_budget_returns_json_status(self):
        status, ctype, body = self._get("/api/budget")
        self.assertEqual(status, 200)
        self.assertIn("application/json", ctype)
        payload = json.loads(body.decode("utf-8"))
        self.assertIn("total", payload)
        self.assertIn("spent", payload["total"])

    def test_alert_create_and_list(self):
        status, _, body = self._post(
            "/api/alerts",
            {"pair": "USD/CNY", "target": 7.3, "direction": "above"},
        )
        self.assertEqual(status, 201, body.decode("utf-8"))
        alert = json.loads(body.decode("utf-8"))["alert"]
        self.assertEqual(alert["pair"], "USD/CNY")
        self.assertEqual(alert["target"], 7.3)
        self.assertEqual(alert["direction"], "above")

        status, _, body = self._get("/api/alerts")
        self.assertEqual(status, 200)
        alerts = json.loads(body.decode("utf-8"))["alerts"]
        self.assertTrue(any(a["id"] == alert["id"] for a in alerts))

    def test_alert_invalid_direction_is_400(self):
        status, _, body = self._post(
            "/api/alerts",
            {"pair": "USD/CNY", "target": 7.3, "direction": "sideways"},
        )
        self.assertEqual(status, 400)
        self.assertIn("error", json.loads(body.decode("utf-8")))

    def test_alert_missing_pair_is_400(self):
        status, _, _ = self._post(
            "/api/alerts", {"target": 7.3, "direction": "above"}
        )
        self.assertEqual(status, 400)

    def test_unknown_path_is_404_json(self):
        status, ctype, body = self._get("/nope")
        self.assertEqual(status, 404)
        self.assertIn("application/json", ctype)
        self.assertEqual(json.loads(body.decode("utf-8")), {"error": "not found"})

    def test_oversized_body_is_413(self):
        # Shrink the limit so a modest body trips it (config is read per request).
        with mock.patch.object(config, "WEB_MAX_BODY_BYTES", 16):
            status, _, body = self._post("/api/chat", raw=b"x" * 64)
            self.assertEqual(status, 413)
            self.assertIn("error", json.loads(body.decode("utf-8")))


if __name__ == "__main__":
    unittest.main()
