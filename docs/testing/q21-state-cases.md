# Q21 Job 상태·이력 경우의 수

상태: **REVIEW_READY — 선언 공간 자체 실행·mutation 완료, Q23 독립 검토 대기**. 작성 Q21(w5:p2), 독립 검토 Q23, 통합 Q00. 기준 `30703feeb8b109dcfbf5093df58c964076e43ae9`; JobStore SHA256 `7949F880B00B894AAA6896C117563F3A6473BF851521F143710848033446AF89`. 1444 PASS는 과거 snapshot이다.

## 소유권·push

쓰기: `tests/property/test_job_case_space.py`, 이 문서만. runtime·기존 시험·config·Git 인덱스는 읽기 전용이다. Q-P02는 Q-P01의 원격 CI PASS 뒤 root가 Q22/독립 리뷰와 통합한다. 이 작업의 dirty workspace 실행은 Q-P02 commit 검증이 아니다. 제품 결함 발견 시 원 반례/원인을 root에 보고하고 직접 수정하지 않는다.

## 위험과 기존 대응

R04/U03/I04/C02의 취소·retry·새 attempt·늦은 결과·UNKNOWN 우선순위를 대상으로 한다. Session 전이 6×6은 기존 `tests/unit/test_domain.py::test_session_transition_matrix`에 연결하고 복제하지 않는다.

| 이미 있는 node (`tests/` 기준) | 기존 보장 / 이번 추가 차이 |
| --- | --- |
| unit/test_jobs.py::test_bounded_retries_keep_all_attempts_and_fence_old_results | 단일 R/R/R retry 경로; 이번에는 recovery와 retry를 섞은 세 단계 8열 |
| unit/test_jobs.py::test_unknown_outcome_dominates_retry_and_survives_restart | 특정 UNKNOWN→claim 거부→cancel/reopen; 이번에는 UNKNOWN 전후 중복·거부 명령을 포함한 모든 깊이4 이력 |
| unit/test_jobs.py::test_explicit_unknown_error_overrides_default_outcome_flag | error code와 outcome flag 우선순위의 기존 분할을 재사용; 이번 U는 TIMEOUT/outcome_known=False/retryable=True |
| unit/test_jobs.py::test_complete_then_cancel_is_idempotent_and_durable, test_cancel_then_complete_rejects_old_publication_and_preserves_intent | 두 대표 순서; 이번에는 중간 retry/recovery와 재진입을 함께 비교 |
| unit/test_jobs.py::test_remote_intent_survives_crash_and_fences_replay_even_after_cancel | 주로 attempt1·active reader·exclusive 복구; 이번 32행은 attempt cap·inactive reader·default 복구 거부까지 교차 |
| unit/test_jobs.py::test_reader_ack_cannot_clear_replacement_attempt_and_retry_waits_for_exit | 실제 reader ACK identity; 이번 공간은 이를 복제하지 않고 recovery의 active/exclusive 결정에 한정 |
| unit/test_jobs.py::test_resume_rejects_unsafe_blocked_conditions | resume의 개별 안전 차단; 이번 UNKNOWN 복구행에서 claim/resume 늦은 재개도 거부·불변 검사 |
| integration/test_job_publication.py::test_cancel_and_completion_order_is_durable, test_competing_connections_cannot_both_claim_one_job | 별도 connection/Barrier 경쟁은 기존 node를 유지; 이번은 명령 선형화 후의 작은 상태 모델 |
| integration/test_publication_independent.py | revision/Job 동시 transaction·세션/reader 경계는 기존 독립 회귀와 Q23의 책임 |

## 네 유한 공간과 별도 분모

| ID | 인자·제약 | 독립 분모 | 포함/제외 |
| --- | --- | --- | --- |
| H | alphabet C=claim, X=cancel, P=현재 발급 token complete, R=known retryable fail, U=unknown retryable fail, A=sole coordinator recover. 길이4 | 6⁴=1296 leaf; 모든 길이≤4 prefix는 (6⁵−1)/5=1555 | 불법 전이와 token 발급 전 P/R/U도 포함. token 미발급은 well-formed 미발급 ID/fence1로 호출. 제외0 |
| D | 세 attempt 각각 C 후 R 또는 A, 핵심 깊이6; terminal probe CPXA 4개를 이어 실행해 전체 최대10 | 2³=8; A 횟수별 C(3,k)=1/3/3/1 | 현재 제품 cap3을 계약 상수로 명시하며 구현의 MAX_ATTEMPTS를 oracle로 import하지 않음 |
| F | 8개 공개 API로 도달한 이력 × token(first/latest) × captured fence delta(−1/0/+1) × result(out/other) | 8×2×3×2=96 | 모든 seed는 attempt≥2여서 first/latest ID가 다름. fence0의 ValidationError도 포함. 거부 조합 제외0 |
| K | remote marker 유무 × cancel 유무 × reader active 유무 × exclusive 유무 × attempt 차수(1/3) | 2⁴×2=32 | active+nonexclusive는 기대 거부이며 제외하지 않음. 매개변수에 dispatch/실서비스는 없음 |

서로 다른 공간 ID를 붙인 leaf 총계는 **1296+8+96+32=1432**다. 이는 새 pytest PASS 수나 모든 가능한 API 입력의 개수가 아니다. H의 짧은 prefix는 1296열 안에서 실행되며 별도 1555개의 새 testcase로 더하지 않는다. 각 공간의 generator와 독립 rank/역변환 또는 set 산식으로 실제 유일 ID·누락·중복을 비교한다. 중복 prefix 실행 비용과 유일 prefix coverage를 구분한다.

F seed: `CRC`, `CRCX`, `CRCU`, `CRCP`, `CRCR`, `CRCRCR`, `CRCXA`, `CRCA`. token 축은 무작위 UUID의 실제 값을 정답으로 쓰지 않고 발급 순서1…n에 매핑한다. 기록은 순서·유일성·기존 token 불변을 검사한다.

깊이에는 초기 create를 세지 않는다. F는 seed≤6+complete 1로 최대7, K는 C/R/X/A core≤7와 reader/marker 2개·후속 resume/claim/complete 거부 probe 3개를 합쳐 최대12개 API 호출이다. H의 깊이4를 다른 공간의 최대 깊이로 확대하지 않는다. K에서 기대 recovery 거부는 active+nonexclusive의 8행이며 나머지24행은 remote UNKNOWN 12 / cancel 6 / cap FAILED 3 / abandoned BLOCKED 3으로 분할된다. 이 분할은 생성기와 별도로 계산한 기대표이며 32행 모두 해당 계약 assertion을 실행한다.

## 독립 oracle

작은 모델은 제품 enum/전이표/MAX_ATTEMPTS/SQL UPDATE를 import하지 않는다. 정상·거부 규칙을 다음처럼 정의한다.

- 새 claim은 queued/backoff/abandoned에서만, 취소 의도 없이 총3회까지 허용한다. 새 token fence는 마지막 job fence 다음 값이며 발급 이력은 append-only다.
- 허가된 complete는 현재 RUNNING/현재 identity/현재 fence/취소 없음의 논리곱이다. 이미 성공한 동일 token·동일 결과의 replay만 무변경 성공이며 다른 결과는 충돌이다.
- known retry는 attempt FAILED와 다음 기회 BACKOFF 또는 cap FAILED다. unknown은 retryable보다 우선하여 attempt UNKNOWN·job BLOCKED(REMOTE_UNKNOWN)이다. 그 뒤 취소/복구/늦은 complete가 이를 성공·재실행으로 바꾸지 않는다.
- cancel은 현재 게시 권한을 회수한다. terminal과 반복 cancel은 무변경, RUNNING은 CANCEL_REQUESTED, UNKNOWN은 불명 이력을 보존한다.
- 복구는 reader active+nonexclusive이면 무변경 거부한다. 허용 복구의 분류는 remote marker → UNKNOWN, 그 외 cancel → CANCELLED, 그 외 cap → FAILED/ABANDONED, 그 외 BLOCKED/ABANDONED 순이다. physical reader ACK와 논리 UNKNOWN을 분리한다.
- 매 명령 뒤 Job 상태·fence·state_version·owner·현재 attempt·결과/오류, 전체 attempt state/fence/순서/결과/오류, 영속 event 이력을 대조한다. 거부·멱등 명령은 모든 Job 소유 테이블의 읽기 snapshot 불변을 별도 확인한다.

실제 SQLite in-memory JobStore를 사용해 논리 command/transaction 모델에 집중한다. file reopen/두 connection의 내구성·경쟁·reader 수명은 기존 node에 연결한다. 모의 DB의 commit을 물리 전원 장애 내구성으로 주장하지 않는다. sleep·실제 worker·모델·원본 미디어는 필요하지 않다.

## mutation·실행 계획

최소 mutant `Q21-M01-UNKNOWN-PRIORITY`: 임시 source 사본의 fail UNKNOWN 우선 분기를 제거한다. 동일 새 시험의 `CU` 포함 대표 이력에서 정상 PASS, mutant는 기대 BLOCKED/UNKNOWN에 대한 목표 assertion FAIL이어야 한다. import/수집/권한/timeout 오류는 kill로 세지 않는다. 원본 source/test/index hash를 전후 비교하며 temporary copy만 바꾼다. 명령·node·hash·결과는 실제 실행 뒤 후단에 기록한다.

case 설계·유일 ID/실제 실행 대조, 정상 pytest, 관련 기존 회귀·Ruff/format/mypy, isolated mutant 순으로 검증한다. pytest는 `.venv/Scripts/python.exe`, `-p no:cacheprovider`, 매 실행 고유 TEMP `--basetemp`, `-W error::ResourceWarning`을 사용한다. 코드 작성 시점의 결과는 NOT_RUN이다.

## 한계

H 깊이4, D 핵심 깊이6·terminal probe 포함 최대10과 명시 F/K seed·대표 값 밖의 모든 이력·문자열·버전·identity·병렬 순서를 전수 증명하지 않는다. resume 전체 결정 cube·실 reader process·원격 ledger·content 게시·세션 삭제·filesystem·실서비스·장비는 기존/다른 배정과 연결하고 이번 유한 분모에 포함됐다고 주장하지 않는다. 독립 검토 Q23과 root의 정확한 Q-P02 tree 실행 전까지 REVIEW_READY 이상으로 자체 승인하지 않는다.

## 2026-11-15 실제 실행

| 공간 | 별도 산식의 분모 | 실제 고유 leaf ID | 누락 / 중복 | 결과 |
| --- | --- | --- | --- | --- |
| H | 1296 | 1296 | 0 / 0 | PASS; 실제 유일 prefix 1555 |
| D | 8 | 8 | 0 / 0 | PASS; retry/recovery 세 번째 attempt cap 및 후단 terminal probe |
| F | 96 | 96 | 0 / 0 | PASS; 수락/replay/StateConflict/ValidationError 모두 모델과 일치 |
| K | 32 | 32 | 0 / 0 | PASS; 제품이 거부하는 8행도 실행 |
| leaf 합계 | 1432 | 1432 | 0 / 0 | PASS |

`test_executed_case_census_has_no_missing_or_duplicate_ids`는 실제 성공한 leaf의 Counter와 product generator를 쓰지 않는 rank/divmod 기대 ID 집합을 비교한다. 전체 모듈을 순서대로 실행할 때의 census다. 필터로 선택한 mutation 단일 node를 전체 공간 통과로 계산하지 않는다. 관측 edge class(state before/command/state after/accept-or-reject)는 55개였으며 이를 모든 가능한 전이의 독립 분모라고 주장하지 않는다.

첫 새 파일 실행은 **1433 PASS / 2.21s**(1432 leaf + 실행 census 1)였다. 이후 Q21 새 파일과 `tests/unit/test_jobs.py`, `tests/integration/test_job_publication.py`, 기존 Session6×6 node만 명시해 **1551 PASS / 3.88s**, ResourceWarning 오류 처리로 통과했다. 기존 회귀 118개와 새1433개를 이 실행에서 구분하며 Q22/Q23/Q24의 dirty 새 시험은 포함하지 않았다. Ruff check/format과 strict mypy(새 파일1개)도 PASS다.

```powershell
$q21FinalTemp = Join-Path $env:TEMP ('recoryn-q21-final-' + [guid]::NewGuid().ToString('N'))
.venv/Scripts/python.exe -m pytest tests/property/test_job_case_space.py tests/unit/test_jobs.py tests/integration/test_job_publication.py tests/unit/test_domain.py::test_session_transition_matrix -q -s -p no:cacheprovider --basetemp $q21FinalTemp -W error::ResourceWarning --tb=short
.venv/Scripts/python.exe -m ruff check tests/property/test_job_case_space.py
.venv/Scripts/python.exe -m ruff format --check tests/property/test_job_case_space.py
$env:MYPYPATH = (Resolve-Path src).Path
.venv/Scripts/python.exe -m mypy tests/property/test_job_case_space.py
```

Windows / Python3.13.1, 실제 basetemp `C:/Users/gangd/AppData/Local/Temp/recoryn-q21-final-9bb136c2719e4275aab2195e14458ac8`. 최종 시험 SHA256 **f37901bba301beb797233d2ad606dd9540bb87572f251b9e56a94ff718ac3ef1**. 이번 공간에서 새 제품 결함을 발견하지 않았으며 제품·기존 시험·공용 config는 수정하지 않았다.

## Q21-M01-UNKNOWN-PRIORITY 검출

증거 root: `C:/Users/gangd/AppData/Local/Temp/recoryn-q21-mutant-swiz6osv`. 별도 `src/` 사본·시험 사본·`pytest.ini`를 만들고 child cwd/PYTHONPATH를 이 root로 고정했다. `Q21_EXPECTED_SOURCE_ROOT=<root>/src`의 실제 import 경로 assertion도 실행해 원 workspace import 우회를 막았다. 원본을 패치하거나 Git 명령을 실행해 격리하지 않았다.

- 정상 JobStore SHA256: `7949f880b00b894aaa6896c117563f3a6473bf851521f143710848033446af89`.
- 변이 JobStore SHA256: `efd28078c27e7fcaa2a315f8cad68ab7e8ddc424310606a4fb1ad2754d93cbde`.
- 유일 의미 변이: `fail`의 `if not outcome_known or error_code == "REMOTE_OUTCOME_UNKNOWN"` 분기를 False로 만들어 retryable 처리가 UNKNOWN보다 앞서게 한다.
- 동일 node `test_job_command_words[H-CUXX]`: 정상 **1 PASS / 0.24s / exit0**, 변이 **1 FAIL / 0.26s / exit1**. `prefix=CU`의 목표 `job state/fence/version/outcome mismatch` assertion에서 실제 BACKOFF/blocked_reason=None과 기대 BLOCKED/REMOTE_UNKNOWN이 달랐다. import/collection/권한/timeout 오류가 아니다. 같은 node의 원 assertion을 바꾸지 않았다.
- root에 약10초 index 관측 구간을 먼저 알렸고 실제 짧은 구간 후 source/test/index SHA를 비교했다. 원본 JobStore와 시험은 위 정상값/f37901bb…로, `.git/index`는 `f09828d68b4ab586204c5f8e4f1419b73b8395abfdc401f3e85ab346d64c9dfe`로 전후 같았다. 구간 종료를 root에 보고했다.

`evidence.json`은 전후 map·정확한 subprocess 인자·source hash·node·exit를, `normal.log`/`mutant.log`는 실제 pytest 출력을 보존한다. 재현 인자는 아래와 같으며 normal-temp/mutant-temp는 각기 고유했다.

```text
.venv/Scripts/python.exe -m pytest -c <evidence-root>/pytest.ini tests/property/test_job_case_space.py::test_job_command_words[H-CUXX] -q -p no:cacheprovider -W error::ResourceWarning --tb=short --basetemp <evidence-root>/<normal|mutant>-temp
```

이 한 mutant의 kill을 전체 프로그램 mutation coverage나 무한 상태 이력 증명으로 확대하지 않는다. 실제 media/서비스/계정/weights/장치는 실행하지 않았다.

## 독립 검토·통합 인계

Q00으로부터 Q-P01 commit `29e18b28d137f9478a139ec28ef086bb6d36e0d3`, 원격 CI run `43608939380` success를 전달받았다. 이 문서는 독자 원격 조회 결과로 바꾸지 않는다. Q-P02의 정확한 stage/commit tree 검증·Q23 독립 판정·commit/push는 root가 수행한다. 현재 실행은 선택한 workspace 파일의 자체 증거이며 후행 dirty 시험을 부분 commit 검증으로 섞지 않았다. Q23 역리뷰 배정과 최종 수락 전까지 **REVIEW_READY**다.
