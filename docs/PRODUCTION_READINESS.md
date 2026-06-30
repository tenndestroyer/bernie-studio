# Bernie Studio — Production Readiness Report

A 13-expert panel reviewed the whole pipeline (voice, lip-sync, music, character, animation,
environment, story, rendering, AI-QA, research, install-readiness, software-eng), scored each
subsystem **against the realistic ceiling for free/local AI video** (Flux + Wan 2.2 = a cute,
stylized-3D AI cartoon with soft AI-video motion — **not** rigged Pixar/Moonbug), and produced
the prioritized roadmap below.

> **Already actioned from this report (committed):**
> - 🔧 **Installer fixed** — the #1 blocker. `setup.ps1` now provisions a pinned, torch-compatible
>   **Python 3.12** (independent of the fragile ComfyUI-portable download), gates `.installed` on
>   `import torch` succeeding, and `run.bat` never falls back to a too-new system Python. `doctor.py`
>   now checks the engine's embedded Python + torch directly. *(install-readiness 42 → much higher.)*
> - 🔊 **Audio quick wins** — real **sidechain music ducking** under dialogue (`music.py`), per-line
>   **voice loudness-normalization** + **parallel TTS** + **[emotion] markup** + unknown-speaker warnings
>   (`voices.py`), best-of-3 for the underscore bed (`music_gen.py`).

---

## 1) Subsystem scores

| Subsystem | 0–100 | One-line |
|---|---|---|
| Story / Writing (writers' room + director) | 80 | Real 22-agent room + multi-pass rewrite loop; coherent on-brand 15-min preschool scripts; self-graded scores are the soft spot. |
| Voice & Dialogue (edge-tts) | 62 → ↑ | Per-character voices with rate/pitch tuning; **now** normalized + parallel + emotion-aware. |
| Lip-sync | 28 | Prompt-only "mouths moving"; fine for preschool, far from phoneme-accurate. Fixable via post-pass. |
| Music & Songs (ACE-Step + ffmpeg) | 58 → ↑ | Local best-of-N songs; **now** ducked under dialogue instead of a flat bed. |
| Render pipeline (Flux→Wan, two-pass) | 72 | Resumable, retrying, VRAM-tiered, tiled-decode. Output quality capped by the model, not the code. |
| Visual QC (qwen2.5-VL) | 66 | Genuinely looks at pixels; JSON+regex parse; scary = hard re-roll; mid-clip frame check. Coarse (7B). |
| Mechanical QC (ffmpeg) | 78 | Deterministic black/blown/frozen/size rejection + auto-retry — the reliable floor. |
| Assembly & Pacing | 60 | Storybook grade, fades, beat-timed durations — long beats filled by **ping-pong looping** one ~3.4s clip. |
| Character consistency (LoRA) | 50 | Full LoRA tooling wired (`pipeline.LORA`←`BERNIE_LORA`); **not yet trained** → today it's "long-prompt" only. |
| Continuity between shots | 40 | Each keyframe independent; opt-in same-location reuse is a softening, not real continuity. |
| Orchestration / Autonomy | 80 | script→voices→songs→render→visual-loop→assemble→music, resumable, per-slot. |
| Config / Hardware-awareness | 85 | Clean NVIDIA/AMD/Intel/CPU detection, 4 VRAM tiers, fp8/fp16 selection, env overrides. |
| GUI / UX | 74 | Dependency-free stdlib server, live dashboard, thumbnails, Writers'-Room & Visual-QC, Doctor. |
| Tests / Maintainability | 62 | 25 mock-based tests; render/LLM/ffmpeg paths are integration-only (untested). |
| Install / first-run | 42 → ↑ | Was the top blocker (Python 3.14 vs torch); **now fixed** (pinned 3.12 + verified torch gate). |
| **OVERALL** | **66** | A genuinely working, autonomous, on-model **AI cartoon** factory — near the free/local ceiling on story & infra, with real gaps in lip-sync, continuity, and (untrained) LoRA. |

---

## 2) Missing capabilities (grouped)

**Audio / Voice** — emotional prosody (partly addressed via `[emotion]` tags); per-line normalization *(done)*;
real music ducking *(done)*; parallel TTS *(done)*; unknown-speaker warning *(done)*.
**Motion / Lip-sync / Continuity** — no phoneme lip-sync (generic cue); ~3.4s clips with ping-pong fill for long
beats; no cross-shot continuity by default; **LoRA not yet trained** (frame-to-frame identity rides the prompt).
**Quality control** — self-graded scripts (rubric anchors + caps mitigate, don't remove inflation); 7B VLM on one
keyframe + one mid-clip frame; no audio-side QC (sync/clarity/level).
**Robustness** — render/LLM/ffmpeg/ComfyUI paths untested (mock-only suite); no offsite output backup; single
ComfyUI process per long job.

---

## 3) Prioritized roadmap

### QUICK WINS (S/M, high impact)
1. ✅ **Sidechain-duck music under dialogue** (`music.py`). — *done.*
2. ✅ **Normalize voice lines** (`voices.py` loudnorm). — *done.*
3. ✅ **Parallelize TTS** (`voices.py`). — *done.*
4. ✅ **Best-of-3 underscore bed** (`music_gen.py`). — *done.*
5. ✅ **Warn on unknown-speaker fallback** (`voices.py`) + Doctor engine-python/torch check. — *done.*
6. **Emit ffmpeg/mechanical-QC verdicts to the GUI event stream** (`qc.py`→`core/events.py`). · med · S.

### SHORT-TERM (the real quality levers)
7. **Train the Bernie character LoRA** (tooling done; needs the GPU hours). · **very high** · L · *curate from
   visual-QC-passed keyframes only; makes characters consistent, not rigged.*
8. **Emotional prosody at depth** — drive richer edge-tts variants, or swap to local **Piper/F5-TTS**. · very high · M–L.
9. **Lengthen real motion per shot** — raise `WAN_FRAMES` where VRAM allows; reduce ping-pong on action beats. · high · M · *gate by tier (OOM risk).*
10. **Opt-in post-render lip-sync pass** (Wav2Lip/LatentSync on dialogue shots). · very high (28→70) · L · *make it opt-in like `interp`; doubles dialogue-shot render time.*

### LONG-TERM (ceiling-pushers)
11. **CLIP/embedding off-model detector** vs a curated reference set (hypothesis — must prove the threshold). · high · L.
12. **Per-character singing stems** (ACE-Step split / spleeter). · med-high · L · experimental.
13. **Voice-pack modularization** (`characters.py`→`configs/voices/*.json`). · med · M.
14. **Offsite output backup + render-process supervision.** · med (ops) · M.

---

## 4) Estimated impact

- **Quality:** the audio quick wins (ducking + normalization) move perceived audio from "amateur YouTube"
  toward "broadcast-ish" — the cheapest, most-felt improvement to a parent's ear. LoRA + longer motion + lip-sync
  move the *picture* toward the top of what free AI video can do. None break the hard ceiling (no rig).
- **Performance:** parallel TTS shaves minutes; longer motion / lip-sync / interp **add** render time. These trade
  time for quality; they don't speed anything up.
- **Maintainability:** architecture is clean (typed state, events bus, presets, doctor, tier config). Biggest debt
  is the untested render/LLM/ffmpeg integration paths — a smoke-test harness would de-risk every future change.
- **UX:** the GUI already turns a blind batch into a watchable, steerable job; surfacing QC verdicts + audio levels
  closes the remaining "why did this shot look/sound off?" gap.

---

## 5) Final assessment

**Ready to consistently produce original, *watchable, on-model preschool AI-cartoon* episodes — yes.** Ep2 already
rendered end-to-end (16 min / 1080p), proving the autonomy and the floor. The engineering is genuinely strong:
hardware-aware tiering, resumable two-pass render, deterministic mechanical QC with retry, a real (if self-grading)
22-agent writers' room, and a true vision-QC pass. That is **at or near "as good as free/local AI video gets"** on
infrastructure, story, and safety.

**Where the line is:**
- **Immovable (free/local AI-video ceiling):** motion is soft, slightly-floaty AI video, not rigged/keyed animation;
  no pose control or pixel-painting (the director *re-rolls*, it doesn't animate); ~3.4s native clip length.
- **Fixable now, locally (engineering gaps, not ceilings):** lip-sync post-pass, deeper emotional voices, music
  ducking *(done)*, voice mastering *(done)*, parallel TTS *(done)*, **training the LoRA**, less ping-pong looping.
- **Would need paid/studio tools (the true "feature" gap):** rigged character animation, hand-keyed acting,
  frame-accurate studio lip-sync, live-performer scored music. Out of scope for any free/local stack — and the repo
  correctly never pretends otherwise.

**Overall: 66/100** against the free/local ceiling today. With the quick wins (audio, ~+6, **now applied**) and the
short-term levers (trained LoRA + emotional voices + lip-sync + longer motion, ~+10–12), a realistic honest ceiling
for this approach is **~80/100** — a consistently on-model, well-written, safe, musical, cute-stylized-3D AI cartoon
that stands on its own on YouTube Kids or hands cleanly to a real animator as an animatic. It will not reach
rigged-Pixar/Moonbug polish, and the codebase is admirably honest that it never will.
