"""The agents page: what a desktop's herdr workspaces are doing, and, if that desktop has KodexBar, how much of each
AI plan it's used.

Herdr's workspaces each get a row of pixel blocks, one per agent, coloured by status; working agents blink and are
named. Plan usage comes from KodexBar's quota engine (kodexbar-quotas), the numbers its widget shows: every window with
how full it is and when it resets. A desktop without KodexBar sends no usage, and herdr gets the whole page.

Both come from the desktop, in ~/.cache/kiosk/desk.json (feed/deskfeed.py), which it reads as its file (kit.Simple).

Options (in playlist.json): feed, the feed file (default ~/.cache/kiosk/desk.json); plans, "auto" (the usage panel
when the feed has usage) or "off" (herdr only, always).
"""
import json, math, os
from datetime import datetime
from PIL import Image, ImageDraw

from kit import SCREEN, O, W, G, D, A, GREEN, BG, RULE, RAISED, ERROR, Simple, fresh, note, local, masthead, text, packed, level, meter

TOP, MARGIN, SPLIT = 98, 16, 720             # usage on the left, herdr on the right of SPLIT
DARK = packed(Image.new("RGB", (12, 12), RAISED))   # a working agent's light, off
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


def text_of(v, n):
    """v if it's a string, cut to n characters, else empty"""
    return v[:n] if isinstance(v, str) else ""


def when_of(v):
    """v if it's an ISO time the page can read, else None"""
    try:
        local(v)
        return v
    except (TypeError, ValueError, OverflowError):
        return None


def tidy(data):
    """the feed as the page draws it: types coerced, missing fields filled in, unusable items dropped. A feed that isn't
    a dict or has no readable 'updated' comes back as None, the page's 'waiting for the desktop'."""
    if not isinstance(data, dict) or not when_of(data.get("updated")):
        return None
    out = {"updated": data["updated"]}
    for key, inner in (("usage", "windows"), ("herdr", "agents")):
        part = data.get(key) if isinstance(data.get(key), dict) else {}
        items = []
        for item in part.get("items") if isinstance(part.get("items"), list) else []:
            if not isinstance(item, dict):
                continue
            rows = []
            for row in item.get(inner) if isinstance(item.get(inner), list) else []:
                if not isinstance(row, dict):
                    continue
                if key == "usage":
                    try:
                        used = float(row.get("used"))
                    except (TypeError, ValueError):
                        continue
                    if math.isfinite(used):
                        rows.append({"name": text_of(row.get("name"), 6), "used": max(0, min(100, used)),
                                     "resets": when_of(row.get("resets"))})
                else:
                    rows.append({"title": text_of(row.get("title"), 80), "status": text_of(row.get("status"), 12)})
            items.append({"label": text_of(item.get("label"), 30), inner: rows,
                          **({"error": text_of(item.get("error"), 80)} if key == "usage" else {})})
        out[key] = {"error": text_of(part.get("error"), 110), "items": items}
    return out


def plans_shown(data, plans="auto"):
    """whether the usage panel goes on the page: only when the feed has usage, and plans isn't off"""
    usage = (data or {}).get("usage") or {}
    return plans != "off" and bool(usage.get("items") or usage.get("error"))


def draw(now, data, note=None, plans="auto"):
    """the whole page, 1920x515 RGB; returns it and the working agents' blocks [(x, y)], which blink"""
    img = Image.new("RGB", SCREEN, BG); d = ImageDraw.Draw(img)
    masthead(img, now, "// AGENTS", "HERDR", note)
    data = data or {}
    y1 = SCREEN[1] - 8
    if plans_shown(data, plans):
        draw_usage(img, d, now, data["usage"], y1)
    blinking = draw_herdr(img, d, data.get("herdr") or {}, SPLIT + 4 if plans_shown(data, plans) else MARGIN, y1)
    return img, blinking


def draw_usage(img, d, now, usage, y1):
    """the usage panel, left of SPLIT: each plan's windows as pixel-block bars"""
    x0, x1 = MARGIN, SPLIT - 4
    d.rectangle((x0, TOP, x1, y1), fill=RAISED, outline=RULE)
    text(img, (x0 + 14, TOP + 10), "TOKENS", O)
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
            if y + 26 > y1:
                break
            used = max(0, min(100, w["used"]))
            text(img, (x0 + 30, y), w["name"][:6], G, scale=1)
            bx = x0 + 90 + meter(d, (x0 + 90, y), used, BLOCKS, BLOCK) + 8
            text(img, (bx + 32, y), f"{round(used)}%", level(used), scale=1, right=True)
            text(img, (bx + 44, y), resets(w.get("resets"), now), G, scale=1)
            y += 26
        y += 10


def draw_herdr(img, d, herdr, x0, y1):
    """herdr's panel, from x0 to the right edge: every workspace, a pixel block per agent -> the blocks that blink"""
    x1 = SCREEN[0] - MARGIN
    columns = WS_COLUMNS if x0 > SPLIT else WS_COLUMNS + 1   # the whole width when there's no usage panel
    d.rectangle((x0, TOP, x1, y1), fill=RAISED, outline=RULE)
    text(img, (x0 + 14, TOP + 10), "WORKSPACES", O)
    agents = [a for ws in herdr.get("items", []) for a in ws["agents"]]
    tally = {}
    for a in agents:
        tally[a["status"]] = tally.get(a["status"], 0) + 1
    x = x1 - 14
    for status, n in sorted(tally.items(), key=lambda kv: -ORDER.get(kv[0], 3)):   # right to left, working ends up first
        if x - len(f"{n} {status}") * 8 < x0 + 14 + 10 * 16 + 24:   # no further than WORKSPACES: the rarest are left out
            break
        x -= text(img, (x, TOP + 18), f"{n} {status}", STATUS.get(status, G), scale=1, right=True) + 24
    if herdr.get("error"):
        text(img, (x0 + 14, TOP + 50), herdr["error"][:110], A, scale=1)
    blinking = []
    col_w = (x1 - x0 - 28) // columns
    shown = [ws for ws in herdr.get("items", []) if ws["agents"]]   # empty workspaces have nothing to say
    fits = (y1 - TOP - 50) // WS_ROW * columns
    for i, ws in enumerate(shown[:fits]):
        wx, wy = x0 + 14 + (i % columns) * col_w, TOP + 50 + (i // columns) * WS_ROW
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
    return blinking


SAMPLE = {"updated": "2026-10-15T03:28:36+00:00",
          "usage": {"error": None, "items": [
              {"label": "Claude", "error": None, "windows": [
                  {"name": "5h", "used": 24.0, "resets": "2026-10-15T07:30:00+00:00"},
                  {"name": "week", "used": 8.0, "resets": "2026-10-20T04:00:00+00:00"},
                  {"name": "Fable", "used": 4.0, "resets": "2026-10-20T04:00:00+00:00"}]},
              {"label": "Claude (team)", "error": None, "windows": [
                  {"name": "5h", "used": 6.0, "resets": "2026-10-15T06:00:00+00:00"},
                  {"name": "week", "used": 55.0, "resets": "2026-10-18T01:00:00+00:00"},
                  {"name": "Fable", "used": 91.0, "resets": "2026-10-18T01:00:00+00:00"}]},
              {"label": "Codex", "error": None, "windows": [{"name": "week", "used": 6.0, "resets": "2026-10-20T14:51:51Z"}]}]},
          "herdr": {"error": None, "items": [
              {"label": "website", "agents": [{"title": "website Next.js", "status": "idle", "agent": "claude"}]},
              {"label": "budget-app", "agents": [{"title": t, "status": "idle", "agent": "claude"} for t in ("app-dev", "app-aux", "app-doc")]},
              {"label": "trip-planner", "agents": [{"title": "trip-dev", "status": "working", "agent": "claude"},
                                                             {"title": "trip-aux", "status": "done", "agent": "claude"},
                                                             {"title": "trip-doc", "status": "idle", "agent": "claude"}]},
              {"label": "game-board", "agents": [{"title": "board-dev", "status": "working", "agent": "claude"}]},
              {"label": "personal", "agents": [{"title": "Kiosk weather and GitHub", "status": "working", "agent": "claude"}]},
              {"label": "desktop", "agents": [{"title": "cad-tools", "status": "blocked", "agent": "claude"}]},
              {"label": "empty", "agents": []}]}}


class Page(Simple):
    """herdr's agents, and the plans' usage if the desktop has it, as a page of the kiosk's cycle"""
    name, seconds, SAMPLE = "agents", 20, SAMPLE

    def __init__(self, feed="~/.cache/kiosk/desk.json", plans="auto"):
        self.file, self.plans, self.lit = feed, plans, []

    def active(self):
        self.load()
        return fresh(self.data)   # skipped while the desktop's away

    def draw(self, img, now, data):
        data = tidy(data)
        picture, blinking = draw(now, data, note(data, now), self.plans)
        img.paste(picture)
        self.lit = [(packed(img.crop((x, y, x + 12, y + 12))), (x, y)) for x, y in blinking]

    def moving(self, now, t, data):
        """working agents blink; with none working, the page stands still"""
        return [(DARK, xy) for _, xy in self.lit] if int(t * 2) % 2 else self.lit



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
    assert tidy(SAMPLE)["usage"]["items"][1]["windows"][2] == {"name": "Fable", "used": 91.0, "resets": "2026-10-18T01:00:00+00:00"}
    assert tidy(None) is None and tidy({"usage": {}}) is None and tidy({"updated": "soon"}) is None, "no readable feed: waiting"
    odd = tidy({"updated": SAMPLE["updated"], "usage": {"items": [{"label": 7, "windows": [{"name": "5h", "used": "12"}, {"used": None}, 3]}, "x"]},
                "herdr": {"items": [{"label": "w", "agents": [{"title": None}, None]}], "error": 4}})
    assert odd["usage"]["items"][0]["windows"] == [{"name": "5h", "used": 12.0, "resets": None}], "a number as text is read, a missing one dropped"
    assert odd["herdr"]["items"][0]["agents"] == [{"title": "", "status": ""}] and odd["herdr"]["error"] == "", "missing fields get defaults"
    assert draw(now, odd)[0].size == SCREEN and draw(now, tidy({"updated": SAMPLE["updated"], "herdr": []}))[0].size == SCREEN
    assert len(draw(now, SAMPLE)[1]) == 3, "each working agent blinks"
    no_plans = dict(SAMPLE, usage=None)
    assert plans_shown(SAMPLE) and not plans_shown(no_plans) and not plans_shown(SAMPLE, "off"), "the usage panel only with usage"
    assert min(x for x, _ in draw(now, no_plans)[1]) < SPLIT and min(x for x, _ in draw(now, SAMPLE, plans="off")[1]) < SPLIT, \
        "without the usage panel, herdr has the whole width"
    assert min(x for x, _ in draw(now, SAMPLE)[1]) > SPLIT, "with it, herdr keeps to the right"
    import tempfile
    path = os.path.join(tempfile.mkdtemp(), "desk.json"); json.dump(SAMPLE, open(path, "w"))
    Page.check()
    page = Page(feed=path)
    key, bg = page.background(now)
    assert bg.mode == "LA" and bg.size == SCREEN and page.background(now)[0] == key, "redrawn only when something changes"
    on, off = page.regions(now, 0.0), page.regions(now, 0.5)
    assert len(on) == 3 and on[0][0].tobytes() != off[0][0].tobytes(), "working agents blink"
    assert TOP + 50 + 3 * 36 + 7 * 26 + 3 * 10 <= SCREEN[1] - 8, "three plans with their windows fit"


def preview(now=None):
    """the page with the sample feed, for the emulator and kiosk.py --png"""
    return draw(now or datetime(2026, 10, 14, 23, 30), SAMPLE, ("desktop · 11:28 PM", D))[0]
