"""고유 임시 데이터만 사용하는 frozen spawn/Qt/기본 차단 smoke oracle."""

from __future__ import annotations

import importlib
import importlib.metadata
import multiprocessing
import os
import sys
import tempfile
import wave
from pathlib import Path
from typing import Any
from unittest.mock import patch

from release_manager import digest, excluded_component


def _block_network() -> None:
    os.environ.update({"HF_HUB_OFFLINE": "1", "HF_HUB_DISABLE_TELEMETRY": "1", "DO_NOT_TRACK": "1"})

    def audit(event: str, args: tuple[object, ...]) -> None:
        if event in {"socket.connect", "socket.getaddrinfo", "socket.gethostbyname"}:
            raise RuntimeError("SMOKE_NETWORK_FORBIDDEN")

    sys.addaudithook(audit)


def _child(output: Any) -> None:
    _block_network()
    # L01 D1: the frozen bundle must not carry PyAV; its import is an inert stub.
    frozen = bool(getattr(sys, "frozen", False))
    stub = getattr(sys.modules.get("av"), "__recoryn_stub__", False) is True
    if frozen and not stub:
        raise RuntimeError("PYAV_BUNDLED_OR_HOOK_MISSING")
    bundle = Path(getattr(sys, "_MEIPASS", "."))
    if frozen and any(
        excluded_component(path.relative_to(bundle).as_posix())
        for path in bundle.rglob("*")
        if path.is_file()
    ):
        raise RuntimeError("LICENSE_EXCLUDED_COMPONENT_BUNDLED")
    ctranslate2 = importlib.import_module("ctranslate2")
    faster_whisper = importlib.import_module("faster_whisper")
    onnxruntime = importlib.import_module("onnxruntime")
    onnx = importlib.import_module("onnx")
    sherpa = importlib.import_module("sherpa_onnx")
    core_version = importlib.metadata.version("sherpa-onnx-core")
    if (onnx.__version__, sherpa.__version__, core_version) != ("1.23.2", "2.0.1", "2.0.1"):
        raise RuntimeError("DIARIZATION_BUNDLE_VERSION_MISMATCH")

    from recoryn.app.inference import LocalSTTProcess
    from recoryn.app.inference import _worker as inference_worker
    from recoryn.transcription.audio_input import prepare_whisper_audio

    # Decode/resample a synthetic 0.1 s 48 kHz stereo WAV without any model.
    with tempfile.SpooledTemporaryFile() as clip:
        with wave.open(clip, "wb") as stream:
            stream.setnchannels(2)
            stream.setsampwidth(2)
            stream.setframerate(48_000)
            stream.writeframes(bytes((0x00, 0x10, 0x00, 0x10)) * 4_800)
        clip.seek(0)
        decoded = prepare_whisper_audio(clip.read(), importlib.import_module("numpy"))
    if decoded.shape != (1_600,) or str(decoded.dtype) != "float32":
        raise RuntimeError("STT_INPUT_DECODE_FAILED")
    from recoryn.diarization import DiarizationConfig, LocalDiarizationProcess

    optional = LocalDiarizationProcess(
        DiarizationConfig(Path(tempfile.gettempdir()) / "absent-release-smoke.json", "a" * 64)
    )
    capability = optional.capabilities()
    optional.close()
    if not capability["diarization"] or capability["model_state"] != "not_checked":
        raise RuntimeError("DIARIZATION_BUNDLE_CAPABILITY_MISSING")

    # Exercise production worker startup/shutdown without submitting inference.
    requests = multiprocessing.get_context("spawn").Queue(maxsize=1)
    replies = multiprocessing.get_context("spawn").Queue(maxsize=1)
    try:
        requests.put(None)
        inference_worker("absent-smoke-model", "cpu", requests, replies)
    finally:
        for channel in (requests, replies):
            channel.close()
            channel.join_thread()

    output.put(
        {
            "pid": os.getpid(),
            "whisper": faster_whisper.__version__,
            "av": "NOT_BUNDLED_STUB" if stub else "SOURCE_ENVIRONMENT_NOT_USED",
            "stt_input": "DECODED_16K_MONO_FLOAT32",
            "ctranslate2": ctranslate2.__version__,
            "onnxruntime": onnxruntime.__version__,
            "onnx": onnx.__version__,
            "sherpa_onnx": sherpa.__version__,
            "sherpa_onnx_core": core_version,
            "diarization": capability,
            "adapter": LocalSTTProcess.__name__,
            "production_worker": "STARTED_AND_STOPPED_WITHOUT_INFERENCE",
        }
    )


def run() -> dict[str, Any]:
    _block_network()
    context = multiprocessing.get_context("spawn")
    output = context.Queue(maxsize=1)
    child = context.Process(target=_child, args=(output,))
    try:
        child.start()
        child_result = output.get(timeout=90)
        child.join(10)
        if child.is_alive() or child.exitcode != 0 or child_result["pid"] == os.getpid():
            raise RuntimeError("FROZEN_SPAWN_FAILED")
    finally:
        if child.is_alive():
            child.terminate()
            child.join(10)
        output.close()
        output.join_thread()
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    with tempfile.TemporaryDirectory(prefix="recoryn-frozen-smoke-") as folder:
        from PySide6.QtCore import QTimer, qVersion
        from PySide6.QtWidgets import QApplication

        from recoryn.cli import _export, _simulate
        from recoryn.security import ConsentStore, Gateway, SecurityError
        from recoryn.storage import Library
        from recoryn.ui.main import MainWindow

        root = Path(folder)
        with ConsentStore(root / "consent.sqlite") as consents:
            try:
                Gateway(consents).request(
                    "openai", "https://api.openai.com/v1/responses", "text", b"{}"
                )
            except SecurityError as exc:
                if exc.code != "CONSENT_REQUIRED":
                    raise RuntimeError("DEFAULT_NETWORK_POLICY_FAILED") from None
            else:
                raise RuntimeError("DEFAULT_NETWORK_POLICY_FAILED")
        with Library(root / "library") as library:
            recorded = _simulate(library, 0.1)
            if recorded.get("state") != "FINALIZED" or not library.chunks(recorded["session_id"]):
                raise RuntimeError("SYNTHETIC_RECORDING_FAILED")
            originals = {
                path: digest(path)
                for chunk in library.chunks(recorded["session_id"])
                for path in (library.root / chunk.relative_path).iterdir()
                if path.is_file()
            }
            exported = _export(library, recorded["session_id"], root / "export")
            if not exported["complete"] or len(exported["files"]) != 2:
                raise RuntimeError("SYNTHETIC_EXPORT_FAILED")
            frames = {}
            for item in exported["files"]:
                with wave.open(str(root / "export" / item["file"]), "rb") as stream:
                    frames[item["track_id"]] = stream.getnframes()
            if frames != {"mic": 4410, "system": 4800}:
                raise RuntimeError("SYNTHETIC_FRAME_ACCOUNTING_FAILED")
            if any(digest(path) != checksum for path, checksum in originals.items()):
                raise RuntimeError("ORIGINAL_MEDIA_CHANGED")
            application = QApplication.instance() or QApplication([])
            # Fail even on accidental future startup device/vault access.
            with (
                patch(
                    "recoryn.capture.devices._WinAPI",
                    side_effect=RuntimeError("SMOKE_NATIVE_ACCESS_FORBIDDEN"),
                ) as devices,
                patch(
                    "recoryn.capture.wasapi.NativeWasapiBackend.open",
                    side_effect=RuntimeError("SMOKE_CAPTURE_FORBIDDEN"),
                ) as capture,
                patch(
                    "recoryn.security.vault._load_api",
                    side_effect=RuntimeError("SMOKE_VAULT_FORBIDDEN"),
                ) as vault,
            ):
                window = MainWindow(library)
                window.show()
                QTimer.singleShot(50, window.close)
                QTimer.singleShot(15_000, application.quit)
                application.exec()
                if not window._closing:
                    raise RuntimeError("OFFSCREEN_CLOSE_ACK_FAILED")
                if devices.called or capture.called or vault.called:
                    raise RuntimeError("SMOKE_PRIVILEGED_ACCESS_ATTEMPTED")
        return {
            "status": "PASS",
            "spawn": child_result,
            "qt": qVersion(),
            "recording": "FINALIZED",
            "separate_originals": "UNCHANGED_AFTER_WAV_EXPORT",
            "frames": frames,
            "network_default": "DENIED_BEFORE_DNS",
            "network_observation": "PYTHON_SOCKET_AUDIT_ONLY_NATIVE_TRAFFIC_NOT_OBSERVED",
            "hardware_capture": "NOT_RUN",
            "model_inference": "NOT_RUN",
        }
