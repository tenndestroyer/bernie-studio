"""Shared fixtures for the Bernie Studio test suite.

Everything here is mock-based and hermetic: no GPU, no network, no real models.
The central trick is that ``bernie/config.py`` reads its paths and hardware tier
from the environment **at import time** and creates its storage directories on
import. So every test that needs config gets a *fresh* import of it pointed at a
throwaway temp dir, with hardware forced via ``BERNIE_VRAM_GB`` / ``BERNIE_TIER``
so nothing depends on the machine actually running the tests.
"""
import sys
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import importlib
import pathlib

import pytest

# Make the bernie/ package dir importable as top-level modules (config, qc, ...),
# exactly the way the pipeline imports them at runtime.
REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
BERNIE_DIR = REPO_ROOT / "bernie"
for _p in (str(BERNIE_DIR), str(REPO_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


# Env keys config (and friends) read on import. We scrub all of them so the host
# machine's real settings never leak into a test.
_BERNIE_ENV_KEYS = (
    "BERNIE_HOME", "BERNIE_STORAGE", "BERNIE_SLOT", "BERNIE_EP",
    "BERNIE_VRAM_GB", "BERNIE_TIER", "BERNIE_EVENTS", "BERNIE_PRESETS",
    "BERNIE_LORA", "BERNIE_INTERP", "BERNIE_POST_UPSCALE", "BERNIE_CONTINUITY",
)

# Modules that cache `import config` and must be reloaded after we swap config.
_CONFIG_DEPENDENT = ("config", "core.events")


def _reload(mod_name):
    """Import or reload a module by name, returning the (re)loaded module."""
    if mod_name in sys.modules:
        return importlib.reload(sys.modules[mod_name])
    return importlib.import_module(mod_name)


@pytest.fixture
def bernie_env(tmp_path, monkeypatch):
    """Point Bernie at an isolated temp HOME/STORAGE and a deterministic GPU tier.

    Returns the tmp storage root. Defaults to the 'balanced' laptop tier (12 GB)
    so config picks a stable, well-defined configuration regardless of the host.
    """
    home = tmp_path / "home"
    storage = tmp_path / "storage"
    home.mkdir(parents=True, exist_ok=True)
    storage.mkdir(parents=True, exist_ok=True)

    for k in _BERNIE_ENV_KEYS:
        monkeypatch.delenv(k, raising=False)

    monkeypatch.setenv("BERNIE_HOME", str(home))
    monkeypatch.setenv("BERNIE_STORAGE", str(storage))
    monkeypatch.setenv("BERNIE_EVENTS", "1")       # event bus on for the roundtrip test
    monkeypatch.setenv("BERNIE_VRAM_GB", "12")     # -> 'balanced' tier, deterministic
    monkeypatch.setenv("BERNIE_SLOT", "")          # pilot slot

    return storage


@pytest.fixture
def fresh_config(bernie_env):
    """A freshly-imported ``config`` module bound to the temp env.

    Also reloads modules that cache ``import config`` so they see the temp paths.
    """
    cfg = _reload("config")
    for dep in _CONFIG_DEPENDENT[1:]:
        try:
            _reload(dep)
        except Exception:
            # Module may not exist yet (owned by another agent) — that's fine.
            pass
    return cfg


@pytest.fixture
def reload_config_with():
    """Factory: set env vars, then return a freshly-imported config.

    Usage in a test::

        cfg = reload_config_with(BERNIE_VRAM_GB="24")
        assert cfg.TIER == "ultra"

    The monkeypatch teardown restores the environment after the test.
    """
    def _factory(monkeypatch, **env):
        for k, v in env.items():
            if v is None:
                monkeypatch.delenv(k, raising=False)
            else:
                monkeypatch.setenv(k, str(v))
        return _reload("config")
    return _factory
