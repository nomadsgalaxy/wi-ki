#!/usr/bin/env python3
"""sink: where the desktop's now-playing stream lands on the Pi. It's the forced command of the desktop's now-playing
key (see feed/README.md), so that key can do this and nothing else.

It reads one JSON message per line from stdin (a line longer than LINE_MAX is skipped as it's read, never held whole),
checks it, and writes it to FOLDER (RAM, so twenty frames a second don't wear the SD card), where the page reads it:
  {"t": "track", "title", "artist", "album", "player", "length", "art": base64 PNG or null, "lyrics": [[seconds, line]]}
      -> track.json, once per song (and again when its art or lyrics arrive)
  {"t": "frame", "levels": [0..64, ... up to 48 of them], "pos": seconds, "playing": bool}
      -> frame.json, about ten times a second
Anything else, or anything malformed, is dropped. When the stream ends, frame.json goes, so the page knows.
Standard library only: it starts on every connection, and on a Pi Zero Pillow alone takes seconds to load.
"""
import base64, binascii, json, math, os, struct, sys

FOLDER = "/dev/shm/kiosk-nowplaying"
LINE_MAX, ART_MAX, LYRICS_MAX = 600_000, 400_000, 1000
LEVELS_MAX = 48     # the bars the page has room for (feed/nowplaying.py sends 48)
ART_SIDE = 1024     # the biggest cover it takes, each way: a small PNG can still say it's enormous


def text(v, n=200):
    return v[:n] if isinstance(v, str) else ""


def number(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v < 1e6 else 0.0


def level(v):
    """one bar's level, 0 to 64, or None if it isn't a finite number (JSON lets Infinity and NaN through)"""
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return None
    return max(0, min(64, int(v)))


def cover(art):
    """the cover if it's a base64 PNG no bigger than ART_SIDE each way (read from its header, without Pillow), else None"""
    if not isinstance(art, str) or len(art) > ART_MAX:
        return None
    try:
        head = base64.b64decode(art[:44], validate=True)   # 33 bytes: the signature and the IHDR chunk
    except (binascii.Error, ValueError):
        return None
    if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
        return None
    w, h = struct.unpack(">II", head[16:24])
    return art if 0 < w <= ART_SIDE and 0 < h <= ART_SIDE else None


def clean(msg):
    """a message from the desktop -> (file name, what to write), or None to drop it"""
    if not isinstance(msg, dict):
        return None
    if msg.get("t") == "frame" and isinstance(msg.get("levels"), list):
        levels = [x for x in map(level, msg["levels"][:LEVELS_MAX]) if x is not None]
        return "frame.json", {"levels": levels, "pos": number(msg.get("pos")), "playing": msg.get("playing") is True}
    if msg.get("t") == "track":
        lyrics = msg.get("lyrics") if isinstance(msg.get("lyrics"), list) else []
        lyrics = [[number(l[0]), text(l[1])] for l in lyrics[:LYRICS_MAX] if isinstance(l, list) and len(l) == 2]
        return "track.json", {"title": text(msg.get("title")), "artist": text(msg.get("artist")),
                              "album": text(msg.get("album")), "player": text(msg.get("player"), 40),
                              "length": number(msg.get("length")), "lyrics": lyrics,
                              "art": cover(msg.get("art"))}
    return None


def write(folder, name, data):
    tmp = os.path.join(folder, name + ".tmp")
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.replace(tmp, os.path.join(folder, name))


def bounded(stream, limit=LINE_MAX):
    """the stream's lines, as bytes, no longer than limit: a longer one is read past in pieces and dropped"""
    while True:
        line = stream.readline(limit + 1)
        if not line:
            return
        if len(line) <= limit:
            yield line
            continue
        while line and not line.endswith(b"\n"):   # the rest of the too-long line, a piece at a time
            line = stream.readline(limit + 1)


def serve(lines, folder=FOLDER):
    os.makedirs(folder, exist_ok=True)
    try:
        for line in lines:
            if len(line) > LINE_MAX:
                continue
            try:
                out = clean(json.loads(line))
            except (ValueError, RecursionError):   # not JSON, or nested too deep to parse
                continue
            if out:
                write(folder, *out)
    finally:
        try:
            os.remove(os.path.join(folder, "frame.json"))
        except OSError:
            pass


def check():
    import io, tempfile
    with tempfile.TemporaryDirectory() as folder:
        _check(folder, io)
    print("nowplaying sink: ok")


def png(w, h):
    """a PNG's first 33 bytes saying it's w x h, base64: enough for cover() to judge"""
    ihdr = struct.pack(">II", w, h) + bytes([8, 2, 0, 0, 0])
    return base64.b64encode(b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + ihdr + b"\0\0\0\0").decode()


def _check(folder, io):
    seen = []
    lines = [json.dumps({"t": "track", "title": "Second Rate Town", "artist": "Good Kid", "length": 157.0,
                         "lyrics": [[1.5, "first"], ["bad"], [3, 4, 5]], "art": "x" * (ART_MAX + 1), "extra": 1}),
             "not json", json.dumps({"t": "rm", "path": "~"}), json.dumps([1, 2]), "x" * (LINE_MAX + 1),
             json.dumps({"t": "frame", "levels": [0, 99, -4, "a", 12.6], "pos": 12.5, "playing": True})]

    def feed():
        for line in lines:
            yield line
        seen.append(sorted(os.listdir(folder)))   # while still connected

    serve(feed(), folder)
    assert seen == [["frame.json", "track.json"]], seen
    track = json.load(open(os.path.join(folder, "track.json")))
    assert track["title"] == "Second Rate Town" and track["lyrics"] == [[1.5, "first"]] and track["art"] is None
    assert "extra" not in track and track["player"] == "", track
    assert os.listdir(folder) == ["track.json"], "the frame goes when the stream ends"
    assert clean({"t": "frame", "levels": [0, 99, -4, "a", 12.6], "pos": True, "playing": 1}) == \
        ("frame.json", {"levels": [0, 64, 0, 12], "pos": 0.0, "playing": False})
    # odd containers, non-finite numbers, too many bars, big covers
    for lyrics in (1, {"a": 1}, "words", None, True):
        assert clean({"t": "track", "lyrics": lyrics})[1]["lyrics"] == [], f"lyrics of {lyrics!r} are none, not a crash"
    weird = json.loads('{"t": "frame", "levels": [Infinity, -Infinity, NaN, 1e400, 30, true], "pos": Infinity}')
    assert clean(weird) == ("frame.json", {"levels": [30], "pos": 0.0, "playing": False}), clean(weird)
    assert len(clean({"t": "frame", "levels": [10] * 500})[1]["levels"]) == LEVELS_MAX == 48, "no more bars than fit"
    assert cover(png(120, 120)) and cover(png(1024, 1024)), "a real cover is kept"
    for bad in (png(1025, 10), png(10, 100_000), png(0, 10), "not base64!", base64.b64encode(b"GIF89a" + b"\0" * 40).decode(), 7):
        assert cover(bad) is None, f"{bad!r:.30} is no cover"
    # a line too long is read past in pieces, never whole, and the lines either side of it still arrive
    stream = io.BytesIO(b'{"t": "frame", "levels": [1]}\n' + b"x" * 5000 + b'\n{"t": "frame", "levels": [2]}\n')
    read = []
    real = stream.readline
    stream.readline = lambda n=-1: read.append(n) or real(n)
    assert [json.loads(l)["levels"] for l in bounded(stream, 100)] == [[1], [2]]
    assert all(0 < n <= 101 for n in read), "every read is bounded"
    serve(iter([json.dumps({"t": "track", "lyrics": 1}).encode(), b"[" * 100_000]), folder)   # neither stops the stream


if __name__ == "__main__":
    serve(bounded(sys.stdin.buffer))
