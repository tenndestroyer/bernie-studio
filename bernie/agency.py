"""The writers'-room orchestrator: runs all 20 agents (agents.py), aggregates their scores
and notes, lets the Master Creative Director resolve/prioritize, then rewrites the script via
director.improve — looping review->revise until every department approves, the score target is
met, or the cycle cap is hit (so it always terminates). Pacing respects the free LLM tier."""
import sys, pathlib, json, time
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import config, director, agents

def compact_story(ep):
    """Small story-essence summary for the packaging agent (not the full shot list)."""
    title = ep.get("title", "Bernie episode")
    beats = []
    for s in ep["shots"]:
        for d in s["dialogue"]:
            beats.append(f'{d["speaker"]}: {d["line"]}')
    dialogue = "  ".join(beats)
    return f"TITLE: {title}\nSTORY (dialogue):\n{dialogue[:5000]}"

def aggregate(results):
    """Per-dimension average across agents that scored it; collect notes."""
    buckets, notes = {}, []
    valid = set(agents.DIMENSIONS)
    for aid, r in results.items():
        for k, v in r.get("scores", {}).items():
            if k not in valid:      # ignore malformed/nested keys some models emit (e.g. 'dim')
                continue
            try: buckets.setdefault(k, []).append(int(v))
            except Exception: pass
        for n in r.get("notes", []):
            n = dict(n); n["agent"] = agents.AGENTS_BY_ID[aid]["name"]; notes.append(n)
    scores = {k: round(sum(v)/len(v)) for k, v in buckets.items() if v}
    return scores, notes

def run_room(script, pace=1.2):   # local LLM: no rate limits, minimal spacing
    results = {}
    for i, agent in enumerate(agents.REVIEWERS):
        if i: time.sleep(pace)   # respect rate limit
        r = agents.run_agent(agent, script)
        results[agent["id"]] = r
        sc = r.get("scores", {})
        v = r.get("verdict", "?")
        print(f"   [{agent['name']:28s}] {v:7s} {sc}")
    return results

def run_agency(ep, target=88, max_cycles=2, pace=1.2):
    history = []
    final_scores, final_notes, master = {}, [], {}
    for cycle in range(1, max_cycles+1):
        print(f"\n===== WRITERS' ROOM — CYCLE {cycle}/{max_cycles} =====")
        script = director.script_text(ep)
        results = run_room(script, pace=pace)
        scores, notes = aggregate(results)
        crit = [v for k, v in scores.items()]
        min_s = min(crit) if crit else 0
        avg_s = round(sum(crit)/len(crit), 1) if crit else 0
        # summaries for the Master
        summ = "\n".join(
            f"  {agents.AGENTS_BY_ID[a]['name']}: {r.get('verdict','?')}"
            + (f" — {r['notes'][0].get('fix','')[:90]}" if r.get("notes") else "")
            for a, r in results.items())
        time.sleep(pace)
        master = agents.run_master(scores, summ, target)
        exec_v = results.get("exec_producer", {}).get("verdict", "revise")
        approved = (master.get("verdict") == "approve" and exec_v == "approve" and min_s >= target)
        history.append(dict(cycle=cycle, min=min_s, avg=avg_s, scores=scores,
                            master_verdict=master.get("verdict"), exec_verdict=exec_v,
                            n_notes=len(notes)))
        print(f"   -> min={min_s} avg={avg_s} | master={master.get('verdict')} exec={exec_v}")
        final_scores, final_notes = scores, notes
        if approved:
            print("   ALL DEPARTMENTS APPROVE — locked."); break
        if cycle == max_cycles:
            print("   cycle cap reached."); break
        # build prioritized note set: Master priorities first, then department notes
        pri = [{"shot": p.get("shot","GLOBAL"), "issue":"director priority",
                "fix": p.get("change","")} for p in master.get("priorities", [])]
        try:
            ep, summary, n = director.improve(ep, {"notes": pri + final_notes})
            print(f"   applied {n} shot rewrites: {summary[:110]}")
        except Exception as e:
            print(f"   improve step failed ({e}); keeping current script and stopping early")
            break
    return ep, history, {"scores": final_scores, "notes": final_notes, "master": master}

def main(target=88, max_cycles=2, apply=False):
    src = config.WORK / "episode.json"
    ep = json.loads(src.read_text(encoding="utf-8"))
    ep, history, final = run_agency(ep, target=target, max_cycles=max_cycles)
    (config.WORK/"episode_directed.json").write_text(json.dumps(ep, indent=2), encoding="utf-8")
    # Packaging & Metadata Agent: produce YouTube Kids title/description/tags/thumbnail.
    # Use a COMPACT story summary (title + beats + dialogue) — the full shot list is too large.
    try:
        summary = compact_story(ep)
        meta = agents.run_packaging(summary)
        (config.WORK/"metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        print(f"packaging: {meta.get('title') or '(none)'}")
    except Exception as e:
        print(f"packaging failed: {e}")
    report = {"history": history, "final_scores": final["scores"],
              "final_min": min(final["scores"].values()) if final["scores"] else 0,
              "final_avg": round(sum(final["scores"].values())/len(final["scores"]),1) if final["scores"] else 0,
              "master": final["master"], "n_agents": len(agents.AGENTS)}
    (config.WORK/"agency_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    if apply:
        src.write_text(json.dumps(ep, indent=2), encoding="utf-8"); print("APPLIED to episode.json")
    print(f"\nAgency done: {len(agents.AGENTS)} agents, final min={report['final_min']} avg={report['final_avg']}")
    return report

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, default=88)
    ap.add_argument("--cycles", type=int, default=2)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    main(target=a.target, max_cycles=a.cycles, apply=a.apply)
