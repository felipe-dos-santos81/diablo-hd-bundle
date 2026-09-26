import json

import numpy as np
from PIL import Image

from dtx.export import rgba, write_frame_pair, write_json, write_sheet, write_swatch
from dtx.formats.frame import Frame
from dtx.verify import read_index_png, verify_written

PAL = np.stack([np.arange(256)] * 3, axis=1).astype(np.uint8)
FRAME = Frame(np.array([[1, 2], [3, 4]], np.uint8), np.array([[True, False], [True, True]]))


def test_rgba_applies_palette_and_alpha():
    out = rgba(FRAME, PAL)
    assert tuple(out[0, 0]) == (1, 1, 1, 255)
    assert out[0, 1, 3] == 0


def test_pair_roundtrip(tmp_path):
    rec = write_frame_pair(FRAME, PAL, tmp_path / "d0", "f000")
    assert rec == {"w": 2, "h": 2, "png": "f000.png", "idx": "f000.idx.png"}
    assert Image.open(tmp_path / "d0" / "f000.png").mode == "RGBA"
    assert read_index_png(tmp_path / "d0" / "f000.idx.png").same_pixels(FRAME)
    assert verify_written(FRAME, tmp_path / "d0" / "f000.idx.png")


def test_verify_detects_one_pixel_change(tmp_path):
    write_frame_pair(FRAME, PAL, tmp_path, "f")
    path = tmp_path / "f.idx.png"
    data = np.asarray(Image.open(path)).copy()
    data[1, 1, 0] = 99
    Image.fromarray(data).save(path)
    assert not verify_written(FRAME, path)


def test_empty_frame_writes_no_png(tmp_path):
    # Review Focus 2
    rec = write_frame_pair(Frame.empty(32, 0), PAL, tmp_path, "f000")
    assert rec == {"w": 32, "h": 0, "empty": True}
    assert not list(tmp_path.iterdir())


def test_sheet_rows_per_group(tmp_path):
    ok = write_sheet([[FRAME, FRAME, FRAME], [FRAME]], PAL, tmp_path / "sheet.png")
    assert ok
    assert Image.open(tmp_path / "sheet.png").size == (6, 4)


def test_sheet_all_empty(tmp_path):
    assert not write_sheet([[Frame.empty()]], PAL, tmp_path / "sheet.png")
    assert not (tmp_path / "sheet.png").exists()


def test_swatch(tmp_path):
    write_swatch(PAL, tmp_path / "p.png")
    img = Image.open(tmp_path / "p.png")
    assert img.size == (256, 256)
    assert img.getpixel((16 * 3 + 1, 16 * 2 + 1))[:3] == (35, 35, 35)


def test_write_json(tmp_path):
    write_json(tmp_path / "a" / "b.json", {"x": 1})
    assert json.loads((tmp_path / "a" / "b.json").read_text()) == {"x": 1}
