#!/usr/bin/env python3
"""autoupdate: keeps the Pi on the latest main from GitHub. A systemd timer runs it as root every 10 minutes
(systemd/kiosk-autoupdate.*); the git work and the tests run as the kiosk user.

Each run:
1. fetches main into the Pi's clone (~/HiveKiosk, pulled over https: the repo is public) and stops if nothing changed
   since the last commit it applied;
2. puts the new code together beside the running one and runs the smoke test on it (every page loads and draws; the
   full check is too slow for a Zero, so that runs before pushing), and stops if it fails (and won't try that commit
   again);
3. swaps the new kiosk/ (with the catalog's pages and transitions, see assemble()) in for ~/kiosk in one move,
   installs any systemd units that changed, and restarts the display.

It remembers the last commit it applied, not what's in ~/kiosk, so a manual deploy/deploy.sh (for trying something
out) stays until main moves.

  autoupdate.py              check for an update and apply it
  autoupdate.py --status     what's applied, and what's on GitHub
  autoupdate.py --assemble DIR  build the kiosk/ folder a kiosk runs into DIR (deploy.sh uses it)
"""
import fcntl, filecmp, os, shutil, subprocess, sys, time

HOME = "/home/kiosk"
CLONE, LIVE = f"{HOME}/HiveKiosk", f"{HOME}/kiosk"
STATE = f"{HOME}/.cache/kiosk"
APPLIED, REFUSED = f"{STATE}/applied-commit", f"{STATE}/refused-commit"
UNITS = "/etc/systemd/system"
# a kiosk can follow another branch, to try something first; ~/.config is outside ~/kiosk, so updates keep it
BRANCH = (open(f"{HOME}/.config/kiosk/branch").read().strip() if os.path.exists(f"{HOME}/.config/kiosk/branch") else "") or "main"


def kiosk(*cmd, timeout=120):
    """run as the kiosk user, in the clone; returns stdout. setpriv rather than runuser: no PAM session, so the journal
    only has what we say"""
    as_kiosk = ["setpriv", "--reuid=kiosk", "--regid=kiosk", "--init-groups", "env", "-i", f"HOME={HOME}", "PATH=/usr/bin:/bin"]
    return subprocess.run(as_kiosk + list(cmd), cwd=CLONE, check=True, capture_output=True, text=True,
                          timeout=timeout).stdout.strip()


def read(path):
    try:
        return open(path).read().strip()
    except OSError:
        return ""


def write(path, value):
    for d in (f"{HOME}/.cache", STATE):   # we're root: make them the kiosk's, or the event sync can't write there
        if not os.path.isdir(d):
            os.mkdir(d); shutil.chown(d, "kiosk", "kiosk")
    open(path, "w").write(value + "\n")
    shutil.chown(path, "kiosk", "kiosk")


def log(msg):
    print(f"autoupdate: {msg}", flush=True)


def assemble(repo, dest):
    """the kiosk/ folder a kiosk runs, at dest: the repo's kiosk/, with the catalog's pages and transitions put back
    where they run (pages/<name>/ and transitions/<name>.py), so a kiosk's paths are the same as they've always been"""
    skip = shutil.ignore_patterns("__pycache__")
    shutil.copytree(f"{repo}/kiosk", dest, ignore=skip)
    for name in os.listdir(f"{repo}/catalog/pages"):
        shutil.copytree(f"{repo}/catalog/pages/{name}", f"{dest}/pages/{name}", ignore=skip)
    for name in os.listdir(f"{repo}/catalog/transitions"):
        if name.endswith(".py"):
            shutil.copy2(f"{repo}/catalog/transitions/{name}", f"{dest}/transitions/{name}")


def update():
    kiosk("git", "fetch", "--quiet", "origin", BRANCH)
    new = kiosk("git", "rev-parse", f"origin/{BRANCH}")
    if new == read(APPLIED):
        return log(f"up to date ({new[:7]})")
    if new == read(REFUSED):
        return log(f"{new[:7]} failed its tests before; waiting for a newer commit")
    kiosk("git", "reset", "--quiet", "--hard", new)
    subject = kiosk("git", "log", "-1", "--format=%s", new)
    log(f"testing {new[:7]}: {subject}")
    # the new code goes in beside the running one, and the smoke test runs on exactly that, so a folder put together
    # wrong fails here instead of on the screen
    shutil.rmtree(f"{LIVE}.new", ignore_errors=True); shutil.rmtree(f"{LIVE}.old", ignore_errors=True)
    assemble(CLONE, f"{LIVE}.new")
    subprocess.run(["chown", "-R", "kiosk:kiosk", f"{LIVE}.new"], check=True)
    started = time.time()
    try:
        kiosk("nice", "python3", "-I", f"{LIVE}.new/kiosk.py", "--smoke", timeout=900)
    except subprocess.CalledProcessError as e:
        write(REFUSED, new); shutil.rmtree(f"{LIVE}.new", ignore_errors=True)
        return log(f"{new[:7]} failed its tests, not applying it:\n{(e.stderr or e.stdout)[-1500:]}")
    except subprocess.TimeoutExpired:   # a busy Zero, not a bad commit: try it again next time rather than refuse it
        shutil.rmtree(f"{LIVE}.new", ignore_errors=True)
        return log(f"{new[:7]}'s tests took over 15 minutes, not applying it yet; trying again next time")
    log(f"smoke test passed in {time.time() - started:.0f} s")

    # then it swaps in in one move
    if os.path.isdir(LIVE):
        os.rename(LIVE, f"{LIVE}.old")
    os.rename(f"{LIVE}.new", LIVE)
    shutil.rmtree(f"{LIVE}.old", ignore_errors=True)

    # systemd units that came with it: install the ones that changed, and make sure every timer is on
    changed = []
    for name in sorted(os.listdir(f"{LIVE}/systemd")):
        src, dst = f"{LIVE}/systemd/{name}", f"{UNITS}/{name}"
        if not os.path.exists(dst) or not filecmp.cmp(src, dst, shallow=False):
            shutil.copyfile(src, dst); changed.append(name)
    if changed:
        subprocess.run(["systemctl", "daemon-reload"], check=True)
        log(f"installed {', '.join(changed)}")
    for name in os.listdir(f"{LIVE}/systemd"):   # every timer on, and every service that says it wants to run always
        if name.endswith(".timer") or name.endswith(".service") and "[Install]" in open(f"{LIVE}/systemd/{name}").read():
            subprocess.run(["systemctl", "enable", "--now", name], check=True, capture_output=True)
            if name in changed and name.endswith(".service"):
                subprocess.run(["systemctl", "restart", name], capture_output=True)

    # the Pi's login loop brings it back in 3 s, and on a render server systemd does, which runs it as /usr/bin/python3
    subprocess.run(["pkill", "-f", f"(^|/)python3 -I {LIVE}/kiosk.py"])
    write(APPLIED, new)
    log(f"applied {new[:7]}: {subject}")


def status():
    kiosk("git", "fetch", "--quiet", "origin", BRANCH)
    applied, latest, refused = read(APPLIED), kiosk("git", "rev-parse", f"origin/{BRANCH}"), read(REFUSED)
    print(f"applied:   {applied[:7] or 'nothing yet'}")
    print(f"on GitHub: {latest[:7]} ({BRANCH})  {kiosk('git', 'log', '-1', '--format=%s', latest)}")
    if refused:
        print(f"refused:   {refused[:7]} (its tests failed)")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--assemble":   # deploy/deploy.sh: what the Pi gets, built here
        sys.exit(assemble(os.path.join(os.path.dirname(os.path.realpath(__file__)), ".."), sys.argv[2]))
    if os.geteuid() != 0:
        sys.exit("autoupdate.py runs as root (systemd does that); try: sudo python3 -I ~/kiosk/autoupdate.py")
    if sys.argv[1:] == ["--status"]:
        status()
    elif len(sys.argv) == 1:
        lock = open("/run/kiosk-autoupdate.lock", "w")
        try:   # one at a time: the timer and someone running it by hand mustn't swap the code at once
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            sys.exit(log("another update is running") or 0)
        update()
    else:
        sys.exit(__doc__)
