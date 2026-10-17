"""The Setup page: how to log in to the kiosk's setup page, on the kiosk's own screen and nowhere else.

admin.py writes /run/kiosk/setup.json (RAM only) while the kiosk hasn't been set up: the addresses to go to, the
first-boot user name and password, and the fingerprint of the certificate it serves by IP, to check against the
browser's warning. While that's there it's urgent(), and kiosk.py shows it over everything, on the Pi itself, even one
that usually shows a render server. Once someone has replaced the first-boot login, admin.py writes where to log in
from then on instead, and that's urgent for 10 minutes. After that, while the setup page can be reached by IP, the
page is active() in the rotation for a few seconds a time with just the addresses and the fingerprint (never a
password), so every later login by IP has something to check against. A kiosk on a render server shows the server's
pages instead, so there it's only on screen while it's urgent. It's never in playlist.json: kiosk.py adds it.
"""
import json, os, time
from datetime import datetime
from PIL import Image

from kit import SCREEN, O, W, G, BG, text, packed

SETUP = "/run/kiosk/setup.json"   # the same file admin.py writes
AFTER = 10 * 60                  # how long "here's where to log in now" stays up once it's set up


def read(path=SETUP):
    try:
        return json.load(open(path)), os.path.getmtime(path)
    except (OSError, ValueError):
        return None, 0


def wanted(path=SETUP):
    """whether the Setup page should be in the rotation"""
    info, when = read(path)
    if not info:
        return False
    return bool(info.get("user")) or recent(info, when) or bool(info.get("fingerprint"))


def recent(info, when):
    return info.get("done") is True and time.time() - when < AFTER


def urgent(path=SETUP):
    """whether it should be on screen ahead of everything: the first-boot login, or where to log in now it's set up"""
    info, when = read(path)
    return bool(info) and (bool(info.get("user")) or recent(info, when))


def draw(info, when=None):
    img = Image.new("RGB", SCREEN, BG)
    if not info.get("user") and info.get("fingerprint") and not recent(info, when if when is not None else time.time()):
        text(img, (40, 30), "THIS KIOSK'S SETUP PAGE", O, scale=3)
        text(img, (40, 110), "  ".join(info.get("addresses", [])[:3]), W, scale=2)
        text(img, (40, 190), "By IP your browser warns that it can't check the certificate. Only go past that warning", G)
        text(img, (40, 225), "if the browser's SHA-256 fingerprint for it reads:", G)
        text(img, (40, 280), info["fingerprint"], O)
        return img
    if info.get("done"):
        text(img, (40, 30), "SET UP", O, scale=3)
        text(img, (40, 110), "From now on, log in to its setup page at:" if info.get("next") else
             "It's set up. Its setup page is off by IP now; it needs its certificate for its name.", W)
        ways = info.get("next", [])[:4]
        small = info.get("fingerprint") and len(ways) > 3   # four ways in and the fingerprint: smaller, so none is left off
        for i, way in enumerate(ways):
            text(img, (80, 170 + i * (40 if small else 50)), way, W, scale=2 if small else 3)
        if info.get("fingerprint"):   # by IP, the certificate to check against is on screen from the very first minute
            text(img, (40, 345), "By IP, only go past the browser's warning if its SHA-256 fingerprint reads:", G)
            text(img, (40, 390), info["fingerprint"], O)
        return img
    text(img, (40, 26), "SET ME UP", O, scale=3)
    ways = info.get("addresses", [])
    text(img, (40, 100), "Go to " + "  or  ".join(ways[:3]), W)
    text(img, (40, 160), "User name", G); text(img, (320, 152), info.get("user", ""), W, scale=3)
    text(img, (40, 230), "Password", G); text(img, (320, 222), info.get("password", ""), W, scale=3)
    if info.get("fingerprint"):
        text(img, (40, 310), "By IP your browser warns that it can't check the certificate. Only you, at this screen, should", G)
        text(img, (40, 345), "go past that warning, and only if the browser's SHA-256 fingerprint for it reads:", G)
        text(img, (40, 390), info["fingerprint"], O)
        text(img, (40, 445), "If it doesn't match, don't log in: something else on the network answered.", G)
    else:
        text(img, (40, 330), "You'll pick your own user name and password when you log in.", G)
    return img


class Page:
    name, seconds = "setup", 30

    def __init__(self, path=SETUP):
        self.path, self.bg = path, (None, None)

    def start(self, now):
        info, when = read(self.path)
        self.bg = (None, None)
        self.seconds = 30 if info and (info.get("user") or recent(info, when)) else 10   # just the fingerprint: briefly

    def background(self, now):
        info, when = read(self.path)
        key = (when, recent(info or {}, when))
        if key != self.bg[0]:
            self.bg = (key, packed(draw(info or {"done": True}, when)))
        return self.bg

    def regions(self, now, t):
        return []

    def active(self):   # in the rotation only as the reminder: while it's urgent, kiosk.py shows it over everything
        return wanted(self.path) and not urgent(self.path)


def check():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "setup.json")
        assert not wanted(path), "nothing to show"
        info = {"user": "Kiosk-Otter", "password": "acorn-lemon-tulip", "addresses": ["https://10.0.0.5", "https://k-abc123.kiosk.local"],
                "fingerprint": ":".join(["AB"] * 32)}
        json.dump(info, open(path, "w"))
        assert wanted(path) and urgent(path) and not Page(path).active(), "the first-boot login goes over everything"
        page = Page(path); page.start(datetime.now())
        key, bg = page.background(datetime.now())
        assert bg.size == SCREEN and page.background(datetime.now())[0] == key and page.regions(datetime.now(), 0) == []
        json.dump({"done": True, "next": ["https://k-abc123.kiosk.local"]}, open(path, "w"))
        assert wanted(path), "where to log in from now on, for a while"
        os.utime(path, (time.time() - AFTER - 1,) * 2)
        assert not wanted(path), "then it goes"
        json.dump({"done": True, "next": ["https://10.0.0.5"], "addresses": ["https://10.0.0.5"], "fingerprint": info["fingerprint"]}, open(path, "w"))
        os.utime(path, (time.time() - AFTER - 1,) * 2)
        assert wanted(path), "unless it can be set up by IP: then the fingerprint stays in the rotation"
        assert not urgent(path) and Page(path).active(), "as a page in the rotation, not over everything"
        page = Page(path); page.start(datetime.now())
        assert page.seconds == 10 and "password" not in json.load(open(path)), "briefly, and never with a password"
        assert draw(json.load(open(path)), os.path.getmtime(path)).size == SCREEN
        for shown in (info, {"done": True, "next": []}, {"done": True, "next": ["https://k-abc123.kiosk.local"]}):
            assert draw(shown).size == SCREEN


def preview(now=None):
    return draw({"user": "Kiosk-Otter", "password": "acorn-lemon-tulip", "addresses": ["https://192.168.1.50"],
                 "fingerprint": ":".join(["3F", "A0", "9C", "71"] * 8)})
