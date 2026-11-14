"""Independent STT adapters. Construction never downloads or loads a model."""

from recoryn.providers import STTProvider, STTRequest, STTResult, TranscriptSegment

from .adapters import FasterWhisperProvider, GeminiTranscriber, OpenAITranscriber

__all__ = [
    "FasterWhisperProvider",
    "GeminiTranscriber",
    "OpenAITranscriber",
    "STTProvider",
    "STTRequest",
    "STTResult",
    "TranscriptSegment",
]
