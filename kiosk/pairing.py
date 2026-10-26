#!/usr/bin/env python3
"""pairing: lets a computer pair with the kiosk using a shared key, so the Desk Kiosk widget can control it without
anyone copying SSH keys around.

The shared key is any 8 to 32 characters, picked when the kiosk is first set up (the setup page asks for it with the
new login) or set over SSH with --set. Every kiosk and every computer that should work together gets the same one.
The kiosk keeps only an scrypt of it, with its own salt, in ~/.config/kiosk/pairing.json.

Pairing (the setup page's /pair, over its HTTPS):
  GET  /pair   {"id", "salt", "n", "r", "p", "nonce"}: the kiosk's salt and scrypt settings, and a one-off nonce
  POST /pair   {"key": "ssh-ed25519 AAAA…", "name": "<computer>", "nonce", "proof"}, where proof is
               HMAC-SHA256(scrypt(shared key, salt), "wi-ki pair" NUL nonce NUL key NUL name), in hex
The shared key itself never crosses the network, a proof only works once, and it's tied to the key it brings, so
nobody watching can swap their own in. The setup page saves the key in ~/.config/kiosk/paired.json (it can't see
~/.ssh), and kiosk-pair.path runs --apply, which writes every paired key into ~/.ssh/authorized_keys locked to
control.py, the same as the control key in feed/README.md. Only the lines between its own markers are ever touched.

  pairing.py --set             (on the kiosk) read a new shared key from stdin and save it
  pairing.py --apply           (on the kiosk, kiosk-pair.service) paired.json -> authorized_keys
  pairing.py pair <address>    (on a computer) pair with the kiosk at <address>: asks for the shared key (or reads
                               KIOSK_PAIR_KEY), makes ~/.ssh/desk-kiosk-control if there isn't one, and writes
                               ~/.config/kiosk-ctl.d/<card id> (host=, setup=, pin=) for kiosk-ctl. --fingerprint
                               AB:CD:… checks the kiosk's certificate against the one on its screen; without it, the
                               first one seen is shown, then pinned, and has to match from then on.
  pairing.py find              (on a computer) the kiosks advertising themselves nearby, one JSON line each: name,
                               address, port, and the TXT record's id, server and server_port
  pairing.py --check           self-test

Standard library only: the setup page imports this on a Zero, and a computer runs it straight from the repo.
"""
import base64, hashlib, hmac, json, os, re, secrets, subprocess, sys, unicodedata

HERE = os.path.dirname(os.path.realpath(__file__))
CONF = os.path.expanduser("~/.config/kiosk")
PAIRING, PAIRED = os.path.join(CONF, "pairing.json"), os.path.join(CONF, "paired.json")
AUTHORIZED = os.path.expanduser("~/.ssh/authorized_keys")
SCRYPT = {"n": 2 ** 15, "r": 8, "p": 1}   # a few seconds on a Zero, once, when it's set; a blink on a computer
MOST = 32   # computers paired with one kiosk
BEGIN, END = "# wi-ki paired computers: begin (pairing.py rewrites these)", "# wi-ki paired computers: end"
CONTROL = f'restrict,command="python3 -I {HERE}/control.py"'
# the computer's side
KEYFILE = os.path.expanduser("~/.ssh/desk-kiosk-control")
SCREENS = os.path.expanduser("~/.config/kiosk-ctl.d")   # one file per kiosk, by card ID: host=, setup=, pin= (kiosk-ctl reads it)
SERVICE = "_wi-ki._tcp"


def shared(text):
    """the shared key as typed -> its bytes, or ValueError. NFC, so the same characters typed on two systems match."""
    text = unicodedata.normalize("NFC", text)
    if not 8 <= len(text) <= 32 or any(unicodedata.category(c).startswith("C") for c in text):
        raise ValueError("The shared key is 8 to 32 characters, with no control characters.")
    return text.encode()


def derive(text, salt, n, r, p):
    return hashlib.scrypt(shared(text), salt=bytes.fromhex(salt), n=n, r=r, p=p, maxmem=128 * 1024 * 1024, dklen=32)


def write_private(path, value):
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    fd = os.open(path + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(value if isinstance(value, str) else json.dumps(value)); f.flush(); os.fsync(f.fileno())
    os.replace(path + ".tmp", path)


def read(path, default):
    try:
        return json.load(open(path))
    except (OSError, ValueError):
        return default


def save_key(text, path=None, params=None):
    path, params = path or PAIRING, params or SCRYPT
    salt = secrets.token_hex(16)
    write_private(path, {**params, "salt": salt, "key": derive(text, salt, **params).hex()})


def stored(path=None):
    """the saved scrypt of the shared key, or None if there isn't a good one"""
    s = read(path or PAIRING, None)
    ok = isinstance(s, dict) and all(isinstance(s.get(k), int) for k in "nrp") and \
        all(isinstance(s.get(k), str) and re.fullmatch(r"[0-9a-f]+", s[k]) for k in ("salt", "key"))
    return s if ok else None


def proof(key, nonce, pubkey, name):
    return hmac.new(key, b"\0".join([b"wi-ki pair", nonce.encode(), pubkey.encode(), name.encode()]), hashlib.sha256).hexdigest()


def pubkey_ok(text):
    """only a plain ed25519 public key: the type, then exactly its 32 bytes, nothing else on the line"""
    m = re.fullmatch(r"ssh-ed25519 ([A-Za-z0-9+/]{68})", text or "")
    try:
        raw = base64.b64decode(m.group(1) + "=" * (-len(m.group(1)) % 4), validate=True) if m else b""
    except ValueError:
        return False
    return raw[:19] == b"\0\0\0\x0bssh-ed25519\0\0\0\x20" and len(raw) == 51


def name_ok(text):
    return bool(re.fullmatch(r"[A-Za-z0-9._@-]{1,40}", text or ""))


def check_pair(message, nonce_ok, path=None):
    """the setup page's POST /pair -> the entry to save, or ValueError. nonce_ok(nonce) uses the nonce up."""
    s = stored(path)
    if not s:
        raise ValueError("this kiosk has no shared key yet")
    pubkey, name, nonce, given = (message.get(k) for k in ("key", "name", "nonce", "proof"))
    if not (pubkey_ok(pubkey) and name_ok(name) and isinstance(nonce, str) and isinstance(given, str)):
        raise ValueError("that isn't a pairing request")
    if not nonce_ok(nonce):
        raise ValueError("that nonce is stale or used")
    if not hmac.compare_digest(given.encode(), proof(bytes.fromhex(s["key"]), nonce, pubkey, name).encode()):
        raise PermissionError("that isn't the shared key")
    return {"key": pubkey, "name": name}


def add(entry, path=None):
    """save a paired computer: the same key again just renames it; the oldest go once there are MOST"""
    path = path or PAIRED
    have = [e for e in read(path, []) if isinstance(e, dict) and e.get("key") != entry["key"]]
    write_private(path, (have + [entry])[-MOST:])


def apply(paired=None, authorized=None):
    """paired.json -> the lines between our markers in authorized_keys; every other line stays exactly as it was"""
    paired, authorized = paired or PAIRED, authorized or AUTHORIZED
    try:
        lines = open(authorized).read().splitlines()
    except FileNotFoundError:
        lines = []
    if BEGIN in lines and END in lines[lines.index(BEGIN):]:
        start = lines.index(BEGIN); end = lines.index(END, start)
        lines = lines[:start] + lines[end + 1:]
    keys = [f"{CONTROL} {e['key']} {e['name']}" for e in read(paired, [])
            if isinstance(e, dict) and pubkey_ok(e.get("key")) and name_ok(e.get("name"))]
    if keys:
        lines += [BEGIN, *keys, END]
    write_private(authorized, "".join(f"{line}\n" for line in lines))
    return len(keys)


def advert(cfg, remote):
    """Avahi's service file for this kiosk (autoupdate writes it to /etc/avahi/services/wi-ki.service): its setup
    page's port, its card ID, and its render server if it has one. None if it shouldn't advertise: no card ID yet,
    or setup turned off, so there's nothing to pair with."""
    cfg, remote = cfg if isinstance(cfg, dict) else {}, remote if isinstance(remote, dict) else {}
    if not re.fullmatch(r"k-[0-9a-f]{6}", str(cfg.get("id"))) or cfg.get("setup") is False:
        return None
    txt = [f"id={cfg['id']}"]
    if re.fullmatch(r"[A-Za-z0-9.-]{1,253}", str(remote.get("server", ""))):
        txt += [f"server={remote['server']}", f"server_port={int(remote.get('port', 7676))}"]
    records = "".join(f"<txt-record>{t}</txt-record>" for t in txt)
    return ('<?xml version="1.0" standalone="no"?>\n<!DOCTYPE service-group SYSTEM "avahi-service.dtd">\n'
            f'<service-group><name replace-wildcards="yes">%h</name><service><type>{SERVICE}</type><port>443</port>{records}'
            '</service></service-group>\n')


# --- the computer's side ---

def fingerprint_of(der):
    digest = hashlib.sha256(der).hexdigest().upper()
    return ":".join(digest[i:i + 2] for i in range(0, 64, 2))


def screen_files(screens=SCREENS):
    return {f: dict(line.split("=", 1) for line in open(os.path.join(screens, f)).read().splitlines() if "=" in line)
            for f in (os.listdir(screens) if os.path.isdir(screens) else [])}


def connect(address, want=None, screens=SCREENS):
    """an HTTPS connection to the kiosk's setup page, once its certificate is the one expected: `want`, or the one
    pinned when this computer paired with it before. The first time, it's shown, to check against the kiosk's screen."""
    import http.client, ssl
    ctx = ssl.create_default_context()
    ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE   # its own certificate, checked by fingerprint instead
    host, _, port = address.partition(":")
    c = http.client.HTTPSConnection(host, int(port or 443), context=ctx, timeout=30)
    c.connect()
    seen = fingerprint_of(c.sock.getpeercert(binary_form=True))
    pinned = [v.get("pin") for v in screen_files(screens).values() if v.get("setup") == f"https://{address}"]
    expected = (want or "").upper() or (pinned[0] if pinned else None)
    if expected and expected != seen:
        c.close()
        raise ValueError(f"{address}'s certificate is {seen}, not {expected}: check the fingerprint on its screen")
    return c, seen


def ask(c, method, path, body=None):
    c.request(method, path, body=json.dumps(body) if body is not None else None, headers={"Content-Type": "application/json"})
    r = c.getresponse()
    out = json.loads(r.read() or b"{}")
    if r.status != 200:
        raise ValueError(out.get("error") or f"the kiosk said {r.status}")
    return out


def own_key(path=KEYFILE):
    if not os.path.exists(path):
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "desk-kiosk-control", "-f", path], check=True)
    return " ".join(open(path + ".pub").read().split()[:2])


def pair(address, get_key, name, want=None, keyfile=KEYFILE, screens=SCREENS):
    """pair with the kiosk at address -> its card ID; writes ~/.config/kiosk-ctl.d/<card id> for kiosk-ctl.
    get_key(fingerprint) asks for the shared key once the kiosk's certificate is known, so whoever types it can check
    that against the kiosk's screen first."""
    pubkey = own_key(keyfile)
    c, pin = connect(address, want, screens)
    try:
        text = get_key(pin)
        shared(text)   # say so now if it can't be one, before telling the kiosk anything
        offer = ask(c, "GET", "/pair")
        if not re.fullmatch(r"k-[0-9a-f]{6}", str(offer.get("id"))):
            raise ValueError("that kiosk didn't say its card ID")
        key = derive(text, offer["salt"], offer["n"], offer["r"], offer["p"])
        ask(c, "POST", "/pair", {"key": pubkey, "name": name, "nonce": offer["nonce"], "proof": proof(key, offer["nonce"], pubkey, name)})
    finally:
        c.close()
    write_private(os.path.join(screens, offer["id"]), f"host=kiosk@{address.partition(':')[0]}\nsetup=https://{address}\npin={pin}\n")
    return offer["id"]


def prompt(address, pin):
    """the shared key, from KIOSK_PAIR_KEY, the terminal, or (for the widget, which has neither) a KDE password box;
    never on a command line, where anything on the computer could read it"""
    if os.environ.get("KIOSK_PAIR_KEY"):
        return os.environ["KIOSK_PAIR_KEY"]
    words = f"{address}'s certificate is\n{pin}\nCheck it matches the kiosk's screen, then type the shared key."
    if sys.stdin.isatty():
        import getpass
        print(words, file=sys.stderr)
        return getpass.getpass("Shared key: ")
    got = subprocess.run(["kdialog", "--title", "Pair with a kiosk", "--password", words], capture_output=True, text=True)
    if got.returncode:
        raise ValueError("cancelled")
    return got.stdout.rstrip("\n")


def find():
    """the kiosks advertising _wi-ki._tcp nearby (autoupdate's wi-ki.service for Avahi), IPv4 only, like the setup page"""
    out = subprocess.run(["avahi-browse", "-rpt", SERVICE], capture_output=True, text=True, timeout=15).stdout
    return list({s["address"]: s for s in map(found, out.splitlines()) if s}.values())


def found(line):
    """one line of avahi-browse -rpt -> {"name", "address", "port", plus its TXT key=values}, or None"""
    f = line.split(";")
    if len(f) < 10 or f[0] != "=" or f[2] != "IPv4" or not f[8].isdigit():
        return None
    txt = dict(t.split("=", 1) for t in re.findall(r'"([^"]*)"', ";".join(f[9:])) if "=" in t)
    return {**{k: v for k, v in txt.items() if k in ("id", "server", "server_port")}, "name": f[3], "address": f[7], "port": int(f[8])}


def check():
    import tempfile
    global SCRYPT
    real, SCRYPT = SCRYPT, {"n": 2 ** 10, "r": 8, "p": 1}   # quick for the test
    with tempfile.TemporaryDirectory() as d:
        for bad in ("short", "x" * 33, "tab\there!", ""):
            try:
                shared(bad); raise AssertionError(f"{bad!r} taken")
            except ValueError:
                pass
        assert shared("open sesame now") and shared("ñ" * 32), "spaces and any letters are fine"
        assert shared("café au lait") == shared("café au lait"), "the same characters, however they were typed"
        save_key("a shared key", f"{d}/pairing.json", SCRYPT)
        s = stored(f"{d}/pairing.json")
        assert os.stat(f"{d}/pairing.json").st_mode & 0o777 == 0o600 and "a shared key" not in open(f"{d}/pairing.json").read()
        pub = "ssh-ed25519 " + base64.b64encode(b"\0\0\0\x0bssh-ed25519\0\0\0\x20" + bytes(range(32))).decode().rstrip("=")
        assert pubkey_ok(pub) and not pubkey_ok(pub + " x") and not pubkey_ok(pub[:-1] + "!") and not pubkey_ok("ssh-rsa " + pub[12:])
        assert not pubkey_ok(pub + "\nssh-ed25519 " + pub[12:]), "one line, one key"
        assert not name_ok('a" b') and not name_ok("x" * 41) and name_ok("me@desktop")
        used = set()
        nonce_ok = lambda n: n == "n1" and n not in used and not used.add(n)
        key = derive("a shared key", s["salt"], s["n"], s["r"], s["p"])
        msg = {"key": pub, "name": "desktop", "nonce": "n1", "proof": proof(key, "n1", pub, "desktop")}
        assert stored(f"{d}/nope.json") is None
        for bad, why in (({**msg, "proof": proof(derive("a wrong key!", s["salt"], **SCRYPT), "n1", pub, "desktop")}, PermissionError),
                         ({**msg, "name": "mallory"}, PermissionError), ({**msg, "key": "ssh-rsa AAAA"}, ValueError)):
            try:
                check_pair(bad, lambda n: True, f"{d}/pairing.json"); raise AssertionError("taken")
            except why:
                pass
        assert check_pair(msg, nonce_ok, f"{d}/pairing.json") == {"key": pub, "name": "desktop"}
        try:
            check_pair(msg, nonce_ok, f"{d}/pairing.json"); raise AssertionError("a proof works twice")
        except ValueError:
            pass
        # authorized_keys: our lines between the markers, everyone else's untouched
        auth = f"{d}/ssh/authorized_keys"
        os.makedirs(f"{d}/ssh"); open(auth, "w").write("ssh-ed25519 AAAAmine me@laptop\n")
        assert apply(f"{d}/paired.json", auth) == 0 and open(auth).read() == "ssh-ed25519 AAAAmine me@laptop\n"
        add({"key": pub, "name": "desktop"}, f"{d}/paired.json"); add({"key": pub, "name": "renamed"}, f"{d}/paired.json")
        assert apply(f"{d}/paired.json", auth) == 1
        text = open(auth).read()
        assert text.startswith("ssh-ed25519 AAAAmine me@laptop\n") and f"{CONTROL} {pub} renamed\n" in text and "desktop\n" not in text
        open(auth, "a").write("ssh-ed25519 AAAAlater later@host\n")
        apply(f"{d}/paired.json", auth)
        assert open(auth).read().count(BEGIN) == 1 and "later@host" in open(auth).read(), "applying again keeps one block and other lines"
        write_private(f"{d}/paired.json", [{"key": pub + "\nssh-ed25519 AAAAevil", "name": "x"}, "junk"])
        assert apply(f"{d}/paired.json", auth) == 0 and BEGIN not in open(auth).read() and "AAAAevil" not in open(auth).read()
        assert os.stat(auth).st_mode & 0o777 == 0o600
        for i in range(MOST + 3):
            add({"key": pub[:-4] + f"{i:04d}", "name": f"c{i}"}, f"{d}/paired.json")
        assert len(read(f"{d}/paired.json", [])) == MOST, "the oldest go"
        line = '=;wlan0;IPv4;desk;_wi-ki._tcp;local;desk.local;192.168.1.50;443;"server_port=7677" "server=192.168.1.60" "id=k-1a2b3c"'
        assert found(line) == {"id": "k-1a2b3c", "server": "192.168.1.60", "server_port": "7677", "name": "desk", "address": "192.168.1.50", "port": 443}
        assert found(line.replace("IPv4", "IPv6")) is None and found("+;wlan0;IPv4;x") is None
        assert advert({"id": "k-1a2b3c", "setup": False}, {}) is None and advert({"id": None}, {}) is None and advert("junk", None) is None
        a = advert({"id": "k-1a2b3c"}, {"server": "render.local", "port": 7677})
        assert "<txt-record>id=k-1a2b3c</txt-record><txt-record>server=render.local</txt-record><txt-record>server_port=7677</txt-record>" in a
        assert "server" not in advert({"id": "k-1a2b3c"}, {"server": "<evil>"}), "only a host name goes in"
        assert fingerprint_of(b"x") == ":".join(re.findall("..", hashlib.sha256(b"x").hexdigest().upper()))
    SCRYPT = real
    print("pairing: ok")


if __name__ == "__main__":
    args = sys.argv[1:]
    if args == ["--check"]:
        check()
    elif args == ["--set"]:
        try:
            save_key(sys.stdin.readline().rstrip("\n"))
        except ValueError as e:
            sys.exit(str(e))
        print("pairing: saved the shared key")
    elif args == ["--apply"]:
        print(f"pairing: {apply()} computers paired")
    elif args == ["find"]:
        for s in find():
            print(json.dumps(s))
    elif len(args) >= 2 and args[0] == "pair":
        import socket
        want = args[args.index("--fingerprint") + 1] if "--fingerprint" in args else None
        try:
            print(f"paired with {pair(args[1], lambda pin: prompt(args[1], pin), re.sub(r'[^A-Za-z0-9._@-]', '-', f'{os.environ.get('USER', 'me')}@{socket.gethostname()}')[:40], want)}")
        except (OSError, ValueError, KeyError) as e:
            sys.exit(f"pairing: {e}")
    else:
        sys.exit(__doc__)
