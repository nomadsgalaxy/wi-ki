#!/usr/bin/env python3
"""nowplaying: streams what my desktop is playing to the desk kiosk's now playing page, the way Chorus and the ASCII
Visualizer show it here.

- The song comes from MPRIS over busctl (no playerctl): the playing player with the most to say. YouTube Music in
  Vivaldi shows up twice, and plasma-browser-integration's copy has the clean title and artist.
- The cover, like Chorus finds it: the player's art, then a YouTube video's thumbnail, then a Deezer search by artist
  and title (which sends those to Deezer). Shrunk to 120x120 and cut to 64 colours, because the kiosk shows it as
  pixel art anyway. When the player gives no artist (YouTube Music often doesn't), the Deezer hit with the same title
  and length (within 2 s) fills in the artist and album.
- Synced lyrics from lrclib.net, like Chorus. Search results only count if their length matches the song's.
- The spectrum from cava, like the visualizer: 48 bars, 20 frames a second, with light smoothing so it keeps up.

While something plays, it keeps an SSH connection to the Pi open (a key that can only feed kiosk/pages/nowplaying/
sink.py) and writes one JSON line per frame. Thirty seconds after the music stops it hangs up and stops cava.
nowplaying.service keeps it running.

  nowplaying.py            stream
  nowplaying.py --once     print the song it would send, without art or lyrics, and exit
  nowplaying.py --check    self-test
"""
import base64, io, json, os, re, shutil, subprocess, sys, threading, time, urllib.parse, urllib.request

HOST = os.environ.get("KIOSK_HOST", "kiosk@kiosk.local")
KEY = os.path.expanduser("~/.ssh/desk-kiosk-nowplaying")
BARS, FPS, IDLE = 48, 20, 30
UA = {"User-Agent": "wi-ki now playing (github.com/nomadsgalaxy/wi-ki)"}


# --- the song -------------------------------------------------------------------------------------------------------
def bus(*args):
    out = subprocess.run(["busctl", "--user", "--json=short", *args], capture_output=True, text=True, timeout=5)
    return [json.loads(line) for line in out.stdout.splitlines() if line.strip()]


def players():
    """every MPRIS player -> [{bus, status, title, artist, album, length, url, art}]"""
    names = bus("call", "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "ListNames")
    out = []
    for name in (n for n in names[0]["data"][0] if n.startswith("org.mpris.MediaPlayer2.")) if names else []:
        try:
            status, meta = bus("get-property", name, "/org/mpris/MediaPlayer2", "org.mpris.MediaPlayer2.Player",
                               "PlaybackStatus", "Metadata")
        except (ValueError, subprocess.TimeoutExpired):
            continue
        m = {k: v["data"] for k, v in meta["data"].items()}
        artist = m.get("xesam:artist") or []
        out.append({"bus": name, "status": status["data"], "title": m.get("xesam:title", ""),
                    "artist": ", ".join(a for a in artist if a) if isinstance(artist, list) else str(artist),
                    "album": m.get("xesam:album", ""), "length": (m.get("mpris:length") or 0) / 1e6,
                    "url": m.get("xesam:url", ""), "art": m.get("mpris:artUrl", "")})
    return out


def pick(found):
    """the player to show: playing before paused, then the one with an artist (the clean copy of a browser's song)"""
    live = [p for p in found if p["status"] in ("Playing", "Paused") and p["title"]]
    return min(live, key=lambda p: (p["status"] != "Playing", not p["artist"], "chromium" in p["bus"] or "vivaldi" in p["bus"]),
               default=None)


def player_name(p):
    if "music.youtube.com" in p["url"] or p["title"].endswith("| YouTube Music"):
        return "YouTube Music"
    name = p["bus"].split(".")[3]
    return {"plasma-browser-integration": "Browser", "spotify": "Spotify"}.get(name, name.split("_")[0].capitalize())


def position(p):
    try:
        return bus("get-property", p["bus"], "/org/mpris/MediaPlayer2", "org.mpris.MediaPlayer2.Player", "Position")[0]["data"] / 1e6
    except (IndexError, KeyError, ValueError, subprocess.TimeoutExpired):
        return 0.0


def cleaned(title):
    """a title without the junk uploads add, for searching"""
    title = re.sub(r"\s*\|\s*YouTube Music$", "", title)
    title = re.sub(r"\s*[\(\[](official|lyrics?|audio|video|visuali[sz]er|hd|4k)[^\)\]]*[\)\]]", "", title, flags=re.I)
    return re.sub(r"\s*[\(\[]?(feat\.|ft\.)[^\)\]]*[\)\]]?", "", title, flags=re.I).strip()


# --- the cover and the lyrics ---------------------------------------------------------------------------------------
def get(url, timeout=8):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read(4_000_000)


def video_id(url):
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    return q.get("v", [None])[0]


def identify(p):
    """the song on Deezer -> (p with any missing artist and album filled in, the Deezer hit or None)"""
    title = cleaned(p["title"]).lower()
    q = f'{p["artist"].split(",")[0]} {cleaned(p["title"])}'.strip()   # Deezer's track:"" filter misses short titles
    try:
        hits = json.loads(get("https://api.deezer.com/search?limit=50&q=" + urllib.parse.quote(q))).get("data", [])
    except Exception:
        return p, None
    artist = p["artist"].split(",")[0].lower()
    fits = [h for h in hits
            if (title in h["title"].lower() or h["title"].lower() in title)
            and (artist in h["artist"]["name"].lower() if artist else True)
            and (not p["length"] or abs(h.get("duration", 0) - p["length"]) <= 2 or artist)]   # no artist: length must match
    if not fits:
        return p, None
    hit = min(fits, key=lambda h: (h["title"].lower() != title, abs(h.get("duration", 0) - (p["length"] or 0))))
    return dict(p, artist=p["artist"] or hit["artist"]["name"], album=p["album"] or hit["album"]["title"]), hit


def cover(p, hit=None):
    """the cover as base64 PNG, 120x120 and 64 colours, or None"""
    from PIL import Image
    sources = []
    if p["art"].startswith("file://"):
        sources.append(lambda: open(urllib.parse.unquote(p["art"][7:]), "rb").read())
    elif p["art"].startswith("http"):
        sources.append(lambda: get(p["art"]))
    if video_id(p["url"]):
        v = video_id(p["url"])
        sources += [lambda: get(f"https://i.ytimg.com/vi/{v}/maxresdefault.jpg"), lambda: get(f"https://i.ytimg.com/vi/{v}/hqdefault.jpg")]
    if hit:
        sources.append(lambda: get(hit["album"]["cover_xl"]))
    for source in sources:
        try:
            raw = source()
            if not raw:
                continue
            img = Image.open(io.BytesIO(raw)).convert("RGB")
            side = min(img.size)   # the centre square: a YouTube thumbnail's middle is the album cover
            img = img.crop(((img.width - side) // 2, (img.height - side) // 2, (img.width + side) // 2, (img.height + side) // 2))
            img = img.resize((120, 120), Image.LANCZOS).quantize(64).convert("RGB")
            buf = io.BytesIO(); img.save(buf, "PNG")
            return base64.b64encode(buf.getvalue()).decode()
        except Exception:
            continue
    return None


def parse_lrc(lrc):
    """'[01:02.50] line' text -> [[62.5, 'line'], ...], in order"""
    out = []
    for raw in (lrc or "").splitlines():
        stamps = re.findall(r"\[(\d+):(\d+(?:\.\d+)?)\]", raw)
        words = re.sub(r"\[[^\]]*\]", "", raw).strip()
        out += [[int(m) * 60 + float(s), words] for m, s in stamps]
    return sorted(out)


def lyrics(p):
    title, artist = cleaned(p["title"]), p["artist"].split(",")[0]
    if not artist:
        return []   # a title alone finds somebody else's song
    queries = [{"track_name": title, "artist_name": artist, "album_name": p["album"], "duration": round(p["length"])},
               {"track_name": title, "artist_name": artist}, {"q": f"{artist} {title}"}]
    for i, q in enumerate(queries):
        try:
            url = "https://lrclib.net/api/" + ("get?" if i == 0 else "search?") + urllib.parse.urlencode(q)
            data = json.loads(get(url))
            for hit in [data] if i == 0 else data:
                if hit.get("syncedLyrics") and (not p["length"] or abs((hit.get("duration") or 0) - p["length"]) <= 3):
                    return parse_lrc(hit["syncedLyrics"])
        except Exception:
            continue
    return []


# --- the stream -----------------------------------------------------------------------------------------------------
class Stream:
    """the SSH connection to the sink and cava, both only while there's music"""

    def __init__(self):
        self.ssh = self.cava = None
        self.lock = threading.Lock()

    def send(self, msg):
        with self.lock:
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

    def levels(self):
        """the next spectrum frame from cava (which paces the loop), or zeros"""
        if self.cava is None and shutil.which("cava"):
            config = (f"[general]\nbars = {BARS}\nframerate = {FPS}\nsleep_timer = 0\n[input]\nmethod = pipewire\n"
                      "[output]\nmethod = raw\nraw_target = /dev/stdout\ndata_format = ascii\nascii_max_range = 64\n"
                      "bar_delimiter = 59\nframe_delimiter = 10\n[smoothing]\nnoise_reduction = 40\n")
            self.cava = subprocess.Popen(["cava", "-p", "/dev/stdin"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.DEVNULL, text=True)
            self.cava.stdin.write(config); self.cava.stdin.close()
        line = self.cava.stdout.readline() if self.cava else ""
        if not line:   # no cava, or it died: keep time ourselves
            self.cava = None; time.sleep(1 / FPS)
            return [0] * BARS
        return [int(v) for v in line.strip().strip(";").split(";") if v.isdigit()]

    def close(self):
        for proc in (self.ssh, self.cava):
            if proc and proc.poll() is None:
                proc.terminate()
        self.ssh = self.cava = None


def run():
    stream, song, since, last_check, idle_since, pos_at = Stream(), None, None, 0, None, (0.0, 0.0)
    p = None
    while True:
        if time.time() - last_check >= 1:   # the song and where it's at, once a second
            last_check = time.time()
            p = pick(players())
            if p:
                pos_at = (position(p), time.time())
                ident = (p["title"], p["artist"], p["album"], round(p["length"]))
                if ident != song:
                    song = ident
                    track = {"t": "track", "title": cleaned(p["title"]) or p["title"], "artist": p["artist"],
                             "album": p["album"], "player": player_name(p), "length": p["length"], "art": None, "lyrics": []}
                    stream.send(track)

                    def extras(track=track, p=p, ident=ident):   # art and lyrics take a second or two: not in the loop
                        p, hit = identify(p)
                        track = dict(track, artist=p["artist"], album=p["album"], art=cover(p, hit), lyrics=lyrics(p))
                        if song == ident:
                            stream.send(track)
                    threading.Thread(target=extras, daemon=True).start()
            playing = bool(p and p["status"] == "Playing")
            idle_since = None if playing else (idle_since or time.time())
            if idle_since and time.time() - idle_since > IDLE:   # the music's stopped: hang up and wait quietly
                stream.close(); song = None
                while not (p := pick(players())) or p["status"] != "Playing":
                    time.sleep(2)
                idle_since, last_check = None, 0
                continue
        playing = bool(p and p["status"] == "Playing")
        pos = pos_at[0] + (time.time() - pos_at[1] if playing else 0)
        if not stream.send({"t": "frame", "levels": stream.levels(), "pos": round(pos, 2), "playing": playing}):
            song = None; time.sleep(5)   # the Pi's away: try again in a bit, and resend the song


def check():
    found = [{"bus": "org.mpris.MediaPlayer2.vivaldi.instance1", "status": "Playing", "title": "Song | YouTube Music",
              "artist": "", "album": "", "length": 157.0, "url": "", "art": ""},
             {"bus": "org.mpris.MediaPlayer2.plasma-browser-integration", "status": "Playing", "title": "Song",
              "artist": "Good Kid", "album": "Song", "length": 157.0, "url": "https://music.youtube.com/", "art": ""},
             {"bus": "org.mpris.MediaPlayer2.vlc", "status": "Paused", "title": "Other", "artist": "X", "album": "",
              "length": 1, "url": "", "art": ""},
             {"bus": "org.mpris.MediaPlayer2.mpv", "status": "Stopped", "title": "Old", "artist": "Y", "album": "",
              "length": 1, "url": "", "art": ""}]
    assert pick(found)["bus"].endswith("plasma-browser-integration"), "the clean copy of a browser song wins"
    assert pick(found[2:])["bus"].endswith("vlc") and pick(found[3:]) is None, "paused beats stopped, stopped is nothing"
    assert player_name(found[1]) == "YouTube Music" and player_name(found[2]) == "Vlc"
    assert cleaned("Song (Official Video) | YouTube Music") == "Song" and cleaned("Song (feat. Someone)") == "Song"
    assert cleaned("Second Rate Town (Acoustic)") == "Second Rate Town (Acoustic)", "real parts of a title stay"
    assert parse_lrc("[00:10.50] first\n[01:02.00][01:30.00] chorus\nno stamp\n[00:00.00]") == \
        [[0.0, ""], [10.5, "first"], [62.0, "chorus"], [90.0, "chorus"]]
    assert video_id("https://music.youtube.com/watch?v=abc123&list=x") == "abc123" and video_id("https://x.com/") is None
    print("nowplaying: ok")


if __name__ == "__main__":
    if sys.argv[1:] == ["--check"]:
        check()
    elif sys.argv[1:] == ["--once"]:
        p = pick(players()); print(json.dumps(p and dict(p, player=player_name(p), position=position(p)), indent=1))
    elif not sys.argv[1:]:
        run()
    else:
        sys.exit(__doc__)
