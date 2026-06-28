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
    a = ap.parse_args()

    if a.slot: os.environ["BERNIE_SLOT"] = a.slot
    os.environ["BERNIE_EP"] = a.name
    import importlib, config; importlib.reload(config)
    print(config.summary())
    if a.config: return

    # optionally generate a fresh long story first (writes this slot's episode.json)
    if a.generate:
        import episode2
        episode2.PREMISE = a.generate
        episode2.main(target_scenes=a.scenes)

    # full director-driven build (uses episode.json if present, else the built-in pilot)
    import direct_episode
    direct_episode.main(script_target=a.target, script_iters=a.cycles)

if __name__ == "__main__":
    main()
