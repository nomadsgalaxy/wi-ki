"""The now playing page: whatever my desktop is playing, the way Chorus and the ASCII Visualizer show it there. The cover
as 4x pixel art on the left, then the title, artist and album, the current line of synced lyrics, a live spectrum as
an LED meter in the brand's title gradient (Warp Cyan -> Pulsar Violet -> Nebula Magenta) with falling peaks, and how
far into the song it is.

The desktop's feed/nowplaying.py streams it here through sink.py, which writes track.json and frame.json to RAM
(/dev/shm/kiosk-nowplaying). It runs at 20 fps, five times the other pages, so the spectrum keeps up with the music.
With nothing playing, active() is False and the rotation skips the page (unless it's pinned).

Options (in playlist.json): folder, where the sink writes (default /dev/shm/kiosk-nowplaying).
"""
import base64, io, json, os, time
from datetime import datetime
from PIL import Image, ImageDraw

from kit import SCREEN, O, W, G, D, B, M, A, BG, RULE, RAISED, text, clock, packed

ART = 120                                 # the cover is 120x120, shown 4x
X, R = 16 + ART * 4 + 32, SCREEN[0] - 16  # the column right of the cover
VIZ_Y, VIZ_H, SCALE = 276, 160, 4         # the spectrum: 40 cells of 4 pixels, so it matches the 4x pixel art
LYRIC_Y, BAR_Y = 188, 452
STALE = 5                                 # seconds without a frame before the stream counts as gone


def gradient(h):
    """the title gradient, bottom to top: cyan, violet, magenta"""
    col = Image.new("RGB", (1, h))
    for y in range(h):
        f = 1 - y / max(1, h - 1)   # 0 at the bottom, 1 at the top
        a, b, k = (O, B, f * 2) if f < 0.5 else (B, M, f * 2 - 1)
        col.putpixel((0, y), tuple(round(a[i] + (b[i] - a[i]) * k) for i in range(3)))
    return col


def mmss(s):
    s = int(s); return f"{s // 60}:{s % 60:02d}"


def lyric_at(lyrics, pos):
    """the index of the line being sung at pos, or -1 before the first"""
    i = -1
    for k, (t, _) in enumerate(lyrics):
        if t > pos:
            break
        i = k
    return i


class Spectrum:
    """the LED meter, built as raw RGB565 bytes. On the Pi Zero, Pillow's copy() and tobytes() of a strip this size take
    75 ms, while joining bytes takes under one, so no images are made per frame: each of the 40 cells (4x4 pixel art,
    like the cover) has its row of 48 bar segments joined from pre-packed pieces, lit in the brand's title gradient,
    dark, or a Starlight peak. Every fourth cell is a dark seam (the visualizer's Blocks look). The result is the full
    screen width, the cover's slice of background either side, so kiosk.py writes it in one copy."""
    HOLD, FALL = 8, 0.6   # frames a peak waits (0.4 s at 20 fps), then cells it drops per frame
    BAR, GAP = 24, 4      # pixels

    def __init__(self):
        self.cells = VIZ_H // SCALE
        px = lambda c: packed(Image.new("RGB", (1, 1), c)).tobytes()
        grad = gradient(self.cells)
        dark, gap = px(BG) * self.BAR, px(BG) * self.GAP
        self.dark = dark + gap
        self.lit = [self.dark if c % 4 == 3 else px(grad.getpixel((0, self.cells - 1 - c))) * self.BAR + gap
                    for c in range(self.cells)]
        self.peak = px(W) * self.BAR + gap
        self.bg = px(BG)
        self.peaks, self.held, self.edges = [], [], (None, None)

    def draw(self, levels, strip):
        """this frame's spectrum over strip (the background behind it, as a packed full-width image) -> bytes"""
        n = len(levels) or 1
        if len(self.peaks) != n:
            self.peaks, self.held = [0.0] * n, [0] * n
        if self.edges[0] is not strip:   # the background's left (cover) and right of the meter, row by row
            raw, w = strip.tobytes(), SCREEN[0] * 2
            self.edges = (strip, [(raw[y * w:y * w + X * 2], raw[y * w + R * 2:(y + 1) * w]) for y in range(VIZ_H)])
        heights, tops = [], []
        for i, v in enumerate(levels):
            h = max(0, min(self.cells, round(v / 64 * self.cells)))
            if h >= self.peaks[i]:
                self.peaks[i], self.held[i] = h, self.HOLD
            elif self.held[i]:
                self.held[i] -= 1
            else:
                self.peaks[i] = max(0.0, self.peaks[i] - self.FALL)
            heights.append(h); tops.append(min(self.cells - 1, round(self.peaks[i])) if self.peaks[i] >= 1 else -1)
        tail = self.bg * (R - X - n * (self.BAR + self.GAP))
        rows = []
        for c in range(self.cells):   # bottom cell first
            lit, dark, peak = self.lit[c], self.dark, self.peak
            rows.append(b"".join([lit if c < h else peak if c == p else dark for h, p in zip(heights, tops)]) + tail)
        out = []
        for y in range(VIZ_H):
            left, right = self.edges[1][y]
            out += (left, rows[(VIZ_H - 1 - y) // SCALE], right)
        return b"".join(out)


def draw(now, track):
    """everything that only changes with the song (or the minute), 1920x515 RGB"""
    img = Image.new("RGB", SCREEN, BG); d = ImageDraw.Draw(img)
    d.rectangle((15, 17, 16 + ART * 4, 18 + ART * 4), outline=RULE)
    cover = None
    if track and track.get("art"):
        try:
            cover = Image.open(io.BytesIO(base64.b64decode(track["art"]))).convert("RGB").resize((ART, ART))
        except Exception:
            cover = None   # a broken picture is just no picture
    if cover:
        img.paste(cover.resize((ART * 4, ART * 4), Image.NEAREST), (16, 18))
    else:
        d.rectangle((16, 18, 15 + ART * 4, 17 + ART * 4), fill=RAISED)
        text(img, (16 + ART * 2 - 32, 18 + ART * 2 - 8), "no cover", D, scale=1)

    player = (track or {}).get("player")
    text(img, (X, 20), "// 04 · NOW PLAYING" + (f" · {player.upper()}" if player else ""), O, scale=1)
    text(img, (R, 14), clock(now), W, right=True)
    if not track:
        text(img, (X, 50), "NOTHING PLAYING", G, scale=4)
        return img
    title = track["title"] or "?"
    scale = 4 if len(title) * 32 <= R - X else 3
    room = (R - X) // (8 * scale)
    text(img, (X, 44 if scale == 4 else 52), title if len(title) <= room else title[:room - 2] + "..", W, scale=scale)
    text(img, (X, 118), track["artist"][:(R - X) // 16], O)
    if track["album"] and track["album"] != title:
        text(img, (X, 156), track["album"][:(R - X) // 8], G, scale=1)
    return img


class Page:
    """now playing, as a page of the kiosk's cycle"""
    name, seconds, fps = "nowplaying", 30, 20

    def __init__(self, folder="/dev/shm/kiosk-nowplaying"):
        self.folder = folder
        self.track, self.track_mtime, self.bg = None, None, (None, None)
        self.spectrum, self.lines, self.bar, self.strip = Spectrum(), (None, None), (None, None), (None, None)

    def path(self, name):
        return os.path.join(self.folder, name)

    def frame(self):
        """the latest frame, or None if the stream has gone quiet"""
        try:
            if time.time() - os.path.getmtime(self.path("frame.json")) > STALE:
                return None
            return json.load(open(self.path("frame.json")))
        except (OSError, ValueError):
            return None

    def active(self):
        """whether the rotation should come here: only while something is playing"""
        f = self.frame()
        return bool(f and f.get("playing"))

    def start(self, now):
        pass   # background() reads the track, and only when it changes

    def background(self, now):
        mtime = os.path.getmtime(self.path("track.json")) if os.path.exists(self.path("track.json")) else None
        if mtime != self.track_mtime:
            self.track_mtime = mtime
            try:
                self.track = json.load(open(self.path("track.json")))
            except (OSError, ValueError):
                self.track = None
        key = (self.track_mtime, now.minute)
        if key != self.bg[0]:
            self.bg = (key, packed(draw(now, self.track)))
        return self.bg

    def regions(self, now, t):
        f = self.frame() or {"levels": [], "pos": 0, "playing": False}
        levels = f["levels"] if f["playing"] else [0] * len(f["levels"] or [0] * 48)
        if self.bg[1] is None:
            self.background(now)
        if self.strip[0] != self.bg[0]:   # the background behind the spectrum, the full screen's width (cover included)
            self.strip = (self.bg[0], self.bg[1].crop((0, VIZ_Y, SCREEN[0], VIZ_Y + VIZ_H)))   # cropped once a song
        viz = self.spectrum.draw(levels, self.strip[1])
        lyrics, pos = (self.track or {}).get("lyrics") or [], f["pos"]
        i = lyric_at(lyrics, pos)
        if (self.track_mtime, i) != self.lines[0]:   # the lyric lines only change when the line does
            img = Image.new("RGB", (R - X, 72), BG)
            if lyrics:
                room = (R - X) // 16
                if i >= 0:
                    text(img, (0, 0), lyrics[i][1][:room], W)
                if i + 1 < len(lyrics):
                    text(img, (0, 36), lyrics[i + 1][1][:room], D)
            self.lines = ((self.track_mtime, i), packed(img))
        length = (self.track or {}).get("length") or 0
        key = (int(pos), length, f["playing"])
        if key != self.bar[0]:
            img = Image.new("RGB", (R - X, 32), BG); d = ImageDraw.Draw(img)
            d.rectangle((0, 0, R - X - 1, 5), fill=RULE)
            if length:
                d.rectangle((0, 0, round((R - X - 1) * min(1, pos / length)), 5), fill=O)
            text(img, (0, 14), mmss(pos) if f["playing"] else "paused", G if f["playing"] else A, scale=1)
            if length:
                text(img, (R - X, 14), mmss(length), G, scale=1, right=True)
            self.bar = (key, packed(img))
        return [(viz, (0, VIZ_Y)), (self.lines[1], (X, LYRIC_Y)), (self.bar[1], (X, BAR_Y))]


def sample_art():
    """a stand-in cover: the gradient, as a PNG in base64 like the desktop sends"""
    img = gradient(ART).resize((ART, ART)).rotate(90); buf = io.BytesIO(); img.save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


SAMPLE = {"title": "Second Rate Town (Acoustic)", "artist": "Good Kid", "album": "Second Rate Town (Acoustic)",
          "player": "YouTube Music", "length": 157.0,
          "lyrics": [[10.0, "I've been living in a second rate town"], [14.5, "with a first rate feeling"],
                     [19.0, "that it's all gonna come around"]]}
LEVELS = [round(60 * abs(((i * 7) % 48) / 48 - 0.5) * 2) for i in range(48)]


def check():
    import tempfile
    from . import sink
    sink.check()
    assert lyric_at(SAMPLE["lyrics"], 5) == -1 and lyric_at(SAMPLE["lyrics"], 15) == 1 and lyric_at(SAMPLE["lyrics"], 99) == 2
    assert mmss(157) == "2:37" and gradient(10).getpixel((0, 9)) == O and gradient(11).getpixel((0, 0)) == M
    now = datetime(2026, 10, 14, 23, 50)
    for track in (dict(SAMPLE, art=sample_art()), dict(SAMPLE, art="not a png"), None, dict(SAMPLE, title="x" * 90)):
        assert draw(now, track).size == SCREEN, "draws with, without and with a broken cover"
    folder = tempfile.mkdtemp()
    page = Page(folder)
    assert not page.active() and page.background(now)[1].size == SCREEN, "nothing playing: skipped, but draws"
    assert len(page.regions(now, 0)) == 3, "and its regions draw too"
    sink.write(folder, "track.json", dict(SAMPLE, art=sample_art()))
    sink.write(folder, "frame.json", {"levels": LEVELS, "pos": 15.0, "playing": True})
    assert page.active(), "playing: in the rotation"
    key, bg = page.background(now)
    assert bg.mode == "LA" and page.background(now)[0] == key, "redrawn only when the song or minute changes"
    first = page.regions(now, 0)
    assert len(first[0][0]) == SCREEN[0] * VIZ_H * 2 and first[0][1] == (0, VIZ_Y) and VIZ_Y + VIZ_H <= BAR_Y, "full width, so it's one copy"
    assert 48 * (Spectrum.BAR + Spectrum.GAP) <= R - X, "48 bars fit"
    strip = Image.frombytes("LA", (SCREEN[0], VIZ_H), first[0][0]); cover = bg.crop((0, VIZ_Y, SCREEN[0], VIZ_Y + VIZ_H))
    assert strip.crop((0, 0, X, VIZ_H)).tobytes() == cover.crop((0, 0, X, VIZ_H)).tobytes(), "the cover shows through"
    assert page.regions(now, 0)[1][0] is first[1][0], "the lyrics are the same image until the line changes"
    sink.write(folder, "frame.json", {"levels": [0] * 48, "pos": 15.1, "playing": True})
    page.regions(now, 0.1)
    assert max(page.spectrum.peaks) > 0, "peaks hang on after the bars drop"
    for _ in range(200):
        page.regions(now, 0.2)
    assert max(page.spectrum.peaks) == 0, "then fall"
    os.utime(os.path.join(folder, "frame.json"), (1, 1))
    assert not page.active(), "a stream that's gone quiet counts as stopped"


def preview(now=None):
    """the page mid-song, for the emulator and kiosk.py --png"""
    import tempfile
    from . import sink
    folder = tempfile.mkdtemp()
    sink.write(folder, "track.json", dict(SAMPLE, art=sample_art()))
    sink.write(folder, "frame.json", {"levels": LEVELS, "pos": 15.0, "playing": True})
    page = Page(folder); now = now or datetime(2026, 10, 14, 23, 50)
    img = page.background(now)[1].copy()
    for _ in range(3):
        regions = page.regions(now, 0)
    for part, xy in regions:
        img.paste(Image.frombytes("LA", (SCREEN[0], len(part) // SCREEN[0] // 2), part) if isinstance(part, bytes) else part, xy)
    from kit import unpack
    return unpack(img)
