"""The Matrix: code rain. Forty columns of green glyphs fall at their own speeds, each with a bright head, and behind
each column's trail the new page shows through, so the page comes in column by column through the rain.

The glyphs stay put and only the head moves, like in the film, so the rain is drawn once, twice over (green, and bright
for the heads), as whole screens. A frame then just copies a few rows per column from one of three places: bright rain
where the head arrives, green rain where it has just been, and the new page where the trail has passed. It never draws
anything that needs wiping, so the canvas runs bare (no clean copy), which halves the copies.
"""
import random
from PIL import Image

import kit
from .canvas import WIDTH, HEIGHT

SECONDS = 4.5
GLYPHS = "0123456789ABCDEFZ:.=*+-<>|$#@%&"
COLUMN, CELL, SCALE = 48, 48, 3     # each column is 48 px wide; glyphs are the VGA font at 3x, 24x48
TRAIL = 4 * CELL                   # how much rain hangs behind a head before the page shows through


def rain(colours, seed=76):
    """a whole screen of glyphs, one per cell, as packed bytes: the same glyphs every time, so the two versions line up"""
    rng, img = random.Random(seed), Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))
    for x in range(0, WIDTH, COLUMN):
        for y in range(0, HEIGHT, CELL):
            kit.text(img, (x + (COLUMN - 8 * SCALE) // 2, y), rng.choice(GLYPHS), rng.choice(colours), scale=SCALE)
    return kit.rgb565(img)


GREEN = rain([(0, 255, 70), (0, 200, 50), (0, 150, 40), (0, 110, 30)])
BRIGHT = rain([(210, 255, 210), (180, 255, 190)])


def frames(c, count):
    c.bare()
    rng, columns = random.Random(), range(0, WIDTH, COLUMN)
    start = {x: rng.uniform(0, 0.3) for x in columns}   # when each column's drop sets off, as a share of the time
    seen = {x: 0 for x in columns}                      # how far down each head has got
    for k in range(count):
        t = k / max(1, count - 1)   # a lone frame is the FIRST one (t=0, still the old page), not a divide by zero; play() lands on the new page
        for x in columns:
            f = max(0.0, (t - start[x]) / (1 - start[x]))   # this drop's own progress, 0 to 1
            head, was = round(f * (HEIGHT + TRAIL + CELL)), seen[x]
            if head > was:
                c.reveal(x, was, COLUMN, head - was, src=BRIGHT)                     # the head arrives, bright
                c.reveal(x, was - CELL, COLUMN, head - was, src=GREEN)               # and what it's passed settles
                c.reveal(x, was - CELL - TRAIL, COLUMN, head - was)                  # the trail's end: the new page
                seen[x] = head
        yield
