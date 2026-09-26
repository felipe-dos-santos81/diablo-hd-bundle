import json

import numpy as np
import pytest

from builders import cel_frame, cl2_frame, grouped, pcx, sheet
from fakes import FakeArchive
from dtx.catalog import Entry
from dtx.handlers import (
    Context,
    VerificationError,
    export_image,
    export_palette,
    export_sprite,
    export_trn,
    sha1,
)
from dtx.mpq import ArchiveStack

PAL_BYTES = bytes(range(256)) * 3
PAL = np.frombuffer(PAL_BYTES, np.uint8).reshape(256, 3)


def ctx_for(tmp_path, files, verify=True):
    files = {"levels\\towndata\\town.pal": PAL_BYTES, **files}
    return Context(ArchiveStack([FakeArchive("DIABDAT.MPQ", files)]), tmp_path, verify)


def test_palette(tmp_path):
    ctx = ctx_for(tmp_path, {})
    dest = tmp_path / "palettes/levels/l3data/l3_1.pal"
    export_palette(ctx, Entry("levels\\l3data\\l3_1.pal", "palette"), "DIABDAT.MPQ", PAL_BYTES, dest)
    record = json.loads((tmp_path / "palettes/levels/l3data/l3_1.pal.json").read_text())
    assert record["source"]["sha1"] == sha1(PAL_BYTES)
    assert record["colors"][1] == [3, 4, 5]
    assert record["cycling"][0]["last"] == 31
    assert (tmp_path / "palettes/levels/l3data/l3_1.pal.png").exists()


def test_trn(tmp_path):
    ctx = ctx_for(tmp_path, {})
    export_trn(ctx, Entry("monsters\\x.trn", "trn"), "DIABDAT.MPQ", bytes(range(256)), tmp_path / "t")
    assert json.loads((tmp_path / "t/trn.json").read_text())["map"][7] == 7


def test_image(tmp_path):
    ctx = ctx_for(tmp_path, {})
    data = pcx(np.array([[1, 2], [3, 4]], np.uint8), PAL)
    info = export_image(ctx, Entry("ui_art\\x.pcx", "ui_image"), "DIABDAT.MPQ", data, tmp_path / "i")
    meta = json.loads((tmp_path / "i/meta.json").read_text())
    assert info == {"frames": 1}
    assert meta["palette"] == "embedded" and meta["width_source"] == "header"
    assert meta["palette_alternatives"] == [] and meta["variants"] == []
    assert meta["frames"] == [{"group": 0, "i": 0, "w": 2, "h": 2, "png": "image.png", "idx": "image.idx.png"}]


def test_grouped_cl2_sprite(tmp_path):
    ctx = ctx_for(tmp_path, {})
    frame = cl2_frame([[1, 2, 3, 4]] * 40)
    data = grouped([sheet([frame, frame]) for _ in range(8)])
    entry = Entry("monsters\\z\\zn.cl2", "monster_anim", "levels\\towndata\\town.pal", width_hint=4,
                  variants=("monsters\\z\\blue.trn",))
    info = export_sprite(ctx, entry, "DIABDAT.MPQ", data, tmp_path / "s")
    meta = json.loads((tmp_path / "s/meta.json").read_text())
    assert info["frames"] == 16 and meta["width_source"] == "table"
    assert meta["groups"] == 8 and meta["group_label"] == "direction"
    assert meta["variants"] == [{"trn": "monsters/z/blue.trn"}]
    assert meta["frames"][3] == {"group": 1, "i": 1, "w": 4, "h": 40, "png": "d1/f001.png", "idx": "d1/f001.idx.png"}
    assert (tmp_path / "s/d7/f001.idx.png").exists() and (tmp_path / "s/sheet.png").exists()


def test_sprite_inferred_width_records_candidates(tmp_path):
    ctx = ctx_for(tmp_path, {})
    data = sheet([cel_frame([[None] * 30 + [1, 2]] * 3)])
    export_sprite(ctx, Entry("data\\x.cel", "ui_sprite", "levels\\towndata\\town.pal"), "DIABDAT.MPQ",
                  data, tmp_path / "s")
    meta = json.loads((tmp_path / "s/meta.json").read_text())
    assert meta["width_source"] == "inferred" and meta["frames"][0]["w"] == 32
    assert 32 in meta["width_candidates"]


def test_sprite_with_empty_frame(tmp_path):
    # Review Focus 2
    ctx = ctx_for(tmp_path, {})
    data = sheet([b"", cel_frame([[1, 2]])])
    export_sprite(ctx, Entry("data\\x.cel", "ui_sprite", "levels\\towndata\\town.pal", width_hint=2),
                  "DIABDAT.MPQ", data, tmp_path / "s")
    meta = json.loads((tmp_path / "s/meta.json").read_text())
    assert meta["frames"][0]["empty"] is True
    assert meta["frames"][1]["png"] == "d0/f001.png"


def test_missing_palette_raises(tmp_path):
    ctx = ctx_for(tmp_path, {})
    with pytest.raises(ValueError):
        export_sprite(ctx, Entry("data\\x.cel", "ui_sprite", "nope.pal", width_hint=2), "DIABDAT.MPQ",
                      sheet([cel_frame([[1, 2]])]), tmp_path / "s")


def test_verification_mismatch_raises(tmp_path, monkeypatch):
    monkeypatch.setattr("dtx.handlers.verify_written", lambda frame, idx_path: False)
    ctx = ctx_for(tmp_path, {})
    dest = tmp_path / "s"
    with pytest.raises(VerificationError):
        export_sprite(ctx, Entry("data\\x.cel", "ui_sprite", "levels\\towndata\\town.pal", width_hint=2),
                      "DIABDAT.MPQ", sheet([cel_frame([[1, 2]])]), dest)
    assert not (dest / "meta.json").exists()
