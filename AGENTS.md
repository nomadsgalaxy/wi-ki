# Wi-Ki: notes for coding agents

What you need to work on the code without breaking the Pi. `docs/` covers setting up a kiosk, a render server and connectors, `docs/make.md` making a page or a transition (`catalog/catalog.py --new`, `kit.Simple`, `canvas.simple()`), and `docs/develop.md` running, testing and deploying.

## The machine

- Raspberry Pi Zero W v1.1: one 1 GHz ARMv6 core, 512 MB RAM. Everything is slow. Measure on the Pi before you assume something is fast enough.
- Raspberry Pi OS Lite (trixie, 32-bit), Python 3.13, Pillow 11 from apt (`python3-pil`). There's no numpy, and don't add it.
- Display: 1920×515 through the KMS driver, exposed as `/dev/fb0`, 16-bit RGB565, stride 3840.
- Host `kiosk` (`kiosk.local`), user `kiosk` with sudo. SSH is key-only. Whoever set the kiosk up holds the sudo password; it isn't in this repo.

## How it runs

- tty1 logs in as `kiosk` by itself, and `~/.bash_profile` runs `python3 -I ~/kiosk/kiosk.py` in a loop (it comes back 3 s after it exits).
- `deploy/deploy.sh` ships `kiosk/` to the Pi as `~/kiosk/`, with the catalog's pages and transitions put back into `pages/` and `transitions/` (`autoupdate.assemble()`).
- `kiosk.py` puts tty1 in graphics mode and shows the pages in `playlist.json` at 4 fps. Its docstring is the page interface: a package in `catalog/pages/<name>/` (`pages/<name>/` on a kiosk) exporting `Page` (`name`, `seconds`, `start(now)`, `background(now) -> (key, image)`, `regions(now, t) -> [(image, (x, y))]`), `check()` and `preview()`. Images are "LA" images holding packed RGB565 (`kit.packed()`).
- The weather page lasts exactly `scene.LOOP` (64 s), one loop of the scene. Don't give it other `seconds` in the playlist unless it's a multiple of 64.

## The render server

A kiosk can have a render server (`kiosk.py --serve`, named in the kiosk's `~/.config/kiosk/remote.json`): pages run there, and the Pi shows what it sends (`kiosk/remote.py`). Without one, the Pi draws its own pages. The Pi still runs transitions, and still draws everything itself when the server's away, so every page and transition must still work on the Pi. Pages' data (the feeds, `/dev/shm` sinks, `control.py`) lives on the server.

## Keep pages modular

- **A page only imports from `kit.py`**, never from another page. Pages that share data share a file: the weather page writes `~/.cache/weather.json` (14 days), and the calendar reads it for each day's weather. The github and agents pages both read `~/.cache/kiosk/desk.json` from the desktop feed (`feed/`), through `kit.Feed`.
- **Shared things go in `kit.py`:** the screen size, colours, the VGA font and `text()`, packing, the weather icons. Add to it only what more than one page needs.
- **Anything a page needs to be told goes in its options** (`Page(**options)` from `playlist.json`), with sensible defaults.
- **Every page has `check()` and `preview()`.** `kiosk.py --check` runs them all, and `deploy.sh` won't deploy if one fails.
- **Event sources follow the same rules:** a module in `sources/` exporting `events(first, days, **options)` and `check()`, listed in `eventsync.json`. `eventsync.py` merges them and keeps a failed source's last events.
- **A failing page doesn't take down the rest:** the playlist skips a page that won't load, and a page that throws shows its error on screen until it recovers.

## Rules that keep it working

- **The scene must loop perfectly.** Anything that moves in `scene.draw()` has to complete whole cycles in `LOOP` seconds: use `laps()` for speeds and `wave()` for oscillations, and take time-based randomness from `frame`. `kiosk.py --check` asserts that frame t equals frame t + LOOP for several weather types.
- **Cache anything slow.** `scene.layers()` caches the static layers for 5 minutes and `foliage()` caches the leaf pattern forever. A per-pixel Python loop over the whole 300×128 scene costs seconds on the Pi.
- **Draw at 300×128 and scale up 4×** with `Image.NEAREST`. Pack to RGB565 before scaling (it's 16× fewer pixels to pack).
- **`-I` mode:** both scripts run with `python3 -I`, which leaves their own folder off `sys.path`, so they add it back themselves. Keep that.
- **Secrets:** never put a password on a command line or in the repo. Take them from a hidden prompt or an environment variable and pass them over stdin (see `deploy/as-root.sh`).
- **Temperatures are °C.** The forecast is fetched in Celsius, and `kit.warmth()` takes °C.
- **Colours are Nomads Galaxy tokens** (`kit.py`, from the Nomads Galaxy brand tokens). Don't invent new ones. Partner owners like Positron 3D and Hive76 aren't drawn in Warp Cyan.
- **Transitions** (`catalog/transitions/`, one file per theme with a `frames(canvas)` generator) work on the framebuffer's raw bytes through `canvas.py`, never Pillow per frame. Each copy costs about 45 us on the Zero whatever its size, so count copies, not bytes: whole rows go in one, and a frame should stay under ~600. Build sprites once, at import, and `stamp()` anything that's stopped moving so it isn't redrawn every frame. Time a new one on the Pi before shipping it. Never flash the whole screen: no full-screen flicker faster than about 3 times a second (it's a seizure risk).
- **Fonts:** text uses `kiosk/fonts/Uni2-VGA16.psf.gz`. Check a glyph exists before you use it (`kit.FONT`).

## The catalog

Every page and transition is in `catalog/`, with an entry in `catalog/entries/<name>.json`: what it is, its licence and its art's credits, the shapes it draws, the services it calls and the settings it takes. `catalog/catalog.py --check` holds each entry against the code on `origin/main`, so a new page or transition needs an entry, and a change to one usually needs its `found` hash updated (`--draft page <name>` shows what the code says). `--table` rewrites `CATALOG.md`. The player (`kiosk/transitions/__init__.py`) and `canvas.py` are the engine's and stay in `kiosk/`.

## The setup page

`kiosk/admin.py` is the kiosk's setup page, and it's security code: it faces whatever network the kiosk is on. Keep its rules when you change it: HTTPS only, its own addresses and local networks only, the form token and the same-origin check on every change, the login throttle, and nothing secret in its log. `kiosk/setup_check.py` tests those rules, and `kiosk.py --check` runs it. A new setting writes the same files `kiosk.py` reads (`playlist.json`, `transitions-off.json`), checked first (`config.validate_playlist()`), and goes to the render server through `link.py` on a kiosk that shows one (signed with the shared key in `remote.json`, and refused without it).

## Installed pages and transitions

A kiosk only has the core (`kiosk/core.json`) plus what's been installed (`kiosk/packs.py`). So no page may import another page, and nothing in the base may name a page or a transition directly: `pages/` and `transitions/` find whatever's installed, and a check that tests one theme in particular skips it when it isn't there. `kiosk.py --check` on a kiosk with only the core has to pass too.

## Per-kiosk settings

Every kiosk runs the same code. What makes one different lives on it, in `~/.config/kiosk/`, which updates never touch: `branch` (what to follow; `main` if it's missing), `playlist.json`, `transitions-off.json`, `remote.json` (its render server) and `eventsync.json` (its calendar's sources). Without one, the repo's copy is used, and with no `remote.json` the kiosk draws its own pages. Never put one kiosk's settings in the repo.

## Pushing to main deploys

The Pi pulls `main` every 10 minutes (`kiosk/autoupdate.py`), runs `kiosk.py --smoke`, and applies the commit if that passes. It doesn't run the full `--check` (10 minutes on a Zero), so you must.

## Before you push

1. `python3 -I kiosk/kiosk.py --check`, and `python3 -I catalog/catalog.py --test` if you touched the catalog
2. Look at it: `python3 -I kiosk/kiosk.py --png <page> out.png`, or `python3 -I emulator/emulate.py --frames 1` for every weather scenario (`emulator/out/sheet.png`) and the calendar.
3. Push to `main`; the Pi picks it up within about 10 minutes. (`deploy/deploy.sh` pushes your working copy straight to the Pi instead, for trying something first.)

## Touch

Some kiosks will have touch screens and some won't, so a page must work untouched and may also take touches.

- **A page that takes touches** has `touch(x, y)` (screen pixels). `kiosk.py` hands it every touch while the page is up
  and starts the page's time over, so the rotation doesn't move on from under someone's finger. Untouched, the page must
  still make sense: `around` goes back to its own view after `IDLE` seconds.
- **Touches arrive as a file**, `~/.cache/kiosk/touch.json` (`touch-<shape>.json` for the browser shapes):
  `{"x": .., "y": ..}` for a tap, or `{"gesture": "menu" | "next" | "prev"}`, watched like the control file. The reader
  works out the gesture: a two-finger double tap is `menu` (the home page), a swipe left `next`, a swipe right `prev`.
  A tap goes to the page if it takes touches; on any other page it holds the rotation still and brings up the home
  button. `kiosk-ctl touch X Y` or `kiosk-ctl touch next` writes one, to try it without a screen.
- **The panel:** `touchpanel.py` reads it on the Pi, in a thread of `kiosk.py`. It looks for a touch screen every few
  seconds and does nothing until one turns up, then works out taps and gestures and writes the touch file. With a touch
  screen, the home page joins the playlist by itself (never in the rotation), so the menu gesture has somewhere to go.
  An upside-down screen (`rotate=180` in the kernel's `video=` option) turns the touches with it.
- **On a kiosk with a render server**, the Pi sends each touch up the link (`TUCH` in `remote.py`), and the server
  writes it to its own touch file, so the touch reaches the page where it's drawn.
- **Still to do:** for the browser shapes, the front door could turn a click on the picture into the same file.
- **Make touch targets big:** at least 44 px high, like `around`'s tabs, and keep them away from the screen's edges.

## Wi-Fi rescue

`rescue.py` (the `kiosk-rescue` service, root) watches the Wi-Fi. After 3 minutes without a connection it scans, then turns wlan0 into a hotspot, `<hostname>-setup`, with a new random password each time, and `kiosk.py` shows its name, password and address (http://10.42.0.1) instead of the pages. The page there lists the networks it saw and takes a network and password; the kiosk drops the hotspot and joins, and if that fails within a minute the hotspot comes back, saying why. The page listens on the hotspot only, and only while it is up. Passwords go to NetworkManager as root-only keyfiles, never on a command line. A Pi Zero W only does 2.4 GHz and WPA2.

Auto-update and `pi-setup.sh` enable any service in `systemd/` with an `[Install]` section, so kiosks pick this up with their next update.
