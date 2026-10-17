#!/usr/bin/env python3
"""eventsync: collects the calendar's events and writes them where the calendar page reads them. On the Pi a systemd
timer runs it at boot and every 15 minutes (systemd/kiosk-eventsync.*).

eventsync.json (~/.config/kiosk/eventsync.json if the kiosk has one) says where to write, how many days ahead to
look, and which sources to ask:
  {"output": "~/.cache/kiosk/events.json", "days": 14,
   "sources": [{"source": "recurring", "options": {...}}]}

A source is a module in sources/ exporting events(first, days, **options) -> [{"title", "start", ...}] and check().
Each event gets tagged with its source. If a source fails, its events from the last good run are kept, so a hiccup
doesn't empty the calendar. The file is written to a temporary name and moved into place, so the calendar never
reads half of it.

  eventsync.py                   sync now
  eventsync.py --check           self-test, every source's included
"""
import importlib, json, os, sys, tempfile
from datetime import date, datetime

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)  # -I leaves our own folder off the path
LOCAL_CONFIG = os.path.expanduser("~/.config/kiosk/eventsync.json")   # this kiosk's own sources; updates leave it alone
CONFIG = LOCAL_CONFIG if os.path.exists(LOCAL_CONFIG) else os.path.join(HERE, "eventsync.json")


def sync(config, today=None):
    """run every source and write the events file; returns the events it wrote"""
    out = os.path.expanduser(config["output"])
    days, today = config.get("days", 14), today or date.today()
    try:
        before = json.load(open(out)).get("events", [])
    except (OSError, ValueError, AttributeError):
        before = []
    events, failed = [], []
    for entry in config["sources"]:
        name = entry["source"]
        try:
            got = importlib.import_module(f"sources.{name}").events(today, days, **entry.get("options", {}))
            events += [dict(e, source=name) for e in got if e.get("title") and e.get("start")]
        except Exception as e:
            failed.append(name)
            print(f"eventsync: {name} failed, keeping its last events: {e}", file=sys.stderr)
            events += [e for e in before if e.get("source") == name]
    seen, unique = set(), []
    for e in sorted(events, key=lambda e: (e["start"], e["title"])):   # the same event from two sources shows once
        if (e["start"], e["title"].lower()) not in seen:
            seen.add((e["start"], e["title"].lower())); unique.append(e)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(out), suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump({"updated": datetime.now().isoformat(timespec="seconds"), "failed": failed, "events": unique}, f, indent=1)
    os.replace(tmp, out)
    return unique


def check():
    names = sorted(n[:-3] for n in os.listdir(os.path.join(HERE, "sources")) if n.endswith(".py") and n != "__init__.py")
    for name in names:
        importlib.import_module(f"sources.{name}").check()
    folder = tempfile.mkdtemp()
    out = os.path.join(folder, "events.json")
    for entry in json.load(open(CONFIG))["sources"]:   # this kiosk's sources exist
        assert entry["source"] in names, entry
    rules = [{"title": "Member Night", "weekday": "wednesday", "start": "19:00", "end": "22:00"},
             {"title": "Open House", "weekday": "sunday", "start": "14:00", "end": "17:00"}]
    config = {"output": out, "days": 14, "sources": [{"source": "recurring", "options": {"events": rules}}]}
    got = sync(config, date(2026, 10, 14))
    titles = {e["title"] for e in got}
    assert {"Member Night", "Open House"} <= titles and all(e["source"] == "recurring" for e in got), got
    assert json.load(open(out))["events"] == got and not [f for f in os.listdir(folder) if f.endswith(".tmp")]
    # a failing source keeps what it had last time; the others still run
    config["sources"] = config["sources"] + [{"source": "recurring", "options": {"events": [{"title": "x"}]}}]
    again = sync(config, date(2026, 10, 14))
    assert again == got and json.load(open(out))["failed"] == ["recurring"], "a broken source doesn't empty the calendar"
    print(f"eventsync: ok ({', '.join(names)})")


if __name__ == "__main__":
    if sys.argv[1:] == ["--check"]:
        check()
    elif len(sys.argv) == 1:
        got = sync(json.load(open(CONFIG)))
        print(f"eventsync: {len(got)} events")
    else:
        sys.exit(__doc__)
