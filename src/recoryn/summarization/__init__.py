"""Reference-preserving summary adapters; all network calls use an injected gateway."""

from recoryn.providers import (
    SummaryCheckpoint,
    SummaryClaim,
    SummaryProvider,
    SummaryRequest,
    SummaryResult,
)

from .adapters import (
    TEMPLATES,
    AnthropicSummarizer,
    GeminiSummarizer,
    OllamaSummarizer,
    OpenAISummarizer,
)
from .planning import SummaryChunk, TextSlice, plan_summary

__all__ = [
    "AnthropicSummarizer",
    "GeminiSummarizer",
    "OllamaSummarizer",
    "OpenAISummarizer",
    "SummaryCheckpoint",
    "SummaryClaim",
    "SummaryProvider",
    "SummaryRequest",
    "SummaryResult",
    "SummaryChunk",
    "TextSlice",
    "TEMPLATES",
    "plan_summary",
]
