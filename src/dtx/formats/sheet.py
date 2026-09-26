from __future__ import annotations

from dtx.binary import u32


def split_sheet(data: bytes) -> list[list[bytes]]:
    """Split a CEL or CL2 file into raw frame bytes, grouped as [group][frame]."""
    if len(data) < 8:
        raise ValueError("file too small to be a CEL/CL2 sheet")
    first = u32(data, 0)
    last_offset_at = 4 * first + 4
    if last_offset_at + 4 <= len(data) and u32(data, last_offset_at) == len(data):
        return [_split_frames(data)]

    if first == 0 or first % 4 or first > len(data):
        raise ValueError("not a CEL/CL2 sheet")
    count = first // 4
    try:
        return _table_groups(data, count)
    except ValueError:
        chained = _chained_groups(data, count)
        if chained is None:
            raise
        return chained


def _table_groups(data: bytes, count: int) -> list[list[bytes]]:
    offsets = [u32(data, 4 * g) for g in range(count)] + [len(data)]
    if any(b < a for a, b in zip(offsets, offsets[1:])):
        raise ValueError("CEL/CL2 group offsets are not increasing")
    # Frame offsets are relative to each group header. Real CL2 files store every group header
    # first and all frame data after them, so a group's frames may lie past the next header.
    return [_split_frames(data[offsets[g] :]) for g in range(count)]


def _chained_groups(data: bytes, count: int) -> list[list[bytes]] | None:
    """Recover a sheet whose group table is stale (two unused DIABDAT.MPQ monster files):
    walk contiguous groups, each starting where the previous one's frames end, and accept
    the result only if the last group ends exactly at the end of the file."""
    groups, start = [], 4 * count
    for _ in range(count):
        try:
            frames = _split_frames(data[start:])
        except ValueError:
            return None
        n = u32(data, start)
        groups.append(frames)
        start += u32(data, start + 4 + 4 * n)
    return groups if start == len(data) else None


def _split_frames(sheet: bytes) -> list[bytes]:
    if len(sheet) < 8:
        raise ValueError("CEL/CL2 frame header past the end of the file")
    n = u32(sheet, 0)
    if 4 * n + 8 > len(sheet):
        raise ValueError("CEL/CL2 frame count exceeds the file size")
    offsets = [u32(sheet, 4 + 4 * i) for i in range(n + 1)]
    if offsets[-1] > len(sheet) or any(b < a for a, b in zip(offsets, offsets[1:])):
        raise ValueError("CEL/CL2 frame offsets out of range")
    return [sheet[offsets[i] : offsets[i + 1]] for i in range(n)]
