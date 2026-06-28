"""FULL director-driven autonomous episode build — the Movie Director Agent overseeing the
whole pipeline with a quality-improvement loop:

  1) SCRIPT DIRECTION (Cerebras gpt-oss-120b): multi-pass review -> score -> rewrite
     dialogue/staging/camera/jokes/hooks, loop to target -> apply improved script
  2) Voices (match improved dialogue) + Songs (ACE-Step)
  3) RENDER (Flux keyframes + Wan video, two-pass)
  4) VISUAL REVIEW (Ollama qwen2.5vl): look at every shot, flag off-model/scary/weak frames
  5) REVISION LOOP: re-render flagged shots (fresh seed + improved prompt), re-review,
     repeat until clean or max revision rounds
  6) Assemble (grade/pacing/1080p) + music mix -> output/Bernie_Ep1.mp4

Honest: script + prompt-level direction is real authority; visual fixes are re-rolls guided
by a vision model, not pixel-precise painting. Scores are heuristic guides with hard caps so
the loop always terminates."""
import sys, pathlib, json, time, traceback
for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import config

LOG = config.LOGDIR / (f"direct_episode_{config.SLOT}.log" if config.SLOT else "direct_episode.log")
def log(m):
    line = f"{time.strftime('%H:%M:%S')}  {m}"; print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f: f.write(line+"\n")

def stage(name, fn):
    log(f"=== START {name} ===")
    try:
        fn(); log(f"=== DONE {name} ==="); return True   # success (fn may return None)
    except Exception as e:
        log(f"=== FAIL {name}: {e} ==="); log(traceback.format_exc()); return False

def main(script_target=88, script_iters=3, visual_min=62, revision_rounds=2):
    log("########## DIRECTOR-DRIVEN BERNIE BUILD ##########")

    # 0) base shot list — use a pre-generated episode.json if present (e.g. a long Ep2),
    #    otherwise build the default Ep1 shot list.
    def _shotlist():
        epf = config.WORK / "episode.json"
        if epf.exists():
            ep = json.loads(epf.read_text(encoding="utf-8"))
            log(f"using pre-generated shotlist: {len(ep['shots'])} shots in {config.WORK}")
            return
        import showrunner
        ep = showrunner.build_episode()
        epf.write_text(json.dumps(ep, indent=2), encoding="utf-8")
        log(f"shotlist: {len(ep['shots'])} shots in {config.WORK}")
    stage("shotlist", _shotlist)

    # 1) SCRIPT DIRECTION — full 20-agent writers' room (Master Creative Director orchestrates)
    def _script():
        import agency
        rep = agency.main(target=script_target, max_cycles=script_iters, apply=True)
        log(f"writers' room: {rep['n_agents']} agents, final min={rep['final_min']} avg={rep['final_avg']}")
    stage("script-direction", _script)

    # 2) voices + songs (voices regen to match new dialogue)
    def _voices():
        (config.VOICES/"manifest.json").unlink(missing_ok=True)   # force regen for new dialogue
        import importlib, voices; importlib.reload(voices); voices.main()
    stage("voices", _voices)
    stage("songs", lambda: __import__("music_gen").main())

    # 3) RENDER
    stage("render", lambda: __import__("pipeline").main())

    # 4+5) VISUAL REVIEW + REVISION LOOP
    def _visual_loop():
        import director_visual, director_revise
        for rnd in range(1, revision_rounds+1):
            log(f"--- visual review round {rnd} ---")
            weak, report = director_visual.review_keyframes(min_score=visual_min)
            log(f"visual avg={report.get('avg_visual')}, flagged {len(weak)}")
            if not weak:
                log("no weak shots; visual quality bar met"); break
            ids = [w["shot"] for w in weak]
            log(f"re-rendering: {ids}")
            director_revise.revise(ids, use_directed_prompts=True)
    stage("visual-review+revision", _visual_loop)

    # 6) assemble + music
    if stage("assemble", lambda: __import__("assemble").main()):
        stage("music", lambda: __import__("music").main())
    final = config.OUT / (getattr(config, "EPISODE_NAME", "Bernie_Ep1") + ".mp4")
    log(f"########## DONE: {final} exists={final.exists()} ##########")

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--script-target", type=int, default=88)
    ap.add_argument("--script-iters", type=int, default=3)
    ap.add_argument("--visual-min", type=int, default=62)
    ap.add_argument("--revision-rounds", type=int, default=2)
    a = ap.parse_args()
    main(a.script_target, a.script_iters, a.visual_min, a.revision_rounds)
