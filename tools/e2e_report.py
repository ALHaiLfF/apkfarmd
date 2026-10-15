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
app = "\n".join(l for l in app.splitlines() if not re.match(r"^H \d+ \d$", l))
ev = [l for l in fake.splitlines() if re.search(r"MG_START|MG_END|FISH|COLLECT|CAST|ROD|STAT|START|DETACH", l) and "EV " not in l and " TR " not in l]
note("notice", "e2e игра", "\n".join(ev[-140:]))
note("notice", "e2e макрос", "\n".join(app.splitlines()[-160:]))
sys.exit(0 if ok else 1)
