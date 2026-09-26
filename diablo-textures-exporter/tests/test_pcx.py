import numpy as np
import pytest

from builders import pcx
from dtx.formats.pcx import decode_pcx

PAL = np.arange(768, dtype=np.uint32).reshape(256, 3).astype(np.uint8)


def test_roundtrip_odd_width_with_padding_and_high_values():
    indices = np.array([[1, 2, 0xC5], [7, 7, 7]], np.uint8)
    frame, palette = decode_pcx(pcx(indices, PAL))
    np.testing.assert_array_equal(frame.indices, indices)
    assert frame.opaque.all()
    np.testing.assert_array_equal(palette, PAL)


def test_rejects_bad_magic():
    data = bytearray(pcx(np.zeros((1, 1), np.uint8), PAL))
    data[0] = 0
    with pytest.raises(ValueError):
        decode_pcx(bytes(data))


def test_rejects_truncated_body():
    data = pcx(np.arange(64, dtype=np.uint8).reshape(8, 8), PAL)
    body_cut = data[:140] + data[-769:]
    with pytest.raises(ValueError):
        decode_pcx(body_cut)


def test_rejects_missing_palette_marker():
    data = bytearray(pcx(np.zeros((1, 1), np.uint8), PAL))
    data[-769] = 0
    with pytest.raises(ValueError):
        decode_pcx(bytes(data))
