# The desktop side

Four things run on my desktop for the kiosk: the feed, which fills in the GitHub and agents pages; the now-playing
and system streams; and the controls, which pick the page it shows. `install.sh` sets them all up (it's safe to run
again).

## The feed

The kiosk's `github` and `agents` pages show things only my desktop can see: private repos, my herdr workspaces and my
Claude and Codex quotas. `deskfeed.py` gathers them every 5 minutes and pushes them to the Pi as
`~/.cache/kiosk/desk.json`. The pages read that file through `kit.Feed`.

It needs `gh` (logged in), `herdr` and `kodexbar-quotas` (KodexBar Suite) on the desktop. Each one is its own
section, so if one breaks the others still go out, and the page shows that section's error.

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
kiosk-ctl                 # status: the pages, the one showing, and the pinned one if any
kiosk-ctl show github     # jump to a page and stay there
kiosk-ctl auto            # back to the rotation
kiosk-ctl next            # skip to the next page, and back to the rotation
```

It uses its own key, `~/.ssh/desk-kiosk-control`, which the Pi only lets run `kiosk/control.py`:

```
restrict,command="python3 -I /home/kiosk/kiosk/control.py" ssh-ed25519 AAAA… desk-kiosk-control
```

`control.py` checks the page against the playlist and writes `~/.cache/kiosk/control.json`, and `kiosk.py` picks it up
within a quarter second. A pinned page starts over every time its seconds run out, so the weather still refreshes.

The **Desk Kiosk** tray widget (`plasmoid/`, installed with `kpackagetool6 -t Plasma/Applet -i feed/plasmoid`) runs
`kiosk-ctl`. Click it for a button per page and Auto and Next; middle-click skips to the next page. The tray icon turns
into a pin while a page is pinned. It only asks the Pi for status while the popup is open.
