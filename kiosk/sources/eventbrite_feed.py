"""eventbrite_feed: the events a WordPress site lists with the "Event Feed for Eventbrite" plugin, read from the JSON
the plugin's own feed uses, so no Eventbrite key is needed here.

Options (in eventsync.json):
  {"url": "https://example.org/wp-json/event-feed-for-eventbrite/v1/feed/<feed ID>"}
The feed ID is the number in the page's event feed (data-feed="..."). The site decides how many events the feed has
(often 8), so a busy feed may only reach a week or two ahead.
"""
import html, json, re, urllib.request
from datetime import datetime, timedelta

UA = {"User-Agent": "wi-ki eventsync (github.com/nomadsgalaxy/wi-ki)"}
URL = re.compile(r"https://[A-Za-z0-9.-]+(:[0-9]+)?/wp-json/event-feed-for-eventbrite/v1/feed/[0-9]+")


def fetch(url):
    if not URL.fullmatch(url):
        raise ValueError("url has to be a site's https://…/wp-json/event-feed-for-eventbrite/v1/feed/<ID>")
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:
        return json.loads(r.read(2 << 20))


def parse(feed, first, days):
    """the feed's JSON -> events from the date first, for days days, in the events' own local time"""
    out, last = [], first + timedelta(days=days)
    for e in (feed.get("events") or []) if isinstance(feed, dict) else []:
        try:
            start = datetime.fromisoformat(e["start"]["local"])
            title = re.sub(r"\s+", " ", html.unescape(e.get("post_title") or "")).strip()
        except (KeyError, TypeError, ValueError):
            continue
        if not title or not first <= start.date() < last:
            continue
        got = {"title": title, "start": start.isoformat(timespec="minutes")}
        try:
            got["end"] = datetime.fromisoformat(e["end"]["local"]).isoformat(timespec="minutes")
        except (KeyError, TypeError, ValueError):
            pass
        venue = e.get("venue")
        if isinstance(venue, dict) and isinstance(venue.get("name"), str) and venue["name"].strip():
            got["location"] = venue["name"].strip()
        out.append(got)
    return out


def events(first, days, url):
    return parse(fetch(url), first, days)


def check():
    from datetime import date
    feed = {"events": [
        {"post_title": "Open House", "start": {"local": "2026-10-25T14:30:00"}, "end": {"local": "2026-10-25T17:00:00"},
         "venue": {"name": "The Shop"}},
        {"post_title": "Intro to Arduino &amp; Microcontrollers", "start": {"local": "2026-11-02T18:30:00"},
         "end": {"local": "2026-11-02T21:00:00"}, "venue": None},
        {"post_title": "Too far out", "start": {"local": "2026-12-25T10:00:00"}},
        {"post_title": "", "start": {"local": "2026-10-26T10:00:00"}},
        {"post_title": "No start"}, "junk"]}
    got = parse(feed, date(2026, 10, 24), 14)
    assert got == [{"title": "Open House", "start": "2026-10-25T14:30", "end": "2026-10-25T17:00", "location": "The Shop"},
                   {"title": "Intro to Arduino & Microcontrollers", "start": "2026-11-02T18:30", "end": "2026-11-02T21:00"}], got
    assert parse({"events": "nope"}, date(2026, 10, 24), 14) == [] and parse([], date(2026, 10, 24), 14) == []
    for bad in ("http://example.org/wp-json/event-feed-for-eventbrite/v1/feed/1", "https://example.org/feed/1",
                "https://example.org/wp-json/event-feed-for-eventbrite/v1/feed/1?x=1"):
        try:
            fetch(bad); raise AssertionError(f"fetched {bad}")
        except ValueError:
            pass
