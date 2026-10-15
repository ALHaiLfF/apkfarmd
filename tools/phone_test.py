"""Дымовой тест питон-части телефона с поддельным мостом Kotlin (без Android)."""
import json, os, sys, tempfile, time, urllib.request
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "app", "src", "main", "python"))


class FakeBridge:
    W, H = 2400, 1080

    def __init__(self):
        self.calls = []
        self.access = True
        self.capture = True
        self.pkg = "com.roblox.client"
        self.frame = np.zeros((self.H, self.W, 4), np.uint8)
        self.frame[..., 3] = 255
        self.frame[300:340, 1800:1840, :3] = 240   # «шар»

    def status(self):
        return json.dumps({"access": self.access, "capture": self.capture, "pkg": self.pkg, "w": self.W, "h": self.H})

    def captureReady(self): return self.capture
    def screenSize(self): return [self.W, self.H]
    def displaySize(self): return [self.W, self.H]
    def foregroundPkg(self): return self.pkg

    def grab(self, x, y, w, h):
        self.calls.append(("grab", x, y, w, h))
        return self.frame[y:y + h, x:x + w].tobytes()

    def thumb(self, w, h):
        g = self.frame[::self.H // h, ::self.W // w, 1][:h, :w]
        return g.astype(np.uint8).tobytes()

    def scaled(self, w, h):
        ys = (np.arange(h) * self.H // h); xs = (np.arange(w) * self.W // w)
        return self.frame[ys][:, xs].tobytes()

    def tap(self, x, y, ms): self.calls.append(("tap", x, y, ms)); return True
    def hold(self, x, y, down): self.calls.append(("hold", x, y, down))
    def releaseAll(self): self.calls.append(("release",))
    def holdMethod(self, m): self.calls.append(("method", m))
    def holdFor(self, x, y, ms): self.calls.append(("holdFor", x, y, ms)); return True
    def launchGame(self, needle="roblox"): self.calls.append(("launch",)); self.pkg = "com.roblox.client"; return True


def get(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.read(), r.headers.get("Content-Type")


def post(url, body=None):
    req = urllib.request.Request(url, data=json.dumps(body or {}).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


def main():
    import android_world as aw
    fb = FakeBridge()
    aw.set_bridge(fb)
    tmp = tempfile.mkdtemp()
    import glue
    port = glue.boot(tmp)
    base = f"http://127.0.0.1:{port}"
    u = glue.url()
    k = u.split("k=")[1]
    # без ключа — нельзя даже локально
    try:
        get(f"{base}/api/state"); raise SystemExit("FAIL: открыто без ключа")
    except urllib.error.HTTPError as e:
        assert e.code == 403, e.code
    st = json.loads(get(f"{base}/api/state?k={k}")[0])
    assert st["phone"]["access"] and st["phone"]["capture"] and not st["phone"]["cast"], st["phone"]
    r = post(f"{base}/api/toggle?k={k}")
    assert r["ok"] is False and "заброса" in r["error"], r
    glue.point_picked("cast", 0.56, 0.26)
    glue.point_picked("collect", 0.5, 0.4)
    glue.point_picked("rod", 0.3, 0.9)
    assert glue.toggle() == "" and glue.is_running()
    time.sleep(2.0)
    kinds = [c[0] for c in fb.calls]
    print("calls:", {kk: kinds.count(kk) for kk in set(kinds)})
    assert "tap" in kinds, "должен был забросить"
    tap = next(c for c in fb.calls if c[0] == "tap")
    assert abs(tap[1] - 0.56 * 2400) < 2 and abs(tap[2] - 0.26 * 1080) < 2, tap
    jpg, ct = get(f"{base}/api/frame.jpg?k={k}")
    assert ct == "image/jpeg" and jpg[:2] == b"\xff\xd8", ct
    st = json.loads(get(f"{base}/api/state?k={k}")[0])
    print("phase:", st["phase"], "| log:", [e["m"] for e in st["log"]][-4:])
    html = get(f"{base}/?k={k}")[0].decode()
    assert "setup" in html and "Android" in html
    # потеря фокуса -> возвращает игру
    fb.pkg = "com.android.launcher"
    time.sleep(3.5)
    assert ("launch",) in fb.calls, "должен был вернуть Roblox"
    assert glue.toggle() == "" and not glue.is_running()
    assert ("release",) in fb.calls
    print("OK")
    sys.stdout.flush(); os._exit(0)


if __name__ == "__main__":
    main()
