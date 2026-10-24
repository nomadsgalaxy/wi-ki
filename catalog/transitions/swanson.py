"""Swanson: oak planks fall into place over the old page, one after another from the top. Once they're all seated, Ron
Swanson slides up from below on the right, in Nula's pixel art, looking left with his mallet, and one of his quotes
appears beside him on a paper card pinned to the oak, line by line, signed. It holds there long enough to read, then
Ron sinks back down out of sight and the planks fall away below, the bottom one first, onto the new page. A fan
tribute to Nick Offerman's Ron Swanson in Parks and Recreation; nothing official.

The quote comes from the Ron Swanson Quotes API (no key). A transition can't wait on the internet, so it shows a quote
fetched earlier and kept in ~/.cache/kiosk/swanson.json, and fetches the next one in the background as it plays, at
most every few minutes, five at a time. It shows the newest one short enough to read in the hold, chosen and laid out
before it starts and kept for the whole play. Until the first one arrives it says so on the wood. The planks with the
quote on them are drawn in that background thread too, so playing it is mostly whole-row copies.

The art is in pieces, so any of it can be drawn properly and dropped in: kiosk/art/swanson.png is Ron (transparent
round him, looking left, shoulders on his picture's bottom edge) and swanson-blink.png the same with his eyes shut, and
kiosk/art/swanson-wood.png the oak, the whole screen of it. Without them, they're drawn here in code. The quote is
always drawn live, never part of the art.
"""
import json, os, random, re, threading, time, urllib.request
from PIL import Image, ImageChops, ImageDraw

import kit
from .canvas import WIDTH, HEIGHT, sprite

SECONDS = 5
STILL = 2.8                                  # seconds it holds still, to be read
PLANKS = 5
PLANK = -(-HEIGHT // PLANKS)                 # 103 rows
DROP, FALL = 0.016, 0.072                    # a plank starts falling this long after the one above, and takes this long
IN, UP, BURNT_IN, OUT = 0.136, 0.22, 0.27, 0.84  # the planks are in, Ron is up, the quote is in, he starts to go
GONE = 0.90                                  # he's gone, and the planks start falling away, the bottom one first
QUOTE = (80, 70, 1340, 430)                  # where the quote and its signature go: left of Ron, clear of him
API = "https://ron-swanson-quotes.herokuapp.com/v2/quotes/5"   # five at a time, so there are short ones to choose from
SHORT = 110                                  # characters: a quote this long can be read in the hold
UA = {"User-Agent": "wi-ki swanson (github.com/nomadsgalaxy/wi-ki)"}
CACHE = os.path.expanduser("~/.cache/kiosk/swanson.json")
KEEP, EVERY = 30, 300                        # quotes kept for when it's offline, and seconds between fetches
WOOD = ((150, 96, 52), (139, 88, 47), (160, 104, 58), (146, 92, 50), (133, 84, 44))   # a plank each
GRAIN, BURNT, CHAR = (112, 70, 36), (52, 28, 12), (196, 140, 88)
PAPER, INKED, SHADOW = (240, 230, 206), (36, 22, 12), (70, 40, 18)   # the card the quote's on, its ink, its shadow
STEEL = (200, 206, 214)
SKIN, SHADE, HAIR, HAIR_LIT, STACHE, STACHE_DARK, INK, LIP = (226, 172, 132), (194, 138, 104), (74, 46, 28), (104, 68, 40), (92, 58, 34), (64, 38, 22), (34, 22, 16), (150, 90, 74)
RED, DARK, LIGHT = (168, 36, 36), (52, 18, 18), (206, 84, 70)
RON, EDGE = 8, 40                            # about 480 tall, 40 px in from the right: Nula's art sits at (1400, 35)
ART = os.path.join(kit.HERE, "art", "swanson.png")   # a drawn Ron, if there is one (and swanson-blink.png, his eyes shut)
OAK = os.path.join(kit.HERE, "art", "swanson-wood.png")   # drawn oak for the whole screen, if there is one


def ron(blink=False):
    """Ron, chest up, as 48x60 pixel art drawn here in code (scaled up RON times): the side-parted hair, the heavy brows,
    the mustache, the red plaid flannel. With blink, his eyes are shut"""
    img = Image.new("RGBA", (48, 60)); d = ImageDraw.Draw(img)
    # shirt: red plaid flannel across broad shoulders, open at the collar
    shoulders = [(0, 59), (1, 52), (6, 47), (14, 44), (20, 43), (28, 43), (34, 44), (42, 47), (47, 52), (47, 59)]
    plaid = Image.new("RGBA", img.size, RED); p = ImageDraw.Draw(plaid)
    for x in range(1, 48, 7):
        p.line((x, 0, x, 59), fill=DARK, width=2); p.line((x + 4, 0, x + 4, 59), fill=LIGHT)
    for y in (46, 53):
        p.line((0, y, 47, y), fill=DARK, width=2)
    p.line((0, 50, 47, 50), fill=LIGHT)
    mask = Image.new("L", img.size); ImageDraw.Draw(mask).polygon(shoulders, fill=255)
    img.paste(plaid, (0, 0), mask); d = ImageDraw.Draw(img)
    d.rectangle((19, 38, 29, 46), fill=SHADE)                         # neck
    d.polygon([(19, 43), (24, 51), (29, 43), (29, 46), (24, 53), (19, 46)], fill=SHADE)   # the open collar
    d.line((19, 43, 24, 51), fill=DARK); d.line((29, 43, 24, 51), fill=DARK)
    d.ellipse((9, 20, 14, 30), fill=SHADE); d.ellipse((34, 20, 39, 30), fill=SHADE)        # ears
    d.ellipse((12, 7, 36, 43), fill=SKIN)                             # face
    d.chord((24, 7, 36, 43), -70, 70, fill=SHADE)                     # the shadowed side
    d.ellipse((14, 9, 34, 42), fill=SKIN)
    d.polygon([(12, 22), (11, 13), (15, 7), (22, 4), (30, 4), (35, 8), (37, 14), (37, 22), (35, 15), (31, 11),
               (19, 12), (15, 15), (14, 22)], fill=HAIR)              # hair, short, parted on his right
    d.line((19, 6, 17, 11), fill=HAIR_LIT); d.line((22, 5, 31, 6), fill=HAIR_LIT)
    d.line((16, 19, 22, 18), fill=HAIR, width=2); d.line((26, 18, 32, 19), fill=HAIR, width=2)   # brows, heavy
    if blink:
        d.line((17, 22, 21, 22), fill=INK); d.line((27, 22, 31, 22), fill=INK)
    else:
        d.rectangle((18, 21, 20, 22), fill=INK); d.rectangle((28, 21, 30, 22), fill=INK)
        d.point((19, 21), fill=(240, 236, 228)); d.point((29, 21), fill=(240, 236, 228))
    d.line((24, 22, 24, 28), fill=SHADE); d.line((22, 29, 26, 29), fill=SHADE)   # nose
    d.polygon([(16, 31), (21, 30), (24, 31), (27, 30), (32, 31), (34, 35), (31, 36), (27, 34), (24, 35),
               (21, 34), (17, 36), (14, 35)], fill=STACHE)            # the mustache
    d.line((17, 33, 31, 33), fill=STACHE_DARK)
    d.line((20, 37, 28, 37), fill=LIP)                                # mouth, unimpressed
    d.line((21, 40, 27, 40), fill=SHADE)                              # chin
    return img


def quotes():
    """the quotes kept on disk: a list of strings, or [] (none yet, or a file that isn't one)"""
    try:
        with open(CACHE) as f:
            kept = json.load(f)
        return [q for q in kept if isinstance(q, str) and q.strip()] if isinstance(kept, list) else []
    except (OSError, ValueError):
        return []


def tidy(quote):
    """a quote as it'll be burnt: one line of plain text, at most 240 characters"""
    quote = re.sub(r"\s+", " ", "".join(ch for ch in str(quote) if ch.isprintable() or ch.isspace())).strip()
    return quote if len(quote) <= 240 else quote[:237].rsplit(" ", 1)[0] + "..."


def wrap(words, width):
    """words in lines of at most width characters; a word longer than that is broken across lines"""
    lines = [""]
    for word in (w[i:i + width] for w in words.split() for i in range(0, len(w), width)):
        if lines[-1] and len(lines[-1]) + 1 + len(word) > width:
            lines.append("")
        lines[-1] = (lines[-1] + " " + word).strip()
    return lines


def portrait():
    """Ron, open-eyed and blinking, at the size he's drawn -> (open, shut), RGBA. A drawn Ron in kiosk/art/swanson.png
    takes the place of the one in code: scaled up by whole pixels to about 480 tall, and swanson-blink.png beside it is
    him blinking (without it, he doesn't)"""
    if os.path.exists(ART):
        art = Image.open(ART).convert("RGBA")
        k = max(1, (60 * RON) // art.height)
        size = (art.width * k, art.height * k)
        blink = ART.replace(".png", "-blink.png")
        shut = Image.open(blink).convert("RGBA") if os.path.exists(blink) else art
        return art.resize(size, Image.NEAREST), shut.resize(size, Image.NEAREST)
    return tuple(ron(blink).resize((48 * RON, 60 * RON), Image.NEAREST).transpose(Image.FLIP_LEFT_RIGHT) for blink in (False, True))


def blinking(open_, shut):
    """the blink: only the part of him that changes when his eyes shut -> (a sprite of it, where it goes in him), or
    (None, None) if nothing does"""
    box = ImageChops.difference(open_, shut).convert("RGB").getbbox()   # the colours: an RGBA bbox only looks at alpha
    return (sprite(shut.crop(box)), box[:2]) if box else (None, None)


def pick(kept):
    """the quote to show: the newest one short enough to read in the hold, or else the shortest there is"""
    return next((q for q in kept if len(q) <= SHORT), min(kept, key=len) if kept else None)


def wood():
    """the oak, the whole screen of it, RGB: drawn art if there is some, or planks drawn here"""
    if os.path.exists(OAK):
        art = Image.open(OAK).convert("RGB")
        return art if art.size == (WIDTH, HEIGHT) else art.resize((WIDTH, HEIGHT))
    rng = random.Random(5)
    img = Image.new("RGB", (WIDTH, HEIGHT)); d = ImageDraw.Draw(img)
    for p in range(PLANKS):
        top = p * PLANK
        d.rectangle((0, top, WIDTH, top + PLANK - 1), fill=WOOD[p % len(WOOD)])
        for _ in range(14):                  # the grain: long thin streaks along the plank
            y, x = top + rng.randrange(6, PLANK - 6), rng.randrange(-400, WIDTH)
            d.line((x, y, x + rng.randrange(300, 900), y + rng.choice((-1, 0, 0, 1))), fill=GRAIN)
        for _ in range(rng.randrange(0, 2)):  # and a knot, now and then
            x, y = rng.randrange(80, WIDTH - 80), top + PLANK // 2
            d.ellipse((x - 18, y - 9, x + 18, y + 9), outline=GRAIN, width=3)
        d.rectangle((0, top + PLANK - 3, WIDTH, top + PLANK - 1), fill=BURNT)   # the seam
        for x in (40, WIDTH - 52):           # nails
            d.rectangle((x, top + PLANK // 2 - 6, x + 11, top + PLANK // 2 + 5), fill=STEEL)
    return img


def scene(quote):
    """the whole of it, laid out before it plays -> {"wood": the oak alone, "quoted": the oak with the quote on its card,
    "full": that and Ron, all packed bytes; "bands": the card in bands from the top, a line of the quote in each and
    the signature in the last, as (x, y, w, h)}"""
    img = wood()
    plain = kit.rgb565(img)
    left, top, right, bottom = QUOTE[0], QUOTE[1], min(QUOTE[2], RON_AT - 60), QUOTE[3]
    pad = 36                                 # the card's margin round the words
    words = tidy(quote) if quote else "NO QUOTE YET. IT'LL BE HERE ONCE THE KIOSK'S BEEN ONLINE."
    for scale in (4, 3, 2):                  # as big as it fits, with room under it for the signature
        lines = wrap(words, (right - left - 2 * pad) // (8 * scale))
        if len(lines) * 20 * scale <= bottom - top - 2 * pad - 44:
            break
    tall = len(lines) * 20 * scale + 44      # the words and the signature under them
    wide = max(len(line) for line in lines) * 8 * scale
    card = ((left + right - wide) // 2 - pad, top + (bottom - top - tall) // 2 - pad)
    card += (card[0] + wide + 2 * pad, card[1] + tall + 2 * pad)
    d = ImageDraw.Draw(img)
    d.rectangle((card[0] + 8, card[1] + 8, card[2] + 8, card[3] + 8), fill=SHADOW)   # its shadow on the oak
    d.rectangle(card, fill=PAPER, outline=BURNT, width=4)
    for x in (card[0] + 16, card[2] - 26):   # pinned up
        d.rectangle((x, card[1] + 12, x + 9, card[1] + 21), fill=STEEL, outline=GRAIN)
    y, bands, last = card[1] + pad, [], card[1]
    for line in lines:
        kit.text(img, ((left + right - len(line) * 8 * scale) // 2, y), line, INKED, scale=scale)
        y += 20 * scale
        bands.append((card[0], last, card[2] - card[0] + 9, y - last)); last = y
    kit.text(img, (card[2] - pad, y + 8), "- RON SWANSON", BURNT, scale=2, right=True)
    bands.append((card[0], last, card[2] - card[0] + 9, card[3] + 9 - last))
    quoted = kit.rgb565(img)
    him = PORTRAIT[0]
    img.paste(him, (RON_AT, HEIGHT - him.height), him)
    return {"wood": plain, "quoted": quoted, "full": kit.rgb565(img), "bands": bands}


PORTRAIT = portrait()
RON_AT = WIDTH - EDGE - PORTRAIT[0].width   # his left edge, on the right of the screen
RISING = sprite(PORTRAIT[0])
SHUT, SHUT_AT = blinking(*PORTRAIT)
ready = {"quote": None, "scene": None}       # the next scene, laid out ahead in the background
_busy = threading.Lock()


def refresh():
    """fetch a new quote if it's time, keep it, and draw the next planks: in a thread, so playing never waits"""
    if not _busy.acquire(blocking=False):
        return
    try:
        kept = quotes()
        try:
            stale = time.time() - os.path.getmtime(CACHE) > EVERY
        except OSError:
            stale = True
        if stale:
            try:
                with urllib.request.urlopen(urllib.request.Request(API, headers=UA), timeout=10) as r:
                    got = json.load(r)
                new = [tidy(q) for q in got if isinstance(q, str) and q.strip()] if isinstance(got, list) else []
                if new:
                    kept = (new + [q for q in kept if q not in new])[:KEEP]
                    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
                    with open(CACHE + ".tmp", "w") as f:
                        json.dump(kept, f)
                    os.replace(CACHE + ".tmp", CACHE)
            except Exception:
                pass                         # offline, or the API's away: the kept ones do
        quote = pick(kept)
        ready["quote"], ready["scene"] = quote, scene(quote)
    finally:
        _busy.release()


def frames(c, count):
    shown = ready["scene"] or scene(ready["quote"] or pick(quotes()))   # chosen now, and kept for the whole play
    ready["scene"] = None                    # this one's used: lay out the next while this plays
    threading.Thread(target=refresh, daemon=True).start()
    down, burnt, up, loose = 0, 0, False, set()
    him = PORTRAIT[0]
    for k in range(count):
        t = k / max(1, count - 1)            # a lone frame is the first; play() lands on the new page
        for p in range(down, PLANKS):        # the oak falls in, plank by plank from the top, each from above the screen
            k_ = (t - p * DROP) / FALL
            if k_ >= 1:
                c.reveal(0, p * PLANK, WIDTH, PLANK, src=shown["wood"]); down = p + 1   # seated, for good
            elif k_ > 0:                     # still falling, slowing as it lands: whole rows, so one copy
                y = round(-PLANK - 16 + (p * PLANK + PLANK + 16) * (1 - (1 - k_) ** 2))
                c.rows(y, shown["wood"][p * PLANK * WIDTH * 2:(p + 1) * PLANK * WIDTH * 2])
        if IN <= t < UP:                     # Ron slides up from below on the right, slowing as he arrives
            k_ = (t - IN) / (UP - IN)
            c.draw(RISING, RON_AT, HEIGHT - round(him.height * (1 - (1 - k_) ** 2)))
        elif UP <= t < OUT and not up:       # and he's there, part of the wood now (once: he leaves at OUT)
            c.reveal(RON_AT, HEIGHT - him.height, him.width, him.height, src=shown["full"]); up = True
        bands = shown["bands"]
        while UP <= t and burnt < len(bands) and t >= UP + (BURNT_IN - UP) * (burnt + 1) / len(bands):
            c.reveal(*bands[burnt], src=shown["full"]); burnt += 1   # the card unrolls, a line of the quote at a time
        if SHUT and BURNT_IN <= t < OUT and (t - BURNT_IN) % 0.25 < 0.025:   # a blink now and then, while it's read
            c.draw(SHUT, RON_AT + SHUT_AT[0], HEIGHT - him.height + SHUT_AT[1])
        if OUT <= t < GONE:                  # he sinks back down out of sight, faster as he goes
            if up:
                c.reveal(RON_AT, HEIGHT - him.height, him.width, him.height, src=shown["quoted"]); up = False
            c.draw(RISING, RON_AT, HEIGHT - him.height + round(him.height * ((t - OUT) / (GONE - OUT)) ** 2))
        elif t >= GONE:                      # then the planks fall away below, bottom first, faster as they go
            if up:                           # (a short run where he never sank)
                c.reveal(RON_AT, HEIGHT - him.height, him.width, him.height, src=shown["quoted"]); up = False
            for p in reversed(range(PLANKS)):
                start = GONE + (PLANKS - 1 - p) * 0.012
                if t < start:
                    continue
                if p not in loose:           # off its nails: the new page is behind it from now on
                    c.reveal(0, p * PLANK, WIDTH, PLANK); loose.add(p)
                fall = (HEIGHT - p * PLANK) * ((t - start) / max(1e-6, 1 - start)) ** 2
                c.rows(p * PLANK + round(fall), shown["quoted"][p * PLANK * WIDTH * 2:(p + 1) * PLANK * WIDTH * 2])
        yield


def check():
    """quotes are tidied and fit the planks however long or odd they are, and a missing or broken cache is no quotes"""
    assert tidy("a\n\tb  c\x07") == "a b c" and len(tidy("word " * 100)) <= 240 and tidy("x" * 300).endswith("...")
    global CACHE
    real, CACHE = CACHE, os.path.join(os.path.dirname(CACHE), "swanson-check-missing.json")
    try:
        assert quotes() == [], "no cache, no quotes"
    finally:
        CACHE = real
    assert pick(["x" * 200, "short one", "another"]) == "short one" and pick(["x" * 300, "y" * 200]) == "y" * 200 and pick([]) is None
    # a drawn Ron takes the place of the one in code, and only what changes in his blink is drawn for it
    import tempfile
    global ART
    real_art = ART
    with tempfile.TemporaryDirectory() as folder:
        ART = os.path.join(folder, "swanson.png")
        art = Image.new("RGBA", (60, 80), (200, 150, 120, 255)); art.save(ART)
        shut = art.copy(); ImageDraw.Draw(shut).rectangle((20, 30, 39, 33), fill=(0, 0, 0, 255)); shut.save(ART.replace(".png", "-blink.png"))
        open_, closed = portrait()
        spr, at = blinking(open_, closed)
        assert open_.size == (360, 480) and at == (120, 180) and (spr["w"], spr["h"]) == (120, 24), (open_.size, at)
    ART = real_art
    assert blinking(PORTRAIT[0], PORTRAIT[0]) == (None, None), "no blink picture, no blink"
    for quote in (None, "x" * 240, "Ωμέγα " * 40, "short"):   # nothing yet, the longest, other scripts, a few words
        laid = scene(quote)
        assert len(laid["full"]) == len(laid["wood"]) == WIDTH * HEIGHT * 2
        assert all(QUOTE[0] <= x and x + w <= min(QUOTE[2] + 9, RON_AT) and QUOTE[1] <= y and y + h <= QUOTE[3] + 9
                   for x, y, w, h in laid["bands"]), "the card, shadow and all, stays in its place, left of him"
        assert len(laid["quoted"]) == WIDTH * HEIGHT * 2
