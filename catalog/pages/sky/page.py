"""Sky: the kiosk's own sky, all the way round. The screen is a panorama of the horizon, north round to north with south
in the middle (north, in the southern hemisphere), and the sky over it as it is now: blue by day with the sun where it
is, a glow where it's setting, then dusk, and as it gets dark the stars come out, brightest first, with the
constellations drawn between them and named, the planets, and the moon in its phase. Along the bottom, a town's
rooftops, lit up at night. Above it, sunrise, sunset and the day's length, the moon's phase and next full and new,
and tonight's clouds. During the day it says which planets will be up this evening.

The sun, moon, planets and stars are all worked out here, from the date and the place, with no network. The sun is
good to about a minute, the planets to a fraction of a degree, and the full and new moons to about an hour. The stars
and constellation lines are d3-celestial's (stars.json, BSD 3-Clause). The clouds are Open-Meteo's forecast (no key),
fetched every half hour into a cache every renderer on the machine shares (kit.Simple); they dim the sky as much as
they would. Without them the page still draws, just clear.

Options (in playlist.json, or the setup page's Location): lat and lon (default: central Philadelphia), and place, for
the heading.
"""
import json, math, os, random, time, urllib.parse, urllib.request
from datetime import datetime, timedelta
from PIL import Image, ImageChops, ImageDraw

from kit import SCREEN, Simple, O, W, G, D, B, A, BG, RULE, RAISED, text, masthead, clock, icon

J2000 = 946728000            # 2000-01-01 12:00 UTC, as a Unix time
MONTH = 29.530588853         # days from new moon to new moon, on average
RISE = -0.833                # the sun's height at sunrise and sunset: its radius, and the air bending its light
TOP = 92                     # the panorama, under the masthead
HORIZON = SCREEN[1] - 44     # the horizon; the town below it
PX = SCREEN[0] / 360         # pixels a degree, round and up alike (5.3 on the bar: up to about 72 degrees shows)
API = "https://api.open-meteo.com/v1/forecast?"
UA = {"User-Agent": "wi-ki sky (github.com/nomadsgalaxy/wi-ki)"}
mix = lambda colour, k: tuple(round(c * k + b * (1 - k)) for c, b in zip(colour, BG))   # a token, faded toward the background
# the sky's colour by the sun's height: (height, top of the sky, at the horizon); in between, a blend of the two nearest
SKY = ((6, (30, 78, 120), (120, 176, 214)), (0, (40, 60, 110), (232, 142, 92)), (-6, (24, 26, 64), (110, 70, 110)),
       (-12, (10, 12, 34), (30, 30, 70)), (-18, BG, (12, 14, 32)))
TOWN, WINDOW = (6, 7, 18), (255, 206, 106)
TILT = math.radians(23.43928)   # the Earth's axial tilt, which turns the ecliptic into RA and Dec
# the planets you can see without a telescope: JPL's Keplerian elements for 1800-2050 (Standish), each as its value at
# J2000 and its change per century: a (au), e, I, L, the longitude of perihelion and of the ascending node (degrees)
PLANETS = {
    "MERCURY": ((0.38709927, 0.00000037), (0.20563593, 0.00001906), (7.00497902, -0.00594749),
                (252.25032350, 149472.67411175), (77.45779628, 0.16047689), (48.33076593, -0.12534081)),
    "VENUS": ((0.72333566, 0.00000390), (0.00677672, -0.00004107), (3.39467605, -0.00078890),
              (181.97909950, 58517.81538729), (131.60246718, 0.00268329), (76.67984255, -0.27769418)),
    "EARTH": ((1.00000261, 0.00000562), (0.01671123, -0.00004392), (-0.00001531, -0.01294668),
              (100.46457166, 35999.37244981), (102.93768193, 0.32327364), (0.0, 0.0)),
    "MARS": ((1.52371034, 0.00001847), (0.09339410, 0.00007882), (1.84969142, -0.00813131),
             (-4.55343205, 19140.30268499), (-23.94362959, 0.44441088), (49.55953891, -0.29257343)),
    "JUPITER": ((5.20288700, -0.00011607), (0.04838624, -0.00013253), (1.30439695, -0.00183714),
                (34.39644051, 3034.74612775), (14.72847983, 0.21252668), (100.47390909, 0.20469106)),
    "SATURN": ((9.53667594, -0.00125060), (0.05386179, -0.00050991), (2.48599187, 0.00193609),
               (49.95424423, 1222.49362201), (92.59887831, -0.41897216), (113.66242448, -0.28867794))}
SHADE = {"MERCURY": G, "VENUS": W, "MARS": (255, 120, 90), "JUPITER": A, "SATURN": (230, 200, 140)}
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "stars.json")) as _f:
    STARMAP = json.load(_f)   # {"stars": [[RA, Dec, magnitude, B-V]], "lines": {constellation: [[[RA, Dec], ...]]}}


def sky_place(ts, ra, dec, lat, lon):
    """where something at ra and dec (degrees) is in the sky at Unix time ts, from lat and lon -> (height above the
    horizon, compass bearing), in degrees"""
    d = (ts - J2000) / 86400
    hour = math.radians((280.46061837 + 360.98564736629 * d + lon - ra) % 360)
    la, dec = math.radians(lat), math.radians(dec)
    up = math.degrees(math.asin(math.sin(la) * math.sin(dec) + math.cos(la) * math.cos(dec) * math.cos(hour)))
    bearing = math.degrees(math.atan2(-math.sin(hour), math.tan(dec) * math.cos(la) - math.sin(la) * math.cos(hour))) % 360
    return up, bearing


def sun_place(ts):
    """the sun's RA and Dec in degrees at Unix time ts (the Almanac's low-precision formulas: good to about a hundredth
    of a degree this century)"""
    d = (ts - J2000) / 86400
    g = math.radians(357.529 + 0.98560028 * d)
    ecl = math.radians(280.459 + 0.98564736 * d + 1.915 * math.sin(g) + 0.020 * math.sin(2 * g))
    tilt = math.radians(23.439 - 0.00000036 * d)
    return (math.degrees(math.atan2(math.cos(tilt) * math.sin(ecl), math.cos(ecl))) % 360,
            math.degrees(math.asin(math.sin(tilt) * math.sin(ecl))))


def sun(ts, lat, lon):
    """the sun's height above the horizon in degrees, at Unix time ts, from lat and lon"""
    return sky_place(ts, *sun_place(ts), lat, lon)[0]


def moon_place(ts):
    """the moon's RA and Dec in degrees at Unix time ts, from its biggest wobbles (good to about half a degree)"""
    d = (ts - J2000) / 86400
    r = lambda deg: math.radians(deg % 360)
    mp, D, F, g = r(134.9633964 + 13.06499295 * d), r(297.8501921 + 12.19074912 * d), r(93.2720950 + 13.22935024 * d), r(357.529 + 0.98560028 * d)
    lon = math.radians(218.3164477 + 13.17639648 * d + 6.289 * math.sin(mp) + 1.274 * math.sin(2 * D - mp)
                       + 0.658 * math.sin(2 * D) + 0.214 * math.sin(2 * mp) - 0.186 * math.sin(g) - 0.114 * math.sin(2 * F))
    lat = math.radians(5.128 * math.sin(F))
    return (math.degrees(math.atan2(math.sin(lon) * math.cos(TILT) - math.tan(lat) * math.sin(TILT), math.cos(lon))) % 360,
            math.degrees(math.asin(math.sin(lat) * math.cos(TILT) + math.cos(lat) * math.sin(TILT) * math.sin(lon))))


def orbit(name, ts):
    """a planet's place around the sun at Unix time ts -> (x, y, z) in au, on the ecliptic"""
    T = (ts - J2000) / 86400 / 36525
    a, e, inc, L, peri, node = (v + rate * T for v, rate in PLANETS[name])
    m = math.radians((L - peri) % 360)
    E = m + e * math.sin(m)
    for _ in range(6):   # Kepler's equation, by Newton's method
        E -= (E - e * math.sin(E) - m) / (1 - e * math.cos(E))
    x, y = a * (math.cos(E) - e), a * math.sqrt(1 - e * e) * math.sin(E)
    w, n, i = math.radians(peri - node), math.radians(node), math.radians(inc)
    return ((math.cos(w) * math.cos(n) - math.sin(w) * math.sin(n) * math.cos(i)) * x
            + (-math.sin(w) * math.cos(n) - math.cos(w) * math.sin(n) * math.cos(i)) * y,
            (math.cos(w) * math.sin(n) + math.sin(w) * math.cos(n) * math.cos(i)) * x
            + (-math.sin(w) * math.sin(n) + math.cos(w) * math.cos(n) * math.cos(i)) * y,
            math.sin(w) * math.sin(i) * x + math.cos(w) * math.sin(i) * y)


def planet(name, ts):
    """a planet as we see it at Unix time ts -> (RA, Dec) in degrees"""
    p, e = orbit(name, ts), orbit("EARTH", ts)
    x, y, z = (p[k] - e[k] for k in range(3))
    y, z = y * math.cos(TILT) - z * math.sin(TILT), y * math.sin(TILT) + z * math.cos(TILT)
    return math.degrees(math.atan2(y, x)) % 360, math.degrees(math.atan2(z, math.hypot(x, y)))


def compass(bearing):
    return ("N", "NE", "E", "SE", "S", "SW", "W", "NW")[round(bearing / 45) % 8]


def crossings(start, lat, lon, minutes=1440):
    """sunrise and sunset in the day from Unix time start -> (rise, set), each a Unix time or None (polar days)"""
    rise = sets = None
    before = sun(start, lat, lon) - RISE
    for m in range(1, minutes + 1):
        now = sun(start + m * 60, lat, lon) - RISE
        if (before < 0) != (now < 0):
            at = start + (m - 1 + before / (before - now)) * 60   # between the two minutes, in a straight line
            if now > 0 and rise is None:
                rise = at
            elif now < 0 and sets is None:
                sets = at
        before = now
    return rise, sets


def elongation(ts):
    """how far the moon is round from the sun at Unix time ts, along the ecliptic: 0 is new, 180 full (degrees). The
    moon's place from its six biggest wobbles, good to about a third of a degree, so the phases to within an hour"""
    d = (ts - J2000) / 86400
    r = lambda deg: math.radians(deg % 360)
    g = r(357.529 + 0.98560028 * d)                      # the sun's mean anomaly, as in sun()
    sun_ = 280.459 + 0.98564736 * d + 1.915 * math.sin(g) + 0.020 * math.sin(2 * g)
    mp, D, F = r(134.9633964 + 13.06499295 * d), r(297.8501921 + 12.19074912 * d), r(93.2720950 + 13.22935024 * d)
    moon_ = (218.3164477 + 13.17639648 * d + 6.289 * math.sin(mp) + 1.274 * math.sin(2 * D - mp) + 0.658 * math.sin(2 * D)
             + 0.214 * math.sin(2 * mp) - 0.186 * math.sin(g) - 0.114 * math.sin(2 * F))
    return (moon_ - sun_) % 360


def moon(ts):
    """-> (its age in days since new, how much is lit from 0 to 1, its phase's name)"""
    e = elongation(ts)
    names = ("NEW MOON", "WAXING CRESCENT", "FIRST QUARTER", "WAXING GIBBOUS",
             "FULL MOON", "WANING GIBBOUS", "LAST QUARTER", "WANING CRESCENT")
    return e / 360 * MONTH, (1 - math.cos(math.radians(e))) / 2, names[int(e / 45 + 0.5) % 8]


def next_phase(ts, angle):
    """the next Unix time after ts when the moon is angle round from the sun (180 full, 0 new)"""
    past = lambda t: (elongation(t) - angle) % 360   # grows through the month, and drops back to 0 when it gets there
    a, before = ts, past(ts)
    while True:
        b = a + 6 * 3600; now = past(b)
        if now < before:   # it got there between a and b
            break
        a, before = b, now
    for _ in range(20):   # to within a few seconds
        mid = (a + b) / 2
        if past(mid) < before:
            b = mid
        else:
            a = mid
    return b


def disc(age, size, south=False):
    """the moon at age, as a picture size across: the lit part in Starlight, the rest faint. In the south it's the other
    way round"""
    img = Image.new("RGBA", (size, size)); r = size / 2
    turn = math.cos(2 * math.pi * age / MONTH)
    for y in range(size):
        w = math.sqrt(max(0, r * r - (y + 0.5 - r) ** 2))
        if w < 0.5:
            continue
        lit = (w * turn, w) if age < MONTH / 2 else (-w, -w * turn)   # growing on the right, then shrinking from it
        if south:
            lit = (-lit[1], -lit[0])
        for x in range(size):
            dx = x + 0.5 - r
            if abs(dx) <= w:
                img.putpixel((x, y), W + (255,) if lit[0] <= dx <= lit[1] else RULE + (255,))
    return img


def length(seconds):
    return f"{int(seconds // 3600)}h {int(seconds % 3600 // 60):02d}m"


def utc(*when):
    """a UTC time -> its Unix time, whatever zone this machine is in"""
    return (datetime(*when) - datetime(1970, 1, 1)).total_seconds()


def clean(raw):
    """Open-Meteo's hourly cloud cover -> {"2026-10-19T21:00": percent}, or None with none of it"""
    hourly = raw.get("hourly") if isinstance(raw, dict) else None
    if not isinstance(hourly, dict) or not isinstance(hourly.get("time"), list) or not isinstance(hourly.get("cloud_cover"), list):
        return None
    out = {}
    for when, cover in zip(hourly["time"], hourly["cloud_cover"]):
        try:
            cover = float(cover)
        except (TypeError, ValueError, OverflowError):
            continue
        if math.isfinite(cover):
            out[str(when)[:13] + ":00"] = max(0, min(100, round(cover)))
    return out or None


def cloudy(cover):
    """a cloud cover percentage, in words for stargazing"""
    return "CLEAR" if cover < 20 else "SOME CLOUD" if cover < 50 else "MOSTLY CLOUDY" if cover < 85 else "OVERCAST"


class Page(Simple):
    """the sun, the night sky and the moon, as a page of the kiosk's cycle"""
    name, seconds = "sky", 20
    every = 1800   # the cloud forecast; everything else is worked out here
    SAMPLE = {"hourly": {"time": [f"2026-10-{19 + h // 24}T{h % 24:02d}:00" for h in range(48)],
                         "cloud_cover": [round(50 + 50 * math.sin(h / 5)) for h in range(48)]}}   # as fetch() gives it
    clean = staticmethod(clean)
    _days = {}   # (date, lat, lon) -> the day worked out: it only changes with the date

    def __init__(self, lat=39.95, lon=-75.17, place=None):
        self.lat, self.lon = max(-90.0, min(90.0, float(lat))), (float(lon) + 180) % 360 - 180
        self.place, self.sunspot, self.behind = place, None, None

    def fetch(self):
        query = urllib.parse.urlencode({"latitude": self.lat, "longitude": self.lon, "timezone": "auto",
                                        "forecast_days": 2, "hourly": "cloud_cover"})
        with urllib.request.urlopen(urllib.request.Request(API + query, headers=UA), timeout=20) as r:
            raw = json.load(r)
        return {"hourly": raw.get("hourly")}

    def day(self, when):
        """the day of when, worked out once: sunrise and sunset, and yesterday's day length"""
        key = (when, self.lat, self.lon)
        if key not in self._days:
            start = time.mktime(datetime.combine(when, datetime.min.time()).timetuple())
            end = time.mktime(datetime.combine(when + timedelta(days=1), datetime.min.time()).timetuple())   # 23 or 25 h when the clocks change
            rise, sets = crossings(start, self.lat, self.lon, round((end - start) / 60))
            before = crossings(start - 86400, self.lat, self.lon)
            self._days.clear()   # one day at a time is plenty
            self._days[key] = {"rise": rise, "set": sets, "noon": sun(start + 12 * 3600, self.lat, self.lon),
                               "yesterday": (before[1] - before[0]) % 86400 if None not in before else None}
        return self._days[key]

    def where(self, ts, ra, dec):
        """something at ra and dec, on the screen at Unix time ts -> (x, y, its height above the horizon)"""
        up, bearing = sky_place(ts, ra, dec, self.lat, self.lon)
        middle = 0 if self.lat < 0 else 180   # face the way the sun goes: south, or north in the southern hemisphere
        return (bearing - middle + 180) % 360 * PX, HORIZON - up * PX, up

    def planets(self, ts):
        """the planets up at Unix time ts that you could see then -> [(name, x, y, height, bearing)], highest first"""
        out = []
        for name in SHADE:
            ra, dec = planet(name, ts)
            x, y, up = self.where(ts, ra, dec)
            if up > 5 and (name != "MERCURY" or up > 10):   # Mercury only shows when it's clear of the glow
                out.append((name, x, y, up, sky_place(ts, ra, dec, self.lat, self.lon)[1]))
        return sorted(out, key=lambda p: -p[3])

    def tonight(self, now, day):
        """when to say what's up this evening -> (Unix time, what to call it), or None if it never gets dark: an hour
        and a half after sunset, once it's set and it's not dark yet"""
        ts = time.mktime(now.timetuple())
        if day["set"] and day["set"] > ts:
            at = day["set"] + 90 * 60
            return at, "TONIGHT AT " + clock(datetime.fromtimestamp(at - at % 900))
        return None

    def draw(self, img, now, data):
        clouds = data if isinstance(data, dict) else {}
        ts, day = time.mktime(now.timetuple()), self.day(now.date())
        sun_ra, sun_dec = sun_place(ts)
        sx, sy, sun_up = self.where(ts, sun_ra, sun_dec)
        cover = clouds.get(now.strftime("%Y-%m-%dT%H:00"))
        w, h = SCREEN[0], HORIZON - TOP
        # the sky: a blend from its top to the horizon by the sun's height, and a glow round where the sun is low
        top, low = shade(sun_up)
        sky = Image.new("RGB", (1, h)); d = ImageDraw.Draw(sky)
        for y in range(h):
            k = (y / h) ** 2
            d.point((0, y), tuple(round(a * (1 - k) + b * k) for a, b in zip(top, low)))
        sky = sky.resize((w, h))
        if -12 < sun_up < 8:   # the glow: strongest near the sun, over the bottom of the sky
            near = Image.new("L", (w, 1)); n = ImageDraw.Draw(near)
            for x in range(w):
                apart = min(abs(x - sx), w - abs(x - sx)) / PX   # degrees round from the sun, either way
                n.point((x, 0), round(255 * max(0, 1 - apart / 70) * max(0, 1 - abs(sun_up - 0) / 12)))
            fade = Image.new("L", (1, h)); f = ImageDraw.Draw(fade)
            for y in range(h):
                f.point((0, y), round(255 * (y / h) ** 3))
            glow = ImageChops.multiply(near.resize((w, h)), fade.resize((w, h)))
            sky = Image.composite(Image.new("RGB", (w, h), (255, 150, 80)), sky, glow.point(lambda v: v * 6 // 10))
        img.paste(sky, (0, TOP))
        d = ImageDraw.Draw(img)
        # the stars, once it's dark enough to see them: the faintest that shows gets fainter as the sun goes down, and
        # clouds take some back
        faintest = min(4.5, -1 + (-4 - sun_up) * 0.47) - (cover or 0) / 100 * 3
        fit = lambda x, y: 0 <= x < w and TOP <= y < HORIZON
        if faintest > 1.5:   # the constellations, faint lines between their stars, and their names
            line = blend(mix(B, 0.42), top, min(1, (faintest - 1.5) / 2))
            taken = []
            for name, segments in sorted(STARMAP["lines"].items(), key=lambda c: -sum(map(len, c[1]))):
                points = []
                for segment in segments:
                    spots = [self.where(ts, ra, dec) for ra, dec in segment]
                    points += spots
                    for (x0, y0, u0), (x1, y1, u1) in zip(spots, spots[1:]):
                        if u0 > 0 and u1 > 0 and abs(x1 - x0) < w / 2:   # both up, and not across the screen's edge
                            d.line((x0, y0, x1, y1), fill=line)
                up = [(x, y) for x, y, u in points if u > 0]
                if len(up) == len(points) and faintest > 2.5:   # a name for the ones all the way up, where it fits
                    xs = [x for x, _ in up]
                    if max(xs) - min(xs) < w / 2:
                        lx, ly = sum(xs) / len(xs), max(y for _, y in up) + 8
                        box = (lx - len(name) * 4, ly, lx + len(name) * 4, ly + 16)
                        if box[3] < HORIZON - 40 and not any(box[0] < t[2] and t[0] < box[2] and box[1] < t[3] and t[1] < box[3] for t in taken):
                            text(img, (round(box[0]), round(ly)), name.upper(), line, scale=1); taken.append(box)
        if faintest > -1:
            for ra, dec, mag, bv in STARMAP["stars"]:
                if mag > faintest:
                    break   # they're brightest first
                x, y, up = self.where(ts, ra, dec)
                if up <= 0 or not fit(x, y):
                    continue
                colour = blend((170, 200, 255) if bv < 0 else (236, 240, 255) if bv < 0.5 else (255, 238, 206) if bv < 1 else (255, 204, 160),
                               top, min(1, (faintest - mag) / 1.2 + 0.45))
                r = 2 if mag < 1 else 1 if mag < 2.2 else 0.5 if mag < 3.5 else 0   # big enough to see across a room
                d.rectangle((round(x - r), round(y - r), round(x + r), round(y + r)), fill=colour)
        # the planets that are up, and named, once it's dark enough for them to show
        for name, x, y, up, _ in self.planets(ts) if sun_up < -3 else []:
            if fit(x, y):
                d.rectangle((round(x) - 3, round(y) - 3, round(x) + 3, round(y) + 3), fill=SHADE[name])
                text(img, (round(x) + 8, round(y) - 6), name, SHADE[name], scale=1)
        # the moon, in its phase, wherever it is (day or night)
        age, lit, phase = moon(ts)
        mx, my, moon_up = self.where(ts, *moon_place(ts))
        if moon_up > -1 and fit(mx, my):
            m = disc(age, 40, self.lat < 0)
            img.paste(m, (round(mx) - 20, round(my) - 20), m)
        if cover:   # the clouds: the sky goes grey and dim as much as they cover it
            part = img.crop((0, TOP, w, HORIZON))
            grey = (210, 214, 222) if sun_up > 0 else (34, 36, 48)
            img.paste(Image.blend(part, Image.new("RGB", part.size, grey), cover / 100 * 0.55), (0, TOP))
        town(img, sun_up, 0 if self.lat < 0 else 180)
        # the sun, where it is: moving() draws it, so it can shine
        self.sunspot = (round(sx) - 24, round(sy) - 24) if sun_up > -2 and 0 <= sx - 24 and sx + 24 <= w and sy + 24 <= HORIZON else None
        if self.sunspot:
            self.behind = img.crop((*self.sunspot, self.sunspot[0] + 48, self.sunspot[1] + 48))
        ImageDraw.Draw(img).rectangle((0, 0, w, TOP - 1), fill=BG)   # lines that ran up past the sky's top, gone
        place = str(self.place or "")[:24].upper()
        masthead(img, now, "// SKY" + (f" · {place}" if place else ""), "SUN, STARS & MOON")
        self.words(img, now, ts, day, clouds, cover, phase, lit)

    def words(self, img, now, ts, day, clouds, cover, phase, lit):
        """the day's times on the left, the moon and the clouds on the right, and tonight's planets during the day"""
        rise, sets = day["rise"], day["set"]
        if rise and sets:
            long, was = (sets - rise) % 86400, day["yesterday"]
            said = [("SUNRISE ", G), (clock(datetime.fromtimestamp(rise)), W), ("  SUNSET ", G),
                    (clock(datetime.fromtimestamp(sets)), W), ("  DAY ", G), (length(long), W)]
            if was:
                change = round(long - was)
                said.append((f"  {'+' if change >= 0 else '-'}{abs(change) // 60}m {abs(change) % 60:02d}s", O if change >= 0 else B))
        else:
            said = [("THE SUN STAYS " + ("UP" if day["noon"] > RISE else "DOWN") + " ALL DAY", W)]
        x = 24
        for words, colour in said:
            x += text(img, (x, 100), words, colour, scale=2)
        tonight = self.tonight(now, day)
        if tonight and sun(ts, self.lat, self.lon) > -3:
            at, title = tonight
            up = self.planets(at)
            later = clouds.get(datetime.fromtimestamp(at).strftime("%Y-%m-%dT%H:00"))
            line = title + ": " + (", ".join(f"{name.title()} {compass(bearing)}" for name, _, _, _, bearing in up) or "no bright planets")
            if later is not None:
                line += f" · {cloudy(later).lower()}"
            text(img, (24, 136), line[:110], O, scale=1)
        R = SCREEN[0] - 24
        text(img, (R, 100), f"{phase} · {round(lit * 100)}%", W, scale=2, right=True)
        full, new = (datetime.fromtimestamp(next_phase(ts, angle)) for angle in (180, 0))
        text(img, (R, 136), f"full {full.strftime('%a %b')} {full.day}, {clock(full)} · new {new.strftime('%a %b')} {new.day}", G, scale=1, right=True)
        if cover is not None:
            text(img, (R, 156), f"{cloudy(cover).lower()} · {cover}% cloud", A if cover >= 50 else G, scale=1, right=True)
        text(img, (R, 176 if cover is not None else 156), "stars: d3-celestial · clouds: open-meteo.com", D, scale=1, right=True)

    def moving(self, now, t, data):
        """the sun on its path, its rays turning twice a second"""
        if not self.sunspot or not self.behind:
            return []
        sun_ = icon("sun", int(t * 2) % 2).resize((48, 48), Image.NEAREST)
        out = self.behind.copy(); out.paste(sun_, (0, 0), sun_)
        return [(out, self.sunspot)]


def shade(up):
    """the sky's colour, top and at the horizon, with the sun up degrees"""
    for (h0, t0, b0), (h1, t1, b1) in zip(SKY, SKY[1:]):
        if up >= h1:
            k = 1 if up >= h0 else (up - h1) / (h0 - h1)
            return blend(t0, t1, k), blend(b0, b1, k)
    return SKY[-1][1], SKY[-1][2]


def blend(a, b, k):
    """a, k of the way from b"""
    return tuple(round(x * k + y * (1 - k)) for x, y in zip(a, b))


def town(img, sun_up, middle):
    """the rooftops along the bottom, the same every day, with a few windows lit after dark, and the compass under
    them, middle being the bearing in the middle of the screen"""
    rng, d = random.Random(76), ImageDraw.Draw(img)
    d.rectangle((0, HORIZON, SCREEN[0], SCREEN[1]), fill=TOWN)
    x = 0
    while x < SCREEN[0]:
        bw, bh = rng.randrange(30, 110), rng.randrange(6, 34)
        if rng.random() < 0.25:   # a tree
            d.ellipse((x, HORIZON - bh - 10, x + bw // 2, HORIZON + 4), fill=TOWN)
        else:
            d.rectangle((x, HORIZON - bh, x + bw, HORIZON), fill=TOWN)
            if rng.random() < 0.3:   # a pitched roof
                d.polygon([(x, HORIZON - bh), (x + bw // 2, HORIZON - bh - 12), (x + bw, HORIZON - bh)], fill=TOWN)
            for wy in range(HORIZON - bh + 6, HORIZON - 4, 8):
                for wx in range(x + 6, x + bw - 6, 10):
                    if rng.random() < 0.18 and sun_up < -3:
                        d.rectangle((wx, wy, wx + 3, wy + 3), fill=WINDOW)
        x += bw + rng.randrange(0, 20)
    for bearing, name in ((0, "N"), (45, "NE"), (90, "E"), (135, "SE"), (180, "S"), (225, "SW"), (270, "W"), (315, "NW")):
        x = (bearing - middle + 180) % 360 * PX
        for x in (x, x + SCREEN[0]) if x < 1 else (x,):   # the edges are the same bearing: say it at both
            text(img, (max(8, min(SCREEN[0] - 8 - len(name) * 8, round(x) - len(name) * 4)), HORIZON + 22), name, D, scale=1)


def check():
    assert 66.5 < sun(J2000, 0, 0) < 67.5, "at the start of 2000 the sun's 23° south: about 67° up at noon on the equator"
    # Philadelphia on the longest day of 2026: sunrise 5:32 AM and sunset 8:32 PM EDT (the Naval Observatory's tables)
    start = utc(2026, 6, 21, 4)   # local midnight there
    rise, sets = crossings(start, 39.95, -75.17)
    assert abs(rise - (start + (5 * 60 + 32) * 60)) < 180 and abs(sets - (start + (20 * 60 + 32) * 60)) < 180, (rise, sets)
    assert crossings(start, 80, 0) == (None, None), "no sunset in the Arctic summer"
    # the full and new moons of late 2026 (the Naval Observatory's times), to within an hour
    for when, angle in (((2026, 10, 26, 4, 12), 180), ((2026, 11, 9, 7, 2), 0), ((2026, 12, 24, 1, 28), 180)):
        assert abs(next_phase(utc(*when) - 10 * 86400, angle) - utc(*when)) < 3600, (when, next_phase(utc(*when) - 10 * 86400, angle) - utc(*when))
    assert moon(utc(2026, 10, 26, 4, 12))[2] == "FULL MOON" and moon(utc(2026, 11, 9, 7, 2))[2] == "NEW MOON"
    first = disc(MONTH / 4, 40)
    assert first.getpixel((35, 20))[:3] == W and first.getpixel((4, 20))[:3] == RULE, "first quarter: lit on the right"
    assert disc(MONTH / 4, 40, south=True).getpixel((4, 20))[:3] == W, "and on the left in the south"
    # the planets, against what the almanacs say: how far each is from the sun in the sky (its elongation)
    def apart(name, ts):
        p, e = orbit(name, ts), orbit("EARTH", ts)
        there, sun_ = [p[k] - e[k] for k in range(3)], [-v for v in e]   # from here, to the planet and to the sun
        return math.degrees(math.acos(sum(u * v for u, v in zip(there, sun_)) / math.hypot(*there) / math.hypot(*sun_)))
    assert apart("SATURN", utc(2026, 10, 4)) > 175, "Saturn at opposition, 4 October 2026"
    assert apart("JUPITER", utc(2026, 1, 10)) > 175, "Jupiter at opposition, 10 January 2026"
    assert apart("VENUS", utc(2026, 10, 24)) < 8, "Venus between us and the sun, 24 October 2026"
    assert max(apart("VENUS", utc(2026, 1, 1) + d * 86400) for d in range(0, 365, 5)) < 48, "Venus never strays far from the sun"
    assert max(apart("MERCURY", utc(2026, 1, 1) + d * 86400) for d in range(0, 365, 3)) < 29
    up, bearing = sky_place(utc(2026, 10, 19, 1), 0, 89.9, 39.95, -75.17)   # Polaris, more or less
    assert abs(up - 39.95) < 0.2 and compass(bearing) == "N", (up, bearing)
    assert clean(None) is None and clean({"hourly": {"time": ["2026-10-19T21:00"], "cloud_cover": ["x"]}}) is None
    assert clean(Page.SAMPLE)["2026-10-19T00:00"] == 50 and cloudy(10) == "CLEAR" and cloudy(90) == "OVERCAST"
    # the panorama: Polaris over the north at the screen's edges, as high as Philadelphia is far north; the sky's colour
    # follows the sun; and the star map is all there
    page = Page(39.95, -75.17)
    x, y, up = page.where(utc(2026, 10, 19, 1), 37.95, 89.26)
    assert (x < 20 or x > SCREEN[0] - 20) and abs(y - (HORIZON - 39.95 * PX)) < 3 * PX, (x, y)
    assert shade(30) == (SKY[0][1], SKY[0][2]) and shade(-30) == (SKY[-1][1], SKY[-1][2]) and shade(-3) != shade(3)
    assert len(STARMAP["stars"]) > 800 and len(STARMAP["lines"]) == 88 and STARMAP["stars"][0][2] < 0, "Sirius first"
    sky = lambda when: Page.showing(None).picture(when, None, safe=False).crop((0, 200, SCREEN[0], HORIZON - 60))
    lit = lambda img: sum(1 for p in img.getdata() if min(p) > 150)
    assert lit(sky(datetime(2026, 10, 19, 23))) > 200 and lit(sky(datetime(2026, 10, 19, 14))) == 0, "stars at night, none by day"
    Page.check()
    for lat, lon in ((39.95, -75.17), (78.2, 15.6), (-33.9, 151.2), (0, 0), ("91", "400")):   # anywhere, even off the map
        page = Page.showing(Page.SAMPLE, lat=lat, lon=lon, place="somewhere with a long name")
        for now in (datetime(2026, 6, 21, 12), datetime(2026, 12, 21, 23, 59), datetime(2026, 3, 8, 2, 30), datetime(2026, 10, 19, 22)):
            assert page.picture(now, page.data, safe=False).size == SCREEN
            for part, (x, y) in page.moving(now, 0, page.data):
                assert 0 <= x and 0 <= y and x + part.width <= SCREEN[0] and y + part.height <= SCREEN[1], (lat, now, x, y)


def preview(now=None):
    return Page.preview(now)
