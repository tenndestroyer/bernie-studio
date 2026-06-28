"""Assemble final episode from rendered shot clips + voices (+ optional music).
Per shot: time to dialogue, color-grade, gentle fades, freeze-pad to length, lay voices.
Then concat all shots and overlay music beds if present in work/music/.
Output: output/Bernie_Ep1.mp4 (1080p, yuv420p)."""
import json, subprocess, sys, pathlib, math
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import config

OUT_W, OUT_H = 1920, 1080
GAP = 0.30            # silence before a line
TAIL = 0.5           # hold after last line

# warm, soft "storybook" grade (gentle lift, warm tint, mild saturation, slight vignette feel)
GRADE = ("eq=contrast=1.06:brightness=0.015:saturation=1.12:gamma_r=1.02:gamma_b=0.99,"
         "colorbalance=rs=0.03:gs=0.01:bs=-0.03:rm=0.02:bm=-0.02,"
         "unsharp=5:5:0.5:5:5:0.0")

def run(args):
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("ffmpeg failed:\n" + " ".join(str(a) for a in args)[:300] + "\n" + r.stderr[-800:])
    return r

def probe_dur(p):
    r = subprocess.run(["ffprobe","-v","quiet","-show_entries","format=duration","-of","csv=p=0",str(p)],
                       capture_output=True, text=True)
    try: return float(r.stdout.strip())
    except: return 0.0

def beat_min_dur(beat):
    # song/theme beats run long so the music actually plays out under the visuals;
    # other beats hold long enough for a calm preschool pace (looped video fills them)
    if beat == "theme" or beat.startswith("song"):
        return 11.0
    return {"wonder":6.0, "open":3.5, "montage":6.0, "fact":5.5, "arrive":4.0,
            "tender":5.0, "resolve":5.0, "suspense":4.5}.get(beat, 4.0)

def shot_voices(manifest, sid):
    return [m for m in manifest if m["shot"] == sid]

def build_shot(shot, manifest, raw_mp4):
    sid = shot["id"]
    vs = shot_voices(manifest, sid)
    # target duration
    voice_total = sum(GAP + m["dur"] for m in vs)
    dur = max(beat_min_dur(shot["beat"]), voice_total + (TAIL if vs else 0))
    raw_dur = probe_dur(raw_mp4) or config.SHOT_SECONDS

    # --- video: keep motion alive for long dialogue via seamless ping-pong loop, then
    #     grade + scale to 1080p + fades ---
    v_out = config.SHOTS / f"{sid}_v.mp4"
    grade_scale = f"scale={OUT_W}:{OUT_H}:flags=lanczos,{GRADE},fps={config.FPS}"
    fades = f"fade=t=in:st=0:d=0.25,fade=t=out:st={max(0,dur-0.25):.3f}:d=0.25"
    if dur <= raw_dur + 0.1:
        vf = f"{grade_scale},trim=duration={dur:.3f},setpts=PTS-STARTPTS,{fades}"
        run(["ffmpeg","-y","-i",str(raw_mp4),"-vf",vf,"-an","-c:v","libx264","-pix_fmt","yuv420p",
             "-r",str(config.FPS),str(v_out)])
    else:
        # 1) build seamless ping-pong (forward+reverse) so loops don't jump
        pp = config.SHOTS / f"{sid}_pp.mp4"
        run(["ffmpeg","-y","-i",str(raw_mp4),"-filter_complex",
             "[0:v]reverse[r];[0:v][r]concat=n=2:v=1[v]","-map","[v]","-an",
             "-c:v","libx264","-pix_fmt","yuv420p","-r",str(config.FPS),str(pp)])
        # 2) loop ping-pong to fill duration, then grade/scale/fade
        vf = f"{grade_scale},trim=duration={dur:.3f},setpts=PTS-STARTPTS,{fades}"
        run(["ffmpeg","-y","-stream_loop","-1","-i",str(pp),"-vf",vf,"-an",
             "-c:v","libx264","-pix_fmt","yuv420p","-r",str(config.FPS),str(v_out)])
        pp.unlink(missing_ok=True)

    # --- audio: place each voice line on a silent bed of length dur ---
    a_out = config.SHOTS / f"{sid}_a.wav"
    if vs:
        inputs = []
        for m in vs:
            inputs += ["-i", str(config.VOICES / m["file"])]
        # build adelay chain
        fc = []; t = GAP*1000
        labels = []
        for i, m in enumerate(vs):
            delay = int(round(t))
            fc.append(f"[{i}:a]aresample=44100,adelay={delay}|{delay}[a{i}]")
            labels.append(f"[a{i}]")
            t += (m["dur"] + GAP) * 1000
        mix = "".join(labels) + f"amix=inputs={len(vs)}:normalize=0,apad,atrim=duration={dur:.3f}[out]"
        fc.append(mix)
        run(["ffmpeg","-y", *inputs, "-filter_complex", ";".join(fc), "-map","[out]",
             "-c:a","pcm_s16le","-ar","44100",str(a_out)])
    else:
        run(["ffmpeg","-y","-f","lavfi","-i",f"anullsrc=r=44100:cl=stereo","-t",f"{dur:.3f}",
             "-c:a","pcm_s16le",str(a_out)])

    # --- mux ---
    s_out = config.SHOTS / f"{sid}_shot.mp4"
    run(["ffmpeg","-y","-i",str(v_out),"-i",str(a_out),"-c:v","copy","-c:a","aac","-b:a","192k",
         "-shortest",str(s_out)])
    return s_out, dur

def concat(shot_files, out_path):
    lst = config.WORK / "concat.txt"
    lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in shot_files), encoding="utf-8")
    run(["ffmpeg","-y","-f","concat","-safe","0","-i",str(lst),
         "-c:v","libx264","-pix_fmt","yuv420p","-c:a","aac","-b:a","192k",str(out_path)])

def main():
    ep = json.loads((config.WORK / "episode.json").read_text(encoding="utf-8"))
    manifest = json.loads((config.VOICES / "manifest.json").read_text(encoding="utf-8"))
    shot_files = []
    timeline = []
    t = 0.0
    for shot in ep["shots"]:
        raw = config.SHOTS / f"{shot['id']}.mp4"
        if not raw.exists():
            print(f"  !! missing rendered clip {raw.name}; skipping"); continue
        sf, dur = build_shot(shot, manifest, raw)
        shot_files.append(sf)
        timeline.append(dict(shot=shot["id"], start=round(t,2), dur=round(dur,2), beat=shot["beat"]))
        t += dur
        print(f"  built {shot['id']}  dur={dur:.2f}s  (total {t:.1f}s)")
    (config.WORK / "timeline.json").write_text(json.dumps(timeline, indent=2), encoding="utf-8")
    epname = getattr(config, "EPISODE_NAME", "Bernie_Ep1")
    base = config.OUT / f"{epname}_nomusic.mp4"
    concat(shot_files, base)
    print(f"\nAssembled {len(shot_files)} shots, {t/60:.1f} min -> {base}")
    # music overlay handled by music.py if beds exist
    print("Run music.py to overlay songs/score if beds are present.")

if __name__ == "__main__":
    main()
