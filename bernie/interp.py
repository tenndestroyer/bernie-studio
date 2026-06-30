"""Optional motion/detail post-pass for Bernie Studio clips.

HONEST SCOPE — read this before expecting magic:
  This module runs *after* Wan i2v has produced an .mp4 shot. It can do two things, both
  with ffmpeg only (no extra model on the guaranteed path):
    1. interpolate() — ffmpeg `minterpolate` (motion-compensated frame interpolation) to a
       higher fps so the existing motion looks *smoother*.
    2. upscale()     — ffmpeg `scale` (lanczos) to a higher resolution so the frame looks
       *sharper*.
  Neither of these converts AI video into rigged/keyframed animation. The underlying motion
  is whatever Wan generated (a cute 3D-cartoon look, not Pixar with a rig). Interpolation
  smooths the *playback* of that motion and can hide a little judder; upscaling adds apparent
  detail but cannot invent real geometry. Both add render time (minterpolate especially —
  it is motion-estimation per frame and is the slowest filter here).

  Everything is OFF by default. It only runs when the caller opts in via
  config.POST_INTERP / config.POST_UPSCALE. On ANY ffmpeg failure the functions return False
  and leave the original clip untouched, so the pipeline can always fall back to the original.
"""
import sys
for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass

import os, shutil, subprocess, pathlib, tempfile

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


def _ffmpeg():
    """Return path to an ffmpeg executable, or None if not available."""
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    # also try a couple of common Windows install spots, best-effort
    for cand in (os.environ.get("FFMPEG", ""),):
        if cand and pathlib.Path(cand).exists():
            return cand
    return None


def _run_ffmpeg(args, timeout=3600):
    """Run ffmpeg with the given arg list (excluding the exe). Return True on rc==0."""
    exe = _ffmpeg()
    if not exe:
        return False
    cmd = [exe, "-y", "-hide_banner", "-loglevel", "error", *args]
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           timeout=timeout)
        return p.returncode == 0
    except Exception:
        return False


def _nontrivial(path):
    """True iff path exists and is a non-trivially-sized file (guards empty outputs)."""
    try:
        return path.exists() and path.stat().st_size > 1024
    except Exception:
        return False


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------
def enabled() -> bool:
    """True if any post-pass (interpolation or upscale) is configured on."""
    return bool(_cfg("POST_INTERP", False) or _cfg("POST_UPSCALE", False))


def interpolate(in_mp4, out_mp4, target_fps=None) -> bool:
    """Motion-compensated frame interpolation to target_fps (default config.POST_FPS).

    Uses ffmpeg `minterpolate` (mi_mode=mci). This smooths the *playback* of the motion
    Wan already generated; it does NOT add new acting or rig anything, and it is the
    slowest filter here. Returns True iff out_mp4 was produced & is non-trivial.
    """
    in_mp4, out_mp4 = pathlib.Path(in_mp4), pathlib.Path(out_mp4)
    if not _nontrivial(in_mp4) or _ffmpeg() is None:
        return False
    fps = target_fps if target_fps else _cfg("POST_FPS", _cfg("FPS", 24) * 2)
    try:
        fps = int(round(float(fps)))
    except Exception:
        fps = _cfg("FPS", 24) * 2
    if fps <= 0:
        fps = _cfg("FPS", 24) * 2
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    vf = (f"minterpolate=fps={fps}:mi_mode=mci:mc_mode=aobmc:"
          f"me_mode=bidir:vsbmc=1")
    ok = _run_ffmpeg(["-i", str(in_mp4), "-vf", vf,
                      "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
                      "-c:a", "copy", str(out_mp4)])
    # some clips have no audio stream; retry without trying to copy audio
    if not (ok and _nontrivial(out_mp4)):
        ok = _run_ffmpeg(["-i", str(in_mp4), "-vf", vf,
                          "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
                          "-an", str(out_mp4)])
    return bool(ok and _nontrivial(out_mp4))


def upscale(in_mp4, out_mp4, scale=2) -> bool:
    """Upscale the video by an integer factor using ffmpeg `scale` (lanczos).

    Lanczos is the GUARANTEED, reliable fallback. (A Real-ESRGAN ComfyUI path would give
    nicer detail but isn't trivially wired here, so we stick to ffmpeg for reliability.)
    Adds apparent sharpness; cannot invent real geometry. Returns True iff out_mp4 produced
    & non-trivial.
    """
    in_mp4, out_mp4 = pathlib.Path(in_mp4), pathlib.Path(out_mp4)
    if not _nontrivial(in_mp4) or _ffmpeg() is None:
        return False
    try:
        s = float(scale)
    except Exception:
        s = 2.0
    if s <= 1.0:
        s = 2.0
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    # iw*scale / ih*scale, rounded to even dims (yuv420p needs even W/H)
    vf = (f"scale=trunc(iw*{s}/2)*2:trunc(ih*{s}/2)*2:flags=lanczos")
    ok = _run_ffmpeg(["-i", str(in_mp4), "-vf", vf,
                      "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
                      "-c:a", "copy", str(out_mp4)])
    if not (ok and _nontrivial(out_mp4)):
        ok = _run_ffmpeg(["-i", str(in_mp4), "-vf", vf,
                          "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
                          "-an", str(out_mp4)])
    return bool(ok and _nontrivial(out_mp4))


def process(in_mp4, out_mp4) -> bool:
    """Apply the configured post-passes (interpolate and/or upscale) into out_mp4.

    Order: interpolate first (so upscale sharpens the already-smoothed frames). If only one
    is enabled, just that one runs. If nothing is enabled, returns False and writes nothing —
    the caller should keep using the original clip. On any ffmpeg failure, returns False and
    leaves the original (in_mp4) intact; out_mp4 is not guaranteed and should be ignored.
    """
    in_mp4, out_mp4 = pathlib.Path(in_mp4), pathlib.Path(out_mp4)
    do_interp = bool(_cfg("POST_INTERP", False))
    do_upscale = bool(_cfg("POST_UPSCALE", False))
    if not (do_interp or do_upscale):
        return False
    if not _nontrivial(in_mp4) or _ffmpeg() is None:
        return False

    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    tmp = None
    try:
        # stage 1: interpolation -> a temp file (or straight to out if it's the only pass)
        if do_interp and do_upscale:
            fd, tmpname = tempfile.mkstemp(suffix=".mp4", dir=str(out_mp4.parent))
            os.close(fd)
            tmp = pathlib.Path(tmpname)
            if not interpolate(in_mp4, tmp):
                return False
            stage_in = tmp
        elif do_interp:
            return interpolate(in_mp4, out_mp4)
        else:
            stage_in = in_mp4

        # stage 2: upscale
        ok = upscale(stage_in, out_mp4)
        return bool(ok and _nontrivial(out_mp4))
    finally:
        if tmp is not None:
            try: tmp.unlink()
            except Exception: pass


if __name__ == "__main__":
    print("interp: enabled=%s ffmpeg=%s POST_FPS=%s"
          % (enabled(), _ffmpeg(), _cfg("POST_FPS", None)))
