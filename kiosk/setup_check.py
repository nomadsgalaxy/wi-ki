"""setup_check: the setup page's security tests, kept apart from admin.py so the code and the rules it has to keep can
be read separately. admin.check() covers the basics with a self-signed certificate. These use a chain like a real one:
a root, an intermediate that may only sign names under .kiosk.local, and the card's certificate with the intermediate
after it, as it would sit in ~/.config/kiosk/tls/cert.pem. They also cover setting it up by IP, logging in, the form
tokens, the origin check, the limits, and handing over from the first-boot login.
"""
import http.client, io, json, os, re, socket, ssl, subprocess, sys, tempfile, threading, time, urllib.parse
from contextlib import redirect_stderr

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))  # -I leaves our own folder off the path
import admin, config  # noqa: E402

ID, OTHER = "k-abc123", "k-000000"


def openssl(*args):
    subprocess.run(["openssl", *args], check=True, capture_output=True)


def chain(d):
    """a throwaway root, a .kiosk.local-only intermediate, and a leaf-signing function, in folder d"""
    open(f"{d}/root.ext", "w").write("basicConstraints=critical,CA:TRUE\nkeyUsage=critical,keyCertSign,cRLSign\n")
    open(f"{d}/inter.ext", "w").write("basicConstraints=critical,CA:TRUE,pathlen:0\nkeyUsage=critical,keyCertSign,cRLSign\n"
                                      "nameConstraints=critical,permitted;DNS:.kiosk.local,excluded;IP:0.0.0.0/0.0.0.0\n")
    for name in ("root", "inter"):
        openssl("genpkey", "-algorithm", "EC", "-pkeyopt", "ec_paramgen_curve:P-256", "-out", f"{d}/{name}.key")
    openssl("req", "-x509", "-new", "-key", f"{d}/root.key", "-subj", "/CN=test root", "-days", "2", "-out", f"{d}/root.pem",
            "-addext", "basicConstraints=critical,CA:TRUE", "-addext", "keyUsage=critical,keyCertSign,cRLSign")
    openssl("req", "-new", "-key", f"{d}/inter.key", "-subj", "/CN=test intermediate", "-out", f"{d}/inter.csr")
    openssl("x509", "-req", "-in", f"{d}/inter.csr", "-CA", f"{d}/root.pem", "-CAkey", f"{d}/root.key", "-days", "2",
            "-set_serial", "1", "-extfile", f"{d}/inter.ext", "-out", f"{d}/inter.pem")

    def leaf(tag, name, expired=False):
        """-> (cert.pem with the intermediate after it, key.pem) for name"""
        key, csr, pem, ext = (f"{d}/{tag}.{x}" for x in ("key", "csr", "leaf", "ext"))
        open(ext, "w").write(f"basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature\n"
                             f"extendedKeyUsage=serverAuth\nsubjectAltName=DNS:{name}\n")
        openssl("genpkey", "-algorithm", "EC", "-pkeyopt", "ec_paramgen_curve:P-256", "-out", key)
        openssl("req", "-new", "-key", key, "-subj", f"/CN={name}", "-out", csr)
        dates = ["-not_before", "20200101000000Z", "-not_after", "20200102000000Z"] if expired else ["-days", "2"]
        openssl("x509", "-req", "-in", csr, "-CA", f"{d}/inter.pem", "-CAkey", f"{d}/inter.key", *dates,
                "-set_serial", str(int.from_bytes(os.urandom(8), "big")), "-extfile", ext, "-out", pem)
        open(f"{d}/{tag}.pem", "w").write(open(pem).read() + open(f"{d}/inter.pem").read())
        return f"{d}/{tag}.pem", key
    return f"{d}/root.pem", leaf


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


def check():
    with tempfile.TemporaryDirectory() as d:
        root, leaf = chain(d)
        on = {**config.DEFAULTS, "id": ID, "setup": True}
        cert, key = leaf("good", f"{ID}.kiosk.local")

        # the gate: every way in is shut unless everything holds
        assert admin.gate(on, cert, key, root) is None, admin.gate(on, cert, key, root)
        assert admin.gate({**on, "setup": False}, cert, key, root), "setup off: closed"
        assert admin.gate({**on, "setup": "yes"}, cert, key, root), "only true turns it on"
        assert admin.gate(on, *leaf("other", f"{OTHER}.kiosk.local"), root), "another card's certificate: closed"
        assert admin.gate(on, *leaf("old", f"{ID}.kiosk.local", expired=True), root), "out of date: closed"
        stray_cert, stray_key = leaf("stray", "evil.example")   # signed, but outside what the intermediate may sign
        assert admin.gate({**on, "id": ID}, stray_cert, stray_key, root), "outside .kiosk.local: closed"
        assert admin.gate(on, cert, leaf("k2", f"{ID}.kiosk.local")[1], root), "a key that isn't the certificate's: closed"
        open(f"{d}/leaf-only.pem", "w").write(open(f"{d}/good.leaf").read())
        assert admin.gate(on, f"{d}/leaf-only.pem", key, root), "without its intermediate it doesn't chain: closed"
        open(f"{d}/empty.pem", "w").close()
        assert admin.gate(on, f"{d}/empty.pem", key, root) and admin.gate(on, cert, key, f"{d}/empty.pem"), "empty files: closed"
        for wild in ("0.0.0.0", "", "::", "0", "::0", "0000:0000::"):
            try:
                live = admin.servers(on, [wild], admin.context(cert, key), free_port(), free_port())
            except (AssertionError, ValueError):
                continue
            for s in live:
                s.server_close()
            raise AssertionError(f"bound to {wild!r}")
        # the same refusal has to survive python -O, which strips asserts
        probe = subprocess.run([sys.executable, "-O", "-I", "-c", f"""
import sys; sys.path.insert(0, {os.path.dirname(os.path.realpath(__file__))!r})
import admin, config
try:
    admin.servers({{**config.DEFAULTS, "id": "{ID}", "setup": True}}, ["0.0.0.0"], admin.context({cert!r}, {key!r}), 0, 0)
except Exception:
    sys.exit(0)
sys.exit("bound to 0.0.0.0 under python -O")"""], capture_output=True, text=True)
        assert probe.returncode == 0, probe.stderr.strip()[-200:] or probe.stdout

        # the servers, on 127.0.0.1, with the real kind of chain
        https, http_ = free_port(), free_port()
        live = admin.servers(on, ["127.0.0.1"], admin.context(cert, key), https, http_, limit=4)
        for s in live:
            threading.Thread(target=s.serve_forever, daemon=True).start()
        name = f"{ID}.kiosk.local:{https}"
        trust = ssl.create_default_context(cafile=root)

        def ask(method, path, headers=None, body=None, sni=f"{ID}.kiosk.local"):
            c = http.client.HTTPSConnection("127.0.0.1", https, timeout=10)
            c.sock = trust.wrap_socket(socket.create_connection(("127.0.0.1", https), timeout=10), server_hostname=sni)
            c.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
            for k, v in (headers if headers is not None else {"Host": name}).items():
                c.putheader(k, v)
            data = body.encode() if body else b""
            if body is not None:
                c.putheader("Content-Length", str(len(data)))
            c.endheaders(data or None)
            r = c.getresponse(); return r.status, r.getheader("Location"), r.read().decode()

        try:
            assert ask("GET", "/up")[0] == 200, "a client that trusts the root reaches it by name"
            for host in ("127.0.0.1", f"127.0.0.1:{https}", f"{OTHER}.kiosk.local:{https}", "evil.example",
                         f"{ID}.kiosk.local.evil.example:{https}", f"evil.example@{ID}.kiosk.local:{https}"):
                assert ask("GET", "/up", {"Host": host})[0] == 421, host
            assert ask("GET", "/up", {})[0] == 421, "no Host at all"
            assert ask("GET", "/up", {"Host": name, "X-Forwarded-Host": "evil.example"})[0] == 200, \
                "forwarded headers change nothing"
            assert ask("GET", "/up", {"Host": "evil.example", "X-Forwarded-Host": name})[0] == 421, \
                "and can't vouch for a wrong Host"
            # every POST is refused until login exists; once it does, these become the CSRF and Origin tests
            for headers in ({"Host": name}, {"Host": name, "Origin": "null"}, {"Host": name, "Origin": "https://evil.example"},
                            {"Host": name, "Origin": f"https://{name}"}):
                status = ask("POST", "/login", {**headers, "Content-Type": "application/x-www-form-urlencoded"},
                             body="user=a&password=b")[0]
                assert status in (403, 421), (headers, status)
            assert ask("POST", "/login", {"Host": name, "Transfer-Encoding": "chunked"})[0] == 411, "a body without a length"
            def exact(head, body=b""):   # header lines exactly as given, repeats and all
                s = trust.wrap_socket(socket.create_connection(("127.0.0.1", https), timeout=10),
                                      server_hostname=f"{ID}.kiosk.local")
                s.sendall(head.encode() + b"\r\n" + body)
                out = b""
                try:
                    while chunk := s.recv(1000):
                        out += chunk
                except (TimeoutError, socket.timeout):
                    raise AssertionError(f"no answer to {head!r}") from None
                s.close()
                return int(out.split(b" ", 2)[1]) if out else 0
            for head, codes, why in (   # repeated or smuggled headers are refused outright, not just
                    # turned away by whatever check happens to come next: a 403 for "no login yet" doesn't count
                    (f"GET /up HTTP/1.1\r\nHost: {name}\r\nHost: evil.example\r\n", (400,), "a second, different Host"),
                    (f"GET /up HTTP/1.1\r\nHost: evil.example\r\nHost: {name}\r\n", (400, 421), "a second Host behind a bad one"),
                    (f"GET /up HTTP/1.1\r\nHost: {name}\r\nHost: {name}\r\n", (400,), "the same Host twice"),
                    (f"POST /login HTTP/1.1\r\nHost: {name}\r\nContent-Length: 3\r\nContent-Length: 300\r\n", (400,), "two lengths"),
                    (f"POST /login HTTP/1.1\r\nHost: {name}\r\nContent-Length: 3\r\nTransfer-Encoding: chunked\r\n", (400,),
                     "a length and chunked"),
                    (f"POST /login HTTP/1.1\r\nHost: {name}\r\nTransfer-Encoding: chunked\r\n", (400, 411), "chunked at all")):
                status = exact(head + "Connection: close\r\n", b"abc")
                assert status in codes, f"{why}: {status}, wanted {codes}"
            for odd in ("²", "١٢", "+5", "-1", "0x10", "99999999999999999999"):   # digits that aren't ASCII, signs, huge
                assert ask("POST", "/login", {"Host": name, "Content-Length": odd.encode()})[0] in (400, 411, 413), odd
            for method in ("PUT", "DELETE", "PATCH"):
                assert ask(method, "/up")[0] >= 400, f"{method} does nothing"

            # what gets logged: never a password, cookie or header
            secret = "correct-horse-battery-" + os.urandom(4).hex()
            err = io.StringIO()
            with redirect_stderr(err):
                ask("POST", "/login", {"Host": name, "Cookie": f"s={secret}", "Authorization": f"Basic {secret}",
                                       "Content-Type": "application/x-www-form-urlencoded"}, body=f"password={secret}")
                time.sleep(0.2)
            assert secret not in err.getvalue(), "a secret reached the log"
            err = io.StringIO()   # nor anything that could fake a line of its own: control characters in the path
            with redirect_stderr(err):
                # no whitespace in it (\r would split the request line and get it refused before it's logged)
                exact(f"GET /up\x1b[2K\x08\x08admin:FORGED HTTP/1.1\r\nHost: {name}\r\nConnection: close\r\n")
                time.sleep(0.2)
            assert "\x1b" not in err.getvalue() and "\x08" not in err.getvalue(), "control characters reached the log"

            # no plain HTTP on the HTTPS port
            raw = socket.create_connection(("127.0.0.1", https), timeout=5)
            raw.sendall(f"GET /up HTTP/1.1\r\nHost: {name}\r\n\r\n".encode())
            try:
                assert b"200" not in raw.recv(100), "plain HTTP on the HTTPS port"
            except OSError:
                pass
            raw.close()

            # port 80: one fixed redirect, whatever the request says
            for host in (name, "evil.example", "127.0.0.1"):
                c = http.client.HTTPConnection("127.0.0.1", http_, timeout=5)
                c.request("GET", "/login?next=https://evil.example/", headers={"Host": host})
                r = c.getresponse()
                assert (r.status, r.getheader("Location")) == (301, f"https://{name}/"), (host, r.getheader("Location"))
                assert not r.read(), "the redirect carries nothing"
        finally:
            for s in live:
                s.shutdown(); s.server_close()

        # the limits, from two addresses: one that fills its share, and one that still gets in
        https, http_ = free_port(), free_port()
        live = admin.servers(on, ["127.0.0.1"], admin.context(cert, key), https, http_, limit=8, per_address=2, deadline=2)
        for s in live:
            threading.Thread(target=s.serve_forever, daemon=True).start()
        try:
            def held(port, source):
                c = socket.create_connection(("127.0.0.1", port), timeout=5, source_address=(source, 0)); return c

            def cut(c, within):   # the server hangs up on it by itself, inside `within` seconds
                c.settimeout(within)
                try:
                    while c.recv(100):
                        pass
                except (TimeoutError, socket.timeout):
                    raise AssertionError("still connected after the deadline")
                except OSError:
                    pass
            hog = [held(https, "127.0.0.1") for _ in range(2)]   # silent: never even says hello
            time.sleep(0.2)
            third = held(https, "127.0.0.1")
            third.settimeout(0.5)   # well inside the 2 s deadline, so only a refusal closes it this fast
            try:
                assert third.recv(1) == b"", "a third from the same address is turned away"
            except (TimeoutError, socket.timeout):
                raise AssertionError("a third from the same address was let in") from None
            third.close()
            # another address still gets a full TLS handshake and an answer while the first is at its cap
            other = trust.wrap_socket(held(https, "127.0.0.2"), server_hostname=f"{ID}.kiosk.local")
            other.sendall(f"GET /up HTTP/1.1\r\nHost: {ID}.kiosk.local:{https}\r\nConnection: close\r\n\r\n".encode())
            answer = b""
            while chunk := other.recv(1000):
                answer += chunk
            assert answer.split(b"\r\n", 1)[0].endswith(b" 200 OK"), answer[:80]
            other.close()
            for c in hog:   # the silent ones are cut at the deadline, handshake never started
                cut(c, 3.5)
            drip = held(http_, "127.0.0.3"); drip.settimeout(5); started = time.time()
            try:   # port 80 has the same deadline: a byte at a time, never finishing
                for ch in "GET / HTTP/1.1\r\nHost: x":
                    drip.send(ch.encode()); time.sleep(0.2)
            except OSError:
                pass
            cut(drip, 3.5)
            assert time.time() - started < 6, "a slow drip on port 80 was cut off at the deadline"
        finally:
            for s in live:
                s.shutdown(); s.server_close()
        # the limits are the kiosk's, not each listener's: 443 and 80 share one count, overall and per address
        https, http_ = free_port(), free_port()
        live = admin.servers(on, ["127.0.0.1"], admin.context(cert, key), https, http_, limit=3, per_address=2, deadline=3)
        for s in live:
            threading.Thread(target=s.serve_forever, daemon=True).start()
        try:
            def refused(port, source):   # turned away at once, well inside the deadline
                c = socket.create_connection(("127.0.0.1", port), timeout=5, source_address=(source, 0))
                c.settimeout(0.5)
                try:
                    return c.recv(1) == b""
                except (TimeoutError, socket.timeout):
                    return False
                finally:
                    c.close()
            hold = [socket.create_connection(("127.0.0.1", https), source_address=("127.0.0.4", 0))]
            hold.append(socket.create_connection(("127.0.0.1", http_), source_address=("127.0.0.4", 0)))
            time.sleep(0.2)
            assert refused(https, "127.0.0.4") and refused(http_, "127.0.0.4"), \
                "one address's share covers 443 and 80 together"
            hold.append(socket.create_connection(("127.0.0.1", http_), source_address=("127.0.0.5", 0)))
            time.sleep(0.2)
            assert refused(https, "127.0.0.6"), "and so does the kiosk's total"
            for c in hold:
                c.close()
        finally:
            for s in live:
                s.shutdown(); s.server_close()
    by_ip()
    config_errors()
    unit()
    print("setup_check: ok")


class Answer:
    def __init__(self, r):
        self.status, self.location, self.body = r.status, r.getheader("Location"), r.read().decode()
        self.set, self.served, self.cookie_lines = {}, None, {}
        for line in r.headers.get_all("Set-Cookie") or []:
            k, _, v = line.split(";", 1)[0].partition("=")
            self.set[k], self.cookie_lines[k] = v, line


def by_ip():
    """setting it up by IP address (on by default), logging in, and handing over from the temporary login"""
    import hashlib
    saved = admin.SCRYPT, admin.SETUP
    admin.SCRYPT = {"n": 2 ** 10, "r": 8, "p": 1}   # quick for the test
    try:
        with tempfile.TemporaryDirectory() as d:
            admin.SETUP = f"{d}/run/setup.json"
            root, leaf = chain(d)
            cert, key = leaf("good", f"{ID}.kiosk.local")
            name_ctx = admin.context(cert, key)
            addrs = ["127.0.0.1", "127.0.0.2"]
            ipc, ipk = admin.ip_cert(addrs, f"{d}/ip.pem", f"{d}/ip.key")
            temp = {"user": "Kiosk-Test", "password": "alpha-bravo-" + os.urandom(3).hex()}
            on = {**config.DEFAULTS, "id": ID, "setup": True}
            on.pop("setup_by_ip", None)   # nobody set it: the default has to be on

            def start(cfg, login, ctx=name_ctx):
                https, http_ = free_port(), free_port()
                live = admin.servers(cfg, addrs, ctx, https, http_, ip_ctx=admin.context(ipc, ipk), temp=dict(temp), login=login)
                for s in live:
                    threading.Thread(target=s.serve_forever, daemon=True).start()
                return live, https, http_

            def stop(live):
                for s in live:
                    s.shutdown(); s.server_close()

            def call(port, method, path, host, sni=None, local="127.0.0.1", source="127.0.0.1", headers=None, form=None,
                     cookies=None):
                """one request; sni None is how a browser asks for a bare address"""
                ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
                c = http.client.HTTPSConnection(local, port, timeout=10)
                c.sock = ctx.wrap_socket(socket.create_connection((local, port), timeout=10, source_address=(source, 0)),
                                         server_hostname=sni)
                body = urllib.parse.urlencode(form).encode() if form is not None else None
                hdrs = {"Host": host, **(headers or {})}
                if cookies:
                    hdrs["Cookie"] = "; ".join(f"{k}={v}" for k, v in cookies.items())
                if body is not None:
                    hdrs.update({"Content-Type": "application/x-www-form-urlencoded", "Content-Length": str(len(body))})
                c.request(method, path, body=body, headers=hdrs)
                served = c.sock.getpeercert(binary_form=True)
                a = Answer(c.getresponse()); a.served = served; c.close(); return a

            def logged_in(port, host, user, password, sni=None, local="127.0.0.1", source="127.0.0.1"):
                pre = call(port, "GET", "/login", host, sni, local, source).set["__Host-pre"]
                return call(port, "POST", "/login", host, sni, local, source, {"Origin": f"https://{host}"},
                            {"pre": pre, "user": user, "password": password}, {"__Host-pre": pre})

            der = lambda pem: ssl.PEM_cert_to_DER_cert(open(pem).read().split("-----END CERTIFICATE-----")[0] + "-----END CERTIFICATE-----\n")

            # --- which certificate, by how it's asked for ---
            live, https, http_ = start(on, f"{d}/login.json")
            ip_host, name = f"127.0.0.1:{https}", f"{ID}.kiosk.local:{https}"
            try:
                assert call(https, "GET", "/up", ip_host).served == der(ipc), "a bare address gets the kiosk's own certificate"
                assert call(https, "GET", "/up", name, sni=f"{ID}.kiosk.local").served == der(cert), "its name gets the CA's"
                try:
                    call(https, "GET", "/up", "evil.example", sni="evil.example")
                    raise AssertionError("a handshake for some other name went through")
                except ssl.SSLError:
                    pass
                shown = admin.fingerprint(ipc)
                assert re.fullmatch(r"([0-9A-F]{2}:){31}[0-9A-F]{2}", shown), shown
                assert shown.replace(":", "") == hashlib.sha256(call(https, "GET", "/up", ip_host).served).hexdigest().upper(), \
                    "the fingerprint on the screen is the certificate actually served"

                # --- the modes don't cross ---
                assert call(https, "GET", "/up", ip_host).status == 200
                assert call(https, "GET", "/up", name).status == 421, "the name, on an IP connection"
                assert call(https, "GET", "/up", ip_host, sni=f"{ID}.kiosk.local").status == 421, "an IP, on a name connection"
                assert call(https, "GET", "/up", f"127.0.0.2:{https}").status == 421, "IP A's connection naming IP B"
                assert call(https, "GET", "/up", f"127.0.0.2:{https}", local="127.0.0.2").status == 200
                pre = call(https, "GET", "/login", ip_host).set["__Host-pre"]
                for origin, why in ((f"https://{name}", "name origin to an IP Host"), (f"https://127.0.0.2:{https}", "IP B to IP A"),
                                    ("null", "a null origin"), (f"http://{ip_host}", "plain http"), (None, "no origin at all")):
                    a = call(https, "POST", "/login", ip_host, headers={"Origin": origin} if origin else {},
                             form={"pre": pre, "user": temp["user"], "password": temp["password"]}, cookies={"__Host-pre": pre})
                    assert a.status == 403 and "__Host-kiosk" not in a.set, why
                pre = call(https, "GET", "/login", name, sni=f"{ID}.kiosk.local").set["__Host-pre"]
                a = call(https, "POST", "/login", name, sni=f"{ID}.kiosk.local", headers={"Origin": f"https://{ip_host}"},
                         form={"pre": pre, "user": "x", "password": "y"}, cookies={"__Host-pre": pre})
                assert a.status == 403, "IP origin to the name Host"

                # --- port 80 sends you to a fixed place, never to what the request says ---
                for host in ("evil.example", f"evil.example:{https}", ip_host, ""):
                    c = http.client.HTTPConnection("127.0.0.1", http_, timeout=5)
                    c.putrequest("GET", "/", skip_host=True)
                    if host:
                        c.putheader("Host", host)
                    c.endheaders()
                    where = c.getresponse().getheader("Location")
                    assert where == f"https://127.0.0.1:{https}/", (host, where)
                c = http.client.HTTPConnection("127.0.0.1", http_, timeout=5)
                c.request("GET", "/", headers={"Host": f"{ID}.kiosk.local"})
                assert c.getresponse().getheader("Location") == f"https://{name}/"

                # --- the throttle: 5 wrong, then it makes you wait, from that address and in total ---
                for i in range(5):
                    assert logged_in(https, ip_host, temp["user"], "wrong").status == 403, i
                a = logged_in(https, ip_host, temp["user"], temp["password"])
                assert a.status == 429 and "__Host-kiosk" not in a.set, "even the right password waits its turn"
                hashes, real = [], admin.password_ok
                admin.password_ok = lambda *x: hashes.append(1) or real(*x)
                open(f"{d}/login.json", "w").write(json.dumps({"user": "owner", **admin.hash_password("whatever-it-is")}))
                try:
                    assert logged_in(https, ip_host, "owner", "whatever-it-is").status == 429 and not hashes, \
                        "a throttled address is turned away before any scrypt runs"
                finally:
                    admin.password_ok = real; os.remove(f"{d}/login.json")
                assert logged_in(https, f"127.0.0.2:{https}", temp["user"], "wrong", local="127.0.0.2",
                                 source="127.0.0.3").status == 429, "and so does everyone else, once there've been 5"
            finally:
                stop(live)

            # --- on by default; off only when config says false; always on until the first login is replaced ---
            for cfg, has_login, want, why in ((on, True, 200, "on by default, even once set up"),
                                              ({**on, "setup_by_ip": True}, True, 200, "on when it says so"),
                                              ({**on, "setup_by_ip": False}, True, 421, "off only when it says false"),
                                              ({**on, "setup_by_ip": False}, False, 200, "always on until set up")):
                login = f"{d}/login-{has_login}.json"
                if has_login:
                    open(login, "w").write('{"user": "someone"}')
                live, https, _ = start(cfg, login)
                try:
                    assert call(https, "GET", "/up", f"127.0.0.1:{https}").status == want, why
                finally:
                    stop(live)

            # --- a verifier that's there but broken counts as set: it never reopens first-boot setup ---
            for bad in ("", "{not json", "[]", '{"user": "x"}', None):   # None: there, but unreadable
                login = f"{d}/broken.json"
                if os.path.exists(login):
                    os.chmod(login, 0o600)
                open(login, "w").write(bad or '{"user": "x"}')
                if bad is None:
                    os.chmod(login, 0)
                live, https, _ = start({**on, "setup_by_ip": False}, login)
                try:
                    assert call(https, "GET", "/up", f"127.0.0.1:{https}").status == 421, f"broken login {bad!r} reopened setup"
                    a = logged_in(https, f"{ID}.kiosk.local:{https}", temp["user"], temp["password"], sni=f"{ID}.kiosk.local")
                    assert a.status == 403 and "__Host-kiosk" not in a.set, f"the temporary login worked past {bad!r}"
                finally:
                    stop(live)

            # --- the handover, by IP, with no CA certificate at all, both ways the switch can be ---
            for switch, stays in ((None, True), (False, False)):
                cfg = dict(on) if switch is None else {**on, "setup_by_ip": switch}
                login = f"{d}/handover-{switch}.json"
                live, https, _ = start(cfg, login, ctx=None)
                ip_host = f"127.0.0.1:{https}"
                err = io.StringIO()
                try:
                    with redirect_stderr(err):
                        a = logged_in(https, ip_host, temp["user"], temp["password"])
                        assert a.status == 303 and a.location == "/change", (a.status, a.location)
                        first = a.set["__Host-kiosk"]
                        assert call(https, "GET", "/", ip_host, cookies={"__Host-kiosk": first}).location == "/change", \
                            "the temporary login can only change the login"
                        form = call(https, "GET", "/change", ip_host, cookies={"__Host-kiosk": first}).body
                        csrf = re.search(r'name=csrf value="([^"]+)"', form).group(1)
                        mine = "correct-horse-" + os.urandom(4).hex()
                        a = call(https, "POST", "/change", ip_host, headers={"Origin": f"https://{ip_host}"},
                                 form={"csrf": "not-it", "user": "owner", "password": mine, "again": mine, "pairing": "open sesame now"},
                                 cookies={"__Host-kiosk": first})
                        assert a.status in (303, 403) and not os.path.exists(login), "a wrong CSRF token changes nothing"
                        a = call(https, "POST", "/change", ip_host, headers={"Origin": f"https://{ip_host}"},
                                 form={"csrf": csrf, "user": "owner", "password": mine, "again": mine, "pairing": "open sesame now"},
                                 cookies={"__Host-kiosk": first})
                        if stays:   # by IP is still on, so this connection carries on, with a new session
                            assert a.status == 303 and a.set.get("__Host-kiosk") not in (None, "", first), (a.status, a.set)
                        else:       # by IP just went off: a clear answer on this connection, and nothing to carry on with
                            assert a.status == 200 and "From now on" in a.body and a.set.get("__Host-kiosk") == "", a.status
                        assert os.stat(login).st_mode & 0o777 == 0o600
                        saved_login = open(login).read()
                        assert mine not in saved_login and temp["password"] not in saved_login, "only a hash is kept"
                        if stays:
                            assert call(https, "GET", "/", ip_host, cookies={"__Host-kiosk": first}).location == "/login", \
                                "the temporary session ended"
                            assert logged_in(https, ip_host, temp["user"], temp["password"]).status == 403, \
                                "the temporary login stops working"
                            assert logged_in(https, ip_host, "owner", mine).status == 303
                        else:
                            assert call(https, "GET", "/up", ip_host).status == 421, "and by IP is off from then on"
                    log = err.getvalue()
                    assert mine not in log and temp["password"] not in log and first not in log, "a secret reached the log"
                finally:
                    stop(live)

            # --- every field, header and limit, one at a time ---
            login = f"{d}/set.json"
            mine = "the-owners-own-" + os.urandom(3).hex()
            open(login, "w").write(json.dumps({"user": "owner", **admin.hash_password(mine)}))
            os.chmod(login, 0o600)
            live, https, _ = start(on, login)
            ip_host = f"127.0.0.1:{https}"
            try:
                def answered(*a, **k):   # a refusal, never a dropped connection
                    try:
                        return call(*a, **k).status
                    except (http.client.HTTPException, ConnectionError) as e:
                        raise AssertionError(f"the connection was dropped instead of answered: {type(e).__name__}") from None
                # non-ASCII where it's compared: user, password, the login form's token, the session's CSRF token
                pre = call(https, "GET", "/login", ip_host).set["__Host-pre"]
                for field, value in (("user", "änthony"), ("password", "pässword-ünïcode"), ("pre", "préé")):
                    form = {"pre": pre, "user": "owner", "password": "wrong", field: value}
                    assert answered(https, "POST", "/login", ip_host, headers={"Origin": f"https://{ip_host}"}, form=form,
                                    cookies={"__Host-pre": pre}) in (400, 403), f"non-ASCII {field}"
                a = logged_in(https, ip_host, "owner", mine)
                assert a.status == 303, a.status
                session = a.set["__Host-kiosk"]
                assert answered(https, "POST", "/logout", ip_host, headers={"Origin": f"https://{ip_host}"},
                                form={"csrf": "çsrf-ünïcode"}, cookies={"__Host-kiosk": session}) in (303, 400, 403), "non-ASCII csrf"

                # changing the password takes the current one
                form = call(https, "GET", "/change", ip_host, cookies={"__Host-kiosk": session}).body
                csrf = re.search(r'name=csrf value="([^"]+)"', form).group(1)
                assert re.search(r'name=current\b', form), "the change form asks for the current password"
                before = open(login).read()
                new = "a-brand-new-one-" + os.urandom(3).hex()
                for current, why in ((None, "without the current password"), ("not-it", "with the wrong current password")):
                    fields = {"csrf": csrf, "user": "owner", "password": new, "again": new, "pairing": "open sesame now"}
                    if current is not None:
                        fields["current"] = current
                    a = call(https, "POST", "/change", ip_host, headers={"Origin": f"https://{ip_host}"}, form=fields,
                             cookies={"__Host-kiosk": session})
                    assert a.status in (400, 403) and open(login).read() == before, f"the password changed {why}"
                a = call(https, "POST", "/change", ip_host, headers={"Origin": f"https://{ip_host}"},
                         form={"csrf": csrf, "current": mine, "user": "owner", "password": new, "again": new, "pairing": "open sesame now"},
                         cookies={"__Host-kiosk": session})
                assert a.status == 303 and open(login).read() != before, "and with it, it changes"
            finally:
                stop(live)

            # the throttle forgets: after about 15 quiet minutes, and a success clears the shared count too
            t, clock, real_clock = admin.Throttle(), [1000.0], admin.time.monotonic
            admin.time.monotonic = lambda: clock[0]
            try:
                for _ in range(8):
                    t.fail("10.0.0.9")
                assert t.wait("10.0.0.9") and t.wait("10.0.0.10"), "8 failures: everyone waits"
                clock[0] += 16 * 60
                assert not t.wait("10.0.0.9") and not t.wait("10.0.0.10"), "16 quiet minutes later, nobody does"
                t.fail("10.0.0.9")
                assert not t.wait("10.0.0.9"), "and the count started again, rather than carrying on from 8"
                t2 = admin.Throttle()
                for _ in range(5):
                    t2.fail("10.0.0.9")
                t2.ok("10.0.0.9")
                assert not t2.wait("10.0.0.10"), "a success clears the shared count, so one stranger can't hold it"
            finally:
                admin.time.monotonic = real_clock

            # --- races: a login or a change parked mid-way while the login changes ---
            def owner(password):
                open(login, "w").write(json.dumps({"user": "owner", **admin.hash_password(password)})); os.chmod(login, 0o600)

            def change_now(port, host, session, current, new):
                form = call(port, "GET", "/change", host, cookies={"__Host-kiosk": session}).body
                csrf = re.search(r'name=csrf value="([^"]+)"', form).group(1)
                fields = {"csrf": csrf, "user": "owner", "password": new, "again": new, "pairing": "open sesame now"}
                if current is not None:
                    fields["current"] = current
                return call(port, "POST", "/change", host, headers={"Origin": f"https://{host}"}, form=fields,
                            cookies={"__Host-kiosk": session})

            def usable(port, host, session):
                return bool(session) and call(port, "GET", "/", host, cookies={"__Host-kiosk": session}).status == 200

            for bootstrap in (False, True):
                login = f"{d}/race-{bootstrap}.json"
                if not bootstrap:
                    owner(mine)
                user, old = ("Kiosk-Test", temp["password"]) if bootstrap else ("owner", mine)
                live, https, _ = start(on, login)
                ip_host = f"127.0.0.1:{https}"
                state = live[0].RequestHandlerClass.state
                parked, go, real_start = threading.Event(), threading.Event(), admin.State.start_session
                real_thread = admin.Bounded.process_request_thread
                try:
                    first = logged_in(https, ip_host, user, old).set["__Host-kiosk"]   # the session that'll do the change

                    def park(self, temporary_login, generation):   # checked, not yet given its session
                        if threading.current_thread().name == "parked":
                            parked.set(); go.wait(10)
                        return real_start(self, temporary_login, generation)
                    admin.State.start_session = park
                    result = {}   # the server handles the parked login on a thread of its own: name that one

                    def named(self, request, client_address):
                        if client_address[0] == "127.0.0.5":
                            threading.current_thread().name = "parked"
                        return real_thread(self, request, client_address)
                    admin.Bounded.process_request_thread = named
                    t = threading.Thread(target=lambda: result.update(a=logged_in(https, ip_host, user, old, source="127.0.0.5")))
                    t.start()
                    assert parked.wait(10), "the login never reached its session"
                    new = "after-the-race-" + os.urandom(3).hex()
                    a = change_now(https, ip_host, first, None if bootstrap else old, new)
                    assert a.status in (200, 303), ("the change", a.status)
                    go.set(); t.join(15)
                    late = result["a"]
                    assert late.status == 403 and not usable(https, ip_host, late.set.get("__Host-kiosk")), \
                        f"a {'first-boot' if bootstrap else 'saved'}-password login checked before the change got in after it"
                finally:
                    admin.State.start_session, admin.Bounded.process_request_thread = real_start, real_thread
                    go.set(); stop(live)

            # two changes at once: only one replaces the login, and the other is turned away cleanly
            login = f"{d}/two.json"; owner(mine)
            live, https, _ = start(on, login)
            ip_host = f"127.0.0.1:{https}"
            try:
                s1 = logged_in(https, ip_host, "owner", mine).set["__Host-kiosk"]
                s2 = logged_in(https, ip_host, "owner", mine, source="127.0.0.6").set["__Host-kiosk"]
                gate_, outcomes = threading.Barrier(2), {}

                def racer(k, session, new):
                    gate_.wait(5); outcomes[k] = (new, change_now(https, ip_host, session, mine, new))
                pair = [threading.Thread(target=racer, args=(k, s, f"racer-{k}-" + os.urandom(3).hex())) for k, s in ((1, s1), (2, s2))]
                for p in pair:
                    p.start()
                for p in pair:
                    p.join(30)
                won = [k for k, (_, a) in outcomes.items() if a.status == 200 or (a.status == 303 and a.location == "/")]
                lost = [k for k, (_, a) in outcomes.items() if a.status == 303 and a.location == "/login"]
                assert len(won) == 1 and len(lost) == 1, {k: (a.status, a.location) for k, (_, a) in outcomes.items()}
                winner, loser = outcomes[won[0]][0], outcomes[lost[0]][0]
                stored = json.load(open(login))
                assert admin.password_ok(winner, stored) and not admin.password_ok(loser, stored), "only the winner's password is kept"
            finally:
                stop(live)

            # a session that goes away between the POST's check and the change itself: a clean redirect, not a dropped
            # connection, whether or not the form had a problem
            for short in (False, True):
                login = f"{d}/gone-{short}.json"; owner(mine)
                live, https, _ = start(on, login)
                ip_host = f"127.0.0.1:{https}"
                real_session = admin.State.session
                try:
                    session = logged_in(https, ip_host, "owner", mine).set["__Host-kiosk"]
                    form = call(https, "GET", "/change", ip_host, cookies={"__Host-kiosk": session}).body
                    csrf = re.search(r'name=csrf value="([^"]+)"', form).group(1)
                    seen = []

                    def fickle(self, token):   # good for do_POST's check, gone by the time change() looks
                        seen.append(token)
                        return real_session(self, token) if len(seen) == 1 else None
                    admin.State.session = fickle
                    new = "x" if short else "long-enough-new-" + os.urandom(3).hex()
                    a = answered(https, "POST", "/change", ip_host, headers={"Origin": f"https://{ip_host}"},
                                 form={"csrf": csrf, "current": mine, "user": "owner", "password": new, "again": new, "pairing": "open sesame now"},
                                 cookies={"__Host-kiosk": session})
                    assert a == 303, f"a session gone mid-change ({'with' if short else 'without'} a form problem): {a}"
                    assert admin.password_ok(mine, json.load(open(login))), "and nothing changed"
                finally:
                    admin.State.session = real_session; stop(live)

            # the login file is replaced, then saving it fails (the folder's fsync): every session ends, and nothing
            # says it worked
            login = f"{d}/torn.json"; owner(mine)
            live, https, _ = start(on, login)
            ip_host = f"127.0.0.1:{https}"
            real_write = admin.write_private
            try:
                session = logged_in(https, ip_host, "owner", mine).set["__Host-kiosk"]

                def torn(path, value):
                    real_write(path, value)
                    if path == login:
                        raise OSError(5, "Input/output error (after the rename)")
                admin.write_private = torn
                new = "torn-write-" + os.urandom(3).hex()
                try:
                    a = change_now(https, ip_host, session, mine, new)
                    status = a.status
                    if "__Host-kiosk" in a.set:   # a cleared cookie only takes with the same attributes, and an expiry
                        line = a.cookie_lines["__Host-kiosk"]
                        assert all(x in line for x in ("Path=/", "Secure", "Max-Age=0")), line
                    assert not (status == 200 or (status == 303 and a.location == "/")) and not a.set.get("__Host-kiosk"), \
                        f"a change that didn't save cleanly said it worked: {status} {a.location}"
                except (http.client.HTTPException, ConnectionError):
                    pass   # no answer at all is acceptable: it didn't say it worked
                admin.write_private = real_write
                assert not usable(https, ip_host, session), "every session ended"
            finally:
                admin.write_private = real_write; stop(live)

            # --- the screen: the fingerprint is in what's actually drawn, not just in setup.json ---
            from PIL import Image, ImageChops
            import kit, importlib
            setup_page = importlib.import_module("pages.setup.page")

            def shows(img, s):
                """whether s, drawn in the kiosk's font at any size it uses, is somewhere in img"""
                lit = lambda im: ImageChops.difference(im.convert("RGB"), Image.new("RGB", im.size, kit.BG)).convert("L").point(lambda v: 255 if v else 0)
                big, w = lit(img).tobytes(), img.width
                for scale in (1, 2, 3):
                    t = Image.new("RGB", (len(s) * 8 * scale, 16 * scale), kit.BG); kit.text(t, (0, 0), s, (255, 255, 255), scale)
                    small, tw = lit(t).tobytes(), t.width
                    rows = [small[r * tw:(r + 1) * tw] for r in range(t.height)]
                    r0 = next(r for r, row in enumerate(rows) if row.strip(b"\0"))
                    for y in range(img.height - t.height + 1):
                        line = big[(y + r0) * w:(y + r0 + 1) * w]
                        x = line.find(rows[r0])
                        while x != -1:
                            if all(big[(y + r) * w + x:(y + r) * w + x + tw] == rows[r] for r in range(t.height)):
                                return True
                            x = line.find(rows[r0], x + 1)
                return False
            fp = admin.fingerprint(ipc)
            other = ":".join(["AB"] * 32)
            four = [f"https://{ID}.kiosk.local", "https://192.168.1.50", "https://192.168.4.1", "https://192.168.1.51"]
            img = setup_page.draw(admin.screen(None, four, fp, done=four), time.time())
            assert shows(img, fp) and all(shows(img, w) for w in four), "four ways in and the fingerprint: none left off"
            ways = [f"https://127.0.0.1"]
            for why, info in (("right after the change", admin.screen(None, ways, fp, done=ways)),
                              ("after a restart", admin.screen(None, ways, fp)),
                              ("on first boot", admin.screen(temp, ways, fp))):
                img = setup_page.draw(info, time.time())
                assert shows(img, fp), f"the fingerprint isn't drawn {why}"
                assert not shows(img, other), "(and the check can tell)"

            # --- its own certificate is made again before it runs out, or when its key doesn't match ---
            c2, k2 = f"{d}/renew.pem", f"{d}/renew.key"
            admin.keygen(k2)
            openssl("req", "-x509", "-new", "-key", k2, "-days", "1", "-subj", "/CN=127.0.0.1",
                    "-addext", "subjectAltName=IP:127.0.0.1", "-out", c2)
            before = open(c2).read()
            admin.ip_cert(["127.0.0.1"], c2, k2)
            assert open(c2).read() != before and not admin.renew_due(c2), "a day from running out, it's made again"
            before = open(c2).read()
            admin.ip_cert(["127.0.0.1"], c2, k2)
            assert open(c2).read() == before, "and left alone when it's fine"
            shown_before = admin.fingerprint(c2)
            os.remove(k2); admin.keygen(k2)
            admin.ip_cert(["127.0.0.1"], c2, k2)
            assert admin.matches(c2, k2), "a new key gets a new certificate"
            assert admin.fingerprint(c2) != shown_before and admin.fingerprint(c2).replace(":", "") == \
                hashlib.sha256(der(c2)).hexdigest().upper(), "and the screen's fingerprint follows the new one"
            img = setup_page.draw(admin.screen(None, ways, admin.fingerprint(c2)), time.time())
            assert shows(img, admin.fingerprint(c2)) and not shows(img, shown_before), "the screen draws the renewed one, not the old"
            # the real scrypt parameters, both ways: what's stored can be checked again (maxmem on the verify path too)
            stored = admin.hash_password("the-real-thing", saved[0])
            assert {k: stored[k] for k in ("n", "r", "p")} == saved[0]
            assert admin.password_ok("the-real-thing", stored) and not admin.password_ok("the-real-thinG", stored)
    finally:
        admin.SCRYPT, admin.SETUP = saved


def config_errors():
    """config.json's errors reach the journal (admin.py prints them), so they never echo what was in it"""
    secret = "Tok-" + os.urandom(6).hex()   # not a valid page name, so every case is refused
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "config.json")
        for bad in ({"playlist": [{"page": "weather", "options": {"token": secret}, "colour": 1}]},
                    {"playlist": [{"page": secret}]},
                    {"playlist": [{"page": "weather", "seconds": secret}]},
                    {"playlist": [{"page": "weather", "on": secret}]},
                    {"setup": secret}, {"setup_by_ip": secret}, {"id": secret},
                    '{"id": "' + secret + '", }'):
            open(path, "w").write(bad if isinstance(bad, str) else json.dumps(bad))
            try:
                config.load(path)
            except ValueError as e:
                assert secret not in str(e), f"config.json's error echoed what was in it: {e}"
            else:
                raise AssertionError(f"{bad} loaded")


def unit(path=os.path.join(os.path.dirname(os.path.realpath(__file__)), "systemd", "kiosk-admin.service")):
    """what the unit lets the server do has to be enough for what the server does. These tests run outside systemd,
    so they'd never see a sandbox that breaks it: addresses() needs `ip`, and `ip` needs a netlink socket."""
    lines = [l.strip() for l in open(path) if "=" in l and not l.lstrip().startswith("#")]
    settings = {}
    for l in lines:
        k, v = l.split("=", 1); settings.setdefault(k, []).append(v)
    families = " ".join(settings.get("RestrictAddressFamilies", [])).split()
    if families and not families[0].startswith("~"):
        assert "AF_NETLINK" in families, f"RestrictAddressFamilies={' '.join(families)} stops `ip` finding the addresses"
        try:   # and for real, where systemd-run is there to try it (a desktop; the Pi's kiosk user has no user manager)
            out = subprocess.run(["systemd-run", "--user", "--quiet", "--wait", "--pipe", "-p",
                                  f"RestrictAddressFamilies={' '.join(families)}", "ip", "-4", "-o", "addr"],
                                 capture_output=True, text=True, timeout=20)
        except (OSError, subprocess.SubprocessError):
            return
        assert "netlink" not in out.stderr.lower(), out.stderr.strip()


if __name__ == "__main__":
    check()
