"""Assemble final episode from rendered shot clips + voices (+ optional music).
Per shot: time to dialogue, color-grade, gentle fades, freeze-pad to length, lay voices.
Then concat all shots and overlay music beds if present in work/music/.
Output: output/Bernie_Ep1.mp4 (1080p, yuv420p).

Long-beat fill: when a beat needs more time than the ~3.4s Wan clip, we pick the
least-jarring way to stretch to length instead of always reverse-loop ping-ponging
(which visibly plays the motion backwards). Small overflow -> hold the last frame
(or a single gentle slow-down); only large gaps fall back to ping-pong. Each shot's
total duration is kept EXACT so the timeline stays in sync.

Lip-sync is an OPT-IN hook (config.LIPSYNC): if a 'lipsync' module is importable and
reports available(), we try to re-sync a dialogue shot's mouth to its voice audio.
This is an AI cartoon, not a rigged lip-synced film -- without a sync model the mouths
just animate generically; the hook never breaks the cut and silently keeps the
original clip on any failure."""
import json, subprocess, sys, pathlib, math
for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import config

# Long-beat fill tuning (seconds). Overflow = how much longer the beat is than the raw clip.
HOLD_MAX_OVERFLOW = 1.5     # <= this: just hold the last frame for the overflow tail
SLOW_MAX_FACTOR   = 2.0     # up to this slowdown (setpts) before we give up and ping-pong

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

    # --- video: fill the beat to exactly `dur`, choosing the least-jarring method, then
    #     grade + scale to 1080p + fades ---
    v_out = config.SHOTS / f"{sid}_v.mp4"
    grade_scale = f"scale={OUT_W}:{OUT_H}:flags=lanczos,{GRADE},fps={config.FPS}"
    fades = f"fade=t=in:st=0:d=0.25,fade=t=out:st={max(0,dur-0.25):.3f}:d=0.25"
    # always trim to the EXACT target so the timeline stays in sync, regardless of method
    tail = f"trim=duration={dur:.3f},setpts=PTS-STARTPTS,{fades}"
    overflow = dur - raw_dur
    if dur <= raw_dur + 0.1:
        # clip already long enough: just grade + trim to length
        vf = f"{grade_scale},{tail}"
        run(["ffmpeg","-y","-i",str(raw_mp4),"-vf",vf,"-an","-c:v","libx264","-pix_fmt","yuv420p",
             "-r",str(config.FPS),str(v_out)])
    elif overflow <= HOLD_MAX_OVERFLOW:
        # SMALL overflow -> hold the last frame for the overflow (no reversed motion, no speed
        # change). tpad clones the final frame; trim then clamps to the exact target length.
        pad = math.ceil(overflow * 100) / 100.0 + 0.2   # pad a touch extra; trim clamps exact
        vf = f"tpad=stop_mode=clone:stop_duration={pad:.3f},{grade_scale},{tail}"
        run(["ffmpeg","-y","-i",str(raw_mp4),"-vf",vf,"-an","-c:v","libx264","-pix_fmt","yuv420p",
             "-r",str(config.FPS),str(v_out)])
    elif raw_dur > 0 and (dur / raw_dur) <= SLOW_MAX_FACTOR:
        # MEDIUM overflow -> gently slow the whole clip to fit (motion stays forward, just
        # calmer). setpts factor = dur/raw_dur (<= SLOW_MAX_FACTOR); trim clamps exact.
        factor = dur / raw_dur
        vf = f"setpts={factor:.5f}*PTS,{grade_scale},{tail}"
        run(["ffmpeg","-y","-i",str(raw_mp4),"-vf",vf,"-an","-c:v","libx264","-pix_fmt","yuv420p",
             "-r",str(config.FPS),str(v_out)])
    else:
        # LARGE gap -> seamless ping-pong (forward+reverse) loop. Last resort: motion does
        # reverse, but it loops without a hard jump, which reads better than a long freeze.
        # 1) build seamless ping-pong (forward+reverse) so loops don't jump
        pp = config.SHOTS / f"{sid}_pp.mp4"
        run(["ffmpeg","-y","-i",str(raw_mp4),"-filter_complex",
             "[0:v]reverse[r];[0:v][r]concat=n=2:v=1[v]","-map","[v]","-an",
             "-c:v","libx264","-pix_fmt","yuv420p","-r",str(config.FPS),str(pp)])
        # 2) loop ping-pong to fill duration, then grade/scale/fade
        vf = f"{grade_scale},{tail}"
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

    # --- opt-in lip-sync (config.LIPSYNC) -------------------------------------------------
    # Only meaningful for DIALOGUE shots (those with voice lines). Fully guarded: if the
    # 'lipsync' module is missing / reports unavailable / errors, we keep the original cut.
    # Honest note: this needs a real model (Wav2Lip / LatentSync) to actually move the mouth;
    # with no model available the shot is left as the generic AI-animated cartoon it already is.
    if vs and getattr(config, "LIPSYNC", False):
        try:
            import lipsync  # owned elsewhere; may not exist -> degrade gracefully
            if lipsync.available():
                tmp = config.SHOTS / f"{sid}_lipsync.mp4"
                synced = lipsync.sync(s_out, a_out, tmp)   # returns a bool
                if synced and tmp.exists() and probe_dur(tmp) > 0:
                    s_out = tmp
                    print(f"  lip-synced {sid}")
        except Exception as e:
            # never break the cut over an optional cosmetic pass
            print(f"  lip-sync skipped for {sid}: {e}")

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
