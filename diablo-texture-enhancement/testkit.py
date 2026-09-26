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
