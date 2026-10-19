"""{name}: say what the page shows here, in a sentence or two, and where its data comes from.

Made from catalog/new/page.py with kit.Simple (docs/make.md has the whole story). You write draw(), and fetch() if it
shows data from somewhere; kit does the rest.
"""
from PIL import Image

from kit import Simple, O, W, BG, text, masthead


class Page(Simple):
    name, seconds = "{name}", 20
    every = 600   # run fetch() every 10 minutes. Take this out (and fetch()) for a page that has no data to get
    SAMPLE = {"title": "HELLO", "count": 42}   # what fetch() gives back: check(), preview() and fuzz draw with it
    cursor = 104   # where the title ends, for the blinking cursor: draw() moves it

    def __init__(self, title=None):
        """its options, from the playlist or the setup page, each with a default that works"""
        self.title = title

    def fetch(self):
        """get the data: from the internet (urllib.request), a file, anything. It runs in the background, so it can be
        slow, and if it raises, the page keeps the data it had and tries again in a minute."""
        return self.SAMPLE   # put yours here

    def draw(self, img, now, data):
        """draw on img, an RGB picture the size of the screen, cleared to the background. data can be anything at all
        in check() (it tries broken data too), so use .get() and str() rather than trusting it."""
        data = data if isinstance(data, dict) else {}
        title = str(self.title or data.get("title") or "")[:40].upper()
        self.cursor = masthead(img, now, "// {name}".upper(), title)   # the Drifter, the title and the clock, like every page
        text(img, (40, 160), f"{data.get('count', '?')} things"[:70], W, scale=4)

    def moving(self, now, t, data):
        """what moves, every frame: [(picture, (x, y))]. t is seconds since the page came up. Keep the pictures small,
        since every one is packed and copied 4 times a second."""
        on = int(t * 2) % 2 == 0   # a cursor blinking twice a second, so the page is never quite still
        return [(Image.new("RGB", (16, 40), O if on else BG), (self.cursor + 8, 34))]


def check():
    Page.check()   # draws SAMPLE, the waiting screen and broken data, and checks what moves stays on the screen
    # your own asserts go here


def preview(now=None):
    return Page.preview(now)
