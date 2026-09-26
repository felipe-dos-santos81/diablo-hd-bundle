"""Shared test support: a miniature diablo-textures-exporter output, a
characters.yaml writer, the ComfyUI and vLLM patch stacks, a fake sheet
renderer, a CLI-capture helper, and where the real corpus is.

The real source tree is diablo-textures-exporter's `out/`: manifest.json with
an hd_contract, assets/<record dir>/meta.json with frames (png RGBA, idx LA),
palettes/<name>.json and assets/<trn>/trn.json.
"""
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
