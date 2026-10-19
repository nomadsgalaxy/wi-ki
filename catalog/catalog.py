#!/usr/bin/env python3
"""catalog: every page and transition the kiosks have, one file each in this folder (<name>.json), and where each
version of it lives today. Each file is the pack.json that pack will carry once it's carved out, plus "found": the git
tree (or blob, for a transition) of each version, by the line it's on.

  {"name": "radar", "kind": "page", "home": "public", "about": "what's flying overhead, on a live map",
   "found": {"main": "feb2da"},
   "shapes": ["bar", "16-9", "9-16"],
   "needs": {"render": "any", "touch": false, "services": ["api.adsb.lol", ...], "secrets": []},
   "settings": {"lat": null, "lon": null, "radius": 25}, "ask": [],
   "licence": {"code": "MIT", "assets": "OpenStreetMap data, ODbL, credited on screen",
               "notes": "..."},
   "quality": {"zero": "unchecked", "shapes": "unchecked", "flicker": "unchecked", "licence": "unchecked",
               "offline": "unchecked"}}

  home      public (the open catalog), private (ours only), hive (Hive76's repo), core (part of the runtime, not a pack)
  render    any: a Zero can draw it; server: its data only reaches the render server (a desktop feed)
  services  every host its code talks to; secrets  what it has to be given, by reference, never in its settings
  ask       what installing it asks the owner for, from its settings and secrets: anything it needs a fresh API token
            for, or a server of some kind (a feed's address, a Home Assistant), and nothing else. septa's sfw is the
            one exception. A location has a working default, so it isn't asked.
  form      optional: which settings the setup page may change, and how (kiosk/form.py has the rules)
  quality   the bar to clear: runs on a Zero, readable at its shapes, no flicker, licence clear, fails quietly.
            Each is unchecked, pass or fail. Having a check() is the sixth, and --check enforces that one itself.

  catalog.py --check          refuses a file with a missing or unknown field, then holds each one against the code on
                              every line: the versions match, every host the code contacts is in services (and no more),
                              settings are Page's options, every version has a check(), and nothing public mentions
                              secret refs (op://), Prusa or a private address. Every page and transition on any line
                              needs a file.
  catalog.py --table          writes CATALOG.md from the files
  catalog.py --draft KIND N   prints a starting file for page or transition N, read from the code
  catalog.py --new KIND N     starts page or transition N from catalog/new/ (docs/make.md), with its file here
  catalog.py --test           the self-test, on a made-up repo

It reads origin/main, the remote-tracking branch, so fetch first.
"""
import ast, glob, json, os, re, subprocess, sys, tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "kiosk"))
import form  # noqa: E402  the rules for "form", shared with the setup page
from packs import NAME  # noqa: E402  what a pack can be called

HERE = os.path.dirname(os.path.realpath(__file__))
REPO = os.path.dirname(HERE)
ENTRIES = os.path.join(HERE, "entries")
LINES = {"main": (REPO, "origin/main")}
FIELDS = {"name", "kind", "home", "about", "found", "shapes", "needs", "settings", "ask", "licence", "quality"}
OPTIONAL = {"form"}
CHOICES = {"kind": {"page", "transition"}, "home": {"public", "private", "hive", "core"}}
NEEDS = {"render": {"any", "server"}, "touch": {True, False}}
SHAPES_ORDER = ("bar", "16-9", "9-16")   # kit.SHAPES
SHAPES = set(SHAPES_ORDER)
QUALITY = {"zero", "shapes", "flicker", "licence", "offline"}
MARKS = {"unchecked", "pass", "fail"}
NOT_PUBLIC = re.compile(r"op://|prusa|\b[a-z0-9-]+\.local\b|\b10\.\d+\.\d+\.\d+|\b192\.168\.\d", re.I)
HOST = re.compile(r"https?://([a-z0-9.-]+)|\b([a-z0-9-]+\.local)\b", re.I)
ENGINE = {"__init__", "canvas"}   # the transitions' player and drawing, part of the core
FRAMES = re.compile(r"^(def frames\(|frames = simple\()", re.M)
FIXTURES = {"data", "planes"}   # what a page's own check() hands it so it never fetches; never set in a playlist


def git(repo, *args):
    r = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def where(kind, name):
    return f"catalog/pages/{name}" if kind == "page" else f"catalog/transitions/{name}.py"


def version(repo, ref, kind, name):
    """(its tree or blob hash, {file: source}) on that line, or (None, {}) if it isn't there"""
    path = where(kind, name)
    obj = git(repo, "rev-parse", "--verify", "-q", f"{ref}:{path}")
    if not obj:
        return None, {}
    files = (git(repo, "ls-tree", "-r", "--name-only", ref, "--", path) or "").split() if kind == "page" else [path]
    return obj.strip(), {f: git(repo, "show", f"{ref}:{f}") or "" for f in files if f.endswith(".py")}


def options(src):
    """Page's options, with their defaults where they're plain values: {name: default}"""
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.ClassDef) and node.name == "Page":
            for f in node.body:
                if isinstance(f, ast.FunctionDef) and f.name == "__init__":
                    a = f.args
                    args = (a.posonlyargs + a.args)[1:] + a.kwonlyargs
                    defaults = [None] * (len(a.posonlyargs + a.args) - 1 - len(a.defaults)) + a.defaults + a.kw_defaults
                    out = {}
                    for arg, d in zip(args, defaults):
                        try:
                            out[arg.arg] = ast.literal_eval(d) if d is not None else None
                        except ValueError:
                            out[arg.arg] = None   # worked out at run time
                    return {k: v for k, v in out.items() if k not in FIXTURES}
    return {}


def shapes(src):
    """the shapes Page says it can be drawn in (Page.shapes); just the bar if it doesn't say"""
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.ClassDef) and node.name == "Page":
            for a in node.body:
                if isinstance(a, ast.Assign):
                    names = a.targets[0].elts if isinstance(a.targets[0], ast.Tuple) else [a.targets[0]]
                    values = a.value.elts if isinstance(a.targets[0], ast.Tuple) else [a.value]
                    for n, v in zip(names, values):
                        if isinstance(n, ast.Name) and n.id == "shapes":
                            return set(ast.literal_eval(v))
    return {"bar"}


def scanned(src):
    """the part of a file its hosts are read from: not comments (a credit's link isn't a call) or check() (the hosts a
    self-test refuses aren't ones it calls), plus the hosts in any *_HOSTS allow-list, which it fetches from"""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return src
    skip, allowed = set(), []
    for n in tree.body:
        if isinstance(n, ast.FunctionDef) and n.name == "check":
            skip |= set(range(n.lineno, n.end_lineno + 1))
        elif isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id.endswith("HOSTS") for t in n.targets):
            allowed += [f"https://{v.value}" for v in ast.walk(n.value)
                        if isinstance(v, ast.Constant) and isinstance(v.value, str)]
    lines = [l for i, l in enumerate(src.splitlines(), 1) if i not in skip and not l.lstrip().startswith("#")]
    return "\n".join(lines + allowed)


def facts(repo, ref, kind, name):
    """what the code on one line says: (hash, hosts it contacts, its options, whether it has a check(), its source,
    its shapes)"""
    obj, files = version(repo, ref, kind, name)
    if not obj:
        return None
    text = "\n".join(files.values())
    code = "\n".join(scanned(src) for src in files.values())
    hosts = {(m.group(1) or m.group(2)).lower() for m in HOST.finditer(code)}
    if kind == "page":
        page = files.get(f"catalog/pages/{name}/page.py", "")
        return obj, hosts, options(page) if page else {}, "def check(" in text, text, shapes(page) if page else {"bar"}
    # the player's check() plays every theme it finds, so a transition with frames() (or simple()'s) is checked
    return obj, hosts, {}, bool(FRAMES.search(text)), text, {"bar"}   # canvas.py draws the bar


def problems(entry, lines):
    """everything wrong with one catalog entry, against the code on lines ({line: (repo, ref)}), as sentences"""
    name = entry.get("name", "?")
    out = []
    if not FIELDS <= set(entry) <= FIELDS | OPTIONAL:
        return [f"{name}: fields must be exactly {', '.join(sorted(FIELDS))}, and optionally {', '.join(sorted(OPTIONAL))}"]
    if "form" in entry:
        out += [f"{name}: {p}" for p in form.problems(entry["form"], entry.get("settings") or {})]
    for field, allowed in CHOICES.items():
        if entry[field] not in allowed:
            out.append(f"{name}: {field} must be one of {', '.join(sorted(allowed))}")
    needs = entry["needs"]
    if not isinstance(needs, dict) or set(needs) != {*NEEDS, "services", "secrets"}:
        return out + [f"{name}: needs is {{render, touch, services, secrets}}"]
    out += [f"{name}: needs.{k} can't be {needs[k]!r}" for k, allowed in NEEDS.items() if needs[k] not in allowed]
    if not set(entry["shapes"]) <= SHAPES or not entry["shapes"]:
        out.append(f"{name}: shapes are some of {', '.join(sorted(SHAPES))}")
    if set(entry["quality"]) != QUALITY or not set(entry["quality"].values()) <= MARKS:
        out.append(f"{name}: quality is {', '.join(sorted(QUALITY))}, each {', '.join(sorted(MARKS))}")
    if not isinstance(entry["licence"], dict) or set(entry["licence"]) != {"code", "assets", "notes"}:
        out.append(f"{name}: licence is {{code, assets, notes}}")
    if not isinstance(entry["ask"], list) or not set(entry["ask"]) <= {*entry["settings"], *entry["needs"]["secrets"]}:
        out.append(f"{name}: ask names its own settings and secrets")
    if not isinstance(entry["about"], str) or not entry["about"]:
        out.append(f"{name}: about says what it is in a line")
    if out or entry["kind"] not in CHOICES["kind"]:
        return out

    unknown = set(entry["found"]) - set(LINES) - set(lines)
    if unknown:
        out.append(f"{name}: found names lines nobody knows: {', '.join(sorted(unknown))}")
    hosts, settings, drawn, seen = set(), {}, set(), 0
    for line, (repo, ref) in lines.items():
        got, said = facts(repo, ref, entry["kind"], name), entry["found"].get(line)
        if not got:
            if said:
                out.append(f"{name}: isn't on {line}, but the catalog says {said}")
            continue
        obj, h, opts, checked, text, can = got
        seen += 1
        if not said or not obj.startswith(said):
            out.append(f"{name}: {line} has {obj[:6]}, the catalog says {said or 'nothing'}")
        if not checked:
            out.append(f"{name}: {line}'s version has no check()")
        if entry["home"] == "public":
            bad = sorted({m.group(0).lower() for m in NOT_PUBLIC.finditer(text)})
            if bad:
                out.append(f"{name}: it's public, but {line}'s version mentions {', '.join(bad)}")
        hosts |= h
        settings.update(opts)
        drawn |= can
    if not seen:
        return out + [f"{name}: isn't on any line"]
    listed = set(needs["services"])
    if hosts - listed:
        out.append(f"{name}: services is missing {', '.join(sorted(hosts - listed))}")
    if listed - hosts:
        out.append(f"{name}: services lists {', '.join(sorted(listed - hosts))}, which no version contacts")
    if set(entry["shapes"]) != drawn:
        out.append(f"{name}: shapes are {', '.join(sorted(drawn))}, the ones Page says it can be drawn in")
    if set(entry["settings"]) != set(settings):
        out.append(f"{name}: settings are {', '.join(sorted(settings)) or 'none'}, the options its code takes")
    return out


def everything(lines):
    """every (kind, name) on any of lines"""
    out = set()
    for repo, ref in lines.values():
        for kind, path in (("page", "catalog/pages"), ("transition", "catalog/transitions")):
            for f in (git(repo, "ls-tree", "--name-only", f"{ref}:{path}") or "").split():
                if kind == "page" and git(repo, "cat-file", "-t", f"{ref}:{path}/{f}") == "tree\n":
                    out.add((kind, f))
                elif kind == "transition" and f.endswith(".py") and f[:-3] not in ENGINE:
                    out.add((kind, f[:-3]))
    return out


def load(folder=ENTRIES):
    return {os.path.basename(p)[:-5]: json.load(open(p)) for p in sorted(glob.glob(os.path.join(folder, "*.json")))}


def check(folder=ENTRIES, lines=None):
    if lines is None:
        lines = {k: v for k, v in LINES.items() if os.path.isdir(v[0])}
        for k in sorted(set(LINES) - set(lines)):
            print(f"catalog: skipped {k}: no checkout at {LINES[k][0]}")
    entries, out = load(folder), []
    for file, e in entries.items():
        if e.get("name") != file:
            out.append(f"{file}.json: its name has to be {file}")
        out += problems(e, lines)
    named = {(e.get("kind"), e.get("name")) for e in entries.values()}
    out += [f"{name}: a {kind} with no catalog file" for kind, name in sorted(everything(lines) - named)]
    return out


def draft(kind, name, lines=LINES):
    found, hosts, settings, drawn = {}, set(), {}, set()
    for line, (repo, ref) in lines.items():
        got = os.path.isdir(repo) and facts(repo, ref, kind, name)
        if got:
            found[line] = got[0][:6]; hosts |= got[1]; settings.update(got[2]); drawn |= got[5]
    return {"name": name, "kind": kind, "home": "private", "about": "", "found": found, "shapes": sorted(drawn, key=list(SHAPES_ORDER).index),
            "needs": {"render": "any", "touch": False, "services": sorted(hosts), "secrets": []},
            "settings": settings, "ask": [], "licence": {"code": None, "assets": None, "notes": None},
            "quality": {q: "unchecked" for q in sorted(QUALITY)}}


def new(kind, name, root=REPO, folder=ENTRIES):
    """start page or transition name from its template in catalog/new/, with a catalog file -> the files it wrote"""
    if not NAME.fullmatch(name):
        raise ValueError(f"{name!r}: a name is 2 to 31 lowercase letters, digits and _, starting with a letter")
    code = os.path.join(root, "catalog", "pages", name, "page.py") if kind == "page" else \
        os.path.join(root, "catalog", "transitions", name + ".py")
    entry = os.path.join(folder, name + ".json")
    if os.path.exists(os.path.dirname(code) if kind == "page" else code) or os.path.exists(entry) or name in ENGINE:
        raise ValueError(f"{name}: there's already one called that")
    os.makedirs(os.path.dirname(code), exist_ok=True)
    open(code, "w").write(open(os.path.join(HERE, "new", kind + ".py")).read().replace("{name}", name))
    written = [code]
    if kind == "page":
        written.append(os.path.join(os.path.dirname(code), "__init__.py"))
        open(written[-1], "w").write("from .page import Page, check, preview   # noqa: F401\n")
    blank = draft(kind, name, {})   # it's on no line yet, so this is a blank file; --check says what it still needs
    blank["shapes"] = ["bar"]   # what the templates draw
    if kind == "page":
        blank["settings"] = options(open(code).read())
    json.dump(blank, open(entry, "w"), indent=1); open(entry, "a").write("\n")
    return written + [entry]


def table(folder=ENTRIES):
    entries = load(folder)
    rows = ["# The kiosks' catalog", "",
            "Written by `catalog/catalog.py --table` from the files beside it; edit those, not this. Same hash, same code.",
            "", "Installing a pack asks for anything it needs a fresh API token or a server for, and nothing else, plus "
            "septa's sfw. Locations and titles have working defaults, so they aren't asked.", "",
            "**Licences.** Pages and transitions are MIT (`LICENSE-MIT`): everything in `catalog/pages/`, and the theme files "
            "in `catalog/transitions/`. A page's code stays MIT while it runs inside the engine. The engine is everything "
            "else (`kit.py`, `kiosk.py`, the transitions' `__init__.py` and "
            "`canvas.py`, the setup server, updates, feeds and tools), under the Open Community Licence with the Software "
            "Attribution add-on, `OCL v1.1 + SWAtt v1` (`LICENSE`, `LICENSE-SWAtt-v1.md`). The engine isn't open "
            "source in the OSI sense. SWAtt means anyone distributing a derivative has to show who built it in its UI and "
            "in its source (for a kiosk, on the screen), and it forbids systematic or automated text and data mining "
            "without permission. The attribution is \"Built By NomadsGalaxy\", linking to nomadsgalaxy.com, in "
            "`kit.py`'s header. Packs run inside the engine, so they don't carry it. "
            "Assets keep their own licences, listed per entry.", "",
            "**Fonts.** The VGA font every page uses, `Uni2-VGA16.psf.gz`, comes from Debian's `console-setup`: Dmitry "
            "Bolkhovityanov's u_vga16 under an MIT/X11-style licence, plus legacy console glyphs that console-setup "
            "lists as public domain. Its notice is in `kiosk/fonts/LICENSE`. Any new font comes from Google Fonts.",
            "", "| name | kind | home | what it is | versions | needs | quality |", "|---|---|---|---|---|---|---|"]
    for e in sorted(entries.values(), key=lambda e: (e["kind"], e["home"], e["name"])):
        n = len(set(e["found"].values()))
        versions = ("one, on " if n == 1 else f"{n} forks: ") + ", ".join(f"{k} `{v}`" for k, v in e["found"].items())
        needs = [*e["needs"]["services"], *(f"secret: {s}" for s in e["needs"]["secrets"])]
        needs += [f"asks: {', '.join(e['ask'])}"] * bool(e["ask"])
        needs += ["render server"] * (e["needs"]["render"] == "server") + ["touch"] * e["needs"]["touch"]
        marks = [q for q, m in sorted(e["quality"].items()) if m == "pass"]
        fails = [q for q, m in sorted(e["quality"].items()) if m == "fail"]
        quality = ", ".join(marks + [f"**{q} fails**" for q in fails]) or "unchecked"
        rows.append(f"| {e['name']} | {e['kind']} | {e['home']} | {e['about']} | {versions} | {', '.join(needs) or '–'} | {quality} |")
    return "\n".join(rows) + "\n"


def test():
    def run(*args, cwd):
        subprocess.run(args, cwd=cwd, check=True, capture_output=True)

    page = '"""p"""\n# art credit: https://commons.example.org/File:x.jpg\nURL = "https://api.example.org/x"\n' \
           'ART_HOSTS = ("art.example.org",)\nclass Page:\n    name, shapes = "sky", ("bar", "9-16")\n' \
           '    def __init__(self, lat=1.5, where=None, data=None):\n' \
           '        pass\ndef check():\n    assert not ok("https://evil.example/x")\n'
    with tempfile.TemporaryDirectory() as d:
        repo, folder = os.path.join(d, "repo"), os.path.join(d, "catalog")
        os.makedirs(os.path.join(repo, "catalog/pages/sky")); os.makedirs(os.path.join(repo, "catalog/transitions")); os.makedirs(os.path.join(repo, "kiosk/transitions"))
        os.mkdir(folder)
        open(os.path.join(repo, "catalog/pages/sky/page.py"), "w").write(page)
        open(os.path.join(repo, "catalog/pages/__init__.py"), "w").write("")   # a file beside the pages isn't one
        open(os.path.join(repo, "kiosk/transitions/__init__.py"), "w").write('THEMES = {"rain": rain}\ndef check(): pass\n')
        open(os.path.join(repo, "kiosk/transitions/canvas.py"), "w").write("")
        open(os.path.join(repo, "catalog/transitions/rain.py"), "w").write("def frames(canvas, count):\n    yield\n")
        run("git", "init", "-q", "-b", "main", cwd=repo); run("git", "add", ".", cwd=repo)
        run("git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "one", cwd=repo)
        lines = {"one": (repo, "main")}
        sky, rain = draft("page", "sky", lines), draft("transition", "rain", lines)
        assert sky["settings"] == {"lat": 1.5, "where": None} and sky["needs"]["services"] == ["api.example.org", "art.example.org"], sky
        assert sky["shapes"] == ["bar", "9-16"] and rain["shapes"] == ["bar"], (sky, rain)
        assert set(rain["found"]) == {"one"} and rain["settings"] == {}, rain
        for e in (sky, rain):
            e["about"] = "a test"
            json.dump(e, open(os.path.join(folder, e["name"] + ".json"), "w"))
        assert check(folder, lines) == [], check(folder, lines)

        def wrong(change, says, entry=sky):
            e = json.loads(json.dumps(entry)); change(e)
            got = problems(e, lines)
            assert any(says in p for p in got), (says, got)

        wrong(lambda e: e.update(colour=1), "fields must be exactly")
        wrong(lambda e: e.update(home="everywhere"), "home must be")
        wrong(lambda e: e["needs"].update(render="cloud"), "needs.render")
        wrong(lambda e: e.update(shapes=["round"]), "shapes are some of")
        wrong(lambda e: e.update(shapes=["bar"]), "the ones Page says")
        wrong(lambda e: e["quality"].update(zero="probably"), "quality is")
        wrong(lambda e: e.update(about=""), "about says")
        wrong(lambda e: e.update(ask=["colour"]), "ask names")
        wrong(lambda e: e.update(form={"colour": {"type": "text", "max": 4}}), "isn't one of its settings")
        wrong(lambda e: e.update(form={"lat": {"type": "wheel"}}), "type is")
        e = json.loads(json.dumps(sky)); e["form"] = {"lat": {"type": "number", "min": -90, "max": 90}}
        assert problems(e, lines) == [], problems(e, lines)
        e = json.loads(json.dumps(sky)); e["needs"]["secrets"] = ["a token"]; e["ask"] = ["a token", "lat"]
        assert problems(e, lines) == [], problems(e, lines)
        wrong(lambda e: e["found"].update(one="abcdef"), "one has")
        wrong(lambda e: e["found"].update(two="abcdef"), "lines nobody knows")
        wrong(lambda e: e["needs"].update(services=[]), "missing api.example.org, art.example.org")
        wrong(lambda e: e["needs"]["services"].append("x.org"), "lists x.org")
        wrong(lambda e: e.update(settings={"lat": 1.5}), "settings are")
        wrong(lambda e: e.update(name="cloud"), "isn't on any line")
        wrong(lambda e: e["found"].update(one="abcdef"), "rain: one has", rain)

        open(os.path.join(repo, "catalog/pages/sky/page.py"), "w").write(page.replace("def check", "def nope") + "# home.local\n")
        open(os.path.join(repo, "catalog/transitions/rain.py"), "w").write("def frame(canvas, count):\n    yield\n")
        os.makedirs(os.path.join(repo, "catalog/pages/moon")); open(os.path.join(repo, "catalog/pages/moon/page.py"), "w").write(page)
        open(os.path.join(repo, "catalog/transitions/snow.py"), "w").write("")
        run("git", "add", ".", cwd=repo); run("git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "two", cwd=repo)
        for e in (sky, rain):   # the new versions, so only what changed in them is wrong
            e["found"]["one"] = git(repo, "rev-parse", f"main:{where(e['kind'], e['name'])}")[:6]
            e["needs"]["services"] = sorted(draft(e["kind"], e["name"], lines)["needs"]["services"])
        sky["home"] = "public"
        got = [p for e in (sky, rain) for p in problems(e, lines)]
        assert any("sky: one's version has no check()" in p for p in got), got
        assert any("rain: one's version has no check()" in p for p in got), got
        assert any("public, but one's version mentions home.local" in p for p in got), got
        assert set(everything(lines)) == {("page", "sky"), ("page", "moon"), ("transition", "rain"),
                                          ("transition", "snow")}, "a new page or transition is found; the engine isn't"
        made = new("page", "kite", repo, folder) + new("transition", "wind", repo, folder)
        assert [os.path.relpath(f, d) for f in made] == ["repo/catalog/pages/kite/page.py", "repo/catalog/pages/kite/__init__.py",
                "catalog/kite.json", "repo/catalog/transitions/wind.py", "catalog/wind.json"], made
        assert 'name, seconds = "kite", 20' in open(made[0]).read() and "{name}" not in open(made[3]).read()
        assert load(folder)["kite"]["settings"] == {"title": None} and load(folder)["kite"]["shapes"] == ["bar"] and load(folder)["wind"]["kind"] == "transition"
        for kind, name in (("page", "kite"), ("transition", "wind"), ("page", "Kite"), ("page", "k"), ("page", "../x"),
                           ("transition", "canvas")):
            try:
                new(kind, name, repo, folder)
                raise AssertionError(f"made {kind} {name}")
            except ValueError:
                pass   # one that's there already, or a name that can't be one
        assert FRAMES.search("frames = simple(shown)\n") and FRAMES.search("def frames(c, count):") and not FRAMES.search("# def frames(")
        md = table(folder)
        assert "| sky | page | private | a test | one, on one `" in md and "api.example.org" in md, md
    print("catalog: ok")


if __name__ == "__main__":
    a = sys.argv[1:]
    if a == ["--check"]:
        bad = check()
        print("\n".join(bad) or f"catalog: {len(load())} entries, all ok")
        sys.exit(1 if bad else 0)
    elif a == ["--table"]:
        open(os.path.join(HERE, "CATALOG.md"), "w").write(table())
    elif len(a) == 3 and a[0] == "--draft" and a[1] in CHOICES["kind"]:
        print(json.dumps(draft(a[1], a[2]), indent=1))
    elif len(a) == 3 and a[0] == "--new" and a[1] in CHOICES["kind"]:
        try:
            made = new(a[1], a[2])
        except ValueError as e:
            sys.exit(str(e))
        print("made " + ", ".join(os.path.relpath(f) for f in made) + ". Next:\n"
              f"  to look at it:      python3 -I kiosk/kiosk.py --png {a[2]} {a[2]}.png\n"
              f"  before you push:    python3 -I kiosk/kiosk.py --check\n"
              f"  its catalog file:   python3 -I catalog/catalog.py --check says what it still needs")
    elif a == ["--test"]:
        test()
    else:
        sys.exit(__doc__)
