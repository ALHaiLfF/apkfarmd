"""Разбирает логи автотеста и печатает аннотации GitHub. Код возврата 1, если макрос не справился."""
import re, sys
fake = open(sys.argv[1], encoding="utf-8", errors="ignore").read()
app = open(sys.argv[2], encoding="utf-8", errors="ignore").read() if len(sys.argv) > 2 else ""
stats = re.findall(r"STAT inst=\d+ t=(\d+) casts=(\d+) catches=(\d+) fails=(\d+) collects=(\d+) missed=(\d+) breaks=(\d+) tapsFish=(\d+) downs=(\d+) gameDowns=(\d+)", fake)
def enc(s): return s.replace("%", "%25").replace("\r", "").replace("\n", "%0A")
def note(kind, title, body): print(f"::{kind} title={title}::{enc(body[:28000])}")
ok = True
if not stats:
    note("error", "e2e: игра не писала STAT", "\n".join(fake.splitlines()[-60:]) + "\n--- app ---\n" + "\n".join(app.splitlines()[-80:]))
    sys.exit(1)
t, casts, catches, fails, collects, missed, breaks, taps, downs, gdowns = map(int, stats[-1])
summary = f"t={t}s casts={casts} миниигр выиграно={catches} проиграно={fails} собрано={collects} упущено={missed} срывов сбора={breaks} тыков по рыбе={taps} касаний={downs} нажатий в миниигре={gdowns}"
need_c = max(3, t // 60)
verdict = []
if catches < need_c: verdict.append(f"мало выигранных миниигр ({catches} < {need_c})")
if collects < max(2, catches - 2): verdict.append(f"рыба не собирается ({collects} из {catches})")
if missed: verdict.append(f"рыба упущена {missed} раз")
if taps > 6 * max(1, collects): verdict.append(f"слишком много тыков по рыбе ({taps})")
ok = not verdict
note("notice" if ok else "error", "e2e итог", ("ПРОШЁЛ: " if ok else "ПРОВАЛ: " + "; ".join(verdict) + "\n") + summary)
import bisect, statistics
Hs = [(int(m.group(1)), int(m.group(2))) for m in re.finditer(r"^H (\d+) (\d)$", app, re.M)]
Ev = [(int(m.group(2)), 1 if m.group(1) == "D" else 0) for m in re.finditer(r"EV ([DU]) (\d+)", fake)]
lat = {1: [], 0: []}
for dn in (1, 0):
    hs = [t for t, d in Hs if d == dn]
    for t, d in Ev:
        if d != dn: continue
        i = bisect.bisect_right(hs, t) - 1
        if i >= 0 and t - hs[i] < 1500: lat[dn].append(t - hs[i])
def q(a, p):
    a = sorted(a); return a[min(len(a) - 1, int(len(a) * p))] if a else -1
tr = [tuple(map(int, m.groups())) for m in re.finditer(r"TR (\d+) (-?\d+) (-?\d+) (\d)", fake)]
err = [abs(b - z) for _, b, z, _ in tr]
lat_s = (f"задержка нажатия (вызов макроса -> касание дошло до игры): вниз n={len(lat[1])} med={q(lat[1],.5)} p90={q(lat[1],.9)} мс; "
         f"вверх n={len(lat[0])} med={q(lat[0],.5)} p90={q(lat[0],.9)} мс; вызовов макроса: {len(Hs)}, касаний в игре: {len(Ev)}; "
         f"средняя ошибка |шар-зона|={statistics.mean(err) if err else -1:.0f}px по {len(tr)} точкам")
note("notice", "e2e латентность", lat_s)
Ds = [(int(a), int(b), int(c), int(d), e, int(f), int(g)) for a, b, c, d, e, f, g in re.findall(r"^D (\d+) (-?\d+) (-?\d+) (-?\d+) (\w+) (\d+) (\d+)$", app, re.M)]
trt = [t for t, *_ in tr]
eb, ez, nz = [], [], 0
ages = [x[5] for x in Ds]; procs = [x[6] for x in Ds]
def match(off):
    eb_, n_ = [], 0
    for t, by, zt, zb, src, age, proc in Ds:
        tt = t - proc - age + off          # момент, когда картинка реально была нарисована
        i = bisect.bisect_left(trt, tt)
        cand = [j for j in (i - 1, i) if 0 <= j < len(tr)]
        if not cand: continue
        j = min(cand, key=lambda j: abs(trt[j] - tt))
        if abs(trt[j] - tt) > 120: continue
        eb_.append(by - tr[j][1])
    return eb_
scan = []
for off in range(-300, 301, 50):
    e_ = match(off)
    if len(e_) > 20: scan.append((statistics.median(abs(x) for x in e_), off))
best = min(scan) if scan else None
note("notice", "e2e возраст картинки", f"возраст кадра при захвате: med={q(ages,.5)} p90={q(ages,.9)} мс; от захвата до решения: med={q(procs,.5)} p90={q(procs,.9)} мс; "
     f"поправка времени, при которой ошибка шара минимальна: {best[1] if best else '?'} мс (ошибка {best[0] if best else '?'} px); по сетке: {scan}")
for t, by, zt, zb, src, age, proc in Ds:
    tt = t - proc - age
    i = bisect.bisect_left(trt, tt)
    cand = [j for j in (i - 1, i) if 0 <= j < len(tr)]
    if not cand: continue
    j = min(cand, key=lambda j: abs(trt[j] - tt))
    if abs(trt[j] - tt) > 150: continue
    eb.append(by - tr[j][1])
    if zt >= 0:
        nz += 1
        ez.append((zt + zb) / 2 - tr[j][2])
def stat(a):
    if not a: return "нет данных"
    a2 = sorted(abs(x) for x in a)
    return f"med|e|={a2[len(a2)//2]:.0f} p90={a2[int(len(a2)*.9)]:.0f} bias={statistics.mean(a):.0f}"
if tr:
    t0g = tr[len(tr) // 3][0]
    rows = []
    hi = 0
    seg = [r for r in tr if t0g <= r[0] <= t0g + 14000]
    for k, (t, b, z, h) in enumerate(seg):
        t_next = seg[k + 1][0] if k + 1 < len(seg) else t + 100
        cm = "".join(("v" if d else "^") for tt, d in Hs if t <= tt < t_next)   # v — макрос велел держать, ^ — отпустить
        rows.append(f"{(t - t0g) / 1000:5.1f} err={b - z:4d} {'#' if h else '.'} {cm}")
    note("notice", "e2e трасса 14с", "err=шар-зона (минус: шар выше зоны); # — палец реально прижат в игре; v/^ — команды макроса\n" + "\n".join(rows))
note("notice", "e2e детектор vs правда", f"кадров с шаром={len(Ds)}, с зоной={nz}; шар: {stat(eb)}; центр зоны: {stat(ez)}")
app = "\n".join(l for l in app.splitlines() if not re.match(r"^[HD] \d+ ", l))
ev = [l for l in fake.splitlines() if re.search(r"MG_START|MG_END|FISH|COLLECT|CAST|ROD|STAT|START|DETACH", l) and "EV " not in l and " TR " not in l]
note("notice", "e2e игра", "\n".join(ev[-140:]))
note("notice", "e2e макрос", "\n".join(app.splitlines()[-160:]))
sys.exit(0 if ok else 1)
