"""Точка входа на Android. Kotlin (CoreService) вызывает boot(), остальное — панель и мозг в потоках."""
from __future__ import annotations

import os
import sys
import threading
import time
import traceback
from pathlib import Path

_S: dict = {}


def _crash_log(text: str) -> None:
    try:
        base = os.environ.get("FISH_HOME") or "."
        with open(os.path.join(base, "anime-fishing-error.log"), "a", encoding="utf-8") as f:
            f.write(time.strftime("%F %T") + "\n" + text + "\n")
    except OSError:
        pass


def boot(files_dir: str) -> int:
    """Поднимает всё и возвращает порт панели. Повторный вызов безопасен."""
    if _S.get("port"):
        return _S["port"]
    os.environ["FISH_HOME"] = files_dir
    os.makedirs(files_dir, exist_ok=True)
    os.chdir(files_dir)
    sys.excepthook = lambda et, ev, tb: _crash_log("".join(traceback.format_exception(et, ev, tb)))
    threading.excepthook = lambda a: _crash_log("".join(traceback.format_exception(a.exc_type, a.exc_value, a.exc_traceback)))

    import android_world as aw
    from config import Config
    from hub import Hub
    from supervisor import Supervisor
    from webui import Panel

    cfg = Config.load(Path(files_dir) / "config.json")
    if cfg.get("platform") != "android":
        cfg.update({"platform": "android", "cast": None, "collect": None, "rod": None,
                    "collect_mode": "click", "rod_key": "slot"})
    hub = Hub()
    sup = Supervisor(cfg, hub, aw.AndroidWorld, aw.release_all)

    def pts() -> dict:
        return {n: isinstance(cfg.get(n), dict) for n in ("cast", "collect", "rod")}

    def phone_state() -> dict:
        st = aw.status()
        return {"phone": {"access": bool(st.get("access")), "capture": bool(st.get("capture")),
                          "pkg": st.get("pkg", ""), **pts()},
                "detect": aw.NOTE["text"], "dfps": round(aw.NOTE["fps"], 1),
                "scan_area": cfg.get("scan_area")}

    def check() -> str | None:
        st = aw.status()
        p = pts()
        if not st.get("access"):
            return "Сначала включи «Управление касаниями» в настройке телефона"
        if not st.get("capture"):
            return "Сначала разреши «Видеть экран»"
        if not p["cast"]:
            return "Укажи точку заброса"
        if not p["collect"]:
            return "Укажи кнопку «Собрать»"
        return None

    def shutdown() -> None:
        sup.shutdown()
        aw.release_all()

    panel = Panel(cfg, hub, sup, lambda: aw.preview_jpeg(cfg, hub), shutdown,
                  host="127.0.0.1", strict=True, extra_state=phone_state, start_check=check)
    port = panel.start()
    hub.event("info", f"Панель: порт {port}")
    _S.update(port=port, cfg=cfg, hub=hub, sup=sup, panel=panel, check=check)
    if cfg.get("autostart") and not check():
        sup.start()
    return port


def url() -> str:
    return _S["panel"].local_url()


def is_running() -> bool:
    sup = _S.get("sup")
    return bool(sup and sup.running)


def toggle() -> str:
    """'' — всё хорошо (запущено/остановлено), иначе текст причины, почему не стартует."""
    sup = _S.get("sup")
    if sup is None:
        return "Ещё запускаюсь…"
    if sup.running:
        sup.stop()
        return ""
    problem = _S["check"]()
    if problem:
        return problem
    sup.start()
    return ""


def stop() -> None:
    sup = _S.get("sup")
    if sup:
        sup.stop()


def point_picked(name: str, fx: float, fy: float) -> None:
    if name not in ("cast", "collect", "rod"):
        return
    fx, fy = min(1.0, max(0.0, float(fx))), min(1.0, max(0.0, float(fy)))
    _S["cfg"].update({name: {"x": round(fx, 5), "y": round(fy, 5)}})
    label = {"cast": "заброса", "collect": "кнопки «Собрать»", "rod": "слота удочки"}[name]
    _S["hub"].event("info", f"Точка {label} сохранена")
