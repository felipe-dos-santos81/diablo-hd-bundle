# Diablo Animation Regeneration — Design

Date: 2026-09-26
Status: approved design, pending spec review

## 1. Problem

Regenerate the animated sprites of *Diablo* + *Hellfire* (Blizzard North,
1996/1997), already extracted by `diablo-textures-exporter` (`dtx`) into
`diablo-textures-exporter/out/`, as painted high-definition art at exactly 2x
their native size, with local models driven through ComfyUI. The kit is a
fork of the *Fate of Atlantis* kit
(`~/code/atlantis-hd-bundle/atlantis-texture-enhancement`, design
`docs/superpowers/specs/2026-09-24-atlantis-regeneration-design.md` there):
stages joined by hand-editable YAML, resumable runs, an audit folder per
attempt, a deterministic geometry gate and a vision-model review loop.
Everything this document does not change is as that design and that kit's
AGENTS.md describe; this document states the differences.

The export holds about 153,000 frames of four families. This is the first
sub-project, and it takes the largest one, the animations:

| Kind | Animations | Frames | Directions |
|---|---|---|---|
| `player_anim` | 1,056 (4 classes x armour x weapon x action) | 108,760 | 8 |
| `monster_anim` | 334 (182 with recolour tables) | 31,193 | 8 (23 have 1) |
| `towner_anim` | 21 | 790 | 8 or 1 |
| `missile` | 380 | 4,817 | 1 per file |

Recolour variants add about 74,000 frames (97 distinct TRN tables over the
monster animations), for about 220,000 frames in all. UI images, level
tilesets and static sprites are later sub-projects.

The frames are small: measured over a sample of 100 animations, the median
figure box over one direction is 64x70 native px for players, 88x76 for
monsters (largest 200x156), 37x63 for towners and 66x51 for missiles, with
12–16 frames per direction. Shadows are opaque black pixels inside the
sprite's mask.

## 2. Decisions

| Question | Decision |
|---|---|
| Asset scope | **Animations:** every `player_anim`, `monster_anim`, `towner_anim` and `missile` asset in the manifest, including the two overridden `@DIABDAT.MPQ` versions |
| What consumes the output | **A future DevilutionX fork** loading HD true-colour sprites (out of scope). Every output honours the manifest's `hd_contract` with k = 2 |
| Look | **Painted repaint**, as in Atlantis: new painted detail, same pose and silhouette |
| Scale | **2x** (a 1280x960 game) |
| Recolour variants | **Repaint each variant** as its own animation, anchored to its base |
| Silhouette | **Locked, soft edge:** alpha is the source mask at 2x nearest-neighbour, anti-aliased only within 1 HD px of its edge, never beyond |
| Frame consistency | **Approach A, sheet repaint:** all frames of a direction are repainted together on one canvas through Qwen-Image 2.1 img2img, with a per-character anchor as second reference |
| Architecture | **Fork** the Atlantis kit into a Diablo kit; the Atlantis kit is not touched |
| Repository | **Monorepo** `~/code/diablo-hd-bundle`, mirroring the Atlantis and Dig bundles: `diablo-textures-exporter/` (subtree-merged with history) and `diablo-texture-enhancement/` (new) |

Approaches rejected:

- **B, video repaint with Wan 2.2** (per-direction clips with a reference
  image). Temporal consistency is built in, but the models are not installed
  (about 30–60 GB), the path is unproven in these kits, clips must be 4n+1
  frames at 480p or more while these are 8–20 tiny frames, loops must close,
  and there is no alpha.
- **C, keyframe then propagate** through Qwen-Image-Edit 2511. One render per
  frame (about 220,000) and the model that drifted 0.4–2 native px in the
  Atlantis spike.
- **Derive variants from the base** by shifting remapped colours in Lab. Cheap
  and consistent, but the user chose a repaint per variant.
- **Faithful upscale** (SeedVR2 or an ESRGAN model). The user chose a
  painted repaint.

## 3. Goals and non-goals

Goals:

- Every base animation and every recolour variant rendered, checked and
  promoted frame by frame at exactly `(2w, 2h)` RGBA, with the locked soft
  outline; every `skip` animation written as a nearest-neighbour 2x.
- Frames consistent within a direction (painted together), across a
  character's directions and animations (the anchor), and between a variant
  and its base (the base as anchor).
- Geometry and frame-to-frame consistency measured objectively on every
  frame before promotion.
- Resumable, auditable runs with the Atlantis attempt, STUCK and fallback
  rules.

Non-goals:

- UI images, level tilesets, static sprites (items, objects, UI and level
  sprites): later sub-projects.
- The player TRNs `plrgfx/stone.trn` and `plrgfx/infra.trn`: they are engine
  effects (stone curse, infravision), not variants in the metadata; the HD
  engine handles them.
- The HD engine, repacking, and any change to the exporter.
- A review gallery.

## 4. Repository and data flow

```
~/code/diablo-hd-bundle/                git monorepo
  docs/superpowers/                      this spec and its plan
  diablo-textures-exporter/              dtx, subtree-merged with history
    out/                                 the export (gitignored)
  diablo-texture-enhancement/            the new kit
    data/anims-ai/                       outputs (gitignored)
```

The exporter lives today as its own git repository inside the bundle
directory, with no remote. The plan's first task moves that repository to
`~/code/diablo-textures`, subtree-merges it into the bundle at
`diablo-textures-exporter/` (as was done for the Dig), and then moves the
gitignored `out/` from the old location to `diablo-textures-exporter/out/`,
so the export is not re-extracted.
The bundle's `.gitignore` is the Dig bundle's (`out/`, `data/`,
`reviews.yaml`, `*.pending`, `*.tmp`, Python caches, `.superpowers/`,
`.DS_Store`).

Input: `../diablo-textures-exporter/out/` (override with `DIA_SRC`).
Output: `data/anims-ai/` (override with `DIA_DST`), mirroring each asset's
record directory under `assets/`:

```
data/anims-ai/monsters/zombie/zombiew.cl2/d0/f000.png                 base frame
data/anims-ai/monsters/zombie/zombiew.cl2/@trn/monsters/zombie/grey.trn/d0/f000.png
data/anims-ai/@DIABDAT.MPQ/monsters/goatlord/goatld.cl2/...          an overridden version
data/anims-ai/.quality/<sheet key>/attempt-N.*                        the audit folder
```

The frame file names are the ones in the asset's `meta.json` (`png`), so a
loader maps each output to its frame without a table.

```
DIA_SRC ──[make caption]──▶ characters.yaml ──(you edit)──┐
            vLLM up                                         ▼
data/anims-ai/ ◀──[make batch]── characters.yaml + reviews.yaml (rejects only)
   │               ComfyUI up, vLLM stopped
   ├──[make review]──▶ reviews.yaml   (vLLM up)
   └──[make preview]─▶ data/preview/*.gif
```

## 5. Units

| Module | Owns | Must not |
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
sheets instead of rooms. Only `comfy_client` knows node ids. Only
`source_tree` reads `DIA_SRC`, and never writes under it.

### 5.1 `characters.yaml`

One entry per character, seeded by the first `caption` run:

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

Seeding groups animations by their directory for monsters, players and
towners, and missiles by file stem without its trailing digits
(`acidbf1`..`acidbf16` form `missiles/acidbf`): 251 characters on the current
export (108 player, 56 monster, 13 towner, 72 missile, and the 2 overridden
`@DIABDAT.MPQ` versions). The seeded anchor is the players' standing
animation (stem ending `st`), the monsters' neutral one (ending `n`), and
otherwise the first animation, never one without frames while another has
some. The
seed is only a proposal: the user may regroup, re-anchor or skip by hand,
and `characters_file.seed` is the one place that reads names for meaning.
Caption fills blank captions only; `force=1` redoes all.

## 6. The render path

A **sheet** is one canvas and the unit of render, attempt, retry and
promotion. Its key is `<record dir>[@trn/<trn path>]/sNN`. An animation (a
base or one variant) is done when all its sheets are done.

1. **Guide.** Each frame's index image goes through its palette (and TRN) to
   RGB, is upscaled 2x with Lanczos, and everything outside the mask is the
   flat `BACKGROUND` colour.
2. **Layout.** Each direction gets one cell size: the union of its frames'
   opaque boxes at 2x, plus `CELL_MARGIN` (8 HD px), plus `GUTTER` HD px
   between cells. Cells pack left to right, top to bottom, into canvases whose
   sides are multiples of 32 (Qwen 2.1's `resolution: 0` needs it). A
   direction is never split across canvases. `SHEET_PACKING` chooses one
   direction per canvas (`direction`) or consecutive directions of one
   animation up to `MAX_CANVAS_PX` (1,048,576) (`packed`). A direction that
   alone exceeds `MAX_CANVAS_PX` gets a canvas that fits it (1,866 sheets
   with variants; the largest, `monsters/nkr/nkrd.cl2`, is 1952x1440, about
   2.8 MP). A
   variant's layout equals its base's: a TRN changes colours, not masks, so
   variant sheet `sNN` pairs with base sheet `sNN`.
3. **Anchor.** A character's anchor animation renders first, with the guide
   as its only reference. Every other base sheet of the character gets the
   anchor's first promoted sheet as a second reference image. A variant sheet
   gets its base's promoted sheet `sNN` instead.
4. **Order and staleness.** Batch renders anchors, then other base
   animations, then variants (`--no-variants` stops after the bases). A sheet
   whose anchor is not promoted waits (status `blocked`, reported, not an
   error). Each attempt records the SHA-256 of the anchor sheet it was
   painted against; when that differs from the anchor's current promoted
   sheet, the sheet is `stale` and renders again.
5. **Render.** `comfy_client.render_sheet` sends the guide canvas, the anchor
   (or none), the prompt and a seed through the default workflow
   `qwen-image-2.1-i2i` (denoise 1.0, 40 steps, cfg 1.0), with
   `qwen-image-2.1-i2i-faithful` (denoise 0.9) as the fallback for a stuck
   sheet, both as in Atlantis until the spike says otherwise.
6. **Slice.** Each cell is cut back to its frame at `(2w, 2h)`, at the same
   place in the frame. Alpha is the locked soft outline: the mask at 2x
   nearest-neighbour, anti-aliased only within 1 HD px of its edge. A pixel
   with partial alpha takes its colour from the nearest fully opaque pixel,
   so the background never tints the outline.
7. **Colour match.** Each frame is matched in Lab toward its own guide, over
   its mask only, at `DEFAULT_MATCH_STRENGTH` (0.5).
8. **Checks** (§8), then promotion: every frame of the sheet is written
   (`*.pending`, then renamed) and the attempt's record says promoted. A
   rejection goes to `reviews.yaml` as `source: geometry`.

Statuses, as in Atlantis plus two: `new`, `blocked`, `stale`, `failed`,
`rejected`, `missing`, `stuck`, `done`. `MAX_ATTEMPTS` stays 4. A `skip`
animation is written as a nearest-neighbour 2x with the hard mask, never
rendered.

## 7. Prompts and review

**Caption** (vLLM `Qwen/Qwen3.8-27B`, one per character). The VLM sees a
contact sheet at 4x nearest-neighbour: the anchor animation's first frame in
each direction and the first frame of each other animation. It answers, in
under 300 words: SUBJECT, BODY AND MATERIALS, EQUIPMENT, COLOURS, SHADOW,
INVARIANTS. Every caption is read by hand before a batch.

**Render prompt** (`render_prompt`), in order:

1. `SPRITE_RULES`: the canvas holds N frames of one animation of a game
   sprite on a flat background; repaint every cell as a hand-painted
   dark-fantasy game sprite, keeping each cell's pose, outline and position;
   the same light and the same painting in every cell; leave the background
   and gutters flat; keep the shadow a flat dark shadow.
2. The anchor note when there is an anchor: image 2 is the same character
   already painted; match its painting.
3. REFERENCE OBSERVATIONS: the caption. A variant's prompt drops the COLOURS
   section and says its colours follow the guide.
4. Corrections: the current review's issues, or `GEOMETRY_CORRECTION`.

`PAINTED_NEGATIVE` goes to the negative prompt as in Atlantis (ignored at
cfg 1).

**Review** (`REVIEW_QUESTION`): the guide canvas, the render canvas and the
anchor. Accept only when the render is the same character as the guide and
the anchor, consistent across cells, invents no object, and keeps each cell
separate. Returns `{"accepted", "issues"}`; `parse_review` is Atlantis's.
`review` sends up to `--concurrency` (default 8) requests at once, so vLLM
batches them.

## 8. Checks

Every frame of a sheet, at native size after a 2x box downscale:

- **Size and outline:** RGBA, exactly `(2w, 2h)`, alpha equal to the locked
  soft outline. Computed, so it cannot fail in batch; `verify` re-checks it
  on disk.
- **Shift:** phase correlation inside the mask; fails at `MAX_SHIFT` (0.5
  native px) or more. A frame with fewer than `MIN_SHIFT_PIXELS` (200) opaque
  native pixels passes.
- **Interior edge agreement:** Atlantis's hysteresis (`EDGE_THRESHOLD` 80,
  `RENDER_EDGE_THRESHOLD` 60, within 1 px) over the mask eroded by 1 native
  px, so the locked outline cannot inflate it; fails below
  `MIN_EDGE_AGREEMENT` (0.80). A frame with fewer than `MIN_CELL_EDGES` (30)
  strong source edge pixels passes.
- **Consistency:** for consecutive frames i, i+1 of a direction, the mean
  absolute difference of the render over the intersection of their masks,
  `D_r`, against the source's, `D_s`; the pair fails when
  `D_r > FLICKER_FACTOR * D_s + FLICKER_FLOOR` (2.0 and 4 levels).
- **Gutter bleed:** a gutter whose mean moves more than `GUTTER_WARN` (12
  levels) from `BACKGROUND` is printed as a warning.

Every starting value above is recalibrated by the spike (§10) and recorded in
AGENTS.md. The rule from Atlantis stands: do not loosen the gate to get a
sheet through; fix its caption or its settings.

## 9. Errors, services and commands

As in Atlantis: services are external (the driver checks `GET /v1/models`
and `GET /queue`; its only state-changing ComfyUI calls are `POST /free` and
`POST /interrupt`); a render that raises writes `attempt-N.error.txt` and no
record, never counts toward STUCK, and exits 1 at the end of the run; stray
outputs are swept, anchored to SaveImage's
`<sheet key>_a<attempt>-sheet_NNNNN_.png` naming (the key's slashes become
`+`); `batch`
refuses below `MEMORY_FLOOR_GB` (45) unless `--no-memory-check`; YAML and
JSON are written through `.tmp`, images through `.pending`.

| Target | What it does |
|---|---|
| `make caption [character=] [force=1]` | Seed and caption `characters.yaml` |
| `make dry-run [character=] [anim=]` | Sheets, cells, canvas sizes, dependency order, stale and blocked sheets |
| `make batch [character=] [anim=] [variant=] [variants=0] [workflow=] [strength=] [memcheck=0] [force=1]` | Render and promote into `data/anims-ai/` |
| `make review [character=] [concurrency=8] [force=1]` | Write `reviews.yaml` |
| `make preview [character=] [anim=]` | An animated GIF per direction: source (nearest-neighbour 2x) and render side by side |
| `make verify [character=]` | Audit `data/anims-ai/` against the manifest, the 2x contract, the outline and the attempts |
| `make server` / `install` / `check` / `test` / `clean` | As in Atlantis |

`character=` selects by character key, `anim=` by record directory and
`variant=` by TRN path (of the variants, only those); all accept several
space-separated values. The spike's layout switches are `packing=`,
`gutter=`, `background=` and `anchor=0`. Environment overrides: `DIA_SRC`,
`DIA_DST`, `DIA_CHARACTERS`, `DIA_REVIEWS`, `DIA_WORKFLOW`,
`DIA_MATCH_STRENGTH`, `COMFY_URL`, `COMFY_DIR`, `VLM_BASE_URL`, `VLM_MODEL`,
`VLM_API_KEY`.

## 10. Testing and the spike

**Unit tests** (no GPU, no network), one module per production module, the
Atlantis rules (`subTest` tables, a rule tested once at the layer that owns
it). `testkit.py` builds a miniature `dtx` output: `manifest.json`, a
two-direction monster anchor and walk that both carry a grey TRN variant, a
two-file missile group, an animation with no frames, index images, a palette
JSON and the TRN; plus `fake_render` (the guide canvas, optionally through a
transform such as a shift), `comfy_stub` and `vlm_stub`.

**Real-corpus tests**, whenever `DIA_SRC` exists: every animation in the
manifest lays out (and the largest canvas is reported); a perfect render (the
guide itself) of a fixed sample of 50 animations passes every check through
`finish_sheet`.

**Spike** (a gated plan task, before the full run; recorded in `NOTES.md`).
Animations: the warrior walk `plrgfx/warrior/wlm/wlmwl.cl2` and one player
attack, the zombie walk `monsters/zombie/zombiew.cl2` and its `grey.trn`
variant, the largest monster, the smith, the missile `missiles/fireba*`, and
one inferred-width monster animation (`monsters/magma/magball1.cel`).
Variants compared, one at a time from the defaults:

1. `SHEET_PACKING`: `direction` against `packed`;
2. `GUTTER`: 16 against 32 HD px;
3. the anchor reference on and off;
4. denoise 1.0 against 0.9;
5. `BACKGROUND`: neutral grey (128, 128, 128) against dark (24, 24, 24).

Measured: seconds per canvas, gate pass rate, the consistency ratios, the
largest canvas's time and memory. The thresholds of §8 are recalibrated from
these renders and from perfect and deliberately broken ones. The user picks
the settings from the `make preview` GIFs.

**Full run** (the last plan task): caption all → hand-fix → `batch
variants=0` and `review` until the bases settle → `batch` and `review` until
the variants settle → `verify`. Measured on the export: 11,394 base sheets,
17,410 with the variants (11,386 packed), about 9.8 gigapixels of canvas a
pass; at the Atlantis rate (about 50 s per 1.2 MP) that is roughly 110–120 h
a pass before retries, so the run spans a week or more.

## 11. Definition of done

- Every base animation and recolour variant promoted, or reported STUCK with
  its reason in `NOTES.md`.
- `make verify` clean.
- `make test` passes, including the real-corpus tests.
- `NOTES.md` records the spike's decisions and the full run's statistics.
