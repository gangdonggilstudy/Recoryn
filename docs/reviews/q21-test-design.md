# Q21 상태·이력 시험 독립 검토

2026-11-15 / 검토 Q23(w5:p4), 작성 Q21, 통합 Q00 / Q-P02.

판정: **REVIEW_READY — 아래 고정 바이트의 선언된 유한 공간 RECHECKED, 열린 S0/S1/S2 발견 없음**. Q23 본인의 게시 시험이나 B22 구현을 승인하는 문서가 아니다. 정확한 Q-P02 tree 검증·최종 수락·commit/push는 Q00 책임이다.

## 대상과 독립 조사

| 읽기 전용 대상 | SHA256 |
| --- | --- |
| tests/property/test_job_case_space.py | f37901bba301beb797233d2ad606dd9540bb87572f251b9e56a94ff718ac3ef1 |
| docs/testing/q21-state-cases.md | 0e337775620ff8c4db8afd138f5da20172571fcd8a1fcaa8bd3bec594ce5556c |
| src/recoryn/jobs/__init__.py | 7949f880b00b894aaa6896c117563f3a6473bf851521f143710848033446af89 |

AGENTS/onboarding의 읽기 순서, workflow/assignments/quality, case-space/push-units, 제품·코어 계약과 결과 및 관련 기존 node를 읽었다. 이전 1444 PASS는 현재 검증으로 사용하지 않았다. 이번 쓰기는 이 리뷰 파일뿐이다. 원 시험·제품·config·Git은 변경하지 않았다.

H는 6개 명령의 길이4 단어이므로 6⁴=1296이고, 길이0…4의 유일 prefix는 Σ6ⁱ=(6⁵−1)/5=1555다. 검토 wrapper는 제품 생성기를 호출하지 않고 alphabet `ACPRUX`에 대해 길이별 집합을 반복 확장해 기대 leaf/prefix를 만들었다. D는 세 attempt의 R/A 선택 2³=8, F는 문서에 고정된 8 seed × first/latest × fence delta −1/0/+1 × 결과2 =96, K는 다섯 이진 축 2⁵=32다. D/K는 별도 정수 rank의 bit 분해, F는 명시 축의 직적으로 기대 ID를 구성했다. 합계 **1432**와 실제 성공 실행 Counter를 대조했다.

독립 실행 결과 **1433 PASS**(1432 leaf와 census1), 실제 고유 ID **1432**, missing/extra/duplicate 각각 **0**, 실제 H prefix **1555**였다. wrapper가 실제 모듈의 OBSERVED/PREFIXES와 독립 기대 집합을 대조한 증거는 `C:/Users/gangd/AppData/Local/Temp/recoryn-q23-q21-audit-4aaf52947e1646dfaf4c36eb705b3583/evidence.json`이다. 실제 거부 명령은 **2763회**였으며 거부 행을 분모에서 빼지 않았다. 관측 edge class 55개는 독립적인 전체 전이 분모가 아니다.

## oracle·거부·fence 확인

모델은 제품 enum/전이표/상수/SQL UPDATE를 기대값으로 import하지 않는다. 계약의 claim 상한3, 현재 attempt identity와 fence, cancel 회수, 동일 성공 replay만 멱등 허용, UNKNOWN 우선순위, remote marker→cancel→cap→abandoned 복구 우선순위를 문자열 상태와 발급 ordinal로 표현한다. 실제 Job의 state/version/fence/owner/result/error, 전체 Attempt·event·reader를 각 명령 뒤 대조한다. 거부·멱등 호출은 Job 소유 7개 테이블 snapshot 불변까지 검사한다.

token 미발급 P/R/U는 잘못된 fixture를 생략하지 않고 well-formed 미발급 identity/fence1로 호출한다. F는 first/latest가 서로 다른 발급 attempt인 seed를 사용하고 fence0의 ValidationError도 실행한다. 과거 token, 미래/과거 fence, 다른 성공 result replay를 포함한다. 다만 중간 모든 ordinal·임의 UUID 문자열을 전수 증명하지는 않는다.

K32의 reader active+nonexclusive 8행은 기대 거부로 실행한다. 나머지24행은 remote UNKNOWN12 / cancel6 / cap FAILED3 / abandoned BLOCKED3으로 독립 분할된다. UNKNOWN은 retryable이어도 재실행 허용으로 바뀌지 않으며 후속 resume/claim/complete 거부를 확인한다. 논리 UNKNOWN과 실제 reader 종료 ACK를 혼동하지 않는다.

기존 `test_bounded_retries_keep_all_attempts_and_fence_old_results`, `test_unknown_outcome_dominates_retry_and_survives_restart`, `test_remote_intent_survives_crash_and_fences_replay_even_after_cancel`, `test_reader_ack_cannot_clear_replacement_attempt_and_retry_waits_for_exit` 및 job publication 경쟁 node와 대응을 확인했다. 기존 시험을 새 파일에 그대로 복제하지 않고 작은 명령열의 조합과 거부 불변을 보강한다. 관련 기존 node 별도 실행은 **118 PASS / 1.81s**였다. 이를 새1433개나 다른 worker/전체 QA 숫자와 겹쳐 합산하지 않는다.

## 독립 named mutant 재현

Q21 작성자의 TEMP 증거는 ACL 때문에 직접 읽지 못했다. 이 환경 제한을 통과 근거로 삼지 않고 새 TEMP 사본에서 직접 재현했다. 증거 root는 `C:/Users/gangd/AppData/Local/Temp/recoryn-q23-q21-review-871c3a5cdfe648159fb514ec9bc99db0`이며 `evidence.json`, `normal.log`, `mutant.log`에 정확한 argv/출력/전후 hash가 있다.

`Q21-M01-UNKNOWN-PRIORITY`는 TEMP JobStore의 유일한 `if not outcome_known or error_code == "REMOTE_OUTCOME_UNKNOWN":` 분기를 False로 바꾼다. 변이 SHA256은 `efd28078c27e7fcaa2a315f8cad68ab7e8ddc424310606a4fb1ad2754d93cbde`다. 같은 `test_job_command_words[H-CUXX]`를 실행해 정상 **1 PASS / exit0**, 변이 **1 FAIL / exit1**을 확인했다. `prefix=CU`의 `job state/fence/version/outcome mismatch` assertion에서 BACKOFF/None과 계약상 BLOCKED/REMOTE_UNKNOWN이 달랐다. import/collection/권한/timeout 오류를 kill로 세지 않았다.

child 환경에서 COVERAGE*, COV_CORE*, PYTEST*를 제거하고 plugin 자동적재를 차단했다. `-I`로 시작하여 TEMP src만 명시 삽입하고 Q21_EXPECTED_SOURCE_ROOT로 실제 제품 import 위치를 검사했다. TEMP pytest.ini는 importlib mode와 property marker만 지정한다. 원본 JobStore/시험은 위 표의 hash로 전후 동일했다. root에 사전 통지한 짧은 index 관측 창의 `.git/index` SHA256도 `f09828d68b4ab586204c5f8e4f1419b73b8395abfdc401f3e85ab346d64c9dfe`로 전후 동일했다. **관측 창은 종료했고 root에 종료 통지했다. 현재 index 동결 요청은 없다.**

실제 재현 명령 형식(정확한 확장 argv는 evidence.json):

```text
.venv/Scripts/python.exe -I -c "import sys;sys.path.insert(0,sys.argv[1]);import pytest;raise SystemExit(pytest.main(sys.argv[2:]))" <evidence-root>/src <evidence-root>/test_job_case_space.py::test_job_command_words[H-CUXX] -c <evidence-root>/pytest.ini -q -p no:cacheprovider --basetemp <evidence-root>/<normal|mutant> -W error::ResourceWarning --tb=short
```

일반 실행은 `.venv/Scripts/python.exe`의 pytest.main에 다음 인자를 전달했고 wrapper에서 기대 ID와 실제 ID를 대조했다. 고유 TEMP 디렉터리 뒤에 `/pytest`를 basetemp로 썼다.

```text
tests/property/test_job_case_space.py -q -s -p no:cacheprovider --basetemp <audit-root>/pytest -W error::ResourceWarning --tb=short
```

관련 기존 회귀의 실제 명령:

```powershell
$q21Related = Join-Path $env:TEMP ('recoryn-q23-q21-related-' + [guid]::NewGuid().ToString('N'))
.venv/Scripts/python.exe -m pytest tests/unit/test_jobs.py tests/integration/test_job_publication.py tests/unit/test_domain.py::test_session_transition_matrix -q -p no:cacheprovider --basetemp $q21Related -W error::ResourceWarning --tb=short
```

## 한계와 인계

H 깊이4, D core6/terminal probe 포함10, F seed+probe 최대7, K 준비·reader/marker·후속 거부 포함 최대12 API 호출의 유한 범위다. in-memory SQLite의 순차 명령 선형화를 검증하며 file reopen/전원 내구성·동시 scheduler·실 reader process·resume 전체 cube·모든 UUID/무한 입력을 증명하지 않는다. 한 mutant 검출은 전체 mutation coverage가 아니다. 모델/weights/실음성/계정/서비스는 실행하지 않았다.

대상 hash를 재확인했고 이 리뷰를 동결 제출한다. Q-P01 원격 성공은 root 전달 사실이며 독자 원격 조회 결과가 아니다. 정확한 Q-P02 tree 회귀·계측·원격 CI와 최종 승인은 root가 수행한다. Q23 본인의 COV/DAG 재작업과 이 독립 판정은 별도 역할이다.
