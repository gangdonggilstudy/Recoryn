from __future__ import annotations

import threading
import wave
from pathlib import Path

import pytest

from recoryn.app.inference import LocalSTTProcess
from recoryn.providers import ExecutionContext, ProviderError, STTRequest


def test_missing_model_is_safe_child_failure_and_child_is_reusable(tmp_path: Path):
    audio = tmp_path / "audio.wav"
    with wave.open(str(audio), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(16000)
        stream.writeframes(b"\0\0" * 160)
    provider = LocalSTTProcess(tmp_path / "missing", timeout=10)
    assert provider._process is None
    try:
        first = provider.transcribe(STTRequest(audio))
        assert not first.complete and first.error_code == "MODEL_MISSING"
        child = provider._process
        assert child.is_alive()
        second = provider.transcribe(STTRequest(audio))
        assert second.error_code == "MODEL_MISSING"
        assert provider._process is child
    finally:
        provider.close()
    assert provider._process is None


def test_cancel_before_inference_never_spawns_process(tmp_path: Path):
    cancel = threading.Event()
    cancel.set()
    provider = LocalSTTProcess(tmp_path / "missing")
    with pytest.raises(ProviderError, match="CANCELLED"):
        provider.transcribe(STTRequest(tmp_path / "missing.wav"), ExecutionContext(cancel=cancel))
    assert provider._process is None
    provider.close()


@pytest.mark.parametrize("device,timeout", [("auto", 5), ("cpu", 0), ("cuda", -1)])
def test_execution_policy_invalid(device, timeout, tmp_path):
    with pytest.raises(ProviderError):
        LocalSTTProcess(tmp_path, device=device, timeout=timeout)
