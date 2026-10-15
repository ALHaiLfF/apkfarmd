"""Как качество слежения зависит от частоты кадров и задержки касания (симулятор из sim_world)."""
import os, sys, copy, math
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sim_world as sw


class LagSim(sw.SimWorld):
    def __init__(self, seed, look_cost, hold_lat, **k):
        super().__init__(seed, 0.0, True, **k) if False else super().__init__(seed, 0.0, True)
        self.look_cost = look_cost
        self.hold_lat = hold_lat
        self._pending = []

    def _step(self, dt):
        # применяем отложенные нажатия
        while self._pending and self._pending[0][0] <= self.t:
            _, d = self._pending.pop(0)
            self._real = d
        super()._step(dt)

    def set_hold(self, down):
        self._pending.append((self.t + self.hold_lat, bool(down)))
        if not self.hold_lat:
            self.hold = bool(down)

    def _apply(self):
        pass

    def look(self, near, wide):
        self.sleep(self.look_cost)
        return super().look(near, wide)


# подмена: физика берёт self.hold; связываем с отложенным значением
orig_step = sw.SimWorld._step
def _step(self, dt):
    if hasattr(self, "_pending"):
        while self._pending and self._pending[0][0] <= self.t:
            _, d = self._pending.pop(0)
            self.hold = d
    orig_step(self, dt)
sw.SimWorld._step = _step


def run(look_cost, hold_lat, hours=0.5, seeds=3):
    tot = 0
    for seed in range(seeds):
        w = LagSim(seed, look_cost, hold_lat)
        t_end = hours * 3600
        cfg = sw.Config.__new__(sw.Config); cfg.lock = sw.threading.RLock()
        from config import DEFAULTS
        cfg.data = copy.deepcopy(DEFAULTS); cfg.path = None; cfg.save = lambda: None
        hub = sw.Hub(); hub.begin_run()
        b = sw.Brain(w, cfg, hub, sw.TrackController(), lambda: w.now() >= t_end)
        b.run()
        tot += w.true_catches
    return tot / seeds / hours


if __name__ == "__main__":
    for lc, hl in [(0.006, 0.0), (0.04, 0.03), (0.07, 0.03), (0.1, 0.03), (0.1, 0.07), (0.15, 0.05)]:
        print(f"look={lc*1000:.0f}мс (≈{1/(lc+0.0):.0f} к/с макс), задержка нажатия={hl*1000:.0f}мс -> уловов/час: {run(lc, hl):.0f}")
