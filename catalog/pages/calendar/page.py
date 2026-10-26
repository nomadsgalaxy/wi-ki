"""The calendar page: the next 14 days as two weeks of seven, starting today, in the same VGA-font look as the weather
page. Each day shows its weather, when there's a forecast for it, and its events.

Events come from a JSON file that the event sync writes (events, below). Until that exists the days just show their
date and weather. The page reads the file again whenever it changes, and so it does the forecast.

  {"updated": "2026-10-14T15:00:00",
   "events": [{"title": "Open House", "start": "2026-10-16T19:00", "end": "2026-10-16T22:00",
               "all_day": false, "location": "the workshop"}]}

start and end are local times (America/New_York), or plain dates ("2026-10-24") for all-day events. Only title and
start are required. A broken entry is skipped, and a missing or broken file is just a calendar with no events.

Options (in playlist.json): events, the events file (default ~/.cache/kiosk/events.json); forecast, the weather
page's forecast cache (default ~/.cache/weather.json), for each day's weather; title, a name to go before NEXT 14 DAYS
(a place's name, say STUDIO; without one the heading is just NEXT 14 DAYS).
"""
import json, math, os
from datetime import date, datetime, timedelta
from PIL import Image, ImageDraw

from kit import SCREEN, O, W, G, C, BG, RULE, DIM, Simple, text, paste_icon, kind, warmth, packed

DAYS, COLUMNS = 14, 7
TOP, MARGIN = 72, 16
CELL_W = (SCREEN[0] - 2 * MARGIN) // COLUMNS
CELL_H = (SCREEN[1] - TOP - 8) // (DAYS // COLUMNS)
CELL, WEEKEND = (20, 23, 31), (22, 30, 48)        # weekends are tinted blue, so they stand out as they come up
WEEKEND_RULE, WEEKEND_TEXT = (52, 72, 112), (150, 190, 240)
SHOWN = 2   # lines a day has room for at the events' size; events that don't get one become "+N more"
BLINK = [packed(Image.new("RGB", (16, 32), c)) for c in (O, BG)]


def load_events(path):
    """the events file -> {date: [events, all-day first, then by start]}"""
    try:
        return events_from(json.load(open(path)))
    except (OSError, ValueError):
        return {}


def events_from(data):
    try:
        raw = data["events"]
    except (KeyError, TypeError):
        return {}
    days = {}
    for e in raw if isinstance(raw, list) else []:
        try:
            start = datetime.fromisoformat(e["start"])
        except (KeyError, TypeError, ValueError):
            continue
        if start.tzinfo:   # one with an offset is moved to the kiosk's own time, so it sorts with the rest
            start = start.astimezone().replace(tzinfo=None)
        all_day = bool(e.get("all_day")) or len(e["start"]) == 10
        days.setdefault(start.date(), []).append(dict(e, _start=start, _all_day=all_day))
    for evs in days.values():
        evs.sort(key=lambda e: (not e["_all_day"], e["_start"]))
    return days


def hour(t):
    """19:00 -> '7p', 9:30 -> '9:30a', the way hours read on the weather page"""
    return t.strftime("%I").lstrip("0") + (t.strftime(":%M") if t.minute else "") + ("a" if t.hour < 12 else "p")


def heading(title):
    """the big heading, what follows it, and where the cursor goes after them: STUDIO NEXT 14 DAYS, or with no title just
    NEXT 14 DAYS"""
    big, small = (title, "NEXT 14 DAYS") if title else ("NEXT 14 DAYS", "")
    x = 24 + len(big) * 24 + (24 + len(small) * 16 if small else 0)
    return big, small, (x + 8, 24)


def weather_by_day(forecast):
    """the weather page's forecast -> {date: (code, high, low)}; one that isn't the shape it should be is no weather"""
    try:
        dd = forecast["daily"]
        days = {date.fromisoformat(t): (dd["weather_code"][i], dd["temperature_2m_max"][i], dd["temperature_2m_min"][i])
                for i, t in enumerate(dd["time"])}
    except (KeyError, IndexError, TypeError, ValueError):
        return {}
    ok = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)   # JSON lets NaN and Infinity in
    return {k: v for k, v in days.items() if all(map(ok, v))}


def fit(title, room):
    """title in room characters: cut at a word where it can be, and an ellipsis to say it was"""
    if len(title) <= room:
        return title
    cut = title[:room - 1]
    if " " in cut[room // 2:]:
        cut = cut[:cut.rindex(" ")]
    return cut.rstrip() + "…"


def wrap(title, first, room, lines):
    """title in at most lines lines: the first first characters wide (after the time), the rest room wide (the whole
    day). Breaks between words, splits a word only when it's wider than a line, and the last line says it was cut."""
    out, words = [], title.split()
    while words and len(out) < lines:
        width = first if not out else room
        line = ""
        while words and len(line) + bool(line) + len(words[0]) <= width:
            line += (" " if line else "") + words.pop(0)
        if not line:   # a word wider than the line: as much of it as fits
            line, words[0] = words[0][:width], words[0][width:]
        out.append(line)
    if words and out:   # more than fits: the last line is cut, with an ellipsis
        out[-1] = fit(out[-1] + " " + " ".join(words), first if len(out) == 1 else room)
    return out


def draw(now, events, forecast=None, title=None):
    """the whole page, 1920x515 RGB"""
    img = Image.new("RGB", SCREEN, BG); d = ImageDraw.Draw(img)
    first = now.date(); last = first + timedelta(days=DAYS - 1)

    big, small, _ = heading(title)
    text(img, (24, 16), big, O, scale=3)
    if small:
        text(img, (24 + len(big) * 24 + 24, 24), small, W)
    text(img, (SCREEN[0] - 24, 24), f"{first.strftime('%b')} {first.day} - {last.strftime('%b')} {last.day}", G, right=True)
    d.rectangle((MARGIN, 62, SCREEN[0] - MARGIN, 63), fill=RULE)

    daily = weather_by_day(forecast)

    for i in range(DAYS):
        day = first + timedelta(days=i)
        x0, y0 = MARGIN + (i % COLUMNS) * CELL_W, TOP + (i // COLUMNS) * CELL_H
        x1, y1 = x0 + CELL_W - 6, y0 + CELL_H - 6
        today, weekend = i == 0, day.weekday() >= 5
        d.rectangle((x0, y0, x1, y1), fill=WEEKEND if weekend else CELL)
        d.rectangle((x0, y0, x1, y1), outline=O if today else WEEKEND_RULE if weekend else RULE, width=2 if today else 1)

        # the weekday and the date, and the month on the first day and on the 1st
        text(img, (x0 + 12, y0 + 10), "TODAY" if today else day.strftime("%a").upper(), O if today else WEEKEND_TEXT if weekend else G)
        text(img, (x0 + 12, y0 + 44), str(day.day), WEEKEND_TEXT if weekend and not today else W, scale=4)
        if i == 0 or day.day == 1:
            text(img, (x0 + 12 + len(str(day.day)) * 32 + 10, y0 + 76), day.strftime("%b").upper(), O)

        # the day's weather, top right
        if day in daily:
            code, hi, lo = daily[day]
            paste_icon(img, kind(code), 0, (x1 - 50, y0 + 8), 3)
            text(img, (x1 - 10, y0 + 60), f"{round(hi)}°", warmth(hi), scale=1, right=True)
            text(img, (x1 - 10, y0 + 78), f"{round(lo)}°", warmth(lo), scale=1, right=True)

        # the events: the time in orange (all-day ones in blue), then the title, wrapped onto the day's next line when
        # there's one to spare; every event that's shown keeps at least one line
        evs = events.get(day, [])
        y, room = y0 + 112, (x1 - x0 - 20) // 16          # characters across a day at scale 2 (15)
        shown = evs[:SHOWN]
        left = SHOWN
        for n, e in enumerate(shown):
            when = "" if e["_all_day"] else hour(e["_start"]) + " "
            lines = wrap(str(e.get("title", "")), room - len(when), room, left - (len(shown) - n - 1))
            text(img, (x0 + 12, y), when, O)
            for k, line in enumerate(lines):
                text(img, (x0 + 12 + (16 * len(when) if k == 0 else 0), y), line, C if e["_all_day"] else W)
                y += 36
            left -= len(lines)
        if len(evs) > SHOWN:
            text(img, (x0 + 12, y + 2), f"+{len(evs) - SHOWN} more", DIM, scale=1)
    return img


SAMPLE = {"updated": "2026-10-14T15:00:00", "events": [
    {"title": "Open House", "start": "2026-10-16T19:00", "end": "2026-10-16T22:00"},
    {"title": "3D Printing 101", "start": "2026-10-18T13:00", "end": "2026-10-18T15:00"},
    {"title": "Laser Cutter Checkout", "start": "2026-10-18T16:30", "end": "2026-10-18T17:30"},
    {"title": "Members Meeting", "start": "2026-10-21T19:30", "end": "2026-10-21T21:00"},
    {"title": "Halloween Build Night", "start": "2026-10-24", "all_day": True},
    {"title": "Soldering Workshop", "start": "2026-10-24T14:00"}, {"title": "Arduino Night", "start": "2026-10-24T18:00"},
    {"title": "Cleanup Day", "start": "2026-10-24T20:00"}, {"title": "past the window", "start": "2026-11-30T19:00"},
    {"title": "a broken entry with no start"}]}
FORECAST = {"daily": {"time": [f"2026-10-{d}" for d in range(14, 28)], "weather_code": [0, 2, 3, 61, 95, 71, 45] * 2,
                      "temperature_2m_max": [21 - d for d in range(14)], "temperature_2m_min": [10 - d for d in range(14)]}}


class Page(Simple):
    """the calendar, as a page of the kiosk's cycle: events is its file, and the forecast is read with each drawing"""
    name, seconds, SAMPLE = "calendar", 20, SAMPLE

    def __init__(self, events="~/.cache/kiosk/events.json", forecast="~/.cache/weather.json", title=None):
        self.file, self.forecast, self.title = events, os.path.expanduser(forecast), title
        self.cursor = heading(title)[2]   # just after the heading

    def draw(self, img, now, data):
        try:
            forecast = json.load(open(self.forecast))
        except (OSError, ValueError):
            forecast = None
        img.paste(draw(now, events_from(data), forecast, self.title))

    def moving(self, now, t, data):
        return [(BLINK[int(t * 2) % 2], self.cursor)]   # a blinking terminal cursor, so it's never quite still



def check():
    import tempfile
    with tempfile.TemporaryDirectory() as folder:
        _check(folder)


def _check(folder):
    events, forecast = os.path.join(folder, "events.json"), os.path.join(folder, "weather.json")
    json.dump(SAMPLE, open(events, "w")); json.dump(FORECAST, open(forecast, "w"))
    evs = load_events(events)
    assert [e["title"] for e in evs[date(2026, 10, 18)]] == ["3D Printing 101", "Laser Cutter Checkout"], evs
    assert evs[date(2026, 10, 24)][0]["title"] == "Halloween Build Night", "all-day events come first"
    assert sum(len(v) for v in evs.values()) == 9, "a broken entry is skipped, not fatal"
    assert load_events(os.path.join(folder, "missing.json")) == {}, "no file, no events"
    assert hour(datetime(2026, 1, 1, 19)) == "7p" and hour(datetime(2026, 1, 1, 9, 30)) == "9:30a"
    now = datetime(2026, 10, 14, 15, 0)
    assert draw(now, evs, FORECAST).size == SCREEN and draw(now, {}, None).size == SCREEN, "draws with or without data"
    Page.check(events=events, forecast=forecast)
    page = Page(events=events, forecast=forecast)
    key, bg = page.background(now)
    assert bg.mode == "LA" and bg.size == SCREEN and page.background(now)[0] == key, "redrawn only when something changes"
    assert page.regions(now, 0.0)[0][0].tobytes() != page.regions(now, 0.5)[0][0].tobytes(), "the cursor blinks"
    assert TOP + 2 * CELL_H <= SCREEN[1] and 112 + SHOWN * 36 + 18 <= CELL_H, "the grid and a full day fit"
    assert (CELL_W - 6 - 20) // 16 >= len("7p Member Night"), "a Member Night fits on one line"
    assert fit("Members Meeting", 15 - len("7:30p ")) == "Members…" and fit("Open House", 9) == "Open…", "cut at a word"
    assert fit("Supercalifragilistic", 9) == "Supercal…" and fit("Open House", 10) == "Open House"
    # wrapping: the rest of a title goes on the day's next line, the whole day wide, and only what doesn't fit is cut
    assert wrap("Hive76 Open House", 9, 15, 2) == ["Hive76", "Open House"]
    assert wrap("Hive76 Open House", 9, 15, 1) == ["Hive76…"], "one line: cut as before"
    assert wrap("Intro to Arduino and Microcontroller Programming", 9, 15, 2) == ["Intro to", "Arduino and…"]
    assert wrap("Member Night", 12, 15, 2) == ["Member Night"], "it only wraps when it has to"
    assert wrap("Supercalifragilistic", 9, 15, 2) == ["Supercali", "fragilistic"], "a word too wide is split"
    assert wrap("", 9, 15, 2) == [] and wrap("Open House", 9, 15, 0) == []
    for title in ("Intro to Arduino and Microcontroller Programming", "a b c d e f g h i j k l m n o p", "x" * 80):
        for lines in (1, 2):
            got = wrap(title, 9, 15, lines)
            assert len(got) <= lines and len(got[0]) <= 9 and all(len(l) <= 15 for l in got[1:]), (title, lines, got)
    for bad in ({"daily": []}, {"daily": {"time": ["2026-10-14"]}}, {"daily": {**FORECAST["daily"], "time": ["soon"]}},
                {"daily": {**FORECAST["daily"], "weather_code": [0]}}, {"daily": {**FORECAST["daily"], "temperature_2m_max": ["hot"] * 14}},
                [], "weather"):
        assert weather_by_day(bad) == {} and draw(now, evs, bad).size == SCREEN, f"a forecast like {bad!r:.40} is no weather, not a crash"
    assert len(weather_by_day(FORECAST)) == 14
    for key in ("temperature_2m_max", "temperature_2m_min"):   # non-finite highs and lows
        for odd in (float("nan"), float("inf"), float("-inf")):
            bent = {"daily": {**FORECAST["daily"], key: [odd] + FORECAST["daily"][key][1:]}}
            days = weather_by_day(bent)
            assert len(days) == 13 and date(2026, 10, 14) not in days, f"a {key} of {odd} is no weather that day"
            assert draw(now, evs, bent).size == SCREEN
    mixed = events_from({"events": [{"title": "a", "start": "2026-10-24T14:00+00:00"}, {"title": "b", "start": "2026-10-24T09:00"}]})
    assert all(e["_start"].tzinfo is None for v in mixed.values() for e in v), "an offset start sorts with local ones"
    assert heading(None) == ("NEXT 14 DAYS", "", (24 + 12 * 24 + 8, 24)) and heading("STUDIO")[2] == (24 + 6 * 24 + 24 + 12 * 16 + 8, 24)
    assert Page(events=events, forecast=forecast, title="STUDIO").cursor == heading("STUDIO")[2]


def preview(now=None):
    """the page with the sample events and forecast, for the emulator and kiosk.py --png"""
    return draw(now or datetime(2026, 10, 14, 15, 0), events_from(SAMPLE), FORECAST)
