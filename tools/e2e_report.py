"""Разбирает логи автотеста и печатает аннотации GitHub. Код возврата 1, если макрос не справился."""
import re, sys
fake = open(sys.argv[1], encoding="utf-8", errors="ignore").read()
app = open(sys.argv[2], encoding="utf-8", errors="ignore").read() if len(sys.argv) > 2 else ""
stats = re.findall(r"STAT t=(\d+) casts=(\d+) catches=(\d+) fails=(\d+) collects=(\d+) missed=(\d+) breaks=(\d+) tapsFish=(\d+) downs=(\d+) gameDowns=(\d+)", fake)
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
ev = [l for l in fake.splitlines() if re.search(r"MG_START|MG_END|FISH|COLLECT|CAST|ROD|STAT", l)]
note("notice", "e2e игра", "\n".join(ev[-140:]))
note("notice", "e2e макрос", "\n".join(app.splitlines()[-160:]))
sys.exit(0 if ok else 1)
