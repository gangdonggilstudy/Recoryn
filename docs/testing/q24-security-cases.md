# Q24 보안·예산 경우의 수 설계 및 증거

2026-11-15. Q24 작성 / 독립 검토 Q22 / push Q-P03. 기준 제품 `30703feeb8b109dcfbf5093df58c964076e43ae9`. **REVIEW_READY — 유한 198/198 유일 행 PASS, 새 pytest 200개/관련 350개 PASS, 격리 핵심 mutant 2개 assertion 검출. Q22 독립 검토 대기.** 제품·기존 시험·공용 설정·Git은 읽기 전용이다. 새 작성은 이 문서와 `tests/property/test_security_case_space.py`뿐이다. Q-P01 정책 리뷰는 별도 `docs/reviews/q-policy-review.md`로 먼저 제출했다. 아래 분모 설계를 먼저 기록한 뒤 실행했으며 실제 결과는 후단에 구분한다.

## 위험·범위·기존 대응

R02/U06/I07: 잘못된 scope/재허용/철회/owner가 전송을 되살리지 않아야 한다. U08/I06: 첫 write 전 실패는 RESERVED/known을 유지하고 handoff 뒤는 UNKNOWN exposure를 보존해야 한다. 유한 대표 공간의 분모와 실제 실행 ID를 대조한다. 실제 음성·모델·daemon·vault·네트워크는 사용하지 않는다. SQLite와 비용 witness는 고유 임시 저장소만 사용하며 transport/시각/owner는 fake다.

| 기존 node (파일 기준) | 기존 근거 / 이번 추가 목적 |
| --- | --- |
| unit/test_security.py::test_expiring_consent_is_exact_and_invalid_after_restart | scope별 단일 부정 및 grant 만료 동일 시각. 복합 scope/이력/owner/예약 결정 cube를 추가한다. |
| unit/test_security.py::test_epoch_regrant_and_session_revocation_invalidate_permits 및 test_frozen_grant_bindings_do_not_expand_or_revive | stale epoch/session의 단일 반례. 재허용과 현재 철회를 서로 다른 이력 축으로 두어 다른 실패와 조합한다. session 삭제·실행 재시작은 기존 근거에 연결하며 새 cube 전수에 포함했다고 주장하지 않는다. |
| integration/test_gateway.py::test_revoke_before_first_or_second_handoff_blocks_unsent_bytes | grant/session/execution 철회 × 첫/후속 handoff. owner·취소·기한과의 동시 부정 우선순위와 잔여 budget을 추가한다. |
| integration/test_gateway.py::test_deadline_and_cancel_preserve_unsent_or_unknown_cost | 단일 취소/timeout의 전후 경계. 여기서는 정확한 deadline −1/동일/+1 및 복합 부정을 확인한다. |
| integration/test_egress_independent.py::test_dispatch_guard_faults_preserve_exact_handoff_and_cost | guard enter/exit의 단일 fault와 비용. 이번에는 guard 구현의 호출 횟수를 복제하지 않고 실제 open/write event에서 상태를 바꿔 여러 실패를 조합한다. |
| unit/test_security.py::test_local_attestation_and_send_permit_expire_independently | local 승인과 permit의 만료 뒤 경계. 두 만료 각각 직전/동일/직후를 완성한다. |
| unit/test_security.py::test_cost_rejects_non_integer_or_out_of_range_amount | 이미 invalid bool/float/문자열/음수/overflow를 검사한다. 새 표는 amount/limit 각각의 0/1/MAX−1/MAX와 인접 거부를 비교한다. float/문자열 중복을 새 case 수로 늘리지 않는다. |
| unit/test_security.py::test_cost_unknown_restart_settlement_and_idempotency | UNKNOWN 60→확정 40 및 재시작/중복 정산. 이번에는 같은 총 exposure의 confirmed/reserved/unknown 네 구성과 1 microunit 경계, 분할/합침 property를 추가한다. |

이전 R14 security 작성분의 독립 승인은 BR23/R13 기록이다. Q24의 새 시험 설계·oracle·mutant는 Q22가 별도로 검토하며 Q24가 단독 종결하지 않는다.

## 유한 분모와 독립 oracle

### A: admission 128행

인자 순서는 P/E/D/H/V/O/B다. P/E/D는 요청 provider/endpoint/data가 동의와 일치하는지, H는 binding을 고정한 뒤 revoke→grant 이력이 있는지, V는 요청 직전 현재 grant를 revoke했는지, O는 owner lease가 유효한지, B는 예약이 RESERVED인지(아니면 이미 UNKNOWN)다. 모든 인자는 bool이며 모두 fixture로 구성할 수 있다. 특히 H/V는 독립적인 **이력 동작**이므로 V=true가 epoch를 증가시키는 사실을 숨기면서 '현재 epoch 일치'라는 인자로 부르지 않는다.

Ω=2⁷=128, F=Ω=128. 별도 손계산 분모는 scope 8 × permission history 4 × owner 2 × reservation 2=128이다. 제외 0. 부정 복합 행도 유지한다. ID는 `admit-0000000`…`admit-1111111`; 생성은 bool 직적, 기대 ID 집합은 독립적인 정수 0…127의 이진 표현으로 만든다.

독립 허용 결정은 모든 gate의 논리곱이며 성공은 한 행뿐이다. 부정 원인별 safe error는 scope/provider/data 불일치의 CONSENT_REQUIRED, endpoint 불일치의 CONSENT_REQUIRED/ENDPOINT_CHANGED, 현재 철회의 CONSENT_REQUIRED/CONSENT_REVOKED/PERMIT_REVOKED, 재허용 이력의 PERMIT_REVOKED, 이미 UNKNOWN인 예약의 RESERVATION_NOT_DISPATCHABLE, owner 무효의 LOCAL_EXECUTION_UNVERIFIED다. 복합 실패는 해당 집합들의 합집합을 허용한다. 고정 binding/permit·예약·owned handoff의 선행 검증이 필요하다는 계약과, 동시에 여러 문제가 있을 때 진단 코드 총순서는 구분한다. 총순서는 제품 계약에 확정되지 않았으므로 우연한 구현 순서를 새 필수 계약으로 강제하지 않는다. 실제 진단은 JUnit property로 기록하되 필수 oracle는 open/write·outcome·잔액이다. 기대값 생성에 제품의 predicate/전이표를 import하지 않는다.

실패 행은 open=0/write=[]/known=True, 성공 행은 실제 write=[b'ab',b'cd']다. 예약 7/한도 10에서 RESERVED 상태가 어떤 handoff 없이 UNKNOWN으로 바뀌면 실패다. 초기부터 UNKNOWN인 행은 그대로 UNKNOWN이며 재전송을 허용하지 않는다. 성공 요청도 Gateway가 정산을 추론하지 않으므로 handoff 후 UNKNOWN 7을 유지한다. provider 응답 성공과 청구 정산을 혼동하지 않는다.

### H: handoff 복합 부정 32행

경계={transport.open 반환 직후, 첫 body write 반환 직후}, fault={현재 grant revoke, owner revoke, cancel, deadline 도달} 각 bool. Ω=2×2⁴=32, F=32, 제외 0. 별도 기대 ID 집합은 경계 두 이름 × 정수 0…15의 4bit다.

mutator는 fake transport가 관측한 실제 event에서 실행한다. 긴 sleep/스케줄러 운을 쓰지 않는다. fault가 없으면 두 body chunk가 모두 관측된다. fault가 있으면 open 완료 경계는 write 0·RESERVED·known=True, 첫 body 뒤는 [b'ab']만·UNKNOWN·known=False다. 원인별 safe error는 철회={CONSENT_REQUIRED,CONSENT_REVOKED,PERMIT_REVOKED}, cancel={CANCELLED}, deadline={TIMEOUT}, owner={LOCAL_EXECUTION_UNVERIFIED}의 합집합이다. 이미 첫 body를 넘겼으면 원인 코드와 별개로 REMOTE_OUTCOME_UNKNOWN 정규화도 허용하며 반드시 outcome_known=False다. 현재 코드의 진단 우선순위 관측과 이 필수 안전 계약을 분리한다. 이미 전달된 bytes를 철회했다고 주장하지 않는다.

### T: 시간 경계 12행

대상={grant TTL 10, SendPermit TTL 30, local endpoint 승인 TTL 10, Gateway deadline 10} × 상대시각={−1,0,+1}. Ω=4×3=12, F=12. grant/permit/local approval은 fake wall clock, request deadline은 별도 fake monotonic clock을 사용한다. 정확한 만료/기한에서는 허용하지 않는 half-open oracle다. 서로 다른 clock domain을 섞지 않는다.

### L: 비용 구성 경계 12행

총 exposure 3의 구성은 (confirmed,reserved,unknown)={(3,0,0),(0,3,0),(0,0,3),(1,1,1)}. 새 예약 2에서 한도={4,5,6}. Ω=4×3=12, F=12. 손계산 oracle는 4 거부, 5/6 수락이다. 총계가 같더라도 범주를 옮기거나 예약을 해제하지 않아야 한다. 실패 행은 이전 snapshot 그대로다. 이는 모든 분할·금액의 전수 주장이 아니다.

### I: 정수 표현 경계 14행

필드={amount,limit} × 값={−1,0,1,2⁶³−2,2⁶³−1,2⁶³,True}. Ω=2×7=14, F=14. 음수/overflow/bool은 제품 거부 입력이며 분모에 남긴다. 기대 수락값·잔액은 명시 표로 둔다. SQLite 정수 상한 내부에서 테스트하며 float/문자열 등 나머지 타입은 기존 시험에 연결한다.

유한 합계 128+32+12+12+14=**198행**. 이는 명명한 다섯 대표 부분 공간의 합집합이며 시간×scope×모든 금액까지 전체 직적의 전수라는 뜻이 아니다. manifest 검사는 중복/누락/ID를 따로 검사하며 실제 pytest JUnit node ID를 TEMP의 별도 audit로 대조한다. '생성 198'을 '실제 실행 198'로 대체하지 않는다. 권한 이력은 capture 뒤 revoke→grant 및 마지막 revoke까지 최대 3명령이며 임의 길이 상태열을 증명하지 않는다.

## Property·mutation 계획

비용 동일 범주에서 한 예약 x+y를 두 예약 x,y로 분할해도 같은 confirmed/reserved/UNKNOWN·available 결과여야 한다는 metamorphic property를 고정 seed/유한 example 수로 보강한다. 각 example은 고유 TEMP를 쓰고 무한 입력 전체 증명으로 주장하지 않는다.

명명한 mutant는 `M-Q24-EPOCH-PERMIT`(고정 binding의 epoch 불일치 검사 제거)와 `M-Q24-BUDGET-EQUALITY`(예산 초과의 >를 >=로 반전)다. 일반 pytest/CI 안에서는 소스를 바꾸거나 pytest를 재귀 호출하지 않는다. TEMP의 정상 source 사본과 개별 mutant 사본에서 별도 검증 명령으로 정상 PASS/목표 assertion FAIL 및 실제 import origin을 기록한다. workspace 원본과 인덱스는 불변이어야 한다. import/수집 실패만 발생하면 검출로 세지 않는다.

## 실행 상태와 한계

Q-P03 공개는 Q-P02 원격 CI PASS와 root의 정확한 통합 tree 검증 뒤에만 가능하다. 다른 단위의 dirty/untracked 시험을 포함한 로컬 실행을 현재 commit 검증으로 표시하지 않는다. 아래는 Q24 자신의 명시 시험 파일과 기존 관련 파일만 선택한 작업 트리 실행이며 root의 향후 stage/commit tree 승인과 구분한다.

## 실제 실행 및 분모 대조

환경 Windows 11 `10.0.26300-SP0` / AMD64 / Python 3.13.1, `.venv/Scripts/python.exe`. Ruff 0.15.22·mypy 1.20.2·pytest 9.2.0·Hypothesis 6.170.15를 사용했다. cache provider 비활성, 실행마다 고유 TEMP basetemp, ResourceWarning 오류 처리다. 관련 Qt fixture는 offscreen이며 실제 장치·네트워크·키를 사용하지 않았다.

최종 새 시험 raw SHA-256: **`7f99e7f85aeb7ab47db722130e023eacf65a374bdd25597c1d6888dbff0800d4`**. 초기 새 파일 실행은 200 PASS/9.49s였다. 이후 두 mutant의 목표가 명시적인 AssertionError가 되도록 수락/거부 assertion을 강화했고, 그 최종 파일로 아래 350개 묶음과 격리 실험을 다시 실행했다. 정상 코드에서 실패한 제품 반례는 없었다.

| 유한 family | 별도 선언 분모 | JUnit 실제 행 | 유일 ID | 누락/중복/추가 |
| --- | --- | --- | --- | --- |
| admission | 8×4×2×2=128 | 128 | 128 | 0/0/0 |
| handoff | 2×16=32 | 32 | 32 | 0/0/0 |
| exact time | 4×3=12 | 12 | 12 | 0/0/0 |
| integer budget composition | 4×3=12 | 12 | 12 | 0/0/0 |
| integer representation | 2×7=14 | 14 | 14 | 0/0/0 |
| 합계 | **198** | **198** | **198** | **0/0/0** |

`audit_cases.py`는 제품/새 시험의 생성기를 import하지 않는다. 정수 0…127/0…15의 bit ID, 네 clock 이름×세 delta, 네 명시 비용 구성×세 한도, 두 필드×일곱 경계 이름으로 기대 집합을 별도 생성하고 최종 JUnit의 실제 case ID·실패/skip 태그를 검사했다. 모든 명명한 행이 PASS였고 manifest 검사와 property 2개를 더해 새 pytest node는 200개다.

최종 관련 묶음은 **350 PASS / 15.66s, skip/xfail 0**: 새 200개와 기존 security unit 76, Gateway integration 31, BR23 egress 43이다. 합성 property 통계는 별도 node 재실행에서 **30 passing / 0 failing / 0 invalid**, `max_examples=30` 종료를 확인했다(1 PASS/1.98s). 이 중복 실행을 351개의 서로 다른 시험이라고 합산하지 않는다. property 입력은 x/y∈[0,100000], 동일 비용 상태 3종이며 더 큰 값/임의 상태 이력·무한 공간 전수 증명이 아니다.

관련 security coverage는 line **868/878=98.86%**, branch **222/232=95.69%**다. 기존 95/90 기준을 충족하며 이 수치가 미선택한 조합의 충분성을 대신하지 않는다. 새 파일 Ruff check/format 및 MYPYPATH=src mypy PASS다.

### 진단 관측과 필수 안전 계약의 구분

admission 진단 관측은 CONSENT_REQUIRED 120 / PERMIT_REVOKED 4 / RESERVATION_NOT_DISPATCHABLE 2 / LOCAL_EXECUTION_UNVERIFIED 1 / SUCCESS 1이다. handoff는 CONSENT_REQUIRED 16 / CANCELLED 4 / TIMEOUT 2 / LOCAL_EXECUTION_UNVERIFIED 2 / REMOTE_OUTCOME_UNKNOWN 6 / SUCCESS 2다. 이 분포는 `case-audit.json`에 기록한 현재 실행 관측이며 새 필수 총순서 계약으로 assert하지 않는다. 시험은 원인별 safe error 합집합, 실제 open/write 목록, outcome_known 및 RESERVED/UNKNOWN·available을 assert한다. 부정 복합 행이나 분모를 없애지 않았다.

## 격리 mutant 결과

일반 CI 시험 파일에는 source 편집·subprocess pytest 호출이 없다. 별도 TEMP 실험에서 production source 67개와 새 시험/pyproject만 사본으로 만들고, 각 사본의 `PYTHONPATH=<copy>/src`·cwd·pytest `-c`를 고정했다. 실행 전 `consent.__file__`/`ledger.__file__`이 해당 TEMP 사본임을 확인했다. 다른 worker의 dirty 시험을 복사하거나 import하지 않았다.

| 실험 | 실제 검출 node / 결과 |
| --- | --- |
| 정상 사본 | 아래 두 목표 node **2 PASS**, exit 0 |
| M-Q24-EPOCH-PERMIT | `test_admission_case_space[admit-1111011]`에서 **AssertionError: denied admission row reached a successful dispatch**, 1 FAIL/exit 1 |
| M-Q24-BUDGET-EQUALITY | `test_integer_budget_composition_boundary[budget-c1r1u1-limit5]`에서 **AssertionError: inclusive budget boundary rejected an affordable reservation**, 1 FAIL/exit 1 |

epoch mutant는 `permit`의 `expected_grant != current binding` 검사를 false로 만들어 건너뛴다. 고정 binding은 grant ID와 epoch를 함께 포함하므로 'epoch 필드 단독 비교만 검증했다'고 확대하지 않는다. regrant한 과거 계획의 revival을 검출한 것이다. 예산 mutant는 `exposure + amount > limit`의 `>`를 `>=`로 바꿨다. 두 경우 모두 import/collection error·skip·timeout 0이며 정상본 수락 기준을 통과한 **목표 assertion**이 실패했다. 일부 핵심 mutant 2개 검출이지 전체 mutation coverage가 아니다.

| 변이 파일 | 정상 raw SHA-256 | mutant raw SHA-256 |
| --- | --- | --- |
| security/consent.py | e6eda682f676ef90d0e0fae5dbcbebf6871b346a59084b3277150a656d65f4a5 | 4f3607ca7f6df93e85890b192957b2657b292600162b8c733840d15c7ed3778d |
| security/ledger.py | aae43acf576c006db8680d70d2cbc6ff16bddbb61ec3741462e73627ae93f4fa | b9885afa36efed2c998482a02808070495539f7a6f8c8fe6455632e3e1919100 |

원본 runtime 67파일의 raw SHA map이 실험 전후 동일했다. 인덱스까지 측정한 최종 실험의 전후 `.git/index` raw SHA는 양쪽 모두 `f09828d68b4ab586204c5f8e4f1419b73b8395abfdc401f3e85ab346d64c9dfe`였다. worker는 Git을 변경하는 명령을 실행하지 않았다. 첫 실험은 runtime 불변을 확인했고, 누락된 index 측정을 보완하려고 새 TEMP 사본에서 같은 정상/변이 명령을 별도로 실행해 이 witness를 확보했다. 기존 사본의 pytest basetemp를 재사용하지 않았다.

## 명령·증거 경로

증거 root: `C:\Users\gangd\AppData\Local\Temp\recoryn-q24-e6faae2e1d9f45568d29330201eb2821`. 아래 `$q24Evidence`는 이 실제 경로다.

```powershell
$q24Evidence = 'C:\Users\gangd\AppData\Local\Temp\recoryn-q24-e6faae2e1d9f45568d29330201eb2821'
$env:QT_QPA_PLATFORM = 'offscreen'
$env:HYPOTHESIS_STORAGE_DIRECTORY = "$q24Evidence\hypothesis-final"
$env:COVERAGE_FILE = "$q24Evidence\.coverage"
.venv/Scripts/python.exe -m pytest tests/property/test_security_case_space.py tests/unit/test_security.py tests/integration/test_gateway.py tests/integration/test_egress_independent.py -q -p no:cacheprovider --basetemp "$q24Evidence\combined-pytest" --hypothesis-seed=20261115 -W error::ResourceWarning --junitxml "$q24Evidence\final.xml" --cov=recoryn.security --cov-branch --cov-report=term --cov-report="json:$q24Evidence\coverage.json" --tb=short
.venv/Scripts/python.exe "$q24Evidence\audit_cases.py"
.venv/Scripts/python.exe -m pytest tests/property/test_security_case_space.py::test_cost_partition_preserves_exposure -q -p no:cacheprovider --basetemp "$q24Evidence\property-stats" --hypothesis-seed=20261115 --hypothesis-show-statistics -W error::ResourceWarning
.venv/Scripts/python.exe -m ruff check tests/property/test_security_case_space.py
.venv/Scripts/python.exe -m ruff format --check tests/property/test_security_case_space.py
$env:MYPYPATH = 'src'
.venv/Scripts/python.exe -m mypy tests/property/test_security_case_space.py
```

최종 mutation 실험은 `$q24Evidence\mutation-with-index\mutation_check.py`를 repo cwd에서 별도 실행했다. 내부의 각 pytest argv/cwd/PYTHONPATH/import origin·변경 파일 hash·반환 코드·failure node는 `mutation-with-index/mutation-witness.json`에 완전한 문자열로 기록했다. 공통 interpreter는 `D:\project\Recoryn\.venv\Scripts\python.exe`, 공통 옵션은 `-q -p no:cacheprovider -W error::ResourceWarning --tb=short`이며 각 사본의 고유 basetemp/JUnit/pyproject를 지정했다. 정상 사본은 두 node, 각 mutant 사본은 위 표의 해당 node 하나만 선택했다. 사본 source는 준비 단계에서 한 곳만 변이하고 실제 workspace는 건드리지 않았다.

| 증거 root 상대 파일 | raw SHA-256 |
| --- | --- |
| final.xml | ad969980db462ccc99453ddf8bd808f01f72bf741beb25051d5609cebfe8502d |
| combined.log | 0c49965066347712794c93b11c4adaf31eee9025c5cf6dba86e2d96ebd42bafa |
| case-audit.json | 292d393f7ed5d8efbf05042225aaeebbb3d85425d97269591e9f920b5814d317 |
| coverage.json | 2a79d1987b85b13d6a502ef1c00d8f390c79ea5b7a6b72c3522ed2942b70f602 |
| property-statistics.log | 0e9b0c0873cac9d95861b3b725f7c0823b6d43e30254ca78b6019ad3e2e8da18 |
| mutation-with-index/mutation-witness.json | 740fa0db559c3beda7f305ee3a90754ad33669d8d71cec422056cbe5dd3d35fa |
| mutation-with-index/index-witness.json | cc0c29c996fbc3d5c032a1afc1275c7e89661bde9c9a9a4b6983468b06389b15 |

fixture/API·제품 source 변경 없음, 제품 결함 미발견. 실제 daemon·외부 네트워크·vault 실키·모델·장치·전원 장애는 NOT_RUN이다. 이 제출은 Q24 작성자 검증이며 Q22의 분모·oracle·변이 독립 재확인과 root의 Q-P03 정확 통합 tree/전체 회귀가 남아 있다. Q-P02 원격 CI PASS 전 Q-P03 공개를 승인하지 않는다.
