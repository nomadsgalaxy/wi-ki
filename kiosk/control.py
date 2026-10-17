#!/usr/bin/env python3
"""control: lets my desktop pick what the kiosk shows. It's the forced command of the desktop's control key on the Pi
(see feed/README.md), so the key can do this and nothing else. The command comes in SSH_ORIGINAL_COMMAND:

  status          {"pages": [...], "showing": "<page>", "pinned": "<page>" or null}, as JSON
  show <page>     jump to that page and stay there
  auto            back to the normal rotation
  next            on to the next page, and back to the rotation
  touch <x> <y>   a touch on the screen at x, y (for trying a touchable page without a touch screen)

It writes ~/.cache/kiosk/control.json, which kiosk.py watches: {"page": <pinned page or null>, "skip": <changes on
every next>}. kiosk.py writes the page it's showing to ~/.cache/kiosk/showing. This deliberately imports nothing
heavy: on a Pi Zero, loading Pillow alone takes a couple of seconds.
"""
import json, os, sys, time

HERE = os.path.dirname(os.path.realpath(__file__))
CACHE = os.path.expanduser("~/.cache/kiosk")
LOCAL_PLAYLIST = os.path.expanduser("~/.config/kiosk/playlist.json")   # this kiosk's own, as in kiosk.py
PLAYLIST = LOCAL_PLAYLIST if os.path.exists(LOCAL_PLAYLIST) else os.path.join(HERE, "playlist.json")


def pages(playlist=PLAYLIST):
    return [e.get("name", e["page"]) for e in json.load(open(playlist)) if e.get("on") is not False]


def read(path):
    try:
        return json.load(open(path))
    except (OSError, ValueError):
        return {}


def run(args, cache=CACHE, playlist=PLAYLIST):
    """one command -> what to print. Raises ValueError for one it doesn't know."""
    control, names = os.path.join(cache, "control.json"), pages(playlist)
    state = read(control)
    if args == ["status"]:
        try:
            showing = open(os.path.join(cache, "showing")).read().strip()
        except OSError:
            showing = None
        pinned = state.get("page") if state.get("page") in names else None
        return json.dumps({"pages": names, "showing": showing, "pinned": pinned})
    if len(args) == 2 and args[0] == "show" and args[1] in names:
        state["page"] = args[1]
    elif args == ["auto"]:
        state["page"] = None
    elif args == ["next"]:
        state["page"], state["skip"] = None, time.time()
    elif len(args) == 3 and args[0] == "touch" and all(a.isdigit() for a in args[1:]):
        os.makedirs(cache, exist_ok=True)
        touch = os.path.join(cache, "touch.json")
        json.dump({"x": int(args[1]), "y": int(args[2])}, open(touch + ".tmp", "w")); os.replace(touch + ".tmp", touch)
        return "ok"
    else:
        raise ValueError(f"usage: status | show <{'|'.join(names)}> | auto | next | touch <x> <y>")
    os.makedirs(cache, exist_ok=True)
    json.dump(state, open(control + ".tmp", "w")); os.replace(control + ".tmp", control)
    return "ok"


def check():
    import tempfile
    cache, playlist = tempfile.mkdtemp(), os.path.join(tempfile.mkdtemp(), "playlist.json")
    json.dump([{"page": "weather"}, {"page": "github", "seconds": 20}, {"page": "radar", "on": False}], open(playlist, "w"))
    assert pages(playlist) == ["weather", "github"], "a page switched off isn't offered"
    assert run(["touch", "120", "480"], cache, playlist) == "ok" and json.load(open(os.path.join(cache, "touch.json"))) == {"x": 120, "y": 480}
    status = lambda: json.loads(run(["status"], cache, playlist))
    assert status() == {"pages": ["weather", "github"], "showing": None, "pinned": None}
    open(os.path.join(cache, "showing"), "w").write("weather\n")
    assert run(["show", "github"], cache, playlist) == "ok" and status()["pinned"] == "github"
    assert status()["showing"] == "weather"
    run(["next"], cache, playlist)
    first = read(os.path.join(cache, "control.json"))
    assert first["page"] is None and first["skip"], "next unpins and skips"
    run(["show", "weather"], cache, playlist); run(["auto"], cache, playlist)
    assert read(os.path.join(cache, "control.json")) == dict(first, page=None), "auto keeps the last skip"
    for bad in (["show", "calendar"], ["show"], ["rm", "-rf"], []):
        try:
            run(bad, cache, playlist)
        except ValueError:
            continue
        raise AssertionError(f"{bad} should be refused")
    print("control: ok")


if __name__ == "__main__":
    try:
        print(run(os.environ.get("SSH_ORIGINAL_COMMAND", " ".join(sys.argv[1:])).split()))
    except ValueError as e:
        sys.exit(str(e))
