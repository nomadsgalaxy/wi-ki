# A render server

A Pi Zero is slow at drawing but quick at copying. A render server draws a kiosk's pages and sends them to the Pi,
which just puts them on its screen. Pages that are heavy for a Zero (the radar, now playing, system) run smoothly this
way, and the same server can show the kiosk in a browser too.

> **How it is today:** one render server draws for **one** Pi. A second Pi connecting to the same server takes over
> from the first. For several kiosks, run one server for each: they're small, so a container each on one machine is
> fine. Setting a server up and pairing it still uses SSH.
>
> **Coming:** one server for any number of kiosks, with "Use a server" on the kiosk's setup page and a pairing code
> instead of copying a key, every kiosk's settings and backups in one place on the server, and an encrypted link
> between them (board topic 103). This guide changes to match when that lands.

## What you need

- A **small Linux box or container**, Debian 12 or newer, with 2 cores and 1 GB of memory. A Proxmox LXC works well.
  It needs no screen.
- **Root over SSH with your key** on it, from a computer with a copy of this repo.
- A **kiosk** already set up ([kiosk.md](kiosk.md)), on a network that can reach the server on port **7676**.

## Steps

1. **Give the server its `kiosk` user and services.** From the repo, as root on the server:
   ```
   scp setup/pi-setup.sh root@<server>:/tmp/ && ssh root@<server> bash /tmp/pi-setup.sh
   ```
   With no screen (`/dev/fb0`), `pi-setup.sh` makes it a render server: it creates the `kiosk` user with root's SSH
   keys, installs Pillow and git, and installs `kiosk-serve` and the browser kiosks instead of the screen login.

   **You should see:** a note that the code isn't there yet. That's expected, because the next step puts it there.

2. **Put the code on it:**
   ```
   KIOSK_HOST=kiosk@<server> deploy/deploy.sh
   ```
   It runs every self-test here first, then copies and checks the files.

3. **Run step 1 again, then reboot the server** (`ssh root@<server> reboot`). The second run installs the timers that
   come with the code (auto-update and event sync), and the reboot starts `kiosk-serve` and the browser kiosks. From
   then on, the server updates itself from GitHub every 10 minutes, the same way a kiosk does.

4. **Make a key the two will share:**
   ```
   python3 -c "import secrets; print(secrets.token_hex(32))"
   ```
   Every settings message between the kiosk and its server is signed with it and only works once, so nothing else on
   the network can change them. Keep it somewhere safe, like a password manager.

5. **Point the kiosk at the server.** On the kiosk, write `~/.config/kiosk/remote.json`:
   ```json
   {"server": "<server address>", "port": 7676, "key": "<the key>"}
   ```
   and on the server, `~/.config/kiosk/remote.json` with the same key:
   ```json
   {"key": "<the key>"}
   ```
   Then restart the kiosk's display: in a shell on the kiosk, `pkill -f kiosk.py`. Its screen login starts it again in
   3 seconds, and it connects to the server.

   **You should see:** the kiosk's setup page says **Pages drawn by** the server on its Status tab, and
   `journalctl -u kiosk-serve` on the server says "the Pi connected from" the kiosk's address.

6. **Change its pages from the kiosk's setup page,** as before. With the key in place, the Pages, Transitions and
   Location tabs change what the server draws. Without the key, they show the server's settings but can't change them.

## What it does

- After every frame, the server sends the Pi only the rows that changed, compressed. On a page change it sends the new
  page and which transition to play, and the Pi plays it itself.
- **If the Pi can't reach the server,** or the link drops, the Pi draws its own pages and tries the server again every
  minute. So a server that's down just makes the kiosk slower, not blank, and it switches back by itself.
- **The playlist lives on the server,** in the server's own `~/.config/kiosk/`. The kiosk's own playlist is only used
  while it draws for itself.
- **Desktop feeds go to the server,** not the Pi, since that's where the pages run: set `KIOSK_HOST=kiosk@<server>`
  when you install them ([connectors.md](connectors.md)). `kiosk-ctl` talks to the server too.
- **Pages installed from the setup page** go on the server. Transitions play on the Pi, so they go on both.

## Browser kiosks

A render server also draws the kiosk for any screen with a browser:

- `http://<server>/16-9` for TVs and tablets in landscape;
- `http://<server>/9-16` for phones.

Each shape has its own renderer (`kiosk-web@16-9`, `kiosk-web@9-16`) with its own rotation, and it only draws while
someone's watching. A page shows up in a shape only if it can lay itself out for it.

## If it doesn't work

- **The kiosk still draws its own pages:** check `remote.json` on the kiosk (the server's address and port), and that
  the kiosk can reach port 7676 on the server. Firewalls between VLANs are the usual cause.
- **Two kiosks keep taking turns:** they're pointed at the same server, which only draws for one. Give each its own.
- **The setup page shows the server's settings but won't save:** the keys don't match, or one side has none. They have
  to be the same 64 characters on both.
- **The server isn't updating:** `sudo python3 -I ~/kiosk/autoupdate.py --status` on it shows what's applied and what's
  on GitHub, and `journalctl -u kiosk-autoupdate` shows what it did.

The details are in `kiosk/remote.py` (the frames), `kiosk/link.py` (the signed settings), and `kiosk/web.py` (the
browser kiosks).
