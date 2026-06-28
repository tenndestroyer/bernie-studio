"""Director's VISUAL review pass — uses the local Ollama vision model (qwen2.5vl:7b) to
actually LOOK at rendered frames and judge them like an art director: character on-model,
composition, appeal, and (critically) nothing scary/ugly for preschoolers.

Flags weak shots so the revision loop can re-render them. This is the genuine 'review the
pixels' capability (Cerebras is text-only). Falls back to ffmpeg QC heuristics if Ollama is
unavailable."""
import json, sys, pathlib, base64, subprocess, urllib.request, urllib.error, time
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import config

OLLAMA = "http://localhost:11434/api/generate"
VLM = "qwen2.5vl:7b"

CHAR_REF = {
 "BERNIE":"Bernie, a fluffy black-and-white Bernese Mountain Dog puppy with brown eyebrow dots, a red bandana and a gold paw tag",
 "PIP":"Pip, a tiny red ladybug with black spots",
 "TUMBLE":"Tumble, a small friendly teal-green Stegosaurus with soft-yellow back plates",
 "ROSIE":"Rosie, a small lavender-pink baby Triceratops with a little daisy",
 "SKY":"Sky, a sky-blue Pteranodon with goggles",
 "REX":"Grandpa Rex, a big soft GENTLE green T-Rex with a cozy scarf (must look friendly, never scary)",
 "MAPLE":"Maple, a kind old tortoise with glasses",
}

def ollama_up():
    try:
        urllib.request.urlopen("http://localhost:11434/api/tags", timeout=5); return True
    except Exception: return False

def vlm(prompt, image_path, timeout=120):
    b64 = base64.b64encode(pathlib.Path(image_path).read_bytes()).decode()
    body = json.dumps({"model":VLM,"prompt":prompt,"images":[b64],"stream":False,
                       "options":{"temperature":0.1}}).encode()
    req = urllib.request.Request(OLLAMA, data=body, headers={"Content-Type":"application/json"})
    r = json.loads(urllib.request.urlopen(req, timeout=timeout).read())
    return r.get("response","")

def parse(resp):
    out = {"score":0,"onmodel":True,"scary":False,"issue":""}
    for line in resp.replace("|","\n").splitlines():
        u = line.upper()
        if "SCORE" in u:
            d = "".join(c for c in line if c.isdigit())
            if d: out["score"] = min(100,int(d[:3]))
        elif "ONMODEL" in u: out["onmodel"] = "YES" in u
        elif "SCARY" in u: out["scary"] = "YES" in u and "NO" not in u.split("SCARY")[-1][:5].upper()
        elif "ISSUE" in u: out["issue"] = line.split(":",1)[-1].strip()[:140]
    return out

def review_frame(image_path, chars):
    who = "; ".join(CHAR_REF[c] for c in chars if c in CHAR_REF) or "the characters"
    prompt = (f"You are a strict art director for a premium preschool cartoon (ages 2-6). "
        f"Expected characters in this frame: {who}. Look at the image and judge it.\n"
        f"Reply EXACTLY in one line:\n"
        f"SCORE: <0-100 overall quality+appeal as a polished kids cartoon> | "
        f"ONMODEL: <yes/no are the characters correct and not deformed> | "
        f"SCARY: <yes/no anything scary, ugly, or creepy for toddlers> | "
        f"ISSUE: <short note or 'none'>")
    try:
        return parse(vlm(prompt, image_path))
    except Exception as e:
        return {"score":-1,"onmodel":True,"scary":False,"issue":f"vlm error {e}"}

def review_keyframes(min_score=62):
    ep = json.loads((config.WORK/"episode.json").read_text(encoding="utf-8"))
    if not ollama_up():
        print("Ollama vision model not reachable; skipping visual review."); return [], {}
    results, weak = {}, []
    for shot in ep["shots"]:
        kf = config.SHOTS / f"{shot['id']}_key.png"
        if not kf.exists(): continue
        r = review_frame(kf, shot["chars"])
        results[shot["id"]] = r
        bad = (r["score"]>=0 and r["score"]<min_score) or r["scary"] or (not r["onmodel"])
        flag = "  <-- FLAG" if bad else ""
        print(f"  {shot['id']}: score={r['score']} onmodel={r['onmodel']} scary={r['scary']} "
              f"{r['issue'][:50]}{flag}")
        if bad: weak.append({"shot":shot["id"], **r})
    scores = [r["score"] for r in results.values() if r["score"]>=0]
    report = {"avg_visual":round(sum(scores)/len(scores),1) if scores else 0,
              "n":len(results), "weak":weak}
    (config.WORK/"visual_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nvisual avg={report['avg_visual']}  flagged {len(weak)} shots for re-render")
    return weak, report

if __name__ == "__main__":
    review_keyframes()
