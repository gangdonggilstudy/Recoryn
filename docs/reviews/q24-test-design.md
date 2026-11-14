# Q24 시험 설계 독립 검토

상태: **REVIEW_READY — 선언한 198행·oracle·두 mutant 독립 재확인, 이 snapshot의 OPEN 발견 없음**. 2026-11-15 검토 Q22(w5:p3), 작성 Q24, 통합 Q00(w5:p1), push Q-P03. Q22 자신의 오디오 시험 작성·승인과 구분한 독립 검토다. 제품 전체 승인, commit/push 승인 또는 공식 릴리스 판정은 아니다.

## 범위와 동결 입력

AGENTS, onboarding 필수 순서, workflow, 2026-11-15 Q 배정, quality-system, case-space, push-units와 제품 계약·결과를 읽고 현재 status와 배정 파일을 확인했다. 이 검토의 저장소 쓰기는 이 문서 하나다. 대상 시험·case 문서, 제품, 기존 시험과 config는 읽기 전용으로 유지했다. Git 변경 명령·추가 위임·다른 workspace 제어를 하지 않았다. Q22 작성 파일은 앞서 REVIEW_READY로 제출한 hash 그대로 동결했다.

| 검토 대상 | raw SHA256 |
| --- | --- |
| tests/property/test_security_case_space.py | 7f99e7f85aeb7ab47db722130e023eacf65a374bdd25597c1d6888dbff0800d4 |
| docs/testing/q24-security-cases.md | 1bd4e606fb9dd733b37d8ea727cb44117651631a9c56f36f2328148e811926d7 |
| src/recoryn/security/consent.py | e6eda682f676ef90d0e0fae5dbcbebf6871b346a59084b3277150a656d65f4a5 |
| src/recoryn/security/ledger.py | aae43acf576c006db8680d70d2cbc6ff16bddbb61ec3741462e73627ae93f4fa |

기준 runtime은 기존 30703fe snapshot과 대조한 현재 파일이다. Q-P01=29e18b2/원격 CI 43608939380 success는 root의 선행 단위 보고이며, 이 실행을 아직 없는 Q-P03 commit의 검증으로 표현하지 않는다. 아래에는 명시 선택 파일의 workspace 실행과 TEMP 사본 검증만 기록한다.

## 유한 분모와 실제 실행 ID

시험 모듈이나 그 생성기를 import하지 않는 별도 검토 계산으로 기대 ID 집합을 만들고, 독립 실행의 JUnit testcase에서 실제 parameter ID를 추출했다. 생성 개수를 실행 개수로 대신하지 않았다.

| 가족 | 독립 분모 | 실제 유일 ID | 누락/중복/추가 |
| --- | --- | --- | --- |
| admission | scope 8 × history 4 × owner 2 × reservation 2 = 128 | 128 | 0/0/0 |
| handoff | 관측 경계 2 × fault subset 16 = 32 | 32 | 0/0/0 |
| clock boundary | grant/permit/local/deadline 4 × 상대 시각 3 = 12 | 12 | 0/0/0 |
| budget composition | 명시 exposure 구성 4 × limit 3 = 12 | 12 | 0/0/0 |
| integer representation | amount/limit 2 × 대표값 7 = 14 | 14 | 0/0/0 |
| 합계 | **198** | **198** | **0/0/0** |

admission 기대 집합은 정수 0…127의 7bit 표기, handoff는 두 경계 이름과 정수 0…15의 4bit 표기로 별도 구성했다. 나머지는 네 clock 이름 × {-1,0,+1}, 네 literal 비용 구성 × {4,5,6}, 두 필드 × 일곱 literal 값 이름을 사용했다. 유한 198행 외 manifest와 property 각 1개를 포함해 새 시험은 200 node다. 각 실행 행에 failure/error/skipped가 없음을 확인했다.

admission의 H는 binding capture 후 revoke→grant **이력**, V는 마지막 revoke **동작**이다. 이들을 서로 독립인 구성 가능한 동작으로 정의했으므로 V가 epoch를 바꾸는 사실을 이유로 행을 제외하지 않는다. provider/endpoint/data 불일치, 이미 UNKNOWN인 예약, invalid owner, 음수·overflow·bool 등 제품이 거부해야 하는 입력도 분모에 남아 있다. 선언한 가족의 fixture 불가능 제외는 0이다.

7인자 admission 전체와 각 handoff 경계의 4fault 전체를 실행하지만, 이 198행은 다섯 가족의 합이다. scope×시각×모든 금액의 전체 직적이나 모든 event permutation을 실행했다는 주장은 없다. history는 capture 뒤 최대 revoke→grant→revoke, handoff fault callback 내부 순서는 고정돼 있다. 더 긴 이력·임의 스케줄은 이 분모 밖이다.

## Oracle와 기존 시험 대응

Q24 문서가 연결한 기존 security unit의 동의 만료·epoch/regrant·frozen binding·비용 타입/UNKNOWN 복구, Gateway의 첫/후속 handoff 철회·deadline/cancel, 독립 egress의 guard fault 시험을 코드와 대조했다. 기존 단일 결함 사례를 복제해 개수만 늘리는 대신 복합 gate·관측 경계·정확한 만료와 inclusive 비용 경계를 보강한다. float/문자열 invalid 비용과 session 삭제·재시작 등은 기존 시험 근거로 연결하며 새 198행의 전수 대상이라고 하지 않는다.

**복합 거부:** admission은 모든 gate의 conjunction만 성공하게 한다. 여러 원인이 동시에 틀린 행은 해당 원인들에 허용된 safe-error 집합의 합집합을 사용한다. 코드 하나가 달라도 허용하는 무제한 오류 집합이 아니며, 임의 구현의 진단 우선순위를 새 계약으로 고정하지 않는다. 동시에 transport.open=0, writes=[], outcome_known=True와 예약/UNKNOWN exposure 전부를 검사한다. 따라서 오류명만 맞추고 전송하는 구현은 통과할 수 없다. 성공 단일 행은 정확히 [b'ab', b'cd']를 관측한다.

**Handoff:** fake transport의 실제 open-return/first-write-return callback에서 revoke/owner/cancel/deadline를 바꾼다. open 뒤 fault는 write 0·RESERVED·known, 첫 body 뒤 fault는 [b'ab']·UNKNOWN·unknown으로 구분한다. 후자에서 REMOTE_OUTCOME_UNKNOWN 정규화도 허용하되 unsent 후속 bytes와 비용 보존을 함께 확인한다. sleep이나 scheduler 우연에 의존하지 않는다. 현재 관측 diagnostic 분포도 JUnit에 남지만 분포 자체를 필수 우선순위로 assert하지 않는다.

**Clock domain:** grant TTL 10, permit TTL 30, local 승인 TTL 10은 fake wall clock을 사용한다. Gateway deadline 10은 별도 fake monotonic clock을 사용하며 wall 값은 그대로 둔다. 각 만료의 -1/0/+1에서 직전만 수락하는 half-open oracle를 확인했다. permit은 다른 TTL에 가려지지 않도록 grant TTL 60 안에서 직접 validate한다. local 승인도 grant TTL 60 안에서 검사한다.

**정수 비용:** 총 exposure 3을 confirmed/reserved/unknown의 네 구성으로 만들고 새 예약 2에 limit 4/5/6을 적용한다. 4 거부·snapshot 불변, 5 정확히 수락·available 0, 6 수락·available 1이 독립 산술 oracle다. amount와 limit 양쪽에서 -1/0/1/MAX-1/MAX/MAX+1/True를 구별하고 int64 상한과 bool 거부를 검사한다. 제품의 money/exposure predicate나 내부 상태표를 기대값으로 import하지 않는다.

**Property:** 동일 비용 상태에서 x+y 한 예약과 x,y 두 예약의 최종 snapshot/available 5를 비교한다. x,y ∈ [0,100000], 상태 세 종류, max_examples=30/derandomize/database=None의 유한 탐색이다. 독립 350 node 실행에서 통과했고, 작성자의 별도 statistics 증거(30 passing/0 failing/0 invalid) hash도 확인했다. 무한 수치 공간·혼합 상태 전이의 전수 증명은 아니다.

Owner는 synthetic lease bool guard이며 실제 Windows daemon identity의 oracle가 아니다. Wire 역시 fake transport다. 이 선택의 범위를 제품 실장비·실서비스 보장으로 확대하지 않는다.

## 독립 실행과 mutation 재확인

검토 증거 root는 `C:\Users\gangd\AppData\Local\Temp\recoryn-q22-review-q24-2b919445e0314e69adf6e18ebcebce0d`다. `.venv/Scripts/python.exe`, offscreen, cache provider 비활성, 새 TEMP basetemp, ResourceWarning-error를 사용했다.

```powershell
$q22ReviewEvidence = 'C:\Users\gangd\AppData\Local\Temp\recoryn-q22-review-q24-2b919445e0314e69adf6e18ebcebce0d'
$env:QT_QPA_PLATFORM = 'offscreen'
$env:PYTHONDONTWRITEBYTECODE = '1'
.venv/Scripts/python.exe -m pytest tests/property/test_security_case_space.py tests/unit/test_security.py tests/integration/test_gateway.py tests/integration/test_egress_independent.py -q -p no:cacheprovider --basetemp "$q22ReviewEvidence/pytest" -W error::ResourceWarning --tb=short --hypothesis-seed=2026111522 --junitxml "$q22ReviewEvidence/review.xml" --hypothesis-show-statistics
.venv/Scripts/python.exe -m ruff check tests/property/test_security_case_space.py
.venv/Scripts/python.exe -m ruff format --check tests/property/test_security_case_space.py
$env:MYPYPATH = 'src'
.venv/Scripts/python.exe -m mypy tests/property/test_security_case_space.py
```

결과는 **350 PASS, failure/error/skip 0**이다. JUnit suite 시간 13.929초이며 작성자의 350 PASS 재실행과 합산하지 않는다. 새 200 + 기존 security 76 + Gateway 31 + egress 43의 선택 실행이다. Ruff check/format 및 mypy도 PASS다. 검토자는 coverage를 새로 계측하지 않았다. 작성자의 868/878 line·222/232 branch는 작성자 결과로 구분하며 전 조합 정당성의 대체 근거로 쓰지 않는다.

작성자 증거 root `C:\Users\gangd\AppData\Local\Temp\recoryn-q24-e6faae2e1d9f45568d29330201eb2821` 아래 final.xml/combined.log/case-audit.json/coverage.json/property-statistics.log 및 mutation-with-index의 mutation-witness.json/index-witness.json 총 7개 hash가 제출 문서와 일치했다.

mutation은 작성자의 기존 TEMP source snapshot을 **읽기 전용**으로 사용하되 검토자가 새 subprocess 명령·결과·basetemp로 다시 실행했다. 정상 snapshot의 runtime 67개가 현재 원본과 byte hash로 같고, 각 mutant는 지정 파일의 지정 비교 한 곳만 달랐다. byte replace 결과를 독립 대조했다. 세 사본의 시험 hash도 동결 시험과 같았다. `-I`로 실행하고 사본 src만 앞에 삽입한 뒤 실제 consent/ledger import origin이 그 사본 안임을 subprocess 내부에서 assert했다. inherited coverage/PYTEST/PYTHONPATH 환경을 제거하고 plugin autoload를 꺼 계측·다른 시험 의존을 피했다. 정확한 argv/cwd/origin은 independent-mutation-review.json에 기록했다.

| 사본 | 목표 node | 독립 결과 |
| --- | --- | --- |
| normal | 아래 두 node | 2 PASS, exit 0 |
| M-Q24-EPOCH-PERMIT | test_admission_case_space[admit-1111011] | 1 FAIL, exit 1; AssertionError: denied admission row reached a successful dispatch |
| M-Q24-BUDGET-EQUALITY | test_integer_budget_composition_boundary[budget-c1r1u1-limit5] | 1 FAIL, exit 1; AssertionError: inclusive budget boundary rejected an affordable reservation |

두 mutant 모두 import/collection error·skip 0이며 지정 assertion에서 실패했다. 첫 mutant는 `expected_grant != self._binding(row)` 검사를 건너뛰어 stale frozen binding이 살아나는 결함, 둘째는 `exposure + amount > limit`를 `>=`로 바꿔 정확한 한도를 거부하는 결함이다. binding의 전체 identity 검사를 제거한 실험이지 epoch 필드 단독 비교만의 검출이라고 확대하지 않는다. 두 결함의 검출은 전체 mutation coverage가 아니다.

검토 mutation 전후 runtime 67개 raw hash가 작성자 before/after map 및 현재 원본과 같았다. `.git/index`도 양쪽 `f09828d68b4ab586204c5f8e4f1419b73b8395abfdc401f3e85ab346d64c9dfe`로 같았다. 검토자는 원본·인덱스를 수정하지 않았다.

새 시험의 일반 pytest 경로에는 source 복사/수정·subprocess·재귀 pytest 호출이 없다. fixture는 그 파일의 Wire/Owner/no_network와 pytest 기본 tmp_path/monkeypatch/request로 충분하며, mutation TEMP나 외부 증거 파일은 일반 실행의 입력이 아니다. 선택한 기존 integration의 conftest는 별도 DNS/socket 차단 fixture다. no_network는 전송 시도 자체를 기록해 예외가 삼켜져도 teardown에서 실패한다. 임시 SQLite와 fake 동작만 사용했다.

| 독립 증거 root 상대 파일 | raw SHA256 |
| --- | --- |
| review.xml | 7b3f9307584dd8d9124f4efc04a0b54c4ee503dfbb56c2483fa94f6ad275f522 |
| independent-id-audit.json | f2cc5f920c8895c68df9c459f9b2497c197c950bb0d1374ab192eeea4f8101c4 |
| independent-mutation-review.json | 0ee69f256e09923361eeafc6a9a72a363c9db74472d387a1ededa424b582f1b4 |

각 mutant/normal 하위 디렉터리의 result.xml/result.log에 재실행 failure와 origin이 있다. TEMP 증거는 영구 CI artifact가 아니므로 root가 통합 근거로 보존할 필요가 있다. 재실행은 위 basetemp를 재사용하지 않고 새 고유 경로를 사용해야 한다.

## 독립 판정과 남은 게이트

지정한 Q24 198행 가족, 독립 oracle, 실제 ID audit와 두 named mutant 증거에는 현재 보류할 발견이 없다. 대상 두 파일의 hash는 검토 전후 동일하다. 원본 트랙 불변·녹음/AI 분리·기본 무전송·Credential Manager 계약을 변경한 작업은 없다. 실제 daemon·Windows vault·장비 캡처·weights·실계정·유료/실서비스·전원 장애는 NOT_RUN이며 시험 통과로 확대하지 않는다.

본 제출은 **REVIEW_READY**까지다. Q22 자체 작성분은 Q24의 역리뷰가 담당한다. Q-P02 독립검토와 root의 정확한 tree 검증·원격 CI PASS를 선행한 뒤 Q-P03 통합/전체 회귀/coverage/commit/push를 root가 판정한다. dirty workspace의 다른 단위 시험을 현재 commit 검증으로 취급하지 않는다.
