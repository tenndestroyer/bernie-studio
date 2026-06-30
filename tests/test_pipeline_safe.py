"""Safe pipeline tests: QC clip checks, JSON repair, and a mocked comfy.run.

Nothing here touches a GPU or the network. The only external tool used is
ffmpeg, purely to synthesize tiny test clips; if it's absent those tests skip.
"""
import sys
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import importlib
import json
import shutil
import subprocess

import pytest


HAVE_FFMPEG = shutil.which("ffmpeg") is not None
HAVE_FFPROBE = shutil.which("ffprobe") is not None


def _try_pillow_numpy():
    try:
        import PIL  # noqa: F401
        import numpy  # noqa: F401
        return True
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# qc.check_clip
# --------------------------------------------------------------------------- #
def _lavfi_source(source, w, h, seconds):
    """Build a valid lavfi input spec.

    lavfi options attach to the filter name with '='  (e.g. 'testsrc2=s=...').
    A bare filter name ('testsrc2') needs the '=' inserted; a source that already
    carries options ('color=c=black') just gets ':'-joined extra options.
    """
    opts = f"s={w}x{h}:d={seconds}:r=24"
    sep = ":" if "=" in source else "="
    return f"{source}{sep}{opts}"


def _make_clip(path, source, seconds=2, w=1280, h=720, extra_vf=None, crf=None):
    """Render a tiny test clip with an ffmpeg lavfi source. Returns True on success."""
    vf = f"scale={w}:{h}"
    if extra_vf:
        vf = extra_vf + "," + vf
    cmd = [
        "ffmpeg", "-y", "-f", "lavfi", "-i", _lavfi_source(source, w, h, seconds),
        "-vf", vf, "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "ultrafast",
    ]
    if crf is not None:
        cmd += ["-crf", str(crf)]
    cmd.append(str(path))
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except Exception:
        return False
    return r.returncode == 0 and path.exists() and path.stat().st_size > 0


@pytest.mark.skipif(not (HAVE_FFMPEG and HAVE_FFPROBE),
                    reason="ffmpeg/ffprobe not available")
def test_check_clip_accepts_normal_clip(fresh_config, tmp_path):
    import qc
    importlib.reload(qc)
    clip = tmp_path / "normal.mp4"
    # testsrc2 = a moving, colorful, mid-luma pattern -> should pass all checks.
    if not _make_clip(clip, "testsrc2"):
        pytest.skip("ffmpeg could not synthesize the normal test clip")
    ok, why = qc.check_clip(clip, min_w=1000)
    assert ok, f"normal clip wrongly rejected: {why}"


@pytest.mark.skipif(not (HAVE_FFMPEG and HAVE_FFPROBE),
                    reason="ffmpeg/ffprobe not available")
def test_check_clip_rejects_black_clip(fresh_config, tmp_path):
    import qc
    importlib.reload(qc)
    if not _try_pillow_numpy():
        # Without PIL/numpy, qc can't analyze luma/motion and assumes ok by design.
        pytest.skip("PIL/numpy absent: qc skips luma/motion analysis (assumes ok)")
    clip = tmp_path / "dark.mp4"
    # A near-black source with faint grain: full-size (passes the resolution gate)
    # and big enough to clear qc's 50 KB tiny-file floor, so it actually reaches the
    # luma/motion analysis and is rejected for being too dark (not just "tiny").
    # (Pure-black H.264 compresses to a few KB and would trip the tiny-file check
    # first — a valid rejection, but it wouldn't exercise the luma path we want.)
    ok_made = _make_clip(clip, "color=c=0x080808", seconds=4,
                         extra_vf="noise=alls=8:allf=t", crf=18)
    if not ok_made:
        pytest.skip("ffmpeg could not synthesize the dark test clip")
    ok, why = qc.check_clip(clip, min_w=1000)
    assert not ok, "near-black clip should be rejected"
    assert ("dark" in why) or ("frozen" in why) or ("motion" in why), why


@pytest.mark.skipif(not (HAVE_FFMPEG and HAVE_FFPROBE),
                    reason="ffmpeg/ffprobe not available")
def test_check_clip_rejects_tiny_resolution(fresh_config, tmp_path):
    import qc
    importlib.reload(qc)
    clip = tmp_path / "tiny.mp4"
    # 320x180 moving source: real video, but below the min_w=1000 gate.
    if not _make_clip(clip, "testsrc2", w=320, h=180):
        pytest.skip("ffmpeg could not synthesize the tiny test clip")
    ok, why = qc.check_clip(clip, min_w=1000)
    assert not ok, "low-resolution clip should be rejected"
    assert "resolution" in why, why


def test_check_clip_rejects_missing_file(fresh_config, tmp_path):
    # No ffmpeg needed: a non-existent path is rejected up front.
    import qc
    importlib.reload(qc)
    ok, why = qc.check_clip(tmp_path / "does_not_exist.mp4")
    assert not ok
    assert "missing" in why or "tiny" in why


# --------------------------------------------------------------------------- #
# director.extract_json
# --------------------------------------------------------------------------- #
def _extract_json():
    import director
    importlib.reload(director)
    return director.extract_json


def test_extract_json_clean(fresh_config):
    extract_json = _extract_json()
    obj = extract_json('{"a": 1, "b": [1, 2, 3]}')
    assert obj == {"a": 1, "b": [1, 2, 3]}


def test_extract_json_in_code_fence(fresh_config):
    extract_json = _extract_json()
    text = "```json\n{\"scores\": {\"story\": 88}}\n```"
    obj = extract_json(text)
    assert obj["scores"]["story"] == 88


def test_extract_json_with_prose_prefix(fresh_config):
    extract_json = _extract_json()
    text = 'Sure! Here is the result:\n{"ok": true, "n": 7}\ntrailing chatter'
    obj = extract_json(text)
    assert obj == {"ok": True, "n": 7}


def test_extract_json_repairs_truncated(fresh_config):
    extract_json = _extract_json()
    # A response cut off mid-object/array (open string + open brackets).
    truncated = '{"notes": [{"shot": "s001", "issue": "too dark", "fix": "brighten the lant'
    obj = extract_json(truncated)
    assert isinstance(obj, dict)
    assert "notes" in obj
    assert obj["notes"][0]["shot"] == "s001"
    assert obj["notes"][0]["issue"] == "too dark"
    # the dangling key got its string closed during repair
    assert obj["notes"][0]["fix"].startswith("brighten")


def test_extract_json_repairs_trailing_comma(fresh_config):
    extract_json = _extract_json()
    truncated = '{"scores": {"story": 90, "humor": 80,'
    obj = extract_json(truncated)
    assert obj["scores"]["story"] == 90
    assert obj["scores"]["humor"] == 80


def test_extract_json_no_json_raises(fresh_config):
    extract_json = _extract_json()
    with pytest.raises(ValueError):
        extract_json("there is absolutely no json here")


# --------------------------------------------------------------------------- #
# comfy.run is mocked: nothing hits a GPU
# --------------------------------------------------------------------------- #
def test_comfy_run_is_mockable(fresh_config, monkeypatch, tmp_path):
    """Sanity-check the mock contract other pipeline code relies on.

    We never call a real ComfyUI server; we patch comfy.run to return fake
    output paths and assert callers would receive them.
    """
    import comfy
    importlib.reload(comfy)

    fake_out = tmp_path / "fake_0001.png"
    fake_out.write_bytes(b"not a real image")

    calls = {}

    def _fake_run(workflow_graph, timeout=600):
        calls["graph"] = workflow_graph
        calls["timeout"] = timeout
        return [fake_out]

    monkeypatch.setattr(comfy, "run", _fake_run)
    monkeypatch.setattr(comfy, "server_up", lambda: True)

    result = comfy.run({"1": {"class_type": "Noop"}}, timeout=5)
    assert result == [fake_out]
    assert calls["graph"]["1"]["class_type"] == "Noop"
    assert comfy.server_up() is True
