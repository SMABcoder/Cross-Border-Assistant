"""Local web UI: stdlib ``http.server`` JSON API + self-contained chat page.

Binds to 127.0.0.1 by default and serves data from the local SQLite DB
only. No authentication is required for the localhost demo -- this is
deliberate for ease of demoing, but PRODUCTION USE MUST sit behind a
reverse proxy (TLS) with authentication. Nothing leaves this machine:
no external network calls are made by the server itself.

Tunables are read from :mod:`config` (``CBA_`` env overrides):
``WEB_HOST``, ``WEB_PORT``, ``WEB_MAX_BODY_BYTES``, ``APP_CURRENCY``,
``DEFAULT_LANG``. They are read inside methods so tests can override
them.
"""
from __future__ import annotations

import json
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import config
from cba.assistant import Assistant
from cba.fx import FxError, FxService


# -- JSON safety ------------------------------------------------------------
def _json_safe(value):
    """Convert any value to something ``json.dumps`` can serialize.

    Budget/alert rows may carry ``None``, ints, floats, strings; this also
    defends against Decimals, datetimes or NaN/Inf sneaking into payloads.
    """
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if value == value and abs(value) != float("inf") else None
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    try:  # Decimal and friends
        return float(value)
    except (TypeError, ValueError):
        return str(value)


# -- HTML chat page (single self-contained file, no external assets) --------
_INDEX_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cross Border Assistant</title>
<style>
  body { font-family: system-ui, -apple-system, sans-serif; margin: 0;
         background: #f4f6f8; color: #1a1a1a; }
  .wrap { max-width: 720px; margin: 0 auto; padding: 24px 16px 80px; }
  h1 { font-size: 1.4rem; margin: 0 0 4px; }
  .sub { color: #666; font-size: 0.85rem; margin-bottom: 16px; }
  #log { display: flex; flex-direction: column; gap: 10px; }
  .msg { padding: 10px 14px; border-radius: 12px; max-width: 85%;
         line-height: 1.45; white-space: pre-wrap; word-wrap: break-word; }
  .user { align-self: flex-end; background: #1a73e8; color: #fff; }
  .bot { align-self: flex-start; background: #fff; border: 1px solid #ddd; }
  .err { align-self: flex-start; background: #fdecea; border: 1px solid #f5c6cb;
         color: #a94442; }
  .bar { position: fixed; left: 0; right: 0; bottom: 0; background: #fff;
         border-top: 1px solid #ddd; padding: 10px 16px; }
  .bar-inner { max-width: 720px; margin: 0 auto; display: flex; gap: 8px; }
  #input { flex: 1; padding: 10px 12px; font-size: 1rem;
           border: 1px solid #ccc; border-radius: 8px; }
  #send { padding: 10px 20px; font-size: 1rem; border: none; border-radius: 8px;
          background: #1a73e8; color: #fff; cursor: pointer; }
  #send:disabled { background: #9db8e8; cursor: wait; }
  .note { margin-top: 20px; color: #888; font-size: 0.75rem; }
</style>
</head>
<body>
<div class="wrap">
  <h1>Cross Border Assistant</h1>
  <div class="sub">Your cross-border student finance helper</div>
  <div id="log"></div>
  <div class="note">Demo UI &mdash; all data stays on this machine.</div>
</div>
<div class="bar">
  <div class="bar-inner">
    <input id="input" type="text" autocomplete="off"
           placeholder="Try: convert 100 USD to CNY">
    <button id="send">Send</button>
  </div>
</div>
<script>
(function () {
  var log = document.getElementById("log");
  var input = document.getElementById("input");
  var sendBtn = document.getElementById("send");

  function addMsg(text, cls) {
    var div = document.createElement("div");
    div.className = "msg " + cls;
    div.textContent = text;
    log.appendChild(div);
    window.scrollTo(0, document.body.scrollHeight);
  }

  function send() {
    var text = input.value.trim();
    if (!text) return;
    addMsg(text, "user");
    input.value = "";
    sendBtn.disabled = true;
    fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text })
    })
      .then(function (resp) {
        if (!resp.ok) {
          return resp.json().then(function (data) {
            throw new Error(data.error || ("HTTP " + resp.status));
          });
        }
        return resp.json();
      })
      .then(function (data) { addMsg(data.reply, "bot"); })
      .catch(function (err) { addMsg("Error: " + err.message, "err"); })
      .then(function () { sendBtn.disabled = false; input.focus(); });
  }

  sendBtn.addEventListener("click", send);
  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter") send();
  });
  addMsg("Hello! Ask me about exchange rates, budgets, tuition, "
       + "transfers, credit building or rate alerts.", "bot");
  input.focus();
})();
</script>
</body>
</html>
"""


class WebApp:
    """The HTTP application: service wiring + routes."""

    def __init__(
        self,
        db_path: str | Path | None = None,
        fx: FxService | None = None,
    ) -> None:
        self.fx = fx or FxService()
        # The Assistant builds BudgetService and AlertService internally;
        # reuse those instances so every route shares one db_path and one fx.
        self.assistant = Assistant(db_path=db_path, fx=self.fx)
        self.budgets = self.assistant.budgets
        self.alerts = self.assistant.alerts

    # -- server lifecycle ---------------------------------------------------
    def handler_class(self) -> type[BaseHTTPRequestHandler]:
        """Return a request-handler class closing over this app instance."""
        app = self

        class _RequestHandler(BaseHTTPRequestHandler):
            server_version = "CrossBorderAssistant/1"

            def log_message(self, *args):  # keep test output clean
                pass

            def do_GET(self):
                parsed = urlparse(self.path)
                route = parsed.path
                if route == "/":
                    app._serve_index(self)
                elif route == "/api/rates":
                    app._get_rates(self, parse_qs(parsed.query))
                elif route == "/api/budget":
                    app._get_budget(self)
                elif route == "/api/alerts":
                    app._list_alerts(self)
                else:
                    app._send_json(self, 404, {"error": "not found"})

            def do_POST(self):
                body = app._read_body(self)
                if body is None:  # 413 already sent
                    return
                route = urlparse(self.path).path
                if route == "/api/chat":
                    app._post_chat(self, body)
                elif route == "/api/alerts":
                    app._post_alert(self, body)
                else:
                    app._send_json(self, 404, {"error": "not found"})

        return _RequestHandler

    def start(self, host: str | None = None, port: int | None = None):
        """Start a ThreadingHTTPServer in a daemon thread; return (server, thread).

        ``port=0`` lets the OS pick an ephemeral port (used by tests); the
        actual port is ``server.server_address[1]``.
        """
        host = host or config.WEB_HOST
        port = config.WEB_PORT if port is None else port
        server = ThreadingHTTPServer((host, port), self.handler_class())
        thread = threading.Thread(
            target=server.serve_forever, daemon=True, name="cba-web"
        )
        thread.start()
        return server, thread

    def run(self, host: str | None = None, port: int | None = None) -> None:
        """Block serving forever (the ``cba serve`` entry point)."""
        host = host or config.WEB_HOST
        port = config.WEB_PORT if port is None else port
        server = ThreadingHTTPServer((host, port), self.handler_class())
        print(
            f"Serving on http://{host}:{server.server_address[1]}"
            " — Ctrl-C to stop"
        )
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()

    # -- response helpers ---------------------------------------------------
    @staticmethod
    def _send_json(handler: BaseHTTPRequestHandler, status: int, payload: dict) -> None:
        body = json.dumps(_json_safe(payload)).encode("utf-8")
        handler.send_response(status)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)

    @staticmethod
    def _send_html(handler: BaseHTTPRequestHandler, html: str) -> None:
        body = html.encode("utf-8")
        handler.send_response(200)
        handler.send_header("Content-Type", "text/html; charset=utf-8")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)

    def _read_body(self, handler: BaseHTTPRequestHandler) -> bytes | None:
        """Read the request body; send 413 and return None if oversized."""
        raw = handler.headers.get("Content-Length")
        try:
            length = int(raw) if raw else 0
        except (TypeError, ValueError):
            length = 0
        max_bytes = config.WEB_MAX_BODY_BYTES
        if length > max_bytes:
            self._send_json(handler, 413, {"error": "request body too large"})
            return None
        body = handler.rfile.read(length) if length > 0 else b""
        if len(body) > max_bytes:
            self._send_json(handler, 413, {"error": "request body too large"})
            return None
        return body

    @staticmethod
    def _parse_json(body: bytes) -> tuple[dict | None, str | None]:
        """Return (payload, error). Payload must be a JSON object."""
        try:
            payload = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None, "invalid JSON body"
        if not isinstance(payload, dict):
            return None, "body must be a JSON object"
        return payload, None

    # -- routes -------------------------------------------------------------
    def _serve_index(self, handler: BaseHTTPRequestHandler) -> None:
        self._send_html(handler, _INDEX_HTML)

    def _get_rates(
        self, handler: BaseHTTPRequestHandler, query: dict[str, list[str]]
    ) -> None:
        base = (query.get("base") or [""])[0].strip().upper()
        quote = (query.get("quote") or [""])[0].strip().upper()
        if not base or not quote:
            self._send_json(
                handler, 400, {"error": "base and quote query params are required"}
            )
            return
        try:
            rate = self.fx.get_rate(base, quote)
        except FxError as exc:
            self._send_json(handler, 400, {"error": str(exc)})
            return
        self._send_json(handler, 200, {"pair": f"{base}/{quote}", "rate": rate})

    def _post_chat(self, handler: BaseHTTPRequestHandler, body: bytes) -> None:
        payload, error = self._parse_json(body)
        if error:
            self._send_json(handler, 400, {"error": error})
            return
        message = payload.get("message")
        if not isinstance(message, str) or not message.strip():
            self._send_json(handler, 400, {"error": "message is required"})
            return
        lang = payload.get("lang")
        if lang is not None and (not isinstance(lang, str) or not lang.strip()):
            self._send_json(handler, 400, {"error": "lang must be a string"})
            return
        try:
            reply = self.assistant.chat(message, lang=lang or None)
        except Exception as exc:  # never leak a stack trace to the client
            self._send_json(handler, 500, {"error": f"assistant error: {exc}"})
            return
        self._send_json(handler, 200, {"reply": reply})

    def _get_budget(self, handler: BaseHTTPRequestHandler) -> None:
        today = date.today()
        status = self.budgets.status(today.year, today.month)
        self._send_json(handler, 200, _json_safe(status))

    def _list_alerts(self, handler: BaseHTTPRequestHandler) -> None:
        self._send_json(handler, 200, {"alerts": _json_safe(self.alerts.list())})

    def _post_alert(self, handler: BaseHTTPRequestHandler, body: bytes) -> None:
        payload, error = self._parse_json(body)
        if error:
            self._send_json(handler, 400, {"error": error})
            return
        pair = payload.get("pair")
        direction = payload.get("direction")
        target = payload.get("target")
        if not isinstance(pair, str) or not pair.strip():
            self._send_json(
                handler, 400, {"error": "pair is required, e.g. USD/CNY"}
            )
            return
        if not isinstance(direction, str) or not direction.strip():
            self._send_json(
                handler, 400, {"error": "direction must be 'above' or 'below'"}
            )
            return
        try:
            target_num = float(target)
        except (TypeError, ValueError):
            self._send_json(handler, 400, {"error": "target must be a number"})
            return
        try:
            alert = self.alerts.create(pair.strip(), target_num, direction)
        except (ValueError, KeyError) as exc:
            self._send_json(handler, 400, {"error": str(exc)})
            return
        self._send_json(handler, 201, {"alert": _json_safe(alert)})
