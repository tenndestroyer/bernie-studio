"""Director's VISUAL review pass — uses the local Ollama vision model (qwen2.5vl:7b) to
actually LOOK at rendered frames and judge them like an art director: character on-model,
composition, appeal, and (critically) nothing scary/ugly for preschoolers.

Flags weak shots so the revision loop can re-render them. This is the genuine 'review the
pixels' capability (Cerebras is text-only). Falls back to ffmpeg QC heuristics if Ollama is
unavailable.

Honest limits: the VLM is a 7B model judging single stills. It catches obvious off-model /
scary / deformed frames, not subtle art-direction nuance, and it can't see motion in a
keyframe — that's what review_clips() is for (it pulls the MIDDLE frame of each rendered mp4
so motion-only glitches, e.g. a limb melting mid-tween, get a look too)."""
import sys
for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass
import json, pathlib, base64, subprocess, shutil, tempfile, urllib.request, urllib.error, re
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import config

# Reuse the director's robust JSON extractor if importable; else use a local tolerant parser.
try:
    from director import extract_json as _extract_json
except Exception:
    _extract_json = None

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

def _local_extract_json(text):
    """Tolerant fallback JSON extractor (used only if director.extract_json isn't importable)."""
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\n?", "", text); text = re.sub(r"\n?```$", "", text)
    s = text.find("{")
    if s < 0: raise ValueError("no JSON in response")
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
                return json.loads(text[s:i+1])
    raise ValueError("unbalanced JSON")

def _json_to_result(obj):
    """Coerce a parsed VLM dict into the strict result shape."""
    def _truthy(v):
        if isinstance(v, bool): return v
        return str(v).strip().lower() in ("yes","true","1","y")
    score = obj.get("score", 0)
    try: score = int(round(float(score)))
    except Exception: score = 0
    score = max(0, min(100, score))
    return {"score": score,
            "onmodel": _truthy(obj.get("onmodel", True)),
            "scary": _truthy(obj.get("scary", False)),
            "issue": str(obj.get("issue", "") or "")[:140]}

def parse(resp):
    """Parse a VLM response into {score,onmodel,scary,issue}.

    Prefers strict-JSON extraction; falls back to the original line/regex parser so old-style
    pipe-delimited replies (or non-JSON degradation) still work."""
    # 1) try JSON (director.extract_json if available, else local tolerant parser)
    for extractor in (_extract_json, _local_extract_json):
        if extractor is None: continue
        try:
            obj = extractor(resp)
            if isinstance(obj, dict) and ("score" in obj or "onmodel" in obj or "scary" in obj):
                return _json_to_result(obj)
        except Exception:
            pass
    # 2) fall back to the legacy regex/line parser
    out = {"score":0,"onmodel":True,"scary":False,"issue":""}
    for line in (resp or "").replace("|","\n").splitlines():
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
        f"Reply with ONLY a single JSON object, no prose, no code fence:\n"
        f'{{"score": <0-100 overall quality+appeal as a polished kids cartoon>, '
        f'"onmodel": <true/false are the characters correct and not deformed>, '
        f'"scary": <true/false anything scary, ugly, or creepy for toddlers>, '
        f'"issue": "<short note or none>"}}')
    try:
        return parse(vlm(prompt, image_path))
    except Exception as e:
        return {"score":-1,"onmodel":True,"scary":False,"issue":f"vlm error {e}"}

def _is_bad(r, min_score):
    """SCARY is a HARD flag — always re-roll regardless of score. Otherwise: low score or off-model."""
    if r.get("scary"): return True
    if not r.get("onmodel", True): return True
    return r.get("score", 0) >= 0 and r.get("score", 0) < min_score

def _write_report(results, weak, per_shot):
    scores = [r["score"] for r in results.values() if r["score"]>=0]
    report = {"avg_visual":round(sum(scores)/len(scores),1) if scores else 0,
              "n":len(results), "weak":weak, "shots":per_shot}
    try:
        config.WORK.mkdir(parents=True, exist_ok=True)
        (config.WORK/"visual_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"  (could not write visual_report.json: {e})")
    return report

def review_keyframes(min_score=62):
    """Review every rendered keyframe (SHOTS/<id>_key.png). Returns (weak_list, report).

    Backward-compatible: same signature, same return shape (weak items carry shot+score+
    onmodel+scary+issue). Also refreshes WORK/visual_report.json (now incl. a per-shot 'shots'
    list with source='key' for the GUI Visual-QC page)."""
    try:
        ep = json.loads((config.WORK/"episode.json").read_text(encoding="utf-8"))
    except Exception as e:
        print(f"No episode.json to review ({e}); skipping visual review."); return [], {}
    if not ollama_up():
        print("Ollama vision model not reachable; skipping visual review."); return [], {}
    results, weak, per_shot = {}, [], []
    for shot in ep.get("shots", []):
        sid = shot.get("id")
        kf = config.SHOTS / f"{sid}_key.png"
        if not kf.exists(): continue
        r = review_frame(kf, shot.get("chars", []))
        results[sid] = r
        bad = _is_bad(r, min_score)
        flag = "  <-- FLAG" if bad else ""
        print(f"  {sid}: score={r['score']} onmodel={r['onmodel']} scary={r['scary']} "
              f"{r['issue'][:50]}{flag}")
        per_shot.append({"id":sid, "score":r["score"], "onmodel":r["onmodel"],
                         "scary":r["scary"], "issue":r["issue"], "source":"key"})
        if bad: weak.append({"shot":sid, **r})
    report = _write_report(results, weak, per_shot)
    print(f"\nvisual avg={report.get('avg_visual',0)}  flagged {len(weak)} shots for re-render")
    return weak, report

def _ffmpeg():
    """Return path to an ffmpeg binary, or None. Prefers PATH, then engine bundle if present."""
    p = shutil.which("ffmpeg")
    if p: return p
    try:
        cand = config.ENGINE / "ffmpeg" / "bin" / "ffmpeg.exe"
        if cand.exists(): return str(cand)
    except Exception: pass
    return None

def _middle_frame(mp4, ffmpeg, out_png, nframes=None):
    """Extract the MIDDLE frame of an mp4 to out_png via ffmpeg. Returns True on success."""
    # Seek to ~half the configured shot duration; robust even if we can't probe the file.
    secs = getattr(config, "SHOT_SECONDS", 3) or 3
    mid = max(0.0, float(secs) / 2.0)
    cmd = [ffmpeg, "-y", "-ss", f"{mid:.2f}", "-i", str(mp4),
           "-frames:v", "1", "-q:v", "2", str(out_png)]
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=60, check=False)
        return out_png.exists() and out_png.stat().st_size > 0
    except Exception:
        return False

def review_clips(min_score=60):
    """Review the MIDDLE frame of each rendered clip (SHOTS/<id>.mp4) with the same VLM check.

    Catches motion-frame problems a static keyframe can't show (e.g. a limb deforming mid-tween).
    Optional & safe: skips entirely if there are no clips, no ffmpeg, or Ollama is down. Returns
    (weak_list, report) and MERGES clip results into WORK/visual_report.json (source='clip').

    Honest limit: this samples ONE interior frame per clip, not every frame — it spot-checks
    motion, it doesn't fully QC the animation."""
    try:
        ep = json.loads((config.WORK/"episode.json").read_text(encoding="utf-8"))
    except Exception as e:
        print(f"No episode.json to review ({e}); skipping clip review."); return [], {}
    if not ollama_up():
        print("Ollama vision model not reachable; skipping clip review."); return [], {}
    ffmpeg = _ffmpeg()
    if not ffmpeg:
        print("ffmpeg not found; skipping clip review (keyframe review still covers stills)."); return [], {}
    clips = [s for s in ep.get("shots", []) if (config.SHOTS / f"{s.get('id')}.mp4").exists()]
    if not clips:
        print("No rendered clips (.mp4) to review; skipping clip review."); return [], {}

    # Preserve any existing keyframe results in the report and merge clip rows in.
    existing = {}
    try:
        rep = json.loads((config.WORK/"visual_report.json").read_text(encoding="utf-8"))
        for row in rep.get("shots", []):
            if isinstance(row, dict) and "id" in row:
                existing[(row["id"], row.get("source","key"))] = row
    except Exception:
        pass

    results, weak, clip_rows = {}, [], []
    tmpdir = pathlib.Path(tempfile.mkdtemp(prefix="bernie_clipqc_"))
    try:
        for shot in clips:
            sid = shot.get("id")
            mp4 = config.SHOTS / f"{sid}.mp4"
            png = tmpdir / f"{sid}_mid.png"
            if not _middle_frame(mp4, ffmpeg, png):
                print(f"  {sid}: (could not extract middle frame; skipped)"); continue
            r = review_frame(png, shot.get("chars", []))
            results[sid] = r
            bad = _is_bad(r, min_score)
            flag = "  <-- FLAG" if bad else ""
            print(f"  {sid} [clip]: score={r['score']} onmodel={r['onmodel']} scary={r['scary']} "
                  f"{r['issue'][:50]}{flag}")
            clip_rows.append({"id":sid, "score":r["score"], "onmodel":r["onmodel"],
                              "scary":r["scary"], "issue":r["issue"], "source":"clip"})
            if bad: weak.append({"shot":sid, "source":"clip", **r})
    finally:
        try: shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception: pass

    # Merge: keep existing key rows, replace/add clip rows.
    merged = {}
    for (sid, src), row in existing.items():
        merged[(sid, src)] = row
    for row in clip_rows:
        merged[(row["id"], "clip")] = row
    per_shot = list(merged.values())
    report = _write_report(results, weak, per_shot)
    print(f"\nclip visual avg={report.get('avg_visual',0)}  flagged {len(weak)} clips for re-render")
    return weak, report

if __name__ == "__main__":
    review_keyframes()
    review_clips()
