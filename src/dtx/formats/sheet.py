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
    offsets = [u32(data, 4 * g) for g in range(count)] + [len(data)]
    if any(b < a for a, b in zip(offsets, offsets[1:])):
        raise ValueError("CEL/CL2 group offsets are not increasing")
    return [_split_frames(data[offsets[g] : offsets[g + 1]]) for g in range(count)]


def _split_frames(sheet: bytes) -> list[bytes]:
    n = u32(sheet, 0)
    offsets = [u32(sheet, 4 + 4 * i) for i in range(n + 1)]
    if offsets[-1] > len(sheet) or any(b < a for a, b in zip(offsets, offsets[1:])):
        raise ValueError("CEL/CL2 frame offsets out of range")
    return [sheet[offsets[i] : offsets[i + 1]] for i in range(n)]
