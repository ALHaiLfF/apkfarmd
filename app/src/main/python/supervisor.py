"""Сторож: запускает рабочий поток и следит, чтобы тот не завис и не умер."""
from __future__ import annotations

import threading
import time
import traceback

from brain import Brain
from config import Config
from track_control import TrackController


class Supervisor:
    def __init__(self, cfg: Config, hub, world_factory, release) -> None:
        self.cfg = cfg
        self.hub = hub
        self.world_factory = world_factory
        self.release = release
        self._lock = threading.RLock()
        self._gen = 0
        self._running = False
        self._brain: Brain | None = None
        self._thread: threading.Thread | None = None
        self._quit = threading.Event()
        self._warned_stall = False
        self._respawn_at = 0.0
        self._respawns = 0
        threading.Thread(target=self._watchdog, name="watchdog", daemon=True).start()

    # ---- управление
    @property
    def running(self) -> bool:
        return self._running

    def start(self) -> bool:
        with self._lock:
            if self._running:
                return False
            self._running = True
            self._respawns = 0
            self.hub.begin_run()
            self._spawn()
            return True

    def stop(self) -> None:
        with self._lock:
            if not self._running:
                return
            self._running = False
            self._gen += 1          # старый поток увидит это в guard() и выйдет
            th = self._thread
        try:
            self.release()
        except Exception:
            pass
        if th is not None and th.is_alive() and th is not threading.current_thread():
            th.join(timeout=2.0)
        try:
            self.release()
        except Exception:
            pass
        self.hub.end_run()

    def toggle(self) -> bool:
        if self._running:
            self.stop()
            return False
        return self.start()

    def shutdown(self) -> None:
        self._quit.set()
        self.stop()

    # ---- рабочий поток
    def _spawn(self) -> None:
        with self._lock:
            self._gen += 1
            gen = self._gen
            self._warned_stall = False
            th = threading.Thread(target=self._worker, args=(gen,), name=f"fisher-{gen}", daemon=True)
            self._thread = th
            th.start()

    def _worker(self, gen: int) -> None:
        def aborted() -> bool:
            return (not self._running) or gen != self._gen or self._quit.is_set()

        try:
            world = self.world_factory(self.cfg, self.hub)
            brain = Brain(world, self.cfg, self.hub, TrackController(), aborted)
            self._brain = brain
            brain.run()
        except Exception as exc:  # noqa: BLE001
            self.hub.event("error", f"Рабочий поток упал: {type(exc).__name__}: {exc}")
            try:
                with open("anime-fishing-error.log", "a", encoding="utf-8") as f:
                    f.write(time.strftime("%F %T") + "\n" + traceback.format_exc() + "\n")
            except OSError:
                pass

    # ---- сторож
    def _watchdog(self) -> None:
        while not self._quit.wait(1.0):
            try:
                self._tick()
            except Exception:  # noqa: BLE001
                pass

    def _tick(self) -> None:
        if not self._running:
            return
        now = time.monotonic()
        th, brain = self._thread, self._brain
        if th is None or not th.is_alive():
            if now >= self._respawn_at:
                self._respawns += 1
                self._respawn_at = now + min(30.0, 2.0 * self._respawns)
                self.hub.recovery("Рабочий поток остановился — запускаю заново")
                self._spawn()
            return
        if brain is None:
            return
        stall = now - brain.beat
        if stall > self.cfg.adv("stall_warn_s") and not self._warned_stall:
            self._warned_stall = True
            self.hub.event("warn", f"Сторож: нет активности {int(stall)} с — отпускаю кнопки")
            try:
                self.release()
            except Exception:
                pass
        if stall > self.cfg.adv("stall_kill_s"):
            self.hub.recovery(f"Сторож: поток завис на {int(stall)} с — перезапускаю")
            try:
                self.release()
            except Exception:
                pass
            self._spawn()
        elif stall < 2.0:
            self._warned_stall = False
            if self._respawns and now - self._respawn_at > 120:
                self._respawns = 0
