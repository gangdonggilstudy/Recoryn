"""Small frame-set oracle and explicit clock partitions; no product oracle imports."""

from itertools import product

import pytest

from recoryn.domain.capture_health import loss_totals, observed_interval
from tests.unit.test_track_health import fact

D = list(product(range(6), range(3), (False, True), (False, True), (1, 2)))
C = list(product(range(6), ("PAUSE", "DEVICE_LOST"), (1, 2)))
INTERVALS = ((30, 40), (20, 25), (10, 20), (12, 18), (15, 25), (None, None))


@pytest.mark.parametrize("row", D, ids=[f"G08-D-{i:03}" for i in range(1, 145)])
def test_interval_union_against_integer_sets(row):
    relation, source_kind, known, same_coordinate, tracks = row
    a = fact().to_dict()
    start, end = INTERVALS[relation]
    events = [a]
    if source_kind != 1:
        events.append(
            fact(
                event_id="device",
                gap_id="device",
                reason="DEVICE_DISCONTINUITY",
                source="DEVICE",
                start=start,
                end=end,
                range_quality="EXACT_SOURCE" if start is not None and known else "UNKNOWN",
                lost_frames=end - start if start is not None and known else None,
                count_quality="EXACT" if start is not None and known else "UNKNOWN",
                epoch_id="epoch" if same_coordinate else "other",
            ).to_dict()
        )
    if source_kind in {1, 2}:
        events.append({"event_id": "ai", "source": "AI_TAP", "lost_frames": 1000})
    if not known and source_kind == 1:
        events.append(
            fact(
                reason="UNKNOWN_TAIL",
                source="RECOVERY",
                kind="UNKNOWN_TAIL",
                start=None,
                end=None,
                range_quality="UNKNOWN",
                lost_frames=None,
                count_quality="UNKNOWN",
                event_id="tail",
                gap_id="tail",
            ).to_dict()
        )
    expected = 10
    exact = True
    if source_kind != 1:
        exact = start is not None and known and same_coordinate
        if exact:
            expected = len(set(range(10, 20)) | set(range(start, end)))
    elif not known:
        exact = False
    result = loss_totals(events + [a])  # repeated event ID cannot double count.
    assert result["known_loss_frames"] == (expected if exact else None)
    assert result["sources"]["APP_QUEUE"] == 10
    assert "AI_TAP" not in result["sources"]
    if tracks == 2:
        assert loss_totals([])["known_loss_frames"] == 0


@pytest.mark.parametrize("row", C, ids=[f"G08-C-{i:02}" for i in range(1, 25)])
def test_clock_partitions(row):
    clock, reason, tracks = row
    args = (
        (10, 20, "clock", "clock"),
        (10, 10, "clock", "clock"),
        (20, 10, "clock", "clock"),
        (10, 20, "old", "new"),
        (None, 20, None, "clock"),
        (float("nan"), 20, "clock", "clock"),
    )[clock]
    bounds = observed_interval(*args)
    assert bounds == ((10, 20) if clock == 0 else (10, 10) if clock == 1 else (None, None))
    # Control coordinates never produce measured lost frames. A device-lost
    # callback provides observation bounds, not the physical onset coordinate.
    for _ in range(tracks):
        gap = fact(
            reason=reason,
            source="CONTROL" if reason == "PAUSE" else "DEVICE",
            start=bounds[0] if reason == "PAUSE" else None,
            end=bounds[1] if reason == "PAUSE" else None,
            range_quality="OBSERVED_CONTROL"
            if reason == "PAUSE" and bounds[0] is not None
            else "UNKNOWN",
            lost_frames=None,
            count_quality="UNKNOWN",
        )
        assert gap.lost_frames is None
