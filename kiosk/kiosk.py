#!/usr/bin/env python3
"""kiosk: the Hive76 kiosk's display. It shows the pages in playlist.json one after another on the 1920x515 bar,
drawn straight to the framebuffer (16-bit RGB565, /dev/fb0), with tty1 in graphics mode so the console stays out of
the way. If another console takes the screen it stops drawing, and repaints everything once tty1 is back.

Pages live in pages/<name>/, one package each, and share only kit.py. A page package exports:
  Page(**options)           with:
    name, seconds             what it is, and how long it stays up each time round
    fps, active()             optional: frames a second if not FPS; and whether the rotation should come to it now
                              (now playing says no when nothing is playing). A pinned page shows either way.
    start(now)                called as it comes up; the place for anything slow
    background(now)           -> (key, image): the whole screen, drawn again only when key changes
    touch(x, y)               optional: a touch on the screen at x, y, while the page is up (see TOUCH and route()). It
                              can return the name of a page to go to (the home page's tiles do)
    regions(now, t)           -> [(image, (x, y))]: what moves, every frame; t is seconds since the page came up. The
                              image can instead be raw packed bytes for whole rows of the screen, at (0, y): the
                              fastest thing to put on the screen, which now playing needs for 20 fps
  check()                   its self-test (raise AssertionError on failure)
  preview(now=None)         an RGB picture of it, for looking at without a Pi
Images are "LA" images holding packed RGB565 (kit.packed()), which is what the framebuffer takes.

playlist.json lists the pages in order: {"page": "<name>", "seconds": <optional>, "options": {<optional, for Page>}}.
A package can be in it more than once, with different options, if each has its own "name" (what the desktop and
kiosk-ctl call it).
Leave a page out, or give it "on": false (deploy/kiosk-config does that), to turn it off.

My desktop can pin a page, skip to the next or go back to the rotation through control.py, which writes CONTROL. A
pinned page starts over every time its seconds run out, so it still refreshes. The page showing goes in SHOWING.

  kiosk.py                       run the display (the Pi's tty1 does this): from the render server if
                                 ~/.config/kiosk/remote.json names one and it answers (see remote.py), otherwise
                                 drawn here
  kiosk.py --serve               be the render server: draw the pages and send them to the Pi
  kiosk.py --web                 draw this shape (KIOSK_SHAPE) for browsers, and --front to serve them (see web.py)
  kiosk.py --check               every page's self-test (about 10 minutes on the Pi; deploy.sh runs it here)
  kiosk.py --smoke               the quick version the Pi runs before it applies an update
  kiosk.py --png <page> FILE     a picture of a page
"""
import fcntl, importlib, json, mmap, os, socket, sys, threading, time
from datetime import datetime
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)  # -I leaves our own folder off the path
import kit, remote, transitions, web  # noqa: E402
from pages import setup as setup_page  # noqa: E402

FPS = 4
# the bar's are the ones control.py and kiosk-ctl use; a browser shape keeps its own, so pinning the Pi leaves it be
_suffix = "" if kit.SHAPE == "bar" else f"-{kit.SHAPE}"
CONTROL = os.path.expanduser(f"~/.cache/kiosk/control{_suffix}.json")
SHOWING = os.path.expanduser(f"~/.cache/kiosk/showing{_suffix}")
# a touch, {"x": .., "y": ..} in screen pixels: whatever reads the touch panel writes it (or kiosk-ctl touch, to try one)
TOUCH = os.path.expanduser(f"~/.cache/kiosk/touch{_suffix}.json")
# On a screen someone's touching, the rotation holds still for HOLD seconds after each touch, and a home button sits in
# the corner (HOME_BUTTON, x0, y0, x1, y1) of every page but the home page itself.
HOLD = 60
RESCUE = "/run/kiosk-rescue.json"   # rescue.py's hotspot, while the kiosk has lost its Wi-Fi: shown instead of the pages
HOME_BUTTON = (0, kit.SCREEN[1] - 72, 72, kit.SCREEN[1])
KDSETMODE, KD_TEXT, KD_GRAPHICS = 0x4B3A, 0, 1


# a kiosk can have its own playlist (its location, say) outside ~/kiosk, which updates replace whole
LOCAL_PLAYLIST = os.path.expanduser("~/.config/kiosk/playlist.json")
PLAYLIST = LOCAL_PLAYLIST if os.path.exists(LOCAL_PLAYLIST) else os.path.join(HERE, "playlist.json")


def playlist(path=PLAYLIST):
    """playlist.json -> [Page]. A page that won't load is left out (and says why), so one bad page can't stop the rest,
    and so is one that can't be drawn in this shape (Page.shapes, just the bar unless it says otherwise)."""
    pages = []
    for entry in json.load(open(path)):
        if entry.get("on") is False:   # switched off with deploy/kiosk-config
            continue
        try:
            module = importlib.import_module(f"pages.{entry['page']}")
            if kit.SHAPE not in getattr(module.Page, "shapes", ("bar",)):
                continue
            page = module.Page(**entry.get("options", {}))
            if "name" in entry:
                page.name = entry["name"]
            if "seconds" in entry:
                page.seconds = entry["seconds"]
            pages.append(page)
        except Exception as e:
            print(f"playlist: leaving out {entry}: {e}", file=sys.stderr)
    return pages


def active_vt():
    try:
        return open("/sys/class/tty/tty0/active").read().strip()
    except OSError:
        return "tty1"


def rows(data):
    """raw packed bytes for whole rows of the screen -> an image of them"""
    return Image.frombytes("LA", (kit.SCREEN[0], len(data) // kit.SCREEN[0] // 2), data)


def blit(mm, img, xy):
    """copy a packed image into the framebuffer at xy, row by row (or in one go, if it's the screen's full width)"""
    if isinstance(img, bytes):   # whole rows, already packed
        o = xy[1] * kit.SCREEN[0] * 2; mm[o:o + len(img)] = img
        return
    x, y = xy; w = img.width * 2; data = memoryview(img.tobytes())
    if img.width == kit.SCREEN[0] and x == 0:   # one copy instead of a Python loop: what makes 20 fps possible
        o = y * w; mm[o:o + len(data)] = data
        return
    for row in range(img.height):
        o = ((y + row) * kit.SCREEN[0] + x) * 2
        mm[o:o + w] = data[row * w:(row + 1) * w]


def route(pages, index, x, y, holding):
    """where a touch goes -> the index of the page to show now, or None to stay. With a home page in the playlist: a touch
    on a rotating page goes home; on the home page, it opens the page whose tile it hit; on a page someone opened, it
    goes to the page if it takes touches, unless it's on the home button, and home if not. Without one, the page up
    gets it, as it would anyway."""
    names = [p.name for p in pages]
    home = names.index("home") if "home" in names else None
    page = pages[index]
    on_button = HOME_BUTTON[0] <= x < HOME_BUTTON[2] and HOME_BUTTON[1] <= y < HOME_BUTTON[3]
    if home is None or index == home or holding and hasattr(page, "touch") and not on_button:
        go = page.touch(x, y) if hasattr(page, "touch") else None
        return names.index(go) if go in names and names.index(go) != index else None
    return home


def rescue_screen(info):
    """what the screen says while rescue.py's hotspot is up: how to give the kiosk its Wi-Fi back, RGB"""
    img = Image.new("RGB", kit.SCREEN, kit.BG)
    kit.text(img, (60, 40), "THIS KIOSK HAS LOST ITS WI-FI", kit.O, scale=3)
    kit.text(img, (60, 130), "1. Join this Wi-Fi network:", kit.W, scale=2)
    kit.text(img, (120, 170), info.get("ssid", "?"), kit.O, scale=3)
    kit.text(img, (60, 240), "2. Its password:", kit.W, scale=2)
    kit.text(img, (120, 280), info.get("password", "?"), kit.O, scale=3)
    kit.text(img, (60, 350), "3. Open this page, and pick the kiosk's network:", kit.W, scale=2)
    kit.text(img, (120, 390), info.get("url", "?"), kit.O, scale=3)
    if info.get("note"):
        kit.text(img, (60, 460), info["note"][:110], kit.G, scale=1)
    return img


def badge():
    """the home button: a little house in a rounded square, packed"""
    img = Image.new("RGB", (64, 64), kit.BG); d = ImageDraw.Draw(img)
    d.rounded_rectangle((4, 4, 59, 59), radius=12, fill=(20, 24, 40), outline=kit.O, width=2)
    d.polygon([(32, 14), (14, 31), (50, 31)], fill=kit.O)
    d.rectangle((20, 31, 44, 48), fill=kit.O); d.rectangle((29, 37, 35, 48), fill=(20, 24, 40))
    return kit.packed(img)


BADGE = badge()


def following(pages, index):
    """the next page in the rotation that wants to be shown (the next one, if none do)"""
    for k in range(1, len(pages) + 1):
        j = (index + k) % len(pages)
        try:
            if getattr(pages[j], "active", lambda: True)():
                return j
        except Exception:
            pass   # a page that can't say is skipped this time round
    return (index + 1) % len(pages)


def steer(pages, index, since, last, path=CONTROL):
    """which page comes up now, if any, given the rotation and the control file -> (index or None, last), where last is
    what the control file said the time before: (its mtime, the pinned page, its skip), ("start", ...) at first"""
    mtime = os.path.getmtime(path) if os.path.exists(path) else None
    names, jump = [p.name for p in pages], None
    if mtime != last[0]:   # the desktop asked for something
        try:
            control = json.load(open(path))
        except (OSError, ValueError):
            control = {}
        pinned = control.get("page") if control.get("page") in names else None
        if pinned:
            jump = names.index(pinned)
        elif control.get("skip") != last[2] and last[0] != "start":
            jump = following(pages, index)
        last = (mtime, pinned, control.get("skip"))
    if jump is None and (index < 0 or time.time() - since >= pages[index].seconds):
        jump = index if last[1] and index >= 0 else following(pages, index)
    return jump, last


class Framebuffer:
    """the screen kiosk.py draws on when it runs on the Pi: /dev/fb0, with tty1 in graphics mode"""

    def __init__(self):
        self.fb = open("/dev/fb0", "r+b"); self.mm = mmap.mmap(self.fb.fileno(), kit.SCREEN[0] * kit.SCREEN[1] * 2)
        self.tty = sys.stdin.fileno() if sys.stdin.isatty() else None
        if self.tty is not None:
            fcntl.ioctl(self.tty, KDSETMODE, KD_GRAPHICS)   # the console stops drawing on top of us

    def visible(self):
        return active_vt() == "tty1"

    def play(self, new):
        transitions.play(self.mm, new)

    def flush(self):
        pass

    def close(self):
        if self.tty is not None:
            fcntl.ioctl(self.tty, KDSETMODE, KD_TEXT)


def main(screen, until=None):
    """show the pages on screen (the Framebuffer, or a remote.Server), forever or until until() says to stop"""
    pages = playlist()
    if not pages:
        sys.exit("playlist.json has no pages that load")
    for p in pages:
        if hasattr(p, "pages"):   # the home page: it shows the others
            p.pages = pages
    pages = pages + [setup_page.Page()]   # its fingerprint reminder, in the rotation only when active() says so
    steering, mm = ("start", None, None), screen.mm
    index, since, shown, drawn, moving = -1, 0.0, None, {}, False
    touched = os.path.getmtime(TOUCH) if os.path.exists(TOUCH) else None
    held, forced, badged = 0.0, None, False
    try:
        while not (until and until()):
            if os.path.exists(RESCUE) and screen.visible():   # no Wi-Fi: say how to fix it, and nothing else
                try:
                    info = json.load(open(RESCUE))
                    if shown != ("rescue", info):
                        mm[:] = kit.rgb565(rescue_screen(info)); shown = ("rescue", info); screen.flush()
                except (OSError, ValueError):
                    pass
                time.sleep(1)
                continue
            if setup_page.urgent() and screen.visible():   # the first-boot login: on this screen, ahead of every page
                info = setup_page.read()
                if shown != ("setup", info):
                    mm[:] = kit.rgb565(setup_page.draw(*info)); shown = ("setup", info); screen.flush()
                time.sleep(1)
                continue
            mtime = os.path.getmtime(TOUCH) if os.path.exists(TOUCH) else None
            if mtime != touched and index >= 0:   # a touch: route() says where it goes, and the screen holds still
                touched = mtime
                try:
                    at = json.load(open(TOUCH))
                    forced = route(pages, index, int(at["x"]), int(at["y"]), time.time() < held)
                    held = time.time() + HOLD
                except Exception as e:
                    print(f"touch: {e}", file=sys.stderr)
            holding = time.time() < held
            jump, steering = steer(pages, index, time.time() if holding else since, steering)   # holding: never due
            if forced is not None:   # where a touch went, straight there: no transition to wait through
                jump, forced, touched_jump = forced, None, True
            else:
                touched_jump = False
            if jump is not None:   # the next page's turn, or the one the desktop asked for
                moving = 0 <= index != jump and not touched_jump   # a new page gets a transition, unless a touch asked
                index = jump
                page = pages[index]
                try:
                    os.makedirs(os.path.dirname(SHOWING), exist_ok=True)
                    open(SHOWING, "w").write(page.name + "\n")
                except OSError:
                    pass
                try:
                    page.start(datetime.now())
                except Exception as e:
                    print(f"{page.name}: {e}", file=sys.stderr)
                since, shown = time.time(), None
            if not screen.visible():   # something else has the screen: don't draw over it, repaint when it's done
                shown = None
            else:
                now, t = datetime.now(), time.time() - since
                try:
                    key, bg = page.background(now)
                    regions = page.regions(now, t)
                    wants_badge = holding and page.name != "home" and any(p.name == "home" for p in pages)
                    if wants_badge != badged:   # the home button comes or goes: draw the page again whole
                        badged, shown = wants_badge, None
                    if wants_badge:
                        regions = list(regions) + [(BADGE, (HOME_BUTTON[0] + 4, HOME_BUTTON[1] + 4))]
                    if key != shown:   # the moving parts go into the background first, so the screen gets one
                        full = bg.copy()   # finished frame: writing the background alone blanks them for a moment
                        for img, xy in regions:
                            full.paste(rows(img) if isinstance(img, bytes) else img, xy)
                        if moving:
                            screen.play(full.tobytes()); moving = False
                        else:
                            mm[:] = full.tobytes()
                        shown = key
                        drawn = {xy: img for img, xy in regions}
                    else:
                        for img, xy in regions:
                            if drawn.get(xy) is not img:   # a page hands back the same image when nothing changed
                                blit(mm, img, xy); drawn[xy] = img
                except Exception as e:   # a broken page says so on screen rather than going dark
                    img = Image.new("RGB", kit.SCREEN, kit.BG)
                    kit.text(img, (40, 40), page.name.upper(), kit.O)
                    kit.text(img, (40, 90), f"waiting... {str(e)[:80]}", kit.G)
                    mm[:] = kit.rgb565(img); shown = None
                screen.flush()
            fps = getattr(page, "fps", FPS)
            time.sleep(max(0.02, 1 / fps - time.time() % (1 / fps)))   # on the beat (the quarter second, mostly)
    finally:
        getattr(screen, "close", lambda: None)()


def back(where, every=60):
    """for main(): True once the render server answers. A thread knocks every `every` seconds, so the display never
    waits on the network."""
    up = threading.Event()

    def knock():
        while not up.wait(every):
            try:
                socket.create_connection(where, timeout=5).close(); up.set()
            except OSError:
                pass
    threading.Thread(target=knock, daemon=True).start()
    return up.is_set


def display():
    """the Pi: the render server's picture if there is one, and our own when it can't be had. When the server answers
    again (we knock every minute), exit, so tty1's loop brings us back to connect to it."""
    where = remote.config()
    screen = Framebuffer()
    try:
        if where:
            try:
                remote.client(where, screen.mm, stop=setup_page.urgent)   # the Setup page is only ever drawn here
            except Exception as e:   # unreachable, hung up, or garbled: draw it ourselves
                print(f"remote: {e}; drawing locally for now", file=sys.stderr)
        ready = back(where) if where else None
        main(screen, until=(lambda: ready() and not setup_page.urgent()) if where else None)
    finally:
        screen.close()


def check():
    """every page package's self-test, the event sync's, then the playlist itself"""
    import pages
    names = sorted(n for d in pages.__path__ if os.path.isdir(d) for n in os.listdir(d)
                   if os.path.isfile(os.path.join(d, n, "__init__.py")))
    for name in names:
        importlib.import_module(f"pages.{name}").check()
        print(f"{name}: ok")
    importlib.import_module("eventsync").check()
    importlib.import_module("control").check()
    for name in ("config", "admin", "setup_check"):   # the setup page and the rules it has to keep
        importlib.import_module(name).check()
    gone = os.path.join(HERE, "no-setup.json")   # the Setup page as main() and run() reach it, through the package
    assert setup_page.urgent(gone) is False and setup_page.read(gone) == (None, 0)
    assert setup_page.draw({"done": True}).size == kit.SCREEN

    class Screen:   # always visible, and only memory: a few turns of the display loop itself, which nothing else runs
        mm = bytearray(kit.SCREEN[0] * kit.SCREEN[1] * 2)
        visible, flush, close = (lambda self: True), (lambda self: None), (lambda self: None)
        def play(self, new): self.mm[:] = new
    turns = iter(range(4))
    main(Screen(), until=lambda: next(turns, None) is None)
    transitions.check()
    remote.check()
    web.check()
    check_steer()
    check_touch()
    importlib.import_module("rescue").check()
    assert rescue_screen({"ssid": "kiosk-setup", "password": "abc", "url": "http://10.42.0.1", "note": "x"}).size == kit.SCREEN
    listener = socket.create_server(("127.0.0.1", 0)); up = back(listener.getsockname(), every=0.05)
    gone = back(("127.0.0.1", 1), every=0.05)   # nothing listens on port 1
    time.sleep(0.5)
    assert up() and not gone(), "back() sees a server that answers, and not one that doesn't"
    listener.close()
    loaded = playlist()
    assert loaded and all(hasattr(p, a) for p in loaded for a in ("name", "seconds", "start", "background", "regions"))
    print(f"playlist: {' -> '.join(f'{p.name} ({p.seconds:g} s)' for p in loaded)}")


def check_touch():
    """route(): where touches go, with and without a home page"""
    class P:
        def __init__(self, name, touchy=False, go=None):
            self.name, self.got = name, []
            if touchy:
                self.touch = lambda x, y: self.got.append((x, y)) or go
    rotating, map_, home = P("weather"), P("around", touchy=True), P("home", touchy=True, go="around")
    pages = [rotating, map_, home]
    assert route(pages, 0, 500, 200, False) == 2, "a touch on a page going round goes home"
    assert route(pages, 2, 500, 200, True) == 1, "the home page's tile opens its page"
    assert route(pages, 1, 500, 200, True) is None and map_.got == [(500, 200)], "an opened page that takes touches gets them"
    assert route(pages, 1, 10, kit.SCREEN[1] - 10, True) == 2, "except on the home button"
    assert route(pages, 0, 500, 200, True) == 2, "a page that doesn't take touches goes home"
    assert route([rotating, map_], 1, 500, 200, False) is None and map_.got[-1] == (500, 200), "no home page: as before"
    assert route([rotating], 0, 500, 200, False) is None
    assert BADGE.size == (64, 64)
    print("touch: ok")


def check_steer():
    """the desktop's pin, skip and auto, against a fake rotation"""
    import tempfile, types
    path = os.path.join(tempfile.mkdtemp(), "control.json")
    pages = [types.SimpleNamespace(name=n, seconds=20) for n in ("weather", "github", "agents")]
    now = time.time()

    def write(**control):
        json.dump(control, open(path, "w")); os.utime(path, (now + write.n, now + write.n)); write.n += 1
    write.n = 1
    jump, last = steer(pages, -1, 0, ("start", None, None), path)
    assert jump == 0, "no control file: the rotation starts at the top"
    assert steer(pages, 0, now, last, path)[0] is None and steer(pages, 0, now - 21, last, path)[0] == 1, "rotates"
    write(page="agents", skip=None)
    jump, last = steer(pages, 0, now, last, path)
    assert jump == 2 and steer(pages, 2, now - 21, last, path)[0] == 2, "a pinned page jumps in, then starts over"
    write(page=None, skip=None)
    jump, last = steer(pages, 2, now, last, path)
    assert jump is None and steer(pages, 2, now - 21, last, path)[0] == 0, "auto just lets the rotation carry on"
    write(page=None, skip=1)
    assert steer(pages, 2, now, last, path)[0] == 0, "next moves on at once"
    pages[1].active = lambda: False
    assert steer(pages, 0, now - 21, last, path)[0] == 2, "a page that isn't active is skipped"
    pages[1].active = lambda: 1 / 0
    assert steer(pages, 0, now - 21, last, path)[0] == 2, "and so is one that breaks"
    write(page="github", skip=None)
    assert steer(pages, 0, now, last, path)[0] == 1, "but pinning shows it anyway"
    write(page="calendar", skip=None)
    assert steer(pages, 1, now, ("start", None, None), path)[0] is None, "a page not in the playlist is ignored"
    print("steer: ok")


def smoke():
    """the quick test the Pi runs before it applies an update (the full check takes about 10 minutes on a Zero):
    every page in the playlist loads, comes up and draws, and the event sync works"""
    loaded = playlist()
    names = [e["page"] for e in json.load(open(PLAYLIST)) if e.get("on") is not False]
    assert len(loaded) == len(names), f"pages that didn't load: {set(names) - {p.name for p in loaded}}"
    for name in names:
        img = importlib.import_module(f"pages.{name}").preview()
        assert img.size == kit.SCREEN, name
    importlib.import_module("eventsync").check()
    importlib.import_module("control").check()   # the desktop's control key runs it
    print(f"smoke: ok ({', '.join(names)})")


if __name__ == "__main__":
    if sys.argv[1:] == ["--check"]:
        check()
    elif sys.argv[1:] == ["--smoke"]:
        smoke()
    elif sys.argv[1:2] == ["--png"] and len(sys.argv) == 4:
        importlib.import_module(f"pages.{sys.argv[2]}").preview().save(sys.argv[3])
    elif sys.argv[1:] == ["--web"]:
        main(web.Browser())
    elif sys.argv[1:] == ["--front"]:
        web.front(int(os.environ.get("KIOSK_PORT", 80)))
    elif sys.argv[1:] == ["--serve"]:
        main(remote.Server((remote.config() or ("", 7676))[1]))
    elif len(sys.argv) == 1:
        display()
    else:
        sys.exit(__doc__)
