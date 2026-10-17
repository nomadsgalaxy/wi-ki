#!/usr/bin/env python3
"""sink: where the desktop's resource stream lands on the Pi. It's the forced command of the desktop's system key (see
feed/README.md), so that key can do this and nothing else.

It reads one JSON message per line from stdin, {"t": "system", ...} (feed/sysfeed.py), keeps only plain values (finite
numbers, short strings, short lists of numbers, one level of nested objects), and writes the latest to FILE in RAM.
When the stream ends the file goes, so the page knows. Standard library only, like the now playing sink.
"""
import json, math, os, sys

FILE = "/dev/shm/kiosk-system.json"
LINE_MAX = 20_000


def value(v, depth=0):
    """a JSON value -> a safe copy of it, or None to drop it"""
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, (int, float)):
        return v if math.isfinite(v) and abs(v) < 1e15 else None
    if isinstance(v, str):
        return v[:60]
    if isinstance(v, list) and len(v) <= 128:
        return [x for x in v if isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)]
    if isinstance(v, dict) and depth == 0 and len(v) <= 40:
        return {str(k)[:30]: value(x, 1) for k, x in v.items() if not isinstance(x, (dict, list))}
    return None


def clean(msg):
    if not isinstance(msg, dict) or msg.get("t") != "system" or len(msg) > 60:
        return None
    return {str(k)[:30]: value(v) for k, v in msg.items() if k != "t"}


def serve(lines, path=FILE):
    try:
        for line in lines:
            if len(line) > LINE_MAX:
                continue
            try:
                out = clean(json.loads(line))
            except ValueError:
                continue
            if out:
                with open(path + ".tmp", "w") as f:
                    json.dump(out, f)
                os.replace(path + ".tmp", path)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def check():
    import tempfile
    path, seen = os.path.join(tempfile.mkdtemp(), "system.json"), []
    lines = [json.dumps({"t": "system", "cpu": 12.5, "host": "x" * 99, "threads": [1, "a", True, 2.5],
                         "gpu": {"util": 4, "nested": {"no": 1}}, "bad": float("1e300")}),
             "nope", json.dumps({"t": "other", "cpu": 1}), "x" * (LINE_MAX + 1)]

    def feed():
        yield from lines
        seen.append(json.load(open(path)))

    serve(feed(), path)
    assert seen == [{"cpu": 12.5, "host": "x" * 60, "threads": [1, 2.5], "gpu": {"util": 4}, "bad": None}], seen
    assert not os.path.exists(path), "the file goes when the stream ends"
    assert clean({"t": "system", "x": float("nan")}) == {"x": None} and clean([1]) is None
    print("system sink: ok")


if __name__ == "__main__":
    serve(sys.stdin)
