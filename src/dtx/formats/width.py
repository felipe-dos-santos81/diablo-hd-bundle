from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from dtx.formats.cel import CelScan, scan_cel_frame
from dtx.formats.cl2 import Cl2Scan, scan_cl2_frame

MAX_WIDTH = 640
# Most common first, then constant widths used by DevilutionX (Source/*.cpp LoadCel calls).
PREFERRED_WIDTHS = (
    32, 64, 96, 128, 160, 180, 192, 256,
    28, 56, 12, 33, 37, 48, 61, 71, 88, 261, 271, 296, 430, 591, 640,
)

Scan = CelScan | Cl2Scan


@dataclass(frozen=True)
class WidthResult:
    widths: tuple[int, ...]
    source: str
    candidates: tuple[int, ...] = ()


def candidate_order() -> list[int]:
    preferred = list(PREFERRED_WIDTHS)
    return preferred + [w for w in range(1, MAX_WIDTH + 1) if w not in preferred]


def scan_frame(fmt: str, raw: bytes) -> Scan:
    if fmt == "cel":
        return scan_cel_frame(raw)
    if fmt == "cl2":
        return scan_cl2_frame(raw)
    raise ValueError(f"unknown sprite format {fmt!r}")


def resolve_widths(scans: Sequence[Scan], hint: int | Sequence[int] | None) -> WidthResult:
    count = len(scans)
    if hint is not None:
        widths = tuple(int(w) for w in hint) if isinstance(hint, (list, tuple)) else (int(hint),) * count
        # DevilutionX decodes with the table width and ignores CL2 skip tables, some of which
        # disagree with it (warrior bow attacks), so a table width only has to decode.
        if len(widths) == count and all(s.fits(w, strict=False) for s, w in zip(scans, widths)):
            return WidthResult(widths, "table")

    order = candidate_order()
    common = tuple(w for w in order if all(s.fits(w) for s in scans))
    if common:
        return WidthResult((common[0],) * count, "inferred", common)

    per_frame = []
    for index, scan in enumerate(scans):
        width = next((w for w in order if scan.fits(w)), None)
        if width is None:
            raise ValueError(f"no width between 1 and {MAX_WIDTH} fits frame {index}")
        per_frame.append(width)
    return WidthResult(tuple(per_frame), "inferred_per_frame")
