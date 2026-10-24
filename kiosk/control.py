#!/usr/bin/env python3
"""control: lets my desktop pick what the kiosk shows. It's the forced command of the desktop's control key on the Pi
(see feed/README.md), so the key can do this and nothing else. The command comes in SSH_ORIGINAL_COMMAND:

  status          {"pages": [...], "showing": "<page>", "pinned": "<page>" or null}, as JSON
  show <page>     jump to that page and stay there
  auto            back to the normal rotation
  next            on to the next page, and back to the rotation
  touch <x> <y>   a touch on the screen at x, y (for trying a touchable page without a touch screen)
  touch <gesture> menu, next or prev: a two-finger double tap, a swipe left, a swipe right
  thumbs          {"<page>": "<a small JPEG of it, base64>"}, for the pages it's drawn lately (the desktop widget's
                  pictures; kiosk.py keeps them in ~/.cache/kiosk/thumbs/)
  transitions     {"all": [...], "off": [...]}: the transitions installed, and the ones turned off
  transition <name> on|off   turn one on or off (not the last one on), and restart the display, as the setup page does

It writes ~/.cache/kiosk/control.json, which kiosk.py watches: {"page": <pinned page or null>, "skip": <changes on
every next>}. kiosk.py writes the page it's showing to ~/.cache/kiosk/showing. This deliberately imports nothing
heavy: on a Pi Zero, loading Pillow alone takes a couple of seconds.
"""
import base64, json, os, re, subprocess, sys, time

HERE = os.path.dirname(os.path.realpath(__file__))
CACHE = os.path.expanduser("~/.cache/kiosk")
LOCAL_PLAYLIST = os.path.expanduser("~/.config/kiosk/playlist.json")   # this kiosk's own, as in kiosk.py
PLAYLIST = LOCAL_PLAYLIST if os.path.exists(LOCAL_PLAYLIST) else os.path.join(HERE, "playlist.json")
OFF = os.path.expanduser("~/.config/kiosk/transitions-off.json")   # as in transitions/__init__.py
# where transitions are installed, as transitions/__init__.py finds them (without importing it: that loads them all)
THEMES = [os.path.join(HERE, "transitions"), os.path.join(HERE, "..", "catalog", "transitions"),
          os.path.expanduser("~/.local/share/kiosk/transitions")]


def themes(dirs=THEMES):
    return sorted({f[:-3] for d in dirs if os.path.isdir(d) for f in os.listdir(d)
                   if f.endswith(".py") and f not in ("__init__.py", "canvas.py")})


def restart():
    """the display picks up new settings when it starts, as the setup page does it (admin.restart())"""
    subprocess.run(["pkill", "-f", f"(^|/)python3 -I {HERE}/kiosk.py"], capture_output=True, timeout=10)


def pages(playlist=PLAYLIST):
    return [e.get("name", e["page"]) for e in json.load(open(playlist)) if e.get("on") is not False]


def read(path):
    try:
        return json.load(open(path))
    except (OSError, ValueError):
        return {}


def run(args, cache=CACHE, playlist=PLAYLIST, off=OFF, dirs=THEMES, restart=restart):
    """one command -> what to print. Raises ValueError for one it doesn't know."""
    control, names = os.path.join(cache, "control.json"), pages(playlist)
    state = read(control)
    if args == ["thumbs"]:
        out, folder = {}, os.path.join(cache, "thumbs")
        for name in names:
            path = os.path.join(folder, f"{name}.jpg")
            if re.fullmatch(r"[A-Za-z0-9_-]+", name) and os.path.exists(path):
                out[name] = base64.b64encode(open(path, "rb").read()).decode()
        return json.dumps(out)
    if args == ["transitions"] or args[:1] == ["transition"]:
        installed, skipped = themes(dirs), read(off)
        skipped = [n for n in skipped if n in installed] if isinstance(skipped, list) else []
        if args == ["transitions"]:
            return json.dumps({"all": installed, "off": skipped})
        if len(args) != 3 or args[1] not in installed or args[2] not in ("on", "off"):
            raise ValueError(f"usage: transition <{'|'.join(installed)}> on|off")
        skipped = [n for n in skipped if n != args[1]] + ([args[1]] if args[2] == "off" else [])
        if len(skipped) >= len(installed):
            raise ValueError("leave at least one transition on")
        os.makedirs(os.path.dirname(off), exist_ok=True)
        json.dump(skipped, open(off + ".tmp", "w")); os.replace(off + ".tmp", off)
        restart()
        return "ok"
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
    elif args[:1] == ["touch"] and (len(args) == 3 and all(a.isdigit() for a in args[1:]) or args[1:] in (["menu"], ["next"], ["prev"])):
        os.makedirs(cache, exist_ok=True)
        touch = os.path.join(cache, "touch.json")
        at = {"x": int(args[1]), "y": int(args[2])} if len(args) == 3 else {"gesture": args[1]}
        json.dump(at, open(touch + ".tmp", "w")); os.replace(touch + ".tmp", touch)
        return "ok"
    else:
        raise ValueError(f"usage: status | show <{'|'.join(names)}> | auto | next | touch <x> <y> | touch menu|next|prev"
                         " | thumbs | transitions | transition <name> on|off")
    os.makedirs(cache, exist_ok=True)
    json.dump(state, open(control + ".tmp", "w")); os.replace(control + ".tmp", control)
    return "ok"


def check():
    import tempfile
    cache, playlist = tempfile.mkdtemp(), os.path.join(tempfile.mkdtemp(), "playlist.json")
    json.dump([{"page": "weather"}, {"page": "github", "seconds": 20}, {"page": "radar", "on": False}], open(playlist, "w"))
    assert pages(playlist) == ["weather", "github"], "a page switched off isn't offered"
    assert run(["touch", "120", "480"], cache, playlist) == "ok" and json.load(open(os.path.join(cache, "touch.json"))) == {"x": 120, "y": 480}
    assert run(["touch", "prev"], cache, playlist) == "ok" and json.load(open(os.path.join(cache, "touch.json"))) == {"gesture": "prev"}
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
    # the widget's pictures: only the playlist's pages, and only plain names
    os.makedirs(os.path.join(cache, "thumbs"))
    for name in ("weather", "radar"):
        open(os.path.join(cache, "thumbs", f"{name}.jpg"), "wb").write(b"\xff\xd8" + name.encode())
    assert json.loads(run(["thumbs"], cache, playlist)) == {"weather": base64.b64encode(b"\xff\xd8weather").decode()}
    # transitions: listed, turned off and on again, never all off, and each change restarts the display
    themes_dir, off, restarts = tempfile.mkdtemp(), os.path.join(tempfile.mkdtemp(), "off.json"), []
    for name in ("matrix", "tetris", "canvas", "__init__"):
        open(os.path.join(themes_dir, f"{name}.py"), "w").close()
    t = lambda *a: run(list(a), cache, playlist, off, [themes_dir], lambda: restarts.append(1))
    assert json.loads(t("transitions")) == {"all": ["matrix", "tetris"], "off": []}
    assert t("transition", "tetris", "off") == "ok" and json.loads(t("transitions"))["off"] == ["tetris"] and restarts == [1]
    for bad in (("transition", "matrix", "off"), ("transition", "nope", "off"), ("transition", "matrix", "maybe")):
        try:
            t(*bad); raise AssertionError(f"{bad} should be refused")
        except ValueError:
            pass
    assert t("transition", "tetris", "on") == "ok" and json.loads(t("transitions"))["off"] == [] and len(restarts) == 2
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
