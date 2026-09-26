# Diablo Animation Regeneration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Regenerate every Diablo + Hellfire animation frame (players, monsters, towners, missiles and every monster recolour variant) as painted HD art at exactly 2x, with the outline locked, through local ComfyUI models, a deterministic gate and a VLM review loop.

**Architecture:** `~/code/diablo-hd-bundle` becomes a monorepo holding the existing exporter (subtree-merged with its history) and a new kit, `diablo-texture-enhancement/`, built on the Atlantis/Dig kit pattern: stages joined by hand-editable YAML (`characters.yaml`, `reviews.yaml`), an audit folder per attempt, resumable status derived from it. The unit of work is a **sheet**: all frames of one direction laid out as cells on one canvas and repainted in one Qwen-Image 2.1 img2img pass, with the character's anchor sheet as a second reference image; the sheet is cut back into frames, colour-matched, given the locked soft outline and checked frame by frame before promotion.

**Tech Stack:** Python 3.12, Pillow, numpy, PyYAML, `unittest`; ComfyUI (Qwen-Image 2.1, `TextEncodeQwenImage21` with two reference images) on `:8188`; vLLM `Qwen/Qwen3.8-27B` on `:8000`.

**Spec:** `docs/superpowers/specs/2026-09-26-diablo-animation-regeneration-design.md` (bundle root). The kit patterns it builds on are in `~/code/thedig-hd-bundle/thedig-texture-enhancement` (its `AGENTS.md`); read it once before Task 2. Every module's code below was written and run as a prototype against the real export before this plan was written: the suite passed (58 tests, including the real-corpus ones), and each task's stage passed on its own.

## Global Constraints

- Python ≥ 3.12. Kit runtime dependencies are exactly `pillow>=10`, `pyyaml>=6`, `numpy>=1.26`. No new dependencies.
- `SCALE = 2`. Every output frame is RGBA, exactly `(2w, 2h)` of its native frame. A rendered frame's alpha is the **locked soft outline**: the native mask at 2x nearest-neighbour, then a 3x3 box average (`sheet_layout.soft_alpha`); a skipped animation's alpha is the hard 2x mask (`hard_alpha`).
- The kit reads `DIA_SRC` only through `source_tree`, never writes under it, and never reads game files. Animation keys are record directories under `assets/`, used only as names; only `characters_file.seed_characters` reads names for meaning.
- Never commit art: the exporter's `out/`, the kit's `data/` and `reviews.yaml` stay gitignored (the bundle `.gitignore` already says so). `characters.yaml` is committed.
- Only `comfy_client` knows ComfyUI node ids.
- Services are external: the driver never starts or stops vLLM or ComfyUI; they never run together; `MEMORY_FLOOR_GB = 45` guards `batch`.
- Atomic writes: YAML/JSON through `<name>.tmp` + rename, images through `<name>.pending` + rename.
- Gate starting values (the spike recalibrates them): `MAX_SHIFT = 0.5`, `EDGE_THRESHOLD = 80.0`, `RENDER_EDGE_THRESHOLD = 60.0`, `MIN_EDGE_AGREEMENT = 0.80`, `MIN_SHIFT_PIXELS = 200`, `MIN_CELL_EDGES = 30`, `FLICKER_FACTOR = 2.0`, `FLICKER_FLOOR = 4.0`, `GUTTER_WARN = 12.0`.
- Layout: `CELL_MARGIN = 8`, `GUTTER = 16`, `ALIGN = 32`, `MAX_CANVAS_PX = 1_048_576`, `SHEET_PACKING = "direction"`, `BACKGROUND = "grey"` (128, 128, 128; `"dark"` is 24, 24, 24). A direction is never split across sheets.
- `SEED = 42` (attempt N uses `SEED + N − 1`), `MAX_ATTEMPTS = 4`, `DEFAULT_WORKFLOW = "qwen-image-2.1-i2i"` (denoise 1.0) with fallback `qwen-image-2.1-i2i-faithful` (0.9), `DEFAULT_MATCH_STRENGTH = 0.5`, `DEFAULT_CONCURRENCY = 8`.
- Environment prefix `DIA_` (`DIA_SRC`, `DIA_DST`, `DIA_PREVIEW`, `DIA_CHARACTERS`, `DIA_REVIEWS`, `DIA_WORKFLOW`, `DIA_MATCH_STRENGTH`); `COMFY_URL`, `COMFY_DIR`, `VLM_BASE_URL`, `VLM_MODEL`, `VLM_API_KEY` as in the other kits.
- Kit tests: `unittest`, no GPU, no network; `testkit.py` is the only shared test-support module; one test module per production module; real-corpus tests skip when the export is absent.
- The bundle has no remote. Do not add one or push unless the user asks.
- Every commit message ends with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

## Review Focus

1. **A render that fails mid-sheet** (a ComfyUI error, or an image of the wrong size): the attempt must read `failed` (an `error.txt`, no record), the sheet's stray outputs swept, the batch must go on and exit 1, and the next batch must retry it without counting it toward STUCK. Pinned in Task 9 (`test_a_failed_render_leaves_an_error_and_no_record`).
2. **Ctrl-C during a render**: the error is recorded, the sheet's outputs swept, ComfyUI's models freed, and the interrupt re-raised. Pinned in Task 9 (`test_ctrl_c_sweeps_frees_and_stops`).
3. **ComfyUI down, a model file missing, or vLLM still holding the memory**: `batch` must refuse with the reason (exit 2) before rendering anything. Pinned in Task 9 (`test_batch_refuses_without_comfyui_its_models_or_memory`).
4. **A `characters.yaml` out of step with the manifest** (an animation left out, or an anchor with no frames while its character has some): every stage must refuse with the reason (exit 2), never render or wait forever. Pinned in Task 4 (coverage) and Task 9 (`test_characters_yaml_must_match_the_manifest`).
5. **A frame, or a whole direction, with no opaque pixel** (the export has an animation with no frames at all, `monsters/darkmage/dmagew.cl2`): it must come out fully transparent at 2x, never crash the layout or the checks. Pinned in Task 5 (`test_an_empty_direction_still_gets_cells`, `test_an_empty_frame_comes_out_fully_transparent`) and by `dmagew.cl2` in every driver test's miniature source.

---

## File Structure

```
~/code/diablo-hd-bundle/
  README.md                         the two projects and their order (Task 1)
  .gitignore                        already committed (out/, data/, reviews.yaml, caches)
  docs/superpowers/specs/2026-09-26-diablo-animation-regeneration-design.md
  docs/superpowers/plans/2026-09-26-diablo-animation-regeneration.md   (this plan)
  diablo-textures-exporter/         subtree of ~/code/diablo-textures (Task 1); out/ moved back in
  diablo-texture-enhancement/       the new kit
    pyproject.toml, Makefile, run_batch.sh, run_server.sh   (Task 2)
    colour_match.py                 Lab transfer over a mask, from the Dig kit (Task 2)
    source_tree.py                  the export's manifest, frames, palettes, TRNs (Task 3)
    testkit.py                      miniature export (Task 3); driver stubs (Task 9)
    characters_file.py              characters.yaml, reviews.yaml, the seed (Task 4)
    sheet_layout.py                 cells, sheets, guide canvas, slicing, soft outline (Task 5)
    geometry_check.py               per-frame shift and edges, consistency, gutter bleed (Task 6)
    comfy_client.py, anim_qwen21_i2i.json   ComfyUI client and graph (Task 7)
    prompts.py                      caption, render and review prompts (Task 8)
    anim_recreate.py                driver: batch (Task 9), caption and review (Task 10),
                                    verify and preview (Task 11)
    test_*.py                       one per module
    README.md, AGENTS.md, CLAUDE.md (symlink), NOTES.md   (Task 12)
    characters.yaml                 seeded and captioned on the GB10 (Task 13)
```

---

### Task 1: Make the bundle a monorepo with the exporter

**Files:**
- Move: `~/code/diablo-hd-bundle/diablo-textures-exporter/` (a git repo, branch `main`, clean) to `~/code/diablo-textures`
- Create: `~/code/diablo-hd-bundle/README.md`; the subtree at `diablo-textures-exporter/`

**Interfaces:**
- Consumes: the bundle repo (branch `main`, holding `.gitignore` and the spec) and the exporter repo.
- Produces: branch `main` with the subtree and the export back at `diablo-textures-exporter/out/`, then branch `feat/diablo-animations` for Tasks 2–14.

- [ ] **Step 1: Check both repos are clean**

```bash
cd ~/code/diablo-hd-bundle/diablo-textures-exporter && git status --short && git branch --show-current
cd ~/code/diablo-hd-bundle && git status --short
```

Expected: the exporter prints only `main`; the bundle prints only `?? diablo-textures-exporter/` (and `?? docs/superpowers/plans/` if this plan is not committed yet: commit it first with `git add docs/superpowers/plans && git commit -m "docs: plan the Diablo animation regeneration kit"` plus the trailer).

- [ ] **Step 2: Move the exporter out and subtree-merge it back with its history**

```bash
cd ~/code && mv diablo-hd-bundle/diablo-textures-exporter diablo-textures
cd ~/code/diablo-hd-bundle
git subtree add --prefix=diablo-textures-exporter ~/code/diablo-textures main
mv ~/code/diablo-textures/out diablo-textures-exporter/out
git status --short
```

Expected: a merge commit; `git log --oneline | wc -l` is above 40; the last `git status` prints nothing (`out/` is ignored). `~/code/diablo-textures` keeps its `.venv`; run `make install` in the bundle copy only when the exporter is needed there (it needs macOS for StormLib).

- [ ] **Step 3: Write the bundle README**

`README.md`:

```markdown
# diablo-hd-bundle

HD graphics for *Diablo* + *Hellfire* (Blizzard North, 1996/1997), for personal use,
toward a DevilutionX fork that loads HD true-colour sprites. Two projects, run in
this order:

| Folder | What it does | Output |
|---|---|---|
| [`diablo-textures-exporter/`](diablo-textures-exporter/) | Exports every graphic from your own GOG copy (`DIABDAT.MPQ`, `hellfire.mpq`, `hfmonk.mpq`) as lossless PNGs with palette indices and metadata | `out/`: `manifest.json`, `assets/`, `palettes/` |
| [`diablo-texture-enhancement/`](diablo-texture-enhancement/) | Repaints every animation frame (players, monsters, towners, missiles, and each monster recolour variant) at exactly 2x through ComfyUI, with the outline locked, then checks it with a gate and a VLM review | `data/anims-ai/`: 2x RGBA frames under the exporter's asset paths |

The enhancement kit reads `../diablo-textures-exporter/out` by default; set
`DIA_SRC` to point it elsewhere. Each folder has its own README and Makefile.

Neither project commits game data or generated art: `out/`, `data/` and
`reviews.yaml` are gitignored. You need your own copy of the game.

Design: [`docs/superpowers/specs/2026-09-26-diablo-animation-regeneration-design.md`](docs/superpowers/specs/2026-09-26-diablo-animation-regeneration-design.md).
Plan: [`docs/superpowers/plans/2026-09-26-diablo-animation-regeneration.md`](docs/superpowers/plans/2026-09-26-diablo-animation-regeneration.md).
```

- [ ] **Step 4: Commit and branch**

```bash
git add README.md
git commit -m "docs: bundle README

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
git switch -c feat/diablo-animations
```

---

### Task 2: Kit scaffold, Makefile and colour match

**Files:**
- Create: `diablo-texture-enhancement/{pyproject.toml,Makefile,run_batch.sh,run_server.sh,test_scripts.py}`
- Copy: `colour_match.py`, `test_colour_match.py` from `~/code/thedig-hd-bundle/thedig-texture-enhancement/` (unchanged: the Lab transfer with an optional statistics mask)

**Interfaces:**
- Produces: `make install|check|test|server` and the pipeline targets (they call `./run_batch.sh`, whose `anim_recreate.py` arrives in Task 9); `colour_match.match(render, guide, strength=1.0, mask=None) -> Image RGB`, `colour_match.RULE == "source-relative"`.

- [ ] **Step 1: Create the folder and copy the reused files**

```bash
mkdir ~/code/diablo-hd-bundle/diablo-texture-enhancement && cd ~/code/diablo-hd-bundle/diablo-texture-enhancement
D=~/code/thedig-hd-bundle/thedig-texture-enhancement
cp $D/colour_match.py $D/test_colour_match.py $D/run_server.sh .
```

- [ ] **Step 2: Write `pyproject.toml`**

```toml
[project]
name = "diablo_anim_regen"
version = "0.1.0"
description = "Caption, render and review high-definition 2x recreations of Diablo's animated sprites with ComfyUI (Qwen-Image) and a local Qwen3.8 VLM"
requires-python = ">=3.12"
dependencies = [
    "pillow>=10.0.0",
    "pyyaml>=6.0",
    "numpy>=1.26",
]
```

- [ ] **Step 3: Write the failing test `test_scripts.py`**

```python
import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent


def dry_make(*args):
    """The ./run_* command lines `make -n` would run, whitespace collapsed."""
    out = subprocess.run(["make", "-n", "-s", *args], cwd=REPO, capture_output=True, text=True,
                         check=True).stdout
    return [" ".join(line.split()) for line in out.splitlines() if line.startswith("./run_")]


class MakeTests(unittest.TestCase):
    def test_targets_forward_their_arguments(self):
        cases = {
            ("caption", "character=monsters/zombie missiles/fireba", "force=1"):
                "./run_batch.sh caption --character monsters/zombie --character missiles/fireba "
                "--force",
            ("dry-run", "variants=0", "packing=packed"):
                "./run_batch.sh batch --dry-run --no-variants --packing packed",
            ("dry-run", "variant=monsters/zombie/grey.trn"):
                "./run_batch.sh batch --dry-run --variant monsters/zombie/grey.trn",
            ("batch", "anim=monsters/zombie/zombiew.cl2", "memcheck=0", "force=1",
             "dst=data/spike/a", "gutter=32", "background=dark", "anchor=0"):
                './run_batch.sh batch --anim monsters/zombie/zombiew.cl2 --dst "data/spike/a" '
                "--gutter 32 --background dark --no-anchor --no-memory-check --force",
            ("batch", "workflow=qwen-image-2.1-i2i-faithful", "strength=0.5"):
                "./run_batch.sh batch --match-strength 0.5 --workflow qwen-image-2.1-i2i-faithful",
            ("review", "concurrency=4"): "./run_batch.sh review --concurrency 4",
            ("verify", "src=/x"): './run_batch.sh verify --src "/x"',
            ("preview", "character=missiles/fireba"):
                "./run_batch.sh preview --character missiles/fireba",
            ("server",): "./run_server.sh",
        }
        for args, expected in cases.items():
            with self.subTest(args=args):
                self.assertEqual(dry_make(*args), [expected])


if __name__ == "__main__":
    unittest.main()
```

Run: `python3 -m unittest test_scripts -v`
Expected: FAIL (`make: *** No rule to make target`: there is no Makefile yet).

- [ ] **Step 4: Write `Makefile` and `run_batch.sh`**

`Makefile`:

```make
# Makefile for the Diablo animation regeneration kit
# Pipeline: caption -> (edit characters.yaml) -> batch -> review -> batch ... -> verify
SERVICE = Diablo Animation Regen

VENV_DIR = .venv
PY = $(VENV_DIR)/bin/python

# Arguments, e.g. make batch character="monsters/zombie" variants=0 force=1
character ?=
anim ?=
src ?=
dst ?=
force ?=
variants ?= 1
variant ?=
memcheck ?= 1
strength ?=
workflow ?=
packing ?=
gutter ?=
background ?=
anchor ?= 1
concurrency ?=
FORCE_ARG = $(if $(force),--force)
ARGS = $(foreach c,$(character),--character $(c)) $(foreach a,$(anim),--anim $(a)) \
       $(if $(src),--src "$(src)") $(if $(dst),--dst "$(dst)") \
       $(if $(filter 0,$(variants)),--no-variants) $(foreach v,$(variant),--variant $(v)) $(if $(packing),--packing $(packing)) \
       $(if $(gutter),--gutter $(gutter)) $(if $(background),--background $(background)) \
       $(if $(filter 0,$(anchor)),--no-anchor)
BATCH_ARGS = $(if $(filter 0,$(memcheck)),--no-memory-check) $(if $(strength),--match-strength $(strength)) \
             $(if $(workflow),--workflow $(workflow)) $(FORCE_ARG)

.PHONY: help install server caption dry-run batch review verify preview check test clean

help: ## Print this help message
	@printf '\033[01;32m${SERVICE}\033[00;37m\n\n'
	@printf "\033[33mUsage:\033[0m\n  make [target] [arg=\"val\"...]\n\n\033[33mTargets:\033[0m\n"
	@grep -E '^[-a-zA-Z0-9_\.\/]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; \
		{printf "  \033[36m%-26s\033[0m %s\n", $$1, $$2}'

# ── Environment ──────────────────────────────────────────────────────────────

install: ## Create .venv with Pillow, PyYAML and numpy (re-running is safe)
	@if [ ! -x "$(PY)" ]; then python3 -m venv $(VENV_DIR); fi
	@$(PY) -c 'import PIL, yaml, numpy' 2>/dev/null || $(VENV_DIR)/bin/pip install -q "pillow>=10" "pyyaml>=6" "numpy>=1.26"

server: ## Start ComfyUI on :8188 from ~/ComfyUI (override COMFY_DIR)
	./run_server.sh

clean: ## Remove __pycache__ (never touches data/)
	find . -path ./.venv -prune -o -type d -name "__pycache__" -exec rm -rf {} +

# ── Pipeline ─────────────────────────────────────────────────────────────────

caption: install ## [STEP 1] Seed characters.yaml, caption its characters with vLLM (character=, force=1)
	./run_batch.sh caption $(ARGS) $(FORCE_ARG)

dry-run: install ## [STEP 2a] Show batch's sheets and statuses, without ComfyUI (character=, anim=, variants=0)
	./run_batch.sh batch --dry-run $(ARGS) $(BATCH_ARGS)

batch: install ## [STEP 2] Render sheets via ComfyUI into data/anims-ai; stop vLLM first (character=, anim=, variant=, variants=0, workflow=, strength=, memcheck=0, force=1)
	./run_batch.sh batch $(ARGS) $(BATCH_ARGS)

review: install ## [STEP 3] Review done sheets with vLLM into reviews.yaml (character=, concurrency=, force=1)
	./run_batch.sh review $(ARGS) $(if $(concurrency),--concurrency $(concurrency)) $(FORCE_ARG)

verify: install ## [STEP 4] Audit data/anims-ai against the manifest, the 2x rule, the outline and the attempts
	./run_batch.sh verify $(ARGS)

preview: install ## Write an animated GIF per direction into data/preview (character=, anim=)
	./run_batch.sh preview $(ARGS)

# ── Development ──────────────────────────────────────────────────────────────

check: install ## Byte-compile the Python modules
	@$(PY) -m py_compile *.py && echo "check ok"

test: install ## Run the unit tests (no GPU, no network)
	$(PY) -m unittest discover -s . -p 'test_*.py'
```

`run_batch.sh` (then `chmod +x run_batch.sh run_server.sh`):

```bash
#!/bin/bash
# Run the Diablo animation regeneration driver: forwards every argument to
# anim_recreate.py (caption | batch | review | verify | preview, plus their
# options). Prefers the project venv (.venv, made by make install), then PYTHON,
# then python3; the interpreter needs Pillow, PyYAML and numpy.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY=""
if [ -x "$SCRIPT_DIR/.venv/bin/python" ]; then
  PY="$SCRIPT_DIR/.venv/bin/python"
fi
PY="${PY:-${PYTHON:-python3}}"

"$PY" -c 'import PIL, yaml, numpy' 2>/dev/null || {
  echo "error: $PY lacks Pillow, PyYAML or numpy - run: make install" >&2
  exit 1
}

exec "$PY" "$SCRIPT_DIR/anim_recreate.py" "$@"
```

- [ ] **Step 5: Run the suite**

Run: `make install && make check && make test`
Expected: `check ok`; the tests pass (`test_scripts`, `test_colour_match`).

- [ ] **Step 6: Commit**

```bash
cd ~/code/diablo-hd-bundle
git add diablo-texture-enhancement
git commit -m "feat(kit): scaffold the Diablo animation kit

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Read the export (`source_tree`) and the miniature export (`testkit`)

**Files:**
- Create: `diablo-texture-enhancement/source_tree.py`, `testkit.py`, `test_source_tree.py`

**Interfaces:**
- Produces:
  - `source_tree.SCALE = 2`, `ANIM_KINDS`, `SourceError(ValueError)`.
  - `Frame(group: int, i: int, w: int, h: int, png: str, idx: str)`; `Animation(key: str, kind: str, path: str, palette: str, groups: int, frames: tuple[Frame], variants: tuple[str])`; `Source(root: Path, animations: tuple[Animation])` with `.animation(key) -> Animation`.
  - `load(root) -> Source`; `palette(root, name) -> (256, 3) uint8`; `trn_map(root, trn) -> (256,) uint8`; `frame_pixels(root, anim, frame) -> (indices (h, w) uint8, mask (h, w) bool)`; `frame_rgba(root, anim, frame, trn=None) -> Image RGBA`; `file_sha256(path) -> str`.
  - `testkit`: `REAL_SRC`, `needs_real_corpus`, `BASE`, `PALETTE`, `PALETTE_NAME`, `GREY_TRN`, `GREY_MAP`, `anim(...)`, `DEFAULT_ANIMS` (zombien 2x3 frames and zombiew 2x4 frames, both with the grey variant; missiles fireba1 and fireba2, 3 frames each; `dmagew.cl2` with no frames), `frame_indices(spec, group, i)`, `make_source(root, anims=DEFAULT_ANIMS) -> Path`, `rewrite_meta(src, key, change)`.

- [ ] **Step 1: Write `testkit.py` (its source half; Task 9 adds the driver half)**

```python
"""Shared test support: a miniature diablo-textures-exporter output, a
characters.yaml writer, the ComfyUI and vLLM patch stacks, a fake sheet
renderer, a CLI-capture helper, and where the real corpus is.

The real source tree is diablo-textures-exporter's `out/`: manifest.json with
an hd_contract, assets/<record dir>/meta.json with frames (png RGBA, idx LA),
palettes/<name>.json and assets/<trn>/trn.json.
"""
import json
import os
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

# The real corpus: diablo-textures-exporter's output.
REAL_SRC = Path(os.environ.get("DIA_SRC")
                or Path(__file__).resolve().parent.parent / "diablo-textures-exporter" / "out")

needs_real_corpus = unittest.skipUnless(
    (REAL_SRC / "manifest.json").is_file(),
    "no diablo-textures-exporter output at REAL_SRC (or DIA_SRC)")

# Indices 2-13 lie far apart (RGB distance over 64), so every block edge is a
# strong edge; index 0 is black, the colour of transparent pixels.
BASE = [(0, 0, 0), (255, 255, 255), (200, 40, 40), (40, 200, 40), (40, 40, 200),
        (200, 200, 40), (200, 40, 200), (40, 200, 200), (120, 60, 20), (20, 120, 60),
        (60, 20, 120), (230, 140, 60), (60, 140, 230), (140, 230, 60)]
PALETTE = BASE + [(i, i, i) for i in range(len(BASE), 256)]
PALETTE_NAME = "levels/towndata/town.pal"
# The grey TRN sends every colour index 2-13 to a grey index, like a recolour table.
GREY_TRN = "monsters/zombie/grey.trn"
GREY_MAP = list(range(256))
for _n in range(2, len(BASE)):
    GREY_MAP[_n] = 40 + 12 * _n


def anim(key, kind, groups, per_group, width=32, height=24, *, variants=(), seed=1):
    """An animation for make_source: `groups` directions of `per_group` frames of
    width x height. Each frame's figure is a 14x16 block of 2-pixel random
    colour squares (indices 2-13, seeded by `seed` and the group) that moves one
    pixel right per frame, over transparency."""
    return {"key": key, "kind": kind, "groups": groups, "per_group": per_group,
            "width": width, "height": height, "variants": tuple(variants), "seed": seed}


DEFAULT_ANIMS = (
    anim("monsters/zombie/zombien.cl2", "monster_anim", 2, 3, variants=[GREY_TRN], seed=1),
    anim("monsters/zombie/zombiew.cl2", "monster_anim", 2, 4, variants=[GREY_TRN], seed=2),
    anim("missiles/fireba1.cl2", "missile", 1, 3, 24, 24, seed=3),
    anim("missiles/fireba2.cl2", "missile", 1, 3, 24, 24, seed=4),
    anim("monsters/darkmage/dmagew.cl2", "monster_anim", 8, 0, seed=5),   # no frames at all
)


def frame_indices(spec, group, i):
    """(indices, mask): the frame's (h, w) palette indices and opacity."""
    h, w = spec["height"], spec["width"]
    rng = np.random.default_rng(spec["seed"] * 100 + group)
    figure = np.kron(rng.integers(2, len(BASE), size=(8, 7), dtype=np.uint8),
                     np.ones((2, 2), np.uint8))                  # 16 x 14
    indices = np.zeros((h, w), np.uint8)
    mask = np.zeros((h, w), bool)
    x = 4 + i
    indices[4:20, x:x + 14] = figure
    mask[4:20, x:x + 14] = True
    return indices, mask


def _write_frame(folder, name, indices, mask):
    folder.mkdir(parents=True, exist_ok=True)
    rgb = np.array(PALETTE, np.uint8)[indices]
    rgb[~mask] = 0
    alpha = np.where(mask, 255, 0).astype(np.uint8)
    Image.fromarray(np.dstack([rgb, alpha]), "RGBA").save(folder / f"{name}.png")
    Image.fromarray(np.dstack([np.where(mask, indices, 0).astype(np.uint8), alpha]),
                    "LA").save(folder / f"{name}.idx.png")


def make_source(root, anims=DEFAULT_ANIMS):
    """Write <root>/out like `dtx extract` and return it."""
    src = Path(root) / "out"
    assets = []
    for spec in anims:
        folder = src / "assets" / spec["key"]
        frames = []
        for g in range(spec["groups"]):
            for i in range(spec["per_group"]):
                _write_frame(folder / f"d{g}", f"f{i:03d}", *frame_indices(spec, g, i))
                frames.append({"group": g, "i": i, "w": spec["width"], "h": spec["height"],
                               "png": f"d{g}/f{i:03d}.png", "idx": f"d{g}/f{i:03d}.idx.png"})
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "meta.json").write_text(json.dumps({
            "source": {"archive": "DIABDAT.MPQ", "path": spec["key"].replace("/", "\\")},
            "format": "cl2", "kind": spec["kind"], "palette": PALETTE_NAME,
            "palette_alternatives": [], "variants": [{"trn": t} for t in spec["variants"]],
            "width_source": "table", "groups": spec["groups"], "group_label": "direction",
            "sheet": "sheet.png", "frames": frames}, indent=1))
        assets.append({"path": spec["key"].replace("/", "\\"), "kind": spec["kind"],
                       "archive": "DIABDAT.MPQ", "sha1": "0" * 40,
                       "record": f"assets/{spec['key']}/meta.json"})
    pal = src / "palettes" / f"{PALETTE_NAME}.json"
    pal.parent.mkdir(parents=True, exist_ok=True)
    pal.write_text(json.dumps({"colors": [list(c) for c in PALETTE], "cycling": []}))
    trn = src / "assets" / GREY_TRN / "trn.json"
    trn.parent.mkdir(parents=True, exist_ok=True)
    trn.write_text(json.dumps({"map": GREY_MAP}))
    # A kind the kit ignores, with no files behind it.
    assets.append({"path": "items\\armor2.cel", "kind": "item", "archive": "DIABDAT.MPQ",
                   "sha1": "0" * 40, "record": "assets/items/armor2.cel/meta.json"})
    (src / "manifest.json").write_text(json.dumps({
        "version": 1,
        "hd_contract": {"scale": "integer k >= 1, chosen once per asset",
                        "units": ["frame", "cell", "column"]},
        "assets": assets}, indent=1))
    return src


def rewrite_meta(src, key, change):
    """Load the animation's meta.json, let change(meta) edit it in place, save it."""
    path = Path(src) / "assets" / key / "meta.json"
    meta = json.loads(path.read_text())
    change(meta)
    path.write_text(json.dumps(meta, indent=1))

```

- [ ] **Step 2: Write the failing test `test_source_tree.py`**

```python
import json
import tempfile
import unittest

import numpy as np

import source_tree
import testkit


class LoadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.src = testkit.make_source(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_load_reads_the_animations_and_ignores_other_kinds(self):
        source = source_tree.load(self.src)
        self.assertEqual([a.key for a in source.animations],
                         [spec["key"] for spec in testkit.DEFAULT_ANIMS])
        walk = source.animation("monsters/zombie/zombiew.cl2")
        self.assertEqual((walk.kind, walk.groups, len(walk.frames)), ("monster_anim", 2, 8))
        self.assertEqual(walk.variants, (testkit.GREY_TRN,))
        self.assertEqual(walk.frames[4], source_tree.Frame(1, 0, 32, 24, "d1/f000.png",
                                                           "d1/f000.idx.png"))
        self.assertEqual(source.animation("monsters/darkmage/dmagew.cl2").frames, ())

    def test_frame_rgba_applies_the_trn_then_the_palette(self):
        source = source_tree.load(self.src)
        walk = source.animation("monsters/zombie/zombiew.cl2")
        indices, mask = testkit.frame_indices(testkit.DEFAULT_ANIMS[1], 0, 0)
        base = np.asarray(source_tree.frame_rgba(self.src, walk, walk.frames[0]))
        grey = np.asarray(source_tree.frame_rgba(self.src, walk, walk.frames[0], testkit.GREY_TRN))
        np.testing.assert_array_equal(base[..., :3][mask], np.array(testkit.PALETTE)[indices][mask])
        np.testing.assert_array_equal(grey[..., 0][mask], np.array(testkit.GREY_MAP)[indices][mask])
        np.testing.assert_array_equal(base[..., 3], np.where(mask, 255, 0))
        self.assertEqual(int(base[~mask].max()), 0, msg="transparent pixels are all zero")

    def test_bad_output_is_a_source_error(self):
        cases = {
            "no hd_contract": lambda: (self.src / "manifest.json").write_text(
                json.dumps({"assets": []})),
            "frame size disagrees with meta.json": lambda: testkit.rewrite_meta(
                self.src, "missiles/fireba1.cl2",
                lambda meta: meta["frames"][0].update(w=25)),
            "missing palette": lambda: (self.src / "palettes" / f"{testkit.PALETTE_NAME}.json")
            .unlink(),
        }
        for label, breaks in cases.items():
            with self.subTest(label):
                self.tearDown()
                self.setUp()
                breaks()
                with self.assertRaises(source_tree.SourceError):
                    source = source_tree.load(self.src)
                    anim = source.animation("missiles/fireba1.cl2")
                    source_tree.frame_rgba(self.src, anim, anim.frames[0])


@testkit.needs_real_corpus
class RealCorpusTests(unittest.TestCase):
    def test_the_real_manifest(self):
        source = source_tree.load(testkit.REAL_SRC)
        kinds = {}
        for anim in source.animations:
            kinds[anim.kind] = kinds.get(anim.kind, 0) + 1
        self.assertEqual(kinds, {"player_anim": 1056, "monster_anim": 334, "towner_anim": 21,
                                 "missile": 380})
        self.assertEqual(sum(len(a.frames) for a in source.animations), 145560)
        self.assertEqual(sum(1 for a in source.animations if a.variants), 182)


if __name__ == "__main__":
    unittest.main()
```

Run: `.venv/bin/python -m unittest test_source_tree -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'source_tree'`.

- [ ] **Step 3: Write `source_tree.py`**

```python
"""Read diablo-textures-exporter's output: the animations the kit regenerates.

The only reader of DIA_SRC. manifest.json decides which animations exist; each
one's meta.json lists its frames, palette and recolour (TRN) variants. A frame
is two files: <png> (RGBA, the palette applied) and <idx> (LA: L the palette
index, A 0 or 255); the kit builds its own RGB from the index image, so a
variant is the same indices through the TRN first. Never writes; never parses
paths for meaning: an animation's key is its record directory under assets/,
used only as a name.
"""
import functools
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

SCALE = 2
ANIM_KINDS = ("player_anim", "monster_anim", "towner_anim", "missile")


class SourceError(ValueError):
    """The exporter's output does not have the shape this kit expects."""


@dataclass(frozen=True)
class Frame:
    group: int          # direction (or 0 for a one-group animation)
    i: int              # position in its group
    w: int
    h: int
    png: str            # path relative to the animation's directory, reused for the output
    idx: str


@dataclass(frozen=True)
class Animation:
    key: str            # record directory under assets/, e.g. monsters/zombie/zombiew.cl2
    kind: str
    path: str           # the archive path, for messages
    palette: str        # e.g. levels/towndata/town.pal
    groups: int
    frames: tuple       # Frame, ordered by (group, i)
    variants: tuple     # TRN asset paths, e.g. monsters/zombie/grey.trn


@dataclass(frozen=True)
class Source:
    root: Path
    animations: tuple   # Animation, in manifest order

    def animation(self, key):
        for anim in self.animations:
            if anim.key == key:
                return anim
        raise SourceError(f"no animation {key!r} in {self.root / 'manifest.json'}")


def _json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise SourceError(f"{path}: file not found") from error
    except ValueError as error:
        raise SourceError(f"{path}: invalid JSON: {error}") from error


def _int(value, where, least=0):
    if type(value) is not int or value < least:
        raise SourceError(f"{where}: expected an integer >= {least}, got {value!r}")
    return value


def _animation(root, entry):
    record = entry.get("record")
    if not isinstance(record, str) or not record.startswith("assets/") \
            or not record.endswith("/meta.json"):
        raise SourceError(f"manifest entry {entry.get('path')!r}: bad record {record!r}")
    key = record[len("assets/"):-len("/meta.json")]
    meta = _json(Path(root) / record)
    where = f"{record}"
    palette = meta.get("palette")
    if not isinstance(palette, str) or not palette:
        raise SourceError(f"{where}: no palette")
    frames = []
    for n, f in enumerate(meta.get("frames") or []):
        at = f"{where}: frame {n}"
        if not isinstance(f, dict) or not isinstance(f.get("png"), str) \
                or not isinstance(f.get("idx"), str):
            raise SourceError(f"{at}: expected png and idx paths")
        frames.append(Frame(_int(f.get("group"), at), _int(f.get("i"), at),
                            _int(f.get("w"), at, 1), _int(f.get("h"), at, 1), f["png"], f["idx"]))
    variants = []
    for v in meta.get("variants") or []:
        if not isinstance(v, dict) or not isinstance(v.get("trn"), str):
            raise SourceError(f"{where}: a variant without a trn path")
        variants.append(v["trn"])
    return Animation(key, entry["kind"], entry.get("path", key), palette,
                     _int(meta.get("groups"), where), tuple(sorted(frames, key=lambda f: (f.group, f.i))),
                     tuple(variants))


def load(root):
    """The Source at `root` (the exporter's out/): every animation of ANIM_KINDS."""
    root = Path(root)
    manifest = _json(root / "manifest.json")
    contract = manifest.get("hd_contract") if isinstance(manifest, dict) else None
    if not isinstance(contract, dict) or "frame" not in (contract.get("units") or []):
        raise SourceError(f"{root / 'manifest.json'}: no hd_contract with frame units - "
                          "is this diablo-textures-exporter's output?")
    assets = manifest.get("assets")
    if not isinstance(assets, list):
        raise SourceError(f"{root / 'manifest.json'}: no assets list")
    animations = tuple(_animation(root, entry) for entry in assets
                       if isinstance(entry, dict) and entry.get("kind") in ANIM_KINDS)
    keys = [anim.key for anim in animations]
    if len(set(keys)) != len(keys):
        raise SourceError(f"{root / 'manifest.json'}: an animation record appears twice")
    return Source(root, animations)


@functools.lru_cache(maxsize=64)
def _palette(root, name):
    colors = _json(Path(root) / "palettes" / f"{name}.json").get("colors")
    array = np.array(colors, dtype=np.int64) if isinstance(colors, list) else None
    if array is None or array.shape != (256, 3) or array.min() < 0 or array.max() > 255:
        raise SourceError(f"palettes/{name}.json: expected 256 RGB colours")
    return array.astype(np.uint8)


def palette(root, name):
    """(256, 3) uint8 colours of the palette `name` (e.g. levels/towndata/town.pal)."""
    return _palette(str(root), name)


@functools.lru_cache(maxsize=256)
def _trn(root, trn):
    table = _json(Path(root) / "assets" / trn / "trn.json").get("map")
    array = np.array(table, dtype=np.int64) if isinstance(table, list) else None
    if array is None or array.shape != (256,) or array.min() < 0 or array.max() > 255:
        raise SourceError(f"assets/{trn}/trn.json: expected a map of 256 indices")
    return array.astype(np.uint8)


def trn_map(root, trn):
    """(256,) uint8 index translation of the TRN asset `trn`."""
    return _trn(str(root), trn)


def frame_pixels(root, anim, frame):
    """(indices, mask) of one frame: (h, w) uint8 palette indices and (h, w) bool opacity."""
    path = Path(root) / "assets" / anim.key / frame.idx
    try:
        with Image.open(path) as im:
            la = np.asarray(im.convert("LA"))
    except OSError as error:
        raise SourceError(f"{path}: {error}") from error
    if la.shape[:2] != (frame.h, frame.w):
        raise SourceError(f"{path}: is {la.shape[1]}x{la.shape[0]}, "
                          f"meta.json says {frame.w}x{frame.h}")
    return la[..., 0].copy(), la[..., 1] > 0


def frame_rgba(root, anim, frame, trn=None):
    """The native RGBA frame: its indices through `trn` (when given) and its
    palette; transparent pixels are (0, 0, 0, 0)."""
    indices, mask = frame_pixels(root, anim, frame)
    if trn is not None:
        indices = trn_map(root, trn)[indices]
    rgb = palette(root, anim.palette)[indices]
    rgb[~mask] = 0
    return Image.fromarray(np.dstack([rgb, np.where(mask, 255, 0).astype(np.uint8)]), "RGBA")


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m unittest test_source_tree -v`
Expected: PASS, including `RealCorpusTests` when `../diablo-textures-exporter/out` exists (1,056 player, 334 monster, 21 towner and 380 missile animations; 145,560 frames; 182 animations with variants).

- [ ] **Step 5: Commit**

```bash
git add diablo-texture-enhancement/source_tree.py diablo-texture-enhancement/testkit.py diablo-texture-enhancement/test_source_tree.py
git commit -m "feat(kit): read the exporter's animations, palettes and TRNs

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: `characters.yaml`, `reviews.yaml` and the seed

**Files:**
- Create: `diablo-texture-enhancement/characters_file.py`, `test_characters_file.py`

**Interfaces:**
- Produces: `CharactersFileError(ValueError)`; `Character(animations: tuple, anchor: str, caption: str = "", skip: tuple = ())`; `Review(attempt: int, accepted: bool, issues: tuple, source: str = "review")`; `load_characters(path) -> {key: Character}`; `save_characters(path, characters)`; `check_coverage(characters, animation_keys, path)`; `character_key(anim_key, kind) -> str`; `seed_anchor(anim_keys, kind, empty=()) -> str`; `seed_characters([(key, kind, frame count), ...]) -> {key: Character}`; `load_reviews(path, optional=False) -> {sheet key: Review}`; `save_reviews(path, reviews)`; `normalize_text(text)`. A sheet key is `<job key>/sNN`.

- [ ] **Step 1: Write the failing test `test_characters_file.py`**

```python
import tempfile
import unittest
from pathlib import Path

import characters_file as cf


class SeedTests(unittest.TestCase):
    def test_seed_groups_by_directory_and_missile_stem_and_picks_anchors(self):
        seeded = cf.seed_characters([
            ("monsters/zombie/zombiew.cl2", "monster_anim", 64),
            ("monsters/zombie/zombien.cl2", "monster_anim", 64),
            ("plrgfx/warrior/wlm/wlmwl.cl2", "player_anim", 64),
            ("plrgfx/warrior/wlm/wlmst.cl2", "player_anim", 64),
            ("missiles/acidbf10.cl2", "missile", 8),
            ("missiles/acidbf2.cl2", "missile", 8),
            ("missiles/arrows.cl2", "missile", 16),
            ("towners/smith/smithn.cel", "towner_anim", 16),
            ("@DIABDAT.MPQ/monsters/goatlord/goatld.cl2", "monster_anim", 64),
            ("monsters/darkmage/dmagen.cl2", "monster_anim", 0),      # no frames: never the anchor
            ("monsters/darkmage/dmagew.cl2", "monster_anim", 64),
        ])
        self.assertEqual(seeded, {
            "monsters/zombie": cf.Character(("monsters/zombie/zombien.cl2",
                                             "monsters/zombie/zombiew.cl2"),
                                            "monsters/zombie/zombien.cl2"),
            "plrgfx/warrior/wlm": cf.Character(("plrgfx/warrior/wlm/wlmst.cl2",
                                                "plrgfx/warrior/wlm/wlmwl.cl2"),
                                               "plrgfx/warrior/wlm/wlmst.cl2"),
            "missiles/acidbf": cf.Character(("missiles/acidbf2.cl2", "missiles/acidbf10.cl2"),
                                            "missiles/acidbf2.cl2"),
            "missiles/arrows": cf.Character(("missiles/arrows.cl2",), "missiles/arrows.cl2"),
            "towners/smith": cf.Character(("towners/smith/smithn.cel",),
                                          "towners/smith/smithn.cel"),
            "monsters/darkmage": cf.Character(("monsters/darkmage/dmagew.cl2",
                                               "monsters/darkmage/dmagen.cl2"),
                                              "monsters/darkmage/dmagew.cl2"),
            "@DIABDAT.MPQ/monsters/goatlord": cf.Character(
                ("@DIABDAT.MPQ/monsters/goatlord/goatld.cl2",),
                "@DIABDAT.MPQ/monsters/goatlord/goatld.cl2"),
        })


class CharactersTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "characters.yaml"

    def tearDown(self):
        self.tmp.cleanup()

    def test_round_trip_keeps_a_multi_line_caption(self):
        chars = {"monsters/zombie": cf.Character(("a.cl2", "b.cl2"), "a.cl2",
                                                 "SUBJECT: a zombie  \nCOLOURS: green", ("b.cl2",))}
        cf.save_characters(self.path, chars)
        self.assertIn("caption: >", self.path.read_text())
        loaded = cf.load_characters(self.path)
        self.assertEqual(loaded["monsters/zombie"].caption, "SUBJECT: a zombie\nCOLOURS: green")
        self.assertEqual(loaded["monsters/zombie"].skip, ("b.cl2",))

    def test_bad_entries_are_refused(self):
        cases = {
            "anchor outside": "c:\n  animations: [a.cl2]\n  anchor: b.cl2\n",
            "anchor skipped": "c:\n  animations: [a.cl2]\n  anchor: a.cl2\n  skip: [a.cl2]\n",
            "skip outside": "c:\n  animations: [a.cl2]\n  anchor: a.cl2\n  skip: [z.cl2]\n",
            "unknown field": "c:\n  animations: [a.cl2]\n  anchor: a.cl2\n  style: x\n",
            "no animations": "c:\n  anchor: a.cl2\n",
        }
        for label, text in cases.items():
            with self.subTest(label):
                self.path.write_text(text)
                with self.assertRaises(cf.CharactersFileError):
                    cf.load_characters(self.path)

    def test_coverage_needs_each_animation_exactly_once(self):
        chars = {"x": cf.Character(("a", "b"), "a"), "y": cf.Character(("b",), "b")}
        with self.assertRaisesRegex(cf.CharactersFileError, "b is in both x and y.*no character "
                                                            "for c.*not in the manifest: d"):
            cf.check_coverage({**chars, "z": cf.Character(("d",), "d")}, ["a", "b", "c"])
        cf.check_coverage({"x": cf.Character(("a", "b"), "a")}, ["a", "b"])


class ReviewsTests(unittest.TestCase):
    def test_round_trip_and_refusals(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "reviews.yaml"
            reviews = {"monsters/zombie/zombiew.cl2/@trn/monsters/zombie/grey.trn/s02":
                       cf.Review(3, False, ("cell 4 bleeds into cell 5",), "review")}
            cf.save_reviews(path, reviews)
            self.assertEqual(cf.load_reviews(path), reviews)
            self.assertEqual(cf.load_reviews(Path(tmp) / "none.yaml", optional=True), {})
            for text in ("a.cl2:\n  attempt: 1\n  accepted: true\n  issues: []\n",
                         "a.cl2/s01:\n  attempt: 1\n  accepted: true\n  issues: [x]\n"):
                with self.subTest(text=text):
                    path.write_text(text)
                    with self.assertRaises(cf.CharactersFileError):
                        cf.load_reviews(path)


if __name__ == "__main__":
    unittest.main()
```

Run: `.venv/bin/python -m unittest test_characters_file -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'characters_file'`.

- [ ] **Step 2: Write `characters_file.py`**

```python
"""Read and write characters.yaml and reviews.yaml.

characters.yaml is hand-owned: one entry per character, keyed by a name (the
seed uses the animations' shared directory), with its `animations` (record
directories, in render order), its `anchor` (the animation every other one is
painted against), a `caption` that `make caption` fills and the user edits,
and `skip` (animations written as a nearest-neighbour 2x instead). Every
manifest animation belongs to exactly one character.

reviews.yaml is machine-written: one verdict per sheet (key
`<job key>/sNN`) on its latest judged attempt, from the VLM review
(`source: review`) or from batch's gate (`source: geometry`).

Multi-line strings are written in folded (`>`) style; every save goes to
<file>.tmp and is renamed into place.
"""
import os
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

REVIEW_SOURCES = ("review", "geometry")
_SHEET_KEY = re.compile(r"^\S+/s\d{2}$")
_TRAILING_DIGITS = re.compile(r"\d+$")


class CharactersFileError(ValueError):
    """A YAML file does not have the shape this kit expects."""


@dataclass(frozen=True)
class Character:
    animations: tuple   # record directories, in render order
    anchor: str         # one of animations, not skipped
    caption: str = ""
    skip: tuple = ()    # animations written as a nearest-neighbour 2x


@dataclass(frozen=True)
class Review:
    attempt: int
    accepted: bool
    issues: tuple
    source: str = "review"


def normalize_text(text):
    """Strip trailing whitespace on each line and trailing blank lines.

    PyYAML refuses block style for text with a space before a line break and
    falls back to a double-quoted scalar; VLM output often has such spaces.
    """
    return "\n".join(line.rstrip() for line in text.splitlines()).rstrip("\n")


class _Dumper(yaml.SafeDumper):
    pass


def _represent_str(dumper, data):
    style = ">" if "\n" in data else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


_Dumper.add_representer(str, _represent_str)


def _dump(mapping, path):
    path = Path(path)
    text = yaml.dump(mapping, Dumper=_Dumper, sort_keys=False, allow_unicode=True,
                     width=1_000_000)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _read_mapping(path, optional):
    path = Path(path)
    if not path.exists():
        if optional:
            return {}
        raise CharactersFileError(f"{path}: file not found")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise CharactersFileError(f"{path}: invalid YAML: {error}") from error
    if data is None:
        return {}
    if not isinstance(data, dict) or any(not isinstance(k, str) for k in data):
        raise CharactersFileError(f"{path}: expected a mapping with string keys")
    return data


def _strings(value, where, field):
    if not isinstance(value, list) or any(not isinstance(x, str) or not x for x in value):
        raise CharactersFileError(f'{where}: "{field}" must be a list of animation keys')
    return tuple(value)


def load_characters(path):
    """{character key: Character}. A missing or blank caption loads as ""."""
    result = {}
    for key, entry in _read_mapping(path, optional=False).items():
        where = f"{Path(path)}: {key}"
        if not isinstance(entry, dict):
            raise CharactersFileError(f"{where}: expected a mapping")
        unknown = sorted(set(entry) - {"animations", "anchor", "caption", "skip"})
        if unknown:
            raise CharactersFileError(f"{where}: unknown field(s) {', '.join(unknown)}")
        animations = _strings(entry.get("animations"), where, "animations")
        skip = _strings(entry.get("skip") or [], where, "skip")
        anchor = entry.get("anchor")
        if anchor not in animations:
            raise CharactersFileError(f'{where}: "anchor" must be one of its animations')
        if anchor in skip:
            raise CharactersFileError(f'{where}: the anchor {anchor} cannot be skipped')
        if set(skip) - set(animations):
            raise CharactersFileError(f'{where}: "skip" names animations it does not have: '
                                      + ", ".join(sorted(set(skip) - set(animations))))
        caption = entry.get("caption")
        if caption is None:
            caption = ""
        if not isinstance(caption, str):
            raise CharactersFileError(f'{where}: "caption" must be a string')
        result[key] = Character(animations, anchor, caption, skip)
    return result


def save_characters(path, characters):
    def entry(c):
        out = {"animations": list(c.animations), "anchor": c.anchor,
               "caption": normalize_text(c.caption)}
        if c.skip:
            out["skip"] = list(c.skip)
        return out
    _dump({key: entry(characters[key]) for key in sorted(characters)}, path)


def check_coverage(characters, animation_keys, path="characters.yaml"):
    """Raise unless every key in `animation_keys` belongs to exactly one character
    and no character names an animation outside them."""
    owner, problems = {}, []
    for key, character in characters.items():
        for anim in character.animations:
            if anim in owner:
                problems.append(f"{anim} is in both {owner[anim]} and {key}")
            owner[anim] = key
    missing = [k for k in animation_keys if k not in owner]
    extra = sorted(set(owner) - set(animation_keys))
    if missing:
        problems.append("no character for " + ", ".join(missing))
    if extra:
        problems.append("animations not in the manifest: " + ", ".join(extra))
    if problems:
        raise CharactersFileError(f"{path}: " + "; ".join(problems))


def character_key(anim_key, kind):
    """The seed's character for an animation: a missile's directory plus its file
    stem without trailing digits (missiles/acidbf1.cl2 -> missiles/acidbf);
    anything else, its directory (monsters/zombie/zombiew.cl2 -> monsters/zombie)."""
    folder, _, name = anim_key.rpartition("/")
    if kind == "missile":
        stem = _TRAILING_DIGITS.sub("", name.split(".")[0])
        return f"{folder}/{stem}" if folder else stem
    return folder or name


def _natural(key):
    return [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", key)]


def seed_anchor(anim_keys, kind, empty=()):
    """The seed's anchor: a player's standing animation (stem ending "st"), a
    monster's neutral one (ending "n"), else the first in natural order;
    never one of `empty` (animations without frames) while another has frames."""
    ordered = sorted(anim_keys, key=_natural)
    ordered = [k for k in ordered if k not in empty] or ordered
    ending = {"player_anim": "st", "monster_anim": "n"}.get(kind)
    if ending:
        for key in ordered:
            if key.rpartition("/")[2].split(".")[0].endswith(ending):
                return key
    return ordered[0]


def seed_characters(animations):
    """{character key: Character} for [(animation key, kind, frame count), ...]:
    the grouping and anchors `make caption` proposes. The one place that reads
    names for meaning; the user may change all of it."""
    groups, kinds, empty = {}, {}, set()
    for key, kind, count in animations:
        ck = character_key(key, kind)
        groups.setdefault(ck, []).append(key)
        kinds.setdefault(ck, kind)
        if not count:
            empty.add(key)
    result = {}
    for ck, keys in groups.items():
        anchor = seed_anchor(keys, kinds[ck], empty)
        rest = [k for k in sorted(keys, key=_natural) if k != anchor]
        result[ck] = Character(tuple([anchor] + rest), anchor)
    return result


def load_reviews(path, optional=False):
    """{sheet key: Review}. A missing file is {} when optional, else an error."""
    result = {}
    for key, entry in _read_mapping(path, optional).items():
        where = f"{Path(path)}: {key}"
        if not _SHEET_KEY.match(key):
            raise CharactersFileError(f"{where}: not a sheet key (<animation>/sNN)")
        if not isinstance(entry, dict):
            raise CharactersFileError(f"{where}: expected a mapping")
        unknown = sorted(set(entry) - {"attempt", "accepted", "issues", "source"})
        if unknown:
            raise CharactersFileError(f"{where}: unknown field(s) {', '.join(unknown)}")
        attempt, accepted = entry.get("attempt"), entry.get("accepted")
        issues, source = entry.get("issues"), entry.get("source", "review")
        if type(attempt) is not int or attempt < 0:
            raise CharactersFileError(f'{where}: "attempt" must be a non-negative integer')
        if type(accepted) is not bool:
            raise CharactersFileError(f'{where}: "accepted" must be true or false')
        if (not isinstance(issues, list)
                or any(not isinstance(x, str) or not x.strip() for x in issues)):
            raise CharactersFileError(f'{where}: "issues" must be a list of non-empty strings')
        if accepted != (not issues):
            raise CharactersFileError(f'{where}: "accepted" contradicts "issues"')
        if source not in REVIEW_SOURCES:
            raise CharactersFileError(f'{where}: "source" must be one of '
                                      f'{", ".join(REVIEW_SOURCES)}')
        result[key] = Review(attempt, accepted, tuple(issues), source)
    return result


def save_reviews(path, reviews):
    _dump({key: {"attempt": r.attempt, "accepted": r.accepted,
                 "issues": [normalize_text(x) for x in r.issues], "source": r.source}
           for key, r in sorted(reviews.items())}, path)
```

- [ ] **Step 3: Run the tests**

Run: `.venv/bin/python -m unittest test_characters_file -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add diablo-texture-enhancement/characters_file.py diablo-texture-enhancement/test_characters_file.py
git commit -m "feat(kit): characters.yaml, reviews.yaml and the seeded grouping

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: `sheet_layout` — cells, sheets, guide canvas, slicing, soft outline

**Files:**
- Create: `diablo-texture-enhancement/sheet_layout.py`, `test_sheet_layout.py`

**Interfaces:**
- Consumes: `testkit.needs_real_corpus`, `REAL_SRC`; `source_tree.load`, `frame_pixels`.
- Produces: the layout constants; `Cell(frame: int, box: (x0, y0, x1, y1) native, at: (x, y) HD canvas)`; `Sheet(number: int, groups: tuple, size: (w, h), cells: tuple[Cell])` with `.label -> "sNN"`; `union_box(masks)`; `plan_sheets([(group, mask), ...], packing=SHEET_PACKING, gutter=GUTTER) -> tuple[Sheet]`; `frame_region(cell, size)`; `gutter_mask(sheet) -> (H, W) bool`; `fill_transparent(rgb, known, rings=None)`; `hard_alpha(mask)`, `soft_alpha(mask) -> (2h, 2w) uint8`; `guide_frame(frame_rgba, background) -> Image RGB 2x`; `guide_native(frame_rgba, background) -> Image RGB native`; `guide_canvas(sheet, guides, background) -> Image RGB`; `frame_rgb(canvas, cell, size, background) -> Image RGB 2x`; `finish_frame(rgb, mask) -> Image RGBA 2x`; `nearest_frame(frame_rgba) -> Image RGBA 2x`.

- [ ] **Step 1: Write the failing test `test_sheet_layout.py`**

```python
import unittest

import numpy as np
from PIL import Image

import sheet_layout as sl
import source_tree
import testkit

GREY = sl.BACKGROUNDS["grey"]


def mask_at(x0, y0, x1, y1, w=32, h=24):
    mask = np.zeros((h, w), bool)
    mask[y0:y1, x0:x1] = True
    return mask


def rgba(mask, colour=(200, 40, 40)):
    out = np.zeros(mask.shape + (4,), np.uint8)
    out[mask] = colour + (255,)
    return Image.fromarray(out, "RGBA")


def cell_rect(cell):
    """The cell's footprint on the canvas: box at SCALE plus the margin."""
    bw = sl.SCALE * (cell.box[2] - cell.box[0])
    bh = sl.SCALE * (cell.box[3] - cell.box[1])
    x, y = cell.at
    return (x - sl.CELL_MARGIN, y - sl.CELL_MARGIN, x + bw + sl.CELL_MARGIN,
            y + bh + sl.CELL_MARGIN)


class PlanTests(unittest.TestCase):
    def frames(self, groups=2, per_group=4):
        return [(g, mask_at(4 + i, 4, 18 + i, 20)) for g in range(groups) for i in range(per_group)]

    def test_direction_packing_gives_each_direction_its_own_aligned_sheet(self):
        sheets = sl.plan_sheets(self.frames(), "direction", gutter=16)
        self.assertEqual([(s.label, s.groups) for s in sheets], [("s01", (0,)), ("s02", (1,))])
        self.assertEqual([c.frame for c in sheets[1].cells], [4, 5, 6, 7])
        for sheet in sheets:
            w, h = sheet.size
            self.assertEqual((w % sl.ALIGN, h % sl.ALIGN), (0, 0))
            self.assertEqual({c.box for c in sheet.cells}, {(4, 4, 21, 20)},
                             msg="one union box per direction")
            rects = [cell_rect(c) for c in sheet.cells]
            for k, (x0, y0, x1, y1) in enumerate(rects):
                self.assertTrue(x0 >= 16 and y0 >= 16 and x1 <= w - 16 and y1 <= h - 16,
                                msg="a gutter at the canvas edge")
                for other in rects[k + 1:]:
                    apart = (x1 + 16 <= other[0] or other[2] + 16 <= x0
                             or y1 + 16 <= other[1] or other[3] + 16 <= y0)
                    self.assertTrue(apart, msg="cells never overlap and keep the gutter")

    def test_packed_stacks_directions_until_the_canvas_limit(self):
        small = sl.plan_sheets(self.frames(groups=8), "packed")
        self.assertEqual([s.groups for s in small], [tuple(range(8))])
        self.assertLessEqual(small[0].size[0] * small[0].size[1], sl.MAX_CANVAS_PX)
        big = [(g, mask_at(0, 0, 200, 156, 200, 156)) for g in range(3) for _ in range(16)]
        sheets = sl.plan_sheets(big, "packed")
        self.assertEqual([s.groups for s in sheets], [(0,), (1,), (2,)],
                         msg="a direction larger than the limit gets a sheet of its own")
        self.assertGreater(sheets[0].size[0] * sheets[0].size[1], sl.MAX_CANVAS_PX)

    def test_an_empty_direction_still_gets_cells(self):
        empty = np.zeros((24, 32), bool)
        sheets = sl.plan_sheets([(0, empty), (0, empty)])
        self.assertEqual([c.box for c in sheets[0].cells], [(0, 0, 1, 1)] * 2)


class RoundTripTests(unittest.TestCase):
    def test_a_guide_canvas_cut_back_gives_each_frame_its_guide(self):
        masks = [mask_at(4 + i, 4, 18 + i, 20) for i in range(3)]
        rng = np.random.default_rng(0)
        frames = []
        for mask in masks:
            pixels = np.zeros((24, 32, 4), np.uint8)
            pixels[..., :3] = rng.integers(0, 256, (24, 32, 3))
            pixels[..., 3] = np.where(mask, 255, 0)
            frames.append(Image.fromarray(pixels, "RGBA"))
        guides = [sl.guide_frame(f, GREY) for f in frames]
        sheet = sl.plan_sheets([(0, m) for m in masks])[0]
        canvas = sl.guide_canvas(sheet, guides, GREY)
        for cell in sheet.cells:
            with self.subTest(frame=cell.frame):
                cut = sl.frame_rgb(canvas, cell, (32, 24), GREY)
                self.assertEqual(cut.tobytes(), guides[cell.frame].tobytes())
        self.assertTrue((np.asarray(canvas)[sl.gutter_mask(sheet)] == GREY).all(),
                        msg="the gutters are the flat background")


class AlphaTests(unittest.TestCase):
    def test_soft_alpha_only_touches_one_hd_pixel_around_the_hard_edge(self):
        mask = mask_at(8, 6, 20, 16)
        hard = sl.hard_alpha(mask).astype(int)
        soft = sl.soft_alpha(mask).astype(int)
        self.assertEqual(soft.shape, (48, 64))
        partial = (soft > 0) & (soft < 255)
        near = np.zeros_like(partial)
        edge = np.abs(np.diff(hard, axis=0, prepend=hard[:1])) + np.abs(
            np.diff(hard, axis=1, prepend=hard[:, :1]))
        ys, xs = np.nonzero(edge)
        for y, x in zip(ys, xs):
            near[max(0, y - 2):y + 2, max(0, x - 2):x + 2] = True
        self.assertTrue(partial.any())
        self.assertFalse((partial & ~near).any(), msg="nothing soft away from the edge")
        self.assertTrue(((soft == 255) == ((hard == 255) & ~partial)).all())

    def test_finish_frame_colours_the_edge_from_the_figure_not_the_background(self):
        mask = mask_at(8, 6, 20, 16)
        rgb = np.zeros((48, 64, 3), np.uint8)
        rgb[:] = GREY
        rgb[sl.hard_alpha(mask) > 0] = (200, 40, 40)
        out = np.asarray(sl.finish_frame(Image.fromarray(rgb), mask))
        alpha = out[..., 3]
        np.testing.assert_array_equal(alpha, sl.soft_alpha(mask))
        self.assertTrue((out[alpha > 0][:, :3] == (200, 40, 40)).all())
        self.assertEqual(int(out[alpha == 0].max()), 0)

    def test_an_empty_frame_comes_out_fully_transparent(self):
        empty = np.zeros((24, 32), bool)
        out = np.asarray(sl.finish_frame(Image.new("RGB", (64, 48), GREY), empty))
        self.assertEqual((out.shape, int(out.max())), ((48, 64, 4), 0))


@testkit.needs_real_corpus
class RealCorpusTests(unittest.TestCase):
    def test_every_real_animation_lays_out(self):
        source = source_tree.load(testkit.REAL_SRC)
        count, largest = 0, (0, None, None)
        for anim in source.animations:
            masks = [source_tree.frame_pixels(testkit.REAL_SRC, anim, f)[1] for f in anim.frames]
            sheets = sl.plan_sheets([(f.group, m) for f, m in zip(anim.frames, masks)])
            self.assertEqual(sorted(c.frame for s in sheets for c in s.cells),
                             list(range(len(anim.frames))), msg=anim.key)
            count += len(sheets)
            for sheet in sheets:
                area = sheet.size[0] * sheet.size[1]
                if area > largest[0]:
                    largest = (area, sheet.size, anim.key)
        self.assertEqual(count, 11394)
        self.assertEqual(largest[1:], ((1952, 1440), "monsters/nkr/nkrd.cl2"))


if __name__ == "__main__":
    unittest.main()
```

Run: `.venv/bin/python -m unittest test_sheet_layout -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sheet_layout'`.

- [ ] **Step 2: Write `sheet_layout.py`**

```python
"""Lay an animation's frames out on sheets, and cut a rendered sheet back into frames.

A sheet is one canvas the model repaints in one pass. Every direction (group)
gets one cell size: the union of its frames' opaque boxes at SCALE, plus
CELL_MARGIN on each side. Cells sit on a grid with `gutter` pixels between
them and at the canvas edge; the canvas sides are multiples of ALIGN, the
rest filled with the background. A direction is never split across sheets.

The outline is locked: a frame's alpha is its source mask at SCALE,
nearest-neighbour, softened only within 1 HD pixel of its edge
(`soft_alpha`). A pixel with partial alpha takes the colour of the nearest
fully opaque pixel, so the background never tints the outline.

Pure image maths on numpy arrays and Pillow images; knows no files or services.
"""
import math
from dataclasses import dataclass

import numpy as np
from PIL import Image

SCALE = 2
CELL_MARGIN = 8                 # HD px of context around a direction's union box
GUTTER = 16                     # HD px between cells and at the canvas edge
ALIGN = 32                      # canvas sides are multiples of this (Qwen 2.1 resolution 0)
MAX_CANVAS_PX = 1_048_576       # a packed sheet stays at or under this many pixels
PACKINGS = ("direction", "packed")
SHEET_PACKING = "direction"     # one direction per sheet, or several up to MAX_CANVAS_PX
BACKGROUNDS = {"grey": (128, 128, 128), "dark": (24, 24, 24)}
BACKGROUND = "grey"
GUIDE_FILL_RINGS = 4             # native px of fill under the Lanczos kernel (radius 3)
EDGE_FILL_RINGS = 2              # HD px: every partly transparent pixel is within 2 of an opaque one


@dataclass(frozen=True)
class Cell:
    frame: int          # index into the animation's frames
    box: tuple          # (x0, y0, x1, y1): the direction's union box, native frame px
    at: tuple           # (x, y): where the box's top-left lands on the canvas, HD px


@dataclass(frozen=True)
class Sheet:
    number: int         # 1-based, in direction order
    groups: tuple       # the directions it holds
    size: tuple         # (width, height), HD px, multiples of ALIGN
    cells: tuple        # Cell, in frame order

    @property
    def label(self):
        return f"s{self.number:02d}"


def union_box(masks):
    """(x0, y0, x1, y1) around every opaque pixel of `masks`; (0, 0, 1, 1)
    when none has one (an empty direction still gets a cell)."""
    boxes = []
    for mask in masks:
        ys, xs = np.nonzero(mask)
        if xs.size:
            boxes.append((xs.min(), ys.min(), xs.max() + 1, ys.max() + 1))
    if not boxes:
        return (0, 0, 1, 1)
    return (int(min(b[0] for b in boxes)), int(min(b[1] for b in boxes)),
            int(max(b[2] for b in boxes)), int(max(b[3] for b in boxes)))


def _align(n):
    return -(-n // ALIGN) * ALIGN


def _block(frames, box, gutter):
    """(cells relative to the block, width, height) of one direction: a grid of
    about square shape, `gutter` px above and left of each cell."""
    bw, bh = SCALE * (box[2] - box[0]), SCALE * (box[3] - box[1])
    cw, ch = bw + 2 * CELL_MARGIN, bh + 2 * CELL_MARGIN
    n = len(frames)
    cols = max(1, min(n, math.ceil(math.sqrt(n * ch / cw))))
    rows = -(-n // cols)
    cells = [(index, (gutter + (k % cols) * (cw + gutter) + CELL_MARGIN,
                      gutter + (k // cols) * (ch + gutter) + CELL_MARGIN))
             for k, index in enumerate(frames)]
    return cells, cols * (cw + gutter), rows * (ch + gutter)


def plan_sheets(frames, packing=SHEET_PACKING, gutter=GUTTER):
    """The sheets of one animation. `frames` is [(group, mask), ...] in the
    animation's frame order, mask a native (h, w) bool array. `packing` is
    "direction" (one sheet per direction) or "packed" (consecutive directions
    stacked while the canvas stays within MAX_CANVAS_PX; a direction that alone
    exceeds it gets a sheet that fits it)."""
    if packing not in PACKINGS:
        raise ValueError(f"packing must be one of {', '.join(PACKINGS)}, got {packing!r}")
    groups = {}
    for index, (group, mask) in enumerate(frames):
        groups.setdefault(group, []).append((index, mask))
    blocks = []
    for group in sorted(groups):
        members = groups[group]
        box = union_box([mask for _, mask in members])
        cells, width, height = _block([index for index, _ in members], box, gutter)
        blocks.append((group, box, cells, width, height))

    sheets, current = [], []

    def size(parts):
        return (_align(max(p[3] for p in parts) + gutter),
                _align(sum(p[4] for p in parts) + gutter))

    def close():
        if not current:
            return
        cells, y = [], 0
        for _, box, block_cells, _, height in current:
            cells.extend(Cell(index, box, (x, y + by)) for index, (x, by) in block_cells)
            y += height
        sheets.append(Sheet(len(sheets) + 1, tuple(p[0] for p in current), size(current),
                            tuple(sorted(cells, key=lambda c: c.frame))))
        current.clear()

    for block in blocks:
        if current and (packing == "direction"
                        or math.prod(size(current + [block])) > MAX_CANVAS_PX):
            close()
        current.append(block)
    close()
    return tuple(sheets)


def frame_region(cell, size):
    """(x0, y0, x1, y1): the part of the frame at SCALE, in HD frame px, that
    the cell holds: its box grown by CELL_MARGIN, clipped to the frame. `size`
    is the native (w, h)."""
    x0, y0, x1, y1 = cell.box
    return (max(0, SCALE * x0 - CELL_MARGIN), max(0, SCALE * y0 - CELL_MARGIN),
            min(SCALE * size[0], SCALE * x1 + CELL_MARGIN),
            min(SCALE * size[1], SCALE * y1 + CELL_MARGIN))


def _canvas_origin(cell):
    """Where the frame's HD origin (0, 0) lands on the canvas."""
    return cell.at[0] - SCALE * cell.box[0], cell.at[1] - SCALE * cell.box[1]


def gutter_mask(sheet):
    """(H, W) bool: the canvas pixels outside every cell (box plus margin)."""
    w, h = sheet.size
    out = np.ones((h, w), bool)
    for cell in sheet.cells:
        bw = SCALE * (cell.box[2] - cell.box[0])
        bh = SCALE * (cell.box[3] - cell.box[1])
        x, y = cell.at
        out[max(0, y - CELL_MARGIN):y + bh + CELL_MARGIN,
            max(0, x - CELL_MARGIN):x + bw + CELL_MARGIN] = False
    return out


def fill_transparent(rgb, known, rings=None):
    """`rgb` ((h, w, 3) uint8) with each pixel `known` does not mark set to the
    mean of its known 8-neighbours, ring by ring outward, for at most `rings`
    rings (all when None). A pixel no ring reaches keeps its own colour.
    Returns a new array."""
    out = rgb.astype(np.float64).copy()
    known = known.copy()
    h, w = known.shape
    done = 0
    while not known.all() and (rings is None or done < rings):
        total = np.zeros_like(out)
        count = np.zeros((h, w))
        pv = np.pad(out * known[..., None], ((1, 1), (1, 1), (0, 0)))
        pk = np.pad(known, 1).astype(np.float64)
        for dy in range(3):
            for dx in range(3):
                total += pv[dy:dy + h, dx:dx + w]
                count += pk[dy:dy + h, dx:dx + w]
        grow = ~known & (count > 0)
        if not grow.any():
            break
        out[grow] = total[grow] / count[grow][:, None]
        known = known | grow
        done += 1
    return np.round(out).astype(np.uint8)


def hard_alpha(mask):
    """(2h, 2w) uint8: the native bool `mask` at SCALE, nearest-neighbour, 0 or 255."""
    return np.kron(mask.astype(np.uint8) * 255, np.ones((SCALE, SCALE), np.uint8))


def soft_alpha(mask):
    """(2h, 2w) uint8: hard_alpha softened by a 3x3 box, so partial alpha lies
    only within 1 HD px of the hard edge, on either side of it."""
    hard = hard_alpha(mask).astype(np.float64)
    h, w = hard.shape
    p = np.pad(hard, 1)
    total = sum(p[dy:dy + h, dx:dx + w] for dy in range(3) for dx in range(3))
    return np.round(total / 9).astype(np.uint8)


def guide_frame(frame_rgba, background):
    """The frame's guide at SCALE, RGB: its colours (transparent pixels filled
    from the nearest opaque ones) upscaled with Lanczos, laid over the flat
    `background` colour through the hard mask."""
    rgba = np.asarray(frame_rgba.convert("RGBA"))
    mask = rgba[..., 3] > 0
    size = (frame_rgba.width * SCALE, frame_rgba.height * SCALE)
    big = np.asarray(Image.fromarray(fill_transparent(rgba[..., :3], mask, GUIDE_FILL_RINGS))
                     .resize(size, Image.Resampling.LANCZOS))
    out = np.empty_like(big)
    out[:] = background
    hard = hard_alpha(mask) > 0
    out[hard] = big[hard]
    return Image.fromarray(out)


def guide_native(frame_rgba, background):
    """The native frame over the flat `background` colour, RGB: what a
    render's frame, box-downscaled, is compared with."""
    rgba = np.asarray(frame_rgba.convert("RGBA"))
    out = np.empty(rgba.shape[:2] + (3,), np.uint8)
    out[:] = background
    mask = rgba[..., 3] > 0
    out[mask] = rgba[..., :3][mask]
    return Image.fromarray(out)


def guide_canvas(sheet, guides, background):
    """The sheet's guide canvas, RGB: each cell's region of its frame's guide
    (`guides[frame index]`, guide_frame images) on the flat `background`."""
    canvas = Image.new("RGB", sheet.size, background)
    for cell in sheet.cells:
        guide = guides[cell.frame]
        region = frame_region(cell, (guide.width // SCALE, guide.height // SCALE))
        ox, oy = _canvas_origin(cell)
        canvas.paste(guide.crop(region), (ox + region[0], oy + region[1]))
    return canvas


def frame_rgb(canvas, cell, size, background):
    """The frame at SCALE cut from a rendered `canvas`, RGB: the cell's region
    where it was painted, `background` elsewhere. `size` is the native (w, h)."""
    out = Image.new("RGB", (size[0] * SCALE, size[1] * SCALE), background)
    region = frame_region(cell, size)
    ox, oy = _canvas_origin(cell)
    out.paste(canvas.crop((ox + region[0], oy + region[1], ox + region[2], oy + region[3])),
              region[:2])
    return out


def finish_frame(rgb, mask):
    """The output frame, RGBA at SCALE: `rgb` under the soft outline of the
    native `mask`, each partly transparent pixel coloured from the nearest
    fully opaque one, and fully transparent pixels (0, 0, 0, 0)."""
    alpha = soft_alpha(mask)
    colours = np.asarray(rgb.convert("RGB"))
    colours = fill_transparent(colours, alpha == 255, EDGE_FILL_RINGS)
    colours[alpha == 0] = 0
    return Image.fromarray(np.dstack([colours, alpha]), "RGBA")


def nearest_frame(frame_rgba):
    """A skipped frame's output: the native RGBA frame at SCALE, nearest-neighbour."""
    return frame_rgba.convert("RGBA").resize(
        (frame_rgba.width * SCALE, frame_rgba.height * SCALE), Image.Resampling.NEAREST)
```

- [ ] **Step 3: Run the tests**

Run: `.venv/bin/python -m unittest test_sheet_layout -v`
Expected: PASS. With the real export present, `RealCorpusTests` plans all 1,791 animations in about 20 s: 11,394 base sheets, the largest 1952x1440 (`monsters/nkr/nkrd.cl2`). If the count differs, the export changed: re-measure and update the pin, never the layout.

- [ ] **Step 4: Commit**

```bash
git add diablo-texture-enhancement/sheet_layout.py diablo-texture-enhancement/test_sheet_layout.py
git commit -m "feat(kit): lay frames out on sheets and cut them back with a locked outline

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: `geometry_check` — per-frame shift and edges, consistency, gutter bleed

**Files:**
- Create: `diablo-texture-enhancement/geometry_check.py`, `test_geometry_check.py`

**Interfaces:**
- Produces: the gate constants; `luminance`, `phase_shift(a, b) -> (dx, dy)`, `sobel`, `erode(mask)`, `edge_maps(source, render)`; `FrameResult(shift, agreement, issues)`; `check_frame(render, source, mask, label) -> FrameResult`; `step(a, b, both) -> float`; `SheetResult(frames, flicker, bleed, issues)` with `.passed` and `.as_dict()`; `check_sheet(items, canvas=None, gutters=None, background=None) -> SheetResult`, `items` being `[(label, group, render native RGB, source native RGB, mask), ...]` in frame order.

- [ ] **Step 1: Write the failing test `test_geometry_check.py`**

```python
import unittest

import numpy as np
from PIL import Image

import geometry_check as gc

GREY = (128, 128, 128)


def figure(x, w=40, h=32, seed=0):
    """A native RGB frame: 2-px random colour squares in a 16x20 block at x,
    over grey, and its mask."""
    rng = np.random.default_rng(seed)
    out = np.empty((h, w, 3), np.uint8)
    out[:] = GREY
    block = np.kron(rng.integers(0, 256, (10, 8, 3)), np.ones((2, 2, 1))).astype(np.uint8)
    out[6:26, x:x + 16] = block
    mask = np.zeros((h, w), bool)
    mask[6:26, x:x + 16] = True
    return Image.fromarray(out), mask


class FrameTests(unittest.TestCase):
    def test_a_perfect_frame_passes_and_a_shifted_one_fails(self):
        source, mask = figure(10)
        self.assertEqual(gc.check_frame(source, source, mask, "d0/f000.png"),
                         gc.FrameResult((0.0, 0.0), 1.0, ()))
        moved, _ = figure(12)
        result = gc.check_frame(moved, source, mask, "d0/f000.png")
        self.assertAlmostEqual(result.shift[0], 2.0, delta=0.1)
        self.assertIn("geometry: d0/f000.png is shifted +2.0,+0.0 px", result.issues)

    def test_the_edge_measure_ignores_the_locked_outline(self):
        source, mask = figure(10)
        flat = np.asarray(source).copy()
        flat[mask] = flat[mask].mean(axis=0).astype(np.uint8)      # a blob: interior lost
        result = gc.check_frame(Image.fromarray(flat), source, mask, "f")
        self.assertLess(result.agreement, gc.MIN_EDGE_AGREEMENT)
        tiny = np.zeros_like(mask)
        tiny[6:9, 10:13] = True
        self.assertEqual(gc.check_frame(Image.fromarray(flat), source, tiny, "f"),
                         gc.FrameResult((0.0, 0.0), 1.0, ()),
                         msg="too few pixels and edges to judge")


class SheetTests(unittest.TestCase):
    def items(self, renders):
        sources = [figure(10 + i) for i in range(len(renders))]
        return [(f"d0/f{i:03d}.png", 0, render, sources[i][0], sources[i][1])
                for i, render in enumerate(renders)]

    def test_consistency_flags_the_frame_that_flickers(self):
        frames = [figure(10 + i)[0] for i in range(3)]
        self.assertTrue(gc.check_sheet(self.items(frames)).passed)
        other = figure(11, seed=9)[0]                              # frame 1 repainted differently
        result = gc.check_sheet(self.items([frames[0], other, frames[2]]))
        labels = [issue.split(" to ")[0] for issue in result.issues
                  if issue.startswith("consistency")]
        self.assertEqual(labels, ["consistency: d0/f000.png", "consistency: d0/f001.png"])

    def test_pairs_across_directions_or_sizes_are_not_compared(self):
        a, mask = figure(10)
        b = figure(10, seed=9)[0]
        c = Image.new("RGB", (41, 32), GREY)
        items = [("a", 0, a, a, mask), ("b", 1, b, b, mask),
                 ("c", 1, c, c, np.zeros((32, 41), bool))]
        self.assertEqual(gc.check_sheet(items).flicker, ())

    def test_gutter_bleed_is_measured_but_never_an_issue(self):
        canvas = Image.new("RGB", (64, 64), (160, 128, 128))
        gutters = np.ones((64, 64), bool)
        result = gc.check_sheet([], canvas, gutters, GREY)
        self.assertAlmostEqual(result.bleed, 32 / 3)
        self.assertTrue(result.passed)


if __name__ == "__main__":
    unittest.main()
```

Run: `.venv/bin/python -m unittest test_geometry_check -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'geometry_check'`.

- [ ] **Step 2: Write `geometry_check.py`**

`phase_shift`, `sobel` and `_grow` are the Dig kit's, unchanged.

```python
"""The deterministic check of a rendered sheet's frames against their sources.

The gate before promotion. Every frame is compared at native size: the
render's frame (colour-matched, box-downscaled from SCALE) against the source
frame over the flat background. Numpy maths on Pillow images and arrays;
knows no files, animations or audit tree.

Each measure has one job:
- phase correlation finds a figure that slid (a 1-pixel shift reads as 1.0);
- edge agreement, inside the outline (the mask eroded by 1 px, so the locked
  outline cannot inflate it), finds lost or moved inner structure; it has
  the Atlantis hysteresis (a source edge is strong above EDGE_THRESHOLD and
  kept by a render edge above RENDER_EDGE_THRESHOLD within 1 px);
- consistency finds a frame that changes far more from its neighbour than
  the source does (flicker): the render's mean absolute step between
  consecutive frames of a direction, over the pixels opaque in both, against
  the source's;
- gutter bleed (a warning) finds a model that painted outside the cells.

The starting values are the Atlantis gate's where one exists; the spike
recalibrates every one of them for sprites (AGENTS.md).
"""
from dataclasses import dataclass

import numpy as np

MAX_SHIFT = 0.5             # native px
EDGE_THRESHOLD = 80.0       # Sobel magnitude on 0-255 luminance of a strong source edge
RENDER_EDGE_THRESHOLD = 60.0
MIN_EDGE_AGREEMENT = 0.80
MIN_SHIFT_PIXELS = 200      # a frame with fewer opaque native px is too small to measure a shift
MIN_CELL_EDGES = 30         # a frame with fewer strong interior source edges reads 1.0
FLICKER_FACTOR = 2.0        # a pair fails when render step > FACTOR * source step + FLOOR
FLICKER_FLOOR = 4.0         # levels (0-255, mean over RGB)
GUTTER_WARN = 12.0          # levels a gutter's mean may move from the background


def luminance(image):
    return np.asarray(image.convert("L"), dtype=np.float64)


def phase_shift(a, b):
    """(dx, dy) by which luminance array `b` is displaced from `a`, sub-pixel.

    Phase correlation under a Hann window, refined by a parabola through the
    peak. A flat array has no position to measure and reads as (0, 0).
    """
    if a.std() < 1 or b.std() < 1:
        return (0.0, 0.0)
    h, w = a.shape
    window = np.outer(np.hanning(h), np.hanning(w))
    fa = np.fft.fft2((a - a.mean()) * window)
    fb = np.fft.fft2((b - b.mean()) * window)
    cross = fb * np.conj(fa)
    cross /= np.abs(cross) + 1e-9
    corr = np.fft.ifft2(cross).real
    py, px = np.unravel_index(np.argmax(corr), corr.shape)

    def refine(before, peak, after):
        denominator = before - 2 * peak + after
        return 0.0 if denominator == 0 else 0.5 * (before - after) / denominator

    dy = py + refine(corr[(py - 1) % h, px], corr[py, px], corr[(py + 1) % h, px])
    dx = px + refine(corr[py, (px - 1) % w], corr[py, px], corr[py, (px + 1) % w])
    if dy > h / 2:
        dy -= h
    if dx > w / 2:
        dx -= w
    return (round(float(dx), 3) + 0.0, round(float(dy), 3) + 0.0)


def sobel(lum):
    """The Sobel gradient magnitude of the 2-D array `lum`, at its own size;
    edge pixels are repeated at the border."""
    p = np.pad(lum, 1, mode="edge")
    gx = (p[:-2, 2:] + 2 * p[1:-1, 2:] + p[2:, 2:]) - (p[:-2, :-2] + 2 * p[1:-1, :-2] + p[2:, :-2])
    gy = (p[2:, :-2] + 2 * p[2:, 1:-1] + p[2:, 2:]) - (p[:-2, :-2] + 2 * p[:-2, 1:-1] + p[:-2, 2:])
    return np.hypot(gx, gy)


def _grow(mask):
    """`mask` grown by one pixel in every direction."""
    p = np.pad(mask, 1)
    out = np.zeros_like(mask)
    for dy in range(3):
        for dx in range(3):
            out |= p[dy:dy + mask.shape[0], dx:dx + mask.shape[1]]
    return out


def erode(mask):
    """`mask` shrunk by one pixel in every direction."""
    return ~_grow(~mask)


def edge_maps(source, render):
    """(strong, kept): the source's strong edge pixels, and those of them with a
    render edge within 1 px. Arrays are native-size luminance."""
    strong = sobel(source) > EDGE_THRESHOLD
    return strong, strong & _grow(sobel(render) > RENDER_EDGE_THRESHOLD)


@dataclass(frozen=True)
class FrameResult:
    shift: tuple        # (dx, dy), native px
    agreement: float    # interior edge agreement; 1.0 when too sparse to judge
    issues: tuple


def check_frame(render, source, mask, label):
    """Compare one frame: `render` and `source` native RGB images of the same
    size (the source over the flat background), `mask` its native opacity.
    `label` names the frame in the issue strings."""
    small, base = luminance(render), luminance(source)
    issues = []
    shift = (0.0, 0.0)
    if int(mask.sum()) >= MIN_SHIFT_PIXELS:
        shift = phase_shift(base, small)
        if max(abs(shift[0]), abs(shift[1])) >= MAX_SHIFT:
            issues.append(f"geometry: {label} is shifted {shift[0]:+.1f},{shift[1]:+.1f} px")
    strong, kept = edge_maps(base, small)
    inside = erode(mask)
    strong, kept = strong & inside, kept & inside
    count = int(strong.sum())
    agreement = 1.0 if count < MIN_CELL_EDGES else round(float(kept.sum() / count), 4)
    if agreement < MIN_EDGE_AGREEMENT:
        issues.append(f"geometry: {label} edge agreement {agreement:.2f}, needs "
                      f"{MIN_EDGE_AGREEMENT:.2f}")
    return FrameResult(shift, agreement, tuple(issues))


def step(a, b, both):
    """Mean absolute RGB difference of native images `a` and `b` over the bool
    array `both`; 0.0 when it marks nothing."""
    if not both.any():
        return 0.0
    diff = np.abs(np.asarray(a, np.float64) - np.asarray(b, np.float64))
    return float(diff[both].mean())


@dataclass(frozen=True)
class SheetResult:
    frames: tuple       # FrameResult per checked frame, in order
    flicker: tuple      # (label, render step, source step) per consecutive pair of a direction
    bleed: float        # the gutters' mean distance from the background, levels
    issues: tuple

    @property
    def passed(self):
        return not self.issues

    def as_dict(self):
        return {"passed": self.passed,
                "frames": [{"shift": list(f.shift), "agreement": f.agreement}
                           for f in self.frames],
                "flicker": [[label, round(r, 2), round(s, 2)] for label, r, s in self.flicker],
                "bleed": round(self.bleed, 2), "issues": list(self.issues)}


def check_sheet(items, canvas=None, gutters=None, background=None):
    """Check every frame of a sheet. `items` is [(label, group, render, source,
    mask), ...] in frame order: render and source native RGB images, mask the
    native bool opacity. With the rendered `canvas`, its `gutters` (bool) and the
    `background` colour, the gutter bleed is measured too (a warning, never an
    issue)."""
    frames, issues, flicker = [], [], []
    for label, _group, render, source, mask in items:
        result = check_frame(render, source, mask, label)
        frames.append(result)
        issues.extend(result.issues)
    for (label, group, render, source, mask), (_, next_group, r2, s2, m2) in zip(items, items[1:]):
        if group != next_group or render.size != r2.size:
            continue
        both = mask & m2
        rendered, original = step(render, r2, both), step(source, s2, both)
        flicker.append((label, rendered, original))
        if rendered > FLICKER_FACTOR * original + FLICKER_FLOOR:
            issues.append(f"consistency: {label} to the next frame changes {rendered:.1f} levels, "
                          f"the source {original:.1f}")
    bleed = 0.0
    if canvas is not None and gutters is not None and gutters.any():
        pixels = np.asarray(canvas.convert("RGB"), np.float64)[gutters]
        bleed = float(np.abs(pixels - np.array(background, np.float64)).mean())
    return SheetResult(tuple(frames), tuple(flicker), bleed, tuple(issues))
```

- [ ] **Step 3: Run the tests**

Run: `.venv/bin/python -m unittest test_geometry_check -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add diablo-texture-enhancement/geometry_check.py diablo-texture-enhancement/test_geometry_check.py
git commit -m "feat(kit): check each frame's shift, inner edges and frame-to-frame consistency

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: `comfy_client` and the sheet graph

**Files:**
- Create: `diablo-texture-enhancement/comfy_client.py`, `anim_qwen21_i2i.json`, `test_comfy_client.py`

**Interfaces:**
- Produces: `OUTPUT_PREFIX = "dia"`; `Workflow` (fields `name template guide anchor anchor_input positive negative seed save model_files node_classes reference anchor_reference settings fallback`); `WORKFLOWS` (`qwen-image-2.1-i2i`, `qwen-image-2.1-i2i-faithful`); `DEFAULT_WORKFLOW`; the Dig plumbing (`load_template`, `http_json`, `is_up`, `free_models`, `missing_model_files`, `missing_nodes`, `wait_history`, `stage_input`, `execute`, `output_path`); `comfy_name(key) -> str` (slashes to `+`); `render_sheet(workflow, *, guide, anchor, positive, negative, seed, name, url, comfy_dir, http=..., timeout=..., sleep=...) -> Path`; `sweep_outputs(name, comfy_dir) -> int`.
- Node ids: 1 LoadImage (guide canvas: reference `images.image_1` and the VAE-encoded start latent), 2 LoadImage (anchor: `images.image_2`; removed with its slot when there is no anchor), 4 CLIPLoader (qwen3vl_8b), 5 UNETLoader (2.1 bf16), 6 VAELoader, 9 TextEncodeQwenImage21 (resolution 0), 11 VAEEncode, 13 KSampler (40 steps, cfg 1.0, denoise 1.0), 14 VAEDecode, 15 SaveImage. The encoder's reference slots are autogrow inputs `images.image_1` … `images.image_16` (ComfyUI docs); a flat `image_1` key kills the render (the AITD kit's live check).

- [ ] **Step 1: Write the failing test `test_comfy_client.py`**

```python
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

import comfy_client


class FakeComfy:
    """Answers /prompt, /history and /interrupt like ComfyUI, saving one render."""

    def __init__(self, comfy_dir, status="success", history=True):
        self.comfy_dir, self.status, self.history, self.calls = comfy_dir, status, history, []

    def __call__(self, url, data=None, timeout=60, token=None):
        self.calls.append((url, json.loads(data) if data else None))
        if url.endswith("/prompt"):
            return {"prompt_id": "p1"}
        if url.endswith("/interrupt"):
            return {}
        if "/history/" in url:
            if not self.history:
                return {}
            prefix = self.calls[0][1]["prompt"]["15"]["inputs"]["filename_prefix"]
            folder, stem = prefix.split("/")
            out = self.comfy_dir / "output" / folder
            out.mkdir(parents=True, exist_ok=True)
            name = f"{stem}_00001_.png"
            Image.new("RGB", (32, 32)).save(out / name)
            return {"p1": {"status": {"status_str": self.status, "messages": ["boom"]},
                           "outputs": {"15": {"images": [{"filename": name, "subfolder": folder,
                                                          "type": "output"}]}}}}
        raise AssertionError(f"unexpected request {url}")


def links(prompt):
    return [(node_id, value[0]) for node_id, node in prompt.items()
            for value in node["inputs"].values()
            if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str)]


class TemplateTests(unittest.TestCase):
    def test_each_record_matches_its_template(self):
        self.assertIn(comfy_client.DEFAULT_WORKFLOW, comfy_client.WORKFLOWS)
        for name, wf in comfy_client.WORKFLOWS.items():
            with self.subTest(name):
                prompt = comfy_client.load_template(wf)
                for node, key in (wf.guide, wf.anchor, wf.anchor_input, wf.positive,
                                  wf.negative, wf.seed):
                    self.assertIn(key, prompt[node]["inputs"])
                self.assertEqual(prompt[wf.guide[0]]["class_type"], "LoadImage")
                self.assertEqual(prompt[wf.anchor[0]]["class_type"], "LoadImage")
                self.assertEqual(prompt[wf.anchor_input[0]]["inputs"][wf.anchor_input[1]],
                                 [wf.anchor[0], 0])
                # The 2.1 encoder's autogrow slots: a flat "image_1" key kills the render.
                self.assertEqual(prompt["9"]["inputs"]["images.image_1"], [wf.guide[0], 0])
                for _folder, node, key in wf.model_files:
                    self.assertIn(key, prompt[node]["inputs"])
                classes = {node["class_type"] for node in prompt.values()}
                self.assertTrue(set(wf.node_classes) <= classes)
                sampler = prompt[wf.seed[0]]
                encode = prompt[sampler["inputs"]["latent_image"][0]]
                self.assertEqual((encode["class_type"], encode["inputs"]["pixels"]),
                                 ("VAEEncode", [wf.guide[0], 0]))
                self.assertEqual(prompt[wf.save]["class_type"], "SaveImage")
                for node_id, target in links(prompt):
                    self.assertIn(target, prompt, f"node {node_id} links to {target}")

    def test_the_fallback_is_the_template_at_denoise_0_9(self):
        full = comfy_client.WORKFLOWS["qwen-image-2.1-i2i"]
        faithful = comfy_client.WORKFLOWS[full.fallback]
        expected = comfy_client.load_template(full)
        self.assertEqual(expected["13"]["inputs"]["denoise"], 1.0)
        expected["13"]["inputs"]["denoise"] = 0.9
        self.assertEqual(comfy_client.load_template(faithful), expected)
        self.assertIsNone(faithful.fallback)


class RenderSheetTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.comfy_dir = Path(tmp.name) / "comfy"
        self.inputs = Path(tmp.name) / "in"
        self.inputs.mkdir()
        for part in ("guide", "anchor"):
            Image.new("RGB", (32, 32)).save(self.inputs / f"{part}.png")

    def render(self, anchor=True, http=None, timeout=60, sleep=lambda s: None):
        http = http or FakeComfy(self.comfy_dir)
        path = comfy_client.render_sheet(
            comfy_client.WORKFLOWS["qwen-image-2.1-i2i"], guide=self.inputs / "guide.png",
            anchor=self.inputs / "anchor.png" if anchor else None, positive="paint it",
            negative="no photo", seed=43, name="monsters+zombie+zombiew.cl2+s01_a1-sheet",
            url="http://c", comfy_dir=self.comfy_dir, http=http, timeout=timeout, sleep=sleep)
        return path, http

    def test_render_sheet_fills_the_graph(self):
        path, http = self.render()
        name = "monsters+zombie+zombiew.cl2+s01_a1-sheet"
        self.assertEqual(path, self.comfy_dir / "output" / "dia" / f"{name}_00001_.png")
        prompt = http.calls[0][1]["prompt"]
        for node, part in (("1", "guide"), ("2", "anchor")):
            staged = f"__dia_{name}_{part}.png"
            self.assertEqual(prompt[node]["inputs"]["image"], staged)
            self.assertTrue((self.comfy_dir / "input" / staged).is_file())
        inputs = prompt["9"]["inputs"]
        self.assertEqual((inputs["prompt"], inputs["negative_prompt"]), ("paint it", "no photo"))
        self.assertEqual(prompt["13"]["inputs"]["seed"], 43)
        self.assertEqual(prompt["15"]["inputs"]["filename_prefix"], f"dia/{name}")

    def test_without_an_anchor_the_second_reference_is_removed(self):
        _, http = self.render(anchor=False)
        prompt = http.calls[0][1]["prompt"]
        self.assertNotIn("2", prompt)
        self.assertNotIn("images.image_2", prompt["9"]["inputs"])
        self.assertEqual([t for _, t in links(prompt) if t not in prompt], [])

    def test_failures_and_interrupts(self):
        with self.subTest("a failed execution"):
            with self.assertRaisesRegex(RuntimeError, "ComfyUI execution failed"):
                self.render(http=FakeComfy(self.comfy_dir, status="error"))
        with self.subTest("a timeout interrupts the prompt"):
            http = FakeComfy(self.comfy_dir, history=False)
            with self.assertRaises(TimeoutError):
                self.render(http=http, timeout=0)
            self.assertEqual(http.calls[-1], ("http://c/interrupt", {"prompt_id": "p1"}))

        def ctrl_c(seconds):
            raise KeyboardInterrupt
        with self.subTest("Ctrl-C interrupts the prompt"):
            http = FakeComfy(self.comfy_dir, history=False)
            with self.assertRaises(KeyboardInterrupt):
                self.render(http=http, sleep=ctrl_c)
            self.assertEqual(http.calls[-1], ("http://c/interrupt", {"prompt_id": "p1"}))


class PreflightTests(unittest.TestCase):
    def test_missing_model_files_and_nodes(self):
        wf = comfy_client.WORKFLOWS["qwen-image-2.1-i2i"]
        with tempfile.TemporaryDirectory() as tmp:
            missing = comfy_client.missing_model_files(wf, tmp)
            self.assertEqual(missing, ["models/diffusion_models/qwen_image_2.1_bf16.safetensors",
                                       "models/text_encoders/qwen3vl_8b_bf16.safetensors",
                                       "models/vae/qwen_image_2.1_vae_bf16.safetensors"])

        def http(url, timeout=60):
            raise RuntimeError("HTTP 500")
        self.assertEqual(comfy_client.missing_nodes(wf, "http://c", http),
                         ["TextEncodeQwenImage21"])

    def test_is_up_and_free(self):
        calls = []

        def http(url, data=None, timeout=60):
            calls.append((url, data))
            return {}
        self.assertTrue(comfy_client.is_up("http://c", http))
        comfy_client.free_models("http://c", http)
        self.assertEqual(calls[-1], ("http://c/free",
                                     b'{"unload_models": true, "free_memory": true}'))


class SweepTests(unittest.TestCase):
    def test_sweep_removes_only_the_sheets_own_renders(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "output" / "dia"
            out.mkdir(parents=True)
            name = comfy_client.comfy_name("monsters/zombie/zombiew.cl2/s01")
            self.assertEqual(name, "monsters+zombie+zombiew.cl2+s01")
            for file in (f"{name}_a1-sheet_00001_.png", f"{name}_a3-sheet_00002_.png",
                         "monsters+zombie+zombiew.cl2+@trn+monsters+zombie+grey.trn+s01"
                         "_a1-sheet_00001_.png",
                         "monsters+zombie+zombiew.cl2+s02_a1-sheet_00001_.png"):
                (out / file).touch()
            self.assertEqual(comfy_client.sweep_outputs(name, tmp), 2)
            self.assertEqual(len(list(out.iterdir())), 2)
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(comfy_client.sweep_outputs(name, tmp), 0)


if __name__ == "__main__":
    unittest.main()
```

Run: `.venv/bin/python -m unittest test_comfy_client -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'comfy_client'`.

- [ ] **Step 2: Write `anim_qwen21_i2i.json`**

```json
{
 "prompt": {
  "1": {"class_type": "LoadImage", "inputs": {"image": "guide.png"}},
  "2": {"class_type": "LoadImage", "inputs": {"image": "anchor.png"}},
  "4": {"class_type": "CLIPLoader", "inputs": {
    "clip_name": "qwen3vl_8b_bf16.safetensors", "type": "qwen_image"}},
  "5": {"class_type": "UNETLoader", "inputs": {
    "unet_name": "qwen_image_2.1_bf16.safetensors", "weight_dtype": "default"}},
  "6": {"class_type": "VAELoader", "inputs": {"vae_name": "qwen_image_2.1_vae_bf16.safetensors"}},
  "9": {"class_type": "TextEncodeQwenImage21", "inputs": {
    "clip": ["4", 0], "vae": ["6", 0], "prompt": "", "negative_prompt": "", "resolution": 0,
    "images.image_1": ["1", 0], "images.image_2": ["2", 0]}},
  "11": {"class_type": "VAEEncode", "inputs": {"pixels": ["1", 0], "vae": ["6", 0]}},
  "13": {"class_type": "KSampler", "inputs": {
    "model": ["5", 0], "seed": 42, "steps": 40, "cfg": 1.0, "sampler_name": "euler",
    "scheduler": "simple", "positive": ["9", 0], "negative": ["9", 1],
    "latent_image": ["11", 0], "denoise": 1.0}},
  "14": {"class_type": "VAEDecode", "inputs": {"samples": ["13", 0], "vae": ["6", 0]}},
  "15": {"class_type": "SaveImage", "inputs": {"images": ["14", 0], "filename_prefix": "dia"}}
 }
}
```

- [ ] **Step 3: Write `comfy_client.py`**

```python
"""Thin client for the local ComfyUI HTTP API.

The only module that knows workflow node ids. WORKFLOWS records, per render
workflow, the template file and where the driver's values go:
  guide         LoadImage: the sheet's guide canvas, also the first reference
                image and the latent the sampler starts from
  anchor        LoadImage: the anchor sheet, the second reference image; with
                no anchor its node and `anchor_input` are removed from the graph
  positive, negative, seed, save  as named
  settings      graph values this workflow overrides in its template
  fallback      the workflow batch renders a stuck sheet through once more
The HTTP plumbing (http_json, is_up, free_models, missing_model_files,
missing_nodes, wait_history, stage_input, execute, output_path) is the Dig
kit's, unchanged.
"""
import json
import re
import shutil
import time
import urllib.error
import urllib.request
from collections import namedtuple
from pathlib import Path

HISTORY_TIMEOUT = 1800
POLL_SECONDS = 2
OUTPUT_PREFIX = "dia"
REPO_DIR = Path(__file__).resolve().parent

# name:        registry key, also written into attempt-N.prompt.txt and attempt-N.json
# template:    workflow file, relative to the repository (absolute paths work too)
# guide, anchor: (node id, input key) that receive the two staged images
# anchor_input: (node id, input key) of the encoder slot the anchor feeds
# positive, negative, seed: (node id, input key)
# save:        SaveImage node id
# model_files: (models subfolder, node id, input key) ComfyUI must have on disk
# node_classes: class_type values the ComfyUI build must know
# reference, anchor_reference: how the positive prompt names the guide and the anchor
# settings:    ((node id, input key), value) pairs written over the template's values
# fallback:    registry key of the workflow for a sheet this one left stuck, or None
Workflow = namedtuple("Workflow", "name template guide anchor anchor_input positive negative "
                                  "seed save model_files node_classes reference anchor_reference "
                                  "settings fallback",
                      defaults=((), None))

WORKFLOWS = {
    "qwen-image-2.1-i2i": Workflow(
        name="qwen-image-2.1-i2i",
        template="anim_qwen21_i2i.json",
        guide=("1", "image"), anchor=("2", "image"), anchor_input=("9", "images.image_2"),
        positive=("9", "prompt"), negative=("9", "negative_prompt"), seed=("13", "seed"),
        save="15",
        model_files=(("diffusion_models", "5", "unet_name"),
                     ("text_encoders", "4", "clip_name"),
                     ("vae", "6", "vae_name")),
        node_classes=("TextEncodeQwenImage21",),
        reference="<image1>", anchor_reference="<image2>",
        fallback="qwen-image-2.1-i2i-faithful"),
}
# The same graph below full denoise: a cleaner repaint that keeps closer to the
# guide, for a sheet the gate or the review rejected MAX_ATTEMPTS times (the
# Atlantis choice; the spike may change it).
WORKFLOWS["qwen-image-2.1-i2i-faithful"] = WORKFLOWS["qwen-image-2.1-i2i"]._replace(
    name="qwen-image-2.1-i2i-faithful", settings=((("13", "denoise"), 0.9),), fallback=None)
DEFAULT_WORKFLOW = "qwen-image-2.1-i2i"


def load_template(workflow):
    """The `prompt` graph of the workflow's template file, read fresh, with the
    workflow's settings applied."""
    path = Path(workflow.template)
    if not path.is_absolute():
        path = REPO_DIR / path
    prompt = json.loads(path.read_text())["prompt"]
    for (node, key), value in workflow.settings:
        prompt[node]["inputs"][key] = value
    return prompt


def http_json(url, data=None, timeout=60, token=None):
    headers = {}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode(errors="replace")[:2000]
        except Exception:
            detail = ""
        raise RuntimeError(f"HTTP {e.code} {e.reason} for {url}: {detail}") from e


def is_up(url, http=http_json):
    try:
        http(f"{url}/queue", timeout=5)
        return True
    except (OSError, ValueError, RuntimeError):
        return False


def free_models(url, http=http_json):
    http(f"{url}/free", json.dumps({"unload_models": True, "free_memory": True}).encode(),
         timeout=60)


def missing_model_files(workflow, comfy_dir):
    """Workflow model files absent from <comfy_dir>/models, as relative paths."""
    prompt = load_template(workflow)
    missing = []
    for folder, node, key in workflow.model_files:
        name = prompt[node]["inputs"][key]
        if not (Path(comfy_dir) / "models" / folder / name).is_file():
            missing.append(f"models/{folder}/{name}")
    return missing


def missing_nodes(workflow, url, http=http_json):
    """Node classes of the workflow that the running ComfyUI does not describe.

    GET /object_info/<class> answers {} for an unknown class; an HTTP error
    counts as unknown too, so an old checkout fails the preflight, not the render.
    """
    missing = []
    for cls in workflow.node_classes:
        try:
            info = http(f"{url}/object_info/{cls}", timeout=30)
        except (OSError, ValueError, RuntimeError):
            info = {}
        if not isinstance(info, dict) or cls not in info:
            missing.append(cls)
    return missing


def wait_history(url, prompt_id, http=http_json, timeout=HISTORY_TIMEOUT, sleep=time.sleep):
    deadline = time.monotonic() + timeout
    while True:
        hist = http(f"{url}/history/{prompt_id}")
        if prompt_id in hist:
            return hist[prompt_id]
        if time.monotonic() >= deadline:
            raise TimeoutError(f"no history for {prompt_id} within {timeout}s")
        sleep(POLL_SECONDS)


def stage_input(source, stage_name, comfy_dir):
    """Copy `source` into ComfyUI's input folder as `stage_name`."""
    input_dir = Path(comfy_dir) / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, input_dir / stage_name)


def execute(prompt, url, http, timeout, sleep, interrupt=False):
    """Queue `prompt` and return its history entry once it succeeded.

    Raises RuntimeError when ComfyUI reports a failed execution and
    TimeoutError when the history never appears. With `interrupt`, a timeout
    or a KeyboardInterrupt while waiting first asks ComfyUI to stop the prompt
    (best effort: a failed interrupt must not hide the original exception).
    """
    resp = http(f"{url}/prompt", json.dumps({"prompt": prompt}).encode())
    try:
        entry = wait_history(url, resp["prompt_id"], http, timeout, sleep)
    except (TimeoutError, KeyboardInterrupt):
        if interrupt:
            try:
                http(f"{url}/interrupt", json.dumps({"prompt_id": resp["prompt_id"]}).encode())
            except Exception:
                pass
        raise
    status = entry.get("status", {})
    if status.get("status_str") != "success":
        raise RuntimeError(f"ComfyUI execution failed: {status.get('messages', status)}")
    return entry


def output_path(comfy_dir, img):
    """Where ComfyUI saved the output image `img` (a history `images[]` entry)."""
    return Path(comfy_dir) / "output" / (img.get("subfolder") or "") / img["filename"]


def comfy_name(key):
    """A sheet key as a flat ComfyUI file name: its slashes become "+"."""
    return key.replace("/", "+")


def render_sheet(workflow, *, guide, anchor, positive, negative, seed, name, url, comfy_dir,
                 http=http_json, timeout=HISTORY_TIMEOUT, sleep=time.sleep):
    """Queue one sheet render and return the path of the image ComfyUI saved.

    `guide` and `anchor` (or None) are local PNG paths, staged into ComfyUI's
    input folder as __dia_<name>_<part>.png. The render lands in output/dia/
    as <name>_NNNNN_.png; the caller moves it away and checks its size. Raises
    RuntimeError when ComfyUI reports a failed execution, and TimeoutError,
    after asking ComfyUI to interrupt the prompt, when no history appears in
    time; a KeyboardInterrupt while waiting interrupts the prompt too.
    """
    comfy_dir = Path(comfy_dir)
    prompt = load_template(workflow)
    parts = [(workflow.guide, guide, "guide")]
    if anchor is None:
        del prompt[workflow.anchor[0]]
        del prompt[workflow.anchor_input[0]]["inputs"][workflow.anchor_input[1]]
    else:
        parts.append((workflow.anchor, anchor, "anchor"))
    for (node, key), path, part in parts:
        staged = f"__dia_{name}_{part}.png"
        stage_input(path, staged, comfy_dir)
        prompt[node]["inputs"][key] = staged
    for (node, key), value in ((workflow.positive, positive), (workflow.negative, negative),
                               (workflow.seed, seed)):
        prompt[node]["inputs"][key] = value
    prompt[workflow.save]["inputs"]["filename_prefix"] = f"{OUTPUT_PREFIX}/{name}"
    # A timed-out or Ctrl-C'd render is still running in ComfyUI; interrupt it so
    # it does not hold the queue (and ~45 GB) and write a file nobody collects.
    entry = execute(prompt, url, http, timeout, sleep, interrupt=True)
    return output_path(comfy_dir, entry["outputs"][workflow.save]["images"][0])


def sweep_outputs(name, comfy_dir):
    """Delete a sheet's leftover renders under output/dia/, named as SaveImage
    names them: <name>_a<attempt>-sheet_NNNNN_.png, `name` a comfy_name. Returns
    the count. Another sheet's names never match: the pattern needs "_a" right
    after `name`."""
    folder = Path(comfy_dir) / "output" / OUTPUT_PREFIX
    pattern = re.compile(rf"^{re.escape(name)}_a\d+-[A-Za-z0-9-]+_\d{{5}}_\.png$")
    removed = 0
    if folder.is_dir():
        for path in folder.iterdir():
            if pattern.match(path.name):
                path.unlink(missing_ok=True)
                removed += 1
    return removed
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m unittest test_comfy_client -v`
Expected: PASS. The graph is only validated by rendering it (Task 13, Step 2).

- [ ] **Step 5: Commit**

```bash
git add diablo-texture-enhancement/comfy_client.py diablo-texture-enhancement/anim_qwen21_i2i.json diablo-texture-enhancement/test_comfy_client.py
git commit -m "feat(kit): ComfyUI client and the two-reference sheet graph

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Prompts

**Files:**
- Create: `diablo-texture-enhancement/prompts.py`, `test_prompts.py`

**Interfaces:**
- Produces: `CAPTION_QUESTION`, `SECTION_LABELS`, `SPRITE_RULES`, `ANCHOR_NOTE`, `VARIANT_NOTE`, `GEOMETRY_CORRECTION`, `PAINTED_NEGATIVE`, `REVIEW_QUESTION`; `section(caption, label)`, `without_colours(caption)`; `render_prompt(caption, count, *, reference, anchor_reference=None, variant=False, corrections=()) -> str`; `caption_character(images, http, base_url, model, key) -> str`; `parse_review(text) -> {"accepted", "issues"}`; `review_sheet(guide, render, anchor, count, http, base_url, model, key) -> {"accepted", "issues"}`; `vlm_is_serving(base_url, model, http, key="")`. `_image`, `_ask`, `_json_text`, `_verdict` are the Dig kit's.

- [ ] **Step 1: Write the failing test `test_prompts.py`**

```python
import json
import unittest

from PIL import Image

import prompts

CAPTION = ("**SUBJECT:** a rotting zombie\nBODY AND MATERIALS: grey flesh, torn rags\n"
           "COLOURS: green-grey skin, brown rags\nSHADOW: a dark blot to the lower left\n"
           "INVARIANTS: arms forward")


class RenderPromptTests(unittest.TestCase):
    def test_a_base_sheet_with_an_anchor_and_corrections(self):
        text = prompts.render_prompt(CAPTION, 16, reference="<image1>",
                                     anchor_reference="<image2>",
                                     corrections=["cell 3 lost its left arm"])
        self.assertTrue(text.startswith("<image1> is a sheet of 16 frames"))
        self.assertIn("<image2> shows the same figure already painted", text)
        self.assertIn("REFERENCE OBSERVATIONS:\n" + CAPTION, text)
        self.assertIn("PREVIOUS ATTEMPT WHILE KEEPING THE REFERENCE LAYOUT:\ncell 3 lost its left "
                      "arm", text)
        self.assertNotIn("colour variant", text)

    def test_a_variant_drops_the_caption_colours(self):
        text = prompts.render_prompt(CAPTION, 4, reference="<image1>", variant=True)
        self.assertIn("take its colours from <image1>", text)
        self.assertNotIn("green-grey", text)
        self.assertIn("SHADOW: a dark blot", text)
        self.assertNotIn("already painted", text, msg="no anchor, no anchor note")

    def test_sections(self):
        self.assertEqual(prompts.section(CAPTION, "SUBJECT"), "a rotting zombie")
        self.assertEqual(prompts.section(CAPTION, "EQUIPMENT"), None)
        self.assertEqual(prompts.without_colours("SUBJECT: x"), "SUBJECT: x")


class ReviewTests(unittest.TestCase):
    def test_parse_review_tolerates_fences_and_refuses_contradictions(self):
        self.assertEqual(prompts.parse_review('```json\n{"accepted": false, "issues": ["cell 2"]}'
                                              '\n```'),
                         {"accepted": False, "issues": ["cell 2"]})
        for text in ('{"accepted": true, "issues": ["x"]}', '{"accepted": "yes", "issues": []}'):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    prompts.parse_review(text)

    def test_review_sheet_sends_guide_render_and_anchor(self):
        sent = {}

        def http(url, data=None, timeout=60, token=None):
            sent.update(json.loads(data))
            return {"choices": [{"finish_reason": "stop", "message": {
                "content": '{"accepted": true, "issues": []}'}}]}
        image = Image.new("RGB", (64, 32))
        verdict = prompts.review_sheet(image, image, image, 12, http, "http://v/v1", "m", "")
        self.assertEqual(verdict, {"accepted": True, "issues": []})
        content = sent["messages"][1]["content"]
        self.assertTrue(content[0]["text"].endswith("This sheet has 12 cell(s)."))
        self.assertEqual(len(content), 4, msg="question, guide, render, anchor")


if __name__ == "__main__":
    unittest.main()
```

Run: `.venv/bin/python -m unittest test_prompts -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'prompts'`.

- [ ] **Step 2: Write `prompts.py`**

```python
"""Prompts and VLM requests: the caption question, the sprite-sheet render
prompt, the review question and its parser.

Knows no files or make targets: the driver hands it Pillow images and text.
The VLM plumbing (_image, _ask, _json_text, _verdict, parse_review,
vlm_is_serving) is the Dig kit's, unchanged.
"""
import base64
import io
import json
import re

from PIL import Image

CAPTION_TIMEOUT = 900   # a caption is up to 1000 tokens; about 4 tok/s on this host
REVIEW_TIMEOUT = 600
VLM_MAX_SIDE = 1280     # every image is scaled so its longer side is this

CAPTION_QUESTION = '''The images show one character, creature or spell effect from Diablo (Blizzard North, 1996), a dark gothic-fantasy action role-playing game with small pre-rendered sprites seen from an isometric view. Image 1 shows its reference animation, one frame per direction. Image 2, when present, shows the first frame of each of its other animations. Describe it for an artist who will repaint every frame in high definition with exactly the same poses and outlines. Report only what the images show; this is observation, not creative writing.
Use these short labelled sections:
SUBJECT: what it is (a warrior, a zombie, a fireball, a townsperson) and its build, pose and bearing.
BODY AND MATERIALS: skin, fur, bone, cloth, leather, metal or flame, and where each is.
EQUIPMENT: weapons, shields, armour pieces and carried objects; say none if there are none.
COLOURS: the dominant colours of each part.
SHADOW: the shadow it casts on the ground, its shape and direction; say none if there is none.
INVARIANTS: what must not change between frames and directions. Mark ambiguity instead of inventing detail.
Do not prescribe a style, lens or colour grade. Keep under 300 words.'''

SECTION_LABELS = ("SUBJECT", "BODY AND MATERIALS", "EQUIPMENT", "COLOURS", "SHADOW", "INVARIANTS")

SPRITE_RULES = '''{reference} is a sheet of {count} frames of one animation of a game sprite from Diablo (1996), laid out in cells on a flat background. Repaint every cell as a high-definition hand-painted dark-fantasy game sprite: rich painted detail, crisp readable forms, the gothic mood of the original.
Keep each cell's pose, outline, size and position exactly as the reference shows it; nothing is moved, added, removed or resized. Every cell is the same figure: the same light from the same side, the same colours and the same painting in every cell, so the frames animate without flicker.
Leave the background and the gaps between cells flat and untouched; paint nothing outside the figures. Keep the shadow a flat dark shadow on the ground.
No photograph, no 3D render, no pixel art, no border or frame, no text.'''

ANCHOR_NOTE = '''{anchor} shows the same figure already painted in high definition. Match its painting exactly: the same materials, colours, brushwork, detail and light.'''

VARIANT_NOTE = '''This figure is a colour variant: take its colours from {reference}, not from the observations below.'''

# The one correction after a geometry rejection: the gate's issue strings mean
# nothing to the diffusion model, and it likes to paint text it is given.
GEOMETRY_CORRECTION = ("Keep every figure's outline, pose, size and position exactly where the "
                       "reference image has it, in every cell; do not shift, crop, rescale or "
                       "redraw any figure, and keep the frames consistent with each other.")

PAINTED_NEGATIVE = ("photograph, photorealistic, 3D render, CGI, pixel art, dithering, jpeg "
                    "artifacts, blurry, noisy, extra limbs, extra figures, extra objects, text, "
                    "watermark, signature, frame, border, background scenery")

REVIEW_QUESTION = '''Image 1 is a sheet of frames of one animation of a 1996 game sprite (smoothed and enlarged): the authoritative original. Image 2 is the same sheet repainted in high definition. Image 3, when present, is the same figure already accepted in high definition: the reference for how it must look. The cells hold consecutive frames, left to right, row by row. New painted detail replacing the original's pixels is the goal and is never a reason to reject.
Reject when:
1. identity: a cell shows a different figure, body, weapon or equipment than the original, or than image 3;
2. consistency: the cells differ from each other in colours, materials, light or detail more than the motion explains, so the animation would flicker;
3. invention: a limb, weapon, object or effect is added or dropped, or a pose changed;
4. cells: a figure bleeds into a neighbouring cell or paints into the background;
5. style: the repaint looks like a photograph or a 3D render, or keeps the original's blocky pixels.
Return ONLY JSON: {"accepted": true or false, "issues": ["one specific problem: its cell number (1 is the top left), what is wrong and a concrete correction"]}. Accept only if there are no significant problems; use an empty issues list when accepted. At most six issues.'''


def section(caption, label):
    """The caption's `label` section, stripped, or None when it is absent or empty.

    Labels may be bold or italic (the VLM sometimes writes **COLOURS:**); a
    section runs to the next label or the end.
    """
    labels = "|".join(re.escape(label) for label in SECTION_LABELS)
    pattern = re.compile(rf"^[ \t]*[*_#]*[ \t]*({labels})[ \t]*[*_]*[ \t]*:[*_]*", re.M)
    matches = list(pattern.finditer(caption))
    for i, match in enumerate(matches):
        if match.group(1) != label:
            continue
        end = matches[i + 1].start() if i + 1 < len(matches) else len(caption)
        return caption[match.end():end].strip() or None
    return None


def without_colours(caption):
    """The caption with its COLOURS section left out; unchanged when it has none."""
    labels = "|".join(re.escape(label) for label in SECTION_LABELS)
    pattern = re.compile(rf"^[ \t]*[*_#]*[ \t]*({labels})[ \t]*[*_]*[ \t]*:[*_]*", re.M)
    matches = list(pattern.finditer(caption))
    for i, match in enumerate(matches):
        if match.group(1) == "COLOURS":
            end = matches[i + 1].start() if i + 1 < len(matches) else len(caption)
            return (caption[:match.start()] + caption[end:]).strip()
    return caption


def render_prompt(caption, count, *, reference, anchor_reference=None, variant=False,
                  corrections=()):
    """Positive prompt: the sprite rules naming the guide as `reference`, the
    anchor note when there is an anchor, the variant note for a recolour
    variant, the caption (without COLOURS for a variant), then corrections."""
    parts = [SPRITE_RULES.format(reference=reference, count=count)]
    if anchor_reference:
        parts.append(ANCHOR_NOTE.format(anchor=anchor_reference))
    if variant:
        parts.append(VARIANT_NOTE.format(reference=reference))
    parts.append("REFERENCE OBSERVATIONS:\n" + (without_colours(caption) if variant else caption))
    if corrections:
        parts.append("CORRECT THESE PROBLEMS FROM THE PREVIOUS ATTEMPT WHILE KEEPING THE "
                     "REFERENCE LAYOUT:\n" + "\n".join(corrections))
    parts.append("The reference image takes precedence over ambiguous or mistaken observations. "
                 "Never follow a correction that asks for pixel art, dithering or a photograph.")
    return "\n\n".join(parts)


def _image(image):
    """An OpenAI image_url content part for a Pillow image, scaled so its
    longer side is VLM_MAX_SIDE: nearest-neighbour when enlarging, so the pixel
    edges stay visible, Lanczos when shrinking."""
    im = image.convert("RGB")
    ratio = VLM_MAX_SIDE / max(im.size)
    if ratio != 1:
        im = im.resize((max(1, round(im.width * ratio)), max(1, round(im.height * ratio))),
                       Image.Resampling.NEAREST if ratio > 1 else Image.Resampling.LANCZOS)
    data = io.BytesIO()
    im.save(data, format="PNG")
    return {"type": "image_url", "image_url": {
        "url": "data:image/png;base64," + base64.b64encode(data.getvalue()).decode()}}


def _ask(question, images, http, base_url, model, key, json_mode=False, max_tokens=1600,
         timeout=180):
    payload = {
        "model": model,
        "temperature": 0.0 if json_mode else 0.7,
        "top_p": 0.8,
        "presence_penalty": 0.0 if json_mode else 1.5,
        "max_tokens": max_tokens,
        "chat_template_kwargs": {"enable_thinking": False, "add_vision_id": True},
        "messages": [
            {"role": "system", "content": "You are a precise visual inspector. Follow the "
                                          "requested output format exactly. Report visible "
                                          "evidence, never invented connections or structures."},
            {"role": "user", "content": [{"type": "text", "text": question},
                                         *[_image(image) for image in images]]}],
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    response = http(base_url.rstrip("/") + "/chat/completions", json.dumps(payload).encode(),
                    timeout=timeout, token=key)
    choice = response["choices"][0]
    if choice.get("finish_reason") == "length":
        raise ValueError("VLM response was truncated; no result accepted")
    text = choice["message"]["content"]
    if not isinstance(text, str) or not text.strip():
        raise ValueError("VLM returned no usable text")
    return text.strip()


def caption_character(images, http, base_url, model, key):
    """The VLM's caption of a character from its contact sheets."""
    return _ask(CAPTION_QUESTION, images, http, base_url, model, key, max_tokens=1000,
                timeout=CAPTION_TIMEOUT)


def _json_text(text, required):
    """The JSON object in the VLM's answer that has the key `required`,
    tolerating fences and chatter."""
    text = text.strip()
    if "```" in text:
        parts = text.split("```")
        for i in range(1, len(parts), 2):
            chunk = parts[i].strip()
            if chunk.startswith("json"):
                chunk = chunk[4:].strip()
            try:
                value = json.loads(chunk)
            except ValueError:
                continue
            if isinstance(value, dict) and required in value:
                return chunk
    elif not text.startswith("{") and "{" in text and "}" in text:
        return text[text.find("{"):text.rfind("}") + 1].strip()
    return text


def _verdict(value):
    """{"accepted", "issues"} from one verdict mapping, or ValueError."""
    if not isinstance(value, dict) or type(value.get("accepted")) is not bool:
        raise ValueError("VLM review must contain a boolean accepted verdict")
    issues = value.get("issues")
    if not isinstance(issues, list) or any(not isinstance(x, str) or not x.strip() for x in issues):
        raise ValueError("VLM review must contain a list of nonempty issue strings")
    if value["accepted"] != (not issues):
        raise ValueError("VLM review verdict contradicts its issues")
    return {"accepted": value["accepted"], "issues": issues}


def parse_review(text):
    """{"accepted", "issues"} from the VLM's answer, tolerating fences and chatter."""
    return _verdict(json.loads(_json_text(text, "accepted")))


def review_sheet(guide, render, anchor, count, http, base_url, model, key):
    """The VLM's verdict on a sheet: its guide canvas, its render canvas, and
    the anchor canvas (or None) the render was painted against."""
    question = REVIEW_QUESTION + f"\nThis sheet has {count} cell(s)."
    images = [guide, render] + ([anchor] if anchor is not None else [])
    return parse_review(_ask(question, images, http, base_url, model, key, json_mode=True,
                             max_tokens=1200, timeout=REVIEW_TIMEOUT))


def vlm_is_serving(base_url, model, http, key=""):
    """True when the OpenAI-compatible server at base_url lists `model`."""
    try:
        models = http(base_url.rstrip("/") + "/models", timeout=5, token=key)["data"]
        return any(m.get("id") == model for m in models)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, AttributeError):
        return False
```

- [ ] **Step 3: Run the tests**

Run: `.venv/bin/python -m unittest test_prompts -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add diablo-texture-enhancement/prompts.py diablo-texture-enhancement/test_prompts.py
git commit -m "feat(kit): caption, sprite-sheet render and review prompts

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: The driver — jobs, statuses, anchors and `batch`

**Files:**
- Create: `diablo-texture-enhancement/anim_recreate.py`, `test_anim_recreate.py`
- Modify: `diablo-texture-enhancement/testkit.py` (the import block, and the driver half appended)

**Interfaces:**
- Consumes: every module above.
- Produces (used by Tasks 10–11):
  - `Job(anim, trn, character, skip=False)` with `.key` (`anim.key`, or `<anim.key>/@trn/<trn>`); `SheetJob(job, sheet)` with `.key` (`<job key>/sNN`).
  - `load_characters_checked(args)`, `select_jobs(args, characters) -> [Job]` (anchors, other bases, variants), `layout(args, anim) -> (sheets, masks)`, `sheet_jobs(args, jobs) -> [SheetJob]`, `anchor_key(sj, characters)`.
  - Audit: `audit_dir(dst, key)`, `latest_attempt`, `read_record`, `current_review`, `sheet_status(dst, key, reviews) -> (status, attempt)`, `status_of(args, sj, reviews, characters) -> (status, attempt, anchor)` (adds `blocked` and `stale`), `corrections_for`, `fallback_for`.
  - `finish_sheet(canvas, sheet, anim, frames_rgba, guides, strength, background) -> ({frame index: RGBA}, SheetResult)`; `sheet_inputs(args, sj, background) -> (frames_rgba, guides, guide canvas)`; `render_sheet_job(args, workflow, sj, character, corrections, anchor) -> (attempt, SheetResult)`.
  - `fail`, `write_atomic`, `save_image_atomic`, `UsageError`, `vlm_preflight`, `free_comfy_models`, `comfy_preflight`, `memory_available_gb`, `write_nearest`, `cmd_batch`, `dry_run`, `build_parser`, `main`; constants `SEED`, `MAX_ATTEMPTS`, `DEFAULT_MATCH_STRENGTH`, `DEFAULT_CONCURRENCY`, `CAPTION_SCALE`, `CONTACT_COLUMNS`, `PREVIEW_BACKGROUND`, `PREVIEW_MS`.
  - Attempt record (`attempt-N.json`): `attempt, workflow, seed, packing, gutter, background, canvas, groups, cells, anchor ({key, sha256} or null), match, geometry, promoted, canvas_sha256, frames ({"<job key>/<png>": sha256}), seconds`. `attempt-N.png` is the raw render canvas (the anchor image for dependants); `attempt-N.tiles/` holds `sheet.guide.png` and `sheet.anchor.png`.
  - `testkit`: `CAPTION`, `write_characters(path, src, caption=CAPTION, skip=None)`, `run_cli(argv)`, `vlm_stub(...)`, `shift_right(image, pixels=4)`, `fake_render(transform=None)`, `comfy_stub(...)`.

- [ ] **Step 1: Give `testkit.py` its driver half**

Replace its import block (from `import json` to the blank line before `# The real corpus`) with:

```python
import contextlib
import io
import json
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from PIL import Image

import anim_recreate as a
import comfy_client
import source_tree
from characters_file import Character, save_characters, seed_characters

```

Append to the end of the file:

```python


# ---- the driver's side ------------------------------------------------------

CAPTION = "SUBJECT: a test figure\nCOLOURS: red and blue\nSHADOW: none"


def write_characters(path, src, caption=CAPTION, skip=None):
    """Write the seeded characters.yaml of the miniature source at `src`, every
    character captioned with `caption`; `skip` maps a character key to the
    animations it writes as a nearest 2x."""
    source = source_tree.load(src)
    seeded = seed_characters([(an.key, an.kind, len(an.frames)) for an in source.animations])
    skip = skip or {}
    save_characters(path, {key: Character(c.animations, c.anchor, caption,
                                          tuple(skip.get(key, ())))
                           for key, c in seeded.items()})


def run_cli(argv):
    """Run anim_recreate.main(argv), capturing stdout and stderr: (code, out, err)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = a.main(list(argv))
    return code, out.getvalue(), err.getvalue()


_UNSET = object()


@contextlib.contextmanager
def vlm_stub(*, serving=True, caption=None, review=None, free=_UNSET):
    """Patch the vLLM side of `caption` and `review`: anim_recreate.vlm_is_serving
    and, when given, a side_effect callable for anim_recreate.caption_character
    or review_sheet. Pass `free` (a side_effect, or None for a plain stub) to
    also patch comfy_client.free_models, which `review` calls.

    Yields the mocks: serving, and caption, review and freed when requested.
    """
    with contextlib.ExitStack() as stack:
        mocks = SimpleNamespace(
            serving=stack.enter_context(patch.object(a, "vlm_is_serving", return_value=serving)))
        if caption is not None:
            mocks.caption = stack.enter_context(
                patch.object(a, "caption_character", side_effect=caption))
        if review is not None:
            mocks.review = stack.enter_context(patch.object(a, "review_sheet", side_effect=review))
        if free is not _UNSET:
            mocks.freed = stack.enter_context(
                patch.object(comfy_client, "free_models", side_effect=free))
        yield mocks


def shift_right(image, pixels=4):
    """`image` moved `pixels` HD px to the right over grey: a render that slid
    2 native px."""
    out = Image.new("RGB", image.size, (128, 128, 128))
    out.paste(image, (pixels, 0))
    return out


def fake_render(transform=None):
    """A comfy_client.render_sheet stand-in that 'renders' a sheet by saving its
    guide canvas (through `transform`, when given) where ComfyUI would."""
    def render(workflow, **kw):
        with Image.open(kw["guide"]) as im:
            image = im.convert("RGB")
        if transform is not None:
            image = transform(image)
        folder = Path(kw["comfy_dir"]) / "output" / comfy_client.OUTPUT_PREFIX
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{kw['name']}_00001_.png"
        image.save(path)
        return path
    return render


@contextlib.contextmanager
def comfy_stub(*, up=True, mem=100.0, missing=(), nodes=(), comfy_dir=None, render=None,
               free=None, swept=0):
    """Patch the ComfyUI side of `batch`: comfy_client.is_up, free_models,
    missing_model_files, missing_nodes, sweep_outputs, anim_recreate's
    memory_available_gb and (when given) COMFY_DIR and comfy_client.render_sheet
    (`render`, a side_effect callable such as fake_render()).

    Yields the mocks: is_up, freed, missing_model_files, missing_nodes, sweep,
    memory_available_gb, and render when requested.
    """
    with contextlib.ExitStack() as stack:
        mocks = SimpleNamespace(
            is_up=stack.enter_context(patch.object(comfy_client, "is_up", return_value=up)),
            freed=stack.enter_context(patch.object(comfy_client, "free_models", side_effect=free)),
            missing_model_files=stack.enter_context(
                patch.object(comfy_client, "missing_model_files", return_value=list(missing))),
            missing_nodes=stack.enter_context(
                patch.object(comfy_client, "missing_nodes", return_value=list(nodes))),
            sweep=stack.enter_context(
                patch.object(comfy_client, "sweep_outputs", return_value=swept)),
            memory_available_gb=stack.enter_context(
                patch.object(a, "memory_available_gb", return_value=mem)))
        if comfy_dir is not None:
            stack.enter_context(patch.object(a, "COMFY_DIR", comfy_dir))
        if render is not None:
            mocks.render = stack.enter_context(
                patch.object(comfy_client, "render_sheet", side_effect=render))
        yield mocks
```

- [ ] **Step 2: Write the failing test `test_anim_recreate.py`**

```python
import json
import random
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

import anim_recreate as a
import comfy_client
import sheet_layout
import source_tree
import testkit
from characters_file import Character, load_characters, load_reviews, save_characters

ZN, ZW = "monsters/zombie/zombien.cl2", "monsters/zombie/zombiew.cl2"
GREY = f"@trn/{testkit.GREY_TRN}"
# Every sheet of the miniature source, in the order batch renders them: the
# anchors of the characters in key order, the other base animations, the variants.
ORDER = ["missiles/fireba1.cl2/s01", f"{ZN}/s01", f"{ZN}/s02", "missiles/fireba2.cl2/s01",
         f"{ZW}/s01", f"{ZW}/s02", f"{ZN}/{GREY}/s01", f"{ZN}/{GREY}/s02",
         f"{ZW}/{GREY}/s01", f"{ZW}/{GREY}/s02"]


def mark_corner(image):
    """A render that differs from the guide by one gutter pixel: a new canvas
    that still passes every check."""
    image.putpixel((0, 0), (0, 0, 0))
    return image


class DriverTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.src = testkit.make_source(self.root)
        self.dst = self.root / "dst"
        self.chars = self.root / "characters.yaml"
        self.reviews = self.root / "reviews.yaml"
        self.comfy = self.root / "comfy"
        testkit.write_characters(self.chars, self.src)

    def argv(self, command, *extra):
        return [command, "--src", str(self.src), "--dst", str(self.dst), "--characters-file",
                str(self.chars), "--reviews", str(self.reviews), *extra]

    def batch(self, *extra, render=None):
        with testkit.comfy_stub(comfy_dir=self.comfy,
                                render=render or testkit.fake_render()) as mocks:
            code, out, err = testkit.run_cli(self.argv("batch", *extra))
        return code, out, err, mocks

    def record(self, key, attempt):
        return json.loads((self.dst / ".quality" / key / f"attempt-{attempt}.json").read_text())


class BatchTests(DriverTest):
    def test_batch_renders_anchors_first_and_promotes_every_frame(self):
        code, out, err, mocks = self.batch()
        self.assertEqual(code, 0, err)
        names = [c.kwargs["name"] for c in mocks.render.call_args_list]
        self.assertEqual(names, [comfy_client.comfy_name(k) + "_a1-sheet" for k in ORDER])
        anchors = {k: (self.record(k, 1)["anchor"] or {}).get("key") for k in ORDER}
        self.assertEqual(anchors, {
            f"{ZN}/s01": None, f"{ZN}/s02": f"{ZN}/s01", "missiles/fireba1.cl2/s01": None,
            f"{ZW}/s01": f"{ZN}/s01", f"{ZW}/s02": f"{ZN}/s01",
            "missiles/fireba2.cl2/s01": "missiles/fireba1.cl2/s01",
            f"{ZN}/{GREY}/s01": f"{ZN}/s01", f"{ZN}/{GREY}/s02": f"{ZN}/s02",
            f"{ZW}/{GREY}/s01": f"{ZW}/s01", f"{ZW}/{GREY}/s02": f"{ZW}/s02"})
        calls = {c.kwargs["name"]: c.kwargs for c in mocks.render.call_args_list}
        self.assertIsNone(calls[f"{comfy_client.comfy_name(ZN)}+s01_a1-sheet"]["anchor"])
        self.assertTrue(str(calls[f"{comfy_client.comfy_name(ZN)}+s02_a1-sheet"]["anchor"])
                        .endswith("sheet.anchor.png"))
        prompt = mocks.render.call_args_list[6].kwargs["positive"]
        self.assertIn("colour variant", prompt)
        self.assertNotIn("red and blue", prompt, msg="a variant drops the caption's COLOURS")
        source = source_tree.load(self.src)
        for key in (ZN, ZW, f"{ZN}/{GREY}"):
            anim = source.animation(key.split("/@trn/")[0])
            for frame in anim.frames:
                with Image.open(self.dst / key / frame.png) as im:
                    self.assertEqual((im.size, im.mode), ((64, 48), "RGBA"))
        self.assertIn("done: promoted=10 rejected=0 failed=0 done=0 blocked=0", out)
        mocks.freed.assert_called_once()
        code, out, _, mocks = self.batch()
        self.assertEqual((code, mocks.render.call_count), (0, 0), msg="a second batch is a no-op")
        self.assertIn("done=10", out)

    def test_a_shifted_anchor_is_rejected_and_its_dependants_wait(self):
        code, out, _, mocks = self.batch("--character", "monsters/zombie",
                                         render=testkit.fake_render(testkit.shift_right))
        self.assertEqual(code, 0)
        self.assertEqual(mocks.render.call_count, 1)
        self.assertIn("rejected=1", out)
        self.assertIn("blocked=7", out)
        review = load_reviews(self.reviews)[f"{ZN}/s01"]
        self.assertEqual((review.attempt, review.source), (1, "geometry"))
        self.assertTrue(any("is shifted" in issue for issue in review.issues))
        code, out, _, mocks = self.batch("--character", "monsters/zombie")
        self.assertIn(a.GEOMETRY_CORRECTION, mocks.render.call_args_list[0].kwargs["positive"])
        self.assertIn("promoted=8", out)

    def test_stuck_sheets_get_the_fallback_once_then_report_stuck(self):
        shifted = testkit.fake_render(testkit.shift_right)
        args = ("--anim", "missiles/fireba1.cl2")
        for _ in range(a.MAX_ATTEMPTS):
            self.batch(*args, render=shifted)
        code, out, _, mocks = self.batch(*args, render=shifted)
        self.assertEqual(mocks.render.call_args.args[0].name, "qwen-image-2.1-i2i-faithful")
        code, out, err, mocks = self.batch(*args, render=shifted)
        self.assertEqual((code, mocks.render.call_count), (1, 0))
        self.assertIn("STUCK   missiles/fireba1.cl2/s01", err)

    def test_a_new_anchor_makes_its_dependants_stale(self):
        self.batch()
        code, out, _, mocks = self.batch("--anim", ZN, "--no-variants", "--force",
                                         render=testkit.fake_render(mark_corner))
        self.assertEqual(mocks.render.call_count, 2)
        code, out, _, mocks = self.batch()
        rendered = [c.kwargs["name"].split("_a")[0] for c in mocks.render.call_args_list]
        self.assertEqual(rendered, [comfy_client.comfy_name(k) for k in (
            f"{ZW}/s01", f"{ZW}/s02", f"{ZN}/{GREY}/s01", f"{ZN}/{GREY}/s02")])
        self.assertIn("(its anchor changed)", out)

    def test_a_failed_render_leaves_an_error_and_no_record(self):
        def boom(workflow, **kw):
            raise RuntimeError("ComfyUI execution failed: out of memory")
        audit = self.dst / ".quality" / "missiles/fireba1.cl2/s01"
        cases = {"a ComfyUI error": (boom, "out of memory"),
                 "a render of the wrong size": (
                     testkit.fake_render(lambda im: im.resize((64, 64))), "came back 64x64")}
        for attempt, (label, (render, message)) in enumerate(cases.items(), 1):
            with self.subTest(label):
                code, out, err, mocks = self.batch("--anim", "missiles/fireba1.cl2", render=render)
                self.assertEqual(code, 1)
                self.assertIn(message, (audit / f"attempt-{attempt}.error.txt").read_text())
                self.assertFalse((audit / f"attempt-{attempt}.json").exists())
                mocks.sweep.assert_called_once_with("missiles+fireba1.cl2+s01", self.comfy)
                self.assertEqual(a.sheet_status(self.dst, "missiles/fireba1.cl2/s01", {}),
                                 ("failed", attempt))

    def test_ctrl_c_sweeps_frees_and_stops(self):
        def ctrl_c(workflow, **kw):
            raise KeyboardInterrupt
        with testkit.comfy_stub(comfy_dir=self.comfy, render=ctrl_c) as mocks:
            with self.assertRaises(KeyboardInterrupt):
                testkit.run_cli(self.argv("batch"))
        self.assertEqual(mocks.render.call_count, 1)
        mocks.sweep.assert_called_once()
        mocks.freed.assert_called_once()
        error = self.dst / ".quality" / "missiles/fireba1.cl2/s01" / "attempt-1.error.txt"
        self.assertIn("KeyboardInterrupt", error.read_text())

    def test_batch_refuses_without_comfyui_its_models_or_memory(self):
        cases = {"ComfyUI down": (dict(up=False), "not answering"),
                 "a missing model file": (dict(missing=["models/vae/x"]), "missing model files"),
                 "too little memory": (dict(mem=10.0), "stop vLLM first")}
        for label, (stub, message) in cases.items():
            with self.subTest(label):
                with testkit.comfy_stub(comfy_dir=self.comfy, render=testkit.fake_render(),
                                        **stub) as mocks:
                    code, _, err = testkit.run_cli(self.argv("batch"))
                self.assertEqual((code, mocks.render.call_count), (2, 0))
                self.assertIn(message, err)

    def test_characters_yaml_must_match_the_manifest(self):
        characters = load_characters(self.chars)
        zombie, mage = characters["monsters/zombie"], "monsters/darkmage/dmagew.cl2"
        cases = {
            "an anchor without frames": ({**characters, "monsters/zombie": Character(
                zombie.animations + (mage,), mage, zombie.caption)}, "has no frames"),
            "an animation left out": ({k: c for k, c in characters.items()
                                       if k != "missiles/fireba"}, "no character for"),
        }
        for label, (edited, message) in cases.items():
            with self.subTest(label):
                if label == "an anchor without frames":
                    del edited["monsters/darkmage"]
                save_characters(self.chars, edited)
                code, _, err, mocks = self.batch()
                self.assertEqual((code, mocks.render.call_count), (2, 0))
                self.assertIn(message, err)

    def test_skipped_animations_are_copied_with_their_variants(self):
        testkit.write_characters(self.chars, self.src, skip={"monsters/zombie": [ZW]})
        code, out, _, mocks = self.batch("--character", "monsters/zombie")
        self.assertEqual(code, 0)
        self.assertEqual(mocks.render.call_count, 4, msg="zombien and its variant only")
        with Image.open(self.dst / ZW / GREY / "d1/f003.png") as im:
            alpha = np.asarray(im.getchannel("A"))
        self.assertEqual(set(np.unique(alpha)), {0, 255}, msg="a copy keeps the hard outline")

    def test_uncaptioned_characters_stop_the_batch_but_not_the_dry_run(self):
        testkit.write_characters(self.chars, self.src, caption="")
        code, _, err, mocks = self.batch()
        self.assertEqual((code, mocks.render.call_count), (2, 0))
        self.assertIn("no caption", err)
        code, out, _, mocks = self.batch("--dry-run")
        self.assertEqual((code, mocks.render.call_count), (0, 0))
        self.assertIn(f"blocked  {ZW}/s01", out)
        self.assertIn(f"new      {ZN}/s01  3 frames", out)
        self.assertIn("no caption - run: make caption", out)
        self.assertIn("sheets: blocked=8 new=2", out)


class SelectionTests(DriverTest):
    def test_character_anim_and_variant_select_the_sheets(self):
        cases = {("--character", "missiles/fireba"): "2 sheet(s)",
                 ("--anim", ZW): "4 sheet(s)",
                 ("--anim", ZW, "--no-variants"): "2 sheet(s)",
                 ("--variant", testkit.GREY_TRN): "10 sheet(s)"}
        for extra, expected in cases.items():
            with self.subTest(extra=extra):
                code, out, _, _ = self.batch("--dry-run", *extra)
                self.assertEqual(code, 0)
                self.assertIn(expected, out)
        for extra, message in ((("--variant", "x.trn"), "no selected animation has variant x.trn"),
                               (("--character", "nobody"), "no character nobody"),
                               (("--anim", "a.cl2"), "no selected character has animation a.cl2")):
            with self.subTest(extra=extra):
                code, _, err, _ = self.batch("--dry-run", *extra)
                self.assertEqual(code, 2)
                self.assertIn(message, err)


@testkit.needs_real_corpus
class RealCorpusTests(unittest.TestCase):
    """A perfect render (the guide canvas itself) of real animations passes every
    check: the gate never rejects a faithful sheet."""

    def test_perfect_renders_of_a_real_sample_pass(self):
        source = source_tree.load(testkit.REAL_SRC)
        sample = random.Random(7).sample([an for an in source.animations if an.frames], 50)
        background = sheet_layout.BACKGROUNDS[sheet_layout.BACKGROUND]
        args = type("Args", (), {"src": testkit.REAL_SRC})()
        failures = []
        for anim in sample:
            masks = [source_tree.frame_pixels(testkit.REAL_SRC, anim, f)[1] for f in anim.frames]
            sheets = sheet_layout.plan_sheets([(f.group, m) for f, m in zip(anim.frames, masks)])
            for sheet in sheets:
                sj = a.SheetJob(a.Job(anim, None, "x"), sheet)
                frames, guides, canvas = a.sheet_inputs(args, sj, background)
                _, result = a.finish_sheet(canvas, sheet, anim, frames, guides,
                                           a.DEFAULT_MATCH_STRENGTH, background)
                if not result.passed:
                    failures.append((sj.key, result.issues[:2]))
        self.assertEqual(failures, [])


if __name__ == "__main__":
    unittest.main()
```

Run: `.venv/bin/python -m unittest test_anim_recreate -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'anim_recreate'` (from `testkit`).

- [ ] **Step 3: Write `anim_recreate.py`**

```python
#!/usr/bin/env python3
"""Regenerate Diablo's animated sprites as painted high-definition art at
exactly 2x, frame by frame, with the outline locked.

Human-paced stages, each a subcommand:

  caption   seed characters.yaml when it is missing, then describe every
            character with the local vLLM and write its caption
  batch     render every sheet of every selected animation through ComfyUI:
            anchors first, then the other base animations, then the recolour
            variants; colour-match, slice and check each frame; promote a
            sheet's frames when all of them pass; re-render the sheets
            reviews.yaml rejects; write skipped animations as a nearest 2x
  review    compare every promoted sheet with its guide and its anchor
            through the vLLM and write reviews.yaml
  verify    audit the output tree against the manifest, the 2x rule, the
            outline and the attempt records
  preview   write an animated GIF per direction: source and render side by side

The source tree is diablo-textures-exporter's output; its manifest.json (read by
source_tree) decides which animations exist. Services are external: vLLM
(Qwen/Qwen3.8-27B on :8000) and ComfyUI (:8188) are started by the user; this
driver only checks that they answer.
"""
import argparse
import json
import os
import re
import shutil
import sys
import time
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
from PIL import Image

import colour_match
import comfy_client
import geometry_check
import sheet_layout
import source_tree
from characters_file import (CharactersFileError, Review, check_coverage, load_characters,
                             load_reviews, save_reviews)
from prompts import GEOMETRY_CORRECTION, PAINTED_NEGATIVE, render_prompt, vlm_is_serving
from source_tree import SourceError

REPO = Path(__file__).resolve().parent


def _env_path(name, default):
    return Path(os.environ.get(name) or default).expanduser()


SRC_ROOT = _env_path("DIA_SRC", REPO.parent / "diablo-textures-exporter" / "out")
DST_ROOT = _env_path("DIA_DST", REPO / "data" / "anims-ai")
PREVIEW_ROOT = _env_path("DIA_PREVIEW", REPO / "data" / "preview")
CHARACTERS_FILE = _env_path("DIA_CHARACTERS", REPO / "characters.yaml")
REVIEWS_FILE = _env_path("DIA_REVIEWS", REPO / "reviews.yaml")
COMFY_URL = os.environ.get("COMFY_URL", "http://127.0.0.1:8188").rstrip("/")
COMFY_DIR = _env_path("COMFY_DIR", Path.home() / "ComfyUI")
VLM_BASE_URL = os.environ.get("VLM_BASE_URL", "http://127.0.0.1:8000/v1")
VLM_MODEL = os.environ.get("VLM_MODEL", "Qwen/Qwen3.8-27B")
VLM_API_KEY = os.environ.get("VLM_API_KEY", "")
MEMORY_FLOOR_GB = 45
SEED = 42                   # attempt N of a sheet uses SEED + N - 1
MAX_ATTEMPTS = 4            # a sheet with this many judged attempts, the latest rejected, waits
DEFAULT_MATCH_STRENGTH = 0.5
DEFAULT_CONCURRENCY = 8     # review requests in flight at once
CAPTION_SCALE = 4           # the caption contact sheets enlarge frames this much
CONTACT_COLUMNS = 8
PREVIEW_BACKGROUND = (24, 24, 24)
PREVIEW_MS = 100            # GIF frame duration
SCALE = source_tree.SCALE
_ATTEMPT = re.compile(r"^attempt-(\d+)(\.|$)")


class UsageError(Exception):
    """Bad arguments or a precondition the user must fix; reported without a traceback."""


def fail(msg):
    print(f"error: {msg}", file=sys.stderr)
    return 2


def write_atomic(path, text):
    """Write `text` to `path` through <path>.tmp and a rename."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def save_image_atomic(image, path):
    """Save `image` as a PNG at `path` through <path>.pending and a rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_name(path.name + ".pending")
    image.save(pending, format="PNG")
    os.replace(pending, path)


# ---- jobs and sheets --------------------------------------------------------

@dataclass(frozen=True)
class Job:
    """One animation to regenerate: a base animation, or one recolour variant of it."""
    anim: source_tree.Animation
    trn: object             # the TRN asset path of a variant, or None
    character: str
    skip: bool = False

    @property
    def key(self):
        return self.anim.key if self.trn is None else f"{self.anim.key}/@trn/{self.trn}"


@dataclass(frozen=True)
class SheetJob:
    job: Job
    sheet: sheet_layout.Sheet

    @property
    def key(self):
        return f"{self.job.key}/{self.sheet.label}"


def load_characters_checked(args):
    """characters.yaml, checked to cover exactly the manifest's animations, with
    no anchor that lacks frames while its character has some."""
    characters = load_characters(args.characters_file)
    check_coverage(characters, [a.key for a in args.source.animations], args.characters_file)
    for key, character in characters.items():
        counts = {a: len(args.source.animation(a).frames) for a in character.animations}
        if not counts[character.anchor] and any(counts.values()):
            raise UsageError(f"{args.characters_file}: {key}'s anchor {character.anchor} has no "
                             "frames - choose an animation with frames")
    return characters


def select_jobs(args, characters):
    """The selected jobs in render order: every anchor animation, then the other
    base animations, then (unless --no-variants) the variants in the same order,
    only the --variant TRNs when given."""
    names = args.character or sorted(characters)
    unknown = sorted(set(names) - set(characters))
    if unknown:
        raise UsageError("no character " + ", ".join(unknown) + f" in {args.characters_file}")
    wanted = set(args.anim or ())
    known = {a for name in names for a in characters[name].animations}
    if wanted - known:
        raise UsageError("no selected character has animation "
                         + ", ".join(sorted(wanted - known)))
    anchors, others = [], []
    for name in names:
        character = characters[name]
        for key in character.animations:
            if wanted and key not in wanted:
                continue
            job = Job(args.source.animation(key), None, name, key in character.skip)
            (anchors if key == character.anchor else others).append(job)
    bases = anchors + others
    trns = {trn for job in bases for trn in job.anim.variants}
    if args.variant and set(args.variant) - trns:
        raise UsageError("no selected animation has variant "
                         + ", ".join(sorted(set(args.variant) - trns)))
    variants = [] if args.no_variants else [
        replace(job, trn=trn) for job in bases for trn in job.anim.variants
        if not args.variant or trn in args.variant]
    return bases + variants


def layout(args, anim):
    """(sheets, masks) of an animation under the run's packing and gutter, cached."""
    cached = args.layouts.get(anim.key)
    if cached is None:
        masks = [source_tree.frame_pixels(args.src, anim, frame)[1] for frame in anim.frames]
        sheets = sheet_layout.plan_sheets([(f.group, m) for f, m in zip(anim.frames, masks)],
                                          args.packing, args.gutter)
        cached = args.layouts[anim.key] = (sheets, masks)
    return cached


def sheet_jobs(args, jobs):
    return [SheetJob(job, sheet) for job in jobs if not job.skip for sheet in layout(args, job.anim)[0]]


def anchor_key(sj, characters):
    """The key of the sheet `sj` is painted against, or None: a variant's base
    sheet of the same number; else the character's anchor animation's first
    sheet, except for that sheet itself."""
    if sj.job.trn is not None:
        return f"{sj.job.anim.key}/{sj.sheet.label}"
    character = characters[sj.job.character]
    if sj.job.anim.key == character.anchor and sj.sheet.number == 1:
        return None
    return f"{character.anchor}/s01"


# ---- audit folder -----------------------------------------------------------

def audit_dir(dst_root, key):
    return dst_root / ".quality" / key


def latest_attempt(audit):
    """The highest N among the audit folder's attempt-N.* entries, 0 when none.
    A failed attempt leaves attempt-N.tiles/ behind and still uses up N."""
    if not audit.is_dir():
        return 0
    return max((int(m.group(1)) for p in audit.iterdir() if (m := _ATTEMPT.match(p.name))),
               default=0)


def read_record(audit, attempt):
    """attempt-N.json as a mapping, or None when it is missing or unreadable."""
    try:
        value = json.loads((audit / f"attempt-{attempt}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def current_review(reviews, key, latest):
    """reviews.yaml's verdict on the sheet, or None when there is none or it is
    stale: an attempt later than the audit folder's latest."""
    review = reviews.get(key)
    return None if review is None or review.attempt > latest else review


def sheet_status(dst, key, reviews):
    """(status, latest attempt) of a sheet, from its audit folder alone:
    new       never attempted
    stuck     its latest judged attempt was rejected, and it has MAX_ATTEMPTS or
              more judged attempts
    failed    the latest attempt never finished (it has no record)
    rejected  the latest attempt failed the gate, or its review rejected it
    missing   promoted and not rejected, but a frame it wrote is gone
    done      promoted and not rejected (reviewed, or waiting for review)
    A failed attempt has no record and never counts toward STUCK."""
    audit = audit_dir(dst, key)
    attempt = latest_attempt(audit)
    if attempt == 0:
        return "new", 0
    review = current_review(reviews, key, attempt)
    records = {n: r for n in range(1, attempt + 1) if (r := read_record(audit, n)) is not None}

    def rejected(n):
        return not records[n].get("promoted") or (review is not None and not review.accepted
                                                  and review.attempt >= n)

    if records and rejected(max(records)) and len(records) >= MAX_ATTEMPTS:
        return "stuck", attempt
    if attempt not in records:
        return "failed", attempt
    if rejected(attempt):
        return "rejected", attempt
    if any(not (dst / rel).is_file() for rel in records[attempt].get("frames", {})):
        return "missing", attempt
    return "done", attempt


def status_of(args, sj, reviews, characters):
    """(status, attempt, anchor) of a sheet, with the anchor rules on top of
    sheet_status. `anchor` is (key, canvas path, canvas sha256) of the anchor
    sheet's promoted attempt, or None when the sheet has no anchor or it is not
    done. A sheet that still needs rendering waits as `blocked` while its
    anchor is not done; a done sheet painted against another anchor canvas than
    the current one is `stale`."""
    status, attempt = sheet_status(args.dst, sj.key, reviews)
    key = None if args.no_anchor else anchor_key(sj, characters)
    if key is None:
        return status, attempt, None
    a_status, a_attempt = sheet_status(args.dst, key, reviews)
    anchor = None
    if a_status == "done":
        record = read_record(audit_dir(args.dst, key), a_attempt)
        anchor = (key, audit_dir(args.dst, key) / f"attempt-{a_attempt}.png",
                  record.get("canvas_sha256"))
    elif status != "done":
        return "blocked", attempt, None
    if status == "done" and anchor is not None:
        record = read_record(audit_dir(args.dst, sj.key), attempt)
        if (record.get("anchor") or {}).get("sha256") != anchor[2]:
            return "stale", attempt, anchor
    return status, attempt, anchor


def corrections_for(dst, key, reviews):
    """What the sheet's next attempt must correct: the issues of its current
    review when that review rejected an attempt and no later attempt was
    promoted. After a geometry rejection it is the one GEOMETRY_CORRECTION
    sentence: the gate's own strings mean nothing to the diffusion model."""
    audit = audit_dir(dst, key)
    latest = latest_attempt(audit)
    review = current_review(reviews, key, latest)
    if review is None or review.accepted:
        return []
    if any((read_record(audit, n) or {}).get("promoted")
           for n in range(review.attempt + 1, latest + 1)):
        return []
    return [GEOMETRY_CORRECTION] if review.source == "geometry" else list(review.issues)


def fallback_for(dst, key, workflow):
    """The workflow to render a stuck sheet through once more: `workflow`'s
    fallback while no judged attempt of the sheet has used it; else None."""
    if workflow.fallback is None:
        return None
    audit = audit_dir(dst, key)
    used = {record.get("workflow") for n in range(1, latest_attempt(audit) + 1)
            if (record := read_record(audit, n)) is not None}
    return None if workflow.fallback in used else comfy_client.WORKFLOWS[workflow.fallback]


# ---- render one sheet -------------------------------------------------------

def finish_sheet(canvas, sheet, anim, frames_rgba, guides, strength, background):
    """Cut the rendered `canvas` into its frames, colour-match each toward its
    guide over its outline, lock the outline, and check them all.
    Returns ({frame index: RGBA image at SCALE}, SheetResult)."""
    items, outputs = [], {}
    for cell in sheet.cells:
        frame = anim.frames[cell.frame]
        size = (frame.w, frame.h)
        mask = np.asarray(frames_rgba[cell.frame])[..., 3] > 0
        raw = sheet_layout.frame_rgb(canvas, cell, size, background)
        matched = colour_match.match(raw, guides[cell.frame], strength,
                                     mask=sheet_layout.hard_alpha(mask) > 0)
        items.append((frame.png, frame.group, matched.resize(size, Image.Resampling.BOX),
                      sheet_layout.guide_native(frames_rgba[cell.frame], background), mask))
        outputs[cell.frame] = sheet_layout.finish_frame(matched, mask)
    result = geometry_check.check_sheet(items, canvas, sheet_layout.gutter_mask(sheet), background)
    return outputs, result


def sheet_inputs(args, sj, background):
    """(frames_rgba, guides, guide canvas) of a sheet: each cell's native RGBA
    frame (through the job's TRN) and its guide at SCALE, keyed by frame index."""
    anim = sj.job.anim
    frames = {c.frame: source_tree.frame_rgba(args.src, anim, anim.frames[c.frame], sj.job.trn)
              for c in sj.sheet.cells}
    guides = {i: sheet_layout.guide_frame(f, background) for i, f in frames.items()}
    return frames, guides, sheet_layout.guide_canvas(sj.sheet, guides, background)


def render_sheet_job(args, workflow, sj, character, corrections, anchor):
    """Render one sheet, finish and check its frames, and promote them when
    every frame passes. Returns (attempt, SheetResult).

    Raises when the render fails or comes back the wrong size: the attempt
    number stays used, attempt-N.error.txt says what failed, and no
    attempt-N.json is written, so the attempt reads as failed.
    """
    audit = audit_dir(args.dst, sj.key)
    audit.mkdir(parents=True, exist_ok=True)
    attempt = latest_attempt(audit) + 1
    tiles = audit / f"attempt-{attempt}.tiles"
    tiles.mkdir()
    seed = SEED + attempt - 1
    started = time.monotonic()
    stage = None
    background = sheet_layout.BACKGROUNDS[args.background]
    try:
        anim = sj.job.anim
        frames_rgba, guides, canvas = sheet_inputs(args, sj, background)
        guide_path = tiles / "sheet.guide.png"
        canvas.save(guide_path)
        anchor_path = None
        if anchor is not None:
            anchor_path = tiles / "sheet.anchor.png"
            shutil.copyfile(anchor[1], anchor_path)
        positive = render_prompt(
            character.caption, len(sj.sheet.cells), reference=workflow.reference,
            anchor_reference=workflow.anchor_reference if anchor is not None else None,
            variant=sj.job.trn is not None, corrections=corrections)
        stage = "sheet"
        saved = comfy_client.render_sheet(
            workflow, guide=guide_path, anchor=anchor_path, positive=positive,
            negative=PAINTED_NEGATIVE, seed=seed,
            # The attempt in the name keeps ComfyUI's cache from answering a rerun of
            # the same inputs and seed with an old render.
            name=f"{comfy_client.comfy_name(sj.key)}_a{attempt}-sheet", url=COMFY_URL,
            comfy_dir=COMFY_DIR)
        raw = audit / f"attempt-{attempt}.png"
        shutil.move(saved, raw)
        with Image.open(raw) as im:
            rendered = im.convert("RGB")
        if rendered.size != sj.sheet.size:
            raise RuntimeError(f"the sheet came back {rendered.width}x{rendered.height}, "
                               f"expected {sj.sheet.size[0]}x{sj.sheet.size[1]}")
        stage = None
        write_atomic(audit / f"attempt-{attempt}.prompt.txt",
                     f"workflow: {workflow.name}\n\n{positive}\n\n--- negative ---\n"
                     f"{PAINTED_NEGATIVE}\n")
        outputs, result = finish_sheet(rendered, sj.sheet, anim, frames_rgba, guides,
                                       args.match_strength, background)
        if result.bleed > geometry_check.GUTTER_WARN:
            print(f"  warning: {sj.key} painted into its gutters ({result.bleed:.1f} levels from "
                  "the background)", flush=True)
        frames = {}
        if result.passed:
            for index, image in outputs.items():
                rel = f"{sj.job.key}/{anim.frames[index].png}"
                save_image_atomic(image, args.dst / rel)
                frames[rel] = source_tree.file_sha256(args.dst / rel)
        record = {
            "attempt": attempt, "workflow": workflow.name, "seed": seed,
            "packing": args.packing, "gutter": args.gutter, "background": args.background,
            "canvas": list(sj.sheet.size), "groups": list(sj.sheet.groups),
            "cells": len(sj.sheet.cells),
            "anchor": None if anchor is None else {"key": anchor[0], "sha256": anchor[2]},
            "match": {"rule": colour_match.RULE, "strength": args.match_strength},
            "geometry": result.as_dict(), "promoted": result.passed,
            "canvas_sha256": source_tree.file_sha256(raw), "frames": frames,
            "seconds": round(time.monotonic() - started, 1),
        }
        write_atomic(audit / f"attempt-{attempt}.json", json.dumps(record, indent=2))
        return attempt, result
    except BaseException as error:
        write_atomic(audit / f"attempt-{attempt}.error.txt",
                     f"workflow: {workflow.name}\nseed: {seed}\nstage: {stage or 'none'}\n"
                     f"seconds: {time.monotonic() - started:.1f}\n"
                     f"error: {type(error).__name__}: {error}\n")
        raise


# ---- batch ------------------------------------------------------------------

def memory_available_gb(meminfo=Path("/proc/meminfo")):
    """MemAvailable in GiB. On this unified-memory host it is the GPU budget too."""
    for line in meminfo.read_text().splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) / 2 ** 20
    raise RuntimeError(f"MemAvailable not found in {meminfo}")


def vlm_preflight():
    """None when vLLM serves VLM_MODEL; else fail(...)'s exit code."""
    if not vlm_is_serving(VLM_BASE_URL, VLM_MODEL, comfy_client.http_json, VLM_API_KEY):
        return fail(f"vLLM is not serving {VLM_MODEL} at {VLM_BASE_URL} - start it first")
    return None


def free_comfy_models():
    """Ask ComfyUI to unload its models; a warning, never an error, when it cannot."""
    try:
        comfy_client.free_models(COMFY_URL)
    except Exception as error:
        print(f"warning: failed to free ComfyUI's models: {error}", file=sys.stderr)


def comfy_preflight(workflow, no_memory_check):
    """None when ComfyUI answers, has the model files, knows the node classes
    and there is memory to render; else fail(...)'s exit code."""
    if not comfy_client.is_up(COMFY_URL):
        return fail(f"ComfyUI is not answering at {COMFY_URL} - start it first (make server)")
    missing = comfy_client.missing_model_files(workflow, COMFY_DIR)
    if missing:
        return fail(f"ComfyUI is missing model files under {COMFY_DIR}:\n  " + "\n  ".join(missing))
    unknown = comfy_client.missing_nodes(workflow, COMFY_URL)
    if unknown:
        return fail(f"ComfyUI at {COMFY_URL} does not know {', '.join(unknown)} - update the "
                    f"checkout (git -C {COMFY_DIR} pull) and restart it")
    if not no_memory_check:
        available = memory_available_gb()
        if available < MEMORY_FLOOR_GB:
            return fail(f"only {available:.0f} GB of memory available, a render needs about "
                        f"{MEMORY_FLOOR_GB} GB: stop vLLM first (or pass --no-memory-check)")
    return None


def write_nearest(args, job):
    """A skipped animation's output: every frame at SCALE, nearest-neighbour."""
    for frame in job.anim.frames:
        save_image_atomic(sheet_layout.nearest_frame(
            source_tree.frame_rgba(args.src, job.anim, frame, job.trn)),
            args.dst / job.key / frame.png)


def stuck_line(sj):
    return (f"  STUCK   {sj.key}: rejected {MAX_ATTEMPTS} times - fix {sj.job.character}'s "
            f"caption in characters.yaml, then: make batch anim={sj.job.anim.key} force=1")


def cmd_batch(args):
    workflow = comfy_client.WORKFLOWS[args.workflow]
    characters = load_characters_checked(args)
    reviews = load_reviews(args.reviews, optional=True)
    jobs = select_jobs(args, characters)
    copies = [job for job in jobs if job.skip and (args.force or any(
        not (args.dst / job.key / f.png).is_file() for f in job.anim.frames))]
    items = sheet_jobs(args, jobs)
    uncaptioned = sorted({sj.job.character for sj in items
                          if not characters[sj.job.character].caption.strip()})
    print(f"workflow: {workflow.name}  match strength: {args.match_strength}  packing: "
          f"{args.packing}  gutter: {args.gutter}  background: {args.background}"
          + ("  no anchor" if args.no_anchor else ""))
    print(f"{len(jobs)} animation(s) and variant(s): {len(items)} sheet(s), "
          f"copy {len(copies)} (skip)")
    if args.dry_run:
        return dry_run(args, items, copies, characters, reviews, uncaptioned)
    if uncaptioned:
        return fail(f"{len(uncaptioned)} selected character(s) have no caption in "
                    f"{args.characters_file} - run: make caption\n  " + "\n  ".join(uncaptioned))
    for job in copies:
        write_nearest(args, job)
        print(f"  copy    {job.key} (nearest {SCALE}x)")
    if not items:
        return 0
    code = comfy_preflight(workflow, args.no_memory_check)
    if code is not None:
        return code
    # ComfyUI keeps its models loaded after rendering (~40 GB); free them on the
    # way out, even after a failure, so vLLM has room to start for `make review`.
    try:
        counts = dict.fromkeys(("promoted", "rejected", "failed", "done", "blocked"), 0)
        stuck = []
        for i, sj in enumerate(items, 1):
            status, _, anchor = status_of(args, sj, reviews, characters)
            if status == "done" and not args.force:
                counts["done"] += 1
                continue
            if status == "blocked":
                counts["blocked"] += 1
                continue
            sheet_workflow = workflow
            if status == "stuck" and not args.force:
                sheet_workflow = fallback_for(args.dst, sj.key, workflow)
                if sheet_workflow is None:
                    stuck.append(sj)
                    continue
            corrections = corrections_for(args.dst, sj.key, reviews)
            note = f" with {len(corrections)} correction(s)" if corrections else ""
            if sheet_workflow is not workflow:
                note += f" through the fallback {sheet_workflow.name}"
            if status == "stale":
                note += " (its anchor changed)"
            print(f"[{i}/{len(items)}] render {sj.key} ({len(sj.sheet.cells)} frames){note}",
                  flush=True)
            try:
                attempt, result = render_sheet_job(args, sheet_workflow, sj,
                                                   characters[sj.job.character], corrections,
                                                   anchor)
            except KeyboardInterrupt:
                comfy_client.sweep_outputs(comfy_client.comfy_name(sj.key), COMFY_DIR)
                raise
            except Exception as error:
                counts["failed"] += 1
                swept = comfy_client.sweep_outputs(comfy_client.comfy_name(sj.key), COMFY_DIR)
                extra = f" (removed {swept} stray output file(s))" if swept else ""
                print(f"  ERROR rendering {sj.key}: {error}{extra}", file=sys.stderr, flush=True)
                continue
            if result.passed:
                counts["promoted"] += 1
                print(f"  promoted attempt {attempt}", flush=True)
                continue
            counts["rejected"] += 1
            reviews[sj.key] = Review(attempt, False, result.issues, "geometry")
            save_reviews(args.reviews, reviews)
            print(f"  rejected attempt {attempt}: " + "; ".join(result.issues[:3])
                  + (f" (+{len(result.issues) - 3} more)" if len(result.issues) > 3 else ""),
                  flush=True)
            if sheet_status(args.dst, sj.key, reviews)[0] == "stuck":
                fallback = fallback_for(args.dst, sj.key, sheet_workflow)
                if fallback is None:
                    stuck.append(sj)
                else:
                    print(f"  next batch renders it through the fallback {fallback.name}",
                          flush=True)
        for sj in stuck:
            print(stuck_line(sj), file=sys.stderr)
        print("done: " + " ".join(f"{k}={v}" for k, v in counts.items())
              + f" copied={len(copies)} stuck={len(stuck)}")
        return 1 if counts["failed"] or stuck else 0
    finally:
        free_comfy_models()


def dry_run(args, items, copies, characters, reviews, uncaptioned):
    """Print what batch would do: every sheet not done, with its size, anchor
    and corrections, then the counts by status."""
    counts = {}
    for job in copies:
        print(f"  copy    {job.key} ({len(job.anim.frames)} frames, nearest {SCALE}x)")
    for sj in items:
        status, _, _ = status_of(args, sj, reviews, characters)
        counts[status] = counts.get(status, 0) + 1
        if status == "done":
            continue
        w, h = sj.sheet.size
        extras = [f"{len(sj.sheet.cells)} frames", f"{w}x{h}"]
        key = None if args.no_anchor else anchor_key(sj, characters)
        if key:
            extras.append(f"anchor {key}")
        corrections = corrections_for(args.dst, sj.key, reviews)
        if corrections:
            extras.append(f"{len(corrections)} correction(s)")
        if sj.job.character in uncaptioned:
            extras.append("no caption - run: make caption")
        print(f"  {status:8} {sj.key}  " + "; ".join(extras))
    largest = max((sj.sheet for sj in items), key=lambda s: s.size[0] * s.size[1], default=None)
    if largest is not None:
        print(f"largest canvas: {largest.size[0]}x{largest.size[1]}")
    print("sheets: " + " ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    return 0


# ---- command line -----------------------------------------------------------

def default_workflow(environ=os.environ):
    """--workflow when the flag is absent: DIA_WORKFLOW or comfy_client.DEFAULT_WORKFLOW."""
    name = environ.get("DIA_WORKFLOW") or comfy_client.DEFAULT_WORKFLOW
    if name not in comfy_client.WORKFLOWS:
        raise UsageError(f"DIA_WORKFLOW={name!r} is not a workflow; choose one of "
                         + ", ".join(sorted(comfy_client.WORKFLOWS)))
    return name


def match_strength(text):
    """argparse type for --match-strength: a number from 0 to 1."""
    try:
        value = float(text)
    except ValueError:
        value = -1.0
    if not 0 <= value <= 1:
        raise argparse.ArgumentTypeError(f"{text} is not a number from 0 to 1")
    return value


def default_match_strength(environ=os.environ):
    """--match-strength when the flag is absent: DIA_MATCH_STRENGTH or DEFAULT_MATCH_STRENGTH."""
    text = environ.get("DIA_MATCH_STRENGTH")
    if not text:
        return DEFAULT_MATCH_STRENGTH
    try:
        return match_strength(text)
    except argparse.ArgumentTypeError as error:
        raise UsageError(f"DIA_MATCH_STRENGTH: {error}") from error


def positive_int(text):
    try:
        value = int(text)
    except ValueError:
        value = 0
    if value < 1:
        raise argparse.ArgumentTypeError(f"{text} is not a whole number of 1 or more")
    return value


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    def common(p):
        p.add_argument("--src", type=Path, default=SRC_ROOT,
                       help="diablo-textures-exporter output (default: %(default)s, or DIA_SRC)")
        p.add_argument("--dst", type=Path, default=DST_ROOT,
                       help="output tree (default: %(default)s, or DIA_DST)")
        p.add_argument("--characters-file", type=Path, default=CHARACTERS_FILE,
                       help="characters file (default: %(default)s, or DIA_CHARACTERS)")
        p.add_argument("--reviews", type=Path, default=REVIEWS_FILE,
                       help="reviews file (default: %(default)s, or DIA_REVIEWS)")
        p.add_argument("--character", action="append", metavar="KEY",
                       help="process character KEY only (repeatable)")
        p.add_argument("--anim", action="append", metavar="KEY",
                       help="process animation KEY (its record directory) only (repeatable)")
        p.add_argument("--no-variants", action="store_true",
                       help="leave out the recolour variants")
        p.add_argument("--variant", action="append", metavar="TRN",
                       help="of the variants, process TRN (e.g. monsters/zombie/grey.trn) only "
                            "(repeatable)")
        p.add_argument("--packing", choices=sheet_layout.PACKINGS,
                       default=sheet_layout.SHEET_PACKING,
                       help="one direction per sheet, or several (default: %(default)s)")
        p.add_argument("--gutter", type=positive_int, default=sheet_layout.GUTTER, metavar="PX",
                       help="HD px between cells (default: %(default)s)")
        p.add_argument("--background", choices=sorted(sheet_layout.BACKGROUNDS),
                       default=sheet_layout.BACKGROUND,
                       help="the flat colour behind the figures (default: %(default)s)")
        p.add_argument("--no-anchor", action="store_true",
                       help="paint every sheet against its guide only (a spike variant)")

    batch = sub.add_parser("batch", help="render sheets through ComfyUI")
    common(batch)
    batch.add_argument("--dry-run", action="store_true",
                       help="print the plan without contacting ComfyUI or writing files")
    batch.add_argument("--no-memory-check", action="store_true",
                       help=f"skip the {MEMORY_FLOOR_GB} GB available-memory guard")
    batch.add_argument("--force", action="store_true",
                       help="render the selection again, even when done or stuck")
    batch.add_argument("--match-strength", type=match_strength, default=default_match_strength(),
                       metavar="X", help="how far each frame moves toward its source's colours, "
                                         "0 to 1 (default: %(default)s, or DIA_MATCH_STRENGTH)")
    batch.add_argument("--workflow", choices=sorted(comfy_client.WORKFLOWS),
                       default=default_workflow(), metavar="NAME",
                       help="render workflow: " + ", ".join(sorted(comfy_client.WORKFLOWS))
                            + " (default: %(default)s, or DIA_WORKFLOW)")
    batch.set_defaults(func=cmd_batch)

    return ap


def main(argv=None):
    try:
        args = build_parser().parse_args(argv)
        if not args.src.is_dir():
            return fail(f"source is not a directory: {args.src} - set DIA_SRC or pass --src")
        args.source = source_tree.load(args.src)
        args.layouts = {}
        return args.func(args)
    except (UsageError, CharactersFileError, SourceError) as error:
        return fail(str(error))


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the whole suite**

Run: `make check && make test`
Expected: PASS. With the real export, `test_anim_recreate.RealCorpusTests` (a perfect render of 50 sampled animations passes every check) takes about a minute.

- [ ] **Step 5: Smoke-test a dry run on the real export**

```bash
cd ~/code/diablo-hd-bundle/diablo-texture-enhancement
.venv/bin/python -c "
import anim_recreate as a, source_tree, characters_file as cf
s = source_tree.load(a.SRC_ROOT)
c = cf.seed_characters([(x.key, x.kind, len(x.frames)) for x in s.animations])
cf.save_characters('/tmp/dia-chars.yaml', {k: cf.Character(v.animations, v.anchor, 'SUBJECT: x') for k, v in c.items()})"
./run_batch.sh batch --dry-run --characters-file /tmp/dia-chars.yaml --dst /tmp/dia-dst --character monsters/zombie | tail -3
rm /tmp/dia-chars.yaml
```

Expected: `largest canvas: 1056x768` and `sheets: blocked=383 new=1` (the zombie's anchor sheet is the only one not waiting on another).

- [ ] **Step 6: Commit**

```bash
git add diablo-texture-enhancement/anim_recreate.py diablo-texture-enhancement/test_anim_recreate.py diablo-texture-enhancement/testkit.py
git commit -m "feat(kit): batch renders sheets in anchor order and promotes checked frames

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: `caption` and `review`

**Files:**
- Modify: `diablo-texture-enhancement/anim_recreate.py`, `test_anim_recreate.py`

**Interfaces:**
- Consumes: Task 9's driver.
- Produces: `contact_sheet(frames, columns=CONTACT_COLUMNS, scale=CAPTION_SCALE, background=PREVIEW_BACKGROUND)`, `caption_images(args, character)`, `cmd_caption(args)` (seeds `characters.yaml` when missing; skips captioned characters unless `--force`, and characters with no frames at all); `judge(args, sj, attempt)`, `cmd_review(args)` (only `done` sheets; `--concurrency` requests at once; `reviews.yaml` written from the main thread after each verdict).

- [ ] **Step 1: Write the failing tests**

In `test_anim_recreate.py`, insert before `@testkit.needs_real_corpus`:

```python
class CaptionReviewTests(DriverTest):
    def test_caption_seeds_the_file_and_fills_blank_captions(self):
        self.chars.unlink()
        with testkit.vlm_stub(caption=lambda images, *rest: "SUBJECT: seen") as mocks:
            code, out, _ = testkit.run_cli(self.argv("caption"))
        self.assertEqual(code, 0)
        self.assertIn("seeded 3 character(s)", out)
        characters = load_characters(self.chars)
        self.assertEqual({k: c.caption for k, c in characters.items()},
                         {"missiles/fireba": "SUBJECT: seen", "monsters/darkmage": "",
                          "monsters/zombie": "SUBJECT: seen"},
                         msg="a character with no frames is not captioned")
        images = mocks.caption.call_args_list[-1].args[0]
        self.assertEqual(len(images), 2, msg="the anchor's directions, then the other animations")

    def test_review_judges_done_sheets_and_a_rejection_comes_back_as_corrections(self):
        self.batch("--character", "missiles/fireba")

        def review(guide, render, anchor, count, *rest):
            return ({"accepted": False, "issues": ["cell 2 grew a tail"]} if anchor is not None
                    else {"accepted": True, "issues": []})
        with testkit.vlm_stub(review=review, free=None):
            code, out, _ = testkit.run_cli(self.argv("review", "--concurrency", "2"))
        self.assertEqual(code, 0)
        self.assertIn("accepted=1 rejected=1", out)
        code, out, _, mocks = self.batch("--character", "missiles/fireba")
        self.assertEqual(mocks.render.call_count, 1)
        self.assertIn("cell 2 grew a tail", mocks.render.call_args.kwargs["positive"])


```

Run: `.venv/bin/python -m unittest test_anim_recreate.CaptionReviewTests -v`
Expected: FAIL (`invalid choice: 'caption'` / `'review'`, exit 2).

- [ ] **Step 2: Implement**

In `anim_recreate.py`, add `from concurrent.futures import ThreadPoolExecutor, as_completed` after `import time`, and make the two project imports:

```python
from characters_file import (CharactersFileError, Review, check_coverage, load_characters,
                             load_reviews, save_characters, save_reviews, seed_characters)
from prompts import (GEOMETRY_CORRECTION, PAINTED_NEGATIVE, caption_character, render_prompt,
                     review_sheet, vlm_is_serving)
```

Insert before `# ---- command line`:

```python
# ---- caption ----------------------------------------------------------------

def contact_sheet(frames, columns=CONTACT_COLUMNS, scale=CAPTION_SCALE,
                  background=PREVIEW_BACKGROUND):
    """Native RGBA `frames` enlarged `scale` times, nearest-neighbour, on a grid
    of up to `columns` over `background`, 8 px apart."""
    cw = max(f.width for f in frames) * scale
    ch = max(f.height for f in frames) * scale
    cols = min(columns, len(frames))
    rows = -(-len(frames) // cols)
    out = Image.new("RGB", (cols * (cw + 8) + 8, rows * (ch + 8) + 8), background)
    for k, frame in enumerate(frames):
        big = frame.convert("RGBA").resize((frame.width * scale, frame.height * scale),
                                           Image.Resampling.NEAREST)
        out.paste(big, (8 + (k % cols) * (cw + 8), 8 + (k // cols) * (ch + 8)), big)
    return out


def caption_images(args, character):
    """What the VLM sees: the anchor animation's first frame in each direction,
    then the first frame of every other animation with frames."""
    anchor = args.source.animation(character.anchor)
    firsts = [f for f in anchor.frames if f.i == 0]
    images = [contact_sheet([source_tree.frame_rgba(args.src, anchor, f) for f in firsts])]
    others = [args.source.animation(k) for k in character.animations if k != character.anchor]
    others = [a for a in others if a.frames]
    if others:
        images.append(contact_sheet([source_tree.frame_rgba(args.src, a, a.frames[0])
                                     for a in others]))
    return images


def cmd_caption(args):
    if not args.characters_file.exists():
        seeded = seed_characters([(a.key, a.kind, len(a.frames)) for a in args.source.animations])
        save_characters(args.characters_file, seeded)
        print(f"seeded {len(seeded)} character(s) -> {args.characters_file}")
    characters = load_characters_checked(args)
    names = args.character or sorted(characters)
    unknown = sorted(set(names) - set(characters))
    if unknown:
        raise UsageError("no character " + ", ".join(unknown) + f" in {args.characters_file}")
    code = vlm_preflight()
    if code is not None:
        return code
    done = skipped = failed = 0
    for i, name in enumerate(names, 1):
        character = characters[name]
        if (character.caption.strip() and not args.force) or not any(
                args.source.animation(k).frames for k in character.animations):
            skipped += 1
            continue
        print(f"[{i}/{len(names)}] caption {name}", flush=True)
        try:
            caption = caption_character(caption_images(args, character), comfy_client.http_json,
                                        VLM_BASE_URL, VLM_MODEL, VLM_API_KEY)
        except Exception as error:
            failed += 1
            print(f"  ERROR captioning {name}: {error}", file=sys.stderr, flush=True)
            continue
        characters[name] = replace(character, caption=caption)
        save_characters(args.characters_file, characters)
        done += 1
    print(f"done: captioned={done} skipped={skipped} failed={failed} -> {args.characters_file}")
    return 1 if failed else 0


# ---- review -----------------------------------------------------------------

def judge(args, sj, attempt):
    """The VLM's verdict on one promoted attempt of a sheet."""
    audit = audit_dir(args.dst, sj.key)
    tiles = audit / f"attempt-{attempt}.tiles"
    with Image.open(tiles / "sheet.guide.png") as g, Image.open(audit / f"attempt-{attempt}.png") as r:
        guide, render = g.convert("RGB"), r.convert("RGB")
    anchor = None
    if (tiles / "sheet.anchor.png").is_file():
        with Image.open(tiles / "sheet.anchor.png") as a:
            anchor = a.convert("RGB")
    return review_sheet(guide, render, anchor, len(sj.sheet.cells), comfy_client.http_json,
                        VLM_BASE_URL, VLM_MODEL, VLM_API_KEY)


def cmd_review(args):
    characters = load_characters_checked(args)
    items = sheet_jobs(args, select_jobs(args, characters))
    code = vlm_preflight()
    if code is not None:
        return code
    free_comfy_models()     # give the VLM room; ComfyUI may be down
    reviews = load_reviews(args.reviews, optional=True)
    todo, skipped = [], 0
    for sj in items:
        status, attempt, _ = status_of(args, sj, reviews, characters)
        review = current_review(reviews, sj.key, attempt)
        # Only a done sheet (promoted, not stale) is judged: a gate rejection already has
        # its verdict, and a failed attempt has nothing to show.
        if status != "done" or (review is not None and review.attempt >= attempt
                                and not args.force):
            skipped += 1
            continue
        todo.append((sj, attempt))
    accepted = rejected = failed = 0
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = {pool.submit(judge, args, sj, attempt): (sj, attempt) for sj, attempt in todo}
        for n, future in enumerate(as_completed(futures), 1):
            sj, attempt = futures[future]
            audit = audit_dir(args.dst, sj.key)
            try:
                verdict = future.result()
            except Exception as error:
                failed += 1
                write_atomic(audit / f"attempt-{attempt}.review-error.txt", str(error))
                print(f"[{n}/{len(todo)}] ERROR reviewing {sj.key}: {error}", file=sys.stderr,
                      flush=True)
                continue
            write_atomic(audit / f"attempt-{attempt}.review.json", json.dumps(verdict, indent=2))
            reviews[sj.key] = Review(attempt, verdict["accepted"], tuple(verdict["issues"]),
                                     "review")
            save_reviews(args.reviews, reviews)
            if verdict["accepted"]:
                accepted += 1
                print(f"[{n}/{len(todo)}] {sj.key}: accepted", flush=True)
            else:
                rejected += 1
                print(f"[{n}/{len(todo)}] {sj.key}: rejected: " + "; ".join(verdict["issues"]),
                      flush=True)
    print(f"done: accepted={accepted} rejected={rejected} skipped={skipped} failed={failed} "
          f"-> {args.reviews}")
    return 1 if failed else 0


```

In `build_parser`, insert before `    batch = sub.add_parser(`:

```python
    caption = sub.add_parser("caption", help="seed characters.yaml and caption its characters")
    common(caption)
    caption.add_argument("--force", action="store_true",
                         help="re-caption characters that already have a caption")
    caption.set_defaults(func=cmd_caption)

```

and before `    return ap`:

```python
    review = sub.add_parser("review", help="judge promoted sheets through the local vLLM")
    common(review)
    review.add_argument("--force", action="store_true",
                        help="review sheets whose latest attempt was already reviewed")
    review.add_argument("--concurrency", type=positive_int, default=DEFAULT_CONCURRENCY,
                        metavar="N", help="requests in flight at once (default: %(default)s)")
    review.set_defaults(func=cmd_review)

```

- [ ] **Step 3: Run the tests**

Run: `make test`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add diablo-texture-enhancement/anim_recreate.py diablo-texture-enhancement/test_anim_recreate.py
git commit -m "feat(kit): seed and caption characters; review done sheets concurrently

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 11: `verify` and `preview`

**Files:**
- Modify: `diablo-texture-enhancement/anim_recreate.py`, `test_anim_recreate.py`

**Interfaces:**
- Produces: `frame_problem(path, mask, skip) -> (code, detail) | None` (`MISSING`, `UNREADABLE`, `WRONGSIZE`, `WRONGMODE`, `WRONGALPHA`); `cmd_verify(args)` (also `UNRECORDED` for a frame whose sha256 is not its sheet's promoted record's, and the sheet status in capitals for `rejected`, `stuck`, `failed`, `missing`, `stale`); `cmd_preview(args)` (one GIF per direction under `--preview-dir`, named `<comfy_name(job key)>/d<group>.gif`).

- [ ] **Step 1: Write the failing tests**

In `test_anim_recreate.py`, change the `characters_file` import to:

```python
from characters_file import (Character, Review, load_characters, load_reviews,
                             save_characters, save_reviews)
```

and insert, before `@testkit.needs_real_corpus`:

```python
class VerifyPreviewTests(DriverTest):
    def test_verify_is_clean_after_a_batch_and_names_each_problem(self):
        self.batch()
        code, out, _ = testkit.run_cli(self.argv("verify"))
        self.assertEqual(code, 0, out)
        self.assertIn("verify: 7 animation(s) and variant(s), 34 frame(s), 0 problem(s)", out)
        frame = self.dst / ZW / "d0/f001.png"
        with Image.open(frame) as im:
            im.convert("RGBA").resize((64, 48)).convert("RGB").convert("RGBA").save(frame)
        (self.dst / ZN / "d1/f002.png").unlink()
        review = {f"{ZW}/{GREY}/s02": Review(1, False, ("bad",), "review")}
        save_reviews(self.reviews, review)
        code, out, _ = testkit.run_cli(self.argv("verify"))
        self.assertEqual(code, 1)
        for line in (f"WRONGALPHA {ZW}/d0/f001.png", f"MISSING    {ZN}/d1/f002.png",
                     f"UNRECORDED {ZW}/d0/f001.png", f"REJECTED   {ZW}/{GREY}/s02"):
            self.assertIn(line, out)

    def test_preview_writes_a_gif_per_direction(self):
        self.batch("--character", "missiles/fireba")
        preview = self.root / "preview"
        code, out, _ = testkit.run_cli(self.argv("preview", "--character", "missiles/fireba",
                                                 "--preview-dir", str(preview)))
        self.assertEqual(code, 0)
        gif = preview / "missiles+fireba1.cl2" / "d0.gif"
        with Image.open(gif) as im:
            self.assertEqual((im.n_frames, im.size), (3, (104, 48)))


```

Run: `.venv/bin/python -m unittest test_anim_recreate.VerifyPreviewTests -v`
Expected: FAIL (`invalid choice: 'verify'` / `'preview'`, exit 2).

- [ ] **Step 2: Implement**

Insert before `# ---- command line` in `anim_recreate.py`:

```python
# ---- verify -----------------------------------------------------------------

def frame_problem(path, mask, skip):
    """(code, detail) for an output frame that breaks the contract, or None."""
    if not path.is_file():
        return "MISSING", ""
    try:
        with Image.open(path) as im:
            size, mode = im.size, im.mode
            alpha = np.asarray(im.getchannel("A")) if mode == "RGBA" else None
    except OSError:
        return "UNREADABLE", ""
    want = (mask.shape[1] * SCALE, mask.shape[0] * SCALE)
    if size != want:
        return "WRONGSIZE", f"is {size[0]}x{size[1]}, expected {want[0]}x{want[1]}"
    if mode != "RGBA":
        return "WRONGMODE", f"is {mode}, expected RGBA"
    expected = sheet_layout.hard_alpha(mask) if skip else sheet_layout.soft_alpha(mask)
    if not np.array_equal(alpha, expected):
        return "WRONGALPHA", "the alpha is not the source outline at 2x"
    return None


def cmd_verify(args):
    characters = load_characters_checked(args)
    reviews = load_reviews(args.reviews, optional=True)
    jobs = select_jobs(args, characters)
    bad = frames = 0
    for job in jobs:
        sheets, masks = layout(args, job.anim)
        for frame, mask in zip(job.anim.frames, masks):
            frames += 1
            problem = frame_problem(args.dst / job.key / frame.png, mask, job.skip)
            if problem:
                bad += 1
                print(f"{problem[0]:10} {job.key}/{frame.png}"
                      + (f"  {problem[1]}" if problem[1] else ""))
        if job.skip:
            continue
        for sheet in sheets:
            sj = SheetJob(job, sheet)
            status, attempt, _ = status_of(args, sj, reviews, characters)
            if status == "done":
                record = read_record(audit_dir(args.dst, sj.key), attempt)
                for rel, sha in record.get("frames", {}).items():
                    if source_tree.file_sha256(args.dst / rel) != sha:
                        bad += 1
                        print(f"{'UNRECORDED':10} {rel}  no attempt record promoted this file - "
                              f"run: make batch anim={job.anim.key} force=1")
            elif status not in ("new", "blocked"):
                bad += 1
                print(f"{status.upper():10} {sj.key}")
    print(f"verify: {len(jobs)} animation(s) and variant(s), {frames} frame(s), "
          f"{bad} problem(s)")
    return 1 if bad else 0


# ---- preview ----------------------------------------------------------------

def cmd_preview(args):
    """An animated GIF per direction of each selected job: the source at
    SCALE (nearest) and the output side by side, over a dark background."""
    characters = load_characters_checked(args)
    written = 0
    for job in select_jobs(args, characters):
        groups = {}
        for frame in job.anim.frames:
            groups.setdefault(frame.group, []).append(frame)
        for group, frames in sorted(groups.items()):
            pictures = []
            for frame in frames:
                w, h = frame.w * SCALE, frame.h * SCALE
                picture = Image.new("RGB", (2 * w + 8, h), PREVIEW_BACKGROUND)
                source = sheet_layout.nearest_frame(
                    source_tree.frame_rgba(args.src, job.anim, frame, job.trn))
                picture.paste(source, (0, 0), source)
                out = args.dst / job.key / frame.png
                if out.is_file():
                    with Image.open(out) as im:
                        render = im.convert("RGBA")
                    picture.paste(render, (w + 8, 0), render)
                pictures.append(picture)
            path = args.preview_dir / comfy_client.comfy_name(job.key) / f"d{group}.gif"
            path.parent.mkdir(parents=True, exist_ok=True)
            pictures[0].save(path, save_all=True, append_images=pictures[1:],
                             duration=PREVIEW_MS, loop=0)
            written += 1
    print(f"preview: {written} GIF(s) -> {args.preview_dir}")
    return 0


```

In `build_parser`, insert before `    return ap`:

```python
    verify = sub.add_parser("verify", help="audit the output tree")
    common(verify)
    verify.set_defaults(func=cmd_verify)

    preview = sub.add_parser("preview", help="write an animated GIF per direction")
    common(preview)
    preview.add_argument("--preview-dir", type=Path, default=PREVIEW_ROOT,
                         help="where the GIFs go (default: %(default)s, or DIA_PREVIEW)")
    preview.set_defaults(func=cmd_preview)
```

- [ ] **Step 3: Run the suite**

Run: `make check && make test`
Expected: PASS: every test module, with the real-corpus tests when the export is present (about 75 s in all).

- [ ] **Step 4: Commit**

```bash
git add diablo-texture-enhancement/anim_recreate.py diablo-texture-enhancement/test_anim_recreate.py
git commit -m "feat(kit): verify the output tree; preview directions as GIFs

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 12: Documentation

**Files:**
- Create: `diablo-texture-enhancement/README.md`, `AGENTS.md`, `CLAUDE.md` (a symlink to `AGENTS.md`), `NOTES.md`

**Interfaces:**
- Consumes: every earlier task's commands, files and constants.

- [ ] **Step 1: Write README.md (the user view)**

Model it on the Dig kit's README section by section, with these contents:
- Title "Diablo Animation Regeneration"; what it regenerates (1,791 animations, 145,560 frames, and each monster recolour variant as its own animation: about 220,000 frames, exactly 2x, outline locked) and with which models (Qwen-Image 2.1 img2img with two reference images, `qwen-image-2.1-i2i-faithful` as the fallback; Qwen3.8-27B for captions and reviews).
- Input `../diablo-textures-exporter/out/` (`DIA_SRC`); output `data/anims-ai/<asset path>/d<g>/f<i>.png` and variants under `…/@trn/<trn>/…` (`DIA_DST`); previews in `data/preview/` (`DIA_PREVIEW`). Personal use only; never commit art.
- The pipeline (spec §4) and the order: `make caption` (seeds `characters.yaml`) → edit captions, anchors, `skip` → `make batch variants=0` → `make review` → repeat until the bases settle → `make batch` → `make review` → repeat → `make verify`.
- Swapping services (the Dig table and the `/free` curl).
- Characters: the seeded grouping, the anchor, `skip`; sheets and cells; `blocked` and `stale`.
- Checks (spec §8), STUCK and the fallback; restarting a sheet (delete `data/anims-ai/.quality/<sheet key>/` and its `reviews.yaml` entry, then `make batch anim=… force=1`).
- The audit folder (Task 9's record and files).
- The commands table (spec §9 plus `variant=`, `packing=`, `gutter=`, `background=`, `anchor=0`, `concurrency=`).
- Setup (ComfyUI at or after c194dd0 with `qwen_image_2.1_bf16`, `qwen3vl_8b_bf16`, `qwen_image_2.1_vae_bf16`; vLLM) and the project structure table.

- [ ] **Step 2: Write AGENTS.md (the agent view)**

Follow the Dig kit's `AGENTS.md` layout:
- §1 architecture: the stage table (caption / batch / review) and the rules that must survive any change:
  - the source is diablo-textures-exporter's output;
  - outputs are exactly 2x RGBA with the soft outline;
  - a sheet is the unit of attempt;
  - never loosen the gate;
  - services are external;
  - unified memory;
  - atomic writes;
  - resumable by construction, including `blocked` and `stale`;
  - only `comfy_client` knows node ids.
- §2 the module table (spec §5).
- §3 the render path (spec §6), with the node ids from Task 7.
- §4 the prompts.
- §5 testing: the rules, `DEFAULT_ANIMS` described, and the three real-corpus classes (`source_tree`, the full layout, perfect renders).
- §6: "Live checks, spikes and runs are in `NOTES.md`", plus the starting values of every constant the spike may change.

Then `ln -s AGENTS.md CLAUDE.md`.

- [ ] **Step 3: Start NOTES.md**

```markdown
# NOTES

Live checks, spikes and runs of the Diablo animation kit, newest last.

## Extraction

The export (`../diablo-textures-exporter/out`, exporter 97939cd, DevilutionX 8bef7bc):
1,791 animations (1,056 player, 334 monster, 21 towner, 380 missile), 145,560
frames, every one on `levels/towndata/town.pal`; 182 monster animations carry 97
distinct TRNs (about 74,000 variant frames). `monsters/darkmage/dmagew.cl2` has
no frames. Layout at the defaults: 11,394 base sheets; 17,410 with variants
(11,386 packed); about 9.8 gigapixels of canvas a pass; 1,866 sheets over
1 MP, the largest 1952x1440 (`monsters/nkr/nkrd.cl2`).
```

- [ ] **Step 4: Check the docs against the code**

Run: `make help` and compare every target and argument with the README's command table; `grep -n "DIG_\|dig_recreate\|room" README.md AGENTS.md` must only hit sentences naming the Dig or Atlantis kit as the model.

- [ ] **Step 5: Commit**

```bash
git add diablo-texture-enhancement/README.md diablo-texture-enhancement/AGENTS.md diablo-texture-enhancement/CLAUDE.md diablo-texture-enhancement/NOTES.md
git commit -m "docs(kit): README, AGENTS.md and NOTES.md for the Diablo kit

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 13: Live check and the spike (manual, GB10)

**Files:**
- Modify: `diablo-texture-enhancement/NOTES.md`, `characters.yaml` (seeded, spike captions), the constants the user's decisions change (with their tests), `AGENTS.md` §6

**Interfaces:**
- Consumes: everything. Needs the GPU services and the user's visual judgement; nothing here runs in CI.

- [ ] **Step 1: Seed and caption the spike characters (vLLM up, ComfyUI down)**

```bash
cd ~/code/diablo-hd-bundle/diablo-texture-enhancement
make caption character="plrgfx/warrior/wlm monsters/zombie monsters/nkr towners/smith missiles/fireba monsters/magma"
```

Expected: `seeded 251 character(s)`, then six captions. Read each caption against its contact sheet (`caption_images`) and fix misreadings by hand: in Atlantis, 61 of 91 captions needed fixes.

- [ ] **Step 2: Live check (vLLM down, ComfyUI up: `make server`)**

```bash
make dry-run anim=monsters/zombie/zombien.cl2 variants=0 dst=data/spike/live
make batch anim=monsters/zombie/zombien.cl2 variants=0 dst=data/spike/live
```

Expected: s01 renders with no anchor, s02–s08 with s01 as `images.image_2`. This is the only proof that the two-reference graph runs. If ComfyUI refuses the graph, fix `anim_qwen21_i2i.json` and its registry record and re-run Task 7's tests. Record the seconds per sheet and the gate results in `NOTES.md` under "## Live check".

- [ ] **Step 3: Spike renders**

The spike set is these animations with the anchors they need (`make dry-run` names any other anchor as `blocked`):
- `plrgfx/warrior/wlm/wlmst.cl2`, `wlmwl.cl2`, `wlmat.cl2`;
- `monsters/zombie/zombien.cl2`, `zombiew.cl2` with only `variant=monsters/zombie/grey.trn`;
- the nkr anchor and `monsters/nkr/nkrd.cl2` (the largest canvas);
- `towners/smith/smithn.cel`;
- `missiles/fireba1.cl2`;
- the magma anchor and `monsters/magma/magball1.cel` (an inferred width).

Render the baseline, then each variant alone, each into its own `dst=data/spike/<name>`:
1. `base` — the defaults;
2. `packed` — `packing=packed`;
3. `gutter32` — `gutter=32`;
4. `noanchor` — `anchor=0`;
5. `faithful` — `workflow=qwen-image-2.1-i2i-faithful`;
6. `dark` — `background=dark`.

Watch `free -g` while `nkrd.cl2`'s 1952x1440 sheet renders.

- [ ] **Step 4: Measure and judge**

For each variant, collect from the attempt records:
- seconds per sheet;
- promoted and rejected counts with their issues;
- the flicker ratios (`geometry.flicker`) and gutter bleed.

Also measure:
- the peak memory for the largest canvas;
- the gate itself: rerun `finish_sheet` on a few promoted renders after deliberately breaking them (shift 2 native px, replace one cell with another frame's), and list which thresholds catch them.

Run `make preview dst=data/spike/<name>` for every variant (each variant's GIFs land in `data/preview/<name>/<comfy name>/d<g>.gif`, keyed by the tree's directory name, so the variants never overwrite each other) and show the user the GIFs side by side. The user picks the settings.

- [ ] **Step 5: Record and apply the decisions**

Write "## Spike" in `NOTES.md` (Atlantis's format: a table per variant, then the decisions and why). Change the constants the user chose (`SHEET_PACKING`, `GUTTER`, `BACKGROUND`, the default workflow's denoise, the gate thresholds) and the tests that pin them, update AGENTS.md §6, and run `make test`.

- [ ] **Step 6: Commit**

```bash
git add diablo-texture-enhancement
git commit -m "docs(kit): record the live check and the spike; apply its settings

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 14: Full run (manual, GB10)

**Files:**
- Modify: `diablo-texture-enhancement/characters.yaml`, `NOTES.md`

**Interfaces:**
- Consumes: Task 13's settings. Expect about 11,400–17,400 sheets (by packing), about 9.8 gigapixels of canvas a pass: roughly 110–120 h at the Atlantis rate of about 50 s per 1.2 MP, before retries.

- [ ] **Step 1: Caption everything (vLLM up)**

`make caption`, then read every caption (251 characters) against its contact sheet, fix misreadings, and set `anchor` and `skip` by hand where the seed chose badly (for example, a player combination with no standing animation).

- [ ] **Step 2: Settle the base animations**

vLLM down, ComfyUI up: `make dry-run variants=0`, then `make batch variants=0`; repeat until nothing is new, rejected, stale or failed. ComfyUI down, vLLM up: `make review variants=0`. Repeat batch and review until the bases settle. Handle STUCK sheets by fixing captions (and clearing their `reviews.yaml` entries when the old issues quote the wrong words), then re-render each one alone as its STUCK line says: `make batch sheet=<sheet key> force=1`.

- [ ] **Step 3: Settle the variants**

The same loop without `variants=0`.

- [ ] **Step 4: Verify and record**

`make verify` → `verify: … 0 problem(s)`, or only sheets the user accepted STUCK, each listed in `NOTES.md` with its reason. Record the run in `NOTES.md` under "## Full run": first-attempt rejections, fallback promotions, review rejections and false ones, caption fixes, hours spent.

- [ ] **Step 5: Commit and finish the branch**

```bash
git add diablo-texture-enhancement/characters.yaml diablo-texture-enhancement/NOTES.md
git commit -m "docs(kit): record the full run

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

Then use superpowers:finishing-a-development-branch to merge `feat/diablo-animations` into `main`.
