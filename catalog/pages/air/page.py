"""Air: how clean the air is where the kiosk is, and the sun's UV. The US Air Quality Index now, big, in the EPA's
colour for it and with what it means, what's in the air (fine and coarse particles, ozone, nitrogen dioxide), the UV
index, and the next 24 hours of both as bars.

The data is Open-Meteo's air quality forecast (no key; CAMS's model, so it's a forecast for the area, not a sensor down
the street), fetched every half hour into a cache every renderer on the machine shares (kit.Simple).

Options (in playlist.json, or the setup page's Location): lat and lon (default: central Philadelphia), and place, for
the heading.
"""
import json, math, urllib.parse, urllib.request
from datetime import datetime
from PIL import ImageDraw

from kit import SCREEN, Simple, O, W, G, D, A, M, GREEN, ERROR, RULE, text, masthead, freshness

API = "https://air-quality-api.open-meteo.com/v1/air-quality?"
UA = {"User-Agent": "wi-ki air (github.com/nomadsgalaxy/wi-ki)"}
# the US AQI's bands, with the EPA's colours for them (yellow is the brand's amber)
AQI = ((50, "GOOD", GREEN, "Air quality is good. Enjoy the outdoors."),
       (100, "MODERATE", A, "Fine for most. Very sensitive people may want to take it easy."),
       (150, "UNHEALTHY FOR SOME", (255, 140, 60), "Sensitive groups: keep long outdoor effort short."),
       (200, "UNHEALTHY", ERROR, "Everyone: cut back on long or heavy effort outside."),
       (300, "VERY UNHEALTHY", M, "Everyone: avoid long or heavy effort outside."),
       (math.inf, "HAZARDOUS", (190, 60, 90), "Everyone: stay indoors and keep activity low."))
UV = ((2, "LOW", GREEN), (5, "MODERATE", A), (7, "HIGH", (255, 140, 60)), (10, "VERY HIGH", ERROR), (math.inf, "EXTREME", M))
GASES = (("pm2_5", "PM2.5", "fine particles"), ("pm10", "PM10", "coarse particles"),
         ("ozone", "O3", "ozone"), ("nitrogen_dioxide", "NO2", "nitrogen dioxide"))
HOURS = 24
LEFT, RIGHT, TOP, BOTTOM = 1000, 1880, 150, 400   # the next 24 hours


def band(value, bands):
    return next(b for b in bands if value <= b[0])


def number(v, high):
    """v as a number from 0 to high, or None if it isn't one"""
    try:
        v = float(v)
        return max(0.0, min(high, v)) if math.isfinite(v) else None
    except (TypeError, ValueError, OverflowError):
        return None


def clean(raw):
    """Open-Meteo's answer -> {"time", "aqi", "uv", the gases, "hours": [[time, aqi, uv]]}, every number made to fit
    (None where it isn't one), or None with no AQI now"""
    if not isinstance(raw, dict) or not isinstance(raw.get("current"), dict):
        return None
    now = raw["current"]
    if number(now.get("us_aqi"), 999) is None:
        return None
    out = {"time": str(now.get("time") or "")[:16], "aqi": number(now["us_aqi"], 999), "uv": number(now.get("uv_index"), 30)}
    out.update({key: number(now.get(key), 9999) for key, _, _ in GASES})
    hourly = raw.get("hourly") if isinstance(raw.get("hourly"), dict) else {}
    times, aqi, uv = (hourly.get(k) if isinstance(hourly.get(k), list) else [] for k in ("time", "us_aqi", "uv_index"))
    out["hours"] = [[str(t)[:16], number(a, 999), number(u, 30)] for t, a, u in zip(times, aqi, uv + [None] * len(times))]
    return out


class Page(Simple):
    """the air, as a page of the kiosk's cycle"""
    name, seconds = "air", 20
    every = 1800   # the model runs every hour or so; half an hour keeps it close without asking too often
    SAMPLE = {"current": {"time": "2026-10-19T09:00", "us_aqi": 73, "pm2_5": 19.2, "pm10": 20.0, "ozone": 32.0,
                                "nitrogen_dioxide": 28.7, "uv_index": 2.65},
                    "hourly": {"time": [f"2026-10-{19 + h // 24}T{h % 24:02d}:00" for h in range(48)],
                               "us_aqi": [round(60 + 30 * math.sin(h / 4)) for h in range(48)],
                               "uv_index": [round(max(0, 4.5 * math.sin((h % 24 - 7) / 11 * math.pi)), 2) for h in range(48)]}}   # as fetch() gives it
    clean = staticmethod(clean)
    mark = (SCREEN[0] - 24, 54)

    def __init__(self, lat=39.95, lon=-75.17, place=None):
        self.lat, self.lon, self.place = float(lat), float(lon), place

    def fetch(self):
        query = urllib.parse.urlencode({"latitude": self.lat, "longitude": self.lon, "timezone": "auto", "forecast_days": 2,
                                        "current": "us_aqi,uv_index," + ",".join(k for k, _, _ in GASES),
                                        "hourly": "us_aqi,uv_index"})
        with urllib.request.urlopen(urllib.request.Request(API + query, headers=UA), timeout=20) as r:
            raw = json.load(r)
        return {k: raw.get(k) for k in ("current", "hourly")}   # just what draw() uses

    def draw(self, img, now, data):
        place = str(self.place or "")[:24].upper()
        said, old = freshness(self.updated, now, 3 * self.every)
        masthead(img, now, "// AIR" + (f" · {place}" if place else ""), "AIR QUALITY",
                 (f"can't reach Open-Meteo: {said}", A) if self.problem and old else (said, A if old else D))
        aqi = data["aqi"]
        _, words, colour, advice = band(aqi, AQI)
        d = ImageDraw.Draw(img)
        text(img, (40, 108), "US AQI", G, scale=2)
        text(img, (40, 140), str(round(aqi)), colour, scale=10)
        text(img, (40, 312), words, colour, scale=3)
        for i, line in enumerate(wrap(advice, 52)[:3]):
            text(img, (40, 372 + i * 24), line, W, scale=1)
        y = 120   # what's in the air, and the UV
        for key, short, long in GASES:
            value = data.get(key)
            text(img, (560, y), short, O, scale=2)
            text(img, (680, y), "--" if value is None else f"{value:.0f}", W, scale=2)
            text(img, (760, y + 8), f"µg/m³  {long}", D, scale=1)
            y += 48
        uv = data.get("uv")
        if uv is not None:
            _, words, colour = band(round(uv), UV)   # by the number shown: 2.65 is a 3, and moderate
            text(img, (560, y + 12), "UV", O, scale=2)
            text(img, (680, y + 12), f"{uv:.0f}", colour, scale=2)
            text(img, (760, y + 20), words, colour, scale=1)
        # the next 24 hours: the AQI as bars, the UV as a line over them
        hours = [h for h in data.get("hours", []) if h[0] >= now.strftime("%Y-%m-%dT%H:00")][:HOURS]
        text(img, (LEFT, 108), "NEXT 24 HOURS", G, scale=2)
        text(img, (RIGHT, 116), "bars: AQI   line: UV", D, scale=1, right=True)
        top = max([h[1] for h in hours if h[1] is not None] + [100])
        step = (RIGHT - LEFT) / HOURS
        uv_points = []
        for i, (when, value, uv) in enumerate(hours):
            x = LEFT + round(i * step)
            if value is not None:
                h = round(value / top * (BOTTOM - TOP))
                d.rectangle((x + 2, BOTTOM - h, x + round(step) - 4, BOTTOM), fill=band(value, AQI)[2])
            if uv is not None:
                uv_points.append((x + round(step / 2), BOTTOM - round(min(uv, 12) / 12 * (BOTTOM - TOP))))
            if when[11:13] in ("00", "06", "12", "18"):
                hour = int(when[11:13])
                text(img, (x, BOTTOM + 10), "12a" if hour == 0 else "12p" if hour == 12 else f"{hour % 12}{'a' if hour < 12 else 'p'}", D, scale=1)
        d.rectangle((LEFT, BOTTOM + 1, RIGHT, BOTTOM + 2), fill=RULE)
        if len(uv_points) > 1:
            d.line(uv_points, fill=W, width=2)
        if not hours:
            text(img, (LEFT, 200), "no forecast", D, scale=2)
        text(img, (RIGHT, 492), "open-meteo.com · CAMS forecast", D, scale=1, right=True)


def wrap(words, width):
    """words in lines of at most width characters"""
    lines = [""]
    for word in str(words).split():
        if lines[-1] and len(lines[-1]) + 1 + len(word) > width:
            lines.append("")
        lines[-1] = (lines[-1] + " " + word).strip()
    return lines


def check():
    assert band(0, AQI)[1] == "GOOD" and band(50, AQI)[1] == "GOOD" and band(51, AQI)[1] == "MODERATE" and band(999, AQI)[1] == "HAZARDOUS"
    assert band(2, UV)[1] == "LOW" and band(3, UV)[1] == "MODERATE" and band(11, UV)[1] == "EXTREME"
    assert clean(None) is None and clean({"current": {"us_aqi": None}}) is None, "no AQI now is no data"
    odd = clean({"current": {"us_aqi": "1e9", "pm2_5": "x", "uv_index": float("nan")}, "hourly": {"time": ["a"], "us_aqi": "x"}})
    assert odd["aqi"] == 999 and odd["pm2_5"] is None and odd["uv"] is None and odd["hours"] == [], odd
    assert len(clean(Page.SAMPLE)["hours"]) == 48 and clean(Page.SAMPLE)["hours"][9][0] == "2026-10-19T09:00"
    assert wrap("one two three", 7) == ["one two", "three"]
    Page.check()


def preview(now=None):
    return Page.preview(now)
