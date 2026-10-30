"""The slides page: cards of your own words, a few side by side, stepping through them while the page is up. For the
things a sign on the door would say: how to join, what tools there are, how to donate, how to get in touch.

Options (in playlist.json):
  cards   [{"title": "Visit", "lines": ["Open Saturdays, 10 to 4", "..."]}, ...]: up to 12 cards of up to 8 lines each. A long
          line wraps. If one card has too much for the big size, every card on screen with it goes small, so they match.
          A card can have "qr": "https://..." too, a QR code down its right side. That takes segno (python3-segno),
          wherever the page is drawn; without it, the card shows the address as a line instead
  title   the masthead's title (default SLIDES)
  per     how many cards side by side (1 to 4, default 3)
  turn    seconds each set of cards stays up (default 10). The page's seconds default to long enough to show them all
The cards are set in the playlist (or over SSH), not on the setup page: the form has no way to edit a list of cards yet.
"""
import functools, math
from datetime import datetime
from PIL import Image, ImageDraw

from kit import SCREEN, O, W, G, BG, RAISED, RULE, Simple, text, masthead

TOP, GAP, PAD = 104, 24, 24   # where the cards start (under the masthead), the space between them, and inside them
EXAMPLE = [{"title": "Slides", "lines": ["Put your own cards in this page's options: a title and a few lines each"]}]


def wrap(line, width):
    """line in lines of at most width characters, broken at spaces (a word longer than width is cut)"""
    out, now = [], ""
    for word in line.split():
        while len(word) > width:
            if now:
                out.append(now); now = ""
            out.append(word[:width]); word = word[width:]
        if not now:
            now = word
        elif len(now) + 1 + len(word) <= width:
            now += " " + word
        else:
            out.append(now); now = word
    return out + [now] if now else out


def groups(cards, per):
    """the cards in sets of at most per, as even as can be (7 by 3 is 3, 2, 2, not 3, 3, 1)"""
    n = math.ceil(len(cards) / per)
    size, extra = divmod(len(cards), n)
    out, i = [], 0
    for g in range(n):
        step = size + (g < extra)
        out.append(cards[i:i + step]); i += step
    return out


def fit(lines, w, h, scale):
    """lines wrapped for a card's body w x h at scale, or None if they don't fit"""
    wrapped = [wrap(line, w // (8 * scale) - 2) for line in lines]   # 2 for the bullet and its space
    step, gap = 16 * scale + 4, 6 * scale
    return wrapped if sum(len(x) * step for x in wrapped) + gap * (len(wrapped) - 1) <= h else None


@functools.cache
def qr(url):
    """url as a QR code, one pixel a module with its 2-module margin, light on dark ink (an "L" image), or None without
    segno"""
    try:
        import segno
    except ImportError:
        return None
    rows = segno.make(url, error="m", micro=False).matrix
    img = Image.new("L", (len(rows[0]) + 4, len(rows) + 4), 255)
    img.putdata([0 if 0 <= y - 2 < len(rows) and 0 <= x - 2 < len(rows[0]) and rows[y - 2][x - 2] else 255
                 for y in range(img.height) for x in range(img.width)])
    return img


def layout(c, box):
    """a card's body, under its title: (its lines, the room for them as (width, height), its QR code at size or None)"""
    x0, y0, x1, y1 = box
    w, h = x1 - x0 - 2 * PAD, y1 - PAD - (y0 + PAD + 64)
    code = qr(c["qr"]) if c.get("qr") else None
    if c.get("qr") and code is None:
        return c["lines"] + [c["qr"].split("://", 1)[-1]], (w, h), None   # no segno: the address, written out
    if code:
        code = code.resize((code.width * (h // code.width),) * 2, Image.NEAREST)
        w -= code.width + PAD
    return c["lines"], (w, h), code


def card(img, box, c, scale):
    """one card: a raised panel, its title in the accent, its lines as bullets at scale, and its QR code on the right"""
    x0, y0, x1, y1 = box
    ImageDraw.Draw(img).rectangle(box, fill=RAISED, outline=RULE, width=2)
    text(img, (x0 + PAD, y0 + PAD), c["title"][:(x1 - x0 - 2 * PAD) // 24].upper(), O, scale=3)
    lines, (w, h), code = layout(c, box)
    y, room = y0 + PAD + 64, y1 - PAD
    if code:
        square = Image.new("RGB", code.size, BG)
        square.paste(W, mask=code)   # light modules and margin, dark ink: what a phone's camera expects
        img.paste(square, (x1 - PAD - code.width, y))
    for lines_of in fit(lines, w, h, scale) or [wrap(line, w // (8 * scale) - 2) for line in lines]:
        for i, part in enumerate(lines_of):
            if y + 16 * scale > room:
                return   # shortcut: what doesn't fit even small is cut, no "…"; fine for a sign someone writes and looks at
            if i == 0:
                text(img, (x0 + PAD, y), "•", O, scale=scale)
            text(img, (x0 + PAD + 16 * scale, y), part, W, scale=scale)
            y += 16 * scale + 4
        y += 6 * scale


class Page(Simple):
    name = "slides"

    def __init__(self, cards=None, title="SLIDES", per=3, turn=10):
        cards = EXAMPLE if cards is None else cards
        if not isinstance(cards, list) or not 1 <= len(cards) <= 12:
            raise ValueError("cards has to be a list of 1 to 12 cards")
        for c in cards:
            if not (isinstance(c, dict) and isinstance(c.get("title"), str) and isinstance(c.get("lines"), list)
                    and len(c["lines"]) <= 8 and all(isinstance(line, str) for line in c["lines"])
                    and (c.get("qr") is None or isinstance(c["qr"], str) and 0 < len(c["qr"]) <= 300)):
                raise ValueError('each card is {"title": "...", "lines": ["...", ...]}, with up to 8 lines, and maybe "qr": "<an address>"')
        if not (isinstance(per, int) and 1 <= per <= 4) or not (isinstance(turn, (int, float)) and turn >= 3):
            raise ValueError("per is 1 to 4, and turn at least 3 seconds")
        self.cards, self.title, self.turn = cards, str(title)[:40].upper(), turn
        self.sets = groups(cards, per)
        self.seconds = turn * len(self.sets)
        self.began = datetime.now()

    def start(self, now):
        self.began = now   # every visit starts at the first set

    def showing_set(self, now):
        return int(max(0, (now - self.began).total_seconds()) // self.turn) % len(self.sets)

    def redraw_on(self, now):
        return self.showing_set(now)

    def draw(self, img, now, data):
        n = self.showing_set(now)
        note = f"{n + 1} OF {len(self.sets)}" if len(self.sets) > 1 else None
        masthead(img, now, "// SLIDES", self.title, note and (note, G))
        cards = self.sets[n]
        w = (SCREEN[0] - 2 * GAP - GAP * (len(cards) - 1)) // len(cards)
        boxes = [(GAP + i * (w + GAP), TOP, GAP + i * (w + GAP) + w, SCREEN[1] - GAP) for i in range(len(cards))]
        # one size for the whole set: the big one if every card fits it, so the cards on screen match
        scale = 2 if all(fit(layout(c, b)[0], *layout(c, b)[1], 2) is not None for c, b in zip(cards, boxes)) else 1
        for c, b in zip(cards, boxes):
            card(img, b, c, scale)


def check():
    assert wrap("one two three four", 9) == ["one two", "three", "four"] and wrap("abcdefghij", 4) == ["abcd", "efgh", "ij"]
    assert wrap("", 5) == [] and [len(g) for g in groups(list(range(7)), 3)] == [3, 2, 2]
    assert [len(g) for g in groups(list(range(3)), 3)] == [3] and [len(g) for g in groups(list(range(4)), 1)] == [1] * 4
    Page.check()
    cards = [{"title": f"Card {i}", "lines": ["a line long enough that it has to wrap at least once on a card"] * 8} for i in range(7)]
    page = Page(cards=cards, title="Our space")
    assert page.seconds == 30 and len(page.sets) == 3
    t0 = datetime(2026, 10, 19, 9, 41)
    page.start(t0)
    assert [page.showing_set(t0.replace(second=s)) for s in (0, 9, 10, 25, 30)] == [0, 0, 1, 2, 0]
    for s in (0, 10, 20):
        assert page.picture(t0.replace(second=s), None, safe=False).size == SCREEN
    with_qr = Page(cards=[{"title": "Join", "lines": ["Scan me"], "qr": "https://example.org/join"}])
    assert with_qr.picture(t0, None, safe=False).size == SCREEN   # a QR code with segno, the address written out without
    if qr("https://example.org/join") is None:
        assert layout(with_qr.cards[0], (0, TOP, 600, 491))[0][-1] == "example.org/join"
    for bad in ([], "x", [{"title": 1, "lines": []}], [{"title": "t", "lines": ["x"] * 9}],
                [{"title": "t", "lines": [], "qr": ""}], [{"title": "t", "lines": [], "qr": 5}]):
        try:
            Page(cards=bad); raise AssertionError(f"took {bad!r}")
        except ValueError:
            pass
    for per, turn in ((0, 10), (5, 10), (3, 1)):
        try:
            Page(per=per, turn=turn); raise AssertionError(f"took per {per}, turn {turn}")
        except ValueError:
            pass


def preview(now=None):
    return Page.preview(now)
