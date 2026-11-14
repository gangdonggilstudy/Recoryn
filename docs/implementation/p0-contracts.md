# P0.1 녹음 코어 구현 계약

상태: 사용자 승인 개발의 첫 배정. 설계 G0는 완료했고 P0 전체 하드웨어 게이트는 아직 열려 있다. 이번 범위는 외부 의존성 없는 Python 녹음 코어와 합성 입력 CLI, 저장·복구 및 독립 테스트다. 실제 WASAPI, PySide6, STT/LLM, 클라우드, GPU와 설치 프로그램은 후속 배정이다. 실제 사용자 음성은 자동으로 녹음하지 않는다.

## 실행 환경과 소유권

Python 3.13에서 개발하고 최소 3.11을 대상으로 표준 라이브러리만 runtime에 사용한다. pytest·Hypothesis·coverage·Ruff·mypy는 개발 의존성이다. 모델 다운로드나 외부 API가 없이 실행되어야 한다. 앱 import와 help는 저장소 생성 같은 부작용도 없어야 한다. 저장 경로는 명시적 인자 또는 사용자 앱 데이터 경로이며 예제는 OS 임시 폴더를 사용한다.

| 배정 | 소유 파일 | 구현 및 자체 시험 |
| --- | --- | --- |
| P00 오케스트레이터 | 패키징, src/recoryn/__init__.py, __main__.py, app/*, cli.py, tests/e2e/*, scripts/*, CI 및 문서 | 통합 서비스·CLI·설치와 최종 검사 |
| P01 아키텍트 | domain/*, jobs/*, tests/unit/test_domain.py, tests/unit/test_jobs.py | 불변 PCM·세션 계약, SQLite Job/Attempt·fence·취소·재시도 |
| P02 오디오 | capture/*, tests/unit/test_capture.py | 제한된 큐, cutoff/drain 제어, 합성 native 포맷 블록 |
| P03 저장 엔지니어 | storage/*, tests/unit/test_storage.py | 청크 journal, 카탈로그, manifest, 복구·삭제와 단일 writer lock |
| P04 독립 QA·보안 | tests/integration/*, tests/property/*, docs/reviews/p0-qa.md | 독립 oracle, 실제 subprocess 종료 복구·포화·원본·기본 무네트워크, 코드 리뷰 |

공용 API 변경은 오케스트레이터가 이 문서를 바꾸고 관련 담당에게 알린 뒤 한다. 다른 소유 파일·Git 인덱스·브랜치를 수정하거나 추가 위임하지 않는다. 각 담당은 API stub만 만들고 끝내지 않고 자체 시험을 통과시킨다.

## Domain 정본 API

`recoryn.domain`에서 아래 타입과 함수를 export한다. 예외는 ValueError를 상속하는 `ValidationError`, `StateConflict`다. dataclass는 frozen을 기본으로 하며 dict 직렬화는 손상·미지원 version을 검증한다.

- `AudioFormat(sample_rate: int, channels: int, sample_type: str = "s16le")`: `frame_bytes` property, `to_dict()`, `from_dict()`. s16le/s24le/s32le/f32le 지원. 범위·타입·길이를 검증한다.
- `PCMBlock(session_id: str, track_id: str, epoch_id: str, sequence: int, format: AudioFormat, frame_count: int, payload: bytes, capture_mono_ns: int | None, arrival_mono_ns: int, device_frame_position: int | None = None, clock_quality: str = "DEVICE_CORRELATED", fragment_index: int = 0, fragment_count: int = 1, flags: tuple[str, ...] = ())`. payload 크기/frame·식별자·정수/시간·fragment를 검증한다. 식별자는 경로로 안전한 제한된 ASCII ID다. `to_metadata()`는 payload를 제외하며 포맷은 포함한다. `from_metadata(metadata, payload)`로 복원한다.
- `SessionState`: CREATED/RECORDING/PAUSED/FINALIZING/FINALIZED/INTERRUPTED. `Session(session_id, state=CREATED, state_version=0)` 및 `transition_session(session, target, expected_version) -> Session`. 설계의 합법 전이만 허용한다.

## Capture 정본 API

- `BoundedCaptureQueue(max_blocks: int, max_bytes: int)`: `offer(block) -> bool`, `get(timeout: float | None = None) -> PCMBlock`, `close()`, `snapshot() -> dict`. slot·bytes 상한과 drop-newest. `get`은 빈 경우 queue.Empty, closed+drained는 EOFError. offer의 callback 경로에서 디스크/AI를 호출하지 않는다. close는 포화 큐의 sentinel에 의존하지 않고 기존 accepted 데이터 drain을 허용한다. 카운터에는 accepted/dropped frames·bytes와 high-water·closed를 포함한다. close 후 offer는 false이지만 privacy-rejected frame을 queue loss에 합산하지 않는다.
- `SyntheticSource(session_id, track_id, epoch_id, format, total_frames, block_frames=480, start_ns=0)`: iterable PCMBlock. 일정한 수학적 테스트 신호, 마지막 짧은 블록, sample rate 기반 정수 시각과 frame position. 하드웨어나 네트워크 접근 없음.
- 큐의 Python lock/GIL은 실시간 보장이 아니다. 단위 시험에서 정확한 frame 회계·close와 포화 경쟁을 검증한다.

## Storage 정본 API

`recoryn.storage`에서 다음을 export한다. 모든 파일은 root 내부의 안전한 경로만 사용하고 미지원 schema는 쓰지 않는다. 링크/reparse point와 경로 이탈을 차단하며 고유 최종 bundle을 덮어쓰지 않는다.

- `ChunkWriter(root: Path, first_block: PCMBlock, chunk_id: str | None = None)`: constructor는 identity/format 설정만 하며 첫 블록도 `append(block)`로 명시적으로 추가한다. `seal() -> ChunkDescriptor`, `abort()`는 staging을 복구 후보로 남긴다.
- `ChunkDescriptor`: session_id/track_id/epoch_id/chunk_id/format/frame_count/byte_count/relative_path/sha256과 블록 범위. `to_dict()/from_dict()`.
- `verify_bundle(path: Path) -> ChunkDescriptor`: schema, raw PCM, journal prefix와 descriptor를 함께 검증한다. journal의 identity/format/offset/frame/sequence/fragment·레코드 및 payload checksum을 검사한다. 크기 제한과 엄격 JSON 파싱을 적용한다.
- `Library(root: Path)`: context manager 또는 close(), create_session(session_id), get_session(session_id) -> Session, list_sessions() -> list[Session], transition(session_id, target, expected_version) -> Session, register_chunk(descriptor), chunks(session_id) -> list[ChunkDescriptor], finalize_session(session_id) -> dict, write_manifest(session_id) -> dict, recover_session(session_id) -> dict, delete_session(session_id) -> dict.
- `Library.record_capture_health(session_id, health: dict)`, `capture_health(session_id) -> dict`: pause/stop 전에 cutoff·트랙별 accepted/dropped frame·정확한 gap·queue watermark를 DB에 기록하고 manifest에 포함한다. health는 JSON에 안전한 제한된 metadata이며 원음이나 비밀을 포함하지 않는다.
- `finalize_session`은 FINALIZING에서 FINALIZED와 고정 원본 목록을 DB에 commit하고 manifest를 projection한다. 반환 dict에는 state/manifest_sync_pending/chunk_count/frame_count를 포함한다. manifest만 실패하면 FINALIZED 유지, pending=true. DB commit 실패면 성공을 반환하지 않는다.
- `recover_session`은 session_id, adopted/recovered/quarantined 개수, warnings, state를 포함한 dict를 반환한다. lock→삭제 의도→bundle/journal 검증→idempotent 카탈로그 반영→manifest 순서다. 실제 중단 상태만 INTERRUPTED로 표시한다. FINALIZED의 고아는 자동 편입하지 않는다. DB 손상·삭제 이력 판정불가는 자동 재등록을 막는다.
- `delete_session`은 최소 journal→DB 삭제 세대→활성 작업/reader 확인→미디어/metadata 정리 순서를 지킨다. tombstone은 보존하고 recover가 부활시키지 않는다. 없던 세션 삭제는 안전하게 구분한다. Library별 단일 writer lock을 context 수명 동안 유지하며 두 프로세스 동시 쓰기를 차단한다.
- 라이브러리 SQLite user_version=1은 storage가 소유한다. 세션·청크·상태 이벤트·generation·삭제 정보가 transaction으로 관리된다. JobStore는 같은 DB에 자기 테이블을 추가하고 user_version을 바꾸지 않는다. `WAL + synchronous=FULL`을 사용하되 물리 전원 장애 보장은 하지 않는다.

## Jobs 정본 API

`JobStore(db_path: Path)`는 별도 connection으로 library.sqlite의 jobs/attempts/events 테이블을 관리한다. session 테이블을 소유하지 않는다. `create(kind, input_key, job_id=None)`, `get(job_id)`, `claim(job_id, owner)`, `cancel(job_id)`, `complete(job_id, attempt_id, fence, result_ref)`, `fail(job_id, attempt_id, fence, error_code, retryable=False, outcome_known=True)`, `recover_abandoned()`를 제공한다. 반환은 frozen JobRecord/AttemptRecord이며 상태 enum은 JobState/AttemptState로 export한다. 실제 AI 런타임·원격 전송은 구현하지 않는다.

claim은 job_id/attempt_id/fence를 포함한 AttemptRecord를 반환하고 게시·취소를 같은 DB 직렬화 경계로 판정한다. cancel은 실행 전 즉시 CANCELLED, 실행 중 fence 회수와 CANCEL_REQUESTED, 원격 결과 불명은 BLOCKED(REMOTE_UNKNOWN) 및 Attempt UNKNOWN으로 둔다. 재시도는 유한 횟수 내 새 attempt다. 입력 key의 활성/성공 중복은 재사용한다. close/context manager 지원. recover_abandoned는 실행 중 owner가 없는 단독 재시작 복구에서만 명시 호출하며 이전 attempt를 재사용하지 않는다.

## 통합과 수락

P00은 큐 소비 writer thread를 앱 서비스에 두고, track/epoch별 writer를 일정 frame 경계마다 봉인·카탈로그 반영한다. 원본 writer에 AI를 연결하지 않는다. pause는 모든 source gate 중단과 drain/seal ack 후 PAUSED이며 resume은 새 epoch다. stop은 source close/drain→seal→DB finalize이며 manifest pending을 따로 보여준다. 저장 오류는 INTERRUPTED와 보존 결과로 노출한다.

CLI는 명시적으로 `simulate`, `list`, `inspect`, `recover`, `export`를 제공한다. simulate는 마이크·시스템 두 합성 트랙을 독립 포맷으로 만들고 원본 청크·manifest를 저장한다. export는 검증한 원본 s16le를 트랙별 WAV로 파생 출력하며 기존 파일 덮어쓰기와 unsafe path를 거절한다. 이 CLI는 실장치 녹음 앱이라고 표시하지 않는다.

필수 실행: PCM/시간·상태 전이, bounded queue 포화와 close, journal 중복·torn write·prefix, actual subprocess crash 및 반복 복구, manifest-only 실패, 삭제 후 재복구 차단, Job 취소/완료 양 순서와 stale fence, 합성 두 트랙 end-to-end와 WAV sample oracle. pytest·Hypothesis 및 coverage, Ruff와 mypy를 실행한다. P0 전체와 W01~W05/G3/G4는 이번 증거로 통과시키지 않는다.

커버리지 게이트는 domain/capture/jobs/storage 각각 line 95%와 branch 90%, 전체 line 85%와 branch 80%다. `scripts/check_coverage.py`가 실제 JSON의 두 비율을 분리 검사한다. subprocess 계측을 켜되 강제 종료 자식의 미수집 가능성은 실제 frame·byte 복구 oracle과 구분한다. 실행 중 source를 바꾸면 최종 측정을 다시 수행한다. 현재 milestone에 없는 security/provider/UI 패키지의 검증을 대신하지 않는다.
