"""Curate a character-LoRA training dataset from the episode's rendered keyframes.

HONEST SCOPE: a character LoRA is the single biggest *real* consistency lever in
this pipeline -- it teaches the base model what "Bernie" actually looks like so he
stops drifting frame to frame. But it makes the character CONSISTENT, not RIGGED:
the downstream Wan i2v motion stays soft AI-video, not a posed/rigged 3D puppet.
This module only BUILDS the dataset (images + caption .txt files + a manifest);
the long multi-hour GPU training run lives in lora_train.py.

Public API:
    build(character="bernie", slot="", min_score=66, limit=60) -> pathlib.Path
        Copy usable keyframes into config.DATASET/<character>/, write a caption
        .txt beside each, write manifest.json, and return the dataset dir.
        Never raises; if there are no keyframes it prints guidance and still
        returns the (empty) dataset dir.
"""
import sys
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import json
import shutil
import pathlib

# Make 'import config' work from the bernie/ dir.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import config  # noqa: E402

# Optional: reuse the canonical character descriptions for nicer captions.
# Guarded so a missing/partial characters.py never breaks dataset building.
try:
    import characters as _characters  # noqa: E402
except Exception:
    _characters = None

# Short, training-friendly trigger-word descriptions per character. The caption's
# leading token is the LoRA "trigger word" (the bare character name) followed by a
# compact look description -- captions intentionally describe what is CONSTANT
# (the character) and leave the per-image specifics ("<action>") to vary.
_CHAR_CAPTION = {
    "bernie": "bernie, a cute stylized 3D bernese mountain dog puppy, black and white fluffy fur, "
              "red bandana, big expressive eyes",
    "pip":    "pip, a tiny cute red ladybug with black spots and springy antennae",
    "tumble": "tumble, a cute chubby teal-green stegosaurus with soft-yellow back plates",
    "rosie":  "rosie, a shy lavender-pink baby triceratops with a little daisy",
    "sky":    "sky, a sleek sky-blue pteranodon with goggles",
    "rex":    "grandpa rex, a big soft gentle green t-rex with a cozy scarf",
    "maple":  "maple, a kind old tortoise with gold spectacles",
}


def _caption_for(character):
    """Return the constant caption prefix for a character.

    Prefers the hand-written short caption above; falls back to the canonical
    characters.py description (lowercased, trimmed); finally a generic line.
    """
    c = (character or "bernie").lower().strip()
    if c in _CHAR_CAPTION:
        return _CHAR_CAPTION[c]
    if _characters is not None:
        desc = ""
        try:
            desc = _characters.CHARS.get(c.upper(), {}).get("desc", "")
        except Exception:
            desc = ""
        if desc:
            # compress the long canonical string to a usable caption
            short = desc.split(",")
            short = ", ".join(s.strip() for s in short[:4])
            return f"{c}, {short}".lower()
    return f"{c}, a cute stylized 3D cartoon character, big expressive eyes"


def _work_dir(slot):
    """Resolve the WORK dir for an explicit slot (defaults to config.WORK)."""
    if not slot:
        return config.WORK
    try:
        return config.STORAGE / ("work_" + slot)
    except Exception:
        return config.WORK


def _good_shot_ids(work_dir, min_score):
    """Return (ids_set_or_None, weak_ids_set).

    Reads WORK/visual_report.json if present. The visual report stores a list of
    WEAK shots (under "weak", each with "shot" + "score"); shots NOT in that list
    passed review. We therefore treat 'good' = every keyframe that is NOT flagged
    weak. If no report exists, return (None, set()) meaning "use all keyframes".
    Never raises.
    """
    rep = work_dir / "visual_report.json"
    if not rep.exists():
        return None, set()
    try:
        data = json.loads(rep.read_text(encoding="utf-8"))
    except Exception:
        return None, set()
    weak_ids = set()
    for w in data.get("weak", []) or []:
        try:
            sid = w.get("shot")
            sc = w.get("score", 0)
            # a weak entry below min_score (or scary/off-model) is excluded
            if sid and (sc < 0 or sc < min_score or w.get("scary") or (not w.get("onmodel", True))):
                weak_ids.add(sid)
        except Exception:
            continue
    return "have_report", weak_ids


def _shot_action(work_dir, sid):
    """Best-effort: pull a short '<action>' for a shot from episode.json.

    Uses the shot's 'motion' (preferred) or a trimmed 'positive'. Returns "" if
    unavailable. Never raises.
    """
    ep_path = work_dir / "episode.json"
    if not ep_path.exists():
        return ""
    try:
        ep = json.loads(ep_path.read_text(encoding="utf-8"))
    except Exception:
        return ""
    for shot in ep.get("shots", []):
        if shot.get("id") == sid:
            action = (shot.get("motion") or "").strip()
            if not action:
                pos = (shot.get("positive") or "").strip()
                action = pos.split(".")[0][:80].strip()
            # keep captions short and clean
            return action.replace("\n", " ").strip()[:120]
    return ""


def build(character="bernie", slot="", min_score=66, limit=60):
    """Curate approved keyframes into config.DATASET/<character>/.

    For each usable SHOTS/<id>_key.png:
      - copy it into the dataset dir as <id>.png
      - write <id>.txt beside it: "<char caption>, <action>"
    Prefers keyframes that passed WORK/visual_report.json (>= min_score, on-model,
    not scary); if no report exists, uses ALL keyframes. Writes manifest.json.

    Returns the dataset directory (always), never raises.
    """
    character = (character or "bernie").lower().strip()
    work_dir = _work_dir(slot)
    shots_dir = work_dir / "shots" if slot else config.SHOTS

    ds_dir = config.DATASET / character
    try:
        ds_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        print(f"[lora_dataset] could not create dataset dir {ds_dir}: {e}")
        return ds_dir

    caption_prefix = _caption_for(character)

    # find candidate keyframes
    keyframes = []
    try:
        if shots_dir.exists():
            keyframes = sorted(shots_dir.glob("*_key.png"))
    except Exception:
        keyframes = []

    if not keyframes:
        print("[lora_dataset] No keyframes found at", shots_dir)
        print("  -> Render an episode first (keyframes are written to SHOTS/<id>_key.png),")
        print("     then re-run dataset build. 20-60 good, on-model frames make a solid LoRA.")
        _write_manifest(ds_dir, character, str(shots_dir), 0, min_score, limit)
        return ds_dir

    mode, weak_ids = _good_shot_ids(work_dir, min_score)
    used_report = mode is not None

    copied = 0
    selected = []
    for kf in keyframes:
        if copied >= max(1, int(limit)):
            break
        sid = kf.name[:-len("_key.png")]  # strip suffix -> shot id
        if used_report and sid in weak_ids:
            continue  # skip flagged-weak frames when we have a report
        action = _shot_action(work_dir, sid)
        caption = caption_prefix if not action else f"{caption_prefix}, {action}"
        img_dst = ds_dir / f"{sid}.png"
        txt_dst = ds_dir / f"{sid}.txt"
        try:
            shutil.copy(str(kf), str(img_dst))
            txt_dst.write_text(caption, encoding="utf-8")
            copied += 1
            selected.append(sid)
        except Exception as e:
            print(f"[lora_dataset] skip {sid}: {e}")
            continue

    _write_manifest(ds_dir, character, str(shots_dir), copied, min_score, limit,
                    selected=selected, used_report=used_report)

    if copied == 0:
        print("[lora_dataset] Found keyframes but none qualified (all flagged weak?).")
        print(f"  -> Lower min_score (currently {min_score}) or render better frames, then re-run.")
    else:
        print(f"[lora_dataset] {copied} caption pairs -> {ds_dir}")
        if copied < 12:
            print(f"  note: {copied} images is on the thin side; 20-60 on-model frames train best.")
    return ds_dir


def _write_manifest(ds_dir, character, source, count, min_score, limit,
                    selected=None, used_report=False):
    """Write dataset/manifest.json. Never raises."""
    manifest = {
        "character": character,
        "count": count,
        "source": source,
        "min_score": min_score,
        "limit": limit,
        "used_visual_report": bool(used_report),
        "selected": selected or [],
        "note": ("LoRA dataset of curated keyframes. Each <id>.png has a matching <id>.txt "
                 "caption whose first token is the trigger word. Train with lora_train.py."),
    }
    try:
        (ds_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[lora_dataset] could not write manifest: {e}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Build a character-LoRA dataset from rendered keyframes.")
    ap.add_argument("--character", default="bernie")
    ap.add_argument("--slot", default=config.SLOT)
    ap.add_argument("--min-score", type=int, default=66)
    ap.add_argument("--limit", type=int, default=60)
    a = ap.parse_args()
    d = build(character=a.character, slot=a.slot, min_score=a.min_score, limit=a.limit)
    print("dataset dir:", d)
