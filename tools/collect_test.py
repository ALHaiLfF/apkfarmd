import os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app", "src", "main", "python"))
os.environ["FISH_HOME"] = tempfile.mkdtemp()
from pathlib import Path
from brain import Brain
from config import Config
from hub import Hub

class W:
    """Виртуальные часы + ромб, который исчезает после нужного удержания."""
    def __init__(self, mode):
        self.t = 0.0; self.mode = mode; self.down_at = None; self.log = []
        self.pos = (1500, 500); self.gone = False; self.appear_at = 0.5
        self.moved = False; self.fixed = 0
    def now(self): return self.t
    def sleep(self, s): self.t += max(s, 1e-4)
    def abort(self): return False
    def find_collect(self, bans=()):
        if self.mode == "never": return None
        if self.mode == "static": return None if any(abs(self.pos[0]-b[0])<50 for b,_ in bans) else self.pos
        if self.gone or self.t < self.appear_at: return None
        if self.mode == "moves" and self.down_at is not None and not self.moved and self.t - self.down_at > 0.8:
            self.moved = True; self.pos = (900, 300)   # игра отодвинула кнопку, палец теперь мимо
            self.down_at = None
        return self.pos
    def hold_pixel(self, x, y, down):
        self.log.append(("hold", round(self.t, 2), (round(x), round(y)), down))
        if down: self.down_at = self.t; self.hx = (x, y)
        else:
            if self.down_at is not None and self.mode in ("ok", "moves") and self.t - self.down_at >= 2.5 \
               and abs(x - self.pos[0]) < 60 and abs(y - self.pos[1]) < 60: self.gone = True
            self.down_at = None
    def hold_collect_click(self, s): self.fixed += 1; self.t += s
    def window_ok(self): return True
    def is_foreground(self): return True
    def release_all(self): pass
    def set_hold(self, d): pass

def run(mode):
    w = W(mode)
    cfg = Config.load(Path(os.environ["FISH_HOME"]) / f"{mode}.json")
    cfg.update({"collect_mode": "click"})
    hub = Hub()
    b = Brain(w, cfg, hub, None, lambda: False)
    b.collect()
    # «ромб исчезает раньше, чем отпустили» — считаем по моменту, когда down был и gone стал True
    msgs = [e["m"] for e in hub.log]
    return w, b, msgs

ok = True
def expect(name, cond, extra=""):
    global ok; ok &= bool(cond); print(("OK  " if cond else "FAIL"), name, extra)

w, b, m = run("ok");     expect("обычный сбор: держит и ромб исчезает", w.gone and w.fixed == 0, str([x for x in w.log][:4]))
w, b, m = run("moves");  expect("кнопку отодвинули: перехватывает на новом месте", w.gone and w.moved, str(w.log))
w, b, m = run("never");  expect("ромба не видно: жмёт в сохранённую точку один раз", w.fixed == 1 and not w.log, str(m))
w, b, m = run("static"); expect("ложный ромб: 5 попыток, потом в игнор", len(b.dbans) == 1 and sum(1 for l in w.log if l[3]) == 5, f"{len(b.dbans)} {m[-2:]}")
print("ВСЁ ХОРОШО" if ok else "ЕСТЬ ПРОВАЛЫ"); sys.exit(0 if ok else 1)
