import numpy as np

TRN_BYTES = 256


def decode_trn(data: bytes) -> np.ndarray:
    """A TRN maps each palette index to a replacement index (monster colour variants)."""
    if len(data) < TRN_BYTES:
        raise ValueError(f"TRN must be at least {TRN_BYTES} bytes, got {len(data)}")
    return np.frombuffer(data[:TRN_BYTES], np.uint8).copy()
