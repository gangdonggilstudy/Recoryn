# Recoryn 제품 구현 계약

상태: 사용자 지시(구현 완료까지 진행)에 따른 활성 구현 계약. P0.1의 불변 원본·복구 계약을 유지한다. 구현과 실제 장치·모델·클라우드·배포 인증의 검증 상태를 별도로 기록한다. 버전은 구현과 독립 검토 후 결정하며 미완료 기능을 완료로 표기하지 않는다.

## 진행 단위

1. B1: Windows 캡처, 오디오 파생 처리, 전사·요약 revision 저장, AI 어댑터, 보안 gateway 기반.
2. B2: PySide6 UI와 앱 서비스 통합, 실제 장치 선택·녹음 조작, AI 실행·편집·검색·근거·재생·내보내기.
3. B3: 모델 설치·GPU·작업 재개·다운로드, 진단·보존, 선택 화자 구분, 패키징·설치·CI·라이선스 목록.
4. B4: 독립 교차 검토, 장애·경쟁·오프라인 E2E, 설치물 smoke 및 미검증 항목 보고. 기능 누락은 다음 단계로 숨기지 않고 구현 추적표에 유지한다.

## 공통 경계

- 기존 domain/__init__.py, jobs/__init__.py, storage/*, app/recording.py는 명시적 소유자만 수정한다. 새 기능은 하위 모듈로 추가한다. root가 CLI·UI·패키지 설정·배포를 통합한다.
- 선택 패키지는 import-time에 로드하지 않는다. 장치 열기·모델 다운로드·네트워크·vault 쓰기는 생성자/import의 부작용으로 수행하지 않는다.
- PCMBlock, AudioFormat, RecordingService의 기존 API는 보존한다. 원본 청크는 변환·전사·편집으로 변경하지 않는다.
- 예외의 사용자 표시에는 안전한 code만 사용하고 provider 응답·요청·토큰·임의 예외 repr를 출력하지 않는다.
- 모든 새 코드는 타입·lint·의미 있는 실패 시험을 포함한다. 기존 coverage 목표를 낮추거나 파일을 임의 제외하지 않는다. Windows FFI의 실제 장치 분기는 계약 시험과 실장비 NOT_RUN을 분리한다.

## B11: 내용 저장과 작업 실행 (w5:p2)

소유: src/recoryn/content/*, src/recoryn/jobs/__init__.py, src/recoryn/jobs/runner.py, tests/unit/test_content.py, tests/unit/test_runner.py, tests/unit/test_jobs.py. domain 및 storage 기존 파일은 읽기만 한다.

`recoryn.content` 공개 계약:

```python
@dataclass(frozen=True)
class Segment:
    segment_id: str
    start_ms: int
    end_ms: int
    text: str
    speaker: str | None = None
    provenance: str = "audio"  # audio/user_assertion/unresolved

@dataclass(frozen=True)
class Claim:
    text: str
    segment_ids: tuple[str, ...]
    status: str = "uncertain"  # model output is not human-verified support

ContentStore(library: Library)
create_transcript(session_id, segments: Sequence[Segment], *, kind="corrected",
                  parent_revision_id=None, expected_active=None) -> str
transcript(revision_id) -> dict  # revision_id/session_id/kind/segments/parent_revision_id
active_transcript(session_id) -> dict | None
edit_segment(session_id, revision_id, segment_id, text, *, expected_active) -> str
search(session_id, query) -> list[Segment]
create_summary(session_id, transcript_revision_id, claims: Sequence[Claim], *,
               template="meeting", expected_transcript=None, expected_summary=None) -> str
summary(revision_id) -> dict
active_summary(session_id) -> dict | None
export_transcript(revision_id, format: str) -> str  # txt/srt/vtt/json
```

반환 사전의 segments/claims는 JSON 호환 사전 배열이다. 기대값 None은 미선택을 뜻하며 무조건 덮어쓰기가 아니다. CAS 불일치에도 revision은 후보로 저장하고 active는 변경하지 않는다. 편집은 새 revision과 user_assertion으로 기록하고 기존 audio 근거를 자동 상속하지 않는다. source revision과 segment는 불변이며 summary는 선택된 transcript와의 stale 여부를 반환한다. 문장부호 편집도 발화의 자동 검증으로 취급하지 않는다.

모든 DB 쓰기는 library.sqlite의 별도 테이블과 SQLite 직렬화 경계를 사용한다. 삭제 intent와 tombstone, 현재 세션 상태를 확인한다. Job 결과 게시 API를 추가할 때 revision/active 선택/Job·Attempt 완료/event를 동일 transaction으로 수행한다. 기존 JobStore.complete를 호출한 뒤 따로 revision을 게시하는 방식은 금지한다. 독립 Job 취소·늦은 fence·편집 경쟁·삭제와의 양순서 시험을 포함한다. runner는 bounded queue, 협력 취소, 명시 재시작·중단과 부분 저장을 갖추며 녹음 경로에서 inference를 호출하지 않는다. 정확한 runner 공개 API는 작성자가 먼저 제안하고 root가 통합한다.

## B12: Windows 오디오와 파생 처리 (w5:p3)

B11 reader 수명 확장: job_local_readers(job_id,attempt_id,fence,active)와 reader_started/reader_finished/local_reader_active를 사용한다. 실제 task 직전 active=1, 반환·예외 후 동일 attempt 영속 ACK로 0을 기록한다. 논리 terminal도 active=1이면 삭제를 차단한다. session-bound BLOCKED + 명시 active=0만 논리 UNKNOWN을 유지한 채 원본 삭제를 허용한다. 미바인딩·미상 legacy는 fail-closed다. 재시작에서 reader 해제는 recover_abandoned(coordinator_exclusive=True)의 단일 재시작 coordinator 증거가 필요하다. 부모 AI worker는 원본 저장과 분리하며 자식은 파생 파일만 읽는다.

B11 추가 확정 API: BoundedRunner(jobs,capacity=16,workers=1,owner='local')의 start/submit/cancel/stop/running/snapshot. task는 (AttemptRecord, Event)->str다. JobStore.complete_with는 callback을 동일 SQLite transaction에서 호출하며 재진입·외부 I/O를 금지한다. ContentStore.publish_transcript/publish_summary는 fence·삭제와 revision·Job 완료를 원자 게시한다. complete=False는 비활성 부분 후보만 보존한다. 별도 streaming_transcription Job에서 고정 snapshot coverage 전체 성공+kind=draft는 Job 성공을 허용하되 revision.complete=False를 유지한다.

B11 데이터 확장: Segment의 track_id=None/timing_quality='model'을 보존한다. coverage는 schema_version=1, planned/completed/failed/missing의 유일·서로소 분할과 source_ranges를 갖는다. audio_revision_id는 봉인 청크 snapshot SHA256다. list_revisions와 명시 select_transcript/select_summary는 CAS·세션 검증·감사 이력을 유지한다. JobStore.bind_session(job_id,session_id)는 불변 바인딩이며 list_for_session으로 재시작 후 상태·취소를 복원한다. 기존 미바인딩 active Job은 삭제를 보수적으로 차단한다.

### B12 소유 범위

소유: src/recoryn/capture/wasapi.py, src/recoryn/capture/devices.py, src/recoryn/audio/*, tests/unit/test_wasapi.py, tests/unit/test_audio.py. 기존 capture queue/synthetic와 공용 파일은 읽기만 한다.

```python
@dataclass(frozen=True)
class DeviceInfo:
    device_id: str
    name: str
    flow: str  # capture/render
    default: bool

list_devices() -> list[DeviceInfo]  # read-only enumeration; never starts capture
probe_device(device_id: str, *, loopback=False) -> AudioFormat
WasapiSource(device_id: str, *, loopback=False)
# source construction has no device-open side effect
source.start(session_id: str, track_id: str, epoch_id: str,
             submit: Callable[[PCMBlock], bool],
             on_health: Callable[[dict], None]) -> AudioFormat
source.stop(timeout: float = 5.0) -> None
source.running: bool
```

start가 worker 내 COM 초기화·기본 mix format 확인·실행을 수행하고 반환 전 ready/error를 확인한다. format은 probe 결과와 다르면 시작을 실패시키고 재선택을 요구한다. stop은 callback 종료와 장치 해제 ack를 기다린다. timeout은 완료가 아니다. 분리·timestamp error·불연속·silent packet·장치 위치·100ns QPC→ns를 정확히 보고한다. timestamp 오류는 capture_mono_ns=None으로 유지한다. COM 인터페이스의 ABI는 Microsoft 정본을 확인하고 명시적 장치 시험 전 experimental로 표시한다. 편의용 soundcard를 정밀 native timestamp와 혼동하지 않는다. import/테스트에서 실제 장치를 열지 않는다. fake low-level backend 주입으로 의미 있는 계약 시험을 구성한다.

audio는 PCM→float, mono downmix, 리샘플링, meter, 에너지 기반 VAD, 다중 시계 정렬·drift 추정과 source mapping을 제공한다. 선택 scipy/numpy 사용은 root에 보고한다. 간단한 선형 보간을 고품질 bandlimited resampling으로 주장하지 않는다. 공개 함수의 구체 API를 먼저 root에 보고한다. 시간 gap·epoch를 결합하지 않으며 원본을 수정하지 않는다.

## B13: AI 제공업체 (w5:p4)

소유: src/recoryn/providers/*, src/recoryn/transcription/*, src/recoryn/summarization/*, tests/unit/test_providers.py, tests/contract/*, docs/implementation/provider-matrix.md. domain/providers 등 공용 파일을 만들지 않는다.

providers/contracts.py에 frozen DTO를 정의하고 각 package에서 공개한다. 사용자 입력에는 provider_id/model/언어/실행위치/timeout/취소/진행 정보가 필요하다. local FasterWhisper는 명시적 로컬 모델 디렉터리만 받고(관리 설치가 아닌 디렉터리는 validation S04의 사용자 지정 모델 예외: 사용자 책임 확인, 실행 bytes 고정과 실행 직전 digest 재검사, G-P13) local_files_only=True, CPU 또는 GPU 명시 선택, 패키지 미설치·모델 미설치·OOM은 안전한 capability/resource 오류로 표시한다. 모델명으로 자동 다운로드하지 않는다.

요약 결과는 content.Claim으로 변환 가능해야 하며 고정 transcript revision 및 segment ID를 유지한다. 긴 문서는 겹치는 문맥·분할 처리·진행·취소·부분 결과·최종 합성을 구현한다. 모델이 반환한 존재하지 않는 reference를 거부하고 reference 존재를 의미 검증과 구별한다. 회의·강의·핵심·결정·할 일 템플릿을 제공한다.

클라우드 STT와 요약은 독립 어댑터다. OpenAI는 STT+요약, Anthropic은 text요약, Gemini는 지원 확인된 audio/text만 구현한다. 기능 미지원은 명시 차단한다. HTTP는 B14 Gateway만 사용하고 SDK 직접 egress 금지. 응답 파싱은 고정 fixture와 계약 시험으로 확인하며 실제 계정·최신 모델 호환성은 별도 NOT_RUN이다. 모델 ID는 사용자 설정이고 고정 유효 모델을 추측하지 않는다.

Gateway 의존 API: `gateway.request(provider_id, endpoint, data_type, body: bytes, *, headers: dict[str,str] | None = None, reservation_id: str | None = None, cancel: threading.Event | None = None) -> bytes`. 원격 body는 모든 콘텐츠가 gateway 보호 대상이다. local Ollama도 이 경로를 쓰며 명시적 loopback 접근·로컬 처리 위치 검증이 필요하다. local_only 모델 확인이 안 되면 차단하고 cloud 모델을 loopback이라는 이유로 허용하지 않는다. 어댑터는 가능한 경우 fake Gateway를 주입받는다.

provider capability/error DTO 세부 API는 root에 먼저 보고한다. API 정본·버전·응답 한도·SDK retry 비활성·지원 범위는 provider-matrix.md에 기록한다.

## B14: 보안 gateway·vault·비용 (w5:p5)

소유: src/recoryn/security/*, src/recoryn/diagnostics/*, tests/unit/test_security.py, tests/unit/test_diagnostics.py, tests/integration/test_gateway.py. 기존 tests/integration 파일과 저장 모듈은 읽기만 한다.

B14U 추가 배정: ui/privacy.py와 tests/ui/test_privacy_ui.py. PrivacyPanel(consents, ledger, vault, *, gateway=None)의 provider_config(kind), execution_context(kind,cancel), gateway_for(session_id), config_key(kind), set_local_attestation(attestation)을 root가 사용한다. kind는 stt/summary다. STT/요약 독립 설정과 exact endpoint/data type별 기본 거부·허용·철회, endpoint별 vault reference, USD 예산·요청 상한·UNKNOWN 표시와 명시 정산을 제공한다. 클라우드 요청 상한 0은 차단한다. 생성 시 vault 접근·전송하지 않는다. local Ollama attestation은 root 소유 프로세스·모델 검증에서만 주입한다.

```python
ConsentStore(db_path: Path)
grant(provider_id: str, endpoint: str, data_type: str) -> str
revoke(provider_id: str, endpoint: str, data_type: str) -> None
allowed(provider_id: str, endpoint: str, data_type: str) -> bool
# all grants invalid on fresh application launch; fail closed after restore

CredentialVault()  # Windows Credential Manager ctypes, no fallback plaintext
set(provider_id: str, secret: str) -> None
get(provider_id: str) -> str | None
delete(provider_id: str) -> None

CostLedger(db_path: Path)
reserve(provider_id: str, request_id: str, amount_microunits: int,
        limit_microunits: int) -> str
mark_unknown(reservation_id: str) -> None
settle(reservation_id: str, actual_microunits: int) -> None
release(reservation_id: str) -> None  # only provably unsent reservations
snapshot(provider_id: str) -> dict  # confirmed/reserved/unknown_exposure/available

Gateway(consents: ConsentStore, *, ledger=None, transport=None)
request(provider_id, endpoint, data_type, body: bytes, *, headers=None,
        reservation_id=None, cancel=None) -> bytes
```

재부팅 후 owned Ollama 수명 계약 확장: `LocalModelAttestation`은 기존 필드에 선택 `lifetime_guard: Callable[[], AbstractContextManager[None]] | None`를 추가하며 repr·동등성 비교에서 제외한다. `execution_guard()`는 TTL과 managed owner의 고정 세대·프로세스/Job listener·시작 시 검증한 파일 identity를 검사하고 한 전송 단위 동안 owner lock을 유지한다. hook 없는 static proof는 신뢰된 호출자의 기존 계약/fixture와 호환한다. 이 DTO가 임의 외부 daemon의 무전송이나 바이너리 진위를 인증하는 것은 아니다.

`Gateway(..., dispatch_guard: Callable[[SendPermit], AbstractContextManager[None]] | None = None)`는 고정 실행 계획의 선택 수명 guard를 받고 `for_session()`에도 보존한다. 동의 coordinator 안의 open 직전, 각 write와 비용 UNKNOWN 전환 직전, 최종 응답 반환 직전에 적용한다. lock 순서는 consent → ledger → owner이며 owner가 consent를 역호출하지 않는다. PrivacyPanel은 GUI에서 선택한 proof/endpoint/provider/data type을 고정하고 해당 proof의 guard를 전달한다. 설정 변경·owner 재시작으로 예전 gateway를 새 proof에 연결하지 않는다. 첫 write 전 거부는 미송신/known이며 이미 handoff한 요청은 UNKNOWN 의미를 유지한다.

`ManagedOllama(startup_timeout=10).start(executable, models, model, *, cancel=None)`는 파일 검증 후 suspended 프로세스를 private kill-on-close Windows Job에 할당하고 시작한다. 새 프로세스 또는 동일 private Job의 descendant가 정확한 loopback 포트에서 listen함을 확인한 뒤 proof를 반환한다. Windows venv launcher의 자식 listener도 소유 Job 관계로 확인한다. `attestation()`은 현재 proof를 재검사하고 `close()`는 먼저 같은 owner lock에서 revoke한 뒤 Job 전체 종료·root process ACK를 확인한다. 실패 시 proof를 복원하지 않고 cleanup 재시도용 handle을 보존한다. 모델 hash 검증은 시작 시 수행하며 각 handoff에는 파일 dev/ino/size/mtime/ctime identity를 재검사한다. 같은 사용자 권한의 악성 동시 변경에 대한 OS sandbox 보장은 하지 않는다. 실제 Ollama·모델·후속 트래픽 관측은 별도 게이트다.

시간 범위를 갖는 consent·execution generation과 전송 직전 SendPermit 직렬화 경계를 구현한다. provider+정확한 origin/endpoint+data type이 일치해야 한다. 기본 DNS 이전 차단, redirect/proxy/비HTTPS 원격 차단, 요청·응답 크기 상한과 timeout, 자동 retry 없음. 철회가 commit된 뒤 새 write 없음. 이미 handoff한 bytes는 되돌릴 수 없다고 구분한다. transport는 low-level connection/write를 주입할 수 있어 barrier로 철회·삭제 경계를 검사할 수 있어야 한다. session deletion hook/permit session binding 세부 API는 root에 먼저 제안한다.

금액은 integer microunits, 재시작 영속·동시 예약·idempotency·UNKNOWN 우선. 세션 삭제와 독립 ledger다. 손상/rollback·불명 가격이면 strict 모드 dispatch 차단. 실제 청구 통화와 단위는 UI에서 명시하며 추정 단가를 사실로 표시하지 않는다.

diagnostics는 whitelist metadata와 secret canary 가림, 지원 번들에 원본/텍스트/키 제외를 기본으로 한다. vault 실제 write/read 테스트에는 실키 대신 전용 테스트 namespace와 정리 절차가 필요하며 사용자 기존 키를 변경하지 않는다.

## B10: 오케스트레이터 통합

소유: pyproject.toml, requirements 및 lock, README, AGENTS, docs/collaboration/*, 공용 구현 문서, src/recoryn/app/*, src/recoryn/ui/*, src/recoryn/models/*, src/recoryn/cli.py, tests/ui/*, tests/e2e/*, tests/unit/test_models.py, scripts/*, packaging/*, CI. 작업자가 제안한 공개 API를 검토하고 변경을 각 작성자에게 배정한다. 모든 기능에 작성자 외 검토자를 재배정한다. 리뷰는 docs/reviews/product-*.md의 각 지정 파일에만 작성한다.

## 완료 추적

전체 설계 범위의 추적표·검증 결과·미실행 게이트는 후속 product-results.md에서 관리한다. 구현 완료를 실제 장치8시간·음성 품질·모든 라이선스 법률 판정·서명 인증 완료로 확장하지 않는다. 사용자 동의·키·장비·corpus 없이 가능한 코드·합성·패키지 검증은 계속 수행하고 외부 조건은 분리해 명시한다.
