# Built By NomadsGalaxy (https://nomadsgalaxy.com): OCL v1.1 + SWAtt v1, see LICENSE
"""kit: what every page of the kiosk shares. The screen, the colours, the VGA console font, RGB565 packing for the
framebuffer, and the little pixel weather icons. A page imports what it needs from here and nothing from other pages.
"""
import gzip, json, math, os, struct, threading, time
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
# ~/.cache/kiosk/desk.json, which feed/deskfeed.py writes from the desktop; the pages read it as a Simple page's file
STALE = 15 * 60   # a feed older than this: the desktop's off, or off the network


def fresh(feed):
    """whether the desktop sent this feed in the last STALE seconds: when it hasn't, the rotation skips its pages"""
    try:
        return (datetime.now() - local(feed["updated"])).total_seconds() <= STALE
    except (TypeError, KeyError, ValueError):
        return False


def note(feed, now):
    """(what to say about the feed's age, its colour), for the masthead"""
    if not feed:
        return "waiting for the desktop", A
    age = (now - local(feed["updated"])).total_seconds()
    return (f"no update for {round(age / 60)} min", A) if age > STALE else ("desktop · " + clock(local(feed["updated"])), D)


def drifter():
    """the Drifter: the brand's 32 px small companion, as-is (never redrawn or recoloured), RGBA"""
    return Image.open(os.path.join(HERE, "art", "drifter.png")).convert("RGBA")


_drifter = []
LOGO = os.path.expanduser("~/.config/kiosk/logo.png")   # a kiosk's own logo for its pages, in place of the Drifter


def logo(path=None):
    """the 64 px mark at the top left of a page: this kiosk's own logo.png (a club's or a shop's), fitted into the
    square and centred, or the Drifter at 2x, so it stays pixel art"""
    try:
        own = Image.open(path or LOGO)
        if own.width * own.height > 4096 * 4096:
            raise ValueError("too big for a logo")
        own = own.convert("RGBA"); own.thumbnail((64, 64), Image.LANCZOS)
        out = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        out.paste(own, ((64 - own.width) // 2, (64 - own.height) // 2))
        return out
    except (OSError, ValueError, Image.DecompressionBombError):   # none, or not a picture: the Drifter
        return drifter().resize((64, 64), Image.NEAREST)


def check_logo():
    """a kiosk's own logo, fitted and centred, whatever its shape; anything else is the Drifter"""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        Image.new("RGBA", (256, 128), (246, 145, 31, 255)).save(f"{d}/wide.png")
        wide = logo(f"{d}/wide.png")
        assert wide.size == (64, 64) and wide.getbbox() == (0, 16, 64, 48), wide.getbbox()
        open(f"{d}/junk.png", "w").write("not a picture")
        drift = drifter().resize((64, 64), Image.NEAREST).tobytes()
        assert logo(f"{d}/junk.png").tobytes() == logo(f"{d}/none.png").tobytes() == drift, "no logo, or a broken one: the Drifter"


def masthead(img, now, kicker, title, note=None):
    """the top of a desktop page: the kiosk's logo (the Drifter, unless it has its own), a ship's-log kicker and the
    title, the clock and the feed's age on the right, and the hairline under it all"""
    if not _drifter:
        _drifter.append(logo())
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


# --- the easy way to make a page ---------------------------------------------------------------------------------------


class Simple:
    """a page you make by saying what it shows: kit does the rest. catalog/new/page.py is one to start from, and
    docs/make.md the whole story. A page fills in what it needs:

      draw(img, now, data)    draw on img, an RGB picture the size of the screen, cleared to BG. It runs when
                              redraw_on(now) changes (the minute, unless the page says: halflife3's is the day), new
                              data comes, or redraw() asks. With no data yet, data is None: a draw
                              that can't do anything with None gets the waiting screen
      fetch() and every       get the data from the internet, every `every` seconds (it can be a property, to fetch
                              more often while something's on). It runs in the background, and goes in a cache file
                              that every renderer shares (`cache`, from the page and its options unless it says),
                              so it's fetched once however many draw it. It has to be JSON. If it raises, the page
                              keeps what it had, problem says why, and it tries again in a minute
      file                    or: a JSON file something else writes (a desktop feed), read again when it changes
      clean(data)             optional: the data as draw() wants it (types checked, missing parts filled in), or
                              None if it's no good: then the page keeps the data it had. Read data is anyone's
      moving(now, t, data)    what changes every frame: [(picture, (x, y))]. t is seconds since the page came up. RGB
                              pictures are packed each frame, so keep them small, or hand back packed ones
                              (kit.packed()), or raw packed bytes for whole rows at (0, y)
      SAMPLE                  data to draw in check(), preview() and fuzz, without the network

    and anything else a page has (fps, shapes, active(), touch(x, y), start(now)) works as on any page: see kiosk.py.
    It also gets updated (when its data was fetched or written, a datetime, or None), age() (seconds since), problem
    (why the last fetch failed: the exception, or None), redraw() (draw again on the next frame, after a touch say)
    and load() (bring data up to date now, for active()).

    Data that can't be drawn never replaces a picture: the page keeps showing the last data that drew, marked
    CAN'T DRAW, and says why on the console. Options are __init__'s arguments, as on any page; no need to call this
    __init__."""
    seconds, every, file, cache, SAMPLE = 20, 0, None, None, None
    mark = (SCREEN[0] - 24, SCREEN[1] - 40)   # where CAN'T DRAW goes (its right end), if that's in the way
    data, updated, problem, failed = None, None, None, None
    _bg, _good, _busy, _tried, _mtime, _turn, _fixed, _where = (None, None), None, False, 0.0, None, 0, False, None
    options = {}

    def __init_subclass__(cls, **kw):
        """note each page's options as it's made, for its cache's name"""
        super().__init_subclass__(**kw)
        init = cls.__dict__.get("__init__")
        if init:
            import functools, inspect
            sig = inspect.signature(init)

            @functools.wraps(init)
            def noted(self, *args, **kwargs):
                bound = sig.bind(self, *args, **kwargs); bound.apply_defaults()
                self.options = dict(list(bound.arguments.items())[1:])
                init(self, *args, **kwargs)
            cls.__init__ = noted

    @classmethod
    def showing(cls, data, **options):
        """the page with this data for good, never fetching or reading: for tests and previews"""
        page = cls(**options)
        page.data, page._fixed, page.updated = None if data is None else page.clean(data), True, datetime(2026, 10, 19, 9, 40)
        return page

    def fetch(self):
        return None

    def clean(self, data):
        return data

    def draw(self, img, now, data):
        text(img, (40, 40), type(self).__name__.upper(), O, scale=4)

    def moving(self, now, t, data):
        return []

    def redraw(self):
        self._turn += 1

    def redraw_on(self, now):
        return now.minute

    @property
    def drawn(self):
        """the picture showing now, packed (None before the first): for a page that moves parts of its own background"""
        return self._bg[1]

    def age(self):
        """seconds since the data was fetched or written (infinity with none; 0 for showing()'s, which never ages)"""
        if self._fixed:
            return 0
        return (datetime.now() - self.updated).total_seconds() if self.updated else float("inf")

    def where(self):
        """the file the data is read from: file, or the cache fetch() writes"""
        if self.file:
            return os.path.expanduser(self.file)
        if self.cache:
            return os.path.expanduser(self.cache)
        if not self._where:   # a cache for each set of options: two kiosks drawn on one server can want different teams
            import hashlib
            key = hashlib.sha1(json.dumps(self.options, sort_keys=True, default=repr).encode()).hexdigest()[:8]
            self._where = os.path.expanduser(f"~/.cache/kiosk/{type(self).name}-{key}.json")
        return self._where

    def fetch_now(self, path=None):
        """fetch() into the cache, here and now (load() does it in the background when it's time)"""
        path = path or self.where()
        try:
            data = self.fetch()
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path + ".tmp", "w") as f:
                json.dump(data, f)
            os.replace(path + ".tmp", path)   # whole, or not at all: another renderer may be reading it
            self.problem = None
        except Exception as e:
            self.problem = e
            print(f"{self.name}: can't fetch: {type(e).__name__}: {e}", flush=True)
        finally:
            self._tried, self._busy = time.time(), False

    def load(self):
        """fetch when the cache is old (another renderer may have just done it), and read it, or file, when it changes.
        background() does this every frame; active() can too, to decide on the latest data"""
        if self._fixed or not (self.file or self.every):
            return
        path = self.where()
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            mtime = None
        every = self.every
        if not self.file and every and not self._busy:
            wait = every if self.problem is None else min(every, 60)   # a failure tries again in a minute
            if (mtime is None or time.time() - mtime >= every) and time.time() - self._tried >= wait:
                self._busy = True
                threading.Thread(target=self.fetch_now, args=(path,), daemon=True).start()
        if mtime != self._mtime:
            try:
                with open(path) as f:
                    data = json.load(f)
                self._mtime, data = mtime, self.clean(data)
                if data is not None:   # data that's no good keeps what it had
                    self.data, self.updated = data, datetime.fromtimestamp(mtime)
            except (OSError, ValueError, TypeError):
                pass   # gone, or half written: keep the last, and look again next time

    def picture(self, now, data, safe=True):
        """the page with data, as an RGB picture. safe: if draw() fails, the last picture that drew, marked (or the
        waiting screen, with no data yet), instead of raising"""
        img = Image.new("RGB", SCREEN, BG)
        try:
            self.draw(img, now, data)
            self.failed = None
            return img
        except Exception as e:
            if data is None:   # nothing to draw yet, and the page doesn't say so itself
                img = Image.new("RGB", SCREEN, BG)
                text(img, (40, 40), "WAITING FOR DATA…", G, scale=3)
                return img
            if not safe:
                raise
            failed = f"{type(e).__name__}: {e}"
            print(f"{self.name}: can't draw: {failed}", flush=True)
            img = self._good.copy() if self._good else self.picture(now, None)   # or the page with no data yet
            self.failed = failed
            text(img, self.mark, "CAN'T DRAW THE LATEST DATA", A, right=True)
            return img

    def start(self, now):
        pass

    def background(self, now):
        self.load()
        key = (self.redraw_on(now), self._mtime, self._turn, id(self.data), repr(self.problem))
        if key != self._bg[0]:
            img = self.picture(now, self.data)
            if not self.failed:
                self._good = img
            self._bg = (key, packed(img))
        return self._bg

    def regions(self, now, t):
        try:
            return [(part if isinstance(part, bytes) or part.mode == "LA" else packed(part.convert("RGB")), xy)
                    for part, xy in self.moving(now, t, self.data) or []]
        except Exception as e:   # what moves just stops; the page stays
            self.failed = f"{type(e).__name__}: {e}"
            return []

    @classmethod
    def check(cls, tries=20, **options):
        """the self-test every Simple page gets: it draws with no data yet and SAMPLE, and what moves has to stay on the
        screen. Then SAMPLE broken tries ways (fuzz.py): the page has to stay up, though draw() may refuse the data (it
        keeps its last picture). python3 -I kiosk/fuzz.py <page> says which broken data it refused, and why"""
        import contextlib, copy, inspect, io, random, fuzz
        for name in ("where", "load", "fetch_now", "picture", "background", "regions", "age", "redraw"):   # Simple's own
            mine, its = getattr(cls, name), getattr(Simple, name)
            if mine is not its and list(inspect.signature(mine).parameters) != list(inspect.signature(its).parameters):
                raise AssertionError(f"{cls.name}: its {name}() takes the place of Simple's, which kit calls as "
                                     f"{name}{inspect.signature(its)}: give it another name")
        now = datetime(2026, 10, 19, 9, 41)
        for n in range(-1, tries + 1):
            data = None if n < 0 else cls.SAMPLE if n == 0 else fuzz.mangle(copy.deepcopy(cls.SAMPLE), random.Random(19000 + n))
            page = cls.showing(data, **options)
            try:
                with contextlib.redirect_stdout(io.StringIO()) if n > 0 else contextlib.nullcontext():   # refusals aren't news here
                    picture = page.picture(now, page.data, safe=n > 0)
                    page.background(now)   # as the display has it, so what moves can use the picture (drawn)
                assert picture.size == SCREEN, f"draws {picture.size}, not {SCREEN}"
                for t in (0, .5, 3, 30):
                    for part, (x, y) in page.regions(now, t):
                        w, h = (SCREEN[0], len(part) // SCREEN[0] // 2) if isinstance(part, bytes) else part.size
                        assert 0 <= x and 0 <= y and x + w <= SCREEN[0] and y + h <= SCREEN[1], \
                            f"something moving at ({x}, {y}), {w}x{h}, goes off the screen"
                    assert not page.failed or n > 0, "what moves: " + page.failed
            except Exception as e:
                raise AssertionError(f"{cls.name}: with " + ("no data" if n < 0 else "SAMPLE" if n == 0 else f"SAMPLE broken (try {n})")
                                     + f": {type(e).__name__}: {e}. data: {data!r:.300}") from e

    @classmethod
    def preview(cls, now=None, **options):
        """the page with SAMPLE, and what moves where it is when the page comes up"""
        now = now or datetime(2026, 10, 19, 9, 41)
        page = cls.showing(cls.SAMPLE, **options)
        img = page.picture(now, page.data, safe=False)
        for part, xy in page.moving(now, 0, page.data) or []:
            if isinstance(part, bytes):
                part = unpack(Image.frombytes("LA", (SCREEN[0], len(part) // SCREEN[0] // 2), part))
            img.paste(unpack(part) if part.mode == "LA" else part.convert("RGB"), xy)
        return img
