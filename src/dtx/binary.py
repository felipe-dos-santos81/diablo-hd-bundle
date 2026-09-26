def _read(data: bytes, offset: int, size: int) -> int:
    if offset < 0 or offset + size > len(data):
        raise ValueError(f"read of {size} bytes at offset {offset} past end of {len(data)}-byte buffer")
    return int.from_bytes(data[offset : offset + size], "little")


def u16(data: bytes, offset: int) -> int:
    return _read(data, offset, 2)


def u32(data: bytes, offset: int) -> int:
    return _read(data, offset, 4)
