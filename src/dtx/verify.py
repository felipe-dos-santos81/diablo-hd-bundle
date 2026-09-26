from pathlib import Path

import numpy as np
from PIL import Image

from dtx.formats.frame import Frame


def read_index_png(path: Path) -> Frame:
    with Image.open(path) as img:
        if img.mode != "LA":
            raise ValueError(f"{path} is {img.mode}, expected an LA index image")
        data = np.asarray(img)
    return Frame(data[..., 0].copy(), data[..., 1] == 255)


def verify_written(frame: Frame, idx_path: Path) -> bool:
    return frame.same_pixels(read_index_png(idx_path))
