"""Render driver: for each shot -> Flux keyframe (+LoRA) -> Wan image-to-video -> mp4.
Resumable (skips finished shots), retries on failure, writes work/progress.json for the monitor."""
import json, sys, pathlib, shutil, time, subprocess, zlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import config, comfy, workflows, qc

# optional helpers (never block the render if absent)
try:
    from core import events
except Exception:
    events = None
try:
    import interp
except Exception:
    interp = None

def _emit(stage, msg, level="info", data=None):
    try:
        if events:
            events.emit(stage, msg, level, data)
    except Exception:
        pass

# Character LoRA: activated by BERNIE_LORA / config.LORA_BERNIE once trained (see lora_train.py).
LORA = config.LORA_BERNIE or None
if LORA and not (config.LORA_OUT / LORA).exists():
    print(f"[pipeline] LoRA '{LORA}' not found in {config.LORA_OUT}; rendering without it.")
    LORA = None
elif LORA:
    print(f"[pipeline] character LoRA active: {LORA}")

def seed_for(sid, salt=0):
    return (zlib.crc32(sid.encode()) + salt*7919) % (2**31)

def frames_to_mp4(frame_paths, out_mp4):
    seqdir = config.SHOTS / "_seq"
    if seqdir.exists(): shutil.rmtree(seqdir)
    seqdir.mkdir(parents=True)
    # MOVE frames (not copy) so the raw PNG dump doesn't accumulate on disk
    for i, p in enumerate(sorted(frame_paths, key=lambda x: x.name)):
        try: shutil.move(str(p), str(seqdir / f"{i:05d}.png"))
        except Exception: shutil.copy(str(p), str(seqdir / f"{i:05d}.png"))
    subprocess.run(["ffmpeg","-y","-framerate",str(config.FPS),"-i",str(seqdir/"%05d.png"),
                    "-c:v","libx264","-pix_fmt","yuv420p","-crf","16",str(out_mp4)],
                   capture_output=True, text=True, check=True)
    shutil.rmtree(seqdir, ignore_errors=True)   # frames consumed -> gone

def render_keyframe(shot, salt=0):
    sid = shot["id"]
    prefix = f"key_{sid}"
    wf = workflows.flux_keyframe(shot["positive"], shot["negative"], seed_for(sid, salt),
                                 prefix, lora=LORA)
    imgs = comfy.run(wf, timeout=600)
    if not imgs: raise RuntimeError("no keyframe produced")
    key = imgs[-1]
    dst = config.ENGINE / "input" / f"{sid}_key.png"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(key, dst)
    shutil.copy(key, config.SHOTS / f"{sid}_key.png")   # archive
    return f"{sid}_key.png"

# Push Wan toward a CUTE STYLIZED 3D look (dimensional, not flat 2D, not realistic).
WAN_3D_BOOST = ("3D rendered CGI animation, cute stylized cartoon character design, big expressive eyes, "
    "rounded adorable proportions, soft volumetric lighting, dimensional rounded forms, soft global "
    "illumination, gentle depth of field, smooth cinematic motion, preschool cartoon, stable consistent "
    "character")
WAN_NEG_BOOST = ("2D, flat, flat shading, hand-drawn, drawing, sketch, anime, line art, cel shaded, "
    "comic, paper cutout, realistic, photorealistic, real animal, detailed realistic fur, jitter, "
    "flicker, strobe, washed out, faded, overexposed, morphing, warping, deformed, melting, blurry")

def render_video(shot, key_name, salt=0):
    sid = shot["id"]
    talk = ", characters talking, mouths moving naturally" if shot["dialogue"] else ""
    motion = f"{shot['positive']}. {WAN_3D_BOOST}. {shot['motion']}{talk}"
    neg = shot["negative"] + ", " + WAN_NEG_BOOST
    wf = workflows.wan_i2v(motion, neg, key_name, seed_for(sid, salt+1), f"vid_{sid}")
    frames = comfy.run(wf, timeout=3600)
    if len(frames) < 8: raise RuntimeError(f"too few frames ({len(frames)})")
    out_mp4 = config.SHOTS / f"{sid}.mp4"
    frames_to_mp4(frames, out_mp4)
    ok, why = qc.check_clip(out_mp4)
    if not ok:
        _emit("qc", f"{sid} QC rejected: {why}", "warn", {"sid": sid, "why": why})
        raise RuntimeError(f"QC rejected clip: {why}")
    # optional post-pass: smoother motion (interp) / sharper detail (upscale) — off by default
    if interp is not None and interp.enabled():
        try:
            tmp = out_mp4.with_suffix(".post.mp4")
            if interp.process(out_mp4, tmp) and tmp.exists() and tmp.stat().st_size > 1000:
                tmp.replace(out_mp4)
        except Exception as e:
            print(f"[pipeline] interp post-pass skipped for {sid}: {e}")
    return len(frames)

def load_progress():
    p = config.WORK / "progress.json"
    return json.loads(p.read_text()) if p.exists() else {}

def save_progress(prog):
    (config.WORK / "progress.json").write_text(json.dumps(prog, indent=2), encoding="utf-8")

def main(retries=2):
    """Two-pass render to avoid swapping Flux<->Wan in VRAM every shot:
    Pass A = all keyframes (Flux resident), Pass B = all videos (Wan resident)."""
    ep = json.loads((config.WORK / "episode.json").read_text(encoding="utf-8"))
    comfy.start_server()
    prog = load_progress()
    prog.setdefault("started", time.time()); prog.setdefault("shots", {})
    total = len(ep["shots"])

    # ---- Pass A: keyframes ----
    print("=== PASS A: keyframes (Flux) ===")
    _emit("render", f"Pass A: keyframes (0/{total})", data={"pass": "A", "total": total})
    prev_loc = prev_key = None
    for i, shot in enumerate(ep["shots"], 1):
        sid = shot["id"]
        st = prog["shots"].setdefault(sid, {})
        keyfile = config.SHOTS / f"{sid}_key.png"
        loc = shot.get("location") or shot.get("setting")
        if keyfile.exists() and st.get("key") == "done":
            prev_loc, prev_key = loc, keyfile
            print(f"[A {i}/{total}] {sid} keyframe exists, skip"); continue
        # continuity (experimental, opt-in): consecutive same-location shots share an establishing keyframe
        if config.CONTINUITY and prev_key and prev_key.exists() and loc and loc == prev_loc:
            try:
                shutil.copy(prev_key, keyfile)
                (config.ENGINE / "input").mkdir(parents=True, exist_ok=True)
                shutil.copy(prev_key, config.ENGINE / "input" / f"{sid}_key.png")
                st.update(key="done", key_secs=0, continuity=True); save_progress(prog)
                _emit("keyframe", f"{sid} reused prior keyframe (continuity)", data={"sid": sid, "i": i})
                print(f"[A {i}/{total}] {sid} keyframe reused (continuity)")
                prev_loc, prev_key = loc, keyfile; continue
            except Exception:
                pass
        for attempt in range(retries+1):
            try:
                t0 = time.time()
                render_keyframe(shot, salt=attempt)
                st["key"] = "done"; st["key_secs"] = round(time.time()-t0,1); save_progress(prog)
                _emit("keyframe", f"{sid} keyframe OK ({i}/{total})", data={"sid": sid, "i": i, "secs": st["key_secs"]})
                print(f"[A {i}/{total}] {sid} keyframe OK ({st['key_secs']:.0f}s)")
                prev_loc, prev_key = loc, keyfile
                break
            except Exception as e:
                print(f"[A {i}/{total}] {sid} keyframe FAIL {attempt+1}: {e}")
                st["key"] = f"retry{attempt+1}"; save_progress(prog); time.sleep(2)
        else:
            st["key"] = "failed"; save_progress(prog)
            _emit("keyframe", f"{sid} keyframe FAILED", "warn", {"sid": sid, "i": i})

    # ---- Pass B: videos ----
    print("=== PASS B: videos (Wan) ===")
    _emit("render", f"Pass B: videos (0/{total})", data={"pass": "B", "total": total})
    for i, shot in enumerate(ep["shots"], 1):
        sid = shot["id"]
        st = prog["shots"].setdefault(sid, {})
        out = config.SHOTS / f"{sid}.mp4"
        if out.exists() and st.get("status") == "done":
            print(f"[B {i}/{total}] {sid} video done, skip"); continue
        if not (config.SHOTS / f"{sid}_key.png").exists():
            print(f"[B {i}/{total}] {sid} no keyframe, skip"); st["status"]="failed"; save_progress(prog); continue
        # ensure keyframe is in ComfyUI/input
        key_name = f"{sid}_key.png"
        dst = config.ENGINE / "input" / key_name
        if not dst.exists():
            shutil.copy(config.SHOTS / key_name, dst)
        for attempt in range(retries+1):
            try:
                t0 = time.time()
                nf = render_video(shot, key_name, salt=attempt)
                dt = time.time()-t0
                st.update(status="done", frames=nf, secs=round(dt,1), t=time.time()); save_progress(prog)
                _emit("video", f"{sid} video OK ({i}/{total})", data={"sid": sid, "i": i, "frames": nf, "secs": round(dt, 1)})
                print(f"[B {i}/{total}] {sid} video OK ({nf} frames, {dt:.0f}s)")
                break
            except Exception as e:
                print(f"[B {i}/{total}] {sid} video FAIL {attempt+1}: {e}")
                st["status"] = f"retry{attempt+1}"; st["err"]=str(e)[:160]; save_progress(prog); time.sleep(2)
        else:
            st["status"] = "failed"; save_progress(prog)
            _emit("video", f"{sid} video FAILED", "warn", {"sid": sid, "i": i})

    done = sum(1 for s in prog["shots"].values() if s.get("status")=="done")
    _emit("render", f"Render complete: {done}/{total} shots done.", data={"done": done, "total": total})
    print(f"\nRender complete: {done}/{total} shots done.")

if __name__ == "__main__":
    main()
