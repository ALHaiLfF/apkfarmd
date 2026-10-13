"""Поиск кнопки сбора Slayers 2 на кадре: белый кружок с рукой, который при вращении становится ромбом;
справа от него тёмная плашка «<рыба> / Collect». Проверено на реальной записи экрана телефона."""
from __future__ import annotations

import cv2
import numpy as np

WHITE = 215                       # все три канала не темнее (кадр может быть уменьшен — края мягче)
SIDE_LO, SIDE_HI = 0.06, 0.17     # размер иконки в долях высоты экрана (на записи 0.08–0.12)
FILL_LO, FILL_HI = 0.36, 0.82     # заполнение рамки: ромб с рукой ≈0.44, кружок ≈0.67, повёрнутый квадрат — между
DARK_MIN = 0.35                   # доля тёмных пикселей справа (плашка с названием)


def find_collect_icon(bgr: np.ndarray, avoid=()):
    """Список (cx, cy, w, h, score), лучший первым. avoid — [(x, y)] где не искать (кнопка заброса: она тоже белая)."""
    H, W = bgr.shape[:2]
    m = cv2.inRange(bgr, (WHITE, WHITE, WHITE), (255, 255, 255))
    k = max(3, int(0.006 * H) | 1)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((k, k), np.uint8))
    n, _lab, st, cen = cv2.connectedComponentsWithStats(m)
    out = []
    for i in range(1, n):
        x, y, w, h, a = (int(v) for v in st[i])
        if not (SIDE_LO * H <= w <= SIDE_HI * H and SIDE_LO * H <= h <= SIDE_HI * H):
            continue
        if not 0.7 <= w / float(h) <= 1.43:
            continue
        fill = a / float(w * h)
        if not FILL_LO <= fill <= FILL_HI:
            continue
        cx, cy = x + w / 2.0, y + h / 2.0
        if any(abs(cx - ax) < 0.1 * H and abs(cy - ay) < 0.1 * H for ax, ay in avoid):
            continue
        x0, x1 = int(cx + 0.55 * w), int(min(W, cx + 3.4 * w))
        y0, y1 = int(max(0, cy - 0.35 * h)), int(cy + 0.35 * h)
        reg = bgr[y0:y1, x0:x1]
        dark = float((reg.max(axis=2) < 120).mean()) if reg.size else 0.0
        if dark < DARK_MIN:
            continue
        out.append((cx, cy, w, h, dark))
    out.sort(key=lambda c: -c[4])
    return out
