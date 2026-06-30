# Bernie Studio — Architecture & Honest Roadmap

> A grounded design for the local AI animation pipeline in this repo. Every recommendation
> names the real files it touches. **Nothing here promises rigged-studio Pixar.** The achievable
> ceiling is a *genuinely polished, on-model, well-directed "cute stylized-3D AI cartoon"* with
> soft AI-video motion — and the whole design pushes **that** ceiling as far as it honestly goes.
>
> This document is the synthesis of a 7-agent design pass (architecture, GUI/UX, AI quality-control,
> render-quality, and DevOps experts) followed by an adversarial **honesty review**. The honesty
> pass's corrections are folded in — most importantly: **a working GUI already exists** (`bernie/gui.py`),
> so the GUI work below *extends* it, it does not build one from scratch.

---

## 0. Honest baseline — what exists today

The pipeline works end-to-end and is more capable than most "AI cartoon" toys:

- **Story** — `showrunner.build_episode()` (hand-authored pilot) and `episode2.build()` (LLM-generated,
  outline → per-scene shots, validated against `characters.CHARS` / `LOCATIONS`).
- **Direction** — a real **22-agent writers' room** (`agents.AGENTS`, orchestrated by `agency.run_agency()`),
  the multi-lens script director (`director.direct()`), and a **vision-QC** pass
  (`director_visual.review_keyframes()`) that actually looks at rendered PNGs with `qwen2.5vl:7b`.
- **Render** — `pipeline.main()` two-pass (Flux keyframes → Wan 2.2 i2v), graphs in `workflows.py`,
  driven via `comfy.py`; hardware auto-tiering in `config.py`.
- **Media** — `voices.py` (edge-tts per character), `music_gen.py` (ACE-Step, best-of-N),
  `assemble.py` (grade / pacing / ping-pong fill), `music.py` (beat-aligned beds).
- **Autonomy** — `series.py` builds Season 1 episode-by-episode as isolated subprocesses; resumable via
  `progress.json` / `series_state.json`.
- **GUI (NEW, v1)** — `bernie/gui.py` + `bernie/web/index.html`: a **dependency-free** stdlib
  `ThreadingHTTPServer` bound to `127.0.0.1` that opens a browser and serves a single-page app with a
  live Dashboard (GPU/VRAM/disk/tier, render-slot progress, season progress), Episode Creator, Story
  Builder, Character reference, Library, live Logs, Settings (writes `keys.env`), and an Install wizard.
  JSON API: `/api/status`, `/api/season`, `/api/settings`, `/api/logs`, `/api/create`, `/api/series`,
  `/api/stop`, `/api/install`, `/api/shots`, `/api/thumb`.

**The real remaining gaps** this roadmap targets: the GUI is **stdlib-based and now wired into `run.bat`**
as the default front door, but it can be deepened (per-shot keyframe **thumbnails** are now in v1; a live
*event stream* and Writers'-Room / Visual-QC pages are still to come). There is no structured logging or
typed state (everything is `print` + raw `dict` reads). The 22-agent scores are LLM self-reports with no
calibration. And **character LoRA lock is stubbed** (`pipeline.LORA = None`) — so frame-to-frame identity
rests entirely on prompt strings. That last one is the single biggest realistic quality lever left.

---

## 1. Target architecture

Goal: **modular vertical slices** (story → direction → media → render → QC → assemble → series), a thin
service layer the GUI calls, typed state, and centralized logging — *without breaking the one-command flow*.
Old flat modules stay importable during migration (backward-compatible shims), so nothing breaks on day one.

```
bernie-studio/
├── make.py                 # CLI entry (thin dispatcher)
├── run.bat / setup.ps1     # one-click installer → launches the GUI
├── bernie/
│   ├── gui.py              # ✅ v1 GUI server (stdlib http.server + JSON API) — the front door
│   ├── web/index.html      # ✅ v1 single-page UI (no build step, no CDN, works offline)
│   ├── core/               # (planned) config.py (exists) + context.py, state.py, events.py, log.py
│   ├── llm/                # (planned) chain.py + jsonrepair.py extracted from director.py
│   ├── story/              # showrunner.py, generator.py (episode2.py)
│   ├── direction/          # agents.py, agency.py, director.py, visual.py, revise.py
│   ├── render/             # comfy.py, workflows.py, pipeline.py, qc.py
│   ├── media/              # voices.py, music.py, music_gen.py, characters.py
│   ├── assemble/           # assemble.py
│   └── series/             # series.py
└── docs/ARCHITECTURE_AND_ROADMAP.md   # this file
```

> **Honest note on the refactor:** the design pass proposed FastAPI/uvicorn and a big package reshuffle.
> We deliberately **kept the GUI on Python stdlib** (zero new dependencies — consistent with the repo's
> "dependency-free local web app" principle) and treat the package reshuffle as **incremental cleanup, not
> a precondition**. The current `gui.py` already drives the pipeline as tracked subprocesses without any
> refactor, which proves a working GUI does not require it. Extracting `orchestrator.run_episode()` from
> `direct_episode.main()` is still a worthwhile dedup (one shared code path for CLI + GUI) — recommended,
> not a hard blocker.

---

## 2. AI quality-control / director system

Three layers exist; the design hardens each and adds calibration so the loop is *trustworthy*, not just
self-congratulatory.

- **Layer A — Writers' Room (text authority; strong, real).** 20 reviewer/creator agents score their
  dimensions 0–100 with shot-tagged `{issue, fix}`; the Master resolves conflicts; `director.improve()`
  applies rewrites. *Honest limit:* scores are the model grading its own homework → risk of inflation.
  **Fix (NEXT):** rubric anchors (worked 60/75/90 examples) so scores spread; persist a before/after diff
  of changed shots; de-dup notes by shot before the 24-note cap silently drops departments.
- **Layer B — Visual QC (pixel authority; genuine but coarse).** `qwen2.5vl:7b` scores each keyframe
  (`score / onmodel / scary / issue`); weak/scary/off-model shots are flagged and re-rolled.
  *Honest limit:* it reviews the **keyframe, not the motion**; the parser is a brittle regex.
  **Fix (NEXT):** have the VLM return JSON; add a mid-clip frame review; make `scary` a *hard* re-roll.
  An experimental CLIP/embedding distance check vs. a curated reference set is a **hypothesis to validate**
  (tune the threshold and prove it separates on-model from off-model for this style before trusting it).
- **Layer C — Mechanical QC (deterministic; keep as-is).** `qc.check_clip()` rejects black/blown-out/
  frozen/tiny clips; `pipeline` retries. The reliable floor — just surface its verdicts in the GUI.
- **Layer D — Character LoRA (the real consistency lever; currently stubbed).** `workflows.flux_keyframe`
  already wires a `LoraLoaderModelOnly` node. Training a per-character LoRA is the difference between
  "consistent-ish because the prompt is long" and "actually the same character every shot."

**The blunt truth about the revision loop:** re-rolling is a **lottery, not a paintbrush.** A new seed +
better prompt improves the *odds* of a good frame; it cannot guarantee one, and it cannot fix the soft,
slightly-floaty quality of AI-video motion.

---

## 3. Prioritized roadmap

Format: **effort** (S ≤1d · M few days · L 1–2 wk) · **impact** · one honest limit / acceptance check.

### NOW — done or in-progress this pass
1. ✅ **Ship the GUI v1** (`gui.py` + `web/index.html`): Dashboard, Episode Creator, Story Builder,
   Characters, Library, Logs, Settings, Install. · **L** · **Very High** · *Turns a blind multi-hour batch
   into something you start from a form, watch live, and stop. It does **not** make renders faster.*
   **Acceptance:** server boots, `/api/status` returns valid JSON, "Generate Episode" launches a resumable
   render — **verified**.
2. ✅ **Wire the GUI into `run.bat`** as the default launch (after first-run install). · **S** · **High** ·
   *The front door is now the app, not a CLI.* **Acceptance:** double-click → browser opens to the GUI.
3. ✅ **Per-shot Render Monitor + keyframe thumbnails** (`/api/shots`, `/api/thumb`; expandable slot grid). ·
   **M** · **High** · *You can see off-model shots forming — but the only action is re-roll, not a fix.*

### NEXT — clear value, more effort
4. **Train a character LoRA; flip `pipeline.LORA` on.** Add `lora_train.py`, curate a dataset of approved
   keyframes into `config.DATASET`. · **L** · **Very High** · *Biggest realistic jump in frame-to-frame
   consistency. Caveats: chicken-and-egg (you need consistent frames to train the LoRA that makes consistent
   frames — bootstrap from the best existing keyframes + light manual curation), and LoRA training itself
   costs GPU-hours/VRAM on the same tiers that already take overnight per episode. Makes characters
   consistent, **not rigged** — motion stays AI-video soft.* **Acceptance:** same character recognizable
   across ≥90% of shots in a held-out episode by human spot-check.
5. **Calibrate the writers' room** (rubric anchors + persisted before/after shot diffs + note de-dup). ·
   **M** · **High** · *Reduces score inflation and makes the room auditable; still can't judge final pixels.*
   **Acceptance:** agent scores show >10-pt spread on a deliberately weak draft (no longer all 85–92).
6. **VLM returns JSON; add mid-clip review.** · **M** · **High** · *More reliable flagging; a 7B VLM is a
   smart filter, not a human art director.*
7. **`core/events.py` append-only `events.jsonl`; GUI tails a live event stream.** · **S** · **Medium** ·
   *Richer than log-tailing; no effect on output quality.*

### LATER — real but deferrable
8. **Typed `core/state.py`** wrapping the JSON artifacts (no more raw-dict drift). · **M** · **Medium**.
9. **YAML preset system (`configs/`)** so a new show is config, not code edits. · **L** · **Medium**.
10. **`pyproject.toml` + mock-based tests** around `aggregate`, `extract_json`, `qc`, state I/O. · **M** ·
    **Medium** · *Prevents refactor regressions; users never see it.*
11. **Optional RIFE interpolation + detail upscale post-pass** before assemble. · **L** · **Medium** ·
    *Reads smoother/sharper, but polishes AI-video motion — it does not convert it into rigged animation,
    and it adds render time.*
12. **Last-frame → next-shot continuity chaining.** · **L** · **Medium** · *Softens shot-to-shot drift;
    AI i2v still wanders, so it's a softening, not true continuity.*

---

## 4. What this system can and cannot do

**It genuinely can:** write and *rewrite* a coherent ~15-min preschool episode with a 22-agent room; produce
attractive on-style 3D-looking keyframes and watchable cute-stylized motion; voice every line and compose
original songs locally; catch and re-roll weak/scary/off-model frames with a COPPA-minded safety screen; run
fully autonomously and resumably across a whole season; and (after the LoRA item) keep characters
recognizably the same shot to shot.

**It cannot — and the design never pretends otherwise:**
- **It is not rigged-studio Pixar/Moonbug animation.** Wan/Flux produce AI-video motion: soft, slightly
  floaty, occasionally drifting limbs/faces. No amount of re-rolling or QC changes that ceiling.
- **The director re-rolls; it does not paint.** No pixel-level correction, no hand-keyed animation, no pose control.
- **Scores are heuristic, not ground truth.** Calibration makes them more trustworthy, never authoritative —
  a human eye on the Visual-QC view stays the real quality gate.
- **Lip-sync is approximate** (mouths "move while talking"; audio over timed silence). Fine for preschool pacing.
- **It is not fast, and the GUI doesn't change that.** Hours on a 24 GB desktop; overnight-to-multi-day on a
  laptop. The GUI makes the wait *visible and steerable* — not shorter.
- **AMD/Intel is best-effort** (DirectML, no fp8, more VRAM; heavy Wan step may be slow/unsupported).
  NVIDIA/CUDA is the verified path.

**Bottom line:** the honest target is a *consistently on-model, well-written, well-scored, safe, musical,
cute-stylized 3D AI cartoon* — strong enough to stand on its own or to hand a real animator as an animatic.
The NOW bucket makes that reachable without flying blind; NEXT (LoRA + calibration) pushes the ceiling as far
as AI video honestly goes.
