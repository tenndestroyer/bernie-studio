"""Revision loop: re-render the shots the Director flagged (visual or script), using a fresh
seed each attempt and (optionally) the Director's improved prompt for that shot. Updates
work/progress.json. Runs on the GPU, so call it AFTER a render pass, not during one."""
import json, sys, pathlib, shutil, time
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import config, comfy, pipeline, qc

def _load(name):
    p = config.WORK / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

def revise(weak_shot_ids, use_directed_prompts=True, max_reroll=2):
    ep = _load("episode.json")
    directed = _load("episode_directed.json") if use_directed_prompts else None
    by_id = {s["id"]: s for s in ep["shots"]}
    if directed:
        for s in directed["shots"]:
            if s["id"] in weak_shot_ids:  # adopt improved prompt/motion for flagged shots
                by_id[s["id"]]["positive"] = s.get("positive", by_id[s["id"]]["positive"])
                by_id[s["id"]]["motion"]   = s.get("motion", by_id[s["id"]]["motion"])
    prog = pipeline.load_progress()
    comfy.start_server()
    for sid in weak_shot_ids:
        shot = by_id.get(sid)
        if not shot: continue
        rr = prog["shots"].get(sid, {}).get("reroll", 0) + 1
        salt = 100 + rr * 13      # new seed family each reroll
        print(f"[revise] {sid} reroll #{rr} ...")
        # clear old outputs
        for f in (config.SHOTS/f"{sid}.mp4", config.SHOTS/f"{sid}_key.png",
                  config.ENGINE/"input"/f"{sid}_key.png"):
            try: f.unlink()
            except FileNotFoundError: pass
        try:
            key = pipeline.render_keyframe(shot, salt=salt)
            nf  = pipeline.render_video(shot, key, salt=salt)
            ok, why = qc.check_clip(config.SHOTS/f"{sid}.mp4")
            prog["shots"].setdefault(sid, {}).update(
                status="done" if ok else "weak", frames=nf, reroll=rr, t=time.time())
            print(f"[revise] {sid} -> {'OK' if ok else why} ({nf} frames)")
        except Exception as e:
            prog["shots"].setdefault(sid, {}).update(status="failed", reroll=rr, err=str(e)[:160])
            print(f"[revise] {sid} FAIL: {e}")
        pipeline.save_progress(prog)
    print(f"revision done: {len(weak_shot_ids)} shots")

if __name__ == "__main__":
    vis = _load("visual_report.json")
    ids = [w["shot"] for w in (vis or {}).get("weak", [])]
    if ids: revise(ids)
    else: print("no flagged shots in visual_report.json")
