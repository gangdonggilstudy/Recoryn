# G06 / G-P06 비용 상한 계약안과 경우의 수

상태: **8e09b62 기준 작성자 검증 완료 — 독립 검토 대기**. 작성자는 w5:p8 Codex, 독립 검토자는 C00이 지정한다. C00이 (a)~(f), 아래29파일과 기본 catalog 비어 있음을 승인했고 G-P03·G-P02·G-P02b push 뒤 구현을 지시했다. 신규4파일 시간 게이트는 분모 유지·최적화 실측을 보고 **이 PC 120초로 재승인**됐다. 구현 시작 기준은 **234dd31a32426367268b3c8710a11ca82a010e6f**, C00의 G-P04 push 뒤 최종 검증 기준은 **8e09b62ad1bb94475b5895e53438dbbe45a8b18d**다. 실제 변경26파일, 호환 확인만 한 동일3파일을 구별한다. 작업 트리의 G-P05 변경은 복사하지 않았다. §12는 이전 기준의 직접 검증 이력이며 새 기준 결과는 §13에 별도로 기록한다.

## 1. 요구와 직접 확인한 현 상태

정본은 [통합안 G-P06](../implementation/v1-gap-plan.md), [설계의 전송 동의와 비용](../architecture-v1.md#전송-동의와-비용), [경우의 수 규칙](case-space.md)이다. G01B-046/F-COST01의 검증되지 않은 사용자 cap 예약은 S1이다. G01B-047/F-COST02의 자동 usage 정산 누락은 G01BR-07의 **S2 조정에 동의**한다. RESERVED/UNKNOWN이 남는 현재의 보수적 동작과 검증되지 않은 요청 상한의 문제를 구별한다.

2026-11-23 작업 트리에서 직접 읽은 근거다. 이 트리에는 미커밋 G-P02/G-P03 변경이 있으므로 향후 구현 결과의 기준 commit으로 사용하지 않는다.

| 근거 | 직접 확인한 사실 | 계약에 반영할 내용 |
| --- | --- | --- |
| `src/recoryn/ui/privacy.py:494`의 `reserve` 클로저 | `body_size`는 음이 아닌 정수인지 확인하지만 모델·본문·출력량과 무관하게 `cap`을 `ledger.reserve`에 넘긴다 | 요청별 검증 상한 U와 사용자 수락 cap C를 구별한다 |
| `src/recoryn/providers/_common.py:179`의 `Run.request` | 기존 factory에 provider/endpoint/data_type/본문 길이 네 값만 전달한다. factory 예외는 `BUDGET_BLOCKED`로 뭉친다 | 불변 요청 명세와 구체적인 안전 오류 코드를 전달한다 |
| `src/recoryn/security/ledger.py:40`의 테이블, `:148`의 `_snapshot` | provider별 정수 금액·상태만 있고 통화·기간·가격 기준시각 열은 없다 | additive v2 계정·요청 메타데이터, 기존 노출액 보존 |
| `src/recoryn/security/ledger.py:73`의 `_state`, `:125`의 `_change` | 기존 witness는 v1 상태만 해시하며 witness 게시가 DB commit보다 먼저다 | v2 정보를 해시에 넣고 전환 중 실패도 차단한다 |
| `src/recoryn/security/gateway.py:273`의 `_write` | 첫 transport write 전에 UNKNOWN으로 전환한다. write가 부분 성공 뒤 예외를 내도 불명 노출을 남긴다 | 이 경계를 보존하고, 비용 검증도 open/각 write 직전에 추가한다 |
| `src/recoryn/summarization/adapters.py:130`·`:141`·`:150` | 공급자별 출력 제한 필드가 다르다 | 실제 직렬화된 필드와 검증한 과금 출력 상한의 일치가 필요하다 |
| `src/recoryn/transcription/adapters.py:232`·`:352`, `src/recoryn/providers/_common.py:77` | STT는 PCM 길이 확인을 거친 WAV를 사용하며 Gemini에는 별도 출력 토큰 필드가 있다 | 음성 byte 수를 텍스트 토큰으로 취급하지 않는다 |
| `src/recoryn/app/ai.py:155`, `src/recoryn/ui/ai_bridge.py:116` | 예약 factory를 감싸거나 ExecutionContext를 다시 만든다 | 새 문맥 전달과 `mark_remote_intent` 선행 기록을 함께 보존한다 |

위 행은 코드 읽기 결과이며 새 실행 증거가 아니다. Q24 문서에 적힌 198행/200개 시험·mutation 2개 등의 숫자는 **기존 작성자가 기록한 과거 결과**다. 이번에 재실행한 결과처럼 인용하지 않는다. 실제 가격·모델별 토크나이저·최종 청구와의 일치는 이번에 확인하지 않았다.

## 2. 제안 결정과 범위

1. 유료 원격 요청의 기본은 **strict**다. 일반 모드는 사용자가 불확실성을 표시한 확인 창에서 명시적으로 선택한 경우만 허용한다. 가격 만료나 검증 실패로 strict가 일반 모드로 바뀌는 fallback은 없다. 로컬 실행은 기존 실행 위치 검증을 통과해야 하며 비용 0이라는 이유로 원격 경로를 로컬로 간주하지 않는다.
2. strict에서는 유효한 가격표와 모델·API·과금 규칙에 대한 요청 상한 근거가 모두 있어야 한다. UI에 큰 cap을 넣거나 컨텍스트 크기를 직접 입력한 사실만으로 검증된 근거가 되지 않는다. 가격·요청 상한이 없으면 연결 전에 차단한다.
3. 검증 가능한 요청은 strict/일반 모두 계산한 **U를 예약**한다. 사용자 cap C는 `U <= C`를 만족해야 하는 수락 한계다. C를 가격 추정치로 쓰지 않는다. 일반 모드에서만 검증 불가 요청을 명시적으로 `UNVERIFIED_USER_CAP`으로 표시하고 C를 노출액으로 예약한다. 이는 공급자 청구 상한 보장이 아니며 strict의 합격 근거로 사용할 수 없다.
4. cap과 예산 한도가 없거나 0이면 유료 원격 요청은 두 모드 모두 차단한다. 한도 증가는 사용자의 명시적 적용과 새 실행 계획을 요구한다. 기존 계획이 변경된 위젯 값을 읽지 않는다.
5. G-P06은 F-COST01, 통화·기간·가격 근거 영속화와 정산 이벤트의 최소 기반을 닫는다. **모든 공급자의 usage 응답 해석·청구 API 연동은 포함하지 않는다.** F-COST02의 자동 usage 연결은 S2 후속으로 남긴다. 새 기반에서도 usage를 확인할 수 없는 요청은 UNKNOWN으로 유지한다. 수동 정산은 확인된 금액이라는 기존 명시 확인을 요구하고 이벤트로 기록한다.
6. 실제 유료 가격표를 검증하지 못하면 본 계약 구현이 통과해도 그 공급자/모델의 strict 실행은 차단 상태다. 합성 fixture 성공을 실제 모델·가격 호환성이나 공급자 청구 상한 검증으로 표시하지 않는다.

## 3. 가격표와 요청별 상한

### 3.1 오프라인 가격 근거

제안 `security/cost_catalog.py`는 네트워크 조회·다운로드·임의 경로 파일 로드를 하지 않는 고정 catalog다. entry의 키는 `(provider_id, 정규화한 정확한 endpoint, model_revision, api_version, operation, billing_profile_version)`이다. 모델 alias, 유사한 endpoint, 다른 API operation으로 대체하지 않는다. provider 이름만 같다고 가격을 공유하지 않는다. 조직별 요금이 다른 경우 검증한 billing profile을 명시적으로 분리한다. 검증되지 않은 사용자 서버·프록시는 strict에서 차단한다.

entry는 `currency`, `price_as_of_utc`, `valid_from_utc`, `valid_until_utc`, 단가의 정수 분자·분모, 최소 청구량·청구 증분·고정 수수료, 적용 tier의 보수적 최대 단가, 과금 입력/출력 종류, 상한 계산 profile ID와 version을 포함한다. provenance는 공식 원문 URL, 보관한 원문/발췌의 SHA-256, 취득일, 검토 ID다. **URL을 실행 중 열지 않는다.** source 날짜와 가격 적용 시각을 혼동하지 않는다.

catalog의 canonical bytes digest를 애플리케이션이 신뢰하는 digest와 대조한다. digest는 내용 결합을 확인할 뿐 가격의 진실성을 증명하지 않는다. 최초 실제 entry 추가와 갱신은 C00/독립 검토를 거쳐 코드·근거를 고정한다. 사용자가 임의 단가나 `verified=True`를 넣는 방법으로 신뢰 catalog에 진입하지 못한다. **본 단계에는 실제 가격 원문이 주어지지 않았으므로 실제 유료 entry는 미승인·미검증이다.** 후속 구현의 기본 catalog가 비어 있어도 strict 거부는 정상이다. 승인된 로컬 fixture 주입은 시험에서만 사용한다.

### 3.2 계산 규칙과 한계

모든 돈은 통화별 **백만분의 1 단위 정수**다. USD와 EUR 등의 값은 서로 더하거나 환전하지 않는다. Decimal 문자열은 UI 경계에서 한 번 변환하며 float로 계산하지 않는다. 개별 과금 항목 j의 단가를 `n_j/d_j`, 검증된 청구 단위 상한을 `q_j`라 할 때:

`U = 고정 수수료 + Σ ceil(q_j × n_j / d_j)`

최소 청구량·증분 반올림은 해당 profile에 따라 q를 구할 때 먼저 적용한다. 항목별 반올림이 공급자의 과금 규칙을 안전하게 덮는다는 근거가 있어야 한다. 알려진 tier·reasoning·추가 요청·캐시 미적중·도구 비용도 상한에 포함한다. 불명인 항목을 0으로 놓지 않는다. 모든 중간 곱은 충분한 정밀도의 정수로 계산하고 최종 금액과 영속 정수는 `0..2^63-1`을 검사한다. overflow를 포화·절삭하거나 bool을 int로 받지 않는다.

- 텍스트: 입력 UTF-8 byte 수 B와 정확한 wire body를 고정한다. profile의 검증된 `input_token_upper_bound(B, 구조·메시지·추가 토큰)`을 적용한다. `토큰 <= bytes`, `len(JSON)` 또는 문맥 창 자체를 일반적인 과금 상한이라고 가정하지 않는다. 입력 프로토콜·토크나이저/프레이밍의 근거가 없는 모델은 strict에서 `COST_BOUND_UNVERIFIED`다. 검증된 컨텍스트 제한도 넘으면 차단한다.
- 출력: 요청에 실제 적용한 출력 제한을 읽고, 그것이 공급자의 **전체 과금 출력**을 제한한다는 profile 근거가 있어야 한다. 별도 reasoning·숨은 출력이 있으면 그것까지 유한하게 덮는다. 설정상의 `max_output_tokens`만 복사하고 실제 body의 필드가 없거나 더 크면 차단한다.
- 음성: 검증된 WAV payload의 frame 수·sample rate에서 지속시간 상한을 정수로 구한다. 과금 단위가 분/초이면 공급자의 최소량·올림 규칙을 적용한다. audio-token 과금이면 별도 검증된 상한이 필요하다. PCM 길이와 헤더 불일치는 일반 모드에서도 잘못된 입력으로 거부한다. 지속시간만으로 비용이 고정되는 profile은 별도 출력 과금이 없다는 근거가 있어야 한다.
- 중간 요약·최종 통합·각 STT 청크는 각각의 실제 HTTP 요청마다 계산·예약한다. 첫 요청의 예약을 재사용하지 않는다. 작업 전체 cap으로 UI에 표시하려면 별도 합계 계약이 필요하며 이번 cap은 **요청 1회**다. 라이브러리 기간 예산은 모든 요청을 합산한다.

### 3.3 불변 DTO와 API

`security/cost.py`는 I/O 없는 DTO·상한 산술을 제공한다. providers에 의존하지 않아 import 순환을 피한다. frozen DTO 안의 컬렉션도 tuple/불변 값으로 고정한다.

| 제안 API/DTO | 필수 내용과 계약 |
| --- | --- |
| `CostRequest` | provider, endpoint, model_revision, api_version, operation(stt/summary/diarization), data_type, 실제 body bytes(메모리에만), 검증용 입력 메타데이터, wire 출력 제한. 클라이언트가 청구 상한 금액을 직접 선언하지 않는다 |
| `CostPolicy` | strict/general, currency, UTC 기간 `[start,end)`, 계정 한도, 사용자 요청 cap, policy_version, catalog_digest. 일반 모드 확인 결과도 고정한다 |
| `CostQuote` | request fingerprint, body_sha256·길이, 입력/출력 상한, U 또는 미검증 표시와 C, 통화·기간·정책·가격 기준/만료 시각·catalog/profile version. 비밀·본문은 포함하지 않는다 |
| `ReservationFactory` | 기존 네 인자에서 `Callable[[CostRequest], str]`로 변경. 옛 factory를 검증된 quote로 승격하는 호환 fallback은 없다 |
| `CostLedger.reserve_quote(request_id, quote, policy)` | quote와 일치하는 요청을 원자 예약한다. 같은 ID·같은 fingerprint는 기존 예약 반환, 내용/통화/기간/quote가 다르면 충돌. 반환 ID는 Gateway에서 다시 확인한다 |
| `CostLedger.validate_dispatch(reservation_id, provider, endpoint, body, now)` | 저장된 quote의 fingerprint, 정확한 wire의 모델/operation/입출력 제한, 현재 정책 version·기간·가격 유효성·노출액을 확인한다. strict는 검증된 quote가 필수다 |
| `CostLedger.apply_usage(event)` | reservation_id, source, event_id, version, provisional/final, currency, 원래 period ID, amount. 수동 확인 이벤트부터 연결하며 자동 supplier usage decoder는 별도 후속이다 |

`Run.request`는 직렬화를 끝낸 body와 profile별 메타데이터로 CostRequest를 만든다. STT/요약 어댑터는 실제 payload와 출력 필드를 전달한다. Gateway의 외부 request 형식은 body/reservation_id를 유지할 수 있지만, 자체적으로 저장 quote와 **실제 body**를 검증해야 한다. caller가 보내는 메타데이터만 믿지 않는다. 지원 프로토콜별 엄격한 body 검사에서 알 수 없는/중복 필드나 quote와 다른 model·출력 한도는 거부한다. bare `ledger.reserve(provider,...,amount,limit)`는 v1 관리·기존 단위시험용으로 남겨도 **새 strict dispatch 자격이 없다**. general도 자동 승격하지 않고 고정된 일반 모드 계획의 명시 권한을 요구한다.

새 dispatch는 RESERVED에만 허용한다. 첫 write 시도 후 UNKNOWN이 된 같은 요청의 후속 write는 **이미 발급한 동일 SendPermit과 실행 중 연결**에만 허용하며 quote/철회 검사를 계속한다. UNKNOWN ID로 새 연결·재접속·재시도를 시작하지 않는다. `reserve_quote`가 기존 ID를 반환한 사실은 재전송 허가가 아니다. 비용 검사와 handoff는 consent → ledger → owner의 기존 lock 순서로 같은 직렬화 경계에 둬 검사 후 가격/예산 변경이 끼어들지 못하게 한다.

`PrivacyPanel.prepare_execution` 한 번의 스냅샷에 G-P02 동의 문맥·설정 키와 비용 정책/catalog를 함께 고정한다. worker가 위젯을 다시 읽지 않는다. **구현 착수 때 C00의 G02A-05 결정과 일치하도록 정정:** 결과·checkpoint·admission·G-P03 settings_key인 config_key에는 비용 모드·통화·기간·요청 cap·계정 limit·가격 digest·비용 정책 version을 넣지 않는다. 기존 키에 있던 금액 cap/limit도 제거하고 제공업체·모델·endpoint/실행 위치·실제 모델 입력/출력 제한·기능·작업 세션만 남긴다. 비용 값은 결과를 바꾸지 않으며, 키에 넣으면 처리한 실시간 청크를 재전송하거나 요약 checkpoint를 버리는 문제가 반복된다. 권한·비용 신선도는 매 요청의 새 binding·policy snapshot·quote와 dispatch 재검사로 보장한다. 같은 결과 키가 옛 quote나 권한을 재사용하도록 허용하는 것은 아니다. `app/ai.py`의 wrapper는 새 DTO를 그대로 전달하고 예약 후 Gateway 호출 전에 `jobs.mark_remote_intent`를 기록한다. `ui/ai_bridge.py`의 Context 복사도 새 문맥을 보존한다. G-P02의 세션·기능·정책 version 검사를 우회하지 않는다.

## 4. ledger v2와 수명

### 4.1 additive schema 제안

기존 세 표를 DROP/ALTER해 의미를 바꾸지 않고 다음을 추가한다. 실제 DDL은 승인 뒤 구현하고 필수 값에 NOT NULL·금액 범위·유일성 제약을 둔다.

| 새 표 | 키·필수 열 |
| --- | --- |
| `security_cost_accounts_v2` | account_id PK, provider, currency, period_start_utc, period_end_utc, policy_version, amount_limit; provider/currency/기간별 유일성. endpoint를 바꿔 같은 공급자 예산을 우회하지 못한다 |
| `security_cost_requests_v2` | reservation_id PK, provider+request_id 유일, account_id FK, reserved_amount, actual nullable, state, quote_kind, model/profile ID, endpoint 식별용 digest, body_sha256·byte_length, input/output upper, price_as_of_utc·valid_until_utc, catalog_digest, request_fingerprint. 본문·세션 제목·파일 경로·비밀 없음 |
| `security_cost_usage_events` | provider/request/source/event_id 유일, version, kind, currency, period_id, amount, payload_digest; 동일 요청의 확정 event version·내용 충돌을 탐지 |
| `security_cost_meta_v2` | singleton, schema_version, revision, witness_protocol_version, predecessor_v1_state_digest, migration_state, clock_high_water_utc |

계정 통화·기간, 가격 기준시각은 요청이 계정 FK와 immutable quote를 통해 복원할 수 있어야 한다. FK만 가리키는 계정 행의 통화·기간을 나중에 바꾸지 않는다. 세션 FK의 cascade에 비용 기록을 연결하지 않는다. 세션 삭제 뒤에도 불투명 요청 ID와 정산에 필요한 최소 비용·가격/모델 근거만 보존한다. body hash도 내용 추측·연결에 쓰일 수 있는 파생 식별자이므로 일반 내보내기/진단에 노출하지 않고, 정산·보존 정책에서 취급한다.

VERIFIED quote의 가격 시각·입력/출력 상한은 필수다. USER_CAP에서 알 수 없는 가격 시각/상한은 **NULL과 미검증 사유**로 기록하며 0이나 현재 시각을 가격 근거처럼 만들지 않는다. 이 경우에도 계정의 통화·기간·정책 만료는 필수이며 만료 뒤 새 송신은 거부한다. NULL이 있는 quote를 strict로 사용할 수 없도록 API와 DDL의 quote_kind별 제약을 함께 둔다.

**G-P09 migration에 네 신규 표와 witness v2 프로토콜·v1 전환 상태를 버전 목록으로 인계한다.** G-P06은 additive 초기화/명시 전환만 제공하며 공용 `user_version` 변경과 v1 표 정리·backup/import 호환 정책은 G-P09가 다룬다. G-P02의 `security_grants_v2`·`security_consent_meta` 인계와 충돌하지 않는다.

### 4.2 기존 DB·witness 전환

v1 witness가 맞는지 **먼저 검증**한다. v2를 만들었다는 이유로 현재 DB를 새 기준으로 재서명해 rollback을 덮지 않는다. v1 금액에는 통화·기간 근거가 없으므로 UI의 과거 USD 라벨만으로 자동 매핑하지 않는다. v1의 RESERVED/UNKNOWN 및 확인되지 않은 계정은 `LEGACY_UNSCOPED`로 표시하고, 사용자 명시적 통화·기간 확인과 노출액 승계 전까지 새 원격 지출을 두 모드 모두 막는다. 기존 확정 내역도 명시 확인 뒤 보존하며 버리지 않는다. 유효한 빈 v1만 안전한 전환 절차를 거쳐 새 v2로 시작할 수 있다.

전환은 coordinator/DB 트랜잭션 안에서 v1 predecessor digest와 전체 v2 상태를 연결한 witness v2를 게시한다. 기존의 **witness 선행 → DB commit** 원칙을 유지한다. 전환 중 crash·witness replace 실패·DB commit 실패는 가용성을 잃을 수 있지만 노출액을 자동 해제하지 않는다. 재시작 시 혼합 버전/해시 불일치가 보이면 재구성·명시 정산 전 차단한다. v2와 v1 상태를 모두 검증 범위에 포함한다. 모든 v2 표를 잃은 DB를 새 예산으로 열지 않는다. DB와 witness가 모두 함께 과거로 복원된 공격까지 인증하는 외부 원장은 아니며 기존 witness의 보장 범위를 확대하지 않는다.

구버전 앱은 v2 witness를 v1로 해석하지 못하므로 **안전 차단**이 기대 동작이다. 구버전과 동시 쓰기/자동 downgrade는 지원하지 않는다. G-P09가 이 제약을 backup·복원 UI에 인계받는다.

### 4.3 통화·기간·이벤트 상태 규칙

- 계정은 고정 UTC 반개구간 `[start,end)`다. 만료 시각과 정확히 같으면 새 송신은 거부한다. UI는 UTC와 현지 표시를 함께 제공한다. 자동 월 경계 계산이나 환율 변환을 이번 계약에 숨겨 넣지 않는다. 사용자가 새 기간을 명시 적용하고 새 계획을 만든다.
- 계정별 `confirmed + reserved + unknown + next <= limit`를 원자 검사한다. 예산 축소는 적용 가능하나 노출액을 줄이지 않으며 다음 송신이 막힌다. period를 바꿔 기존 예약/UNKNOWN을 숨길 수 없다. **같은 provider의 이전 기간 또는 다른 통화에 미정산 노출이 있으면 정산·명시 승계 전 신규 지출을 막는 보수적 방식**을 제안한다. 기존 기간의 SETTLED는 새 기간에 다시 더하지 않고 원래 기간에 남긴다.
- 예약은 가격·통화·기간을 고정한다. 늦게 온 정산은 원래 요청의 계정에 적용한다. 현재 UI의 통화·기간으로 해석하지 않는다. 알려진 과소 예약은 실제 금액을 기록하고 계획 오류를 표시하며 해당 provider의 다음 송신을 차단한다. 사용자 정책의 명시 재설정 전 숨기지 않는다.
- 첫 write 전 비용·철회·취소 실패는 RESERVED를 보존한다. 확실한 미송신 확인에 의한 명시 release만 가능하다. 첫 write 시도 직전에 UNKNOWN으로 바꾸며 write 예외도 UNKNOWN이다. 철회·취소·세션 삭제·재시작·period 변경으로 UNKNOWN을 해제하지 않는다. timeout 후 무조건 자동 재시도하지 않는다. 수동 재시도는 새 request/reservation ID다.
- provisional은 최종 비용에 더하지 않고 원래 예약/UNKNOWN 노출을 유지한다. final은 같은 요청의 범주를 원자 이동한다. 같은 event ID/내용은 no-op, 같은 ID/다른 내용·역순 version·상충 final은 `SETTLEMENT_CONFLICT`로 보류하고 기존 노출을 유지한다. 이미 SETTLED인 금액을 다시 더하거나 두 번 반환하지 않는다. 다른 통화·기간 event도 보류한다. 공급자가 event/version을 제공하지 않으면 자동으로 최종이라고 추측하지 않는다.
- 예: limit=100, UNKNOWN=60에서 확인된 final40은 `(confirmed,reserved,unknown,available)=(40,0,0,60)`이다. 재수신·재시작 후에도 같다. partial 응답/완성 텍스트를 받았다는 사실만으로 금액을 final로 처리하지 않는다.
- 가격 유효성은 `[valid_from,valid_until)`로 reserve/open/각 write 전에 재검사한다. first write 뒤 만료면 새 write를 막고 이미 넘긴 비용은 UNKNOWN으로 유지한다. 일반 모드의 기존 VERIFIED quote가 만료됐다고 자동으로 USER_CAP으로 바뀌지 않는다. 최초부터 일반 모드에서 미검증 가격으로 확인한 계획만 USER_CAP이다.
- UTC 시계가 저장한 high-water보다 뒤로 가면 `COST_CLOCK_INVALID`로 차단한다. 정상 진행 중 TTL에는 monotonic deadline도 사용한다. 시스템 시각 자체를 신뢰할 수 없는 환경의 가격 신선도를 보증하지 않는다.

## 5. 차단 코드와 UI

| 코드 | 의미/사용자 다음 행동 |
| --- | --- |
| `COST_PRICE_UNKNOWN` / `COST_PRICE_EXPIRED` | strict에서 가격 없음/만료. 승인된 오프라인 가격 근거 갱신 또는 사용자가 일반 모드를 별도 선택 |
| `COST_BOUND_UNVERIFIED` | 모델/요청의 입력·전체 과금 출력 상한 근거 없음. cap 증가로 해결되지 않음 |
| `COST_CAP_REQUIRED` / `COST_CAP_EXCEEDED` | 양의 cap 없음 / 계산 U가 cap보다 큼 |
| `COST_REQUEST_INVALID` / `COST_AMOUNT_OVERFLOW` | wire 필드/음성 메타데이터 오류 또는 정수 범위 초과 |
| `COST_QUOTE_MISMATCH` / `COST_QUOTE_EXPIRED` | 예약과 실제 요청/가격 snapshot 불일치 또는 예약 뒤 만료. 새 계획·예약 필요 |
| `COST_CURRENCY_MISMATCH` / `COST_PERIOD_CHANGED` | 통화 또는 요청 기간 불일치. FX·자동 period 대체 없음 |
| `COST_LEGACY_UNSCOPED` / `COST_UNRESOLVED_EXPOSURE` | 옛 노출액 또는 다른 기간/통화의 미정산분 확인 필요 |
| `COST_CLOCK_INVALID` / `COST_PLAN_UNDERESTIMATED` | 시계 역행 / 실제 금액이 계획 상한 초과. 신규 송신 차단 |
| 기존 코드 유지 | `BUDGET_EXCEEDED`, `BUDGET_POLICY_CHANGED`, `RESERVATION_CONFLICT`, `RESERVATION_NOT_DISPATCHABLE`, `SETTLEMENT_CONFLICT`, `LEDGER_ROLLBACK_DETECTED`와 G-P02 동의 오류 |

복합 실패는 원인별 허용 코드 집합을 oracle에 적고 특정 구현 검사 순서를 복제하지 않는다. 공통 수락 조건은 open/write 0, 금액·동의 불변이다. 단일 원인 행은 위 정확한 코드를 검사한다. `Run.request`와 UI는 safe code를 보존하되 provider 예외 본문·비밀·wire 내용을 오류에 넣지 않는다. 전송 후 실패에는 `outcome_known=False`가 유지돼야 한다.

UI에 strict/일반, 현재 통화·UTC 기간, 가격 기준/만료 시각·출처 식별자, 검증 여부, 예상 입력/출력 상한, 계산 U, 사용자 cap C, 요청 1회와 기간 전체 예산을 구분해 표시한다. 실제 payload 생성 전에는 **잠정 예상**으로 표시하고 최종 예약액과 혼동하지 않는다. 일반 모드 확인 창에는 “입력한 cap은 공급자 청구 상한을 보장하지 않음”, UNKNOWN 유지·중복 청구 위험을 명시한다. 이 선택은 전송 동의를 대신하지 않는다. 설정 변경은 이전 실행 계획을 무효화한다. 통화/기간별 confirmed/reserved/UNKNOWN과 legacy 보류를 표시하고 수동 정산은 선택 요청에 고정된 통화·기간으로만 수행한다. 기존 USD 하드코딩 표시는 제거한다. 가격 확인을 위해 외부 사이트를 자동 열지 않는다.

## 6. 유한 경우의 수와 독립 oracle

### 6.1 합성 계산 기준

다음 수치는 **합성 fixture**이며 실제 모델/가격의 사실이 아니다. 텍스트 fixture `TEXT-FIXTURE-v1`은 검증된 가상 profile로 `Tin=B+3`, `U=ceil(2×Tin/3)+ceil(5×O/2)+7` microunits다. 고정 3토큰은 fixture의 구조 비용이다. 예를 들어 B=1/O=1은 U=13, B=33/O=32는 U=111이다. 음성 fixture `AUDIO-FIXTURE-v1`은 `U=11×ceil(duration_ms/1000)+7`이다. 1/999/1000ms는 U=18, 1001ms는 U=29다. 0ms는 잘못된 입력이다. 실제 텍스트에 `B+3`을 적용하지 않는다.

기대 U는 제품 calculator/profile을 import하지 않는 시험 전용 **Fraction 기반 유리수 + 독립 올림**으로 구하고 위 손계산 상수를 함께 검사한다. 실제 byte 수는 독립 UTF-8 fixture의 알려진 길이와 비교한다. fake profile은 일반 계산 엔진 시험용이며 production catalog allowlist로 승격되지 않는다.

### 6.2 대표 집합 분모

각 family는 자체 fixture를 가지며 family 사이 직적을 주장하지 않는다. 아래 **F=Ω**, 제외 0이다. 거부 입력·실패 순서도 feasible 행으로 유지한다. STATE의 도달 불가능 상태를 직접 주입하지 않고 모든 명령열의 거부 결과까지 관측한다. 아직 생성·실행하지 않았으므로 E=0이다.

| family / 제안 시험 계층 | 입력 분할과 독립 산식 | Ω=F / 계획 E |
| --- | --- | --- |
| TEXT / unit·property | 가격 valid/unknown/expired 3 × 텍스트 bytes B=0/1/33/4096/4097 5 × 실제 출력 필드 absent/1/32/33 4 × cap 없음/U−1/U/U+1 4 × strict/general 2 × 상한 근거 verified/unverified 2. profile 입력 최대4096·출력 최대32. absent/33은 wire invalid로 두 모드 모두 거부. 가격/근거 부정도 제외하지 않음 | **960 / 0** |
| AUDIO / unit·provider integration | 가격 3 × 지속시간 0/1/999/1000/1001ms 5 × profile duration_verified/audio_token_unknown/header_payload_mismatch 3 × cap 4 × 모드 2. PCM 표본은 정수 frame/rate로 정확히 구성 | **360 / 0** |
| BALANCE / ledger unit | 노출 구성 `(3,0,0)/(0,3,0)/(0,0,3)/(1,1,1)` 4 × limit4/5/6 3 × 통화 USD/EUR 2; next=2, 같은 유효 기간. limit4 거부,5 정확경계 허용,6 허용 | **24 / 0** |
| BIND / Gateway integration | provider, endpoint, model+API revision, operation, body digest, 실제 출력 필드, catalog digest, budget policy version의 일치 여부 8개 bit. 각각 하나의 값만 바꾼 복합 부정. 같은 provider 다른 endpoint도 포함 | **256 / 0** |
| PRICE-TIME / fake clock integration | 시각 valid_from−1/valid_from/valid_until−1/valid_until/valid_until+1 5 × 관측 경계 reserve/open/second-write 3 × 정상/벽시계 역행 2 × 모드 2 | **60 / 0** |
| STATE / bounded state model | alphabet reserve60/first-write/timeout/release/provisional-v1/final40-v2/final41-v2, 길이0..4의 모든 명령열. `1+7+49+343+2401` | **2,801 / 0** |
| ORDER / barrier integration | R=reserve, O=open시도, W=첫write시도에 R<O<W, 철회V 독립. 위치4 × V 종류 grant철회/세션삭제/취소 3 × transport 정상/open실패/부분write예외 3 | **36 / 0** |
| PERIOD / ledger integration | quote/계정 통화 일치·불일치 2 × now=start−1/start/end−1/end/end+1 5 × 같은 provider의 이전 기간 노출 없음/RESERVED/UNKNOWN/SETTLED 4 × 모드2. 새 기간 quote를 원할 때는 별도 명시 적용; 현재 interval 밖은 거부 | **80 / 0** |
| EVENTS / ledger unit·restart | 요청 없음/RESERVED/UNKNOWN/SETTLED/RELEASED 5 × 이벤트 provisional-v4/final40-v3/final41-v4/final-v1역순/동일ID다른내용/다른통화/다른기간 7 × 재열기 없음/있음2. SETTLED fixture는 final40-v3, 그 밖에 요청이 있는 상태는 기존 provisional-v2를 둬 역순/재수신 기준을 독립 정의. final41-v4는 미정산 상태에서 첫 확정이면 허용, SETTLED에서는 상충으로 보류 | **70 / 0** |
| NUMERIC / unit | 필드 B/O/단가분자/단가분모/cap/limit/usage금액/version/period_start/period_end 10 × 값 −1/0/1/MAX−1/MAX/MAX+1/True/1.0/문자열1/None/NaN/+Inf 12. MAX=2^63−1 | **120 / 0** |
| DB / persistence fault | 아래 DB-01..16 손으로 명시한 16가지. 실패 행 포함, 임의 직적 축약 아님 | **16 / 0** |
| UI / offscreen | 모드2 × 가격3 × cap U−1/U 2 × 실행 스냅샷 뒤 UI 변경 없음/있음2 × STT/요약2 | **48 / 0** |
| LOCAL / provider contract | 로컬 Faster-Whisper / 유효한 고정 Ollama / 로컬이라고 주장하는 미검증 원격 모델. 앞의 두 경우 비용 catalog 없음과 독립, 마지막 거부 | **3 / 0** |
| 합계 | 합성 대표 행 합계. 서로 다른 가족은 ID prefix로 구별 | **4,834 / 0** |

TEXT에서 U−1/U/U+1는 독립 가상 계산의 기준값이다. invalid 조합에서도 기준 U를 계산해 fixture cap을 정할 수 있으나 제품이 그 입력을 수락한다는 뜻은 아니다. 출력 absent 행은 cap 좌표용 O=1을 사용한다. AUDIO의 0ms도 cap 좌표용 가상 U=7을 쓰되 oracle는 입력 거부다. 유효한 빈 text B=0은 profile이 허용하는 빈 사용자 텍스트와 고정 프레이밍을 가진 요청이며 빈 wire body가 아니다. 일반 모드의 unknown/expired/unverified는 별도 확인된 USER_CAP만 가능하다. cap 없음·잘못된 wire·초과 크기는 일반에서도 거부한다.

PRICE-TIME은 reserve를 시험할 때 그 이전 시각을 가정하지 않는다. open/second-write는 유효한 시각에 실제 예약/선행 write를 끝낸 뒤 fake 시각을 목표값으로 이동한다. 목표 시각이 과거이면 high-water에 의한 거부도 기대한다. 일반의 만료 가격 허용은 **reserve 이전부터** USER_CAP으로 고정한 행뿐이며, 유효 VERIFIED quote의 사후 만료는 두 모드 모두 재계획한다.

NUMERIC은 단일 필드를 바꾼 **판정 대표값**이다. 나머지 필드·기간 순서는 별도 손작성 fixture로 맞춘다. 0의 의미는 필드별로 다르다(분모·실제 출력 제한은 양수, 금액 actual0과 기간 시작0은 표현 가능). MAX의 표현 가능성과 실제 요청 한도/기간 순서에 의한 거부를 나눈다. 이 120행이 모든 수치 경계의 교차 조합이라는 주장은 하지 않는다.

### 6.3 DB 가족 16행

| ID | 준비/주입 | 기대 |
| --- | --- | --- |
| DB-01 | 새 DB→v2 초기화→재열기 두 번 | 테이블·계정 중복 없음, 노출액 불변 |
| DB-02 | 유효한 빈 v1와 witness→승인된 전환 | v1 검증 후 v2 생성, 반복 멱등 |
| DB-03 | v1 RESERVED60 | 자동 USD/현재 기간 배정 금지, legacy 차단 |
| DB-04 | v1 UNKNOWN60→명시 통화·기간 승계→재열기 | UNKNOWN60 그대로, 새 예산으로 초기화 금지 |
| DB-05 | v1 SETTLED40과 출처 불명 계정 | 자동 소실 금지, 명시 이력 확인 경로 |
| DB-06 | v1 witness 없음/DB에는 요청 존재 | rollback 차단, v2 생성으로 정상화 금지 |
| DB-07 | v2 witness 삭제 | 차단, 재생성 금지 |
| DB-08 | v2 witness 내용 손상 | 차단 |
| DB-09 | witness를 둔 채 DB만 이전 백업으로 rollback | 차단 |
| DB-10 | witness를 둔 채 DB 파일 소실 | 새 예산 생성 금지 |
| DB-11 | v2 표 하나 삭제 | 차단, CREATE IF NOT EXISTS로 손실 은폐 금지 |
| DB-12 | v2 표 전부 삭제·v1 표 잔존 | v1 새 ledger로 재시작 금지 |
| DB-13 | 전환 witness replace 실패 | 원자 오류, 자동 송신/노출액 해제 없음 |
| DB-14 | 전환 witness 게시 후 DB commit 실패 | 다음 열기 fail closed, 혼합 버전 재서명 금지 |
| DB-15 | 정상 v2 reserve/UNKNOWN/정산 후 구버전 ledger로 열기 | v1 소비자는 안전 차단, v2 금액을 모른 채 지출 불가 |
| DB-16 | 세션 삭제 후 ledger 재열기·늦은 final40-v2 | UNKNOWN60 보존 후 원 계정 confirmed40, 세션 복원 불필요 |

소유한 TEMP subprocess 또는 결정적 I/O fault로만 주입한다. 실제 라이브러리·vault·번들은 사용하지 않는다. DB-15의 구버전 코드는 기준 commit의 임시 사본을 사용하며 workspace 코드를 바꾸지 않는다.

### 6.4 상태 oracle·행 감사

시험용 순수 모델은 `(요청존재, 상태, reserved_amount, actual, 마지막event/version, 동의유효)`만 갖는다. 제품 ledger의 SQL·상태표·상한 함수를 import하지 않는다. STATE의 reserve는 같은 request_id를 사용하고, 거부된 명령 뒤에도 다음 명령을 계속 실행한다. first-write는 유효한 RESERVED에서만 UNKNOWN, timeout은 범주를 바꾸지 않음, release는 미송신 RESERVED만 RELEASED, final40/41은 RESERVED/UNKNOWN에서 SETTLED로 이동하되 첫 final과 다른 금액의 후속 final은 충돌이다. 같은 final 재수신은 멱등이다. final 없는 RELEASED나 요청 없음의 usage는 거부한다. provisional은 금액 합계에 영향이 없다.

각 trace 끝에 실제 DB를 닫고 다시 열어 모델과 비교한다. 이 재열기는 **같은 행의 추가 assertion**이며 2,801행을 두 배로 세지 않는다. 깊이4를 넘는 이력은 전수 범위 밖이다. EVENT 가족과 별도 결정적 R→W→timeout→재열기→final→중복final 회귀로 긴 핵심 이력을 보강한다. 이 보강 node는 4,834 유한 행에 더하지 않고 auxiliary로 따로 보고한다. ORDER에서는 transport 실패 뒤의 write시도도 실행해 안전 거부를 검사하며 fixture 불가능으로 제거하지 않는다.

ID는 `G06-{family}-{고정폭 ordinal}`이며 family별 인자 이름/값을 JUnit property에 기록한다. 예: TEXT-000..959, STATE-0000..2800. manifest의 별도 상수 `960,360,24,256,60,2801,36,80,70,120,16,48,3` 및 독립 `divmod` 좌표 복원으로 기대 ID 집합을 만든다. 시험 생성기의 `len`만 분모로 쓰지 않는다. 수집 node 수, 실행 행 수, 유일 ID, 누락·중복·추가·skip을 별도 대조한다. property node와 trace 내부 명령 수를 행 수와 합산하지 않는다.

## 7. 기존 시험 연결·추가 속성·mutation 계획

| 직접 존재를 확인한 기존 node | 유지/새 계약과의 관계 |
| --- | --- |
| `tests/property/test_security_case_space.py::test_integer_budget_composition_boundary` | 기존 네 노출 구성×세 한도 12행. BALANCE는 통화 두 개와 v2로 검증; 기존 행을 없애거나 새 행 성공으로 대신하지 않음 |
| 같은 파일 `::test_integer_representation_boundaries`, `::test_cost_partition_preserves_exposure` | 기존 int 경계와 같은 총액의 분할 법칙 유지. **요청별 올림 비용 자체**는 분할 시 늘 수 있으므로 새 상한 계산에 동일 금액 분할 불변을 잘못 적용하지 않음 |
| `tests/unit/test_security.py::test_cost_unknown_restart_settlement_and_idempotency` | 60→40·중복·release 금지 보존. EVENTS는 통화·기간·event/version을 추가 |
| 같은 파일 `::test_cost_concurrent_reservations_have_one_winner` | v2에서 두 ledger/동일 계정 동시 예약도 한도 내 승자만 허용 |
| 같은 파일 `::test_ledger_detects_database_rollback_against_witness`, `::test_ledger_fails_closed_for_missing_or_corrupt_witness`, `::test_witness_with_lost_cost_schema_is_not_treated_as_new_budget` | v1 보장 유지와 v2 전환/누락 표 검증 |
| `tests/integration/test_gateway.py::test_revoke_before_first_or_second_handoff_blocks_unsent_bytes`, `::test_deadline_and_cancel_preserve_unsent_or_unknown_cost`, `::test_unknown_cost_survives_failed_write_restart_and_session_delete` | 기존 철회 양순서·handoff·삭제·재시작 보존. ORDER는 quote 검증을 함께 관측 |
| `tests/ui/test_privacy_ui.py::test_worker_reservation_factory_uses_frozen_gui_values`, `::test_frozen_worker_scope_cannot_widen_or_outlive_revocation` | cap 그대로 예약한다는 과거 기대값은 새 계산 U로 적응하되 GUI snapshot·철회 assertion은 보존 |
| `tests/ui/test_consent_scope_ui.py`, `tests/integration/test_consent_scope.py` | G-P02 범위·세대·정책 version과 비용 계획 결합. 동의 허용이 비용 허용을 대신하지 않음 |

새 네 시험 파일은 unit `test_cost_cap.py`(DTO·산술·형식·이벤트), property `test_cost_cap_case_space.py`(TEXT/숫자/상태/manifest), integration `test_cost_cap.py`(wire·음성·순서·DB), ui `test_cost_cap_ui.py`(표시·snapshot·일반 확인)를 제안한다. 가족이 실제로 들어갈 최종 node는 구현 승인 후 매핑한다. 보강 속성은 (1) 검증 profile의 B/O 증가가 U를 줄이지 않음, (2) 더 큰 cap이 U를 바꾸지 않음, (3) 가격표 순서가 quote digest/결과를 바꾸지 않도록 canonical화, (4) 재시작·같은 final 재수신이 노출액을 바꾸지 않음이다. 유한 대표값 외 속성은 seed·예제 수·범위를 실행 결과에 따로 기록한다.

다음 **28개 명명 mutant**를 TEMP의 pyproject/src/tests 전체 사본에 한 번에 하나만 적용한다. 정상본 PASS 후 목표 assertion FAIL이어야 검출이다. import/수집 오류·권한·timeout은 invalid다. 실행 전 `__file__`이 사본 src인지 확인한다. 실제 workspace와 인덱스는 수정하지 않는다.

| ID | 결함 | 목표 oracle |
| --- | --- | --- |
| M01 | unknown 가격 strict 거부 제거 | TEXT strict unknown에서 open0 |
| M02 | 가격 만료 비교 `<`/`<=` 반전 | PRICE-TIME 동일 시각 |
| M03 | 상한 근거 없이 bytes를 토큰으로 간주 | TEXT unverified 거부 |
| M04 | 출력 전체 과금 상한 확인 제거 | TEXT output invalid/unsupported |
| M05 | 항목별 올림을 내림으로 변경 | 손계산 U13/U111 |
| M06 | 계산 U 대신 사용자 cap 예약 | 같은 U에서 cap 변화에도 예약 U 불변 |
| M07 | U>cap을 U>=cap으로 변경 | TEXT 정확 cap 허용 |
| M08 | 음성 ms를 byte/초로 오인 | AUDIO 1000/1001ms U18/U29 |
| M09 | unknown 노출액을 예산 합계에서 제외 | BALANCE unknown 구성 |
| M10 | 예산 `>`를 `>=`로 변경 | BALANCE limit5 허용 |
| M11 | 통화 키 제거 | PERIOD 통화 mismatch |
| M12 | 기간 경계 end 포함 | PERIOD at-end 거부 |
| M13 | 이전 기간 UNKNOWN 무시 | PERIOD 새 기간 우회 차단 |
| M14 | body/model fingerprint 검사 제거 | BIND body/model 부정 |
| M15 | 실제 wire 출력 필드 검사 제거 | BIND 출력 필드 부정 |
| M16 | catalog/policy version 검사 제거 | BIND catalog/policy 부정 |
| M17 | 각 write의 비용 재검사 생략 | PRICE-TIME second-write 만료 |
| M18 | 첫 write 전 UNKNOWN 전환 제거 | ORDER 부분 write 예외에도 UNKNOWN |
| M19 | timeout/revoke에서 UNKNOWN release | STATE/ORDER 노출액 유지 |
| M20 | final을 UNKNOWN에 가산 | 60→40 예제의 unknown0 |
| M21 | 중복 final을 두 번 더함 | EVENTS 동일 event no-op |
| M22 | 역순/상충 event 허용 | EVENTS 보류·노출 불변 |
| M23 | provisional을 final로 처리 | STATE confirmed0 유지 |
| M24 | v1을 자동 USD/현재 기간에 승격 | DB-03/04 legacy 차단 |
| M25 | v2 표 누락 시 새 witness 생성 | DB-11/12 차단 |
| M26 | ledger hash에서 v2 메타/요청 누락 | DB-09/11과 직접 quote 변조 거부 |
| M27 | worker가 변경된 UI cap/모드를 읽음 | UI frozen 계획 불변 |
| M28 | 시계 high-water 검사 제거 | PRICE-TIME 역행 거부 |

## 8. 후속 구현에 요청하는 정확한 쓰기 범위

아래 **29파일**을 요청한다. 승인 전에는 변경하지 않는다. 새 타입에 따른 기존 fixture 적응은 기존 검증의 의미를 유지하고 신뢰 가격 근거를 조작해 정상으로 만들지 않는다. 특히 기존 fake adapter를 통과시키려고 production strict 기본값을 낮추지 않는다.

| 구분 | 파일 |
| --- | --- |
| 신규 보안 모듈 2 | `src/recoryn/security/cost.py`, `src/recoryn/security/cost_catalog.py` |
| 보안 수정 3 | `src/recoryn/security/ledger.py`, `src/recoryn/security/gateway.py`, `src/recoryn/security/__init__.py` |
| 제공업체 수정 4 | `src/recoryn/providers/contracts.py`, `src/recoryn/providers/_common.py`, `src/recoryn/transcription/adapters.py`, `src/recoryn/summarization/adapters.py` |
| 실행 연결 3 | `src/recoryn/app/ai.py`, `src/recoryn/ui/privacy.py`, `src/recoryn/ui/ai_bridge.py` |
| 신규 시험 4 | `tests/unit/test_cost_cap.py`, `tests/property/test_cost_cap_case_space.py`, `tests/integration/test_cost_cap.py`, `tests/ui/test_cost_cap_ui.py` |
| 기존 시험 적응 12 | `tests/unit/test_security.py`, `tests/unit/test_providers.py`, `tests/property/test_security_case_space.py`, `tests/integration/test_gateway.py`, `tests/integration/test_egress_independent.py`, `tests/integration/test_provider_security_independent.py`, `tests/integration/test_publication_independent.py`, `tests/integration/test_consent_scope.py`, `tests/contract/test_provider_contracts.py`, `tests/ui/test_privacy_ui.py`, `tests/ui/test_consent_scope_ui.py`, `tests/integration/test_ai_independent.py` |
| 계약·결과 1 | `docs/testing/g06-cost-cap-cases.md` |

12 source + 16 test + 1 document = 29. `providers/__init__.py`는 DTO를 security에서 공개해 변경을 피한다. `security/consent.py`, `jobs/store.py`, `content/store.py`, `ui/main.py`, 공용 pyproject·릴리스 파일은 범위 밖이다. 구현 중 다른 fixture/공용 계약 파일 수정이 필요하면 실제 실패와 함께 범위 추가를 먼저 요청한다. `tests/ui/test_live_ui.py`·`tests/ui/test_gpu_runtime_ui.py`도 이 목록에는 없으며 **tests/ui 전체 실행 대상**이다. fixture 수정이 필요하면 별도 승인을 받는다. G-P09 문서는 인계 사항을 이 문서에 남기고 C00이 통합한다.

## 9. 대안과 승인 요청

| 대안 | 장점 | 한계/제안 |
| --- | --- | --- |
| 요청 cap 자체를 계속 예약 | 기존 API 변경 작음 | 모델/요청 상한을 검증하지 못해 strict의 F-COST01을 닫지 못함. 일반의 명시 USER_CAP에만 제한 |
| 실제 토크나이저 패키지를 실행 중 설치/다운로드 | 일부 모델의 입력 추정 정확도 향상 | 이번 금지 범위이며 전체 과금 출력·음성/수수료까지 자동 증명하지 않음. 채택하지 않음 |
| 모든 원격 요청을 무조건 차단 | 초기 안전성과 구현 단순성 | 비용 기능을 실사용할 수 없음. 검증 근거 없는 모델의 strict에는 이 결과가 맞지만 유효 profile/fake와 일반 모드 계약을 생략하지 않음 |
| 검증한 offline catalog + strict 기본 + 명시 일반 모드 | 상한 근거·불명확 실행을 구분하고 기존 사용자 확인 경로 유지 | 가격 유지보수와 요청별 profile 검증 필요. **권고안** |
| 이전 기간 UNKNOWN을 새 기간 가용액에서 차감 | 기간 전환 때 계속 사용 가능 | 통화/정책 변경과 중복 이월 방지에 별도 배분 원장 필요. 이번에는 미정산 차단 방식 권고 |
| G-P09 이후에 ledger v2만 구현 | 공용 migration 순서 단순 | 현재 G-P06의 통화·기간 요구를 미룸. additive+fail-closed 전환과 G-P09 인계 권고 |

C00에게 요청하는 결정: (a) strict 기본·명시 일반과 USER_CAP의 제한, (b) 실가격 미검증 모델 strict 차단 및 offline catalog 승인 절차, (c) 새 요청 DTO/29파일 범위와 G-P02/G-P03 이후 직렬 수정, (d) additive v2·witness 전환·legacy 명시 승계·타 기간 미정산 차단, (e) F-COST02 자동 usage 연결은 S2로 남기고 최소 이벤트 기반/수동 정산만 포함, (f) **4,834 대표 행과 28 mutant**의 계획 분모. 이는 구현 완료 승인이 아니다.

## 10. 실행·제출 게이트와 계약 작성 당시 관측

승인 후 기준 commit·각 파일 LF hash·환경을 고정한다. 정상본에서 유한 행 4,834개 및 auxiliary/속성 node를 별도 보고하고 ID 누락·중복·추가0, skip0을 요구한다. 수집 node 수와 의미 행 수를 혼동하지 않는다. 네 신규 파일의 실행 시간·행/초를 측정해 보고하며 느리다고 분모나 거부 행을 몰래 축약하지 않는다. 필요하면 근거와 축약안을 C00에게 먼저 제시한다.

정상본→독립 fake의 원 반례(작은 cap+큰 입력 거부, cap 정확 경계 허용, strict unknown/expired 거부, 일반 USER_CAP 식별)→TEMP mutation 순으로 확인한다. 기존 security/Gateway/privacy/provider 계약 및 **tests/ui 전체**, G-P02 새 네 시험과 G-P03 선택 CAS 회귀를 실행한다. 전체 오프라인 회귀와 `ruff check`, `ruff format --check`, `python -m mypy src/recoryn scripts packaging`를 통합 게이트로 한다. 시험은 `-p no:cacheprovider`, 고유 OS TEMP `--basetemp`, `QT_QPA_PLATFORM=offscreen`과 네트워크/실제 모델/vault 쓰기 차단 fixture를 사용한다. 네트워크 시도를 삼킨 예외도 실패다.

계약 작성 당시 관측은 **코드·기존 시험 node·문서 읽기와 분모 산술 확인만**이었다. 당시 새 제품 구현0, 새 시험 실행0, mutation 실행0, 실제 가격/계정 검증0이며 4,834/28은 계획이었다. 구현 후 직접 결과는 §12에 있다. 공급자 최종 청구·환율·지연 청구의 절대 상한, 독립 공급자 서버가 출력 제한을 지킨다는 보장은 하지 않는다. C00 승인과 작성자 외 독립 검토 전에는 G-P06을 완료 처리하지 않는다.

## 11. 구현 중 관측과 시간 게이트 재결정

§10의 마지막 문단은 계약 단계 당시의 이력이다. 구현 시작 기준은 234dd31이며 실제 가격 catalog는 여전히 비어 있다. 비용 정책은 §3.3의 C00 결정대로 결과 config_key에서 제외하고 고정 실행 snapshot/quote에만 넣는다. 요청 DTO에는 실제 wire bytes와 닫힌 의미 header만 들어가고, 저장소에는 body 자체나 인증 header를 넣지 않는다. G04의 우선 수정 때마다 G06 29파일의 hash/부재를 별도로 동결하고 대조했다.

초기 선택 직접 결과: 신규 unit와 기존 security **292 PASS / 7.63초**, 신규 property **3763 PASS / 144.06초**, 신규 UI **50 PASS / 5.84초**다. 아직 최종 정상본·전체 분모 PASS가 아니다. 기존 회귀의 첫 선택은 **898 PASS·436 FAIL / 135.63초**이며, 기존 4인자 factory와 v1 cap 예약을 쓰던 승인 12파일 안의 fixture 적응이 필요했다. 목록 밖 UI 파일의 실패는 이 실행에서 없었다. 기존 권한/철회 oracle을 줄이거나 제품에 구 factory 승격 fallback을 넣지 않는다.

property 파일만 60초를 넘은 실측을 C00에게 먼저 보고했다. **C00 답변: ‘4,834행 유지, 초과 실측 후 예산 결정’.** 길이4 STATE 2,401행을 빼거나 별도 게이트로 옮기지 않는다. 공통 prefix의 검증된 임시 DB 사본을 재사용하는 fixture 최적화를 검토하며, 최종 새 4파일의 합계 실행 시간을 다시 보고한다. 독립 oracle·각 행의 영속 재열기 검증과 유일 case ID는 유지한다. 아직 최종 실행·mutation·정적 검사·독립 검토 완료를 주장하지 않는다.

### 11.1 최적화와 최종 실행 입력

STATE의 alphabet·길이0~4·2,801 ID는 그대로다. 동일 prefix를 실제 ledger 명령으로 한 번 만들고 연결을 닫은 DB/witness를 다음 행의 별도 경로로 복사한다(WAL 부재 확인). 각 행은 자신의 완성 snapshot을 실제 CostLedger로 다시 열어, 제품의 SQL/quote를 참조하지 않는 순수 상태 모델이 전체 명령열에서 계산한 잔액·상태·거부 여부와 대조한다. 재열기 때문에 가려질 수 있는 차이를 보강하려고 대표 상태열 7개는 한 연결에서 명령마다 검증하고 snapshot 결과와 비교한다. 이 family는 시간·dispatch 검사를 수행하지 않으며 그 경계는 PRICE-TIME/BIND/ORDER에서 별도로 검증한다. 최적화 중 선택 실행은 **3764 PASS / 59.10초**였으며 최종 네 파일 합계가 아니다.

최종 실행에는 의미 분모 **4,834행**과 파일별 manifest 4개를 구별한다. 단위 손계산/빈 catalog 2개, property 단조성 1개·연속 상태열 7개, UI 확인/결과 키 2개, 독립 fake의 원 반례 5개, 실제 제공업체 wire+빈 catalog 2개, v1 revision을 그대로 둔 v2 quote/meta 변조 2개를 auxiliary로 별도 센다. 원 반례의 손계산은 `ceil(2*(4096+3)/3)+ceil(5*32/2)+7=2820`이며 cap 2819 거부·2820 허용, strict unknown/expired 차단과 일반 USER_CAP 13을 비교한다. 실제 가격으로 오인하지 않도록 모든 합성 profile은 테스트에서만 주입한다. 배포 catalog는 항목 0개다.

기존 4인자 factory 시험은 실제 CostRequest를 받도록 적응하고, 전송을 수행하는 fixture에는 명시적 합성 가격과 통화·기간이 있는 v2 예약을 준다. 순수 v1 정산·rollback·재시작 시험은 legacy 동작을 계속 확인한다. 비용을 설정하지 않았다는 이유가 동의·철회 oracle를 대신하지 않도록, 기존 전송 성공·UNKNOWN·fence 결과를 그대로 검사한다. final 정상본·case ID 감사·mutation·정적 검사와 전체 회귀는 **234dd31+G06 29파일** 사본에서 실행하며 G04 변경을 섞지 않는다.

mutation 선택을 점검하면서 통화 identity 결함을 가격 통화 불일치가 대신 차단할 수 있음을 확인했다. 서로 다른 USD/EUR 모델의 합성 가격을 모두 유효하게 둔 같은 기간 계정 1행을 auxiliary로 보강한다. EUR 예약은 EUR 계정에만 들어가고 빈 USD 계정의 잔액은 그대로여야 한다. 이로써 계획 의미 행 4,834 + auxiliary 22 + manifest 4 = 최종 새 시험 **4,860 node**이며 분모를 늘려 coverage를 주장하지 않는다.

최적화한 새 네 파일의 직접 선택은 **4857 PASS / 93.14초**였고 testcase 시간 합은 unit 5.687·property 54.378·integration 26.226·UI 4.671 = **90.962초**였다. 이후 보강한 quote/meta 변조·통화 identity 3행은 **3 PASS / 0.45초**로 따로 확인했다. C00이 이 실측을 보고 **이 PC의 합계 120초 예산을 승인**했다. 의미 분모는 계속 4,834행이며 축약하지 않았다.

첫 분리 사본 전체 오프라인 실행은 **13945 PASS·34 FAIL / 554.22초**였다. 실패는 전부 승인 범위의 `tests/property/test_security_case_space.py`에서 전송 fixture가 v1 cap 예약을 써 `COST_LEGACY_UNSCOPED`에 막힌 경우였다. Q24의 admission/handoff만 실제 DTO·합성 가격·v2 quote로 적응한다. 권한·철회·owner·전송 경계의 기대값과 Q24의 198행은 유지하며, 순수 legacy 금액·정산·분할 속성 시험은 v1을 계속 검증한다. 이 실패 실행을 정상본 PASS로 합산하지 않는다. FIX6의 우선 처리가 끝난 뒤 정상 선택과 분리 사본 전체를 다시 실행한다.

## 12. 234dd31 기준 구현·직접 검증 이력

증거 루트 **R=`C:/Users/gangd/AppData/Local/Temp/recoryn-g06-9xj3t7ap`**, 기준 commit **234dd31a32426367268b3c8710a11ca82a010e6f**다. R/isolated는 그 commit을 git archive로 풀고 승인된 G06 29파일만 복사했다. G04 제품·시험 변경은 포함하지 않았다. `case-id-audit.json`은 비소유 추적 파일 차이 0과 작업 트리/사본의 G06 LF hash 일치를 확인한다. 최종 제출 hash는 아래 파일 표와 제출 창에 고정한다. `git add/commit/push`를 실행하지 않았다.

### 12.1 실제 동작과 구현 경계

- `security/cost.py:96`의 필수 CostRequest는 실제 본문 bytes·닫힌 의미 header·provider/endpoint/model/API/기능을 받는다. CostPolicy·CostQuote와 정수 올림 계산은 `:164`, `:504`, `:524`에 있다. 호출자가 알려 준 byte/token 수나 cap을 VERIFIED 증거로 승격하지 않는다. ledger 저장에는 본문 hash·길이·정책/quote 메타데이터만 넣고 본문·인증 header를 넣지 않는다.
- `security/cost_catalog.py`는 canonical digest를 고정한 **빈 catalog**이며 실행 중 네트워크나 임의 파일을 읽지 않는다. 실제 가격 항목은 추가하지 않았다. 합성 text/audio/정액 profile은 시험에서만 주입하며 실제 가격·모델 과금 증거로 집계하지 않는다. 실제 가격이 없는 원격 제공업체는 strict에서 사전 차단되고, 일반 모드는 명시 위험 확인 후 USER_CAP으로만 표시한다.
- `security/ledger.py`의 네 additive 표와 witness v2는 통화·기간·가격 기준/만료·quote 종류와 노출액을 보존한다. v1 witness 검증을 먼저 하며 기존 DB를 재서명하지 않는다. v1 노출은 LEGACY_UNSCOPED이고 명시 승계 전 새 지출을 거부한다. 구버전 앱·표 누락·rollback·DB/witness 게시 중단은 안전 차단한다. 같은 provider의 다른 통화/기간 RESERVED·UNKNOWN도 새 요청을 보류한다. G-P09 인계는 §4의 네 표·witness v2·v1 전환 상태 그대로다.
- `security/ledger.py:752`의 reserve_quote는 신뢰한 고정 catalog로 quote를 다시 계산해 일치시킨다. `:829`의 validate_dispatch와 Gateway는 연결 전·매 write 전에 실제 본문/문맥·계정 정책·만료·시계를 다시 확인한다. 첫 write 전에 UNKNOWN을 영속화하며 철회·timeout·부분 실패로 UNKNOWN을 해제하지 않는다. `:939`의 usage 이벤트와 수동 정산은 중복·역순·상충을 검사한다. 공급자 응답 usage의 자동 연결(F-COST02)은 승인대로 S2 후속이다.
- `ui/privacy.py:524`의 snapshot과 `:548`의 prepare_execution은 비용 정책을 동의 binding과 함께 고정한다. worker는 위젯을 재조회하지 않는다. UI에 모드·통화·명시 UTC 기간·검증 U/사용자 C·가격 기준/만료·USER_CAP·미정산 상태를 표시하며 일반 모드의 확인 기본값은 No다. 비용 값은 결과 config_key에서 제외한다. `app/ai.py:156`의 wrapper는 새 DTO를 그대로 전달하고 원격 intent를 Gateway보다 먼저 기록한다. `ui/ai_bridge.py`의 기존 context 복사는 이를 보존하므로 이 파일을 변경할 필요가 없었다.

실제 가격·청구액·환율·실모델·실제 장치·유료/계정 호출은 검증하지 않았다. 기본 catalog가 비어 strict가 모든 유료 원격을 막는 것은 C00이 수용한 이번 동작이다. 일반 USER_CAP은 실제 청구 상한을 보증하지 않는다.

### 12.2 경우의 수·시간 게이트

최종 새 네 파일을 같은 사본에서 함께 실행해 **4860 PASS / 99.68초**, failure/error/skip/경고 0을 직접 확인했다(`new-final2.xml/log`). testcase 시간 합은 **97.412초**로 C00이 승인한 이 PC의 **120초** 예산을 통과했다. 앞선 4857+3 선택 실행과 중복 합산하지 않는다.

| 파일 | node | testcase 시간 합(초) |
| --- | ---: | ---: |
| tests/unit/test_cost_cap.py | 217 | 6.396 |
| tests/property/test_cost_cap_case_space.py | 3770 | 55.679 |
| tests/integration/test_cost_cap.py | 822 | 30.311 |
| tests/ui/test_cost_cap_ui.py | 51 | 5.026 |

의미 행은 TEXT960·STATE2801·BALANCE24·EVENTS70·NUMERIC120·AUDIO360·BIND256·PRICE-TIME60·ORDER36·PERIOD80·DB16·LOCAL3·UI48 = **4834**다. independent 산식에서 생성한 ID 집합과 XML의 실제 ID를 비교해 **누락0·중복0·추가0**이며 node 중복도 0이다. auxiliary22·manifest4는 별도다. 기존 Q24는 전송 fixture만 적응한 뒤 **200 PASS / 15.00초**였다(`q24-final.xml/log`); 의미 198행·manifest·Hypothesis 속성 구조를 줄이지 않았다.

원 반례 `G06-AUX-P1-0~4`는 실제 Gateway와 fake transport에서 cap2819/큰 입력 차단·cap2820 정확 경계 허용·strict unknown/expired 차단·일반 USER_CAP13을 대조한다. 실제 제공업체 wire와 빈 catalog 2행은 strict의 COST_PRICE_UNKNOWN·일반 USER_CAP 구별을 추가로 확인한다. 실제 전송 대신 메모리 transport의 open/write를 관측했다.

### 12.3 mutation

R/mutations의 별도 사본마다 **pyproject + src + tests + scripts + packaging**을 함께 복사했다. 실제 cost/ledger import가 그 사본 src임을 실행 전에 확인했다. 정상 목표 선택은 **26 PASS / 3.63초**였다. 아래 명명한 결함 28개는 각각 독립 사본에서 실행해 **28/28 KILLED**, survived/invalid/import 오류/timeout 0이다. 원본 제품 파일은 바꾸지 않았다. 전체 프로젝트의 mutation coverage나 단일 연산자 변이 28개라고 부르지 않는다.

M14는 같은 본문 fingerprint 계약을 중복 확인하는 세 지점을 함께 우회한 한 변이다. M16은 정책 version 분기, M26은 v2 요청 hash 누락을 선택했다. M11은 가격 불일치가 아닌 통화 계정 identity로 검출하고, M15는 TEXT의 실제 출력 필드로 검출했다. M24는 자동 승계 뒤 COST_LEGACY_UNSCOPED 대신 BUDGET_EXCEEDED가 되어 명시 승계 전 거부 코드 assertion이 실패했다. 이 결과를 ‘원격 write까지 성공’했다고 확대하지 않는다. diff·원본/변이 hash·명령·실패 node·실패 상세는 `run_mutations.py`, `mutations/results.json`, `M01~M28.diff`, 각 evidence XML/log에 있다.

| 변이 | 실제 검출 case/시험 | 관측 |
| --- | --- | --- |
| M01 | TEXT-0408 | strict unknown 거부 누락 |
| M02 | PRICE-TIME-036 | 만료 동일 시각 거부 누락 |
| M03 | TEXT-0089 | 미검증 상한 거부 누락 |
| M04 | TEXT-0124 | 출력 profile 상한 초과 수락 |
| M05 | 손계산 시험 | 올림 누락으로 U 불일치 |
| M06 | 손계산 시험 | cap을 U로 반환 |
| M07 | 손계산 시험 | 정확 cap을 잘못 거부 |
| M08 | AUDIO-100 | 음성 1001ms 비용 불일치 |
| M09 | BALANCE-012 | UNKNOWN 노출 누락 |
| M10 | BALANCE-002 | 정확 budget 경계 거부 |
| M11 | 통화 identity 보강 | USD/EUR account ID 충돌 |
| M12 | PERIOD-024 | 기간 끝 시각 수락 |
| M13 | PERIOD-012 | 이전 UNKNOWN 무시 |
| M14 | BIND-008 | 다른 본문 수락 |
| M15 | TEXT-0108 | 실제 출력 상한을 읽지 않음 |
| M16 | BIND-001 | 옛 정책 version 수락 |
| M17 | PRICE-TIME-044 | 후속 write 만료 검사 누락 |
| M18 | ORDER-035 | UNKNOWN 대신 RESERVED 유지 |
| M19 | STATE-0067 | UNKNOWN release 수락 |
| M20 | EVENTS-030 | final 뒤 UNKNOWN 이중 계상 |
| M21 | EVENTS-044 | 같은 final 이중 정산 |
| M22 | EVENTS-020 | 역순 event 수락 |
| M23 | STATE-0012 | provisional을 final로 계상 |
| M24 | DB-03 | 명시 승계 전 거부 코드 불일치 |
| M25 | DB-12 | 표 누락을 새 witness로 덮음 |
| M26 | AUX-WITNESS-request | v1 revision 유지한 quote 변조 미검출 |
| M27 | UI-006 | worker가 현재 UI 정책을 읽어 snapshot 불일치 |
| M28 | PRICE-TIME-018 | clock 역행 수락 |

### 12.4 전체 회귀·정적 검사

R/isolated에서 최종 전체 오프라인 회귀 **13979 PASS / 397.51초**, failure/error/skip/경고 0이다(`full2.xml/log`). 새 의미 4834행을 포함한 신규 파일 4860node와 기존 9119node를 함께 실행했다. 첫 실행의 34개 실패는 정상 PASS에 합산하지 않았다. 실제 import 경로·소유 파일 hash·비소유 추적 파일 차이 0은 `audit.py`와 `final-audit.json`으로 다시 대조했다.

명령은 `D:/project/Recoryn/.venv/Scripts/python.exe -B -m pytest -m "not hardware and not live_provider" -q -ra -p no:cacheprovider -W error::ResourceWarning -W error::pytest.PytestUnraisableExceptionWarning --basetemp R/full2-bt --junitxml R/full2.xml --tb=short`이며 cwd는 R/isolated다. PYTHONPATH는 그 사본 src, Qt는 offscreen, bytecode/HF/transformers/telemetry는 억제했다. 실제 장치·모델·유료/계정/vault 쓰기·네트워크·설치를 하지 않았다.

| 전체 실행에 포함된 범위 | 직접 확인한 node |
| --- | ---: |
| tests/ui 전체 | 392 |
| tests/ui/test_live_ui.py | 10 |
| tests/ui/test_gpu_runtime_ui.py | 4 |
| tests/ui/test_privacy_ui.py | 18 |
| tests/ui/test_consent_scope_ui.py | 292 |
| tests/unit/test_consent_scope.py | 112 |
| tests/property/test_consent_scope_case_space.py | 5 |
| tests/integration/test_consent_scope.py | 685 |
| tests/unit/test_content.py | 103 |
| tests/integration/test_selection_version_cas.py | 203 |
| tests/property/test_security_case_space.py | 200 |

기존 security·Gateway·provider 계약과 G-P02/G-P02b/G-P03 회귀도 같은 전체 실행에 포함됐다. UI 부분집합을 전체 개수에 또 더하지 않는다. ResourceWarning·unraisable을 오류로 처리한 명령에서 PASS였으며, 전체 line/branch coverage를 별도 측정한 것으로 주장하지 않는다.

`ruff check --no-cache <승인 Python28파일>`·`ruff format --check --no-cache <동일28파일>` PASS, `python -m mypy src/recoryn scripts packaging`은 R/isolated의 **85 source files PASS**다. mypy cache도 TEMP에 뒀다. 초기 mypy의 지역 변수 타입 오류 2건은 수정한 뒤 통과했고 최종 결과를 `mypy-final.log`에 보존했다. 최종 mutation의 제품 source hash는 제출 원본과 계속 같다.

### 12.5 인계·남은 검증

이번 승인 범위의 미해결 구현·실패 시험·살아남은 변이는 없다. 작성자 검증 결과이며 C00 지정자의 독립 검토·통합 승인은 남아 있다. 실가격 최초 항목은 공식 원문·SHA·취득일 고정과 별도 독립 검토를 거치는 외부 게이트다. 공급자 usage 자동 연결은 F-COST02/S2, 정본 migration·backup의 네 표/witness v2/v1 전환 상태는 G-P09, COST_* 및 CONSENT_POLICY_CHANGED의 BLOCKED 사유 분류는 G-P07에 인계한다. 이번에는 CONSENT_POLICY_CHANGED의 기존 provider 오류 분류를 고치지 않았다.

### 12.6 최종 파일·증거 hash

승인29파일 중 **신규7·변경19 = 실제 변경26파일**, 동일3파일이다. `ui/ai_bridge.py`는 기존 실행 문맥 복사로 새 factory를 보존하며, unit security·AI independent는 기존 oracle을 변경하지 않고 회귀 실행했다. 아래 Python28파일과 이 문서의 제출 창 hash가 정본이다. 문서 자체의 hash는 자기 참조를 피하여 최종 창·R/implementation-files.json에 기록한다. 작업 트리와 사본의 Python LF hash가 일치하고, 사본의 나머지 추적 파일은 기준 commit 그대로다.

| 파일 | 기준 대비 | SHA256(LF, CR 제거) |
| --- | --- | --- |
| src/recoryn/security/cost.py | 신규 | `84d4f651df97b2038e634fbf345140766dd1c8c7ba48f0d54dc785d79d59b1b3` |
| src/recoryn/security/cost_catalog.py | 신규 | `40f83a75a1720e4dd991b4c90219d6e93e63f3a8c8f8cd2cd9f48c88995fa0d4` |
| src/recoryn/security/ledger.py | 변경 | `9f0898533034f9cc8b3127c917c64799f48c4ef72b25fad7d2b2a8872d3f23d9` |
| src/recoryn/security/gateway.py | 변경 | `0b8105670e1471592018121d8a30d6f94d64a684ae7efeb6cfd0d265b76c6ccc` |
| src/recoryn/security/__init__.py | 변경 | `43d30b6fb9eb39c002ffecae9169bbfcaabfd381e33c208adc21b8c9bd51caa5` |
| src/recoryn/providers/contracts.py | 변경 | `82d362917540e7035c749787137064cc5b8360c770cec5a10b01aff94a3d039a` |
| src/recoryn/providers/_common.py | 변경 | `8f31bb3abb6a34f150f25dd83b2a0dd759681435fae55d8d2cc0ccd90a054867` |
| src/recoryn/transcription/adapters.py | 변경 | `7428d6a3eebcfba6f9ccc90e0abd19509651d903c6f3128fd1963777c4ec266c` |
| src/recoryn/summarization/adapters.py | 변경 | `ee244773642a73e3d30ba64712deea158185f08ad6d08344ef3aff148434d240` |
| src/recoryn/app/ai.py | 변경 | `dd6291ce65292230e4deaa8516f9356e09c6d1ff6aca71049dcd1721984d03c5` |
| src/recoryn/ui/privacy.py | 변경 | `111f9276226bedb6408815ff223bd520af925c399314a71804ee64d11a30a6e4` |
| src/recoryn/ui/ai_bridge.py | 동일 | `725db065d0eeda327736a262b646d9aa46f7a04779f360d3bd6835afc9ff0a3c` |
| tests/unit/test_cost_cap.py | 신규 | `1c33e4b45e8222cb9e18c0c6c353dca0f3b8f05a8eaa5fa9a40c96bb0b7a9df4` |
| tests/property/test_cost_cap_case_space.py | 신규 | `bba52544f277ddd40fbe25923b1954c904687b5a223436450c8f02909e5cf0d8` |
| tests/integration/test_cost_cap.py | 신규 | `e623a0397820db49507fa5d141f875d81f1f616408bb817a1e0143da83ecdac0` |
| tests/ui/test_cost_cap_ui.py | 신규 | `d1a7409ba476861634f9ea953ec368ee74069b96130043913699fccb64966113` |
| tests/unit/test_security.py | 동일 | `4629c0a0276fbe0d88ec291c9a64d8d60ff5d28e93401c164b4a8a0402714c6a` |
| tests/unit/test_providers.py | 변경 | `eb8b649d564199de0dd7995c430bd38c50c9bfd4e8d5cf646891784c00e039a7` |
| tests/property/test_security_case_space.py | 변경 | `17506104be58ca68fd27ece7ede8092a02422841d459595842a670baf7d9600b` |
| tests/integration/test_gateway.py | 변경 | `97e2470314967c68f03476b56c61e43af51e2d3b70c5ef06945c28458467795d` |
| tests/integration/test_egress_independent.py | 변경 | `cf0043af4653f3eadb761e6ad8ed61dad24458dda063ea1458a7eb02bb8bcaba` |
| tests/integration/test_provider_security_independent.py | 변경 | `7eafb85a8002f184d2b309685cf649fe960318b7516fbde86fa1d3591aa5ec3e` |
| tests/integration/test_publication_independent.py | 변경 | `be0768e291bea77e85a91def58b59d3868854c6873d40d59d3efe177a0a1f046` |
| tests/integration/test_consent_scope.py | 변경 | `7fa7a2646c7042525ccd3451846d9fa9f5da414e57cac2052aaa703e8de496bd` |
| tests/contract/test_provider_contracts.py | 변경 | `0c0dc941ed31b53e5df132838fdc3cc1b79f2c6d9770a0a43e2475af88a5c61c` |
| tests/ui/test_privacy_ui.py | 변경 | `7daa11da328c8899f8f886f35a2f63ea37028d86be0e62253745575710fdf1c9` |
| tests/ui/test_consent_scope_ui.py | 변경 | `fa836e195864248d3bad20e35cf8db303a23f5ada3e7dfcd51c43af4829ebd9e` |
| tests/integration/test_ai_independent.py | 동일 | `b80139e46372426e72429c78a7f72cfe53cc4524617a052c7ca67add04dd6370` |

| 직접 증거(R 기준) | SHA256(LF, CR 제거) |
| --- | --- |
| new-final2.xml | `523232b8d0a0db545143144c3c9cf3a87bedf5a87f186aa0943645f08cd38831` |
| full2.xml | `85641b7a27cfeee3cc2c2e007df8d04e2b43ef3904794cc15b9085ae2515b6fb` |
| q24-final.xml | `b17d0640b2ad7cfbd25b1554aad593e9cfc1bd7f6d176ac9a548107147c6a3f9` |
| mutations/results.json | `fc0083a0226a77eb4ea285b540f72359ad48ac04c277756754f0d609ec8dc26f` |
| case-id-audit.json | `4bbab91507da9b4d1b68f617fbffc4f65677afad2c1faa6bc0c3d7f1ae5338d5` |
| ruff-final.log | `82b3e6a6c090a57601d22943bd23fca9218d1031dbe5a7b754092f9a156b4f18` |
| format-final.log | `2bcbe8e6e763d11737554aa861ef6606aea9d87114a002aa9bd426ec920674cf` |
| mypy-final.log | `8695a1c573afa655b92b1ddd9f4c5906462a39968f31f64c8ae54f732e265b04` |

## 13. G-P04 push 뒤 8e09b62 기준 최종 재검증

C00이 G-P04 commit **8e09b62ad1bb94475b5895e53438dbbe45a8b18d**를 push한 뒤 그 commit을 최종 기준으로 지정했다. 해당 commit의 git archive를 새 OS TEMP에 풀고 **G06 승인29파일만** 복사한다. G-P04 10파일과 G-P05의 library.py·main.py·cli.py·신규 시험5·경우의 수 문서는 G06 쓰기 범위와 교집합이 없음을 대조한다. 작업 트리에서 진행 중인 G-P05 변경은 가져오지 않는다. 사본의 나머지 추적 파일은 전부 8e09b62와 byte 단위로 같아야 한다.

G06 Python28파일은 §12 제출 hash 그대로이며 변경은 이 문서의 기준·결과 기록뿐이다. 새 사본에서 전체 오프라인 회귀를 `-p no:cacheprovider`, 고유 OS TEMP basetemp, offscreen, ResourceWarning·unraisable 오류 처리로 실행한다. 결과·파일 대응·보호 경로 hash·최종 문서 hash를 실행 뒤 기록한다. §12의 13979 PASS를 새 기준 실행 결과로 재사용하지 않는다.

### 13.1 직접 결과와 포함 범위

새 증거 루트 **H=`C:/Users/gangd/AppData/Local/Temp/recoryn-g06-head8e09-y2lex9mg`**다. H/isolated는 8e09b62 archive와 G06 29파일만으로 만들었다. 실제 ledger와 Library import가 H/isolated/src임을 실행 전에 확인했다. 명령·module 경로·exit0·프로세스 시간을 `run-result.json`에, 실제 stdout과 JUnit을 `full.log/xml`에 보존했다.

이 사본에서 **14407 PASS / pytest 680.84초**, failure/error/skip/경고 0이다. 하네스 프로세스 전체 686.596초와 pytest 보고 시간을 구별한다. 기준의 9547node + G06 신규4860node이며 전체 node 중복도 0이다. G06 의미 **4834행 누락0·중복0·추가0**, auxiliary22·manifest4는 별도로 대조했다. §12 실행 숫자를 새 실행에 더하지 않는다.

| 새 기준 전체 실행에 포함된 범위 | node |
| --- | ---: |
| tests/ui 전체 | 423 |
| tests/ui/test_live_ui.py | 10 |
| tests/ui/test_gpu_runtime_ui.py | 4 |
| tests/unit/test_content.py | 103 |
| tests/integration/test_selection_version_cas.py | 203 |
| G04 신규 4파일 합계 | 428 |
| G06 신규 4파일 합계 | 4860 |

G-P02/G-P02b의 기존 unit/property/integration/UI와 security·Gateway·provider 계약 회귀도 모두 포함됐다. G04의 목록7200·확정900·복구900 행은 관리 root 최대 **1.176/15.094/1.833ms**, 관리 ≥50ms 이력은 각각 0이었다. 이는 이 실행의 관측이며 G-P15의 writer seal 유실 문제를 해결했다는 뜻이 아니다.

이 전체 실행 안에서 G06 네 파일의 testcase 시간 합은 unit10.935·property53.081·integration30.224·UI6.877 = **101.117초**였다. §12의 네 파일 단독 실행 99.68초와 서로 다른 측정이며 두 값 모두 승인된 이 PC의 120초 예산 안이다. 실행 순서·동시 부하 전반의 시간 보장은 하지 않는다.

### 13.2 변경 격리·정적 검사·인계

`ownership.json`은 G06/G04/G05 허용 파일 목록과 교집합 0을 기록한다. `protected-head.json`의 **16개 보호 경로**는 사본에서 commit의 hash 또는 부재 상태 그대로다. G-P05의 신규 시험5·문서는 사본에 없고 shared library/main/cli는 작업 트리 대신 8e09b62 판본이다. 최종 감사는 사본의 모든 비소유 추적 파일을 archive와 byte 단위로 비교해 **차이0**을 확인했다. 작업 트리의 G-P05 파일은 수정하지 않았다.

G06 Python28파일은 이전 제출 hash와 전부 같고, 새 기준의 실제 변경은 동일하게 **신규7·변경19·동일3**이다. 28 mutation 대상 제품 source hash도 그대로다. mutation28·ruff/format28 증거는 §12의 동일 판본 결과이며 새 기준에서 mutation을 다시 실행했다고 주장하지 않는다. 새 사본의 `python -m mypy src/recoryn scripts packaging`은 G04의 recovery 모듈을 포함한 **86 source files PASS**다.

H/audit.py·final-audit.json은 전체14407·UI423·G04 428·G06 4860·case ID·보호 경로·소스 hash와 기준 대비 변경 파일을 대조한다. H/implementation-files.json에 최종29파일의 LF hash를 기록한다. Python28파일의 정본 hash는 §12.6 그대로이며, 이 문서의 갱신 hash만 제출 창에서 교체한다. 독립 검토·실가격 최초 항목·usage 자동 연결·G-P09/G-P07 인계 경계는 §12.5 그대로다. 이번 재검증에서 미해결 실패는 없다.

| 새 기준 증거(H 기준) | SHA256(LF, CR 제거) |
| --- | --- |
| full.xml | `029543b128af82f42c2a2072e1eaa671bde2de217a26323d499eec2f9fdc15ac` |
| run-result.json | `28036fd92eb2f62a8c5895e436fc6d1bcc5b5684918f2c53427b413abd551c14` |
| protected-head.json | `6311a83b0584aa5d55b1d2310b4d630986efc0db0f7f47082bfe374d92dacca8` |
| ownership.json | `538fec2abe3dde7f07b3d26aeec310dd5d1acabac674f30300d914e8634cb7fb` |
| mypy.log | `94843c6b8c4b1100515d4ee5b127e274eeaaa4f0e0a33546bc6c163a8e33977e` |

## 14. G06 FIX1 독립 검토 반영 계획(구현 전 고정)

기준 HEAD 29335737b744d430a93dd95aa3d1764c2e3abb7b. 검토 문서 d947a628b51eb5b4a4bb85cbd8e0c30056c9da549d52f6fae11ccd1f2af67dc4의 G06R-01~07을 고친다. 기존 의미 분모 4,834는 축약하지 않는다. 추가 보강은 G06-FIX1 이름의 auxiliary로 별도 수집하며 기존 ID 감사와 분리한다. 제품 수정 전에 다음 입력 분할과 독립 oracle를 고정한다.

- 시계: 정상/재시작 역행/무결성 장애 × 비용 조회/유료 admission/명시 reset/로컬 녹음. 미래 high-water로 다시 열어도 앱·로컬 녹음은 허용, 비용 전송은 COST_CLOCK_INVALID. reset은 기본 No·Esc 취소의 명시 확인과 감사 기록을 요구하며 과거 노출을 지우지 않는다. reset 뒤 동일 제공업체·통화의 모든 기간 확정액을 현재 계정에 보수 합산해 시계 교정으로 지출을 줄일 수 없게 하는 안을 사용한다. 새 audit metadata는 기존 v2 witness의 검증 대상이며 구 v2 전환은 기존 witness 검증 뒤에만 한다. UI 생성 경계 ui/main.py 한 줄 추가 범위는 C00에게 요청 중이다.
- 전송: 실제 OpenAI multipart 5분/10분 WAV·20MiB 요청 × 이력0/1,000이상. quote·본문 digest·wire 파싱은 open 전 한 번, 같은 dispatch의 write는 immutable 본문 identity·누적 byte 상한 및 최신 시각/정책/예약 상태를 검사한다. 변경 없는 write에서 ledger 전체 hash·wire parse·witness fsync·commit을 반복하지 않는다. 최초 dispatch claim·UNKNOWN 전환은 기존 노출 보호를 유지한다. 정상 fake 네트워크는 UNKNOWN 0이며 시간·호출 횟수·write당 추가 비용을 측정한다.
- 단일 원인: 신규 COST_* 15코드 각각의 정확한 코드를 독립 상수로 검사한다. 복합 입력은 우선순위에 따른 명시 허용 집합만 인정한다. 제품에서 발생한 예외 코드를 기대값으로 다시 복사하지 않는다.
- 공개 Gateway: 가격/정책/시계의 첫 write 뒤 변경·ledger 부재·과소 예약 차단·general ack 부재·위조 quote를 주입한다. 다음 write/open0·정확 코드·UNKNOWN 보존을 검증한다. 매 write 연결 제거를 ledger 함수 직접 호출 시험으로 대신하지 않는다.
- 경쟁: v2 같은 계정의 별도 ledger thread/process 예약 경쟁과 같은 예약 중복 dispatch. 승인 금액7/한도10의 승자1·노출7, 중복 open/write0을 독립 SQL·fake transport로 검사한다.
- UI: 과소 예약 blocked 표시·한도 적용 후 유지, 미적용 예산의 안내, 일반 확인의 중복 청구 위험·동의와 별개 문구, 시계 확인/명시 reset. 결과 config_key는 비용·동의 정책 변경으로 바꾸지 않는다.
- catalog: 실제 load_catalog가 fixture wire profile을 선택하지 못하는 음성 시험. 실제 가격·billing profile version·최소 청구량/증분·tier·텍스트 framing·Gemini 음성 혼합 과금은 별도 최초 가격 항목 게이트로 인계한다.

mutation은 기존28과 검토자 R01~R15/A-M17을 TEMP 사본에서 재실행한다. 구조 변경으로 원 패턴이 없어졌으면 같은 방어선을 제거한 등가 변이와 hash·목표 실패 node를 기록한다. 다른 방어가 남아 생존한 변이는 검출로 부풀리지 않는다. 정상본 PASS 후에만 검출을 계산한다. 새4파일 120초 예산·ResourceWarning 오류·UI 전체·G02/G02b/G03 회귀·정적 검사·최종 정확한 사본 전체 회귀를 유지한다. 현재는 계획만 추가했으며 완료 결과가 아니다.

### 14.1 추가 연결·호환·본문 수명 계획

- 시계 reset은 기존 `security_cost_meta_v2`에 additive `clock_reset_audit` JSON 열을 추가해 감사한다(새 표 없음). 기존 v2는 원 witness를 먼저 검증한 뒤 이 열을 추가한다. 실제 reset 이후 witness v2에는 필수 확장 표식 `clock_reset_protocol_version=1`을 둔다. 구 v2의 전체 dictionary 비교가 이 확장을 거부하므로 보수 합산을 모르는 이전 코드로 지출을 우회하지 못한다. G-P09에는 4표·witness v2와 함께 이 열·확장 필수 조건·구 v2 전환 순서를 인계한다. 시계 watermark는 예약 수명/정산/명시 변경 시 영속하고 write마다 fsync하지 않는다. 읽기/송신 중의 더 늦은 관측은 메모리 high-water로 검사하며 crash 뒤 그 미영속 시각까지 증명했다고 주장하지 않는다.
- 저장 본문 재사용은 소유자의 `CostRequest` 약한 참조다. quote 후 버림/예약 후 버림/실제 Run이 소유한 채 quote→reserve→dispatch를 진행하는 3개 대표를 추가 보강한다. 앞의 2행은 weakref 소멸과 예산 노출 불변, Run 1행은 해석1회·정상 송신·종료 후 약한 참조 소멸을 oracle로 한다. 모든 수명×모든 phase의 직적 전수라 부르지 않는다. 캐시 miss나 재시작이면 입장 검증을 다시 수행하며 per-write 경로에서 본문을 재해석하지 않는다. `_Dispatch`의 활성 본문 참조는 Gateway finally에서 해제한다. 금융 이력에 본문을 저장하지 않는다.
- USER_CAP/strict의 최종 방어는 정상 발급 경로에서 앞선 quote 검사가 가려 검토자 R08이 처음 생존했다. 소유 TEMP DB에서 선행 검증 누락을 대표하는 유효 witness·불일치 USER_CAP/strict 행을 구성한 별도 Gateway 음성 행을 추가한다. 기대는 구체 COST_QUOTE_MISMATCH·open/write0·노출 보존이다. 이는 외부 사용자가 witness를 위조할 수 있다는 보장이 아니라 독립 방어선 시험이다.
- write 재검사는 첫 송신 뒤 legacy 노출 생성 또는 다른 기간으로 명시 승계된 미정산도 관측한다. revision 변경 시에만 전체 무결성과 노출 요약을 재인증하고, 변경 없는 write는 고정 본문 identity·누적 byte 상한·시계/기간·예약 상태·정책/차단 및 인증된 노출 요약을 검사한다. 한도0의 명시 적용과 계정 부재를 UI에서 구별한다.
- 의미 분모 4,834는 그대로다. 새 보강은 auxiliary로 별도 집계한다. UI/main.py 연결 승인은 아직 대기 중이므로 해당 무결성 시작 시험을 제외한 결과를 전체 완료로 표현하지 않는다.

write 경계의 누적 byte 입력은 필수 사실이다. 추가 음성 대표는 None/bool/음수/예약 byte 길이+1의 4행이며 각각 COST_REQUEST_INVALID/동일/동일/COST_PLAN_UNDERESTIMATED와 open 후 실제 write0·기존 예약 노출 불변을 검사한다. open 단계는 byte 누적값이 없고, 기존 직접 phase=write 시험은 실제 fake 첫/다음 handoff의 5/9byte를 명시한다. None을 상한 검사 생략 fallback으로 사용하지 않는다.

## 15. G06 FIX1 구현·검증 기록(연결 범위 승인 대기)

기준 HEAD `29335737b744d430a93dd95aa3d1764c2e3abb7b`. 증거 루트 `R=C:/Users/gangd/AppData/Local/Temp/recoryn-g06-fix1-pzqh5nmn`. R/isolated는 이 HEAD의 git archive에 승인 29파일만 덧씌운 사본이다. G-P05·G-P15 파일을 복사하거나 수정하지 않았다. LF 비교의 실제 차이는 여전히 **26파일**, 동일한 승인 파일3개는 ui/ai_bridge.py·tests/unit/test_security.py·tests/integration/test_ai_independent.py다. archive와 범위 밖 파일의 바이트 차이0은 R/scope-audit.json으로 확인했다.

**현재 완료 아님:** 무결성 오류를 MainWindow 생성에서 격리하는 `CostLedger.open_for_ui`는 구현·시험했으나, MainWindow의 CostLedger 생성 호출 한 줄 연결은 승인29파일 밖이므로 C00에게 범위·수정 시점 추가를 요청하고 대기 중이다. 작업 트리 ui/main.py는 G-P05 소유이며 수정하지 않았다. 따라서 새 `test_main_window_cost_failure_never_blocks_the_recording_controls[integrity]` 1건을 제외한 결과를 정상본 전체 PASS로 부르지 않는다.

### 15.1 구현과 위험·복구 의미

| 지적 | 반영 |
| --- | --- |
| G06R-01 | 기존 v2 열기는 시계 역행만으로 생성자를 실패시키지 않는다. 비용 경로의 `_now`는 COST_CLOCK_INVALID를 유지한다. availability는 비용 상태를 반환하고, open_for_ui는 무결성/열기 오류를 비용 전용 불능 객체로 격리한다(실제 MainWindow 연결은 위 승인 대기). privacy는 ‘시계 확인 필요’와 기본 No 확인의 명시 reset을 제공하며, 로컬 제공업체 선택 상태에서도 시계 동작을 사용할 수 있다 |
| reset의 지출 보존 | 예약·UNKNOWN·확정/usage 행은 지우지 않는다. clock_reset_audit를 witness 안에 넣고, reset 뒤 동일 제공업체·통화의 **전체 기간 확정액**을 현재 예산에 보수 합산한다. 과거 정상 기간도 포함할 수 있으므로 새 기간 가용액이 통상보다 작을 수 있다. 기존 요청별 신뢰할 수 있는 과금 시각 열이 없어 과소 산정 대신 이 보수 정책을 선택했고 확인 창에 범위를 밝힌다. UI 한도 증액/통화 변경/정산을 자동 수행하지 않는다 |
| G06R-02 | CostRequest는 immutable bytes의 SHA를 1회 계산한다. quote/reserve/open에서 같은 DTO의 검증 결과를 재사용한다. 캐시는 약한 참조이며 실제 Run이 요청 동안 DTO를 소유한다. 캐시 miss/재시작은 open 전에 다시 검증한다. 매 write는 immutable body identity·필수 누적 byte 상한·예약/정책/시계/기간·가격 만료·인증한 노출 요약을 확인한다. 카탈로그는 실행 중 바꾸지 않는 compiled catalog이므로 write마다 재로드/전체 해시하지 않는다 |
| 무결성·동시 변경 | 변경 없는 write의 stamp 비교는 SQLite revision/data_version/schema_version/total_changes와 witness stat이다. stamp가 바뀌면 전체 무결성을 재인증하며, 금융 상태 변경 때 활성 dispatch의 노출 요약을 갱신한다. 다른 기간 미정산·새 legacy 노출도 다음 write를 막는다. SQL 전체 해시·wire 파싱·witness fsync를 매 조각 반복하지 않는다. 기존 dispatch claim·최초 UNKNOWN 전환의 금융 상태 commit은 유지한다 |
| G06R-03 | TEXT/AUDIO/NUMERIC/PRICE-TIME/PERIOD/EVENTS/STATE/UI의 단일 원인 코드를 literal oracle로 검사한다. BIND 복합 행은 실제 설정한 독립 결함의 허용 코드 집합만 인정한다. COST_* 15종의 정확한 기대 코드와 변경 우선순위를 보강했다 |
| G06R-04·05 | 실제 Gateway의 first→next write를 거쳐 만료·정책·시계·과소 예약·legacy·다른 기간 노출을 검사한다. ledger 부재·위조 quote·general ack·재시작 high-water·dispatch claim을 별도 시험한다. v2 thread/process의 승자1·중복 open/write0 확인 |
| G06R-06 | 과소 예약 blocked를 balance에 표시하고 한도 적용이 이를 지우지 않는다. 일반 확인에 중복 청구 위험·동의와 별개를 명시했다. 계정 부재는 BUDGET_REQUIRED와 ‘예산 미적용’으로 안내하며, 실제 적용한 한도0과 구별한다 |
| G06R-07 | production load_catalog는 text-/audio-/opaque-fixture-v1을 canonical digest가 맞아도 거부한다. synthetic 시험은 시험 쪽 loader 주입을 사용한다. 실제 가격 항목은 추가하지 않았다 |

G-P09 추가 인계: 기존 4표와 witness v2에 더해 `security_cost_meta_v2.clock_reset_audit`의 존재/구 v2 인증 후 additive 전환, reset 후 필수 witness 확장 `clock_reset_protocol_version=1`을 버전 목록에 포함해야 한다. 확장 전 구 v2 코드는 reset 뒤 witness를 거부해야 한다. R/older-reader-clock-check의 직접 실행에서 수정 전 G06 코드(LF SHA `9f0898533034f9cc8b3127c917c64799f48c4ef72b25fad7d2b2a8872d3f23d9`)는 LEDGER_ROLLBACK_DETECTED, 새 코드는 READY였고 원문·금액을 재서명해 살리지 않았다. 비용 시각 불확실성을 복구한 경우의 보수 합산 규칙을 모르는 앱으로 돌아가 지출을 줄이지 못하게 한다.

실가격 최초 항목 후속 게이트는 billing profile version·최소 청구량/증분·tier·텍스트 framing 상한·Gemini 음성/텍스트/출력 혼합 과금을 표현하고 공식 원문/SHA/취득일·독립 검토를 고정해야 한다. 이번 빈 카탈로그와 USER_CAP을 그 검증 완료로 집계하지 않는다. 자동 usage 연결 F-COST02는 승인된 S2 후속 그대로다.

### 15.2 현재 직접 실행 결과

- 최종 현재 29파일 사본의 신규4파일: **4,907 PASS·1 deselected·skip/실패/경고0, 109.99초**. 제외는 위 MainWindow integrity 1건뿐이다. testcase 시간 합 **107.477초**(unit6.632 / property59.041 / integration33.942 / UI7.862)로 120초 예산 안이다. 제외까지 포함한 완료 게이트는 아직 닫지 않았다. R/four-final.xml, four-audit.json.
- 별도 literal ID 감사: 의미 **4,834 고유**, missing/duplicate/extra0. 위 부분 실행의 non-family73은 auxiliary와 manifest이며 의미 분모에 합치지 않는다. 원 계획 분모를 줄이지 않았다.
- 중간 관련 회귀: UI·security/gateway·G02/G02b·G03 선택 CAS 포함 **1,739 PASS·위 1건 deselected·경고0, 116.25초**(R/regression.xml). 이 뒤 witness 확장·약한 참조·byte 타입 가드를 보강했으므로 최종 전체 회귀와 구별한다.
- 최종 source의 ruff check/format 및 `mypy src/recoryn scripts packaging`: PASS, mypy86 source files. cache와 basetemp는 R 아래다. 실제 장치·네트워크·설치·계정·vault 쓰기 없이 offscreen/offline으로 실행했다.
- R/isolated에서 HEAD2933573+G06 승인 파일만의 전체 오프라인 회귀 진행 중이다. 위 제외1건은 동일하게 명시했으며, 결과가 나오기 전 전체 PASS 숫자를 쓰지 않는다.

### 15.3 반례·성능 직접 재실행

검토자의 스크립트는 R/reviewer-relocated로 복사해 COPY/import 경로만 R/isolated로 옮겼다. 원 스크립트/검토 폴더는 수정하지 않았다. opaque/concurrency의 synthetic profile은 production loader에서 거부되므로 R/reviewer-fixtures에서 **시험 loader 주입만** 추가한 별도 변형이며 실제 가격 표본이 아니다. 각 출력은 이전에 존재하지 않은 R 아래 새 폴더다. 명령·stdout은 R/probes-final.json과 probe-final-*.log에 있다.

| 검토 스크립트·조건 | 직접 결과 |
| --- | --- |
| probe_clock.py | 미래1시간 high-water 뒤 corrected clock 재열기 OPENED, MainWindow CONSTRUCTED. 이 원 반례의 시계 경로는 닫혔지만 별도 무결성 startup 연결은 승인 대기 |
| probe_perf_openai.py, 5분·USER_CAP·이력0/1200 | 본문9,600,441B, 각각147/147 write, 0.14/0.28초, OK. 전체 요청 시간을 write 수로 나눈 값0.98/1.88ms |
| 같은 스크립트, 10분·이력0/1200 | 본문19,200,441B, 293/293 write, 0.24/0.38초, OK. 전체 요청 기준0.81/1.30ms/write |
| probe_perf.py(시험 profile), 20MiB·이력0/1200 | 320/320 write, 0.26/0.39초, OK. ledger UNKNOWN은 정상 handoff 뒤 정산 전 상태이며 REMOTE_OUTCOME_UNKNOWN **실패가 아님** |
| probe_concurrency.py(시험 profile) | thread 승자1·예약7, process 승자1·예약7·exit 전부0, 동일 예약 중복 dispatch는 OK/RESERVATION_NOT_DISPATCHABLE, open1·300,000B 한 번 |

정식 성능 행은 실제 OpenAI 5분/10분 multipart 및 실제 OpenAI JSON 20MiB × 이력0/1200의 6개다. CostQuote wire 해석1회, 요청별 witness2회(dispatch claim·최초 UNKNOWN), 전체 `_verify` 호출 수 상한을 독립 계측하고 모든 조각·원문 bytes 일치를 확인한다. **매 write 비용 검사 평균≤2ms**를 이 PC의 회귀 예산으로 두며 개별 OS 스케줄링 지연의 절대 상한으로 주장하지 않는다. 네트워크 지연0 fake 결과이지 실제 서버/회선 시간 보장이 아니다. 상세 평균·최댓값은 해당 성능 실행 stdout으로 구별한다.

### 15.4 mutation 재확인

최종 source의 R/mutation-evidence4/results.json: 정상 목표129 PASS 뒤 **작성자 M01~M28 28/28**, **검토자 R01~R15 15/15**, **실제 Gateway 연결 제거 A-M17 1/1**, 합계44/44 목표 assertion 검출·survived/invalid0. 매 변이에서 source/mutant LF hash·명령·JUnit 실패 node·diff를 보존했고 원본은 TEMP 사본에서만 복원했다. 실제 import는 R/mutation-copy4/src다.

초기 재실행에서 R08은 1,369개 관련 합법 요청 대표에서 생존했다(선행 quote/reserve 검증이 strict USER_CAP 발급을 막음). 새 유효 witness/비정상 저장 행의 공개 Gateway 음성 시험으로 마지막 방어를 관측해 재실행에서 검출했다. 이 이력을 숨기거나 처음부터 검출됐다고 고치지 않는다. R03은 첫 write 전 `_write` 바깥 barrier로 경쟁 창을 열어 open claim을 검사했고, R09는 독립 BUDGET_SCOPE_MISMATCH, R10은 동일 version 한도 변경 거부를 고정했다. R11은 1000→2000 상태 commit 뒤1500 재시작에서 실제 전송이 차단되는지 검증한다.

본문 재사용 보강 변이2개도 정상본 목표 PASS 뒤 검출했다(R/cache-mutations.json). 강한 참조로 되돌리면 원문 소유자 소멸 oracle가, Run의 DTO 소유자를 Gateway 전에 버리면 해석1회 oracle가 실패한다. 금융 노출은 이 메모리 정리로 release하지 않는다.

### 15.5 현재 source·test LF SHA-256

아래는 현재 승인된 Python28파일이며 문서 자체 hash는 이 창에 별도 보고한다. UI/main.py 추가 연결은 이 표에 들어 있지 않다.

| 파일 | SHA-256(LF) |
| --- | --- |
| `src/recoryn/security/cost.py` | `5121330e3cec65c32646c25b0e7d2ef2a1acb3bb71213466c3ba87b85b46b9f6` |
| `src/recoryn/security/cost_catalog.py` | `2273ed62714bc8ee79c1e6968e54549a63d15daf214e675b97aff6bbaddb050a` |
| `src/recoryn/security/ledger.py` | `374d07dd49876707a84e27e3b0547f0b23dc1430425fda6aa8f367151876e961` |
| `src/recoryn/security/gateway.py` | `02a345bc98a512a77d2ebf41c457dbe1e865f1643db7968427b92a86ca7795ca` |
| `src/recoryn/security/__init__.py` | `43d30b6fb9eb39c002ffecae9169bbfcaabfd381e33c208adc21b8c9bd51caa5` |
| `src/recoryn/providers/contracts.py` | `82d362917540e7035c749787137064cc5b8360c770cec5a10b01aff94a3d039a` |
| `src/recoryn/providers/_common.py` | `310a2f958a1745a69e320030e287ab791795965ad668c9f21fbdd3091c4e363b` |
| `src/recoryn/transcription/adapters.py` | `7428d6a3eebcfba6f9ccc90e0abd19509651d903c6f3128fd1963777c4ec266c` |
| `src/recoryn/summarization/adapters.py` | `ee244773642a73e3d30ba64712deea158185f08ad6d08344ef3aff148434d240` |
| `src/recoryn/app/ai.py` | `dd6291ce65292230e4deaa8516f9356e09c6d1ff6aca71049dcd1721984d03c5` |
| `src/recoryn/ui/privacy.py` | `474588f59ff676c1ae85136bbda95cfa4238aac8cfba333bf06eaee3d6fe007f` |
| `src/recoryn/ui/ai_bridge.py` | `725db065d0eeda327736a262b646d9aa46f7a04779f360d3bd6835afc9ff0a3c` |
| `tests/unit/test_cost_cap.py` | `a57b076e44ec68a398f01af44928c9b69363b0dda04bf0a3d649807ca70a6715` |
| `tests/property/test_cost_cap_case_space.py` | `4e34b0bccf824404ee08ad73691a22ae1d9008e2f8565aa36aa2e287ddf80284` |
| `tests/integration/test_cost_cap.py` | `85e71c4601c75e1bd8e6402c2a6e7e72177059de3e296ada8b8c8dc09979a875` |
| `tests/ui/test_cost_cap_ui.py` | `32a117aa9cf3e1f1b21685584ddbdf7defff117e69a6c2a9b5fa12fe5aeeca22` |
| `tests/unit/test_security.py` | `4629c0a0276fbe0d88ec291c9a64d8d60ff5d28e93401c164b4a8a0402714c6a` |
| `tests/unit/test_providers.py` | `eb8b649d564199de0dd7995c430bd38c50c9bfd4e8d5cf646891784c00e039a7` |
| `tests/property/test_security_case_space.py` | `17506104be58ca68fd27ece7ede8092a02422841d459595842a670baf7d9600b` |
| `tests/integration/test_gateway.py` | `97e2470314967c68f03476b56c61e43af51e2d3b70c5ef06945c28458467795d` |
| `tests/integration/test_egress_independent.py` | `cf0043af4653f3eadb761e6ad8ed61dad24458dda063ea1458a7eb02bb8bcaba` |
| `tests/integration/test_provider_security_independent.py` | `7eafb85a8002f184d2b309685cf649fe960318b7516fbde86fa1d3591aa5ec3e` |
| `tests/integration/test_publication_independent.py` | `be0768e291bea77e85a91def58b59d3868854c6873d40d59d3efe177a0a1f046` |
| `tests/integration/test_consent_scope.py` | `7fa7a2646c7042525ccd3451846d9fa9f5da414e57cac2052aaa703e8de496bd` |
| `tests/contract/test_provider_contracts.py` | `0c0dc941ed31b53e5df132838fdc3cc1b79f2c6d9770a0a43e2475af88a5c61c` |
| `tests/ui/test_privacy_ui.py` | `7daa11da328c8899f8f886f35a2f63ea37028d86be0e62253745575710fdf1c9` |
| `tests/ui/test_consent_scope_ui.py` | `fa836e195864248d3bad20e35cf8db303a23f5ada3e7dfcd51c43af4829ebd9e` |
| `tests/integration/test_ai_independent.py` | `b80139e46372426e72429c78a7f72cfe53cc4524617a052c7ca67add04dd6370` |

### 15.6 추가 성능 실측과 범위 추가 후보

동일 최종 source에서 성능 6행을 stdout 포함 별도로 실행: **6 PASS·840 deselected·경고0, 6.40초**. R/perf-final-values.xml 및 도구 stdout에서 전사한 R/perf-final-values.json(원문 로그 파일과 구별)에 보존했다.

| 요청 | 이력 | 전체 요청 시간(s) | write 비용 평균/최대(ms) |
| --- | ---: | ---: | ---: |
| OpenAI STT 5분 | 0 | 0.1497 | 0.1560 / 0.3919 |
| OpenAI STT 10분 | 0 | 0.2893 | 0.1773 / 0.4252 |
| OpenAI JSON 20MiB | 0 | 0.3549 | 0.2084 / 0.5433 |
| OpenAI STT 5분 | 1200 | 0.3928 | 0.2225 / 0.5137 |
| OpenAI STT 10분 | 1200 | 0.5589 | 0.2371 / 0.3938 |
| OpenAI JSON 20MiB | 1200 | 0.5998 | 0.2406 / 0.5408 |

모든 행에서 wire 해석1·witness2, body 전체 전달·정상 응답을 확인했다. 이 실행은 네트워크0 fake와 합성 오디오이며 실가격/실제 오디오 장치/실서버 검증이 아니다. multipart framing이 검토자 스크립트와 달라 정식 성능 본문은 9,600,273B·19,200,273B이며 위 §15.3 스크립트 본문 크기와 섞지 않는다.

범위 승인 요청의 구체적 변경은 MainWindow의 `self.ledger = CostLedger(...)` 한 줄을 `CostLedger.open_for_ui(...)`로 바꾸는 것이다. R/main-ui-scope-request.patch(LF SHA `845f63d509f4795f95650c49050f2fe5834506506e5bf3d998e3f577fe3ea0a9`)에 고정했다. 제품 작업 트리·R/isolated에는 이 변경을 적용하지 않았다. **별도 TEMP 후보 R/main-link-preview에서만** 적용해 시계·무결성 MainWindow 두 행 **2 PASS·54 deselected·경고0, 1.32초**를 확인했다(R/link-preview-venv.xml). MainWindow 생성·녹음 버튼 활성·비용 차단 표시를 확인하며 실제 장치는 열지 않는다. 이 후보 실행을 승인 범위 정상본 PASS로 집계하지 않는다. 최초 실행은 시스템 Python을 잘못 골라 PySide6 미설치 수집 오류였고, 저장소 .venv Python으로 다시 실행한 위 결과와 구별한다.

### 15.7 전체 회귀 종료·승인 대기 상태

HEAD2933573+G06 승인 파일만인 R/isolated의 전체 오프라인 실행이 **14,454 PASS·1 deselected·skip/실패/경고0, 886.48초**로 종료했다(명령 exit0, R/full.xml). `-B -p no:cacheprovider -W error::ResourceWarning -W error::pytest.PytestUnraisableExceptionWarning`, offscreen, R/bt-full을 사용했다. tests/ui 전체와 G02/G02b/G03 관련 시험을 수집하되 MainWindow integrity 1건만 명시적으로 제외했다. 해당 후보 시험2건의 별도 PASS를 여기에 더해 ‘전체 PASS’로 합산하지 않는다.

R/final-partial-audit.json: 시험한 source와 현재 승인 Python28파일의 LF 차이0, archive와 사본 범위 밖 파일의 바이트 차이0, 실제 변경26·승인 목록 중 동일3이다. 이 문서의 결과 기록은 시험 종료 뒤 추가했으며 제품 source 변경은 없다. §15.5 source/test hash는 그대로 유효하다.

현재 G06 FIX1_READY로 보고하지 않는다. R01의 MainWindow 무결성 격리 호출 한 줄을 추가하는 범위 승인이 남았으며, 승인 뒤 제품 연결·제외 없는 신규4파일 시간 게이트·최종 회귀를 닫아야 한다. G-P05 작업 트리 ui/main.py는 이 작업에서 수정하지 않았다.

## 16. G06 FIX1 연결 승인 뒤 최종 검증(HEAD6072ef1)

### 16.1 기준·범위·변경

C00이 G-P05(133b010)·G-P05b(6072ef1) push 뒤 ui/main.py의 한 줄 연결을 추가 승인했다. 기준은 **6072ef1dfbb5c69490812ca1b103e248dbf78743**으로 바꿨다. 기존 승인29파일+ui/main.py의 허용30파일 중 실제 변경은 **27파일**이다. 동일3파일은 ai_bridge.py·tests/unit/test_security.py·tests/integration/test_ai_independent.py다.

MainWindow의 self.ledger = CostLedger(library.root / "security.sqlite")를 CostLedger.open_for_ui(...)로 바꿨다. import 변경은 필요하지 않았다. HEAD 대비 **+1/−1**이고 G-P05의 삭제 대기·경고 우선·worker 목록 동작은 바꾸지 않았다. 다른 작업자가 쓰는 storage/chunks.py·app/recording.py·storage/library.py·storage/_coordination.py·seal 시험은 수정하거나 사본에 덧씌우지 않았다.

최종 증거 루트 **S=C:/Users/gangd/AppData/Local/Temp/recoryn-g06-fix1-final-378bb9c5aab641f7811fe9e870a378fe**. S/isolated는 git archive HEAD6072ef1에 G06 실제 변경27파일만 덧씌웠다. 최초 scope-audit.json에서 범위 밖 바이트 차이0과 제품 source 복사 차이0을 확인했다. MainWindow integrity 행의 기존 제외 조건을 CLI에서 없앴으며 시험 코드는 삭제하거나 축약하지 않았다. §15의 제외1건/승인 대기는 이전 상태의 이력이다.

의미 분모4,834와 독립 oracle는 유지한다. 신규4파일, UI 전체, 최종 전체 오프라인 회귀를 이 사본에서 다시 실행한다. 신규4파일 120초 예산을 그대로 적용한다. 기존 금융 source의 mutation44개와 원문 수명2개는 §15의 실행 이력과 대상 source 해시로 구별한다. 추가 연결의 회귀는 MainWindow clock/integrity 두 행으로 확인하며, MainWindow 호출을 strict 생성자로 되돌리는 TEMP 변이가 integrity 행에 잡히는지도 확인한다.

### 16.2 제외 없는 신규 시험·UI·정적 검사

- 신규4파일 **4,908 PASS·skip/제외/실패/경고0, pytest114.24초·실행기 전체115.31초**(S/four.xml, four.log, four-result.json). 120초 예산 이내다.
- 파일별 node는 unit236·property3770·integration846·UI56. testcase 시간 합111.635초(unit7.579 / property61.524 / integration35.914 / UI6.618). S/four-audit.json의 의미 ID **4,834 고유·missing/extra/duplicate0·pytest node 중복0**. 나머지74는 보강/manifest이며 의미 분모에 합치지 않는다.
- **tests/ui 전체500 PASS·skip/제외/실패/경고0, 71.07초**(S/ui.xml·ui.log). MainWindow clock/integrity 두 행을 포함한다.
- 사본 전체 ruff check PASS, ruff format --check **168파일 PASS**, mypy src/recoryn scripts packaging **86 source files PASS**. 실행 명령과 stdout은 S/ruff-check·ruff-format·mypy의 command.json/log/result.json에 있다. 정적 검사·시험 cache는 TEMP에만 둔다.
- MainWindow 연결을 strict 생성자로 되돌린 추가 TEMP 변이 **1/1 검출**: 정상 source LF SHA 8c92a483b78cbd57377fc28863ff05a8d8df1528c008e8a9d6cd4a5dc3a6649b, mutant SHA 941e9af34a165a75135ed883153e07493d59326ec6e15aabc258853ebc718ae9. integrity node가 LEDGER_ROLLBACK_DETECTED로 실패했다(S/main-mutant-result.json·main-mutant.xml·main-mutant.log). 정상 두 행 PASS는 S/four.xml과 구별한다.
- 금융 source·원문 수명 대상의 코드 바이트는 §15의 최종 검증본과 같고, mutation44/44+수명2/2의 이전 실행을 이번 HEAD에서 재실행한 것으로 바꾸어 쓰지 않는다. 추가 MainWindow 연결 변이는 이번 HEAD 사본에서 직접 실행했다.

이제 동일한 사본에서 제외 조건 없이 최종 전체 오프라인 회귀를 실행한다. 결과와 최종27파일 해시는 종료 뒤 아래에 기록한다.

### 16.3 새 기준의 전송 비용 실측

S/perf.log·perf.xml·perf-values.json: **6 PASS·840 deselected·실패/경고0, 4.82초**. 같은 HEAD 사본에서 실제 OpenAI 형식의 합성 WAV/JSON과 네트워크 지연0 fake를 사용했다. 이 시험만 선택한 실행의 deselected840은 전체 실행의 제외가 아니다.

| 요청 | 이력 | 전체 요청(s) | write 검사 평균/최대(ms) |
| --- | ---: | ---: | ---: |
| STT 5분 | 0 | 0.1528 | 0.1607 / 0.3393 |
| STT 10분 | 0 | 0.2597 | 0.1514 / 0.4642 |
| JSON 20MiB | 0 | 0.2793 | 0.1540 / 0.4728 |
| STT 5분 | 1200 | 0.2759 | 0.1568 / 0.3841 |
| STT 10분 | 1200 | 0.4506 | 0.1891 / 0.5273 |
| JSON 20MiB | 1200 | 0.4924 | 0.1888 / 0.6235 |

모든 행에서 wire 파싱1회·witness2회였으며, 누적 본문이 정확히 전송되고 REMOTE_OUTCOME_UNKNOWN 실패가 없었다. 각 요청 write 수는 147/293/320이다. 이력1200의 평균0.1568~0.1891ms는 평균≤2ms 예산 안이다. 개별 OS 지연의 절대 상한이나 실제 회선·가격·서비스 호환성을 보장하는 수치는 아니다. 실가격 catalog는 빈 상태를 유지했다.

### 16.4 최종 전체 오프라인 회귀·범위 감사

S/isolated의 **HEAD6072ef1+G06 실제 변경27파일만**으로 전체 오프라인 **14,850 PASS·skip/제외/실패/경고0, pytest886.23초·실행기891.94초**(S/full.xml·full.log·full-result.json, exit0). MainWindow integrity 제외 조건은 없다. 테스트는 -B·-p no:cacheprovider·offscreen 및 ResourceWarning/PytestUnraisableExceptionWarning 오류 승격으로 실행하고 basetemp를 S/bt-full로 고정했다. 네트워크·설치·모델·실제 장치·계정·vault 쓰기는 실행하지 않았다.

전체 안에서도 UI500, G03 content unit103·selection CAS203, G02 scope unit112·integration685가 PASS했다. 기존 security·gateway·provider 계약·G02b 시험도 전체 수집에 포함됐다. S/full-case-audit.json에서 신규4908·의미4834·누락/추가/중복0을 다시 확인했다.

**시간 측정 별도 보고:** 120초 예산을 확인한 신규4파일 선택 실행은 §16.2의 pytest114.24초·실행기115.31초(testcase 합111.635초)다. 전체 회귀 안에서 동일4파일의 testcase 합은 **140.253초**(integration60.419·property60.963·UI7.570·unit11.301)였다. 두 측정은 서로 다른 실행이며, 전체 속의 수치를 선택 실행 값으로 대체하지 않는다. 이 차이의 원인을 따로 분리 측정하지 않았고 경우의 수 축약·fixture 변경·예산 증액은 하지 않았다. 전체 내 누적 시간에도 120초를 적용할지에 대한 C00 판단을 위해 함께 보고한다.

S/final-scope-proof.json에서 현재 작업 트리의 G06 Python26파일과 시험 사본의 LF 차이0, 사본 범위 밖 파일과 HEAD archive의 바이트 차이0을 확인했다. MainWindow는 HEAD 대비 호출1줄만 변경(+1/−1). G-P15 작업 트리 파일을 사본에 복사하지 않았다. 아래 결과·해시 기록은 시험 종료 뒤 문서에 추가하며 제품 코드·시험 코드는 바꾸지 않았다.

기능 수정의 남은 구현은 없다. G06R-01~07의 최종 닫힘은 독립 재확인과 C00 판단에 맡긴다. 시간 측정 차이는 위와 같이 별도 보고하며, 실제 가격 최초 항목·자동 usage 연결은 기존 승인된 후속/외부 게이트 그대로다.

### 16.5 실제 변경 파일의 LF SHA-256

실제 변경27파일 중 Python26파일의 해시다. 경우의 수 문서 자체 해시는 최종 이 창과 S/manifest-final.json에 별도로 보고한다. 승인 목록 중 변경하지 않은3파일은 이 표에 넣지 않는다.

| 파일 | SHA-256(LF) |
| --- | --- |
| src/recoryn/security/cost.py | 5121330e3cec65c32646c25b0e7d2ef2a1acb3bb71213466c3ba87b85b46b9f6 |
| src/recoryn/security/cost_catalog.py | 2273ed62714bc8ee79c1e6968e54549a63d15daf214e675b97aff6bbaddb050a |
| src/recoryn/security/ledger.py | 374d07dd49876707a84e27e3b0547f0b23dc1430425fda6aa8f367151876e961 |
| src/recoryn/security/gateway.py | 02a345bc98a512a77d2ebf41c457dbe1e865f1643db7968427b92a86ca7795ca |
| src/recoryn/security/__init__.py | 43d30b6fb9eb39c002ffecae9169bbfcaabfd381e33c208adc21b8c9bd51caa5 |
| src/recoryn/providers/contracts.py | 82d362917540e7035c749787137064cc5b8360c770cec5a10b01aff94a3d039a |
| src/recoryn/providers/_common.py | 310a2f958a1745a69e320030e287ab791795965ad668c9f21fbdd3091c4e363b |
| src/recoryn/transcription/adapters.py | 7428d6a3eebcfba6f9ccc90e0abd19509651d903c6f3128fd1963777c4ec266c |
| src/recoryn/summarization/adapters.py | ee244773642a73e3d30ba64712deea158185f08ad6d08344ef3aff148434d240 |
| src/recoryn/app/ai.py | dd6291ce65292230e4deaa8516f9356e09c6d1ff6aca71049dcd1721984d03c5 |
| src/recoryn/ui/privacy.py | 474588f59ff676c1ae85136bbda95cfa4238aac8cfba333bf06eaee3d6fe007f |
| tests/unit/test_cost_cap.py | a57b076e44ec68a398f01af44928c9b69363b0dda04bf0a3d649807ca70a6715 |
| tests/property/test_cost_cap_case_space.py | 4e34b0bccf824404ee08ad73691a22ae1d9008e2f8565aa36aa2e287ddf80284 |
| tests/integration/test_cost_cap.py | 85e71c4601c75e1bd8e6402c2a6e7e72177059de3e296ada8b8c8dc09979a875 |
| tests/ui/test_cost_cap_ui.py | 32a117aa9cf3e1f1b21685584ddbdf7defff117e69a6c2a9b5fa12fe5aeeca22 |
| tests/unit/test_providers.py | eb8b649d564199de0dd7995c430bd38c50c9bfd4e8d5cf646891784c00e039a7 |
| tests/property/test_security_case_space.py | 17506104be58ca68fd27ece7ede8092a02422841d459595842a670baf7d9600b |
| tests/integration/test_gateway.py | 97e2470314967c68f03476b56c61e43af51e2d3b70c5ef06945c28458467795d |
| tests/integration/test_egress_independent.py | cf0043af4653f3eadb761e6ad8ed61dad24458dda063ea1458a7eb02bb8bcaba |
| tests/integration/test_provider_security_independent.py | 7eafb85a8002f184d2b309685cf649fe960318b7516fbde86fa1d3591aa5ec3e |
| tests/integration/test_publication_independent.py | be0768e291bea77e85a91def58b59d3868854c6873d40d59d3efe177a0a1f046 |
| tests/integration/test_consent_scope.py | 7fa7a2646c7042525ccd3451846d9fa9f5da414e57cac2052aaa703e8de496bd |
| tests/contract/test_provider_contracts.py | 0c0dc941ed31b53e5df132838fdc3cc1b79f2c6d9770a0a43e2475af88a5c61c |
| tests/ui/test_privacy_ui.py | 7daa11da328c8899f8f886f35a2f63ea37028d86be0e62253745575710fdf1c9 |
| tests/ui/test_consent_scope_ui.py | fa836e195864248d3bad20e35cf8db303a23f5ada3e7dfcd51c43af4829ebd9e |
| src/recoryn/ui/main.py | 8c92a483b78cbd57377fc28863ff05a8d8df1528c008e8a9d6cd4a5dc3a6649b |

## 17. G06 FIX2 커버리지 오염·실제 미검증 분기 보강

### 17.1 착수 계획과 판정 기준

C00의 정확한 tree f53893fa 검증은 14,850 PASS지만 CI 커버리지 예산이 실패했다. C00 보고의 security93.16/82.26 및 all81.77/72.77은 인계받은 결과이며 이번 직접 실측이 아니다. 기준은 HEAD6072ef1, 작업은 G06 승인 범위 안에서 수행하고 G-P15 제품/시험/문서는 수정하지 않는다.

먼저 기존 G06-DB 16행의 legacy_class를 비제품 모듈 이름으로 읽되, 상대 import는 __package__를 명시하는 최소 조정만 한다. LEGACY_V1_SOURCE·LEGACY_V1_SHA256 검사는 그대로 둔다. 이 단계는 기존 시험 의미·ID를 바꾸거나 옛 코드를 coverage 분모로 세지 않도록 하는 조정이다.

TEMP archive 사본에서 현재4파일의 진단 coverage를 먼저 읽고, 보강 시험을 쓰기 전에 실제 미실행 경계의 입력 분할·정확한 독립 기대 코드/금액/상태와 보강 ID 목록을 이 절에 고정한다. 새 접두사는 G06-COV2-이며 원 의미 분모4,834에 합치지 않는다. assert 없는 호출·제품 함수를 재사용한 expected·pragma/no-cover·pyproject/check_coverage 예산 변경은 하지 않는다. 도달 불가 방어는 근거로 보고하고 숨기기 전에 C00 확인을 받는다.

수락은 신규4파일120초 시간 게이트, 의미4834 및 보강 ID 누락/중복 감사, HEAD6072ef1+G06 실제 변경 파일만의 최종 전체 오프라인 CI 명령(--cov=recoryn --cov-branch --cov-fail-under=85), scripts/check_coverage.py의 모든 묶음 PASS, coverage.json의 tmp 사본0, ruff/format/mypy다. ResourceWarning은 오류로 처리한다. 일부 파일만의 진단 coverage는 최종 전체 결과로 보고하지 않는다. 저장소 루트 coverage.json은 옛185문장 ledger 보고서라 이번 f53893fa의 실패 보고로 사용하지 않았다.

### 17.2 보강 입력 분할·독립 oracle(시험 작성 전)

진단 선택 실행은4,908 PASS·154.47초, tmp ledger 측정0이었다. 직접 coverage는 cost278/350문장·100/162분기, ledger586/662문장·180/246분기였다. 기존 보안 회귀를 제외한 선택 계측이므로 이 수치를 전체 budget 판정으로 쓰지 않는다. 계측 시간은120초를 넘었으며 경우의 수 축약/예산 변경 없이 보고한다. 첫 package 지정은 __package__/__spec__ 불일치 경고16건이 있어, 옛 원문은 그대로 두고 비제품 package+실제 _core alias로 보정한다.

다음은 새로운 보강178행 계획이다. G06-COV2 접두사를 쓰고 의미 분모4,834 및 기존74 보강/manifest와 분리 감사한다. hand-written 입력 목록은 TEMP cov2-plan.json에도 고정했다.

| 가족 | 입력 분할·분모 | 독립 기대 |
| --- | ---: | --- |
| REQ/POLICY/PRICE | 요청 DTO16·정책7·가격 metadata28 | bool/비지원 문자열/빈·과대 필드·비정규 endpoint·bytes/tuple 계약·부분 유효시각·출처 형식 위반을 COST_REQUEST_INVALID로 거부 |
| HEADERS/CURRENCY/CLOCK/CATALOG | 6/3/9/3 | header 중복·타입·CR/LF, 통화 대문자3자리, 유한 비음수 clock, catalog tuple/항목/중복 키 검증. CLOCK은 정상0/12.25도 확인하여 blanket reject를 막음 |
| WIRE | 명명48 | 실제 OpenAI/Anthropic/Gemini JSON·multipart·작은 WAV의 알려진/추가/누락/중복/잘못된 role·MIME·base64·시각/출력 제한 경계. 단일 결함별 COST_REQUEST_INVALID, 네트워크/SDK 호출0 |
| QUOTE | 타입3 + 상한 부적합3×strict/general2 + 입력 상한 overflow1 =10 | 정확한 코드·USER_CAP 식별·한도 금액. upper가 없는데 VERIFIED로 승격하지 않음 |
| POS | 7 | 허용 header만의 정렬, 독립 SHA/JSON 기대 fingerprint, 실제 공급자 wire5종의 수작업 token/초·ceil 산술과 예약 상한 |
| WRITE | 14 | direct phase=write에서 본문 identity/문맥7, dispatch/state/quote/blocked/exposure/기간7. 거부 코드·원장 행·금액 불변으로 비교; Gateway가 같은 인자를 쓰는 경우와 구분 |
| EXTERNAL | 4 | 별도 SQLite 연결 변조, 다른 Ledger의 유효 정산/legacy/다른 기간 갱신 뒤 stamp 재인증. 변조는 LEDGER_ROLLBACK_DETECTED, 정상 갱신은 최신 노출 반영/정확 사유 |
| OPEN/TYPED | 5/4 | phase/provider/fingerprint/catalog/quote 불일치와 공개 API DTO 오용. 거부·예약행 불변 |
| CACHE/OLDV2 | 1/1 | 캐시4개 초과 후에도6개 예약·88금액 보존과 재검증, 인증된 audit열 없는 구v2의 명시 additive 전환·금액/high-water 보존 |
| IO/WITNESS | 2/3 | v1→v2/일반 변경의 witness 게시 실패 시 rollback, v1 witness 과대/타입/메타유실 거부. source 행/기존 witness 보존·정확 오류 |
| AVAILABILITY/CLOSED/USAGE | 1/1/4 | 비용 불능의 안전 상태·close 멱등과 불능 객체 cleanup, usage version0/bool 아닌 final/통화/legacy 금지 |
| MANIFEST | 1 | 고정 가족별 기대 개수·ID 유일성을 실제 수집과 별도 대조 |

합계178은 새로운 입력/보강 계획이며 실행 PASS나 새 가격 근거가 아니다. DTO·wire의 거부는 정확한 code, 정상 wire의 기대 UTF-8 byte 수·audio ceil·금액은 literal/Fraction/수작업 JSON SHA로 계산한다. ledger의 fault fixture는 고의로 알려진 schema/행을 만들어도, 기대 상태/노출/금액을 제품 _snapshot이나 _state로 생성하지 않는다. 유효 witness를 만드는 setup과 검증 oracle를 구분한다. 개별 구현에서 가족의 실제 분할이 달라지면 실행 전에 이유와 갱신된 분모를 기록한다. pragma/문장 삭제로 숨기지 않는다.

### 17.3 진단 후 입력 계획 보강

178행은 직접 실행해 모두 PASS했다(2.48초, ResourceWarning 오류 승격). 진단 coverage 합산에서 cost는348/350문장·160/162분기까지 도달했다. 남은 text-fixture-v1 공개 파서의 거부3종(추가 필드·모델 불일치·text 비문자열)을 WIRE에 추가해51행, 전체 보강을 **181행**으로 고정한다. production catalog에서 이 프로토콜을 거부하는 기존 검사는 유지하며, 이를 실제 제공업체/실가격 검증으로 세지 않는다. 기존 CLOSED1행은 close 뒤 직접 write API도 같은 LEDGER_CLOSED로 거부하는 상태열을 확인한다.

cost.py의 뒤쪽 중복 currency 방어(현재582행)는 immutable entry/policy의 currency를 앞의 동일 비교에서 이미 거부하므로 정당한 입력 경로로는 도달하지 않는다. 이를 pragma로 제외하거나 frozen 객체를 몰래 바꿔 도달시켰다고 하지 않는다. 남은 ledger의 방어 경로도 최종 전체 보고에서 실제 미실행 목록과 도달 조건을 구별한다.

### 17.4 현재 정상본·변이·시간 실측과 최종 CI 실행

새 보강181행은3.90초에 모두 PASS했고, 고정 그룹별 ID181개 누락/중복0을 XML로 감사했다. 기존 178행 실행(2.48초) 뒤 WIRE3행을 추가한 이력을 구별한다. legacy 원문·SHA 상수는 FIX1 이전과 완전히 같고 SHA는890baaf75eae21e3307c66eb38144407735572b9f66ef187ab3dfaea24dd7935다. 비제품 g06_legacy_v1_fixture package에 실제 recoryn.security._core만 alias하므로 원문 상대 import를 바꾸지 않고 경고도 없앴다.

별도 process 예약 경쟁의 자식 PYTHONPATH를 부모가 실제 import한 src로 고정하고 ledger.__file__도 assert했다. 기존 경쟁 case ID/승자1 oracle는 유지한다. 새 보강으로는 세지 않는다.

추가 TEMP 변이 N01(본문 identity/문맥 검사 제거)·N03(stamp 변경 뒤 재인증 제거)는 각각 WRITE-006·EXTERNAL-000의 DID NOT RAISE assertion으로 **2/2 검출**됐다. 정상181행 PASS와 구별하며 최초 harness 문법 오류는 제품 변이 검출로 세지 않는다. 대상 ledger 제품 source LF SHA374d07dd49876707a84e27e3b0547f0b23dc1430425fda6aa8f367151876e961은 FIX1과 같다.

정상4파일은 **5,089 PASS·skip/제외/실패/경고0, 144.56초**(실행기145.57초)였다. testcase 합142.083초(unit12.988/property66.501/integration56.176/UI6.418), 그중 새181행2.054초·기존 행140.029초다. **120초 예산 초과**를 C00에게 보고했고, 행 축약·oracle 변경·예산 증액은 하지 않았다. fixture 최적화/조용한 재측정 구간은 C00 판단을 기다리며, 이 결과를 시간 게이트 PASS로 쓰지 않는다.

제품 코드는 FIX1 그대로이고 이번 수정은 unit/integration 비용 시험 두 파일과 이 문서다. ruff check·format(168파일)·mypy(86 source files)는 사본에서 PASS했다. 이제 HEAD6072ef1+G06 실제 변경27파일만의 TEMP 사본에서 CI와 같은 coverage 옵션으로 전체 오프라인을 실행하고, check_coverage 출력 전문·tmp fixture0·최종 남은 방어 목록과 해시를 아래에 추가한다.

### 17.5 최종 전체 CI 커버리지 결과와 출력 전문

증거 루트 **U=C:/Users/gangd/AppData/Local/Temp/recoryn-g06-fix2-e4313a16bd91442abd4ff84ec12a4df6**. U/isolated는 HEAD6072ef1dfbb5c69490812ca1b103e248dbf78743 archive에 G06 실제 변경27파일만 적용한 사본이다. G-P15 작업 트리 파일은 복사하지 않았다.

다음 CI 명령으로 **15,031 PASS·skip/제외/실패/경고0, 1021.74초**(실행기1027.92초, U/fullcov.xml·fullcov.log·fullcov-result.json, exit0):

```text
python -B -m pytest -q -p no:cacheprovider -W error::ResourceWarning --cov=recoryn --cov-branch --cov-report=json:coverage.json --cov-fail-under=85 --basetemp <U>/bt-fullcov --junitxml <U>/fullcov.xml
python -B scripts/check_coverage.py coverage.json
```

pytest-cov의 line+branch 합산은92.53%로 --cov-fail-under=85도 통과했다. 아래는 별도 line/branch 예산 검사의 **출력 전문**(U/coverage-check.log, exit0)이다.

```text
domain: line=100.00%/95% branch=100.00%/90% PASS
capture: line=99.85%/95% branch=98.57%/90% PASS
jobs: line=98.89%/95% branch=97.47%/90% PASS
storage: line=96.30%/95% branch=91.56%/90% PASS
security: line=98.11%/95% branch=94.43%/90% PASS
content: line=99.59%/95% branch=98.75%/90% PASS
all: line=93.95%/85% branch=88.20%/80% PASS
```

최종 coverage.json은73개 제품 source만 포함하고, 경로가 src/recoryn 밖인 측정 파일0·ledger-v1 tmp fixture0이다. SHA256은743f903735a644aefe60bb6629ff6af6c0551ef8f31a00395f0008831d42fce3(U/isolated/coverage.json). 실제 TEMP archive의 제품 source는 측정 대상이고, 제외된 것은 제품 namespace로 위장했던 옛 fixture다. source/omit 설정·checker·기준 수치·pragma는 바꾸지 않았다.

cost.py는 **349/350문장·161/162분기**, ledger.py는 **647/662문장·228/246분기**를 확인했다. UI500·G03 content103/CAS203도 전체 안에서 PASS다. 원 의미4,834와 새 G06-COV2 보강181을 별도 감사해 각각 missing/duplicate/extra0, 전체 pytest node 중복0이다. 신규4파일 전체는5,089node=원분모4,834+기존 non-family74+새181이다(U/semantic-audit.json·final-audit.json). 과거 보강/manifest를 새 의미 분모로 부풀리지 않았다.

### 17.6 남은 방어 경로·시간 게이트·한계

| 근거 | 판단·처리 |
| --- | --- |
| cost.py:582 및 분기581→582 | 앞의 currency 비교에서 같은 불변 entry/policy의 불일치를 이미 거부한다. 현재 지원 DTO/동기 경로에서 중복 방어다. 임의 object 변경/동일 프로세스 악성 코드를 허용한 절대 불가능 증명은 아니다. pragma 없이 남김 |
| ledger.py:639~641 | settle 초반의 SETTLED 검사가 같은 읽기 전용 SQLite Row에 대해 이미 return/raise했다. 뒤의 동일 SETTLED 참 분기는 정상 경로상 중복이다. pragma 없이 남김 |
| ledger.py 분기1110→1134 | 지원 phase 문자열은 open/write뿐이고 write는 앞에서 return한다. 이 지점의 정상 phase는 open이라 false edge는 중복 방어다. phase 타입을 속이는 임의 객체는 지원 경로로 세지 않음 |
| ledger.py:302/333/534/575/683/826/830/869/937/1026/1109/1142 및 rollback 분기195→197·425→427 | 구조/메타 손상·직접 API/중복 요청·만료·예외 경계의 **현재 미실행 부분**이다. 모두 도달 불가라고 단정하지 않는다. 이번 기준은 security 묶음95/90을 충족하는 것이며100% 전수 검증을 주장하지 않는다. 제외/삭제하지 않았다 |

비계측4파일의 첫 실행5,089 PASS·144.56초 뒤, 이 작업의 다른 실행을 겹치지 않고 같은 source를 한 번 더 측정해 **5,089 PASS·123.10초**(실행기124.05초, testcase 합120.421초: unit11.230/property60.441/integration42.303/UI6.447)를 얻었다(U/four-recheck.xml·four-recheck.log). 전체 PC의 다른 작업이 없었다고 확인한 것은 아니다. **120초를3.10초 초과하므로 시간 게이트 PASS나 예산 증액으로 처리하지 않는다.** 최초144.56초와 진단 계측154.47초도 보존한다. C00에게 측정값과 조용한 구간/fixture 방향을 요청했으며, 행 축약·oracle 완화·최소 시간만 골라 과거 초과를 숨기는 변경은 없다.

기능/커버리지 수정은 검토 가능한 상태이며, **시간 예산의 남은 초과는 C00 판단 사항**이다. S0/S1의 닫힘을 작성자가 단독 재승인하지 않는다. 실가격 첫 항목·자동 usage 연결·실네트워크/전원 장애 외부 게이트는 기존 인계 그대로다. G09/G10 재대조 결과는 보존하고 이번 작업에서 변경하지 않았다.

### 17.7 최종 파일·범위 증거

FIX1 뒤 변경은 이 문서와 tests/unit/test_cost_cap.py·tests/integration/test_cost_cap.py **3파일**뿐이며 제품 코드 변경0이다. G06 전체로는 HEAD6072ef1 대비27파일이다. U/final-audit.json에서 시험 source와 작업 트리 Python의 LF 차이0, 사본 범위 밖 HEAD 파일 바이트 차이0을 확인했다. ruff check PASS·ruff format168파일 PASS·mypy86 source files PASS다.

아래는 G06 실제 변경27파일 중 Python26파일의 **현재 LF SHA256**이다. 이 문서 자체의 최종 SHA는 이 창과 U/manifest-final.json에 별도로 쓴다. §16.5의 이전 시험 hash와 구분한다.

| 파일 | SHA256(LF) |
| --- | --- |
| src/recoryn/security/cost.py | 5121330e3cec65c32646c25b0e7d2ef2a1acb3bb71213466c3ba87b85b46b9f6 |
| src/recoryn/security/cost_catalog.py | 2273ed62714bc8ee79c1e6968e54549a63d15daf214e675b97aff6bbaddb050a |
| src/recoryn/security/ledger.py | 374d07dd49876707a84e27e3b0547f0b23dc1430425fda6aa8f367151876e961 |
| src/recoryn/security/gateway.py | 02a345bc98a512a77d2ebf41c457dbe1e865f1643db7968427b92a86ca7795ca |
| src/recoryn/security/__init__.py | 43d30b6fb9eb39c002ffecae9169bbfcaabfd381e33c208adc21b8c9bd51caa5 |
| src/recoryn/providers/contracts.py | 82d362917540e7035c749787137064cc5b8360c770cec5a10b01aff94a3d039a |
| src/recoryn/providers/_common.py | 310a2f958a1745a69e320030e287ab791795965ad668c9f21fbdd3091c4e363b |
| src/recoryn/transcription/adapters.py | 7428d6a3eebcfba6f9ccc90e0abd19509651d903c6f3128fd1963777c4ec266c |
| src/recoryn/summarization/adapters.py | ee244773642a73e3d30ba64712deea158185f08ad6d08344ef3aff148434d240 |
| src/recoryn/app/ai.py | dd6291ce65292230e4deaa8516f9356e09c6d1ff6aca71049dcd1721984d03c5 |
| src/recoryn/ui/privacy.py | 474588f59ff676c1ae85136bbda95cfa4238aac8cfba333bf06eaee3d6fe007f |
| tests/unit/test_cost_cap.py | c1ac728a2064a230b08e9a5b5af4acc0df955fd9cfd97f5ed4b083f46f163880 |
| tests/property/test_cost_cap_case_space.py | 4e34b0bccf824404ee08ad73691a22ae1d9008e2f8565aa36aa2e287ddf80284 |
| tests/integration/test_cost_cap.py | 284024599e76788d26f983c1ad1b3902cec6190ddab3fe3262ebfeb7c0412251 |
| tests/ui/test_cost_cap_ui.py | 32a117aa9cf3e1f1b21685584ddbdf7defff117e69a6c2a9b5fa12fe5aeeca22 |
| tests/unit/test_providers.py | eb8b649d564199de0dd7995c430bd38c50c9bfd4e8d5cf646891784c00e039a7 |
| tests/property/test_security_case_space.py | 17506104be58ca68fd27ece7ede8092a02422841d459595842a670baf7d9600b |
| tests/integration/test_gateway.py | 97e2470314967c68f03476b56c61e43af51e2d3b70c5ef06945c28458467795d |
| tests/integration/test_egress_independent.py | cf0043af4653f3eadb761e6ad8ed61dad24458dda063ea1458a7eb02bb8bcaba |
| tests/integration/test_provider_security_independent.py | 7eafb85a8002f184d2b309685cf649fe960318b7516fbde86fa1d3591aa5ec3e |
| tests/integration/test_publication_independent.py | be0768e291bea77e85a91def58b59d3868854c6873d40d59d3efe177a0a1f046 |
| tests/integration/test_consent_scope.py | 7fa7a2646c7042525ccd3451846d9fa9f5da414e57cac2052aaa703e8de496bd |
| tests/contract/test_provider_contracts.py | 0c0dc941ed31b53e5df132838fdc3cc1b79f2c6d9770a0a43e2475af88a5c61c |
| tests/ui/test_privacy_ui.py | 7daa11da328c8899f8f886f35a2f63ea37028d86be0e62253745575710fdf1c9 |
| tests/ui/test_consent_scope_ui.py | fa836e195864248d3bad20e35cf8db303a23f5ada3e7dfcd51c43af4829ebd9e |
| src/recoryn/ui/main.py | 8c92a483b78cbd57377fc28863ff05a8d8df1528c008e8a9d6cd4a5dc3a6649b |
