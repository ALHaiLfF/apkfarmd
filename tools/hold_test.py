"""Мозг сам находит рабочий способ удержания: в симуляторе реагирует только способ №3 (индекс 2)."""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sim_world as sw
from sim_world import *  # noqa: F401,F403


class HoldSim(sw.SimWorld):
    GOOD = 2

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.mode = 0
        self.hold_known = False
        self.switched = 0
        self.saved = None
        self._real_hold = False

    def set_hold(self, down):
        self.hold = bool(down) and self.mode == self.GOOD   # в «плохом» режиме палец не доходит до игры

    def next_hold_mode(self):
        self.hold = False
        self.mode = (self.mode + 1) % 4
        self.switched += 1
        self.hold_known = False
        return f"режим {self.mode}"

    def hold_works(self):
        if not self.hold_known:
            self.hold_known = True
            self.saved = self.mode


def main():
    import copy
    from config import DEFAULTS
    out = 0
    for seed in range(4):
        w = HoldSim(seed, 0.0, True)
        t_end = 1800.0
        cfg = sw.Config.__new__(sw.Config)
        cfg.lock = sw.threading.RLock()
        cfg.data = copy.deepcopy(DEFAULTS); cfg.path = None; cfg.save = lambda: None
        hub = sw.Hub(); hub.begin_run()
        b = sw.Brain(w, cfg, hub, sw.TrackController(), lambda: w.now() >= t_end)
        b.run()
        ok = w.saved == HoldSim.GOOD and w.true_catches >= 15 and w.switched <= 8
        print(f"seed {seed}: режим={w.mode} сохранён={w.saved} переключений={w.switched} уловов={w.true_catches} -> {'OK' if ok else 'ПРОВАЛ'}")
        out += not ok
    return out


if __name__ == "__main__":
    sys.exit(main())
