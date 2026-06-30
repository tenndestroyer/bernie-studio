# Bernie Studio presets — make a new show with config, not code

This folder holds the **data** that defines a show: the cast, locations, art style, and the
season's episode list. By default Bernie Studio loads the built-in Bernie values (from
`bernie/characters.py` and `bernie/series.py`). Drop matching JSON files here and they take over —
no Python edits required.

```
configs/
  characters/bernie.json     # cast + locations + style/neg
  series/season_1.json       # the episode plan
  README.md                  # this file
```

Nothing here changes current behavior unless you provide your own configs. If a file is missing or
malformed, the studio silently falls back to the built-in Bernie defaults — it never crashes.

## Make your own show

1. **Copy the templates.** Copy this whole `configs/` folder somewhere, e.g. `MyShow_configs/`.
2. **Edit the cast** in `characters/bernie.json`:
   - `style` — one global look string, repeated on every keyframe to stay on-style.
   - `neg` — the negative prompt (things to avoid).
   - `env_style` — shared environment look; the token `{ENV_STYLE}` inside any location string is
     replaced with this value.
   - `chars` — a map of `TOKEN -> { "desc": "...canonical appearance...", "voice": [...] }`.
     - `desc` is the full appearance string used verbatim in prompts.
     - `voice` is `[edge_tts_voice, rate, pitch]` (e.g. `["en-US-AnaNeural", "+10%", "+0Hz"]`),
       or `null` for a character with no lines (or for narration use a real voice).
   - `locations` — a map of `KEY -> "scene description, {ENV_STYLE}"`.
3. **Edit the season** in `series/season_1.json` — a JSON list of episode objects, each with:
   `n` (number), `slug` (work-slot id like `ep1`), `name` (output base name), `scenes`
   (shot count), `title`, and `premise` (the one-paragraph story seed the writers' room expands).
4. **Point the studio at your folder** by setting the environment variable before you run:

   ```powershell
   $env:BERNIE_PRESETS = "C:\path\to\MyShow_configs"
   ```

   ```bash
   export BERNIE_PRESETS=/path/to/MyShow_configs
   ```

   The studio reads `config.PRESETS_DIR`, which honors `BERNIE_PRESETS` (defaulting to this
   `configs/` folder in the repo).

## YAML (optional)

`bernie/presets.py` will also read `.yaml`/`.yml` versions of these files **if** PyYAML happens to
be installed (`pip install pyyaml`). It is never required — the run path stays standard-library
only, and JSON always works.

## Honest limits

Presets swap the **data** (descriptions, voices, locations, episodes). They do not change the
renderer, the 22-agent writers' room, or the look of the AI video — that's still a cute 3D cartoon,
not rigged Pixar. A wildly different art style may need a trained LoRA (a long GPU job), not just a
prompt change.
