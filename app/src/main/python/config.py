"""Настройки. Всё, что можно определить автоматически, определяется само;
старые значения (удочка, точка заброса, зона шкалы, цвета) подтягиваются
из config.json старого макроса при первом запуске."""
from __future__ import annotations

import copy
import json
import os
import secrets
import threading
from pathlib import Path

from advanced_settings import DEFAULT_ADVANCED

ROOT = Path(os.environ.get("FISH_HOME") or Path(__file__).resolve().parent.parent)
CFG_PATH = ROOT / "config.json"

# Параметры «самолечения». Менять не нужно — они здесь, чтобы было что подкрутить при желании.
AUTO_DEFAULTS = {
    "end_grace_s": 1.0,        # сколько шар должен отсутствовать (при полном пересканировании), чтобы миниигра считалась оконченной
    "min_minigame_s": 1.2,     # короче — это шум/ложное срабатывание, а не поклёвка
    "max_minigame_s": 45.0,    # жёсткий потолок миниигры
    "frozen_s": 90.0,          # столько секунд неподвижной картинки = «завис»
    "idle_catch_s": 300.0,     # столько секунд без улова = глубокое восстановление
    "stall_warn_s": 20.0,      # сторож: рабочий поток молчит -> отпустить кнопки
    "stall_kill_s": 60.0,      # сторож: рабочий поток молчит -> перезапустить
}

DEFAULTS: dict = {
    "rod_key": "5",
    "cast": {"x": 0.5640625, "y": 0.2633333},
    "collect": {"x": 0.51015625, "y": 0.4027777},
    "collect_mode": "t",            # "t" — держать T, "click" — держать ЛКМ в точке collect
    "visual_collect": True,         # собирать по ромбу на экране (телефон)
    "rod": None,                    # точка слота удочки (телефон)
    "platform": "",
    "scan_area": {"x": 0.7317708, "y": 0.2925, "w": 0.0385417, "h": 0.3766667},
    "bar_colors": None,
    "hotkeys": {"toggle": "F1", "exit": "F4"},
    "window_hint": "",              # подстрока заголовка окна (для эмулятора); пусто = Roblox
    "autostart": False,
    "web": {"port": 8765, "token": ""},
    "advanced": {},
    "auto": {},
}


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _legacy_paths() -> list[Path]:
    found = []
    if os.environ.get("FISH_HOME"):
        return found
    parent = ROOT.parent
    try:
        for d in sorted(parent.iterdir()):
            p = d / "config.json"
            if d.is_dir() and d.resolve() != ROOT.resolve() and p.is_file():
                found.append(p)
    except OSError:
        pass
    return found


def _import_legacy() -> dict:
    for p in _legacy_paths():
        try:
            old = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(old, dict) or "scan_area" not in old:
            continue
        out: dict = {}
        pts = old.get("points") or {}
        if isinstance(pts.get("cast"), dict):
            out["cast"] = pts["cast"]
        if isinstance(pts.get("collect"), dict):
            out["collect"] = pts["collect"]
        if isinstance(old.get("scan_area"), dict):
            out["scan_area"] = old["scan_area"]
        if str(old.get("rod_key", "")).strip():
            out["rod_key"] = str(old["rod_key"]).strip()
        if old.get("bar_colors"):
            out["bar_colors"] = old["bar_colors"]
        out["collect_mode"] = "t" if old.get("collect_hold_t", True) else "click"
        adv = old.get("advanced")
        if isinstance(adv, dict):
            out["advanced"] = {k: v for k, v in adv.items() if k in DEFAULT_ADVANCED}
        return out
    return {}


class Config:
    def __init__(self, path: Path = CFG_PATH) -> None:
        self.path = Path(path)
        self.lock = threading.RLock()
        self.data: dict = copy.deepcopy(DEFAULTS)

    @classmethod
    def load(cls, path: Path = CFG_PATH) -> "Config":
        cfg = cls(path)
        loaded = None
        if cfg.path.is_file():
            try:
                loaded = json.loads(cfg.path.read_text(encoding="utf-8"))
            except Exception:
                try:  # битый файл не должен убивать запуск
                    cfg.path.replace(cfg.path.with_suffix(".broken.json"))
                except OSError:
                    pass
        if isinstance(loaded, dict):
            cfg.data = _merge(DEFAULTS, loaded)
        else:
            cfg.data = _merge(DEFAULTS, _import_legacy())
        if not cfg.data["web"].get("token"):
            cfg.data["web"]["token"] = secrets.token_urlsafe(9)
        cfg.save()
        return cfg

    def save(self) -> None:
        with self.lock:
            tmp = self.path.with_suffix(".tmp")
            try:
                tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
                os.replace(tmp, self.path)
            except OSError:
                pass

    def get(self, key, default=None):
        with self.lock:
            return copy.deepcopy(self.data.get(key, default))

    def update(self, patch: dict) -> None:
        with self.lock:
            self.data = _merge(self.data, patch)
        self.save()

    def adv(self, key: str) -> float:
        """Любой числовой параметр: пользовательский -> по умолчанию -> авто."""
        with self.lock:
            for src in (self.data.get("advanced") or {}, self.data.get("auto") or {}):
                if key in src:
                    try:
                        return float(src[key])
                    except (TypeError, ValueError):
                        pass
        if key in DEFAULT_ADVANCED:
            return float(DEFAULT_ADVANCED[key])
        return float(AUTO_DEFAULTS.get(key, 0.0))

    def advanced_all(self) -> dict:
        with self.lock:
            out = dict(DEFAULT_ADVANCED)
            for k, v in (self.data.get("advanced") or {}).items():
                try:
                    out[k] = float(v)
                except (TypeError, ValueError):
                    pass
            return out
