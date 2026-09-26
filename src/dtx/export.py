from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import numpy as np
from PIL import Image

from dtx.formats.frame import Frame


def rgba(frame: Frame, palette: np.ndarray) -> np.ndarray:
    out = np.zeros((frame.height, frame.width, 4), np.uint8)
    out[..., :3] = palette[frame.indices]
    out[..., 3] = frame.opaque.astype(np.uint8) * 255
    return out


def _index_image(frame: Frame) -> np.ndarray:
    grey = np.where(frame.opaque, frame.indices, 0).astype(np.uint8)
    return np.dstack([grey, frame.opaque.astype(np.uint8) * 255])


def write_frame_pair(frame: Frame, palette: np.ndarray, directory: Path, stem: str) -> dict:
    record: dict = {"w": frame.width, "h": frame.height}
    if frame.width == 0 or frame.height == 0:
        record["empty"] = True
        return record
    directory.mkdir(parents=True, exist_ok=True)
    png, idx = f"{stem}.png", f"{stem}.idx.png"
    Image.fromarray(rgba(frame, palette)).save(directory / png)
    Image.fromarray(_index_image(frame)).save(directory / idx)
    record.update(png=png, idx=idx)
    return record


def write_sheet(groups: Sequence[Sequence[Frame]], palette: np.ndarray, path: Path) -> bool:
    frames = [f for g in groups for f in g]
    cell_w = max((f.width for f in frames), default=0)
    cell_h = max((f.height for f in frames), default=0)
    columns = max((len(g) for g in groups), default=0)
    if cell_w == 0 or cell_h == 0 or columns == 0:
        return False
    canvas = np.zeros((len(groups) * cell_h, columns * cell_w, 4), np.uint8)
    for row, group in enumerate(groups):
        for col, frame in enumerate(group):
            if frame.width and frame.height:
                y, x = row * cell_h, col * cell_w
                canvas[y : y + frame.height, x : x + frame.width] = rgba(frame, palette)
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(canvas).save(path)
    return True


def write_swatch(palette: np.ndarray, path: Path) -> None:
    grid = palette.reshape(16, 16, 3)
    big = np.repeat(np.repeat(grid, 16, axis=0), 16, axis=1)
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(big.astype(np.uint8)).save(path)


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2) + "\n")
