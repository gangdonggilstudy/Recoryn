# D01 수석 소프트웨어 아키텍트 검토

작성일: 2026-11-14. 배정: D01. 상태: **통합 검토용 설계 제안 / 구현·실행 검증 전**.

근거는 [설계 입력](../design-input-v1.md), [작업 규칙](../collaboration/workflow.md), [배정표](../collaboration/assignments.md), [온보딩](../collaboration/onboarding.md), [저장소 규칙](../../AGENTS.md)이다. 검토 시작 시 `architecture-v1.md`, `validation-plan.md` 및 VoiceLocal 소스는 없었다. 이 문서는 현재 소스 분석, 마이그레이션 구현, Windows 장치 시험, 성능 측정의 결과가 아니다. 공용 계약 채택과 다른 리뷰와의 충돌 해결은 D00의 책임이다.

## 1. 권한과 요구사항 추적

**사용자 원칙**은 변경하지 않는다. 아래의 구체적인 상태명, 테이블, 프로토콜, 기본 정책은 모두 **D01 제안**이며 사용자 확정 사항과 구분한다.

| 사용자 원칙 | D01 계약 제안 | 주요 수락 기준 |
| --- | --- | --- |
| R01: STT·LLM 실패에도 녹음 지속 | 캡처 저장과 AI 실행 경로 격리, AI 큐 역압을 캡처에 전달하지 않음 | A01, A02 |
| R02: 로컬 기본, 제공업체·데이터 종류별 동의 | 모든 외부 어댑터에 전송 직전 권한 검사 포트 적용 | A09 |
| R03: 마이크·시스템 원본 분리 및 불변 | 봉인된 원본의 덮어쓰기 금지, 파생 산출물과 사용자 삭제 명령 분리 | A03, A10 |
| R04: 재개·취소·관측, 부분 결과 보존 | Session/Job/Attempt 분리, 체크포인트 및 게시 fencing | A04~A08, A11 |
| R05: Credential Manager 비밀 저장 | 계약에는 credential 참조만 전달, 내용은 DB·파일·로그에 금지 | A09 |
| R06: 선택적 제공업체·모델, 기능 검사 | 버전 있는 capability 및 요청/응답 DTO, 미지원 기능 사전 차단 | A12 |

## 2. 의존성과 실행 경계

소스 디렉터리명은 입력 제안을 따른다. 의존성 방향과 런타임 호출 방향을 구분한다.

```text
ui ──────────────> app ──────────────> domain
capture/audio/transcription/summarization/jobs/storage/security
    └── app이 정의한 포트와 domain 값 형식을 구현/사용
composition root ──> 구현체를 생성하여 app에 주입
```

- `domain`: Session, Track, CaptureEpoch, AudioRevision, Job, Attempt, TranscriptRevision, SummaryRevision, 삭제 상태와 전이 규칙. Qt, SQLite, 파일 시스템, 모델, 네트워크, 전역 시계에 의존하지 않는다. ID·시간·해시·버전은 명시적 값 형식으로 전달한다.
- `app`: 명령, 조회, 트랜잭션 범위, 권한 검사, 워커 예약, 게시와 충돌 처리. `SessionRepository`, `UnitOfWork`, `ArtifactStore`, `CapturePort`, `STTPort`, `SummaryPort`, `ConsentPort`, `SecretStore`, `Clock` 등의 포트를 소유한다.
- `storage`, `security`: 포트 구현. 다른 모듈은 SQL·경로·자격증명 원문을 직접 다루지 않는다. 원본 저장 포트와 파생 산출물 포트를 분리하여 추론 워커에 원본 수정 권한을 주지 않는다.
- `capture`: 장치 콜백에서 타임스탬프 블록을 제한된 원본 쓰기 큐에 전달한다. 콜백은 SQL, 모델 추론, 네트워크, 리샘플링, 동기 UI 호출, 장시간 flush를 수행하지 않는다. 별도 원본 writer가 청크를 봉인하고 비동기로 카탈로그 반영을 요청한다.
- `audio`: 확정 청크의 정렬·리샘플링·믹스 등 파생 처리. 원본과 다른 artifact ID를 만든다. D02가 시간축·포맷·드리프트 세부 계약을 확정한다.
- `transcription`, `summarization`: 입력 스냅샷을 읽고 결과/체크포인트를 생성하는 엔진과 어댑터. Session의 녹음 상태나 현재 전사 포인터를 직접 바꾸지 않는다.
- `jobs`: app의 작업 정책을 실행하는 스케줄러. SQLite 게시와 재시도 결정을 app에 요청한다. GPU/CPU 자원 정책은 캡처 자원을 먼저 보호한다. 무거운 AI는 종료 가능한 별도 프로세스로 격리하는 안을 권고하며 실제 프로세스/IPC 방식은 미결정이다.
- `ui`: 명령 제출과 조회 DTO 렌더링만 수행한다. 위젯이 워커·DB 연결·파일 writer를 소유하지 않는다. UI 종료/멈춤과 녹음 종료의 관계는 명시적 종료 명령으로 처리하며, 백그라운드 서비스 생존은 별도 제품 결정이다.
- `diagnostics`: 가림 처리된 구조화 관측 정보. 전사·원본·프롬프트·비밀을 기본 로그에서 제외한다. 도메인의 의존 대상이 되지 않는다.

의존성 검사는 구현 시 import 경계로 검증한다. DI 프레임워크나 특정 Qt/ML API가 필요한 기능을 이미 지원한다고 가정하지 않는다.

### 명령·조회·이벤트 계약

명령 공통 필드는 `contract_version`, `command_id`, `session_id`, `expected_entity_version`, `payload`이다. 동일 `command_id`와 동일 payload의 재호출은 이전 결과를 반환한다. 같은 ID에 다른 payload면 `IDEMPOTENCY_CONFLICT`다. 중복 판정 범위는 프로젝트와 명령 종류를 포함한다.

제안 명령은 `CreateSession`, `StartCapture`, `PauseCapture`, `ResumeCapture`, `StopCapture`, `EnqueueJob`, `RequestCancel`, `ResumeJob`, `PublishTranscript`, `SaveTranscriptEdit`, `SelectRevision`, `DeleteSession`, `ExportSnapshot`이다. 녹음 정지는 AI 취소와 다르다. 취소는 삭제가 아니다.

응답은 `accepted/applied/conflict/rejected`, 엔티티 버전, 결과 ID, 안정된 오류 코드, 복구 행동을 포함한다. DB에 수락 기록을 남기기 전에 성공 응답하지 않는다. 캡처 시작 명령의 수락과 실제 장치 시작 확인을 구분하고, `RECORDING` 표시는 엔진 시작 확인 후 전이한다. 시작 중에는 조회의 `pending_command`를 표시한다.

이벤트는 `event_id`, `session_id`, `entity_id`, `entity_version`, `kind`, `occurred_at`, `schema_version`을 가진다. DB 변경과 outbox 기록을 같은 트랜잭션에 쓴 뒤 전달한다. 소비자는 중복을 허용하고 ID/버전으로 걸러낸다. 이벤트 누락·재연결 시 조회로 복구하며 이벤트만으로 상태를 재구성하지 않는다. 초 단위 진행률·미터를 모두 영속 이벤트로 쓰지 않는다.

### 엔진·제공업체 포트의 DTO

아래는 Recoryn 내부에서 요구할 계약이며 특정 라이브러리의 기존 API 시그니처가 아니다. 어댑터가 반환하는 capability는 버전·모델 선택에 종속되며, 확인되지 않은 기능은 지원하지 않는 것으로 처리한다.

| 포트 | 입력/출력의 필수 의미 |
| --- | --- |
| `describe_capabilities()` | adapter/contract 버전, local/external 및 수신자, 지원 작업·언어·포맷, 입력 길이/크기·컨텍스트 제한, streaming/checkpoint/cancel/idempotency/status-query 지원 여부, 비용 추정 가능 여부와 근거 |
| `transcribe(request, context)` | 요청: 봉인된 AudioRevision 또는 확정 청크 집합 ID/hash, track/epoch 범위, timeline 버전, 언어·모델·설정, 검증된 checkpoint. 결과: revision 후보, segment·시간·출처·coverage·gap·완전성, 실제 사용량과 불확실성 |
| `summarize(request, context)` | 요청: 고정 전사 revision/hash와 분할 범위, 근거 segment 참조, 요약 유형·템플릿·설정, 검증된 checkpoint. 결과: summary 후보, 근거 링크, coverage·누락·완전성, 사용량과 불확실성 |
| `ExecutionContext` | job/attempt/fence, deadline, cancel 신호, 결과 sink, credential 참조와 전송 권한 범위. 비밀 값과 제어 권한은 산출물 DTO에 복사하지 않음 |
| `progress/checkpoint/result` | 진행은 관측값, checkpoint는 검증된 처리 단위, result는 게시 전 후보. 엔진이 현재 포인터를 갱신하지 않음 |

외부 전송 직전에 제공업체·endpoint·데이터 종류·동의 세대를 재검사한다. 초기 예약 시 동의 확인만으로 오래 대기한 작업을 전송하지 않는다. 동의 철회는 신규 전송 차단과 진행 요청 취소 시도로 처리하며 이미 전송한 내용의 회수를 뜻하지 않는다. 모델 다운로드 권한은 음성/전사 전송 동의와 별개다. 입력 제한 초과는 분할 계획 또는 명시적 오류로 처리하고 조용한 잘림을 금지한다. 비용 추정 불가는 0원과 구분한다.

## 3. Session과 AI 작업의 별도 상태 머신

### 3.1 녹음 Session

`capture_state`는 녹음 수명만 나타낸다. 전사·요약 성공 여부를 포함하지 않는다. `lifecycle=ACTIVE/DELETE_REQUESTED/DELETING/DELETED`와 미디어 무결성은 별도 축이다.

| 전이 | 선행 조건과 효과 |
| --- | --- |
| `CREATED → RECORDING` | 장치 시작 확인, 새 CaptureEpoch 생성, 시작 명령 결과 영속화 |
| `CREATED → FAILED` | 시작 실패. 기존 미디어 없음 여부를 명시하며 같은 세션에서 명시적 재시작 허용 |
| `FAILED → RECORDING` | 장치·저장소 조건 재검사와 사용자 재시작. 새 epoch 생성 |
| `RECORDING → PAUSED` | 새 블록 유입 중단 확인과 현재 epoch 청크 봉인. 일시정지 구간 기록 |
| `PAUSED → RECORDING` | 새 epoch·시계 앵커로 시작. 이전 구간에 이어 붙여 연속 녹음으로 위장하지 않음 |
| `RECORDING/PAUSED/CREATED → FINALIZING` | StopCapture 수락. 캡처 유입 중단 후 writer drain 및 봉인 시작 |
| `FINALIZING → CLOSED` | 원본 목록, 유실·공백, 무결성 결과와 최종 AudioRevision 게시. AI 성공은 조건 아님 |
| `RECORDING/PAUSED/FINALIZING → INTERRUPTED` | 프로세스 재시작 시 이전 소유자 상실, 장치·저장 실패 등. 마지막 확인 시점과 중단 원인 기록 |
| `INTERRUPTED → PAUSED` | 복구 검증 후 사용자가 녹음 재개를 선택. 이후 ResumeCapture로 새 epoch 시작 |
| `INTERRUPTED → FINALIZING` | 복구 검증 후 사용자가 현재 자료로 종료 선택 |

`CLOSED`는 녹음 수명 종료다. 추가 녹음은 새 Session을 기본으로 제안한다. `FINALIZING` 실패는 오류와 재시도 가능한 단계 체크포인트를 남기며 무한 대기를 성공으로 표시하지 않는다. 정상 종료 시 자료가 없으면 `CLOSED + media_status=EMPTY`도 허용한다.

장치 장애 시 한 트랙만 계속할지 전체 중단할지는 D02/D00 결정이다. 어떤 경우든 트랙별 누락 구간과 원인을 기록한다. AI 예외·GPU 부족·클라우드 timeout은 Session 전이 원인이 아니다. 실제 저장 불가능은 R01의 AI 격리와 별개인 녹음 장애로 사용자에게 즉시 노출한다.

`media_status=UNVERIFIED/VERIFIED/DEGRADED/EMPTY/UNAVAILABLE`는 게시된 원본 목록 검사에서 계산한다. `CLOSED`만으로 무손실·정상·전원 장애 내구성을 뜻하지 않는다. 확인된 유실은 `DEGRADED`; 모든 매체를 읽을 수 없으면 `UNAVAILABLE`이다.

### 3.2 Job과 Attempt

Job 종류는 적어도 `LIVE_STT`, `FINAL_STT`, `ALIGN`, `MIX`, `SUMMARY`, `EXPORT`, `INTEGRITY_CHECK`로 구분한다. 원본 봉인과 삭제 처리는 취소 가능한 AI Job에 종속시키지 않는다.

| Job 상태/전이 | 의미 |
| --- | --- |
| `QUEUED → BLOCKED/RUNNING` | 입력·권한·모델·자원 조건을 검사. BLOCKED에는 이유와 해제 조건 필수 |
| `BLOCKED → QUEUED` | 실행 의도가 남아 있는 Job만 조건 충족 재확인. 동의나 CPU fallback을 임의로 승인하지 않음. `CANCEL_UNCONFIRMED`는 제외 |
| `RUNNING → SUCCEEDED` | 검증된 결과와 완료 상태의 DB 게시가 한 트랜잭션으로 성공 |
| `RUNNING → BACKOFF → QUEUED` | 분류상 재시도 가능한 실패, 횟수·시간 예산 내 새 attempt 예약 |
| `RUNNING → FAILED` | 비재시도 실패 또는 예산 소진. 기존 결과/체크포인트 유지 |
| `QUEUED/BLOCKED/BACKOFF → CANCELLED` | 활성 실행 없이 취소. 예약 제거와 상태 기록을 한 트랜잭션으로 수행 |
| `RUNNING → CANCEL_REQUESTED → CANCELLED` | 게시 권한 회수 후 협력적 중단. 필요한 경우 해당 AI 프로세스만 종료 |
| `CANCEL_REQUESTED → BLOCKED` | 원격 중단 여부 불명 등으로 정리가 끝나지 않음. 이유 `CANCEL_UNCONFIRMED`; 자동 재실행 금지 |
| `BLOCKED(CANCEL_UNCONFIRMED) → CANCELLED` | 로컬 실행/게시 권한 정리 확인. 원격 실행·과금 불확실성은 별도 표시하고 보존 |

`SUCCEEDED/FAILED/CANCELLED`는 해당 Job의 종료 상태다. 사용자의 ResumeJob은 `resume_of_job_id`를 가진 새 Job을 생성한다. 자동 재시도는 동일 Job 아래 새 Attempt를 추가한다. 이미 성공한 결과를 교체하려는 재실행은 명시적 새 run이며 dedupe 범위를 새로 부여한다.

Attempt에는 `attempt_id`, `job_id`, `attempt_no`, `state`, `worker_owner`, `fence_token`, `lease_deadline`, 시작/종료 시각, 오류 분류, 제공업체 요청 참조, 사용량·비용 확인 상태를 기록한다. 상태는 `RUNNING/SUCCEEDED/FAILED/CANCELLED/ABANDONED/UNKNOWN`이다. `(job_id, attempt_no)`는 유일하다. 이전 행을 초기화하여 재시도 이력을 지우지 않는다.

워커 획득·lease 갱신·게시에는 현재 fence와 엔티티 버전을 검사한다. 소유자 상실 시 local attempt는 `ABANDONED`, 외부 요청의 결과가 불명확하면 `UNKNOWN`으로 보존한다. 새 워커가 획득한 뒤 이전 워커의 늦은 결과는 게시할 수 없다. lease 만료만으로 원격 실행이 중단되었다고 판단하지 않는다. 시간 비교에는 주입된 Clock과 재시작 식별자를 사용하며 lease 수치는 실측 전 미결정이다.

복구 시 실행 의도가 남은 RUNNING Job은 기존 attempt를 위와 같이 닫고 BLOCKED로 옮긴 뒤 재실행 조건을 판단한다. 기존 취소 의도는 유지한다. 실제 원격 상태가 나중에 확인되어도 사용자가 취소한 결과를 현재 포인터로 자동 게시하지 않는다.

기본 재시도 제안은 로컬 일시 오류에 한해 최초 포함 최대 3 attempt, 지수 backoff와 jitter다. 인증·동의·미지원 기능·입력 손상은 자동 재시도하지 않는다. GPU 부족은 자원 대기/사용자 허용 정책으로 처리하며 CPU·클라우드로 조용히 전환하지 않는다. 외부 호출 timeout은 결과와 과금이 불명확할 수 있어, 제공업체 조회·idempotency 계약을 검증하기 전 자동 재호출하지 않는다.

## 4. 영속 모델과 단일 진실

### 4.1 소유권과 최소 데이터

**D01 제안: 프로젝트별 SQLite를 게시 상태와 제어 메타데이터의 단일 진실로 둔다.** 미디어·전사·요약 본문은 불변 파일에 있고 SQLite가 가리키는 ID·해시로 읽는다. 파일 존재만으로 게시되었다고 판단하지 않는다. manifest는 SQLite 스냅샷의 교환·진단 표현이며 정상 운용에서 독립 수정하거나 DB와 서로 덮어쓰지 않는다.

| 엔티티 | 최소 필드/제약 |
| --- | --- |
| Project | `project_id`, DB 스키마 버전, generation, 마이그레이션 이력 |
| Session | `session_id`, capture/lifecycle 상태, `entity_version`, `deletion_epoch`, 현재 AudioRevision·전사·요약 참조 |
| Track/CaptureEpoch | 원본 역할 mic/system, 포맷, 장치 참조, 시계 앵커, 시작·종료·공백. 장치 이름에 불필요한 개인정보 금지 |
| Chunk | `chunk_id`, track/epoch/sequence, 프레임 수, 포맷, 시간 범위, 상대 경로, byte 수, hash, 검증 상태 |
| AudioRevision | 순서 있는 청크 목록 해시, 공백/유실 목록, 봉인 여부, timeline/mapping 버전 |
| Job/Attempt | 고정 입력 참조, 요청 계약/설정 버전, idempotency 키, 상태, fence, 오류·진행·비용 |
| Artifact | ID, 종류, 불변 상대 경로, 본문 스키마, 크기/hash, 생성 attempt, 입력 참조, 게시/격리 상태 |
| TranscriptRevision | revision/parent ID, source AudioRevision, timeline 버전, segment 목록 artifact, 생성 출처, coverage, 완전성 |
| SummaryRevision | 입력 전사 revision/hash, 요약 설정·템플릿·모델 식별, 근거 목록, 부분/완료 표시 |
| CommandReceipt/Outbox | 명령 중복 판정과 응답, 게시 세대, 이벤트 전달 상태 |
| DeletionRecord | session ID, 삭제 세대, 단계, 미삭제 경로 수, 오류; 전사/원본 내용·비밀 제외 |

`(track_id, epoch_id, sequence)`와 artifact ID는 유일하다. 외래키·유일성·상태 갱신 CAS를 저장소 구현의 필수 조건으로 둔다. 경로는 프로젝트 상대 경로이며 경로 탈출을 거부한다. 세션 간 원본 중복 제거는 초기 범위에서 제외하여 한 세션 삭제가 다른 세션의 참조를 훼손하지 않게 한다.

manifest에는 `manifest_schema_version`, `project_id`, `session_id`, `catalog_generation`, `session_entity_version`, 불변 artifact 참조·해시, 원본 목록, 공백, revision 계보, lifecycle/deletion 정보를 포함한다. 자격증명 값과 자격증명 저장소 내부 식별자는 제외한다. 실행 중 lease와 워커 권한은 import 시 복구하지 않는다.

### 4.2 파일 게시와 DB commit 사이의 프로토콜

DB 트랜잭션과 외부 파일 변경이 하나로 묶인다고 가정하지 않는다. SQLite의 원자 commit은 DB 내부 변경에 대한 것이며 저장장치·flush 가정에도 영향을 받는다. 이 제안은 그 위에 파일 게시 절차를 추가한다. [SQLite Atomic Commit](https://www.sqlite.org/atomiccommit.html)

1. writer는 고유 `artifact_id`의 staging 경로에 쓴다. 청크는 열린 파일과 봉인된 파일을 구분한다. 닫히지 않은 청크를 STT가 고정 헤더 오프셋으로 읽지 않는다.
2. 본문을 닫고 크기·포맷·프레임 수·hash를 검증한다. `ArtifactStore.seal()`은 선택된 파일 시스템에서 검증할 flush/봉인 절차를 수행한다. API 성공과 실제 전원 장애 내구성을 같은 것으로 보고하지 않는다.
3. 같은 프로젝트 볼륨의 고유 최종 경로로 게시한다. 기존 파일을 덮어쓰지 않는다. 경로 이동/교체의 Windows 동작은 D02/D04 시험으로 확인해야 한다. 플랫폼 검증 전에는 rename 한 번으로 전원 장애 안전성을 보장하지 않는다.
4. 짧은 SQLite 트랜잭션에서 참조 무결성, 현재 fence, 입력 버전, 취소/삭제 세대를 검사한다. artifact 행, revision 행, 필요한 현재 포인터, 완료 Job/Attempt, CommandReceipt, generation 증가, outbox를 함께 commit한다. 이 시점이 애플리케이션 게시 경계다.
5. manifest projector는 commit된 generation을 스냅샷으로 읽어 고유 임시 파일을 만들고 최신 manifest를 교체한다. 실패하면 outbox 재시도로 복구한다. 뒤늦은 낮은 generation이 높은 generation을 덮지 않도록 projector를 직렬화한다.
6. UI는 DB 조회로 결과를 노출한다. manifest가 뒤처지면 `manifest_sync_pending`을 표시하되 DB의 현재 결과를 롤백하지 않는다. 프로젝트 내보내기는 해당 스냅샷 manifest까지 완성해야 성공한다.

원본 writer는 DB 잠금 지연으로 캡처 콜백을 막지 않도록 자체 식별 가능한 봉인 청크와 최소 복구 receipt를 남길 수 있다. receipt는 track/epoch/sequence/포맷/프레임/시간/hash를 포함한 **미게시 복구 증거**다. 새로운 제어 상태의 단일 진실이 아니다. DB가 회복되면 검증 후 카탈로그에 채택한다. DB 장애가 길어지면 제한된 큐·디스크 여유 정책에 따라 명시적 녹음 장애가 될 수 있으며 무한 지속을 약속하지 않는다.

초기 DB 운영 후보는 로컬 저장소의 `WAL + synchronous=FULL`이다. SQLite 문서는 WAL의 NORMAL과 FULL에 전원 장애 내구성 차이가 있음을 설명한다. 실제 설정값을 연결마다 확인하고 성능과 장치 내구성은 시험으로 결정한다. [SQLite synchronous](https://www.sqlite.org/pragma.html#pragma_synchronous)

SQLite WAL은 같은 호스트 제약과 부수 파일·체크포인트 관리가 필요하다. 라이브 프로젝트를 네트워크 공유에 두지 않는 안을 제안하며, 열린 DB 본체 파일만 복사하는 것을 프로젝트 백업 계약으로 삼지 않는다. 내보내기는 일관된 DB 스냅샷을 얻는 검증된 방법과 고정 artifact 목록을 사용해야 한다. [SQLite WAL](https://www.sqlite.org/wal.html)

### 4.3 장애 지점별 복구

복구는 해당 프로젝트의 단독 coordinator가 수행한다. 두 인스턴스가 같은 프로젝트를 동시 소유하지 못하게 하고, 소유권을 확인하기 전에 파일 채택·정리를 수행하지 않는다.

| 장애 지점/상태 | 재시작 처리 |
| --- | --- |
| staging 일부만 기록 | 기본 비게시·격리. 포맷 검증으로 확인된 프레임만 별도 복구 artifact에 보존. 원본 추정 복원으로 정상 표시 금지 |
| 봉인 파일/receipt 있음, DB commit 없음 | 알려진 ACTIVE 세션의 미게시 원본만 검증·중복 검사 후 채택. 파생 결과는 입력·attempt·권한을 검증해 후보 보존하며 자동 현재 포인터 교체 금지 |
| DB commit 성공, 응답 유실 | CommandReceipt 재조회. 같은 명령으로 추가 Job/revision 생성 금지 |
| DB commit 성공, manifest 구버전/없음 | DB에서 재생성. 구버전 manifest로 DB rollback 금지 |
| DB 참조 있음, 파일 누락/손상 | artifact를 unavailable/quarantined로 표시하고 readiness 재계산. 원본은 자동 대체하지 않음. 파생물 재생성은 새 artifact로 수행 |
| Job RUNNING이나 소유자 없음 | attempt를 ABANDONED/UNKNOWN으로 분류. 게시 fence 회수. 체크포인트·원격 상태 확인 후 정책에 따라 재예약 |
| DELETE_REQUESTED/DELETING | 삭제 절차만 재개. 청크 자동 채택·AI 재시작·내보내기 금지 |
| SQLite 손상/없음 | 정상 편집·녹음·자동 manifest import 중단. 읽기 전용 격리와 사용자가 선택한 복구 절차. snapshot 복구가 삭제 이력·최신 편집을 되돌릴 수 있음을 표시 |

복구는 반복 실행해도 같은 청크·revision을 중복 생성하지 않는다. hash 불일치를 경로명만으로 수리하지 않는다. 복구로 생긴 결손·미확인 구간은 사용자에게 유지한다. 파일 정리기는 미게시 결과를 즉시 삭제하지 않고 격리하며, 보존 기간과 사용자 정리 정책은 D04와 확정한다.

## 5. 취소·재개·idempotency·부분 결과

### 취소의 게시 경계

RequestCancel은 DB에서 Job 버전과 fence를 갱신하여 게시 권한을 먼저 회수한 후 워커에 중단 신호를 보낸다. 결과 commit과 취소 commit을 직렬화하여 **먼저 commit한 쪽**을 따른다. 성공 게시가 먼저면 취소 응답은 `ALREADY_SUCCEEDED`이고 결과를 지우지 않는다. 취소가 먼저면 늦은 결과는 현재 결과로 게시하지 않는다.

협력 취소 확인 또는 격리 워커 종료 후 CANCELLED로 확정한다. 취소 응답이 없으면 CANCEL_REQUESTED 또는 `BLOCKED/CANCEL_UNCONFIRMED`를 유지하고 이유를 표시한다. 캡처 프로세스를 AI 취소 수단으로 종료하지 않는다. 원격 요청은 로컬 취소 뒤에도 실행·과금될 수 있으므로 별도 `remote_effect=NONE/PENDING/CONFIRMED/UNKNOWN`을 기록한다. 제공업체의 원격 취소 지원은 검증 전 가정하지 않는다.

### 재개와 중복 억제

Job 입력 키는 정규화된 `kind + immutable_input_ids/hashes + timeline_version + adapter/model/config/template_version + output_contract_version + user_run_scope`로 계산한다. canonical 직렬화 규칙과 해시 알고리즘 버전을 고정한다. 비밀 값은 키나 로그에 포함하지 않는다. 명령 중복 억제와 의미상 Job 중복 억제는 별개다.

중복 키의 활성 Job 또는 성공 결과는 재사용한다. 실패·취소 Job의 명시적 재개는 새 Job으로 계보를 남긴다. 같은 입력의 의도적 새 생성은 새 run scope를 요구한다. 외부 API에 이 키를 전달할 수 있다는 사실이나 정확히 한 번 과금된다는 보장은 없다. 지원 범위·보존 시간·요청 조회 동작을 어댑터별 공식 계약과 시험으로 확인해야 한다.

### 체크포인트와 부분 결과

체크포인트는 `job_kind`, 체크포인트 스키마, 입력 키, 처리 단위 ID, 확정 coverage, adapter/model/config 버전, 결과 hash를 포함한다. 완성된 단위의 불변 artifact와 체크포인트 참조를 같은 DB 트랜잭션에 등록한다. 파일 단편이나 메모리상 token 수를 재개 지점으로 사용하지 않는다.

전사는 트랙/epoch/시간 구간, 요약은 분할 입력 revision·범위·중간 결과, 내보내기는 고정 스냅샷과 산출물 목록으로 진행도를 표현한다. AI가 실제 처리한 coverage와 전체 분모를 보여주며, 새 녹음 구간이 늘어나는 live 작업에 고정 전체 완료율을 부여하지 않는다. 토큰 스트림 미리보기와 검증된 부분 산출물을 구분한다.

재개는 동일 입력 키와 호환 체크포인트만 재사용한다. 시간 매핑·편집·모델 설정 변경 시 기존 결과를 보존하고 새 작업으로 다시 계산한다. 부분 전사는 `partial=true`와 빠진 구간을, 부분 요약은 포함 범위와 누락을 명시한다. 실패·취소 시 기존 원본과 게시된 부분 결과는 유지한다. 완전한 결과를 부분 결과가 자동 대체하지 않는다.

## 6. 전사 revision 원자 게시와 편집·요약 충돌

### 전사 계보

`TranscriptRevision`은 본문과 세그먼트 목록이 불변이다. 세그먼트 ID는 revision 안에서 유일하며, 참조는 `(revision_id, segment_id)` 쌍이다. 필수 정보는 track/epoch, 시작·종료 시간, 본문, 출처, draft/final/edited 구분, coverage와 gap, audio/timeline 버전이다. 시간·화자·텍스트 정정도 새 revision으로 만들고 부모와 변경 근거를 남긴다.

세션은 `latest_machine_revision_id`와 `current_transcript_revision_id`를 분리한다. live 초안과 완료 전사도 구분한다. 전체 전사 결과를 새 불변 파일에 완성·검증한 뒤 4.2 절의 DB 트랜잭션에서 revision과 해당 포인터를 게시한다. 여러 구간을 쓰는 중에 현재 전사가 반쯤 바뀌어 보이지 않게 한다. 독자는 한 조회 스냅샷에서 revision ID를 고정하여 읽는다.

PublishTranscript에는 실행 시작 시의 `expected_current_revision_id`가 필요하다. 사용자가 그 뒤 편집했다면 기계 결과는 `latest_machine` 후보로 보존하고 현재 편집 포인터는 유지한다. 단순히 완료 시각이 늦다는 이유로 덮어쓰지 않는다. FINAL_STT의 Job 성공과 사용자 현재 revision 채택은 구분한다. 입력 AudioRevision이 달라졌다면 이전 오디오용 결과로 남기며 최신 전사로 자동 채택하지 않는다.

SaveTranscriptEdit는 `base_revision_id`와 현재 포인터 CAS를 요구한다. 경쟁 편집 중 먼저 게시한 편집만 현재 포인터를 갱신한다. 뒤 편집은 `REVISION_CONFLICT`와 두 revision 참조를 반환하고 편집 내용을 충돌 후보로 보존한다. 자동 덮어쓰기·추측 병합은 하지 않는다. 병합은 사용자가 확인한 새 revision으로 게시한다. 감사 이력은 사용자 삭제 정책의 적용 대상이며 삭제를 막는 영구 보존 장치가 아니다.

### 요약의 입력 고정과 freshness

Summary Job은 `transcript_revision_id/hash`, segment 참조, 요약 유형, 템플릿·설정·제공업체·모델 식별을 시작 때 고정한다. 실행 중 현재 전사를 다시 읽어 서로 다른 revision을 섞지 않는다. 겹치는 분할 범위와 중간 요약도 동일 입력 revision을 가리켜야 한다.

요약 완료 시 결과는 원래 입력 revision에 연결해 보존한다. 현재 전사가 바뀌었다면 `OUTDATED`로 조회하며 현재 요약 포인터를 자동 교체하지 않는다. 동일 전사라도 템플릿/설정 변경 또는 더 최신 요약 채택이 있으면 `expected_summary_selection_version` CAS로 늦은 작업의 덮어쓰기를 막는다.

freshness는 별도 편집 가능한 boolean이 아니라 입력 revision/hash·설정 키와 현재 선택의 비교로 계산한다. 이전 전사로 사용자가 돌아오면 입력이 일치하는 요약을 다시 선택할 수 있다. 근거 링크는 과거 revision의 세그먼트에 유지하며 최신 revision에 자동으로 시간/텍스트를 재연결하지 않는다. 원본·전사가 삭제되면 링크는 unavailable로 처리하고 내용 복구를 유도하지 않는다.

## 7. 세션 준비 상태의 계산

`READY/COMPLETE`를 Session의 녹음 상태로 저장하지 않는다. UI 조회는 같은 DB 스냅샷에서 아래 축과 blocking reason을 계산한다. 캐시는 generation을 키로 하고 원본 상태가 바뀌면 무효화한다.

| 조회 값 | 계산 조건 |
| --- | --- |
| `playback_ready` | ACTIVE이며 요청 구간에 검증된 읽기 가능한 원본 또는 파생 재생물이 존재. 녹음 중에도 가능; 공백 경고 유지 |
| `audio_finalized` | capture_state=CLOSED이고 봉인된 AudioRevision과 검사 결과 존재. DEGRADED도 가능하므로 integrity 별도 표시 |
| `transcript_partial_available` | 고정 입력·coverage를 가진 게시된 부분 전사가 읽기 가능 |
| `transcript_ready` | audio_finalized이며 현재 전사가 동일 AudioRevision/timeline에 연결되고, 알려진 공백을 제외한 처리 대상 coverage 전체가 완료되어 있고 필수 파일 검증 통과 |
| `summary_status` | 미요청 NOT_REQUESTED / 실행 WAITING·RUNNING / 현재 전사·설정 일치 CURRENT / 이전 입력 OUTDATED / 부분 PARTIAL / 실패 FAILED. Job 상태와 결과 가용성은 함께 표시 |
| `export_ready(profile)` | profile이 요구하는 원본·전사·요약·근거가 해당 스냅샷에 존재하고 검증/권한 조건 충족. 부분 내보내기는 별도 명시적 옵션 |
| `completion(profile)` | 녹음 종료 및 사용자가 선택한 필수 산출물 준비. 선택하지 않은 요약은 완료를 막지 않음. 무결성 경고는 제거하지 않음 |

무음은 성공한 전사의 빈 세그먼트와 평가 완료 coverage로 표현할 수 있다. 실패로 생긴 빈 결과와 구분한다. AI 미설치 세션도 원본 저장 완료로 표시할 수 있다. lifecycle이 ACTIVE가 아니면 `DELETE_REQUESTED`부터 모든 준비 boolean을 false로 우선 처리하고 삭제 상태를 표시한다. 누락/손상을 발견하면 관련 준비 값을 즉시 낮추며 오래된 성공 Job만으로 true를 반환하지 않는다.

## 8. 원본 불변과 사용자 삭제

원본 불변은 **보존하는 동안 편집·재처리로 바꾸지 않는다**는 원칙이다. 명시적 사용자 삭제를 금지한다는 뜻이 아니다. 봉인 전의 청크 완성과 봉인 후 본문 변경을 구분하며, 봉인 후 복구·포맷 보정은 원본을 덮어쓰지 않고 별도 artifact로 남긴다.

DeleteSession 제안 절차:

1. DB 트랜잭션으로 `DELETE_REQUESTED`, `deletion_epoch` 증가, 모든 게시 fence 회수, 삭제 작업 기록. 신규 녹음·AI·편집·내보내기·원본 복구 채택을 차단한다. UI에서 즉시 접근을 숨기되 물리 삭제 완료라고 표시하지 않는다.
2. 녹음 중이면 실제 캡처·writer를 중단하고 열려 있는 handle과 진행 중 전송/내보내기 소유자를 정리한다. 중단 확인 전 파일 삭제를 진행하지 않는다. 이미 외부로 전송된 데이터의 회수는 별도 제공업체 절차이며 성공을 가정하지 않는다.
3. 원본, 파생물, 부분 결과, staging, 복구 receipt, manifest, 검색 인덱스, 앱 관리 캐시를 목록에 따라 삭제한다. 각 단계는 반복 가능하고 파일 잠김·권한 실패는 경로 수와 재시도 상태로 남긴다. 진행 중 reader/writer가 있으면 DELETING을 유지한다.
4. 참조 본문·메타데이터를 정리하고 최소 삭제 tombstone만 남긴 뒤 DELETED로 완료한다. tombstone은 옛 파일의 자동 재채택을 막는다. 내용·제목·전사·원본 hash를 필요 이상 남기지 않는다. tombstone 보존 기간은 D04 결정 사항이다.

내보내기·재생 reader는 고정 artifact 목록에 대해 수명 있는 읽기 참조를 획득한다. 일반 정리기는 이 참조가 있는 파일을 제거하지 않는다. 사용자 삭제는 참조 보유자에게 취소를 요청하고 해제될 때까지 DELETING으로 대기하며, 내보내기의 최종 성공 게시도 deletion_epoch를 검사한다. 삭제 요청 후 진행 중 내보내기가 새 외부 사본을 성공으로 확정하지 못하게 한다.

전사 한 revision 또는 원본만 선택 삭제하는 세부 UX는 D00/D04에서 확정한다. 그 기능을 도입하면 참조 중인 요약·검색·내보내기에 미치는 영향을 사전에 계산해야 한다. 사용자 소유 내보내기/백업 및 제공업체 사본은 앱 로컬 삭제와 범위가 다르다. SQLite 본문 삭제, WAL/백업 잔존, SSD의 안전 삭제까지 자동 보장하지 않는다. 이전 백업 복원은 삭제 자료를 되살릴 수 있어 별도 복원 동의와 경고가 필요하다. DB 소실 시 구 manifest만으로 자동 복원하지 않는 이유도 삭제 이력의 부재다.

## 9. 버전과 마이그레이션

버전 축을 분리한다: 앱 릴리스, DB schema 정수, manifest/artifact/checkpoint schema, 명령/이벤트 계약 major·minor, timeline/정렬 알고리즘, adapter capability, 모델·설정·템플릿 버전. 앱 버전 하나로 호환성을 판정하지 않는다.

- DB에는 적용 순서·checksum·시작/완료·원/대상 버전을 기록한다. 동시 앱 소유자와 실행 워커가 없고 녹음 중이 아닐 때만 마이그레이션한다. 업데이트 때문에 녹음 중 스키마를 변경하지 않는다.
- 새 앱은 지원하는 버전 범위를 검사한다. 더 새 DB/필수 major 계약을 만나면 쓰기를 거부하고 가능한 범위의 읽기 전용 내보내기를 안내한다. 추측 변환이나 자동 downgrade를 하지 않는다.
- 추가 optional 필드는 minor로 허용하되 필수 의미·단위·enum 변경은 major로 처리한다. 알 수 없는 필수 enum은 거부한다. import 후 재내보내기가 필요한 확장 필드는 보존하거나 명시적으로 지원 불가를 알린다.
- 이행 전 일관된 DB 스냅샷과 불변 artifact 목록을 보관하고 공간·권한을 확인한다. 대용량 파일 변환은 새 artifact를 만드는 재시작 가능한 단계로 수행한다. 이전 포인터는 새 파일 검증과 DB commit까지 유지한다.
- DB 내부 변환은 가능한 트랜잭션 범위에서 수행한다. 파일 변환과 DB 변경의 전체 rollback을 가정하지 않는다. 중간 단계 실패는 이전 버전 유지 또는 명시적인 이행 재개 상태로 복구하며 반쯤 이행된 프로젝트를 일반 열기하지 않는다.
- 복구용 이전 사본의 보관 기간과 삭제 요청 적용 범위도 정책에 포함한다. 성공 후 무기한 원본·전사 백업을 숨겨 보관하지 않는다.
- 오래된 checkpoint 재사용은 입력·계약·adapter 버전 호환 검사를 통과해야 한다. 기존 Job payload를 최신 엔진에 그대로 넘기지 않는다.

VoiceLocal 이행은 **소스/저장 형식/라이선스 제공 후 별도 설계**다. 현재 경로·테이블·포맷을 추정하지 않는다. 향후 import는 별도 프로젝트로 수행하고 원본 프로젝트를 수정하지 않으며 ID·시간·원본 hash·트랙·편집 계보 보존 가능성을 fixture로 확인한다.

## 10. 공통 실패·관측 계약과 성능 예산

오류 DTO는 `code`, `category`, `retryable`, `stage`, `job_id/attempt_id`, 가림 처리된 상세, `recovery_actions`를 갖는다. 분류는 INPUT, PERMISSION, CAPABILITY, RESOURCE, TRANSIENT, INTEGRITY, CONFLICT, CANCELLED, REMOTE_UNKNOWN이다. 오류에 원본 텍스트·API 키·프롬프트를 넣지 않는다.

필수 관측 값은 트랙별 캡처 프레임·확인된 유실·큐 수위·마지막 봉인 시점, 미게시 원본 수, DB/catalog 지연, manifest generation 차이, Job coverage·현재 단계·시도 횟수·오류, 취소 대기 시간, 원격 비용 확인 상태다. 전체 실패 하나로 원본 가용성을 숨기지 않는다.

성능의 구조적 예산은 확정한다: 모든 큐와 IPC 버퍼에 상한, AI 입력을 확정 청크로 제한, DB 트랜잭션에서 추론·파일 대량 복사 금지, UI 조회에 장기 읽기 트랜잭션 금지, 캡처 저장이 AI 자원보다 우선이다. AI 큐 초과 시 live 초안 작업을 합치거나 미처리로 표시하고 확정 청크 기반 재처리로 따라잡는다. 원본 큐의 유실은 별도 경고·구간 기록 대상이다.

큐 크기, 청크 길이, writer 지연 상한, 디스크 예약량, lease/취소 timeout, AI GPU 여유분, 장시간 WAL 관리 기준은 **측정 후 결정**이다. 고정 메모리 사용이나 특정 지연·무손실을 보장하지 않는다. D02/D03/D04가 제안하고 D00이 검증 게이트와 함께 수치를 채택해야 한다.

## 11. 구현 후 검증할 수락 기준

아래는 시험 설계이며 실행 결과가 아니다. 문서 작성 완료와 제품 합격을 구분한다.

| ID | 주입/행동 | 기대 결과 |
| --- | --- | --- |
| A01 | 느린 STT, LLM 예외, AI 프로세스 종료, GPU 부족 | Session이 AI 이유로 종료되지 않음. 원본 writer와 유실 계측이 계속됨. 하드웨어 지속성은 D02 별도 시험 |
| A02 | 금지된 UI→SQL/모델 직접 의존, callback→AI 호출 검사 | import/구조 검증에서 위반 0. callback의 블로킹 연산 금지 확인 |
| A03 | 재전사·믹스·정렬·편집·요약 전후 원본 hash 비교 | 기존 봉인 원본 byte/hash 동일. 파생 ID·계보 생성 |
| A04 | 4.2 절 각 단계 직전/직후 프로세스 종료, 복구 두 번 | 같은 복구 결과. 중복 청크/Job/revision 0. DB 참조 누락은 격리·경고. manifest 역방향 덮어쓰기 0 |
| A05 | 동일 command 2회, 동일 키 Job 동시 제출, commit 후 응답 유실 | 영속 부작용 1회, 같은 응답/Job 참조. 다른 payload 재사용은 충돌 |
| A06 | 취소와 결과 게시를 양 순서로 경쟁, 오래된 fence로 게시 | 먼저 commit한 규칙 준수. 취소 뒤 현재 포인터 변경 0. 기존 부분 결과 유지 |
| A07 | attempt 실행 중 강제 종료·lease 소유권 교체·원격 timeout | 새 attempt ID/이력 유지. 이전 워커 게시 거부. 불명 원격 호출 자동 중복 0 |
| A08 | 전체 전사 생성 중 편집 두 건, 요약 중 전사/설정 변경 | 편집 유실 0. CAS 충돌과 후보 보존. 요약 입력 revision 혼합 0, 늦은 요약 현재 포인터 덮어쓰기 0 |
| A09 | 동의 없음/철회, capability 미지원, 비밀 포함 진단·내보내기 검사 | 외부 전송 시작 0, BLOCKED 이유 표시. 비밀 값 노출 0. 이미 전송된 요청은 별도 상태 |
| A10 | 녹음·AI·내보내기 중 삭제, 삭제 단계마다 종료, 파일 잠금 | 신규 게시·재채택 차단. 재시작 후 삭제 재개. 미삭제 파일이 있으면 DELETED 완료 금지 |
| A11 | 무음·트랙 누락·부분 전사·요약 미요청·현재 revision 변경 | readiness 표에 맞는 축별 결과. 무음과 전사 실패 구분. 원본 준비와 AI 실패 동시 표현 |
| A12 | 구/미래 스키마, 깨진 artifact, 중간 이행 종료, 체크포인트 버전 변경 | 미래 형식 쓰기 거부. 구 자료 보존, 이행 반복 가능. 호환 안 되는 checkpoint 재사용 0 |
| A13 | 스냅샷 내보내기 중 편집·Job 완료·취소 | 고정 generation의 DB·manifest·artifact 목록/hash 일치. 혼합 revision·비밀·staging 제외 |
| A14 | 앱 종료 시험과 실제 전원/저장 장애 시험 분리 | 각각 환경·flush 설정·마지막 확인 프레임·복구 범위 기록. 앱 종료 합격만으로 전원 장애 합격 표시 금지 |

문서 수준 검증은 R01~R06 추적, 상태 종료/재개 경로, 저장 순서·실패 표, 버전 충돌·삭제 fencing, 링크와 파일 소유권 검토로 한정한다. 라이브러리 설치, 프로그램 구현, 자동화 시험, 음성 분석, 장치 시험은 수행하지 않았다.

## 12. 미결정 질문과 통합 요청

| 항목 | D01 권고/남은 질문 | 결정 담당·해소 조건 |
| --- | --- | --- |
| Q01 단일 진실 | SQLite 권위 + manifest projection을 채택할지, 프로젝트별 DB 배치를 확정할지 | D00, D02/D04 복구·교환 요구 대조 |
| Q02 캡처 복구 | receipt 포맷, 봉인/flush 순서, 트랙별 실패 시 계속 정책, epoch 시간축 | D02 + D00, 합성 시계 및 Windows 장애 시험 계획 |
| Q03 실행 수명 | 단일 인스턴스 소유권, UI 종료 시 녹음 동작, AI 격리 프로세스/IPC·종료 timeout | D00, 실행/패키징 위험 검토 |
| Q04 전사 선택 | 기계 결과와 사용자 현재 전사 포인터 분리, 충돌 후보 UX, 전체 coverage 정의 | D03 + D00, 무음·gap·편집 경쟁 사례 합의 |
| Q05 삭제 | 활성 녹음 삭제 UX, 부분 삭제 허용, tombstone/격리/이행 백업 보존 기간, 원격 잔존 안내 | D04 + D00, 삭제 범위와 실패 보고 승인 |
| Q06 비용·재시도 | 외부 timeout 조회·idempotency·취소 가능 여부, 사용자 재시도 동의·비용 상한 | D03/D04, 어댑터별 공식 근거와 시험 |
| Q07 저장 지원 | 로컬 파일 시스템 범위, WAL 설정, 일관된 백업 방식, 전원 장애 주장 수준 | D02/D04 + D00, 런타임 SQLite 버전·파일 API·장치 시험 |
| Q08 수치 예산 | 큐·청크·메모리·디스크·lease·취소·WAL 한도 | D02/D03/D04, 측정 환경과 합격 기준 명시 |
| Q09 migration | 지원 버전 범위 및 fixture, VoiceLocal import 범위 | D00, 실제 소스·형식 제공 후 별도 배정 |

다른 파일에는 직접 반영하지 않았다. D00은 `docs/architecture-v1.md`에 채택/보류 결정·소유자·상태를 기록하고, `docs/validation-plan.md`에 A01~A14를 실제 시험 종류·환경·증거와 연결할 것을 제안한다. `docs/collaboration/assignments.md`의 D01 상태 갱신도 D00이 수행한다. 중요한 미결정 사항의 소유자와 해소 조건 없이 구현 준비 완료로 승격하지 않는다.

공식 자료는 2026-11-14 확인했다. SQLite 자료는 DB 동작의 설계 근거이며 Recoryn 런타임 버전이나 Windows 하드웨어에서 해당 내구성을 검증했다는 뜻이 아니다.
