#!/bin/bash
# Turn a freshly booted Pi into the kiosk, or a fresh Debian box into its render server (one without a screen: see
# kiosk/remote.py). Push the code first, then run this on it as root:
#   deploy/deploy.sh && deploy/as-root.sh setup/pi-setup.sh
# Safe to run again.
set -euo pipefail
apt-get -qq update >/dev/null
DEBIAN_FRONTEND=noninteractive apt-get -qq install -y python3-pil git >/dev/null   # Pillow: all the drawing; git: updates
if ! id kiosk >/dev/null 2>&1; then   # the Pi's card makes the kiosk user; a server needs one made, with root's keys
  useradd -m -s /bin/bash kiosk
  install -d -m700 -o kiosk -g kiosk /home/kiosk/.ssh
  install -m600 -o kiosk -g kiosk /root/.ssh/authorized_keys /home/kiosk/.ssh/authorized_keys
fi
install -d -o kiosk -g kiosk /home/kiosk/kiosk

if [ ! -e /dev/fb0 ]; then   # no screen: this is the render server, which draws the pages and sends them to the Pi
  cat > /etc/systemd/system/kiosk-serve.service <<'S'
[Unit]
Description=Desk kiosk render server: draws the pages and sends them to the Pi (kiosk/remote.py)
After=network-online.target

[Service]
User=kiosk
ExecStart=/usr/bin/python3 -I /home/kiosk/kiosk/kiosk.py --serve
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
S
  # and the browser kiosks (kiosk/web.py): a renderer for each shape, and the front door on port 80
  cat > /etc/systemd/system/kiosk-web@.service <<'S'
[Unit]
Description=Desk kiosk browser renderer, %i (kiosk/web.py)
After=network-online.target

[Service]
User=kiosk
Environment=KIOSK_SHAPE=%i
ExecStart=/usr/bin/python3 -I /home/kiosk/kiosk/kiosk.py --web
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
S
  cat > /etc/systemd/system/kiosk-web-front.service <<'S'
[Unit]
Description=Desk kiosk browser front door, port 80 (kiosk/web.py)
After=network-online.target

[Service]
User=kiosk
AmbientCapabilities=CAP_NET_BIND_SERVICE
ExecStart=/usr/bin/python3 -I /home/kiosk/kiosk/kiosk.py --front
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
S
  systemctl daemon-reload
  systemctl enable kiosk-serve.service kiosk-web@16-9.service kiosk-web@9-16.service kiosk-web-front.service
fi

if [ -e /dev/fb0 ]; then   # the Pi: kiosk logs in on tty1 by itself, and that login runs the display
mkdir -p /etc/systemd/system/getty@tty1.service.d
printf '[Service]\nExecStart=\nExecStart=-/sbin/agetty --autologin kiosk --noclear %%I $TERM\n' \
  > /etc/systemd/system/getty@tty1.service.d/autologin.conf
cat > /home/kiosk/.bash_profile <<'P'
. ~/.profile
# on the Pi's own screen, run the kiosk (its pages take turns), and bring it back if it ever exits
if [ "$(tty)" = /dev/tty1 ]; then
  while :; do python3 -I ~/kiosk/kiosk.py; sleep 3; done
fi
P
chown kiosk:kiosk /home/kiosk/.bash_profile

# never blank the screen, and keep boot messages off the console (firstboot.sh does this too, for older cards)
for extra in consoleblank=0 systemd.show_status=0; do
  grep -q "$extra" /boot/firmware/cmdline.txt || sed -i "1 s/\$/ $extra/" /boot/firmware/cmdline.txt
done
fi

# updates from GitHub: the repo is public, so the kiosk user clones it over https and needs no key
runuser -u kiosk -- bash -c '[ -d ~/HiveKiosk/.git ] || git clone -q https://github.com/nomadsgalaxy/wi-ki.git ~/HiveKiosk' \
  || echo "Couldn't clone github.com/nomadsgalaxy/wi-ki; check the kiosk's network, then run this again."

# the timers that come with the code (the event sync, auto-update), so deploy first
if [ -d /home/kiosk/kiosk/systemd ]; then
  install -m644 /home/kiosk/kiosk/systemd/* /etc/systemd/system/
  systemctl daemon-reload
  for t in /home/kiosk/kiosk/systemd/*.timer /home/kiosk/kiosk/systemd/*.path; do systemctl enable --now "$(basename "$t")"; done
  for s in /home/kiosk/kiosk/systemd/*.service; do   # and the services that run all the time (the Wi-Fi rescue)
    grep -q '^\[Install\]' "$s" && systemctl enable --now "$(basename "$s")"
  done
  systemctl start kiosk-eventsync.service
else
  echo "The code isn't on the Pi yet: run deploy/deploy.sh, then this again, for the timers." >&2
fi
systemctl daemon-reload
echo "Set up. Reboot (sudo reboot) to start on the kiosk."
