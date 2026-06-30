# 🐶 Bernie Studio

**An autonomous, fully-local AI pipeline that writes, directs, voices, scores, renders, and
edits a complete animated kids' episode — from one command.**

It generates *"Bernie & the Dino Valley Pals"* (a Bernese Mountain Dog puppy and his dinosaur
friends), but the whole system is reusable for any preschool-style show. Everything runs on
**your own machine** with free/open models — no paid services required.

> **Honest scope:** this produces a genuinely good **AI cartoon** — cute stylized-3D characters,
> rich environments, real songs, a 22-agent "writers' room" that rewrites the script. It is **not**
> rigged-studio Pixar/Moonbug animation; AI video models can't match hand-rigged 3D. Set
> expectations accordingly. The still frames are 3D-Pixar-like; the motion is good AI video.

---

## ✨ What it does (all automatic, all local)

1. **Writes** a long episode (LLM story generator → structured shot list)
2. **Directs** it with a **22-agent AI writers' room** (Executive Producer, Head Story Writer,
   Comedy/Emotional/Continuity/Safety/Packaging directors, … + a Master Creative Director that
   loops review→revise) — scores every dimension and rewrites dialogue/staging
3. **Voices** every line (per-character TTS), **composes songs** (ACE-Step), 
4. **Renders** each shot: Flux-dev 3D keyframe → Wan 2.2 image-to-video (cute-stylized 3D)
5. **Reviews the pixels** with a local vision model (qwen2.5-VL) and **re-renders weak shots**
6. **Assembles** with color-grade, pacing, ping-pong motion fill, and **mixes the music**
7. Outputs a finished **1080p `.mp4` + YouTube-Kids metadata** (title/tags/thumbnail)

## 🖥️ Requirements

- **Windows 10/11** with a GPU. It **auto-detects your GPU vendor** and configures itself:
  - 🟢 **NVIDIA (CUDA)** — fully supported & verified. Works from 8 GB VRAM; better with more. **Recommended.**
  - 🟡 **AMD / Intel Arc (DirectML)** — supported **best-effort / experimental**. The installer sets up
    `torch-directml` and launches with `--directml` automatically. Honest caveats: it's **slower**, can't
    use fp8 (so it needs **more VRAM** — fp16 weights), and the heavy **Wan video** model may be slow or
    not fully supported on DirectML. Image generation (Flux) generally works. For better AMD performance,
    the community [ComfyUI-Zluda](https://github.com/patientx/ComfyUI-Zluda) (CUDA-on-AMD) is an alternative.
  - ⚪ **No GPU** → CPU mode (extremely slow; testing only).
- ~70 GB free disk. `git`, `ffmpeg`, and `Ollama` are **auto-installed** if missing (via winget).
- *(Optional, free)* a [HuggingFace token](https://huggingface.co/settings/tokens) + accepting the
  [FLUX.1-dev license](https://huggingface.co/black-forest-labs/FLUX.1-dev) to fetch that model
- *(Optional, free)* Cerebras/Groq API keys for faster cloud LLM (local Ollama works with none)

## 🚀 Quick start

> ⚠️ **You can't run it from this GitHub web page.** First get the files onto your PC, *then*
> double-click `run.bat`. Two ways:

**Option A — Download ZIP (no tools needed):**
1. Click the green **`< > Code`** button at the top of the repo → **Download ZIP**
2. **Right-click the ZIP → Extract All** (run it from a real folder, not inside the ZIP)
3. Open the extracted folder and **double-click `run.bat`**

**Option B — git clone:**
```bat
git clone https://github.com/tenndestroyer/bernie-studio
cd bernie-studio
run.bat
```

That's the whole thing — **double-click `run.bat`**.

On the **first run** it asks for your (free) HuggingFace token, then auto-installs **everything**
(ComfyUI + cu128 PyTorch + all models + custom nodes + Ollama LLMs, ~50 GB), detecting your
hardware as it goes. Then it **starts the fully-autonomous series** and keeps building the whole
season by itself — episode after episode, hands-off. Every later double-click just continues.

Make a **new** episode from any premise:
```bat
python make.py --slot ep3 --name Bernie_Ep3 --generate "Bernie and Rosie get lost in a glowing cave" --scenes 14
```

### 🤖 Fully-autonomous Series Mode
```bat
python make.py --series
```
This **auto-picks the next un-made episode** from the built-in 12-episode Season 1 plan, builds it
completely (story → 22-agent direction → voices → songs → render → review → final cut), then moves
to the **next episode automatically** — hands-off, forever, until the whole season is done. It's
**resumable at every level**: a crash or PC restart just continues from the next unfinished episode
(tracked in `series_state.json`), and each episode's render resumes mid-way via `progress.json`.
Edit the `SEASON` list in `bernie/series.py` to write your own episodes.

## ⚙️ Hardware auto-scaling (tiers)

On first run it picks a tier from your VRAM (override with `BERNIE_TIER`):

| Tier | VRAM | Wan video | Native res | Notes |
|------|------|-----------|-----------|-------|
| `ultra` | 24 GB+ | 5B fp16 | 1280×720, 121f | full res, no tiled decode, `qwen2.5:32b` agents |
| `high` | 16–22 GB | 5B fp8 | 1280×720, 81f | `qwen2.5:14b` agents |
| `balanced` | 12–15 GB | 5B fp8 | 960×544, 81f | laptop default, tiled decode |
| `low` | <12 GB | 5B fp8 | 640×368, 81f | fastest |

**With 64 GB RAM + a 24 GB GPU** you get the `ultra` tier automatically: full-resolution video,
fp16 weights, a 32B local LLM for the writers' room, and the biggest models held in memory.

## ⏱️ Render time (honest)

Video is the long pole. Roughly **per 15-min episode**: `low` ~15 h · `balanced` ~50 h ·
`high`/`ultra` faster *per step* but higher res — plan for **overnight to multi-day** on a laptop,
**hours** on a 24 GB desktop. The render is **resumable** (survives crashes/restarts) and runs
unattended.

## 🔑 Configuration

Copy `keys.example.env` → `keys.env` (gitignored) and add any optional API keys:
```
HF_TOKEN=hf_...
CEREBRAS_API_KEY=csk_...     # optional free cloud LLM
GROQ_API_KEY=gsk_...         # optional free cloud LLM
BERNIE_TIER=high             # optional manual tier override
BERNIE_HOME=D:\BernieData    # optional: put the 50GB of models/output on another drive
```

## 📁 Layout

```
bernie-studio/
  bernie/            # the pipeline package (config, agents, director, render, assemble, ...)
  make.py            # CLI entry
  setup.ps1          # first-run auto-installer
  run.bat            # one-click
  BernieStudioData/  # (auto-created, gitignored) engine + models + output
```

## 📜 License
MIT for this code. The downloaded **models** (FLUX.1-dev, Wan 2.2, ACE-Step, etc.) each carry
their **own licenses** — review them before any commercial use.
