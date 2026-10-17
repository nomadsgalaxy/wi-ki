#!/usr/bin/env python3
"""emulate: see the weather kiosk on this laptop before it goes to the Pi.

It runs weather.py's own frame() for any weather and time of day and saves what the 1920x515 bar display would show,
including the Pi's RGB565 colour depth (each frame goes through the same packing and back). Each video is exactly one
loop of the scene (64 s at the Pi's 4 frames a second), so set to repeat it plays seamlessly, like the display.

  emulate.py                         every scenario: a contact sheet (sheet.png) and one looping MP4 each, in ./out
  emulate.py rain night              just those scenarios
  emulate.py --gif storm             a half-size looping GIF as well
  emulate.py --frames 16 clear       only the first 16 frames (quick look; won't loop)
  emulate.py --list                  the scenarios

The forecast numbers are live from Open-Meteo (cached in out/live.json for the day); each scenario swaps in its own
weather code and time of day.
"""
import argparse, json, os, subprocess, sys, urllib.request
from datetime import datetime
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "kiosk"))
from pages.weather import page as weather  # noqa: E402
from pages import github, agents, system, radar, nowplaying  # noqa: E402
import transitions  # noqa: E402

# name: (weather code, time of day, wind mph or None for the forecast's)
SCENARIOS = {
    "clear": (0, "11:30", 4), "partly": (2, "10:00", None), "overcast": (3, "14:00", None), "fog": (45, "08:00", 3),
    "drizzle": (53, "16:00", None), "rain": (63, "13:00", None), "heavy": (65, "15:00", 18), "snow": (73, "11:00", None),
    "storm": (95, "17:00", 20), "golden": (1, "17:55", None), "dusk": (0, "18:40", None), "night": (0, "22:30", None),
    "rainnight": (63, "23:30", None), "snownight": (73, "21:00", None),
}


def as_pi(img):
    """what the Pi's 16-bit framebuffer actually shows: drop the low bits the way RGB565 does"""
    return img.point([v >> 3 << 3 for v in range(256)] + [v >> 2 << 2 for v in range(256)] + [v >> 3 << 3 for v in range(256)])


def live():
    """today's real forecast, fetched once a day"""
    path = os.path.join(HERE, "out", "live.json")
    if not os.path.exists(path) or datetime.fromtimestamp(os.path.getmtime(path)).date() != datetime.now().date():
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with urllib.request.urlopen(weather.URL, timeout=20) as r:
            json.dump(json.load(r), open(path, "w"))
    return json.load(open(path))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("scenarios", nargs="*", help="names from --list (default: all)")
    ap.add_argument("--frames", type=int, default=int(weather.scene.LOOP * weather.scene.FPS), help="frames (default: one whole loop)")
    ap.add_argument("--gif", action="store_true", help="also save a half-size GIF")
    ap.add_argument("--out", default=os.path.join(HERE, "out"))
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    if a.list:
        print("\n".join(f"{k:10} code {c:2}  {t}" for k, (c, t, _) in SCENARIOS.items())); return
    base = live()
    os.makedirs(a.out, exist_ok=True)
    stills = []
    for name in a.scenarios or list(SCENARIOS):
        code, hhmm, wind = SCENARIOS[name]
        w = json.loads(json.dumps(base)); w["current"]["weather_code"] = code
        if wind is not None:
            w["current"]["wind_speed_10m"] = wind
        day = datetime.strptime(w["daily"]["sunrise"][0][:10], "%Y-%m-%d")
        when = datetime.combine(day, datetime.strptime(hhmm, "%H:%M").time())
        rise, sset = (datetime.strptime(w["daily"][k][0], "%Y-%m-%dT%H:%M") for k in ("sunrise", "sunset"))
        w["current"]["is_day"] = int(rise <= when <= sset)
        # the clock stays put, so the panel doesn't change mid-loop; only the scene's animation runs
        imgs = [as_pi(weather.frame(w, when, 120, f / weather.scene.FPS)) for f in range(a.frames)]
        mp4 = os.path.join(a.out, f"{name}.mp4")
        ff = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
                               "-s", "%dx%d" % weather.SCREEN, "-r", str(weather.scene.FPS), "-i", "-",
                               "-vf", "scale=1920:516:flags=neighbor", "-c:v", "libx264", "-crf", "16",
                               "-pix_fmt", "yuv420p", mp4], stdin=subprocess.PIPE)
        for im in imgs:
            ff.stdin.write(im.tobytes())
        ff.stdin.close(); ff.wait()
        if a.gif:
            half = [im.resize((im.width // 2, im.height // 2), Image.NEAREST) for im in imgs]
            half[0].save(os.path.join(a.out, f"{name}.gif"), save_all=True, append_images=half[1:], duration=250, loop=0)
        stills.append((name, imgs[0])); print(f"{name}: {mp4}")
    # contact sheet: every scenario's first frame, labelled, at half size
    tw, th = weather.SCREEN[0] // 2, weather.SCREEN[1] // 2
    sheet = Image.new("RGB", (tw * 2 + 30, (th + 34) * ((len(stills) + 1) // 2) + 10), (30, 30, 30))
    d = ImageDraw.Draw(sheet)
    for i, (name, img) in enumerate(stills):
        x, y = 10 + (i % 2) * (tw + 10), 10 + (i // 2) * (th + 34)
        d.text((x, y), f"{name}  (code {SCENARIOS[name][0]}, {SCENARIOS[name][1]})", fill=(246, 145, 31))
        sheet.paste(img.resize((tw, th), Image.NEAREST), (x, y + 18))
    sheet.save(os.path.join(a.out, "sheet.png")); print(f"sheet: {a.out}/sheet.png")
    for page in (github, agents, system, radar, nowplaying):
        name = page.Page.name
        page.preview().save(os.path.join(a.out, f"{name}.png")); print(f"{name}: {a.out}/{name}.png")
    for theme in transitions.THEMES:
        transitions.preview(theme).save(os.path.join(a.out, f"transition-{theme}.png"))
        print(f"transition {theme}: {a.out}/transition-{theme}.png")


if __name__ == "__main__":
    main()
