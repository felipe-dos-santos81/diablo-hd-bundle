import pytest

from dtx.binary import u16, u32
from dtx.paths import canonical, directory, extension, rel_path, stem


def test_canonical_and_rel():
    assert canonical("Levels/L1Data/L1.CEL") == "levels\\l1data\\l1.cel"
    assert rel_path("Levels\\L1Data\\L1.CEL") == "levels/l1data/l1.cel"


def test_parts():
    assert extension("levels\\l1data\\l1.cel") == "cel"
    assert extension("levels\\l1data\\noext") == ""
    assert directory("levels\\l1data\\l1.cel") == "levels\\l1data"
    assert directory("toplevel.pcx") == ""
    assert stem("levels\\l1data\\l1.cel") == "levels\\l1data\\l1"


def test_binary_reads():
    data = bytes([1, 0, 2, 0, 0, 0])
    assert u16(data, 0) == 1
    assert u32(data, 2) == 2
    with pytest.raises(ValueError):
        u32(data, 4)
