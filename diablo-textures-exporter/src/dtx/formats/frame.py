from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, eq=False)
class Frame:
    """A decoded image: palette indices plus an opacity mask. Row 0 is the top row."""

    indices: np.ndarray  # (h, w) uint8
    opaque: np.ndarray  # (h, w) bool

    def __post_init__(self) -> None:
        if self.indices.shape != self.opaque.shape:
            raise ValueError(
                f"indices shape {self.indices.shape} != opaque shape {self.opaque.shape}"
            )

    @property
    def width(self) -> int:
        return int(self.indices.shape[1])

    @property
    def height(self) -> int:
        return int(self.indices.shape[0])

    @classmethod
    def empty(cls, width: int = 0, height: int = 0) -> Frame:
        return cls(np.zeros((height, width), np.uint8), np.zeros((height, width), bool))

    @classmethod
    def from_bottom_up(cls, pixels: bytes, mask: bytes, width: int) -> Frame:
        """Build a frame from row-major pixel data whose first row is the bottom row."""
        if width <= 0:
            raise ValueError(f"frame width must be positive, got {width}")
        if len(pixels) != len(mask):
            raise ValueError("pixel and mask lengths differ")
        if len(pixels) % width:
            raise ValueError(f"{len(pixels)} pixels is not a multiple of width {width}")
        height = len(pixels) // width
        indices = np.frombuffer(bytes(pixels), np.uint8).reshape(height, width)[::-1].copy()
        opaque = np.frombuffer(bytes(mask), np.uint8).reshape(height, width)[::-1] != 0
        return cls(indices, opaque.copy())

    def same_pixels(self, other: Frame) -> bool:
        """True when both frames have the same opacity and the same indices where opaque."""
        return (
            self.indices.shape == other.indices.shape
            and np.array_equal(self.opaque, other.opaque)
            and np.array_equal(self.indices[self.opaque], other.indices[other.opaque])
        )
