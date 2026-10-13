"""Tiny web server so you can use the report from your phone.

  python -m vdf serve --port 8000 --scan-every 30 --key mysecret

Open http://<this-computer's-LAN-IP>:8000/?key=mysecret on your phone (same Wi-Fi), then
"Add to Home Screen". The page gets a "Scan now" button. Use a tunnel (Tailscale, Cloudflare Tunnel)
for access away from home; don't port-forward it to the open internet.
"""
from __future__ import annotations

import hmac
import json
import logging
import socket
import threading
import time
from functools import partial
from http.cookies import SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

log = logging.getLogger(__name__)


class Scanner:
    """Runs scans in a background thread, one at a time."""

    def __init__(self, scan_fn):
        self.scan_fn = scan_fn
        self.lock = threading.Lock()
        self.running = False
        self.last_scan = None
        self.error = None

    def start(self) -> bool:
        if not self.lock.acquire(blocking=False):
            return False
        self.running = True
        threading.Thread(target=self._run, daemon=True).start()
        return True

    def _run(self):
        try:
            res = self.scan_fn()
            self.last_scan, self.error = res.started.isoformat(), None
        except Exception as e:
            log.exception("scan failed")
            self.error = str(e)[:200]
        finally:
            self.running = False
            self.lock.release()

    def status(self) -> dict:
        return {"running": self.running, "last_scan": self.last_scan, "error": self.error}


class Handler(SimpleHTTPRequestHandler):
    scanner: Scanner = None
    key: str = ""

    def _authorised(self) -> bool:
        if not self.key:
            return True
        q = parse_qs(urlparse(self.path).query).get("key", [""])[0]
        c = SimpleCookie(self.headers.get("Cookie", "")).get("vdf_key")
        given = q or (c.value if c else "")
        return hmac.compare_digest(given, self.key)

    def _deny(self):
        self.send_response(401)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Add ?key=... to the URL (see `serve --key`).")

    def end_headers(self):
        if self.key and "key=" in self.path:
            # Remember the key so the home-screen app keeps working without it in the URL.
            self.send_header("Set-Cookie", f"vdf_key={self.key}; Max-Age=31536000; Path=/; SameSite=Lax; HttpOnly")
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self._authorised():
            return self._deny()
        if urlparse(self.path).path == "/api/status":
            return self._json(self.scanner.status())
        return super().do_GET()

    def do_POST(self):
        if not self._authorised():
            return self._deny()
        if urlparse(self.path).path == "/api/scan":
            return self._json({"started": self.scanner.start()}, 202)
        self.send_error(404)

    def log_message(self, fmt, *args):
        log.debug("%s " + fmt, self.address_string(), *args)


def lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def serve(out_dir: Path, scan_fn, host: str = "0.0.0.0", port: int = 8000, scan_every: int = 0, key: str = ""):
    out_dir.mkdir(parents=True, exist_ok=True)
    scanner = Scanner(scan_fn)
    handler = type("H", (Handler,), {"scanner": scanner, "key": key})
    httpd = ThreadingHTTPServer((host, port), partial(handler, directory=str(out_dir)))
    if not (out_dir / "index.html").exists() or scan_every:
        scanner.start()
    if scan_every:
        def loop():
            while True:
                time.sleep(scan_every * 60)
                scanner.start()
        threading.Thread(target=loop, daemon=True).start()
    url = f"http://{lan_ip()}:{port}/" + (f"?key={key}" if key else "")
    print(f"Open on your phone (same Wi-Fi): {url}\nThen use Share → Add to Home Screen. Ctrl+C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
