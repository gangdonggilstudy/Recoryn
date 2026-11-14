from __future__ import annotations

import hashlib
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from recoryn.domain import StateConflict, ValidationError
from recoryn.models import FileSpec, GPUInfo, ModelManager, ModelSpec, ResourceScheduler, probe_gpus
from recoryn.models.manager import parse_spec


def spec(data: bytes = b"a model") -> ModelSpec:
    return ModelSpec(
        "test-model",
        "whisper",
        "MIT",
        "https://example.invalid/LICENSE",
        (
            FileSpec(
                "model.bin",
                "https://example.invalid/model",
                len(data),
                hashlib.sha256(data).hexdigest(),
            ),
        ),
    )


def test_no_install_without_explicit_approval(tmp_path: Path) -> None:
    def forbidden(url: str, offset: int):
        raise AssertionError("must not connect")

    manager = ModelManager(tmp_path / "models", downloader=forbidden)
    assert manager.list_installed() == []
    with pytest.raises(ValidationError, match="APPROVAL"):
        manager.install(spec())
    assert not manager.root.exists()


def test_verified_install_corruption_and_delete(tmp_path: Path) -> None:
    data = b"a model"
    manager = ModelManager(tmp_path / "models", downloader=lambda u, o: iter([data[o:]]))
    path = manager.install(spec(), approved=True)
    assert manager.verify("test-model") == path
    assert manager.list_installed()[0]["verified"] is True
    with pytest.raises(StateConflict, match="ALREADY"):
        manager.install(spec(), approved=True)
    (path / "model.bin").write_bytes(b"altered")
    with pytest.raises(ValidationError, match="CHECKSUM"):
        manager.verify("test-model")
    assert manager.list_installed()[0]["verified"] is False
    manager.delete("test-model")
    assert manager.list_installed() == []


def test_cancel_resume_exact_prefix_and_no_activation(tmp_path: Path) -> None:
    cancel = threading.Event()
    calls: list[int] = []

    def stream(url: str, offset: int):
        calls.append(offset)
        if offset == 0:
            yield b"a "
            cancel.set()
            yield b"model"
        else:
            yield b"model"

    manager = ModelManager(tmp_path / "models", downloader=stream)
    with pytest.raises(StateConflict, match="CANCELLED"):
        manager.install(spec(), approved=True, cancel=cancel)
    assert not (manager.root / "test-model").exists()
    cancel.clear()
    assert manager.install(spec(), approved=True).is_dir()
    assert calls == [0, 2]


@pytest.mark.parametrize(
    "data,code", [(b"bad!!!!", "CHECKSUM"), (b"short", "INCOMPLETE"), (b"oversized!", "OVERSIZED")]
)
def test_download_faults_never_activate(tmp_path: Path, data: bytes, code: str) -> None:
    manager = ModelManager(tmp_path / "models", downloader=lambda u, o: iter([data]))
    with pytest.raises(ValidationError, match=code):
        manager.install(spec(), approved=True)
    assert not (manager.root / "test-model").exists()


@pytest.mark.parametrize(
    "path", ["../escape", "a/../b", "x:y", "CON.bin", "a\\b", "/absolute", "x.", "a//b"]
)
def test_manifest_path_rejection(path: str) -> None:
    with pytest.raises(ValidationError):
        FileSpec(path, "https://example.invalid/x", 1, "a" * 64)


@pytest.mark.parametrize(
    "url",
    [
        "http://example.invalid/x",
        "https://u:p@host/x",
        "https://host/x#part",
        "file:///x",
        "https://host:bad/x",
        "https://host/x\n",
    ],
)
def test_download_url_rejection(url: str) -> None:
    with pytest.raises(ValidationError):
        FileSpec("x.bin", url, 1, "a" * 64)


def test_changed_plan_blocked_and_limited_schema(tmp_path: Path) -> None:
    manager = ModelManager(tmp_path / "models", downloader=lambda u, o: iter([b"a"]))
    with pytest.raises(ValidationError, match="INCOMPLETE"):
        manager.install(spec(), approved=True)
    with pytest.raises(StateConflict, match="PLAN_MISMATCH"):
        manager.install(spec(b"other data"), approved=True)
    with pytest.raises(ValidationError, match="SCHEMA"):
        parse_spec({"model_id": "x"})


def test_nested_files_and_duplicate_directories() -> None:
    item = FileSpec("tokenizer/config.json", "https://example.invalid/t", 1, "a" * 64)
    with pytest.raises(ValidationError, match="DUPLICATE"):
        ModelSpec("x", "whisper", "MIT", "https://example.invalid/license", (item, item))
    parent = FileSpec("tokenizer", "https://example.invalid/t", 1, "a" * 64)
    with pytest.raises(ValidationError, match="CONFLICT"):
        ModelSpec("x", "whisper", "MIT", "https://example.invalid/license", (item, parent))


def test_gpu_policy_has_no_silent_fallback() -> None:
    scheduler = ResourceScheduler(headroom_bytes=100)
    gpu = GPUInfo(0, "test", 1000, 2000)
    assert scheduler.choose("GPU_ONLY", 900, (gpu,)) == ("cuda", 0)
    with pytest.raises(StateConflict, match="UNAVAILABLE"):
        scheduler.choose("GPU_ONLY", 901, (gpu,))
    assert scheduler.choose("GPU_WITH_CPU_FALLBACK_ALLOWED", 901, (gpu,)) == ("cpu", 0)
    assert scheduler.choose("CPU_ONLY", 10000, ()) == ("cpu", 0)
    with pytest.raises(ValidationError):
        scheduler.choose("auto", 0, ())
    with pytest.raises(ValidationError):
        scheduler.choose("CPU_ONLY", True, ())
    with pytest.raises(ValidationError):
        ResourceScheduler(headroom_bytes=-1)


def test_cancelled_resource_lease_is_released() -> None:
    scheduler = ResourceScheduler()
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(StateConflict, match="CANCELLED"), scheduler.acquire(cancel):
        pytest.fail("must not enter")
    with scheduler.acquire():
        pass


def test_gpu_probe_absence_vs_failure() -> None:
    with patch("recoryn.models.resources.shutil.which", return_value=None):
        assert probe_gpus() == ("UNAVAILABLE", ())
    with (
        patch("recoryn.models.resources.shutil.which", return_value="nvidia-smi"),
        patch("recoryn.models.resources.subprocess.run", side_effect=OSError),
    ):
        assert probe_gpus() == ("UNKNOWN", ())
