import numpy as np
import pytest

from builders import cl2_frame
from dtx.formats.cl2 import decode_cl2_frame, scan_cl2_frame


def test_decode_transparent_fill_and_literal():
    rows = [[None, None, 9, 9, 9], [1, 2, None, 4, 5]]
    frame = decode_cl2_frame(cl2_frame(rows), 5)
    np.testing.assert_array_equal(frame.indices, [[0, 0, 9, 9, 9], [1, 2, 0, 4, 5]])
    np.testing.assert_array_equal(frame.opaque[0], [False, False, True, True, True])


def test_runs_may_cross_rows():
    # one literal run of 6 covering two rows of width 3
    raw = bytes([10, 0, 0, 0, 0, 0, 0, 0, 0, 0, 256 - 6, 1, 2, 3, 4, 5, 6])
    frame = decode_cl2_frame(raw, 3)
    np.testing.assert_array_equal(frame.indices, [[4, 5, 6], [1, 2, 3]])


def test_pixel_count_not_multiple_of_width_raises():
    with pytest.raises(ValueError):
        decode_cl2_frame(cl2_frame([[1, 2, 3]]), 2)


def test_skip_table_pins_width():
    rows = [[(x + y) % 7 + 1 for x in range(4)] for y in range(40)]
    scan = scan_cl2_frame(cl2_frame(rows))
    assert scan.fits(4)
    assert not scan.fits(2)  # 80 rows: row-32 offset would be at 64 pixels, not 128
    assert not scan.fits(8)  # 20 rows: offset at 128 pixels expected 256
    assert scan.fits(2, strict=False)  # divisibility alone is ambiguous


def test_empty_frame():
    assert decode_cl2_frame(b"", 8).height == 0


def test_fill_missing_colour_raises():
    with pytest.raises(ValueError):
        scan_cl2_frame(bytes([10, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0xBE]))


def test_header_size_past_end_raises():
    with pytest.raises(ValueError):
        scan_cl2_frame(bytes([40, 0, 1]))
