#!/usr/bin/env python3
"""sysfeed: streams my desktop's resources to the desk kiosk's system page, every 2 seconds.

CPU per thread and in total (/proc/stat), its temperature (k10temp's Tctl), the GPU (nvidia-smi), memory and swap
(/proc/meminfo), the root disk, network throughput on the busiest interface, load and uptime. It keeps the last two
minutes of CPU and GPU load, so the page can draw them as graphs without remembering anything itself.

It holds one SSH connection to the Pi, with a key that can only feed kiosk/pages/system/sink.py, and writes one JSON
line per sample. sysfeed.service keeps it running.

  sysfeed.py            stream
  sysfeed.py --once     print one sample and exit
  sysfeed.py --check    self-test
"""
import glob, json, os, re, shutil, socket, subprocess, sys, time

HOST = os.environ.get("KIOSK_HOST", "kiosk@kiosk.local")
KEY = os.path.expanduser("~/.ssh/desk-kiosk-system")
EVERY, HISTORY = 2, 60   # seconds between samples; samples kept for the graphs (2 minutes)


def cpu_times():
    """/proc/stat -> {'cpu': (busy, total), 'cpu0': ...}"""
    out = {}
    for line in open("/proc/stat"):
        if line.startswith("cpu"):
            name, *v = line.split(); v = [int(x) for x in v[:8]]
            idle = v[3] + v[4]
            out[name] = (sum(v) - idle, sum(v))
    return out


def percent(before, after):
    busy, total = after[0] - before[0], after[1] - before[1]
    return round(100 * busy / total, 1) if total > 0 else 0.0


def hwmon(name, sensor="temp1_input"):
    for h in glob.glob("/sys/class/hwmon/hwmon*"):
        try:
            if open(f"{h}/name").read().strip() == name:
                return round(int(open(f"{h}/{sensor}").read()) / 1000, 1)
        except OSError:
            continue
    return None


def meminfo(text):
    m = {k: int(v) for k, v in re.findall(r"^(\w+):\s+(\d+)", text, re.M)}   # kB
    gb = lambda kb: round(kb / 1048576, 1)
    return {"mem_used": gb(m["MemTotal"] - m["MemAvailable"]), "mem_total": gb(m["MemTotal"]),
            "swap_used": gb(m.get("SwapTotal", 0) - m.get("SwapFree", 0)), "swap_total": gb(m.get("SwapTotal", 0))}


def gpu():
    if not shutil.which("nvidia-smi"):
        return None
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=name,utilization.gpu,temperature.gpu,memory.used,memory.total,power.draw",
                              "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5).stdout
        name, util, temp, used, total, power = [x.strip() for x in out.splitlines()[0].split(",")]
        num = lambda x: float(x) if re.fullmatch(r"[\d.]+", x) else 0.0
        return {"name": name.replace("NVIDIA ", "").replace("GeForce ", ""), "util": num(util), "temp": num(temp),
                "vram_used": round(num(used) / 1024, 1), "vram_total": round(num(total) / 1024, 1), "power": num(power)}
    except (OSError, IndexError, ValueError, subprocess.TimeoutExpired):
        return None


def net_bytes():
    """the busiest real interface -> (name, rx, tx)"""
    best = None
    for line in open("/proc/net/dev").readlines()[2:]:
        name, data = line.split(":", 1); name = name.strip(); v = data.split()
        if name == "lo" or name.startswith(("docker", "veth", "br-", "virbr", "tailscale")):
            continue
        rx, tx = int(v[0]), int(v[8])
        if best is None or rx + tx > best[1] + best[2]:
            best = (name, rx, tx)
    return best or ("-", 0, 0)


def cpu_model():
    for line in open("/proc/cpuinfo"):
        if line.startswith("model name"):
            return re.sub(r"\s+\d+-Core Processor|\(R\)|\(TM\)|AMD |Intel ", "", line.split(":", 1)[1]).strip()
    return "CPU"


def sample(before, after, net_before, net_after, seconds):
    cores = sorted((k for k in after if k != "cpu"), key=lambda k: int(k[3:]))
    disk = shutil.disk_usage("/")
    return {"cpu": percent(before["cpu"], after["cpu"]), "threads": [percent(before[c], after[c]) for c in cores],
            "rx": round((net_after[1] - net_before[1]) / seconds), "tx": round((net_after[2] - net_before[2]) / seconds),
            "iface": net_after[0], "disk_used": round(disk.used / 1e9), "disk_total": round(disk.total / 1e9)}


class Stream:
    def __init__(self):
        self.ssh = None

    def send(self, msg):
        if self.ssh is None or self.ssh.poll() is not None:
            self.ssh = subprocess.Popen(["ssh", "-T", "-i", KEY, "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes",
                                         "-o", "ConnectTimeout=5", "-o", "ServerAliveInterval=10", HOST],
                                        stdin=subprocess.PIPE, text=True)
        try:
            self.ssh.stdin.write(json.dumps(msg, separators=(",", ":")) + "\n"); self.ssh.stdin.flush()
            return True
        except (BrokenPipeError, OSError):
            self.ssh.kill(); self.ssh = None
            return False


def run(once=False):
    stream, cpu_hist, gpu_hist = Stream(), [], []
    host, model = socket.gethostname(), cpu_model()
    before, net_before, t = cpu_times(), net_bytes(), time.time()
    while True:
        time.sleep(EVERY)
        after, net_after, now = cpu_times(), net_bytes(), time.time()
        msg = dict(sample(before, after, net_before, net_after, now - t), t="system", host=host, model=model,
                   cpu_temp=hwmon("k10temp") or hwmon("coretemp"), disk_temp=hwmon("nvme"), gpu=gpu(),
                   load=round(os.getloadavg()[0], 2), uptime=round(time.monotonic()),
                   **meminfo(open("/proc/meminfo").read()))
        before, net_before, t = after, net_after, now
        cpu_hist = (cpu_hist + [msg["cpu"]])[-HISTORY:]
        gpu_hist = (gpu_hist + [msg["gpu"]["util"] if msg["gpu"] else 0])[-HISTORY:]
        msg.update(cpu_hist=cpu_hist, gpu_hist=gpu_hist)
        if once:
            print(json.dumps(msg, indent=1)); return
        if not stream.send(msg):
            time.sleep(10)   # the Pi's away: try again in a bit


def check():
    assert percent((100, 1000), (150, 1100)) == 50.0 and percent((5, 5), (5, 5)) == 0.0
    m = meminfo("MemTotal:       32000000 kB\nMemAvailable:   12000000 kB\nSwapTotal:       8388608 kB\nSwapFree:        8388608 kB\n")
    assert m == {"mem_used": 19.1, "mem_total": 30.5, "swap_used": 0.0, "swap_total": 8.0}, m
    before = {"cpu": (0, 100), "cpu1": (0, 50), "cpu0": (0, 50), "cpu10": (0, 50)}
    after = {"cpu": (60, 200), "cpu1": (10, 100), "cpu0": (50, 100), "cpu10": (0, 100)}
    s = sample(before, after, ("eth", 0, 0), ("eth", 2000, 500), 2)
    assert s["cpu"] == 60.0 and s["threads"] == [100.0, 20.0, 0.0], "threads in number order, not text order"
    assert s["rx"] == 1000 and s["tx"] == 250
    assert all(k in cpu_times() for k in ("cpu", "cpu0")) and net_bytes()[0] != "lo"
    print("sysfeed: ok")


if __name__ == "__main__":
    if sys.argv[1:] == ["--check"]:
        check()
    elif sys.argv[1:] == ["--once"]:
        run(once=True)
    elif not sys.argv[1:]:
        run()
    else:
        sys.exit(__doc__)
