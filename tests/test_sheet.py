import pytest

from builders import grouped, grouped_headers_first, sheet
from dtx.formats.sheet import split_sheet


def test_single_sheet():
    assert split_sheet(sheet([b"ab", b"", b"cde"])) == [[b"ab", b"", b"cde"]]


def test_zero_frame_sheet():
    assert split_sheet(sheet([])) == [[]]


def test_grouped_sheet_of_eight_directions():
    groups = [sheet([bytes([g]) * (g + 1), b"z"]) for g in range(8)]
    result = split_sheet(grouped(groups))
    assert len(result) == 8
    assert result[3] == [b"\x03" * 4, b"z"]


def test_grouped_sheet_with_headers_before_frame_data():
    """Real CL2 files store all group headers first; frame offsets are relative to each group header."""
    groups = [[bytes([g]) * (g + 1), b"z" * (g + 2)] for g in range(8)]
    assert split_sheet(grouped_headers_first(groups)) == groups


def test_rejects_garbage():
    with pytest.raises(ValueError):
        split_sheet(b"\xff\xff\xff\xff\x00\x00\x00\x00")


def test_rejects_too_small():
    with pytest.raises(ValueError):
        split_sheet(b"\x00\x00")
