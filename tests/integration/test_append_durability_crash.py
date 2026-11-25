"""G17 strict crash cuts and media I/O failures; all inputs are synthetic PCM."""

from __future__ import annotations

import errno
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from itertools import product
from pathlib import Path

import pytest

from recoryn.app.recording import RecordingError, RecordingService
from recoryn.storage import Library, chunks
from recoryn.storage.chunks import has_active_writer
from tests.unit.test_append_durability import FORMAT, Harness, IOTrace, TrackedLock, block

pytestmark = pytest.mark.integration

# The actor exercises the actual RecordingService, queue, writer, sealer and Library.
# A shared checkpoint image avoids paying for three identical child starts; each
# persistence row below runs recovery on its own faulted copy, independently.
CHILD = r"""
import json,os,sys,threading,time
from pathlib import Path
root=Path(sys.argv[1]);stage=int(sys.argv[2]);tracks=("mic","system")[:int(sys.argv[3])]
tree=Path(sys.argv[4]);sys.path[:0]=[str(tree/'src'),str(tree)]
import recoryn
assert Path(recoryn.__file__).resolve().is_relative_to(tree/'src')
from recoryn.app.recording import RecordingService
from recoryn.capture.queue import BoundedCaptureQueue
from recoryn.storage import Library,ChunkWriter,chunks
from tests.unit.test_append_durability import FORMAT,block,IOTrace
import pytest,queue
patch=pytest.MonkeyPatch();freeze=threading.RLock();offered=threading.Event()
armed=False;marked=False;infos={};accepted=[]
library=Library(root);io=IOTrace(library.root,patch,library=library)
service=RecordingService(library,{t:FORMAT for t in tracks},session_id='s',chunk_frames=4)

def checkpoint():
 global marked
 if marked:return
 marked=True
 assert offered.wait(10)
 rows=[]
 for info in infos.values():
  writer=info['writer'];location=writer.path if writer.path.exists() else writer.staging_path
  rows.append({k:v for k,v in info.items() if k!='writer'}|{'location':location.relative_to(root).as_posix()})
 value={'stage':stage,'pid':os.getpid(),'origin':recoryn.__file__,'accepted':accepted,
        'writers':rows,'worker_alive':service.worker_alive}
 target=root.parent/'ready.json';temporary=target.with_suffix('.tmp');deadline=time.monotonic()+5
 while True:
  try:
   temporary.write_text(json.dumps(value),encoding='utf-8');os.replace(temporary,target);break
  except PermissionError:
   if time.monotonic()>=deadline:raise
   time.sleep(.005)
 threading.Event().wait()

original_init=ChunkWriter.__init__
def init(self,*args,**kwargs):
 original_init(self,*args,**kwargs)
 with freeze:
  infos[self.chunk_id]={'writer':self,'track':self.track_id,'sequence':None,'records':[],
   'pcm_sync':0,'journal_sync':0,'descriptor_sync':False,'cataloged':False}
patch.setattr(ChunkWriter,'__init__',init)

original_append=ChunkWriter.append
def append(self,item):
 with freeze:infos[self.chunk_id]['sequence']=item.sequence
 result=original_append(self,item)
 if armed and item.sequence==1 and stage==8:
  service._checkpoint_health(force=True)
  with freeze:checkpoint()
 return result
patch.setattr(ChunkWriter,'append',append)

def info_for(path):
 for info in infos.values():
  if path.parent in (info['writer'].staging_path,info['writer'].path):return info
 raise AssertionError(path)

def write(path,stream,data):
 with freeze:
  info=info_for(path);target=armed and info['sequence']==1
  if target and (stage==2 and path.name=='audio.pcm' or stage==5 and path.name=='blocks.jsonl'):
   stream.write(data[:max(1,len(data)//2)]);checkpoint()
  io.original_write(stream,data)
  if path.name=='blocks.jsonl':
   record=json.loads(data)
   info['records'].append([record['metadata']['sequence'],os.fstat(stream.fileno()).st_size,
                           record['offset']+record['length']])
io.write_hook=write

def sync(stream):
 path=io.paths[id(stream)]
 assert not io.mutex.owned and not io.registry.owned and not io.coordination.owned
 with freeze:
  info=info_for(path);target=armed and info['sequence']==1;name=path.name
  if target and (stage==3 and name=='audio.pcm' or stage==6 and name=='blocks.jsonl'
                 or stage==10 and name=='descriptor.json'):checkpoint()
  io.original_sync(stream)
  if name=='audio.pcm':info['pcm_sync']=os.fstat(stream.fileno()).st_size
  elif name=='blocks.jsonl':info['journal_sync']=os.fstat(stream.fileno()).st_size
  else:info['descriptor_sync']=True
  if target and (stage==4 and name=='audio.pcm' or stage==7 and name=='blocks.jsonl'):checkpoint()
patch.setattr(chunks,'sync',sync)

original_publish=ChunkWriter._publish
def publish(self):
 with freeze:
  result=original_publish(self)
  if armed and infos[self.chunk_id]['sequence']==1 and stage==11:checkpoint()
  return result
patch.setattr(ChunkWriter,'_publish',publish)

original_register=library.register_chunk
def register(value):
 result=original_register(value)
 descriptor=getattr(value,'descriptor',value)
 with freeze:
  infos[descriptor.chunk_id]['cataloged']=True
  if armed and descriptor.first_sequence==1 and stage==12:checkpoint()
 return result
library.register_chunk=register

original_get=BoundedCaptureQueue.get
def get(self,*args,**kwargs):
 value=original_get(self,*args,**kwargs)
 if armed and value.sequence==1 and stage==1:
  with freeze:checkpoint()
 return value
patch.setattr(BoundedCaptureQueue,'get',get)

original_seal_get=queue.Queue.get
def seal_get(self,*args,**kwargs):
 value=original_seal_get(self,*args,**kwargs)
 if isinstance(value,ChunkWriter) and armed and infos[value.chunk_id]['sequence']==1 and stage==9:
  with freeze:checkpoint()
 return value
patch.setattr(queue.Queue,'get',seal_get)

original_finish=library.finish_capture_health
def finish(*args,**kwargs):
 if armed and stage==13:
  with freeze:checkpoint()
 return original_finish(*args,**kwargs)
library.finish_capture_health=finish

service.start()
for track in tracks:
 item=block(0,track=track,epoch=service.epochs[track]);assert service.submit(item)
 accepted.append([track,0])
deadline=time.monotonic()+10
while len(library.chunks('s'))!=len(tracks):
 assert time.monotonic()<deadline and not service.health_snapshot()['storage_failed']
 time.sleep(.002)
armed=True
for track in tracks:
 item=block(1,track=track,epoch=service.epochs[track]);assert service.submit(item)
 accepted.append([track,1])
offered.set()
if stage==13:service.stop(timeout=30)
while True:
 assert not service.health_snapshot()['storage_failed']
 time.sleep(.01)
"""


@pytest.fixture(scope="module")
def checkpoints(tmp_path_factory):
    return tmp_path_factory.mktemp("g17-checkpoints"), {}


def checkpoint_image(checkpoints, tracks, stage):
    directory, cache = checkpoints
    key = (tracks, stage)
    if key in cache:
        return cache[key]
    artifact = directory / f"tracks{tracks}-C{stage:02}"
    artifact.mkdir()
    root, script = artifact / "library", artifact / "actor.py"
    script.write_text(CHILD, encoding="utf-8")
    tree = Path(__file__).resolve().parents[2]
    # Windows venv python.exe is a launcher; own the actual interpreter handle.
    interpreter = getattr(sys, "_base_executable", sys.executable)
    site = Path(sys.prefix) / (
        "Lib/site-packages"
        if os.name == "nt"
        else f"lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages"
    )
    command = [interpreter, str(script), str(root), str(stage), str(tracks), str(tree)]
    with (artifact / "actor.log").open("wb") as log:
        process = subprocess.Popen(
            command,
            cwd=tree,
            env={
                **os.environ,
                "PYTHONPATH": os.pathsep.join((str(tree / "src"), str(site))),
                "PYTHONDONTWRITEBYTECODE": "1",
                "QT_QPA_PLATFORM": "offscreen",
            },
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            deadline = time.monotonic() + 30
            ready = artifact / "ready.json"
            while True:
                try:
                    value = json.loads(ready.read_bytes())
                    break
                except (FileNotFoundError, PermissionError):
                    if time.monotonic() >= deadline or process.poll() is not None:
                        raise AssertionError(
                            (command, (artifact / "actor.log").read_text())
                        ) from None
                    time.sleep(0.005)
            assert value["pid"] == process.pid
            assert Path(value["origin"]).resolve().is_relative_to(tree / "src")
            assert value["stage"] == stage
            if stage == 13:
                assert value["worker_alive"] is False
        finally:
            if process.poll() is None:
                process.kill()  # only the child handle this fixture owns
            process.wait(timeout=15)
    cache[key] = root, value
    return root, value


C = list(product((1, 2), range(1, 14), ("kill", "sync-prefix", "tear")))


@pytest.mark.parametrize("tracks,stage,persistence", C, ids=[f"G17-C-{i:03}" for i in range(1, 79)])
def test_strict_crash_prefix_recovery_and_no_original_overwrite(
    tmp_path, checkpoints, tracks, stage, persistence
):
    source, observed = checkpoint_image(checkpoints, tracks, stage)
    root = tmp_path / "copy"
    shutil.copytree(source, root)
    expected = {t: [] for t in ("mic", "system")[:tracks]}
    optional = set()
    for info in observed["writers"]:
        path = root / info["location"]
        if not path.exists():
            continue
        pcm, journal, descriptor = (
            path / "audio.pcm",
            path / "blocks.jsonl",
            path / "descriptor.json",
        )
        pcm_limit, journal_limit = pcm.stat().st_size, journal.stat().st_size
        if persistence != "kill":
            for file, limit in ((pcm, info["pcm_sync"]), (journal, info["journal_sync"])):
                size = file.stat().st_size
                surviving = min(size, limit + int(persistence == "tear" and size > limit))
                with file.open("r+b") as stream:
                    stream.truncate(surviving)
            pcm_limit, journal_limit = pcm.stat().st_size, journal.stat().st_size
            if descriptor.exists() and not info["descriptor_sync"]:
                if persistence == "sync-prefix":
                    descriptor.unlink()
                else:
                    descriptor.write_bytes(b'{"schema_version":')
                    optional.add(info["track"])
        for sequence, journal_end, pcm_end in info["records"]:
            if journal_end <= journal_limit and pcm_end <= pcm_limit:
                expected[info["track"]].append(sequence)
    for values in expected.values():
        values.sort()
        assert values in ([0], [0, 1])
    originals = {
        p.relative_to(root): p.read_bytes()
        for p in root.rglob("*")
        if p.is_file() and p.name in {"audio.pcm", "blocks.jsonl", "descriptor.json"}
    }
    with Library(root) as library:
        library.recover_session("s")
        recovered = library.chunks("s")
        for track, sequences in expected.items():
            saved = sorted(
                (c for c in recovered if c.track_id == track), key=lambda c: c.first_sequence
            )
            actual = b"".join((root / c.relative_path / "audio.pcm").read_bytes() for c in saved)
            wanted = b"".join(block(i, track=track).payload for i in sequences)
            allowed = {wanted, block(0, track=track).payload} if track in optional else {wanted}
            assert actual in allowed
            assert sum(c.frame_count for c in saved) * 2 == len(actual)
        assert all((root / p).read_bytes() == data for p, data in originals.items())
        first = [(c.chunk_id, c.sha256, c.frame_count) for c in recovered]
        library.recover_session("s")
        assert [(c.chunk_id, c.sha256, c.frame_count) for c in library.chunks("s")] == first
        assert all((root / p).read_bytes() == data for p, data in originals.items())
        health = library.capture_health("s")
        assert health["health_schema_version"] == 2 and health["has_unknown"] is True


WRITE_FAULTS = list(
    product(("audio.pcm", "blocks.jsonl", "descriptor.json"), ("short", "zero", "full", "badfd"))
)
SYNC_FAULTS = list(
    product(("audio.pcm", "blocks.jsonl", "descriptor.json"), ("eio", "badfd", "pending"))
)
FAULTS = [
    (count, "write", name, fault, n + (0 if count == 1 else 26))
    for count in (1, 2)
    for n, (name, fault) in enumerate(WRITE_FAULTS, 1)
] + [
    (count, "sync", name, fault, n + 12 + (0 if count == 1 else 26))
    for count in (1, 2)
    for n, (name, fault) in enumerate(SYNC_FAULTS, 1)
]


class RawFault:
    """Unbuffered write fault adapter: the real write_all still performs its loop."""

    def __init__(self, stream, fault):
        self.stream, self.fault, self.calls = stream, fault, 0

    def __getattr__(self, name):
        return getattr(self.stream, name)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.stream.close()

    def write(self, data):
        self.calls += 1
        if self.fault == "short":
            return self.stream.write(data[:2])
        if self.fault == "zero":
            return 0
        if self.fault == "full" and self.calls == 1:
            return self.stream.write(data[:2])
        raise OSError(
            errno.ENOSPC if self.fault == "full" else errno.EBADF, "synthetic media failure"
        )


def pending_sync_case(root, monkeypatch, tracks, name):
    with Library(root) as library:
        service = RecordingService(
            library, {t: FORMAT for t in ("mic", "system")[:tracks]}, session_id="s", chunk_frames=4
        )
        trace = IOTrace(library.root, monkeypatch, library=library)
        gate = TrackedLock(service._gate)
        monkeypatch.setattr(service, "_gate", gate)
        entered, release = threading.Event(), threading.Event()

        def pending(phase, path, stream):
            assert not gate.owned
            if phase == "before" and path.name == name:
                entered.set()
                assert release.wait(10)

        trace.sync_hook = pending
        try:
            service.start()
            for track in service.formats:
                assert service.submit(block(track=track, epoch=service.epochs[track]))
            assert entered.wait(5)
            with pytest.raises(RecordingError, match="WRITER_ACK_PENDING"):
                service.stop(timeout=0.01)
            assert service.worker_alive and has_active_writer(library.root, "s")
            assert (
                library._db.execute(
                    "SELECT status FROM capture_health_runs WHERE session_id='s'"
                ).fetchone()[0]
                == "OPEN"
            )
            release.set()
            assert service.stop(timeout=30)["frame_count"] == tracks * 4
            for track in service.formats:
                assert (
                    b"".join(
                        (root / c.relative_path / "audio.pcm").read_bytes()
                        for c in library.chunks("s")
                        if c.track_id == track
                    )
                    == block(track=track).payload
                )
            assert not service.worker_alive and not has_active_writer(library.root, "s")
        finally:
            release.set()
            service.join_writer()


@pytest.mark.parametrize(
    "count,operation,name,fault,number",
    FAULTS,
    ids=[f"G17-F-{row[-1]:03}" for row in FAULTS],
)
def test_strict_media_faults_keep_prefix_and_never_ack_pending_handles(
    tmp_path, monkeypatch, count, operation, name, fault, number
):
    if fault == "pending":
        pending_sync_case(tmp_path, monkeypatch, count, name)
        return
    h = Harness(tmp_path, monkeypatch)
    writers, adapters = [], []
    try:
        for track in ("mic", "system")[:count]:
            writer = h.writer(track=track)
            writer.append(block(track=track))
            writers.append(writer)
        original_open = chunks.open_file

        def open_fault(path, mode):
            stream = original_open(path, mode)
            if operation == "write" and path.name == "descriptor.json" and mode == "xb":
                stream = RawFault(stream, fault)
                adapters.append(stream)
                h.io.paths[id(stream)] = path
            return stream

        monkeypatch.setattr(chunks, "open_file", open_fault)
        if operation == "write" and name != "descriptor.json":
            for writer in writers:
                field = "_pcm" if name == "audio.pcm" else "_journal"
                original = getattr(writer, field)
                proxy = RawFault(original, fault)
                h.io.paths[id(proxy)] = h.io.paths[id(original)]
                setattr(writer, field, proxy)
                adapters.append(proxy)
        elif operation == "sync":

            def sync_fault(phase, path, stream):
                if phase == "before" and path.name == name:
                    raise OSError(
                        errno.EIO if fault == "eio" else errno.EBADF, "synthetic sync failure"
                    )

            h.io.sync_hook = sync_fault
        for writer in writers:
            prior = (writer.staging_path / "blocks.jsonl").read_bytes()
            action = (
                writer.seal
                if name == "descriptor.json"
                else lambda writer=writer: writer.append(block(1, track=writer.track_id))
            )
            if fault == "short":
                action()
            else:
                with pytest.raises(OSError) as failure:
                    action()
                wanted_errno = (
                    errno.ENOSPC
                    if fault == "full"
                    else errno.EIO
                    if fault == "eio"
                    else errno.EBADF
                )
                if fault != "zero":
                    assert failure.value.errno == wanted_errno
                assert writer._failed and writer._pcm is None and writer._journal is None
                assert not writer.path.exists()
                assert writer._frames == 4
            path = writer.path if writer.path.exists() else writer.staging_path
            pcm = (path / "audio.pcm").read_bytes()
            expected = block(track=writer.track_id).payload
            if name != "descriptor.json":
                if name == "audio.pcm" and operation == "write" and fault in {"zero", "badfd"}:
                    pass
                elif name == "audio.pcm" and operation == "write" and fault == "full":
                    expected += block(1, track=writer.track_id).payload[:2]
                else:
                    expected += block(1, track=writer.track_id).payload
            assert pcm == expected
            journal = (path / "blocks.jsonl").read_bytes()
            assert journal.startswith(prior)
            if name == "blocks.jsonl" and operation == "write" and fault == "full":
                assert len(journal) == len(prior) + 2
            elif name != "descriptor.json" and (
                fault == "short" or name == "blocks.jsonl" and operation == "sync"
            ):
                assert [
                    json.loads(line)["metadata"]["sequence"] for line in journal.splitlines()
                ] == [0, 1]
            else:
                assert journal == prior
        if fault == "short":
            assert all(adapter.calls > 1 for adapter in adapters)
        assert not has_active_writer(h.root, "s") or fault == "short" and name != "descriptor.json"
    finally:
        h.io.sync_hook = None
        h.close()
