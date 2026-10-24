"""xkcd: the latest xkcd comic, or a random one from the archive. The comic fills the right of the screen, as big as it
fits; on the left, its number, title and date, and its alt text, the joke xkcd hides in the mouse-over that a kiosk
would otherwise never show. Black-and-white comics are drawn light on the kiosk's dark background (their colours
turned round), and colour ones on a white card.

The comic comes from xkcd's own JSON (xkcd.com/info.0.json, no key), every hour, with its picture from imgs.xkcd.com
(the double-size one where there is one). The picture is kept in ~/.cache/kiosk/xkcd/, beside the cache every renderer
on the machine shares (kit.Simple), so it's fetched once. xkcd is Randall Munroe's, CC BY-NC 2.5, credited on screen.

Options (in playlist.json): random, true for a random comic every hour instead of the latest (default false).
"""
import io, json, os, random as chance, urllib.error, urllib.request
from PIL import Image, ImageOps

from kit import SCREEN, Simple, G, D, RAISED, text, masthead

API = "https://xkcd.com/{}info.0.json"         # "" for the latest, "1205/" for one
PICTURES = "https://imgs.xkcd.com/comics/"     # the only place a picture is fetched from
UA = {"User-Agent": "wi-ki xkcd (github.com/nomadsgalaxy/wi-ki)"}
FOLDER = os.path.expanduser("~/.cache/kiosk/xkcd")
KEEP, BIGGEST = 10, 4 << 20                    # pictures kept, and the most a picture may be, in bytes
COMIC = (680, 12, SCREEN[0] - 24, SCREEN[1] - 12)   # where the comic goes
SAY = 600                                      # the left side's width, for the words


def get(url, limit=1 << 20):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:
        body = r.read(limit + 1)
    if len(body) > limit:
        raise ValueError(f"{url} is bigger than {limit} bytes")
    return body


def picture(url):
    """a comic's picture, the double-size one if xkcd has it -> PNG bytes, decoded and saved again here so only a
    picture that really is one gets kept"""
    if not url.startswith(PICTURES) or not url.lower().endswith((".png", ".jpg", ".jpeg", ".gif")):
        raise ValueError(f"not an xkcd picture: {url[:80]}")
    stem, _, ext = url.rpartition(".")
    for each in (f"{stem}_2x.{ext}", url):
        try:
            img = Image.open(io.BytesIO(get(each, BIGGEST)))
            img.load()
            out = io.BytesIO(); img.convert("RGBA" if "A" in img.getbands() else "RGB").save(out, "PNG")
            return out.getvalue()
        except urllib.error.HTTPError as e:
            if e.code != 404 or each == url:   # no double-size one is fine; anything else isn't
                raise
    raise ValueError("no picture")


def text_of(value, most):
    return " ".join(str(value).split())[:most] if isinstance(value, (str, int)) else ""


def clean(raw):
    """the fetched comic -> {num, title, alt, date, file}, every part made to fit, the file only if it's one of ours;
    None without a number"""
    if not isinstance(raw, dict) or not isinstance(raw.get("num"), int) or isinstance(raw.get("num"), bool):
        return None
    file = raw.get("file")
    ours = isinstance(file, str) and os.path.dirname(os.path.realpath(file)) == os.path.realpath(FOLDER)
    return {"num": max(0, raw["num"]), "title": text_of(raw.get("title"), 60), "alt": text_of(raw.get("alt"), 600),
            "date": text_of(raw.get("date"), 10), "file": file if ours else None}


def wrap(words, width):
    lines = [""]
    for word in (w[i:i + width] for w in words.split() for i in range(0, len(w), width)):
        if lines[-1] and len(lines[-1]) + 1 + len(word) > width:
            lines.append("")
        lines[-1] = (lines[-1] + " " + word).strip()
    return lines


def fitted(img, box):
    """the comic as big as it fits in box (w, h): line art doubled or more by whole pixels stays sharp. Black and
    white ones are turned light on dark -> (picture, on a white card or not)"""
    w, h = box
    grey = img.convert("RGB")
    plain = all(abs(r - g) < 24 and abs(g - b) < 24 for (r, g, b) in grey.resize((64, 64)).getdata())
    if plain:   # black on white: light on the kiosk's dark instead
        grey = ImageOps.invert(grey.convert("L")).convert("RGB")
        grey = Image.eval(grey, lambda v: v * 236 // 255)   # a touch under full white, like the rest of the kiosk
    k = min(w / grey.width, h / grey.height)
    if k >= 2:
        k = int(k); out = grey.resize((grey.width * k, grey.height * k), Image.NEAREST)
    else:
        out = grey.resize((max(1, round(grey.width * k)), max(1, round(grey.height * k))), Image.LANCZOS)
    return out, not plain


class Page(Simple):
    """the comic, as a page of the kiosk's cycle"""
    name, seconds = "xkcd", 25
    every = 3600
    SAMPLE = {"num": 1, "title": "A Sample Comic", "date": "2026-10-19", "file": None,
              "alt": "The alt text goes here: the line xkcd hides in the mouse-over, which a kiosk shows instead."}
    clean = staticmethod(clean)
    mark = (SAY, 54)

    def __init__(self, random=False):
        self.random, self.shown = bool(random), (None, None)

    def fetch(self):
        latest = json.loads(get(API.format("")))
        comic = latest
        if self.random and isinstance(latest.get("num"), int):
            for _ in range(5):   # a few tries: some numbers have no comic (404 never did)
                try:
                    comic = json.loads(get(API.format(f"{chance.randint(1, latest['num'])}/"))); break
                except urllib.error.HTTPError:
                    continue
        num = comic["num"]
        os.makedirs(FOLDER, exist_ok=True)
        file = os.path.join(FOLDER, f"{int(num)}.png")
        if not os.path.exists(file):
            with open(file + ".tmp", "wb") as f:
                f.write(picture(str(comic.get("img", ""))))
            os.replace(file + ".tmp", file)
            kept = sorted((os.path.join(FOLDER, n) for n in os.listdir(FOLDER) if n.endswith(".png")), key=os.path.getmtime)
            for old in kept[:-KEEP]:   # only the last few
                os.remove(old)
        date = "-".join(f"{int(comic.get(k, 0)):02d}" for k in ("year", "month", "day")) if comic.get("year") else ""
        return {"num": num, "title": comic.get("safe_title") or comic.get("title"), "alt": comic.get("alt"),
                "date": date, "file": file}

    def draw(self, img, now, data):
        title = data["title"] or "?"
        masthead(img, now, f"// XKCD #{data['num']}" + (f" · {data['date']}" if data["date"] else ""),
                 title.upper()[:20] + ("…" if len(title) > 20 else ""))
        y = 110
        for line in wrap(data["alt"], SAY // 16 - 3)[:9]:   # the alt text, the joke under the joke
            text(img, (24, y), line, G, scale=2); y += 36
        text(img, (24, SCREEN[1] - 22), "xkcd.com · Randall Munroe · CC BY-NC 2.5", D, scale=1)
        box = (COMIC[2] - COMIC[0], COMIC[3] - COMIC[1])
        if self.shown[0] != (data["num"], data["file"]):   # sized once for each comic
            comic = None
            if data["file"]:
                try:
                    comic = fitted(Image.open(data["file"]), (box[0] - 32, box[1] - 32))
                except (OSError, ValueError):
                    comic = None   # gone, or not a picture: say so, below
            self.shown = ((data["num"], data["file"]), comic)
        comic = self.shown[1]
        if not comic:
            img.paste(RAISED, COMIC)
            text(img, (COMIC[0] + 40, COMIC[1] + 40), "the comic is on its way", D, scale=2)
            return
        pic, card = comic
        x, y = COMIC[0] + (box[0] - pic.width) // 2, COMIC[1] + (box[1] - pic.height) // 2
        if card:   # colour comics keep their white
            img.paste((255, 255, 255), (x - 16, y - 16, x + pic.width + 16, y + pic.height + 16))
        img.paste(pic, (x, y))


def check():
    assert clean(None) is None and clean({"num": "3"}) is None and clean({"num": True}) is None
    assert clean({"num": 5, "file": "/etc/passwd"})["file"] is None, "only a picture in our own folder"
    assert clean({"num": 5, "title": "x" * 99, "alt": ["no"]}) == {"num": 5, "title": "x" * 60, "alt": "", "date": "", "file": None}
    for bad in ("https://example.com/comics/a.png", "https://imgs.xkcd.com/comics/a.exe", ""):
        try:
            picture(bad); raise AssertionError(f"fetched {bad!r}")
        except ValueError:
            pass
    line_art = Image.new("RGB", (100, 80), (255, 255, 255)); line_art.paste((0, 0, 0), (10, 10, 90, 12))
    pic, card = fitted(line_art, (400, 320))
    assert not card and pic.size == (400, 320) and pic.getpixel((50, 45)) == (236, 236, 236) and pic.getpixel((5, 5)) == (0, 0, 0), \
        "black and white turned light on dark, doubled up by whole pixels"
    colour = Image.new("RGB", (300, 200), (200, 40, 40))
    pic, card = fitted(colour, (600, 300))
    assert card and pic.size == (450, 300), "colour keeps its card, and is scaled to fit"
    Page.check()
    page = Page.showing(Page.SAMPLE)
    with __import__("tempfile").TemporaryDirectory() as folder:   # a real picture, through the page as it'd be drawn
        global FOLDER
        real, FOLDER = FOLDER, folder
        try:
            path = os.path.join(folder, "1.png"); line_art.save(path)
            page = Page.showing(dict(Page.SAMPLE, file=path))
            assert page.data["file"] == path and page.picture(__import__("datetime").datetime(2026, 10, 19, 9, 41), page.data, safe=False).size == SCREEN
            assert page.shown[1] is not None, "it drew the comic"
        finally:
            FOLDER = real


def preview(now=None):
    return Page.preview(now)
