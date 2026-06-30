"""Overlay music beds onto the assembled episode, ducked under dialogue.
Looks for beds in work/music/: underscore.mp3 (bed under all), theme.mp3 (theme beat),
say_hello.mp3 (song beat). If none present, just promotes the no-music cut to final.
Drop Suno/Udio tracks (from Bernie_Show/05_Song_Production_Suno_Ready.md) into work/music/ with
those names and re-run for full music."""
import json, sys, pathlib, subprocess
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import config

def main():
    epname = getattr(config, "EPISODE_NAME", "Bernie_Ep1")
    base = config.OUT / f"{epname}_nomusic.mp4"
    final = config.OUT / f"{epname}.mp4"
    if not base.exists():
        print("no assembled cut yet; run assemble.py first"); return
    M = config.MUSIC
    under = M / "underscore.mp3"; theme = M / "theme.mp3"; song = M / "say_hello.mp3"
    timeline = json.loads((config.WORK / "timeline.json").read_text()) if (config.WORK/"timeline.json").exists() else []

    beds = [b for b in (under, theme, song) if b.exists()]
    if not beds:
        print("no music beds found in work/music/ -> promoting no-music cut to final.")
        subprocess.run(["ffmpeg","-y","-i",str(base),"-c","copy",str(final)], capture_output=True)
        print(f"OUTPUT: {final}")
        return

    def span(beat):
        segs = [t for t in timeline if t["beat"]==beat]
        if not segs: return None
        return segs[0]["start"], segs[-1]["start"]+segs[-1]["dur"]

    def build(ducked):
        """Build (inputs, filter_complex). When ducked, the underscore bed is
        sidechain-compressed by the dialogue track so the music drops ~10 dB under
        speech and swells back in the gaps (broadcast-style), instead of sitting at a
        flat low volume. A fuller bed (0.28) is safe precisely because it ducks."""
        inputs = ["-i", str(base)]
        fc = []; idx = 1
        if ducked:
            fc.append("[0:a]asplit=2[vmix][vkey]"); voice = "[vmix]"
        else:
            voice = "[0:a]"
        mixlabels = [voice]
        if under.exists():
            inputs += ["-stream_loop","-1","-i",str(under)]
            if ducked:
                fc.append(f"[{idx}:a]volume=0.28[bedraw]")
                fc.append("[bedraw][vkey]sidechaincompress=threshold=0.04:ratio=9:attack=5:release=300[bed]")
            else:
                fc.append(f"[{idx}:a]volume=0.12[bed]")
            mixlabels.append("[bed]"); idx+=1
        if theme.exists():
            s = span("theme")
            if s:
                inputs += ["-i",str(theme)]
                fc.append(f"[{idx}:a]adelay={int(s[0]*1000)}|{int(s[0]*1000)},volume=0.5[th]"); mixlabels.append("[th]"); idx+=1
        if song.exists():
            s = span("song")
            if s:
                inputs += ["-i",str(song)]
                fc.append(f"[{idx}:a]adelay={int(s[0]*1000)}|{int(s[0]*1000)},volume=0.5[sg]"); mixlabels.append("[sg]"); idx+=1
        fc.append("".join(mixlabels) + f"amix=inputs={len(mixlabels)}:normalize=0:duration=first[aout]")
        return inputs, fc

    def render(inputs, fc):
        return subprocess.run(["ffmpeg","-y", *inputs, "-filter_complex",";".join(fc),
                    "-map","0:v","-map","[aout]","-c:v","copy","-c:a","aac","-b:a","192k",str(final)],
                   capture_output=True, text=True)

    # primary: broadcast-style sidechain ducking; fall back to the simple fixed bed on any ffmpeg error
    inp, fc = build(ducked=True)
    r = render(inp, fc)
    if r.returncode != 0 or not final.exists():
        print("ducked mix failed; falling back to fixed-volume bed.")
        inp, fc = build(ducked=False); r = render(inp, fc)
        print(f"OUTPUT (with music): {final}")
    else:
        print(f"OUTPUT (with music + dialogue ducking): {final}")

if __name__ == "__main__":
    main()
