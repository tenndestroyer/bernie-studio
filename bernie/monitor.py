"""Print render progress + ETA from work/progress.json. Used by the monitoring loop."""
import json, sys, pathlib, time
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import config

def main():
    ep = json.loads((config.WORK / "episode.json").read_text(encoding="utf-8"))
    total = len(ep["shots"])
    p = config.WORK / "progress.json"
    if not p.exists():
        print("no progress yet (render not started)"); return
    prog = json.loads(p.read_text())
    shots = prog.get("shots", {})
    done = [s for s,v in shots.items() if v.get("status")=="done"]
    failed = [s for s,v in shots.items() if v.get("status")=="failed"]
    rendering = [s for s,v in shots.items() if v.get("status")=="rendering"]
    secs = [v["secs"] for v in shots.values() if v.get("status")=="done" and "secs" in v]
    avg = sum(secs)/len(secs) if secs else 0
    remaining = total - len(done)
    eta_min = remaining*avg/60 if avg else 0
    print(f"shots done: {len(done)}/{total}  | failed: {len(failed)} {failed} | in-progress: {rendering}")
    if avg: print(f"avg/shot: {avg:.0f}s  | est remaining: {eta_min:.0f} min ({remaining} shots)")
    # check final
    final = config.OUT / "Bernie_Ep1.mp4"
    fnm = config.OUT / "Bernie_Ep1_nomusic.mp4"
    for f in (final, fnm):
        if f.exists():
            print(f"OUTPUT: {f.name}  {f.stat().st_size/1e6:.1f} MB")

if __name__ == "__main__":
    main()
