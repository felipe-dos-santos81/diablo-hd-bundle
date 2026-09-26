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
        if not 0 <= p.column < len(columns):
            raise ValueError(f"placement references column {p.column} but only {len(columns)} columns exist")
        col = columns[p.column]
        ys, xs = slice(p.y, p.y + col.height), slice(p.x, p.x + col.width)
        idx[ys, xs][col.opaque] = col.indices[col.opaque]
        op[ys, xs] |= col.opaque
    return Frame(idx, op)


def crop_box(p: Placement, column_height: int, scale: int) -> tuple[int, int, int, int]:
    """Crop rectangle of a placed column in a layout regenerated at integer scale."""
    x0, y0 = p.x * scale, p.y * scale
    return x0, y0, x0 + COLUMN_WIDTH * scale, y0 + column_height * scale
