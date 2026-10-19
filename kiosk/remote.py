"""remote: the kiosk drawn on a server and shown on the Pi. The Pi Zero is slow at drawing but quick at copying, so the
pages run on the render server (kiosk.py --serve, on another machine), and the Pi just puts what it's sent on its screen.

The server keeps a copy of what the Pi has. After every frame it compares, and sends only what changed,
zlib-compressed (pixel art squeezes about 25 to 1): whole rows when the change is wide (one copy on the Pi), or just the
rectangle that changed when it's narrow, like the radar's sweep (less to unpack). When the page changes it sends the new
page's whole frame and which transition to play, and the Pi plays it itself: transitions are already cheap on the Pi,
and streaming one would cost more than playing it. When nothing changes it sends a ping every few seconds, so the Pi
can tell a still page from a dead link.

Every message is a 12-byte header (kind, a, payload length) and its payload:
  ROWS  a = the first row; the payload is the rows, compressed
  RECT  a = the first row; the payload is x and width (two shorts), then the rectangle's rows, compressed
  TRAN  a = the length of the transition's name; the payload is the name, then the whole frame, compressed
  PING  nothing
and one the Pi sends the other way:
  TUCH  a touch on the Pi's screen, as JSON (see kiosk.py's TOUCH): the server hands it to the page it's drawing

REMOTE (~/.config/kiosk/remote.json) says where the server is: {"server": "<address>", "port": 7676}. Without it, or
when it can't be reached, the Pi draws the pages itself.
Standard library only.
"""
import json, os, socket, struct, threading, time, zlib

import kit, link, transitions

HERE = os.path.dirname(os.path.realpath(__file__))
REMOTE = os.path.expanduser("~/.config/kiosk/remote.json")   # this kiosk's own server, which updates leave alone
STRIDE = kit.SCREEN[0] * 2
SIZE = STRIDE * kit.SCREEN[1]
HEADER = struct.Struct("<4sII")
GAP, PING, TIMEOUT = 8, 5, 20   # rows apart that still go as one band; seconds between pings; seconds before giving up


def config():
    """remote.json -> (host, port), or None to draw locally"""
    try:
        c = json.load(open(REMOTE))
        return (c["server"], c.get("port", 7676)) if c.get("server") else None
    except (OSError, ValueError, KeyError):
        return None


def columns(old, new, top, bottom):
    """the leftmost and rightmost pixel that differs between two screens in rows top to bottom (XOR as big integers:
    C speed, no per-byte loop)"""
    left, right = kit.SCREEN[0], 0
    for y in range(top, bottom):
        a = y * STRIDE
        x = int.from_bytes(old[a:a + STRIDE], "big") ^ int.from_bytes(new[a:a + STRIDE], "big")
        if x:
            left = min(left, (STRIDE - (x.bit_length() + 7) // 8) // 2)
            right = max(right, (STRIDE - ((x & -x).bit_length() - 1) // 8 - 1) // 2 + 1)
    return left, right


def bands(old, new):
    """the rows that differ between two screens -> [(first row, row after the last)], near neighbours merged"""
    out = []
    for y in range(kit.SCREEN[1]):
        a = y * STRIDE
        if old[a:a + STRIDE] != new[a:a + STRIDE]:
            if out and y - out[-1][1] <= GAP:
                out[-1][1] = y + 1
            else:
                out.append([y, y + 1])
    return out


class Server:
    """the screen kiosk.py draws on when it serves: memory, with whatever changed sent on to the Pi after each frame"""

    def __init__(self, port, touch=None, poke=lambda: None):
        self.mm, self.sent, self.conn, self.quiet, self.pinged = bytearray(SIZE), None, None, 0.0, 0.0
        self.touch, self.poke = touch, poke   # where the Pi's touches go (kiosk.py's TOUCH), and what wakes the display
        self.listener = socket.create_server(("", port), reuse_port=False)
        threading.Thread(target=self.accept, daemon=True).start()

    def accept(self):
        nonces = link.Nonces()
        while True:
            conn, addr = self.listener.accept()
            conn.settimeout(0.5)
            try:   # a setup page with a settings message starts with CONF (link.py); a Pi says nothing and waits
                first = conn.recv(4, socket.MSG_PEEK | socket.MSG_WAITALL)
            except OSError:   # the half second ran out with nothing said: a Pi
                first = None
            if first == b"CONF":
                threading.Thread(target=link.answer, args=(conn, link.key(), link.settings, nonces), daemon=True).start()
                continue
            if first is not None:   # it said something else, or hung up straight away: not a Pi, so the Pi keeps its screen
                conn.close()
                continue
            conn.settimeout(None)
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            print(f"remote: the Pi connected from {addr[0]}", flush=True)
            if self.conn:
                self.conn.close()
            self.sent, self.conn = None, conn   # a new connection gets the whole screen
            threading.Thread(target=self.touches, args=(conn,), daemon=True).start()

    def touches(self, conn):
        """what the Pi sends: its touches, into the touch file, until the connection goes"""
        try:
            while True:
                kind, _, n = HEADER.unpack(read(conn, HEADER.size))
                if n > 1024:
                    raise ConnectionError("not a touch")
                at = json.loads(read(conn, n))
                if kind == b"TUCH" and self.touch and isinstance(at, dict):
                    os.makedirs(os.path.dirname(self.touch), exist_ok=True)
                    json.dump(at, open(self.touch + ".tmp", "w")); os.replace(self.touch + ".tmp", self.touch)
                    self.poke()
        except (OSError, ValueError, ConnectionError, struct.error):
            pass   # it hung up, or sent nonsense: the screen's side finds out on its next send

    def send(self, kind, a, payload=b""):
        try:
            self.conn.sendall(HEADER.pack(kind, a, len(payload)) + payload)
            self.pinged = time.time()
            return True
        except OSError:
            self.conn.close(); self.conn = None
            return False

    def visible(self):
        return True

    def play(self, new):
        """a page change: the Pi plays the transition into new, and the server waits it out before sending more"""
        self.mm[:] = new
        if self.conn:
            name = next(transitions.ORDER)
            if self.send(b"TRAN", len(name), name.encode() + zlib.compress(new, 1)):
                self.sent = bytes(new)
                # the theme's own length if it's loaded here; if not (a server doesn't load them), the usual one: a
                # longer theme's frames just wait on the Pi, which reads the next message once the transition's done
                module = transitions.THEMES[name]
                self.quiet = time.time() + getattr(module, "SECONDS", transitions.SECONDS) + 0.5

    def flush(self):
        """after a frame: send the Pi what changed, or a ping if it's been a while"""
        if not self.conn or time.time() < self.quiet:
            return
        if self.sent is None:
            if self.send(b"ROWS", 0, zlib.compress(bytes(self.mm), 1)):
                self.sent = bytes(self.mm)
            return
        changed = bands(self.sent, self.mm)
        for top, bottom in changed:
            left, right = columns(self.sent, self.mm, top, bottom)
            if right - left > kit.SCREEN[0] * 0.6:   # wide: whole rows, one copy on the Pi
                ok = self.send(b"ROWS", top, zlib.compress(bytes(self.mm[top * STRIDE:bottom * STRIDE]), 1))
            else:                                     # narrow: just the rectangle, much less to unpack
                rect = b"".join(self.mm[y * STRIDE + left * 2:y * STRIDE + right * 2] for y in range(top, bottom))
                ok = self.send(b"RECT", top, struct.pack("<HH", left, right - left) + zlib.compress(rect, 1))
            if not ok:
                return
        if changed:
            self.sent = bytes(self.mm)
        elif time.time() - self.pinged > PING:
            self.send(b"PING", 0)


def read(sock, n):
    data = bytearray()
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            raise ConnectionError("the server hung up")
        data += chunk
    return bytes(data)


def forward(sock, touch, every=0.05):
    """the Pi's touches (its touch file, written by touchpanel.py) up the link to the server, until it closes"""
    seen = os.path.getmtime(touch) if os.path.exists(touch) else None
    while True:
        time.sleep(every)
        try:
            mtime = os.path.getmtime(touch)
            if mtime != seen:
                seen, body = mtime, open(touch, "rb").read()
                sock.sendall(HEADER.pack(b"TUCH", 0, len(body)) + body)
        except FileNotFoundError:
            pass
        except OSError:
            return


def client(address, mm, play=transitions.play, stop=None, touch=None):
    """the Pi's side: put what the server sends on the screen, until the link drops (then it raises) or stop() says
    the Pi has something of its own to show. The server pings every few seconds, so that's checked often enough.
    touch: the Pi's touch file, whose touches go up to the server."""
    sock = socket.create_connection(address, timeout=5)
    sock.settimeout(TIMEOUT)
    if touch:
        threading.Thread(target=forward, args=(sock, touch), daemon=True).start()
    print(f"remote: showing {address[0]}:{address[1]}", flush=True)
    while True:
        kind, a, n = HEADER.unpack(read(sock, HEADER.size))
        payload = read(sock, n)
        if kind == b"ROWS":
            rows = zlib.decompress(payload)
            mm[a * STRIDE:a * STRIDE + len(rows)] = rows
        elif kind == b"RECT":
            x, w = struct.unpack("<HH", payload[:4]); rect, w2 = zlib.decompress(payload[4:]), w * 2
            for i in range(len(rect) // w2):
                o = (a + i) * STRIDE + x * 2; mm[o:o + w2] = rect[i * w2:(i + 1) * w2]
        elif kind == b"TRAN":
            play(mm, zlib.decompress(payload[a:]), payload[:a].decode())
        if stop and stop():
            sock.close()
            return


def check():
    old, new = bytearray(SIZE), bytearray(SIZE)
    new[3 * STRIDE] = 1; new[10 * STRIDE + 5] = 1; new[200 * STRIDE] = 1
    assert bands(old, new) == [[3, 11], [200, 201]], bands(old, new)
    assert bands(new, new) == []
    assert columns(old, new, 3, 11) == (0, 3), columns(old, new, 3, 11)   # bytes 0 and 5: pixels 0 to 2
    assert columns(new, new, 0, 515) == (kit.SCREEN[0], 0), "nothing changed, nothing to send"
    # the whole round trip, over loopback: a full screen, some changed rows, a transition
    server = Server(0); port = server.listener.getsockname()[1]
    seen, mm = [], bytearray(SIZE)
    def fake_play(mm, frame, name):
        seen.append(name); mm[:] = frame
    done = threading.Event()
    pi = threading.Thread(target=lambda: client(("127.0.0.1", port), mm, fake_play, stop=done.is_set), daemon=True)
    pi.start()
    for _ in range(100):
        if server.conn:
            break
        time.sleep(0.02)
    server.mm[0:4] = b"\x01\x02\x03\x04"; server.flush()
    server.mm[100 * STRIDE:100 * STRIDE + 2] = b"\xff\xff"; server.flush()      # a narrow change: a RECT
    server.mm[300 * STRIDE:301 * STRIDE] = b"\x05" * STRIDE; server.flush()     # a wide one: ROWS
    frame = bytes([7]) * SIZE; server.play(frame)
    for _ in range(200):
        if seen and mm == frame:
            break
        time.sleep(0.02)
    assert seen and seen[0] in transitions.THEMES and mm == frame, "the Pi ends up with exactly what the server has"
    server.quiet = 0; server.mm[0:2] = b"\x09\x09"; server.flush()
    for _ in range(100):
        if mm[0:2] == b"\x09\x09":
            break
        time.sleep(0.02)
    assert mm == server.mm, "and keeps up after the transition"
    # a settings message, or anything else that isn't a Pi, gets its own answer and leaves the Pi's screen alone
    pi_conn = server.conn
    try:
        link.request(("127.0.0.1", port), "0" * 64, {"op": "get"})
    except ValueError:   # this machine's key isn't all zeros (or it has none): either way it's answered, and refused
        pass
    socket.create_connection(("127.0.0.1", port)).sendall(b"GET / HTTP/1.0\r\n\r\n")
    time.sleep(0.2)
    assert server.conn is pi_conn, "the Pi still has its screen"
    done.set(); server.mm[0:2] = b"\x0a\x0a"; server.flush(); pi.join(5)
    assert not pi.is_alive(), "stop() hands the screen back to the Pi at the next message"
    server.listener.close()
    # a touch on the Pi reaches the server's touch file, and wakes its display
    import tempfile
    tmp = tempfile.mkdtemp()
    pokes, theirs, ours = [], os.path.join(tmp, "server-touch.json"), os.path.join(tmp, "pi-touch.json")
    server = Server(0, theirs, lambda: pokes.append(1)); port = server.listener.getsockname()[1]
    mm, done = bytearray(SIZE), threading.Event()
    pi = threading.Thread(target=lambda: client(("127.0.0.1", port), mm, fake_play, done.is_set, ours), daemon=True)
    pi.start()
    for _ in range(100):
        if server.conn:
            break
        time.sleep(0.02)
    server.mm[0:2] = b"\x0b\x0b"; server.flush()
    time.sleep(0.2)
    json.dump({"gesture": "next"}, open(ours, "w"))
    for _ in range(100):
        if os.path.exists(theirs):
            break
        time.sleep(0.02)
    assert mm[0:2] == b"\x0b\x0b" and json.load(open(theirs)) == {"gesture": "next"} and pokes, "frames come down, and touches go up"
    done.set(); server.mm[0:2] = b"\x0c\x0c"; server.flush(); pi.join(5)
    server.listener.close()
    print("remote: ok")
