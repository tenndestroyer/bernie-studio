"""Generate per-line character voices with edge-tts, and report durations.
Output: work/voices/<shot>_<idx>_<speaker>.mp3  +  work/voices/manifest.json"""
import json, subprocess, sys, pathlib, asyncio
for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from characters import CHARS
import config

async def _tts(text, voice, rate, pitch, out):
    import edge_tts
    c = edge_tts.Communicate(text, voice=voice, rate=rate, pitch=pitch)
    await c.save(str(out))

def ffprobe_dur(p):
    try:
        r = subprocess.run(["ffprobe","-v","quiet","-show_entries","format=duration",
                            "-of","csv=p=0",str(p)], capture_output=True, text=True)
        return float(r.stdout.strip())
    except Exception:
        return 0.0

def main():
    ep = json.loads((config.WORK / "episode.json").read_text(encoding="utf-8"))
    manifest = []
    for shot in ep["shots"]:
        for i, d in enumerate(shot["dialogue"]):
            sp = d["speaker"]
            voice = CHARS.get(sp, {}).get("voice")
            if not voice:
                voice = CHARS["NARR"]["voice"]
            vname, rate, pitch = voice
            out = config.VOICES / f"{shot['id']}_{i}_{sp}.mp3"
            try:
                asyncio.run(_tts(d["line"], vname, rate, pitch, out))
                dur = ffprobe_dur(out)
            except Exception as e:
                print(f"  !! {shot['id']} {sp}: {e}")
                dur = 0.0
            manifest.append(dict(shot=shot["id"], idx=i, speaker=sp, file=out.name,
                                 line=d["line"], dur=round(dur,2)))
            print(f"  {shot['id']} {sp:7s} {dur:5.2f}s  {d['line'][:45]}")
    (config.VOICES / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    total = sum(m["dur"] for m in manifest)
    print(f"\n{len(manifest)} voice lines, {total:.1f}s total dialogue -> {config.VOICES}")

if __name__ == "__main__":
    main()
