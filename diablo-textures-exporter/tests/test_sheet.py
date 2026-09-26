import struct

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


def test_grouped_sheet_with_stale_group_table_falls_back_to_chained_headers():
    """DIABDAT.MPQ monsters\\unrav\\unravw.cel has a wrong group table; its groups are contiguous."""
    groups = [[bytes([g]) * (g + 1), b"z"] for g in range(8)]
    data = bytearray(grouped([sheet(frames) for frames in groups]))
    for g in range(1, 8):  # shift every group offset but the first, as in the real file
        struct.pack_into("<I", data, 4 * g, struct.unpack_from("<I", data, 4 * g)[0] + g)
    assert split_sheet(bytes(data)) == groups


def test_grouped_sheet_of_empty_groups_with_stale_group_table():
    """DIABDAT.MPQ monsters\\darkmage\\dmagew.cl2: eight empty groups, group table off by one byte each."""
    empty = struct.pack("<2I", 0, 8)
    data = struct.pack("<8I", *(32 + 7 * g for g in range(8))) + empty * 8
    assert split_sheet(data) == [[]] * 8


def test_rejects_group_table_that_matches_no_layout():
    data = bytearray(grouped([sheet([b"ab"]), sheet([b"cd"])]))
    data += b"\x00"  # chained headers no longer end exactly at the end of the file
    struct.pack_into("<I", data, 4, 999)
    with pytest.raises(ValueError):
        split_sheet(bytes(data))


def test_rejects_garbage():
    with pytest.raises(ValueError):
        split_sheet(b"\xff\xff\xff\xff\x00\x00\x00\x00")


def test_rejects_too_small():
    with pytest.raises(ValueError):
        split_sheet(b"\x00\x00")


def test_read_sheet_reports_chained_recovery():
    from dtx.formats.sheet import read_sheet

    groups = [[bytes([g]) * (g + 1), b"z"] for g in range(8)]
    good = grouped([sheet(frames) for frames in groups])
    data = bytearray(good)
    for g in range(1, 8):
        struct.pack_into("<I", data, 4 * g, struct.unpack_from("<I", data, 4 * g)[0] + g)
    stale = read_sheet(bytes(data))
    assert stale.groups == groups and stale.recovery == "chained"
    normal = read_sheet(good)
    assert normal.groups == groups and normal.recovery is None
    assert read_sheet(sheet([b"ab"])).recovery is None
