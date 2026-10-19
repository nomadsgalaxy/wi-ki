# Connectors: getting your data onto a kiosk

Most pages fetch what they show from the internet by themselves: the weather, the radar, sports, Around, SEPTA. They
need nothing but a network. A few show things only you have, like your desktop's CPU, your music, your repos or your
calendar. Those need a **connector**: something on another machine that sends the kiosk that data.

Today there are two kinds: the **desktop feeds** and the **calendar's event sources**.

> **Coming:** a general connector contract, so anything that can serve JSON can feed a page, and a **Home
> Assistant** page that reads your entities with a token, set up and tested from the setup page (board topic 103).
> Setting up a connector still uses a terminal on the desktop today, but never on the kiosk.

## A desktop

Four pages show what's on a desktop: **GitHub** (your repos, PRs and issues), **agents** (your herdr workspaces, and
plan usage), **system** (CPU, GPU, memory, network) and **now playing** (the song, cover, lyrics and a live spectrum).
The desktop runs small programs that send the kiosk this, each over its own SSH key that the kiosk only lets do that
one thing.

### What you need

- A **render server** for the kiosk ([server.md](server.md)). These four pages run there, because that's where the
  feeds go.
- A **Linux desktop** with Python 3, on the same network as the render server.
- The tools behind the pages you want. A tool that isn't there just leaves its part out:

  | page | needs on the desktop |
  |---|---|
  | GitHub | `gh`, logged in |
  | agents | `herdr`; plan usage also needs KodexBar (`kodexbar-quotas`) |
  | system | nothing extra (`nvidia-smi` for the GPU, if you have one) |
  | now playing | a player that speaks MPRIS, and `cava` for the spectrum |
  | calendar | KDE's calendar (Akonadi) and `konsolekalendar`, for desktop events (below) |

- **SSH to the render server** with your own key, just this once, so the installer can hand it the feeds' keys.
- For the tray widget, **KDE Plasma 6** (`kpackagetool6`) and a `~/.local/bin` on your `PATH`. Without Plasma, the
  installer stops at the widget, after the feeds are already running.

### Steps

1. **Run the installer** from a copy of this repo on the desktop:
   ```
   KIOSK_HOST=kiosk@<server> feed/install.sh
   ```
   It makes a key for each feed, gives each one to the server locked down to its one job, installs the feeds as user
   services and pushes once. Then it links `kiosk-ctl` into `~/.local/bin` and installs the Desk Kiosk tray widget,
   which pick the page the kiosk shows. It's safe to run again.

2. **Pick your GitHub owners,** if you want something other than your `gh` account and its first two orgs. Run step 1
   with them set:
   ```
   DESKFEED_OWNERS="nomadsgalaxy=Nomads Galaxy,hive76" KIOSK_HOST=kiosk@<server> feed/install.sh
   ```
   Each is a GitHub login, with the name to show after an `=` if you like. The page shows three.

3. **Turn the pages on** in the kiosk's setup page, under **Pages** (or **Install** if they're not there yet).

   **You should see:** GitHub and agents fill in within 5 minutes, system right away, and now playing joins the
   rotation whenever music plays.

### If it doesn't work

- `journalctl --user -u deskfeed` (or `sysfeed`, `nowplaying`) on the desktop shows what each one did.
- `feed/deskfeed.py` prints the feed it would send, `feed/sysfeed.py --once` a system sample, and
  `feed/nowplaying.py --once` the song.
- **A page says it's waiting:** the feed hasn't arrived. Check that `KIOSK_HOST` is the render server that draws the
  kiosk's pages, not the Pi.
- **When the desktop is off,** the pages keep showing the last feed, and after 15 minutes they say how old it is.

`feed/README.md` has the details of each feed, setting them up by hand, and `kiosk-ctl` and the tray widget, which
pick what the kiosk shows from the desktop.

## The calendar

The calendar page shows events from `~/.cache/kiosk/events.json` on the kiosk. The kiosk's event sync writes it at
boot and every 15 minutes, from the sources in the kiosk's `~/.config/kiosk/eventsync.json`. If a source fails, its
last events are kept.

There are two sources today:

- **`recurring`:** events on the same weekday every week, written into the settings:
  ```json
  {"output": "~/.cache/kiosk/events.json", "days": 14,
   "sources": [{"source": "recurring", "options": {"events": [
     {"title": "Member Night", "weekday": "wednesday", "start": "19:00", "end": "22:00", "location": "Hive76"}]}}]}
  ```
- **`desk`:** the events on a desktop's KDE calendars, the ones its Event Calendar widget shows. They come in with the
  desktop feed above (titles, times and places only, never descriptions):
  ```json
  {"output": "~/.cache/kiosk/events.json", "days": 14, "sources": [{"source": "desk"}]}
  ```

`eventsync.json` is set over SSH today. Picking calendars from the setup page is part of the connectors work.

## Your own data

Anything that can write a file to the kiosk can feed it. The simplest is the calendar's file, which any program can
write:

```json
{"updated": "2026-10-14T15:00:00",
 "events": [{"title": "Open House", "start": "2026-10-16T19:00", "end": "2026-10-16T22:00", "all_day": false,
             "location": "Hive76"}]}
```

Times are local. Use a plain date as `start` for an all-day event. Only `title` and `start` are required.

For your own page, see [develop.md](develop.md): a page can read any file, and the feeds above show how to get one onto
a kiosk safely, with a key that can only write that one file.
