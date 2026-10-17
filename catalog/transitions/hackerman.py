"""Hackerman: a neon terminal types its way in (HACKERMAN v1.985 ... hacking time ... ACCESS GRANTED) while the new page
glitches in behind it, band by band, VHS style, until the terminal blinks out.
"""
import random
from PIL import Image

import kit
from .canvas import WIDTH, HEIGHT, sprite

PINK, CYAN, BLACK, SCAN = (255, 40, 170), (0, 240, 255), (10, 0, 20), (0, 110, 125)
LINES = ["HACKERMAN v1.985", "> bypassing the firewall...", "> rerouting the mainframe...", "> hacking time...",
         "> ACCESS GRANTED"]
BOX_W, BOX_H = 760, 240


def terminal(shown):
    """the terminal with its first `shown` lines typed, as a solid sprite (one run a row: cheap)"""
    img = Image.new("RGB", (BOX_W, BOX_H), PINK)
    img.paste(BLACK, (4, 4, BOX_W - 4, BOX_H - 4))
    for i, line in enumerate(LINES[:shown]):
        kit.text(img, (24, 20 + i * 36), line, CYAN if i < len(LINES) - 1 else PINK)
    return sprite(img)


TERMINALS = [terminal(n) for n in range(len(LINES) + 1)]


def frames(c, count):
    rng, x, y, closing = random.Random(), (WIDTH - BOX_W) // 2, (HEIGHT - BOX_H) // 2, False
    for k in range(count):
        t = k / max(1, count - 1)   # a lone frame is the FIRST one (t=0, the terminal opening), not a divide by zero; play() lands on the new page
        for _ in range(round(1 + t * t * 12)):   # glitch bands of the new page, more and more of them
            top, h = rng.randrange(HEIGHT // 4) * 4, rng.choice((4, 8, 16, 24))
            c.reveal(0, top, WIDTH, h)
        for _ in range(2):                        # and some that are still slipping sideways
            c.smear(rng.randrange(HEIGHT // 4) * 4, rng.choice((4, 8)), rng.randrange(-120, 120))
        if t < 0.85:                              # then the terminal's gone, and the page settles
            shown = min(len(LINES), int(t / 0.6 * len(LINES)))
            c.draw(TERMINALS[shown], x, y, keep=True)   # it stays put
            if shown and k // 6 % 2 == 0:   # a cursor blinking after the last typed line, twice a second at 24 fps
                c.fill(x + 24 + len(LINES[shown - 1]) * 16 + 4, y + 20 + (shown - 1) * 36, 14, 28, CYAN)
            c.fill(x + 4, y + 4 + k * 5 % (BOX_H - 8), BOX_W - 8, 2, SCAN)   # and a dim scanline rolling down the glass
            if t > 0.6:   # the progress bar under ACCESS GRANTED
                c.fill(x + 24, y + BOX_H - 34, round((BOX_W - 48) * (t - 0.6) / 0.25), 12, PINK)
            closing = True
        elif closing:
            c.clear(x, y, BOX_W, BOX_H); closing = False
        yield
