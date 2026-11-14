# Q23 게시·ML 계약 경우의 수

상태: **REVIEW_READY / Q23-COV-01·Q23-DAG-02 FIXED 자체 제출, Q21 독립 재확인 대기**. 작성 Q23, 독립 검토 Q21, push Q-P03. 기준 제품 30703fe. 실제 제품·기존 시험·공용 설정·Git은 읽기 전용이며 새 전용 시험과 이 문서만 작성한다. Q-P01 → Q-P02 → Q-P03의 원격 CI 게이트 및 정확한 stage/commit tree의 최종 검증은 Q00 책임이다. 여기의 workspace 시험을 아직 만들어지지 않은 commit 검증으로 사용하지 않는다.

## 공간·독립 oracle·제약

단일 finalized synthetic 원본과 완성 base transcript, claimed Job/Attempt를 시작 상태로 둔다. 사건 ER/EW는 base에 대한 편집의 현재 active 읽기/편집 commit, SR/SW는 생성된 편집본을 명시 선택하는 active 읽기/CAS commit, PR/PW는 머신 결과의 active 읽기/게시 commit, C는 취소 commit이다. 편집 parent는 원 base로 고정하되 expected_active는 읽은 시점으로 고정한다.

HB DAG는 **ER→EW→SW, SR→SW, PR→PW**, 독립 C다. SR은 active만 읽으므로 EW보다 앞설 수 있다. 편집본 ID가 필요한 시점은 SW다. 선언한 유한 순열 Ω는 7!=5,040. 편집/선택 네 사건에서 SW는 마지막이고 ER<EW이므로 앞선 세 사건의 내부 순서는 3!/2!=3개(`ER EW SR SW`, `ER SR EW SW`, `SR ER EW SW`)다. 네 위치 C(7,4), 남은 세 위치 중 게시 pair의 위치 C(3,2)를 곱해 **315 DAG**, full/partial 교차 **630행**이다. 생성기는 7! 순열 필터, 분모는 위 독립 산식, 별도 검산 집합은 위치 조합과 명시 내부 순서3개를 사용한다. case ID는 모드와 7사건의 순서를 그대로 기록한다. 누락/중복·잘못된 순서가 있으면 audit assertion이 실패한다.

이 fixture 밖의 순서는 **4,725**개다. 중복 없는 분할은 첫 위반 우선으로 ER>EW 2,520개(편집 read snapshot 없음), 그 외 EW>SW 1,680개(선택할 edit ID 없음), 그 외 SR>SW 210개(선택 CAS snapshot 없음), 그 외 PR>PW 315개(게시 CAS snapshot 없음)다. 이는 이 client-history의 입력 의존 조건이지 제품 API가 잘못된 입력을 안전하게 거부함을 면제하는 규칙이 아니다. C 선행 게시, stale selection CAS와 stale 게시 후보는 F에 그대로 남는다. 잘못된 target ID/세션·타입·schema 자체는 기존 전용 시험에 대응하며 이 DAG의 전수 공간으로 주장하지 않는다. 사건 반복·다중 Job/Attempt·L=7 밖·무한 텍스트/시간 공간은 전수 검증하지 않는다.

Q23-DAG-02 원 발견을 수용한다. 이전 `EW→SR`을 필수 의존으로 둔 105 DAG/210행은 과도한 제약이었고, 이전의 “4,935순서 전체 구성 불가” 주장은 철회한다. 리뷰 반례 `ER-SR-EW-SW-PR-PW-C`는 full/partial 모두 구성 가능하며 SR의 base snapshot이 EW 뒤 stale이 되어 SW가 거부돼야 한다. 이번 범위는 이전 밖의 210 DAG를 추가한 최소 의존 전체315개다. 이는 시험 분모/문구 수정이며 제품 결함 수정이 아니다.

Oracle은 제품 transition table/선택 함수를 import하지 않는다. `base/edit/machine` label과 read snapshot만으로 active, revision 집합, Job/Attempt 상태·fence·result/checkpoint·감사 event 수를 예측한다. 각 prefix 7개와 초기 상태에서 public DTO, 별도 SQLite connection의 Attempt/event/checkpoint, 원 base 본문 및 실제 봉인 PCM/journal/descriptor/manifest SHA를 대조한다. full 성공은 Job/Attempt 성공이며 CAS가 지면 후보로만 남는다. partial은 비선택 draft checkpoint이고 Job/Attempt RUNNING이다. C 선행은 늦은 PW를 거부하고 fence를 회수하며 Attempt는 아직 RUNNING이다. 실제 worker ACK를 실행하지 않았으므로 CANCELLED라고 꾸미지 않는다.

이 공간은 ContentStore의 호출자가 고정한 expected_active에 대한 공개 CAS 계약이다. PR이 이미 선택된 edited를 읽고 그 ID를 명시하면 일치하는 게시를 허용한다. AIService가 자동 머신 결과에 대해 edited를 강제 교체하지 않도록 계획하는 상위 정책은 기존 AI/E2E 시험의 범위이며 이 하위 API oracle와 혼동하지 않는다. 새 경계·타입·수치 값을 무작정 곱하지 않았고, summary의 이중 포인터·UNKNOWN/reader ACK·더 긴 재시도 이력은 기존 전용 시험 및 후속 별도 공간으로 남긴다.

순차 630행은 API commit 경계의 선형화 순서 검증이다. 병렬 scheduler 자체를 전수 탐색한 결과가 아니다. 별도 4행(first writer publish/cancel × full/partial)은 세 연결의 publish/edit/cancel을 실제 thread로 시작한다. SQLite trace/Event로 첫 writer transaction을 보유한 동안 별도 reader가 이전 commit만 보는지 확인하고 두 contender를 입장시킨 뒤 해제한다. publish가 완성 commit한 뒤의 edit와 cancel은 하나는 CAS-losing 후보, 하나는 이미 성공한 Job의 취소 no-op이므로 이 관측에서 commute한다. partial 뒤에는 edit 선택과 cancel fence가 서로 다른 대상에 작용한다. cancel 선행이면 PW 거부와 edit 선택을 확인한다. 이 4행을 315가지 실제 동시 scheduler 순서라고 부르지 않는다.

실제 경합의 관측점도 구분했다. 상대 publisher/canceller 연결이 `BEGIN IMMEDIATE`에 진입한 trace를 받은 뒤 editor 호출을 시작하며 두 future가 완료되지 않은 상태에서 첫 writer를 해제한다. editor는 공유 root mutex의 호출 대기이며 SQLite lock 안까지 진입했다고 주장하지 않는다. 별도 WAL observer는 미완성 writer의 content/selection/Job/Attempt 변경을 볼 수 없다. 원자성 관측은 이 고정 SQL 지점이며 transaction 내부의 모든 instruction interleaving 전수 검증이 아니다.

## 기존 시험 대응과 새 위험

| 기존 node | 기존 범위 | Q23 추가 이유 |
| --- | --- | --- |
| tests/unit/test_content.py::test_atomic_cancel_completion_orders | 취소/완료 양순서 | 편집·명시 선택의 read/commit까지 섞인 315순서와 prefix oracle 부재 |
| tests/unit/test_content.py::test_atomic_job_edit_cas_orders | 편집/머신 양순서 | stale/현 expected를 만드는 read 시점과 취소의 고차 상호작용 |
| tests/unit/test_content.py::test_history_selection_cas_and_session | 선택 성공/거부·세션 | 선택 read와 commit 사이 머신 게시 경쟁 |
| tests/unit/test_content.py::test_partial_checkpoint_preserves_without_selection_or_success | partial 단일 사례 | 모든 feasible 읽기/편집/선택/취소 순서의 partial 교차 |
| tests/integration/test_publication_independent.py::test_sql_publication_commit_first_wins_against_concurrent_cancel | 실제 SQL callback/취소 경합 | content revision/선택/Attempt/원본과 제3 editor 연결을 함께 관측 |
| tests/integration/test_publication_independent.py::test_event_commit_failure_rolls_back_content_selection_job_and_attempt | SQL trigger 장애 rollback | 기존 장애 oracle를 유지하며 같은 장애 사례를 재작성하지 않음 |
| tests/integration/test_publication_independent.py::test_bound_job_cannot_publish_into_other_live_session | target session 거부 | 기존 잘못된 입력을 범위 축소로 면제하지 않음 |

## 실행 및 mutation

Windows / Python 3.13.1. 이전217 PASS는105 DAG의 과거 snapshot이며 현재 분모의 증거로 사용하지 않는다. 재작업 후 정확한 시험 바이트에서 비mutation **636 PASS / 1 deselected / 106.48s**, 별도 coverage 포함 mutation node **1 PASS / 1.63s**를 실행했다. 두 실행 모두 실패·skip·xfail은 없다. node 분할은 DAG630 + 생성 분모 audit1 + 실제 SQL4 + 실행 census1 =636과 mutation1이며 단일 실행637 PASS로 표현하지 않는다. mutation 내부 정상/변이 target 각1 실행은 별도 subprocess 관측이므로 최상위 시험 수에 더하지 않는다. 모두 `.venv/Scripts/python.exe`, cache-off, 고유 TEMP basetemp, ResourceWarning-error를 사용했다.

`test_case_space_has_exact_unique_ids_and_all_invalid_outcomes_are_retained`는 독립 산식315와 위치 조합 집합을 순열 필터와 비교한다. `test_completed_case_ids_have_no_missing_or_duplicate_rows`는 실제 성공 실행 뒤 append한 ID를 별도 모듈 fixture에서 집계한다. **DAG 630/630, 실제 SQL 4/4, missing 0, unexpected 0, duplicate 0**을 확인했다. DAG의 실제 초기+7 prefix ID **5,040/5,040**도 유일성/기대집합과 대조했다. SR-before-EW는 두 내부 순서 ×105위치 ×2모드 = **420/420행**, 실제 SW CAS 거부는 **416행**이었다. 리뷰 원 반례의 full/partial 두 ID가 실제 거부 집합에 있어야 census가 통과한다. 이 census는 DAG·SQL 전체 실행이 전제이며 부분 node 선택의 결과를 전체 coverage로 쓰지 않는다. 이름만 추가하고 실행하지 않은 행은 census에 들어가지 않는다.

명명 mutant `PUB_CAS_DROP_EXPECTED`는 TEMP의 전체 runtime 사본에서 `_create_transcript`의 active==expected_active 검사만 제거한다. 목표 순서는 PR→ER→EW→SR→SW→PW→C의 full 행으로, 정상은 edited active를 보존하고 mutant는 late machine으로 덮는다. 같은 node 정상 PASS와 `Q23_ACTIVE_CAS` assertion FAIL을 요구한다. child의 import 경로가 TEMP 사본인지 직접 확인하며 import/수집 오류는 kill로 세지 않는다. workspace 원 제품 bytes와 Git index bytes는 전후 동일성을 확인한다. 이 한 mutant가 전체 mutation coverage나 모든 비교 결함 검출을 증명하지 않는다.

실제 normal child exit **0 / 목표 1 PASS**, mutant child exit **1 / 목표 1 assertion FAIL**이다. 목표 node는 `test_publication_dag[full:PR-ER-EW-SR-SW-PW-C]`, 실패 표지는 `Q23_ACTIVE_CAS:`이며 pytest 출력에 `AssertionError`와 같은 node의 `1 failed`를 확인했다. import path가 TEMP src 아래임을 child에서 확인하고 제품 import 전 `sys.dont_write_bytecode=True`로 사본 bytecode 쓰기를 막았다. 테스트 안의 subprocess argv와 `-c` program이 재현 명령의 정본이다. 원본 runtime/config를 변경하지 않았다.

Q23-COV-01도 별도 수용했다. 이전의 source path guard만으로는 부모 coverage의 subprocess 계측 상속을 막지 못했다. 이제 child 환경의 대소문자 정규화된 **COVERAGE*/COV_CORE*/PYTEST***를 제거하고 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`을 지정한다. child는 **-I**로 시작해 PYTHONPATH/사용자 site 의존을 차단하고 TEMP src를 명시 삽입한다. 제품 import 전 `coverage.Coverage.current() is None`과 TEMP import 위치를 모두 검사한다. 원 pyproject는 사본에서 그대로 사용하며 부모의 coverage 설정/정본 측정대상은 바꾸지 않는다.

동일 `--cov=recoryn --cov-report=` 조건으로 재현해 부모 `.coverage`의 measured_files **67개가 전부 정본 src/recoryn 아래**, TEMP isolated 경로 **0**, 그 밖 foreign 경로 **0**임을 확인했다. 67개는 measured 파일 목록 수이며 모든 파일의 실행이나 전체 coverage 수치를 뜻하지 않는다. 정상본/변이본의 목표 oracle는 위와 같이 유지됐다. root에 사전 알린 짧은 관측 창의 source/test/index SHA는 전후 같았다. index는 `f09828d68b4ab586204c5f8e4f1419b73b8395abfdc401f3e85ab346d64c9dfe`였고 **모든 index 관측 창은 종료·통지했다**. root의 이후 stage를 동결해 달라는 요청은 없다.

새 증거는 DAG의 `C:/Users/gangd/AppData/Local/Temp/recoryn-q23-dag-fix-f9b0d7c781bd499ebc837afbe494fdcf/run.log`와 COV의 `C:/Users/gangd/AppData/Local/Temp/recoryn-q23-cov-fix-79a168eb00474d3dad226cb0f3b9785b/{evidence.json,run.log,.coverage}`다. COV evidence는 정확한 argv, 전후 hash, measured/foreign/isolated 목록을 보존한다. Q21 원 반례 TEMP는 ACL로 직접 읽지 못했으며 리뷰 문서·반례 순서를 기준으로 재현했다. 원 발견 증거를 읽은 것처럼 주장하지 않는다.

| 검증 바이트 | SHA256 |
| --- | --- |
| content/store.py 정상 | d2c4f3d7fa99ccc7c132ea61a664ca598377997d864d9ee390642c1918835f5c |
| TEMP content/store.py mutant | b9cf32f6662c30533f11a6de5c7de6eba0c18c60445b6790272eded47e7c1a10 |
| jobs/__init__.py 정상 | 7949f880b00b894aaa6896c117563f3a6473bf851521f143710848033446af89 |
| tests/property/test_publication_case_space.py | 5191e14a0b772d71e82584fda7780c6fd8331ca1c55c67865efd6a2e88e4d77a |

```powershell
$q23Run = Join-Path $env:TEMP ('recoryn-q23-dag-fix-' + [guid]::NewGuid().ToString('N'))
.venv/Scripts/python.exe -m pytest tests/property/test_publication_case_space.py -k 'not named_cas_mutant' -q -s -p no:cacheprovider --basetemp (Join-Path $q23Run 'pytest') -W error::ResourceWarning --tb=short
# 다음 명령의 COVERAGE_FILE은 별도 driver의 child 환경에서만 고유 TEMP/.coverage로 지정했다.
.venv/Scripts/python.exe -m pytest tests/property/test_publication_case_space.py::test_named_cas_mutant_is_killed_by_target_assertion --cov=recoryn --cov-report= -q -s -p no:cacheprovider --basetemp '<고유 COV TEMP>/pytest' -W error::ResourceWarning --tb=short
.venv/Scripts/python.exe -m ruff check tests/property/test_publication_case_space.py
.venv/Scripts/python.exe -m ruff format --check tests/property/test_publication_case_space.py
$env:MYPYPATH = (Resolve-Path src).Path
.venv/Scripts/python.exe -m mypy tests/property/test_publication_case_space.py
```

재작업 바이트의 Ruff check/format 및 mypy strict 1파일 PASS. 최초 mypy를 MYPYPATH 없이 단독 지정했을 때 editable install의 untyped import 경로 오류가 있었으며, 위처럼 workspace src를 명시해 해결했다. 제품 결함은 발견하지 않았다. 저장된 로그에 없는 기존 1444 PASS나 타 worker의 dirty 시험을 이번 commit 결과로 합산하지 않는다. 이번 제출은 두 건의 **FIXED 자체 보고**이며 Q21의 독립 RECHECKED/CLOSED를 대신하지 않는다. Q00 정확한 Q-P03 tree의 전체 회귀/coverage·선행 CI 확인은 대기 중이다. 별도 Q21 역리뷰는 docs/reviews/q21-test-design.md에 동결했으며 본인 Q23 승인이 아니다.

미검증: 이 하나의 L=7 DAG 밖 반복/여러 editor·여러 Job·summary의 추가 선택 차원·무한 입력·모든 OS scheduler, 실제 프로세스 crash/전원 손실·장치·모델·음성·실서비스 및 G3/G4. 기존 failure injection/UNKNOWN/reader 시험의 통과를 이번 실행으로 재선언하지 않는다. 고위험 유한 계약은 전수 열거·결정적 경합·mutation을 선택했으며 동일 상태열을 무작위 sleep이나 Hypothesis로 반복해 개수를 늘리지 않았다.
