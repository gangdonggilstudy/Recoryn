"""G13 unit rows: A (source 8 x role 2 x confirmation 4 x license 3 = 192), B (Whisper
load set 2 x 2 x 6 x time 3 = 72), K (confirmation key 2^8 x role 2 = 512) and the named
negatives T01-T09, T11-T28 (T10 lives with the model panel in the UI file).

Expected digests are written out by hand: the domain tag followed by the exact canonical
JSON bytes. Native/refusal outcomes come from hand-written tables of
docs/testing/g13-manual-model-cases.md sections 3, 4, 6 and 7. Synthetic bytes only: no
model weights, network, GPU, model download or user folder is ever used.
"""

from __future__ import annotations

import errno
import hashlib
import itertools
import json
import os
import threading
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from recoryn.diarization import DiarizationConfig, LocalDiarizationProcess
from recoryn.diarization.models import verified_bundle
from recoryn.domain import ValidationError
from recoryn.models import ModelManager
from recoryn.models import artifacts as art
from recoryn.models._artifact_io import (
    ArtifactIo,
    diarization_snapshot,
    freeze,
    hash_file,
    managed_snapshot,
    recheck_whisper,
    whisper_files,
    whisper_snapshot,
)
from recoryn.models.manager import FileSpec, ModelSpec, spec_digest
from recoryn.providers import ProviderError, STTRequest
from recoryn.transcription import FasterWhisperProvider

pytestmark = pytest.mark.unit

WHISPER_LOADER = "faster-whisper-1.2.1-files-v1"
DIARIZATION_LOADER = "sherpa-onnx-2.0.1-pyannote-v1"
FILES = {
    "config.json": b'{"synthetic":1}',
    "model.bin": b"synthetic model bytes, not weights",
    "tokenizer.json": b'{"tokens":[]}',
}
PREPROCESSOR, VOCABULARY = b'{"feature_size":80}', b'["a","b"]'
LICENSE = b"Synthetic license text"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def by_hand(loader: str, kind: str, rows: list[tuple[str, int, str, str]]) -> str:
    """The canonical description written out by hand (never the product helper)."""
    body = ",".join(f'["{n}",{s},"{h}","{st}"]' for n, s, h, st in sorted(rows))
    text = '{"files":[' + body + f'],"kind":"{kind}","loader":"{loader}","version":1}}'
    return sha(b"recoryn.model-artifact.v1\x00" + text.encode("ascii"))


def whisper_rows(
    files: dict[str, bytes], preproc: bytes | None, vocab: bytes | None, text: bytes | None = None
) -> list:
    """Hand rows: the absent vocabulary.txt is recorded as absent too (G13R-01)."""
    rows = [(name, len(data), sha(data), "PRESENT") for name, data in files.items()]
    rows.append(
        ("vocabulary.txt", len(text), sha(text), "PRESENT")
        if text is not None
        else ("vocabulary.txt", 0, "", "ABSENT")
    )
    rows.append(
        ("preprocessor_config.json", len(preproc), sha(preproc), "PRESENT")
        if preproc is not None
        else ("preprocessor_config.json", 0, "", "ABSENT_DEFAULT")
    )
    rows.append(
        ("vocabulary.json", len(vocab), sha(vocab), "PRESENT")
        if vocab is not None
        else ("vocabulary.json", 0, "", "ABSENT")
    )
    return rows


def write(folder: Path, files: dict[str, bytes]) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (folder / name).write_bytes(data)
    return folder


def confirm(registry: art.ConfirmationRegistry, snapshot: Any, *, ack: bool = True) -> Any:
    return registry.confirm(snapshot, shown=registry.key(snapshot), accepted=True, acknowledged=ack)


class Factory:
    """A fake loader recording exactly the mapping it received (bytes read back)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, bytes], dict[str, Any]]] = []

    def __call__(self, identifier: str, **options: Any) -> Any:
        files = options.pop("files")
        read = {
            name: value if isinstance(value, bytes) else value.read()
            for name, value in files.items()
        }
        self.calls.append((identifier, read, options))
        return type("Model", (), {"model": None})()


def whisper_native(evidence: Any, tmp: Path) -> Factory | None:
    """Run the product path up to the loader: re-check, seal, child-side read, factory."""
    factory = Factory()
    try:
        bundle = freeze(evidence, parent=tmp)
    except ProviderError:
        return None
    try:
        provider = FasterWhisperProvider(
            Path(evidence.snapshot.root), model_factory=factory, bundle=bundle.description()
        )
        provider.load()
        provider.close()
    finally:
        bundle.close()
    return factory


def manifest(
    folder: Path, *, license_text: bool = True, tamper: bool = False, variant: bytes = b""
) -> DiarizationConfig:
    folder.mkdir(parents=True, exist_ok=True)
    models = {}
    for role in ("segmentation", "embedding"):
        data = b"synthetic-not-onnx-" + role.encode() + variant
        (folder / f"{role}.onnx").write_bytes(data)
        if license_text:
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
    if tamper:
        (folder / "segmentation.onnx").write_bytes(b"synthetic-not-onnx-tampered")
    return DiarizationConfig(path, sha(path.read_bytes()), True)


def diarization_of(config: DiarizationConfig, io: ArtifactIo | None = None) -> Any:
    files, terms = verified_bundle(config)
    return diarization_snapshot(
        files,
        config.manifest_path.parent,
        license_id=terms["license_id"],
        license_url=terms["license_url"],
        reference=config.manifest_sha256,
        io=io,
    )


def diarization_native(evidence: Any, config: DiarizationConfig) -> bool:
    """The parent gate right before spawn: strict re-verify, compare, seal."""
    provider = LocalDiarizationProcess(config, model_evidence=evidence)

    class Execution:
        cancel = None

    try:
        bundle = provider._seal(Execution())  # type: ignore[arg-type]
    except ProviderError:
        return False
    from recoryn.models._artifact_io import release

    release(bundle)
    return True


class LinkIo(ArtifactIo):
    """The OS answers that a component is a link (the protection itself is real)."""

    def check(self, path: Path) -> None:
        raise ValidationError("Links and reparse points are not supported")


class NetworkIo(ArtifactIo):
    def drive_type(self, anchor: str) -> int:
        return 4  # DRIVE_REMOTE: a mapped network drive


def managed_install(root: Path, model_id: str, files: dict[str, bytes]) -> tuple[Any, ModelSpec]:
    specs = tuple(
        FileSpec(name, f"https://publisher.invalid/{name}", len(data), sha(data))
        for name, data in files.items()
    )
    spec = ModelSpec(model_id, "whisper", "test-only", "https://publisher.invalid/license", specs)
    data = {f"https://publisher.invalid/{name}": value for name, value in files.items()}
    manager = ModelManager(root, downloader=lambda url, offset: iter([data[url][offset:]]))
    manager.install(spec, approved=True)
    return manager, spec


@pytest.fixture(autouse=True)
def _idle_copies_released() -> Any:
    """Sealed copies kept for reuse never outlive one row (G13R-03 a)."""
    yield
    from recoryn.models._artifact_io import release_idle

    release_idle()


# --- A: source 8 x role 2 x confirmation 4 x license 3 = 192 -------------------------

SOURCES = (
    "managed_ok",
    "manual",
    "managed_tampered",
    "partial",
    "symlink",
    "parent_reparse",
    "unc",
    "network",
)
CONFIRMS = ("none", "current", "old_digest", "old_generation")
LICENSES = ("explicit", "refused", "not_provided")
A_ROWS = list(itertools.product(SOURCES, (art.WHISPER, art.DIARIZATION), CONFIRMS, LICENSES))
A_CASES = [pytest.param(*row, id=f"G13-A-{i:03d}") for i, row in enumerate(A_ROWS, 1)]


def a_expected(source: str, role: str, confirmation: str, license_axis: str) -> bool:
    """Hand table (G13 §3.1, §7.1 A): native only for a valid source, a current
    confirmation and an acceptable license state; refused/declined license never runs."""
    if source not in ("managed_ok", "manual") or confirmation != "current":
        return False
    if license_axis == "refused":
        return False
    if license_axis == "not_provided":
        return role == art.WHISPER and source == "manual"  # the manual Whisper exception
    return True


def a_source(tmp: Path, source: str, role: str, license_axis: str, *, old: bool = False) -> Any:
    """(snapshot or raised code, config) for one A source; ``old`` uses other bytes."""
    model = b"old synthetic bytes" if old else FILES["model.bin"]
    files = dict(FILES, **{"model.bin": model})
    if license_axis == "explicit":
        files["LICENSE"] = LICENSE
    if role == art.DIARIZATION:
        folder = tmp / ("models" if source == "managed_ok" else "user") / "diarization"
        config = manifest(
            folder,
            license_text=license_axis != "not_provided",
            tamper=source == "managed_tampered",
            variant=b"-old" if old else b"",  # an earlier, also valid pinned manifest
        )
        io: ArtifactIo | None = None
        if source == "symlink":
            io = LinkIo()
        elif source == "network":
            io = NetworkIo()
        if source == "partial":
            (folder / "LICENSE.embedding.txt").unlink(missing_ok=True)
        if source == "parent_reparse":
            import _winapi

            target = tmp / "elsewhere"
            os.replace(folder, target)
            _winapi.CreateJunction(str(target), str(folder))
        if source == "unc":
            config = DiarizationConfig(
                Path(r"\\g13-server\share\manifest.json"), config.manifest_sha256, True
            )
        return (lambda: diarization_of(config, io)), config
    if source in ("managed_ok", "managed_tampered") or (
        license_axis == "not_provided" and source == "managed_ok"
    ):
        manager, spec = managed_install(tmp / "models", "whisper-a", files)
        if source == "managed_tampered":
            (manager.root / "whisper-a" / "model.bin").write_bytes(b"tampered same length!!!!!")
        if license_axis == "not_provided":
            installed = manager.root / "whisper-a" / "installed.json"
            value = json.loads(installed.read_bytes())
            value["spec"].pop("license_id")  # managed license metadata missing
            installed.write_text(json.dumps(value), encoding="utf-8")
        return (lambda: managed_snapshot(manager, "whisper-a", spec_digest(spec))), None
    folder = write(tmp / "user" / "whisper", files)
    if source == "partial":
        (folder / "tokenizer.json").unlink()
    if source == "parent_reparse":
        import _winapi

        target = tmp / "elsewhere"
        os.replace(folder, target)
        _winapi.CreateJunction(str(target), str(folder))
    if source == "unc":
        return (lambda: whisper_snapshot(Path(r"\\g13-server\share\whisper"))), None
    io = LinkIo() if source == "symlink" else NetworkIo() if source == "network" else None
    return (lambda: whisper_snapshot(folder, io=io)), None


@pytest.mark.parametrize(("source", "role", "confirmation", "license_axis"), A_CASES)
def test_only_a_current_confirmation_of_a_valid_source_reaches_native(
    tmp_path: Path, source: str, role: str, confirmation: str, license_axis: str
) -> None:
    registry = art.ConfirmationRegistry()
    evidence = None
    if confirmation == "old_digest" and source in ("managed_ok", "manual"):
        old, _ = a_source(tmp_path / "now", source, role, license_axis, old=True)
        try:
            confirm(registry, old(), ack=True)  # a confirmation of the earlier bytes
        except ProviderError:
            pass  # e.g. no license text: the strict check refuses even the old version
        installed = tmp_path / "now" / "models" / "whisper-a"
        if installed.exists():
            ModelManager(installed.parent).delete("whisper-a")  # reinstall the current bytes
    make, config = a_source(tmp_path / "now", source, role, license_axis)
    try:
        snapshot = make()
    except ProviderError:
        snapshot = None
    if snapshot is not None:
        if confirmation in ("current", "old_generation"):
            confirm(registry, snapshot, ack=license_axis != "refused")
        if confirmation == "old_generation":
            registry.new_generation()  # a new run / restore: nothing carries over
        evidence = registry.evidence(snapshot)
        # A damaged managed install is never promoted (no automatic manual success).
        if source == "managed_tampered":
            assert registry.display(snapshot) == art.CHANGED_INVALID
    ran = False
    if evidence is not None:
        if role == art.WHISPER:
            ran = whisper_native(evidence, tmp_path) is not None
        else:
            ran = diarization_native(evidence, config)
    assert ran is a_expected(source, role, confirmation, license_axis)
    assert snapshot is None or snapshot.source_authenticity == "UNVERIFIED"


# --- B: preprocessor 2 x vocabulary 2 x file set 6 x time 3 = 72 --------------------

SETS = ("normal", "missing", "zero", "boundary", "new_metadata", "readme")
TIMES = ("select", "pre_native", "running")
B_ROWS = list(itertools.product((True, False), (True, False), SETS, TIMES))
B_CASES = [pytest.param(*row, id=f"G13-B-{i:02d}") for i, row in enumerate(B_ROWS, 1)]
BOUNDARY = {"config.json": b'{"synthetic":1}{"tok', "tokenizer.json": b'ens":[]}'}


def apply_set(folder: Path, name: str) -> None:
    if name == "missing":
        (folder / "tokenizer.json").unlink()
    elif name == "zero":
        (folder / "config.json").write_bytes(b"")
    elif name == "boundary":  # the same concatenated bytes, another file boundary
        for file, data in BOUNDARY.items():
            (folder / file).write_bytes(data)
    elif name == "new_metadata":  # a load input this loader contract does not support
        (folder / "shared_vocabulary.json").write_bytes(b'["a"]')
    elif name == "readme":
        (folder / "README.md").write_bytes(b"not a loader input")


@pytest.mark.parametrize(("preproc", "vocab", "file_set", "time"), B_CASES)
def test_the_load_set_and_its_digest_are_exactly_the_loader_inputs(
    tmp_path: Path, preproc: bool, vocab: bool, file_set: str, time: str
) -> None:
    files = dict(FILES)
    if preproc:
        files["preprocessor_config.json"] = PREPROCESSOR
    if vocab:
        files["vocabulary.json"] = VOCABULARY
    folder = write(tmp_path / "model", files)
    base = dict(FILES)
    normal = by_hand(
        WHISPER_LOADER,
        "whisper",
        whisper_rows(base, PREPROCESSOR if preproc else None, VOCABULARY if vocab else None),
    )
    expected_map = dict(FILES)
    expected_map["preprocessor_config.json"] = PREPROCESSOR if preproc else b"{}"
    if vocab:
        expected_map["vocabulary.json"] = VOCABULARY
    if time == "select":
        apply_set(folder, file_set)
        refused = {"missing": "MODEL_MISSING", "zero": "MODEL_MISSING"}
        refused["new_metadata"] = "CAPABILITY_UNSUPPORTED"
        if file_set in refused:
            with pytest.raises(ProviderError, match=refused[file_set]):
                whisper_snapshot(folder)
            return
        snapshot = whisper_snapshot(folder)
        if file_set == "boundary":
            changed = dict(base, **BOUNDARY)
            legacy = ("model.bin", "config.json", "tokenizer.json")  # the old concatenation
            assert b"".join(changed[n] for n in legacy) == b"".join(base[n] for n in legacy)
            assert snapshot.artifact_digest == by_hand(
                WHISPER_LOADER,
                "whisper",
                whisper_rows(
                    changed, PREPROCESSOR if preproc else None, VOCABULARY if vocab else None
                ),
            )
            assert snapshot.artifact_digest != normal  # a moved boundary is another identity
        else:
            assert snapshot.artifact_digest == normal  # README is never a loader input
        return
    registry = art.ConfirmationRegistry()
    evidence = confirm(registry, whisper_snapshot(folder))
    assert evidence is not None and evidence.snapshot.artifact_digest == normal
    factory = Factory()
    if time == "pre_native":
        apply_set(folder, file_set)
        if file_set not in ("normal", "readme"):
            with pytest.raises(ProviderError):
                freeze(evidence, parent=tmp_path)  # the pre-native re-check refuses
            assert list(p for p in tmp_path.iterdir() if p.name.startswith("recoryn-model")) == []
            return
        bundle = freeze(evidence, parent=tmp_path)
    else:
        bundle = freeze(evidence, parent=tmp_path)
        apply_set(folder, file_set)  # after the seal: the current run keeps its copy
    try:
        provider = FasterWhisperProvider(folder, model_factory=factory, bundle=bundle.description())
        provider.load()
        provider.close()
    finally:
        bundle.close()
    identifier, received, options = factory.calls[0]
    assert identifier == "recoryn-bundle-" + normal[:16] and options["local_files_only"] is True
    assert received == expected_map  # exactly the confirmed bytes, nothing else


# --- K: the eight key fields, each match/mismatch (2^8) x role 2 = 512 ----------------

FIELDS = (
    "library_instance",
    "execution_generation",
    "root_identity",
    "kind",
    "loader_contract",
    "artifact_digest",
    "terms_digest",
    "source_kind",
)
K_ROWS = list(itertools.product(range(256), (art.WHISPER, art.DIARIZATION)))
K_CASES = [pytest.param(*row, id=f"G13-K-{i:03d}") for i, row in enumerate(K_ROWS, 1)]


@pytest.fixture(scope="module")
def k_world(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    tmp = tmp_path_factory.mktemp("g13-k")
    whisper = whisper_snapshot(write(tmp / "whisper", FILES))
    diarization = diarization_of(manifest(tmp / "diarization"))
    return {art.WHISPER: whisper, art.DIARIZATION: diarization}


def other(field: str, value: Any) -> Any:
    """A different value for one key field (hand-written alternatives)."""
    return {
        "library_instance": "another-library",
        "execution_generation": "another-run",
        "root_identity": (value[0], value[1] + 1, value[2] + "-sibling")
        if isinstance(value, tuple)
        else value,
        "kind": art.DIARIZATION if value == art.WHISPER else art.WHISPER,
        "loader_contract": "another-loader-v9",
        "artifact_digest": "0" * 64,
        "terms_digest": "1" * 64,
        "source_kind": art.MANAGED if value == art.MANUAL else art.MANUAL,
    }[field]


@pytest.mark.parametrize(("mask", "role"), K_CASES)
def test_any_differing_key_field_is_another_confirmation(
    k_world: dict[str, Any], mask: int, role: str
) -> None:
    snapshot = k_world[role]
    registry = art.ConfirmationRegistry("library-under-test")
    base = registry.key(snapshot)
    changed = {
        field: other(field, getattr(base, field))
        for bit, field in enumerate(FIELDS)
        if mask >> bit & 1
    }
    presented = replace(base, **changed)
    # 1. A record is issued only for exactly the shown key (record 0/1 issuance).
    issued = registry.confirm(snapshot, shown=presented, accepted=True, acknowledged=True)
    assert (issued is not None) is (mask == 0)
    assert (registry.evidence(snapshot) is not None) is (mask == 0)
    # 2. A recorded confirmation never vouches for a key that differs in any field.
    fresh = art.ConfirmationRegistry("library-under-test")
    real = confirm(fresh, snapshot)
    forged = art.ModelUseEvidence(real.record_id, replace(real.key, **changed), snapshot, fresh)
    assert fresh.valid(forged) is (mask == 0)


# --- T: named negatives ---------------------------------------------------------------


def case(cid: str) -> Any:
    """One named row, one collected node carrying its case ID."""
    return pytest.mark.parametrize("case_id", [cid], ids=[cid])


@case("G13-T-01")
def test_t01_digest_must_be_text(case_id: str) -> None:
    for value in (True, 123, None):
        with pytest.raises(ValidationError):
            art.FileEntry("model.bin", 1, value)  # type: ignore[arg-type]


@case("G13-T-02")
def test_t02_digest_length_and_case(case_id: str) -> None:
    for value in ("a" * 63, "A" * 64):
        with pytest.raises(ValidationError):
            art.FileEntry("model.bin", 1, value)


@case("G13-T-03")
def test_t03_size_type_and_sign(case_id: str) -> None:
    for value in (True, -1):
        with pytest.raises(ValidationError):
            art.FileEntry("model.bin", value, "a" * 64)  # type: ignore[arg-type]


@case("G13-T-04")
def test_t04_case_collision(case_id: str, tmp_path: Path) -> None:
    """G13-T-04"""

    class Listing(ArtifactIo):
        def listdir(self, path: Path) -> list[str]:
            return [*FILES, "Tokenizer.json"]

    folder = write(tmp_path / "model", FILES)
    with pytest.raises(ProviderError, match="CAPABILITY_UNSUPPORTED"):
        whisper_snapshot(folder, io=Listing())
    entries = (art.FileEntry("a.json", 1, "a" * 64), art.FileEntry("A.json", 1, "b" * 64))
    with pytest.raises(ValidationError, match="MODEL_NAME_COLLISION"):
        art.artifact_digest(art.WHISPER, WHISPER_LOADER, entries)


@case("G13-T-05")
def test_t05_boundary_only_change(case_id: str, tmp_path: Path) -> None:
    """G13-T-05: equal concatenations, different file boundaries, different identities."""
    first = whisper_snapshot(write(tmp_path / "a", FILES))
    second = whisper_snapshot(write(tmp_path / "b", dict(FILES, **BOUNDARY)))
    assert first.artifact_digest != second.artifact_digest
    assert first.artifact_digest == by_hand(
        WHISPER_LOADER, "whisper", whisper_rows(FILES, None, None)
    )


@case("G13-T-06")
def test_t06_preprocessor_appears(case_id: str, tmp_path: Path) -> None:
    """G13-T-06: an appearing optional input is a new identity and is supplied as is."""
    folder = write(tmp_path / "model", FILES)
    before = whisper_snapshot(folder)
    (folder / "preprocessor_config.json").write_bytes(PREPROCESSOR)
    after = whisper_snapshot(folder)
    assert before.artifact_digest != after.artifact_digest
    factory = whisper_native(confirm(art.ConfirmationRegistry(), after), tmp_path)
    assert factory is not None and factory.calls[0][1]["preprocessor_config.json"] == PREPROCESSOR


@case("G13-T-07")
def test_t07_missing_tokenizer_never_falls_back(case_id: str, tmp_path: Path) -> None:
    """G13-T-07: no tokenizer bytes, no loader (the SDK would look on disk or the Hub)."""
    folder = write(tmp_path / "model", FILES)
    evidence = confirm(art.ConfirmationRegistry(), whisper_snapshot(folder))
    bundle = freeze(evidence, parent=tmp_path)
    try:
        forged = bundle.description()
        forged["entries"] = [row for row in forged["entries"] if row[0] != "tokenizer.json"]
        factory = Factory()
        provider = FasterWhisperProvider(folder, model_factory=factory, bundle=forged)
        with pytest.raises(ProviderError, match="MODEL_MISSING"):
            provider.load()
        with pytest.raises(ProviderError):
            whisper_files(forged)
        assert factory.calls == []
    finally:
        bundle.close()


def _local_only(path: Path) -> None:
    """A watched call must never receive a UNC/device path (no OS or network access)."""
    text = str(path)
    assert not text.startswith(("\\\\", "//")), "a non-local path reached the filesystem"


class Watch(ArtifactIo):
    def __init__(self, drive: int = 3) -> None:
        self.drive, self.calls = drive, []

    def drive_type(self, anchor: str) -> int:
        self.calls.append("drive")
        return self.drive

    def stat(self, path: Path) -> os.stat_result:
        self.calls.append("stat")
        _local_only(path)
        return super().stat(path)

    def realpath(self, path: Path) -> str:
        self.calls.append("realpath")
        _local_only(path)
        return super().realpath(path)

    def check(self, path: Path) -> None:
        self.calls.append("check")
        _local_only(path)
        super().check(path)


@case("G13-T-08")
def test_t08_unknown_drive_type(case_id: str, tmp_path: Path) -> None:
    """G13-T-08: an unknown drive is refused before any filesystem access."""
    watch = Watch(drive=0)
    with pytest.raises(ProviderError, match="CAPABILITY_UNSUPPORTED"):
        whisper_snapshot(write(tmp_path / "model", FILES), io=watch)
    assert watch.calls == ["drive"]


@case("G13-T-09")
def test_t09_non_local_path_is_never_resolved(case_id: str) -> None:
    """G13-T-09: UNC/device/extended paths: no drive query, stat, check or realpath."""
    for text in (r"\\server\share\m", r"\\?\C:\m", r"\\.\C:\m", "//server/share/m"):
        watch = Watch()
        with pytest.raises(ProviderError, match="CAPABILITY_UNSUPPORTED"):
            whisper_snapshot(Path(text), io=watch)
        assert watch.calls == []


@case("G13-T-11")
def test_t11_consistent_installed_change_still_mismatches_the_pin(
    case_id: str, tmp_path: Path
) -> None:
    """G13-T-11: installed.json and weights changed together; the external pin decides."""
    manager, spec = managed_install(tmp_path / "models", "whisper-t11", FILES)
    pin = spec_digest(spec)
    folder = manager.root / "whisper-t11"
    (folder / "model.bin").write_bytes(b"replaced weights")
    value = json.loads((folder / "installed.json").read_bytes())
    for item in value["spec"]["files"]:
        if item["path"] == "model.bin":
            item["size"], item["sha256"] = len(b"replaced weights"), sha(b"replaced weights")
    (folder / "installed.json").write_text(json.dumps(value), encoding="utf-8")
    assert manager.verify("whisper-t11") == folder  # self-consistent listing check
    snapshot = managed_snapshot(manager, "whisper-t11", pin)
    assert snapshot.integrity == art.INVALID and not art.eligible(snapshot)


@case("G13-T-12")
def test_t12_no_reference_no_self_approval(case_id: str, tmp_path: Path) -> None:
    """G13-T-12: a managed install without an external reference is never confirmable."""
    manager, _ = managed_install(tmp_path / "models", "whisper-t12", dict(FILES, LICENSE=LICENSE))
    snapshot = managed_snapshot(manager, "whisper-t12", None)
    registry = art.ConfirmationRegistry()
    assert snapshot.integrity == art.INVALID and confirm(registry, snapshot) is None


@case("G13-T-13")
def test_t13_evidence_of_another_library_or_run(case_id: str, tmp_path: Path) -> None:
    """G13-T-13"""
    snapshot = whisper_snapshot(write(tmp_path / "model", FILES))
    first, second = art.ConfirmationRegistry("library-1"), art.ConfirmationRegistry("library-2")
    evidence = confirm(first, snapshot)
    moved = art.ModelUseEvidence(evidence.record_id, evidence.key, snapshot, second)
    assert not second.valid(moved)
    first.new_generation()
    assert not evidence.valid()
    with pytest.raises(ProviderError, match="CAPABILITY_UNSUPPORTED"):
        freeze(evidence, parent=tmp_path)


@case("G13-T-14")
def test_t14_role_cross(case_id: str, tmp_path: Path) -> None:
    """G13-T-14: a Whisper confirmation never serves the diarization path and back."""
    whisper = confirm(art.ConfirmationRegistry(), whisper_snapshot(write(tmp_path / "w", FILES)))
    config = manifest(tmp_path / "d")
    files, _ = verified_bundle(config)
    with pytest.raises(ProviderError):
        freeze(whisper, data=files, parent=tmp_path)
    diarization = confirm(art.ConfirmationRegistry(), diarization_of(config))
    with pytest.raises(ProviderError, match="CAPABILITY_UNSUPPORTED"):
        recheck_whisper(diarization)
    assert not diarization_native(whisper, config)


@case("G13-T-15")
def test_t15_terms_change_alone_needs_a_new_confirmation(case_id: str, tmp_path: Path) -> None:
    """G13-T-15"""
    folder = write(tmp_path / "model", dict(FILES, LICENSE=LICENSE))
    registry = art.ConfirmationRegistry()
    evidence = confirm(registry, whisper_snapshot(folder))
    (folder / "LICENSE").write_bytes(b"Other license text")
    with pytest.raises(ProviderError, match="MODEL_CHECKSUM_MISMATCH"):
        freeze(evidence, parent=tmp_path)
    changed = whisper_snapshot(folder)
    assert changed.artifact_digest == evidence.snapshot.artifact_digest
    assert changed.terms_digest != evidence.snapshot.terms_digest
    assert registry.evidence(changed) is None


@case("G13-T-16")
def test_t16_same_size_same_mtime_change(case_id: str, tmp_path: Path) -> None:
    """G13-T-16: content is compared, not size or modification time."""
    folder = write(tmp_path / "model", FILES)
    evidence = confirm(art.ConfirmationRegistry(), whisper_snapshot(folder))
    target = folder / "model.bin"
    stamp = target.stat()
    target.write_bytes(bytes(reversed(FILES["model.bin"])))
    os.utime(target, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    with pytest.raises(ProviderError, match="MODEL_CHECKSUM_MISMATCH"):
        freeze(evidence, parent=tmp_path)


@case("G13-T-17")
def test_t17_identity_swap_while_open(case_id: str, tmp_path: Path) -> None:
    """G13-T-17: the name now names another file than the read handle."""

    class Swap(ArtifactIo):
        def stat(self, path: Path) -> os.stat_result:
            info = super().stat(path)
            if path.name == "model.bin":
                fields = list(info)
                fields[1] += 1  # st_ino
                return os.stat_result(fields)
            return info

    folder = write(tmp_path / "model", FILES)
    with pytest.raises(ProviderError, match="MODEL_CHECKSUM_MISMATCH"):
        hash_file(folder / "model.bin", Swap())


class Faulty(ArtifactIo):
    def __init__(self, error: OSError) -> None:
        self.error = error

    def write(self, stream: Any, data: bytes) -> None:
        stream.write(data[: len(data) // 2])
        raise self.error


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (OSError("short write"), "INPUT_INVALID"),
        (OSError(errno.ENOSPC, "full"), "RESOURCE_EXHAUSTED"),
    ],
    ids=["G13-T-18", "G13-T-19"],
)
def test_t18_t19_copy_failures_leave_no_bundle(tmp_path: Path, error: OSError, code: str) -> None:
    folder = write(tmp_path / "model", FILES)
    evidence = confirm(art.ConfirmationRegistry(), whisper_snapshot(folder))
    bundles = tmp_path / "bundles"
    bundles.mkdir()
    with pytest.raises(ProviderError, match=code):
        freeze(evidence, parent=bundles, io=Faulty(error))
    assert list(bundles.iterdir()) == []
    assert (folder / "model.bin").read_bytes() == FILES["model.bin"]  # the source untouched


@case("G13-T-20")
def test_t20_sdk_without_files_mapping(case_id: str, tmp_path: Path) -> None:
    """G13-T-20: an explicit capability failure; never a retry with the folder path."""
    calls: list[tuple[str, dict[str, Any]]] = []

    def old_sdk(identifier: str, **options: Any) -> Any:
        calls.append((identifier, options))
        if "files" in options:
            raise TypeError("unexpected keyword argument 'files'")
        raise AssertionError("retried with a path")

    folder = write(tmp_path / "model", FILES)
    evidence = confirm(art.ConfirmationRegistry(), whisper_snapshot(folder))
    bundle = freeze(evidence, parent=tmp_path)
    try:
        provider = FasterWhisperProvider(folder, model_factory=old_sdk, bundle=bundle.description())
        with pytest.raises(ProviderError, match="CAPABILITY_UNSUPPORTED"):
            provider.load()
    finally:
        bundle.close()
    assert len(calls) == 1 and calls[0][0].startswith("recoryn-bundle-")


@case("G13-T-21")
def test_t21_sealed_bundle_cannot_be_changed_or_renamed(case_id: str, tmp_path: Path) -> None:
    """G13-T-21: the real share-deny guards (synthetic files in OS TEMP only)."""
    folder = write(tmp_path / "model", FILES)
    evidence = confirm(art.ConfirmationRegistry(), whisper_snapshot(folder))
    bundle = freeze(evidence, parent=tmp_path)
    try:
        target = bundle.directory / "model.bin"
        with pytest.raises(OSError):
            target.open("r+b").close()
        with pytest.raises(OSError):
            os.replace(target, bundle.directory / "moved.bin")
        with pytest.raises(OSError):
            os.replace(bundle.directory, bundle.directory.with_name("moved-bundle"))
        mapping, handles, digest = whisper_files(bundle.description())
        for stream in handles:
            stream.close()
        assert digest == evidence.snapshot.artifact_digest and bundle.sealed
    finally:
        bundle.close()


@case("G13-T-22")
def test_t22_native_reply_digest_substitution(
    case_id: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """G13-T-22: a child reporting other bytes is refused and closed."""
    from recoryn.app.inference import LocalSTTProcess

    folder = write(tmp_path / "model", FILES)
    evidence = confirm(art.ConfirmationRegistry(), whisper_snapshot(folder))
    provider = LocalSTTProcess(folder, model_evidence=evidence)
    closed: list[bool] = []
    monkeypatch.setattr(
        provider, "_call", lambda request, context: {"facts": {"artifact_digest": "f" * 64}}
    )
    monkeypatch.setattr(provider, "close", lambda: closed.append(True))
    with pytest.raises(ProviderError, match="MODEL_CHECKSUM_MISMATCH"):
        provider.load()
    assert closed == [True]


@case("G13-T-23")
def test_t23_missing_child_ack_keeps_the_guard(case_id: str, tmp_path: Path) -> None:
    """G13-T-23: the bundle stays sealed until the child is gone."""
    from recoryn.app.inference import LocalSTTProcess

    folder = write(tmp_path / "model", FILES)
    evidence = confirm(art.ConfirmationRegistry(), whisper_snapshot(folder))
    provider = LocalSTTProcess(folder, model_evidence=evidence)
    bundle = freeze(evidence, parent=tmp_path)
    alive = [True]

    class Child:
        def is_alive(self) -> bool:
            return alive[0]

        def join(self, timeout: float) -> None:
            pass

        def terminate(self) -> None:
            pass

        def close(self) -> None:
            pass

    class Channel:
        def put_nowait(self, item: Any) -> None:
            pass

        def cancel_join_thread(self) -> None:
            pass

        def close(self) -> None:
            pass

    provider._process, provider._bundle = Child(), bundle
    provider._requests = provider._replies = Channel()
    with pytest.raises(ProviderError, match="INFERENCE_ACK_PENDING"):
        provider.close()
    assert bundle.sealed and (bundle.directory / "model.bin").exists()
    alive[0] = False
    provider.close()
    assert not bundle.directory.exists()


@case("G13-T-24")
def test_t24_no_evidence_is_lazy_only(case_id: str, tmp_path: Path) -> None:
    """G13-T-24: objects without evidence are created, but no loader or child starts."""
    from recoryn.app.inference import LocalSTTProcess

    folder = write(tmp_path / "model", FILES)
    factory = Factory()
    provider = FasterWhisperProvider(folder, model_factory=factory)
    with pytest.raises(ProviderError, match="CAPABILITY_UNSUPPORTED") as raised:
        provider.load()
    assert getattr(raised.value, "detail", None) == "MODEL_CONFIRMATION_REQUIRED"  # G13R-10
    process = LocalSTTProcess(folder)
    with pytest.raises(ProviderError, match="CAPABILITY_UNSUPPORTED") as raised:
        process.transcribe(STTRequest(tmp_path / "audio.wav"))
    assert getattr(raised.value, "detail", None) == "MODEL_CONFIRMATION_REQUIRED"
    assert process._process is None and factory.calls == []


@case("G13-T-25")
def test_t25_a_profile_for_other_bytes_mismatches(case_id: str, tmp_path: Path) -> None:
    """G13-T-25: the explicit known profile stays applied and mismatches the new digest."""
    from recoryn.models.resource_catalog import MemoryProfile, profile_digest
    from recoryn.models.resources import PROFILE_MISMATCH, ResourceRequest, resolve_profile
    from recoryn.ui.ai_bridge import model_request

    snapshot = whisper_snapshot(write(tmp_path / "model", FILES))
    fields: dict[str, Any] = {
        "profile_id": "fake-profile",
        "kind": "stt",
        "backend": "LOCAL_CT2",
        "model_identity": "0" * 64,  # the previous bytes
        "runtime_identity": "runtime-fake",
        "envelope": (),
        "cpu_host_ram": 1,
        "gpu_host_ram": None,
        "gpu_bytes": None,
        "evidence": "e" * 64,
        "status": "REVIEWED",
        "digest": "",
    }
    probe = MemoryProfile.__new__(MemoryProfile)
    for name, value in fields.items():
        object.__setattr__(probe, name, value)
    fields["digest"] = profile_digest(probe)
    profile = MemoryProfile(**fields)
    request = ResourceRequest(
        "stt",
        "LOCAL_CT2",
        "CPU_ONLY",
        runtime_identity="runtime-fake",
        profile_identity="fake-profile",
    )
    bound = model_request(request, snapshot)
    assert bound.profile_identity == "fake-profile"
    assert bound.model_identity == snapshot.artifact_digest
    with pytest.raises(Exception, match=PROFILE_MISMATCH):
        resolve_profile(bound, (profile,))


@case("G13-T-26")
def test_t26_no_profile_stays_unknown(case_id: str, tmp_path: Path) -> None:
    """G13-T-26: no profile: UNKNOWN (None), nothing estimated or added by G13."""
    from recoryn.models.resources import ResourceRequest, resolve_profile
    from recoryn.ui.ai_bridge import model_request

    snapshot = whisper_snapshot(write(tmp_path / "model", FILES))
    request = ResourceRequest("stt", "LOCAL_CT2", "CPU_ONLY", runtime_identity="runtime-fake")
    bound = model_request(request, snapshot)
    assert replace(bound, model_identity=None) == request  # only the digest was bound
    assert resolve_profile(bound, ()) is None


@case("G13-T-27")
def test_t27_terms_refresh_keeps_the_result_key(case_id: str, tmp_path: Path) -> None:
    """G13-T-27: same bytes and device: same result key; the old confirmation is not
    reused for the new terms (a new confirmation, not a re-run of processed audio)."""
    from recoryn.ui.ai_bridge import local_result_key

    folder = write(tmp_path / "model", dict(FILES, LICENSE=LICENSE))
    registry = art.ConfirmationRegistry()
    before = whisper_snapshot(folder)
    confirm(registry, before)
    (folder / "LICENSE").write_bytes(b"Updated license text")
    after = whisper_snapshot(folder)
    assert local_result_key(before.artifact_digest, "cpu") == local_result_key(
        after.artifact_digest, "cpu"
    )
    assert local_result_key(after.artifact_digest, "cpu") == after.artifact_digest + ":cpu"
    assert registry.evidence(after) is None and registry.evidence(before) is not None


@case("G13-T-28")
def test_t28_device_change_continue_is_plan_changed(case_id: str, tmp_path: Path) -> None:
    """G13-T-28: another real device is another semantic key; a continue is refused."""
    from recoryn.app.ai import AIService
    from recoryn.content import ContentStore
    from recoryn.domain import StateConflict
    from recoryn.models import ResourceRequest
    from recoryn.storage import Library
    from recoryn.ui.ai_bridge import local_result_key
    from tests.e2e.test_ai_workflow import FakeSTT, recording

    digest = whisper_snapshot(write(tmp_path / "model", FILES)).artifact_digest
    with Library(tmp_path / "library") as library, ContentStore(library) as content:
        session = recording(library)
        service = AIService(library, content)
        try:
            service.runner.submit = lambda *args, **kwargs: True  # type: ignore[method-assign]
            request = ResourceRequest("stt", "LOCAL_CT2", "GPU_WITH_CPU_FALLBACK_ALLOWED")
            job_id = service.transcribe(
                session,
                FakeSTT(),
                config_key=local_result_key(digest, "cuda"),
                resource_request=request,
            )
            job = service.jobs.get(job_id)
            blocked = service.jobs.block_pending(
                job_id, "BUDGET", "COST_CAP_EXCEEDED", expected_version=job.state_version
            )
            count = len(service.jobs.list_for_session(session))
            with pytest.raises(StateConflict, match="CONTINUE_PLAN_CHANGED"):
                service.transcribe(
                    session,
                    FakeSTT(),
                    config_key=local_result_key(digest, "cpu"),
                    resource_request=request,
                    expected_job_id=job_id,
                    expected_job_version=blocked.state_version,
                )
            assert service.jobs.get(job_id) == blocked
            assert len(service.jobs.list_for_session(session)) == count  # no new Job/attempt
        finally:
            service.close()


# --- FIX1 supplementary rows (G13 review G13R-01..10; outside the 1,660 plan) --------


def x(cid: str) -> Any:
    return pytest.mark.parametrize("case_id", [cid], ids=[cid])


def accepted(action: Any) -> Any:
    """An accepted case must not be refused: a refusal is this row's assertion failure."""
    try:
        return action()
    except ProviderError as error:
        raise AssertionError(f"refused {error.code}/{error.detail}") from None


VOCAB_TXT = b"a\nb\n"


@x("G13-X-07")
def test_vocabulary_txt_is_an_optional_loader_input(case_id: str, tmp_path: Path) -> None:
    """G13R-01: the pinned SDK's own model form; recorded, sealed and supplied."""
    folder = write(tmp_path / "model", dict(FILES, **{"vocabulary.txt": VOCAB_TXT}))
    snapshot = accepted(lambda: whisper_snapshot(folder))
    assert snapshot.artifact_digest == by_hand(
        WHISPER_LOADER, "whisper", whisper_rows(FILES, None, None, VOCAB_TXT)
    )
    factory = whisper_native(confirm(art.ConfirmationRegistry(), snapshot), tmp_path)
    assert factory is not None
    received = factory.calls[0][1]
    assert received.get("vocabulary.txt") == VOCAB_TXT and "vocabulary.json" not in received
    manager, spec = managed_install(
        tmp_path / "models",
        "whisper-vocab",
        dict(FILES, **{"vocabulary.txt": VOCAB_TXT}, LICENSE=LICENSE),
    )
    managed = accepted(lambda: managed_snapshot(manager, "whisper-vocab", spec_digest(spec)))
    assert managed.integrity == art.MATCH and art.eligible(managed)


@x("G13-X-08")
def test_two_vocabulary_forms_are_ambiguous(case_id: str, tmp_path: Path) -> None:
    folder = write(tmp_path / "model", dict(FILES, **{"vocabulary.txt": VOCAB_TXT}))
    (folder / "vocabulary.json").write_bytes(b'["a"]')
    with pytest.raises(ProviderError, match="CAPABILITY_UNSUPPORTED") as raised:
        whisper_snapshot(folder)
    assert getattr(raised.value, "detail", None) == "VOCABULARY_AMBIGUOUS"


def confirmed_managed(tmp_path: Path) -> tuple[Any, Any, Any]:
    manager, spec = managed_install(tmp_path / "models", "whisper-x", dict(FILES, LICENSE=LICENSE))
    registry = art.ConfirmationRegistry()
    snapshot = managed_snapshot(manager, "whisper-x", spec_digest(spec))
    assert snapshot.integrity == art.MATCH
    return manager, registry, confirm(registry, snapshot)


@x("G13-X-09")
def test_a_managed_install_judged_invalid_now_never_runs_on_its_old_confirmation(
    case_id: str, tmp_path: Path
) -> None:
    """G13R-02 B: only installed.json changed (still self-consistent, same license)."""
    manager, registry, evidence = confirmed_managed(tmp_path)
    installed = manager.root / "whisper-x" / "installed.json"
    value = json.loads(installed.read_bytes())
    value["spec"]["files"][0]["url"] = "https://publisher.invalid/other-url"
    installed.write_text(json.dumps(value), encoding="utf-8")
    current = managed_snapshot(manager, "whisper-x", evidence.snapshot.terms.reference)
    assert current.integrity == art.INVALID
    assert registry.display(current) == art.CHANGED_INVALID
    assert registry.evidence(current) is None  # the screen and the run decision agree
    with pytest.raises(ProviderError, match="MODEL_CHECKSUM_MISMATCH"):
        freeze(evidence, parent=tmp_path)  # a queued Job's pre-native re-check refuses


@x("G13-X-10")
def test_a_deleted_installed_json_stops_a_queued_job(case_id: str, tmp_path: Path) -> None:
    """G13R-02 B2"""
    manager, _, evidence = confirmed_managed(tmp_path)
    (manager.root / "whisper-x" / "installed.json").unlink()
    with pytest.raises(ProviderError, match="MODEL_CHECKSUM_MISMATCH"):
        freeze(evidence, parent=tmp_path)


@x("G13-X-11")
def test_match_is_bound_to_the_hashed_bytes(case_id: str, tmp_path: Path) -> None:
    """G13R-04: model.bin changes between the manager check and the snapshot hash."""
    manager, spec = managed_install(tmp_path / "models", "whisper-y", dict(FILES, LICENSE=LICENSE))

    class Between(ArtifactIo):
        done = False

        def open_read(self, path: Path) -> Any:
            if not self.done and path.name == "config.json":
                self.done = True
                (path.parent / "model.bin").write_bytes(b"changed between the two reads!!!!!")
            return super().open_read(path)

    snapshot = managed_snapshot(manager, "whisper-y", spec_digest(spec), io=Between())
    assert snapshot.integrity == art.INVALID and not art.eligible(snapshot)


@x("G13-X-12")
def test_license_files_of_any_case_and_size_are_recorded_consistently(
    case_id: str, tmp_path: Path
) -> None:
    """G13R-05: an empty LICENSE and a lower-case license.txt never block a model."""
    folder = write(tmp_path / "model", dict(FILES, LICENSE=b""))
    snapshot = accepted(lambda: whisper_snapshot(folder))
    assert [(e.name, e.size) for e in snapshot.terms.license_files] == [("LICENSE", 0)]
    assert whisper_native(confirm(art.ConfirmationRegistry(), snapshot), tmp_path) is not None
    other = write(tmp_path / "lower", dict(FILES, **{"license.txt": LICENSE}))
    lower = accepted(lambda: whisper_snapshot(other))
    assert [e.name for e in lower.terms.license_files] == ["license.txt"]
    assert lower.license_state == art.FILE_ONLY  # G13R-06: a text, no id/URL
    assert whisper_native(confirm(art.ConfirmationRegistry(), lower), tmp_path) is not None


class Disk(ArtifactIo):
    def __init__(self, free: int, total: int) -> None:
        self.free, self.total = free, total

    def disk_usage(self, path: Path) -> Any:
        return SimpleNamespace(total=self.total, used=self.total - self.free, free=self.free)


@x("G13-X-14")
def test_a_copy_needs_the_model_size_plus_the_recording_reserve(
    case_id: str, tmp_path: Path
) -> None:
    """G13R-03 b: free >= size + max(1 GiB, 10% of the volume); the boundary exactly."""
    folder = write(tmp_path / "model", FILES)
    evidence = confirm(art.ConfirmationRegistry(), whisper_snapshot(folder))
    size = sum(len(v) for v in FILES.values())
    total = 100 * 1024**3
    reserve = max(1024**3, total // 10)  # by hand: 10 GiB here
    bundles = tmp_path / "bundles"
    bundles.mkdir()
    with pytest.raises(ProviderError, match="RESOURCE_EXHAUSTED") as raised:
        freeze(evidence, parent=bundles, io=Disk(size + reserve - 1, total))
    assert getattr(raised.value, "detail", None) == "DISK_RESERVE" and list(bundles.iterdir()) == []
    assert (folder / "model.bin").read_bytes() == FILES["model.bin"]
    small = 4 * 1024**3  # a small volume: the 1 GiB floor applies
    with pytest.raises(ProviderError, match="RESOURCE_EXHAUSTED"):
        freeze(evidence, parent=bundles, io=Disk(size + 1024**3 - 1, small))
    accepted(lambda: freeze(evidence, parent=bundles, io=Disk(size + reserve, total))).close()


@x("G13-X-15")
def test_one_confirmation_reuses_its_sealed_copy_between_jobs(case_id: str, tmp_path: Path) -> None:
    """G13R-03 a: re-check each Job, copy once, keep the guards, retire when replaced."""
    from recoryn.models._artifact_io import acquire, release, release_idle

    class Count(ArtifactIo):
        copies = 0

        def open_new(self, path: Path) -> Any:
            Count.copies += 1
            return super().open_new(path)

    folder = write(tmp_path / "model", FILES)
    registry = art.ConfirmationRegistry()
    evidence = confirm(registry, whisper_snapshot(folder))
    first = acquire(evidence, parent=tmp_path, io=Count())
    second = acquire(evidence, parent=tmp_path, io=Count())
    assert first is second and Count.copies == len(FILES)  # one copy for both Jobs
    assert release(first) and release(second) and first.sealed  # idle, still sealed
    third = acquire(evidence, parent=tmp_path, io=Count())
    assert third is first and Count.copies == len(FILES)
    release(third)
    (folder / "model.bin").write_bytes(b"newer synthetic bytes")
    with pytest.raises(ProviderError, match="MODEL_CHECKSUM_MISMATCH"):
        acquire(evidence, parent=tmp_path)  # every Job re-checks the original first
    assert not first.directory.exists()  # an idle copy of a changed source is retired
    newer = confirm(registry, whisper_snapshot(folder))
    replacement = acquire(newer, parent=tmp_path)
    assert replacement is not first
    other = confirm(registry, whisper_snapshot(write(tmp_path / "other", FILES)))
    release(acquire(other, parent=tmp_path))
    release(replacement)
    again = confirm(art.ConfirmationRegistry(), whisper_snapshot(folder))
    release(acquire(again, parent=tmp_path))  # another confirmation of the same folder
    assert not replacement.directory.exists()  # retires the idle older copy
    assert release_idle() == 0  # the remaining idle copies (other folder, again) closed


@x("G13-X-16")
def test_a_file_added_to_a_sealed_bundle_stops_the_loader(case_id: str, tmp_path: Path) -> None:
    """G13R-07 b: the folder guard cannot stop creation; the exact listing check does."""
    folder = write(tmp_path / "model", FILES)
    evidence = confirm(art.ConfirmationRegistry(), whisper_snapshot(folder))
    bundle = freeze(evidence, parent=tmp_path)
    try:
        (bundle.directory / "extra.onnx.data").write_bytes(b"sidecar")
        with pytest.raises(ProviderError, match="MODEL_CHECKSUM_MISMATCH") as raised:
            whisper_files(bundle.description())
        assert getattr(raised.value, "detail", None) == "BUNDLE_CHANGED"
        (bundle.directory / "extra.onnx.data").unlink()
    finally:
        bundle.close()
    config = manifest(tmp_path / "diarization")
    files, _ = verified_bundle(config)
    sealed = freeze(
        confirm(art.ConfirmationRegistry(), diarization_of(config)), data=files, parent=tmp_path
    )
    try:
        (sealed.directory / "segmentation.onnx.data").write_bytes(b"sidecar")
        from recoryn.models._artifact_io import diarization_files

        with pytest.raises(ProviderError, match="MODEL_CHECKSUM_MISMATCH"):
            diarization_files(sealed.description())
        (sealed.directory / "segmentation.onnx.data").unlink()
    finally:
        sealed.close()


@x("G13-X-17")
def test_a_failed_cleanup_is_counted_and_retried(case_id: str, tmp_path: Path) -> None:
    """G13R-07 a: "임시 모델 사본 정리 대기" is counted, retried, never elsewhere."""
    from recoryn.models._artifact_io import cleanup_pending, release, release_idle

    class Stuck(ArtifactIo):
        fail = True

        def remove(self, path: Path) -> None:
            if Stuck.fail:
                raise PermissionError("still open elsewhere")
            super().remove(path)

    folder = write(tmp_path / "model", FILES)
    evidence = confirm(art.ConfirmationRegistry(), whisper_snapshot(folder))
    bundle = freeze(evidence, parent=tmp_path, io=Stuck())
    assert release(bundle) is False and cleanup_pending() == 1
    assert release_idle() == 1 and bundle.directory.exists()
    Stuck.fail = False
    # The next Job's acquisition retries it (as do shutdown and model deletion).
    from recoryn.models._artifact_io import acquire

    release(acquire(evidence, parent=tmp_path))
    assert cleanup_pending() == 0 and not bundle.directory.exists()
    assert release_idle() == 0
    assert (folder / "model.bin").read_bytes() == FILES["model.bin"]  # only its own copy


@x("G13-X-18")
def test_the_missing_confirmation_detail_is_carried(case_id: str, tmp_path: Path) -> None:
    """G13R-10: CAPABILITY_UNSUPPORTED with detail MODEL_CONFIRMATION_REQUIRED."""
    from recoryn.diarization import backend

    config = manifest(tmp_path / "diarization")
    with pytest.raises(ProviderError, match="CAPABILITY_UNSUPPORTED") as raised:
        backend.compute(config, None, threading.Event(), "0" * 64, None)  # type: ignore[arg-type]
    assert getattr(raised.value, "detail", None) == "MODEL_CONFIRMATION_REQUIRED"
    provider = LocalDiarizationProcess(config)

    class Execution:
        cancel = None

    with pytest.raises(ProviderError) as raised:
        provider._seal(Execution())  # type: ignore[arg-type]
    assert getattr(raised.value, "detail", None) == "MODEL_CONFIRMATION_REQUIRED"


@x("G13-X-19")
def test_a_bundle_digest_failure_never_reaches_the_loader(case_id: str, tmp_path: Path) -> None:
    """G13R-09 b: names intact, digest wrong: whisper_files refuses before any loader."""
    folder = write(tmp_path / "model", FILES)
    bundle = freeze(confirm(art.ConfirmationRegistry(), whisper_snapshot(folder)), parent=tmp_path)
    try:
        forged = bundle.description()
        forged["entries"] = [
            [n, s, ("0" * 64 if n == "config.json" else h), st] for n, s, h, st in forged["entries"]
        ]
        factory = Factory()
        provider = FasterWhisperProvider(folder, model_factory=factory, bundle=forged)
        with pytest.raises(ProviderError, match="MODEL_CHECKSUM_MISMATCH"):
            provider.load()
        assert factory.calls == []
    finally:
        bundle.close()


@x("G13-X-20")
def test_a_bundle_change_between_copy_and_seal_is_refused(case_id: str, tmp_path: Path) -> None:
    """G13R-09 h: the bundle (not the source) changes right before the guards."""

    class Swap(ArtifactIo):
        done = False

        def guard(self, path: Path, *, directory: bool) -> Any:
            if not self.done and not directory:
                self.done = True
                path.write_bytes(b"tampered bundle bytes")
            return super().guard(path, directory=directory)

    folder = write(tmp_path / "model", FILES)
    evidence = confirm(art.ConfirmationRegistry(), whisper_snapshot(folder))
    bundles = tmp_path / "bundles"
    bundles.mkdir()
    with pytest.raises(ProviderError, match="MODEL_CHECKSUM_MISMATCH"):
        freeze(evidence, parent=bundles, io=Swap())
    assert list(bundles.iterdir()) == []


@x("G13-X-22")
def test_a_file_added_between_copy_and_seal_is_refused(case_id: str, tmp_path: Path) -> None:
    """G13R-07 b / G13R-09 h: a name appears in the bundle right before its folder guard."""

    class Add(ArtifactIo):
        def guard(self, path: Path, *, directory: bool) -> Any:
            if directory:
                (path / "extra.bin").write_bytes(b"not part of the confirmation")
            return super().guard(path, directory=directory)

    folder = write(tmp_path / "model", FILES)
    evidence = confirm(art.ConfirmationRegistry(), whisper_snapshot(folder))
    bundles = tmp_path / "bundles"
    bundles.mkdir()
    with pytest.raises(ProviderError, match="MODEL_CHECKSUM_MISMATCH") as raised:
        freeze(evidence, parent=bundles, io=Add())
    assert getattr(raised.value, "detail", None) == "BUNDLE_CHANGED"
    # Only its own copies were removed; the foreign name is left alone (never deleted).
    left = [p for p in bundles.rglob("*") if p.is_file()]
    assert [p.name for p in left] == ["extra.bin"]
    assert (folder / "model.bin").read_bytes() == FILES["model.bin"]


def test_declared_unit_denominators() -> None:
    assert len(A_CASES) == 8 * 2 * 4 * 3 == 192 and len(B_CASES) == 2 * 2 * 6 * 3 == 72
    assert len(K_CASES) == 2**8 * 2 == 512
