"""web: the kiosk in a browser, for screens that can take more than the Pi: http://<render server>/16-9, /9-16. Each
shape has its own renderer (kiosk.py --web, with KIOSK_SHAPE set), drawing the pages that can do that shape in its
own rotation, with the transitions, and saving each changed frame as a PNG in RAM (FOLDER). The front door
(kiosk.py --front) serves a page per shape that streams those PNGs as they change (multipart PNG, which any browser
shows in a plain <img>), lossless so the pixel art stays crisp.

A renderer only draws while someone's watching: the front door touches <shape>.watch while a stream is open.
"""
import io, os, time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from PIL import Image

import kit, transitions

FOLDER = "/dev/shm/kiosk-web"
WATCHED = 10   # seconds a watch lasts without a touch
PAGE = """<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Desk Kiosk {shape}</title><style>html,body{{margin:0;height:100%;background:#05060F}}
img{{width:100vw;height:100vh;object-fit:contain;image-rendering:pixelated}}</style><img src="/{shape}/stream" alt="">"""
INDEX = """<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Desk Kiosk</title><style>body{{margin:2rem;background:#05060F;color:#E8ECFF;font:1.2rem monospace}}
a{{color:#7DF9FF}}</style><h1>Desk Kiosk</h1><ul>{links}</ul>"""


def path(shape, ext):
    return os.path.join(FOLDER, f"{shape}.{ext}")


class Browser:
    """the screen kiosk.py draws on as a shape's renderer: memory, saved as a PNG after every frame that changed it"""

    def __init__(self):
        os.makedirs(FOLDER, exist_ok=True)
        self.mm, self.saved = bytearray(kit.SCREEN[0] * kit.SCREEN[1] * 2), None

    def visible(self):
        try:
            return time.time() - os.path.getmtime(path(kit.SHAPE, "watch")) < WATCHED
        except OSError:
            return False

    def save(self):
        frame = bytes(self.mm)
        if frame != self.saved:
            buf = io.BytesIO()
            kit.unpack(Image.frombytes("LA", kit.SCREEN, frame)).save(buf, "PNG", compress_level=1)
            open(path(kit.SHAPE, "tmp"), "wb").write(buf.getvalue()); os.replace(path(kit.SHAPE, "tmp"), path(kit.SHAPE, "png"))
            self.saved = frame

    def play(self, new, theme=None):
        transitions.play(self.mm, new, theme, on_frame=lambda c: self.save())

    def flush(self):
        self.save()


class Front(BaseHTTPRequestHandler):
    def do_GET(self):
        parts = self.path.strip("/").split("/")
        shapes = [s for s in kit.SHAPES if s != "bar"]   # the bar is the Pi's
        if parts == [""]:
            return self.reply("text/html", INDEX.format(links="".join(f'<li><a href="/{s}">{s}</a>' for s in shapes)).encode())
        if parts[0] not in shapes:
            return self.send_error(404)
        if len(parts) == 1:
            return self.reply("text/html", PAGE.format(shape=parts[0]).encode())
        if parts[1:] == ["stream"]:
            return self.stream(parts[0])
        self.send_error(404)

    def reply(self, kind, body):
        self.send_response(200); self.send_header("Content-Type", kind); self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)

    def stream(self, shape):
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame"); self.send_header("Cache-Control", "no-store")
        self.end_headers()
        last, touched = None, 0.0
        try:
            while True:
                if time.time() - touched > 2:   # keep the renderer drawing
                    open(path(shape, "watch"), "a").close(); os.utime(path(shape, "watch")); touched = time.time()
                try:
                    mtime = os.path.getmtime(path(shape, "png"))
                    if mtime != last:
                        frame, last = open(path(shape, "png"), "rb").read(), mtime
                        self.wfile.write(b"--frame\r\nContent-Type: image/png\r\nContent-Length: %d\r\n\r\n" % len(frame) + frame + b"\r\n")
                except FileNotFoundError:
                    pass   # the renderer hasn't drawn yet
                time.sleep(1 / 30)
        except (BrokenPipeError, ConnectionResetError):
            pass   # they closed the tab

    def log_message(self, *args):
        pass


def front(port=80):
    os.makedirs(FOLDER, exist_ok=True)
    ThreadingHTTPServer(("", port), Front).serve_forever()


def check():
    import tempfile, threading, urllib.request
    global FOLDER
    FOLDER = tempfile.mkdtemp()
    b = Browser()
    assert not b.visible(), "nobody watching: don't draw"
    b.mm[0:2] = b"\xff\xff"; b.flush()
    first = os.path.getmtime(path(kit.SHAPE, "png")); b.flush()
    assert os.path.getmtime(path(kit.SHAPE, "png")) == first, "an unchanged frame isn't saved again"
    img = Image.open(path(kit.SHAPE, "png"))
    assert img.size == kit.SCREEN and img.getpixel((0, 0)) == (248, 252, 248), "the PNG is the frame"
    server = ThreadingHTTPServer(("127.0.0.1", 0), Front); port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    get = lambda p: urllib.request.urlopen(f"http://127.0.0.1:{port}{p}", timeout=5)
    assert b"/16-9" in get("/").read() and b"/16-9/stream" in get("/16-9").read()
    try:
        get("/nope"); raise AssertionError("an unknown shape is a 404")
    except urllib.error.HTTPError as e:
        assert e.code == 404
    os.replace(path(kit.SHAPE, "png"), path("16-9", "png"))
    r = get("/16-9/stream")
    assert r.headers["Content-Type"].startswith("multipart/x-mixed-replace") and b"image/png" in r.read(200)
    server.shutdown()
    print("web: ok")
