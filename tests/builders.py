"""Synthetic encoders for every Diablo format. Test-only: no game data."""
import struct

import numpy as np


def pcx(indices: np.ndarray, palette: np.ndarray, bytes_per_line: int | None = None) -> bytes:
    h, w = indices.shape
    bpl = bytes_per_line or (w + (w & 1))
    header = bytearray(128)
    header[0], header[1], header[2], header[3] = 0x0A, 5, 1, 8
    struct.pack_into("<4H", header, 4, 0, 0, w - 1, h - 1)
    header[65] = 1
    struct.pack_into("<H", header, 66, bpl)
    body = bytearray()
    for row in indices:
        line = bytes(int(v) for v in row) + bytes(bpl - w)
        i = 0
        while i < len(line):
            v = line[i]
            n = 1
            while i + n < len(line) and line[i + n] == v and n < 63:
                n += 1
            if n > 1 or v >= 0xC0:
                body += bytes([0xC0 | n, v])
            else:
                body.append(v)
            i += n
    return bytes(header) + bytes(body) + b"\x0c" + palette.astype(np.uint8).tobytes()


def sheet(frames: list[bytes]) -> bytes:
    n = len(frames)
    offsets = [4 * (n + 2)]
    for f in frames:
        offsets.append(offsets[-1] + len(f))
    return struct.pack(f"<{n + 2}I", n, *offsets) + b"".join(frames)


def grouped(sheets: list[bytes]) -> bytes:
    pos = 4 * len(sheets)
    offsets = []
    for s in sheets:
        offsets.append(pos)
        pos += len(s)
    return struct.pack(f"<{len(sheets)}I", *offsets) + b"".join(sheets)
