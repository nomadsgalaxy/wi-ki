#!/usr/bin/env python3
"""packs: installing pages and transitions on a kiosk, from the catalog or from someone's GitHub repo.

A kiosk comes with a small core (core.json) and installs the rest when someone asks, on its setup page:

  from the catalog   the pages and transitions in Wi-Ki's catalog, reviewed before they were merged. They come from the
                     kiosk's own update clone (~/wi-ki), so they're always the version that goes with its code, and
                     autoupdate keeps them up to date with everything else. installed.json lists which.
  from a repo        anyone's, on GitHub: a wiki-pack.json and the page's folder (or the transition's .py) at the top of
                     the repo. Nobody has reviewed that code, and it runs as the kiosk's user, so the setup page says so
                     before it installs one. It's pinned to the exact commit it was installed at, and only changes
                     when someone clicks Update. It lives in ~/.local/share/kiosk/, which updates never touch, and
                     packs.json lists them.

A page that's in the playlist stays installed (remove it from the playlist first), and so does everything in core.

The setup page doesn't install anything itself (it has no internet, and only sees its own settings): it writes a
request to packs-request.json, and systemd/kiosk-packs.path runs this as the kiosk's user to carry it out, then
writes what happened to packs-status.json. On a kiosk whose pages a render server draws, the request goes to the
server (link.py), since that's where the pages run; a transition is installed on both, since the Pi plays it.

  packs.py --run      carry out the request in packs-request.json
  packs.py --check    self-test
"""
import io, json, os, re, shutil, subprocess, sys, tarfile, tempfile, time, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.realpath(__file__))
HOME = os.path.expanduser("~")
CONF = os.path.join(HOME, ".config", "kiosk")
SHARE = os.path.join(HOME, ".local", "share", "kiosk")   # repo packs: pages/<name>/ and transitions/<name>.py
CLONE = os.path.join(HOME, "wi-ki")                     # the update clone: the whole catalog, at the code's commit
if not os.path.isdir(CLONE) and os.path.isdir(os.path.join(HOME, "HiveKiosk")):   # its old name, till autoupdate moves it
    CLONE = os.path.join(HOME, "HiveKiosk")
REQUEST, STATUS = "packs-request.json", "packs-status.json"
KINDS = {"page": "pages", "transition": "transitions"}
NAME = re.compile(r"[a-z][a-z0-9_]{1,30}")
GITHUB = re.compile(r"https://github\.com/([A-Za-z0-9-]{1,39})/([A-Za-z0-9._-]{1,100}?)(?:\.git)?/?")
MOST_BYTES, MOST_UNPACKED, MOST_FILES = 4 << 20, 8 << 20, 200
FILE_TYPES = (".py", ".json", ".png", ".txt", ".md")   # what a pack may hold
UA = {"User-Agent": "wi-ki packs (github.com/nomadsgalaxy/wi-ki)"}


def copy(src, dst):
    """a page's folder or a transition's file, into place"""
    if os.path.isdir(src):
        shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__"))
    else:
        shutil.copy2(src, dst)


def drop(path):
    if os.path.isdir(path):
        shutil.rmtree(path)
    elif os.path.exists(path):
        os.remove(path)


def core(here=HERE):
    return json.load(open(os.path.join(here, "core.json")))


def read_json(path, default):
    try:
        return json.load(open(path))
    except (OSError, ValueError):
        return default


def write_json(path, value):
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    with open(path + ".tmp", "w") as f:
        json.dump(value, f, indent=1)
    os.replace(path + ".tmp", path)


def installed(conf=CONF):
    """the catalog pages and transitions installed beyond core -> {"pages": [...], "transitions": [...]}, or None for a
    kiosk set up before there was such a thing"""
    got = read_json(os.path.join(conf, "installed.json"), None)
    if not isinstance(got, dict):
        return None
    return {k: sorted({n for n in got.get(k, []) if isinstance(n, str) and NAME.fullmatch(n)}) for k in KINDS.values()}


def in_playlist(conf=CONF, here=HERE):
    """the pages the kiosk's playlist names, on or off; on a server that draws for several kiosks (each with its own
    HOME in servers/<name>, see docs/server.md), every one of their playlists too, since they share these pages"""
    names = set()
    for path in (os.path.join(conf, "playlist.json"), os.path.join(here, "playlist.json")):
        got = read_json(path, None)
        if isinstance(got, list):
            names = {e["page"] for e in got if isinstance(e, dict) and isinstance(e.get("page"), str)}
            break
    servers = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(conf))), "servers")
    for name in sorted(os.listdir(servers)) if os.path.isdir(servers) else []:
        got = read_json(os.path.join(servers, name, ".config", "kiosk", "playlist.json"), None)
        if isinstance(got, list):
            names |= {e["page"] for e in got if isinstance(e, dict) and isinstance(e.get("page"), str)}
    return names


def wanted(repo, conf, live):
    """what a kiosk runs from the catalog: core, what's installed, and every page its playlist names. A kiosk from
    before packs gets installed.json made from whatever it has now, so an update never takes a page away."""
    have = installed(conf)
    if have is None:
        have = {k: sorted(n[:-3] if n.endswith(".py") else n for n in os.listdir(os.path.join(live, k))
                          if not n.startswith("__") and n != "canvas.py" and n != "setup")
                for k in KINDS.values() if os.path.isdir(os.path.join(live, k))} if os.path.isdir(live) else {}
        have = {k: have.get(k, []) for k in KINDS.values()}
        if os.path.isdir(live):
            write_json(os.path.join(conf, "installed.json"), have)
    c = core(os.path.join(repo, "kiosk"))
    return {"pages": set(c["pages"]) | set(have["pages"]) | in_playlist(conf, os.path.join(repo, "kiosk")),
            "transitions": set(c["transitions"]) | set(have["transitions"])}


# --- from a repo ---

def github(url):
    """https://github.com/<owner>/<repo> -> (owner, repo), or ValueError"""
    m = GITHUB.fullmatch(url.strip())
    if not m:
        raise ValueError("a repo is https://github.com/<owner>/<repo>")
    return m.group(1), m.group(2)


def fetch(url, most=MOST_BYTES):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        data = r.read(most + 1)
    if len(data) > most:
        raise ValueError("that's bigger than a pack can be")
    return data


def resolve(owner, repo, ref="HEAD", get=fetch):
    """the commit a branch, tag or commit names right now"""
    if not re.fullmatch(r"[A-Za-z0-9._/-]{1,100}", ref) or ".." in ref:
        raise ValueError("that isn't a branch, tag or commit")
    got = json.loads(get(f"https://api.github.com/repos/{owner}/{repo}/commits/{urllib.parse.quote(ref, safe='/')}"))
    sha = got.get("sha", "") if isinstance(got, dict) else ""
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("GitHub didn't say which commit that is")
    return sha


def unpack(data, into):
    """a GitHub tarball into a folder, refusing anything that isn't a plain file of a pack's kind inside it -> the
    folder with the repo's files in it"""
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        members, total, files = tar.getmembers(), 0, 0
        top = {m.name.split("/")[0] for m in members}
        if len(top) != 1:
            raise ValueError("that isn't a GitHub tarball")
        for m in members:
            parts = m.name.split("/")
            if m.name.startswith("/") or ".." in parts or not (m.isfile() or m.isdir()):
                raise ValueError(f"{m.name}: only plain files and folders, inside the pack")
            if m.isfile():
                rel = "/".join(parts[1:])
                if rel.startswith(".") or "/." in rel:
                    continue   # .github/, .gitignore and the like aren't part of it
                files += 1; total += m.size
                if files > MOST_FILES or total > MOST_UNPACKED:
                    raise ValueError("that's bigger than a pack can be")
                out = os.path.join(into, rel)
                os.makedirs(os.path.dirname(out), exist_ok=True)
                with tar.extractfile(m) as src, open(out, "wb") as dst:
                    dst.write(src.read())
    return into


def plain(path):
    """a pack's own folder (or file) holds only the kinds of files a page or transition is made of -> ValueError if not.
    The rest of the repo (its LICENSE, README, docs) isn't installed, so it can be anything."""
    found = [path] if os.path.isfile(path) else [os.path.join(r, f) for r, _, fs in os.walk(path) for f in fs]
    for f in found:
        if not f.endswith(FILE_TYPES):
            raise ValueError(f"{os.path.relpath(f, os.path.dirname(path))}: a pack holds {', '.join(FILE_TYPES)} files")


def describe(folder, taken):
    """a pack's wiki-pack.json, checked -> dict, or ValueError"""
    meta = read_json(os.path.join(folder, "wiki-pack.json"), None)
    if not isinstance(meta, dict):
        raise ValueError("there's no wiki-pack.json at the top of that repo")
    name, kind = meta.get("name"), meta.get("kind")
    if not (isinstance(name, str) and NAME.fullmatch(name)):
        raise ValueError("wiki-pack.json's name is lowercase letters, digits and _")
    if kind not in KINDS:
        raise ValueError('wiki-pack.json\'s kind is "page" or "transition"')
    if name in taken:
        raise ValueError(f"there's already a page or transition called {name}")
    if not isinstance(meta.get("about"), str) or not isinstance(meta.get("licence"), str):
        raise ValueError("wiki-pack.json says what it is (about) and its licence")
    code = os.path.join(folder, name, "__init__.py") if kind == "page" else os.path.join(folder, name + ".py")
    if not os.path.isfile(code):
        raise ValueError(f"the {kind} isn't there: {os.path.relpath(code, folder)}")
    return {"name": name, "kind": kind, "about": meta["about"][:200], "licence": meta["licence"][:100]}


def trial(folder, meta, here=HERE, timeout=300):
    """load the new page or transition in a process of its own and have it draw once, before it's switched on"""
    kind, name = meta["kind"], meta["name"]
    script = (f"import sys; sys.path.insert(0, {here!r}); import {KINDS[kind]}; {KINDS[kind]}.__path__.insert(0, {folder!r})\n"
              + (f"import importlib; m = importlib.import_module('pages.{name}'); import kit\n"
                 f"assert m.preview().size == kit.SCREEN and hasattr(m, 'Page')\n" if kind == "page" else
                 f"import importlib; from transitions.canvas import Canvas, WIDTH, HEIGHT\n"
                 f"m = importlib.import_module('transitions.{name}'); size = WIDTH * HEIGHT * 2\n"
                 f"c = Canvas(bytearray(size), b'\\x55' * size)\n"
                 f"for _, _ in zip(m.frames(c, 24), range(24)): pass\n"))
    got = subprocess.run([sys.executable, "-I", "-c", script], capture_output=True, text=True, timeout=timeout)
    if got.returncode:
        raise ValueError(f"it didn't load and draw: {(got.stderr.strip().splitlines() or ['?'])[-1][:160]}")


def taken_names(here=HERE, share=SHARE, repo=CLONE):
    names = set()
    for root in (here, share, os.path.join(repo, "catalog")):
        for k in KINDS.values():
            d = os.path.join(root, k)
            if os.path.isdir(d):
                names |= {n[:-3] if n.endswith(".py") else n for n in os.listdir(d)}
    return names


def from_repo(url, ref, conf=CONF, share=SHARE, here=HERE, repo_clone=CLONE, get=fetch, check=trial, replacing=None):
    """download a pack at a pinned commit, check it, try it, and put it in place -> its record in packs.json"""
    owner, repo = github(url)
    sha = resolve(owner, repo, ref or "HEAD", get)
    with tempfile.TemporaryDirectory() as tmp:
        folder = unpack(get(f"https://codeload.github.com/{owner}/{repo}/tar.gz/{sha}"), os.path.join(tmp, "pack"))
        taken = taken_names(here, share, repo_clone) - ({replacing} if replacing else set())
        meta = describe(folder, taken)
        if replacing and meta["name"] != replacing:
            raise ValueError(f"that repo's pack is {meta['name']} now, not {replacing}")
        stage = os.path.join(tmp, "stage", KINDS[meta["kind"]]); os.makedirs(stage)
        src = os.path.join(folder, meta["name"]) + ("" if meta["kind"] == "page" else ".py")
        plain(src)
        dst = os.path.join(stage, os.path.basename(src))
        copy(src, dst)
        check(stage, meta, here)
        final = os.path.join(share, KINDS[meta["kind"]], os.path.basename(src))
        os.makedirs(os.path.dirname(final), exist_ok=True)
        drop(final)
        copy(dst, final)
    record = {**meta, "repo": f"https://github.com/{owner}/{repo}", "ref": ref or "HEAD", "commit": sha,
              "installed": time.strftime("%Y-%m-%d")}
    packs = read_json(os.path.join(conf, "packs.json"), {})
    packs[meta["name"]] = record
    write_json(os.path.join(conf, "packs.json"), packs)
    return record


# --- carrying out a request ---

def restart_display(here=HERE):
    subprocess.run(["pkill", "-f", f"(^|/)python3 -I {here}/kiosk.py"], capture_output=True, timeout=10)


def carry_out(req, conf=CONF, share=SHARE, here=HERE, repo_clone=CLONE, get=fetch, check=trial, restart=restart_display):
    """one request from the setup page -> a message for people, or ValueError"""
    op, kind, name, source = req.get("op"), req.get("kind"), req.get("name"), req.get("source")
    packs = read_json(os.path.join(conf, "packs.json"), {})
    if op == "check":
        newer = {}
        for n, p in packs.items():
            try:
                sha = resolve(*github(p["repo"]), p["ref"], get)
            except (OSError, ValueError):
                continue
            if sha != p["commit"]:
                newer[n] = sha
        return ("Updates: " + ", ".join(sorted(newer)) if newer else "Everything's up to date."), newer
    if op == "install" and source == "repo":
        record = from_repo(str(req.get("repo", "")), str(req.get("ref") or ""), conf, share, here, repo_clone, get, check)
        restart()
        return f"Installed {record['name']} from {record['repo']} at {record['commit'][:7]}.", None
    if op == "update":
        if name not in packs:
            raise ValueError("that isn't installed from a repo")
        record = from_repo(packs[name]["repo"], packs[name]["ref"], conf, share, here, repo_clone, get, check, replacing=name)
        restart()
        return f"Updated {name} to {record['commit'][:7]}.", None
    if kind not in KINDS or not (isinstance(name, str) and NAME.fullmatch(name)):
        raise ValueError("which page or transition?")
    folder, mine = KINDS[kind], installed(conf) or {k: [] for k in KINDS.values()}
    if op == "install" and source == "catalog":
        src = os.path.join(repo_clone, "catalog", folder, name + ("" if kind == "page" else ".py"))
        if not os.path.exists(src):
            raise ValueError(f"the catalog has no {kind} called {name}")
        dst = os.path.join(here, folder, os.path.basename(src))
        if not os.path.exists(dst):
            copy(src, dst)
        mine[folder] = sorted(set(mine[folder]) | {name})
        write_json(os.path.join(conf, "installed.json"), mine)
        restart()
        return f"Installed {name} from the catalog.", None
    if op == "remove":
        if name in core(here)[folder]:
            raise ValueError(f"{name} comes with every kiosk, so it stays")
        if kind == "page" and name in in_playlist(conf, here):
            raise ValueError(f"{name} is in the playlist: take it out first")
        if name in packs:
            target = os.path.join(share, folder, name + ("" if kind == "page" else ".py"))
            del packs[name]; write_json(os.path.join(conf, "packs.json"), packs)
        elif name in mine[folder]:
            target = os.path.join(here, folder, name + ("" if kind == "page" else ".py"))
            mine[folder] = [n for n in mine[folder] if n != name]; write_json(os.path.join(conf, "installed.json"), mine)
        else:
            raise ValueError(f"{name} isn't installed")
        drop(target)
        off = read_json(os.path.join(conf, "transitions-off.json"), [])
        if kind == "transition" and isinstance(off, list) and name in off:
            write_json(os.path.join(conf, "transitions-off.json"), [n for n in off if n != name])
        restart()
        return f"Removed {name}.", None
    raise ValueError("that isn't something it does")


def run(conf=CONF, **kw):
    """carry out packs-request.json, once, and say how it went in packs-status.json"""
    path = os.path.join(conf, REQUEST)
    req = read_json(path, None)
    if not isinstance(req, dict):
        return
    try:
        os.remove(path)
    except OSError:
        pass
    status = {"id": req.get("id"), "at": time.time(), "state": "working", "message": "Working on it..."}
    write_json(os.path.join(conf, STATUS), status)
    try:
        message, newer = carry_out(req, conf, **kw)
        status.update(state="done", message=message, **({"updates": newer} if newer is not None else {}))
    except (OSError, ValueError, subprocess.TimeoutExpired, tarfile.TarError) as e:
        status.update(state="failed", message=str(e)[:300])
    status["at"] = time.time()
    write_json(os.path.join(conf, STATUS), status)


def check():
    import hashlib
    with tempfile.TemporaryDirectory() as d:
        here, conf, share, clone = (os.path.join(d, n) for n in ("live", "conf", "share", "clone"))
        for n in ("pages/weather", "pages/radar", "transitions"):
            os.makedirs(os.path.join(here, n))
        open(os.path.join(here, "transitions", "matrix.py"), "w").write("")
        json.dump({"pages": ["weather", "radar"], "transitions": ["matrix"]}, open(os.path.join(here, "core.json"), "w"))
        json.dump([{"page": "weather"}], open(os.path.join(here, "playlist.json"), "w"))
        os.makedirs(os.path.join(clone, "catalog", "pages", "septa")); os.makedirs(os.path.join(clone, "catalog", "transitions"))
        open(os.path.join(clone, "catalog", "pages", "septa", "__init__.py"), "w").write("")
        open(os.path.join(clone, "catalog", "transitions", "hive76.py"), "w").write("")
        restarts = []
        go = lambda req, **kw: carry_out(req, conf, share, here, clone, restart=lambda: restarts.append(1), **kw)
        # the catalog: in, then out again; core and what's in the playlist stay
        assert go({"op": "install", "source": "catalog", "kind": "page", "name": "septa"})[0].startswith("Installed")
        assert os.path.isdir(os.path.join(here, "pages", "septa")) and installed(conf)["pages"] == ["septa"] and restarts
        go({"op": "install", "source": "catalog", "kind": "transition", "name": "hive76"})
        assert installed(conf)["transitions"] == ["hive76"] and os.path.exists(os.path.join(here, "transitions", "hive76.py"))
        for req, says in (({"op": "remove", "kind": "page", "name": "weather"}, "comes with every kiosk"),
                          ({"op": "install", "source": "catalog", "kind": "page", "name": "nope"}, "no page called"),
                          ({"op": "install", "source": "catalog", "kind": "page", "name": "../x"}, "which page"),
                          ({"op": "remove", "kind": "page", "name": "radar"}, "comes with every kiosk"),
                          ({"op": "wat"}, "which page")):
            try:
                go(req)
            except ValueError as e:
                assert says in str(e), (req, e)
            else:
                raise AssertionError(f"did {req}")
        json.dump([{"page": "weather"}, {"page": "septa", "on": False}], open(os.path.join(conf, "playlist.json"), "w"))
        try:
            go({"op": "remove", "kind": "page", "name": "septa"})
        except ValueError as e:
            assert "in the playlist" in str(e)
        else:
            raise AssertionError("removed a page that's in the playlist")
        os.remove(os.path.join(conf, "playlist.json"))
        # a server that draws for several kiosks: a page any of their playlists names is in use, and stays
        with tempfile.TemporaryDirectory() as home:
            mine, door = os.path.join(home, ".config", "kiosk"), os.path.join(home, "servers", "door", ".config", "kiosk")
            os.makedirs(mine); os.makedirs(door)
            json.dump([{"page": "weather"}], open(os.path.join(mine, "playlist.json"), "w"))
            json.dump([{"page": "sky"}, {"page": "calendar", "on": False}], open(os.path.join(door, "playlist.json"), "w"))
            assert in_playlist(mine, here) == {"weather", "sky", "calendar"}, in_playlist(mine, here)
            os.makedirs(os.path.join(home, "servers", "broken", ".config", "kiosk"))
            open(os.path.join(home, "servers", "broken", ".config", "kiosk", "playlist.json"), "w").write("[not")
            assert in_playlist(mine, here) == {"weather", "sky", "calendar"}, "a broken one is skipped"
        json.dump(["hive76"], open(os.path.join(conf, "transitions-off.json"), "w"))
        go({"op": "remove", "kind": "transition", "name": "hive76"})
        assert not os.path.exists(os.path.join(here, "transitions", "hive76.py")) and installed(conf)["transitions"] == []
        assert json.load(open(os.path.join(conf, "transitions-off.json"))) == [], "and it's not left in transitions-off"

        # a repo: a GitHub tarball, pinned, checked, tried, and refused when it isn't right
        def tarball(files, top="me-clock-0123456"):
            buf = io.BytesIO()
            with tarfile.open(fileobj=buf, mode="w:gz") as tar:
                for name, body in files.items():
                    info = tarfile.TarInfo(f"{top}/{name}"); data = body.encode(); info.size = len(data)
                    tar.addfile(info, io.BytesIO(data))
            return buf.getvalue()
        pack = {"wiki-pack.json": json.dumps({"name": "clock", "kind": "page", "about": "a big clock", "licence": "MIT"}),
                "clock/__init__.py": "from .page import Page, check, preview\n", "clock/page.py": "x = 1\n", ".github/ci.yml": "ignored",
                "LICENSE": "MIT", "README": "a clock", "docs/shot.jpg": "not installed, so it can be anything"}
        shas = iter(["a" * 40, "b" * 40, "b" * 40, "c" * 40])
        repo_files = {"files": pack}
        def get(url, most=MOST_BYTES):
            if "api.github.com" in url:
                return json.dumps({"sha": next(shas)}).encode()
            return tarball(repo_files["files"])
        tried = []
        trial_ok = lambda folder, meta, here: tried.append(meta["name"])
        msg, _ = go({"op": "install", "source": "repo", "repo": "https://github.com/me/clock", "ref": "main"}, get=get, check=trial_ok)
        assert "at aaaaaaa" in msg and tried == ["clock"], msg
        assert os.path.isfile(os.path.join(share, "pages", "clock", "page.py")) and not os.path.exists(os.path.join(share, "pages", "clock", ".github"))
        assert sorted(os.listdir(os.path.join(share, "pages", "clock"))) == ["__init__.py", "page.py"], "only the pack itself"
        record = json.load(open(os.path.join(conf, "packs.json")))["clock"]
        assert record["commit"] == "a" * 40 and record["repo"] == "https://github.com/me/clock" and record["ref"] == "main"
        assert go({"op": "check"}, get=get)[1] == {"clock": "b" * 40}, "a newer commit is an update, not installed till asked"
        assert json.load(open(os.path.join(conf, "packs.json")))["clock"]["commit"] == "a" * 40
        go({"op": "update", "name": "clock"}, get=get, check=trial_ok)
        assert json.load(open(os.path.join(conf, "packs.json")))["clock"]["commit"] == "b" * 40
        go({"op": "remove", "kind": "page", "name": "clock"})
        assert not os.path.exists(os.path.join(share, "pages", "clock")) and "clock" not in json.load(open(os.path.join(conf, "packs.json")))
        bads = [({"wiki-pack.json": pack["wiki-pack.json"]}, "isn't there"),
                ({"clock/__init__.py": ""}, "no wiki-pack.json"),
                (dict(pack, **{"wiki-pack.json": json.dumps({"name": "weather", "kind": "page", "about": "x", "licence": "MIT"}),
                               "weather/__init__.py": ""}), "already a page"),
                (dict(pack, **{"wiki-pack.json": json.dumps({"name": "Clock!", "kind": "page", "about": "x", "licence": "MIT"})}), "lowercase"),
                (dict(pack, **{"clock/run.sh": "rm -rf"}), "a pack holds"),
                (dict(pack, **{f"clock/f{i}.txt": "" for i in range(MOST_FILES + 1)}), "bigger than a pack"),
                (dict(pack, **{"wiki-pack.json": json.dumps({"name": "clock", "kind": "app", "about": "x", "licence": "MIT"})}), "kind is")]
        for files, says in bads:
            repo_files["files"] = files; shas = iter(["d" * 40])
            try:
                go({"op": "install", "source": "repo", "repo": "https://github.com/me/clock"}, get=get, check=trial_ok)
            except ValueError as e:
                assert says in str(e), (says, e)
            else:
                raise AssertionError(f"installed {sorted(files)[:3]}")
        assert not os.path.exists(os.path.join(share, "pages", "clock")), "nothing half-installed"
        # a tarball that reaches outside, or links somewhere, is refused before anything's written
        for evil in ("../escape.py", "/etc/evil.py"):
            buf = io.BytesIO()
            with tarfile.open(fileobj=buf, mode="w:gz") as tar:
                info = tarfile.TarInfo(evil); info.size = 1; tar.addfile(info, io.BytesIO(b"x"))
            try:
                unpack(buf.getvalue(), os.path.join(d, "x"))
            except ValueError:
                pass
            else:
                raise AssertionError(f"unpacked {evil}")
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            info = tarfile.TarInfo("top/link.py"); info.type = tarfile.SYMTYPE; info.linkname = "/etc/passwd"; tar.addfile(info)
        try:
            unpack(buf.getvalue(), os.path.join(d, "y"))
        except ValueError:
            pass
        else:
            raise AssertionError("unpacked a symlink")
        for url in ("http://github.com/me/clock", "https://gitlab.com/me/clock", "https://github.com/me", "https://github.com/me/clock/../x"):
            try:
                github(url)
            except ValueError:
                pass
            else:
                raise AssertionError(f"took {url}")
        for ref in ("../main", "a b", "main;rm"):
            try:
                resolve("me", "clock", ref, get)
            except ValueError:
                pass
            else:
                raise AssertionError(f"took the ref {ref!r}")
        # a kiosk from before packs keeps everything it has
        old_conf, old_live = os.path.join(d, "old-conf"), os.path.join(d, "old-live")
        os.makedirs(os.path.join(old_live, "pages", "github")); os.makedirs(os.path.join(old_live, "transitions"))
        open(os.path.join(old_live, "transitions", "johnny5.py"), "w").write("")
        repo = os.path.join(d, "repo"); os.makedirs(os.path.join(repo, "kiosk"))
        json.dump({"pages": ["weather"], "transitions": ["matrix"]}, open(os.path.join(repo, "kiosk", "core.json"), "w"))
        json.dump([{"page": "weather"}, {"page": "radar"}], open(os.path.join(repo, "kiosk", "playlist.json"), "w"))
        got = wanted(repo, old_conf, old_live)
        assert got == {"pages": {"weather", "github", "radar"}, "transitions": {"matrix", "johnny5"}}, got
        assert installed(old_conf) == {"pages": ["github"], "transitions": ["johnny5"]}, "and remembers it"
        fresh = wanted(repo, os.path.join(d, "fresh-conf"), os.path.join(d, "no-live"))
        assert fresh == {"pages": {"weather", "radar"}, "transitions": {"matrix"}}, "a new kiosk gets core and its playlist"
        # the request file: carried out once, and how it went is in the status
        json.dump({"id": "r1", "op": "install", "source": "catalog", "kind": "page", "name": "nope"}, open(os.path.join(conf, REQUEST), "w"))
        run(conf, share=share, here=here, repo_clone=clone, restart=lambda: None)
        status = json.load(open(os.path.join(conf, STATUS)))
        assert status["id"] == "r1" and status["state"] == "failed" and "no page" in status["message"]
        assert not os.path.exists(os.path.join(conf, REQUEST))
    print("packs: ok")


if __name__ == "__main__":
    if sys.argv[1:] == ["--check"]:
        check()
    elif sys.argv[1:] == ["--run"]:
        run()
    else:
        sys.exit(__doc__)
