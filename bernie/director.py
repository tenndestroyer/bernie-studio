"""Autonomous AI Movie Director Agent (LLM-driven, Cerebras gpt-oss-120b).

Reviews the episode SCRIPT across many professional lenses, scores it 0-100 per
dimension, then rewrites dialogue / staging / camera / pacing and adds jokes, callbacks
and stronger hooks/endings — looping review->improve until a quality target is met or an
iteration cap is hit.

HONEST SCOPE: the Director has real authority over the *script* (story, dialogue, comedy,
pacing, hooks, educational beats) and over *prompt-level* staging/camera/lighting cues that
feed Flux/Wan. It cannot repaint pixels; visual fixes happen by re-rendering a shot with the
improved prompt. LLM self-scores are a heuristic guide, not ground truth — hence the cap.
Visual review of rendered frames is a separate optional pass (needs a vision model)."""
import json, sys, pathlib, urllib.request, urllib.error, time, re
# Windows console defaults to cp1252 and crashes on LLM Unicode (smart quotes/hyphens).
# Force UTF-8 with replacement so printing/logging LLM text never raises.
for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import config
from characters import char_block
from showrunner import build_positive, LOCATIONS

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
MODEL = "gpt-oss-120b"

# ---- scoring dimensions (0-100) ----
DIMENSIONS = ["story_quality","character_development","dialogue","humor","adventure",
    "emotional_impact","educational_value","child_engagement","pacing","hook",
    "ending","retention","rewatchability","visual_storytelling","music_audio",
    "youtube_suitability","production_quality","overall_entertainment"]

# ---- review passes: (name, focus + which dims to score) ----
PASSES = [
 ("Story",      "story structure, arc, adventure progression, satisfying payoffs, pacing of acts",
                ["story_quality","adventure","pacing"]),
 ("Character",  "character consistency, distinct personalities, emotional development, relationships",
                ["character_development"]),
 ("Dialogue",   "natural kid-friendly dialogue, clarity, voice per character, no stiff lines",
                ["dialogue"]),
 ("Comedy",     "humor, comic timing, visual gags, running jokes a 2-6yo laughs at",
                ["humor"]),
 ("Emotional",  "emotional highs/lows, heart, empathy, the lonely-friend payoff landing",
                ["emotional_impact"]),
 ("Educational","natural (not preachy) lesson + dino fact woven into story",
                ["educational_value"]),
 ("Engagement", "no dead time, something delightful every few seconds, momentum for little kids",
                ["child_engagement"]),
 ("Retention",  "5-15s hook strength, curiosity gaps, cliffhanger/teaser, rewatch + viral pull",
                ["hook","ending","retention","rewatchability"]),
 ("Cinematic",  "visual storytelling, shot composition, camera movement, lighting mood cues "
                "(as PROMPT guidance in each shot's action/motion text)",
                ["visual_storytelling"]),
 ("Music",      "where songs/score/sfx should land for maximum effect",
                ["music_audio"]),
 ("Executive",  "overall YouTube-Kids production quality and entertainment, greenlight verdict",
                ["youtube_suitability","production_quality","overall_entertainment"]),
]

SHOW = ("'Bernie & the Dino Valley Pals' — a premium preschool (ages 2-6) animated series. "
        "Bernie is a brave, big-hearted Bernese Mountain Dog puppy; Pip is his tiny excitable "
        "ladybug pal. They discover a hidden valley of FRIENDLY dinosaurs. Warm, funny, gentle, "
        "musical, with a clear kindness lesson and a fun dino fact per episode. Think CoComelon/"
        "Moonbug polish + Bluey heart.")

def _post(url, headers, payload, timeout):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers)
    return json.loads(urllib.request.urlopen(req, timeout=timeout).read())

def _p_cerebras(system, user, mt, temp):
    key = config.cerebras_key()
    if not key: raise RuntimeError("no cerebras key")
    r = _post("https://api.cerebras.ai/v1/chat/completions",
        {"Authorization":"Bearer "+key,"Content-Type":"application/json","User-Agent":UA},
        {"model":"gpt-oss-120b","messages":[{"role":"system","content":system},
         {"role":"user","content":user}],"max_tokens":mt,"temperature":temp,
         "reasoning_effort":"low","response_format":{"type":"json_object"}}, 90)
    m = r["choices"][0]["message"]; return m.get("content") or m.get("reasoning") or ""

def _p_openai(url, key, model, system, user, mt, temp):
    if not key: raise RuntimeError("no key")
    r = _post(url, {"Authorization":"Bearer "+key,"Content-Type":"application/json","User-Agent":UA},
        {"model":model,"messages":[{"role":"system","content":system},
         {"role":"user","content":user}],"max_tokens":mt,"temperature":temp,
         "response_format":{"type":"json_object"}}, 90)
    return r["choices"][0]["message"].get("content","") or ""

def _p_ollama(system, user, mt, temp):
    r = _post(config.OLLAMA_URL + "/api/chat", {"Content-Type":"application/json"},
        {"model":config.LOCAL_LLM_MODEL,"messages":[{"role":"system","content":system},
         {"role":"user","content":user}],"stream":False,"format":"json",
         "options":{"temperature":temp,"num_predict":mt}}, 600)
    return r.get("message", {}).get("content", "") or ""

def _provider(name, system, user, mt, temp):
    if name == "cerebras": return _p_cerebras(system, user, mt, temp)
    if name == "groq":     return _p_openai("https://api.groq.com/openai/v1/chat/completions",
                                config.GROQ_KEY, "llama-3.3-70b-versatile", system, user, mt, temp)
    if name == "mistral":  return _p_openai("https://api.mistral.ai/v1/chat/completions",
                                config.MISTRAL_KEY, "mistral-large-latest", system, user, mt, temp)
    if name == "ollama":   return _p_ollama(system, user, mt, temp)
    raise RuntimeError(f"unknown provider {name}")

def llm(system, user, max_tokens=4096, temperature=0.7, effort="low", retries=1):
    """FREE provider chain: tries each free cloud provider once, then guaranteed LOCAL Ollama.
    No long backoff — a rate-limited provider just yields to the next free one."""
    last = None
    for name in config.LLM_CHAIN:
        try:
            out = _provider(name.strip(), system, user, max_tokens, temperature)
            if out and out.strip():
                return out
        except Exception as e:
            last = f"{name}: {e}"; continue
    raise RuntimeError(f"all free LLM providers failed (last: {last})")

def extract_json(text):
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\n?", "", text); text = re.sub(r"\n?```$", "", text)
    s = text.find("{")
    if s < 0: raise ValueError("no JSON in response")
    # strict: brace-match, ignoring braces inside strings
    depth = 0; instr = False; esc = False
    for i in range(s, len(text)):
        ch = text[i]
        if esc: esc = False; continue
        if ch == "\\": esc = True; continue
        if ch == '"': instr = not instr; continue
        if instr: continue
        if ch == "{": depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try: return json.loads(text[s:i+1])
                except Exception: break
    # truncated/unbalanced -> repair: close any open string + brackets and retry
    frag = text[s:]
    instr = False; esc = False; stack = []
    for ch in frag:
        if esc: esc = False; continue
        if ch == "\\": esc = True; continue
        if ch == '"': instr = not instr; continue
        if instr: continue
        if ch in "{[": stack.append(ch)
        elif ch == "}" and stack and stack[-1] == "{": stack.pop()
        elif ch == "]" and stack and stack[-1] == "[": stack.pop()
    repaired = frag.rstrip().rstrip(",")
    if instr: repaired += '"'
    for opener in reversed(stack):
        repaired += "}" if opener == "{" else "]"
    return json.loads(repaired)

def script_text(ep):
    lines = [f"EPISODE: {ep['title']}  ({len(ep['shots'])} shots)"]
    for s in ep["shots"]:
        dlg = "  ".join(f'{d["speaker"]}: "{d["line"]}"' for d in s["dialogue"]) or "(no dialogue)"
        lines.append(f'[{s["id"]} | beat={s["beat"]} | {",".join(s["chars"])}] '
                     f'ACTION: {s.get("action","")}  CAMERA: {s.get("motion","")}  {dlg}')
    return "\n".join(lines)

def review_pass(script, name, focus, dims):
    sys_p = ("You are an uncompromising, world-class animation director and children's-TV "
             "showrunner reviewing a script for "+SHOW)
    user_p = (f"REVIEW LENS: {name} — focus on: {focus}.\n\nSCRIPT:\n{script}\n\n"
        f"Score ONLY these dimensions 0-100 (be a tough but fair professional; great kids' TV "
        f"scores 80-90, masterpiece 90+): {dims}.\n"
        "Then give the most impactful, concrete fixes. Reply ONLY as JSON:\n"
        '{"scores":{"dim":int,...},"notes":[{"shot":"sID or GLOBAL","issue":"...","fix":"..."}]}')
    try:
        return extract_json(llm(sys_p, user_p, max_tokens=4000))
    except Exception as e:
        print(f"   [pass {name} parse fail: {e}]"); return {"scores":{}, "notes":[]}

def review(ep):
    script = script_text(ep)
    scores, notes = {}, []
    for i, (name, focus, dims) in enumerate(PASSES):
        print(f"   pass: {name} ...")
        if i: time.sleep(6)   # space calls to respect free-tier rate limit
        r = review_pass(script, name, focus, dims)
        for k,v in r.get("scores",{}).items():
            try: scores[k] = int(v)
            except: pass
        for n in r.get("notes",[]):
            n["pass"] = name; notes.append(n)
    # any unscored dims -> derive overall later; compute summary
    crit = [scores.get(d,0) for d in DIMENSIONS if d in scores]
    report = {"scores":scores, "notes":notes,
              "min_score":min(crit) if crit else 0,
              "avg_score":round(sum(crit)/len(crit),1) if crit else 0}
    return report

def improve(ep, report):
    script = script_text(ep)
    weak = report["notes"][:24]   # cap to keep request small (avoid 413 on free tiers)
    notes_txt = "\n".join(f'- [{n.get("shot","")}] {str(n.get("fix") or n.get("issue",""))[:160]}'
                          for n in weak)
    sys_p = ("You are an Oscar-winning animation director and head writer doing a polish pass on "
             "a script for "+SHOW+" You make it funnier, warmer, tighter and more bingeable while "
             "keeping it gentle and age-appropriate. Keep each character's voice; keep the kindness "
             "lesson and dino fact; keep it the same story and the same shot IDs.")
    user_p = (f"CURRENT SCRIPT:\n{script}\n\nDIRECTOR NOTES TO ADDRESS:\n{notes_txt}\n\n"
        "Rewrite to fix these. You may rewrite dialogue (punchier, funnier, more natural), "
        "enrich ACTION (clearer staging, expressions, composition, lighting mood) and CAMERA "
        "(motion that serves the moment) — ACTION/CAMERA become image-generation prompts so make "
        "them vivid and concrete. Add callbacks/running gags and a stronger hook + ending where "
        "noted. Keep dialogue lines short for little kids. Return ONLY JSON with the shots you "
        "changed:\n"
        '{"shots":[{"id":"sID","dialogue":[{"speaker":"NAME","line":"..."}],"action":"...",'
        '"motion":"..."}],"summary":"what you changed"}\n'
        "Only include fields you changed per shot; omit dialogue to leave it as-is.")
    out = extract_json(llm(sys_p, user_p, max_tokens=4000, temperature=0.8))
    changed = {s["id"]: s for s in out.get("shots",[])}
    n_applied = 0
    for shot in ep["shots"]:
        c = changed.get(shot["id"])
        if not c: continue
        if "dialogue" in c and c["dialogue"]:
            shot["dialogue"] = [{"speaker":d["speaker"],"line":d["line"]} for d in c["dialogue"]]
        if c.get("action"): shot["action"] = c["action"]
        if c.get("motion"): shot["motion"] = c["motion"]
        # rebuild the render prompt with style+characters locked + new action — but only if the
        # shot actually has an action (don't degrade a positive on an action-less legacy episode)
        if shot.get("action") and shot.get("location") is not None and shot.get("chars") is not None:
            shot["positive"] = build_positive(shot["location"], shot["chars"], shot["action"])
        n_applied += 1
    return ep, out.get("summary",""), n_applied

def direct(ep, target=90, max_iters=3):
    history = []
    for it in range(1, max_iters+1):
        print(f"\n=== DIRECTOR ROUND {it}/{max_iters} ===")
        rep = review(ep)
        print(f"   scores: min={rep['min_score']} avg={rep['avg_score']}")
        history.append({"round":it,"min":rep["min_score"],"avg":rep["avg_score"],
                        "scores":rep["scores"]})
        if rep["min_score"] >= target:
            print(f"   TARGET MET (min {rep['min_score']} >= {target})"); break
        if it == max_iters:
            print("   max iterations reached"); break
        ep, summary, n = improve(ep, rep)
        print(f"   improved {n} shots: {summary[:120]}")
    return ep, history, rep

def main(target=90, max_iters=3, apply=False):
    src = config.WORK / "episode.json"
    ep = json.loads(src.read_text(encoding="utf-8"))
    ep, history, final = direct(ep, target=target, max_iters=max_iters)
    out = config.WORK / "episode_directed.json"
    out.write_text(json.dumps(ep, indent=2), encoding="utf-8")
    report = {"history":history, "final_scores":final["scores"],
              "final_min":final["min_score"], "final_avg":final["avg_score"],
              "notes":final["notes"]}
    (config.WORK / "director_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    if apply:
        src.write_text(json.dumps(ep, indent=2), encoding="utf-8")
        print(f"\nAPPLIED to episode.json")
    print(f"\nDirector done. final min={final['min_score']} avg={final['avg_score']}")
    print(f"-> {out}  +  director_report.json")
    return report

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, default=90)
    ap.add_argument("--iters", type=int, default=3)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    main(target=a.target, max_iters=a.iters, apply=a.apply)
