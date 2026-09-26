# Diablo + Hellfire Graphics Exporter — Design

Date: 2026-09-26
Status: Approved design, pending spec review

## 1. Goal

Extract every graphic from the GOG Diablo + Hellfire game data so it can be regenerated at HD resolution by AI, and later loaded by a future forked DevilutionX that supports HD true-colour sprites.

This project is **only the exporter**. It must emit lossless pixels and complete metadata so that regenerated images can be mapped back onto the original assets. It does not modify the engine, repack MPQs, or run any AI.

### Inputs

`~/diablo1-hellfire-gog/`:

| Archive | Size | In scope |
|---|---|---|
| `DIABDAT.MPQ` | 518 MB | yes — base game |
| `hellfire.mpq` | 65 MB | yes — Hellfire content |
| `hfmonk.mpq` | 38 MB | yes — Monk class |
| `hfmusic.mpq` | 34 MB | no — audio only |
| `hfvoice.mpq` | 38 MB | no — audio only |

### Scope: all graphics

UI/menu art (PCX, CEL), town and dungeon tilesets (CEL+MIN+TIL+SOL for town, L1–L4, Hellfire crypt/nest), DUN layouts, monsters, player characters (all classes × armour × weapon × animation), towners, items (ground, flip, inventory), missiles/spell effects, objects, control panel, fonts, palettes and colour-translation tables (TRN).

### Non-goals

- Engine changes, HD loading, repacking into MPQ/mod format.
- Byte-identical re-encoding of CEL/CL2. Round-trip fidelity is defined at the palette-index level.
- Audio, video (SMK), text data.

## 2. Architecture

Python 3.12 package `dtx`, managed with `uv`. MPQ access through StormLib (Homebrew `stormlib`, loaded via `ctypes`) because Diablo MPQs use PKWare DCL implode compression and have no internal `(listfile)`. Format decoders written in Python (numpy + Pillow), using DevilutionX source (pinned commit) as the reference specification.

CLI:

```
dtx extract --game ~/diablo1-hellfire-gog --out ./out [--only KIND[,KIND...]] [--verify] [--force]
dtx listfile build --devilutionx PATH --community PATH   # regenerates data/listfile.txt
```

### Units

| Unit | Responsibility | Depends on |
|---|---|---|
| `dtx.mpq` | ctypes StormLib wrapper: open archives read-only, read file by name, enumerate hash-table entries. Archive stack resolves names in priority order `hfmonk > hellfire > DIABDAT`. When a name exists in several archives with different content, every distinct version is exported (see §3.1). | StormLib |
| `dtx.listfile` | Load `data/listfile.txt`; build it from sources (§4.1); report which hash entries are named. | `mpq` |
| `dtx.formats.pal` | 768-byte palette → `(256, 3) uint8`. | numpy |
| `dtx.formats.pcx` | PCX (8-bit, RLE, trailing 256-colour palette) → index array + palette. | numpy |
| `dtx.formats.cel` | CEL (single and grouped headers) → list of frames (index array + alpha mask), given width. Level-cell variants (square, triangle/trapezoid transparency types) decoded by draw type. | numpy |
| `dtx.formats.cl2` | CL2 (single and grouped) → frames, given width. | numpy |
| `dtx.formats.trn` | 256-byte index translation table. | numpy |
| `dtx.formats.tileset` | MIN (column cell lists, cell frame index + draw type), TIL (4 columns per tile), SOL (per-column flags), DUN (tile grid + optional layers). | numpy |
| `dtx.formats.width` | Frame-width inference fallback. | `cel`, `cl2` |
| `dtx.catalog` | Ordered rule table: path → `kind`, palette, frame width (source), group layout, TRN variants. The only unit containing game knowledge. | `listfile` |
| `dtx.export` | Write RGBA PNG + index-map PNG per frame, `meta.json`, sheets. | Pillow |
| `dtx.render` | Tileset context renders (tiles, contact sheet) and DUN layout renders with placements. | `formats`, `export` |
| `dtx.verify` | Reload index-map PNGs + metadata, compare to decoder output exactly. | `formats` |
| `dtx.report` | Coverage report and manifest. | all |

Decoders are pure (bytes in, arrays out; no I/O, no catalog knowledge). The catalog knows nothing about pixel decoding. This keeps each unit testable in isolation and lets a future HD engine tool reuse decoders and schema.

## 3. Output layout and metadata

Output paths mirror archive paths, lower-cased, `\` → `/`. Each source file becomes a directory named after the file.

```
out/
  manifest.json
  report.json
  palettes/<path>.pal.png          16×16 swatch
  palettes/<path>.pal.json         RGB list + cycling ranges
  assets/
    ui_art/title.pcx/
      meta.json  image.png  image.idx.png
    monsters/zombie/zombiea.cl2/
      meta.json  d0/f000.png  d0/f000.idx.png  ...  sheet.png
    levels/l1data/l1/                  tileset (from l1.cel + l1.min + l1.til + l1.sol)
      tileset.json
      columns/m0000.png  m0000.idx.png ...     editable unit
      cells/c0000.png  c0000.idx.png ...       reference only
      tiles/t0000.png ...                      context
      sheet.png                                context contact sheet of all tiles
    levels/towndata/town.dun/
      layout.png  layout.json                  context
```

### 3.1 Archive versions

`manifest.json` records, per logical path, the archive it was taken from. If a path exists in more than one archive with differing SHA-1, the winning (highest-priority) version is exported at the normal path and each overridden version under `assets/@<archive>/<path>/`.

### 3.2 Images

Every frame is written twice:

- `*.png` — RGBA, rendered through the asset's assigned palette, alpha 0 for transparent pixels. This is the AI input.
- `*.idx.png` — 8-bit greyscale + alpha (`LA`): L = palette index, A = 0 or 255. This is the lossless source of truth; it allows re-rendering under any palette or TRN.

`sheet.png` per animation: frames laid out one row per group (direction), for AI context and visual checking.

### 3.3 `meta.json` (sprites and single images)

```json
{
  "source": {"archive": "DIABDAT.MPQ", "path": "monsters\\zombie\\zombiea.cl2", "sha1": "…"},
  "format": "cl2",
  "kind": "monster_anim",
  "palette": "levels/towndata/town.pal",
  "palette_alternatives": [],
  "variants": [{"trn": "monsters/zombie/bluered.trn"}],
  "width_source": "table",
  "groups": 8,
  "group_label": "direction",
  "frames": [
    {"group": 0, "i": 0, "w": 128, "h": 128, "png": "d0/f000.png", "idx": "d0/f000.idx.png"}
  ]
}
```

Single-image assets (PCX) use `groups: 1` and one frame with `png: "image.png"`. `width_source` is `"header"`, `"table"` or `"inferred"`.

### 3.4 `tileset.json`

```json
{
  "source": {"cel": "…", "min": "…", "til": "…", "sol": "…", "archive": "DIABDAT.MPQ"},
  "palette": "levels/l1data/l1_1.pal",
  "palette_alternatives": ["levels/l1data/l1_2.pal", "…"],
  "column_height": 10,
  "column_size_px": [64, 320],
  "columns": [
    {"id": 0, "png": "columns/m0000.png", "idx": "columns/m0000.idx.png",
     "cells": [{"slot": 0, "frame": 12, "draw_type": 1}, {"slot": 1, "frame": 0, "draw_type": 0}],
     "sol": {"solid": false, "block_light": false, "block_missile": false, "transparent": false}}
  ],
  "tiles": [{"id": 0, "columns": [0, 1, 2, 3], "png": "tiles/t0000.png"}],
  "cell_users": {"12": [0, 57]}
}
```

- `column_height` is the number of 32-px cell rows (town/L4: 16; L1–L3, crypt, nest: 10). Columns are rendered as 64 × (32·column_height) pixels.
- Cell `slot` enumerates left/right halves row-by-row as in MIN; `frame: 0` means empty.
- The HD engine replaces **whole columns**. `cell_users` exposes shared cells so tooling can detect inconsistency.

### 3.5 `layout.json`

```json
{
  "source": {"dun": "levels\\towndata\\sector1s.dun", "archive": "DIABDAT.MPQ"},
  "tileset": "levels/l1data/l1",
  "size_px": [3072, 1856],
  "placements": [{"column": 57, "x": 1024, "y": 288}]
}
```

Slicing a layout regenerated at integer scale *k*: each placement yields crop `(x·k, y·k, 64·k, colH·k)` as a candidate for its column. Columns placed multiple times yield multiple candidates; choosing among them is out of scope.

### 3.6 HD contract (recorded in `manifest.json`)

A replacement image for a frame, cell, or column must be exactly `(w·k, h·k)` for one integer `k` per asset; all offsets and anchors scale by the same `k`.

## 4. Catalog, palettes, filename discovery

### 4.1 Listfile

`data/listfile.txt` is committed and regenerated by `dtx listfile build`, which merges:

1. Asset path strings extracted from DevilutionX source at a pinned commit (data tables and literals).
2. A community Diablo I listfile.
3. Pattern expansion from naming conventions, e.g. `plrgfx/{class}/{c}{armour}{weapon}/{c}{armour}{weapon}{anim}.cl2` and monster names from the monster data table.

A name is kept only if its hash exists in an in-scope archive. Unnamed hash entries are listed in `report.json`.

### 4.2 Catalog rules

Ordered rules; the first match wins. Unmatched named files that are graphics by extension (`.cel`, `.cl2`, `.pcx`) are exported with inferred width and `kind: "unknown_graphic"`; other unmatched files are reported as skipped with the reason `not graphics`.

| Match (examples) | kind | palette | width source |
|---|---|---|---|
| `ui_art/*.pcx`, `gendata/*.pcx` | `ui_image` | embedded PCX palette | header |
| `levels/l{1..4}data/l?.cel` (+ `.min/.til/.sol`), `levels/towndata/town.*` | `tileset` | `l?_1.pal` / `town.pal`; others as alternatives | fixed 32×32 cells |
| `nlevels/l5data/*`, `nlevels/l6data/*`, `nlevels/towndata/*` | `tileset` | Hellfire crypt / nest / town palettes | fixed |
| `levels/**/*.dun`, `nlevels/**/*.dun` | `layout` | owning tileset's palette | n/a |
| `monsters/**/*.cl2` | `monster_anim` | `town.pal` | monster data table |
| `plrgfx/**/*.cl2` | `player_anim` | `town.pal` | class/animation table (96 or 128) |
| `towners/**` | `towner_anim` | `town.pal` | table |
| `items/*.cel`, `data/inv/*.cel` | `item` | `town.pal` | table |
| `objects/*.cel`, `nlevels/**/objects` | `object` | per-level default | table |
| `missiles/*.cl2` | `missile` | `town.pal` | table |
| `ctrlpan/*.cel`, `data/*.cel`, fonts | `ui_sprite` | `town.pal` or UI palette | table |

Tables (monster, missile, object, item widths) are transcribed from DevilutionX data at the pinned commit into `data/*.toml`.

### 4.3 Width inference

For CEL/CL2 frames without a table width: try candidate widths (multiples of 2 from 2 to 640, most likely first: 32, 64, 96, 128, 160, 180, 192, 256, …); accept the first for which every frame decodes with rows ending exactly on row boundaries and total pixels divisible by width. If none is accepted, the file is recorded as failed. Result stored as `width_source: "inferred"`.

### 4.4 Palettes

Every `.pal` exported as an asset with a swatch image and JSON. Palette JSON records colour-cycling index ranges per DevilutionX's palette code (e.g. caves water, hell lava, Hellfire crypt/nest). Since index maps are lossless, the default palette choice never loses information.

## 5. Error handling

- Per-file isolation: exceptions are caught per source file, recorded in `report.failed` with the path and message, and extraction continues.
- Exit code: non-zero if `failed > 0` or any verification mismatch.
- MPQs opened read-only.
- Idempotent re-runs: a file whose `meta.json` source SHA-1 matches is skipped unless `--force`.
- Missing StormLib: fail fast with an install hint (`brew install stormlib`).

## 6. Testing

### Unit (no game data; CI-safe, no copyrighted bytes in the repo)

- Per decoder: hand-built byte fixtures written in the test file with expected index arrays — empty frames, fully transparent rows, max-length runs, grouped CEL/CL2, every level-cell draw type.
- Width inference: fixtures valid only at one width.
- Catalog: path → kind/palette/width-source, including overlapping rules and the unknown-graphic fallback.
- Export + verify: synthetic asset round-trips exactly; a one-pixel corruption is detected.
- Layout slicing: synthetic placements yield expected crop rectangles at k = 1 and k = 4.

### Integration (`@pytest.mark.game`, requires `DTX_GAME_DIR`)

- Wrapper opens all in-scope archives and reads known files.
- Known facts: `ui_art/title.pcx` is 640×480; `town.pal` has 256 entries; L1 `column_height == 10`, town `column_height == 16`.
- Full `dtx extract --verify`: zero failures, zero mismatches; listfile names ≥ 99% of hash entries in graphics archives, remaining gap reported.

### Visual (manual, once)

Inspect contact sheets and layout renders for town, L1–L4, crypt, nest. Wrong width shows as shearing; wrong palette as false colours.

## 7. Definition of done

- Every graphics file in `DIABDAT.MPQ`, `hellfire.mpq`, `hfmonk.mpq` is exported and verified, or listed in `report.json` with a reason.
- Every tileset has columns, cells, tiles, a contact sheet and `tileset.json`.
- Every DUN has `layout.png` + `layout.json`.
- `manifest.json` contains the HD contract.
- Unit tests pass; integration suite passes against the local GOG install.
