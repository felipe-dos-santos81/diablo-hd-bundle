# NOTES

Live checks, spikes and runs of the Diablo animation kit, newest last.

## Extraction

The export (`../diablo-textures-exporter/out`, exporter 97939cd, DevilutionX 8bef7bc):
1,791 animations (1,056 player, 334 monster, 21 towner, 380 missile), 145,560
frames, every one on `levels/towndata/town.pal`; 182 monster animations carry 97
distinct TRNs (about 74,000 variant frames). `monsters/darkmage/dmagew.cl2`
has no frames. Layout at the defaults: 11,394 base sheets; 17,410 with
variants (11,386 packed); about 9.8 gigapixels of canvas a pass; 1,866 sheets
over 1 MP, the largest 1952x1440 (`monsters/nkr/nkrd.cl2`).

## Captions (spike characters)

`make caption` seeded 251 characters and captioned the six spike characters in
6 min 15 s. Four of six needed fixing against their contact sheets: the
warrior's one steel pauldron and one-handed mace had been read as "a large
object on his back" and "a long-handled polearm"; the zombie's olive rotting
skin as "exposed bone, skull, ribs"; nkr's blade-tipped back tentacles as
"antennae or horns"; the smith's grey beard as "a grey collar or scarf".
Magma's second image (its lava-rock projectile) was tidied; the fireball's
caption was right. The VLM also calls the anchor's eight first frames "a walk
cycle" when the anchor is a standing animation.

## Live check

ComfyUI c194dd0, Qwen-Image 2.1 bf16, `monsters/zombie/zombien.cl2` (idle,
11 frames a direction, sheets 512x480 to 576x544), `dst=data/spike/live*`.
The two-reference graph runs: s01 renders with no anchor, s02-s08 with s01's
canvas as `images.image_2`.

**Denoise 1.0 (the plan's default) moves cells.** Three attempts at s01: whole
rows of cells 2.9 px up (attempt 1), 1-3 px every way (attempt 2, with the
geometry correction), 3-11 px and edge agreement 0.74 (attempt 3). All
rejected. The painting itself was good.

**Denoise 0.9 keeps the layout** (shift ≤ 0.3 native px, edge agreement
0.98-1.0 over two attempts) but failed consistency: every pair of frames
changes 8-11 levels where the idle source changes 2-4, a uniform shimmer of
per-cell brushwork rather than a jump (the 1.0 renders had jumps of 25-31).

**The shadow turned grey.** Diablo's ground shadow is opaque pure black
(0,0,0); the repaint made it grey speckle (mean 41 at 0.9, 66 at 1.0), which
the game would draw as a grey blob. Forcing it back to black lowers the
shimmer by 1-1.5 levels.

Decisions (the user, after the GIFs in `data/preview/live-check/`):
- the default workflow runs at denoise 0.9 (the template's value); the
  fallback `qwen-image-2.1-i2i-faithful` at 0.8;
- the ground shadow is locked: a source pixel that is opaque pure black stays
  pure black (`sheet_layout.keep_shadow`, in `finish_sheet` after the colour
  match);
- `FLICKER_FLOOR` 4 → 10 levels, so a uniform shimmer passes and real jumps
  still fail.

At those settings, `dst=data/spike/live2`:

| Sheet | Canvas | Anchor | s | Result | Max shift | Min agreement | Flicker max / mean | Bleed |
|---|---|---|---|---|---|---|---|---|
| s01 | 576x480 | – | 16.3 | promoted | 0.13 | 1.00 | 10.6 / 9.5 | 3.5 |
| s02 | 544x480 | s01 | 14.2 | promoted | 0.22 | 1.00 | 10.1 / 9.0 | 1.1 |
| s03 | 512x512 | s01 | 14.2 | rejected (flicker 14.0 vs source 1.8) | 0.49 | 1.00 | 14.0 / 10.2 | 0.6 |
| s03 #2 | 512x512 | s01 | 18.2 | rejected (shift 2.4-2.7, with a correction) | 2.67 | 1.00 | 22.9 / 13.1 | 7.8 |
| s04 | 512x512 | s01 | 14.3 | promoted | 0.07 | 1.00 | 9.3 / 8.8 | 0.7 |
| s05 | 544x544 | s01 | 16.3 | promoted | 0.06 | 1.00 | 11.0 / 10.6 | 0.8 |
| s06 | 576x544 | s01 | 18.2 | promoted | 0.06 | 1.00 | 9.2 / 8.2 | 0.7 |
| s07 | 544x512 | s01 | 16.2 | promoted | 0.15 | 1.00 | 10.3 / 9.8 | 1.1 |
| s08 | 576x480 | s01 | 16.2 | promoted | 0.11 | 1.00 | 12.4 / 9.9 | 10.4 |

About 16 s a sheet at 0.25-0.31 MP. 7 of 8 sheets promoted at the first
attempt. Every attempt that carried a correction note (three at 1.0, one at
0.9) moved further than the attempt before it: the spike should watch whether
corrections help geometry at all.
