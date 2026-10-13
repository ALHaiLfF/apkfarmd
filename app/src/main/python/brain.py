"""Мозг макроса — конечный автомат, который сверяется с реальностью на каждом шаге.

Принципы, из-за которых он не «путается»:
  1. Никаких слепых сценариев: каждое действие (бросок, достать удочку, сбор) заканчивается
     НАБЛЮДЕНИЕМ — появилась ли миниигра. Нет — значит что-то не так, идём по лестнице исправлений.
  2. Клавиша удочки — переключатель, и мы не знаем, в каком она положении. Поэтому лестница
     попыток чередует «просто бросить» и «переключить удочку + бросить», и за 4 попытки
     гарантированно перебирает оба положения. Рассинхрон невозможен по построению.
  3. Миниигра считается оконченной только когда шар не найден даже при поиске по ВСЕМУ окну
     дольше `end_grace_s`. Мерцание детектора больше не уводит нас в «сбор» посреди игры.
  4. Любое ожидание имеет таймаут, любой таймаут — следующий шаг. Исключения не убивают цикл:
     отпускаем все кнопки, ждём (с нарастающей паузой) и пробуем снова.
  5. Окно Roblox пропало / потеряло фокус — ждём и возвращаем, а не жмём клавиши в пустоту.
  6. Статичные ложные срабатывания (элемент интерфейса, похожий на шкалу) отсекаются по
     отсутствию движения и банятся.
Брейн работает только через интерфейс World, поэтому его можно целиком прогнать в симуляторе.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from config import Config


class Abort(Exception):
    """Остановка по команде (или поток заменён сторожем)."""


class Restart(Exception):
    """Начать цикл заново — не считается провалом (например, окно моргнуло)."""


@dataclass
class Look:
    game: object = None   # detect.Game | None
    src: str = ""         # "roi" | "area" | "wide"
    ok: bool = True       # удалось ли вообще получить кадр


# Лестница исправлений по числу подряд идущих провалов.
LADDER = (
    ("cast",),
    ("collect", "cast"),   # вдруг рыба так и осталась несобранной (сбор мог не сработать) — она блокирует новые забросы
    ("rod", "cast"),
    ("rod", "cast"),       # два раза подряд: перебираем оба положения переключателя «удочка»
    ("refocus", "cast"),
    ("collect", "cast"),
    ("rod", "cast"),
    ("rod", "cast"),
)


def same_game(a, b) -> bool:
    if not (a.has_zone and b.has_zone):
        return False
    w = max(4, a.ball_w)
    ha, hb = a.zone_bot - a.zone_top, b.zone_bot - b.zone_top
    return (abs(a.ball_x - b.ball_x) <= w
            and abs(a.zone_x - b.zone_x) <= w
            and abs(ha - hb) <= max(4, 0.3 * ha))


class Brain:
    def __init__(self, world, cfg: Config, hub, tracker, aborted) -> None:
        self.w = world
        self.cfg = cfg
        self.hub = hub
        self.tr = tracker
        self._aborted = aborted
        try:
            self.w.abort = aborted   # чтобы долгие удержания клавиш прерывались мгновенно
        except Exception:  # noqa: BLE001
            pass
        self.beat = time.monotonic()
        self.fail_streak = 0
        self.err_streak = 0
        self.bite_times: list[float] = []
        self.force_wide = False
        self.deep_flag: str | None = None
        t = self.w.now()
        self.last_deep = t
        self.last_catch_at = t
        self.last_upkeep = 0.0
        self.focus_fail = 0
        self.still_since: float | None = None
        self.bans: list[tuple[float, float]] = []
        self.bad_looks = 0
        self.dbans: list = []
        self.found_leftover = False
        self.last_left_check = 0.0

    # ------------------------------------------------------------------ каркас
    def v(self, key: str) -> float:
        return self.cfg.adv(key)

    def guard(self) -> None:
        if self._aborted():
            raise Abort()
        self.beat = time.monotonic()

    def sleep(self, seconds: float) -> None:
        end = self.w.now() + max(0.0, seconds)
        while True:
            self.guard()
            left = end - self.w.now()
            if left <= 0:
                return
            self.w.sleep(min(0.05, left))

    def phase(self, name: str, text: str | None = None) -> None:
        self.hub.set_phase(name, text)

    # ------------------------------------------------------------------ окно / фокус
    def ensure_window(self) -> None:
        """Блокируется, пока окно Roblox не появится И не окажется на переднем плане."""
        announced = False
        tries = 0
        while True:
            self.guard()
            if self.w.window_ok():
                self.hub.window_ok = True
                if self.w.is_foreground():
                    self.focus_fail = 0
                    return
                if self.w.focus():
                    self.focus_fail = 0
                    return
                self.focus_fail += 1
                tries += 1
                if tries % 3 == 0:
                    # Windows иногда не отдаёт фокус программно; клик в окно всегда активирует его.
                    self.hub.event("warn", "Не удалось вывести Roblox вперёд — активирую кликом")
                    self.w.click_cast()
                self.phase("paused", "Не могу вывести Roblox вперёд, пробую ещё")
                self.sleep(1.0)
                continue
            self.hub.window_ok = False
            if not announced:
                self.hub.event("warn", getattr(self.w, "missing_msg", "Окно Roblox не найдено — жду"))
                announced = True
            self.phase("paused")
            self.w.focus()  # вдруг оно просто свёрнуто
            self.sleep(1.5)

    def refocus(self) -> None:
        self.w.set_hold(False)
        ok = self.w.focus()
        self.hub.event("info" if ok else "warn", "Вернул фокус Roblox" if ok else "Фокус вернуть не удалось")

    def upkeep(self, waiting: bool = False) -> None:
        """Раз в секунду: окно живо? фокус на месте? курсор в окне? картинка не заморожена?"""
        now = self.w.now()
        if now - self.last_upkeep < 1.0:
            return
        self.last_upkeep = now
        if not self.w.window_ok():
            self.w.set_hold(False)
            raise Restart("окно пропало")
        if not self.w.is_foreground():
            self.hub.event("warn", "Roblox потерял фокус — возвращаю")
            self.refocus()
        if not self.w.cursor_ok():
            self.w.park_cursor()
        if waiting:
            m = self.w.motion()
            if m is not None:
                if m < 0.12:
                    if self.still_since is None:
                        self.still_since = now
                    elif (now - self.still_since > self.v("frozen_s")
                          and now - self.last_deep > self.v("frozen_s")):
                        self.deep_flag = "картинка не меняется (игра зависла?)"
                else:
                    self.still_since = None

    # ------------------------------------------------------------------ действия
    def cast(self) -> None:
        self.phase("cast")
        self.ensure_window()
        self.w.click_cast()
        self.sleep(self.v("cast_after_sec"))

    def press_rod(self) -> None:
        key = str(self.cfg.get("rod_key") or "").strip()
        if not key:
            return
        self.phase("cast", "Достаю/убираю удочку")
        self.ensure_window()
        self.w.tap_key(key, self.v("key_hold_sec"))
        self.sleep(0.7)

    def collect(self) -> None:
        self.phase("collect")
        self.ensure_window()
        hold = self.v("collect_hold_sec")
        fc = getattr(self.w, "find_collect", None)
        if self.cfg.get("collect_mode") == "click" and fc is not None and self.cfg.get("visual_collect", True):
            self.collect_visual(fc, hold)
        elif self.cfg.get("collect_mode") == "click":
            self.w.hold_collect_click(hold)
        else:
            self.w.tap_key("t", hold)
        self.sleep(self.v("after_collect_sec"))

    # ---- сбор по глазам: видим ромб — держим, пока не исчезнет; не исчез/сместился — берём заново
    def _diamond(self, fc, wait: float):
        """Ждём появления ромба до wait секунд (подтверждение — 2 кадра подряд рядом)."""
        end = self.w.now() + wait
        prev = None
        while True:
            self.guard()
            p = fc(self.dbans)
            if p is not None:
                if prev is not None and abs(p[0] - prev[0]) < 60 and abs(p[1] - prev[1]) < 60:
                    return p
                prev = p
            else:
                prev = None
            if self.w.now() >= end:
                return None
            self.sleep(0.08)

    def collect_visual(self, fc, hold: float) -> None:
        seen = False
        last = None
        for attempt in range(5):
            p = self._diamond(fc, 4.0 if not seen else 1.2)
            if p is None:
                if not seen:
                    self.hub.event("info", "Ромб сбора не вижу — жму в сохранённую точку")
                    self.w.hold_collect_click(hold)
                return   # видели и пропал — значит собрано
            seen, last = True, p
            t0 = self.w.now()
            gone = far = None
            self.w.hold_pixel(p[0], p[1], True)
            try:
                while self.w.now() - t0 < hold + 1.0:
                    self.guard()
                    self.sleep(0.12)
                    now = self.w.now()
                    q = fc(self.dbans)
                    if q is None:
                        gone = gone or now
                        if now - gone > 0.5 and now - t0 > 0.3:
                            break
                    else:
                        gone = None
                        if abs(q[0] - p[0]) > 90 or abs(q[1] - p[1]) > 90:
                            far = far or now                 # игра отодвинула кнопку — палец уже мимо
                            if now - far > 0.4:
                                break
                        else:
                            far = None
            finally:
                self.w.hold_pixel(p[0], p[1], False)
            self.sleep(0.25)
            if attempt >= 1:
                self.hub.event("info", f"Сбор не прошёл с первого раза, пробую снова ({attempt + 1})")
        if last is not None:
            self.dbans.append(last)
            self.dbans = self.dbans[-6:]
            self.hub.event("warn", "Ромб не исчезает после 5 попыток — считаю его ложным и игнорирую")

    def leftover(self) -> bool:
        """Есть ли на экране несобранный ромб (рыба осталась)."""
        fc = getattr(self.w, "find_collect", None)
        if fc is None or self.cfg.get("collect_mode") != "click" or not self.cfg.get("visual_collect", True):
            return False
        return self._diamond(fc, 0.3) is not None

    def bite_timeout(self) -> float:
        base = self.v("wait_minigame_start_sec")
        recent = sorted(self.bite_times[-10:])
        if len(recent) >= 3:
            p90 = recent[min(len(recent) - 1, int(len(recent) * 0.9))]
            base = max(base, p90 * 1.5 + 3.0)
        return min(base, 40.0)

    def _banned(self, g) -> bool:
        return any(abs(g.ball_x - bx) < 14 and abs(g.ball_y - by) < 14 for bx, by in self.bans)

    # ------------------------------------------------------------------ ожидание поклёвки
    def wait_for_minigame(self, deadline: float):
        """Ждём миниигру до deadline. Возвращает (Game, src) или None."""
        self.phase("wait")
        need = max(2, int(round(self.v("start_confirm_frames"))))
        idle_dt = 1.0 / 15.0
        fps_dt = 1.0 / max(5.0, self.v("task_fps"))
        hits, n, last = 0, 0, None
        ys: list[float] = []
        last_hit = 0.0
        stale = 0.8   # столько секунд подтверждение живёт без новых попаданий (широкий поиск идёт не каждый кадр)
        while self.w.now() < deadline:
            self.guard()
            t0 = self.w.now()
            self.upkeep(waiting=True)
            if self.deep_flag:
                return None
            if t0 - self.last_left_check > 2.0 and hits == 0:
                self.last_left_check = t0
                if self.leftover():
                    self.found_leftover = True
                    return None
            look = self.w.look(None, self.force_wide or n % 3 == 2)
            n += 1
            if not look.ok:
                self.bad_looks += 1
                if self.bad_looks >= 10:
                    self.bad_looks = 0
                    self.ensure_window()
                    raise Restart("кадр не получен")
            else:
                self.bad_looks = 0
            g = look.game
            if g is not None and look.src == "wide" and self._banned(g):
                g = None
            valid = g is not None and g.has_zone
            if valid and (last is None or same_game(g, last)):
                hits += 1
                last_hit = t0
                ys.append(g.ball_y + (g.zone_y or 0))
                if look.src == "wide":
                    moved = (max(ys) - min(ys)) >= 3
                    if hits >= 2 * need and moved:
                        return g, look.src
                    if hits >= 2 * need + 10 and not moved:
                        self.bans.append((g.ball_x, g.ball_y))
                        self.hub.event("info", "Отсёк статичный ложный объект")
                        hits, ys, last = 0, [], None
                        g = None
                elif hits >= need:
                    return g, look.src
            elif valid:
                hits, last_hit = 1, t0          # другое место/размер — начинаем подтверждение заново
                ys = [g.ball_y + (g.zone_y or 0)]
            elif t0 - last_hit > stale:
                hits, ys, last = 0, [], None    # давно не видели — забываем
            if valid:
                last = g
            dt = fps_dt if hits else idle_dt
            used = self.w.now() - t0
            if dt > used:
                self.w.sleep(dt - used)
        return None

    # ------------------------------------------------------------------ миниигра
    def play(self, g0, src: str) -> str:
        """Возвращает: 'done' | 'timeout' | 'noise' | 'window'."""
        self.phase("fight")
        adv = self.cfg.advanced_all()
        self.tr.configure(adv)
        t_begin = self.w.now()
        self.tr.start(g0.ball_y, g0.zone_y, g0.ball_h, t_begin)
        near = (g0.ball_x, g0.ball_y)
        last_seen = t_begin
        grace = max(self.v("end_grace_s"), self.v("lost_timeout_s"))
        max_s = self.v("max_minigame_s")
        min_s = self.v("min_minigame_s")
        fps_dt = 1.0 / max(5.0, self.v("task_fps"))
        samples: list[tuple] = []
        result = "done"
        try:
            while True:
                self.guard()
                t0 = self.w.now()
                self.upkeep()
                lost = t0 - last_seen
                look = self.w.look(near, lost > 0.25)
                now = self.w.now()
                g = look.game
                if not look.ok and not self.w.window_ok():
                    result = "window"
                    break
                if g is not None:
                    last_seen = now
                    near = (g.ball_x, g.ball_y)
                    self.tr.observe(g.ball_y, g.ball_h, g.zone_top, g.zone_y, now)
                    self.w.set_hold(bool(self.tr.decide(now)))
                    if g.has_zone:
                        samples.append((g.ball_x, g.ball_y, g.zone_top, g.zone_bot, g.ball_w))
                    self.hub.track = self.w.overlay(g)
                else:
                    lost = now - last_seen
                    if lost > 0.3:
                        self.w.set_hold(False)
                    if lost > grace:
                        break
                if now - t_begin > max_s:
                    result = "timeout"
                    self.hub.event("warn", "Миниигра длится слишком долго — иду дальше")
                    break
                used = self.w.now() - t0
                if fps_dt > used:
                    self.w.sleep(fps_dt - used)
        finally:
            self.w.set_hold(False)
            self.hub.track = None
        dur = self.w.now() - t_begin
        if result == "done" and dur < min_s + grace:
            return "noise"
        if result in ("done", "timeout") and src == "wide" and len(samples) > 20:
            self.w.adopt_area(samples)
        return result

    # ------------------------------------------------------------------ одна попытка (бросок + ожидание + игра)
    def attempt(self, steps) -> bool:
        for s in steps:
            self.guard()
            if s == "rod":
                self.press_rod()
            elif s == "refocus":
                self.refocus()
                self.sleep(0.3)
            elif s == "collect":
                self.collect()
            elif s == "cast":
                self.cast()
        t_cast = self.w.now()
        deadline = t_cast + self.bite_timeout()
        noise = 0
        while True:
            found = self.wait_for_minigame(deadline)
            if found is None:
                return False
            g, src = found
            t_found = self.w.now()
            res = self.play(g, src)
            if res == "noise":
                noise += 1
                if noise >= 3:
                    self.force_wide = True
                deadline = max(deadline, self.w.now() + 6.0)
                continue
            if res == "window":
                raise Restart("окно пропало во время игры")
            self.bite_times.append(t_found - t_cast)
            self.bite_times = self.bite_times[-30:]
            return True

    # ------------------------------------------------------------------ восстановление
    def deep_recover(self, why: str) -> None:
        self.hub.recovery(f"Глубокое восстановление: {why}")
        self.phase("recover")
        self.w.release_all()
        self.ensure_window()
        self.force_wide = True
        self.still_since = None
        self.deep_flag = None
        self.sleep(1.5)
        self.last_deep = self.w.now()

    def deep_needed(self) -> str | None:
        if self.deep_flag:
            return self.deep_flag
        now = self.w.now()
        idle = now - max(self.last_catch_at, self.last_deep)
        if idle > self.v("idle_catch_s"):
            return f"{int(idle)} с без улова"
        if self.fail_streak >= 8 and self.fail_streak % 4 == 0:
            return f"{self.fail_streak} провалов подряд"
        if self.err_streak >= 4:
            return "ошибки подряд"
        return None

    # ------------------------------------------------------------------ цикл
    def cycle(self) -> None:
        self.phase("prepare")
        self.ensure_window()
        self.w.release_all()
        why = self.deep_needed()
        if why:
            self.deep_recover(why)
            if self.fail_streak % 4 == 0:
                self.fail_streak += 1  # не зацикливаться на одном и том же триггере
        if self.fail_streak >= 12:
            self.hub.event("warn", f"Долго не получается ({self.fail_streak}). Передохну 20 с и продолжу")
            self.phase("recover", "Что-то идёт не так, делаю паузу и пробую снова")
            self.sleep(20.0)
        if (self.fail_streak > 0 or self.last_catch_at == self.last_deep) and self.leftover():
            self.hub.event("info", "На экране несобранная рыба — собираю")
            self.collect()
        steps = LADDER[self.fail_streak % len(LADDER)]
        if self.attempt(steps):
            self.fail_streak = 0
            self.err_streak = 0
            self.force_wide = False
            self.last_catch_at = self.w.now()
            self.hub.catch()
            self.phase("settle")
            self.sleep(self.v("after_minigame_sec"))
            self.collect()
        elif self.found_leftover:
            self.found_leftover = False
            self.hub.event("info", "Нашла несобранную рыбу — собираю и бросаю заново")
            self.collect()
        else:
            self.fail_streak += 1
            self.hub.set_fail(self.fail_streak)
            self.hub.event("warn", f"Поклёвки нет (попытка {self.fail_streak}): {' + '.join(steps)}")

    def run(self) -> None:
        self.w.open()
        try:
            while True:
                self.guard()
                try:
                    self.cycle()
                except Abort:
                    raise
                except Restart as r:
                    self.hub.event("info", f"Перезапуск цикла: {r}")
                    self.w.release_all()
                except Exception as exc:  # noqa: BLE001 — цикл обязан пережить всё
                    self.err_streak += 1
                    self.hub.errors += 1
                    self.hub.event("error", f"Ошибка: {type(exc).__name__}: {exc}")
                    try:
                        self.w.release_all()
                    except Exception:  # noqa: BLE001
                        pass
                    self.sleep(min(15.0, 0.5 * (2 ** min(self.err_streak, 5))))
        except Abort:
            pass
        finally:
            try:
                self.w.release_all()
            finally:
                self.w.close()
