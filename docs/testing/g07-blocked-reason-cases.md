# G07 / G-P07 BLOCKED 사유와 녹음 시작 표시 — 계약안·경우의 수

상태: **계약 승인 대기, 구현·신규 시험·mutation 미실행**. 작성 역할은 w5:p8의 계약 작성자이며 독립 검토·최종 승인은 별도다. 이번 쓰기는 이 문서 하나다. 아래 API·파일·분모는 후속 구현을 위한 제안이며 이미 존재하는 구현이나 실행 결과가 아니다.

## 1. 정본·범위·착수 순서

- 정본: `docs/implementation/v1-gap-plan.md:39-40`의 G1A-15·G1A-22 결정, 같은 문서 G-P07 행, `docs/architecture-v1.md`의 상태·provider 오류 우선순위 표.
- 추적: G01-A의 G1A-15·G1A-22·GF-03·GF-08, `docs/reviews/g01-gap-ai-security-ui-review.md`의 G01BR-20·G01CR-01, G01-B의 G01B-071/F-UX02. **오류 사유 기록(GF-03)을 먼저 구현하고 그 사실에 다음 행동 UI를 연결한다.**
- 선행 계약: G-P02 `g02-consent-scope-cases.md`, G-P06 `g06-cost-cap-cases.md`, G-P04 `g04-unfinished-session-cases.md`, G-P05 `g05-pending-deletion-cases.md`.
- 구현은 **G-P04·G-P05·G-P02·G-P06이 모두 push되고 C00가 착수 신호를 준 뒤** 시작한다. G-P04 RECHECK가 오면 이 계약 작업보다 먼저 처리한다. 선행 단위의 변경을 되돌리거나 미커밋 공유 파일을 수정하지 않는다.
- G-P04/P05의 `ui/main.py`, G-P02/P06의 `ui/privacy.py`·`ui/ai_bridge.py`, G-P06의 `app/ai.py`·`providers/_common.py`와 직렬화한다. 착수 시 승인된 최종 tree와 파일 해시를 다시 고정한다.
- 영속 RECORDING 선행과 부분 시작 실패 시 PAUSED·원본 보존은 C00 결정대로 유지한다. Job/Session enum 추가, 저장 스키마 변경, WASAPI·PCM 저장 경로 변경, 실제 가격 항목 추가, 장치별 건강 판정 전체(G-P08)는 범위 밖이다. WAITING_USER는 BLOCKED의 UI 투영이다.

## 2. 직접 확인한 현 상태와 위험

다음은 계약 작성 중 작업 트리를 읽어 확인한 사실이다. G-P02/G-P04의 미커밋 변경이 섞여 있으므로 최종 push tree의 증거로 대신 쓰지 않는다. 다른 단위의 과거 PASS 숫자는 이 단위의 결과에 합산하지 않는다.

| 근거 | 읽어서 확인한 사실 | 변경 방향 |
| --- | --- | --- |
| `src/recoryn/jobs/__init__.py:674` `fail` | REMOTE_UNKNOWN 외에는 BACKOFF/FAILED만 기록. 사유 5종을 생성하지 않음 | 직접 `fail` 호출과 runner 호출에 같은 결정표 적용 |
| 같은 파일 `:417` `resume` | 5사유+ABANDONED 재개 허용, cancel/시도 3회/reader ACK 검사 존재 | UNKNOWN·reader·시도 상한의 보호 유지 |
| `src/recoryn/jobs/runner.py:182` `_failure` | `.code`·bool 속성만 추출. 안전한 도메인 예외의 코드형 `args[0]`은 읽지 않음 | 안전한 정규화와 분류를 구분, 일반 예외 문자열 노출 금지 |
| `src/recoryn/providers/_common.py:179` `request` | factory 예외를 BUDGET_BLOCKED로 합침. gateway 허용 목록에 CONSENT_POLICY_CHANGED 없음 | G-P06 완료 뒤 남은 코드 소실만 보완, UNKNOWN 전파 보존 |
| `src/recoryn/security/transport.py:90` 부근 | 3xx/비정상 응답은 결과 미확인으로 보고 | 401/403 등을 근거 없이 known AUTH로 재해석하지 않음 |
| `src/recoryn/app/desktop.py:93` `_submit` | 수락 여부와 무관하게 미터에 block을 보관할 수 있음 | 미터·packet·진폭으로 녹음 수락을 추정하지 않음 |
| `src/recoryn/app/recording.py:79,154` | 현재 epoch의 accepted_frames 관측과 실제 수락 시 증가가 존재 | current run 관측에 재사용, 이전 epoch와 합쳐 REC를 켜지 않음 |
| `src/recoryn/ui/main.py:382,397` | start/resume 완료 콜백이 곧바로 REC를 표시 | 현재 run의 수락 사실을 투영하는 단일 표시 함수 사용 |
| `src/recoryn/ui/ai_bridge.py` `tick`·준비 실패 처리 | 일반 state/code, UNKNOWN 설명은 있으나 사유별 행동은 불완전 | 안전한 읽기 모델과 명시적 탐색·계속 실행을 분리 |

G1A-15·F-UX02 자체는 S2 기능 편차다. 다만 UNKNOWN을 known으로 낮추는 오류, 동의·예산 우회, 잘못된 세션 재전송, 원본/선택 결과 변경은 S1 위험으로 시험한다. 첫 수락 전 REC는 관측의 사실성 문제이며 녹음 저장 성공·전원 장애 내구성의 증거로 확대하지 않는다.

## 3. 오류 계약

### 3.1 단일 결정표와 안전한 전달

신규 `jobs/failures.py`에 Qt·SDK·네트워크·스토리지와 독립적인 코드 catalog, 안전한 예외 정규화, 순수 결정 함수를 둔다. `runner._failure`는 이 정규화를 호출하고 **JobStore.fail도 같은 순수 결정 함수를 사용**한다. runner에서만 바꿔 직접 `fail(...,"OOM")`이 FAILED로 남는 경로를 허용하지 않는다. 순환 import를 피하기 위해 순수 함수의 결과는 독립 DTO/문자열 literal로 주고 JobStore가 기존 enum으로 변환한다.

`NormalizedFailure(code, retryable, outcome_known)`는 안전한 코드만 가진다. 알려진 ProviderError/SecurityError의 `.code`, 명시적으로 허용한 로컬 StateConflict/ValidationError의 **단일 코드 인자**만 목록과 대조한다. 일반 RuntimeError의 문장·`str(exc)`·서버 body·토큰·경로를 코드/라벨/로그에 복사하지 않는다. MemoryError는 OOM으로 정규화한다. 속성 getter가 예외를 던져도 처리기를 다시 실패시키지 않는다. retryable은 정확히 `True`일 때만 참이다. outcome_known 속성이 없으면 기존 로컬 예외 호환을 위해 참, 존재하지만 bool이 아니거나 읽기 실패이면 거짓으로 보수화한다. 원격 실행을 감싼 `_OutcomeGuard`의 미확인 사실을 덮어쓰지 않는다.

G-P02 CONSENT_POLICY_CHANGED 및 G-P06의 구체 COST_*는 provider 공통 경로에서 허용 목록으로 전달한다. factory가 안전한 typed COST_*를 냈으면 BUDGET_BLOCKED로 뭉개지 않는다. 그 밖의 알 수 없는 factory 오류를 안전한 BUDGET_BLOCKED로 처리하는 기존 fallback은 유지한다. gateway의 출처·결과가 불명확한 오류는 기존 REMOTE_OUTCOME_UNKNOWN으로 보수화한다. 소문자·임의 prefix·문자열 포함 검색으로 범주를 추정하지 않는다.

### 3.2 유한 코드 catalog와 범주

아래 목록은 **이 계약의 폐쇄된 대표 입력 표**다. 합계 100개 중 99개는 명시 처리할 코드, `G07_UNREGISTERED_ERROR` 1개는 등록되지 않은 코드 대표다. 모든 가능한 Python 예외나 타 단위의 전체 오류 문자열을 조사 완료했다는 뜻이 아니다. G-P06 코드는 승인된 계약에서 옮긴 것으로 아직 그 구현을 검증한 결과가 아니다. 목록 밖 코드의 안전한 기본값도 아래에 고정한다.

| 그룹 | 수 | 입력 코드 — 목록 자체를 독립 시험 oracle에 손으로 고정 |
| --- | ---: | --- |
| C / CONSENT | 10 | CONSENT_REQUIRED, CONSENT_REVOKED, CONSENT_POLICY_CHANGED, CONSENT_CLOCK_INVALID, PERMIT_REVOKED, EXECUTION_CHANGED, ENDPOINT_CHANGED, NETWORK_POLICY_DENIED, DNS_TARGET_DENIED, REDIRECT_DENIED |
| A / AUTH | 3 | AUTH_REQUIRED, VAULT_UNAVAILABLE, VAULT_READ_FAILED |
| P / CAPABILITY | 13 | CAPABILITY_UNSUPPORTED, LANGUAGE_UNSUPPORTED, AUDIO_UNSUPPORTED, CONTEXT_LIMIT, CONTEXT_LIMIT_UNKNOWN, DEPENDENCY_MISSING, DEPENDENCY_VERSION_UNSUPPORTED, LOCAL_EXECUTION_UNVERIFIED, DIARIZATION_PLATFORM_UNSUPPORTED, DIARIZATION_AUDIO_UNSUPPORTED, DIARIZATION_LICENSE_REQUIRED, OLLAMA_LOCAL_EXECUTION_UNVERIFIED, OLLAMA_REMOTE_MODEL_BLOCKED |
| R / RESOURCE | 17 | OOM, RESOURCE_EXHAUSTED, RESOURCE_GPU_UNAVAILABLE, RESOURCE_ESTIMATE_REQUIRED, MODEL_MISSING, LOCAL_MODEL_REQUIRED, GPU_RUNTIME_UNAVAILABLE, GPU_RUNTIME_DAMAGED, GPU_RUNTIME_NOT_INSTALLED, GPU_RUNTIME_LATE, GPU_RUNTIME_UNSUPPORTED, INFERENCE_ACK_PENDING, DIARIZATION_ACK_PENDING, MODEL_OPERATION_ACTIVE, GPU_RUNTIME_IN_USE, LOCAL_READER_ACK_REQUIRED, LOCAL_READER_STILL_ACTIVE |
| B / BUDGET | 24 | BUDGET_BLOCKED, BUDGET_REQUIRED, BUDGET_EXCEEDED, BUDGET_POLICY_CHANGED, BUDGET_SCOPE_MISMATCH, LEDGER_REQUIRED, LEDGER_ROLLBACK_DETECTED, RESERVATION_CONFLICT, RESERVATION_NOT_DISPATCHABLE, RESERVATION_MAY_BE_SENT, SETTLEMENT_CONFLICT, COST_PRICE_UNKNOWN, COST_PRICE_EXPIRED, COST_BOUND_UNVERIFIED, COST_CAP_REQUIRED, COST_CAP_EXCEEDED, COST_QUOTE_MISMATCH, COST_QUOTE_EXPIRED, COST_CURRENCY_MISMATCH, COST_PERIOD_CHANGED, COST_LEGACY_UNSCOPED, COST_UNRESOLVED_EXPOSURE, COST_CLOCK_INVALID, COST_PLAN_UNDERESTIMATED |
| T / 알려진 일시 오류 | 8 | TEMPORARY, UNSENT, TIMEOUT, NETWORK_TIMEOUT, TRANSPORT_FAILED, CONNECTION_FAILED, CONNECTION_CLOSED, POLICY_BUSY |
| F / 입력·무결성·기타 known 실패 | 23 | INPUT_INVALID, INPUT_MISSING, INPUT_TOO_LARGE, REQUEST_TOO_LARGE, RESPONSE_TOO_LARGE, RESULT_INVALID, RESULT_INCOMPLETE, REFERENCE_INVALID, CHECKPOINT_MISMATCH, PROGRESS_CALLBACK_FAILED, PROVIDER_FAILED, TASK_FAILED, COST_REQUEST_INVALID, COST_AMOUNT_OVERFLOW, SESSION_REVOKED, SESSION_DELETED, CANCELLED, RESOURCE_CANCELLED, MODEL_CHECKSUM_MISMATCH, DIARIZATION_MODEL_CHECKSUM, BUDGET_RESERVATION_REUSED, REMOTE_REJECTED, REQUEST_LIMIT |
| U / 명시 UNKNOWN과 미등록 대표 | 2 | REMOTE_OUTCOME_UNKNOWN, G07_UNREGISTERED_ERROR |

T의 TEMPORARY/UNSENT는 현행 fake·복구 시험의 계약을 유지하기 위해 명시한 이름이다. 미등록 SDK 예외를 임의로 일시 오류로 승격하지 않는다.

### 3.3 오류 코드 × retryable × outcome_known 전수 결정

아래 표는 100개 각각에 적용하는 `retryable × outcome_known` 4칸의 압축 표다. `n`은 **이번 attempt를 포함한 누적 시도 수**, 상한은 기존 3이다. `K = outcome_known is True AND code != REMOTE_OUTCOME_UNKNOWN`으로 정의한다. Job/Attempt 상태와 blocked_reason을 모두 검증한다.

| 그룹 | retryable=거짓, known=참 | retryable=참, known=참 | retryable=거짓, known=거짓 | retryable=참, known=거짓 |
| --- | --- | --- | --- | --- |
| C/A/P/R/B 각각의 모든 코드 | BLOCKED(해당 사유), Attempt FAILED | BLOCKED(해당 사유), Attempt FAILED | BLOCKED(REMOTE_UNKNOWN), Attempt UNKNOWN | BLOCKED(REMOTE_UNKNOWN), Attempt UNKNOWN |
| T 각각 | FAILED, 사유 없음, Attempt FAILED | n<3이면 BACKOFF, n=3이면 FAILED. 사유 없음, Attempt FAILED | BLOCKED(REMOTE_UNKNOWN), Attempt UNKNOWN | BLOCKED(REMOTE_UNKNOWN), Attempt UNKNOWN |
| F 각각 | FAILED, 사유 없음, Attempt FAILED | FAILED, 사유 없음, Attempt FAILED | BLOCKED(REMOTE_UNKNOWN), Attempt UNKNOWN | BLOCKED(REMOTE_UNKNOWN), Attempt UNKNOWN |
| REMOTE_OUTCOME_UNKNOWN | BLOCKED(REMOTE_UNKNOWN), Attempt UNKNOWN | 동일 | 동일 | 동일 |
| 미등록 대표 | TASK_FAILED로 정규화 후 FAILED, Attempt FAILED | 동일, 임의 자동 retry 금지 | BLOCKED(REMOTE_UNKNOWN), Attempt UNKNOWN | 동일 |

따라서 OOM에 retryable=True가 붙어도 자동 BACKOFF가 아니라 RESOURCE 대기다. COST_REQUEST_INVALID·COST_AMOUNT_OVERFLOW는 COST_ prefix만으로 BUDGET으로 만들지 않는다. HTTP REMOTE_REJECTED/REDIRECT_DENIED라도 known=False이면 UNKNOWN이 우선이다. 구체 상태코드를 보고 송신·과금 결과를 확인했다고 간주하지 않는다.

우선순위와 부수효과는 다음으로 고정한다.

1. 기존 attempt/fence·게시 권한과 취소·삭제 검사는 유지한다. stale ACK가 새 attempt/결과를 바꾸지 못한다.
2. 취소 의도가 먼저 commit됐으면 runner는 기존 취소 ACK 절차를 따른다. K가 거짓이면 CANCELLED로 낮추지 않고 BLOCKED(REMOTE_UNKNOWN)/Attempt UNKNOWN·cancel_requested를 보존한다. 명시 REMOTE_OUTCOME_UNKNOWN도 **취소 ACK 이전**에 K=거짓으로 정규화한다. 취소 의도 없는 `CANCELLED` 코드만으로 취소를 위조하지 않는다.
3. 삭제된 세션의 attempt는 새로운 읽기·재개를 허용하지 않되 실패 ACK는 허용한다. K=거짓은 UNKNOWN을 유지하고 K=참은 FAILED로 닫는다. 이미 삭제된 Job을 새 known BLOCKED 사유로 재개 가능하게 만들지 않는다.
4. 나머지는 위 표. 사유 분류는 retryable보다 먼저다. BLOCKED도 시도 한도는 늘리지 않으며 n=3이면 사용자에게 한도 소진을 표시한다.
5. 어떤 분류도 원본·선택 결과·checkpoint를 지우거나 재예약·정산하거나 reader active를 0으로 만들지 않는다. 작업 반환 후 reader_finished의 실제 ACK만 사용한다. 같은 transaction에서 Job/Attempt와 기존 outbox를 기록하고 fence/state_version을 증가시킨다.

이 계약은 등록되지 않은 retryable 코드의 자동 BACKOFF를 금지하는 쪽으로 현 동작을 좁힌다. 새 일시 오류를 지원하려면 catalog·독립 oracle·mutation을 함께 추가한다. 이 강화와 범주별 선택은 C00 승인 대상이다.

### 3.4 JobStore의 실행 전 BLOCKED API

제안 서명: `block_pending(job_id, reason, error_code, *, expected_version) -> JobRecord`.

- QUEUED이고 expected_version이 현재 state_version과 같으며 세션이 유효할 때만 적용한다. 이전 attempt가 있으면 종료 상태·명시 reader inactive가 필요하다. 처음 생성되어 attempt가 없으면 reader receipt 부재를 허용한다.
- reason은 CONSENT/AUTH/CAPABILITY/RESOURCE/BUDGET 5종만 허용하고 code의 catalog 범주와 정확히 일치해야 한다. ABANDONED는 재시작 복구, REMOTE_UNKNOWN은 실제 attempt 결과 경로에서만 만든다. 대소문자 보정·빈 값·임의 문자열 fallback은 없다.
- QUEUED→BLOCKED, code/reason 및 기존 outbox를 원자 기록하고 fence/state_version을 증가시킨다. attempt를 만들거나 누적 count·checkpoint·이전 결과를 초기화하지 않는다. RUNNING을 이 API로 중단하거나 reader ACK를 위조하지 않는다.
- API 거부는 기존 StateConflict/ValidationError의 안전한 코드로 처리한다. UI에는 `JOB_NOT_BLOCKABLE`, `JOB_VERSION_CHANGED`, `BLOCK_REASON_INVALID`, `BLOCK_REASON_MISMATCH`를 구별하되 임의 DB 내용을 노출하지 않는다.
- 유효한 ExecutionPlan조차 만들지 못한 준비 단계(동의·키·비용 검증 실패)는 **Job을 억지 생성하지 않는다**. 같은 사유 read model을 가진 “실행 준비 차단, 작업 미접수” 안내로 표시한다. 이미 BLOCKED인 Job의 계속 준비가 실패하면 그 Job은 그대로 두고 새 준비 사유를 별도 표시한다. 준비 실패를 실행 attempt 또는 성공한 접수로 세지 않는다.
- 유효 계획으로 이미 QUEUED에 입장한 뒤 dispatch 전 재검사에서 알려진 5사유가 발생한 호출부는 이 API를 사용한다. RUNNING attempt 안에서 같은 오류가 발생하면 `fail`을 사용한다. 사유 표·원본 보존 결과가 두 경로에서 같아야 하며 실행되지 않은 작업을 실패 attempt로 위조하지 않는다.

### 3.5 재개와 기존 호출자

`resume`의 6사유·시도 한도·삭제·cancel·reader 조건은 보존한다. 선택적인 keyword `expected_version`을 추가해 UI의 명시 계속 실행은 transaction 안에서도 version을 대조한다. 기존 호출자는 생략 가능하지만 UI에서 읽은 version을 빠뜨리지 않는다. ABANDONED는 기존의 명시 복구/재검사 경로를 사용하고 REMOTE_UNKNOWN은 이 버튼으로 재개하지 않는다. 단순히 설정 화면을 열거나 값이 바뀐 신호가 왔다는 이유로 resume하지 않는다.

UI의 “조건 다시 확인 후 계속”은 다음 순서다.

1. 클릭 때 job_id/session_id/state_version/현재 선택을 다시 확인한다. 다른 세션의 오래된 버튼이면 실행하지 않고 새 표시를 요구한다. UNKNOWN·terminal·시도 한도·reader active는 예약 등 준비 부수효과 전에 먼저 거부하며 store의 재개 transaction에서도 재검사한다.
2. G-P02/G-P06의 현재 정책·동의·가격/예산·인증·자원으로 새 불변 실행 준비 snapshot을 한 번 만든다. 준비 중 철회·정책 변경·삭제는 송신 직전 guard에서도 계속 검사한다. 같은 snapshot을 재료로 삼되 옛 grant·reservation을 재활용하지 않는다.
3. `AIService.transcribe/summarize`에 선택적인 `expected_job_id`·`expected_job_version`을 추가하여 **기존 idempotency/input/의미 설정 키와 동일한 Job으로만** 계속한다. 계산한 키를 기존 Job과 대조하는 시점은 `jobs.create`보다 앞이다. 불일치는 `CONTINUE_PLAN_CHANGED`로 새 Job 생성 전에 거부한다. retry nonce를 자동 발급하지 않는다. JobStore.resume의 version 검사를 통과한 뒤 기존 runner 입장 절차로 새 attempt를 시작한다. 단순 UI 호출만으로 reader·자원·권한 검사를 우회하지 않는다.
4. 모델·입력·템플릿 등 의미가 달라지면 기존 BLOCKED Job을 바꿔치기하지 않는다. “설정이 달라 새 작업 필요”와 명시적 새 요청 동작을 제공한다. 기존 terminal 수동 재실행과 UNKNOWN의 위험 확인을 없애지 않는다. 자원 배치/CPU 허용처럼 같은 의미인 변경은 검증된 ExecutionPlan만 갱신하며 CPU fallback은 사용자 정책을 따른다.

화자 구분은 현재 service의 제공 경로에 맞춰 사유 표시·설정 안내만 제공하며 존재하지 않는 Job을 만들지 않는다. G-P03의 화자 게시 CAS는 유지한다. 추후 화자 기능이 Job에 들어갈 때도 같은 규칙을 적용하되 이 단위에서 새 화자 작업 시스템을 만들지 않는다.

## 4. 사유별 다음 행동 UI

신규 `app/status.py`의 순수 read model은 job/preparation의 안전한 사실로 상태·사유·설명·행동 식별자·continue 가능 여부를 만든다. Qt 위젯·비밀·실제 네트워크를 소유하지 않는다. `ui/content.py`는 원본·기존 결과 보존, 사유와 행동 버튼을 보여 주고 `ai_bridge.py`가 현재 선택과 Job을 대조해 연결한다.

| 사유/상황 | 화면 안내·탐색 행동 | 계속 실행 제약 |
| --- | --- | --- |
| CONSENT | “동의/전송 정책 확인”; privacy의 세션/기능/endpoint/정책 version 위치로 이동 | G-P02의 명시 SESSION/LIBRARY 선택·확인 후 새 준비. 화면 열기는 grant 발급 아님 |
| AUTH | “제공업체 키 설정 확인”; 해당 키 설정 위치로 이동 | 기존 vault UI의 사용자 조작을 사용. 탐색만으로 vault 읽기/쓰기·키 검증 호출 금지 |
| CAPABILITY | “모델·기능·언어·컨텍스트/사용 조건 확인”; 모델/제공업체 설정 표시 | 설치·다운로드·모델 대체 자동 수행 금지. 의미 변경이면 새 Job 안내 |
| RESOURCE | “메모리·GPU·로컬 모델·종료 확인”; 자원/모델 설정 또는 ACK 상세 | RESOURCE_EXHAUSTED도 자동 무한 재시도 금지. reader/GPU ACK 미확인은 실제 종료 전 계속 비활성. 자동 CPU 전환 금지 |
| BUDGET: cap 부족/없음 | 상한·현재 계산과 “예산 확인” | 명시 예산 변경 뒤 새 검증. 사용자 cap을 검증 가격 근거로 승격하지 않음 |
| BUDGET: 가격/상한 미검증 | “검증된 가격·요청 상한 근거 필요”; strict가 막힌 이유 표시 | cap 증액이 해결책인 것처럼 표시 금지. G-P06의 별도 위험 확인을 거친 일반 모드만 기존 UI에서 선택 가능 |
| BUDGET: clock/ledger/미정산/기간·통화 | “시각·원장·미정산 확인”; 안전한 내역/기존 설정 위치 안내 | 원장 삭제/UNKNOWN 해제/통화 변환/기간 대체/재서명 자동 수행 금지. 현재 API로 해결 못 하면 안내 후 비활성 유지 |
| BLOCKED(REMOTE_UNKNOWN) | “결과·비용 미확인, 자동 재전송 없음”; 내역·기존 결과 보기 | 계속 버튼 없음. 별도의 명시 새 요청+중복 실행/비용 경고는 유지. 취소 의도도 표시 |
| BLOCKED(ABANDONED) | “이전 실행 종료·권한 재확인” | 실제 reader 종료 증거와 같은 계획 검증 필요 |
| FAILED 입력/무결성 | 입력·모델 파일·참조 확인과 보존 결과 보기 | terminal을 resume하지 않음. 수정 뒤 명시 새 Job |
| BACKOFF / 시도 한도 소진 / 취소·삭제 | 대기·남은 시도 / 한도 소진 / 취소·삭제 상태 | 해당 상태를 BLOCKED 5사유로 위장하지 않음. 완료된 Job 새 실행은 기존 계약 |

`ui/privacy.py`에는 `focus_blocked_action(kind, action_id)`처럼 **설정 위치를 보여 주고 초점을 옮기는 helper만** 추가한다. 키/동의/cap/일반 모드 확인 자체는 선행 단위의 기존 조작을 사용한다. 모델·자원 위치는 MainWindow가 기존 패널로 탐색한다. 없는 정산 기능을 동작하는 버튼처럼 만들지 않는다. provider 응답의 임의 메시지·endpoint 쿼리·비밀을 라벨에 넣지 않는다.

읽기 모델은 “실행 준비 차단(미접수)”와 “Job BLOCKED”를 구별한다. render/open은 Job/grant/ledger/선택 revision에 부수효과 0이다. continue만 명시적으로 실행하며 버튼 누름 뒤 선택 변경·삭제·fence 교체가 있으면 stale 조작을 거부한다. 취소·확정/복구·삭제 UI는 G-P04/P05 계약을 유지한다.

## 5. REC/시작 중 계약

### 5.1 관측 API와 표시 우선순위

`DesktopRecorder.capture_progress()`에 frozen 사실 DTO를 제안한다: session_id, 증가하는 run_generation(start/resume마다 새 값), 현재 epoch 식별, control_mode, all_sources_ready, current_accepted_frames, accepting, storage_failed, failure/ACK 상태. Qt는 이 DTO를 `app/status.py`에서 투영한다.

- source.start의 정상 반환/검증된 장치 준비 완료와 첫 submit 수락을 구별한다. start 도중 한 source가 먼저 PCM을 줄 수 있다. current_accepted_frames는 **현재 run의 submit=True인 양의 frame 합**이다. 무음도 양의 frame이면 수락이며 진폭 0은 장애가 아니다. queue 거부·packet 통지·미터 값은 수락 근거가 아니다.
- 시작·재개 시 token과 현재 epoch 관측을 새로 잡는다. callback은 생성 시 고정한 session/run/epoch와 현재 값을 대조한다. 오래된 callback이 현재 수락·ready·실패 표시를 덮어쓰지 못한다. 기존 PCM·epoch 검증과 원본 보존은 그대로 둔다.
- DesktopRecorder lock을 잡은 채 RecordingService.health_snapshot의 lock을 기다리는 반대 순서를 만들지 않는다. 참조/token 복사→락 해제 후 snapshot→token 재확인으로 오래된 관측을 거부하거나 보수적인 시작/종료 확인 상태를 반환한다. 표시 DTO 추가가 저장/worker 종료 증명을 대체하지 않는다.
- REC는 **현재 session/run 일치 AND control_mode=ACTIVE AND all_sources_ready AND accepting AND current_accepted_frames>0 AND storage_failed=False AND 종료/실패/ACK 대기 없음**일 때만 표시한다. ACTIVE는 장치 시작 절차가 끝난 제어 상태이며 첫 frame 수락과 별개다. UI의 시작 완료 콜백과 tick은 같은 투영 함수를 호출한다.
- 준비 완료 전 이미 일부 PCM을 수락했으면 “시작 중 · 일부 오디오 수락 · 장치 준비 확인 중”. 모든 장치가 ready여도 0 frame이면 “시작 중 · 첫 오디오 블록 대기”. 이 중 **장치 전체 ready도 REC의 필요조건으로 하는 강화**는 C00 승인 대상이다.
- PAUSED·STOPPING·ENDED·storage 실패·장치 실패·ACK 대기는 REC보다 우선한다. 오류 코드와 “종료 확인 중/일부 원본 보존”을 구별한다. 모든 원본이 저장됐다는 보장은 표시하지 않는다. 현재 부분 트랙 상태를 정상 전체 녹음으로 표현하지 않으며 상세 트랙 건강 정책은 G-P08 후속이다.

### 5.2 대표 상태열

| 이벤트 | 영속/원본 | UI |
| --- | --- | --- |
| 시작 요청 | 기존 절차로 RECORDING 선행 가능 | 시작 중 |
| 장치 ready, 아직 수락 0 | 상태 유지, 새 원본 없음 | 첫 블록 대기, REC 없음 |
| 첫 블록 submit 거부 | 수락 0 유지 | 시작 중, 거부/저장 실패 사실은 별도 표시 |
| 첫 양의 block 수락 + 모든 장치 ready | 원본 worker의 기존 수락 경로 | REC 가능. 파일 확정/내구성과 구별 |
| 첫 block이 장치 전체 ready보다 먼저 수락 | 일부 원본 존재 | 시작 중·일부 수락. 이후 전체 ready 때 REC |
| pause 요청/ACK 대기→PAUSED | 기존 drain·부분 원본 보존 | 일시정지 중/일시정지, REC 없음 |
| resume 요청→ready, 이전 epoch에는 frame 존재 | 새 epoch 수락 0 | 시작 중. 이전 누적 frame으로 REC 금지 |
| 새 epoch 첫 양의 무음 block 수락 | 실제 frame 수락 | REC 가능 |
| stop/실패→종료 ACK 지연 | 기존 원본·reader/owner 계약 | 정지/종료 확인 중 또는 실패, REC 없음 |
| 실패 뒤 오래된 ready/PCM callback | 기존 세대에 대한 late 입력 거부 | 종료/실패 표시 유지 |

경과 시간·frame 통계·PCM 시각의 기준은 바꾸지 않는다. 시작 대기에도 경과 시간이 흐를 수 있으나 “녹음 원본 수락 시간”으로 오인하지 않게 라벨을 구별한다. 실제 장치가 영원히 첫 블록을 주지 않는 경우의 새로운 자동 timeout/자동 stop 정책은 추가하지 않는다.

## 6. 입력 분할·분모·독립 oracle

### 6.1 유한 대표 공간

아래는 **11개의 서로 다른 시험 family에 속한 의미 행 4,490개 계획**이다. 가족 간 직적이나 모든 상태열 깊이에 대한 전수 증명이 아니다. 실제 pytest node 수는 fixture batching 방식에 따라 다르므로 실행 시 둘 다 보고한다. 모든 행은 거부·손상 fixture도 포함해 TEMP 안에서 구성 가능하게 한다. 물리 캡처에서 도달하지 않는 DTO 조합도 read model의 방어 입력으로 시험하며 정상 도달 상태라고 주장하지 않는다. 이번 표는 각 family F=Ω이고 제외 0이다.

| family / 고유 ID | 인자·직적 Ω=F | 계획 행 | 독립 기대값 |
| --- | --- | ---: | --- |
| D / G07-D-0001…2400 | 코드100 × retryable2 × known2 × 이번 누적 시도{1,2,3} × 세션{유효,삭제됨} | 2,400 | §3.3의 손으로 쓴 범주·4칸 표와 삭제 override. Job/Attempt/reason/fence/reader/결과 불변 |
| R / G07-R-0001…0960 | 사유{5종,ABANDONED,REMOTE_UNKNOWN,미등록}=8 × 상태{BLOCKED,QUEUED,FAILED,CANCELLED,SUCCEEDED}=5 × 이력6 × cancel2 × 세션2 | 960 | resume 허용은 BLOCKED의 알려진6사유·유효 세션·취소 없음·허용 이력만 |
| P / G07-P-0001…0360 | 알려진 사유5 × 상태{QUEUED,RUNNING,BLOCKED,SUCCEEDED,FAILED,CANCELLED}=6 × expected_version{이전,현재,미래}=3 × 세션2 × 이력{미실행,종료된1회}=2 | 360 | block_pending 허용은 QUEUED·현재 version·유효 세션·종료 reader. count/기존 결과 불변 |
| C / G07-C-001…072 | 대표 오류9 × retryable2 × known2 × {취소 commit→실패 ACK,실패 ACK→취소 commit}2 | 72 | 5사유 각1+T/F/명시REMOTE/미등록. K 거짓은 UNKNOWN+취소 의도 유지; known은 취소 절차, 늦은 게시 0 |
| F / G07-F-01…30 | 사유5 × 준비{유효한 같은 계획,권한 snapshot 폐기됨,의미/input 키 변경}=3 × reader{inactive,active}=2 | 30 | 유효 같은 계획·inactive만 같은 Job 새 attempt. stale은 새 write 전 차단, 키 변경은 새 Job 암묵 생성 0 |
| V / G07-V-001…288 | control{IDLE,STARTING,ACTIVE,PAUSED,STOPPING,ENDED}=6 × all_ready2 × 현재 accepted{0,1,2}=3 × accepting2 × storage_failed2 × generation_match2 | 288 | §5의 논리 조건을 손으로 정한 참인 tuple 집합과 대조. 불일치/비정상 DTO는 REC 없음 |
| O / G07-O-001…120 | 시작 요청 고정 뒤 독립 이벤트 D/A/R/E의 순서4!=24 × 종료종류{pause,stop,start실패,storage실패,device실패}=5 | 120 | D=전체 장치 완료 시도, A=양의 PCM 제출 시도, R=거부 제출 시도, E=종료. E 뒤 A/D는 late 시도이므로 무효, A가 실제 수락됐을 때만 REC 근거 |
| E / G07-E-001…072 | 이전 epoch 수락{0,양수}=2 × 새 입력{없음,packet만,거부,양의 무음 수락}=4 × 늦은 이전 callback{없음,ready,PCM시도}=3 × 마지막 제어{계속,pause,stop}=3 | 72 | 이전 frame/late 입력은 현재 REC 근거 아님, 새 무음 수락은 근거. 종료 우선 |
| U / G07-U-001…150 | UI 범주{5사유,REMOTE_UNKNOWN,FAILED입력,FAILED기타}=8 × 기능{STT,요약,화자}=3 × 동작{render,open,continue}=3 × 선택{같음,다름}=2 →144; 별도 UNKNOWN 새요청 확인3기능×{거부,승인}2 →6 | 150 | render/open 부수효과 0; Job 없는 화자 continue 비활성; 다른 선택의 늦은 동작 차단; UNKNOWN 확인 거부 시 dispatch 0 |
| N / G07-N-01…20 | §6.3의 정규화 named case 20 | 20 | 안전한 고정 코드·정확한 bool·UNKNOWN 보존. 비밀 canary 미노출 |
| T / G07-T-01…18 | §6.3의 API/DTO 타입·version 경계 named case 18 | 18 | 안전한 거부와 DB/reader/원본 불변 |
| **합계** | 2400+960+360+72+30+288+120+72+150+20+18 | **4,490** | 계획 수치, 실행 수치 아님 |

R의 이력6은 (h0)count0/attempt 없음/receipt 없음, (h1)count1/종료 attempt/active0, (h2)count1/active1, (h3)count1/legacy receipt 없음, (h4)count2/종료 attempt/active0, (h5)count3/종료 attempt/active0이다. 허용 이력은 h0/h1/h4뿐이다. terminal×h0 등 정상 API로 만들지 않는 조합은 격리 SQLite의 방어 fixture로 구분하며 정상 상태 모델의 도달 주장에 합산하지 않는다. P의 RUNNING×미실행 등도 거부 fixture다. 실제 DB 제약 때문에 구성 불가가 발견되면 임의 제외/분모 축소 전에 C00에게 제약과 대체 입력을 보고한다.

C의 “실패 ACK→취소”에서 BACKOFF/BLOCKED 취소와 FAILED terminal 응답은 기존 cancel API의 표를 따른다. 실패 먼저인 known FAILED를 소급 CANCELLED로 바꾼다는 뜻은 아니다. K 거짓일 때만 취소 의도와 UNKNOWN을 함께 유지하는지를 두 순서에서 확인한다.

O는 제출 **시도**와 ready **완료 시도**의 순서다. E 뒤 성공 수락/ready를 강제로 만든다는 뜻이 아니므로 24개 모두 실행 가능한 호출열이다. 이벤트 내부 인과는 시작 요청 선행뿐이며 각 제출 호출의 반환·실제 수락을 기록한다. 별도 Event/barrier로 콜백을 정지시켜 순서를 재현하고 긴 sleep이나 scheduler 우연을 분모 근거로 쓰지 않는다.

V는 장치 오류·종료 ACK 대기 flag를 거짓으로 고정한 순수 투영 cube다. REC 참 tuple은 `(ACTIVE, ready=True, frames=1 또는 2, accepting=True, storage_failed=False, generation_match=True)` 두 개뿐이다. 장치 실패/ACK 대기의 REC 억제는 O/E의 상태열에서 따로 확인한다. 따라서 V의 288행을 모든 건강 flag의 완전 직적이라고 부르지 않는다. R/F의 version은 현재 값으로 고정하며, resume의 오래된/미래 expected_version 거부는 T17/18에 별도 둔다.

### 6.2 oracle 독립성과 감사

- 시험의 code→reason 표는 §3.2 목록을 손으로 고정한다. 제품 catalog/classifier/render 함수를 import하여 expected를 생성하지 않는다. 제품 목록과 독립 목록의 차집합·중복·범주 충돌도 별도 감사한다.
- D의 기대 state/attempt/reason은 §3.3과 n=1/2/3 경계에서 독립 계산한다. R은 허용 사유6·이력3의 명시 집합, P는 QUEUED/현재 version/세션/reader 조건을 고정 oracle로 사용한다. SQL 사후 관측과 이벤트를 함께 확인한다.
- 원본은 합성 PCM의 사전 SHA-256/bytes/frame 수와 대조한다. AI 오류·취소·대기·재개가 녹음을 끝내거나 선택된 결과/checkpoint를 바꾸지 않는다. 원격 경로는 독립 fake의 DNS/연결/본문/예약 횟수를 관측하며 렌더/탐색/거부는 0이다.
- REC oracle은 fake source의 제출 호출 반환과 수락된 frame 합을 별도 기록한다. 제품 health의 값을 기대값 계산에 다시 사용하지 않는다. 진폭 0/양수, 트랙1/2, ready 순서를 바꿔도 수락 사실만 같으면 REC 결과가 같다.
- 고유 ID를 family별 고정 순서의 tuple에 붙인다. 계획 ID 집합과 실제 manifest를 독립 대조해 missing/duplicate/extra=0을 요구한다. named case를 제외한 임의 seed 생성은 별도 보강이며 4,490에 합산하지 않는다. 실제 예외·skip·xfail·구성 실패도 숨기지 않고 분모와 함께 보고한다.

### 6.3 정규화·타입 named case

N01~20은 순서대로 다음 입력이다: (01)정상 ProviderError 코드, (02)정상 SecurityError 코드, (03)허용된 StateConflict 단일 코드, (04)허용된 ValidationError 단일 코드, (05)MemoryError, (06)일반 RuntimeError에 코드 같은 문장, (07)임의 대문자 미등록 `.code`, (08)소문자 코드, (09)비밀/개행을 포함한 코드, (10)code getter 예외, (11)retryable getter 예외, (12)outcome getter 예외, (13)retryable=1, (14)retryable=None, (15)outcome_known=1, (16)outcome_known=None, (17)outcome 속성 없음, (18)known=True인 명시 REMOTE_OUTCOME_UNKNOWN, (19)retryable=True/known=False인 OOM, (20)알려진 COST_CAP_EXCEEDED 전파. 06~12에는 비밀 canary가 있으며 안전한 고정 코드 외 문자열 저장·표시가 없어야 한다. 18은 취소 ACK 경로에서도 UNKNOWN이어야 한다.

T01~18은 (01)빈 job_id, (02)None job_id, (03)빈 reason, (04)소문자 reason, (05)REMOTE_UNKNOWN을 pending API에 전달, (06)ABANDONED를 pending API에 전달, (07)reason/code 불일치, (08)미등록 code, (09)None code, (10)expected_version=True, (11)음수 version, (12)문자열 version, (13)fail retryable=1, (14)fail outcome_known=None, (15)capture DTO frame=-1, (16)capture DTO frame=True, (17)resume의 이전 expected_version, (18)resume의 미래 expected_version이다. 15/16은 안전한 관측 불가/REC 없음, 17/18은 StateConflict·상태 불변, API의 나머지는 ValidationError·상태 불변이 기대값이다. 구체 오류 문구 전체와 traceback을 oracle로 고정하지 않는다.

## 7. 기존 시험과 변경·보강 관계

아래는 node의 소스/기대값을 읽은 결과이며 이번 계약 단계에서 실행한 PASS 기록이 아니다.

| 기존 node/범위 | 기대값 변경/보존 | 새 family와 관계 |
| --- | --- | --- |
| `tests/integration/test_app_service.py::test_job_failure_and_cancel_do_not_end_recording` | 직접 OOM 실패 뒤 FAILED→BLOCKED(RESOURCE)/Attempt FAILED. 녹음 계속·원본 frame 기대값 유지 | D/F: 직접 store 호출과 runner의 차이 방지 |
| `tests/ui/test_gpu_runtime_ui.py::test_runtime_failure_is_tracked_per_install_in_this_run_only` | GPU_RUNTIME_DAMAGED의 FAILED→BLOCKED(RESOURCE). 설치별 현 실행 실패 기억·사용자 CPU 정책은 유지 | R/U/F: 같은 Job 재개인지 새 의미 요청인지 명시 대조 |
| `tests/unit/test_jobs.py::test_resume_known_blocked_preserves_identity_history_checkpoint_and_attempt_limit` | 5사유의 성공 fixture를 SQL 강제 주입 대신 실제 fail/block_pending으로 생성. ABANDONED는 실제 recover_abandoned 경로 | D/P/R. 부정 legacy SQL fixture 자체는 유지 가능 |
| `tests/unit/test_jobs.py::test_resume_undispatched_known_block_and_deleted_session` | 성공 fixture를 pending API로 생성하고 삭제 뒤 거부 유지 | P/R |
| `tests/unit/test_jobs.py::test_resume_rejects_unsafe_blocked_conditions` | UNKNOWN·취소·시도 상한·reader 미확인 거부 유지 | R/T |
| `tests/unit/test_runner.py::test_error_policy_retries_are_bounded_and_unknown_dominates` | TEMPORARY known 재시도3회·unknown1회 차단 유지 | D/C. 기존 이름을 일괄 FAILED로 바꾸지 않음 |
| `tests/unit/test_jobs.py::test_old_remote_marker_does_not_poison_recovery_of_a_known_unsent_retry` | UNSENT의 known retry 의미 유지 | D/R |
| `tests/property/test_job_case_space.py` Q21 | 기존 TEMPORARY/TIMEOUT와 UNKNOWN 모델의 의미 유지. 기존 분모를 이번 결과에 중복 합산하지 않음 | 새 D/R/P/C는 신규 표로 별도 감사 |
| `tests/ui/test_desktop_ui.py::test_end_to_end_record_pause_resume_stop_ui` | Source.start 안에서 PCM을 실제 수락하므로 REC 기대 유지. ready-only 시험이라고 잘못 정정하지 않음 | 새 V/O/E가 ready만·거부·무음·새 epoch를 검증 |
| `tests/unit/test_desktop.py::test_failed_start_preserves_partial_audio_and_safe_health`, `tests/integration/test_desktop_independent.py::test_partial_start_failure_waits_for_all_source_stops_and_keeps_media` | PAUSED·부분 원본·전체 source 종료 ACK 기대 유지 | O/E에서 REC 미표시와 결합 |
| provider/security 계약·G-P02·G-P06 | 안전한 코드와 권한·예산·UNKNOWN 보존. G-P06의 빈 production 가격 catalog/strict 차단을 정상 fixture로 속이지 않음 | N/D/U/F |
| G-P03/G-P04/G-P05 관련 회귀 | 선택 version·삭제·live owner·확정·대기 복원 계약 유지 | 변경 범위 밖 결과를 늦은 callback으로 덮지 않는지 확인 |

현재 읽기에서 확정한 상태 기대값 변경은 위 OOM/GPU_RUNTIME_DAMAGED 두 node와 실제 BLOCKED 생성 fixture다. `test_desktop_ui.py`의 REC 기대값 삭제는 필요하지 않으므로 기본 쓰기 목록에서 뺐다. 선행 push 뒤 다른 회귀 실패가 생기면 실제 node·오류·수정 이유를 보고하고 범위를 먼저 추가 승인받는다.

신규 시험 파일 5개를 제안한다.

| 파일 | 주된 family·계층 |
| --- | --- |
| `tests/unit/test_blocked_reasons.py` | D/P/N/T의 결정·타입·코드 집합, 직접 store API |
| `tests/property/test_blocked_reason_case_space.py` | D/R/P의 tuple manifest 및 제한 상태 모델, 원본/결과 불변 보강 |
| `tests/integration/test_blocked_reason_flow.py` | C/F, 독립 fake+실제 임시 SQLite/JobStore/runner, 취소·철회·삭제·reader ACK 양순서 |
| `tests/ui/test_blocked_reason_ui.py` | U, 실제 위젯 클릭·stale 선택·준비 미접수·권한/원장 부수효과 0 |
| `tests/ui/test_capture_start_ui.py` | V/O/E, Event 제어 fake source·현재 run/epoch·무음·부분 시작 실패 |

family를 여러 파일에서 교차 확인해도 의미 행 합계를 중복 증가시키지 않는다. 실행 manifest에는 대표 소유 node와 보강 node를 구분한다. bounded 순서 O는 이벤트 4개, E는 위 3단계 조합까지만 전수이며 더 긴 실제 스케줄·장치 동작은 미검증이다.

## 8. 임시 사본 mutation 계획

계획 **22개**, 아직 실행 0이다. 먼저 정상본의 목표 assertion PASS를 확인하고 하나씩 격리 변이한다. OS TEMP 사본에는 pyproject·src·tests·필요 scripts/packaging을 함께 복사하고, cwd/pythonpath/import `__file__`이 사본 src를 가리키는지 확인한다. 수집 실패·import 오류·권한 실패·timeout만으로 검출이라 세지 않는다. 각 결과에 mutant 소스 hash·명령·목표 실패 node를 남긴다.

| ID | 의도적 결함 | 목표 oracle |
| --- | --- | --- |
| M01 | outcome_known=False 우선순위 제거 | D/C의 UNKNOWN/Attempt UNKNOWN·비용 보존 |
| M02 | 명시 REMOTE_OUTCOME_UNKNOWN의 K=False 처리 제거 | D/N18 및 취소 ACK의 UNKNOWN |
| M03 | retryable=True이면 5사유보다 BACKOFF 우선 | D 5사유의 BLOCKED |
| M04 | CONSENT_POLICY_CHANGED를 AUTH로 오분류 | D/N 독립 code→reason 표 |
| M05 | runner만 분류하고 JobStore.fail은 옛 구현 유지 | 직접 OOM D 및 기존 앱 통합 node |
| M06 | BLOCKED 처리 중 reader active를 0으로 위조 | R/P/C의 active1 보존·재개 거부 |
| M07 | REMOTE_UNKNOWN 재개 허용 | R/U의 재송신 0 |
| M08 | 재개에서 시도 한도 검사 제거 | R h5의 거부·attempt 증가 0 |
| M09 | block_pending expected_version CAS 제거 | P의 이전/미래 version 거부 |
| M10 | 일반 예외 str(exc)를 코드/라벨에 복사 | N의 canary·unsafe 문자열 미노출 |
| M11 | 공통 provider 경로에서 CONSENT_POLICY_CHANGED/COST_* 소실 | N20/F의 구체 코드 전달 |
| M12 | 모든 COST_ prefix를 BUDGET 처리 | D의 COST_REQUEST_INVALID/AMOUNT_OVERFLOW FAILED |
| M13 | continue의 계획 불일치 때 암묵 새 Job 생성 | F/U의 CONTINUE_PLAN_CHANGED·dispatch 0 |
| M14 | 설정 화면 열기만으로 resume 실행 | U render/open의 상태/예약/송신 불변 |
| M15 | ready만으로 REC 표시 | V/O의 0 frame |
| M16 | 거부된 block의 미터를 수락 근거로 사용 | O/E 제출 반환과 REC 대조 |
| M17 | resume 후 이전 epoch accepted를 재사용 | E의 새 수락 전 REC 없음 |
| M18 | 이전 run callback token 검사 제거 | O/E의 종료/재개 표시 보존 |
| M19 | block_pending이 attempt_count를 0으로 초기화 | P/R의 이력·시도 한도 보존 |
| M20 | BLOCKED 전환이 checkpoint/result를 삭제 | D/R/F의 게시본·checkpoint 불변 |
| M21 | RESOURCE 행동이 CPU fallback/정책 변경 자동 수행 | U/F의 명시 정책·새 준비 필요 |
| M22 | 무음 양의 frame을 수락 0으로 취급 | V/E의 무음 수락 뒤 REC |

## 9. 후속 구현 쓰기 범위와 대안

승인 요청 파일은 **20개 = source 11 + 신규 시험5 + 기존 시험3 + 이 문서1**다. 지금 승인받아 쓴 것은 이 문서뿐이며 아래 제품 구현 권한은 아직 없다.

| 구분 | 정확한 파일 |
| --- | --- |
| 신규 source 2 | `src/recoryn/jobs/failures.py`, `src/recoryn/app/status.py` |
| jobs 수정 2 | `src/recoryn/jobs/__init__.py`, `src/recoryn/jobs/runner.py` |
| provider 수정 1 | `src/recoryn/providers/_common.py` |
| app 수정 2 | `src/recoryn/app/ai.py`, `src/recoryn/app/desktop.py` |
| UI 수정 4 | `src/recoryn/ui/main.py`, `src/recoryn/ui/ai_bridge.py`, `src/recoryn/ui/content.py`, `src/recoryn/ui/privacy.py` |
| 신규 시험 5 | `tests/unit/test_blocked_reasons.py`, `tests/property/test_blocked_reason_case_space.py`, `tests/integration/test_blocked_reason_flow.py`, `tests/ui/test_blocked_reason_ui.py`, `tests/ui/test_capture_start_ui.py` |
| 기존 시험 수정 3 | `tests/unit/test_jobs.py`, `tests/integration/test_app_service.py`, `tests/ui/test_gpu_runtime_ui.py` |
| 계약·결과 1 | `docs/testing/g07-blocked-reason-cases.md` |

`app/recording.py`·`content/store.py`·`storage/library.py`·`cli.py`·security modules·transport·실제 capture/backend·공용 설정·설계 정본은 범위 밖이다. 기존 `health_snapshot`과 새 DesktopRecorder 관측으로 현재 run 수락을 증명할 수 없는 실제 결함이 있으면 파일 추가 필요를 먼저 보고한다. G-P09로 넘길 새 DB 표는 없으며 기존 blocked_reason 열을 쓴다. 설계 문서의 결정 반영은 C00 소유다.

| 대안 | 장점 | 한계·권고 |
| --- | --- | --- |
| UI에서 FAILED를 BLOCKED처럼 번역만 하기 | 소규모 수정 | Job 재개·사유·시도/UNKNOWN 정책이 어긋남. 채택하지 않음 |
| runner에만 분류표 두기 | worker 연결 간단 | 직접 fail 호출이 편차로 남음. 공통 순수표+store 사용 권고 |
| retryable인 모든 코드를 계속 BACKOFF | 기존 broad 동작 유지 | 동의·예산·OOM 대기 우회, 미등록 SDK 오류 자동 재송신. 명시 일시 목록 권고 |
| 준비 실패마다 placeholder Job 만들기 | 모든 안내가 Job처럼 보임 | 불완전 plan/input 키·중복·권한을 새로 설계해야 함. 미접수 준비 안내 권고 |
| 같은 BLOCKED 재개 버튼 없이 매번 새 Job | 구현 작음 | 기존 resume 의미·checkpoint 활용과 구분이 불명확. 같은 계획 guard를 둔 명시 continue 권고 |
| 장치 ready 또는 첫 packet에서 REC | 관측 추가 적음 | 실제 수락 0·거부 block을 녹음으로 표시. 현재 run의 수락 counter 권고 |
| 파일 청크 확정 뒤에만 REC | 디스크 게시까지 관측 가능 | flush 전 실제 수락 녹음을 과도하게 대기로 표시. 이번 요구는 수락 기준이며 저장 내구성은 별도 표시 |

## 10. 구현 수락 게이트·현재 결과·승인 항목

후속 실행은 기존 오프라인 환경을 사용한다. 새 OS TEMP basetemp와 `QT_QPA_PLATFORM=offscreen`, `PYTHONDONTWRITEBYTECODE=1`, pytest `-p no:cacheprovider`를 지정한다. 실제 장치·네트워크·모델·계정·vault 호출 없이 fake 경계에서 실행한다. 모든 G-P07 신규 파일, 기존 jobs/runner/provider/security 회귀, `tests/ui` 전체, G-P03 선택 CAS, G-P04/G-P05 복구·삭제, G-P02/G-P06 계약 회귀를 포함한다. 가능하면 선행 push HEAD+승인 G-P07 파일만 담은 TEMP 사본에서 전체 오프라인 회귀를 한 번 돌린다.

필수 결과는 정상본 PASS, semantic case ID 4,490의 missing/duplicate/extra=0, skip=0, 계획22 mutation의 목표 assertion 검출/생존/무효 구분, ruff check·format check 및 `python -m mypy src/recoryn scripts packaging`다. 신규 시험5파일 합계 실행 시간과 명령을 측정한다. 60초를 넘으면 분모/입력 축약 전에 측정값·시간 원인·의미 행 보존 최적화안을 먼저 보고한다. node 수·행 수·실행 시간·tree/파일 hash를 분리해 기록하며 정상본 PASS 전 mutation 성과를 주장하지 않는다.

**현재 직접 수행:** 관련 문서·코드·시험 소스 읽기와 분모 설계. **현재 미실행:** 제품 변경, 신규 시험, 기존 회귀 재실행, mutation, 정적 검사, 실제 Windows 장치/원격 제공업체 검증. 이 문서는 기존 다른 배정의 PASS를 G07 PASS로 인용하지 않는다.

C00 승인 요청: (a) §3의 99코드+미등록 대표/UNKNOWN·취소·삭제 우선순위와 closed transient 강화, (b) pending API와 준비 미접수 표시·같은 계획 expected_job_id continue, (c) 현재 run의 양의 수락+전체 장치 준비 후 REC·epoch/late callback 차단, (d) 탐색/계속 분리 및 권한·가격·예산 자동 완화 금지, (e) 선행 4단위 push 뒤 20파일 직렬 수정, (f) 계획 4,490행/22 mutation·회귀/시간 게이트. 결정 전까지 제품 구현은 시작하지 않는다.

## §개정 요청(8e09b62·G-P06 반영)

### 대조 기준과 수행 범위

2026-11-23 C00의 읽기 위주 재대조 배정에 따른 **계약 개정 요청**이다. 앞의 승인 원문 299행(LF SHA-256 `fe53a0afff333b42f85f1e3095bbdb000e831e22be4c9609a6f03e9f7a771c0c`)은 변경하지 않았다. 원문의 승인 대기 표현은 당시 이력이며, C00은 그 뒤 (a)~(f)를 승인했다. 아래 추가 사항은 그 승인과 구별하여 다시 결정받는다. 제품·시험 구현은 시작하지 않았다.

- 실제 코드 근거는 `git show 8e09b62:<경로>`와 `git show 5317e250:<경로>`로 읽었다. 후자는 G-P06 검토 tree이며 push 완료본이나 독립 검토 승인본으로 간주하지 않는다. 작업 트리 src의 G-P05 변경은 근거로 사용하지 않았다.
- G-P05는 `docs/testing/g05-pending-deletion-cases.md` §2.2·§2.3·§3과 배정표 G05 행의 **계약·C00 결정**을 대조했다. 구현 중인 G-P05의 PASS나 실제 오류 전달을 확인했다는 뜻이 아니다. 배정표 확인 시 G05 행은 30행이었다.
- 아래 `tree:파일:행`은 해당 Git 객체의 줄번호다. 직접 한 일은 소스·시험 소스 읽기, 코드 집합·파일 목록·분모 산술 감사다. 기존 시험 실행·신규 시험·mutation·정적 검사는 이번 배정에서 모두 미실행이다.

### 1. 실제 오류 코드와 BLOCKED 사유 대조

BLOCKED의 기존 사유 집합은 유지한다. 알려진 원인의 `CONSENT/AUTH/CAPABILITY/RESOURCE/BUDGET` 5종과 기존 `ABANDONED/REMOTE_UNKNOWN`이며, 삭제 대기나 녹음 세션 live를 새 Job 사유로 만들지 않는다. `5317e250:src/recoryn/jobs/__init__.py:432`의 재개 허용 6종은 앞의 5종+ABANDONED이고 REMOTE_UNKNOWN은 계속 제외된다. 원문의 UNKNOWN·취소·삭제 우선순위도 유지한다.

| 점검 항목 | 직접 확인한 근거 | 개정 요청·판정 |
| --- | --- | --- |
| G-P06 비용 상한 코드 | `5317e250:src/recoryn/security/cost.py:21`의 `COST_CODES` 15개를 원문 §3.2 목록과 집합 대조. 누락 0·중복 0 | 13개는 BUDGET, `COST_REQUEST_INVALID/COST_AMOUNT_OVERFLOW` 2개는 F로 기존 분류 유지. COST_ prefix 전체를 BUDGET 처리하지 않음. 빈 실제 가격 catalog를 오류로 취급하거나 가격 항목을 추가하지 않음 |
| 동의 정책·범위의 factory 오류 | `5317e250:src/recoryn/ui/privacy.py:597`의 factory는 요청 범위를 확인하고 606행에 BUDGET_SCOPE_MISMATCH, 609행에 CONSENT_REQUIRED, 611행에 binding 검사를 수행. `5317e250:src/recoryn/providers/_common.py:211`은 COST_CODES와 일부 예산 코드만 보존하고 나머지를 221행 BUDGET_BLOCKED로 바꿈 | 원문 §3.1의 “typed COST_* 보존”을 **typed 동의 오류와 범위 입력 오류도 보존**하도록 명시 확장. CONSENT_POLICY_CHANGED·PERMIT_REVOKED·SESSION_REVOKED 등을 factory 단계에서 예산 부족으로 표시하지 않음. 미등록 factory 오류의 기존 안전 fallback은 유지 |
| gateway 오류의 전달 | `5317e250:src/recoryn/providers/_common.py:245` 허용 목록에는 CONSENT_POLICY_CHANGED·CONSENT_CLOCK_INVALID·DNS_TARGET_DENIED·REDIRECT_DENIED가 없고, 277행에서 REMOTE_OUTCOME_UNKNOWN으로 바뀜. 273~275행은 허용 코드의 outcome_known을 전달 | 두 경계(factory/gateway)를 각각 시험. 안전한 typed 코드만 전달하며, `outcome_known=False`를 True로 승격하지 않음. 전송 전 정책 변경은 CONSENT, 이미 결과 미상인 redirect 등은 계속 REMOTE_UNKNOWN. 코드 전달만으로 무전송·정산 완료를 추론하지 않음 |
| 동의 DTO·scope 입력 오류 | `5317e250:src/recoryn/security/consent.py:31`, `:50`, `:660`, `:684`, `:701`의 INVALID_CONSENT_CONTEXT·INVALID_CONSENT_SCOPE·INVALID_CONSENT_SCOPES·INVALID_CONSENT_BINDING·INVALID_SESSION_GENERATION | 아래 F 목록에 5개 추가. 잘못 구성된 요청을 동의 재발급·예산 증액으로 해결할 수 있는 BLOCKED로 승격하지 않음. 사용자 제공 문장이나 예외 메시지에서 문자열 추출 금지 |
| 미확정 오디오·전사 선행조건 | `5317e250:src/recoryn/app/ai.py:192`의 TRANSCRIPTION_REQUIRES_FINALIZED_AUDIO, `:449`의 SUMMARY_REQUIRES_COMPLETE_TRANSCRIPT는 Job 접수 전 거부 | P/CAPABILITY에 2개 추가. “실행 준비 차단·작업 미접수”로 표시하고 기존 확정/전사 화면으로 탐색. 자동 확정·전사·새 Job 생성 없음. `provisional=True`인 명시 live STT 경로를 이 검사로 차단하지 않음 |
| 삭제 대기·삭제·세션 소실 | `8e09b62:src/recoryn/storage/library.py:319`의 DELETE_PENDING, `5317e250:src/recoryn/jobs/__init__.py:503`의 JOB_SESSION_DELETED, `:511`의 JOB_SESSION_MISSING | F에 3개 추가. 삭제 대기는 동의 화면을 열어 계속할 사유가 아니며 준비/재개를 거부. 기존 SESSION_REVOKED·SESSION_DELETED도 F 유지. known 실패는 FAILED, 결과 미상은 REMOTE_UNKNOWN 유지 |
| live 관리 동작·보류 사유 | `8e09b62:src/recoryn/storage/library.py:323`·`:989`의 SESSION_LIVE/DELETE_PENDING. G-P05 계약 §2.3과 배정표 G05 행은 초기 live delete를 의도 기록 뒤 DELETE_PENDING/SESSION_LIVE로 보류하도록 결정 | SESSION_LIVE는 복구·확정·삭제 관리 동작의 보류 이유이며 AI Job의 새 RESOURCE 사유로 합치지 않음. 미확정이면서 live이면 “녹음 종료 후 확정”을 안내하고, 삭제 의도가 있으면 삭제 대기 안내를 우선. 이 결정이 G-P05에서 구현됐다고 아직 주장하지 않음 |

원문 §3.2에 더할 코드의 정확한 집합은 다음과 같다. 기존 코드의 분류 변경은 없다.

| 그룹 | 추가 코드 | 수 |
| --- | --- | ---: |
| P / CAPABILITY | TRANSCRIPTION_REQUIRES_FINALIZED_AUDIO, SUMMARY_REQUIRES_COMPLETE_TRANSCRIPT | 2 |
| F / known 입력·수명 실패 | INVALID_CONSENT_CONTEXT, INVALID_CONSENT_SCOPE, INVALID_CONSENT_SCOPES, INVALID_CONSENT_BINDING, INVALID_SESSION_GENERATION, DELETE_PENDING, JOB_SESSION_DELETED, JOB_SESSION_MISSING | 8 |

따라서 대표 입력 집합은 **100→110개 = 등록 109+미등록 대표 1**이다. 그룹별 수는 `C10/A3/P15/R17/B24/T8/F31/U2=110`이다. 이는 폐쇄된 대표 입력 표의 보강이며 모든 관리·SDK 오류의 전수 목록이라는 주장은 하지 않는다. 그 밖의 미등록 known 오류는 TASK_FAILED, 미확인 결과는 REMOTE_UNKNOWN이라는 기본값을 유지한다. 추후 G-P11의 표시 상태와 이번 catalog를 혼동해 미확인 메모리 추정만으로 실행을 막는 변경도 하지 않는다.

### 2. 삭제 권위와 재개 경계의 보강 요청

`8e09b62:src/recoryn/storage/library.py:206`의 삭제 권위는 DB와 journal의 합집합이다. 212행 DB 조회 뒤 213~226행 journal을 검사하며, 손상·미완성 이력은 실패한다. 반면 `5317e250:src/recoryn/jobs/__init__.py:493`의 `_session_live`는 SQLite의 deleted_sessions·sessions만 조회한다. 따라서 **JobStore의 현 검사만으로 journal-only 삭제 의도까지 확인한다고 쓸 수 없다**. `_live`의 232행 사람용 문장을 code로 복사하는 방법도 금지한다.

G-P05의 pending 목록은 정상 완료 tombstone을 제외하지만, 작업 입장 금지는 삭제 대기뿐 아니라 완료 tombstone·journal-only 의도도 포함해야 한다. pending 목록에 없다는 사실만으로 재개를 허용하지 않는다. 다음을 원문 §3.3~§3.5의 “유효 세션” 정의에 명시 추가하도록 요청한다.

1. 실행 준비·`block_pending`·`resume`·신규 claim은 유효한 DB/journal 삭제 의도, 완료 tombstone, 세션 소실이 있으면 차단한다. 이력 확인 불가도 허용으로 해석하지 않고 “삭제 이력 확인 불가·준비 미접수/계속 불가”로 표시한다. 삭제 의도 존재와 단순 녹음 live는 다른 조건이다. live STT는 계속 허용된 경로다.
2. 삭제 뒤 기존 attempt의 종료 ACK는 계속 받아들인다. `5317e250:src/recoryn/jobs/__init__.py:690`의 cleanup 의미를 보존하며, known은 FAILED, unknown은 REMOTE_UNKNOWN이다. 이력 검사 예외로 reader 종료 ACK를 막거나 ACK 없이 reader를 inactive로 위조하지 않는다.
3. **구현 전 남은 연결 결정:** G-P05 최종 push tree의 읽기 전용 삭제 권위 경계를 다시 대조한다. journal 열거를 GUI thread나 JobStore SQL transaction/root mutex 안에 새로 넣지 않는다. 삭제와 재개의 경쟁에서 권위 재확인을 빠뜨리지 않되 잠금 역순을 만들지 않는 연결 방식을 먼저 고정한다. 승인 20파일 안에서 이를 보장할 수 없으면 필요한 helper·파일·경쟁 반례를 C00에 보고하고 범위 승인을 받는다. 현재 G-P05 작업 트리를 보고 API가 이미 있다고 가정하지 않는다.

이 보강은 Job 입장·표시의 계약이다. G-P05 §3.2의 고아 reader 종료 자동 증명, §3.3의 별도 library.sqlite DB-only tombstone을 ConsentStore가 보지 못하는 **직접 Gateway 보안 경계**까지 G-P07에서 해결한다고 확장하지 않는다. 두 후속의 소유권과 UNKNOWN 비용 보존은 유지한다.

### 3. 현재 AI 접수·비용 snapshot과 계속 실행

`5317e250:src/recoryn/app/ai.py:103`은 같은 키로 찾은 BLOCKED Job의 사유가 허용 6종이면 111행에서 곧바로 resume한다. 원문에서 요구한 명시 계속 버튼만 추가하고 이 경로를 남기면 live tick·중복 요청이 알려진 BLOCKED를 암묵 재개할 수 있다. 따라서 기존 `_admit`의 이 경로도 **명시 expected_job_id/version을 검증한 계속 실행**과 분리한다. 일반 중복 접수는 기존 BLOCKED를 관찰할 뿐 새 attempt·예약·dispatch를 만들지 않는다. ABANDONED의 명시 재검사와 원문 R 가족의 reader/한도 조건도 유지한다.

G-P06 실제 factory는 `CostRequest` 한 인자를 받는다(`5317e250:src/recoryn/ui/privacy.py:597`). G-P07의 context wrapper도 이 서명을 유지하며 옛 인자 수 fallback을 만들지 않는다. 비용 quote·동의 binding은 매 요청 새 실행 snapshot으로 확인한다. `5317e250:src/recoryn/ui/privacy.py:510`의 config_key에는 비용 모드·통화·기간·cap·가격 digest·동의 scope·정책 version이 없다. 이를 G-P07에서 추가하지 않는다. 새 권한·비용 snapshot으로 같은 의미 계획을 계속할 수 있어야 하며, 정책 값만 바뀌었다고 처리한 실시간 청크 재전송이나 checkpoint 상실을 만들지 않는다.

### 4. REC 조건·기존 시험 기대값·공유 UI

REC에 관한 승인 조건과 원문 V/O/E 분모는 변경하지 않는다. 직접 확인한 근거는 다음과 같다.

- `8e09b62:src/recoryn/app/desktop.py:93`은 submit 반환과 meter를 따로 다루며, 101행의 meter는 거부된 block에도 갱신된다. 따라서 meter/ready는 수락 증명이 아니다. `8e09b62:src/recoryn/app/recording.py:79`의 health_snapshot과 154행의 accepted_frames를 현재 run/epoch에 한정해 관찰해야 한다. RecordingService의 제품 코드 수정 권한은 추가하지 않는다.
- `8e09b62:src/recoryn/ui/main.py:391`·`:404`는 시작/재개 완료 콜백에서 곧바로 REC를 표시한다. 이를 원문 §5의 공통 투영으로 연결해야 한다. `8e09b62:src/recoryn/app/desktop.py:159`의 시작 실패 처리와 CAPTURE_START_FAILED_ACK_PENDING을 보존하고, ACK 대기를 PAUSED나 정지 성공으로 표시하지 않는다.
- 실제 기대값 변경 대상도 여전히 있다. `8e09b62:tests/integration/test_app_service.py:200`의 OOM→FAILED assertion(201행), `8e09b62:tests/ui/test_gpu_runtime_ui.py:182`의 GPU_RUNTIME_DAMAGED→FAILED 기대는 RESOURCE/BLOCKED로 바꿔야 한다. 다른 미실행 시험이 통과한다고 선인정하지 않는다.
- ui/main.py의 G-P04 비동기 목록·조회 세대·관리 작업 claim·세션별 검사 실패 처리와 G-P05의 pending worker·선택 해제(None) 전달·명시 재시도를 보존한다. REC/차단 안내 구현을 위해 과거 동기 목록 조회를 복원하거나 녹음 writer가 쓰는 root mutex에서 무거운 검사·UI 대기를 만들지 않는다. G-P15 writer seal 지연을 G-P07이 해결했다고 주장하지 않는다.

### 5. 시험 분모 개정 요청과 독립 oracle

원문 11가족의 산술은 직접 재계산하여 **4,490행과 일치**했다. 다만 위 10개 코드를 추가하면 D 가족의 분모가 바뀌고, provider 경계 및 삭제 권위·암묵 재개의 관측이 별도 필요하다. 다음 **4,947행**을 새 계획으로 요청한다. 아직 실행 node나 PASS 수가 아니다.

| 가족 | 개정 후 산식·의미 | 행 수 | 원문 대비 |
| --- | --- | ---: | ---: |
| D | 110 codes × retryable2 × known2 × attempt count3 × session2 | 2,640 | +240 |
| R | 원문 재개 사유·상태·이력·cancel·session 분할 유지 | 960 | 0 |
| P | 원문 block_pending 상태·CAS·session·이력 분할 유지 | 360 | 0 |
| C | 원문 취소 ACK 순서 분할 유지 | 72 | 0 |
| F | 원문 같은 계획/새 binding/변경 의미 키·reader 분할 유지 | 30 | 0 |
| V | 원문 REC 표시 정적 조합 유지 | 288 | 0 |
| O | 원문 callback 순서 조합 유지 | 120 | 0 |
| E | 원문 epoch·늦은 callback 조합 유지 | 72 | 0 |
| U | 원문 UI 탐색/계속·UNKNOWN 확인 분할 유지 | 150 | 0 |
| N | 원문 예외 정규화 20개 유지 | 20 | 0 |
| T | 원문 타입·version 18개 유지 | 18 | 0 |
| W（추가） | 43개 안전 typed 코드 × factory/gateway2 × outcome_known2 | 172 | +172 |
| L（추가） | 삭제 권위7 × 입장 동작3 + 삭제 권위7 × 종료 ACK known2 | 35 | +35 |
| A（추가） | 알려진 BLOCKED 사유5 × STT/summary2의 일반 중복 접수 | 10 | +10 |
| 합계 | 4,490 + 240 + 172 + 35 + 10 | **4,947** | **+457** |

W의 고정 43개는 원문 C10+B24, COST_REQUEST_INVALID/COST_AMOUNT_OVERFLOW 2개, 위 INVALID_CONSENT_*·INVALID_SESSION_GENERATION 5개, SESSION_REVOKED 1개, LOCAL_EXECUTION_UNVERIFIED 1개다. factory/gateway의 주입 가능한 typed 오류 프로토콜을 검사하며, 실제 모든 backend가 각 코드를 발생시킨다고 주장하지 않는다. 둘 다 같은 입력과 outcome_known을 보존하는지를 판정하고, False이면 비용·전송 결과가 확인됐다고 승격하지 않는다. 기존 unknown factory fallback과 정규화 음성 행도 유지한다.

L의 권위 7개는 `VALID/DB-only DELETE_PENDING/journal-only 의도/DB+journal 의도/완료 tombstone/세션 소실/이력 확인 불가`다. 입장 3개는 resume/block_pending/claim이며 각 API가 동작 가능한 상태와 비활성 reader를 먼저 만든 뒤 권위를 주입한다. 종료 ACK는 유효한 RUNNING attempt로 시작한다. 동의 오류를 고정하여 known은 삭제 상태에서 FAILED, unknown은 REMOTE_UNKNOWN이라는 원문 우선순위를 비교한다. 정상 권위에서는 각 API의 정상 상태 전이를 요구하므로 전역 차단으로 통과하지 못한다. 이 35행은 권위와 경계의 조합이며 권위7×코드110 전수라는 주장은 하지 않는다.

A의 10행은 같은 의미 키의 BLOCKED Job을 만든 뒤 **expected_job_id/version 없는** 일반 재요청을 한다. Job 상태·attempt 수·예약·dispatch가 그대로여야 한다. 명시 계속은 기존 F/R/U 가족에서 새 snapshot·CAS·reader 조건과 함께 검증한다.

독립 oracle는 제품 catalog/분류 함수를 import하지 않고 코드→범주 표를 손으로 고정한다. wrapper의 코드는 fake가 입력한 값, Job/Attempt/outbox·reader 상태는 SQL/공개 관측, 송신·예약은 독립 fake 횟수로 비교한다. catalog 코드 수와 분모는 별도의 고정 상수로 검사한다. ID는 원문 G07 가족에 W/L/A를 추가하며 가족별 2,640/960/360/72/30/288/120/72/150/20/18/172/35/10의 기대 ordinal 집합과 누락·중복·추가 0을 대조한다. 경계 fixture를 공유해 시간을 줄이더라도 권위·reader·Job 상태가 다음 행으로 새지 않아야 한다.

원문 mutation 22개는 유지하고 M11을 factory/gateway 양쪽 관측으로 구체화한다. 다음 3개 추가로 **25개**를 요청한다. mutant 하나의 여러 목표 node를 여러 검출로 중복 계산하지 않는다.

| ID | 추가 결함 | 독립 검출 근거 |
| --- | --- | --- |
| M23 | factory typed 오류의 outcome_known=False를 True로 승격 | W의 False 보존·Job UNKNOWN |
| M24 | 입장 검사에서 journal-only 삭제 의도 누락 | L의 DB 부재/journal 존재에서 입장 0·기록 보존 |
| M25 | expected_job_id 없이 `_admit`가 알려진 BLOCKED를 resume | A의 attempt/예약/dispatch 불변 |

M11은 factory의 CONSENT_POLICY_CHANGED→BUDGET_BLOCKED와 gateway의 같은 코드→REMOTE_OUTCOME_UNKNOWN을 각각 변이해 관측해야 한다. 타입/임의 문자열 음성, pending 삭제 우선순위, 구체 COST_* 분류는 원문 mutation 목표와 연결한다. 정상본 PASS 전 검출률을 보고하지 않는다.

### 6. 쓰기 범위·착수 순서·결정 요청

쓰기 범위는 원문 **20파일 그대로** 요청한다. 파일 목록 중복 0을 직접 대조했다.

| 구분 | 파일 |
| --- | --- |
| 신규 source 2 | src/recoryn/jobs/failures.py, src/recoryn/app/status.py |
| jobs 2 | src/recoryn/jobs/__init__.py, src/recoryn/jobs/runner.py |
| provider 1 | src/recoryn/providers/_common.py |
| app 2 | src/recoryn/app/ai.py, src/recoryn/app/desktop.py |
| UI 4 | src/recoryn/ui/main.py, src/recoryn/ui/ai_bridge.py, src/recoryn/ui/content.py, src/recoryn/ui/privacy.py |
| 신규 시험 5 | tests/unit/test_blocked_reasons.py, tests/property/test_blocked_reason_case_space.py, tests/integration/test_blocked_reason_flow.py, tests/ui/test_blocked_reason_ui.py, tests/ui/test_capture_start_ui.py |
| 기존 시험 3 | tests/unit/test_jobs.py, tests/integration/test_app_service.py, tests/ui/test_gpu_runtime_ui.py |
| 문서 1 | docs/testing/g07-blocked-reason-cases.md |

이번 배정에서는 이 절 추가 외에 저장소 파일을 수정하지 않았다.

착수 조건은 기존처럼 G-P04·G-P05·G-P02·G-P06의 push와 C00 시작 신호다. 이번 고정 기준은 8e09b62이지만, 구현 착수 시 선행 단위를 포함한 최종 HEAD·공유 파일 hash를 다시 고정하고 특히 G-P05의 삭제 권위 연결을 재확인한다. 20파일 밖 변경이 필요하면 실제 근거와 추가 승인을 먼저 요청한다.

C00 결정 요청은 ①대표 코드 10개 추가와 factory/gateway 양쪽 경계의 typed 전달, ②DB/journal 삭제 권위에 대한 입장·ACK 계약 보강 및 G-P05 최종 API 확인, ③암묵 resume 금지 명시, ④계획 4,947행·mutation 25개로 증가다. REC 조건·5종 BLOCKED 사유·20파일 범위는 유지한다. 신규 시험 5파일의 60초 게이트도 유지하며 G-P06의 120초 특례를 적용하지 않는다. 현재 제품 변경·시험 실행·신규 구현 완료를 주장하지 않는다.


## 착수 기록·삭제 권위 helper 요청 (68fbbda)

### 기준과 파일 동결

C00의 G-P07 구현 시작 신호로 착수했다. 기준은 `68fbbda5ac73e3b7d6486343ec15e630d6866269`이며, 승인 원문과 개정 요청의 LF SHA-256은 `aea79c0ef55e5f417641412107a1b585134b2f3d450ab470c508a3aaaed81b85`다. 승인된 20파일만 수정한다. 추적 파일 12개의 시작 바이트를 HEAD와 LF 기준으로 대조하여 모두 같음을 확인했다. 신규 source/시험 7개는 없었고, 이 계약 문서는 미추적 상태로 존재했다.

시작 사본·20파일 목록·해시는 OS TEMP의 `recoryn-g07-617b634e33364d388f8e8e9c01a24959/{before/,before-manifest.json,scope.json,head.tar}`에 보관했다. 별도 작업자의 G-P15 및 G-P06b 변경은 읽기/격리 대상일 뿐 이 단위 사본에 넣지 않는다. 구현 작성과 최종 독립 승인은 구분한다.

| 허용 파일 | 시작 LF SHA-256/상태 |
| --- | --- |
| `src/recoryn/jobs/failures.py` | `신규 예정` |
| `src/recoryn/app/status.py` | `신규 예정` |
| `src/recoryn/jobs/__init__.py` | `7949f880b00b894aaa6896c117563f3a6473bf851521f143710848033446af89` |
| `src/recoryn/jobs/runner.py` | `a63c10bc131875e63055f06eec216bc212ab04432fcfed643b9de504a084e557` |
| `src/recoryn/providers/_common.py` | `310a2f958a1745a69e320030e287ab791795965ad668c9f21fbdd3091c4e363b` |
| `src/recoryn/app/ai.py` | `dd6291ce65292230e4deaa8516f9356e09c6d1ff6aca71049dcd1721984d03c5` |
| `src/recoryn/app/desktop.py` | `d36adbd4a635643e9bc88b5e595fe512b2084102ae902961c22db24139c954f1` |
| `src/recoryn/ui/main.py` | `8c92a483b78cbd57377fc28863ff05a8d8df1528c008e8a9d6cd4a5dc3a6649b` |
| `src/recoryn/ui/ai_bridge.py` | `725db065d0eeda327736a262b646d9aa46f7a04779f360d3bd6835afc9ff0a3c` |
| `src/recoryn/ui/content.py` | `341c952ddd4eb67c3847e4a14dcac4d0afb32cb65d50feb4f6fa390992c6455a` |
| `src/recoryn/ui/privacy.py` | `474588f59ff676c1ae85136bbda95cfa4238aac8cfba333bf06eaee3d6fe007f` |
| `tests/unit/test_blocked_reasons.py` | `신규 예정` |
| `tests/property/test_blocked_reason_case_space.py` | `신규 예정` |
| `tests/integration/test_blocked_reason_flow.py` | `신규 예정` |
| `tests/ui/test_blocked_reason_ui.py` | `신규 예정` |
| `tests/ui/test_capture_start_ui.py` | `신규 예정` |
| `tests/unit/test_jobs.py` | `4ed55bd4f1d4c0ff71044bfbd70dcef6b05412e410f2f9722e41f5942bf67a57` |
| `tests/integration/test_app_service.py` | `f9ba4a195327ba2594a79547deebf0abb98b2c8e9999d39073a756f27d7e9fce` |
| `tests/ui/test_gpu_runtime_ui.py` | `c63a533ed118e7e4efb7939297e0db97ae1c12a94c32c5c4896547a300d61cc9` |
| `docs/testing/g07-blocked-reason-cases.md` | `aea79c0ef55e5f417641412107a1b585134b2f3d450ab470c508a3aaaed81b85` |

### 삭제 권위 연결: C00 결정 대기

`68fbbda:storage/library.py`의 `deletion_generation`은 DB와 journal의 최대 세대를 반환하지만 반환 전에 root mutex를 해제한다. `pending_deletions`는 완료 tombstone을 제외하므로 삭제 권위의 대체물이 아니다. `_journal_prefetch`는 root 밖에서 journal을 읽지만, `_deletion_history`는 세대가 달라지면 root 안에서 재열거할 수 있다. 이 세 API를 Job transaction 안에서 호출하거나 GUI 조회에서 재사용하지 않는다.

실제 TEMP 사본의 재현 결과(`authority-proof.json`): 새 세션 s와 QUEUED/알려진 BLOCKED/RUNNING Job을 만든 뒤, DB 삭제 행 없이 정본 journal에 세대 1 의도를 게시했다. Library의 관측은 `deletion_generation=1`, DB 행은 0이다. 현재 JobStore의 DB 전용 검사로는 다음 결과가 나온다.

| 호출 | 실제 결과 | 승인 계약의 기대 |
| --- | --- | --- |
| claim | RUNNING 수락 | 입장 거부·시도 불변 |
| block_pending | BLOCKED 수락 | 입장 거부·상태 불변 |
| resume | QUEUED 수락 | 입장 거부·상태 불변 |
| known CONSENT_REQUIRED 실패 ACK | BLOCKED(CONSENT) | FAILED; reader 종료 ACK는 허용 |

이는 현 구현의 미해결 경계이며 PASS로 집계하지 않는다. journal-only가 없다는 가정이나 한 번의 검사 뒤의 TOCTOU를 동의 신선도처럼 취급하지 않는다.

**요청하는 경계**: G-P15 push 이후 삭제 권위 소유 계층의 canonical guard를 별도 배정한다. guard는 journal 검증/색인 준비를 root mutex 밖에서 하고, root 안에서 세대/권위를 재확인하여 짧은 Job transaction 동안 권위를 유지해야 한다. 세대가 바뀌면 root 밖으로 나가 다시 준비한다. Job 잠금을 잡고 root를 기다리는 역순을 만들지 않는다. 손상 이력은 입장을 막으며, 실패/reader 종료 ACK는 삭제·손상 이후에도 허용하고 UNKNOWN을 보존한다. API와 새 기준 tree는 C00이 확정한다. Library/_coordination 수정 권한은 아직 없으며 해당 파일은 수정하지 않았다. 독립적인 JobStore 분류·UI·REC 작업은 계속한다.

L 35행과 M24는 이 연결을 실제로 구현한 뒤 검증한다. 나머지 분모나 실패 행을 줄여서 완료로 보고하지 않는다.

### 화자 경로의 사실 정정 제안

원문 §3의 화자 설명과 달리 기준 tree의 `ui/ai_bridge.py:diarize`는 이미 `service.jobs.create("diarization", ...)`, 세션 바인딩, runner 및 G-P03 게시 CAS를 사용한다. 새 화자 Job 시스템을 만들지 않고 기존 Job의 사유와 설정 탐색은 제공한다. 전사/요약의 동일 계획 계속 API를 화자에 새로 만드는 것은 이번 구현으로 선결하지 않는다. 화자 계속 버튼 비활성 및 원문 설명 정정에 대해 C00 결정을 요청했다. 기존 화자 원문·CAS·명시 모델/라이선스 조작을 보존한다.

### 중간 검증 기록 (최종 완료 판정 아님)

- 공통 `jobs/failures.py`의 폐쇄 목록과 직접 `JobStore.fail`, runner 정규화를 연결했다. UNKNOWN이 삭제·사유·retryable보다 우선한다. QUEUED용 block_pending과 resume의 expected_version CAS를 추가했으며 이전 attempt의 논리 종료와 reader ACK를 따로 확인한다.
- `_admit`의 암묵 resume을 제거했다. 명시 계속은 기존 Job의 세션·kind·input_key/version을 확인한 뒤 같은 Job에만 입장한다. UI의 탐색은 실행/동의/비용/CPU 정책 변경을 하지 않는다.
- 현재 run의 실제 양의 submit 수락과 전체 장치 준비를 REC의 필요조건으로 연결했다. fake source의 거부·무음·이전 run/epoch 콜백·종료/재개를 검증한다. 실제 장치·모델·네트워크 검증으로 집계하지 않는다.
- 첫 신규 5파일 선택 실행은 **5,028 PASS / 5.37초**였다. 이 시점의 의미 행은 L을 제외한 **4,912/4,947**이며, 직접 store·census 등의 보강 node는 의미 분모에 중복 합산하지 않았다. 이후 보강/정적 수정 뒤의 최종 node·시간은 별도 다시 측정한다.
- `HEAD 68fbbda + 당시 G-P07 허용 파일만`인 TEMP archive에서 기존 UI 전체와 jobs/runner/content/G-P03/앱 서비스 관련 **1,563 PASS / 136.63초**, ResourceWarning 오류 0. 초기 14개 UI 실패는 테스트 더블에 새 panel 속성을 요구한 제품 selection 연결을 정정하여 해결했으며 범위 밖 fixture는 수정하지 않았다.
- 임시 사본의 **논리 mutation 24/25 검출**. M11의 factory/gateway 두 변형 때문에 실행 변형 수는 25개이며 이를 25/25로 부풀리지 않는다. M24는 삭제 권위 연결 대기다. `mutation-results.json`과 M01~M25 로그에 명령·판정·시간을 보관했다. import/syntax/수집 실패를 검출로 세지 않았다.
- 별도 실제 runner 보강 5행은 각 BLOCKED 사유에서 같은 Job의 명시 계속과 성공, 다른 세션 녹음의 수락 지속·원본 frame 보존을 확인했다. 실제 MainWindow도 ready-only/submit 거부 뒤 시작 중, 첫 무음 수락 뒤 REC, resume 뒤 새 수락 전 REC 금지를 통과했다.
- 첫 전체 오프라인 CI 동형 coverage 실행은 같은 TEMP archive 사본에서 진행 중이다. 최종 20파일 hash, 4,947행 감사, M24, 독립 검토 및 최종 CI 전 묶음 PASS는 아직 완료가 아니다.


## 중간 검증 보강·추가 범위 요청 (2026-11-24)

### 삭제 권위 35행의 독립 반례

앞 절의 canonical guard 요청 근거를 35행 TEMP 반례로 확장했다. `test_authority_contract.py`를 `prepared/src`에 연결하여 실행한 결과는 **27 PASS·8 FAIL / 1.15초**다. 실패는 journal-only 및 이력 확인 불가의 claim/block_pending/resume 세 입장과 known 실패 ACK이다. 해당 ID는 G07-L-07/08/09/19/20/21/26/34다. DB-only DELETE_PENDING·DB+journal·완료 tombstone(DELETED_LOCAL)·세션 소실의 차단, 정상 권위의 허용, 모든 권위의 unknown ACK 보존·reader ACK 허용은 이 반례에서 통과했다.

이는 보안 경계를 수정한 완료 증거가 아니라 **현재 결함을 보여 주는 정상본 반례**다. 제품 시험에는 L35를 아직 옮기지 않았다. 제품 5파일의 승인 의미 ID는 4,912개이며 L35를 합친 TEMP 수집 감사는 4,947개, 누락/중복/추가 0이다. 그중 L35는 27 PASS·8 FAIL이므로 전체를 PASS로 보고하지 않는다. 근거는 `case-audit-combined-interim.json`, `authority35.log`다. M24는 정상본의 이 8건을 닫은 뒤 실행해야 하므로 아직 NOT_RUN이다.

기준 코드 위치는 `68fbbda:src/recoryn/storage/library.py:233`(_journal_prefetch), `:242`(_deletion_history), `:1111`(deletion_generation) 및 `68fbbda:src/recoryn/jobs/__init__.py:493`(DB 전용 _session_live)이다. 라이브러리 guard의 소유권·공개 API·G-P15 이후 기준 갱신은 C00 결정 대기다. protected 파일을 직접 수정하거나 private journal/잠금을 복제하지 않았다.

### 기존 시험 fixture 추가 승인 요청

첫 정확한 격리 사본의 전체 실행은 **20,065 PASS·1 FAIL / pytest 1,165.05초**였다. harness 벽시계는 1,173.578초다. 실패는 다음 한 node이다.

`tests/integration/test_publication_independent.py::test_stale_ack_cannot_clear_replacement_reader_and_default_recovery_cannot_clear_live_reader`

기준 `68fbbda`의 해당 파일 **296행**이 `jobs.fail(..., "RETRYABLE", retryable=True)` 뒤 reader ACK 후 새 claim을 기대한다. 미등록 RETRYABLE은 승인된 폐쇄 표에서 FAILED이므로 새 claim이 `job is not claimable`로 거부되는 것이 현재 계약상 맞다. reader 교체와 stale ACK라는 원래 시험 목적은 등록된 일시 오류 TEMPORARY로 보존할 수 있다. **이 한 fixture 문자열만 RETRYABLE→TEMPORARY로 바꾸도록 추가 쓰기 범위를 요청**했다. 해당 파일은 아직 수정하지 않았다. 검토할 1행 diff는 TEMP의 `proposed-publication-fixture.patch`다. 미등록 SDK 오류를 BACKOFF로 승격하는 제품 변경으로 시험에 맞추지 않는다.

### coverage·선택 회귀·시간 게이트

전체 실행은 당시 `HEAD 68fbbda + G-P07 허용 파일만`인 `isolated/` 사본에서 다음 명령으로 수행했다. `initial-full-command.json`에 실제 인자를 보관했다.

```text
python -B -m pytest -q -p no:cacheprovider -W error::ResourceWarning --cov=recoryn --cov-branch --cov-report=json:coverage.json --cov-fail-under=85 --basetemp <TEMP 고유 경로>
python scripts/check_coverage.py coverage.json
```

pytest의 결합 coverage는 92.31%였으며, 별도 check_coverage 출력은 다음과 같다. 실패한 시험 1건과 coverage PASS를 구별한다. JSON의 측정 파일은 src/recoryn 아래 75개이며 tmp 사본 0개다.

```text
domain: line=100.00%/95% branch=100.00%/90% PASS
capture: line=99.85%/95% branch=98.57%/90% PASS
jobs: line=98.87%/95% branch=97.31%/90% PASS
storage: line=96.30%/95% branch=91.56%/90% PASS
security: line=98.11%/95% branch=94.43%/90% PASS
content: line=99.59%/95% branch=98.75%/90% PASS
all: line=93.79%/85% branch=87.85%/80% PASS
```

이 전체 실행 뒤의 UI 보강은 별도 `prepared/` 사본에서 확인했다. 최초 전체 source snapshot과 후기 UI 보강 snapshot을 같은 hash의 실행처럼 합치지 않는다.

| 직접 실행 | 결과·범위 |
| --- | --- |
| 최신 신규 5파일 단독 실행 | **5,064 PASS / 7.86초**, ResourceWarning 오류 0, skip 0. 의미 분모 4,912와 보강 152 node를 분리한다. L35는 이 실행에 없다 |
| 위 5파일의 JUnit testcase 시간 합 | unit 0.132 / property 1.897 / integration 1.644 / UI 사유 0.726 / UI 캡처 0.451 = **4.850초**. 60초 게이트는 pytest 7.86초로도 충족 |
| 후기 UI 전체 + jobs/runner/content/G-P03/앱 서비스 관련 | **1,593 PASS / 82.91초**, ResourceWarning 오류 0. status.py의 None 타입 좁히기만 이후 적용했고 관련 사유 UI 7행도 재확인했다 |
| ruff check . / ruff format --check . | prepared 사본 PASS / Python 175파일 format PASS |
| mypy src/recoryn scripts packaging | prepared 사본 88 source files PASS |
| M14/M21 후기 UI 재확인 | 실제 설정 열기에서 암묵 계속/CPU 정책 변경 두 변형 모두 KILLED. patch·명령·로그를 별도 보관. 기존 24개 논리 mutation에 중복 합산하지 않음 |

보강 node에는 직접 store의 checkpoint/reader 보존, 실제 1/2/3 Attempt 이력, 5사유 실제 runner의 같은 Job 계속과 독립 녹음, 실제 MainWindow의 요청 직후/장치 준비/거부/무음/일시정지/재개/정지 표시, 순수 사유 표시와 실제 privacy 초점, 가격 미상과 clock/미정산의 서로 다른 탐색, 준비 재차단 뒤 기존 Job 유지, 물리 inference worker의 종료 ACK, 명시 한도/reader 거부 설명을 포함한다. 이 보강을 승인 의미 분모에 중복 합산하지 않았다.

시작 요청 직후부터 시작 중을 표시하고, 일시정지·정지 요청은 worker 실행 전에도 REC를 억제한다. 종료 후 manifest 동기화 대기를 저장 완료로 덮지 않는다. 가격 근거가 없을 때 cap 입력을 해결책처럼 안내하지 않고 가격 근거 위치로 이동한다. clock/미정산은 기존 명시 확인 경로를 보여 줄 뿐 자동 완화하지 않는다. 논리 reader ACK가 끝나도 inference worker 핸들이 보류되면 계속을 막고, 명시 close의 실제 성공 후에만 보류 해제를 관측한다.

### C00 결정 필요와 중간 파일 동결

1. G-P15 push 뒤 canonical 삭제 권위 guard의 별도 배정/공개 API 및 기준 갱신. L 8건과 M24가 이 결정에 종속된다.
2. 위 기존 integration 시험의 fixture 문자열 1곳에 한정한 쓰기 범위 추가.
3. `68fbbda:ui/ai_bridge.py:398`의 기존 화자 Job이라는 사실을 계약 설명에 반영하고, 이번에는 표시·탐색만 제공하며 동일 계획 계속은 제외하는 제안의 확인.

위 결정 전에는 G07 IMPLEMENTATION_READY로 보고하지 않는다. 승인된 20파일 밖의 제품/시험 수정, G-P15/G-P06b 작업 파일 변경 및 Git 쓰기는 수행하지 않았다. 아래 hash는 **현재 중간 결과**이며 최종 검토 hash가 아니다. 이 문서의 최종 LF hash는 이 창의 보고와 TEMP manifest로 별도 제공한다.

| 중간 변경 파일 | LF SHA-256 |
| --- | --- |
| `src/recoryn/jobs/failures.py` | `9b39060f46eff9ec866684ed0a55f3e48a3a13a855564284f5e4683e60f63313` |
| `src/recoryn/app/status.py` | `50857f8ce14ce91519e59404cb719db99b83c0b23be6c23365a96032242e2d69` |
| `src/recoryn/jobs/__init__.py` | `4fea249be9e66d420413b60aed41a45429e79a0db415e54ef9b7a17beac1f9db` |
| `src/recoryn/jobs/runner.py` | `477e92ec3625981e9241986e5a222ae1aeaa8f928c17e3671884d6a20e262ace` |
| `src/recoryn/providers/_common.py` | `686e659ecd2a2202a5686f016f25d015657e811d2c9cf4ab89e6d7853a846647` |
| `src/recoryn/app/ai.py` | `4442a3f6e79689bbd47c3589b58eadb9348c24dd8048ca2a6cc14c945edef554` |
| `src/recoryn/app/desktop.py` | `7f49902d425f645757639f0465ffae2666a6af152326f677c46afd541192d021` |
| `src/recoryn/ui/main.py` | `e26f08bd42a3efd4077cbfc2feef996c3c3b69d034679b53880c6c8bd9618883` |
| `src/recoryn/ui/ai_bridge.py` | `79bb94b247427fd86e0fc253c5799c68fb6a8a47baf971924f7a16ff6db1e21c` |
| `src/recoryn/ui/content.py` | `a9bd22ff7fdcb8d51509c5b90730d627d1d6c9a9ad82813b78adbbb59bcdef2b` |
| `src/recoryn/ui/privacy.py` | `b90b3dcaa2c010c3f69218be3d8672b937739e79489386fb732161522d217e29` |
| `tests/unit/test_blocked_reasons.py` | `b4ab7f763d5ea05619ab4af7b977dc959b2cd1556dd173a3182cb5229206f80b` |
| `tests/property/test_blocked_reason_case_space.py` | `b61eb2b3edee4847bfa0f874f5a42c0e5ccde78064518cba34b94a459c2d201c` |
| `tests/integration/test_blocked_reason_flow.py` | `330ecd183e09119bfe4b25c85ac98bbd01a4f9abcfe5bf95d3d1425a17536b94` |
| `tests/ui/test_blocked_reason_ui.py` | `3936248771f5432dfbabbe3094873b805fbb97f948cd248d59fc17683399bc90` |
| `tests/ui/test_capture_start_ui.py` | `83bac3f5451753c075219df4a3a4602a7bd4a94001ddc1865a6b0abf2a0aaca4` |
| `tests/unit/test_jobs.py` | `fe14505de7f9d9039205fb0ab5014d61a0ebee73ff55f0aa3096205ac1caa78a` |
| `tests/integration/test_app_service.py` | `77d0a9d39e84829bed903d7cadc87dcda8eb01b4fc8d4f543e0eb8c538500007` |
| `tests/ui/test_gpu_runtime_ui.py` | `3ad13518e4b67b50fc599229ec0820d6590ff78e077764695600321d679116b6` |


## C00 범위 결정 반영·G-P15 전 단계 (0d846d6)

### 세 결정의 확인과 착수 조건

C00이 앞 절의 세 요청에 답했다. 이 절 이후에는 추가 범위 결정을 계속 대기 중인 것으로 해석하지 않는다.

1. **삭제 권위의 소유자는 storage/library.py**다. G-P15 push와 별도 C00 시작 신호 뒤 이 파일을 G-P07 범위에 추가한다. 허용 내용은 Job 입장·종료 ACK가 쓰는 읽기 전용 공개 API 하나와 그 연결이다. G-P15의 색인을 사용하고 journal 전체 열거를 GUI thread/root mutex/JobStore transaction 안에 넣지 않는다. private journal·잠금을 제품에 복제하지 않는다. 그때 기준을 G-P15 commit으로 갱신하고 L 8건·M24를 닫는다. **현재는 해당 파일의 수정 권한이 활성화되지 않았으며 수정하지 않았다.** 작업 트리의 G-P15 변경은 다른 작성자의 결과다.
2. `tests/integration/test_publication_independent.py`를 범위에 추가했다. 296행의 fixture **RETRYABLE→TEMPORARY 한 문자열**만 변경했다. 기존 바이트와 줄 단위 대조 결과 변경 줄은 [296] 하나이며 나머지 줄과 EOL은 보존했다. 단독 재실행은 **1 PASS / 0.40초**, ResourceWarning 오류 0이다. 읽기 ACK·교체 reader라는 독립 oracle와 나머지 assertion은 그대로다. 미등록 오류를 제품에서 일시 오류로 승격하지 않는다.
3. 기준 `68fbbda:ui/ai_bridge.py:398`에는 **이미 화자 Job이 존재**한다. 원문 §3의 ‘존재하지 않는 Job’ 설명은 사실 오류였으며 이 확인으로 정정한다. 이번 단위는 기존 화자 Job의 사유 표시·설정 탐색을 제공하고, 같은 계획 계속은 제외한다. C00이 이를 확인했다. `diarize` 함수의 AST를 0d846d6과 대조해 G-P03의 게시 CAS를 포함한 기존 본문이 보존됨을 확인했다. 새 화자 Job 시스템을 추가하지 않는다.

현재 활성 쓰기 범위는 **21파일(기존 20 + publication fixture 1)**이다. Library가 활성화되면 총 22파일이 된다. 공용 설정·다른 시험·G-P06b·G-P15 파일은 이번 단계에서 수정하지 않는다.

### 새 기준과 격리

C00 허용에 따라 기준을 **0d846d663919e4cea7bca0e1054bc0e81516259a**로 갱신했다. 68fbbda 이후의 G-P06b·GC-P02 결과를 포함하며 G-P07 20파일과 겹치는 기존 변경은 없었다. `git archive`로 TEMP에 별도 추출한 `head-0d846d6/`와 `phase-0d846d6/`를 사용한다. 후자에는 활성 21파일만 덮어 넣었고 archive의 나머지 추적 파일은 바이트 단위로 같음을 확인했다. 공유 작업 트리의 G-P15 코드를 검증 사본에 넣지 않았다.

fixture 변경의 LF SHA-256은 다음과 같다.

- 전: be0768e291bea77e85a91def58b59d3868854c6873d40d59d3efe177a0a1f046
- 후: 73093dd97214923c72c4f0313454482e106f71de64264d9120f8bb90a23fde7d

### L 가족의 단계별 이관

앞 절의 TEMP 35행을 그대로 완료로 집계하지 않고, 현재 구현으로 통과하는 **27행을 정식 integration 시험에 이관**했다. 정본 DB/journal 상태를 구별하고, 실패 ACK 이후에도 reader는 실제 종료 전까지 active이며 종료 ACK는 삭제·이력 이상 이후에도 허용됨을 확인한다. 별도 합성 canary 바이트도 보존한다. 이는 실제 음성 파일을 검증했다는 주장이 아니다. journal-only를 만들기 위해 시험 fixture가 정본 의도 게시 함수를 호출하며, 제품에 별도 journal parser나 잠금을 추가하지 않았다.

**L_WAITING={7,8,9,19,20,21,26,34}**를 명시하고 나머지 27개 ordinal만 실행한다. 이 8개를 skip/xfail 또는 PASS node로 만들지 않았다. 가족 계획은 **L35·전체 4,947행 그대로**이고, 현재 제품 시험의 의미 ID는 **4,939개**, 미구현 ID는 위 8개다. 27개 정식 행 + 분할 감사 1개는 **28 PASS / 1.80초**였다. 해당 명령의 -k 선택 때문에 publication node는 이 28개에 포함되지 않았고, 위 1 PASS는 별도 실행 결과다.

G-P15 시작 신호 뒤 이 보류 목록을 제거하고 같은 35개 ID를 모두 실행한다. 알려진 실패 ACK는 삭제/이력 확인 불가에서 FAILED, unknown ACK는 모든 권위에서 REMOTE_UNKNOWN이라는 oracle를 유지한다. 중간 목표를 맞추기 위해 분모를 줄이지 않는다.

### 최신 선택 실행·mutation

새 기준의 신규 5파일 단독 실행은 **5,092 PASS / 8.92초**, ResourceWarning 오류 0, skip/xfail 0이다. 의미 행 **4,939**와 별도 보강 **153 node**를 구별한다. 60초 게이트를 충족했다. JUnit은 `phase2-new.xml`, 명령 출력은 `phase2-new.log`에 보관했다.

임시 사본 `mutations-phase2/`에서 **M24 외 24개 논리 mutation을 모두 재실행·검출**했다. M11은 factory/gateway 두 변형이므로 실제 실행은 25개이고, 이를 25개 논리 결함으로 부풀리지 않는다. `mutate-phase2.py`에 재실행 harness를 저장했고 `mutation-phase2-results.json`에는 source/mutant hash·정확한 명령·시간·실제 결과를, `phase2-M*.patch/.log`에는 각 변이와 assertion 실패를 보관했다. import/syntax/수집 실패는 검출이 아니다. M24는 아직 NOT_RUN이며 Library 공개 API 연결 후 검증한다.

새 사본의 ruff check .·ruff format --check .는 모두 PASS(Python 175파일), mypy src/recoryn scripts packaging은 PASS(88 source files)다. G-P06b가 추가한 reserving catalog 결합 시험은 별도로 **4 PASS / 0.81초**를 확인했다.

이 단계의 전체 UI·보안·provider·G-P02·G-P03·jobs·reader 회귀는 별도 선택 묶음으로 실행한다. 앞 절의 68fbbda 전체 coverage 수치를 새 기준의 실행처럼 재사용하지 않는다. 최종 전체 오프라인·CI형 coverage 검증은 G-P15 기준 및 삭제 권위 연결을 마친 최종 사본에서 다시 실행한다.


### G-P15 전 단계 마감 기록

0d846d6 격리 사본의 추가 선택 회귀는 **4,313 PASS / pytest 182.79초**(harness 187.501초), ResourceWarning 오류 0으로 끝났다. 정확한 선택 목록과 명령은 `phase2-related-command.json`, 출력은 `phase2-related.log`, 종료 상태는 `phase2-related-result.json`이다. UI 전체·보안·provider·G-P02·G-P03·Job 상태 모델·게시/reader·원격 gateway 계약을 포함한다. 신규 5파일 결과와 겹치는 UI node를 합산하여 총 시험 수를 부풀리지 않는다.

`phase2-case-audit.json`의 실제 수집 결과는 계획 4,947 중 **4,939개**, 보류된 G07-L-07/08/09/19/20/21/26/34만 누락이며 **그 외 누락·중복·추가 0**이다. 신규 5파일은 총 5,092 node이고, 미구현 8개를 테스트 skip/xfail로 숨기지 않았다. 보류 목록과 분모를 대조하는 별도 보강 시험도 통과했다.

앞 절에서 실패했던 publication node는 승인된 문자열 변경 뒤 통과했고, 이 4,313개 회귀에도 포함되어 다시 통과했다. C00의 화자 설명 정정 확인과 기존 diarize 본문 보존도 기록했다. 현재까지 Library 공개 API는 추가하지 않았고 G-P15 파일 수정 명령을 실행하지 않았다.

**다음 작업은 G-P15 push 후 C00 시작 신호에 종속**된다. 그 신호 뒤 최종 G-P15 tree를 읽고 공개 삭제 권위 API와 Job 입장/ACK를 연결하여 L 8개와 M24를 닫는다. 이후 최종 기준으로 4,947행 감사·신규 시간 게이트·관련 회귀·전체 오프라인/CI형 coverage를 수행한다. 이 중간 기록은 G07 IMPLEMENTATION_READY나 최종 독립 검토 완료를 뜻하지 않는다.

현재 활성 21파일의 LF hash는 TEMP의 `phase2-ready-manifest.json`에 동결했다. Python source/시험은 검증 사본과 작업 트리가 바이트 단위로 같고, archive 기준의 허용 목록 밖 추적 파일 차이는 0이다. 문서에는 이번 마감 절을 추가한 뒤 별도 hash를 기록한다.


## G-P15 이후 연결·실행 기록 (90c6123)

### 최종 기준과 22파일 착수 동결

C00의 G-P15 push 완료 및 Library 착수 신호를 받았다. 기준을 **90c612378e0cdb991319098124f9139fac4817fd**로 갱신하고, 기존 20 + publication fixture + storage/library.py의 **22파일** hash를 `before-90c6123-manifest.json`에 동결했다. 수정 전 Library의 LF 바이트가 이 commit과 같음을 확인했다. 이제 Library는 이 단위 소유이며 G-P15b의 chunks/recording/seal 시험·문서는 쓰기 범위 밖이다.

검증 사본은 `head-90c6123.tar`를 추출한 `final-90c6123/`다. 허용 22파일만 반영했으며 공유 작업 트리의 G-P15b 변경을 포함하지 않는다. 실행 전 Python source/시험 hash를 `final-run-manifest.json`에 고정했다. 문서 추가만 실행 후 별도 hash로 보고한다.

### 하나의 공개 삭제 권위 API와 잠금 순서

`Library.job_authority(db_path, session_id)`는 context manager 형태의 읽기 전용 공개 API다. 판정은 VALID/DB_ONLY/JOURNAL_ONLY/BOTH/TOMBSTONE/MISSING/HISTORY_UNAVAILABLE의 폐쇄 집합이다. 열린 Library를 약한 참조로 찾으므로 새 DB/Library/OS 잠금을 만들지 않는다. Library 열기·닫기 연결을 추가했으며, 이미 닫힌 옛 객체가 새 소유자의 등록을 지우지 못한다. 소유자가 없거나 닫혔으면 HISTORY_UNAVAILABLE이다.

- 호출은 worker/control 경로다. 제품 UI의 탐색·render·tick은 이 API를 호출하지 않는다. DesktopAI의 준비 작업과 runner 입장/실패 처리에서 사용한다.
- 기존 G-P15 journal 검증 함수를 **root mutex 밖**에서 실행한다. index와 비교·entry 이름 준비도 밖에서 한다. 이 단계는 전체 이력 크기에 비례할 수 있으며 admission/ACK마다 한 번이다. 네트워크 write마다 반복하는 검사가 아니다. 총 조회가 O(1)이라고 주장하지 않는다.
- root 안에서는 준비 세대·현재 stamp·현재 소유자를 확인하고 G-P15의 기존 index를 재사용/갱신한다. 이 세션의 DB 행·세대·tombstone만 검증한다. 세대가 바뀌면 root 밖에서 다시 준비하며, 반복 변경은 3회 뒤 HISTORY_UNAVAILABLE로 끝낸다. root/Job transaction 안에서 journal을 재열거하지 않는다.
- 반환된 권위를 **짧은 Job transaction이 끝날 때까지** root mutex로 유지한다. JobStore는 먼저 Job 잠금 아래에서 불변 binding을 복사하고 잠금을 놓은 뒤 API를 호출한다. 획득 순서는 root → Job 잠금 → Job transaction이다. transaction 안에서 binding이 바뀌지 않았는지도 재확인한다. private journal parser나 root 잠금을 JobStore에 복제하지 않았다.
- claim/block_pending/resume 및 실제 reader 시작은 VALID만 입장한다. 이력 불명은 허용으로 해석하지 않는다. fail ACK는 삭제·소유자 종료·이력 불명에서도 실행하여 known은 FAILED, unknown은 REMOTE_UNKNOWN으로 정리한다. reader_finished는 기존의 실제 I/O 종료 ACK이며 삭제 상태와 무관하게 허용하고, logical failure가 active reader를 0으로 바꾸지 않는다.
- user_version=0의 독립 Job DB는 기존 DB 전용 계약을 유지한다. Library schema와 연결된 세션 Job은 현재 Library 권위가 필요하다. 승인 범위의 schema·원본·삭제 이력·cost history를 새로 쓰거나 정리하지 않는다.

회귀 근거는 L35와 보강 시험이다. 이력 확인 불가(소유자 없음/도중 close/미래 schema/잘못된 DB 상태·세대/더 새 세션/이동 stamp/반복 세대 변경), 새 소유자 보존, binding 경합, intent↔claim commit 선형화, claim 뒤 intent가 생긴 reader 시작 거부, 종료 ACK 허용을 검사했다. 구조 감시 시험은 Path.iterdir/os.scandir/os.listdir/remove_tree를 감시해 root mutex·Job transaction·Job 잠금 아래의 호출을 assertion으로 거부한다. 기존 G05/G15 구조·경합 시험은 최종 전체 묶음에서도 실행한다.

### 110코드·UI 보충 결정

C00의 G-P11 보충에 따라 표시 모델의 탐색 행동에 **execution_policy**를 추가했다. 현재 RESOURCE_GPU_UNAVAILABLE 안내가 기존 장치 실행 정책 control의 탭을 보여 주고 초점을 이동한다. 정책 값·저장·동의·예산은 바꾸지 않는다. 정책 저장은 G-P16 후속이며 새 저장 기능을 만들지 않았다. 실제 QWidget/QComboBox 시험으로 탭·초점 이동과 GPU_ONLY 값 보존을 확인했다.

C00의 G-P12 보충대로 **SUMMARY_PARTIAL은 등록하지 않았다.** 폐쇄 코드 109개 + 미등록 대표 1개의 **110 분할**과 승인 분모를 유지한다. provider partial 결과의 기존 revision/checkpoint 보존과 unknown 우선순위도 유지한다.

### L35·분모·mutation·자식 import 확인

- L_WAITING을 비우고 **35개 원 ID 전부**를 활성화했다. 각 행에서 독립 DB/journal 입력을 실제 공개 API의 7판정과 대조한 뒤 Job 입장/ACK 상태·reader·합성 canary를 검증했다. L35+분할 감사는 **36 PASS / 2.61초**였다.
- 최종 신규 5파일은 **5,116 PASS / 9.85초**, ResourceWarning 오류 0, skip/xfail 0이다. 계획 의미 **4,947행**과 별도 보강 **169 node**를 구별한다. testcase 시간은 unit 0.131 / property 1.597 / integration 3.393 / UI 사유 0.828 / UI 캡처 0.525 = 6.474초다. pytest 9.85초로 60초 게이트를 충족한다.
- `final-case-audit.json`의 실제 수집은 **4,947개, 누락·중복·추가 0**이다. 보류 8건은 모두 닫혔고 분모를 줄이지 않았다.
- 정상본 PASS 뒤 최종 사본의 **M1~M25 논리 25/25 검출**을 확인했다. M11 factory/gateway 두 변형 때문에 실제 변형 실행은 26개다. M24는 JOURNAL_ONLY를 VALID처럼 허용하는 변이이며 L 행이 거부·상태 불변/known ACK의 FAILED oracle로 검출했다. `mutate-final.py`, `mutation-final-results.json`, `final-M*.patch/.log`에 재현 명령·source/mutant hash·실제 assertion 실패가 있다. import/syntax/수집 오류를 검출로 세지 않았다.
- 격리 실행은 **PYTHONPATH=<final-90c6123/src>**로 고정했다. 실제 자식 Python이 가져온 jobs, storage.library, app.status의 __file__이 모두 사본 src 아래임을 assertion으로 확인하고 `final-child-imports.json`에 저장했다. .venv editable 설치가 작업 트리를 대신 가져오는 것을 허용하지 않았다.
- 최종 사본의 ruff check . / ruff format --check .는 PASS(177 Python 파일), mypy src/recoryn scripts packaging은 PASS(88 source files)다.

동일 사본에서 `--cov=recoryn --cov-branch --cov-report=json:coverage.json --cov-fail-under=85`, `-p no:cacheprovider`, `-W error::ResourceWarning`, offscreen 및 고유 TEMP basetemp로 전체 오프라인 회귀를 실행 중이다. 그 뒤 check_coverage.py 전 묶음을 확인한다. 아직 실행 중인 전체 결과를 완료로 쓰지 않는다.


### 디스크 입력과 캐시의 독립 대조 보강

첫 90c6123 전체 실행은 **20,294 PASS / 1,168.22초**(harness 1,175.013초), ResourceWarning 오류 0으로 끝났고 check_coverage 전 묶음도 PASS였다. 이 결과의 사본은 `final-90c6123/`다.

검토 중 journal-only fixture가 정본 게시 함수를 통해 메모리 index까지 함께 갱신하면, 디스크에만 존재하는 의도를 index에 반영하는 경로를 독립적으로 확인하지 못한다는 점을 보강했다. 기존 **G07-L의 journal_only 입력만** 유효한 journal JSON 리터럴을 디스크에 기록하는 방식으로 바꿨다. DB+journal 입력은 기존 게시 경로를 유지하여 두 경로를 함께 확인한다. 기대값은 같은 JOURNAL_ONLY·입장 거부/known FAILED이며, 35개 ID·전체 분모 4,947은 바뀌지 않는다. 제품 코드는 변경하지 않았다.

추가 보강 1행은 다른 세션의 기존 journal 파일 내용만 손상시켜 **디렉터리 stamp가 그대로**임을 확인한 뒤, 정상 세션의 조회/입장도 HISTORY_UNAVAILABLE로 보류되는지를 검사한다. 따라서 G-P15 index만 믿고 원문 검증을 생략하는 결함이 드러난다. 제품의 전체 원문 검증을 worker/root 밖에 둔 이유이며, 초기화/전송을 자동 허용하는 최적화로 바꾸지 않는다.

최신 `final-v2-90c6123/` 사본의 신규 5파일은 **5,117 PASS / 10.83초**이고, 의미 4,947행 + 보강 170 node를 구별한다. ResourceWarning 오류·skip·xfail은 0이며 60초 게이트를 충족했다. ruff check/format(177파일)·mypy(88 source files)도 PASS다.

이 사본에서 계획 M1~M25를 다시 실행해 **25/25 검출**했다(M11 두 변형으로 계획 실행 26개). 추가로 **AUX-CACHE-REFRESH**(검증된 디스크 의도를 index에 반영하는 대입 제거), **AUX-HISTORY-VALIDATION**(원문 검증 대신 cached journal만 사용)도 각각 검출했다. 계획 25개와 보강 2개를 구분하며 실제 변형 실행은 총 28개다. `mutate-final-v2.py`, `mutation-final-v2-results.json`, `final-v2-M*.patch/.log`와 `final-v2-AUX*.patch/.log`가 근거다.

최신 시험 파일 hash까지 포함하는 같은 22파일 사본에서 CI형 전체 검증을 재실행한다. 이전 전체 PASS와 최신 신규/변이 PASS를 합쳐 같은 트리의 전체 PASS처럼 쓰지 않는다. 최신 전체 로그는 `final-v2-full.log`, 실제 명령은 `final-v2-full-command.json`이다.


## G07 최종 구현·검증 결과 — IMPLEMENTATION_READY

### 최종 결과와 적용 범위

기준은 **90c612378e0cdb991319098124f9139fac4817fd + 아래 22파일**이다. `final-v2-90c6123/` 사본의 전체 오프라인 회귀는 **20,295 PASS / 1,196.55초**(harness 1,202.795초), 실패·ResourceWarning/기타 warning 요약·skip·xfail 0으로 끝났다. 아래 명령은 CI와 같은 coverage 옵션과 검사기를 사용했다. 원격 CI를 실행하거나 통합 push한 결과가 아니라, 이 기준의 로컬 Windows/Python 3.13.1 검증이다.

```text
PYTHONPATH=<TEMP>/final-v2-90c6123/src
QT_QPA_PLATFORM=offscreen
python -B -m pytest -q -p no:cacheprovider -W error::ResourceWarning --cov=recoryn --cov-branch --cov-report=json:coverage.json --cov-fail-under=85 --basetemp <TEMP 고유 폴더>
python scripts/check_coverage.py coverage.json
```

`final-v2-full-command.json`, `final-v2-full.log`, `final-v2-full-result.json`, `final-v2-coverage-check.log`가 실제 명령·출력·종료 상태다. coverage JSON은 src/recoryn 아래 **75파일**만 측정했고 tmp 사본 **0개**다. pytest의 결합 coverage는 **92.47%**이며, check_coverage 출력은 다음과 같다.

```text
domain: line=100.00%/95% branch=100.00%/90% PASS
capture: line=99.85%/95% branch=98.57%/90% PASS
jobs: line=98.92%/95% branch=97.42%/90% PASS
storage: line=96.51%/95% branch=92.43%/90% PASS
security: line=98.11%/95% branch=94.43%/90% PASS
content: line=99.59%/95% branch=98.75%/90% PASS
all: line=93.90%/85% branch=88.15%/80% PASS
```

- 신규 5파일: **5,117 PASS / 10.83초**, skip/xfail/ResourceWarning 오류 0. testcase 합은 unit 0.131 / property 1.497 / integration 4.735 / UI 사유 0.706 / UI 캡처 0.544 = **7.613초**다. 단독 pytest의 10.83초로 60초 게이트를 충족했다.
- 계획 의미 행은 **4,947**, 최신 실제 ID 감사의 누락·중복·추가 **0**이다. 신규 node와의 차이 170개는 직접 store·독립 녹음·실제 위젯·구조·경합·장애·자식 import 등의 보강이며 중복 합산하지 않는다. `final-v2-case-audit.json`이 근거다.
- 계획 mutation **25/25 검출**(M11 두 경계로 실행 26개), 보강 mutation **2/2 검출**. 전체 실제 변형 28개이며 import/syntax/수집 실패는 검출이 아니다. source/mutant hash·명령·patch·assertion 실패를 `mutation-final-v2-results.json`과 `final-v2-M*`, `final-v2-AUX*`에 남겼다.
- ruff check .·ruff format --check . 모두 PASS(177 Python 파일), `mypy src/recoryn scripts packaging` PASS(88 source files).
- UI 전체·기존 보안/gateway/privacy/provider 계약·G-P02/G-P02b/G-P03·G05 PERF/G15 구조/경합 시험을 위 전체 묶음에 포함했다. 별도 선택 결과와 전체 결과를 더해 시험 수를 부풀리지 않는다.
- API의 root mutex/Job transaction/Job 잠금 아래 journal 전체 열거 0을 구조 감시로 고정했다. 대규모 실제 장치 실측이나 원본 무손실의 일반 보장으로 확대하지 않는다. 저장·전송·모델 검증은 기존 fake/임시 DB/합성 PCM 범위이며 실제 장치·모델 weights·네트워크·유료 호출은 사용하지 않았다.

### 최종 사본·쓰기 범위 감사

Python source/시험의 작업 트리 바이트가 실행 사본과 같음을 확인했다. archive 기준의 **22파일 밖 추적 파일 변경 0**, src/tests/scripts/packaging 아래 **예상 밖 Python 파일 0**이다. 자식 Python의 jobs/storage.library/app.status 실제 __file__이 모두 사본 src 아래임을 `final-v2-child-imports.json`으로 확인했다. .venv editable 설치로 작업 트리를 대신 읽은 결과를 인정하지 않았다. 종합 감사는 `final-v2-audit.json`이다.

publication fixture는 승인된 296행의 RETRYABLE→TEMPORARY 한 문자열만 바뀌었다. G-P03 diarize 본문의 AST와 원본 게시 CAS를 보존했다. G-P15b의 chunks/recording/seal 시험·문서 및 공용 설정은 수정하지 않았다. Git 쓰기·하위 에이전트/pane·계정/vault 쓰기·패키지 설치도 수행하지 않았다.

L 8건·M24 및 세 범위 요청은 모두 닫혔다. 기존 화자 Job의 표시·탐색만 제공하는 C00 확인, 실행 정책 탐색 식별자와 기존 control 연결, SUMMARY_PARTIAL 미등록을 반영했다. **이 단위의 미해결 구현/시험 실패는 없다. 독립 검토·최종 통합 승인은 C00이 지정한 별도 검토자의 몫이다.**

### 변경 파일과 LF SHA-256

CR을 제거한 LF 기준이다. 문서는 결과·아래 표를 쓴 뒤 계산하므로 자기 hash를 표 안에 순환 기입하지 않고 이 창의 완료 보고와 `g07-implementation-ready-manifest.json`으로 제공한다. 아래 21개 Python 파일과 문서 1개로 총 22개다.

| 변경 파일 | SHA-256(LF) |
| --- | --- |
| `src/recoryn/jobs/failures.py` | `9b39060f46eff9ec866684ed0a55f3e48a3a13a855564284f5e4683e60f63313` |
| `src/recoryn/app/status.py` | `eb0006d21258a5e4e13afc3e9c1d1e8fbd1056025fc64d2fcf03dadcd26cb3a1` |
| `src/recoryn/jobs/__init__.py` | `aa0e5dfd4ba846035618c52c08ed281adfd62e760889e7b89ab93a762ba13b3c` |
| `src/recoryn/jobs/runner.py` | `477e92ec3625981e9241986e5a222ae1aeaa8f928c17e3671884d6a20e262ace` |
| `src/recoryn/providers/_common.py` | `686e659ecd2a2202a5686f016f25d015657e811d2c9cf4ab89e6d7853a846647` |
| `src/recoryn/app/ai.py` | `4442a3f6e79689bbd47c3589b58eadb9348c24dd8048ca2a6cc14c945edef554` |
| `src/recoryn/app/desktop.py` | `7f49902d425f645757639f0465ffae2666a6af152326f677c46afd541192d021` |
| `src/recoryn/ui/main.py` | `e26f08bd42a3efd4077cbfc2feef996c3c3b69d034679b53880c6c8bd9618883` |
| `src/recoryn/ui/ai_bridge.py` | `6c4927bc128fb8f48bc69aa28fba532f45070f1770e706fee950ef3883e578c2` |
| `src/recoryn/ui/content.py` | `a9bd22ff7fdcb8d51509c5b90730d627d1d6c9a9ad82813b78adbbb59bcdef2b` |
| `src/recoryn/ui/privacy.py` | `b90b3dcaa2c010c3f69218be3d8672b937739e79489386fb732161522d217e29` |
| `tests/unit/test_blocked_reasons.py` | `b4ab7f763d5ea05619ab4af7b977dc959b2cd1556dd173a3182cb5229206f80b` |
| `tests/property/test_blocked_reason_case_space.py` | `b61eb2b3edee4847bfa0f874f5a42c0e5ccde78064518cba34b94a459c2d201c` |
| `tests/integration/test_blocked_reason_flow.py` | `9d7822c7803c9e28def95a79aec8c9840e58c39030514f31ab5fd48a4bec2ed2` |
| `tests/ui/test_blocked_reason_ui.py` | `9fae8201fa6509a65f35f556688ab050cdda39ac3a4cb23b434463bc1ad86318` |
| `tests/ui/test_capture_start_ui.py` | `83bac3f5451753c075219df4a3a4602a7bd4a94001ddc1865a6b0abf2a0aaca4` |
| `tests/unit/test_jobs.py` | `fe14505de7f9d9039205fb0ab5014d61a0ebee73ff55f0aa3096205ac1caa78a` |
| `tests/integration/test_app_service.py` | `77d0a9d39e84829bed903d7cadc87dcda8eb01b4fc8d4f543e0eb8c538500007` |
| `tests/ui/test_gpu_runtime_ui.py` | `3ad13518e4b67b50fc599229ec0820d6590ff78e077764695600321d679116b6` |
| `tests/integration/test_publication_independent.py` | `73093dd97214923c72c4f0313454482e106f71de64264d9120f8bb90a23fde7d` |
| `src/recoryn/storage/library.py` | `39e63c8e04f93165d08283d463dc36e6fb5350b4debab5836afa2fdfb2959537` |


## G-P07 FIX1 — 독립 검토 수정 계획(2026-11-24)

C00가 G07R-01을 S1로 상향하고 G07R-01~09의 수정을 배정했다. 검토 문서 LF SHA-256은 `9448f0fb231d6b52ebeab78aee5923cdfa81364584e750e2a75cc10e3507f3b3`다. 위 IMPLEMENTATION_READY는 수정 전 이력이다. 기준 HEAD 90c6123 + 승인 22파일만 TEMP에 복사하여 판단하며 G-P15b 변경은 포함하지 않는다.

입력 분할/독립 oracle: STOPPING/PAUSING의 현재 epoch PCM은 저장 서비스가 epoch를 닫기 전 수락하고 실제 보존 bytes/frame·건강 누계와 대조한다(G07-FIX1-PCM-01~04: stop/pause×1/2트랙). 늦은 run/session/epoch는 계속 거부한다. epoch 조회는 DesktopRecorder lock 밖임을 감시한다. gateway outcome은 속성 없음/비bool/getter실패/로컬 인자/명시False/명시True 6행(G07-FIX1-WIRE-01~06)으로 분할하고 명시True 외에는 실제 Job/Attempt UNKNOWN을 검증한다. 기존 O의 start-failure는 pause 대체를 제거하고 실제 재개 start 실패로 수정한다. 부분 시작 실패+source ACK 실패·pause/stop ACK 실패는 별도 G07-FIX1-ACK- 접두사로 실제 분기를 실행한다.

계속·UI 보강은 기존 실제 PrivacyPanel/ConsentStore/CostLedger/Gateway에 fake transport/vault만 주입하여 새 binding·예약·철회 경합을 관찰한다. 화자 제외는 시험 내 override 없이 실제 tick/continue 분기로 관찰하고, 미확정/미완성 안내의 초점·탐색 부수효과0, 재시작 실패·절전·재생 Job 뒤 BLOCKED 유지도 고정한다. 상세 ID/분모와 결과는 수정 완료 후 아래에 추가하며 지금 PASS로 집계하지 않는다. 기존 4,947 계획 ID와 보강 ID를 분리한다. DELETION_HISTORY_UNAVAILABLE의 명시 코드 추가·전용 입장 거부 기록은 C00 결정 요청 중이며 다른 수정부터 진행한다.

### FIX1 확정 입력 분할·구현 범위

공유 오류 catalog는 **110개를 유지**한다. 중간에 요청한 111코드/전용 BLOCKED 기록 API는 필요 없어 철회한다. 삭제 이력 거부는 Job 오류 범주와 구별한 runner의 bounded 읽기 모델이며, claim 전 거부는 AIService 중복 접수 캐시를 해제한다. Job/Attempt를 새로 만들거나 권한을 승인하지 않고, 이력 회복 후 사용자의 같은 요청이 실제 입장 guard를 다시 통과한다. reader 입장 거부는 기존 실패 ACK 규칙으로 안전 종료한 뒤 명시 새 요청 경로를 쓴다. post-task 오류를 입장 전/무전송 사실로 오인하지 않는다. 메타데이터 조회는 GUI에서 journal/authority를 열거하지 않으며 observer 호출은 root/runner condition 잠금 밖이다. G-P11의 110→112→122 인계 수에는 변화가 없다.

| 수정 분할 | 계획 의미/실행 node | 독립 관측 |
| --- | ---: | --- |
| PCM / G07-FIX1-PCM-01~04 | 4 | stop/pause×1/2트랙, payload 연결·frame 합·수락 누계·drop0 |
| gateway / G07-FIX1-WIRE-01~06 | 6 | outcome 속성 없음/비bool/getter실패/로컬인자/False/True, 실제 Job UNKNOWN 우선 |
| history / G07-FIX1-HISTORY-01~04 | 4 | claim/reader×한번/지속 거부, native0·원본 bytes·캐시 해제·재입장 |
| ACK / G07-FIX1-ACK-01~03 | 3 | 실제 부분 시작/일시정지/정지 ACK 실패, 정확한 종료 대기 text/상태 |
| 실제 Window / G07-FIX1-WINDOW-01~04 | 4 | 시작/pause/stop 제어 실패 뒤 request 해제·tick, 절전 표시 보존 |
| 새 실행 준비 / G07-FIX1-CONTINUE-01~10 | 10 | STT/요약×유효/준비전철회/준비후철회/의미변경/이력미확인, 실제 Privacy·Ledger·Gateway·adapter. 전송은 fake transport |
| 입력 안내 / G07-FIX1-NAV-01~03 | 3 | 확정 활성/비활성·미완성 전사, 실제 초점·탭, 실행0 |
| UNKNOWN 준비 / G07-FIX1-UNKNOWN-01~03 | 3 | 실제 worker의 consent/history typed 미확인·모순 UNKNOWN DTO, 기존 BLOCKED 계속 활성화0 |
| 명명 singleton 6개 | 6 | epoch lock/중간 generation 변경, 재시작 실패, 화자 직접 계속 거부, 재생 Job 필터·안전 코드, 실제 Window 이력 표시, task 오류의 입장 전 사실 위조 금지 |
| 기존 integration F30의 CAS 보강 / G07-FIX1-CAS-01~30 | 30 | 동일/오래된 Job version/변경 의미와 reader ACK. 아래 canonical F30과 구별 |
| **FIX1 보강 합계** | **73** | 기존 계획 외 추가 지원 행이며 전체 시스템 전수라는 뜻이 아님 |

**F 가족 정정:** 앞 제출의 integration F30에서 stale은 실제로 Job version stale이었다. 이 사실을 숨기지 않고 그 30행을 G07-FIX1-CAS로 다시 명명했다. canonical **G07-F-01~30**은 실제 UI에서 사유5×준비{유효한 같은 계획,철회된 권한,변경 의미}3×reader active2로 새로 수행한다. 최초 QUEUED fixture를 만들 때만 dispatch를 보류하고 실제 public claim/fail/block_pending으로 상태를 구성한다. 관측하는 계속 동작 전에 원래 runner.submit을 복원하며 Privacy/ConsentStore/CostLedger/Gateway/adapter는 제품 경로다. 철회된 동의의 실제 prepare 실패·reader 보호·새 의미 키 거부·USER_CAP 예약/전송을 독립 oracle로 관찰한다. source/code를 복제한 화자 override는 U에서 제거하고 실제 tick·직접 continue guard를 거친다.

원래 계획은 **4,947행 그대로**, 기존 지원170 + FIX1 지원73 = 지원243, 신규5파일 수집 예상은 **5,190 node**다. canonical F의 이동을 추가 계획 행으로 중복 계산하지 않는다. O의 start-failure 종료는 실제 pause 후 resume의 start 실패이며 partial-start ACK 실패는 별도 ACK/Window 행이다. D 2,640행은 순수 함수만 보던 기존 한계를 보강해 모든 tuple에서 실제 SQLite Job/Attempt/reader/checkpoint까지 대조한다. 행 수를 늘린 것으로 집계하지 않는다.

mutation은 기존 논리25(실제26변형), 기존 AUX2, 검토자의 M23/M24/M25·X1/X2/X5/X6a/X6b를 재적용하고 X3/X4는 수정의 반대 변이(STOPPING 거부/default known)로 검증한다. R-X9는 epoch 조회를 DesktopRecorder lock 아래로 되돌린다. FIX 추가 논리11은 cache 해제 제거/입장 거부 metadata 제거/GUI snapshot의 metadata 누락/이력 준비 표시 제거/post-task를 무전송 입장거부로 오인/잘못된 입력 안내/재생 Job 필터 제거/절전 표시 제거/시작 실패 표시 퇴행/옛 실행 snapshot 재사용/미확인 준비 뒤 계속 활성화다. snapshot 재사용은 STT·요약 두 변형이라 추가11논리=12실행이다. 정상본 PASS 뒤 최종 사본에서 총51변형(기존26+AUX2+검토11+FIX12)을 실행하고 논리 결함·중복 의도·invalid를 구별한다. 추가를 원 계획25개 검출처럼 부풀리지 않는다.

### FIX1 작성자 재현 결과(전체 CI 동등 회귀 실행 중)

다음은 작성자의 수정·재현 결과다. G07R-01~09의 독립 RECHECKED/CLOSED 판정은 C00 지정 검토자의 몫이다. 1차 검토의 등급과 C00 최종 결정은 구분하며 G07R-01은 C00 결정 S1로 기록한다.

| 지적 | 등급 | 최종 구현 근거 | 실제 재현·시험 근거 |
| --- | --- | --- | --- |
| G07R-01 | S1(C00 상향) | `app/desktop.py:140` — control mode는 PCM 수락 거부 조건에서 제거. 현재 generation/session/epoch와 재확인만 유지 | 원 `probe_stop_inflight.py`: stop/pause 모두 1,440 frame. `probe_two_track_stop.py`: system 2,880 frame, 모두 True. 새 PCM4는 track별 실제 audio.pcm 연결 bytes/frame·수락/유실 누계까지 확인 |
| G07R-02 | S2 | `jobs/failures.py:85`, `providers/_common.py:278` — gateway 전용 기본 미상, 로컬 문자열 인자 추출 금지 | 원 boundary probe의 속성 부재·StateConflict는 REMOTE_UNKNOWN. WIRE6은 실제 JobStore 분류도 확인. factory False 보존은 기존 W/M23 유지 |
| G07R-03 | S3 | `app/desktop.py:212`, `ui/main.py`의 제어 실패 callback — 기존 ACK 보존 분기를 실제 실행 | O의 start 실패 대체 제거, ACK3·실제 Window3·X1/X2 검출. 부분 시작 실패의 RECORDING·ack_pending과 정확한 “종료 확인 대기 · 일부 원본 보존”을 확인 |
| G07R-04 | S3 | `jobs/runner.py:71`, `:76`, `:204`, `app/ai.py:96`, `ui/ai_bridge.py:178`, `:874`, `app/status.py:183` | 원 history probe: 첫 거부 QUEUED/attempt0 → 같은 Job 재요청 SUCCEEDED/attempt1/provider1. HISTORY4·실제 Window 이력 표시·계속 중 이력 거부2행. task 실행 뒤 오류에는 입장 전/무전송 사실을 붙이지 않음 |
| G07R-05 | S3 | `ui/ai_bridge.py:292`, `:874` — 실제 kind guard와 tick 표시 | U의 시험 내 화자 override 제거. 실제 tick의 버튼 비활성과 직접 continue의 호출0/Job 불변. 검토 X6a/X6b 모두 검출 |
| G07R-06 | S3(S0 민감 경로 시험) | 기존 UI→새 privacy 준비→명시 expected Job/version→실제 service/runner/adapter/Gateway 연결 보존 | canonical F30·CONTINUE10에서 실제 ConsentStore/CostLedger/Gateway 사용, OS vault/transport만 fake. 철회 전후·새 예약 ID·옛 binding 거부·의미 변경·원본/기존 Job 보존 확인. D 전수의 실제 Attempt/reader/checkpoint SQL 확인. 옛 snapshot 재사용 STT/요약 변이와 미확인 준비 계속 변이 검출 |
| G07R-07 | S3 | `app/status.py:78`, `ui/ai_bridge.py:236`, `ui/content.py:66` | NAV3: 확정 가능하면 확정 버튼, 녹음 중 등 확정 불가이면 녹음 정보, 미완성 전사는 전사 실행 control로 초점 이동. 모델 설정으로 보내지 않고 실행0 |
| G07R-08 | S3 | `app/desktop.py:108`, `ui/main.py:1085`, `ui/ai_bridge.py:874`, `app/status.py:113` | 재시작 실패 원 probe는 START_FAILED/“시작 실패”. 실제 Window의 절전 표시가 다음 tick에도 유지. playback_verification은 AI 상태에서 제외해 BLOCKED 안내/계속이 유지됨. 미등록 코드는 빈 칸 대신 TASK_FAILED, 원문 유출0 |
| G07R-09 | S3 | `app/desktop.py:140` — 참조/token 복사→잠금 밖 epoch 조회→token 재확인→submit | epoch getter가 DesktopRecorder lock 보유를 직접 거부하는 시험과 조회 중 generation 변화 거부. R-X9 잠금 중첩 변이 검출. 실제 deadlock을 재현했다는 주장은 아님 |

최종 사본은 OS TEMP `recoryn-g07-fix1-zb_6bliv/final1`이다. `git archive 90c6123` 위에 승인22파일만 복사했다. 범위 대조22/22·범위 밖 source 변경0, G-P15b 금지 영역과 coordination 등 6파일은 90c6123 bytes와 일치한다. Python spawn 자식에서 recoryn/jobs/app.status/storage.library 네 모듈의 실제 __file__이 사본 src임을 확인했다. 검토 probe의 -I가 환경 bytecode 설정을 무시해 만든 TEMP __pycache__41개는 생성 artifact로 별도 계수했고 versioned source 변경으로 세지 않았다. 이후 격리 probe에도 -B를 명시했다.

- 최종 신규5: **5,190 PASS / 25.96초**, skip0, 단독 실행60초 게이트 충족. pytest testcase 합계는 별도 XML에 있으며 wall/time을 서로 바꾸지 않는다. 앞의 26.94초 실행 뒤 unused import1개만 제거하고 다시 측정한 값이다.
- tests/ui 전체와 jobs/app_service/publication/desktop 관련 회귀: **1,368 PASS / 83.08초**, ResourceWarning 오류 처리. 이 전체 회귀 시간을 새5파일60초 게이트와 혼동하지 않는다.
- 검토자 독립 case audit: 14가족 **4,947 ID 누락/중복/추가0**, 수집5,190. 추가 감사는 FIX1 ordinal67+명명 singleton6=73, canonical F30이 실제 UI 파일에 있는지도 확인했다. 기존 지원170+새지원73=243으로 총수를 대조했다.
- 최종 사본 mutation: **51/51 assertion 검출**, survived/invalid0. 원 계획 논리25=26실행(M11 두 경계), 기존 AUX2, 검토 재적용11, 새 FIX 논리11=12실행(STT·요약 snapshot 두 변형)이다. 검토 X3/X4는 원 수정 patch를 다시 적용한 것으로 세지 않고 회귀를 되살리는 반대 변이로 실행했다. 수집/import/권한/timeout 검출은0이다.
- 정적 검사: ruff check PASS, format check **177파일** PASS, mypy `src/recoryn scripts packaging` **88 source files** PASS.
- 검토자 원 root 보유 probe(삭제 이력300·40 cycle): claim **2.477ms**, reader_started **3.064ms**, fail **2.429ms**, resume **4.682ms** 최장 관측. 구조 시험의 대체나 실시간 보증이 아닌 이 PC 표본이다.

CI 동등 전체 회귀·7묶음 coverage는 아직 실행 중이며 아래 최종 절에서 확정한다. 실제 장치·모델 weights·네트워크·유료 호출·OS vault 쓰기·원격 CI는 수행하지 않았다. G-P07b로 미룬 검토 항목은 현재 없으며, 구현 승인/독립 재확인을 대신하는 자체 최종 승인은 하지 않는다.

### FIX1 최종 CI 동등 회귀·제출

앞 절의 “전체 회귀 실행 중”은 중간 이력이며 다음 결과로 확정한다. **HEAD 90c6123 + G-P07 22파일** 사본에서 전체 오프라인 **20,368 PASS / 1,176.31초(19분36초)**, fail/error/skip0, pytest warnings summary 없음. 실행은 Python3.13.1·offscreen·-p no:cacheprovider·-W error::ResourceWarning·고유 OS TEMP basetemp·-B이며 PYTHONPATH는 사본 src다. 작업 트리 G-P15b는 포함하지 않았다.

```text
python -B -m pytest -q -p no:cacheprovider -W error::ResourceWarning --cov=recoryn --cov-branch --cov-report=json:coverage.json --cov-fail-under=85 --basetemp=<고유 OS TEMP>
python -B scripts/check_coverage.py coverage.json
domain: line=100.00%/95% branch=100.00%/90% PASS
capture: line=99.85%/95% branch=98.57%/90% PASS
jobs: line=99.10%/95% branch=96.04%/90% PASS
storage: line=96.51%/95% branch=92.43%/90% PASS
security: line=98.11%/95% branch=94.43%/90% PASS
content: line=99.59%/95% branch=98.75%/90% PASS
all: line=94.13%/85% branch=88.28%/80% PASS
```

pytest 결합 coverage는 **92.68%**다. check_coverage의 line/branch 비율과 다른 집계이므로 섞지 않는다. coverage.json의 측정 파일은 **src/recoryn 아래75개**, TEMP/legacy fixture/범위 밖 파일0이다. 결과를 맞추기 위해 pyproject·check_coverage·pragma를 바꾸지 않았다. source21파일이 검증 사본과 같은 LF hash임을 재확인했으며 publication fixture는 90c6123 원문 대비 RETRYABLE→TEMPORARY 한 문자열뿐이다.

증거 정본은 `C:/Users/gangd/AppData/Local/Temp/recoryn-g07-fix1-zb_6bliv/` 아래다.

- `final-full-command.json`·`final-full-result.json`·`final-full.log`·`final-full.xml`, `final1/coverage.json`·`final-coverage-check.log`
- `final-new5b-command.json`·`final-new5b.log/xml`, `final-ui-related-command.json`·`final-ui-related.log/xml`
- `final-collection.log`·`final-case-audit.log`·`final-support-audit.json`, `final-scope-audit.json`·`final-child-import.log`
- `mutate-fix1-final.py`·`mutation-fix1final-results.json`, `fix1final-*.patch/.log` — 51변형 전부 assertion 검출
- `final-reviewer-probes.json`·`final-probe_*.py.log`·`final-root-hold.log`, `final-ruff.log`·`final-format.log`·`final-mypy.log`

G07R-01~09는 이 22파일 안에서 작성자 수정/검증을 마쳤다. **G-P07b로 미룬 지적 없음**, 새로운 111코드나 JobStore 쓰기 API 없음. 동의·비용·UNKNOWN을 UI에서 완화하지 않으며 이력 미확인을 유효 권한으로 해석하지 않는다. 독립 재확인은 C00 지정 검토자에게 인계한다. G16·G13은 기존 CONTRACT_READY/RECONCILED 문서 해시 그대로이며 제품 구현에 착수하지 않았다.

### FIX1 변경 파일과 SHA-256(LF)

다음21 Python 파일의 hash는 실제 검증한 source와 같다. 22번째 파일인 이 문서의 최종 hash는 자기참조 없이 창의 FIX1_READY와 외부 `g07-fix1-ready-manifest.json`에 기록한다.

| 파일 | SHA-256(LF) |
| --- | --- |
| `src/recoryn/jobs/failures.py` | `36fea38413511c0a1f862aa485d09fbf5d62fa724ca851d8e9e6d61ff4d2c994` |
| `src/recoryn/app/status.py` | `27e25a49d2cc5e89792f7ba25ab5db1a69738eabb30522494ec10b3725f49e57` |
| `src/recoryn/jobs/__init__.py` | `aa0e5dfd4ba846035618c52c08ed281adfd62e760889e7b89ab93a762ba13b3c` |
| `src/recoryn/jobs/runner.py` | `819c399b89f46d61294e02d5f5aa1cdd48b021a04e1b5271795748e8858de54c` |
| `src/recoryn/providers/_common.py` | `2d6df75ed4f6a2ab9fff9ae1bb0db98ecc838b204f91511e49281162afea50f3` |
| `src/recoryn/app/ai.py` | `19707dc3b71a385d182f4a610b048df8004559b239bd6cdad640551c827374d7` |
| `src/recoryn/app/desktop.py` | `5183ce23cf3a2a51cad5dc8f38fda483a58a503115142ebb5b0a5e389dc39bba` |
| `src/recoryn/ui/main.py` | `e63f7ed39c0ffbcc4bb4a8afda1f3087933a12e8ec1950460352b5120e5e5cb6` |
| `src/recoryn/ui/ai_bridge.py` | `163affb7a3cc20a9a3c3cefd010f4f54e0d5b09b937823ced747de26bd4f2f64` |
| `src/recoryn/ui/content.py` | `c857766b33c5281c099e1a14f18e3eea9f7fb8705bbd63912585c278c15dc989` |
| `src/recoryn/ui/privacy.py` | `b90b3dcaa2c010c3f69218be3d8672b937739e79489386fb732161522d217e29` |
| `tests/unit/test_blocked_reasons.py` | `b4ab7f763d5ea05619ab4af7b977dc959b2cd1556dd173a3182cb5229206f80b` |
| `tests/property/test_blocked_reason_case_space.py` | `1c0e52879db3f8b6e879f5ec34a8ffda14c4aff93b666dcf82a1921717be2bce` |
| `tests/integration/test_blocked_reason_flow.py` | `295ec03565eae7c98f0624cb7d5e1a1e3b90fe9d56680240b69ad479d05f3697` |
| `tests/ui/test_blocked_reason_ui.py` | `c3864313e7d8309baf64d7a39ae0a3e5882af55f559f86276859b2c8ad90a52a` |
| `tests/ui/test_capture_start_ui.py` | `d24e65ce1fe3c277b6323a7486516f3ef79bd10948ad8796f1881f0551b723e6` |
| `tests/unit/test_jobs.py` | `fe14505de7f9d9039205fb0ab5014d61a0ebee73ff55f0aa3096205ac1caa78a` |
| `tests/integration/test_app_service.py` | `77d0a9d39e84829bed903d7cadc87dcda8eb01b4fc8d4f543e0eb8c538500007` |
| `tests/ui/test_gpu_runtime_ui.py` | `3ad13518e4b67b50fc599229ec0820d6590ff78e077764695600321d679116b6` |
| `tests/integration/test_publication_independent.py` | `73093dd97214923c72c4f0313454482e106f71de64264d9120f8bb90a23fde7d` |
| `src/recoryn/storage/library.py` | `39e63c8e04f93165d08283d463dc36e6fb5350b4debab5836afa2fdfb2959537` |
