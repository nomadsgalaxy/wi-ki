"""Premier Cherdenko escapes to space: the old page gives way to a starry night, the Premier rises into view and
addresses his comrades, looks up, and with SPAAAACE! the whole scene blasts off the top of the screen on a rocket
flame, leaving the new page behind it. A fan tribute to Tim Curry's Premier Cherdenko in Red Alert 3 (2008); nothing
official.

The art is Nula's pixel art of the Premier (see "the Premier" below). Everything is drawn once, at import: the night as
a whole screen, and each pose and the speech as small boxes with the night behind them, so a frame only copies what
changes: his head while he talks, a box when something appears, and in the launch one shifted copy of the scene, one
copy of the new page under it and the flame.
"""
import math, os, random, re

from PIL import Image, ImageDraw

import kit
from .canvas import WIDTH, HEIGHT, STRIDE, sprite

SECONDS = 5   # 120 frames: the night and the Premier in 0.8 s, his speech to 2.6 s, SPAAAACE! and a shake, the launch
RED, GOLD, INK, PAPER = (204, 26, 26), (255, 206, 40), (14, 12, 20), (248, 244, 232)

# --- the Premier ----------------------------------------------------------------------------------------------------
# Nula's pixel art of Premier Cherdenko: a 4x3 sheet of him speaking, and him looking up, mouth open,
# shouting SPACE. Reduced to sprites in kiosk/art/: twelve frames 237x230 cut to one shared box so he doesn't jump between
# them (cherdenko-talk.png, in a row), and the shout, 255x230 (cherdenko-space.png); stray edge pixels taken off, and 64
# colours shared by both. Drawn at 2x. The character is Red Alert 3's, played by Tim Curry: a fan tribute, for our kiosks.
TALK_ART = Image.open(os.path.join(kit.HERE, "art", "cherdenko-talk.png")).convert("RGBA")
SHOUT_ART = Image.open(os.path.join(kit.HERE, "art", "cherdenko-space.png")).convert("RGBA")
FRAME_W = 237
TALK = [TALK_ART.crop((i * FRAME_W, 0, (i + 1) * FRAME_W, TALK_ART.height)) for i in range(TALK_ART.width // FRAME_W)]
K = 2                                        # drawn at twice the art's size
FIG_W, FIG_H = SHOUT_ART.width * K, TALK_ART.height * K   # the box both poses fit, his shoulders on the screen's bottom
FIG_X, FIG_Y = 250, HEIGHT - FIG_H
SPEAKING = [0, 1, 2, 3, 5, 6, 10, 4, 1, 7]   # the frames he talks through, in order; 8 and 9 are him looking up

# --- the night, the bubble and the shout ----------------------------------------------------------------------------
BUBBLE = (840, 34, 1886, 238)                # his speech bubble, top right, its tail to his mouth
TAIL = [(880, 226), (985, 226), (FIG_X + FIG_W + 20, 262)]   # a wedge off its bottom, its tip just right of him,
                                                               # so his poses never cover it
LINES = [((878, 60), "COMRADES! I MUST LEAVE YOU NOW."), ((878, 112), "I GO WHERE THEY CAN NEVER"),
         ((878, 164), "FOLLOW...")]
SHOUT, SHOUT_K = "SPAAAACE!", 10
SHOUT_XY = (BUBBLE[0] + (BUBBLE[2] - BUBBLE[0] - len(SHOUT) * 8 * SHOUT_K) // 2, 282)


def night():
    """the whole screen: deep space fading to a red glow at the bottom, with stars"""
    img = Image.new("RGB", kit.SCREEN); d = ImageDraw.Draw(img)
    for y in range(0, HEIGHT, 4):   # in 4-pixel bands, like the rest of the pixel art
        k = y / HEIGHT
        d.rectangle((0, y, WIDTH, y + 3), fill=(round(8 + 40 * k ** 2), round(10 + 4 * k), round(26 - 12 * k)))
    rnd = random.Random(97)
    for _ in range(260):
        x, y, s = rnd.randrange(0, WIDTH, 2), rnd.randrange(0, HEIGHT - 60, 2), rnd.choice((2, 2, 2, 4))
        v = rnd.randrange(150, 256)
        d.rectangle((x, y, x + s - 1, y + s - 1), fill=(v, v, min(255, v + 20)))
    return img


def bubble(img, lines):
    """the speech bubble, with this many of its lines"""
    d = ImageDraw.Draw(img)
    d.polygon(TAIL, fill=PAPER, outline=INK)
    d.rectangle(BUBBLE, fill=PAPER, outline=INK, width=6)
    d.line(TAIL[:2], fill=PAPER, width=5)   # the tail joins the bubble without a line across it
    for xy, words in LINES[:lines]:
        kit.text(img, xy, words, INK, scale=3)


def shout(img):
    """SPAAAACE!, gold on a red shadow"""
    x, y = SHOUT_XY
    kit.text(img, (x + 8, y + 8), SHOUT, RED, scale=SHOUT_K)
    kit.text(img, (x, y), SHOUT, GOLD, scale=SHOUT_K)


def pose(art):
    """him at rest, the night behind him, as the figure's box"""
    box = (FIG_X, FIG_Y, FIG_X + FIG_W, HEIGHT)
    img = NIGHT.crop(box)
    big = art.resize((art.width * K, art.height * K), Image.NEAREST)
    img.paste(big, ((FIG_W - big.width) // 2, FIG_H - big.height), big)
    return img


NIGHT = night()
BACK = kit.rgb565(NIGHT)


def packed(img, x, y):
    """a box drawn once -> (x, y, w, h, its rows in packed bytes)"""
    return (x, y, img.width, img.height, kit.rgb565(img))


def region(make, box):
    """the night under box with make() drawn over the whole screen, cut to box -> packed"""
    img = NIGHT.copy(); make(img)
    return packed(img.crop(box), box[0], box[1])


POSES = {i: packed(pose(TALK[i]), FIG_X, FIG_Y) for i in sorted(set(SPEAKING) | {8})}   # only the ones he uses
SHOUTING = packed(pose(SHOUT_ART), FIG_X, FIG_Y)
SPEECH = [region(lambda img, n=n: bubble(img, n), (TAIL[2][0] - 8, BUBBLE[1] - 8, BUBBLE[2] + 8, TAIL[2][1] + 8))
          for n in (1, 2, 3)]
SHOUT_BOX = (SHOUT_XY[0] - 4, SHOUT_XY[1] - 4, SHOUT_XY[0] + len(SHOUT) * 8 * SHOUT_K + 12, SHOUT_XY[1] + 16 * SHOUT_K + 12)
SHOUTED = region(shout, SHOUT_BOX)
SOLID = bytes(1 if v >= 128 else 0 for v in range(256))   # an alpha byte -> 1 where canvas.sprite counts it solid


def big_sprite(img, k):
    """canvas.sprite(img, k), with no Python loop over pixels: Pillow scales and packs, a regex finds each row's solid
    runs in the alpha, and each run's colours are one slice of the packed image. The same runs, exactly; it matters
    because a per-pixel loop costs seconds at import on a Pi Zero"""
    img = img.convert("RGBA"); img = img.resize((img.width * k, img.height * k), Image.NEAREST)
    w, packed, alpha = img.width, kit.rgb565(img.convert("RGB")), img.getchannel("A").tobytes().translate(SOLID)
    rows = [[(m.start(), packed[(y * w + m.start()) * 2:(y * w + m.end()) * 2])
             for m in re.finditer(b"\x01+", alpha[y * w:(y + 1) * w])] for y in range(img.height)]
    return {"w": w, "h": img.height, "rows": rows}


RISING = big_sprite(TALK[0], K)               # rising into view, he's drawn see-through over the night


def flame(size, seed):
    """a rocket flame, pointing down: white heart, gold, then red at the ragged tip"""
    w, h = size
    img = Image.new("RGBA", (w, h)); d = ImageDraw.Draw(img); rnd = random.Random(seed)
    for (k, colour) in ((1.0, RED + (255,)), (0.7, GOLD + (255,)), (0.38, PAPER + (255,))):
        pts = []
        for i in range(9):
            t = i / 8
            pts.append((w / 2 + (t - .5) * w * k, 0))
        tip = h * k * (0.86 + rnd.random() * .14)
        pts += [(w / 2 + w * k * .18, tip * .55), (w / 2 + w * k * .06, tip), (w / 2 - w * k * .08, tip * .8),
                (w / 2 - w * k * .2, tip * .5)]
        d.polygon(pts, fill=colour)
    return big_sprite(img.resize((w // 4, h // 4), Image.NEAREST), 4)   # drawn at a quarter and blown up: chunky


FLAMES = [flame((360, 220), s) for s in (1, 2)]   # two, taking turns: it flickers
FLAME_X = FIG_X + FIG_W // 2 - 180


def put(c, box, part=None, keep=True):
    """copy a packed box (or part of it, (dx, dy, w, h) inside it) to the screen: for good (keep), or for this frame"""
    x, y, w, h, data = box
    dx, dy, pw, ph = part or (0, 0, w, h)
    dsts = (c.cur, c.mm) if keep and c.cur is not None else (c.mm,)
    for row in range(max(0, y + dy), min(HEIGHT, y + dy + ph)):
        src = ((row - y) * w + dx) * 2
        a = row * STRIDE + (x + dx) * 2
        for dst in dsts:
            dst[a:a + pw * 2] = data[src:src + pw * 2]
    if not keep:
        c.dirty.append((x + dx, max(0, y + dy), pw, min(HEIGHT, y + dy + ph) - max(0, y + dy)))


def ease_in(t):
    return t * t * t


def frames(c, count):
    """count frames (120 by default): the night drops in (0-8%), he rises (8-17%), talks while his speech fills in
    (17-55%), looks up and shouts SPAAAACE! (55-62%), the screen shakes (62-70%), and the whole scene blasts off the
    top on a flame, the new page coming up from below (70-100%)"""
    n = max(1, count)
    at = lambda f: round(f * n)
    drop, rise, talk, shout_at, shake, launch = at(.08), at(.17), at(.55), at(.62), at(.70), n
    scene, shown = None, POSES[0]
    for i in range(n):
        if i < drop:   # the night drops down over the old page, a band a frame
            c.reveal(0, 0, WIDTH, math.ceil(HEIGHT * (i + 1) / max(1, drop)), src=BACK)
        elif i < rise:   # he rises from the bottom edge, decelerating, see-through over the night
            if i == drop:
                c.reveal(0, 0, WIDTH, HEIGHT, src=BACK)
            k = (i - drop + 1) / max(1, rise - drop)
            c.draw(RISING, FIG_X + (FIG_W - RISING["w"]) // 2, FIG_Y + round(FIG_H * (1 - k) ** 2))
            if i == rise - 1:
                put(c, POSES[0])
        elif i < talk:   # he talks, a new frame every third: drawn for good when it changes, nothing in between
            k = (i - rise) / max(1, talk - rise)
            if i == rise:
                put(c, SPEECH[0])
            if i == rise + (talk - rise) // 3:
                put(c, SPEECH[1])
            if i == rise + 2 * (talk - rise) // 3:
                put(c, SPEECH[2])
            frame = POSES[8] if k > .9 else POSES[SPEAKING[((i - rise) // 3) % len(SPEAKING)]]   # 8: he looks up
            if frame is not shown:   # each of Nula's frames is drawn whole, so all of him changes: ~920 copies, 1 in 3
                put(c, frame); shown = frame
        elif i < shout_at:   # he looks up and shouts: the pose in two halves, then SPAAAACE!
            j = i - talk
            if j == 0:
                put(c, SHOUTING, (0, 0, FIG_W, FIG_H // 2))
            elif j == 1:
                put(c, SHOUTING, (0, FIG_H // 2, FIG_W, FIG_H - FIG_H // 2))
            else:
                put(c, SHOUTED)
                if i == shout_at - 1 and j < 2:   # too few frames for the halves: all of it at once
                    put(c, SHOUTING)
        elif i < shake:   # the screen shakes as the engines light
            if scene is None:
                put(c, SHOUTING); put(c, SHOUTED)   # whatever was skipped, it's all there before it goes
                scene = bytes(c.cur)
            dy = (6, -6, 4, -4, 2, -2, 0)[(i - shout_at) % 7]
            if dy:
                c.rows(dy, scene)
            c.draw(FLAMES[i % 2], FLAME_X, HEIGHT - 60 + abs(dy))
        else:   # lift-off: the scene goes up, faster and faster, on its flame, and the new page comes up from below
            if scene is None:
                put(c, SHOUTING); put(c, SHOUTED)
                scene = bytes(c.cur)
            k = (i - shake + 1) / max(1, launch - shake)
            lift = round(ease_in(k) * (HEIGHT + 240))
            c.reveal(0, max(0, HEIGHT - lift), WIDTH, lift)
            if lift < HEIGHT:
                c.rows(-lift, scene)
            c.draw(FLAMES[i % 2], FLAME_X, HEIGHT - lift)
        yield


def check():
    """the art is there and the right size, and the story's beats come in order at any length"""
    assert len(TALK) == 12 and all(t.size == (FRAME_W, TALK_ART.height) for t in TALK), "twelve frames of him talking"
    assert SHOUT_ART.height == TALK_ART.height and FIG_W >= TALK[0].width * K, "the shout fits the same box"
    assert all(big_sprite(img, k) == sprite(img, k) for img, k in ((TALK[0], K), (TALK[3], 3), (SHOUT_ART, 1))), \
        "the runs are the engine's own, exactly"
    assert SHOUT_BOX[2] <= WIDTH and SHOUT_BOX[3] <= HEIGHT and BUBBLE[2] < WIDTH, "SPAAAACE! and the bubble fit"
    from .canvas import Canvas
    size = WIDTH * HEIGHT * 2
    for count in (1, 2, 12, 120):
        c = Canvas(bytearray(size), b"\x55" * size)
        shown = [bytes(c.mm) for _ in frames(c, count)]
        assert len(shown) == count, count
    print("cherdenko: ok")
