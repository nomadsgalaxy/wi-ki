"""fuzz: every page drawn with data it didn't expect, so a page holds up with anyone's data, not just ours.

Each page's own SAMPLE is taken apart and put back wrong, many times over, with a fixed seed so a failure comes back
the same way: text empty, very long or in other scripts; numbers zero, negative, huge or the wrong type; lists empty,
long or short; fields missing. The page is then built with it the way the display builds it (its test data, or a
feed file in a temporary folder), and started, drawn and moved on a few frames. It passes if nothing raises and every
picture it hands the display is the screen's size, or fits on the screen where it's placed.

  fuzz.py              every page, the usual number of tries
  fuzz.py PAGE [N]     one page, N tries, saying what went wrong in each (any kit.Simple page, too: their check()
                       runs 20 tries itself)
"""
import copy, importlib, json, os, random, sys, tempfile, traceback, types
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)  # -I leaves our own folder off the path

import kit  # noqa: E402

# how each page is handed its data: a test argument, or a file it reads (the option that names it, and the file's
# name in a folder for a page that reads a folder)
TAKES = {"around": ("data", None), "cfradar": ("data", None), "radar": ("planes", None), "septa": ("data", None),
         "sports": ("data", None), "weather": ("w", None), "agents": ("feed", "file"), "github": ("feed", "file"),
         "system": ("file", "file"), "calendar": ("events", "file"), "nowplaying": ("folder", "track.json")}
TRIES = 40
STRINGS = ["", " ", "x" * 300, "Ωμέγα · 漢字 · العربية · 🙂🚀", "a\tb", "NaN", "0", "-1", "<b>&amp;</b>", "​"]
NUMBERS = [0, -1, 1, 10 ** 9, -10 ** 9, 0.5, 1e-9, 2 ** 31]


def mangle(value, rnd, depth=0):
    """value with some of its parts put back wrong"""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if rnd.random() < .12:
                continue                                   # a field that isn't there
            out[k] = mangle(v, rnd, depth + 1) if rnd.random() < .6 else v
        return out
    if isinstance(value, list):
        if rnd.random() < .15:
            return []
        items = [mangle(v, rnd, depth + 1) if rnd.random() < .6 else v for v in value]
        if items and rnd.random() < .2:
            items = items * rnd.randint(2, 12)              # far more of them than usual
        elif items and rnd.random() < .2:
            items = items[:1]
        return items
    if isinstance(value, bool):
        return rnd.random() < .5
    if isinstance(value, (int, float)):
        return rnd.choice(NUMBERS) if rnd.random() < .8 else rnd.choice([None, "12"])
    if isinstance(value, str):
        if rnd.random() < .2:
            return value                                    # dates and ids mostly stay readable
        return rnd.choice(STRINGS) if rnd.random() < .8 else rnd.choice([None, 0])
    return value


def build(name, data, folder):
    """the page, built the way the display builds it, with data -> Page"""
    module = importlib.import_module(f"pages.{name}.page")
    if name not in TAKES and issubclass(module.Page, kit.Simple):   # a Simple page is handed its data straight
        page = module.Page(); page.every, page.data = 0, data
        return page
    option, kind = TAKES[name]
    if kind is None:
        return module.Page(**{option: data})
    os.makedirs(folder, exist_ok=True)
    if kind == "file":
        path = os.path.join(folder, f"{name}.json")
        json.dump(data, open(path, "w"))
        return module.Page(**{option: path})
    json.dump(data, open(os.path.join(folder, kind), "w"))
    return module.Page(**{option: folder})


def run(page, now):
    """start it, draw it and move it on a few frames -> what's wrong, or None"""
    w, h = kit.SCREEN
    page.start(now)
    for t in (0, .5, 3, 30):
        _, bg = page.background(now + timedelta(seconds=t))   # (what it shows, the picture), as the display asks
        if getattr(page, "failed", None):   # a Simple page shows its error rather than raising it
            return page.failed
        if bg.size != kit.SCREEN:
            return f"its background is {bg.size}, not {kit.SCREEN}"
        for img, (x, y) in page.regions(now + timedelta(seconds=t), t) or []:
            if isinstance(img, bytes):   # whole rows of packed pixels, as kiosk.rows() reads them
                img = types.SimpleNamespace(width=w, height=len(img) // w // 2)
            if x < 0 or y < 0 or x + img.width > w or y + img.height > h:
                return f"a region at ({x}, {y}), {img.width}x{img.height}, goes off the screen"
    return getattr(page, "failed", None)


def fuzz(name, tries=TRIES, seed=19, say=False):
    """-> [(try, what went wrong)]"""
    module = importlib.import_module(f"pages.{name}.page")
    sample = module.SAMPLE if hasattr(module, "SAMPLE") else module.Page.SAMPLE   # a Simple page keeps it on Page
    now, failed = datetime(2026, 10, 19, 9, 41), []
    for n in range(tries):
        rnd = random.Random(seed * 1000 + n)
        data = sample if n == 0 else mangle(copy.deepcopy(sample), rnd)   # the first try is the sample as it is
        with tempfile.TemporaryDirectory() as folder:
            try:
                why = run(build(name, data, os.path.join(folder, "feed")), now)
            except Exception as e:
                why = f"{type(e).__name__}: {e}"[:200]
                if say:
                    traceback.print_exc()
        if why:
            failed.append((n, why))
    return failed


def check():
    bad = {name: fuzz(name) for name in TAKES}
    bad = {k: v for k, v in bad.items() if v}
    assert not bad, "pages that don't hold up with odd data:\n" + "\n".join(
        f"  {k}: {len(v)} of {TRIES}, first: try {v[0][0]}: {v[0][1]}" for k, v in bad.items())
    print(f"fuzz: ok ({len(TAKES)} pages, {TRIES} tries each)")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        for n, why in fuzz(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else TRIES, say=True):
            print(f"try {n}: {why}")
    else:
        bad = {name: fuzz(name) for name in TAKES}
        for name, failed in bad.items():
            print(f"{name:11} {len(failed):2} of {TRIES} failed" + (f"  first: try {failed[0][0]}: {failed[0][1]}" if failed else ""))
