import os, sys
import cv2, numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app", "src", "main", "python"))
import diamond

def canvas():
    img = np.full((288, 640, 3), (160, 90, 20), np.uint8)       # синяя вода
    return img

def label(img, cx, cy, h=28, w=110):
    cv2.rectangle(img, (cx + 20, cy - h // 2), (cx + 20 + w, cy + h // 2), (70, 55, 40), -1)
    cv2.putText(img, "Collect", (cx + 30, cy + 6), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

def circle_icon(img, cx, cy, r=22):
    label(img, cx, cy); cv2.circle(img, (cx, cy), r, (250, 250, 250), -1); cv2.circle(img, (cx, cy), 7, (60, 60, 60), -1)

def diamond_icon(img, cx, cy, r=20, rot=0.0):
    a = np.deg2rad(rot)
    pts = np.array([[cx + r*np.cos(a+k*np.pi/2), cy + r*np.sin(a+k*np.pi/2)] for k in range(4)], np.int32)
    label(img, cx, cy); cv2.fillPoly(img, [pts], (250, 250, 250)); cv2.circle(img, (cx, cy), 7, (60, 60, 60), -1)

ok = True
def check(name, img, expect, avoid=()):
    global ok
    r = diamond.find_collect_icon(img, avoid)
    good = (len(r) >= 1) == expect
    ok &= good
    print(("OK  " if good else "FAIL"), name, [(round(c[0]), round(c[1])) for c in r][:3])

i = canvas(); circle_icon(i, 200, 150); check("кружок с рукой и плашкой", i, True)
i = canvas(); diamond_icon(i, 200, 150); check("ромб", i, True)
i = canvas(); diamond_icon(i, 200, 150, rot=20); check("повёрнутый (крутится)", i, True)
i = canvas(); circle_icon(i, 200, 150, 8); check("слишком мелкий — не берём", i, False)
i = canvas(); cv2.circle(i, (200, 150), 24, (250, 250, 250), -1); check("белый кружок без плашки (кнопка заброса, блик) — не берём", i, False)
i = canvas(); circle_icon(i, 580, 71); check("у точки заброса — не берём", i, False, avoid=[(580, 71)])
i = canvas(); cv2.rectangle(i, (380,130), (420,170), (250,250,250), -1); check("квадрат (шар миниигры) — не берём", i, False)
i = canvas(); check("пустой кадр", i, False)
print("ВСЁ ХОРОШО" if ok else "ЕСТЬ ПРОВАЛЫ"); sys.exit(0 if ok else 1)
