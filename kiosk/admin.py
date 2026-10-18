#!/usr/bin/env python3
"""admin: the kiosk's setup page, hosted by the kiosk itself.

Two ways in, each with its own certificate:
  by name   https://k-<id>.kiosk.local (k-<id> is its card ID), with a certificate for that name that chains up to
            the kiosks' root (tls-root.pem). Not yet: there's no root in the repo until the kiosks have a CA, so for
            now this way stays off and every kiosk is set up by IP.
  by IP     https://<its address>, with a certificate the kiosk makes for itself, so the browser warns. The kiosk's
            screen shows that certificate's fingerprint, to check against the warning. On by default, behind the
            login; "setup_by_ip": false in config.json turns it off once the first login's been replaced. Before
            that (first boot, or once admin-login.json is deleted to reset a forgotten login) it's always on.

It runs on every kiosk with a screen (to show the first-boot login on), unless config.json says "setup": false, and
never on a render server. A kiosk without a card ID gets one when it starts. It only starts if config.json reads
cleanly and at least one of those ways in is good. systemd/kiosk-admin.service runs it as the kiosk user, with only
the capability to bind ports 443 and 80.

Once someone's logged in with their own login, it has the kiosk's settings: its status, its pages (on or off, how
long, in what order, and more from the catalog), its transitions and its location. They're the same files kiosk.py
reads in ~/.config/kiosk/, and a change restarts the display. A kiosk whose pages a render server draws has its
settings on the server: with the same "key" in both kiosks' remote.json, changes go to the server (link.py), and
without one they're only shown.

Logging in: until the kiosk is set up, its screen shows a user name (Kiosk-<word>) and three-word password, new every
time this starts, kept only in /run/kiosk. The first login has to replace them; the replacement is kept as an scrypt
hash in ~/.config/kiosk/admin-login.json, and only that. Every form carries a token and is only taken from this
page's own origin. Logins slow down after 5 failures, from one address and overall.

It serves HTTPS on 443 and nothing but a redirect on 80, on the kiosk's own addresses, never 0.0.0.0, not over IPv6.
Sixteen clients at a time and four from any one address, 30 s for each from connecting to its answer, 4 KB posts at
most. The log has the client's address, the method, the path (no query) and the status, nothing more.

  admin.py            run it
  admin.py --csr      make this kiosk's key (once; it never leaves the kiosk) and print a certificate request for
                      k-<id>.kiosk.local, to be signed off the kiosk; the signed certificate goes in tls/cert.pem
  admin.py --check    self-test (throwaway certificates on 127.0.0.1)
"""
import hashlib, hmac, html, importlib, ipaddress, json, os, re, secrets, socket, ssl, subprocess, sys, threading, time, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)  # -I leaves our own folder off the path

import config, link, look, packs  # noqa: E402

CONF = os.path.dirname(config.PATH)
TLS = os.path.join(CONF, "tls")
CERT, KEY = os.path.join(TLS, "cert.pem"), os.path.join(TLS, "key.pem")   # the card's certificate (with its chain) and key
CSR = os.path.join(TLS, "csr.pem")
IP_CERT, IP_KEY = os.path.join(TLS, "ip-cert.pem"), os.path.join(TLS, "ip-key.pem")   # the kiosk's own, for its addresses
ROOT = os.path.join(HERE, "tls-root.pem")   # the kiosks' root certificate, the one people choose to trust
LOGIN = os.path.join(CONF, "admin-login.json")   # the login someone set: user name and scrypt hash; none until then
SETUP = "/run/kiosk/setup.json"   # the temporary login and how to reach this page, for the kiosk's screen; RAM only
WORDS = os.path.join(HERE, "words.txt")   # the EFF short word list, 1296 words, as published: "EFF Dice-Generated Passphrases",
# Electronic Frontier Foundation, https://www.eff.org/dice, CC BY 3.0 (https://creativecommons.org/licenses/by/3.0/us/)
SCRYPT = {"n": 2 ** 15, "r": 8, "p": 3}   # measured on a Zero beside the display: about 8 s and 43 MB
CLIENTS, PER_ADDRESS, DEADLINE, BODY = 16, 4, 30, 4096   # 30 s: a login's scrypt alone is about 8 s on a busy Zero
SESSION = 30 * 60   # a session lasts half an hour since its last use
DOMAIN = "kiosk.local"
HTTPS, HTTP = 443, 80
HEADERS = {"Strict-Transport-Security": "max-age=86400", "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'",
           "X-Content-Type-Options": "nosniff", "Referrer-Policy": "same-origin", "Cache-Control": "no-store"}


def host(cfg):
    return f"{cfg['id']}.{DOMAIN}"


def context(cert, key):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(cert, key)
    return ctx


class Why(str):
    """why it won't start, said for people, with a short code for the code: off, id, missing, chain, name, key"""
    def __new__(cls, text, code):
        why = super().__new__(cls, text); why.code = code
        return why


def gate(cfg, cert=CERT, key=KEY, root=ROOT):
    """None if the setup page may be served by name, else Why not"""
    if not config.setup_on(cfg):
        return Why('setup is off ("setup": false in config.json, or no screen to show its first-boot login on)', "off")
    if not cfg["id"]:
        return Why("this kiosk has no card ID yet (config.py --id)", "id")
    for path in (root, cert, key):
        if not os.path.isfile(path):
            return Why(f"no {path}", "missing")
    chain = subprocess.run(["openssl", "verify", "-x509_strict", "-CAfile", root, "-untrusted", cert, cert],
                           capture_output=True, text=True)
    if chain.returncode:   # also out of date (or not yet in date: a Zero with no clock), either way
        return Why(f"the certificate doesn't chain up to {os.path.basename(root)}: {chain.stderr.strip()[-200:]}", "chain")
    out = subprocess.run(["openssl", "x509", "-in", cert, "-noout", "-checkend", "0", "-ext", "subjectAltName"],
                         capture_output=True, text=True)
    if out.returncode:
        return Why("the certificate has expired or won't read", "chain")
    if host(cfg) not in re.findall(r"DNS:([^,\s]+)", out.stdout):
        return Why(f"the certificate isn't for {host(cfg)}", "name")
    try:
        context(cert, key)
    except ssl.SSLError as e:
        return Why(f"the certificate and key don't go together ({e.reason})", "key")
    return None


def configured(login=LOGIN):
    """whether someone has set a login. Fails closed: a file that's there but won't read, or can't even be looked at,
    counts as set, so a damaged file can never reopen first-boot setup. Only a missing one counts as fresh."""
    try:
        os.stat(login)
    except FileNotFoundError:
        return False
    except OSError:
        return True
    return True


def by_ip(cfg, login=LOGIN):
    """whether it can be set up by IP address right now: always before its first login is replaced, and after that
    unless config.json says "setup_by_ip": false"""
    return config.setup_on(cfg) and bool(cfg["id"]) and (cfg.get("setup_by_ip") is not False or not configured(login))


def request(cfg, key=KEY, csr=CSR):
    """make the kiosk's key if it hasn't one (P-256, readable only by the kiosk user) and a certificate request for
    k-<id>.kiosk.local; -> the request's path. The key stays put: asking again makes a new request for the same key."""
    keygen(key)
    subprocess.run(["openssl", "req", "-new", "-key", key, "-subj", f"/CN={host(cfg)}",
                    "-addext", f"subjectAltName=DNS:{host(cfg)}", "-out", csr], check=True, capture_output=True)
    return csr


def keygen(key):
    os.makedirs(os.path.dirname(key), mode=0o700, exist_ok=True)
    if not os.path.exists(key):
        old = os.umask(0o077)
        try:
            subprocess.run(["openssl", "genpkey", "-algorithm", "EC", "-pkeyopt", "ec_paramgen_curve:P-256", "-out", key],
                           check=True, capture_output=True)
        finally:
            os.umask(old)


def ip_cert(addrs, cert=IP_CERT, key=IP_KEY):
    """the kiosk's own certificate for its addresses (self-signed, 30 days), made again whenever they change or it's
    about to run out; -> (cert, key). Its key is its own, never the one the card's certificate is for."""
    keygen(key)
    want = sorted(addrs)
    out = subprocess.run(["openssl", "x509", "-in", cert, "-noout", "-checkend", "86400", "-ext", "subjectAltName"],
                         capture_output=True, text=True) if os.path.exists(cert) else None
    if not out or out.returncode or sorted(re.findall(r"IP Address:([\d.]+)", out.stdout)) != want or not matches(cert, key):
        subprocess.run(["openssl", "req", "-x509", "-new", "-key", key, "-days", "30", "-subj", f"/CN={want[0]}",
                        "-addext", "subjectAltName=" + ",".join(f"IP:{a}" for a in want), "-out", cert + ".tmp"],
                       check=True, capture_output=True)
        os.replace(cert + ".tmp", cert)
    return cert, key


def matches(cert, key):
    try:
        context(cert, key); return True
    except (ssl.SSLError, OSError):
        return False


def renew_due(cert=IP_CERT):
    """whether the kiosk's own certificate runs out within a day"""
    return subprocess.run(["openssl", "x509", "-in", cert, "-noout", "-checkend", "86400"], capture_output=True,
                          timeout=10).returncode != 0


def fingerprint(cert):
    """the certificate's SHA-256 in full, as a browser's certificate viewer shows it: 32 pairs, AB:CD:..."""
    out = subprocess.run(["openssl", "x509", "-in", cert, "-noout", "-fingerprint", "-sha256"], capture_output=True, text=True,
                         timeout=10)
    shown = out.stdout.partition("=")[2].strip().upper()
    if out.returncode or not re.fullmatch(r"([0-9A-F]{2}:){31}[0-9A-F]{2}", shown):
        raise ValueError(f"can't read {os.path.basename(cert)}'s fingerprint")
    return shown


def temporary(words):
    """a fresh first-boot login: Kiosk-<Word> and three words"""
    pick = lambda: secrets.choice(words)
    return {"user": "Kiosk-" + pick().capitalize(), "password": "-".join(pick() for _ in range(3))}


def word_list(path=WORDS):
    words = [line.split()[-1] for line in open(path) if line.strip()]
    assert len(words) == len(set(words)) >= 1000, "words.txt should be the EFF short word list"
    return words


def write_private(path, value):
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    fd = os.open(path + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(value, f); f.flush(); os.fsync(f.fileno())
    os.replace(path + ".tmp", path)
    d = os.open(os.path.dirname(path), os.O_RDONLY)   # and the rename itself, so a power cut can't undo a saved login
    try:
        os.fsync(d)
    finally:
        os.close(d)


def hash_password(password, params=SCRYPT):
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, maxmem=256 * 1024 * 1024, dklen=32, **params)
    return {**params, "salt": salt.hex(), "hash": digest.hex()}


def same(a, b):
    """a constant-time comparison that can't throw: hmac.compare_digest raises on str that isn't ASCII"""
    return hmac.compare_digest(str(a).encode(), str(b).encode())


def password_ok(password, stored):
    params = {k: stored[k] for k in ("n", "r", "p")}
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(stored["salt"]), maxmem=256 * 1024 * 1024, dklen=32, **params)
    return hmac.compare_digest(digest.hex(), stored["hash"])


class Throttle:
    """after 5 failures (from one address, or from everyone together) each attempt waits twice as long as the one
    before, up to a minute. A success clears that address and the overall count, and failures are forgotten after
    FORGET seconds without another one, so the overall count can't keep everyone waiting for good."""
    FORGET = 15 * 60

    def __init__(self):
        self.lock, self.failed = threading.Lock(), {}   # who -> (failures, not before, last failure)

    def get(self, k, now):
        n, until, last = self.failed.get(k, (0, 0, 0))
        if n and now - last > self.FORGET:
            self.failed.pop(k, None); return 0, 0, 0
        return n, until, last

    def wait(self, who):
        now = time.monotonic()
        with self.lock:
            return max(0, max(self.get(k, now)[1] for k in (who, "*")) - now)

    def fail(self, who):
        now = time.monotonic()
        with self.lock:
            for k in (who, "*"):
                n = self.get(k, now)[0] + 1
                self.failed[k] = (n, now + (min(60, 2 ** (n - 5)) if n >= 5 else 0), now)

    def ok(self, who):
        with self.lock:
            self.failed.pop(who, None); self.failed.pop("*", None)


class Limits:
    """how many clients the kiosk takes at once, overall and from any one address, across all its listeners (443 and 80
    on every address share one count)"""
    def __init__(self, limit=CLIENTS, per_address=PER_ADDRESS):
        self.lock, self.by, self.free, self.per_address = threading.Lock(), {}, limit, per_address

    def take(self, who):
        with self.lock:
            if self.free <= 0 or self.by.get(who, 0) >= self.per_address:
                return False
            self.free -= 1; self.by[who] = self.by.get(who, 0) + 1
            return True

    def give(self, who):
        with self.lock:
            self.free += 1; self.by[who] -= 1
            if not self.by[who]:
                del self.by[who]


class Bounded(ThreadingHTTPServer):
    """a threaded server that takes a few clients at a time, and only a few from any one address, and drops the rest,
    so nobody can tie up every thread. Each client gets DEADLINE seconds from connecting to its answer, however slowly
    it drips its request in."""
    daemon_threads = True

    def __init__(self, addr, handler, limit=CLIENTS, per_address=PER_ADDRESS, deadline=DEADLINE, limits=None):
        super().__init__(addr, handler)
        self.limits, self.deadline = limits or Limits(limit, per_address), deadline

    def process_request(self, request, client_address):
        who = client_address[0]
        if not self.limits.take(who):
            return self.shutdown_request(request)
        try:
            super().process_request(request, client_address)
        except BaseException:   # its thread never started, so it never gives its slot back itself
            self.limits.give(who); raise

    def process_request_thread(self, request, client_address):
        def cut_off():   # time's up, whatever it's doing (it may have just hung up by itself)
            try:
                request.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        cut = threading.Timer(self.deadline, cut_off)
        cut.start()
        try:
            super().process_request_thread(request, client_address)
        except OSError:
            pass
        finally:
            cut.cancel(); self.limits.give(client_address[0])

    def handle_error(self, request, client_address):   # a client hanging up mid-handshake is normal: one line, no traceback
        print(f"admin: {client_address[0]} dropped: {type(sys.exc_info()[1]).__name__}", file=sys.stderr, flush=True)


class State:
    """what the running setup page knows: its config, its two ways in, the temporary login, and who's logged in"""
    def __init__(self, cfg, name_ctx, ip_ctx, addrs, port, temp, login=LOGIN):
        self.cfg, self.name_ctx, self.ip_ctx, self.login, self.temp = cfg, name_ctx, ip_ctx, login, temp
        suffix = "" if port == HTTPS else f":{port}"
        self.name = host(cfg) + suffix                                  # the one Host (and origin) by name
        self.ips = {a + suffix for a in addrs}                          # the Hosts by IP
        self.addrs = addrs
        self.sessions, self.lock, self.throttle, self.hashing = {}, threading.Lock(), Throttle(), threading.Lock()
        self.saving = threading.Lock()   # one settings change at a time
        self.fingerprint = None   # of the certificate it serves by IP, for the screen
        self.generation = 0       # goes up whenever the login changes; a session or a login checked before that is void

    def hosts(self, ctx, local):
        """the Hosts a connection may name, by the certificate it was given and the address it came in on: a name
        connection can't turn into an IP one or the other way round, an IP one only names the address it reached, and
        only while setting up by IP is on"""
        if ctx is self.name_ctx and self.name_ctx is not None:
            return {self.name}
        if ctx is self.ip_ctx and by_ip(self.cfg, self.login):
            return {a for a in self.ips if a.split(":")[0] == local}
        return set()

    def session(self, token):
        with self.lock:
            s = self.sessions.get(token or "")
            if not s or s["until"] < time.monotonic() or s["generation"] != self.generation:
                self.sessions.pop(token or "", None)
                return None
            s["until"] = time.monotonic() + SESSION
            return s

    def start_session(self, temporary_login, generation):
        """a new session for a login checked against `generation`; None if the login has changed since"""
        token = secrets.token_urlsafe(32)
        with self.lock:
            if generation != self.generation:
                return None
            self.sessions[token] = {"csrf": secrets.token_urlsafe(32), "temporary": temporary_login, "generation": generation,
                                    "until": time.monotonic() + SESSION}
        return token

    def end_all(self):
        """the login changed: every session, and every login checked before now, is void"""
        with self.lock:
            self.generation += 1; self.sessions.clear()


class Setup(BaseHTTPRequestHandler):
    state = None   # set by servers()
    timeout = 15   # a client that stops talking (or never finishes its TLS handshake) is dropped

    def setup(self):
        super().setup()
        if isinstance(self.connection, ssl.SSLSocket):
            self.connection.do_handshake()   # here in its own thread, not in the accept loop, so one slow client can't stall the rest

    # --- who's asking ---
    def own_host(self):
        """the Host it named, if that's one this connection may name"""
        name = re.sub(r":443$", "", (self.headers.get("Host") or "").lower())
        ctx = getattr(self.connection, "context", None)
        return name if name in self.state.hosts(ctx, self.connection.getsockname()[0]) else None

    def refuse(self):
        """None if the request can be looked at, else after answering it: headers it can't have twice, had twice;
        a length smuggled in beside chunked; a Host that isn't one this connection may name"""
        if any(len(self.headers.get_all(h) or []) > 1 for h in ("Host", "Origin", "Referer", "Content-Length", "Transfer-Encoding", "Cookie")):
            return self.reply("Some headers came twice.", code=400) or True
        if self.headers.get("Transfer-Encoding") is not None and self.headers.get("Content-Length") is not None:
            return self.reply("A length and chunked, both.", code=400) or True
        here = self.own_host()
        if not here:
            return self.reply("Not this kiosk's name.", code=421) or True
        self.here = here
        return None

    def cookie(self, name):
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == name:
                return v
        return None

    def same_origin(self, here):
        """a change only comes from this page itself: Origin (or, without one, Referer) is exactly https://<here>"""
        origin = self.headers.get("Origin")
        if origin is None:
            ref = urllib.parse.urlsplit(self.headers.get("Referer") or "")
            origin = f"{ref.scheme}://{ref.netloc}" if ref.scheme and ref.netloc else None
        return origin == f"https://{here}"

    def framing(self):
        """None if the post's length is one it can read, else after answering it"""
        length = self.headers.get("Content-Length")
        if length is None:
            return self.reply("A post needs its length.", code=411) or True
        if not re.fullmatch(r"[0-9]{1,5}", length):   # ASCII digits only: no signs, spaces, other scripts' digits
            return self.reply("That isn't a length.", code=400) or True
        if int(length) > BODY:
            return self.reply("That's more than this page ever posts.", code=413) or True
        return None

    def form(self):
        length = self.headers.get("Content-Length")
        return {k: v[0] for k, v in urllib.parse.parse_qs(self.rfile.read(int(length)).decode(errors="replace")).items()}

    # --- the pages ---
    def do_GET(self):
        if self.refuse():
            return
        path = self.path.split("?")[0]
        if path == "/up":
            return self.reply("up", kind="text/plain; charset=utf-8")
        if path == "/login":
            pre = secrets.token_urlsafe(32)   # the login form's own token, before there's a session to carry one
            return self.reply(page(self.state.cfg["id"], LOGIN_FORM.format(pre=pre, note="")), cookies={"__Host-pre": pre})
        s = self.state.session(self.cookie("__Host-kiosk"))
        if not s:
            return self.go("/login")
        if s["temporary"] and path != "/change":
            return self.go("/change")
        if path == "/change":
            return self.reply(page(self.state.cfg["id"], ("" if s["temporary"] else nav("/change")) + change_form(s)))
        if path == "/":
            return self.reply(page(self.state.cfg["id"], status_page(self.state, s["csrf"])))
        if path in SETTINGS:
            return self.reply(page(self.state.cfg["id"], SETTINGS[path](s["csrf"])))
        self.reply("Nothing here.", code=404)

    def do_POST(self):
        if self.refuse() or self.framing():
            return
        if not self.same_origin(self.here):
            return self.reply("Changes only come from this page itself.", code=403)
        fields = self.form()
        path = self.path.split("?")[0]
        if path == "/login":
            return self.log_in(fields)
        s = self.state.session(self.cookie("__Host-kiosk"))
        if not s or not same(fields.get("csrf", ""), s["csrf"]):
            return self.go("/login")
        if path == "/change":
            return self.change(fields)
        if path in SETTINGS:
            return self.settings(path, fields, s)
        if path == "/logout":
            with self.state.lock:
                self.state.sessions.pop(self.cookie("__Host-kiosk"), None)
            settled()   # the owner's done: the kiosk's screen goes back to its pages now, not in ten minutes
            return self.go("/login", cookies={"__Host-kiosk": ""})
        self.reply("Nothing here.", code=404)

    def log_in(self, fields):
        st, who = self.state, self.client_address[0]
        pre = self.cookie("__Host-pre")
        if not pre or not same(fields.get("pre", ""), pre):
            return self.reply(page(st.cfg["id"], LOGIN_FORM.format(pre=pre or "", note="That form had expired; try again.")), code=403)
        wait = st.throttle.wait(who)
        if wait:   # the overall count is deliberate: it slows a whole network guessing, at the cost of the owner waiting too
            return self.reply(f"Too many wrong logins on this kiosk (from here, or from anywhere on its network). Wait {wait:.0f} s.",
                              code=429, headers={"Retry-After": str(int(wait) + 1)})
        user, password = fields.get("user", ""), fields.get("password", "")
        if not st.hashing.acquire(blocking=False):   # one scrypt at a time on a Zero, and never while the login's changing
            return self.reply("Busy checking another login; try again in a few seconds.", code=503, headers={"Retry-After": "10"})
        try:
            generation = st.generation   # what this login is checked against
            if configured(st.login):
                temporary_login = False
                try:
                    stored = json.load(open(st.login))
                    ok = same(user, stored["user"]) & password_ok(password, stored)
                except (OSError, ValueError, KeyError, TypeError):   # a damaged login file lets nobody in (delete it over SSH)
                    print("admin: the saved login won't read", file=sys.stderr, flush=True); ok = False
            else:
                temporary_login = True
                ok = bool(st.temp) and same(user, st.temp["user"]) & same(password, st.temp["password"])
        finally:
            st.hashing.release()
        if not ok:
            st.throttle.fail(who)
            return self.reply(page(st.cfg["id"], LOGIN_FORM.format(pre=pre, note="That isn't right.")), code=403)
        st.throttle.ok(who)
        token = st.start_session(temporary_login, generation)
        if not token:   # the login changed while this one was being checked: the old one doesn't get in
            return self.reply(page(st.cfg["id"], LOGIN_FORM.format(pre=pre, note="The login was just changed; log in with the new one.")), code=403)
        return self.go("/change" if temporary_login else "/", cookies={"__Host-kiosk": token, "__Host-pre": ""})

    def change(self, fields):
        st, who, token = self.state, self.client_address[0], self.cookie("__Host-kiosk")
        user, password, again = fields.get("user", ""), fields.get("password", ""), fields.get("again", "")
        problem = ("A user name is 3 to 32 letters, digits, dots, dashes or underscores." if not re.fullmatch(r"[A-Za-z0-9._-]{3,32}", user)
                   else "The passwords don't match." if password != again
                   else "Make the password at least 12 characters." if len(password) < 12
                   else "That's the temporary password; pick your own." if st.temp and password == st.temp["password"]
                   else None)
        s = st.session(token)
        if s is None:   # it ran out (or the login changed) since do_POST looked: log in again, nothing changes
            return self.go("/login")
        if problem:
            return self.reply(page(st.cfg["id"], change_form(s, problem)), code=400)
        if not s["temporary"]:   # replacing a login someone set takes that login's password, the same as logging in
            wait = st.throttle.wait(who)
            if wait:
                return self.reply(f"Too many wrong passwords on this kiosk. Wait {wait:.0f} s.", code=429, headers={"Retry-After": str(int(wait) + 1)})
        with st.hashing:   # the whole change, one at a time: a change or a login that waited for this one finds it void
            if st.session(token) is not s:
                return self.go("/login")
            if not s["temporary"]:
                try:
                    current = password_ok(fields.get("current", ""), json.load(open(st.login)))
                except (OSError, ValueError, KeyError, TypeError):
                    current = False
                if not current:
                    st.throttle.fail(who)
                    return self.reply(page(st.cfg["id"], change_form(s, "That isn't the current password.")), code=403)
                st.throttle.ok(who)
            try:
                write_private(st.login, {"user": user, **hash_password(password)})
            except OSError as e:   # it may have been saved, or half saved (the rename done, its fsync not): fail closed
                st.end_all()
                print(f"admin: saving the new login failed ({e.strerror or e}); every session ended", file=sys.stderr, flush=True)
                return self.reply(page(st.cfg["id"], "<p>That didn't save cleanly, so everyone's been logged out. Log in again "
                                       "and check which password works.</p>"), code=500, cookies={"__Host-kiosk": ""})
            st.temp = None
            st.end_all()   # every session, and every login checked before now, is void
            ways = [f"https://{st.name}"] if st.name_ctx else []
            by_addr = bool(st.ip_ctx) and by_ip(st.cfg, st.login)
            if by_addr:
                ways += [f"https://{a}" for a in sorted(st.ips)]
            try:   # the screen stops showing the temporary login, and shows the way in from now on instead
                write_private(SETUP, screen(None, ways if by_addr else [], st.fingerprint if by_addr else None, done=ways))
            except OSError:
                pass
            fresh = st.start_session(False, st.generation) if self.here in {w[8:] for w in ways} else None
        if fresh:   # this way in still works: carry on, with a new session
            return self.go("/", cookies={"__Host-kiosk": fresh})
        return self.reply(page(st.cfg["id"], DONE.format(ways="".join(f"<li>{html.escape(w)}" for w in ways)
                                                          or "<li>over SSH: config.json's setup_by_ip, or a certificate for its name")),
                          cookies={"__Host-kiosk": ""})

    def settings(self, path, fields, s):
        """one change from the Pages, Transitions or Location form: checked, saved in one move, then the display
        restarts with it, or the render server's if it draws the pages. Not with the first-boot login, and not on a
        kiosk shown by a render server without the key to change it there."""
        st = self.state
        if s["temporary"]:
            return self.go("/change")
        if locked():
            return self.reply(page(st.cfg["id"], SETTINGS[path](s["csrf"])), code=409)
        with st.saving:
            try:
                if path == "/install":
                    send_pack(pack_form(fields))
                elif path == "/transitions":
                    save(off=change_transitions(fields, themes()))
                elif path == "/pages":
                    save(playlist=change_pages(current()["playlist"], fields, catalog(), server()))
                else:
                    save(playlist=change_location(current()["playlist"], fields, catalog()))
            except ValueError as e:
                return self.reply(page(st.cfg["id"], SETTINGS[path](s["csrf"], str(e))), code=400)
            except OSError as e:
                return self.reply(page(st.cfg["id"], SETTINGS[path](s["csrf"], f"Couldn't reach its render server: {e}")), code=502)
        return self.go(path)

    # --- answering ---
    def go(self, where, cookies=None):
        self.send_response(303); self.send_header("Location", where)
        self.cookies(cookies); self.send_header("Content-Length", "0"); self.end_headers()

    def cookies(self, cookies):
        for k, v in (cookies or {}).items():   # __Host-: only over HTTPS, only for this exact origin, so name and IP never share one
            self.send_header("Set-Cookie", f"{k}={v}; Path=/; Secure; HttpOnly; SameSite=Strict" + ("; Max-Age=0" if not v else ""))

    def reply(self, body, kind="text/html; charset=utf-8", code=200, cookies=None, headers=None):
        data = body.encode()
        self.send_response(code)
        for k, v in {**HEADERS, **(headers or {}), "Content-Type": kind, "Content-Length": str(len(data))}.items():
            self.send_header(k, v)
        self.cookies(cookies)
        self.end_headers(); self.wfile.write(data)

    def log_request(self, code="-", size="-"):   # the method, path and status only: never a query, header, form or cookie
        path = re.sub(r"[^\x21-\x7e]", "?", (getattr(self, "path", "") or "").split("?")[0][:80])   # nothing that fakes a log line
        print(f"admin: {self.address_string()} {getattr(self, 'command', '-')} {path} {code}", file=sys.stderr, flush=True)

    def log_message(self, fmt, *args):   # http.server's own complaints quote the raw request line, so they just get counted
        print(f"admin: {self.address_string()} refused a malformed request", file=sys.stderr, flush=True)


class Redirect(BaseHTTPRequestHandler):
    """port 80: nothing but a redirect to the setup page over HTTPS. Its target is one of a fixed few: by name if the
    request named the card's name, else by the address it came in on (not what the request says) if that's on"""
    state, timeout = None, 15

    def do_GET(self):
        st = self.state
        named = re.sub(r":\d+$", "", (self.headers.get("Host") or "").lower()) == host(st.cfg)
        here = self.server.server_address[0] + st.name[len(host(st.cfg)):]   # the same port suffix as the name's
        target = st.name if (named and st.name_ctx) or not (st.ip_ctx and by_ip(st.cfg, st.login)) else here
        self.send_response(301); self.send_header("Location", f"https://{target}/"); self.send_header("Content-Length", "0"); self.end_headers()

    do_POST = do_HEAD = do_PUT = do_DELETE = do_GET

    def log_message(self, *args):
        pass


def page(kiosk, body):
    """a whole setup page: the title bar, then body (its tabs and panels), then the engine's credit"""
    return f"""<!doctype html><html lang=en><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>{html.escape(kiosk)}: setup</title><style>{look.CSS}</style>
<div class=term><header><h1>WI-KI SETUP</h1><span>{html.escape(kiosk)}</span></header><main>{body}</main></div>{FOOTER}"""


# the engine's credit: the page's one link off the kiosk, which tells that site nothing
FOOTER = '<footer><a href="https://nomadsgalaxy.com" rel="noopener noreferrer">Built By NomadsGalaxy</a></footer>'


LOGIN_FORM = """<fieldset><legend>Log in</legend><p>Until you've set your own, the user name and password are on the kiosk's screen.</p>
<p class=note>{note}</p><form method=post action=/login class=go><input type=hidden name=pre value="{pre}"><label>User name<input name=user autocomplete=username></label>
<label>Password<input name=password type=password autocomplete=current-password></label><button>Log in</button></form></fieldset>"""
CHANGE_FORM = """<fieldset><legend>Your login</legend><p>{intro}</p>
<p class=note>{note}</p><form method=post action=/change class=go><input type=hidden name=csrf value="{csrf}">{current}
<label>User name<input name=user autocomplete=username></label><label>New password (12 characters or more)<input name=password type=password autocomplete=new-password></label>
<label>Again<input name=again type=password autocomplete=new-password></label><button>Save</button></form></fieldset>"""
DONE = """<fieldset><legend>Saved</legend><p>Saved. Setting it up by IP address was only for the first login, so this connection is finished.
From now on, log in at:</p><ul>{ways}</ul></fieldset>"""
def screen(temp, addresses, fingerprint, done=None):
    """what the kiosk's own screen shows about its setup page (pages/setup): the first-boot login while there is one,
    where to log in once it's set up, and, while it can be reached by IP, the addresses and the fingerprint of the
    certificate served there. Never a password but the first-boot one."""
    out = {**(temp or {}), "addresses": addresses, "fingerprint": fingerprint}
    if done is not None:
        out.update(done=True, next=done)
    return out


def settled(path=None):
    """take "it's set up, log in here" off the kiosk's screen, keeping where to log in and the fingerprint (which only
    show for a moment each time round). Not while there's a first-boot login to show; anything that won't read is
    left as it is."""
    path = path or SETUP
    try:
        info = json.load(open(path))
        if isinstance(info, dict) and info.get("done") and not info.get("user"):
            write_private(path, {k: v for k, v in info.items() if k not in ("done", "next")})
    except (OSError, ValueError):
        pass


def change_form(s, note=""):
    if s["temporary"]:
        intro, current = "Now pick your own user name and password. The ones on the screen stop working, and the screen stops showing them.", ""
    else:
        intro, current = "A new user name and password for this kiosk's setup page.", \
            "<label>Current password<input name=current type=password autocomplete=current-password></label>"
    return CHANGE_FORM.format(intro=intro, current=current, csrf=s["csrf"], note=html.escape(note))


# --- the settings: the same files kiosk.py reads, beside config.json in ~/.config/kiosk/ ---
PLAYLIST = os.path.join(CONF, "playlist.json")          # the kiosk's own playlist; the repo's until it has one
REPO_PLAYLIST = os.path.join(HERE, "playlist.json")
OFF = os.path.join(CONF, "transitions-off.json")        # the transitions it skips
REMOTE = os.path.join(CONF, "remote.json")              # its render server, if it has one (set over SSH, not here)
CACHE = os.path.expanduser("~/.cache/kiosk")            # what autoupdate applied, and the page showing
CATALOG = [os.path.join(HERE, "entries"), os.path.join(HERE, "..", "catalog", "entries")]          # on a kiosk, in the repo
THEMES = [os.path.join(HERE, "transitions"), os.path.join(HERE, "..", "catalog", "transitions")]


def restart():
    """the display picks up its new settings when it starts: the Pi's login loop brings it back in 3 s"""
    subprocess.run(["pkill", "-f", f"(^|/)python3 -I {HERE}/kiosk.py"], capture_output=True, timeout=10)


def catalog():
    """the catalog's entries, by name: what each page and transition is, what it needs, and what it takes"""
    out = {}
    for d in CATALOG:
        if os.path.isdir(d):
            for f in sorted(os.listdir(d)):
                try:
                    e = json.load(open(os.path.join(d, f)))
                    out.setdefault(e["name"], e)
                except (OSError, ValueError, KeyError, TypeError):
                    pass
    return out


def themes():
    names = set()
    for d in THEMES:
        if os.path.isdir(d):
            names |= {f[:-3] for f in os.listdir(d) if f.endswith(".py") and f not in ("__init__.py", "canvas.py")}
    return sorted(names)


def server():
    """the render server it shows, or None if it draws its own pages"""
    try:
        return json.load(open(REMOTE)).get("server") or None
    except (OSError, ValueError, AttributeError):
        return None


def linked():
    """(the render server's address, the shared key) when this kiosk's settings are kept on its server and both have
    the key in remote.json; None otherwise"""
    try:
        r = json.load(open(REMOTE))
        address = (r["server"], int(r.get("port", 7676)))
    except (OSError, ValueError, AttributeError, KeyError, TypeError):
        return None
    k = link.key(REMOTE)
    return (address, k) if k else None


def locked():
    """a kiosk whose pages a render server draws, without the key to change them there: it only shows its settings"""
    return bool(server()) and not linked()


def current():
    """the settings the display runs -> {"playlist", "own", "off"}: from its render server when that's where they're
    kept, else from this kiosk's files. Raises OSError or ValueError if the server can't be asked."""
    to = linked() if server() else None
    if to:
        got = link.request(*to, {"op": "get"})
        return {"playlist": config.validate_playlist(got["playlist"]), "own": bool(got["own"]),
                "off": [n for n in got["off"] if isinstance(n, str)]}
    playlist, own = [], False
    for path, mine in ((PLAYLIST, True), (REPO_PLAYLIST, False)):
        try:
            playlist, own = config.validate_playlist(json.load(open(path))), mine
            break
        except (OSError, ValueError):
            pass
    try:
        off = json.load(open(OFF))
    except (OSError, ValueError):
        off = []
    return {"playlist": playlist, "own": own,
            "off": sorted({n for n in off if isinstance(n, str)}) if isinstance(off, list) else []}


def save(playlist=None, off=None):
    """save new settings where they're kept: on the render server (which restarts its own display), or here, then
    restart this display"""
    to = linked() if server() else None
    if to:
        link.request(*to, {"op": "put", **({"playlist": playlist} if playlist is not None else {}),
                           **({"off": off} if off is not None else {})})
        return
    if playlist is not None:
        write_private(PLAYLIST, playlist)
    if off is not None:
        write_private(OFF, off)
    restart()


def unusable(entry, drawn_by):
    """why a catalog page can't go in this kiosk's playlist, or None if it can"""
    if entry.get("kind") != "page":
        return "it's a transition"
    if "bar" not in entry.get("shapes", ["bar"]):
        return "it isn't drawn for the bar"
    if entry.get("needs", {}).get("render") == "server" and not drawn_by:
        return "it needs a render server"
    return None


def change_pages(entries, form, known, drawn_by=None):
    """the playlist after one change from the Pages form -> a new list, or ValueError saying what's wrong. known is the
    catalog, so only a real page can be added."""
    out = [dict(e) for e in entries]
    action = form.get("action", "")
    if action == "add":
        name = form.get("page", "")
        if name not in known or unusable(known[name], drawn_by):
            raise ValueError("That isn't a page this kiosk can show.")
        out.append({"page": name})
        return config.validate_playlist(out)
    try:
        i = int(form.get("i", ""))
    except ValueError:
        raise ValueError("Which page?") from None
    if not 0 <= i < len(out):
        raise ValueError("Which page?")
    if action in ("on", "off"):
        out[i]["on"] = action == "on"
        if out[i]["on"]:
            out[i].pop("on")
    elif action == "seconds":
        if not re.fullmatch(r"[0-9]{1,4}", form.get("seconds", "")) or not 1 <= int(form["seconds"]) <= 3600:
            raise ValueError("Seconds are a whole number from 1 to 3600.")
        out[i]["seconds"] = int(form["seconds"])
    elif action == "up" and i > 0:
        out[i - 1], out[i] = out[i], out[i - 1]
    elif action == "down" and i < len(out) - 1:
        out[i + 1], out[i] = out[i], out[i + 1]
    elif action == "remove":
        out.pop(i)
    elif action not in ("up", "down"):
        raise ValueError("That isn't something this page does.")
    if out and not any(e.get("on", True) for e in out):
        raise ValueError("Keep at least one page on, or the screen has nothing to show.")
    return config.validate_playlist(out)


def change_location(entries, form, known):
    """the playlist with every page that takes a location set to this one -> a new list, or ValueError"""
    try:
        lat, lon = float(form.get("lat", "")), float(form.get("lon", ""))
    except ValueError:
        raise ValueError("Latitude and longitude are numbers, like 39.95 and -75.17.") from None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("Latitude is -90 to 90 and longitude -180 to 180.")
    place = form.get("place", "").strip().upper()
    if place and not re.fullmatch(r"[A-Z0-9 .,'-]{1,24}", place):
        raise ValueError("The place is up to 24 letters, digits, spaces and . , ' -")
    out = []
    for e in entries:
        e, takes = dict(e), known.get(e["page"], {}).get("settings", {})
        if "lat" in takes and "lon" in takes:
            e["options"] = {**e.get("options", {}), "lat": round(lat, 4), "lon": round(lon, 4)}
            if place and "place" in takes:
                e["options"]["place"] = place
        out.append(e)
    return config.validate_playlist(out)


def change_transitions(form, names):
    """-> the transitions to skip, from the boxes left unticked; all of them off means none are, so that's refused"""
    off = [n for n in names if form.get(f"t_{n}") != "on"]
    if names and len(off) == len(names):
        raise ValueError("Leave at least one transition on.")
    return off



TABS = [("/", "Status"), ("/pages", "Pages"), ("/transitions", "Transitions"), ("/install", "Install"),
        ("/location", "Location"), ("/change", "Login")]


def nav(here=None):
    """the tabs, the one being shown marked as such"""
    return "<nav>" + "".join(f'<a href={path}{" aria-current=page" if path == here else ""}>{name}</a>'
                             for path, name in TABS) + "</nav>"


NAV = nav()


def logout(csrf):
    return f'<form method=post action=/logout><input type=hidden name=csrf value="{csrf}"><button>log out</button></form>'


def elsewhere(drawn_by):
    """the note for a kiosk whose pages come from a render server: changed there, or only shown without the key"""
    if not locked():
        return f"<p>This kiosk's pages are drawn by its render server, {html.escape(drawn_by)}. Changes here go to it.</p>"
    return (f"<p class=note>This kiosk shows pages drawn by its render server, {html.escape(drawn_by)}, so its pages, "
            "transitions and location are set on the server. To change them from here, give this kiosk and its "
            "server the same \"key\" in remote.json. What it's set to is below.</p>")


def unreachable(title, e):
    here = next((path for path, name in TABS if name == title), None)
    return nav(here) + look.panel(title, f"<p class=note>Couldn't reach its render server ({html.escape(str(e))}), so "
                                         "there's nothing to show here right now.</p>")


def status_page(st, csrf):
    applied = read_text(os.path.join(CACHE, "applied-commit"))[:7] or "not by autoupdate yet"
    drawn_by = server()
    try:
        now = current()
    except (OSError, ValueError):
        now = {"playlist": [], "own": True, "off": []}
    entries, own = now["playlist"], now["own"]
    on = [e["page"] for e in entries if e.get("on", True)] or ["(couldn't reach its render server)"]
    rows = [("Card", st.cfg["id"]), ("Name", socket.gethostname()), ("Addresses", ", ".join(st.addrs)),
            ("Code", applied), ("Pages drawn by", drawn_by or "this kiosk"),
            ("Showing", "" if drawn_by else read_text(os.path.join(CACHE, "showing"))),
            ("Playlist", ", ".join(on) + ("" if own else " (the repo's)")),
            ("Transitions off", ", ".join(now["off"]) or "none"),
            ("Setup by IP", "on" if by_ip(st.cfg, st.login) else "off")]
    table = "".join(f"<tr><th>{html.escape(k)}<td>{html.escape(v)}" for k, v in rows if v)
    return nav("/") + look.panel("Status", f"<table>{table}</table>{logout(csrf)}")


def read_text(path):
    try:
        return open(path).read().strip()
    except OSError:
        return ""


def button(csrf, action, label, i=None, extra="", danger=False):
    hidden = f'<input type=hidden name=i value="{i}">' if i is not None else ""
    return (f'<form method=post action=/pages class=inline><input type=hidden name=csrf value="{csrf}">'
            f'<input type=hidden name=action value="{action}">{hidden}{extra}<button{" class=danger" if danger else ""}>'
            f'{label}</button></form>')


def pages_page(csrf, note=""):
    try:
        now = current()
    except (OSError, ValueError) as e:
        return unreachable("Pages", e)
    drawn_by, entries, own, known, ro = server(), now["playlist"], now["own"], catalog(), locked()
    rows = []
    for i, e in enumerate(entries):
        on = e.get("on", True)
        about = known.get(e["page"], {}).get("about", "")
        seconds = (f'<form method=post action=/pages class=inline><input type=hidden name=csrf value="{csrf}">'
                   f'<input type=hidden name=action value=seconds><input type=hidden name=i value="{i}">'
                   f'<label>seconds <input name=seconds inputmode=numeric value="{html.escape(str(e.get("seconds", "")))}" '
                   f'placeholder=own></label><button>set</button></form>')
        controls = "" if ro else (button(csrf, "off" if on else "on", "turn off" if on else "turn on", i) +
                                  button(csrf, "up", "↑ up", i) + button(csrf, "down", "↓ down", i) +
                                  button(csrf, "remove", "remove", i, danger=True) + seconds)
        rows.append(f"<li class='item {'on' if on else 'off'}'><span class=n>{i + 1:02}</span>"
                    f"<span class=name>{html.escape(e['page'])}</span><span class=tag>{'ON' if on else 'OFF'}</span>"
                    f"<small>{html.escape(about)}</small><div class=actions>{controls}</div>")
    adds = []
    for name, entry in sorted(known.items()):
        if entry.get("kind") != "page" or any(e["page"] == name for e in entries):
            continue
        why = unusable(entry, drawn_by)
        adds.append(f"<li class='item bare'><span class=name>{html.escape(name)}</span><span></span>"
                    f"<small>{html.escape(entry.get('about', ''))}</small><div class=actions>" +
                    (f"<small class=note>Can't: {html.escape(why)}</small>" if why else
                     "" if ro else button(csrf, "add", "add", extra=f'<input type=hidden name=page value="{html.escape(name)}">'))
                    + "</div>")
    return (nav("/pages") + (elsewhere(drawn_by) if drawn_by else "") + f"<p class=note>{html.escape(note)}</p>"
            + look.panel("Playlist", f"<p>{'This kiosk has its own playlist.' if own else 'It runs the repo playlist until you change something here.'}"
                                     f" A page with no seconds set stays up for its own time.</p><ol>{''.join(rows)}</ol>")
            + look.panel("More pages", f"<ul>{''.join(adds) or '<li>Every page is in the playlist.'}</ul>"))


def transitions_page(csrf, note=""):
    try:
        off = set(current()["off"])
    except (OSError, ValueError) as e:
        return unreachable("Transitions", e)
    drawn_by, known, ro = server(), catalog(), locked()
    boxes = "".join(f'<label class=check><input type=checkbox name="t_{n}" value=on{"" if n in off else " checked"}'
                    f'{" disabled" if ro else ""}> <b>{html.escape(n)}</b> '
                    f'<small>{html.escape(known.get(n, {}).get("about", ""))}</small></label>' for n in themes())
    save = "" if ro else f'<input type=hidden name=csrf value="{csrf}"><button>save</button>'
    return (nav("/transitions") + (elsewhere(drawn_by) if drawn_by else "") + f"<p class=note>{html.escape(note)}</p>"
            + look.panel("Transitions", f"<p>Between pages, these take turns. Untick one to skip it.</p>"
                                        f"<form method=post action=/transitions class=go>{boxes}{save}</form>"))


def location_page(csrf, note=""):
    try:
        entries = current()["playlist"]
    except (OSError, ValueError) as e:
        return unreachable("Location", e)
    drawn_by, known, ro = server(), catalog(), locked()
    takers = [e for e in entries if {"lat", "lon"} <= set(known.get(e["page"], {}).get("settings", {}))]
    now = next((e.get("options", {}) for e in takers if "lat" in e.get("options", {})), {})
    names = ", ".join(sorted({e["page"] for e in takers})) or "none of its pages"
    field = lambda k, label: (f'<label>{label}<input name={k} value="{html.escape(str(now.get(k, "")))}"'
                              f'{" inputmode=decimal" if k in ("lat", "lon") else ""}{" disabled" if ro else ""}></label>')
    save = "" if ro else f'<input type=hidden name=csrf value="{csrf}"><button>save</button>'
    return (nav("/location") + (elsewhere(drawn_by) if drawn_by else "") + f"<p class=note>{html.escape(note)}</p>"
            + look.panel("Location", f"<p>Where it is, for {html.escape(names)}. A page with no location set uses its own default.</p>"
                                     f"<form method=post action=/location class=go>{field('lat', 'Latitude')}{field('lon', 'Longitude')}"
                                     f"{field('place', 'Place, for the weather heading')}{save}</form>"))


PACKS_REQUEST, PACKS_STATUS = os.path.join(CONF, packs.REQUEST), os.path.join(CONF, packs.STATUS)
PRESENT = link.present   # what's installed here; the self-test swaps it


def pack_state():
    """what's installed where the pages run -> {"present": {"pages", "transitions"}, "packs": {...}, "status": {...}}"""
    to = linked() if server() else None
    if to:
        got = link.request(*to, {"op": "get"})
        return {k: got.get(k) or {} for k in ("present", "packs", "status")}
    read = lambda path: packs.read_json(path, {})
    return {"present": PRESENT(HERE), "packs": read(os.path.join(CONF, "packs.json")), "status": read(PACKS_STATUS)}


def pack_form(fields):
    """the Install page's form -> a request for packs.py, checked here and again by packs.py, or ValueError"""
    action, kind, name = fields.get("action"), fields.get("kind"), fields.get("name", "")
    named = lambda: kind in packs.KINDS and packs.NAME.fullmatch(name)
    if action == "catalog" and named():
        req = {"op": "install", "source": "catalog", "kind": kind, "name": name}
    elif action == "remove" and named():
        req = {"op": "remove", "kind": kind, "name": name}
    elif action == "update" and packs.NAME.fullmatch(name):
        req = {"op": "update", "name": name}
    elif action == "check":
        req = {"op": "check"}
    elif action == "repo":
        if fields.get("agree") != "on":
            raise ValueError("Tick the box first: it's code nobody has reviewed, and it runs on the kiosk.")
        owner, repo = packs.github(fields.get("repo", ""))
        ref = fields.get("ref", "").strip()
        if ref and (not re.fullmatch(r"[A-Za-z0-9._/-]{1,100}", ref) or ".." in ref):
            raise ValueError("That isn't a branch, tag or commit.")
        req = {"op": "install", "source": "repo", "repo": f"https://github.com/{owner}/{repo}", **({"ref": ref} if ref else {})}
    else:
        raise ValueError("That isn't something this page does.")
    return {"id": secrets.token_hex(8), **req}


def send_pack(req):
    """to where it's carried out: this kiosk's packs.py, and on a render server's kiosk the server's too (pages run
    there, and transitions on both)"""
    to = linked() if server() else None
    if to:
        link.request(*to, {"op": "packs", "request": req})
    write_private(PACKS_REQUEST, req)


def install_page(csrf, note=""):
    try:
        state = pack_state()
    except (OSError, ValueError) as e:
        return unreachable("Install", e)
    drawn_by, ro, known = server(), locked(), catalog()
    have = {k: set(state["present"].get(k, [])) for k in ("pages", "transitions")}
    playing, core_names = {e["page"] for e in current()["playlist"]} if not ro else set(), packs.core(HERE)
    status, mine = state["status"], state["packs"]
    form = lambda action, label, **hidden: "" if ro else (
        f'<form method=post action=/install class=inline><input type=hidden name=csrf value="{csrf}">'
        f'<input type=hidden name=action value="{action}">' +
        "".join(f'<input type=hidden name={k} value="{html.escape(str(v))}">' for k, v in hidden.items()) +
        f'<button{" class=danger" if action == "remove" else ""}>{label}</button></form>')
    banner = ""
    if os.path.exists(PACKS_REQUEST) or status.get("state") == "working":
        banner = '<meta http-equiv=refresh content=5><p class=note>Working on it. This page checks again every few seconds.</p>'
    elif status.get("message"):
        banner = f"<p class=note>Last time: {html.escape(status['message'])}</p>"
    sections = []
    for kind, folder, title in (("page", "pages", "Pages"), ("transition", "transitions", "Transitions")):
        rows = []
        for name, entry in sorted(known.items()):
            if entry.get("kind") != kind:
                continue
            about = html.escape(entry.get("about", ""))[:160]
            installed = name in have[folder]
            if installed:
                why = ("comes with every kiosk" if name in core_names[folder] else "in the playlist" if name in playing else "")
                action = f"<small>Installed{', ' + why if why else ''}.</small>" + ("" if why else " " + form("remove", "remove", kind=kind, name=name))
            else:
                action = form("catalog", "install", kind=kind, name=name)
            rows.append(f"<li class='item bare {'on' if installed else 'off'}'><span class=name>{html.escape(name)}</span>"
                        f"<span class=tag>{'INSTALLED' if installed else ''}</span><small>{about}</small>"
                        f"<div class=actions>{action}</div>")
        sections.append(look.panel(f"{title} from the catalog", f"<ul>{''.join(rows)}</ul>"))
    updates = status.get("updates") or {}
    repo_rows = "".join(
        f"<li class='item bare'><span class=name>{html.escape(n)}</span><span class=tag>INSTALLED</span><small>a "
        f"{html.escape(p.get('kind', '?'))} from {html.escape(p.get('repo', '?'))} at {html.escape(p.get('commit', '')[:7])}"
        f"</small><div class=actions>"
        + (form("update", f"update to {html.escape(updates[n][:7])}", name=n) if n in updates else "")
        + form("remove", "remove", kind=p.get("kind", "page"), name=n) + "</div>" for n, p in sorted(mine.items()))
    repo_form = "" if ro else f"""<form method=post action=/install class=go><input type=hidden name=csrf value="{csrf}">
<input type=hidden name=action value=repo><label>GitHub repo<input name=repo placeholder="https://github.com/someone/their-page"></label>
<label>Branch, tag or commit (optional)<input name=ref placeholder="the default branch"></label>
<label class=check><input type=checkbox name=agree value=on> I understand nobody has reviewed this code, and it runs on the kiosk
with the kiosk's access: only install from someone you trust.</label><button>Install from the repo</button></form>"""
    return (nav("/install") + (elsewhere(drawn_by) if drawn_by else "") + banner + f"<p class=note>{html.escape(note)}</p>"
            + "<p>Everything in the catalog has been reviewed. Installing restarts the display.</p>" + "".join(sections)
            + look.panel("From a repo", f"<ul>{repo_rows or '<li>Nothing yet.'}</ul>"
                                        f"{form('check', 'check for updates') if mine else ''}{repo_form}"))


SETTINGS = {"/pages": pages_page, "/transitions": transitions_page, "/location": location_page, "/install": install_page}


def servers(cfg, addrs, ctx, https=HTTPS, http=HTTP, limit=CLIENTS, per_address=PER_ADDRESS, deadline=DEADLINE,
            ip_ctx=None, temp=None, login=LOGIN):
    """-> the HTTPS and redirect servers, bound to addrs (never a wildcard); their State is .RequestHandlerClass.state.
    ctx is the name's certificate (None if it isn't good), ip_ctx the kiosk's own for its addresses (None if setting
    up by IP is off). A connection that asks for exactly the card's name gets ctx; one that asks for no name (a bare
    address) gets ip_ctx; any other name, or a way in that's off, has its handshake refused. The limits are shared by
    every listener. If any of them won't bind, this raises and the process exits, so port 80 is never left up alone."""
    if not addrs:
        raise ValueError("no addresses")
    for a in addrs:   # a real check, not an assert (python -O drops those), and not a list of spellings
        if ipaddress.ip_address(a).is_unspecified:   # "0", "::0" and the like don't parse or are unspecified: both raise
            raise ValueError(f"{a} is every address")
    if not (ctx or ip_ctx):
        raise ValueError("neither way in is good")
    state = State(cfg, ctx, ip_ctx, addrs, https, temp, login)
    shared = Limits(limit, per_address)
    first = ip_ctx or ctx

    def pick(sock, name, _):
        if name is None and ip_ctx:
            sock.context = ip_ctx
        elif name == host(cfg) and ctx:
            sock.context = ctx
        else:
            return ssl.ALERT_DESCRIPTION_UNRECOGNIZED_NAME
    first.sni_callback = pick
    handler = type("Handler", (Setup,), {"state": state})
    redirect = type("Redirect", (Redirect,), {"state": state})
    out = []
    for a in addrs:
        s = Bounded((a, https), handler, deadline=deadline, limits=shared)
        s.socket = first.wrap_socket(s.socket, server_side=True, do_handshake_on_connect=False)
        out += [s, Bounded((a, http), redirect, deadline=deadline, limits=shared)]
    return out


def addresses():
    """the kiosk's own IPv4 addresses: its network, and the rescue hotspot's while that's up. Never 0.0.0.0."""
    out = subprocess.run(["ip", "-4", "-o", "addr", "show", "scope", "global"], capture_output=True, text=True, timeout=10).stdout
    return sorted(set(re.findall(r"\binet (\d+\.\d+\.\d+\.\d+)/", out)))


def clock_set():
    out = subprocess.run(["timedatectl", "show", "-p", "NTPSynchronized", "--value"], capture_output=True, text=True, timeout=10)
    return out.stdout.strip() == "yes"


def main():
    try:
        return run()
    except (subprocess.TimeoutExpired, OSError, ValueError) as e:   # a stuck tool, an address gone before it could bind,
        print(f"admin: stopping to start again: {type(e).__name__}: {e}", flush=True)   # a fingerprint that won't read
        return 1


def run():
    try:
        cfg = config.load()
    except ValueError as e:   # the display falls back to its defaults; the setup page doesn't start at all
        print(f"admin: not starting: config.json: {e}", flush=True)
        return 0
    if config.setup_on(cfg) and not cfg["id"]:   # a card made before IDs gets one now, and keeps it
        cfg = {**cfg, "id": config.card_id()}
    why, ip = gate(cfg), by_ip(cfg)
    if why and not ip:
        print(f"admin: not starting: {why}", flush=True)
        if why.code == "chain" and not clock_set():   # a Zero has no clock of its own: "not yet valid" may only mean that
            return 1   # come back once the time's been set
        return 0   # a refusal isn't a failure: systemd leaves it off rather than retrying
    addrs = addresses()
    if not addrs:
        print("admin: no network address yet", flush=True)
        return 1
    temp = None
    if not configured():
        try:
            temp = temporary(word_list())
        except (OSError, AssertionError) as e:
            print(f"admin: not starting: can't make a first-boot login ({e})", flush=True)
            return 0
    ip_ctx = context(*ip_cert(addrs)) if ip else None
    live = servers(cfg, addrs, None if why else context(CERT, KEY), ip_ctx=ip_ctx, temp=temp)
    state = live[0].RequestHandlerClass.state
    state.fingerprint = fingerprint(IP_CERT) if ip else None   # of the very certificate being served
    if temp or ip:   # for the kiosk's own screen, and nowhere else: by IP its fingerprint is always there to check against
        write_private(SETUP, screen(temp, [f"https://{a}" for a in addrs] + ([] if why else [f"https://{host(cfg)}"]), state.fingerprint))
    for s in live:
        threading.Thread(target=s.serve_forever, daemon=True).start()
    print(f"admin: up on {', '.join(addrs)}" + ("" if why else f" as https://{host(cfg)}") + (" (and by IP)" if ip else ""), flush=True)
    code = os.path.getmtime(os.path.realpath(__file__))
    while True:   # the addresses moved (new DHCP lease, hotspot up or down) or the code was updated: systemd restarts it
        time.sleep(30)
        try:
            moved = addresses() != addrs or os.path.getmtime(os.path.realpath(__file__)) != code or (ip and renew_due())
        except (subprocess.TimeoutExpired, OSError):   # a stuck check counts as a change: start again rather than hang
            moved = True
        if moved:
            print("admin: restarting for a new address, new code or a new certificate", flush=True)
            state.hashing.acquire(timeout=120)   # let a login change in progress finish its save first; never let go
            return 1


def settings_check():
    known = {"weather": {"kind": "page", "settings": {"lat": 0, "lon": 0, "place": ""}},
             "radar": {"kind": "page", "settings": {"lat": 0, "lon": 0}}, "clock": {"kind": "page"},
             "wide": {"kind": "page", "shapes": ["16-9"]}, "big": {"kind": "page", "needs": {"render": "server"}}}
    three = [{"page": "weather"}, {"page": "radar", "seconds": 20}, {"page": "clock"}]
    pages = lambda form, drawn_by=None: [e["page"] for e in change_pages(three, form, known, drawn_by)]
    assert pages({"action": "up", "i": "1"}) == ["radar", "weather", "clock"]
    assert pages({"action": "up", "i": "0"}) == pages({"action": "down", "i": "2"}) == ["weather", "radar", "clock"], "ends stay put"
    assert pages({"action": "remove", "i": "2"}) == ["weather", "radar"] and three[2] == {"page": "clock"}, "a copy, not the original"
    assert change_pages(three, {"action": "seconds", "i": "0", "seconds": "64"}, known)[0] == {"page": "weather", "seconds": 64}
    assert change_pages([{"page": "clock", "on": False}], {"action": "on", "i": "0"}, known) == [{"page": "clock"}]
    assert pages({"action": "add", "page": "big"}, "10.0.0.9")[-1] == "big", "with a render server it can"
    for bad in ({"action": "seconds", "i": "0", "seconds": s} for s in ("0", "3601", "1.5", "-1", "x", "", "٣")):
        try:
            change_pages(three, bad, known)
        except ValueError:
            pass
        else:
            raise AssertionError(bad)
    for bad in ({"action": "add", "page": n} for n in ("wide", "big", "../etc", "")):
        try:
            change_pages(three, bad, known)
        except ValueError:
            pass
        else:
            raise AssertionError(bad)
    where = change_location(three, {"lat": "39.704", "lon": "-75.241", "place": "Mullica Hill"}, known)
    assert [e.get("options") for e in where] == [{"lat": 39.704, "lon": -75.241, "place": "MULLICA HILL"},
                                                 {"lat": 39.704, "lon": -75.241}, None], "only pages that take it"
    for bad in ({"lat": "91", "lon": "0"}, {"lat": "0", "lon": "181"}, {"lat": "x", "lon": "0"}, {"lat": "nan", "lon": "0"},
                {"lat": "0", "lon": "0", "place": "<script>"}, {"lat": "0", "lon": "0", "place": "A" * 25}):
        try:
            change_location(three, bad, known)
        except ValueError:
            pass
        else:
            raise AssertionError(bad)
    assert change_transitions({"t_matrix": "on"}, ["coreone", "matrix"]) == ["coreone"]
    try:   # only "on" ticks a box, so this leaves both off, and that's refused
        change_transitions({"t_matrix": "yes"}, ["coreone", "matrix"])
    except ValueError:
        pass
    else:
        raise AssertionError("every transition off")


def check():
    import contextlib, http.client, io, tempfile
    global SCRYPT, SETUP, PLAYLIST, REPO_PLAYLIST, OFF, REMOTE, CATALOG, THEMES, CACHE, restart, PACKS_REQUEST, PACKS_STATUS, PRESENT
    saved, settings_saved = (SCRYPT, SETUP), (PLAYLIST, REPO_PLAYLIST, OFF, REMOTE, CATALOG, THEMES, CACHE, restart, PACKS_REQUEST, PACKS_STATUS, PRESENT)
    SCRYPT = {"n": 2 ** 10, "r": 8, "p": 1}   # quick for the test; the real ones are measured on a Zero
    settings_check()
    with tempfile.TemporaryDirectory() as d:
        SETUP = f"{d}/run/setup.json"
        # the settings' files, and a small catalog: two pages that take a location, one that needs a render server,
        # and two transitions
        PLAYLIST, REPO_PLAYLIST, OFF, REMOTE = (f"{d}/conf/{n}.json" for n in ("playlist", "repo", "off", "remote"))
        CATALOG, THEMES, CACHE = [f"{d}/entries"], [f"{d}/themes"], f"{d}/cache"
        os.makedirs(f"{d}/conf"); os.makedirs(f"{d}/entries"); os.makedirs(f"{d}/themes")
        where = {"lat": None, "lon": None, "place": "PHILADELPHIA"}
        for e in ({"name": "weather", "kind": "page", "about": "the <b>weather</b>", "settings": where},
                  {"name": "sky", "kind": "page", "about": "a sky", "settings": where},
                  {"name": "big", "kind": "page", "about": "a big one", "needs": {"render": "server"}},
                  {"name": "rain", "kind": "transition", "about": "rain"}):
            json.dump(e, open(f"{d}/entries/{e['name']}.json", "w"))
        for t in ("rain", "snow"):
            open(f"{d}/themes/{t}.py", "w").write("")
        json.dump([{"page": "weather"}], open(REPO_PLAYLIST, "w"))
        restarts = []
        restart = lambda: restarts.append(1)
        PACKS_REQUEST, PACKS_STATUS = f"{d}/conf/packs-request.json", f"{d}/conf/packs-status.json"
        PRESENT = lambda here: {"pages": ["weather"], "transitions": ["rain"]}

        def make(name, cn):
            subprocess.run(["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256", "-nodes",
                            "-keyout", f"{d}/{name}.key", "-out", f"{d}/{name}.pem", "-days", "2", "-subj", f"/CN={cn}",
                            "-addext", f"subjectAltName=DNS:{cn}"], check=True, capture_output=True)
            return f"{d}/{name}.pem", f"{d}/{name}.key"
        mine = f"{d}/tls/key.pem"
        req = request({"id": "k-abc123"}, mine, f"{d}/tls/csr.pem")
        first = open(mine).read()
        assert os.stat(mine).st_mode & 0o777 == 0o600 and os.stat(f"{d}/tls").st_mode & 0o777 == 0o700
        info = subprocess.run(["openssl", "req", "-in", req, "-noout", "-verify", "-subject"], capture_output=True, text=True)
        assert info.returncode == 0 and "k-abc123.kiosk.local" in info.stdout, info
        request({"id": "k-abc123"}, mine, f"{d}/tls/csr.pem")
        assert open(mine).read() == first, "asking again keeps the key"
        cert, key = make("good", "k-abc123.kiosk.local")   # self-signed, so in the test it's its own root
        other, other_key = make("other", "k-000000.kiosk.local")
        on = {**config.DEFAULTS, "id": "k-abc123", "setup": True, "setup_by_ip": False}   # by IP off once set up, for these
        assert config.DEFAULTS["setup_by_ip"] is True, "by IP is on by default"
        assert "setup is off" in gate({**on, "setup": False}, cert, key, cert), "off by default"
        assert "setup is off" in gate({**on, "setup": "yes"}, cert, key, cert), "only true itself turns it on"
        assert "no card ID" in gate({**on, "id": None}, cert, key, cert)
        assert "no " in gate(on, f"{d}/missing.pem", key, cert)
        assert "no " in gate(on, cert, key, f"{d}/no-root.pem"), "no root shipped yet: no way in by name"
        assert "doesn't chain up" in gate(on, cert, key, other), "signed by someone else"
        assert "isn't for k-abc123" in gate(on, other, other_key, other), "another card's certificate"
        assert "don't go together" in gate(on, cert, other_key, cert)
        assert gate(on, cert, key, cert) is None

        # setting up by IP: before the first login's replaced, or by choice; never with setup off
        login = f"{d}/admin-login.json"
        assert by_ip(on, login) and not by_ip({**on, "setup": False}, login) and not by_ip({**on, "id": None}, login)
        ipc, ipk = ip_cert(["127.0.0.1"], f"{d}/tls/ip-cert.pem", f"{d}/tls/ip-key.pem")
        print_ = fingerprint(ipc)
        assert re.fullmatch(r"([0-9A-F]{2}:){31}[0-9A-F]{2}", print_), print_
        assert ip_cert(["127.0.0.1"], ipc, ipk) and fingerprint(ipc) == print_, "the same addresses keep the certificate"
        subprocess.run(["openssl", "req", "-x509", "-new", "-key", ipk, "-days", "1", "-subj", "/CN=127.0.0.1",
                        "-addext", "subjectAltName=IP:127.0.0.1", "-out", ipc], check=True, capture_output=True)
        assert renew_due(ipc)
        ip_cert(["127.0.0.1"], ipc, ipk)
        assert not renew_due(ipc) and fingerprint(ipc) != print_, "about to run out: a new one, with a new fingerprint"
        assert open(ipk).read() != first, "its own key, never the card's"
        for wild in ("0.0.0.0", "0", "::", "::0", ""):
            try:
                servers(on, [wild], context(cert, key))
            except ValueError:
                pass
            else:
                raise AssertionError(f"bound to {wild!r}")
        open(f"{d}/damaged.json", "w").write("{not json")
        assert configured(f"{d}/damaged.json") and not by_ip(on, f"{d}/damaged.json"), "a damaged login file fails closed"
        os.chmod(f"{d}/damaged.json", 0)
        assert configured(f"{d}/damaged.json"), "and so does one it can't read"
        os.makedirs(f"{d}/shut"); open(f"{d}/shut/login.json", "w").write("{}"); os.chmod(f"{d}/shut", 0)
        assert configured(f"{d}/shut/login.json"), "or can't even look at"
        os.chmod(f"{d}/shut", 0o700)
        real = hash_password("correct horse", saved[0])   # the real parameters: hashing and checking agree on maxmem
        assert {k: real[k] for k in "nrp"} == saved[0] and password_ok("correct horse", real) and not password_ok("wrong", real)
        words = [f"w{i}" for i in range(1296)]
        temp = temporary(words)
        assert re.fullmatch(r"Kiosk-W\d+", temp["user"]) and len(temp["password"].split("-")) == 3

        def port():
            s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p
        https, http_ = port(), port()
        ipc, ipk = ip_cert(["127.0.0.1", "127.0.0.2"], ipc, ipk)
        live = servers(on, ["127.0.0.1", "127.0.0.2"], context(cert, key), https, http_, limit=8, per_address=4, deadline=2,
                       ip_ctx=context(ipc, ipk), temp=temp, login=login)
        state = live[0].RequestHandlerClass.state
        for s in live:
            threading.Thread(target=s.serve_forever, daemon=True).start()
        name, ip = f"k-abc123.kiosk.local:{https}", f"127.0.0.1:{https}"
        by_name, by_addr = ssl.create_default_context(cafile=cert), ssl.create_default_context(cafile=ipc)
        by_addr.check_hostname = False   # the browser's warning, which the fingerprint on the screen answers

        def ask(method, path, host, body=None, cookies=None, origin="same", sni=True, to="127.0.0.1"):
            ctx, server_name = (by_name, "k-abc123.kiosk.local") if sni is True else (by_addr, sni or None)
            c = http.client.HTTPSConnection(to, https, timeout=10)
            c.sock = ctx.wrap_socket(socket.create_connection((to, https)), server_hostname=server_name)
            headers = {"Host": host, "Content-Type": "application/x-www-form-urlencoded"}
            if origin:
                headers["Origin"] = f"https://{host}" if origin == "same" else origin
            if cookies:
                headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in cookies.items())
            if body == "big":
                headers["Content-Length"] = "99999"
            c.request(method, path, body=urllib.parse.urlencode(body) if isinstance(body, dict) else body, headers=headers)
            r = c.getresponse(); data = r.read().decode()
            jar = dict(re.match(r"([^=]+)=([^;]*)", v).groups() for k, v in r.getheaders() if k == "Set-Cookie")
            return r.status, r.getheader("Location"), data, jar, r

        # by name and by IP, each with its own certificate and its own Host
        assert ask("GET", "/up", name)[0:3:2] == (200, "up")
        assert ask("GET", "/up", ip, sni=False)[0] == 200, "by IP, while it's not set up yet"
        assert ask("GET", "/up", f"127.0.0.2:{https}", sni=False)[0] == 421, "an IP connection only names the address it reached"
        assert ask("GET", "/up", f"127.0.0.2:{https}", sni=False, to="127.0.0.2")[0] == 200
        try:
            ask("GET", "/up", name, sni="k-000000.kiosk.local")
        except ssl.SSLError:
            pass
        else:
            raise AssertionError("a name it isn't got a certificate")
        assert ask("GET", "/up", ip)[0] == 421, "a name connection can't turn into an IP one"
        assert ask("GET", "/up", name, sni=False)[0] == 421, "or the other way round"
        assert ask("GET", "/up", "evil.example")[0] == 421 and ask("GET", "/up", "evil.example", sni=False)[0] == 421
        assert ask("GET", "/", name)[:2] == (303, "/login"), "everything else needs a login"
        status, _, body, jar, r = ask("GET", "/login", name)
        assert status == 200 and r.getheader("Content-Security-Policy").startswith("default-src 'none'") and "__Host-pre" in jar
        assert "Secure; HttpOnly; SameSite=Strict" in r.getheader("Set-Cookie")
        assert body.endswith(FOOTER) and page("k", NAV).endswith(FOOTER) and ">Built By NomadsGalaxy</a>" in FOOTER, \
            "every screen of it says what it's built on"
        pre = jar["__Host-pre"]
        good = {"pre": pre, "user": temp["user"], "password": temp["password"]}
        # the login's own protections
        assert ask("POST", "/login", name, good, {"__Host-pre": pre}, origin=None)[0] == 403, "no Origin or Referer: refused"
        assert ask("POST", "/login", name, good, {"__Host-pre": pre}, origin="null")[0] == 403, "a null origin: refused"
        assert ask("POST", "/login", name, good, {"__Host-pre": pre}, origin="https://evil.example")[0] == 403
        assert ask("POST", "/login", name, good, {"__Host-pre": pre}, origin=f"https://{ip}")[0] == 403, "an IP origin to the name"
        assert ask("POST", "/login", ip, good, {"__Host-pre": pre}, origin=f"https://{name}", sni=False)[0] == 403, "the name's origin to an IP"
        assert ask("POST", "/login", f"127.0.0.2:{https}", good, {"__Host-pre": pre}, origin=f"https://{ip}", sni=False,
                   to="127.0.0.2")[0] == 403, "one address's origin to another"
        assert ask("POST", "/login", name, good, {"__Host-pre": "x" * 43})[0] == 403, "the form's token has to match its cookie"
        assert ask("POST", "/login", name, "big", {"__Host-pre": pre})[0] == 413, "4 KB at most"
        # the temporary login gets in, only to replace itself
        status, where, _, jar, _ = ask("POST", "/login", name, good, {"__Host-pre": pre})
        assert (status, where) == (303, "/change") and "__Host-kiosk" in jar
        temp_session = jar["__Host-kiosk"]
        assert ask("GET", "/", name, cookies={"__Host-kiosk": temp_session})[:2] == (303, "/change"), "nothing else until it's replaced"
        early = re.search(r'name=csrf value="([^"]+)"', ask("GET", "/change", name, cookies={"__Host-kiosk": temp_session})[2]).group(1)
        assert ask("POST", "/pages", name, {"action": "add", "page": "sky", "csrf": early}, {"__Host-kiosk": temp_session})[:2] \
            == (303, "/change") and not os.path.exists(PLAYLIST), "the login on the screen can't change settings"
        csrf = re.search(r'name=csrf value="([^"]+)"', ask("GET", "/change", name, cookies={"__Host-kiosk": temp_session})[2]).group(1)
        new = {"csrf": csrf, "user": "owner", "password": "a much longer one", "again": "a much longer one"}
        assert ask("POST", "/change", name, {**new, "csrf": "wrong"}, {"__Host-kiosk": temp_session})[:2] == (303, "/login"), "CSRF"
        assert ask("POST", "/change", name, {**new, "again": "different"}, {"__Host-kiosk": temp_session})[0] == 400
        assert ask("POST", "/change", name, {**new, "password": "short", "again": "short"}, {"__Host-kiosk": temp_session})[0] == 400
        log = io.StringIO()
        with contextlib.redirect_stderr(log):
            status, where, _, jar, _ = ask("POST", "/change", name, new, {"__Host-kiosk": temp_session})
        assert (status, where) == (303, "/") and jar["__Host-kiosk"] != temp_session, "a new session after the change"
        assert "a much longer one" not in log.getvalue() and temp["password"] not in log.getvalue()
        stored = json.load(open(login))
        assert os.stat(login).st_mode & 0o777 == 0o600 and "a much longer one" not in open(login).read()
        assert stored["user"] == "owner" and password_ok("a much longer one", stored) and not password_ok("nope", stored)
        session = jar["__Host-kiosk"]
        assert ask("GET", "/", name, cookies={"__Host-kiosk": temp_session})[:2] == (303, "/login"), "every old session ended"
        assert ask("GET", "/", name, cookies={"__Host-kiosk": session})[0] == 200
        # the settings: each form changes the kiosk's own files in one move, then restarts the display
        for path in ("/", "/pages", "/transitions", "/location"):
            status, _, body, _, _ = ask("GET", path, name, cookies={"__Host-kiosk": session})
            assert status == 200 and "the <b>" not in body, (path, status)   # the catalog's text is escaped
        assert "the &lt;b&gt;weather" in ask("GET", "/pages", name, cookies={"__Host-kiosk": session})[2]
        csrf = re.search(r'name=csrf value="([^"]+)"', ask("GET", "/pages", name, cookies={"__Host-kiosk": session})[2]).group(1)
        post = lambda path, form: ask("POST", path, name, {**form, "csrf": csrf}, {"__Host-kiosk": session})
        assert post("/pages", {"action": "add", "page": "sky"})[:2] == (303, "/pages") and restarts
        assert [e["page"] for e in json.load(open(PLAYLIST))] == ["weather", "sky"], "the repo's playlist, plus the new one"
        assert os.stat(PLAYLIST).st_mode & 0o777 == 0o600
        assert post("/pages", {"action": "off", "i": "0"})[0] == 303 and json.load(open(PLAYLIST))[0]["on"] is False
        assert post("/pages", {"action": "off", "i": "1"})[0] == 400, "not the last page on"
        for bad in ({"action": "add", "page": "rain"}, {"action": "add", "page": "big"}, {"action": "add", "page": "nope"},
                    {"action": "seconds", "i": "1", "seconds": "0"}, {"action": "up", "i": "9"}, {"action": "wat", "i": "0"}):
            assert post("/pages", bad)[0] == 400, bad
        assert ask("POST", "/pages", name, {"action": "on", "i": "0"}, {"__Host-kiosk": session})[:2] == (303, "/login"), \
            "no form token: nothing changes"
        assert ask("POST", "/pages", name, {"action": "on", "i": "0", "csrf": csrf}, {"__Host-kiosk": session},
                   origin="https://evil.example")[0] == 403, "and only from this page itself"
        assert post("/location", {"lat": "40.1", "lon": "-75.2", "place": "home"})[0] == 303
        assert [e.get("options") for e in json.load(open(PLAYLIST))] == [{"lat": 40.1, "lon": -75.2, "place": "HOME"}] * 2
        assert post("/location", {"lat": "91", "lon": "0"})[0] == 400
        assert post("/transitions", {"t_rain": "on"})[0] == 303 and json.load(open(OFF)) == ["snow"]
        assert post("/transitions", {})[0] == 400, "not every transition off"
        # the Install page: a request for packs.py, checked here first
        status, _, body, _, _ = ask("GET", "/install", name, cookies={"__Host-kiosk": session})
        assert status == 200 and "Install from the repo" in body and "comes with every kiosk" in body, status
        assert post("/install", {"action": "catalog", "kind": "page", "name": "sky"})[:2] == (303, "/install")
        assert json.load(open(PACKS_REQUEST)) | {"id": "x"} == {"id": "x", "op": "install", "source": "catalog", "kind": "page", "name": "sky"}
        assert "Working on it" in ask("GET", "/install", name, cookies={"__Host-kiosk": session})[2], "while it's carried out"
        os.remove(PACKS_REQUEST)
        json.dump({"state": "done", "message": "Installed sky from the catalog."}, open(PACKS_STATUS, "w"))
        assert "Last time: Installed sky" in ask("GET", "/install", name, cookies={"__Host-kiosk": session})[2]
        status, _, body, _, _ = post("/install", {"action": "repo", "repo": "https://github.com/me/clock"})
        assert status == 400 and "Tick the box" in body and not os.path.exists(PACKS_REQUEST), "not without the warning ticked"
        for bad in ({"action": "repo", "agree": "on", "repo": "http://github.com/me/clock"},
                    {"action": "repo", "agree": "on", "repo": "https://github.com/me/clock", "ref": "../main"},
                    {"action": "remove", "kind": "page", "name": "../x"}, {"action": "catalog", "kind": "app", "name": "sky"},
                    {"action": "format"}):
            assert post("/install", bad)[0] == 400 and not os.path.exists(PACKS_REQUEST), bad
        assert post("/install", {"action": "repo", "agree": "on", "repo": "https://github.com/me/clock/", "ref": "main"})[0] == 303
        assert json.load(open(PACKS_REQUEST)) | {"id": "x"} == {"id": "x", "op": "install", "source": "repo",
                                                              "repo": "https://github.com/me/clock", "ref": "main"}
        os.remove(PACKS_REQUEST)
        json.dump({"server": "10.0.0.9", "port": 7676}, open(REMOTE, "w"))
        before = open(PLAYLIST).read()
        status, _, body, _, _ = post("/pages", {"action": "on", "i": "0"})
        assert status == 409 and "render server, 10.0.0.9" in body and open(PLAYLIST).read() == before, \
            "a render server's kiosk without the key only shows its settings"
        # with the key in both remote.json files, the setup page changes the settings on the server
        shared, served, server_restarts = secrets.token_hex(32), f"{d}/served", []
        os.makedirs(f"{served}/conf"); os.makedirs(f"{served}/code/transitions")
        for t in ("rain", "snow"):
            open(f"{served}/code/transitions/{t}.py", "w").write("")
        json.dump([{"page": "weather"}], open(f"{served}/code/playlist.json", "w"))
        listener = socket.create_server(("127.0.0.1", 0)); link_port = listener.getsockname()[1]
        handle = lambda m: link.settings(m, f"{served}/conf", f"{served}/code", lambda: server_restarts.append(1))
        def serve():
            nonces = link.Nonces()
            while True:
                try:
                    conn, _ = listener.accept()
                except OSError:
                    return
                link.answer(conn, shared, handle, nonces)
        threading.Thread(target=serve, daemon=True).start()
        json.dump({"server": "127.0.0.1", "port": link_port, "key": shared}, open(REMOTE, "w"))
        here_before, local_restarts = open(PLAYLIST).read(), len(restarts)
        assert "the repo playlist" in ask("GET", "/pages", name, cookies={"__Host-kiosk": session})[2], "the server's settings"
        assert post("/pages", {"action": "add", "page": "sky"})[:2] == (303, "/pages")
        assert [e["page"] for e in json.load(open(f"{served}/conf/playlist.json"))] == ["weather", "sky"] and server_restarts
        assert open(PLAYLIST).read() == here_before and len(restarts) == local_restarts, "and not on the Pi"
        assert post("/transitions", {"t_snow": "on"})[0] == 303 and json.load(open(f"{served}/conf/transitions-off.json")) == ["rain"]
        assert post("/pages", {"action": "add", "page": "nope"})[0] == 400
        assert post("/install", {"action": "catalog", "kind": "transition", "name": "rain"})[0] == 303
        assert json.load(open(f"{served}/conf/packs-request.json"))["name"] == "rain", "the server installs it, where pages run"
        assert json.load(open(PACKS_REQUEST))["name"] == "rain", "and the Pi too, which plays transitions"
        os.remove(PACKS_REQUEST)
        listener.close()
        status, _, body, _, _ = post("/pages", {"action": "on", "i": "0"})
        assert status == 502 and "Couldn't reach" in body, "a server that's away says so"
        assert "Couldn't reach its render server" in ask("GET", "/location", name, cookies={"__Host-kiosk": session})[2]
        os.remove(REMOTE)
        # once it's set up, by IP goes away (unless config keeps it), and the temporary login stops working
        assert ask("GET", "/up", ip, sni=False)[0] == 421, "set up, with setup_by_ip false: no more by IP"
        state.cfg = {**on, "setup_by_ip": True}
        assert ask("GET", "/up", ip, sni=False)[0] == 200, "on by default (behind the login)"
        state.cfg = on
        pre = ask("GET", "/login", name)[3]["__Host-pre"]
        assert ask("POST", "/login", name, {**good, "pre": pre}, {"__Host-pre": pre})[0] == 403, "the temporary login is gone"
        assert ask("POST", "/login", name, {"pre": pre, "user": "owner", "password": "a much longer one"}, {"__Host-pre": pre})[:2] == (303, "/")
        # replacing a login someone set needs its password
        csrf = re.search(r'name=csrf value="([^"]+)"', ask("GET", "/change", name, cookies={"__Host-kiosk": session})[2]).group(1)
        again = {**new, "csrf": csrf, "user": "owner2", "password": "another long one", "again": "another long one"}
        assert ask("POST", "/change", name, again, {"__Host-kiosk": session})[0] == 403, "no current password"
        assert ask("POST", "/change", name, {**again, "current": "a much longer one"}, {"__Host-kiosk": session})[:2] == (303, "/")
        assert json.load(open(login))["user"] == "owner2"
        new = {**new, "user": "owner", "password": "a much longer one"}   # back as it was, for what follows
        session = ask("POST", "/login", name, {"pre": pre, "user": "owner2", "password": "another long one"}, {"__Host-pre": pre})[3]["__Host-kiosk"]
        csrf = re.search(r'name=csrf value="([^"]+)"', ask("GET", "/change", name, cookies={"__Host-kiosk": session})[2]).group(1)
        ask("POST", "/change", name, {**new, "csrf": csrf, "again": new["password"], "current": "another long one"}, {"__Host-kiosk": session})
        assert password_ok("a much longer one", json.load(open(login)))
        # races, without timing: two sessions from the same login, and a login checked before a change
        pre = ask("GET", "/login", name)[3]["__Host-pre"]
        a = ask("POST", "/login", name, {"pre": pre, "user": "owner", "password": "a much longer one"}, {"__Host-pre": pre})[3]["__Host-kiosk"]
        b = ask("POST", "/login", name, {"pre": pre, "user": "owner", "password": "a much longer one"}, {"__Host-pre": pre})[3]["__Host-kiosk"]
        ca = re.search(r'name=csrf value="([^"]+)"', ask("GET", "/change", name, cookies={"__Host-kiosk": a})[2]).group(1)
        cb = re.search(r'name=csrf value="([^"]+)"', ask("GET", "/change", name, cookies={"__Host-kiosk": b})[2]).group(1)
        checked = state.generation   # a login that's been checked against the current password, and hasn't got its session yet
        ask("POST", "/change", name, {**new, "csrf": ca, "again": new["password"], "current": "a much longer one"}, {"__Host-kiosk": a})
        assert state.start_session(False, checked) is None, "a login checked before the change never gets a session"
        mallory = {**new, "csrf": cb, "password": "overwrite attempt", "again": "overwrite attempt", "current": "a much longer one"}
        assert ask("POST", "/change", name, mallory, {"__Host-kiosk": b})[:2] == (303, "/login"), "the second change finds its session void"
        assert password_ok("a much longer one", json.load(open(login))) and not password_ok("overwrite attempt", json.load(open(login)))
        session = ask("POST", "/login", name, {"pre": pre, "user": "owner", "password": "a much longer one"}, {"__Host-pre": pre})[3]["__Host-kiosk"]
        # non-ASCII in a token, or in the temporary login, gets a plain answer, not a dropped connection
        assert ask("POST", "/login", name, {"pre": "ünïcode", "user": "ü", "password": "ü"}, {"__Host-pre": pre})[0] == 403
        # throttling: five failures, then each try waits, and a waiting one never gets as far as hashing
        for _ in range(5):
            ask("POST", "/login", name, {"pre": pre, "user": "owner", "password": "wrong"}, {"__Host-pre": pre})
        hashed = []
        real_ok, globals()["password_ok"] = password_ok, lambda *a: hashed.append(1) or real_ok(*a)
        try:
            assert ask("POST", "/login", name, {"pre": pre, "user": "owner", "password": "a much longer one"}, {"__Host-pre": pre})[0] == 429
        finally:
            globals()["password_ok"] = real_ok
        assert not hashed, "a throttled login never reaches scrypt"
        t = Throttle()
        for _ in range(11):
            t.fail("10.0.0.9")
        assert t.wait("10.0.0.7") > 0, "the overall count slows everyone"
        t.failed = {k: (n, until, last - Throttle.FORGET - 1) for k, (n, until, last) in t.failed.items()}
        assert t.wait("10.0.0.7") == 0 and "*" not in t.failed, "but it's forgotten after a quiet 15 minutes"
        for _ in range(11):
            t.fail("10.0.0.9")
        t.ok("10.0.0.7")
        assert t.wait("10.0.0.7") == 0, "and a success clears it"
        # port 80: a fixed target, never the request's Host
        c = http.client.HTTPConnection("127.0.0.1", http_, timeout=10); c.request("GET", "/", headers={"Host": "evil.example"})
        assert c.getresponse().getheader("Location") == f"https://{name}/", "set up, by-IP off: always the name"
        for s in live:
            s.shutdown(); s.server_close()

        # a fresh kiosk with no certificate for its name yet, by IP on (the default): it carries on after the change
        os.remove(login)
        live = servers({**on, "setup_by_ip": True}, ["127.0.0.1"], None, https, http_, deadline=2, ip_ctx=context(ipc, ipk),
                       temp=temp, login=login)
        live[0].RequestHandlerClass.state.fingerprint = fingerprint(ipc)   # as main() does
        for s in live:
            threading.Thread(target=s.serve_forever, daemon=True).start()
        pre = ask("GET", "/login", ip, sni=False)[3]["__Host-pre"]
        s1 = ask("POST", "/login", ip, {**good, "pre": pre}, {"__Host-pre": pre}, sni=False)[3]["__Host-kiosk"]
        csrf = re.search(r'name=csrf value="([^"]+)"', ask("GET", "/change", ip, cookies={"__Host-kiosk": s1}, sni=False)[2]).group(1)
        status, where, _, jar, _ = ask("POST", "/change", ip, {**new, "csrf": csrf}, {"__Host-kiosk": s1}, sni=False)
        assert (status, where) == (303, "/") and jar["__Host-kiosk"] != s1, "by IP stays on: carry on, with a new session"
        assert ask("GET", "/", ip, cookies={"__Host-kiosk": jar["__Host-kiosk"]}, sni=False)[0] == 200
        assert ask("GET", "/", ip, cookies={"__Host-kiosk": s1}, sni=False)[:2] == (303, "/login"), "the old session ended"
        shown = json.load(open(SETUP))
        assert shown["next"] == [f"https://{ip}"] and shown["fingerprint"] == fingerprint(ipc) and "password" not in shown, \
            "the screen says where to log in now, keeps the fingerprint to check, and drops the password"
        assert screen(None, [f"https://{ip}"], fingerprint(ipc)) == {"addresses": [f"https://{ip}"], "fingerprint": fingerprint(ipc)}, \
            "after a restart (or a renewal, which restarts it): addresses and the served fingerprint, no password"
        setup_page = importlib.import_module("pages.setup")
        assert setup_page.urgent(SETUP), "set up: where to log in now, on the screen ahead of the pages"
        owner = jar["__Host-kiosk"]
        csrf = re.search(r'name=csrf value="([^"]+)"', ask("GET", "/", ip, cookies={"__Host-kiosk": owner}, sni=False)[2]).group(1)
        assert ask("POST", "/logout", ip, {"csrf": csrf}, {"__Host-kiosk": owner}, sni=False)[:2] == (303, "/login")
        shown = json.load(open(SETUP))
        assert not setup_page.urgent(SETUP) and "done" not in shown and shown["fingerprint"] == fingerprint(ipc), \
            "logged out, the screen goes straight back to its pages, still with the fingerprint for next time"
        write_private(SETUP, {"user": "Kiosk-X", "password": "a-b-c", "done": True}); settled()
        assert json.load(open(SETUP))["user"] == "Kiosk-X", "a first-boot login is never taken off the screen this way"
        for s in live:
            s.shutdown(); s.server_close()

        # ...and with "setup_by_ip": false, the change finishes on that connection, then by IP closes
        os.remove(login)
        live = servers(on, ["127.0.0.1"], None, https, http_, deadline=2, ip_ctx=context(ipc, ipk), temp=temp, login=login)
        for s in live:
            threading.Thread(target=s.serve_forever, daemon=True).start()
        try:
            ask("GET", "/up", name)
        except ssl.SSLError:
            pass
        else:
            raise AssertionError("no certificate for the name, yet it answered by name")
        c = http.client.HTTPConnection("127.0.0.1", http_, timeout=10); c.request("GET", "/", headers={"Host": "evil.example"})
        assert c.getresponse().getheader("Location") == f"https://{ip}/", "port 80 sends a fresh kiosk to its own address"
        _, _, _, jar, _ = ask("GET", "/login", ip, sni=False)
        pre = jar["__Host-pre"]
        _, where, _, jar, _ = ask("POST", "/login", ip, {**good, "pre": pre}, {"__Host-pre": pre}, sni=False)
        s1 = jar["__Host-kiosk"]
        csrf = re.search(r'name=csrf value="([^"]+)"', ask("GET", "/change", ip, cookies={"__Host-kiosk": s1}, sni=False)[2]).group(1)
        status, _, body, _, _ = ask("POST", "/change", ip, {**new, "csrf": csrf}, {"__Host-kiosk": s1}, sni=False)
        assert status == 200 and "this connection is finished" in body and "over SSH" in body, \
            "it says so on the same connection, and that there's no other way in by the network yet"
        shown = json.load(open(SETUP))
        assert shown["done"] and shown["next"] == [] and not shown["fingerprint"] and "password" not in shown, \
            "and the screen stops showing the temporary login (and, by IP being off, any fingerprint)"
        assert ask("GET", "/up", ip, sni=False)[0] == 421, "then by IP is off"
        for s in live:
            s.shutdown(); s.server_close()

        # the limits, on their own server
        live = servers(on, ["127.0.0.1"], context(cert, key), https, http_, limit=3, per_address=3, deadline=2)
        for s in live:
            threading.Thread(target=s.serve_forever, daemon=True).start()
        idle = [socket.create_connection(("127.0.0.1", https)) for _ in range(3)]   # three that never say a word
        time.sleep(0.3)
        try:
            ask("GET", "/up", name)
        except OSError:
            pass
        else:
            raise AssertionError("a fourth client got in past the limit")
        for sock in idle:
            sock.close()
        time.sleep(0.3)
        assert ask("GET", "/up", name)[0] == 200, "room again once they've gone"
        drip = by_name.wrap_socket(socket.create_connection(("127.0.0.1", https)), server_hostname="k-abc123.kiosk.local")
        drip.settimeout(5); started = time.time()
        try:
            for ch in "GET /up HTTP/1.1\r\nHost: ":   # a byte at a time, slower than the deadline allows
                drip.send(ch.encode()); time.sleep(0.2)
            drip.recv(100)
        except OSError:
            pass
        assert time.time() - started < 4.5, "a slow drip was cut off at the deadline"
        drip.close()
        log = io.StringIO()
        with contextlib.redirect_stderr(log):
            ask("GET", "/login?password=hunter2", name)
        assert "hunter2" not in log.getvalue() and "GET /login 200" in log.getvalue(), log.getvalue()
        for s in live:
            s.shutdown(); s.server_close()
        per = Bounded(("127.0.0.1", 0), Redirect, limit=10, per_address=2)   # one address can't take every slot
        held = [socket.create_connection(per.server_address) for _ in range(2)]
        threading.Thread(target=per.serve_forever, daemon=True).start(); time.sleep(0.3)
        third = socket.create_connection(per.server_address); third.settimeout(3)
        assert third.recv(10) == b"", "a third from the same address is dropped"
        for sock in held + [third]:
            sock.close()
        per.shutdown(); per.server_close()
    SCRYPT, SETUP = saved
    PLAYLIST, REPO_PLAYLIST, OFF, REMOTE, CATALOG, THEMES, CACHE, restart, PACKS_REQUEST, PACKS_STATUS, PRESENT = settings_saved
    print("admin: ok")


if __name__ == "__main__":
    if sys.argv[1:] == ["--check"]:
        check()
    elif sys.argv[1:] == ["--csr"]:
        print(open(request({**config.load(), "id": config.card_id()})).read(), end="")
    elif not sys.argv[1:]:
        sys.exit(main())
    else:
        sys.exit(__doc__)
