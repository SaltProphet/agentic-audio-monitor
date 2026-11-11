"""Local page. It serves this process only and has no remote client."""

from __future__ import annotations

import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

log = logging.getLogger("audiomonitor")

WEB_PATH = Path(__file__).resolve().parent / "web" / "index.html"
_BLANK_GIF = (
    b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!"
    b"\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00"
    b"\x00\x02\x02D\x01\x00;"
)


class MonitorServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, engine):
        super().__init__(address, Handler)
        self.engine = engine


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:
        return

    def do_GET(self) -> None:
        path = unquote(urlsplit(self.path).path)
        if path == "/":
            self._bytes(200, "text/html; charset=utf-8", WEB_PATH.read_bytes())
            return
        if path == "/favicon.ico":
            self._bytes(200, "image/gif", _BLANK_GIF)
            return
        if path == "/api/state":
            self._json(200, self.server.engine.snapshot())
            return
        if path == "/api/cc":
            self._json(200, self.server.engine.cc.snapshot())
            return
        if path == "/api/devices":
            self._json(200, self.server.engine.list_devices())
            return
        if path == "/api/live":
            self._live()
            return
        if path.startswith("/clips/"):
            self._clip(path[len("/clips/") :])
            return
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        try:
            self._handle_post()
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception:
            # A bad payload must come back as an error, not as a dropped connection.
            log.exception("unhandled error while applying a request")
            try:
                self._json(500, {"error": "The monitor could not apply that change."})
            except OSError:
                return

    def _handle_post(self) -> None:
        path = unquote(urlsplit(self.path).path)
        if not self._write_allowed():
            self._json(403, {"error": "Writes must be JSON from this page."})
            return
        try:
            payload = self._read_json()
        except ValueError as exc:
            self._json(400, {"error": str(exc)})
            return
        engine = self.server.engine
        if path == "/api/device":
            try:
                index = payload.get("index")
                index = None if index is None else int(index)
                name = payload.get("name")
                hostapi = payload.get("hostapi", "")
                if not isinstance(name, str) or not name.strip() or not isinstance(hostapi, str):
                    raise ValueError("name and hostapi are required")
            except (TypeError, ValueError) as exc:
                self._json(400, {"error": str(exc)})
                return
            ok, message = engine.select_device(index, name, hostapi)
            self._json(200 if ok else 409, {"ok": ok, "message": message, "state": engine.snapshot()})
            return
        if path == "/api/settings":
            ok, message = engine.update_settings(payload)
            code = 200 if ok else 400
            self._json(code, {"ok": ok, "message": message, "state": engine.snapshot()})
            return
        if path == "/api/cc":
            ok, message = engine.update_cc(payload)
            code = 200 if ok else 400
            self._json(code, {"ok": ok, "message": message, "state": engine.snapshot()})
            return
        if path == "/api/model/load":
            ok, message = engine.request_load()
            self._json(200 if ok else 409, {"ok": ok, "message": message, "state": engine.snapshot()})
            return
        self._json(404, {"error": "not found"})

    def _live(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self._security_headers()
        self.end_headers()
        engine = self.server.engine
        try:
            while not engine.stop_event.is_set():
                payload = json.dumps(engine.live(), separators=(",", ":"))
                self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                self.wfile.flush()
                if engine.stop_event.wait(0.1):
                    break
        except (BrokenPipeError, ConnectionResetError, OSError):
            return

    def _clip(self, name: str) -> None:
        path = self.server.engine.clip_file(name)
        if path is None:
            self._json(404, {"error": "clip not found"})
            return
        data = path.read_bytes()
        self._bytes(200, "audio/wav", data)

    def _write_allowed(self) -> bool:
        """Only this page may change state. Cross-origin form posts are refused."""
        if self.headers.get_content_type() != "application/json":
            return False
        origin = (self.headers.get("Origin") or "").strip()
        if not origin:
            return True
        host = (self.headers.get("Host") or "").strip().lower()
        return bool(host) and urlsplit(origin).netloc.lower() == host

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length < 0 or length > 32768:
            raise ValueError("body is too large")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("body must be JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("body must be a JSON object")
        return payload

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._bytes(status, "application/json; charset=utf-8", body)

    def _security_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")

    def _bytes(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._security_headers()
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)


def serve(engine, host: str, port: int) -> MonitorServer:
    httpd = MonitorServer((host, port), engine)
    return httpd
