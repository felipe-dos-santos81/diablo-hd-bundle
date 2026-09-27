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

Status: the export, the kit, the caption review, the live check and the spike
are done (see the kit's `NOTES.md`); the full run (about 11,400 base and 6,000
variant sheets, roughly a week on a GB10) runs unattended:

```bash
cd diablo-texture-enhancement
make run          # start or resume: bases, then variants, then verify
make run-status   # where it is; make run-log follows the log; make run-stop stops it
```

Neither project commits game data or generated art: `out/`, `data/` and
`reviews.yaml` are gitignored. You need your own copy of the game.

Design: [`docs/superpowers/specs/2026-09-26-diablo-animation-regeneration-design.md`](docs/superpowers/specs/2026-09-26-diablo-animation-regeneration-design.md).
Plan: [`docs/superpowers/plans/2026-09-26-diablo-animation-regeneration.md`](docs/superpowers/plans/2026-09-26-diablo-animation-regeneration.md).
