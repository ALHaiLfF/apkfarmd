"""Веб-панель: открывается окном на ПК и по QR-коду на телефоне (та же Wi-Fi сеть)."""
from __future__ import annotations

import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import qr

HERE = Path(__file__).resolve().parent
UI_FILE = HERE / "ui.html"
APP_ID = "anime-fishing"
DEFAULT_AREA = {"x": 0.7317708, "y": 0.2925, "w": 0.0385417, "h": 0.3766667}


def lan_ips() -> list[str]:
    ips: list[str] = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ips.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in ips and not ip.startswith(("127.", "169.254.")):
                ips.append(ip)
    except OSError:
        pass
    return [ip for ip in ips if not ip.startswith("127.")]


class Panel:
    def __init__(self, cfg, hub, sup, preview_fn, on_exit, host="0.0.0.0", strict=False,
                 extra_state=None, start_check=None) -> None:
        self.cfg, self.hub, self.sup = cfg, hub, sup
        self.host, self.strict = host, strict
        self.extra_state, self.start_check = extra_state, start_check
        self.preview_fn = preview_fn
        self.on_exit = on_exit
        self.port = 0
        self._srv: ThreadingHTTPServer | None = None
        self._prev = (0.0, None)
        self.last_seen = time.time()
        self._prev_lock = threading.Lock()

    # ---- адреса
    def token(self) -> str:
        return self.cfg.get("web")["token"]

    def local_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/?k={self.token()}"

    def phone_url(self) -> str | None:
        ips = lan_ips()
        return f"http://{ips[0]}:{self.port}/?k={self.token()}" if ips else None

    # ---- запуск
    def start(self) -> int:
        base = int(self.cfg.get("web").get("port", 8765))
        panel = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def _local(self) -> bool:
                return (not panel.strict) and self.client_address[0] in ("127.0.0.1", "::1")

            def _authorized(self, query) -> bool:
                if self._local():
                    return True
                key = (query.get("k") or [""])[0] or self.headers.get("X-Key", "")
                return bool(key) and key == panel.token()

            def _send(self, code, body: bytes, ctype="application/json; charset=utf-8", extra=None):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                for k, v in (extra or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(body)

            def _json(self, obj, code=200):
                self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

            def do_GET(self):
                u = urlparse(self.path)
                q = parse_qs(u.query)
                if u.path == "/api/ping":
                    return self._json({"app": APP_ID})
                if not self._authorized(q):
                    return self._send(403, "Нужна ссылка с ключом (отсканируй QR на ПК)".encode("utf-8"),
                                      "text/plain; charset=utf-8")
                if u.path in ("/", "/index.html"):
                    try:
                        return self._send(200, UI_FILE.read_bytes(), "text/html; charset=utf-8")
                    except OSError:
                        return self._send(500, b"ui.html not found", "text/plain")
                if u.path == "/api/state":
                    panel.last_seen = time.time()
                    since = int((q.get("since") or ["0"])[0] or 0)
                    return self._json(panel.state(since))
                if u.path == "/api/frame.jpg":
                    data = panel.frame()
                    if data is None:
                        return self._send(404, b"no window", "text/plain")
                    return self._send(200, data, "image/jpeg")
                if u.path == "/api/qr.svg":
                    url = panel.phone_url()
                    if not url:
                        return self._send(404, b"no network", "text/plain")
                    return self._send(200, qr.make_svg(url).encode("utf-8"), "image/svg+xml")
                return self._send(404, b"not found", "text/plain")

            def do_POST(self):
                u = urlparse(self.path)
                q = parse_qs(u.query)
                if not self._authorized(q):
                    return self._send(403, b"forbidden", "text/plain")
                n = int(self.headers.get("Content-Length") or 0)
                try:
                    body = json.loads(self.rfile.read(n) or b"{}") if n else {}
                except Exception:
                    body = {}
                try:
                    return self._json(panel.act(u.path, body, self._local()))
                except Exception as exc:  # noqa: BLE001
                    return self._json({"ok": False, "error": str(exc)}, 500)

        last_err = None
        for p in range(base, base + 20):
            try:
                self._srv = ThreadingHTTPServer((self.host, p), H)
                self.port = p
                break
            except OSError as exc:
                last_err = exc
        if self._srv is None:
            raise RuntimeError(f"не удалось открыть порт: {last_err}")
        self._srv.daemon_threads = True
        threading.Thread(target=self._srv.serve_forever, name="web", daemon=True).start()
        return self.port

    def stop(self) -> None:
        if self._srv is not None:
            threading.Thread(target=self._srv.shutdown, daemon=True).start()

    # ---- данные
    def state(self, since: int) -> dict:
        s = self.hub.snapshot(since)
        c = self.cfg.data
        s["settings"] = {
            "rod_key": c.get("rod_key", ""),
            "collect_mode": c.get("collect_mode", "t"),
            "autostart": bool(c.get("autostart")),
            "hotkey": (c.get("hotkeys") or {}).get("toggle", "F1"),
        }
        s["phone_url"] = self.phone_url()
        s["cast"] = c.get("cast")
        if self.extra_state is not None:
            try:
                s.update(self.extra_state())
            except Exception:  # noqa: BLE001
                pass
        return s

    def frame(self):
        with self._prev_lock:
            t, data = self._prev
            if time.time() - t < 0.35:
                return data
            try:
                data = self.preview_fn()
            except Exception:
                data = None
            self._prev = (time.time(), data)
            return data

    def act(self, path: str, body: dict, local: bool) -> dict:
        if path in ("/api/start", "/api/toggle") and self.start_check is not None and not self.sup.running:
            problem = self.start_check()
            if problem:
                return {"ok": False, "error": problem, "running": False}
        if path == "/api/start":
            return {"ok": True, "running": self.sup.start() or self.sup.running}
        if path == "/api/stop":
            self.sup.stop()
            return {"ok": True, "running": False}
        if path == "/api/toggle":
            return {"ok": True, "running": self.sup.toggle()}
        if path == "/api/cast":
            x, y = float(body["x"]), float(body["y"])
            if not (0 <= x <= 1 and 0 <= y <= 1):
                return {"ok": False, "error": "точка вне окна"}
            self.cfg.update({"cast": {"x": round(x, 5), "y": round(y, 5)}})
            self.hub.event("info", "Точка заброса обновлена")
            return {"ok": True}
        if path == "/api/settings":
            patch = {}
            if "rod_key" in body:
                patch["rod_key"] = str(body["rod_key"]).strip()[:12]
            if body.get("collect_mode") in ("t", "click"):
                patch["collect_mode"] = body["collect_mode"]
            if "autostart" in body:
                patch["autostart"] = bool(body["autostart"])
            if patch:
                self.cfg.update(patch)
            return {"ok": True}
        if path == "/api/reset_area":
            self.cfg.update({"scan_area": dict(DEFAULT_AREA)})
            self.hub.event("info", "Область шкалы сброшена, найду заново сама")
            return {"ok": True}
        if path == "/api/exit" and local:
            threading.Thread(target=self.on_exit, daemon=True).start()
            return {"ok": True}
        return {"ok": False, "error": "unknown"}
