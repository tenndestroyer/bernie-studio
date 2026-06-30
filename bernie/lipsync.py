"""Optional, OPT-IN post-render lip-sync pass for Bernie Studio shots.

HONEST SCOPE — read this before expecting magic:
  Lip-sync (making a character's mouth match the spoken audio) is NOT something this
  module can do on its own. It needs a *separate dedicated model* that the user installs:
  Wav2Lip, LatentSync, or a Sonic-style ComfyUI custom node, plus GPU weights. This file
  is only the SCAFFOLDING + WIRING:
    - enabled()   — is the feature switched on (config.LIPSYNC, default OFF)?
    - available() — is a lip-sync backend actually installed (ComfyUI custom node, or a
                    CLI tool on PATH / in HOME)? Returns the backend name or None.
    - sync()      — if a backend is available, run it to lip-sync one clip to one audio
                    track; otherwise return False so the caller keeps the original clip.

  This is deliberately conservative: it is OFF by default, it never raises, and when it
  cannot find a backend it just declines (returns False) and — the first time — drops a
  short install note in the log dir. For a preschool AI cartoon, "talking-ish" mouths
  (which Wan already produces) are perfectly fine; real lip-sync is a nice-to-have, not a
  requirement. Do not expect Pixar-grade visemes — at best you get whatever the installed
  model produces, which for Wav2Lip is a low-res mouth-region overlay.
"""
import sys
for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass

import os, shutil, subprocess, pathlib

# make `import config` work from the bernie/ dir
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
try:
    import config
except Exception:                       # degrade gracefully if config can't import
    config = None


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _cfg(name, default):
    return getattr(config, name, default) if config is not None else default


def _nontrivial(path):
    """True iff path exists and is a non-trivially-sized file (guards empty outputs)."""
    try:
        path = pathlib.Path(path)
        return path.exists() and path.stat().st_size > 1024
    except Exception:
        return False


# names that identify a lip-sync ComfyUI custom node or CLI tool
_BACKEND_HINTS = ("wav2lip", "latentsync", "sonic")


def _scan_custom_nodes():
    """Look for a lip-sync custom node under config.ENGINE/custom_nodes. Return name|None."""
    engine = _cfg("ENGINE", None)
    if not engine:
        return None
    try:
        nodes_dir = pathlib.Path(engine) / "custom_nodes"
        if not nodes_dir.is_dir():
            return None
        for child in nodes_dir.iterdir():
            try:
                low = child.name.lower()
            except Exception:
                continue
            for hint in _BACKEND_HINTS:
                if hint in low:
                    return f"comfy:{hint}"
    except Exception:
        pass
    return None


def _scan_path_and_home():
    """Look for a wav2lip/latentsync CLI on PATH or under config.HOME. Return name|None."""
    # 1) on PATH (with and without common extensions, via shutil.which)
    for hint in ("wav2lip", "latentsync"):
        try:
            if shutil.which(hint):
                return f"cli:{hint}"
        except Exception:
            pass
    # 2) somewhere under HOME (a cloned repo / venv). Best-effort, shallow-ish walk.
    home = _cfg("HOME", None)
    if home:
        try:
            home = pathlib.Path(home)
            if home.is_dir():
                for root, dirs, files in os.walk(home):
                    # don't descend into huge/irrelevant trees forever; prune obvious noise
                    depth = pathlib.Path(root).relative_to(home).parts
                    if len(depth) > 4:
                        dirs[:] = []
                        continue
                    rl = pathlib.Path(root).name.lower()
                    for hint in ("wav2lip", "latentsync"):
                        if hint in rl:
                            return f"home:{hint}"
                        for fn in files:
                            fl = fn.lower()
                            if hint in fl and fl.endswith((".py", ".exe", ".bat", ".cmd", ".sh")):
                                return f"home:{hint}"
        except Exception:
            pass
    return None


_README_WRITTEN = False
_README_TEXT = """\
Bernie Studio — Lip-Sync (OPTIONAL, currently OFF or unavailable)
=================================================================

You turned lip-sync ON (BERNIE_LIPSYNC=1 / config.LIPSYNC), but no lip-sync backend was
found, so Bernie kept the original (un-synced) clips. THIS IS FINE. For a preschool AI
cartoon, the "talking-ish" mouth motion Wan already produces reads as talking to a young
viewer. Lip-sync is a nice-to-have, not a requirement.

If you DO want real lip-sync, you must install a separate model yourself (it needs GPU
weights and is not bundled). Bernie will auto-detect any of these:

  ComfyUI custom node (recommended — auto-detected under <ENGINE>/custom_nodes):
    - Wav2Lip   : https://github.com/ArtVentureX/comfyui-wav2lip  (or similar Wav2Lip node)
    - LatentSync: https://github.com/bytedance/LatentSync  (+ a ComfyUI wrapper node)
    - Sonic     : a Sonic / portrait-audio ComfyUI node (name contains "sonic")
    After cloning into ComfyUI/custom_nodes, download the model's weights per its README.

  Standalone CLI (auto-detected on PATH or under your BERNIE_HOME):
    - Wav2Lip   : https://github.com/Rudrabha/Wav2Lip   (clone, install reqs, get weights)
    - LatentSync: https://github.com/bytedance/LatentSync

Notes:
  - All of these need GPU weights downloaded separately (hundreds of MB to several GB).
  - Quality varies; Wav2Lip is low-res mouth-region only. None are Pixar-grade.
  - This is OFF by default. Delete this file; it is regenerated only when lip-sync is on
    but no backend is found.
"""


def _write_readme_once():
    """Write install guidance to LOGDIR/README_LIPSYNC.txt, at most once per process."""
    global _README_WRITTEN
    if _README_WRITTEN:
        return
    _README_WRITTEN = True
    logdir = _cfg("LOGDIR", None)
    if not logdir:
        return
    try:
        logdir = pathlib.Path(logdir)
        logdir.mkdir(parents=True, exist_ok=True)
        (logdir / "README_LIPSYNC.txt").write_text(_README_TEXT, encoding="utf-8")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------
def enabled() -> bool:
    """True if the user opted in to the lip-sync post-pass (config.LIPSYNC). Default OFF."""
    return bool(_cfg("LIPSYNC", False))


def available():
    """Detect an installed lip-sync backend; return its name (str) or None.

    Checks, in order:
      1. a ComfyUI lip-sync custom node under config.ENGINE/custom_nodes whose folder name
         contains 'wav2lip', 'latentsync', or 'sonic'  -> "comfy:<hint>"
      2. a 'wav2lip'/'latentsync' executable on PATH                     -> "cli:<hint>"
      3. a 'wav2lip'/'latentsync' repo/script under config.HOME          -> "home:<hint>"
    Returns None if nothing is found. Never raises. NOTE: detection only confirms the code
    is present — it does NOT verify model weights are downloaded; a backend can be found yet
    still fail at run time, in which case sync() returns False and the original clip is kept.
    """
    return _scan_custom_nodes() or _scan_path_and_home()


def sync(video_in, audio_in, video_out) -> bool:
    """Lip-sync video_in to audio_in, writing video_out. Return True iff it succeeded.

    Behavior:
      - If a backend is available(), invoke it (CLI backends are run directly; a ComfyUI
        node backend would be driven through the Comfy server, which is owned by another
        module, so here we attempt only the CLI/repo path and otherwise decline).
      - If NO backend is available, return False so the caller keeps the original clip, and
        — only the FIRST time lip-sync is enabled-but-unavailable — write concise install
        guidance to config.LOGDIR/README_LIPSYNC.txt.
    True is returned only when video_out was produced and is non-trivial. Never raises.

    HONEST: this wires up the *invocation*; it cannot itself perform lip-sync without an
    installed model. For a preschool cartoon, declining (keeping the original) is fine.
    """
    video_in = pathlib.Path(video_in)
    audio_in = pathlib.Path(audio_in)
    video_out = pathlib.Path(video_out)

    if not _nontrivial(video_in) or not _nontrivial(audio_in):
        return False

    backend = available()
    if not backend:
        # enabled but no backend -> leave install guidance once, then decline
        if enabled():
            _write_readme_once()
        return False

    try:
        video_out.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    # Only CLI / repo-script backends can be driven from here. ComfyUI-node backends need
    # the Comfy server graph (owned elsewhere), so we conservatively decline those for now.
    if not (backend.startswith("cli:") or backend.startswith("home:")):
        return False

    hint = backend.split(":", 1)[1]
    return _run_cli_backend(hint, video_in, audio_in, video_out)


def _resolve_cli(hint):
    """Find an invocable command list for a CLI/repo lip-sync backend. Return list|None."""
    # direct executable on PATH
    try:
        exe = shutil.which(hint)
    except Exception:
        exe = None
    if exe:
        return [exe]
    # a repo under HOME: prefer inference.py at the repo root
    home = _cfg("HOME", None)
    if home:
        try:
            home = pathlib.Path(home)
            if home.is_dir():
                for root, dirs, files in os.walk(home):
                    depth = pathlib.Path(root).relative_to(home).parts
                    if len(depth) > 4:
                        dirs[:] = []
                        continue
                    if hint in pathlib.Path(root).name.lower():
                        for cand in ("inference.py", "infer.py", "run.py", f"{hint}.py"):
                            p = pathlib.Path(root) / cand
                            if p.exists():
                                py = _cfg("PY_EMBED", None)
                                py = str(py) if (py and pathlib.Path(py).exists()) else sys.executable
                                return [py, str(p)]
        except Exception:
            pass
    return None


def _run_cli_backend(hint, video_in, audio_in, video_out) -> bool:
    """Best-effort run of a Wav2Lip/LatentSync-style CLI. Return True iff output produced.

    Uses Wav2Lip's well-known flag names (--face/--audio/--outfile), which LatentSync's
    common wrappers also accept variants of. If the tool uses different flags or its weights
    are missing, it will fail and we return False (caller keeps the original). Never raises.
    """
    cmd = _resolve_cli(hint)
    if not cmd:
        return False
    full = [*cmd,
            "--face", str(video_in),
            "--audio", str(audio_in),
            "--outfile", str(video_out)]
    try:
        p = subprocess.run(full, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           timeout=3600)
        if p.returncode == 0 and _nontrivial(video_out):
            return True
    except Exception:
        pass
    return False


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    import argparse
    ap = argparse.ArgumentParser(
        description="Optional lip-sync pass (OFF by default; needs an installed backend).")
    ap.add_argument("--video", required=True, help="input video (.mp4)")
    ap.add_argument("--audio", required=True, help="input audio (voice track)")
    ap.add_argument("--out",   required=True, help="output lip-synced video (.mp4)")
    args = ap.parse_args()

    print("lipsync: enabled=%s backend=%s" % (enabled(), available()))
    ok = sync(args.video, args.audio, args.out)
    print("lipsync: %s -> %s" % ("OK" if ok else "declined/failed (kept original)",
                                 args.out if ok else "(none)"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
