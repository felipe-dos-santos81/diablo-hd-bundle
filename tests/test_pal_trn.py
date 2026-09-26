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
