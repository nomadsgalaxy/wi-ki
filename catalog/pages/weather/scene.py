"""scene: Philadelphia in pixel art, with the real weather playing over it. Part of the weather kiosk.

The view is the classic one from the South Street Bridge, drawn from a photo of it: the Schuylkill in front
mirroring everything, rowhouses and trees along the far bank (green, then orange, then bare as the year turns), and
Center City behind, with the real towers at their real relative heights: the Comcast Technology Center's slender
top, the Comcast Center's gold crown, One and Two Liberty's chevron crowns, BNY Mellon's pyramid over the WSFS sign,
Commerce Square's dark towers with their corner ears, and Rittenhouse's high-rises running off to the right.

The sky follows the clock: day, golden hour, dusk and night, with the moon in its real phase. Open-Meteo's weather
code brings the clouds, rain, snow, fog or lightning, and the wind pushes them. At night the windows and the Liberty
crowns light up, and their lights glint in the water.

Everything is drawn at ART (300x128) and scaled up 4x with no smoothing, so each art pixel is a crisp 4x4 block.

  scene.draw(w, now, t) -> 300x128 RGB image. w is Open-Meteo JSON, now a datetime, t seconds (the animation clock).
"""
import hashlib, math, os
from datetime import datetime
from PIL import Image, ImageDraw, ImageFilter

ART = (300, 128)
LOOP, FPS = 64.0, 4   # the animation repeats exactly every 64 s (256 frames): every motion completes whole laps in it


def laps(speed, wrap):
    """the speed nearest `speed` that crosses `wrap` a whole number of times per LOOP"""
    return max(1, round(speed * LOOP / wrap)) * wrap / LOOP


def wave(rate):
    """the angular rate nearest `rate` (radians a second) that makes whole cycles per LOOP"""
    return max(1, round(rate * LOOP / (2 * math.pi))) * 2 * math.pi / LOOP
STRIKE = int(LOOP * FPS) // 4   # frames between lightning strikes (16 s)
NEW_MOON = datetime(2000, 1, 6, 18, 14)
ARC, PHASES = 100, 60   # the sun and moon move along their arc in 100 steps, and the moon has 60 phases


def rand(*k):
    """a repeatable 0..1 from some ints (murmur3's finaliser), so the city is the same every frame"""
    h = 0x9E3779B9
    for v in k:
        h ^= int(v) & 0xffffffff
        h = (h * 0x85EBCA6B) & 0xffffffff; h ^= h >> 13
        h = (h * 0xC2B2AE35) & 0xffffffff; h ^= h >> 16
    return h / 4294967296


def mix(a, b, t):
    t = max(0.0, min(1.0, t))
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def shade(c, k):
    return tuple(max(0, min(255, round(v * k))) for v in c)


# what each weather code puts in the sky: (cloud cover 0-1, how dark the clouds are 0-1, precipitation, amount, fog)
def weather_of(code):
    table = {0: (0, 0, None, 0, 0), 1: (.15, 0, None, 0, 0), 2: (.45, .1, None, 0, 0), 3: (.9, .35, None, 0, 0),
             45: (.6, .2, None, 0, 1), 48: (.6, .2, None, 0, 1),
             51: (.8, .45, "rain", 25, 0), 53: (.8, .45, "rain", 35, 0), 55: (.85, .5, "rain", 50, 0),
             56: (.85, .5, "rain", 35, 0), 57: (.85, .5, "rain", 50, 0),
             61: (.85, .5, "rain", 70, 0), 63: (.9, .6, "rain", 120, 0), 65: (1, .7, "rain", 200, 0),
             66: (.9, .6, "rain", 100, 0), 67: (1, .7, "rain", 180, 0),
             71: (.85, .3, "snow", 60, 0), 73: (.9, .35, "snow", 110, 0), 75: (1, .4, "snow", 180, 0), 77: (.85, .3, "snow", 50, 0),
             80: (.75, .5, "rain", 90, 0), 81: (.85, .6, "rain", 140, 0), 82: (1, .75, "rain", 220, 0),
             85: (.8, .35, "snow", 80, 0), 86: (.95, .4, "snow", 150, 0),
             95: (1, .85, "storm", 160, 0), 96: (1, .85, "storm", 180, 0), 99: (1, .9, "storm", 200, 0)}
    return table.get(code, (.4, .2, None, 0, 0))


def shadow(phase):
    """how far the moon's shadow sits from the moon, in art pixels: none when new, a whole moon off to the left when
    full (waxing: lit on the right), coming back in from the right as it wanes"""
    return -18 * phase if phase < 0.5 else 18 * (1 - phase)


def daylight(w, now):
    """-> (light 0 night .. 1 day, golden 0..1 how close to sunrise/sunset, t 0..1 across the sky, sun up?)"""
    d = w["daily"]
    rise = datetime.strptime(d["sunrise"][0], "%Y-%m-%dT%H:%M").replace(year=now.year, month=now.month, day=now.day)
    sset = datetime.strptime(d["sunset"][0], "%Y-%m-%dT%H:%M").replace(year=now.year, month=now.month, day=now.day)
    m = lambda a, b: (a - b).total_seconds() / 60
    to_edge = min(m(now, rise), m(sset, now))            # minutes from the nearer of sunrise and sunset; < 0 at night
    light = max(0.0, min(1.0, (to_edge + 40) / 100))     # fades over the 40 min either side of the horizon, and up
    golden = max(0.0, 1 - abs(to_edge - 10) / 60)
    if rise <= now <= sset:
        return light, golden, m(now, rise) / max(1, m(sset, rise)), True
    since = m(now, sset) if now > sset else m(now, rise) + 24 * 60 - m(sset, rise)
    return light, golden, since / max(1, 24 * 60 - m(sset, rise)), False


def sky_colours(light, golden, cover, dark):
    """the sky's top, middle and horizon colours. Around sunrise and sunset the horizon warms to orange, the middle to
    pink and the top to purple, most strongly in clear weather, and it all fades smoothly into night."""
    night = ((6, 9, 28), (28, 38, 74))
    day = ((52, 108, 205), (158, 205, 242))
    dusk = ((44, 46, 104), (246, 140, 92))
    top = mix(mix(night[0], dusk[0], min(1, light * 2)), day[0], max(0, light * 2 - 1))
    low = mix(mix(night[1], dusk[1], min(1, light * 2)), day[1], max(0, light * 2 - 1))
    warm = max(0.0, min(1.0, max(golden, 1 - abs(light - 0.45) / 0.45))) * (1 - cover * 0.7)   # the sunset's strength
    mid = mix(top, low, 0.5)
    low = mix(low, (255, 146, 78), warm * 0.85)
    mid = mix(mid, (214, 112, 142), warm * 0.6)
    top = mix(top, (72, 58, 138), warm * 0.45)
    grey = shade((150, 158, 172), 0.35 + 0.65 * light)
    k = cover * 0.75 + dark * 0.2
    return (mix(top, shade(grey, 1 - dark * 0.45), k), mix(mid, shade(grey, 1.02 - dark * 0.42), k),
            mix(low, shade(grey, 1.05 - dark * 0.4), k), warm)


BAYER = ((0, 2), (3, 1))


def sky(top, mid, low):
    """the sky in 9 bands from top through mid to the horizon, dithered where they meet: the pixel-art gradient. The
    dither only depends on x % 2, so each row is two colours taking turns, built as bytes rather than pixel by pixel"""
    bands = 9
    cols = [mix(top, mid, i / 4) if i <= 4 else mix(mid, low, (i - 4) / 4) for i in range(bands)]
    rows = []
    for y in range(ART[1]):   # the horizon colour sits at the skyline's foot, where you can see it
        f = min(1.0, y / WATERLINE) * (bands - 1); i = int(f)
        a, b = (cols[min(bands - 1, i + (1 if (f - i) * 4 > BAYER[y % 2][x] + 0.5 else 0))] for x in (0, 1))
        rows.append(bytes(a + b) * (ART[0] // 2))
    return Image.frombytes("RGB", ART, b"".join(rows))


_leaves = {}
LEAVES = os.path.expanduser("~/.cache/kiosk/foliage")   # the leaf patterns, kept across restarts: seconds on a Zero
LEAVES_VERSION = 1                                      # bump it when foliage() draws its leaves differently


def leaves_on_disk(key, n, masks=None):
    """the n leaf masks for key from LEAVES, or (masks given) save them there; None if they aren't there or won't read"""
    path = os.path.join(LEAVES, hashlib.sha1(repr((LEAVES_VERSION, key)).encode()).hexdigest()[:16])
    size = ART[0] * ART[1]
    try:
        if masks is None:
            data = open(path, "rb").read()
            if len(data) != n * size:
                return None
            return [Image.frombytes("L", ART, data[i * size:(i + 1) * size]) for i in range(n)]
        os.makedirs(LEAVES, exist_ok=True)
        with open(path + ".tmp", "wb") as f:
            f.write(b"".join(m.tobytes() for m in masks))
        os.replace(path + ".tmp", path)
    except OSError:
        return None   # no cache is only slower


def foliage(img, blobs, greens, seed, night=False, bare=0, accents=()):
    """a tree canopy in pixel art: the union of some (cx, cy, rx, ry) ellipses, filled with clumps of leaves from
    layered noise, lit from the upper left, with ragged edges. greens run darkest to lightest. The leaf pattern never
    changes, only its colours, so it's worked out once (slow on the Pi Zero) and recoloured from then on."""
    key = (tuple(blobs), seed, bare, tuple(accents))
    if key not in _leaves:
        _leaves[key] = leaves_on_disk(key, 4 + len(accents))
    if _leaves[key] is None:
        # the canopy's shape, drawn in C; its edge is whatever a 3x3 min-filter eats away
        shape = Image.new("L", ART, 0); sd = ImageDraw.Draw(shape)
        for cx, cy, rx, ry in blobs:
            sd.ellipse((cx - rx, cy - ry, cx + rx, cy + ry), fill=255)
        inner = shape.filter(ImageFilter.MinFilter(3))
        box = shape.getbbox() or (0, 0, 1, 1)
        x0, y0, x1, y1 = box; mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        sp, ip = shape.load(), inner.load()
        idx = Image.new("L", ART, 0); px = idx.load()
        for y in range(y0, y1):
            for x in range(x0, x1):
                if not sp[x, y]:
                    continue
                edge = not ip[x, y]
                if (edge and rand(seed, x, y) < 0.45) or rand(seed + 4, x, y) < bare:   # ragged edges, bare branches
                    continue
                for j, (colour, share) in enumerate(accents):   # blossom or turning leaves, scattered through
                    if rand(seed + 10 + j, x // 2, y) < share:
                        px[x, y] = 5 + j; break
                else:
                    clump = rand(seed + 1, x // 3, y // 2) * 0.55 + rand(seed + 2, x // 2, y // 2) * 0.25 + rand(seed + 3, x, y) * 0.2
                    lit = clump + (mx - x) / (x1 - x0) * 0.35 + (my - y) / (y1 - y0) * 0.45 - (0.15 if edge else 0)
                    px[x, y] = 1 + (0 if lit < 0.3 else 1 if lit < 0.55 else 2 if lit < 0.78 else 3)
        _leaves[key] = [idx.point(lambda v, i=i: 255 if v == i + 1 else 0) for i in range(4 + len(accents))]
        leaves_on_disk(key, len(_leaves[key]), _leaves[key])
    for i, mask in enumerate(_leaves[key]):
        colour = greens[min(i, 1 if night else 3)] if i < 4 else shade(accents[i - 4][0], 0.45 if night else 1)
        img.paste(colour + ((255,) if img.mode == "RGBA" else ()), (0, 0), mask)


# --- the city -----------------------------------------------------------------------------------------------------
# Traced from "The Philadelphia skyline (cropped)" by Mefman00 (Wikimedia Commons, CC BY-SA 4.0), taken from the
# South Street Bridge on 31 December 2024: the Schuylkill in front, mirroring the skyline, and Center City behind.
# Mapped onto the scene at 0.156x (photo pixel x, y on the 1920x1200 copy -> scene x*0.156, (y-200)*0.156), with
# colours sampled from it. The Schuylkill Banks Boardwalk sweeps across the bottom right on its piers.
WATERLINE = 92                                                                  # the far bank, mirrored about here
RIVER = [(0, 92), (300, 92), (300, 128), (0, 128)]
def land():
    """the ground right of where the boardwalk leaves the shore: from the tree line down to the boardwalk's far railing,
    and on the right down to the foot of the retaining wall. None of it is river."""
    far = []
    for sx in range(48, 301, 4):
        px = sx / 0.15625
        rh = (8 + 37 * max(0.0, min(1.0, (px - 300) / 1300))) * 0.15625
        wall = 119 + (sx - 156) * 5 / 53 if 156 <= sx < 209 else 124 if sx >= 209 else 0
        far.append((sx, max((rail_top(px) - 200) * 0.15625 - rh * 1.65 + 1, wall)))
    return [(48, 88), (300, 84)] + far[::-1]
WATER_TOP = WATERLINE

# the trees change with the seasons: four leaf colours darkest to lightest, how bare they are, and accents
# (colour, share of leaves) sprinkled through: spring blossom, fall's reds and the last green leaves
SEASONS = {"spring": (((48, 84, 34), (84, 128, 52), (130, 172, 80), (176, 206, 118)), 0.05, [((246, 190, 212), 0.16), ((252, 246, 240), 0.06)]),
           "summer": (((26, 46, 20), (46, 78, 30), (76, 114, 42), (120, 152, 58)), 0, []),
           "fall":   (((84, 40, 20), (156, 72, 28), (206, 122, 40), (236, 182, 72)), 0.12, [((186, 48, 30), 0.12), ((96, 112, 42), 0.07)]),
           "winter": (((70, 60, 50), (98, 86, 72), (124, 110, 94), (150, 136, 116)), 0.5, [])}


def season(month):
    return "winter" if month in (12, 1, 2, 3) else "spring" if month in (4, 5) else "fall" if month in (10, 11) else "summer"


def city(light, golden, now_seed, glow, month=6):
    """the skyline, the rowhouses and the trees along the far bank, as a transparent layer"""
    img = Image.new("RGBA", ART, (0, 0, 0, 0)); r = ImageDraw.Draw(img); d = r
    sun = 0.45 + 0.55 * light
    warm = (255, 196, 140)
    night = glow > 0.7                                                   # the trees lose their highlights
    lamp = lambda x, y, odds=0.42: glow > 0 and rand(7, x, y, now_seed) < odds * glow   # windows come on one by one through dusk
    lit = lambda day, on, start=0.0: mix(day, on, (glow - start) / (1 - start))   # a light fading up from its day colour

    def tint(c):
        c = shade(c, sun)
        return mix(c, warm, golden * 0.25 * light) if golden else c

    def glass(x0, x1, top, colour, bottom=92, floors=2):
        """a glass tower: a sunlit left edge, a shadowed right one, floor lines; windows lit at night"""
        base = tint(colour)
        r.rectangle((x0, top, x1, bottom), fill=base)
        r.line((x0, top, x0, bottom), fill=shade(base, 1.2)); r.line((x1, top, x1, bottom), fill=shade(base, 0.76))
        for y in range(top + 1, bottom, floors):
            for x in range(x0 + 1, x1):
                if lamp(x, y, 0.3): r.point((x, y), fill=(255, 226, 150) if rand(8, x, y) < 0.7 else (236, 244, 255))
                elif glow < 0.5 and y % 4 == 0: r.point((x, y), fill=shade(base, 0.88))

    def stone(x0, x1, top, colour, bottom=92, win=None):
        """masonry or concrete: punched windows in a grid"""
        base = tint(colour)
        r.rectangle((x0, top, x1, bottom), fill=base)
        r.line((x1, top, x1, bottom), fill=shade(base, 0.8))
        for y in range(top + 2, bottom, 2):
            for x in range(x0 + 1, x1, 2):
                r.point((x, y), fill=(255, 214, 130) if lamp(x, y) else tint(win) if win else shade(base, 0.72))

    def liberty(x0, x1, apex, base, spire, colour):
        """One and Two Liberty: a steep gabled crown of stacked chevrons over a blue glass shaft"""
        mid = (x0 + x1) / 2
        if spire:
            r.line((round(mid), apex - spire, round(mid), apex - 1), fill=lit(tint((210, 214, 220)), (250, 252, 255), 0.3))
        glass(x0, x1, base, colour)
        half = lambda y: (x1 - x0) / 2 * (y - apex + 1) / (base - apex)   # the gable's half-width at row y
        for y in range(apex, base):   # the crown: a sunlit left face and a shadowed right one
            h = half(y)
            r.line((round(mid - h), y, round(mid), y), fill=tint(shade(colour, 1.18)))
            r.line((round(mid) + 1, y, round(mid + h), y), fill=tint(shade(colour, 0.82)))
        on = lit(tint((214, 226, 236)), (250, 252, 255), 0.3)
        for k in range((base - apex) // 3):   # the chevrons: Vs stepping down the crown, kept a pixel inside it
            y0 = apex + 2 + k * 3
            for j in range(round((x1 - x0) / 2) + 1):
                y = y0 + j // 2
                if y >= base or j > half(y) - 1:
                    continue
                for x in (round(mid) - j, round(mid) + j):
                    r.point((x, y), fill=on)

    # far left: a low green-glass block, the tall grey-and-cream tower, and the low blocks by the river
    glass(0, 8, 69, (80, 120, 118))
    stone(9, 22, 47, (150, 160, 168), win=(96, 110, 120)); stone(22, 30, 47, (232, 220, 190), win=(196, 184, 156))
    r.rectangle((14, 44, 21, 46), fill=tint((150, 160, 168)))
    glass(30, 37, 56, (74, 92, 104))
    stone(30, 61, 70, (204, 200, 190), win=(150, 150, 146)); stone(35, 47, 66, (190, 190, 184))
    stone(61, 87, 73, (176, 96, 74), win=(120, 70, 58))                       # the red brick warehouse
    # the curved blue glass tower, then Commerce Square's two dark towers with the ears on their corners
    glass(47, 60, 44, (90, 155, 177)); r.line((48, 45, 48, 92), fill=tint((170, 214, 226)))
    for x0, x1, top in ((54, 69, 40), (72, 87, 42)):
        stone(x0, x1, top, (120, 132, 134), win=(86, 96, 100))
        for ex in (x0 + 1, x1 - 2):
            r.rectangle((ex, top - 3, ex + 1, top), fill=tint((120, 132, 134)))
    # Comcast Technology Center: a slender top with its blade, stepping out to a wider sunlit block
    r.rectangle((89, 9, 91, 16), fill=lit(tint((176, 190, 204)), (110, 126, 156)))
    glass(88, 93, 16, (112, 130, 148)); glass(93, 102, 23, (131, 178, 200))
    if glow > 0.5:
        r.line((93, 23, 102, 23), fill=(232, 238, 252))
        for y in range(10, 16, 2): r.point((90, y), fill=(226, 236, 255))
    glass(105, 112, 46, (120, 150, 160))
    # the white tower with balconies, right in front
    stone(87, 104, 38, (218, 220, 204), win=(176, 180, 170))
    for y in range(39, 92, 2): r.line((87, y, 89, y), fill=tint((236, 236, 226)))
    # the blue glass tower with the pointed top, then the Comcast Center and its crown and notch
    glass(104, 115, 39, (130, 172, 170)); r.polygon([(104, 39), (110, 36), (115, 39)], fill=tint((130, 172, 170)))
    glass(112, 123, 24, (82, 122, 144))
    r.rectangle((112, 24, 123, 31), fill=lit(tint((236, 228, 200)), (240, 236, 210), 0.2))
    r.rectangle((118, 32, 121, 39), fill=tint((40, 56, 72)))
    glass(115, 123, 54, (60, 70, 82))
    # BNY Mellon: the stepped pyramid, then the WSFS building in front with its sign
    glass(127, 140, 36, (82, 121, 144))
    for i, y in enumerate(range(35, 30, -1)):   # the pyramid: solid, a sunlit face and a shadowed one, and a finial
        left, right = 127 + round(i * 1.4), 140 - round(i * 1.4)
        if left > right: break
        mid = (left + right) // 2
        r.line((left, y, mid, y), fill=lit(tint((236, 228, 200)), (255, 246, 220), 0.3))
        r.line((mid + 1, y, right, y), fill=lit(tint((150, 168, 186)), (200, 196, 180), 0.3))
    r.point((133, 30), fill=tint((210, 214, 220)))
    stone(128, 146, 47, (106, 127, 132), win=(72, 86, 92))
    for x in list(range(131, 138)) + list(range(141, 145)): r.point((x, 49), fill=lit(tint((226, 232, 228)), (120, 230, 160), 0.4))
    # the beige mid-rises, One Liberty, the plain tower beside it, Two Liberty, and the brick one in front
    stone(117, 140, 62, (196, 186, 160)); stone(146, 152, 62, (182, 172, 152))
    stone(151, 166, 61, (172, 162, 142)); glass(152, 171, 69, (110, 128, 136))
    liberty(161, 175, 30, 42, 8, (75, 110, 130))
    stone(175, 188, 29, (150, 160, 165), win=(100, 116, 126))
    liberty(188, 199, 33, 42, 0, (92, 125, 140))   # Two Liberty: no spire, just the point
    stone(171, 184, 65, (196, 200, 204), win=(126, 136, 146)); stone(189, 205, 56, (150, 122, 104), win=(110, 86, 72))
    # Rittenhouse, running off to the right: tan and white high-rises, one with an antenna
    for x0, x1, top, c in ((201, 212, 50, (176, 170, 156)), (225, 239, 54, (192, 188, 174)), (239, 246, 56, (180, 174, 160)),
                           (247, 256, 62, (188, 180, 166)), (256, 266, 64, (170, 164, 150)), (266, 275, 66, (182, 176, 162)),
                           (275, 281, 59, (176, 170, 156)), (280, 288, 52, (188, 182, 168)), (288, 300, 59, (170, 166, 154))):
        stone(x0, x1, top, c)
    glass(213, 221, 50, (110, 128, 136)); r.line((232, 47, 232, 54), fill=tint((150, 150, 156)))
    if glow > 0.4: r.point((232, 47), fill=(255, 40, 40))

    # rowhouses along the bank: short brick and white fronts, flat roofs, chimneys
    for i, x in enumerate(range(28, 300, 5)):
        h = 4 + int(rand(60, i) * 6); w_ = 4 + int(rand(61, i) * 3)
        c = [(150, 104, 88), (196, 190, 176), (128, 92, 80), (210, 204, 190), (122, 110, 100)][int(rand(62, i) * 5)]
        stone(x, x + w_, 90 - h, c)
        if rand(63, i) < 0.4: r.rectangle((x + 1, 88 - h, x + 1, 89 - h), fill=tint((90, 70, 60)))
    # the far left: a road bridge over the river, and the promenade along the water
    r.rectangle((0, 84, 19, 86), fill=tint((120, 136, 120))); r.line((0, 84, 19, 84), fill=tint((170, 184, 168)))
    for x in (4, 12): r.line((x, 87, x, 92), fill=tint((96, 104, 100)))
    r.rectangle((0, 90, 48, 92), fill=tint((110, 112, 110)))
    # the right bank: the path on land with its railing, the retaining wall under it, graffiti on the far part
    r.polygon(land(), fill=tint((52, 48, 40)))
    r.rectangle((156, 110, 300, 112), fill=tint((176, 180, 186)))
    for x in range(156, 300): r.point((x, 108), fill=tint((200, 206, 214)))
    for x in range(156, 300, 3): r.line((x, 108, x, 110), fill=tint((150, 158, 170)))
    r.polygon([(156, 112), (300, 112), (300, 124), (209, 124), (156, 119)], fill=tint((126, 128, 126)))
    for i in range(34):   # graffiti: blocky tags in blues, purples and white along the far part of the wall
        x, y = 209 + int(rand(70, i) * 88), 113 + int(rand(71, i) * 8)
        w_, h_ = 2 + int(rand(75, i) * 5), 1 + int(rand(76, i) * 3)
        c = tint([(70, 96, 196), (130, 90, 170), (220, 224, 236), (60, 150, 190), (40, 44, 60)][int(rand(72, i) * 5)])
        r.rectangle((x, y, x + w_, y + h_), fill=c)
        if w_ > 3: r.line((x + 1, y + h_ // 2, x + w_ - 1, y + h_ // 2), fill=shade(c, 0.6))
    # the trees along the bank, in their season, then the evergreen and the big tree on the right
    colours, bare, accents = SEASONS[season(month)]
    foliage(img, [(70 + i * 8 + rand(64, i) * 5, 86 + rand(65, i) * 4, 6 + rand(66, i) * 4, 7 + rand(67, i) * 3) for i in range(22)]
                 + [(74 + i * 9 + rand(68, i) * 5, 95 + rand(69, i) * 3, 6 + rand(73, i) * 3, 5 + rand(74, i) * 2) for i in range(20)]
                 + [(270, 82, 6, 8), (286, 78, 12, 14), (296, 90, 8, 12)],
            [tint(c) for c in colours], 500 + month // 3, night, bare, accents)
    foliage(img, [(248, 96, 9, 7), (256, 92, 7, 8), (262, 98, 6, 6)], [tint(c) for c in SEASONS["summer"][0]], 520, night)  # the evergreen
    return img


# The Schuylkill Banks Boardwalk, measured on the photo (photo x -> near rail's top y), and how its parts grow as it
# comes toward the camera. Everything is in photo pixels here and converted with ph() below.
RAIL_TOP = [(305, 800), (450, 815), (550, 832), (700, 850), (800, 870), (900, 893), (1000, 903), (1100, 920), (1200, 938),
            (1300, 960), (1400, 980), (1500, 1000), (1600, 1020), (1700, 1040), (1920, 1085)]
PIERS = [380, 470, 560, 650, 760, 850, 950, 1050, 1170, 1290, 1420, 1560, 1700]
LAMPS = [(510, 775), (530, 775), (555, 778), (580, 780), (615, 782), (670, 785), (720, 790), (760, 800), (820, 795),
         (870, 800), (940, 795), (975, 800), (1070, 812), (1170, 840), (1300, 845)]   # (photo x, top of the lamp)
ph = lambda x, y: (x * 0.15625, (y - 200) * 0.15625)


def rail_top(px):
    """the near rail's top in photo y, at photo x"""
    for (x0, y0), (x1, y1) in zip(RAIL_TOP, RAIL_TOP[1:]):
        if px <= x1:
            return y0 + (y1 - y0) * max(0, px - x0) / (x1 - x0)
    return RAIL_TOP[-1][1]


def foreground(light, golden, glow, month=6, precip=None):
    """the boardwalk: its railings, deck, piers and lamps, with their shadows and reflections on the river"""
    img = Image.new("RGBA", ART, (0, 0, 0, 0)); d = ImageDraw.Draw(img)
    k = 0.4 + 0.6 * light
    rail, post, slab = shade((176, 190, 206), k), shade((104, 116, 134), k), shade((136, 146, 158), k)   # blue-grey, like the photo
    deck = (232, 236, 242) if precip == "snow" else shade((160, 168, 178), k)
    under, pier = (20, 24, 30, 210), shade((70, 72, 76), k)
    grow = lambda px: max(0.0, min(1.0, (px - 300) / 1300))           # 0 at the far end, 1 up close
    for sx in range(round(ph(305, 0)[0]), 300):
        px = sx / 0.15625
        top = ph(0, rail_top(px))[1]
        rh, sh, pl = (8 + 37 * grow(px)) * 0.15625, (6 + 8 * grow(px)) * 0.15625, (22 + 58 * grow(px)) * 0.15625
        dw = rh * 1.1                                                    # how much deck you see from up on the bridge
        y_far, y_rail, y_deck, y_slab = top - dw - rh * 0.55, top, top + rh, top + rh + sh
        d.line((sx, y_slab, sx, y_slab + pl), fill=under)                # the shadow under the deck
        d.line((sx, top - dw, sx, y_rail), fill=deck)                    # the deck's walking surface
        if sx % 4 == 0: d.line((sx, y_far, sx, top - dw), fill=post)     # the far railing, its posts
        d.point((sx, y_far), fill=rail)
        d.line((sx, y_deck, sx, y_slab), fill=slab)                      # the slab's side face
        d.point((sx, y_slab), fill=shade(slab, 0.7))
        if sx % 2 == 0 or rh > 4:                                        # the near railing: balusters, posts, the top rail
            d.line((sx, y_rail, sx, y_deck), fill=post if sx % 6 else rail)
        d.point((sx, y_rail), fill=rail); d.point((sx, y_deck - 1), fill=post)
    for p in PIERS:                                                      # piers: dark bents down to the water, reflected
        sx = p * 0.15625
        top = ph(0, rail_top(p))[1]
        rh, sh, pl = (8 + 37 * grow(p)) * 0.15625, (6 + 8 * grow(p)) * 0.15625, (22 + 58 * grow(p)) * 0.15625
        w_ = 1 + round(3 * grow(p)); y0 = top + rh + sh; y1 = y0 + pl
        d.rectangle((sx, y0, sx + w_, y1), fill=pier)
        d.line((sx, y0, sx, y1), fill=shade(pier, 1.25))
        d.rectangle((sx, y1 + 1, sx + w_, y1 + pl * 0.6), fill=shade(pier, 0.7) + (150,))
    for lx, ly in LAMPS:                                                 # the lamps: a pole, a little tilted solar panel
        sx = round(lx * 0.15625); tip = ph(0, ly)[1]
        rh = (8 + 37 * grow(lx)) * 0.15625; base = ph(0, rail_top(lx))[1] - rh * 2.1   # on the far railing
        d.line((sx, tip, sx, base), fill=shade((190, 196, 204), k))
        d.line((sx - 1, tip - 1, sx + 1, tip - 2), fill=shade((60, 72, 96), k))
        if glow > 0.35:   # the lamps come on early in the dusk
            d.point((sx - 1, tip + 1), fill=(255, 226, 150))
            for dy in range(3): d.point((sx - 1, 2 * WATERLINE - tip + dy * 3), fill=(255, 210, 130, 160))   # glints below
    return img


# --- the moving parts ---------------------------------------------------------------------------------------------
def cloud(seed, size, light, dark, warm=0.0):
    """a puffy pixel cloud: lit tops, a body, a shadowed base; pink and gold when the sun is low"""
    w, h = size, size // 3 + 4
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0)); d = ImageDraw.Draw(img)
    base = mix(shade(mix((246, 248, 252), (110, 116, 130), dark), 0.35 + 0.65 * light), (250, 168, 150), warm * 0.55)
    for i in range(5):
        cx = int(w * (0.15 + 0.7 * rand(seed, i, 1))); r = int(h * (0.3 + 0.25 * rand(seed, i, 2)))
        d.ellipse((cx - r * 1.4, h - 2 - r * 2, cx + r * 1.4, h - 2), fill=base)
    d.rectangle((2, h - 4, w - 3, h - 2), fill=base)
    out = img.copy(); px, op = img.load(), out.load()
    for y in range(h):
        for x in range(w):
            if px[x, y][3]:
                above = y == 0 or not px[x, y - 1][3]
                below = y == h - 1 or not px[x, min(h - 1, y + 2)][3]
                if above: op[x, y] = shade(base, 1.08) + (255,)
                elif below: op[x, y] = shade(base, 0.8) + (255,)
    return out


def moon(now):
    """the moon's phase, 0 new .. 0.5 full .. 1 new again"""
    return ((now - NEW_MOON).total_seconds() / 86400 % 29.530588) / 29.530588


def wind_of(w):
    """how hard the wind pushes things, from its speed in whole mph (finer would only redraw the loop for nothing)"""
    return max(0.5, round(w["current"].get("wind_speed_10m") or 5) / 6)   # a null reading runs at the default 5 mph, not a crash


def layer_key(light, golden, weather, now):
    """-> (key, glow): what the cached layers depend on. The clock is only in it while the windows light up through
    dusk, since they reshuffle every 5 minutes then; the rest of the time the layers last until the light or the weather
    changes"""
    cover, dark, precip = weather[:3]
    glow = max(0.0, min(1.0, (0.65 - light) / 0.5))   # 0 by day, rising through dusk, 1 once it's dark
    clock = (now.hour, now.minute // 5) if 0 < glow < 1 else ()   # the windows only change through dusk
    return (round(light, 2), round(golden, 2), cover, dark, precip, now.month) + clock, glow


def moment(w, now):
    """a key for the loop draw() makes at `now`: the layers, the wind, and where the sun or moon is if it's out. Two
    moments with the same key look the same, so the weather page can replay one loop instead of drawing it again"""
    light, golden, arc, sunup = daylight(w, now)
    weather = weather_of(w["current"]["weather_code"])
    key = layer_key(light, golden, weather, now)[0] + (wind_of(w),)
    cover, _, precip, _, fog = weather
    if cover < 0.85 and not precip and not fog:
        key += (round(arc * ARC), sunup) + (() if sunup else (round(moon(now) * PHASES),))
    return key


_cache = {}


def layers(w, now):
    """everything that only changes every few minutes, cached"""
    light, golden, arc, sunup = daylight(w, now)
    cover, dark, precip, amount, fog = weather_of(w["current"]["weather_code"])
    key, glow = layer_key(light, golden, (cover, dark, precip), now)
    if key not in _cache:
        _cache.clear()
        top, mid, low, warm = sky_colours(light, golden, cover, dark)
        _cache[key] = {"sky": sky(top, mid, low), "city": city(light, golden, now.hour * 12 + now.minute // 5, glow, now.month),
                       "fore": foreground(light, golden, glow, now.month, precip), "glow": glow,
                       "clouds": [cloud(i, 26 + int(rand(50, i) * 40), light, dark, warm) for i in range(int(cover * 9))],
                       "water": shade(mix(low, (40, 80, 110), 0.35), 0.85), "deep": shade((34, 56, 50), 0.4 + 0.6 * light)}
        # the water mirrors the sky and the city about the waterline, blended once here; each frame only shifts its
        # rows to ripple them, then pastes them through the channel's shape
        L = _cache[key]
        above = L["sky"].copy(); above.paste(L["city"], (0, 0), L["city"])
        rows = []
        for y in range(WATER_TOP, 128):
            src = above.crop((0, max(0, round(2 * WATERLINE - y * 1.0 - (y - WATERLINE) * 0.1)), 300, 1 + max(0, round(2 * WATERLINE - y * 1.0 - (y - WATERLINE) * 0.1))))
            # far water is dark and green (the trees and the bridge's shadow), near water mirrors the sky
            tone = mix(L["deep"], L["water"], (y - WATERLINE) / 40)
            rows.append(Image.blend(src, Image.new("RGB", (300, 1), tone), 0.45 if y >= WATERLINE else 0.75))
        L["refl"] = rows
        mask = Image.new("L", (300, 128 - WATER_TOP), 0); md = ImageDraw.Draw(mask)
        md.polygon([(x, y - WATER_TOP) for x, y in RIVER], fill=255); md.polygon([(x, y - WATER_TOP) for x, y in land()], fill=0)
        L["mask"] = mask
    return _cache[key], (light, golden, arc, sunup), (cover, dark, precip, amount, fog)


_paths = {}


def paths(cover, precip, amount, wind):
    """where every star, cloud, glint, raindrop, snowflake and wisp of mist starts and how fast it moves. They depend
    only on the weather, never on the frame, so they're worked out once here instead of 256 times a loop"""
    key = (cover, precip, amount, wind)
    if key not in _paths:
        _paths.clear()
        wh = 128 - WATER_TOP
        P = {"stars": [(int(rand(1, i) * 300), int(rand(2, i) * 70), rand(5, i), rand(4, i) < 0.3) for i in range(70)],
             "ceiling": (laps(wind, 300), [3 + int(3 * rand(54, k)) for k in range(50)]),
             "ripple": wave(1.6), "clouds": [], "glints": [], "mist": []}
        for i in range(int(cover * 9)):
            span = 300 + 26 + int(rand(50, i) * 40)   # the cloud's width, as layers() makes it
            P["clouds"].append((span, rand(51, i) * span, laps(wind * (0.8 + rand(52, i)), span),
                                int(4 + rand(53, i) * (30 if cover < 0.8 else 22))))
        for i in range(46 if precip else 30):
            y = int(rand(60, i) * wh)
            P["glints"].append((y, rand(61, i) * 300, laps(4 * (1 + y / 30), 300), 1 + int(rand(62, i) * (1 + y // 20))))
        P["rain"] = (laps(40 * wind / 3, 340), laps(120, 140), [(rand(70, i) * 340, rand(71, i) * 140) for i in range(amount)])
        P["snow"] = (laps(wind * 3, 320), wave(1), [(rand(75, i) * 320, rand(76, i) * 136, laps(10 + 8 * rand(77, i), 136),
                                                     1 if rand(78, i) < 0.7 else 2) for i in range(amount)])
        for i in range(7):
            P["mist"].append((laps(1.5 + i % 3, 300), [(int(rand(90, i, k) * 3), 2 + int(rand(91, i, k) * (3 + i))) for k in range(50)]))
        _paths[key] = P
    return _paths[key]


def draw(w, now, t):
    L, (light, golden, arc, sunup), (cover, dark, precip, amount, fog) = layers(w, now)
    light, golden = round(light, 2), round(golden, 2)   # as the key has them, so one key always draws one picture
    img = L["sky"].copy(); d = ImageDraw.Draw(img, "RGBA")
    t = t % LOOP
    glow, frame = L["glow"], round(t * FPS) % int(LOOP * FPS)
    night = glow > 0.5
    wind = wind_of(w)
    P = paths(cover, precip, amount, wind)

    if glow > 0.3 and cover < 0.7:   # stars, the brightest first, more as it gets darker, twinkling
        for i, (x, y, bright, white) in enumerate(P["stars"]):
            if bright < (glow - 0.3) / 0.7 and rand(3, i, frame // 4) > 0.15:
                d.point((x, y), fill=(255, 255, 255) if white else (170, 180, 210))

    # the sun or the moon on its arc, the moon in its real phase
    arc = round(arc * ARC) / ARC
    bx, by = 8 + arc * 284, 84 - 74 * math.sin(math.pi * arc)
    if cover < 0.85 and not precip and not fog:
        if sunup:
            glow = mix((255, 230, 150), (255, 150, 80), golden)
            d.ellipse((bx - 7, by - 7, bx + 7, by + 7), fill=glow + (60,))
            d.ellipse((bx - 4, by - 4, bx + 4, by + 4), fill=mix((255, 244, 200), (255, 190, 110), golden))
        else:
            phase = round(moon(now) * PHASES) / PHASES
            d.ellipse((bx - 4, by - 4, bx + 4, by + 4), fill=(236, 236, 214))
            if 0.03 < phase < 0.97:
                d.ellipse((bx - 4 + shadow(phase), by - 5, bx + 4 + shadow(phase), by + 5), fill=img.getpixel((int(bx), int(by) - 8)))
            else:
                d.ellipse((bx - 4, by - 4, bx + 4, by + 4), fill=img.getpixel((int(bx), int(by) - 8)))

    # clouds drift with the wind, behind the towers
    for c, (span, x0, speed, y) in zip(L["clouds"], P["clouds"]):
        img.paste(c, (int(x0 + t * speed) % span - c.width, y), c)
    if cover >= 0.85:   # overcast: a ceiling of cloud across the top
        ceil = shade(mix((200, 204, 212), (90, 94, 106), dark), 0.35 + 0.65 * light)
        speed, heights = P["ceiling"]; shift = int(t * speed)
        for x in range(300):
            d.line((x, 0, x, heights[(x + shift) % 300 // 6]), fill=ceil)

    img.paste(L["city"], (0, 0), L["city"])

    # the water: the mirrored rows rippling (more the closer they are), glints drifting downstream, rain splashes,
    # all pasted through the shape of the channel and the main river
    water = L["water"]
    wh = 128 - WATER_TOP
    wimg = Image.new("RGB", (300, wh), water); wd = ImageDraw.Draw(wimg)
    for i, row in enumerate(L["refl"]):
        wimg.paste(row, (round(math.sin(t * P["ripple"] + i * 0.9) * (0.4 + i / 14)), i))
    glint = (255, 214, 140) if night else shade(water, 1.5)
    for y, x0, speed, n in P["glints"]:
        x = int(x0 + t * speed) % 300
        wd.line((x, y, x + n, y), fill=glint)
    if precip in ("rain", "storm"):
        for i in range(amount // 5):
            if rand(72, i, frame) < 0.5:
                wd.point((int(rand(73, i, frame) * 300), int(rand(74, i, frame) * wh)), fill=(210, 226, 244))
    img.paste(wimg, (0, WATER_TOP), L["mask"])

    img.paste(L["fore"], (0, 0), L["fore"])
    p = ImageDraw.Draw(img)   # opaque drawing for the particles: Pillow's alpha blending is slow on the Pi Zero

    # rain in slanted streaks, snow drifting, both in front of everything
    if precip in ("rain", "storm"):
        vx, vy, drops = P["rain"]
        for x0, y0 in drops:
            x, y = (x0 + t * vx) % 340 - 20, (y0 + t * vy) % 140 - 8
            p.line((x, y, x - wind, y + 4), fill=(160, 186, 220))
    elif precip == "snow":
        vx, sway, flakes = P["snow"]
        for i, (x0, y0, vy, s) in enumerate(flakes):
            x = (x0 + t * vx + 3 * math.sin(t * sway + i)) % 320 - 10
            y = (y0 + t * vy) % 136 - 6
            p.rectangle((x, y, x + s - 1, y + s - 1), fill=(244, 246, 252))
    if precip == "storm" and frame % STRIKE in (0, 1, 3):   # lightning four times a loop, whole ones, so it repeats exactly: a flash, and a bolt onto One Liberty
        img = Image.blend(img, Image.new("RGB", ART, (230, 232, 255)), 0.35 if frame % STRIKE == 0 else 0.12)
        d = ImageDraw.Draw(img, "RGBA")
        sx, sy = 168, 22   # One Liberty's spire
        x, y, pts = sx + int(rand(80, frame // STRIKE) * 30) - 15, 0, []
        while y < sy - 4:
            pts.append((x, y)); y += 2 + int(rand(81, y, frame // STRIKE) * 3); x += int(rand(82, y, frame // STRIKE) * 7) - 3
        pts.append((sx, sy))
        d.line(pts, fill=(255, 255, 240), width=1)
    if fog:   # bands of mist drifting along the river
        mist = shade((210, 214, 220), 0.4 + 0.6 * light)
        for i, (speed, wisps) in enumerate(P["mist"]):   # ragged bands, thicker and slower lower down
            y0, drift = 46 + i * 9, t * speed
            for x in range(0, 300, 2):
                dy, h = wisps[int((x + drift) % 300 // 6)]
                d.rectangle((x, y0 + dy, x + 1, y0 + dy + h), fill=mist + (50 + i * 14,))
    return img
