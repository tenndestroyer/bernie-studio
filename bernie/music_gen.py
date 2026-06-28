"""Generate the episode's songs locally with ACE-Step (no account needed).
Produces work/music/theme.mp3, say_hello.mp3, underscore.mp3 — which music.py overlays.
Lyrics/style from Bernie_Show/05_Song_Production_Suno_Ready.md."""
import sys, pathlib, shutil, subprocess, zlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import config, comfy, workflows

SONGS = {
    "theme": dict(
        seconds=36,
        tags="children's TV theme song, ukulele, glockenspiel, hand claps, light upbeat drums, "
             "bright and sunny, kids gang vocals, C major, 124 bpm, joyful, wholesome, clean",
        lyrics="""[verse]
He's got four big paws and a heart so wide,
A best little buddy right there by his side!
Through the meadows, 'cross the sea,
Wherever there's a friend to be...
[chorus]
Here comes Bernie, woof woof!
Big brave Bernie, here we go!
He's fluffy and he's friendly and he's ready to roam,
Every road's an adventure and every friend's a home!"""),
    "say_hello": dict(
        seconds=42,
        tags="gentle children's song building to a joyful sing-along, solo ukulele intro then full band, "
             "glockenspiel, claps, warm, F major, kids choir on chorus, tender then bright",
        lyrics="""[verse]
When somebody looks different, or big, or new,
You can't know their heart till you say how do you do!
So wave a little wave, and try a little grin,
'Cause a stranger's just a friend who hasn't started yet, let 'em in!
[chorus]
Say hello, say hello, it's the bravest word you know!
Say hello, say hello, and watch a friendship grow!"""),
    "underscore": dict(
        seconds=60,
        tags="gentle instrumental underscore, soft ukulele and glockenspiel, warm strings, wholesome, "
             "light, calm, children's show background music, no vocals, no drums, soft",
        lyrics=""),
}

STEPS = 60          # higher = better fidelity
TAKES = 2           # best-of-N auto-selection

def to_mp3(src, dest):
    # master to a consistent broadcast-ish loudness while converting
    subprocess.run(["ffmpeg","-y","-i",str(src),"-af","loudnorm=I=-15:TP=-1.0:LRA=11",
                    "-codec:a","libmp3lame","-q:a","2",str(dest)],
                   capture_output=True, text=True, check=True)

def score_take(src):
    """Higher is better: prefer loud-but-unclipped, musically-present takes."""
    r = subprocess.run(["ffmpeg","-i",str(src),"-af","volumedetect","-f","null","-"],
                       capture_output=True, text=True)
    txt = r.stderr
    def grab(key):
        import re
        m = re.search(rf"{key}:\s*(-?\d+\.?\d*) dB", txt)
        return float(m.group(1)) if m else None
    mean = grab("mean_volume") or -60.0
    mx = grab("max_volume") or 0.0
    clip_pen = max(0.0, mx + 0.3) * 4.0      # penalize hitting 0 dB (clipping)
    quiet_pen = max(0.0, (-18.0 - mean)) * 1.0
    return -clip_pen - quiet_pen + (mean/10.0)

def gen_one(name, spec):
    dest = config.MUSIC / f"{name}.mp3"
    if dest.exists() and dest.stat().st_size > 50_000:
        print(f"  {name}.mp3 exists, skip"); return dest
    print(f"  generating {name} ({spec['seconds']}s, best-of-{TAKES} @ {STEPS} steps)...")
    takes = []
    for k in range(TAKES):
        seed = (zlib.crc32(name.encode()) + k*104729) % (2**31)
        wf = workflows.ace_step(spec["tags"], spec["lyrics"], spec["seconds"], seed,
                                f"music_{name}_{k}", steps=STEPS)
        outs = comfy.run(wf, timeout=1500)
        audio = [o for o in outs if o.suffix.lower() in (".flac",".wav",".mp3",".ogg")]
        if audio:
            s = score_take(audio[-1])
            takes.append((s, audio[-1]))
            print(f"    take {k+1}: score {s:.2f}")
    if not takes:
        raise RuntimeError(f"no audio produced for {name}")
    best = max(takes, key=lambda t: t[0])[1]
    to_mp3(best, dest)
    print(f"  -> {dest.name} (best take)")
    return dest

def main():
    comfy.start_server()
    ok = 0
    for name, spec in SONGS.items():
        try:
            gen_one(name, spec); ok += 1
        except Exception as e:
            print(f"  !! {name} failed: {e}")
    print(f"\nmusic: {ok}/{len(SONGS)} tracks in {config.MUSIC}")

if __name__ == "__main__":
    main()
