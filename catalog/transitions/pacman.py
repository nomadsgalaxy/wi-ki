"""Pac-Man: a row of dots goes down each of three lanes across the old page, and Pac-Man chomps along them, left to
right, back right to left, and left to right again. The new page is there behind him wherever he's been.

He's arcade pixel art, 16 pixels scaled up 7 times, with his mouth opening and closing as he goes. A lane is a third of
the screen, so revealing behind him costs a copy for each of its rows every frame, and he's kept small enough that he
and his wipe fit in beside that.
"""
import math
from PIL import Image

from .canvas import WIDTH, HEIGHT, sprite, grid

SECONDS = 4
LANES = 3
LANE = -(-HEIGHT // LANES)                  # 172 rows
SCALE = 7
SIZE = 16 * SCALE                           # Pac-Man, on the screen
YELLOW, DOT = (255, 230, 0), (255, 184, 151)
GAP = 64                                    # between dots
TRIP = WIDTH + SIZE                         # how far he goes along a lane: in from off the edge, and out the other side


def pacman(mouth, left=False):
    """Pac-Man with his mouth open mouth degrees (each side of straight ahead), facing right or left -> a sprite"""
    img = Image.new("RGBA", (16, 16))
    for y in range(16):
        for x in range(16):
            dx, dy = x - 7.5, y - 7.5
            if dx * dx + dy * dy <= 7.3 * 7.3 and not (dx > 0 and abs(math.degrees(math.atan2(dy, dx))) < mouth):
                img.putpixel((x, y), YELLOW + (255,))
    if left:
        img = img.transpose(Image.FLIP_LEFT_RIGHT)
    return sprite(img, SCALE)


CHOMP = (0, 20, 45, 20)                     # his mouth, frame by frame: shut, open, wide, open
FACES = {(m, left): pacman(m, left) for m in set(CHOMP) for left in (False, True)}
PELLET = grid("""
.##.
####
####
.##.""", {"#": DOT}, 3)


def where(lane, s):
    """his left edge in lane, s pixels along it"""
    return -SIZE + s if lane % 2 == 0 else WIDTH - s


def frames(c, count):
    dots = [(x, lane * LANE + LANE // 2 - 6) for lane in range(LANES) for x in range(GAP // 2, WIDTH, GAP)]
    shown = [0] * LANES                     # how far each lane's new page is in, from where he started it
    for k in range(count):
        if k < LANES:                       # the dots, a lane a frame, as part of the old page: he eats them by revealing
            for x, y in dots:
                if (y - LANE // 2 + 6) // LANE == k:
                    c.stamp(PELLET, x - 6, y)
        s = k / max(1, count - 1) * LANES * TRIP   # how far he's gone, all lanes together: a lone frame is the first; play() lands on the new page
        lane = min(LANES - 1, int(s // TRIP))
        for done in range(lane):            # lanes behind him: all the way in
            if shown[done] < WIDTH:
                c.reveal(0, done * LANE, WIDTH, LANE); shown[done] = WIDTH
        along = s - lane * TRIP
        x = where(lane, along)
        mouth = max(0, min(WIDTH, round(x + SIZE / 2)))   # the middle of him: everything he's passed is the new page
        reach = mouth if lane % 2 == 0 else WIDTH - mouth
        if reach > shown[lane]:
            a, b = (shown[lane], reach) if lane % 2 == 0 else (WIDTH - reach, WIDTH - shown[lane])
            c.reveal(a, lane * LANE, b - a, LANE); shown[lane] = reach
        c.draw(FACES[CHOMP[k % len(CHOMP)], lane % 2 == 1], round(x), lane * LANE + (LANE - SIZE) // 2)
        yield
