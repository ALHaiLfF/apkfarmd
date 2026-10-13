"""Общее состояние: его пишут мозг и сторож, читает веб-панель."""
from __future__ import annotations

import threading
import time
from collections import deque

PHASES = {
    "idle":    ("待機", "Отдыхаю. Нажми СТАРТ, и пойдём рыбачить"),
    "prepare": ("準備", "Проверяю окно и готовлюсь"),
    "cast":    ("投げ", "Забрасываю удочку"),
    "wait":    ("待ち", "Жду поклёвку"),
    "fight":   ("戦い", "Миниигра! Держу зону"),
    "settle":  ("間",   "Миниигра окончена"),
    "collect": ("回収", "Собираю рыбу"),
    "recover": ("復旧", "Самовосстановление"),
    "paused":  ("休止", "Жду окно Roblox"),
}


class Hub:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.running = False
        self.phase = "idle"
        self.status = PHASES["idle"][1]
        self.catches = 0
        self.recoveries = 0
        self.fail_streak = 0
        self.errors = 0
        self.started_at = 0.0
        self.last_catch_at = 0.0
        self.window_ok = False
        self.fps = 0.0
        self.track = None  # доли клиентской области: ball/zone для превью
        self.catch_times: deque[float] = deque(maxlen=5000)
        self.log: deque[dict] = deque(maxlen=150)
        self.area_note = ""
        self.seq = 0

    # ---- запись
    def event(self, kind: str, msg: str) -> None:
        with self.lock:
            self.seq += 1
            self.log.append({"t": time.time(), "k": kind, "m": msg, "n": self.seq})

    def set_phase(self, name: str, text: str | None = None) -> None:
        with self.lock:
            self.phase = name
            self.status = text or PHASES.get(name, ("", name))[1]

    def catch(self) -> None:
        with self.lock:
            self.catches += 1
            self.last_catch_at = time.time()
            self.catch_times.append(self.last_catch_at)
            self.fail_streak = 0
        self.event("catch", f"Улов №{self.catches}")

    def recovery(self, why: str) -> None:
        with self.lock:
            self.recoveries += 1
        self.event("recover", why)

    def set_fail(self, n: int) -> None:
        with self.lock:
            self.fail_streak = n

    def begin_run(self) -> None:
        with self.lock:
            self.running = True
            self.started_at = time.time()
            self.last_catch_at = self.started_at
            self.fail_streak = 0
            self.phase = "prepare"
            self.status = PHASES["prepare"][1]
        self.event("info", "Старт")

    def end_run(self) -> None:
        with self.lock:
            self.running = False
            self.phase = "idle"
            self.status = PHASES["idle"][1]
            self.track = None
        self.event("info", "Стоп")

    # ---- чтение
    def health(self) -> int:
        """0..100 для полоски «HP»: падает при подряд идущих провалах, растёт с уловом."""
        with self.lock:
            if not self.running:
                return 100
            hp = 100 - self.fail_streak * 12
            if time.time() - self.last_catch_at > 180:
                hp -= 25
            return max(5, min(100, hp))

    def snapshot(self, since_n: int = 0) -> dict:
        now = time.time()
        with self.lock:
            el = (now - self.started_at) if self.running else 0.0
            per_hour = (self.catches / el * 3600.0) if el > 60 else 0.0
            recent = sum(1 for t in self.catch_times if now - t <= 600)
            kana = PHASES.get(self.phase, ("", ""))[0]
            return {
                "running": self.running,
                "phase": self.phase,
                "kana": kana,
                "status": self.status,
                "catches": self.catches,
                "per_hour": round(per_hour, 1),
                "last10": recent,
                "uptime": int(el),
                "recoveries": self.recoveries,
                "fail_streak": self.fail_streak,
                "health": self.health(),
                "window_ok": self.window_ok,
                "fps": round(self.fps, 1),
                "since_catch": int(now - self.last_catch_at) if self.running else 0,
                "track": self.track,
                "log": [e for e in self.log if e["n"] > since_n][-60:],
                "seq": self.seq,
                "now": now,
            }
