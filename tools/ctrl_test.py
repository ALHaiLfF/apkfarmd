"""Качество слежения при задержках: частота кадров, запаздывание картинки, задержка касания; авто-задержка против фиксированной."""
import os, sys, copy, math, bisect
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sim_world as sw


class LagSim(sw.SimWorld):
    def __init__(self, seed, look_cost, hold_lat, obs_delay):
        super().__init__(seed, 0.0, True)
        self.look_cost, self.hold_lat, self.obs_delay = look_cost, hold_lat, obs_delay
        self._pending = []
        self._real = False
        self._hist = []      # (t, y, zone_center)

    def _step(self, dt):
        while self._pending and self._pending[0][0] <= self.t:
            self._real = self._pending.pop(0)[1]
        self.hold = self._real
        super()._step(dt)
        self._hist.append((self.t, self.y, self.zone_c(self.t)))
        if len(self._hist) > 400:
            del self._hist[:100]

    def set_hold(self, down):
        self._pending.append((self.t + self.hold_lat, bool(down)))

    def release_all(self):
        self._pending.clear(); self._real = False; self.hold = False

    def look(self, near, wide):
        self.sleep(self.look_cost)
        lk = super().look(near, wide)
        if lk.game is not None and self.state == "game" and self._hist:
            ts = [h[0] for h in self._hist]
            i = max(0, bisect.bisect_left(ts, self.t - self.obs_delay))
            _, y, zc = self._hist[min(i, len(self._hist) - 1)]
            g = lk.game
            lk.game = sw.Game(g.ball_x, y, g.ball_w, g.ball_h, g.zone_x0, g.zone_x1, int(zc - 27), int(zc + 27))
        return lk


def run(look_cost, hold_lat, obs_delay, auto, hours=0.5, seeds=3):
    tot = lat = 0
    for seed in range(seeds):
        w = LagSim(seed, look_cost, hold_lat, obs_delay)
        t_end = hours * 3600
        cfg = sw.Config.__new__(sw.Config); cfg.lock = sw.threading.RLock()
        from config import DEFAULTS
        cfg.data = copy.deepcopy(DEFAULTS); cfg.path = None; cfg.save = lambda: None
        cfg.data["advanced"] = {"auto_latency": 1.0 if auto else 0.0}
        hub = sw.Hub(); hub.begin_run()
        tr = sw.TrackController()
        b = sw.Brain(w, cfg, hub, tr, lambda: w.now() >= t_end)
        b.run()
        tot += w.true_catches
        lat += (tr.lat_ema or 0)
    return tot / seeds / hours, lat / seeds


if __name__ == "__main__":
    print("look(мс) | касание(мс) | запаздывание картинки(мс) | уловов/час: фикс 0.10 с -> авто (выученная задержка, мс)")
    for lc, hl, od in [(0.04, 0.03, 0.0), (0.07, 0.03, 0.05), (0.10, 0.04, 0.15), (0.10, 0.05, 0.25), (0.07, 0.05, 0.35), (0.12, 0.06, 0.45)]:
        f, _ = run(lc, hl, od, False)
        a, l = run(lc, hl, od, True)
        print(f"{lc*1000:5.0f} | {hl*1000:5.0f} | {od*1000:5.0f} | {f:5.0f} -> {a:5.0f} (латентность {l*1000:.0f} мс; ожид. ≈{(hl+od+lc/2)*1000:.0f})")
