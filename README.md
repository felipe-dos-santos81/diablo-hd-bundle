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
