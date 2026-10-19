"""form: which of a page's settings the setup page may change, and how, from the "form" in its catalog entry. One
place for the rules, used by the setup page (admin.py) to draw and check its settings panels, and by catalog.py to
check entries.

  "form": {"units":     {"type": "choice", "label": "Units", "of": [["", "the place's own"], ["f", "°F"], ["c", "°C"]]},
           "landscape": {"type": "choice", "from": "landscapes", "of": [["", "Philadelphia's skyline"]]},
           "title":     {"type": "text", "max": 24, "upper": true},
           "radius":    {"type": "number", "min": 5, "max": 250, "whole": true, "unit": "km"},
           "secondary": {"type": "bool", "label": "Show the other unit too"},
           "won":       {"type": "date"},
           "teams":     {"type": "picks", "max": 5, "of": [["nfl/21", "Philadelphia Eagles (NFL)"], ...]},
           "events":    {"type": "internal"}}

  choice    one of "of" ([value, label] pairs), plus, with "from", the names a kiosk has of that kind (landscapes)
  text      a line of text, at most "max" characters, capitals if "upper"
  number    between "min" and "max", a whole number if "whole"; "unit" is what's shown after it
  bool      a tick box
  date      a day, YYYY-MM-DD
  picks     some of "of" (at most "max"), as a list: a page that can follow several things
  internal  never on the form, and refused if a post names it: a path, a feed's address, a URL. Set over SSH.

An empty value (or the "" choice) means the page's own default: the option is taken out of the playlist entry. A
setting the form doesn't name is kept as it is, so a playlist set by hand keeps everything it says.
"""
import datetime, re

TYPES = {"choice", "text", "number", "bool", "date", "picks", "internal"}
FROM = {"landscapes"}   # the kinds of name a kiosk can list for a choice
CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class FieldError(ValueError):
    """what's wrong with one field, for showing beside it"""
    def __init__(self, field, message):
        super().__init__(message)
        self.field = field


def problems(spec, settings):
    """what's wrong with an entry's form, against its settings, as sentences: [] if nothing"""
    if not isinstance(spec, dict):
        return ["form is {setting: {type, ...}}"]
    out = []
    for name, f in spec.items():
        if name not in settings:
            out.append(f"form names {name}, which isn't one of its settings")
            continue
        if not isinstance(f, dict) or f.get("type") not in TYPES:
            out.append(f"form.{name}: type is one of {', '.join(sorted(TYPES))}")
            continue
        kind = f["type"]
        allowed = {"type", "label", "help"} | {"choice": {"of", "from"}, "text": {"max", "upper"},
                                               "number": {"min", "max", "whole", "unit"}, "picks": {"of", "max"}}.get(kind, set())
        if set(f) - allowed:
            out.append(f"form.{name}: a {kind} takes only {', '.join(sorted(allowed))}")
        for k in ("label", "help", "unit"):
            if k in f and not isinstance(f[k], str):
                out.append(f"form.{name}: {k} is text")
        if kind in ("choice", "picks"):
            of = f.get("of", [])
            if not (isinstance(of, list) and all(isinstance(o, list) and len(o) == 2 and all(isinstance(x, str) for x in o) for o in of)):
                out.append(f"form.{name}: of is a list of [value, label]")
            elif not of and "from" not in f or kind == "picks" and not of:
                out.append(f"form.{name}: a choice needs of or from")
            if "from" in f and f["from"] not in FROM:
                out.append(f"form.{name}: from is one of {', '.join(sorted(FROM))}")
        if kind == "picks" and not (isinstance(f.get("max"), int) and not isinstance(f["max"], bool) and f["max"] >= 1):
            out.append(f"form.{name}: a picks' max is 1 or more")
        if kind == "text" and not (isinstance(f.get("max"), int) and 1 <= f["max"] <= 64):
            out.append(f"form.{name}: a text's max is 1 to 64")
        if kind == "number":
            lo, hi = f.get("min"), f.get("max")
            if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (lo, hi)) or lo >= hi:
                out.append(f"form.{name}: a number has a min below its max")
    return out


def value(name, f, raw, choices=()):
    """one posted field -> (set it?, its value); FieldError if it isn't one this field takes"""
    kind, raw = f["type"], (raw if isinstance(raw, str) else "").strip()
    label = f.get("label", name)
    if kind == "internal":
        raise FieldError(name, f"{label} is set over SSH, not here.")
    if kind == "bool":
        return True, raw == "on"
    if kind == "picks":   # each one ticked, a line apiece (admin.py joins a field posted more than once)
        picks = list(dict.fromkeys(p for p in raw.split("\n") if p.strip()))
        if any(p not in [v for v, _ in f["of"]] for p in picks):
            raise FieldError(name, f"{label} isn't one of the choices.")
        if len(picks) > f["max"]:
            raise FieldError(name, f"{label} is at most {f['max']}.")
        return (True, picks) if picks else (False, None)
    if raw == "":
        return False, None   # back to the page's own default
    if CONTROL.search(raw):
        raise FieldError(name, f"{label} can't have control characters.")
    if kind == "choice":
        if raw not in [v for v, _ in f.get("of", [])] + list(choices):
            raise FieldError(name, f"{label} isn't one of the choices.")
        return True, raw
    if kind == "text":
        if len(raw) > f["max"]:
            raise FieldError(name, f"{label} is at most {f['max']} characters.")
        return True, raw.upper() if f.get("upper") else raw
    if kind == "number":
        try:
            n = float(raw)
        except ValueError:
            raise FieldError(name, f"{label} is a number.") from None
        if n != n or not f["min"] <= n <= f["max"]:   # n != n: not a number at all (nan)
            raise FieldError(name, f"{label} is {f['min']} to {f['max']}.")
        if f.get("whole"):
            if n != int(n):
                raise FieldError(name, f"{label} is a whole number.")
            return True, int(n)
        return True, round(n, 6)
    if kind == "date":
        try:
            return True, datetime.date.fromisoformat(raw).isoformat()
        except ValueError:
            raise FieldError(name, f"{label} is a day, like 1975-05-27.") from None
    raise FieldError(name, f"{label} can't be changed here.")


def apply(options, spec, posted, defaults, choices=lambda kind: ()):
    """a playlist entry's options after one save of its settings panel -> a new dict. Only fields on the form change;
    a value equal to the page's default is taken out, so the entry stays as short as it was. posted names an internal
    setting: FieldError"""
    out = dict(options)
    for name in posted:
        if name in spec and spec[name]["type"] == "internal":
            raise FieldError(name, f"{spec[name].get('label', name)} is set over SSH, not here.")
    for name, f in spec.items():
        if f["type"] == "internal":
            continue
        keep, v = value(name, f, posted.get(name, ""), choices(f["from"]) if "from" in f else ())
        if not keep or v == defaults.get(name):
            out.pop(name, None)
        else:
            out[name] = v
    return out


def check():
    spec = {"units": {"type": "choice", "label": "Units", "of": [["", "own"], ["f", "°F"], ["c", "°C"]]},
            "landscape": {"type": "choice", "from": "landscapes", "of": [["", "skyline"]]},
            "title": {"type": "text", "max": 8, "upper": True}, "radius": {"type": "number", "min": 5, "max": 250, "whole": True},
            "secondary": {"type": "bool"}, "won": {"type": "date"}, "events": {"type": "internal"},
            "teams": {"type": "picks", "max": 2, "of": [["nfl/21", "Eagles"], ["mlb/22", "Phillies"], ["nhl/15", "Flyers"]]}}
    settings = {"units": None, "landscape": None, "title": None, "radius": 25, "secondary": False, "won": None, "events": "~/x",
                "teams": ["nfl/21"]}
    assert problems(spec, settings) == [], problems(spec, settings)
    for bad, says in (({"colour": {"type": "text", "max": 4}}, "isn't one of its settings"), ({"units": {"type": "wheel"}}, "type is"),
                      ({"units": {"type": "choice"}}, "needs of or from"), ({"title": {"type": "text", "max": 999}}, "max is 1 to 64"),
                      ({"radius": {"type": "number", "min": 9, "max": 1}}, "min below"), ({"title": {"type": "text", "max": 4, "min": 1}}, "takes only"),
                      ({"units": {"type": "choice", "of": [["f"]]}}, "[value, label]"), ({"landscape": {"type": "choice", "from": "files"}}, "from is"),
                      ({"teams": {"type": "picks", "of": [["a", "A"]]}}, "max is 1"), ({"teams": {"type": "picks", "max": 1, "from": "landscapes"}}, "takes only")):
        assert any(says in p for p in problems(bad, settings)), (bad, problems(bad, settings))
    defaults = settings
    lands = lambda kind: ["lake"] if kind == "landscapes" else []
    got = apply({"lat": 1.5, "events": "/keep/me"}, spec, {"units": "f", "landscape": "lake", "title": "mullica", "radius": "40",
                                                          "secondary": "on", "won": "1975-05-27", "teams": "nhl/15\nmlb/22\nnhl/15"}, defaults, lands)
    assert got == {"lat": 1.5, "events": "/keep/me", "units": "f", "landscape": "lake", "title": "MULLICA", "radius": 40,
                   "secondary": True, "won": "1975-05-27", "teams": ["nhl/15", "mlb/22"]}, got
    assert apply(got, spec, {"radius": "25", "teams": "nfl/21"}, defaults, lands) == {"lat": 1.5, "events": "/keep/me"}, \
        "empty fields and defaults come out; what the form doesn't name stays"
    for posted, field in (({"units": "k"}, "units"), ({"landscape": "../etc"}, "landscape"), ({"title": "much-too-long"}, "title"),
                          ({"title": "a\nb"}, "title"), ({"radius": "4"}, "radius"), ({"radius": "nan"}, "radius"), ({"radius": "4.5"}, "radius"),
                          ({"radius": "x"}, "radius"), ({"won": "yesterday"}, "won"), ({"events": "/etc/shadow"}, "events"),
                          ({"teams": "nfl/21\nmlb/22\nnhl/15"}, "teams"), ({"teams": "nfl/99"}, "teams")):
        try:
            apply({}, spec, posted, defaults, lands)
        except FieldError as e:
            assert e.field == field and str(e), (posted, e.field)
        else:
            raise AssertionError(f"took {posted}")
    print("form: ok")
