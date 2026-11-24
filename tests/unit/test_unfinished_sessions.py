"""G04 unfinished sessions: state x action table, inventory, command sequences, values, read model.

Expected outcomes are literal tables copied from docs/testing/g04-unfinished-session-cases.md
(section 4). They are never derived from the domain transition table or the implementation.
Real SQLite and temporary files only; no device, model or network.
"""

from __future__ import annotations

import gc
import itertools
import json
import sys
import weakref
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from recoryn.app.ai import AIService
from recoryn.app.recording import RecordingError, RecordingService
from recoryn.app.recovery import (
    CANDIDATE,
    INFO,
    MISSING,
    UNKNOWN,
    describe,
    next_actions,
    recovery_view,
)
from recoryn.cli import _export, _parser
from recoryn.content import ContentStore
from recoryn.domain import AudioFormat, PCMBlock, SessionState, StateConflict, ValidationError
from recoryn.providers import ProviderCapabilities, STTResult, TranscriptSegment
from recoryn.storage import ChunkWriter, Library
from tests.resource_fakes import STT

pytestmark = pytest.mark.unit

FMT = AudioFormat(48000, 1)
SID = "s"

STATES = (
    "CREATED",
    "RECORDING_STALE",
    "RECORDING_LIVE",
    "PAUSED_STALE",
    "PAUSED_INPROC",
    "FINALIZING",
    "INTERRUPTED_STALE",
    "INTERRUPTED_INPROC",
    "FINALIZED",
    "DELETE_PENDING",
    "DIRECTORY_ONLY",
    "NOT_FOUND",
)
ACTIONS = ("FINALIZE", "RESUME", "EXPORT", "TRANSCRIBE", "DELETE", "RECOVER")


def pcm(session: str, epoch: str, sequence: int, track: str = "mic") -> PCMBlock:
    return PCMBlock(
        session,
        track,
        epoch,
        sequence,
        FMT,
        4,
        bytes([10 + sequence, 0]) * 4,
        1_000 + sequence * 100,
        1_000 + sequence * 100,
        device_frame_position=sequence * 4,
    )


def sealed(root: Path, session: str, epoch: str, sequences: tuple[int, ...]) -> Any:
    writer = ChunkWriter(root, pcm(session, epoch, sequences[0]))
    for sequence in sequences:
        writer.append(pcm(session, epoch, sequence))
    return writer.seal()


def staged(root: Path, session: str, epoch: str, sequences: tuple[int, ...]) -> Path:
    """An unsealed writer left behind by a crash: staging only, never catalogued."""
    writer = ChunkWriter(root, pcm(session, epoch, sequences[0]))
    for sequence in sequences:
        writer.append(pcm(session, epoch, sequence))
    writer.abort()
    return writer.staging_path


@dataclass
class World:
    library: Library
    root: Path
    service: RecordingService | None = None
    cleanup: list[Callable[[], None]] = field(default_factory=list)
    result: Any = None


def _service_cleanup(world: World) -> None:
    service = world.service
    if service is None:
        return
    try:
        state = world.library.get_session(SID).state
        if state in {SessionState.RECORDING, SessionState.PAUSED, SessionState.CREATED}:
            service.stop()
    except (StateConflict, KeyError, RecordingError, ValueError):
        pass
    finally:
        service.join_writer()


def _stale(library: Library, root: Path, *path: SessionState, staging: bool = False) -> None:
    library.create_session(SID)
    version = 0
    for target in path:
        if target == SessionState.RECORDING:
            library.transition(SID, target, version)
            version += 1
            library.register_chunk(sealed(root, SID, "e1", (0, 1)))
            if staging:
                staged(root, SID, "e1", (2,))
            continue
        library.transition(SID, target, version)
        version += 1


def build(state: str, root: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    library = Library(root)
    world = World(library, root)
    world.cleanup.append(lambda: _service_cleanup(world))
    if state == "CREATED":
        library.create_session(SID)
    elif state == "RECORDING_STALE":
        _stale(library, root, SessionState.RECORDING, staging=True)
    elif state == "RECORDING_LIVE":
        world.service = RecordingService(library, {"mic": FMT}, session_id=SID)
        world.service.start()
    elif state == "PAUSED_STALE":
        _stale(library, root, SessionState.RECORDING, SessionState.PAUSED)
    elif state == "PAUSED_INPROC":
        world.service = RecordingService(library, {"mic": FMT}, session_id=SID)
        world.service.start()
        assert world.service.submit(pcm(SID, world.service.epochs["mic"], 0))
        world.service.pause()
    elif state == "FINALIZING":
        _stale(library, root, SessionState.RECORDING, SessionState.FINALIZING)
    elif state == "INTERRUPTED_STALE":
        _stale(library, root, SessionState.RECORDING, SessionState.INTERRUPTED, staging=True)
    elif state == "INTERRUPTED_INPROC":
        world.service = RecordingService(library, {"mic": FMT}, session_id=SID, chunk_frames=1)
        world.service.start()

        def fail_seal(writer: ChunkWriter) -> None:
            raise OSError("G04 injected seal failure")

        with monkeypatch.context() as patch:
            patch.setattr(ChunkWriter, "seal", fail_seal)
            assert world.service.submit(pcm(SID, world.service.epochs["mic"], 0))
            with pytest.raises(RecordingError, match="STORAGE_FAILED"):
                world.service.stop()
        assert not world.service.is_live()
    elif state == "FINALIZED":
        _stale(library, root, SessionState.RECORDING, SessionState.FINALIZING)
        library.finalize_session(SID)
    elif state == "DELETE_PENDING":
        _stale(library, root, SessionState.RECORDING)
        writer = ChunkWriter(root, pcm(SID, "e2", 0))
        writer.append(pcm(SID, "e2", 0))
        assert library.delete_session(SID)["state"] == "DELETE_PENDING"
        writer.abort()
    elif state == "DIRECTORY_ONLY":
        sealed(root, SID, "e1", (0, 1))  # media without any catalog row
    elif state != "NOT_FOUND":
        raise AssertionError(state)
    return world


@pytest.fixture
def worlds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[[str], World]]:
    made: list[World] = []

    def make(state: str, name: str = "library") -> World:
        world = build(state, tmp_path / name, monkeypatch)
        made.append(world)
        return world

    yield make
    for world in made:
        for step in world.cleanup:
            step()
        world.library.close()


def files(root: Path, *, originals_only: bool = False) -> dict[str, bytes]:
    base = root / "sessions" / SID
    if not base.exists():
        return {}
    found = {}
    for path in base.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(base).as_posix()
        if originals_only and not relative.startswith(("tracks/", "staging/")):
            continue
        found[relative] = path.read_bytes()
    return found


def database(library: Library) -> tuple[Any, int]:
    row = library._db.execute(
        "SELECT state,state_version FROM sessions WHERE session_id=?", (SID,)
    ).fetchone()
    events = library._db.execute(
        "SELECT COUNT(*) FROM storage_events WHERE session_id=?", (SID,)
    ).fetchone()[0]
    return (tuple(row) if row else None), events


def preserved(before: dict[str, bytes], after: dict[str, bytes]) -> bool:
    return all(after.get(name) == content for name, content in before.items())


class FakeSTT:
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities("fake", transcription=True)

    def transcribe(self, request: Any, context: Any = None) -> STTResult:
        item = TranscriptSegment("x", request.offset_ms, request.offset_ms + 1, "x")
        return STTResult("fake", "model", (item,), True, processed_ms=1)


# Section 4.3, written by hand. U = (recovery review, finalize, delete).
_FINALIZE = {
    "CREATED": "FINALIZED",
    "RECORDING_STALE": "FINALIZED",
    "RECORDING_LIVE": "SESSION_LIVE",
    "PAUSED_STALE": "FINALIZED",
    "PAUSED_INPROC": "FINALIZED",
    "FINALIZING": "FINALIZED",
    "INTERRUPTED_STALE": "FINALIZED",
    "INTERRUPTED_INPROC": "FINALIZED",
    "FINALIZED": "FINALIZED_ALREADY",
    "DELETE_PENDING": "DELETE_PENDING",
    "DIRECTORY_ONLY": "FINALIZED",
    "NOT_FOUND": "KEYERROR",
}
_RESUME = {
    "RECORDING_LIVE": "RESUME_REQUIRES_PAUSED",
    "PAUSED_INPROC": "RESUMED",
    "INTERRUPTED_INPROC": "RESUME_REQUIRES_PAUSED",
}
_EXPORT = {
    "FINALIZED": "EXPORTED",
    "DELETE_PENDING": "DELETION_INTENT",
    "DIRECTORY_ONLY": "KEYERROR",
    "NOT_FOUND": "KEYERROR",
}
_TRANSCRIBE = {
    "FINALIZED": "ACCEPTED",
    "DELETE_PENDING": "DELETION_INTENT",
    "DIRECTORY_ONLY": "KEYERROR",
    "NOT_FOUND": "KEYERROR",
}
# G-P05 (4), C00-approved: a live owner between writers keeps the intent pending.
_DELETE = {
    "DIRECTORY_ONLY": "NOT_FOUND_DELETE",
    "NOT_FOUND": "NOT_FOUND_DELETE",
    "RECORDING_LIVE": "DELETE_PENDING",
}
_RECOVER = {
    "CREATED": "STATE:CREATED",
    "RECORDING_STALE": "STATE:INTERRUPTED",
    "RECORDING_LIVE": "SESSION_LIVE",
    "PAUSED_STALE": "STATE:PAUSED",
    "PAUSED_INPROC": "STATE:PAUSED",
    "FINALIZING": "STATE:INTERRUPTED",
    "INTERRUPTED_STALE": "STATE:INTERRUPTED",
    "INTERRUPTED_INPROC": "STATE:INTERRUPTED",
    "FINALIZED": "STATE:FINALIZED",
    "DELETE_PENDING": "RECOVER_DELETE_PENDING",
    "DIRECTORY_ONLY": "STATE:CREATED",
    "NOT_FOUND": "KEYERROR",
}
EXPECT = {
    (state, action): {
        "FINALIZE": _FINALIZE[state],
        "RESUME": _RESUME.get(state, "NO_PATH"),
        "EXPORT": _EXPORT.get(state, "NOT_FINALIZED"),
        "TRANSCRIBE": _TRANSCRIBE.get(state, "REQUIRES_FINALIZED"),
        "DELETE": _DELETE.get(state, "DELETED_LOCAL"),
        "RECOVER": _RECOVER[state],
    }[action]
    for state in STATES
    for action in ACTIONS
}
# Frames in the sealed list after finalizing, from each fixture's blocks (4 frames each):
# catalogued (0, 1) = 8, a staged block 2 = 4, one in-process block = 4.
SEALED_FRAMES = {
    "CREATED": 0,
    "RECORDING_STALE": 12,
    "PAUSED_STALE": 8,
    "PAUSED_INPROC": 4,
    "FINALIZING": 8,
    "INTERRUPTED_STALE": 12,
    "INTERRUPTED_INPROC": 4,
    "FINALIZED": 8,
    "DIRECTORY_ONLY": 8,
}
REFUSALS = {
    "SESSION_LIVE",
    "DELETE_PENDING",
    "KEYERROR",
    "NOT_FINALIZED",
    "DELETION_INTENT",
    "REQUIRES_FINALIZED",
    "NO_PATH",
    "RESUME_REQUIRES_PAUSED",
    "NOT_FOUND_DELETE",
}
TABLE = [
    pytest.param(state, action, id=f"G04-T-{state}-{action}")
    for state in STATES
    for action in ACTIONS
]


def act(world: World, action: str, output: Path) -> str:
    library = world.library
    try:
        if action == "FINALIZE":
            result = world.result = library.finalize_unfinished(SID)
            return "FINALIZED_ALREADY" if result["already_finalized"] else str(result["state"])
        if action == "RESUME":
            if world.service is None:
                # No user path attaches to an existing session (resume is out of scope).
                with pytest.raises(SystemExit) as refused:
                    _parser().parse_args(["resume", SID])
                assert refused.value.code == 2
                return "NO_PATH"
            world.service.resume()
            return "RESUMED"
        if action == "EXPORT":
            _export(library, SID, output)
            assert (output / "export.json").is_file()
            return "EXPORTED"
        if action == "TRANSCRIBE":
            with ContentStore(library) as content:
                service = AIService(library, content)
                try:
                    job_id = service.transcribe(
                        SID, FakeSTT(), config_key="stt", resource_request=STT
                    )
                finally:
                    service.close()
            assert isinstance(job_id, str) and job_id
            return "ACCEPTED"
        if action == "DELETE":
            result = world.result = library.delete_session(SID)
            return "NOT_FOUND_DELETE" if result["state"] == "NOT_FOUND" else str(result["state"])
        result = library.recover_session(SID)
        if result["state"] == "DELETE_PENDING":
            return "RECOVER_DELETE_PENDING"
        again = library.recover_session(SID)
        assert (again["adopted"], again["recovered"], again["state"]) == (0, 0, result["state"])
        return "STATE:" + str(result["state"])
    except KeyError:
        return "KEYERROR"
    except RecordingError as error:
        return str(error)
    except StateConflict as error:
        message = str(error)
        if message in {"SESSION_LIVE", "DELETE_PENDING"}:
            return message
        if message == "Session has a deletion intent":
            return "DELETION_INTENT"
        if message == "TRANSCRIPTION_REQUIRES_FINALIZED_AUDIO":
            return "REQUIRES_FINALIZED"
        return "STATE_CONFLICT:" + message
    except ValueError as error:
        if str(error) == "Only finalized sessions can be exported":
            return "NOT_FINALIZED"
        raise


@pytest.mark.parametrize(("state", "action"), TABLE)
def test_state_action_table(
    worlds: Callable[[str], World], tmp_path: Path, state: str, action: str
) -> None:
    world = worlds(state)
    before_files, before_db = files(world.root), database(world.library)
    before_originals = files(world.root, originals_only=True)
    outcome = act(world, action, tmp_path / "export")
    assert outcome == EXPECT[state, action]
    if outcome in REFUSALS:
        # A refusal changes nothing: catalog row, events and every byte of the session.
        assert database(world.library) == before_db
        assert files(world.root) == before_files
    if action != "DELETE":
        assert preserved(before_originals, files(world.root, originals_only=True))
    if outcome in {"FINALIZED", "FINALIZED_ALREADY"}:
        assert world.library.get_session(SID).state is SessionState.FINALIZED
        if action == "FINALIZE":
            # Staging is salvaged before sealing; a skipped recovery loses these frames.
            assert world.result["frame_count"] == SEALED_FRAMES[state]
    if (state, action) == ("RECORDING_LIVE", "DELETE"):
        # Intent recorded first, nothing removed while the recorder is live.
        assert world.result["reason"] == "SESSION_LIVE"
        assert (world.root / "deletion-journal" / f"{SID}.json").is_file()
        assert files(world.root) == before_files
    if outcome == "NOT_FOUND_DELETE" and state == "DIRECTORY_ONLY":
        assert before_files and files(world.root) == before_files  # not deleted (out of scope)


# Section 4.3 inventory column. None: not listed.
INVENTORY = {
    "CREATED": ("CREATED", False),
    "RECORDING_STALE": ("RECORDING", False),
    "RECORDING_LIVE": ("RECORDING", True),
    "PAUSED_STALE": ("PAUSED", False),
    "PAUSED_INPROC": ("PAUSED", False),
    "FINALIZING": ("FINALIZING", False),
    "INTERRUPTED_STALE": ("INTERRUPTED", False),
    "INTERRUPTED_INPROC": ("INTERRUPTED", False),
    "FINALIZED": None,
    "DELETE_PENDING": None,
    "DIRECTORY_ONLY": ("DIRECTORY_ONLY", False),
    "NOT_FOUND": None,
}
INVENTORY_CASES = [pytest.param(state, id=f"G04-I-{state}") for state in STATES]


@pytest.mark.parametrize("state", INVENTORY_CASES)
def test_inventory_lists_unfinished_sessions_read_only(
    worlds: Callable[[str], World], state: str
) -> None:
    world = worlds(state)
    before = files(world.root), database(world.library), world.library.list_sessions()
    items = {item["session_id"]: item for item in world.library.unfinished_sessions()}
    expected = INVENTORY[state]
    if expected is None:
        assert SID not in items
    else:
        assert (items[SID]["state"], items[SID]["live"]) == expected
    after = files(world.root), database(world.library), world.library.list_sessions()
    assert after == before  # detection writes nothing, not even a row for a bare directory
    if state == "DIRECTORY_ONLY":
        assert items[SID]["state_version"] is None
        assert items[SID]["uncatalogued_bundles"] == 1
        assert database(world.library)[0] is None
    assert world.library.inventory_warnings() == {"skipped_entries": 0}


SEQUENCE_STARTS = {
    "CREATED": "CREATED",
    "RECORDING": "RECORDING_STALE",
    "PAUSED": "PAUSED_STALE",
    "FINALIZING": "FINALIZING",
    "INTERRUPTED": "INTERRUPTED_STALE",
}
WORDS = ["".join(word) for length in (1, 2, 3) for word in itertools.product("RFE", repeat=length)]
SEQUENCES = [
    pytest.param(start, word, id=f"G04-Q-{start}-{word}")
    for start in SEQUENCE_STARTS
    for word in WORDS
]


def predicted_state(start: str, word: str) -> str:
    """Closed predicate from section 4.6, independent of the implementation."""
    if "F" in word:
        return "FINALIZED"
    if "R" in word and start in {"RECORDING", "FINALIZING"}:
        return "INTERRUPTED"
    return start


@pytest.mark.parametrize(("start", "word"), SEQUENCES)
def test_bounded_command_sequences(
    worlds: Callable[[str], World], tmp_path: Path, start: str, word: str
) -> None:
    world = worlds(SEQUENCE_STARTS[start])
    library = world.library
    originals = files(world.root, originals_only=True)
    for index, command in enumerate(word):
        if command == "R":
            library.recover_session(SID)
        elif command == "F":
            library.finalize_unfinished(SID)
        else:
            output = tmp_path / f"export-{index}"
            if "F" in word[:index]:
                _export(library, SID, output)
                assert (output / "export.json").is_file()
            else:
                state_before = database(library)
                with pytest.raises(ValueError, match="Only finalized"):
                    _export(library, SID, output)
                assert database(library) == state_before and not output.exists()
        assert preserved(originals, files(world.root, originals_only=True))
    assert library.get_session(SID).state.value == predicted_state(start, word)


VALUES = [
    pytest.param("session_id", "s", "FINALIZED", id="G04-V-sid-valid"),
    pytest.param("session_id", "", "INVALID", id="G04-V-sid-empty"),
    pytest.param("session_id", "../x", "INVALID", id="G04-V-sid-traversal"),
    pytest.param("session_id", "a\x00b", "INVALID", id="G04-V-sid-nul"),
    pytest.param("session_id", "a" * 129, "INVALID", id="G04-V-sid-129"),
    pytest.param("session_id", 5, "INVALID", id="G04-V-sid-int"),
    pytest.param("expected_version", None, "FINALIZED", id="G04-V-ver-none"),
    pytest.param("expected_version", -1, "INVALID", id="G04-V-ver-negative"),
    pytest.param("expected_version", 2, "FINALIZED", id="G04-V-ver-current"),
    pytest.param("expected_version", 3, "STALE_SESSION_VERSION", id="G04-V-ver-plus1"),
    pytest.param("expected_version", 1, "STALE_SESSION_VERSION", id="G04-V-ver-minus1"),
    pytest.param("expected_version", True, "INVALID", id="G04-V-ver-bool"),
    pytest.param("expected_version", 1.0, "INVALID", id="G04-V-ver-float"),
]


@pytest.mark.parametrize(("argument", "value", "expected"), VALUES)
def test_finalize_argument_values(
    worlds: Callable[[str], World], argument: str, value: Any, expected: str
) -> None:
    world = worlds("INTERRUPTED_STALE")  # create 0 -> RECORDING 1 -> INTERRUPTED 2
    assert world.library.get_session(SID).state_version == 2
    before = files(world.root), database(world.library)
    call: dict[str, Any] = {"session_id": SID, "expected_version": None, argument: value}
    try:
        result = world.library.finalize_unfinished(
            call["session_id"], expected_version=call["expected_version"]
        )
        outcome = str(result["state"])
    except ValidationError:
        outcome = "INVALID"
    except StateConflict as error:
        outcome = str(error)
    assert outcome == expected
    if outcome != "FINALIZED":
        assert (files(world.root), database(world.library)) == before


WARNINGS = [
    pytest.param("INVALID_BUNDLE", MISSING, id="G04-R-code-invalid-bundle"),
    pytest.param("INVALID_STAGING", MISSING, id="G04-R-code-invalid-staging"),
    pytest.param("STAGING_TAIL_NOT_ADOPTED", MISSING, id="G04-R-code-tail"),
    pytest.param("MISSING_OR_INVALID_CATALOG_MEDIA:abc123", MISSING, id="G04-R-code-missing-media"),
    pytest.param("FINALIZED_ORPHAN", CANDIDATE, id="G04-R-code-finalized-orphan"),
    pytest.param("FINALIZED_STAGING", CANDIDATE, id="G04-R-code-finalized-staging"),
    pytest.param("MANIFEST_SYNC_PENDING", INFO, id="G04-R-code-manifest"),
    pytest.param("DELETION_INTENT", INFO, id="G04-R-code-deletion"),
    pytest.param("SOMETHING_NEW", UNKNOWN, id="G04-R-code-unknown"),
]


@pytest.mark.parametrize(("code", "category"), WARNINGS)
def test_warning_codes_have_a_closed_category(code: str, category: str) -> None:
    found, label = describe(code)
    assert found == category and label
    if ":" in code:
        assert code.split(":", 1)[1] in label
    if category == UNKNOWN:
        assert code in label  # an unknown code is shown, never hidden


HEALTH = [
    pytest.param(True, id="G04-R-health-recorded"),
    pytest.param(False, id="G04-R-health-unknown"),
]


@pytest.mark.parametrize("recorded", HEALTH)
def test_missing_health_record_is_unknown_not_zero(tmp_path: Path, recorded: bool) -> None:
    chunk = sealed(tmp_path / "library", SID, "e1", (0, 1))
    health = (
        {"epochs": [{"tracks": {"mic": {"epoch_id": "e1", "dropped_frames": 3}}}]}
        if recorded
        else {}
    )
    result = {
        "session_id": SID,
        "state": "INTERRUPTED",
        "previous_state": "RECORDING",
        "adopted": 0,
        "recovered": 1,
        "quarantined": 0,
        "warnings": [],
        "details": [],
        "verified_chunk_ids": [chunk.chunk_id],
    }
    view = recovery_view(result, [chunk], health)
    text = "\n".join(view.lines())
    assert view.preserved[0].frames == 8 and view.preserved[0].chunk_count == 1
    if recorded:
        assert view.preserved[0].dropped_frames == 3 and "큐 유실 3프레임" in text
    else:
        assert view.preserved[0].dropped_frames is None
        assert "유실 누계 알 수 없음" in text and "큐 유실 0" not in text
    assert "{" not in text and "중단·누락 구간은 복원되지 않습니다." in text


UNFINISHED_ACTIONS = ("복구 검토", "세션 확정", "세션 삭제")
NEXT = {
    "CREATED": (("CREATED", False), UNFINISHED_ACTIONS),
    "RECORDING_STALE": (("RECORDING", False), UNFINISHED_ACTIONS),
    "RECORDING_LIVE": (("RECORDING", True), ("정지 후 가능",)),
    "PAUSED_STALE": (("PAUSED", False), UNFINISHED_ACTIONS),
    "PAUSED_INPROC": (("PAUSED", False), UNFINISHED_ACTIONS),
    "FINALIZING": (("FINALIZING", False), UNFINISHED_ACTIONS),
    "INTERRUPTED_STALE": (("INTERRUPTED", False), UNFINISHED_ACTIONS),
    "INTERRUPTED_INPROC": (("INTERRUPTED", False), UNFINISHED_ACTIONS),
    "FINALIZED": (("FINALIZED", False), ("내보내기", "전사 요청", "세션 삭제")),
    "DELETE_PENDING": (("DELETE_PENDING", False), ("삭제 대기 재시도",)),
    "DIRECTORY_ONLY": (("DIRECTORY_ONLY", False), ("복구 검토", "세션 확정")),
    "NOT_FOUND": (("NOT_FOUND", False), ()),
}
NEXT_CASES = [pytest.param(state, id=f"G04-R-next-{state}") for state in STATES]


@pytest.mark.parametrize("state", NEXT_CASES)
def test_next_actions_table(state: str) -> None:
    (value, live), expected = NEXT[state]
    assert next_actions(value, live=live) == expected


def test_declared_unit_denominators_are_complete_and_unique() -> None:
    groups = {
        "T": TABLE,
        "I": INVENTORY_CASES,
        "Q": SEQUENCES,
        "V": VALUES,
        "R": WARNINGS + HEALTH + NEXT_CASES,
    }
    sizes = {name: len(cases) for name, cases in groups.items()}
    assert sizes == {"T": 12 * 6, "I": 12, "Q": 5 * (3 + 9 + 27), "V": 6 + 7, "R": 9 + 2 + 12}
    ids = [case.id for cases in groups.values() for case in cases]
    assert len(ids) == len(set(ids)) == 315
    assert all(case_id.startswith("G04-") for case_id in ids)


@pytest.mark.parametrize(
    "case", ("same", "collected", "unhashable"), ids=[f"G04-FIX-WEAK-{i}" for i in range(3)]
)
def test_owner_registry_observes_weak_identity_and_current_liveness(
    tmp_path: Path, case: str
) -> None:
    class Owner:
        def __init__(self) -> None:
            self.live = False
            self.calls = 0

        def is_live(self) -> bool:
            self.calls += 1
            return self.live

    class UnhashableOwner(Owner):
        __hash__ = None  # type: ignore[assignment]

    with Library(tmp_path / "library") as library:
        library.create_session(SID)
        owner = UnhashableOwner() if case == "unhashable" else Owner()
        library.register_live_owner(SID, owner)
        if case == "same":
            library.register_live_owner(SID, owner)
            library.register_live_owner(SID, owner)
            assert not library._is_live(SID)
            assert owner.calls == 1
        if case == "collected":
            owner.live = True
            reference = weakref.ref(owner)
            del owner
            gc.collect()
            assert reference() is None
            assert library.finalize_unfinished(SID)["state"] == "FINALIZED"
        else:
            owner.live = True
            with pytest.raises(StateConflict, match="SESSION_LIVE"):
                library.finalize_unfinished(SID)
            owner.live = False
            assert library.finalize_unfinished(SID)["state"] == "FINALIZED"


@pytest.mark.skipif(sys.platform != "win32", reason="actual NTFS junction requires Windows")
@pytest.mark.parametrize(
    "part", ("staging", "tracks", "track", "epoch"), ids=[f"G04-FIX-PATH-{i}" for i in range(4)]
)
def test_inventory_checks_each_nested_directory_before_following_junction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, part: str
) -> None:
    import _winapi

    outside = tmp_path / "outside"
    (outside / "private-track" / "private-epoch" / "private-bundle").mkdir(parents=True)
    with Library(tmp_path / "library") as library:
        library.create_session(SID)
        relative = {
            "staging": "staging",
            "tracks": "tracks",
            "track": "tracks/mic",
            "epoch": "tracks/mic/epoch",
        }[part]
        link = library.root / "sessions" / SID / relative
        link.parent.mkdir(parents=True, exist_ok=True)
        _winapi.CreateJunction(str(outside), str(link))
        traversed: list[Path] = []
        original = Path.iterdir

        def observe(path: Path) -> Iterator[Path]:
            if path == link or link in path.parents or path == outside or outside in path.parents:
                traversed.append(path)
            return original(path)

        try:
            assert getattr(link.lstat(), "st_file_attributes", 0) & 0x400
            with monkeypatch.context() as patch:
                patch.setattr(Path, "iterdir", observe)
                try:
                    library.unfinished_sessions()
                except (OSError, ValueError):
                    pass  # an explicit safe failure is allowed
            assert traversed == []
        finally:
            # Remove only the checked junction itself, never recurse into its target.
            assert link.parent.is_relative_to(library.root)
            assert getattr(link.lstat(), "st_file_attributes", 0) & 0x400
            link.rmdir()
            assert (outside / "private-track/private-epoch/private-bundle").is_dir()


MEDIA_CASES = list(itertools.product(("valid", "missing", "corrupt"), (False, True))) + [
    ("legacy", False),
    ("mismatch", False),
]


@pytest.mark.parametrize("state,mixed", MEDIA_CASES, ids=[f"G04-FIX-MEDIA-{i}" for i in range(8)])
def test_recovery_view_separates_catalog_expectation_from_verified_preservation(
    tmp_path: Path, state: str, mixed: bool
) -> None:
    with Library(tmp_path / "library") as library:
        library.create_session(SID)
        descriptor = sealed(library.root, SID, "e1", (0, 1))
        library.register_chunk(descriptor)
        if mixed:
            library.register_chunk(sealed(library.root, SID, "e2", (0,)))
        audio = library.root / descriptor.relative_path / "audio.pcm"
        if state == "missing":
            audio.unlink()
        elif state == "corrupt":
            audio.write_bytes(b"invalid")
        elif state == "mismatch":
            value = descriptor.to_dict()
            value["sha256"] = "0" * 64
            library._db.execute(
                "UPDATE chunks SET descriptor=? WHERE chunk_id=?",
                (json.dumps(value), descriptor.chunk_id),
            )
            library._db.commit()
        before = files(library.root, originals_only=True)
        result = library.recover_session(SID)
        if state == "legacy":
            result.pop("verified_chunk_ids", None)
        view = recovery_view(result, library.chunks(SID), {})
        expected_verified = (8 if state == "valid" else 0) + (4 if mixed else 0)
        assert sum(item.frames for item in view.catalog) == 8 + (4 if mixed else 0)
        assert sum(item.frames for item in view.preserved) == expected_verified
        assert sum(item.chunk_count for item in view.preserved) == int(state == "valid") + int(
            mixed
        )
        if state in ("missing", "corrupt", "mismatch"):
            assert descriptor.chunk_id not in result["verified_chunk_ids"]
            assert any(
                code.startswith("MISSING_OR_INVALID_CATALOG_MEDIA") for code in result["warnings"]
            )
        if state == "legacy":
            assert any("보존량을 확인하지 못했습니다" in note for note in view.notes)
        assert "원본은 보존" not in "\n".join(view.lines())
        assert files(library.root, originals_only=True) == before


@pytest.mark.skipif(sys.platform != "win32", reason="actual NTFS junction/hard link")
@pytest.mark.parametrize(
    "kind", ("junction", "hardlink"), ids=[f"G04-FIX2-PAIR-{i}" for i in range(2)]
)
def test_unsafe_session_does_not_hide_or_block_a_safe_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    import _winapi

    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "private"
    target.write_bytes(b"private canary")
    with Library(tmp_path / "library") as library:
        for sid in ("bad", "good"):
            library.create_session(sid)
            library.transition(sid, SessionState.RECORDING, 0)
            library.register_chunk(sealed(library.root, sid, "e1", (0,)))
            library.transition(sid, SessionState.INTERRUPTED, 1)
        base = library.root / "sessions/bad"
        if kind == "junction":
            link = base / "staging"
            link.rmdir()  # empty staging directory left after seal
            _winapi.CreateJunction(str(outside), str(link))
        else:
            link = base / "tracks/linked-file"
            link.hardlink_to(target)
        original = Path.iterdir
        followed: list[Path] = []

        def observe(path: Path) -> Iterator[Path]:
            if path == link or link in path.parents or path == outside or outside in path.parents:
                followed.append(path)
            return original(path)

        before = library.get_session("bad")
        try:
            with monkeypatch.context() as patch:
                patch.setattr(Path, "iterdir", observe)
                items = {item["session_id"]: item for item in library.unfinished_sessions()}
                assert set(items) == {"bad", "good"}
                assert items["bad"]["inspection_error"] == "INSPECTION_UNSAFE"
                assert items["bad"]["staging_entries"] is None
                assert items["good"]["inspection_error"] is None
                for operation in (library.recover_session, library.finalize_unfinished):
                    with pytest.raises(StateConflict, match="INSPECTION_UNSAFE"):
                        operation("bad")
                result = library.finalize_unfinished("good")
                assert result["state"] == "FINALIZED" and result["frame_count"] == 4
            assert followed == []
            assert library.get_session("bad") == before
            assert target.read_bytes() == b"private canary"
        finally:
            assert link.parent.is_relative_to(library.root)
            if kind == "junction":
                assert getattr(link.lstat(), "st_file_attributes", 0) & 0x400
                link.rmdir()
            else:
                assert link.lstat().st_nlink == 2
                link.unlink()
            assert target.read_bytes() == b"private canary"


def test_inventory_io_failure_is_local_to_its_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with Library(tmp_path / "library") as library:
        for sid in ("bad", "good"):
            library.create_session(sid)
            (library.root / f"sessions/{sid}/staging").mkdir(parents=True)
        original = Path.iterdir

        def unavailable(path: Path) -> Iterator[Path]:
            if path == library.root / "sessions/bad/staging":
                raise PermissionError("synthetic access failure")
            return original(path)

        with monkeypatch.context() as patch:
            patch.setattr(Path, "iterdir", unavailable)
            items = {item["session_id"]: item for item in library.unfinished_sessions()}
            assert items["bad"]["inspection_error"] == "INSPECTION_UNAVAILABLE"
            assert items["good"]["inspection_error"] is None
            with pytest.raises(StateConflict, match="INSPECTION_UNAVAILABLE"):
                library.recover_session("bad")
            assert library.finalize_unfinished("good")["state"] == "FINALIZED"


class ClaimRecorder(dict[str, int]):
    """Observe publications independently of the later writer's success/failure."""

    def __init__(self) -> None:
        super().__init__()
        self.publications: list[str] = []

    def __setitem__(self, key: str, value: int) -> None:
        self.publications.append(key)
        super().__setitem__(key, value)


@pytest.mark.parametrize(
    "condition,operation",
    [
        ("live", "recover"),
        ("live", "finalize"),
        ("deleted", "recover"),
        ("deleted", "finalize"),
        ("stale", "finalize"),
        ("missing", "finalize"),
    ],
    ids=[f"G04-F4-ADMIT-{i}" for i in range(6)],
)
def test_refused_admission_never_publishes_claim(
    tmp_path: Path, condition: str, operation: str
) -> None:
    class Owner:
        def is_live(self) -> bool:
            return True

    with Library(tmp_path / "library") as library:
        if condition != "missing":
            library.create_session("s")
        owner = Owner()
        if condition == "live":
            library.register_live_owner("s", owner)
        elif condition == "deleted":
            library.delete_session("s")
        claims = ClaimRecorder()
        library._claims = claims
        if condition == "deleted" and operation == "recover":
            assert library.recover_session("s")["state"] == "DELETE_PENDING"
        else:
            expected = {
                "live": "SESSION_LIVE",
                "deleted": "DELETE_PENDING",
                "stale": "STALE_SESSION_VERSION",
            }.get(condition)
            if expected is None:
                with pytest.raises(KeyError):
                    library.finalize_unfinished("s")
            else:
                with pytest.raises(StateConflict, match=expected):
                    if operation == "recover":
                        library.recover_session("s")
                    else:
                        library.finalize_unfinished(
                            "s", expected_version=1 if condition == "stale" else None
                        )
        assert claims.publications == [] and not library._claims
