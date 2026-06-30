"""Fully-autonomous SERIES MODE.

Picks the next un-made episode from the built-in Season 1 plan, builds it end-to-end (LLM story
-> 22-agent direction -> voices -> songs -> render -> visual review -> assemble -> music), marks
it done, and moves to the next — automatically, forever, until the season is complete.

Resumable at every level: each episode runs as its own subprocess (isolated work slot), the render
inside it resumes via progress.json, and series_state.json tracks finished episodes — so a crash or
PC restart just continues where it left off. Run:  python make.py --series
"""
import sys, os, json, time, subprocess, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import config

REPO = config.REPO
STATE = config.HOME / "series_state.json"

# --- Season 1 plan: each pal gets a spotlight; every episode has a gentle lesson + a real dino/nature fact ---
SEASON = [
 dict(n=1,  slug="ep1",  name="Bernie_Ep1",  scenes=12, title="Bernie Finds the Valley",
   premise="Bernie the brave Bernese Mountain Dog puppy and Pip the ladybug follow a mysterious message to a hidden valley and meet Tumble, a goofy clumsy Stegosaurus who thinks he's too scary to have friends. Lesson: a stranger is just a friend you haven't met — say hello. Dino fact: a Stegosaurus's back-plates soaked up the morning sun to keep it warm."),
 dict(n=2,  slug="ep2",  name="Bernie_Ep2",  scenes=16, title="The Shy Triceratops",
   premise="The Valley Pals go on a quest to find the legendary Giggle Flowers to cheer up Rosie, a sweet shy baby Triceratops who hides because she thinks her honking sneezes scare everyone. Lesson: being shy is okay, and good friends help you bloom. Dino fact: a Triceratops's frill and three horns helped it stay safe and say hello — special, not scary."),
 dict(n=3,  slug="ep3",  name="Bernie_Ep3",  scenes=14, title="Sky's Big Race",
   premise="Sky the cool Pteranodon challenges everyone to a big flying race but discovers that teamwork and cheering friends on feels better than showing off. Lesson: it's more fun to lift others up than to win alone. Dino fact: Pteranodon had huge light wings and glided on the wind like a paper airplane."),
 dict(n=4,  slug="ep4",  name="Bernie_Ep4",  scenes=14, title="Grandpa Rex's Lost Scarf",
   premise="A gust of wind carries off Grandpa Rex's cozy scarf and the pals search the whole valley to bring it back, learning to be patient and gentle with their kind elder. Lesson: helping and patience. Dino fact: a T-Rex had tiny arms but a giant nose and could smell things very far away."),
 dict(n=5,  slug="ep5",  name="Bernie_Ep5",  scenes=14, title="The Counting Berries",
   premise="The pals pick a giant pile of berries for a picnic and must count and share them so everyone gets a fair amount, even tiny Pip. Lesson: sharing and fairness, with gentle counting. Dino fact: many dinosaurs were plant-eaters who ate berries, leaves and ferns all day long."),
 dict(n=6,  slug="ep6",  name="Bernie_Ep6",  scenes=14, title="The Rainy Day Cave",
   premise="A sudden rainstorm sends the Valley Pals into the cozy Whispering Cave, where they turn a boring wait into the best afternoon ever with games, echoes and shadow puppets. Lesson: you can make your own fun and stay positive. Dino fact: caves make echoes because sound bounces off the smooth rock walls."),
 dict(n=7,  slug="ep7",  name="Bernie_Ep7",  scenes=14, title="Pip's Big Adventure",
   premise="When the pals are too big to reach a stuck baby bird in a tiny hole, it's up to little Pip the ladybug to save the day and prove that small friends are mighty too. Lesson: everyone is important, no matter how small. Dino fact: ladybugs are tiny helpers that keep gardens and plants healthy."),
 dict(n=8,  slug="ep8",  name="Bernie_Ep8",  scenes=14, title="Maple's Storytime Mystery",
   premise="Wise old Maple the tortoise is telling a story when clues to a real little mystery start appearing in the valley, and the pals must listen carefully and be patient to solve it together. Lesson: good listening and patience. Dino fact: tortoises live a very, very long time and do everything slow and steady."),
 dict(n=9,  slug="ep9",  name="Bernie_Ep9",  scenes=14, title="The Lost Little Dino",
   premise="The pals find a lost, sniffly baby dinosaur far from home and gently work together to help it find its family before sundown. Lesson: kindness and helping someone in need. Dino fact: many dinosaurs were caring parents who looked after their babies in cozy nests."),
 dict(n=10, slug="ep10", name="Bernie_Ep10", scenes=14, title="Tumble's Bouncy Trouble",
   premise="Tumble's wiggly tail keeps bonking things and knocking over the festival decorations, until the pals help him see that his big bouncy tail is actually perfect for something wonderful. Lesson: your differences are special gifts. Dino fact: a Stegosaurus's tail helped it balance and feel safe (here it's gentle and friendly)."),
 dict(n=11, slug="ep11", name="Bernie_Ep11", scenes=14, title="The Sleepy Volcano",
   premise="The pals hike to a warm, gently rumbling friendly volcano to roast marshmallows, and Rosie learns to face a little nervousness with her friends beside her. Lesson: facing small fears with friends. Dino fact: volcanoes are mountains that can be warm inside, and dinosaurs lived near them long ago."),
 dict(n=12, slug="ep12", name="Bernie_Ep12", scenes=16, title="The Valley Festival",
   premise="Season finale: the whole valley throws a giant friendship festival where every pal shows off the special thing that makes them them, in a big musical celebration. Lesson: friendship and community make everything brighter. Dino fact: a joyful recap — frills, plates, wings, tiny arms and big hearts all together."),
]

def _state():
    if STATE.exists():
        try: return json.loads(STATE.read_text(encoding="utf-8"))
        except Exception: pass
    return {"done": [], "history": []}

def _save(st): STATE.write_text(json.dumps(st, indent=2), encoding="utf-8")

def _is_done(ep):
    out = config.OUT / f"{ep['name']}.mp4"
    return out.exists() or ep["slug"] in _state()["done"]

def next_episode():
    for ep in SEASON:
        if not _is_done(ep): return ep
    return None

def build(ep):
    """Build one episode as an isolated subprocess (resumable)."""
    print(f"\n################  EPISODE {ep['n']}: {ep['title']}  ################", flush=True)
    env = {**os.environ, "BERNIE_SLOT": ep["slug"], "BERNIE_EP": ep["name"], "PYTHONUTF8": "1"}
    cmd = [sys.executable, str(REPO / "make.py"),
           "--slot", ep["slug"], "--name", ep["name"],
           "--generate", ep["premise"], "--scenes", str(ep["scenes"])]
    r = subprocess.run(cmd, env=env, cwd=str(REPO))
    ok = (config.OUT / f"{ep['name']}.mp4").exists()
    return ok, r.returncode

def _maybe_auto_lora(ep):
    """Opt-in (BERNIE_AUTO_LORA): once an episode has produced on-model keyframes, train a
    Bernie character LoRA and ACTIVATE it (via BERNIE_LORA) for the rest of the season, so
    later episodes are more consistent — fully hands-off. Safe + honest:
      * default OFF (no behavior change unless BERNIE_AUTO_LORA=1);
      * if a LoRA is already trained/active, just reuse it (no re-train);
      * if no trainer is installed, it stages the kohya job and continues WITHOUT a LoRA
        (never blocks the season on a trainer the user doesn't have);
      * training, when it does run, is a long one-time GPU job — by design, and opt-in."""
    if not getattr(config, "AUTO_LORA", False) or os.environ.get("BERNIE_LORA"):
        return
    lora_file = config.LORA_OUT / "bernie_lora.safetensors"
    if lora_file.exists():
        os.environ["BERNIE_LORA"] = lora_file.name
        print(f"[series] activating existing LoRA {lora_file.name} for the rest of the season.", flush=True)
        return
    try:
        import lora_dataset, lora_train
        if lora_train.detect_trainer() is None:
            print("[series] AUTO_LORA on but no trainer installed -> staging the kohya job and "
                  "continuing without a LoRA (see LORA_OUT/README_LORA.txt).", flush=True)
            lora_train.train(character="bernie")   # writes the ready-to-run job, returns None
            return
        print("[series] AUTO_LORA: building dataset + training the Bernie LoRA (one-time, LONG GPU job)...", flush=True)
        lora_dataset.build(character="bernie", slot=ep["slug"])
        path = lora_train.train(character="bernie")
        if path and pathlib.Path(path).exists():
            os.environ["BERNIE_LORA"] = pathlib.Path(path).name
            print(f"[series] ✅ LoRA trained + activated: {path} — later episodes lock to a consistent Bernie.", flush=True)
    except Exception as e:
        print(f"[series] auto-LoRA skipped: {e}", flush=True)


def run_series(max_episodes=None):
    print("########## BERNIE STUDIO — AUTONOMOUS SERIES MODE ##########", flush=True)
    print(config.summary(), flush=True)
    made = 0
    while True:
        ep = next_episode()
        if ep is None:
            print("\n🎉 SEASON COMPLETE — all episodes made!", flush=True); break
        if max_episodes and made >= max_episodes:
            print(f"\nreached max_episodes={max_episodes}; stopping.", flush=True); break
        ok, rc = build(ep)
        st = _state()
        st["history"].append(dict(slug=ep["slug"], name=ep["name"], ok=ok, rc=rc, t=time.time()))
        if ok and ep["slug"] not in st["done"]:
            st["done"].append(ep["slug"])
            print(f"✅ EPISODE {ep['n']} DONE: {config.OUT / (ep['name']+'.mp4')}", flush=True)
            _maybe_auto_lora(ep)
        else:
            print(f"⚠️ episode {ep['n']} ({ep['slug']}) did not finish (rc={rc}); will retry on next pass.", flush=True)
            time.sleep(10)
        _save(st)
        made += 1

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(); ap.add_argument("--max", type=int, default=None)
    run_series(max_episodes=ap.parse_args().max)
