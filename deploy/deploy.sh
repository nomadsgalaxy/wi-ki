#!/bin/bash
# Push the kiosk to the Pi and restart the display.
#   deploy/deploy.sh                       (the Pi is kiosk@kiosk.local unless KIOSK_HOST says otherwise)
# It runs every page's self-test, ships kiosk/ (with the catalog's pages and transitions) to the Pi as ~/kiosk.new,
# checks every file arrived intact, then swaps it in for ~/kiosk in one move (so anything deleted here is gone there
# too) and restarts kiosk.py.
# No sudo needed: the kiosk user owns its files, and its login brings kiosk.py back within 3 seconds.
set -euo pipefail
here="$(cd "$(dirname "$0")/.." && pwd)"
host="${KIOSK_HOST:-kiosk@kiosk.local}"

python3 -I "$here/kiosk/kiosk.py" --check
stage=$(mktemp -d); trap 'rm -rf "$stage"' EXIT
python3 -I "$here/kiosk/autoupdate.py" --assemble "$stage/kiosk"   # kiosk/ plus the catalog's pages and transitions

tar -C "$stage/kiosk" --exclude=__pycache__ -czf - . | ssh "$host" 'rm -rf ~/kiosk.new && mkdir ~/kiosk.new && tar -C ~/kiosk.new -xzf -'

sums='find . -type f ! -path "*/__pycache__/*" -print0 | LC_ALL=C sort -z | xargs -0 sha256sum'   # LC_ALL=C: the same order on any machine
local_sums=$(cd "$stage/kiosk" && eval "$sums")
remote_sums=$(ssh "$host" "cd ~/kiosk.new && $sums")
if [ "$local_sums" != "$remote_sums" ]; then
  echo "The files on the Pi don't match. Nothing was changed." >&2
  diff <(echo "$local_sums") <(echo "$remote_sums") >&2 || true
  exit 1
fi

ssh "$host" 'rm -rf ~/kiosk.old && { [ ! -d ~/kiosk ] || mv ~/kiosk ~/kiosk.old; } && mv ~/kiosk.new ~/kiosk && rm -rf ~/kiosk.old
             pkill -f "python3 -I /home/kiosk/kiosk/[k]iosk.py" || true   # on the Pi and the server; [k]: not this shell'
echo "Deployed to $host. The display restarts in a few seconds (about 7 more if the trees need working out)."
