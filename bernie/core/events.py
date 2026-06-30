"""Append-only structured event bus the GUI tails.

Honest scope: this is a tiny JSONL event log, not a real message queue. It is
single-process-friendly and best-effort. Concurrent writers from different
processes can theoretically interleave or duplicate the 'i' sequence (we
compute it from the current line count, not an atomic counter), but for the
pipeline's one-writer / GUI-reader usage that is fine. Everything degrades
gracefully: emit never raises, reads of a missing file return [].
"""
import sys
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import json
import pathlib
import time

# Make 'import config' work from the bernie/ dir (we live in bernie/core/).
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import config  # noqa: E402


def _events_path(slot=""):
    s = (slot or "").strip()
    if ".." in s or "/" in s or "\\" in s or ":" in s:   # no path traversal
        s = ""
    return config.STORAGE / ("work_" + s if s else "work") / "events.jsonl"


def _count_lines(path):
    """Current line count of the file (== next sequence number). 0 if absent."""
    n = 0
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for _ in fh:
                n += 1
    except Exception:
        return 0
    return n


def emit(stage, msg, level="info", data=None, slot=None):
    if not getattr(config, "EVENTS_ON", False):
        return
    if slot is None:
        slot = getattr(config, "SLOT", "")
    try:
        path = _events_path(slot)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        # 1-based sequence: the first event is i=1 so the default
        # read_events(since=0) query (i > since) includes it.
        seq = _count_lines(path) + 1
        rec = {
            "i": seq,
            "t": time.time(),
            "stage": stage,
            "level": level,
            "msg": msg,
            "data": data or {},
        }
        line = json.dumps(rec, ensure_ascii=False)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        # Never raise from the event bus.
        return


def _load_all(slot=""):
    out = []
    try:
        path = _events_path(slot)
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        return []
    return out


def read_events(slot="", since=0, limit=400):
    """Events with i > since, newest-last, capped to the last 'limit'."""
    rows = [r for r in _load_all(slot) if isinstance(r.get("i"), (int, float)) and r["i"] > since]
    if limit and len(rows) > limit:
        rows = rows[-limit:]
    return rows


def tail(slot="", n=120):
    """Last n events (newest-last)."""
    rows = _load_all(slot)
    if n and len(rows) > n:
        rows = rows[-n:]
    return rows


def clear(slot=""):
    """Truncate the events file. Never raises."""
    try:
        path = _events_path(slot)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("")
    except Exception:
        return
