# AGENTS.md

Guidance for agents working on the Diablo animation regeneration kit.
README.md is the user view; this is the agent view. The kit is a fork of the
*Fate of Atlantis* kit
(`~/code/atlantis-hd-bundle/atlantis-texture-enhancement`), reworked for
sheets of animation frames instead of rooms; everything here does not repeat
from there is unchanged. The design is the bundle root's
`docs/superpowers/specs/2026-09-26-diablo-animation-regeneration-design.md`
and the build plan
`docs/superpowers/plans/2026-09-26-diablo-animation-regeneration.md`.

## 1. Architecture

| Stage | Command | Service | Reads | Writes |
|---|---|---|---|---|
| Caption | `anim_recreate.py caption` | vLLM `:8000` | the source animations | `characters.yaml` (seed and captions) |
| Batch | `anim_recreate.py batch` | ComfyUI `:8188` | `characters.yaml`, `reviews.yaml`, the workflow template | `data/anims-ai/`; geometry rejections in `reviews.yaml` |
| Review | `anim_recreate.py review` | vLLM `:8000` | source, promoted sheets, their anchors | `reviews.yaml` |

`verify` audits `data/anims-ai/`; `preview` writes GIFs and touches neither
service.

Run order: `caption` (seeds and fills `characters.yaml`) → edit the file →
`batch --no-variants` → `review` → repeat until the base animations settle
(no more rejections) → `batch` (with the variants) → `review` → repeat until
the variants settle too → `verify`.

Rules that must survive any change:

- **The source is diablo-textures-exporter's output**, read in place from
  `DIA_SRC`. `source_tree` is its only reader: `manifest.json`'s
  `hd_contract` (with `"frame"` among its `units`) is what marks it as this
  exporter's output at all, and `ANIM_KINDS` (`player_anim`, `monster_anim`,
  `towner_anim`, `missile`) decides which of its entries are animations.
  Never write under `DIA_SRC`. `characters_file.seed_characters` is the one
  place that reads an animation's key for meaning (its grouping and anchor);
  everywhere else a key is only a name.
- **Outputs are exactly 2x RGBA with the soft outline.** Every promoted
  frame is `(2w, 2h)`, with alpha equal to the locked soft outline
  (`sheet_layout.soft_alpha`: the native mask at 2x nearest-neighbour,
  anti-aliased only within 1 HD px of its edge) — never beyond. A `skip`
  animation's frames get the hard mask instead (`nearest_frame`) and are
  never rendered. No render is promoted without passing
  `geometry_check.check_sheet`; `make verify`'s `frame_problem` re-checks the
  size, mode and exact alpha of every frame on disk, skip or not.
- **A sheet is the unit of attempt.** Its key,
  `<record dir>[@trn/<trn path>]/sNN`, is what every attempt, retry,
  promotion, audit folder and review verdict is keyed by — never an
  animation or a frame. An animation (a base or one variant) is done only
  once every one of its sheets is done.
- **Never loosen the gate to get a sheet through.** Fix its character's
  caption in `characters.yaml`, or the run's settings (`packing=`, `gutter=`,
  `background=`, `--workflow`) — never `geometry_check`'s thresholds.
- **Services are external.** The driver never starts or stops vLLM or
  ComfyUI. It checks `GET /v1/models` (vLLM) and `GET /queue` (ComfyUI). Its
  only state-changing ComfyUI calls are `POST /free`
  (`comfy_client.free_models`, at the end of `batch` — even after a
  failure, so vLLM has room to start — and the start of `review`) and
  `POST /interrupt` (`comfy_client.execute`, sent only by `comfy_client`) for
  a render that timed out or was stopped with Ctrl-C. After a failed or
  Ctrl-C'd sheet, `batch` deletes that sheet's own leftover renders
  (`comfy_client.sweep_outputs`, anchored to SaveImage's
  `<name>_a<attempt>-sheet_NNNNN_.png` naming, where `name` is
  `comfy_name(sheet key)`: its slashes become `+`). The attempt number in
  the ComfyUI-facing name keeps ComfyUI's cache from answering a rerun with
  an old render.
- **Unified memory.** vLLM holds about 73 GB and a render about 45 GB of the
  GB10's 121 GB. `batch` refuses below `MEMORY_FLOOR_GB` (45) unless
  `--no-memory-check` (`memcheck=0`).
- **Atomic writes.** `characters.yaml` and `reviews.yaml` go through
  `<name>.tmp` and a rename (`characters_file._dump`); every JSON record
  goes the same way (`anim_recreate.write_atomic`); every image —
  including a sheet's promoted frames, the skip copies, and the preview
  GIFs, no differently from any other image — goes through `<name>.pending`
  and a rename (`save_image_atomic`).
- **Resumable by construction, including `blocked` and `stale`.** A sheet's
  status is derived from its audit folder alone (`sheet_status`): `new`
  (never attempted), `stuck` (its latest judged attempt was rejected and it
  has `MAX_ATTEMPTS` (4) or more judged attempts — a failed attempt never
  counts, so a sheet that keeps failing on infrastructure is retried on
  every run and the run exits 1), `failed` (the latest attempt has no
  record), `rejected` (by the gate or the review), `missing` (promoted, but
  a frame it wrote is gone from disk), `done`. `status_of` layers the anchor
  rules on top: a sheet that is not `done` and whose anchor sheet is not
  `done` reports `blocked` — checked in `cmd_batch` before `--force` is even
  considered, so `batch --force` never renders a sheet with no anchor to
  paint against while that anchor is not done. A `done` sheet whose attempt
  record's anchor SHA-256 no longer matches its anchor's current promoted
  canvas reports `stale` and renders again, exactly like `new`. A stuck
  sheet whose workflow names a `fallback` is rendered once more through it
  on the next batch (`fallback_for`), and reported STUCK only once that
  attempt is rejected too. The next attempt's corrections
  (`corrections_for`) are the current review's issues while no later attempt
  was promoted; a geometry rejection gives the one
  `prompts.GEOMETRY_CORRECTION` sentence instead of the gate's own strings.
- **Renders never depend on other animations**, except that every sheet but
  a character's anchor animation's own first sheet depends on a promoted
  canvas: the anchor animation's first promoted sheet, or, for a variant
  sheet, its own base's promoted sheet of the same number instead. A sheet
  is consistent with its neighbours within one canvas by being painted
  together, and with the rest of its character through the anchor reference.
- **Only `comfy_client` knows node ids.**

## 2. Modules

| File | Owns | Must not |
|---|---|---|
| `anim_recreate.py` | CLI and stages (`caption`, `batch`, `review`, `verify`, `preview`, `--dry-run`), selection, dependency order, staleness, preflights, audit folders, promotion | know node ids or YAML syntax |
| `source_tree.py` | reading and validating `manifest.json`, `meta.json` and palette JSON; animations, frames, variants; each frame's RGB guide from its `*.idx.png` through its palette and, for a variant, its TRN | talk to services or write files |
| `characters_file.py` | `characters.yaml` and `reviews.yaml`: shape, validation, the seeded grouping, atomic save | do I/O beyond its own files |
| `sheet_layout.py` | per-direction cell boxes, packing into canvases, guide canvas, slicing, the locked soft alpha, edge decontamination | talk to services or know files |
| `geometry_check.py` | per-cell shift and interior edge agreement, frame-to-frame consistency, gutter bleed | know files or the audit tree |
| `colour_match.py` | the Lab transfer, restricted to a mask | know animations or files |
| `prompts.py` | caption, render and review prompts, VLM payloads, `parse_review`, `vlm_is_serving` | know files or make targets |
| `comfy_client.py` | ComfyUI HTTP, the workflow registry, node ids, staging, output lookup, interrupt, sweep | decide what to render |
| `anim_qwen21_i2i.json` | the ComfyUI API graph | — |

`colour_match.py`, `comfy_client.py` and the attempt, status and fallback
logic are ported from the Atlantis kit with the smallest changes that fit
sheets instead of rooms. Only `source_tree` reads `DIA_SRC`, and never writes
under it.

## 3. The render path

Per sheet (`anim_recreate.render_sheet_job`, `sheet_inputs`, `finish_sheet`):

1. **Guide** (`sheet_inputs`, `sheet_layout.guide_frame`). Each cell's frame
   is read through `source_tree.frame_rgba` (through its TRN first, for a
   variant), its transparent pixels filled from their nearest opaque
   neighbours (`fill_transparent`, `GUIDE_FILL_RINGS` = 4 native px), then
   upscaled 2x with Lanczos and laid over the flat `background` colour
   through the hard mask. `guide_canvas` pastes each cell's guide region
   onto the sheet.
2. **Layout** (`sheet_layout.plan_sheets`, cached per animation in
   `anim_recreate.layout`). Each direction (group) gets one cell size: the
   union of its frames' opaque boxes at 2x, plus `CELL_MARGIN` (8 HD px),
   plus `GUTTER` HD px between cells. Cells pack into a roughly square grid;
   canvases round up to a multiple of `ALIGN` (32, Qwen 2.1's
   `resolution: 0` needs it). `SHEET_PACKING` (`--packing`) is `direction`
   (one direction per canvas, the default) or `packed` (consecutive
   directions of one animation, stacked while the canvas stays at or under
   `MAX_CANVAS_PX`, 1,048,576 px); a direction that alone exceeds that gets a
   canvas sized to fit it. A direction is never split across canvases. A
   variant's layout equals its base's, so variant sheet `sNN` pairs with
   base sheet `sNN`.
3. **Anchor** (`anchor_key`, `status_of`). A character's anchor animation's
   first sheet renders with no anchor. Every other base sheet gets the
   anchor animation's first promoted sheet as its second reference image. A
   variant sheet gets its own base's promoted sheet of the same number
   instead. `--no-anchor` (`anchor=0`) is a spike variant that paints every
   sheet against its guide only.
4. **Order and staleness** (`select_jobs`, `sheet_jobs`, `sheet_status`,
   `status_of`). `batch` renders every character's anchor animation, then
   the other base animations, then (unless `--no-variants`/`variants=0`)
   the recolour variants, in that order. A sheet whose anchor is not yet
   `done` reports `blocked` and waits, even under `--force`. Each attempt
   records the SHA-256 of the anchor canvas it was painted against
   (`anchor.sha256` in `attempt-N.json`); when a `done` sheet's record no
   longer matches its anchor's current promoted canvas, the sheet is
   `stale` and renders again.
5. **Render** (`comfy_client.render_sheet`). The guide canvas, the anchor
   canvas (or none), the positive prompt (`prompts.render_prompt`),
   `PAINTED_NEGATIVE` and the seed (`SEED` 42, plus `attempt - 1`) go to the
   default workflow `qwen-image-2.1-i2i` (denoise 1.0, 40 steps, cfg 1.0);
   a sheet stuck after `MAX_ATTEMPTS` (4) rejections renders once more
   through the fallback `qwen-image-2.1-i2i-faithful` (the same graph at
   denoise 0.9), both as in Atlantis until the spike says otherwise.
6. **Slice** (`sheet_layout.frame_rgb`, `finish_frame`). Each cell is cut
   back to its frame at `(2w, 2h)`, at the same place in the frame. Alpha is
   the locked soft outline; a pixel with partial alpha takes its colour from
   the nearest fully opaque pixel (`fill_transparent`, `EDGE_FILL_RINGS` = 2
   HD px), so the background never tints the outline.
7. **Colour match** (`colour_match.match`). Each frame is matched in Lab
   toward its own guide, over its outline mask only, at `--match-strength`
   (`DEFAULT_MATCH_STRENGTH` 0.5).
8. **Checks** (`geometry_check.check_sheet`), then promotion: every frame of
   the sheet is written (`*.pending`, then renamed) and the attempt's record
   says `promoted: true`. A rejection goes to `reviews.yaml` as
   `source: geometry`.

A render that raises (a ComfyUI error, a timeout, the wrong canvas size,
Ctrl-C) writes `attempt-N.error.txt` (workflow, seed, stage, seconds, error)
and no `attempt-N.json`, so the attempt reads as failed. `batch` then sweeps
the sheet's stray outputs; on Ctrl-C `comfy_client` has already sent
`/interrupt`, and `batch` re-raises after the sweep and `/free`. Failed
attempts never count toward STUCK, and the next attempt still carries the
current review's corrections (see §1).

Node ids in `anim_qwen21_i2i.json`: 1 LoadImage (the guide canvas — also the
VAEEncode source and the encoder's `images.image_1`), 2 LoadImage (the
anchor canvas, `images.image_2`; the node and that input key are deleted
from the graph together when there is no anchor), 4 CLIPLoader
(`qwen3vl_8b_bf16`), 5 UNETLoader (`qwen_image_2.1_bf16`), 6 VAELoader
(`qwen_image_2.1_vae_bf16`), 9 TextEncodeQwenImage21 (`prompt`,
`negative_prompt`, `resolution: 0`, `images.image_1`/`images.image_2` as the
two references), 11 VAEEncode (the guide canvas as the starting latent),
13 KSampler (seed, 40 steps, cfg 1.0, euler/simple, denoise 1.0 — the
fallback workflow's `settings` overwrite `denoise` to 0.9 on this same
node), 14 VAEDecode, 15 SaveImage (`filename_prefix` set per sheet to
`dia/<comfy name>_a<attempt>-sheet`).

The 2.1 encoder's reference slots are autogrow inputs and must be addressed
as `images.image_1` / `images.image_2`: a flat `image_1` key arrives as an
unexpected keyword and kills the render (the Dig and AITD kits' live
checks). `resolution: 0` relies on every canvas being a multiple of 32 in
both dimensions, which `plan_sheets` guarantees.

**A graph is only validated by rendering it.** The template test checks the
graph against its registry record, not against ComfyUI's real node schemas.
Render one sheet through any new or edited graph before trusting it.

## 4. Prompts

- `CAPTION_QUESTION` (vLLM `Qwen/Qwen3.8-27B`, one call per character): the
  VLM sees a contact sheet at 4x nearest-neighbour (`CAPTION_SCALE`,
  `contact_sheet`, up to `CONTACT_COLUMNS` (8) per row): the anchor
  animation's first frame in each direction, then, as a second image, the
  first frame of every other animation that has frames. It answers, under
  300 words, in six sections: SUBJECT, BODY AND MATERIALS, EQUIPMENT,
  COLOURS, SHADOW, INVARIANTS. Every caption is read by hand before a batch.
- `render_prompt` builds the positive prompt in order: `SPRITE_RULES`
  (naming the guide as the workflow's `reference`, `<image1>`, with the
  sheet's cell count); `ANCHOR_NOTE` naming the anchor (`<image2>`) when the
  sheet has one; `VARIANT_NOTE` for a recolour variant, which also strips
  the caption's COLOURS section (`without_colours`) since a variant's
  colours come from the guide, not the caption; `"REFERENCE OBSERVATIONS:"`
  plus the caption; then, when the sheet carries corrections, either the
  current review's issues or, after a geometry rejection, the single
  `GEOMETRY_CORRECTION` sentence (the gate's own issue strings mean nothing
  to the diffusion model); a closing note that the reference image outranks
  the caption and that a correction asking for pixel art, dithering or a
  photograph is never followed. `PAINTED_NEGATIVE` is the negative prompt
  (node 9's `negative_prompt`; ignored at cfg 1, as in Atlantis).
- `REVIEW_QUESTION` sends the guide canvas (image 1), the render canvas
  (image 2) and the anchor canvas when there is one (image 3), and rejects
  on identity (a different figure than the guide or the anchor), cross-cell
  consistency, invention, a figure bleeding into another cell or the
  background, or a photographic/3D-render/pixel-art style. Returns
  `{"accepted", "issues"}`; `parse_review` (the Atlantis parser) tolerates
  fences and chatter and refuses a verdict that contradicts its issues.
  `make review` sends up to `--concurrency` (`DEFAULT_CONCURRENCY` 8)
  requests at once, so vLLM batches them.

## 5. Testing

```bash
make check   # py_compile every module
make test    # unittest discover: every test_*.py
```

Tests never touch the network or the GPU. `testkit.py` is the one shared
test-support module. Rules, as in Atlantis:

- one test module per production module;
- data-only variations are one `subTest` table;
- keep the suite small: a test covers one behaviour, and the facets of one
  run are asserted in one test; add a separate test only for a different
  behaviour or a named regression;
- a rule is tested once, at the layer that owns it;
- a regression test names what it guards.

The miniature source (`testkit.make_source`, from `DEFAULT_ANIMS`) has five
animations: `monsters/zombie/zombien.cl2` and `.../zombiew.cl2` (2 directions
of 3 and 4 frames, each with the `grey.trn` variant), `missiles/fireba1.cl2`
and `fireba2.cl2` (1 direction of 3 frames each, 24x24), and
`monsters/darkmage/dmagew.cl2` (8 directions with no frames at all — the
kit's one animation with nothing to render). `write_characters`, `run_cli`,
`fake_render`, `comfy_stub` and `vlm_stub` work as in Atlantis and the Dig
kit; never re-implement these in a test module.

Three test classes run on the real corpus, whenever
`../diablo-textures-exporter/out` (or `DIA_SRC`) exists;
`testkit.REAL_SRC` and `testkit.needs_real_corpus` are their one definition
of it:

- `test_source_tree.RealCorpusTests` pins the manifest: 1,056 `player_anim`,
  334 `monster_anim`, 21 `towner_anim` and 380 `missile` animations, 145,560
  frames in all, and 182 animations carrying a recolour variant.
- `test_sheet_layout.RealCorpusTests` lays out every real animation: every
  frame lands in exactly one sheet, 11,394 sheets at the defaults, the
  largest 1952x1440 (`monsters/nkr/nkrd.cl2`).
- `test_anim_recreate.RealCorpusTests` pins the sheet gate: a fixed sample of
  50 animations' own guide canvas, run through `finish_sheet` at
  `DEFAULT_MATCH_STRENGTH`, passes `geometry_check.check_sheet` on every
  sheet (a perfect render of any real sheet is always promotable).

## 6. Live checks and the spike

Live checks, spikes and runs are in `NOTES.md`.

The starting values below are the Atlantis kit's where one carries over
unchanged, and are what the spike (design spec §10) recalibrates for
sprites; record what changes, and why, in `NOTES.md`:

- Layout: `SHEET_PACKING` = `"direction"`; `GUTTER` = 16 HD px;
  `CELL_MARGIN` = 8 HD px; `ALIGN` = 32; `MAX_CANVAS_PX` = 1,048,576;
  `BACKGROUND` = `"grey"` (128, 128, 128) (the alternative, `"dark"`, is
  (24, 24, 24)); the anchor reference on by default (`--no-anchor` off).
- Render: the default workflow `qwen-image-2.1-i2i` at denoise 1.0, 40
  steps, cfg 1.0; its fallback `qwen-image-2.1-i2i-faithful` at denoise 0.9;
  `DEFAULT_MATCH_STRENGTH` = 0.5; `MAX_ATTEMPTS` = 4; `SEED` = 42.
- Checks (`geometry_check.py`): `MAX_SHIFT` = 0.5 native px;
  `MIN_SHIFT_PIXELS` = 200; `EDGE_THRESHOLD` = 80.0;
  `RENDER_EDGE_THRESHOLD` = 60.0; `MIN_EDGE_AGREEMENT` = 0.80;
  `MIN_CELL_EDGES` = 30; `FLICKER_FACTOR` = 2.0; `FLICKER_FLOOR` = 4.0;
  `GUTTER_WARN` = 12.0 levels.
