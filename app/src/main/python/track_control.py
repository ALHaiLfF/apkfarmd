from __future__ import annotations

from advanced_settings import DEFAULT_ADVANCED

TRACK_KEYS = (
    "accel_hold", "accel_release", "ball_ref_px", "latency_s",
    "hysteresis_px", "aim_offset", "zone_hold_s", "lost_timeout_s", "auto_latency",
)


class Motion:
    def __init__(self, alpha: float = 0.8, beta: float = 0.6) -> None:
        self.alpha, self.beta = alpha, beta
        self.y = self.v = None
        self.t = None

    def reset(self, y: float, t: float) -> None:
        self.y, self.v, self.t = float(y), 0.0, t

    def predict(self, t: float, a: float) -> tuple[float, float]:
        dt = max(0.0, t - self.t)
        return self.y + self.v * dt + 0.5 * a * dt * dt, self.v + a * dt

    def update(self, y_meas: float, t: float, a: float, jump: float) -> None:
        if self.y is None:
            self.reset(y_meas, t)
            return
        yp, vp = self.predict(t, a)
        dt = max(1e-3, t - self.t)
        r = y_meas - yp
        if abs(r) > jump:
            self.y, self.v = float(y_meas), vp
        else:
            self.y = yp + self.alpha * r
            self.v = vp + self.beta * r / dt
        self.t = t


class TrackController:
    def __init__(self) -> None:
        self.lat_ema: float | None = None    # выученная задержка «команда -> видно на экране», живёт между играми
        self.lat_n = 0
        self.configure({})
        self.reset()

    def configure(self, adv: dict) -> None:
        for k in TRACK_KEYS:
            d = DEFAULT_ADVANCED[k]
            try:
                setattr(self, k, float(adv.get(k, d)))
            except (TypeError, ValueError):
                setattr(self, k, float(d))
        self.ball_ref_px = max(1.0, self.ball_ref_px)

    def reset(self) -> None:
        self.ball = Motion()
        self.zone = Motion(alpha=0.6, beta=0.3)
        self.held = False
        self.bh = 0.0
        self._last_read = None
        self._last_new = 0.0
        self.zone_seen = 0.0
        self._hist: list[tuple[float, float]] = []
        self._cmd: tuple[float, bool] | None = None     # последняя смена команды: (когда, что)
        self._prev_cmd_t = -9.0
        self._last_cmd_t = -9.0

    @property
    def latency(self) -> float:
        if self.auto_latency >= 0.5 and self.lat_ema is not None:
            return self.lat_ema
        return self.latency_s

    def _learn_lag(self, now: float) -> None:
        """По вторым разностям положения шара ищем момент, когда он «почувствовал» нашу команду."""
        h = self._hist
        if len(h) < 3 or self._cmd is None:
            return
        (t0, y0), (t1, y1), (t2, y2) = h[-3], h[-2], h[-1]
        if t1 <= t0 or t2 <= t1:
            return
        v1 = (y1 - y0) / (t1 - t0)
        v2 = (y2 - y1) / (t2 - t1)
        a_est = (v2 - v1) / (((t1 + t2) - (t0 + t1)) / 2.0)
        tc, st = self._cmd
        s = self.bh / self.ball_ref_px
        a_ref = (self.accel_hold if st else self.accel_release) * s
        a_after = -a_ref if st else a_ref
        if a_est * (1 if a_after > 0 else -1) >= 0.55 * a_ref:
            lag = t1 - tc
            valid = 0.0 <= lag <= 0.9 and tc - self._prev_cmd_t > 0.6
            self._cmd = None
            if valid:
                lag = min(0.6, max(0.04, lag))
                self.lat_ema = lag if self.lat_ema is None else 0.6 * self.lat_ema + 0.4 * lag
                self.lat_n += 1
        elif now - tc > 1.0:
            self._cmd = None

    def start(self, ball_y: float, zone_y: float | None, ball_h: float, now: float) -> None:
        self.reset()
        self.ball.reset(ball_y, now)
        self.zone.reset(zone_y if zone_y is not None else ball_y, now)
        self.bh = float(ball_h)
        self.zone_seen = now

    def observe(self, ball_y: float, ball_h: float, zone_top: float | None, zone_y: float | None, now: float) -> bool:
        self.bh = 0.8 * self.bh + 0.2 * float(ball_h) if self.bh > 0 else float(ball_h)
        inside = False
        read = (ball_y, zone_top)
        same = read == self._last_read and now - self._last_new < 0.15
        if not same:
            self._last_read = read
            self._last_new = now
            self._hist.append((now, float(ball_y)))
            del self._hist[:-4]
            self._learn_lag(now)
            s = self.bh / self.ball_ref_px
            a_applied = -self.accel_hold * s if self.held else self.accel_release * s
            self.ball.update(ball_y, now, a_applied, jump=4 * self.bh)
            if zone_y is not None:
                self.zone.update(zone_y, now, 0.0, jump=4 * self.bh)
                self.zone_seen = now
        return inside

    def decide(self, now: float) -> bool | None:
        if now - self.zone_seen > self.zone_hold_s:
            self.held = False
            return None
        if now - self.zone_seen > 0.1:
            self.zone.v = 0.0
        s = self.bh / self.ball_ref_px
        a_up = self.accel_hold * s
        a_dn = self.accel_release * s
        a_now = -a_up if self.held else a_dn
        lat = self.latency
        y, v = self.ball.predict(now + lat, a_now)
        ty, tv = self.zone.predict(now + lat, 0.0)
        target = ty + self.aim_offset * self.bh
        v_rel = v - tv
        if v_rel < 0:
            stop = y - v_rel * v_rel / (2 * a_dn)
        else:
            stop = y + v_rel * v_rel / (2 * a_up)
        band = self.hysteresis_px * s
        was = self.held
        if self.held:
            self.held = stop > target - band
        else:
            self.held = stop > target + band
        if self.held != was:
            self._prev_cmd_t = self._last_cmd_t
            self._last_cmd_t = now
            self._cmd = (now, self.held)
        return self.held
