"""The weather page: Philly's skyline in pixel art on the left, playing the real weather, time of day and season
(scene.py), and the forecast on the right in the VGA console font: the big temperature, the next 12 hours as a pixel
chart and the next five days, every temperature in °F or °C (whichever the place uses, unless units says), and the
other one in smaller type if asked.

It stays up for exactly one 64 s loop of the scene, which plays seamlessly. Open-Meteo (no key) every 10 minutes into
CACHE, fetched in a background thread so the display never waits on the network. If the network drops, it keeps showing
the last forecast and says how old it is. The forecast covers 14 days so other pages (the calendar) can use it too.

Options (in playlist.json): lat and lon, for the forecast; place, the heading; landscape, the name of a folder in the
catalog's landscapes/, to show someone's own scene instead of Philadelphia's (scene.py says what one is). A landscape
brings its own location, place and credit, and lat, lon and place still win over them. units: "f" or "c", the unit
every temperature is shown in; left out, it's the one people use where the forecast is for (°F in the US). secondary:
true also shows the other unit, in smaller type beside the big temperature and under each day's.
"""
import json, math, os, struct, time, urllib.request
from datetime import date, datetime, timedelta
from PIL import Image, ImageDraw

from kit import (SCREEN, O, W, G, D, B, C, A, BG, RULE, DIM, Simple, kind, warmth, clock, FONT, text, paste_icon,
                 packed, rgb565)
from . import scene

# the forecast is for Philadelphia, where the skyline is, unless the playlist gives lat and lon or a landscape (which
# has its own); the panel says PHILADELPHIA, or the landscape's place, unless it gives a place
URL = ("https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
       "&current=temperature_2m,apparent_temperature,relative_humidity_2m,wind_speed_10m,wind_direction_10m,weather_code,is_day"
       "&hourly=temperature_2m,precipitation_probability,weather_code&forecast_hours=12"
       "&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,sunrise,sunset"
       "&temperature_unit=celsius&wind_speed_unit=mph&timezone=auto&forecast_days=14")
CACHE = os.path.expanduser("~/.cache/weather.json")
PANEL = 1200                     # the scene is 1200 wide (300 art pixels x 4), the forecast takes the rest
CREDIT = "skyline: Mefman00, CC BY-SA 4.0"   # "The Philadelphia skyline (cropped)", the photo the scene is drawn from
COMPASS = "N NE E SE S SW W NW".split()
WORDS = {0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "fog", 51: "drizzle", 53: "drizzle",
         55: "drizzle", 56: "freezing drizzle", 57: "freezing drizzle", 61: "light rain", 63: "rain", 65: "heavy rain",
         66: "freezing rain", 67: "freezing rain", 71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains",
         80: "showers", 81: "showers", 82: "heavy showers", 85: "snow showers", 86: "snow showers", 95: "thunderstorms",
         96: "thunderstorms", 99: "thunderstorms"}


FAHRENHEIT = {"US", "PR", "GU", "VI", "AS", "MP", "UM", "BS", "BZ", "KY", "LR", "PW", "FM", "MH"}   # where °F is everyday
ZONES = "/usr/share/zoneinfo/zone.tab"   # each time zone's country, from the system's time zone data


def fahrenheit(c):
    return c * 9 / 5 + 32


def local_units(w, zones=ZONES):
    """the unit people use where the forecast is for, from its time zone (the forecast is asked for in the place's own):
    "f" in the US and the few others, "c" everywhere else, and when it can't tell"""
    try:
        country = {z[2]: z[0] for z in (l.rstrip("\n").split("\t") for l in open(zones) if not l.startswith("#")) if len(z) > 2}.get(w.get("timezone"))
    except OSError:
        return "c"
    return "f" if country in FAHRENHEIT else "c"


def windtext(c):
    """no wind reading says so, rather than 0 mph (the scene falls back to its default animation speed, a 5 mph breeze)"""
    ws = c["wind_speed_10m"]
    return "wind unavailable" if ws is None else f"{round(ws)} mph {COMPASS[round(c['wind_direction_10m'] / 45) % 8]}"


def panel(w, now, age, frame, place="PHILADELPHIA", credit=None, units=None, secondary=False):
    """the right side, 720x515. The forecast is in °C, and so are the colours (kit.warmth); units and secondary only
    change what's written. No units: the place's own"""
    units = units or local_units(w)
    as_f, as_c = (lambda c: round(fahrenheit(c))), round
    shown, unit = (as_f, "°F") if units == "f" else (as_c, "°C")   # the unit everything is shown in
    other, other_unit = (as_c, "°C") if units == "f" else (as_f, "°F")   # and the other, in small type, if asked
    img = Image.new("RGB", (SCREEN[0] - PANEL, SCREEN[1]), BG); d = ImageDraw.Draw(img)
    c, h, dd = w["current"], w["hourly"], w["daily"]
    X, R = 28, img.width - 24
    d.rectangle((0, 0, 7, img.height), fill=RULE); d.rectangle((2, 0, 3, img.height), fill=(70, 76, 92))   # the bezel

    text(img, (X, 14), place, O)
    text(img, (R, 14), clock(now), W, right=True)
    text(img, (X, 50), now.strftime("%A, %B ") + str(now.day), G)
    text(img, (R, 66), CREDIT if credit is None else credit, G, scale=1, right=True)   # the scene's licence, always on screen
    d.rectangle((X, 90, R, 91), fill=RULE)

    # now: icon, the big temperature, what it's like
    t = c["temperature_2m"]
    paste_icon(img, kind(c["weather_code"], c.get("is_day", 1)), frame // 2, (X, 106), 5)
    stale = age > 1800
    hot = DIM if stale else warmth(t)   # an old forecast's big temperature is greyed out, so it doesn't pass for now
    wide = text(img, (X + 100, 102), f"{shown(t)}", hot, scale=6)
    text(img, (X + 104 + wide, 106), unit, hot)
    col = X + 184 + wide
    text(img, (col, 106), WORDS.get(c["weather_code"], "")[:20], W)
    feels = c["apparent_temperature"]
    text(img, (col, 142), (f"{other(t)}{other_unit}  " if secondary else "") + f"feels {shown(feels)}{unit}", G)
    wind = windtext(c)
    text(img, (col, 178), f"{round(c['relative_humidity_2m'])}% humid  {wind}", G, scale=1)
    text(img, (col, 196), f"sunrise {clock(dd['sunrise'][0])}  sunset {clock(dd['sunset'][0])}", G, scale=1)
    d.rectangle((X, 222, R, 223), fill=RULE)

    # the next 12 hours: the temperature as a stepped pixel line, rain chances as bars underneath
    text(img, (X, 232), "NEXT 12 HOURS", O, scale=1)
    legend = "bars: chance of rain, taller is likelier"
    text(img, (R, 232), legend, G, scale=1, right=True)
    d.rectangle((R - len(legend) * 8 - 20, 232, R - len(legend) * 8 - 8, 243), fill=B)   # a bar swatch, the colour of a likely one
    hours = [(t, v, p) for t, v, p in zip(h["time"], h["temperature_2m"], h["precipitation_probability"])
             if isinstance(v, (int, float))][:12]   # an hour with no temperature (null) is left out, not a crash
    if not hours:
        text(img, (X, 290), "no hourly forecast", D, scale=1)
    times, temps, rain = (list(col) for col in zip(*hours)) if hours else ([], [], [])
    step = (R - X) // max(1, len(temps))
    lo, hi = (min(temps), max(max(temps), min(temps) + 1)) if temps else (0, 1)
    top, bot = 272, 316
    ys = [round(bot - (v - lo) / (hi - lo) * (bot - top)) // 4 * 4 for v in temps]   # snapped to a 4-pixel grid
    for i, (v, y) in enumerate(zip(temps, ys)):
        x = X + i * step
        d.rectangle((x + 4, y, x + step - 4, y + 3), fill=warmth(v))
        if i + 1 < len(ys):
            d.rectangle((x + step - 4, min(y, ys[i + 1]), x + step - 1, max(y, ys[i + 1]) + 3), fill=D)
        label = f"{shown(v)}°"
        text(img, (x + step // 2 - len(label) * 4, y - 20), label, warmth(v), scale=1)
        p = rain[i] or 0
        if p:
            bh = max(4, round(p / 100 * 28) // 4 * 4)
            d.rectangle((x + 8, 358 - bh, x + step - 8, 358), fill=B if p >= 30 else D)
        hour = clock(times[i]).replace(":00 ", "").lower()[:-1]
        text(img, (x + step // 2 - len(hour) * 4, 362), hour, G if p < 30 else C, scale=1)
    d.rectangle((X, 398, R, 399), fill=RULE)

    # the next five days
    days = min(5, len(dd["time"]))   # the forecast has 14 days (for the calendar); this strip shows five
    step = (R - X) // days
    for i in range(days):
        x = X + i * step
        name = "TODAY" if i == 0 else date.fromisoformat(dd["time"][i]).strftime("%a").upper()
        text(img, (x, 406), name, W if i == 0 else G, scale=1)
        p = dd["precipitation_probability_max"][i] or 0
        if p >= 30:
            text(img, (x + 54, 406), f"{p}% rain", B, scale=1)
        paste_icon(img, kind(dd["weather_code"][i]), frame // 2 + i, (x, 426), 3)
        hi_, lo_ = dd["temperature_2m_max"][i], dd["temperature_2m_min"][i]
        text(img, (x + 54, 426), f"{shown(hi_)}°", warmth(hi_))
        text(img, (x + 54, 460), f"{shown(lo_)}°", warmth(lo_), scale=1)
        if secondary:   # the same day in the other unit, small, under it
            text(img, (x + 54, 476), f"{other(hi_)}/{other(lo_)}{other_unit}", G, scale=1)

    if stale:   # a bar across the bottom that reads from across the room
        d.rectangle((8, 480, img.width, img.height), fill=A)
        text(img, (X, 482), f"NO UPDATE FOR {round(age / 60)} MIN", BG)
    else:
        text(img, (R, 492), "open-meteo.com · " + clock(datetime.fromtimestamp(now.timestamp() - age)), D, scale=1, right=True)
    return img


def frame(w, now, age, t, units=None, secondary=False):
    """one full 1920x515 frame"""
    img = Image.new("RGB", SCREEN, BG)
    img.paste(scene.draw(w, now, t).resize((PANEL, 512), Image.NEAREST), (0, 1))
    img.paste(panel(w, now, age, 0, units=units, secondary=secondary), (PANEL, 0))
    return img


# --- the framebuffer --------------------------------------------------------------------------------------------------


def download(url):
    with urllib.request.urlopen(url, timeout=20) as r:
        return json.load(r)


def clean(w):
    """a forecast the page can draw, made from whatever it was given, or None if there's no usable now or day. Numbers
    are coerced and held to what the earth can do, a field that's missing or the wrong type takes a plain default,
    hours and days that can't be drawn are dropped, and lists that don't line up are cut to the length that does.
    Valid data comes out the same, so every drawing function below can trust what it's handed"""
    def num(v, lo, hi, default=None):
        v = v if isinstance(v, (int, float)) and not isinstance(v, bool) else default
        return default if v is None or not math.isfinite(v) else max(lo, min(hi, v))

    def stamp(v):
        try:
            return v if datetime.strptime(v, "%Y-%m-%dT%H:%M") else None
        except (TypeError, ValueError):
            return None

    def day(v):
        try:
            return v if date.fromisoformat(v) else None
        except (TypeError, ValueError):
            return None

    def column(section, key):
        got = section.get(key) if isinstance(section, dict) else None
        return got if isinstance(got, list) else []

    def code(v):
        return v if isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 99 else 0

    if not isinstance(w, dict) or not isinstance(w.get("current"), dict):
        return None
    c, h, d = w["current"], w.get("hourly"), w.get("daily")
    try:
        t = num(c.get("temperature_2m"), -90, 60)
        if t is None:
            return None
        now = {"temperature_2m": t, "apparent_temperature": num(c.get("apparent_temperature"), -90, 60, t),
               "relative_humidity_2m": num(c.get("relative_humidity_2m"), 0, 100, 50),
               "wind_speed_10m": num(c.get("wind_speed_10m"), 0, 300),   # no reading stays None
               "wind_direction_10m": num(c.get("wind_direction_10m"), 0, 360, 0), "weather_code": code(c.get("weather_code")),
               "is_day": c["is_day"] if c.get("is_day") in (0, 1) and not isinstance(c.get("is_day"), bool) else 1}
        hours = [(a, num(b, -90, 60), num(p, 0, 100, 0)) for a, b, p in
                 zip(map(stamp, column(h, "time")), column(h, "temperature_2m"), column(h, "precipitation_probability"))]
        hours = [x for x in hours if x[0] and x[1] is not None][:48]
        days = zip(map(day, column(d, "time")), map(code, column(d, "weather_code")),
                   (num(v, -90, 60) for v in column(d, "temperature_2m_max")), (num(v, -90, 60) for v in column(d, "temperature_2m_min")),
                   (num(v, 0, 100) for v in column(d, "precipitation_probability_max")),
                   map(stamp, column(d, "sunrise")), map(stamp, column(d, "sunset")))
        days = [x for x in days if None not in (x[0], x[2], x[3], x[5], x[6])][:14]   # a missing chance of rain is fine
    except OverflowError:   # a number with a thousand digits, which isfinite() can't take
        return None
    if not days:
        return None
    out = {"current": now, "hourly": dict(zip(("time", "temperature_2m", "precipitation_probability"), map(list, zip(*hours)))) if hours
           else {"time": [], "temperature_2m": [], "precipitation_probability": []},
           "daily": dict(zip(("time", "weather_code", "temperature_2m_max", "temperature_2m_min", "precipitation_probability_max",
                              "sunrise", "sunset"), map(list, zip(*days))))}
    if isinstance(w.get("timezone"), str):
        out["timezone"] = w["timezone"]
    return out


def valid(w):
    """w if it's a forecast this page can draw (every section, lists that line up, finite numbers, times that read),
    else None. Checked before it replaces the cache and when the cache is read, so an answer like {"error": true}
    never takes the place of the last good forecast"""
    num = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
    code = lambda v: isinstance(v, int) and not isinstance(v, bool)
    stamp = lambda v: bool(datetime.strptime(v, "%Y-%m-%dT%H:%M"))
    try:
        c, h, d = w["current"], w["hourly"], w["daily"]
        ok = (all(num(c[k]) for k in ("temperature_2m", "apparent_temperature", "relative_humidity_2m",
                                       "wind_direction_10m")) and code(c["weather_code"])
              and (c["wind_speed_10m"] is None or num(c["wind_speed_10m"]))   # no wind reading draws at the default speed
              and c.get("is_day", 1) in (0, 1) and not isinstance(c.get("is_day"), bool)
              and h["time"] and all(len(h[k]) == len(h["time"]) for k in ("temperature_2m", "precipitation_probability"))
              and all(map(stamp, h["time"]))
              and all(v is None or num(v) for k in ("temperature_2m", "precipitation_probability") for v in h[k])   # a gap is drawn without
              and d["time"] and all(len(d[k]) == len(d["time"]) for k in ("weather_code", "temperature_2m_max", "temperature_2m_min",
                                                                           "precipitation_probability_max", "sunrise", "sunset"))
              and all(date.fromisoformat(t) for t in d["time"]) and all(map(stamp, d["sunrise"] + d["sunset"]))
              and all(map(code, d["weather_code"])) and all(map(num, d["temperature_2m_max"] + d["temperature_2m_min"]))
              and all(v is None or num(v) for v in d["precipitation_probability_max"]))
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):   # OverflowError: isfinite(10**1000)
        return None
    return w if ok else None


def fetch(lat, lon):
    w = valid(download(URL.format(lat=lat, lon=lon)))
    if not w:
        raise ValueError("not a forecast")   # the page keeps the last good one, and its age
    return w


def cached():
    """the saved forecast, or None if there isn't one or it won't read"""
    try:
        with open(CACHE) as f:
            return valid(json.load(f))
    except (OSError, ValueError):
        return None


def waiting():
    """the screen before the first forecast has come: the page's name and what it's waiting for"""
    img = Image.new("RGB", SCREEN, BG)
    for y, say, col, scale in ((SCREEN[1] // 2 - 56, "WEATHER", O, 4), (SCREEN[1] // 2 + 8, "waiting for the first forecast", W, 2)):
        text(img, ((SCREEN[0] - len(say) * 8 * scale) // 2, y), say, col, scale=scale)
    return img


# TODAY's low (4.1) is the calendar day's, so it can sit below the overnight hours on the strip: it was colder this morning
SAMPLE = {"current": {"temperature_2m": 16.3, "apparent_temperature": 14.9, "relative_humidity_2m": 62, "wind_speed_10m": 9.4,
                      "wind_direction_10m": 300, "weather_code": 3, "is_day": 1},
          "hourly": {"time": [f"2026-10-14T{h:02d}:00" for h in range(17, 24)] + [f"2026-10-15T{h:02d}:00" for h in range(5)],
                     "temperature_2m": [16, 16, 14, 13, 11, 10, 9, 8, 8, 7, 7, 7],
                     "precipitation_probability": [0, 0, 5, 10, 35, 60, 40, 20, 0, 0, 0, 0], "weather_code": [3] * 12},
          "daily": {"time": [f"2026-10-{d}" for d in range(14, 19)], "weather_code": [3, 61, 0, 2, 95],
                    "temperature_2m_max": [17.4, 14.4, 18.9, 21.7, 26.7], "temperature_2m_min": [4.1, 6.7, 8.3, 11.1, 16.1],
                    "precipitation_probability_max": [10, 70, 0, None, 40],
                    "sunrise": ["2026-10-14T07:12"] * 5, "sunset": ["2026-10-14T18:20"] * 5}}


class Page(Simple):
    """the weather, as a page of the kiosk's cycle (see kiosk.py). It stays up for exactly one loop of the scene, and
    the scene holds one moment of the day for that whole loop, so it always plays one seamless loop. Its frames are
    drawn once, packed at 300x128, and replayed until the sky moves on: by day when the sun steps along its arc or the
    weather changes, at night every 5 minutes, as the lit windows reshuffle. The forecast is fetched every 10 minutes
    into CACHE, which the calendar reads too."""
    name, seconds, every, cache, SAMPLE = "weather", scene.LOOP, 600, CACHE, SAMPLE

    def __init__(self, lat=None, lon=None, place=None, landscape=None, units=None, secondary=False):
        if units not in (None, "c", "f"):
            raise ValueError(f'units is "f" or "c" (or left out, for the place\'s own), not {units!r}')
        if not isinstance(secondary, bool):
            raise ValueError(f"secondary is true or false, not {secondary!r}")
        self.units, self.secondary = units, secondary
        land = scene.landscape(landscape) if landscape else None   # one that isn't there, or isn't right, says why
        self.land = landscape or None
        self.lat = lat if lat is not None else land["lat"] if land else 39.95
        self.lon = lon if lon is not None else land["lon"] if land else -75.17
        self.place = place or (land["place"].upper() if land else "PHILADELPHIA")
        self.credit = f"scene: {land['credit']['author']}, {land['credit']['licence']}"[:40] if land else None
        self.loop, self.loop_key, self.moment = {}, None, None

    def fetch(self):
        return fetch(self.lat, self.lon)

    def clean(self, data):
        return clean(data)   # one it can't draw is no forecast: the page keeps the last, or waits

    def start(self, now):
        self.load()
        key = scene.moment(self.data, now, self.land) if self.data else None   # not the clock: by day one loop lasts until the sun or the weather moves
        if key != self.loop_key:
            self.loop, self.loop_key, self.moment = {}, key, now
        if self.data:
            self.small(0)   # any rebuild happens now, before anything moves

    def small(self, i):
        if i not in self.loop:
            self.loop[i] = packed(scene.draw(self.data, self.moment, i / scene.FPS, self.land))
        return self.loop[i]

    def draw(self, img, now, data):
        if not data:   # the first forecast hasn't come yet: say so, rather than show one that's made up
            img.paste(waiting())
            return
        img.paste((0, 0, 0), (0, 0, PANEL, SCREEN[1]))   # the scene goes here
        img.paste(panel(data, now, self.age(), 0, self.place, self.credit, self.units, self.secondary), (PANEL, 0))

    def moving(self, now, t, data):
        if not data:
            return []
        if self.moment is None:
            self.start(now)
        i = round(t * scene.FPS) % int(scene.LOOP * scene.FPS)
        return [(self.small(i).resize((PANEL, 512), Image.NEAREST), (0, 1))]


def check():
    now = datetime(2026, 10, 14, 17, 3)
    img = frame(SAMPLE, now, 120, 0.0)
    assert img.size == SCREEN and img.mode == "RGB"
    px = Image.new("RGB", (3, 1)); px.putdata([(255, 0, 0), (0, 255, 0), (0, 0, 255)])
    assert rgb565(px) == struct.pack("<3H", 0xF800, 0x07E0, 0x001F), rgb565(px).hex()
    assert len(rgb565(img)) == SCREEN[0] * SCREEN[1] * 2
    small = scene.draw(SAMPLE, now, 0.0)   # packing then scaling is the same as scaling then packing
    assert packed(small).resize((PANEL, 512), Image.NEAREST).tobytes() == rgb565(small.resize((PANEL, 512), Image.NEAREST))
    assert frame(SAMPLE, now, 120, 0.0).tobytes() == img.tobytes(), "the same moment draws the same frame"
    assert frame(SAMPLE, now, 120, 0.5).tobytes() != img.tobytes(), "it animates"
    assert all(ch in FONT for ch in "PHILADELPHIA°·%:/-0123456789abcdefghijklmnopqrstuvwxyz"), "the font has our glyphs"
    w = json.loads(json.dumps(SAMPLE))
    for code in WORDS:   # every weather code, at noon, sunset, night and dawn, draws
        for hh, mm in ((12, 0), (18, 25), (23, 0), (6, 50)):
            w["current"]["weather_code"] = code
            frame(w, datetime(2026, 10, 14, hh, mm), 0, 3.0)
    assert frame(SAMPLE, now, 4000, 0).tobytes() != img.tobytes(), "a stale forecast says so"
    Page.check(tries=6)   # each try draws a whole scene: a few is plenty, fuzz.py does more
    page = Page.showing(json.loads(json.dumps(SAMPLE)))   # as a page: one whole loop, ending where it began
    page.start(now)
    key, bg = page.background(now)
    assert bg.size == SCREEN and bg.mode == "LA" and page.background(now)[0] == key, "the background only changes when it must"
    first, last = page.regions(now, 0.0)[0][0], page.regions(now, page.seconds)[0][0]
    assert first.tobytes() == last.tobytes() and page.seconds == scene.LOOP, "the page shows exactly one seamless loop"
    day = json.loads(json.dumps(SAMPLE)); at = lambda hh, mm: datetime(2026, 10, 14, hh, mm)
    assert scene.moment(day, at(12, 0)) == scene.moment(day, at(14, 30)), "overcast by day, one loop lasts for hours"
    day["current"]["weather_code"] = 0
    assert scene.moment(day, at(12, 0)) == scene.moment(day, at(12, 2)), "a clear day replays its loop until the sun moves"
    assert scene.moment(day, at(12, 0)) != scene.moment(day, at(12, 30)), "and the sun does move"
    assert scene.moment(day, at(22, 0)) != scene.moment(day, at(22, 5)), "at night the lit windows reshuffle"
    assert scene.moment(day, at(18, 10)) != scene.moment(day, at(18, 40)), "dusk comes"
    for hh, mm in ((12, 0), (18, 13), (21, 1)):   # one key, one picture: midday, golden hour, night
        first = at(hh, mm)
        later = next(m for m in (first + timedelta(seconds=s) for s in range(5, 300, 5))
                     if scene.moment(day, m) == scene.moment(day, first))
        scene._cache.clear(); scene._paths.clear(); a = scene.draw(day, first, 9.25).tobytes()   # drawn fresh
        assert scene.draw(day, later, 9.25).tobytes() == a, (hh, mm)                               # and warm
    rainy = json.loads(json.dumps(day)); rainy["current"]["weather_code"] = 63
    assert scene.moment(rainy, at(12, 0)) != scene.moment(day, at(12, 0)), "the weather changes the loop"
    assert scene.draw(rainy, at(12, 0), 9.25).tobytes() != scene.draw(day, at(12, 0), 9.25).tobytes()
    for code in (0, 2, 3, 45, 63, 73, 95):   # every animation loops seamlessly: LOOP seconds later is the same frame
        w["current"]["weather_code"] = code
        for t in (0.0, 0.25, 17.5, 63.75):
            assert scene.draw(w, now, t).tobytes() == scene.draw(w, now, t + scene.LOOP).tobytes(), (code, t)
    # no wind reading, is_day, the moon's phase, the layers' key, the strikes, the stale bar, the credit
    calm = json.loads(json.dumps(SAMPLE)); calm["current"]["wind_speed_10m"] = None
    assert valid(calm) and frame(calm, now, 0, 0.0).size == SCREEN, "a null wind reading still draws"
    assert windtext(calm["current"]) == "wind unavailable" and "mph" in windtext(SAMPLE["current"]), "no wind reading isn't 0 mph"
    for bad_day in (2, "day", True):
        odd = json.loads(json.dumps(SAMPLE)); odd["current"]["is_day"] = bad_day
        assert valid(odd) is None, f"is_day {bad_day!r} isn't a forecast"
    sky = json.loads(json.dumps(SAMPLE)); sky["current"]["weather_code"] = 0
    for day, lit_left, lit_right in ((17, False, True), (26, True, True), (12, False, False)):   # waxing, full, new (2026)
        late = datetime(2026, 10, day, 0, 46)   # the moon high in the middle of the sky
        arc = scene.daylight(sky, late)[2]; bx, by = 8 + arc * 284, 84 - 74 * math.sin(math.pi * arc)
        art = scene.draw(sky, late, 0.0)
        lit = lambda x: sum(art.getpixel((int(bx) + x, int(by) + y))[0] > 180 for y in (-1, 0, 1))
        assert (lit(-3) > 0, lit(3) > 0) == (lit_left, lit_right), (day, lit(-3), lit(3))
    noon = datetime(2026, 10, 14, 12, 0)
    assert scene.layers(sky, noon)[0] is scene.layers(sky, noon.replace(minute=5))[0], "nothing visible changed: nothing is rebuilt"
    morning = noon.replace(hour=9)   # between sunrise and dusk light is 1.0, so five minutes later is the same layers; inside dusk the windows change
    assert scene.layers(sky, morning)[0] is scene.layers(sky, morning.replace(minute=5))[0], "9:00 and 9:05 share their layers"
    dusk = noon.replace(hour=18, minute=30)
    assert scene.layers(sky, dusk)[0] is not scene.layers(sky, dusk.replace(minute=35))[0], "inside dusk the windows are redrawn every five minutes"
    assert scene.STRIKE * 4 == int(scene.LOOP * scene.FPS), "whole lightning strikes fill the loop"
    landscapes_check(at)
    stale = panel(SAMPLE, now, 4000, 0); fresh = panel(SAMPLE, now, 120, 0)
    assert stale.getpixel((600, 500)) == A and fresh.getpixel((600, 500)) != A, "an old forecast gets a bar you can read across the room"
    global CREDIT
    credit = CREDIT; CREDIT = ""
    try:
        assert panel(SAMPLE, now, 120, 0).tobytes() != fresh.tobytes(), "the skyline's credit is on the panel"
    finally:
        CREDIT = credit
    assert (fahrenheit(0), fahrenheit(100), round(fahrenheit(16.3))) == (32, 212, 61)
    lit = lambda img: sum(p != BG for p in img.crop((0, 477, img.width, 491)).getdata())   # the row under each day's high and low
    drawn = {(u, s): panel(SAMPLE, now, 120, 0, units=u, secondary=s) for u in "cf" for s in (False, True)}
    assert drawn["c", False].tobytes() == fresh.tobytes(), "°C, and nothing else, is what it always drew"
    assert len({img.tobytes() for img in drawn.values()}) == 4, "each of the four ways draws differently"
    assert lit(drawn["c", True]) > lit(drawn["c", False]) and lit(drawn["f", True]) > lit(drawn["f", False]), \
        "the second unit adds a line under each day"
    import tempfile
    with tempfile.TemporaryDirectory() as zd:   # the unit by where the forecast is for, from a zone.tab of our own
        zones = os.path.join(zd, "zone.tab")
        open(zones, "w").write("# country\tcoordinates\tTZ\tcomments\nUS\t+404251-0740023\tAmerica/New_York\tEastern (most areas)\n"
                               "CA\t+4339-07923\tAmerica/Toronto\tEastern - ON & QC (most areas)\nPR\t+182806-0660622\tAmerica/Puerto_Rico\n"
                               "CZ\t+5005+01426\tEurope/Prague\n")
        where = lambda tz: local_units({**SAMPLE, "timezone": tz}, zones)
        assert (where("America/New_York"), where("America/Puerto_Rico")) == ("f", "f"), "°F in the US"
        assert (where("America/Toronto"), where("Europe/Prague")) == ("c", "c"), "°C next door and everywhere else"
        assert where(None) == where("Mars/Base") == "c" and local_units(SAMPLE, os.path.join(zd, "none")) == "c", "can't tell: °C"
    assert panel({**SAMPLE, "timezone": "UTC"}, now, 120, 0).tobytes() == fresh.tobytes(), "left out: the place's own"
    assert frame(SAMPLE, now, 120, 0.0, "f", True).size == SCREEN
    assert (Page(units="f", secondary=True).units, Page(units="f", secondary=True).secondary) == ("f", True)
    assert (Page().units, Page().secondary) == (None, False), "by default, the place's own unit, and no second one"
    for bad in ({"units": "kelvin"}, {"units": "F"}, {"secondary": "yes"}, {"secondary": 1}):
        try:
            Page(**bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"took {bad}")
    wait = waiting(); lit = lambda box: max(sum(p) for p in wait.crop(box).getdata())
    assert lit((600, 190, 1320, 240)) > 600 and lit((400, 260, 1520, 300)) > 600, "the waiting screen names the page and is readable"
    sans = panel(SAMPLE, now, 120, 0)
    assert any(sans.getpixel((x, 238)) == B for x in range(340, 372)), "the rain bars have a legend"
    # null hours, no forecast yet, the location's own time zone
    gaps = json.loads(json.dumps(SAMPLE))
    gaps["hourly"]["temperature_2m"][3] = None
    assert frame(gaps, now, 0, 0.0).size == SCREEN, "an hour with no temperature is left out"
    gaps["hourly"]["temperature_2m"] = [None] * len(gaps["hourly"]["time"])
    assert frame(gaps, now, 0, 0.0).size == SCREEN, "no hourly temperatures at all: the strip says so"
    # odd data: what can be drawn is, what can't is no forecast yet
    assert frame(clean(SAMPLE), now, 0, 0.0).tobytes() == frame(SAMPLE, now, 0, 0.0).tobytes(), "a good forecast is drawn as it is"
    odd = json.loads(json.dumps(SAMPLE)); odd["hourly"]["temperature_2m"] = odd["hourly"]["temperature_2m"][:5]
    odd["daily"]["sunset"] = odd["daily"]["sunset"][:3]; odd["current"]["relative_humidity_2m"] = "12"; del odd["current"]["wind_direction_10m"]
    odd["daily"]["temperature_2m_max"][1] = 10 ** 9
    got = clean(odd)
    assert len(got["hourly"]["time"]) == 5 and len(got["daily"]["time"]) == 3, "lists that don't line up are cut to what does"
    assert got["daily"]["temperature_2m_max"][1] == 60 and got["current"]["relative_humidity_2m"] == 50, "clamped, and defaulted"
    odd_page = Page.showing(odd); odd_page.start(now)
    assert odd_page.data == got and odd_page.regions(now, 0.0), "and drawn"
    assert all(clean(x) is None for x in (None, "x", {}, {"current": {}}, {**SAMPLE, "daily": {}}, {**SAMPLE, "current": {"temperature_2m": "16"}}))
    assert Page.showing({}).data is None and Page.showing({}).regions(now, 0.0) == [], "no usable forecast: the page waits"
    assert "timezone=auto" in URL and "New_York" not in URL, "the forecast's hours are the location's own"
    global CACHE, fetch, download
    import tempfile
    real = CACHE, fetch, download
    with tempfile.TemporaryDirectory() as folder:
        try:
            CACHE = os.path.join(folder, "weather.json")
            Here = type("Here", (Page,), {"cache": CACHE})   # the page, with its cache in folder
            fetch = lambda lat, lon: (_ for _ in ()).throw(OSError("offline"))
            first = Here(); first.fetch_now()   # the very first fetch fails, with nothing cached
            key, bg = first.background(now)
            assert bg.size == SCREEN and first.regions(now, 0.0) == [] and isinstance(first.problem, OSError), "it waits, and says so, instead of crashing"
            open(CACHE, "w").write("{broken"); first.load()
            assert first.data is None and first.regions(now, 0.0) == [], "a broken cache is still no forecast"
            # a good forecast cached, then answers that aren't forecasts: the cache and the page keep the good one
            fetch = real[1]
            with open(CACHE, "w") as f:
                json.dump(SAMPLE, f)
            os.utime(CACHE, (1_000_000, 1_000_000))
            page = Here(); page._tried = time.time(); page.load()
            assert page.data == clean(SAMPLE) and page.updated == datetime.fromtimestamp(1_000_000)
            bad = [{"error": True}, {"current": SAMPLE["current"]}, json.loads(json.dumps(SAMPLE).replace('"temperature_2m": 16.3', '"temperature_2m": NaN')),
                   json.loads(json.dumps(SAMPLE).replace('"sunrise": ["2026-10-14T07:12"', '"sunrise": ["dawn"')),
                   {**SAMPLE, "hourly": {**SAMPLE["hourly"], "temperature_2m": [16]}},
                   {**SAMPLE, "daily": {**SAMPLE["daily"], "temperature_2m_max": [float("inf")] * 5}},
                   {**SAMPLE, "daily": {**SAMPLE["daily"], "weather_code": ["rain"] * 5}}, [], "forecast",
                   json.loads(json.dumps(SAMPLE).replace('"temperature_2m": 16.3', '"temperature_2m": 1' + "0" * 1000))]   # isfinite() overflows
            for answer in bad:
                download = lambda url: answer
                page.fetch_now(); page.load()
                with open(CACHE) as f:
                    assert json.load(f) == SAMPLE, f"{answer!r:.50} didn't replace the cache"
                assert page.data == clean(SAMPLE) and os.path.getmtime(CACHE) == 1_000_000, "nor the forecast, nor its age"
            assert valid(SAMPLE) is SAMPLE and all(valid(b) is None for b in bad)
            with open(CACHE, "w") as f:
                json.dump({"error": True}, f)
            page.load()
            assert page.data == clean(SAMPLE), "a cached answer that isn't a forecast isn't one: the page keeps the good one it had"
            # a slow network never holds up the page boundary: the fetch is in the background
            download = lambda url: (time.sleep(0.5), SAMPLE)[1]
            os.utime(CACHE, (1_000_000, 1_000_000))
            slow = Here(); began = time.time(); slow.start(now)
            assert time.time() - began < 0.25 and slow._busy, "the fetch is off the display path"
            while slow._busy:
                time.sleep(0.05)
        finally:
            CACHE, fetch, download = real


def landscapes_check(at):
    """every landscape in the catalog keeps the rules, and a landscape plays like Philadelphia does"""
    import shutil, tempfile
    folder = scene.LANDSCAPES
    names = sorted(n for n in os.listdir(folder) if os.path.isdir(os.path.join(folder, n))) if os.path.isdir(folder) else []
    for name in names:
        assert not scene.landscape_problems(os.path.join(folder, name)), (name, scene.landscape_problems(os.path.join(folder, name)))
    assert "lake" in names, "the catalog's sample landscape"
    lake = scene.landscape("lake")
    for code in (0, 63, 73, 95):   # it loops seamlessly in any weather, and it isn't Philadelphia
        w = json.loads(json.dumps(SAMPLE)); w["current"]["weather_code"] = code
        for t in (0.0, 9.25):
            assert scene.draw(w, at(19, 0), t, "lake").tobytes() == scene.draw(w, at(19, 0), t + scene.LOOP, "lake").tobytes(), (code, t)
    assert scene.draw(SAMPLE, at(12, 0), 0.0, "lake").tobytes() != scene.draw(SAMPLE, at(12, 0), 0.0).tobytes()
    assert scene.moment(SAMPLE, at(12, 0), "lake") != scene.moment(SAMPLE, at(12, 0)), "each landscape has its own loop"
    assert scene.layers(SAMPLE, at(12, 0), "lake")[0]["strike"] == tuple(lake["strike"]), "lightning hits its own peak"
    page = Page.showing(json.loads(json.dumps(SAMPLE)), landscape="lake")
    assert (page.lat, page.lon, page.place) == (lake["lat"], lake["lon"], "LAKE PLACID") and "Wi-Ki, CC0-1.0" in page.credit
    assert Page(landscape="lake", lat=1.0, place="HOME").lat == 1.0 and Page(landscape="lake", place="HOME").place == "HOME"
    assert Page().credit is None and Page().place == "PHILADELPHIA", "no landscape: Philadelphia, as always"
    for bad in ("nope", "../lake", "Lake"):
        try:
            Page(landscape=bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"took the landscape {bad!r}")
    # what a submitted one is held to
    with tempfile.TemporaryDirectory() as d:
        good = os.path.join(d, "good"); shutil.copytree(os.path.join(folder, "lake"), good)
        assert scene.landscape_problems(good) == []
        def broken(change, says):
            bad = os.path.join(d, "bad"); shutil.rmtree(bad, ignore_errors=True); shutil.copytree(good, bad)
            change(bad)
            got = scene.landscape_problems(bad)
            assert any(says in p for p in got), (says, got)
        meta = json.load(open(os.path.join(good, "landscape.json")))
        edit = lambda **k: lambda f: json.dump({**meta, **k}, open(os.path.join(f, "landscape.json"), "w"))
        broken(edit(credit={"author": "x", "licence": "all rights reserved", "source": "y"}), "licence is one of")
        broken(edit(credit={"author": "", "licence": "CC0-1.0", "source": "y"}), "author, licence and source")
        broken(edit(lat=91), "place on Earth")
        broken(edit(waterline=200), "waterline")
        broken(edit(strike=[400, 10]), "strike")
        broken(edit(place=""), "place is")
        broken(lambda f: os.remove(os.path.join(f, "landscape.png")), "landscape.png is missing")
        broken(lambda f: Image.new("RGBA", (200, 128)).save(os.path.join(f, "landscape.png")), "not 300x128")
        broken(lambda f: Image.new("L", (300, 64)).save(os.path.join(f, "water.png")), "water.png is 300x64")
        noisy = Image.frombytes("RGBA", scene.ART, os.urandom(scene.ART[0] * scene.ART[1] * 4))
        broken(lambda f: noisy.save(os.path.join(f, "landscape.png")), "over 64 KB")
        many = Image.new("RGBA", scene.ART); many.putdata([(i % 200, i // 200 % 200, 0, 255) for i in range(300 * 128)])
        broken(lambda f: many.save(os.path.join(f, "landscape.png")), "more than 64 colours")
        broken(lambda f: open(os.path.join(f, "landscape.json"), "w").write("{"), "won't read")


def preview(now=None):
    """one frame of the page with the cached forecast (or the sample), for kiosk.py --png"""
    w = cached() or SAMPLE
    return frame(w, now or datetime.now(), 0, 0.0)
