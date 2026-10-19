# Working on Wi-Ki

This is for writing pages and transitions, and for changing Wi-Ki itself. To set one up, start with
[kiosk.md](kiosk.md).

Read `AGENTS.md` first. It has the Pi's limits and the rules that keep the display working.

## Layout

| Folder | What it is |
|---|---|
| `kiosk/` | The base, which runs on every kiosk. `kiosk.py` shows the pages listed in the playlist and draws them to the framebuffer. It also has the auto-updates, the render server, the browser kiosks, the Wi-Fi rescue, the calendar's event sync and the transitions player. |
| `catalog/` | What a kiosk picks from: `pages/<name>/`, `transitions/<name>.py`, and an entry for each in `entries/` with its licence, art credits, shapes, services and settings. `catalog.py` checks the entries against the code, and `catalog/CATALOG.md` is the table it writes. |
| `emulator/` | Previews the pages on your own computer. |
| `feed/` | Runs on a desktop. Gathers what the GitHub, agents, system and now-playing pages show and pushes it to the kiosk. `kiosk-ctl` and the Desk Kiosk tray widget pick which page it shows. |
| `setup/` | Builds a kiosk from a blank SD card. |
| `deploy/` | Pushes changes to a kiosk by hand. |
| `docs/` | The guides: a kiosk, a render server, connectors, and this one. |

On a kiosk, the catalog's pages and transitions sit inside `~/kiosk/` (`pages/` and `transitions/`), so a kiosk's paths stay simple. `kiosk/autoupdate.py` puts them there.

## Day to day

You'll need Python 3 with Pillow, and `ffmpeg` for the emulator's videos.

```
python3 -I kiosk/kiosk.py --check               # every page's self-test
python3 -I kiosk/kiosk.py --png weather w.png   # a picture of any page
python3 -I catalog/catalog.py --check           # the catalog against the code on origin/main
python3 -I emulator/emulate.py --frames 1       # every weather scenario on one sheet, in emulator/out/
deploy/deploy.sh                                # self-tests, copy to the Pi, verify, restart the display
```

The Pi is `kiosk@kiosk.local` unless you set `KIOSK_HOST`. SSH is key-only.

## Updates

**Pushing to `main` deploys to every kiosk.** Every 10 minutes each kiosk checks GitHub. The repo is public, so it pulls over https and needs no key. When `main` has moved, it runs a quick smoke test on the new code, and only if that passes does it swap it in and restart the display. A commit that fails is skipped until a newer one arrives. So run `python3 -I kiosk/kiosk.py --check` before you push: the full check takes about 10 minutes on a Zero, which is why the Pi only runs the quick one.

On the Pi, `sudo python3 -I ~/kiosk/autoupdate.py --status` shows what's applied and what's on GitHub, and `journalctl -u kiosk-autoupdate` shows what it did. `deploy/deploy.sh` still works for trying something before it's on `main`. It stays on the Pi until `main` moves again.

## Pages and transitions

[`catalog/CATALOG.md`](../catalog/CATALOG.md) lists everything in the catalog, with what each needs. [make.md](make.md) says how to make a new one: `python3 -I catalog/catalog.py --new page <name>` (or `transition`) starts it from a template that already works, with its catalog file. A page that needs more than the template gives can write the whole interface, which `kiosk/kiosk.py` describes. `AGENTS.md` has the rules.

Between pages, a transition plays for about 3 seconds, and the ones a kiosk has installed take turns. The catalog has: **CoreOne** (the new page is printed layer by layer by a zig-zagging hotend), **Hive76** (honeycomb cells fill with honey and open onto it, while a bee flies past), **Nomads Galaxy** (warp: it opens from the middle between beams, and the Drifter flies through), **The Matrix** (forty columns of code rain, with the new page showing through behind each one), **Hackerman** (a neon terminal hacks time while the page glitches in), **Johnny 5** (a comic page: he rolls in and strikes, and the new page comes through) and **Cherdenko** (a Soviet-era poster of the Premier escaping to space, which blasts off on a rocket flame). Nothing flashes the whole screen, so they're safe for anyone sensitive to flicker. A kiosk can turn any of them off in `transitions-off.json`.

## Your own landscape

The weather page plays the real weather over Philadelphia's skyline, but it can show any place's: give it `"landscape": "<name>"` in the playlist's options, and it uses `catalog/landscapes/<name>/` instead, with that landscape's own location and heading unless the playlist says otherwise. The catalog comes with one, `lake`, a mountain lake drawn for it (CC0).

To make one, draw it at 300×128 pixels, the size it's shown at (it's scaled up four times on the screen):

- **`landscape.png`:** the land, with the sky left clear. RGBA, 64 colours or fewer, 64 KB at most. Draw it as it looks at noon; the page lights it for the time of day.
- **`windows.png`, `water.png`, `leaves.png`:** optional masks, white where lights come on at dusk, where it's water (the scene mirrors and ripples there), and where there are leaves (they take the season's colours, by how light each one is). Leave one out and that effect doesn't happen.
- **`landscape.json`:** its name; `place`, the heading; `lat` and `lon`, for the forecast; `waterline`, the row the water starts at; `strike`, the `[x, y]` lightning hits; and `credit`, with `author`, `licence` and `source`.

The licence has to be an open one (CC0, CC BY or CC BY-SA), and anything traced from a photo names the photo in `source`. `kiosk.py --check` holds every landscape to these rules. Send one in as a pull request that adds its folder, and a person looks at the art and where it came from before it's merged. `catalog/pages/weather/scene.py` has the details.

## Publishing a page or transition from your own repo

A kiosk installs the catalog's pages and transitions from its own copy of this repo, so they're always the version that
goes with its code. Anyone can also publish one on GitHub for kiosks to install from the setup page's **Install** tab.

**From someone's repo.** Anyone can publish a page or a transition on GitHub, and a kiosk can install it from there. Nobody has reviewed that code, and it runs with the kiosk's own access, so the setup page asks you to say you understand that before it installs one. Only install from people you trust. It's pinned to the exact commit it was installed at, so it never changes by itself; **Check for updates** says when there's a newer one, and **Update** installs it. Before it's switched on, the kiosk loads it in a separate process and has it draw once, so one that's plainly broken doesn't get installed.

To publish one, put these at the top of a GitHub repo:

- **`wiki-pack.json`:** `{"name": "clock", "kind": "page", "about": "a big clock", "licence": "MIT"}`. The kind is `page` or `transition`, and the name is 2 to 31 lowercase letters, digits and `_`, starting with a letter, and can't be one the catalog already has.
- **The code:** a page is a folder named after it (`clock/`, with `__init__.py` exporting `Page`, `check()` and `preview()`, like the catalog's pages); a transition is one file (`clock.py`, with `frames(canvas, count)`). `AGENTS.md` has the rules that keep them working on a Pi Zero.

A pack holds `.py`, `.json`, `.png`, `.txt` and `.md` files only, up to 200 of them, 4 MB to download and 8 MB unpacked, with no links. On a kiosk whose pages a render server draws, the setup page installs on the server too (pages run there; transitions play on the Pi, so they go on both). `kiosk/packs.py` has the details.
