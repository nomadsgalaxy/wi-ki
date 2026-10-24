"""Transitions: what plays between two pages. They don't know anything about pages; they get the screen as it is and the
next page's finished frame, and get from one to the other in SECONDS (or the theme's own SECONDS, for the ones that
tell a longer story).

Each theme is its own module with a `frames(canvas, count)` generator that draws `count` frames, one per step (see
canvas.py):
  coreone        the new page is printed, layer by layer, by a zig-zagging hotend
  hive76         honeycomb cells fill with honey and open onto the new page, while a bee flies past
  nomadsgalaxy   hyperspace: streaks and rings of light rush down a tunnel, the Drifter flies through, and the page opens
                 from the middle between three beams
  matrix         a curtain of green code rain falls and leaves the new page behind it
  hackerman      a neon terminal hacks time while the new page glitches in
  johnny5        Johnny-5 rolls in, needs input, and scans the new page in with his eyes
  pacman         a maze builds over the old page, and Pac-Man eats his way through it to the new one
  tetris         the stack fills the screen, then an I piece scores a Tetris and clears it to the new page

kiosk.py calls play() whenever the page changes. The themes take turns, in ORDER, leaving out any listed in
~/.config/kiosk/transitions-off.json (deploy/kiosk-config sets it). A kiosk has the ones it's installed (packs.py):
they're found here, in the catalog's folder in the repo, and in ~/.local/share/kiosk/transitions/ for ones from a repo.
One that won't even load is left out, so it can't stop the display.
"""
import importlib, itertools, json, os, sys, time

HERE = os.path.dirname(os.path.realpath(__file__))
# the catalog's themes, in the repo (on a kiosk, autoupdate.py puts them here), then any installed from a repo
__path__ += [os.path.join(HERE, "..", "..", "catalog", "transitions"), os.path.expanduser("~/.local/share/kiosk/transitions")]
from .canvas import Canvas

SECONDS, FPS = 3, 24   # slow enough to watch; 24 fps is what the busiest one manages on the Pi
MAXIMUM = 5            # seconds: johnny5's length, the longest a theme should run (check() holds them to it)
FIRST = ("coreone", "hive76", "nomadsgalaxy", "matrix", "hackerman", "johnny5")   # the order they've always taken turns in


def names():
    """every installed theme's name, the usual ones first in their order, then the rest by name"""
    found = {f[:-3] for d in __path__ if os.path.isdir(d) for f in os.listdir(d)
             if f.endswith(".py") and f not in ("__init__.py", "canvas.py")}
    return sorted(found, key=lambda n: (FIRST.index(n) if n in FIRST else len(FIRST), n))


def themes():
    """every installed theme -> {name: module}, in names() order"""
    found = {}
    for name in names():
        try:
            found[name] = importlib.import_module(f"{__name__}.{name}")
        except Exception as e:   # a broken one is left out, and says why, rather than stopping the display
            print(f"transitions: leaving out {name}: {type(e).__name__}: {e}", file=sys.stderr)
    return found


# a render server only names the theme for the Pi to play, so it doesn't load them: some build ~30 MB of sprites
THEMES = {name: None for name in names()} if "--serve" in sys.argv else themes()
OFF = os.path.expanduser("~/.config/kiosk/transitions-off.json")


def turned_off(path=OFF):
    """the themes transitions-off.json turns off: a list of theme names. Anything else in it (null, a number, a bare
    string, objects, names we don't have) is ignored, so a bad file can't stop the kiosk starting"""
    try:
        with open(path) as f:
            names = json.load(f)
    except (OSError, ValueError):
        return set()
    return {n for n in names if isinstance(n, str) and n in THEMES} if isinstance(names, list) else set()


off = turned_off()
ORDER = itertools.cycle([t for t in THEMES if t not in off] or THEMES)   # all of them off means none are


# a swipe's own transition, never in the rotation: the new page slides in from the side the finger moved towards, pushing
# the old one out, so the screen follows the finger. slide-next is a swipe left (the new page comes in from the right)
SLIDES, SLIDE = {"slide-next": 1, "slide-prev": -1}, 0.25   # and its seconds: quick, it's feedback


def slide(mm, new, step, seconds=SLIDE, fps=30):
    """the slide itself: whole rows, two copies a row a frame. Each frame goes as far as the time says, so it lands on
    time on any Pi: a Zero manages about three frames in a quarter second (80 ms each), a Pi 4 all of them"""
    from .canvas import WIDTH, STRIDE
    old, start, cost = bytes(mm[:len(new)]), time.monotonic(), 0.0
    # each frame shows where the slide should be when it's finished (the last one took cost), and none starts that
    # would land after the end: the final copy (in play()) lands it
    while (done := (time.monotonic() - start + cost) / seconds) < 1:
        began = time.monotonic()
        x = round((1 - (1 - done) ** 2) * WIDTH) * 2   # bytes the new page is in by then, slowing as it lands
        for o in range(0, len(new), STRIDE):
            if step > 0:   # in from the right
                mm[o:o + STRIDE - x] = old[o + x:o + STRIDE]; mm[o + STRIDE - x:o + STRIDE] = new[o:o + x]
            else:          # in from the left
                mm[o:o + x] = new[o + STRIDE - x:o + STRIDE]; mm[o + x:o + STRIDE] = old[o:o + STRIDE - x]
        cost = time.monotonic() - began
        time.sleep(max(0, 1 / fps - cost))   # no faster than fps on a quick machine


def play(mm, new, theme=None, fps=FPS, on_frame=None):
    """turn what's in mm (the framebuffer) into new, a page's whole frame in packed bytes. It always ends on the new
    page exactly: if a theme, on_frame or the pacing fails partway, the rest of the transition is skipped, the failure
    goes to stderr, and the screen still lands on the new page"""
    name = theme or next(ORDER)
    try:
        if name in SLIDES:
            return slide(mm, new, SLIDES[name])
        canvas = Canvas(mm, new)
        module = THEMES[name]
        steps = module.frames(canvas, round(getattr(module, "SECONDS", SECONDS) * FPS))
        beat = time.monotonic()   # not the wall clock: setting the clock back mustn't make it sleep
        while True:
            canvas.wipe()
            if next(steps, "done") == "done":
                break
            if on_frame:
                on_frame(canvas)
            if fps:
                beat += 1 / fps
                time.sleep(max(0, beat - time.monotonic()))
    except Exception as e:
        print(f"transitions: {name} failed partway, so it skipped to the new page: {e!r}", file=sys.stderr)
    finally:
        mm[:len(new)] = new   # whatever happened along the way, it ends on the new page exactly


def check():
    from .canvas import WIDTH, HEIGHT
    size = WIDTH * HEIGHT * 2
    old, new = bytes(size), b"\x55" * size
    for name in THEMES:
        mm, frames = bytearray(old), []
        play(mm, new, name, fps=None, on_frame=lambda c: frames.append(bytes(c.mm)))
        assert mm == new, f"{name} ends on the new page"
        want = round(getattr(THEMES[name], "SECONDS", SECONDS) * FPS)
        assert want <= MAXIMUM * FPS, f"{name} runs {want / FPS:g} s, and no theme should run longer than {MAXIMUM} s"
        assert abs(len(frames) - want) <= want // 8, f"{name} takes {len(frames)} frames, not ~{want}"
        assert frames[0].count(b"\x00\x00"), f"{name} starts from the old page"
        assert any(f.count(b"\x55\x55") for f in frames[:-2]), f"{name} shows the new page, not just snaps to it"
        moving = sum(a != b for a, b in zip(frames, frames[1:]))
        still = round(getattr(THEMES[name], "STILL", 0) * FPS)   # seconds a theme holds still on purpose, for reading
        assert moving >= (len(frames) - still) // 2, f"{name} only moves on {moving} of {len(frames)} frames"   # holds are fine
    # one or two frames: the themes' own frames() run to the end without a divide by zero. play() would hide that,
    # since a theme failing partway is caught and it lands on the new page anyway. A lone frame is the transition's
    # first (t=0), never the finished page: play() is what ends on the new page.
    # not johnny5: its last frame is always the new page, even when it's the only one
    for name in [n for n in ("hackerman", "hive76", "matrix", "nomadsgalaxy", "coreone", "pacman", "tetris") if n in THEMES]:
        for count in (1, 2):
            c, shown = Canvas(bytearray(old), new), []
            for _ in THEMES[name].frames(c, count):
                shown.append(bytes(c.mm))
            assert shown, f"{name} draws no frames of {count}"
            assert shown[0] != new, f"{name}'s first frame of {count} is not the new page"   # the first only: coreone's later ones may finish it
    if "coreone" in THEMES:
        coreone = THEMES["coreone"]
        layers = -(-HEIGHT // coreone.LAYER)   # coreone plays count // layers steps a layer, and at least one (its docstring)
        for count, want in ((1, layers), (2, layers), (36, 2 * layers), (72, 5 * layers)):
            got = sum(1 for _ in coreone.frames(Canvas(bytearray(old), new), count))
            assert got == want, f"coreone draws {got} frames of {count}, not {want}"
    # a theme, on_frame or the pacing failing partway still ends on the new page, and doesn't raise
    import io, contextlib, tempfile
    def broken(c, count):
        yield; yield
        raise RuntimeError("a theme with a bug")
    THEMES["broken"] = type("Broken", (), {"frames": staticmethod(broken)})
    try:
        for kw in ({"theme": "broken"}, {"theme": "matrix", "on_frame": lambda c: 1 / 0}):
            mm, err = bytearray(old), io.StringIO()
            with contextlib.redirect_stderr(err):
                play(mm, new, fps=None, **kw)
            assert mm == new and "skipped to the new page" in err.getvalue(), kw
        def stopped(c, count):   # Ctrl-C partway: it still lands on the new page, and the interrupt goes on up
            yield
            raise KeyboardInterrupt
        THEMES["broken"] = type("Stopped", (), {"frames": staticmethod(stopped)})
        mm = bytearray(old)
        try:
            play(mm, new, "broken", fps=None)
        except KeyboardInterrupt:
            assert mm == new, "interrupted, it still ends on the new page"
        else:
            raise AssertionError("an interrupt was swallowed")
    finally:
        del THEMES["broken"]
    real = time.sleep
    try:   # the pacing failing (here, sleep) is the same
        time.sleep = lambda s: 1 / 0
        mm = bytearray(old)
        with contextlib.redirect_stderr(io.StringIO()):
            play(mm, new, "matrix", fps=FPS)
        assert mm == new, "a failure in the pacing still ends on the new page"
    finally:
        time.sleep = real
    # the beat is kept on the monotonic clock: the wall clock jumping back an hour doesn't make it sleep
    slept, clock, asked, wall, mono = [], [0.0], [0], time.time, time.monotonic
    def sleep(s):
        slept.append(s); clock[0] += s
    def jumpy():   # the wall clock: set back an hour partway through
        asked[0] += 1
        return 1e9 if asked[0] < 20 else 1e9 - 3600
    try:
        time.sleep, time.monotonic, time.time = sleep, lambda: clock[0], jumpy
        play(bytearray(old), new, "matrix", fps=FPS)
        assert slept and max(slept) <= 1 / FPS + 1e-9, max(slept)
        want = getattr(THEMES["matrix"], "SECONDS", SECONDS)
        assert abs(sum(slept) - want) < 0.2, f"paced to {sum(slept):.2f} s, not {want}"
    finally:
        time.sleep, time.time, time.monotonic = real, wall, mono
    # transitions-off.json: a list of our theme names, and anything else is ignored rather than stopping the kiosk
    with tempfile.TemporaryDirectory() as folder:
        path = os.path.join(folder, "off.json")
        assert turned_off(path) == set(), "no file: none off"
        a, b = list(THEMES)[:2]   # two that are installed: every kiosk has at least core's two
        for body, want in ((f'["{a}", "{b}"]', {a, b}), ('null', set()), ('7', set()), (f'"{a}"', set()),
                           (f'[{{"name": "{a}"}}, "{b}"]', {b}), ('["nope", 3, null]', set()), ('{not json', set()),
                           (f'{{"{a}": true}}', set())):
            open(path, "w").write(body)
            assert turned_off(path) == want, (body, turned_off(path))
    if "nomadsgalaxy" in THEMES:
        nomadsgalaxy = THEMES["nomadsgalaxy"]
        # nomadsgalaxy: the amber burst is 7 of 72 frames, the Drifter is never drawn over the page once it
        # has opened, and the beams never reach the header (the clock)
        n_burst = sum(0 < nomadsgalaxy.ease(k / 71, *nomadsgalaxy.BURST) < 1 for k in range(72))
        assert n_burst == 7, f"the amber burst is {n_burst} frames, and the docs say 7"
        real_draw, real_fill, over, high = Canvas.draw, Canvas.fill, [], []
        def draw(self, spr, x, y, keep=False):
            if spr in nomadsgalaxy.SHIPS:   # which rows of the screen hold the new page just now?
                rows = [r for r in range(max(0, y), min(HEIGHT, y + spr["h"])) if self.cur[r * WIDTH * 2:(r + 1) * WIDTH * 2] == new[r * WIDTH * 2:(r + 1) * WIDTH * 2]]
                over.append(len(rows))
            return real_draw(self, spr, x, y, keep)
        def fill(self, x, y, w, h, rgb, keep=False):
            if 0 <= y < nomadsgalaxy.HEADER and (w == WIDTH and h in (4, 8) or h in (2, 3) and w >= 3 and self.cur[y * WIDTH * 2:(y + 1) * WIDTH * 2] == new[y * WIDTH * 2:(y + 1) * WIDTH * 2]):   # a beam, or a star over the opened header
                high.append(y)
            return real_fill(self, x, y, w, h, rgb, keep)
        Canvas.draw, Canvas.fill = draw, fill
        try:
            play(bytearray(old), new, "nomadsgalaxy", fps=None)
        finally:
            Canvas.draw, Canvas.fill = real_draw, real_fill
        assert over and not any(over), f"the Drifter is drawn over the new page on {sum(map(bool, over))} frames"
        assert not high, f"a beam is drawn over the header at rows {high}"
    for name, module in THEMES.items():   # and a theme's own self-test, if it has one, so --check runs it too
        if callable(getattr(module, "check", None)):
            module.check()
    # a swipe's slide: the new page comes in from the side the finger moved towards, and it ends on the new page
    from .canvas import WIDTH, STRIDE
    old, new = bytes([1]) * (STRIDE * 4), bytes([2]) * (STRIDE * 4)
    seen = []
    class Watch(bytearray):
        def __setitem__(self, key, value):
            super().__setitem__(key, value)
            if isinstance(key, slice) and key.start == 0 and key.stop and key.stop > 2 and len(seen) < 99:
                seen.append(bytes(self[:STRIDE]))
    for name, edge in (("slide-next", -2), ("slide-prev", 0)):   # where the new page shows first: the right, the left
        mm, seen[:] = Watch(old), []
        play(mm, new, name, fps=None)
        assert bytes(mm) == new, f"{name} ends on the new page"
        mid = seen[len(seen) // 2]
        assert mid[edge] == 2 and mid[-2 - edge] == 1, f"{name}: halfway, the new page is in on its side and the old on the other"
    print("transitions: ok")


def preview(theme, shots=8):
    """a sheet of frames from one theme, going from the github page to the agents page, for the emulator"""
    import importlib
    from PIL import Image
    import kit
    old, new = (kit.rgb565(importlib.import_module(f"pages.{p}").preview()) for p in ("github", "agents"))
    frames = []
    play(bytearray(old), new, theme, fps=None, on_frame=lambda c: frames.append(bytes(c.mm)))
    picks = [frames[round(i * (len(frames) - 1) / (shots - 1))] for i in range(shots)]
    w, h = kit.SCREEN[0] // 2, kit.SCREEN[1] // 2
    sheet = Image.new("RGB", (w * 2, h * (shots // 2)), kit.BG)
    for i, raw in enumerate(picks):
        img = kit.unpack(Image.frombytes("LA", kit.SCREEN, raw)).resize((w, h), Image.NEAREST)
        sheet.paste(img, (i % 2 * w, i // 2 * h))
    return sheet
