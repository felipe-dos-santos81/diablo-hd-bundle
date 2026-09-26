from __future__ import annotations

from dataclasses import dataclass, field

from dtx.binary import u16
from dtx.formats.frame import Frame

SKIP_TABLE_HEADER_BYTES = 10


@dataclass(frozen=True, eq=False)
class Cl2Scan:
    """Width-independent decode of a CL2 frame."""

    pixels: bytes
    mask: bytes
    run_starts: dict[int, int] = field(default_factory=dict)  # byte offset -> pixels before it
    skip_offsets: tuple[int, ...] = ()

    def fits(self, width: int, strict: bool = True) -> bool:
        if width <= 0 or len(self.pixels) % width:
            return False
        if strict:
            for k, offset in enumerate(self.skip_offsets):
                if offset and self.run_starts.get(offset) != 32 * (k + 1) * width:
                    return False
        return True

    def to_frame(self, width: int) -> Frame:
        if not self.fits(width, strict=False):
            raise ValueError(f"CL2 frame has {len(self.pixels)} pixels, not a multiple of width {width}")
        return Frame.from_bottom_up(self.pixels, self.mask, width)


def scan_cl2_frame(raw: bytes) -> Cl2Scan:
    if not raw:
        return Cl2Scan(b"", b"", {0: 0}, ())
    start = u16(raw, 0)
    if start > len(raw):
        raise ValueError("CL2 frame header size exceeds frame length")
    skip = tuple(u16(raw, 2 + 2 * k) for k in range(4)) if start >= SKIP_TABLE_HEADER_BYTES else ()
    pixels, mask = bytearray(), bytearray()
    run_starts: dict[int, int] = {}
    i, n = start, len(raw)
    while i < n:
        run_starts[i] = len(pixels)
        control = raw[i]
        i += 1
        if control < 0x80:
            pixels += bytes(control)
            mask += bytes(control)
        elif control <= 0xBE:
            if i >= n:
                raise ValueError("CL2 fill run is missing its colour byte")
            run = 0xBF - control
            pixels += bytes([raw[i]]) * run
            mask += b"\x01" * run
            i += 1
        else:
            run = 256 - control
            if i + run > n:
                raise ValueError("CL2 pixel run extends past the end of the frame")
            pixels += raw[i : i + run]
            mask += b"\x01" * run
            i += run
    run_starts[n] = len(pixels)
    return Cl2Scan(bytes(pixels), bytes(mask), run_starts, skip)


def decode_cl2_frame(raw: bytes, width: int) -> Frame:
    return scan_cl2_frame(raw).to_frame(width)
