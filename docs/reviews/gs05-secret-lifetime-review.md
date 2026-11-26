# GS05-R1 — 비밀 읽기 수명 계약 독립 검토

검토자: w5:pB Codex. 작성자 w5:pA와 별도 세션이다. 배정은 H03의 GS05-R1이며 현재 쓰기는 이 문서 하나다. GS05 계약·제품·시험·배정표·Git은 수정하지 않는다. 시험 수집/실행·mutation·실제 vault·네트워크·설치·장치/모델 실행은 0이다.

상태: **REVIEW_READY — 계약 개정 필요 / OPEN S2 4건**. 새 구현/실행을 승인하는 문서가 아니다. X00 최종 결정과 작성자 수정·독립 재확인은 미완료다.

## 1. 대상·기준·관측

- 시작: 2026-11-26 13:08:55 +09:00, cwd `D:/project/Recoryn`, HEAD `b77cc102a9db818a8c1d1a2840933ffa28e1b14c`.
- 대상 계약: `docs/testing/gs05-secret-lifetime-cases.md`, 52,715 bytes/310줄, LF SHA-256 `5b2918a9a34346a63780267b1b36a0cbb73ecae484da4b6254467e3de5b4b341`. 13:09:04 +09:00에 실제 읽기/hash 대조. 승인된 제품 구현이 아닌 CONTRACT_DRAFT다.
- 배정 snapshot: `docs/collaboration/assignments.md`, LF SHA-256 `3660834a005e9bffe23699b9d545cdb92e519be1f793540f00dcdd84ed0f6843`, 129,948 bytes. H02/H03·GS05-R1의 한 파일 범위·상호 독립 검토를 확인했다.
- 시작 dirty: 수정18·미추적21, staged/unmerged 표기0. 미통합 GS04a/GS11a·다른 문서와 이 검토를 합산하지 않는다. 본인의 G09-PREP1 결과는 동결하며 다시 쓰지 않는다.
- 제품·시험 근거 `B:경로:줄`은 모두 위 고정 commit의 `git show` 출력이다. 계약 근거 `C:줄`은 위 hash의 GS05 문서다. 정적 단언/소스 존재와 실제 PASS/FAIL을 구분한다.

## 2. D01~D07 및 D08 결정 경계

| 결정 | 독립 대조·판정 | X00가 닫아야 할 조건 |
| --- | --- | --- |
| D01 보호된 read/직렬화 | C:87·94·96·98은 native CredRead가 돌아올 때까지 consent 직렬화를 유지하고 Q 의도/commit을 구분한다. B:security/_core.py:157·164의 동일 DB Coordinator가 같은 RLock/프로세스 잠금을 공유하는 계약과 맞는다. ledger/owner를 read 동안 추가 보유하지 않는 점도 타당하다 | 무기한 native 지연·철회 commit 지연을 명시 수용할지 결정. GUI의 **모든** 동일 coordinator 대기를 worker로 옮겨야 하며 GS05R-04의 버튼/refresh 누락을 보강. A를 B(two-phase)로 바꾸면서 같은 Q 뒤 physical read0 oracle를 유지하면 안 됨 |
| D02 취소 의미 | C:93은 Event.set/C0와 승인 gate/C를 분리해 set 이후 물리 호출 절대0을 주장하지 않는다. 기존 Event 기반 B:gateway.py:184와 양립하는 한계 고지다 | read 중 취소는 native 종료 ACK가 아님. r 뒤 결과 폐기·O/H/다음 body 차단을 관측하고 실제 in-flight 작업은 종료/정리 전 완료로 표시하지 않음. 이 약한 경계를 사용자에게 더 강한 취소 보장으로 표시하지 않음 |
| D03 DTO/ref/resolver | B:providers/contracts.py:159·171, _common.py:241은 현재 raw auth header를 복사·보관하므로 C:71~76의 비밀 없는 reference/요청별 해석은 gap에 직접 대응한다. epoch가 키 hash와 무관하고 provider/exact endpoint·앱 execution에 묶이는 점도 타당하다 | 새 gateway 인자/프로토콜과 raw auth 거부를 공용 계약에 반영. resolver capability가 검사 우회 권한이 되지 않게 현재 binding/epoch·대상을 gateway에서 독립 검사. gateway→provider→Job 오류 보존은 GS05R-02와 D08에 추가해야 함 |
| D04 기존 기대 변경 | B:tests/ui/test_privacy_ui.py:196은 context 생성의 AUTH_REQUIRED, tests/integration/test_egress_independent.py:267·277은 실제 옛 키 보관, tests/unit/test_providers.py:204는 raw auth context 허용을 직접 기대한다. 작성자가 변경 필요를 숨기지 않았다 | 이 세 종류는 단순 fixture 정리가 아니라 새 계약에 따른 oracle 변경이다. X00가 단계/공개 API를 승인한 뒤 기존 거부·고정 설정·UNKNOWN·CAS 원 반례를 보존하여 적응. 원 독립 반례를 작성자가 단독 종결하지 않음 |
| D05 redaction hints | B:security/vault.py:124·139는 set/get 때 register_secret을 부르고 B:security/_secrets.py:8은 최대256 비밀 str을 보관한다. C:77·297·308은 이를 분명히 잔여 위험으로 남긴다 | **요청 DTO/header 수명 개선**이라는 범위로 수용할지 X00 결정. 프로세스 메모리 전체의 비밀 제거/zeroization 완료라고 승인하면 안 됨. hints까지 바꾸려면 vault/_secrets/diagnostics·caller·분모의 새 범위가 필요하며 현재20파일에 조용히 포함하지 않음 |
| D06 입력/실패 UI | B:ui/privacy.py:998·999는 동기 set 성공 뒤 clear다. C:103의 제출 수락 직후 clear/실패 때 안전 코드+재입력은 비밀을 callback으로 되돌리지 않는 선택이다 | 실제 worker 제출 실패와 제출 수락 후 native 실패를 구분하고 safe callback·nonce/선택 세대·close 뒤 widget 접근0을 확인. 저장/철회 pending을 완료로 알리지 않음. native hang의 강제 종료 보장을 추가하지 않음 |
| D07 분모/44변이/20파일/60초 | 44변이·20파일 산술은 맞지만 **620행은 틀리며 현재 정의는520행**이다(GS05R-01). wall60초·coverage·원격 CI·mutation은 모두 계획/NOT_RUN | GS05R-01~04를 반영하고 수정된 primary ID/선택 manifest와 실제 코드 seam을 사전 고정한 뒤 승인. 시험 수를 맞추려고 중복/감사 node를 의미 행으로 합산하지 않음 |
| D08 추가 오류 결정 | 계약은 D01~D07뿐 아니라 **D08도 별도 미결정**으로 두고 있다(C:300). A의 CONSENT_REQUIRED/CONSENT_REVOKED/PERMIT_REVOKED 확정은 타당한 요청이다 | VAULT_READ_FAILED/VAULT_UNAVAILABLE/VAULT_INVALID_VALUE의 provider/Job 경계 변환도 함께 고정(GS05R-02). 알려진 미송신을 UNKNOWN으로 승격하거나 오류 허용 집합을 넓히는 방식은 금지 |

동시성 모델의 R→r→O→H→B→F와 Q commit 뒤 새 handoff0, 첫 write 전 known/이후 UNKNOWN 보존은 큰 방향에서 일관된다. C:170의 cut1은 **r 뒤 lock을 놓은 지점**에서 대기 중 Q가 O보다 먼저 commit하도록 barrier로 강제할 때 feasible하다. 같은 consent lock을 가진 read thread가 Q를 동기로 기다리는 fixture는 교착이므로 금지한 점(C:176)을 수용한다. 공통 취소/epoch/owner guard를 몇 번 불렀는지 대신 실제 R/O/H/B/F로 관측하는 원칙도 유지해야 한다.

## 3. 독립 발견·정적 반례

아래는 **계약의 OPEN 발견**이다. 현재 제품에서 새 무동의 송신/유출/오류를 실행 재현했다는 뜻이 아니다. 심각도는 제안대로 구현/검증할 때의 영향과 수락 가능성을 기준으로 S2로 분류한다. 제품 S0/S1 발견을 새로 주장하지 않는다.

### GS05R-01 / S2 / OPEN — 총분모620과 명시 가족520 불일치

- 근거: C:134~143의 가족은 A240/B40/C36/D45/E20/F40/G72/U16/X11이다. **240+40+36+45+20+40+72+16+11=520**이며 C:143의 ‘=620’과 맞지 않는다. C:3·299·306·310에도620이 반복된다. A의 5×4×3×2×2=240과 성공5/거부235는 자체로 맞다.
- 정적 반례: 명시한 range/tuple만 독립 열거하면 유일 tagged ID는520개뿐이다. 제품/작성자 생성기를 import하지 않은 문서 산술로 확인했다. 남는100개는 이름·입력·oracle·소유 node가 없다. 따라서 ‘620 literal ID 감사’를 그대로 구현하면100개 부족이거나, 무관한 보강/중복/감사 node를 채워 넣게 된다.
- 수정 요청: (A) 명시 범위가 의도 전부라면 총분모520으로 관련 문구·ID manifest·D07을 일괄 정정하거나, (B) 빠진100개가 필요하다면 그 입력 분할·제약/feasible·유일 ID·독립 기대·계층/primary node를 먼저 추가한다. 단순 숫자 맞추기나 생성기 길이로 expected를 재정의하면 안 된다. 이 리뷰는 미래 제품 시험의 분모를 대신 승인하지 않는다.
- 재확인 기준: 수정 문서의 독립 산식/유일 tuple/ID·선택 계층이 선언값과 맞고 차이100의 처리 근거가 남아야 한다. 이 단계는 정적 재검토이며 실제 collected/executed 감사는 구현 후 별도다.

### GS05R-02 / S2 / OPEN — vault 오류의 gateway→provider→Job 알려진 미송신 의미가 닫히지 않음

- 계약 근거: C:163의 B는 invalid/예외를 **VAULT_INVALID_VALUE/VAULT_READ_FAILED known-unsent**, DNS/open0으로 정한다. C:75는 실제 읽기를 gateway로 옮기고 C:74는 `_common.Run.request`를 경유하게 한다. 하지만 D08(C:300)은 동의/binding 명칭만 다룬다.
- 기준 근거: B:security/vault.py:136~144의 malformed/UTF-8/예외는 위 코드로 나온다. B:providers/_common.py:254~289는 `normalize_failure(...,remote_boundary=True)` 후 자체 safe code 집합에 없으면 **REMOTE_OUTCOME_UNKNOWN/outcome_known=False**로 바꾼다. VAULT_READ_FAILED/VAULT_UNAVAILABLE은 B:jobs/failures.py:14에서 AUTH 그룹이지만 `_common` safe 집합/BOUNDARY_CODES에는 없다. VAULT_INVALID_VALUE은 CODE_GROUPS에도 없어 B:failures.py:97에서 TASK_FAILED가 된다. `safe_codes`에 raw 문자열만 추가해도 normalize 뒤에는 이미 다른 code가 될 수 있다.
- 정적 trace(실행 아님): 정상 동의/예약 → 새 gateway resolver가 fake vault의 malformed/UTF-8 오류로 R1·O/H0 → SecurityError(known=True) → 기존 Run normalize/safe list → REMOTE_OUTCOME_UNKNOWN. Job은 B:failures.py:113에서 BLOCKED(REMOTE_UNKNOWN)/Attempt UNKNOWN으로 판정할 수 있다. 원격 전송은 없는데 원격 결과 미확인이 생기며, B의 gateway 직접 시험만으로 이 전파를 잡지 못한다. 이 읽기 위치는 새 제안이므로 기존 제품이 이미 같은 오류를 일으킨다는 주장이 아니다.
- 수정 요청: gateway의 raw vault 진단과 공개 provider/Job의 닫힌 AUTH code를 **층별 literal 표**로 결정한다. 기존 AUTH_REQUIRED/VAULT_READ_FAILED 등에 정규화해 현재20파일 안의 `_common.py`에서 처리할지, 공용 failure table까지 확장할지 X00가 정해야 한다. 후자면 `jobs/failures.py`와 해당 시험이 현재 manifest 밖임을 보고해야 한다. 단순 예외 허용 집합 확대·모든 오류 UNKNOWN 처리는 수락하지 않는다.
- 필수 oracle: 실제 provider→Run→Gateway+fake vault/ledger 경로에서 invalid value/UTF-8/백엔드 실패와 정상 대조를 확인한다. R1·DNS/O/H/B0, 공개 safe code 하나, outcome_known=True, 예약 RESERVED 유지·unknown_exposure0, Job/Attempt의 승인된 AUTH 종료, 자동 retry0·canary0. H 뒤 오류는 기존 UNKNOWN80을 계속 유지한다. 목표 변이도 provider에서 known→unknown으로 재분류하는 단일 결함을 실제 assertion으로 잡아야 한다.

### GS05R-03 / S2 / OPEN — ‘첫 write 직후 정리’보다 늦은 정리를 검출할 oracle/변이가 없음

- 요구: C:76은 gateway/transport 앱 소유 header 사본을 **첫 write 성공/실패 직후** 정리하고, 다음 body/응답 대기까지 보관하지 않는다고 한다. HTTP/OS 내부 복사본·redaction hints를 없앤다는 요구는 아니다.
- 빈틈: C:178~192 D는 종료·fault 뒤 cleanup을 확인하고, C:223 M14는 ‘종료 뒤 gateway/transport 앱 header 사본 secret0’를 목표로 한다. C:239의 상세 M14도 **요청 종료 cleanup** 한 위치로 한정한다. C cut4/B1 뒤·G 정상 완료·X08은 전달/읽기 횟수·최종 출력 oracle는 있으나 **요청이 끝나기 전의 참조 수명**을 명시해서 검사하지 않는다.
- 독립 정적 mutant trace: 첫 write 뒤 clear를 제거하고 같은 clear를 최종 request finally에만 둔다 → 요청 종료 뒤 DTO/로그/header0·read1·H1/B2·UNKNOWN 판정은 모두 그대로일 수 있지만 B2/느린 응답 동안 비밀 사본이 살아 있다. 이 mutant는 C:76을 어기면서 선언한 종료 시점 oracle를 통과할 수 있다. 아직 실제 코드를 변이/실행하지 않았다.
- 수정 요청: 첫 H/B1이 끝난 뒤 B2 또는 read/F를 barrier로 멈추고, **정확히 앱 소유인 resolver lease/local secret/header dict·transport `_headers`의 허용된 검사 면**을 정해 비밀 참조0을 단언한다. fake vault 저장·테스트 관측 원본·전역 hints·HTTP 내부를 숨겨서 전체 process zeroization을 주장하지 않는다. 첫 write 전 open 실패와 첫 write 부분 오류의 finally 정리도 유지한다.
- 재확인: ‘정리를 request 종료까지 미룸’이라는 단일 새 변이가 위 **중간 call assertion**에서 FAIL해야 한다. Event를 풀기 전 timeout/worker hang으로 끝나는 것은 INVALID다. 기존 C/D/X 행에 assertion을 배정할지 독립 보강 ID를 추가할지 명시하고, mutation44를 유지/확장할지도 X00에게 다시 제출한다.

### GS05R-04 / S2 / OPEN — 보호된 read 중 GUI가 기다릴 동일 coordinator 경로의 선택 분모 누락

- 요구: C:73·98·293은 native read가 consent를 잡아도 GUI가 자유롭도록 동의/**ledger** 대기를 worker로 이행한다. 동일 security DB의 ConsentStore/CostLedger는 B:security/_core.py:157~171의 같은 lock을 공유한다.
- 기준의 GUI 입장: B:ui/privacy.py:262~304는 grant/revoke/save/delete 외에 **budget/reset_clock/refresh/settle/adopt** 버튼도 `_action`에 직접 연결한다. B:926~1027은 해당 동작과 `_refresh`를 동기로 호출한다. B:857의 `_refresh`는 `availability/account_snapshot/account/legacy_unscoped/reservations`를 조회하며 B:ledger.py:694·697의 account도 coordinator를 잡는다. native read를 새 A gate 안에 둔 상태에서 이 옛 경로가 남으면 버튼 또는 refresh로 GUI가 같은 lock을 기다릴 수 있다.
- 분모의 빈틈: C:200의 U는 STT/summary 준비·키 저장/삭제·endpoint 철회·설정 변경·close·완료 callback 8동작뿐이다. 일반 ‘설정 변경’을 grant/예산/시계/정산/refresh 각각의 실제 Qt 버튼·후속 조회 전체를 실행했다고 해석할 수 없다. U 전체를 worker로 옮긴 구현이 나머지 동기 경로를 남겨도 U16은 통과할 수 있다.
- 수정 요청: **공통 보안 action dispatcher와 조회/read model 경계 전체**의 worker 소유·GUI에서 금지된 hold/native 진입을 계약에 명시한다. 같은 DB의 protected fake read를 Event로 막은 동안 grant·budget·refresh·reset/adopt/settle 등 실제 보안 진입을 각각 호출하는 bound/ID를 정한다. 정상적으로 확인 모달이 필요한 동작은 비민감 fixture에서 확인 단계와 worker 입장을 구분한다. GUI·coordinator lock 안에서 barrier를 기다려 시험 교착을 만들지 않는다.
- 독립 oracle/변이: GUI action은 작업 접수/안전 pending만 반환, lock/native 진입 thread ID≠GUI, Qt heartbeat 진행·late callback generation 유지·합성 recorder control 독립. 공통 worker 경계를 한 보안 action만 GUI 직접 호출로 되돌린 변이를 heartbeat timeout만이 아니라 thread/입장 assertion FAIL로 검출한다. C:73 요구를 줄이려면 D01의 위험/보장도 다시 결정해야 하며 선택 계층/시간 예산을 갱신한다.

## 4. 620행·44변이·20파일 대조

### 4.1 입력 분모와 제외

| 가족 | 독립 산식 | F | 확인 |
| --- | --- | ---: | --- |
| A | 5×4×3×2×2 | 240 | 성공5·거부235, 거부를 분모에 포함한 점은 맞음 |
| B | 5×8 | 40 | fake read 결과8종. stage/code의 층별 oracle는 GS05R-02 보강 필요 |
| C | 6×6 | 36 | 명시 cut bound, 모든 schedule 전수라는 주장을 하지 않음. Q 뒤 R0와 R 중 Q 대기를 구분 |
| D | 5×9 | 45 | enter/exit·header/body 부분 전달을 관측으로 구분. 중간 정리 시점은 GS05R-03 |
| E | 2×2×3+8 | 20 | ID00~11과12~19, epoch 실패 rollback0·동일 endpoint STT/summary 동시 무효화 포함 |
| F | 5×8 | 40 | provider/endpoint/capability/data/session/session generation/execution/epoch 단일 변경. ref가 아닌 축은 permit에서 검사 |
| G | 12×6 | 72 | absent file만으로 통과하지 않고 안전 필드·실제 출력 호출을 관측하라는 요구 수용. scope 예외는 fake vault/hints에 한정 |
| U | 8×2 | 16 | 두 선택 세대. GS05R-04의 GUI 진입 누락을 별도 보완 |
| X | named00~10 | 11 | 로컬 read0·우회 거부·요청별 R2/한 요청 R1·빈 body H1/B0 구분 |
| 합계 | 240+40+36+45+20+40+72+16+11 | **520** | 선언620 대비100 부족 |

이것은 tagged 대표 공간의 문서 대조다. 외부 모델/실서비스·같은 사용자 악성 프로세스 sandbox·프로토콜상 H보다 B2가 먼저인 불가능 순서 등 C:147의 제외를 **산술 차이100의 근거로 쓸 수 없다**. 현재 각 family에 추가 raw/excluded100이 정의되어 있지 않다. 새 보강을 넣으면 실제 입력/feasible와 독립 기대부터 정의해야 한다.

### 4.2 mutation44

M01~M26 중 composite M20/M22/M24를 뺀 단일23개 + M20-02..06의5 + M22-03..11의9 + M24-00..06의7 = **44**, expanded label의 중복0이다. 이는 KILLED 결과가 아니라 명명된 계획 수다. M10/11/12/14/17/19/21/23의 단일 편집 의미를 C:239에서 다시 한정한 점과 SURVIVED/INVALID/EQUIVALENT를 분리하는 원칙은 수용한다. 단, 44가 맞는다는 사실은 GS05R-02~04의 새 의미 결함을 검출한다는 증거가 아니다. 특히 ‘모든620행이 family mutation에 대응’(C:241)은 총분모 정정과 추가 중간/전체 경계 oracle 뒤 다시 기술해야 한다.

후속 정상 PASS→격리 단일 mutant 목표 call assertion FAIL, source/import hash·선택 node·teardown error/timeout 분리, subset 선택의 기대 ID 감사는 필수다. reviewer가 이번에 변이를 직접 실행한 수는0이다.

### 4.3 정확한20파일·소유 충돌

| 구분 | 정확한 경로 | B 존재·경계 |
| --- | --- | --- |
| 제품 신규1 | `src/recoryn/security/credentials.py` | MISSING/PLANNED. ref/resolver/epoch·키 명령 서비스 |
| 제품 기존6 | `src/recoryn/security/gateway.py`, `src/recoryn/security/transport.py`, `src/recoryn/providers/contracts.py`, `src/recoryn/providers/_common.py`, `src/recoryn/ui/privacy.py`, `src/recoryn/ui/ai_bridge.py` | 모두 존재. gateway와 provider safe 오류·UI 전체 worker 이행이 이 범위에 포함되어야 함 |
| 기존 시험8 | `tests/ui/test_privacy_ui.py`, `tests/ui/test_consent_scope_ui.py`, `tests/ui/test_cost_cap_ui.py`, `tests/integration/test_cost_cap.py`, `tests/integration/test_egress_independent.py`, `tests/unit/test_providers.py`, `tests/contract/test_provider_contracts.py`, `tests/integration/test_provider_security_independent.py` | 모두 존재. 기존 raw auth/실키 보관 기대 변경은 D04 승인 필요. 기존 UNKNOWN/원본·동의·CAS·예약 oracle 보존 |
| 새 시험4 | `tests/unit/test_secret_lifetime.py`, `tests/integration/test_secret_lifetime.py`, `tests/ui/test_secret_lifetime_ui.py`, `tests/property/test_secret_lifetime_case_space.py` | 모두 B에 MISSING/PLANNED. 아직 node/실행/primary ID mapping 없음 |
| 계약1 | `docs/testing/gs05-secret-lifetime-cases.md` | B에 없고 WT 대상 hash만 존재. 작성자 현재 동결, X00 결정 뒤 재배정 |

7+8+4+1=20, 고유20이다. B 존재14/부재6이며 source/ref/epoch가 구현됐다고 계산하지 않는다. `vault.py`, `_secrets.py`, `consent.py`, `ledger.py`, `jobs/failures.py`, diagnostics·app/ai.py·일반 설정·CI/패키징은 **범위 밖**이다. GS05R-02 해결을 공용 failure enum 추가로 택하거나 D05 hints까지 확장하면 선행 계약/범위 재승인이 필요하다. 제안의 worker/정리/API 경계가 다른 시험을 깨뜨리면 실제 실패·최소 변경안을 먼저 보고하며, 독립 시험을 직접 약화해 통과시키지 않는다.

직접 활성 충돌은 미통합 GS04a의 `ui/privacy.py`다. 먼저 X00 통합/CI와 실제 기준을 인수해야 한다. GS11a의21파일과 이20파일에는 직접 교집합이 없으나 동일 session/deletion fence 회귀는 유지한다. G09a가 뒤에 security/gateway.py 등을 수정할 계획이므로 X00이 직렬 배정해야 한다. 계약의 메모리 전용 ref/epoch는 schema/backup component로 승격하지 않는다. GS04b metadata GET/probe·새 인증 route/실계정을 이번 범위에 추가하지 않는다.

신규4파일60초는 아직 **제안**이며 측정0이다. 실제 비용은 fixture·barrier·GUI action 확장과 결함/cleanup 경로가 확정된 뒤 측정해야 한다. 기존 다른 단위의100/120/360초를 상속하지 않고, 60초 초과 시 분모/반례를 줄이기 전에 실측과 최적화/예산 변경안을 보고한다. line/branch 및 의미 분모·ID 감사·독립 mutation은 서로 대체되지 않는다.

## 5. 최종 판정·미검증

판정은 **REVIEW_READY / 계약 개정 필요, 구현 승인 보류**다. OPEN S2 4건(GS05R-01~04), 새 제품 S0/S1 실행 발견0이며 D01~D08은 X00 결정 사항이다. 작성자는 발견 사항을 고치고 같은 검토자가 원 반례/정적 기대를 재확인해야 한다. X00만 최종 CLOSED·통합·후속 구현 배정을 결정한다.

제출 전 문서 산술·명명 집합·manifest 존재를 정적으로 대조했다. 명시 가족의 합520(선언 대비100 부족), 변이 단일23+5+9+7=44/유일44, manifest20/유일20·B 존재14/부재6이다. 대상 계약은 시작 LF hash `5b2918a9…b341`와 같았다. 이 정적 계산은 pytest 수집/실행·새 fixture·변이 실행이 아니며, 향후 정상/변이 수락을 대신하지 않는다. 최종 문서 LF hash와 HEAD는 완료 답변에서 전달한다.

관측/한계: 이번에는 제품 import·pytest 수집/실행·mutation·실제 vault/OS credential·네트워크·모델·장치·설치를 하지 않았다. 새 auth 오류 trace·지연 cleanup mutant·GUI lock 경쟁은 **정적 논증/후속 시험 설계**이며 실행 FAIL/KILLED로 기록하지 않는다. Windows native read의 취소/시간 상한·실계정 격리·외부 키 변경·실서비스/TLS·실과금·Narrator·전체 메모리 zeroization은 NOT_RUN/범위 밖이다. 허용된 인증 전달 자체와 로그/DB/GUI 출력 누출은 구분한다.


## 6. GS05-R2 — C2 계약 독립 재확인 (2026-11-26)

배정 GS05-R2, 검토자 w5:pB. **REVIEW_READY — GS05R-01~04 CLOSED(계약 정적 재확인), 새 GS05R-05 / S2 / OPEN 1건**이다. 앞 §1~5는 C1에 대한 당시 판정/근거로 원래 바이트를 보존한다. 이 절의 CLOSED는 원 발견의 계약 보강을 독립 확인했다는 뜻이며, 제품 구현·시험 PASS·X00의 최종 수락/통합 승인이 아니다. 새 경쟁 검증 명세가 닫히기 전 전체 계약 수락을 권고하지 않는다. GS11a 제품 검토는 별도 배정이며 여기서 수행하지 않았다.

### 6.1 고정 기준·입력·변경 관측

- 제품/기존 시험 기준 B:는 계속 `b77cc102a9db818a8c1d1a2840933ffa28e1b14c`의 `git show <commit>:<path>`에 실제 줄 번호를 붙여 읽은 것이다. 작업 트리의 GS11a 제품/시험을 이 기준에 합치지 않았다.
- 이번 시작 재확인 HEAD는 **`b30b3a7b7223fa20ca19ae17fe1975aa80e598f2`**다. X00의 GS04a 공개로 이전 HEAD와 달라졌으며 이를 새 제품 분석 기준으로 몰래 치환하지 않는다. 시작 `git status --short`는 수정15·미추적14, staged/unmerged 표시0이었다. Git 사용자 ignore 경로 Permission denied 경고는 읽기 환경 관측이며 제품 실패가 아니다. 다른 단위의 dirty를 변경/복원하지 않았다.
- 대상 C2:는 `docs/testing/gs05-secret-lifetime-cases.md`, **60,906 bytes/406줄**, LF SHA256 **`f3125dd7eda83a19abdbd566dcdfd1706383451e9594ff2210ad2a0d2bb763b8`**다. 원 리뷰의 보존 prefix는 **22,406 bytes/112줄**, raw/LF SHA256 **`82bd3b22bb3862b669b7175c73e1e7d649ae6f381373c5645af1fc1d8aa209b0`**다. 쓰기는 이 prefix 뒤의 재확인 절뿐이다.
- 아래 pending/협업 입력은 **2026-11-26 13:52:26 +09:00**의 별도 작업 트리 snapshot이다. 승인/보고 문서의 내용이며 현재 B 제품에서 새 기능이 실행됐다는 증거가 아니다. LF는 CRLF→LF 정규화 SHA256이며 당시 raw bytes 수와 구분한다.

| 입력 | raw bytes/줄 | LF SHA256 | 이번 사용 범위 |
| --- | --- | --- | --- |
| `build/orchestrator-tools/gs05-c2-decisions.md` | 5,590/16 | `f83667d23f16afe7c2ecb8871c0dc989e2641ecc9a27401d9d2bd915a7050348` | D01 B·D02~08, 원 발견에 대한 X00의 개정 지시 |
| `docs/collaboration/assignments.md` | 133,234/251 | `b686bacdc5a38b346369413b58c2df78b300b3dc51e00091d247c01c79f78d78` | H03 :26~27의 동결 C2/R2 범위, :84 GS04a 공개·CI 진행 중, :87 GS11a 별도 조건 |
| `docs/testing/gs04-provider-facts-cases.md` | 84,716/445 | `f7cb09fddbb716eca79a4f7a435a3607ebdc04830bc17a4e2fca406c3335f634` | :80~96 identity/수명, :292~295 04a 한계, :398 실제 UI 경로 단언 |
| `docs/reviews/gs04-provider-facts-review.md` | 14,152/105 | `b18eb3673da39d8e79679a70b3bdd5de690bc573593ecaa2285ccab869942154` | :41~47·85~105 후단 검증/독립 수락과 외부 게이트 |

C2:381의 ‘GS04a 아직 미통합’은 제출 시 관측이다. 이 snapshot의 배정표 :84는 `b30b3a7` 공개와 CI `45757743149` 진행 중을 보고한다. 이 세션은 원격/CI를 조회하지 않았다. GS04 계약 :422~445의 옛 전체 검증 미완료를 리뷰 :85~103의 후단 28,839 PASS·수락과 혼동하지 않는다. 후단 결과 역시 다른 세션의 고정 사본 보고이며 본인의 재실행이 아니다. 현재 원격 CI 완료·GS04b·실서비스 검증은 별개다.

### 6.2 원 발견별 재확인

| 원 발견 | 판정 | C2의 해결 근거와 독립 대조 | 남는 경계 |
| --- | --- | --- | --- |
| GS05R-01 분모620/520 | **CLOSED** | :3·78·184~205는 실제 기본520과 존재하지 않던100을 구분한다. A240/B40/C2 36/D45/E20/F40/G72/U16/X11=520, 보강 P45/Q20/L10/V88/S16/T20=199, 총719. old C36 ID를 폐기하고 B의 C2 36으로 대체하며 old cut2/5는 T12/16으로 인계(:203). :284~292의 primary 합도719 | 계획 ID와 실제 collection/call/deselected 감사는 별도. 의미 행을 감사 node로 채우지 않음 |
| GS05R-02 AUTH 전파 | **CLOSED** | :148~160은 missing/stale/pending→AUTH_REQUIRED, unavailable→VAULT_UNAVAILABLE, malformed/UTF8/backend→VAULT_READ_FAILED를 gateway와 Run/provider에 동일하게 고정한다. known=true·retryable=false·RESERVED80/UNKNOWN0·유효 Job BLOCKED/AUTH·Attempt FAILED. 실제 adapter→Run→Gateway→Job P45와 post-H Q20을 분리(:238~240). C2-M02~04(:327~329)가 raw 정규화·known 전파·UNKNOWN 우선순위를 각각 겨냥 | jobs/failures.py 확대 없이 gateway에서 raw invalid를 먼저 좁게 변환하고 Run의 닫힌 AUTH3+known 분기를 보존하는 제안이다. 실제 연결/실패 결과는 미검증 |
| GS05R-03 중간 cleanup | **CLOSED** | :130~134는 첫 write 반환 직후/B2·read 전의 lease secret slot None·민감 dict/closure·transport auth 항목0을 지정한다. L10(:242)은 F0/request finally 전 Event 대기 중 관측한다. C2-M01(:326)은 cleanup을 request finally로 늦추어 그 중간 call assertion에서 실패하도록 정의 | OS/HTTP 내부·fake 관측 원본·기존 hints256은 별도이며 전체 메모리 제거가 아니다. 미래 구현의 실제 검사 면/fixture는 고정 필요 |
| GS05R-04 UI 보안 진입 누락 | **CLOSED** | :138~142는 모든 action·snapshot/cost-policy·scope/select/retry·생성자·success/failure refresh·signal 연쇄까지 worker 소유로 지정한다. V88(:246~252)는 grant/budget/refresh/reset/adopt/settle 및 조회 trace 각각, STT/summary·세대·native/동일 DB coordinator 지연을 분리한다. C2-M05~07(:330~332)이 refresh/_cost_policy/grant 각 경로만 GUI로 되돌린다 | GUI 금지 진입 순간 spy/call assertion과 실제 worker 양성 진입이 필요하다. 모든 버튼 disable·timeout·Qt 예외만으로 대체하지 않는다. 제품/시험 검증은 미수행 |

B:security/vault.py:131~144, providers/_common.py:254~289, jobs/failures.py:14·90~120을 다시 대조했다. gateway 선행 정규화는 raw VAULT_INVALID_VALUE→TASK_FAILED 문제를 막고, Run의 AUTH3/known 보존은 기존 safe-list fallback UNKNOWN 문제를 해결하는 방향이다. B:app/ai.py:305~325는 예약 뒤 remote_intent를 기록하고 기존 context 필드만 복사한다. :61~78·505~519·563~567·694~704의 outcome/error 전달은 known-unsent와 실제 UNKNOWN을 구분하므로, C2:160의 ‘remote_intent 존재만으로 UNKNOWN으로 만들지 않음’과 P/Q의 실제 Job 결과 관측이 필요하다. 이 문서만으로 현재 gateway에 resolver가 구현됐다고 세지 않는다.

기존 기대 변경은 여전히 명시 승인이 필요하다. B:tests/ui/test_privacy_ui.py:196~197의 준비 중 AUTH_REQUIRED, tests/unit/test_providers.py:203~209의 raw auth context 허용, tests/integration/test_egress_independent.py:267·277의 실제 키 header 보관은 C2:53~63·75·361~368의 세 기대 변경 대상과 일치한다. 설정/config_key 불변·endpoint scope·원본·철회 차단·UNKNOWN·CAS 단언까지 삭제/약화할 근거가 되지 않는다. 실제 실패를 실행한 기록은 없다.

### 6.3 D01 B ticket·철회/삭제/녹음·인증 경계

B:ui/ai_bridge.py:1240~1249는 revoke_session 뒤 cancel_session이며, B:security/consent.py:715~722의 revoke는 coordinator를 잡는다. B:ui/main.py:941~947·1183~1189는 그 뒤 recorder.close와 delete/retry를 호출한다. 이 정적 순서에서 A의 native read 중 coordinator 보유는 제어 진행을 지연시킬 수 있다. D01 B를 수용하며 A의 Q 대기/commit 뒤 physical read0을 다시 요구하지 않는다.

C2:101~116·217~222는 I→U→R/r→O→H/B→F에서 (1) Q 전/후 I, (2) I 뒤 U 전 사건, (3) U 마지막 승인 후 Q commit/실제 R 진입, (4) R 정지 중 Q commit, (5) O 뒤 H 전, (6) H/B1 뒤 사건을 구분한다. U→R 사이의 늦은 **R1**은 허용하되 반환값 discard1·후속 송신0을 요구한다. 기존 A의 결과를 B 증거로 재사용하지 않는다. C2-M13/14는 native 입장 held locks=[]와 invalid 값의 다음 continuation 제공0을 call assertion으로 검사하므로 뒤 O guard가 우연히 차단해도 r 위반을 숨길 수 없다. 다만 **동일 ticket의 두 경쟁 소비자는 아래 GS05R-05가 남는다.**

T13~15(:272~280)는 지연된 fake native R이 반환하기 전에 revoke commit·정상 source/consumer/sealer ACK·before_delete/close·durable intent/fence가 진행하는 실제 경로를 요구한다. 진행 중 AI reader는 실제 종료 전 ACK0/DELETE_PENDING이며 강제 해제·DELETED_LOCAL로 만들지 않는다. Event.set은 취소 의도이고 native call 종료 ACK가 아니다. handoff 뒤 노출은 유지하며 F의 늦은 성공 채택0이다. main.py/recording/storage를 고치지 않고 합성 fixture로 실제 공개 제어 흐름을 부르는 계획이며 범위 밖 수정이 필요하면 먼저 보고한다.

D06(:120~126·256·276~278)의 동일 provider+endpoint 단일 FIFO 실행자·짧은 pending/epoch 상태 전이, native set/delete 동안 공용 잠금0, 다른 endpoint 진행, 실패도 epoch/revoke rollback0, pending 중 app grant와 I/U 거부는 읽기 B와 일관된다. 이미 소비한 read가 native 변경과 겹치더라도 r/O가 old epoch 값을 폐기한다. 접수 성공 시 clear와 queue 거부 시 원문 보존을 S16/C2-M08~09가 분리하고 native 완료 전 ACK를 만들지 않는다. actual native 취소/상한·앱 밖 무통지 변경을 보장하지 않는다.

### 6.4 719행·61변이·20파일 정적 감사

독립 손 literal 범위로 구성한 tagged tuple의 문서 산술은 **총719/고유719**였다. 기본9가족520+보강6가족199=15가족이며 명시 bound의 excluded0/feasible719와 OS 스케줄 전체 비전수(:205)를 구분한다. family 간 동일 현상을 다시 관측하더라도 tagged 의미 ID는 primary 파일 하나에만 배정한다. primary는 unit323(A240+E20+F40+X11+T00~11 12), integration200(B40+C2 36+D45+P45+Q20+L10+T12/16/18/19 4), property72(G72), UI124(U16+V88+S16+T13/14/15/17 4)로719이며 T00~19는 중복/누락 없이20이다. 이 감사는 pytest collection 또는 실제 param ID가 이미 존재한다는 증거가 아니다.

변이 명명도 single23(M01~26 중 M20/22/24 제외)+M20-02~06 5+M22-03~11 9+M24-00~06 7=44, C2-M01~17 17을 더해 **61/유일61**로 정합하다. 의미 행719와 변이61은 다른 분모다. 각 사본 하나의 결함·정상본 목표 PASS·목표 call assertion FAIL을 요구한다(:344~346). import/syntax/ACL/timeout/teardown만 실패한 INVALID는 검출 증거가 아니며 선언된 변이 수가 실제61 KILLED라는 뜻도 아니다. 기존 vault.py는20파일 밖이므로 M07 등의 실제 source seam을 X00에게 먼저 고정해야 한다.

정확 manifest(:354~375)는 제품7+기존 시험8+신규 시험4+계약1=**고유20**으로 C1과 경로가 같다. `git cat-file -e B:<path>` 정적 존재 대조는 B에14 존재/6 MISSING이었다. 없는6은 security/credentials.py, 신규 unit/integration/UI/property test_secret_lifetime 계열4파일, 계약 자체다. 이를 이미 구현/실행된 것으로 세지 않는다. 기존 제품6과 시험8은 존재만 확인했으며 새 수락 조건을 이미 단언하지 않는다. jobs/failures.py·app/ai.py·runner·vault/_secrets/consent/ledger·main/recording/storage는 계속 범위 밖이다.

Gateway-bound auth carrier와 for_session 보존(:95~99·335)은 B:app/ai.py:305~325의 field 복사로 새 context-only ref가 사라지는 문제를20파일 안에서 피하는 합리적 제안이다. B:security/gateway.py:82~114의 clone 생성에 현재 auth carrier는 없으므로 실제 API/정확 전달은 후속 검증 대상이다. 새 공용 GatewayLike 인자를 기존 fake에 암묵 강제하거나 config/body에 ref를 숨기는 구현은 수락 근거가 없다.

신규4시험 fixture 포함 wall60초(:385~389)는 **측정0인 제안**이다. 보강199·UI124·실제 provider/Job/control fixture 비용을 따로 계측해야 하며 의미 행/ACK/양성 대조를 줄여 맞추지 않는다. 고정 archive+정확 승인 파일의 TEMP, cwd/rootdir/config/PYTHONPATH와 부모·실제 spawn import 출처, 부분 선택/실행 ID 감사, cache off/고유 basetemp/offscreen/ResourceWarning 오류화, core.yml flags·coverage85·check_coverage7묶음·offline wheel은 후속 허용 검증의 조건이다. 이번 실행 수는 전부0이다.

### 6.5 GS05R-05 / S2 / OPEN — 두 경쟁 소비자의 단회 전이 반례가 명시되지 않음

- 근거: C2:107은 ‘동시에 두 소비자가 이길 수 없음’을 보장한다. 그러나 T00(:262)은 ‘같은 ticket을 두 번 소비’와 두번째 AUTH_REQUIRED/R합1만 적고 **동시 contender/상태 확인과 commit 사이의 강제 순서**를 정하지 않는다. primary는 unit의 test_ticket_once(:286), 변이 C2-M11(:336)은 CONSUMED CAS 생략이다. T01~19는 다른 scope·정책·제어·native 변경 경합이며 같은 ticket의 두 소비자 경쟁을 별도 강제하지 않는다.
- 독립 정적 반례(실행 아님): 원자 CAS를 `if state == ISSUED: state = CONSUMED`라는 분리된 check-then-act로 바꾼다. 순차 T00은 첫 소비 후 상태가 CONSUMED여서 두번째를 거부하므로 R합1을 만족한다. 경쟁에서는 A가 ISSUED 확인→B도 ISSUED 확인→A/B 각각 CONSUMED 기록/실제 R 진입으로 R합2가 가능하다. 뒤 reservation/permit guard가 송신을 막더라도 최소 native 읽기·단회 ticket 규칙 위반은 남는다. 단순 CAS 완전 삭제만 죽인 결과로 이 경쟁 결함까지 검출했다고 할 수 없다.
- 변경 요청: **기존 T00을** 동일 ticket의 두 경쟁 소비자와 종료 뒤 replay를 포함한 명시 bounded trace로 구체화하고, 두 contender가 경쟁 gate에 실제 도달하는 양성 관측·한 전이 승자/한 AUTH_REQUIRED·native R합1·추가 lease/송신0을 고정한다. C2-M11도 단일 결함 ‘원자 단회 전이→분리 check/commit’으로 명확히 하여 두 소비가 성공하는 오구현의 실제 call assertion에서 FAIL하도록 한다. 정상 구현의 mutex 안에서 서로 barrier를 기다리게 하거나 timeout만으로 실패시키면 INVALID다. 결정적 scheduling/관측 seam의 정확 위치는 구현 API 승인 때 고정한다.
- 분모 영향: 위 방식은 named T00 한 bounded trace와 C2-M11의 의미 구체화이므로 **719행/61변이/20파일 유지안**이다. 독립된 신규 의미 행/변이를 택하면 입력/ID/feasible·oracle·primary와 총계를 먼저 재제출해야 한다. 이 리뷰는 계약을 직접 수정하지 않았다.
- 닫힘 기준: 작성자의 계약 보강 뒤 독립 정적 재확인으로 이 명세 OPEN을 닫는다. 실제 정상/변이 검출·경쟁 안전은 후속 구현/시험의 별도 게이트다. 현재 제품에서 경쟁 오류나 비밀 유출을 실행 재현했다는 주장이 아니다.

### 6.6 GS04a 접점·착수 선행·제출 판정

직접 공유 파일은 ui/privacy.py다. GS04 계약 :398의 **실제 timer 만료·실제 설정 키 입력·grant/revoke/save/delete 후 UNKNOWN** 단언을 worker model 이행에서도 보존해야 한다. :80~96의 exact identity/credential·consent 세대, 만료300초 미만·late callback 차단·무자동 재조회와 :292~295의 production registry 비어 있음/metadata 송신 API 없음/actual_service_status NOT_RUN도 그대로다. 새 저장 pending/epoch·callback이 옛 OBSERVED를 되살리거나 서버 신뢰 안내를 지우지 않아야 한다. GS05는 GS04b route/probe/비용 정책이나 실제 서비스 인증을 추가하는 배정이 아니다.

구현 착수 전에 X00가 (1) GS05R-05 재확인과 공용 계약 수락, (2) GS04a 공개판의 정확 HEAD·허용 source hash·최종 CI 인수, (3) Gateway-bound auth carrier/for_session·ticket 단회 전이와 소유·FIFO/pending gate·관측 seam의 정확 API/manifest, (4) 기존 세 기대 변경과60초 제안, (5) GS11a 최종 control/deletion/reader ACK 회귀 기준을 인수하는 순서를 확정해야 한다. GS11a 미통합 원위치 staged/negative fence/UNKNOWN을 이 문서로 승인하거나 reader 종료 전 삭제 허용을 만들지 않는다. G09a와 gateway는 직렬 소유하며 ref/ticket/process-local credential epoch는 복원 가능한 권한·schema/backup component로 승격하지 않는다. 범위 밖 source/기존 시험의 실패는 파일·실패·변경안을 먼저 보고한다.

제출 판정은 **REVIEW_READY / 원 GS05R-01~04 CLOSED, 새 OPEN S2 1건(GS05R-05), 제품 구현 승인 전**이다. 수집/시험/변이·제품 import·실제 vault/네트워크·설치/모델/장치/유료 호출·Git 쓰기는0이며 문서 산술/기준 소스 읽기만 수행했다. 전체719 실행·61 검출·60초·coverage/CI/wheel·실제 native 지연/취소·앱 밖 키 변경·OS/HTTP/Python 전체 메모리 제거는 NOT_RUN/UNVERIFIED다. 최종 승인·계약 반영·Git 통합은 X00 소관이며 후속 명시 배정 전 쓰기 없이 대기한다.


## 7. GS05-R3 — GS05R-05 한정 C3 독립 재확인 (2026-11-26)

**REVIEW_READY / GS05R-05 CLOSED(계약 정적 재확인), 이번 범위 새 OPEN 0건**이다. 검토자 w5:pB는 H03 GS05-R3에 따라 C3의 T00·C2-M11 보강과 분모/파일 보존만 재확인했다. 앞 §1~6의 R1/R2 바이트와 당시 OPEN 판정은 이력으로 보존하며, 최신 계약 판정은 이 절을 따른다. 실제 경쟁 안전·정상본 PASS·mutation KILLED·X00의 최종 수락/구현 승인을 뜻하지 않는다.

### 7.1 고정 입력과 범위 보존

- 2026-11-26 14:03:20 +09:00 관측: cwd `D:/project/Recoryn`, HEAD `b30b3a7b7223fa20ca19ae17fe1975aa80e598f2`, dirty 수정15·미추적14·staged/unmerged 표시0이다. 제품/기존 시험 근거 기준은 지시대로 `b77cc102a9db818a8c1d1a2840933ffa28e1b14c`를 유지하며 새 HEAD나 GS11a dirty를 합치지 않았다.
- 대상 C3: `docs/testing/gs05-secret-lifetime-cases.md`, 66,063 bytes/418줄, LF SHA256 **`3bcef72bf706c4f13902e4ac035c061b600ae9f09f2bcfb96bb1b519c524a5c6`**. 아래 C3:줄은 이 고정 입력의 실제 줄이다.
- 보존할 R2 리뷰: 39,575 bytes/184줄, LF SHA256 **`b1b1dc26897c796677a889cd2c632d46daba5b80a108a18676f56b487681a34f`**. 쓰기는 그 뒤 이 재확인 절뿐이다.
- 배정표는 위 시각의 작업 트리 snapshot 134,004 bytes/253줄, LF SHA256 `80c777685085d49055db068bd1e0fe98c12bb93499f7a405d7cb07463d66ff1f`이며 :27~29에서 R2 동결·C3 hash·R3 한정 범위를 확인했다. 공용 문서를 수정하거나 원격 CI를 조회하지 않았다.
- 독립적인 문서 차이 감사로 C3 제목, :68~69의 입력/범위 설명, :264의 T00 행, :282~291의 상세 보강, :348의 C2-M11 행만 이전 내용으로 메모리에서 복원했다. 그 결과 LF SHA256는 원 C2 **`f3125dd7eda83a19abdbd566dcdfd1706383451e9594ff2210ad2a0d2bb763b8`**와 정확히 일치했다. 디스크의 계약은 그대로 두었으며 다른 가족/oracle·manifest가 조용히 바뀌지 않았음을 정적으로 확인했다.

### 7.2 GS05R-05 CLOSED의 근거

| 원 반례/요구 | C3 근거 | 독립 재확인 |
| --- | --- | --- |
| 같은 ticket을 순차 두 번만 소비하면 check-then-act 경쟁을 놓침 | :264·282 | 단일 ISSUED ticket·동일 유효 권한/기한/epoch/scope로 A/B가 실제 소비 호출을 각각 수행한다. 원자 전이 직전 잠금 밖 gate의 두 진입을 관측하므로 단순 thread 생성/순차 replay로 대체되지 않는다. 정상 소비·실제 fake vault read·앱 lease 생성 경로를 호출하며 CAS 결과를 fixture가 꾸미지 않는다 |
| 경쟁의 독립 기대와 실제 native/lease 관측 | :282~284 | 승자 A/B identity를 정하지 않고 성공1·AUTH_REQUIRED1·전이 승인1·native read 합1·lease 생성 합1을 요구한다. unit trace는 network를 호출하지 않아 DNS/O/H/B 합0이며, 패자의 추가 read/lease/송신0을 별도로 본다. 뒤 network guard가 막아도 선행 read2/lease2는 실패다 |
| 완료 후 replay가 실제 terminal 상태를 검사해야 함 | :284 | A/B 모두 실제 종료하고 승자 lease 정리·잔여 lease0을 확인한 뒤 세 번째 동일 ticket 호출을 한다. replay AUTH_REQUIRED·추가 승인/read/lease/송신0, 최종 read/lease 합1이다. 경쟁 중 두번째 호출을 종료 후 replay로 대신 세지 않는다 |
| 단일 비원자 변이를 결정적으로 드러내야 함 | :286~288·348 | 정상 check+commit은 한 원자 연산이며 내부 hook은 비차단 기록만 한다. mutant만 ‘ISSUED 확인 후 잠금 해제→재검사 없는 commit’으로 분리한다. A의 확인 뒤/commit 전 잠금 밖에서 A를 멈추고 B의 실제 ISSUED 확인을 기록한 뒤 양쪽 commit을 진행시켜 원 반례의 두 선행 확인 이력을 만든다. 같은 observer는 정상본의 원자 연산을 쪼개거나 상태를 대신 변경하지 않는다 |
| mutex barrier/timeout으로 얻은 실패는 검출 증거가 아님 | :286~290 | 대기는 모든 서비스/정책 잠금 밖 상태 연산 경계에서만 허용한다. 정상본 목표 PASS 후 별도 TEMP 사본에 단일 결함을 넣어 실제 call 결과의 consume_successes==1 및 native_reads==1/leases_created==1 assertion FAIL을 요구한다. 경쟁 진입/상태 이력이 없거나 import·timeout·teardown·잠금 안 barrier만 실패하면 INVALID다. 실패 시에도 barrier/worker/lease를 finally에서 회수한다 |

원 R2의 정적 반례 ‘A/B가 모두 ISSUED를 읽고 각각 CONSUMED를 기록’이 C3:288의 명시 mutant 순서와 직접 대응한다. 이 명세대로 수행하면 단순 CAS 완전 삭제의 검출이나 후단 송신 차단으로 경쟁 결함을 숨길 수 없다. 따라서 **GS05R-05의 검증 명세 누락은 CLOSED**다. 실제 seam API/소스 위치·잠금 미보유 증거는 구현 승인 때 고정해야 한다. 숨은 외부 잠금으로 이력을 만들 수 없으면 C3:288대로 seam·실패·변경안을 먼저 보고해야 하며, 그 상태를 검출 완료로 계산하지 않는다.

### 7.3 분모·범위·미검증

C3:68·184~205·298~308·366~387을 대조했다. 기본520+보강199=**719행/15가족**, primary **323+200+72+124=719**, 변이 **23+5+9+7+17=61**을 유지한다. T00은 경쟁→양쪽 종료/lease 정리→replay를 담은 기존 named trace 한 행이며 primary는 기존 unit test_ticket_once다. C2-M11도 기존 변이 한 개의 결함 의미 구체화다. 별도 새 행/변이를 추가하지 않았다. 정확 §8.1의 경로는 제품7+기존 시험8+신규 시험4+계약1=**20/고유20**이며 C2와 동일하다. 문서 산술/정적 차이 감사이며 실제 collection·call·분모 실행/검출 감사는 아니다.

GS05R-01~04는 R2의 계약 정적 CLOSED를 유지한다. 이번 범위에서 새 OPEN은0이며 X00의 최종 공용 계약 수락·GS04a 정확 통합/CI 기준 인수·API/manifest/시험 기대/예산 승인과 GS11a 회귀 기준 인수 조건은 R2 §6.6 그대로다. GS11a의 새 검토나 후단 CI 확인을 이번 좁은 재확인에 합산하지 않는다.

**제품·시험·Git 수정, 시험 수집/실행·mutation 실행·제품 import는0**이다. 실제719행·61변이·wall60초·coverage/CI/wheel·실제 vault/서비스/모델/장치·전체 메모리 제거는 이번에 검증하지 않았다. 저장소 쓰기는 기존 리뷰 prefix를 보존한 이 끝 절 하나뿐이며, 제출 후 읽기 전용으로 대기한다.

## 8. GS05-IMPL-R1 — 동결32 구현 독립 검토 (2026-11-26)

### 8.1 배정·고정 입력·결과 경계

w5:pB / GS05-IMPL-R1. 기준 HEAD는 `b30b3a7b7223fa20ca19ae17fe1975aa80e598f2`이며 시작 및 재확인 시 동일했다. 공유 작업 트리에는 GS05와 GS11a 등의 변경이 섞여 있으므로 이를 통합 구현으로 세지 않았다. 저장소 쓰기는 이 리뷰의 끝 절만이다. 기존 **46,091바이트/217행**, LF SHA256 `a4c29169b7d77920f4e2676b747743f8ab69557021c95db06bc1685641d927d4`를 바이트 그대로 보존한다. 제품·배정 시험·공용 계약·Git 쓰기는0이다.

배정된 원 manifest는 `%TEMP%/recoryn-gs05-94f2f62e8176402ab606843b483eb349/final-submission32-lf.json`, LF **`ab2c7c689cf910b3744168846e47ea9b0269fa5aa895f8a44d7b63042b7343c1`**다. 2026-11-26 18:01:37 +09:00에 기준 archive와 이 목록의 정확32파일을 새 OS TEMP `C:/Users/gangd/AppData/Local/Temp/recoryn-pB-gs05-r1-j1j75f8_`에 구성했다. 원 패키지의 실제 대응 하위 경로는 `submission-ci-tree`다. 패키지 루트나 다른 `tree`를 같은 입력으로 대체하지 않았다. 구성 당시32/32 및 검토 종료18:16:03 +09:00의 격리 사본32/32 해시가 원 목록과 일치했다. 이후 이 절의 파일:줄 표기는 별도 언급이 없으면 **이 격리 사본** 기준이다.

정확 범위는 제품9+기존 시험18+신규 시험4+계약1=32다. C4의30파일에 명시 승인된 `app/desktop.py`와 `test_publication_independent.py`를 더한 범위이며, GS11a 파일은 얹지 않았다. 계약 snapshot은 LF `7504c5ba15384c1cacba1baa5b70826798e447326833dcbf4ff2c829d723a7d4`의 C4다. 작업 트리의 후속 결과 절/작성자 CI66 기록은 이 동결 입력이나 독립 실행 증거로 바꾸어 세지 않았다.

재현 메타데이터·실행 argv·별도 하네스·JUnit·ID 감사는 위 TEMP에 보존했다. 최종 증거 `pB-final-review-evidence.json` LF SHA256은 **`0787b3992a641edf905a65bc26076fcf5d9d474e45aa14dcc1fe1a60f3006227`**다. 입력32파일의 전체 해시, 변경 전후 assertion AST 차이, 실행 결과와 아래 후단 manifest 변동을 함께 담는다.

### 8.2 권한·ticket·비밀·비용의 구현 대조

| 경계 | 실제 구현 근거 | 독립 판정 |
| --- | --- | --- |
| 공개 DTO와 고정 권한 | `providers/contracts.py:152`, `ui/privacy.py:479`·507·528·581, `security/credentials.py:39`·46·52·59 | GUI는 입력/plan/auth 참조를 고정하고 실제 정책·비용 준비는 worker가 수행한다. ExecutionContext에 원문 인증을 보관하지 않으며 요청·target·body digest·reservation·deadline을 ReadScope로 묶는다. 원문 헤더 주입은 DTO/gateway 경계에서 거부한다. |
| 단회 소비와 replay | `credentials.py:272`·283·305·361·368, `gateway.py:313`·329·333·338·345 | I/U의 정책·ledger 재검사와 ticket CAS가 짧은 잠금 안에 있고 R의 native get은 그 밖이다. owner/object/정확 scope/epoch/plan/deadline을 검사한다. 경쟁 두 소비자와 종료 후 replay는 별도 호출로 다뤄지며 뒤의 송신 차단만으로 CAS의 성공 수를 대체하지 않는다. |
| R 중 철회·키 변경 | `credentials.py:305`·324·376·393·434, `gateway.py:342`·345 | native read와 native key set/delete는 정책 coordinator 밖이다. 키 명령 수락 시 pending fence가 먼저 닫히고 실제 worker가 epoch/동의를 무효화한다. R 반환 뒤 r에서 권한/비용을 재검사한다. R의 임시 producer lease 생성 자체를 O 송신 권한으로 세지 않는다. r 실패 시 lease를 버리는지와 open0을 확인했다. |
| I/U/r 비등록, O 등록 | `ledger.py:1018`·1084·1118·1146·1182·1226, `gateway.py:313`·351 | preflight는 quote cache를 소비하거나 dispatch DML을 등록하지 않고 prior deadline을 연장하지 않는다. O는 현 catalog를 다시 비교하고 dispatch를 한 번 등록한다. r 성공 뒤 catalog 변경을 놓치는 옛 API-R01 반례를 독립 fake로 확인했다. 기존 예약 비용은 AUTH 미송신 때도 자동 환불하지 않는다. |
| 첫 write·응답의 비밀 정리 | `credentials.py:101`·128, `gateway.py:255`·395·403·453, `transport.py:78`·90·93·113 | 첫 write의 finally에서 gateway lease/인증 헤더를 제거하며, transport는 첫 write의 finally에서 자체 헤더와 http.client buffer를 비운다. 두번째 body/응답 직전의 실제 슬롯 상태를 확인했다. 이 관측은 Python/OS 전체 메모리의 물리적 소거 보장이 아니다. |
| 금전·UNKNOWN·오류 전파 | `gateway.py:237`·419·426·456·478, `providers/_common.py:242`·285, `ledger.py:1348` | 첫 handoff 뒤 UNKNOWN 노출을 보존하고 AUTH3의 알려진 미송신 의미를 통일한다. finish_dispatch의 메모리 정리는 durable 예약 취소/환불과 구분했다. native 예외 원문 대신 안전한 오류 코드를 전달한다. |

제품 근거는 위 동결 사본의 소스이며, 실행 근거는 §8.4의 독립 기록이다. 위 표의 각 행이 모든 장애/모든67변이에 대한 독립 실행 완료를 뜻하지 않는다.

### 8.3 Qt·삭제 실제 ACK와 기존 oracle 보존

`ui/privacy.py:258`의 worker 제출과 `:1487`·1517의 결과 수신은 GUI 의도와 후단 조회를 구분한다. `:1675`의 키 명령은 bounded queue가 수락한 뒤에만 입력을 지우고 안전한 결과만 전달한다. `PrivacyBackend.begin_shutdown/await_shutdown`과 `credentials.py:485`·491은 실제 active/native/request 수가 남아 있으면 ACK를 완료하지 않는다. `ui/ai_bridge.py:1576`은 준비 취소→Qt pool→실제 AI service→privacy backend ACK 뒤 store/history를 닫는다. 독립 시험에서는 native key write를 막은 동안 await_shutdown이 false이고 실제 반환 뒤에만 true인지 확인했다.

`tests/ui/test_secret_lifetime_ui.py:615` 이하 T13/T14/T15는 실제 MainWindow/RecordingService/JobStore를 쓰며 입력 장치만 SyntheticSource다. `:672`·676의 실제 reader 등록, `:689`의 실제 종료, `:723`·737의 DELETE_PENDING, `:738`의 source ACK, `:739`의 read 미완료/local_reader_active, `:752`의 실제 reader 종료를 함께 단언한다. 종료 편의를 위한 callback 한 번이나 fixture 정리를 삭제 완료로 세지 않는다. 승인 추가 파일 `app/desktop.py:361`은 삭제 intent의 정확 StateConflict에서 source 종료 뒤 실제 writer/sealer join만 수행하며, 이미 fence된 세션을 다시 finalize하지 않는다. 다른 StateConflict는 삼키지 않는다.

기존18시험 파일을 기준 b30b3a7의 AST와 정적으로 대조했다. **15파일은 assertion AST multiset이 그대로**다. 특히 a11y 215/215, AI 독립136/136, publication51/51, resource policy UI74/74, local notice28/28을 보존한다. 이 수치만으로 fixture 의미 보존을 승인하지 않고 실제 diff도 읽었다. a11y의 모달/키 입력 뒤 기다림, AI의 고정 gateway/prepare worker 호출, publication의 fake auth binding 추가는 원 oracle을 바꾸지 않는다. GS11a receipt/TTL 적응은 이 snapshot 밖이다.

나머지3파일은 의도된 새 경계에 맞춰 다음을 변경했다. `test_privacy_ui.py:215`는 prepare 시 AUTH 실패 대신 secret-free context/read0을 확인하고 실제 예약 후 요청에서 AUTH 실패를 확인하며, Ollama의 무비용 관측은 worker helper로 이동했다. `test_consent_scope_ui.py:348`·364는 정책 변경으로 예약 전 차단되면 native read0, 실제 송신이면 read1을 요구한다. `:457`·462는 GUI에서 prepare0→고정 A intent의 worker prepare1을 확인하고 원 A 세션/송신 body oracle을 보존한다. 요청 없는 prepare의 옛 read1은 read0으로 바꿨다. `test_egress_independent.py:273`·283은 DTO에 옛 Bearer가 남는 가정 대신 빈 headers/read0을 요구하며, 실제 요청의 송신/차단 assertion은 남긴다. 기존 시험 전체를 이번 선정 실행에 포함했다고 주장하지 않는다.

### 8.4 실제 선정 실행·독립 반례와 선택 감사

기준 archive+원32 사본에서 `D:/project/Recoryn/.venv/Scripts/python.exe`를 사용했다. cwd/rootdir/pytest 설정은 사본이며 PYTHONPATH는 사본 src다. 실제 부모 PID46288와 spawn 자식 PID50080의 recoryn/credentials/gateway/ledger/privacy import가 모두 사본 src임을 `pB-origin.log`에 확인했다. `-p no:cacheprovider`, 고유 OS TEMP basetemp, `QT_QPA_PLATFORM=offscreen`, `-W error::ResourceWarning`, offline 환경을 적용했다.

선정 분할은 실행 전 `pB-review-plan.json`에 고정했다. unit335 + integration165(P45/Q20/K50/L10/C2-36/T4) + UI124 = **624**다. 전체781에서 이번에 제외한157은 B40/D45/G72다. 이 제외는 새 feasible 분모나 계약 변경이 아니며, 전체 독립 검증으로 확대해 세지 않는다. 기대 ID는 제품 enum/TEMPLATES/parser와 분리한 손 literal 축으로 만들었다.

- `pB-selected.xml`: **624 PASS**, fail/error/skip0, JUnit43.864초, process wall45.421초. `pB-selected-audit.json`에서 exact624 수집/고유624 call/각1회/PASS를 확인했다. 누락·초과·중복 ID·setup/teardown 실패0, 수집 파일은 모두 사본 아래다.
- `pB_independent.py`는 작성자의 secret_world/fixture를 가져오지 않고 별도 fake target/body/금액과 실제 ConsentStore/CostLedger를 구성했다. `pB-independent.xml`: **10 PASS**, fail/error/skip0, JUnit2.043초, process wall2.744초다. 10은 계약 행 추가가 아니라 검토용 probe이며 781에 합산하지 않는다.
- 독립 probe는 R 중 철회 완료와 coordinator 미보유/RESERVED13·미송신·witness 불변, 경쟁 두 소비자+종료 replay, request/body/reservation 교차3종 거부, r 성공 후 catalog 교체 거부, cache miss/재개 preflight의 deadline1010 보존·등록0→O1, 첫 write 뒤 lease/headers 정리와 UNKNOWN13, native 지연 중 shutdown ACK 미완료, 실제 127.0.0.1 loopback HTTP write 직후 인증 슬롯/buffer 정리를 확인했다. loopback 서버는 이 probe가 소유한 것만 종료했다.
- 최초 독립 하네스의 PrivacyBackend 생성에서 필수 `gateway` 인자를 빠뜨려 1실패/8성공이 있었다. 제품 실패가 아닌 TypeError이며 `pB-independent-first-harness-error.log/xml`를 보존했다. TEMP 하네스에 `gateway=None`을 명시한 뒤 위10개가 통과했다. 원 제품/시험을 수정해 이 오류를 가리지 않았다.

독립 기대와 선정/call 감사가 있어 단순 수집 성공, 다른 checkout import, 목표 행 미실행, timeout/teardown 실패를 PASS로 세지 않는다. **이번에는 mutation을 실행하지 않았다.** 작성자67변이 기록이나 계획을 독립 검출 PASS로 재인용하지 않는다. 향후 변이 확인도 각 새 사본의 단일 결함에서 목표 call assertion FAIL이 필요하며 import/선택/잠금 안 barrier/timeout 오류는 INVALID로 구분해야 한다.

### 8.5 판정·후단 입력 변동·인수 조건

**배정된 ab2c…43c1 동결본의 이번 범위에서 새 제품 OPEN은0, REVIEW_READY다.** 원 GS05R-01~05의 계약 정적 CLOSED와 실제 구현 검토 범위를 구분한다. 전체781/67변이·coverage85/check_coverage7·wheel·작성자 CI66를 독립 재실행한 결과가 아니며, GS11a 합성 gate/스케일/L30/TTL 및 실제 Windows Credential Manager·음성/모델/외부 서비스는 미검증이다. GS11a와 합친 최종 승인/통합은 X00 소관이다.

다만 종료 재해시에서 **제출 정합 확인1건(PENDING/X00 결정 필요)**을 발견했다. 18:16:03 +09:00에 원 패키지 manifest는 LF `aa241d3df82671fa6b470f9252ec24104fa1d6bc64025a8ae264a918a96f84f2`로 바뀌었고, 차이는 `tests/integration/test_ai_independent.py`의 **f6e6dbe7…3052f7b → 6c07dfb0…ff1173** 한 항목이었다. 계약 결과 절 추가와 다른 시험 입력 변경이다. 새 파일은 settle_privacy import와 기존 durable grant 단언 전 실제 policy worker ACK 기다림1회를 추가한다. 정적 diff에서 원 assertion 변경은 없지만, **이 후단 파일을 실행/재인수하지 않았다.** 따라서 기존624+10 PASS를 새 manifest 전체의 검증으로 옮겨 붙일 수 없다.

원 manifest는 구성 시 기록한 ordered mapping에서 LF 정규화 JSON을 복원해 원 ab2c 전체 해시 일치를 확인한 `pB-original-submission32-lf.json`으로 보존했다. 후단 manifest와 시험은 `pB-later-submission32-lf.json`·`pB-later-test-ai-independent.txt`로 따로 snapshot했다. 위 최종 증거 JSON에 양쪽 hash/시각/정확 차이를 고정했다. X00는 최종 제출할 manifest를 선택하고, 후단 ACK 적응을 채택하면 해당 시험의 필요한 독립 확인과 GS11a 합성 게이트를 별도로 닫아야 한다. 이 pending을 제품 결함이나 원 동결 사본 오염으로 오인하지 않는다.

추가 구현·공용 계약 수정은 하지 않는다. 이 끝 절 제출 후 읽기 전용으로 대기한다.

## 9. GS05-IMPL-R2 — 두 시험의 실제 정책 ACK 적응 재확인 (2026-11-26)

### 9.1 고정 입력과 좁은 차이

w5:pB / GS05-IMPL-R2. 시작18:45:31 +09:00 및 종료 재확인 HEAD는 `b30b3a7b7223fa20ca19ae17fe1975aa80e598f2`다. 공유 dirty는 GS05/GS11a 등이 혼재한 채이며 통합 근거로 쓰지 않았다. 리뷰 R1까지의 **59,173바이트/275행**, LF `273247f7777893c69d914a3a6039e128bd013a973fd0d7c44a32f50f98efb352`를 그대로 보존하고 이 끝 절만 추가한다.

지정된 기존 TEMP 패키지 `final-submission32-lf.json`의 최신 LF는 **`31b20286d418c7893d5a45ba0a9218489a5cdfe64fe33e8680231bf34331cbf0`**다. 새 `git archive b30b3a7` 사본 **`C:/Users/gangd/AppData/Local/Temp/recoryn-pB-gs05-r2-p908jy7v`**에 패키지 `submission-ci-tree`의 정확32파일만 얹고 각각의 LF 해시를 확인했다. 아래 소스/시험 파일:줄은 이 사본 기준이다. 원 R1 ab2c…43c1의 ordered mapping과 비교해 **제품 전부를 포함한30파일 동일**, 변경은 다음2개뿐임을 확인했다.

| 파일 | R1 LF SHA256 | R2 LF SHA256 |
| --- | --- | --- |
| `tests/integration/test_ai_independent.py` | `f6e6dbe7158faa6b55bde11850475476073f9b4a94c53eac0e8d361a03052f7b` | `6c07dfb011eafeacca98adb71b8b19ba7cd06c8693bc27841a44740cf0ff1173` |
| `tests/integration/test_egress_independent.py` | `33f2f3f4249d6b4fa5b2ff442e5672766d023f49c6225e9a264948a8bd1a5c01` | `548e3dc20b3a155e1ed10426267bf76d9dc79d24a0aeab734521fa45c2345bce` |

18:50:17 +09:00에 사본32/32를 재해시했고 패키지 manifest도 여전히 지정31b20286…cbf0였다. 작성자 CI84, 작업 트리의 계약 결과 절, GS11a 사본/합성 gate는 이번 입력·실행에 포함하지 않았다.

### 9.2 ACK 위치와 원 oracle 보존

두 파일의 assertion AST multiset은 **AI136→136, egress82→82로 정확 동일**하다. 새 settle_privacy import와 세 call만 제거한 AST는 R1과 정확 일치한다. 주석 이외의 다른 조건·예외·분기·송신 oracle 변경은 없다.

| 적응 위치 | ACK 앞/뒤의 실제 관측 | 판정 |
| --- | --- | --- |
| AI `:1012` | `:1009`~1011의 옛 frozen gateway SecurityError·delivered=[]가 **대기 앞**이다. 그 뒤 실제 정책 worker ACK를 기다리고 `:1016`의 replacement grant 유지 또는 `:1032`의 stop/shutdown durable 철회를 단언한다. `:1024` 새 owner 전송, `:1027` owner 무효화 차단, `:1029` 정확 delivered=[new-plan]은 남긴다. | 즉시 plan 차단을 durable 완료 대기로 대체하지 않음. 옛 attestation의 성공/실패 늦은 결과가 proof를 복구하지 못하는 원 oracle도 보존. |
| egress bounded summary `:205` | 실제 summary 성공·segment ID·transport 연결을 먼저 확인한다. context_window 변경 및 config key 변경 뒤 ACK를 기다리고 `:206`에서 durable grant 철회를 확인한다. | 비동기 설정 철회의 실제 완료 시점을 기다리는 적응. 원 성공/범위/전송 oracle 유지. |
| egress old model/key `:230` | model 또는 key 변경 뒤 ACK를 기다리고 durable 철회→명시 재동의→옛 config/context/gateway로 실행 실패·연결0→새 계획 성공/연결1·정확 model/body/Bearer를 확인한다(`:231`~265). | 재동의가 옛 권한을 살리지 않는 관측 유지. key 분기의 기존 privacy_action(delete/save)도 완료를 기다리므로 새 settle이 native 실패를 성공으로 바꾸지 않는다. |

실제 구현은 `ui/privacy.py:305`의 동기 plan epoch 무효화와 `:312`의 worker durable revoke를 구분한다. `security/credentials.py:210`~213은 옛 plan을 정확 **PERMIT_REVOKED**로 거부하고, `ui/privacy.py:629`는 고정 gateway의 plan_check에 이를 연결한다. `tests/ui/test_secret_lifetime_ui.py:66`의 settle은 backend.idle 및 남은 view 작업을 기다린다. 이 helper의 polling 자체를 삭제/Job/native ACK의 대체 권위로 취급하지 않았다.

### 9.3 격리 정상 실행과 독립 지연 대조

실행 전 `pB-r2-plan.json`에 선정 분할·독립 기대·제외를 썼다. 정상 행은 AI **old_result 2×race 3=6**, egress bounded summary1, egress model/key2로 **정확9**다. 별도 지연 대조는 context_window/model/proof_none/proof_replacement의4개 named trace다. 이4개는 새 제품 분모가 아니라 검토 하네스이며781이나 CI84에 합산하지 않는다.

사본 cwd/rootdir/pyproject.toml/PYTHONPATH=사본 src, 고유 OS TEMP basetemp, `-p no:cacheprovider`, offscreen, `-W error::ResourceWarning`, offline 환경으로 실행했다. 실제 부모 PID25340 및 spawn 자식 PID26044의 recoryn/credentials/gateway/ledger/privacy import가 사본 src였다. 두 pytest 실행 안에서도 rootpath와 실제 product import 경로를 별도 감사했다.

- **정상9 PASS**: fail/error/skip0, JUnit2.838초, process wall3.619초. 위 세 함수의 실제9 node를 손 literal 목록과 정확 대조했다.
- **독립 지연4 PASS**: fail/error/skip0, JUnit1.067초, process wall1.735초. `pB_r2_delay.py`는 작성자 fixture/helper를 가져오지 않은 별도 PrivacyPanel/ConsentStore/CostLedger와 fake vault/transport/살아 있는 owner guard를 썼다. 실제 외부 네트워크와 vault 접근은 AssertionError로 금지했다.
- 지연은 backend.revoke_pending에 들어온 **실제 worker의 원 호출 앞**, coordinator 미보유 상태에서 Event로 멈췄다. worker thread≠GUI, 미완료/비idle, **실제 durable policy.allowed=True**를 먼저 확인했다. 이 상태에서 원 frozen gateway의 실제 request가 PERMIT_REVOKED이며 추가 transport open/write0임을 단언했다. 옛 owner는 계속 유효하므로 owner 종료나 정책 철회 완료에 기대어 차단한 결과가 아니다.
- Event를 해제해 원 revoke_pending을 실제 실행하고 worker 완료·durable allowed=False를 확인했다. 명시 current proof/재동의 뒤에도 원 gateway는 PERMIT_REVOKED·추가 open0이고, 새 gateway만 새 literal body를 전송했다. 각 trace의 최종 wire는 정확 **opens2, writes=[PB-R2-before, PB-R2-new-plan]**이다. 전후8개 관측은 `pB-r2-delay-events.json`에 남겼다.
- 독립 대조는 cloud key native worker를 별도로 지연시키지 않았다. 해당 정상 key 행의 durable 철회/재동의/정확 새 Bearer oracle은 실제 실행했으며, R1의 native 지연/정리 검토와 구분한다. AI stop/shutdown의 실제 ModelPanel 경합은 정상6행에 있고, 별도 지연에서는 이에 대응하는 proof 제거/교체 권한 경계를 검사했다.
- 초기 독립 하네스는 존재하지 않는 issue_send_permit API, EOF를 주지 않는 fake read, plan 철회에 AUTH_REQUIRED를 기대한 가정 때문에 각각 실패했다. 원 제품·배정 시험을 고치지 않고 TEMP 하네스만 바로잡았다. 원 실패 log/xml3쌍, 원 계획과 `pB-r2-plan-correction.json`을 보존했다. 최종 기대는 정확 PERMIT_REVOKED이며 포괄적 오류 허용으로 넓히지 않았다. 이 초기 실패는 제품 반례나 mutation 검출 PASS가 아니다.

정상9/지연4 모두 exact node 집합·고유 collection·각1회 call/PASS를 확인했다. 누락·초과·중복·setup/teardown 실패·skip0이다. 시험 ID/기대 code/body/금액을 제품 enum/TEMPLATES/parser에서 만들지 않았다. mutation은 실행하지 않았으며, 이 지연은 단일 결함 주입의 목표 assertion FAIL 증거와 구분한다.

### 9.4 판정·증거·미검증

**GS05-IMPL-R2 REVIEW_READY / 새 제품 OPEN0.** 지정31b20286…cbf0에 대한 두 ACK 적응의 독립 재확인이 끝나 **R1 §8.5의 제출 정합 확인1건은 이 최신 입력 범위에서 CLOSED**다. R1의 나머지 제품 검토와 기존 증거는 원 ab2c snapshot으로 남기며, 그624+10 실행을 최신32 전체의 재실행으로 소급하지 않는다.

TEMP의 `pB-r2-final-evidence.json` LF SHA256은 **`36e3cc80a8a3ac7a073dd09d877c489a5f1bca614051ba0dc9a8de68e8e301fa`**다. 기준·32해시·R1 차이·AST 보존·정확 argv·부모/spawn/pytest import·정상9/지연4 JUnit/ID 감사·전후8관측·초기 하네스 오류 파일의 해시를 담는다.

전체781/67변이·coverage/check_coverage/wheel·작성자 CI84·GS11a 합성 게이트/스케일/L30/TTL·실제 Windows Credential Manager/모델/음성/외부 서비스는 이번 재확인에서 검증하지 않았다. 최종 승인·통합·push는 X00 소관이다. 제품·배정 시험·공용 문서·Git 쓰기0이며 저장소 쓰기는 기존 리뷰 prefix를 보존한 이 끝 절뿐이다. 제출 뒤 읽기 전용으로 대기한다.

## 10. 공개 GS11a 기준 GS05 합성 검증

기준은 `494342a0a48322c09a1a4fd002ec1c3dec4cd47e`의 archive와 승인 GS05 32파일이다. 최종 합성 입력 LF SHA-256은 `871417e86f2e20d32e90d9946baac72980ecd0cdafd784a4ff919ee2ba30e857`이다. X00은 32파일과 보고·시험 증거 37파일의 해시, 실제 XML의 시험 수와 실패·오류·skip, wheel 바이트를 대조했다.

- 공유 a11y 시험은 앞서 검토한 병합본으로 원 단언 215개와 GS11 READY 준비 단언 1개가 유지됐다. L003은 양측 단언 28개와 정확 300초의 실제 타이머 대기 경로가 동일하다. L01 변이가 실제 만료 표시 단언에서 검출됐다.
- 신규 **782 PASS**, 프로세스 **40.95초**, 교차 **1,672 PASS**. 확정 부모·실제 spawn 출처와 ID 집합을 대조했다. 새 기준에서 67개 변이가 목표 단언 실패로 검출됐고 INVALID와 생존은 0이었다.
- 정확 합성 전체 **30,131 PASS**, 실패·오류·skip 0. 정적 검사와 coverage 7묶음 및 오프라인 wheel을 통과했다. Wheel SHA-256은 `d8390fb42c5163e833224a1591b26978c4429ab22b917582a2ed817640f85e65`다.
- 이 결과는 로컬 합성 검증이다. 선행 GS11a의 원격 core 3.13에서 G12 출판 시험 91건이 실패해 공개를 보류한다. 회복 단위의 정확 공개 기준에서 새로 검증한다. Python 3.11, 실제 Windows Credential Manager·실장치·서비스는 이번 합성 실행의 범위 밖이다.

## 11. 복구 공개 d127019 기준 최종 인수

§10의 공개 보류 원인은 d127019의 복구와 [CI45845073225](https://github.com/gangdonggilstudy/Recoryn/actions/runs/45845073225) core3.11·core3.13·optional-runtime 실제 success로 해소됐다. GS05는 그 공개 archive에 실효32(LF871417e8…)만 적용해 다시 검사했다. 전체435입력 LF는 `ea63f57655cbd0b0233611319436bb1af27793fd665c909854ca54238f3a72c3`다. 이전30131 성공을 새 기준으로 옮기지 않았다.

- 동일 입력에서 **30145 PASS·실패/오류/skip0**, 전체 수집/XML 각1회를 X00이 읽어 대조했다. 신규782는 준비 포함40.986823초/60초, 교차1672·AUTH14·publication386·G15전체102와 기존 성능/capture7이 통과했다. 전체 process2286.523983초다.
- GS05 정상63 뒤 단일67개, 복구 정상14 뒤 단일10개, L01 정상 뒤 timer 시작 제거가 각각 지정 call assertion에서 실패했다. 변이 INVALID/생존0과 최초 시험전 로그 소유권 하네스 INVALID1을 분리해 보존했다. 기존67 목표와 assertion 위치를 대조했다.
- Ruff·format·mypy·coverage7·offline wheel이 통과했다. Combined coverage92.7015%와 별개로 전체 line94.10%/branch88.48%, security97.35%/92.75%, storage95.20%/90.16%를 확인했다. wheel `b3d48773c151579746e97632be577e327e507b786d52a4231f6b343bee8e3d9c`의 package Python86개와 제품 bytes가 검사 사본과 같았다.
- a11y 병합본11f16d0c는 원215단언+READY1을 보존한다. 작성자 완료 뒤 X00이 기존 공유50942234를 hash로 확인하고 이 검사한 병합본만 동기화했다. L003의 worker ACK·실제 timer/event·300초·1초 poll과28단언은 그대로다. 다른 worker/계획의 변경은 통합 후보에 포함하지 않는다.

작성자 report LF `8f7d5909c12dde001e2f5ffc5cf2e5f5a3aeba50d4b9eff942692b091662411f`, evidence LF `58b618af360d3c95faf70b77169fcaf63f7e4c96f1d79151499a73a01465519e`는 `build/gs05-d127-preview/`에 있다. X00의 별도 읽기 인수는 `build/gs05-d127-integration/final-acceptance.json`이다. 검사 후 제품·시험 코드를 수정하지 않았다.

pB의 추가 d127 독립 검토는 report LF `a60d09ec863ec92b564eef10d3255b689aa19fca1ace6af6a8ed42120c7e341a`, evidence LF `94e0e228855dd4607ec596b1730112dae1d296fd018c5b69f259613b4c847a5e`, 제품 OPEN0이다. 독립 구성435파일이 검사 입력과 같고 선택30/API3 PASS·원자입장 및 ticket 두 부정대조의 목표 FAIL/INVALID0을 확인했다. AUTH13/14의 입장전 call0과 입장후 실패의 합법적인 선행 작업을 구분했으며 source/native/reader ACK와 기본 API를 직접 관측했다. 기존 R1/R2의 깊은 비밀수명 검토와 이 추가 교차 실행을 구분하고, 전체30145를 pB 실행으로 세지 않는다.

로컬 제품 판정은 **VERIFIED·OPEN0**이다. 정확34파일 후보와 최신 문서의 독립 대조 및 실제 tree/부모/ref·commit 전체 메시지/trailer0·정상 push가 남아 있다. GS05 통합판 원격 CI·Python3.11 로컬·실 vault/장치/서비스·유료 호출·전원 장애·완전한 메모리 소거를 완료로 표시하지 않는다. 다음 G09 공개도 GS05 실제 공개와 그 원격 CI 성공 뒤다.
