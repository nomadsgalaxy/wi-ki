"""desk: the events on my desktop's calendars, the ones its Event Calendar widget shows. feed/deskfeed.py sends them in
the desk feed's calendar section (~/.cache/kiosk/desk.json), already in local time.

Options (in eventsync.json): feed, the desk feed (default ~/.cache/kiosk/desk.json).
A missing feed or a calendar section with an error fails, so the event sync keeps the last events it had.
"""
import json, os
from datetime import date, timedelta


def events(first, days, feed="~/.cache/kiosk/desk.json"):
    cal = json.load(open(os.path.expanduser(feed)))["calendar"]
    if cal.get("error"):
        raise RuntimeError(cal["error"])
    last = first + timedelta(days=days)
    # an event shows if any of it falls in the window: a trip that started last week and ends tomorrow included
    return [e for e in cal["items"]
            if date.fromisoformat(e["start"][:10]) < last and date.fromisoformat(e.get("end", e["start"])[:10]) >= first]


def check():
    import tempfile
    path = os.path.join(tempfile.mkdtemp(), "desk.json")
    items = [{"title": "1on1", "start": "2026-10-27T16:00", "end": "2026-10-27T16:30"},
             {"title": "Trip", "start": "2026-10-10", "end": "2026-10-15"},
             {"title": "Too late", "start": "2026-10-28T09:00"}, {"title": "Gone", "start": "2026-10-01"}]
    json.dump({"calendar": {"items": items, "error": None}}, open(path, "w"))
    assert [e["title"] for e in events(date(2026, 10, 14), 14, path)] == ["1on1", "Trip"]
    json.dump({"calendar": {"items": [], "error": "konsolekalendar: not found"}}, open(path, "w"))
    try:
        events(date(2026, 10, 14), 14, path); raise AssertionError("an error in the feed should fail the source")
    except RuntimeError:
        pass
