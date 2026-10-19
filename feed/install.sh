#!/bin/sh
# Set up the desktop side of the desk kiosk. It trusts the Pi's host key, makes the feed, control, now-playing and
# system keys and gives them to the Pi locked down: the feed key can only replace ~/.cache/kiosk/desk.json, the control
# key can only run kiosk/control.py, and the now-playing and system keys can only feed their pages' sinks. Then it
# installs the feed's user timer and pushes once, starts the now-playing and system streams, links kiosk-ctl into
# ~/.local/bin and installs the Desk Kiosk tray widget. Safe to run again: it skips whatever is already there.
set -eu
host=${KIOSK_HOST:-kiosk@kiosk.local}
here=$(dirname "$(readlink -f "$0")")

# Everything goes to the render server (kiosk/remote.py), which draws the pages and sends them to the Pi. Its host key
# is trusted the first time only.
ssh-keygen -F "${host#*@}" >/dev/null || ssh-keyscan -t ed25519 "${host#*@}" >> ~/.ssh/known_hosts

[ -e ~/.ssh/desk-kiosk-feed ] || ssh-keygen -q -t ed25519 -N '' -C desk-kiosk-feed -f ~/.ssh/desk-kiosk-feed

restrict='restrict,command="mkdir -p ~/.cache/kiosk && cat > ~/.cache/kiosk/desk.json.tmp && [ -s ~/.cache/kiosk/desk.json.tmp ] && mv ~/.cache/kiosk/desk.json.tmp ~/.cache/kiosk/desk.json"'
printf '%s %s\n' "$restrict" "$(cat ~/.ssh/desk-kiosk-feed.pub)" |
  ssh "$host" 'grep -q desk-kiosk-feed ~/.ssh/authorized_keys || cat >> ~/.ssh/authorized_keys'

[ -e ~/.ssh/desk-kiosk-control ] || ssh-keygen -q -t ed25519 -N '' -C desk-kiosk-control -f ~/.ssh/desk-kiosk-control
printf 'restrict,command="python3 -I /home/kiosk/kiosk/control.py" %s\n' "$(cat ~/.ssh/desk-kiosk-control.pub)" |
  ssh "$host" 'grep -q desk-kiosk-control ~/.ssh/authorized_keys || cat >> ~/.ssh/authorized_keys'

[ -e ~/.ssh/desk-kiosk-nowplaying ] || ssh-keygen -q -t ed25519 -N '' -C desk-kiosk-nowplaying -f ~/.ssh/desk-kiosk-nowplaying
printf 'restrict,command="python3 -I /home/kiosk/kiosk/pages/nowplaying/sink.py" %s\n' "$(cat ~/.ssh/desk-kiosk-nowplaying.pub)" |
  ssh "$host" 'grep -q desk-kiosk-nowplaying ~/.ssh/authorized_keys || cat >> ~/.ssh/authorized_keys'

[ -e ~/.ssh/desk-kiosk-system ] || ssh-keygen -q -t ed25519 -N '' -C desk-kiosk-system -f ~/.ssh/desk-kiosk-system
printf 'restrict,command="python3 -I /home/kiosk/kiosk/pages/system/sink.py" %s\n' "$(cat ~/.ssh/desk-kiosk-system.pub)" |
  ssh "$host" 'grep -q desk-kiosk-system ~/.ssh/authorized_keys || cat >> ~/.ssh/authorized_keys'

mkdir -p ~/.config/systemd/user
for unit in deskfeed.service deskfeed.timer nowplaying.service sysfeed.service; do   # with this checkout's path and host
  sed -e "s|%h/wi-ki/feed|$here|g" -e "s|KIOSK_HOST=kiosk@kiosk.local|KIOSK_HOST=$host|" \
    -e "s|DESKFEED_OWNERS=\"|DESKFEED_OWNERS=${DESKFEED_OWNERS:-}\"|" \
    "$here/$unit" > ~/.config/systemd/user/$unit
done
systemctl --user daemon-reload
systemctl --user enable --now deskfeed.timer nowplaying.service sysfeed.service
systemctl --user restart nowplaying.service sysfeed.service   # picks up changed scripts on a rerun
systemctl --user start deskfeed.service   # one push now

ssh "$host" 'ls -l ~/.cache/kiosk/desk.json && head -c 120 ~/.cache/kiosk/desk.json; echo'

ln -sf "$here/kiosk-ctl" ~/.local/bin/kiosk-ctl
widget=$(mktemp -d)   # the widget runs kiosk-ctl by its full path, so it gets this user's
cp -r "$here/plasmoid/." "$widget" && sed -i "s|\"kiosk-ctl\"|\"$HOME/.local/bin/kiosk-ctl\"|" "$widget/contents/ui/main.qml"
kpackagetool6 -t Plasma/Applet -u "$widget" 2>/dev/null || kpackagetool6 -t Plasma/Applet -i "$widget"
rm -rf "$widget"
kiosk-ctl status
