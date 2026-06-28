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

    inputs = ["-i", str(base)]
    fc = []; idx = 1; mixlabels = ["[0:a]"]
    def span(beat):
        segs = [t for t in timeline if t["beat"]==beat]
        if not segs: return None
        return segs[0]["start"], segs[-1]["start"]+segs[-1]["dur"]

    if under.exists():
        inputs += ["-stream_loop","-1","-i",str(under)]
        fc.append(f"[{idx}:a]volume=0.12[bed]"); mixlabels.append("[bed]"); idx+=1
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
    subprocess.run(["ffmpeg","-y", *inputs, "-filter_complex",";".join(fc),
                    "-map","0:v","-map","[aout]","-c:v","copy","-c:a","aac","-b:a","192k",str(final)],
                   capture_output=True, text=True)
    print(f"OUTPUT (with music): {final}")

if __name__ == "__main__":
    main()
