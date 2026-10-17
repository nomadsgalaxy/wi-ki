# Wi-Ki

Wide Kiosk: the base OS and catalog for every kiosk I run, from my desks to the screens at Hive76. It's built for a Raspberry Pi Zero W on a 12.6" stretched bar screen (1920×515), and it cycles through pages: the weather, with a pixel-art Philly skyline that plays the real weather, time of day and season; a flight radar of what's overhead; my latest GitHub pushes; my agents and their usage; my desktop's CPU, GPU, memory and network; what's playing, with the cover, synced lyrics and a live spectrum; and more in the catalog.

Every kiosk runs the same code. What makes one kiosk different from another lives on the kiosk itself, in `~/.config/kiosk/`, not in a branch.

## Layout

| Folder | What it is |
|---|---|
| `kiosk/` | The base, which runs on every kiosk. `kiosk.py` shows the pages listed in the playlist and draws them to the framebuffer. It also has the auto-updates, the render server, the browser kiosks, the Wi-Fi rescue, the calendar's event sync and the transitions player. |
| `catalog/` | What a kiosk picks from: `pages/<name>/`, `transitions/<name>.py`, and an entry for each in `entries/` with its licence, art credits, shapes, services and settings. `catalog.py` checks the entries against the code, and `CATALOG.md` is the table it writes. |
| `emulator/` | Previews the pages on your own computer. |
| `feed/` | Runs on a desktop. Gathers what the GitHub, agents, system and now-playing pages show and pushes it to the kiosk. `kiosk-ctl` and the Desk Kiosk tray widget pick which page it shows. |
| `setup/` | Builds a kiosk from a blank SD card. |
| `deploy/` | Pushes changes to a kiosk by hand. |

On a kiosk, the catalog's pages and transitions sit inside `~/kiosk/` (`pages/` and `transitions/`), so a kiosk's paths stay simple. `kiosk/autoupdate.py` puts them there.

Working on the code? Read `AGENTS.md` first. It has the Pi's limits and the rules that keep the display working.

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

## A kiosk's own settings

Each kiosk keeps its own settings in `~/.config/kiosk/`. The updates never touch it, and every file is optional:

| File | What it sets | Without it |
|---|---|---|
| `branch` | the branch to follow | `main` |
| `playlist.json` | the pages, how long each stays up, and their options (like `lat`, `lon` and `place` for the weather) | the repo's `kiosk/playlist.json`: weather and radar, over Philadelphia |
| `transitions-off.json` | transitions to skip, like `["matrix"]` (`deploy/kiosk-config` writes it) | all of them on |
| `remote.json` | its render server: `{"server": "<address>", "port": 7676}` | it draws its own pages |
| `eventsync.json` | where the calendar's events come from | no events |
| `config.json` | the card's ID, and `"setup": false` to turn its setup page off | the setup page is on, wherever there's a screen |
| `installed.json`, `packs.json` | what's installed beyond the core, from the catalog and from repos (the setup page keeps them) | just the core |
| `admin-login.json` | the setup page's login, as a hash (the setup page writes it) | the first-boot login on the screen |

The setup page changes `playlist.json` and `transitions-off.json` for you, on a kiosk that draws its own pages.

## Setting up a new kiosk

1. Flash **Raspberry Pi OS Lite, 32-bit** (trixie or newer) to the SD card. Don't boot it yet.
2. With the card's boot partition mounted: `setup/firstboot.sh /run/media/$USER/bootfs`. It asks for the Wi-Fi name and password and a password for the `kiosk` user, and writes cloud-init's first-boot files (hostname `kiosk`, your SSH key, no password logins over SSH).
3. Boot the Pi and give it 2–3 minutes.
4. `deploy/deploy.sh` puts the code on the Pi.
5. `deploy/as-root.sh setup/pi-setup.sh` installs Pillow and git, sets tty1 to log in and run the kiosk, and starts the timers (event sync and auto-update). It also clones the repo for the updates. It asks for the `kiosk` password.
6. Reboot the Pi.

**For a kiosk on a network you can't reach** (so you can't run steps 4 and 5 over SSH), run step 2 as `KIOSK_HOSTNAME=<name> KIOSK_UNATTENDED=1 setup/firstboot.sh <boot partition>`. The card then sets itself up on first boot (about 15 minutes on a Zero): it installs what it needs, clones the repo, puts the code in place, runs `pi-setup.sh` and reboots into the kiosk. After that it updates itself like any other kiosk.

Then give it its own settings in `~/.config/kiosk/`, if it needs any.

## The setup page

A kiosk can host its own setup page, so you can change its pages, transitions and location from a browser on the same network, without SSH. It's on by default on every kiosk with a screen, so you can come back and change things whenever you like, at `https://<the kiosk's address>`. To turn it off, put `"setup": false` in the kiosk's `~/.config/kiosk/config.json`, or make the card with `KIOSK_SETUP=0 setup/firstboot.sh <boot partition>`. Render servers never run it.

**The first login.** While the kiosk isn't set up, its screen shows its address, a user name like `Kiosk-Otter` and a three-word password. Both are new every time the setup page starts, and they're only kept in memory. Go to the address. Your browser will warn that it can't check the certificate, because the kiosk made it for itself. Only go past that warning if the SHA-256 fingerprint your browser shows for it matches the one on the kiosk's screen: ignore the colons and capitals, and compare all 64 characters. If it doesn't match, don't log in, because something else on the network answered. The first thing it asks is for your own user name and password, and the screen stops showing the old ones.

**What it changes.** The status of the kiosk, its pages (on or off, how long each stays up, their order, and more from the catalog), its transitions and its location. A change restarts the display, so you'll see it in a few seconds. A kiosk whose pages come from a render server has those settings on the server: give the kiosk and its server the same `"key"` in `remote.json` (below) and the setup page changes them there. Without the key, it shows them but doesn't change them.

**Forgot the login?** Over SSH, delete `~/.config/kiosk/admin-login.json` and run `sudo systemctl restart kiosk-admin`. The screen shows a new first-boot login.

It only serves HTTPS, on the kiosk's own addresses and only to local networks. Logins slow down after 5 wrong tries, and every change has to come from the page itself. `kiosk/admin.py` has the details, and `kiosk/setup_check.py` tests them. Setting a kiosk up by name (`https://k-<id>.kiosk.local`) is built in but stays off until the kiosks have their own certificate authority.

## Installing pages and transitions

A kiosk comes with a small core: the weather, radar and calendar pages, and the Nomads Galaxy and Matrix transitions (`kiosk/core.json`). Everything else is installed from the setup page's **Install** tab, and taken off again there. A page in the playlist stays installed until you take it out of the playlist, and the core always stays.

**From the catalog.** Every page and transition in `catalog/` has been reviewed before it was merged. A kiosk installs them from its own copy of the repo, so they're always the version that goes with its code, and its updates keep them up to date.

**From someone's repo.** Anyone can publish a page or a transition on GitHub, and a kiosk can install it from there. Nobody has reviewed that code, and it runs with the kiosk's own access, so the setup page asks you to say you understand that before it installs one. Only install from people you trust. It's pinned to the exact commit it was installed at, so it never changes by itself; **Check for updates** says when there's a newer one, and **Update** installs it. Before it's switched on, the kiosk loads it in a separate process and has it draw once, so one that's plainly broken doesn't get installed.

To publish one, put these at the top of a GitHub repo:

- **`wiki-pack.json`:** `{"name": "clock", "kind": "page", "about": "a big clock", "licence": "MIT"}`. The kind is `page` or `transition`, and the name is lowercase letters, digits and `_`, and can't be one the catalog already has.
- **The code:** a page is a folder named after it (`clock/`, with `__init__.py` exporting `Page`, `check()` and `preview()`, like the catalog's pages); a transition is one file (`clock.py`, with `frames(canvas, count)`). `AGENTS.md` has the rules that keep them working on a Pi Zero.

A pack holds `.py`, `.json`, `.png`, `.txt` and `.md` files only, up to 200 of them and 8 MB, with no links. On a kiosk whose pages a render server draws, the setup page installs on the server too (pages run there; transitions play on the Pi, so they go on both). `kiosk/packs.py` has the details.

## The render server

A Pi Zero is slow at drawing but quick at copying, so a kiosk can have a render server draw its pages while the Pi just shows them. A server is any small Linux box or container (Debian, 2 cores and 1 GB is plenty) running the same code as `kiosk.py --serve` (the `kiosk-serve` service). It updates itself from `main` the same way the Pi does. Setting one up is the same as a Pi, minus the screen: `deploy/deploy.sh`, then `setup/pi-setup.sh` as root. With no `/dev/fb0`, it installs `kiosk-serve` instead of the tty1 login. Then point the Pi at it with `~/.config/kiosk/remote.json`.

After every frame, the server sends the Pi only the rows that changed, compressed. On a page change it sends the new page and which transition to play, and the Pi plays it itself. If the Pi can't reach the server, or the link drops, the Pi draws the pages itself for 10 minutes, then tries the server again. The desktop feeds and `kiosk-ctl` go to the server. Details are in `kiosk/remote.py`.

**Changing its settings from the kiosk.** The kiosk's setup page can change the pages, transitions and location a render server draws for it, once both have the same key in `~/.config/kiosk/remote.json`: `{"server": "<address>", "port": 7676, "key": "<64 hex characters>"}` on the Pi, and the same `"key"` in the server's own `remote.json`. Make one with `python3 -c "import secrets; print(secrets.token_hex(32))"`. Every message between them is signed with it and only works once, so nothing else on the network can change the kiosk. `kiosk/link.py` has the details.

## Browser kiosks

A render server also draws the kiosk for screens with more bandwidth than a Pi: `http://<server>/16-9` (TVs, tablets in landscape) and `/9-16` (phones). In `kiosk/web.py`, each shape has its own renderer (`kiosk-web@16-9`, `kiosk-web@9-16`) with its own rotation and transitions, and the front door (`kiosk-web-front`, port 80) streams lossless PNG frames to a plain `<img>`. A renderer only draws while someone's watching.

Shapes are in `kit.SHAPES`, and a process draws the one `KIOSK_SHAPE` names. A page lists the shapes it can lay itself out for in `Page.shapes`, and a shape's rotation only has those pages.

## Pages and transitions

`CATALOG.md` lists everything in the catalog, with what each needs. To add a page, make `catalog/pages/<name>/` exporting `Page`, `check()` and `preview()`, give it an entry (`python3 -I catalog/catalog.py --draft page <name>` starts one), then add it to a playlist. `kiosk/kiosk.py` describes the interface, `catalog/pages/calendar` is a simple example, and `AGENTS.md` has the rules.

Between pages, a transition plays for about 3 seconds, and the ones a kiosk has installed take turns. The catalog has: **CoreOne** (the new page is printed layer by layer by a zig-zagging hotend), **Hive76** (honeycomb cells fill with honey and open onto it, while a bee flies past), **Nomads Galaxy** (warp: it opens from the middle between beams, and the Drifter flies through), **The Matrix** (forty columns of code rain, with the new page showing through behind each one), **Hackerman** (a neon terminal hacks time while the page glitches in) and **Johnny 5** (a comic page: he rolls in and strikes, and the new page comes through). Nothing flashes the whole screen, so they're safe for anyone sensitive to flicker. A kiosk can turn any of them off in `transitions-off.json`.

### The desktop pages

GitHub, agents, system and now playing show what a desktop pushes to the kiosk, so they need the feeds in `feed/` running on that desktop. `feed/README.md` covers setting them up: `deskfeed` for GitHub and agents, `sysfeed` for system, and `nowplaying.py` for what's playing. The Desk Kiosk tray widget is optional.

### Calendar events

The calendar reads `~/.cache/kiosk/events.json`, whenever it changes:

```json
{"updated": "2026-10-14T15:00:00",
 "events": [{"title": "Open House", "start": "2026-10-16T19:00", "end": "2026-10-16T22:00", "all_day": false, "location": "Hive76"}]}
```

Times are local (America/New_York). Use a plain date as `start` for all-day events. Only `title` and `start` are required.

`kiosk/eventsync.py` writes it, from the sources in the kiosk's `eventsync.json` (one module each in `kiosk/sources/`). A systemd timer runs it at boot and every 15 minutes. If a source fails, its last events are kept.

## Credits

The setup page's first-boot passwords use the [EFF short word list](https://www.eff.org/dice) (`kiosk/words.txt`), by the Electronic Frontier Foundation, licensed [CC BY 3.0 US](https://creativecommons.org/licenses/by/3.0/us/). The skyline is traced from [The Philadelphia skyline (cropped)](https://commons.wikimedia.org/wiki/File:The_Philadelphia_skyline_(cropped).jpg) by Mefman00, licensed [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/), and the pixel art is shared under the same licence. The text uses the VGA console font from Debian's `console-setup`; its notice is in [`kiosk/fonts/LICENSE`](kiosk/fonts/LICENSE). Forecasts come from [Open-Meteo](https://open-meteo.com), flights from [adsb.lol](https://adsb.lol), or [adsb.fi](https://adsb.fi) when it's away, and routes from [adsbdb.com](https://www.adsbdb.com). The radar's street map is © [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors (ODbL). Every other page's and transition's credits are in its catalog entry.

## Licence

Wi-Ki is built by NomadsGalaxy, and it comes under two licences:

- **The pages and transitions are MIT** ([`LICENSE-MIT`](LICENSE-MIT)): everything in `catalog/pages/` and `catalog/transitions/`.
- **Everything else is the engine,** under the Open Community Licence with the Software Attribution add-on: **OCL v1.1 + SWAtt v1**. That's `kit.py`, `kiosk.py`, the transitions' player and `canvas.py`, the setup and update code, the feeds and the tools.

A page's own code is MIT even though it runs inside the OCL engine; the engine's terms still cover the engine. If you share something built on the engine, say so where people use it and in its source: "Built By NomadsGalaxy", linking to [nomadsgalaxy.com](https://nomadsgalaxy.com). Ours says it at the top of `kiosk/kit.py`. The texts are in [`LICENSE`](LICENSE) and [`LICENSE-SWAtt-v1.md`](LICENSE-SWAtt-v1.md), copied unchanged from [OpenCommunityLicence/OpenCommunityLicence](https://github.com/OpenCommunityLicence/OpenCommunityLicence) (commit `7469fcd`). The assets and data keep their own licences: the skyline's pixel art, for one, stays CC BY-SA 4.0.
