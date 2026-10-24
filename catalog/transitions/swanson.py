"""Swanson: planks of wood drop in over the old page, one after another, with Ron Swanson on them in pixel art and one
of his quotes burnt into the wood beside him, signed. It holds there long enough to read while he blinks at you, then
a saw blade runs along each plank's seam and the planks come away, top to bottom, onto the new page. A fan tribute to
Nick Offerman's Ron Swanson in Parks and Recreation; nothing official.

The quote comes from the Ron Swanson Quotes API (no key). A transition can't wait on the internet, so it shows a quote
fetched earlier and kept in ~/.cache/kiosk/swanson.json, and fetches the next one in the background as it plays, at
most every few minutes, five at a time. It shows the newest one short enough to read in the hold, chosen and laid out
before it starts and kept for the whole play. Until the first one arrives it says so on the wood. The planks with the
quote on them are drawn in that background thread too, so playing it is all whole-row copies.

Ron is drawn in code, unless there's a drawn one in kiosk/art/swanson.png (and swanson-blink.png, his eyes shut): the
art is only him, never the wood or the quote, and only what differs between the two blinks.
"""
import json, os, random, re, threading, time, urllib.request
from PIL import Image, ImageChops, ImageDraw

import kit
from .canvas import WIDTH, HEIGHT, sprite

SECONDS = 5
STILL = 3.4                                  # seconds it holds still, to be read
PLANKS = 5
PLANK = -(-HEIGHT // PLANKS)                 # 103 rows
IN, OUT = 0.08, 0.76                         # the planks are all in by here, and start coming away here
API = "https://ron-swanson-quotes.herokuapp.com/v2/quotes/5"   # five at a time, so there are short ones to choose from
SHORT = 110                                  # characters: a quote this long can be read in the hold
UA = {"User-Agent": "wi-ki swanson (github.com/nomadsgalaxy/wi-ki)"}
CACHE = os.path.expanduser("~/.cache/kiosk/swanson.json")
KEEP, EVERY = 30, 300                        # quotes kept for when it's offline, and seconds between fetches
WOOD = ((150, 96, 52), (139, 88, 47), (160, 104, 58), (146, 92, 50), (133, 84, 44))   # a plank each
GRAIN, BURNT, CHAR = (112, 70, 36), (52, 28, 12), (196, 140, 88)
STEEL, TEETH = (200, 206, 214), (120, 126, 134)
SKIN, SHADE, HAIR, HAIR_LIT, STACHE, STACHE_DARK, INK, LIP = (226, 172, 132), (194, 138, 104), (74, 46, 28), (104, 68, 40), (92, 58, 34), (64, 38, 22), (34, 22, 16), (150, 90, 74)
RED, DARK, LIGHT = (168, 36, 36), (52, 18, 18), (206, 84, 70)
RON, RON_X = 8, 40                           # he's drawn 8 times his art's size, on the left, shoulders on the bottom
TEXT_X = RON_X + 48 * RON + 40               # the quote goes right of him
ART = os.path.join(kit.HERE, "art", "swanson.png")   # a drawn Ron, if there is one (and swanson-blink.png, his eyes shut)


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
    lines = [""]
    for word in words.split():
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
    return tuple(ron(blink).resize((48 * RON, 60 * RON), Image.NEAREST) for blink in (False, True))


def blinking(open_, shut):
    """the blink: only the part of him that changes when his eyes shut -> (a sprite of it, where it goes in him), or
    (None, None) if nothing does"""
    box = ImageChops.difference(open_, shut).convert("RGB").getbbox()   # the colours: an RGBA bbox only looks at alpha
    return (sprite(shut.crop(box)), box[:2]) if box else (None, None)


def pick(kept):
    """the quote to show: the newest one short enough to read in the hold, or else the shortest there is"""
    return next((q for q in kept if len(q) <= SHORT), min(kept, key=len) if kept else None)


def planks(quote):
    """the planks with quote burnt in, the whole screen of them -> packed bytes"""
    rng = random.Random(quote)
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
    him = PORTRAIT[0]
    img.paste(him, (RON_X, HEIGHT - him.height), him)
    words = tidy(quote) if quote else "NO QUOTE YET. IT'LL BE HERE ONCE THE KIOSK'S BEEN ONLINE."
    for scale in (4, 3, 2):                  # as big as it fits
        lines = wrap(words, (WIDTH - TEXT_X - 60) // (8 * scale))
        if len(lines) * 20 * scale <= HEIGHT - 150:
            break
    y = (HEIGHT - 60 - len(lines) * 20 * scale) // 2
    for line in lines:                       # burnt in: dark letters, a lighter scorch under them
        x = TEXT_X + (WIDTH - TEXT_X - 60 - len(line) * 8 * scale) // 2
        kit.text(img, (x + 2, y + 2), line, CHAR, scale=scale)
        kit.text(img, (x, y), line, BURNT, scale=scale)
        y += 20 * scale
    kit.text(img, (WIDTH - 120, HEIGHT - 70), "- RON SWANSON", BURNT, scale=2, right=True)
    return kit.rgb565(img)


def blade():
    """a circular saw blade, as a sprite: steel with teeth round it and a hole in the middle"""
    img = Image.new("RGBA", (40, 40)); d = ImageDraw.Draw(img)
    d.ellipse((2, 2, 37, 37), fill=TEETH + (255,)); d.ellipse((6, 6, 33, 33), fill=STEEL + (255,))
    d.ellipse((16, 16, 23, 23), fill=(0, 0, 0, 0))
    return sprite(img, 2)


BLADE = blade()
PORTRAIT = portrait()
SHUT, SHUT_AT = blinking(*PORTRAIT)
ready = {"quote": None, "bytes": None}       # the next planks, drawn ahead in the background
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
        ready["quote"], ready["bytes"] = quote, planks(quote)
    finally:
        _busy.release()


def frames(c, count):
    backdrop = ready["bytes"] or planks(ready["quote"] or pick(quotes()))   # chosen now, and kept for the whole play
    ready["bytes"] = None                    # this one's used: draw the next while this plays
    threading.Thread(target=refresh, daemon=True).start()
    down, gone = 0, 0
    for k in range(count):
        t = k / max(1, count - 1)            # a lone frame is the first; play() lands on the new page
        while down < PLANKS and t >= IN * (down + 1) / PLANKS:   # the planks drop in, top to bottom
            c.reveal(0, down * PLANK, WIDTH, PLANK, src=backdrop); down += 1
        if SHUT and IN <= t < OUT and (t - IN) % 0.25 < 0.025:   # a blink now and then, while it's being read
            c.draw(SHUT, RON_X + SHUT_AT[0], HEIGHT - PORTRAIT[0].height + SHUT_AT[1])
        if t >= OUT:                         # the saw runs along each seam, and that plank comes away
            span = (1 - OUT) / PLANKS
            while gone < PLANKS and t >= OUT + span * (gone + 1):
                c.reveal(0, gone * PLANK, WIDTH, PLANK); gone += 1
            if gone < PLANKS:
                along = (t - OUT - span * gone) / span
                c.draw(BLADE, round(-80 + along * (WIDTH + 80)), min(HEIGHT, (gone + 1) * PLANK) - 40)
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
        assert len(planks(quote)) == WIDTH * HEIGHT * 2
