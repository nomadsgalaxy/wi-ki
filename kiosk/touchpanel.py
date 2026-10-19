"""touchpanel: reads the kiosk's touch screen, if it has one, and turns what fingers do into kiosk.py's touch file
(TOUCH). It looks for a panel every few seconds, so one plugged in later works too, and on a kiosk without one it does
nothing else. Standard library only: it reads the panel's evdev device (/dev/input/event*), which the kiosk user can
as a member of "input".

  a tap                       {"x": .., "y": ..}, in screen pixels
  a swipe left or right       {"gesture": "next"} or {"gesture": "prev"}
  a two-finger double tap     {"gesture": "menu"}: the home page

A touch screen is an input device with INPUT_PROP_DIRECT (so not a touchpad) that reports multi-touch positions. On a
screen turned upside down (rotate=180 in the kernel's video= option), the touches are turned with it.
"""
import fcntl, glob, json, os, re, struct, sys, threading, time

EVENT = struct.Struct("llHHi")   # struct input_event: its time is two longs (4 bytes each on the Pi's 32-bit OS)
EV_SYN, EV_ABS, SYN_REPORT = 0, 3, 0
ABS_MT_SLOT, ABS_MT_POSITION_X, ABS_MT_POSITION_Y, ABS_MT_TRACKING_ID = 0x2F, 0x35, 0x36, 0x39
INPUT_PROP_DIRECT = 1
TAP, SWIPE, DOUBLE, LOOK = 30, 150, 0.5, 5   # px a tap may wander, px a swipe must cover, s between a double tap's two, s between looks


def bits(text):
    """a sysfs capability bitmask ("1 0 3": longs, the most significant first) -> int"""
    size = 8 * struct.calcsize("l")
    return sum(int(w, 16) << (size * i) for i, w in enumerate(reversed(text.split())))


def find(root="/sys/class/input"):
    """the touch screen's /dev/input/event* path, or None"""
    for dev in sorted(glob.glob(f"{root}/event*")):
        try:
            props, axes = (bits(open(f"{dev}/device/{f}").read()) for f in ("properties", "capabilities/abs"))
        except OSError:
            continue
        if props >> INPUT_PROP_DIRECT & 1 and axes >> ABS_MT_POSITION_X & 1:
            return "/dev/input/" + os.path.basename(dev)
    return None


def span(f, code):
    """(min, max) of one of the panel's axes (EVIOCGABS)"""
    info = bytearray(24)   # struct input_absinfo: six 32-bit ints
    fcntl.ioctl(f, (2 << 30) | (24 << 16) | (ord("E") << 8) | (0x40 + code), info)
    return struct.unpack("6i", info)[1:3]


def upside_down(cmdline="/proc/cmdline"):
    try:
        return bool(re.search(r"\bvideo=\S*rotate=180", open(cmdline).read()))
    except OSError:
        return False


class Gestures:
    """fingers going down, moving and coming up (in screen pixels) -> what they meant, handed to send()"""

    def __init__(self, send):
        self.send, self.start, self.end, self.down_now, self.most, self.two = send, {}, {}, set(), 0, -DOUBLE

    def down(self, finger, xy):
        self.start[finger] = self.end[finger] = xy
        self.down_now.add(finger); self.most = max(self.most, len(self.down_now))

    def move(self, finger, xy):
        self.end[finger] = xy

    def up(self, finger, now):
        self.down_now.discard(finger)
        if self.down_now:   # it's over when the last finger lifts
            return
        moves = [(self.end[f][0] - self.start[f][0], self.end[f][1] - self.start[f][1]) for f in self.start]
        still = all(abs(dx) < TAP and abs(dy) < TAP for dx, dy in moves)
        if self.most == 1:
            (dx, dy), = moves
            if abs(dx) > SWIPE and abs(dx) > 2 * abs(dy):
                self.send({"gesture": "next" if dx < 0 else "prev"})
            elif still:
                x, y = self.start[finger]
                self.send({"x": x, "y": y})
        if self.most == 2 and still and now - self.two >= DOUBLE:
            self.two = now   # the first half of a double tap
        else:
            if self.most == 2 and still:
                self.send({"gesture": "menu"})
            self.two = -DOUBLE   # anything else in between starts it over
        self.start, self.end, self.most = {}, {}, 0


def read(f, spans, screen, send, flip=False, clock=time.monotonic):
    """follow the panel's events (multi-touch protocol B: slots) until it's unplugged or the stream ends"""
    (x0, x1), (y0, y1) = spans
    w, h = screen

    def place(x, y):
        x, y = round((x - x0) * (w - 1) / max(1, x1 - x0)), round((y - y0) * (h - 1) / max(1, y1 - y0))
        return (w - 1 - x, h - 1 - y) if flip else (x, y)

    g, slot, at, touching, was = Gestures(send), 0, {}, set(), set()
    while True:
        data = f.read(EVENT.size)
        if len(data) < EVENT.size:
            return
        _, _, kind, code, value = EVENT.unpack(data)
        if kind == EV_ABS:
            if code == ABS_MT_SLOT:
                slot = value
            elif code == ABS_MT_TRACKING_ID:
                (touching.discard if value < 0 else touching.add)(slot)
            elif code in (ABS_MT_POSITION_X, ABS_MT_POSITION_Y):
                at.setdefault(slot, [x0, y0])[code - ABS_MT_POSITION_X] = value
        elif kind == EV_SYN and code == SYN_REPORT:   # a whole frame of the panel's state: compare it with the last
            for s in touching - was:
                g.down(s, place(*at.get(s, (x0, y0))))
            for s in touching & was:
                g.move(s, place(*at[s]))
            for s in was - touching:
                g.up(s, clock())
            was = set(touching)


def run(touch, screen, poke, look=LOOK):
    """forever: find the panel, read it until it's unplugged, then look again. poke() wakes the display."""
    def send(what):
        os.makedirs(os.path.dirname(touch), exist_ok=True)
        json.dump(what, open(touch + ".tmp", "w")); os.replace(touch + ".tmp", touch)
        poke()
    while True:
        path = find()
        if path:
            try:
                with open(path, "rb", buffering=0) as f:
                    print(f"touchpanel: reading {path}", file=sys.stderr)
                    read(f, (span(f, ABS_MT_POSITION_X), span(f, ABS_MT_POSITION_Y)), screen, send, upside_down())
            except OSError as e:
                print(f"touchpanel: {path}: {e}", file=sys.stderr)
        time.sleep(look)


def start(touch, screen, poke=lambda: None):
    threading.Thread(target=run, args=(touch, screen, poke), daemon=True).start()


def check():
    import io, tempfile
    assert bits("1 0") == 1 << (8 * struct.calcsize("l")) and bits("2") == 2
    root = tempfile.mkdtemp()
    for name, props, axes in (("event0", "0", "3"), ("event1", "2", f"{1 << 21:x} 0")):   # a mouse, then a touch screen
        os.makedirs(f"{root}/{name}/device/capabilities")
        open(f"{root}/{name}/device/properties", "w").write(props + "\n")
        open(f"{root}/{name}/device/capabilities/abs", "w").write(axes + "\n")
    if struct.calcsize("l") == 8:   # 64-bit longs: ABS_MT_POSITION_X (bit 53) sits in the first and only long
        open(f"{root}/event1/device/capabilities/abs", "w").write(f"{1 << 53:x}\n")
    assert find(root) == "/dev/input/event1" and find(tempfile.mkdtemp()) is None, "only the touch screen"
    cmd = os.path.join(root, "cmdline")
    open(cmd, "w").write("rootwait video=HDMI-A-1:1920x515@60,rotate=180\n")
    assert upside_down(cmd) and not upside_down(root + "/nope")

    def events(*frames):   # each frame: [(slot, tracking id or None, x, y)], then a SYN_REPORT
        out = b""
        for frame in frames:
            for slot, tid, x, y in frame:
                out += EVENT.pack(0, 0, EV_ABS, ABS_MT_SLOT, slot)
                if tid is not None:
                    out += EVENT.pack(0, 0, EV_ABS, ABS_MT_TRACKING_ID, tid)
                if x is not None:
                    out += EVENT.pack(0, 0, EV_ABS, ABS_MT_POSITION_X, x) + EVENT.pack(0, 0, EV_ABS, ABS_MT_POSITION_Y, y)
            out += EVENT.pack(0, 0, EV_SYN, SYN_REPORT, 0)
        return out

    def got(stream, flip=False):
        sent, t = [], iter(range(0, 1000))
        read(io.BytesIO(stream), ((0, 4095), (0, 4095)), (1920, 515), sent.append, flip, clock=lambda: next(t) * 0.1)
        return sent

    tap = [[(0, 1, 2048, 2048)], [(0, -1, None, None)]]
    assert got(events(*tap)) == [{"x": 960, "y": 257}], "a tap, scaled to the screen"
    assert got(events(*tap), flip=True) == [{"x": 959, "y": 257}], "and turned with an upside-down screen"
    left = [[(0, 1, 3000, 2000)], [(0, None, 2000, 2000)], [(0, None, 1000, 2100)], [(0, -1, None, None)]]
    assert got(events(*left)) == [{"gesture": "next"}], "a swipe left: the next page"
    assert got(events(*left), flip=True) == [{"gesture": "prev"}], "which is a swipe right on an upside-down screen"
    two = [[(0, 1, 1000, 2000), (1, 2, 1400, 2000)], [(0, -1, None, None)], [(1, -1, None, None)]]
    assert got(events(*two)) == [], "one two-finger tap: nothing yet"
    assert got(events(*two, *two)) == [{"gesture": "menu"}], "two of them: the menu"
    assert got(events(*two, [(0, 3, 50, 50)], [(0, -1, None, None)], *two)) == [{"x": 23, "y": 6}], "not with a tap between"
    print("touchpanel: ok")
