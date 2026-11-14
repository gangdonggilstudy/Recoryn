"""Explicit derived audio operations; source PCM is never modified.

Linear interpolation and energy VAD are basic processing tools, not a claim of
bandlimited resampling, neural speech detection, or measured device accuracy.
"""

from recoryn.audio.alignment import AlignedSpan, ClockEstimate, align_blocks, estimate_drift
from recoryn.audio.processing import (
    FrameRegion,
    LevelMeter,
    decode_pcm,
    downmix_mono,
    encode_pcm,
    energy_vad,
    measure_level,
    resample_linear,
)

__all__ = [
    "AlignedSpan",
    "ClockEstimate",
    "FrameRegion",
    "LevelMeter",
    "align_blocks",
    "decode_pcm",
    "downmix_mono",
    "encode_pcm",
    "energy_vad",
    "estimate_drift",
    "measure_level",
    "resample_linear",
]
