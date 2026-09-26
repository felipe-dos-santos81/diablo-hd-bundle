import numpy as np
import pytest

from builders import dun_bytes, min_bytes, til_bytes
from dtx.formats.frame import Frame
from dtx.formats.tileset import (
    cell_types, cell_users, compose_column, parse_dun, parse_min, parse_sol, parse_til,
)


def solid(value):
    return Frame(np.full((32, 32), value, np.uint8), np.ones((32, 32), bool))


def test_parse_min_splits_frame_and_type():
    data = min_bytes([[(1, 0), (2, 4), (0, 0), (3, 1)], [(0, 0)] * 4])
    columns = parse_min(data, 4)
    assert len(columns) == 2
    assert columns[0][1].frame == 2 and columns[0][1].tile_type == 4
    assert columns[0][2].empty
    assert type(columns[0][1].frame) is int and type(columns[0][1].tile_type) is int


def test_parse_min_rejects_partial_column():
    with pytest.raises(ValueError):
        parse_min(min_bytes([[(1, 0)] * 3]), 4)


def test_parse_til_and_sol():
    assert parse_til(til_bytes([(0, 1, 2, 3)])) == [(0, 1, 2, 3)]
    sol = parse_sol(bytes([1 | 8, 128]))
    assert sol[0]["solid"] and sol[0]["transparent"] and not sol[0]["trap"]
    assert sol[1]["trap"]


def test_parse_dun():
    dun = parse_dun(dun_bytes([[1, 2, 0], [4, 5, 6]]) + b"extra layers ignored")
    assert (dun.width, dun.height) == (3, 2)
    np.testing.assert_array_equal(dun.tiles, [[1, 2, 0], [4, 5, 6]])


def test_parse_dun_truncated():
    with pytest.raises(ValueError):
        parse_dun(dun_bytes([[1, 2]])[:-2])


def test_compose_column_places_top_row_first():
    columns = parse_min(min_bytes([[(1, 0), (0, 0), (0, 0), (2, 0)]]), 4)
    frame = compose_column(columns[0], {1: solid(10), 2: solid(20)})
    assert (frame.width, frame.height) == (64, 64)
    assert (frame.indices[:32, :32] == 10).all()  # slot 0: top-left
    assert (frame.indices[32:, 32:] == 20).all()  # slot 3: bottom-right
    assert not frame.opaque[:32, 32:].any()


def test_compose_column_missing_cell_raises():
    columns = parse_min(min_bytes([[(9, 0), (0, 0)]]), 2)
    with pytest.raises(ValueError):
        compose_column(columns[0], {})


def test_cell_types_and_users():
    columns = parse_min(min_bytes([[(1, 0), (2, 1)], [(1, 0), (0, 0)]]), 2)
    assert cell_types(columns) == {1: 0, 2: 1}
    assert cell_users(columns) == {1: [0, 1], 2: [0]}


def test_cell_types_conflict_raises():
    columns = parse_min(min_bytes([[(1, 0), (1, 2)]]), 2)
    with pytest.raises(ValueError):
        cell_types(columns)
