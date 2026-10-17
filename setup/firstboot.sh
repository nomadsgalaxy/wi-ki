#!/bin/bash
# Write the kiosk's first-boot setup onto a freshly flashed Raspberry Pi OS Lite card.
#   setup/firstboot.sh /run/media/$USER/bootfs
# Raspberry Pi OS trixie and later set themselves up with cloud-init from files on the boot partition. This writes
# them: the hostname (KIOSK_HOSTNAME, default "kiosk"), timezone, the kiosk user with sudo and your SSH key (password
# logins over SSH are off), and the Wi-Fi. It asks for the passwords (or takes KIOSK_PASSWORD and KIOSK_WIFI_PASS from
# the environment). The Wi-Fi password goes onto the card (it has to), the kiosk user's password only as a hash.
#
# Unattended: set KIOSK_DEPLOY_KEY to the private half of a read-only deploy key that's already on the GitHub repo,
# and the Pi sets itself up completely on first boot, for a kiosk on a network you can't reach: it installs what it
# needs, clones the repo, puts the code in place (autoupdate.py), runs pi-setup.sh and reboots into the kiosk, then
# keeps itself updated. The key is removed from the card's boot partition once it's been used.
set -euo pipefail
boot="${1:?usage: setup/firstboot.sh <mounted boot partition>}"
[ -f "$boot/cmdline.txt" ] || { echo "$boot doesn't look like a Raspberry Pi boot partition (no cmdline.txt)." >&2; exit 1; }

export KIOSK_HOSTNAME="${KIOSK_HOSTNAME:-kiosk}"
[ -n "${KIOSK_WIFI_SSID:-}" ] || read -rp "Wi-Fi network name: " KIOSK_WIFI_SSID
export KIOSK_WIFI_SSID
export KIOSK_KEY="$(cat "${KIOSK_KEY_FILE:-$HOME/.ssh/id_ed25519.pub}")"
[ -n "${KIOSK_PASSWORD:-}" ] || { read -rsp "password for the kiosk user (for sudo): " KIOSK_PASSWORD; echo; }
[ -n "${KIOSK_WIFI_PASS:-}" ] || { read -rsp "Wi-Fi password for $KIOSK_WIFI_SSID: " KIOSK_WIFI_PASS; echo; }
export KIOSK_HASH="$(printf '%s' "$KIOSK_PASSWORD" | openssl passwd -6 -stdin)" KIOSK_WIFI_PASS
unset KIOSK_PASSWORD

export KIOSK_DEPLOY_KEY="${KIOSK_DEPLOY_KEY:-}" KIOSK_GITHUB_HOST=""
if [ -n "$KIOSK_DEPLOY_KEY" ]; then
  [ -f "$KIOSK_DEPLOY_KEY" ] || { echo "No deploy key at $KIOSK_DEPLOY_KEY." >&2; exit 1; }
  # GitHub's host key, checked against the fingerprint GitHub publishes, so the Pi trusts the right github.com
  KIOSK_GITHUB_HOST=$(ssh-keyscan -t ed25519 github.com 2>/dev/null)
  [ "$(echo "$KIOSK_GITHUB_HOST" | ssh-keygen -lf - | awk '{print $2}')" = "SHA256:+DiY3wvvV6TuJJhbpZisF/zLDA0zPMSvHdkr4UvCOqU" ] \
    || { echo "github.com's host key doesn't match GitHub's published one; not writing it." >&2; exit 1; }
fi

python3 -I - "$boot" <<'EOF'
import json, os, sys
boot, e = sys.argv[1], os.environ
q = json.dumps   # a JSON string is a valid YAML string, so odd characters in a password can't break the file
indent = lambda text, n: "\n".join(" " * n + line for line in text.strip("\n").split("\n"))
unattended = ""
if e["KIOSK_DEPLOY_KEY"]:
    key = open(e["KIOSK_DEPLOY_KEY"]).read()
    unattended = f"""write_files:
  - path: /home/kiosk/.ssh/hivekiosk_deploy
    owner: kiosk:kiosk
    permissions: "0600"
    defer: true
    content: |
{indent(key, 6)}
  - path: /home/kiosk/.ssh/config
    owner: kiosk:kiosk
    permissions: "0600"
    defer: true
    content: |
      Host github.com
        IdentityFile ~/.ssh/hivekiosk_deploy
        IdentitiesOnly yes
  - path: /home/kiosk/.ssh/known_hosts
    owner: kiosk:kiosk
    permissions: "0644"
    defer: true
    content: |
{indent(e["KIOSK_GITHUB_HOST"], 6)}
"""
open(f"{boot}/user-data", "w").write(f"""#cloud-config
hostname: {q(e["KIOSK_HOSTNAME"])}
manage_etc_hosts: true
timezone: America/New_York
users:
  - name: kiosk
    groups: users,adm,dialout,audio,netdev,video,plugdev,input,gpio,render,sudo
    shell: /bin/bash
    lock_passwd: false
    passwd: {q(e["KIOSK_HASH"])}
    ssh_authorized_keys:
      - {q(e["KIOSK_KEY"])}
enable_ssh: true
ssh_pwauth: false
{unattended}runcmd:
  - systemctl enable --now ssh
""" + ("""  - chown -R kiosk:kiosk /home/kiosk/.ssh && chmod 700 /home/kiosk/.ssh
  - DEBIAN_FRONTEND=noninteractive apt-get -qq update && DEBIAN_FRONTEND=noninteractive apt-get -qq install -y python3-pil git
  - runuser -u kiosk -- git clone -q git@github.com:nomadsgalaxy/wi-ki.git /home/kiosk/HiveKiosk
  - python3 -I /home/kiosk/HiveKiosk/kiosk/autoupdate.py
  - bash /home/kiosk/HiveKiosk/setup/pi-setup.sh
  - sed -i '/BEGIN OPENSSH PRIVATE KEY/,/END OPENSSH PRIVATE KEY/c\\      (the deploy key was here; it lives in /home/kiosk/.ssh now)' /boot/firmware/user-data
power_state:
  mode: reboot
  message: the kiosk is set up, rebooting into the kiosk
  condition: true
""" if e["KIOSK_DEPLOY_KEY"] else ""))
open(f"{boot}/network-config", "w").write(f"""network:
  version: 2
  wifis:
    renderer: NetworkManager
    wlan0:
      dhcp4: true
      optional: true
      regulatory-domain: US
      access-points:
        {q(e["KIOSK_WIFI_SSID"])}:
          password: {q(e["KIOSK_WIFI_PASS"])}
""")
open(f"{boot}/meta-data", "w").write("dsmode: local\ninstance-id: kiosk-%s\n" % os.urandom(4).hex())
cmdline = open(f"{boot}/cmdline.txt").read().strip()
for extra in ("consoleblank=0", "cfg80211.ieee80211_regdom=US", "systemd.show_status=0"):
    if extra not in cmdline:
        cmdline += " " + extra   # never blank the screen, Wi-Fi region, no boot chatter on the console
open(f"{boot}/cmdline.txt", "w").write(cmdline + "\n")
print("first-boot files written to", boot, "(unattended)" if e["KIOSK_DEPLOY_KEY"] else "")
EOF
sync
if [ -n "$KIOSK_DEPLOY_KEY" ]; then
  echo "Unmount the card, put it in the Pi and power it on. It sets itself up (about 15 minutes on a Zero) and reboots into the kiosk."
else
  echo "Unmount the card, put it in the Pi and power it on. First boot takes 2-3 minutes; then deploy/deploy.sh and setup/pi-setup.sh."
fi
