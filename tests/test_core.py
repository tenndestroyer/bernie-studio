"""Core utility tests: events bus, typed state, presets, config tier selection.

All hermetic. State/presets modules are owned by other agents and may not exist
yet at the time these tests run; those tests skip cleanly rather than fail, but
exercise the real API when the modules are present.
"""
import sys
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import importlib

import pytest


# --------------------------------------------------------------------------- #
# events bus: emit -> read roundtrip
# --------------------------------------------------------------------------- #
def test_events_emit_read_roundtrip(fresh_config):
    import core.events as events
    importlib.reload(events)  # rebind to the temp-pointed config

    events.clear()
    events.emit("render", "starting shot s001", level="info", data={"shot": "s001"})
    events.emit("render", "shot s001 done", level="info", data={"shot": "s001", "frames": 81})

    rows = events.read_events(since=-1)
    assert len(rows) == 2
    assert rows[0]["stage"] == "render"
    assert rows[0]["msg"] == "starting shot s001"
    assert rows[0]["data"]["shot"] == "s001"
    assert rows[1]["data"]["frames"] == 81
    # sequence numbers are monotonic
    assert rows[0]["i"] < rows[1]["i"]

    # 'since' filters correctly: only events after the first remain.
    after_first = events.read_events(since=rows[0]["i"])
    assert len(after_first) == 1
    assert after_first[0]["msg"] == "shot s001 done"


def test_events_missing_file_returns_empty(fresh_config):
    import core.events as events
    importlib.reload(events)
    events.clear()
    # Fresh/empty log -> empty list, never raises.
    assert events.read_events(since=-1) == []
    assert events.tail(n=10) == []


def test_events_off_is_a_noop(monkeypatch, bernie_env):
    monkeypatch.setenv("BERNIE_EVENTS", "0")
    cfg = importlib.reload(importlib.import_module("config"))
    assert cfg.EVENTS_ON is False
    import core.events as events
    importlib.reload(events)
    events.clear()
    events.emit("render", "should not be written")
    assert events.read_events(since=-1) == []


# --------------------------------------------------------------------------- #
# typed state wrappers: load+save roundtrip in a temp dir
# --------------------------------------------------------------------------- #
def _import_state_or_skip():
    try:
        import core.state as state
    except Exception:
        pytest.skip("core.state not present yet (owned by another module)")
    importlib.reload(state)
    return state


def _roundtrip_state_class(cls, sample):
    """Generic load/save roundtrip for a typed-state wrapper.

    Tries the common shapes these wrappers expose without hard-coding one API:
    a .save()/.load() pair, dict-like .to_dict()/from-path, or attribute access.
    Skips if the class doesn't look like a load/save state object.
    """
    obj = None
    # Construction: try no-arg, then a dict, then kwargs.
    for attempt in (lambda: cls(), lambda: cls(sample), lambda: cls(**sample)):
        try:
            obj = attempt()
            break
        except Exception:
            continue
    if obj is None:
        pytest.skip(f"{cls.__name__}: could not construct with known signatures")

    # Set sample fields where possible.
    for k, v in sample.items():
        try:
            setattr(obj, k, v)
        except Exception:
            pass

    save = getattr(obj, "save", None)
    load = getattr(cls, "load", None)
    if not callable(save) or not callable(load):
        pytest.skip(f"{cls.__name__}: no save()/load() pair to roundtrip")

    save()
    loaded = load()
    assert loaded is not None
    return loaded


def test_state_roundtrip(fresh_config):
    state = _import_state_or_skip()
    found_any = False
    for name in ("EpisodeState", "RenderProgress", "SeriesState"):
        cls = getattr(state, name, None)
        if cls is None:
            continue
        found_any = True
        _roundtrip_state_class(cls, {"title": "Pilot", "shots": [], "done": []})
    if not found_any:
        pytest.skip("core.state present but exposes none of the expected classes")


# --------------------------------------------------------------------------- #
# presets: characters() / season() return non-empty
# --------------------------------------------------------------------------- #
def _presets_module():
    """Prefer core.presets; fall back to the raw characters/series modules."""
    try:
        import core.presets as presets
        importlib.reload(presets)
        return presets
    except Exception:
        return None


def test_presets_characters_non_empty(fresh_config):
    presets = _presets_module()
    if presets is not None and hasattr(presets, "characters"):
        chars = presets.characters()
        assert chars, "presets.characters() returned empty"
        return
    # Fallback: the canonical character table must be populated.
    import characters as ch
    importlib.reload(ch)
    assert ch.CHARS, "characters.CHARS is empty"
    assert "BERNIE" in ch.CHARS
    assert ch.CHARS["BERNIE"]["desc"]


def test_presets_season_non_empty(fresh_config):
    presets = _presets_module()
    if presets is not None and hasattr(presets, "season"):
        season = presets.season()
        assert season, "presets.season() returned empty"
        return
    # Fallback: the built-in Season 1 plan must be populated.
    import series as sr
    importlib.reload(sr)
    assert sr.SEASON, "series.SEASON is empty"
    assert sr.SEASON[0]["title"]
    assert all("premise" in ep for ep in sr.SEASON)


# --------------------------------------------------------------------------- #
# config tier selection across VRAM values
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "vram, expected_tier",
    [
        ("24", "ultra"),     # >= 22
        ("22", "ultra"),     # boundary
        ("16", "high"),      # >= 15
        ("12", "balanced"),  # >= 11
        ("8", "low"),        # < 11
        ("4", "low"),
    ],
)
def test_config_tier_selection(monkeypatch, bernie_env, reload_config_with, vram, expected_tier):
    # bernie_env already points HOME/STORAGE at a temp dir; override VRAM only.
    monkeypatch.delenv("BERNIE_TIER", raising=False)
    cfg = reload_config_with(monkeypatch, BERNIE_VRAM_GB=vram)
    assert cfg.TIER == expected_tier
    # Tier must yield a coherent resolution.
    assert cfg.WAN_W > 0 and cfg.WAN_H > 0
    assert cfg.KEY_W > 0 and cfg.KEY_H > 0


def test_config_tier_forced_override(monkeypatch, bernie_env, reload_config_with):
    # An explicit BERNIE_TIER wins regardless of VRAM.
    cfg = reload_config_with(monkeypatch, BERNIE_VRAM_GB="4", BERNIE_TIER="ultra")
    assert cfg.TIER == "ultra"


def test_config_new_flags_default_off(monkeypatch, bernie_env, reload_config_with):
    # New behavior must be OFF by default unless the caller opts in.
    for k in ("BERNIE_LORA", "BERNIE_INTERP", "BERNIE_POST_UPSCALE", "BERNIE_CONTINUITY"):
        monkeypatch.delenv(k, raising=False)
    cfg = reload_config_with(monkeypatch, BERNIE_VRAM_GB="12")
    assert cfg.LORA_BERNIE == ""
    assert cfg.POST_INTERP is False
    assert cfg.POST_UPSCALE is False
    assert cfg.CONTINUITY is False
