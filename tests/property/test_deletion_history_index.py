"""Exact-map cost oracle: hot operations cannot enumerate or copy history."""

from itertools import product

import pytest

from recoryn.storage.deletion_history import DeletionHistoryIndex, HistoryClockSample, HistoryEntry

pytestmark = pytest.mark.property
SIZES = (0, 100, 1000, 10000)
GLOBAL_I = list(product(SIZES, ("job", "page", "delete")))
I_ROWS = [
    pytest.param(h, op, id=f"GS11-I-{index:03}")
    for index, (h, op) in enumerate(GLOBAL_I, 1)
    if op != "page"
]


class ExactMap(dict):
    gets = 0
    sets = 0

    def get(self, key, default=None):
        self.gets += 1
        return super().get(key, default)

    def __setitem__(self, key, value):
        self.sets += 1
        return super().__setitem__(key, value)

    def forbidden(self, *args, **kwargs):
        pytest.fail("hot operation enumerated/copied H entries")

    __iter__ = keys = values = items = copy = forbidden


@pytest.mark.parametrize("size,operation", I_ROWS)
def test_exact_lookup_and_one_delta_do_not_walk_or_copy_the_map(tmp_path, size, operation):
    index = DeletionHistoryIndex(tmp_path, clock=lambda: HistoryClockSample(10, 10))
    entry = HistoryEntry(3, "a" * 64, 3, "DELETED_LOCAL")
    rows = {f"past-{i:05}": entry for i in range(size)}
    scan = index.begin_scan()
    index.publish(index.prepare(scan, rows, index.cut()))
    guarded = ExactMap(rows)
    index._entries = guarded
    before_receipt, before_cut = index.receipt, index.cut()
    if operation == "job":
        assert index.known("ordinary") is None
        if size:
            assert index.known("past-00000") == entry
        assert guarded.sets == 0 and guarded.gets == (2 if size else 1)
        assert index.version == before_cut.version
    else:
        new = HistoryEntry(7, "b" * 64)
        index.trusted_delta("new", new)
        assert index.known("new") == new
        assert guarded.sets == 1 and guarded.gets == 2
        assert index.version == before_cut.version + 1
        assert index.cut().head.previous is before_cut.head
    assert index.receipt is before_receipt and index.valid()
    assert len(guarded) == size + (operation == "delete")
    # The cut held by a concurrent auditor remains immutable and complete.
    assert before_cut.materialize() == rows
