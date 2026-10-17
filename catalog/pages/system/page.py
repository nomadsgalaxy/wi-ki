"""The system page: my desktop's resources, live. The CPU with a pixel column per thread, its total, temperature and the
last two minutes as a graph; the GPU's load, temperature, power, VRAM and graph; memory, swap, disk, network, load and
uptime; and a line for the kiosk itself.

The desktop's feed/sysfeed.py streams a sample every 2 seconds through sink.py, which keeps the latest in RAM
(/dev/shm/kiosk-system.json). The page redraws whenever a new one lands.

Options (in playlist.json): file, where the sink writes (default /dev/shm/kiosk-system.json).
"""
import json, os, time
from datetime import datetime
from PIL import Image, ImageDraw

from kit import SCREEN, O, W, G, D, A, BG, RULE, RAISED, text, masthead, packed, level, meter

TOP, MARGIN = 98, 16
PANELS = [(16, 776), (784, 1352), (1360, 1904)]   # CPU, GPU, everything else
STALE = 10   # seconds without a sample before the page says so


def rate(b):
    """bytes a second, short"""
    for unit in ("B", "KB", "MB", "GB"):
        if b < 1000 or unit == "GB":
            return f"{b:.0f} {unit}/s" if unit == "B" or b >= 100 else f"{b:.1f} {unit}/s"
        b /= 1000


def since(seconds):
    d, h, m = int(seconds // 86400), int(seconds % 86400 // 3600), int(seconds % 3600 // 60)
    return f"{d}d {h}h" if d else f"{h}h {m}m"


def graph(d, x, y, w, h, hist, samples=60):
    """the last samples (0-100) as a pixel area chart, newest on the right, in 4 px cells"""
    col, cells = w // samples, h // 4
    d.rectangle((x, y, x + col * samples - 1, y + h - 1), fill=BG)
    for i, v in enumerate(hist[-samples:]):
        cx = x + (samples - len(hist[-samples:]) + i) * col
        lit = max(1, round(max(0, min(100, v)) / 100 * cells))
        d.rectangle((cx, y + h - lit * 4, cx + col - 2, y + h - 1), fill=RULE)
        d.rectangle((cx, y + h - lit * 4, cx + col - 2, y + h - lit * 4 + 3), fill=level(v))


def kiosk_stats():
    """this Pi: (temperature °C, load, memory used %), whatever can be read"""
    try:
        temp = int(open("/sys/class/thermal/thermal_zone0/temp").read()) / 1000
    except (OSError, ValueError):
        temp = None
    try:
        m = dict(l.split(":", 1) for l in open("/proc/meminfo"))
        mem = 100 - int(m["MemAvailable"].split()[0]) / int(m["MemTotal"].split()[0]) * 100
    except (OSError, KeyError, ValueError):
        mem = None
    return temp, os.getloadavg()[0], mem


def draw(now, s, note=None, pi=(None, 0.0, None)):
    """the whole page, 1920x515 RGB"""
    img = Image.new("RGB", SCREEN, BG); d = ImageDraw.Draw(img)
    masthead(img, now, "// 05 · SYSTEM", (s or {}).get("host", "THE DESKTOP").upper()[:30], note)
    for x0, x1 in PANELS:
        d.rectangle((x0, TOP, x1, SCREEN[1] - 8), fill=RAISED, outline=RULE)
    if not s:
        text(img, (PANELS[0][0] + 14, TOP + 10), "waiting for the desktop", A)
        return img
    num = lambda k, default=0: s.get(k) if isinstance(s.get(k), (int, float)) else default

    # CPU: total and temperature, a column per thread, two minutes of history
    x, R = PANELS[0][0] + 14, PANELS[0][1] - 14
    text(img, (x, TOP + 10), "CPU", O)
    text(img, (R, TOP + 18), str(s.get("model", ""))[:40], G, scale=1, right=True)
    cpu = num("cpu")
    wide = text(img, (x, TOP + 46), f"{round(cpu)}%", level(cpu), scale=4)
    if s.get("cpu_temp") is not None:
        text(img, (x + wide + 24, TOP + 62), f"{round(num('cpu_temp'))}°C", level(num("cpu_temp")))
    text(img, (R, TOP + 62), f"load {num('load'):.2f}", G, right=True)
    threads = [t for t in s.get("threads") or [] if isinstance(t, (int, float))][:48]
    if threads:
        pitch = (R - x) // len(threads); cells, top = 16, TOP + 122
        for i, t in enumerate(threads):
            lit = round(max(0, min(100, t)) / 100 * cells)
            for c in range(cells):
                y = top + (cells - 1 - c) * 8
                d.rectangle((x + i * pitch, y, x + (i + 1) * pitch - 5, y + 5), fill=level(t) if c < lit else RULE)
    text(img, (x, TOP + 260), "LAST 2 MIN", G, scale=1)
    graph(d, x, TOP + 280, R - x, 112, s.get("cpu_hist") or [])

    # GPU
    x, R = PANELS[1][0] + 14, PANELS[1][1] - 14
    text(img, (x, TOP + 10), "GPU", O)
    g = s.get("gpu") if isinstance(s.get("gpu"), dict) else None
    if g:
        text(img, (R, TOP + 18), str(g.get("name", ""))[:34], G, scale=1, right=True)
        util = g.get("util") or 0
        wide = text(img, (x, TOP + 46), f"{round(util)}%", level(util), scale=4)
        text(img, (x + wide + 24, TOP + 62), f"{round(g.get('temp') or 0)}°C", level(g.get("temp") or 0))
        text(img, (R, TOP + 62), f"{round(g.get('power') or 0)} W", G, right=True)
        used, total = g.get("vram_used") or 0, g.get("vram_total") or 1
        text(img, (x, TOP + 122), "VRAM", G, scale=1)
        meter(d, (x, TOP + 142), used / total * 100, blocks=20, block=16)
        text(img, (R, TOP + 142), f"{used:.1f}/{total:.0f} GB", W, scale=1, right=True)
    else:
        text(img, (x, TOP + 50), "no GPU reported", D, scale=1)
    text(img, (x, TOP + 260), "LAST 2 MIN", G, scale=1)
    graph(d, x, TOP + 280, R - x, 112, s.get("gpu_hist") or [])

    # everything else: one row each
    x, R = PANELS[2][0] + 14, PANELS[2][1] - 14
    y = TOP + 14
    for label, used, total, unit in (("MEMORY", num("mem_used"), num("mem_total", 1), "GB"),
                                     ("SWAP", num("swap_used"), num("swap_total", 0), "GB"),
                                     ("DISK", num("disk_used"), num("disk_total", 1), "GB")):
        extra = f"  {round(num('disk_temp'))}°C" if label == "DISK" and s.get("disk_temp") is not None else ""
        text(img, (x, y), label, G, scale=1)
        text(img, (R, y), f"{used:g}/{total:g} {unit}{extra}", W, scale=1, right=True)
        meter(d, (x, y + 20), used / total * 100 if total else 0, blocks=32, block=16)
        y += 54
    text(img, (x, y), "NETWORK", G, scale=1)
    text(img, (R, y), str(s.get("iface", ""))[:16], D, scale=1, right=True)
    text(img, (x, y + 20), f"↓ {rate(num('rx'))}", O); text(img, (x + 256, y + 20), f"↑ {rate(num('tx'))}", O)
    y += 64
    text(img, (x, y), "UP", G, scale=1); text(img, (x + 32, y), since(num("uptime")), W, scale=1)
    d.rectangle((x, SCREEN[1] - 58, R, SCREEN[1] - 58), fill=RULE)
    temp, load, mem = pi
    bits = [f"{round(temp)}°C" if temp is not None else None, f"load {load:.2f}", f"mem {round(mem)}%" if mem is not None else None]
    text(img, (x, SCREEN[1] - 46), "THIS KIOSK", G, scale=1)
    text(img, (x, SCREEN[1] - 28), "  ·  ".join(b for b in bits if b), level(temp or 0) if temp and temp >= 50 else W, scale=1)
    return img


class Page:
    """the desktop's resources, as a page of the kiosk's cycle"""
    name, seconds = "system", 20

    def __init__(self, file="/dev/shm/kiosk-system.json"):
        self.file, self.bg, self.data = file, (None, None), None

    def active(self):
        """skipped while the desktop's away: the sink removes the file when the stream ends, and a stuck one goes stale"""
        try:
            return time.time() - os.path.getmtime(self.file) <= STALE
        except OSError:
            return False

    def start(self, now):
        pass   # background() reads each new sample as it lands

    def background(self, now):
        mtime = os.path.getmtime(self.file) if os.path.exists(self.file) else None
        age = time.time() - mtime if mtime else None
        stale = age is not None and age > STALE
        key = (mtime, now.minute, stale)
        if key != self.bg[0]:
            try:
                self.data = json.load(open(self.file)) if mtime else None
            except (OSError, ValueError):
                pass   # half written: keep the last sample
            note = ("waiting for the desktop", A) if not self.data else \
                (f"no update for {round(age)} s", A) if stale else ("live · every 2 s", D)
            self.bg = (key, packed(draw(now, self.data, note, kiosk_stats())))
        return self.bg

    def regions(self, now, t):
        return []   # it all changes together, every 2 seconds


SAMPLE = {"cpu": 37.4, "threads": [92, 71, 64, 40, 33, 20, 15, 9, 8, 5, 4, 6, 80, 55, 13, 6, 3, 3, 1, 2, 3, 1, 3, 8],
          "rx": 1234567, "tx": 18505, "iface": "enp5s0", "disk_used": 399, "disk_total": 987, "host": "Anthony-Desktop",
          "model": "Ryzen 9 9900X", "cpu_temp": 71.5, "disk_temp": 40.9,
          "gpu": {"name": "RTX 2070 SUPER", "util": 19.0, "temp": 53.0, "vram_used": 3.6, "vram_total": 8.0, "power": 54.6},
          "load": 2.41, "uptime": 517777, "mem_used": 19.1, "mem_total": 30.4, "swap_used": 21.3, "swap_total": 38.4,
          "cpu_hist": [20 + (i * 13) % 70 for i in range(60)], "gpu_hist": [10 + (i * 7) % 40 for i in range(45)]}


def check():
    import tempfile
    from . import sink
    sink.check()
    assert rate(512) == "512 B/s" and rate(18505) == "18.5 KB/s" and rate(1234567) == "1.2 MB/s" and rate(123e6) == "123 MB/s"
    assert since(517777) == "5d 23h" and since(3700) == "1h 1m"
    now = datetime(2026, 10, 15, 0, 30)
    broken = dict(SAMPLE, gpu=None, threads=[], cpu="x", swap_total=0, cpu_hist=None)
    for s in (SAMPLE, None, broken, {"host": "x"}):
        assert draw(now, s).size == SCREEN, "draws with, without and with broken data"
    path = os.path.join(tempfile.mkdtemp(), "system.json")
    page = Page(path)
    assert page.background(now)[1].size == SCREEN and page.data is None and not page.active(), "no stream: skipped"
    json.dump(SAMPLE, open(path, "w"))
    assert page.active(), "a live stream: shown"
    key, bg = page.background(now)
    assert bg.mode == "LA" and page.background(now)[0] == key and page.data["cpu"] == 37.4, "redrawn on each new sample"
    open(path, "w").write("{half")
    os.utime(path, (time.time() + 5, time.time() + 5)); page.background(now)
    assert page.data["cpu"] == 37.4, "a half-written sample keeps the last one"
    assert len(kiosk_stats()) == 3


def preview(now=None):
    """the page with the sample, for the emulator and kiosk.py --png"""
    return draw(now or datetime(2026, 10, 15, 0, 30), SAMPLE, ("live · every 2 s", D), (46.0, 0.82, 41.0))
