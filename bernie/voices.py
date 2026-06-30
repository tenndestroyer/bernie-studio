"""Generate per-line character voices with edge-tts, and report durations.
Output: work/voices/<shot>_<idx>_<speaker>.mp3  +  work/voices/manifest.json

Quality passes (production-readiness review quick wins):
  * loudness-normalize every line (-16 LUFS) so speaker levels never jump
  * generate lines in parallel (bounded) instead of one-at-a-time
  * honor a leading [EMOTION] tag in a line (nudges edge-tts rate/pitch), then strip it
  * warn (don't silently swap) when a speaker isn't in characters.CHARS
"""
import json, subprocess, sys, pathlib, asyncio, re
for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from characters import CHARS
import config
try:
    import presets
except Exception:
    presets = None

# leading [EMOTION] markup -> (rate %delta, pitch Hz delta) on top of the character's base voice
EMOTION = {
    "EXCITED": (12, 12), "HAPPY": (6, 6), "CURIOUS": (4, 6), "PROUD": (5, 5), "PLAYFUL": (8, 8),
    "TENDER": (-8, -4), "GENTLE": (-6, -3), "CALM": (-4, -2), "SAD": (-12, -8),
    "SCARED": (8, 10), "NERVOUS": (5, 6), "WHISPER": (-12, -6), "SLEEPY": (-14, -8),
}
_TAG = re.compile(r"^\s*\[([A-Za-z]{3,10})\]\s*")

# Keyword cues for the no-tag heuristic -> (rate %delta, pitch Hz delta). Magnitudes are kept to
# ~half of the explicit-tag deltas so an inferred mood is a gentle nudge, never a caricature; an
# explicit [TAG] always wins over anything inferred here.
_CUE_WORDS = [
    (("yay", "hooray", "woohoo", "wow", "yes!", "awesome", "amazing", "hurray"), (6, 6)),   # mild excited
    (("shh", "shhh", "quietly", "whisper", "whispers", "softly", "hush"), (-6, -3)),         # gentle/whisper
    (("sorry", "uh-oh", "uh oh", "oh no", "scared", "scary", "afraid", "worried", "yikes"), (4, 5)),  # mild nervous
]
_EXCITED = (6, 6)    # trailing '!'  -> mild excited
_CURIOUS = (2, 3)    # trailing '?'  -> mild curious
_GENTLE  = (-4, -2)  # '...'         -> gentle/trailing-off

def _infer_emotion(line):
    """Infer a SUBTLE (rate %, pitch Hz) delta for a line that has NO explicit [TAG].

    Pure punctuation/keyword heuristic — not sentiment analysis. Word cues take priority over
    bare punctuation; returns (0, 0) when nothing matches so the base voice is used unchanged.
    """
    s = (line or "").strip()
    if not s:
        return (0, 0)
    low = s.lower()
    for words, delta in _CUE_WORDS:
        for w in words:
            if w in low:
                return delta
    if s.endswith("..."):
        return _GENTLE
    if s.endswith("!"):
        return _EXCITED
    if s.endswith("?"):
        return _CURIOUS
    return (0, 0)

def _delta(val, d, unit):
    try: n = int(str(val).replace(unit, "").replace("+", ""))
    except Exception: n = 0
    n += d
    return f"{'+' if n >= 0 else ''}{n}{unit}"

def _apply_emotion(line, rate, pitch):
    """Apply emotion to a line. An explicit leading [TAG] wins; otherwise infer a subtle mood from
    punctuation/keywords. Either way the [TAG] is stripped from the spoken text."""
    m = _TAG.match(line or "")
    if not m:
        dr, dp = _infer_emotion(line)
        if dr or dp:
            return line, _delta(rate, dr, "%"), _delta(pitch, dp, "Hz")
        return line, rate, pitch
    spoken = _TAG.sub("", line, count=1)
    dr, dp = EMOTION.get(m.group(1).upper(), (0, 0))
    return spoken, _delta(rate, dr, "%"), _delta(pitch, dp, "Hz")

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

def _normalize(mp3, target_i=-16):
    """Loudness-normalize one line in place (-16 LUFS) so every speaker sits at the
    same level. Safe: on any ffmpeg error the original line is left untouched."""
    try:
        if not mp3.exists() or mp3.stat().st_size < 200:
            return
        tmp = mp3.with_suffix(".norm.mp3")
        r = subprocess.run(["ffmpeg","-y","-i",str(mp3),
                            "-af", f"loudnorm=I={target_i}:TP=-1.5:LRA=11",
                            "-c:a","libmp3lame","-q:a","2", str(tmp)],
                           capture_output=True, text=True)
        if r.returncode == 0 and tmp.exists() and tmp.stat().st_size > 200:
            tmp.replace(mp3)
        elif tmp.exists():
            tmp.unlink()
    except Exception:
        pass

def _voice_map():
    """Speaker -> (voice_name, rate, pitch), from the active voice pack merged over CHARS.

    presets.voices() already returns the CHARS tuples as its fallback base with the JSON pack
    (configs/voices/<VOICEPACK>.json) merged on top; if presets is unavailable we degrade to the
    raw CHARS voices. Never raises."""
    vm = {}
    try:
        if presets is not None:
            for sp, v in (presets.voices() or {}).items():
                if v:
                    vm[sp] = tuple(v)
    except Exception:
        vm = {}
    if not vm:  # last-ditch fallback if presets failed entirely
        for sp, c in CHARS.items():
            v = c.get("voice")
            if v:
                vm[sp] = tuple(v)
    return vm

def main():
    ep = json.loads((config.WORK / "episode.json").read_text(encoding="utf-8"))
    vmap = _voice_map()
    narr = vmap.get("NARR") or CHARS["NARR"]["voice"]
    jobs = []
    for shot in ep["shots"]:
        for i, d in enumerate(shot["dialogue"]):
            sp = d["speaker"]
            cv = vmap.get(sp)
            if not cv:
                print(f"  !! unknown speaker '{sp}' -> narrator voice (add it to the voice pack / characters.CHARS)")
                cv = narr
            vname, rate, pitch = cv
            spoken, rate, pitch = _apply_emotion(d["line"], rate, pitch)
            jobs.append(dict(shot=shot["id"], idx=i, speaker=sp, raw=d["line"], spoken=spoken,
                             voice=vname, rate=rate, pitch=pitch,
                             out=config.VOICES / f"{shot['id']}_{i}_{sp}.mp3"))

    # ---- generate in parallel (bounded concurrency), with a sequential fallback ----
    async def _run_all():
        sem = asyncio.Semaphore(int(getattr(config, "TTS_WORKERS", 4)))
        async def one(j):
            async with sem:
                try:
                    await _tts(j["spoken"], j["voice"], j["rate"], j["pitch"], j["out"])
                except Exception as e:
                    print(f"  !! {j['shot']} {j['speaker']}: {e}")
        await asyncio.gather(*[one(j) for j in jobs])
    try:
        asyncio.run(_run_all())
    except Exception as e:
        print(f"  parallel TTS failed ({e}); falling back to sequential.")
        for j in jobs:
            try: asyncio.run(_tts(j["spoken"], j["voice"], j["rate"], j["pitch"], j["out"]))
            except Exception as ee: print(f"  !! {j['shot']} {j['speaker']}: {ee}")

    # ---- normalize + probe durations + manifest ----
    manifest = []
    for j in jobs:
        _normalize(j["out"])
        dur = ffprobe_dur(j["out"])
        manifest.append(dict(shot=j["shot"], idx=j["idx"], speaker=j["speaker"],
                             file=j["out"].name, line=j["raw"], dur=round(dur, 2)))
        print(f"  {j['shot']} {j['speaker']:7s} {dur:5.2f}s  {j['raw'][:45]}")
    (config.VOICES / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    total = sum(m["dur"] for m in manifest)
    print(f"\n{len(manifest)} voice lines (parallel+normalized), {total:.1f}s total dialogue -> {config.VOICES}")

if __name__ == "__main__":
    main()
