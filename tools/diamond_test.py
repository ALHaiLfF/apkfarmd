import os, sys, time
import cv2, numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app", "src", "main", "python"))
import diamond

def canvas(): 
    img = np.full((288, 640, 3), 40, np.uint8)
    cv2.putText(img, "COLLECT 12:34 abc", (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
    return img

def dia(img, cx, cy, r, fill=True, rot=0.0):
    a = np.deg2rad(rot)
    pts = np.array([[cx + r*np.cos(a+k*np.pi/2), cy + r*np.sin(a+k*np.pi/2)] for k in range(4)], np.int32)
    if fill: cv2.fillPoly(img, [pts], (250, 250, 250))
    else: cv2.polylines(img, [pts], True, (250, 250, 250), 3)

ok = True
def check(name, img, expect):
    global ok
    r = diamond.find_diamonds(img, 4)
    good = (len(r) >= 1) == expect
    ok &= good
    print(("OK  " if good else "FAIL"), name, [(round(x), round(y), w, h) for x, y, w, h, *_ in r][:3])

i = canvas(); dia(i, 400, 150, 22); check("ромб заполненный", i, True)
i = canvas(); dia(i, 400, 150, 22, fill=False); check("ромб контуром", i, True)
i = canvas(); dia(i, 400, 150, 22); cv2.circle(i, (400,150), 6, (60,60,60), -1); check("ромб с иконкой", i, True)
i = canvas(); dia(i, 300, 100, 14); check("маленький ромб", i, True)
i = canvas(); dia(i, 400, 150, 22, rot=8); check("слегка повёрнут (крутится)", i, True)
i = canvas(); cv2.rectangle(i, (380,130), (420,170), (250,250,250), -1); check("квадрат (шар миниигры) — не ромб", i, False)
i = canvas(); cv2.circle(i, (400,150), 22, (250,250,250), -1); check("круг — не ромб", i, False)
i = canvas(); cv2.rectangle(i, (100,100), (110,250), (250,250,250), -1); check("полоса — не ромб", i, False)
i = canvas(); check("только текст — не ромб", i, False)
print("ВСЁ ХОРОШО" if ok else "ЕСТЬ ПРОВАЛЫ"); sys.exit(0 if ok else 1)
