"""xkcd panel: a small xkcd comic between pages, in xkcd's own look. A sheet of white paper slides down over the old
page, with the comic's number, title and alt text hand-lettered on the left (the xkcd Script font, in kiosk/fonts);
the comic prints in on the right, top to bottom, black ink on white in a wobbly hand-drawn panel; it holds long
enough to read, and the sheet slides up and away, off the new page.

Only small comics, ones you can read in a few seconds: at most 700 x 420 at xkcd's own size, so the bar shows them at
least that big, with alt text of 120 characters or less. Big ones are for the xkcd page. A transition can't wait on the internet, so a
background thread finds them ahead of time, as it plays: a few random comics an hour from xkcd's JSON (no key), the
pictures from imgs.xkcd.com, kept in ~/.cache/kiosk/xkcd-panel/ (the last 20). It shows one it hasn't shown lately,
laid out before it starts and kept for the whole play. Until it has one, it says so. xkcd is Randall Munroe's,
CC BY-NC 2.5, credited on screen.
"""
import io, json, os, random, threading, time, urllib.error, urllib.request
from PIL import Image, ImageDraw, ImageFont

import kit
from .canvas import WIDTH, HEIGHT, STRIDE

SECONDS = 5
IN, PRINTED, OUT = 0.10, 0.24, 0.88           # the sheet's down, the comic's printed, the sheet starts going up
STILL = (OUT - PRINTED) * SECONDS             # seconds it holds still, to be read
API = "https://xkcd.com/{}info.0.json"
PICTURES = "https://imgs.xkcd.com/comics/"
UA = {"User-Agent": "wi-ki xkcd_panel (github.com/nomadsgalaxy/wi-ki)"}
FOLDER = os.path.expanduser("~/.cache/kiosk/xkcd-panel")
KEPT = os.path.join(FOLDER, "kept.json")
KEEP, EVERY, TRIES = 20, 3600, 6              # comics kept, seconds between looking for more, comics looked at (about 2 in 5 are small)
WIDE, TALL = 700, 420                    # the biggest a small comic is at xkcd's own size, so it shows at least that big
ALT = 120                                     # the longest alt text
BIGGEST = 4 << 20
COMIC = (700, 24, WIDTH - 24, HEIGHT - 24)    # where the comic goes
PAPER, INK, PENCIL, EDGE = (255, 255, 255), (0, 0, 0), (110, 110, 110), (40, 40, 40)
FONT = os.path.join(os.path.dirname(os.path.realpath(kit.__file__)), "fonts", "xkcd-script-subset.ttf")
LEFT, TEXT_W = 40, 620                        # the words' column


def get(url, limit=1 << 20):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:
        body = r.read(limit + 1)
    if len(body) > limit:
        raise ValueError(f"{url} is bigger than {limit} bytes")
    return body


def small(comic, img):
    """whether a comic is one to read in a few seconds"""
    alt = comic.get("alt")
    return img.width <= WIDE and img.height <= TALL and isinstance(alt, str) and len(alt) <= ALT


def look():
    """a random comic, if it's a small one -> its entry for kept.json, its picture saved; or None"""
    latest = json.loads(get(API.format("")))["num"]
    comic = json.loads(get(API.format(f"{random.randint(1, latest)}/")))
    url = str(comic.get("img", ""))
    if not url.startswith(PICTURES) or not url.lower().endswith((".png", ".jpg", ".jpeg", ".gif")):
        return None
    img = Image.open(io.BytesIO(get(url, BIGGEST))); img.load()
    if not small(comic, img):
        return None
    stem, _, ext = url.rpartition(".")
    try:   # the double-size picture, where there is one, for a sharper print
        big = Image.open(io.BytesIO(get(f"{stem}_2x.{ext}", BIGGEST))); big.load(); img = big
    except (urllib.error.HTTPError, OSError, ValueError):
        pass
    file = os.path.join(FOLDER, f"{int(comic['num'])}.png")
    img.convert("RGBA" if "A" in img.getbands() else "RGB").save(file + ".tmp.png"); os.replace(file + ".tmp.png", file)
    return {"num": int(comic["num"]), "title": " ".join(str(comic.get("safe_title") or comic.get("title") or "").split())[:40],
            "alt": " ".join(comic["alt"].split()), "file": file, "shown": 0}


def kept():
    """the comics kept on disk: a list of entries, or [] (none yet, or a file that isn't one). A file outside our
    folder is never read"""
    try:
        with open(KEPT) as f:
            got = json.load(f)
    except (OSError, ValueError):
        return []
    return [c for c in got if isinstance(c, dict) and isinstance(c.get("num"), int) and isinstance(c.get("file"), str)
            and os.path.dirname(os.path.realpath(c["file"])) == os.path.realpath(FOLDER) and os.path.exists(c["file"])] \
        if isinstance(got, list) else []


def save(comics):
    os.makedirs(FOLDER, exist_ok=True)
    with open(KEPT + ".tmp", "w") as f:
        json.dump(comics, f)
    os.replace(KEPT + ".tmp", KEPT)


def hand(size):
    return ImageFont.truetype(FONT, size)


def wrap(words, font, width):
    """words in lines no wider than width pixels in font; a word wider than a line is split"""
    lines, line = [], ""
    for word in words.split():
        while font.getlength(word) > width:   # too wide for any line: as much as fits, on a line of its own
            cut = 1
            while cut < len(word) and font.getlength(word[:cut + 1]) <= width:
                cut += 1
            if line:
                lines.append(line); line = ""
            lines.append(word[:cut]); word = word[cut:]
        if line and font.getlength(line + " " + word) > width:
            lines.append(line); line = word
        else:
            line = (line + " " + word).strip()
    return lines + [line] if line else lines


def wobble(d, points, seed, width=3):
    """a hand-drawn line through points: every short stretch nudged a pixel or two off true, the same each time"""
    rnd = random.Random(seed)
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        n = max(1, round(max(abs(x1 - x0), abs(y1 - y0)) / 40))
        way = [(x0 + (x1 - x0) * i / n + (rnd.uniform(-1.6, 1.6) if 0 < i < n else 0),
                y0 + (y1 - y0) * i / n + (rnd.uniform(-1.6, 1.6) if 0 < i < n else 0)) for i in range(n + 1)]
        d.line(way, fill=INK, width=width, joint="curve")


def scene(comic):
    """the comic laid out on its sheet, before it plays -> {"words": the sheet with the number, title and alt text,
    "full": that and the comic, packed bytes; "box": where the comic and its panel are (x, y, w, h)}"""
    img = Image.new("RGB", (WIDTH, HEIGHT), PAPER); d = ImageDraw.Draw(img)
    if not comic:
        d.text((LEFT, 40), "xkcd", font=hand(40), fill=PENCIL)
        d.text((LEFT, 100), "A comic will be here once the kiosk's been online.", font=hand(44), fill=INK)
        plain = kit.rgb565(img)
        return {"words": plain, "full": plain, "box": None}
    d.text((LEFT, 22), f"xkcd #{comic['num']}", font=hand(30), fill=PENCIL)
    size = 64
    while size > 30 and hand(size).getlength(comic["title"]) > TEXT_W:
        size -= 4
    title = hand(size)
    d.text((LEFT, 58), comic["title"] if title.getlength(comic["title"]) <= TEXT_W else wrap(comic["title"], title, TEXT_W)[0],
           font=title, fill=INK)
    rule = 58 + size + 22
    wobble(d, [(LEFT, rule), (LEFT + TEXT_W, rule)], comic["num"])
    words = hand(32)
    for i, line in enumerate(wrap(comic["alt"], words, TEXT_W)[:(HEIGHT - 60 - rule) // 38]):
        d.text((LEFT, rule + 14 + i * 38), line, font=words, fill=INK)
    d.text((LEFT, HEIGHT - 38), "xkcd.com · Randall Munroe · CC BY-NC 2.5", font=hand(22), fill=PENCIL)
    sheet = kit.rgb565(img)
    pic = Image.open(comic["file"]).convert("RGB")
    w, h = COMIC[2] - COMIC[0] - 24, COMIC[3] - COMIC[1] - 24   # inside its panel
    k = min(w / pic.width, h / pic.height)
    pic = pic.resize((pic.width * int(k), pic.height * int(k)), Image.NEAREST) if k >= 2 else \
        pic.resize((max(1, round(pic.width * k)), max(1, round(pic.height * k))), Image.LANCZOS)
    x, y = COMIC[0] + 12 + (w - pic.width) // 2, COMIC[1] + 12 + (h - pic.height) // 2
    img.paste(pic, (x, y))
    x0, y0, x1, y1 = x - 12, y - 12, x + pic.width + 11, y + pic.height + 11   # the panel, as xkcd draws one
    wobble(d, [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)], comic["num"] + 1)
    return {"words": sheet, "full": kit.rgb565(img), "box": (x0 - 2, y0 - 2, x1 - x0 + 5, y1 - y0 + 5)}


def pick(comics):
    """the comic to show: the one shown least, newest first among those"""
    return min(comics, key=lambda c: c.get("shown", 0)) if comics else None


ready = {"scene": None}
_busy = threading.Lock()


def refresh():
    """look for more small comics if it's time, and lay out the next one: in a thread, so playing never waits"""
    if not _busy.acquire(blocking=False):
        return
    try:
        comics = kept()
        try:
            stale = time.time() - os.path.getmtime(KEPT) > EVERY
        except OSError:
            stale = True
        if stale or len(comics) < 3:
            os.makedirs(FOLDER, exist_ok=True)
            for _ in range(TRIES):
                try:
                    found = look()
                except Exception:
                    break   # offline, or xkcd's away: the kept ones do
                if found and all(c["num"] != found["num"] for c in comics):
                    comics.insert(0, found)
            for old in comics[KEEP:]:   # only the last few
                try:
                    os.remove(old["file"])
                except OSError:
                    pass
            comics = comics[:KEEP]
            save(comics)
        comic = pick(comics)
        if comic:
            comic["shown"] = comic.get("shown", 0) + 1; save(comics)
        ready["scene"] = scene(comic)
    finally:
        _busy.release()


def ease(t):
    t = min(1.0, max(0.0, t))
    return t * t * (3 - 2 * t)


def frames(c, count):
    shown = ready["scene"] or scene(pick(kept()))   # chosen now, and kept for the whole play
    ready["scene"] = None                            # this one's used: lay out the next while this plays
    threading.Thread(target=refresh, daemon=True).start()
    down = printed = 0
    gone = False
    box = shown["box"]
    for k in range(count):
        t = k / max(1, count - 1)                    # a lone frame is the first; play() lands on the new page
        if t < IN:                                   # in: the sheet slides down over the old page, its edge dark
            at = round(ease(t / IN) * HEIGHT)
            c.rows(at - HEIGHT, shown["words"]); c.fill(0, at, WIDTH, 3, EDGE)
        elif not down:                               # down: the sheet's the page now, for good
            c.reveal(0, 0, WIDTH, HEIGHT, src=shown["words"]); down = 1
        if box and IN <= t < OUT:                    # the comic prints in, top to bottom, panel and all
            done = min(box[3], round((t - IN) / (PRINTED - IN) * box[3]))
            if done > printed:
                c.reveal(box[0], box[1] + printed, box[2], done - printed, src=shown["full"]); printed = done
        if t >= OUT:                                 # out: the new page under it, and the sheet slides up and away
            if not gone:
                c.reveal(0, 0, WIDTH, HEIGHT); gone = True
            at = round(ease((t - OUT) / (1 - OUT)) * HEIGHT)
            if at < HEIGHT:
                c.rows(-at, shown["full"]); c.fill(0, HEIGHT - at, WIDTH, 3, EDGE)
        yield


def check():
    """only small comics are kept, only our own files are read, and any comic (or none) lays out on the screen"""
    assert small({"alt": "short"}, Image.new("RGB", (400, 300))) and not small({"alt": "x" * 200}, Image.new("RGB", (400, 300)))
    assert not small({"alt": "short"}, Image.new("RGB", (740, 300))) and not small({"alt": None}, Image.new("RGB", (40, 30)))
    assert not small({"alt": "short"}, Image.new("RGB", (280, 560))), "a tall one shows too small to read on the bar"
    assert pick([]) is None and pick([{"num": 1, "shown": 3}, {"num": 2, "shown": 1}])["num"] == 2
    import tempfile
    global FOLDER, KEPT
    real = FOLDER, KEPT
    with tempfile.TemporaryDirectory() as folder:
        FOLDER, KEPT = folder, os.path.join(folder, "kept.json")
        try:
            assert kept() == [], "nothing yet"
            line_art = Image.new("RGB", (300, 200), (255, 255, 255)); line_art.paste((0, 0, 0), (20, 20, 280, 24))
            line_art.save(os.path.join(folder, "1.png"))
            save([{"num": 1, "title": "One", "alt": "a", "file": os.path.join(folder, "1.png")},
                  {"num": 2, "title": "Elsewhere", "alt": "b", "file": "/etc/hostname"}])
            assert [c["num"] for c in kept()] == [1], "a file outside the folder is never read"
            laid = scene(kept()[0])
            x, y, w, h = laid["box"]
            assert COMIC[0] <= x and x + w <= COMIC[2] and COMIC[1] <= y and y + h <= COMIC[3], laid["box"]
            assert len(laid["full"]) == len(laid["words"]) == WIDTH * HEIGHT * 2
            assert scene(None)["box"] is None, "with no comic yet, it says so"
            colour = Image.new("RGB", (500, 500), (200, 40, 40)); colour.save(os.path.join(folder, "3.png"))
            x, y, w, h = scene({"num": 3, "title": "Ω" * 50, "alt": "word " * 30, "file": os.path.join(folder, "3.png")})["box"]
            assert COMIC[0] - 2 <= x and x + w <= COMIC[2] + 3 and y >= 0 and y + h <= HEIGHT, "colour, in its panel"
            assert scene({"num": 4, "title": "A Title Far Too Long To Fit In The Column At Any Size At All", "alt": "x" * 119,
                          "file": os.path.join(folder, "1.png")})["box"], "long words and titles still lay out"
            f = hand(32)
            for text in ("Supercalifragilisticexpialidocious " * 3, "a b c", "", "w" * 200):
                assert all(f.getlength(l) <= TEXT_W for l in wrap(text, f, TEXT_W)), text[:20]
            assert wrap("one two", f, TEXT_W) == ["one two"] and ease(-1) == 0 and ease(2) == 1
        finally:
            FOLDER, KEPT = real
