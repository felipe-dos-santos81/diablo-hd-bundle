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
