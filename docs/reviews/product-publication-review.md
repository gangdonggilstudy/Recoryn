# BR24 Job·내용 게시 독립 검토

검토자 B14 / 대상 작성자 B11, `_active_jobs` 연동 B10. 2026-11-14. 최초 **OPEN S1 3건**, 현재 후단 기록의 **3건 RECHECKED**. 범위는 jobs/*, content/*, Library._active_jobs 및 오케스트레이터가 확정한 remote-intent 연동 계약이다. B14 자신이 작성한 보안 코드는 승인하지 않는다.

AGENTS, onboarding, workflow, assignments, product-contracts, quality-system 및 통합 설계의 Job/Attempt·UNKNOWN·게시 계약을 확인했다. 변경 파일은 이 문서와 [독립 반례](../../tests/integration/test_publication_independent.py)뿐이다. 실제 SQLite·임시 session·fake task를 사용하며 모델/네트워크/사용자 데이터는 사용하지 않는다.

## 최초 재현 snapshot

reader API 추가 중인 초기 collection 미완성은 결함으로 세지 않았다. 아래는 reader_started/reader_finished/local_reader_active가 준비된 뒤 원래 반례를 실행한 파일의 SHA-256이다.

| 파일 (`src/recoryn/` 기준) | SHA-256 |
| --- | --- |
| jobs/__init__.py | ccdb040fd5e19a0d3fcdaf719f73a37f3ba6de266776c87b9b4e21f5767fa456 |
| jobs/runner.py | 69ba48589f0c255b2069e949c42ba891fd359ae6941b04ab075beec58dd54d95 |
| content/store.py | 265d27b28ed2db3e4434d73c6c87531606b017da36073894157e04214a2c9906 |
| content/models.py | c595c810d08b54c0a980c17e575a0323923d745fbd9bf15e60c1f8cfa5a394cf |
| storage/library.py | 852a9f680c8ba17c1144435190946c8ef3392c08f68ac06bf679e784fc77f48c |

## 발견 사항

### BR24-01 · S1 · OPEN — Job의 session binding과 게시 대상 불일치

- 위치: content/store.py::_publication_preflight, publish_transcript, publish_summary. 같은 DB인지 검사하지만 Job의 불변 job_sessions 바인딩과 대상 session_id를 대조하지 않는다.
- 반례: source/other 두 live session을 만든다. Job을 source에 bind하고 claim한 Attempt로 other의 전사 또는 요약을 게시한다. 양쪽 모두 예외 없이 other에 revision을 저장하고 Job SUCCEEDED로 완료한다.
- 영향: source Job의 결과·수명·삭제 보호가 다른 세션의 내용 변경과 연결된다. 호출자 오류를 공개 게시 경계에서 막지 못하며 세션별 삭제/reader 격리 계약이 깨진다.
- 시험: test_bound_job_cannot_publish_into_other_live_session[transcript/summary], **2 FAIL**.
- 해결 조건: content publisher callback 전에 bind된 session과 목표 session이 같음을 확인한다. 불일치는 revision/selection/Job/Attempt/event를 변경하지 않아야 한다. 미바인딩 legacy 처리 정책은 기존 정상 공개 계약과 함께 명시한다.

### BR24-02 · S1 · OPEN — 원격 handoff 뒤 crash와 Job 복구를 잇는 영속 계약 부재

- 위치: JobStore.recover_abandoned 및 AIService의 원격 예약→Gateway dispatch 연동. JobStore 단독으로 별도 ledger의 provider/request를 추론하라는 지적은 아니다.
- 반례: RUNNING Attempt의 reader 시작을 영속화하고 비용 예약 50/100을 UNKNOWN으로 바꾼 뒤 Job.fail/complete 전에 실행이 사라진 상태를 재현한다. sole coordinator 확인으로 reader를 해제해 복구하면 ledger UNKNOWN=50은 남지만 Job은 ABANDONED로 바뀌어 새 claim이 가능하다. 원래 시나리오는 프로세스 중단 직전의 영속 상태를 저장·재개한 것이며 실제 외부 handoff는 실행하지 않았다.
- 영향: Job 미완료 창에서 원격 실행 불명이 로컬 실행 상실로 오분류돼 같은 작업을 다시 보낼 수 있다. UNKNOWN은 retryable보다 우선한다는 통합 설계와 충돌한다.
- 시험: test_crash_after_remote_handoff_cannot_become_locally_retryable, **1 FAIL**.
- B10 확정 대응 계약: JobStore.mark_remote_intent(attempt,reservation_id)를 예약 ID 수신 후 Gateway 호출 전에 commit한다. 재시작은 current Attempt의 marker가 있으면 UNKNOWN/BLOCKED(REMOTE_UNKNOWN)으로 보수 복구한다. 실제 write 전 crash도 미송신 가능성을 남긴 UNKNOWN이다. known 실패 후 새 Attempt는 이전 marker를 상속하지 않는다. shipped remote 경로는 ledger 필수로 유지한다. 신규 API 구현 중 자체 부재를 추가 결함으로 세지 않으며 안정화 후 이 명시 hook 경로로 반례를 확장한다.
- 해결 조건: marker commit 실패 시 dispatch 0, marker 이후 crash 및 취소+crash에서도 UNKNOWN 우선, 원격 marker 없는 로컬 실행 상실은 별도로 회복 가능해야 한다. 실제 예약 callback과의 연결 및 새 Attempt 분리를 검토·실행한다.

### BR24-03 · S1 · OPEN — reader ACK 저장 실패가 원격 UNKNOWN 예외를 덮음

- 위치: jobs/runner.py::_execute의 task 호출 뒤 finally reader_finished 및 _failure 분류.
- 반례: task가 code=REMOTE_OUTCOME_UNKNOWN/outcome_known=False 예외를 발생시킨다. SQLite BEFORE UPDATE trigger로 reader active=1→0 ACK만 ABORT시킨다. finally의 IntegrityError가 원래 task 오류를 대체하고 Runner는 TASK_FAILED/known=True로 분류해 Job FAILED로 종료한다.
- 영향: 물리 reader ACK 저장 오류가 이미 관측한 원격 불명 결과를 지워 신규 실행을 가능하게 할 수 있다. reader active=1이 남아 삭제는 보수 차단하지만 논리 UNKNOWN 보존을 대신하지 못한다.
- 시험: test_reader_ack_storage_failure_does_not_erase_remote_unknown, **1 FAIL**.
- 해결 조건: 원 task의 UNKNOWN을 우선 보존하고 ACK 실패를 별도 안전 오류로 기록한다. ACK 미기록은 active=1로 차단을 유지해야 한다. coordinator 증거 없이 false ACK로 바꾸면 안 된다. 정상 known 실패·성공 및 ACK 성공과의 대조 시험이 필요하다.

## 확인한 경계

- terminal event INSERT를 SQL trigger로 실패시키면 실제 content revision/selection/content_event/Job/Attempt/terminal event가 모두 rollback된다. active 없음, Job/Attempt RUNNING, 결과 ref 없음이 독립 connection에서도 일치한다.
- 취소 commit 선행은 complete=True/False 모두 늦은 content 게시를 막는다. 반대 순서는 서로 다른 JobStore connection의 동시 cancel을 SQL publication transaction 뒤로 직렬화하고 SUCCEEDED를 유지한다. replay callback은 재호출되지 않는다.
- 편집 CAS가 먼저면 늦은 머신 결과는 Job 성공 및 후보 revision으로 남고 active 편집을 덮지 않는다. 원문 hash/본문은 동일하고 편집은 user_assertion/unverified, 요약 근거도 user_assertion이다.
- 이미 기록한 Job UNKNOWN은 cancel/reopen/recover로 CANCELLED/재시도 가능 상태가 되지 않는다. BR24-02는 fail 이전 crash 창에 한정된 별도 문제다.
- 새 reader 계약에서 success/failure/UNKNOWN 모두 active=1인 동안 source 삭제는 DELETE_PENDING이다. 독립 session 삭제는 허용되고, 정확한 reader ACK 후 source 삭제가 완료되어도 논리 결과는 보존된다. 삭제 후 반복 ACK는 안전하다.
- active reader는 다음 claim 및 기본 recover를 막는다. 명시 ACK 후 새 Attempt가 시작되면 이전 Attempt의 늦은 ACK는 새 active reader를 해제하지 못한다.

## 실행 및 게이트

Windows / Python 3.13.1 / 고유 TEMP basetemp, cache provider 비활성. reader API 준비 후 독립 **13개 중 9 PASS / 4 FAIL**, skip/xfail 0. Ruff lint/format 및 MYPYPATH=src mypy PASS. 제품 코드·공용 설정·Git 변경·재위임 없음.

```powershell
$br24Run = Join-Path $env:TEMP ('recoryn-br24-' + [guid]::NewGuid().ToString('N'))
.venv/Scripts/python.exe -m pytest tests/integration/test_publication_independent.py --basetemp $br24Run -p no:cacheprovider -q --tb=short
.venv/Scripts/python.exe -m ruff check tests/integration/test_publication_independent.py
.venv/Scripts/python.exe -m ruff format --check tests/integration/test_publication_independent.py
$env:MYPYPATH = 'src'
.venv/Scripts/python.exe -m mypy tests/integration/test_publication_independent.py
```

원 발견을 작성자에게 보고했으며 작성자 수정 뒤 같은 검토자가 재확인한다. **최초 G1은 S1 OPEN 때문에 미통과**였다. 라이브러리의 모든 storage 동작, 실제 원격 billing/취소/프로세스 격리 및 G3/G4 전체를 이 검토로 승인하지 않는다.

## 수정 후 독립 재확인

수정자 B11/B10, 재확인자 B14. 원래 실패·당시 hash·발견 기록은 보존한다. 명시 remote marker API와 B10 연결이 준비된 뒤 BR24-02 시험을 확정 계약의 hook 경로로 확장했다. marker가 없는 임의 caller의 네트워크 사실을 JobStore가 추론하도록 기대하지 않는다.

| ID | 판정 | 확인한 계약 및 실행 근거 |
| --- | --- | --- |
| BR24-01 | **RECHECKED** | ContentStore가 preflight와 publisher의 동일 SQL transaction 안에서 job_sessions↔목표 session을 검사한다. 전사·요약 원반례 모두 거부되며 other revision 목록/Job RUNNING이 그대로다. unbound legacy는 기존 호환 정책을 유지한다. |
| BR24-02 | **RECHECKED** | mark_remote_intent는 current Attempt와 reservation ID를 영속화한다. recover가 current marker를 cancel/ABANDONED 판정보다 먼저 검사한다. marker 후 송신 전/후 × 취소 전/후 4조합에서 Job BLOCKED(REMOTE_UNKNOWN), 재claim 거부 및 기존 RESERVED/UNKNOWN 비용을 확인했다. known 실패 뒤 새 Attempt에는 이전 marker가 승계되지 않아 marker 없는 새 로컬 실행의 ABANDONED를 구분한다. 실제 AIService.summarize→예약 wrapper→marker commit→real Gateway/fake transport 순서를 독립 SQLite observer가 Gateway.open에서 확인했다. marker INSERT 실패는 Gateway 진입 0이고 예약 10은 provably-unsent RESERVED로 남는다. |
| BR24-03 | **RECHECKED** | Runner가 원 task_error를 별도 보존하고 reader_finished 오류가 원 UNKNOWN을 덮지 않게 했다. 원 SQL ACK trigger 실패 반례에서 Job BLOCKED(REMOTE_UNKNOWN), reader active=True, reader_ack_error=LOCAL_READER_ACK_FAILED 및 DELETE_PENDING을 확인했다. false ACK를 만들어 회피하지 않았다. 정상 ACK·known 실패·success 대조 경계도 함께 통과했다. |

재확인 snapshot SHA-256:

| 파일 (`src/recoryn/` 기준, 시험은 저장소 기준) | SHA-256 |
| --- | --- |
| jobs/__init__.py | 7949f880b00b894aaa6896c117563f3a6473bf851521f143710848033446af89 |
| jobs/runner.py | a63c10bc131875e63055f06eec216bc212ab04432fcfed643b9de504a084e557 |
| content/store.py | d2c4f3d7fa99ccc7c132ea61a664ca598377997d864d9ee390642c1918835f5c |
| content/models.py | c595c810d08b54c0a980c17e575a0323923d745fbd9bf15e60c1f8cfa5a394cf |
| storage/library.py | 852a9f680c8ba17c1144435190946c8ef3392c08f68ac06bf679e784fc77f48c |
| app/ai.py | 1483f1a91499eb527d8807c13bee56d49a3973ba0d3722966fb32b3d5e1760b3 |
| tests/integration/test_publication_independent.py | 2e7fc6f19b91fbd55d75fae4fe4fac0efe1b50a0352076fa3c5b673dfc3ef97a |

최종 실행은 독립 **19 PASS**, jobs/content/runner 유닛을 더해 **208 PASS**, skip/xfail 0이다. 위 pytest에 `tests/unit/test_jobs.py tests/unit/test_content.py tests/unit/test_runner.py -W error::ResourceWarning`을 추가했고 매번 unique TEMP basetemp를 사용했다. Ruff lint/format 및 MYPYPATH=src mypy PASS. 이 표의 모든 digest를 실제 파일 바이트와 프로그램 비교했다.

BR24 범위 OPEN S0/S1/S2 **0건**. 이 결과는 게시·reader·UNKNOWN 계약의 지정 snapshot에 한정하며 실제 원격 실행·물리 전원 장애·백업 전체 rollback 탐지·전체 제품 G1/G2 또는 G3/G4 승인이 아니다. reader coordinator_exclusive=True는 이전 worker/자식 종료를 확인한 오케스트레이터의 명시 증거이며 OS 생존 탐지 기능으로 주장하지 않는다. B14 보안 코드의 최종 승인은 다른 검토자가 맡는다.
