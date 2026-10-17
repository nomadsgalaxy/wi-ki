"""The Around Hive76 page: the blocks around the space, from the City of Philadelphia's open data and Indego. A map of
the streets around Hive76 (1821 E. Hagert St., Kensington) on the left, and on the right whichever view is up:

  all        the overview: this week's 311 reports, the month's building permits, the nearest Indego bikes
  reports    the 311 reports within RADIUS this week, newest first: when, what, where, open or closed
  building   the L&I permits within RADIUS this month, newest first: when, what kind, the work, where
  bikes      the nearest Indego stations: bikes, e-bikes, open docks, and how far a walk

The map shows the view's things: 311 reports as orange dots, permits as light blue squares, Indego stations with their
bikes, Hive76 as an orange hexagon. Touch a tab along the top to change the view (see kiosk.py's touch); with nobody
touching, it goes back to its own view after a while. A screen without touch just shows the page's own view, so list
the views as pages of their own as well: {"page": "around", "name": "bikes", "options": {"view": "bikes"}}.

Data: 311 and permits come from the city's Carto SQL API (phl.carto.com, no key) every 15 minutes, Indego's live station
feed (GBFS, no key) every minute, and the streets from OpenStreetMap's Overpass API once, cached on disk. Everything
goes in caches every renderer shares, and a failed fetch keeps the last one. Hive76's own colours, and only this page
uses them.

Options (in playlist.json): view (default all); lat, lon, the middle (default Hive76); radius, in metres (default 1000).
Another city's: place and area, for the title and the spot in the middle (default HIVE76 and Kensington); bikes, its
bike share's GBFS feed, the folder with station_information.json in it, or null for none (default Indego's), and
bike_share, its name; reports, "phl-carto", the address of an Open311 GeoReport v2 server (its open311/v2 folder,
the standard most cities' 311 systems publish), or null; permits, "phl-carto" or null. Streets come from OpenStreetMap
anywhere. A city with none of the rest still gets the map.
"""
import json, math, os, threading, time, urllib.parse, urllib.request, zlib
from datetime import datetime, timedelta, timezone
from PIL import Image, ImageDraw

from kit import SCREEN, A, text, clock, packed, local, freshness

ORANGE, WHITE, GREY, DARK, BLUE, LIGHT = (246, 145, 31), (235, 235, 235), (170, 170, 170), (85, 85, 85), (60, 120, 255), (120, 200, 255)
BG, RULE, PANEL = (12, 14, 20), (40, 44, 56), (22, 25, 34)
ROAD_MAJOR, ROAD, RAIL = (78, 84, 104), (40, 44, 58), (104, 64, 26)
HIVE76 = (39.986727, -75.130526)
CARTO = "https://phl.carto.com/api/v2/sql"
INDEGO = "https://gbfs.bcycle.com/bcycle_indego/"
OVERPASS = ("https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter")
CACHE = os.path.expanduser("~/.cache/kiosk/around-{lat}_{lon}_{radius}{src}.json")   # 311 and permits, for one middle,
BIKES = os.path.expanduser("~/.cache/kiosk/around-bikes-{lat}_{lon}{src}.json")      # radius and source; the bikes too
PHL = "phl-carto"   # the City of Philadelphia's own data, for reports and permits
STREETS = os.path.expanduser("~/.cache/kiosk/around-streets-{lat}_{lon}.json")
EVERY, BIKES_EVERY, IDLE = 900, 60, 30   # seconds: city data, bikes, and how long a touched view stays before going back
RETRY = 600                               # seconds before a fetch that failed is tried again (a success waits its EVERY)
STALE_CITY, STALE_BIKES = 3600, 600       # seconds: older than this and the corner says so
UA = {"User-Agent": "wi-ki around (github.com/nomadsgalaxy/wi-ki)"}
VIEWS = [("all", "OVERVIEW"), ("reports", "311"), ("building", "BUILDING"), ("bikes", "BIKES")]
MAP_W, PIX = 840, 2                       # the map: the left of the screen, drawn at half size and scaled up
TAB_X, TAB_Y, TAB_W, TAB_H = 1192, 10, 170, 44
X0 = MAP_W + 28                           # where the right side starts


def get(url, data=None, timeout=30):
    with urllib.request.urlopen(urllib.request.Request(url, data, UA), timeout=timeout) as r:
        return json.load(r)


def carto(sql):
    return get(CARTO + "?" + urllib.parse.urlencode({"q": sql}), timeout=60)["rows"]


def fetch_city(lat, lon, radius, reports=PHL, permits=PHL):
    """this week's 311 reports and this month's permits within radius metres, newest first, from wherever the page was
    told: Philadelphia's own data, an Open311 server for the reports, or nothing"""
    lat, lon = float(lat), float(lon)   # they go into the SQL
    near = f"ST_DWithin(the_geom::geography, ST_SetSRID(ST_MakePoint({lon}, {lat}), 4326)::geography, {int(radius)})"
    if reports == PHL:
        found = carto("select service_name, status, requested_datetime t, address, ST_Y(the_geom) lat, ST_X(the_geom) lon "
                      f"from public_cases_fc where requested_datetime > now() - interval '7 days' and {near} "
                      "order by requested_datetime desc limit 300")
    else:
        found = open311(reports, lat, lon, radius) if reports else []
    issued = carto("select permittype, typeofwork, permitissuedate t, address, ST_Y(the_geom) lat, ST_X(the_geom) lon "
                   f"from permits where permitissuedate > now() - interval '30 days' and {near} "
                   "order by permitissuedate desc limit 300") if permits == PHL else []
    return {"reports": found, "permits": issued, "fetched": datetime.now().isoformat(timespec="seconds")}


def open311(base, lat, lon, radius, days=7):
    """this week's 311 reports within radius metres from an Open311 GeoReport v2 server, in the shape carto's come in.
    Servers differ on radius, so it's checked here too, and a row with no place or time is left out."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = get(base.rstrip("/") + "/requests.json?" + urllib.parse.urlencode(
        {"lat": lat, "long": lon, "radius": int(radius), "start_date": since}), timeout=60)
    out = []
    for r in rows if isinstance(rows, list) else []:
        try:
            a, b, t = float(r["lat"]), float(r["long"]), str(r["requested_datetime"])
        except (KeyError, TypeError, ValueError):
            continue
        if math.hypot(*metres(lat, lon, a, b)) <= radius:
            out.append({"service_name": str(r.get("service_name") or "report"), "status": str(r.get("status") or ""),
                        "t": t, "address": str(r.get("address") or ""), "lat": a, "lon": b})
    return sorted(out, key=lambda r: r["t"], reverse=True)[:300]


def metres(lat, lon, a, b):
    """how far (a, b) is from (lat, lon), east and north, in metres"""
    return (b - lon) * 111320 * math.cos(math.radians(lat)), (a - lat) * 110540


def fetch_bikes(lat, lon, count=6, feed=INDEGO):
    """the nearest stations of a bike share's GBFS feed (Indego's by default): name, metres away, bikes, e-bikes, open
    docks"""
    feed = feed.rstrip("/") + "/"
    info = {s["station_id"]: s for s in get(feed + "station_information.json")["data"]["stations"]}
    status = {s["station_id"]: s for s in get(feed + "station_status.json")["data"]["stations"]}
    out = []
    for sid, s in info.items():
        st = status.get(sid, {})   # a station with no status says so (None), not 0 bikes and open
        e = (st.get("num_bikes_available_types") or {}).get("electric", 0 if st else None)   # Indego's: classic, smart, electric
        out.append({"name": s["name"], "lat": s["lat"], "lon": s["lon"], "far": math.hypot(*metres(lat, lon, s["lat"], s["lon"])),
                    "bikes": st.get("num_bikes_available"), "ebikes": e, "docks": st.get("num_docks_available"),
                    "open": bool(st["is_renting"]) if "is_renting" in st else None})
    return {"stations": sorted(out, key=lambda s: s["far"])[:count], "fetched": datetime.now().isoformat(timespec="seconds")}


def count(n):
    """a station's count as text: "?" when its status didn't say"""
    return "?" if n is None else str(n)


def streets_ok(x):
    """is x the shape fetch_streets writes: {"roads": [[major, [[lat, lon], ...]]], "rail": [[[lat, lon], ...]]}"""
    num = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
    line = lambda l: isinstance(l, list) and all(isinstance(p, list) and len(p) == 2 and all(map(num, p)) for p in l)
    return (isinstance(x, dict) and isinstance(x.get("roads"), list) and isinstance(x.get("rail"), list)
            and all(isinstance(r, list) and len(r) == 2 and line(r[1]) for r in x["roads"]) and all(map(line, x["rail"])))


def fetch_streets(lat, lon, half_w, half_h):
    """the streets and the El around (lat, lon), from OpenStreetMap, cached on disk once fetched:
    {"roads": [[major, [[lat, lon], ...]]], "rail": [[[lat, lon], ...]]}"""
    path = STREETS.format(lat=lat, lon=lon)
    try:
        with open(path) as f:
            got = json.load(f)
        if streets_ok(got):
            return got
    except (OSError, ValueError):
        pass   # none yet, or corrupt, or valid JSON of the wrong shape: fetch it again
    dlat, dlon = half_h / 110540, half_w / (111320 * math.cos(math.radians(lat)))
    box = f"{lat - dlat:.5f},{lon - dlon:.5f},{lat + dlat:.5f},{lon + dlon:.5f}"
    sel = f'way["highway"~"^(motorway|trunk|primary|secondary|tertiary|residential|unclassified|living_street)$"]({box});' \
          f'way["railway"~"^(subway|rail|light_rail|tram)$"]({box});'
    body = urllib.parse.urlencode({"data": f"[out:json][timeout:90];({sel});out geom qt;"}).encode()
    for attempt in range(4):
        try:
            got = get(OVERPASS[attempt % 2], body, timeout=120)["elements"]; break
        except Exception:
            if attempt == 3:
                raise
            time.sleep(15)
    pts = lambda e: [[round(p["lat"], 5), round(p["lon"], 5)] for p in e.get("geometry", [])]
    major = {"motorway", "trunk", "primary", "secondary"}
    data = {"roads": [[e["tags"]["highway"] in major, pts(e)] for e in got if "highway" in e.get("tags", {})],
            "rail": [pts(e) for e in got if "railway" in e.get("tags", {})]}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump(data, open(path + ".tmp", "w")); os.replace(path + ".tmp", path)
    return data


def spot(p):
    """a row's (lat, lon) if it has a place on the map (the city's rows sometimes have no geometry), else None"""
    try:
        a, b = float(p["lat"]), float(p["lon"])
    except (KeyError, TypeError, ValueError):
        return None
    return (a, b) if math.isfinite(a) and math.isfinite(b) else None


def hexagon(d, x, y, r, fill, outline):
    d.polygon([(x + r * math.cos(math.radians(a)), y + r * math.sin(math.radians(a))) for a in range(30, 390, 60)],
              fill=fill, outline=outline)


WHERE = {"place": "HIVE76", "area": "Kensington", "bike_share": "INDEGO", "city": "City of Philadelphia"}


def credit_for(view, where=WHERE):
    """the map's credit: only the data this view draws (the streets are always there)"""
    return " · ".join(["© OpenStreetMap contributors"] + ([where["city"]] if view != "bikes" and where["city"] else [])
                      + ([where["bike_share"].title()] if view in ("all", "bikes") and where["bike_share"] else []))


def draw_map(view, lat, lon, radius, streets, city, bikes, where=WHERE):
    """the map: the streets, the El, the view's things, a ring at radius and the place in the middle, RGB at screen
    size"""
    w, h = MAP_W // PIX, SCREEN[1] // PIX
    scale = (h / 2 - 6) / (radius * 1.08)                 # map pixels a metre: the ring just fits top to bottom
    to = lambda a, b: (w / 2 + metres(lat, lon, a, b)[0] * scale, h / 2 - metres(lat, lon, a, b)[1] * scale)
    img = Image.new("RGB", (w, h), BG); d = ImageDraw.Draw(img)
    for major in (False, True):
        for m, line in (streets or {}).get("roads", []):
            if m == major and len(line) > 1:
                d.line([to(*p) for p in line], fill=ROAD_MAJOR if major else ROAD)
    for line in (streets or {}).get("rail", []):
        if len(line) > 1:
            d.line([to(*p) for p in line], fill=RAIL, width=2)
    cx, cy, r = w / 2, h / 2, radius * scale
    for a in range(0, 360, 6):                           # the ring, dashed
        a0, a1 = math.radians(a), math.radians(a + 3)
        d.line((cx + r * math.cos(a0), cy + r * math.sin(a0), cx + r * math.cos(a1), cy + r * math.sin(a1)), fill=DARK)
    if view in ("all", "building"):
        for p in (city or {}).get("permits", []):
            if spot(p):
                x, y = to(*spot(p)); d.rectangle((x - 1, y - 1, x + 1, y + 1), fill=LIGHT)
    if view in ("all", "reports"):
        for p in (city or {}).get("reports", []):
            if spot(p):
                x, y = to(*spot(p)); d.ellipse((x - 2, y - 2, x + 2, y + 2), fill=ORANGE)
    if view in ("all", "bikes"):
        for s in (bikes or {}).get("stations", []):
            x, y = to(s["lat"], s["lon"])
            d.rectangle((x - 3, y - 3, x + 3, y + 3), fill=WHITE if s["bikes"] else DARK, outline=BG)   # unknown is as dark as none
    hexagon(d, cx, cy, 6, ORANGE, WHITE)
    img = img.resize((MAP_W, SCREEN[1]), Image.NEAREST)
    if view in ("all", "bikes"):   # each station's bikes, at screen size
        for s in (bikes or {}).get("stations", []):
            x, y = to(s["lat"], s["lon"])
            text(img, (round(x * PIX) + 10, round(y * PIX) - 8), count(s["bikes"]), WHITE, scale=1)
    text(img, (round(cx * PIX) + 16, round(cy * PIX) - 8), where["place"], ORANGE, scale=1)
    credit = credit_for(view, where)
    ImageDraw.Draw(img).rectangle((6, SCREEN[1] - 28, 18 + len(credit) * 8, SCREEN[1] - 6), fill=BG)   # a backing, so the rail doesn't run through it
    text(img, (12, SCREEN[1] - 22), credit, GREY, scale=1)
    return img


def stamp(src):
    """when a cache was fetched, or None if it doesn't say"""
    try:
        return datetime.fromisoformat(src["fetched"])
    except (KeyError, TypeError, ValueError):
        return None


def when(iso, now):
    """a time, short: "4:10p" today, "Wed 6:23p" this week, "Oct 1" before that"""
    t = local(iso.replace("Z", "+00:00"))
    hm = f"{t.hour % 12 or 12}:{t.minute:02d}{'a' if t.hour < 12 else 'p'}"
    return hm if t.date() == now.date() else f"{t:%a} {hm}" if (now - t).days < 6 else t.strftime("%b ") + str(t.day)


def near_bikes(stations):
    """the bikes at these stations as text: "?" if none says, "5+" if some don't (they're not 0)"""
    known = [s["bikes"] for s in stations if s["bikes"] is not None]
    return "?" if not known else str(sum(known)) + ("+" if len(known) < len(stations) else "")


def tally(rows, key):
    counts = {}
    for r in rows:
        counts[r[key]] = counts.get(r[key], 0) + 1
    return sorted(counts.items(), key=lambda kv: -kv[1])


def draw(now, view, lat, lon, radius, streets, city, bikes, where=WHERE):
    """the whole page, RGB at the screen's size"""
    img = Image.new("RGB", SCREEN, BG); d = ImageDraw.Draw(img)
    img.paste(draw_map(view, lat, lon, radius, streets, city, bikes, where), (0, 0))
    d.line((MAP_W, 0, MAP_W, SCREEN[1]), fill=RULE, width=2)
    hexagon(d, X0 + 14, 32, 14, ORANGE, None)
    text(img, (X0 + 36, 10), f"AROUND {where['place']}"[:30], WHITE, scale=2)
    text(img, (X0 + 36, 40), " · ".join(x for x in (where["area"], clock(now)) if x), GREY, scale=1)
    for i, (key, label) in enumerate(VIEWS):   # the tabs, for touching
        x = TAB_X + i * (TAB_W + 8)
        on = key == view
        d.rounded_rectangle((x, TAB_Y, x + TAB_W, TAB_Y + TAB_H), radius=10, fill=ORANGE if on else PANEL, outline=ORANGE if on else RULE)
        text(img, (x + (TAB_W - len(label) * 16) // 2, TAB_Y + 6), label, BG if on else GREY, scale=2)
    reports = [r for r in (city or {}).get("reports", []) if r.get("t")]   # a row with no time can't be listed
    permits = [p for p in (city or {}).get("permits", []) if p.get("t")]
    stations = (bikes or {}).get("stations", [])
    Y, R = 80, SCREEN[0] - 24
    if city is None and view != "bikes" or bikes is None and view == "bikes":
        text(img, (X0, Y + 20), "asking the city...", GREY, scale=2)
        return img
    parts = ([(city, STALE_CITY)] if view != "bikes" else []) + ([(bikes, STALE_BIKES)] if view in ("all", "bikes") else [])
    ages = [freshness(stamp(src), now, limit) for src, limit in parts]
    note, stale = max(ages, key=lambda a: a[1])   # one that's stale, else the first
    text(img, (R, SCREEN[1] - 17), note, A if stale else GREY, scale=1, right=True)
    if view == "all":
        cols = [(X0, "311 · 7 DAYS", len(reports), ORANGE, [f"{n:>3}  {k}" for k, n in tally(reports, "service_name")[:6]]),
                (X0 + 360, "PERMITS · 30 DAYS", len(permits), LIGHT, [f"{n:>3}  {k}" for k, n in tally(permits, "permittype")[:6]]),
                (X0 + 720, (where["bike_share"] or "BIKES")[:20], near_bikes(stations[:4]), WHITE,
                 [f"{count(s['bikes']):>2}  {s['name'][:24]}" for s in stations[:6]])]
        for x, title, big, colour, lines in cols:
            text(img, (x, Y), title, GREY, scale=1)
            text(img, (x, Y + 20), str(big), colour, scale=4)
            text(img, (x + len(str(big)) * 32 + 10, Y + 52), ("bikes, some unknown" if big == "?" or big.endswith("+") else "bikes nearby") if x == X0 + 720 else "nearby", GREY, scale=1)
            for i, line in enumerate(lines):
                text(img, (x, Y + 100 + i * 24), line[:40], WHITE, scale=1)
        d.line((X0, Y + 258, R, Y + 258), fill=RULE)
        text(img, (X0, Y + 272), "LATEST", GREY, scale=1)
        latest = sorted([(r["t"], ORANGE, r["service_name"], r["address"]) for r in reports[:4]] +
                        [(p["t"], LIGHT, p["permittype"] + " permit", p["address"]) for p in permits[:4]], reverse=True)
        for i, (t, colour, what, where) in enumerate(latest[:5]):
            y = Y + 296 + i * 26
            text(img, (X0, y), when(t, now), GREY, scale=1)
            text(img, (X0 + 100, y), (what or "")[:36], colour, scale=1)
            text(img, (X0 + 420, y), (where or "")[:40], WHITE, scale=1)
    elif view == "reports":
        text(img, (X0, Y), f"{len(reports)} reports to 311 within {radius / 1000:g} km this week", GREY, scale=1)
        for i, r in enumerate(reports[:16]):
            y = Y + 26 + i * 25
            text(img, (X0, y), when(r["t"], now), GREY, scale=1)
            text(img, (X0 + 100, y), (r["service_name"] or "")[:30], ORANGE, scale=1)
            text(img, (X0 + 360, y), (r["address"] or "")[:42], WHITE, scale=1)
            text(img, (R, y), (r["status"] or "").upper(), LIGHT if r["status"] == "Closed" else GREY, scale=1, right=True)
    elif view == "building":
        text(img, (X0, Y), f"{len(permits)} L&I permits within {radius / 1000:g} km in 30 days", GREY, scale=1)
        for i, p in enumerate(permits[:16]):
            y = Y + 26 + i * 25
            text(img, (X0, y), when(p["t"], now), GREY, scale=1)
            text(img, (X0 + 100, y), (p["permittype"] or "")[:22], LIGHT, scale=1)
            text(img, (X0 + 290, y), (p["typeofwork"] or "")[:30], WHITE, scale=1)
            text(img, (R, y), (p["address"] or "")[:30], GREY, scale=1, right=True)
    else:   # bikes
        text(img, (X0, Y), "the nearest Indego stations, live", GREY, scale=1)
        for i, s in enumerate(stations[:6]):
            y = Y + 28 + i * 66
            text(img, (X0, y), s["name"][:40], GREY if s["open"] is None else WHITE if s["open"] else DARK, scale=2)
            text(img, (X0, y + 34), f"{s['far'] / 1000:.1f} km · {max(1, round(s['far'] / 80))} min walk", GREY, scale=1)
            text(img, (R - 360, y + 4), count(s["bikes"]), WHITE, scale=3); text(img, (R - 360 + len(count(s["bikes"])) * 24 + 8, y + 22), "bikes", GREY, scale=1)
            text(img, (R - 200, y + 4), count(s["ebikes"]), LIGHT, scale=3); text(img, (R - 200 + len(count(s["ebikes"])) * 24 + 8, y + 22), "electric", GREY, scale=1)
            text(img, (R - 50, y + 4), count(s["docks"]), GREY, scale=3, right=True); text(img, (R, y + 22), "docks", GREY, scale=1, right=True)
    return img


def read(path):
    try:
        return json.load(open(path)), os.path.getmtime(path)
    except (OSError, ValueError):
        return None, None


class Page:
    """the blocks around Hive76, as a page of the kiosk's cycle"""
    name, seconds = "around", 30

    def __init__(self, view="all", lat=HIVE76[0], lon=HIVE76[1], radius=1000, data=None, place="HIVE76",
                 area="Kensington", bikes=INDEGO, bike_share="INDEGO", reports=PHL, permits=PHL):
        assert view in dict(VIEWS), f"view is one of {', '.join(dict(VIEWS))}"
        for url in (bikes, reports):   # they're fetched, so only https, and only from a playlist someone wrote
            assert url in (None, PHL) or isinstance(url, str) and url.startswith("https://"), "a source has to be an https address"
        assert permits in (None, PHL), "permits are phl-carto or null"
        self.home = self.view = view
        self.lat, self.lon, self.radius = lat, lon, radius
        self.sources = {"bikes": bikes, "reports": reports, "permits": permits}
        city = "City of Philadelphia" if PHL in (reports, permits) else urllib.parse.urlsplit(reports).hostname if reports else ""
        self.where = {"place": str(place).upper()[:16], "area": str(area or "")[:24], "city": city,
                      "bike_share": str(bike_share).upper()[:16] if bikes else ""}
        self.fixed = data is not None
        self.streets, self.city, self.bikes = (data or {}).get("streets"), (data or {}).get("city"), (data or {}).get("bikes")
        self.busy, self.touched, self.bg, self.tried = False, 0.0, (None, None), {}
        self.paths = ()   # the two caches, set when first used: they depend on lat, lon and radius, and the tests swap CACHE and BIKES

    def caches(self):
        """(path, every, make) for the city's data and the bikes, each cached for its own middle (and radius)"""
        if not self.paths:
            # today's sources keep today's cache names; any other gets its own
            src = lambda *k: "" if k in ((PHL, PHL), (INDEGO,)) else f"-{zlib.crc32(json.dumps(k).encode()):08x}"
            s = self.sources
            self.paths = (CACHE.format(lat=self.lat, lon=self.lon, radius=self.radius, src=src(s["reports"], s["permits"])),
                          BIKES.format(lat=self.lat, lon=self.lon, src=src(s["bikes"])))
        s = self.sources
        return ((self.paths[0], EVERY, lambda: fetch_city(self.lat, self.lon, self.radius, s["reports"], s["permits"])),
                (self.paths[1], BIKES_EVERY,
                 (lambda: fetch_bikes(self.lat, self.lon, 6, s["bikes"])) if s["bikes"] else
                 (lambda: {"stations": [], "fetched": datetime.now().isoformat(timespec="seconds")})))

    def due(self, path, every):
        """is a cache old (or missing) and not just tried: a failure leaves it old, and mustn't be asked every tick"""
        old = not os.path.exists(path) or time.time() - os.path.getmtime(path) > every
        return old and time.time() - self.tried.get(path, 0) > RETRY

    def fetch(self):
        """whatever is old, in a thread: the city's data, the bikes, and the streets the first time"""
        half_w, half_h = self.radius * 1.08 * MAP_W / SCREEN[1], self.radius * 1.12
        for path, every, make in self.caches():
            if self.due(path, every):
                try:
                    data = make()
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    json.dump(data, open(path + ".tmp", "w")); os.replace(path + ".tmp", path)
                except Exception as e:
                    self.tried[path] = time.time()
                    print(f"around: {e}", flush=True)   # keep the last; try again after RETRY
        if self.streets is None and time.time() - self.tried.get("streets", 0) > RETRY:
            try:
                self.streets = fetch_streets(self.lat, self.lon, half_w, half_h)
            except Exception as e:
                self.tried["streets"] = time.time()
                print(f"around streets: {e}", flush=True)
        self.busy = False

    def start(self, now):
        self.view = self.home

    def touch(self, x, y):
        """a touch on a tab changes the view"""
        if TAB_Y <= y <= TAB_Y + TAB_H + 10:
            for i, (key, _) in enumerate(VIEWS):
                if TAB_X + i * (TAB_W + 8) <= x <= TAB_X + i * (TAB_W + 8) + TAB_W:
                    self.view, self.touched = key, time.time()

    def background(self, now):
        if not self.fixed:
            (city_path, city_every, _), (bikes_path, bikes_every, _) = self.caches()
            if not self.busy and (self.due(city_path, city_every) or self.due(bikes_path, bikes_every)
                                  or self.streets is None and time.time() - self.tried.get("streets", 0) > RETRY):   # nothing due, no thread
                self.busy = True; threading.Thread(target=self.fetch, daemon=True).start()
            self.city, city_t = read(city_path)
            self.bikes, bikes_t = read(bikes_path)
        else:
            city_t = bikes_t = 0
        if self.view != self.home and time.time() - self.touched > IDLE:   # nobody's touched it for a while
            self.view = self.home
        key = (self.view, now.minute, city_t, bikes_t, self.streets is not None)
        if key != self.bg[0]:
            self.bg = (key, packed(draw(now, self.view, self.lat, self.lon, self.radius, self.streets, self.city, self.bikes,
                                        self.where)))
        return self.bg

    def regions(self, now, t):
        return []


SAMPLE = {"streets": {"roads": [[True, [[39.98, -75.14], [39.99, -75.12]]], [False, [[39.984, -75.135], [39.989, -75.128]]]],
                      "rail": [[[39.975, -75.135], [39.995, -75.125]]]},
          "city": {"reports": [{"service_name": "Abandoned Vehicle", "status": "Open", "t": "2026-10-14T22:23:15Z",
                                "address": "2307 E BOSTON ST", "lat": 39.97996, "lon": -75.12539},
                               {"service_name": "Sanitation Violation", "status": "Closed", "t": "2026-10-15T15:10:28Z",
                                "address": "2226 N FRONT ST", "lat": 39.98396, "lon": -75.13250}],
                   "permits": [{"permittype": "Zoning", "typeofwork": "Change of Use", "t": "2026-10-14T18:23:19Z",
                                "address": "1828 FRANKFORD AVE", "lat": 39.9771, "lon": -75.1330}],
                   "fetched": "2026-10-15T16:00:00"},
          "bikes": {"stations": [{"name": "York-Dauphin Station, MFL", "lat": 39.9853, "lon": -75.1317, "far": 270, "bikes": 5,
                                  "ebikes": 2, "docks": 10, "open": True},
                                 {"name": "Lehigh & B", "lat": 39.9909, "lon": -75.1295, "far": 470, "bikes": 0, "ebikes": 0,
                                  "docks": 12, "open": True}], "fetched": "2026-10-15T16:00:00"}}


def check():
    now = datetime(2026, 10, 15, 16, 10)
    for view, _ in VIEWS:
        assert draw(now, view, *HIVE76, 1000, SAMPLE["streets"], SAMPLE["city"], SAMPLE["bikes"]).size == SCREEN, view
        assert draw(now, view, *HIVE76, 1000, None, None, None).size == SCREEN, f"{view} before any data"
    assert tally(SAMPLE["city"]["reports"] * 2, "service_name")[0][1] == 2
    assert when("2026-10-01T10:00:00Z", now) == "Oct 1" and when("2026-10-15T15:10:28Z", now).endswith(("a", "p"))
    assert when("2026-10-14T22:23:15Z", now)[:4] in ("Wed ", "Thu ") or ":" in when("2026-10-14T22:23:15Z", now)
    e, n = metres(*HIVE76, HIVE76[0] + 0.001, HIVE76[1] + 0.001)
    assert 80 < e < 90 and 105 < n < 115, "a thousandth of a degree is about 85 m east and 111 m north here"
    # a row with no geometry or time doesn't blank the page
    holes = {"reports": SAMPLE["city"]["reports"] + [{"service_name": "x", "status": "Open", "t": "2026-10-15T15:00:00Z", "address": "y",
                                                       "lat": None, "lon": None}, {"service_name": "z", "status": "Open", "t": None, "address": None}],
             "permits": SAMPLE["city"]["permits"] + [{"permittype": "p", "typeofwork": None, "t": "2026-10-15T15:00:00Z", "address": None, "lat": float("nan"), "lon": None}],
             "fetched": SAMPLE["city"]["fetched"]}
    for view, _ in VIEWS:
        assert draw(now, view, *HIVE76, 1000, SAMPLE["streets"], holes, SAMPLE["bikes"]).size == SCREEN, f"{view} with holes"
    assert spot({"lat": None, "lon": 1}) is None and spot({"lat": "x", "lon": 1}) is None and spot({"lat": 1, "lon": 2}) == (1, 2)
    # the age: updated hh:mm, then amber when old
    fresh, old = (draw(now, "all", *HIVE76, 1000, None, SAMPLE["city"], SAMPLE["bikes"]),
                  draw(now, "all", *HIVE76, 1000, None, dict(SAMPLE["city"], fetched="2026-10-15T09:00:00"), SAMPLE["bikes"]))
    assert fresh.tobytes() != old.tobytes() and freshness(datetime(2026, 10, 15, 16, 0), now, STALE_CITY) == ("updated 4:00 PM", False)
    # a fetch that fails isn't asked for again until RETRY has passed; lat and lon are numbers before they reach the SQL
    try:
        fetch_city("39;drop table x", 0, 1000); raise AssertionError("lat went into the SQL")
    except ValueError:
        pass
    import tempfile, types
    names = ("CACHE", "BIKES", "fetch_city", "fetch_bikes", "fetch_streets")
    real = {n: globals()[n] for n in names}
    asked = []
    def down(*a):
        asked.append(1); raise OSError("down")
    folder = tempfile.mkdtemp()
    globals().update(CACHE=os.path.join(folder, "a.json"), BIKES=os.path.join(folder, "b.json"), fetch_city=down, fetch_bikes=down, fetch_streets=down)
    try:
        page = Page(); page.fetch(); page.fetch(); page.fetch()
        assert len(asked) == 3, f"city, bikes and streets once each, not {len(asked)}"
        page.tried = {k: v - RETRY - 1 for k, v in page.tried.items()}; page.fetch()
        assert len(asked) == 6, "and again after RETRY"
    finally:
        globals().update(real)
    # with nothing cached and everything down, a thread is started once, not every tick
    spawned = []
    class Now:   # a thread that runs at once
        def __init__(self, target): self.target = target
        def start(self): spawned.append(1); self.target()
    real_threading = globals()["threading"]
    globals().update(CACHE=os.path.join(folder, "c-{lat}.json"), BIKES=os.path.join(folder, "d.json"), fetch_city=down, fetch_bikes=down,
                     fetch_streets=down, threading=types.SimpleNamespace(Thread=lambda target, daemon=None: Now(target)))
    try:
        page = Page(); page.background(now); page.background(now); page.background(now)
        assert len(spawned) == 1, f"{len(spawned)} fetch threads in 3 ticks with no cache"
    finally:
        globals().update(real); globals()["threading"] = real_threading
    # each middle and radius has its own cache
    assert len({Page().caches()[0][0], Page(radius=500).caches()[0][0], Page(lat=40.0).caches()[0][0], Page(lon=-75.2).caches()[0][0]}) == 4
    assert Page(lat=40.0).caches()[1][0] != Page().caches()[1][0]
    # a station with no status is unknown, not 0 bikes and open; a corrupt streets cache is fetched again
    feed = {"station_information.json": {"data": {"stations": [{"station_id": "1", "name": "A", "lat": HIVE76[0], "lon": HIVE76[1]}]}},
            "station_status.json": {"data": {"stations": []}}}
    real_get = globals()["get"]; globals()["get"] = lambda url, *a, **k: feed[url.rsplit("/", 1)[1]]
    try:
        st = fetch_bikes(*HIVE76)["stations"][0]
    finally:
        globals()["get"] = real_get
    assert st["bikes"] is None and st["docks"] is None and st["open"] is None and count(st["bikes"]) == "?"
    unknown = dict(SAMPLE["bikes"], stations=[st] + SAMPLE["bikes"]["stations"])
    for view in ("all", "bikes"):
        assert draw(now, view, *HIVE76, 1000, None, SAMPLE["city"], unknown).tobytes() != draw(now, view, *HIVE76, 1000, None, SAMPLE["city"],
            dict(unknown, stations=[dict(st, bikes=0, ebikes=0, docks=0, open=True)] + SAMPLE["bikes"]["stations"])).tobytes(), "unknown isn't 0"
    real_streets = globals()["STREETS"]
    globals()["STREETS"] = os.path.join(folder, "s-{lat}_{lon}.json")
    open(globals()["STREETS"].format(lat=1, lon=2), "w").write("{not json")
    globals()["get"] = lambda *a, **k: {"elements": []}
    try:
        assert fetch_streets(1, 2, 100, 100) == {"roads": [], "rail": []}, "corrupt cache is fetched again, not raised every time"
    finally:
        globals()["STREETS"], globals()["get"] = real_streets, real_get
    # a streets cache of valid JSON and the wrong shape is fetched again, and the credit names what the view draws
    assert streets_ok(SAMPLE["streets"]) and not any(map(streets_ok, ([], {"roads": 1}, {"roads": [], "rail": [[1]]}, None, {"roads": [[True, [[1, "x"]]]], "rail": []})))
    globals()["STREETS"] = os.path.join(folder, "s-{lat}_{lon}.json")
    globals()["get"] = lambda *a, **k: {"elements": []}
    try:
        for bad in ("[]", '{"roads": 1}'):
            open(globals()["STREETS"].format(lat=1, lon=2), "w").write(bad)
            assert fetch_streets(1, 2, 100, 100) == {"roads": [], "rail": []}, f"{bad} reached draw"
    finally:
        globals()["STREETS"], globals()["get"] = real_streets, real_get
    assert "Indego" not in credit_for("reports") and "Philadelphia" not in credit_for("bikes") and "Indego" in credit_for("all")
    got = []; real_credit = credit_for
    globals()["credit_for"] = lambda view, where=WHERE: (got.append(view), real_credit(view, where))[1]
    try:
        for view, _ in VIEWS:
            draw_map(view, *HIVE76, 1000, None, None, None)
    finally:
        globals()["credit_for"] = real_credit
    assert got == [v for v, _ in VIEWS], "the map's credit is the view's own"
    # some stations unknown: the overview says so instead of summing them as 0
    assert near_bikes([{"bikes": 3}, {"bikes": None}]) == "3+" and near_bikes([{"bikes": None}]) == "?" and near_bikes([{"bikes": 0}]) == "0"
    page = Page(data=SAMPLE)
    key, bg = page.background(now)
    assert bg.mode == "LA" and page.background(now)[0] == key and page.regions(now, 0) == []
    page.touch(TAB_X + 3 * (TAB_W + 8) + 20, TAB_Y + 20)
    assert page.view == "bikes" and page.background(now)[0] != key, "touching a tab changes the view"
    page.touch(10, 10); assert page.view == "bikes", "a touch on the map doesn't"
    page.touched -= IDLE + 1; page.background(now)
    assert page.view == "all", "and with nobody touching it goes back to its own"
    try:
        Page(view="weather"); raise AssertionError("a view that isn't one should fail")
    except AssertionError as err:
        assert "view is one of" in str(err)

    # another city: Open311 for the reports, its own bike share, no permits, its own names
    asked = []
    def city_api(url, *a, **k):
        asked.append(url)
        return [{"service_name": "Pothole", "status": "open", "requested_datetime": "2026-10-15T10:00:00-07:00",
                 "address": "1 Main St", "lat": 47.6205, "long": -122.3493},
                {"service_name": "Far away", "requested_datetime": "2026-10-15T10:00:00Z", "lat": 48.0, "long": -122.0},
                {"service_name": "No place", "requested_datetime": "2026-10-15T10:00:00Z"}]
    real_get = globals()["get"]; globals()["get"] = city_api
    try:
        rows = open311("https://311.example.org/open311/v2/", 47.6205, -122.3493, 1000)
    finally:
        globals()["get"] = real_get
    assert [r["service_name"] for r in rows] == ["Pothole"] and rows[0]["lon"] == -122.3493, "only what's near, with a place"
    assert asked[0].startswith("https://311.example.org/open311/v2/requests.json?") and "start_date=" in asked[0], asked
    seattle = Page(lat=47.6205, lon=-122.3493, place="Space Needle", area="Seattle", bikes=None,
                   reports="https://311.example.org/open311/v2", permits=None)
    assert seattle.caches()[1][2]()["stations"] == [], "no bike share: no stations, and nothing fetched"
    assert "-" not in os.path.basename(Page().caches()[0][0]).split("_")[-1], "today's caches keep today's names"
    assert Page(reports=None).caches()[0][0] != Page().caches()[0][0], "and another source gets its own"
    for bad in ({"bikes": "http://gbfs.example.org/"}, {"reports": "ftp://x"}, {"permits": "https://permits.example.org"}):
        try:
            Page(**bad)
        except AssertionError:
            pass
        else:
            raise AssertionError(f"took {bad}")
    assert seattle.where["place"] == "SPACE NEEDLE" and seattle.where["city"] == "311.example.org" and not seattle.where["bike_share"]
    assert "311.example.org" in credit_for("all", seattle.where) and "Indego" not in credit_for("all", seattle.where)
    for view in dict(VIEWS):
        assert draw(now, view, 47.6205, -122.3493, 1000, None, {"reports": rows, "permits": [], "fetched": now.isoformat()},
                    {"stations": [], "fetched": now.isoformat()}, seattle.where).size == SCREEN, view

def preview(now=None):
    """the overview with the sample, for the emulator and kiosk.py --png"""
    import kit
    return kit.unpack(Page(data=SAMPLE).background(now or datetime(2026, 10, 15, 16, 10))[1])
