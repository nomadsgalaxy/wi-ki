"""Premier Cherdenko escapes to space, as a Soviet-era propaganda poster in two panels: they drop in over the old page,
the Premier rises into the first and says where he's going in the second, looks up, and with SPACE!!!! the whole page
blasts off the top of the screen on a rocket flame, leaving the new page behind it. A fan tribute to Tim Curry's Premier Cherdenko in Red Alert 3 (2008); nothing
official.

The art is Nula's pixel art of the Premier (see "the Premier" below). Everything is drawn once, at import: the page as
a whole screen, and each pose and the speech as small boxes with the page behind them, so a frame only copies what
changes: his head while he talks, a box when something appears, and in the launch one shifted copy of the scene, one
copy of the new page under it and the flame.
"""
import math, os, random, re

from PIL import Image, ImageDraw, ImageFont

import kit
from . import FPS
from .canvas import WIDTH, HEIGHT, STRIDE, sprite

# his performance, 5 s in all (no theme runs longer than johnny5): a quick monologue, "I'M ESCAPING TO THE ONE PLACE"
# alone for 0.5 s, "NOT CORRUPTED" 0.22 s, "BY CAPITALISM..." 0.23 s, then 1.35 s of withheld laughter with his whole
# line up to read, then he throws his head back for SPACE!!!!
LINES_AT = (0, .5, .72)  # seconds into his talking that each line of the banner comes up
SPEAK = .95             # seconds he talks, through the three lines
SHOUT_HOLD = .5         # seconds SPACE!!!! holds once it's formed, to be read
BEATS = {"drop": .25, "rise": .25, "talk": None, "shout": None, "shake": .2, "launch": .95}   # talk and shout: below
RED, ORANGE, GOLD, INK, PAPER = (204, 26, 26), (255, 120, 20), (255, 206, 40), (14, 12, 20), (248, 244, 232)
CREAM, NAVY, TEAL = (238, 226, 198), (20, 24, 40), (40, 150, 140)   # the poster's paper, its dark fields, its cool accent

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
SPEAKING = [11, 0, 1, 2, 6, 10, 0, 1, 2, 6, 4]   # the frames he talks through, in order: a smirk before he starts,
                                                 # his open-mouthed frames, and his straight face (4) to finish
LAUGH = [(11, .24), (5, .15), (11, .2), (5, .15), (11, .27), (3, .34)]   # each flip is 2+ frames: a blend, then the pose   # (frame, seconds): withheld laughter, the smirk
                                                 # breaking into a grin and back, twice, then nearly bursting
LOOKING = [(7, .1), (8, .1), (9, .1)]          # then his head goes back: eyes up, looking up, and the grin he shouts with
SCRIPT = [(f, SPEAK / len(SPEAKING)) for f in SPEAKING] + LAUGH + LOOKING   # all of it, (frame, seconds)
BEATS["talk"] = sum(t for _, t in SCRIPT)

# --- the poster: two panels on cream paper, him in the first, his line and SPACE!!!! in the second --------------------
# A Soviet-era propaganda poster's look, around Nula's art (which stays as it is): a few flat colours, no shading,
# cream paper round dark fields, a spiky sunburst behind him and red stars, and heavy condensed capitals: his line on a
# cream banner, and SPACE!!!! as the launch itself, cream on a red trail, rising, with launch rays behind. The lettering is Fira Sans Condensed ExtraBold (fonts/, SIL OFL 1.1, cut down
# to the characters a line needs), drawn at half size without smoothing and doubled, so its edges are pixels like the
# art's. His panel runs off the screen's foot, so he can rise into it from below.
P1, P2 = (12, 12, 712, HEIGHT + 8), (724, 12, 1908, HEIGHT - 12)
HEAD = (FIG_X + FIG_W // 2, FIG_Y + 150)     # where his head is: the sunburst's centre
BUBBLE = (790, 30, 1868, 236)                # his line's banner, slanted, its pointer across the gutter to his mouth
TAIL = [(800, 160), (800, 214), (FIG_X + FIG_W + 16, 248)]
# his line, as three deliberate lines, the last two bigger: (words, cap height in pixels)
LINES = [("I'M ESCAPING TO THE ONE PLACE", 32), ("NOT CORRUPTED", 52), ("BY CAPITALISM...", 52)]
SHOUT, SHOUT_CAP = "SPACE", 116                # the shout's word, and how tall its capitals are; then four !s
FONT = os.path.join(kit.HERE, "fonts", "FiraSansCondensed-ExtraBold-subset.ttf")
DROPS = [(0, (P1[2] + P2[0]) // 2), ((P1[2] + P2[0]) // 2, WIDTH)]   # each panel with the paper round it, to drop in
SLIDE = [(-42, 28), (-20, 13), (-7, 5), (0, 0)]   # where the word's face is, frame by frame, as it slides onto its trail


def star(d, cx, cy, r, fill):
    """a five-pointed star, point up"""
    d.polygon([(cx + (r if i % 2 == 0 else r * .4) * math.sin(i * math.pi / 5),
                cy - (r if i % 2 == 0 else r * .4) * math.cos(i * math.pi / 5)) for i in range(10)], fill=fill)


def lettering(words, cap, colour, track=0, gap=None):
    """words in heavy condensed capitals, cap pixels tall: drawn at half size without smoothing and doubled, track
    pixels (at half size) taken out between letters, and gap, if given, the space between !s -> an RGBA image, cut to
    the ink"""
    probe = ImageFont.truetype(FONT, 100)
    font = ImageFont.truetype(FONT, max(4, round(cap / 2 * 100 / (probe.getbbox("H")[3] - probe.getbbox("H")[1]))))
    mask = Image.new("L", (len(words) * font.size + 20, font.size * 2))
    d = ImageDraw.Draw(mask); d.fontmode = "1"
    x = 4
    for i, ch in enumerate(words):
        d.text((x, font.size // 2), ch, fill=255, font=font)
        step = font.getlength(ch) - track
        if gap is not None and ch == "!":   # the !s: narrow, at cap height, close together
            step = (font.getbbox("!")[2] - font.getbbox("!")[0]) + gap
        x += step
    mask = mask.crop(mask.getbbox())
    out = Image.new("RGBA", mask.size, colour + (255,)); out.putalpha(mask)
    return out.resize((out.width * 2, out.height * 2), Image.NEAREST)


def page():
    """the whole screen: the poster with both panels empty"""
    img = Image.new("RGB", kit.SCREEN, CREAM); d = ImageDraw.Draw(img)
    for box in (P1, P2):
        d.rectangle(box, fill=NAVY)
    rays = img.crop(P1); rd = ImageDraw.Draw(rays); cx, cy = HEAD[0] - P1[0], HEAD[1] - P1[1]
    for i in range(24):                                     # his panel: a teal sunburst from behind his head
        if i % 2 == 0:
            a, b = math.radians(i * 15), math.radians(i * 15 + 9)
            rd.polygon([(cx, cy), (cx + 1200 * math.cos(a), cy + 1200 * math.sin(a)),
                        (cx + 1200 * math.cos(b), cy + 1200 * math.sin(b))], fill=TEAL)
    rd.ellipse((cx - 190, cy - 190, cx + 190, cy + 190), fill=NAVY)   # the rays start clear of him
    img.paste(rays, P1[:2])
    for x, y, r in ((60, 70, 22), (650, 60, 16), (90, 330, 14), (640, 300, 20)):
        star(d, P1[0] + x, P1[1] + y, r, RED)
    return img   # the other panel stays a clear navy field, for his line and the word


def bubble(img, lines):
    """his line's banner, with this many of its lines: a slanted cream band, a hard red shadow, navy capitals, and a
    pointer to his mouth"""
    d = ImageDraw.Draw(img); x0, y0, x1, y1 = BUBBLE; lean = 30
    d.polygon(TAIL, fill=CREAM)
    band = [(x0 + lean, y0), (x1, y0), (x1 - lean, y1), (x0, y1)]
    d.polygon([(x + 10, y + 10) for x, y in band], fill=RED)   # a hard red shadow
    d.polygon(band, fill=CREAM)
    y = y0 + (y1 - y0 - TEXT_H) // 2
    for n, part in enumerate(SAID):
        if n < lines:
            img.paste(part, ((x0 + x1) // 2 - part.width // 2, y), part)
        y += part.height + LEADING


def headline(cap, colour):
    """SPACE!!!! as one piece: the word, then four narrow !s at cap height close after it, on one baseline -> RGBA"""
    word, bangs = lettering(SHOUT, cap, colour, track=1), lettering("!!!!", cap, colour, gap=max(2, cap // 40))
    space = cap // 10
    out = Image.new("RGBA", (word.width + space + bangs.width, max(word.height, bangs.height)))
    out.paste(word, (0, out.height - word.height), word); out.paste(bangs, (word.width + space, out.height - bangs.height), bangs)
    return out


def fitted(cap, width, colour):
    """the headline at cap, or smaller until it's no wider than width"""
    out = headline(cap, colour)
    return out if out.width <= width else headline(cap * width // out.width, colour)


def word_layers():
    """SPACE!!!! as the launch, in its two layers, on canvases the same size so they line up: cream letter faces, and
    the red trail running down to the left from them; both rising 6 degrees to the right -> (face, trail)"""
    face = fitted(142, 860, CREAM)
    red = Image.new("RGBA", face.size, RED + (255,)); red.putalpha(face.getchannel("A"))
    top, trail = Image.new("RGBA", (face.width + 20, face.height + 20)), Image.new("RGBA", (face.width + 20, face.height + 20))
    for k in range(18, 0, -1):   # the extrusion, down and to the left
        trail.paste(red, (20 - k, k), red)
    top.paste(face, (20, 0), face)
    return top.rotate(6, resample=Image.NEAREST, expand=True), trail.rotate(6, resample=Image.NEAREST, expand=True)


FACE, TRAIL = word_layers()
WORD_AT = ((P2[0] + P2[2]) // 2 + 20 - FACE.width // 2, 380 - FACE.height // 2)


def rays(img):
    """three teal launch rays, meeting low on the left of the shout's field and running off the panel's right edge"""
    field = img.crop(P2); fd = ImageDraw.Draw(field)
    meet = (60, P2[3] - P2[1] - 20)
    for to, half in (((1230, 90), 22), ((1230, 250), 30), ((1230, 410), 18)):
        fd.polygon([meet, (to[0], to[1] - half), (to[0], to[1] + half)], fill=TEAL)
    img.paste(field.crop((0, BUBBLE[3] + 16 - P2[1], field.width, field.height)), (P2[0], BUBBLE[3] + 16))   # below the banner


def shout(img, trail=True, face=(0, 0)):
    """SPACE!!!! going off: the rays, the red trail if asked, and the cream face at an offset from where it rests (or
    none). Flat, no outline, the counters open."""
    rays(img)
    if trail:
        img.paste(TRAIL, WORD_AT, TRAIL)
    if face is not None:
        img.paste(FACE, (WORD_AT[0] + face[0], WORD_AT[1] + face[1]), FACE)


SAID = [lettering(words, cap, NAVY, track=0 if cap < 40 else 1) for words, cap in LINES]   # his line, a picture a line;
# the small line keeps its spacing, or its apostrophe runs into the letters
LEADING = 10
TEXT_H = sum(p.height for p in SAID) + LEADING * (len(SAID) - 1)


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


ORDER = [f for f, _ in SCRIPT]
SEEN = {i: pose(TALK[i]) for i in sorted(set(ORDER))}   # only the ones he uses
POSES = {i: packed(img, FIG_X, FIG_Y) for i, img in SEEN.items()}
BLENDS = {(a, b): packed(Image.blend(SEEN[a], SEEN[b], .5), FIG_X, FIG_Y) for a, b in zip(ORDER, ORDER[1:])}
# halfway between each pose and the next, shown for one frame as he changes, so his face eases rather than snaps
SHOUTING = POSES[ORDER[-1]]   # the grin, drawn for good now, so it's in the scene that lifts off
SPEECH = [region(lambda img, n=n: bubble(img, n), (TAIL[2][0] - 8, BUBBLE[1] - 8, BUBBLE[2] + 16, TAIL[2][1] + 8))
          for n in range(1, len(LINES) + 1)]
SHOUT_BOX = (P2[0], BUBBLE[3] + 14, P2[2], P2[3])   # everything below the banner


def shout_steps():
    """the shout, step by step, each over the banner's whole line: the rays, then the trail, then the face sliding onto
    it. The page, the banner and the rays are drawn once; each step only adds its layers."""
    base = PAGE.copy(); bubble(base, len(LINES)); shout(base, trail=False, face=None)
    base = base.crop(SHOUT_BOX)
    out = []
    for trail, face in ((False, None), (True, None), *((True, at) for at in SLIDE)):
        img = base.copy(); x0, y0 = SHOUT_BOX[:2]
        if trail:
            img.paste(TRAIL, (WORD_AT[0] - x0, WORD_AT[1] - y0), TRAIL)
        if face is not None:
            img.paste(FACE, (WORD_AT[0] + face[0] - x0, WORD_AT[1] + face[1] - y0), FACE)
        out.append(packed(img, x0, y0))
    return out


SHOUT_STEPS = shout_steps()
BEATS["shout"] = len(SHOUT_STEPS) / FPS + SHOUT_HOLD
SECONDS = sum(BEATS.values())   # 5 s, 120 frames: johnny5's length, which is the longest a theme should run
STILL = BEATS["talk"] + SHOUT_HOLD   # seconds it holds still on purpose, to be read: his line, his laughter and the
                                     # shout (only his face moves); transitions.check() wants the rest moving
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
FLAME_H = FLAMES[0]["h"]
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
    """count frames (120 by default), in BEATS: the panels drop in, one then the other; he rises; he plays SCRIPT, his
    line coming up a line at a time (LINES_AT), then holding in his laughter, then throwing his head back; SPACE!!!!
    goes off (the rays, the trail, the word sliding up onto it) and holds; the screen shakes; and the whole page blasts
    off the top on its flame, the new page coming up from below. Times are shares of SECONDS, so any count keeps the
    shape."""
    n = max(1, count)
    at = lambda t: round(t / SECONDS * n)   # seconds -> frames
    ends, t = [], 0
    for beat in BEATS.values():
        t += beat; ends.append(at(t))
    drop, rise, talk, shout_at, shake_end, launch = ends[:5] + [n]
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
        elif i < talk:   # he plays SCRIPT, and his line comes up a line at a time
            for line, part in enumerate(SPEECH):
                if i == rise + at(LINES_AT[line]):
                    put(c, part)
            when, want = (i - rise) * SECONDS / n, ORDER[-1]
            for f, t in SCRIPT:
                if when < t:
                    want = f; break
                when -= t
            if want != shown:   # each of Nula's frames is drawn whole, once a hold, to the screen alone: nothing wipes
                                # or captures him before the shout replaces him, so ~460 copies, not ~920
                if (shown, want) in BLENDS and not easing:   # a frame halfway first
                    put(c, BLENDS[shown, want], screen=True); easing = True
                else:
                    put(c, POSES[want], screen=True); shown, easing = want, False
        elif i < shout_at:   # SPACE!!!!: the rays, the trail, then the word slides up onto it as one, and holds;
            j = i - talk     # his grin is put down for good alongside, in two halves, for the scene that lifts off
            if j < len(SHOUT_STEPS):
                put(c, SHOUT_STEPS[j])
            if j in (0, 1):
                put(c, SHOUTING, (0, 0, FIG_W, FIG_H // 2) if j == 0 else (0, FIG_H // 2, FIG_W, FIG_H - FIG_H // 2))
        elif i < shake_end:   # the screen shakes as the engines light
            if scene is None:
                if shout_at - talk < len(SHOUT_STEPS):   # too few frames for every step: all of it now, before it goes
                    put(c, SHOUTING); put(c, SHOUT_STEPS[-1])
                scene = bytes(c.cur)
            dy = (6, -6, 4, -4, 2, -2, 0)[(i - shout_at) % 7]
            shake(c, scene, dy)   # no flame yet: it only ever shows below the page, never over him
        else:   # lift-off: the scene goes up, faster and faster, on its flame, and the new page comes up from below
            if scene is None:   # no shake at this length either
                put(c, SHOUTING); put(c, SHOUT_STEPS[-1])
                scene = bytes(c.cur)
            k = (i - shake_end + 1) / max(1, launch - shake_end)
            lift = round(ease_in(k) * (HEIGHT + FLAME_H))   # far enough that the flame's tip is off the top too
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
    assert len({step[4] for step in SHOUT_STEPS}) == len(SHOUT_STEPS), "every step of the shout is a step"
    from .canvas import Canvas
    size = WIDTH * HEIGHT * 2
    # his timing: a quick monologue (the first line alone for half a second, the next two about a fifth each), then the
    # longest beat, holding in his laughter with all of it up, the shout formed for half a second, 5 s in all; STILL
    # claims no more than the holds
    assert LINES_AT[0] == 0 and LINES_AT[1] >= .5 and all(b - a >= .2 for a, b in zip(LINES_AT[1:], LINES_AT[2:] + (SPEAK,)))
    assert abs(sum(t for _, t in LAUGH) - 1.35) < .05 and sum(t for _, t in LAUGH) > SPEAK, "his withheld laughter, longer than his line"
    assert SHOUT_HOLD >= .5, "time to read SPACE!!!!"
    assert STILL <= BEATS["talk"] + SHOUT_HOLD and abs(SECONDS - 5) < .05, "5 s, johnny5's length"
    # the flame never lands on the poster in his panel's columns: every frame, drawn with and without it, may only
    # differ there on rows the new page already shows
    count, cols = round(SECONDS * FPS), slice(0, (P1[2] + 8) * 2)
    def run():
        c, got = Canvas(bytearray(size), b"\x55" * size), []
        steps = frames(c, count)
        while c.wipe() or next(steps, "done") != "done":
            got.append(bytes(c.mm))
        return got
    lit, real = run(), FLAMES[:]
    FLAMES[:] = [{"w": 1, "h": 1, "rows": [[]]}] * len(real)
    try:
        dark = run()
    finally:
        FLAMES[:] = real
    new_row = b"\x55" * STRIDE
    for k, (a, b) in enumerate(zip(lit, dark)):
        for r in range(HEIGHT):
            row = slice(r * STRIDE, (r + 1) * STRIDE)
            if a[row][cols] != b[row][cols] and b[row] != new_row:
                raise AssertionError(f"the flame is over his panel on frame {k}, row {r}")
    for count in (1, 2, 12, 144, round(SECONDS * FPS)):
        c = Canvas(bytearray(size), b"\x55" * size)
        shown, steps = [], frames(c, count)
        while c.wipe() or next(steps, "done") != "done":   # as play() goes: this frame's decorations off, then the next
            shown.append(bytes(c.mm))
        assert len(shown) == count, count
        if count >= 12:   # its own last frame is already the new page, flame and all gone, before play() makes sure
            assert shown[-1] == b"\x55" * size, f"something's left on the last of {count} frames"
    order = []   # the poses he goes through: SCRIPT in order, each once, at full length or more
    real = globals()["put"]
    def spy(c, box, part=None, keep=True, screen=False):
        if box in POSES.values() and (not order or order[-1] is not box):
            order.append(box)
        return real(c, box, part, keep, screen)
    globals()["put"] = spy
    try:
        for count in (round(SECONDS * FPS), 400):
            order.clear(); list(frames(Canvas(bytearray(size), b"\x55" * size), count))
            want = [POSES[f] for f in ORDER]
            assert order == want, (count, [next(k for k, v in POSES.items() if v is b) for b in order])
    finally:
        globals()["put"] = real
    print("cherdenko: ok")
