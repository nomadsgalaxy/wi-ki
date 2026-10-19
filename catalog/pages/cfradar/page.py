"""The Cloudflare Radar page: Philadelphia's corner of the Internet, as Cloudflare sees it, laid out like Radar itself:
its header and breadcrumbs, and rounded cards. Radar's finest place is a state, so it's Pennsylvania's traffic, and the
networks that carry it: Comcast, headquartered in Philadelphia, first.

  traffic trends   Pennsylvania's HTTP requests over the last 24 hours, every 15 minutes, against the day before
  the map          Pennsylvania in pixels, Philadelphia pulsing (the page's one moving part), Pittsburgh and Harrisburg
  networks         the networks Pennsylvania's traffic comes from, then people against bots and mobile against desktop
  quality          Comcast's and Verizon's speed tests over 90 days, and the outages and anomalies Radar has flagged in
                   the US in four weeks

It fetches from the Cloudflare Radar API every 15 minutes (Radar's own step), in a background thread, into CACHE,
which every renderer shares; a failed fetch keeps the last one and says how old it is. The API needs a token with the
Radar Read permission, read from TOKEN (outside the repo; never put it in the playlist). Without one, the page says so.

Options (in playlist.json): geo, the region's Radar geoId (default 6254927, Pennsylvania); name, what to call it
(default PENNSYLVANIA); asns, the two networks to compare (default [7922, 701], Comcast and Verizon).
Cloudflare's orange, yellow and blue, and only this page uses them.
"""
import json, math, os, tempfile, time, urllib.parse, urllib.request
from datetime import datetime, timezone
from PIL import Image, ImageDraw

from kit import SCREEN, W, G, D, A, Simple, text, clock, packed, local

API = "https://api.cloudflare.com/client/v4/radar/"
TOKEN = os.path.expanduser("~/.config/kiosk/cloudflare-radar.token")
CACHE = os.path.expanduser("~/.cache/kiosk/cfradar.json")   # cache_for() makes it per region and networks
EVERY = 900
ORANGE, YELLOW, GREY, INK, PANEL = (0xf3, 0x80, 0x20), (0xfa, 0xad, 0x3f), (0x40, 0x40, 0x41), (14, 14, 16), (26, 26, 30)
BLUE, CARD, EDGE, MUTED, GOOD = (0x3e, 0x8a, 0xf7), (28, 29, 33), (52, 54, 60), (150, 152, 160), (0x2b, 0xb5, 0x6b)
# Pennsylvania's border (longitude, latitude), clockwise from the south-west corner: the Mason-Dixon line, the Delaware
# up past Philadelphia, New York's line, the Erie notch, and down the Ohio line
PA = [(-80.52, 39.72), (-75.79, 39.72), (-75.42, 39.80), (-75.13, 39.95), (-74.97, 40.05), (-74.72, 40.15), (-74.76, 40.42),
      (-75.06, 40.62), (-75.20, 40.86), (-75.07, 41.02), (-74.82, 41.29), (-74.69, 41.36), (-75.02, 41.62), (-75.06, 41.85),
      (-75.36, 42.00), (-79.76, 42.00), (-79.76, 42.27), (-80.52, 41.98)]
CITIES = [("PHILADELPHIA", -75.17, 39.95), ("PITTSBURGH", -80.00, 40.44), ("HARRISBURG", -76.88, 40.27)]
MAP = (330, 228)                 # the map's size in screen pixels
MAP_PIX = 3                      # drawn this many times smaller and scaled up, for the pixel look
PULSE = 16                       # frames in Philadelphia's pulse
NAMES = {7922: "Comcast", 701: "Verizon", 6167: "Verizon Wireless", 21928: "T-Mobile", 3737: "PenTeleData", 7018: "AT&T"}


def cache_for(geo, asns):
    """CACHE, one per region and pair of networks, so a second cfradar page with other options doesn't read the first's"""
    return CACHE.replace(".json", "-" + "-".join(str(x) for x in (geo, *asns)) + ".json")


def finite(rows):
    """the (time, value) rows that are a pair of a time string and a real number (JSON lets NaN and Infinity through, and
    a row can be anything); rows itself that isn't a list is no rows"""
    return [r for r in rows if isinstance(r, (list, tuple)) and len(r) == 2 and isinstance(r[0], str)
            and isinstance(r[1], (int, float)) and not isinstance(r[1], bool) and math.isfinite(r[1])] if isinstance(rows, (list, tuple)) else []


def cloud():
    """a pixel cloud, 22x12, in Cloudflare's orange with its yellow underneath, RGBA"""
    img = Image.new("RGBA", (22, 12)); d = ImageDraw.Draw(img)
    for box in ((1, 5, 9, 11), (5, 2, 14, 11), (10, 0, 19, 10), (14, 5, 21, 11)):
        d.ellipse(box, fill=ORANGE)
    d.rectangle((3, 9, 19, 11), fill=YELLOW)
    return img


def fetch(token, geo, asns):
    """the page's data from Radar: {"traffic": [(iso, value)], "networks": [(asn, name, %)], "bots": %, "quality":
    {asn: {...}}, "events": [(start, what)], "fetched": iso}"""
    def get(path, **query):
        req = urllib.request.Request(API + path + "?" + urllib.parse.urlencode(query, doseq=True),
                                     headers={"Authorization": f"Bearer {token}", "User-Agent": "wi-ki"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)["result"]
    s = get("http/timeseries", geoId=geo, dateRange="2d")["serie_0"]
    top = get("http/top/ases", geoId=geo, dateRange="1d", limit=5)["top_0"]
    bots = get("http/summary/bot_class", geoId=geo, dateRange="1d")["summary_0"]
    quality = {str(a): get("quality/speed/summary", asn=a)["summary_0"] for a in asns}
    devices = get("http/summary/device_type", geoId=geo, dateRange="1d")["summary_0"]
    outages = get("annotations/outages", location="US", dateRange="28d", limit=5).get("annotations", [])
    anomalies = get("traffic_anomalies", location="US", dateRange="28d", limit=5).get("trafficAnomalies", [])
    events = [(o["startDate"], o.get("description") or ", ".join(a["name"] for a in o.get("asnsDetails", [])) or "outage") for o in outages]
    events += [(a["startDate"], f"traffic anomaly · {(a.get('asnDetails') or {}).get('name') or (a.get('locationDetails') or {}).get('name', '')}") for a in anomalies]
    return {"traffic": list(zip(s["timestamps"], map(float, s["values"]))),
            "networks": [(t["clientASN"], t["clientASName"], float(t["value"])) for t in top],
            "bots": float(bots["bot"]), "mobile": float(devices.get("mobile", 0)), "quality": quality, "events": sorted(events, reverse=True)[:4],
            "fetched": datetime.now(timezone.utc).isoformat(timespec="seconds")}


WEST, EAST = min(p[0] for p in PA), max(p[0] for p in PA)
SOUTH, NORTH = min(p[1] for p in PA), max(p[1] for p in PA)
SQUASH = math.cos(math.radians((SOUTH + NORTH) / 2))   # a degree east is this much shorter than a degree north, here


def project(lon, lat):
    """a longitude and latitude in Pennsylvania -> pixels on the map (small: times MAP_PIX for the screen). One scale both
    ways, with longitude squashed for the latitude, so the state keeps its real shape, centred in the map"""
    w, h = MAP[0] // MAP_PIX, MAP[1] // MAP_PIX
    s = min((w - 4) / ((EAST - WEST) * SQUASH), (h - 4) / (NORTH - SOUTH))
    ox, oy = (w - (EAST - WEST) * SQUASH * s) / 2, (h - (NORTH - SOUTH) * s) / 2
    return (ox + (lon - WEST) * SQUASH * s, oy + (NORTH - lat) * s)


def state(pulse=None):
    """Pennsylvania in pixels: the state in dark orange with a bright border, the cities as dots, and, at pulse (0 to 1),
    a ring spreading out from Philadelphia, RGB at screen size"""
    w, h = MAP[0] // MAP_PIX, MAP[1] // MAP_PIX
    img = Image.new("RGB", (w, h), CARD); d = ImageDraw.Draw(img)
    border = [project(*p) for p in PA]
    d.polygon(border, fill=(82, 44, 14), outline=ORANGE)
    px, py = project(-75.17, 39.95)
    if pulse is not None:
        r = 2 + pulse * 18
        fade = tuple(round(c * (1 - pulse) + b * pulse) for c, b in zip(YELLOW, (82, 44, 14)))
        d.ellipse((px - r, py - r, px + r, py + r), outline=fade)
    for name, lon, lat in CITIES:
        x, y = project(lon, lat)
        d.rectangle((x - 1, y - 1, x + 1, y + 1), fill=YELLOW if name == "PHILADELPHIA" else W)
    img = img.resize((w * MAP_PIX, h * MAP_PIX), Image.NEAREST)
    for name, lon, lat in CITIES:   # the names, at screen size: Philadelphia's under its dot, Harrisburg's over it
        x, y = (round(c * MAP_PIX) for c in project(lon, lat))
        label = name.title()
        at = {"PHILADELPHIA": (x - len(label) * 8 + 8, y + 14), "HARRISBURG": (x - len(label) * 4, y - 26)}.get(name, (x + 10, y - 8))
        text(img, at, label, YELLOW if name == "PHILADELPHIA" else MUTED, scale=1)
    return img


def card(img, box, title, subtitle=""):
    """one of Radar's cards: rounded, edged, its title in grey capitals"""
    ImageDraw.Draw(img).rounded_rectangle(box, radius=14, fill=CARD, outline=EDGE, width=2)
    text(img, (box[0] + 18, box[1] + 14), title, MUTED, scale=1)
    if subtitle:
        text(img, (box[2] - 18, box[1] + 14), subtitle, D, scale=1, right=True)


def chart(points, size):
    """the last day's traffic as an orange line over an orange fill fading downwards, the day before dashed, gridlines
    and the hours along the bottom, RGB"""
    w, h = size
    img = Image.new("RGB", size, CARD); d = ImageDraw.Draw(img)
    points = finite(points); vals = [v for _, v in points]
    day = len(vals) // 2
    if day < 2:   # a day needs two points to be a line (the first half is yesterday): say so, don't divide by zero
        text(img, (w // 2 - 8 * 7, h // 2 - 8), "NO TRAFFIC DATA", A, scale=2)
        return img
    plot = h - 22                                           # room for the hours
    for g in range(1, 4):
        d.line((0, plot * g // 4, w, plot * g // 4), fill=EDGE)
    top = max(vals) or 1
    text(img, (4, 0), "relative traffic, scaled to the 2-day peak", MUTED, scale=1)   # Radar's series are relative, not request counts; the page stretches them so the peak of the two days fills the chart
    xy = lambda i, v, n: (round(i * (w - 1) / (n - 1)), round(plot - 2 - v / top * (plot - 22)))
    before, today = vals[:day], vals[day:]   # an odd count: today has the extra one, so it's 2 or more too
    line = [xy(i, v, len(today)) for i, v in enumerate(today)]
    fade = Image.new("RGB", size)                           # the fill: orange at the top fading to the card
    for y in range(h):
        k = max(0.0, 1 - y / plot) * 0.55
        ImageDraw.Draw(fade).line((0, y, w, y), fill=tuple(round(c * k + b * (1 - k)) for c, b in zip(ORANGE, CARD)))
    mask = Image.new("L", size); ImageDraw.Draw(mask).polygon(line + [(w - 1, plot), (0, plot)], fill=255)
    img.paste(fade, (0, 0), mask)
    dashed = [xy(i, v, len(before)) for i, v in enumerate(before)]
    for i in range(0, len(dashed) - 1, 2):
        d.line(dashed[i:i + 2], fill=MUTED, width=2)
    d.line(line, fill=ORANGE, width=3)
    d.ellipse((line[-1][0] - 6, line[-1][1] - 5, line[-1][0] + 4, line[-1][1] + 5), fill=YELLOW)
    stamps = [local(t.replace("Z", "+00:00")) for t, _ in points[day:]]
    for i, t in enumerate(stamps):
        if t.minute == 0 and t.hour % 6 == 0:
            x = round(i * (w - 1) / (len(stamps) - 1))
            d.line((x, plot, x, plot + 4), fill=MUTED)
            label = "12a" if t.hour == 0 else "12p" if t.hour == 12 else f"{t.hour % 12}{'a' if t.hour < 12 else 'p'}"
            text(img, (min(max(0, x - 12), w - 24), plot + 6), label, MUTED, scale=1)
    return img


def donut(img, centre, r, share, colours, names):
    """a Radar donut: share (0-100) of the ring in the first colour for names[0], the rest in the second for names[1];
    the first's share and name in the middle, and a key with both underneath, so it's clear which is which"""
    d = ImageDraw.Draw(img); x, y = centre
    d.pieslice((x - r, y - r, x + r, y + r), -90, -90 + 360 * share / 100, fill=colours[0])
    d.pieslice((x - r, y - r, x + r, y + r), -90 + 360 * share / 100, 270, fill=colours[1])
    d.ellipse((x - r + 12, y - r + 12, x + r - 12, y + r - 12), fill=CARD)
    text(img, (x - len(f"{share:.0f}%") * 8, y - 22), f"{share:.0f}%", W, scale=2)
    text(img, (x - len(names[0]) * 4, y + 8), names[0], colours[0], scale=1)
    key = [(names[0], share, colours[0]), (names[1], 100 - share, colours[1])]
    for i, (name, part, colour) in enumerate(key):   # the key: a swatch, the name and its share, one line each
        ky = y + r + 6 + i * 18
        d.rectangle((x - 60, ky + 4, x - 52, ky + 12), fill=colour)
        text(img, (x - 46, ky), f"{name} {part:.0f}%", MUTED, scale=1)


def draw(now, data, problem=None):
    """the whole page but the map's pulse, RGB at the screen's size"""
    img = Image.new("RGB", SCREEN, INK); d = ImageDraw.Draw(img)
    # Radar's header: the cloud, the name, the breadcrumbs, the range and the time
    d.rectangle((0, 0, SCREEN[0], 50), fill=(22, 22, 25)); d.line((0, 50, SCREEN[0], 50), fill=EDGE)
    c = cloud().resize((44, 24), Image.NEAREST); img.paste(c, (20, 13), c)
    text(img, (76, 9), "Cloudflare Radar", W, scale=2)
    text(img, (76 + 17 * 16 + 16, 17), "United States  ›  Pennsylvania  ›  Philadelphia", MUTED, scale=1)
    d.rounded_rectangle((SCREEN[0] - 340, 11, SCREEN[0] - 170, 39), radius=14, fill=CARD, outline=EDGE)
    text(img, (SCREEN[0] - 20, 9), clock(now), W, scale=2, right=True)
    if not data:
        text(img, (24, 120), problem or "asking Cloudflare Radar...", YELLOW if problem else W, scale=2)
        return img
    name = data.get("name", "PENNSYLVANIA").title()
    fetched = local(data["fetched"])
    age = (now - fetched).total_seconds()
    stale = age >= 3600
    T, B = 64, SCREEN[1] - (50 if stale else 14)   # stale: the foot of the screen is a row of its own
    # traffic trends
    traffic = finite(data["traffic"]); vals = [v for _, v in traffic]
    day = len(vals) // 2   # chart() draws the second half against the first, so it has a headline only with two points of each
    label = f"Last {round((local(traffic[-1][0].replace('Z', '+00:00')) - local(traffic[day][0].replace('Z', '+00:00'))).total_seconds() / 3600)} hours" if day >= 2 else "No traffic data"
    text(img, (SCREEN[0] - 255 - len(label) * 4, 17), label, W, scale=1)   # the span the chart really covers
    change = (vals[-1] / vals[len(vals) // 2 - 1] - 1) * 100 if len(vals) >= 2 and vals[len(vals) // 2 - 1] else 0
    card(img, (14, T, 774, B), "TRAFFIC TRENDS", f"HTTP requests · {name}")
    if day >= 2:
        text(img, (32, T + 38), f"{change:+.1f}%", ORANGE if change >= 0 else BLUE, scale=3)
        text(img, (32 + len(f"{change:+.1f}%") * 24 + 12, T + 50), "on this time yesterday", MUTED, scale=1)
    if day >= 2:
        text(img, (756, T + 50), "— today   - - yesterday", D, scale=1, right=True)
    img.paste(chart(traffic, (724, B - T - 110)), (32, T + 96))
    # the map
    card(img, (788, T, 1150, B), "WHERE", "Comcast HQ")
    comcast = next((share for asn, _, share in data["networks"] if asn == 7922), None)
    if comcast is not None:   # Radar's big-number style: Philadelphia's own network's share of the state
        text(img, (806, B - 96), f"{comcast:.1f}%", ORANGE, scale=4)
        text(img, (806, B - 30), "of the state's traffic is Comcast", MUTED, scale=1)
    # networks
    X0, X1 = 1164, 1530
    card(img, (X0, T, X1, B), "TOP NETWORKS", "share of requests")
    rows = data["networks"][:5]
    top = max([r[2] for r in rows if math.isfinite(r[2])], default=0)   # the biggest real share: a NaN or a tiny first one can't blow the bars up
    for i, (asn, full, share) in enumerate(rows):
        y = T + 40 + i * 38
        text(img, (X0 + 18, y), NAMES.get(asn, full.split(",")[0][:16]), W, scale=1)
        text(img, (X1 - 18, y), f"{share:.1f}%", MUTED, scale=1, right=True)
        width = min(X1 - X0 - 36, round((X1 - X0 - 36) * share / top)) if top > 0 and math.isfinite(share) and share > 0 else 0   # no real share: no bar
        bar = Image.new("RGB", (max(1, width), 10))
        for x in range(bar.width):   # each bar fades from orange to yellow, like Radar's
            k = x / max(1, bar.width - 1)
            ImageDraw.Draw(bar).line((x, 0, x, 9), fill=tuple(round(a * (1 - k) + b * k) for a, b in zip(ORANGE, YELLOW)))
        img.paste(bar, (X0 + 18, y + 20))
    donut(img, (X0 + 92, B - 110), 50, 100 - data["bots"], (ORANGE, BLUE), ("people", "bots"))
    donut(img, (X1 - 92, B - 110), 50, data.get("mobile", 0), (YELLOW, (110, 112, 120)), ("mobile", "desktop"))
    # quality
    X2, R = 1544, SCREEN[0] - 14
    card(img, (X2, T, R, B), "INTERNET QUALITY", "90 days")
    for i, (asn, q) in enumerate(data["quality"].items()):
        y = T + 40 + i * 118
        text(img, (X2 + 18, y), NAMES.get(int(asn), f"AS{asn}"), MUTED, scale=1)
        text(img, (X2 + 18, y + 18), f"{float(q['bandwidthDownload']):.0f}", W, scale=4)
        text(img, (X2 + 18 + len(f"{float(q['bandwidthDownload']):.0f}") * 32 + 8, y + 50), "Mbps down", MUTED, scale=1)
        text(img, (X2 + 18, y + 86), f"↑ {float(q['bandwidthUpload']):.0f} Mbps · {float(q['latencyIdle']):.0f} ms", G, scale=1)
    calm = not data["events"]
    d.rounded_rectangle((X2 + 18, B - 86, R - 18, B - 56), radius=15, fill=(18, 60, 38) if calm else (80, 40, 10),
                        outline=GOOD if calm else A)
    text(img, (X2 + 34, B - 79), "No US outages · 4 weeks" if calm else f"{len(data['events'])} US outages · 4 weeks",
         GOOD if calm else A, scale=1)
    if not calm:
        text(img, (X2 + 18, B - 112), f"{data['events'][0][0][5:10]} {data['events'][0][1]}"[:(R - X2 - 36) // 8], W, scale=1)
    img.paste(state(), (804, T + 44))
    if not stale:
        text(img, (R - 18, B - 30), f"radar.cloudflare.com · updated {clock(fetched)}", D, scale=1, right=True)
    else:   # stale: the numbers dimmed, and across the foot a bar of its own, not a small line under numbers that look current
        img.paste(Image.blend(img.crop((0, 51, SCREEN[0], B + 14)), Image.new("RGB", (SCREEN[0], B + 14 - 51), INK), .5), (0, 51))
        d.rounded_rectangle((14, B + 8, R, SCREEN[1] - 8), radius=14, fill=(80, 40, 10), outline=A)
        text(img, (32, B + 14), f"NO UPDATE FOR {round(age / 60)} MIN", A, scale=2)
        text(img, (R - 18, B + 22), f"radar.cloudflare.com · last answer {clock(fetched)}", A, scale=1, right=True)
    return img


def _sample():
    import math
    from datetime import timedelta
    start = datetime(2026, 10, 13, 20, 0)
    traffic = [((start + timedelta(minutes=15 * q)).isoformat() + "Z", 0.55 + 0.4 * math.sin((q - 40) / 96 * 2 * math.pi) ** 2) for q in range(192)]
    q = {"bandwidthDownload": "321.7", "bandwidthUpload": "57.0", "latencyIdle": "21.2"}
    return {"name": "PENNSYLVANIA", "traffic": traffic, "bots": 17.7, "mobile": 54.2,
            "networks": [(7922, "Comcast Cable Communications, LLC", 30.8), (701, "Verizon Business", 17.9),
                         (21928, "T-Mobile USA, Inc.", 11.3), (6167, "Verizon Business", 7.3), (3737, "PenTeleData Inc.", 4.7)],
            "quality": {"7922": q, "701": dict(q, bandwidthUpload="134.6", latencyIdle="11.8")},
            "events": [], "fetched": "2026-10-15T20:00:00+00:00"}


SAMPLE = _sample()


class Page(Simple):
    """Radar, as a page of the kiosk's cycle"""
    name, seconds, every, SAMPLE = "cfradar", 20, EVERY, SAMPLE
    fps = 4 if os.uname().machine.startswith("arm") else 8   # Philadelphia's pulse
    mark = (1216, 14)

    def __init__(self, geo=6254927, name="PENNSYLVANIA", asns=(7922, 701)):
        self.geo, self.label, self.asns = geo, name, list(asns)
        self.cache = cache_for(self.geo, self.asns)
        self.pulse = []   # Philadelphia's pulse, packed, made the first time it's needed

    def fetch(self):
        try:
            with open(TOKEN) as f:
                token = f.read().strip()
        except OSError:
            raise Trouble("needs a Radar token in ~/.config/kiosk/cloudflare-radar.token") from None
        try:
            data = dict(fetch(token, self.geo, self.asns), name=self.label)
            try:
                draw(datetime.now(), data)   # a reply the page can't draw doesn't replace the cache
            except Exception:
                raise ValueError("odd reply")
        except Exception as e:
            raise Trouble(f"Radar: {e}"[:60]) from e   # the last data stays; the page says how old it is
        return data

    def draw(self, img, now, data):
        img.paste(draw(now, data, self.problem and str(self.problem)))

    def moving(self, now, t, data):
        if not data:
            return []
        if not self.pulse:
            self.pulse = [packed(state(i / PULSE)) for i in range(PULSE)]
        return [(self.pulse[int(t * 8) % PULSE], (804, 64 + 44))]   # a ring every 2 s


class Trouble(Exception):
    """why there's no new data, as the page says it"""


def check():
    from datetime import timedelta
    from kit import unpack
    saved_tz = os.environ.get("TZ"); os.environ["TZ"] = "America/New_York"; time.tzset()   # the stale test compares a UTC stamp with a local now
    now = datetime(2026, 10, 15, 16, 10)
    for data, problem in ((SAMPLE, None), (None, None), (None, "needs a Radar token"), (dict(SAMPLE, events=[("2026-10-02T10:00:00Z", "Comcast fibre cut")]), None),
                          (dict(SAMPLE, traffic=[]), None)):
        assert draw(now, data, problem).size == SCREEN, "draws with data, waiting, without a token, with an outage, with no traffic"
    assert cloud().getbbox() and chart(SAMPLE["traffic"], (100, 50)).size == (100, 50)
    Page.check()
    page = Page.showing(SAMPLE)
    key, bg = page.background(now)
    assert bg.mode == "LA" and page.background(now)[0] == key
    a, b = page.regions(now, 0), page.regions(now, 1)
    assert a[0][1] == b[0][1] and a[0][0] is not b[0][0] and page.regions(now, 2)[0][0] is a[0][0], "the pulse moves and loops"
    assert all(0 <= x <= MAP[0] // MAP_PIX and 0 <= y <= MAP[1] // MAP_PIX for x, y in map(lambda p: project(*p), PA)), "the state fits"
    # the map keeps the state's real shape: its width over its height is the real one, to 2%
    xs, ys = zip(*(project(*q) for q in PA))
    real = (EAST - WEST) * math.cos(math.radians(41.0)) / (NORTH - SOUTH)
    assert abs((max(xs) - min(xs)) / (max(ys) - min(ys)) / real - 1) < 0.02, "Pennsylvania isn't stretched"
    # every city sits where its coordinates put it: the same share of the way across and down the state as on the
    # ground, to within one map pixel, and inside the border
    for name, lon, lat in CITIES:
        x, y = project(lon, lat)
        across = min(xs) + (lon - WEST) / (EAST - WEST) * (max(xs) - min(xs))
        down = min(ys) + (NORTH - lat) / (NORTH - SOUTH) * (max(ys) - min(ys))
        assert abs(x - across) <= 1 and abs(y - down) <= 1, f"{name} is at {x:.1f}, {y:.1f}, not {across:.1f}, {down:.1f}"
        inside = False
        for (ax, ay), (bx, by) in zip(PA, PA[1:] + PA[:1]):   # even-odd: a ray east from the city crosses the border oddly
            if (ay > lat) != (by > lat) and lon < ax + (lat - ay) * (bx - ax) / (by - ay):
                inside = not inside
        assert inside, f"{name} is inside Pennsylvania"
    # and against each other, as on the ground: west to east Pittsburgh, Harrisburg, Philadelphia; north to south
    # Pittsburgh (40.44), a little above Harrisburg (40.27), then Philadelphia (39.95)
    at = {name: project(lon, lat) for name, lon, lat in CITIES}
    (px, py), (hx, hy), (fx, fy) = at["PITTSBURGH"], at["HARRISBURG"], at["PHILADELPHIA"]
    assert px < hx < fx and py < hy < fy, at
    # odd data: a one-point or empty series, a zero first share, NaN, a mangled schema
    traffic = SAMPLE["traffic"]
    for pts in ([], traffic[:1], traffic[:2], traffic[:3], [("2026-10-15T16:00:00Z", float("nan"))] * 4, [(t, float("inf")) for t, _ in traffic[:6]]):
        assert chart(pts, (100, 50)).size == (100, 50), "a series too short to be a line draws a message, not a division by zero"
    assert chart(traffic[:2], (100, 50)).tobytes() != chart(traffic, (100, 50)).tobytes()
    zero = dict(SAMPLE, networks=[(7922, "Comcast", 0.0), (701, "Verizon", 0.0)])
    nan = dict(SAMPLE, networks=[(7922, "Comcast", float("nan"))], traffic=traffic[:1], bots=float("nan"))
    for data in (dict(SAMPLE, traffic=traffic[:1]), dict(SAMPLE, traffic=traffic[:3]), zero, nan, dict(SAMPLE, networks=[])):
        assert draw(now, data).size == SCREEN, "odd numbers draw"
    # a NaN or tiny first share can't make the bars huge or raise, and the bars stay inside their card
    X1 = 1530
    for nets in ([(7922, "Comcast", float("nan")), (701, "Verizon", 30.0)], [(7922, "Comcast", 1e-9), (701, "Verizon", 30.0)],
                 [(7922, "Comcast", -5.0), (701, "Verizon", float("inf"))], [(7922, "Comcast", 0.0)]):
        img = draw(now, dict(SAMPLE, networks=nets))
        assert all(img.getpixel((x, 64 + 40 + 38 + 25)) == INK for x in range(X1 + 2, X1 + 12)), "no bar leaves the networks card"
    bars = draw(now, dict(SAMPLE, networks=[(7922, "Comcast", float("nan")), (701, "Verizon", 30.0)]))
    assert bars.getpixel((1164 + 30, 64 + 40 + 38 + 25)) != CARD, "with a NaN first share the bars are scaled to the biggest real one"
    assert finite([5, None, ("t",), ("t", 1, 2), (1, 2), ("t", True), ("t", None), ("t", 3)]) == [("t", 3)] and finite(None) == finite(5) == []
    assert chart([5, None, ["t", "x"]], (100, 50)).size == (100, 50), "rows that aren't pairs are dropped, not raised on"
    assert draw(now, dict(SAMPLE, traffic=[1, 2, 3])).size == SCREEN
    # and what can't draw keeps the last good frame, or says so before there is one
    flaky = Page.showing(SAMPLE); good = flaky.background(now)[1]
    flaky.data = {"traffic": 5}
    marked = flaky.background(now + timedelta(minutes=1))[1]   # the next minute: a repeat failure
    assert marked.size == good.size and marked.tobytes() != good.tobytes(), "data that can't be drawn shows the last good data, marked"
    mark = lambda im: any(r > 200 and g > 150 and b < 140 for _, (r, g, b) in unpack(im).crop((800, 14, 1160, 30)).getcolors(99999))   # RGB565 rounds the amber
    assert mark(marked) and not mark(good), "with the marker in amber in the header"
    assert Page.showing({"traffic": 5}).background(now)[1].mode == "LA", "and with none yet, a no-data page"
    # the stale line is big and amber
    stale = draw(datetime(2026, 10, 15, 20, 0) + timedelta(hours=3), SAMPLE)
    row = lambda im: [c for _, c in im.crop((14, SCREEN[1] - 42, SCREEN[0] - 14, SCREEN[1] - 8)).getcolors(99999)]
    assert A in row(stale) and A not in row(draw(now, SAMPLE)), "stale says so, big and amber, in a row of its own"
    lit = lambda im: max(sum(c) for n, c in im.crop((32, 100, 140, 126)).getcolors(99999))
    assert lit(stale) < lit(draw(now, SAMPLE)), "and the numbers are dimmed"
    # no traffic data: no headline over the message, and the header's span is the chart's
    head = lambda data: [c for _, c in draw(now, data).crop((32, 100, 140, 124)).getcolors(99999)]
    assert ORANGE in head(SAMPLE) and ORANGE not in head(dict(SAMPLE, traffic=[])), "no data: no +0.0% headline"
    assert draw(now, SAMPLE).crop((SCREEN[0] - 340, 11, SCREEN[0] - 170, 39)).tobytes() != draw(now, dict(SAMPLE, traffic=SAMPLE["traffic"][-40:])).crop((SCREEN[0] - 340, 11, SCREEN[0] - 170, 39)).tobytes(), "the span label follows the data"
    # a failed fetch, or no token, waits a minute, not a tick, and says why; the cache is per region and networks
    global fetch, TOKEN, CACHE
    saved = fetch, TOKEN, CACHE
    tmp = tempfile.TemporaryDirectory(); here = tmp.name
    TOKEN, CACHE = os.path.join(here, "_no.token"), os.path.join(here, "_test_cache.json")
    page = Page()
    try:
        assert cache_for(1, [2, 3]) != cache_for(1, [3, 2]) != cache_for(4, [2, 3]) and page.cache != Page(geo=1).cache != Page(asns=(1, 2)).cache
        page.fetch_now()
        assert "token" in str(page.problem) and time.time() - page._tried < 5 and not page._busy
        opened = []
        real_open = open
        globals()["open"] = lambda *a, **k: (opened.append(a), real_open(*a, **k))[1]
        try:
            page.background(now)
        finally:
            del globals()["open"]
        assert not opened and not page._busy, "a tick right after a failure doesn't touch the token or fetch again"
        with open(TOKEN, "w") as f:
            f.write("x")
        calls = []
        def down(*a):
            calls.append(a); raise OSError("down")
        fetch = down
        page.fetch_now()
        assert str(page.problem).startswith("Radar:") and len(calls) == 1
        page.background(now)
        assert len(calls) == 1, "after a failed fetch, the next tick waits"
        fetch = lambda *a: {"traffic": 5}   # a reply that can't be drawn doesn't replace the cache
        page.fetch_now()
        assert str(page.problem) == "Radar: odd reply" and not os.path.exists(page.cache), "an undrawable reply isn't cached"
        fetch = lambda *a: SAMPLE
        page.fetch_now()
        assert page.problem is None and os.path.exists(page.cache), "a drawable one is"
    finally:
        fetch, TOKEN, CACHE = saved
        tmp.cleanup()
        if saved_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = saved_tz
        time.tzset()


def preview(now=None):
    """the page with the sample, for the emulator and kiosk.py --png"""
    import kit
    page = Page.showing(SAMPLE); now = now or datetime(2026, 10, 15, 16, 10)
    img = page.background(now)[1].copy()
    for part, xy in page.regions(now, 0.6):
        img.paste(part, xy)
    return kit.unpack(img)
