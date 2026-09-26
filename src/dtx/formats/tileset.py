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
    values = np.frombuffer(data, "<u2").tolist()
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
