"""Generate Episode 2 — 'The Shy Triceratops' — a long (~14-18 min) shot list via the free LLM
chain, schema-compatible with the render pipeline. Staged generation (outline -> per-scene shots)
with strict validation so only canonical characters/locations survive. Writes episode.json into
the current slot's work dir; the rest of the pipeline (agency -> voices -> songs -> render) then
runs on it unchanged."""
import sys, pathlib, json, time, re
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import config, director
from characters import CHARS, LOCATIONS, NEG
from showrunner import build_positive

VALID_CHARS = set(CHARS.keys())
VALID_LOCS  = set(LOCATIONS.keys())
SPEAKERS    = [c for c in CHARS if CHARS[c]["voice"]]   # who can talk
BEATS = ["open","theme","calm","tender","brave","wonder","suspense","reveal","warm","sad",
         "song1","song2","song3","fact","resolve","montage","arrive","funny"]

PREMISE = (
 "EPISODE 2: 'The Shy Triceratops'. Bernie the brave Bernese Mountain Dog puppy and Pip the tiny "
 "ladybug return to Dino Valley to make friends with ROSIE, a sweet shy baby Triceratops who hides "
 "in her fern hollow because she thinks her loud honking sneezes scare everyone away. The Valley "
 "Pals (Tumble the goofy Stegosaurus, Sky the cool Pteranodon, gentle Grandpa Rex, wise old Maple) "
 "go on a gentle adventure to find the legendary GIGGLE FLOWERS in the Giggle Grove to cheer Rosie "
 "up — crossing the Sunny River on stepping stones, picking berries, exploring the Tall Trees. "
 "Rosie must find the courage to come out of hiding and help her new friends. Warm comedy, a "
 "scary-but-safe wobble crossing the river, an emotional heartfelt moment where Rosie blooms with "
 "confidence, a triumphant finish. LESSON: being shy is okay, and real friends help you bloom. "
 "DINO FACT: a Triceratops's frill and three horns helped protect it and show off — they're "
 "special, not scary. Include the theme song, a tender Rosie courage song, and the 'Valley Pals' "
 "team cheer. End with a cozy wrap-up + a teaser for the next adventure.")

ROSTER = ("Canonical characters (use these exact TOKENS): BERNIE (hero puppy), PIP (tiny ladybug, "
 "excitable), ROSIE (shy baby Triceratops - the star of this episode), TUMBLE (goofy Stegosaurus), "
 "SKY (cool Pteranodon), REX (Grandpa Rex, gentle giant T-Rex), MAPLE (wise old tortoise mentor), "
 "SEAGULL, NARR (narrator).")
LOCS_TXT = "Allowed location KEYS: " + ", ".join(VALID_LOCS)

def _clean_chars(lst):
    out = [c for c in (lst or []) if c in VALID_CHARS]
    return out or ["BERNIE"]

def _clean_dialogue(dlg):
    out = []
    for d in (dlg or []):
        sp = (d.get("speaker") or "").strip().upper()
        ln = (d.get("line") or "").strip()
        if sp not in VALID_CHARS: sp = "NARR"
        if not CHARS.get(sp, {}).get("voice"): sp = "NARR"
        if ln: out.append({"speaker": sp, "line": ln[:240]})
    return out

def gen_outline(n_scenes=12):
    sys_p = ("You are the Head Story Writer for a premium preschool cartoon. You structure long "
             "episodes into vivid scenes with constant momentum and zero filler.")
    user_p = (f"{PREMISE}\n\n{ROSTER}\n{LOCS_TXT}\n\n"
        f"Write a {n_scenes}-scene outline for this ~16-minute episode. Strong hook, clear act "
        f"structure, comedy + heart + a song or two, satisfying payoff and a teaser. Reply ONLY "
        f'as JSON: {{"scenes":[{{"title":"...","location":"<one location KEY>",'
        f'"chars":["TOKEN",...],"beat":"<one of {BEATS}>","summary":"2-3 sentences of what '
        f'happens, with the emotional beat"}}]}}')
    r = director.extract_json(director.llm(sys_p, user_p, max_tokens=3000, temperature=0.8))
    scenes = r.get("scenes", [])
    for s in scenes:
        if s.get("location") not in VALID_LOCS: s["location"] = "VALLEY"
        s["chars"] = _clean_chars(s.get("chars"))
        if s.get("beat") not in BEATS: s["beat"] = "calm"
    return scenes

def gen_scene_shots(scene, idx, total, prev_summary):
    sys_p = ("You are a master children's-TV writer-director turning a scene into a vivid shot list. "
             "Each shot has clear staging (for image generation), camera motion, and short, funny or "
             "heartfelt kid-friendly dialogue. Keep characters perfectly in voice. No filler.")
    loc_desc = LOCATIONS[scene["location"]]
    user_p = (f"{ROSTER}\n\nSCENE {idx}/{total}: '{scene['title']}' | location={scene['location']} "
        f"({loc_desc}) | mood/beat={scene['beat']} | characters={scene['chars']}\n"
        f"What happens: {scene['summary']}\nPrevious scene: {prev_summary}\n\n"
        f"Break this scene into 8 to 11 SHOTS. Each shot: vivid ACTION (concrete staging, "
        f"expressions, what we SEE — becomes an image prompt; do NOT name camera moves here), "
        f"MOTION (one short camera/movement phrase), and 1-3 short DIALOGUE lines (speaker must be "
        f"a TOKEN who can talk; MOST shots should have dialogue to keep kids engaged). Keep dialogue "
        f"snappy, warm and age 2-6 friendly. Reply ONLY as JSON: "
        f'{{"shots":[{{"action":"...","motion":"...","beat":"<one of {BEATS}>",'
        f'"chars":["TOKEN",...],"dialogue":[{{"speaker":"TOKEN","line":"..."}}]}}]}}')
    r = director.extract_json(director.llm(sys_p, user_p, max_tokens=4096, temperature=0.85))
    return r.get("shots", [])

def build(target_scenes=12):
    print(f"Generating Ep2 outline ({target_scenes} scenes)...")
    scenes = gen_outline(target_scenes)
    print(f"  outline: {len(scenes)} scenes")
    all_shots = []
    prev = "(start of episode)"
    for i, scene in enumerate(scenes, 1):
        for attempt in range(3):
            try:
                shots = gen_scene_shots(scene, i, len(scenes), prev)
                if shots: break
            except Exception as e:
                print(f"  scene {i} retry {attempt+1}: {e}"); time.sleep(2); shots = []
        print(f"  scene {i} '{scene['title'][:30]}': {len(shots)} shots")
        for sh in shots:
            chars = _clean_chars(sh.get("chars") or scene["chars"])
            loc = scene["location"]
            action = (sh.get("action") or "").strip()
            if not action: continue
            beat = sh.get("beat") if sh.get("beat") in BEATS else scene["beat"]
            all_shots.append(dict(
                location=loc, chars=chars, action=action,
                motion=(sh.get("motion") or "gentle camera move").strip(),
                dialogue=_clean_dialogue(sh.get("dialogue")), beat=beat))
        prev = scene["summary"]
    # finalize ids + prompts
    shots = []
    for n, sh in enumerate(all_shots, 1):
        sh["id"] = f"s{n:03d}"
        sh["positive"] = build_positive(sh["location"], sh["chars"], sh["action"])
        sh["negative"] = NEG
        shots.append(sh)
    ep = dict(title="The Shy Triceratops", episode=2, fps=config.FPS, shots=shots)
    return ep

def main(target_scenes=12):
    ep = build(target_scenes)
    out = config.WORK / "episode.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(ep, indent=2), encoding="utf-8")
    nd = sum(len(s["dialogue"]) for s in ep["shots"])
    print(f"\nEp2 written: {len(ep['shots'])} shots, {nd} dialogue lines -> {out}")
    return ep

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(); ap.add_argument("--scenes", type=int, default=12)
    main(ap.parse_args().scenes)
