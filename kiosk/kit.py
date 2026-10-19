# Built By NomadsGalaxy (https://nomadsgalaxy.com): OCL v1.1 + SWAtt v1, see LICENSE
"""kit: what every page of the kiosk shares. The screen, the colours, the VGA console font, RGB565 packing for the
framebuffer, and the little pixel weather icons. A page imports what it needs from here and nothing from other pages.
"""
import gzip, json, math, os, struct
from datetime import datetime
from PIL import Image, ImageChops, ImageDraw

HERE = os.path.dirname(os.path.realpath(__file__))
# the shapes the kiosk can be drawn in: the Pi's bar, and the browser kiosks the render server streams (web.py). A
# process draws one shape, chosen by KIOSK_SHAPE; pages say which shapes they can do (Page.shapes).
SHAPES = {"bar": (1920, 515), "16-9": (1920, 1080), "9-16": (1080, 1920)}
SHAPE = os.environ.get("KIOSK_SHAPE", "bar")
SCREEN = SHAPES[SHAPE]
# map data that doesn't change (street maps). Kiosks drawn on one machine (a render server's instances, one per kiosk)
# can share a folder for it with KIOSK_MAPS, so each map is fetched once rather than once per kiosk
MAPS = os.environ.get("KIOSK_MAPS") or os.path.expanduser("~/.cache/kiosk")
# Nomads Galaxy's brand tokens: O is the lead accent, Warp Cyan; W Starlight, G Dust,
# D and DIM the muted ink, B Pulsar Violet, C Warp Cyan, M Nebula Magenta (emphasis only), A Booster Amber (warnings);
# then Deep Space, the Hairline (cyan at 18% over Deep Space) and Raised Space for panels
O, W, G, D, B, C = (125, 249, 255), (232, 236, 255), (154, 163, 199), (74, 82, 112), (164, 139, 255), (125, 249, 255)
M, A, GREEN = (255, 92, 243), (255, 206, 106), (74, 222, 128)
BG, RULE, DIM, RAISED = (5, 6, 15), (27, 50, 58), (74, 82, 112), (10, 12, 31)
ERROR = (255, 107, 107)   # the brand's error status colour


def kind(code, day=True):
    """weather code -> which icon"""
    if code in (0, 1): return "sun" if day else "moon"
    if code == 2: return "partly"
    if code == 3: return "cloud"
    if code in (45, 48): return "fog"
    if code in (51, 53, 55, 56, 57): return "drizzle"
    if code in (71, 73, 75, 77, 85, 86): return "snow"
    if code in (95, 96, 99): return "storm"
    return "rain"


def warmth(c):
    """temperature colour (°C): violet when it's cold, then cyan, Starlight, and amber when it's hot"""
    return B if c < 5 else C if c < 13 else W if c < 24 else A


def level(used):
    """a percentage's colour: cyan, amber from 50, red from 80"""
    return O if used < 50 else A if used < 80 else ERROR


def meter(d, xy, used, blocks=20, block=16, colour=None):
    """a bar of pixel blocks, used% of them lit (in level()'s colour unless given), on ImageDraw d. Returns its width."""
    x, y = xy; lit = round(max(0, min(100, used)) / 100 * blocks)
    for k in range(blocks):
        d.rectangle((x + k * block, y, x + k * block + block - 5, y + 15), fill=(colour or level(used)) if k < lit else RULE)
    return blocks * block


def clock(t):
    t = datetime.strptime(t, "%Y-%m-%dT%H:%M") if isinstance(t, str) else t
    return t.strftime("%I:%M %p").lstrip("0")


def freshness(then, now, limit):
    """how old some data is, for a corner of a page: ("updated 9:40 PM", False), or once it's older than limit seconds (or
    then is None, it has no time) ("no update for 25 min", True): the page shows the second in amber"""
    if then is None:
        return "no update time", True
    age = max(0, (now - then).total_seconds())
    if age <= limit:
        return "updated " + clock(then), False
    mins = round(age / 60)
    return "no update for " + (f"{mins} min" if mins < 120 else f"{mins // 60} h" if mins < 2880 else f"{mins // 1440} days"), True


# --- the VGA font -------------------------------------------------------------------------------------------------
def load_font(path):
    """a PSF1 console font -> {char: 8x16 '1' image}"""
    b = gzip.open(path).read()
    mode, h = b[2], b[3]; n = 512 if mode & 1 else 256
    table = struct.unpack("<%dH" % ((len(b) - 4 - n * h) // 2), b[4 + n * h:])
    glyphs, i = {}, 0
    for c in table:
        if c == 0xFFFF: i += 1
        elif c < 0xFFFE and chr(c) not in glyphs:
            glyphs[chr(c)] = Image.frombytes("1", (8, h), b[4 + i * h:4 + (i + 1) * h])
    return glyphs


FONT = load_font(os.path.join(HERE, "fonts", "Uni2-VGA16.psf.gz"))
_scaled = {}


def text(img, xy, s, colour, scale=2, right=False):
    """draw s in the VGA font at scale, its top left at xy (or its top right, if right). Returns its width."""
    width = len(s) * 8 * scale
    x, y = (xy[0] - width, xy[1]) if right else xy
    for i, ch in enumerate(s):
        key = (ch, scale)
        if key not in _scaled:
            _scaled[key] = FONT.get(ch, FONT["?"]).resize((8 * scale, 16 * scale), Image.NEAREST)
        img.paste(colour, (x + i * 8 * scale, y), _scaled[key])
    return width


def since(then, now):
    """the time from then to now in words, like 19 years, 5 days: whole years, then the days since the last anniversary"""
    y = now.year - then.year - ((now.month, now.day) < (then.month, then.day))
    d = (now - then.replace(year=then.year + y)).days
    return ", ".join(f"{n} {unit}{'s' if n != 1 else ''}" for n, unit in ((y, "year"), (d, "day")) if n) or "today"


def local(iso):
    """an ISO time with a zone (the desktop feed's) -> naive local time, like the now pages are given"""
    return datetime.fromisoformat(iso).astimezone().replace(tzinfo=None)


# --- the desktop feed, for the pages that show what's on my desktop (github, agents) --------------------------------
class Feed:
    """~/.cache/kiosk/desk.json, which feed/deskfeed.py writes from the desktop. Read again when it changes; a broken
    or half-written file keeps the last good one."""
    STALE = 15 * 60

    def __init__(self, path="~/.cache/kiosk/desk.json"):
        self.path, self.mtime, self.data = os.path.expanduser(path), None, None

    def load(self):
        mtime = os.path.getmtime(self.path) if os.path.exists(self.path) else None
        if mtime != self.mtime:
            self.mtime = mtime
            try:
                self.data = json.load(open(self.path))
            except (OSError, ValueError):
                pass
        return self.data

    def fresh(self):
        """whether the desktop has sent the feed in the last STALE seconds: when it hasn't (it's off, or off the
        network), the rotation skips its pages"""
        data = self.load()
        try:
            return (datetime.now() - local(data["updated"])).total_seconds() <= self.STALE
        except (TypeError, KeyError, ValueError):
            return False

    def note(self, now):
        """(what to say about the feed's age, its colour), for the masthead"""
        if not self.data:
            return "waiting for the desktop", A
        age = (now - local(self.data["updated"])).total_seconds()
        return (f"no update for {round(age / 60)} min", A) if age > self.STALE else ("desktop · " + clock(local(self.data["updated"])), D)


def drifter():
    """the Drifter: the brand's 32 px small companion, as-is (never redrawn or recoloured), RGBA"""
    return Image.open(os.path.join(HERE, "art", "drifter.png")).convert("RGBA")


_drifter = []


def masthead(img, now, kicker, title, note=None):
    """the top of a desktop page: the Drifter (at 2x, so it stays pixel art), a ship's-log kicker and the title, the
    clock and the feed's age on the right, and the hairline under it all"""
    if not _drifter:
        _drifter.append(drifter().resize((64, 64), Image.NEAREST))
    img.paste(_drifter[0], (24, 12), _drifter[0])
    text(img, (104, 14), kicker, O, scale=1)
    text(img, (104, 32), title, W, scale=3)
    text(img, (SCREEN[0] - 24, 14), clock(now), W, right=True)
    if note:
        text(img, (SCREEN[0] - 24, 54), note[0], note[1], scale=1, right=True)
    ImageDraw.Draw(img).rectangle((16, 86, SCREEN[0] - 16, 87), fill=RULE)
    return 104 + len(title) * 24   # where the title ends, for a cursor


# --- pixel icons, 16x16, two frames each so they move ---------------------------------------------------------------
def icon(name, frame):
    img = Image.new("RGBA", (16, 16), (0, 0, 0, 0)); d = ImageDraw.Draw(img)
    f = frame % 2

    def puff(dx, dy, colour):
        for box in ((1, 7, 8, 13), (4, 4, 11, 11), (7, 6, 14, 13)):
            d.ellipse((box[0] + dx, box[1] + dy, box[2] + dx, box[3] + dy), fill=colour)
        d.rectangle((3 + dx, 10 + dy, 12 + dx, 13 + dy), fill=colour)
        d.line((5 + dx, 5 + dy, 9 + dx, 5 + dy), fill=tuple(min(255, v + 25) for v in colour))

    if name == "sun":
        for k in range(8):   # the rays turn
            a = k * math.pi / 4 + f * math.pi / 8
            d.point((round(7.5 + 7 * math.cos(a)), round(7.5 + 7 * math.sin(a))), fill=O)
        d.ellipse((3, 3, 12, 12), fill=O); d.ellipse((4, 4, 9, 8), fill=(255, 200, 90))
    elif name == "moon":
        d.ellipse((3, 2, 13, 12), fill=(236, 236, 214)); d.ellipse((6, 1, 15, 10), fill=(0, 0, 0, 0))
        d.point((2 if f else 13, 13), fill=W); d.point((13 if f else 2, 3), fill=G)
    elif name == "partly":
        d.ellipse((1, 1, 9, 9), fill=O); puff(1 if f else 0, 2, (232, 236, 242))
    elif name == "cloud":
        puff(0, 0, (180, 186, 196)); puff(1 if f else 0, 1, (210, 214, 222))
    elif name == "fog":
        for i, y in enumerate((4, 8, 12)):
            d.line(((i + f) % 2 * 2, y, 13 + (i + f) % 2 * 2, y), fill=(190, 196, 206))
    elif name in ("drizzle", "rain"):
        puff(0, -2, (170, 178, 192))
        for k, x in enumerate((3, 7, 11) if name == "rain" else (5, 10)):
            y = 13 + (k + f) % 2
            d.line((x, y, x - 1, y + 2), fill=C if name == "drizzle" else B)
    elif name == "snow":
        puff(0, -2, (200, 206, 216))
        for k, x in enumerate((3, 8, 13)):
            d.point((x, 13 + (k + f) % 2 * 2), fill=W)
    elif name == "storm":
        puff(0, -2, (96, 100, 116))
        if f: d.line([(9, 9), (6, 12), (9, 12), (6, 15)], fill=(255, 220, 80))
    return img


def paste_icon(img, name, frame, xy, scale):
    i = icon(name, frame).resize((16 * scale, 16 * scale), Image.NEAREST)
    img.paste(i, xy, i)


# --- RGB565 packing ---------------------------------------------------------------------------------------------------


R5 = [v >> 3 << 3 for v in range(256)]; G3 = [v >> 5 for v in range(256)]
G3LO = [(v >> 2 & 7) << 5 for v in range(256)]; B5 = [v >> 3 for v in range(256)]


def packed(img):
    """RGB image -> an "LA" image whose two bytes per pixel are little-endian RGB565, all in Pillow's C code (no numpy
    needed on the Pi Zero). Being an image, it can still be scaled and pasted."""
    r, g, b = img.split()
    hi = ImageChops.add(r.point(R5), g.point(G3))
    lo = ImageChops.add(g.point(G3LO), b.point(B5))
    return Image.merge("LA", (lo, hi))


def rgb565(img):
    return packed(img).tobytes()


def unpack(img):
    """packed RGB565 ("LA") -> RGB, to look at what the framebuffer would show"""
    lo, hi = img.split()
    g = ImageChops.add(hi.point([(v & 7) << 5 for v in range(256)]), lo.point([(v >> 5) << 2 for v in range(256)]))
    return Image.merge("RGB", (hi.point([v >> 3 << 3 for v in range(256)]), g, lo.point([(v & 31) << 3 for v in range(256)])))
