"""The Half-Life 3 page: is it out yet? Dressed as Half-Life: the Lambda in its ring, the answer in the HEV suit's HUD
amber, the HUD's panels along the bottom (health, suit, and the days since Half-Life 2: Episode Two, 10 October 2007,
counted like ammo), a crowbar, a headcrab, and Black Mesa's hazard stripes.

It really checks: once an hour, in a background thread, it searches the Steam store (no key) for a game called exactly
"Half-Life 3", and when one turns up it asks the store whether it's out or only coming soon. YES only once it's out.
A coming-soon listing is still NO, and the HEV says it's listed. The answer goes in CACHE, so a restart doesn't forget
it, and a failed search keeps the last answer. The colours are Half-Life's, and only this page uses them.
"""
import json, math, os, threading, time, urllib.parse, urllib.request
from datetime import date, datetime
from PIL import Image, ImageChops, ImageDraw

from kit import SCREEN, W, text, clock, packed, since

EPISODE_TWO = date(2007, 10, 10)
SINCE = "since 10 Oct 2007"
NAMES = {"half-life 3", "half life 3", "half-life: 3"}   # what counts as the real thing; mods and chapters "3" don't
SEARCH = "https://store.steampowered.com/api/storesearch/?" + urllib.parse.urlencode({"term": "half-life 3", "cc": "us", "l": "english"})
DETAILS = "https://store.steampowered.com/api/appdetails?appids={}&cc=us&l=english"   # whether a listing is out yet
CACHE = os.path.expanduser("~/.cache/kiosk/halflife3.json")
EVERY = 3600
UA = {"User-Agent": "wi-ki (github.com/nomadsgalaxy/wi-ki)"}


def listed(found):
    """Steam's search results -> the Half-Life 3 among them, or None"""
    items = found.get("items") if isinstance(found, dict) else None
    return next((i for i in items if isinstance(i, dict) and str(i.get("name", "")).strip().lower() in NAMES), None) \
        if isinstance(items, list) else None


def out_now(details, app):
    """Steam's app details -> whether that listing is actually out (not coming soon); unsure is no"""
    try:
        got = details[str(app)]
        return bool(got["success"]) and got["data"]["release_date"]["coming_soon"] is False
    except (KeyError, TypeError):
        return False


def valid(answer):
    """the cached answer if it's the shape this page writes, else None (a bad cache is the same as no cache)"""
    try:
        datetime.fromisoformat(answer["checked"])
        ok = isinstance(answer["released"], bool) and isinstance(answer.get("listed", False), bool) and isinstance(answer["name"], str)
        return answer if ok else None
    except (KeyError, TypeError, ValueError):
        return None


HUD, HUD_DIM, PANEL = (255, 176, 0), (150, 100, 0), (34, 26, 8)   # the HEV suit's amber, dimmed, and its panels
OK, OK_DIM, OK_PANEL = (74, 222, 128), (40, 130, 70), (8, 34, 18)  # the day it's out, the HUD goes green
LAMBDA, HAZARD, DARK = (255, 112, 0), (232, 184, 0), (10, 10, 12)
WALL, SEAM, FLOOR, RAIL = (18, 19, 23), (30, 32, 38), (24, 22, 19), (62, 62, 70)   # a Black Mesa test chamber, dim
RUST, IRON = (178, 34, 22), (96, 34, 26)
FPS = 4
RING = (0, 40, 380, 420)             # the Lambda's tile: its ring, the glow behind it and the trace going round it
STRIP = (940, 306, 1340, 499)       # where the headcrab hops
STATUS = (400, 270, 1330, 304)       # the HEV's line, typed out
START = 34   # where the crab sits on the left: clear of the crowbar's claw
GLOW, HOP, TYPE, HOLD = 16, 48, 4, 10   # frames: a glow-and-trace loop (4 s), a hop there and back (12 s); chars a frame


def crowbar():
    """Gordon's crowbar standing on the floor, 14x28 pixels, RGBA: the claw at the foot, the bar, the hook at the top
    curving toward the wall it leans on"""
    img = Image.new("RGBA", (14, 28)); d = ImageDraw.Draw(img)
    d.line((8, 6, 8, 25), fill=RUST, width=3)                                              # the bar
    d.line((8, 6, 8, 3), fill=RUST, width=3); d.line((8, 2, 3, 2), fill=RUST, width=3); d.line((3, 2, 3, 6), fill=RUST, width=3)   # the hook
    d.line((8, 27, 12, 27), fill=IRON, width=2); d.line((12, 27, 13, 23), fill=IRON, width=2)   # the claw, on the floor
    d.line((7, 8, 7, 22), fill=(232, 84, 60))                                              # a glint
    return img


SW, SH, MARGIN, K, Q = 84, 50, 3, 1.35, 4   # a crab sprite in art pixels, and the clear rows kept below its lowest claw (so no foot touches the hazard stripe)
# each pose: the body's tilt in degrees (negative is nose up), where its centre sits, and its legs as points in the body's own
# frame (x forward, y down): the two long hooked front legs (far one first), then the two shorter rear ones
POSES = {
    "crouch": (0, (36, 27), (((5, 4), (12, -4), (21, -2), (27, 6), (25, 10)), ((7, 5), (15, -1), (24, 2), (30, 9), (28, 12))),
                            (((-5, 4), (-11, -3), (-17, 3), (-19, 10), (-16, 10)), ((-7, 5), (-14, 0), (-20, 6), (-22, 12), (-19, 12)))),
    "launch": (-22, (36, 21), (((5, 4), (12, -2), (20, -5), (26, 0), (24, 4)), ((7, 5), (15, 1), (23, -1), (29, 5), (27, 9))),
                              (((-5, 4), (-9, 5), (-13, 6), (-17, 6), (-15, 8)), ((-7, 5), (-11, 6), (-15, 8), (-19, 8), (-17, 10)))),
    "apex": (-6, (35, 23), (((5, 4), (14, -7), (23, -9), (30, -3), (28, 1)), ((7, 5), (16, -3), (25, -4), (32, 3), (30, 7))),
                           (((-5, 4), (-12, 0), (-18, 2), (-22, 8), (-19, 8)), ((-7, 5), (-13, 3), (-19, 7), (-22, 13), (-19, 13)))),
    "land": (10, (36, 18), (((5, 4), (13, 1), (21, 6), (24, 12), (21, 13)), ((7, 5), (16, 4), (23, 9), (26, 15), (23, 16))),
                           (((-5, 4), (-10, 1), (-15, -2), (-19, 0), (-17, 2)), ((-7, 5), (-12, 2), (-17, -1), (-21, 2), (-19, 4)))),
}


def headcrab(pose="apex"):
    """a headcrab from the side, SWxSH pixels, RGBA, facing right in mid-leap: a pale cream dome lit from above with the
    belly and beak underneath, the body tilted, two long hooked legs reaching forward and two shorter ones trailing.
    pose is crouch (sitting), launch, apex or land."""
    skin, light, shade, deep, line = (226, 200, 160), (248, 232, 202), (190, 156, 120), (150, 112, 84), (74, 48, 36)
    claw, mouth, lip = (60, 38, 30), (36, 14, 18), (176, 112, 96)
    big = Image.new("RGBA", (SW * Q, SH * Q), line + (0,)); d = ImageDraw.Draw(big)   # drawn Q times too big, then shrunk with hard edges
    tilt, (cx, cy), front, rear = POSES[pose]
    s, c = math.sin(math.radians(tilt)), math.cos(math.radians(tilt))
    at = lambda p: (Q * (cx + K * (p[0] * c - p[1] * s)), Q * (cy + K * (p[0] * s + p[1] * c)))   # a point in the body's frame -> the big sprite's
    def leg(pts, tone):
        pts = [at(p) for p in pts]
        for grow, col in ((1.2, line), (0, tone)):   # an outline, then the leg: round at every joint, thick at the hip, thin at the hook
            for (p, q), w in zip(zip(pts, pts[1:]), (6, 5, 4, 2)):
                r = (w / 2 + grow) * Q
                d.line((*p, *q), fill=col, width=round(2 * r))
                for x, y in (p, q):
                    d.ellipse((x - r, y - r, x + r, y + r), fill=col)
        d.line([((pts[2][0] + pts[3][0]) / 2, (pts[2][1] + pts[3][1]) / 2), *pts[3:]], fill=claw, width=Q * 2, joint="curve")   # the hook, dark
    for pts in (front[0], rear[0]):   # the far legs, in shade, behind
        leg(pts, shade)
    belly = [(16 * math.cos(t / 20 * math.pi), (-12 if t < 20 else -8) * math.sin(t / 20 * math.pi)) for t in range(41)]
    d.polygon([at(p) for p in belly], fill=line)
    inner = [(p[0] * 0.92, p[1] * 0.9) for p in belly]
    d.polygon([at(p) for p in inner], fill=skin)
    d.polygon([at(p) for p in inner if p[1] > 1], fill=shade)                             # the shaded underside
    lx, ly = at((-3, -6)); d.ellipse((lx - 6 * Q, ly - 3 * Q, lx + 6 * Q, ly + 2.5 * Q), fill=light)   # the light from above
    for dot in ((-5, -1), (2, -2), (8, -4), (-9, 1)):                                     # the bumps in its skin
        x, y = at(dot); d.ellipse((x - Q, y - Q, x + Q, y + Q), fill=deep)
    for pts in (front[1], rear[1]):   # the near legs
        leg(pts, skin)
        d.line([at(p) for p in pts[:2]], fill=light, width=Q)
    mx, my = at((15, 1)); d.ellipse((mx - 4 * Q, my - 2.8 * Q, mx + 4 * Q, my + 2.8 * Q), fill=mouth)   # the maw under the front of the dome
    for dx in (-2, 2):
        x, y = at((15 + dx, 0)); d.ellipse((x - Q, y - Q, x + Q, y + Q), fill=lip)         # its lips
    img = big.resize((SW, SH), Image.BOX)
    img.putalpha(img.getchannel("A").point(lambda a: 255 if a > 127 else 0))
    return img


CRABS = {pose: headcrab(pose).resize((SW * 3, SH * 3), Image.NEAREST) for pose in POSES}   # 3 screen pixels to an art pixel


def colours(out):
    return (OK, OK_DIM, OK_PANEL) if out else (HUD, HUD_DIM, PANEL)


def panel(img, box, label, value, scale, out, icon=False):
    """an HL2 HUD panel: a dark box, the label small, the number big (and the health cross, if icon)"""
    hud, dim, back = colours(out)
    d = ImageDraw.Draw(img); d.rectangle(box, fill=back)
    text(img, (box[0] + 16, box[1] + 12), label, dim, scale=2)
    x = box[0] + 16
    if icon:   # the HUD's health cross
        cx, cy = x + 22, box[1] + 44 + 8 * scale
        d.rectangle((cx - 8, cy - 22, cx + 8, cy + 22), fill=hud); d.rectangle((cx - 22, cy - 8, cx + 22, cy + 8), fill=hud)
        x += 60
    text(img, (x, box[1] + 44), value, hud, scale=scale)


def scene(now, answer):
    """everything that stands still, RGB: the chamber, the question and answer, the crowbar and the HUD"""
    img = Image.new("RGB", SCREEN, WALL); d = ImageDraw.Draw(img)
    out = bool(answer and answer["released"])
    hud, dim, back = colours(out)
    floor = SCREEN[1] - 16
    for sx in range(0, SCREEN[0], 160):   # the chamber's wall panels, and the floor with the tram rail along it
        d.line((sx, 0, sx, floor - 70), fill=SEAM, width=2)
    d.line((0, 250, SCREEN[0], 250), fill=SEAM, width=2)
    d.rectangle((0, floor - 70, SCREEN[0], floor), fill=FLOOR)
    for sx in range(0, SCREEN[0], 40):
        d.rectangle((sx, floor - 26, sx + 18, floor - 4), fill=(36, 32, 26))
    d.line((0, floor - 22, SCREEN[0], floor - 22), fill=RAIL, width=3); d.line((0, floor - 8, SCREEN[0], floor - 8), fill=RAIL, width=3)
    # the question and the answer
    x = 400
    text(img, (x, 34), "IS HALF-LIFE 3 OUT YET?", hud, scale=3)
    text(img, (x + 4, 104), "YES." if out else "NO.", dim, scale=13)   # a shadow, like the HUD's glow
    text(img, (x, 100), "YES." if out else "NO.", hud, scale=13)
    bar = crowbar().resize((14 * 4, 28 * 4), Image.NEAREST); img.paste(bar, (x + 510 + 2, floor - 8 - bar.height), bar)   # leans on the SUIT panel, its claw on the floor
    text(img, (SCREEN[0] - 28, 34), '"Rise and shine, Mr. Freeman."', dim, scale=2, right=True)
    checked = f"Steam checked {clock(datetime.fromisoformat(answer['checked']))}" if answer else "checking Steam..."
    text(img, (SCREEN[0] - 28, 70), checked, dim, scale=1, right=True)
    # the HUD: health with its cross and suit, bottom left; the wait as ammo, bottom right (the clip, then the reserve)
    days = (now.date() - EPISODE_TWO).days
    y0, y1 = 362, floor - 12
    panel(img, (x, y0, x + 290, y1), "HEALTH", "100", 4, out, icon=True)
    panel(img, (x + 310, y0, x + 510, y1), "SUIT", "0", 4, out)
    ammo = (1360, 120, SCREEN[0] - 28, y1)
    d.rectangle(ammo, fill=back)
    text(img, (ammo[0] + 20, ammo[1] + 16), "DAYS SINCE EPISODE TWO", dim, scale=2)
    text(img, (ammo[0] + 20, ammo[1] + 64), f"{days:,}", hud, scale=8)
    text(img, (ammo[0] + 20, ammo[1] + 64 + 16 * 8 + 24), SINCE, dim, scale=2)
    text(img, (ammo[0] + 20, ammo[1] + 64 + 16 * 8 + 60), since(EPISODE_TWO, now.date()), hud, scale=2)
    # Black Mesa's hazard stripes
    d.rectangle((0, floor, SCREEN[0], SCREEN[1]), fill=HAZARD)
    for sx in range(-40, SCREEN[0], 48):
        d.polygon([(sx, SCREEN[1]), (sx + 24, SCREEN[1]), (sx + 40, floor), (sx + 16, floor)], fill=DARK)
    return img


def lambda_tile(base, k, out):
    """the Lambda's tile, frame k of GLOW: the resonance glow behind it breathing, a bright trace going round the ring"""
    img = base.crop(RING); d = ImageDraw.Draw(img)
    ox, oy = RING[0], RING[1]
    cx, cy, r = 190 - ox, 230 - oy, 150
    g = 0.5 + 0.5 * math.sin(2 * math.pi * k / GLOW)   # one slow breath every 4 s
    for grow, f in ((34, 0.45), (20, 0.75)):
        d.ellipse((cx - r - grow, cy - r - grow, cx + r + grow, cy + r + grow), fill=(round(8 * f), round((34 + 30 * g) * f), round(14 * f)))
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=DARK)
    d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=OK if out else LAMBDA, width=18)
    a = 360 * k / GLOW - 90
    d.arc((cx - r, cy - r, cx + r, cy + r), a, a + 40, fill=(255, 214, 140) if not out else (190, 255, 210), width=18)
    w, c = 26, OK if out else LAMBDA   # the Lambda: the hook at the top, the long stroke down to the right, the short leg
    d.line((cx - 78, cy - 92, cx - 34, cy - 92), fill=c, width=w)
    d.line((cx - 44, cy - 98, cx + 62, cy + 92), fill=c, width=w)
    d.line((cx + 50, cy + 92, cx + 92, cy + 92), fill=c, width=w)
    d.line((cx + 2, cy - 14, cx - 70, cy + 98), fill=c, width=w)
    return img


def leap(k, sw, sh):
    """where the crab is in frame k of HOP: (pose, x, y, heading back). Each half sits, then leaps for 8 frames and lands on
    the floor at the far end on the last one (p=1), so the loop has no snap; sw and sh are how far it can go across and up"""
    half, hop = HOP // 2, 8
    i = k % half; there = k >= half
    p = max(0.0, (i - (half - hop - 1)) / hop)   # 0 sitting, then how far through the leap: 1/8 ... 8/8 over the last 8 frames
    pose = "crouch" if p in (0, 1) else "launch" if p < 0.3 else "apex" if p < 0.6 else "land"
    u = 1 - p if there else p               # how far across: 0 at the start, 1 at the far end
    return pose, round(START + u * (sw - START - 4)), round(sh - math.sin(math.pi * p) * sh), there


def crab_tile(base, k, out):
    """the headcrab's strip, frame k of HOP: it sits, then leaps across (launch, apex, land) and sits, and leaps back. The
    day it's out, it lies on its back and gives up."""
    img = base.crop(STRIP)
    crouch = CRABS["crouch"]
    sw, sh = img.width - crouch.width, img.height - crouch.height   # sh is also the most it rises: the real hop height
    if out:
        crab = crouch.transpose(Image.FLIP_TOP_BOTTOM); img.paste(crab, (sw // 2, img.height - 3 * MARGIN - crab.getbbox()[3]), crab); return img   # its back on the floor, same line as the crowbar
    pose, x, y, there = leap(k, sw, sh)
    crab = CRABS[pose] if not there else CRABS[pose].transpose(Image.FLIP_LEFT_RIGHT)
    img.paste(crab, (x, y), crab)
    return img


def lines(now, answer):
    """what the HEV suit says, in turn"""
    if answer and answer["released"]:
        return ["HEV: Half-Life 3 detected on Steam.", "HEV: Have a very safe day."]
    days = (now.date() - EPISODE_TWO).days
    found = "Half-Life 3 listed, coming soon." if answer and answer.get("listed") else "no Half-Life 3 found."
    return [f"HEV: Checking Steam store... {found}", "HEV: Morphine administered.",
            f"HEV: {days:,} days since Episode Two.", "HEV: Vital signs nominal. Still waiting."]


def status_tile(base, line, n, out):
    """the HEV's line, its first n characters typed, with a block cursor after them"""
    img = base.crop(STATUS); hud, dim, _ = colours(out)
    text(img, (0, 0), line[:n], hud, scale=2)
    if n < len(line):
        ImageDraw.Draw(img).rectangle((n * 16, 2, n * 16 + 12, 30), fill=dim)
    return img


def typing(said):
    """[(line index, characters shown)] for one full turn of the lines: typed TYPE a frame, then held HOLD frames"""
    out = []
    for i, line in enumerate(said):
        out += [(i, min(len(line), n)) for n in range(0, len(line) + TYPE, TYPE)] + [(i, len(line))] * HOLD
    return out


def draw(now, answer):
    """the whole page, still, RGB at the screen's size: the first frame of everything that moves"""
    img = scene(now, answer); out = bool(answer and answer["released"])
    img.paste(lambda_tile(img, 0, out), RING[:2]); img.paste(crab_tile(img, 0, out), STRIP[:2])
    said = lines(now, answer)
    img.paste(status_tile(img, said[0], len(said[0]), out), STATUS[:2])
    return img


class Page:
    """the question, as a page of the kiosk's cycle"""
    name, seconds, fps = "halflife3", 15, FPS

    def __init__(self, answer=None):
        self.fixed = answer is not None   # given an answer (the self-test), it never searches
        try:
            self.answer = valid(answer or json.load(open(CACHE)))
        except (OSError, ValueError):
            self.answer = None
        self.asked, self.bg = 0.0, (None, None)

    def ask(self):
        try:
            get = lambda url: json.load(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=15))
            hit = listed(get(SEARCH))
            out = bool(hit) and out_now(get(DETAILS.format(int(hit["id"]))), hit["id"])
            self.answer = {"released": out, "listed": bool(hit), "name": str(hit["name"]) if hit else "",
                           "checked": datetime.now().isoformat(timespec="minutes")}
            os.makedirs(os.path.dirname(CACHE), exist_ok=True)
            with open(CACHE + ".tmp", "w") as f:
                json.dump(self.answer, f)
            os.replace(CACHE + ".tmp", CACHE)
        except Exception:
            pass   # keep the last answer; try again in an hour

    def start(self, now):
        if not self.fixed and time.time() - self.asked > EVERY:
            self.asked = time.time(); threading.Thread(target=self.ask, daemon=True).start()

    def background(self, now):
        key = (now.date(), json.dumps(self.answer, sort_keys=True))
        if key != self.bg[0]:
            base, out = scene(now, self.answer), bool(self.answer and self.answer.get("released"))
            self.lambdas = [packed(lambda_tile(base, k, out)) for k in range(GLOW)]   # made once a day; drawn every frame
            self.crabs = [packed(crab_tile(base, k, out)) for k in range(HOP)]
            self.said, self.base, self.out = lines(now, self.answer), base, out
            self.typed, self.status = typing(self.said), {}
            self.bg = (key, packed(draw(now, self.answer)))
        return self.bg

    def regions(self, now, t):
        f = int(t * FPS)
        i, n = self.typed[f % len(self.typed)]
        if (i, n) not in self.status:
            self.status[(i, n)] = packed(status_tile(self.base, self.said[i], n, self.out))
        return [(self.lambdas[f % GLOW], RING[:2]), (self.crabs[f % HOP], STRIP[:2]), (self.status[(i, n)], STATUS[:2])]


def check():
    hl2 = {"items": [{"id": 670870, "name": "Half-Life: A Place in the West - Chapter 3"}, {"id": 220, "name": "Half-Life 2"}]}
    assert listed(hl2) is None and listed({}) is None, "a chapter 3 or a Half-Life 2 isn't it"
    assert listed({"items": [{"id": 1, "name": "Half-Life 3"}]})["id"] == 1
    assert listed({"items": 1}) is None and listed([]) is None and listed({"items": [1, None]}) is None, "odd answers are no"
    soon = {"1": {"success": True, "data": {"release_date": {"coming_soon": True, "date": "Coming soon"}}}}
    out = {"1": {"success": True, "data": {"release_date": {"coming_soon": False, "date": "1 Apr, 2027"}}}}
    assert not out_now(soon, 1) and out_now(out, 1), "listed but coming soon isn't out; released is"
    assert not out_now({}, 1) and not out_now({"1": {"success": False}}, 1) and not out_now(None, 1), "unsure is no"
    good = {"released": False, "listed": True, "name": "Half-Life 3", "checked": "2026-10-15T15:00"}
    assert valid(good) == good and valid({"released": False, "name": "", "checked": "2026-10-15T15:00"})
    for bad in (None, [], {"released": "yes", "name": "", "checked": "2026-10-15T15:00"}, {"released": False, "name": "", "checked": "soon"},
                {"released": False, "checked": "2026-10-15T15:00"}, {"released": False, "name": 3, "checked": "2026-10-15T15:00"}):
        assert valid(bad) is None, f"a cache like {bad!r} is ignored"
    listing = Page(good); listing.background(datetime(2026, 10, 15, 16, 0))
    assert "coming soon" in listing.said[0] and not listing.out, "a coming-soon listing says so, and is still NO"
    now = datetime(2026, 10, 15, 16, 0)
    assert (now.date() - EPISODE_TWO).days == 6945 and since(EPISODE_TWO, now.date()) == "19 years, 5 days"
    assert since(date(2007, 10, 10), date(2008, 10, 10)) == "1 year" and since(date(2007, 12, 20), date(2008, 1, 5)) == "16 days"
    for answer in (None, {"released": False, "name": "", "checked": "2026-10-15T15:00"},
                   {"released": True, "name": "Half-Life 3", "checked": "2026-10-15T15:00"}):
        assert draw(now, answer).size == SCREEN, "draws before the first check, with no, and with yes"
    assert CRABS["apex"].width < STRIP[2] - STRIP[0] and CRABS["apex"].height + 30 < STRIP[3] - STRIP[1], "the crab fits its strip with room to hop"
    page = Page({"released": False, "name": "", "checked": "2026-10-15T15:00"})
    key, bg = page.background(now)
    assert bg.mode == "LA" and page.background(now)[0] == key, "redrawn only when something changes"
    seen = [[im.tobytes() for im, _ in page.regions(now, f / FPS)] for f in range(HOP)]
    for part in range(3):
        assert len({frame[part] for frame in seen}) > 1, f"region {part} moves"
    for im, (x, y) in page.regions(now, 0):
        assert x + im.width <= SCREEN[0] and y + im.height <= SCREEN[1]
    assert seen[0][0] == seen[GLOW][0] and seen[0][1] == page.regions(now, HOP / FPS)[1][0].tobytes(), "the glow and the hop loop"
    # no flashing: from one frame to the next, the glow behind the Lambda changes by a few levels at most
    tiles = [lambda_tile(scene(now, None), k, False).getpixel((10, 190)) for k in range(GLOW)]
    assert max(abs(a[1] - b[1]) for a, b in zip(tiles, tiles[1:] + tiles[:1])) <= 6, tiles
    assert all(n <= len(page.said[i]) for i, n in page.typed) and page.typed[-1] == (len(page.said) - 1, len(page.said[-1]))
    assert crab_tile(page.base, 0, False).tobytes() != crab_tile(page.base, HOP // 2 + 7, False).tobytes()
    base = scene(now, None)
    feet = [y for y in range(SCREEN[1]) for x in range(900, 1000) if base.getpixel((x, y)) == IRON]
    assert feet and SCREEN[1] - 16 - 16 <= max(feet) < SCREEN[1] - 16, "the crowbar's claw is on the floor, not floating"
    # the crab: side-on and directional, its feet clear of the stripe and the crowbar's claw, and it really leaps
    assert len({im.tobytes() for im in CRABS.values()}) == len(POSES) == 4, "a pose each for sitting, launch, apex and landing"
    for name, (_, _, front, rear) in POSES.items():
        reach = lambda legs: min(math.dist(leg[0], leg[3]) for leg in legs)
        assert reach(front) > reach(rear) + 4, f"{name}: the front legs reach further than the trailing ones"
        assert CRABS[name].getbbox()[3] <= CRABS[name].height - 3 * MARGIN, f"{name}: a clear margin under the lowest claw"
    strip = base.crop(STRIP)
    claw_px = lambda im: sum(px[:3] == IRON for px in im.getdata())
    drawn = [ImageChops.difference(crab_tile(base, k, False).convert("RGB"), strip.convert("RGB")).getbbox() for k in range(HOP)]
    assert all(box[3] <= strip.height - 8 for box in drawn), "every foot is at least 8 px above the hazard stripe"
    assert all(claw_px(crab_tile(base, k, False)) == claw_px(strip) > 0 for k in range(HOP)), "the crab never covers the crowbar's claw"
    assert drawn[0][1] - min(box[1] for box in drawn) >= 50, "its top rises at least 50 px from where it sits: the leap is real"
    # the frame sequence: one continuous path, and it lands on the floor at p=1, with no jump at 23->24 or 47->0
    sw, sh = STRIP[2] - STRIP[0] - CRABS["crouch"].width, STRIP[3] - STRIP[1] - CRABS["crouch"].height
    path = [leap(k, sw, sh) for k in range(HOP)]
    for k in range(HOP):
        a, b = path[k], path[(k + 1) % HOP]
        assert abs(a[1] - b[1]) <= 14 and abs(a[2] - b[2]) <= 17, f"frame {k}->{k + 1} moves smoothly: {a} {b}"
    for k in (HOP // 2 - 1, HOP - 1):
        assert path[k][0] == "crouch" and path[k][2] == sh and path[k][1:3] == path[(k + 1) % HOP][1:3], "it has landed on the floor by the last frame of a leap"
    assert {path[k][2] for k in range(HOP // 2 - 8, HOP // 2 - 1)} != {sh}, "and the leap before it is in the air"
    assert "10 Oct 2007" in SINCE, "the reserve says what 2007 is"
    yes = Page({"released": True, "name": "Half-Life 3", "checked": "2026-10-15T15:00"}); yes.background(now)
    assert "detected" in yes.said[0] and len({c.tobytes() for c in yes.crabs}) == 1, "out: it says so, and the crab gives up"
    lying = crab_tile(base, 0, True).convert("RGB"); gap = ImageChops.difference(lying, strip.convert("RGB")).getbbox()[3]
    assert strip.height - 12 < gap <= strip.height - 8, "on its back it rests on the floor line, not floating or in the stripe"


def preview(now=None):
    """the page as it's been since 2007, for the emulator and kiosk.py --png"""
    import kit
    page = Page({"released": False, "name": "", "checked": "2026-10-15T15:00"})
    return kit.unpack(page.background(now or datetime(2026, 10, 15, 16, 0))[1])
