"""The agents page: how much of each AI plan I've used (Claude Personal, Claude Work, Codex), and what my herdr
workspaces are doing.

Usage comes from KodexBar's quota engine (kodexbar-quotas), the same numbers the KodexBar widget shows: every window
with how full it is and when it resets. Herdr's workspaces each get a row of pixel blocks, one per agent, coloured by
status; working agents blink and are named.

Both come from my desktop, in ~/.cache/kiosk/desk.json (feed/deskfeed.py, read through kit.Feed).

Options (in playlist.json): feed, the feed file (default ~/.cache/kiosk/desk.json).
"""
import json, os
from datetime import datetime
from PIL import Image, ImageDraw

from kit import SCREEN, O, W, G, D, A, GREEN, BG, RULE, RAISED, ERROR, Feed, local, masthead, text, packed, level, meter

TOP, MARGIN, SPLIT = 98, 16, 720             # usage on the left, herdr on the right of SPLIT
BLOCKS, BLOCK = 20, 16                        # a usage bar is 20 pixel blocks, 5% each
STATUS = {"working": O, "done": GREEN, "idle": D, "blocked": A, "waiting": A}
ORDER = {"working": 0, "blocked": 1, "waiting": 1, "done": 2}
WS_COLUMNS, WS_ROW = 2, 52


def resets(when, now):
    """'2h 31m' within a day, else 'Sat 9p'"""
    if when is None:
        return ""
    when = local(when); m = (when - now).total_seconds() / 60
    if m < 0:
        return "now"
    if m < 24 * 60:
        return f"{int(m // 60)}h {int(m % 60):02d}m" if m >= 60 else f"{int(m)}m"
    return when.strftime("%a ") + when.strftime("%I").lstrip("0") + ("a" if when.hour < 12 else "p")


def draw(now, data, note=None):
    """the whole page, 1920x515 RGB; returns it and the working agents' blocks [(x, y)], which blink"""
    img = Image.new("RGB", SCREEN, BG); d = ImageDraw.Draw(img)
    masthead(img, now, "// 03 · AGENTS", "FLIGHT DECK", note)
    data = data or {}

    # usage: one panel, each plan's windows as pixel-block bars
    x0, x1, y1 = MARGIN, SPLIT - 4, SCREEN[1] - 8
    d.rectangle((x0, TOP, x1, y1), fill=RAISED, outline=RULE)
    text(img, (x0 + 14, TOP + 10), "TOKENS", O)
    usage = data.get("usage") or {}
    y = TOP + 50
    if usage.get("error"):
        text(img, (x0 + 14, y), usage["error"][:80], A, scale=1); y += 24
    for plan in usage.get("items", []):
        rows = max(1, len(plan["windows"]))
        if y + 36 + rows * 26 > y1:
            break
        text(img, (x0 + 14, y), plan["label"].upper(), W); y += 36
        if plan.get("error"):
            text(img, (x0 + 30, y), str(plan["error"])[:76], A, scale=1); y += 26
        for w in plan["windows"]:
            used = max(0, min(100, w["used"]))
            text(img, (x0 + 30, y), w["name"][:6], G, scale=1)
            bx = x0 + 90 + meter(d, (x0 + 90, y), used, BLOCKS, BLOCK) + 8
            text(img, (bx + 32, y), f"{round(used)}%", level(used), scale=1, right=True)
            text(img, (bx + 44, y), resets(w.get("resets"), now), G, scale=1)
            y += 26
        y += 10

    # herdr: every workspace, a pixel block per agent
    x0, x1 = SPLIT + 4, SCREEN[0] - MARGIN
    d.rectangle((x0, TOP, x1, y1), fill=RAISED, outline=RULE)
    text(img, (x0 + 14, TOP + 10), "HERDR", O)
    herdr = data.get("herdr") or {}
    agents = [a for ws in herdr.get("items", []) for a in ws["agents"]]
    tally = {}
    for a in agents:
        tally[a["status"]] = tally.get(a["status"], 0) + 1
    x = x1 - 14
    for status, n in sorted(tally.items(), key=lambda kv: -ORDER.get(kv[0], 3)):   # right to left, working ends up first
        x -= text(img, (x, TOP + 18), f"{n} {status}", STATUS.get(status, G), scale=1, right=True) + 24
    if herdr.get("error"):
        text(img, (x0 + 14, TOP + 50), herdr["error"][:110], A, scale=1)
    blinking = []
    col_w = (x1 - x0 - 28) // WS_COLUMNS
    shown = [ws for ws in herdr.get("items", []) if ws["agents"]]   # empty workspaces have nothing to say
    fits = (y1 - TOP - 50) // WS_ROW * WS_COLUMNS
    for i, ws in enumerate(shown[:fits]):
        wx, wy = x0 + 14 + (i % WS_COLUMNS) * col_w, TOP + 50 + (i // WS_COLUMNS) * WS_ROW
        busy = sorted(ws["agents"], key=lambda a: ORDER.get(a["status"], 3))
        live = ORDER.get(busy[0]["status"], 3) < 3
        text(img, (wx, wy), ws["label"][:18], W if live else G)
        for k, a in enumerate(busy[:12]):
            bx = wx + col_w - 56 - k * 18
            d.rectangle((bx, wy + 10, bx + 11, wy + 21), fill=STATUS.get(a["status"], G))
            if a["status"] == "working":
                blinking.append((bx, wy + 10))
        names = ", ".join(a["title"] for a in busy if ORDER.get(a["status"], 3) < 3)
        sub = names or f"{len(busy)} idle"
        text(img, (wx, wy + 32), sub[:(col_w - 16) // 8], G if names else D, scale=1)
    if len(shown) > fits:
        text(img, (x1 - 14, y1 - 22), f"+{len(shown) - fits} more", D, scale=1, right=True)
    return img, blinking


class Page:
    """the agents and tokens, as a page of the kiosk's cycle"""
    name, seconds = "agents", 20

    def __init__(self, feed="~/.cache/kiosk/desk.json"):
        self.feed, self.bg, self.blinking = Feed(feed), (None, None), []
        self.dark = packed(Image.new("RGB", (12, 12), RAISED))

    def active(self):
        return self.feed.fresh()   # skipped while the desktop's away

    def start(self, now):
        pass   # background() reads the feed, and only when it changes

    def background(self, now):
        data = self.feed.load()
        key = (now.minute, self.feed.mtime)   # the reset countdowns move on every minute
        if key != self.bg[0]:
            img, self.blinking = draw(now, data, self.feed.note(now))
            self.bg = (key, packed(img))
            self.lit = [(self.bg[1].crop((x, y, x + 12, y + 12)), (x, y)) for x, y in self.blinking]
        return self.bg

    def regions(self, now, t):
        """working agents blink; with none working, the page stands still"""
        if int(t * 2) % 2:
            return [(self.dark, xy) for xy in self.blinking]
        return self.lit


SAMPLE = {"updated": "2026-10-15T03:28:36+00:00",
          "usage": {"error": None, "items": [
              {"label": "Claude Personal", "error": None, "windows": [
                  {"name": "5h", "used": 24.0, "resets": "2026-10-15T07:30:00+00:00"},
                  {"name": "week", "used": 8.0, "resets": "2026-10-20T04:00:00+00:00"},
                  {"name": "Fable", "used": 4.0, "resets": "2026-10-20T04:00:00+00:00"}]},
              {"label": "Claude Work", "error": None, "windows": [
                  {"name": "5h", "used": 6.0, "resets": "2026-10-15T06:00:00+00:00"},
                  {"name": "week", "used": 55.0, "resets": "2026-10-18T01:00:00+00:00"},
                  {"name": "Fable", "used": 91.0, "resets": "2026-10-18T01:00:00+00:00"}]},
              {"label": "Codex", "error": None, "windows": [{"name": "week", "used": 6.0, "resets": "2026-10-20T14:51:51Z"}]}]},
          "herdr": {"error": None, "items": [
              {"label": "EventTracker", "agents": [{"title": "EventTracker Next.js", "status": "idle", "agent": "claude"}]},
              {"label": "Astroledger", "agents": [{"title": t, "status": "idle", "agent": "claude"} for t in ("AL-Dev", "AL-Aux", "AL-Doc")]},
              {"label": "Staff-Travel-Checklist", "agents": [{"title": "stc-dev", "status": "working", "agent": "claude"},
                                                             {"title": "stc-aux", "status": "done", "agent": "claude"},
                                                             {"title": "stc-doc", "status": "idle", "agent": "claude"}]},
              {"label": "GalacticBoard", "agents": [{"title": "GM-Dev", "status": "working", "agent": "claude"}]},
              {"label": "personal", "agents": [{"title": "Kiosk weather, GitHub and tokens", "status": "working", "agent": "claude"}]},
              {"label": "Home-Desktop", "agents": [{"title": "Solidcraft", "status": "blocked", "agent": "claude"}]},
              {"label": "empty", "agents": []}]}}


def check():
    now = datetime(2026, 10, 14, 23, 30)
    import time
    if time.localtime().tm_zone in ("EDT", "EST"):   # the sample's times are New York's
        assert resets("2026-10-15T07:30:00+00:00", now) == "4h 00m" and resets("2026-10-15T03:40:00+00:00", now) == "10m"
        assert resets("2026-10-18T01:00:00+00:00", now) == "Sat 9p" and resets("2026-10-14T00:00:00+00:00", now) == "now"
    assert resets(None, now) == "" and level(10) == O and level(60) == A and level(95) == ERROR
    for data in (SAMPLE, None, {"updated": SAMPLE["updated"], "usage": {"error": "kodexbar-quotas: not found", "items": []},
                                "herdr": {"error": "herdr: no server", "items": []}}):
        img, blinking = draw(now, data)
        assert img.size == SCREEN, "draws with, without and with broken data"
    assert len(draw(now, SAMPLE)[1]) == 3, "each working agent blinks"
    import tempfile
    path = os.path.join(tempfile.mkdtemp(), "desk.json"); json.dump(SAMPLE, open(path, "w"))
    page = Page(feed=path)
    key, bg = page.background(now)
    assert bg.mode == "LA" and bg.size == SCREEN and page.background(now)[0] == key, "redrawn only when something changes"
    on, off = page.regions(now, 0.0), page.regions(now, 0.5)
    assert len(on) == 3 and on[0][0].tobytes() != off[0][0].tobytes(), "working agents blink"
    assert TOP + 50 + 3 * 36 + 7 * 26 + 3 * 10 <= SCREEN[1] - 8, "three plans with their windows fit"


def preview(now=None):
    """the page with the sample feed, for the emulator and kiosk.py --png"""
    return draw(now or datetime(2026, 10, 14, 23, 30), SAMPLE, ("desktop · 11:28 PM", D))[0]
