"""G13 UI rows: C (confirmation events 144), U (display x keys 180), T10 (managed root
prefix) and the C00 refusal rows X-02..X-05: without this run's confirmation no worker,
child or loader is created on the local STT, diarization, live STT and explicit continue
paths (the fixture adaptations elsewhere never hide that refusal).

Real ModelPanel / MainWindow widgets and real Qt key input. Expected states, texts and
counts are hand-written from docs/testing/g13-manual-model-cases.md sections 3, 4.2 and 7.
Synthetic bytes only: no weights, network, GPU or user folder.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from recoryn.diarization import DiarizationConfig
from recoryn.diarization.models import verified_bundle
from recoryn.models import ModelManager
from recoryn.models import artifacts as art
from recoryn.models._artifact_io import diarization_snapshot
from recoryn.models.manager import FileSpec, ModelSpec, spec_digest

pytestmark = pytest.mark.ui

FILES = {
    "config.json": b'{"synthetic":1}',
    "model.bin": b"synthetic model bytes, not weights",
    "tokenizer.json": b'{"tokens":[]}',
}
LICENSE = b"Synthetic license text"
# Hand-written display texts (the product's own tables are never imported).
STATE_TEXT = {
    "UNCONFIRMED": "미확인 — 확인 전에는 실행하지 않습니다",
    "MANUAL_USER_CONFIRMED": "사용자 확인됨(이 실행 동안) — 출처 인증 아님",
    "MANAGED_PIN_MATCH": "확인됨(이 실행 동안) — 고정 manifest 일치, 게시자 인증 아님",
    "CHANGED_INVALID": "변경됨 또는 검증 실패 — 실행하지 않습니다. 다시 확인하세요",
    "LICENSE_UNCONFIRMED": "조건 미확인 — 사용 권한 확인은 사용자 책임",
}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def spin(app: QApplication, condition: Callable[[], bool], timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while not condition() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.001)
    app.processEvents()
    assert condition()


def write(folder: Path, files: dict[str, bytes]) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (folder / name).write_bytes(data)
    return folder


def manifest(folder: Path, *, variant: bytes = b"", digest: str | None = None) -> DiarizationConfig:
    folder.mkdir(parents=True, exist_ok=True)
    models = {}
    for role in ("segmentation", "embedding"):
        data = b"synthetic-not-onnx-" + role.encode() + variant
        (folder / f"{role}.onnx").write_bytes(data)
        (folder / f"LICENSE.{role}.txt").write_bytes(LICENSE)
        models[role] = {
            "file": f"{role}.onnx",
            "size": len(data),
            "sha256": sha(data),
            "license_id": "test-only",
            "license_url": "https://publisher.invalid/license",
            "license_file": f"LICENSE.{role}.txt",
            "license_sha256": sha(LICENSE),
        }
    path = folder / "manifest.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "runtime": "sherpa-onnx",
                "runtime_version": "2.0.1",
                "models": models,
            }
        ),
        encoding="utf-8",
    )
    return DiarizationConfig(path, digest or sha(path.read_bytes()), True)


def diarization_of(config: DiarizationConfig) -> Any:
    files, terms = verified_bundle(config)
    return diarization_snapshot(
        files,
        config.manifest_path.parent,
        license_id=terms["license_id"],
        license_url=terms["license_url"],
        reference=config.manifest_sha256,
    )


class Env:
    """One real, shown ModelPanel; each row gets a fresh run registry and models root."""

    def __init__(self, root: Path, mp: pytest.MonkeyPatch) -> None:
        from recoryn.ui.models import ModelPanel

        self.app = QApplication.instance() or QApplication([])
        self.root = root
        self.panel = ModelPanel(root / "models")
        self.panel.show()
        self.announced: list[str] = []
        self.panel._confirm_announce = lambda target, text, priority: self.announced.append(text)
        self.questions: list[str] = []
        self.answer: Any = QMessageBox.StandardButton.No
        self.during: Callable[[], None] | None = None

        def question(*args: Any, **kwargs: Any) -> Any:
            self.questions.append(str(args[1]))
            if self.during is not None:
                self.during()  # something happens while the dialog is open
            return self.answer

        mp.setattr(QMessageBox, "question", question)
        self.rows = 0

    def reset(self) -> Path:
        self.rows += 1
        panel = self.panel
        panel.confirmations = art.ConfirmationRegistry()
        panel._confirm_snapshot = panel._confirm_key = None
        panel._pins.clear()
        panel._manual_roots.clear()
        panel.confirm_ack.setChecked(False)
        panel.confirm_button.setEnabled(False)
        panel.adopt_button.setEnabled(False)
        self.announced.clear()
        self.questions.clear()
        self.answer, self.during = QMessageBox.StandardButton.No, None
        base = self.root / f"row-{self.rows}"
        base.mkdir()
        panel.manager = ModelManager(base / "models", downloader=self._download)
        return base

    _urls: dict[str, bytes] = {}

    def _download(self, url: str, offset: int) -> Iterator[bytes]:
        return iter([self._urls[url][offset:]])

    def install(self, files: dict[str, bytes], model_id: str = "whisper-u") -> tuple[Path, str]:
        specs = tuple(
            FileSpec(name, f"https://publisher.invalid/{model_id}/{name}", len(data), sha(data))
            for name, data in files.items()
        )
        spec = ModelSpec(model_id, "whisper", "test-only", "https://publisher.invalid/l", specs)
        for name, data in files.items():
            self._urls[f"https://publisher.invalid/{model_id}/{name}"] = data
        self.panel.manager.install(spec, approved=True)
        return self.panel.manager.root / model_id, spec_digest(spec)

    def close(self) -> None:
        self.panel.shutdown()
        self.panel.deleteLater()
        self.app.processEvents()


@pytest.fixture(scope="module")
def env(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Env]:
    mp = pytest.MonkeyPatch()
    value: Env | None = None
    try:
        value = Env(tmp_path_factory.mktemp("g13-ui"), mp)
        yield value
    finally:
        if value is not None:
            value.close()
        mp.undo()


def snapshot_for(env: Env, base: Path, role: str, source: str, *, variant: bytes = b"") -> Any:
    """One preview snapshot through the panel's own lane function (or None: refused)."""
    panel = env.panel
    if role == "whisper":
        files = dict(FILES, **{"model.bin": FILES["model.bin"] + variant})
        if source == "manual":
            folder = write(base / "user" / "whisper", files)
            return panel.model_snapshot(folder)
        folder = panel.manager.root / "whisper-u"
        if not folder.exists():
            folder, pin = env.install(dict(files, LICENSE=LICENSE))
            panel._pins["whisper-u"] = pin  # the reviewed spec (install or a shown manifest)
        return panel.model_snapshot(folder)
    if source == "manual":
        config = manifest(base / "user" / "diarization", variant=variant, digest="b" * 64)
    else:
        where = panel.manager.root if source == "managed" else base / "user"
        config = manifest(where / "diarization", variant=variant)
    try:
        return diarization_of(config)
    except Exception:
        return None  # an unpinned diarization model is refused before any preview


# --- C: role 2 x event 4 x button 3 x generation 3 x session 2 = 144 ----------------

EVENTS = ("first", "same", "new_digest", "new_root")
BUTTONS = ("Yes", "No", "Esc")
GENERATIONS = ("same", "new_run", "restore")
C_ROWS = list(
    itertools.product(("whisper", "diarization"), EVENTS, BUTTONS, GENERATIONS, ("keep", "change"))
)
C_CASES = [pytest.param(*row, id=f"G13-C-{i:03d}") for i, row in enumerate(C_ROWS, 1)]


@pytest.mark.parametrize(("role", "event", "button", "generation", "session"), C_CASES)
def test_a_confirmation_records_only_the_shown_bytes_after_an_explicit_yes(
    env: Env, role: str, event: str, button: str, generation: str, session: str
) -> None:
    base = env.reset()
    panel = env.panel
    source = "manual" if role == "whisper" else "user_pin"
    first = snapshot_for(env, base, role, source)
    earlier = None
    if event != "first":
        earlier = panel.confirmations.confirm(
            first, shown=panel.confirmations.key(first), accepted=True, acknowledged=True
        )
        assert earlier is not None
    if event in ("first", "same"):
        shown = first
    elif event == "new_digest":
        shown = snapshot_for(env, base, role, source, variant=b"-new")
    else:
        other = base / "elsewhere"
        if role == "whisper":
            shown = panel.model_snapshot(write(other, FILES))
        else:
            shown = diarization_of(manifest(other / "diarization"))
    if event == "same" and generation != "same":
        # A re-view after a restart or restore: nothing carries over, ask again.
        if generation == "new_run":
            panel.confirmations = art.ConfirmationRegistry()
        else:
            panel.confirmations.new_generation()
    registry = panel.confirmations
    panel.show_confirmation(shown)
    panel.confirm_ack.setChecked(True)
    env.answer = (
        QMessageBox.StandardButton.Yes if button == "Yes" else QMessageBox.StandardButton.No
    )

    def during() -> None:
        if event == "same":
            pass  # the generation was applied before the re-view
        elif generation == "new_run":
            panel.confirmations = art.ConfirmationRegistry()  # the app was restarted
        elif generation == "restore":
            registry.new_generation()  # a restore/import: nothing carries over
        if session == "change":
            env.app.processEvents()  # another session selected: not a model input

    env.during = during
    keys = {"Yes": Qt.Key.Key_Return, "No": Qt.Key.Key_Return, "Esc": Qt.Key.Key_Return}
    QTest.keyClick(panel.confirm_button, keys[button])
    env.app.processEvents()
    asked = not (event == "same" and generation == "same")
    # Already confirmed in this run: the button is off and nothing is asked.
    assert env.questions == (["로컬 모델 사용 확인"] if asked else [])
    current = panel.confirmations
    recorded = current.evidence(shown) is not None
    if event == "same" and generation == "same":
        expected = True  # the earlier record, untouched by a re-view
    elif event == "same":
        expected = button == "Yes"  # a new run asks again; only Yes records
    else:
        expected = button == "Yes" and generation == "same"  # a late Yes never records
    assert recorded is expected
    if earlier is not None and generation == "same":
        assert earlier.valid()  # No/Esc or another snapshot never revokes the earlier one
    if generation != "same" and earlier is not None and event != "same":
        assert current.evidence(earlier.snapshot) is None  # nothing carries over
    if not recorded and asked:
        assert panel.confirm_status.text() in (
            "확인하지 않았습니다(아니요/Esc).",
            "확인 화면이 바뀌어 기록하지 않았습니다. 다시 확인하세요.",
            "책임·조건 확인란을 선택해야 기록합니다.",
        )


# --- U: display 5 x role 2 x action 6 x source 3 = 180 -------------------------------

DISPLAYS = (
    "UNCONFIRMED",
    "MANUAL_USER_CONFIRMED",
    "MANAGED_PIN_MATCH",
    "CHANGED_INVALID",
    "LICENSE_UNCONFIRMED",
)
ACTIONS = ("Tab", "Enter", "Space", "Esc", "poll", "late")
SOURCES = ("manual", "managed", "user_pin")
U_ROWS = list(itertools.product(DISPLAYS, ("whisper", "diarization"), ACTIONS, SOURCES))
U_CASES = [pytest.param(*row, id=f"G13-U-{i:03d}") for i, row in enumerate(U_ROWS, 1)]


def shown_state(target: str, role: str, source: str) -> str | None:
    """Hand table: the state really shown for a target; an impossible pair is never
    promoted (manual Whisper is never 'managed', managed is never 'manual', strict
    diarization always has its license text). None: refused before any preview."""
    if role == "diarization" and source == "manual":
        return None
    confirmed = (
        "MANUAL_USER_CONFIRMED" if (role, source) == ("whisper", "manual") else "MANAGED_PIN_MATCH"
    )
    unconfirmed = (
        "LICENSE_UNCONFIRMED" if (role, source) == ("whisper", "manual") else "UNCONFIRMED"
    )
    return {
        "UNCONFIRMED": unconfirmed,
        "MANUAL_USER_CONFIRMED": confirmed,
        "MANAGED_PIN_MATCH": confirmed,
        "CHANGED_INVALID": "CHANGED_INVALID",
        "LICENSE_UNCONFIRMED": unconfirmed,
    }[target]


def confirmable(state: str, role: str, source: str) -> bool:
    """Hand table: whether the confirm button may be pressed for the shown state."""
    if state in ("MANUAL_USER_CONFIRMED", "MANAGED_PIN_MATCH"):
        return False  # already confirmed for this run
    if state == "CHANGED_INVALID":
        return not (role == "whisper" and source != "manual")  # a damaged managed install
    return True


@pytest.mark.parametrize(("target", "role", "action", "source"), U_CASES)
def test_keys_and_polls_show_one_honest_model_state(
    env: Env, target: str, role: str, action: str, source: str
) -> None:
    base = env.reset()
    panel = env.panel
    expected = shown_state(target, role, source)
    snapshot = snapshot_for(env, base, role, source)
    if expected is None:
        assert snapshot is None and not panel.confirm_button.isEnabled()
        return
    registry = panel.confirmations
    if target in ("MANUAL_USER_CONFIRMED", "MANAGED_PIN_MATCH", "CHANGED_INVALID"):
        assert registry.confirm(
            snapshot, shown=registry.key(snapshot), accepted=True, acknowledged=True
        )
    if target == "CHANGED_INVALID":
        if role == "whisper" and source != "manual":
            folder = Path(snapshot.root)
            (folder / "model.bin").write_bytes(b"tampered synthetic bytes")
            snapshot = panel.model_snapshot(folder)
        else:
            snapshot = snapshot_for(env, base, role, source, variant=b"-changed")
    panel.show_confirmation(snapshot)
    text = panel.confirm_preview.toPlainText()
    assert panel.confirm_status.text() == "상태: " + STATE_TEXT[expected]
    assert "출처 인증: 안 됨" in text and snapshot.artifact_digest in text
    assert "공식" in text and "이 실행 동안만 유효" in text  # never an official check
    can = confirmable(expected, role, source)
    assert panel.confirm_button.isEnabled() is can
    said, records = len(env.announced), len(registry)
    if action == "Tab":
        panel.confirm_ack.setFocus()
        spin(env.app, panel.confirm_ack.hasFocus)
        QTest.keyClick(panel.confirm_ack, Qt.Key.Key_Tab)
        env.app.processEvents()
        assert (QApplication.focusWidget() is panel.confirm_button) is can
        assert len(registry) == records
    elif action == "Space":
        panel.confirm_ack.setFocus()
        QTest.keyClick(panel.confirm_ack, Qt.Key.Key_Space)
        assert panel.confirm_ack.isChecked() and len(registry) == records
    elif action in ("Enter", "Esc"):
        panel.confirm_ack.setChecked(True)
        env.answer = (
            QMessageBox.StandardButton.Yes if action == "Enter" else QMessageBox.StandardButton.No
        )
        QTest.keyClick(panel.confirm_button, Qt.Key.Key_Return)
        env.app.processEvents()
        assert len(env.questions) == (1 if can else 0)  # one question, never two
        now = registry.evidence(snapshot) is not None
        assert now is (
            expected in ("MANUAL_USER_CONFIRMED", "MANAGED_PIN_MATCH")
            or (can and action == "Enter")
        )
        if can and action == "Enter":
            done = (
                "MANUAL_USER_CONFIRMED"
                if (role, source) == ("whisper", "manual")
                else "MANAGED_PIN_MATCH"
            )
            assert panel.confirm_status.text().startswith("상태: " + STATE_TEXT[done])
            assert len(env.announced) == said + 1
    elif action == "poll":
        panel.confirm_ack.setChecked(True)
        panel.show_confirmation(snapshot)  # the same model shown again
        assert panel.confirm_ack.isChecked() and len(env.announced) == said
        assert len(registry) == records
    else:  # a late answer: another model was shown while the dialog was open
        panel.confirm_ack.setChecked(True)
        env.answer = QMessageBox.StandardButton.Yes
        other = panel.model_snapshot(write(base / "late", FILES))
        env.during = lambda: panel.show_confirmation(other)
        QTest.keyClick(panel.confirm_button, Qt.Key.Key_Return)
        env.app.processEvents()
        if can:
            assert (
                panel.confirm_status.text()
                == "확인 화면이 바뀌어 기록하지 않았습니다. 다시 확인하세요."
            )
            assert registry.evidence(other) is None
        assert len(registry) == records


@pytest.mark.parametrize("case_id", ["G13-T-10"], ids=["G13-T-10"])
def test_t10_a_sibling_with_the_managed_root_as_prefix_is_not_managed(
    env: Env, case_id: str
) -> None:
    base = env.reset()
    root = env.panel.manager.root
    sibling = write(root.parent / (root.name + "-evil") / "whisper-u", FILES)
    snapshot = env.panel.model_snapshot(sibling)
    assert snapshot.source_kind == art.MANUAL and env.panel._managed(root / "whisper-u")
    assert not env.panel._managed(sibling)
    assert base.exists()


# --- X: no confirmation, no worker, child or loader on any path (C00 condition 3) ----


class Window:
    def __init__(self, root: Path, mp: pytest.MonkeyPatch) -> None:
        import recoryn.diarization as diarization
        import recoryn.security as security
        import recoryn.ui.ai_bridge as bridge_module
        from recoryn.models import ResourceRequest
        from recoryn.providers import ExecutionContext
        from recoryn.security import CredentialVault
        from recoryn.storage import Library
        from recoryn.ui.main import MainWindow
        from tests.e2e.test_ai_workflow import FakeSTT, finished, recording

        class Vault:
            def read(self, key: str) -> bytes | None:
                return None

            def write(self, *args: Any) -> None:
                pytest.fail("no credential writes")

            def delete(self, *args: Any) -> None:
                pytest.fail("no credential deletion")

        mp.setattr(
            security, "CredentialVault", lambda: CredentialVault(backend=Vault(), namespace="g13")
        )
        self.app = QApplication.instance() or QApplication([])
        self._library = Library(root / "library")
        self.library = self._library.__enter__()
        self.session = recording(self.library)
        self.window = window = MainWindow(self.library)
        window.timer.stop()
        window.refresh_sessions()
        spin(self.app, lambda: window.sessions.count() == 1)
        window.sessions.setCurrentRow(0)
        self.bridge = window.ai_bridge
        self.service = self.bridge._service()
        seed = self.service.transcribe(
            self.session,
            FakeSTT(),
            config_key="seed",
            resource_request=ResourceRequest("stt", "LOCAL_CT2", "CPU_ONLY"),
        )
        assert finished(self.service, seed).state.value == "SUCCEEDED"
        self.bridge.panel.load(self.session)
        self.workers: list[str] = []
        mp.setattr(bridge_module, "LocalSTTProcess", lambda *a, **k: self.workers.append("stt"))
        mp.setattr(
            diarization,
            "LocalDiarizationProcess",
            lambda *a, **k: self.workers.append("diarization"),
        )
        mp.setattr(
            self.service.runner, "submit", lambda *a, **k: self.workers.append("dispatch") or True
        )
        mp.setattr(window.model_panel, "request_attestation_check", lambda: None)

        def prepare(kind: str, *args: Any) -> Any:
            return SimpleNamespace(
                config=SimpleNamespace(provider_id="faster_whisper"),
                context=ExecutionContext(),
                config_key="ignored",
                gateway=None,
            )

        mp.setattr(window.privacy_panel, "prepare_execution", prepare)
        stt = window.privacy_panel.controls["stt"].provider
        stt.setCurrentIndex(stt.findData("faster_whisper"))
        self.model = write(root / "model", FILES)
        window.local_model.setText(str(self.model))

    def close(self) -> None:
        self.window.close()
        spin(self.app, lambda: self.window._closing)
        self.window.deleteLater()
        self.app.processEvents()
        self._library.__exit__(None, None, None)


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Window]:
    mp = pytest.MonkeyPatch()
    value: Window | None = None
    try:
        value = Window(tmp_path_factory.mktemp("g13-x"), mp)
        yield value
    finally:
        if value is not None:
            value.close()
        mp.undo()


def held(world: Window) -> None:
    """The request stopped before any Job: the model panel shows exactly those bytes."""
    bridge, panel = world.bridge, world.window.model_panel
    spin(world.app, lambda: not bridge.busy)
    assert "MODEL_CONFIRMATION_REQUIRED" in bridge.panel.job_status.text()
    assert bridge._preparation_action is not None
    assert bridge._preparation_action[2] == "model_confirmation"
    assert panel._confirm_snapshot is not None
    assert panel._confirm_snapshot.artifact_digest in panel.confirm_preview.toPlainText()
    bridge.open_blocked_action()
    assert world.window.tabs.currentWidget() is panel


@pytest.mark.parametrize("case_id", ["G13-X-02"], ids=["G13-X-02"])
def test_local_stt_without_a_confirmation_creates_nothing(world: Window, case_id: str) -> None:
    jobs = world.service.jobs.list_for_session(world.session)
    world.workers.clear()
    world.bridge.transcribe()
    held(world)
    assert world.workers == [] and world.service.jobs.list_for_session(world.session) == jobs


@pytest.mark.parametrize("case_id", ["G13-X-03"], ids=["G13-X-03"])
def test_diarization_without_a_confirmation_creates_nothing(world: Window, case_id: str) -> None:
    window, bridge = world.window, world.bridge
    config = manifest(world.library.root.parent / "diarization")
    window.diarization_manifest.setText(str(config.manifest_path))
    window.diarization_hash.setText(config.manifest_sha256)
    window.diarization_approval.setChecked(True)
    panel = bridge.panel
    panel.revision = {
        "complete": True,
        "session_id": world.session,
        "revision_id": "fixture",
        "segments": [],
        "coverage": {},
        "kind": "corrected",
    }
    panel.diarization_ranges.clear()
    panel.diarization_ranges.addItem("fixture", {"offset_ms": 0, "track_id": "mic"})
    jobs = world.service.jobs.list_for_session(world.session)
    world.workers.clear()
    bridge.diarize()
    held(world)
    assert world.workers == [] and world.service.jobs.list_for_session(world.session) == jobs


@pytest.mark.parametrize("case_id", ["G13-X-04"], ids=["G13-X-04"])
def test_live_stt_without_a_confirmation_creates_nothing(world: Window, case_id: str) -> None:
    jobs = world.service.jobs.list_for_session(world.session)
    world.workers.clear()
    world.bridge._live_snapshots.pop(world.session, None)
    world.bridge._transcribe(session_id=world.session, provisional=True)
    held(world)
    assert world.workers == [] and world.service.jobs.list_for_session(world.session) == jobs
    assert world.session in world.bridge._live_blocked  # live stays paused, never retried


@pytest.mark.parametrize("case_id", ["G13-X-05"], ids=["G13-X-05"])
def test_explicit_continue_without_a_confirmation_creates_nothing(
    world: Window, case_id: str
) -> None:
    from recoryn.models import ResourceRequest
    from tests.e2e.test_ai_workflow import FakeSTT

    service, bridge = world.service, world.bridge
    job_id = service.transcribe(
        world.session,
        FakeSTT(),
        config_key="g13-continue",
        resource_request=ResourceRequest("stt", "LOCAL_CT2", "CPU_ONLY"),
    )
    record = service.jobs.get(job_id)
    blocked = service.jobs.block_pending(
        job_id, "BUDGET", "COST_CAP_EXCEEDED", expected_version=record.state_version
    )
    bridge.tick()
    world.workers.clear()
    bridge.continue_blocked()
    held(world)
    assert world.workers == [] and service.jobs.get(job_id) == blocked  # still BLOCKED
    assert threading.active_count() >= 1


# --- FIX1 supplementary UI rows (G13R-06, G13R-07 a, G13R-10; outside the plan) -------


class _StuckIo:
    """An ArtifactIo whose removals fail until released (a copy still open elsewhere)."""

    @staticmethod
    def make() -> Any:
        from recoryn.models._artifact_io import ArtifactIo

        class Stuck(ArtifactIo):
            fail = True

            def remove(self, path: Path) -> None:
                if Stuck.fail:
                    raise PermissionError("still open elsewhere")
                super().remove(path)

        return Stuck


PENDING_TEXT = "임시 모델 사본 정리 대기 1개 — 다음 정리 때 다시 시도합니다"


def pending_bundle(base: Path) -> tuple[Any, Any]:
    from recoryn.models._artifact_io import freeze, release, whisper_snapshot

    stuck = _StuckIo.make()
    registry = art.ConfirmationRegistry()
    snapshot = whisper_snapshot(write(base / "pending-model", FILES))
    evidence = registry.confirm(
        snapshot, shown=registry.key(snapshot), accepted=True, acknowledged=True
    )
    bundle = freeze(evidence, parent=base, io=stuck())
    assert release(bundle) is False  # its cleanup failed: pending
    return stuck, bundle


@pytest.mark.parametrize("case_id", ["G13-X-13"], ids=["G13-X-13"])
def test_the_confirmation_names_its_folder_and_an_honest_license_line(
    env: Env, case_id: str
) -> None:
    from recoryn.models._artifact_io import release_idle

    base = env.reset()
    panel = env.panel
    folder = write(base / "user" / "whisper", dict(FILES, LICENSE=LICENSE))
    snapshot = panel.model_snapshot(folder)
    panel.show_confirmation(snapshot)
    lines = panel.confirm_preview.toPlainText().splitlines()
    assert lines[1] == f"대상 폴더: {snapshot.root}" and Path(snapshot.root) == folder.resolve()
    license_line = (
        "라이선스: 라이선스 파일 있음(SHA256 표시) — 식별자·URL 미제공, 조건 확인은 사용자 책임"
    )
    assert license_line in lines and not any("원문 없음" in line for line in lines)
    assert f"  LICENSE · {len(LICENSE):,} bytes · SHA256 {sha(LICENSE)}" in lines
    # A temporary copy whose cleanup failed stays visible until a retry removes it.
    stuck, bundle = pending_bundle(base)
    panel.refresh_cleanup()
    assert panel.cleanup_status.text() == PENDING_TEXT
    assert panel.cleanup_status.accessibleName() == "임시 모델 사본 정리 상태"
    stuck.fail = False
    assert release_idle() == 0 and not bundle.directory.exists()
    panel.refresh_cleanup()
    assert panel.cleanup_status.text() == ""
    assert (folder / "model.bin").read_bytes() == FILES["model.bin"]  # the source intact


@pytest.mark.parametrize("case_id", ["G13-X-21"], ids=["G13-X-21"])
def test_the_bridge_tick_keeps_a_pending_cleanup_visible(
    world: Window, case_id: str, tmp_path: Path
) -> None:
    from recoryn.models._artifact_io import release_idle

    panel = world.window.model_panel
    stuck, bundle = pending_bundle(tmp_path)
    world.bridge.tick()
    assert panel.cleanup_status.text() == PENDING_TEXT
    stuck.fail = False
    assert release_idle() == 0 and not bundle.directory.exists()
    world.bridge.tick()
    assert panel.cleanup_status.text() == ""


def test_declared_ui_denominators() -> None:
    assert len(C_CASES) == 2 * 4 * 3 * 3 * 2 == 144 and len(U_CASES) == 5 * 2 * 6 * 3 == 180
