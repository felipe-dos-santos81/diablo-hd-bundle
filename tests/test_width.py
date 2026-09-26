import pytest

from builders import cel_frame, cl2_frame
from dtx.formats.width import candidate_order, resolve_widths, scan_frame


def rows(width, height, value=5):
    return [[value + (x % 3) for x in range(width)] for _ in range(height)]


def test_candidate_order_prefers_common_widths_and_covers_range():
    order = candidate_order()
    assert order[:4] == [32, 64, 96, 128]
    assert sorted(order) == list(range(1, 641))


def test_table_width_accepted():
    scans = [scan_frame("cel", cel_frame(rows(64, 3)))]
    result = resolve_widths(scans, 64)
    assert result.widths == (64,) and result.source == "table"


def test_wrong_table_width_falls_back_to_inference():
    scans = [scan_frame("cl2", cl2_frame(rows(96, 40)))]
    result = resolve_widths(scans, 128)
    assert result.source == "inferred"
    assert result.widths == (96,)
    assert 96 in result.candidates


def test_per_frame_table_widths():
    scans = [scan_frame("cel", cel_frame(rows(28, 2))), scan_frame("cel", cel_frame(rows(56, 2)))]
    result = resolve_widths(scans, [28, 56])
    assert result.widths == (28, 56) and result.source == "table"


def test_per_frame_inference_when_no_common_width():
    # Review Focus 1: frames of different widths, no table
    a = [[None] * 30 + [1, 2]]  # width 32: transparent run of 30 then 2 pixels
    b = [[1] * 5 + [None] * 50 + [2]]  # width 56
    scans = [scan_frame("cel", cel_frame(a)), scan_frame("cel", cel_frame(b))]
    result = resolve_widths(scans, None)
    assert result.source == "inferred_per_frame"
    assert result.widths == (32, 56)


def test_unknown_format_rejected():
    with pytest.raises(ValueError):
        scan_frame("bmp", b"")
