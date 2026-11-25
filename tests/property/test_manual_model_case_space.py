"""G13 case space: the independent 12-family denominator (1,660 rows) and generated
invariants of the artifact identity and of this run's confirmation registry.

The denominator is declared here from docs/testing/g13-manual-model-cases.md section 7.1
and its revision section 5, independently of the row modules; their declared case IDs are
compared with it (missing/duplicate/extra = 0). Generated checks use synthetic bytes only.
"""

from __future__ import annotations

import hashlib
import itertools
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from recoryn.models import artifacts as art
from recoryn.models._artifact_io import hash_file

pytestmark = pytest.mark.property

# family: (size, ID width), declared by hand.
PLAN = {
    "A": (192, 3),
    "B": (72, 2),
    "R": (144, 3),
    "P": (112, 3),
    "C": (144, 3),
    "L": (100, 3),
    "D": (48, 2),
    "U": (180, 3),
    "K": (512, 3),
    "T": (28, 2),
    "I": (64, 2),
    "J": (64, 2),
}


def expected_ids() -> set[str]:
    return {
        f"G13-{family}-{n:0{width}d}"
        for family, (size, width) in PLAN.items()
        for n in range(1, size + 1)
    }


def declared_ids() -> list[str]:
    from tests.integration import test_model_bundle as integration
    from tests.ui import test_manual_model_ui as ui
    from tests.unit import test_manual_models as unit

    ids: list[str] = []
    for module, names in (
        (unit, ("A_CASES", "B_CASES", "K_CASES")),
        (integration, ("R_CASES", "P_CASES", "L_CASES", "D_CASES", "I_CASES", "J_CASES")),
        (ui, ("C_CASES", "U_CASES")),
    ):
        for name in names:
            ids += [case.id for case in getattr(module, name)]
    # The named negatives carry their IDs on their own nodes.
    for module in (unit, ui):
        for value in vars(module).values():
            marks = getattr(value, "pytestmark", [])
            for mark in marks:
                if mark.name == "parametrize" and mark.kwargs.get("ids"):
                    ids += [i for i in mark.kwargs["ids"] if i.startswith("G13-T-")]
                elif mark.name == "parametrize" and len(mark.args) > 1:
                    ids += [
                        getattr(p, "id", None) or ""
                        for p in mark.args[1]
                        if str(getattr(p, "id", "")).startswith("G13-T-")
                    ]
    return ids


def test_the_twelve_family_denominator_is_exact() -> None:
    expected = expected_ids()
    assert sum(size for size, _ in PLAN.values()) == len(expected) == 1660
    declared = declared_ids()
    assert len(declared) == len(set(declared))  # no duplicate case ID
    assert set(declared) == expected  # nothing missing, nothing extra


ENTRY = st.builds(
    art.FileEntry,
    st.sampled_from(("config.json", "model.bin", "tokenizer.json", "vocabulary.json")),
    st.integers(1, 2**40),
    st.text("0123456789abcdef", min_size=64, max_size=64),
)


@settings(max_examples=120, deadline=None, derandomize=True, database=None)
@given(st.lists(ENTRY, min_size=1, max_size=4, unique_by=lambda e: e.name), st.randoms())
def test_the_artifact_digest_ignores_order_and_sees_every_field(
    entries: list[Any], rng: Any
) -> None:
    loader = art.LOADERS[art.WHISPER]
    shuffled = list(entries)
    rng.shuffle(shuffled)
    digest = art.artifact_digest(art.WHISPER, loader, tuple(entries))
    assert art.artifact_digest(art.WHISPER, loader, tuple(shuffled)) == digest
    first = entries[0]
    variants = [
        art.FileEntry(first.name, first.size + 1, first.sha256),
        art.FileEntry(first.name, first.size, "f" * 64 if first.sha256 != "f" * 64 else "e" * 64),
        art.FileEntry(first.name + "x", first.size, first.sha256),
        art.FileEntry(first.name, 0, "", art.ABSENT),
    ]
    for variant in variants:
        changed = (variant, *entries[1:])
        assert art.artifact_digest(art.WHISPER, loader, changed) != digest


@settings(max_examples=60, deadline=None, derandomize=True, database=None)
@given(st.binary(min_size=0, max_size=4096))
def test_the_same_bytes_hash_the_same_every_time(tmp_path_factory: Any, data: bytes) -> None:
    folder = tmp_path_factory.mktemp("g13-rehash")
    path = folder / "model.bin"
    path.write_bytes(data)
    first, second = hash_file(path, art_io()), hash_file(path, art_io())
    assert first == second and first[:2] == (len(data), hashlib.sha256(data).hexdigest())


def art_io() -> Any:
    from recoryn.models._artifact_io import ArtifactIo

    return ArtifactIo()


OPS = st.lists(
    st.tuples(
        st.sampled_from(("confirm", "decline", "new_generation", "lookup")), st.integers(0, 2)
    ),
    min_size=1,
    max_size=30,
)


@pytest.fixture(scope="module")
def snapshots(tmp_path_factory: pytest.TempPathFactory) -> list[Any]:
    from recoryn.models._artifact_io import whisper_snapshot

    result = []
    for index in range(3):
        folder = tmp_path_factory.mktemp(f"g13-state-{index}")
        for name, data in (
            ("config.json", b"{}"),
            ("model.bin", b"synthetic-" + bytes([index])),
            ("tokenizer.json", b"[]"),
        ):
            (folder / name).write_bytes(data)
        result.append(whisper_snapshot(Path(folder)))
    return result


@settings(max_examples=150, deadline=None, derandomize=True, database=None)
@given(OPS)
def test_a_confirmation_lives_only_in_its_run_generation(
    snapshots: list[Any], ops: list[Any]
) -> None:
    """State model: evidence exists exactly for snapshots confirmed (Yes + check) since
    the last generation change; a decline or a lookup never records anything."""
    registry = art.ConfirmationRegistry("model-state")
    confirmed: set[int] = set()
    issued: list[Any] = []
    for op, index in ops:
        snapshot = snapshots[index]
        if op == "confirm":
            evidence = registry.confirm(
                snapshot, shown=registry.key(snapshot), accepted=True, acknowledged=True
            )
            assert evidence is not None
            issued.append((index, evidence))
            confirmed.add(index)
        elif op == "decline":
            assert (
                registry.confirm(
                    snapshot, shown=registry.key(snapshot), accepted=False, acknowledged=True
                )
                is None
            )
        elif op == "new_generation":
            registry.new_generation()
            confirmed.clear()
        for other in range(3):
            assert (registry.evidence(snapshots[other]) is not None) is (other in confirmed)
        assert len(registry) == len(confirmed)
    for index, evidence in issued:
        assert evidence.valid() is (
            index in confirmed and registry.evidence(snapshots[index]) == evidence
        )


def test_family_axes_multiply_to_their_sizes() -> None:
    """The axes of section 7.1, by hand (the row modules must agree)."""
    sizes = {
        "A": len(list(itertools.product(range(8), range(2), range(4), range(3)))),
        "B": len(list(itertools.product(range(2), range(2), range(6), range(3)))),
        "R": len(list(itertools.product(range(6), range(6), range(2), range(2)))),
        "P": len(list(itertools.product(range(14), range(4), range(2)))),
        "C": len(list(itertools.product(range(2), range(4), range(3), range(3), range(2)))),
        "L": len(list(itertools.product(range(5), range(5), range(2), range(2)))),
        "D": len(list(itertools.product(range(8), range(3), range(2)))),
        "U": len(list(itertools.product(range(5), range(2), range(6), range(3)))),
        "K": 2**8 * 2,
        "T": 28,
        "I": len(list(itertools.product(range(8), range(2), range(2), range(2)))),
        "J": len(list(itertools.product(range(8), range(2), range(2), range(2)))),
    }
    assert sizes == {family: size for family, (size, _) in PLAN.items()}
