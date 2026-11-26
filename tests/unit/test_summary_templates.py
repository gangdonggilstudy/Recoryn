"""T21: literal template set and all four adapters' actual fake-Gateway wire."""

from __future__ import annotations

import itertools
import json
from typing import Any

import pytest

from recoryn.summarization import (
    AnthropicSummarizer,
    GeminiSummarizer,
    OllamaSummarizer,
    OpenAISummarizer,
)
from recoryn.summarization.adapters import TEMPLATES
from tests.property.test_provider_facts_case_space import execution_audit as execution_audit
from tests.unit.test_provider_facts import EXECUTED
from tests.unit.test_providers import FakeGateway, config, transcript

pytestmark = pytest.mark.unit
PROMPTS = {
    "meeting": "Summarize discussion, explicit decisions, open questions, and actions.",
    "lecture": "Summarize concepts, explanations, examples, and unresolved questions.",
    "key_points": "Extract key points and preserve material qualifications and contradictions.",
    "decisions": "Extract explicit decisions; distinguish proposed, discussed, rejected and decided.",
    "tasks": "Extract explicit actions; do not invent an owner or due date.",
}
T_CASES = [
    pytest.param(f"GS04-T-{n:03d}", *row, id=f"GS04-T-{n:03d}")
    for n, row in enumerate(
        itertools.product(
            ("meeting", "lecture", "key_points", "decisions", "tasks"),
            ("ollama", "openai", "anthropic", "gemini"),
        ),
        2,
    )
]


@pytest.mark.parametrize("case_id", ["GS04-T-001"], ids=["GS04-T-001"])
def test_five_template_set(case_id: str) -> None:
    EXECUTED.append(case_id)
    assert set(TEMPLATES) == {"meeting", "lecture", "key_points", "decisions", "tasks"}


@pytest.mark.parametrize("case_id,template,provider", T_CASES)
def test_template_wire(case_id: str, template: str, provider: str) -> None:
    EXECUTED.append(case_id)
    from dataclasses import replace

    adapters: dict[str, Any] = {
        "ollama": OllamaSummarizer,
        "openai": OpenAISummarizer,
        "anthropic": AnthropicSummarizer,
        "gemini": GeminiSummarizer,
    }
    gateway = FakeGateway()
    result = adapters[provider](gateway, config(provider)).summarize(
        replace(transcript(), template=template)
    )
    assert result.complete and len(gateway.calls) == 1
    wire = json.loads(gateway.calls[0]["body"])
    encoded = {
        "ollama": lambda: wire["messages"][1]["content"],
        "openai": lambda: wire["input"],
        "anthropic": lambda: wire["messages"][0]["content"],
        "gemini": lambda: wire["contents"][0]["parts"][0]["text"],
    }[provider]()
    assert json.loads(encoded)["template"] == PROMPTS[template]
