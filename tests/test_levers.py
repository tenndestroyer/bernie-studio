"""Tests for the opt-in "lever" features: offsite backup, voice presets/emotion,
the lip-sync hook, and the new config flags that gate them.

All mock-based and hermetic: no GPU, no network, no real models. Each test that
touches config uses the ``fresh_config`` fixture (from conftest.py) which points
Bernie at a throwaway temp HOME/STORAGE with a deterministic GPU tier.

Some of the modules exercised here (``lipsync``, and a ``voices()`` helper on
``presets``) are owned by sibling agents and may not exist yet in a given
checkout. Those tests degrade to ``pytest.skip`` instead of failing the suite,
so this file passes whether or not the sibling modules have landed. The backup,
voices-emotion, and config tests cover modules that are always present.
"""
import sys
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import importlib
import os
import pathlib

import pytest

# Make the bernie/ package dir importable as top-level modules (config, backup, ...),
# exactly the way the pipeline imports them at runtime. conftest also does this, but
# keep it here so the file is self-sufficient.
REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
BERNIE_DIR = REPO_ROOT / "bernie"
for _p in (str(BERNIE_DIR), str(REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _reload(mod_name):
    if mod_name in sys.modules:
        return importlib.reload(sys.modules[mod_name])
    return importlib.import_module(mod_name)


# --------------------------------------------------------------------------- #
# config: the new opt-in flags must exist (backward-compatible, OFF by default)
# --------------------------------------------------------------------------- #
def test_config_has_lever_flags(fresh_config):
    cfg = fresh_config
    for attr in ("BACKUP_DIR", "LIPSYNC", "DRIFT_CHECK", "VOICEPACK", "TTS_WORKERS"):
        assert hasattr(cfg, attr), f"config is missing the {attr!r} lever flag"
    # types / defaults: features are OFF by default
    assert cfg.BACKUP_DIR is None              # no BERNIE_BACKUP set -> disabled
    assert isinstance(cfg.LIPSYNC, bool) and cfg.LIPSYNC is False
    assert isinstance(cfg.DRIFT_CHECK, bool) and cfg.DRIFT_CHECK is False
    assert isinstance(cfg.VOICEPACK, str) and cfg.VOICEPACK            # non-empty pack name
    assert isinstance(cfg.TTS_WORKERS, int) and cfg.TTS_WORKERS >= 1


def test_config_backup_dir_resolves_when_set(reload_config_with, monkeypatch, tmp_path):
    bdir = tmp_path / "offsite"
    cfg = reload_config_with(monkeypatch,
                             BERNIE_HOME=str(tmp_path / "home"),
                             BERNIE_STORAGE=str(tmp_path / "storage"),
                             BERNIE_VRAM_GB="12",
                             BERNIE_BACKUP=str(bdir))
    assert cfg.BACKUP_DIR is not None
    assert pathlib.Path(cfg.BACKUP_DIR) == bdir.resolve()


# --------------------------------------------------------------------------- #
# backup: idempotent offsite copy
# --------------------------------------------------------------------------- #
def _load_backup_with_dir(reload_config_with, monkeypatch, tmp_path, backup_dir):
    """Reload config (with BERNIE_BACKUP set) then (re)import backup against it."""
    reload_config_with(monkeypatch,
                       BERNIE_HOME=str(tmp_path / "home"),
                       BERNIE_STORAGE=str(tmp_path / "storage"),
                       BERNIE_VRAM_GB="12",
                       BERNIE_BACKUP=str(backup_dir))
    return _reload("backup")


def test_backup_episode_copies_and_is_idempotent(reload_config_with, monkeypatch, tmp_path):
    backup_dir = tmp_path / "offsite"
    backup = _load_backup_with_dir(reload_config_with, monkeypatch, tmp_path, backup_dir)
    import config

    name = "Bernie_TestEp"
    src = config.OUT / f"{name}.mp4"
    src.write_bytes(b"fake mp4 payload" * 64)
    src_size = src.stat().st_size

    # first copy
    dest = backup.backup_episode(name)
    assert dest is not None, "backup_episode should return the dest path"
    dest = pathlib.Path(dest)
    assert dest.exists()
    assert dest.parent == backup_dir.resolve() or dest.parent == backup_dir
    assert dest.stat().st_size == src_size

    # idempotent: second call no-ops (same dest, file unchanged on disk)
    mtime_before = dest.stat().st_mtime
    dest2 = backup.backup_episode(name)
    assert dest2 is not None and pathlib.Path(dest2) == dest
    assert dest.stat().st_size == src_size
    # the up-to-date skip path doesn't recopy, so mtime is preserved
    assert dest.stat().st_mtime == mtime_before


def test_backup_all_returns_copied(reload_config_with, monkeypatch, tmp_path):
    backup_dir = tmp_path / "offsite"
    backup = _load_backup_with_dir(reload_config_with, monkeypatch, tmp_path, backup_dir)
    import config

    src = config.OUT / "Bernie_AllEp.mp4"
    src.write_bytes(b"another fake episode" * 32)

    results = backup.backup_all()
    assert isinstance(results, list)
    assert len(results) >= 1
    names = {pathlib.Path(r).name for r in results}
    assert "Bernie_AllEp.mp4" in names
    for r in results:
        assert pathlib.Path(r).exists()


def test_backup_disabled_is_noop(fresh_config):
    """With no BERNIE_BACKUP (the default temp env), backup is OFF and never raises."""
    backup = _reload("backup")
    assert backup.target() is None
    assert backup.backup_episode("anything") is None
    assert backup.backup_all() == []


# --------------------------------------------------------------------------- #
# presets.voices(): a voice pack dict including a Bernie-ish key -> [voice,rate,pitch]
# --------------------------------------------------------------------------- #
def _bernie_ish_key(d):
    for k in d:
        if "bern" in str(k).lower():
            return k
    return None


def test_presets_voices_has_bernie_with_three_tuple(fresh_config):
    import presets
    importlib.reload(presets)
    if not hasattr(presets, "voices"):
        pytest.skip("presets.voices() not implemented yet (owned by a sibling agent)")

    d = presets.voices()
    assert isinstance(d, dict) and d, "voices() should return a non-empty dict"

    key = _bernie_ish_key(d)
    assert key is not None, f"expected a Bernie-ish key in {list(d)[:8]}"
    v = d[key]
    # voice is a (voice_name, rate, pitch) triple (tuple or list -> 3 elements)
    assert isinstance(v, (list, tuple)), f"voice for {key!r} should be a list/tuple, got {type(v)}"
    assert len(v) == 3, f"voice for {key!r} should have 3 elements, got {len(v)}"
    vname, rate, pitch = v
    assert isinstance(vname, str) and vname, "voice name should be a non-empty string"


# --------------------------------------------------------------------------- #
# voices emotion heuristic: emphasis changes (rate, pitch)
# --------------------------------------------------------------------------- #
def _emotion_helper(voices_mod):
    """Return a callable(line, rate, pitch) -> (spoken, rate, pitch).

    Prefers a public helper if the module exposes one; falls back to the
    internal ``_apply_emotion`` that the module is known to define.
    """
    for name in ("apply_emotion", "emotion", "_apply_emotion"):
        fn = getattr(voices_mod, name, None)
        if callable(fn):
            return fn
    return None


def test_voices_emotion_changes_rate_pitch(fresh_config):
    import voices
    importlib.reload(voices)
    helper = _emotion_helper(voices)
    if helper is None:
        pytest.skip("voices module exposes no emotion helper")

    base_rate, base_pitch = "+0%", "+0Hz"

    def rp(line):
        out = helper(line, base_rate, base_pitch)
        # helper returns (spoken, rate, pitch)
        assert isinstance(out, tuple) and len(out) == 3
        _spoken, r, p = out
        return (r, p)

    plain = rp("Hello there friend")

    # The module's documented heuristic keys off an emphasis marker. Try a couple
    # of forms so the test is robust to exactly how "excited" is detected: a
    # trailing bang, or an explicit [EXCITED] tag (the known-supported form).
    emphasized = None
    for line in ("Hello there friend!", "[EXCITED] Hello there friend"):
        cand = rp(line)
        if cand != plain:
            emphasized = cand
            break

    assert emphasized is not None, (
        "an emphasized line should yield a different (rate, pitch) than a plain one; "
        f"plain={plain}"
    )
    assert emphasized != plain


# --------------------------------------------------------------------------- #
# lipsync hook: enabled()/available()/sync() return correct types and never raise
# --------------------------------------------------------------------------- #
def _import_lipsync():
    try:
        mod = _reload("lipsync")
    except Exception:
        return None
    return mod


def test_lipsync_hook_contract(fresh_config, tmp_path):
    lipsync = _import_lipsync()
    if lipsync is None:
        pytest.skip("lipsync module not present (owned by a sibling agent)")

    # enabled() -> bool, must not raise. OFF by default (config.LIPSYNC False).
    assert hasattr(lipsync, "enabled"), "lipsync must expose enabled()"
    en = lipsync.enabled()
    assert isinstance(en, bool)
    if "BERNIE_LIPSYNC" not in os.environ:
        assert en is False  # OFF by default unless the user opted in

    # available() detects an installed backend; its contract is the backend NAME
    # (str) or None — not a bool. In a hermetic test env nothing is installed, so
    # it must be None. Either way it must be the documented type and never raise.
    assert hasattr(lipsync, "available"), "lipsync must expose available()"
    av = lipsync.available()
    assert av is None or isinstance(av, str)

    # sync() on bogus paths must degrade to a falsy result, never raise.
    assert hasattr(lipsync, "sync"), "lipsync must expose sync()"
    bogus_v = tmp_path / "no_such_video.mp4"
    bogus_a = tmp_path / "no_such_audio.mp3"
    out = tmp_path / "synced.mp4"
    result = lipsync.sync(bogus_v, bogus_a, out)
    assert not result, "sync() on a bogus path should return a falsy value (e.g. False)"
