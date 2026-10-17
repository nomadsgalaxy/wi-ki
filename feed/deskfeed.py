#!/usr/bin/env python3
"""deskfeed: what the desk kiosk's github and agents pages show, gathered on my desktop, since the Pi can't see any of it.

It collects four things and prints them as one JSON document:
  github    the newest pushes, open PRs and issues for each owner in OWNERS (gh, so private repos count too)
  usage     Claude Personal, Claude Work and Codex quota windows, from KodexBar's engine (kodexbar-quotas)
  herdr     my herdr workspaces and the agents running in each one (herdr api snapshot)
  calendar  the next DAYS days of events from the calendars the Event Calendar widget shows (Akonadi, through
            konsolekalendar; the widget's list is PIMEventsPlugin's in plasmashellrc). Title, times and location only,
            never descriptions. The kiosk's event sync takes them from here (kiosk/sources/desk.py).

A section that fails says why in its "error" and the others still go out. deskfeed.service pipes the output to the Pi
over SSH, with a key that is only allowed to write ~/.cache/kiosk/desk.json (see feed/README.md).

  deskfeed.py            print the feed
  deskfeed.py --check    self-test the parsing on sample data
"""
import csv, io, json, os, sqlite3, subprocess, sys
from datetime import date, datetime, timedelta, timezone

OWNERS = [("nomadsgalaxy", "Nomads Galaxy"), ("Positron3D", "Positron 3D"), ("hive76", "Hive76")]
REPOS = 5
WINDOWS = {300: "5h", 10080: "week"}
DAYS = 14
PLASMA, AKONADI = os.path.expanduser("~/.config/plasmashellrc"), os.path.expanduser("~/.local/share/akonadi/akonadi.db")


def run(*cmd, timeout=120):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=True).stdout


def github_query():
    parts = []
    for i, (login, _) in enumerate(OWNERS):
        parts.append(f'''
  o{i}: repositoryOwner(login: "{login}") {{ repositories(first: {REPOS}, ownerAffiliations: OWNER,
        orderBy: {{field: PUSHED_AT, direction: DESC}}) {{ nodes {{ name isPrivate pushedAt
        defaultBranchRef {{ target {{ ... on Commit {{ messageHeadline }} }} }} }} }} }}
  p{i}: search(query: "is:pr is:open user:{login}", type: ISSUE) {{ issueCount }}
  i{i}: search(query: "is:issue is:open user:{login}", type: ISSUE) {{ issueCount }}''')
    return "query {" + "".join(parts) + "\n}"


def github_parse(data):
    out = []
    for i, (login, label) in enumerate(OWNERS):
        repos = ((data.get(f"o{i}") or {}).get("repositories") or {}).get("nodes") or []
        out.append({"owner": label, "login": login, "prs": data[f"p{i}"]["issueCount"], "issues": data[f"i{i}"]["issueCount"],
                    "repos": [{"name": r["name"], "private": r["isPrivate"], "pushed": r["pushedAt"],
                               "commit": ((r.get("defaultBranchRef") or {}).get("target") or {}).get("messageHeadline", "")}
                              for r in repos]})
    return out


def usage_parse(entries):
    """kodexbar-quotas usage JSON -> [{label, windows: [{name, used, resets}], error}]"""
    out = []
    for e in entries:
        u = e.get("usage") or {}
        label = e.get("provider", "?").capitalize() + (f" {e['profileLabel']}" if e.get("profileLabel") else "")
        windows = []
        for key in ("primary", "secondary", "tertiary"):
            w = u.get(key)
            if w and w.get("usedPercent") is not None:
                windows.append({"name": WINDOWS.get(w.get("windowMinutes"), f"{w.get('windowMinutes')}m"),
                                "used": w["usedPercent"], "resets": w.get("resetsAt")})
        for x in u.get("extraRateWindows") or []:   # model-specific weekly limits, like Fable
            w = x.get("window") or {}
            if w.get("usageKnown", True) and w.get("usedPercent") is not None:
                windows.append({"name": x.get("title", "?"), "used": w["usedPercent"], "resets": w.get("resetsAt")})
        out.append({"label": label, "windows": windows, "error": e.get("error") if not windows else None})
    return out


def herdr_parse(snapshot):
    """herdr's session snapshot -> [{label, agents: [{title, status, agent}]}], in herdr's workspace order"""
    s = snapshot["result"]["snapshot"]
    agents = {}
    for a in s.get("agents", []):
        agents.setdefault(a["workspace_id"], []).append(
            {"title": a.get("terminal_title_stripped") or a.get("agent", ""), "status": a.get("agent_status", "unknown"),
             "agent": a.get("agent", "")})
    return [{"label": w["label"], "agents": agents.get(w["workspace_id"], [])} for w in s.get("workspaces", [])]


def calendar_ids(rc):
    """plasmashellrc's text -> the Akonadi collection ids the Event Calendar widget shows"""
    group = None
    for line in rc.splitlines():
        if line.startswith("["):
            group = line.strip()
        elif group == "[PIMEventsPlugin]" and line.startswith("calendars="):
            return {int(x) for x in line.split("=", 1)[1].split(",") if x.strip().isdigit()}
    return set()


def calendar_parse(rows, ours):
    """konsolekalendar's CSV rows (start date, start time, end date, end time, summary, location, description, uid) ->
    [{title, start, end, location}] for the events whose uid is in ours (the widget's calendars), once each. Times are
    already local; an all-day event has none."""
    out, seen = [], set()
    for r in rows:
        if len(r) < 8:
            continue
        sd, st, ed, et, title, where, _, uid = r[:8]
        if uid not in ours and uid.rsplit("@", 1)[0] not in ours:
            continue
        e = {"title": title, "start": f"{sd}T{st[:5]}" if st else sd, "end": f"{ed}T{et[:5]}" if et else ed}
        if where:
            e["location"] = where
        if (title, e["start"]) not in seen:   # the same event in two calendars (Event Tracker's in both accounts)
            seen.add((title, e["start"])); out.append(e)
    return out


def calendar():
    wanted, first = calendar_ids(open(PLASMA).read()), date.today()
    rows = list(csv.reader(io.StringIO(run("konsolekalendar", "--view", "--export-type", "csv", "--date", first.isoformat(),
                                           "--end-date", (first + timedelta(days=DAYS - 1)).isoformat()))))
    return calendar_parse(rows, akonadi_uids(wanted))


def akonadi_uids(collections):
    """every uid in those Akonadi calendars: each item's remoteId (Google's event id, its uid minus @google.com) and
    the UID inside its iCalendar (the only match for events another app put there, like Event Tracker's)"""
    ours, files = set(), None
    with sqlite3.connect(f"file:{AKONADI}?mode=ro", uri=True) as db:   # read-only: Akonadi owns it
        marks = ",".join("?" * len(collections))
        for rid, data, storage in db.execute(f"select i.remoteId, p.data, p.storage from PimItemTable i left join PartTable p "
                                             f"on p.pimItemId = i.id where i.collectionId in ({marks})", list(collections)):
            ours.add(rid)
            if storage == 1:   # a big payload lives in a file of its own, named by data
                if files is None:
                    files = {f: os.path.join(d, f) for d, _, fs in os.walk(os.path.join(os.path.dirname(AKONADI), "file_db_data")) for f in fs}
                data = open(files[data.decode()], "rb").read() if data and data.decode() in files else b""
            ours |= ical_uids(data)
    return ours - {None, ""}


def ical_uids(data):
    """the UID lines of an iCalendar payload (bytes or text), unfolded"""
    text = (data.decode("utf-8", "replace") if isinstance(data, bytes) else data or "").replace("\r\n ", "").replace("\n ", "")
    return {line[4:].strip() for line in text.splitlines() if line.startswith("UID:")}


def section(fn):
    try:
        return {"items": fn(), "error": None}
    except Exception as e:   # one broken source mustn't blank the other pages
        return {"items": [], "error": f"{type(e).__name__}: {e}"[:120]}


def feed():
    return {"updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "github": section(lambda: github_parse(json.loads(run("gh", "api", "graphql", "-f", f"query={github_query()}"))["data"])),
            "usage": section(lambda: usage_parse(json.loads(run("kodexbar-quotas", "usage", "--provider", "enabled")))),
            "herdr": section(lambda: herdr_parse(json.loads(run("herdr", "api", "snapshot")))),
            "calendar": section(calendar)}


def check():
    gh = {"o0": {"repositories": {"nodes": [{"name": "desk-kiosk", "isPrivate": True, "pushedAt": "2026-10-15T03:23:14Z",
                                             "defaultBranchRef": {"target": {"messageHeadline": "Celsius"}}},
                                            {"name": "empty", "isPrivate": False, "pushedAt": "2026-10-14T00:00:00Z",
                                             "defaultBranchRef": None}]}},
          "p0": {"issueCount": 2}, "i0": {"issueCount": 5}, "o1": None, "p1": {"issueCount": 0}, "i1": {"issueCount": 0},
          "o2": {"repositories": {"nodes": []}}, "p2": {"issueCount": 1}, "i2": {"issueCount": 3}}
    g = github_parse(gh)
    assert g[0]["repos"][0] == {"name": "desk-kiosk", "private": True, "pushed": "2026-10-15T03:23:14Z", "commit": "Celsius"}
    assert g[0]["repos"][1]["commit"] == "" and g[1]["repos"] == [] and g[2]["issues"] == 3, g
    u = usage_parse([
        {"provider": "claude", "profileLabel": "Work", "usage": {"primary": {"usedPercent": 6.0, "windowMinutes": 300, "resetsAt": "x"},
         "secondary": {"usedPercent": 55.0, "windowMinutes": 10080}, "tertiary": None,
         "extraRateWindows": [{"title": "Fable", "window": {"usedPercent": 15.0, "usageKnown": True}}]}},
        {"provider": "codex", "usage": {"primary": None, "secondary": {"usedPercent": 6.0, "windowMinutes": 10080}}},
        {"provider": "claude", "profileLabel": "Personal", "error": "signed out"}])
    assert [w["name"] for w in u[0]["windows"]] == ["5h", "week", "Fable"] and u[0]["label"] == "Claude Work", u
    assert u[1]["label"] == "Codex" and u[1]["windows"][0]["name"] == "week" and u[2]["error"] == "signed out", u
    h = herdr_parse({"result": {"snapshot": {
        "workspaces": [{"workspace_id": "w1", "label": "kiosk"}, {"workspace_id": "w2", "label": "empty"}],
        "agents": [{"workspace_id": "w1", "terminal_title_stripped": "Kiosk pages", "agent_status": "working", "agent": "claude"}]}}})
    assert h == [{"label": "kiosk", "agents": [{"title": "Kiosk pages", "status": "working", "agent": "claude"}]},
                 {"label": "empty", "agents": []}], h
    assert section(lambda: 1 / 0)["error"].startswith("ZeroDivisionError")
    assert calendar_ids("[General]\ncalendars=1\n\n[PIMEventsPlugin]\ncalendars=6,24, 31\n") == {6, 24, 31}
    rows = [["2026-10-15", "20:00:00", "2026-10-15", "20:30:00", "Team Meeting", "", "secret notes", "abc@google.com"],
            ["2026-10-15", "19:00:00", "2026-10-15", "22:00:00", "Happy Hour", "a bar", "", "xyz@google.com"],
            ["2026-10-18", "", "2026-10-18", "", "Day off", "", "", "local-1"],
            ["2026-10-18", "", "2026-10-18", "", "Day off", "", "", "local-2"], ["short"]]
    assert ical_uids(b"BEGIN:VEVENT\r\nUID:0400000082\r\n 00E0074\r\nSUMMARY:x\r\n") == {"040000008200E0074"}, "unfolded"
    c = calendar_parse(rows, {"abc", "local-1", "local-2"})
    assert c == [{"title": "Team Meeting", "start": "2026-10-15T20:00", "end": "2026-10-15T20:30"},
                 {"title": "Day off", "start": "2026-10-18", "end": "2026-10-18"}], c
    print("deskfeed: ok")


if __name__ == "__main__":
    if sys.argv[1:] == ["--check"]:
        check()
    elif not sys.argv[1:]:
        json.dump(feed(), sys.stdout)
    else:
        sys.exit(__doc__)
