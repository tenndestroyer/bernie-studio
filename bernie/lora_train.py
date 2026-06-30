"""Character-LoRA training: detect a local trainer, or emit a ready-to-run kohya_ss job.

HONEST SCOPE -- read this before you expect magic:
  * A character LoRA makes the character CONSISTENT (same face/markings/colors shot
    to shot). It does NOT make it RIGGED. The downstream Wan i2v motion is still soft
    AI-video, not a posed/rigged 3D puppet. LoRA fixes "who", not "how it moves".
  * Real training is a LONG GPU JOB (often 1-4+ hours on a consumer GPU) and needs an
    actual trainer (kohya_ss, or a ComfyUI LoRA-training node) PLUS the base model
    weights already downloaded. This module does NOT secretly train in-process.
  * If a trainer is detected we wire up and launch it. If not, we WRITE a complete,
    ready-to-run kohya_ss config + train.bat + README so the user can install the
    trainer and kick off the multi-hour run themselves. Either way: never raises.

Public API:
  detect_trainer() -> str | None
  train(character="bernie", steps=1200, rank=16, base="flux") -> pathlib.Path | None
  main()   # argparse CLI: --character --steps --rank ; build() then train()
"""
import sys
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import os
import json
import shutil
import pathlib
import subprocess

# Make 'import config' work from the bernie/ dir.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import config  # noqa: E402

try:
    import lora_dataset  # noqa: E402
except Exception:
    lora_dataset = None

try:
    import comfy  # noqa: E402
except Exception:
    comfy = None


# ---------------------------------------------------------------------------
# trainer detection
# ---------------------------------------------------------------------------
def detect_trainer():
    """Look for a usable LoRA trainer. Returns a short id string or None.

    Detected, in priority order:
      "comfy-train"  : a ComfyUI training node (FluxTrainModelSelect / TrainLoraNode /
                       the kohya-in-Comfy custom nodes) is installed in config.ENGINE.
      "kohya"        : a kohya_ss checkout / sd-scripts is on disk near ENGINE/HOME or on PATH.
    Never raises; returns None if nothing is found.
    """
    # 1) ComfyUI training node? Scan custom_nodes folder names + any object_info if server is up.
    try:
        cn = config.ENGINE / "custom_nodes"
        if cn.exists():
            names = " ".join(p.name.lower() for p in cn.iterdir())
            if any(k in names for k in ("train", "kohya", "flux-trainer", "fluxtrainer", "lora_train")):
                return "comfy-train"
    except Exception:
        pass
    # if a comfy server is already up, ask it which node classes exist
    try:
        if comfy is not None and comfy.server_up():
            info = comfy._get("/object_info")
            keys = " ".join(info.keys()).lower()
            if any(k in keys for k in ("trainlora", "fluxtrain", "kohya", "loratraining")):
                return "comfy-train"
    except Exception:
        pass

    # 2) kohya_ss / sd-scripts checkout on disk near our paths?
    candidates = []
    for base in (config.HOME, config.ENGINE.parent, config.REPO):
        try:
            for name in ("kohya_ss", "sd-scripts", "kohya-ss", "sd_scripts"):
                candidates.append(base / name)
        except Exception:
            pass
    for c in candidates:
        try:
            if c.exists() and (
                (c / "train_network.py").exists()
                or (c / "sd-scripts" / "train_network.py").exists()
                or (c / "flux_train_network.py").exists()
                or (c / "sd-scripts" / "flux_train_network.py").exists()
            ):
                return "kohya"
        except Exception:
            continue

    # 3) kohya entrypoint on PATH?
    for exe in ("kohya_ss", "kohya", "accelerate"):
        if shutil.which(exe):
            # accelerate alone isn't a trainer, but a kohya/sd-scripts presence with it is handled above.
            if exe != "accelerate":
                return "kohya"
    return None


def _kohya_script_path():
    """Return the path to flux/sd train_network.py if a kohya checkout exists, else None."""
    for base in (config.HOME, config.ENGINE.parent, config.REPO):
        for name in ("kohya_ss", "sd-scripts", "kohya-ss", "sd_scripts"):
            for sub in ("", "sd-scripts"):
                root = base / name / sub if sub else base / name
                for script in ("flux_train_network.py", "train_network.py"):
                    p = root / script
                    try:
                        if p.exists():
                            return p
                    except Exception:
                        continue
    return None


# ---------------------------------------------------------------------------
# training
# ---------------------------------------------------------------------------
def train(character="bernie", steps=1200, rank=16, base="flux"):
    """Train (or stage) a character LoRA.

    If a trainer is detected -> build + launch it, producing
        config.LORA_OUT/<character>_lora.safetensors  (returned).
    If NO trainer -> write a ready-to-run kohya_ss job (toml + train.bat + README)
        into config.LORA_OUT, print next steps, and return None.

    Never raises.
    """
    character = (character or "bernie").lower().strip()
    try:
        config.LORA_OUT.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        print(f"[lora_train] could not create LORA_OUT {config.LORA_OUT}: {e}")

    ds_dir = config.DATASET / character
    n_imgs = 0
    try:
        n_imgs = len(list(ds_dir.glob("*.png")))
    except Exception:
        pass
    if n_imgs == 0:
        print(f"[lora_train] dataset {ds_dir} has no images.")
        print("  -> run lora_dataset.build() first (or this module's main()).")
        # still emit the kohya job so the user has the scaffold ready
    out_path = config.LORA_OUT / f"{character}_lora.safetensors"

    trainer = detect_trainer()
    if trainer == "comfy-train":
        result = _train_comfy(character, steps, rank, base, ds_dir, out_path)
        if result is not None:
            return result
        print("[lora_train] ComfyUI train node detected but the run could not be wired up;")
        print("  falling back to writing a kohya_ss job you can launch manually.")
    elif trainer == "kohya":
        result = _train_kohya(character, steps, rank, base, ds_dir, out_path)
        if result is not None:
            return result
        print("[lora_train] kohya checkout found but launch failed; writing the job files so")
        print("  you can run it by hand (see README_LORA.txt).")

    # No trainer (or launch failed): write the complete ready-to-run job + guidance.
    _write_kohya_job(character, steps, rank, base, ds_dir, out_path)
    return None


def _train_kohya(character, steps, rank, base, ds_dir, out_path):
    """Launch a detected kohya/sd-scripts train_network.py. Returns out_path or None.

    Honest: this kicks off a multi-hour GPU process. We always WRITE the toml/bat
    first (so a manual re-run is trivial), then attempt to launch accelerate. If the
    launch can't start or the output never appears, we return None.
    """
    script = _kohya_script_path()
    if script is None:
        return None
    toml_path, _bat, _readme = _write_kohya_job(character, steps, rank, base, ds_dir, out_path)

    accel = shutil.which("accelerate")
    py = shutil.which("python") or sys.executable
    if accel:
        cmd = [accel, "launch", str(script), f"--config_file={toml_path}"]
    else:
        cmd = [py, str(script), f"--config_file={toml_path}"]
    print("[lora_train] launching kohya (this is a LONG multi-hour GPU job)...")
    print("  cmd:", " ".join(cmd))
    try:
        log = open(config.LOGDIR / f"lora_train_{character}.log", "w", encoding="utf-8")
    except Exception:
        log = subprocess.DEVNULL
    try:
        proc = subprocess.run(cmd, cwd=str(script.parent), stdout=log,
                              stderr=subprocess.STDOUT)
    except Exception as e:
        print(f"[lora_train] could not launch kohya: {e}")
        print("  -> run train.bat in", out_path.parent, "manually (see README_LORA.txt).")
        return None
    if getattr(proc, "returncode", 1) == 0 and out_path.exists():
        print(f"[lora_train] DONE -> {out_path}")
        return out_path
    print("[lora_train] kohya run did not produce the .safetensors (rc="
          f"{getattr(proc, 'returncode', '?')}). See logs and README_LORA.txt.")
    return None


def _train_comfy(character, steps, rank, base, ds_dir, out_path):
    """Run a ComfyUI LoRA-training node if present. Returns out_path or None.

    Honest: ComfyUI training-node graphs are node-pack specific (FluxTrainModelSelect,
    TrainLoraNode, kohya-in-Comfy, etc.) and not standardized, so we can't hard-code a
    universally-correct graph. We build a best-effort graph from a discovered class and
    run it; if anything is off we return None and the caller falls back to the kohya job.
    """
    if comfy is None:
        return None
    try:
        if not comfy.server_up():
            comfy.start_server()
        info = comfy._get("/object_info")
    except Exception as e:
        print(f"[lora_train] comfy not reachable for training: {e}")
        return None

    # find a plausible training node class
    train_class = None
    for cls in info.keys():
        cl = cls.lower()
        if ("trainlora" in cl or "loratraining" in cl or "fluxtrain" in cl
                or ("train" in cl and "lora" in cl)):
            train_class = cls
            break
    if train_class is None:
        print("[lora_train] no recognizable Comfy training node class found.")
        return None

    print(f"[lora_train] found Comfy training node '{train_class}'.")
    print("  NOTE: Comfy training graphs are node-pack specific. Building a best-effort")
    print("  graph; if your node expects different inputs, use the kohya job instead.")
    graph = {
        "1": {"class_type": train_class, "inputs": {
            "dataset_path": str(ds_dir),
            "output_name": f"{character}_lora",
            "output_dir": str(config.LORA_OUT),
            "steps": int(steps),
            "rank": int(rank),
            "network_dim": int(rank),
            "learning_rate": 1e-4,
        }},
    }
    try:
        comfy.run(graph, timeout=6 * 3600)  # up to 6h
    except Exception as e:
        print(f"[lora_train] comfy training graph failed: {e}")
        return None
    if out_path.exists():
        print(f"[lora_train] DONE -> {out_path}")
        return out_path
    # node may name the file differently; try to find any new safetensors with our prefix
    try:
        cands = sorted(config.LORA_OUT.glob(f"{character}*.safetensors"))
        if cands:
            print(f"[lora_train] training produced {cands[-1].name}")
            return cands[-1]
    except Exception:
        pass
    print("[lora_train] Comfy run finished but no .safetensors found; falling back to kohya job.")
    return None


# ---------------------------------------------------------------------------
# ready-to-run kohya job writer (no-trainer path)
# ---------------------------------------------------------------------------
def _flux_model_paths():
    """Best-effort absolute paths to the Flux base weights inside the engine."""
    m = config.ENGINE / "models"
    return {
        "pretrained": m / "unet" / "flux1-dev.safetensors",
        "clip_l": m / "clip" / "clip_l.safetensors",
        "t5": m / "clip" / "t5xxl_fp8_e4m3fn.safetensors",
        "ae": m / "vae" / "ae.safetensors",
    }


def _write_kohya_job(character, steps, rank, base, ds_dir, out_path):
    """Write <character>_kohya.toml + train.bat + README_LORA.txt into LORA_OUT.

    Returns (toml_path, bat_path, readme_path). Never raises.
    """
    out_dir = config.LORA_OUT
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    toml_path = out_dir / f"{character}_kohya.toml"
    bat_path = out_dir / f"train_{character}.bat"
    readme_path = out_dir / "README_LORA.txt"

    fm = _flux_model_paths()
    # kohya wants the parent of the image folder as train_data_dir; the image folder
    # itself encodes repeats as "<N>_<name>". We point train_data_dir at the dataset
    # parent and let the README explain the "<repeats>_<character>" subfolder convention.
    train_data_dir = str(ds_dir.parent)

    def _p(path):
        return str(path).replace("\\", "/")

    toml = f'''# kohya_ss / sd-scripts LoRA training config for "{character}" (Flux-dev).
# Generated by bernie/lora_train.py -- edit paths if your install differs.
# HONEST: this is a multi-hour GPU job. It makes the character CONSISTENT, not rigged.

pretrained_model_name_or_path = "{_p(fm["pretrained"])}"
clip_l = "{_p(fm["clip_l"])}"
t5xxl = "{_p(fm["t5"])}"
ae = "{_p(fm["ae"])}"

# Dataset: point at the PARENT of the image folder. kohya reads subfolders named
# "<repeats>_<name>" (e.g. "10_{character}"). See README_LORA.txt for one-line setup.
train_data_dir = "{_p(train_data_dir)}"

output_dir = "{_p(out_dir)}"
output_name = "{character}_lora"
save_model_as = "safetensors"
logging_dir = "{_p(config.LOGDIR)}"

# --- network (LoRA) ---
network_module = "networks.lora_flux"
network_dim = {int(rank)}
network_alpha = {max(1, int(rank) // 2)}

# --- schedule ---
max_train_steps = {int(steps)}
train_batch_size = 1
learning_rate = 1e-4
unet_lr = 1e-4
text_encoder_lr = 0.0
optimizer_type = "adamw8bit"
lr_scheduler = "cosine"
lr_warmup_steps = {max(1, int(steps) // 20)}

# --- resolution / memory (tuned conservative for consumer VRAM) ---
resolution = "768,768"
enable_bucket = true
min_bucket_reso = 512
max_bucket_reso = 1024
cache_latents = true
cache_latents_to_disk = true
gradient_checkpointing = true
mixed_precision = "bf16"
save_precision = "bf16"
sdpa = true
seed = 42

# --- flux specifics ---
apt = false
guidance_scale = 1.0
timestep_sampling = "sigmoid"
model_prediction_type = "raw"
discrete_flow_shift = 3.0
loss_type = "l2"

save_every_n_steps = {max(100, int(steps) // 4)}
'''

    bat = f'''@echo off
REM ---------------------------------------------------------------------------
REM  Train the "{character}" character LoRA (Flux-dev) via kohya_ss / sd-scripts.
REM  THIS IS A LONG GPU JOB (often 1-4+ hours). See README_LORA.txt first.
REM
REM  1) Edit the CALL paths below if your kohya_ss / sd-scripts lives elsewhere.
REM  2) Make sure your dataset folder is renamed to "<repeats>_{character}"
REM     (e.g. 10_{character}) under: {_p(train_data_dir)}
REM ---------------------------------------------------------------------------
setlocal

REM --- EDIT ME: where you installed kohya_ss / sd-scripts ---
set SDSCRIPTS=%USERPROFILE%\\kohya_ss\\sd-scripts

REM Use kohya's own venv python if present, else system python.
set PYEXE=%SDSCRIPTS%\\..\\venv\\Scripts\\python.exe
if not exist "%PYEXE%" set PYEXE=python

echo Starting {character} LoRA training (multi-hour GPU job)...
"%PYEXE%" -m accelerate.commands.launch "%SDSCRIPTS%\\flux_train_network.py" --config_file "{_p(toml_path)}"

echo.
echo Done. Look for {character}_lora.safetensors in:
echo   {_p(out_dir)}
echo Then set BERNIE_LORA={character}_lora.safetensors to use it in renders.
pause
'''

    readme = f'''BERNIE CHARACTER LoRA -- how to actually train it
==================================================

WHAT THIS DOES (and does not)
-----------------------------
A character LoRA teaches the Flux base model exactly what "{character}" looks like,
so the character stays CONSISTENT (same face, markings, colors) shot to shot. It is
the single biggest real consistency lever in this pipeline.

It does NOT rig or pose the character. Motion still comes from Wan i2v and stays soft
AI-video -- think "consistent cute 3D cartoon", not "rigged Pixar puppet".

Training is a LONG GPU JOB: typically 1-4+ hours on a consumer NVIDIA GPU for
{int(steps)} steps at rank {int(rank)}. You need a trainer installed + the Flux base
weights already present (they are, in your ComfyUI models folder).

FILES GENERATED HERE
--------------------
  {toml_path.name}      kohya_ss / sd-scripts config (paths point at your engine + dataset)
  {bat_path.name}   one-click launcher (EDIT the SDSCRIPTS path inside it first)
  README_LORA.txt          this file

STEP 1 -- BUILD THE DATASET (already automated)
-----------------------------------------------
  python bernie\\lora_train.py --character {character}
This runs lora_dataset.build() then this trainer. The dataset lands in:
  {ds_dir}
Each <id>.png has a matching <id>.txt caption (first word = the trigger word "{character}").

STEP 2 -- INSTALL A TRAINER (one-time)
--------------------------------------
kohya_ss (recommended, includes sd-scripts with Flux support):
  git clone https://github.com/bmaltais/kohya_ss
  cd kohya_ss && git submodule update --init --recursive
  setup.bat   (creates a venv and installs torch + deps)
Flux training lives in:  kohya_ss\\sd-scripts\\flux_train_network.py

STEP 3 -- NAME THE IMAGE FOLDER WITH REPEATS
--------------------------------------------
kohya reads a subfolder named "<repeats>_<name>". Rename / copy your dataset folder:
  from:  {ds_dir}
  to:    {ds_dir.parent}\\10_{character}
(10 repeats x your image count is a good starting point.) The .toml's train_data_dir
already points at the PARENT folder ({ds_dir.parent}).

STEP 4 -- RUN IT (the multi-hour part)
--------------------------------------
Edit the SDSCRIPTS path at the top of {bat_path.name}, then double-click it, OR run:
  accelerate launch <kohya>/sd-scripts/flux_train_network.py --config_file "{toml_path}"
Leave it running. Checkpoints save every {max(100, int(steps)//4)} steps into:
  {out_dir}

STEP 5 -- USE THE LoRA
----------------------
When training finishes you'll have:
  {out_path.name}
Turn it on for renders by setting the env var the pipeline already reads:
  set BERNIE_LORA={character}_lora.safetensors
(workflows.flux_keyframe already supports a LoRA; the pipeline passes config.LORA_BERNIE.)

TUNING NOTES
------------
  * Too rigid / artifacts on new poses -> fewer steps or lower rank (rank 8-16).
  * Character not consistent enough     -> more on-model images, more steps (1500-2500).
  * OOM on a small GPU                   -> drop resolution to "512,512" in the .toml.
'''

    for path, text in ((toml_path, toml), (bat_path, bat), (readme_path, readme)):
        try:
            path.write_text(text, encoding="utf-8")
        except Exception as e:
            print(f"[lora_train] could not write {path.name}: {e}")

    print("[lora_train] No live trainer detected -- wrote a ready-to-run kohya_ss job:")
    print("   config :", toml_path)
    print("   launcher:", bat_path)
    print("   guide  :", readme_path)
    print("Next: install kohya_ss, then run the launcher. This is a multi-hour GPU job.")
    print(f"When done, set  BERNIE_LORA={character}_lora.safetensors  to use it in renders.")
    return toml_path, bat_path, readme_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    import argparse
    ap = argparse.ArgumentParser(
        description="Build a character-LoRA dataset and train (or stage) the LoRA.")
    ap.add_argument("--character", default="bernie")
    ap.add_argument("--steps", type=int, default=1200)
    ap.add_argument("--rank", type=int, default=16)
    ap.add_argument("--min-score", type=int, default=66)
    ap.add_argument("--limit", type=int, default=60)
    a = ap.parse_args()

    if lora_dataset is not None:
        print("=== building dataset ===")
        lora_dataset.build(character=a.character, min_score=a.min_score, limit=a.limit)
    else:
        print("[lora_train] lora_dataset module unavailable; skipping dataset build.")

    print("=== training (or staging) LoRA ===")
    result = train(character=a.character, steps=a.steps, rank=a.rank)
    if result is not None:
        print("LoRA ready:", result)
    else:
        print("LoRA staged (no trainer). Follow README_LORA.txt to run the multi-hour job.")


if __name__ == "__main__":
    main()
