import numpy as np
import pytest

from builders import cel_frame
from dtx.formats.levelcel import TileType, decode_level_cell


def triangle_bytes(left: bool, rows: int = 31) -> bytes:
    out = bytearray()
    for i in range(rows):
        w = 2 * (i + 1) if i < 16 else 2 * (31 - i)
        if left and i % 2 == 0:
            out += b"\0\0"
        out += bytes([i + 1]) * w
        if not left and i % 2 == 0:
            out += b"\0\0"
    return bytes(out)


def test_square_is_bottom_up():
    raw = bytes(range(32)) + bytes([200]) * (1024 - 32)
    cell = decode_level_cell(raw, TileType.SQUARE)
    np.testing.assert_array_equal(cell.indices[31], list(range(32)))
    assert cell.opaque.all()


def test_left_triangle_geometry():
    raw = triangle_bytes(left=True)
    assert len(raw) == 544
    cell = decode_level_cell(raw, TileType.LEFT_TRIANGLE)
    np.testing.assert_array_equal(np.nonzero(cell.opaque[31])[0], [30, 31])  # bottom row, 2 px, right-aligned
    assert cell.opaque[16].all()  # i = 15, full width
    assert not cell.opaque[0].any()  # top row empty
    assert set(np.unique(cell.indices[31][cell.opaque[31]])) == {1}  # padding never shown


def test_right_triangle_geometry():
    cell = decode_level_cell(triangle_bytes(left=False), TileType.RIGHT_TRIANGLE)
    np.testing.assert_array_equal(np.nonzero(cell.opaque[31])[0], [0, 1])
    np.testing.assert_array_equal(np.nonzero(cell.opaque[1])[0], [0, 1])  # i = 30


def test_left_trapezoid_geometry():
    raw = triangle_bytes(left=True, rows=16) + bytes([100]) * 512
    assert len(raw) == 800
    cell = decode_level_cell(raw, TileType.LEFT_TRAPEZOID)
    assert cell.opaque[:16].all()
    assert (cell.indices[:16] == 100).all()
    np.testing.assert_array_equal(np.nonzero(cell.opaque[31])[0], [30, 31])


def test_transparent_square_never_reads_header():
    # Review Focus 3: data starting 0A 00 is a 10-pixel literal run, not a frame header
    rows = [[0] * 10 + [None] * 22 for _ in range(32)]
    raw = cel_frame(rows)
    assert raw[:2] == b"\x0a\x00"
    cell = decode_level_cell(raw, TileType.TRANSPARENT_SQUARE)
    assert cell.opaque[:, :10].all() and not cell.opaque[:, 10:].any()


def test_wrong_size_rejected():
    with pytest.raises(ValueError):
        decode_level_cell(bytes(543), TileType.LEFT_TRIANGLE)
    with pytest.raises(ValueError):
        decode_level_cell(bytes(1000), TileType.SQUARE)
