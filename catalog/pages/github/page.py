"""The GitHub page: one column each for Nomads Galaxy, Positron 3D and Hive76, with their open PRs and issues and the
five repos pushed to most recently, each with its last commit.

The Pi can't see private repos, so the data comes from my desktop: feed/deskfeed.py asks GitHub with gh and pushes
~/.cache/kiosk/desk.json here (kit.Feed). Until that arrives the page says it's waiting.

Options (in playlist.json): feed, the feed file (default ~/.cache/kiosk/desk.json).
"""
import json, os
from datetime import datetime
from PIL import Image, ImageDraw

from kit import SCREEN, O, W, G, D, A, BG, RULE, RAISED, Feed, local, masthead, text, packed

COLUMNS, TOP, MARGIN = 3, 98, 16
COL_W = (SCREEN[0] - 2 * MARGIN) // COLUMNS
ROW = 70
BRAND = "nomadsgalaxy"   # the one owner drawn in Warp Cyan; partners keep plain Starlight (brand manual 8.2)


def ago(when, now):
    """how long ago, short: 12m, 5h, 3d"""
    m = max(0, (now - when).total_seconds() / 60)
    return f"{round(m)}m" if m < 60 else f"{round(m / 60)}h" if m < 48 * 60 else f"{round(m / 1440)}d"


def text_of(v, n):
    """v if it's a string, cut to n characters, else empty"""
    return v[:n] if isinstance(v, str) else ""


def count_of(v):
    """v as a whole number from 0 to 99999, else 0"""
    try:
        return max(0, min(99999, int(v)))
    except (TypeError, ValueError, OverflowError):
        return 0


def when_of(v):
    """v as a local time, or None when it isn't an ISO time"""
    try:
        return local(v)
    except (TypeError, ValueError, OverflowError):
        return None


def tidy(data):
    """the feed as the page draws it: types coerced, missing fields filled in, repos without a readable push time
    dropped (their 'pushed' becomes a local time). A feed that isn't a dict or has no readable 'updated' comes back as
    None, the page's 'waiting for the desktop'."""
    if not isinstance(data, dict) or not when_of(data.get("updated")):
        return None
    gh = data.get("github") if isinstance(data.get("github"), dict) else {}
    owners = []
    for o in gh.get("items") if isinstance(gh.get("items"), list) else []:
        if not isinstance(o, dict):
            continue
        repos = []
        for r in o.get("repos") if isinstance(o.get("repos"), list) else []:
            pushed = when_of(r.get("pushed")) if isinstance(r, dict) else None
            if pushed:
                repos.append({"name": text_of(r.get("name"), 60), "private": r.get("private") is True, "pushed": pushed,
                              "commit": text_of(r.get("commit"), 200)})
        owners.append({"owner": text_of(o.get("owner"), 40), "login": text_of(o.get("login"), 40),
                       "prs": count_of(o.get("prs")), "issues": count_of(o.get("issues")), "repos": repos})
    return {"updated": data["updated"], "github": {"error": text_of(gh.get("error"), 110), "items": owners}}


def draw(now, data, note=None):
    """the whole page, 1920x515 RGB; returns it and where the cursor goes"""
    img = Image.new("RGB", SCREEN, BG); d = ImageDraw.Draw(img)
    end = masthead(img, now, "// 02 · GITHUB", "LATEST PUSHES", note)
    gh = (data or {}).get("github") or {}
    if gh.get("error"):
        text(img, (MARGIN + 8, TOP + 8), ("github: " + gh["error"])[:110], A)
    for i, owner in enumerate(gh.get("items", [])[:COLUMNS]):
        x0, y0 = MARGIN + i * COL_W, TOP
        x1, y1 = x0 + COL_W - 8, SCREEN[1] - 8
        d.rectangle((x0, y0, x1, y1), fill=RAISED, outline=RULE)
        text(img, (x0 + 14, y0 + 10), owner["owner"].upper(), O if owner.get("login") == BRAND else W)
        counts = f"{owner['prs']} PR · {owner['issues']} issues"
        text(img, (x1 - 14, y0 + 18), counts, G, scale=1, right=True)
        d.rectangle((x0 + 8, y0 + 50, x1 - 8, y0 + 50), fill=RULE)
        room = (x1 - x0 - 28) // 16 - 5   # characters for a repo name at scale 2, leaving room for the age
        if not owner.get("repos"):
            text(img, (x0 + 14, y0 + 64), "no recent pushes", D, scale=1)
        for k, r in enumerate(owner["repos"]):
            y = y0 + 60 + k * ROW
            if y + 52 > y1:
                break
            pushed = r["pushed"]
            fresh = (now - pushed).total_seconds() < 24 * 3600   # pushed in the last day: lit up
            text(img, (x0 + 14, y), r["name"][:room], W if fresh else G)
            text(img, (x1 - 14, y), ago(pushed, now), O if fresh else D, right=True)
            commit = ("■ " if r.get("private") else "") + r.get("commit", "")
            text(img, (x0 + 14, y + 36), commit[:(x1 - x0 - 28) // 8], G if fresh else D, scale=1)
    return img, (end + 10, 44)


class Page:
    """GitHub, as a page of the kiosk's cycle"""
    name, seconds = "github", 20

    def __init__(self, feed="~/.cache/kiosk/desk.json"):
        self.feed, self.bg, self.cursor = Feed(feed), (None, None), (0, 0)
        self.blink = [packed(Image.new("RGB", (16, 32), c)) for c in (O, BG)]

    def active(self):
        return self.feed.fresh()   # skipped while the desktop's away

    def start(self, now):
        pass   # background() reads the feed, and only when it changes

    def background(self, now):
        data = tidy(self.feed.load())
        key = (now.minute, self.feed.mtime)   # the ages move on every minute
        if key != self.bg[0]:
            img, self.cursor = draw(now, data, self.feed.note(now) if data else ("waiting for the desktop", A))
            self.bg = (key, packed(img))
        return self.bg

    def regions(self, now, t):
        return [(self.blink[int(t * 2) % 2], self.cursor)]   # a blinking terminal cursor, so it's never quite still


SAMPLE = {"updated": "2026-10-15T03:28:36+00:00", "github": {"error": None, "items": [
    {"owner": "Nomads Galaxy", "login": "nomadsgalaxy", "prs": 9, "issues": 3, "repos": [
        {"name": "desk-kiosk", "private": True, "pushed": "2026-10-15T03:23:14Z", "commit": "GitHub and agents pages"},
        {"name": "galacticmap", "private": False, "pushed": "2026-10-15T03:03:19Z",
         "commit": "Spreadsheets: Excel-compatible formulas, units and typed variables, and a very long tail that gets cut"},
        {"name": "PrintTracking", "private": True, "pushed": "2026-10-14T14:01:30Z", "commit": "Accept October 14 metadata"},
        {"name": "arch-systemsync", "private": True, "pushed": "2026-10-14T04:50:19Z", "commit": "Move galacticmap repo"},
        {"name": "SM4L", "private": False, "pushed": "2026-10-10T02:59:42Z", "commit": "Document HF5.9"}]},
    {"owner": "Positron 3D", "login": "Positron3D", "prs": 13, "issues": 29, "repos": [
        {"name": "PosiWebsite", "private": False, "pushed": "2026-10-09T02:08:29Z", "commit": "Merge pull request #12"},
        {"name": "printer-klipper-config-with-a-name-too-long", "private": False, "pushed": "2026-10-08T02:22:14Z",
         "commit": "Merge pull request #39"}]},
    {"owner": "Hive76", "login": "hive76", "prs": 0, "issues": 2, "repos": []}]}}


def check():
    now = datetime(2026, 10, 14, 23, 30)
    assert ago(datetime(2026, 10, 14, 23, 18), now) == "12m" and ago(datetime(2026, 10, 14, 18, 0), now) == "6h"
    assert ago(datetime(2026, 10, 10, 23, 30), now) == "4d" and ago(datetime(2026, 10, 15), now) == "0m", "clock skew isn't negative"
    for data in (tidy(SAMPLE), None, {"updated": SAMPLE["updated"], "github": {"error": "gh: not logged in", "items": []}}):
        img, cursor = draw(now, data)
        assert img.size == SCREEN, "draws with, without and with broken data"
    assert tidy(None) is None and tidy({"github": {}}) is None and tidy({"updated": "soon"}) is None, "no readable feed: waiting"
    odd = tidy({"updated": SAMPLE["updated"], "github": {"error": 3, "items": [
        {"owner": None, "prs": "7", "issues": None, "repos": [{"name": "a"}, {"pushed": "2026-10-15T03:23:14Z"}, 5]}, "x"]}})
    assert [(o["owner"], o["prs"], o["issues"], len(o["repos"])) for o in odd["github"]["items"]] == [("", 7, 0, 1)], "odd types are coerced"
    assert odd["github"]["items"][0]["repos"][0]["name"] == "" and draw(now, odd)[0].size == SCREEN, "a repo with no push time is dropped"
    assert tidy({"updated": SAMPLE["updated"], "github": {"items": {}}})["github"]["items"] == [], "an empty list draws"
    import tempfile
    path = os.path.join(tempfile.mkdtemp(), "desk.json")
    page = Page(feed=path)
    assert page.background(now)[1].size == SCREEN and page.feed.note(now)[0] == "waiting for the desktop"
    assert not page.active(), "no feed: skipped"
    json.dump(dict(SAMPLE, updated=datetime.now().astimezone().isoformat()), open(path, "w"))
    assert page.active(), "a fresh feed: shown"
    json.dump(SAMPLE, open(path, "w")); os.utime(path, (2, 2))
    assert not page.active(), "a feed from long ago: skipped"
    key, bg = page.background(now)
    assert bg.mode == "LA" and page.background(now)[0] == key, "redrawn only when something changes"
    open(path, "w").write("{half a fi")
    os.utime(path, (1, 1)); page.background(now)
    assert page.feed.data == SAMPLE, "a broken file keeps the last good feed"
    assert page.regions(now, 0.0)[0][0].tobytes() != page.regions(now, 0.5)[0][0].tobytes(), "the cursor blinks"
    assert TOP + 60 + 5 * ROW - 18 <= SCREEN[1] - 8, "five repos fit"


def preview(now=None):
    """the page with the sample feed, for the emulator and kiosk.py --png"""
    return draw(now or datetime(2026, 10, 14, 23, 30), tidy(SAMPLE), ("desktop · 11:28 PM", D))[0]
