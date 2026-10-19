# Setting up a kiosk

This takes a Raspberry Pi from a blank SD card to a kiosk showing your pages. Once the card is written, everything
happens in a browser on the kiosk's setup page.

> **Coming:** a ready-made Wi-Ki image you flash and boot, which puts up its own Wi-Fi hotspot so you can pick your
> network from a phone (board topic 102). When it lands, step 2 below goes away and this guide changes to match.
> Until then, writing the card takes one command on a computer.

## What you need

- A **Raspberry Pi Zero W** (or another Pi) and a **1920×515 bar screen**, the 12.6" stretched kind. Other screens
  work, but the pages are laid out for that one.
- A **microSD card**, 8 GB or more.
- A **Linux computer** with `bash`, `openssl` and `python3` to write the card, and the Wi-Fi name and password the
  kiosk will use. It puts your SSH key (`~/.ssh/id_ed25519.pub`, or the file `KIOSK_KEY_FILE` names) on the card, so
  you can still get in if you ever need to. Make one with `ssh-keygen -t ed25519` if you haven't got one.
- **Raspberry Pi OS Lite, 32-bit**, trixie or newer. Flash it with Raspberry Pi Imager, and skip Imager's own
  settings: the next step writes those.

## Steps

1. **Flash the card** with Raspberry Pi OS Lite (32-bit). Don't boot it yet. Take it out and put it back in, so the
   boot partition (`bootfs`) is mounted.

2. **Write Wi-Ki's first boot onto it.** From a copy of this repo:
   ```
   KIOSK_UNATTENDED=1 setup/firstboot.sh /run/media/$USER/bootfs
   ```
   It asks for the Wi-Fi name and password, and a password for the kiosk's `kiosk` user (only kept as a hash). It
   prints the card's ID, like `k-6cca5e`. Add `KIOSK_HOSTNAME=<name>` to give it a name other than `kiosk`.

   **You should see:** `card ID: k-…` and no errors. Eject the card.

3. **Boot the Pi** with the card and the screen plugged in, and leave it for about 15 minutes. On the first boot, a
   Zero installs what it needs, fetches Wi-Ki from GitHub, sets itself up and reboots.

   **You should see:** the screen shows the setup page's address, a user name like `Kiosk-Otter`, a three-word
   password and a certificate fingerprint.

4. **Open the setup page** from a phone or computer on the same network, at the address on the screen
   (`https://…`). Your browser warns that it can't check the certificate, because the kiosk made its own. Only go past
   that warning if the SHA-256 fingerprint your browser shows matches the one on the screen: ignore colons and
   capitals, and compare all 64 characters. If it doesn't match, stop, because something else on the network
   answered.

5. **Log in** with the user name and password from the screen. The first thing it asks for is your own user name and
   password. From then on, the screen stops showing the first-boot login.

6. **Make it yours.** The setup page has these tabs:
   - **Status:** its card ID, name and addresses, the code it's running, and what it's showing.
   - **Pages:** turn pages on and off, change their order and how long each stays up, and open **config** on a page
     for its own settings, like the sports teams or the weather's units.
   - **Transitions:** which ones play between pages.
   - **Install:** more pages and transitions from the catalog, or from someone's GitHub repo.
   - **Location:** where the weather, radar and other local pages look.
   - **Login:** change your user name and password.

   A change restarts the display, so you'll see it within a few seconds.

   A page in the playlist stays installed until you take it out of the playlist, and the core (weather, radar,
   calendar, home, and the Nomads Galaxy and Matrix transitions) always stays. Something installed from someone's repo
   hasn't been reviewed and runs with the kiosk's own access, so only install from people you trust. It stays at the
   version you installed until you press **Update**.

The setup page only serves HTTPS (plain HTTP just sends you there), on the kiosk's own addresses and only to local
networks. Logins slow down after 5
wrong tries, and every change has to come from the page itself. `kiosk/admin.py` has the details.

That's it. The kiosk checks GitHub every 10 minutes and updates itself, so you don't need to do anything to keep it
current.

## Pages that need something else

Most pages only need the internet. A few need more:

- **GitHub, agents, system and now playing** show what's on a desktop, so that desktop runs a small feed, and they
  run on a render server. See [connectors.md](connectors.md) and [server.md](server.md).
- **The calendar** shows events from sources you set up. See [connectors.md](connectors.md).
- **Several kiosks, or a slow Pi:** a render server can draw the pages for them. See [server.md](server.md).

## If it doesn't work

- **Nothing on the screen after 20 minutes:** check that the screen works with another device, and that the card was
  written with `KIOSK_UNATTENDED=1`. Without it, the card only joins Wi-Fi and waits to be set up over SSH (the
  manual path, below).
- **It can't reach your Wi-Fi:** after 3 minutes without a network, the kiosk turns itself into a hotspot called
  `<its name>-setup` and shows the hotspot's password on the screen. Join it from a phone, open `http://10.42.0.1`, and
  pick your network from the list it saw. If the new network doesn't work within a minute, the hotspot comes back and
  says so.
- **The browser can't reach the setup page:** the phone or computer has to be on the same network as the kiosk, and the
  setup page only answers local networks. Check the address on the screen, not an old one: a kiosk's address can
  change when the router gives it a new one.
- **The fingerprint doesn't match:** don't log in. Something else on the network has the kiosk's old address, which
  happens when the router moves addresses around. Use the address on the screen right now.
- **A page says "waiting…" or shows an error:** it's waiting for data it hasn't got yet, like a desktop feed that isn't
  set up. The rest of the pages keep going.
- **Forgot your setup login:** this one needs SSH today. Delete `~/.config/kiosk/admin-login.json` on the kiosk and run
  `sudo systemctl restart kiosk-admin`, and the screen shows a new first-boot login. A way to do this at the kiosk itself
  is planned.

## Still needs a terminal

The goal is a kiosk you can set up without SSH or a terminal at all. These are what's left, and where each is going:

| needs a terminal today | where it's going |
|---|---|
| writing Wi-Fi onto the card (step 2) | the flash-and-go image's hotspot |
| pairing a kiosk with a render server | "Use a server" on the setup page, with a code |
| settings a page marks as set over SSH (a feed's file, the calendar's events) | picked from the connectors the kiosk knows |
| an API key file (cfradar's token) | key fields on the setup page |
| following another branch | Status, under advanced |
| restoring a backup | a Backup tab |
| a forgotten setup login | a reset at the kiosk itself (it can't be on the page, or anyone could get in) |

## The manual path

For a kiosk you can reach over SSH, or when you're working on Wi-Ki itself:

1. Write the card without `KIOSK_UNATTENDED`: `setup/firstboot.sh /run/media/$USER/bootfs`. It puts your SSH key
   (`~/.ssh/id_ed25519.pub`, or `KIOSK_KEY_FILE`) on the card and turns off password logins over SSH.
2. Boot it and give it 2–3 minutes.
3. `deploy/deploy.sh` puts the code on the Pi (`kiosk@kiosk.local`, or `KIOSK_HOST`).
4. `deploy/as-root.sh setup/pi-setup.sh` installs what it needs, sets tty1 to log in and run the kiosk, and starts
   the timers. It asks for the `kiosk` password.
5. Reboot the Pi.

`KIOSK_SETUP=0` on `firstboot.sh` makes a kiosk with no setup page.

## Where its settings live

Each kiosk keeps its own settings in `~/.config/kiosk/`. The updates never touch them, and every file is optional.
The setup page writes most of them for you.

| File | What it sets | Without it |
|---|---|---|
| `playlist.json` | the pages, how long each stays up, and their settings | weather and radar, over Philadelphia |
| `transitions-off.json` | transitions to skip, like `["matrix"]` | all of them on |
| `installed.json`, `packs.json` | what's installed beyond the core, from the catalog and from repos | just the core |
| `config.json` | the card's ID, and `"setup": false` to turn the setup page off | the setup page is on |
| `admin-login.json` | the setup page's login, as a hash | the first-boot login on the screen |
| `remote.json` | its render server (see [server.md](server.md)) | it draws its own pages |
| `eventsync.json` | where the calendar's events come from (see [connectors.md](connectors.md)) | no events |
| `branch` | the branch to follow | `main` |

**Backing them up.** `tools/kiosk-backup` copies each kiosk's settings into a git repo of your own, one folder per
kiosk, so a dead SD card can be set up again the way it was. It runs on a desktop that can reach the kiosks over SSH
and pulls, so the kiosks hold no key to the backups. Secrets stay on the kiosk: the setup login and certificates aren't
copied, the key in `remote.json` is left out, and a file that still looks like it holds a key or a token is refused.
`tools/kiosk-backup --restore` puts a kiosk's settings back.
