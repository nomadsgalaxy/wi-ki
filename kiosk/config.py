"""config: the setup page's settings for this kiosk, in ~/.config/kiosk/config.json. Updates never touch it.

  {"id": "k-7f3a2c",          the card's ID, picked when the card is made
   "setup": true,             whether the setup page runs; without it, it runs on any kiosk with a screen (one
                              that can show its first-boot login), and not on a render server
   "setup_by_ip": true}       its setup page can be reached by IP address, behind its login; false turns that off
                              (it can always be reached by IP before its first login is replaced)

Every key is optional. Anything else in the file is refused, so a typo can't be silently ignored. The kiosk's other
settings have files of their own beside it (playlist.json, transitions-off.json, remote.json), and the setup page
checks a playlist with validate_playlist() before it writes one.

  load(path)     -> the config, with defaults filled in; raises ValueError if the file is there but wrong
  save(cfg, path)   checks it, then writes it in one move, readable only by the kiosk user

  config.py --id    this kiosk's card ID, giving it one first if it hasn't got one (cards made before IDs existed)
"""
import json, os, re, secrets, sys

PATH = os.path.expanduser("~/.config/kiosk/config.json")
DEFAULTS = {"id": None, "setup": None, "setup_by_ip": True}
SCREEN = "/dev/fb0"   # a kiosk's own screen; a render server hasn't one
ENTRY = {"page", "seconds", "options", "on", "name"}


def validate(cfg):
    """raise ValueError saying what's wrong with cfg, or return it"""
    if not isinstance(cfg, dict):
        raise ValueError("config.json must be a JSON object")
    unknown = set(cfg) - set(DEFAULTS)
    if unknown:
        raise ValueError(f"unknown settings: {', '.join(sorted(unknown))}")
    if cfg.get("id") is not None and not (isinstance(cfg["id"], str) and re.fullmatch(r"k-[0-9a-f]{6}", cfg["id"])):
        raise ValueError("id must look like k-7f3a2c")
    for flag in ("setup", "setup_by_ip"):
        if flag in cfg and cfg[flag] is not None and not isinstance(cfg[flag], bool):
            raise ValueError(f"{flag} must be true or false")
    return cfg


def setup_on(cfg, screen=SCREEN):
    """whether the setup page runs: "setup" says so if it's there, and otherwise it's on wherever there's a screen"""
    return cfg.get("setup") is True or (cfg.get("setup") is None and os.path.exists(screen))


def validate_playlist(playlist):
    """raise ValueError saying what's wrong with a playlist.json, or return it. Errors name an entry by its number and
    never echo what's in it, because options can hold anything."""
    if not isinstance(playlist, list) or not playlist:
        raise ValueError("playlist must be a list with at least one page")
    for n, e in enumerate(playlist, 1):
        if not isinstance(e, dict) or not ENTRY >= set(e) or "page" not in e:
            raise ValueError(f"playlist entry {n}: entries are {{page, seconds, options, on, name}}")
        if not (isinstance(e["page"], str) and re.fullmatch(r"[a-z0-9_]+", e["page"])):
            raise ValueError(f"playlist entry {n}: the page has to be a page's name")   # it's imported as pages.<name>
        s = e.get("seconds", 1)
        if isinstance(s, bool) or not isinstance(s, (int, float)) or not 1 <= s <= 3600:
            raise ValueError(f"{e['page']}: seconds must be 1 to 3600")
        if not isinstance(e.get("options", {}), dict) or not isinstance(e.get("on", True), bool):
            raise ValueError(f"{e['page']}: options must be an object and on true or false")
        if not isinstance(e.get("name", ""), str):
            raise ValueError(f"{e['page']}: name must be text")
    return playlist


def load(path=PATH):
    try:
        raw = open(path).read()
    except FileNotFoundError:
        return dict(DEFAULTS)
    try:
        cfg = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"{path} isn't valid JSON: {e}") from None
    return {**DEFAULTS, **validate(cfg)}


def save(cfg, path=PATH):
    """write cfg (just the settings that differ from the defaults) in one move, so a power cut mid-write leaves the old
    file rather than half a new one"""
    validate(cfg)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({k: v for k, v in cfg.items() if v != DEFAULTS.get(k)}, f, indent=1)
        f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path)


def card_id(path=PATH):
    """the card's ID; one made before IDs existed gets one now, once, and keeps it"""
    cfg = load(path)
    if not cfg["id"]:
        cfg["id"] = "k-" + secrets.token_hex(3)
        save(cfg, path)
    return cfg["id"]


def check():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "kiosk", "config.json")
        assert load(path) == DEFAULTS, "no file: today's behaviour"
        screen = os.path.join(d, "fb0"); open(screen, "w").close()
        assert setup_on(DEFAULTS, screen) and not setup_on(DEFAULTS, os.path.join(d, "none")), "on where there's a screen"
        assert not setup_on({"setup": False}, screen) and setup_on({"setup": True}, os.path.join(d, "none"))
        assert not setup_on({"setup": "yes"}, screen), "only true or false say"
        cfg = {"id": "k-7f3a2c", "setup": True}
        save(cfg, path)
        assert load(path) == {**DEFAULTS, **cfg} and os.stat(path).st_mode & 0o777 == 0o600 and not os.path.exists(path + ".tmp")
        save({**DEFAULTS, "id": "k-000000"}, path)
        assert json.load(open(path)) == {"id": "k-000000"}, "only what differs from the defaults is written"
        for bad in ({"setup": "yes"}, {"setup_by_ip": 1}, {"id": "k-XYZ"}, {"id": "tennant"}, {"colour": 1},
                    {"playlist": [{"page": "weather"}]}, ["weather"]):
            try:
                save(bad, path)
            except ValueError:
                pass
            else:
                raise AssertionError(f"accepted {bad}")
        assert load(path) == {**DEFAULTS, "id": "k-000000"}, "a refused save leaves the file as it was"
        good = [{"page": "weather"}, {"page": "calendar", "seconds": 20, "on": False, "options": {"lat": 1.0}}]
        assert validate_playlist(good) == good
        for bad in ([], {}, [{"page": "../etc"}], [{"page": "weather", "seconds": 0}], [{"page": "weather", "seconds": True}],
                    [{"page": "weather", "wat": 1}], [{"page": "weather", "on": "no"}], [{"page": "weather", "options": []}], ["weather"]):
            try:
                validate_playlist(bad)
            except ValueError:
                pass
            else:
                raise AssertionError(f"accepted the playlist {bad}")
        assert card_id(path) == "k-000000", "an ID is kept"
        os.remove(path); first = card_id(path)
        assert re.fullmatch(r"k-[0-9a-f]{6}", first) and card_id(path) == first, "a card without one gets one, once"
        open(path, "w").write("{not json")
        try:
            load(path)
        except ValueError as e:
            assert "isn't valid JSON" in str(e)
        else:
            raise AssertionError("loaded broken JSON")
    print("config: ok")


if __name__ == "__main__":
    if sys.argv[1:] == ["--id"]:
        print(card_id())
    else:
        sys.exit(__doc__)
