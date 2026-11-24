"""Owned subprocess kills at real OPEN/checkpoint/worker/CLOSED boundaries."""

import json
import os
import subprocess
import sys
import time
from itertools import product
from pathlib import Path

import pytest

from recoryn.storage import Library

pytestmark = pytest.mark.integration
K = [
    (stage, prefix, tracks)
    for stage, prefix, tracks in product(range(10), (None, 0, 6), (1, 2))
    if (stage == 0 and prefix is None)
    or (stage == 1 and prefix == 0)
    or (stage >= 2 and prefix in {0, 6})
]


def permission_retry(action, deadline):
    while True:
        try:
            return action()
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.005)


@pytest.mark.parametrize("case", range(36, 41), ids=[f"G08-FIX1-{n:02}" for n in range(36, 41)])
def test_marker_permission_retry_is_narrow(case, tmp_path):
    calls = []
    error = PermissionError("owned marker sharing race")
    marker = tmp_path / "ready.json"
    temporary = tmp_path / "ready.publishing"
    temporary.write_text('{"ready":true}')

    def action():
        calls.append(1)
        if case == 40:
            raise ValueError("not a sharing violation")
        if case in {38, 39} or len(calls) < 3:
            raise error
        if case == 36:
            os.replace(temporary, marker)
        else:
            marker.write_text(temporary.read_text())
        return json.loads(marker.read_text())

    if case in {38, 39}:
        with pytest.raises(PermissionError) as caught:
            permission_retry(action, time.monotonic() - 1)
        assert caught.value is error and len(calls) == 1
    elif case == 40:
        with pytest.raises(ValueError, match="not a sharing"):
            permission_retry(action, time.monotonic() + 5)
        assert len(calls) == 1
    else:
        assert permission_retry(action, time.monotonic() + 5) == {"ready": True}
        assert len(calls) == 3


CHILD = r"""
import json, os, sys, threading, time
from pathlib import Path
from contextlib import contextmanager
from recoryn.app.recording import RecordingService
from recoryn.domain import AudioFormat, PCMBlock, SessionState
from recoryn.storage import Library, ChunkWriter
import recoryn.app.recording as imported
from tests.integration.test_health_crash import permission_retry
root, marker, stage, prefix, tracks = Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5])
lib=Library(root)
svc=RecordingService(lib, {t:AudioFormat(48000,1) for t in ('mic','system')[:tracks]}, session_id='s', chunk_frames=3, max_blocks=1)
def park():
    temporary=marker.with_suffix('.publishing')
    temporary.write_text(json.dumps({'import':imported.__file__, 'stage':stage, 'accepting':svc.health_snapshot()['accepting']}),encoding='utf-8')
    permission_retry(lambda: os.replace(temporary,marker),time.monotonic()+10)
    threading.Event().wait(300)
def block(n, track='mic', frames=3):
    return PCMBlock('s',track,svc.epochs[track],n,svc.formats[track],frames,b'\x01\0'*frames,n,n,n*frames)
if stage==0:
    original=lib._transaction
    @contextmanager
    def held():
        with original() as db:
            yield db
            park()
    lib._transaction=held
svc.start()
if stage==1: park()
if prefix==6:
    offer=svc._queue.offer
    svc._queue.offer=lambda _:False
    for track in svc.formats: assert not svc.submit(block(0,track,6))
    svc._queue.offer=offer
    svc._checkpoint_health(force=True)
if stage in (2,3):
    entered=threading.Event()
    def append(*_):
        entered.set()
        threading.Event().wait(300)
    ChunkWriter.append=append
    assert svc.submit(block(1))
    assert entered.wait(10)
    if stage==3:
        assert svc.submit(block(2))
        assert not svc.submit(block(3))
    park()
elif stage==4:
    svc._checkpoint_health(force=True)
    park()
elif stage==5:
    register=lib.register_chunk
    def published(value):
        register(value)
        park()
    lib.register_chunk=published
    assert svc.submit(block(1))
    threading.Event().wait(300)
elif stage==6:
    svc._join_workers=lambda _:park()
    svc.pause()
elif stage==7:
    lib.finish_capture_health=lambda *a,**k:park()
    svc.pause()
elif stage==8:
    transition=lib.transition
    def changed(sid,target,version):
        if target==SessionState.PAUSED: park()
        return transition(sid,target,version)
    lib.transition=changed
    svc.pause()
else:
    svc.pause()
    park()
"""


@pytest.mark.parametrize("row", K, ids=[f"G08-K-{i:02}" for i in range(1, 37)])
def test_actual_health_boundary_kill(row, tmp_path):
    stage, prefix, tracks = row
    root, marker = tmp_path / "library", tmp_path / "ready.json"
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    import recoryn.app.recording as parent

    src = Path(parent.__file__).resolve().parents[2]
    env["PYTHONPATH"] = str(src)
    with subprocess.Popen(
        [
            sys.executable,
            "-B",
            "-c",
            CHILD,
            str(root),
            str(marker),
            str(stage),
            str(prefix or 0),
            str(tracks),
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ) as child:
        deadline = time.monotonic() + 15
        try:
            while not marker.exists() and child.poll() is None and time.monotonic() < deadline:
                time.sleep(0.005)
            if not marker.exists():
                child.kill()
                out, error = child.communicate(timeout=5)
                pytest.fail(f"boundary not reached: {out!r} {error!r}")
            evidence = json.loads(
                permission_retry(lambda: marker.read_text(encoding="utf-8"), deadline)
            )
            assert Path(evidence["import"]).resolve() == Path(parent.__file__).resolve()
            assert evidence["stage"] == stage
            if stage == 0:
                assert evidence["accepting"] is False
            media = {p.relative_to(root): p.read_bytes() for p in root.rglob("audio.pcm")}
        finally:
            if child.poll() is None:
                child.kill()
            child.communicate(timeout=5)
    with Library(root) as library:
        result = library.recover_session("s")
        assert result["health_recovery"]["status"] != "DEFERRED"
        tails = [
            json.loads(r[0])
            for r in library._db.execute("SELECT payload FROM capture_health_events")
            if json.loads(r[0])["reason"] == "UNKNOWN_TAIL"
        ]
        assert len(tails) == (tracks if stage in range(1, 8) else 0)
        assert all(t["lost_frames"] is None for t in tails)
        if stage:
            for value in library.capture_health("s")["tracks"].values():
                assert value["dropped_frames"] == prefix
        for relative, content in media.items():
            assert (root / relative).read_bytes() == content
        before = list(library._db.execute("SELECT event_id,payload FROM capture_health_events"))
        library.recover_session("s")
        assert (
            list(library._db.execute("SELECT event_id,payload FROM capture_health_events"))
            == before
        )


def test_kill_denominator_is_independently_feasible():
    assert len(K) == 36
    assert [len([r for r in K if r[0] == stage]) for stage in range(10)] == [2, 2] + [4] * 8
