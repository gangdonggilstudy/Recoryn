"""Cheap display peak; evaluated by the UI timer rather than capture callbacks."""

from __future__ import annotations

import math
import struct

from recoryn.domain import PCMBlock


def peak_percent(block: PCMBlock) -> int:
    width = block.format.frame_bytes // block.format.channels
    peak = 0.0
    # Bound display work; the stored original always contains every accepted sample.
    stride = max(1, block.frame_count * block.format.channels // 1024)
    for index in range(0, len(block.payload) // width, stride):
        offset = index * width
        if block.format.sample_type == "f32le":
            value = abs(struct.unpack_from("<f", block.payload, offset)[0])
        else:
            value = abs(
                int.from_bytes(block.payload[offset : offset + width], "little", signed=True)
            ) / (2 ** (width * 8 - 1))
        if math.isfinite(value):
            peak = max(peak, value)
    return min(100, int(peak * 100))
