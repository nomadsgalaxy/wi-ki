"""The SEPTA page: is SEPTA fucked? The answer from isseptafucked.com (Douglas Muth's status dashboard for Philadelphia
public transit), dressed as SEPTA: the SEPTA Metro line bullets along the top, Regional Rail's verdict with a pixel
sign for it (all clear, a warning, or a dumpster fire), the buses, a station departure board of the trains running now
in SEPTA gold, and a Silverliner rolling along the track at the bottom.

The site judges Regional Rail: every train under 10 minutes late is "not fucked", one or more 10 to 29 minutes late "a
little fucked", one or more 30 minutes late "fucked". Its API (/api/status, /api/rr) asks for no more than a request
every few minutes, so this fetches every 5 minutes, in a background thread, into CACHE, which every renderer on the
machine shares. A failed fetch keeps the last one and says how old it is.

Options (in playlist.json): sfw, true to say "fcked" like the site's work-safe twin, isseptafcked.com (default false).
The colours are SEPTA's own, from septa.org's stylesheet (the line colours are its SEPTA Metro letters), and only this
page uses them.
"""
import json, math, os, tempfile, threading, time, urllib.error, urllib.request
from datetime import datetime
from PIL import Image, ImageDraw

from kit import SCREEN, W, A, text, clock, packed

API = "https://isseptafucked.com/api/"
CACHE = os.path.expanduser("~/.cache/kiosk/septa.json")
EVERY = 300
NAVY, BLUE, LIGHT, TEAL, RED = (0x20, 0x28, 0x46), (0x1f, 0x4f, 0xa3), (0x99, 0xc2, 0xff), (0x10, 0xb0, 0xaa), (0xdc, 0x35, 0x45)
GOLD, RAIL, BUS = (0xff, 0xd7, 0x00), (0x4c, 0x74, 0x8c), (0x1a, 0x18, 0x18)
LINES = [("L", (0x00, 0x97, 0xd6)), ("B", (0xf2, 0x61, 0x00)), ("T", (0x5a, 0x96, 0x0a)), ("D", (0xdc, 0x2e, 0x6b)),
         ("G", GOLD), ("M", (0x5f, 0x24, 0x9f))]
VERDICT = {"not fucked": TEAL, "a little fucked": A, "fucked": RED}
BOARD, LED_OFF = (8, 8, 12), (26, 24, 18)
SILVER, STEEL, GLASS = (196, 202, 210), (140, 146, 156), (34, 42, 66)
P = 4                                   # an art pixel, in screen pixels
TRACK_Y = SCREEN[1] - 22 * P            # the strip the train runs along
SLOW = os.uname().machine.startswith("arm")   # the Pi Zero, drawing by itself: the train moves less often
ROW = 34


def bullet(letter, colour, size=40):
    """a SEPTA Metro line bullet: the letter in white on a disc of the line's colour, RGBA"""
    img = Image.new("RGBA", (size, size)); ImageDraw.Draw(img).ellipse((0, 0, size - 1, size - 1), fill=colour)
    text(img, ((size - 16) // 2, (size - 32) // 2), letter, W if colour != GOLD else BUS, scale=2)
    return img


def sign(verdict):
    """the verdict as a 24x24 pixel sign, RGBA: a check in a teal disc, an amber warning, or a dumpster on fire"""
    img = Image.new("RGBA", (24, 24)); d = ImageDraw.Draw(img)
    if verdict == "not fucked":
        d.ellipse((0, 0, 23, 23), fill=TEAL); d.line((5, 12, 10, 17, 18, 6), fill=W, width=3)
    elif verdict == "a little fucked":
        d.polygon([(12, 0), (23, 22), (0, 22)], fill=A); d.rectangle((11, 7, 12, 15), fill=BUS); d.rectangle((11, 18, 12, 19), fill=BUS)
    elif verdict != "fucked":   # a verdict the site never gave: a grey "?", not the dumpster fire
        d.ellipse((0, 0, 23, 23), fill=STEEL); text(img, (4, 4), "?", W, scale=2)
    else:
        d.polygon([(4, 10), (7, 2), (9, 7), (12, 0), (15, 6), (17, 3), (20, 10)], fill=(0xf2, 0x61, 0x00))   # flames
        d.polygon([(7, 10), (9, 6), (12, 9), (15, 5), (17, 10)], fill=GOLD)
        d.rectangle((2, 11, 21, 23), fill=(52, 92, 64)); d.rectangle((1, 10, 22, 11), fill=(38, 70, 48))  # the dumpster
        d.line((5, 14, 5, 21), fill=(38, 70, 48)); d.line((11, 14, 11, 21), fill=(38, 70, 48)); d.line((17, 14, 17, 21), fill=(38, 70, 48))
    return img


def coach():
    """a SEPTA bus from the side, 16x10 pixels, RGBA: silver, the red and blue stripes, windows and wheels"""
    img = Image.new("RGBA", (16, 10)); d = ImageDraw.Draw(img)
    d.rectangle((0, 0, 15, 7), fill=SILVER)
    for x in (3, 7, 11):
        d.rectangle((x, 1, x + 2, 3), fill=GLASS)
    d.rectangle((0, 1, 1, 5), fill=GLASS)                        # the windscreen
    d.line((0, 5, 15, 5), fill=RED); d.line((0, 6, 15, 6), fill=BLUE)
    for x in (2, 11):
        d.rectangle((x, 7, x + 2, 9), fill=BUS)                  # wheels
    return img


def silverliner():
    """two Silverliner IV cars in pixels, coupled: stainless, the red and blue stripes, windows, doors and pantographs,
    RGBA at art size (scale it by P)"""
    car_w, h = 74, 17
    img = Image.new("RGBA", (car_w * 2 + 2, h + 3)); d = ImageDraw.Draw(img)
    for c in range(2):
        x = c * (car_w + 2)
        d.line((x + 20, 0, x + 28, 2), fill=STEEL); d.line((x + 28, 2, x + 20, 3), fill=STEEL)   # the pantograph
        d.rectangle((x, 3, x + car_w - 1, h + 1), fill=SILVER)
        d.rectangle((x, 3, x + car_w - 1, 3), fill=STEEL)                                       # roof edge
        for wx in range(x + 6, x + car_w - 6, 8):
            d.rectangle((wx, 6, wx + 5, 9), fill=GLASS)                                         # windows
        for dx in (x + 14, x + car_w - 18):
            d.rectangle((dx, 6, dx + 3, h), fill=STEEL); d.rectangle((dx + 1, 7, dx + 2, 9), fill=GLASS)   # doors
        d.rectangle((x, 11, x + car_w - 1, 11), fill=RED); d.rectangle((x, 12, x + car_w - 1, 12), fill=BLUE)   # stripes
        d.rectangle((x + 4, h + 2, x + 10, h + 2), fill=BUS); d.rectangle((x + car_w - 11, h + 2, x + car_w - 5, h + 2), fill=BUS)   # trucks
    d.rectangle((0, 5, 1, 10), fill=GLASS); d.rectangle((img.width - 2, 5, img.width - 1, 10), fill=GLASS)        # cab ends
    d.point((0, 14), fill=GOLD); d.point((img.width - 1, 14), fill=RED)                                         # head and tail lights
    return img.resize((img.width * P, img.height * P), Image.NEAREST)


TRAIN = silverliner()
LAP = SCREEN[0] + TRAIN.width   # the track is a ring this long: as the train's tail leaves on the left its nose comes in on the right
SPEED = LAP / 10                 # a lap every 10 s, so the page's 20 s is exactly two and every turn plays the same


def track():
    """the strip along the bottom: the rail line's colour, sleepers, a rail and the catenary above, RGB"""
    img = Image.new("RGB", (SCREEN[0], SCREEN[1] - TRACK_Y), NAVY); d = ImageDraw.Draw(img)
    rail_y = TRAIN.height - 2
    d.line((0, 6, SCREEN[0], 6), fill=STEEL, width=2)                                      # the catenary
    for x in range(0, SCREEN[0], 96):
        d.line((x, 6, x, 0), fill=STEEL, width=2)
    d.rectangle((0, rail_y + 2, SCREEN[0], img.height), fill=(40, 44, 58))                  # ballast
    for x in range(0, SCREEN[0], 3 * P):
        d.rectangle((x, rail_y + 2, x + P, rail_y + 2 + P), fill=(86, 70, 54))              # sleepers
    d.rectangle((0, rail_y, SCREEN[0], rail_y + 1), fill=STEEL)                            # the rail
    d.rectangle((0, img.height - P, SCREEN[0], img.height), fill=RAIL)                     # Regional Rail's colour
    return img


def trains(rr):
    """/api/rr -> [(number, from, to, minutes late or None)], the latest first, those with no delay data last. A train
    that isn't a dict is skipped, a late that isn't a number is None (unknown, not on time), not raised"""
    data = rr.get("data") if isinstance(rr, dict) else None
    rows = [(str(t.get("number", n)), str(t.get("from", "?")), str(t.get("to", "?")), minutes(t.get("late")))
            for n, t in (data.items() if isinstance(data, dict) else ()) if isinstance(t, dict)]
    return sorted(rows, key=lambda r: (r[3] is None, -(r[3] or 0), r[0]))


def minutes(late):
    """a train's whole minutes late from whatever the API sent (12, "12.5", "12 min", null, NaN): None if it isn't a number, which is not the same as on time"""
    try:
        m = float(late.split()[0] if isinstance(late, str) else late)
    except (TypeError, ValueError, IndexError):
        return None
    return int(m) if math.isfinite(m) else None


def stamp(iso):
    """an ISO time as a naive local datetime (to compare with the clock), or None if it isn't one"""
    try:
        t = datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return None
    return t.astimezone().replace(tzinfo=None) if t.tzinfo else t


def usable(data):
    """data if draw() can use it: {"status": {"status": {"rr": {...}, "bus": {...}}}, "rr": {...}, "fetched": iso}, else None"""
    try:
        st = data["status"]["status"]
        ok = isinstance(st["rr"], dict) and isinstance(st.get("bus", {}), dict) and stamp(data["fetched"]) and isinstance(data.get("rr", {}), dict)
    except (TypeError, KeyError, AttributeError):
        return None
    return data if ok else None


def late_colour(minutes):
    if minutes is None:
        return STEEL   # no delay data: grey, not the gold of on time
    return GOLD if minutes < 1 else W if minutes < 10 else A if minutes < 30 else RED


def draw(now, data, sfw=False, problem=None):
    """the page above the track, RGB at the screen's size. data: {"status", "rr", "fetched"} or None; problem, why there's
    none (then it says so, in amber, instead of "asking")"""
    clean = (lambda s: s.replace("fucked", "fcked").replace("Fucked", "Fcked").replace("FUCKED", "FCKED")) if sfw else (lambda s: s)
    img = Image.new("RGB", SCREEN, NAVY); d = ImageDraw.Draw(img)
    # the header: SEPTA on a blue band, the question, the line bullets, the time
    d.rectangle((0, 0, SCREEN[0], 60), fill=BLUE); d.rectangle((0, 60, SCREEN[0], 63), fill=RED)
    text(img, (24, 6), "SEPTA", W, scale=3)
    text(img, (24 + 5 * 24 + 28, 14), clean("IS SEPTA FUCKED?"), LIGHT, scale=2)
    x = SCREEN[0] - 24 - 8 * 16 - 24 - 7 * 46
    for letter, colour in LINES + [("R", RAIL)]:
        b = bullet(letter, colour); img.paste(b, (x, 10), b); x += 46
    text(img, (SCREEN[0] - 24, 14), clock(now), W, scale=2, right=True)
    data = usable(data)
    if not data:
        text(img, (28, 120), clean(problem) if problem else "asking isseptafucked.com...", A if problem else LIGHT, scale=2)
        return img
    st = data["status"]["status"]
    rr, bus = st["rr"], st.get("bus", {})
    verdict = str(rr.get("status", "?"))
    fetched = stamp(data["fetched"]); age = (now - fetched).total_seconds()
    future = age < -300   # a stamp from the future (a clock that's wrong, here or where it was fetched) can't be trusted either
    stale = age >= 900 or future
    # Regional Rail's verdict, with its sign
    b = bullet("R", RAIL, 32); img.paste(b, (28, 84), b)
    text(img, (72, 84), "REGIONAL RAIL", LIGHT, scale=2)
    s = sign(verdict).resize((96, 96), Image.NEAREST); img.paste(s, (28, 130), s)
    words = clean(verdict.upper())
    text(img, (144, 138 if len(words) <= 10 else 150), words, VERDICT.get(verdict, W), scale=5 if len(words) <= 15 else 4)
    text(img, (144, 226), clean(str(rr.get("summary", ""))), W, scale=2)
    d.rectangle((28, 272, 744, 273), fill=BLUE)
    b = coach().resize((32, 20), Image.NEAREST); img.paste(b, (28, 294), b)
    text(img, (72, 288), "BUSES", LIGHT, scale=2)
    bus_status = str(bus.get("status", "?"))   # whatever it is: a list isn't a key
    text(img, (72 + 6 * 16 + 8, 288), clean(bus_status.upper()), VERDICT.get(bus_status, W), scale=2)
    text(img, (72, 324), clean(str(bus.get("summary", ""))), W, scale=2)
    # the departure board: gold LED letters on black, like the boards at the stations
    X0, X, R, Y1 = 776, 800, SCREEN[0] - 24, TRACK_Y - 12
    d.rectangle((X0, 76, SCREEN[0] - 12, Y1), fill=BOARD, outline=STEEL)
    text(img, (X, 88), "TRAIN", GOLD, scale=2); text(img, (X + 7 * 16, 88), "FROM", GOLD, scale=2)
    text(img, (X + 26 * 16, 88), "TO", GOLD, scale=2); text(img, (R, 88), "STATUS", GOLD, scale=2, right=True)
    d.rectangle((X, 122, R, 123), fill=(60, 52, 20))
    rows = trains(data.get("rr") or {})
    for i, (number, frm, to, late) in enumerate(rows[:(Y1 - 132) // ROW]):
        y = 132 + i * ROW
        text(img, (X, y), str(number)[:6], GOLD, scale=2)
        text(img, (X + 7 * 16, y), frm[:18], GOLD, scale=2)
        text(img, (X + 26 * 16, y), to[:22], GOLD, scale=2)
        text(img, (R, y), "NO DATA" if late is None else "ON TIME" if late < 1 else f"{late} MIN", late_colour(late), scale=2, right=True)
    for y in range(124, Y1, 2):   # LED rows: every other line dimmed, so the letters read as lamps
        d.line((X0 + 1, y, SCREEN[0] - 13, y), fill=BOARD)
    if stale:   # an answer that old is shown dimmed, all of it (the verdict, the buses, the board), under its own notice
        img.paste(Image.blend(img.crop((0, 64, SCREEN[0], TRACK_Y)), Image.new("RGB", (SCREEN[0], TRACK_Y - 64), NAVY), .5), (0, 64))
    site = "isseptafcked.com" if sfw else "isseptafucked.com"
    if not stale:
        text(img, (28, TRACK_Y - 26), f"{site} · updated {clock(fetched)}", LIGHT, scale=1)
    else:   # stale: big and amber, not a small line under an answer that looks current
        text(img, (28, TRACK_Y - 44), "ANSWER DATED IN THE FUTURE" if future else f"NO UPDATE FOR {round(age / 60)} MIN", A, scale=2)
        text(img, (28, TRACK_Y - 16), f"{site} · last answer {clock(fetched)}", A, scale=1)
    return img


def api(path):
    with urllib.request.urlopen(urllib.request.Request(
            API + path, headers={"User-Agent": "wi-ki septa (github.com/nomadsgalaxy/wi-ki)"}), timeout=20) as r:
        return json.load(r)


class Page:
    """SEPTA's state, as a page of the kiosk's cycle"""
    name, seconds = "septa", 20
    fps = 4 if SLOW else 10   # the train: smooth on the render server, steppier on the Pi drawing by itself

    def __init__(self, sfw=False, data=None):
        self.sfw, self.fixed, self.data = sfw, data is not None, data
        self.busy, self.mtime, self.bg, self.rail, self.frames = False, None, (None, None), track(), {}
        self.good = None   # the last data that drew, for when the newest can't
        self.problem, self.tried = None, 0   # why there's no data; when a fetch was last tried

    def fetch(self):
        self.tried = time.time()   # a failure waits EVERY like a success, not a tick
        try:
            data = {"status": api("status"), "rr": api("rr"), "fetched": datetime.now().isoformat(timespec="seconds")}
            if not usable(data):
                raise ValueError("odd reply")   # not cached: the last good one stays
            os.makedirs(os.path.dirname(CACHE), exist_ok=True)
            with open(CACHE + ".tmp", "w") as f:
                json.dump(data, f)
            os.replace(CACHE + ".tmp", CACHE)
            self.problem = None
        except ValueError:   # a reply that came, but isn't JSON or isn't the shape
            self.problem = "isseptafucked.com sent something odd"
        except Exception:
            self.problem = "can't reach isseptafucked.com"   # keep the last one; the page says how old it is. Not the exception's text
        self.busy = False

    def start(self, now):
        pass   # background() fetches when the shared cache is old

    def background(self, now):
        if not self.fixed:
            mtime = os.path.getmtime(CACHE) if os.path.exists(CACHE) else None
            if not self.busy and (mtime is None or time.time() - mtime > EVERY) and time.time() - self.tried > EVERY:   # another renderer may have fetched
                self.busy = True; threading.Thread(target=self.fetch, daemon=True).start()
            if mtime != self.mtime:
                self.mtime = mtime
                try:
                    with open(CACHE) as f:
                        self.data = usable(json.load(f)) or self.data
                except (OSError, ValueError):
                    pass
        key = (now.minute, self.mtime, id(self.data), self.problem)
        if key != self.bg[0]:
            try:
                img = draw(now, self.data, self.sfw, self.problem); img.paste(self.rail, (0, TRACK_Y))
                self.bg = (key, packed(img)); self.good = self.data
            except Exception:   # data that got past usable() but still can't be drawn: the last data that did, marked, or a no-data page before there is any
                try:
                    assert self.good
                    img = draw(now, self.good, self.sfw); text(img, (480, 18), "CAN'T DRAW LATEST DATA", A, scale=2)
                except Exception:
                    img = draw(now, None, self.sfw, "septa data can't be drawn")
                img.paste(self.rail, (0, TRACK_Y)); self.bg = (key, packed(img))
        return self.bg

    def regions(self, now, t):
        """the train, right to left along the track, which wraps round: the whole strip, so nothing it passed is left
        behind. A lap is exactly 10 s, so its frames repeat: each is made once and kept (on a Pi Zero, packing the strip
        every frame would cost more than the rest of the page)"""
        k = int(t * self.fps) % (10 * self.fps)
        if k not in self.frames:
            x = round(SCREEN[0] - k / self.fps * SPEED % LAP)
            strip = self.rail.copy()
            for at in (x, x + LAP):   # the train, and its front coming round again on the right
                strip.paste(TRAIN, (at, 0), TRAIN)
            self.frames[k] = packed(strip)
        return [(self.frames[k], (0, TRACK_Y))]


SAMPLE = {"status": {"status": {"rr": {"status": "fucked", "summary": "2 out of 45 trains are late."},
                                "bus": {"status": "not fucked", "summary": "All 156 bus lines are running!"}}},
          "rr": {"data": {"284": {"number": "284", "from": "Marcus Hook", "to": "Norristown TC", "late": 12},
                          "444": {"number": "444", "from": "Airport", "to": "Warminster", "late": 1},
                          "453": {"number": "453", "from": "Warminster", "to": "Airport", "late": 0},
                          "9999": {"number": "9999", "from": "Doylestown", "to": "Newark", "late": 41}}},
          "fetched": "2026-10-15T16:00:00"}


def check():
    from datetime import timedelta
    from kit import unpack
    assert [t[0] for t in trains(SAMPLE["rr"])] == ["9999", "284", "444", "453"] and trains({}) == []
    assert [late_colour(m) for m in (0, 5, 12, 41, None)] == [GOLD, W, A, RED, STEEL]
    assert all(sign(v).getbbox() for v in VERDICT) and coach().getbbox() and TRAIN.height * 1 <= SCREEN[1] - TRACK_Y
    now = datetime(2026, 10, 15, 16, 2)
    for data, sfw in ((SAMPLE, False), (SAMPLE, True), (None, False), (dict(SAMPLE, rr={}), False)):
        assert draw(now, data, sfw).size == SCREEN, "draws with data, work-safe, before the first fetch, and with no trains"
    page = Page(data=SAMPLE)
    key, bg = page.background(now)
    assert bg.mode == "LA" and page.background(now)[0] == key
    for t in (0, 1.5, 7, 9.99):   # the strip is the whole track, and the loop is seamless
        for img, (x, y) in page.regions(now, t):
            assert (x, y) == (0, TRACK_Y) and img.size == (SCREEN[0], SCREEN[1] - TRACK_Y)
    frame = lambda t: page.regions(now, t)[0][0].tobytes()
    assert frame(0) == frame(10) == frame(20) and frame(3) == frame(13), "a lap every 10 s: two a turn, each the same"
    assert frame(0) != frame(0.1), "and it moves"
    # odd data: late as text or junk, a verdict the site never gave, a bad stamp, a mangled schema
    assert [minutes(v) for v in (12, "12.5", "12 min", None, "soon", float("nan"), float("inf"), "")] == [12, 12, 12, None, None, None, None, None] and minutes(0) == 0, "no number is unknown, not on time"
    odd = {"data": {"1": {"late": "12 min"}, "2": "oops", "3": {"number": 3, "late": None}}}
    assert [t[3] for t in trains(odd)] == [12, None] and trains({"data": []}) == [] and trains(None) == []
    assert sign("on fire?").tobytes() != sign("fucked").tobytes() and sign("on fire?").getbbox(), "an unknown verdict isn't the dumpster fire"
    status = lambda **kw: dict(SAMPLE, status={"status": {"rr": {"status": "melting", "summary": 7}, "bus": {"status": None}}}, **kw)
    for data in (status(), status(rr={"data": {"1": {"late": "x"}}}), dict(SAMPLE, fetched="2026-10-15T16:00:00+00:00"),
                 dict(SAMPLE, status={}), dict(SAMPLE, status={"status": []}), dict(SAMPLE, fetched="yesterday"), {"status": 3}, []):
        assert draw(now, data).size == SCREEN, "odd data draws, as the data or as no data, and never raises"
    assert usable(SAMPLE) and not usable(dict(SAMPLE, fetched="x")) and not usable({"status": {"status": {"rr": 1}}})
    old = draw(datetime(2026, 10, 15, 17, 30), SAMPLE)   # an hour and a half old
    assert old.crop((28, TRACK_Y - 44, 400, TRACK_Y - 28)).getcolors(9999) and A in [c for _, c in old.crop((28, TRACK_Y - 44, 400, TRACK_Y - 28)).getcolors(9999)], "stale says so, big and amber"
    live = {"not fucked", "a little fucked", "fucked"}   # the three verdicts the site gives (/api/status), each its own sign
    assert live == set(VERDICT) and len({sign(v).tobytes() for v in live | {"?"}}) == 4, "every real verdict has its own sign; anything else a grey ?"
    red = lambda im: [n for n, c in (im.crop((144, 138, 744, 190)).getcolors(99999) or []) if c == RED]
    assert red(draw(now, SAMPLE)) and not red(old), "a stale answer's big verdict is dimmed"
    # a bus status that is a list is a status, not a key
    assert draw(now, dict(SAMPLE, status={"status": {"rr": {"status": "fucked"}, "bus": {"status": ["a"], "summary": ["b"]}}})).size == SCREEN
    # a train with no delay data says so on the board, not ON TIME
    board = lambda data: [c for _, c in draw(now, data).crop((SCREEN[0] - 136, 120, SCREEN[0] - 24, 160)).getcolors(99999)]
    nodata = dict(SAMPLE, rr={"data": {"1": {"number": "1", "from": "A", "to": "B", "late": "soon"}}})
    assert STEEL in board(nodata) and GOLD not in board(nodata) and GOLD in board(dict(SAMPLE, rr={"data": {"1": {"late": 0}}})), "unknown delay isn't ON TIME"
    # a draw that raises: the last good data, marked, or a no-data page before there is one (a frozen frame would leave the clock and banner stale)
    flaky = Page(data=SAMPLE); good = flaky.background(now)[1]
    bad = {"status": {"status": {"rr": {"status": "x"}, "bus": {"summary": 1, "status": 1}}}, "fetched": "2026-10-15T16:00:00"}
    flaky.data = bad
    real = globals()["draw"]
    globals()["draw"] = lambda now, data, sfw=False, problem=None: (_ for _ in ()).throw(KeyError("late")) if data is bad else real(now, data, sfw, problem)
    mark = lambda im: any(r > 200 and g > 150 and b < 140 for _, (r, g, b) in unpack(im).crop((480, 18, 840, 40)).getcolors(99999))   # RGB565 rounds the amber
    try:
        marked = flaky.background(now + timedelta(minutes=1))[1]
        assert marked.tobytes() != good.tobytes() and mark(marked) and not mark(good), "a draw that fails shows the last good data, marked, with the new time"
        fresh = Page(data=SAMPLE); fresh.data = bad
        assert fresh.background(now)[1] is not None and not mark(fresh.background(now)[1]), "and with none yet, a no-data page"
    finally:
        globals()["draw"] = real
    # every part of an old answer is dimmed, not only the verdict, and a stamp from the future is no answer either
    lit = lambda im, box: max(sum(c) for n, c in im.crop(box).getcolors(99999))
    for box in ((144, 226, 700, 250), (72, 324, 700, 348), (72 + 6 * 16 + 8, 288, 700, 312), (800, 132, 1500, 160)):   # summary, bus summary, bus status, a board row
        assert lit(old, box) < lit(draw(now, SAMPLE), box), "stale dims the summary, the bus lines and the departure board"
    future = draw(now, dict(SAMPLE, fetched="2026-10-16T16:00:00"))
    assert lit(future, (144, 226, 700, 250)) < lit(draw(now, SAMPLE), (144, 226, 700, 250)) and A in [c for _, c in future.crop((28, TRACK_Y - 44, 400, TRACK_Y - 28)).getcolors(9999)], "a future stamp is dimmed and flagged"
    # a failed fetch waits EVERY like a success, not a tick; a good reply is cached, a bad one is not
    global api, CACHE
    tmp = tempfile.TemporaryDirectory()
    got, saved, CACHE = api, CACHE, os.path.join(tmp.name, "septa.json")
    try:
        calls = []
        def down(path):
            calls.append(path); raise urllib.error.URLError("down")
        api = down
        p = Page(); p.mtime = 1; p.fetch()
        assert p.problem == "can't reach isseptafucked.com" and "urlopen" not in p.problem and time.time() - p.tried < 5 and not p.busy and calls == ["status"]
        p.background(now)
        assert calls == ["status"] and not p.busy, "a tick right after a failure doesn't fetch again"
        api = lambda path: {"junk": 1}
        p.fetch()
        assert p.problem == "isseptafucked.com sent something odd" and not os.path.exists(CACHE), "an odd reply isn't cached, and isn't called unreachable"
        def junk(path):
            raise json.JSONDecodeError("x", "", 0)
        api = junk
        p.fetch()
        assert p.problem == "isseptafucked.com sent something odd", "so is a reply that isn't JSON"
        api = lambda path: SAMPLE["status"] if path == "status" else SAMPLE["rr"]
        p.fetch()
        assert p.problem is None and usable(json.load(open(CACHE))), "a good reply is cached"
        with open(CACHE, "w") as f:
            f.write('{"status": 5, "fetched": "x"}')
        q = Page(); q.background(now)
        assert q.data is None and q.bg[1] is not None, "an odd cache file isn't installed"
        assert draw(now, None, False, "can't reach isseptafucked.com").tobytes() != draw(now, None).tobytes(), "no data says so"
    finally:
        api, CACHE = got, saved
        tmp.cleanup()


def preview(now=None):
    """the page with the sample, the train mid-screen, for the emulator and kiosk.py --png"""
    import kit
    page = Page(data=SAMPLE)
    img = page.background(now or datetime(2026, 10, 15, 16, 2))[1].copy()
    for part, xy in page.regions(now, 5.5):
        img.paste(part, xy)
    return kit.unpack(img)
