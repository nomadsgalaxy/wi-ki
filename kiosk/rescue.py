#!/usr/bin/env python3
"""rescue: gets a kiosk that's lost its Wi-Fi back on a network, without taking its SD card out. A systemd service
(systemd/kiosk-rescue.service) runs it as root.

Every 30 seconds it asks NetworkManager whether wlan0 is connected. After OFFLINE seconds without a connection, it
scans for the networks around (a Pi Zero W has one radio, so it can't scan while it's a hotspot), then turns wlan0 into
a hotspot, <hostname>-setup, with a new random password each time. It writes the hotspot's name, password and address
to STATUS, and kiosk.py shows them on the screen, so only someone standing at the kiosk can join. On the hotspot, a
small page at http://10.42.0.1 lists the networks it saw and takes a network and password. Then it drops the hotspot
and joins; if that hasn't worked within JOIN seconds, the hotspot comes back, saying so.

Passwords never go on a command line: the hotspot and the new network are NetworkManager keyfiles (root-only), loaded
with nmcli. A machine without Wi-Fi (the render server) just sleeps.

  rescue.py            run it (as root)
  rescue.py --check    self-test, no network needed
"""
import html, json, os, secrets, socket, subprocess, sys, threading, time, urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))  # -I leaves our own folder off the path
import look  # noqa: E402  the setup pages' one stylesheet

STATUS = "/run/kiosk-rescue.json"        # what kiosk.py shows while the hotspot is up
KEYFILES = "/etc/NetworkManager/system-connections"
HOTSPOT, ADDRESS = "kiosk-rescue", "10.42.0.1"
EVERY, OFFLINE, JOIN = 30, 180, 60


def nmcli(*args, timeout=60):
    return subprocess.run(["nmcli", *args], capture_output=True, text=True, timeout=timeout)


def fields(line):
    """one line of nmcli -t output -> its fields (nmcli escapes a colon in a value as \\:)"""
    out, cur, i = [], "", 0
    while i < len(line):
        if line[i] == "\\" and i + 1 < len(line):
            cur += line[i + 1]; i += 2; continue
        if line[i] == ":":
            out.append(cur); cur = ""
        else:
            cur += line[i]
        i += 1
    return out + [cur]


def state(text):
    """`nmcli -t -f DEVICE,TYPE,STATE,CONNECTION device` -> (has wifi, connected to a network that isn't the hotspot)"""
    wifi = [fields(l) for l in text.splitlines() if l and fields(l)[1:2] == ["wifi"]]
    return bool(wifi), any(f[2] == "connected" and f[3] != HOTSPOT for f in wifi)


def networks(text):
    """`nmcli -t -f SSID,SIGNAL,SECURITY device wifi list` -> [(ssid, signal, secured)], strongest first, once each"""
    best = {}
    for line in text.splitlines():
        f = fields(line)
        if len(f) >= 3 and f[0]:
            sig = int(f[1]) if f[1].isdigit() else 0
            if sig > best.get(f[0], (-1,))[0]:
                best[f[0]] = (sig, f[2] not in ("", "--"))
    return sorted(((s, sig, sec) for s, (sig, sec) in best.items()), key=lambda n: -n[1])


def keyfile(name, ssid, password, ap=False):
    """a NetworkManager keyfile: a network to join, or (ap) the hotspot"""
    sec = f"[wifi-security]\nkey-mgmt=wpa-psk\npsk={password}\n" + ("proto=rsn\npairwise=ccmp\ngroup=ccmp\n" if ap else "") if password else ""
    ipv4 = f"method=shared\naddress1={ADDRESS}/24" if ap else "method=auto"
    return (f"[connection]\nid={name}\ntype=wifi\ninterface-name=wlan0\nautoconnect={'false' if ap else 'true'}\n"
            f"{'' if ap else 'autoconnect-retries=0'}\n\n[wifi]\nmode={'ap' if ap else 'infrastructure'}\nssid={ssid}\n"
            f"{'band=bg' if ap else ''}\n\n{sec}\n[ipv4]\n{ipv4}\n\n[ipv6]\nmethod={'ignore' if ap else 'auto'}\n")


def install(name, body):
    path = os.path.join(KEYFILES, f"{name}.nmconnection")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(body)
    nmcli("connection", "load", path)
    return path


PAGE = """<!doctype html><html lang=en><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>{host}: Wi-Fi</title><style>{css}</style><div class=term><header><h1>WI-KI WI-FI</h1><span>{host}</span></header><main>
<fieldset><legend>Join a network</legend><p>This kiosk lost its Wi-Fi. Pick a network and give its password, and it will
drop this hotspot and join it. If it can't, this hotspot comes back in about a minute.</p>{note}
<form method=post action=/join class=go><label>Network<select name=ssid>{options}</select></label>
<label>Or type its name<input name=other placeholder="a hidden network"></label>
<label>Password<input name=password type=password autocomplete=off></label><button>Join</button></form></fieldset></main></div>"""


class Rescue:
    def __init__(self, host):
        self.host, self.seen, self.note, self.offline_since = host, [], "", None
        self.request, self.server, self.hotspot = None, None, False

    def page(self):
        options = "".join(f"<option value='{html.escape(s, True)}'>{html.escape(s)} ({sig}%{', open' if not sec else ''})</option>"
                          for s, sig, sec in self.seen)
        note = f"<p class=note>{html.escape(self.note)}</p>" if self.note else ""
        return PAGE.format(host=html.escape(self.host), options=options or "<option value=''>(none seen)</option>", note=note,
                           css=look.CSS)

    def serve(self):
        rescue = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.reply(rescue.page())

            def do_POST(self):
                form = urllib.parse.parse_qs(self.rfile.read(min(int(self.headers.get("Content-Length", 0)), 4096)).decode())
                ssid = (form.get("other", [""])[0] or form.get("ssid", [""])[0]).strip()
                password = form.get("password", [""])[0]
                if ssid and (not password or 8 <= len(password) <= 63):
                    rescue.request = (ssid, password)
                    self.reply(f"<meta charset=utf-8><body style='font:18px system-ui;background:#0c0e14;color:#ebebeb;padding:2em'>"
                               f"Joining {html.escape(ssid)}... this hotspot goes away now. If it comes back, it didn't work.")
                else:
                    rescue.note = "A WPA2 password is 8 to 63 characters."
                    self.reply(rescue.page())

            def reply(self, body):
                data = body.encode()
                self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.server = HTTPServer((ADDRESS, 80), Handler)   # on the hotspot only, never the kiosk's own network
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def start_hotspot(self):
        self.seen = networks(nmcli("-t", "-f", "SSID,SIGNAL,SECURITY", "device", "wifi", "list", "--rescan", "yes").stdout)
        password = "".join(secrets.choice("abcdefghjkmnpqrstuvwxyz23456789") for _ in range(10))
        ssid = f"{self.host}-setup"
        install(HOTSPOT, keyfile(HOTSPOT, ssid, password, ap=True))
        if nmcli("connection", "up", HOTSPOT).returncode == 0:
            self.hotspot = True
            write_status({"ssid": ssid, "password": password, "url": f"http://{ADDRESS}", "note": self.note})
            if not self.server:
                time.sleep(2)   # the hotspot's address takes a moment to appear
                self.serve()
            print(f"rescue: hotspot {ssid} up, {len(self.seen)} networks seen", flush=True)

    def stop_hotspot(self):
        if self.server:   # the page goes with the hotspot
            self.server.shutdown(); self.server.server_close(); self.server = None
        nmcli("connection", "down", HOTSPOT)
        self.hotspot = False
        try:
            os.remove(STATUS)
        except OSError:
            pass

    def join(self, ssid, password):
        """drop the hotspot and join ssid; True if it's connected within JOIN seconds"""
        self.stop_hotspot()
        install(ssid, keyfile(ssid, ssid, password))
        nmcli("connection", "up", ssid, timeout=JOIN + 10)
        until = time.time() + JOIN
        while time.time() < until:
            if state(nmcli("-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device").stdout)[1]:
                return True
            time.sleep(5)
        return False

    def tick(self):
        has_wifi, connected = state(nmcli("-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device").stdout)
        if not has_wifi:
            return
        if self.request:
            ssid, password = self.request; self.request = None
            if self.join(ssid, password):
                print(f"rescue: joined {ssid}", flush=True); self.offline_since, self.note = None, ""
                return
            self.note = f"Couldn't join {ssid}: check the password, and that it's a 2.4 GHz network."
            self.start_hotspot(); return
        if connected:
            self.offline_since = None
            if self.hotspot:
                self.stop_hotspot()
            return
        self.offline_since = self.offline_since or time.time()
        if not self.hotspot and time.time() - self.offline_since >= OFFLINE:
            self.start_hotspot()


def write_status(info):
    tmp = STATUS + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)   # kiosk.py, as the kiosk user, reads it
    with os.fdopen(fd, "w") as f:
        json.dump(info, f)
    os.replace(tmp, STATUS)


def check():
    assert fields(r"wlan0:wifi:connected:Hive\:76") == ["wlan0", "wifi", "connected", "Hive:76"], "nmcli's escaped colons"
    assert state("wlan0:wifi:connected:Home-IoT\nlo:loopback:connected (externally):lo\n") == (True, True)
    assert state("wlan0:wifi:connected:kiosk-rescue\n") == (True, False), "its own hotspot isn't being online"
    assert state("wlan0:wifi:disconnected:--\n") == (True, False) and state("eth0:ethernet:connected:x\n") == (False, False)
    assert networks("Home:70:WPA2\nHome:40:WPA2\nCafe:55:\n:30:WPA2\n") == [("Home", 70, True), ("Cafe", 55, False)]
    k = keyfile("Home", "Home", "secret-pass")
    assert "psk=secret-pass" in k and "mode=infrastructure" in k and "autoconnect-retries=0" in k and "method=auto" in k
    ap = keyfile(HOTSPOT, "kiosk-setup", "abcdefghjk", ap=True)
    assert "mode=ap" in ap and f"address1={ADDRESS}/24" in ap and "autoconnect=false" in ap and "method=shared" in ap
    r = Rescue("kiosk"); r.seen = [("Home", 70, True)]; r.note = "<b>"
    assert "Home (70%)" in r.page() and "&lt;b&gt;" in r.page(), "the page lists what it saw, and escapes"
    print("rescue: ok")


if __name__ == "__main__":
    if sys.argv[1:] == ["--check"]:
        check()
    elif not sys.argv[1:]:
        if os.geteuid() != 0:
            sys.exit("rescue.py runs as root (systemd does that)")
        r = Rescue(socket.gethostname())
        while True:
            try:
                r.tick()
            except Exception as e:
                print(f"rescue: {e}", flush=True)
            for _ in range(EVERY):   # a second at a time, so a Join on the page starts at once
                if r.request:
                    break
                time.sleep(1)
    else:
        sys.exit(__doc__)
