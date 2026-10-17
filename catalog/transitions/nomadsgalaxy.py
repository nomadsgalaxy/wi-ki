"""Nomads Galaxy: hyperspace, in three beats. Spool up: the old page parts from the middle onto deep space, which has a
faint tunnel in it, and a bright core opens at the vanishing point. The jump: streaks fan out of the core with a white
head and a long tail, and rings of light rush out of the middle one after another, violet, then Warp Cyan, then Nebula
Magenta, while the Drifter comes down the tunnel at us. At the peak one amber ring bursts out of the core (once, about 7
of the 72 frames, and only a ring, never the whole screen) and the Drifter breaks away to the left, clear of the screen
before the page opens over it. Drop out: the new page opens from the middle between three beams, which fall away before
they reach the header, and the tunnel with them.
"""
import math, random

from PIL import Image, ImageDraw

import kit
from kit import O, B, W, M, A, BG, drifter
from .canvas import WIDTH, HEIGHT, colour, sprite

STARS, RINGS = 26, 4
SHIPS = [sprite(drifter(), s) for s in (1, 2, 3)]   # the Drifter coming down the tunnel
CX, MID = WIDTH // 2, HEIGHT // 2
REACH = CX + 160   # how far out a star goes before it's past the edge
BURST = (0.5, 0.6)   # when the amber ring bursts (t): 7 of 72 frames
HEADER = 90   # the page's header (clock and all) is above this row; the beams stay below it
RATIO = WIDTH / HEIGHT   # rings are as wide as the bar, so they're wide, not round


def tunnel():
    """what's behind the old page, made once: deep space with faint spokes and rings running to the middle"""
    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(img)
    for i in range(32):
        a = i * math.tau / 32
        draw.line((CX, MID, CX + math.cos(a) * WIDTH, MID + math.sin(a) * WIDTH / RATIO * 1.4), (20, 22, 52), 2)
    for r in (0.07, 0.15, 0.27, 0.45, 0.72):
        h = r * HEIGHT
        draw.ellipse((CX - h * RATIO / 1.9, MID - h / 1.9, CX + h * RATIO / 1.9, MID + h / 1.9), None, (24, 34, 66), 2)
    return kit.rgb565(img)


SPACE = tunnel()


def ease(t, a, b):
    """0 before a, 1 after b, smoothly in between"""
    u = min(1.0, max(0.0, (t - a) / (b - a)))
    return u * u * (3 - 2 * u)


def speed(t):
    """how fast the stars go at t (0 to 1): spool up, the jump, and drop out"""
    return 0.3 + 4.5 * math.sin(math.pi * min(1.0, max(0.0, (t - 0.05) / 0.85))) ** 2


def ring(c, half, rgb, thick):
    """a frame of four corner brackets, `half` rows from the middle to its top and bottom: a ring of the tunnel seen
    edge on. Only the corners, so it costs a few dozen rows however big it gets."""
    w, arm = round(half * RATIO), min(half, 9)
    for sx in (-1, 1):
        for sy in (-1, 1):
            x, y = CX + sx * w, MID + sy * half
            run = round(w * 0.4)   # how far the top and bottom arms reach
            c.fill(x - run if sx > 0 else x, y - thick if sy > 0 else y, run, thick, rgb)
            c.fill(x - thick if sx > 0 else x, y - arm if sy > 0 else y + thick, thick, arm - thick, rgb)


def frames(c, count):
    rng = random.Random()
    # each star: which way it goes (-1 left, 1 right), its slope, how fast, where it starts, and its head colour
    stars = [(rng.choice((-1, 1)), rng.uniform(-0.5, 0.5), rng.uniform(0.6, 1.4), rng.random(),
              M if i % 6 == 0 else A if i % 11 == 0 else W) for i in range(STARS)]
    travel, parted, opened = 0.0, 0, 0
    for k in range(count):
        t = k / max(1, count - 1)   # a lone frame is the FIRST one (t=0, the old page); play() asks for 72 and lands on the new page itself
        v = speed(t)
        travel += v / count
        # spool up: the old page parts onto space; drop out: the new page opens over it
        p = round(ease(t, 0.0, 0.3) * (MID + 8)) // 2 * 2
        c.reveal(0, MID - p, WIDTH, p - parted, SPACE); c.reveal(0, MID + parted, WIDTH, p - parted, SPACE)
        parted = p
        r = round(ease(t, 0.62, 0.92) * (MID + 8)) // 4 * 4
        c.reveal(0, MID - r, WIDTH, r - opened); c.reveal(0, MID + opened, WIDTH, r - opened)
        opened = r
        fade = 1.0 if t < 0.85 else (1 - t) / 0.15   # dropping out, the tunnel thins away
        tail = O if v > 2.2 else B   # the tails go from violet to Warp Cyan as it speeds up
        for side, slope, s, start, head in stars[:round(STARS * fade)]:
            d = ((start + travel * s) % 1.0) ** 1.7 * REACH   # slow near the middle, fast at the edges, like depth
            length = max(3, round(d * v * 0.3))
            y0 = MID + d * slope
            if not MID - p <= y0 < MID + p or (MID - r - 8 <= y0 < MID + r + 8 and t < 0.85) or (r and y0 < HEADER):
                continue   # only in space, not over the new page while it opens (or its header)
            thick = 3 if d > REACH / 2 else 2
            n = min(2, 1 + length // 90)
            for j in range(n):   # a long streak steps along its slope, so the fan reads as rays
                d0, d1 = d - length + length * j / n, d - length + length * (j + 1) / n
                x = CX + side * round(d1)
                c.fill(x - round(d1 - d0) if side > 0 else x, round(MID + d0 * slope), round(d1 - d0), thick, tail)
            hx = CX + side * round(d)
            c.fill(hx - 14 if side > 0 else hx, round(y0), 14, thick, head)   # the bright head
        if p > 8 and fade:
            for i in range(RINGS):   # rings rush out of the middle, each a little further on, in violet, cyan, magenta
                z = ((i / RINGS + travel * 0.9) % 1.0) ** 2.2
                half = round(6 + z * MID * 1.5)
                if half <= r + 6 or half > MID * 1.4 or p < half * 0.25:
                    continue   # not over the new page, off the edge, or before space has opened this far
                ring(c, half, B if z < 0.15 else O if z < 0.45 else M, 2 if z < 0.2 else 3 if z < 0.5 else 4)
        if 0.3 < t < 0.9 and fade:   # the bright core at the vanishing point, wider and hotter as it speeds up
            w = round(30 + v * 22)
            c.fill(CX - w, MID - 2, 2 * w, 4, B); c.fill(CX - w // 2, MID - 1, w, 2, O); c.fill(CX - w // 5, MID - 1, w * 2 // 5, 2, W)
        flash = ease(t, *BURST)   # one amber ring bursts from the core: 7 frames, local, and it's over
        if 0 < flash < 1:
            ring(c, round(10 + flash * MID * 1.2), A, 6)
        if t > 0.12:
            ship = SHIPS[min(len(SHIPS) - 1, int((t - 0.12) * 2.2 * len(SHIPS)))]   # out of the tunnel, coming closer
            u = ease(t, 0.55, 0.66)   # then it breaks away to the left after the burst, off before the page opens past it
            sway = round(math.sin(t * 14) * 10 * (1 - u))
            if u < 1 and not r:   # never over the new page
                c.draw(ship, round(CX - ship["w"] / 2 - u * (CX + ship["w"])), MID - ship["h"] // 2 + sway)
        beam = 8 if 0.68 < t < 0.76 else 4   # the beams thicken once, as the page comes through
        if r and MID - r - 3 * beam > HEADER:   # and are gone before they cross the clock
            for k2, rgb in enumerate((M, B, O)):
                c.fill(0, MID - r - (3 - k2) * beam, WIDTH, beam, rgb); c.fill(0, MID + r + k2 * beam, WIDTH, beam, rgb)
        yield
