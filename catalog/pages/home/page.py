"""The home page: where a touch screen goes when someone touches it. A tile for every page in the playlist, each with a
picture of that page as it is now, and its name; touching a tile opens that page (kiosk.py's route()). It's never in
the rotation, so a screen nobody can touch never shows it.

kiosk.py hands it the playlist's pages (pages). The pictures are the pages' own backgrounds, shrunk, made again every
minute. On a Pi Zero drawing every page would take too long, so there the tiles are just names.
"""
import os
from datetime import datetime, timedelta
from PIL import Image, ImageDraw

import kit
from kit import SCREEN, O, W, G, D, A, BG, RULE, text, clock, packed

TITLES = {"weather": "Weather", "github": "GitHub", "agents": "Agents", "nowplaying": "Now Playing", "system": "System",
          "radar": "Flight Radar", "calendar": "Calendar", "cfradar": "Cloudflare Radar", "septa": "SEPTA",
          "halflife3": "Half-Life 3", "flyers": "Flyers", "around": "Around", "around-311": "Around · 311",
          "around-building": "Around · Building", "around-bikes": "Around · Bikes", "sports": "Sports"}
SLOW = os.uname().machine.startswith("arm")
COLS, TOP, GAP, MARGIN = 5, 64, 14, 20
TILE_BG, TILE_EDGE = (20, 24, 40), (52, 58, 80)


def title(name):
    return TITLES.get(name, name.replace("-", " ").title())


def grid(count):
    """the tiles' boxes, (x0, y0, x1, y1), filling the screen under the header in COLS columns"""
    rows = max(1, -(-count // COLS))
    w = (SCREEN[0] - 2 * MARGIN - (COLS - 1) * GAP) // COLS
    h = (SCREEN[1] - TOP - MARGIN - (rows - 1) * GAP) // rows
    return [(MARGIN + i % COLS * (w + GAP), TOP + i // COLS * (h + GAP),
             MARGIN + i % COLS * (w + GAP) + w, TOP + i // COLS * (h + GAP) + h) for i in range(count)]


def draw(now, names, pictures, pictured=True, made=None, stale=()):
    """the whole page, RGB: names are the pages' names, pictures {name: RGB picture} for the ones that have one, made the
    time the oldest of them was drawn (default now), stale the names whose picture is an old one because the page couldn't
    draw again (their tile gets an amber edge and "old")"""
    img = Image.new("RGB", SCREEN, BG); d = ImageDraw.Draw(img)
    text(img, (MARGIN, 14), "HOME", O, scale=2)
    text(img, (MARGIN + 5 * 16 + 8, 22), "tap a page to open it · it goes back to rotating after a minute alone", G, scale=1)
    text(img, (SCREEN[0] - MARGIN, 14), clock(now), W, scale=2, right=True)
    text(img, (SCREEN[0] - MARGIN, 44), f"updated {clock(made or now)}" if pictured else "names only", G, scale=1, right=True)
    for name, (x0, y0, x1, y1) in zip(names, grid(len(names))):
        d.rounded_rectangle((x0, y0, x1, y1), radius=10, fill=TILE_BG, outline=A if name in stale else TILE_EDGE, width=2)
        pic = pictures.get(name)
        label_h = 38
        if pic is not None:
            w, h = x1 - x0 - 12, y1 - y0 - 12 - label_h
            fit = min(w / pic.width, h / pic.height)
            small = pic.resize((max(1, round(pic.width * fit)), max(1, round(pic.height * fit))), Image.BILINEAR)
            img.paste(small, (x0 + 6 + (w - small.width) // 2, y0 + 6))
            text(img, (x0 + 10, y1 - label_h + 4), title(name)[:(x1 - x0 - 20) // 16], W, scale=2)
            if name in stale:
                text(img, (x1 - 10, y1 - label_h + 12), "old", A, scale=1, right=True)
        else:
            sc = 3 if len(title(name)) * 24 <= x1 - x0 - 20 else 2   # as big as fits
            label = title(name)[:(x1 - x0 - 20) // (8 * sc)]
            text(img, (x0 + (x1 - x0 - len(label) * 8 * sc) // 2, (y0 + y1) // 2 - 8 * sc), label, W, scale=sc)
    return img


class Page:
    """the home page: kiosk.py fills in pages"""
    name, seconds = "home", 60

    def __init__(self):
        self.pages, self.pictures, self.made, self.bg = [], {}, {}, (None, None)
        self.keys, self.stale = {}, set()   # each page's last frame key (an unchanged frame keeps its time); pages whose last draw failed
        self.shown = []   # the names on the tiles of the finished frame: a touch goes to what's on the screen

    def active(self):
        return False   # never in the rotation: only a touch brings it up

    def others(self):
        return [p for p in self.pages if p is not self]

    def start(self, now):
        pass

    def touch(self, x, y):
        """the name of the page whose tile was touched, for kiosk.py to open"""
        for name, (x0, y0, x1, y1) in zip(self.shown, grid(len(self.shown))):
            if x0 <= x <= x1 and y0 <= y <= y1:
                return name
        return None

    def background(self, now):
        key = (now.minute, tuple(p.name for p in self.others()))
        if key != self.bg[0]:
            shown = [p.name for p in self.others()]
            if not SLOW:   # each page as it is now, shrunk; a page that can't draw just gets its name
                for p in self.others():
                    try:
                        k, frame = p.background(now)
                        if k != self.keys.get(p.name) or p.name not in self.pictures:   # the same frame again is no newer
                            self.pictures[p.name] = kit.unpack(frame); self.made[p.name] = now; self.keys[p.name] = k
                        self.stale.discard(p.name)
                    except Exception:
                        self.stale.add(p.name)   # keeps its last picture; the tile and the corner show how old it is
            for old in (self.pictures, self.made, self.keys):   # only the tiles on the screen are kept
                for name in [n for n in old if n not in shown]:
                    del old[name]
            self.stale &= set(shown)
            self.bg = (key, packed(draw(now, shown, self.pictures, not SLOW, min(self.made.values(), default=None), self.stale)))
            self.shown = shown   # only with its frame: a draw that raised leaves the touch targets of the frame still up
        return self.bg

    def regions(self, now, t):
        return []


def check():
    now = datetime(2026, 10, 15, 17, 30)
    boxes = grid(15)
    assert len(boxes) == 15 and boxes[-1][2] <= SCREEN[0] and boxes[-1][3] <= SCREEN[1] and boxes[0][1] >= TOP
    assert all(b[2] < c[0] or b[1] != c[1] for b, c in zip(boxes, boxes[1:])), "tiles in a row don't overlap"
    assert grid(1)[0][3] <= SCREEN[1]

    class Fake:
        def __init__(self, name, colour=(200, 40, 40)):
            self.name, self.colour, self.key = name, colour, 0
        def background(self, now):
            return self.key, packed(Image.new("RGB", SCREEN, self.colour))
    home = Page(); home.pages = [Fake("weather"), Fake("septa"), home]
    assert home.active() is False, "never in the rotation"
    key, bg = home.background(now)
    assert bg.mode == "LA" and home.background(now)[0] == key
    x0, y0, x1, y1 = grid(2)[1]
    assert home.touch((x0 + x1) // 2, (y0 + y1) // 2) == "septa" and home.touch(5, 5) is None, "a tile opens its page"
    assert draw(now, ["weather", "around-bikes"], {}, False).size == SCREEN, "names only, as on the Pi"
    # the Pi: no pictures, only names, through background() itself
    global SLOW
    real_slow, SLOW = SLOW, True
    try:
        pi = Page(); pi.pages = [Fake("weather"), Fake("septa"), pi]
        assert pi.background(now)[1].size == SCREEN and pi.pictures == {} and pi.shown == ["weather", "septa"]
    finally:
        SLOW = real_slow
    # the pictures are bounded to the tiles shown, and the corner says how old the oldest picture is
    class Flaky(Fake):
        def background(self, now):
            if self.broken: raise OSError("down")
            return Fake.background(self, now)
    a, b = Flaky("weather"), Flaky("septa"); a.broken = b.broken = False
    h = Page(); h.pages = [a, b, h]; h.background(now)
    a.key = b.key = 1   # drawn again, differently
    assert set(h.pictures) == {"weather", "septa"} and set(h.made) == {"weather", "septa"}
    h.pages = [a, h]; h.background(now.replace(minute=31))
    assert set(h.pictures) == {"weather"} and set(h.made) == {"weather"} and h.made["weather"] == now.replace(minute=31), "a page that left the playlist leaves the cache"
    # the same frame again (same key) is no newer: "updated" keeps the old time
    h.background(now.replace(minute=32)); assert h.made["weather"] == now.replace(minute=31) and not h.stale
    b2 = now.replace(minute=45); a.broken = True; h.background(b2)
    assert h.stale == {"weather"}, "a tile whose page can't draw is marked old"
    assert draw(b2, ["weather"], h.pictures, True, None, {"weather"}).tobytes() != draw(b2, ["weather"], h.pictures, True).tobytes()
    assert Page().stale == set() and preview(pictured=False).size == SCREEN, "the Pi's names-only render"
    assert "weather" in h.pictures and h.made["weather"] == now.replace(minute=31), "a page that can't draw keeps its last picture, with its time"
    assert h.background(b2)[1].tobytes() == packed(draw(b2, ["weather"], h.pictures, True, now.replace(minute=31), h.stale)).tobytes(), \
        "the page's corner says when its oldest picture was drawn"
    assert h.background(b2)[1].tobytes() != packed(draw(b2, ["weather"], h.pictures, True, b2, h.stale)).tobytes()
    assert draw(now, ["weather"], {}, True, now).tobytes() == draw(now, ["weather"], {}, True).tobytes()
    assert draw(now, ["weather"], {}, True, now - timedelta(minutes=14)).tobytes() != draw(now, ["weather"], {}, True).tobytes(), \
        "updated shows the age of the pictures, not the clock"
    # the tap target is the tile on the screen, even if the playlist is reordered under a page already drawn
    red, blue = Fake("weather", (255, 0, 0)), Fake("septa", (0, 0, 255))
    home = Page()
    for order in ([red, blue], [blue, red]):   # same count, same minute
        home.pages = order + [home]
        img = kit.unpack(home.background(now)[1])
        for (x0, y0, x1, y1) in grid(2):
            shown = "weather" if img.getpixel(((x0 + x1) // 2, y0 + 20))[0] > 128 else "septa"
            assert home.touch((x0 + x1) // 2, (y0 + y1) // 2) == shown, "the tap opens the page whose picture is on the tile"
    # touch targets change only with the finished frame: a draw that raises leaves the tiles that are up
    g = Page(); g.pages = [red, blue, g]; g.background(now)
    assert g.shown == ["weather", "septa"]
    g.pages = [blue, g]; real_draw = draw
    globals()["draw"] = lambda *a, **k: 1 / 0
    try:
        g.background(now.replace(minute=40)); raise AssertionError("draw should have raised")
    except ZeroDivisionError:
        assert g.shown == ["weather", "septa"], "targets stay with the frame still up"
    finally:
        globals()["draw"] = real_draw
    assert title("cfradar") != "cfradar" and all(len(title(n)) * 16 <= grid(15)[0][2] - grid(15)[0][0] - 20 for n in TITLES), "names fit at scale 2"

def preview(now=None, pictured=True):
    """the home page with a few made-up tiles, for the emulator and kiosk.py --png; pictured=False is the Pi's, names only"""
    now = now or datetime(2026, 10, 15, 17, 30)
    names = list(TITLES)
    pictures = {n: Image.new("RGB", SCREEN, (30 + 12 * i, 40, 70)) for i, n in enumerate(names)}
    return draw(now, names, pictures if pictured else {}, pictured)
