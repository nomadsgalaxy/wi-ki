"""The sports page: every Philadelphia team at once. A column each for the Eagles, Phillies, Flyers, Sixers and
Union, in the team's own colours with its logo in pixels and its record. During a game: the score, both logos, the
period or inning and the clock, and a pulsing LIVE dot (the page's moving part). Otherwise: the next game (who, home or
away, when, on what channel) and how the last one went. Off-season, it says so, and when they're back.

From ESPN's public site API (no key): each team, and its schedule for the last result. It fetches every 10 minutes, and
every 30 seconds while a Philly team is playing or about to, into CACHE, which every renderer shares. A failed fetch
keeps the last one. Needs (for the catalog): site.api.espn.com for the data and a.espncdn.com (ESPN's logo CDN) for the
logos, https only and nothing else. A redirect is checked at every hop, for the data and the logos alike. The logos are
ESPN's, shrunk to pixels once and cached in LOGOS. The teams' colours are ESPN's for each team, and only this page uses
them.
"""
import io, json, os, re, threading, time, urllib.error, urllib.request
from urllib.parse import urlparse
from datetime import datetime, timezone
from PIL import Image, ImageDraw

from kit import SCREEN, text, clock, packed, local

API = "https://site.api.espn.com/apis/site/v2/sports/"
TEAMS = [("football/nfl", "phi", "EAGLES"), ("baseball/mlb", "phi", "PHILLIES"), ("hockey/nhl", "phi", "FLYERS"),
         ("basketball/nba", "phi", "SIXERS"), ("soccer/usa.1", "10739", "UNION")]
CACHE = os.path.expanduser("~/.cache/kiosk/sports.json")
LOGOS = os.path.expanduser("~/.cache/kiosk/logos")
EVERY, LIVE_EVERY = 600, 30
RETRY_LOGO = 600   # a logo that couldn't be had is tried again after this many seconds
LOGO_HOSTS = ("a.espncdn.com",)   # exactly these hosts, no subdomains: what the page needs, nothing else is ever fetched
API_HOSTS = ("site.api.espn.com",)
LOGO_MAX = 1 << 20   # bytes; a team logo is a few KB
LOGO_PIXELS = 1024 * 1024   # decoded size; a 500 x 500 logo is a quarter of it, a tiny PNG can claim 50000 x 50000
LOGO_SIDE = 1024   # and each side, so 2048 x 512 (the same total) doesn't pass
TEAM_KEYS = {"label", "id", "color", "alt", "logo", "record", "next", "last"}
GAME_KEYS = {"when", "state", "detail", "home", "them", "them_logo", "us_score", "them_score", "won", "tv"}
INK, WHITE, SOFT, LIVE = (8, 9, 12), (240, 240, 240), (190, 192, 200), (255, 64, 64)
COL = SCREEN[0] // len(TEAMS)
UA = {"User-Agent": "wi-ki sports (github.com/nomadsgalaxy/wi-ki)"}


def get(url):
    with API_OPENER.open(urllib.request.Request(url, headers=UA), timeout=20) as r:
        return json.load(r)


def hexrgb(h, fallback=(60, 60, 70)):
    try:
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    except (TypeError, ValueError):
        return fallback


def score(c):
    s = c.get("score")
    return s.get("displayValue") if isinstance(s, dict) else s


def game(ev, us):
    """an ESPN event -> {when, state ("pre", "in", "post"), detail, home (are we), them, them_logo, us_score, them_score,
    won, tv}, from our side (us: our team id)"""
    c = ev["competitions"][0]
    st = (c.get("status") or ev.get("status") or {}).get("type", {})
    ours = next((k for k in c["competitors"] if str(k["team"]["id"]) == str(us)), c["competitors"][0])
    them = next((k for k in c["competitors"] if k is not ours), ours)
    tvs = [b for b in c.get("broadcasts", []) if (b.get("type") or {}).get("shortName") == "TV"
           and (b.get("market") or {}).get("type") in ("Home", "National")] or c.get("broadcasts", [])
    logo = (them["team"].get("logos") or [{}])[0].get("href") or them["team"].get("logo")
    return {"when": ev["date"], "state": st.get("state", "pre"), "detail": st.get("shortDetail", ""),
            "home": ours.get("homeAway") == "home", "them": them["team"].get("abbreviation", "?"), "them_logo": logo,
            "us_score": score(ours), "them_score": score(them), "won": ours.get("winner"),
            "tv": ((tvs[0].get("media") or {}).get("shortName") if tvs else None)}


def fetch():
    """every team: its name, colours, logo, record, the game on or next, and the last result"""
    teams = []
    for sport, key, label in TEAMS:
        t = get(f"{API}{sport}/teams/{key}")["team"]
        nxt = (t.get("nextEvent") or [None])[0]
        events = get(f"{API}{sport}/teams/{t['id']}/schedule").get("events", [])
        done = [e for e in events if e["competitions"][0]["status"]["type"].get("completed")]
        teams.append({"label": label, "id": t["id"], "color": t.get("color"), "alt": t.get("alternateColor"),
                      "logo": (t.get("logos") or [{}])[0].get("href"),
                      "record": ((t.get("record") or {}).get("items") or [{}])[0].get("summary", ""),
                      "next": game(nxt, t["id"]) if nxt else None, "last": game(done[-1], t["id"]) if done else None})
    return {"teams": teams, "fetched": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def logo_ok(url, hosts=LOGO_HOSTS):
    """whether a URL is https, on exactly one of the hosts (the logo CDN's, unless said otherwise)"""
    try:
        u = urlparse(url)
        return u.scheme == "https" and u.hostname in hosts
    except (AttributeError, ValueError):
        return False


class OnlyEspn(urllib.request.HTTPRedirectHandler):
    """follows a redirect only to one of its hosts, so nothing off ESPN is ever requested"""
    def __init__(self, hosts):
        self.hosts = hosts

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not logo_ok(newurl, self.hosts):
            raise urllib.error.URLError(f"redirect off ESPN: {newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


OPENER = urllib.request.build_opener(OnlyEspn(LOGO_HOSTS))
API_OPENER = urllib.request.build_opener(OnlyEspn(API_HOSTS))


def small(img):
    """whether a decoded-to-be image is within the bounds (its header only is read): each side and the total"""
    return img.width <= LOGO_SIDE and img.height <= LOGO_SIDE and img.width * img.height <= LOGO_PIXELS


def logo(url, size):
    """a team's logo, shrunk to size x size pixels and cached on disk, RGBA (None if it can't be had)"""
    if not isinstance(url, str) or not logo_ok(url):
        return None
    path = os.path.join(LOGOS, re.sub(r"\W", "_", "-".join(url.rstrip("/").split("/")[-3:]).split(".")[0]) + f"-{size}.png")
    try:
        if not os.path.exists(path):
            with OPENER.open(urllib.request.Request(url, headers=UA), timeout=20) as r:
                raw = r.read(LOGO_MAX + 1)
            if len(raw) > LOGO_MAX:
                return None
            img = Image.open(io.BytesIO(raw))   # the header only: the size is known before the pixels are decoded
            if not small(img):
                return None
            img = img.convert("RGBA"); img.thumbnail((size, size), Image.LANCZOS)
            os.makedirs(LOGOS, exist_ok=True); img.save(path)
        img = Image.open(path)   # a cached file is checked like a fresh one: the disk is no more trusted than the CDN
        return img.convert("RGBA") if small(img) else None
    except Exception:
        return None


def placeholder(label, size):
    """a neutral crest for a team whose logo isn't here: its initials on a grey disc, RGBA"""
    img = Image.new("RGBA", (size, size)); d = ImageDraw.Draw(img)
    d.ellipse((0, 0, size - 1, size - 1), fill=(70, 74, 88), outline=(110, 114, 128), width=max(1, size // 24))
    label = label[:3] or "?"
    scale = max(1, min(size * 3 // 4 // (8 * len(label)), size // 2 // 16))
    text(img, ((size - 8 * scale * len(label)) // 2, (size - 16 * scale) // 2), label, SOFT, scale=scale)
    return img


def aware(iso):
    """an ISO time that carries a zone (local() and the clock sums need one), else ValueError"""
    if datetime.fromisoformat(iso.replace("Z", "+00:00")).tzinfo is None:
        raise ValueError(iso)
    return True


def valid(data):
    """whether a cache file has the shape draw() reads; a stale or damaged one is ignored"""
    try:
        aware(data["fetched"])
        teams = data["teams"]
        assert isinstance(teams, list) and teams
        for t in teams:
            assert TEAM_KEYS <= t.keys() and isinstance(t["label"], str) and isinstance(t["record"], str)
            assert all(t[k] is None or isinstance(t[k], str) for k in ("logo", "color", "alt"))
            for g in (t["next"], t["last"]):
                if g is not None:
                    assert GAME_KEYS <= g.keys() and isinstance(g["them"], str) and isinstance(g["state"], str)
                    assert isinstance(g["detail"], str) and aware(g["when"])
                    assert all(g[k] is None or isinstance(g[k], str) for k in ("them_logo", "tv"))
        return True
    except (KeyError, TypeError, ValueError, AttributeError, AssertionError):
        return False


def when(iso, now):
    """a game's start, short: "7:30p" today, "Sat 1:00p" this week, "Feb 19" further off"""
    t = local(iso.replace("Z", "+00:00"))
    hm = f"{t.hour % 12 or 12}:{t.minute:02d}{'a' if t.hour < 12 else 'p'}"
    days = (t.date() - now.date()).days
    return f"today {hm}" if days == 0 else f"{t:%a} {hm}" if 0 < days < 7 else t.strftime("%b ") + str(t.day)


def pixel(img, size):
    """a logo at a chunky pixel size: shrunk to size // 4, then scaled back up 4x"""
    small = img.resize((max(1, size // 4), max(1, size // 4)), Image.LANCZOS)
    return small.resize((size, size), Image.NEAREST)


def column(now, team, logos):
    """one team's column, RGB COL x SCREEN[1]"""
    colour, alt = hexrgb(team.get("color")), hexrgb(team.get("alt"), (0, 0, 0))
    img = Image.new("RGB", (COL, SCREEN[1]), INK); d = ImageDraw.Draw(img)
    d.rectangle((0, 0, COL, 140), fill=colour); d.rectangle((0, 140, COL, 146), fill=alt)
    mark = logos.get(team.get("logo"))
    if mark:
        d.rounded_rectangle((12, 12, 128, 128), radius=16, fill=WHITE)   # a white tile, so a red P shows on Phillies red
        big = pixel(mark, 100); img.paste(big, (20, 20), big)
    else:
        crest = placeholder(team["label"][:1], 100); img.paste(crest, (20, 20), crest)
    text(img, (140, 34), team["label"], WHITE, scale=3 if len(team["label"]) <= 7 else 2)
    text(img, (140, 90), team.get("record", ""), WHITE, scale=2)
    g, last = team.get("next"), team.get("last")
    y = 168
    if g and g["state"] == "in":   # a game on now
        text(img, (18, y), "LIVE", LIVE, scale=2)
        text(img, (18 + 5 * 16, y), g["detail"][:(COL - 110) // 16], WHITE, scale=2)
        opp = logos.get(g.get("them_logo"))
        for row, (who, pts, mk) in enumerate((("PHI", g["us_score"], mark), (g["them"], g["them_score"], opp))):
            ry = y + 48 + row * 84
            m = pixel(mk, 64) if mk else placeholder(who, 64)
            img.paste(m, (18, ry), m)
            text(img, (96, ry + 16), who, SOFT, scale=2)
            text(img, (COL - 24, ry), str(pts if pts is not None else "-"), WHITE, scale=4, right=True)
        if g.get("tv"):
            text(img, (18, y + 230), g["tv"], SOFT, scale=1)
    elif g and g["state"] == "pre" and g.get("detail") != "TBD" and (local(g["when"].replace("Z", "+00:00")) - now).days < 60:
        text(img, (18, y), "NEXT", SOFT, scale=1)
        opp = logos.get(g.get("them_logo"))
        m = pixel(opp, 64) if opp else placeholder(g["them"], 64)
        img.paste(m, (18, y + 22), m)
        text(img, (96, y + 26), ("vs " if g["home"] else "@ ") + g["them"], WHITE, scale=3)
        text(img, (18, y + 104), when(g["when"], now), WHITE, scale=2)
        if g.get("tv"):
            text(img, (18, y + 140), g["tv"][:(COL - 36) // 8], SOFT, scale=1)
    else:   # the off-season
        text(img, (18, y), "SEASON OVER", WHITE, scale=2)
        if g:
            back = local(g["when"].replace("Z", "+00:00"))
            text(img, (18, y + 40), f"back {back:%b} {back.day}", SOFT, scale=2)
    if last:
        res = "W" if last.get("won") else "L" if last.get("won") is False else "T"
        d.line((18, SCREEN[1] - 76, COL - 18, SCREEN[1] - 76), fill=(40, 42, 50))
        text(img, (18, SCREEN[1] - 62), "LAST", SOFT, scale=1)
        text(img, (18, SCREEN[1] - 42), f"{res} {last['us_score']}-{last['them_score']} " + ("vs " if last["home"] else "@ ") + last["them"],
             (120, 220, 140) if res == "W" else (240, 120, 120) if res == "L" else SOFT, scale=2)
    d.line((COL - 1, 0, COL - 1, SCREEN[1]), fill=INK)
    return img


def draw(now, data, logos):
    img = Image.new("RGB", SCREEN, INK)
    if not data:
        text(img, (40, 200), "asking ESPN...", WHITE, scale=2)
        return img
    for i, team in enumerate(data["teams"][:len(TEAMS)]):
        img.paste(column(now, team, logos), (i * COL, 0))
    text(img, (SCREEN[0] - 12, SCREEN[1] - 14), f"ESPN · {clock(local(data['fetched']))}", (90, 92, 100), scale=1, right=True)
    return img


def live(data):
    """whether a Philly team is playing, or starts within 15 minutes"""
    for t in (data or {}).get("teams", []):
        g = t.get("next")
        if g and (g["state"] == "in" or g["state"] == "pre" and
                  0 <= (datetime.fromisoformat(g["when"].replace("Z", "+00:00")) - datetime.now(timezone.utc)).total_seconds() < 900):
            return True
    return False


class Page:
    """Philadelphia's teams, as a page of the kiosk's cycle"""
    name, seconds = "sports", 20
    fps = 2   # the LIVE dot

    def __init__(self, data=None):
        self.fixed, self.data = data is not None, data
        self.busy, self.mtime, self.logos, self.bg, self.last = False, None, {}, (None, None), None
        self.tried, self.loading, self.missed = 0, False, {}   # when we last asked ESPN; logos in hand; when each missing logo was tried

    def due(self, mtime, ts):
        """whether it's time to ask ESPN: a while since the cache was written or since we last tried, whichever is later,
        so a failed fetch waits its turn instead of retrying every tick (a minute, when there's no data at all)"""
        wait = LIVE_EVERY if live(self.data) else EVERY
        return ts - max(mtime or 0, self.tried) > (wait if self.data else min(wait, 60))

    def fetch(self):
        self.tried = time.time()
        try:
            data = fetch()
            os.makedirs(os.path.dirname(CACHE), exist_ok=True)
            with open(CACHE + ".tmp", "w") as f:
                json.dump(data, f)
            os.replace(CACHE + ".tmp", CACHE)
        except Exception as e:
            print(f"sports: {e}", flush=True)
        self.busy = False

    def load_logos(self):
        urls = {t.get("logo") for t in self.data["teams"]} | {g.get("them_logo") for t in self.data["teams"]
                                                           for g in (t.get("next"), t.get("last")) if g}
        for url in self.pending(urls):
            self.logos[url] = logo(url, 128)
            self.missed[url] = time.time()
        self.loading = False

    def pending(self, urls=None):
        """the logos to fetch: new ones, and ones that failed more than RETRY_LOGO ago"""
        if urls is None:
            urls = {t.get("logo") for t in self.data["teams"]} | {g.get("them_logo") for t in self.data["teams"]
                                                               for g in (t.get("next"), t.get("last")) if g}
        return [u for u in urls if u and (u not in self.logos or self.logos[u] is None and time.time() - self.missed[u] > RETRY_LOGO)]

    def start(self, now):
        pass

    def background(self, now):
        if not self.fixed:
            mtime = os.path.getmtime(CACHE) if os.path.exists(CACHE) else None
            if not self.busy and self.due(mtime, time.time()):
                self.busy = True; threading.Thread(target=self.fetch, daemon=True).start()
            if mtime != self.mtime:
                self.mtime = mtime
                try:
                    with open(CACHE) as f:
                        data = json.load(f)
                    if valid(data):   # else keep the last good one
                        self.data = data
                except (OSError, ValueError):
                    pass
        if self.data and not self.loading and self.pending():
            self.loading = True
            threading.Thread(target=self.load_logos, daemon=True).start()   # logos come in behind
        key = (now.minute, self.mtime, sum(v is not None for v in self.logos.values()))
        if key != self.bg[0]:
            try:
                self.last = draw(now, self.data, self.logos)
            except Exception as e:   # keep the last good frame, marked, instead of freezing the page or the cycle
                print(f"sports: can't draw: {e}", flush=True)
                self.last = (self.last or Image.new("RGB", SCREEN, INK)).copy()
                text(self.last, (SCREEN[0] - 12, 12), "CAN'T DRAW", LIVE, scale=1, right=True)
            self.bg = (key, packed(self.last))
        return self.bg

    def regions(self, now, t):
        """the LIVE dot beside each game that's on, on and off each second"""
        out = []
        for i, team in enumerate((self.data or {}).get("teams", [])):
            if (team.get("next") or {}).get("state") == "in":
                dot = Image.new("RGB", (14, 14), LIVE if int(t) % 2 == 0 else INK)
                out.append((packed(dot), (i * COL + COL - 30, 172)))
        return out


def _ev(state, detail, us, them, won=None, date="2026-10-15T23:30Z"):
    return {"when": date, "state": state, "detail": detail, "home": True, "them": "DET", "them_logo": None,
            "us_score": us, "them_score": them, "won": won, "tv": "NBC Sports Phil"}


SAMPLE = {"teams": [{"label": "EAGLES", "id": "21", "color": "06424d", "alt": "000000", "logo": None, "record": "2-3",
                     "next": _ev("pre", "10/18 - 1:00 PM EDT", None, None, date="2026-10-18T17:00Z"), "last": _ev("post", "Final", "17", "24", False)},
                    {"label": "PHILLIES", "id": "22", "color": "e81828", "alt": "003278", "logo": None, "record": "88-74",
                     "next": _ev("pre", "TBD", None, None, date="2027-02-19T05:00Z"), "last": _ev("post", "Final", "3", "6", False)},
                    {"label": "FLYERS", "id": "15", "color": "fe5823", "alt": "000000", "logo": None, "record": "0-5",
                     "next": _ev("in", "2nd 12:01", "2", "1"), "last": _ev("post", "Final/SO", "2", "3", False)},
                    {"label": "SIXERS", "id": "20", "color": "1d428a", "alt": "e01234", "logo": None, "record": "1-2",
                     "next": _ev("pre", "10/16 - 7:00 PM EDT", None, None, date="2026-10-16T23:00Z"), "last": None},
                    {"label": "UNION", "id": "10739", "color": "051f31", "alt": "b19b69", "logo": None, "record": "13-6-10",
                     "next": _ev("pre", "10/17", None, None, date="2026-10-17T18:30Z"), "last": _ev("post", "FT", "2", "0", True)}],
          "fetched": "2026-10-15T21:40:00+00:00"}


def check():
    global fetch
    now = datetime(2026, 10, 15, 17, 40)
    assert logo_ok("https://a.espncdn.com/i/teamlogos/nfl/500/phi.png") and logo_ok("https://a.espncdn.com/combiner/i?img=/x.png")
    for bad in ("http://a.espncdn.com/x.png", "https://evil.example/x.png", "https://espncdn.com.evil.example/x.png",
                "file:///etc/passwd", "https://notespn.com/x.png", "https://s.espncdn.com/x.png", "https://espn.com/x.png",
                "https://site.api.espn.com/x.png", "", None, 5):
        assert not logo_ok(bad) and logo(bad, 32) is None, bad
    pl = placeholder("PHI", 64)
    assert pl.size == (64, 64) and pl.getpixel((32, 32))[3] == 255 and pl.getpixel((0, 0))[3] == 0, "a crest, not blank"
    assert placeholder("", 64).size == (64, 64) and placeholder("DETROIT", 20).size == (20, 20)
    assert valid(SAMPLE) and not valid(None) and not valid({}) and not valid({"teams": [], "fetched": "2026-10-15T21:40:00+00:00"})
    assert not valid(dict(SAMPLE, teams=[{"label": "X"}])) and not valid(dict(SAMPLE, teams="nope")) and not valid(dict(SAMPLE, fetched="soon"))
    assert not valid(dict(SAMPLE, teams=[dict(SAMPLE["teams"][0], next={"when": "now"})])), "a game missing its fields"
    assert not valid(dict(SAMPLE, teams=[dict(SAMPLE["teams"][0], last=dict(SAMPLE["teams"][0]["last"], when="whenever"))]))
    t0 = SAMPLE["teams"][0]
    for bad in (dict(SAMPLE, fetched="2026-10-15T21:40:00"), dict(SAMPLE, teams=[dict(t0, logo=["x"])]), dict(SAMPLE, teams=[dict(t0, logo={"href": "x"})]),
                dict(SAMPLE, teams=[dict(t0, next=dict(t0["next"], when="2026-10-18T17:00"))]), dict(SAMPLE, teams=[dict(t0, last=dict(t0["last"], them_logo=["x"]))]),
                dict(SAMPLE, teams=[dict(t0, last=dict(t0["last"], tv=["NBC"]))])):
        assert not valid(bad), "a naive time or a list/dict where a string goes would crash draw()"
    import tempfile
    class Reply(io.BytesIO):
        __enter__ = lambda self: self
        __exit__ = lambda self, *a: None
    png = io.BytesIO(); Image.new("RGB", (32, 32), (200, 0, 0)).save(png, "PNG")
    wide = io.BytesIO(); Image.new("L", (2000, 2000)).save(wide, "PNG")
    real_open, real_dir = OPENER.open, LOGOS
    with tempfile.TemporaryDirectory() as tmp:
        globals()["LOGOS"] = tmp
        try:
            OPENER.open = lambda r, timeout=0: Reply(png.getvalue())
            assert logo("https://a.espncdn.com/i/teamlogos/nfl/500/phi.png", 16).size == (16, 16)
            OPENER.open = lambda r, timeout=0: Reply(png.getvalue() + b"0" * LOGO_MAX)
            assert logo("https://a.espncdn.com/i/teamlogos/nfl/500/big.png", 16) is None, "a logo past the size bound"
            OPENER.open = lambda r, timeout=0: Reply(wide.getvalue())
            assert len(wide.getvalue()) < LOGO_MAX and logo("https://a.espncdn.com/i/teamlogos/nfl/500/px.png", 16) is None, "a small file with too many pixels"
            flat = io.BytesIO(); Image.new("L", (2048, 512)).save(flat, "PNG")   # 1,048,576 pixels: the total passes, a side doesn't
            OPENER.open = lambda r, timeout=0: Reply(flat.getvalue())
            assert logo("https://a.espncdn.com/i/teamlogos/nfl/500/flat.png", 16) is None, "a side past its bound"
            OPENER.open = lambda r, timeout=0: Reply(png.getvalue())
            assert logo("https://a.espncdn.com/i/teamlogos/nfl/500/cached.png", 16).size == (16, 16)
            for name in os.listdir(tmp):
                if "cached" in name:
                    Image.new("L", (2048, 512)).save(os.path.join(tmp, name))   # the cached file swapped for a huge one
            OPENER.open = lambda r, timeout=0: 1 / 0   # never reached: it's cached
            assert logo("https://a.espncdn.com/i/teamlogos/nfl/500/cached.png", 16) is None, "a cached logo past its bounds"
        finally:
            OPENER.open = real_open; globals()["LOGOS"] = real_dir
    req = urllib.request.Request("https://a.espncdn.com/x.png")
    hop = lambda to, hosts=LOGO_HOSTS: OnlyEspn(hosts).redirect_request(req, None, 302, "Found", {}, to)
    assert hop("https://a.espncdn.com/y.png").full_url.endswith("/y.png"), "a hop within ESPN is followed"
    for off in ("https://evil.example/x.png", "http://a.espncdn.com/x.png", "http://169.254.169.254/"):
        try:
            hop(off); assert False, off
        except urllib.error.URLError:
            pass   # refused before any request goes out
    assert hop("https://site.api.espn.com/y", API_HOSTS).full_url.endswith("/y")
    for off in ("https://a.espncdn.com/x.png", "https://evil.example/x"):
        try:
            hop(off, API_HOSTS); assert False, off
        except urllib.error.URLError:
            pass   # the data fetch's redirects are checked too, and only to the API's own host
    real_api = API_OPENER.open
    API_OPENER.open = lambda r, timeout=0: Reply(b'{"ok": 1}')
    try:
        assert get(API + "x") == {"ok": 1}, "get() goes through the checked opener"
    finally:
        API_OPENER.open = real_api
    col = column(now, SAMPLE["teams"][0], {})
    assert col.getpixel((50, 222)) != INK and col.getpixel((70, 70)) != hexrgb("06424d"), "no white tile or blank: a crest"
    real_cache = CACHE
    with tempfile.TemporaryDirectory() as tmp:
        globals()["CACHE"] = os.path.join(tmp, "sports.json")
        try:
            pg = Page(data=SAMPLE); pg.fixed, pg.tried = False, time.time()
            for i, body in enumerate((dict(SAMPLE, fetched="2026-10-15T21:41:00+00:00"), {"teams": [{"label": 1}], "fetched": "x"})):
                with open(CACHE, "w") as f:
                    json.dump(body, f)
                os.utime(CACHE, (1000 + i, 1000 + i)); pg.background(now)
                assert pg.data["fetched"] == "2026-10-15T21:41:00+00:00", ("a good file is read", "a bad one is ignored")[i]
        finally:
            globals()["CACHE"] = real_cache
    real_fetch, fetch = fetch, lambda: (_ for _ in ()).throw(OSError("ESPN is down (test)"))
    try:
        late = Page(); late.fetch()
    finally:
        fetch = real_fetch
    assert late.tried > 0 and not late.due(None, late.tried + 30) and late.due(None, late.tried + 61), "a failed fetch backs off"
    keep = Page(data=SAMPLE); keep.fixed = False
    keep.logos = {"https://a.espncdn.com/x.png": None}; keep.missed = {"https://a.espncdn.com/x.png": time.time()}
    assert "https://a.espncdn.com/x.png" not in keep.pending({"https://a.espncdn.com/x.png"}), "a failed logo waits"
    keep.missed["https://a.espncdn.com/x.png"] -= RETRY_LOGO + 1
    assert keep.pending({"https://a.espncdn.com/x.png"}) == ["https://a.espncdn.com/x.png"], "then it is tried again"
    assert draw(now, SAMPLE, {}).size == SCREEN and draw(now, None, {}).size == SCREEN
    assert hexrgb("e81828") == (232, 24, 40) and hexrgb(None) == (60, 60, 70)
    assert when("2026-10-18T17:00Z", now).startswith("Sun ") and when("2027-02-19T05:00Z", now) == "Feb 19"
    assert score({"score": {"displayValue": "2"}}) == "2" and score({"score": "3"}) == "3"
    ev = {"date": "2026-10-13T23:00Z", "competitions": [{"status": {"type": {"state": "post", "shortDetail": "Final/SO"}},
          "competitors": [{"homeAway": "home", "team": {"id": "15", "abbreviation": "PHI"}, "score": {"displayValue": "2"}, "winner": False},
                          {"homeAway": "away", "team": {"id": "25", "abbreviation": "SEA"}, "score": {"displayValue": "3"}, "winner": True}],
          "broadcasts": [{"type": {"shortName": "Streaming"}, "market": {"type": "National"}, "media": {"shortName": "ESPN+"}},
                         {"type": {"shortName": "TV"}, "market": {"type": "Home"}, "media": {"shortName": "NBC Sports Phil"}}]}]}
    g = game(ev, "15")
    assert (g["them"], g["us_score"], g["them_score"], g["won"], g["home"], g["tv"]) == ("SEA", "2", "3", False, True, "NBC Sports Phil")
    page = Page(data=SAMPLE)
    key, bg = page.background(now)
    assert bg.mode == "LA" and page.background(now)[0] == key
    page.data = {"teams": [{"label": None}], "fetched": SAMPLE["fetched"]}   # a shape draw() can't take, past valid()
    key2, bad = page.background(now.replace(minute=41)); page.data = SAMPLE
    assert key2 != key and bad.size == bg.size and bad.tobytes() != bg.tobytes(), "a failed draw keeps the last frame, marked"
    marked = Page(data={"teams": [{"label": None}], "fetched": SAMPLE["fetched"]})
    assert marked.background(now)[1].size == bg.size, "and with no frame yet, a blank one"
    on, off = page.regions(now, 0), page.regions(now, 1)
    assert len(on) == 1 and on[0][1] == off[0][1] and on[0][0].tobytes() != off[0][0].tobytes(), "the Flyers' LIVE dot blinks"


def preview(now=None):
    """the sample, the Flyers mid-game, for the emulator and kiosk.py --png"""
    import kit
    return kit.unpack(Page(data=SAMPLE).background(now or datetime(2026, 10, 15, 17, 40))[1])
