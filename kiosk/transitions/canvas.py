"""The canvas transitions draw on: the framebuffer's raw bytes, with no Pillow in sight once it starts, because on a Pi
Zero turning an image into bytes takes longer than a whole frame. Every copy costs about 45 us there whatever its size,
so a frame's cost is how many copies it makes: whole rows go in one copy, and a frame should stay under ~600.

It keeps two copies of the screen. `cur` is the old page with whatever has been revealed of the new one so far, and the
framebuffer is that plus this frame's decorations (glows, sprites). At the start of every frame the decorations are
wiped by copying `cur` back over them, so they can move without leaving trails.
"""
from functools import cache
from PIL import Image


import kit

WIDTH, HEIGHT = kit.SCREEN
STRIDE = WIDTH * 2   # bytes in one row of the screen


@cache   # packing goes through Pillow, far too slow to do for every fill on the Pi
def colour(rgb):
    """an (r, g, b) colour -> its two bytes"""
    return kit.rgb565(Image.new("RGB", (1, 1), rgb))


def banner(words, fg, bg, scale=4, pad=16, border=None):
    """words in the VGA font on a solid box, as a sprite. Solid means one run a row: cheap to draw, unlike loose text."""
    w, h = len(words) * 8 * scale + 2 * pad, 16 * scale + 2 * pad
    img = Image.new("RGB", (w, h), border or bg)
    img.paste(bg, (4, 4, w - 4, h - 4) if border else (0, 0, w, h))
    kit.text(img, (pad, pad), words, fg, scale=scale)
    return sprite(img)


def grid(art, palette, scale=1):
    """pixel art typed out as text, one character a pixel ('.' is see-through), with palette mapping characters to
    colours -> a sprite"""
    rows = [line for line in art.strip("\n").splitlines()]
    img = Image.new("RGBA", (max(map(len, rows)), len(rows)))
    for y, line in enumerate(rows):
        for x, ch in enumerate(line):
            if ch in palette:
                img.putpixel((x, y), palette[ch] + (255,))
    return sprite(img, scale)


def sprite(img, scale=1):
    """an RGBA image -> a sprite: for each row, its (x, bytes) runs of solid pixels. Made once, drawn every frame."""
    img = img.convert("RGBA").resize((img.width * scale, img.height * scale), Image.NEAREST)
    packed = kit.rgb565(img.convert("RGB")); alpha = img.getchannel("A").tobytes()
    rows = []
    for y in range(img.height):
        runs, x = [], 0
        while x < img.width:
            if alpha[y * img.width + x] < 128:
                x += 1; continue
            start = x
            while x < img.width and alpha[y * img.width + x] >= 128:
                x += 1
            runs.append((start, packed[(y * img.width + start) * 2:(y * img.width + x) * 2]))
        rows.append(runs)
    return {"w": img.width, "h": img.height, "rows": rows}


class Canvas:
    def __init__(self, mm, new):
        self.mm, self.new = mm, new
        self.cur = bytearray(mm[:len(new)])
        self.dirty = []   # where this frame drew decorations, to wipe at the start of the next

    def _rect(self, x, y, w, h):
        """a rectangle, clipped to the screen (None if nothing's left)"""
        x0, y0, x1, y1 = max(0, x), max(0, y), min(WIDTH, x + w), min(HEIGHT, y + h)
        return (x0, y0, x1 - x0, y1 - y0) if x1 > x0 and y1 > y0 else None

    def _copy(self, src, dsts, rect):
        x, y, w, h = rect
        if x == 0 and w == WIDTH:   # whole rows are one block: one copy
            a, b = y * STRIDE, (y + h) * STRIDE
            for dst in dsts:
                dst[a:b] = src[a:b]
            return
        for row in range(y, y + h):
            a = row * STRIDE + x * 2; b = a + w * 2
            for dst in dsts:
                dst[a:b] = src[a:b]

    def bare(self):
        """for a theme that never draws decorations: don't keep the clean copy (`cur`), which halves its copies"""
        self.cur = None

    def reveal(self, x, y, w, h, src=None):
        """show the new page (or src, a whole screen of packed bytes, like a backdrop) in this rectangle, for good"""
        if (r := self._rect(x, y, w, h)):
            self._copy(src or self.new, (self.mm,) if self.cur is None else (self.cur, self.mm), r)

    def fill(self, x, y, w, h, rgb, keep=False):
        """paint this rectangle for this frame only, or (keep) until something is revealed over it"""
        if (r := self._rect(x, y, w, h)):
            x, y, w, h = r; line = colour(rgb) * w
            if w == WIDTH:   # whole rows: one copy
                self.mm[y * STRIDE:(y + h) * STRIDE] = line * h
            else:
                for row in range(y, y + h):
                    a = row * STRIDE + x * 2; self.mm[a:a + w * 2] = line
            if not keep:
                self.dirty.append(r)

    def draw(self, spr, x, y, keep=False):
        """draw a sprite with its top left at (x, y), for this frame only, or (keep) until clear() or a reveal.
        Keep a sprite that stays put and gets drawn every frame anyway: it saves wiping it."""
        for dy, runs in enumerate(spr["rows"]):
            row = y + dy
            if not 0 <= row < HEIGHT:
                continue
            for dx, data in runs:
                left, right = max(0, x + dx), min(WIDTH, x + dx + len(data) // 2)
                if right > left:
                    a = row * STRIDE + left * 2
                    self.mm[a:a + (right - left) * 2] = data[(left - x - dx) * 2:(right - x - dx) * 2]
        if not keep and (r := self._rect(x, y, spr["w"], spr["h"])):
            self.dirty.append(r)

    def stamp(self, spr, x, y):
        """draw a sprite for good, as if it were part of the page: for one that's stopped moving"""
        mm, self.mm = self.mm, self.cur
        self.draw(spr, x, y, keep=True); self.mm = mm
        self.draw(spr, x, y, keep=True)

    def clear(self, x, y, w, h):
        """take kept paint off this rectangle"""
        if (r := self._rect(x, y, w, h)):
            self._copy(self.cur, (self.mm,), r)

    def rows(self, y, data):
        """draw whole rows of packed bytes from row y down, for this frame only"""
        top, bottom = max(0, y), min(HEIGHT, y + len(data) // STRIDE)
        if bottom > top:
            self.mm[top * STRIDE:bottom * STRIDE] = data[(top - y) * STRIDE:(bottom - y) * STRIDE]
            self.dirty.append((0, top, WIDTH, bottom - top))

    def smear(self, y, h, dx):
        """the new page's rows y to y + h, shoved dx pixels sideways, for this frame only (a glitch)"""
        if (r := self._rect(0, y, WIDTH, h)):
            for row in range(r[1], r[1] + r[3]):
                a = row * STRIDE; line = self.new[a:a + STRIDE]
                k = (dx % WIDTH) * 2; self.mm[a:a + STRIDE] = line[-k:] + line[:-k] if k else line
            self.dirty.append(r)

    def wipe(self):
        """take this frame's decorations off again"""
        for r in self.dirty:
            self._copy(self.cur, (self.mm,), r)
        self.dirty = []


def simple(shown):
    """the easy way to make a transition: shown(t) gives the parts of the new page showing at t, from 0 (none of it) to
    1 (all of it), as [(x, y, w, h)], and this turns it into frames(). A part stays shown once it is, so returning all
    of what's showing is fine, but each rectangle costs a copy every frame, or one a row when it isn't the screen's
    whole width: keep a frame under ~600. catalog/new/transition.py is one to start from."""
    def frames(c, count):
        c.bare()   # nothing to wipe: it only ever reveals
        seen = set()
        for k in range(count):
            for r in shown(k / max(1, count - 1)):   # a lone frame is t=0; play() lands on the new page
                if tuple(r) not in seen:   # a part already shown, exactly, costs nothing
                    seen.add(tuple(r)); c.reveal(*r)
            yield
    return frames
