# GS05-C3: 요청 직전 비밀 읽기 수명 계약 개정

상태: **CONTRACT_REVISION_READY / 독립 재확인·X00 구현 승인 전**. 작성 w5:pA Codex, 2026-11-26. GS05R-01~04와 X00 D01~D08을 반영한 정적 개정이며 제품·시험·Git 쓰기와 시험 실행은 없다. C1의 620 합계는 산술 오류였고 실제 기본 분모는 **520**이다. C2 보강199를 별도로 제안해 총 **719행/15가족**, mutation61, 향후20파일 범위를 아래 고정한다. D01은 X00 최신 결정 B이며 native read 밖 잠금·단회 ticket·반환 뒤 폐기와 송신 재검사를 명시한다. 전부 계획/NOT_RUN이고 독립 재확인 전 구현 착수 승인이 아니다.

## 1. 고정 기준, 현재 사실과 기존 단언

### 1.1 기준과 입력의 구분

- 시작/분석 기준: `main`, HEAD `b77cc102a9db818a8c1d1a2840933ffa28e1b14c`. 시작 `git status --short`는 수정 18파일·미추적 19파일, 합계 37파일이고 staged 표시는 없었다. 기존 GS04a 11파일·GS11a 및 추가 시험 적응·G09/G10/G14 계약·X00 문서가 섞여 있었다. 본 문서는 이 변경을 기준 제품으로 채택하지 않는다. Git의 사용자 ignore 읽기 권한 경고는 관측했으나 제품 실패로 계산하지 않는다.
- 아래 **제품·기존 시험·기존 설계 근거는 모두 위 commit의 `git show <commit>:<path>` 출력**에 줄 번호를 붙여 읽었다. 작업 트리의 제품/시험 파일을 읽어 기준을 보충하지 않았다. 이전 G01 리뷰의 옛 줄 번호 대신 이번 기준의 실제 줄 번호를 기록한다.
- 현재 작업 트리에서 읽은 계획/승인 근거: `docs/implementation/s3-bundle-plan.md`의 P05·공유 파일 표, `docs/testing/gs04-provider-facts-cases.md:62,64,68,76,252,271`, `docs/reviews/gs04-provider-facts-review.md`의 최종 판정, `docs/collaboration/assignments.md`의 H02/H03·GS04/GS11 및 GS05-C1 행, `docs/collaboration/orchestrator-handoff-h02.md:43,48`. 이들은 계획/승인 또는 미통합 결과다. GS04-R1 수락/OPEN 0을 제품 commit/push·GS04b 완료로 간주하지 않는다.
- 첫 계획 입력 읽기에서 기록한 **원본 바이트 SHA256**: s3-bundle-plan `028490188016735a12c253c4f56c454348772cb540b4830f153673cfa4f8239f`; gs04 계약 `f7cb09fddbb716eca79a4f7a435a3607ebdc04830bc17a4e2fca406c3335f634`; gs04 독립 리뷰 `b18eb3673da39d8e79679a70b3bdd5de690bc573593ecaa2285ccab869942154`; assignments `ba3afdfa350640573166e6e55f731222f966ab9ef64abaa1e5e83f454c3cd708`; H02 `76a0e5e8102fbc6992c8ab1b7d710ab70f766f7a7679f730eb04881b3c8f3a6b`. 배정표는 X00이 병행 갱신할 수 있어 후속 읽기까지 같은 hash라고 주장하지 않는다. 이 값은 LF 정규화 hash와 다르다.

주요 기준 제품의 Git blob ID도 고정한다. blob ID는 파일 SHA256 또는 실행 증거가 아니다.

| 기준 경로 | Git blob ID |
| --- | --- |
| src/recoryn/ui/privacy.py | `38a3c0fd5d1680b3b8a1350b70241cf027f0365d` |
| src/recoryn/ui/ai_bridge.py | `eb509355b67c44ad50dc5d4301873375f777166e` |
| src/recoryn/providers/contracts.py | `f4bbaff26c3137ddeab231b75577e2a8e9ccd71e` |
| src/recoryn/providers/_common.py | `7097271a2015c1a9554d090b82645aa377b29dbc` |
| src/recoryn/security/gateway.py | `7c3c270da180e1c47193aa2b0999580954c6e8a7` |
| src/recoryn/security/vault.py | `1f16bc1fe01c949ef4d536d7003d5fac5c2ab08a` |
| src/recoryn/security/transport.py | `8e537cbd4fb96f9d661f55c3269f75389ca049b1` |
| src/recoryn/security/_secrets.py | `2e38c8c6c0f2241b47ca6052ab0689c4e3585ecb` |

### 1.2 설계와 구현의 차이

| 구분 | 기준 근거(path:line) | 읽어서 확인한 사실 / 본 계약 요구 |
| --- | --- | --- |
| 정본 | docs/architecture-v1.md:215,217,225,227,235 | 정확 endpoint/기능/데이터/범위, 전송 직전 재검사, 비용 fail closed, credential reference와 요청 직전 최소 읽기. 저장된 키 자체가 송신 권한은 아님 |
| 정본 | docs/implementation/product-contracts.md:142,146,148,150 | guard의 open/각 write/응답 승인, consent→ledger→owner 순서, UNKNOWN 노출 보존, 비밀 없는 진단을 유지 |
| 원 gap | docs/reviews/g01-gap-ai-security-ui-review.md:75 | 실행 문맥 생성 시 읽기와 header 장기 보관을 PARTIAL/S3로 판정. 이번 분석에서 무동의 송신이나 새 S0/S1을 재현한 것은 아님 |
| GUI snapshot | src/recoryn/ui/privacy.py:65,74,571,595,619,630,636,676 | frozen PrivacyExecution/_Snapshot, bindings·cap/limit 확인 뒤 vault.get과 provider별 header 생성. cost quote/reserve는 이후 callback(:644). 현재 독립 api_key DTO field가 아니라 실제 키 snapshot은 header 값 |
| 장기 보관 | src/recoryn/providers/contracts.py:152,159,166,171; src/recoryn/providers/_common.py:159,241,245 | context는 header를 repr에서 숨기지만 MappingProxyType에 복사·보관. Run도 context를 보관하고 매 HTTP 요청에서 combined 복사. repr 비표시는 DTO에서 비밀을 제거한 것과 다름 |
| GUI/worker | src/recoryn/ui/ai_bridge.py:728,772,811,875,900,935,957,976 | GUI에서 prepare_execution 호출 뒤 worker로 진행. context factory가 headers=context.headers를 복사하므로 native vault 읽기를 worker로 옮겨야 함 |
| 송신 권한 | src/recoryn/security/consent.py:80,97,403,428,748,789 | binding에 execution/grant epoch, permit에 session generation/body digest/reservation/기한. 재동의가 옛 binding을 되살리지 않음. 독립 credential epoch는 현재 없음 |
| gateway | src/recoryn/security/gateway.py:174,216,230,248,252,265,275,295,318 | body/header 검사→permit→ledger→coordinator 안 재검사→open, 각 write·최종 응답도 검사. cancel/deadline은 :184의 remaining, UNKNOWN은 첫 write 직전(:339) |
| header 경계 | src/recoryn/security/transport.py:25,56,69,78,85,100 | open은 DNS/connect/TLS와 header 로컬 복사. 첫 write의 endheaders에서 HTTP header handoff. 두 관측점을 구분. close는 현재 _headers를 명시 clear하지 않음 |
| 저장/삭제 | src/recoryn/ui/privacy.py:926,996,1001,1034 | save/delete는 endpoint 동의를 먼저 revoke한 뒤 vault.set/delete, 그 뒤 _changed. native 호출은 동기. 저장 성공 시 입력란 clear, 실패를 완료로 표시하지 않음 |
| vault 한계 | src/recoryn/security/vault.py:68,79,82,99,108,116,131,146 | lazy backend·평문 fallback 없음. native write buffer memset·CredFree가 있지만 get은 bytes→str 반환. 강제 중단이나 Python str 전체 복사본 zeroization 보장 아님 |
| 별도 메모리 보관 | src/recoryn/security/vault.py:124,139; src/recoryn/security/_secrets.py:8,11,17 | set/get이 실제 비밀을 process-local hints의 최대256개 deque에 등록. header 수명 축소 뒤에도 이 참조가 남으므로 프로세스 메모리에서 비밀이 사라졌다고 선언 불가 |

### 1.3 읽어서 확인한 기존 시험과 없는 단언

아래는 **시험 코드 존재/단언 내용 확인**이며 새 실행 결과가 아니다. 해당 node를 그대로 재사용할지, fixture 적응할지는 구현 배정 때 독립 검토한다.

원 gap의 분류는 S3지만 인증/동의 경계의 변경 위험은 별도다. 잘못된 구현의 무동의 송신·비밀 출력은 S0, 옛 키/계획의 잘못된 승인·핵심 요청 차단은 S1 후보로 검토한다. 이것은 현재 제품에서 새 S0/S1이 재현됐다는 판정이 아니다. 독립 보안 관점과 QA/상태·순서 관점의 검토를 요구한다.

| 기존 node / 기준 줄 | 이미 있는 단언 | 이번에 보강할 차이 |
| --- | --- | --- |
| tests/ui/test_privacy_ui.py::test_constructor_default_denial_no_vault_read_and_summary_off (:98) | 생성 시 reads=0, 기본 거부·요약 off | 실행 준비·큐 대기·다중 요청 동안의 무비밀 context까지 확인하지 않음 |
| 같은 파일::test_credentials_are_endpoint_bound_fail_closed_and_never_in_config_key (:180) | endpoint 별 키, config_key 불변, 저장 실패 안전 코드; :196은 문맥 생성에서 AUTH_REQUIRED 기대 | AUTH_REQUIRED를 요청 직전 gate로 옮기면 :196의 단계 기대가 바뀜. 실제 실패를 실행했다고 쓰지 않으며 X00 사전 승인 대상 |
| 같은 파일::test_worker_reservation_factory_uses_frozen_gui_values (:212), ::test_execution_settings_change_key_and_revoke_old_plan (:274) | worker 비용 callback의 고정 값·옛 binding 차단 | callback/DTO가 비밀을 잡지 않는지, vault read보다 비용 거부가 앞서는지 확인 필요 |
| 같은 파일::test_zero_cloud_cap_is_blocked_and_ollama_requires_attestation (:262) | cap=0 때 reads=0 | 복수 원인·직접 gateway·queue 뒤 재검사 분모를 대체하지 않음 |
| tests/unit/test_providers.py::test_frozen_values_and_secret_context_repr (:203) | raw auth header context의 repr 비노출·mapping 불변 | 현재 :204는 실제 header 보관을 허용한다. 제안은 비인증 header 불변과 ref/resolver repr 비노출로 분리해야 함 |
| tests/unit/test_security.py::test_vault_fake_roundtrip_and_safe_failure_has_no_plaintext_fallback (:324), ::test_invalid_vault_read_values_never_escape_or_persist (:852), ::test_native_invalid_blob_frees_native_result (:860) | fake roundtrip, 안전 오류·평문 파일 없음, 잘못된 bytes 거부, fake CredFree 1회 | 요청 gate/키 epoch/GUI thread/종료 후 참조 제거는 별도 |
| tests/integration/test_egress_independent.py::test_new_grant_cannot_revive_old_model_or_key_context (:208) | 옛 계획 dispatch 0, 새 계획은 새 키 사용 | read 횟수·read 위치·credential epoch 독립 결속은 없음. 옛 계획 거부 assertion은 유지 |
| 같은 파일::test_ui_budget_and_headers_are_immutable_but_revocation_blocks_worker (:260) | :267,277에서 context.headers가 **실제 옛 키**라고 직접 기대 | 단순 fixture 변화가 아닌 계약 기대 변경이다. 새 기대는 context 비밀0·준비 read0·old ref 불변·철회 뒤 dispatch0. 승인 없이 고치지 않음 |
| 같은 파일::test_committed_revocation_before_first_write_sends_no_body (:341), ::test_write_before_revocation_cannot_send_next_chunk_after_commit (:403) | 첫/후속 write 양 순서, 닫힘·UNKNOWN 비용 보존 | vault read 전/중/후 및 transport header 복사본 정리 관측 추가 |
| 같은 파일::test_dispatch_guard_faults_preserve_exact_handoff_and_cost (:792) | open/첫·둘째 write/결과의 enter·exit 장애별 literal delivered·known·비용 | 새 resolver 장애도 같은 분류를 보존해야 하며 guard 호출 개수 기반 oracle로 바꾸지 않음 |
| tests/integration/test_gateway.py::test_deadline_and_cancel_preserve_unsent_or_unknown_cost (:506), ::test_budget_and_header_failures_never_open_transport (:563) | handoff 전/후 cancel·timeout, reservation 상태, bad header/예산에서 opens0 | 비용·동의 거부 시 **vault read도 0**인지 추가 |
| tests/contract/test_provider_contracts.py::test_session_bound_real_gateway_blocks_without_consent_then_uses_fake_transport (:200); tests/integration/test_provider_security_independent.py::test_failed_handoff_preserves_unknown_and_only_safe_error (:185) | provider→실제 gateway+fake transport의 거부·UNKNOWN·안전 오류 | 기존 raw auth fixture를 새 production 인증 경계와 구별해 이행해야 함 |


C2 입력: C1 LF `5b2918a9a34346a63780267b1b36a0cbb73ecae484da4b6254467e3de5b4b341`, 독립 GS05-R1 LF `82bd3b22bb3862b669b7175c73e1e7d649ae6f381373c5645af1fc1d8aa209b0`, `build/orchestrator-tools/gs05-c2-decisions.md`의 D01~D08, 배정표 H03 GS05-C2. 이 개정은 C1의 결정/분모/오류/변이/primary 미확정 내용을 대체한다. 결정 파일 최신 LF SHA256는 `f83667d23f16afe7c2ecb8871c0dc989e2641ecc9a27401d9d2bd915a7050348`이다. `B:`는 위 기준 commit의 `src/recoryn/` 아래 경로를 줄여 쓴 표기다. 위 §1의 시작 snapshot은 C1 관측 이력이며 C2 시작 HEAD는 같은 b77cc10, dirty는 수정18·미추적23·staged/unmerged 표시0이었다.

C3 입력/범위: 동결 C2 LF `f3125dd7eda83a19abdbd566dcdfd1706383451e9594ff2210ad2a0d2bb763b8`와 GS05-R2 리뷰 LF `b1b1dc26897c796677a889cd2c632d46daba5b80a108a18676f56b487681a34f`의 §6.5 GS05R-05만 반영한다. 두 입력 hash를 실제 읽기와 대조했다. C3 시작 cwd는 `D:/project/Recoryn`, 실제 HEAD는 X00 공개 뒤 `b30b3a7b7223fa20ca19ae17fe1975aa80e598f2`, dirty 수정15·미추적14·staged/unmerged 표시0이다. 제품/기존 시험 분석 기준은 계속 b77cc10이며 새 HEAD·GS11a dirty를 합치지 않는다. 아래 C2 당시의 GS04a 미통합 관측은 제출 이력이고 최신 CI 완료를 이 문서에서 조회/확인하지 않았다. 이번 쓰기는 이 문서 하나, T00 한 bounded trace와 기존 C2-M11의 의미 구체화뿐이며 **719행/15가족·61변이·20파일·primary 323/200/72/124를 유지**한다. GS05R-01~04는 R2의 계약 정적 재확인 CLOSED 보고이고 GS05R-05는 독립 재확인 대기다. 제품·시험·Git 쓰기와 시험 실행은0이다.

## 2. C2 결정과 독립 발견 대응

| 결정/발견 | 개정 수락 조건 | 상태 |
| --- | --- | --- |
| D01 / A→B | 단회 ticket의 짧은 검증·발급/사용과 native read를 분리한다. native read는 consent/ledger/credential/owner/root/Job 잠금 밖이다. 이미 발급된 ticket의 물리 진입 경쟁을 명시하고 철회·삭제·녹음 제어가 native 반환을 기다리지 않게 한다 | X00의 갱신 결정 반영. 실제 안전성 NOT_RUN |
| D02 | Event.set 취소 의도와 gate 관측을 분리. read 중 취소는 native 완료 ACK가 아니다. 반환값·후속 O/H/B/F를 차단하고 이미 전달된 노출은 유지 | 계약 반영 |
| D03 | 비밀 없는 ref/resolver·요청별 늦은 읽기·raw auth context 거부. gateway가 permit/권한/비용/대상/epoch를 직접 재검사 | 정확 공개 API는 후속 승인 |
| D04 | 기존 AUTH 실패 시점·실키 header 보관·raw auth context 허용의 세 부류만 새 계약에 맞게 제안. 설정 불변·원본·거부·UNKNOWN·CAS는 보존 | 실제 시험 수정 미승인 |
| D05 | 기존 최대256개 redaction hints는 유지. 요청 DTO/앱 소유 header 수명만 개선. OS/HTTP/Python 전체 zeroization 보장 없음 | 잔여 위험 수용 범위 반영 |
| D06 | 접수 성공 때 입력란 clear. 접수 거부와 native/후속 read 실패를 구분. epoch 무효화·endpoint 철회가 native set/delete보다 먼저이며 native 변경 동안 공용 잠금을 보유하지 않음 | S16/T 행과 소유 조건에 명시 |
| D07 / GS05R-01 | 기본 합계 620→520 정정. 사라진100행은 실제 정의가 없었던 산술 오류이며 제외/축소/새 PASS가 아님 | 아래 기본520+보강199=719, 별도 ID |
| GS05R-02 / D08 | gateway→Run→provider→Job의 미송신 AUTH 의미·정확 code를 닫는다. 기존 jobs/failures.py를 확대하지 않음 | P45/Q20 및 C2-M02~04 |
| GS05R-03 | 첫 write 반환 뒤 B2/응답을 멈춘 중간 시점에서 lease/header0. 종료까지 cleanup을 미루는 단일 변이로 검출 | L10 및 C2-M01 |
| GS05R-04 | 모든 보안 action/implicit query를 worker로 이행. native 지연과 별도 coordinator 지연을 각각 시험 | V88 및 C2-M05~07 |

위 표는 작성자의 수정 대응이다. GS05R-01~04의 RECHECKED/CLOSED 판정은 독립 검토자와 X00가 한다. 새 제품/시험 실행 결과나 단독 승인으로 쓰지 않는다.

### 2.1 A를 폐기한 실제 정적 근거

B:ui/ai_bridge.py:1240~1249의 before_delete는 consent.revoke_session(:1242)을 먼저 호출한다. B:security/consent.py:715~722는 coordinator.hold를 사용한다. B:ui/main.py:941→945→947과 :1183→1185→1187은 그 반환 뒤 recorder.close와 삭제/재시도로 진행한다. A가 native read 동안 같은 coordinator를 잡으면 이 순서가 지연될 수 있다. X00가 이 근거를 직접 확인하고 B를 지시했다. 정적 경로 확인이지 실행 교착/새 제품 S0·S1 재현이 아니다.

이하에서는 **A의 Q commit 대기·Q 뒤 physical read0 요구를 사용하지 않는다.** B의 ticket/반환 후 재검사와 control 진행을 새 oracle로 정의한다. B에서도 기존 O/H/B의 짧은 handoff 직렬화는 유지하며, 이미 허용된 네트워크 handoff가 지연되는 기존 위험과 native vault 지연을 구분한다.

## 3. B의 수명·소유권·worker 경계

### 3.1 비밀 없는 carrier와 단회 ticket

권고 carrier는 **계획에 고정된 Gateway의 auth binding**이다. CredentialRef는 provider, 정규화 exact endpoint, 앱 execution ID, 값과 무관한 credential epoch를 포함한다. resolver/service capability와 ref는 repr/일반 serializer에서 제외하고 실제 비밀·비밀 hash·header를 담지 않는다. ExecutionContext는 cancel/progress/reservation_factory와 비인증 protocol header만 갖는다. raw auth context 생성은 INPUT_INVALID로 거부한다.

이 배치는 C1의 새 ExecutionContext 필드 전달안을 구체화·변경한다. B:app/ai.py:305~325의 _execution_context는 기존 필드만 복사하므로, 새 ref 필드를 context에만 넣으면 사라질 수 있다. auth binding을 session/실행에 고정한 Gateway에 두고 Gateway.for_session이 동일 binding을 보존하게 하여 app/ai.py 수정 없이20파일 안에서 이행하는 안을 권고한다. ui/ai_bridge.py:728의 factory도 secret-free context만 복사한다. app/ai.py·Job runner를 고치거나 body/config_key에 ref를 숨기는 것은 현재 범위 밖이다.

Run.request는 현재 요청의 CostRequest/예약을 먼저 만들고, 기존 Gateway.request에 body·비인증 headers·reservation·cancel을 넘긴다. GatewayLike를 구현한 기존 fake에 auth 인자를 몰래 강제하지 않는다. gateway의 auth binding은 현재 permit과 별도로 검사하며 binding/resolver의 존재 자체가 송신 허가가 아니다.

read ticket은 메모리 전용 불투명 nonce와 ref, request/attempt 식별, exact 목적지·capability/data/session/generation, body digest·reservation ID, 단조 기한을 고정한다. 비밀 값/hash는 없다. 발급 목록과 상태는 요청 소유 서비스에만 존재하며 DB/로그/backup/관측 cache로 직렬화하지 않는다. ticket은 ISSUED→CONSUMED→READING→RETURNED/DISCARDED의 한 번 흐름이며 terminal은 다시 ISSUED가 되지 않는다. 미사용 ticket은 취소/만료로 폐기한다. 실행 중 native call은 metadata 만료로 종료했다고 표시하지 않는다.

| 사건 | 동작과 잠금/검증 | 보장 |
| --- | --- | --- |
| P 준비 | GUI는 값/대상/선택 세대/nonce 캡처만. worker가 auth binding·현재 권한/비용 준비 | vault/DNS/open/header/body0, context/큐/Job에 비밀0 |
| I 발급 | 짧은 consent→ledger→credential→선택 owner 순서에서 cancel/deadline, exact binding/permit, 비용, ref/epoch 재검사. ticket 기한은 요청/permit 기한의 최솟값 | Q commit 뒤 새 I0. 실패 시 native read0 |
| U 사용 승인 | 같은 scope/현재 상태를 다시 확인하고 짧은 서비스 원자 상태 전이로 단회 CONSUMED. 동시에 두 소비자가 이길 수 없음 | replay/다른 요청·대상·body/예약 ticket은 거부. 사용 후 재발급·자동 retry 없음 |
| R 실제 native read | U의 마지막 검사와 공용 잠금 해제 뒤 호출. consent/ledger/credential/owner/root/Job 잠금을 하나도 잡지 않음 | U와 실제 R 사이 Q가 commit할 수 있어 물리 R1 가능. Q 뒤 물리 read0 보장은 없음 |
| r 반환/폐기 | 현재 권한·기한·키 epoch·session 삭제·취소를 다시 검사. 무효면 값을 즉시 폐기·lease 해제 | ticket만 믿고 O/H/B/F로 진행0. 늦은 반환을 GUI/Job/다른 요청에 캐시하지 않음 |
| O open | 현재 permit/비용/ref/epoch/owner/cancel을 재검사한 짧은 기존 handoff 직렬화 | DNS/connect/TLS, 신뢰 transport의 앱 header 복사. 아직 wire header 송신과 다름 |
| H/B | 첫 write 직전과 각 body마다 같은 검증. 첫 write 직전 ledger UNKNOWN 처리. H는 HTTP header handoff 시작 | Q 뒤 새 handoff0. 이전 OS/TLS 전달·부분 write는 회수하지 못함 |
| F 채택 | 최종 현재 permit/기한/ref/epoch/owner/cancel 확인 | 늦은 응답은 성공/게시/관측으로 승격0 |

U는 **마지막 pre-read gate**다. 시험의 U→R cut은 마지막 검사 후 잠금이 풀린 지점에 barrier를 둔다. 이후 Q가 commit하고 허용된 단회 call이 R에 늦게 진입하는 bound를 R1로 관측한다. best-effort 검사를 추가한다면 그 마지막 검사를 U로 정의하고 같은 경쟁을 다시 시험한다. 이를 R0으로만 허용해 B를 A처럼 표현하지 않는다.

Q는 실제 정책/epoch 무효화 commit, C0는 Event.set, C는 gate의 취소 관측이다. Q 성공은 read 종료 ACK가 아니다. native R이 아직 진행 중이어도 Q commit·소유한 capture 종료 ACK·삭제 intent/fence 등록은 진행해야 한다. 실제 Job reader가 남으면 물리 삭제는 DELETE_PENDING일 수 있으며 이를 강제 해제/DELETED_LOCAL로 만들지 않는다. 별도 native 완료 ACK는 r/실제 task 종료 뒤에만 표시한다.

### 3.2 key save/delete의 실제 소유 조건

같은 provider+endpoint의 변경 명령은 **하나의 FIFO 실행자**가 소유한다. 접수 순번/command nonce·pending 집합·최신 epoch를 짧은 메모리 상태 전이로 기록한다. worker는 epoch 증가와 endpoint revoke를 native set/delete보다 먼저 확정하고 잠금을 모두 놓는다. native set/delete 동안 consent/ledger/owner/root/Job/credential mutex를 보유하지 않는다. FIFO 소유는 지속한 공용 mutex가 아니라 command 상태/단일 실행자다. 다른 endpoint와 원본 제어를 전역 native 대기에 묶지 않는다.

같은 대상의 다음 native 변경은 앞 변경의 실제 반환/정리 뒤 시작한다. pending 변경이 하나라도 남거나 앞선 nonce 결과가 최신이 아니면 새 동의 발급/새 ticket을 허용하지 않는다. 직접 grant가 생겼더라도 gateway I/U는 pending target을 AUTH_REQUIRED로 거부한다. 앱 grant 명령의 pending 거부 code도 AUTH_REQUIRED로 고정한다. 실패도 epoch/철회를 rollback하지 않으며 옛 ref/기존 grant를 복원하지 않는다. 변경 실패는 OS 키 값이 바뀌었거나 삭제됐다는 보장이 아니다. 다음 실행은 새 명시 동의와 현재 epoch를 요구한다.

이미 CONSUMED인 read와 native 키 변경은 겹칠 수 있다. read가 새 키/옛 키 어느 값을 받든 r/O의 현재 epoch/권한이 맞지 않으면 폐기한다. 서비스는 read를 끝내려고 writer 명령이나 Q를 공용 잠금 아래 기다리지 않는다. 앱 밖 무통지 key 변경을 epoch만으로 인증했다는 보장도 없다.

저장 접수는 bounded queue의 수락이 선형화 지점이다. 수락 때 GUI 입력란을 clear하고 비밀을 worker payload에만 둔다. 이는 실행 준비 P의 secret-free 큐와 다른 전용 key 명령 payload이며 repr/로그/일반 serializer/callback에는 값을 노출하지 않고 실제 native 완료/실패 정리 때 앱 소유 payload 참조를 해제한다. queue 거부는 RESOURCE_EXHAUSTED, native 호출0·입력 보존·pending0이다. 수락 뒤 native 실패는 clear를 취소하거나 callback으로 키를 복원하지 않고 safe code/재입력 안내를 보인다. 선택 세대·command nonce·닫힌 widget 검증을 통과한 callback만 화면에 적용한다. native read/write가 아직 진행 중이면 '완료' ACK를 표시하지 않는다.

### 3.3 첫 write 반환 직후의 앱 소유 참조

한 HTTP 요청의 resolver lease는 actual secret과 auth header를 소유하는 유일한 앱 소유 객체다. gateway는 lease 밖 장기 local/closure에 비밀 str을 복사하지 않고, transport 사본도 추적한다. OpenAI=authorization/Bearer, Anthropic=x-api-key, Gemini=x-goog-api-key의 손 표를 사용한다. provider protocol header의 덮어쓰기/대소문자 중복은 송신 전 거부한다.

첫 write가 성공/부분 실패로 **반환한 직후**, B2 또는 응답 read에 들어가기 전에 lease의 secret slot=None, 민감 header dict={}, gateway의 민감 dict={}, transport._headers의 인증 항목0을 만족해야 한다. 첫 write 전 open 실패/철회·취소도 즉시 abort cleanup한다. close 실패나 request finally는 보조 cleanup이며 위 정리를 요청 끝까지 미룰 수 없다. 그 뒤 ledger에는 비용 검증용 비인증 cost_headers만 전달한다.

검사 면은 요청 소유 lease의 민감 slots·dict와 gateway/transport의 선언된 사본/closure다. 미래 구현에서 이름을 고정해 해당 owner를 보유한 관측 fixture로 검사하되 새 공개 secret getter를 만들지 않는다. fake vault 저장소·시험의 K_A 원본/허용된 wire 관측·기존 redaction hints·HTTP/OS 내부 복사본은 별도로 분류한다. 이 제외를 request context/closure/DB/로그 보관의 허가로 쓰지 않는다. hints의 최대256 str 보관은 잔여 위험으로 유지한다.

### 3.4 모든 UI 보안 경로의 worker 소유

B:ui/privacy.py:262~325의 grant/revoke/save/delete/budget/reset_clock/refresh/settle/adopt 및 설정·선택 signal을 빠짐없이 포함한다. _snapshot/_cost_policy(:749)/_changed, _show_scope(:388)/select_session(:349)/retry timer, _cost_unavailable(:840)/_refresh(:857)의 모든 조회와 후속 success/failure refresh도 worker read model로 옮긴다. scope_view가 현재 nonblocking try-lock이어도 GUI의 DB/coordinator 진입 예외로 남기지 않는다.

GUI는 local validation·cached 비민감 view 렌더·확인 dialog·bounded enqueue·pending 표시만 한다. 모달 문구는 미리 고정한 안전한 proposal/read model을 사용하고 worker가 commit 직전에 다시 검사한다. 아직 읽기 자료가 없으면 worker 준비를 기다리는 pending UI를 표시하며 GUI에서 ledger/account/정책을 직접 읽지 않는다. callback 안의 재조회, 생성자 최초 refresh, _request_currency의 signal 연쇄도 같은 규칙이다. GUI에서 actual credential/network/coordinator 획득0이다.

worker 명령은 고정 대상/기능/범위/세대/nonce로 실행한다. 선택이 바뀌어도 옛 결과가 현재 화면·새 명령을 덮지 않는다. 별도 coordinator 지연에서는 pending이 유지되지만 GUI heartbeat·capture control은 진행해야 한다. B의 native 지연에서는 coordinator가 자유로워 실제 grant/budget/refresh/시계/정산 worker가 진행할 수 있어야 한다. 모든 것을 disable하여 시험 경로 자체를 실행하지 않는 것은 수락하지 않는다.

## 4. 오류 literal과 계층별 의미

### 4.1 AUTH의 공개 경계(D08)

| read 전/중 원인 | gateway 공개 code | Run/provider 공개 code | 공통 속성 / 유효 session의 Job·Attempt |
| --- | --- | --- | --- |
| ref/키 없음, stale ref/epoch, pending credential target | AUTH_REQUIRED | AUTH_REQUIRED | retryable=false, known=true, BLOCKED/AUTH·FAILED |
| backend VAULT_UNAVAILABLE | VAULT_UNAVAILABLE | VAULT_UNAVAILABLE | 위와 같음 |
| 빈/NUL/초과 bytes·invalid UTF-8·내부 VAULT_INVALID_VALUE·read backend 예외 | VAULT_READ_FAILED | VAULT_READ_FAILED | 위와 같음. 내부 invalid code/text를 공개하지 않음 |
| read가 deadline 뒤 반환 | TIMEOUT | TIMEOUT | retryable=false, known=true. AUTH로 분류하지 않음 |
| H 진입/부분 body 뒤 AUTH처럼 보이는 예외 | REMOTE_OUTCOME_UNKNOWN | REMOTE_OUTCOME_UNKNOWN | retryable=false, known=false, BLOCKED/REMOTE_UNKNOWN·UNKNOWN |

known AUTH 실패의 DNS/O/T/H/B/F는0이고 미리 예약된 현재 행은 RESERVED80·unknown_exposure0이다. 기존 다른 요청의 UNKNOWN은 그대로다. 자동 retry/refund0, canary/비밀 hash/예외 원문 출력0. native read 횟수는 missing-key1/stale-ref0처럼 실제 단계와 분리한다. 요청 전에 거부되면 claim하지 않은 Job에 새 Attempt를 발명하지 않으며, P의 Job oracle는 실제 claim된 유효 session을 전제로 한다.

gateway는 기존 vault.get의 raw error를 R 경계에서 위 세 AUTH code로 좁게 변환하고 안전 속성을 고정한다. _common.Run은 normalize_failure 후 **이 닫힌 세 code와 known을 함께** 검사해 provider로 보존한다. known=false가 먼저면 AUTH로 낮추지 않는다. B:jobs/failures.py:14,90~120의 기존 AUTH/UNKNOWN 분류를 그대로 사용하고 CODE_GROUPS/BOUNDARY_CODES를 확대하지 않는다. raw VAULT_INVALID_VALUE가 normalize_failure로 먼저 들어가 TASK_FAILED가 되는 경로와 known AUTH가 Run fallback에서 UNKNOWN이 되는 경로를 모두 차단한다.

실제 adapter 결과의 error_code/outcome_known, runner/JobStore.fail의 state/attempt/blocked_reason까지 P에서 관측한다. app/ai.py의 _OutcomeGuard와 result.error_code 전파·remote_intent/reader ACK도 읽기 근거로 유지하며, known-unsent를 단지 remote intent 행이 존재한다는 이유로 미송신 UNKNOWN으로 바꾸지 않는다. 반대로 이미 H를 넘긴 노출은 인증 실패로 해제하지 않는다.

### 4.2 동의·permit·우선순위 literal

B:consent.py:438~465의 _grant는 없음/allowed=0/다른 scope/만료를 CONSENT_REQUIRED로 거부한다. 새 CONSENT_REVOKED 값을 가정하지 않는다. 현재 row는 유효하지만 옛 captured binding/grant epoch인 경우 :682~695와 :765~771에서 PERMIT_REVOKED다. session generation/삭제는 :724~745의 SESSION_REVOKED, 앱 execution store 자체가 바뀐 경우 _active의 EXECUTION_CHANGED를 보존한다.

A의 순서는 구조 유효 입력→현재 cancel/deadline→동의/정확 binding→비용→ref/epoch다. consent=absent/revoked/wrong scope는 **각각 CONSENT_REQUIRED 하나**다. budget missing/rollback은 BUDGET_REQUIRED/LEDGER_ROLLBACK_DETECTED, ref stale는 AUTH_REQUIRED다. cancel=true면 CANCELLED가 우선한다. 새 permit 발급 뒤라도 각 O/H/B/F에서 다시 검사한다.

F는 session-scope 고정 fixture다. field0 ref.provider·1 ref.endpoint·6 ref.execution·7 ref.epoch만 불일치하면 AUTH_REQUIRED, field2 capability·3 data_type·4 request.session_id는 해당 exact grant 부재/범위 불일치로 CONSENT_REQUIRED, field5 request.session_generation은 permit이 expected binding과 달라 먼저 PERMIT_REVOKED다. grant를 새로 발급해 옛 binding만 남기는 T09도 PERMIT_REVOKED다. 다른 fixture/phase의 code를 허용 집합으로 묶지 않는다.

C2 cut0~4의 grant revoke/키 교체·삭제는 endpoint grant를 먼저 철회하므로 CONSENT_REQUIRED, session revoke는 SESSION_REVOKED, cancel은 CANCELLED, deadline은 TIMEOUT이다. cut5(H/B1 후)는 grant/key의 CONSENT_REQUIRED·session의 SESSION_REVOKED code는 유지하되 known=false/Job REMOTE_UNKNOWN, cancel/deadline은 REMOTE_OUTCOME_UNKNOWN이다. credential-only stale(ref만 불일치)와 실제 key-command의 grant 철회를 혼동하지 않는다.

## 5. 입력 공간·기본520과 보강199

### 5.1 공통 손 fixture/분모

route 0..4는 독립 literal 목록: OpenAI/STT/audio, Gemini/STT/audio, OpenAI/summary/transcript, Anthropic/summary/transcript, Gemini/summary/context. 서로 다른 exact HTTPS fixture endpoint를 사용한다. provider enum/TEMPLATES/parser/schema factory로 route/expected를 만들지 않는다. 실제 서비스/모델 전체의 조합을 뜻하지 않는다.

direct gateway 기본 body는 b'abcdef', chunk3, 예산 limit100/예약80, 정상 응답 b'{}', K_A/K_B는 비민감 서로 다른 canary다. 실제 adapter 통합 P/Q는 각 route에 맞는 작은 합성 WAV/전사와 손 literal 정상 응답/비용 fixture를 사용한다. 운영 가격/모델/계정을 추측하지 않는다. 모든 network/credential는 주입 fake이고 OS DNS·실제 WinCred·실서비스 호출0이다.

벡터 (R,D,O,T,H,B,F)는 실제 fake vault read·fake DNS·open·transport의 앱 auth 사본 수락·wire header 진입·비어 있지 않은 body write 진입·성공 채택 횟수다. direct 정상은 (1,1,1,1,1,2,1). ticket I/U/폐기·실제 bytes/작업 ACK는 별도 계수다. 부분 write 진입을 성공한 bytes나0 bytes로 추정하지 않는다. 모든 행은 원본 canary/확정 media 불변·출력 비밀0을 요구한다.

| family / ID | literal 범위·분모 | C1 대비 |
| --- | --- | ---: |
| A GS05-A-{r}-{c}-{b}-{x}-{e} | r0..4 × consent0..3 × budget0..2 × cancel0..1 × epoch0..1 =240 | 유지240 |
| B GS05-B-{r}-{v} | r0..4 × read_result0..7 =40 | 유지40, 공개 오류 정정 |
| C GS05-C2-{q}-{cut} | cause0..5 × B의 cut0..5 =36 | C1 GS05-C 36 폐기/36 대체 |
| D GS05-D-{r}-{fault} | r0..4 × fault0..8 =45 | 유지45, 중간 cleanup assertion은 L로 추가 |
| E GS05-E-{id:02} | 00..11=2×2×3, 12..19 named8 =20 | 유지20, native 변경 잠금/소유 정정 |
| F GS05-F-{r}-{field} | r0..4 × field0..7 =40 | 유지40, code·변경 field 위치 고정 |
| G GS05-G-{sink}-{stage} | sink0..11 × stage0..5 =72 | 유지72 |
| U GS05-U-{action}-{gen} | action0..7 × gen0..1 =16 | 유지16, 부족 경로 V로 추가 |
| X GS05-X-{id:02} | 00..10 named11 | 유지11 |
| 기본 | 240+40+36+45+20+40+72+16+11 = **520** | C1의620은 오류 |
| P GS05-P-{r}-{outcome} | r0..4 × outcome0..8 =45 | 신규 AUTH 전체 경로 |
| Q GS05-Q-{r}-{handoff}-{code} | r0..4 × H-partial/B1-partial 2 × AUTH_REQUIRED/VAULT_READ_FAILED 2 =20 | 신규 post-handoff 우선순위 |
| L GS05-L-{r}-{wait} | r0..4 × B2전/응답 read전 2 =10 | 신규 중간 secret lifetime |
| V GS05-V-{entry}-{kind}-{gen}-{delay} | entry0..10 × stt/summary 2 × gen0..1 × native/coordinator delay2 =88 | 신규 전체 UI 입장 |
| S GS05-S-{outcome}-{view} | outcome0..3 × view0..3 =16 | 신규 key 접수/실패 UI |
| T GS05-T-{id:02} | 00..19 named20 | 신규 ticket/제어/변경 소유 |
| 보강 | 45+20+10+88+16+20 = **199** | 기본에 몰래 합치지 않음 |
| 총계 | **520+199=719 / 15가족** | 계획·실행0 |

old C cut은 A의 보호된 R/Q 순서였다. old cut0은 새0/1/2로 ticket 발급/사용/실제진입을 분해했고, old cut1은 새3에서 Q가 **R 반환 전 commit**하도록 바꿨다. old cut2(r→O 전 무효화)는 T12·현재 r 검사로 보강하고, old cut3/4는 새4/5에 대응한다. old cut5(B2→F 전)는 T16으로 옮겼다. 기존 GS05-C ID36은 C2 ID36과 같은 실행 ID가 아니며 A 결과를 B 증거로 재사용하지 않는다.

각 표의 raw 대표 집합은 명시한 직적/named trace이고 이 bound 안의 제외는0, feasible는 표의 수와 같다. 거부·실패도 fixture로 구성할 수 있어 분모에 남긴다. 총계는 tagged family의 합이다. 실제 지원 불가 route·악성 동일 사용자 OS sandbox·프로토콜상 B2가 H보다 앞서는 순서는 별도 한계다. 거부 입력·복수 실패·stale ticket을 F에서 빼지 않는다. named trace는 기재한 event 순서 bound이며 모든 OS 스케줄의 전수라는 주장은 없다. source generator의 len으로 expected 분모를 만들지 않는다.

### 5.2 기본 family의 literal oracle

**A:** consent={0 current,1 absent,2 revoked,3 wrong session scope}; budget={0 valid,1 missing reservation,2 rollback witness}; cancel={0 clear,1 set before I}; epoch={0 current,1 stale ref only}. 구조는 정상으로 고정한다. 우선순위 cancel→consent→budget→ref. 각각 CANCELLED, CONSENT_REQUIRED(1/2/3 공통), BUDGET_REQUIRED/LEDGER_ROLLBACK_DETECTED, AUTH_REQUIRED. 실패 I/R/D/O/T/H/B/F0. 전부 통과한5행만 정상, 거부235행. R 전 실패가 native read를 먼저 하게 해서는 안 된다.

**B:** read_result0..7=K_A/None/빈 bytes/NUL/2561bytes/invalid UTF-8/backend 예외/기한 뒤 반환. 전부 I1/U1/R1,0만 정상.1 AUTH_REQUIRED,2..6 공개 VAULT_READ_FAILED,7 TIMEOUT. 실패 D/O/T/H/B/F0, known=true·retryable=false, 예약 RESERVED80·UNKNOWN0. 내부 VAULT_INVALID_VALUE는 공개 expected가 아니다. unavailable과 stale-ref R0는 P에서 전체 경로로 보강한다.

**C2:** cause0..5=grant revoke/cancel/key replace/key delete/session revoke/deadline. Q/취소/기한 사건은 단독 원인으로 주입한다.

| cut | 강제 순서 | I/U/R | (D,O,T,H,B,F) | 독립 기대 |
| --- | --- | --- | --- | --- |
| 0 | Q 또는 취소/기한 사건이 I보다 먼저 | 0/0/0 | 0/0/0/0/0/0 | 새 ticket0·native0 |
| 1 | I 뒤 사건, U 마지막 검사보다 먼저 | 1/0/0 | 0/0/0/0/0/0 | unused ticket 폐기, read0 |
| 2 | I→U 마지막 검사→사건 commit→실제 R | 1/1/1 | 0/0/0/0/0/0 | 늦은 물리 read 가능·값 폐기. Q 뒤 R0이라 주장하지 않음 |
| 3 | R 진입/정지→사건 commit→r | 1/1/1 | 0/0/0/0/0/0 | commit이 r를 기다리지 않음·discard1·새 송신0 |
| 4 | r/O 성공→사건→H | 1/1/1 | 1/1/1/0/0/0 | 로컬 사본은 있었으나 wire0·known-unsent |
| 5 | H/B1 완료→사건→B2 | 1/1/1 | 1/1/1/1/1/0 | body b'abc'만·UNKNOWN80 유지·F0 |

**D:** fault0 resolver admission 거부: R/O/T/H/B/F=0/0/0/0/0/0;1 read 후 lease 오류=1/0/0/0/0/0;2 O guard enter 거부=1/0/0/0/0/0;3 O guard exit=1/1/1/0/0/0;4 header 뒤 body 전 오류=1/1/1/1/0/0;5 첫 body가 b'a'만 수락 후 오류=1/1/1/1/1/0;6 응답 오류=1/1/1/1/2/0;7 close 오류=1/1/1/1/2/1;8 결과 guard 거부=1/1/1/1/2/0. O가 없으면 DNS0, O가 있으면 DNS1. 0..3 known-unsent,4..6/8 UNKNOWN80;7은 기존 승인 성공을 close 오류로 뒤집지 않는다. 모든 경우 앱 참조 cleanup, 자동 retry0. H/부분 body는 실제 bytes를 별도 기록한다.

**E:** 00..11은 action save/delete × outcome success/failure × phase 옛 요청 없음/R전/B1후, index=action*6+outcome*3+phase. 실패도 epoch/revoke rollback0, R전 old ref send0, B1후 추가 body0/UNKNOWN 유지.12 다른 provider 같은 endpoint 비간섭;13 같은 provider 다른 endpoint 비간섭;14 같은 endpoint의 STT/summary old ref 동시 무효;15 저장하지 않은 입력 변경은 기존 credential epoch/값 불변;16 save→delete FIFO 최종 부재;17 delete→save 최종 새 키/재동의 필요;18 늦은 callback/close 뒤 적용0;19 새 앱에서 old ref0. native 변경 중 공용 잠금0은 T18에서 별도 관측한다.

**F:** field0 ref.provider,1 ref.exact endpoint,2 request.capability,3 data_type,4 request.session_id,5 request.session_generation,6 ref.execution,7 ref.epoch. 하나만 바꾸고 session-scope의 나머지 권한은 current. 전부 R/D/O/T/H/B/F0, code는 §4.2의 단일 표대로다.

**G:** sink0..11=DTO repr/공개 serializer/config_key/Job DB·event/consent DB/cost DB·witness/일반 설정·export metadata/구조화 로그/exception·safe error DTO/UI status/support bundle 해제/crash용 safe metadata. stage0..5=prepare/read 예외/부분 header 예외/정상 완료/key 저장 실패/late callback. 각 출력 동작을 실제 안전 fixture로 호출하고 canary/secret hash0·허용 필드 동일을 확인한다. 파일 부재만으로 통과시키지 않으며 intentional vault/hints·허용 wire 관측 예외를 로그/DTO로 확대하지 않는다.

**U:** action0..7=STT준비/summary준비/save/delete/revoke/설정변경/close/완료callback, gen0 same/1 changed. GUI native/coordinator 진입0·pending·late 적용0·원본 제어 독립. 부족한 실제 버튼/조회는 V로 각각 실행한다.

**X:**00 local Whisper ref 없음(R/network0);01 검증된 local Ollama(R0, 기존 fake loopback만);02 local에 cloud ref(INPUT_INVALID,0);03 미지원 route(CAPABILITY_UNSUPPORTED,0);04 cloud auth binding 없음(AUTH_REQUIRED,0);05 raw auth ExecutionContext 생성(INPUT_INVALID,생성 수락0);06 Run의 adapter auth 덮어쓰기(INPUT_INVALID,0);07 같은 context 두 HTTP 요청(R2, 각 요청별 예약/ticket);08 한 요청 두 chunk(R1,H1,B2);09 timeout/UNKNOWN 뒤 자동 retry0, 새 명시 요청은 새 권한/예약;10 direct gateway 빈 body(R1,H1,B0,header 부분 오류 UNKNOWN). X10은 제공업체의 유효 추론 입력/새 GET route를 뜻하지 않는다.

### 5.3 보강 P/Q/L의 전체 경로·중간 수명

**P outcome0..8:** 정상/키None/stale-ref/VAULT_UNAVAILABLE/빈 bytes/NUL/2561bytes/invalid UTF-8/backend read 예외.5 route마다 실제 provider→Run→실제 Gateway+fake vault/ledger→실제 claim된 Job/Attempt 결과를 관측한다. stale만 R0, 나머지 R1.0은 성공 채택·정확 auth header,1..8은 §4.1 code·false retry/true known·DNS/O/H/B/F0·RESERVED80/unknown0·Job BLOCKED/AUTH·Attempt FAILED. missing은 AUTH_REQUIRED, unavailable은 VAULT_UNAVAILABLE, malformed/예외는 VAULT_READ_FAILED다. 키 값/예외 canary0. 정상 요청의 usage 정산을 하지 않은 fixture는 기존처럼 UNKNOWN80이 남을 수 있으며 이를 청구 확정으로 부르지 않는다.

**Q:** H는 header가 일부 handoff된 뒤 body0에서 raise, B1은 body의 첫 일부 bytes 뒤 raise. fake transport가 AUTH_REQUIRED 또는 VAULT_READ_FAILED처럼 보이는 SecurityError를 낸다. native read는 정상1, 추가 read0. gateway/Run/provider 공개 REMOTE_OUTCOME_UNKNOWN·known=false, Job BLOCKED/REMOTE_UNKNOWN·Attempt UNKNOWN·UNKNOWN80 유지·refunded0·자동 retry0다. read 전 오류 normalization을 이 뒤까지 적용해 AUTH/known으로 낮추면 실패다.

**L wait0/1:** 정상 read1/첫 write 완료 뒤 wait0은 B2 gate 밖, wait1은 모든 body 뒤 응답 read 입구에서 Event로 멈춘다. F는 아직0이고 request finally는 실행되지 않았다. 그 상태에서 lease released=true·secret slot None·민감 dict/declared closure/transport auth 사본0을 **call assertion**으로 확인한다. fixture의 원래K·wire/hints는 따로 둔다. finally에서만 clear하는 변이는 Event를 풀기 전 이 assertion에서 FAIL해야 한다. 정리 지연을 timeout/teardown error로 검출했다고 세지 않는다.

### 5.4 V88: GUI action과 두 종류의 지연

entry0..10은 grant/budget/refresh/reset_clock/adopt/settle/scope-view·selection·retry trace/cost-policy·mode·currency·period-edit trace/constructor initial refresh/post-command success refresh/post-command failure refresh다. 각 trace는 열거한 실제 signal/조회 경로를 각각 호출·기록하는 bounded trace이며 모든 interleaving의 전수가 아니다. kind stt/summary, gen0 unchanged/gen1는 접수 뒤 선택 세대 변경, delay N=fake native read Event 정지/C=별도 thread의 **동일 DB coordinator 보유**다.

N에서는 R의 held locks=[]와 실제 정책/금융 worker 진입·완료, C에서는 worker의 coordinator 입장 대기와 pending을 관측한다. 둘 다 GUI coordinator/native 진입0, Qt heartbeat 진행·고정 대상/nonce·gen1 callback 현재 화면 적용0, 합성 recorder의 별도 제어 진행을 요구한다. 캡처 제어와 삭제 fence의 실제 경계는 T13~15로 추가한다.

필요 확인 dialog는 합성 앱 fixture에서 사전 고정한 비민감 proposal로 명시 수락/거부를 제어한다. 도구/사용자 승인 UI를 대리 입력하지 않는다. 확인 전/후 worker preflight·commit을 구분하고 worker가 현재 정책을 재검사한다. cached view가 없으면 준비 요청·pending을 관측하되 GUI에서 DB 조회를 대신 실행하지 않는다. 올바른 경로의 양성 대조는 실제 worker 조회/commit에 도달해야 한다.

coordinator spy는 GUI의 금지된 acquire/native **진입 순간**을 기록하고, 오구현/변이에서 GUI가 실제로 block되기 전에 sentinel로 중단하도록 한다. 주 assertion은 gui_forbidden_entries==0이며 Qt exception/timeout이 아니다. barrier는 assertion 실패 때도 finally에서 해제한다. 그중 refresh 한 경로만 옛 GUI 직접 호출로 되돌린 변이는 V02의 thread/입장 assertion에서 FAIL해야 한다.

### 5.5 S16: 접수·native 실패·callback

outcome0 queue capacity 거부/1 접수 후 write 성공/2 접수 후 VAULT_WRITE_FAILED/3 write 성공 뒤 다음 명시 요청에서 VAULT_READ_FAILED, view0 current/1 선택 변경/2 같은 선택의 더 새 command nonce/3 widget closed다.0은 RESOURCE_EXHAUSTED, native0·입력 원문 유지·pending0.1..3은 **enqueue 성공 즉시** 입력 empty, native 진행 중 pending, 완료 전 ACK0, 실패도 callback 비밀/입력 복원0.2는 safe write 오류+재입력,3의 다음 요청은 P의 known-unsent AUTH 의미다. view1/2/3의 옛 callback 현재 UI 적용0; 닫힌 widget 접근0. 접수 성공과 네이티브 성공을 같은 시점으로 세지 않는다.

### 5.6 T20: ticket·제어·native 변경 순서

| ID | 명시 입력/순서 | 손 oracle |
| --- | --- | --- |
| T00 | 동일 ticket에 경쟁 소비자 A/B 두 명이 실제 소비 gate 도달→경쟁 종료/승자 lease 정리→같은 ticket으로 종료 뒤 replay | 실제 진입 A/B 각1, 단회 전이 승자1·패자 AUTH_REQUIRED, native R 합1·lease 생성 합1. 패자/replay의 추가 lease·R·송신0, replay AUTH_REQUIRED. 아래 한 bounded trace로 고정 |
| T01 | 모르는 nonce | AUTH_REQUIRED,R0 |
| T02/03 | ticket provider/endpoint 각각 한 필드만 다른 요청 | AUTH_REQUIRED,R0 |
| T04/05/06 | ticket request ID/body digest/reservation ID 각각 불일치 | AUTH_REQUIRED,R0, 다른 요청으로 빌려 쓰기0 |
| T07 | I 뒤 U 시 기한 만료 | TIMEOUT,R0, ticket 폐기 |
| T08 | I 뒤 U 전 Event.set | CANCELLED,R0, native 완료 ACK 발명0 |
| T09 | I 뒤 grant 재발급, old captured binding으로 U | PERMIT_REVOKED,R0 |
| T10 | I 뒤 credential epoch만 달라짐 | AUTH_REQUIRED,R0 |
| T11 | unused ticket abandon/정리 | R0·token 비밀0·재활성화0 |
| T12 | 정상 R 진행 중 같은 대상 키 변경 완료, old R이 K_B 반환 | Q/native 변경 완료가 R 반환을 기다리지 않음; r discard1·O/H/B/F0·lease0 |
| T13 | R Event 정지 중 grant revoke와 정상 녹음 stop | revoke commit·source/consumer/sealer의 정상 ACK가 먼저 진행, read 완료 ACK는 아직0 |
| T14 | R 정지 중 실제 delete→before_delete→recorder.close→Library.delete | native 잠금0, revoke/정상 capture 해제·durable 삭제 intent/fence 진행. AI reader가 남으면 DELETE_PENDING, 강제 삭제0 |
| T15 | R 먼저 시작 후 삭제 intent가 생긴 대상의 retry 경로 | before_delete/close/재시도 fence 진행, 남은 reader를 종료로 꾸미지 않음 |
| T16 | B2 뒤 grant revoke, F 전 | F0·CONSENT_REQUIRED known=false·UNKNOWN80, old C cut5를 대체 |
| T17 | 같은 대상 native 변경 pending 중 app grant 및 out-of-band grant 후 I 시도 | app grant AUTH_REQUIRED·수락0; low-level grant가 생겨도 I는 AUTH_REQUIRED/ticket0, pending 완료 전 실행0 |
| T18 | 같은 대상 native 변경 두 명령, 첫 native Event 정지 | native 변경은 FIFO·겹침0, 각 native의 공용 held locks=[], 다른 endpoint 정책/제어 진행. 최종 nonce만 완료 채택 |
| T19 | native key 변경 실패 뒤 old ref 사용 | epoch/철회 rollback0·old read/send0·pending 완료 시점은 실제 실패 반환 뒤, 새 명시 동의 전 재실행0 |

**T00의 경쟁·replay 손 oracle(GS05R-05):** 현재 권한/기한/epoch와 scope가 같은 단일 ISSUED ticket을 한 번만 발급한다. A/B는 같은 소비 호출을 각각 한 번 수행하고, 실제 단회 상태 전이 직전의 **잠금 밖 진입 gate**에서 둘의 도달을 먼저 관측한 후 해제한다. 호출 thread를 만들었다는 사실만으로 실제 경쟁 진입을 대신하지 않는다. 승자 identity는 A/B 어느 쪽이든 가능하되, 결과의 손 기대는 성공1·AUTH_REQUIRED1, 실제 ISSUED→CONSUMED 승인1, 주입 fake vault의 실제 read 합1·앱 lease 생성 합1이다. 정상 소비 경로와 실제 read/lease 생성 경로를 호출하며 consume/CAS 반환값을 fake 성공/실패로 꾸미지 않는다.

이 unit trace는 승자가 resolver lease를 받은 뒤 앱 소유 lease를 해제하는 경계까지 수행하고 network 단계는 호출하지 않는다. DNS/O/H/B는 합0이고 패자의 lease/read/송신은 각각0이다. A/B 호출이 모두 실제 종료하고 승자 lease 정리 완료·잔여 lease0을 관측한 **뒤**, 동일 ticket으로 세 번째 호출 replay를 한다. replay는 AUTH_REQUIRED, 추가 승인/read/lease/송신0이며 최종 native R 합1·lease 생성 합1을 유지한다. 패자 또는 replay가 추가 read를 한 뒤 뒤쪽 permit/비용 guard에서 막힌 결과는 실패다. 이 여러 사건은 기존 named T00 하나의 bounded trace이며 새 의미 ID/행으로 합산하지 않는다. primary는 기존 unit `test_ticket_once`다.

**C2-M11의 결정적 관측/scheduling seam:** 진입 gate와 상태 확인·commit 관측을 구분한다. 상태 확인/commit 안의 hook은 비차단 기록만 하고, 시험 scheduler의 대기는 **모든 서비스/정책 잠금이 해제된 상태 연산 경계**에서만 허용한다. 정상 구현은 check+commit이 한 원자 연산이므로 그 사이 외부 대기 지점이 없고, 첫 승인 뒤 다른 소비자는 CONSUMED 또는 그 후속 상태를 보고 거부한다. 정상 mutex 안에서 두 contender의 도달/상태 확인을 서로 기다리게 하지 않는다.

단일 mutant는 원자 check+commit을 분리해 'ISSUED 확인 및 그 잠금 해제→재검사 없는 CONSUMED commit'으로 바꾼 경우다. 위 관측 seam으로 A의 확인 후·commit 전 **잠금 밖**에서 A를 멈추고, B도 실제 ISSUED를 확인한 것을 기록한 뒤 양쪽 commit을 진행시킨다. 정상본의 확인/commit 사이를 강제로 열거나 시험이 원자 상태를 대신 변경하지 않는다. 같은 observer/scheduler는 정상본에서 원자 commit 후에만 제어를 받아 두 성공을 만들 수 없고, mutant에서만 두 ISSUED 확인이 첫 commit보다 앞선 실제 이력을 만든다. seam의 실제 API/소스 위치·잠금 미보유 확인은 X00의 구현 API 승인 때 고정한다. 숨은 외부 잠금/관측 API 때문에 이 이력을 구성할 수 없으면 검출됐다고 하지 않고 seam/실패/변경안을 먼저 보고한다.

정상본 목표 PASS 뒤 한 TEMP 사본에 이 결함 하나만 넣고, mutant의 실제 call 결과에서 `consume_successes == 1` 및 `native_reads == 1`/`leases_created == 1` 같은 목표 assertion이 FAIL해야 한다. 뒤 network guard가 송신을 막아도 두 소비 성공/read/lease를 허용하지 않는다. 두 contender 실제 진입·상태 이력이 없거나 mutex 안 barrier·timeout/teardown/import 오류만 발생하면 INVALID이며 KILLED로 세지 않는다. barrier/worker/lease는 assertion 실패 때도 finally에서 회수한다. 실제 정상/변이 실행은 아직0이다.

T14/15는 기존20파일 밖 main.py/recording/storage를 **변경하지 않고** 실제 공개 제어 흐름을 새 UI 시험에서 호출하는 계획이다. 추가 source 수정이 필요하거나 B에서도 control/fence 지연이 확인되면 파일·실패·변경안을 X00에 먼저 보고한다. native 진입의 held-lock assertion과 control 진입/완료 Event를 사용하고 긴 sleep/timeout만으로 성공·실패를 판정하지 않는다.

## 6. Primary ID/선택 소유

| 새 시험 파일 / 제안 node | primary ID 집합 | 수 |
| --- | --- | ---: |
| tests/unit/test_secret_lifetime.py / test_admission_cube,test_key_model,test_binding,test_closed_routes,test_ticket_once | A240+E20+F40+X11+T00..11 12 | **323** |
| tests/integration/test_secret_lifetime.py / test_read_results,test_read_orders_b,test_fault_cleanup,test_auth_pipeline,test_post_handoff,test_first_write_release,test_key_concurrency | B40+C2 36+D45+P45+Q20+L10+T12/16/18/19 4 | **200** |
| tests/property/test_secret_lifetime_case_space.py / test_output_space | G72 | **72** |
| tests/ui/test_secret_lifetime_ui.py / test_existing_ui_bounds,test_all_security_entries,test_save_admission,test_control_during_read | U16+V88+S16+T13/14/15/17 4 | **124** |
| 합계 | 323+200+72+124 | **719** |

단위 node/param의 suffix는 §5의 literal 인자 범위와 정확히 대응한다. 위 집합은 서로 겹치지 않는다. property 파일의 별도 ID audit는 이719와 예상 분모/인자 집합·primary 파일·실제 collection/call/deselected를 대조하지만 **감사 node를 의미 행으로 합산하지 않는다**. 보강을 기존520에 섞거나 subset 선택에 전체719를 강제해 teardown만 실패시키지 않는다. 실제 node/수집/실행 hash 감사는 구현 후 별도다.

## 7. 단일 mutation 61개 계획

C1의 expanded44는 이름/의미를 보존하되 아래 code·B 순서·목표로 정정한다. single23(M01..26에서 M20/22/24 제외)+M20-02..06 5+M22-03..11 9+M24-00..06 7=44. C2-M01..17 17을 추가해 **61개**다. 실제 편집 source/행·기준/변이 hash는 구현 뒤 고정한다. 아직 PASS/KILLED/SURVIVED/INVALID 결과는 없다.

| label/개수 | 단일 의미 결함 | 목표 primary ID/실패 assertion |
| --- | --- | --- |
| M01 | prepare에서 실제 키 읽기 | A·U 준비 R0/context 비밀0 |
| M02 | I의 cancel 검사 생략 | A cancel1/I0·R0 |
| M03 | 동의 검사를 read 뒤로 이동 | A consent1..3/I0·R0 |
| M04 | 비용 검사를 read 뒤로 이동 | A budget1..2/I0·R0 |
| M05 | ref epoch 비교 제거 | A epoch1/F7 AUTH_REQUIRED·R0 |
| M06 | None 키로 계속 진행 | B1 D/O/H/B0 |
| M07 | malformed credential 검증 우회 | B2..5의 공개 VAULT_READ_FAILED·송신0 |
| M08 | backend repr를 공개 오류에 포함 | B6/G의 canary0 |
| M09 | read 후 공통 deadline 검사 무효 | B7/C2 deadline의 O/H0 |
| M10 | H의 permit 재검사 한 곳 제거 | C2 cut4의 H0 |
| M11 | 공통 cancel 관측 거부 제거 | C2 cancel cut1..5의 해당 다음 gate0 |
| M12 | 공통 ref/epoch 검사 제거 | F7/T10·key 변경의 다음 승인0 |
| M13 | H 뒤 오류를 known/refund로 낮춤 | D4..6/Q UNKNOWN80 |
| M14 | abort/request 종료의 참조 cleanup 제거 | D fault별 잔여 앱 사본0 |
| M15 | 빈 body에서 H/UNKNOWN을 생략 | X10 H1/B0·부분 H UNKNOWN |
| M16 | 기존 owner guard 제거 | D2/3/8의 거부·late F0 |
| M17 | native 변경 실패 때 epoch 복원 | E 실패/T19 old ref 거부 |
| M18 | ref를 exact endpoint 없이 provider만으로 결속 | E13/F1 대상 비간섭·scope 거부 |
| M19 | 완료 callback 선택 세대 검사 제거 | E18/U gen1/S view1~3 적용0 |
| M20-02..06 /5 | capability/data/session/session-generation/execution 비교 각각 하나 제거 | 해당 F2..6 R0·단일 code |
| M21 | 공개 plan serializer에 인증 필드 추가 | G sink1 허용필드·비밀0 |
| M22-03..11 /9 | 각 출력 sink 하나에 raw key 추가 | 해당 G sink3..11 비밀0 |
| M23 | native 작업을 GUI에서 직접 실행 | U thread/입장0 |
| M24-00..06 /7 | local Whisper read/local Ollama read/local cloud-ref 수락/unknown cloud fallback/missing auth fallback/raw auth context 생성 수락/adapter auth 덮어쓰기 각각 | X00..06의 R0·명시 거부·정확 auth. X05는 context 생성 수락0 |
| M25 | Run/context에 첫 비밀 cache | X07 R2·X08 R1 |
| M26 | UNKNOWN 뒤 자동 retry | X09 automatic retry0 |
| C2-M01 | 첫 write cleanup을 request finally까지 지연 | L10의 **F 전/대기 중** lease/header0 call assertion |
| C2-M02 | gateway raw invalid 오류를 정규화하지 않음 | P malformed/UTF8의 공개 VAULT_READ_FAILED |
| C2-M03 | Run이 known AUTH를 REMOTE_OUTCOME_UNKNOWN으로 바꿈 | P known=true/Job AUTH/RESERVED80·UNKNOWN0 |
| C2-M04 | post-H의 AUTH처럼 보이는 오류를 known AUTH로 낮춤 | Q20 public REMOTE_OUTCOME_UNKNOWN·Job UNKNOWN |
| C2-M05 | refresh만 GUI 직접 조회로 되돌림 | V entry2의 gui_forbidden_entries==0 |
| C2-M06 | _cost_policy 조회만 GUI로 되돌림 | V entry7의 thread/입장0 |
| C2-M07 | grant만 GUI에서 coordinator로 직접 진입 | V entry0의 thread/입장0 |
| C2-M08 | accepted write 실패 callback이 입력 키 복원 | S outcome2의 입력empty·callback 비밀0 |
| C2-M09 | enqueue 거부에서도 입력 clear | S outcome0 입력보존·pending0 |
| C2-M10 | Gateway.for_session이 auth binding을 유실 | P 정상 route의 성공/정확 header |
| C2-M11 | 원자적 단회 check+commit을 잠금 밖 간격이 있는 분리 check/재검사 없는 commit으로 변경 | T00의 A/B 실제 경쟁에서 성공1·AUTH_REQUIRED1·native R합1·lease 생성합1 call assertion. 종료 뒤 replay의 추가 lease/read/송신0도 유지 |
| C2-M12 | ticket request/body/reservation scope predicate를 무조건 참으로 | T04..06 R0 |
| C2-M13 | native read 동안 coordinator를 다시 보유 | C2 cut3/T13~15 native held locks=[]·Q/control 진행 |
| C2-M14 | r에서 무효 값을 폐기하지 않고 다음 continuation에 제공 | C2 cut2/3·T12의 discard1/invalid-value offer0/앱 lease0 |
| C2-M15 | native set/delete 동안 공용 coordinator 보유 | T18 native held locks=[]·다른 endpoint 진행 |
| C2-M16 | pending target의 app grant gate 허용 | T17 app grant 수락0·새 ticket0 |
| C2-M17 | 같은 대상 mutation 명령의 FIFO를 제거 | T18 native 변경 겹침0·최종 nonce |

C2-M13/15는 native 진입에서 lock 소유를 먼저 관측해 call assertion으로 실패시킨다. Q/control Event의 미도달 timeout만으로 KILLED라 하지 않는다. C2-M14는 단순 guard 호출 횟수가 아니라 read 값의 **폐기/다음 단계 제공**과 앱 소유 참조를 관측한다. 뒤 O guard가 우연히 송신을 막더라도 무효 secret의 다음 단계 제공은 실패다.

정상본 목표 PASS 뒤 **각각 별도 TEMP 사본에서 한 결함만** 주입한다. M07 등 미변경 baseline 검사 자체를 대상으로 할 경우에도 workspace의 vault.py 쓰기를 허용하는 것이 아니며 실제 mutation source seam을 X00에게 먼저 고정한다. 수집/import/syntax·ACL·timeout·teardown만 실패하면 INVALID, 동치/생존은 독립 검토한다. 61/61 검출이나 모든719행의 mutation 실행을 지금 주장하지 않는다.

## 8. 향후20파일 영향과 독립 검증

### 8.1 정확 manifest — 제품 쓰기 승인이 아님

| 구분 | 정확 경로 | C2 목적 |
| --- | --- | --- |
| 제품1 신규 | src/recoryn/security/credentials.py | secret-free ref·single-use ticket·lease·key command FIFO/pending/epoch. native는 모든 공용 잠금 밖 |
| 제품2 | src/recoryn/security/gateway.py | auth binding/for_session 보존, I/U/r와 O/H/B/F 재검사·좁은 AUTH 정규화·중간 cleanup |
| 제품3 | src/recoryn/security/transport.py | 첫 write/abort/close에서 앱 header 사본 정리. 새 method/route 없음 |
| 제품4 | src/recoryn/providers/contracts.py | raw auth context 거부·secret-free DTO/serializer·호환 protocol 경계. 새 ref 필드의 암묵 유실 금지 |
| 제품5 | src/recoryn/providers/_common.py | 기존 요청/비용 순서와 닫힌 AUTH3+known 전파, post-H 우선순위 |
| 제품6 | src/recoryn/ui/privacy.py | 모든 action/query/refresh의 worker model, key 접수/nonce/세대/close·pending |
| 제품7 | src/recoryn/ui/ai_bridge.py | GUI 캡처·worker 준비와 고정 Gateway 전달. context factory에 비밀 없음 |
| 기존 시험1 | tests/ui/test_privacy_ui.py | AUTH 시점/비동기 키 접수·비밀 없는 문맥의 승인된 기대 변경 |
| 기존 시험2 | tests/ui/test_consent_scope_ui.py | fixture·worker 시점 적응. scope/철회/고정 session 보존 |
| 기존 시험3 | tests/ui/test_cost_cap_ui.py | fixture·worker view 적응. 상한·quote·거부 literal 보존 |
| 기존 시험4 | tests/integration/test_cost_cap.py | 준비 이행, 금액/witness/UNKNOWN 불변 |
| 기존 시험5 | tests/integration/test_egress_independent.py | 실제 header 보관 기대만 새 계약으로 적응. 원 거부/UNKNOWN 반례 유지 |
| 기존 시험6 | tests/unit/test_providers.py | raw auth context 허용→INPUT_INVALID, non-auth mapping 불변/DTO repr 유지 |
| 기존 시험7 | tests/contract/test_provider_contracts.py | 실제 gateway의 auth binding fixture, consent 거부·정상대조·session revoke 유지 |
| 기존 시험8 | tests/integration/test_provider_security_independent.py | fake auth binding으로 이행, UNKNOWN70/close/available30 유지 |
| 신규 시험1 | tests/unit/test_secret_lifetime.py | primary323 |
| 신규 시험2 | tests/integration/test_secret_lifetime.py | primary200 |
| 신규 시험3 | tests/ui/test_secret_lifetime_ui.py | primary124 |
| 신규 시험4 | tests/property/test_secret_lifetime_case_space.py | primary G72 + 의미 행에 더하지 않는 literal ID/선택 감사 |
| 계약1 | docs/testing/gs05-secret-lifetime-cases.md | 이번 C2, 이후 허용된 결과/한계 기록 |

7+8+4+1=20. C1과 파일 수/경로는 같지만 B ticket·전체 UI worker·오류 전파·첫 write cleanup의 책임을 명확히 했다. jobs/failures.py, app/ai.py, runner, vault/_secrets/consent/ledger, diagnostics, main.py/recording/storage, 모델/PC 설정/CI는 읽기 전용이다. 새 route/provider_metadata GET·계정·실제 credential 작업은 추가하지 않는다.

Gateway-bound carrier로 app/ai.py 복사 문제를 피하고 기존 failure table을 변경하지 않는 안이20파일을 유지하는 근거다. 실제 API 조립/시험이 다른 파일을 요구하면 실패·필요 변경을 먼저 보고한다. T control 흐름을 고치기 위해 main.py를 조용히 추가하거나 기존 원본·동의·UNKNOWN·CAS assertion을 약화하지 않는다.

### 8.2 선행·공유 충돌

GS04a의 privacy.py는 아직 미통합이다. X00 공개/CI와 정확 hash 인수 뒤 구현 기준을 새로 고정한다. GS11a와 직접 파일 교집합은 없지만 session/deletion/ACK/control 경쟁은 최종 통합판에서 재검증한다. G09a와 gateway는 직렬 소유하며 ref/ticket/credential epoch를 schema/backup에 저장하지 않는다. G16 자원 정책·G12 선택/CAS·GS04b 사실/route는 별도 축이다. 보호된 native A를 되살려 control을 막는 방식으로 성능/시험을 맞추지 않는다.

### 8.3 60초 제안·증거

신규4파일 **fixture 포함 단독 command wall60초**는 계속 제안이며 아직 측정0이다.719행은 작은 fake 값·임시 DB·합성 media이며 실native/실network를 사용하지 않는다. V의 두 delay는 Event/동기화로 구분하고 fake clock으로 시간 경계를 다룬다. UI spy는 금지 진입을 실제 block 전에 기록하므로 오구현을 timeout으로만 검출하지 않는다. 부모/소유 thread의 모든 barrier/handle을 finally에서 회수한다.

보강199·UI124의 fixture/actual call 비용을 따로 보고하며 정상 row·ID·독립성·control/ACK 단언을 줄여60초를 맞추지 않는다. 초과 시 최초 실패/실측·파일/family별 wall과 최적화/예산안을 X00에 보고한다. 전체 CI/coverage/mutation 시간은 별도이며 다른 단위의100/120/360초를 상속하지 않는다.

향후 허용된 검증은 고정 commit git archive+정확 승인 파일만 OS TEMP 사본, 사본 cwd/rootdir/config/PYTHONPATH/MYPYPATH·부모/실제 spawn import 출처 확인, no:cacheprovider·고유 basetemp·offscreen·HF offline·ResourceWarning 오류화다. CI flag 그대로 coverage85와 check_coverage의6핵심+전체7묶음, Ruff/format/mypy·offline wheel을 요구한다. 의미 ID/선택/실행과 line/branch는 서로 대체되지 않는다. 이번에 이 명령을 실행하지 않았다.

## 9. X00 후속 결정 요청

| 요청 | 이번 반영 / 독립 검토 뒤 확정할 범위 |
| --- | --- |
| API·소유권 | D01 B와 D03의 Gateway-bound auth carrier·ticket scope/기한/단회 상태·for_session 보존, D06 동일 대상 FIFO/pending grant gate의 정확 API. 20파일 밖 이행이 필요하면 쓰기 전에 재배정 |
| 재확인·선행 | GS05R-01~04의 독립 재확인, 520+199=719행/15가족·61변이·primary 323/200/72/124와20파일 수락 여부. GS04a 통합/CI hash와 GS11 최종판의 control/deletion 회귀 기준 및 gateway 직렬 소유 순서 |
| 예산·공용 계약 | 신규4시험 fixture 포함 wall60초 제안과 초과 보고 조건, D04의 세 기대 변경 및 D05 hints256 잔여 수명 반영. 공용 계약 갱신·실제 구현/검증 배정은 X00만 수행 |

D01을 다시 A/B 선택 미정으로 두지 않는다. 위 요청은 갱신된 B 결정에 대한 구현 전 API/범위·독립 수락 확정이며 이번에 제품/시험을 작성하거나 기존 승인을 우회할 요청이 아니다.

## 10. 제출 판정과 미검증

- **CONTRACT_REVISION_READY**: GS05R-01 합계520 정정, R-02 공개 AUTH 전체 전파, R-03 첫 write 중간 수명, R-04 전체 UI·두 delay를 각각 §4~7에 연결했다. D01은 X00 최신 B 결정이며 A의 control 지연 근거/수명 차이를 보존한다.
- 실제719행 수집/실행·61 mutation·60초·coverage·원격 CI·wheel은 NOT_RUN/UNVERIFIED다. 문서의 산식·primary mapping은 계획이며 PASS가 아니다. 독립 검토자가 원 반례와 새 B cut/추가 분모·좁은 오류 mapping·20파일 범위를 재확인해야 한다. 작성자는 GS05R 항목을 단독 CLOSED하지 않는다.
- 실제 WinCred의 native 지연/취소·앱 밖 key 변경·실계정/TLS/모델/음성/장치/Narrator·실과금·OS/HTTP/Python 전체 메모리 zeroization은 검증하지 않았다. read ticket은 원격 권한이나 native 취소 가능성을 보장하지 않는다. 기존 hints256 보관 한계를 유지한다.
- X00의 공용 계약/API·정확 구현 manifest/기준·독립 검토자 확정 전 제품·시험을 작성하지 않는다. 현재 변경은 이 계약 파일 하나이며 Git 통합/push는 X00 소관이다.

## 11. GS05-C4 — 비등록 비용 preflight·O 현재 catalog·정확 범위 개정

상태: **CONTRACT_REVISION_READY / API-R01 반영·독립 재확인 및 X00 범위 승인 전**. 작성 w5:pA, 2026-11-26. 이 절만 끝에 추가하며 앞의 동결 C3 **66,063 bytes/418줄**, raw=LF SHA256 **3bcef72bf706c4f13902e4ac035c061b600ae9f09f2bcfb96bb1b519c524a5c6**를 그대로 보존한다. 앞 절의719/61/20은 C3 당시 계획이고 **이번 제안의 최신 합계는781행/17가족·67변이·30파일**이다.

### 11.1 입력·기준·대체 범위

- 시작 cwd D:/project/Recoryn, HEAD/제품·기존 시험 기준 **b30b3a7b7223fa20ca19ae17fe1975aa80e598f2**, dirty 수정15·미추적14·staged/unmerged0. 고정 commit의 git show/grep만으로 제품·기존 시험을 읽었다. GS11a dirty를 합치지 않는다.
- 동결 API 준비안 build/gs05-api-prep/seams.md LF **a1b6be48c0b7124bc0be10ec1b34c670bc3060692f0bb39ad9e8dacb3b96fa30**, 교차 검토 build/gs05-api-prep/cross-review.md LF **be296d72b38069a97acc498ca8fae9e43815bbaa44d3b25e8ff10e1f1c56a501** 및 H03 GS05-C4를 승인/계획 입력으로 구분한다. C3·교차 검토는 실제 hash를 대조했다. 원격 CI 완료는 조회하지 않았다.
- X00 API-R01 결정은 **ledger 소유 비등록 preflight와 기존 O의 현 catalog 대조·등록1회 분리**다. API 준비안의 I 등록1회→U/r/O write/0 안을 대체한다. catalog 불변 전제를 수락한 것으로 해석하지 않는다.
- X00 보충에 따라 R 중 교체의 r 거부와 **r 성공·잠금 해제 뒤 O 전 교체의 O 거부**를 별도 ID/분모로 고정한다. C3의 B ticket·native 잠금0·T00 경쟁/replay·AUTH·첫 write cleanup·동의/UNKNOWN/원본/CAS는 유지한다.
- 이하 B:는 위 commit의 src/recoryn/, T:는 tests/ 아래 경로다. 정적 source/기존 assertion 확인이며 실행 PASS/FAIL이 아니다. 현재 쓰기는 이 문서 끝 절뿐이고 제품·시험·Git 쓰기/시험 실행은0이다.

### 11.2 실제 ledger 사실과 권장 분리 API

B:security/ledger.py:991–1133의 phase=open은 quote 캐시 pop(:1031), 현 catalog digest 대조(:1071–1073), 기한 설정(:1105), durable dispatch_id 기록과 _Dispatch 생성(:1110–1133)을 한다. :1144–1214의 write는 등록된 동일 body 객체/예약/정책/기한을 검사하지만 **현재 load_catalog digest 대조는 없다**. 따라서 write/0만으로 O의 의미를 대체하지 않는다.

권장 ledger 소유 API는 다음이다. 함수/타입 이름과 정확 signature는 X00가 후속 구현 승인에서 고정한다.

    CostLedger.preflight_request(
        reservation_id, provider, target, body, *,
        data_type, operation, headers=None, prior=None
    ) -> CostPreflight
    CostLedger.validate_dispatch(
        ...기존 인자..., phase="open", preflight=None
    ) -> None

CostPreflight는 비민감 immutable 값으로 예약/request fingerprint·monotonic quote 기한을 묶는다. 자체로 송신 허가가 아니며 prior가 있어도 현재 상태·현재 catalog를 다시 검사한다. body/secret/header를 일반 serializer에 넣지 않는다. O의 optional preflight는 I/U/r에서 확정한 **더 짧은 기한을 연장하지 않기 위한 입력**이고 기존 direct 호출의 기본값 None은 기존 동작을 보존한다.

preflight는 ledger 내부에서 witness/현재 예약·body fingerprint·목적지/데이터/기능/비인증 cost_headers·정책/기간/계정·노출·quote 유효기간·현재 catalog digest와 quote 적합성을 검사한다. 이 검사를 Gateway에 복제하지 않는다. _UnavailableLedger(:1321–1340)는 _verify의 기존 startup 거부를 먼저 통과해야 하므로 미초기화 cache 접근으로 실패를 바꾸지 않는다.

**I/U/r의 금지 부작용:** _prepared_quotes/_reserved_quotes를 pop·재정렬·덮어쓰기하지 않고, _quote_deadlines/_dispatches에 새 항목을 넣거나 기존 것을 바꾸지 않는다. SQL DML/BEGIN IMMEDIATE/_change·witness 쓰기·dispatch 등록·mark_unknown·refund0이다. 유효한 예약을 검사했다는 이유로 durable dispatch_id를 기록하지 않는다. cache hit/miss 모두 비등록이며 miss에서는 요청/quote를 로컬로 재검증한다.

검증용 clock high-water scalar와 검증 stamp/파생 balance cache의 기존 메모리 bookkeeping은 위 금전·quote/dispatch 상태 쓰기와 구분한다. B:ledger.py:259–267의 _last_now 의미를 보존해 preflight 사이 clock rollback을 감추지 않는다. :367–383의 witness 검증을 생략해 무변경처럼 보이지 않는다. 허용할 정확한 파생 메모리 bookkeeping 범위는 X00 API 수락 사항이며 새 durable clock 기록/복구 쓰기를 preflight에 넣지 않는다.

기존 예약에 _quote_deadlines가 있으면 읽기만 한다. 없으면 최초 I에서 로컬 기한을 계산해 CostPreflight로 전달하고 U/r/O는 기존/새 계산/prior 중 가장 짧은 기한을 유지한다. 매 preflight마다 만료를 앞으로 미루지 않는다. 최종 O만 기한·dispatch를 등록할 수 있다. UTC quote 기한과 monotonic 요청 기한을 숫자로 직접 min하지 않고 각 clock의 유효성 및 환산 anchor를 보존한다.

| 단계 | C4 비용 동작 | 등록/네트워크 |
| --- | --- | --- |
| I | 현재 동의/기한·비등록 preflight·ref/epoch/pending 확인 뒤 ticket 발급 | quote cache 소비0·dispatch0·native0 |
| U | 현재 권한/ref·비등록 preflight 재검사 뒤 원자 ticket 소비 | dispatch0, 모든 잠금을 놓고 R로 |
| R/r | R은 공용 잠금 밖. 반환 뒤 현재 권한/ref·비등록 preflight를 다시 검사 | r 실패면 lease/값 폐기·O 진입0·dispatch0 |
| O | r 성공 뒤에도 현재 permit/ref/비용 재검사. 기존 open 검증이 **현 catalog를 새로 대조하고** 적합하면1회 등록 | 이 등록 후에만 owner guard/transport.open. 두 번째 open 등록0 |
| H/B/F | 기존 실제 누적 bytes의 write 검증·첫 UNKNOWN·현재 권한/owner·결과 채택 | 이미 handoff한 UNKNOWN을 preflight 실패/cleanup으로 해제하지 않음 |

O의 open 검증과 transport handoff 사이에는 기존 consent→ledger→owner 순서를 유지한다. I/U/r도 짧은 consent→ledger→credential 순서를 쓰고 native를 그 잠금 안에 두지 않는다. catalog 변경용 시험 barrier는 I/U/r/O의 잠금 해제 지점에서만 기다린다.

preflight와 open은 공통 **검증 계산**을 ledger 내부 helper로 공유할 수 있으나 검증과 등록 부작용은 분리한다. O는 이전 r의 “catalog 통과” 결과를 권한으로 재사용하지 않는다. O에서 current load_catalog를 생략한 뒤 saved digest끼리만 비교하는 대안은 금지한다. O의 cache pop은 기존 등록 경로에서만 가능하고, 거부 시 durable 상태/witness를 쓰지 않는 G06 계약을 보존한다.

### 11.3 추가 입력 공간·독립 손 oracle·합계

C3의719행/15가족을 삭제·재번호하지 않는다. 아래 두 가족은 별도 ID이며 기존 G06 행을 새 GS05 행으로 중복 합산하지 않는다. 제품 enum/TEMPLATES/parser/검증 helper에서 expected를 생성하지 않는다.

| 가족/ID | raw 대표 공간→feasible | 제외 |
| --- | --- | --- |
| K: GS05-K-{route}-{cut}-{catalog} | route0..4 × cut0..4 × catalog0..1 = **50→50** | 0. 거부 순서도 구성 가능하므로 포함 |
| J: GS05-J-{quote}-{cache}-{gate} | VERIFIED/USER_CAP 2 × quote-cache present/miss 2 × I/U/r 3 = **12→12** | 0. cache miss는 보존 예약의 ledger 재열기 등 실제 가능한 상태 |
| C4 보강 | 50+12=**62** | 모든 OS schedule/실서비스 전수라는 뜻이 아님 |
| 최신 전체 | 기본520+C2 보강199+C4 보강62=**781 / 17가족** | 계획·실제 실행0 |

**K의 고정 입력:** route0..4는 C3의 손 literal OpenAI-STT/audio, Gemini-STT/audio, OpenAI-summary/transcript, Anthropic-summary/transcript, Gemini-summary/context다. direct Gateway+실제 TEMP ledger/consent, fake vault/transport로 검사한다. body b'abcdef', chunk3, 예산100/USER_CAP80, 합성 opaque fixture wire·비검증 가격/명시 general 동의로 고정한다. 실제 API/가격이 아니라 현재 G06 fixture가 허용한 주입 시험 profile이다(T:unit/test_cost_cap.py:128–180). 각 route의 대상/모델/기능/입력은 손 literal이며 실제 계정·서비스 인증은 외부 게이트다.

C0와 C1은 같은 wire entry/동일 cap·가격 의미를 갖되 review_id 같은 비금액 입력이 달라 digest가 다른 **두 유효 catalog fixture**다. catalog0은 모든 gate에서 C0 그대로, catalog1은 아래 사건에서 C1로 바꾼다. 저장된 정책/quote/witness는 변경하지 않는다. C1을 파싱 실패·미지원 route로 만들어 오류 원인을 바꾸지 않는다. expected는 현 catalog와 예약 catalog의 불일치에 따른 **COST_QUOTE_MISMATCH** literal이다.

| cut | catalog1의 강제 시점 | I/U/R | catalog1의 독립 oracle |
| --- | --- | --- | --- |
| 0 | 예약 C0 후, I preflight 전 C1 | 0/0/0 | I에서 거부, ticket0·dispatch_id None·DNS/open/header/body/F0 |
| 1 | I 성공·잠금 해제 뒤, U 마지막 검증 전 C1 | 1/0/0 | U에서 거부, 미사용 ticket 폐기·native0·dispatch_id None·송신0 |
| 2 | U 성공/R 실제 진입 Event 정지 중 C1, 그 뒤 정상 키 반환 | 1/1/1 | **r에서 거부**·값/lease 폐기, o_admission_entered0·DNS/open/header/body/F0·dispatch_id None |
| 3 | **r 성공·잠금 전부 해제 뒤**, O admission 전 C1 | 1/1/1 | r는 C0로 성공, **O의 현 catalog 검사에서 거부**, open 등록 성공0·DNS/open/header/body/F0·dispatch_id None |
| 4 | O 등록1회·H/B1 완료 뒤 C1, B2 전 | 1/1/1 | 기존 등록 요청의 write 의미 보존: 추가 read0, b'abc'/b'def'·F1, UNKNOWN80 유지·환급/자동 retry0 |

catalog0의 모든 cut은 정상 양성 대조다: I/U/R 각1, O 등록 성공1, fake DNS/open/header 각1·body2·정확 bytes b'abcdef'·F1, usage 미정산 UNKNOWN80이다. catalog1 cut4도 catalog 변경만으로 기존 요청의 저장된 quote/write 의미를 바꾸거나 이미 handoff한 노출을 낮추지 않는다. **현재 catalog의 O 경계 보존**과 **이미 등록·전달된 요청의 노출 보존**을 구분한다.

catalog1 cut0..3은 known=true·retryable=false·COST_QUOTE_MISMATCH, 현재 예약 RESERVED80·unknown_exposure0·actual 미확정, 예약 이후 snapshot 대비 witness bytes/금전 row/revision 불변이다. app/ai의 remote_intent만으로 UNKNOWN으로 올리지 않는다. 실제 Job 경로를 병행 검증하면 유효 session에서 BLOCKED/BUDGET·Attempt FAILED를 요구하되 K의 primary direct Gateway trace와 이중 집계하지 않는다.

K의 literal 분모는 unchanged25+changed25이고, 정상30/거부20, native read0인10/실제 read1인40이다. 전체 오류가 같아도 cut2는 r 거부/O admission0, cut3은 r 성공/O 검사 거부라는 **사건·실패 위치**를 반드시 관측한다. DNS/open0만 보고 두 cut을 같은 행으로 합치지 않는다. 관측은 실제 단계의 결과·비민감 event이며 내부 guard 호출 횟수만 세지 않는다.

**J의 고정 입력/순수성 oracle:** provider p, endpoint https://cost.invalid/v1/responses, operation summary/data transcript, model fee13, body b'synthetic-packet', USD [0,2000), cap13/limit100. VERIFIED는 opaque fixture fixed_fee13·input/output 가격0의 strict, USER_CAP은 가격시각 미검증 같은 fixture의 명시 general cap13이다. 두 경우 손 금액은13이며 운영 가격 주장이 아니다(T:unit/test_cost_cap.py:46–99,128–147).

quote cache present는 실제 reserve_quote가 만든 같은 살아 있는 CostRequest, miss는 durable 예약은 유지한 ledger 재열기 뒤의 빈 quote cache다. 각 gate의 실제 preflight를 호출하고 이전 I/U의 CostPreflight를 다음 gate에 넘긴다. UTC1000을 유지하고 monotonic은 I=10/U=11/r=12로 진행시킨다. 최초 기한은 **10+(2000−1000)=1010**, 다음 단계도1010으로 연장0이다. fixture 준비/재열기 부작용은 snapshot 전에 끝낸다.

J의 호출 전후 예약은 RESERVED13·dispatch_id None·unknown0, witness bytes/금전 row/revision/DB total_changes 동일, DML/등록/mark_unknown/송신0이다. _prepared_quotes/_reserved_quotes의 키·순서·값/referent와 _quote_deadlines/_dispatches는 동일하며 miss는 miss로 남는다. 허용한 검증 clock/stamp/파생 메모리 bookkeeping은 quote 캐시 소비·등록으로 위장하지 않는다. read-only 검사에서 실제 quote cache를 pop하고 나중에 복원하는 것도 소비0 oracle 위반이다.

### 11.4 primary·기존 G06 대응·행별 mutation

| primary 파일 / 제안 node | C4 추가 | 최신 primary |
| --- | --- | ---: |
| tests/unit/test_secret_lifetime.py / test_nonregistering_preflight | J12 | 323+12=**335** |
| tests/integration/test_secret_lifetime.py / test_catalog_gate_orders | K50 | 200+50=**250** |
| tests/property/test_secret_lifetime_case_space.py / 기존 출력·ID 감사 | 의미 행 추가0, J/K ID 선택 감사 | **72** |
| tests/ui/test_secret_lifetime_ui.py / 기존 UI 경계 | 의미 행 추가0 | **124** |
| 합계 | C4 추가62 | **781** |

K/J 각각 한 primary에만 속한다. 기존 G06-COV3-OPEN-000..003은 T:integration/test_cost_cap.py:2221–2294의 **원 oracle 그대로** 유지한다: 예약 뒤 사전 catalog 변경/저장 digest 불일치 거부는 RESERVED13·dispatch None·opens/writes0·witness 불변이고 unchanged 양성은 등록에 도달한다. 이4개를 새62개에 섞지 않는다. 기존 G06-COV2-WRITE 14행(:2007–2104)의 body identity·scope·정책·노출/만료 반례도 보존한다.

preflight의 quote-cache 재사용 여부를 이유로 같은 bytes의 다른 객체를 기존 write에서 허용하지 않는다. 기존 기간/clock rollback·witness 변조·strict/general·USER_CAP/VERIFIED·UNKNOWN/정산/CAS 의미와 원 금액 oracle를 약화하지 않는다. 실제 실패/범위 밖 적응이 생기면 파일·실패·변경안을 먼저 보고한다.

기존61변이는 유지하며 다음 **C4-M01..06 6개**를 추가해 **67개**를 제안한다. source/행·정상/변이 hash는 구현 후 정확 API에서 고정한다. 각 의미 행은 아래 해당 변이와 기존 변이의 목표에 연결하며 K의 post-H는 기존 M13/C2-M04의 UNKNOWN 보존도 인계한다.

| 새 변이 | 단일 의미 결함 | 목표 ID/실제 call assertion |
| --- | --- | --- |
| C4-M01 | 비등록 preflight 공통 helper의 현재 catalog digest 대조만 생략 | GS05-K-{0..4}-0-1의 I 거부/ticket0. 뒤 U/O가 막더라도 I를 통과시키면 실패 |
| C4-M02 | **O 등록 분기만** 현재 catalog digest 대조를 생략하고 preflight 검사는 유지 | **GS05-K-{0..4}-3-1**. r 성공 뒤 C1 교체, O에서 COST_QUOTE_MISMATCH·등록 성공0/open0. 이 cut 없이 R 중 교체만 죽인 결과로 O 보호를 증명하지 않음 |
| C4-M03 | preflight의 quote cache 조회를 pop/소비로 바꿈 | GS05-J-{0,1}-0-{0,1,2}의 실제 소비0·cache 동일. 나중에 O가 재계산해 성공해도 중간 oracle FAIL |
| C4-M04 | 비등록 preflight가 dispatch 등록/금전 DB 쓰기를 수행 | J12/K 정상의 gate 직후 dispatch None·DML0·witness/row 불변 |
| C4-M05 | Gateway U에서 비용 preflight만 건너뜀 | GS05-K-{0..4}-1-1의 native read0. 뒤 r/O가 거부해도 read1이면 FAIL |
| C4-M06 | Gateway r에서 비용 preflight만 건너뜀 | GS05-K-{0..4}-2-1의 r 거부·o_admission_entered0/무효 값 다음 단계 제공0. O가 같은 code로 뒤늦게 막아도 FAIL |

C4-M02는 동일 body 객체·현재 살아 있는 reserved quote cache를 유지한 USER_CAP fixture에서 O의 해당 대조만 제거하는 의미다. 새 공통 helper 추출로 중복 대조가 생겨 같은 편집이 동치가 되면 그 사실을 보고하고 **O의 현재 catalog 검사만 빠진 한 의미 결함**의 실제 seam을 독립 고정한다. 정상/r 검사까지 함께 제거해 다른 cut에서만 실패시키지 않는다.

정상 목표 PASS→각각 별도 OS TEMP 사본의 단일 결함→위 목표 **call assertion FAIL**을 요구한다. barrier는 모든 공용 잠금 밖이고 실제 stage 진입/종료로 순서를 보증한다. 수집/import/syntax/ACL/timeout/teardown만 실패하면 INVALID다. 781행 실행·67 KILLED를 지금 주장하지 않는다.

### 11.5 AP-05의9후보: 수정/회귀 전용 판정과 근거

이번 정확 manifest는 **GUI capture/비GUI backend prepare의 명시 split API로 이행**하는 안이다. 그 안에서는 아래9후보 모두 실제 fixture/seam/ACK 적응 범위로 제안하며, 이9개 중 수정0의 회귀 전용으로 충분하다고 판정한 파일은0이다. 이름만 옛 prepare wrapper로 남기고 실제 새 준비를 우회하는 호환안을 채택하지 않는다. 순수 local façade를 별도로 보존해 일부를 회귀 전용으로 바꾸려면 실제 반환값/양성 관측을 인계한 새 API·manifest를 X00가 먼저 확정해야 한다.

| AP-05 정확 후보 | 분류 | 고정 b30 근거·허용 수정 / 보존 oracle |
| --- | --- | --- |
| tests/ui/test_local_server_notice_ui.py | **수정** | :145,150–166의 click/processEvents 뒤 실제 grant 활성·write/delete 각1은 worker ACK 대기로 적응. 접수 즉시 UNKNOWN·실제 키 입력·timer 만료(:168–178)·서버 신뢰 안내·무전송은 유지 |
| tests/integration/test_ai_independent.py | **수정** | :962–965,992,1003–1038의 grant→gateway 동기 준비를 실제 backend 완료/고정 execution으로 연결. old/new owner 양성·옛 계획 거부·leases3·정확 delivered·close ACK는 유지 |
| tests/integration/test_resource_policy.py | **수정** | :121–134와160–219의 prepare 실제 예외/준비 +1/+2 관측을 worker 결과에 retarget. budget/grant 완료 대기 추가. 원 T27/T28 code·Jobs/ResourceRequest·wire +0/+1·같은 정책 성공 대조 보존 |
| tests/ui/test_blocked_reason_ui.py | **수정** | :134–143 및353–370의 **두 wrapper**를 새 실제 prepare/반환 context에 연결. fresh execution/config_key/bindings·actual reservation_factory/예약 집합·철회 시점·원 Job/version/reader/CAS 보존. dummy execution으로 목록만 채우지 않음 |
| tests/ui/test_provider_facts_ui.py | **수정** | :43–69의 module/standalone panel fixture 종료에 실제 backend ACK를 추가. panel.close/deleteLater/processEvents만으로 외부 store를 닫지 않음. 실제 facts·memory-only·기본 비전송은 유지 |
| tests/ui/test_resource_policy_ui.py | **수정** | :116–121,228–248,372–388,408–433,700–723의 fake 준비/예외를 실제 backend 준비 seam에 연결하고 완료를 기다림. static 거부 준비0·허용1·**prepared provider의 2차 gate**·새 정책 계속/attempt·local CPU 결과/종료 보존 |
| tests/ui/test_device_policy_ui.py | **수정** | :194–206의 ready config/CONSENT_REQUIRED 공급 seam을 backend로 이행. :207–219의 캡처 정책/_request·diarization spy는 따로 보존. 실제 Job/모델 도달·guard 순서를 약화하지 않음 |
| tests/ui/test_manual_model_ui.py | **수정** | :504–514의 local faster_whisper fake prepare를 선택한 명시 split API의 local worker 준비에 retarget. cloud auth 우회 fallback을 만들지 않음. :518–523 실제 MainWindow 종료·fake local 모델·명시 승인/결과를 유지 |
| tests/ui/test_basis_a11y_ui.py | **수정** | :284–320의 standalone budget/read-model 준비와 종료 ACK, :492–512 throwaway/숨김·파괴 widget 수명 및 key 명령 뒤 실제 revoke 수를 비동기 결과에 연결. 한 key당 명령 수·No 기본·거부 grant0·stale callback0·focus oracle 보존 |

**회귀 전용(수정0)으로 제안하는 별도 예:** tests/unit/test_cost_cap.py의 기존 금액/clock/witness/캐시 fixture와 tests/integration/test_gateway.py의 기존 direct gateway/거부/UNKNOWN oracle는 그대로 실행 대상으로 둔다. preflight 새 literal J/K는 신규 secret_lifetime 시험 안에 작성하고 이 두 파일의 expected를 수정해 맞추지 않는다. 기존 G06-COV3-OPEN/G06-COV2-WRITE는 이미 쓰기 manifest에 있는 tests/integration/test_cost_cap.py 안에서도 원 assertion을 보존하는 회귀다. 같은 파일 안의 fixture 적응과 원 oracle 회귀를 구분한다.

9개를 후보였다는 이유만으로 일괄 허용하는 것이 아니라 위 특정 호출·반환·종료 가정 때문에 각각 수정 범위를 제안한다. 다른 assertion/API를 바꾸려면 실제 실패·최소 변경안을 먼저 보고한다. 이 정적 분류가 전체 프로젝트에서 다른 적응 파일이 전혀 없다는 증명은 아니다.

### 11.6 ledger 포함 정확 manifest 제안30

기존 C3의20개는 유지하고 ledger.py 1개와 위9시험을 추가하는 **30개 proposal**이다. 제품8+기존 시험17+신규 시험4+계약1이다. 지금 제품·시험 쓰기 승인이 아니며 X00의 정확 범위/공용 계약·독립 검토 확정이 선행한다. build API 준비안/교차 리뷰는 동결 근거이지 아래 구현 파일에 넣지 않는다.

| 번호/구분 | 정확 경로 | 제한 목적 |
| --- | --- | --- |
| 01 제품 신규 | src/recoryn/security/credentials.py | 기존 C3 ref/ticket/claim/lease·FIFO/pending·T00 관측 |
| 02 제품 | src/recoryn/security/gateway.py | I/U/r 비등록 preflight·prior 기한 전달·O 등록1회/현 catalog·기존 auth/handoff |
| 03 제품 | src/recoryn/security/transport.py | 첫 write/abort/close의 앱 auth 사본 정리 |
| 04 제품 | src/recoryn/providers/contracts.py | raw auth context 거부·비인증 mapping 불변 |
| 05 제품 | src/recoryn/providers/_common.py | AUTH3/known·UNKNOWN·adapter header 경계 |
| 06 제품 | src/recoryn/ui/privacy.py | capture/backend·view/action·key pending·callback 세대·standalone 종료 |
| 07 제품 | src/recoryn/ui/ai_bridge.py | GUI capture/실제 worker prepare·반환 execution 사용·backend/reader ACK |
| 08 제품 추가 | src/recoryn/security/ledger.py | ledger 소유 비등록 preflight·shared validation/registration 분리·current catalog/기한 보존 |
| 09 기존 시험 | tests/ui/test_privacy_ui.py | 기존 C3 기대/worker 이행, 원 권한·비밀·입력 oracle |
| 10 기존 시험 | tests/ui/test_consent_scope_ui.py | scope/view·명령/worker fixture 이행 |
| 11 기존 시험 | tests/ui/test_cost_cap_ui.py | 비용 view·worker/모달 fixture, 원 cap/UNKNOWN |
| 12 기존 시험 | tests/integration/test_cost_cap.py | 새 API 조립 fixture만, 기존 G06 금액/직접 O/write 반례·목록/ID 보존 |
| 13 기존 시험 | tests/integration/test_egress_independent.py | snapshot 기대 이행·실제 원 거부/guard/부분 전달 |
| 14 기존 시험 | tests/unit/test_providers.py | context raw auth 금지·비인증 불변·safe 오류 |
| 15 기존 시험 | tests/contract/test_provider_contracts.py | 실제 cloud gateway의 fake credential binding fixture |
| 16 기존 시험 | tests/integration/test_provider_security_independent.py | fake resolver/UNKNOWN·안전 오류/close |
| 17 기존 시험 추가 | tests/ui/test_local_server_notice_ui.py | §11.5의 command/native ACK |
| 18 기존 시험 추가 | tests/integration/test_ai_independent.py | §11.5의 grant/prepare/owner 고정 및 종료 |
| 19 기존 시험 추가 | tests/integration/test_resource_policy.py | §11.5의 실제 prepare/예외·budget 완료 |
| 20 기존 시험 추가 | tests/ui/test_blocked_reason_ui.py | §11.5의 두 prepare/예약 관측 |
| 21 기존 시험 추가 | tests/ui/test_provider_facts_ui.py | §11.5의 standalone/backend ACK |
| 22 기존 시험 추가 | tests/ui/test_resource_policy_ui.py | §11.5의 실제 준비/2차 gate/양성 대조 |
| 23 기존 시험 추가 | tests/ui/test_device_policy_ui.py | §11.5의 fake 준비/정책 경계 |
| 24 기존 시험 추가 | tests/ui/test_manual_model_ui.py | §11.5의 local backend 준비 seam |
| 25 기존 시험 추가 | tests/ui/test_basis_a11y_ui.py | §11.5의 keyboard/모달/명령 수·종료 |
| 26 신규 시험 | tests/unit/test_secret_lifetime.py | primary335 = 기존323+J12 |
| 27 신규 시험 | tests/integration/test_secret_lifetime.py | primary250 = 기존200+K50 |
| 28 신규 시험 | tests/ui/test_secret_lifetime_ui.py | primary124, 실제 worker/UI/control |
| 29 신규 시험 | tests/property/test_secret_lifetime_case_space.py | primary72, 781 literal ID/선택 감사 |
| 30 계약 | docs/testing/gs05-secret-lifetime-cases.md | C3 보존·C4 및 후속 승인된 증거 |

수정 없는 회귀 전용 파일은 이30개에 넣어 수를 부풀리지 않는다. security/__init__.py·cost/cost_catalog.py·vault/_secrets·consent·Task·app/ai·Job/runner·main/recording/storage·공통 conftest·CI/패키징은 범위 밖이다. CostPreflight 타입을 export하려고 __init__를 추가하지 않고 ledger에서 직접 import한다. source/fixture 실패가 다른 파일을 요구하면 중단 지점·실패·변경안을 먼저 보고한다.

GS04a 공유 privacy 및 새9시험은 공개판 b30의 timer/identity/UNKNOWN/신뢰/양성 관측을 보존한다. GS11a dirty와 직접 합쳐 검증하지 않으며 최종 control/deletion/reader ACK·staged 원위치 실패 폐쇄 회귀는 정확 통합 hash 인수 뒤 별도로 고정한다. G09와 gateway는 직렬 소유, G16 CPU/GPU·실행 자원 정책은 별도다. 원격 GS04a CI·독립 API/C4 검토 수락 전 제품 승인 없음은 그대로다.

### 11.7 X00 결정 요청·제출과 미검증

| 요청 | 이번 반영 / 후속 확정 |
| --- | --- |
| C4-D01 API-R01 | X00의 비등록 preflight+O 현 catalog/등록1회 결정은 반영했다. ledger 소유 CostPreflight/prior 기한·shared validation와 허용한 비금전 메모리 bookkeeping의 정확 API/독립 재확인 |
| C4-D02 경우의 수 | J12+K50 추가·최신781/17가족·67변이, r/O 개별 거부와 각 목표 assertion/primary335·250·72·124 수락 여부 |
| C4-D03 범위 | 명시 split API에 따라9후보를 각각 수정으로 분류한30파일 제안 및 원 oracle를 보존할 최소 허용 편집. 회귀 전용으로 줄일 호환 API를 택하면 실제 seam/반환/ACK 근거와 manifest를 먼저 재결정 |
| C4-D04 착수/예산 | GS04a CI 완료/정확 기준, GS11 최종 회귀 인수, gateway/privacy 직렬 소유·독립 검토자 및 구현/시험 별도 배정. 신규4시험 fixture 포함60초는 추가62행 비용까지 **재측정할 제안**, 미측정 |

작성자는 API-R01을 독립 CLOSED하지 않는다. 실제 구현·기존 회귀·새781 수집/실행·67 mutation·60초·coverage85/check_coverage7묶음·core.yml flag 동등 검증·offline wheel은 모두 **NOT_RUN/UNVERIFIED**다. 문서의 literal 집합/산식/고유 ID/manifest 정적 대조와 실행 결과를 구분한다.

향후 시험은 고정 git archive+정확 승인 파일만 TEMP 사본, 사본 cwd/rootdir/config/PYTHONPATH·부모/실제 spawn import 출처, no cache·고유 basetemp·offscreen·ResourceWarning 오류화, 부분 선택/actual call ID 감사와 단일 mutant의 목표 assertion을 유지한다. 예산 초과/기존 시험 내부 가정 실패는 로그·파일·변경안을 먼저 보고하며 원 반례·분모/계층을 줄여 맞추지 않는다.

실제 native/강제 취소·Credential Manager·외부 key 변경·실계정/네트워크/서비스/과금·모델/음성/장치·Python/OS 전체 zeroization은 검증하지 않았다. 기존 hints256 한계를 유지한다. 이번 쓰기는 C3를 보존한 이 끝 절뿐이며 Git 통합·공용 계약·최종 승인/원격 push는 X00 소관이다.

## 12 GS-P05 구현 제출 결과 — b30 고정 사본 / X00·독립 검토 대기

이 절만 구현 후 추가했다. 앞선 C4 94,057바이트(LF SHA256 7504c5ba15384c1cacba1baa5b70826798e447326833dcbf4ff2c829d723a7d4)를 그대로 보존했다. 앞 절의 NOT_RUN은 설계 제출 당시 기록이며 아래 실제 실행과 시점이 다르다. 작성자는 최종 승인하지 않는다.

### 12.1 기준·정확 범위·격리

- 작성 w5:pA / GS-P05. 기준 b30b3a7b7223fa20ca19ae17fe1975aa80e598f2의 git archive에 승인 파일만 겹쳤다. GS11a dirty와 작업 트리 다른 단위는 제외했다.
- C4의30파일에 X00 GS05-T15 결정으로 src/recoryn/app/desktop.py의 DesktopRecorder.close만 추가했다(31). 이후 GS05-PUBLICATION-FIXTURE 승인으로 tests/integration/test_publication_independent.py의 합성 인증 carrier만 추가했다(32). 제품9·기존 시험18·신규 시험4·계약1이다. main/recording/storage/Job/공용 계약/배정표/Git은 작성하지 않았다.
- 미소유 텍스트 330개를 archive와 바이트 대조해 차이0을 확인했다. cwd/rootdir/pytest 설정은 사본, PYTHONPATH는 사본 src다. 부모와 실제 multiprocessing spawn 자식에서 recoryn/credentials/gateway/desktop/ai_bridge/ledger/contracts/privacy 8개 import 경로가 사본 아래임을 확인했다.
- 실행 사본의 문서는 동결 C4 원문이다. 이 결과 절은 검증 완료 뒤 추가했으며 비실행 Markdown 후첨을 검증 당시 코드/시험 hash와 구별한다.
- 모든 유효 실행은 -p no:cacheprovider, 고유 OS TEMP --basetemp, QT_QPA_PLATFORM=offscreen, -W error::ResourceWarning, HF_HUB_OFFLINE=1/HF_HUB_DISABLE_TELEMETRY=1을 사용했다. 네트워크/실제 vault/실서비스/계정/모델 추론을 시험 fixture로 대체했다.
- 경로 실수 이력: local-notice-debug53은 PYTHONPATH만 사본이고 cwd/시험 경로가 저장소였다. 72 PASS/2.11초를 격리 증거에서 제외하고 즉시 X00에 보고했다. 같은72개를 사본에서 local-notice-copy54로 다시 실행해72 PASS/1.82초였다. 저장소 실행의 bytecode 가능성을 숨기거나 타 작업 캐시를 지우지 않았다.

### 12.2 구현된 경계와 사실

| 경계 | 실제 구현·관측 |
| --- | --- |
| 요청 carrier·권한 | Gateway.auth_binding과 for_session이 같은 CredentialService/ref/plan을 전달한다. ExecutionContext/adapter에서 raw Authorization/x-api-key/x-goog-api-key를 거부한다. GUI capture_execution은 intent만 만들고 PrivacyBackend.prepare_execution이 worker에서 정책·설정·비용·Gateway를 준비한다. api_key snapshot으로 전송하지 않는다. |
| I/U/R/r | I/U/r은 ledger 소유 preflight와 현재 동의·cancel/deadline/ref/plan을 검사한다. U의 ticket consume은 원자 단회다. R의 실제 vault get은 공용 정책/owner/Job 잠금 밖이다. R 반환 뒤 오류인 경우에도 r 정책 검사를 우선하므로 철회/삭제를 AUTH 없음으로 오분류하지 않는다. |
| O/H/B/F | O에서 현재 catalog/정책/기한을 다시 대조하고 등록1회다. H/B/F의 실제 guard·cancel/ref 검사를 유지하며 먼저 발생한 handoff 뒤 실패는 UNKNOWN/known false를 보존한다. r 성공 뒤 O 진입 전 catalog 교체와 R 중 교체를 구별한다. |
| 비등록 비용 | CostPreflight는 요청 fingerprint/ledger 소유/단축 가능한 monotonic 기한만 가진다. I/U/r에서 quote cache pop/order/deadline/dispatch/DB/witness 쓰기0을 J/K가 직접 관측한다. 기존 direct open/write의 body identity·금액·clock·witness·UNKNOWN 반례를 유지했다. |
| 앱 비밀 참조 | lease·Gateway auth mapping과 stdlib HTTPConnection의 미전송 _buffer를 첫 write 반환/abort/close에서 정리한다. D4의 fake socket/TLS+실제 HTTPConnection subtrace는 putheader 뒤 실패 시 실제 buffer가 비워지는지 본다. Python str·OS/native 복사본 강제 zeroization은 보장하지 않는다. |
| 단회 T00 | 같은 ticket 경쟁2인과 종료 후 replay: 성공 claim1, 패자/replay AUTH_REQUIRED, native read 합1, 추가 lease/송신0. 정상 barrier는 잠금 밖이다. C2-M11만 consume check/commit을 분리해 두 승인이라는 실제 call assertion으로 실패시킨다(후단 claim guard 때문에 native2라고 주장하지 않음). |
| key 수명·FIFO | 명령 접수와 grant_active/pending은 원자 검사다. credential epoch와 provider facts epoch는 별개다. native worker<=4, 미완료 접수<=8, 동일 target<=2이며 target FIFO, 다른 target 진행을 검증했다. fixture는 이 한도를 줄일 수 있고 늘리면 INPUT_INVALID다. 실제 set/delete 중 공용 잠금을 소유하지 않으며 실패해도 epoch를 되돌리지 않는다. |
| GUI·종료 | policy/query 단일 bounded lane과 native key lane을 분리했다. 접수 성공 시에만 key 입력을 즉시 비우고 실패로 복원하지 않는다. generation/nonce/closed 검사로 늦은 callback 적용0이다. GUI는 begin_shutdown만 하고 비GUI await_shutdown이 실제 요청/native/reader와 두 pool ACK를 기다린다. |
| 삭제 T15 승인 범위 | DesktopRecorder.close는 source ACK를 먼저 받은 뒤 get_session의 정확한 StateConflict('Session has a deletion intent')에서 실제 writer/sealer join만 한다. finalize/state 변경0이며 다른 오류와 source ACK 실패는 전파한다. 실제 reader/generation/pending 회귀를 유지했다. |

구현 위치(현재 제출 코드):

| 파일 | 함수 | 줄 |
| --- | --- | ---: |
| src/recoryn/security/credentials.py | CredentialService.consume_ticket | 283 |
| src/recoryn/security/credentials.py | CredentialService.read_claim | 305 |
| src/recoryn/security/credentials.py | CredentialService.try_enqueue_key_change | 393 |
| src/recoryn/security/credentials.py | CredentialService._run_target | 434 |
| src/recoryn/security/credentials.py | CredentialService.await_shutdown | 491 |
| src/recoryn/security/gateway.py | Gateway.for_session | 88 |
| src/recoryn/security/gateway.py | Gateway.request | 194 |
| src/recoryn/security/gateway.py | Gateway._write | 456 |
| src/recoryn/security/ledger.py | CostLedger.preflight_request | 1146 |
| src/recoryn/security/ledger.py | CostLedger.validate_dispatch | 1182 |
| src/recoryn/security/transport.py | _HttpConnection.write | 78 |
| src/recoryn/security/transport.py | _HttpConnection._clear_auth | 93 |
| src/recoryn/ui/privacy.py | PrivacyBackend.commit_action | 392 |
| src/recoryn/ui/privacy.py | PrivacyBackend.prepare_execution | 507 |
| src/recoryn/ui/privacy.py | PrivacyBackend.await_shutdown | 637 |
| src/recoryn/ui/privacy.py | PrivacyPanel.capture_execution | 1439 |
| src/recoryn/ui/privacy.py | PrivacyPanel._on_work_ready | 1517 |
| src/recoryn/ui/privacy.py | PrivacyPanel._action | 1675 |
| src/recoryn/ui/ai_bridge.py | DesktopAI._transcribe | 743 |
| src/recoryn/ui/ai_bridge.py | DesktopAI.summarize | 911 |
| src/recoryn/ui/ai_bridge.py | DesktopAI.close | 1576 |
| src/recoryn/app/desktop.py | DesktopRecorder.close | 361 |
| src/recoryn/providers/contracts.py | ExecutionContext.__post_init__ | 161 |
| src/recoryn/providers/_common.py | Run.request | 182 |

### 12.3 literal 분모·ID·선택 감사

feasible 분모는 C4의781개/17가족 그대로이며 실행782에는 의미 행이 아닌 metadata 감사1만 추가된다. 제품 enum/TEMPLATES/parser로 expected를 만들지 않았다. route5/오류 literal/금액/권한·세대 순서를 손 oracle로 두고 실제 call/도달 stage/DB·witness/표시/Job을 관측했다.

| primary 파일 | 의미 ID |
| --- | ---: |
| tests/unit/test_secret_lifetime.py | 335 |
| tests/integration/test_secret_lifetime.py | 250 |
| tests/property/test_secret_lifetime_case_space.py | 72 |
| tests/ui/test_secret_lifetime_ui.py | 124 |

| family | feasible |
| --- | ---: |
| A | 240 |
| F | 40 |
| T | 20 |
| J | 12 |
| E | 20 |
| X | 11 |
| B | 40 |
| P | 45 |
| Q | 20 |
| K | 50 |
| L | 10 |
| C2 | 36 |
| D | 45 |
| G | 72 |
| V | 88 |
| S | 16 |
| U | 16 |

정렬된781 ID의 LF SHA256: 27898b7d1a8cf5c13360599cc04ede158fa7c4aebea42230d328ef6ec67a978b.actual call에서 ID·primary 소유·중복을 감사한다. 전체4파일 선택이면781 집합을 감사하고 부분 선택이면 실제 선택 ID만 비교한다. 정상 변이 목표63개 부분 선택도 통과했으며 미선택 행을 실행했다고 채우지 않았다.
P/Q는 공개 transcribe/summarize→Run/Gateway→실제 CostLedger와 JobStore/BoundedRunner의 실제 Job/Attempt 상태를 관측한다. Gemini context는 합성 core 결과로 미리 만든 유효 checkpoint를 입력 fixture로만 사용하고 인증·결과 expected를 planner에서 추출하지 않는다. G의 SQLite 관측은 WAL을 놓치지 않도록 실제 iterdump와 물리 파일을 함께 확인한다.

### 12.4 정상·변이 결과와 INVALID 구분

mutation-r8-final32: 정상 목표63 PASS → 서로 다른 archive+32파일 사본의 단일 의미 결함67개 → 목표 call assertion FAIL67, 생존0, INVALID0. 각 case의 결과·trace·변경 전후 SHA256은 TEMP results.json에 보관했다. 수집/import/syntax/ACL/timeout/teardown 실패는 목표 검출로 세지 않았다. 아래 목표는 실제 실행 node이며 다른 후단 거부로 앞선 생략을 가리지 않는다.

| 변이 | 목표 node | 단일 결함 | 실제 call assertion 위치 |
| --- | --- | --- | --- |
| M01 | tests/ui/test_secret_lifetime_ui.py::test_existing_ui_bounds[GS05-U-0-0] | prepare reads vault before a request | tests/ui/test_secret_lifetime_ui.py:487 |
| M02 | tests/unit/test_secret_lifetime.py::test_admission_cube[GS05-A-0-0-0-1-0] | defer initial cancel until a ticket already exists | tests/unit/test_secret_lifetime.py:379 |
| M03 | tests/unit/test_secret_lifetime.py::test_admission_cube[GS05-A-0-1-0-0-0] | read secret before denied consent | tests/unit/test_secret_lifetime.py:377 |
| M04 | tests/unit/test_secret_lifetime.py::test_admission_cube[GS05-A-0-0-1-0-0] | read secret before missing budget | tests/unit/test_secret_lifetime.py:377 |
| M05 | tests/unit/test_secret_lifetime.py::test_admission_cube[GS05-A-0-0-0-0-1] | omit credential epoch equality | tests/unit/test_secret_lifetime.py:368 |
| M06 | tests/integration/test_secret_lifetime.py::test_read_results[GS05-B-0-1] | missing native key uses a fallback | tests/integration/test_secret_lifetime.py:227 |
| M07 | tests/integration/test_secret_lifetime.py::test_read_results[GS05-B-0-2] | accept malformed read through a fallback credential | tests/integration/test_secret_lifetime.py:227 |
| M08 | tests/integration/test_secret_lifetime.py::test_read_results[GS05-B-0-6] | public native error includes backend context | tests/integration/test_secret_lifetime.py:227 |
| M09 | tests/integration/test_secret_lifetime.py::test_read_results[GS05-B-0-7] | skip deadline checks once the native lease returned | tests/integration/test_secret_lifetime.py:227 |
| M10 | tests/integration/test_secret_lifetime.py::test_read_orders_b[GS05-C2-0-4] | remove H permit recheck | tests/integration/test_secret_lifetime.py:744 |
| M11 | tests/integration/test_secret_lifetime.py::test_read_orders_b[GS05-C2-1-1] | omit post-I cancellation checks | tests/integration/test_secret_lifetime.py:741 |
| M12 | tests/unit/test_secret_lifetime.py::test_ticket_once[GS05-T-10] | disable common current reference gate | tests/unit/test_secret_lifetime.py:563 |
| M13 | tests/integration/test_secret_lifetime.py::test_fault_cleanup[GS05-D-0-4] | lower partial handoff to known | tests/integration/test_secret_lifetime.py:861 |
| M14 | tests/integration/test_secret_lifetime.py::test_fault_cleanup[GS05-D-0-4] | remove abort cleanup of app-owned stdlib authentication buffer | tests/integration/test_secret_lifetime.py:890 |
| M15 | tests/unit/test_secret_lifetime.py::test_closed_routes[GS05-X-10] | empty body never hands its header off | tests/unit/test_secret_lifetime.py:1039 |
| M16 | tests/integration/test_secret_lifetime.py::test_fault_cleanup[GS05-D-0-2] | omit owner execution guard | tests/integration/test_secret_lifetime.py:859 |
| M17 | tests/integration/test_secret_lifetime.py::test_key_concurrency[GS05-T-19] | rollback credential epoch on native change failure | tests/integration/test_secret_lifetime.py:1036 |
| M18 | tests/unit/test_secret_lifetime.py::test_binding[GS05-F-0-1] | compare credential destinations by provider only | tests/unit/test_secret_lifetime.py:430 |
| M19 | tests/ui/test_secret_lifetime_ui.py::test_save_admission[GS05-S-2-1] | apply an old selection's key callback | tests/ui/test_secret_lifetime_ui.py:414 |
| M20-02 | tests/unit/test_secret_lifetime.py::test_binding[GS05-F-0-2] | trust a frozen carrier over one changed request scope field | tests/unit/test_secret_lifetime.py:428 |
| M20-03 | tests/unit/test_secret_lifetime.py::test_binding[GS05-F-0-3] | trust a frozen carrier over one changed request scope field | tests/unit/test_secret_lifetime.py:428 |
| M20-04 | tests/unit/test_secret_lifetime.py::test_binding[GS05-F-0-4] | trust a frozen carrier over one changed request scope field | tests/unit/test_secret_lifetime.py:428 |
| M20-05 | tests/unit/test_secret_lifetime.py::test_binding[GS05-F-0-5] | trust a frozen carrier over one changed request scope field | tests/unit/test_secret_lifetime.py:428 |
| M20-06 | tests/unit/test_secret_lifetime.py::test_binding[GS05-F-0-6] | omit credential execution binding | tests/unit/test_secret_lifetime.py:428 |
| M21 | tests/property/test_secret_lifetime_case_space.py::test_output_space[GS05-G-1-0] | public plan serialization carries an authentication field | tests/property/test_secret_lifetime_case_space.py:252 |
| M22-03 | tests/property/test_secret_lifetime_case_space.py::test_output_space[GS05-G-3-0] | raw credential leaks into output sink 3 | tests/property/test_secret_lifetime_case_space.py:401 |
| M22-04 | tests/property/test_secret_lifetime_case_space.py::test_output_space[GS05-G-4-0] | raw credential leaks into output sink 4 | tests/property/test_secret_lifetime_case_space.py:401 |
| M22-05 | tests/property/test_secret_lifetime_case_space.py::test_output_space[GS05-G-5-0] | raw credential leaks into output sink 5 | tests/property/test_secret_lifetime_case_space.py:401 |
| M22-06 | tests/property/test_secret_lifetime_case_space.py::test_output_space[GS05-G-6-0] | raw credential leaks into output sink 6 | tests/property/test_secret_lifetime_case_space.py:337 |
| M22-07 | tests/property/test_secret_lifetime_case_space.py::test_output_space[GS05-G-7-0] | raw credential leaks into output sink 7 | tests/property/test_secret_lifetime_case_space.py:357 |
| M22-08 | tests/property/test_secret_lifetime_case_space.py::test_output_space[GS05-G-8-0] | raw credential leaks into output sink 8 | tests/property/test_secret_lifetime_case_space.py:401 |
| M22-09 | tests/property/test_secret_lifetime_case_space.py::test_output_space[GS05-G-9-0] | raw credential leaks into output sink 9 | tests/property/test_secret_lifetime_case_space.py:378 |
| M22-10 | tests/property/test_secret_lifetime_case_space.py::test_output_space[GS05-G-10-0] | raw credential leaks into output sink 10 | tests/property/test_secret_lifetime_case_space.py:393 |
| M22-11 | tests/property/test_secret_lifetime_case_space.py::test_output_space[GS05-G-11-0] | raw credential leaks into output sink 11 | tests/property/test_secret_lifetime_case_space.py:397 |
| M23 | tests/ui/test_secret_lifetime_ui.py::test_existing_ui_bounds[GS05-U-2-0] | native key change runs on GUI | tests/ui/test_secret_lifetime_ui.py:513 |
| M24-00 | tests/unit/test_secret_lifetime.py::test_closed_routes[GS05-X-00] | local path unnecessarily reads credentials | tests/unit/test_secret_lifetime.py:951 |
| M24-01 | tests/unit/test_secret_lifetime.py::test_closed_routes[GS05-X-01] | local path unnecessarily reads credentials | tests/unit/test_secret_lifetime.py:951 |
| M24-02 | tests/unit/test_secret_lifetime.py::test_closed_routes[GS05-X-02] | silently ignore a cloud auth binding on local request | tests/unit/test_secret_lifetime.py:979 |
| M24-03 | tests/unit/test_secret_lifetime.py::test_closed_routes[GS05-X-03] | unsupported provider accepted | tests/unit/test_secret_lifetime.py:983 |
| M24-04 | tests/unit/test_secret_lifetime.py::test_closed_routes[GS05-X-04] | missing cloud binding falls back to implicit credentials (fake-only) | tests/unit/test_secret_lifetime.py:988 |
| M24-05 | tests/unit/test_secret_lifetime.py::test_closed_routes[GS05-X-05] | raw auth context construction accepted | tests/unit/test_secret_lifetime.py:992 |
| M24-06 | tests/unit/test_secret_lifetime.py::test_closed_routes[GS05-X-06] | adapter auth accepted by Run before downstream guard | tests/unit/test_secret_lifetime.py:998 |
| M25 | tests/unit/test_secret_lifetime.py::test_closed_routes[GS05-X-07] | cache first native secret in Run/context for subsequent requests | tests/unit/test_secret_lifetime.py:1027 |
| M26 | tests/unit/test_secret_lifetime.py::test_closed_routes[GS05-X-09] | automatically retry an UNKNOWN handoff once | tests/unit/test_secret_lifetime.py:1042 |
| C2-M01 | tests/integration/test_secret_lifetime.py::test_first_write_release[GS05-L-0-0] | delay first-write cleanup to final request exit | tests/integration/test_secret_lifetime.py:646 |
| C2-M02 | tests/integration/test_secret_lifetime.py::test_auth_pipeline[GS05-P-0-4] | publish raw invalid credential error | tests/integration/test_secret_lifetime.py:448 |
| C2-M03 | tests/integration/test_secret_lifetime.py::test_auth_pipeline[GS05-P-0-1] | known AUTH becomes UNKNOWN in Run | tests/integration/test_secret_lifetime.py:448 |
| C2-M04 | tests/integration/test_secret_lifetime.py::test_post_handoff[GS05-Q-0-0-0] | post-H auth-shaped fault becomes known AUTH | tests/integration/test_secret_lifetime.py:515 |
| C2-M05 | tests/ui/test_secret_lifetime_ui.py::test_all_security_entries[GS05-V-2-0-0-0] | GUI refresh directly queries policy | tests/ui/test_secret_lifetime_ui.py:303 |
| C2-M06 | tests/ui/test_secret_lifetime_ui.py::test_all_security_entries[GS05-V-7-0-0-0] | GUI cost policy directly queries ledger | tests/ui/test_secret_lifetime_ui.py:303 |
| C2-M07 | tests/ui/test_secret_lifetime_ui.py::test_all_security_entries[GS05-V-0-0-0-0] | GUI grant directly enters policy | tests/ui/test_secret_lifetime_ui.py:303 |
| C2-M08 | tests/ui/test_secret_lifetime_ui.py::test_save_admission[GS05-S-2-0] | restore accepted key text after native failure | tests/ui/test_secret_lifetime_ui.py:409 |
| C2-M09 | tests/ui/test_secret_lifetime_ui.py::test_save_admission[GS05-S-0-0] | erase input on enqueue rejection | tests/ui/test_secret_lifetime_ui.py:386 |
| C2-M10 | tests/integration/test_secret_lifetime.py::test_auth_pipeline[GS05-P-0-0] | clone loses frozen auth binding | tests/integration/test_secret_lifetime.py:463 |
| C2-M11 | tests/unit/test_secret_lifetime.py::test_ticket_once[GS05-T-00] | split atomic check/commit; uncommitted seam outside all locks | tests/unit/test_secret_lifetime.py:516 |
| C2-M12 | tests/unit/test_secret_lifetime.py::test_ticket_once[GS05-T-04] | ticket accepts another request/body/reservation scope | tests/unit/test_secret_lifetime.py:563 |
| C2-M13 | tests/integration/test_secret_lifetime.py::test_read_orders_b[GS05-C2-0-3] | native R holds policy coordinator | tests/integration/test_secret_lifetime.py:736 |
| C2-M14 | tests/integration/test_secret_lifetime.py::test_read_orders_b[GS05-C2-0-3] | skip r authority gate and offer invalid lease to O | tests/integration/test_secret_lifetime.py:753 |
| C2-M15 | tests/integration/test_secret_lifetime.py::test_key_concurrency[GS05-T-18] | native set/delete holds policy coordinator | tests/integration/test_secret_lifetime.py:985 |
| C2-M16 | tests/ui/test_secret_lifetime_ui.py::test_control_during_read[GS05-T-17] | pending target invisible to grant and request admission | tests/ui/test_secret_lifetime_ui.py:560 |
| C2-M17 | tests/integration/test_secret_lifetime.py::test_key_concurrency[GS05-T-18] | same-target queue loses FIFO | tests/integration/test_secret_lifetime.py:1028 |
| C4-M01 | tests/integration/test_secret_lifetime.py::test_catalog_gate_orders[GS05-K-0-0-1] | preflight omits current catalog comparison | tests/integration/test_secret_lifetime.py:593 |
| C4-M02 | tests/integration/test_secret_lifetime.py::test_catalog_gate_orders[GS05-K-0-3-1] | O omits catalog comparison after r succeeded | tests/integration/test_secret_lifetime.py:585 |
| C4-M03 | tests/unit/test_secret_lifetime.py::test_nonregistering_preflight[GS05-J-0-0-0] | preflight consumes quote cache | tests/unit/test_secret_lifetime.py:666 |
| C4-M04 | tests/unit/test_secret_lifetime.py::test_nonregistering_preflight[GS05-J-0-0-0] | preflight writes a dispatch registration | tests/unit/test_secret_lifetime.py:676 |
| C4-M05 | tests/integration/test_secret_lifetime.py::test_catalog_gate_orders[GS05-K-0-1-1] | U omits nonregistering cost preflight | tests/integration/test_secret_lifetime.py:593 |
| C4-M06 | tests/integration/test_secret_lifetime.py::test_catalog_gate_orders[GS05-K-0-2-1] | r omits cost preflight; O later rejection is insufficient | tests/integration/test_secret_lifetime.py:595 |

변이 재현 artifact SHA256(수정 전후 각 파일 LF hash는 results.json의 changes 행):

- gs05-mutations.py: 092138dfcb0a9e2e8a5d307de0cd79c8d45d33eaee420a92ac91fb535c624deb
- mutation-r8-final32/results.json: 1a7b22bd6e112b897b62036b754795facec7be4556322ea03f2bc30b51067b25
- mutation-r8-final32/baseline.json: 6c577ae628e6b58af54b5c0026f0de09ce9f6ef8cc6f26e6a317ca9f7579fa10

C4-M02는 r 성공/잠금 해제 뒤 O 전 교체에서만 O 대조 생략을 검출한다. C4-M06은 r 생략 시 O가 뒤늦게 거부하더라도 r 다음 단계 진입0 단언으로 실패한다. C2-M13/15의 native 잠금 결함은 실제 native 진입 때 기록한 잠금 깊이를 main assertion에서 비교하므로 timeout을 kill로 세지 않는다.
이력: 최초 변이 분류기는 pytest XML의 생략된 type 필드를 잘못 처리했고, G sink3/4/5는 WAL 내용을 놓쳐 생존했다. 분류/관측을 수정한 뒤 현재 전체67을 다시 실행했다. 최초 결과를 현재 kill로 합산하지 않았다.

### 12.5 60초 예산과 fixture 근거

최종 new781-final83: 782 PASS, XML suite 55.656초, fixture 준비 포함 독립 wall **57.094541초**. 코드 hash는 아래와 같고 최종 constructor 한도/T18 추가 probe를 포함한다.
초과 기록도 남긴다: stdlib D4/public P/Q 포함 단계 wall68.6899583초, integration 빈 store 복사만 적용한 단계61.6402358초로 게이트 실패였다. 파일/가족별 시간을 X00에 보고하고 승인된 범위 안에서 UI/property에도 같은 fixture 개선을 적용했다. 후속53.7807668초/39.7971797초/44.0478551초는 중간 측정이며 위 최종 측정과 구분한다. 외부 부하가 원인이라고 단정하지 않았다.
템플릿은 실제 빈 ConsentStore/CostLedger를 초기화한 뒤 닫은 DB·witness bytes뿐이다. grants0/reservations0/WAL 없음과 매 행 새로운 execution ID를 단언한다. 각 행은 새 물리 파일로 복사하고 실제 store를 다시 열며 활성 동의·예약·권한·connection·lock·sidecar·worker를 공유하지 않는다. 실제 행별 정책/금전 I/O와 native 경쟁은 계속 실행한다.

### 12.6 기존 회귀·CI·coverage·wheel

기존18시험의 수정은 API 준비/worker 완료/실제 종료·fake carrier 이행이다. G06 direct O/write 금액·body/scope·clock/witness/UNKNOWN, G12 real keyboard/default No/confirm, G16 static 및 prepared provider 2차 gate, owner/reader ACK, GS04a memory facts·정확300초/실제 timer 표시 oracle를 보존했다.
실패 이력: core-ci52는29617 PASS/4 FAIL(2041.91초)였다. BR24의 carrier 없음은 X00 32번째 파일 승인 후 합성 AuthBinding만 주입했고 marker→open/실패open0/예약·UNKNOWN·Job 단언은 유지했다. G06의 닫기만 한 panel이 남긴 privacy/key worker75개는 소유 fixture 두 pool ACK로 회수했다. test_seal_mutex의 두 원 단언은 수정하지 않았다. GS04-L003은 단독72행·관련138행에서는 PASS였으나 전단 UI2684행 순서에서 두 차례2683 PASS/1 FAIL로 재현됐다. 계측상 clock1300/stamp1000, 활성10ms timer, 신호차단False였고 qWait(5) 한 번이1.4636904초 소요되어 timer remaining10→0인데 다음 timer tick 전에 poll deadline이 끝났다. qWait 직후 실제 app.processEvents 1회를 추가해 due callback을 처리한다. 정확300초·실제 timer·1초 poll deadline·표시 oracle를 유지했다. widget별 재귀 순회에서 활성 timer61회 관측했으나 고유 timer 개수/제품 누수 증거로 사용하지 않는다. old hash의 core-ci58은16%에서 중단한 INCOMPLETE이며 PASS로 세지 않는다. 새 hash에서 전단 UI2684 PASS/127.29초, 같은 qWait1.2337598초/remaining0 조건에서 추가 실제 event turn으로 target tick17→18과 원 만료 표시를 확인했다. 별도 GS04-L01은 timer.start만 제거한 사본에서 기존 만료 표시 call assertion FAIL(오류/timeout0)을 확인했다.
이전 G11 fake Gateway 주입 root가 옛 panel._gateway에 남아 DNS 경로를 시도한 두 fixture는 integration socket/DNS 차단 fixture가 실제 OS 호출 전에 거부했고 실패 처리됐다. backend.gateway로 주입 위치만 옮긴 뒤 재검증했다. 실제 네트워크 성공으로 계산하지 않는다.
CI66 첫 구간의 F1은 수집169번 owner success-shutdown 후보였다(중단 전 최종 trace 미집계). 단독6/모듈36/전단173은 PASS였으나 정책 worker만0.3초 지연한 고정 사본에서 test_ai_independent.py:1026의 durable policy.allowed 단언이 실제 ACK 전에 assert not True로 실패했다. frozen.request 즉시 거부·delivered0은 ACK 전에 유지하고, 그 뒤 settle_privacy로 실제 policy ACK를 기다린 다음 원 durable 동의 단언을 수행하도록 X00 확인 범위에서 이행했다. 초기 재현의 이름 재사용/동시 경로 충돌 실행은 제외하고 고유 owner-before-ack75.xml에 원 assertion FAIL, owner-after-ack76.xml에 같은 지연의 PASS를 각각 보존했다. CI66은10%에서 본인 시험만 중단한 INCOMPLETE다.
CI78은 끝까지 실행해29620 PASS/1 FAIL,2103.19초로 종료했다. 유일한 실패는 test_egress_independent.py:228의 model 변경 직후 durable allowed 조회였다. 정책 worker만0.3초 지연한 egress-before-ack81.xml에서는 같은 패턴의 :204/228 원 단언 두 곳이 FAIL/오류0이었다. X00 확인 후 두 조회 앞에 settle_privacy만 추가했고 같은 지연의 egress-after-ack82.xml은2 PASS다. 설정 key·옛 계획 거부·재동의·key/wire 기대값은 보존했다. 기존 소유 시험 direct allowed 호출17곳/3파일의 읽기 감사도 남겼으며 다른 완료 가정 변경0이다.

- 최종 core-ci84: **29621 PASS**, XML suite 시간 2140.752초. core.yml의 pytest/cache/ResourceWarning/branch coverage85 flags 그대로, 추가로 고유 TEMP/XML만 사용했다. 전체 회귀 안의 desktop independent/desktop UI/pending deletion UI/원 seal worker 검사도 통과했다.
- ruff check src tests scripts packaging PASS; ruff format --check 동일 범위229파일 PASS; mypy src/recoryn scripts packaging 97 source files PASS.
- optional-runtime과 같은 시험 선택: 504 PASS/XML suite 36.616초. 기존 설치 환경만 사용했으며 설치 단계는 실행하지 않았다. packaging/entry_cli.py --release-smoke PASS: 합성 PCM/분리 원본/production spawn 시작·종료, 모델 추론0·장치 캡처0이다. native traffic 전체를 관측했다고 주장하지 않는다.

| coverage 묶음 | line / 기준 | branch / 기준 |
| --- | --- | --- |
| domain | 99.18% / 95% PASS | 97.89% / 90% PASS |
| capture | 99.73% / 95% PASS | 98.29% / 90% PASS |
| jobs | 99.20% / 95% PASS | 95.65% / 90% PASS |
| storage | 96.21% / 95% PASS | 91.55% / 90% PASS |
| security | 97.35% / 95% PASS | 92.75% / 90% PASS |
| content | 98.98% / 95% PASS | 99.02% / 90% PASS |
| all | 94.16% / 85% PASS | 88.55% / 80% PASS |

offline wheel: recoryn-0.2.0.dev2-py3-none-any.whl, SHA256 1d1c01f0cabb38b3922451445a9f85758667c2c792ed6494d50135e37fa2acd1. pip wheel --no-deps --no-build-isolation --no-index 사용(네트워크/설치0), 배정 제품9개가 wheel 안에서 제출 소스와 hash 일치함을 확인했다.

### 12.7 제출 파일 LF SHA256

아래31개 코드/시험 hash는 최종 CI·변이·wheel 대상과 일치한다. 문서 자체는 자기 hash 순환을 피하려고 표에서 제외하며, 고정 C4 prefix hash는12.1에 기록하고 최종 문서 LF hash/32파일 manifest는 별도 완료 보고에 남긴다.

| 파일 | LF SHA256 |
| --- | --- |
| src/recoryn/security/credentials.py | fd3940bb0ce6db3ed1b6091e9d447825e6630eb3410bef20f64203f3790d1223 |
| src/recoryn/security/gateway.py | 577baf42c5e141a5790f710423ca782e74a542278c8499e05f70390a3a24bf4b |
| src/recoryn/security/transport.py | 063369f2768d7a4d753f0baf51603d222ca2aacfc04f8c3a1b6963496512b66d |
| src/recoryn/providers/contracts.py | 37227ee30a6f43572c43123c1c90926630a9e3aada2c558a2922c9bc4ae2d6c1 |
| src/recoryn/providers/_common.py | 346470bdea1d13b15faac13410afeb920f28fd8426c07cc1977036cc16c5e4c2 |
| src/recoryn/ui/privacy.py | 186e3cf71c84031a35c959224dc5e0d162b2a6ab0b1c8a5b0c0ae5eae3e07e02 |
| src/recoryn/ui/ai_bridge.py | 23fc136fef77fc75c7aaaf92687645eb30c18804ec2276a7133f916edb82aa6a |
| src/recoryn/security/ledger.py | 5ada45d25107e835b5ba83e60c94a6c5cad89dc0b8006ff306ba491b0689f53d |
| tests/ui/test_privacy_ui.py | e6a1021bebe85d41d51a701b063889b75dd2a00cbc5bda454eeeda4a33ad6b73 |
| tests/ui/test_consent_scope_ui.py | 17c4923280f06c04475cf1e4699243ebd1348fc1c078cbaa8e8c0e0a6bec781f |
| tests/ui/test_cost_cap_ui.py | 2a78275673d9b822d52d985a7cc75b0743117b3acea691084ccdcf8916df4799 |
| tests/integration/test_cost_cap.py | 09f5bb1a4712e3f09389fa15b4890d4014936b73fbdb4a13ad39e86253ac1532 |
| tests/integration/test_egress_independent.py | 548e3dc20b3a155e1ed10426267bf76d9dc79d24a0aeab734521fa45c2345bce |
| tests/unit/test_providers.py | abd1bfa0075dcb87bf39f1ff3773b2018ab303fdf7bfd767f26e0fc1f7db35e2 |
| tests/contract/test_provider_contracts.py | feff99a3d21f8596805b4a5c6205f1bbeb49ed5b5bbb3136f30532f6e3e93474 |
| tests/integration/test_provider_security_independent.py | cb808e4ddb8b7d84bf3ccc921abb38c37f34efa922c199157f8aa8d3e29198d2 |
| tests/ui/test_local_server_notice_ui.py | db02c618c669bf40ffeb03587133105c1a5e21aec04c44dc3b65991438125f64 |
| tests/integration/test_ai_independent.py | 6c07dfb011eafeacca98adb71b8b19ba7cd06c8693bc27841a44740cf0ff1173 |
| tests/integration/test_resource_policy.py | f13e6c085c080d3f4a72d2b29da1929bda5a9e4e9840f52620955934073e1f93 |
| tests/ui/test_blocked_reason_ui.py | 0658fddbc4a4fb3f8949f543127ca2e7590420e0d8d432047feb32e551f456ee |
| tests/ui/test_provider_facts_ui.py | 931b35d19b21ed48b868d6d83590c5431b93d8848935ab838473c1e05abf5791 |
| tests/ui/test_resource_policy_ui.py | e9d57ecfcc92ab8533b704952d6f68f4bd514ca9c943371a84951ae4171bc4ce |
| tests/ui/test_device_policy_ui.py | b30016cf76c60222128e46a851e85aac31736850f10c635e420b9377bbac76cc |
| tests/ui/test_manual_model_ui.py | 8ff6f33ca86f8c4c2e1d080edb9724ad5739614eb3e1feb6e65c5ced7aad4a7b |
| tests/ui/test_basis_a11y_ui.py | 50942234bc0a22c17d554680f13443e2504789517df4c97a55c19b94c82ef9f1 |
| tests/unit/test_secret_lifetime.py | 24245ed43d019fc288a3118c3a12609fb5f288a2cdcdccdf0567b624d0d1d227 |
| tests/integration/test_secret_lifetime.py | 6c0fff2238bdcb18b486d9cb08ecf92bef281f9a1e6feea8a5e53e17919a582a |
| tests/ui/test_secret_lifetime_ui.py | f7bb9392e451014bea1f626da53cf4ffec21356457bac3f7bd71192d9f771822 |
| tests/property/test_secret_lifetime_case_space.py | 6427ff7c8fb0ee3605e5cc95108e473bd28182ba0a73c47664fcfad8a4d4af9f |
| src/recoryn/app/desktop.py | 360b5e4504dd5e98a4eba4a9fa7a66c045b29636f71077014347d06ee0d43c80 |
| tests/integration/test_publication_independent.py | a49e4d7b6300ebddedd4fc26c4a7096b7b98f56a0ac56a028bdd6127b4ca0e51 |

### 12.8 인계·미검증·X00 결정

- 상태 GS-P05 IMPLEMENTATION_READY 제안, pB 독립 검토 대기. 이 작성 결과는 자체 최종 승인이 아니다. X00만 배정표/공용 계약/통합 commit/push/원격 최종 승인을 수행한다.
- 로컬 Python3.13.1만 검증했다. Python3.11 및 원격 CI matrix/optional 설치 재현은 X00 외부 게이트다. 위 optional fixture PASS를 새 원격 optional-runtime job PASS로 바꾸지 않는다.
- GS11a dirty를 통합 구현/검증으로 세지 않았다. GS11 최종 정확 tree/hash를 인수한 뒤 control/deletion/reader ACK·staged 실패 폐쇄를 별도 재검증해야 한다. 기존 baseline의 seal_mutex 시험 통과가 미통합 GS11 승인이라는 뜻은 아니다.
- 실제 Windows Credential Manager/native 강제 중단·외부 키 변경·실계정/서비스 인증·실네트워크/모델/유료 호출·실음성/장치/품질·OS/Python 전체 zeroization은 NOT_RUN. fake/loopback fixture만으로 실제 서비스 readiness를 승인하지 않는다.
- GS04b provider_metadata의 송신 API/route/계정은 만들지 않았다. G16 자원 사실/정책은 다른 축이며 기존 거부 의미를 보존했다.
- X00 결정 요청: 독립 검토 수락 여부, 정확 GS11 최종 tree 재검증 배정, Python3.11/원격 matrix 및 실제 서비스 외부 게이트. 추가 공용 API/파일 변경은 별도 배정을 받는다.

## 13. X00 최종 통합 인수 — 공개 d127019 기준

이전 계약·구현 결과 LF `a02350987db3132422bd3fb9065ee4062e6147964e99b01dba5bae8626a9c79b` 전체를 prefix로 보존한다. 앞의 이전 기준·원32·미통합 GS11 표기는 당시 이력이다. 현재 기준은 복구 공개 `d1270191382363cc6486d9ccac02e187ce18f661`, 실효32 LF `871417e86f2e20d32e90d9946baac72980ecd0cdafd784a4ff919ee2ba30e857`, 전체 검사 입력435파일 LF `ea63f57655cbd0b0233611319436bb1af27793fd665c909854ca54238f3a72c3`다.

### 13.1 정확 입력과 기존 계약 보존

- 실효32는 제품9·시험22·이 계약1이다. 검사한 제품·시험31파일을 그대로 통합한다. a11y는 원32의50942234 대신 앞서 독립 검토한 병합본 `11f16d0c847ea1064c0c29a0ecdd426f11066b1998964612385cda30336ee7a5`다. 기존215단언과 GS11 정상 준비의 공개 fresh/정확 READY 단언1을 보존한다. X00은 작성자 완료 뒤 공유 파일의 기존 hash를 확인하고 이 검사한 병합본만 동기화했다.
- L003은 실제 worker ACK·timer·300초·1초 poll과 qWait 뒤 실제 event turn을 유지한다. 원 payload·삭제 intent·Job attempt/fence·비용/credential 기한과 손 oracle·781행/17family·감사1을 바꾸지 않았다.
- 복구3은 BASE에 포함되어 있으며 실효32와 경로 교집합0이다. Library9f1e625c·unfinished9c9747d5·publication dad7를 덮지 않았다. archive 비overlay403파일은 raw bytes 동일하다. G09 계획/초안과 다른 미공개 파일은 GS05 통합에 포함하지 않는다.

### 13.2 최종 로컬 증거

| 검사 | 동일 입력의 결과 |
| --- | --- |
| 신규782 단독 | 782 PASS, 준비 포함 process40.986823초/60초 |
| 교차/권위/출판 | 1672 / AUTH14 / publication386 PASS |
| G15/기존 성능·capture | 102+7=109 PASS, 원본·실제 source/reader ACK·root0.5초 단언 보존 |
| 선정 집합 | 중복을 제외한2918 ID, 전체 수집에 포함 |
| 전체 core | 30145 PASS, 실패·오류·skip0, 수집 ID와 XML 각1회·제거0 |
| 전체 시간 | process2286.523983초 |
| 변이 | GS05 정상63→단일67 목표 call assertion FAIL, 복구 정상14→단일10 목표 FAIL, L01 정상→timer 시작 제거→원 만료표시 단언 FAIL |
| 변이 유효성 | 변이 INVALID/생존0. 최초 시험전 AUTH launcher INVALID1은 별도 보존 |
| 정적/coverage/wheel | Ruff·format·mypy, 원 core.yml flag의 coverage85 및 check_coverage7, offline wheel PASS |

coverage의 combined 지표는92.7015%이며 line/branch 예산과 구분한다. 전체 line94.10%/branch88.48%, security97.35%/92.75%, storage95.20%/90.16%로 각 묶음 예산을 통과했다. Wheel SHA-256 `b3d48773c151579746e97632be577e327e507b786d52a4231f6b343bee8e3d9c`의 package Python86개 및 모든 package member bytes가 검사 사본과 같다. 부모와 실제spawn15모듈, pytest cwd/rootdir/config/PYTHONPATH는 같은 사본이다.

최초 AUTH launcher는 로그를 중복 소유하여 제품/수집/call 전에 실패했다. 원 auth14.log/process는 유지하고 외부 auth14-r2에서 child auth14로 직접 연결했다. 시험·기대값·copied helper 변경0이며 정상14를 확인한 뒤 의존 변이를 실행했다. 실행 중 선행 복구 CI 세 작업 성공을 확인했을 때 같은 BASE/입력을 재시작 없이 최종 검증으로 인수했다.

### 13.3 독립성·통합·미검증

작성자 최종 보고 `build/gs05-d127-preview/report.md` LF `8f7d5909c12dde001e2f5ffc5cf2e5f5a3aeba50d4b9eff942692b091662411f`, evidence LF `58b618af360d3c95faf70b77169fcaf63f7e4c96f1d79151499a73a01465519e`를 X00이 실제 XML·수집·변이·제품/wheel bytes와 대조했다. root 인수는 `build/gs05-d127-integration/final-acceptance.json`에 있다.

기존 GS05 R1/R2와 별도로 pB의 d127 교차 독립 검토 report LF `a60d09ec863ec92b564eef10d3255b689aa19fca1ace6af6a8ed42120c7e341a`, evidence LF `94e0e228855dd4607ec596b1730112dae1d296fd018c5b69f259613b4c847a5e`는 제품 OPEN0이다. 독립435 입력 일치, 실제 선택30/API3 PASS·단일부정2 목표 FAIL/INVALID0을 확인했다. 이 제한된 독립 실행을 전체30145 실행으로 합산하지 않는다.

선행 복구 [CI45845073225](https://github.com/gangdonggilstudy/Recoryn/actions/runs/45845073225)의 core3.11·core3.13·optional-runtime은 모두 실제 success다. 이는 d127 기준의 선행 게이트이며 GS05 통합판 자체의 원격 성공은 아니다. 정확 통합 후보는 실효32와 이 결과 덧붙임, 공식 리뷰, GS05 배정만의 assignments 총34파일이다. 최종 문서·후보의 독립 대조, 정확 tree·부모/ref·실제 전체 commit 메시지/trailer0, 정상 push와 GS05 원격 CI를 별도 확인한다. 실제 Windows vault/서비스 인증·실장비·실음성·모델·유료 호출·메모리 완전 소거·전원 장애는 미검증이다.


## 14. CI864: 저장 시험의 native idle과 GUI reply 완료 구분

이 절은 앞의 계약·결과 bytes를 보존하는 덧붙임이다. 기준은 공개 `864e238961dc00807114d3dd6ce14f2e2eb5ee79`이며 원격 [CI45914988082](https://github.com/gangdonggilstudy/Recoryn/actions/runs/45914988082)의 core3.11은 `test_save_admission[GS05-S-2-0]`에서 1 FAIL/30,165 PASS였다. 기대는 VAULT_WRITE_FAILED, 관측은 키 변경 접수됨·실제 완료 확인 중이었다. 같은 HEAD의 core3.13과 optional-runtime은 성공했다. 이전 GS05·S1·규범 검증 결과와 이 새 실패를 구분한다.

### 14.1 기존 의미와 수정 범위

CredentialService는 실제 native 작업 뒤 queue/pending을 내리고 나서 KeyResult callback을 호출한다. idle과 backend.idle은 해당 key reply가 Qt GUI slot에 전달·소비됐다는 확인이 아니다. 기존 spin/settle이 idle과 view_pending을 확인해도 아직 emit하지 않은 key reply를 보장하지 않는다.

수정은 `test_save_admission` 한 함수뿐이다. save 접수 직후 원 command nonce·selection generation을 캡처하고, 접수 성공 outcome에서만 callbacks 중 kind=stt/tag=key/같은 nonce·generation인 reply를 기존 bounded spin으로 기다린다. 그 뒤 원 settle과 모든 단언을 그대로 수행한다. 접수 거부 outcome0은 ACK를 기다리지 않는다. view1/2/3의 이전 reply 수신과 선택 변경·refresh·close 뒤 화면 반영 거부는 별도다.

제품·공통 helper·timeout·sleep·정확 오류 문구·원16 tuple/ID·즉시 비밀 지움·native 비차단·pending·stale 거부·비밀 비노출을 변경하지 않는다. 모든 기존 Assert AST와 다른 top-level AST는 동일하다. GS05 의미781/기존 감사1 및 전체 선언 분모는 유지하며 새로운 formal ID·고유 fault를 추가하지 않는다.

### 14.2 직접 검증과 반례

작성자 p8은 원 archive864+시험 한 파일 후보의 사본에서 계측 없는 모듈124행+기존 감사1, 총125 PASS/오류·skip0을 확인했다. command14.196381초이며 60초 이하다. 원781 primary 수집 누락·중복0, 기존 ID와 실행을 대조했다. Ruff check/format은 통과했다.

그 전 조사에서는 로컬3.13 원S16이 자연 실패 없이 통과했다. 실제 native 오류 후 emit 직전만 event로 유보하면 idle=True이고 GUI 문구가 pending인 상태에서 원412행 표시 assertion이 실패했다. 같은 실제 KeyResult/slot을 진행시키면 VAULT_WRITE_FAILED가 표시됐다. preview의 S16과 같은 barrier target은 통과했다. 조사34선택은17.785297초이고 목표 실패와 teardown error0을 분리했다.

수정 비작성자 pB는 자기 사건 순서를 고정한 별도 event/barrier로 원S16 정상16·수정 target1 PASS, original target의 원표시 assertion FAIL1, 추가 ACK 한site만 비활성화한 target assertion FAIL1을 확인했다. 직접19선택/17.887189초, error·skip·MASKED·INVALID0이다. 동일 반례·같은 ACK site의 재확인을 고유 fault 여러 개로 더하지 않는다. 실행 출처·부모/실제 spawn·정확 source·동일 KeyResult와 실제 GUI slot을 확인했고 원제품/다른시험은 byte 그대로다.

시험 파일까지 확장한 임의 mypy 선택은 원본에도 있던 오류5건으로 실패했고 동일 메시지/새 오류0을 보존한다. 이는 PASS가 아니다. 저장소 CI의 mypy 대상은 src/recoryn·scripts·packaging이며 해당 실제 gate 및 정확 통합 tree를 별도로 확인한다. 최초 EOL/경로/후처리 가정 오류는 원 로그와 함께 인프라·정적 실패로 보존하고 목표 assertion 검출과 구분한다.

### 14.3 결론의 범위와 공개 게이트

관측된 시험 완료 대기의 공백을 보강한 것이며 원격3.11 당시 상세 스케줄은 미확정이다. 로컬 결정적 반례가 그 당시 사건 순서를 직접 증명하지 않는다. 실제 로컬3.11·실vault·실장비·음성·모델·유료 호출·전원 장애는 미검증이다. 제품 source의 새 full/coverage/wheel 성공을 이 시험 수정의 결과로 발명하지 않는다.

X00의 정확 파일/tree·독립 검토·실제 commit 전체 메시지/trailer0·원격 ref 확인 및 복구판 원격3.11/3.13/optional 전체 CI 성공은 별도 게이트다. 현재 실패와 관련한 복구 단위 외 후속 G09 기능 공개는 복구 원격 성공 전까지 보류한다. private API/codec 후보는 이 단위에 포함하지 않는다.

X00는 위 동일 시험 blob와 복구 문서4파일의 별도 archive864 사본에서 실제 CI 대상 Ruff check/format 및 mypy src/recoryn·scripts·packaging을 실행해 모두 통과했다. 근거는 `build/ci864-exact4-static/result.json`이다. source·비소유 파일 raw 불변이며, 이후 문서 상태 전사의 차이는 runtime source·시험과 분리해 최종 tree에서 대조한다. 기존 시험 mypy 오류5는 숨기지 않고 추가 범위로 확장하지 않는다. 이 결과는 새 로컬 full/coverage/wheel 또는 복구 원격 성공이 아니다.
