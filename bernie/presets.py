"""Dependency-free preset system: a new show is config, not code edits.

The canonical cast/locations/style live in bernie/characters.py and the season plan in
bernie/series.py. This module lets a user OVERRIDE them with plain JSON (or YAML, if PyYAML
happens to be installed) so they can ship a different show without touching any Python.

Default behavior is unchanged: if no config file is present, every function falls back to the
real values imported from characters.py / series.py. Point the env var BERNIE_PRESETS at your own
folder (config.PRESETS_DIR) to load custom configs/characters/<name>.json + configs/series/*.json.

Honest limits: this only swaps the DATA (descriptions, voices, locations, episode list). It does
not change the renderer, the 22-agent writers' room, or the look of the AI video — that's still a
cute 3D cartoon, not rigged Pixar. Nothing here ever raises on a missing/bad file; it degrades to
the built-in Bernie defaults.
"""
import sys, json, pathlib

for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass

# make 'import config' work from the bernie/ dir
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

try:
    import config
except Exception:
    config = None


def _presets_dir():
    """The active presets folder (config.PRESETS_DIR / BERNIE_PRESETS), or the repo's configs/."""
    if config is not None:
        d = getattr(config, "PRESETS_DIR", None)
        if d:
            return pathlib.Path(d)
    # fall back to <repo>/configs relative to this file (bernie/ -> repo root)
    return pathlib.Path(__file__).resolve().parent.parent / "configs"


def load_json(path):
    """Load a JSON file -> dict|list, or None if it's absent or unparseable. Never raises."""
    try:
        p = pathlib.Path(path)
        if not p.is_file():
            return None
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def load_yaml(path):
    """Load a YAML file -> dict|list, ONLY if PyYAML is importable; else None. Never raises.

    YAML is purely optional — it is never required and the run path stays stdlib-only.
    """
    try:
        import yaml  # optional dependency, guarded
    except Exception:
        return None
    try:
        p = pathlib.Path(path)
        if not p.is_file():
            return None
        return yaml.safe_load(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_file(base):
    """Try base.json then base.yaml/.yml (YAML only if PyYAML present). Returns parsed data or None."""
    j = load_json(base.with_suffix(".json"))
    if j is not None:
        return j
    for ext in (".yaml", ".yml"):
        y = load_yaml(base.with_suffix(ext))
        if y is not None:
            return y
    return None


def _fallback_characters():
    """Build the canonical dict straight from characters.py — the always-available default."""
    try:
        import characters as ch
    except Exception:
        return {"style": "", "neg": "", "env_style": "", "chars": {}, "locations": {}}
    return {
        "style": getattr(ch, "STYLE", ""),
        "neg": getattr(ch, "NEG", ""),
        "env_style": getattr(ch, "ENV_STYLE", ""),
        # copy so callers can't mutate the module globals
        "chars": {k: dict(v) for k, v in getattr(ch, "CHARS", {}).items()},
        "locations": dict(getattr(ch, "LOCATIONS", {})),
    }


def _resolve_locations(data):
    """Expand the {ENV_STYLE} placeholder in location strings using the data's env_style."""
    env = data.get("env_style", "") or ""
    locs = data.get("locations", {}) or {}
    out = {}
    for k, v in locs.items():
        try:
            out[k] = v.replace("{ENV_STYLE}", env) if isinstance(v, str) else v
        except Exception:
            out[k] = v
    data["locations"] = out
    return data


def _normalize_voices(data):
    """JSON arrays become tuples (matching characters.py), and JSON null stays None."""
    for k, v in (data.get("chars") or {}).items():
        try:
            voice = v.get("voice")
            if isinstance(voice, list):
                v["voice"] = tuple(voice)
        except Exception:
            pass
    return data


def characters(path=None):
    """Return the cast/locations/style dict.

    Loads configs/characters/bernie.json from the active presets dir (or `path` if given),
    falling back to the live characters.py values when the file is missing or unreadable.
    Shape:  {"style": str, "neg": str, "env_style": str,
             "chars": {TOKEN: {"desc": str, "voice": tuple|None}},
             "locations": {KEY: str (with {ENV_STYLE} expanded)}}
    Never raises.
    """
    data = None
    try:
        if path is not None:
            data = _load_file(pathlib.Path(path).with_suffix("")) if pathlib.Path(path).suffix == "" \
                   else (load_json(path) or load_yaml(path))
        else:
            base = _presets_dir() / "characters" / "bernie"
            data = _load_file(base)
    except Exception:
        data = None

    if not isinstance(data, dict):
        return _fallback_characters()

    # fill any missing top-level keys from the fallback so callers always get the full shape
    fb = _fallback_characters()
    for key in ("style", "neg", "env_style", "chars", "locations"):
        data.setdefault(key, fb.get(key))
    try:
        data = _normalize_voices(data)
        data = _resolve_locations(data)
    except Exception:
        pass
    return data


def season(path=None):
    """Return the season plan as a list of episode dicts (n, slug, name, scenes, title, premise).

    Loads configs/series/season_1.json from the active presets dir (or `path` if given),
    falling back to series.SEASON when the file is missing or unreadable. Never raises.
    """
    data = None
    try:
        if path is not None:
            data = _load_file(pathlib.Path(path).with_suffix("")) if pathlib.Path(path).suffix == "" \
                   else (load_json(path) or load_yaml(path))
        else:
            base = _presets_dir() / "series" / "season_1"
            data = _load_file(base)
    except Exception:
        data = None

    if isinstance(data, list) and data:
        return data

    # fallback to the built-in season plan
    try:
        import series
        s = getattr(series, "SEASON", None)
        if isinstance(s, list) and s:
            return [dict(ep) for ep in s]
    except Exception:
        pass
    return []
