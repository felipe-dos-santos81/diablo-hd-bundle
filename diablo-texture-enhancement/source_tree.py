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
