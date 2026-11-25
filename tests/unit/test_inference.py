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
    # G-P13: without this run's confirmation the lazy object stays reusable but no child
    # or loader is ever started (native 0), however often it is asked.
    provider = LocalSTTProcess(tmp_path / "missing", timeout=10)
    assert provider._process is None
    try:
        for _ in range(2):
            with pytest.raises(ProviderError, match="CAPABILITY_UNSUPPORTED"):
                provider.transcribe(STTRequest(audio))
            assert provider._process is None
    finally:
        provider.close()
    assert provider._process is None
    # A confirmed synthetic folder that changed before start: the pre-native re-check
    # refuses it, no child starts and no partial bundle is left behind.
    from recoryn.models import artifacts
    from recoryn.models._artifact_io import whisper_snapshot

    folder = tmp_path / "model"
    folder.mkdir()
    for name in ("model.bin", "config.json", "tokenizer.json"):
        (folder / name).write_bytes(b"synthetic, not weights")
    registry = artifacts.ConfirmationRegistry()
    snapshot = whisper_snapshot(folder)
    evidence = registry.confirm(
        snapshot, shown=registry.key(snapshot), accepted=True, acknowledged=True
    )
    assert evidence is not None
    (folder / "model.bin").write_bytes(b"changed after the confirmation")
    bundles = tmp_path / "bundles"
    bundles.mkdir()
    changed = LocalSTTProcess(folder, timeout=10, model_evidence=evidence, bundle_parent=bundles)
    with pytest.raises(ProviderError, match="MODEL_CHECKSUM_MISMATCH"):
        changed.transcribe(STTRequest(audio))
    assert changed._process is None and list(bundles.iterdir()) == []
    # G13R-09 a: a load-stage failure inside a real child keeps that child and reuses it.
    # The child is handed a description whose config.json digest is wrong (names intact),
    # so its bundle check refuses before any loader, twice, in the same process.
    from recoryn.models._artifact_io import release_idle

    (folder / "model.bin").write_bytes(b"synthetic, not weights")
    evidence = registry.confirm(
        whisper_snapshot(folder),
        shown=registry.key(whisper_snapshot(folder)),
        accepted=True,
        acknowledged=True,
    )
    assert evidence is not None
    reused = LocalSTTProcess(folder, timeout=30, model_evidence=evidence, bundle_parent=bundles)
    real_args = reused._extra_args

    def forged_args() -> tuple:
        runtime, index, compute, description = real_args()
        description["entries"] = [
            [name, size, "0" * 64 if name == "config.json" else digest, state]
            for name, size, digest, state in description["entries"]
        ]
        return runtime, index, compute, description

    reused._extra_args = forged_args  # type: ignore[method-assign]
    try:
        with pytest.raises(ProviderError, match="MODEL_CHECKSUM_MISMATCH"):
            reused.load()
        child = reused._process
        assert child is not None and child.is_alive()
        with pytest.raises(ProviderError, match="MODEL_CHECKSUM_MISMATCH"):
            reused.load()
        assert reused._process is child and child.is_alive()  # the same child, reused
    finally:
        reused.close()
    assert reused._process is None
    assert release_idle() == 0 and list(bundles.iterdir()) == []
    changed.close()


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
