"""Hive76: honeycomb. Hexagon cells spread out from a random spot; each one fills with honey for a frame, then opens onto
the new page. A pixel bee flies across while it happens.

Honey is Hive76 orange (246, 145, 31) and two shades of it, so neighbouring cells stand apart.
"""
import math, random
from PIL import Image, ImageDraw

from .canvas import WIDTH, HEIGHT, sprite

HONEY = [(246, 145, 31), (255, 179, 71), (214, 118, 20)]
CELL_W, CELL_H, BAND = 184, 160, 8   # a cell, and the steps its slanted sides are drawn in (big cells: fewer copies)


def cell_rows():
    """a flat-topped hexagon as (y, inset) bands. Insets round down, so neighbours overlap instead of leaving gaps."""
    bands = CELL_H // BAND
    return [(b * BAND, int(CELL_W / 4 * abs(b + 0.5 - bands / 2) / (bands / 2)) // BAND * BAND) for b in range(bands)]


def cells():
    """the top left of every cell that touches the screen, with its column and row"""
    out = []
    for col in range(WIDTH // (CELL_W * 3 // 4) + 2):
        for row in range(-1, HEIGHT // CELL_H + 2):
            x, y = col * CELL_W * 3 // 4 - CELL_W // 4, row * CELL_H + (CELL_H // 2 if col % 2 else 0)
            if x < WIDTH and y < HEIGHT and x + CELL_W > 0 and y + CELL_H > 0:
                out.append((x, y, col, row))
    return out


def bee(flap):
    """a 13x9 pixel bee facing right, drawn 4x, wings up (flap 0) or down (flap 1)"""
    img = Image.new("RGBA", (13, 9)); d = ImageDraw.Draw(img)
    wing = (220, 235, 255)
    top = 0 if flap == 0 else 2
    d.ellipse((3, top, 6, top + 3), fill=wing); d.ellipse((6, top, 9, top + 3), fill=wing)
    d.ellipse((1, 3, 10, 8), fill=(255, 206, 0))
    for x in (4, 7):
        d.line((x, 3, x, 8), fill=(20, 20, 20))
    d.ellipse((9, 4, 12, 7), fill=(20, 20, 20)); d.point((11, 5), fill=(255, 255, 255))
    d.point((0, 6), fill=(20, 20, 20))   # the stinger
    return sprite(img, 4)


BEES = [bee(0), bee(1)]


def frames(c, count):
    rows, rng = cell_rows(), random.Random()
    sx, sy = rng.randrange(WIDTH), rng.randrange(HEIGHT)
    order = sorted(cells(), key=lambda h: math.hypot(h[0] + CELL_W / 2 - sx, h[1] + CELL_H / 2 - sy) + rng.random() * CELL_W)
    last = max(1, count - 1)   # a lone frame fills every cell with honey (t=0, the whole honeycomb in one batch), not a divide by zero; play() lands on the new page
    batches = [order[i * len(order) // last:(i + 1) * len(order) // last] for i in range(last)] + [[]]
    for k in range(count):
        for x, y, _, _ in batches[k - 1] if k else []:   # last frame's honey opens up
            for dy, inset in rows:
                c.reveal(x + inset, y + dy, CELL_W - 2 * inset, BAND)
        for x, y, col, row in batches[k]:                # this frame's cells fill with honey
            for dy, inset in rows:
                c.fill(x + inset, y + dy, CELL_W - 2 * inset, BAND, HONEY[(col + row) % 3], keep=True)
        t = k / last
        c.draw(BEES[k % 2], round(-60 + t * (WIDTH + 60)), round(HEIGHT / 2 - 20 + math.sin(t * 6 * math.pi) * 90))
        yield
