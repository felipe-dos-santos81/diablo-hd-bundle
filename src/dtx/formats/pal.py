import numpy as np

from dtx.paths import directory

PALETTE_BYTES = 768

# Colour-cycling ranges by palette directory, from DevilutionX
# Source/engine/palette.cpp (palette_update_caves/crypt/hive) and
# Source/lighting.cpp (lighting_color_cycling) at commit 8bef7bce.
CYCLING: dict[str, list[dict]] = {
    "levels\\l3data": [{"first": 1, "last": 31, "direction": "forward", "every_n_frames": 1}],
    "levels\\l4data": [
        {"first": 1, "last": 31, "direction": "forward", "every_n_frames": 1, "via": "light_tables"}
    ],
    "nlevels\\l5data": [
        {"first": 1, "last": 15, "direction": "reverse", "every_n_frames": 2},
        {"first": 16, "last": 31, "direction": "reverse", "every_n_frames": 1},
    ],
    "nlevels\\l6data": [
        {"first": 1, "last": 8, "direction": "reverse", "every_n_frames": 3},
        {"first": 9, "last": 15, "direction": "reverse", "every_n_frames": 3},
    ],
}


def decode_pal(data: bytes) -> np.ndarray:
    if len(data) != PALETTE_BYTES:
        raise ValueError(f"palette must be {PALETTE_BYTES} bytes, got {len(data)}")
    return np.frombuffer(data, np.uint8).reshape(256, 3).copy()


def cycling_for(pal_name: str) -> list[dict]:
    return [dict(r) for r in CYCLING.get(directory(pal_name), [])]
