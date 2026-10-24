"""xkcd panel: a small xkcd comic between pages. The old page goes dark from the top down, with the comic's number,
title and alt text on the left; the comic prints in on the right, top to bottom, black-and-white ones light on dark
like the xkcd page draws them; it holds long enough to read, and the new page comes down over it.

Only small comics, ones you can read in a few seconds: at most 700 x 420 at xkcd's own size, so the bar shows them at
least that big, with alt text of 120 characters or less. Big ones are for the xkcd page. A transition can't wait on the internet, so a
background thread finds them ahead of time, as it plays: a few random comics an hour from xkcd's JSON (no key), the
pictures from imgs.xkcd.com, kept in ~/.cache/kiosk/xkcd-panel/ (the last 20). It shows one it hasn't shown lately,
laid out before it starts and kept for the whole play. Until it has one, it says so. xkcd is Randall Munroe's,
CC BY-NC 2.5, credited on screen.
"""
import io, json, os, random, threading, time, urllib.error, urllib.request
from PIL import Image, ImageOps

import kit
from .canvas import WIDTH, HEIGHT

SECONDS = 5
STILL = 3.0                                   # seconds it holds still, to be read
DARK, PRINTED, COVER = 0.08, 0.20, 0.88       # it's dark, the comic's printed, the new page starts coming down
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
INK, DIM = (232, 236, 255), (154, 163, 199)


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


def wrap(words, width):
    lines = [""]
    for word in (w[i:i + width] for w in words.split() for i in range(0, len(w), width)):
        if lines[-1] and len(lines[-1]) + 1 + len(word) > width:
            lines.append("")
        lines[-1] = (lines[-1] + " " + word).strip()
    return lines


def scene(comic):
    """the comic laid out, before it plays -> {"words": the dark screen with the title and alt text, "full": that and
    the comic, packed bytes; "box": where the comic is (x, y, w, h)}"""
    img = Image.new("RGB", (WIDTH, HEIGHT), kit.BG)
    if not comic:
        kit.text(img, (40, 40), "// XKCD", kit.O, scale=1)
        kit.text(img, (40, 64), "A COMIC WILL BE HERE ONCE THE KIOSK'S BEEN ONLINE", DIM, scale=2)
        plain = kit.rgb565(img)
        return {"words": plain, "full": plain, "box": None}
    kit.text(img, (40, 40), f"// XKCD #{comic['num']}", kit.O, scale=1)
    kit.text(img, (40, 64), comic["title"].upper()[:20], INK, scale=4)
    for i, line in enumerate(wrap(comic["alt"], 38)[:5]):
        kit.text(img, (40, 160 + i * 40), line, DIM, scale=2)
    kit.text(img, (40, HEIGHT - 30), "xkcd.com · Randall Munroe · CC BY-NC 2.5", kit.D, scale=1)
    words = kit.rgb565(img)
    pic = Image.open(comic["file"]).convert("RGB")
    plain = all(abs(r - g) < 24 and abs(g - b) < 24 for r, g, b in pic.resize((64, 64)).getdata())
    if plain:   # black on white: light on dark instead, as the xkcd page draws it
        pic = Image.eval(ImageOps.invert(pic.convert("L")), lambda v: v * 236 // 255).convert("RGB")
    w, h = COMIC[2] - COMIC[0], COMIC[3] - COMIC[1]
    k = min(w / pic.width, h / pic.height)
    pic = pic.resize((pic.width * int(k), pic.height * int(k)), Image.NEAREST) if k >= 2 else \
        pic.resize((max(1, round(pic.width * k)), max(1, round(pic.height * k))), Image.LANCZOS)
    x, y = COMIC[0] + (w - pic.width) // 2, COMIC[1] + (h - pic.height) // 2
    if not plain:   # colour keeps a white card round it
        img.paste((255, 255, 255), (x - 12, y - 12, x + pic.width + 12, y + pic.height + 12))
        x0, y0, x1, y1 = x - 12, y - 12, x + pic.width + 12, y + pic.height + 12
    else:
        x0, y0, x1, y1 = x, y, x + pic.width, y + pic.height
    img.paste(pic, (x, y))
    return {"words": words, "full": kit.rgb565(img), "box": (x0, y0, x1 - x0, y1 - y0)}


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


def frames(c, count):
    shown = ready["scene"] or scene(pick(kept()))   # chosen now, and kept for the whole play
    ready["scene"] = None                            # this one's used: lay out the next while this plays
    threading.Thread(target=refresh, daemon=True).start()
    dark = printed = covered = 0
    box = shown["box"]
    for k in range(count):
        t = k / max(1, count - 1)                    # a lone frame is the first; play() lands on the new page
        rows = min(HEIGHT, round(t / DARK * HEIGHT))
        if rows > dark:                              # the dark comes down, with the words: whole rows
            c.reveal(0, dark, WIDTH, rows - dark, src=shown["words"]); dark = rows
        if box and t >= DARK:                        # the comic prints in, top to bottom
            done = min(box[3], round((t - DARK) / (PRINTED - DARK) * box[3]))
            if done > printed:
                c.reveal(box[0], box[1] + printed, box[2], done - printed, src=shown["full"]); printed = done
        if t >= COVER:                               # and the new page comes down over it: whole rows
            rows = min(HEIGHT, round((t - COVER) / (1 - COVER) * HEIGHT))
            if rows > covered:
                c.reveal(0, covered, WIDTH, rows - covered); covered = rows
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
            assert COMIC[0] <= x and x + w <= COMIC[2] + 12 and y >= 0 and y + h <= HEIGHT, "colour, with its card"
        finally:
            FOLDER, KEPT = real
