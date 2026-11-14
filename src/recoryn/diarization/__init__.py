"""Optional local anonymous diarization; importing never loads native dependencies."""

from .assignment import assign_speakers
from .contracts import (
    DiarizationConfig,
    DiarizationRequest,
    DiarizationResult,
    SpeakerTurn,
)
from .process import LocalDiarizationProcess

__all__ = [
    "DiarizationConfig",
    "DiarizationRequest",
    "DiarizationResult",
    "LocalDiarizationProcess",
    "SpeakerTurn",
    "assign_speakers",
]
