"""Premier Cherdenko escapes to space, as a comic page of two panels, like Johnny-5's: they drop in over the old page,
the Premier rises into the first and says where he's going in the second, looks up, and with SPACE!!!! the whole page
blasts off the top of the screen on a rocket flame, leaving the new page behind it. A fan tribute to Tim Curry's Premier Cherdenko in Red Alert 3 (2008); nothing
official.

The art is Nula's pixel art of the Premier (see "the Premier" below). Everything is drawn once, at import: the page as
a whole screen, and each pose and the speech as small boxes with the page behind them, so a frame only copies what
changes: his head while he talks, a box when something appears, and in the launch one shifted copy of the scene, one
copy of the new page under it and the flame.
"""
import math, os, random, re

from PIL import Image, ImageDraw

import kit
from .canvas import WIDTH, HEIGHT, STRIDE, sprite

SECONDS = 6   # 144 frames: the panels and the Premier in 0.8 s, his line to 3.7 s, SPACE!!!! and a shake, a 1.7 s launch
LOOK_UP = .84  # how far through his talking he looks up (frame 8), then grins (9)
RED, ORANGE, GOLD, INK, PAPER = (204, 26, 26), (255, 120, 20), (255, 206, 40), (14, 12, 20), (248, 244, 232)
DEEP_RED, DOT = (150, 18, 22), (226, 150, 40)   # his panel, and its halftone
SPACE_BLUE, SPACE_DOT = (38, 58, 150), (64, 92, 196)   # the other panel, and its

# --- the Premier ----------------------------------------------------------------------------------------------------
# Nula's pixel art of Premier Cherdenko: a 4x3 sheet of him speaking, ending with him looking up and grinning at the
# sky. Reduced to sprites in kiosk/art/cherdenko-talk.png: twelve frames 237x230 in a row, cut to one shared box, stray
# edge pixels taken off, 64 colours, and each frame shifted to line up on his shoulders, so his body doesn't hop. Drawn
# at 2x. He shouts with the sheet's own last grin: Nula's separate shouting picture was drawn smaller and softer, and
# didn't match. The character is Red Alert 3's, played by Tim Curry: a fan tribute, for our kiosks.
TALK_ART = Image.open(os.path.join(kit.HERE, "art", "cherdenko-talk.png")).convert("RGBA")
FRAME_W = 237
TALK = [TALK_ART.crop((i * FRAME_W, 0, (i + 1) * FRAME_W, TALK_ART.height)) for i in range(TALK_ART.width // FRAME_W)]
K = 2                                        # drawn at twice the art's size
FIG_W, FIG_H = 255 * K, TALK_ART.height * K   # the box he's drawn in, a little wider than him, his shoulders on the
                                              # screen's bottom
FIG_X, FIG_Y = 107, HEIGHT - FIG_H             # centred in the first panel
SPEAKING = [11, 0, 1, 2, 3, 5, 6, 10, 4, 1, 7]   # the frames he talks through, in order: a smirk before he starts,
                                                 # ending on 7, his eyes already drifting up, so 7 -> 8 is never a jump back
LOOKING = [8, 9]                             # then he looks up, and grins at the sky: the face he shouts with

# --- the comic page: two panels, him in the first, his line and SPACE!!!! in the second -------------------------------
# Like Johnny-5's page: ink gutters, a halftone panel and lettering with a hard ink shadow. His panel runs off the
# screen's foot, so he can rise into it from below.
P1, P2 = (12, 12, 712, HEIGHT + 8), (724, 12, 1908, HEIGHT - 12)
HEAD = (FIG_X + FIG_W // 2, FIG_Y + 150)     # where his head is, for the focus lines
BUBBLE = (780, 26, 1880, 246)                # an oval, its tail across the gutter to his mouth, its tip just right of him
TAIL = [(840, 120), (850, 190), (FIG_X + FIG_W + 16, 248)]
LINES = ["I'M ESCAPING TO THE ONE PLACE", "NOT CORRUPTED BY CAPITALISM..."]   # his line
SHOUT, SHOUT_K = "SPACE!!!!", 10
DROPS = [(0, (P1[2] + P2[0]) // 2), ((P1[2] + P2[0]) // 2, WIDTH)]   # each panel with the gutters round it, to drop in
BURST = ((P2[0] + P2[2]) // 2, 380, 500, 118)   # the jagged burst SPACE!!!! goes off in: centre, half width, half height


def page():
    """the whole screen: the comic page with both panels empty"""
    img = Image.new("RGB", kit.SCREEN, INK); d = ImageDraw.Draw(img)
    d.rectangle(P1, fill=DEEP_RED)                        # his panel: red, gold-flecked halftone, focus lines on him
    lines = img.crop(P1); ld = ImageDraw.Draw(lines); cx, cy = HEAD[0] - P1[0], HEAD[1] - P1[1]
    for a in range(0, 360, 9):
        r = math.radians(a)
        ld.line((cx + 60 * math.cos(r), cy + 60 * math.sin(r), cx + 900 * math.cos(r), cy + 900 * math.sin(r)),
                fill=RED, width=3)
    img.paste(lines, P1[:2])
    for j, y in enumerate(range(P1[1] + 4, HEIGHT, 10)):
        for x in range(P1[0] + 4 + (5 if j % 2 else 0), P1[2], 10):
            d.rectangle((x, y, x + 1, y + 1), fill=DOT)
    d.rectangle(P2, fill=SPACE_BLUE)                      # his line's panel: space, light enough for ink to read
    for j, y in enumerate(range(P2[1] + 4, P2[3], 10)):   # on, like Johnny-5's panels, halftone and stars
        for x in range(P2[0] + 4 + (5 if j % 2 else 0), P2[2], 10):
            d.rectangle((x, y, x + 1, y + 1), fill=SPACE_DOT)
    rnd = random.Random(97)
    for _ in range(160):
        x, y, s = rnd.randrange(P2[0] + 6, P2[2] - 6, 2), rnd.randrange(P2[1] + 6, P2[3] - 6, 2), rnd.choice((2, 2, 2, 4))
        v = rnd.randrange(150, 256)
        d.rectangle((x, y, x + s - 1, y + s - 1), fill=(v, v, min(255, v + 20)))
    for box in (P1, P2):                                  # ink borders
        d.rectangle(box, outline=INK, width=6)
    return img


def bubble(img, lines):
    """the speech bubble, with this many of its lines: white oval, ink edge, its tail to his mouth"""
    d = ImageDraw.Draw(img); x0, y0, x1, y1 = BUBBLE
    d.ellipse((x0 + 8, y0 + 8, x1 + 8, y1 + 8), fill=INK)   # a hard shadow, like the lettering's
    d.polygon(TAIL, fill=PAPER, outline=INK, width=5)
    d.ellipse(BUBBLE, fill=PAPER, outline=INK, width=6)
    d.polygon([(TAIL[0][0] + 6, TAIL[0][1] + 6), (TAIL[1][0] + 4, TAIL[1][1] - 6), (TAIL[2][0] + 40, TAIL[2][1] - 18)],
              fill=PAPER)                                   # the tail joins the bubble, no line across
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    for n, words in enumerate(LINES[:lines]):
        kit.text(img, (cx - len(words) * 12, cy - 54 + 60 * n), words, INK, scale=3)


def jagged(cx, cy, rx, ry, inner=.8, points=26):
    """a jagged burst's outline, alternately rx/ry and inner times that out"""
    return [(cx + (1 if i % 2 else inner) * rx * math.cos(i * math.pi * 2 / points),
             cy + (1 if i % 2 else inner) * ry * math.sin(i * math.pi * 2 / points)) for i in range(points)]


def shout(img):
    """SPACE!!!! going off in a red burst: gold comic lettering over a thick ink shadow"""
    d = ImageDraw.Draw(img); cx, cy, rx, ry = BURST
    d.polygon([(x + 8, y + 8) for x, y in jagged(*BURST)], fill=INK)
    d.polygon(jagged(*BURST), fill=RED, outline=INK, width=5)
    x, y = cx - len(SHOUT) * 4 * SHOUT_K, cy - 8 * SHOUT_K
    for dx, dy in ((-4, 0), (4, 0), (0, -4), (0, 4), (8, 8)):
        kit.text(img, (x + dx, y + dy), SHOUT, INK, scale=SHOUT_K)
    kit.text(img, (x, y), SHOUT, GOLD, scale=SHOUT_K)


def pose(art):
    """him at rest, his panel behind him, as the figure's box"""
    box = (FIG_X, FIG_Y, FIG_X + FIG_W, HEIGHT)
    img = PAGE.crop(box)
    big = art.resize((art.width * K, art.height * K), Image.NEAREST)
    img.paste(big, ((FIG_W - big.width) // 2, FIG_H - big.height), big)
    return img


PAGE = page()
BACK = kit.rgb565(PAGE)


def packed(img, x, y):
    """a box drawn once -> (x, y, w, h, its rows in packed bytes)"""
    return (x, y, img.width, img.height, kit.rgb565(img))


def region(make, box):
    """the page under box with make() drawn over the whole screen, cut to box -> packed"""
    img = PAGE.copy(); make(img)
    return packed(img.crop(box), box[0], box[1])


SEEN = {i: pose(TALK[i]) for i in sorted(set(SPEAKING + LOOKING))}   # only the ones he uses
POSES = {i: packed(img, FIG_X, FIG_Y) for i, img in SEEN.items()}
ORDER = SPEAKING + LOOKING
BLENDS = {(a, b): packed(Image.blend(SEEN[a], SEEN[b], .5), FIG_X, FIG_Y) for a, b in zip(ORDER, ORDER[1:])}
# halfway between each pose and the next, shown for one frame as he changes, so his face eases rather than snaps
SHOUTING = POSES[LOOKING[-1]]   # the grin, drawn for good now, so it's in the scene that lifts off
SPEECH = [region(lambda img, n=n: bubble(img, n), (TAIL[2][0] - 8, BUBBLE[1] - 8, BUBBLE[2] + 16, BUBBLE[3] + 16))
          for n in range(1, len(LINES) + 1)]
SHOUT_BOX = (BURST[0] - BURST[2] - 4, BURST[1] - BURST[3] - 4, BURST[0] + BURST[2] + 12, BURST[1] + BURST[3] + 12)
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


RISING = big_sprite(TALK[SPEAKING[0]], K)               # rising into view, he's drawn see-through over his panel


def flame(size, seed):
    """a rocket flame, pointing down: ragged tongues of red, orange, gold, and a white-hot heart, drawn at a quarter
    size and blown up, so it's chunky like the art"""
    w, h = size[0] // 4, size[1] // 4
    img = Image.new("RGBA", (w, h)); d = ImageDraw.Draw(img); rnd = random.Random(seed)
    for k, colour in ((1.0, RED), (.78, ORANGE), (.55, GOLD), (.3, PAPER)):
        left, right = [], []
        for j in range(13):
            t = j / 12; half = w / 2 * k * (1 - t) ** .6 * (1 + rnd.uniform(-.18, .18))   # it narrows, raggedly
            left.append((w / 2 - half, t * h * k)); right.append((w / 2 + half, t * h * k))
        d.polygon(left + [(w / 2 + rnd.uniform(-2, 2), h * k)] + right[::-1], fill=colour + (255,))
    return big_sprite(img, 4)


FLAMES = [flame((360, 260), s) for s in (1, 2, 3)]   # three, taking turns: it flickers
FLAME_X = FIG_X + FIG_W // 2 - 180


def put(c, box, part=None, keep=True, screen=False):
    """copy a packed box (or part of it, (dx, dy, w, h) inside it) to the screen: for good (keep), or for this frame.
    screen: to the screen only, not the clean copy, for something nothing will wipe or capture before it's replaced"""
    x, y, w, h, data = box
    dx, dy, pw, ph = part or (0, 0, w, h)
    dsts = (c.cur, c.mm) if keep and not screen and c.cur is not None else (c.mm,)
    for row in range(max(0, y + dy), min(HEIGHT, y + dy + ph)):
        src = ((row - y) * w + dx) * 2
        a = row * STRIDE + (x + dx) * 2
        for dst in dsts:
            dst[a:a + pw * 2] = data[src:src + pw * 2]
    if not keep and not screen:
        c.dirty.append((x + dx, max(0, y + dy), pw, min(HEIGHT, y + dy + ph) - max(0, y + dy)))


def shake(c, scene, dy):
    """the scene, dy rows down (or up), straight onto the screen: every row, every frame, so there's nothing to wipe,
    which halves what a frame copies (the edge it uncovers keeps the scene's own rows)"""
    mm, s = c.mm, dy * STRIDE
    if dy > 0:
        mm[:s] = scene[:s]; mm[s:len(scene)] = scene[:len(scene) - s]
    elif dy < 0:
        mm[:len(scene) + s] = scene[-s:]; mm[len(scene) + s:len(scene)] = scene[len(scene) + s:]
    else:
        mm[:len(scene)] = scene


def ease_in(t):
    return t * t   # gentler than a cube: it still speeds up, without the last frames leaping


def frames(c, count):
    """count frames (144 by default): the panels drop in, one then the other (0-6%), he rises (6-13%), says his line, a line of the bubble
    at a time, both up in time to read before he looks up (13-62%), shouts SPACE!!!! (62-66%), the screen shakes
    (66-72%), and the whole scene blasts off the top on a flame, the new page coming up from below (72-100%)"""
    n = max(1, count)
    at = lambda f: round(f * n)
    drop, rise, talk, shout_at, shake_end, launch = at(.06), at(.13), at(.62), at(.66), at(.72), n
    scene, shown, easing, lifted = None, SPEAKING[0], False, 0
    for i in range(n):
        if i < drop:   # the panels drop down over the old page, his first, the other starting halfway through his
            for p, (x0, x1) in enumerate(DROPS):
                k = min(1, max(0, (i + 1) / max(1, drop) * 1.6 - p * .6))
                c.reveal(x0, 0, x1 - x0, math.ceil(HEIGHT * k), src=BACK)
        elif i < rise:   # he rises from the bottom edge, decelerating, see-through over the night
            if i == drop:
                c.reveal(0, 0, WIDTH, HEIGHT, src=BACK)
            k = (i - drop + 1) / max(1, rise - drop)
            c.draw(RISING, FIG_X + (FIG_W - RISING["w"]) // 2, FIG_Y + round(FIG_H * (1 - k) ** 2))
            if i == rise - 1:
                put(c, POSES[SPEAKING[0]])
        elif i < talk:   # he talks: each pose held about a quarter second at the usual length, spread so it always
                         # ends on the last one just before he looks up
            k = (i - rise) / max(1, talk - rise)
            for line, part in enumerate(SPEECH):   # the bubble's first line as he starts, the rest by 40% in
                if i == rise + round(line * .4 * (talk - rise) / max(1, len(SPEECH) - 1)):
                    put(c, part)
            if k > LOOK_UP:   # he looks up, then grins at the sky
                want = LOOKING[min(len(LOOKING) - 1, int((k - LOOK_UP) / (1 - LOOK_UP) * len(LOOKING)))]
            else:
                want = SPEAKING[min(len(SPEAKING) - 1, int(k / LOOK_UP * len(SPEAKING)))]
            if want != shown:   # each of Nula's frames is drawn whole, once a hold, to the screen alone: nothing wipes
                                # or captures him before the shout replaces him, so ~460 copies, not ~920
                if (shown, want) in BLENDS and not easing:   # a frame halfway first
                    put(c, BLENDS[shown, want], screen=True); easing = True
                else:
                    put(c, POSES[want], screen=True); shown, easing = want, False
        elif i < shout_at:   # he looks up and shouts: the pose in two halves, then SPACE!!!!
            j = i - talk
            if j == 0:
                put(c, SHOUTING, (0, 0, FIG_W, FIG_H // 2))
            elif j == 1:
                put(c, SHOUTING, (0, FIG_H // 2, FIG_W, FIG_H - FIG_H // 2))
            elif j == 2:
                put(c, SHOUTED)
        elif i < shake_end:   # the screen shakes as the engines light
            if scene is None:
                if shout_at - talk < 3:   # too few frames for the shout's three steps: all of it now, before it goes
                    put(c, SHOUTING); put(c, SHOUTED)
                scene = bytes(c.cur)
            dy = (6, -6, 4, -4, 2, -2, 0)[(i - shout_at) % 7]
            shake(c, scene, dy)
            c.draw(FLAMES[i % len(FLAMES)], FLAME_X + (-6, 0, 6, 0)[i % 4], HEIGHT - 60 + abs(dy))
        else:   # lift-off: the scene goes up, faster and faster, on its flame, and the new page comes up from below
            if scene is None:   # no shake at this length either
                put(c, SHOUTING); put(c, SHOUTED)
                scene = bytes(c.cur)
            k = (i - shake_end + 1) / max(1, launch - shake_end)
            lift = round(ease_in(k) * (HEIGHT + FLAMES[0]["h"]))   # far enough that the flame's tip is off the top too
            if i == shake_end:   # the last shake may have left it shifted: straight again before it goes
                shake(c, scene, 0)
            c.reveal(0, max(0, HEIGHT - lift), WIDTH, lift - lifted)   # just the rows uncovered since last frame
            if lift < HEIGHT:   # the scene, lifted, straight onto the screen: the next frame covers it again
                c.mm[:(HEIGHT - lift) * STRIDE] = scene[lift * STRIDE:]
            lifted = lift
            c.draw(FLAMES[i % len(FLAMES)], FLAME_X + (-6, 0, 6, 0)[i % 4], HEIGHT - lift)   # it flickers and wobbles every frame
        yield


def check():
    """the art is there and the right size, and the story's beats come in order at any length"""
    assert len(TALK) == 12 and all(t.size == (FRAME_W, TALK_ART.height) for t in TALK), "twelve frames of him talking"
    assert FIG_W >= TALK[0].width * K, "he fits his box"
    assert all(big_sprite(img, k) == sprite(img, k) for img, k in ((TALK[0], K), (TALK[3], 3), (TALK[9], 1))), \
        "the runs are the engine's own, exactly"
    assert SHOUT_BOX[2] <= WIDTH and SHOUT_BOX[3] <= HEIGHT and BUBBLE[2] < WIDTH, "SPACE!!!! and the bubble fit"
    from .canvas import Canvas
    size = WIDTH * HEIGHT * 2
    for count in (1, 2, 12, 144, 200):
        c = Canvas(bytearray(size), b"\x55" * size)
        shown, steps = [], frames(c, count)
        while c.wipe() or next(steps, "done") != "done":   # as play() goes: this frame's decorations off, then the next
            shown.append(bytes(c.mm))
        assert len(shown) == count, count
        if count >= 12:   # its own last frame is already the new page, flame and all gone, before play() makes sure
            assert shown[-1] == b"\x55" * size, f"something's left on the last of {count} frames"
    order = []   # the poses he goes through: each of SPEAKING once, in order, then looking up, at any length
    real = globals()["put"]
    def spy(c, box, part=None, keep=True, screen=False):
        if box in POSES.values() and (not order or order[-1] is not box):
            order.append(box)
        return real(c, box, part, keep, screen)
    globals()["put"] = spy
    try:
        for count in (144, 200, 96):
            order.clear(); list(frames(Canvas(bytearray(size), b"\x55" * size), count))
            want = [POSES[f] for f in SPEAKING + LOOKING] if count >= 96 else None
            assert order == want, (count, [next(k for k, v in POSES.items() if v is b) for b in order])
    finally:
        globals()["put"] = real
    print("cherdenko: ok")
