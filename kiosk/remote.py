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
  SHOW  a page change, before the server draws it: the payload is the page's name. Both sides keep each page's last
        frame (what the Pi had on screen when it left that page), so with a = 1 the Pi puts its copy up at once (2 and 3:
        slides it in, for a swipe to the next page or the last; see transitions.SLIDES), and what the server sends next
        is only what's changed since: a touch doesn't wait for the page to be drawn and sent
and one the Pi sends the other way:
  TUCH  a touch on the Pi's screen, as JSON (see kiosk.py's TOUCH): the server hands it to the page it's drawing
  TIME  before a group of messages: when the server drew them, in milliseconds since it started (a), as it counts them
        (a 32-bit count that wraps; the Pi unwraps it), and b"u" as the payload if they answer a touch. The Pi shows
        them that long after the server drew them, whatever the link did to them on the way, so a stall (TCP waits out
        a lost packet, then delivers a clump) plays out as the server drew it, not as a freeze and a rush. A touch's
        answer isn't held. No TIME (an older server), and the Pi shows each as it arrives. An older Pi ignores it
  DONE  how many transitions (and slides) the Pi has played since it connected, as JSON {"played": 3}. It sends one as
        soon as the server first speaks, which says it will answer, and one after each. (Not on connecting: a Pi
        says nothing then, and a server hangs up on anything else.) A server that's been told holds the next frames
        until the Pi has played everything it was sent, however long a theme takes on the Pi; without one, it holds for
        the theme's length, a guess (a server doesn't load the themes, so it never knew their real lengths). A server
        from before this ignores it, since it isn't a touch

REMOTE (~/.config/kiosk/remote.json) says where the server is: {"server": "<address>", "port": 7676}. Without it, or
when it can't be reached, the Pi draws the pages itself.
Standard library only.
"""
import json, os, queue, socket, struct, threading, time, zlib

import kit, link, transitions

HERE = os.path.dirname(os.path.realpath(__file__))
REMOTE = os.path.expanduser("~/.config/kiosk/remote.json")   # this kiosk's own server, which updates leave alone
STRIDE = kit.SCREEN[0] * 2
SIZE = STRIDE * kit.SCREEN[1]
HEADER = struct.Struct("<4sII")
GAP, PING, TIMEOUT = 8, 5, 20   # rows apart that still go as one band; seconds between pings; seconds before giving up
DELAY, CREEP = 0.4, 0.00005     # seconds the Pi holds each frame after the server drew it (see TIME), and how far its
                                # idea of the link's best case may drift a message, for the two clocks running apart


def config():
    """remote.json -> (host, port), or None to draw locally"""
    try:
        c = json.load(open(REMOTE))
        return (c["server"], c.get("port", 7676)) if c.get("server") else None
    except (OSError, ValueError, KeyError):
        return None


def delay():
    """remote.json's "delay": seconds the Pi holds each frame after the server drew it, to even out a Wi-Fi link that
    stalls and then delivers a clump (0 to show them as they arrive), or DELAY"""
    try:
        d = float(json.load(open(REMOTE)).get("delay", DELAY))
        return d if 0 <= d <= 5 else DELAY
    except (OSError, ValueError, TypeError, AttributeError):
        return DELAY


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
        self.acks, self.expected, self.played = False, 0, 0   # does the Pi say when a transition is done (DONE), and how
                                                              # many it's been sent and has played
        self.kept, self.current = {}, None   # each page's last frame, as the Pi keeps it (see SHOW), and the page up
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
            self.acks, self.expected, self.played, self.quiet = False, 0, 0, 0.0   # and no transition in flight
            self.kept, self.current = {}, None   # and starts with nothing kept, as the Pi does
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
                elif kind == b"DONE" and isinstance(at, dict) and isinstance(at.get("played"), int):
                    self.done(at["played"])
        except (OSError, ValueError, ConnectionError, struct.error):
            pass   # it hung up, or sent nonsense: the screen's side finds out on its next send

    def stamp(self, urgent=False):
        """TIME, before a group of messages: when they were drawn (see TIME above)"""
        if self.conn:
            self.send(b"TIME", int(time.monotonic() * 1000) & 0xFFFFFFFF, b"u" if urgent else b"")

    def done(self, played):
        """the Pi says how many transitions it has played: once it's played all it was sent, frames can go again"""
        self.acks, self.played = True, max(self.played, played)
        if self.played >= self.expected:
            self.quiet = 0.0

    def hold(self, seconds):
        """no frames while the Pi plays a transition, which must be called before the transition is sent, since the
        Pi's DONE can be back before send() returns. If the Pi answers, until it has (seconds + 5 s is the longest to
        wait, if it never does); if not, for the theme's length, as a guess"""
        self.expected += 1
        self.quiet = time.time() + seconds + (5 if self.acks else 0.5)

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

    def page(self, name, instant, theme=None):
        """kiosk.py's main(), as a new page comes up: tell the Pi (SHOW), and on an instant change (a touch, no
        transition) have it put up its own copy of the page's last frame, if it has one, or slide it in for a swipe
        (theme: one of transitions.SLIDES). True if the Pi's doing that, so there's nothing for main() to show yet."""
        if self.conn and self.current is not None and self.sent is not None:
            self.kept[self.current] = self.sent   # what the Pi has on screen now, which it keeps too
        up = instant and name in self.kept
        how = (2 if transitions.SLIDES.get(theme) == 1 else 3) if up and theme in transitions.SLIDES else int(up)
        if how > 1 and self.conn:   # the Pi's about to slide: what changed can wait till it's done
            self.hold(transitions.SLIDE + 0.2)
        self.stamp(urgent=instant)   # an instant change answers a touch, which shouldn't wait
        shown = bool(self.conn) and self.send(b"SHOW", how, name.encode()) and up
        if shown:
            self.sent = self.kept[name]
        self.current = name
        return shown

    def play(self, new, theme=None):
        """a page change: the Pi plays the transition into new, and the server waits it out before sending more"""
        self.mm[:] = new
        if self.conn:
            name = theme or next(transitions.ORDER)
            # the theme's own length if it's loaded here; if not (a server doesn't load them), the usual one. That only
            # matters to a Pi that doesn't say when it's done: one that does is waited for
            seconds = transitions.SLIDE if name in transitions.SLIDES else getattr(transitions.THEMES[name], "SECONDS", transitions.SECONDS)
            self.hold(seconds)
            self.stamp()
            if self.send(b"TRAN", len(name), name.encode() + zlib.compress(new, 1)):
                self.sent = bytes(new)

    def flush(self):
        """after a frame: send the Pi what changed, or a ping if it's been a while"""
        if not self.conn or time.time() < self.quiet:
            return
        if self.sent is None:
            self.stamp()
            if self.send(b"ROWS", 0, zlib.compress(bytes(self.mm), 1)):
                self.sent = bytes(self.mm)
            return
        changed = bands(self.sent, self.mm)
        if changed:
            self.stamp()
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


def forward(sock, touch, wake, lock=None):
    """the Pi's touches (its touch file, written by touchpanel.py) up the link to the server, until it closes. wake is
    set the moment there's a touch (kiosk.py's WAKE), so it goes straight away; the timeout is for anything else that
    writes the file, like kiosk-ctl."""
    seen = os.path.getmtime(touch) if os.path.exists(touch) else None
    lock = lock or threading.Lock()   # the socket has other writers (the transitions' DONE): one message at a time
    while True:
        wake.wait(0.1); wake.clear()
        try:
            mtime = os.path.getmtime(touch)
            if mtime != seen:
                seen, body = mtime, open(touch, "rb").read()
                with lock:
                    sock.sendall(HEADER.pack(b"TUCH", 0, len(body)) + body)
        except FileNotFoundError:
            pass
        except OSError:
            return


def client(address, mm, play=transitions.play, stop=None, touch=None, wake=None, delay=DELAY):
    """the Pi's side: put what the server sends on the screen, until the link drops (then it raises) or stop() says
    the Pi has something of its own to show. The server pings every few seconds, so that's checked often enough.
    touch: the Pi's touch file, whose touches go up to the server, and wake what says there's a new one.
    delay: seconds after the server drew a frame that it's shown (see TIME), or 0 to show each as it arrives."""
    sock = socket.create_connection(address, timeout=5)
    sock.settimeout(TIMEOUT)
    lock, played = threading.Lock(), [0]

    def tell():
        """DONE: how many transitions this Pi has played, so the server knows when to send frames again"""
        body = json.dumps({"played": played[0]}).encode()
        with lock:
            sock.sendall(HEADER.pack(b"DONE", 0, len(body)) + body)

    def play_one(*args):
        play(*args)
        played[0] += 1; tell()
    if touch:
        threading.Thread(target=forward, args=(sock, touch, wake or threading.Event(), lock), daemon=True).start()
    print(f"remote: showing {address[0]}:{address[1]}", flush=True)

    inbox, rush = queue.Queue(), [-1]   # what's come in, with when to show it; and the last message that mustn't wait

    def listen():
        """the socket's reader. It never waits on the screen, so a long transition doesn't back the link up, and it
        works out when each message should be shown: when the server drew it, plus the delay, on this clock. The
        link's best case so far (the smallest gap between a message's arrival and its time) is what lines the two
        clocks up, so a late message is late and an on-time one isn't, whatever the clocks say."""
        base, due, last, wrap, seq, heard = None, None, 0, 0, 0, False
        try:
            while True:
                kind, a, n = HEADER.unpack(read(sock, HEADER.size))
                payload = read(sock, n)
                if not heard:   # once the server has spoken, it's taken us for a Pi: now we can say we answer
                    heard = True; tell()   # transitions. Not before: a server that hears anything first takes it for a settings message
                if kind == b"TIME":
                    at = a + wrap
                    if at + 2 ** 31 < last:   # the server's 32-bit count wrapped
                        wrap += 2 ** 32; at += 2 ** 32
                    last, now = at, time.monotonic()
                    base = now - at / 1000 if base is None else min(base + CREEP, now - at / 1000)
                    due = base + at / 1000 + delay
                    if payload == b"u":
                        rush[0] = seq
                    continue
                inbox.put((seq, due if delay else None, kind, a, payload))
                seq += 1
        except Exception as e:   # the link went (or the server hung up): the screen's side raises it, after what's here
            inbox.put((None, None, e, None, None))
    threading.Thread(target=listen, daemon=True).start()

    kept, current = {}, None   # each page's last frame, as the server keeps it (see SHOW)
    try:
        while True:
            try:
                seq, due, kind, a, payload = inbox.get(timeout=1)
            except queue.Empty:
                if stop and stop():
                    return
                continue
            if seq is None:
                raise kind
            if due is not None and seq > rush[0]:   # a touch's answer, and what's queued before it, isn't held
                wait = due - time.monotonic()
                if wait > 0:
                    time.sleep(min(wait, delay + 1))   # never longer than the delay allows, whatever the clocks did
            if kind == b"ROWS":
                rows = zlib.decompress(payload)
                mm[a * STRIDE:a * STRIDE + len(rows)] = rows
            elif kind == b"RECT":
                x, w = struct.unpack("<HH", payload[:4]); rect, w2 = zlib.decompress(payload[4:]), w * 2
                for i in range(len(rect) // w2):
                    o = (a + i) * STRIDE + x * 2; mm[o:o + w2] = rect[i * w2:(i + 1) * w2]
            elif kind == b"TRAN":
                play_one(mm, zlib.decompress(payload[a:]), payload[:a].decode())
            elif kind == b"SHOW":
                if current is not None:
                    kept[current] = bytes(mm)
                current = payload.decode()
                if a and current in kept:
                    if a == 1:
                        mm[:] = kept[current]
                    else:   # a swipe: slide it in, the way the finger went
                        play_one(mm, kept[current], "slide-next" if a == 2 else "slide-prev")
            if stop and stop():
                return
    finally:
        sock.close()


def check():
    old, new = bytearray(SIZE), bytearray(SIZE)
    new[3 * STRIDE] = 1; new[10 * STRIDE + 5] = 1; new[200 * STRIDE] = 1
    assert bands(old, new) == [[3, 11], [200, 201]], bands(old, new)
    assert bands(new, new) == []
    assert columns(old, new, 3, 11) == (0, 3), columns(old, new, 3, 11)   # bytes 0 and 5: pixels 0 to 2
    assert columns(new, new, 0, 515) == (kit.SCREEN[0], 0), "nothing changed, nothing to send"
    # the whole round trip, over loopback: a full screen, some changed rows, a transition
    server = Server(0); port = server.listener.getsockname()[1]
    seen, mm, gate = [], bytearray(SIZE), threading.Event()
    gate.set()   # clear it and a transition takes as long as the test wants, like a slow Pi
    def fake_play(mm, frame, name):
        gate.wait(10); seen.append(name); mm[:] = frame
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
    # the Pi says when a transition is done, and the server waits for that, not for a guess at the theme's length
    for _ in range(100):
        if server.acks and server.played == server.expected:
            break
        time.sleep(0.02)
    assert server.acks and server.played == server.expected == 1, "it said it answers, and has played the one"
    sends = []; real_send = server.send
    server.send = lambda kind, a, p=b"": (kind != b"TIME" and sends.append(kind)) or real_send(kind, a, p)
    theme = next(iter(transitions.THEMES))
    gate.clear()                                  # a slow Pi: still playing
    server.mm[:] = bytes([8]) * SIZE; server.play(bytes([8]) * SIZE, theme)
    held = server.quiet - time.time()
    server.mm[0:2] = b"\xaa\xaa"; server.flush(); time.sleep(0.3); server.flush()
    assert sends == [b"TRAN"], f"nothing but the transition goes while the Pi is still playing it: {sends}"
    gate.set()                                    # it's done
    for _ in range(100):
        if server.quiet == 0.0:
            break
        time.sleep(0.02)
    assert server.quiet == 0.0 and held > 3, "its DONE lets frames go well before the cap, which was %.1f s off" % held
    server.flush()
    for _ in range(100):
        if mm[0:2] == b"\xaa\xaa":
            break
        time.sleep(0.02)
    assert sends == [b"TRAN", b"RECT"] and mm == server.mm, f"and then the change goes: {sends}"
    # one that never says: the theme's length, as before (and the Pi, held in its transition, can't have said)
    server.acks = False; gate.clear(); server.expected = server.played = 0
    server.play(bytes([9]) * SIZE, theme)
    guess = server.quiet - time.time()
    assert abs(held - guess - 4.5) < .3, f"without DONE it holds {guess:.1f} s, not {held:.1f}: 4.5 s less"
    gate.set()
    for _ in range(100):
        if mm == server.mm:
            break
        time.sleep(0.02)
    assert mm == server.mm
    server.send = real_send; seen.clear()
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
    for _ in range(100):   # the Pi shows a frame a moment after the server draws it (TIME)
        if mm[0:2] == b"\x0b\x0b":
            break
        time.sleep(0.02)
    assert mm[0:2] == b"\x0b\x0b" and json.load(open(theirs)) == {"gesture": "next"} and pokes, "frames come down, and touches go up"
    # SHOW: a page the Pi has had up before comes straight back from its own copy, and only changes follow
    def settle(want):
        for _ in range(100):
            if mm == want:
                return True
            time.sleep(0.02)
        return False
    server.page("a", False); server.mm[:] = bytes([1]) * SIZE; server.flush()
    assert settle(server.mm), "page a is up"
    server.page("b", False); server.mm[:] = bytes([2]) * SIZE; server.flush()
    assert settle(server.mm), "then page b"
    sends = []; real = server.send; server.send = lambda kind, a, p=b"": (kind != b"TIME" and sends.append(kind)) or real(kind, a, p)
    server.page("a", True)
    assert settle(bytes([1]) * SIZE), "a touch back to a: the Pi's own copy, before the server has drawn anything"
    server.mm[:] = bytes([1]) * SIZE; server.mm[5] = 9; server.flush()
    assert settle(server.mm) and sends == [b"SHOW", b"RECT"], "and then only what changed"
    server.send = real
    seen.clear()
    assert server.page("b", True, "slide-prev") and settle(bytes([2]) * SIZE), "a swipe back to b: the Pi slides in its copy"
    assert seen == ["slide-prev"], "the way the finger went"
    assert not server.page("c", True, "slide-next"), "a page the Pi hasn't had: nothing to slide yet, main() does it once drawn"
    done.set(); server.mm[0:2] = b"\x0c\x0c"; server.flush(); pi.join(5)
    server.listener.close()
    # a stall on the link and then a clump: the Pi shows the frames as far apart as the server drew them
    class Logged(bytearray):
        def __init__(self, *a):
            super().__init__(*a); self.log = []
        def __setitem__(self, k, v):
            self.log.append(time.monotonic()); super().__setitem__(k, v)
    def wait_for(test, seconds=3):
        for _ in range(int(seconds / 0.02)):
            if test():
                return True
            time.sleep(0.02)
        return False
    server = Server(0); port = server.listener.getsockname()[1]
    mm2, done = Logged(SIZE), threading.Event()
    pi = threading.Thread(target=lambda: client(("127.0.0.1", port), mm2, fake_play, done.is_set, delay=0.5), daemon=True)
    pi.start()
    assert wait_for(lambda: server.conn), "the Pi connected"
    server.flush()   # the whole screen first
    assert wait_for(lambda: len(mm2.log) == 1), "and it's up"
    real = server.send; held = []
    server.send = lambda kind, a, p=b"": held.append((kind, a, p)) or True   # the link stalls
    for i in range(1, 6):
        server.mm[0:2] = bytes([i, i]); server.flush(); time.sleep(0.1)
    server.send = real
    for m in held:   # and delivers it all at once, no later than the delay
        real(*m)
    assert wait_for(lambda: len(mm2.log) == 6) and mm2[0:2] == b"\x05\x05", "all five frames get there"
    gaps = [b - a for a, b in zip(mm2.log[1:], mm2.log[2:])]
    assert min(gaps) > 0.06 and mm2.log[-1] - mm2.log[1] > 0.3, f"as spaced as they were drawn, not a rush: {gaps}"
    # an answer to a touch isn't held for the delay
    server.page("a", False); server.mm[:] = bytes([1]) * SIZE; server.flush()
    assert wait_for(lambda: mm2 == server.mm), "page a is up"
    server.page("b", False); server.mm[:] = bytes([2]) * SIZE; server.flush()
    assert wait_for(lambda: mm2 == server.mm), "then page b"
    asked = time.monotonic(); server.page("a", True)
    assert wait_for(lambda: mm2 == bytes([1]) * SIZE) and time.monotonic() - asked < 0.3, "a touch back to a isn't held"
    done.set(); server.mm[0:2] = b"\x0d\x0d"; server.flush(); pi.join(5)
    server.listener.close()
    # a server from before TIME says nothing of when: each message is shown as it comes
    old = socket.create_server(("127.0.0.1", 0)); port = old.getsockname()[1]
    mm3, done = bytearray(SIZE), threading.Event()
    pi = threading.Thread(target=lambda: client(("127.0.0.1", port), mm3, fake_play, done.is_set, delay=0.5), daemon=True)
    pi.start()
    conn, _ = old.accept()
    began, row = time.monotonic(), zlib.compress(b"\x07" * STRIDE, 1)
    conn.sendall(HEADER.pack(b"ROWS", 0, len(row)) + row)
    assert wait_for(lambda: mm3[:4] == b"\x07" * 4) and time.monotonic() - began < 0.3, "no TIME: shown as it arrives"
    done.set(); conn.sendall(HEADER.pack(b"PING", 0, 0)); pi.join(5); conn.close(); old.close()
    assert not pi.is_alive()
    assert delay() == DELAY or os.path.exists(REMOTE), "the delay is DELAY unless remote.json says"
    print("remote: ok")
