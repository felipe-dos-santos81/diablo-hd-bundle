# Diablo Animation Regeneration

Regenerates the 1,791 animations and 145,560 frames of *Diablo* + *Hellfire*
(Blizzard North, 1996/1997) as painted high-definition art at exactly 2x
their native size, with the outline locked, and repaints each monster
recolour variant as its own animation (about 74,000 more frames, for about
220,000 in all), with local models:

- ComfyUI running Qwen-Image 2.1 img2img with two reference images
  (`qwen-image-2.1-i2i`: the sheet's own guide and, for every sheet but a
  character's first, its anchor's promoted render), with
  `qwen-image-2.1-i2i-faithful` (denoise 0.9) as the fallback for a sheet
  stuck after `MAX_ATTEMPTS` (4) rejections.
- vLLM serving `Qwen/Qwen3.8-27B`, which captions each character before
  rendering and reviews each promoted sheet afterwards.

Input: `../diablo-textures-exporter/out/` (override with `DIA_SRC`).
Output: `data/anims-ai/<record dir>/d<g>/f<i>.png` (override with `DIA_DST`),
and each recolour variant under
`data/anims-ai/<record dir>/@trn/<trn path>/d<g>/f<i>.png`. Previews:
`data/preview/<output tree's directory name>/<comfy name>/d<g>.gif` (the
root overridable with `DIA_PREVIEW`): the default tree's land in
`data/preview/anims-ai/`, and `dst=data/spike/<name>`'s in
`data/preview/<name>/`, so each tree keeps its own.

**Personal use only.** The extracted and regenerated art is Blizzard
North/Activision Blizzard copyright. Do not redistribute it. `data/`,
`reviews.yaml`, `*.pending` and `*.tmp` are gitignored; never commit art.

## Pipeline

```
DIA_SRC (exporter out/) ──[caption]──▶ characters.yaml ──(you edit)──┐
                                                                       ▼
data/anims-ai/ ◀──[batch]──── characters.yaml + reviews.yaml (rejects only)
   │              ComfyUI up, vLLM stopped
   ├──[review]──▶ reviews.yaml   (vLLM up)
   └──[preview]─▶ data/preview/anims-ai/*/d<g>.gif
```

1. **`make caption`** (vLLM up) seeds `characters.yaml` from the manifest on
   its first run, then describes every character whose caption is blank and
   writes it in, saving after each one. `force=1` redoes all; blanking one
   caption redoes that character.
2. **Edit `characters.yaml`.** Fix the seeded grouping, `anchor` and `skip`
   by hand; the caption becomes the REFERENCE OBSERVATIONS section of every
   sheet's prompt.
3. **`make batch variants=0`** (ComfyUI up, vLLM stopped) renders every base
   sheet — a character's anchor animation first, then its other base
   animations — into `data/anims-ai/`, leaving the recolour variants alone,
   and writes each `skip` animation as a nearest-neighbour 2x.
4. **`make review`** (vLLM up) judges every promoted sheet whose latest
   attempt is unreviewed and writes `reviews.yaml`, saving each verdict as
   it arrives (Ctrl-C stops it and keeps them).
5. **Repeat `make batch variants=0` and `make review`** until the base
   animations settle (no more rejections).
6. **`make batch`** (no `variants=0`) renders the recolour variants too,
   each variant sheet painted against its base's promoted sheet of the same
   number.
7. **`make review`** again: the bases are already reviewed, so this pass
   judges the variant sheets.
8. **Repeat `make batch` and `make review`** until the variants settle too,
   redoing only the rejected sheets, with the next seed and the review's
   issues as corrections.
9. **`make verify`** audits `data/anims-ai/`.

`make dry-run` prints what `batch` would do — every sheet's size, anchor and
corrections, and its status (including `blocked` and `stale`) — without
touching ComfyUI.

## Swapping the services on this host

vLLM (about 73 GB) and a render (about 45 GB) do not fit together in the
GB10's 121 GB of unified memory.

| Service | Start | Stop |
|---|---|---|
| vLLM | `docker start lmcache-server vllm-server` | `docker stop vllm-server lmcache-server` |
| ComfyUI | `make server` (foreground) or `sudo systemctl start comfyui` | Ctrl-C, or `sudo systemctl stop comfyui` |

`make batch` refuses to start with less than 45 GB free (`memcheck=0` skips
the guard). A sheet whose render fails is left for the next batch while the
batch goes on (it exits 1 at the end); the batch stops early, freeing
ComfyUI's models, when ComfyUI stops answering or 3 sheets fail in a row. If vLLM cannot start after a batch, free ComfyUI's models by
hand:

```
curl -X POST http://127.0.0.1:8188/free -H 'Content-Type: application/json' -d '{"unload_models":true,"free_memory":true}'
```

## Characters

`characters.yaml` has one entry per character, seeded by the first `caption`
run:

```yaml
monsters/zombie:
  animations:            # record directories under assets/, in render order
    - monsters/zombie/zombien.cl2
    - monsters/zombie/zombiew.cl2
  anchor: monsters/zombie/zombien.cl2
  caption: >-
    ...
  skip: []               # animations written as nearest-neighbour 2x
```

Seeding groups a monster's, player's or towner's animations by their shared
directory, and a missile's by its file stem without trailing digits
(`acidbf1`..`acidbf16` become `missiles/acidbf`). The seeded `anchor` is a
player's standing animation (stem ending `st`), a monster's neutral one
(ending `n`), otherwise the first animation in natural order — never one
without frames while another has some. The seed is only a proposal: regroup,
re-anchor or add to `skip` by hand. `caption` fills blank captions only;
`force=1` redoes all.

## Sheets and cells

A **sheet** is one canvas and the unit of render, attempt, retry and
promotion; its key is `<record dir>[@trn/<trn path>]/sNN`. Every direction
(group) gets one cell size — the union of its frames' opaque boxes at 2x,
plus 8 HD px of margin — and `GUTTER` HD px (16 by default) between cells;
canvases are packed to a multiple of 32 px on each side. `SHEET_PACKING`
(`packing=`) chooses one direction per sheet (`direction`, the default) or
several consecutive directions of one animation up to `MAX_CANVAS_PX`
(1,048,576 px) (`packed`); a direction that alone exceeds that gets a sheet
sized to fit it. A direction is never split across sheets, and a variant's
layout always equals its base's: sheet `sNN` of a variant pairs with sheet
`sNN` of its base.

A character's anchor animation renders first, against its own guide only;
every other base sheet gets the anchor's first promoted sheet as a second
reference. A variant sheet gets its own base's promoted sheet of the same
number instead, and is told (and reviewed) to match its painting but to take
every colour from its own guide. A sheet that still needs rendering while its anchor is not
yet promoted reports `blocked` and waits — `batch --force` never renders it
either, since forcing a sheet that has no anchor to paint against would
throw the render away. A promoted sheet whose anchor has since been
re-rendered (a different SHA-256) reports `stale` and renders again, like a
new sheet.

## Checks

Before promotion, `make batch` colour-matches each frame toward its own
source guide in float CIE Lab (over its outline only), then checks every
frame of the sheet at native size:

- **Size and outline:** exactly `(2w, 2h)` RGBA, with the locked soft
  outline (the source mask at 2x nearest-neighbour, anti-aliased only within
  1 HD px of its edge). Computed, so it cannot fail in batch; `make verify`
  re-checks it on disk.
- **Shift:** phase correlation inside the mask; fails at 0.5 native px or
  more. A frame with fewer than 200 opaque native pixels always passes.
- **Interior edge agreement:** the source's strong edges (Sobel magnitude
  above 80) that survive in the render (above 60, within 1 px), over the
  mask eroded by 1 native px so the locked outline itself cannot inflate the
  score; fails below 0.80. A frame with fewer than 30 strong source edge
  pixels always passes.
- **Consistency:** for consecutive frames of a direction, the render's mean
  colour step against its neighbour must not exceed twice the source's own
  step plus 4 levels (flicker).
- **Gutter bleed:** a gutter whose mean colour has moved more than 12 levels
  from the flat background is printed as a warning, never a rejection.

A rejection is written to `reviews.yaml` as `source: geometry`; the next
batch retries the sheet with `prompts.GEOMETRY_CORRECTION` as its correction
(the gate's own issue strings mean nothing to the diffusion model). The rule
from Atlantis stands: do not loosen the gate to get a sheet through — fix
its character's caption or the run's settings instead.

A sheet is **STUCK** when its latest attempt was rejected and 4 of its
attempts were rejected, by the gate or by the review. Only rejections count:
never a failed, unfinished attempt, nor a promoted one that was merely
rendered again (because its anchor changed, or with `force=1`). The next
batch renders it once more through `qwen-image-2.1-i2i-faithful` (unless a
rejected attempt already used it); if that is rejected too, the run reports
it and leaves it alone:

- Fix the sheet's character's caption in `characters.yaml`, then re-render
  that sheet alone, as the STUCK line says: `make batch sheet=<sheet key>
  force=1`

To restart a sheet from scratch, delete its `data/anims-ai/.quality/<sheet
key>/` folder **and** its entry in `reviews.yaml` (a leftover entry becomes
current again once new attempts reach its number), then run
`make batch sheet=<sheet key> force=1`.

## Outputs and the audit folder

```
data/anims-ai/<record dir>/d<g>/f<i>.png                        the promoted base frame
data/anims-ai/<record dir>/@trn/<trn path>/d<g>/f<i>.png         the promoted variant frame
data/anims-ai/.quality/<sheet key>/
  attempt-N.png                        the raw rendered canvas, before the colour match
  attempt-N.tiles/
    sheet.guide.png                    the guide canvas sent to ComfyUI
    sheet.anchor.png                   the anchor canvas, when the sheet has one
  attempt-N.prompt.txt                 starts "workflow: NAME"; the positive and negative prompt
  attempt-N.json                       workflow, seed, packing, gutter, background, canvas,
                                        groups, cells, anchor, match, geometry, promoted,
                                        canvas_sha256, frames (path -> sha256), seconds
  attempt-N.error.txt                  a failed attempt: workflow, seed, stage, seconds, error
                                        (no .json)
  attempt-N.review.json                the VLM verdict ({"accepted", "issues"})
  attempt-N.review-error.txt           a failed review (no .review.json)
```

## Commands

| Target | What it does |
|---|---|
| `make caption [character=] [force=1]` | Seed and caption `characters.yaml` |
| `make dry-run [character=] [anim=] [sheet=] [variants=0]` | Sheets, cells, canvas sizes, dependency order, stale and blocked sheets |
| `make batch [character=] [anim=] [sheet=] [variant=] [variants=0] [workflow=] [strength=] [memcheck=0] [force=1]` | Render and promote into `data/anims-ai/` |
| `make review [character=] [sheet=] [concurrency=] [force=1]` | Write `reviews.yaml` |
| `make preview [character=] [anim=] [sheet=]` | An animated GIF per direction into `data/preview/<dst directory name>/<comfy name>/`: source (nearest-neighbour 2x) and render side by side |
| `make verify [character=] [sheet=]` | Audit `data/anims-ai/` against the manifest, the 2x contract, the outline and the attempts |
| `make server` / `install` / `check` / `test` / `clean` | Start ComfyUI from `~/ComfyUI` / create the venv / byte-compile / run the unit tests / remove `__pycache__` |

`character=` selects by character key, `anim=` by record directory,
`sheet=` by sheet key (a variant's sheet key selects that variant sheet
only; batch, dry-run, review, preview and verify) and `variant=` by TRN path
(of the variants, only those); all accept several space-separated values,
and an unknown one is refused. Every pipeline target also takes `packing=`,
`gutter=`, `background=` and `anchor=0` (the layout switches the spike may
change) and `src=`/`dst=` overrides.

**One `dst=` per layout.** An output tree holds sheets of one layout only:
`make batch` refuses to render into a tree whose sheets were rendered with
another `packing=`, `gutter=` or `background=` (their records' packing,
gutter, background, canvas or directions differ from the sheets as now
planned), naming the first few; `make dry-run` lists them as `layout` and
`make verify` counts them as problems. Give each layout its own `dst=`, or
restore the settings the tree was rendered with. Environment overrides: `DIA_SRC`,
`DIA_DST`, `DIA_PREVIEW`, `DIA_CHARACTERS`, `DIA_REVIEWS`, `DIA_WORKFLOW`,
`DIA_MATCH_STRENGTH`, `COMFY_URL`, `COMFY_DIR`, `VLM_BASE_URL`, `VLM_MODEL`,
`VLM_API_KEY`.

## Setup

- `make install` creates `.venv` with Pillow, PyYAML and numpy.
- ComfyUI at `~/ComfyUI` (override with `COMFY_DIR`), at or after commit
  c194dd0 (2026-09-20), with these files under `models/`:
  - `diffusion_models/qwen_image_2.1_bf16.safetensors`
  - `text_encoders/qwen3vl_8b_bf16.safetensors`
  - `vae/qwen_image_2.1_vae_bf16.safetensors`

  `make batch` checks the files and the node classes (`TextEncodeQwenImage21`)
  before rendering.
- vLLM serving `Qwen/Qwen3.8-27B` at `http://127.0.0.1:8000/v1`.

## Project structure

| File | Purpose |
|---|---|
| `anim_recreate.py` | Driver: `caption`, `batch`, `review`, `verify`, `preview`; selection, dependency order, staleness, preflights, audit folders, promotion |
| `source_tree.py` | Reads and validates diablo-textures-exporter's `manifest.json`, `meta.json` and palette/TRN JSON: animations, frames, variants |
| `characters_file.py` | `characters.yaml` and `reviews.yaml`: shape, validation, the seeded grouping, atomic save |
| `sheet_layout.py` | Per-direction cell boxes, packing into canvases, the guide canvas, slicing, the locked soft alpha |
| `geometry_check.py` | Shift, interior edge agreement, frame-to-frame consistency, gutter bleed |
| `colour_match.py` | The Lab transfer, restricted to a mask |
| `prompts.py` | Caption, render and review prompts, VLM payloads, `parse_review`, `vlm_is_serving` |
| `comfy_client.py` | ComfyUI HTTP client and the workflow registry; the only place that knows node ids |
| `anim_qwen21_i2i.json` | The ComfyUI API graph |
| `characters.yaml` | Character groupings, anchors, captions and `skip` lists (hand-owned; written by `make caption`'s first run) |
| `Makefile`, `run_batch.sh`, `run_server.sh` | Targets and wrappers |
| `testkit.py`, `test_*.py` | Test support and unit tests (no GPU, no network) |
| `NOTES.md` | Live checks, spikes and runs (created by the first spike) |

The design spec and build plan are at the bundle root:
[`../docs/superpowers/specs/2026-09-26-diablo-animation-regeneration-design.md`](../docs/superpowers/specs/2026-09-26-diablo-animation-regeneration-design.md),
[`../docs/superpowers/plans/2026-09-26-diablo-animation-regeneration.md`](../docs/superpowers/plans/2026-09-26-diablo-animation-regeneration.md).
