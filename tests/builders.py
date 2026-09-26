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


def cel_frame(rows: list[list[int | None]], header: bool = False) -> bytes:
    """Encode rows (top row first; None = transparent) as a CEL frame."""
    out = bytearray()
    for row in reversed(rows):
        i = 0
        while i < len(row):
            n = 1
            if row[i] is None:
                while i + n < len(row) and row[i + n] is None and n < 128:
                    n += 1
                out.append(256 - n)
            else:
                while i + n < len(row) and row[i + n] is not None and n < 127:
                    n += 1
                out.append(n)
                out += bytes(row[i : i + n])
            i += n
    if header:
        return struct.pack("<5H", 10, 0, 0, 0, 0) + bytes(out)
    return bytes(out)


def cl2_frame(rows: list[list[int | None]]) -> bytes:
    """Encode rows (top row first; None = transparent) as a CL2 frame with a skip table.

    Runs may cross rows but never cross a 32-row boundary, so skip offsets are exact."""
    width = len(rows[0]) if rows else 0
    flat = [p for row in reversed(rows) for p in row]
    boundaries = sorted(32 * k * width for k in (1, 2, 3, 4) if width and 32 * k * width < len(flat))
    body = bytearray()
    boundary_offsets: dict[int, int] = {}

    def cap(i: int, limit: int) -> int:
        nxt = next((b for b in boundaries if b > i), len(flat))
        return min(limit, nxt - i)

    i = 0
    while i < len(flat):
        if i in boundaries:
            boundary_offsets[i] = len(body)
        n = 1
        if flat[i] is None:
            while n < cap(i, 127) and flat[i + n] is None:
                n += 1
            body.append(n)
        else:
            while n < cap(i, 63) and flat[i + n] == flat[i]:
                n += 1
            if n >= 3:
                body += bytes([0xBF - n, flat[i]])
            else:
                n = 1
                while n < cap(i, 65) and flat[i + n] is not None:
                    n += 1
                body.append(256 - n)
                body += bytes(flat[i : i + n])
        i += n
    skip = [10 + boundary_offsets[b] if b in boundary_offsets else 0 for b in
            (32 * k * width for k in (1, 2, 3, 4))]
    return struct.pack("<5H", 10, *skip) + bytes(body)
