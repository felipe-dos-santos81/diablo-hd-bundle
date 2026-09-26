# Diablo + Hellfire Graphics Exporter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `dtx`, a Python CLI that exports every graphic in the GOG Diablo + Hellfire MPQs as lossless PNG pairs with the metadata a future HD DevilutionX fork needs to map regenerated images back onto the original assets.

**Architecture:** StormLib (Homebrew, via `ctypes`) reads the MPQs. Pure decoders (`dtx.formats.*`) turn bytes into `Frame` objects (palette indices + opacity mask). A rule-table catalog decides what each file is; handlers write PNG/JSON; an orchestrator runs handlers per file with error isolation, idempotency and a coverage report. Game knowledge (file names, frame widths, TRN variants) is generated from DevilutionX at a pinned commit into `src/dtx/data/`.

**Tech Stack:** Python 3.12, uv, numpy, Pillow, pytest, StormLib 9.x (Homebrew `stormlib`).

**Spec:** `docs/superpowers/specs/2026-09-26-diablo-texture-export-design.md`

## Global Constraints

- Python `>=3.12`, managed with `uv`; runtime dependencies are only `numpy` and `pillow`; dev dependency only `pytest`.
- MPQ access only through StormLib (`brew install stormlib`), opened read-only (`MPQ_OPEN_READ_ONLY = 0x100`). Never write into the game directory.
- In-scope archives, highest priority first: `hfmonk.mpq`, `hellfire.mpq`, `DIABDAT.MPQ`. `hfmusic.mpq` and `hfvoice.mpq` are never opened.
- Reference implementation: DevilutionX commit `8bef7bce51641b8faa1f56f4119e5b6ee6ec6f3f`.
- Canonical MPQ names are lower-case with `\` separators (`levels\l1data\l1.cel`). Output paths are the same, with `/` (`out/assets/levels/l1data/l1/`).
- Round-trip fidelity is palette-index equality (indices of opaque pixels + opacity mask), not byte equality.
- No bytes derived from game data are committed: tests use synthetic fixtures built in `tests/builders.py`; `out/` is git-ignored. The generated name/width lists in `src/dtx/data/` contain only file names and numbers, and are committed.
- `dtx extract` exits non-zero if any file failed or failed verification.
- Every record JSON (`meta.json`, `tileset.json`, `layout.json`, `trn.json`, `<name>.pal.json`) is written **last** by its handler, so a partially written asset is re-exported on the next run.

## Review Focus

1. **Sprite files whose frames have different widths and no width table** (e.g. Hellfire's `data\inv\objcurs2.cel`) must export with per-frame inferred widths, not fail. → Task 7, `test_per_frame_inference_when_no_common_width`.
2. **Empty frames** (0-byte frame data, or 0×0 after decoding) must be exported as `"empty": true` without crashing PNG writing or sheet building. → Task 11 `test_empty_frame_writes_no_png`, Task 15 `test_sprite_with_empty_frame`.
3. **Level-cell data that begins with bytes `0A 00`** must not be mistaken for a 10-byte CEL frame header. → Task 8, `test_transparent_square_never_reads_header`.
4. **The same file in several archives**: identical bytes are exported once; different bytes produce an extra `@<archive>` copy. → Task 17, `test_identical_versions_export_once` and `test_different_versions_export_archive_copy`.
5. **A DUN that references tile ids beyond its tileset's TIL** must fail alone, with a clear error, while the rest of the export continues. → Task 16, `test_layout_with_out_of_range_tile_fails`, and Task 17, `test_one_bad_file_does_not_stop_export`.

---

## File Structure

```
pyproject.toml
.python-version
.gitignore                         (exists; extended in Task 1)
Makefile                           install / refdata / extract / test targets with `make help`
README.md                          overview, setup, usage, output layout
src/dtx/
  __init__.py
  cli.py                           argparse entry point: `dtx refdata build`, `dtx extract`
  paths.py                         canonical/relative name helpers
  binary.py                        bounds-checked little-endian reads
  mpq.py                           StormLib ctypes wrapper, MpqArchive, ArchiveStack
  refdata.py                       builds/loads src/dtx/data/{listfile.txt,widths.json,variants.json}
  catalog.py                       rule table: name -> Entry | Skip; tileset specs
  export.py                        PNG pair / sheet / swatch / JSON writers
  verify.py                        index-PNG reload and comparison
  handlers.py                      per-kind export handlers + Context
  extract.py                       orchestration, versions, idempotency, report, manifest, parallelism
  formats/
    __init__.py
    frame.py                       Frame dataclass
    pal.py                         .pal decoder + colour-cycling table
    trn.py                         .trn decoder
    pcx.py                         .pcx decoder
    sheet.py                       CEL/CL2 container (single + grouped) splitter
    cel.py                         CEL frame scanner/decoder
    cl2.py                         CL2 frame scanner/decoder + skip-table check
    width.py                       frame-width resolution (table / inferred / per-frame)
    levelcel.py                    32x32 dungeon cell decoder (6 tile types)
    tileset.py                     MIN/TIL/SOL/DUN parsers, column composition
    render.py                      isometric placement + composition + crop boxes
  data/
    listfile.txt                   generated (Task 13)
    widths.json                    generated (Task 13)
    variants.json                  generated (Task 13)
tests/
  conftest.py                      `game` marker handling, game_dir fixture
  builders.py                      synthetic encoders for every format (test-only)
  fakes.py                         FakeArchive for stack/handler tests
  test_*.py                        one file per module
```

---

### Task 1: Project scaffold, core types, path helpers, Makefile and README

**Files:**
- Create: `pyproject.toml`, `.python-version`, `Makefile`, `README.md`, `src/dtx/__init__.py`, `src/dtx/cli.py`, `src/dtx/paths.py`, `src/dtx/binary.py`, `src/dtx/formats/__init__.py`, `src/dtx/formats/frame.py`, `tests/conftest.py`
- Modify: `.gitignore`
- Test: `tests/test_frame.py`, `tests/test_paths.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `dtx.formats.frame.Frame(indices: np.ndarray[h,w] uint8, opaque: np.ndarray[h,w] bool)` with `.width`, `.height`, `Frame.from_bottom_up(pixels: bytes, mask: bytes, width: int) -> Frame`, `Frame.same_pixels(other) -> bool`, `Frame.empty(width=0, height=0) -> Frame`.
  - `dtx.paths.canonical(name) -> str`, `rel_path(name) -> str`, `extension(name) -> str`, `directory(name) -> str`, `stem(name) -> str`.
  - `dtx.binary.u16(data, offset) -> int`, `u32(data, offset) -> int` (raise `ValueError` when out of range).
  - `dtx.cli.main(argv: list[str] | None = None) -> int` and `dtx.cli.build_parser() -> argparse.ArgumentParser` with a `subparsers` attribute stored as `parser._dtx_subparsers` for later tasks to register commands.

- [ ] **Step 1: Create project files**

`pyproject.toml`:
```toml
[project]
name = "dtx"
version = "0.1.0"
description = "Export Diablo and Hellfire graphics for HD regeneration"
requires-python = ">=3.12"
dependencies = ["numpy>=2.0", "pillow>=10.0"]

[project.scripts]
dtx = "dtx.cli:main"

[dependency-groups]
dev = ["pytest>=8"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/dtx"]

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = ["game: needs DTX_GAME_DIR pointing at the GOG Diablo + Hellfire install"]
```

`.python-version`:
```
3.12
```

`src/dtx/__init__.py`:
```python
"""Diablo + Hellfire graphics exporter."""
```

`src/dtx/formats/__init__.py`:
```python
"""Pure decoders: bytes in, arrays out. No file or archive access."""
```

`tests/conftest.py`:
```python
import os
from pathlib import Path

import pytest


def pytest_collection_modifyitems(config, items):
    if os.environ.get("DTX_GAME_DIR"):
        return
    skip = pytest.mark.skip(reason="set DTX_GAME_DIR to run game-data tests")
    for item in items:
        if "game" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def game_dir() -> Path:
    return Path(os.environ["DTX_GAME_DIR"]).expanduser()
```

- [ ] **Step 2: Write the failing tests**

`tests/test_frame.py`:
```python
import numpy as np
import pytest

from dtx.formats.frame import Frame


def test_from_bottom_up_flips_rows():
    # bottom row first: bottom = [1, 2], top = [3, 4]
    frame = Frame.from_bottom_up(bytes([1, 2, 3, 4]), bytes([1, 1, 0, 1]), 2)
    assert frame.width == 2 and frame.height == 2
    np.testing.assert_array_equal(frame.indices, [[3, 4], [1, 2]])
    np.testing.assert_array_equal(frame.opaque, [[False, True], [True, True]])


def test_from_bottom_up_rejects_partial_rows():
    with pytest.raises(ValueError):
        Frame.from_bottom_up(bytes(3), bytes(3), 2)


def test_from_bottom_up_rejects_zero_width():
    with pytest.raises(ValueError):
        Frame.from_bottom_up(b"", b"", 0)


def test_same_pixels_ignores_indices_under_transparency():
    a = Frame(np.array([[5, 9]], np.uint8), np.array([[True, False]]))
    b = Frame(np.array([[5, 0]], np.uint8), np.array([[True, False]]))
    c = Frame(np.array([[6, 0]], np.uint8), np.array([[True, False]]))
    assert a.same_pixels(b)
    assert not a.same_pixels(c)


def test_shape_mismatch_rejected():
    with pytest.raises(ValueError):
        Frame(np.zeros((2, 2), np.uint8), np.zeros((2, 3), bool))


def test_empty_frame():
    frame = Frame.empty(32, 0)
    assert frame.width == 32 and frame.height == 0
```

`tests/test_paths.py`:
```python
import pytest

from dtx.binary import u16, u32
from dtx.paths import canonical, directory, extension, rel_path, stem


def test_canonical_and_rel():
    assert canonical("Levels/L1Data/L1.CEL") == "levels\\l1data\\l1.cel"
    assert rel_path("Levels\\L1Data\\L1.CEL") == "levels/l1data/l1.cel"


def test_parts():
    assert extension("levels\\l1data\\l1.cel") == "cel"
    assert extension("levels\\l1data\\noext") == ""
    assert directory("levels\\l1data\\l1.cel") == "levels\\l1data"
    assert directory("toplevel.pcx") == ""
    assert stem("levels\\l1data\\l1.cel") == "levels\\l1data\\l1"


def test_binary_reads():
    data = bytes([1, 0, 2, 0, 0, 0])
    assert u16(data, 0) == 1
    assert u32(data, 2) == 2
    with pytest.raises(ValueError):
        u32(data, 4)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv sync && uv run pytest tests/test_frame.py tests/test_paths.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'dtx.formats.frame'` (and `dtx.paths`).

- [ ] **Step 4: Implement**

`src/dtx/formats/frame.py`:
```python
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, eq=False)
class Frame:
    """A decoded image: palette indices plus an opacity mask. Row 0 is the top row."""

    indices: np.ndarray  # (h, w) uint8
    opaque: np.ndarray  # (h, w) bool

    def __post_init__(self) -> None:
        if self.indices.shape != self.opaque.shape:
            raise ValueError(
                f"indices shape {self.indices.shape} != opaque shape {self.opaque.shape}"
            )

    @property
    def width(self) -> int:
        return int(self.indices.shape[1])

    @property
    def height(self) -> int:
        return int(self.indices.shape[0])

    @classmethod
    def empty(cls, width: int = 0, height: int = 0) -> Frame:
        return cls(np.zeros((height, width), np.uint8), np.zeros((height, width), bool))

    @classmethod
    def from_bottom_up(cls, pixels: bytes, mask: bytes, width: int) -> Frame:
        """Build a frame from row-major pixel data whose first row is the bottom row."""
        if width <= 0:
            raise ValueError(f"frame width must be positive, got {width}")
        if len(pixels) != len(mask):
            raise ValueError("pixel and mask lengths differ")
        if len(pixels) % width:
            raise ValueError(f"{len(pixels)} pixels is not a multiple of width {width}")
        height = len(pixels) // width
        indices = np.frombuffer(bytes(pixels), np.uint8).reshape(height, width)[::-1].copy()
        opaque = np.frombuffer(bytes(mask), np.uint8).reshape(height, width)[::-1] != 0
        return cls(indices, opaque.copy())

    def same_pixels(self, other: Frame) -> bool:
        """True when both frames have the same opacity and the same indices where opaque."""
        return (
            self.indices.shape == other.indices.shape
            and np.array_equal(self.opaque, other.opaque)
            and np.array_equal(self.indices[self.opaque], other.indices[other.opaque])
        )
```

`src/dtx/paths.py`:
```python
"""Name helpers. Canonical MPQ names are lower-case with backslash separators."""


def canonical(name: str) -> str:
    return name.replace("/", "\\").lower()


def rel_path(name: str) -> str:
    return canonical(name).replace("\\", "/")


def directory(name: str) -> str:
    c = canonical(name)
    return c.rsplit("\\", 1)[0] if "\\" in c else ""


def extension(name: str) -> str:
    base = canonical(name).rsplit("\\", 1)[-1]
    return base.rsplit(".", 1)[1] if "." in base else ""


def stem(name: str) -> str:
    c = canonical(name)
    ext = extension(c)
    return c[: -(len(ext) + 1)] if ext else c
```

`src/dtx/binary.py`:
```python
def _read(data: bytes, offset: int, size: int) -> int:
    if offset < 0 or offset + size > len(data):
        raise ValueError(f"read of {size} bytes at offset {offset} past end of {len(data)}-byte buffer")
    return int.from_bytes(data[offset : offset + size], "little")


def u16(data: bytes, offset: int) -> int:
    return _read(data, offset, 2)


def u32(data: bytes, offset: int) -> int:
    return _read(data, offset, 4)
```

`src/dtx/cli.py`:
```python
from __future__ import annotations

import argparse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dtx", description="Export Diablo and Hellfire graphics for HD regeneration."
    )
    parser._dtx_subparsers = parser.add_subparsers(dest="command")  # type: ignore[attr-defined]
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 2
    return int(args.func(args))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest -v && uv run dtx --help`
Expected: all tests PASS; `dtx --help` prints usage.

- [ ] **Step 6: Add Makefile, README and .gitignore**

The Makefile follows the style of the user's reference Makefile: a header comment naming the pipeline order, a `SERVICE` name, a `# Variables` block, a `.PHONY` list, `# ── Section ──` dividers, `## description` on every public target (parsed by `help`), `[STEP n]` tags on pipeline targets, and optional `arg=val` switches via `$(if ...)`. Recipe lines must be indented with a **tab**. The `refdata` and `extract` targets call CLI commands that Tasks 13 and 17 add; until then they fail with an argparse error, which is expected.

`Makefile`:
```make
# Makefile for dtx — Diablo + Hellfire graphics exporter
# Targets follow the pipeline:
#   install → 1 refdata → 2 extract → test
SERVICE = dtx

# Variables
UV = uv
DVX_REPO = https://github.com/diasurgical/devilutionx
DVX_COMMIT = 8bef7bce51641b8faa1f56f4119e5b6ee6ec6f3f
game ?= $(HOME)/diablo1-hellfire-gog
out ?= out
dvx ?= $(HOME)/.cache/dtx/devilutionx

.PHONY: help install clean devilutionx refdata extract test test-game

# ── Environment ──────────────────────────────────────────────────────────────

help: ## Print this help message
	@printf '\033[01;32m${SERVICE} — Diablo + Hellfire graphics exporter\033[00;37m\n\n'
	@printf "\033[33mUsage:\033[0m\n  make [target] [arg=\"val\"...]\n\n\033[33mTargets:\033[0m\n"
	@grep -E '^[-a-zA-Z0-9_\.\/]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; \
		{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## Install StormLib (Homebrew) and the Python environment (uv)
	@brew list stormlib >/dev/null 2>&1 || brew install stormlib
	@$(UV) sync
	@echo "Environment setup complete."

clean: ## Remove the venv, caches and exported output
	rm -rf .venv .pytest_cache "$(out)"
	find . -type d -name "__pycache__" -exec rm -rf {} +
	@echo "Cleanup complete."

# ── Stage 1 · Reference data ─────────────────────────────────────────────────

devilutionx: ## Clone DevilutionX at the pinned commit (usage: make devilutionx [dvx=path])
	@if [ ! -d "$(dvx)" ]; then git clone --filter=blob:none $(DVX_REPO) "$(dvx)"; fi
	@git -C "$(dvx)" checkout -q $(DVX_COMMIT)

refdata: install devilutionx ## [STEP 1] Regenerate listfile and width tables (usage: make refdata [community=listfile.txt])
	$(UV) run dtx refdata build --devilutionx "$(dvx)" --game "$(game)" $(if $(community),--community "$(community)")

# ── Stage 2 · Export ─────────────────────────────────────────────────────────

extract: install ## [STEP 2] Export and verify all graphics (usage: make extract [game=dir] [out=dir] [only=tileset,layout] [force=1] [jobs=8])
	$(UV) run dtx extract --game "$(game)" --out "$(out)" --verify $(if $(only),--only "$(only)") $(if $(force),--force) $(if $(jobs),--jobs "$(jobs)")

# ── Development ──────────────────────────────────────────────────────────────

test: install ## Run the unit tests (no game data needed)
	$(UV) run pytest -q

test-game: install ## Run all tests, including those that read the game archives (usage: make test-game [game=dir])
	DTX_GAME_DIR="$(game)" $(UV) run pytest -q
```

`README.md`:
````markdown
# dtx — Diablo + Hellfire graphics exporter

Exports every graphic in the GOG Diablo + Hellfire game data — UI screens, town and dungeon tilesets, level layouts, monsters, player characters, items, spell effects and objects — as lossless PNGs with the metadata needed to put AI-regenerated HD versions back into a future DevilutionX fork.

## Requirements

- macOS with [Homebrew](https://brew.sh) (for StormLib) and [uv](https://docs.astral.sh/uv/)
- The GOG game files `DIABDAT.MPQ`, `hellfire.mpq` and `hfmonk.mpq`, by default in `~/diablo1-hellfire-gog`

## Usage

```sh
make install                      # StormLib + Python environment
make extract                      # export everything to ./out
make extract only=tileset,layout  # just backgrounds
make help                         # all targets and options
```

## Output

```
out/
  manifest.json    every exported asset + the HD replacement contract
  report.json      exported / skipped (with reason) / failed / unnamed files
  palettes/        each .pal as a swatch PNG + JSON (colours, colour cycling)
  assets/<archive path>/
    *.png          RGBA image, ready for AI regeneration
    *.idx.png      exact original palette indices (grey) + transparency (alpha)
    meta.json      sprites and images: frames, widths, palette, colour variants
    tileset.json   tilesets: columns (the editable unit), cells, tiles
    layout.json    level layouts: where each column is placed in layout.png
```

A regenerated image must be the original size multiplied by one whole number per asset (see `hd_contract` in `manifest.json`). The `*.idx.png` files let any image be re-rendered with a different palette.

Exported images come from copyrighted game data: keep `out/` out of version control.

## Reference data

`src/dtx/data/` holds the archive file names and sprite frame widths, generated from [DevilutionX](https://github.com/diasurgical/devilutionx) at a pinned commit. Regenerate with `make refdata`.

## Development

```sh
make test        # unit tests, synthetic data only
make test-game   # also runs tests against the game archives
```

Design: [`docs/superpowers/specs/2026-09-26-diablo-texture-export-design.md`](docs/superpowers/specs/2026-09-26-diablo-texture-export-design.md)
````

Replace `.gitignore` with:
```
# Exported game graphics (copyrighted source data)
out/

# Python
.venv/
__pycache__/
*.py[cod]
*.egg-info/
.pytest_cache/
build/
dist/

# OS
.DS_Store
```

Run: `make help && make test`
Expected: `help` lists `help, install, clean, devilutionx, refdata, extract, test, test-game` with descriptions; `make test` passes.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml .python-version uv.lock Makefile README.md .gitignore src tests
git commit -m "feat: scaffold dtx package with Frame, path helpers, Makefile and README"
```

---

### Task 2: Palette and TRN decoders

**Files:**
- Create: `src/dtx/formats/pal.py`, `src/dtx/formats/trn.py`
- Test: `tests/test_pal_trn.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `decode_pal(data: bytes) -> np.ndarray[256,3] uint8`; `cycling_for(pal_name: str) -> list[dict]`; `decode_trn(data: bytes) -> np.ndarray[256] uint8`.

- [ ] **Step 1: Write the failing tests**

`tests/test_pal_trn.py`:
```python
import numpy as np
import pytest

from dtx.formats.pal import cycling_for, decode_pal
from dtx.formats.trn import decode_trn


def test_decode_pal():
    data = bytes(range(256)) * 3
    pal = decode_pal(data)
    assert pal.shape == (256, 3)
    assert pal.dtype == np.uint8
    assert tuple(pal[1]) == (3, 4, 5)


def test_decode_pal_rejects_wrong_size():
    with pytest.raises(ValueError):
        decode_pal(bytes(767))


def test_cycling_by_directory():
    assert cycling_for("levels\\l3data\\l3_1.pal")[0]["first"] == 1
    assert cycling_for("levels\\l3data\\l3_1.pal")[0]["last"] == 31
    assert len(cycling_for("nlevels\\l5data\\l5base.pal")) == 2
    assert cycling_for("levels\\towndata\\town.pal") == []


def test_decode_trn():
    trn = decode_trn(bytes(reversed(range(256))))
    assert trn[0] == 255 and trn[255] == 0


def test_decode_trn_rejects_short():
    with pytest.raises(ValueError):
        decode_trn(bytes(10))
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_pal_trn.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`src/dtx/formats/pal.py`:
```python
import numpy as np

from dtx.paths import directory

PALETTE_BYTES = 768

# Colour-cycling ranges by palette directory, from DevilutionX
# Source/engine/palette.cpp (palette_update_caves/crypt/hive) and
# Source/lighting.cpp (lighting_color_cycling) at commit 8bef7bce.
CYCLING: dict[str, list[dict]] = {
    "levels\\l3data": [{"first": 1, "last": 31, "direction": "forward", "every_n_frames": 1}],
    "levels\\l4data": [
        {"first": 1, "last": 31, "direction": "forward", "every_n_frames": 1, "via": "light_tables"}
    ],
    "nlevels\\l5data": [
        {"first": 1, "last": 15, "direction": "reverse", "every_n_frames": 2},
        {"first": 16, "last": 31, "direction": "reverse", "every_n_frames": 1},
    ],
    "nlevels\\l6data": [
        {"first": 1, "last": 8, "direction": "reverse", "every_n_frames": 3},
        {"first": 9, "last": 15, "direction": "reverse", "every_n_frames": 3},
    ],
}


def decode_pal(data: bytes) -> np.ndarray:
    if len(data) != PALETTE_BYTES:
        raise ValueError(f"palette must be {PALETTE_BYTES} bytes, got {len(data)}")
    return np.frombuffer(data, np.uint8).reshape(256, 3).copy()


def cycling_for(pal_name: str) -> list[dict]:
    return [dict(r) for r in CYCLING.get(directory(pal_name), [])]
```

`src/dtx/formats/trn.py`:
```python
import numpy as np

TRN_BYTES = 256


def decode_trn(data: bytes) -> np.ndarray:
    """A TRN maps each palette index to a replacement index (monster colour variants)."""
    if len(data) < TRN_BYTES:
        raise ValueError(f"TRN must be at least {TRN_BYTES} bytes, got {len(data)}")
    return np.frombuffer(data[:TRN_BYTES], np.uint8).copy()
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_pal_trn.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/dtx/formats/pal.py src/dtx/formats/trn.py tests/test_pal_trn.py
git commit -m "feat: add palette and TRN decoders with colour-cycling table"
```

---

### Task 3: PCX decoder

**Files:**
- Create: `src/dtx/formats/pcx.py`, `tests/builders.py`
- Test: `tests/test_pcx.py`

**Interfaces:**
- Consumes: `Frame` (Task 1), `u16` (Task 1).
- Produces: `decode_pcx(data: bytes) -> tuple[Frame, np.ndarray[256,3]]` (frame fully opaque). Test helper `tests.builders.pcx(indices, palette, bytes_per_line=None) -> bytes`.

PCX facts: 128-byte header; byte 0 = `0x0A`; byte 3 = bits per pixel (must be 8); bytes 4–11 = xmin, ymin, xmax, ymax (u16); byte 65 = planes (must be 1); bytes 66–67 = bytes per line (≥ width, may pad). Body is RLE: a byte `>= 0xC0` means `count = b & 0x3F` copies of the next byte; otherwise the byte is one pixel. The file ends with `0x0C` + 768-byte palette.

- [ ] **Step 1: Write the test builder**

`tests/builders.py`:
```python
"""Synthetic encoders for every Diablo format. Test-only: no game data."""
import struct

import numpy as np


def pcx(indices: np.ndarray, palette: np.ndarray, bytes_per_line: int | None = None) -> bytes:
    h, w = indices.shape
    bpl = bytes_per_line or (w + (w & 1))
    header = bytearray(128)
    header[0], header[1], header[2], header[3] = 0x0A, 5, 1, 8
    struct.pack_into("<4H", header, 4, 0, 0, w - 1, h - 1)
    header[65] = 1
    struct.pack_into("<H", header, 66, bpl)
    body = bytearray()
    for row in indices:
        line = bytes(int(v) for v in row) + bytes(bpl - w)
        i = 0
        while i < len(line):
            v = line[i]
            n = 1
            while i + n < len(line) and line[i + n] == v and n < 63:
                n += 1
            if n > 1 or v >= 0xC0:
                body += bytes([0xC0 | n, v])
            else:
                body.append(v)
            i += n
    return bytes(header) + bytes(body) + b"\x0c" + palette.astype(np.uint8).tobytes()
```

- [ ] **Step 2: Write the failing tests**

`tests/test_pcx.py`:
```python
import numpy as np
import pytest

from builders import pcx
from dtx.formats.pcx import decode_pcx

PAL = np.arange(768, dtype=np.uint32).reshape(256, 3).astype(np.uint8)


def test_roundtrip_odd_width_with_padding_and_high_values():
    indices = np.array([[1, 2, 0xC5], [7, 7, 7]], np.uint8)
    frame, palette = decode_pcx(pcx(indices, PAL))
    np.testing.assert_array_equal(frame.indices, indices)
    assert frame.opaque.all()
    np.testing.assert_array_equal(palette, PAL)


def test_rejects_bad_magic():
    data = bytearray(pcx(np.zeros((1, 1), np.uint8), PAL))
    data[0] = 0
    with pytest.raises(ValueError):
        decode_pcx(bytes(data))


def test_rejects_truncated_body():
    data = pcx(np.arange(64, dtype=np.uint8).reshape(8, 8), PAL)
    body_cut = data[:140] + data[-769:]
    with pytest.raises(ValueError):
        decode_pcx(body_cut)


def test_rejects_missing_palette_marker():
    data = bytearray(pcx(np.zeros((1, 1), np.uint8), PAL))
    data[-769] = 0
    with pytest.raises(ValueError):
        decode_pcx(bytes(data))
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/test_pcx.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'dtx.formats.pcx'`.

Note: `tests/` is on `sys.path` because pytest uses rootdir-relative imports for test modules; if `from builders import pcx` fails with `ModuleNotFoundError: builders`, add `pythonpath = ["tests"]` under `[tool.pytest.ini_options]` in `pyproject.toml`.

- [ ] **Step 4: Implement**

`src/dtx/formats/pcx.py`:
```python
import numpy as np

from dtx.binary import u16
from dtx.formats.frame import Frame

HEADER_BYTES = 128
PALETTE_TRAILER_BYTES = 769  # 0x0C marker + 768 palette bytes


def decode_pcx(data: bytes) -> tuple[Frame, np.ndarray]:
    """Decode an 8-bit single-plane PCX. Returns an opaque frame and its 256-colour palette."""
    if len(data) < HEADER_BYTES + PALETTE_TRAILER_BYTES or data[0] != 0x0A:
        raise ValueError("not a PCX file")
    if data[3] != 8 or data[65] != 1:
        raise ValueError(f"unsupported PCX: {data[3]} bits per pixel, {data[65]} planes")
    if data[-PALETTE_TRAILER_BYTES] != 0x0C:
        raise ValueError("PCX has no 256-colour palette")
    xmin, ymin, xmax, ymax = (u16(data, 4 + 2 * k) for k in range(4))
    width, height = xmax - xmin + 1, ymax - ymin + 1
    bytes_per_line = u16(data, 66)
    if width <= 0 or height <= 0 or bytes_per_line < width:
        raise ValueError(f"invalid PCX geometry {width}x{height}, {bytes_per_line} bytes per line")

    need = bytes_per_line * height
    end = len(data) - PALETTE_TRAILER_BYTES
    out = bytearray()
    i = HEADER_BYTES
    while len(out) < need and i < end:
        b = data[i]
        i += 1
        if b >= 0xC0:
            if i >= end:
                raise ValueError("PCX run is missing its value byte")
            out += bytes([data[i]]) * (b & 0x3F)
            i += 1
        else:
            out.append(b)
    if len(out) < need:
        raise ValueError(f"PCX body truncated: {len(out)} of {need} bytes")

    indices = np.frombuffer(bytes(out[:need]), np.uint8).reshape(height, bytes_per_line)[:, :width]
    palette = np.frombuffer(data[-768:], np.uint8).reshape(256, 3).copy()
    frame = Frame(indices.copy(), np.ones((height, width), bool))
    return frame, palette
```

- [ ] **Step 5: Run to verify pass**

Run: `uv run pytest tests/test_pcx.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/dtx/formats/pcx.py tests/builders.py tests/test_pcx.py pyproject.toml
git commit -m "feat: add PCX decoder"
```

---

### Task 4: CEL/CL2 sheet container splitter

**Files:**
- Create: `src/dtx/formats/sheet.py`
- Modify: `tests/builders.py` (append)
- Test: `tests/test_sheet.py`

**Interfaces:**
- Consumes: `u32` (Task 1).
- Produces: `split_sheet(data: bytes) -> list[list[bytes]]` — raw frame bytes, `[group][frame]`; ungrouped files return one group. Test helpers `builders.sheet(frames) -> bytes`, `builders.grouped(sheets) -> bytes`.

Container facts (DevilutionX `Source/utils/cel_to_clx.cpp`, `cl2_to_clx.cpp`): a sheet is `u32 n`, then `n+1` u32 offsets (the last equals the sheet size), then frame data. A grouped file starts with `g` u32 offsets to sub-sheets; it is detected when the value at `4*first + 4` is **not** the file size.

- [ ] **Step 1: Append builders**

Append to `tests/builders.py`:
```python
def sheet(frames: list[bytes]) -> bytes:
    n = len(frames)
    offsets = [4 * (n + 2)]
    for f in frames:
        offsets.append(offsets[-1] + len(f))
    return struct.pack(f"<{n + 2}I", n, *offsets) + b"".join(frames)


def grouped(sheets: list[bytes]) -> bytes:
    pos = 4 * len(sheets)
    offsets = []
    for s in sheets:
        offsets.append(pos)
        pos += len(s)
    return struct.pack(f"<{len(sheets)}I", *offsets) + b"".join(sheets)
```

- [ ] **Step 2: Write the failing tests**

`tests/test_sheet.py`:
```python
import pytest

from builders import grouped, sheet
from dtx.formats.sheet import split_sheet


def test_single_sheet():
    assert split_sheet(sheet([b"ab", b"", b"cde"])) == [[b"ab", b"", b"cde"]]


def test_zero_frame_sheet():
    assert split_sheet(sheet([])) == [[]]


def test_grouped_sheet_of_eight_directions():
    groups = [sheet([bytes([g]) * (g + 1), b"z"]) for g in range(8)]
    result = split_sheet(grouped(groups))
    assert len(result) == 8
    assert result[3] == [b"\x03" * 4, b"z"]


def test_rejects_garbage():
    with pytest.raises(ValueError):
        split_sheet(b"\xff\xff\xff\xff\x00\x00\x00\x00")


def test_rejects_too_small():
    with pytest.raises(ValueError):
        split_sheet(b"\x00\x00")
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/test_sheet.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 4: Implement**

`src/dtx/formats/sheet.py`:
```python
from dtx.binary import u32


def split_sheet(data: bytes) -> list[list[bytes]]:
    """Split a CEL or CL2 file into raw frame bytes, grouped as [group][frame]."""
    if len(data) < 8:
        raise ValueError("file too small to be a CEL/CL2 sheet")
    first = u32(data, 0)
    last_offset_at = 4 * first + 4
    if last_offset_at + 4 <= len(data) and u32(data, last_offset_at) == len(data):
        return [_split_frames(data)]

    if first == 0 or first % 4 or first > len(data):
        raise ValueError("not a CEL/CL2 sheet")
    count = first // 4
    offsets = [u32(data, 4 * g) for g in range(count)] + [len(data)]
    if any(b < a for a, b in zip(offsets, offsets[1:])):
        raise ValueError("CEL/CL2 group offsets are not increasing")
    return [_split_frames(data[offsets[g] : offsets[g + 1]]) for g in range(count)]


def _split_frames(sheet: bytes) -> list[bytes]:
    n = u32(sheet, 0)
    offsets = [u32(sheet, 4 + 4 * i) for i in range(n + 1)]
    if offsets[-1] > len(sheet) or any(b < a for a, b in zip(offsets, offsets[1:])):
        raise ValueError("CEL/CL2 frame offsets out of range")
    return [sheet[offsets[i] : offsets[i + 1]] for i in range(n)]
```

- [ ] **Step 5: Run to verify pass**

Run: `uv run pytest tests/test_sheet.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/dtx/formats/sheet.py tests/builders.py tests/test_sheet.py
git commit -m "feat: split CEL/CL2 sheets including grouped files"
```

---

### Task 5: CEL frame scanner and decoder

**Files:**
- Create: `src/dtx/formats/cel.py`
- Modify: `tests/builders.py` (append)
- Test: `tests/test_cel.py`

**Interfaces:**
- Consumes: `Frame`, `u16`.
- Produces: `scan_cel_frame(raw: bytes, allow_header: bool = True) -> CelScan`; `CelScan.fits(width: int, strict: bool = True) -> bool`; `CelScan.to_frame(width: int) -> Frame`; `decode_cel_frame(raw, width, allow_header=True) -> Frame`. Test helper `builders.cel_frame(rows, header=False) -> bytes`.

CEL frame facts (DevilutionX `cel_to_clx.cpp`, `dun_tile.hpp`): optional 10-byte header, present when the first u16 equals 10. Rows are stored bottom row first. Control byte `c >= 0x80` = `256 - c` transparent pixels; otherwise `c` literal pixel bytes follow. Runs never cross a row boundary — this is what makes width inference possible.

- [ ] **Step 1: Append builder**

Append to `tests/builders.py`:
```python
def cel_frame(rows: list[list[int | None]], header: bool = False) -> bytes:
    """Encode rows (top row first; None = transparent) as a CEL frame."""
    out = bytearray()
    for row in reversed(rows):
        i = 0
        while i < len(row):
            n = 1
            if row[i] is None:
                while i + n < len(row) and row[i + n] is None and n < 128:
                    n += 1
                out.append(256 - n)
            else:
                while i + n < len(row) and row[i + n] is not None and n < 127:
                    n += 1
                out.append(n)
                out += bytes(row[i : i + n])
            i += n
    if header:
        return struct.pack("<5H", 10, 0, 0, 0, 0) + bytes(out)
    return bytes(out)
```

- [ ] **Step 2: Write the failing tests**

`tests/test_cel.py`:
```python
import numpy as np
import pytest

from builders import cel_frame
from dtx.formats.cel import decode_cel_frame, scan_cel_frame

ROWS = [[1, None, 3], [None, None, 6]]


def test_decode_basic():
    frame = decode_cel_frame(cel_frame(ROWS), 3)
    np.testing.assert_array_equal(frame.indices, [[1, 0, 3], [0, 0, 6]])
    np.testing.assert_array_equal(frame.opaque, [[True, False, True], [False, False, True]])


def test_decode_with_header():
    frame = decode_cel_frame(cel_frame(ROWS, header=True), 3)
    np.testing.assert_array_equal(frame.indices, [[1, 0, 3], [0, 0, 6]])


def test_fits_only_true_width():
    scan = scan_cel_frame(cel_frame([[1, 2, 3, 4], [5, 6, 7, 8]]))
    # one literal run of 4 per row -> width 2 would split a run across rows
    assert scan.fits(4)
    assert not scan.fits(2)
    assert not scan.fits(3)


def test_run_crossing_row_raises():
    with pytest.raises(ValueError):
        decode_cel_frame(cel_frame([[1, 2, 3, 4]]), 3)


def test_empty_frame():
    frame = decode_cel_frame(b"", 16)
    assert frame.width == 16 and frame.height == 0


def test_truncated_literal_raises():
    with pytest.raises(ValueError):
        scan_cel_frame(bytes([5, 1, 2]))


def test_header_detection_can_be_disabled():
    # literal run of 10 pixels starting with value 0 begins with bytes 0A 00
    raw = bytes([10]) + bytes(range(10))
    frame = decode_cel_frame(raw, 10, allow_header=False)
    np.testing.assert_array_equal(frame.indices[0], list(range(10)))
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/test_cel.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 4: Implement**

`src/dtx/formats/cel.py`:
```python
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from dtx.binary import u16
from dtx.formats.frame import Frame

CEL_FRAME_HEADER_BYTES = 10


@dataclass(frozen=True, eq=False)
class CelScan:
    """Width-independent decode of a CEL frame: pixels in stream order plus run extents."""

    pixels: bytes
    mask: bytes
    starts: np.ndarray  # start pixel position of each non-empty run
    ends: np.ndarray  # end (exclusive) pixel position of each non-empty run

    def fits(self, width: int, strict: bool = True) -> bool:
        """True when no run crosses a row and the frame ends on a row boundary."""
        if width <= 0 or len(self.pixels) % width:
            return False
        if len(self.starts) == 0:
            return True
        return bool(np.all(self.starts // width == (self.ends - 1) // width))

    def to_frame(self, width: int) -> Frame:
        if not self.fits(width):
            raise ValueError(f"CEL frame does not decode at width {width}")
        return Frame.from_bottom_up(self.pixels, self.mask, width)


def scan_cel_frame(raw: bytes, allow_header: bool = True) -> CelScan:
    src = raw
    if allow_header and len(raw) >= CEL_FRAME_HEADER_BYTES and u16(raw, 0) == CEL_FRAME_HEADER_BYTES:
        src = raw[CEL_FRAME_HEADER_BYTES:]
    pixels, mask = bytearray(), bytearray()
    starts: list[int] = []
    ends: list[int] = []
    i, pos, n = 0, 0, len(src)
    while i < n:
        control = src[i]
        i += 1
        if control >= 0x80:
            run = 256 - control
            pixels += bytes(run)
            mask += bytes(run)
        else:
            run = control
            if i + run > n:
                raise ValueError("CEL pixel run extends past the end of the frame")
            pixels += src[i : i + run]
            mask += b"\x01" * run
            i += run
        if run:
            starts.append(pos)
            ends.append(pos + run)
        pos += run
    return CelScan(bytes(pixels), bytes(mask), np.array(starts, np.int64), np.array(ends, np.int64))


def decode_cel_frame(raw: bytes, width: int, allow_header: bool = True) -> Frame:
    return scan_cel_frame(raw, allow_header).to_frame(width)
```

- [ ] **Step 5: Run to verify pass**

Run: `uv run pytest tests/test_cel.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/dtx/formats/cel.py tests/builders.py tests/test_cel.py
git commit -m "feat: add CEL frame scanner and decoder"
```

---

### Task 6: CL2 frame scanner, decoder and skip-table check

**Files:**
- Create: `src/dtx/formats/cl2.py`
- Modify: `tests/builders.py` (append)
- Test: `tests/test_cl2.py`

**Interfaces:**
- Consumes: `Frame`, `u16`.
- Produces: `scan_cl2_frame(raw: bytes) -> Cl2Scan`; `Cl2Scan.fits(width, strict=True) -> bool`; `Cl2Scan.to_frame(width) -> Frame`; `decode_cl2_frame(raw, width) -> Frame`. Test helper `builders.cl2_frame(rows) -> bytes`.

CL2 facts (DevilutionX `cl2_to_clx.cpp`, `clx_decode.hpp`): every frame starts with a header whose first u16 is its size (10 in practice: size + 4 u16 skip offsets). Pixels are stored bottom row first. Control `c < 0x80`: `c` transparent pixels. `0x80 <= c <= 0xBE`: fill run of `0xBF - c` copies of the next byte. `c >= 0xBF`: `256 - c` literal bytes follow. **Runs may cross rows.** Skip offsets k = 0..3 point (relative to frame start) at the byte where row 32·(k+1) from the bottom begins; 0 = absent. This plan assumes the encoder breaks runs at those rows; Task 18 checks the assumption on real data.

- [ ] **Step 1: Append builder**

Append to `tests/builders.py`:
```python
def cl2_frame(rows: list[list[int | None]]) -> bytes:
    """Encode rows (top row first; None = transparent) as a CL2 frame with a skip table.

    Runs may cross rows but never cross a 32-row boundary, so skip offsets are exact."""
    width = len(rows[0]) if rows else 0
    flat = [p for row in reversed(rows) for p in row]
    boundaries = sorted(32 * k * width for k in (1, 2, 3, 4) if width and 32 * k * width < len(flat))
    body = bytearray()
    boundary_offsets: dict[int, int] = {}

    def cap(i: int, limit: int) -> int:
        nxt = next((b for b in boundaries if b > i), len(flat))
        return min(limit, nxt - i)

    i = 0
    while i < len(flat):
        if i in boundaries:
            boundary_offsets[i] = len(body)
        n = 1
        if flat[i] is None:
            while n < cap(i, 127) and flat[i + n] is None:
                n += 1
            body.append(n)
        else:
            while n < cap(i, 63) and flat[i + n] == flat[i]:
                n += 1
            if n >= 3:
                body += bytes([0xBF - n, flat[i]])
            else:
                n = 1
                while n < cap(i, 65) and flat[i + n] is not None:
                    n += 1
                body.append(256 - n)
                body += bytes(flat[i : i + n])
        i += n
    skip = [10 + boundary_offsets[b] if b in boundary_offsets else 0 for b in
            (32 * k * width for k in (1, 2, 3, 4))]
    return struct.pack("<5H", 10, *skip) + bytes(body)
```

- [ ] **Step 2: Write the failing tests**

`tests/test_cl2.py`:
```python
import numpy as np
import pytest

from builders import cl2_frame
from dtx.formats.cl2 import decode_cl2_frame, scan_cl2_frame


def test_decode_transparent_fill_and_literal():
    rows = [[None, None, 9, 9, 9], [1, 2, None, 4, 5]]
    frame = decode_cl2_frame(cl2_frame(rows), 5)
    np.testing.assert_array_equal(frame.indices, [[0, 0, 9, 9, 9], [1, 2, 0, 4, 5]])
    np.testing.assert_array_equal(frame.opaque[0], [False, False, True, True, True])


def test_runs_may_cross_rows():
    # one literal run of 6 covering two rows of width 3
    raw = bytes([10, 0, 0, 0, 0, 0, 0, 0, 0, 0, 256 - 6, 1, 2, 3, 4, 5, 6])
    frame = decode_cl2_frame(raw, 3)
    np.testing.assert_array_equal(frame.indices, [[4, 5, 6], [1, 2, 3]])


def test_pixel_count_not_multiple_of_width_raises():
    with pytest.raises(ValueError):
        decode_cl2_frame(cl2_frame([[1, 2, 3]]), 2)


def test_skip_table_pins_width():
    rows = [[(x + y) % 7 + 1 for x in range(4)] for y in range(40)]
    scan = scan_cl2_frame(cl2_frame(rows))
    assert scan.fits(4)
    assert not scan.fits(2)  # 80 rows: row-32 offset would be at 64 pixels, not 128
    assert not scan.fits(8)  # 20 rows: offset at 128 pixels expected 256
    assert scan.fits(2, strict=False)  # divisibility alone is ambiguous


def test_empty_frame():
    assert decode_cl2_frame(b"", 8).height == 0


def test_fill_missing_colour_raises():
    with pytest.raises(ValueError):
        scan_cl2_frame(bytes([10, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0xBE]))


def test_header_size_past_end_raises():
    with pytest.raises(ValueError):
        scan_cl2_frame(bytes([40, 0, 1]))
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/test_cl2.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 4: Implement**

`src/dtx/formats/cl2.py`:
```python
from __future__ import annotations

from dataclasses import dataclass, field

from dtx.binary import u16
from dtx.formats.frame import Frame

SKIP_TABLE_HEADER_BYTES = 10


@dataclass(frozen=True, eq=False)
class Cl2Scan:
    """Width-independent decode of a CL2 frame."""

    pixels: bytes
    mask: bytes
    run_starts: dict[int, int] = field(default_factory=dict)  # byte offset -> pixels before it
    skip_offsets: tuple[int, ...] = ()

    def fits(self, width: int, strict: bool = True) -> bool:
        if width <= 0 or len(self.pixels) % width:
            return False
        if strict:
            for k, offset in enumerate(self.skip_offsets):
                if offset and self.run_starts.get(offset) != 32 * (k + 1) * width:
                    return False
        return True

    def to_frame(self, width: int) -> Frame:
        if not self.fits(width, strict=False):
            raise ValueError(f"CL2 frame has {len(self.pixels)} pixels, not a multiple of width {width}")
        return Frame.from_bottom_up(self.pixels, self.mask, width)


def scan_cl2_frame(raw: bytes) -> Cl2Scan:
    if not raw:
        return Cl2Scan(b"", b"", {0: 0}, ())
    start = u16(raw, 0)
    if start > len(raw):
        raise ValueError("CL2 frame header size exceeds frame length")
    skip = tuple(u16(raw, 2 + 2 * k) for k in range(4)) if start >= SKIP_TABLE_HEADER_BYTES else ()
    pixels, mask = bytearray(), bytearray()
    run_starts: dict[int, int] = {}
    i, n = start, len(raw)
    while i < n:
        run_starts[i] = len(pixels)
        control = raw[i]
        i += 1
        if control < 0x80:
            pixels += bytes(control)
            mask += bytes(control)
        elif control <= 0xBE:
            if i >= n:
                raise ValueError("CL2 fill run is missing its colour byte")
            run = 0xBF - control
            pixels += bytes([raw[i]]) * run
            mask += b"\x01" * run
            i += 1
        else:
            run = 256 - control
            if i + run > n:
                raise ValueError("CL2 pixel run extends past the end of the frame")
            pixels += raw[i : i + run]
            mask += b"\x01" * run
            i += run
    run_starts[n] = len(pixels)
    return Cl2Scan(bytes(pixels), bytes(mask), run_starts, skip)


def decode_cl2_frame(raw: bytes, width: int) -> Frame:
    return scan_cl2_frame(raw).to_frame(width)
```

- [ ] **Step 5: Run to verify pass**

Run: `uv run pytest tests/test_cl2.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/dtx/formats/cl2.py tests/builders.py tests/test_cl2.py
git commit -m "feat: add CL2 frame scanner with skip-table width check"
```

---

### Task 7: Frame-width resolution

**Files:**
- Create: `src/dtx/formats/width.py`
- Test: `tests/test_width.py`

**Interfaces:**
- Consumes: `scan_cel_frame`, `CelScan` (Task 5); `scan_cl2_frame`, `Cl2Scan` (Task 6).
- Produces: `scan_frame(fmt: str, raw: bytes) -> CelScan | Cl2Scan` (`fmt` is `"cel"` or `"cl2"`); `resolve_widths(scans, hint) -> WidthResult`; `WidthResult(widths: tuple[int, ...], source: str, candidates: tuple[int, ...])` with `source` in `"table" | "inferred" | "inferred_per_frame"`; `candidate_order() -> list[int]`.

Rules (spec §4.3): a table hint (int, or one width per frame) is accepted only if every frame fits it strictly. Otherwise try `candidate_order()` for a width that fits every frame; first one wins, all fitting widths are recorded. If no common width exists, infer each frame on its own (`inferred_per_frame`). If some frame fits no width at all, raise `ValueError`.

- [ ] **Step 1: Write the failing tests**

`tests/test_width.py`:
```python
import pytest

from builders import cel_frame, cl2_frame
from dtx.formats.width import candidate_order, resolve_widths, scan_frame


def rows(width, height, value=5):
    return [[value + (x % 3) for x in range(width)] for _ in range(height)]


def test_candidate_order_prefers_common_widths_and_covers_range():
    order = candidate_order()
    assert order[:4] == [32, 64, 96, 128]
    assert sorted(order) == list(range(1, 641))


def test_table_width_accepted():
    scans = [scan_frame("cel", cel_frame(rows(64, 3)))]
    result = resolve_widths(scans, 64)
    assert result.widths == (64,) and result.source == "table"


def test_wrong_table_width_falls_back_to_inference():
    scans = [scan_frame("cl2", cl2_frame(rows(96, 40)))]
    result = resolve_widths(scans, 128)
    assert result.source == "inferred"
    assert result.widths == (96,)
    assert 96 in result.candidates


def test_per_frame_table_widths():
    scans = [scan_frame("cel", cel_frame(rows(28, 2))), scan_frame("cel", cel_frame(rows(56, 2)))]
    result = resolve_widths(scans, [28, 56])
    assert result.widths == (28, 56) and result.source == "table"


def test_per_frame_inference_when_no_common_width():
    # Review Focus 1: frames of different widths, no table
    a = [[None] * 30 + [1, 2]]  # width 32: transparent run of 30 then 2 pixels
    b = [[1] * 5 + [None] * 50 + [2]]  # width 56
    scans = [scan_frame("cel", cel_frame(a)), scan_frame("cel", cel_frame(b))]
    result = resolve_widths(scans, None)
    assert result.source == "inferred_per_frame"
    assert result.widths == (32, 56)


def test_unknown_format_rejected():
    with pytest.raises(ValueError):
        scan_frame("bmp", b"")
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_width.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`src/dtx/formats/width.py`:
```python
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from dtx.formats.cel import CelScan, scan_cel_frame
from dtx.formats.cl2 import Cl2Scan, scan_cl2_frame

MAX_WIDTH = 640
# Most common first, then constant widths used by DevilutionX (Source/*.cpp LoadCel calls).
PREFERRED_WIDTHS = (
    32, 64, 96, 128, 160, 180, 192, 256,
    28, 56, 12, 33, 37, 48, 61, 71, 88, 261, 271, 296, 430, 591, 640,
)

Scan = CelScan | Cl2Scan


@dataclass(frozen=True)
class WidthResult:
    widths: tuple[int, ...]
    source: str
    candidates: tuple[int, ...] = ()


def candidate_order() -> list[int]:
    preferred = list(PREFERRED_WIDTHS)
    return preferred + [w for w in range(1, MAX_WIDTH + 1) if w not in preferred]


def scan_frame(fmt: str, raw: bytes) -> Scan:
    if fmt == "cel":
        return scan_cel_frame(raw)
    if fmt == "cl2":
        return scan_cl2_frame(raw)
    raise ValueError(f"unknown sprite format {fmt!r}")


def resolve_widths(scans: Sequence[Scan], hint: int | Sequence[int] | None) -> WidthResult:
    count = len(scans)
    if hint is not None:
        widths = tuple(int(w) for w in hint) if isinstance(hint, (list, tuple)) else (int(hint),) * count
        if len(widths) == count and all(s.fits(w) for s, w in zip(scans, widths)):
            return WidthResult(widths, "table")

    order = candidate_order()
    common = tuple(w for w in order if all(s.fits(w) for s in scans))
    if common:
        return WidthResult((common[0],) * count, "inferred", common)

    per_frame = []
    for index, scan in enumerate(scans):
        width = next((w for w in order if scan.fits(w)), None)
        if width is None:
            raise ValueError(f"no width between 1 and {MAX_WIDTH} fits frame {index}")
        per_frame.append(width)
    return WidthResult(tuple(per_frame), "inferred_per_frame")
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_width.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/dtx/formats/width.py tests/test_width.py
git commit -m "feat: resolve sprite frame widths from tables or inference"
```

---

### Task 8: Dungeon level-cell decoder

**Files:**
- Create: `src/dtx/formats/levelcel.py`
- Test: `tests/test_levelcel.py`

**Interfaces:**
- Consumes: `Frame`, `scan_cel_frame`.
- Produces: `TileType` (IntEnum: `SQUARE=0, TRANSPARENT_SQUARE=1, LEFT_TRIANGLE=2, RIGHT_TRIANGLE=3, LEFT_TRAPEZOID=4, RIGHT_TRAPEZOID=5`); `decode_level_cell(raw: bytes, tile_type: TileType) -> Frame` (always 32×32).

Facts (DevilutionX `Source/levels/dun_tile.hpp`, `reencode_dun_cels.cpp`): all types store the bottom row first. Square: 1024 raw bytes. Transparent square: CEL RLE at width 32, never with a frame header. Triangles: 31 rows i = 0..30 from the bottom, row width `2(i+1)` for i ≤ 15 else `2(31-i)`; left triangle pixels are right-aligned (x = 32 − w) with 2 padding bytes **before** each even row; right triangle pixels are left-aligned with 2 padding bytes **after** each even row; total 544 bytes; the top row (array row 0) stays transparent. Trapezoids: the first 16 triangle rows (with padding, 288 bytes) followed by 16 full 32-pixel rows (512 bytes); total 800.

- [ ] **Step 1: Write the failing tests**

`tests/test_levelcel.py`:
```python
import numpy as np
import pytest

from builders import cel_frame
from dtx.formats.levelcel import TileType, decode_level_cell


def triangle_bytes(left: bool, rows: int = 31) -> bytes:
    out = bytearray()
    for i in range(rows):
        w = 2 * (i + 1) if i < 16 else 2 * (31 - i)
        if left and i % 2 == 0:
            out += b"\0\0"
        out += bytes([i + 1]) * w
        if not left and i % 2 == 0:
            out += b"\0\0"
    return bytes(out)


def test_square_is_bottom_up():
    raw = bytes(range(32)) + bytes([200]) * (1024 - 32)
    cell = decode_level_cell(raw, TileType.SQUARE)
    np.testing.assert_array_equal(cell.indices[31], list(range(32)))
    assert cell.opaque.all()


def test_left_triangle_geometry():
    raw = triangle_bytes(left=True)
    assert len(raw) == 544
    cell = decode_level_cell(raw, TileType.LEFT_TRIANGLE)
    np.testing.assert_array_equal(np.nonzero(cell.opaque[31])[0], [30, 31])  # bottom row, 2 px, right-aligned
    assert cell.opaque[16].all()  # i = 15, full width
    assert not cell.opaque[0].any()  # top row empty
    assert set(np.unique(cell.indices[31][cell.opaque[31]])) == {1}  # padding never shown


def test_right_triangle_geometry():
    cell = decode_level_cell(triangle_bytes(left=False), TileType.RIGHT_TRIANGLE)
    np.testing.assert_array_equal(np.nonzero(cell.opaque[31])[0], [0, 1])
    np.testing.assert_array_equal(np.nonzero(cell.opaque[1])[0], [0, 1])  # i = 30


def test_left_trapezoid_geometry():
    raw = triangle_bytes(left=True, rows=16) + bytes([100]) * 512
    assert len(raw) == 800
    cell = decode_level_cell(raw, TileType.LEFT_TRAPEZOID)
    assert cell.opaque[:16].all()
    assert (cell.indices[:16] == 100).all()
    np.testing.assert_array_equal(np.nonzero(cell.opaque[31])[0], [30, 31])


def test_transparent_square_never_reads_header():
    # Review Focus 3: data starting 0A 00 is a 10-pixel literal run, not a frame header
    rows = [[0] * 10 + [None] * 22 for _ in range(32)]
    raw = cel_frame(rows)
    assert raw[:2] == b"\x0a\x00"
    cell = decode_level_cell(raw, TileType.TRANSPARENT_SQUARE)
    assert cell.opaque[:, :10].all() and not cell.opaque[:, 10:].any()


def test_wrong_size_rejected():
    with pytest.raises(ValueError):
        decode_level_cell(bytes(543), TileType.LEFT_TRIANGLE)
    with pytest.raises(ValueError):
        decode_level_cell(bytes(1000), TileType.SQUARE)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_levelcel.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`src/dtx/formats/levelcel.py`:
```python
from enum import IntEnum

import numpy as np

from dtx.formats.cel import scan_cel_frame
from dtx.formats.frame import Frame

CELL = 32
TRIANGLE_BYTES = 544
TRAPEZOID_BYTES = 800


class TileType(IntEnum):
    SQUARE = 0
    TRANSPARENT_SQUARE = 1
    LEFT_TRIANGLE = 2
    RIGHT_TRIANGLE = 3
    LEFT_TRAPEZOID = 4
    RIGHT_TRAPEZOID = 5


def _row_width(i: int) -> int:
    return 2 * (i + 1) if i < 16 else 2 * (31 - i)


def _triangle_rows(raw: bytes, left: bool, rows: int, idx: np.ndarray, op: np.ndarray) -> int:
    pos = 0
    for i in range(rows):
        w = _row_width(i)
        if left and i % 2 == 0:
            pos += 2
        x0 = CELL - w if left else 0
        y = CELL - 1 - i
        idx[y, x0 : x0 + w] = np.frombuffer(raw, np.uint8, w, pos)
        op[y, x0 : x0 + w] = True
        pos += w
        if not left and i % 2 == 0:
            pos += 2
    return pos


def decode_level_cell(raw: bytes, tile_type: TileType) -> Frame:
    idx = np.zeros((CELL, CELL), np.uint8)
    op = np.zeros((CELL, CELL), bool)
    if tile_type == TileType.SQUARE:
        if len(raw) != CELL * CELL:
            raise ValueError(f"square cell must be 1024 bytes, got {len(raw)}")
        return Frame(np.frombuffer(raw, np.uint8).reshape(CELL, CELL)[::-1].copy(), ~op)
    if tile_type == TileType.TRANSPARENT_SQUARE:
        frame = scan_cel_frame(raw, allow_header=False).to_frame(CELL)
        if frame.height != CELL:
            raise ValueError(f"transparent square cell has {frame.height} rows, expected 32")
        return frame
    left = tile_type in (TileType.LEFT_TRIANGLE, TileType.LEFT_TRAPEZOID)
    if tile_type in (TileType.LEFT_TRIANGLE, TileType.RIGHT_TRIANGLE):
        if len(raw) != TRIANGLE_BYTES:
            raise ValueError(f"triangle cell must be {TRIANGLE_BYTES} bytes, got {len(raw)}")
        _triangle_rows(raw, left, 31, idx, op)
        return Frame(idx, op)
    if len(raw) != TRAPEZOID_BYTES:
        raise ValueError(f"trapezoid cell must be {TRAPEZOID_BYTES} bytes, got {len(raw)}")
    pos = _triangle_rows(raw, left, 16, idx, op)
    top = np.frombuffer(raw, np.uint8, 16 * CELL, pos).reshape(16, CELL)[::-1]
    idx[:16] = top
    op[:16] = True
    return Frame(idx, op)
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_levelcel.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/dtx/formats/levelcel.py tests/test_levelcel.py
git commit -m "feat: decode the six dungeon level-cell types"
```

---

### Task 9: MIN/TIL/SOL/DUN parsers and column composition

**Files:**
- Create: `src/dtx/formats/tileset.py`
- Modify: `tests/builders.py` (append)
- Test: `tests/test_tileset.py`

**Interfaces:**
- Consumes: `Frame`, `u16`.
- Produces: `CellRef(frame: int, tile_type: int)` with `.empty`; `parse_min(data, cells_per_column) -> list[list[CellRef]]`; `parse_til(data) -> list[tuple[int,int,int,int]]` (top, right, left, bottom; 0-based column ids); `parse_sol(data) -> list[dict[str,bool]]`; `Dun(width, height, tiles: np.ndarray[h,w] uint16)` and `parse_dun(data) -> Dun` (1-based tile ids, 0 = empty); `cell_types(columns) -> dict[int,int]`; `cell_users(columns) -> dict[int, list[int]]`; `compose_column(cells, cell_frames: Mapping[int, Frame]) -> Frame`. Test helpers `builders.min_bytes`, `builders.til_bytes`, `builders.dun_bytes`.

Facts (DevilutionX `dun_tile_data.cpp` `SetDungeonMicros`, `gendung.cpp`): a MIN column is `cells_per_column` u16 values stored as (left, right) pairs **top row first**; value bits `& 0xFFF` = 1-based level-CEL frame (0 = empty), `(v & 0x7000) >> 12` = tile type. TIL = 4 u16 per tile (top, right, left, bottom) 0-based column ids. SOL = 1 byte per column: solid 1, block_light 2, block_missile 4, transparent 8, transparent_left 16, transparent_right 32, trap 128. DUN = u16 width, u16 height, then width·height u16 tile ids (row-major, 1-based), then optional layers (ignored).

- [ ] **Step 1: Append builders**

Append to `tests/builders.py`:
```python
def min_bytes(columns: list[list[tuple[int, int]]]) -> bytes:
    """columns: per column, (frame, tile_type) per cell in file order."""
    values = [(t << 12) | f for col in columns for f, t in col]
    return struct.pack(f"<{len(values)}H", *values)


def til_bytes(tiles: list[tuple[int, int, int, int]]) -> bytes:
    flat = [v for t in tiles for v in t]
    return struct.pack(f"<{len(flat)}H", *flat)


def dun_bytes(tiles: list[list[int]]) -> bytes:
    h, w = len(tiles), len(tiles[0])
    flat = [v for row in tiles for v in row]
    return struct.pack(f"<2H{len(flat)}H", w, h, *flat)
```

- [ ] **Step 2: Write the failing tests**

`tests/test_tileset.py`:
```python
import numpy as np
import pytest

from builders import dun_bytes, min_bytes, til_bytes
from dtx.formats.frame import Frame
from dtx.formats.tileset import (
    cell_types, cell_users, compose_column, parse_dun, parse_min, parse_sol, parse_til,
)


def solid(value):
    return Frame(np.full((32, 32), value, np.uint8), np.ones((32, 32), bool))


def test_parse_min_splits_frame_and_type():
    data = min_bytes([[(1, 0), (2, 4), (0, 0), (3, 1)], [(0, 0)] * 4])
    columns = parse_min(data, 4)
    assert len(columns) == 2
    assert columns[0][1].frame == 2 and columns[0][1].tile_type == 4
    assert columns[0][2].empty


def test_parse_min_rejects_partial_column():
    with pytest.raises(ValueError):
        parse_min(min_bytes([[(1, 0)] * 3]), 4)


def test_parse_til_and_sol():
    assert parse_til(til_bytes([(0, 1, 2, 3)])) == [(0, 1, 2, 3)]
    sol = parse_sol(bytes([1 | 8, 128]))
    assert sol[0]["solid"] and sol[0]["transparent"] and not sol[0]["trap"]
    assert sol[1]["trap"]


def test_parse_dun():
    dun = parse_dun(dun_bytes([[1, 2, 0], [4, 5, 6]]) + b"extra layers ignored")
    assert (dun.width, dun.height) == (3, 2)
    np.testing.assert_array_equal(dun.tiles, [[1, 2, 0], [4, 5, 6]])


def test_parse_dun_truncated():
    with pytest.raises(ValueError):
        parse_dun(dun_bytes([[1, 2]])[:-2])


def test_compose_column_places_top_row_first():
    columns = parse_min(min_bytes([[(1, 0), (0, 0), (0, 0), (2, 0)]]), 4)
    frame = compose_column(columns[0], {1: solid(10), 2: solid(20)})
    assert (frame.width, frame.height) == (64, 64)
    assert (frame.indices[:32, :32] == 10).all()  # slot 0: top-left
    assert (frame.indices[32:, 32:] == 20).all()  # slot 3: bottom-right
    assert not frame.opaque[:32, 32:].any()


def test_compose_column_missing_cell_raises():
    columns = parse_min(min_bytes([[(9, 0), (0, 0)]]), 2)
    with pytest.raises(ValueError):
        compose_column(columns[0], {})


def test_cell_types_and_users():
    columns = parse_min(min_bytes([[(1, 0), (2, 1)], [(1, 0), (0, 0)]]), 2)
    assert cell_types(columns) == {1: 0, 2: 1}
    assert cell_users(columns) == {1: [0, 1], 2: [0]}


def test_cell_types_conflict_raises():
    columns = parse_min(min_bytes([[(1, 0), (1, 2)]]), 2)
    with pytest.raises(ValueError):
        cell_types(columns)
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/test_tileset.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 4: Implement**

`src/dtx/formats/tileset.py`:
```python
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from dtx.binary import u16
from dtx.formats.frame import Frame

CELL = 32
SOL_FLAGS = {
    "solid": 1, "block_light": 2, "block_missile": 4, "transparent": 8,
    "transparent_left": 16, "transparent_right": 32, "trap": 128,
}


@dataclass(frozen=True)
class CellRef:
    frame: int  # 1-based level-CEL frame, 0 = empty
    tile_type: int

    @property
    def empty(self) -> bool:
        return self.frame == 0


@dataclass(frozen=True, eq=False)
class Dun:
    width: int
    height: int
    tiles: np.ndarray  # (height, width) uint16, 1-based, 0 = empty


def parse_min(data: bytes, cells_per_column: int) -> list[list[CellRef]]:
    if len(data) % (2 * cells_per_column):
        raise ValueError(f"MIN size {len(data)} is not a multiple of {2 * cells_per_column}")
    values = np.frombuffer(data, "<u2").astype(int)
    return [
        [CellRef(v & 0xFFF, (v & 0x7000) >> 12) for v in values[c : c + cells_per_column]]
        for c in range(0, len(values), cells_per_column)
    ]


def parse_til(data: bytes) -> list[tuple[int, int, int, int]]:
    if len(data) % 8:
        raise ValueError(f"TIL size {len(data)} is not a multiple of 8")
    return [tuple(int(v) for v in row) for row in np.frombuffer(data, "<u2").reshape(-1, 4)]


def parse_sol(data: bytes) -> list[dict[str, bool]]:
    return [{name: bool(b & bit) for name, bit in SOL_FLAGS.items()} for b in data]


def parse_dun(data: bytes) -> Dun:
    width, height = u16(data, 0), u16(data, 2)
    if len(data) < 4 + 2 * width * height:
        raise ValueError(f"DUN truncated: {width}x{height} tiles need {4 + 2 * width * height} bytes")
    tiles = np.frombuffer(data, "<u2", count=width * height, offset=4).reshape(height, width).copy()
    return Dun(width, height, tiles)


def cell_types(columns: Sequence[Sequence[CellRef]]) -> dict[int, int]:
    types: dict[int, int] = {}
    for column in columns:
        for ref in column:
            if ref.empty:
                continue
            if types.setdefault(ref.frame, ref.tile_type) != ref.tile_type:
                raise ValueError(f"cell {ref.frame} is used with tile types {types[ref.frame]} and {ref.tile_type}")
    return types


def cell_users(columns: Sequence[Sequence[CellRef]]) -> dict[int, list[int]]:
    users: dict[int, list[int]] = {}
    for column_id, column in enumerate(columns):
        for ref in column:
            if not ref.empty and column_id not in users.setdefault(ref.frame, []):
                users[ref.frame].append(column_id)
    return users


def compose_column(cells: Sequence[CellRef], cell_frames: Mapping[int, Frame]) -> Frame:
    rows = len(cells) // 2
    idx = np.zeros((rows * CELL, 2 * CELL), np.uint8)
    op = np.zeros_like(idx, bool)
    for slot, ref in enumerate(cells):
        if ref.empty:
            continue
        if ref.frame not in cell_frames:
            raise ValueError(f"column references missing cell frame {ref.frame}")
        cell = cell_frames[ref.frame]
        row, side = divmod(slot, 2)
        y, x = row * CELL, side * CELL
        idx[y : y + CELL, x : x + CELL][cell.opaque] = cell.indices[cell.opaque]
        op[y : y + CELL, x : x + CELL] |= cell.opaque
    return Frame(idx, op)
```

- [ ] **Step 5: Run to verify pass**

Run: `uv run pytest tests/test_tileset.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/dtx/formats/tileset.py tests/builders.py tests/test_tileset.py
git commit -m "feat: parse MIN/TIL/SOL/DUN and compose tileset columns"
```

---

### Task 10: Isometric placement, composition and crop boxes

**Files:**
- Create: `src/dtx/formats/render.py`
- Test: `tests/test_render.py`

**Interfaces:**
- Consumes: `Frame`.
- Produces: `Placement(column: int, x: int, y: int)`; `tile_pieces(tile_ids: np.ndarray[h,w] int (0-based, -1 empty), til) -> np.ndarray[2h,2w] int32`; `place_pieces(pieces, column_height: int) -> tuple[list[Placement], tuple[int,int]]` (back-to-front order, canvas `(width, height)`); `compose(placements, size, columns: Sequence[Frame]) -> Frame`; `crop_box(p: Placement, column_height: int, scale: int) -> tuple[int,int,int,int]` (x0, y0, x1, y1).

Geometry (DevilutionX `gendung.cpp` `DRLG_LPass3`, `scrollrt.cpp` `DrawCell`): megatile at (i, j) fills pieces (2i,2j)=top, (2i+1,2j)=right, (2i,2j+1)=left, (2i+1,2j+1)=bottom. Piece (px, py) has screen origin `sx = (px − py)·32`, `sy = (px + py)·16`; its 64-px-wide column's bottom 32 px hold the floor diamond, so the column image's top-left is `(sx, sy + 32 − H)`. Draw order is increasing `px + py`, then `px`.

- [ ] **Step 1: Write the failing tests**

`tests/test_render.py`:
```python
import numpy as np
import pytest

from dtx.formats.frame import Frame
from dtx.formats.render import Placement, compose, crop_box, place_pieces, tile_pieces


def test_tile_pieces_layout():
    pieces = tile_pieces(np.array([[0, -1]]), [(10, 11, 12, 13)])
    np.testing.assert_array_equal(pieces, [[10, 11, -1, -1], [12, 13, -1, -1]])


def test_tile_pieces_out_of_range():
    with pytest.raises(ValueError):
        tile_pieces(np.array([[3]]), [(0, 0, 0, 0)])


def test_single_tile_placement():
    pieces = tile_pieces(np.array([[0]]), [(0, 1, 2, 3)])
    placements, size = place_pieces(pieces, 64)
    assert [p.column for p in placements] == [0, 2, 1, 3]  # top, left, right, bottom
    assert placements == [Placement(0, 32, 0), Placement(2, 0, 16), Placement(1, 64, 16), Placement(3, 32, 32)]
    assert size == (128, 96)  # 2 columns wide, column height + 32


def test_empty_grid():
    assert place_pieces(np.full((2, 2), -1), 64) == ([], (0, 0))


def test_compose_later_placements_overwrite():
    a = Frame(np.full((2, 2), 1, np.uint8), np.ones((2, 2), bool))
    b = Frame(np.array([[2, 2], [2, 2]], np.uint8), np.array([[True, False], [False, False]]))
    out = compose([Placement(0, 0, 0), Placement(1, 1, 0)], (3, 2), [a, b])
    np.testing.assert_array_equal(out.indices, [[1, 2, 0], [1, 1, 0]])
    np.testing.assert_array_equal(out.opaque, [[True, True, False], [True, True, False]])


def test_crop_box_scales():
    p = Placement(5, 32, 16)
    assert crop_box(p, 160, 1) == (32, 16, 96, 176)
    assert crop_box(p, 160, 4) == (128, 64, 384, 704)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_render.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`src/dtx/formats/render.py`:
```python
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from dtx.formats.frame import Frame

COLUMN_WIDTH = 64
HALF_WIDTH = 32
HALF_HEIGHT = 16
FLOOR_HEIGHT = 32


@dataclass(frozen=True)
class Placement:
    column: int
    x: int
    y: int


def tile_pieces(tile_ids: np.ndarray, til: Sequence[tuple[int, int, int, int]]) -> np.ndarray:
    h, w = tile_ids.shape
    pieces = np.full((2 * h, 2 * w), -1, np.int32)
    for j in range(h):
        for i in range(w):
            t = int(tile_ids[j, i])
            if t < 0:
                continue
            if t >= len(til):
                raise ValueError(f"tile id {t + 1} at ({i}, {j}) is beyond the {len(til)} tiles in TIL")
            top, right, left, bottom = til[t]
            pieces[2 * j, 2 * i] = top
            pieces[2 * j, 2 * i + 1] = right
            pieces[2 * j + 1, 2 * i] = left
            pieces[2 * j + 1, 2 * i + 1] = bottom
    return pieces


def place_pieces(pieces: np.ndarray, column_height: int) -> tuple[list[Placement], tuple[int, int]]:
    raw = []
    rows, cols = pieces.shape
    for py in range(rows):
        for px in range(cols):
            column = int(pieces[py, px])
            if column < 0:
                continue
            sx = (px - py) * HALF_WIDTH
            sy = (px + py) * HALF_HEIGHT + FLOOR_HEIGHT - column_height
            raw.append((px + py, px, column, sx, sy))
    if not raw:
        return [], (0, 0)
    raw.sort()
    min_x = min(r[3] for r in raw)
    min_y = min(r[4] for r in raw)
    placements = [Placement(c, sx - min_x, sy - min_y) for _, _, c, sx, sy in raw]
    width = max(p.x for p in placements) + COLUMN_WIDTH
    height = max(p.y for p in placements) + column_height
    return placements, (width, height)


def compose(placements: Sequence[Placement], size: tuple[int, int], columns: Sequence[Frame]) -> Frame:
    width, height = size
    idx = np.zeros((height, width), np.uint8)
    op = np.zeros((height, width), bool)
    for p in placements:
        col = columns[p.column]
        ys, xs = slice(p.y, p.y + col.height), slice(p.x, p.x + col.width)
        idx[ys, xs][col.opaque] = col.indices[col.opaque]
        op[ys, xs] |= col.opaque
    return Frame(idx, op)


def crop_box(p: Placement, column_height: int, scale: int) -> tuple[int, int, int, int]:
    """Crop rectangle of a placed column in a layout regenerated at integer scale."""
    x0, y0 = p.x * scale, p.y * scale
    return x0, y0, x0 + COLUMN_WIDTH * scale, y0 + column_height * scale
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_render.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/dtx/formats/render.py tests/test_render.py
git commit -m "feat: isometric placement, composition and crop boxes"
```

---

### Task 11: PNG/JSON writers and verification

**Files:**
- Create: `src/dtx/export.py`, `src/dtx/verify.py`
- Test: `tests/test_export.py`

**Interfaces:**
- Consumes: `Frame`.
- Produces:
  - `export.rgba(frame, palette) -> np.ndarray[h,w,4]`
  - `export.write_frame_pair(frame, palette, directory: Path, stem: str) -> dict` returning `{"w", "h", "png", "idx"}` (file names relative to `directory`) or `{"w", "h", "empty": True}` for empty frames (no files written).
  - `export.write_sheet(groups: Sequence[Sequence[Frame]], palette, path: Path) -> bool` (False when every frame is empty).
  - `export.write_swatch(palette, path: Path) -> None` (256×256 PNG, 16×16 blocks).
  - `export.write_json(path: Path, obj) -> None`.
  - `verify.read_index_png(path) -> Frame`; `verify.verify_written(frame, idx_path) -> bool`.

- [ ] **Step 1: Write the failing tests**

`tests/test_export.py`:
```python
import json

import numpy as np
from PIL import Image

from dtx.export import rgba, write_frame_pair, write_json, write_sheet, write_swatch
from dtx.formats.frame import Frame
from dtx.verify import read_index_png, verify_written

PAL = np.stack([np.arange(256)] * 3, axis=1).astype(np.uint8)
FRAME = Frame(np.array([[1, 2], [3, 4]], np.uint8), np.array([[True, False], [True, True]]))


def test_rgba_applies_palette_and_alpha():
    out = rgba(FRAME, PAL)
    assert tuple(out[0, 0]) == (1, 1, 1, 255)
    assert out[0, 1, 3] == 0


def test_pair_roundtrip(tmp_path):
    rec = write_frame_pair(FRAME, PAL, tmp_path / "d0", "f000")
    assert rec == {"w": 2, "h": 2, "png": "f000.png", "idx": "f000.idx.png"}
    assert Image.open(tmp_path / "d0" / "f000.png").mode == "RGBA"
    assert read_index_png(tmp_path / "d0" / "f000.idx.png").same_pixels(FRAME)
    assert verify_written(FRAME, tmp_path / "d0" / "f000.idx.png")


def test_verify_detects_one_pixel_change(tmp_path):
    write_frame_pair(FRAME, PAL, tmp_path, "f")
    path = tmp_path / "f.idx.png"
    data = np.asarray(Image.open(path)).copy()
    data[1, 1, 0] = 99
    Image.fromarray(data).save(path)
    assert not verify_written(FRAME, path)


def test_empty_frame_writes_no_png(tmp_path):
    # Review Focus 2
    rec = write_frame_pair(Frame.empty(32, 0), PAL, tmp_path, "f000")
    assert rec == {"w": 32, "h": 0, "empty": True}
    assert not list(tmp_path.iterdir())


def test_sheet_rows_per_group(tmp_path):
    ok = write_sheet([[FRAME, FRAME, FRAME], [FRAME]], PAL, tmp_path / "sheet.png")
    assert ok
    assert Image.open(tmp_path / "sheet.png").size == (6, 4)


def test_sheet_all_empty(tmp_path):
    assert not write_sheet([[Frame.empty()]], PAL, tmp_path / "sheet.png")
    assert not (tmp_path / "sheet.png").exists()


def test_swatch(tmp_path):
    write_swatch(PAL, tmp_path / "p.png")
    img = Image.open(tmp_path / "p.png")
    assert img.size == (256, 256)
    assert img.getpixel((16 * 3 + 1, 16 * 2 + 1))[:3] == (35, 35, 35)


def test_write_json(tmp_path):
    write_json(tmp_path / "a" / "b.json", {"x": 1})
    assert json.loads((tmp_path / "a" / "b.json").read_text()) == {"x": 1}
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_export.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'dtx.export'`.

- [ ] **Step 3: Implement**

`src/dtx/export.py`:
```python
from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import numpy as np
from PIL import Image

from dtx.formats.frame import Frame


def rgba(frame: Frame, palette: np.ndarray) -> np.ndarray:
    out = np.zeros((frame.height, frame.width, 4), np.uint8)
    out[..., :3] = palette[frame.indices]
    out[..., 3] = frame.opaque.astype(np.uint8) * 255
    return out


def _index_image(frame: Frame) -> np.ndarray:
    grey = np.where(frame.opaque, frame.indices, 0).astype(np.uint8)
    return np.dstack([grey, frame.opaque.astype(np.uint8) * 255])


def write_frame_pair(frame: Frame, palette: np.ndarray, directory: Path, stem: str) -> dict:
    record: dict = {"w": frame.width, "h": frame.height}
    if frame.width == 0 or frame.height == 0:
        record["empty"] = True
        return record
    directory.mkdir(parents=True, exist_ok=True)
    png, idx = f"{stem}.png", f"{stem}.idx.png"
    Image.fromarray(rgba(frame, palette)).save(directory / png)
    Image.fromarray(_index_image(frame)).save(directory / idx)
    record.update(png=png, idx=idx)
    return record


def write_sheet(groups: Sequence[Sequence[Frame]], palette: np.ndarray, path: Path) -> bool:
    frames = [f for g in groups for f in g]
    cell_w = max((f.width for f in frames), default=0)
    cell_h = max((f.height for f in frames), default=0)
    columns = max((len(g) for g in groups), default=0)
    if cell_w == 0 or cell_h == 0 or columns == 0:
        return False
    canvas = np.zeros((len(groups) * cell_h, columns * cell_w, 4), np.uint8)
    for row, group in enumerate(groups):
        for col, frame in enumerate(group):
            if frame.width and frame.height:
                y, x = row * cell_h, col * cell_w
                canvas[y : y + frame.height, x : x + frame.width] = rgba(frame, palette)
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(canvas).save(path)
    return True


def write_swatch(palette: np.ndarray, path: Path) -> None:
    grid = palette.reshape(16, 16, 3)
    big = np.repeat(np.repeat(grid, 16, axis=0), 16, axis=1)
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(big.astype(np.uint8)).save(path)


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2) + "\n")
```

`src/dtx/verify.py`:
```python
from pathlib import Path

import numpy as np
from PIL import Image

from dtx.formats.frame import Frame


def read_index_png(path: Path) -> Frame:
    with Image.open(path) as img:
        if img.mode != "LA":
            raise ValueError(f"{path} is {img.mode}, expected an LA index image")
        data = np.asarray(img)
    return Frame(data[..., 0].copy(), data[..., 1] == 255)


def verify_written(frame: Frame, idx_path: Path) -> bool:
    return frame.same_pixels(read_index_png(idx_path))
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_export.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/dtx/export.py src/dtx/verify.py tests/test_export.py
git commit -m "feat: write PNG pairs, sheets, swatches and verify index images"
```

---

### Task 12: StormLib wrapper and archive stack

**Files:**
- Create: `src/dtx/mpq.py`, `tests/fakes.py`
- Test: `tests/test_mpq.py`, `tests/test_mpq_game.py`

**Interfaces:**
- Consumes: `canonical` (Task 1).
- Produces:
  - `StormLibError(RuntimeError)`; `MpqArchive(path)` with `.name`, `.read(name) -> bytes | None`, `.has(name) -> bool`, `.add_listfile(path)`, `.names() -> list[str]`, `.close()`.
  - `ArchiveStack(archives)` with `.read(name) -> tuple[str, bytes] | None` (archive name, data; highest priority first), `.versions(name) -> list[tuple[str, bytes]]`, `.has(name) -> bool`, `.names() -> tuple[list[str], dict[str, list[str]]]` (sorted canonical named files; unnamed pseudo-names per archive), `.close()`, context manager, and `ArchiveStack.open_game(game_dir: Path, listfile: Path | None = None)`.
  - `GRAPHICS_ARCHIVES = ("hfmonk.mpq", "hellfire.mpq", "DIABDAT.MPQ")`.
  - Test helper `tests.fakes.FakeArchive(name, files: dict[str, bytes], unnamed=())`.

StormLib facts: `SFileOpenArchive(char*, DWORD priority, DWORD flags, HANDLE*)`, read-only flag `0x100`; `SFileOpenFileEx(HANDLE, char*, 0, HANDLE*)`; `SFileGetFileSize(HANDLE, DWORD*)`; `SFileReadFile(HANDLE, void*, DWORD, DWORD*, void*)`; `SFileHasFile`; `SFileAddListFile(HANDLE, char*) -> DWORD` (0 = ok); `SFileFindFirstFile(HANDLE, char* mask, SFILE_FIND_DATA*, char* listfile) -> HANDLE`, `SFileFindNextFile`, `SFileFindClose`; `SErrGetLastError()`. `SFILE_FIND_DATA` begins with `char cFileName[MAX_PATH]`; the wrapper passes an 8 KiB buffer and reads only that leading C string, so it does not depend on `MAX_PATH`. Files without a known name are enumerated as pseudo-names `FileNNNNNNNN.ext`.

- [ ] **Step 1: Install StormLib and check the library name**

Run: `brew install stormlib && ls "$(brew --prefix stormlib)/lib"`
Expected: output lists `libstorm.dylib` (or `libstorm.<version>.dylib`). If the file has a different name, use that name in `_LIB_NAMES` below.

- [ ] **Step 2: Write the fake and failing unit tests**

`tests/fakes.py`:
```python
from dtx.paths import canonical


class FakeArchive:
    def __init__(self, name: str, files: dict[str, bytes], unnamed=()):
        self.name = name
        self.files = {canonical(k): v for k, v in files.items()}
        self.unnamed = list(unnamed)

    def read(self, name: str) -> bytes | None:
        return self.files.get(canonical(name))

    def has(self, name: str) -> bool:
        return canonical(name) in self.files

    def names(self) -> list[str]:
        return [n.upper() for n in self.files] + self.unnamed + ["(listfile)"]

    def close(self) -> None:
        pass
```

`tests/test_mpq.py`:
```python
from fakes import FakeArchive
from dtx.mpq import ArchiveStack

HF = FakeArchive("hellfire.mpq", {"data\\a.cel": b"new"}, unnamed=["File00000007.wav"])
DD = FakeArchive("DIABDAT.MPQ", {"data\\a.cel": b"old", "Data/B.pcx": b"b"})


def test_read_prefers_highest_priority():
    stack = ArchiveStack([HF, DD])
    assert stack.read("DATA\\A.CEL") == ("hellfire.mpq", b"new")
    assert stack.read("data/b.pcx") == ("DIABDAT.MPQ", b"b")
    assert stack.read("missing.cel") is None


def test_versions_lists_every_archive():
    stack = ArchiveStack([HF, DD])
    assert stack.versions("data\\a.cel") == [("hellfire.mpq", b"new"), ("DIABDAT.MPQ", b"old")]


def test_names_canonical_and_unnamed():
    named, unnamed = ArchiveStack([HF, DD]).names()
    assert named == ["data\\a.cel", "data\\b.pcx"]
    assert unnamed == {"hellfire.mpq": ["File00000007.wav"], "DIABDAT.MPQ": []}
```

`tests/test_mpq_game.py`:
```python
import pytest

from dtx.mpq import ArchiveStack

pytestmark = pytest.mark.game


def test_reads_real_palette(game_dir):
    with ArchiveStack.open_game(game_dir) as stack:
        archive, data = stack.read("levels\\towndata\\town.pal")
        assert archive == "DIABDAT.MPQ"
        assert len(data) == 768
        assert stack.has("ui_art\\title.pcx")
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/test_mpq.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'dtx.mpq'`.

- [ ] **Step 4: Implement**

`src/dtx/mpq.py`:
```python
from __future__ import annotations

import ctypes
import ctypes.util
import os
import re
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from dtx.paths import canonical

MPQ_OPEN_READ_ONLY = 0x00000100
SFILE_OPEN_FROM_MPQ = 0
FIND_DATA_BYTES = 8192  # larger than SFILE_FIND_DATA; only cFileName (offset 0) is read
PSEUDO_NAME = re.compile(r"^File\d{8}\.\w+$")
GRAPHICS_ARCHIVES = ("hfmonk.mpq", "hellfire.mpq", "DIABDAT.MPQ")
_LIB_NAMES = ("libstorm.dylib", "libstorm.so")

_lib = None


class StormLibError(RuntimeError):
    pass


def _find_library() -> str:
    env = os.environ.get("DTX_STORMLIB")
    if env:
        return env
    try:
        prefix = subprocess.run(
            ["brew", "--prefix", "stormlib"], capture_output=True, text=True, check=True
        ).stdout.strip()
        for name in _LIB_NAMES:
            candidate = Path(prefix) / "lib" / name
            if candidate.exists():
                return str(candidate)
    except (OSError, subprocess.CalledProcessError):
        pass
    found = ctypes.util.find_library("storm")
    if found:
        return found
    raise StormLibError(
        "StormLib not found. Install it with `brew install stormlib` or set DTX_STORMLIB to the library path."
    )


def storm():
    global _lib
    if _lib is None:
        lib = ctypes.CDLL(_find_library())
        H, D, S, B = ctypes.c_void_p, ctypes.c_uint32, ctypes.c_char_p, ctypes.c_bool
        signatures = {
            "SFileOpenArchive": ([S, D, D, ctypes.POINTER(H)], B),
            "SFileCloseArchive": ([H], B),
            "SFileOpenFileEx": ([H, S, D, ctypes.POINTER(H)], B),
            "SFileGetFileSize": ([H, ctypes.POINTER(D)], D),
            "SFileReadFile": ([H, ctypes.c_void_p, D, ctypes.POINTER(D), ctypes.c_void_p], B),
            "SFileCloseFile": ([H], B),
            "SFileHasFile": ([H, S], B),
            "SFileAddListFile": ([H, S], D),
            "SFileFindFirstFile": ([H, S, ctypes.c_void_p, S], H),
            "SFileFindNextFile": ([H, ctypes.c_void_p], B),
            "SFileFindClose": ([H], B),
            "SErrGetLastError": ([], D),
        }
        for name, (args, res) in signatures.items():
            fn = getattr(lib, name)
            fn.argtypes, fn.restype = args, res
        _lib = lib
    return _lib


class MpqArchive:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.name = self.path.name
        handle = ctypes.c_void_p()
        if not storm().SFileOpenArchive(str(self.path).encode(), 0, MPQ_OPEN_READ_ONLY, ctypes.byref(handle)):
            raise StormLibError(f"cannot open {self.path}: StormLib error {storm().SErrGetLastError()}")
        self._handle = handle

    def close(self) -> None:
        if self._handle:
            storm().SFileCloseArchive(self._handle)
            self._handle = None

    def has(self, name: str) -> bool:
        return bool(storm().SFileHasFile(self._handle, canonical(name).encode("ascii")))

    def read(self, name: str) -> bytes | None:
        lib = storm()
        file_handle = ctypes.c_void_p()
        if not lib.SFileOpenFileEx(self._handle, canonical(name).encode("ascii"), SFILE_OPEN_FROM_MPQ,
                                   ctypes.byref(file_handle)):
            return None
        try:
            high = ctypes.c_uint32(0)
            size = lib.SFileGetFileSize(file_handle, ctypes.byref(high))
            buffer = ctypes.create_string_buffer(size)
            got = ctypes.c_uint32(0)
            lib.SFileReadFile(file_handle, buffer, size, ctypes.byref(got), None)
            if got.value != size:
                raise StormLibError(f"read {got.value} of {size} bytes of {name} from {self.name}")
            return buffer.raw[:size]
        finally:
            lib.SFileCloseFile(file_handle)

    def add_listfile(self, listfile: Path) -> None:
        error = storm().SFileAddListFile(self._handle, str(listfile).encode())
        if error:
            raise StormLibError(f"cannot add listfile {listfile} to {self.name}: error {error}")

    def names(self) -> list[str]:
        lib = storm()
        data = ctypes.create_string_buffer(FIND_DATA_BYTES)
        find = lib.SFileFindFirstFile(self._handle, b"*", data, None)
        if not find:
            return []
        names = []
        try:
            while True:
                names.append(data.value.decode("latin-1"))
                if not lib.SFileFindNextFile(find, data):
                    break
        finally:
            lib.SFileFindClose(find)
        return names


class Archive(Protocol):
    name: str

    def read(self, name: str) -> bytes | None: ...
    def has(self, name: str) -> bool: ...
    def names(self) -> list[str]: ...
    def close(self) -> None: ...


class ArchiveStack:
    """Archives in priority order, highest first."""

    def __init__(self, archives: Sequence[Archive]):
        self.archives = list(archives)

    @classmethod
    def open_game(cls, game_dir: Path, listfile: Path | None = None) -> ArchiveStack:
        files = {p.name.lower(): p for p in Path(game_dir).expanduser().iterdir() if p.is_file()}
        missing = [n for n in GRAPHICS_ARCHIVES if n.lower() not in files]
        if missing:
            raise FileNotFoundError(f"missing archives in {game_dir}: {', '.join(missing)}")
        archives = [MpqArchive(files[n.lower()]) for n in GRAPHICS_ARCHIVES]
        if listfile is not None:
            for archive in archives:
                archive.add_listfile(listfile)
        return cls(archives)

    def __enter__(self) -> ArchiveStack:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        for archive in self.archives:
            archive.close()

    def read(self, name: str) -> tuple[str, bytes] | None:
        for archive in self.archives:
            data = archive.read(name)
            if data is not None:
                return archive.name, data
        return None

    def versions(self, name: str) -> list[tuple[str, bytes]]:
        out = []
        for archive in self.archives:
            data = archive.read(name)
            if data is not None:
                out.append((archive.name, data))
        return out

    def has(self, name: str) -> bool:
        return any(a.has(name) for a in self.archives)

    def names(self) -> tuple[list[str], dict[str, list[str]]]:
        named: set[str] = set()
        unnamed: dict[str, list[str]] = {}
        for archive in self.archives:
            pseudo = []
            for name in archive.names():
                if name.startswith("("):
                    continue
                if PSEUDO_NAME.match(name):
                    pseudo.append(name)
                else:
                    named.add(canonical(name))
            unnamed[archive.name] = sorted(pseudo)
        return sorted(named), unnamed
```

- [ ] **Step 5: Run unit and game tests**

Run: `uv run pytest tests/test_mpq.py -v && DTX_GAME_DIR=~/diablo1-hellfire-gog uv run pytest tests/test_mpq_game.py -v`
Expected: both PASS. If `test_reads_real_palette` fails because a name is missing, print `stack.archives[2].names()[:20]` in a Python shell to see how StormLib reports names, and fix the wrapper before continuing.

- [ ] **Step 6: Commit**

```bash
git add src/dtx/mpq.py tests/fakes.py tests/test_mpq.py tests/test_mpq_game.py
git commit -m "feat: read MPQ archives through StormLib with priority stack"
```

---

### Task 13: Reference data builder (listfile, widths, variants)

**Files:**
- Create: `src/dtx/refdata.py`, `src/dtx/data/.gitkeep`
- Modify: `src/dtx/cli.py` (register `refdata build`)
- Test: `tests/test_refdata.py`
- Generate (committed): `src/dtx/data/listfile.txt`, `src/dtx/data/widths.json`, `src/dtx/data/variants.json`

**Interfaces:**
- Consumes: `ArchiveStack` (Task 12), `canonical` (Task 1).
- Produces:
  - `build(dvx: Path, stack, out_dir: Path = DATA_DIR, community: Path | None = None) -> dict` (`{"candidates": int, "present": int}`); writes the three data files.
  - Runtime loaders `listfile_path() -> Path`, `load_widths() -> dict[str, int | list[int]]`, `load_variants() -> dict[str, list[str]]` (empty dicts if files are missing).
  - `PINNED_DEVILUTIONX = "8bef7bce51641b8faa1f56f4119e5b6ee6ec6f3f"`.
  - CLI: `dtx refdata build --devilutionx DIR --game DIR [--community FILE]`.

Name sources (spec §4.1): C++ string literals in DevilutionX `Source/` (including `R"(...)"` raw strings; extensionless names are expanded with `.cel .cl2 .pcx .pal .trn`), the TSV tables, fixed level-file patterns, `MANUAL_WIDTHS`, and an optional community listfile. Only names present in an archive are kept.

- [ ] **Step 1: Write the failing tests**

`tests/test_refdata.py`:
```python
import json

from fakes import FakeArchive
from dtx.mpq import ArchiveStack
from dtx.refdata import build


def tsv(path, header, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(["\t".join(header)] + ["\t".join(r) for r in rows]) + "\n")


def fake_devilutionx(root):
    src = root / "Source"
    src.mkdir(parents=True)
    (src / "a.cpp").write_text(
        r'LoadCel("data\\pentspin", 48); LoadFileInMem("levels\\l1data\\skngdo.dun");'
        '\n' r'BufCopy(x, R"(nlevels\l6data\l6base)", rv, ".pal");'
    )
    txt = root / "assets" / "txtdata"
    tsv(txt / "monsters" / "monstdat.tsv",
        ["_monster_id", "name", "assetsSuffix", "soundSuffix", "trnFile", "availability", "width"],
        [["MT_BZOMBIE", "Ghoul", "zombie\\zombie", "", "zombie\\bluered", "Always", "128"]])
    tsv(txt / "monsters" / "unique_monstdat.tsv", ["name", "mTrnName"], [["Gharbad", "general"]])
    tsv(txt / "missiles" / "missile_sprites.tsv", ["id", "width", "width2", "name", "numFrames"],
        [["Arrow", "96", "16", "arrows", "1"], ["Fireball", "96", "16", "fireba", "2"]])
    tsv(txt / "objects" / "objdat.tsv", ["id", "file", "animWidth"], [["OBJ_L1LIGHT", "l1braz", "64"]])
    sprites = txt / "classes" / "warrior" / "sprites.tsv"
    tsv(sprites, ["Variable", "Value"], [
        ["classPath", "warrior"], ["classChar", "w"], ["trn", "warrior"], ["stand", "96"], ["walk", "96"],
        ["attack", "128"], ["bow", "96"], ["swHit", "96"], ["block", "96"], ["lightning", "96"],
        ["fire", "96"], ["magic", "96"], ["death", "128"]])
    inv = root / "assets" / "data" / "inv"
    inv.mkdir(parents=True)
    (inv / "objcurs-widths.txt").write_text("33\n32\n")


PRESENT = {
    "monsters\\zombie\\zombien.cl2": b"", "monsters\\zombie\\bluered.trn": b"",
    "monsters\\monsters\\general.trn": b"", "data\\pentspin.cel": b"",
    "levels\\l1data\\skngdo.dun": b"", "nlevels\\l6data\\l6base.pal": b"",
    "plrgfx\\warrior\\wlb\\wlbat.cl2": b"", "plrgfx\\warrior\\wln\\wlnst.cl2": b"",
    "missiles\\arrows.cl2": b"", "missiles\\fireba2.cl2": b"", "objects\\l1braz.cel": b"",
    "data\\inv\\objcurs.cel": b"", "levels\\l1data\\l1.min": b"", "extra\\community.cel": b"",
}


def test_build(tmp_path):
    dvx = tmp_path / "dvx"
    fake_devilutionx(dvx)
    community = tmp_path / "community.txt"
    community.write_text("EXTRA\\COMMUNITY.CEL\nnot\\present.cel\n")
    stack = ArchiveStack([FakeArchive("DIABDAT.MPQ", PRESENT)])
    out = tmp_path / "data"

    summary = build(dvx, stack, out, community)

    listed = (out / "listfile.txt").read_text().split()
    assert listed == sorted(PRESENT)
    assert summary["present"] == len(PRESENT)
    widths = json.loads((out / "widths.json").read_text())
    assert widths["monsters\\zombie\\zombien.cl2"] == 128
    assert widths["plrgfx\\warrior\\wln\\wlnst.cl2"] == 96
    assert widths["plrgfx\\warrior\\wlb\\wlbat.cl2"] == 96  # bow attack uses the bow width
    assert widths["missiles\\fireba2.cl2"] == 96
    assert widths["objects\\l1braz.cel"] == 64
    assert widths["data\\inv\\objcurs.cel"] == [33, 32]
    assert widths["data\\pentspin.cel"] == 48
    assert "monsters\\zombie\\zombiew.cl2" not in widths  # absent from archives
    variants = json.loads((out / "variants.json").read_text())
    assert variants == {"monsters\\zombie\\zombien.cl2": ["monsters\\zombie\\bluered.trn"]}
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_refdata.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'dtx.refdata'`.

- [ ] **Step 3: Implement**

`src/dtx/refdata.py`:
```python
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

from dtx.paths import canonical

DATA_DIR = Path(__file__).parent / "data"
PINNED_DEVILUTIONX = "8bef7bce51641b8faa1f56f4119e5b6ee6ec6f3f"

# Constant widths from DevilutionX Source/*.cpp LoadCel(...) calls at the pinned commit.
MANUAL_WIDTHS: dict[str, int] = {
    "ctrlpan\\p8but2.cel": 33, "ctrlpan\\talkbutt.cel": 61, "ctrlpan\\golddrop.cel": 261,
    "ctrlpan\\p8bulbs.cel": 88, "ctrlpan\\panel8bu.cel": 71,
    "data\\diabsmal.cel": 296, "data\\pentspin.cel": 48, "data\\pentspn2.cel": 12,
    "data\\square.cel": 64, "data\\textbox.cel": 591, "data\\textbox2.cel": 271,
    "data\\textslid.cel": 12, "data\\spelli2.cel": 37, "data\\hf_logo3.cel": 430,
    "items\\duricons.cel": 32, "items\\map\\mapztown.cel": 640, "towners\\animals\\cow.cel": 128,
    "levels\\towndata\\towns.cel": 64, "levels\\l1data\\l1s.cel": 64,
    "levels\\l2data\\l2s.cel": 64, "nlevels\\l5data\\l5s.cel": 64,
}
MONSTER_ANIMS = "nwahds"
ARMOUR = "lmh"
WEAPONS = "nusdbamht"
PLAYER_ANIMS = {
    "st": "stand", "as": "stand", "wl": "walk", "aw": "walk", "at": "attack", "ht": "swHit",
    "bl": "block", "lm": "lightning", "fm": "fire", "qm": "magic", "dt": "death",
}
BARE_EXTENSIONS = (".cel", ".cl2", ".pcx", ".pal", ".trn")
LITERAL = re.compile(r'"((?:[A-Za-z0-9_]+\\\\)+[A-Za-z0-9_\-]+(?:\.[A-Za-z0-9]{2,4})?)"')
RAW_LITERAL = re.compile(r'R"\(((?:[A-Za-z0-9_]+\\)+[A-Za-z0-9_\-]+(?:\.[A-Za-z0-9]{2,4})?)\)"')


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as f:
        return [{k: (v or "") for k, v in row.items()} for row in csv.DictReader(f, delimiter="\t")]


def read_kv_tsv(path: Path) -> dict[str, str]:
    return {row["Variable"]: row["Value"] for row in read_tsv(path)}


def _add_bare(names: set[str], name: str) -> None:
    if re.search(r"\.[a-z0-9]{2,4}$", name):
        names.add(name)
    else:
        names.update(name + ext for ext in BARE_EXTENSIONS)


def source_names(source: Path) -> set[str]:
    names: set[str] = set()
    for path in source.rglob("*"):
        if path.suffix not in {".cpp", ".h", ".hpp"}:
            continue
        text = path.read_text(errors="ignore")
        for m in LITERAL.finditer(text):
            _add_bare(names, canonical(m.group(1).replace("\\\\", "\\")))
        for m in RAW_LITERAL.finditer(text):
            _add_bare(names, canonical(m.group(1)))
    return names


def level_names() -> set[str]:
    names: set[str] = set()
    parts = ("cel", "min", "til", "sol", "amp")
    for n in range(1, 5):
        d = f"levels\\l{n}data\\"
        names |= {f"{d}l{n}.{e}" for e in parts} | {f"{d}l{n}s.cel"}
        names |= {f"{d}l{n}_{v}.pal" for v in range(1, 6)}
    for d in ("levels\\towndata\\", "nlevels\\towndata\\"):
        names |= {f"{d}town.{e}" for e in parts + ("pal",)} | {f"{d}towns.cel"}
    names |= {f"nlevels\\l5data\\l5.{e}" for e in parts} | {"nlevels\\l5data\\l5s.cel", "nlevels\\l5data\\l5base.pal"}
    names |= {f"nlevels\\l6data\\l6.{e}" for e in parts} | {"nlevels\\l6data\\l6base.pal"}
    names |= {f"nlevels\\l6data\\l6base{v}.pal" for v in range(1, 6)}
    return names


def table_widths(dvx: Path) -> tuple[dict[str, int | list[int]], dict[str, list[str]], set[str]]:
    txt = dvx / "assets" / "txtdata"
    widths: dict[str, int | list[int]] = dict(MANUAL_WIDTHS)
    variants: dict[str, list[str]] = {}
    names: set[str] = set()

    for row in read_tsv(txt / "monsters" / "monstdat.tsv"):
        base = "monsters\\" + canonical(row["assetsSuffix"])
        trn = canonical(row["trnFile"].strip())
        for anim in MONSTER_ANIMS:
            path = f"{base}{anim}.cl2"
            widths[path] = int(row["width"])
            if trn:
                lst = variants.setdefault(path, [])
                if f"monsters\\{trn}.trn" not in lst:
                    lst.append(f"monsters\\{trn}.trn")
        if trn:
            names.add(f"monsters\\{trn}.trn")
    for row in read_tsv(txt / "monsters" / "unique_monstdat.tsv"):
        for key, value in row.items():
            if key and "trn" in key.lower() and value.strip():
                names.add(f"monsters\\monsters\\{canonical(value.strip())}.trn")

    for row in read_tsv(txt / "missiles" / "missile_sprites.tsv"):
        name = canonical(row["name"].strip())
        if not name:
            continue
        count = int(row["numFrames"])
        paths = [f"missiles\\{name}.cl2"] + [f"missiles\\{name}{i}.cl2" for i in range(0, count + 1)]
        for path in paths:
            widths[path] = int(row["width"])

    for row in read_tsv(txt / "objects" / "objdat.tsv"):
        file = canonical(row["file"].strip())
        if file:
            widths[f"objects\\{file}.cel"] = int(row["animWidth"])

    for sprites in sorted((txt / "classes").glob("*/sprites.tsv")):
        kv = read_kv_tsv(sprites)
        folder, char = canonical(kv["classPath"]), kv["classChar"].lower()
        for armour in ARMOUR:
            for weapon in WEAPONS:
                prefix = f"{char}{armour}{weapon}"
                for anim, key in PLAYER_ANIMS.items():
                    width_key = "bow" if (anim == "at" and weapon == "b") else key
                    widths[f"plrgfx\\{folder}\\{prefix}\\{prefix}{anim}.cl2"] = int(kv[width_key])

    objcurs = dvx / "assets" / "data" / "inv" / "objcurs-widths.txt"
    if objcurs.exists():
        widths["data\\inv\\objcurs.cel"] = [int(v) for v in objcurs.read_text().split()]
    return widths, variants, names


def build(dvx: Path, stack, out_dir: Path = DATA_DIR, community: Path | None = None) -> dict:
    widths, variants, names = table_widths(dvx)
    names |= set(widths) | source_names(dvx / "Source") | level_names()
    if community is not None:
        names |= {canonical(line.strip()) for line in community.read_text(errors="ignore").splitlines()
                  if line.strip()}
    present = sorted(n for n in names if stack.has(n))
    present_set = set(present)

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "listfile.txt").write_text("\n".join(present) + "\n")
    kept_widths = {k: widths[k] for k in sorted(widths) if k in present_set}
    (out_dir / "widths.json").write_text(json.dumps(kept_widths, indent=1) + "\n")
    kept_variants = {}
    for k in sorted(variants):
        if k in present_set:
            trns = [t for t in variants[k] if t in present_set]
            if trns:
                kept_variants[k] = trns
    (out_dir / "variants.json").write_text(json.dumps(kept_variants, indent=1) + "\n")
    return {"candidates": len(names), "present": len(present)}


def listfile_path() -> Path:
    return DATA_DIR / "listfile.txt"


def load_widths() -> dict:
    path = DATA_DIR / "widths.json"
    return json.loads(path.read_text()) if path.exists() else {}


def load_variants() -> dict:
    path = DATA_DIR / "variants.json"
    return json.loads(path.read_text()) if path.exists() else {}
```

Register the CLI command. In `src/dtx/cli.py`, replace `build_parser` with:
```python
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dtx", description="Export Diablo and Hellfire graphics for HD regeneration."
    )
    sub = parser.add_subparsers(dest="command")
    parser._dtx_subparsers = sub  # type: ignore[attr-defined]

    refdata = sub.add_parser("refdata", help="reference data (listfile, widths)")
    refdata_sub = refdata.add_subparsers(dest="refdata_command", required=True)
    rb = refdata_sub.add_parser("build", help="regenerate src/dtx/data from a DevilutionX checkout")
    rb.add_argument("--devilutionx", type=Path, required=True)
    rb.add_argument("--game", type=Path, required=True)
    rb.add_argument("--community", type=Path)
    rb.set_defaults(func=_refdata_build)
    return parser


def _refdata_build(args) -> int:
    from dtx.mpq import ArchiveStack
    from dtx.refdata import build, listfile_path

    with ArchiveStack.open_game(args.game) as stack:
        summary = build(args.devilutionx, stack, community=args.community)
    print(f"{summary['present']} of {summary['candidates']} candidate names exist in the archives")
    with ArchiveStack.open_game(args.game, listfile_path()) as stack:
        named, unnamed = stack.names()
        for archive in stack.archives:
            total = len(archive.names())
            missing = len(unnamed[archive.name])
            print(f"{archive.name}: {total - missing} named, {missing} unnamed")
    return 0
```
and add `from pathlib import Path` to the imports.

Create an empty `src/dtx/data/.gitkeep`.

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_refdata.py -v`
Expected: PASS.

- [ ] **Step 5: Generate the real reference data**

Run:
```bash
mkdir -p ~/.cache/dtx
git clone --filter=blob:none https://github.com/diasurgical/devilutionx ~/.cache/dtx/devilutionx
git -C ~/.cache/dtx/devilutionx checkout 8bef7bce51641b8faa1f56f4119e5b6ee6ec6f3f
uv run dtx refdata build --devilutionx ~/.cache/dtx/devilutionx --game ~/diablo1-hellfire-gog
```
Expected: prints the candidate count and, per archive, named vs unnamed counts. `src/dtx/data/listfile.txt` contains thousands of names including `levels\l1data\l1.cel` and `ui_art\title.pcx`.

If any graphics archive has more than 1% unnamed entries, find a community Diablo I listfile (for example the listfile shipped with diasurgical's MPQ tools or Ladislav Zezula's MPQ Editor listfiles), save it to `~/.cache/dtx/diablo-listfile.txt`, and rerun with `--community ~/.cache/dtx/diablo-listfile.txt`. Record the source URL of that listfile in the commit message.

- [ ] **Step 6: Commit**

```bash
git add src/dtx/refdata.py src/dtx/cli.py src/dtx/data tests/test_refdata.py
git commit -m "feat: generate listfile, width and variant tables from DevilutionX 8bef7bce"
```

---

### Task 14: Catalog

**Files:**
- Create: `src/dtx/catalog.py`
- Test: `tests/test_catalog.py`

**Interfaces:**
- Consumes: `paths` helpers (Task 1).
- Produces:
  - `TilesetSpec(key: str, cells_per_column: int, palette_preference: tuple[str, ...])`; `TILESETS: dict[str, TilesetSpec]`; `DUN_OWNERS: dict[str, str]` (directory → tileset key); `DEFAULT_PALETTE = "levels\\towndata\\town.pal"`; `KINDS: tuple[str, ...]`; `SPRITE_KINDS: frozenset[str]`.
  - `Entry(path, kind, palette=None, palette_alternatives=(), width_hint=None, variants=(), tileset=None)` (frozen, picklable).
  - `Skip(path, reason)`.
  - `classify(name, names: set[str], widths, variants) -> Entry | Skip`; `build_catalog(names, widths, variants) -> tuple[list[Entry], list[Skip]]`.

- [ ] **Step 1: Write the failing tests**

`tests/test_catalog.py`:
```python
from dtx.catalog import Entry, Skip, build_catalog, classify

NAMES = {
    "levels\\towndata\\town.pal", "levels\\l1data\\l1_1.pal", "levels\\l1data\\l1_2.pal",
    "levels\\l1data\\l1.cel", "levels\\l1data\\l1.min", "levels\\l1data\\l1.til", "levels\\l1data\\l1.sol",
    "levels\\l1data\\skngdo.dun", "levels\\l1data\\l1s.cel", "levels\\l2data\\l2.cel",
    "monsters\\zombie\\zombien.cl2", "ui_art\\title.pcx", "monsters\\zombie\\bluered.trn",
    "sfx\\misc\\walk1.wav", "weird\\thing.cel", "arena\\church.dun", "data\\inv\\objcurs.cel",
}
WIDTHS = {"monsters\\zombie\\zombien.cl2": 128, "data\\inv\\objcurs.cel": [33, 32]}
VARIANTS = {"monsters\\zombie\\zombien.cl2": ["monsters\\zombie\\bluered.trn"]}


def c(name):
    return classify(name, NAMES, WIDTHS, VARIANTS)


def test_simple_kinds():
    assert c("levels\\towndata\\town.pal").kind == "palette"
    assert c("monsters\\zombie\\bluered.trn").kind == "trn"
    assert c("ui_art\\title.pcx").kind == "ui_image"


def test_tileset_entry_and_parts():
    entry = c("levels\\l1data\\l1.cel")
    assert entry == Entry("levels\\l1data\\l1.cel", "tileset", "levels\\l1data\\l1_1.pal",
                          ("levels\\l1data\\l1_2.pal",), tileset="levels\\l1data\\l1")
    assert c("levels\\l1data\\l1.min") == Skip("levels\\l1data\\l1.min", "part of tileset levels\\l1data\\l1")


def test_tileset_missing_parts():
    skip = c("levels\\l2data\\l2.cel")
    assert isinstance(skip, Skip) and "missing min, til, sol" in skip.reason


def test_layout():
    entry = c("levels\\l1data\\skngdo.dun")
    assert entry.kind == "layout" and entry.tileset == "levels\\l1data\\l1"
    assert entry.palette == "levels\\l1data\\l1_1.pal"
    assert isinstance(c("arena\\church.dun"), Skip)


def test_sprites():
    monster = c("monsters\\zombie\\zombien.cl2")
    assert monster.kind == "monster_anim" and monster.width_hint == 128
    assert monster.palette == "levels\\towndata\\town.pal"
    assert monster.variants == ("monsters\\zombie\\bluered.trn",)
    assert c("data\\inv\\objcurs.cel").width_hint == (33, 32)
    level_sprite = c("levels\\l1data\\l1s.cel")
    assert level_sprite.kind == "level_sprite" and level_sprite.palette == "levels\\l1data\\l1_1.pal"
    assert c("weird\\thing.cel").kind == "unknown_graphic"


def test_not_graphics():
    assert c("sfx\\misc\\walk1.wav") == Skip("sfx\\misc\\walk1.wav", "not graphics")


def test_build_catalog_partitions_everything():
    entries, skips = build_catalog(NAMES, WIDTHS, VARIANTS)
    assert len(entries) + len(skips) == len(NAMES)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_catalog.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`src/dtx/catalog.py`:
```python
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from dtx.paths import directory, extension, stem

DEFAULT_PALETTE = "levels\\towndata\\town.pal"


@dataclass(frozen=True)
class TilesetSpec:
    key: str
    cells_per_column: int
    palette_preference: tuple[str, ...]


TILESETS: dict[str, TilesetSpec] = {
    s.key: s
    for s in (
        TilesetSpec("levels\\towndata\\town", 16, ("levels\\towndata\\town.pal",)),
        TilesetSpec("nlevels\\towndata\\town", 16, ("nlevels\\towndata\\town.pal", "levels\\towndata\\town.pal")),
        TilesetSpec("levels\\l1data\\l1", 10, ("levels\\l1data\\l1_1.pal",)),
        TilesetSpec("levels\\l2data\\l2", 10, ("levels\\l2data\\l2_1.pal",)),
        TilesetSpec("levels\\l3data\\l3", 10, ("levels\\l3data\\l3_1.pal",)),
        TilesetSpec("levels\\l4data\\l4", 16, ("levels\\l4data\\l4_1.pal",)),
        TilesetSpec("nlevels\\l5data\\l5", 10, ("nlevels\\l5data\\l5base.pal",)),
        TilesetSpec("nlevels\\l6data\\l6", 10, ("nlevels\\l6data\\l6base1.pal", "nlevels\\l6data\\l6base.pal")),
    )
}
DUN_OWNERS: dict[str, str] = {directory(k + ".x"): k for k in TILESETS}

SPRITE_PREFIXES = (
    ("monsters\\", "monster_anim"), ("plrgfx\\", "player_anim"), ("towners\\", "towner_anim"),
    ("missiles\\", "missile"), ("objects\\", "object"), ("items\\", "item"), ("data\\inv\\", "item"),
    ("ctrlpan\\", "ui_sprite"), ("data\\", "ui_sprite"), ("gendata\\", "ui_sprite"),
    ("ui_art\\", "ui_sprite"), ("levels\\", "level_sprite"), ("nlevels\\", "level_sprite"),
)
SPRITE_KINDS = frozenset({k for _, k in SPRITE_PREFIXES} | {"unknown_graphic"})
KINDS = ("palette", "trn", "ui_image", "tileset", "layout") + tuple(sorted(SPRITE_KINDS))


@dataclass(frozen=True)
class Entry:
    path: str
    kind: str
    palette: str | None = None
    palette_alternatives: tuple[str, ...] = ()
    width_hint: int | tuple[int, ...] | None = None
    variants: tuple[str, ...] = ()
    tileset: str | None = None


@dataclass(frozen=True)
class Skip:
    path: str
    reason: str


def choose_palette(preference: Iterable[str], pal_dir: str, names: set[str]) -> tuple[str | None, tuple[str, ...]]:
    in_dir = sorted(n for n in names if extension(n) == "pal" and directory(n) == pal_dir)
    default = next((p for p in preference if p in names), None)
    if default is None:
        default = in_dir[0] if in_dir else (DEFAULT_PALETTE if DEFAULT_PALETTE in names else None)
    return default, tuple(p for p in in_dir if p != default)


def classify(name: str, names: set[str], widths: Mapping, variants: Mapping) -> Entry | Skip:
    ext, base, folder = extension(name), stem(name), directory(name)
    if ext == "pal":
        return Entry(name, "palette")
    if ext == "trn":
        return Entry(name, "trn")
    if ext == "pcx":
        return Entry(name, "ui_image")
    if base in TILESETS and ext in ("cel", "min", "til", "sol"):
        if ext != "cel":
            return Skip(name, f"part of tileset {base}")
        missing = [e for e in ("min", "til", "sol") if f"{base}.{e}" not in names]
        if missing:
            return Skip(name, "tileset is missing " + ", ".join(missing))
        palette, alternatives = choose_palette(TILESETS[base].palette_preference, folder, names)
        return Entry(name, "tileset", palette, alternatives, tileset=base)
    if ext == "dun":
        owner = DUN_OWNERS.get(folder)
        if owner is None:
            return Skip(name, "layout directory has no known tileset")
        palette, alternatives = choose_palette(TILESETS[owner].palette_preference, folder, names)
        return Entry(name, "layout", palette, alternatives, tileset=owner)
    if ext in ("cel", "cl2"):
        kind = next((k for prefix, k in SPRITE_PREFIXES if name.startswith(prefix)), "unknown_graphic")
        palette, alternatives = DEFAULT_PALETTE, ()
        owner = DUN_OWNERS.get(folder)
        if kind == "level_sprite" and owner is not None:
            palette, alternatives = choose_palette(TILESETS[owner].palette_preference, folder, names)
        hint = widths.get(name)
        if isinstance(hint, list):
            hint = tuple(hint)
        return Entry(name, kind, palette, alternatives, width_hint=hint, variants=tuple(variants.get(name, ())))
    return Skip(name, "not graphics")


def build_catalog(names: Iterable[str], widths: Mapping, variants: Mapping) -> tuple[list[Entry], list[Skip]]:
    name_set = set(names)
    entries: list[Entry] = []
    skips: list[Skip] = []
    for name in sorted(name_set):
        result = classify(name, name_set, widths, variants)
        (entries if isinstance(result, Entry) else skips).append(result)
    return entries, skips
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_catalog.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/dtx/catalog.py tests/test_catalog.py
git commit -m "feat: classify archive files into export kinds"
```

---

### Task 15: Handlers for palettes, TRNs, PCX images and sprites

**Files:**
- Create: `src/dtx/handlers.py`
- Test: `tests/test_handlers.py`

**Interfaces:**
- Consumes: `ArchiveStack` (12), `Entry` (14), decoders (2–7), writers (11), `rel_path` (1).
- Produces:
  - `Context(stack, out: Path, verify: bool)` with `.palette(name) -> np.ndarray` (cached; `ValueError` if missing).
  - `VerificationError(ValueError)`.
  - `sha1(data: bytes) -> str`.
  - Handlers, all `handler(ctx, entry, archive: str, data: bytes, dest: Path) -> dict` returning extra report fields; each writes its record JSON last:
    - `export_palette` → `dest.parent/(dest.name + ".png")` and `(dest.name + ".json")`; returns `{}`.
    - `export_trn` → `dest/trn.json`; returns `{}`.
    - `export_image` → `dest/image.png`, `dest/image.idx.png`, `dest/meta.json`; returns `{"frames": 1}`.
    - `export_sprite` → `dest/d{g}/f{i:03d}.png|.idx.png`, `dest/sheet.png`, `dest/meta.json`; returns `{"frames": n, "width_source": ...}`.
  - `record_name(kind) -> str | None` (file name of the record in `dest`; `None` for palettes).

- [ ] **Step 1: Write the failing tests**

`tests/test_handlers.py`:
```python
import json

import numpy as np
import pytest

from builders import cel_frame, cl2_frame, grouped, pcx, sheet
from fakes import FakeArchive
from dtx.catalog import Entry
from dtx.handlers import Context, export_image, export_palette, export_sprite, export_trn, sha1
from dtx.mpq import ArchiveStack

PAL_BYTES = bytes(range(256)) * 3
PAL = np.frombuffer(PAL_BYTES, np.uint8).reshape(256, 3)


def ctx_for(tmp_path, files, verify=True):
    files = {"levels\\towndata\\town.pal": PAL_BYTES, **files}
    return Context(ArchiveStack([FakeArchive("DIABDAT.MPQ", files)]), tmp_path, verify)


def test_palette(tmp_path):
    ctx = ctx_for(tmp_path, {})
    dest = tmp_path / "palettes/levels/l3data/l3_1.pal"
    export_palette(ctx, Entry("levels\\l3data\\l3_1.pal", "palette"), "DIABDAT.MPQ", PAL_BYTES, dest)
    record = json.loads((tmp_path / "palettes/levels/l3data/l3_1.pal.json").read_text())
    assert record["source"]["sha1"] == sha1(PAL_BYTES)
    assert record["colors"][1] == [3, 4, 5]
    assert record["cycling"][0]["last"] == 31
    assert (tmp_path / "palettes/levels/l3data/l3_1.pal.png").exists()


def test_trn(tmp_path):
    ctx = ctx_for(tmp_path, {})
    export_trn(ctx, Entry("monsters\\x.trn", "trn"), "DIABDAT.MPQ", bytes(range(256)), tmp_path / "t")
    assert json.loads((tmp_path / "t/trn.json").read_text())["map"][7] == 7


def test_image(tmp_path):
    ctx = ctx_for(tmp_path, {})
    data = pcx(np.array([[1, 2], [3, 4]], np.uint8), PAL)
    info = export_image(ctx, Entry("ui_art\\x.pcx", "ui_image"), "DIABDAT.MPQ", data, tmp_path / "i")
    meta = json.loads((tmp_path / "i/meta.json").read_text())
    assert info == {"frames": 1}
    assert meta["palette"] == "embedded" and meta["width_source"] == "header"
    assert meta["frames"] == [{"group": 0, "i": 0, "w": 2, "h": 2, "png": "image.png", "idx": "image.idx.png"}]


def test_grouped_cl2_sprite(tmp_path):
    ctx = ctx_for(tmp_path, {})
    frame = cl2_frame([[1, 2, 3, 4]] * 40)
    data = grouped([sheet([frame, frame]) for _ in range(8)])
    entry = Entry("monsters\\z\\zn.cl2", "monster_anim", "levels\\towndata\\town.pal", width_hint=4,
                  variants=("monsters\\z\\blue.trn",))
    info = export_sprite(ctx, entry, "DIABDAT.MPQ", data, tmp_path / "s")
    meta = json.loads((tmp_path / "s/meta.json").read_text())
    assert info["frames"] == 16 and meta["width_source"] == "table"
    assert meta["groups"] == 8 and meta["group_label"] == "direction"
    assert meta["variants"] == [{"trn": "monsters/z/blue.trn"}]
    assert meta["frames"][3] == {"group": 1, "i": 1, "w": 4, "h": 40, "png": "d1/f001.png", "idx": "d1/f001.idx.png"}
    assert (tmp_path / "s/d7/f001.idx.png").exists() and (tmp_path / "s/sheet.png").exists()


def test_sprite_inferred_width_records_candidates(tmp_path):
    ctx = ctx_for(tmp_path, {})
    data = sheet([cel_frame([[None] * 30 + [1, 2]] * 3)])
    export_sprite(ctx, Entry("data\\x.cel", "ui_sprite", "levels\\towndata\\town.pal"), "DIABDAT.MPQ",
                  data, tmp_path / "s")
    meta = json.loads((tmp_path / "s/meta.json").read_text())
    assert meta["width_source"] == "inferred" and meta["frames"][0]["w"] == 32
    assert 32 in meta["width_candidates"]


def test_sprite_with_empty_frame(tmp_path):
    # Review Focus 2
    ctx = ctx_for(tmp_path, {})
    data = sheet([b"", cel_frame([[1, 2]])])
    export_sprite(ctx, Entry("data\\x.cel", "ui_sprite", "levels\\towndata\\town.pal", width_hint=2),
                  "DIABDAT.MPQ", data, tmp_path / "s")
    meta = json.loads((tmp_path / "s/meta.json").read_text())
    assert meta["frames"][0]["empty"] is True
    assert meta["frames"][1]["png"] == "d0/f001.png"


def test_missing_palette_raises(tmp_path):
    ctx = ctx_for(tmp_path, {})
    with pytest.raises(ValueError):
        export_sprite(ctx, Entry("data\\x.cel", "ui_sprite", "nope.pal", width_hint=2), "DIABDAT.MPQ",
                      sheet([cel_frame([[1, 2]])]), tmp_path / "s")
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_handlers.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'dtx.handlers'`.

- [ ] **Step 3: Implement**

`src/dtx/handlers.py`:
```python
from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np

from dtx.catalog import Entry
from dtx.export import write_frame_pair, write_json, write_sheet, write_swatch
from dtx.formats.frame import Frame
from dtx.formats.pal import cycling_for, decode_pal
from dtx.formats.pcx import decode_pcx
from dtx.formats.sheet import split_sheet
from dtx.formats.trn import decode_trn
from dtx.formats.width import resolve_widths, scan_frame
from dtx.paths import extension, rel_path
from dtx.verify import verify_written

RECORD_NAMES = {"trn": "trn.json", "tileset": "tileset.json", "layout": "layout.json"}


class VerificationError(ValueError):
    pass


def sha1(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def record_name(kind: str) -> str | None:
    if kind == "palette":
        return None
    return RECORD_NAMES.get(kind, "meta.json")


def source(archive: str, name: str, data: bytes) -> dict:
    return {"archive": archive, "path": name, "sha1": sha1(data)}


class Context:
    def __init__(self, stack, out: Path, verify: bool):
        self.stack = stack
        self.out = Path(out)
        self.verify = verify
        self._palettes: dict[str, np.ndarray] = {}
        self._tilesets: dict = {}

    def palette(self, name: str | None) -> np.ndarray:
        if name is None:
            raise ValueError("no palette available for this asset")
        if name not in self._palettes:
            found = self.stack.read(name)
            if found is None:
                raise ValueError(f"palette {name} not found in any archive")
            self._palettes[name] = decode_pal(found[1])
        return self._palettes[name]


def write_checked(ctx: Context, frame: Frame, palette: np.ndarray, directory: Path, stem: str) -> dict:
    record = write_frame_pair(frame, palette, directory, stem)
    if ctx.verify and not record.get("empty"):
        if not verify_written(frame, directory / record["idx"]):
            raise VerificationError(f"{directory / record['idx']} does not round-trip")
    return record


def export_palette(ctx: Context, entry: Entry, archive: str, data: bytes, dest: Path) -> dict:
    palette = decode_pal(data)
    write_swatch(palette, dest.parent / (dest.name + ".png"))
    write_json(dest.parent / (dest.name + ".json"), {
        "source": source(archive, entry.path, data),
        "colors": palette.tolist(),
        "cycling": cycling_for(entry.path),
    })
    return {}


def export_trn(ctx: Context, entry: Entry, archive: str, data: bytes, dest: Path) -> dict:
    write_json(dest / "trn.json", {"source": source(archive, entry.path, data), "map": decode_trn(data).tolist()})
    return {}


def export_image(ctx: Context, entry: Entry, archive: str, data: bytes, dest: Path) -> dict:
    frame, palette = decode_pcx(data)
    record = write_checked(ctx, frame, palette, dest, "image")
    write_json(dest / "meta.json", {
        "source": source(archive, entry.path, data),
        "format": "pcx",
        "kind": entry.kind,
        "palette": "embedded",
        "embedded_palette": palette.tolist(),
        "width_source": "header",
        "groups": 1,
        "group_label": None,
        "frames": [{"group": 0, "i": 0, **record}],
    })
    return {"frames": 1}


def export_sprite(ctx: Context, entry: Entry, archive: str, data: bytes, dest: Path) -> dict:
    fmt = extension(entry.path)
    palette = ctx.palette(entry.palette)
    groups = split_sheet(data)
    flat = [(g, i, raw) for g, frames in enumerate(groups) for i, raw in enumerate(frames)]
    scans = [scan_frame(fmt, raw) for _, _, raw in flat]
    widths = resolve_widths(scans, entry.width_hint)

    decoded: list[list[Frame]] = [[] for _ in groups]
    records = []
    for (g, i, _), scan, width in zip(flat, scans, widths.widths):
        frame = scan.to_frame(width)
        decoded[g].append(frame)
        record = write_checked(ctx, frame, palette, dest / f"d{g}", f"f{i:03d}")
        if "png" in record:
            record["png"] = f"d{g}/{record['png']}"
            record["idx"] = f"d{g}/{record['idx']}"
        records.append({"group": g, "i": i, **record})
    has_sheet = write_sheet(decoded, palette, dest / "sheet.png")

    meta = {
        "source": source(archive, entry.path, data),
        "format": fmt,
        "kind": entry.kind,
        "palette": rel_path(entry.palette),
        "palette_alternatives": [rel_path(p) for p in entry.palette_alternatives],
        "variants": [{"trn": rel_path(t)} for t in entry.variants],
        "width_source": widths.source,
        "groups": len(groups),
        "group_label": "direction" if len(groups) == 8 else ("group" if len(groups) > 1 else None),
        "sheet": "sheet.png" if has_sheet else None,
        "frames": records,
    }
    if widths.candidates:
        meta["width_candidates"] = list(widths.candidates)
    write_json(dest / "meta.json", meta)
    return {"frames": len(records), "width_source": widths.source}
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_handlers.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/dtx/handlers.py tests/test_handlers.py
git commit -m "feat: export palettes, TRNs, PCX images and sprites"
```

---

### Task 16: Tileset and layout handlers

**Files:**
- Modify: `src/dtx/handlers.py` (append)
- Test: `tests/test_handlers_tileset.py`

**Interfaces:**
- Consumes: `Context` (15), `TILESETS` (14), `split_sheet` (4), `decode_level_cell`/`TileType` (8), tileset parsers (9), render functions (10), writers (11).
- Produces:
  - `TilesetData(spec, columns, til, sol, cells: dict[int, Frame], column_frames: list[Frame], unreferenced: list[int], sources: dict[str, str], archive: str)`.
  - `Context.tileset(key) -> TilesetData` (cached per context).
  - `export_tileset(ctx, entry, archive, data, dest) -> dict` → `columns/m{i:04d}`, `cells/c{f:04d}`, `tiles/t{t:04d}` PNG pairs, `sheet.png`, `tileset.json`; returns `{"columns": n, "tiles": n}`.
  - `export_layout(ctx, entry, archive, data, dest) -> dict` → `layout.png`, `layout.idx.png`, `layout.json`; returns `{"placements": n}`.

- [ ] **Step 1: Write the failing tests**

`tests/test_handlers_tileset.py`:
```python
import json

import pytest
from PIL import Image

from builders import dun_bytes, min_bytes, sheet, til_bytes
from fakes import FakeArchive
from dtx.catalog import Entry
from dtx.handlers import Context, export_layout, export_tileset
from dtx.mpq import ArchiveStack

KEY = "levels\\l1data\\l1"
PAL = bytes(range(256)) * 3
EMPTY = (0, 0)
# 10 cells per column; bottom row (slots 8, 9) uses square cells 1 and 2
COLUMN = [EMPTY] * 8 + [(1, 0), (2, 0)]
FILES = {
    "levels\\l1data\\l1_1.pal": PAL,
    f"{KEY}.cel": sheet([bytes([10]) * 1024, bytes([20]) * 1024]),
    f"{KEY}.min": min_bytes([COLUMN, COLUMN]),
    f"{KEY}.til": til_bytes([(0, 1, 0, 1)]),
    f"{KEY}.sol": bytes([1, 0]),
}


def ctx_for(tmp_path, extra=None):
    return Context(ArchiveStack([FakeArchive("DIABDAT.MPQ", {**FILES, **(extra or {})})]), tmp_path, True)


def test_tileset_export(tmp_path):
    ctx = ctx_for(tmp_path)
    entry = Entry(f"{KEY}.cel", "tileset", "levels\\l1data\\l1_1.pal", tileset=KEY)
    info = export_tileset(ctx, entry, "DIABDAT.MPQ", FILES[f"{KEY}.cel"], tmp_path / "t")
    assert info == {"columns": 2, "tiles": 1}
    meta = json.loads((tmp_path / "t/tileset.json").read_text())
    assert meta["cells_per_column"] == 10 and meta["column_size_px"] == [64, 160]
    assert meta["columns"][0]["cells"][8] == {"slot": 8, "frame": 1, "draw_type": 0}
    assert meta["columns"][0]["sol"]["solid"] is True
    assert meta["cell_users"] == {"1": [0, 1], "2": [0, 1]}
    assert meta["tiles"][0]["columns"] == [0, 1, 0, 1]
    assert Image.open(tmp_path / "t/columns/m0000.png").size == (64, 160)
    assert Image.open(tmp_path / "t/tiles/t0000.png").size == (128, 192)
    assert (tmp_path / "t/cells/c0001.idx.png").exists() and (tmp_path / "t/sheet.png").exists()


def test_layout_export(tmp_path):
    ctx = ctx_for(tmp_path)
    dun = dun_bytes([[1, 0]])
    entry = Entry("levels\\l1data\\x.dun", "layout", "levels\\l1data\\l1_1.pal", tileset=KEY)
    info = export_layout(ctx, entry, "DIABDAT.MPQ", dun, tmp_path / "l")
    meta = json.loads((tmp_path / "l/layout.json").read_text())
    assert info == {"placements": 4}
    assert meta["size_px"] == [128, 192] and meta["column_height_px"] == 160
    assert meta["tileset"] == "levels/l1data/l1"
    assert meta["placements"][0] == {"column": 0, "x": 32, "y": 0}
    assert Image.open(tmp_path / "l/layout.png").size == (128, 192)


def test_layout_with_out_of_range_tile_fails(tmp_path):
    # Review Focus 5
    ctx = ctx_for(tmp_path)
    entry = Entry("levels\\l1data\\x.dun", "layout", "levels\\l1data\\l1_1.pal", tileset=KEY)
    with pytest.raises(ValueError, match="beyond"):
        export_layout(ctx, entry, "DIABDAT.MPQ", dun_bytes([[5]]), tmp_path / "l")
    assert not (tmp_path / "l/layout.json").exists()


def test_min_referencing_missing_cel_frame_fails(tmp_path):
    bad_min = min_bytes([[EMPTY] * 9 + [(7, 0)]])
    ctx = ctx_for(tmp_path, {f"{KEY}.min": bad_min})
    entry = Entry(f"{KEY}.cel", "tileset", "levels\\l1data\\l1_1.pal", tileset=KEY)
    with pytest.raises(ValueError, match="references cell 7"):
        export_tileset(ctx, entry, "DIABDAT.MPQ", FILES[f"{KEY}.cel"], tmp_path / "t")
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_handlers_tileset.py -v`
Expected: FAIL with `ImportError: cannot import name 'export_layout'`.

- [ ] **Step 3: Implement**

Add this method to the `Context` class in `src/dtx/handlers.py` (it calls `load_tileset`, defined below in the same module, so it resolves at call time):
```python
    def tileset(self, key: str) -> "TilesetData":
        if key not in self._tilesets:
            self._tilesets[key] = load_tileset(self, key)
        return self._tilesets[key]
```

Then append to `src/dtx/handlers.py` (and move the imports to the top of the file):
```python
from dataclasses import dataclass

from dtx.catalog import TILESETS, TilesetSpec
from dtx.formats.levelcel import TileType, decode_level_cell
from dtx.formats.render import compose, place_pieces, tile_pieces
from dtx.formats.tileset import (
    CellRef, cell_types, cell_users, compose_column, parse_dun, parse_min, parse_sol, parse_til,
)


@dataclass
class TilesetData:
    spec: TilesetSpec
    columns: list[list[CellRef]]
    til: list[tuple[int, int, int, int]]
    sol: list[dict[str, bool]]
    cells: dict[int, Frame]
    column_frames: list[Frame]
    unreferenced: list[int]
    sources: dict[str, str]
    archive: str

    @property
    def column_height(self) -> int:
        return self.spec.cells_per_column // 2 * 32


def load_tileset(ctx: Context, key: str) -> TilesetData:
    spec = TILESETS[key]
    parts: dict[str, tuple[str, bytes]] = {}
    for ext in ("cel", "min", "til", "sol"):
        found = ctx.stack.read(f"{key}.{ext}")
        if found is None:
            raise ValueError(f"tileset part {key}.{ext} not found")
        parts[ext] = found
    columns = parse_min(parts["min"][1], spec.cells_per_column)
    types = cell_types(columns)
    raw_cells = split_sheet(parts["cel"][1])[0]
    cells: dict[int, Frame] = {}
    for frame_no, tile_type in sorted(types.items()):
        if frame_no > len(raw_cells):
            raise ValueError(f"MIN references cell {frame_no} but the CEL has {len(raw_cells)} frames")
        cells[frame_no] = decode_level_cell(raw_cells[frame_no - 1], TileType(tile_type))
    return TilesetData(
        spec=spec,
        columns=columns,
        til=parse_til(parts["til"][1]),
        sol=parse_sol(parts["sol"][1]),
        cells=cells,
        column_frames=[compose_column(c, cells) for c in columns],
        unreferenced=[f for f in range(1, len(raw_cells) + 1) if f not in cells],
        sources={ext: f"{key}.{ext}" for ext in parts},
        archive=parts["cel"][0],
    )


def export_tileset(ctx: Context, entry: Entry, archive: str, data: bytes, dest: Path) -> dict:
    ts = ctx.tileset(entry.tileset)
    palette = ctx.palette(entry.palette)
    column_records = []
    for i, frame in enumerate(ts.column_frames):
        record = write_checked(ctx, frame, palette, dest / "columns", f"m{i:04d}")
        column_records.append({
            "id": i,
            "png": f"columns/{record['png']}" if "png" in record else None,
            "idx": f"columns/{record['idx']}" if "idx" in record else None,
            "cells": [{"slot": s, "frame": r.frame, "draw_type": r.tile_type} for s, r in enumerate(ts.columns[i])],
            "sol": ts.sol[i] if i < len(ts.sol) else None,
        })
    for frame_no, frame in ts.cells.items():
        write_checked(ctx, frame, palette, dest / "cells", f"c{frame_no:04d}")

    tile_frames = []
    tile_records = []
    for t in range(len(ts.til)):
        placements, size = place_pieces(tile_pieces(np.array([[t]]), ts.til), ts.column_height)
        image = compose(placements, size, ts.column_frames)
        tile_frames.append(image)
        record = write_checked(ctx, image, palette, dest / "tiles", f"t{t:04d}")
        tile_records.append({"id": t, "columns": list(ts.til[t]),
                             "png": f"tiles/{record['png']}" if "png" in record else None})
    write_sheet([tile_frames[r : r + 16] for r in range(0, len(tile_frames), 16)], palette, dest / "sheet.png")

    write_json(dest / "tileset.json", {
        "source": {**ts.sources, "archive": ts.archive, "path": entry.path, "sha1": sha1(data)},
        "palette": rel_path(entry.palette),
        "palette_alternatives": [rel_path(p) for p in entry.palette_alternatives],
        "cells_per_column": ts.spec.cells_per_column,
        "column_size_px": [64, ts.column_height],
        "columns": column_records,
        "tiles": tile_records,
        "cell_users": {str(k): v for k, v in sorted(cell_users(ts.columns).items())},
        "unreferenced_cells": ts.unreferenced,
    })
    return {"columns": len(column_records), "tiles": len(tile_records)}


def export_layout(ctx: Context, entry: Entry, archive: str, data: bytes, dest: Path) -> dict:
    dun = parse_dun(data)
    ts = ctx.tileset(entry.tileset)
    pieces = tile_pieces(dun.tiles.astype(np.int32) - 1, ts.til)
    placements, size = place_pieces(pieces, ts.column_height)
    image = compose(placements, size, ts.column_frames)
    record = write_checked(ctx, image, ctx.palette(entry.palette), dest, "layout")
    write_json(dest / "layout.json", {
        "source": source(archive, entry.path, data),
        "tileset": rel_path(entry.tileset),
        "palette": rel_path(entry.palette),
        "palette_alternatives": [rel_path(p) for p in entry.palette_alternatives],
        "size_tiles": [dun.width, dun.height],
        "size_px": [size[0], size[1]],
        "column_height_px": ts.column_height,
        "image": record,
        "placements": [{"column": p.column, "x": p.x, "y": p.y} for p in placements],
    })
    return {"placements": len(placements)}
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_handlers_tileset.py tests/test_handlers.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/dtx/handlers.py tests/test_handlers_tileset.py
git commit -m "feat: export tilesets and DUN layouts with placements"
```

---

### Task 17: Extraction orchestrator, report, manifest and `dtx extract`

**Files:**
- Create: `src/dtx/extract.py`
- Modify: `src/dtx/cli.py` (register `extract`)
- Test: `tests/test_extract.py`

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `HD_CONTRACT: dict`.
  - `destination(out: Path, entry: Entry, archive_prefix: str | None = None) -> Path`; `record_path(entry, dest) -> Path`.
  - `process_entry(ctx, entry, force: bool) -> list[dict]` — result dicts with `status` in `exported | unchanged | skipped | failed`.
  - `extract_with(stack, out, *, only=None, verify=False, force=False, widths=None, variants=None) -> dict` (single process; returns the report).
  - `run_extract(game_dir, out, *, only=None, verify=False, force=False, jobs=1) -> dict`.
  - Writes `out/report.json` and `out/manifest.json`.
  - CLI: `dtx extract --game DIR --out DIR [--only KIND,...] [--verify] [--force] [--jobs N]`, exit code 1 when `summary.failed > 0`.

- [ ] **Step 1: Write the failing tests**

`tests/test_extract.py`:
```python
import json

import numpy as np

from builders import cel_frame, dun_bytes, min_bytes, pcx, sheet, til_bytes
from fakes import FakeArchive
from dtx.extract import extract_with
from dtx.mpq import ArchiveStack

PAL = bytes(range(256)) * 3
KEY = "levels\\l1data\\l1"
COLUMN = [(0, 0)] * 8 + [(1, 0), (0, 0)]
BASE = {
    "levels\\towndata\\town.pal": PAL,
    "levels\\l1data\\l1_1.pal": PAL,
    f"{KEY}.cel": sheet([bytes([10]) * 1024]),
    f"{KEY}.min": min_bytes([COLUMN]),
    f"{KEY}.til": til_bytes([(0, 0, 0, 0)]),
    f"{KEY}.sol": bytes([0]),
    "levels\\l1data\\a.dun": dun_bytes([[1]]),
    "ui_art\\title.pcx": pcx(np.zeros((2, 2), np.uint8), np.zeros((256, 3), np.uint8)),
    "data\\good.cel": sheet([cel_frame([[1, 2]])]),
    "sfx\\x.wav": b"RIFF",
}


def run(tmp_path, files, **kw):
    archives = [FakeArchive("DIABDAT.MPQ", files, unnamed=["File00000001.xxx"])]
    if "hellfire" in kw:
        archives.insert(0, FakeArchive("hellfire.mpq", kw.pop("hellfire")))
    stack = ArchiveStack(archives)
    return extract_with(stack, tmp_path / "out", widths={"data\\good.cel": 2}, variants={}, verify=True, **kw)


def test_full_run_writes_report_and_manifest(tmp_path):
    report = run(tmp_path, BASE)
    out = tmp_path / "out"
    assert report["summary"]["failed"] == 0
    assert (out / "assets/levels/l1data/l1/tileset.json").exists()
    assert (out / "assets/levels/l1data/a.dun/layout.json").exists()
    assert (out / "assets/ui_art/title.pcx/meta.json").exists()
    assert (out / "assets/data/good.cel/meta.json").exists()
    assert (out / "palettes/levels/l1data/l1_1.pal.json").exists()
    saved = json.loads((out / "report.json").read_text())
    assert {"path": "sfx\\x.wav", "reason": "not graphics"} in saved["skipped"]
    assert saved["unnamed"] == {"DIABDAT.MPQ": ["File00000001.xxx"]}
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["hd_contract"]["scale"].startswith("integer")
    assert any(a["path"] == "data\\good.cel" and a["record"] == "assets/data/good.cel/meta.json"
               for a in manifest["assets"])


def test_second_run_is_unchanged_unless_forced(tmp_path):
    run(tmp_path, BASE)
    again = run(tmp_path, BASE)
    assert again["summary"]["exported"] == 0 and again["summary"]["unchanged"] > 0
    forced = run(tmp_path, BASE, force=True)
    assert forced["summary"]["unchanged"] == 0


def test_one_bad_file_does_not_stop_export(tmp_path):
    # Review Focus 5 (isolation)
    report = run(tmp_path, {**BASE, "data\\bad.cel": b"\xff\xff\xff\xff\x00\x00"})
    assert report["summary"]["failed"] == 1
    assert report["failed"][0]["path"] == "data\\bad.cel"
    assert (tmp_path / "out/assets/data/good.cel/meta.json").exists()


def test_identical_versions_export_once(tmp_path):
    # Review Focus 4
    report = run(tmp_path, BASE, hellfire={"data\\good.cel": BASE["data\\good.cel"]})
    assert not (tmp_path / "out/assets/@DIABDAT.MPQ").exists()
    assert [r["archive"] for r in report["exported"] if r["path"] == "data\\good.cel"] == ["hellfire.mpq"]


def test_different_versions_export_archive_copy(tmp_path):
    # Review Focus 4
    newer = sheet([cel_frame([[3, 4]])])
    run(tmp_path, BASE, hellfire={"data\\good.cel": newer})
    assert (tmp_path / "out/assets/data/good.cel/meta.json").exists()
    assert (tmp_path / "out/assets/@DIABDAT.MPQ/data/good.cel/meta.json").exists()


def test_only_filter(tmp_path):
    report = run(tmp_path, BASE, only={"palette"})
    kinds = {r["kind"] for r in report["exported"]}
    assert kinds == {"palette"}
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_extract.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'dtx.extract'`.

- [ ] **Step 3: Implement**

`src/dtx/extract.py`:
```python
from __future__ import annotations

import json
import os
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path

from dtx import refdata
from dtx.catalog import SPRITE_KINDS, Entry, build_catalog
from dtx.export import write_json
from dtx.handlers import (
    Context, export_image, export_layout, export_palette, export_sprite, export_tileset, export_trn,
    record_name, sha1,
)
from dtx.mpq import ArchiveStack
from dtx.paths import rel_path

HD_CONTRACT = {
    "scale": "integer k >= 1, chosen once per asset",
    "rule": "a replacement for a frame, cell or column must be exactly (w*k, h*k) of the original; "
            "all offsets, anchors and placements scale by the same k",
    "units": ["frame", "cell", "column"],
    "fidelity": "exported *.idx.png files hold the exact original palette indices (L) and opacity (A)",
}
HANDLERS = {
    "palette": export_palette, "trn": export_trn, "ui_image": export_image,
    "tileset": export_tileset, "layout": export_layout,
    **{kind: export_sprite for kind in SPRITE_KINDS},
}
SINGLE_VERSION_KINDS = {"tileset", "layout"}


def destination(out: Path, entry: Entry, archive_prefix: str | None = None) -> Path:
    root = out / ("palettes" if entry.kind == "palette" else "assets")
    if archive_prefix:
        root = root / f"@{archive_prefix}"
    name = entry.tileset if entry.kind == "tileset" else entry.path
    return root / rel_path(name)


def record_path(entry: Entry, dest: Path) -> Path:
    name = record_name(entry.kind)
    return dest.parent / (dest.name + ".json") if name is None else dest / name


def _recorded_sha1(path: Path) -> str | None:
    try:
        return json.loads(path.read_text())["source"]["sha1"]
    except (OSError, ValueError, KeyError, TypeError):
        return None


def process_entry(ctx: Context, entry: Entry, force: bool) -> list[dict]:
    versions = ctx.stack.versions(entry.path)
    if not versions:
        return [{"status": "failed", "path": entry.path, "kind": entry.kind, "error": "not found in any archive"}]
    results = []
    seen: set[str] = set()
    for n, (archive, data) in enumerate(versions):
        digest = sha1(data)
        if digest in seen:
            continue
        seen.add(digest)
        base = {"path": entry.path, "archive": archive, "kind": entry.kind}
        if n > 0 and entry.kind in SINGLE_VERSION_KINDS:
            results.append({**base, "status": "skipped",
                            "reason": "overridden tileset/layout versions are not exported"})
            continue
        dest = destination(ctx.out, entry, archive if n > 0 else None)
        record = record_path(entry, dest)
        rel_record = record.relative_to(ctx.out).as_posix()
        if not force and _recorded_sha1(record) == digest:
            results.append({**base, "status": "unchanged", "sha1": digest, "record": rel_record})
            continue
        try:
            info = HANDLERS[entry.kind](ctx, entry, archive, data, dest)
        except Exception as exc:  # per-file isolation: one bad file never stops the export
            results.append({**base, "status": "failed", "error": f"{type(exc).__name__}: {exc}"})
            continue
        results.append({**base, "status": "exported", "sha1": digest, "record": rel_record, **info})
    return results


def _finish(out: Path, results: list[dict], skips: list, unnamed: dict) -> dict:
    by_status: dict[str, list[dict]] = {"exported": [], "unchanged": [], "skipped": [], "failed": []}
    for r in results:
        by_status[r["status"]].append(r)
    skipped = [asdict(s) for s in skips] + [
        {"path": r["path"], "archive": r["archive"], "reason": r["reason"]} for r in by_status["skipped"]
    ]
    report = {
        "summary": {
            "exported": len(by_status["exported"]),
            "unchanged": len(by_status["unchanged"]),
            "skipped": len(skipped),
            "failed": len(by_status["failed"]),
            "unnamed": sum(len(v) for v in unnamed.values()),
            "by_kind": dict(Counter(r["kind"] for r in by_status["exported"] + by_status["unchanged"])),
        },
        "exported": by_status["exported"],
        "unchanged": by_status["unchanged"],
        "skipped": skipped,
        "failed": by_status["failed"],
        "unnamed": unnamed,
    }
    manifest = {
        "version": 1,
        "hd_contract": HD_CONTRACT,
        "devilutionx_reference": refdata.PINNED_DEVILUTIONX,
        "assets": [
            {k: r[k] for k in ("path", "kind", "archive", "sha1", "record")}
            for r in sorted(by_status["exported"] + by_status["unchanged"], key=lambda r: (r["path"], r["archive"]))
        ],
    }
    write_json(out / "report.json", report)
    write_json(out / "manifest.json", manifest)
    return report


def _catalog(stack, only, widths, variants):
    names, unnamed = stack.names()
    entries, skips = build_catalog(names, widths, variants)
    if only:
        entries = [e for e in entries if e.kind in only]
    return entries, skips, unnamed


def extract_with(stack, out: Path, *, only=None, verify=False, force=False, widths=None, variants=None) -> dict:
    out = Path(out)
    widths = refdata.load_widths() if widths is None else widths
    variants = refdata.load_variants() if variants is None else variants
    entries, skips, unnamed = _catalog(stack, only, widths, variants)
    ctx = Context(stack, out, verify)
    results = [r for e in entries for r in process_entry(ctx, e, force)]
    return _finish(out, results, skips, unnamed)


_WORKER: Context | None = None


def _init_worker(game_dir: str, out: str, verify: bool) -> None:
    global _WORKER
    _WORKER = Context(ArchiveStack.open_game(Path(game_dir), refdata.listfile_path()), Path(out), verify)


def _work(entry: Entry, force: bool) -> list[dict]:
    assert _WORKER is not None
    return process_entry(_WORKER, entry, force)


def run_extract(game_dir: Path, out: Path, *, only=None, verify=False, force=False, jobs=1) -> dict:
    out = Path(out)
    with ArchiveStack.open_game(game_dir, refdata.listfile_path()) as stack:
        if jobs <= 1:
            return extract_with(stack, out, only=only, verify=verify, force=force)
        entries, skips, unnamed = _catalog(stack, only, refdata.load_widths(), refdata.load_variants())
    results: list[dict] = []
    with ProcessPoolExecutor(max_workers=jobs, initializer=_init_worker,
                             initargs=(str(game_dir), str(out), verify)) as pool:
        futures = [pool.submit(_work, e, force) for e in entries]
        for done, future in enumerate(as_completed(futures), 1):
            results.extend(future.result())
            if done % 250 == 0 or done == len(futures):
                print(f"{done}/{len(futures)} files processed", flush=True)
    return _finish(out, results, skips, unnamed)


def default_jobs() -> int:
    return max(1, (os.cpu_count() or 2) - 1)
```

In `src/dtx/cli.py`, add inside `build_parser()` before `return parser`:
```python
    ex = sub.add_parser("extract", help="export all graphics")
    ex.add_argument("--game", type=Path, required=True)
    ex.add_argument("--out", type=Path, required=True)
    ex.add_argument("--only", help="comma-separated kinds to export")
    ex.add_argument("--verify", action="store_true", help="reload every index PNG and compare")
    ex.add_argument("--force", action="store_true", help="re-export files that are unchanged")
    ex.add_argument("--jobs", type=int, default=None, help="worker processes (default: CPUs - 1)")
    ex.set_defaults(func=_extract)
```
and add the function:
```python
def _extract(args) -> int:
    from dtx.catalog import KINDS
    from dtx.extract import default_jobs, run_extract

    only = None
    if args.only:
        only = {k.strip() for k in args.only.split(",") if k.strip()}
        unknown = only - set(KINDS)
        if unknown:
            print(f"unknown kinds: {', '.join(sorted(unknown))}; valid: {', '.join(KINDS)}")
            return 2
    report = run_extract(args.game, args.out, only=only, verify=args.verify, force=args.force,
                         jobs=args.jobs or default_jobs())
    s = report["summary"]
    print(f"exported {s['exported']}, unchanged {s['unchanged']}, skipped {s['skipped']}, "
          f"failed {s['failed']}, unnamed {s['unnamed']} -> {args.out / 'report.json'}")
    return 1 if s["failed"] else 0
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest -v`
Expected: all unit tests PASS; game tests skipped.

- [ ] **Step 5: Commit**

```bash
git add src/dtx/extract.py src/dtx/cli.py tests/test_extract.py
git commit -m "feat: orchestrate extraction with report, manifest and versions"
```

---

### Task 18: Game-data integration tests, full export and visual check

**Files:**
- Create: `tests/test_game.py`
- Modify: any module where the real data exposes a bug (each fix gets a unit test that reproduces the pattern with synthetic bytes, written before the fix)

**Interfaces:**
- Consumes: everything above.
- Produces: a verified `out/` export and a passing `DTX_GAME_DIR` test suite.

- [ ] **Step 1: Write the integration tests**

`tests/test_game.py`:
```python
import json

import pytest

from dtx import refdata
from dtx.catalog import build_catalog
from dtx.formats.pcx import decode_pcx
from dtx.formats.sheet import split_sheet
from dtx.formats.width import scan_frame
from dtx.handlers import Context
from dtx.mpq import ArchiveStack

pytestmark = pytest.mark.game


@pytest.fixture(scope="module")
def stack(game_dir):
    with ArchiveStack.open_game(game_dir, refdata.listfile_path()) as s:
        yield s


def test_title_is_640x480(stack):
    frame, _ = decode_pcx(stack.read("ui_art\\title.pcx")[1])
    assert (frame.width, frame.height) == (640, 480)


def test_town_palette_size(stack):
    assert len(stack.read("levels\\towndata\\town.pal")[1]) == 768


def test_tileset_geometry(stack, tmp_path):
    ctx = Context(stack, tmp_path, False)
    assert ctx.tileset("levels\\l1data\\l1").column_frames[0].height == 160
    assert ctx.tileset("levels\\towndata\\town").column_frames[0].height == 256


def test_cl2_skip_table_assumption(stack):
    """Frames with table widths must satisfy the skip-table rule (plan Task 6 assumption)."""
    widths = refdata.load_widths()
    checked = matched = 0
    for name in [n for n in widths if n.startswith("monsters\\")][:20]:
        found = stack.read(name)
        if not found:
            continue
        for group in split_sheet(found[1]):
            for raw in group:
                checked += 1
                matched += scan_frame("cl2", raw).fits(widths[name])
    assert checked > 0
    assert matched / checked >= 0.99, f"{matched}/{checked} frames satisfy the skip-table rule"


def test_listfile_coverage(stack):
    named, unnamed = stack.names()
    total_unnamed = sum(len(v) for v in unnamed.values())
    assert total_unnamed / (len(named) + total_unnamed) <= 0.01


def test_every_graphics_file_is_catalogued(stack):
    named, _ = stack.names()
    entries, skips = build_catalog(named, refdata.load_widths(), refdata.load_variants())
    graphics_skips = [s for s in skips if s.path.endswith((".cel", ".cl2", ".pcx")) and "part of tileset" not in s.reason]
    assert graphics_skips == []
```

- [ ] **Step 2: Run the integration tests**

Run: `DTX_GAME_DIR=~/diablo1-hellfire-gog uv run pytest tests/test_game.py tests/test_mpq_game.py -v`
Expected: PASS. If `test_cl2_skip_table_assumption` fails, the skip offsets are not relative to the frame start or runs do cross the 32-row boundaries: dump one failing frame's header and `run_starts`, fix `Cl2Scan.fits` to the observed rule, add a unit test in `tests/test_cl2.py` with synthetic bytes that follow the observed rule, and rerun.

- [ ] **Step 3: Run the full export**

Run: `uv run dtx extract --game ~/diablo1-hellfire-gog --out out --verify`
Expected: exits 0 and prints `failed 0`. If it exits 1, open `out/report.json`, group `failed` entries by `error`, and for each distinct error: write a failing unit test with synthetic bytes reproducing the pattern, fix, rerun only the affected kind with `--only <kind> --force`, then rerun the full command.

- [ ] **Step 4: Check coverage in the report**

Run: `python3 -c "import json; r=json.load(open('out/report.json')); print(r['summary']); print({k: len(v) for k, v in r['unnamed'].items()}); print(sorted({s['reason'] for s in r['skipped']}))"`
Expected: `failed` is 0, `by_kind` includes every kind in `KINDS` that exists in the game (`palette, trn, ui_image, tileset, layout, monster_anim, player_anim, towner_anim, missile, object, item, ui_sprite, level_sprite`), unnamed entries are ≤ 1% of each graphics archive, and skip reasons are only `not graphics`, `part of tileset …`, `layout directory has no known tileset` and `overridden tileset/layout versions are not exported`.

- [ ] **Step 5: Visual check**

Open these with the Read tool (or an image viewer) and confirm there is no shearing (wrong width) and no false colours (wrong palette):
- `out/assets/levels/towndata/town/sheet.png` and `out/assets/levels/towndata/sector1s.dun/layout.png`
- `out/assets/levels/l1data/l1/sheet.png`, `l2`, `l3`, `l4` equivalents
- `out/assets/nlevels/l5data/l5/sheet.png`, `out/assets/nlevels/l6data/l6/sheet.png`
- `out/assets/monsters/zombie/zombiew.cl2/sheet.png`
- `out/assets/plrgfx/warrior/wls/wlsaw.cl2/sheet.png`
- `out/assets/ui_art/title.pcx/image.png`

Also list every asset with `width_source` of `inferred` or `inferred_per_frame`:
`grep -rl '"width_source": "inferred' out/assets --include=meta.json | head -50`
and open a sample of their `sheet.png` files. For any file that shows shearing, add its correct width to `MANUAL_WIDTHS` in `src/dtx/refdata.py` (with the DevilutionX source line it comes from), rerun `dtx refdata build`, and rerun `dtx extract --only <kind> --force`.

If columns look upside down (floor at the top), the MIN row order assumption in Task 9 is inverted: fix `compose_column` to place row 0 at the bottom, update `test_compose_column_places_top_row_first` to match, and re-export tilesets and layouts.

- [ ] **Step 6: Commit**

```bash
git add tests/test_game.py src tests
git commit -m "test: verify full export against the GOG game data"
```

---

## Self-Review Notes

- Spec coverage: §2 units → Tasks 1–17; §3.1 versions → Task 17; §3.2 image pairs and sheets → Tasks 11, 15; §3.3 `meta.json` → Task 15; §3.4 `tileset.json` → Task 16; §3.5 `layout.json` and crop formula → Tasks 10, 16; §3.6 HD contract → Task 17; §4.1 listfile → Task 13; §4.2 catalog → Task 14; §4.3 width inference → Task 7; §4.4 palettes and cycling → Tasks 2, 15; §5 error handling → Tasks 12 (missing StormLib), 17 (isolation, exit code, idempotency); §6 tests → every task plus Task 18; §7 definition of done → Task 18 Steps 3–5.
- Known deliberate limits (recorded in the report, not silent): overridden tileset/layout versions are skipped with a reason; idempotency for tilesets keys on the `.cel` hash only.
