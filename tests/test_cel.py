import numpy as np
import pytest

from builders import cel_frame
from dtx.formats.cel import decode_cel_frame, scan_cel_frame

ROWS = [[1, None, 3], [None, None, 6]]


def test_decode_basic():
    frame = decode_cel_frame(cel_frame(ROWS), 3)
    np.testing.assert_array_equal(frame.indices, [[1, 0, 3], [0, 0, 6]])
    np.testing.assert_array_equal(frame.opaque, [[True, False, True], [False, False, True]])


def test_decode_with_header():
    frame = decode_cel_frame(cel_frame(ROWS, header=True), 3)
    np.testing.assert_array_equal(frame.indices, [[1, 0, 3], [0, 0, 6]])


def test_fits_only_true_width():
    scan = scan_cel_frame(cel_frame([[1, 2, 3, 4], [5, 6, 7, 8]]))
    # one literal run of 4 per row -> width 2 would split a run across rows
    assert scan.fits(4)
    assert not scan.fits(2)
    assert not scan.fits(3)


def test_run_crossing_row_raises():
    with pytest.raises(ValueError):
        decode_cel_frame(cel_frame([[1, 2, 3, 4]]), 3)


def test_empty_frame():
    frame = decode_cel_frame(b"", 16)
    assert frame.width == 16 and frame.height == 0


def test_truncated_literal_raises():
    with pytest.raises(ValueError):
        scan_cel_frame(bytes([5, 1, 2]))


def test_header_detection_can_be_disabled():
    # literal run of 10 pixels starting with value 0 begins with bytes 0A 00
    raw = bytes([10]) + bytes(range(10))
    frame = decode_cel_frame(raw, 10, allow_header=False)
    np.testing.assert_array_equal(frame.indices[0], list(range(10)))
