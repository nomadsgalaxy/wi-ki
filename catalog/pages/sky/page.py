"""Sky: today's sun, tonight's sky and the moon, for where the kiosk is. Across the screen, the whole day from midnight
to midnight, coloured by how light the sky is (night, the three twilights, day), with the sun's height drawn over it,
the sun where it is now, and the cloud forecast along the top. Above it, sunrise, sunset and how long the day is, and
how much longer or shorter than yesterday's. Beside it, the planets you can see and the constellations that are high
up: right now once it's dark, and during the day, for this evening. Then the moon as it looks tonight, how much of it
is lit, and when it's next full and new.

The sun, moon, planets and stars are all worked out here, from the date and the place, with no network. The sun is
good to about a minute, the planets to a fraction of a degree, and the full and new moons to about an hour. The clouds
are Open-Meteo's forecast (no key), fetched every half hour into a cache every renderer on the machine shares
(kit.Simple). Without it the page still draws, just without clouds.

Options (in playlist.json, or the setup page's Location): lat and lon (default: central Philadelphia), and place, for
the heading.
"""
import json, math, time, urllib.parse, urllib.request
from datetime import datetime, timedelta
from PIL import Image, ImageDraw

from kit import SCREEN, Simple, O, W, G, D, B, A, BG, RULE, RAISED, text, masthead, clock, icon

J2000 = 946728000            # 2000-01-01 12:00 UTC, as a Unix time
MONTH = 29.530588853         # days from new moon to new moon, on average
RISE = -0.833                # the sun's height at sunrise and sunset: its radius, and the air bending its light
DARK = -6                    # the sun this far down (the end of civil twilight): the bright planets and stars are out
LEFT, TOP, RIGHT, BOTTOM = 40, 168, 1080, 440   # the day chart
NIGHT = 1120                 # where tonight's sky goes, then the moon at MOON
MOON = 1490
SPAN = 70                    # degrees of the sun's height the chart's top half shows
API = "https://api.open-meteo.com/v1/forecast?"
UA = {"User-Agent": "wi-ki sky (github.com/nomadsgalaxy/wi-ki)"}
mix = lambda colour, k: tuple(round(c * k + b * (1 - k)) for c, b in zip(colour, BG))   # a token, faded toward the background
SKY = ((0, mix(O, 0.30)), (-6, mix(B, 0.45)), (-12, mix(B, 0.25)), (-18, RAISED), (-90, BG))   # day, the twilights, night
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
# constellations, by about where their bright stars are (RA in hours, Dec in degrees): enough to say what's up
STARS = (("ANDROMEDA", 0.8, 37), ("CASSIOPEIA", 1.0, 62), ("PISCES", 0.5, 13), ("ARIES", 2.6, 21),
         ("PERSEUS", 3.2, 45), ("ERIDANUS", 3.3, -29), ("TAURUS", 4.7, 15), ("ORION", 5.6, 5), ("AURIGA", 6.0, 42),
         ("CANIS MAJOR", 6.8, -22), ("GEMINI", 7.1, 23), ("CANIS MINOR", 7.6, 6), ("CANCER", 8.6, 20),
         ("CARINA", 8.7, -63), ("LEO", 10.7, 13), ("URSA MAJOR", 11.3, 51), ("CRUX", 12.4, -60),
         ("CENTAURUS", 13.1, -47), ("VIRGO", 13.4, -4), ("BOOTES", 14.7, 31), ("URSA MINOR", 15.0, 78),
         ("DRACO", 15.1, 67), ("LIBRA", 15.2, -15), ("CORONA BOREALIS", 15.8, 33), ("SCORPIUS", 16.9, -27),
         ("HERCULES", 17.4, 27), ("OPHIUCHUS", 17.4, -8), ("LYRA", 18.85, 36), ("SAGITTARIUS", 19.1, -28),
         ("AQUILA", 19.7, 3), ("CYGNUS", 20.6, 44), ("CAPRICORNUS", 21.0, -18), ("CEPHEUS", 22.0, 71),
         ("AQUARIUS", 22.3, -11), ("PISCIS AUSTRINUS", 22.3, -30), ("PEGASUS", 22.7, 19))
HIGH = 30   # a constellation this many degrees up is clear of the haze and the houses


def sky_place(ts, ra, dec, lat, lon):
    """where something at ra and dec (degrees) is in the sky at Unix time ts, from lat and lon -> (height above the
    horizon, compass bearing), in degrees"""
    d = (ts - J2000) / 86400
    hour = math.radians((280.46061837 + 360.98564736629 * d + lon - ra) % 360)
    la, dec = math.radians(lat), math.radians(dec)
    up = math.degrees(math.asin(math.sin(la) * math.sin(dec) + math.cos(la) * math.cos(dec) * math.cos(hour)))
    bearing = math.degrees(math.atan2(-math.sin(hour), math.tan(dec) * math.cos(la) - math.sin(la) * math.cos(hour))) % 360
    return up, bearing


def sun(ts, lat, lon):
    """the sun's height above the horizon in degrees, at Unix time ts, from lat and lon (the Almanac's low-precision
    formulas: good to about a hundredth of a degree this century)"""
    d = (ts - J2000) / 86400
    g = math.radians(357.529 + 0.98560028 * d)
    ecl = math.radians(280.459 + 0.98564736 * d + 1.915 * math.sin(g) + 0.020 * math.sin(2 * g))
    tilt = math.radians(23.439 - 0.00000036 * d)
    ra = math.degrees(math.atan2(math.cos(tilt) * math.sin(ecl), math.cos(ecl)))
    dec = math.degrees(math.asin(math.sin(tilt) * math.sin(ecl)))
    return sky_place(ts, ra, dec, lat, lon)[0]


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
        """the day of when, worked out once: its start and end, the sun's height for each column of the chart, sunrise
        and sunset, and yesterday's day length"""
        key = (when, self.lat, self.lon)
        if key not in self._days:
            start = time.mktime(datetime.combine(when, datetime.min.time()).timetuple())
            end = time.mktime(datetime.combine(when + timedelta(days=1), datetime.min.time()).timetuple())   # 23 or 25 h when the clocks change
            heights = [sun(start + (end - start) * x / (RIGHT - LEFT), self.lat, self.lon) for x in range(RIGHT - LEFT)]
            rise, sets = crossings(start, self.lat, self.lon, round((end - start) / 60))
            before = crossings(start - 86400, self.lat, self.lon)
            self._days.clear()   # one day at a time is plenty
            self._days[key] = {"start": start, "end": end, "heights": heights, "rise": rise, "set": sets,
                               "yesterday": (before[1] - before[0]) % 86400 if None not in before else None}
        return self._days[key]

    def tonight(self, now, day):
        """when to show the night sky for -> (Unix time, what to call it), or None if it never gets dark today: now,
        once it's dark, or else an hour and a half after sunset"""
        ts = time.mktime(now.timetuple())
        if sun(ts, self.lat, self.lon) < DARK:
            return ts, "UP NOW"
        if day["set"] and day["set"] > ts:
            at = day["set"] + 90 * 60
            return at, "TONIGHT AT " + clock(datetime.fromtimestamp(at - at % 900))
        return None

    def draw(self, img, now, data):
        day, d = self.day(now.date()), ImageDraw.Draw(img)
        clouds = data if isinstance(data, dict) else {}
        place = str(self.place or "")[:24].upper()
        masthead(img, now, "// SKY" + (f" · {place}" if place else ""), "SUN, STARS & MOON")
        y0 = (TOP + BOTTOM) // 2   # the horizon
        y = lambda h: y0 - round(max(-SPAN, min(SPAN, h)) / SPAN * (y0 - TOP))
        width = RIGHT - LEFT
        for x, h in enumerate(day["heights"]):   # the sky's colour, column by column, and the clouds along the top
            d.line((LEFT + x, TOP, LEFT + x, BOTTOM), fill=next(c for low, c in SKY if h >= low))
            cover = clouds.get(datetime.fromtimestamp(day["start"] + (day["end"] - day["start"]) * x / width).strftime("%Y-%m-%dT%H:00"))
            if cover is not None:
                d.line((LEFT + x, TOP - 14, LEFT + x, TOP - 4), fill=mix(G, 0.1 + 0.9 * cover / 100))
        if clouds:
            text(img, (RIGHT, TOP - 34), "clouds: open-meteo.com", D, scale=1, right=True)
        d.rectangle((LEFT, y0, RIGHT - 1, y0 + 1), fill=G)
        d.line([(LEFT + x, y(h)) for x, h in enumerate(day["heights"])], fill=A, width=3)
        for hour in range(0, 25, 3):   # the hours along the bottom
            x = LEFT + round((width - 1) * hour / 24)
            d.rectangle((x, BOTTOM, x, BOTTOM + 6), fill=D)
            label = "12a" if hour % 24 == 0 else "12p" if hour == 12 else f"{hour % 12}{'a' if hour < 12 else 'p'}"
            text(img, (x - (0 if hour == 0 else len(label) * 8 if hour == 24 else len(label) * 4), BOTTOM + 10), label, D, scale=1)
        rise, sets = day["rise"], day["set"]
        if rise and sets:
            long, was = (sets - rise) % 86400, day["yesterday"]
            words = [("SUNRISE ", G), (clock(datetime.fromtimestamp(rise)), W), ("  SUNSET ", G),
                     (clock(datetime.fromtimestamp(sets)), W), ("  DAY ", G), (length(long), W)]
            if was:
                change = round(long - was)
                words.append((f"  {'+' if change >= 0 else '-'}{abs(change) // 60}m {abs(change) % 60:02d}s", O if change >= 0 else B))
        else:
            words = [("THE SUN STAYS " + ("UP" if day["heights"][0] > RISE else "DOWN") + " ALL DAY", W)]
        x = LEFT
        for said, colour in words:
            x += text(img, (x, 104), said, colour, scale=2)
        # now: a line down the chart, and the sun on its path (moving() draws it there, so it can shine)
        x = max(0, min(width - 1, round((time.mktime(now.timetuple()) - day["start"]) / (day["end"] - day["start"]) * width)))
        d.rectangle((LEFT + x, TOP, LEFT + x, BOTTOM), fill=W)
        self.sunspot = (LEFT + x - 24, y(day["heights"][x]) - 24)
        self.behind = img.crop((*self.sunspot, self.sunspot[0] + 48, self.sunspot[1] + 48))   # to draw the sun over
        self.night(img, now, day, clouds)
        # the moon, on the right
        age, lit, phase = moon(time.mktime(now.timetuple()))
        m = disc(age, 120, self.lat < 0)
        img.paste(m, (MOON, 112), m)
        text(img, (MOON + 140, 116), phase.replace("WAXING ", "WAXING\n").split("\n")[0] if len(phase) > 13 else phase, W, scale=2)
        if len(phase) > 13:
            text(img, (MOON + 140, 148), phase.split(" ", 1)[1], W, scale=2)
        text(img, (MOON + 140, 184), f"{round(lit * 100)}% lit", G, scale=2)
        for i, (said, angle) in enumerate((("full", 180), ("new", 0))):
            when = datetime.fromtimestamp(next_phase(time.mktime(now.timetuple()), angle))
            text(img, (MOON, 256 + i * 72), f"{said} moon {when.strftime('%a %b')} {when.day}", O if said == "full" else G, scale=2)
            text(img, (MOON, 292 + i * 72), clock(when), D, scale=1)

    def night(self, img, now, day, clouds):
        """the planets you can see and the constellations high up, now or this evening, and the clouds then"""
        when = self.tonight(now, day)
        if not when:
            text(img, (NIGHT, 112), "NO DARK TONIGHT", G, scale=2)
            return
        ts, title = when
        text(img, (NIGHT, 112), title, O, scale=2)
        cover = clouds.get(datetime.fromtimestamp(ts).strftime("%Y-%m-%dT%H:00"))
        if cover is not None:
            text(img, (NIGHT, 146), f"{cloudy(cover)} · {cover}% cloud", A if cover >= 50 else G, scale=1)
        seen = []
        for name in SHADE:
            up, bearing = sky_place(ts, *planet(name, ts), self.lat, self.lon)
            if up > 5 and (name != "MERCURY" or up > 10):   # Mercury only shows when it's clear of the glow
                seen.append((up, name, bearing))
        y = 174
        for up, name, bearing in sorted(seen, reverse=True):
            text(img, (NIGHT, y), name, SHADE[name], scale=2)
            text(img, (NIGHT + 150, y + 8), f"{compass(bearing)}, {round(up)}° up", G, scale=1)
            y += 30
        if not seen:
            text(img, (NIGHT, y), "no bright planets", D, scale=2); y += 30
        high = sorted(((sky_place(ts, ra * 15, dec, self.lat, self.lon), name) for name, ra, dec in STARS), reverse=True)
        names = [name for (up, _), name in high if up > HIGH][:8]
        if names:
            text(img, (NIGHT, y + 8), "HIGH UP", D, scale=1)
            for i, name in enumerate(names):
                text(img, (NIGHT + i % 2 * 180, y + 28 + i // 2 * 20), name.title(), W, scale=1)

    def moving(self, now, t, data):
        """the sun on its path, its rays turning twice a second"""
        if not self.sunspot or not self.behind:
            return []
        sun_ = icon("sun", int(t * 2) % 2).resize((48, 48), Image.NEAREST)
        out = self.behind.copy(); out.paste(sun_, (0, 0), sun_)
        return [(out, self.sunspot)]


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
    Page.check()
    for lat, lon in ((39.95, -75.17), (78.2, 15.6), (-33.9, 151.2), (0, 0), ("91", "400")):   # anywhere, even off the map
        page = Page.showing(Page.SAMPLE, lat=lat, lon=lon, place="somewhere with a long name")
        for now in (datetime(2026, 6, 21, 12), datetime(2026, 12, 21, 23, 59), datetime(2026, 3, 8, 2, 30), datetime(2026, 10, 19, 22)):
            assert page.picture(now, page.data, safe=False).size == SCREEN
            for part, (x, y) in page.moving(now, 0, page.data):
                assert 0 <= x and 0 <= y and x + part.width <= SCREEN[0] and y + part.height <= SCREEN[1], (lat, now, x, y)


def preview(now=None):
    return Page.preview(now)
