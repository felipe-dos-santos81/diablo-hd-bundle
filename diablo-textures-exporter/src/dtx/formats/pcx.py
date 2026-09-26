import numpy as np

from dtx.binary import u16
from dtx.formats.frame import Frame

HEADER_BYTES = 128
PALETTE_TRAILER_BYTES = 769  # 0x0C marker + 768 palette bytes


def decode_pcx(data: bytes) -> tuple[Frame, np.ndarray]:
    """Decode an 8-bit single-plane PCX. Returns an opaque frame and its 256-colour palette."""
    if len(data) < HEADER_BYTES + PALETTE_TRAILER_BYTES or data[0] != 0x0A:
        raise ValueError("not a PCX file")
    if data[3] != 8 or data[65] != 1:
        raise ValueError(f"unsupported PCX: {data[3]} bits per pixel, {data[65]} planes")
    if data[-PALETTE_TRAILER_BYTES] != 0x0C:
        raise ValueError("PCX has no 256-colour palette")
    xmin, ymin, xmax, ymax = (u16(data, 4 + 2 * k) for k in range(4))
    width, height = xmax - xmin + 1, ymax - ymin + 1
    bytes_per_line = u16(data, 66)
    if width <= 0 or height <= 0 or bytes_per_line < width:
        raise ValueError(f"invalid PCX geometry {width}x{height}, {bytes_per_line} bytes per line")

    need = bytes_per_line * height
    end = len(data) - PALETTE_TRAILER_BYTES
    out = bytearray()
    i = HEADER_BYTES
    while len(out) < need and i < end:
        b = data[i]
        i += 1
        if b >= 0xC0:
            if i >= end:
                raise ValueError("PCX run is missing its value byte")
            out += bytes([data[i]]) * (b & 0x3F)
            i += 1
        else:
            out.append(b)
    if len(out) < need:
        raise ValueError(f"PCX body truncated: {len(out)} of {need} bytes")

    indices = np.frombuffer(bytes(out[:need]), np.uint8).reshape(height, bytes_per_line)[:, :width]
    palette = np.frombuffer(data[-768:], np.uint8).reshape(256, 3).copy()
    frame = Frame(indices.copy(), np.ones((height, width), bool))
    return frame, palette
