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
    """Слежение за шаром с компенсацией задержки (предиктор Смита).

    D — полная задержка «команда -> видна на кадре»: касание + отрисовка игры + возраст кадра.
    Шар на кадре в момент t движется под действием команд, отданных до t-D, поэтому
    и фильтр, и прогноз интегрируют ускорение по ЖУРНАЛУ команд, сдвинутому на D.
    Саму D выучиваем по записи шара и журналу команд (подбор D, при котором траектория
    лучше всего ложится в модель «ускорение по команде»).
    """

    ID_WINDOW_S = 2.0
    ID_EVERY_S = 0.4
    D_MIN, D_MAX, D_STEP = 0.02, 0.70, 0.02
    RULE = 'mpc'
    STEP_USE = 1.0
    PLAN_STEPS = 8
    SWITCH_COST = 0.05
    TERM_W = 3.0
    ZA_GAIN = 0.12
    ZA_USE = 0.7

    def __init__(self) -> None:
        self.lat_ema: float | None = None    # выученная задержка «команда -> видно на экране», живёт между играми
        self.lat_n = 0
        self._wall_bh = 0.0                      # размер шара, при котором выучены границы шкалы
        self._forget_walls()
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
        self.zone_a = 0.0
        self._dec_dt = 0.1
        self._last_dec: float | None = None
        self._obs: list[tuple[float, float]] = []
        self._log_t: list[float] = [-1e9]       # журнал команд: момент смены и новое состояние
        self._log_h: list[bool] = [False]
        self._last_id = -9.0

    @property
    def latency(self) -> float:
        if self.auto_latency >= 0.5 and self.lat_ema is not None:
            return self.lat_ema
        return self.latency_s

    # ---------------------------------------------------------------- журнал команд и модель
    def _note_cmd(self, held: bool, now: float) -> None:
        if held != self._log_h[-1]:
            self._log_t.append(now)
            self._log_h.append(held)
            if len(self._log_t) > 80:
                del self._log_t[1:20]
                del self._log_h[1:20]
                self._log_t[0] = -1e9

    def _held_at(self, w: float) -> bool:
        lt = self._log_t
        lo, hi = 0, len(lt) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if lt[mid] <= w:
                lo = mid
            else:
                hi = mid - 1
        return self._log_h[lo]

    def _advance(self, y: float, v: float, t0: float, t1: float, d: float, a_up: float, a_dn: float) -> tuple[float, float]:
        """Двигаем (y,v) от t0 до t1; ускорение берём из команд, отданных на d раньше."""
        if t1 <= t0:
            return y, v
        cuts = [t0]
        for tc in self._log_t[1:]:
            tt = tc + d
            if t0 < tt < t1:
                cuts.append(tt)
        cuts.append(t1)
        cuts.sort()
        lo, hi = self.wall_lo, self.wall_hi
        for a, b in zip(cuts, cuts[1:]):
            if b - a <= 0:
                continue
            acc = -a_up if self._held_at((a + b) * 0.5 - d) else a_dn
            n = max(1, int((b - a) / 0.03 + 0.999))
            dt = (b - a) / n
            for _ in range(n):
                y += v * dt + 0.5 * acc * dt * dt
                v += acc * dt
                if hi is not None and y > hi:
                    y, v = hi, min(v, 0.0)
                elif lo is not None and y < lo:
                    y, v = lo, max(v, 0.0)
        return y, v

    def _forget_walls(self) -> None:
        self.wall_lo: float | None = None       # границы шкалы: шар дважды упёрся в один и тот же край
        self.wall_hi: float | None = None
        self._rmin = self._rmax = None
        self._hit_lo: list[float] = []
        self._hit_hi: list[float] = []

    def _learn_walls(self, y: float, t: float) -> None:
        tol = 0.15 * self.bh
        if self._wall_bh and abs(self.bh - self._wall_bh) > 0.25 * self._wall_bh:
            self._forget_walls()                # другой масштаб — шкала другая
        if self._rmin is None:
            self._rmin = self._rmax = y
            self._wall_bh = self.bh
        if y > self._rmax + tol:
            self._rmax, self._hit_hi = y, []
            if self.wall_hi is not None and y > self.wall_hi + tol:
                self.wall_hi = None
        if y < self._rmin - tol:
            self._rmin, self._hit_lo = y, []
            if self.wall_lo is not None and y < self.wall_lo - tol:
                self.wall_lo = None
        if y >= self._rmax - tol:
            if not self._hit_hi or t - self._hit_hi[-1] > 0.4:
                self._hit_hi.append(t)
            self._rmax = max(self._rmax, y)
            if len(self._hit_hi) >= 2 and self._rmax - self._rmin > 3 * self.bh:
                self.wall_hi = self._rmax
        if y <= self._rmin + tol:
            if not self._hit_lo or t - self._hit_lo[-1] > 0.4:
                self._hit_lo.append(t)
            self._rmin = min(self._rmin, y)
            if len(self._hit_lo) >= 2 and self._rmax - self._rmin > 3 * self.bh:
                self.wall_lo = self._rmin

    def _fit_delay(self, now: float) -> None:
        obs = self._obs
        if now - self._last_id < self.ID_EVERY_S or len(obs) < 8 or obs[-1][0] - obs[0][0] < 0.8:
            return
        if len(self._log_t) < 3:
            return
        self._last_id = now
        s = self.bh / self.ball_ref_px
        a_up, a_dn = self.accel_hold * s, self.accel_release * s
        t0 = obs[0][0]
        res: list[tuple[float, float]] = []
        d = self.D_MIN
        while d <= self.D_MAX + 1e-9:
            yi = vi = 0.0
            tp = t0
            rows = []
            for t, y in obs:
                yi, vi = self._advance(yi, vi, tp, t, d, a_up, a_dn)
                tp = t
                rows.append((t - t0, y - yi))
            n = len(rows)
            sx = sum(r[0] for r in rows); sy = sum(r[1] for r in rows)
            sxx = sum(r[0] * r[0] for r in rows); sxy = sum(r[0] * r[1] for r in rows)
            den = n * sxx - sx * sx
            if den <= 1e-9:
                return
            b = (n * sxy - sx * sy) / den
            a0 = (sy - b * sx) / n
            e = sum((r[1] - a0 - b * r[0]) ** 2 for r in rows) / n
            res.append((d, e))
            d += self.D_STEP
        es = sorted(r[1] for r in res)
        med = es[len(es) // 2]
        best = min(res, key=lambda r: r[1] * (1.0 + 0.002 * r[0]))        # при равенстве — меньшая задержка
        if best[1] > (1.2 * self.bh) ** 2 or best[1] > 0.5 * med:
            return                                                          # нет возбуждения или модель не ложится
        k = res.index(best)
        dd = best[0]
        if 0 < k < len(res) - 1:
            e0, e1, e2 = res[k - 1][1], res[k][1], res[k + 1][1]
            den = e0 - 2 * e1 + e2
            if den > 1e-9:
                dd += max(-0.5, min(0.5, 0.5 * (e0 - e2) / den)) * self.D_STEP
        dd = min(self.D_MAX, max(self.D_MIN, dd))
        self.lat_ema = dd if self.lat_ema is None else 0.6 * self.lat_ema + 0.4 * dd
        self.lat_n += 1

    # ---------------------------------------------------------------- вход / выход
    def start(self, ball_y: float, zone_y: float | None, ball_h: float, now: float) -> None:
        self.reset()
        self.ball.reset(ball_y, now)
        self.zone.reset(zone_y if zone_y is not None else ball_y, now)
        self.bh = float(ball_h)
        self.zone_seen = now

    def observe(self, ball_y: float, ball_h: float, zone_top: float | None, zone_y: float | None, now: float) -> bool:
        self.bh = 0.8 * self.bh + 0.2 * float(ball_h) if self.bh > 0 else float(ball_h)
        read = (ball_y, zone_top)
        same = read == self._last_read and now - self._last_new < 0.15
        if not same:
            self._last_read = read
            self._last_new = now
            self._obs.append((now, float(ball_y)))
            while self._obs and now - self._obs[0][0] > self.ID_WINDOW_S:
                del self._obs[0]
            self._learn_walls(float(ball_y), now)
            if self.auto_latency >= 0.5:
                self._fit_delay(now)
            s = self.bh / self.ball_ref_px
            a_up, a_dn = self.accel_hold * s, self.accel_release * s
            d = self.latency
            m = self.ball
            if m.y is None:
                m.reset(ball_y, now)
            else:
                yp, vp = self._advance(m.y, m.v, m.t, now, d, a_up, a_dn)
                dt = max(1e-3, now - m.t)
                r = ball_y - yp
                if abs(r) > 4 * self.bh:
                    m.y, m.v = float(ball_y), vp
                else:
                    m.y = yp + m.alpha * r
                    m.v = vp + m.beta * r / dt
                m.t = now
            if zone_y is not None:
                zv0, zt0 = self.zone.v, self.zone.t
                self.zone.update(zone_y, now, 0.0, jump=4 * self.bh)
                if zv0 is not None and zt0 is not None and now - zt0 > 0.02:
                    za = (self.zone.v - zv0) / (now - zt0)
                    lim = 6.0 * self.accel_release * s
                    za = max(-lim, min(lim, za))
                    self.zone_a = (1.0 - self.ZA_GAIN) * self.zone_a + self.ZA_GAIN * za
                self.zone_seen = now
        return False

    def decide(self, now: float) -> bool | None:
        self._note_cmd(self.held, now)          # на случай, если мозг сам сбросил удержание
        if now - self.zone_seen > self.zone_hold_s:
            self.held = False
            self._note_cmd(False, now)
            return None
        if now - self.zone_seen > 0.1:
            self.zone.v = 0.0
        s = self.bh / self.ball_ref_px
        a_up = self.accel_hold * s
        a_dn = self.accel_release * s
        d = self.latency
        horizon = max(now, self.ball.t) + d      # к этому моменту (по часам кадра) дойдёт наша новая команда
        y, v = self._advance(self.ball.y, self.ball.v, self.ball.t, horizon, d, a_up, a_dn)
        za = self.ZA_USE * self.zone_a if now - self.zone_seen < 0.3 else 0.0
        ty, tv = self.zone.predict(horizon, za)
        aim = self.aim_offset * self.bh

        def zat(tt: float) -> float:
            dz = tt - horizon
            return ty + tv * dz + 0.5 * za * dz * dz

        def zvat(tt: float) -> float:
            return tv + za * (tt - horizon)
        dts = self._dec_dt
        if self._last_dec is not None:
            dts = 0.7 * dts + 0.3 * min(0.3, max(0.03, now - self._last_dec))
            self._dec_dt = dts
        self._last_dec = now
        step = min(0.14, max(0.05, dts))
        n = self.PLAN_STEPS
        bh = max(1.0, self.bh)
        wlo, whi = self.wall_lo, self.wall_hi
        sw_cost = self.SWITCH_COST
        prev = self.held
        step = min(0.14, max(0.05, dts))
        if self.RULE == 'mpc':
            # перебираем все последовательности команд «держать/отпустить» по тактам и берём лучшую
            nodes = [(0.0, y, v, prev, None)]       # (цена, y, v, последняя команда, первая команда)
            for k in range(1, n + 1):
                t_k = k * step
                zc = zat(horizon + t_k) + aim
                nxt = []
                for cost, py, pv, pc, first in nodes:
                    for c in (True, False):
                        acc = -a_up if c else a_dn
                        qy = py + pv * step + 0.5 * acc * step * step
                        qv = pv + acc * step
                        if whi is not None and qy > whi:
                            qy, qv = whi, min(qv, 0.0)
                        elif wlo is not None and qy < wlo:
                            qy, qv = wlo, max(qv, 0.0)
                        e = abs(qy - zc) / bh
                        e = e * e if e < 2.0 else 4.0 + 4.0 * (e - 2.0)
                        cc = cost + e + (sw_cost if (c != pc) else 0.0)
                        nxt.append((cc, qy, qv, c, first if first is not None else c))
                nodes = nxt
            best = None
            for cost, qy, qv, c, first in nodes:
                vr = qv - zvat(horizon + n * step)
                stop = qy - vr * vr / (2 * a_dn) if vr < 0 else qy + vr * vr / (2 * a_up)
                ze = abs(stop - (zat(horizon + n * step) + aim)) / bh
                tot = cost + self.TERM_W * (ze * ze if ze < 2.0 else 4.0 + 4.0 * (ze - 2.0))
                if best is None or tot < best[0]:
                    best = (tot, first)
            self.held = bool(best[1])
        else:
            dl = min(0.25, max(0.0, step * self.STEP_USE))
            acc = -a_up if self.held else a_dn
            y2 = y + v * dl + 0.5 * acc * dl * dl
            v2 = v + acc * dl
            if whi is not None and y2 > whi:
                y2, v2 = whi, min(v2, 0.0)
            elif wlo is not None and y2 < wlo:
                y2, v2 = wlo, max(v2, 0.0)
            ty2, tv2 = zat(horizon + dl), zvat(horizon + dl)
            v_rel = v2 - tv2
            if v_rel < 0:
                stop = y2 - v_rel * v_rel / (2 * a_dn)
            else:
                stop = y2 + v_rel * v_rel / (2 * a_up)
            band = self.hysteresis_px * s
            target = ty2 + aim
            if self.held:
                self.held = stop > target - band
            else:
                self.held = stop > target + band
        self._note_cmd(self.held, now)
        return self.held
