from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from dtx.binary import u16
from dtx.formats.frame import Frame

CEL_FRAME_HEADER_BYTES = 10


@dataclass(frozen=True, eq=False)
class CelScan:
    """Width-independent decode of a CEL frame: pixels in stream order plus run extents."""

    pixels: bytes
    mask: bytes
    starts: np.ndarray  # start pixel position of each non-empty run
    ends: np.ndarray  # end (exclusive) pixel position of each non-empty run

    def fits(self, width: int, strict: bool = True) -> bool:
        """True when no run crosses a row and the frame ends on a row boundary."""
        if width <= 0 or len(self.pixels) % width:
            return False
        if len(self.starts) == 0:
            return True
        return bool(np.all(self.starts // width == (self.ends - 1) // width))

    def to_frame(self, width: int) -> Frame:
        if not self.fits(width):
            raise ValueError(f"CEL frame does not decode at width {width}")
        return Frame.from_bottom_up(self.pixels, self.mask, width)


def scan_cel_frame(raw: bytes, allow_header: bool = True) -> CelScan:
    src = raw
    if allow_header and len(raw) >= CEL_FRAME_HEADER_BYTES and u16(raw, 0) == CEL_FRAME_HEADER_BYTES:
        src = raw[CEL_FRAME_HEADER_BYTES:]
    pixels, mask = bytearray(), bytearray()
    starts: list[int] = []
    ends: list[int] = []
    i, pos, n = 0, 0, len(src)
    while i < n:
        control = src[i]
        i += 1
        if control >= 0x80:
            run = 256 - control
            pixels += bytes(run)
            mask += bytes(run)
        else:
            run = control
            if i + run > n:
                raise ValueError("CEL pixel run extends past the end of the frame")
            pixels += src[i : i + run]
            mask += b"\x01" * run
            i += run
        if run:
            starts.append(pos)
            ends.append(pos + run)
        pos += run
    return CelScan(bytes(pixels), bytes(mask), np.array(starts, np.int64), np.array(ends, np.int64))


def decode_cel_frame(raw: bytes, width: int, allow_header: bool = True) -> Frame:
    return scan_cel_frame(raw, allow_header).to_frame(width)
