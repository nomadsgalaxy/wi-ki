"""link: a kiosk's setup page and its render server, for a kiosk whose pages the server draws. The server keeps those
pages' settings (its playlist and the transitions it skips), so the setup page on the Pi asks the server for them and
sends it the changes.

They talk on the server's port, the one the Pi's screen comes over: a connection that starts with a CONF message is
this, and one that says nothing is a Pi (remote.py). Every message is signed with the key both have in
~/.config/kiosk/remote.json ("key": 64 hex characters), so nothing else on the network can change a kiosk's pages,
and each carries the time and a one-off nonce, so a recorded one can't be played back. Without a key on both, the
setup page only shows the settings.

  CONF  a=64, then the HMAC-SHA256 of the body in hex, then the body: {"op": "get"}, {"op": "put", "playlist": [...],
        "off": [...]} (either or both), {"op": "packs", "request": {...}} to install, update or remove a page or
        transition there (packs.py), or {"op": "control", "args": [...]}, a control.py command for the server's
        display, plus "t" and "nonce"
  the reply: CONF a=0, then {"ok": true, ...} or {"ok": false, "error": "..."}

Standard library only, and nothing heavy: the setup page imports this, and it shares a Zero with the display.
"""
import hashlib, hmac, json, os, re, secrets, socket, struct, subprocess, threading, time

import config

HERE = os.path.dirname(os.path.realpath(__file__))
CONF = os.path.expanduser("~/.config/kiosk")
REMOTE = os.path.join(CONF, "remote.json")
HEADER = struct.Struct("<4sII")   # the same framing as remote.py's
MOST, WINDOW, WAIT = 64 * 1024, 120, 10   # bytes in a message; seconds a message is good for; seconds to wait for one


def key(path=REMOTE):
    """the shared key from remote.json, or None"""
    try:
        k = json.load(open(path)).get("key")
    except (OSError, ValueError, AttributeError):
        return None
    return k if isinstance(k, str) and re.fullmatch(r"[0-9a-f]{64}", k) else None


def sign(k, body):
    return hmac.new(bytes.fromhex(k), body, hashlib.sha256).hexdigest().encode()


def read(sock, n):
    data = b""
    while len(data) < n:
        got = sock.recv(n - len(data))
        if not got:
            raise ConnectionError("the other end hung up")
        data += got
    return data


def request(address, k, message, timeout=WAIT):
    """ask the server something -> its reply; raises OSError or ValueError if it can't be had"""
    body = json.dumps({**message, "t": time.time(), "nonce": secrets.token_hex(16)}).encode()
    with socket.create_connection(address, timeout=timeout) as sock:
        sig = sign(k, body)
        sock.sendall(HEADER.pack(b"CONF", len(sig), len(sig) + len(body)) + sig + body)
        kind, _, n = HEADER.unpack(read(sock, HEADER.size))
        if kind != b"CONF" or n > MOST:
            raise ValueError("that isn't a reply")
        reply = json.loads(read(sock, n))
    if not reply.get("ok"):
        raise ValueError(reply.get("error") or "the server said no")
    return reply


class Nonces:
    """the nonces seen in the last WINDOW seconds, so each message only works once"""
    def __init__(self):
        self.lock, self.seen = threading.Lock(), {}

    def fresh(self, nonce, now):
        with self.lock:
            self.seen = {n: t for n, t in self.seen.items() if now - t < 2 * WINDOW}
            if nonce in self.seen:
                return False
            self.seen[nonce] = now
            return True


def answer(sock, k, handle, nonces, timeout=WAIT):
    """the server's side, for a connection that started with CONF: check it, handle() it, reply. Never raises."""
    def reply(out):
        data = json.dumps(out).encode()
        sock.sendall(HEADER.pack(b"CONF", 0, len(data)) + data)
    try:
        sock.settimeout(timeout)
        kind, a, n = HEADER.unpack(read(sock, HEADER.size))
        if kind != b"CONF" or a != 64 or not a < n <= MOST:
            return reply({"ok": False, "error": "that isn't a message"})
        data = read(sock, n)
        sig, body = data[:a], data[a:]
        if not k:
            return reply({"ok": False, "error": "this server has no key in remote.json"})
        if not hmac.compare_digest(sig, sign(k, body)):
            return reply({"ok": False, "error": "that isn't signed with this server's key"})
        message = json.loads(body)
        t, now = message.get("t"), time.time()
        if not isinstance(t, (int, float)) or abs(now - t) > WINDOW or not nonces.fresh(str(message.get("nonce")), now):
            return reply({"ok": False, "error": "that message is stale or has been used"})
        reply(handle(message))
    except (OSError, ValueError, TypeError, AttributeError) as e:
        try:
            reply({"ok": False, "error": type(e).__name__})
        except OSError:
            pass
    finally:
        sock.close()


# --- the settings the server keeps, the same files kiosk.py reads ---

def themes(folder=os.path.join(HERE, "transitions")):
    return sorted(f[:-3] for f in os.listdir(folder) if f.endswith(".py") and f not in ("__init__.py", "canvas.py"))


def present(here=HERE):
    """the pages and transitions this machine has right now, catalog and repo packs alike"""
    share = os.path.expanduser("~/.local/share/kiosk")
    pages = {n for d in (os.path.join(here, "pages"), os.path.join(share, "pages")) if os.path.isdir(d) for n in os.listdir(d)
             if os.path.isfile(os.path.join(d, n, "__init__.py")) and n != "setup"}
    return {"pages": sorted(pages), "transitions": themes(os.path.join(here, "transitions")) +
            sorted(set(themes(os.path.join(share, "transitions"))) if os.path.isdir(os.path.join(share, "transitions")) else [])}


def pack_request(req):
    """a request for packs.py, checked the way the setup page checks it -> the request, or ValueError"""
    if not isinstance(req, dict) or req.get("op") not in ("install", "remove", "update", "check"):
        raise ValueError("that isn't a request for a page or transition")
    if any(not isinstance(v, str) or len(v) > 300 for v in req.values()):
        raise ValueError("that request isn't plain text")
    return {k: req[k] for k in ("id", "op", "kind", "name", "source", "repo", "ref") if k in req}


def machine(here=HERE):
    """the machine's own settings folder, beside the code (~/.config/kiosk of the user it's installed for): where the
    pages and transitions installed for everyone on it are kept. On a server that draws for several kiosks, each runs
    with its own HOME (servers/<name>), but they share one copy of the code, so an install is the machine's."""
    return os.path.realpath(os.path.join(here, "..", ".config", "kiosk"))


def settings(message, conf=CONF, here=HERE, restart=None):
    """handle() for the server: "get" -> its playlist, the transitions it skips, and what it has installed; "put" ->
    saves them, checked first, then restarts its display so they take effect; "packs" -> passes a request to install,
    update or remove something to the machine's packs.py (kiosk-packs.path watches machine())"""
    playlist, repo, off = os.path.join(conf, "playlist.json"), os.path.join(here, "playlist.json"), os.path.join(conf, "transitions-off.json")
    shared = machine(here)
    names = themes(os.path.join(here, "transitions"))
    if message.get("op") == "get":
        own = os.path.exists(playlist)
        try:
            skipped = json.load(open(off))
        except (OSError, ValueError):
            skipped = []
        read = lambda f, default: json.load(open(os.path.join(shared, f))) if os.path.exists(os.path.join(shared, f)) else default
        return {"ok": True, "playlist": json.load(open(playlist if own else repo)), "own": own,
                "off": [n for n in skipped if n in names] if isinstance(skipped, list) else [], "themes": names,
                "present": present(here), "packs": read("packs.json", {}), "status": read("packs-status.json", {})}
    if message.get("op") == "packs":
        try:
            req = pack_request(message.get("request"))
        except ValueError as e:
            return {"ok": False, "error": str(e)}
        os.makedirs(shared, mode=0o700, exist_ok=True)
        with open(os.path.join(shared, "packs-request.json.tmp"), "w") as f:
            json.dump(req, f)
        os.replace(os.path.join(shared, "packs-request.json.tmp"), os.path.join(shared, "packs-request.json"))
        return {"ok": True}
    if message.get("op") == "control":   # the Pi's control.py passing on a command from a paired computer
        args = message.get("args")
        if not (isinstance(args, list) and 0 < len(args) <= 4 and all(isinstance(x, str) and len(x) <= 64 for x in args)):
            return {"ok": False, "error": "that isn't a command"}
        import control
        try:
            return {"ok": True, "out": control.run(args)}
        except (ValueError, OSError) as e:
            return {"ok": False, "error": str(e)}
    if message.get("op") != "put" or not ({"playlist", "off"} & set(message)):
        return {"ok": False, "error": "that isn't something it does"}
    writes = []
    if "playlist" in message:
        try:
            writes.append((playlist, config.validate_playlist(message["playlist"])))
        except ValueError as e:
            return {"ok": False, "error": str(e)}
    if "off" in message:
        skip = message["off"]
        if not isinstance(skip, list) or not set(skip) <= set(names) or (names and len(set(skip)) == len(names)):
            return {"ok": False, "error": "the transitions to skip have to be some of its transitions, not all"}
        writes.append((off, sorted(set(skip))))
    os.makedirs(conf, mode=0o700, exist_ok=True)
    for path, value in writes:   # each in one move, so a power cut leaves the old file rather than half a new one
        fd = os.open(path + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(value, f); f.flush(); os.fsync(f.fileno())
        os.replace(path + ".tmp", path)
    (restart or (lambda: threading.Timer(1, restart_display, [here]).start()))()   # after the reply has gone
    return {"ok": True}


def restart_display(here=HERE):
    """the server's display and its browser renderers start again with the new settings (systemd brings them back)"""
    subprocess.run(["pkill", "-f", f"(^|/)python3 -I {here}/kiosk.py"], capture_output=True, timeout=10)


def check():
    import tempfile
    k, wrong = secrets.token_hex(32), secrets.token_hex(32)
    with tempfile.TemporaryDirectory() as d:
        os.makedirs(f"{d}/conf"); os.makedirs(f"{d}/code/transitions")
        for t in ("matrix", "coreone", "__init__", "canvas"):
            open(f"{d}/code/transitions/{t}.py", "w").write("")
        json.dump([{"page": "weather"}], open(f"{d}/code/playlist.json", "w"))
        json.dump({"server": "10.0.0.9", "port": 7676, "key": k}, open(f"{d}/remote.json", "w"))
        assert key(f"{d}/remote.json") == k and key(f"{d}/nope.json") is None
        json.dump({"server": "10.0.0.9", "key": "short"}, open(f"{d}/bad.json", "w"))
        assert key(f"{d}/bad.json") is None, "a key that isn't 64 hex isn't a key"
        restarts = []
        handle = lambda m: settings(m, f"{d}/conf", f"{d}/code", lambda: restarts.append(1))
        nonces = Nonces()
        listener = socket.create_server(("127.0.0.1", 0)); port = listener.getsockname()[1]

        def serve(server_key):
            conn, _ = listener.accept()
            answer(conn, server_key, handle, nonces)
        def ask(message, client_key=k, server_key=k):
            threading.Thread(target=serve, args=(server_key,), daemon=True).start()
            return request(("127.0.0.1", port), client_key, message)

        got = ask({"op": "get"})
        assert got["playlist"] == [{"page": "weather"}] and not got["own"] and got["themes"] == ["coreone", "matrix"]
        assert ask({"op": "put", "playlist": [{"page": "radar", "seconds": 20}], "off": ["matrix"]}) == {"ok": True}
        assert json.load(open(f"{d}/conf/playlist.json")) == [{"page": "radar", "seconds": 20}] and restarts
        assert os.stat(f"{d}/conf/playlist.json").st_mode & 0o777 == 0o600
        got = ask({"op": "get"})
        assert got["own"] and got["off"] == ["matrix"]
        for message, client_key, server_key, says in (
                ({"op": "get"}, wrong, k, "isn't signed"),
                ({"op": "get"}, k, None, "no key"),
                ({"op": "put", "off": ["matrix", "coreone"]}, k, k, "not all"),
                ({"op": "put", "off": ["nope"]}, k, k, "some of its"),
                ({"op": "put", "playlist": [{"page": "../etc"}]}, k, k, "page's name"),
                ({"op": "put"}, k, k, "isn't something"),
                ({"op": "rm"}, k, k, "isn't something"),
                ({"op": "control", "args": "next"}, k, k, "isn't a command"),
                ({"op": "control", "args": ["x" * 65]}, k, k, "isn't a command"),
                ({"op": "control", "args": ["rm", "-rf"]}, k, k, "usage")):
            try:
                ask(message, client_key, server_key)
            except ValueError as e:
                assert says in str(e), (says, e)
            else:
                raise AssertionError(f"accepted {message}")
        assert ask({"op": "packs", "request": {"id": "x1", "op": "install", "source": "catalog", "kind": "page", "name": "septa"}}) == {"ok": True}
        assert json.load(open(f"{d}/.config/kiosk/packs-request.json"))["name"] == "septa", \
            "it's the machine's packs.py that carries it out: beside the code, whatever HOME this kiosk's server has"
        assert not os.path.exists(f"{d}/conf/packs-request.json")
        json.dump({"state": "done", "message": "Installed septa from the catalog."}, open(f"{d}/.config/kiosk/packs-status.json", "w"))
        assert ask({"op": "get"})["status"]["state"] == "done", "and its status comes from there too"
        for bad in ({"op": "format"}, "install", {"op": "install", "name": ["x"]}):
            try:
                ask({"op": "packs", "request": bad})
            except ValueError:
                pass
            else:
                raise AssertionError(f"passed on {bad}")
        assert "present" in ask({"op": "get"}), "and it says what it has"
        # a message that's been seen, or is old, doesn't work again
        body = json.dumps({"op": "get", "t": time.time(), "nonce": "once"}).encode()
        old = json.dumps({"op": "get", "t": time.time() - WINDOW - 5, "nonce": "old"}).encode()
        for raw, ok in ((body, True), (body, False), (old, False)):
            threading.Thread(target=serve, args=(k,), daemon=True).start()
            with socket.create_connection(("127.0.0.1", port), timeout=5) as s:
                sig = sign(k, raw)
                s.sendall(HEADER.pack(b"CONF", len(sig), len(sig) + len(raw)) + sig + raw)
                _, _, n = HEADER.unpack(read(s, HEADER.size))
                assert json.loads(read(s, n))["ok"] is ok, (raw, ok)
        assert json.load(open(f"{d}/conf/playlist.json")) == [{"page": "radar", "seconds": 20}], "nothing else changed it"
        listener.close()
    print("link: ok")
