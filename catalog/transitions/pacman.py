"""Pac-Man: a maze builds itself over the old page, top to bottom, in the arcade's blue walls with a dot down every
corridor and a power pellet at each turn. Then Pac-Man comes in on the left and eats his way through it: along the top
corridor, down at the end, back along the middle, down again and out along the bottom. Wherever he's been, the maze is
gone and the new page is there.

He's arcade pixel art, 16 pixels scaled up 7 times, mouth opening and closing, facing the way he's going. The maze is
one picture made once and laid down in whole rows, which costs next to nothing; revealing behind him costs a copy for
each row of his lane every frame, and he's kept small enough that he and his wipe fit beside that.
"""
import math, threading
from functools import cache
from PIL import Image, ImageChops, ImageDraw

import kit
from .canvas import WIDTH, HEIGHT, sprite

SECONDS = 4
LANES = 3
LANE = -(-HEIGHT // LANES)                  # 172 rows: each corridor, with its walls, is a lane
SCALE = 7
SIZE = 16 * SCALE                           # Pac-Man, on the screen
HALF = 64                                   # half a corridor's height
YELLOW, DOT, WALL = (255, 230, 0), (255, 184, 151), (33, 33, 255)
GAP = 64                                    # between dots
TURN = 110                                  # the corridors turn down this far in from the screen's edges
BUILD = 0.15                                # of the transition, the maze takes this long to build; then he goes
MIDDLE = [lane * LANE + LANE // 2 for lane in range(LANES)]   # each corridor's middle
# his path, corner to corner: in from the left, then back and forth, and out on the right
PATH = [(-SIZE // 2, MIDDLE[0]), (WIDTH - TURN, MIDDLE[0]), (WIDTH - TURN, MIDDLE[1]), (TURN, MIDDLE[1]),
        (TURN, MIDDLE[2]), (WIDTH + SIZE // 2, MIDDLE[2])]
LEGS = [math.dist(a, b) for a, b in zip(PATH, PATH[1:])]


def pacman(mouth, facing):
    """Pac-Man with his mouth open mouth degrees each side, facing "right", "left" or "down" -> a sprite"""
    img = Image.new("RGBA", (16, 16))
    for y in range(16):
        for x in range(16):
            dx, dy = x - 7.5, y - 7.5
            if dx * dx + dy * dy <= 7.3 * 7.3 and not (dx > 0 and abs(math.degrees(math.atan2(dy, dx))) < mouth):
                img.putpixel((x, y), YELLOW + (255,))
    img = {"right": img, "left": img.transpose(Image.FLIP_LEFT_RIGHT), "down": img.rotate(-90)}[facing]
    return sprite(img, SCALE)


CHOMP = (0, 20, 45, 20)                     # his mouth, frame by frame: shut, open, wide, open
FACES = {(m, f): pacman(m, f) for m in set(CHOMP) for f in ("right", "left", "down")}


@cache
def maze():
    """the maze, the whole screen of it in packed bytes: black, corridors along his path with blue double walls round
    them, dots along the middle and a power pellet at every turn"""
    def grow(n):
        """the corridors, n pixels wider all round. They're rectangles, so that's each one drawn n bigger: the same as a
        (2n + 1)-square max filter over them, and quick, where the filter took over half a minute on a Pi Zero"""
        img = Image.new("L", (WIDTH, HEIGHT)); d = ImageDraw.Draw(img)
        for (x0, y0), (x1, y1) in zip(PATH, PATH[1:]):
            d.rectangle((min(x0, x1) - HALF - n, min(y0, y1) - HALF - n, max(x0, x1) + HALF + n, max(y0, y1) + HALF + n), fill=255)
        return img
    img = Image.new("RGB", (WIDTH, HEIGHT))
    for outer, inner in ((5, 3), (13, 11)):   # the arcade's walls: two thin blue lines, a little apart
        img.paste(WALL, (0, 0), ImageChops.subtract(grow(outer), grow(inner)))
    d = ImageDraw.Draw(img)
    for (x0, y0), (x1, y1) in zip(PATH, PATH[1:]):   # the dots, every GAP along the way
        n = round(math.dist((x0, y0), (x1, y1)) / GAP)
        for k in range(1, n):
            x, y = x0 + (x1 - x0) * k / n, y0 + (y1 - y0) * k / n
            if 0 < x < WIDTH:
                d.rectangle((x - 5, y - 5, x + 5, y + 5), fill=DOT)
    for x, y in PATH[1:-1]:                    # and the power pellets
        d.ellipse((x - 16, y - 16, x + 16, y + 16), fill=DOT)
    return kit.rgb565(img)


threading.Thread(target=maze, daemon=True).start()   # made ahead, while a page shows, not on his first frame


def at(s):
    """his middle and which way he's facing, s pixels along the path"""
    for (a, b), leg in zip(zip(PATH, PATH[1:]), LEGS):
        if s <= leg:
            k = s / leg
            facing = "down" if a[0] == b[0] else "right" if b[0] > a[0] else "left"
            return (a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k), facing
        s -= leg
    return PATH[-1], "right"


def frames(c, count):
    backdrop, built = maze(), 0
    shown = [0] * LANES                         # how far each lane's new page is in, from where he starts it
    for k in range(count):
        t = k / max(1, count - 1)               # a lone frame is the first; play() lands on the new page
        rows = min(HEIGHT, round(t / BUILD * HEIGHT))
        if rows > built:                        # the maze, laid down from the top in whole rows
            c.reveal(0, built, WIDTH, rows - built, src=backdrop); built = rows
        if t <= BUILD:
            yield; continue
        (x, y), facing = at((t - BUILD) / (1 - BUILD) * sum(LEGS))
        lane = min(LANES - 1, int(y // LANE))
        for done in range(lane):                # lanes he's left: all eaten
            if shown[done] < WIDTH:
                c.reveal(0, done * LANE, WIDTH, LANE); shown[done] = WIDTH
        rightwards = lane % 2 == 0
        reach = max(0, min(WIDTH, round(x))) if rightwards else WIDTH - max(0, min(WIDTH, round(x)))
        if reach > shown[lane]:                 # behind him, to his middle
            a, b = (shown[lane], reach) if rightwards else (WIDTH - reach, WIDTH - shown[lane])
            c.reveal(a, lane * LANE, b - a, LANE); shown[lane] = reach
        c.draw(FACES[CHOMP[k % len(CHOMP)], facing], round(x - SIZE / 2), round(y - SIZE / 2))
        yield
