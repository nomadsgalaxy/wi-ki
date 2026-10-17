#!/bin/bash
# Run a local script on the Pi as root.
#   deploy/as-root.sh setup/pi-setup.sh
# It asks for the kiosk user's sudo password (or takes it from KIOSK_SUDO_PASSWORD) and sends it over stdin, never on
# a command line, so it can't show up in the Pi's process list. The script is copied over as a file for the same
# reason (and so a pkill -f in it can't match its own command).
set -euo pipefail
script="${1:?usage: deploy/as-root.sh <script>}"
host="${KIOSK_HOST:-kiosk@kiosk.local}"
if [ -z "${KIOSK_SUDO_PASSWORD:-}" ]; then
  read -rsp "sudo password for kiosk on $host: " KIOSK_SUDO_PASSWORD; echo
fi

scp -q "$script" "$host:/tmp/kiosk-as-root.sh"
printf '%s\n' "$KIOSK_SUDO_PASSWORD" | ssh "$host" 'sudo -S -p "" bash /tmp/kiosk-as-root.sh; status=$?; rm -f /tmp/kiosk-as-root.sh; exit $status'
