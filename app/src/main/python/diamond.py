"""Поиск белого ромба («кнопка сбора» в Slayers 2) на кадре. Чистый numpy/cv2 — проверяется без телефона."""
from __future__ import annotations

import cv2
import numpy as np

WHITE = 190          # все три канала не темнее этого
FILL_LO, FILL_HI = 0.38, 0.66   # площадь выпуклой оболочки / площадь рамки; у ромба ≈ 0.5, у квадрата 1.0, у круга 0.79


def find_diamonds(bgr: np.ndarray, min_side: int = 5, max_side: int | None = None):
    """Список (cx, cy, w, h) белых ромбов. Квадраты (шар миниигры), круги, полосы и текст отсеиваются формой."""
    h_img = bgr.shape[0]
    max_side = max_side or max(12, int(0.28 * h_img))
    m = cv2.inRange(bgr, (WHITE, WHITE, WHITE), (255, 255, 255))
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    res = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cnts = res[0] if len(res) == 2 else res[1]
    out = []
    for c in cnts:
        x, y, w, h = cv2.boundingRect(c)
        if not (min_side <= w <= max_side and min_side <= h <= max_side):
            continue
        if not 0.68 <= w / float(h) <= 1.47:
            continue
        hull = cv2.convexHull(c)
        ha = cv2.contourArea(hull)
        if ha < FILL_LO * w * h or ha > FILL_HI * w * h:
            continue
        peri = cv2.arcLength(hull, True)
        ap = cv2.approxPolyDP(hull, 0.1 * peri, True)
        if len(ap) != 4:
            continue
        # вершины должны лежать у середин сторон рамки (а не по углам, как у наклонного прямоугольника)
        mids = ((x + w / 2, y), (x + w, y + h / 2), (x + w / 2, y + h), (x, y + h / 2))
        pts = ap.reshape(-1, 2).astype(float)
        tol = 0.28 * max(w, h)
        if not all(min(np.hypot(px - mx, py - my) for px, py in pts) <= tol for mx, my in mids):
            continue
        out.append((x + w / 2.0, y + h / 2.0, w, h))
    return out
