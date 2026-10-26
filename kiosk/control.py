#!/usr/bin/env python3
"""control: lets my desktop pick what the kiosk shows. It's the forced command of the desktop's control key on the Pi
(see feed/README.md), so the key can do this and nothing else. The command comes in SSH_ORIGINAL_COMMAND:

  status          {"pages": [...], "showing": "<page>", "pinned": "<page>" or null, "commit": <applied>, "latest":
                  <on GitHub when it last looked>, "behind": <commits>}, as JSON; on a kiosk drawn by a render server,
                  the server's pages, and "server": the server's own commit, latest and behind
  update          update now (kiosk-update.path starts the autoupdate, smoke test and all); on a kiosk drawn by a
                  render server, the server too
  show <page>     jump to that page and stay there
  auto            back to the normal rotation
  next            on to the next page, and back to the rotation
  touch <x> <y>   a touch on the screen at x, y (for trying a touchable page without a touch screen)
  touch <gesture> menu, next or prev: a two-finger double tap, a swipe left, a swipe right
  thumbs          {"<page>": "<a small JPEG of it, base64>"}, for the pages it's drawn lately (the desktop widget's
                  pictures; kiosk.py keeps them in ~/.cache/kiosk/thumbs/)
  transitions     {"all": [...], "off": [...]}: the transitions installed, and the ones turned off
  transition <name> on|off   turn one on or off (not the last one on), and restart the display, as the setup page does

A kiosk whose pages a render server draws (remote.json with a server and the key) passes every command on to the
server over link.py, so one key on the Pi controls both; if the server can't be reached, the Pi is drawing its own
pages, so it answers itself.

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
# autoupdate's, as the kiosk user's: the same place on a Pi and on a render server, whatever HOME an instance has
STATE = os.path.realpath(os.path.join(HERE, "..", ".cache", "kiosk"))
REPO = os.path.realpath(os.path.join(HERE, "..", "wi-ki"))
REMOTE = os.path.expanduser("~/.config/kiosk/remote.json")
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


def version(state=STATE, repo=REPO):
    """the commit autoupdate applied, the latest it's fetched from GitHub, and how many commits that is ahead"""
    def text(*cmd):
        try:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=20).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return ""
    try:
        applied = open(os.path.join(state, "applied-commit")).read().strip()
    except OSError:
        applied = ""
    latest = text("git", "-C", repo, "rev-parse", "origin/main")
    behind = text("git", "-C", repo, "rev-list", "--count", f"{applied}..{latest}") if applied and latest else ""
    return {"commit": applied[:7] or None, "latest": latest[:7] or None, "behind": int(behind) if behind.isdigit() else None}


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
    if args == ["update"]:
        os.makedirs(STATE, exist_ok=True)
        with open(os.path.join(STATE, "update-request"), "w") as f:   # kiosk-update.path watches it
            f.write(f"{time.time():.0f}\n")
        return "ok"
    if args == ["status"]:
        try:
            showing = open(os.path.join(cache, "showing")).read().strip()
        except OSError:
            showing = None
        pinned = state.get("page") if state.get("page") in names else None
        return json.dumps({"pages": names, "showing": showing, "pinned": pinned, **version()})
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
        raise ValueError(f"usage: status | update | show <{'|'.join(names)}> | auto | next | touch <x> <y> | touch menu|next|prev"
                         " | thumbs | transitions | transition <name> on|off")
    os.makedirs(cache, exist_ok=True)
    json.dump(state, open(control + ".tmp", "w")); os.replace(control + ".tmp", control)
    return "ok"


def dispatch(args, remote=REMOTE, here=run, there=None):
    """run a command here, or on the render server that draws this kiosk's pages; update and status take in both"""
    try:
        server = json.load(open(remote))
    except (OSError, ValueError):
        server = {}
    k = None
    if isinstance(server, dict) and server.get("server"):
        sys.path.insert(0, HERE)
        import link   # only now: it's a few imports more, and most kiosks draw their own pages
        k = link.key(remote)
        there = there or (lambda a: link.request((server["server"], int(server.get("port", 7676))), k, {"op": "control", "args": a})["out"])
    if not k:
        return here(args)
    try:
        out = there(args)
    except OSError:   # no server: the Pi is drawing its own pages, so it answers for itself
        return here(args)
    if args == ["update"]:
        return here(args)
    if args == ["status"]:
        theirs, mine = json.loads(out), json.loads(here(args))
        return json.dumps({**theirs, **{k: mine[k] for k in ("commit", "latest", "behind")},
                           "server": {k: theirs.get(k) for k in ("commit", "latest", "behind")}})
    return out


def check():
    import tempfile
    cache, playlist = tempfile.mkdtemp(), os.path.join(tempfile.mkdtemp(), "playlist.json")
    json.dump([{"page": "weather"}, {"page": "github", "seconds": 20}, {"page": "radar", "on": False}], open(playlist, "w"))
    assert pages(playlist) == ["weather", "github"], "a page switched off isn't offered"
    assert run(["touch", "120", "480"], cache, playlist) == "ok" and json.load(open(os.path.join(cache, "touch.json"))) == {"x": 120, "y": 480}
    assert run(["touch", "prev"], cache, playlist) == "ok" and json.load(open(os.path.join(cache, "touch.json"))) == {"gesture": "prev"}
    status = lambda: json.loads(run(["status"], cache, playlist))
    assert {k: v for k, v in status().items() if k in ("pages", "showing", "pinned")} == {"pages": ["weather", "github"], "showing": None, "pinned": None}
    assert {"commit", "latest", "behind"} <= set(status())
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
    # the version: what autoupdate applied, and how far GitHub's main is ahead of it
    repo, state = tempfile.mkdtemp(), tempfile.mkdtemp()
    g = lambda *a: subprocess.run(["git", "-C", repo, "-c", "user.name=t", "-c", "user.email=t@t", *a], check=True, capture_output=True, text=True).stdout.strip()
    g("init", "-q", "-b", "main"); g("commit", "-q", "--allow-empty", "-m", "a")
    first = g("rev-parse", "HEAD"); g("commit", "-q", "--allow-empty", "-m", "b"); g("commit", "-q", "--allow-empty", "-m", "c")
    g("update-ref", "refs/remotes/origin/main", "HEAD")
    open(os.path.join(state, "applied-commit"), "w").write(first + "\n")
    assert version(state, repo) == {"commit": first[:7], "latest": g("rev-parse", "HEAD")[:7], "behind": 2}
    assert version(tempfile.mkdtemp(), repo)["behind"] is None, "nothing applied yet: it can't say"
    # on a kiosk drawn by a render server: commands go there, update and status take in both, and no server means here
    remote = os.path.join(tempfile.mkdtemp(), "remote.json")
    json.dump({"server": "10.0.0.9", "port": 7677, "key": "ab" * 32}, open(remote, "w"))
    sent, mine = [], lambda a: json.dumps({"pages": ["pi"], "commit": "aaaaaaa", "latest": "bbbbbbb", "behind": 1}) if a == ["status"] else "here"
    srv = lambda a: sent.append(a) or (json.dumps({"pages": ["weather"], "showing": "weather", "commit": "ccccccc", "latest": "ccccccc", "behind": 0}) if a == ["status"] else "ok")
    assert dispatch(["next"], remote, mine, srv) == "ok" and sent == [["next"]]
    assert json.loads(dispatch(["status"], remote, mine, srv)) == {"pages": ["weather"], "showing": "weather", "commit": "aaaaaaa", "latest": "bbbbbbb",
                                                                  "behind": 1, "server": {"commit": "ccccccc", "latest": "ccccccc", "behind": 0}}
    assert dispatch(["update"], remote, mine, srv) == "here" and sent[-1] == ["update"], "update: the server, then here"
    def down(a):
        raise OSError("no route")
    assert dispatch(["next"], remote, mine, down) == "here", "no server: the Pi answers"
    assert dispatch(["next"], os.path.join(state, "none.json"), mine, srv) == "here", "no render server: here"
    json.dump({"server": "10.0.0.9"}, open(remote, "w"))
    assert dispatch(["next"], remote, mine, srv) == "here", "a server but no key: it can't ask, so here"
    print("control: ok")


if __name__ == "__main__":
    try:
        print(dispatch(os.environ.get("SSH_ORIGINAL_COMMAND", " ".join(sys.argv[1:])).split()))
    except ValueError as e:
        sys.exit(str(e))
