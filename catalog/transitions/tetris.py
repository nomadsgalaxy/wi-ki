"""Tetris: blocks hard-drop onto the old page and lock into place, the bottom line first. Each line that fills up
clears, with a white flash along it, and the new page is there underneath. Line by line it stacks up to the top.

The pieces are flat bits of tetrominoes, one line high, in the game's own seven colours, so a line always fills
exactly. The drops are fast, like a hard drop, and they come one after another, so only a few pieces are falling at
once: each one costs a copy a row.
"""
import random
from PIL import Image, ImageDraw

from .canvas import WIDTH, HEIGHT, sprite

SECONDS = 4
CELL = 64                                    # a block, in screen pixels
COLUMNS, LINES = WIDTH // CELL, -(-HEIGHT // CELL)   # 30 across, 9 lines (the top one only partly on the screen)
DROP = 160                                   # pixels a piece falls a frame: a hard drop
COLOURS = ((0, 240, 240), (240, 240, 0), (160, 0, 240), (0, 240, 0), (240, 0, 0), (0, 0, 240), (240, 160, 0))   # I O T S Z J L
FLASH = (255, 255, 255)


def block(colour):
    """one block, bevelled like the game's: light along the top and left, dark along the bottom and right"""
    light, dark = tuple(min(255, c + 90) for c in colour), tuple(c * 5 // 10 for c in colour)
    img = Image.new("RGB", (CELL, CELL), colour); d = ImageDraw.Draw(img)
    d.polygon([(0, 0), (CELL - 1, 0), (CELL - 9, 8), (8, 8), (8, CELL - 9), (0, CELL - 1)], fill=light)
    d.polygon([(CELL - 1, CELL - 1), (0, CELL - 1), (8, CELL - 9), (CELL - 9, CELL - 9), (CELL - 9, 8), (CELL - 1, 0)], fill=dark)
    d.rectangle((0, 0, CELL - 1, CELL - 1), outline=(0, 0, 0))
    return img


def piece(length, colour):
    """a flat piece, length blocks long -> a sprite"""
    img, one = Image.new("RGB", (length * CELL, CELL)), block(colour)
    for k in range(length):
        img.paste(one, (k * CELL, 0))
    return sprite(img)


PIECES = {(n, colour): piece(n, colour) for n in (1, 2, 3, 4) for colour in COLOURS}


def plan(count, rng):
    """when each piece drops, and where -> ([(start frame, line, column, length, colour)], [the frame each line clears])
    Lines go from the bottom (0) up. The pieces start one after another, evenly through the transition, so only a few
    are ever falling at once; a line clears two frames after its last piece lands, and the top one on the last frame."""
    order = []
    for line in range(LINES):
        lengths, left = [], COLUMNS
        while left:
            n = min(left, rng.choice((4, 4, 3, 3, 2, 1)))
            lengths.append(n); left -= n
        x, pieces = 0, []
        for n in lengths:
            pieces.append((line, x, n, rng.choice(COLOURS))); x += n
        rng.shuffle(pieces)   # a line fills in any order
        order += pieces
    fall = lambda line: max(1, -(-(HEIGHT - line * CELL) // DROP))   # frames to land, from just above the screen
    room = max(1, count - 1 - fall(LINES - 1) - 2)   # the last piece still lands, and its line flashes, in time
    drops = [(round(i * room / max(1, len(order) - 1)), *p) for i, p in enumerate(order)]
    clears, last = [], 0
    for line in range(LINES):
        last = max([last] + [at + fall(line) for at, l, *_ in drops if l == line]) + 2
        clears.append(min(last, max(1, count - 1)))   # never on the first frame: that one is still the old page
    return drops, clears


def frames(c, count):
    drops, clears = plan(count, random.Random())
    falling, done = [], set()
    for k in range(count):
        for d in drops:                       # new pieces start just above the screen
            if d[0] == k:
                falling.append([d, -CELL])
        for f in falling[:]:                  # the rest fall, and lock in where they land
            (_, line, x, n, colour), y = f
            top = HEIGHT - (line + 1) * CELL
            y = min(top, y + DROP)
            if y == top:
                c.stamp(PIECES[n, colour], x * CELL, y)   # part of the old page now, till its line clears
                falling.remove(f)
            else:
                f[1] = y
                c.draw(PIECES[n, colour], x * CELL, y)
        for line, at in enumerate(clears):
            top = HEIGHT - (line + 1) * CELL
            if line not in done and at - 2 <= k < at:   # the flash, along the line only
                c.fill(0, top, WIDTH, CELL, FLASH)
            elif line not in done and k >= at:
                c.reveal(0, top, WIDTH, CELL); done.add(line)   # whole rows: one copy
        yield
