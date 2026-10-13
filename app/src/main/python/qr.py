"""Мини-генератор QR-кода (байтовый режим, уровень коррекции L, версии 1–6) -> SVG.
Нужен, чтобы телефон открывал панель наведением камеры. Без внешних библиотек."""
from __future__ import annotations

# (всего кодслов, кодслов коррекции на блок, блоков, данных на блок) для уровня L
_VER = {
    1: (26, 7, 1, 19), 2: (44, 10, 1, 34), 3: (70, 15, 1, 55),
    4: (100, 20, 1, 80), 5: (134, 26, 1, 108), 6: (172, 18, 2, 68),
}
_ALIGN = {1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34]}

_EXP = [0] * 512
_LOG = [0] * 256
_x = 1
for _i in range(255):
    _EXP[_i] = _x
    _LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D
for _i in range(255, 512):
    _EXP[_i] = _EXP[_i - 255]


def _mul(a: int, b: int) -> int:
    return 0 if a == 0 or b == 0 else _EXP[_LOG[a] + _LOG[b]]


def _rs(data: list[int], n: int) -> list[int]:
    gen = [1]
    for i in range(n):
        nxt = [0] * (len(gen) + 1)
        for j, c in enumerate(gen):
            nxt[j] ^= c
            nxt[j + 1] ^= _mul(c, _EXP[i])
        gen = nxt
    rem = [0] * n
    for b in data:
        f = b ^ rem[0]
        rem = rem[1:] + [0]
        for i in range(n):
            rem[i] ^= _mul(gen[i + 1], f)
    return rem


def _bch_format(bits5: int) -> int:
    v = bits5 << 10
    for i in range(14, 9, -1):
        if v & (1 << i):
            v ^= 0x537 << (i - 10)
    return ((bits5 << 10) | v) ^ 0x5412


def make_matrix(text: str) -> list[list[int]]:
    data = text.encode("utf-8")
    ver = next((v for v in _VER if _VER[v][2] * _VER[v][3] - 2 >= len(data)), None)
    if ver is None:
        raise ValueError("слишком длинная ссылка для QR")
    total, ec_len, blocks, dpb = _VER[ver]
    cap = blocks * dpb
    bits = "0100" + format(len(data), "08b") + "".join(format(b, "08b") for b in data)
    bits += "0" * min(4, cap * 8 - len(bits))
    bits += "0" * (-len(bits) % 8)
    cw = [int(bits[i:i + 8], 2) for i in range(0, len(bits), 8)]
    pad = [0xEC, 0x11]
    while len(cw) < cap:
        cw.append(pad[(len(cw) - len(bits) // 8) % 2])
    chunks = [cw[i * dpb:(i + 1) * dpb] for i in range(blocks)]
    ecs = [_rs(c, ec_len) for c in chunks]
    final: list[int] = []
    for i in range(dpb):
        for c in chunks:
            final.append(c[i])
    for i in range(ec_len):
        for e in ecs:
            final.append(e[i])
    stream = "".join(format(b, "08b") for b in final) + "0" * (7 if ver >= 2 else 0)

    n = 17 + 4 * ver
    m = [[None] * n for _ in range(n)]

    def put(r, c, v):
        if 0 <= r < n and 0 <= c < n:
            m[r][c] = v

    def finder(r0, c0):
        for dr in range(-1, 8):
            for dc in range(-1, 8):
                inside = 0 <= dr <= 6 and 0 <= dc <= 6
                dark = inside and (dr in (0, 6) or dc in (0, 6) or (2 <= dr <= 4 and 2 <= dc <= 4))
                put(r0 + dr, c0 + dc, 1 if dark else 0)

    finder(0, 0)
    finder(0, n - 7)
    finder(n - 7, 0)
    for i in range(8, n - 8):
        put(6, i, 1 if i % 2 == 0 else 0)
        put(i, 6, 1 if i % 2 == 0 else 0)
    pos = _ALIGN[ver]
    for r in pos:
        for c in pos:
            if (r == 6 and c == 6) or (r == 6 and c == pos[-1]) or (r == pos[-1] and c == 6):
                continue
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    put(r + dr, c + dc, 1 if max(abs(dr), abs(dc)) != 1 else 0)
    put(n - 8, 8, 1)  # тёмный модуль
    reserved = [[m[r][c] is not None for c in range(n)] for r in range(n)]
    for i in range(9):
        for (r, c) in ((8, i), (i, 8)):
            reserved[r][c] = True
    for i in range(8):
        reserved[8][n - 1 - i] = True
        reserved[n - 1 - i][8] = True

    # размещение данных змейкой
    k, up, c = 0, True, n - 1
    cells = []
    while c > 0:
        if c == 6:
            c -= 1
        rng = range(n - 1, -1, -1) if up else range(n)
        for r in rng:
            for cc in (c, c - 1):
                if not reserved[r][cc]:
                    cells.append((r, cc))
        up = not up
        c -= 2
    for idx, (r, cc) in enumerate(cells):
        m[r][cc] = int(stream[idx]) if idx < len(stream) else 0

    masks = [lambda r, c: (r + c) % 2 == 0, lambda r, c: r % 2 == 0, lambda r, c: c % 3 == 0,
             lambda r, c: (r + c) % 3 == 0, lambda r, c: (r // 2 + c // 3) % 2 == 0,
             lambda r, c: (r * c) % 2 + (r * c) % 3 == 0, lambda r, c: ((r * c) % 2 + (r * c) % 3) % 2 == 0,
             lambda r, c: ((r + c) % 2 + (r * c) % 3) % 2 == 0]

    def penalty(g):
        p = 0
        for line in list(g) + [list(col) for col in zip(*g)]:
            run = 1
            for i in range(1, n):
                if line[i] == line[i - 1]:
                    run += 1
                else:
                    if run >= 5:
                        p += run - 2
                    run = 1
            if run >= 5:
                p += run - 2
        for r in range(n - 1):
            for c in range(n - 1):
                if g[r][c] == g[r + 1][c] == g[r][c + 1] == g[r + 1][c + 1]:
                    p += 3
        dark = sum(sum(row) for row in g)
        p += abs(dark * 20 - n * n * 10) // (n * n) * 10
        return p

    best = None
    for mi, fn in enumerate(masks):
        g = [[(m[r][c] ^ (1 if (not reserved[r][c] and fn(r, c)) else 0)) if m[r][c] is not None else 0
              for c in range(n)] for r in range(n)]
        fmt = _bch_format((0b01 << 3) | mi)  # уровень L = 01
        bitsf = [(fmt >> i) & 1 for i in range(15)]
        for i in range(6):
            g[i][8] = bitsf[i]
        g[7][8], g[8][8], g[8][7] = bitsf[6], bitsf[7], bitsf[8]
        for i in range(9, 15):
            g[8][14 - i] = bitsf[i]
        for i in range(8):
            g[8][n - 1 - i] = bitsf[i]
        for i in range(8, 15):
            g[n - 15 + i][8] = bitsf[i]
        sc = penalty(g)
        if best is None or sc < best[0]:
            best = (sc, g)
    return best[1]


def make_svg(text: str, scale: int = 6, border: int = 3) -> str:
    g = make_matrix(text)
    n = len(g)
    size = (n + 2 * border) * scale
    path = "".join(f"M{(c + border) * scale},{(r + border) * scale}h{scale}v{scale}h-{scale}z"
                   for r in range(n) for c in range(n) if g[r][c])
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" shape-rendering="crispEdges">'
            f'<rect width="{size}" height="{size}" fill="#fff"/><path d="{path}" fill="#1b1035"/></svg>')
