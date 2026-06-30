#!/usr/bin/env python
"""Bernie Studio — make an episode end-to-end.

  python make.py                      # build the pilot (director-driven, 22-agent room)
  python make.py --slot ep2 --name Bernie_Ep2 --generate "a story about a shy dinosaur"
  python make.py --config             # just print the auto-detected hardware/config

Everything (script direction by the AI writers' room, voices, songs, render, visual review,
assemble, music) runs locally. Output lands in BernieStudioData/data/output/.
"""
import sys, os, argparse, pathlib
PKG = pathlib.Path(__file__).resolve().parent / "bernie"
sys.path.insert(0, str(PKG))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slot", default="", help="isolated work slot (e.g. ep2)")
    ap.add_argument("--name", default="Bernie_Ep1", help="output episode name")
    ap.add_argument("--generate", default="", help="LLM-generate a new story from this premise")
    ap.add_argument("--scenes", type=int, default=12, help="scenes for a generated episode")
    ap.add_argument("--target", type=int, default=86, help="agency score target")
    ap.add_argument("--cycles", type=int, default=2, help="writers'-room revision cycles")
    ap.add_argument("--config", action="store_true", help="print config and exit")
    ap.add_argument("--series", action="store_true",
                    help="FULLY AUTONOMOUS: auto-pick and build the next episode, forever")
    ap.add_argument("--max", type=int, default=None, help="(with --series) stop after N episodes")
    ap.add_argument("--gui", action="store_true", help="launch the desktop app (GUI) instead of the CLI")
    ap.add_argument("--doctor", action="store_true", help="run an install self-test")
    ap.add_argument("--fix", action="store_true", help="(with --doctor) attempt safe repairs")
    ap.add_argument("--lora", default="", help="train a character LoRA, e.g. --lora bernie")
    ap.add_argument("--continuity", action="store_true",
                    help="experimental: reuse the establishing keyframe across same-location shots")
    ap.add_argument("--backup", action="store_true",
                    help="copy finished episodes to BERNIE_BACKUP and exit")
    a = ap.parse_args()

    if a.continuity:
        os.environ["BERNIE_CONTINUITY"] = "1"

    # back up finished episodes and exit
    if a.backup:
        import backup
        dests = backup.backup_all()
        print(f"backed up {len(dests)} episode(s).")
        return

    # launch the desktop app
    if a.gui:
        import gui
        gui.serve()
        return

    # install self-test / repair
    if a.doctor:
        import doctor
        rep = doctor.run(fix=a.fix)
        for c in rep.get("checks", []):
            print(("  OK   " if c.get("ok") else "  FAIL ") + c.get("name", "") +
                  ("  — " + str(c["detail"]) if c.get("detail") else ""))
        print("\nDOCTOR:", "all good ✓" if rep.get("ok") else "problems found (see above)")
        sys.exit(0 if rep.get("ok") else 1)

    # train a character LoRA (curate dataset -> train). Honest: the training run is a long GPU job.
    if a.lora:
        if a.slot: os.environ["BERNIE_SLOT"] = a.slot
        import importlib, config; importlib.reload(config)
        import lora_dataset, lora_train
        lora_dataset.build(character=a.lora, slot=a.slot)
        lora_train.train(character=a.lora)
        return

    # autonomous series mode: keep making the next episode until the season is done
    if a.series:
        import series
        series.run_series(max_episodes=a.max)
        return

    if a.slot: os.environ["BERNIE_SLOT"] = a.slot
    os.environ["BERNIE_EP"] = a.name
    import importlib, config; importlib.reload(config)
    print(config.summary())
    if a.config: return

    # generate a fresh story only if this slot has none yet (so re-runs RESUME the render)
    if a.generate and not (config.WORK / "episode.json").exists():
        import episode2
        episode2.PREMISE = a.generate
        episode2.main(target_scenes=a.scenes)
    elif a.generate:
        print("episode.json already exists for this slot -> resuming render (not regenerating story)")

    # full director-driven build (uses episode.json if present, else the built-in pilot)
    import direct_episode
    direct_episode.main(script_target=a.target, script_iters=a.cycles)

if __name__ == "__main__":
    main()
