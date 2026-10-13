"""«Мир» для Android: кадры экрана (MediaProjection) и касания (AccessibilityService) через мост Kotlin.

Интерфейс тот же, что у RealWorld на ПК, поэтому мозг (brain.py) один и тот же: тот же самолечащийся
автомат, те же лестница восстановления и сторож. Отличия телефона:
  * «окно» = кадр экрана; «на переднем плане» = пакет приложения Roblox;
  * «клавиша удочки» = тап по слоту удочки на панели;
  * сбор рыбы = удержание пальца на кнопке «Собрать»;
  * «зажать мышь» = удерживать палец на точке заброса (так играется миниигра).
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass

import cv2
import numpy as np

from brain import Look
from config import Config
import diamond
from detect import Detector

cv2.setNumThreads(2)

_B = None  # мост Kotlin (или заглушка в тестах)


def set_bridge(bridge) -> None:
    global _B
    _B = bridge


def bridge():
    global _B
    if _B is None:
        from java import jclass  # доступно только внутри Chaquopy
        _B = jclass("app.sakura.fishing.Bridge")
    return _B


@dataclass
class PixelRect:
    x: int
    y: int
    w: int
    h: int


def _u8(arr) -> np.ndarray:
    """Java byte[] -> numpy uint8 (через буфер, а если не вышло — медленным, но верным путём)."""
    try:
        return np.frombuffer(arr, dtype=np.uint8)
    except Exception:  # noqa: BLE001
        try:
            return np.frombuffer(bytes(arr), dtype=np.uint8)
        except Exception:  # noqa: BLE001
            return np.frombuffer(bytes(bytearray((b & 0xFF) for b in arr)), dtype=np.uint8)


def _rgba_to_bgr(a: np.ndarray, w: int, h: int) -> np.ndarray:
    if a.size != w * h * 4:
        raise RuntimeError(f"кадр {a.size} байт вместо {w * h * 4}")
    return np.ascontiguousarray(cv2.cvtColor(a.reshape(h, w, 4), cv2.COLOR_RGBA2BGR))


def _cut(r: PixelRect, bounds: PixelRect) -> PixelRect:
    x0, y0 = max(bounds.x, r.x), max(bounds.y, r.y)
    x1, y1 = min(bounds.x + bounds.w, r.x + r.w), min(bounds.y + bounds.h, r.y + r.h)
    return PixelRect(x0, y0, max(1, x1 - x0), max(1, y1 - y0))


_held = False
NOTE = {"text": "", "fps": 0.0, "t": 0.0}


def release_all() -> None:
    global _held
    _held = False
    try:
        bridge().releaseAll()
    except Exception:  # noqa: BLE001
        pass


def status() -> dict:
    try:
        return json.loads(str(bridge().status()))
    except Exception:  # noqa: BLE001
        return {"access": False, "capture": False, "pkg": "", "w": 0, "h": 0}


class AndroidWorld:
    missing_msg = "Не вижу экран (захват выключен) — жду"

    def __init__(self, cfg: Config, hub) -> None:
        self.cfg = cfg
        self.hub = hub
        self.scanner = Detector()
        self.abort = lambda: False
        self._roi: PixelRect | None = None
        self._small = None
        self._look_errs = 0
        self._err_logged = 0.0
        self._no_pt_logged = 0.0

    # ---- время
    def now(self) -> float:
        return time.perf_counter()

    def sleep(self, s: float) -> None:
        time.sleep(max(0.0, s))

    def _sleep_abortable(self, s: float) -> None:
        end = time.perf_counter() + s
        while time.perf_counter() < end and not self.abort():
            time.sleep(min(0.02, max(0.0, end - time.perf_counter())))

    # ---- жизненный цикл
    def open(self) -> None:
        adv = self.cfg.advanced_all()
        self.scanner.configure(self.cfg.get("bar_colors"), adv["yellow_boost"], adv["green_boost"], adv["white_boost"])
        release_all()

    def close(self) -> None:
        release_all()

    # ---- «окно»
    def _screen(self) -> PixelRect | None:
        try:
            sz = bridge().screenSize()
            w, h = int(sz[0]), int(sz[1])
        except Exception:  # noqa: BLE001
            return None
        return PixelRect(0, 0, w, h) if w > 0 and h > 0 else None

    def window_ok(self) -> bool:
        try:
            ok = bool(bridge().captureReady()) and self._screen() is not None
        except Exception:  # noqa: BLE001
            ok = False
        self.hub.window_ok = ok
        return ok

    def is_foreground(self) -> bool:
        try:
            pkg = str(bridge().foregroundPkg() or "")
        except Exception:  # noqa: BLE001
            return True
        if not pkg:
            return True   # не знаем — не гоняем игру туда-сюда
        return "roblox" in pkg.lower()

    def focus(self) -> bool:
        try:
            bridge().launchGame()
        except Exception:  # noqa: BLE001
            return False
        end = time.perf_counter() + 6.0
        while time.perf_counter() < end and not self.abort():
            if self.is_foreground():
                break
            time.sleep(0.25)
        time.sleep(0.4)
        return self.is_foreground()

    def cursor_ok(self) -> bool:
        return True

    def park_cursor(self) -> None:
        return None

    # ---- зрение
    def _grab(self, x: int, y: int, w: int, h: int) -> np.ndarray:
        s = self._screen()
        if s is None:
            raise RuntimeError("нет кадра")
        x, y = max(0, min(s.w - 1, int(x))), max(0, min(s.h - 1, int(y)))
        w, h = max(1, min(s.w - x, int(w))), max(1, min(s.h - y, int(h)))
        arr = bridge().grab(x, y, w, h)
        if arr is None:
            raise RuntimeError("нет кадра")
        return _rgba_to_bgr(_u8(arr), w, h)

    def _area_px(self, c: PixelRect) -> PixelRect:
        sa = self.cfg.get("scan_area") or {}
        return PixelRect(
            int(round(c.x + float(sa.get("x", 0.73)) * c.w)),
            int(round(c.y + float(sa.get("y", 0.29)) * c.h)),
            max(8, int(round(float(sa.get("w", 0.04)) * c.w))),
            max(8, int(round(float(sa.get("h", 0.37)) * c.h))),
        )

    @staticmethod
    def _search(c: PixelRect, area: PixelRect) -> PixelRect:
        pad_x = max(80, int(1.5 * area.w))
        pad_y = max(24, int(0.125 * area.h))
        return _cut(PixelRect(area.x - pad_x, area.y - pad_y, area.w + 2 * pad_x, area.h + 2 * pad_y), c)

    @staticmethod
    def _in_box(area: PixelRect, g) -> bool:
        w = max(4, int(g.ball_w))
        return (area.x - w <= g.ball_x <= area.x + area.w + w
                and area.y - w <= g.ball_y <= area.y + area.h + w)

    def look(self, near, wide: bool) -> Look:
        try:
            c = self._screen()
            if c is None or not bridge().captureReady():
                return Look(None, "", False)
            area = self._area_px(c)
            search = self._search(c, area)
            game, src = None, "area"
            if near is not None and self._roi is not None:
                r = self._roi
                if (search.x <= r.x and r.x + r.w <= search.x + search.w
                        and search.y <= r.y and r.y + r.h <= search.y + search.h):
                    game = self.scanner.find(self._grab(r.x, r.y, r.w, r.h), (r.x, r.y), near)
                    src = "roi"
                else:
                    self._roi = None
            if game is None:
                game = self.scanner.find(self._grab(search.x, search.y, search.w, search.h),
                                         (search.x, search.y), near)
                src = "area"
                if game is not None and not self._in_box(area, game) and (near is None or not game.has_zone):
                    game = None
            if game is None and wide:
                game = self.scanner.find(self._grab(c.x, c.y, c.w, c.h), (c.x, c.y), near)
                src = "wide"
            if game is not None:
                w = max(4, int(game.ball_w))
                left = max(search.x, int(game.ball_x - 3 * w))
                right = min(search.x + search.w, int(game.ball_x + 3 * w))
                if right > left:
                    self._roi = PixelRect(left, search.y, right - left, search.h)
            elif near is None:
                self._roi = None
            self._look_errs = 0
            now = time.perf_counter()
            dt = now - NOTE["t"]
            NOTE["t"] = now
            if 0 < dt < 2:
                NOTE["fps"] = 0.9 * NOTE["fps"] + 0.1 / dt
                self.hub.fps = NOTE["fps"]
            NOTE["text"] = ("нашла: " + src if game is not None else "") + (
                (" · зона есть" if game.has_zone else " · зоны нет") if game is not None else "") + \
                ((self.scanner.last or "") if game is None or not game.has_zone else "")
            return Look(game, src if game is not None else "", True)
        except Exception as exc:  # noqa: BLE001
            self._look_errs += 1
            now = time.monotonic()
            if now - self._err_logged > 10:
                self._err_logged = now
                self.hub.event("warn", f"Захват экрана: {type(exc).__name__}: {exc}")
            if self._look_errs >= 3:
                self._roi = None
                self._look_errs = 0
            return Look(None, "", False)

    def motion(self):
        try:
            arr = bridge().thumb(64, 36)
            if arr is None:
                return None
            a = _u8(arr)
            if a.size != 64 * 36:
                return None
            small = a.reshape(36, 64).astype(np.int16)
            prev, self._small = self._small, small
            return None if prev is None else float(np.abs(small - prev).mean())
        except Exception:  # noqa: BLE001
            return None

    def overlay(self, g):
        c = self._screen()
        if c is None or g is None:
            return None
        out = {"bx": (g.ball_x - c.x) / c.w, "by": (g.ball_y - c.y) / c.h,
               "bw": g.ball_w / c.w, "bh": g.ball_h / c.h}
        if g.has_zone:
            out.update({"zx0": (g.zone_x0 - c.x) / c.w, "zx1": (g.zone_x1 - c.x) / c.w,
                        "zt": (g.zone_top - c.y) / c.h, "zb": (g.zone_bot - c.y) / c.h})
        return out

    def adopt_area(self, samples) -> None:
        """Самокалибровка: миниигра найдена вне заданной зоны — запоминаем, где она на самом деле."""
        c = self._screen()
        if c is None or len(samples) < 20:
            return
        xs = sorted(s[0] for s in samples)
        cx = xs[len(xs) // 2]
        bw = sorted(s[4] for s in samples)[len(samples) // 2]
        ys = [s[1] for s in samples] + [s[2] for s in samples] + [s[3] for s in samples]
        old = self.cfg.get("scan_area") or {}
        w = max(float(old.get("w", 0.04)), 2.6 * bw / c.w)
        y0 = (min(ys) - 0.04 * c.h - c.y) / c.h
        y1 = (max(ys) + 0.04 * c.h - c.y) / c.h
        h = max(y1 - y0, 0.6 * float(old.get("h", 0.37)))
        if y1 - y0 < h:
            mid = (y0 + y1) / 2
            y0 = mid - h / 2
        x0 = (cx - c.x) / c.w - w / 2
        x0, y0 = min(max(0.0, x0), 1 - w), min(max(0.0, y0), 1 - h)
        if w > 0.25 or h > 0.9:
            return
        new = {"x": round(x0, 5), "y": round(y0, 5), "w": round(w, 5), "h": round(min(h, 1 - y0), 5)}
        self.cfg.update({"scan_area": new})
        self._roi = None
        self.hub.event("info", "Нашёл шкалу в другом месте — запомнил новую область")

    # ---- касания
    def _pt(self, name: str, dflt=None):
        p = self.cfg.get(name)
        if not isinstance(p, dict) or "x" not in p:
            if dflt is None:
                now = time.monotonic()
                if now - self._no_pt_logged > 15:
                    self._no_pt_logged = now
                    self.hub.event("warn", f"Не задана точка «{name}» — открой настройку телефона")
                return None
            p = dflt
        try:
            d = bridge().displaySize()
            return int(float(p["x"]) * d[0]), int(float(p["y"]) * d[1])
        except Exception:  # noqa: BLE001
            return None

    def click_cast(self) -> None:
        pt = self._pt("cast")
        if pt is None:
            return
        hold = max(0.05, self.cfg.adv("mouse_click_hold_sec"))
        bridge().tap(pt[0], pt[1], int(hold * 1000))
        self._sleep_abortable(self.cfg.adv("cast_settle_sec"))

    def tap_key(self, key: str, hold: float) -> None:
        """На телефоне «клавиша удочки» — слот на панели. Не задан — просто ничего не делаем."""
        pt = self._pt("rod")
        if pt is None:
            return
        bridge().tap(pt[0], pt[1], int(max(0.06, min(0.4, hold)) * 1000))

    def hold_collect_click(self, secs: float) -> None:
        pt = self._pt("collect")
        if pt is None:
            return
        global _held
        _held = False
        bridge().hold(pt[0], pt[1], True)
        try:
            self._sleep_abortable(secs)
        finally:
            bridge().hold(pt[0], pt[1], False)

    def find_collect(self, bans=()):
        """Белый ромб сбора на экране -> (x, y) в пикселях кадра или None."""
        try:
            sz = bridge().screenSize()
            W, H = int(sz[0]), int(sz[1])
            if W <= 0 or H <= 0:
                return None
            ow = 640
            oh = max(1, int(round(H * ow / W)))
            arr = bridge().scaled(ow, oh)
            if arr is None:
                return None
            cands = diamond.find_diamonds(_rgba_to_bgr(_u8(arr), ow, oh), 4)
        except Exception:  # noqa: BLE001
            return None
        k = W / float(ow)
        pts = [(cx * k, cy * (H / float(oh))) for cx, cy, _w, _h in cands]
        pts = [p for p in pts if not any(abs(p[0] - bx) < 50 and abs(p[1] - by) < 50 for bx, by in bans)]
        if not pts:
            return None
        ref = self._pt("collect", {"x": 0.5, "y": 0.4})
        if ref is not None:
            pts.sort(key=lambda p: (p[0] - ref[0]) ** 2 + (p[1] - ref[1]) ** 2)
        return pts[0]

    def hold_pixel(self, x: float, y: float, down: bool) -> None:
        global _held
        _held = False
        try:
            d = bridge().displaySize()
            s = bridge().screenSize()
            fx = d[0] / float(s[0]) if s[0] else 1.0
            fy = d[1] / float(s[1]) if s[1] else 1.0
        except Exception:  # noqa: BLE001
            fx = fy = 1.0
        bridge().hold(int(x * fx), int(y * fy), bool(down))

    def set_hold(self, down: bool) -> None:
        global _held
        down = bool(down)
        if down == _held:
            return
        pt = self._pt("cast")
        if pt is None:
            return
        _held = down
        bridge().hold(pt[0], pt[1], down)

    def release_all(self) -> None:
        release_all()


# ---------------------------------------------------------------- превью для панели
def preview_jpeg(cfg: Config, hub, max_w: int = 640) -> bytes | None:
    sz = bridge().screenSize()
    W, H = int(sz[0]), int(sz[1])
    if W <= 0 or H <= 0 or not bridge().captureReady():
        return None
    ow = min(max_w, W)
    oh = max(1, int(round(H * ow / W)))
    arr = bridge().scaled(ow, oh)
    if arr is None:
        return None
    frame = _rgba_to_bgr(_u8(arr), ow, oh)
    w, h = ow, oh
    th = max(2, w // 400)
    sa = cfg.get("scan_area") or {}
    x0, y0 = int(sa.get("x", 0) * w), int(sa.get("y", 0) * h)
    x1, y1 = x0 + int(sa.get("w", 0) * w), y0 + int(sa.get("h", 0) * h)
    cv2.rectangle(frame, (x0, y0), (x1, y1), (120, 255, 160), th)
    tr = hub.track
    if tr:
        bx, by = int(tr["bx"] * w), int(tr["by"] * h)
        r = max(4, int(tr.get("bw", 0.01) * w / 2))
        cv2.rectangle(frame, (bx - r, by - r), (bx + r, by + r), (255, 255, 255), th)
        if "zt" in tr:
            cv2.rectangle(frame, (int(tr["zx0"] * w), int(tr["zt"] * h)), (int(tr["zx1"] * w), int(tr["zb"] * h)),
                          (90, 255, 90), th)
    for name, col in (("cast", (200, 90, 255)), ("collect", (110, 242, 214)), ("rod", (110, 211, 255))):
        p = cfg.get(name)
        if isinstance(p, dict) and "x" in p:
            px, py = int(p["x"] * w), int(p["y"] * h)
            s = max(8, w // 70)
            cv2.circle(frame, (px, py), s, col, th)
            cv2.line(frame, (px - s, py), (px + s, py), col, th)
            cv2.line(frame, (px, py - s), (px, py + s), col, th)
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 66])
    return buf.tobytes() if ok else None
