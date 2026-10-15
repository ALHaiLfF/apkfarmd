"""Нажимает кнопку на экране эмулятора по тексту/ид: ui_tap.py <xml> <подстрока>[,<подстрока>...]. Печатает 'x y' и выходит с 0, если нашла."""
import re, sys
xml = open(sys.argv[1], encoding="utf-8", errors="ignore").read()
needles = [n.strip().lower() for n in sys.argv[2].split(",")]
for m in re.finditer(r"<node [^>]*>", xml):
    node = m.group(0)
    t = re.search(r'text="([^"]*)"', node)
    rid = re.search(r'resource-id="([^"]*)"', node)
    b = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', node)
    hay = ((t.group(1) if t else "") + " " + (rid.group(1) if rid else "")).lower()
    if b and any(n in hay for n in needles):
        x0, y0, x1, y1 = map(int, b.groups())
        print((x0 + x1) // 2, (y0 + y1) // 2)
        sys.exit(0)
sys.exit(1)
