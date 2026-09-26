import json

import pytest
from PIL import Image

from builders import dun_bytes, min_bytes, sheet, til_bytes
from fakes import FakeArchive
from dtx.catalog import Entry
from dtx.handlers import Context, export_layout, export_tileset
from dtx.mpq import ArchiveStack

KEY = "levels\\l1data\\l1"
PAL = bytes(range(256)) * 3
EMPTY = (0, 0)
# 10 cells per column; bottom row (slots 8, 9) uses square cells 1 and 2
COLUMN = [EMPTY] * 8 + [(1, 0), (2, 0)]
FILES = {
    "levels\\l1data\\l1_1.pal": PAL,
    f"{KEY}.cel": sheet([bytes([10]) * 1024, bytes([20]) * 1024]),
    f"{KEY}.min": min_bytes([COLUMN, COLUMN]),
    f"{KEY}.til": til_bytes([(0, 1, 0, 1)]),
    f"{KEY}.sol": bytes([1, 0]),
}


def ctx_for(tmp_path, extra=None):
    return Context(ArchiveStack([FakeArchive("DIABDAT.MPQ", {**FILES, **(extra or {})})]), tmp_path, True)


def test_tileset_export(tmp_path):
    ctx = ctx_for(tmp_path)
    entry = Entry(f"{KEY}.cel", "tileset", "levels\\l1data\\l1_1.pal", tileset=KEY)
    info = export_tileset(ctx, entry, "DIABDAT.MPQ", FILES[f"{KEY}.cel"], tmp_path / "t")
    assert info == {"columns": 2, "tiles": 1}
    meta = json.loads((tmp_path / "t/tileset.json").read_text())
    assert meta["cells_per_column"] == 10 and meta["column_size_px"] == [64, 160]
    assert meta["columns"][0]["cells"][8] == {"slot": 8, "frame": 1, "draw_type": 0}
    assert meta["columns"][0]["sol"]["solid"] is True
    assert meta["cell_users"] == {"1": [0, 1], "2": [0, 1]}
    assert meta["tiles"][0]["columns"] == [0, 1, 0, 1]
    assert Image.open(tmp_path / "t/columns/m0000.png").size == (64, 160)
    assert Image.open(tmp_path / "t/tiles/t0000.png").size == (128, 192)
    assert (tmp_path / "t/cells/c0001.idx.png").exists() and (tmp_path / "t/sheet.png").exists()


def test_layout_export(tmp_path):
    ctx = ctx_for(tmp_path)
    dun = dun_bytes([[1, 0]])
    entry = Entry("levels\\l1data\\x.dun", "layout", "levels\\l1data\\l1_1.pal", tileset=KEY)
    info = export_layout(ctx, entry, "DIABDAT.MPQ", dun, tmp_path / "l")
    meta = json.loads((tmp_path / "l/layout.json").read_text())
    assert info == {"placements": 4}
    assert meta["size_px"] == [128, 192] and meta["column_height_px"] == 160
    assert meta["tileset"] == "levels/l1data/l1"
    assert meta["placements"][0] == {"column": 0, "x": 32, "y": 0}
    assert Image.open(tmp_path / "l/layout.png").size == (128, 192)


def test_layout_with_out_of_range_tile_fails(tmp_path):
    # Review Focus 5
    ctx = ctx_for(tmp_path)
    entry = Entry("levels\\l1data\\x.dun", "layout", "levels\\l1data\\l1_1.pal", tileset=KEY)
    with pytest.raises(ValueError, match="beyond"):
        export_layout(ctx, entry, "DIABDAT.MPQ", dun_bytes([[5]]), tmp_path / "l")
    assert not (tmp_path / "l/layout.json").exists()


def test_min_referencing_missing_cel_frame_fails(tmp_path):
    bad_min = min_bytes([[EMPTY] * 9 + [(7, 0)]])
    ctx = ctx_for(tmp_path, {f"{KEY}.min": bad_min})
    entry = Entry(f"{KEY}.cel", "tileset", "levels\\l1data\\l1_1.pal", tileset=KEY)
    with pytest.raises(ValueError, match="references cell 7"):
        export_tileset(ctx, entry, "DIABDAT.MPQ", FILES[f"{KEY}.cel"], tmp_path / "t")
