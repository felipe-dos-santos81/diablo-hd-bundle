import numpy as np
import pytest

from dtx.formats.frame import Frame
from dtx.formats.render import Placement, compose, crop_box, place_pieces, tile_pieces


def test_tile_pieces_layout():
    pieces = tile_pieces(np.array([[0, -1]]), [(10, 11, 12, 13)])
    np.testing.assert_array_equal(pieces, [[10, 11, -1, -1], [12, 13, -1, -1]])


def test_tile_pieces_out_of_range():
    with pytest.raises(ValueError):
        tile_pieces(np.array([[3]]), [(0, 0, 0, 0)])


def test_single_tile_placement():
    pieces = tile_pieces(np.array([[0]]), [(0, 1, 2, 3)])
    placements, size = place_pieces(pieces, 64)
    assert [p.column for p in placements] == [0, 2, 1, 3]  # top, left, right, bottom
    assert placements == [Placement(0, 32, 0), Placement(2, 0, 16), Placement(1, 64, 16), Placement(3, 32, 32)]
    assert size == (128, 96)  # 2 columns wide, column height + 32


def test_empty_grid():
    assert place_pieces(np.full((2, 2), -1), 64) == ([], (0, 0))


def test_compose_later_placements_overwrite():
    a = Frame(np.full((2, 2), 1, np.uint8), np.ones((2, 2), bool))
    b = Frame(np.array([[2, 2], [2, 2]], np.uint8), np.array([[True, False], [False, False]]))
    out = compose([Placement(0, 0, 0), Placement(1, 1, 0)], (3, 2), [a, b])
    np.testing.assert_array_equal(out.indices, [[1, 2, 0], [1, 1, 0]])
    np.testing.assert_array_equal(out.opaque, [[True, True, False], [True, True, False]])


def test_crop_box_scales():
    p = Placement(5, 32, 16)
    assert crop_box(p, 160, 1) == (32, 16, 96, 176)
    assert crop_box(p, 160, 4) == (128, 64, 384, 704)


def test_compose_rejects_unknown_column():
    a = Frame(np.array([[2, 2], [2, 2]], np.uint8), np.array([[True, False], [False, False]]))
    with pytest.raises(ValueError, match="column 5"):
        compose([Placement(5, 0, 0)], (2, 2), [a])
