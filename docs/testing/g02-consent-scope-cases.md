# G02 / G-P02 전송 동의 범위 계약안과 경우의 수

상태: **IMPLEMENTATION_READY — C00 계약 승인, G-P03 뒤 2단계 구현·검증 완료, 독립 검토 대기**. 작성: 2026-11-23, w5:p8 Codex. 최초 CONTRACT_READY의 LF SHA256은 `3b6cf68d05dd2b05110f1df50d6ac5d1d6148c5a0f3f852726874b72bada18eb`다. C00은 §2 계약과 §6의 19파일 범위를 승인했고, 후속 시작 신호 뒤 ai_bridge.py를 연결했다. §1~7은 당시 계약·계획, §8은 PHASE1 이력, **§9는 최종 직접 실행 증거**다. 독립 검토·C00 통합 승인 없이 단위를 CLOSED로 판정하지 않는다.

## 1. 요구와 직접 확인한 현재 경계

정본은 [배정표 G02](../collaboration/assignments.md), [통합안 G-P02](../implementation/v1-gap-plan.md), [architecture의 전송 동의와 비용](../architecture-v1.md), [경우의 수 규칙](case-space.md)이다. G01B-040/F-SEC01과 G01BR-01·10을 함께 읽었다. 범위 누락은 **S1·최우선**, 범위·만료·정책 표시 누락은 S2다. UI에 세션 범위 안내가 없었던 사실을 사용자의 전체 세션 동의 증거로 쓰지 않는다.

| 직접 읽은 코드 | 현재 사실 | G02에서 바꿀 계약 |
| --- | --- | --- |
| `src/recoryn/security/consent.py:67`, `:152`, `:191` | grant PK는 provider/endpoint/data_type, TTL·실행 세대 검사 존재 | 기능·선택 범위·정책 version까지 정확히 일치 |
| `consent.py:83`, `:106` | **ConsentStore 생성마다** 새 execution_id를 DB에 기록하며 이전 인스턴스도 무효화 | 이전 grant의 자동 승계 없이 이 경계를 유지 |
| `consent.py:230`, `:252`, `:313`, `:350` | grant ID/epoch를 캡처·재검사, permit 수명 최대 30초 | 새 범위·기능·정책과 요청 세션까지 고정 |
| `consent.py:261`, `:278`, `:287` | session binding은 삭제·세대 fence이며 grant 허용 범위가 아님 | 전체 동의에서도 삭제 fence는 별도로 필수 |
| `src/recoryn/security/gateway.py:69`, `:132`, `:243` | 세션 view, 연결·write 재검사, UNKNOWN 유지 | 기존 선형화·비용·owner guard 순서 보존 |
| `src/recoryn/ui/privacy.py:200`, `:278`, `:322`, `:389` | 범위 선택 없음, context와 gateway가 각각 bindings를 캡처 | GUI에서 한 요청의 동일한 불변 스냅샷 생성 |
| `src/recoryn/ui/ai_bridge.py:103`, `:112`, `:129`, `:263` | 선택 세션은 알지만 privacy에 전달하지 않음 | 선택 표시와 실제 작업의 고정 session_id 전달 |

G01BR-01의 P1(`opens_after_one_grant_two_sessions_and_revoke_a = 3`)은 **상대 문서의 관측 결과를 인용**한 것이다. 이번 계약 단계에서 반례나 기존 시험을 다시 실행한 결과가 아니다. 본인의 최초 F-SEC01 역시 무동의 전송 사고를 관측했다는 주장이 아니다.

## 2. 제안 결정

### 2.1 범위와 기능

1. 기본은 `SESSION(A)`다. 세션 A의 동의로 B를 허용하지 않는다. `bind_session`만 호출해 권한이 생기지 않는다.
2. 명시적 `LIBRARY` 범위를 둔다. **현재 ConsentStore가 속한 라이브러리의 현재·새 세션**, 현재 실행 세대, 해당 grant TTL 안에 한한다. 다른 라이브러리·다른 Windows 사용자·다음 실행·모델 다운로드에는 적용하지 않는다. 이 단위에서 계정 또는 사용자 그룹 범위를 새로 만들지 않는다.
3. SESSION 키를 선택한 요청은 LIBRARY grant로 자동 fallback하지 않는다. SESSION 동의를 철회해도 남은 LIBRARY grant로 같은 옛 요청을 살릴 수 없다. LIBRARY를 쓰려면 그 범위를 명시적으로 선택한 새 요청 계획이 필요하다.
4. 기능은 정확한 `stt`, `summary`, `diarization` 식별자로 분리한다. 하나의 기능 동의가 다른 기능을 허용하지 않는다. 현재 UI는 STT·요약만 노출한다. 화자 구분은 현재 로컬 경로를 유지하고, `diarization` 권한의 fake 시험이 원격 화자 구분 기능 추가를 뜻하지 않는다.
5. 데이터 종류는 기존 정확한 식별자를 유지한다. 오디오·전사·문맥·첨부는 각각 다른 키다. 첨부의 보안 키 시험은 첨부 제품 기능 구현을 뜻하지 않는다. STT·요약 각 어댑터의 지원 데이터 제한은 그대로 유지한다. 범위 확대를 위해 다른 데이터 종류로 바꾸어 적지 않는다.
6. 로컬 faster-whisper·로컬 화자 구분에는 전송 grant를 요구하지 않는다. Ollama loopback은 기존 artifact 증명·실행 guard에 **더해** 요약/선택 범위/정책 동의가 필요하다. 외부 서버의 후속 무전송까지 보장하는 계약이 아니다.

### 2.2 grant schema와 불변 DTO

제안 schema는 기존 표를 재해석하지 않는 additive 방식이다. `security.sqlite`는 CostLedger와 공유하므로 기존 표·ledger·witness·`PRAGMA user_version`을 바꾸거나 삭제하지 않는다. 범용 migration/backup G-P09를 완료했다고 주장하지 않는다.

C00 승인에 따라 **G-P09 migration이 `security_grants_v2`·`security_consent_meta`를 버전 목록에 인계하고, v1 표 정리를 그 단위에서 다룬다.** G02는 v1 grant를 새 범위로 승계하지 않는다.

| 대상 | 필드/제약 |
| --- | --- |
| `security_consent_meta` | 단일 행, `schema_version=2`, `policy_version` 양의 정수. schema와 동의 정책의 version은 별개 |
| `security_grants_v2` 키 | `(provider, endpoint, capability, data_type, scope_kind, scope_id, policy_version)` 전부 NOT NULL |
| 범위 표현 | `scope_kind='session'`이면 유효한 비어 있지 않은 session ID. `'library'`이면 내부 canonical `scope_id=''`. NULL·누락을 전체로 해석하지 않음 |
| grant 값 | 임의 `grant_id`, 기존 실행 `generation`, 해당 전체 키의 `epoch`, `issued_at`, `expires`, `allowed`, `revoked_at`(미철회 시 NULL). 시각은 유한·정상 순서, 허용 플래그 0/1, epoch는 비음수 정수 |
| `ConsentScope` | frozen 값 객체. `session(id)`와 `library()` 명시 생성. 임의 경로·제목·사용자 자유 입력을 ID로 쓰지 않음 |
| `ConsentRequest` | frozen `(session_id, session_generation, capability, policy_version)`. 전송에는 **LIBRARY라도 요청 세션이 필수** |
| `ConsentBinding` | 기존 execution/grant ID/epoch/provider/endpoint/data_type + grant의 capability/scope/policy + 캡처 당시 `ConsentRequest` |
| `SendPermit` | 위 전체 binding과 동일한 요청 문맥 + 기존 body hash/reservation ID/짧은 expires. grant 범위와 요청 세션은 별도 값으로 보존 |

같은 전체 키의 재동의는 새 grant ID와 증가한 epoch를 발급한다. 다른 키 동의의 epoch로 옛 binding을 갱신하지 않는다. epoch overflow·잘못된 타입은 쓰기 전 실패한다. SQL 제약과 API 값 검증을 모두 두며 bool을 int로 받아들이지 않는다. 비밀·인증 헤더·본문·세션 제목은 이 schema에 넣지 않는다.

`policy_version`은 신뢰된 앱 정책 식별자이며 UI에서 숫자를 편집하지 않는다. 초기 제안값은 2다. 생성자 `policy_version=2`와 신뢰된 내부 `advance_policy_version(v)`를 두며, 같은 version은 no-op, 증가는 같은 coordinator에서 commit, 감소는 거부한다. 증가는 모든 옛 정책 grant·binding·permit을 무효화하고 새 정책에 다시 동의하게 한다. 새 version 행이 생겨도 옛 계획은 새 행을 채택하지 않는다. 저장된 현재 정책보다 낮은 정책을 요구하는 실행은 fail closed한다. 정책 변경은 가격표 변경이나 예산 초기화가 아니다.

### 2.3 ConsentStore와 Gateway API

다음은 승인 대상 공개 계약의 형태다. 생략 가능한 옛 3인자 grant를 전체 동의로 바꾸는 호환 경로는 두지 않는다. 옛 호출은 새 필수 keyword가 없어서 실패하며 DB grant를 만들지 않는다. DTO 생성·API 오류는 기존 비민감 `SecurityError` 경계를 따른다.

```text
grant(provider, endpoint, data_type, *, capability, scope, policy_version,
      expires_at=None) -> str
revoke(provider, endpoint, data_type, *, capability, scope, policy_version) -> None
allowed(provider, endpoint, data_type, *, scope, request: ConsentRequest) -> bool
capture_bindings(provider, endpoint, data_types, *, scope,
                 request: ConsentRequest) -> tuple[ConsentBinding, ...]
validate_binding(binding: ConsentBinding) -> None
permit(provider, endpoint, data_type, body_sha256, *, scope,
       request: ConsentRequest, expected_grant: ConsentBinding,
       reservation_id=None) -> SendPermit
validate(permit: SendPermit) -> None
revoke_endpoint(provider, endpoint) -> None
advance_policy_version(version) -> None

Gateway(..., expected_grants=bindings).for_session(
    session_id, generation=0, *, capability, scope, policy_version
) -> Gateway
# provider의 GatewayLike.request(...) 서명은 그대로 유지한다.
```

- `allowed`는 키가 존재한다는 뜻이 아니라 **해당 요청에 효과적으로 허용되는지**를 반환한다. UI의 범위 목록/시각 표시는 비민감 읽기 전용 `grant_info`로 분리한다. 이 조회가 권한을 발급하지 않는다. grant/capture/permit은 현재 정책만 허용하며, 정보 조회와 권한 축소인 revoke는 옛 정책의 정확한 키도 다룰 수 있다.
- capture는 해당 요청·선택 범위에 이미 허용된 데이터 종류만 동결한다. 나중에 추가된 context grant를 옛 transcript-only 계획에 끼워 넣지 않는다.
- unbound Gateway, 누락/빈 expected_grants는 기본 거부다. 연결 전에 `CONSENT_REQUIRED`로 실패한다. 세션을 붙였다는 사실만으로 현재 grant를 임의로 다시 검색·채택하지 않는다.
- `for_session`은 캡처 요청과 전체 문맥이 같아야 한다. A로 캡처한 LIBRARY binding도 B view로 바꿀 수 없다. B의 새 사용자 작업은 B 문맥으로 새 capture를 한다. 전송 중 widgets나 현재 선택을 읽지 않는다.
- `revoke_endpoint`는 그 endpoint의 **모든 기능·데이터·범위·정책**을 원자적으로 철회한다. 키 삭제/교체의 기존 무효화 의미를 유지하기 위한 API이며 특정 세션 grant만 철회하는 버튼과 다르다. 다른 endpoint는 유지한다.
- `revoke_session(A)`는 기존 영속 삭제 fence다. A의 SESSION/LIBRARY 요청을 모두 차단하지만 LIBRARY grant 자체를 지우지는 않는다. 별도로 시작한 B 요청의 명시적 LIBRARY 동의는 유지된다. A의 세션 세대 증가·삭제 journal·삭제 tombstone 검사를 우회하지 않는다.
- 조회·예약 전 binding 검사·연결 전 permit 검사·각 write·최종 응답 경계에서 새 항목을 검사한다. consent → ledger → owner 순서와 **write handoff 동안 coordinator 유지**를 보존한다. 철회가 먼저 commit하면 새 연결/단위를 시작하지 않으며 먼저 handoff한 bytes를 회수했다고 표시하지 않는다.
- 유효한 요청 문맥을 받은 Store의 permit 판단 내부 진단 우선순위는 입력 형식 → 활성 시계/실행 세대 → 현재 정책 → 정확한 grant 키/TTL/allowed → 캡처 ID/epoch/문맥 → 요청 삭제 fence → 기존 budget/owner/transport 순이다. 여러 원인이 동시에 실패해도 연결·write가 없어야 한다. 잘못된 endpoint 등 기존 입력 검증 우선순위는 유지한다. 앞선 capture/불변 view 조립 단계에서 거부되는 경우에는 그 phase를 기록하며, 아직 호출하지 않은 permit의 오류를 관측한 것으로 쓰지 않는다. 기존 오류 코드의 세부 재사용은 구현 diff에서 검토한다.
- 승인 전 가능한 보안 오류를 코드 목록에 새로 구현하지 않는다. `CONSENT_REQUIRED`, `PERMIT_REVOKED`, `EXECUTION_CHANGED`, `SESSION_REVOKED`, `CONSENT_CLOCK_INVALID`의 기존 의미를 보존하고 정책 불일치에는 비민감 `CONSENT_POLICY_CHANGED`를 제안한다.

### 2.4 UI와 앱 연결

각 STT/요약 control에 기본 `이 세션만`과 별도 `현재 라이브러리 전체` 선택을 둔다. 세션 한정이면 표시명과 짧은 식별자를 함께 보여준다. 선택 세션이 없으면 세션 한정 동의와 전송은 비활성이다. 전체 동의는 별도 확인에서 **현재·새 세션 포함, 현재 실행만, 만료 시각, 기능·데이터 종류·수신 endpoint·정책 version**을 보여주고 명시적 확인 후 발급한다. 취소/Esc는 무변경이다. 세션 미선택이어도 이 확인을 마친 전체 grant 발급/철회는 가능하지만 실제 요청에는 대상 세션이 필요하다.

범위 선택과 권한 발급/철회를 구분한다. 선택을 바꿔도 자동 동의하거나 옛 grant를 새 범위로 옮기지 않는다. 범위 선택 변경 자체는 철회가 아니므로 남은 전체 grant를 목록에 **전체 허용 유지 중 / 철회**로 보인다. 버튼은 현재 선택 키만 철회하고 전체 철회 영향도 설명한다. 세션을 바꾸면 선택값은 기본 세션 한정으로 돌아가며, A의 허용을 B의 허용 상태로 표시하거나 전체 grant로 자동 fallback하지 않는다. 기존 A grant는 TTL/명시 철회까지 유지한다.

`PrivacyPanel.select_session(id | None)`로 GUI 선택을 표시한다. `DesktopAI.attach_privacy` 초기 동기화와 `selection`에서 연결한다. 현재 `ui/main.py:392`는 선택 없음이면 조기 반환하므로, attach에서 session list의 `currentItemChanged`에도 연결해 목록 비움/선택 해제를 반드시 None으로 전달한다. 동일 ID의 중복 통지는 idempotent하게 처리해 전체 범위 선택을 매번 초기화하지 않는다. 비동기/실시간 STT는 화면 선택과 실제 작업 세션이 다를 수 있으므로 **작업의 fixed_session**을 따로 인자로 전달한다. 현재 표시 세션 ID로 대체하지 않는다.

`prepare_execution(kind, session_id, cancel)`를 추가해 GUI thread에서 config·scope·현재 정책·bindings·config_key·ExecutionContext·Gateway를 **한 스냅샷**으로 만든다. capture 전에 기존 `bind_session(fixed_session, generation)`을 거쳐 삭제 fence에 등록하되 이미 철회된 세션을 다시 활성화하지 않는다. STT/요약 제출은 이 결과를 사용한다. 기존 `execution_context`는 `session_id` 필수 keyword를 추가하고, `gateway_for`는 주어진 작업 세션으로 캡처하는 보조 API로 유지한다. 둘을 개별 호출해 한 제품 작업을 조립하지 않는다. **G02A-05에 대한 C00의 계약 수정 결정:** 결과·checkpoint·admission·G-P03 settings_key에 쓰이는 `config_key`는 제공업체·모델/고정 artifact·endpoint/실행 위치·한도·기능·작업 세션으로 정한다. 동의 범위(kind/id)와 정책 version은 넣지 않으며 비밀도 넣지 않는다. 범위·정책·grant ID/epoch는 요청마다 새로 캡처한 binding에서 검사한다. 범위나 정책만 바꿨을 때 이미 처리한 실시간 청크의 중복 전송·비용과 요약 checkpoint 재개 상실을 막기 위한 분리다. 같은 결과 키가 옛 권한을 재사용하도록 허용하는 것은 아니다.

**G02A-01·02·06의 보강 계약:** 목록 재구성의 일시 None 뒤 같은 세션 ID가 돌아오면 범위 선택을 보존한다. 실제 다른 ID/선택 해제는 SESSION으로 돌아간다. 일시 None 동안 동의 버튼과 실행 준비는 차단한다. 탐색은 세션을 bind하지 않고 read-only `scope_view`로 상태만 조회한다. 같은 프로세스 coordinator는 try-acquire, 독립 SQLite read transaction은 timeout=0으로 읽으며 실행 권한으로 쓰지 않는다. 잠금 중이면 `확인 중 — 전송 불가`와 비활성 버튼을 먼저 표시하고 GUI timer로 재조회한다. 삭제·철회된 세션은 `삭제 진행 중 — 전송 불가`로 비활성화하되 상세·AI 패널 선택은 정상 갱신한다. 실제 bind는 실행 준비에서만 한다. 활성 grant의 만료는 사용자 현지 시각·UTC offset으로 표시하고, 비활성 grant는 철회됨/이전 실행/만료됨을 구분한다.

예약 closure도 같은 binding을 검사한 뒤에만 ledger.reserve를 수행한다. Worker는 GUI 값·vault를 다시 읽지 않는다. 현재 모델/endpoint/credential 변경 시 철회와 로컬 proof 고정·세대·guard 의미는 유지한다. 범위·만료·정책·철회 결과를 읽을 수 있는 label/accessible name과 키보드 이동을 제공한다. 이미 handoff된 bytes는 철회 후에도 취소를 보장할 수 없음을 표시한다.

예상 비용/가격 근거·상한 계산은 G-P06의 별도 S1이다. 이번 표시를 그 비용 요구 전체의 완료로 기록하지 않는다. 기존 cap·총액·UNKNOWN 및 네트워크 기본 거부를 유지한다.

### 2.5 기존 DB·실행·복원 처리

1. 지원 schema 확인 후 같은 transaction 안에서 v2/meta를 추가하고 새 실행 세대를 기록한다. 중간 실패는 rollback한다. 미래 schema나 부분 생성/불일치 schema는 추측해 복구하거나 덮어쓰지 않는다.
2. v1 `security_grants`의 범위/기능/정책은 알 수 없다. **v2로 복사하지 않고 새 동의를 요구**한다. v1 표는 이 단위에서 삭제하지 않으며 새 권한 조회는 v2만 사용한다.
3. 지금도 재시작 또는 다른 ConsentStore 생성으로 이전 실행 grant는 무효다(`consent.py:83`, `:106`). 따라서 옛 grant의 사용자 동의를 넓혀 보존할 호환 요구가 없다. schema를 추가했다는 이유만으로 실행 경계를 제거하지 않는다.
4. v2 재시작·백업 복원/복사도 새 실행 세대 때문에 옛 동의가 되살아나지 않는다. 여기서 복원은 사본을 새 Store로 여는 경로이며 실행 중 DB 파일을 덮어쓰는 복원을 승인하는 계약이 아니다. 오래된 DTO/permit의 누락 필드를 기본 전체로 채우지 않는다. 런타임 정책 증가 후 낮은 정책으로 여는 것도 거부한다.
5. 기존 `security_sessions` 삭제 세대·tombstone, local endpoint 증명, CostLedger/UNKNOWN/witness는 보존한다. Library DB와 같은 파일로 사용하는 기존 시험 구성도 동작해야 하며 user_version을 consent schema 2로 올리지 않는다(`security/_core.py:219`의 지원 범위 유지).
6. 구버전 실행 파일로 되돌렸을 때 구버전 코드의 권한 모델 자체가 고쳐지는 것은 아니다. 동시 실행은 기존 실행 세대 교체 때문에 먼저 열린 인스턴스를 fail closed시킨다. 구버전 배포 차단·전체 저장소 rollback 방지는 이 단위에서 새로 보장하지 않는다.

## 3. 유한 대표 공간과 독립 oracle

모든 수는 **계획 분모**다. 실제 실행 0, 실제 pytest node 수 미확정이다. case ID와 pytest node는 같지 않다. 아래 집합 이름을 ID prefix로 사용해 교집합 없는 ID registry를 만든다. 같은 행동이 다른 가족에서도 관측되는 것은 의도한 다층 확인이며 제품 전체의 서로 다른 18,433개 상황을 증명한다는 뜻이 아니다.

Fixture는 OS TEMP의 합성 SQLite·가짜 clock/transport/response/vault뿐이다. A/B는 서로 다른 정상 session ID이며 같은 라이브러리에 bind한다. 이 등록은 권한 부여가 아니다. 정상 cloud 시험은 가짜 ledger·credential 조건을 준비하고 실제 네트워크/DNS/socket/WinCred에 도달하면 실패시킨다. 로컬 proof 회귀는 가짜 증명을 쓴다.

기대값은 제품의 key 생성·allowed·validate·decision helper를 import하거나 호출해 만들지 않는다. 손으로 쓴 아래 표와 작은 집합/정수 상태 모델이 oracle다. 실제 결과는 **ConsentStore/진짜 Gateway + fake transport**에서 얻는다. 제품이 거부할 입력과 순서를 분모에서 빼지 않는다.

### 3.1 GATE: 권한 결합 결정, Ω=F=9,216

| 인자 | 대표 값 수/내용 |
| --- | --- |
| grant 범위 | 2: SESSION(A), LIBRARY |
| 요청 세션 | 2: A, B |
| grant 기능 × 요청 기능 | 3×3: stt/summary/diarization 각각 |
| provider / endpoint / 데이터 | 각 2: 일치/불일치 |
| 정책 / 실행 세대 | 각 2: 현재/다름 |
| grant 상태 | 4: 없음/활성/철회/만료 |
| 요청 삭제 상태 | 2: 살아 있음/삭제 fence commit |

분모: `2×2×3×3×2^5×4×2 = 9,216`. 제외 0. 없음은 empty captured tuple, 나머지는 활성 상태에서 capture한 뒤 필요한 상태 변경을 적용한다. 실행 변화와 정책 불일치의 교차도 별도 raw 요청 문맥을 보존해 구성하며 미리 실패한 것을 이유로 row를 제외하지 않는다. endpoint 불일치는 `https://a.example.test/v1`와 `/v2`처럼 정상 URL 두 개, 데이터 대표는 audio/transcript, provider는 정상 식별자 두 개다. 모든 연결은 fake다.

손으로 정한 허용 집합:

| 조건 | 허용 |
| --- | --- |
| SESSION(A) → A | 다른 조건이 모두 참이면 허용 |
| SESSION(A) → B | 항상 거부 |
| LIBRARY → A 또는 B | 다른 조건이 모두 참이면 허용 |
| 기능·provider·endpoint·데이터·정책·실행 중 하나라도 다름 | 거부 |
| 없음/철회/만료/삭제 fence | 거부 |

허용 분자: `3개 범위-대상 쌍 × 3개 동일 기능 쌍 = 9`, 거부 9,207. 정상 요청 본문은 한 write로 고정한다. 허용이면 fake open/write 각 1, 거부면 open/write/실제 socket 모두 0이다. 다중 실패는 §2.3의 phase와 진단 순서로 비교한다. Store permit까지 진입 가능한 형식의 row는 그 결정도 대조하고, 캡처 없음/재지정 거부 row는 Gateway의 선행 거부를 기록한다. 이 대표 cube 하나가 모든 실제 식별자 문자열·타입을 전수 검증한다는 뜻은 아니다.

### 3.2 PICK: 명시 범위 선택·fallback 금지, Ω=F=288

grant 집합 6 × 요청 A/B 2 × 선택 SESSION(요청 세션)/LIBRARY 2 × 기능 3 × 데이터 4(audio/transcript/context/attachment) = **288**, 제외 0. 현재 정책·실행, 정상 session이며 기능·데이터는 정확히 맞춘다. 선택 SESSION(B)도 없다고 row를 제외하지 않는다.

| 준비된 grant 집합 | SESSION(A) 요청 | SESSION(B) 요청 | LIBRARY→A | LIBRARY→B |
| --- | --- | --- | --- | --- |
| 없음 | 거부 | 거부 | 거부 | 거부 |
| A만 | 허용 | 거부 | 거부 | 거부 |
| 전체만 | 거부 | 거부 | 허용 | 허용 |
| A와 전체 | 허용 | 거부 | 허용 | 허용 |
| A 철회·전체 활성 | 거부 | 거부 | 허용 | 허용 |
| A 활성·전체 철회 | 허용 | 거부 | 거부 | 거부 |

허용 `9×3×4 = 108`, 거부 180. 이 표는 제품 lookup이나 scope helper에서 가져오지 않는다.

### 3.3 BIND: binding 신선도, Ω=F=576

범위 2 × 기능 3 × 데이터 4 × binding 상태 6 × 검증 경계 4 = **576**, 제외 0. 요청은 A다. 상태는 현재/옛 grant ID/옛 epoch/옛 실행/다른 scope key/옛 정책, 경계는 open/첫 write/다음 write/응답 반환이다. 활성 grant에서 capture한 뒤 실제 grant/세대/정책 전이 또는 fixture의 단일 필드 변경으로 오래된 DTO를 구성한다. 새 grant는 필요한 곳에 존재시켜 ‘새 grant 없음’만으로 우연히 검출하지 않게 한다.

현재 binding의 96행만 허용, 나머지 480행은 해당 경계 이후 새 동작을 거부한다. 첫 write 뒤 실패는 이미 건넨 bytes와 UNKNOWN을 유지한다. 라이브러리 범위에서도 요청 session_generation을 비교한다.

### 3.4 FROZEN: 요청 재지정 금지, Ω=F=504

범위 2 × 기능 3 × 데이터 4 × 변경 7 × 개입 경계 3 = **504**, 제외 0. A로 캡처한 정상 계획에 변경 없음/요청 A→B/기능 변경/데이터 변경/endpoint 변경/선택 범위 변경/정책 변경을 적용한다. 경계는 예약 전/open 전/첫 write 전이다. 다른 세션·기능·endpoint·범위의 grant도 실제로 준비해 두고, 정책 증가에는 새 정책 grant까지 준비한다.

변경 없음 72행만 허용, 나머지 432행은 옛 view/closure/permit을 바꿔 쓰려 하면 거부한다. 새 문맥으로 **새 capture**한 정상 요청과 대조한다. 새 capture의 허용은 옛 계획이 살아났다는 뜻이 아니다. mutable 속성 직접 대입이 거부되는 경우도 성공적인 차단 관측으로 기록하고, 공개 `for_session`을 통한 재지정도 별도로 호출한다.

### 3.5 HB: 철회·만료·정책·세대 순서, Ω=F=180

대상 A, 범위 2 × 기능 3 × 무효화 사건 6 × 순서 5 = **180**. 사건 X는 정확한 grant 철회/세션 삭제 fence/clock을 grant 만료로 이동/정책 증가/새 실행/같은 키 재동의다. 마지막 재동의도 옛 binding을 무효화한다.

DAG는 `O(open) < W1(first handoff) < W2(next handoff) < R(result 반환)`이며 X와 독립인 chain이므로 linear extension은 정확히 5개다. X는 coordinator를 얻고 상태 변경을 commit한 시점이다. fixture는 barrier와 fake clock으로 실행하며 sleep으로 순서를 추측하지 않는다.

| 순서 | open 수 | handoff 수 | 사용자 결과 |
| --- | --- | --- | --- |
| X O W1 W2 R | 0 | 0 | 전송 전 거부 |
| O X W1 W2 R | 1 | 0 | 본문 전 거부 |
| O W1 X W2 R | 1 | 1 | 다음 단위 차단, UNKNOWN 유지 |
| O W1 W2 X R | 1 | 2 | 늦은 정상 반환 차단, UNKNOWN 유지 |
| O W1 W2 R X | 1 | 2 | 정상 완료 뒤 철회/무효화 |

한 handoff가 먼저 lock을 잡은 경우 그 안에 X의 commit을 삽입하는 순서는 원래 DAG 밖이다. 대신 X 대기가 먼저 시작돼도 handoff 완료 뒤 commit되는 기존 write-first barrier 회귀를 유지한다. 그 회귀를 위 180행을 추가 실행한 것처럼 합산하지 않는다. 이미 전달된 bytes 회수·서버 취소·예약 자동 반환은 oracle가 아니다. 후속 자동 재시도 0, UNKNOWN 과소계상/중복 계상 0을 확인한다.

### 3.6 TIME: 정확한 만료와 역행, Ω=F=72

범위 2 × 기능 3 × 검사 대상 2(grant 허용 조회/짧은 permit 검증) × 시각 3(T−1/T/T+1초) × clock 2(정상/마지막 관측보다 역행) = **72**. grant는 TTL=60초, permit은 30초로 두고 각 대상의 T를 쓴다. 만료 시각과 같은 시각은 거부한다. 역행은 검사 직전 더 큰 시각을 관측한 뒤 되돌려 구성한다. 과거로 되돌아갔다고 만료/철회된 권한을 살리지 않는다. 정상 시계·T−1의 12행만 허용한다. NaN/Inf 등 기존 시계/TTL 음성 시험은 별도 기존 회귀다.

### 3.7 TRACE: 제한 상태 모델, Ω=F=7,381

alphabet은 9개 `{grant_A, grant_LIBRARY, capture_A, capture_B, revoke_A, revoke_LIBRARY, expire, advance_policy, restart}`다. 길이 0~4의 모든 명령열을 구성한다: `Σ(9^k, k=0..4)=1+9+81+729+6561=7,381`. 잘못된 순서도 거부 결과가 있는 유효 fixture이므로 제외하지 않는다. 길이 4는 grant→capture→revoke→regrant의 옛 계획 부활을 포함한다.

모델은 각 grant key의 허용/만료/ID/epoch, 현재 정책·실행, A/B에 보관한 **마지막 capture**를 따로 가진다. capture는 fixture가 명시적으로 선택한 범위로 수행하며, 여기서는 A가 SESSION(A), B가 LIBRARY를 선택한다. 매 prefix에서 두 옛 capture 검증과 동일 문맥의 새 capture 허용 여부를 관측한다. grant 이전 capture의 거부도 기록한다. 실행/정책 증가와 재동의는 보관된 capture를 고쳐 쓰지 않는다. grant를 조회해 기대값을 계산하지 않는다.

registry는 prefix를 한 번만 실행하는 trie 또는 각 trace의 독립 fixture 중 하나를 사용하되 관측 ID는 중복 없이 7,381개다. 영속 DB를 쓰고 오래된 Store 자원을 닫는다. restart에는 모델의 현재 정책 version을 명시적으로 전달한다. 더 낮은 version의 재시작 거부는 MIG11이 담당한다. 더 긴 이력·무제한 상태 공간의 증명이 아니다. session 삭제는 GATE/BIND/HB와 기존 삭제 회귀로 따로 교차하며 이 alphabet의 제10 사건으로 몰래 넣지 않는다.

### 3.8 UI: 182행

| 집합 | 분모 | 독립 기대 |
| --- | --- | --- |
| UI-ACTION | 선택 없음/A/B 3 × STT/요약 2 × 선택 범위 2 × 준비 grant 없음/A/전체/둘 다 4 × 동의/철회/context 생성 3 = 144 | SESSION·미선택은 동의/철회 불가, context는 범위와 무관하게 미선택 거부. 전체 동의는 별도 확인 YES인 fixture. context 허용은 SESSION A의 4행 + LIBRARY A/B의 8행, 합계 12 |
| UI-CANCEL | 선택 3 × 기능 2 × 전체 확인 취소/Esc 2 = 12 | 발급·재동의·epoch·vault 무변경 |
| UI-SNAPSHOT | 범위 2 × 기능 2 × 변경 3 × 변경 시점 2 = 24 | 고정 작업 A, 화면 선택 A→B/범위 선택 전환/정책 증가를 capture 전후에 적용. 표시 세션을 job A로 대체하지 않음 |
| UI-DEFAULT | 기능 2 = 2 | 세션 한정 기본, 자동 grant·실제 vault 읽기·네트워크 없음. 실제 bridge attach 후 A 선택→목록 선택 해제에서도 표시 None/세션 동의 비활성 확인 |

UI-SNAPSHOT에는 관련 두 범위의 정상 grant를 준비한다. 화면 선택 변경은 작업 A의 문맥을 B로 바꾸지 않는다. 범위 선택 변경이 capture 전이면 새 선택 키, 이후면 옛 불변 키다(선택은 철회가 아님). 정책 증가는 전/후 모두 새 정책 grant를 추가하되 capture 전이면 새 문맥, 이후면 옛 문맥 거부다. 모든 UI 행은 offscreen·가짜 vault로 실행한다. label·accessible name·현재 범위/만료/정책·전체 잔여 grant 표시도 assertion에 포함한다.

### 3.9 MIG와 TYPE: 명시 목록 12 + 22

MIG는 Cartesian 축이 아닌 다음 **서로 다른 fixture 12행**이다: 01 새 DB·동의 없음 / 02 v1 허용 grant 있음·v2 승계 0 / 03 v2 재시작 무효 / 04 동일 키 재동의가 옛 capture를 살리지 않음 / 05 옛 필드만 있는 DTO 거부 / 06 미래 consent meta schema 거부·DB 불변 / 07 부분 v2 schema 거부·무추정 / 08 schema transaction 장애 rollback / 09 공유 DB의 ledger UNKNOWN·witness·user_version 보존 / 10 복사·복원 사본 새 실행에서 동의 부활 없음 / 11 현재 정책보다 낮은 version 거부·같은 version no-op / 12 명시 전체 동의 뒤 A 삭제는 A 차단·B 새 capture 유지. 기존 future user_version 거부 회귀도 유지한다.

MIG11은 정책 1로 시작해 2 증가·1 감소 거부·2 동일 no-op·SQLite 양의 정수 최댓값(2^63−1) 증가·동일 no-op·최댓값+1 거부를 순서대로 관측한다. 0/−1은 TYPE에 있다. 이들은 MIG11의 명시된 단일 상태열 안의 assertion이며 별도 row 실행으로 중복 합산하지 않는다.

TYPE 22행의 입력은 각각 하나만 바꾼다: 01 알 수 없는 scope kind / 02 SESSION ID=None / 03 SESSION ID 빈 문자열 / 04 SESSION ID 경로형 / 05 LIBRARY scope_id 비어 있지 않음 / 06 scope=None / 07 capability=None / 08 capability=download / 09 capability=STT(대문자) / 10 policy=True / 11 policy=0 / 12 policy=−1 / 13 policy='2' / 14 policy=None / 15 요청 session=None / 16 요청 session 빈 문자열 / 17 요청 session 경로형 / 18 session_generation=True / 19 generation=−1 / 20 generation='0' / 21 policy=2.0 / 22 generation=None. 정책 상한은 SQLite 정수 범위로 검증하고 기존 identifier/overflow 회귀도 유지한다. malformed scope/문맥은 DTO 생성 또는 공개 API 경계에서 거부하며 grant/ledger 무변경·연결 0이다. `None`을 전체나 현재 세션으로 보충하지 않는다.

### 3.10 분모 확인과 배치

| 집합 | Ω | F | 허용 분자(해당되는 가족만) | 제안 계층 |
| --- | ---: | ---: | ---: | --- |
| GATE | 9,216 | 9,216 | 9 | property / 실제 store+gateway 결정 cube |
| PICK | 288 | 288 | 108 | property / 명시 lookup |
| BIND | 576 | 576 | 96 | property / 신선도·경계 |
| FROZEN | 504 | 504 | 72 | integration / 예약·요청 view |
| HB | 180 | 180 | 순서 표 | integration / barrier |
| TIME | 72 | 72 | 12 | unit / clock 경계 |
| TRACE | 7,381 | 7,381 | 상태 이력별 | property / 영속 상태 모델 |
| UI | 182 | 182 | 동작별 | UI / offscreen |
| MIG | 12 | 12 | 행별 | unit / 실제 TEMP DB |
| TYPE | 22 | 22 | 0 | unit / 입력 경계 |
| **합계** | **18,433** | **18,433** | 합산하지 않음 | **계획이며 실행 수 아님** |

모든 가족에서 Ω=F, fixture 불가능 제외는 현재 0이다. 구현하면서 불가능성이 발견되면 이유·원 row ID·대체 관측·독립 검토를 남기고 승인 없이 분모를 줄이지 않는다. registry의 가족별 수/유일 ID/누락 0을 제품 코드와 별개 상수·산식으로 대조한다. SQLite fixture를 여러 row에 재사용하면 상태가 섞이지 않는 초기화 경계를 기록한다. 성능 때문에 축약하려면 먼저 C00와 독립 검토에서 새 분모를 승인받는다. pytest parameter 수나 loop assertion 수를 위 분모와 혼동하지 않는다.

추가할 node 이름은 다음과 같다. **아직 존재하지 않는 계획 node**이며 DONE의 증거가 아니다.

| 파일 | 계획 node와 가족 |
| --- | --- |
| `tests/property/test_consent_scope_case_space.py` | `test_scope_manifest_is_complete`(registry), `test_authorization_case_space`(GATE), `test_selected_scope_case_space`(PICK), `test_binding_freshness_case_space`(BIND), `test_bounded_consent_traces`(TRACE) |
| `tests/integration/test_consent_scope.py` | `test_captured_request_cannot_be_retargeted`(FROZEN), `test_invalidation_handoff_orders`(HB) |
| `tests/unit/test_consent_scope.py` | `test_exact_consent_time_boundaries`(TIME), `test_legacy_and_schema_cases`(MIG), `test_malformed_scope_context`(TYPE) |
| `tests/ui/test_consent_scope_ui.py` | `test_scope_actions`(UI-ACTION), `test_library_confirmation_cancel`(UI-CANCEL), `test_scope_snapshot_is_fixed`(UI-SNAPSHOT), `test_session_default_and_selection_clear`(UI-DEFAULT) |

문서 작성 중 제품을 import하지 않는 Python 표준 라이브러리 계산으로 위 산식 합계 18,433, GATE 대표 직적의 허용 분자 9, 손으로 쓴 PICK 표의 허용 분자 108을 재계산해 일치를 확인했다. 이는 **문서 산술 확인**이며 제품 registry나 제품 시험을 실행한 결과가 아니다.

## 4. 기존 시험과의 관계

아래 node의 **존재와 assertion 범위를 읽어 확인**했다. 이번 단계에서 실행한 PASS가 아니다. 기존 grant/session/DTO fixture를 새 명시 문맥으로 갱신하되, 무전송·UNKNOWN·guard의 독립 기대값을 약화하지 않는다.

| 실제 기존 node | 유지할 의미 | 새 공간과의 차이 |
| --- | --- | --- |
| `tests/unit/test_security.py::test_expiring_consent_is_exact_and_invalid_after_restart` | 정확한 endpoint/data, TTL, 재생성 무효 | GATE/MIG가 세션·기능·정책을 추가 |
| 같은 파일 `::test_epoch_regrant_and_session_revocation_invalidate_permits`, `::test_frozen_grant_bindings_do_not_expand_or_revive` | 재동의/삭제 후 옛 permit·binding 차단 | BIND/PICK에서 전체와 세션 선택 구분 |
| 같은 파일 `::test_consent_clock_rollback_and_stale_execution_fail_closed`, `::test_session_deletion_evidence_blocks_already_issued_permit` | 시계 역행·세대·삭제 증거 | TIME/HB에서 새 범위 교차 |
| `tests/integration/test_gateway.py::test_revoke_before_first_or_second_handoff_blocks_unsent_bytes` | 철회 선행시 미송신 단위 차단 | HB의 철회-first 순서 |
| 같은 파일 `::test_write_first_finishes_before_revoke_commit_without_blocking_media_db` | write 선행·철회 대기·media DB 분리 | HB 양순서의 기존 핵심 회귀 |
| 같은 파일 `::test_real_process_restart_denies_old_consent_and_preserves_unknown`, `::test_frozen_gateway_rejects_regrant_after_reservation_before_permit` | 실제 subprocess 재시작·UNKNOWN, 예약 뒤 재동의 차단 | MIG/FROZEN과 함께 유지 |
| `tests/integration/test_egress_independent.py::test_committed_revocation_before_first_write_sends_no_body`, `::test_write_before_revocation_cannot_send_next_chunk_after_commit` | 독립 철회 양순서 | HB로 대체·삭제하지 않음 |
| 같은 파일 `::test_previously_ungranted_context_scope_cannot_widen_existing_gateway`, `::test_new_grant_cannot_revive_old_model_or_key_context` | 사후 grant 확대·모델/키 옛 계획 부활 금지 | 새 범위의 자동 fallback도 금지 |
| `tests/property/test_security_case_space.py::test_declared_finite_manifest_has_no_missing_or_duplicate_rows`와 기존 admission/handoff/time node | 기존 유한 분모·예산/헤더/취소 결합 | 기존 분모는 별도 보존. 18,433에 더해 재실행한 것처럼 기록하지 않음 |
| `tests/ui/test_privacy_ui.py::test_exact_datatype_consent_independent_settings_and_endpoint_change`, `::test_frozen_worker_scope_cannot_widen_or_outlive_revocation` | 기능 control 독립·설정 변경 철회·불변 closure | 실제 세션 선택·정책 표시가 추가됨 |
| 같은 파일 `::test_frozen_managed_proof_protects_every_privacy_gateway_boundary` | 로컬 proof·매 경계 guard | 범위 추가로 local proof 검사를 우회하지 않음 |

`test_default_gateway_blocks_before_dns`와 Ollama 기본 거부 node도 그대로 유지한다. 기존 unbound 성공 fixture는 정상 명시 session/scope/capture를 준비하는 fixture로만 바꾸며, 무동의 요청 성공으로 기대값을 바꾸지 않는다. 독립 검토자가 작성한 기존 파일은 API 적응 diff만 따로 검토받는다.

## 5. mutation 계획 — 전부 NOT_RUN

정상본이 목표 시험을 통과한 뒤 OS TEMP의 고유 소스 사본에서 mutant를 **한 개씩** 적용한다. pyproject/src/tests를 함께 복사하고 그 cwd에서 pytest를 실행해 실제 작업 트리 import를 피한다. 소스 hash·import 경로·실패 node·case ID를 기록한다. import/수집 오류·timeout·권한 실패만 난 것은 검출이 아니다.

| ID | 의도한 결함 | 잡아야 할 독립 관측 |
| --- | --- | --- |
| M01 | SESSION ID 비교 제거 | GATE SESSION A→B, open=0 위반 |
| M02 | SESSION 실패시 LIBRARY 자동 fallback | PICK의 전체만/SESSION, A 철회·전체 활성 |
| M03 | capability를 key에서 제외 | GATE의 다른 기능, TYPE 대문자/다운로드 |
| M04 | policy version 검사 제거 | GATE 정책 다름, HB 정책 증가 |
| M05 | 실행 세대 검사 제거 | MIG 재시작/복사, GATE/HB 세대 |
| M06 | grant ID 또는 epoch 재검사 제거(각각 별도 변이) | BIND 옛 ID/epoch, TRACE 재동의 |
| M07 | `now < expires`를 `<=`로 완화 | TIME의 정확한 T |
| M08 | LIBRARY이면 요청 삭제 fence 생략 | MIG12·GATE 삭제·HB 삭제 |
| M09 | 전체 binding의 요청 세션 재지정 허용 | FROZEN A→B, 새 B capture 대조 |
| M10 | 다음 write의 validate 제거 | HB O W1 X W2 R, handoff=1 위반 |
| M11 | 최종 반환의 validate 제거 | HB O W1 W2 X R, 늦은 성공 반환 |
| M12 | UI 기본을 전체로 변경 또는 전체 확인 생략(별도 변이) | UI-DEFAULT·UI-CANCEL |
| M13 | v1 grant를 LIBRARY/현재 기능/정책으로 자동 이관 | MIG02의 v2 grant 행 수 0·무전송 |
| M14 | reservation closure가 캡처 대신 현재 binding 재조회 | FROZEN 예약 전 정책/기능/범위 변경에서 ledger.reserve 0 |
| M15 | prepare_execution에서 fixed_session 대신 현재 표시 세션 사용 | UI-SNAPSHOT의 화면 A→B |

변이 실행은 최소 17개(M06 두 개, M12 두 개) 계획이다. 실제 적용 diff가 목표 결함을 만들었는지 먼저 검토하며 equivalent/survived/invalid를 구분한다. 이 숫자는 전체 프로젝트 mutation coverage가 아니다.

## 6. 승인 요청하는 정확한 구현 쓰기 범위

**아래는 다음 단계 제안이며 지금의 쓰기 허용이 아니다.** 새 공용 설정·dependency·provider 네트워크 경로는 필요 없다.

| 파일 | 허용하려는 변경 |
| --- | --- |
| `src/recoryn/security/consent.py` | v2/meta·DTO·정책/범위·grant/capture/permit API |
| `src/recoryn/security/gateway.py` | 불변 요청 문맥·정확한 binding·매 경계 검증 |
| `src/recoryn/security/__init__.py` | 새 DTO/정책 상수 export |
| `src/recoryn/ui/privacy.py` | 범위/만료/정책 표시·확인·API 적응·단일 실행 스냅샷 |
| `src/recoryn/ui/ai_bridge.py` | **attach_privacy/selection 및 STT·요약 준비 호출부만**. 화자 구분 게시·G03 CAS 변경 불가 |
| `tests/unit/test_consent_scope.py` (신규) | TIME/MIG/TYPE·schema/API |
| `tests/property/test_consent_scope_case_space.py` (신규) | GATE/PICK/BIND/TRACE·분모 registry |
| `tests/integration/test_consent_scope.py` (신규) | FROZEN/HB·가짜 전송·예약 |
| `tests/ui/test_consent_scope_ui.py` (신규) | UI 182행·표시/스냅샷 |
| `tests/unit/test_security.py` | 기존 grant/DTO fixture API 적응·기존 assertion 유지 |
| `tests/property/test_security_case_space.py` | 기존 명시 문맥 fixture 적응·기존 oracle/분모 유지 |
| `tests/integration/test_gateway.py` | 정상 명시 문맥 fixture·기존 철회/UNKNOWN/guard 유지 |
| `tests/integration/test_egress_independent.py` | 새 API fixture만 적응·독립 무전송 기대 유지 |
| `tests/integration/test_provider_security_independent.py` | 동일 |
| `tests/integration/test_publication_independent.py` | 실제 Gateway를 쓰는 예약 fixture만 적응·게시 oracle 불변 |
| `tests/integration/test_ai_independent.py` | privacy session/capture fixture만 적응·G03 게시 시험 불변 |
| `tests/contract/test_provider_contracts.py` | 실제 Gateway fixture만 적응·어댑터 request 계약 불변 |
| `tests/ui/test_privacy_ui.py` | 선택 세션/새 API fixture 적응·기존 endpoint/proof/vault 기대 유지 |
| `docs/testing/g02-consent-scope-cases.md` | 승인 결정·실행/변이/독립 검토 결과 추기 |

합계 19파일(제품 5, 신규 시험 4, 기존 시험 9, 문서 1). 호출 검색은 `rg -l 'ConsentBinding|SendPermit|capture_bindings|\.grant\(|\.revoke\(|\.allowed\(|\.for_session\(' src tests`와 Gateway/ConsentStore/Privacy API 검색으로 수행했다. `cli.py`는 삭제시 Store 생성, `ui/main.py`는 생성/attach, `app/ai.py`는 기존 ExecutionContext 소비라 서명 유지로 수정 불필요하다. `tests/integration/test_ollama_runtime_independent.py`는 unbound 기본 거부를 유지하므로 수정 없이 회귀 실행 대상이다. 구현 중 새 호출자가 필요해지면 목록 밖 수정 전에 C00가 재배정한다.

**파일 공유 경계:** 현재 G03이 `ui/ai_bridge.py`의 화자 구분 게시만 수정 중임을 배정표와 `git diff`에서 확인했다. 위 연결부는 다른 함수지만 파일 단위 공유 승인이 필요하다. C00가 G03 파일 반영 뒤 G02가 수정하도록 순서를 정하거나 함수별 동시 소유를 명시해야 한다. 기존 G03 변경을 덮어쓰지 않는다. `app/ai.py`·`content/store.py`는 G02 쓰기에서 제외한다. B10 등의 공용 문서 정합과 배정표 변경은 C00 소유다.

## 7. 대안·수락 기준·현재 한계

| 대안 | 장점 | 단점/제안 |
| --- | --- | --- |
| SESSION만 제공 | 최소 권한·schema/UI 단순 | 반복 동의 부담, 사용자가 정한 전체 범위 미제공. 보수적 축소안으로 가능 |
| **SESSION 기본 + 명시 LIBRARY** | 설계 범위 선택 제공, 반복 작업 지원 | UI 고지·선택/철회·fallback 금지 시험 증가. 본 제안 |
| 누락 scope를 전체로 간주/옛 grant 자동 이관 | 호출 변경이 적음 | 옛 모호한 동의를 확대하므로 채택 불가 |
| UI에서만 session 제한 | 제품 화면 수정이 적음 | Gateway/다른 호출자가 우회하므로 채택 불가 |
| 기존 grants 표 재구축 | 표 하나로 통일 | 기존 PK 변경·복구/공유 ledger 위험. additive v2가 안전하며 잔여 v1 정리는 후속 migration으로 |
| Windows 사용자 전역·다중 라이브러리 grant | 범위가 넓어 반복 동의 감소 | 계정/라이브러리 신뢰 경계와 새 수명 계약 필요. G02에서 제공하지 않음 |

C00은 ① 기본 SESSION·명시 LIBRARY 의미와 UI 확인, ② 필수 문맥 API·기능/정책·단일 스냅샷, ③ additive v2/meta·v1 미승계·정책 증가·감소 거부, ④ 계획 분모와 시험/변이 범위, ⑤ 정확한 19파일을 승인했다. `CONSENT_POLICY_CHANGED` 신설도 승인됐다. 새 시험 4파일의 합계 실행 시간이 이 PC에서 60초를 넘으면 축약 전에 측정값과 축약안을 보고한다. 보안·privacy·시험을 먼저 진행하고 G-P03 커밋 완료 신호 뒤에만 ai_bridge 연결을 마무리한다.

승인 후 수락 조건은 원 P1의 **A 동의→B 차단** 및 명시 전체의 A/B 허용을 독립 fake로 대조하고, 18,433 case ID의 누락/중복 0과 기존 회귀를 확인하는 것이다. 목표 mutant는 모두 유효한 assertion으로 검출하거나 독립 검토에서 미검출 위험을 결정해야 한다. 관련 ruff/format/mypy와 선택 시험, 이후 C00의 정확한 통합 tree 검증을 구분한다. 시험은 `-p no:cacheprovider`, OS TEMP의 새 `--basetemp`, `QT_QPA_PLATFORM=offscreen`, bytecode 억제로 수행하고 실제 device/model/network/vault는 열지 않는다.

위 절까지는 승인받은 계약·계획이다. 승인 뒤 직접 실행한 구현/시험/변이는 아래 절에 구분한다. 무제한 사용자/세션 문자열, 길이 4 초과 이력, 구버전 실행 파일의 보안성, 외부 loopback 프로세스 후속 전송은 이 유한 검증의 보장이 아니다. 새 기능 화자 원격 전송·첨부 업로드·비용 상한·전체 migration을 완료했다고 확대하지 않는다.

## 8. PHASE1 구현과 직접 검증

2026-11-23, w5:p8 Codex. **보안·privacy·시험 단계 완료, G-P03 커밋 완료 신호 대기**다. `src/recoryn/ui/ai_bridge.py`는 아직 수정하지 않았다. 아래는 작업 트리의 직접 실행 결과이며 독립 검토·정확한 통합 tree·제품 전체 완료가 아니다.

### 8.1 구현과 쓰기 경계

§6의 19파일 중 **ai_bridge.py를 뺀 18파일**을 변경했다. 실제 제품 변경은 security 3파일과 ui/privacy.py 1파일이며, 신규 시험 4·기존 fixture/API 적응 9·이 문서 1이다. app/ai.py·content/store.py·ui/main.py와 다른 문서는 수정하지 않았다. ai_bridge.py는 시작 때 저장한 raw bytes와 동일함을 직접 대조했다.

- `security_grants_v2`와 `security_consent_meta` 추가를 하나의 transaction으로 처리하고 v1 행을 승계하지 않는다. 실행 세대·삭제 fence·기존 CostLedger·witness·user_version을 유지한다. scope와 요청 문맥을 frozen DTO로 표현하며, 기능·정책은 불변 ConsentRequest에서 읽어 중복 필드가 어긋나지 않게 했다.
- grant/capture/permit에 명시 문맥을 요구한다. 범위 fallback이 없고 캡처한 view는 다른 세션/기능/범위/정책으로 다시 바인딩하지 못한다. permit 발급·매 검증 경계의 scope/request·grant ID/epoch 검사를 결합했다. 원본 전송의 GatewayLike.request 서명과 기존 lock 순서는 유지했다.
- privacy에 기본 세션 한정/명시 라이브러리 선택, 남아 있는 전체 허용 표시, 범위·정책·만료 표시 및 전체 확인 창을 구현했다. prepare_execution은 설정·bindings·context·Gateway를 한 번에 고정한다. local faster-whisper의 inert context는 동의와 독립이다.
- 확인 창에서 표시한 만료가 대화 시간만큼 연장되지 않도록 `grant_deadline` 미리보기와 `grant(..., expires_at=...)`를 추가했다. UI는 표시한 절대 시각을 전달하며, 승인 도중 만료됐으면 발급하지 않는다. 이 선택은 범위 확대가 아닌 고지 시각 보존이며 아래 보강 시험 4개로 확인했다.
- 기존 시험은 명시적 LIBRARY fixture를 선택해 옛 전역 동의 의미 아래의 철회/UNKNOWN/guard oracle를 보존했다. 권한 등록은 삭제 fence 검사이며 grant가 아님을 helper에 명시했다. 새 권한 뒤 옛 adapter가 자동 확대되지 않음을 추가 확인하고, 새 사용자 계획에 대해서만 새 Gateway/adapter를 만든다. bind_session의 기존 INVALID_SESSION_GENERATION과 손상된 기존 schema의 SECURITY_STATE_UNAVAILABLE 코드는 보존했다.

### 8.2 분모·실제 실행·대기 행

계획 분모 **18,433은 변경하지 않았다.** registry는 가족별 독립 상수와 실제 ID 목록을 대조하며 누락/중복 0이다. GATE는 실제 9,216행·허용 9, PICK 288행·허용 108, BIND 576행·허용 96을 assertion으로 대조했다. TRACE는 길이 0~4의 **7,381개 ID 모두**를 trie에서 한 번씩 관측했다.

현재 완료된 대표 행은 **18,431/18,433**이다. UI-DEFAULT 2행의 bridge 연결 검사는 G-P03 신호 뒤에 마무리하므로 명시적 SKIP으로 남겼다. 신호 뒤 선택 A→목록 비움/None 전달을 확인하고 SKIP을 제거한다. 이 두 행을 완료로 세지 않는다.

기본 matrix 외 보강은 원 P1 대조 node 1개와 확인 창 만료 보존 4개다. 후자는 STT/요약 × 대화 1,800/3,600초의 fake clock으로, 표시한 4,600초 절대 만료를 보존하거나 만료 후 발급을 차단한다. registry 검증 node 자체도 대표 행 분모에 합산하지 않는다.

실행 증거 루트는 `C:/Users/gangd/AppData/Local/Temp/recoryn-g02-0qz6fhhj`(이하 R)다. 모두 기존 venv, `-B`, offscreen, bytecode 억제, `-p no:cacheprovider`, 새 OS TEMP basetemp를 사용했다.

```powershell
# cwd: D:/project/Recoryn. R은 위 절대 경로의 축약 표기다.
.venv/Scripts/python.exe -B -m pytest tests/unit/test_consent_scope.py tests/property/test_consent_scope_case_space.py tests/integration/test_consent_scope.py tests/ui/test_consent_scope_ui.py -q -p no:cacheprovider --basetemp R/new-four-phase1 --junitxml R/new-four-phase1.xml --durations=6 --tb=short
```

직접 최종 결과: **980 passed, 2 skipped in 50.80s / exit 0**, 경고·실패·xfail 없음. 60초 예산 이내다. 환경 부하가 다른 실행까지 이 시간을 보장한다는 뜻은 아니다.

시간 예산을 넘은 측정과 변경도 이력으로 남긴다. 첫 개별 합계는 UI 전 85.49초, 첫 4파일 합산은 976 PASS·2 SKIP/74.73초였다. 다른 회귀를 병행한 140.47초는 단독 CI 시간으로 쓰지 않았다. 이후 단독 58.72초, 81.96초, 61.08초를 각각 관측·보고했고, 다음과 같이 **행과 assertion을 줄이지 않고** 준비 비용을 줄였다.

1. TRACE를 독립 명령열의 반복 실행에서 공통 prefix trie로 전환했다. 정상 branch는 savepoint로 격리하고 재시작 branch는 SQLite.serialize 결과를 새 TEMP DB에 써 실제 ConsentStore로 연다. 820개 재시작 edge를 실행했다. 부모 Store는 다른 이력에만 쓰며 실제 한 실행의 살아 있는 구 Store로 관측하지 않는다. 동일 파일/실제 subprocess 재시작은 MIG와 기존 회귀에서 별도로 유지한다.
2. TRACE alphabet이 filesystem 항목을 바꾸지 않는 조건에서, 검증한 불변 TEMP deletion-journal 부모 경로만 재사용한다. 실제 exists/tombstone/SQL 삭제 검사는 계속 실행한다. 다른 경로와 기존 reparse/path 변이 시험에는 이 fixture가 적용되지 않는다. SQLite·제품의 권한 helper를 fake oracle로 대체하지 않았다.
3. FROZEN의 저장소를 재사용하되 각 경우 전 grant/session/meta를 setup transaction에서 새 상태로 준비했다. 경우별 provider ID로 비용 계정을 격리하며 앞 경우의 UNKNOWN은 지우지 않는다. 독립 결정표 GATE/BIND를 직렬 관측하는 동안 정책 lock을 재사용해 반복 파일 lock 준비를 줄였다. 실제 HB 경쟁 시험은 별도 저장소와 실제 commit/Event 순서를 유지한다.

### 8.3 기존 회귀와 원 P1

§6 기존 시험 9파일과 **수정하지 않은** `tests/integration/test_ollama_runtime_independent.py`를 함께 선택 실행했다. 직접 결과 **529 passed in 52.56s / exit 0**이며 `R/regression-final.xml`에 남겼다. 철회 양순서·실제 subprocess 세대 무효화·UNKNOWN·endpoint/credential/proof 경계·provider 계약을 포함한다. 프로젝트 전체 시험 또는 Windows 실장비 결과가 아니다.

원 P1은 신규 `tests/integration/test_consent_scope.py::test_original_p1_session_denies_b_and_explicit_library_allows_both`에서 직접 확인했다. SESSION(A) grant 한 건 뒤 A만 보내고 B는 CONSENT_REQUIRED로 차단해 fake open=1·writes=[A]다. 별도 명시 LIBRARY grant와 새 A/B 계획 뒤 open=3·writes=[A,all,all]이다. 실제 DNS·네트워크는 없다.

### 8.4 mutation 실행

계획 M01~M15를 임시 사본에서 실행했다. M06 ID/epoch, M12 기본값/확인을 각각 나누고, M07의 grant/permit 만료도 따로 나눴다. 고지 만료를 버리는 M16을 추가해 **19개**다. 새 파일·구조 때문에 import/수집만 실패한 결과는 검출로 세지 않았다.

사본에 **pyproject·src·tests·scripts·packaging**을 함께 복사했다. `PYTHONPATH`와 pytest pythonpath가 사본 src를 가리키게 하고 실제 consent.__file__ 경로를 매 실행 확인했다. 정상본 선택 node PASS 후 각 변이를 한 번에 하나씩 적용했다. 기존 작업 트리·Git·실제 데이터에는 변이를 쓰지 않았다. 최종 시험 준비 최적화 뒤 같은 변이들을 다시 실행해 **정상 선택 8.389초 PASS, 19/19 KILLED, survived/invalid 0**을 직접 확인했다. 모두 testcase 실패이며 import/수집 오류는 0이다.

재현 script는 `R/recheck_mutations.py`, 최종 로그·명령·실패 node·import 경로·정상/변이 source SHA256은 `R/mutations-final/results.json`에 있다. 이 JSON의 LF SHA256은 **`0faa3bf541588f039f60c7c7e76de11bdd7aa23a2eab37b0d6fe5a55af8c39e1`**다. 실제 변이 사본과 diff는 `R/mutations-2/M*` 및 같은 루트의 `M*.diff.txt`에 보존했다. 최초 실행 도구의 evidence 폴더 이름 충돌은 시험 시작 전 중단된 도구 오류였으며 검출 수에 넣지 않았다.

| 변이 | 잡아야 하는 관측 |
| --- | --- |
| M01 세션 비교 제거 | GATE의 A grant→B 부정 행 |
| M02 전체 fallback 추가 | PICK의 명시 SESSION에서 allowed=False |
| M03 기능 키 상수화 | GATE 기능 불일치 |
| M04 현재 정책 검사 제거 | HB-015 정책 증가 후 미송신 |
| M05 실행 세대 검사 제거 | GATE의 구 Store 재사용 |
| M06-id / M06-epoch | BIND의 단일 ID/epoch 오염 |
| M07-grant / M07-permit | TIME-002 / TIME-008의 정확한 T |
| M08 전체 범위 삭제 fence 생략 | HB-097, 삭제 뒤 새 단위 |
| M09 view 재바인딩 검사 제거 | FROZEN-004, for_session의 즉시 거부 |
| M10 후속 write 검사 제거 | HB-002의 handoff 수 1 |
| M11 최종 반환 검사 제거 | HB-003의 늦은 정상 반환 차단 |
| M12-default / M12-confirm | UI-ACTION-000의 기본 SESSION / UI-CANCEL-00의 무발급 |
| M13 v1 자동 이관 | MIG-02의 v2 grant 수 0 |
| M14 현재 binding 재조회 | UI-SNAPSHOT-05의 예약 0 |
| M15 화면 선택으로 작업 세션 교체 | UI-SNAPSHOT-00의 고정 A |
| M16 표시한 deadline 전달 생략 | 보강 expiry[stt-1800]의 expires=4600 |

### 8.5 정적 검사와 인계

`ruff check --no-cache .`는 전체 저장소 읽기 검사로 PASS, `python -m mypy src/recoryn scripts packaging`는 **83 source files PASS**다. format 쓰기는 승인된 Python 17파일에만 적용했으며 ai_bridge.py를 포함하지 않는다. 같은 17파일의 최종 `ruff format --no-cache --check`도 **17 files already formatted / exit 0**이었다. Mypy cache는 마지막 실행에서 R/mypy-final로 분리했다.

G-P03 커밋 완료 신호 전까지 ai_bridge.py를 수정하지 않는다. 따라서 현재는 PHASE1_READY이며 전체 IMPLEMENTATION_READY가 아니다. 후속 단계는 attach/selection의 선택 해제 신호, STT·요약의 prepare_execution 사용, SKIP 2행 해제와 관련 bridge/UI 회귀다. Git 쓰기·기타 파일 수정·실제 장치/모델/네트워크/계정/vault 쓰기·설치는 수행하지 않았다. Claude의 독립 검토와 C00의 정확한 통합 tree 검증은 미완료다.

## 9. PHASE2 구현과 직접 검증

2026-11-23, w5:p8 Codex. C00의 **G-P02 2단계 시작 신호**를 받고 §6 범위에서 bridge 연결을 완료했다. §8은 PHASE1 당시의 이력이며 그때의 2 SKIP·대기 상태를 이번 결과와 구별한다. 아래 증거 루트는 **R2 = `C:/Users/gangd/AppData/Local/Temp/recoryn-g02-phase2-e60yyio5`**다. 실제 모델·장치·네트워크·유료 호출·계정·vault 쓰기·설치·하위 에이전트·Git 쓰기는 수행하지 않았다.

### 9.1 bridge 연결과 파일 공유 보존

- `attach_privacy`가 현재 선택을 즉시 privacy에 동기화하고, `sessions.currentItemChanged`에서 선택 해제/목록 비움도 None으로 전달한다. `selection`도 선택 세션을 전달한다. PrivacyPanel의 동일 ID 무변경 처리는 유지한다.
- STT는 화면의 현재 선택 대신 **fixed_session**으로 `prepare_execution`을 한 번 호출한다. 로컬 Whisper도 이 API에서 inert 문맥을 받아 기존 로컬 모델 준비 경로로 간다. 원격 STT는 같은 결과의 config·config_key·context·gateway를 함께 사용한다.
- 요약도 하나의 `prepare_execution` 결과만 사용한다. 기존 Ollama attestation 확인과 작업 취소 준비를 유지한다. GUI의 선택을 나중에 worker에서 다시 읽어 session이나 Gateway를 바꾸지 않는다.
- PHASE2 전후 DesktopAI의 메서드 AST를 대조해 **변경된 함수는 attach_privacy·selection·_transcribe·summarize 네 개뿐**임을 직접 확인했다. G-P03의 `diarize` 함수 AST와 화자 게시의 기대 전사 version 전달은 동일하다. `app/ai.py`·`content/store.py`·`ui/main.py`는 수정하지 않았다.
- 신규 UI 파일의 bridge 2 SKIP을 제거했다. 별도 보강 `test_bridge_submission_keeps_one_fixed_session_snapshot[stt/summary]` 2행은 실제 PrivacyPanel·실제 bridge 준비·실제 adapter·실제 Gateway와 fake 전송을 사용한다. STT는 화면 B/작업 A를, 요약은 준비 뒤 A→B 선택 변경을 강제한다. config/Gateway 객체·설정 키·예약 factory가 **같은 단일 스냅샷**인지와 A로만 fake write되는지 검사한다. worker 제출은 대기 action으로 제어하고 실제 모델을 실행하지 않는다.

### 9.2 정상본·분모·실행 시간

최종 새 시험 네 파일은 **984 passed in 40.19s / exit 0 / skip0**이다. 과거 2 SKIP은 둘 다 PASS로 바뀌었다. 계획의 **18,433행은 그대로**이며, GATE/PICK/BIND/TRACE의 loop 내부 행과 pytest node 수를 구분한다.

| 가족 | 계획 F | 직접 관측/대조 |
| --- | ---: | --- |
| GATE | 9,216 | 제품 Store/Gateway 결정 전수 loop의 고유 tuple 9,216·허용9 assertion PASS |
| PICK | 288 | 독립 손작성 허용표 대조·허용108 assertion PASS |
| BIND | 576 | 신선도·경계 loop·허용96 assertion PASS |
| FROZEN | 504 | JUnit의 504개 ID 모두 PASS |
| HB | 180 | JUnit의 180개 ID 모두 PASS |
| TIME | 72 | JUnit의 72개 ID 모두 PASS |
| TRACE | 7,381 | 깊이0..4의 고유 ID 집합 전체·실제 Store 재시작 가지820 assertion PASS |
| UI | 182 | JUnit의 UI 182개 ID 모두 PASS, UI-DEFAULT 2행 포함 |
| MIG | 12 | JUnit의 12개 ID 모두 PASS |
| TYPE | 22 | JUnit의 22개 ID 모두 PASS |
| 합계 | **18,433** | **등록 ID 누락/중복/추가0, skip0** |

pytest 984개는 unit106 + property5 + integration685 + ui188이다. 보강 원 P1 1개·확인 창 만료4개·bridge 고정 스냅샷2개 및 manifest node를 대표 행 분모에 더하지 않는다. `R2/audit_phase2.py`는 제품 predicate를 기대값으로 쓰지 않고 별도 상수/정수 ordinal·9진수 TRACE 복원으로 기대 ID 집합을 작성했다. registry 전체와 JUnit parameter ID를 대조했고, loop 네 개는 각 실제 PASS와 내부 고유 행/수치 assertion을 대조했다. **모든 loop 행의 ID가 JUnit에 따로 존재한다고 주장하지 않는다.**

실행 시간 예산의 관측 이력도 남긴다.

| 실행/조건 | 직접 결과 |
| --- | --- |
| bridge 연결 직후 작업 트리, 보강 bridge2 추가 전 | 982 PASS / 40.25s |
| G-P03+G-P02 격리 사본, bridge2 포함 | 984 PASS / **66.03s** |
| 같은 사본 직렬 재측정 | 984 PASS / **61.89s** |
| 아래 fixture 준비 최적화 뒤 같은 사본 | **984 PASS / 40.19s** |

66.03초와 61.89초의 예산 초과는 이 창에 먼저 보고했고, 분모/검사 축소는 하지 않았다. 변경은 **grant가 하나도 없는 UI fixture의 초기 값 여섯 개를 설정할 때만** signal을 묶고 마지막에 실제 `_changed`를 한 번 호출한 것이다. 빈 `_granted`와 DB grant0을 먼저 assertion한다. setup 이후 실제 선택·발급·철회·설정 변경 신호와 제품 handler는 모두 유지한다. 비용 ledger·witness·handoff 동작을 stub하지 않았다. 전체 시간 차이를 이 최적화만의 효과로 증명하지 않으며 실행 부하의 영향을 분리 측정한 것은 아니다. 마지막 측정은 60초 이내지만 모든 PC/부하에서의 상한 보장은 아니다.

```powershell
# cwd: R2/isolated, 기존 venv / bytecode 억제 / offscreen / offline
D:/project/Recoryn/.venv/Scripts/python.exe -B -m pytest tests/unit/test_consent_scope.py tests/property/test_consent_scope_case_space.py tests/integration/test_consent_scope.py tests/ui/test_consent_scope_ui.py -q -p no:cacheprovider --basetemp R2/n4-opt --junitxml R2/new-four-optimized.xml --durations=6 --tb=short
```

`R2/new-four-optimized.xml` LF SHA256은 **`f49a25ec74bb24f3b87f34a7c4c50e0979d3fe87a97c75219e7844f5a1e06b39`**, `R2/case-audit.json`은 **`dc8a6b5cff37ac72ec0b8a7e8314107af76c820df0500d7448cd9ed91e017d65`**다.

### 9.3 UI 전체·G-P03·원 P1

작업 트리에서 `tests/ui tests/unit/test_content.py tests/integration/test_selection_version_cas.py`를 함께 실행해 **543 PASS / 29.96s / skip0**을 직접 확인했다(`R2/ui-g03.xml`). 이때 bridge 보강2는 포함했고 UI 초기 setup 최적화 전이었다. 구성은 **UI 전체237 + content unit103 + G03 integration203**이다. UI237 중 새 scope UI188, 기존 UI49이며 **live UI10·GPU runtime UI4가 모두 PASS**다. C00이 지적한 live UI7건·GPU runtime UI4건의 결정적 실패는 bridge API 연결로 복구됐다. 해당 두 파일은 수정하지 않았고 추가 쓰기 권한도 필요하지 않았다.

PHASE1의 **529 PASS에는 이 두 파일이 포함되지 않았다.** 그 숫자를 UI 전체 회귀라고 해석하지 않는다. PHASE2는 위 전체 UI와 아래 정확한 사본 전체 회귀를 완료 조건으로 구분한다.

원 P1의 독립 fake 대조는 최종 네 파일 실행에서도 PASS했다. **SESSION(A) 한 grant → A만 write/open1·B 차단**, 별도 명시 LIBRARY와 새 A/B 계획 → **누적 open3·writes=[A,all,all]**이다. 네트워크와 실제 credential을 사용하지 않는다. A용 view를 B로 재지정해 전체 범위를 시험한 것이 아니다.

### 9.4 최종 mutation 재확인

기존 **19개**를 전부 다시 실행하고 bridge 결함 **3개**를 더해 **22/22 KILLED, survived/invalid/error0**을 직접 확인했다. UI setup 최적화 전 실행22/22 뒤, **최종 UI 시험 파일을 모든 사본에 반영해 다시 22/22**를 확인했다. 최종 정상 선택 baseline은 **8.885초 PASS**다.

| 추가 변이 | 결함과 실제 실패 node |
| --- | --- |
| M17 | STT의 fixed_session을 화면 selected_session으로 대체 → `test_bridge_submission_keeps_one_fixed_session_snapshot[stt]` assertion FAIL |
| M18 | 요약에서 prepare_execution을 두 번 호출해 독립 준비 경로 재도입 → 같은 시험 `[summary]`의 단일 호출/스냅샷 assertion FAIL |
| M19 | currentItemChanged에서 선택 없음 통지 생략 → `test_session_default_and_selection_clear[G02-UI-DEFAULT-stt]`의 None assertion FAIL |

TEMP 사본은 pyproject/src/tests/scripts/packaging을 함께 보유한다. 각 실행의 `consent.__file__`이 해당 사본 src인지 확인했고, 새 bridge 시험도 같은 사본에서 import한다. 원본·변이 source hash와 목표 실패 node·명령·시간은 `R2/mutations-final/results.json`에 있다. **모두 실제 testcase 실패이며 import/수집 오류나 timeout을 검출로 세지 않았다.** 원본 workspace와 Git은 변이시키지 않았다.

재현 도구는 `R2/run_mutations_phase2.py`, 최종 시험 적응 후 재확인은 `R2/recheck_mutations_final.py`다. 최초 사본·변이 diff는 `R2/mutations`, 최종 실행 증거는 `R2/mutations-final`에 보존했다. 최종 JSON LF SHA256은 **`f2808917fe039f38f46523030cc9e8c34a26aa8a8e4984e38fa9bb4be0ac83fa`**다.

### 9.5 정적 검사·격리 기준

C00의 G-P03 고정 tree **`044d240ffec01c1b73cdb2be8093dce3a06509e3`**를 git archive로 `R2/isolated`에 풀고 **G-P02 승인 목록19파일만** 덧씌웠다. 이후 커밋된 **`9d46b4a9a38de6f9c6fea38db35a440cbad7779f`의 tree가 위 객체와 정확히 동일**함을 직접 확인했다. 따라서 이 사본은 **HEAD(G-P03)+G-P02**다. 다른 작업자의 G-P04 등 미커밋 파일은 포함하지 않았다. manifest는 `R2/isolated-inputs.json`이다.

최종 사본에서 `ruff check --no-cache .` PASS, 승인된 Python18파일 `ruff format --check --no-cache` PASS, **`python -m mypy src/recoryn scripts packaging` 83 source files PASS**다. 캐시는 R2/mypy-isolated에 뒀다. `R2/static-final.json` LF SHA256은 **`0d7a96c39533fe1d5cf7520260371a11591e82bf32a04de3df37cbe8a2fd87bf`**다. 작업 트리 읽기 검사도 PASS했지만 그때의 mypy84파일에는 다른 배정 파일이 있어 최종 사본의 83파일과 혼동하지 않는다.

### 9.6 제출 파일과 SHA256(LF)

승인된 **19파일(제품5·새 시험4·기존 시험9·이 문서1)**이다. 다음 Python18파일은 사본의 실제 시험 대상과 작업 트리의 LF hash가 같음을 확인했다. 문서 자체 hash는 자기 참조를 피하기 위해 최종 창의 IMPLEMENTATION_READY 보고와 `R2/implementation-files.json`에 기록한다.

| 파일 | SHA256(LF, CR 제거) |
| --- | --- |
| src/recoryn/security/consent.py | `f5bf8a5627bdc136cd22e20d7fd7342575df3ee752e34accd1d1123c91f28391` |
| src/recoryn/security/gateway.py | `7bc28a807ebfbdc48e5d0b799e6487da8c96ad66f8ba64d42bfac614cb7e6384` |
| src/recoryn/security/__init__.py | `a962db7eca98db769027b88023dc980dd63f7aeccf85e967c203bb61cc4f0d18` |
| src/recoryn/ui/privacy.py | `24654aa5a288786e24b1077943c9129a789a74d269c49dcf4212af87a4de6b30` |
| src/recoryn/ui/ai_bridge.py | `f43f38d7ae7f5b0a49da0c680750facf80be5ff26f16cd78515ddbe4ab957891` |
| tests/unit/test_consent_scope.py | `ccdb419f24ed62bc94c970e0d98d3130d7784977019d580cb979ced940ef69d7` |
| tests/property/test_consent_scope_case_space.py | `587301cec639d6faefb2f804767b68e8dacc100515542310bee51696802e02d8` |
| tests/integration/test_consent_scope.py | `5e7fdf6dfda3e4c53fd96fe24aa74d9419906b1c6dc8af257cb2c8aa874416b5` |
| tests/ui/test_consent_scope_ui.py | `ecc33543355f3cf0c02690054977d2a279addac97ecf87ab2aa7103118b31771` |
| tests/unit/test_security.py | `4629c0a0276fbe0d88ec291c9a64d8d60ff5d28e93401c164b4a8a0402714c6a` |
| tests/property/test_security_case_space.py | `5e0b91b15cb83b546abf156ed6eceb187b006451fa4b642eecaaea1f309c593e` |
| tests/integration/test_gateway.py | `abeb9608ae590bd3fb0a172eb988801661e651c83f6163f0b1be3f84a8420ccf` |
| tests/integration/test_egress_independent.py | `8a637753672cbbae8343207160430c7640c71d482be99b9579feb764d27c39ee` |
| tests/integration/test_provider_security_independent.py | `d2c254d5a4f4ad92ba990bca914a3b0941b03e946c90eebdb6db553f822eeb27` |
| tests/integration/test_publication_independent.py | `492f814235daf2b6c1f57288f9d649e58bc6351ce7c01c5895145ba3e9384191` |
| tests/integration/test_ai_independent.py | `b80139e46372426e72429c78a7f72cfe53cc4524617a052c7ca67add04dd6370` |
| tests/contract/test_provider_contracts.py | `9e4fca24c51bf5cb41d6bbc69d449217c1f7e5a9ab5e253575bba7c259ccf8cb` |
| tests/ui/test_privacy_ui.py | `d048ea94088460ac049f4bcf6f895f0db1e809c32ade09c8a603cbe016d6e114` |

### 9.7 HEAD(G-P03)+G-P02 전체 오프라인 회귀·미해결

```powershell
# cwd: R2/isolated. 기준 commit 9d46b4a + G-P02 승인 목록19파일
# PYTHONPATH=R2/isolated/src, PYTHONDONTWRITEBYTECODE=1,
# QT_QPA_PLATFORM=offscreen, HF_HUB_OFFLINE=1,
# TRANSFORMERS_OFFLINE=1, HF_HUB_DISABLE_TELEMETRY=1
D:/project/Recoryn/.venv/Scripts/python.exe -B -m pytest -q -p no:cacheprovider --basetemp R2/full --junitxml R2/full.xml --durations=8 --tb=short
```

직접 결과 **9009 passed in 257.98s / exit 0**, failure/error/skip/xfail0이다. 별도 JUnit 집계 `R2/full-audit.json`으로 다음을 확인했다.

- **신규 네 파일984 PASS**, **UI 전체237 PASS(live10·GPU runtime4 포함)**.
- **G-P03 content unit103·integration203 PASS**, 신규 `test_g03_*` 단위24도 모두 포함한다. G-P03 선택 version CAS와 화자 게시 연결을 보존했다.
- §6의 기존 API 적응 시험9파일 및 수정하지 않은 Ollama runtime independent를 합한 **기존529 node도 이 전체 실행에서 전부 PASS**다. 보안 unit76·Q24 property200·Gateway31·egress43·provider security19·publication19·AI36·provider contract21·privacy18·Ollama66이다. 부분 실행529와 전체9009를 서로 다른 node처럼 더하지 않는다.
- 검사 종료 시 승인된 **Python18파일의 workspace·사본·사본 입력 manifest LF hash가 모두 일치**했다. 문서 최종 결과 추기는 실행 후 반영했으며 시험 소스/제품 코드는 이후 변경하지 않았다.

`R2/full.xml` LF SHA256은 **`1d15c24143b81e524cccc7cef7c2d8ef252246e4be35d4b40038dc9730f04680`**다. 첫 전체 격리 실행에서 정상 종료해 제품 실패를 재시도로 가린 결과가 아니다. 전체 사본의 코드·시험은 G-P03 commit + G-P02이며 다른 배정 변경의 검증 결과를 섞지 않았다.

현재 구현 범위의 **미해결 제품 반례0**, bridge 대기/SKIP0이다. 새 시험4파일의 최종 시간은40.19초이나 앞의66.03/61.89초 관측은 보존했으며 CI 부하별 시간 상한을 보증하지 않는다. 보안 무한 입력 공간·깊이4 밖 이력·실제 제공업체·실제 장치·모델·최종 비용 상한·전원 장애·외부 daemon의 후속 전송은 이 자동 검증으로 완료 처리하지 않는다. 비용 상한 G-P06과 G-P09 migration 인계는 별도 단위다.

**G02 IMPLEMENTATION_READY**다. 작성자 자신이 독립 최종 승인하지 않으며 **Claude 독립 검토와 C00 통합/커밋은 대기**한다. G-P06은 G-P02 커밋과 C00의 별도 시작 신호 전까지 구현하지 않는다.

## 10. 독립 검토 A의 8건 수정과 재검증

2026-11-23, w5:p8 Codex. C00이 G02A-01~08을 모두 고치기로 결정한 뒤의 작성자 수정 결과다. §8~9의 수치·해시는 당시 이력으로 보존한다. 검토 보고서의 9007 PASS·2 SKIP과 반례 7건은 **검토자가 기록한 결과**이며 아래는 이번에 직접 실행한 결과다. 수정에 대한 독립 재확인·최종 수용 판단은 C00과 같은 검토자의 몫이다.

증거 루트 **R3 = `C:/Users/gangd/AppData/Local/Temp/recoryn-g02-fix-h5lge8mg`**. 기준 commit **`7ffc8dceaf5d70ccc95ca5c75e927c869ebf2ed8`**를 git archive로 `R3/isolated`에 풀고 §6의 **G-P02 19파일만** 덧씌웠다. G-P04의 미커밋 recording/library/main/cli 변경과 신규 recovery 파일은 이 사본에 넣지 않았다. 기존 venv를 사용하되 `PYTHONPATH`와 pytest pythonpath가 사본 src를 가리키게 했다. 실제 모델·장치·네트워크·vault 쓰기는 없다.

### 10.1 수정된 계약과 구현

| 검토 ID | 수정과 관측 근거 |
| --- | --- |
| G02A-01 | 목록의 일시 None은 `selection_pending`으로 표시한다. 이때 선택은 즉시 None, 동의 버튼·실행 준비는 차단한다. 재구성 뒤 같은 논리 ID면 LIBRARY를 유지하고 B나 실제 선택 해제면 SESSION으로 돌아간다. `DesktopAI.attach_privacy`의 다음 GUI turn 확인과 `PrivacyPanel.select_session`이 함께 처리한다. FIX-00~05 |
| G02A-02 | 선택에서 bind를 제거했다. 읽기 전용 상태가 revoked/session generation·삭제 journal을 확인해 삭제 진행 중이면 동의 패널을 비활성화한다. 미완성 journal은 확인 중으로 보류한다. 이전 A 대신 현재 C를 표시하고 AI load·상세 갱신은 계속된다. FIX-06~11 |
| G02A-03 | 활성 grant만 절대 만료를 표시한다. 비활성은 철회됨·이전 실행·만료됨을 구분한다. 이전 실행 행을 새 실행으로 승계하지 않는다. FIX-12~19 |
| G02A-04 | scope_info의 실제 세션·기능·정책·활성 만료·전체 잔여 문구를 직접 assertion한다. 만료/전체 문구를 각각 제거한 변이를 검출했다. FIX-12~19, F07·F08 |
| G02A-05 | §2.4를 C00 결정대로 수정했다. 결과 키에서 scope kind/id·정책 version을 제외하고 요청마다 새 binding을 캡처한다. 범위/정책만 변경하면 키는 같고 binding은 다르다. 정책 변경 뒤 옛 binding은 CONSENT_POLICY_CHANGED로 거부된다. 실제 AIService의 두 번째 provisional 호출은 새 청크 한 개만 처리한다. FIX-22~29 |
| G02A-06 | `ConsentStore.scope_view`는 coordinator의 process lock을 비차단 시도하고 별도 read-only SQLite transaction을 timeout=0으로 읽는다. bind/permit/시계 영속 갱신/DDL/cross-process file lock을 하지 않는다. 잠금 중이면 확인 중을 먼저 표시하고 GUI timer가 재조회한다. 실행 준비는 기존 authorizing API로 다시 검사한다. 실제 fake write가 lock을 보유한 채로 탐색이 반환하는 인과 순서를 확인했다. FIX-20~21 |
| G02A-07 | FROZEN의 재바인딩 시도 결과를 Gateway 밖 리스트로 관측해 PERMIT_REVOKED와 대조한다. Gateway의 AssertionError→TRANSPORT_FAILED 변환만으로 통과할 수 없게 했다. 재바인딩 허용 변이의 first 96행을 별도 전수 실행해 96 assertion FAIL·error0을 확인했다. F10 |
| G02A-08 | 확인 창과 scope_info가 같은 현지 시각 변환 helper를 쓰며 UTC offset도 표시한다. OS 시간대를 바꾸지 않고 +05:45 사용자 환경을 주입해 손으로 고정한 `2023-11-15T04:58:20+05:45`와 대조한다. UTC-only 변이를 검출했다. FIX-12·16, F09 |

읽기 전용 상태는 권한 증명이 아니다. 조회 직후 권한이 달라져도 실행 준비·예약·연결·매 write·최종 반환에서 binding과 permit을 다시 검사한다. SQLite busy/읽기 오류는 확인 불가로 보류하며 기존 grant를 대신 채택하지 않는다. 세션 탐색만으로 security_sessions 행을 만들지 않는 것도 FIX-00~05에서 확인한다.

이번 수정에서 제품 파일은 consent.py·privacy.py·ai_bridge.py 세 개, 시험은 integration/property/UI 세 개, 문서는 이 파일 한 개다. 최초 제출의 나머지 12파일은 바꾸지 않았다. 최초 검토 tree `9c7a0d86`와 DesktopAI 메서드 AST를 대조해 **이번에 바뀐 메서드는 attach_privacy뿐**임을 확인했다. G-P03 화자 게시·selection/STT/요약의 기존 단일 스냅샷 연결은 보존했다. app/ai.py·content/store.py·ui/main.py와 기존 live/GPU UI fixture는 수정하지 않았다.

### 10.2 추가 입력 분할·분모·독립 oracle

기존 18,433행을 삭제하거나 축약하지 않고 다음 **UI_FIX 30행**을 추가했다. 새 계획 합계 **18,463행**이며 pytest node 합계와 구분한다.

| 새 case ID 끝자리 | 입력 분할과 feasible 분모 | 독립 기대값 |
| --- | --- | --- |
| 00~05 | STT/요약 2 × 목록 재구성 뒤 A/B/None 3 = 6 | A에서만 LIBRARY 유지, B/None은 SESSION. 재구성 중 무권한·탐색 bind0 |
| 06~11 | 기능2 × 세션 철회/같은 세션 journal/미완성 다른 journal 3 = 6 | C load·상세 갱신 지속, privacy도 C, 삭제 진행/확인 중, 버튼 무발급 |
| 12~19 | 기능2 × active/revoked/previous/expired 4 = 8 | 활성만 현지 절대 만료, 비활성은 사유, 전체 잔여 활성 여부를 손작성 표와 대조 |
| 20~21 | 기능2 × 진행 중 write 1 = 2 | write 해제 Event보다 탐색 반환 Event가 먼저. watchdog가 풀어준 뒤 반환하면 실패 |
| 22~27 | 기능2 × scope/policy/model 변경 3 = 6 | 앞의 둘은 결과 키 동일·신선한 binding, 모델은 키 다름. 정책 변경은 옛 binding 거부 |
| 28~29 | 실제 incremental STT × scope/policy 변경 2 = 2 | 첫 요청1청크 뒤 둘째 요청은 신규1청크, 합2. 실제 PCM·AIService·checkpoint, fake STT만 주입 |
| 합계 | **30** | 제품의 판정 helper로 기대값을 재계산하지 않음 |

FROZEN 분모504는 그대로이며 그중 문맥 변경{세션, 기능, 범위, 정책}4 × 범위2 × 기능3 × 데이터4 × first경계1 = **96행**의 oracle을 보강했다. 나머지 reserve/open도 같은 외부 결과 관측을 쓴다. `R3/audit_fix.py`는 registry와 별도로 작성한 ordinal/상수/TRACE 복원 목록을 대조한다. **18,463 고유 ID, 누락·중복·추가0**, 새 UI_FIX30을 포함한 parameter ID가 JUnit에 존재하며 loop 네 개의 내부 행 assertion도 PASS다.

### 10.3 정상본과 검토자 원 반례

```powershell
# cwd R3/isolated. 모든 실행은 기존 venv, bytecode 억제, offscreen, offline.
# PYTHONPATH=R3/isolated/src. R3는 위 절대 경로의 축약 표기다.
D:/project/Recoryn/.venv/Scripts/python.exe -B -m pytest tests/unit/test_consent_scope.py tests/property/test_consent_scope_case_space.py tests/integration/test_consent_scope.py tests/ui/test_consent_scope_ui.py -q -p no:cacheprovider --basetemp R3/new-four-bt --junitxml R3/new-four.xml --durations=6 --tb=short
```

직접 결과 **1,014 passed in 43.44s / skip0·failure0·error0**, 60초 이내다. 구성은 unit106 + property5 + integration685 + ui218이다. 추가30행과 기존 assertion을 줄이지 않았다. 느린 다른 PC/CI에서도 이 시간을 보장한다는 뜻은 아니다.

검토자의 `build/review-trees/g02-sub-a/tests/review_g02a/test_g02a_probes.py`는 그대로 보존했다. TEMP 사본 `R3/test_g02a_probes.py`에서 **청크 시험의 사전조건 한 줄만** C00의 계약 변경에 맞춰 `key_session != key_library`에서 `==`로 바꿨다. 최종 `resent == 1` 기대값은 유지했다. 직접 결과 **12 PASS / 1.43s**, 기존 반례 7건과 확인/대조5건이 포함된다. 원 파일을 아무 변경 없이 12 PASS했다고 주장하지 않는다. 정식 시험30행은 이 probe를 복사하지 않고 위 독립 입력 분할·상태/인과/청크 수 oracle로 작성했다.

| 검토자 원 반례 | 정식 시험의 대응 |
| --- | --- |
| 같은 A로 목록 갱신 | FIX-00·03 및 B/None 대조4행 |
| 철회된 C 선택 | FIX-06·09 및 실제 journal 대조 |
| 미완성 deletion-journal 중 B 선택 | FIX-08·11 |
| 철회 grant에 활성 만료 표시 | FIX-13·17 |
| 이전 실행 grant에 활성 만료 표시 | FIX-14·18 |
| 범위 변경 후 이미 처리한 청크 재전송 | FIX-28 및 정책 변경 FIX-29 |
| 원격 write 동안 탐색이 coordinator 대기 | FIX-20·21 |

### 10.4 mutation과 정적 검사

`R3/run_fix_mutations.py`가 정상 선택 baseline **9.480초 PASS**를 먼저 확인했다. 기존22개는 현재 구조에 맞춰 변이 위치만 적응했다. M03은 새 metadata 검증 호출과 혼동하지 않고 grant key의 기능 비교를 변이했고, M19는 현재 attach의 None 통지를 생략했다. 기존 변이22와 아래10을 **각각 독립 TEMP 사본**에서 실행해 **32/32 KILLED, survived/invalid/error0**이다. pyproject/src/tests/scripts/packaging을 함께 복사하고 매 실행 consent.__file__이 해당 사본 src인지 확인했다. diff·source hash·실패 node·실행 명령·XML을 보존했다. import/수집 오류·timeout은 검출로 세지 않았다.

| 새 변이 | 의도 | 실제 실패 관측 |
| --- | --- | --- |
| F01 | 같은 ID도 무조건 범위 초기화 | FIX-00 |
| F02 | 선택 시 bind_session 재삽입 | FIX-06 |
| F03 | 결과 키에 scope 재삽입 | FIX-28의 신규 청크 수 |
| F04 | 결과 키에 정책 version 재삽입 | FIX-29의 신규 청크 수 |
| F05 | scope_view lock을 blocking=True로 | FIX-20의 해제 전 반환 순서 |
| F06 | 비활성에도 만료를 표시 | FIX-13 |
| F07 | 전체 허용 유지 문구 제거(검토자 X20 의도) | FIX-12 |
| F08 | 만료 문구 제거(검토자 X21 의도) | FIX-12 |
| F09 | 현지 변환 제거, UTC-only | FIX-12 |
| F10 | for_session 재바인딩 허용(검토자 X09f 의도) | FROZEN-005(first), 별도 first96 전부 FAIL |

F10 사본에서 `-x` 없이 first96만 전수 실행한 결과 **96 failed / error0**이다. 정상본의 동일96은 새4파일 실행과 전체504에 포함돼 PASS했다. Gateway가 변환한 임의 SecurityError를 기대값으로 받지 않고 외부 리스트의 정확한 PERMIT_REVOKED를 검사한다.

격리 사본의 `ruff check --no-cache .` PASS, 승인된 Python18파일 `ruff format --no-cache --check` PASS(**18 files already formatted**), `python -m mypy src/recoryn scripts packaging` PASS(**83 source files**)다. 캐시는 R3/mypy-cache에 분리했다. format 쓰기는 승인 파일에만 적용했고 실제 내용 변경0이었다.

### 10.5 전체 오프라인 회귀·증거 파일

```powershell
# cwd R3/isolated. 기준 7ffc8dc + 승인 G-P02 19파일만 포함.
# PYTHONPATH=R3/isolated/src, PYTHONDONTWRITEBYTECODE=1,
# QT_QPA_PLATFORM=offscreen, HF_HUB_OFFLINE=1,
# TRANSFORMERS_OFFLINE=1, HF_HUB_DISABLE_TELEMETRY=1
D:/project/Recoryn/.venv/Scripts/python.exe -B -m pytest -q -p no:cacheprovider --basetemp R3/full-bt --junitxml R3/full.xml --durations=10 --tb=short
```

직접 결과 **9039 passed in 248.93s / exit0**, failure/error/skip0이다. `R3/full-audit.json`으로 JUnit을 별도 집계했다.

- **UI 전체267 PASS**: 새 scope UI218, 기존49. live UI10·GPU runtime UI4가 모두 포함돼 PASS했다. 그 fixture 두 파일은 수정하지 않았다.
- **G-P03 content unit103 + selection version integration203 = 306 PASS**. 화자 게시 및 선택 version CAS 연결을 보존했다.
- **기존 보안·gateway·privacy·provider 및 Ollama independent 529 PASS**. 새4파일1014도 이 전체 실행에 포함된다. 부분 집계 숫자를 서로 더해 고유 node 수로 쓰지 않는다.
- 종료 시 승인 Python18파일의 workspace·격리 사본 LF hash가 모두 일치했다. 결과 추기는 문서에만 수행했다. 다른 작업자의 미커밋 제품 변경은 포함하지 않았다.

| 증거(R3 기준) | SHA256(LF, CR 제거) |
| --- | --- |
| new-four.xml | `39caaf101614995400082a7f2cb80b9f887fe500c213d4331e50f29346d46e83` |
| probes.xml | `38fc37fc03d472d7319f60909e04a078eb91c7be328122da0a59850c6131a023` |
| case-audit.json | `b4fc0c4d760e36e3f4d4788c3c89e42eaa2f9a28f54f05ed2f351081e902dfd7` |
| mutations/results.json | `1ef247e8ee54ddb5a8c15d062c1df16aabec7e793778a31df6fdbac38325f5da` |
| first96.xml | `ddd87e807cfa3e5044bdaa6b6cc8675877bfaa9351b959f18db9d5c0ba080fa6` |
| full.xml | `01eaca05a12446ce807d8273208adde484811960026b72cf82a8821bbb81a590` |

이번 수정의 재현 증거와 정식 시험은 위 경로에 보존했다. 검토자 원본 probe·보고서는 수정하지 않았다. 제품 반례의 수정은 완료했고 **독립 RECHECK와 C00 통합은 대기**한다. 새 미해결 제품 반례를 발견하지 않았으나 작성자가 검토자의 OPEN을 최종 CLOSED로 승인하지 않는다. 비용 상한·schema migration 등 다음 단위 구현도 시작하지 않았다.

### 10.6 수정 제출 파일과 SHA256(LF)

아래는 최초 제출과 이번 수정이 합쳐진 **승인19파일 중 Python18파일**의 현재 해시다. 이번에 바뀐7파일과 이전 제출에서 유지된12파일은 `R3/full-audit.json`의 fix_changed_files와 §10.1에 구분했다. 문서 자체 해시는 자기 참조를 피하기 위해 창의 FIX_READY와 `R3/fix-files.json`에 기록한다.

| 파일 | SHA256(LF) |
| --- | --- |
| src/recoryn/security/consent.py | `0959e57737bfacc1c630dd0c9ab9feda8f0945fa9ee576f60e5900bc17b1be77` |
| src/recoryn/security/gateway.py | `7bc28a807ebfbdc48e5d0b799e6487da8c96ad66f8ba64d42bfac614cb7e6384` |
| src/recoryn/security/__init__.py | `a962db7eca98db769027b88023dc980dd63f7aeccf85e967c203bb61cc4f0d18` |
| src/recoryn/ui/privacy.py | `5dde7c8a3421a016fc9700f32d267babf16ffe218a5ac6fe8eccb6ecb6f7ccfb` |
| src/recoryn/ui/ai_bridge.py | `725db065d0eeda327736a262b646d9aa46f7a04779f360d3bd6835afc9ff0a3c` |
| tests/unit/test_consent_scope.py | `ccdb419f24ed62bc94c970e0d98d3130d7784977019d580cb979ced940ef69d7` |
| tests/property/test_consent_scope_case_space.py | `b6dfe04f53b56b0762761c6ce518a170c9d35330f948990c468d0c5e901425e0` |
| tests/integration/test_consent_scope.py | `cb5fe3cc40f63105f159163c3141ff21dab0002a11bfbf430f16233a0391080a` |
| tests/ui/test_consent_scope_ui.py | `4962a35a3691b90097287575e53b2e4896cdd99e1f38e764f7a6a0bf8a4fa419` |
| tests/unit/test_security.py | `4629c0a0276fbe0d88ec291c9a64d8d60ff5d28e93401c164b4a8a0402714c6a` |
| tests/property/test_security_case_space.py | `5e0b91b15cb83b546abf156ed6eceb187b006451fa4b642eecaaea1f309c593e` |
| tests/integration/test_gateway.py | `abeb9608ae590bd3fb0a172eb988801661e651c83f6163f0b1be3f84a8420ccf` |
| tests/integration/test_egress_independent.py | `8a637753672cbbae8343207160430c7640c71d482be99b9579feb764d27c39ee` |
| tests/integration/test_provider_security_independent.py | `d2c254d5a4f4ad92ba990bca914a3b0941b03e946c90eebdb6db553f822eeb27` |
| tests/integration/test_publication_independent.py | `492f814235daf2b6c1f57288f9d649e58bc6351ce7c01c5895145ba3e9384191` |
| tests/integration/test_ai_independent.py | `b80139e46372426e72429c78a7f72cfe53cc4524617a052c7ca67add04dd6370` |
| tests/contract/test_provider_contracts.py | `9e4fca24c51bf5cb41d6bbc69d449217c1f7e5a9ab5e253575bba7c259ccf8cb` |
| tests/ui/test_privacy_ui.py | `d048ea94088460ac049f4bcf6f895f0db1e809c32ade09c8a603cbe016d6e114` |
