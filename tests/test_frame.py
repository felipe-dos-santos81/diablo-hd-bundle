import numpy as np
import pytest

from dtx.formats.frame import Frame


def test_from_bottom_up_flips_rows():
    # bottom row first: bottom = [1, 2], top = [3, 4]
    frame = Frame.from_bottom_up(bytes([1, 2, 3, 4]), bytes([1, 1, 0, 1]), 2)
    assert frame.width == 2 and frame.height == 2
    np.testing.assert_array_equal(frame.indices, [[3, 4], [1, 2]])
    np.testing.assert_array_equal(frame.opaque, [[False, True], [True, True]])


def test_from_bottom_up_rejects_partial_rows():
    with pytest.raises(ValueError):
        Frame.from_bottom_up(bytes(3), bytes(3), 2)


def test_from_bottom_up_rejects_zero_width():
    with pytest.raises(ValueError):
        Frame.from_bottom_up(b"", b"", 0)


def test_same_pixels_ignores_indices_under_transparency():
    a = Frame(np.array([[5, 9]], np.uint8), np.array([[True, False]]))
    b = Frame(np.array([[5, 0]], np.uint8), np.array([[True, False]]))
    c = Frame(np.array([[6, 0]], np.uint8), np.array([[True, False]]))
    assert a.same_pixels(b)
    assert not a.same_pixels(c)


def test_shape_mismatch_rejected():
    with pytest.raises(ValueError):
        Frame(np.zeros((2, 2), np.uint8), np.zeros((2, 3), bool))


def test_empty_frame():
    frame = Frame.empty(32, 0)
    assert frame.width == 32 and frame.height == 0
