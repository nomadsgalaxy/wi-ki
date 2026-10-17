"""The radar page: what's flying overhead right now, on a live map. The map is centred on the kiosk (in Beacon Red,
the brand's you-are-here colour) and fills most of the screen, with a blip for every aircraft on it (a helicopter for
the ones that are), pointing where it's heading and coloured by height: amber low, cyan in the middle, violet high.
Beside it (below it, on a tall screen), a compact list of the nearest flights, one line each: callsign, route, type,
altitude, speed and how far away. It lays itself out for the shape it's drawn in (kit.SHAPES): the bar, 16:9, or 9:16.

Aircraft come from adsb.lol (no key) every 20 seconds and fly on along their track between fetches, redrawn every
second (moved()). Told to slow down (429), it waits a minute. Routes and airlines come from adsbdb.com (no key, cached
per callsign). Both run in a background thread so the display never waits on the network. Under them is a street map,
so you can see what they're over: main roads, rivers, the bigger towns and the airports (by their code) from
OpenStreetMap (the Overpass API, fetched once and cached on disk), drawn as quiet pixel lines in the brand's colours. Altitude is in feet and speed in
knots, the way aviation counts them; distances are in km. Under the roads is the live weather radar: the NEXRAD
composite from the Iowa Environmental Mesonet's map tiles (no key, every 5 minutes), in brand colours by strength.

Options (in playlist.json): lat and lon, the middle of the map (default: central Philadelphia; the playlist sets it to
home); radius, in nautical miles (default 25, about 46 km).
"""
import io, json, math, os, threading, time, urllib.error, urllib.parse, urllib.request
from datetime import datetime
from PIL import Image, ImageChops, ImageDraw

from kit import SCREEN, O, W, G, D, B, A, BG, RULE, text, clock, packed

TALL = SCREEN[1] > SCREEN[0]
BIG = SCREEN[1] >= 1000                                  # 16:9 or 9:16: bigger text, chunkier pixels
DS = 2 if BIG else 1                                     # text scale for the list
PIX = 4 if BIG else 2                                    # the map's drawn small and scaled up this much, like the skyline
RH = 22 * DS                                             # a flight's row in the list: one line
if TALL:   # header on top, then the map, then the list
    X0, Y0, SW = 0, 100, SCREEN[0] // 4 * 4
    SH = (SCREEN[1] - Y0 - 20 * RH) // 4 * 4
    HX, LX, LY = 24, 24, Y0 + SH + 24
else:      # the map on the left, as wide as the list allows; the header and list beside it
    X0, Y0, SH = 0, 0, SCREEN[1] // 4 * 4
    SW = (SCREEN[0] - 440 * DS - 48) // 4 * 4
    HX = LX = X0 + SW + 24; LY = 90 * DS
REACH = math.hypot(SW, SH) / SH                          # how far the corners are, in radii: planes are fetched that far
BEACON = (255, 58, 58)
# the Pi Zero, drawing by itself while the render server's away: a redraw takes it 1.3 s (the server 10 ms), so there
# it redraws only on each fetch, instead of every second
SLOW = os.uname().machine.startswith("arm")
EVERY, ROUTES_PER_FETCH, BACKOFF = 20, 2, 60   # the planes glide between fetches, so a fetch every 20 s looks live
ROADS = {"primary": (22, 46, 56), "trunk": (40, 80, 96), "motorway": (60, 120, 140)}   # drawn in this order, dim first
RIVER = (40, 55, 120)
AIRPORT = W
RAIN_TILES = "https://mesonet.agron.iastate.edu/cache/tile.py/1.0.0/nexrad-n0q-900913/{z}/{x}/{y}.png"
RAIN_ZOOM, RAIN_EVERY = 8, 300   # zoom 8 is about half a km a pixel here, near the map's own; the composite moves every 5 min
mix = lambda colour, k: tuple(round(c * k + b * (1 - k)) for c, b in zip(colour, BG))   # a token, faded toward the background
# by the tiles' hue: green is light rain (about 20 dBZ up), yellow and orange moderate, red and magenta heavy. The blues
# below that are drizzle, clear-air echoes and ground clutter, so they're left out.
RAIN = ((mix(O, 0.18), lambda h: 60 <= h < 110), (mix(O, 0.38), lambda h: 20 <= h < 60),
        (mix(A, 0.55), lambda h: h < 20 or h > 190))
OVERPASS = ("https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter")   # the main one, then a mirror
UA = {"User-Agent": "wi-ki radar (github.com/nomadsgalaxy/wi-ki)"}


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=10) as r:
        return json.load(r)


def streets(lat, lon, radius, wide=1.0):
    """main roads, rivers, towns and airports within radius nm (wide times that east and west), from OpenStreetMap,
    cached on disk once fetched:
    {"roads": [[kind, [[lat, lon], ...]]], "rivers": [[[lat, lon], ...]], "places": [[name, kind, population, lat, lon]],
    "airports": [[code, name, lat, lon]]}. Small queries rather than one big one: Overpass times big ones out when it's busy."""
    path = os.path.expanduser(f"~/.cache/kiosk/radar-map-{lat}_{lon}_{radius}{'' if wide == 1 else f'x{wide:g}'}.json")
    if os.path.exists(path):
        return json.load(open(path))
    km = radius * 1.852; dlat, dlon = km / 111.32, wide * km / (111.32 * math.cos(math.radians(lat)))
    box = f"{lat - dlat:.4f},{lon - dlon:.4f},{lat + dlat:.4f},{lon + dlon:.4f}"
    got = {}
    for name, sel in (("roads", f'way["highway"~"^(motorway|trunk|primary)$"]({box});'),
                      ("rivers", f'way["waterway"="river"]({box});'), ("places", f'node["place"~"^(city|town)$"]({box});'),
                      ("airports", f'nwr["aeroway"="aerodrome"]["iata"]({box}); nwr["aeroway"="aerodrome"]["icao"]({box});')):
        for attempt in range(3):
            try:
                out = "center" if name == "airports" else "geom"   # an airport's runways and fence don't matter, just where it is
                body = urllib.parse.urlencode({"data": f"[out:json][timeout:120];({sel});out {out} qt;"}).encode()
                with urllib.request.urlopen(urllib.request.Request(OVERPASS[attempt % len(OVERPASS)], body, UA), timeout=180) as r:
                    got[name] = json.load(r)["elements"]; break
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(10)
    pts = lambda e: [[round(p["lat"], 4), round(p["lon"], 4)] for p in e.get("geometry", [])]
    where = lambda e: (round(e["lat"], 4), round(e["lon"], 4)) if "lat" in e else (round(e["center"]["lat"], 4), round(e["center"]["lon"], 4))
    data = {"roads": [[e["tags"]["highway"], pts(e)] for e in got["roads"]], "rivers": [pts(e) for e in got["rivers"]],
            "places": [[e["tags"].get("name", ""), e["tags"]["place"], int("".join(filter(str.isdigit, e["tags"].get("population", "0"))) or 0),
                        e["lat"], e["lon"]] for e in got["places"]],
            "airports": [[e["tags"].get("iata") or e["tags"]["icao"], e["tags"].get("name", ""), *where(e)] for e in got["airports"]]}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump(data, open(path + ".tmp", "w")); os.replace(path + ".tmp", path)
    return data


def rain(lat, lon, radius):
    """the weather radar over the scope's whole map, small like basemap()'s, RGBA: NEXRAD tiles stitched, cropped to the
    map and recoloured by hue (the tiles go blue, green, yellow, red as the rain gets heavier; see RAIN). The tiles are Web
    Mercator and the map isn't, but over a hundred-odd km the difference is under a pixel."""
    lw, lh = SW // PIX, SH // PIX; r = lh // 2 - 4; km = radius * 1.852
    dlat, dlon = lh / 2 / r * km / 111.32, lw / 2 / r * km / (111.32 * math.cos(math.radians(lat)))
    world = 256 * 2 ** RAIN_ZOOM
    px = lambda la, lo: ((lo + 180) / 360 * world, (1 - math.asinh(math.tan(math.radians(la))) / math.pi) / 2 * world)
    (x0, y0), (x1, y1) = px(lat + dlat, lon - dlon), px(lat - dlat, lon + dlon)
    tx, ty = range(int(x0 // 256), int(x1 // 256) + 1), range(int(y0 // 256), int(y1 // 256) + 1)
    mosaic = Image.new("RGBA", (256 * len(tx), 256 * len(ty)))
    for i, x in enumerate(tx):
        for j, y in enumerate(ty):
            req = urllib.request.Request(RAIN_TILES.format(z=RAIN_ZOOM, x=x, y=y), headers=UA)
            with urllib.request.urlopen(req, timeout=10) as f:
                mosaic.paste(Image.open(io.BytesIO(f.read())).convert("RGBA"), (256 * i, 256 * j))
    ox, oy = tx[0] * 256, ty[0] * 256
    tile = mosaic.crop((round(x0 - ox), round(y0 - oy), round(x1 - ox), round(y1 - oy))).resize((lw, lh), Image.NEAREST)
    hue, alpha = tile.convert("RGB").convert("HSV").getchannel("H"), tile.getchannel("A").point(lambda a: 255 if a > 127 else 0)
    out = Image.new("RGBA", (lw, lh))
    for colour, band in RAIN:
        mask = ImageChops.multiply(hue.point(lambda h: 255 if band(h) else 0), alpha)
        out.paste(colour + (255,), (0, 0), mask)
    return out


def with_rain(over, layer):
    """the scope's background: the rain under the map's lines (basemap()'s transparent layer)"""
    img = Image.new("RGB", over.size, BG)
    if layer:
        img.paste(layer, (0, 0), layer)
    img.paste(over, (0, 0), over)
    return img


def basemap(data, lat, lon, radius):
    """the map's background: the streets, small (scaled up with the blips);
    and the airport codes and town labels that fit without overlapping, airports then the biggest towns first, in
    full-size pixels -> (image, [(x, y, name, colour)], the lines on their own, for with_rain())"""
    lw, lh = SW // PIX, SH // PIX; cx, cy, r = lw // 2, lh // 2, lh // 2 - 4
    km = radius * 1.852
    proj = lambda la, lo: (cx + (lo - lon) * 111.32 * math.cos(math.radians(lat)) / km * r, cy - (la - lat) * 111.32 / km * r)
    inside = lambda x, y, edge: edge <= x <= lw - edge and edge <= y <= lh - edge
    img = Image.new("RGBA", (lw, lh)); d = ImageDraw.Draw(img)
    for line in (data or {}).get("rivers", []):
        d.line([proj(*p) for p in line], fill=RIVER)
    for kind in ROADS:
        for k, line in (data or {}).get("roads", []):
            if k == kind:
                d.line([proj(*p) for p in line], fill=ROADS[kind])
    d.rectangle((cx - 1, cy - 1, cx + 1, cy + 1), fill=BEACON)
    labels, taken = [], []
    airports = [(code, AIRPORT, la, lo) for code, name, la, lo in (data or {}).get("airports", [])
                if "Seaplane" not in name]   # a seaplane base crowds the airport beside it (PSQ by PHL)
    for _, _, la, lo in airports:
        x, y = proj(la, lo)
        if inside(x, y, 2):
            d.rectangle((round(x) - 1, round(y) - 1, round(x) + 1, round(y) + 1), outline=AIRPORT)
    places = sorted((data or {}).get("places", []), key=lambda p: (p[1] != "city", -p[2]))
    towns = [(name, (70, 78, 104), la, lo) for name, kind, _, la, lo in places
             if "Township" not in name and (BIG or kind == "city")]
    for name, colour, la, lo in airports + towns:
        x, y = proj(la, lo)
        box = (x * PIX + 6, y * PIX - 8 * DS, x * PIX + 6 + len(name) * 8 * DS, y * PIX + 8 * DS)
        if not inside(x, y, 6) or box[2] > SW - 4 or box[3] > SH - 20:   # on the map, and clear of the credit
            continue
        if any(not (box[2] < t[0] or box[0] > t[2] or box[3] < t[1] or box[1] > t[3]) for t in taken):
            continue
        taken.append(box); labels.append((round(box[0]), round(box[1]), name, colour))
    return with_rain(img, None), labels, img


def height(alt):
    """a blip's colour by altitude in feet"""
    return G if alt == "ground" else A if alt < 10000 else O if alt < 25000 else B


def plane(track, colour):
    """a 9x9 pixel plane pointing along track (snapped to 45 degrees), drawn small and scaled up with the scope"""
    img = Image.new("RGBA", (9, 9)); d = ImageDraw.Draw(img)
    d.line((4, 0, 4, 8), fill=colour); d.line((0, 4, 8, 4), fill=colour); d.line((1, 3, 7, 3), fill=colour)   # body, wings
    d.line((2, 8, 6, 8), fill=colour); d.point((4, 0), fill=W)                                                  # tail, nose
    return img.rotate(-round((track or 0) / 45) * 45, Image.NEAREST)


def helicopter(track, colour):
    """a 9x9 pixel helicopter from above, pointing along track (snapped to 45 degrees): the cab under its X of rotor
    blades, the tail boom and its rotor, drawn small and scaled up with the scope like plane()"""
    img = Image.new("RGBA", (9, 9)); d = ImageDraw.Draw(img)
    d.rectangle((3, 1, 5, 4), fill=colour)                                       # cab
    d.line((1, 0, 7, 6), fill=colour); d.line((7, 0, 1, 6), fill=colour)         # rotor blades
    d.line((4, 5, 4, 8), fill=colour); d.line((3, 8, 5, 8), fill=colour)         # tail boom, tail rotor
    d.point((4, 1), fill=W)                                                      # nose
    return img.rotate(-round((track or 0) / 45) * 45, Image.NEAREST)


def aircraft(raw):
    """adsb.lol's list -> [{callsign, type, reg, alt, speed, track, dist (nm), bearing, heli}], nearest first. heli is
    the ADS-B emitter category A7, rotorcraft"""
    out = []
    for a in raw:
        if a.get("dst") is None or a.get("dir") is None:
            continue
        out.append({"callsign": (a.get("flight") or a.get("r") or a.get("hex", "?")).strip(), "type": a.get("t", ""),
                    "reg": a.get("r", ""), "alt": a.get("alt_baro", 0), "speed": a.get("gs") or 0,
                    "track": a.get("track"), "dist": a["dst"], "bearing": a["dir"], "heli": a.get("category") == "A7"})
    return sorted(out, key=lambda p: p["dist"])


def moved(planes, seconds):
    """planes flown on along their track at their ground speed for seconds since adsb.lol saw them (a minute at most,
    so a feed that's gone quiet doesn't fly them away), nearest first again. Ones on the ground stay put."""
    if not planes or seconds <= 0:
        return planes
    hours, out = min(seconds, 60) / 3600, []
    for p in planes:
        if p["alt"] == "ground" or not p["speed"] or p["track"] is None:
            out.append(p); continue
        b, t, go = math.radians(p["bearing"]), math.radians(p["track"]), p["speed"] * hours   # nm, like dist
        x, y = p["dist"] * math.sin(b) + go * math.sin(t), p["dist"] * math.cos(b) + go * math.cos(t)
        out.append(dict(p, dist=math.hypot(x, y), bearing=math.degrees(math.atan2(x, y)) % 360))
    return sorted(out, key=lambda p: p["dist"])


def scope(planes, radius, base=None):
    """the map with its blips over base (basemap(): the streets, rain and labels), full size RGB"""
    lw, lh = SW // PIX, SH // PIX
    base = base or basemap(None, 0, 0, radius)
    img = base[0].copy()
    cx, cy, r = lw // 2, lh // 2, lh // 2 - 4
    spots = []
    for p in planes or []:
        x = cx + p["dist"] / radius * r * math.sin(math.radians(p["bearing"]))
        y = cy - p["dist"] / radius * r * math.cos(math.radians(p["bearing"]))
        if not (4 <= x <= lw - 4 and 4 <= y <= lh - 4):   # past the edge of the map
            continue
        icon = (helicopter if p.get("heli") else plane)(p["track"], height(p["alt"]))
        img.paste(icon, (round(x) - 4, round(y) - 4), icon); spots.append((round(x) * PIX, round(y) * PIX, p))
    img = img.resize((SW, SH), Image.NEAREST)
    m = DS   # label scale
    for x, y, name, colour in base[1]:
        text(img, (x, y), name, colour, scale=m)
    text(img, (4, SH - 16), "© OpenStreetMap contributors · radar NOAA via IEM", D, scale=1)
    for x, y, p in spots[:12]:   # the nearest ones get their callsign
        text(img, (x + 7 * PIX, y - 8 * m), p["callsign"][:8], height(p["alt"]), scale=m)
    return img


def draw(now, planes, routes, radius, note=None, base=None):
    """the whole page, RGB at the screen's size"""
    img = Image.new("RGB", SCREEN, BG); R = SCREEN[0] - 24
    img.paste(scope(planes, radius, base), (X0, Y0))
    text(img, (HX, 10 * DS), "// 06 · OVERHEAD", O, scale=DS)
    text(img, (HX, 28 * DS), "FLIGHT RADAR", W, scale=2 * DS)
    text(img, (R, 10 * DS), clock(now), W, right=True, scale=2 * DS)
    if note:
        text(img, (R, 62 * DS), note[0], note[1], scale=DS, right=True)
    if planes is not None:
        text(img, (HX, 62 * DS), f"{len(planes)} within {round(radius * REACH * 1.852)} km", G, scale=DS)
    ImageDraw.Draw(img).rectangle((HX, 82 * DS, SCREEN[0] - 16, 82 * DS + 1), fill=RULE)
    if not planes:
        text(img, (LX, LY + 4), "clear skies" if planes is not None else "listening...", D, scale=DS)
    col = lambda n: LX + n * 8 * DS   # the list's columns, in characters
    for i, p in enumerate((planes or [])[:(SCREEN[1] - LY) // RH]):
        y, route = LY + i * RH, routes.get(p["callsign"]) or {}
        text(img, (col(0), y), p["callsign"][:8], height(p["alt"]), scale=DS)
        where = "helicopter" if p.get("heli") and not route.get("from") else \
            f"{route['from']}→{route['to']}" if route.get("from") else ""
        text(img, (col(9), y), where, W, scale=DS)
        text(img, (col(20), y), p["type"][:4], G, scale=DS)
        text(img, (col(25), y), "ground" if p["alt"] == "ground" else f"{p['alt']:,} ft", G, scale=DS)
        text(img, (col(36), y), f"{round(p['speed'])} kt", D, scale=DS)
        text(img, (R, y), f"{p['dist'] * 1.852:.0f} km", G, right=True, scale=DS)
    return img


class Page:
    """the radar, as a page of the kiosk's cycle"""
    name, seconds, shapes = "radar", 20, ("bar", "16-9", "9-16")

    def __init__(self, lat=39.95, lon=-75.17, radius=25, planes=None):
        self.lat, self.lon, self.radius = lat, lon, radius
        self.planes, self.routes, self.fetched, self.error = planes, {}, (time.time() if planes else 0), None
        self.seen, self.wait = None, 0.0   # when adsb.lol last answered (the planes fly on from there); no fetch till wait
        self.fixed, self.busy, self.bg = planes is not None, False, (None, None)
        self.base, self.mapped = basemap(None, lat, lon, radius), 0.0   # the street map comes in the background
        self.rain, self.rained = None, 0.0

    def fetch(self):
        """the aircraft, then a few routes we don't know yet (in a thread)"""
        try:
            self.planes = aircraft(get(f"https://api.adsb.lol/v2/point/{self.lat}/{self.lon}/{math.ceil(self.radius * REACH)}").get("ac", []))
            self.fetched = self.seen = time.time(); self.error = None
            for p in [p for p in self.planes if p["callsign"] not in self.routes][:ROUTES_PER_FETCH]:
                try:
                    r = get(f"https://api.adsbdb.com/v0/callsign/{p['callsign']}")["response"]["flightroute"]
                    self.routes[p["callsign"]] = {"from": r["origin"]["iata_code"], "to": r["destination"]["iata_code"],
                                                  "airline": (r.get("airline") or {}).get("name")}
                except urllib.error.HTTPError as e:
                    if e.code == 404:   # private flights and the like have none: don't ask again
                        self.routes[p["callsign"]] = {}
                    else:               # busy, or slowing us down: ask again another time
                        break
                except (TypeError, KeyError):
                    self.routes[p["callsign"]] = {}
                except Exception:
                    break
        except Exception as e:
            self.error = str(e)[:40]
            if getattr(e, "code", None) == 429:   # told to slow down: no fetch for BACKOFF
                self.wait = time.time() + BACKOFF
        if self.mapped >= 0 and time.time() - self.mapped > 600:   # the street map: once, or every 10 minutes till it works
            self.mapped = time.time()
            try:
                base = basemap(streets(self.lat, self.lon, self.radius, round(SW / SH, 2)), self.lat, self.lon, self.radius)
                self.base = (with_rain(base[2], self.rain), base[1], base[2])
                self.mapped, self.fetched = -1, time.time()   # done for good; and redraw
            except Exception:
                pass
        if time.time() - self.rained > RAIN_EVERY:   # the weather radar, every 5 minutes; a miss keeps the last one
            self.rained = time.time()
            try:
                self.rain = rain(self.lat, self.lon, self.radius)
                self.base, self.fetched = (with_rain(self.base[2], self.rain), *self.base[1:]), time.time()
            except Exception:
                pass
        self.busy = False

    def start(self, now):
        pass   # background() fetches, in a thread, when it's time

    def background(self, now):
        if not self.fixed and not self.busy and time.time() - self.fetched > EVERY and time.time() > self.wait:
            self.busy = True; threading.Thread(target=self.fetch, daemon=True).start()
        live = self.seen and not SLOW   # the planes fly on, redrawn every second
        key = (self.fetched, len(self.routes), now.minute, int(time.time()) if live else 0)
        if key != self.bg[0]:
            note = (f"no data: {self.error}", A) if self.error else (f"adsb.lol · every {EVERY} s", D)
            planes = moved(self.planes, time.time() - self.seen) if live else self.planes
            self.bg = (key, packed(draw(now, planes, self.routes, self.radius, note, self.base)))
        return self.bg

    def regions(self, now, t):
        return []   # it all changes together, every second


SAMPLE = aircraft([
    {"flight": "AAL322  ", "t": "B38M", "r": "N338RS", "alt_baro": 14150, "gs": 376.3, "track": 43.5, "dst": 3.9, "dir": 293.8},
    {"flight": "ICE686  ", "t": "A21N", "r": "TF-IAC", "alt_baro": 35000, "gs": 463.3, "track": 36, "dst": 35.6, "dir": 21.8},
    {"flight": "GTI8865 ", "t": "B77L", "r": "N712GT", "alt_baro": 35275, "gs": 459.8, "track": 226.8, "dst": 15.7, "dir": 340.3},
    {"flight": "N139MH  ", "t": "EC35", "r": "N139MH", "category": "A7", "alt_baro": 1150, "gs": 140.2, "track": 176.7, "dst": 22.3, "dir": 171.5},
    {"flight": "SKQ51   ", "t": "PC12", "r": "N705LH", "alt_baro": "ground", "gs": 0, "track": None, "dst": 9.5, "dir": 120},
    {"hex": "abc123", "alt_baro": 5000}])
ROUTES = {"AAL322": {"from": "MIA", "to": "EWR", "airline": "American Airlines"}, "N139MH": {}}


def check():
    assert [p["callsign"] for p in SAMPLE] == ["AAL322", "SKQ51", "GTI8865", "N139MH", "ICE686"], "nearest first, no position no blip"
    town = {"places": [["Wilmington", "city", 70000, 39.74, -75.55]], "airports": [["ILG", "Wilmington Airport", 39.6787, -75.6065]]}
    assert [l[2] for l in basemap(town, 39.71, -75.62, 25)[1]] == ["ILG", "Wilmington"], "airports first, then towns"
    lines = basemap(town, 39.71, -75.62, 25)[2]
    shower = Image.new("RGBA", lines.size); ImageDraw.Draw(shower).rectangle((0, 0, 9, 9), fill=mix(O, 0.18) + (255,))
    wet = with_rain(lines, shower)
    assert wet.getpixel((5, 5)) == mix(O, 0.18) and wet.getpixel((lines.width - 2, 2)) == BG, "rain under the map, nowhere else"
    hue = lambda rgb: Image.new("RGB", (1, 1), rgb).convert("HSV").getpixel((0, 0))[0]
    assert [i for i, (_, band) in enumerate(RAIN) for rgb in ((96, 180, 212), (0, 200, 0), (255, 200, 0), (255, 0, 0))
            if band(hue(rgb))] == [0, 1, 2], "blue is left out, green is light, yellow moderate, red heavy"
    assert [p["callsign"] for p in SAMPLE if p["heli"]] == ["N139MH"], "category A7 is a helicopter"
    assert helicopter(0, A).tobytes() != plane(0, A).tobytes() and helicopter(90, A).size == (9, 9)
    south = {"callsign": "S", "alt": 9000, "speed": 360, "track": 180, "dist": 10, "bearing": 0}
    parked = dict(south, callsign="P", alt="ground")
    assert [(p["callsign"], round(p["dist"], 3), round(p["bearing"])) for p in moved([south, parked], 60)] == \
        [("S", 4, 0), ("P", 10, 0)], "6 nm closer after a minute at 360 kt; the parked one stays"
    assert moved([south], 600)[0]["dist"] == moved([south], 60)[0]["dist"], "never more than a minute's worth"
    east = moved([dict(south, track=90)], 60)[0]
    assert round(east["bearing"]) == 31 and round(east["dist"], 2) == 11.66, east
    global get
    real, calls = get, []
    def fake(url):
        calls.append(url)
        if "adsb.lol" in url:
            return {"ac": [{"flight": f"T{i}", "dst": i, "dir": 0} for i in range(3)]}
        raise urllib.error.HTTPError(url, 404 if "T0" in url else 429, "", {}, None)
    get, page = fake, Page()
    page.mapped = page.rained = time.time() + 999   # no map or rain fetches in the test
    page.fetch()
    assert page.routes == {"T0": {}} and len(calls) == 3, "a 404 means no route; a 429 stops asking and asks again later"
    get = lambda url: (_ for _ in ()).throw(urllib.error.HTTPError(url, 429, "", {}, None))
    page.fetch()
    assert page.wait > time.time() + BACKOFF - 5 and page.error, "adsb.lol's 429: wait a minute"
    get = real
    assert height("ground") == G and height(5000) == A and height(20000) == O and height(36000) == B
    now = datetime(2026, 10, 15, 0, 50)
    for planes in (SAMPLE, [], None):
        assert draw(now, planes, ROUTES, 25).size == SCREEN, "draws with planes, an empty sky, and nothing yet"
    page = Page(planes=SAMPLE); page.routes = ROUTES
    key, bg = page.background(now)
    assert bg.mode == "LA" and page.background(now)[0] == key, "redrawn only when the data or minute changes"
    assert page.regions(now, 0) == [] and SW > SCREEN[0] // 2 or TALL, "the map takes most of the screen"
    town = dict(town, roads=[["motorway", [[39.70, -75.70], [39.72, -75.50]]]])
    lines = basemap(town, 39.71, -75.62, 25)[2]
    assert lines.getpixel((lines.width // 2, 2))[3] == 0, "no rings or crosshair: above the beacon is just the map"


def preview(now=None):
    """the page with the sample flights, for the emulator and kiosk.py --png"""
    page = Page(planes=SAMPLE); page.routes = ROUTES
    import kit
    return kit.unpack(page.background(now or datetime(2026, 10, 15, 0, 50))[1])
