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


def module_paths(handles: list[Any], file_name: Any) -> list[str]:
    """Names of every enumerated module; one unresolved name fails the whole list (L08-02).

    A partial list could hide exactly the module whose absence is being checked.
    """
    paths = []
    for handle in handles:
        path = file_name(handle)
        if not path:
            raise OSError("MODULE_NAME_UNRESOLVED")
        paths.append(path)
    return paths


def loaded_modules() -> list[str]:
    """Full paths of every module (EXE, DLL, PYD) mapped in this process."""
    import ctypes
    from ctypes import wintypes

    psapi = ctypes.WinDLL("psapi")
    kernel32 = ctypes.WinDLL("kernel32")
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    psapi.EnumProcessModules.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.HMODULE),
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    psapi.EnumProcessModules.restype = wintypes.BOOL
    kernel32.GetModuleFileNameW.argtypes = [wintypes.HMODULE, wintypes.LPWSTR, wintypes.DWORD]
    process = kernel32.GetCurrentProcess()
    count = 1024
    while True:
        handles = (wintypes.HMODULE * count)()
        needed = wintypes.DWORD()
        if not psapi.EnumProcessModules(
            process, handles, ctypes.sizeof(handles), ctypes.byref(needed)
        ):
            raise OSError("ENUM_PROCESS_MODULES_FAILED")
        if needed.value <= ctypes.sizeof(handles):
            break
        count = needed.value // ctypes.sizeof(wintypes.HMODULE) + 64

    def file_name(handle: Any) -> str | None:
        buffer = ctypes.create_unicode_buffer(32_768)
        length = kernel32.GetModuleFileNameW(wintypes.HMODULE(handle), buffer, len(buffer))
        # 0 is a failure; a full buffer means the name was truncated.
        return buffer.value if 0 < length < len(buffer) else None

    return module_paths(list(handles[: needed.value // ctypes.sizeof(wintypes.HMODULE)]), file_name)


# Seeded so a frozen run and a source run feed the same features (L-P08).
GPU_FEATURES_SEED = 7
GPU_PROMPTS = [[1, 2, 5, 9], [1, 3, 5, 9]]


def _gpu_child(output: Any, runtime_root: str, model: str) -> None:
    """Activate the user's GPU runtime exactly as the inference worker does, then report.

    Facts only: the builder-side verdict (scripts/gpu_frozen_smoke.py) decides pass/fail.
    """
    _block_network()
    from recoryn.app.inference import _activate_gpu

    report: dict[str, Any] = {
        "pid": os.getpid(),
        "frozen": bool(getattr(sys, "frozen", False)),
        # Always a string, so a source run is judged NOT_FROZEN with every other check.
        "bundle": str(Path(getattr(sys, "_MEIPASS", "")).resolve())
        if getattr(sys, "frozen", False)
        else "",
        "activate": _activate_gpu(runtime_root),
    }
    if report["activate"] is None:
        import numpy as np

        ctranslate2 = sys.modules["ctranslate2"]
        transcribe = importlib.import_module("faster_whisper.transcribe")
        report.update(
            {
                "module": ctranslate2.__file__,
                "ext": sys.modules["ctranslate2._ext"].__file__,
                "version": ctranslate2.__version__,
                "cuda_devices": int(ctranslate2.get_cuda_device_count()),
                "faster_whisper_uses_runtime": transcribe.ctranslate2 is ctranslate2,
            }
        )
        rng = np.random.default_rng(GPU_FEATURES_SEED)
        features = rng.standard_normal((2, 80, 3000)).astype(np.float32)
        tokens = {}
        runs = {}
        for compute in ("float16", "float32"):
            whisper = ctranslate2.models.Whisper(model, device="cuda", compute_type=compute)
            # What the loaded model actually runs on, read back from it (L08-03).
            runs[compute] = {
                "device": whisper.device,
                "device_index": list(whisper.device_index),
                "compute_type": whisper.compute_type,
            }
            results = whisper.generate(
                ctranslate2.StorageView.from_array(features),
                GPU_PROMPTS,
                beam_size=1,
                max_length=24,
                suppress_blank=False,
                suppress_tokens=[],
            )
            tokens[compute] = [list(result.sequences_ids[0]) for result in results]
            del whisper
        report["runs"] = runs
        report["tokens"] = tokens
    try:
        report["loaded"] = loaded_modules()
    except OSError as error:
        report["loaded"] = None
        report["loaded_error"] = str(error)
    output.put(report)


def gpu_probe(runtime_root: Path, model: Path, *, timeout: float = 180) -> dict[str, Any]:
    """Run ``_gpu_child`` in a spawned (frozen) worker process; never downloads anything."""
    _block_network()
    context = multiprocessing.get_context("spawn")
    output = context.Queue(maxsize=1)
    child = context.Process(
        target=_gpu_child, args=(output, str(runtime_root.absolute()), str(model.absolute()))
    )
    try:
        child.start()
        try:
            report: dict[str, Any] = output.get(timeout=timeout)
        except Exception:
            return {"activate": "GPU_SMOKE_CHILD_FAILED", "exitcode": child.exitcode}
        child.join(30)
        report["exitcode"] = child.exitcode
        return report
    finally:
        if child.is_alive():
            child.terminate()
            child.join(10)
        output.close()
        output.join_thread()


PLAYBACK_VERIFIED = "PCM_SINK_PLAYED_MUTED_FROM_EXACT_FRAME"
PLAYBACK_CHANNELS = 12  # Media Foundation could not advance 12..32 channels (L04 review)
PLAYBACK_RATE = 16_000
PLAYBACK_CLIP_MS = 3_000
PLAYBACK_SEEK_MS = 2_000


def overall_status(playback: dict[str, Any]) -> str:
    """NOT_RUN or any unverified playback is never a pass (L04-P01)."""
    return "PASS" if playback.get("status") == PLAYBACK_VERIFIED else "PLAYBACK_NOT_VERIFIED"


def progress_ok(first: int | None, second: int | None) -> bool:
    """Positions 150 ms and 600 ms after starting at PLAYBACK_SEEK_MS.

    The start must land on the requested position, time must advance, and the
    position must not run ahead of the wall clock (L04 playback review).
    """
    if first is None or second is None:
        return False
    return (
        PLAYBACK_SEEK_MS <= first <= PLAYBACK_SEEK_MS + 400
        and second - first >= 200
        and second <= PLAYBACK_SEEK_MS + 900
    )


def _playback_probe(folder: Path) -> dict[str, Any]:
    """L01 D7: the product playback path cuts the exact frame and plays it.

    The clip is synthetic silence played at volume 0, so nothing is audible.
    Without an audio output device this is reported NOT_RUN, never as a pass.
    """
    import hashlib

    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtMultimedia import QMediaDevices

    from recoryn.ui.pcm_playback import SinkPlayback, prepare_playback

    if not QMediaDevices.audioOutputs():
        return {"status": "NO_AUDIO_OUTPUT_DEVICE_NOT_RUN"}
    clip = folder / "playback-probe.wav"
    with wave.open(str(clip), "wb") as stream:
        stream.setnchannels(PLAYBACK_CHANNELS)
        stream.setsampwidth(2)
        stream.setframerate(PLAYBACK_RATE)
        stream.writeframes(bytes(PLAYBACK_CHANNELS * 2 * PLAYBACK_RATE * PLAYBACK_CLIP_MS // 1000))
    pcm = prepare_playback(clip, hashlib.sha256(clip.read_bytes()).hexdigest(), PLAYBACK_SEEK_MS)
    remaining = PLAYBACK_RATE * (PLAYBACK_CLIP_MS - PLAYBACK_SEEK_MS) // 1000
    if (pcm.channels, pcm.start_frame, len(pcm.payload)) != (
        1,
        PLAYBACK_RATE * PLAYBACK_SEEK_MS // 1000,
        remaining * 2,
    ):
        raise RuntimeError("PLAYBACK_PREPARE_FAILED")
    player = SinkPlayback()
    positions: list[int | None] = []

    def wait(milliseconds: int) -> None:
        loop = QEventLoop()
        QTimer.singleShot(milliseconds, loop.quit)
        loop.exec()

    try:
        player.start(pcm, volume=0.0)
        wait(150)
        positions.append(player.position_ms())
        wait(450)
        positions.append(player.position_ms())
        if not player.active() or not progress_ok(*positions):
            raise RuntimeError("PLAYBACK_SINK_DID_NOT_ADVANCE")
    finally:
        player.stop()
    return {
        "status": PLAYBACK_VERIFIED,
        "channels_in": PLAYBACK_CHANNELS,
        "start_frame": pcm.start_frame,
        "positions_ms": positions,
    }


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
            playback = _playback_probe(root)
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
            "status": overall_status(playback),
            "spawn": child_result,
            "qt": qVersion(),
            "recording": "FINALIZED",
            "separate_originals": "UNCHANGED_AFTER_WAV_EXPORT",
            "frames": frames,
            "playback": playback,
            "network_default": "DENIED_BEFORE_DNS",
            "network_observation": "PYTHON_SOCKET_AUDIT_ONLY_NATIVE_TRAFFIC_NOT_OBSERVED",
            "hardware_capture": "NOT_RUN",
            "model_inference": "NOT_RUN",
        }
