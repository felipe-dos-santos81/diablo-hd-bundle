import numpy as np
import pytest

from dtx.formats.pal import cycling_for, decode_pal
from dtx.formats.trn import decode_trn


def test_decode_pal():
    data = bytes(range(256)) * 3
    pal = decode_pal(data)
    assert pal.shape == (256, 3)
    assert pal.dtype == np.uint8
    assert tuple(pal[1]) == (3, 4, 5)


def test_decode_jasc_text_palette():
    """DIABDAT.MPQ ships items\\swrdflip.pal as a JASC-PAL text file, not 768 raw bytes."""
    colours = [(i, 255 - i, i // 2) for i in range(256)]
    text = "JASC-PAL\r\n0100\r\n256\r\n" + "".join(f"{r} {g} {b}\r\n" for r, g, b in colours)
    pal = decode_pal(text.encode("ascii"))
    assert pal.shape == (256, 3)
    assert pal.dtype == np.uint8
    assert tuple(pal[0]) == (0, 255, 0)
    assert tuple(pal[200]) == (200, 55, 100)


def test_decode_jasc_rejects_wrong_colour_count():
    text = "JASC-PAL\r\n0100\r\n2\r\n0 0 0\r\n1 1 1\r\n"
    with pytest.raises(ValueError):
        decode_pal(text.encode("ascii"))


def test_decode_pal_rejects_wrong_size():
    with pytest.raises(ValueError):
        decode_pal(bytes(767))


def test_cycling_by_directory():
    assert cycling_for("levels\\l3data\\l3_1.pal")[0]["first"] == 1
    assert cycling_for("levels\\l3data\\l3_1.pal")[0]["last"] == 31
    assert len(cycling_for("nlevels\\l5data\\l5base.pal")) == 2
    assert cycling_for("levels\\towndata\\town.pal") == []


def test_decode_trn():
    trn = decode_trn(bytes(reversed(range(256))))
    assert trn[0] == 255 and trn[255] == 0


def test_decode_trn_rejects_short():
    with pytest.raises(ValueError):
        decode_trn(bytes(10))
