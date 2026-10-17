"""recurring: events that happen on the same weekday every week, like Member Night and Open House.

Options (in eventsync.json): events, a list of
  {"title": "Member Night", "weekday": "wednesday", "start": "19:00", "end": "22:00", "location": "Hive76"}
Only title, weekday and start are required.
"""
from datetime import datetime, timedelta

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def events(first, days, events=()):
    """every occurrence from the date first, for days days"""
    out = []
    for rule in events:
        weekday = WEEKDAYS.index(rule["weekday"].lower())
        for i in range(days):
            day = first + timedelta(days=i)
            if day.weekday() != weekday:
                continue
            at = lambda hhmm: datetime.combine(day, datetime.strptime(hhmm, "%H:%M").time()).isoformat(timespec="minutes")
            e = {"title": rule["title"], "start": at(rule["start"])}
            if rule.get("end"): e["end"] = at(rule["end"])
            if rule.get("location"): e["location"] = rule["location"]
            out.append(e)
    return out


def check():
    from datetime import date
    rules = [{"title": "Member Night", "weekday": "Wednesday", "start": "19:00", "end": "22:00"},
             {"title": "Open House", "weekday": "sunday", "start": "14:00", "end": "17:00"}]
    got = events(date(2026, 10, 14), 14, rules)   # 14 Oct 2026 is a Wednesday
    assert [e["start"] for e in got if e["title"] == "Member Night"] == ["2026-10-14T19:00", "2026-10-21T19:00"], got
    assert [e["start"] for e in got if e["title"] == "Open House"] == ["2026-10-18T14:00", "2026-10-25T14:00"], got
    assert got[0]["end"] == "2026-10-14T22:00" and len(got) == 4
