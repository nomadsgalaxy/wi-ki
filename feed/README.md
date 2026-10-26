# The desktop side

Four things run on my desktop for the kiosk: the feed, which fills in the GitHub and agents pages; the now-playing
and system streams; and the controls, which pick the page it shows. `install.sh` sets them all up (it's safe to run
again).

## The feed

The kiosk's `github` and `agents` pages show things only my desktop can see: private repos, my herdr workspaces and my
Claude and Codex quotas. `deskfeed.py` gathers them every 5 minutes and pushes them to the Pi as
`~/.cache/kiosk/desk.json`. The pages read that file as their `kit.Simple` file, again whenever it changes.

It uses whichever of `gh` (logged in), `herdr` and `kodexbar-quotas` (KodexBar Suite) the desktop has. Each one is its
own section: a tool that isn't installed sends nothing, and its page leaves that part out (without KodexBar, the
agents page is all herdr). One that breaks still lets the others go out, and the page shows that section's error.

The GitHub page shows three owners: the account `gh` is logged in as and its first two orgs. To pick them yourself,
set `DESKFEED_OWNERS` to logins, each with the name to show after an `=` if you like, before running `install.sh`:

```
DESKFEED_OWNERS="octo-org=Octo Org,acme=Acme Makers,makerspace=Makerspace" feed/install.sh
```

```
feed/deskfeed.py            # print the feed
feed/deskfeed.py --check    # self-test the parsing
```

### Setting it up by hand

1. Make a key just for this. It has no passphrase, because a timer can't answer a prompt:
   ```
   ssh-keygen -t ed25519 -N '' -C desk-kiosk-feed -f ~/.ssh/desk-kiosk-feed
   ```
2. On the Pi, add it to `~/.ssh/authorized_keys`, locked down so the only thing it can do is replace the feed file:
   ```
   restrict,command="mkdir -p ~/.cache/kiosk && cat > ~/.cache/kiosk/desk.json.tmp && [ -s ~/.cache/kiosk/desk.json.tmp ] && mv ~/.cache/kiosk/desk.json.tmp ~/.cache/kiosk/desk.json" ssh-ed25519 AAAA… desk-kiosk-feed
   ```
3. Install the timer:
   ```
   cp feed/deskfeed.service feed/deskfeed.timer ~/.config/systemd/user/
   systemctl --user daemon-reload && systemctl --user enable --now deskfeed.timer
   ```
   The unit pushes to `kiosk@kiosk.local`. To use another address, change `KIOSK_HOST` with
   `systemctl --user edit deskfeed.service`.

`journalctl --user -u deskfeed` shows what it did. When the desktop is off, the pages keep showing the last feed,
and after 15 minutes the masthead says how old it is.

## Now playing

`nowplaying.py` (run by `nowplaying.service`, always on) streams the song to the kiosk's now playing page: what's
playing over MPRIS, the cover and synced lyrics the way Chorus finds them, and cava's spectrum at 20 frames a second,
like the ASCII Visualizer. It only holds a connection to the Pi while something's playing, and hangs up 30 seconds
after it stops. On the kiosk the page only joins the rotation while music plays.

Its key, `~/.ssh/desk-kiosk-nowplaying`, can only feed the page's sink, which checks every message and writes it to RAM:

```
restrict,command="python3 -I /home/kiosk/kiosk/pages/nowplaying/sink.py" ssh-ed25519 AAAA… desk-kiosk-nowplaying
```

`nowplaying.py --once` shows the song it would send. Looking up covers and lyrics sends the artist and title to
Deezer and lrclib.net, same as Chorus.

## System

`sysfeed.py` (run by `sysfeed.service`, always on) streams a sample of my desktop's resources every 2 seconds for the
system page: CPU per thread and in total with its temperature, the GPU through `nvidia-smi`, memory, swap, the root
disk, network throughput and uptime, plus two minutes of CPU and GPU history for the graphs. `sysfeed.py --once` prints
a sample. Its key, `~/.ssh/desk-kiosk-system`, can only feed the page's sink:

```
restrict,command="python3 -I /home/kiosk/kiosk/pages/system/sink.py" ssh-ed25519 AAAA… desk-kiosk-system
```

On the Pi a redraw of the page takes about 0.6 s (packing the full screen to RGB565 is most of it), so while it's up it
uses about a third of the Pi's CPU. Nothing on it moves between samples, so you don't see it.

## The controls

`kiosk-ctl` picks what the kiosk shows:

```
kiosk-ctl                        # status: the pages, the one showing, and the pinned one if any
kiosk-ctl show github            # jump to a page and stay there
kiosk-ctl auto                   # back to the rotation
kiosk-ctl next                   # skip to the next page, and back to the rotation
kiosk-ctl thumbs                 # a small picture of each page, the last time it was on (JSON, base64 JPEGs)
kiosk-ctl transitions            # the transitions installed, and the ones turned off
kiosk-ctl transition tetris off  # turn one off (or on); it restarts the display, as the setup page does
kiosk-ctl setup                  # the setup page's address
```

Where it goes is in `~/.config/kiosk-ctl`, which `install.sh` writes: `host=`, where the pages are drawn (the render
server, if there is one), and `setup=`, the Pi's setup page (set `KIOSK_SETUP` when you run `install.sh` if the pages
are drawn on a render server).

It uses its own key, `~/.ssh/desk-kiosk-control`, which the Pi only lets run `kiosk/control.py`:

```
restrict,command="python3 -I /home/kiosk/kiosk/control.py" ssh-ed25519 AAAA… desk-kiosk-control
```

### Pairing with a kiosk

You don't have to add that key by hand. When you set a kiosk up, its setup page asks for a **shared key** along with
your login: any 8 to 32 characters, the same on every kiosk you want to control. Then, from the computer:

```
kiosk-ctl screens                # the kiosks nearby (they advertise themselves; mDNS doesn't cross VLANs)
kiosk-ctl pair 192.168.1.50       # asks for the shared key, pairs, and writes ~/.config/kiosk-ctl.d/<card id>
KIOSK_SCREEN=k-1a2b3c kiosk-ctl status
KIOSK_SCREEN=k-1a2b3c kiosk-ctl update   # update now: the smoke test still runs, and the render server updates too
```

`pair` makes `~/.ssh/desk-kiosk-control` if you don't have it, and proves it knows the shared key without sending it.
The kiosk adds the key locked to `control.py`, the same line as above. The first time, it shows the kiosk's
certificate fingerprint, which should match the one on the kiosk's screen (or pass `--fingerprint AB:CD:…`), and pins
it. On a kiosk drawn by a render server, you pair with the Pi, and it passes every command on to the server. Wrong
shared keys slow down after five, like logins. A kiosk set up before this can get one from the setup page's login
form, or over SSH with `python3 -I ~/kiosk/pairing.py --set` (it reads the key from stdin).

In the widget, the screens you've paired with are along the top. Once there's one, it picks that one; the **Default**
chip goes back to the screen in `~/.config/kiosk-ctl`, if `install.sh` wrote one. A kiosk that comes back at a new
address keeps the certificate it paired with: if it's changed, `pair` stops and asks you to check the fingerprint.

`control.py` checks the page against the playlist and writes `~/.cache/kiosk/control.json`, and `kiosk.py` picks it up
within a quarter second. A pinned page starts over every time its seconds run out, so the weather still refreshes.

The **Desk Kiosk** widget (`plasmoid/`, installed by `install.sh`) runs `kiosk-ctl`, in the kiosk's own look. It goes on
a panel as a button of its own (right-click the panel, **Add Widgets**, Desk Kiosk), not in the system tray, because
the tray squeezes every widget into one small shared popup. Click it for what's on the kiosk now, a picture of every page in the rotation (the last time each was on screen; the kiosk
keeps them in `~/.cache/kiosk/thumbs/`) to jump to, Auto, Next and Settings (the setup page, in the browser), and the
transitions to turn on and off. Middle-click skips to the next page. The icon turns into a pin while a page is
pinned. It only asks the kiosk anything while the popup is open.

Plasma keeps a widget it has loaded, so after `install.sh` updates it, it only shows once plasmashell restarts
(`systemctl --user restart plasma-plasmashell`).

