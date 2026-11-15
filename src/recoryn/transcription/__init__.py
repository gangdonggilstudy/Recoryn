"""Independent STT adapters. Construction never downloads or loads a model."""

from recoryn.providers import STTProvider, STTRequest, STTResult, TranscriptSegment

from .adapters import (
    FasterWhisperProvider,
    GeminiTranscriber,
    OpenAITranscriber,
    cuda_runtime_available,
)

__all__ = [
    "FasterWhisperProvider",
    "GeminiTranscriber",
    "OpenAITranscriber",
    "STTProvider",
    "STTRequest",
    "STTResult",
    "TranscriptSegment",
    "cuda_runtime_available",
]
