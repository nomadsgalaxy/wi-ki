"""Tetris: the stack goes up fast. Tetrominoes hard-drop onto the old page and lock into place until the screen is
full, all but one column, the well. Then a long I piece drops into the well: TETRIS! The four lines flash one after
another and clear, and the new page is there underneath.

The screen is four lines of big blocks, so one I piece clears it all. The pieces are real tetrominoes (I, O, L and J,
in the game's colours), worked out to fill the stack exactly, and they land bottom first so none hangs in the air.
"""
import random, threading
from functools import cache
from PIL import Image, ImageDraw

from .canvas import WIDTH, HEIGHT, sprite, banner

SECONDS = 4
CELL = 128                                   # a block, in screen pixels
COLUMNS, LINES = WIDTH // CELL, 4            # 15 across and 4 down: a Tetris clears the lot
TOP = HEIGHT - LINES * CELL                  # the few rows above the stack
WELL = 10                                    # the column left open for the I piece
DROP = 192                                   # pixels a piece falls a frame: a hard drop
CYAN, YELLOW, ORANGE, BLUE = (0, 240, 240), (240, 240, 0), (240, 160, 0), (0, 80, 240)
FLASH = (255, 255, 255)
FILL, LAND, CLEAR = 0.55, 0.66, 0.70         # when the stack's full, the I piece lands, and the lines start clearing
SAYS = banner("TETRIS!", (255, 255, 255), (160, 0, 240), scale=6, border=CYAN)


def block(colour):
    """one block, bevelled like the game's: light along the top and left, dark along the bottom and right"""
    light, dark = tuple(min(255, c + 90) for c in colour), tuple(c * 5 // 10 for c in colour)
    img = Image.new("RGB", (CELL, CELL), colour); d = ImageDraw.Draw(img); b = CELL // 8
    d.polygon([(0, 0), (CELL - 1, 0), (CELL - 1 - b, b), (b, b), (b, CELL - 1 - b), (0, CELL - 1)], fill=light)
    d.polygon([(CELL - 1, CELL - 1), (0, CELL - 1), (b, CELL - 1 - b), (CELL - 1 - b, CELL - 1 - b), (CELL - 1 - b, b), (CELL - 1, 0)], fill=dark)
    d.rectangle((0, 0, CELL - 1, CELL - 1), outline=(0, 0, 0), width=2)
    return img


def piece(cells, colour):
    """a tetromino from its cells [(column, line)] -> (its sprite, its leftmost column, its top line)"""
    x0, y0 = min(c for c, _ in cells), min(l for _, l in cells)
    return shape(tuple(sorted((c - x0, l - y0) for c, l in cells)), colour), x0, y0


@cache   # a handful of shapes, each always the same colour: made once, not for every piece of every play (seconds on a Zero)
def shape(cells, colour):
    w, h = max(c for c, _ in cells) + 1, max(l for _, l in cells) + 1
    img, one = Image.new("RGBA", (w * CELL, h * CELL)), block(colour).convert("RGBA")
    for c, l in cells:
        img.paste(one, (c * CELL, l * CELL))
    return sprite(img)


def warm():
    """every shape a stack can have, and the I piece in the well, made ahead, while the kiosk's just showing a page"""
    for kind in ("II", "OO", "LJ", "JL"):
        for cells, colour in stack(random.Random(), [kind]):
            piece(cells, colour)
    piece([(WELL, l) for l in range(LINES)], CYAN)


def stack(rng, kinds=("II", "OO", "LJ", "JL")):
    """the tetrominoes that fill every column but the well, two columns at a time -> [(cells, colour)], bottom first.
    Each pair of columns is two I pieces, two O pieces, or an L and a J locked together"""
    pairs = [c for c in range(COLUMNS) if c != WELL]
    out = []
    for a, b in zip(pairs[::2], pairs[1::2]):
        kind = rng.choice(kinds)
        if kind == "II":
            out += [([(a, l) for l in range(4)], CYAN), ([(b, l) for l in range(4)], CYAN)]
        elif kind == "OO":
            out += [([(a, 2), (b, 2), (a, 3), (b, 3)], YELLOW), ([(a, 0), (b, 0), (a, 1), (b, 1)], YELLOW)]
        else:   # one stands on the bottom, three tall with a foot; the other hangs over it from the top
            low, high = (a, b) if kind == "LJ" else (b, a)
            out += [([(high, 1), (high, 2), (high, 3), (low, 3)], BLUE), ([(low, 0), (low, 1), (low, 2), (high, 0)], ORANGE)]
    rng.shuffle(out)
    return sorted(out, key=lambda p: -max(l for _, l in p[0]))   # bottom first: nothing lands on thin air



threading.Thread(target=warm, daemon=True).start()


def frames(c, count):
    pieces = [(*piece(cells, colour), i) for i, (cells, colour) in enumerate(stack(random.Random()))]
    well, wx, _ = piece([(WELL, l) for l in range(LINES)], CYAN)
    speed = DROP * max(1, count - 1)             # a drop's speed, in pixels per whole transition
    landed, cleared = set(), set()
    for k in range(count):
        t = k / max(1, count - 1)                # a lone frame is the first; play() lands on the new page
        for spr, x, line, i in pieces:           # the stack: one piece after another, each falling till it lands
            if i in landed:
                continue
            start = FILL * 0.8 * i / max(1, len(pieces) - 1)
            if t < start:
                continue
            target = TOP + line * CELL
            y = min(target, -spr["h"] + (t - start) * speed)
            if y >= target:
                c.stamp(spr, x * CELL, target); landed.add(i)
            else:
                c.draw(spr, x * CELL, round(y))
        if FILL <= t and "I" not in landed:      # the I piece, down the well
            y = min(TOP, -well["h"] + (t - FILL) / (LAND - FILL) * (TOP + well["h"]))
            if y >= TOP:
                c.stamp(well, wx * CELL, TOP); landed.add("I")
            else:
                c.draw(well, wx * CELL, round(y))
        if t >= CLEAR:                           # the four lines flash white one after another, then clear
            for line in range(LINES):
                at = CLEAR + line * 0.04
                if line not in cleared and at <= t < at + 0.04:
                    c.fill(0, TOP + line * CELL, WIDTH, CELL, FLASH)
                elif line not in cleared and t >= at + 0.04:
                    c.reveal(0, TOP + line * CELL if line else 0, WIDTH, CELL + (TOP if not line else 0)); cleared.add(line)
        if LAND <= t < 0.95:                     # and the banner
            c.draw(SAYS, (WIDTH - SAYS["w"]) // 2, (HEIGHT - SAYS["h"]) // 2)
        yield
