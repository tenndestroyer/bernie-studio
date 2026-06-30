"""Typed, backward-compatible wrappers over the existing JSON artifacts.

These are thin, defensive readers/writers over the SAME files the legacy pipeline already
uses — they do NOT change the on-disk shape, they just give the GUI and tests a typed,
crash-proof interface:

  * episode.json   (WORK/episode.json)        -> EpisodeState
  * progress.json  (WORK/progress.json)       -> RenderProgress
  * series_state.json (HOME/series_state.json)-> SeriesState

Design rules honored here:
  - Never raise on a missing/corrupt file: every .load() returns sensible empty defaults.
  - Don't mutate the file shape. RenderProgress mirrors pipeline.py exactly
    ({"started": float, "shots": {sid: {...}}}); SeriesState mirrors series.py
    ({"done": [...], "history": [...]}).
  - Honest about scope: this is bookkeeping, not validation. We trust the writers' schemas.
"""
import sys, json, pathlib

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# make `import config` work whether we're imported from bernie/ or run from core/
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import config


# ---------- helpers ----------
def _workdir(slot=""):
    """Resolve the work dir for a slot the same way config does (env SLOT drives the default)."""
    slot = (slot or "").strip()
    if ".." in slot or "/" in slot or "\\" in slot or ":" in slot:   # no path traversal
        slot = ""
    if not slot:
        return config.WORK
    return config.STORAGE / ("work_" + slot)


def _read_json(path, default):
    """Read JSON, returning a copy of `default` on any problem (missing / unreadable / bad JSON)."""
    try:
        p = pathlib.Path(path)
        if not p.exists():
            return json.loads(json.dumps(default))
        data = json.loads(p.read_text(encoding="utf-8"))
        return data
    except Exception:
        return json.loads(json.dumps(default))


def _write_json(path, data):
    """Write JSON, creating parent dirs; swallow errors (degrade gracefully, never crash a render)."""
    try:
        p = pathlib.Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return True
    except Exception:
        return False


# ---------- episode.json ----------
class EpisodeState:
    """Typed wrapper over WORK/episode.json (shot list + metadata).

    Shape on disk (written by showrunner/episode2): {"title": str, "episode": int,
    "fps": int, "shots": [ {id, positive, negative, motion, dialogue, ...}, ... ]}.
    """

    def __init__(self, data=None, path=None):
        self.data = data if isinstance(data, dict) else {}
        self.path = path

    @classmethod
    def load(cls, slot=""):
        path = _workdir(slot) / "episode.json"
        return cls(_read_json(path, {}), path)

    @property
    def shots(self):
        v = self.data.get("shots")
        return v if isinstance(v, list) else []

    @property
    def title(self):
        return str(self.data.get("title", "") or "")

    @property
    def name(self):
        # episode.json doesn't carry a 'name'; it comes from the run's EPISODE_NAME.
        # Prefer an explicit field if a writer ever adds one, else fall back to config.
        return str(self.data.get("name") or config.EPISODE_NAME or "")

    def get(self, key, default=None):
        return self.data.get(key, default)

    def save(self):
        if self.path is None:
            self.path = _workdir() / "episode.json"
        _write_json(self.path, self.data)
        return self


# ---------- progress.json ----------
class RenderProgress:
    """Typed wrapper over WORK/progress.json (per-shot render status).

    Shape on disk (written by pipeline.py): {"started": float, "shots": {sid: {
    "key": "done"|"failed"|"retryN", "status": "done"|"failed"|"retryN", ...}}}.
    """

    def __init__(self, data=None, path=None):
        self.data = data if isinstance(data, dict) else {}
        self.data.setdefault("shots", {})
        self.path = path

    @classmethod
    def load(cls, slot=""):
        path = _workdir(slot) / "progress.json"
        return cls(_read_json(path, {"shots": {}}), path)

    @property
    def shots(self):
        v = self.data.get("shots")
        return v if isinstance(v, dict) else {}

    @property
    def started(self):
        return self.data.get("started")

    def counts(self):
        """Tally per-shot state across the keyframe ('key') and video ('status') passes."""
        shots = self.shots
        key_done = sum(1 for s in shots.values()
                       if isinstance(s, dict) and s.get("key") == "done")
        vid_done = sum(1 for s in shots.values()
                       if isinstance(s, dict) and s.get("status") == "done")
        failed = sum(1 for s in shots.values()
                     if isinstance(s, dict) and (s.get("status") == "failed" or s.get("key") == "failed"))
        return dict(total_tracked=len(shots), key_done=key_done,
                    vid_done=vid_done, failed=failed)

    def frac(self, total):
        """Fraction of `total` shots whose video is done (0.0..1.0). Safe if total<=0."""
        try:
            total = int(total)
        except Exception:
            total = 0
        if total <= 0:
            return 0.0
        return max(0.0, min(1.0, self.counts()["vid_done"] / float(total)))

    def update(self, sid, **kw):
        """Merge **kw into the record for shot `sid` (creating it if absent). Returns self."""
        shots = self.data.setdefault("shots", {})
        rec = shots.setdefault(sid, {})
        if isinstance(rec, dict):
            rec.update(kw)
        else:
            shots[sid] = dict(kw)
        return self

    def save(self):
        if self.path is None:
            self.path = _workdir() / "progress.json"
        _write_json(self.path, self.data)
        return self


# ---------- series_state.json ----------
class SeriesState:
    """Typed wrapper over HOME/series_state.json (which episodes are finished).

    Shape on disk (written by series.py): {"done": [slug, ...], "history": [
    {slug, name, ok, rc, t}, ... ]}.
    """

    def __init__(self, data=None, path=None):
        self.data = data if isinstance(data, dict) else {}
        self.data.setdefault("done", [])
        self.data.setdefault("history", [])
        self.path = path

    @classmethod
    def load(cls):
        path = config.HOME / "series_state.json"
        return cls(_read_json(path, {"done": [], "history": []}), path)

    @property
    def done(self):
        v = self.data.get("done")
        return v if isinstance(v, list) else []

    @property
    def history(self):
        v = self.data.get("history")
        return v if isinstance(v, list) else []

    def is_done(self, slug):
        return slug in self.done

    def mark_done(self, slug, name=None, rc=0):
        """Append a history record and add `slug` to done (idempotent). Returns self."""
        import time
        hist = self.data.setdefault("history", [])
        ok = (rc == 0)
        hist.append(dict(slug=slug, name=name, ok=ok, rc=rc, t=time.time()))
        done = self.data.setdefault("done", [])
        if ok and slug not in done:
            done.append(slug)
        return self

    def save(self):
        if self.path is None:
            self.path = config.HOME / "series_state.json"
        _write_json(self.path, self.data)
        return self
