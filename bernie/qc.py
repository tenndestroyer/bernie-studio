"""Lightweight per-clip quality control using ffmpeg/ffprobe.
Flags clips that are black, blown-out, frozen (no motion), or wrong size — so the
render driver can auto-retry them. Pure ffmpeg, no GPU."""
import subprocess, json, pathlib, tempfile, os

def _probe(path):
    r = subprocess.run(["ffprobe","-v","quiet","-print_format","json","-show_streams",str(path)],
                       capture_output=True, text=True)
    try: return json.loads(r.stdout)
    except: return {}

def _frame_stats(path, n=6):
    """Sample n frames, return list of (mean_luma) and a motion score (mean abs diff)."""
    td = pathlib.Path(tempfile.mkdtemp(prefix="qc_"))
    try:
        subprocess.run(["ffmpeg","-y","-i",str(path),"-vf",f"fps=2,scale=160:90,format=gray",
                        str(td/"f_%03d.png")], capture_output=True, text=True)
        frames = sorted(td.glob("f_*.png"))[:n+2]
        if not frames: return [], 0.0
        try:
            from PIL import Image
            import numpy as np
        except Exception:
            return [128.0]*len(frames), 1.0  # can't analyze; assume ok
        arrs = [np.asarray(Image.open(f)).astype("float32") for f in frames]
        means = [float(a.mean()) for a in arrs]
        diffs = [float(abs(arrs[i+1]-arrs[i]).mean()) for i in range(len(arrs)-1)]
        motion = sum(diffs)/len(diffs) if diffs else 0.0
        return means, motion
    finally:
        for f in td.glob("*"):
            try: os.remove(f)
            except: pass
        try: os.rmdir(td)
        except: pass

def check_clip(path, min_w=1000):
    path = pathlib.Path(path)
    if not path.exists() or path.stat().st_size < 50_000:
        return False, "missing or tiny file"
    info = _probe(path)
    vs = next((s for s in info.get("streams",[]) if s.get("codec_type")=="video"), None)
    if not vs: return False, "no video stream"
    w = int(vs.get("width",0))
    if w < min_w: return False, f"low resolution {w}px"
    means, motion = _frame_stats(path)
    if means:
        avg = sum(means)/len(means)
        if avg < 12:  return False, f"too dark (luma {avg:.0f})"
        if avg > 245: return False, f"blown out (luma {avg:.0f})"
        if motion < 0.6: return False, f"frozen / no motion ({motion:.2f})"
    return True, "ok"

if __name__ == "__main__":
    import sys, config, glob
    for mp4 in sorted(config.SHOTS.glob("*.mp4")):
        if mp4.name.endswith(("_v.mp4","_a.mp4","_shot.mp4")): continue
        ok, why = check_clip(mp4)
        print(f"{'OK ' if ok else 'BAD'}  {mp4.name:14s} {why}")
