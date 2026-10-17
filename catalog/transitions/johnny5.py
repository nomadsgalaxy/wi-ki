"""Johnny-5, as a comic page, so he's big, like a comic book. Three panels drop in over the old page in reading order:
two small ones stacked on the left (the lightning striking his head, ZZZAP!, his eyes flickering; then the close-up of
his head, NEED INPUT!) and the hero panel across the rest, all of him under NUMBER 5 IS ALIVE! It holds long enough to
read, then the new page wipes down each panel in the same order. The robot and the strike are pixel art (see "Johnny-5"
below for where they come from and their licence); the panels are in the brand's amber, Warp Cyan and Nebula Magenta.
Johnny-5 is Short Circuit's (1986): a fan tribute, nothing official. The page is drawn once, at import, and only copied
after that.
"""
import math, os

from PIL import Image, ImageChops, ImageDraw, ImageFilter

import kit
from .canvas import WIDTH, HEIGHT

SECONDS = 5   # 120 frames: the story in 2 s, a 2 s hold on the finished page, a 1 s wipe
W2, H2 = 960, 258
INK, PAPER, GLINT = (12, 12, 18), (250, 244, 228), (255, 255, 255)
SKY1, SKY2, SKY3 = kit.A, kit.O, kit.M   # panel backgrounds: brand amber, Warp Cyan, Nebula Magenta
# a comic page: two panels stacked on the left (the close-up taller, so all his head fits), then the hero panel
# across the rest (half size)
P = [(6, 6, 300, 104), (6, 110, 300, 252), (306, 6, 954, 252)]


def halftone(img, box, colour, step=6, r=1):
    """comic dots over box"""
    d = ImageDraw.Draw(img)
    x0, y0, x1, y1 = box
    for j, y in enumerate(range(y0, y1, step)):
        for x in range(x0 + (step // 2 if j % 2 else 0), x1, step):
            d.ellipse((x - r, y - r, x + r, y + r), fill=colour)


def shade(c, k):
    return tuple(round(v * k) for v in c)


# --- Johnny-5 ----------------------------------------------------------------------------------------------------
# Pixel art of the film's robot by Muse, made after "204 MNACTEC
# (Terrassa), exposició temporal Robots, Johnny 5, de Short Circuit (1986).jpg" by Enric (Wikimedia Commons, CC BY-SA
# 4.0: https://commons.wikimedia.org/wiki/File:204_MNACTEC_(Terrassa),_exposici%C3%B3_temporal_Robots,_Johnny_5,_de_Short_Circuit_(1986).jpg).
# Reduced to sprites in kiosk/art/: all of him, 92x122, arms down and (his second pose) arms up, and his head, 84x66,
# with the background cut away from the edges in, a palette of 20 colours taken from the robot, and an ink line round
# the outside. Panel 1's strike is by Nula, after Muse's robot: kiosk/art/johnny5-strike.png, 78x89, cut
# close on his head with the bolt landing on it, its night kept as the panel's sky and its colours cut to 19 from the
# robot and its lightning, plus the sky. All of them are shared under CC BY-SA 4.0, like the photo. Johnny-5 himself is
# the film's design (Short Circuit, 1986): a fan tribute, for our kiosks.
BODY, HEAD = (Image.open(os.path.join(kit.HERE, "art", f)).convert("RGBA") for f in ("johnny5.png", "johnny5-head.png"))


def based(sprite):
    """the sprite with an ink line under its bottom row, where the art stops at his treads, so they read as a base"""
    out = Image.new("RGBA", (sprite.width, sprite.height + 1)); out.paste(sprite, (0, 0))
    for x in range(sprite.width):
        if sprite.getpixel((x, sprite.height - 1))[3]:
            out.putpixel((x, sprite.height), INK + (255,))
    return out


BODY = based(BODY)
ARMS = based(Image.open(os.path.join(kit.HERE, "art", "johnny5-arms-up.png")).convert("RGBA"))   # his second pose
# (arms up, claws open), reduced the same way with the first sprite's own palette


def figure(img, sprite, xy, scale, mirror=False, clip=None):
    """paste a sprite at xy, scale times its size in whole pixels (mirrored if asked), cut to clip, a box, if given"""
    s = sprite.transpose(Image.FLIP_LEFT_RIGHT) if mirror else sprite
    s = s.resize((s.width * scale, s.height * scale), Image.NEAREST)
    if clip:
        s = s.crop((max(0, clip[0] - xy[0]), max(0, clip[1] - xy[1]),
                    min(s.width, clip[2] - xy[0]), min(s.height, clip[3] - xy[1])))
        xy = (max(xy[0], clip[0]), max(xy[1], clip[1]))
    img.paste(s, xy, s)


def bubble(img, box, words, tail, scale=2):
    """a speech bubble: white oval, ink edge, its tail pointing at tail, words centred"""
    d = ImageDraw.Draw(img); x0, y0, x1, y1 = box; cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    d.polygon([(cx - 10, cy + (y1 - y0) / 4), (cx + 10, cy + (y1 - y0) / 4), tail], fill=PAPER, outline=INK, width=2)
    d.ellipse(box, fill=PAPER, outline=INK, width=3)
    d.polygon([(cx - 8, cy + (y1 - y0) / 4), (cx + 8, cy + (y1 - y0) / 4),
               (tail[0] * .6 + cx * .4, tail[1] * .6 + cy * .4)], fill=PAPER)
    w = len(words) * 8 * scale
    kit.text(img, (round(cx - w / 2), round(cy - 8 * scale)), words, INK, scale=scale)


def burst_points(cx, cy, r, ry=None, inner=.62):
    """a jagged burst's outline: 18 points, alternately r and inner times r out, ry tall (0.6 r unless given)"""
    ry = ry or r * .6
    return [(cx + (1 if i % 2 else inner) * r * math.cos(i * math.pi / 9),
             cy + (1 if i % 2 else inner) * ry * math.sin(i * math.pi / 9)) for i in range(18)]


def burst(img, cx, cy, r, words, fill, scale=2, ry=None, inner=.62):
    """a jagged sound-effect burst"""
    d = ImageDraw.Draw(img)
    pts = burst_points(cx, cy, r, ry, inner)
    d.polygon(pts, fill=fill, outline=INK, width=3)
    w = len(words) * 8 * scale
    kit.text(img, (round(cx - w / 2 + 2), round(cy - 8 * scale + 2)), words, INK, scale=scale)
    kit.text(img, (round(cx - w / 2), round(cy - 8 * scale)), words, PAPER, scale=scale)


def caption(img, xy, *lines):
    """a caption box, a line or two of words"""
    d = ImageDraw.Draw(img); w = max(map(len, lines)) * 8 + 12
    d.rectangle((xy[0], xy[1], xy[0] + w, xy[1] + 6 + 16 * len(lines)), fill=kit.A, outline=INK, width=2)
    for i, words in enumerate(lines):
        kit.text(img, (xy[0] + 6, xy[1] + 3 + 16 * i), words, INK, scale=1)


def headline(img, xy, words, scale, fill):
    """big comic lettering: the words in fill, over a thick ink shadow"""
    for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2), (3, 3)):
        kit.text(img, (xy[0] + dx, xy[1] + dy), words, INK, scale=scale)
    kit.text(img, xy, words, fill, scale=scale)


def focus(img, box, centre, colour):
    """focus lines out from centre, inside box only"""
    lines = img.crop(box); ld = ImageDraw.Draw(lines); cx, cy = centre[0] - box[0], centre[1] - box[1]
    for i in range(0, 360, 10):
        a = math.radians(i)
        ld.line((cx + 30 * math.cos(a), cy + 30 * math.sin(a), cx + 700 * math.cos(a), cy + 700 * math.sin(a)),
                fill=colour)
    img.paste(lines, box[:2])


HERO_XY, HERO_K = (622, 0), 5   # his top left and scale, full size: big in the hero panel, facing right toward his
                                # line; his treads run off the panel's foot so he fills more of it
NIGHT = (12, 15, 30)                                 # panel 1's sky: the strike art's own night, so it has no edge
STRIKE_ART = Image.open(os.path.join(kit.HERE, "art", "johnny5-strike.png")).convert("RGB")   # the strike art, below
STRIKE_AT = (196, P[0][1] + 3)                      # right of middle, the art at its own size (half size)
LENSES, LENS_R = [(21, 56), (53, 57)], 6           # his lenses in the strike art, and how far in they're glass


def thunder(img, colours):
    """ZZZAP! as thunder-strike lettering, at half size: a jagged bolt-shaped plate, the letters leaning forward in
    electric white with a dark edge and a hard ink shadow. colours is ZAP_LIT or ZAP_DIM, to flash with the strike"""
    d = ImageDraw.Draw(img)
    d.polygon(PLATE, fill=colours["plate"], outline=INK, width=3)
    h = ZAP_SIZE[1]
    flat = Image.new("L", ZAP_SIZE); kit.text(flat, (round(h * SLANT), 0), "ZZZAP!", 255, scale=ZAP_SCALE)
    lean = flat.transform(flat.size, Image.AFFINE, (1, SLANT, -round(h * SLANT), 0, 1, 0), resample=Image.NEAREST)
    edge = lean.filter(ImageFilter.MaxFilter(3))
    x, y = ZAP_XY
    img.paste(INK, (x + 4, y + 4), edge)                  # the hard offset shadow
    img.paste(colours["edge"], (x, y), edge)              # the dark edge
    img.paste(colours["letters"], (x, y), lean)


def lenses_off(art):
    """the strike with his lenses dark: the glass inside each steel rim, for his eyes to flicker"""
    out = art.copy(); px = out.load()
    for cx, cy in LENSES:
        for y in range(cy - LENS_R, cy + LENS_R + 1):
            for x in range(cx - LENS_R, cx + LENS_R + 1):
                if (x - cx) ** 2 + (y - cy) ** 2 <= LENS_R ** 2:
                    px[x, y] = (8, 20, 45)
    return out


STRIKE_DARK = lenses_off(STRIKE_ART)
# ZZZAP! as thunder-strike lettering: slanted letters on a jagged bolt-shaped plate, half size
PLATE = [(10, 26), (64, 18), (58, 28), (120, 16), (114, 26), (190, 14), (182, 46), (192, 48), (170, 94), (164, 80),
         (98, 92), (102, 82), (38, 96), (44, 84), (10, 88)]
ZAP_XY, ZAP_SCALE, SLANT = (22, 36), 3, 0.32          # where the lettering sits, its size, and how far it leans
ZAP_SIZE = (len("ZZZAP!") * 8 * ZAP_SCALE + round(16 * ZAP_SCALE * SLANT) + 2, 16 * ZAP_SCALE)   # the leaning lettering
ZAP_LIT = {"plate": (255, 214, 90), "letters": (255, 252, 222), "edge": (196, 116, 18)}   # on the strike
ZAP_DIM = {"plate": (176, 128, 44), "letters": (226, 188, 110), "edge": (112, 66, 12)}    # between
HEAD_AT, HEAD_UP = (8, 116), (8, 112)                # his head in the close-up, and lifted two pixels of the art
RING = (736, 128, 214)                               # the burst behind his line: centre and width, half size
RING_SHAPE = {"ry": 116, "inner": .8}                # taller and less spiky than the sound effects, so his line fits
                                                     # inside its inner edge, not just its points
LINES = [((604, 76), "NUMBER 5 IS", 3, PAPER), ((616, 130), "ALIVE!", 5, kit.M)]   # ALIVE! biggest: his capitals
SNAP = 6                                             # ALIVE! lands this far above where it rests, then snaps down


def eyes_off(head, rows=None):
    """his head with the lenses dark: every bright blue pixel dimmed (in the top rows only, if rows is given: the
    body's blue torso stays), for the eyes to come on from"""
    out = head.copy(); px = out.load()
    for y in range(rows or out.height):
        for x in range(out.width):
            r, g, b, a = px[x, y]
            if a and b > 140 and b > r + 50:
                px[x, y] = (r // 5, g // 5, b // 4, a)
    return out


HEAD = HEAD.transpose(Image.FLIP_LEFT_RIGHT)   # turned to look right, at NEED INPUT! and on to the hero panel
HEAD_DARK = eyes_off(HEAD)


def one_eye(head, dark):
    """his head with only one eye lit, the one nearer us on the left: the dark head with the left half of the lens
    pixels taken back from the lit one"""
    box = ImageChops.difference(head, dark).getbbox() or (0, 0, head.width, head.height)
    out = dark.copy(); mid = (box[0] + box[2]) // 2
    out.paste(head.crop((box[0], box[1], mid, box[3])), (box[0], box[1]))
    return out


HEAD_ONE = one_eye(HEAD, HEAD_DARK)


def sparks(img, centres, seed):
    """a crackle of short jagged sparks off his claws, full size"""
    import random
    rnd = random.Random(seed); d = ImageDraw.Draw(img)
    for cx, cy in centres:
        for a in (-150, -90, -30, 20):
            ang = math.radians(a + rnd.uniform(-15, 15)); pts = [(cx, cy)]
            for step in range(1, 4):
                r = step * 10
                pts.append((cx + r * math.cos(ang) + rnd.uniform(-5, 5), cy + r * math.sin(ang) + rnd.uniform(-5, 5)))
            d.line(pts, fill=kit.O, width=4); d.line(pts, fill=PAPER, width=2)


def page(strike=0, eyes=0, lifted=False, smoke=False, ring=False, text=False, alive=0, pose=None, crackle=False):
    """the whole page at full size, RGB, with only the parts asked for. Panel 1: the night, and with strike 1 or 2
    the strike on his head and ZZZAP!, his eyes and the lettering lit (1) or dark and dim (2). Panel 2: his eyes,
    none, one or both lit (eyes 0, 1 or 2), his head lifted, the smoke off it. Hero panel: the burst and his line
    (ALIVE! raised by alive), him in a pose (squash, jolt or up), and sparks off his claws (crackle)"""
    img = Image.new("RGB", (W2, H2), INK); d = ImageDraw.Draw(img)
    for box, sky, k in zip(P[1:], (SKY1, SKY3), (0.82, 0.9)):   # the hero panel's dots and lines are quieter,
        d.rectangle(box, fill=sky)                              # so his dark silhouette stands out
        halftone(img, box, shade(sky, k))
    d.rectangle(P[0], fill=NIGHT)                               # panel 1: night
    if strike:                                                  # the strike on his head, eyes lit or (2) dark
        img.paste(STRIKE_ART if strike == 1 else STRIKE_DARK, STRIKE_AT)
        thunder(img, ZAP_LIT if strike == 1 else ZAP_DIM)   # it flashes with his eyes: lit, or dim between
    focus(img, P[1], (96, 190), shade(SKY1, .7))
    figure(img, (HEAD_DARK, HEAD_ONE, HEAD)[eyes], HEAD_UP if lifted else HEAD_AT, 2, clip=P[1])
    if smoke:   # a wisp of smoke off his head
        for (cx, cy, r) in SMOKE:
            ImageDraw.Draw(img).ellipse((cx - r, cy - r, cx + r, cy + r), fill=(176, 178, 190), outline=INK, width=1)
    bubble(img, (170, 118, 298, 204), "", (156, 216), scale=2)   # two lines: NEED / INPUT!
    kit.text(img, (202, 127), "NEED", INK, scale=2); kit.text(img, (186, 161), "INPUT!", INK, scale=2)
    focus(img, P[2], (420, 120), shade(SKY3, .9))
    if ring:
        burst(img, *RING, "", kit.A, **RING_SHAPE)
    if text:
        (xy1, w1, s1, f1), ((x2, y2), w2, s2, f2) = LINES
        headline(img, xy1, w1, s1, f1); headline(img, (x2, y2 - alive), w2, s2, f2)
    full = img.resize((W2 * 2, H2 * 2 - 1), Image.NEAREST)
    def place(pose, top):
        sprite, xy = POSES[pose]
        clip = (2 * P[2][0] + 6, top, 2 * P[2][2] - 5, 2 * P[2][3] - 5)
        part = sprite.crop((max(0, clip[0] - xy[0]), max(0, clip[1] - xy[1]),
                            min(sprite.width, clip[2] - xy[0]), min(sprite.height, clip[3] - xy[1])))
        full.paste(part, (max(xy[0], clip[0]), max(xy[1], clip[1])), part)
    if pose and pose not in ARMS_UP:
        place(pose, 2 * P[2][1] + 6)
    d = ImageDraw.Draw(full)
    for x0, y0, x1, y1 in P:   # ink borders
        d.rectangle((x0 * 2, y0 * 2, x1 * 2 + 1, y1 * 2 + 1), outline=INK, width=6)
    if pose in ARMS_UP:   # arms up, his claws break out over the panel's top border, like a comic
        place(pose, 0)
    if crackle:
        sparks(full, CLAWS, seed=5)
    return full


SMOKE = [(118, 126, 4), (128, 119, 5), (141, 114, 6)]   # the wisp off his head, half size
ARMS_UP = {"jolt", "up"}


def poses():
    """him in the hero panel, facing right, full size: squashed and dark-eyed, arms down, as the power hits; then his
    arms fly up and his eyes come on, jolted up two pixels of the art; then at rest, arms up"""
    him, up = BODY.transpose(Image.FLIP_LEFT_RIGHT), ARMS.transpose(Image.FLIP_LEFT_RIGHT)
    w, h = him.width * HERO_K, him.height * HERO_K
    dark = eyes_off(him, rows=32)   # his eyes are in the top rows; the power hits him dark-eyed, and they come on
    squash = dark.resize((round(w * 1.08), round(h * 0.9)), Image.NEAREST)
    raised = up.resize((w, h), Image.NEAREST)
    x, y = HERO_XY
    return {"up": (raised, (x, y)), "jolt": (raised, (x, y - 2 * HERO_K)),
            "squash": (squash, (x - (squash.width - w) // 2, y + h - squash.height))}


POSES = poses()
# his claws in the arms-up art, in its own pixels before it's mirrored, and so in the hero panel, full size
CLAWS = [(HERO_XY[0] + HERO_K * (ARMS.width - 1 - x), HERO_XY[1] + HERO_K * y) for x, y in ((14, 19), (80, 6))]


def strip():
    """the page as it ends: everything in it"""
    return page(strike=1, eyes=2, lifted=True, smoke=True, ring=True, text=True, pose="up")


def full(box, pad=4):
    """a half-size box -> its full-size rectangle (x, y, w, h), padded"""
    x0, y0, x1, y1 = box
    return (max(0, 2 * x0 - pad), max(0, 2 * y0 - pad), 2 * (x1 - x0) + 2 * pad, 2 * (y1 - y0) + 2 * pad)


def inside(box):
    """a rectangle cut to the screen"""
    x, y, w, h = box
    return x, y, min(w, WIDTH - x), min(h, HEIGHT - y)


# The pages it copies from. Each step of the story copies only its own small rectangle out of one of these, so the
# panels that have settled are left alone.
START = kit.rgb565(page())                                    # what drops in: panel 1's night, eyes dark, hero empty
PARTS = kit.rgb565(page(strike=1, eyes=2, smoke=True, ring=True))   # the strike, his lit eyes and smoke, the burst
STRIP = kit.rgb565(strip())                                   # the finished page: his head lifted, his line, arms up
SQUASH = kit.rgb565(page(pose="squash", strike=2))           # also panel 1's dark eyes, for them to flicker
JOLT = kit.rgb565(page(pose="jolt"))
# the other half of each flicker, on one page since none overlap: one eye lit in the close-up, ALIVE! just above where
# it rests, and sparks off his claws
ALT = kit.rgb565(page(strike=1, eyes=1, smoke=True, ring=True, text=True, alive=SNAP, pose="up", crackle=True))
REGIONS = [(max(0, x0 * 2 - 12), max(0, y0 * 2 - 12), min(WIDTH, x1 * 2 + 12), min(HEIGHT, y1 * 2 + 12))
           for x0, y0, x1, y1 in P]   # each panel and the gutters round it, out to the screen's edges, in reading order
STRIKE_BOX = full((*STRIKE_AT, STRIKE_AT[0] + STRIKE_ART.width, STRIKE_AT[1] + STRIKE_ART.height), pad=0)
LENS_BOXES = [full((STRIKE_AT[0] + x - LENS_R - 1, STRIKE_AT[1] + y - LENS_R - 1, STRIKE_AT[0] + x + LENS_R + 2,
                    STRIKE_AT[1] + y + LENS_R + 2), pad=0) for x, y in LENSES]
ZAP_BOX = inside(full((min([x for x, _ in PLATE] + [ZAP_XY[0]]) - 3, min([y for _, y in PLATE] + [ZAP_XY[1]]) - 3,
                       max([x for x, _ in PLATE] + [ZAP_XY[0] + ZAP_SIZE[0] + 6]) + 2,
                       max([y for _, y in PLATE] + [ZAP_XY[1] + ZAP_SIZE[1] + 6]) + 2), pad=0))   # plate, lettering,
                                                                                                # and its shadow
SMOKE_BOX = full((min(x - r for x, _, r in SMOKE), min(y - r for _, y, r in SMOKE), max(x + r for x, _, r in SMOKE) + 1,
                  max(y + r for _, y, r in SMOKE) + 1))
SPARK_BOXES = [inside((x - 44, max(0, y - 44), 88, 88)) for x, y in CLAWS]
# where his lenses are: the pixels eyes_off() dims. A head with none (new art without that blue) lights the whole head
# instead of failing at import
_eye = ImageChops.difference(HEAD, HEAD_DARK).getbbox() or (0, 0, HEAD.width, HEAD.height)
EYES_BOX = full((HEAD_AT[0] + 2 * _eye[0], HEAD_AT[1] + 2 * _eye[1],
                 HEAD_AT[0] + 2 * _eye[2], HEAD_AT[1] + 2 * _eye[3]))
HEAD_BOX = full((P[1][0] + 3, HEAD_UP[1], HEAD_AT[0] + 2 * HEAD.width, P[1][3] - 3), pad=0)   # his head, lifted or not
RING_BOX = full((RING[0] - RING[2], RING[1] - RING_SHAPE["ry"], RING[0] + RING[2], RING[1] + RING_SHAPE["ry"]))
(x1, y1), w1, s1, _ = LINES[0]; (x2, y2), w2, s2, _ = LINES[1]
LINE_BOX = full((x1 - 4, y1 - 4, x1 + 8 * s1 * len(w1) + 6, y1 + 16 * s1 + 6))
ALIVE_BOX = full((x2 - 4, y2 - SNAP - 4, x2 + 8 * s2 * len(w2) + 6, y2 + 16 * s2 + 6))
HERO_BOX = inside((min(xy[0] for _, xy in POSES.values()), 0,
                   max(xy[0] + sp.width for sp, xy in POSES.values()) - min(xy[0] for _, xy in POSES.values()),
                   2 * P[2][3] - 5))   # his whole column of the hero panel, from the screen's top (his claws)
                                       # down to its border


def story():
    """{frame of 120: [(rectangle, page to copy it from)]}: the story told, rectangle by rectangle"""
    steps = {}
    def at(frame, box, src):
        steps.setdefault(frame, []).append((inside(box), src))
    x, y, w, h = STRIKE_BOX
    for i in range(3):                                       # the strike comes down out of the night onto his head,
        at(6 + i, (x, y + h * i // 3, w, h // 3 + 1), PARTS)
    at(8, ZAP_BOX, PARTS)                                    # ZZZAP!,
    for frame, src in ((14, SQUASH), (22, PARTS), (30, SQUASH), (39, PARTS)):   # and his eyes flicker as it hits,
        for box in LENS_BOXES + [ZAP_BOX]:                   # ZZZAP! flashing with them, on the same beats: off, on,
            at(frame, box, src)                              # off, on, 8 or 9 frames apart (under 1.5 a second)
    at(20, SMOKE_BOX, PARTS)                                 # smoke off his head,
    at(21, EYES_BOX, ALT)                                    # one eye on,
    at(24, EYES_BOX, PARTS)                                  # then the other,
    at(27, HEAD_BOX, STRIP)                                  # and his head lifts two pixels of the art
    # His poses swap whole, in one frame each, since in two halves they'd tear, half of one pose over half of the other.
    # It makes these three frames the heaviest of the transition.
    at(32, HERO_BOX, SQUASH)                                 # once his panel is in, the power hits him: squash,
    at(34, HERO_BOX, JOLT)                                   # arms up, eyes lit, jolted high,
    at(36, HERO_BOX, STRIP)                                  # and he settles, arms up. No bounce after.
    for box in SPARK_BOXES:
        at(38, box, ALT); at(47, box, STRIP)                 # a crackle off his claws, a third of a second, once
    x, y, w, h = RING_BOX
    for i in range(4):                                       # the burst, down in four
        at(38 + i, (x, y + h * i // 4, w, h // 4 + 1), PARTS)
    at(42, LINE_BOX, STRIP)                                  # NUMBER 5 IS, as one block
    at(44, ALIVE_BOX, ALT)                                   # ALIVE! lands a little high,
    at(46, ALIVE_BOX, STRIP)                                 # and snaps down to rest
    return steps


STORY = story()


def frames(c, count):
    """120 frames: each panel drops in and its moment plays (0-11 the strike,
    12-23 his eyes and head, 24-37 he comes alive, arms up, 38-47 the burst and his line), the finished page holds
    48-95, and 96-119 the new page wipes down each panel in reading order, done by the last frame. Frames are counted
    out of 120 whatever count is, so the timing holds."""
    shown, wiped = [0] * len(REGIONS), [0] * len(REGIONS)
    done = set()
    for k in range(count):
        f = k * 120 // count
        for i, (x0, y0, x1, y1) in enumerate(REGIONS):        # each panel drops in, top to bottom, over 8 frames
            h = y1 - y0
            edge = round(min(1.0, max(0.0, (f - 12 * i + 1) / 8)) * h)
            if edge > shown[i]:
                c.reveal(x0, y0 + shown[i], x1 - x0, edge - shown[i], START); shown[i] = edge
        for step in range(f + 1):                            # its moments, each once
            if step not in done:
                done.add(step)
                for box, src in STORY.get(step, []):
                    c.reveal(*box, src)
        for i, (x0, y0, x1, y1) in enumerate(REGIONS):        # then the new page wipes down each, 8 frames apiece
            h = y1 - y0
            wipe = min(1.0, max(0.0, (f - 96 - 8 * i + 1) / 8))
            down = h if k == count - 1 else round(wipe * h)   # the last frame is the new page, however count falls
            if down > wiped[i]:
                c.reveal(x0, y0 + wiped[i], x1 - x0, down - wiped[i]); wiped[i] = down
            if 0 < wipe < 1 and k < count - 1:
                c.fill(x0, y0 + down, x1 - x0, 6, INK)               # the wipe's ink edge
        yield
