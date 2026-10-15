"""Самопроверка логики: симулятор мира со случайными сбоями.

Запуск:  python tools/selftest.py            (быстрый)
         python tools/selftest.py --hours 6  (дольше)

Проверяет, что мозг макроса не застревает, не ломается и продолжает ловить
при: удочке в неизвестном положении, потере фокуса, пропавшем окне, мерцающем
детекторе, ложных срабатываниях, «пустых» забросах и ошибках ввода.
"""
from __future__ import annotations

import argparse
import math
import os
import random
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "app", "src", "main", "python"))

from brain import Brain, Look  # noqa: E402
from config import Config  # noqa: E402
from detect import Game  # noqa: E402
from hub import Hub  # noqa: E402
from track_control import TrackController  # noqa: E402


class SimWorld:
    """Виртуальное время. Игра: удочка(переключатель) -> бросок -> поклёвка -> миниигра -> сбор."""

    BAR_TOP, BAR_BOT, BAR_X = 300.0, 700.0, 1400.0
    ACC, BALL, ZH = 900.0, 24, 27.0     # ускорение шара, его размер и половина зоны (px)

    def __init__(self, seed: int, chaos: float = 1.0, rod_equipped: bool | None = None) -> None:
        self.rng = random.Random(seed)
        self.chaos = chaos
        self.t = 0.0
        self.rod = self.rng.random() < 0.5 if rod_equipped is None else rod_equipped
        self.state = "idle"          # idle | line | game | ready
        self.bite_at = math.inf
        self.window_up = True
        self.window_back_at = 0.0
        self.next_outage = self.rng.expovariate(1 / 900.0) if chaos else math.inf
        self.fg = True
        self.next_steal = self.rng.expovariate(1 / 150.0) if chaos else math.inf
        self.hold = False
        self.keys_down = 0
        self.y = 600.0
        self.v = 0.0
        self.progress = 0.0
        self.game_t0 = 0.0
        self.dropout_until = 0.0
        self.noise_until = 0.0
        self.static_fp = chaos > 0       # статичный «ложный объект» на экране
        self.area_wrong = chaos > 0 and seed % 2 == 0  # шкала стоит не там, где в конфиге
        self.adopted = 0
        self.true_catches = 0
        self.catch_times: list[float] = []
        self.opened = False
        self.max_hold_run = 0.0
        self._hold_since: float | None = None
        self.input_errors = 0

    # ---- время
    def now(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self._advance(self.t + max(0.0, s))

    def _advance(self, t_to: float) -> None:
        while t_to - self.t > 1e-9:
            dt = min(0.01, t_to - self.t)
            self.t += dt
            self._step(dt)
        self.t = max(self.t, t_to)

    def _step(self, dt: float) -> None:
        t = self.t
        if self.window_up and t >= self.next_outage:
            self.window_up = False
            self.window_back_at = t + self.rng.uniform(5, 30)
            self.next_outage = math.inf
        if not self.window_up and t >= self.window_back_at:
            self.window_up = True
            self.fg = False
            self.next_outage = t + self.rng.expovariate(1 / 900.0) if self.chaos else math.inf
        if t >= self.next_steal:
            self.fg = False
            self.next_steal = t + self.rng.expovariate(1 / 150.0)
        if self.state == "line" and t >= self.bite_at:
            self.state = "game"
            self.game_t0 = t
            self.progress = 0.0
            self.y, self.v = 600.0, 0.0
        if self.state == "game":
            held = self.hold and self.fg and self.window_up
            a = -self.ACC if held else self.ACC
            self.v += a * dt
            self.y += self.v * dt
            lo, hi = self.BAR_TOP + self.BALL / 2, self.BAR_BOT - self.BALL / 2
            if self.y < lo:
                self.y, self.v = lo, 0.0
            if self.y > hi:
                self.y, self.v = hi, 0.0
            inzone = abs(self.y - self.zone_c(t)) <= self.ZH
            self.game_total = getattr(self, 'game_total', 0.0) + dt
            self.inzone_total = getattr(self, 'inzone_total', 0.0) + (dt if inzone else 0.0)
            self.progress = max(0.0, self.progress + (1.0 if inzone else -0.7) * dt)
            if self.progress >= 4.0 or t - self.game_t0 >= 20.0:
                self.state = "ready"
            if self.rng.random() < 0.03 * self.chaos * dt:
                self.dropout_until = t + self.rng.uniform(0.2, 0.7)
        if self.hold and self.fg and self.window_up:
            if self._hold_since is None:
                self._hold_since = t
            self.max_hold_run = max(self.max_hold_run, t - self._hold_since)
        else:
            self._hold_since = None
        if self.state == "line" and self.rng.random() < 0.04 * self.chaos * dt:
            self.noise_until = t + 0.5

    def zone_c(self, t: float) -> float:
        span = self.BAR_BOT - self.BAR_TOP
        return (self.BAR_TOP + self.BAR_BOT) / 2 + 0.275 * span * math.sin(0.8 * t) + 0.0875 * span * math.sin(2.1 * t)

    # ---- окно/фокус
    def open(self) -> None:
        self.opened = True

    def close(self) -> None:
        self.opened = False

    def window_ok(self) -> bool:
        return self.window_up

    def is_foreground(self) -> bool:
        return self.window_up and self.fg

    def focus(self) -> bool:
        self.sleep(0.2)
        if self.window_up and self.rng.random() < 0.7:
            self.fg = True
        return self.is_foreground()

    def cursor_ok(self) -> bool:
        return True

    def park_cursor(self) -> None:
        pass

    # ---- зрение
    def look(self, near, wide: bool) -> Look:
        self.sleep(0.006)
        if not self.window_up:
            return Look(None, "", False)
        if self.rng.random() < 0.004 * self.chaos:
            return Look(None, "", False)   # редкий сбой захвата
        game = None
        src = "area"
        if self.state == "game" and self.t >= self.dropout_until and self.rng.random() > 0.04 * self.chaos:
            if self.area_wrong and not wide:
                game = None
            else:
                zc = self.zone_c(self.t)
                game = Game(self.BAR_X, self.y, self.BALL, self.BALL, int(self.BAR_X - 30), int(self.BAR_X + 30),
                            int(zc - self.ZH), int(zc + self.ZH))
                src = "wide" if self.area_wrong else "area"
        elif self.state == "line" and self.t < self.noise_until and (not self.area_wrong or wide):
            y = 400 + 60 * math.sin(7 * self.t)
            game = Game(1380, y, 24, 24, 1350, 1410, int(y - 20), int(y + 20))
            src = "wide" if self.area_wrong else "area"
        elif self.static_fp and wide:
            game = Game(900, 250, 24, 24, 870, 930, 230, 270)
            src = "wide"
        if game is not None and near is not None:
            # как у настоящего детектора: при поиске «около шара» далёкие кандидаты отбрасываются
            if abs(game.ball_x - near[0]) > 72 or abs(game.ball_y - near[1]) > 288:
                game = None
        return Look(game, src, True)

    def motion(self) -> float | None:
        return 3.0

    # ---- действия
    def _need_fg(self) -> bool:
        return self.window_up and self.fg

    def click_cast(self) -> None:
        self.sleep(0.15)
        if self._need_fg() and self.rod and self.state in ("idle", "line"):
            self.state = "line"
            never = self.rng.random() < 0.12 * max(self.chaos, 0.2)
            self.bite_at = math.inf if never else self.t + self.rng.uniform(3, 16)

    def tap_key(self, key: str, hold: float) -> None:
        if self.chaos and self.rng.random() < 0.002:
            self.input_errors += 1
            raise OSError("sim: SendInput failed")
        self.keys_down += 1
        self.sleep(hold)
        self.keys_down -= 1
        if not self._need_fg():
            return
        if key.lower() == "t":
            if self.state == "ready" and hold >= 2.5:
                self.state = "idle"
                self.true_catches += 1
                self.catch_times.append(self.t)
        else:
            self.rod = not self.rod
            if not self.rod and self.state == "line":
                self.state = "idle"

    def hold_collect_click(self, secs: float) -> None:
        self.tap_key("t", secs)

    def set_hold(self, down: bool) -> None:
        self.hold = bool(down)

    def release_all(self) -> None:
        self.hold = False
        self.keys_down = 0

    def overlay(self, g):
        return None

    def adopt_area(self, samples) -> None:
        self.adopted += 1
        self.area_wrong = False


def run_case(seed: int, hours: float, chaos: float, rod_equipped: bool | None = None):
    w = SimWorld(seed, chaos, rod_equipped)
    t_end = hours * 3600.0
    cfg = Config.__new__(Config)
    cfg.lock = threading.RLock()
    import copy
    from config import DEFAULTS
    cfg.data = copy.deepcopy(DEFAULTS)
    cfg.path = None
    cfg.save = lambda: None
    hub = Hub()
    hub.begin_run()
    brain = Brain(w, cfg, hub, TrackController(), lambda: w.now() >= t_end)
    brain.run()
    gaps = [b - a for a, b in zip([0.0] + w.catch_times, w.catch_times + [t_end])]
    return {
        "seed": seed, "chaos": chaos, "catches": w.true_catches, "hub": hub.catches,
        "per_hour": w.true_catches / hours, "max_gap": max(gaps) if gaps else t_end,
        "recoveries": hub.recoveries, "errors": hub.errors,
        "hold_after": w.hold, "keys_after": w.keys_down, "adopted": w.adopted,
        "max_hold_run": w.max_hold_run, "input_errors": w.input_errors,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=2.0)
    ap.add_argument("--seeds", type=int, default=6)
    args = ap.parse_args()
    bad = 0
    print(f"{'seed':>4} {'chaos':>5} {'улов':>5} {'/час':>6} {'макс.пауза,с':>12} {'восст.':>6} {'ошиб.':>5}  итог")
    for chaos in (0.0, 1.0, 3.0):
        for seed in range(args.seeds):
            r = run_case(seed, args.hours, chaos, rod_equipped=(False if seed % 3 == 0 else None))
            floor = 120 if chaos <= 1 else 60
            ok = (r["per_hour"] >= floor and r["max_gap"] <= 600 and not r["hold_after"]
                  and r["keys_after"] == 0 and r["max_hold_run"] < 50)
            bad += (not ok)
            print(f"{r['seed']:>4} {r['chaos']:>5} {r['catches']:>5} {r['per_hour']:>6.0f} {r['max_gap']:>12.0f} "
                  f"{r['recoveries']:>6} {r['errors']:>5}  {'OK' if ok else 'ПРОВАЛ'}")
    print("\nВсе сценарии прошли" if not bad else f"\nПровалов: {bad}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
