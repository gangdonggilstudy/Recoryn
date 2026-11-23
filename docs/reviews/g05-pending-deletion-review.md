# G05R / G-P05 재시작 뒤 삭제 대기 복원 독립 검토

상태: **REVIEW_READY — 독립 검토 1차, 2026-11-23.** 작성자는 C00이 지정한 구현 하위 에이전트이고, 검토자는 C00이 배정한 다른 하위 에이전트(Claude)다. 검토자는 코드를 고치지 않았다. 쓰기는 이 문서 하나이며 반례·측정 스크립트는 `build/review-trees/g05a-probe/`, 변이 사본은 `build/review-trees/g05a-mut/` 아래에만 두었다. 최종 수용과 push 게이트 판단은 C00이 한다.

**요약.** 계약 §2~§5의 핵심(기존 의도 한정 재시도, expected_generation 필수·stale 거부, NOT_PENDING, 같은 세대 멱등, 부활 0, 완료 오표시 0, tombstone 유지, live 보류, 폴더 제거의 root mutex 밖 실행)은 코드 읽기·전체 회귀·검토자 probe에서 확인했다. G-P05에 귀속되는 S0/S1은 찾지 못했다. **G-P05 귀속 OPEN은 S2 1건(G05R-01)과 S3 1건**이다. 중점 1의 녹음 유실은 **HEAD 2933573 단독에서 같은 크기로 재현되는 기존 결함**이며 G-P05 회귀가 아니다. 다만 영향이 녹음 유실(S1급)이라 별도 ID **G05R-02(기존 결함, S1)**로 기록하고 처리 단위 결정을 C00에 넘긴다.

## 1. 입력 고정

| 항목 | 값 |
| --- | --- |
| 대상 | tree `32081c8017f8a752eab13affc4f43fe41bf7cf32`(`git cat-file -t` = tree) |
| 기준 | HEAD `2933573`(G-P04·GT-P03 포함). `git diff 2933573 32081c80 --stat` = 10파일 4112+/116- |
| 추출 | `git -c core.autocrlf=false archive 32081c80 \| tar -x -C build/review-trees/g05a`, 비교용 `git archive 2933573` → `build/review-trees/g05a-head` |
| 제출 9파일 LF SHA256 | 계약 문서 §11.6 표와 **9/9 일치**(library.py `86ea0d1f…f499`, main.py `7ea90216…675f`, cli.py `6572ea17…9b71`, 새 시험 5, test_unfinished_sessions.py `a648c008…d838`) |
| 계약·실행 기록 | `docs/testing/g05-pending-deletion-cases.md` LF `3946f5912b2efdbd8df85847399526949ecce5d6129e482639ff6cd8f741f4b2`(446행) |
| 환경 | Windows 11 Pro 10.0.26300, 저장소 `.venv` Python 3.13.1, `PYTHONPATH=g05a/src`(사본 src import 확인), offscreen Qt, 실제 장치·모델·네트워크·vault 쓰기 없음 |

작성자는 8e09b62 기준으로 판정했다. **2933573 기준 전체 회귀는 이 검토가 처음 실행했다(J1).** 기존 storage 시험(`test_directory_reparse_point`)이 J1 basetemp에 남긴 junction 1개와 검토자 probe가 만든 junction은 링크만 제거했고 대상 폴더 존재를 확인했다. 중단한 검토자 측정 프로세스는 검토자가 시작한 것만 종료했다.

## 2. 직접 실행한 명령과 결과

| # | 명령(사본 `g05a`에서) | 결과 |
| --- | --- | --- |
| J1 | `python -B -m pytest -q -p no:cacheprovider -W error::ResourceWarning -W error::pytest.PytestUnraisableExceptionWarning --basetemp %LOCALAPPDATA%/Temp/g05a-full-E637rL/bt --junitxml g05a-probe/full.xml --durations=15`, `PYTHONDONTWRITEBYTECODE=1 QT_QPA_PLATFORM=offscreen HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1` | **9927 passed / failure 0 / error 0 / skip 0, 669.32s, exit 0**. `full.xml` LF `839576af02ab6fa5306c7f5d03b607b01b26443ad1a043eabbc8e33beebb5254` |
| J2 | `ruff check --no-cache .` / 제출 Python 9파일 `ruff format --no-cache --check` / `python -m mypy --no-incremental src/recoryn scripts packaging` | PASS / 9 files already formatted / **84 source files no issues** |
| J3 | `audit_ids.py full.xml <basetemp>`(계약 §5.5 상수 72,30,30,48,36,16,4,2801,22,12,60,35로 기대 집합을 따로 만들고 JUnit 이름과 TRACE `trace-ids.json` 5개 대조) | **관측 고유 3,166 / 누락 0 / 추가 0 / 중복 0 / skip 0**, 가족별 수 = 분모. case ID 없는 node 15(manifest 5, TRACE 깊이 5, PERF 2, UIX 2, CLI 호환 1) |
| J4 | `run_tomb.sh`·`run_tomb2.sh` → `tomb_perf.py`(HEAD·G05 같은 스크립트, 순차). 결과 `g05a-probe/tomb1/*.json`, 요약 `tomb_table.txt` | §3 표 |
| J5 | `ui_mask_probe.py ../g05a`, `../g05a-head` | G05R-01 |
| J6 | `junction_probe.py ../g05a/src`(실제 `mklink /J`) | §4.1. 외부 파일 보존, 링크만 제거 |
| J7 | `claim_race_probe.py ../g05a` | §4.2 |
| J8 | `cli_probe.py ../g05a`(새 `python -m recoryn` 프로세스 16회) | §4.4 |
| J9 | `mutate.py ../g05a ../g05a-mut mutations.json`(검토자 작성 변이 13) | §4.6 |

probe 스크립트 LF SHA256: `tomb_perf.py` `170a6849…00a5`, `run_tomb.sh` `8fa596ca…a967`, `run_tomb2.sh` `4fbf50d7…5993`, `tomb_table.py` `482a4094…64d7`, `ui_mask_probe.py` `2e26b30c…383f`, `junction_probe.py` `e85e0a4c…13ccab7`, `claim_race_probe.py` `90b0ad34…5c6c`, `cli_probe.py` `0022aac4…936f8a`, `mutate.py` `92864abc…96cf1`, `audit_ids.py` `57c9a506…29e0`. 작성자 증거(R)는 읽기만 했고 재사용하지 않았다.

## 3. 중점 1 — 삭제 기록 수와 root mutex·녹음 유실

### 3.1 코드 사실

- `_deletion_intents()`(library.py:268 → `_deletion_history` :242 → `_read_journal` :211)는 **root mutex 아래에서 journal 폴더 전체**를 `iterdir`·`check_path`·`read_json`·`schema`로 읽는다. `_live`(:272)가 이를 부르므로 `get_session`·`create_session`·`chunks`·`capture_health`·`record_capture_health`·`_manifest_current`도 모두 매번 전체를 읽는다.
- writer의 `register_chunk`는 mutex 한 구간에서 `_live`(:480)·`get_session`(:490)·`chunks`(:493 → `get_session`)로 **전체 읽기 3회**를 한다. 녹음 writer의 `ChunkWriter.append`는 블록(10ms)마다 같은 root mutex를 잡는다(chunks.py:343).
- GUI `_tick`은 250ms마다 녹음 중 세션의 `library.chunks()`를 GUI thread에서 부른다(main.py:1072). 즉 녹음하는 동안 전체 읽기 1회가 250ms마다 mutex 아래에서 일어난다.
- 완료 tombstone(journal 파일 + DB `DELETED_LOCAL` 행)은 지우지 않는다. HEAD도 완료 시 상태만 바꾸고 journal을 남긴다(g05a-head library.py:1110). G-P05는 이를 계약으로 고정했다(계약 §2.1 "라이브러리 수명 동안 보존"). 따라서 읽기 비용은 **지금까지 삭제한 세션 수**에 비례해 커진다.
- G-P05의 변화: journal 읽기 loop는 HEAD와 같다. DB 행마다 ID·세대·status 검증이 추가됐다. `register_chunk`, `storage/chunks.py`, `storage/_coordination.py`는 HEAD와 **바이트 동일**(diff 0)하다. G-P05의 새 경로(`pending_deletions`·`delete_session`/`retry_deletion` 공유 진행부·`deletion_generation`)는 journal을 mutex 밖에서 먼저 읽고 `_history_version`이 같을 때만 재사용한다(:233, :1247).

### 3.2 측정(J4)

조건: 실제 `RecordingService` 1트랙(48kHz mono, 10ms 블록, 기본 청크 96,000프레임, 큐 256블록)을 12초 실시간 제출한다. 완료 tombstone N개는 실제 `delete_session`이 남기는 모양과 같다(처음 3개는 실제 삭제로 만들고 나머지를 같은 형식으로 생성해 비교). 만든 뒤 Library를 닫았다 다시 연다(재시작). `writer+tick`은 `_tick`처럼 250ms마다 `chunks("rec")`를 부르는 thread를 더한다. root mutex는 작성자 PERF 시험과 같은 방식(최외곽 보유만)으로 쟀다. 제출 프레임은 576,000이다. 같은 PC에서 HEAD와 G05를 번갈아 순차 실행했다.

| 모드 | N | tree | 전체 읽기 1회(냉/온) s | writer `register_chunk` 최대 보유 s | tick `chunks` 최대 보유 s | 거부 블록 | 유실 프레임 |
| --- | ---: | --- | --- | ---: | ---: | ---: | ---: |
| writer | 0 | HEAD / G05 | 0.0003 / 0.0003 | – | – | 0 / 0 | 0 / 0 |
| writer | 100 | HEAD / G05 | 0.175, 0.038 / 0.162, 0.039 | 0.168 / 0.184 | – | 0 / 0 | 0 / 0 |
| writer | 400 | HEAD / G05 | 1.781, 0.146 / 0.645, 0.152 | 0.624 / 0.639 | – | 1 / 10 | 480 / 4,800 |
| writer | 1000 | HEAD / G05 | 3.977, 0.458 / 2.424, 0.539 | 1.625 / 1.596 | – | **344 / 344** | **165,120 / 165,120** |
| writer+tick | 0 | HEAD / G05 | 0.0003 / 0.0003 | – | 0.0018 / 0.0014 | 0 / 0 | 0 / 0 |
| writer+tick | 100 | HEAD / G05 | 0.203, 0.033 / 0.106, 0.035 | 0.143 / 0.134 | 0.066 / 0.066 | 0 / 0 | 0 / 0 |
| writer+tick | 200 | HEAD / G05 | 0.405, 0.066 / 0.233, 0.071 | 0.262 / 0.261 | 0.130 / 0.126 | 0 / 0 | 0 / 0 |
| writer+tick | 400 | HEAD / G05 | 0.836, 0.135 / 0.762, 0.150 | 0.620 / 0.581 | 0.273 / 0.264 | **543 / 544** | **260,640 / 261,120** |
| writer+tick | 1000 | HEAD / G05 | 2.747, 0.533 / 2.834, 0.471 | (writer가 mutex를 얻지 못함) | 0.535 / 0.504 | **923 / 914** | **443,040 / 438,720** |
| G05 새 목록(0.5초마다 `pending_deletions`) | 1000 | G05 | 2.792, 0.426 | 1.678 | 관리 최대 **0.0143**(90회, ≥50ms 0) | 344 | 165,120 |

- 냉 읽기는 다시 연 직후 첫 호출이다. 녹음 시작(`create_session`+`start`)도 N=1000에서 2.3~2.7초 걸리고 그중 `create_session` 한 번이 mutex를 0.9~1.1초 잡는다(작성자 PERF의 MainThread 관찰과 같은 경로).
- N=400·1000 writer 행의 긴 보유는 `register_chunk`(전체 읽기 3회)와 writer seal(0.6초, G-P15)이 이어 붙은 것이다. tick 행은 `chunks` 한 번이 250ms 주기보다 길어져 GUI thread가 mutex를 거의 계속 잡고 writer가 굶는다(N=1000에서 writer 최대 보유 0.024초 = 거의 append하지 못함).
- 마지막 행은 G-P05 새 경로가 이 문제를 키우지 않음을 보인다. 유실은 writer 단독 기준선(같은 N)과 같고 목록 thread의 보유는 14ms 이하다.

### 3.3 판정

- **기존 문제다. G-P05가 새로 만들거나 키우지 않았다.** HEAD 2933573 단독에서 같은 크기로 재현된다(N=1000 writer 344 대 344블록, N=400 tick 543 대 544블록). 원인 경로(`register_chunk`·`chunks`·`_tick`·journal 보존)는 G-P05 이전부터 같다. G-P05의 DB 행 검증은 온 읽기에서 0~+18%(N=1000, 0.458→0.539초) 차이로 측정 잡음과 구분되지 않고 유실 수에 영향이 없다. tombstone이 이전에는 정리되다가 G-P05에서 영구 보존으로 바뀐 것도 아니다(HEAD도 영구 보존). 새 G-P05 경로는 journal을 mutex 밖에서 읽는다.
- 작은 증가 요인 하나: G-P05 UI의 `_render_pending` → `_pending_selected` → `_update_controls`는 녹음 중이면 `get_session`(전체 읽기 1회)을 GUI thread에서 한 번 더 부른다. refresh마다 1회이며 주기 호출이 아니다. 위 측정의 주기 부하(`_tick`)에 비해 작다.
- 이 PC·1트랙에서 UI 녹음의 유실 임계는 완료 삭제 **200~400건 사이**다. 실제 앱의 2트랙은 큐를 나눠 쓰므로 임계가 더 낮을 것으로 추정한다(아래 관찰 O1 때문에 2트랙 수치는 판정에 쓰지 않았다). G-P14 보존 정책이 세션 삭제를 자동화하면 tombstone 증가가 빨라진다.
- 결론적으로 G05R-02로 기록한다. G-P05의 push 게이트에 포함할지는 C00이 결정한다. 검토자 권고는 G-P15(seal mutex)와 묶은 별도 단위다.

## 4. 중점 2~7 점검

### 4.1 삭제 대기 목록·명시 재시도(중점 2)

코드 읽기로 다음을 확인했고 J1의 INV72·GEN30·HISTORY22·TYPE12·RETRY30·CRASH48·TRACE2801이 모두 통과했다.

- `retry_deletion(session_id, *, expected_generation)`은 keyword-only·기본값 없음으로 필수이고 양의 정확한 int만 받는다(:1097). 의도가 없으면 기록을 만들기 전에 `NOT_PENDING`(:1354). 세대 비교와 `DELETE_HISTORY_CONFLICT`는 journal·DB 보강 쓰기보다 먼저다(:1364, :1366).
- 보강은 `_project_intent`의 upsert가 세대만 바꾸고 status를 유지해 `DELETED_LOCAL`을 강등하지 않는다(:1321). 단, 이 성질은 시험으로 검출되지 않는다(§4.6 N1, G05R-03).
- 폴더 제거는 세션 claim 아래·mutex 밖이고(:1391, :1409), claim 획득 뒤 D 세대·완료·보류를 다시 본다. 부분 제거는 `MEDIA_REMOVAL_FAILED`/False이고, 완료는 journal=g·폴더 없음 확인 뒤 한 transaction으로 `DELETED_LOCAL`을 기록한다. journal은 지우지 않는다.
- CRASH C0~C7(정상 unwind 24 + 소유 자식 kill 24)은 J1에서 통과했다. 검토자가 kill 시험을 따로 다시 설계하지는 않았다.
- 실제 junction(J6): 세션 폴더 안 junction과 세션 폴더 자체가 junction인 두 경우 모두 목록 `media_present=True`, 재시도 `MEDIA_REMOVAL_FAILED`, DB `DELETE_PENDING`, **외부 파일 hash 보존**이다. 작성자 위험 4는 fail closed로 확인됐다(사유가 잠김과 구별되지 않는 점은 관찰 O3).

### 4.2 G-P04와의 상호작용(중점 3)

- J7: 같은 세션의 `finalize_unfinished`·`recover_session`을 `verify_bundle` 안(mutex 밖)에서 멈추고 다른 세션을 실시간 녹음하는 중 `delete_session`을 부르면 0.005초 안에 `DELETE_PENDING/SESSION_OPERATION_IN_PROGRESS`를 돌려주고 원본은 그대로다. 멈춘 동안의 `retry_deletion`도 같은 보류다. 풀린 확정·복구는 `StateConflict: DELETE_PENDING`으로 끝나고, 이후 재시도가 `DELETED_LOCAL`(폴더 없음), 다음 재시도는 `already_deleted=True`다. 두 변형 모두 **녹음 세션 거부 0·유실 0·저장 실패 없음·288,000프레임 저장**이다.
- live 보류: `_deletion_blocker`(:1232) 순서는 SESSION_LIVE → ACTIVE_READER_OR_WRITER → SESSION_OPERATION_IN_PROGRESS이고 claim을 걸기 전에 판정한다(G04-10 교훈과 일치). G04 표의 대체 행은 승인 범위(`_DELETE` 한 항목 + 그 행 단언 + `act`의 결과 보관 한 줄)다.
- UI에서 녹음 중 세션을 삭제하면 기존처럼 recorder를 닫은 뒤 삭제하므로(DesktopRecorder.close가 writer join) 완료된다.

### 4.3 UI(중점 4)

- 목록 조회는 `_inventory_pool` worker에서 실행되고 세대 번호로 늦은 결과를 버린다(:850, :858). 작업 뒤 관찰은 그 사이 새 조회 요청이 있으면 버린다. 재시도 결과는 표시 세대와 다르면 적용하지 않는다(:1011). 조회 실패는 마지막 성공 목록을 '확인 전'으로 남기고 재시도를 막는다.
- 선택 세션이 목록 재구성에서 사라지면 `currentItemChanged`를 내보내 privacy 패널이 None을 받는다(:558). HEAD에서 OPEN이던 G04-11과 같은 유형의 회귀는 없고, 오히려 G04-11을 해소한다(관찰 O4).
- 새 GUI thread 작업은 화면 갱신뿐이다. 다만 `_tick`의 삭제 대기 안내가 유실 경고를 덮는다(G05R-01).

### 4.4 CLI(중점 5) — J8

| 명령 | exit | 출력 |
| --- | ---: | --- |
| `list` / `list --unfinished` | 0 / 0 | 기존 형식, 숨긴 세션 없음 |
| `list --delete-pending` | 0 | 닫힌 필드 목록(`RETRY_REQUIRED`, generation 1). 완료 뒤 `[]` |
| `list --unfinished --delete-pending` | 2 | argparse 상호 배타 오류, Library 열기 전 |
| `delete n1 --expected-generation 1` | 2 | `--expected-generation requires --retry-only` |
| `--expected-generation 0` / `x1` | 2 / 2 | 양의 정수 오류 |
| `delete n1 --retry-only`(정상 세션) / `nope` | 2 / 2 | `NOT_PENDING`, security.sqlite 생성 없음 |
| `delete ../x --retry-only` / `CON` | 1 / 1 | `INVALID_SESSION_ID` |
| `delete p1 --retry-only --expected-generation 9` | 1 | `STALE_DELETE_GENERATION`(관찰 O2) |
| `delete c1 --retry-only`(완료) | 0 | `already_deleted=true` |
| `delete p1 --retry-only` ×2 | 0 / 0 | 완료 → `already_deleted=true` |

예외 본문·절대 경로는 출력하지 않는다. 기존 `delete ID`의 대기 exit 0 호환은 작성자 시험(J1 통과)이 검사한다.

### 4.5 시험 충분성(중점 6)

- 분모·ID: J3에서 3,166/누락·추가·중복·skip 0을 독립 대조했다. oracle은 계약 표를 손으로 옮긴 표(`expected_inventory`, `SHAPES`, `AFTER_CRASH`, `LIVE_EXPECT`, `ORDER_EXPECT`, TRACE `step`)와 raw SQL·파일 hash이며 제품 `_deletion_intents`를 import하지 않는다.
- ORDER의 `other_first` 8행은 순차 실행이다(상대 동작이 끝난 뒤 삭제). "상대 동작이 진행 중일 때 삭제 도착"은 J7과 G-P04 시험이 보강한다.
- UI 시험은 모두 `window.timer.stop()` 뒤 실행하므로(test_pending_deletion_ui.py:104) `_tick` 경로를 검사하지 않는다(G05R-01이 남은 이유).
- 변이 결과는 §4.6.

### 4.6 검토자 변이(J9)

`mutate.py`는 변이마다 `build/review-trees/g05a-mut/<ID>`에 pyproject·src·tests·scripts·packaging을 복사하고 한 곳만 바꾼 뒤(패턴 1회 일치 확인, 원본/변이 LF hash·import 위치·실패 node를 `g05a-probe/mutations.json`에 기록) `pytest -x`로 대상 시험을 실행했다. 정상본은 J1에서 PASS다. 모든 변이의 import는 해당 사본 src였다.

| ID | 결함(한 곳 변경) | 대상 시험 | 결과 | 근거 |
| --- | --- | --- | --- | --- |
| R1 | `_deletion_blocker`가 live owner를 무시(열린 writer만 검사) — 작성자 M13 재현 | restart + test_unfinished_sessions | KILLED | G05-LIVE-0006 (1 failed / 84 passed) |
| R2 | expected_generation 비교 제거 — M07 재현 | unit·integration·UI·CLI | KILLED | G05-GEN-0000 |
| R3 | 폴더 제거를 root mutex 안에서 — X1 재현 | PERF retry | KILLED | G05-PERF-retry-10800 |
| R4 | 목록 재구성에서 사라진 선택을 알리지 않음 — X3 재현 | UI | KILLED | UIX-0000 |
| N1 | `_project_intent` upsert가 `DELETED_LOCAL`을 `DELETE_PENDING`으로 강등 | 새 5파일 + test_unfinished_sessions + test_storage + test_storage_integrity | **SURVIVED** | 836 passed. `demote_probe.py`(LF `624b58d9…11f5`): 정상본 DB `(3, DELETED_LOCAL)` 유지, 변이본 `(3, DELETE_PENDING)` |
| N2 | CLI 재시도의 세션 철회 제거 | CLI | KILLED | G05-CLI-0026 |
| N3 | UI 재시도의 `before_delete`(세션 전송 철회·실행 취소) 제거 | UI | **SURVIVED** | 63 passed |
| N4 | claim 획득 뒤 보류 재확인 제거 | 새 5파일 | SURVIVED | 380 passed. 의도가 먼저 기록돼 그 사이 새 writer·job이 생길 수 없으므로 같은 프로세스에서 도달 불가한 방어 코드로 판단(결함으로 세지 않음) |
| N5 | 제거 뒤 journal=g 확인 제거 | 새 5파일 | SURVIVED | 380 passed. journal은 이 Library만 mutex 아래에서 쓰므로 외부 조작 없이는 도달 불가(결함으로 세지 않음) |
| N6 | `_media_present`가 검사 실패를 '폴더 없음'으로 처리 | 새 5파일 | **SURVIVED** | 380 passed. `junction_tomb_probe.py`(LF `309de18e…95db`): 완료 tombstone 뒤 세션 경로가 junction이면 정상본은 목록에 남기고 재시도 `MEDIA_REMOVAL_FAILED`, 변이본은 목록 `[]`·`already_deleted=True`(**완료 오표시**). 외부 파일은 둘 다 보존 |
| N8 | CLI가 명시 `--expected-generation`을 무시하고 현재 세대로 재시도 | CLI | **SURVIVED** | 37 passed. CLI35는 유효한 N을 넘기는 행이 없다(파서 음성 3행뿐) |
| N9 | `_tick`의 삭제 대기 재표시 제거 | UI + test_live_ui | SURVIVED | 73 passed. `_tick`의 덮어쓰기 경로를 고정하는 시험이 없다(G05R-01 수정이 기존 시험을 깨지 않음을 뜻함) |
| N7 | 제거 뒤 폴더 재확인(`RETRY_REQUIRED`) 제거 | 새 5파일 | SURVIVED | 380 passed. 의도가 있으면 늦은 writer가 폴더를 다시 만들 수 없으므로 도달 불가한 방어 코드로 판단(결함으로 세지 않음) |

`mutations.json` LF `1744c9dee823abdbb76e4e5a811c7df8bfb55feac63b3b0f6888ddf938fcebd6`. 생존 변이는 모두 대상 시험 전체를 실행했다(수집·import 오류·timeout 0).

작성자의 26/26 KILLED 중 4개를 독립 재현해 모두 같은 node에서 검출됐다. 검토자 새 변이 9개 중 KILLED 1, 도달 불가 방어 코드 3(N4·N5·N7), 시험 공백 4(N1·N3·N6·N8, G05R-03)와 G05R-01 경로 미시험 1(N9)이다.

### 4.7 전체 회귀·정적 검사(중점 7)

J1·J2 모두 PASS다. 9927은 작성자 R/final(8e09b62 기준)의 수와 같다. GT-P03이 바꾼 `test_unfinished_recovery.py`도 이 tree에서 통과했다.

## 5. 발견

### G05R-01 / S2 / OPEN — 재시작 뒤 복원된 삭제 대기 안내가 녹음 중 프레임 유실 경고를 250ms마다 덮어쓴다

- **근거(코드)**: `_tick`은 유실이 있으면 `warning`에 "오디오 저장 큐 포화로 유실된 프레임이 있습니다…"를 쓴다(main.py:1068-1071). 그 뒤 같은 tick에서 `_pending_deletions`가 있고 `storage_failed`가 아니면 `_show_pending_deletions()`를 불러(main.py:1088-1091) `warning`을 삭제 대기 문구로 바꾼다(main.py:960). 장치 상태 경고(main.py:1061)도 같은 방식으로 덮인다. HEAD도 같은 우선순위 구조였지만(g05a-head main.py:847) `_pending_deletions`는 같은 창에서 삭제가 실패했을 때만 채워졌다(g05a-head main.py:749). G-P05는 이를 **저장소에서 시작 때마다 복원**하므로 삭제 대기가 하나라도 남은 사용자는 재시작 뒤 모든 녹음에서 유실 경고를 보지 못한다.
- **재현(J5)**: `ui_mask_probe.py`. 잠금 주입으로 세션 `old`를 삭제 대기로 만들고 Library를 닫는다. 새 Library·새 MainWindow에서 다른 세션을 `max_blocks=1`로 녹음해 QUEUE_DROP 95,520프레임을 만든 뒤 `_tick()`을 한 번 부른다.
  - G05 tree: 복원 목록 `['old']`, `warning` = "삭제 대기 1건 · 원본 제거 보류 · 재시도 필요 · 이전 제거 실패 사유는 보존되지 않음. …", **유실 경고 없음**.
  - HEAD: 복원 목록 `[]`, `warning` = "오디오 저장 큐 포화로 유실된 프레임이 있습니다. 건강 정보에 누계를 보존합니다."
- **기대**: 계약 §4.1 "기존 녹음 저장 오류 경고의 우선순위와 G-P04 미확정 세션 안내를 유지한다". 녹음 중 유실·장치 경고가 삭제 대기 안내보다 우선한다. 예: `_tick`에서 유실·장치 경고가 있으면 `warning`을 덮지 않고 삭제 대기 문구는 `deletion_status`에만 쓴다. timer를 켠 UI 시험(복원된 대기 + 유실)으로 고정한다.
- **영향·등급**: 유실 자체는 health에 남고 `captured` 표시는 계속되지만, 실시간 유실 경고는 사용자가 녹음 문제를 알아챌 유일한 즉시 신호다. 삭제 대기를 끝내면 사라지는 우회 가능한 품질 결함이므로 S2로 분류했다.

### G05R-02 / S1 / OPEN(기존 결함, G-P05 회귀 아님) — 완료 삭제 기록 수에 비례한 root mutex 보유로 녹음 프레임이 유실된다

- **근거**: §3.1. 완료 tombstone이 영구 보존되는데 `_live`가 journal 전체를 root mutex 아래에서 읽고, 녹음 writer의 `register_chunk`(3회)와 GUI `_tick`의 `chunks`(250ms마다 1회)가 이를 반복한다.
- **재현(J4)**: §3.2 표. 1트랙 실시간 12초 녹음에서 HEAD·G05 모두 완료 삭제 1,000건이면 writer만으로 165,120프레임(29%), UI tick을 더하면 400건에서 약 261,000프레임(45%), 1,000건에서 약 440,000프레임(77%)이 QUEUE_DROP으로 유실된다. 200건 이하에서는 0이다.
- **기대**: 녹음 경로와 화면 갱신이 삭제 이력 크기와 무관하게 큐 용량보다 짧게 mutex를 잡는다. 예: `_live`를 `check_write_allowed`처럼 해당 ID의 journal 파일·DB 행만 보는 O(1) 검사로 바꾸고 전체 무결성 검사(tmp·손상)는 버전 대조 캐시(G-P05가 도입한 `_history_version`)나 mutex 밖 선읽기로 옮긴다. `_tick`의 `chunks` 주기 호출도 줄이거나 worker로 옮긴다. 대량 tombstone + 동시 녹음 유실 0 시험을 더한다.
- **범위**: HEAD 2933573에서 같은 크기로 재현되며 G-P05 diff가 원인 경로를 바꾸지 않았다(§3.3). 녹음 유실이라는 영향 때문에 S1로 분류했다. 처리 단위(G-P15와 묶음 등)와 G-P05 push 게이트 적용 여부는 C00이 결정한다.

### G05R-03 / S3 / OPEN — 계약이 명시한 성질 4가지를 시험이 검출하지 못한다

현재 코드의 동작은 맞다(정상본 probe로 확인). 다만 다음 결함을 넣어도 새 시험 5파일과 관련 기존 시험이 모두 통과한다(§4.6).

1. **검사할 수 없는 세션 경로를 완료로 오표시하지 않음(N6)**: `_media_present`(library.py:1225)의 "검사 실패는 존재로 본다"가 완료 판정(`_deletion_complete` :1267, 빠른 경로 :1371)과 목록(:1176)의 fail-closed 근거다. 변이본은 junction 경로를 `already_deleted=True` 완료로 보고 목록에서 숨긴다. 계약 §2.1 "파일 없음만으로 완료를 추측하지 않는다"와 "완료 오표시 0"에 해당하며, 작성자 §11.7-4가 밝힌 junction 미시험과 같은 범위다.
2. **완료 tombstone 비강등(N1)**: 계약 §2.2 정합표 6행·§2.3-3. 작성자 §11.1의 "tombstone 유지(TRACE의 강등 0)"는 최종 상태만 보므로, `DELETED_LOCAL` + 더 새 journal + 잔여 폴더에서 제거가 실패하는 경우의 강등을 놓친다.
3. **UI 재시도 전 세션 철회·실행 취소(N3)**: 계약 §3.2 "UI retry는 기존 `stop_playback`·`before_delete`를 사용해… 먼저 요청한다". 첫 삭제 때 이미 철회했으므로 현재 영향은 방어 계층이지만 호출 순서를 고정하는 시험이 없다.
4. **CLI 명시 세대 고정(N8)**: 계약 §4.2 `--expected-generation N`. 유효한 N의 일치·불일치 행이 CLI35에 없다. 검토자 J8에서 정상본의 stale 거부(exit 1, `STALE_DELETE_GENERATION`)를 확인했다.

- **기대**: 각 성질에 대한 단언을 추가한다. 예: 실제 junction(권한이 없으면 기존 경로 안전성 회귀처럼 PASS로 세지 않는 skip 규칙) 또는 `safe_path` 실패 주입으로 완료 tombstone 뒤 경로 검사 실패 행, `DELETED_LOCAL`+J 더 새+잠김 행의 DB status, UI 재시도의 `before_delete` 호출 순서, CLI 유효 N 일치/불일치 2행.
- **등급**: 시험 충분성 공백이며 현재 동작 결함은 아니므로 S3로 분류했다.

## 6. 관찰(결함으로 세지 않음)

- **O1 — 2트랙 기준선 유실**: 같은 probe를 2트랙(mic·system, 같은 큐)으로 돌렸다가 검토자가 중단한 실행(`g05a-probe/tomb/*.json`, 검토자가 시작한 프로세스만 종료)에서 **N=0에서도** HEAD 788블록/378,240프레임, G05 751블록/360,480프레임이 유실됐다(writer seal 0.60~0.63초 보유, append마다 fsync 2회). tombstone과 무관한 writer 처리량 문제로 G-P15 계열로 보인다. 같은 시간대에 다른 세션의 디스크 부하가 있었을 가능성을 배제하지 못했다. 실제 WASAPI 2트랙 측정이 필요하다. 이 때문에 §3은 1트랙으로만 판정했다.
- **O2 — stale 거부 전 세션 철회**: CLI `delete --retry-only --expected-generation N`과 UI 재시도는 세대를 비교하기 전에 ConsentStore 세션 철회를 먼저 한다(J8에서 stale exit 1인데 security.sqlite 생성). 계약 §5.5가 허용한 별도 동작이며 철회는 안전 방향이다.
- **O3 — junction 사유 구분 없음**: junction이 있는 세션 폴더는 영구히 `MEDIA_REMOVAL_FAILED`/"원본 파일 제거 실패"로 남고 잠김과 구별되지 않는다. fail closed이며 수동 정리가 필요하다.
- **O4 — G04-11 해소**: HEAD의 `_render_sessions`는 `_session_selected()`만 불러 G04-11(S3)이 남아 있었다. G-P05는 선택이 바뀌면 신호를 내보내 UIX-0000으로 privacy None을 검사한다. C00이 G04-11 상태를 갱신할 수 있다.
- **O5 — 쓰이지 않는 상태**: `MainWindow._pending_observed`는 쓰기만 하고 읽지 않는다(main.py:97, :865).
- **O6 — 목록 비용**: 완료 삭제 1,000건에서 `pending_deletions()` 한 번이 worker에서 최대 3.15초 걸린다(폴더 존재 검사·선읽기, mutex 보유는 14ms 이하). refresh마다 실행된다.
- **O7 — 작성자가 밝힌 차이 (2)(3)**: 바뀐 사유(`ACTIVE_READER_OR_WRITER`→`SESSION_LIVE`)와 이력 오류 메시지 문자열에 의존하는 다른 코드·시험은 `src`·`tests` grep에서 찾지 못했다.

## 7. 미검증·한계

- 측정은 합성 PCM, 이 PC의 SSD와 OS 파일 캐시 기준이다. 실제 WASAPI 2트랙, 느린 디스크, 백신 검사 환경이 아니다. 냉 읽기 값은 첫 호출의 파일 열기 비용을 포함한다. HEAD와 G05를 같은 스크립트로 번갈아 실행해 상대 비교와 유실 유무를 근거로 삼았다.
- tombstone은 실제 삭제 3건과 같은 형식으로 생성했다. 수년간의 실제 삭제 이력(다른 세대 값·삭제 순서)은 재현하지 않았다.
- CRASH kill·TRACE·UI60은 J1의 작성자 시험 실행으로만 확인했고, 검토자가 별도 kill 반례를 만들지 않았다.
- 실제 Windows 파일 잠금은 작성자의 E4 한 경우와 J6 junction만 관측했다. 전원 장애·외부 백업·다른 프로세스 reader 종료 증명은 범위 밖이다.
- 별도 library.sqlite의 DB-only 삭제 기록을 ConsentStore가 직접 보지 못하는 경계(계약 §3.3)는 C00 결정대로 범위 밖이며 검토하지 않았다.

## 8. 결론

**G05R REVIEW_READY: G-P05 귀속 OPEN 2 (S0 0 / S1 0 / S2 1 / S3 1) + 기존 결함 OPEN 1 (S1, G05R-02).**

- G05R-01(S2): 재시작 뒤 복원된 삭제 대기 안내가 녹음 유실·장치 경고를 매 tick 덮음.
- G05R-03(S3): 검사 불가 경로의 완료 오표시 방지·tombstone 비강등·UI 재시도 전 철회·CLI 명시 세대를 시험이 검출하지 못함(변이 N6·N1·N3·N8 생존, 현재 동작은 정상).
- G05R-02(S1, 기존): 완료 삭제 200~400건 이상에서 root mutex 아래 journal 전체 읽기로 녹음 유실. HEAD 2933573에서 동일 재현, G-P05 회귀 아님.

수정 또는 수용과 G05R-02의 처리 단위는 C00이 결정한다.

## RECHECK 1 — 2026-11-23, FIX1 재확인

같은 검토자(Claude 하위 에이전트)가 작성자 FIX1을 확인했다. 위 1차 내용은 이력으로 보존한다.

**요약: G05R-01 RECHECKED, G05R-03 RECHECKED. G05R-02는 C00 결정대로 G-P15 '삭제 의도 색인'으로 이관했고 library.py가 바뀌지 않았음을 확인했다. CRASH fixture의 PermissionError 재시도는 시험 fixture 파일에만 한정되어 제품 결함을 가리지 않는다.** 다만 그 재시도가 피한 Windows 현상(방금 게시된 파일의 첫 open 거부)을 제품의 journal 읽기에 한 번 주입하면, 다른 세션의 녹음이 중단된다. HEAD에서도 같으므로 기존 결함 **G05R-04(S1, 발생 빈도 낮음)**로 기록한다. **새 G-P05 귀속 OPEN은 2건(S3 2)**이다.
- G05R-05: FIX1이 NOT_FOUND 결과에도 '삭제 대기' 문구를 띄운다.
- G05R-06: FIX1 경고 계약 일부를 시험이 고정하지 못한다.

### R1-1. 입력 고정

- 대상 tree `0d562ef311e149262a35586a9c7aa6aec5a05ec7`(`git cat-file -t` = tree)이고 기준 HEAD는 `d26f974`다. 2933573→d26f974는 시험 `test_unfinished_recovery.py`와 문서 2개만 바꿨다.
- `git diff --name-only d26f974 0d562ef3`는 G-P05 10파일이다. 직전 검토 tree 32081c80 대비 G-P05 변경은 `ui/main.py`, 새 시험 5, 계약 문서 §12다.
- `library.py`·`cli.py`·`test_unfinished_sessions.py`는 diff 0이고, LF hash가 §11.6 그대로다(library.py `86ea0d1f…f499`).
- 추출: `git -c core.autocrlf=false archive 0d562ef3 | tar -x -C build/review-trees/g05b`. probe는 `build/review-trees/g05b-probe/`, 변이 사본은 `g05b-mut/`에 두었다.
- 제출 hash는 §12.4 6/6, §11.6 3/3 일치한다. 계약 문서 LF는 `d5e74abab056013b71f9180622d0d2b34cf7e119b5810461b87011a41d3c50e9`다.
- 작성자 증거(`recoryn-g05fix-qz9BGOIn`)는 읽기만 했다. 첫 회귀 `full.log`의 48 errors는 모두 같은 module fixture가 `g05-kills0\C5-normal\marker`를 읽다 난 PermissionError 1건이 행마다 반복 보고된 것이다.
- 정리: 기존 시험 `test_directory_reparse_point`가 K1 basetemp에 남긴 junction 1개는 링크만 제거했고 대상 폴더가 있음을 확인했다.
- 환경: K1 도중 다른 작업자의 G-P15 변이 pytest가 같은 PC에서 동시에 돌았다. 시간에 민감한 시험도 통과했다.

### R1-2. 직접 실행 결과

| # | 명령(사본 `g05b`) | 결과 |
| --- | --- | --- |
| K1 | 1차 J1과 같은 옵션(`-p no:cacheprovider`, 고유 basetemp `%LOCALAPPDATA%/Temp/g05b-full-c7wia5/bt`, offscreen, HF/transformers offline·telemetry 차단, `-W error::ResourceWarning -W error::pytest.PytestUnraisableExceptionWarning`, `PYTHONPATH=g05b/src`) | **9938 passed / failure 0 / error 0 / skip 0, 658.48s, exit 0**. `g05b-probe/full.xml` LF `6eb2dc30740450483a9b56181ff89f6ea83b688c0e983deb5d7189faa1de828f` |
| K2 | `ruff check --no-cache .` / 제출 9파일 `ruff format --check` / `python -m mypy --no-incremental src/recoryn scripts packaging` | PASS / 9 files already formatted / 84 source files no issues |
| K3 | `audit_ids2.py`(1차 상수 + FIX1 11) | **관측 고유 3,177 / 누락·추가·중복·skip 0**. FIX1 11 = 분모. case ID 없는 node 15(변동 없음) |
| K4 | 1차 `ui_mask_probe.py ../g05b` | 복원 목록 `['old']`, `_tick` 뒤 `warning` = 유실 경고, 삭제 대기는 `deletion_status`. **원 반례 재현 안 됨** |
| K5 | `ui_alert_probe.py ../g05b`(LF `9c012518…4465`) | R1-3 |
| K6 | `transient_open_probe.py ../g05b/src`, `../g05a-head/src`(LF `e3fe4024…577c`) | G05R-04 |
| K7 | `natural_open_probe.py ../g05b/src 3000`(LF `374e3a64…3851`) | 같은 프로세스에서 journal을 3,000회 게시하는 동안 읽기 5,424회, **자연 발생 PermissionError 0** |
| K8 | `notfound_probe.py ../g05b`, `../g05a`(LF `e0341aca…35a5`) | G05R-05 |
| K9 | `mutate2.py ../g05b ../g05b-mut mutations2.json`(LF `8e2ac112…f903`, 변이 9) | R1-4·G05R-06. `mutations2.json` LF `891066ef052f9878eb5ed40d302cdeb732d42ca8addb3de8e8d83aa14d23b648` |

### R1-3. G05R-01 — RECHECKED

코드: `_tick`은 녹음·저장·장치 경고를 `_alert`로만 쓴다(main.py:1078, :1084, :1086, 정의 :1109). 삭제 대기는 `_show_pending_deletions()`(announce 없음)로 `deletion_status`만 갱신한다(:1107). 사용자 삭제·재시도 결과는 `_announce`로 쓰고, 지금 칸이 마지막 alert와 같으면 쓰지 않는다(:942-946).

K5 결과(모두 재시작 뒤 복원된 대기가 있는 창, 다른 세션 녹음 중):

| 경우 | `warning` | `deletion_status` |
| --- | --- | --- |
| A 저장 실패 + 유실 + 장치 경고가 한 tick에 동시 발생 | 저장 실패 경고(우선순위 최상) | 대기 1건 |
| A' 그 뒤 tick 3회 + 새로고침 + tick | 저장 실패 경고 유지 | 대기 1건 |
| B 유실 경고 중 사용자가 다른 세션 삭제(잠김 → 대기) | 유실 경고 유지 | 대기 1건 |
| B2 같은 창에서 잠김 해제 뒤 재시도 완료 | 유실 경고 유지 | "로컬 원본·기록 삭제 완료 1건 …" |
| C 경고 없음 → 사용자 삭제(대기) | 삭제 대기 안내 → tick 3회·새로고침 뒤에도 유지 | 대기 |
| C' 이어서 유실 발생 | 유실 경고로 바뀜 | – |
| D 유실 뒤 녹음 정지(서비스 객체 유지) → 재시도 완료 | 유실 경고 유지 | 완료 1건 |

- C00 결정("녹음 유실·장치 경고 항상 우선, 삭제 대기 안내는 덮지 않는 별도 영역")과 맞다.
- **경고 해제 뒤 삭제 안내 복귀**: `warning` 칸은 삭제 안내로 저절로 돌아가지 않는다. 대신 안내는 항상 `deletion_status`에 있으므로 정보가 사라지지 않는다. 다른 메시지(예: 녹음 시작 "녹음 중입니다…")가 칸을 바꾸면 그 뒤의 사용자 결과는 다시 `warning`에 나온다.
- 관찰: 녹음을 정지해도 `recorder.recording`이 남아 있으면 유실 경고가 tick마다 다시 쓰인다(기존 동작, D행). 그동안 사용자 삭제 결과는 `deletion_status`와 목록에만 보인다. 작성자 §12.4의 남은 범위 설명과 같다.

### R1-4. G05R-03 — RECHECKED

1차 원문 패턴을 이 tree에 다시 적용했다(K9, 변이마다 사본, import 위치는 각 사본 src).

| 변이 | 결과 | 검출 node |
| --- | --- | --- |
| N1 tombstone 강등 | KILLED | G05-FIX1-0000 (1 failed / 136 passed) |
| N3 UI 재시도 `before_delete` 제거 | KILLED | G05-FIX1-0004 |
| N6 `_media_present` 검사 실패를 '없음'으로 | KILLED | G05-FIX1-0002 |
| N8 CLI 명시 세대 무시 | KILLED | G05-FIX1-0010 |
| F1 `_announce`가 alert를 무시 | KILLED | G05-FIX1-0008 |
| F3 `_alert`가 `_alert_text`를 기억하지 않음 | KILLED | G05-FIX1-0008 |
| F2·F4·F5 | SURVIVED | G05R-06 |

FIX1-0003(실제 junction)은 `_winapi.CreateJunction`으로 링크를 만들고 `link.rmdir()`로 링크만 지우며, 대상 파일 hash 보존을 검사한다. Windows 외 OS에서는 skip이다(현재 CI는 Windows).

### R1-5. CRASH fixture PermissionError 재시도(요청 3) — 제품 결함을 가리지 않음

재시도 지점은 정확히 3곳이고 모두 시험 fixture 파일만 감싼다(`grep PermissionError` 전수).

| 위치 | 감싸는 호출 | 예외 | 기한·간격 |
| --- | --- | --- | --- |
| 자식 `reach()`(test_pending_deletion_restart.py:376-387) | `temporary.replace(marker)`(시험 marker 원자 게시) | PermissionError만 | 30초, 10ms(최대 약 3,000회), 초과 시 원래 예외 재발생 |
| 부모 `read_published`(:436-446, :484) | `marker.read_text` | PermissionError만 | fixture 공통 기한(시작 +120초, :476), 10ms |
| TRACE `retry_denied`(test_pending_deletion_case_space.py:225-235, :222, :295) | 결과 JSON rename(자식)·읽기(부모) | PermissionError만 | 30초, 10ms |

- 제품 호출(`Library(root)`, `delete_session`, hook 안의 원래 `atomic_json`·`remove_tree`·`unlink`·commit)은 감싸지 않는다.
- 자식에서 제품 경로가 checkpoint 전에 PermissionError를 내면 이전과 같이 자식이 끝나고, 부모가 "child never reached it"으로 실패한다.
- `reach()`가 30초 뒤에도 marker를 못 게시해 제품 hook 안으로 예외가 새면 결과는 둘 중 하나다. 제품이 `MEDIA_REMOVAL_FAILED`로 처리한 뒤 "finished"를 쓰고 끝나거나, 예외가 전파되어 끝난다. 어느 쪽이든 부모가 실패를 보고한다.
- TRACE의 제품 예외는 `run_trace` 안에서 실패 문자열로 기록되고 `failures == []`로 검사된다. 이 경로는 바뀌지 않았다.
- C1 hook이 `os.replace`를 전역으로 바꿔도, marker의 대상 폴더는 `deletion-journal`이 아니므로 재귀나 오인이 없다.
- 따라서 재시도가 제품 assertion·제품 PermissionError를 삼키는 경로는 찾지 못했다. 같은 OS 현상이 제품에 미치는 영향은 G05R-04로 따로 기록한다.

### R1-6. 새 발견

#### G05R-04 / S1 / OPEN(기존 결함, G-P05 회귀 아님) — 다른 세션 journal 파일의 일시적 open 거부 한 번으로 진행 중 녹음이 중단된다

- **근거**: 녹음 writer의 `register_chunk`는 `_live` → `_read_journal`로 **모든 세션의** journal 파일을 연다(library.py:211-231, :480).
  - G-P05에서는 `read_json`의 OSError가 `_deletion_history`에서 `ValidationError(DELETION_HISTORY_UNAVAILABLE)`가 된다(:264-265). HEAD에서는 OSError 그대로다.
  - 어느 쪽이든 `RecordingService._consume`이 writer 오류로 입력 수락을 끈다(recording.py:206-210).
  - CRASH fixture가 겪은 "방금 rename된 파일의 첫 open을 Windows가 잠깐 거부하는" 현상이 deletion journal 파일에 일어나면, 사용자가 녹음 중 다른 세션을 삭제한 것만으로 녹음이 멈출 수 있다.
- **재현(K6, 주입)**: 세션 `rec`를 실시간 녹음(청크 4,800프레임)하는 중 1초 시점에 세션 `x`를 삭제한다. 이어서 writer thread가 `deletion-journal/x.json`을 처음 읽을 때 PermissionError를 1회 주입한다.
  - G05 tree: `writer_error = ValidationError('DELETION_HISTORY_UNAVAILABLE')`, `storage_failed=True`, 입력 수락 중단, 이후 400블록 중 294블록 거부, `stop`은 `STOP_REQUIRES_ACTIVE_SESSION`.
  - HEAD(2933573, library.py는 d26f974와 같음): `PermissionError` 그대로, 295블록 거부, 같은 중단.
- **빈도**: 주입으로만 재현했다. K7에서 같은 프로세스 게시 3,000회 중 자연 발생은 0이었다. 작성자 첫 회귀에서는 프로세스 사이(자식 rename → 부모 open)에 1회 관측됐다. 발생 빈도는 낮다고 보지만 측정하지 못했다.
- **기대**: 다른 세션의 삭제 이력 파일 상태가 진행 중 녹음을 중단시키지 않는다. 예: writer 경로는 자기 세션의 의도만 검사한다(`check_write_allowed`처럼 해당 ID 파일·DB 행만). 전체 이력 무결성 검사는 녹음 밖에서 하고, 일시적 open 거부는 짧은 재시도 뒤에만 fail closed로 판단한다. G-P15의 '삭제 의도 색인'이 이 경로를 대체하면 G05R-02와 함께 닫힌다. 주입 재현을 회귀 시험으로 둔다.
- **등급·범위**: 발생하면 녹음이 중단되는 핵심 기능 실패라 S1로 분류했다(G04-10처럼 확률이 낮아도 정의상 S1). G-P05가 만든 경로가 아니다. 계약 H22의 "journal 읽기 PermissionError → 조회 전체 안전 실패"는 목록 조회의 계약이며, 무관한 녹음 writer까지 멈추라는 뜻은 아니라고 본다. 등급 조정과 처리 단위는 C00이 결정한다.

#### G05R-05 / S3 / OPEN — FIX1이 의도가 없는 NOT_FOUND 결과에 '삭제 대기' 문구를 띄운다

- **근거**: `_delete_result`의 새 분기(main.py:801-807)는 `not deleted`이고 목록 행이 없으면 항상 "삭제 대기 · {사유} · 아직 삭제되지 않았습니다. 목록을 다시 확인합니다."를 `warning`에 쓴다. `delete_session`이 `NOT_FOUND`를 돌려주는 경우도 여기에 들어간다. 예: 미확정 목록의 '폴더만 있음' 항목을 선택해 삭제하면 행도 의도도 없어 `NOT_FOUND`가 된다.
- **재현(K8)**: 폴더만 있는 `dironly` 항목을 선택하고 삭제를 승인한다.
  - FIX1(g05b): `warning` = "삭제 대기 · 삭제 상태 확인 필요 · 아직 삭제되지 않았습니다. 목록을 다시 확인합니다.", journal 0개, DB 삭제 행 0, 폴더 보존.
  - 직전 tree(g05a): `warning` 변화 없음(기존 안내 그대로), 기록 0.
- **기대**: 계약 §2.1 "세션 폴더만 있고 DB/journal 의도가 없으면 삭제 대기로 추정하지 않는다". `NOT_FOUND`는 기존 거부 문구(예: `_REFUSALS["NOT_FOUND"]` "세션을 찾을 수 없습니다. 목록을 새로 고쳤습니다.")로 알리고 '삭제 대기'라고 쓰지 않는다. 시험 1행으로 고정한다.
- **영향·등급**: 실제 기록은 만들지 않는 표시 오류다. 사용자는 대기 목록에 없는 항목을 '삭제 대기'로 오해할 수 있다. S3.

#### G05R-06 / S3 / OPEN — FIX1 경고 계약 중 3가지를 시험이 고정하지 못한다

다음 변이를 넣어도 `test_pending_deletion_ui.py` 전체와 `test_live_ui.py`(78 node)가 통과한다(K9). 현재 코드의 동작은 K5로 맞음을 확인했다.

1. **F2** — `_tick`이 `_show_pending_deletions(announce=True)`를 부르게 바꿈. alert가 없을 때 tick이 250ms마다 공용 `warning`에 삭제 대기 안내를 다시 쓴다. 그러면 "작업 실패: …"·"오디오 내보내기 완료"·"녹음 중입니다…" 같은 다른 안내가 덮인다. FIX1 계약 §12.1 "`_tick`과 백그라운드 목록 조회는 공용 `warning` 칸을 쓰지 않는다"의 반대인데, FIX1-0006~0008은 alert가 켜진 경우만 보므로 잡지 못한다.
2. **F4** — 저장 실패 경고를 `_alert` 대신 `warning.setText`로 씀. 저장 실패 alert 뒤 사용자 결과가 그 경고를 덮게 된다. 저장 실패 문구를 검사하는 UI 시험이 없다.
3. **F5** — 첫 삭제의 완료 문구("로컬 삭제를 완료했습니다.")가 `_announce`를 우회. FIX1-0008은 재시도·잠김 경로만 검사한다.

- **기대**: alert 없는 tick이 다른 안내를 덮지 않음, 저장 실패 alert 중 사용자 결과, alert 중 첫 삭제 완료의 3행을 추가한다.
- **등급**: 시험 충분성 공백, S3.

### R1-7. 미검증·한계

- G05R-04의 실제 발생 조건(백신·인덱서·다른 프로세스의 파일 열기)을 통제해 재현하지 못했다. 주입과 자연 발생 0/3,000만 근거다.
- K1 도중 다른 작업자의 pytest가 같은 PC에서 돌았다. 관리 스레드 mutex 시간 같은 수치는 이 검토가 따로 재지 않았고 작성자 값(0.97ms·3.08ms)을 그대로 인용하지 않는다.
- 1차 §7의 한계(실장비·전원 장애·2트랙 측정)는 그대로다.

### R1-8. RECHECK 1 결론

**G05R-01 RECHECKED / G05R-03 RECHECKED / G05R-02 G-P15 이관(library.py 미변경 확인). 새 OPEN: G-P05 귀속 2 (S0 0 / S1 0 / S2 0 / S3 2) — G05R-05, G05R-06. 기존 결함 1 (S1) — G05R-04.**

- G05R-05(S3): 의도가 없는 NOT_FOUND 삭제 결과에 '삭제 대기' 문구.
- G05R-06(S3): alert 없는 tick·저장 실패 alert·첫 삭제 완료 경로의 경고 우선순위가 시험으로 고정되지 않음(F2·F4·F5 생존).
- G05R-04(S1, 기존): 다른 세션 journal 파일의 일시적 open 거부 한 번으로 진행 중 녹음 중단(주입 재현, HEAD 동일, 빈도 낮음). G-P15 색인 범위에 포함하기를 권고한다.

CRASH fixture 재시도는 시험 파일에 한정되며 제품 결함을 가리지 않는다. 수정·수용과 G05R-02·04의 처리 단위는 C00이 결정한다.

## RECHECK 2 (G-P05b) — 2026-11-23, G05R-05·06 후속 재확인

같은 검토자(Claude 하위 에이전트)가 G-P05 push(133b010) 뒤 후속 G-P05b를 짧게 확인했다. 위 내용은 이력으로 보존한다.

**요약: G05R-05 RECHECKED, G05R-06 RECHECKED.** 새 문구 분기는 다른 결과 상태(예외·세대 충돌·이력 확인 불가·NOT_FOUND·확인 전 목록·stale)에서 잘못된 문구를 만들지 않는다. 새 분기가 alert를 덮는 경로도 없다. **새 OPEN 1 (S3 1) — G05R-07**: 새 분기 두 곳의 'alert 중 덮지 않음'을 시험이 고정하지 못한다. 현재 동작은 정상이다.

### R2-1. 입력

- 대상 tree `490a01ab5aeaa13fdfed64eea1fff237566140f8`(tree)이고 기준 HEAD는 `133b010`이다. `git diff --stat 133b010 490a01ab`는 3파일 171+/6-다.
- 3파일 LF SHA256은 C00 지정 값과 같다.
  - `ui/main.py` `941e9af34a165a75135ed883153e07493d59326ec6e15aabc258853ebc718ae9`
  - `tests/ui/test_pending_deletion_ui.py` `07900e6ea877a03a1302500b46f378dbe9ca34638f491753b0aa2e74e25095bb`
  - 계약 문서 `2255dac8a1308e2f5661c3a5de9fc40857b850f3038b84764dce164ad2fda7cd`
- library.py·cli.py는 diff 0이다.
- 추출: `git -c core.autocrlf=false archive 490a01ab | tar -x -C build/review-trees/g05c`. probe는 `g05c-probe/`, 변이 사본은 `g05c-mut/`에 두었다. 작업 트리(G-P15·G-P06 변경 공존)는 쓰지 않았다. 작성자 증거는 열지 않았다.

### R2-2. 실행

| # | 명령(사본 `g05c`) | 결과 |
| --- | --- | --- |
| L1 | `pytest -q -p no:cacheprovider -W error::ResourceWarning -W error::pytest.PytestUnraisableExceptionWarning --basetemp <고유 TEMP> tests/ui` + G05 시험 4파일(unit·property·integration·e2e; UI 파일은 tests/ui에 포함), offscreen·HF offline, `PYTHONPATH=g05c/src` | **767 passed / failure·error·skip 0, 115.57s, exit 0**(tests/ui 444, unit 141, property 6, integration 137, CLI 39). `run.xml` LF `fb436d1e…54a0` |
| L2 | `ui_branch_probe.py ../g05c`(LF `d6837aab…f3c5`, 결과 `d0274f15…9555`) | R2-4 |
| L3 | `mutate3.py ../g05c ../g05c-mut mutations3.json`(LF `71776571…d3bc`, 결과 `3b860195…4023`) | R2-3 |

### R2-3. G05R-05·06 판정 — RECHECKED

| 변이(한 곳 변경, 대상 tests/ui/test_pending_deletion_ui.py + test_live_ui.py) | 결과 | 검출 node |
| --- | --- | --- |
| R05 G05R-05 되돌림(`pending = not deleted`) | KILLED | G05-FIX2-0000 |
| F2 alert 없는 tick이 대기 안내를 `warning`에 씀 | KILLED | G05-FIX2-0001 |
| F4 저장 실패 경고가 `_alert`를 우회 | KILLED | G05-FIX2-0002 |
| F5 첫 삭제 완료 문구가 `_announce`를 우회 | KILLED | G05-FIX2-0003 |
| R05c 대기(행 있음)의 `warning` 알림 제거 | KILLED | test_live_ui `test_delete_pending_keeps_visible_reason…` |
| R05b NOT_FOUND 문구가 `_announce`를 우회 | **SURVIVED**(82 passed) | G05R-07 |
| R05d 대기(행 없음) 문구가 `_announce`를 우회 | **SURVIVED**(82 passed) | G05R-07 |

`_delete_result`(main.py:797-811)는 세 경우로 갈린다. `DELETED_LOCAL`은 완료 문구다. `DELETE_PENDING`은 목록 행이 있으면 대기 목록 알림, 없으면 "삭제 대기 · 사유 …"다. 그 밖(`delete_session`이 돌려줄 수 있는 나머지는 `NOT_FOUND`뿐)은 기존 거부 문구다. 모두 `_announce`를 거친다.

### R2-4. 다른 결과 상태(L2)

| 경우 | `warning` | `deletion_status` / 기록 |
| --- | --- | --- |
| E1 `delete_session`이 `StateConflict("DELETE_HISTORY_CONFLICT")` | "작업 실패: OPERATION_FAILED_MEDIA_PRESERVED · …" | 비어 있음, 기록 0 |
| E2 `ValidationError("DELETION_HISTORY_UNAVAILABLE")` / E3 OSError / E4 실제 journal `.tmp-` | 같은 일반 실패 문구 | 같음 |
| E1~E3을 장치 alert 표시 중에 | **일반 실패 문구가 장치 alert를 대체**(관찰 R2-O1) | 같음 |
| E5 폴더만 있는 항목(NOT_FOUND), 장치 alert 중 | 장치 alert 유지 | 기록 0 |
| E5b 같은 경우, alert 없음 | "세션을 찾을 수 없습니다. 목록을 새로 고쳤습니다." | 기록 0 |
| E6 `DELETE_PENDING` 결과 + 목록 조회 실패(확인 전 목록) | "삭제 대기 · 원본 파일 제거 실패 · 아직 삭제되지 않았습니다…" | "삭제 이력 확인 불가 · 마지막으로 확인한 목록을…" |
| E7 표시 세대가 stale인 재시도 | 새 세대 행의 대기 안내(자동 재시도 없음, 새 세대 g+1 반영) | 대기 1건 |

- 예외 결과는 새 분기를 지나지 않고 기존 공통 `operation` 실패 처리(main.py:353)로 간다. 삭제 관련 문구가 틀리게 나오는 경우는 없다.
- E7에서는 이번 실행의 `STALE_DELETE_GENERATION` 사유가 옛 세대와 함께 버려진다. 그래서 "목록이 바뀌었습니다…" 대신 일반 대기 안내가 보인다. G-P05 본 단위부터의 동작이고, 계약 요구("자동으로 새 세대에 재시도하지 않고 재조회")는 지킨다(관찰).

### R2-5. 새 발견

#### G05R-07 / S3 / OPEN — 새 분기 두 곳의 'alert 표시 중 덮지 않음'이 시험으로 고정되지 않았다

- **근거**: NOT_FOUND 거부 문구(main.py:811)와 대기(목록 행 없음) 문구(:805-807)가 `_announce` 대신 `warning.setText`를 써도 tests/ui 관련 82 node가 모두 통과한다(R05b·R05d). 계약 문서 §13은 NOT_FOUND 문구도 "녹음·장치 alert가 표시 중이면 덮지 않는다"고 적었고 작성자 보고는 세 경우 모두라고 했지만, 시험이 고정한 것은 완료(FIX2-0003)와 대기·행 있음(FIX1-0008)뿐이다.
- **현재 동작**: L2 E5에서 NOT_FOUND는 장치 alert를 유지했다. 코드상 두 분기 모두 `_announce`를 쓴다.
- **기대**: alert 표시 중 NOT_FOUND 1행과 alert 표시 중 대기(목록 반영 전) 1행을 추가한다.
- **등급**: 시험 충분성 공백, S3.

### R2-6. 관찰(결함으로 세지 않음, G-P05b 변경과 무관)

- **R2-O1**: 공통 `operation` 실패 처리(main.py:353)는 `warning`에 직접 쓴다. 그래서 삭제를 포함한 모든 UI 작업의 예외가 표시 중인 일회성 장치 alert를 대체한다. 유실·저장 실패 alert는 녹음 객체가 남아 있으면 다음 tick에 돌아온다. 삭제 이력 코드는 `Task.SAFE_CODES`에 없어 일반 코드로 표시되고, 실패한 삭제 뒤 대기 목록을 다시 조회하지 않는다. G-P05 이전부터의 공통 구조다. C00 결정("경고 항상 우선")을 작업 실패 문구에도 적용할지는 C00이 정한다.
- **R2-O2**: 창이 열린 상태에서 삭제 이력이 손상되면(E4의 `.tmp-`) `_session_selected`(main.py:592, G-P04 코드)의 `get_session`이 Qt slot 안에서 처리되지 않은 `ValidationError`를 stderr에 남긴다. 화면은 계속 동작했다.

### R2-7. 결론

**G05R-05 RECHECKED / G05R-06 RECHECKED. 새 OPEN 1 (S0 0 / S1 0 / S2 0 / S3 1) — G05R-07(새 분기 두 곳의 alert 우선 미고정, 동작은 정상).** G05R-02·04(기존 S1)는 G-P15 범위로 그대로 OPEN이다. 전체 회귀는 C00이 최종 tree로 실행한다.

## RECHECK 3 (GC-P02) — 2026-11-23, PERF 상한 0.5초·CI timeout 120분 검토

같은 검토자(Claude 하위 에이전트)가 C00 작성 GC-P02를 짧게 검토했다. 위 내용은 이력으로 보존한다.

**요약: retry 행의 0.5초 상한은 X1(폴더 제거를 mutex 안에서)을 10배 이상 여유로 계속 검출한다. 그러나 X2(목록 전체를 mutex 안에서)는 0.5초에서 6/6 생존한다.** 그래서 G-P05가 C00 교훈으로 고정했던 "목록 열거는 root mutex 밖" 성질을 지키는 시험이 사라진다. **새 OPEN 1 (S2) — G05R-08.** 120분 timeout은 당장의 수용량으로는 합리적이지만 hang 탐지·시간 예산·분할 없이 상한만 올리는 방식에는 위험이 있다(R3-5 의견).

### R3-1. 입력

- 대상 tree `b1b7ad724737e9592567839f18b39828b494d8be`(tree)이고 기준 HEAD는 `68fbbda`다. `git diff --stat 68fbbda b1b7ad72`는 2파일 17+/4-다.
  - `tests/integration/test_pending_deletion_restart.py` LF `d11ccbc8174dc76eba707c3981c2ac4dfce0dc5af3156e140f4b33c9eb494449`(C00 지정 값과 일치)
  - `.github/workflows/core.yml` LF `367fed16c3ee5067f8a1508c77fa748c8441cea9def1d35c7cd6d566829e0b74`
- 추출: `git -c core.autocrlf=false archive b1b7ad72 | tar -x -C build/review-trees/gc02`. probe는 `gc02-probe/`, 변이 사본은 `gc02-mut/`에 두었다. 작업 트리(G-P07·G-P15·G-P06b 변경 공존)는 쓰지 않았다.
- CI 근거는 `build/ci-evidence/g06-core3.11.log`·`g06-core3.13.log`를 읽기만 했다.
- 측정 중 다른 작업자의 pytest가 같은 PC에서 돌았다(CPU 약 40%).

### R3-2. 0.5초에서의 검출력(요청 1) — 직접 측정

`perf_mutants.py`(LF `145c02e6…7d08`, 결과 `perf_mutants.json` LF `290be600…6432`)로 PERF 두 행을 정상본·X1·X2 사본에서 각각 3회씩 실행했다. 한 번은 coverage 없이, 한 번은 CI와 같은 `--cov=recoryn --cov-branch`로 돌렸고, 시험이 출력한 JSON(`-s`)에서 관리 스레드 최대 보유를 읽었다.

| 변이 | 행 | coverage 없음(ms, 3회) | coverage 있음(ms, 3회) | 0.5초 판정 |
| --- | --- | --- | --- | --- |
| 정상본 | inventory-400 | 1.07 / 0.74 / 1.31 | 1.83 / 1.79 / 1.84 | PASS 6/6 |
| 정상본 | retry-10800 | 1.57 / 1.28 / 4.76 | 4.88 / 7.45 / 5.32 | PASS 6/6 |
| X1 폴더 제거를 `_remove_and_seal`의 mutex 안에서 | retry-10800 | 5,589.9 / 5,567.7 / 5,638.9 | 7,199.4 / 7,365.9 / 7,125.8 | **KILLED 6/6** |
| X2 `pending_deletions` 전체(선읽기·플래그·폴더 검사)를 mutex 한 구간으로 | inventory-400 | 278.9 / 203.9 / 205.6 | 406.7 / 354.5 / 279.7 | **SURVIVED 6/6** |

- 이전 상한 0.05초에서는 X2가 검출됐다(작성자 X2 0.314초, 1차 §4.6).
- X2의 보유 시간은 대기 기록 수에 비례한다. 400건에서는 큐 용량(1트랙 2.56초, 실제 앱 2트랙 약 1.28초)보다 작아 이 행에서는 유실을 만들지 않는다. 하지만 기록이 수천 건이면 같은 구조가 녹음 유실로 이어진다(G04-07·G05R-02와 같은 유형).
- CI 3.11의 실패 원인 보유(81.4ms)는 `_remove_and_seal`의 mutex 구간(journal 한 파일 확인 + 정리 transaction의 FULL 동기화 commit, 로그 stack `_remove_and_seal:1418`)이었다. 이 구간을 0.5초로 판정하는 것 자체는 타당하다.
- 같은 CI 실행의 그 행에서는 writer 자신의 append가 0.05~1.17초, seal이 0.95~1.12초씩 mutex를 잡았다. 거부 1,511블록, 유실 725,280/1,155,840프레임(63%)이었다. CI 러너에서는 녹음 처리량 자체가 실시간을 따라가지 못한다. 그래서 유실 수로는 관리 동작의 영향을 판정할 수 없고, 보유 시간 또는 구조로만 판정할 수 있다(G-P15 범위, 기록만).
- **구조 oracle 확인**(`structural_probe.py`, LF `f29cc6af…c7fb63d`): 관리 호출 중 현재 thread가 root mutex를 가진 상태(`_is_owned()`)에서 일어난 `Path.iterdir`·`remove_tree` 수를 셌다.

  | 사본 | inventory(400) iterdir owned / free | retry(10,800) iterdir owned / free, remove owned / free |
  | --- | --- | --- |
  | 정상본 | 0 / 1 | 0 / 3,606, 0 / 1 |
  | X1 | 0 / 1 | **3,604** / 2, **1** / 0 |
  | X2 | **1** / 0 | 0 / 3,606, 0 / 1 |

  시간과 무관하게 세 경우를 구분한다(한 파일 `exists`·읽기는 설계상 mutex 안에서 허용).

### R3-3. 같은 파일의 다른 CI 민감 단언(요청 2)

- **ORDER `two.join(0.3)`**(test_pending_deletion_restart.py:891): `waited = two.is_alive()`를 손 표와 비교한다. 기대 False인 4행(export·delete × new·pending × delete_first)은 상대 동작이 0.3초 안에 끝나야 통과한다. 부하가 큰 러너나 coverage 환경에서 thread 시작·export 거부·두 번째 delete 1단계가 0.3초를 넘으면 거짓 실패가 난다. 결정적인 대안: 기대 False 행은 `release.set()` 전에 `two.join(10)`으로 끝났음을 확인하고, 기대 True 행(recover·finalize)은 지금처럼 release 전 생존을 본다.
- 관리 동작 전체 300초 상한(:1134)과 각 `Event.wait(10)`, CRASH 120초, 자식 `wait(60)`은 여유가 크다.
- 같은 단위의 다른 파일: UI `test_uix_pending_query_runs_off_gui_and_older_results_never_win`의 `refresh_sessions()` 0.1초 상한(test_pending_deletion_ui.py:590)도 GUI thread의 동기 `list_sessions` 등이 포함된 실측 상한이라 느린 러너에서 민감하다. 의도는 "조회가 GUI thread에서 실행되지 않음"이며 이미 thread ID 단언(:604)이 있으므로, 시간 상한은 진단 기록으로 낮추는 방안을 권한다.

### R3-4. 새 발견

#### G05R-08 / S2 / OPEN — 0.5초 공통 상한에서 '목록 열거는 root mutex 밖'(X2)을 검출하는 시험이 없어진다

- **근거**: R3-2 표. 정상본 inventory 행의 관리 최대 보유는 coverage 포함 1.84ms인데, X2는 204~407ms로 0.5초 상한 아래에서 통과한다. X2는 G-P05 FIX 전 작성자 mutation의 C00 교훈 변이였다(1차 §4.6, 계약 §11.3 X2).
- **영향**: 누군가 목록 조회를 다시 한 mutex 구간으로 합쳐도 회귀 시험이 통과한다. 그 구조는 대기 기록 수에 비례해 녹음 유실을 일으키는 G04-07형 결함이다. 현재 제품 동작은 정상이고 시험의 검출력만 줄었으므로 S2로 분류했다.
- **기대(택1 또는 병행)**:
  1. 행별 상한: inventory 행은 mutex 안에 fsync·commit이 없으므로(정상본 최대 1.84ms) 예를 들어 0.1초를 쓰고, commit이 있는 retry 행만 0.5초를 쓴다.
  2. 구조 oracle: 관리 thread가 root mutex를 가진 동안 `iterdir`·`remove_tree`가 0회임을 단언한다. 시간 상한은 진단으로 남긴다. R3-2 probe가 정상본·X1·X2를 결정적으로 구분한다.
  3. inventory 행의 규모를 키워(예: 수천 건) X2 보유가 상한보다 충분히 크게 만든다. 단, 실행 시간이 늘어난다.
  - 어느 쪽이든 X1·X2 변이로 다시 검출을 확인한다.
- 참고: G-P04의 GT-P04 상한 0.5초에서 G-P04 관리 변이(MA·MB)가 여전히 검출되는지는 이 검토가 확인하지 않았다. G04 재확인 기록의 해당 변이 보유는 수 초 단위였다.

### R3-5. CI timeout 120분(요청 3) 의견

- **근거 수치**: 3.11 시험 단계 38분 28초(2,308.54초, 15,031 tests), 3.13 27분 54초(run 45190482741). G-P02 직후 3.13 10분 21초였으므로 하루 사이 약 2.7배가 됐다. 3.11이 느린 주원인은 `--cov --cov-branch`의 추적 비용으로 보인다(같은 시험이 3.13 대비 약 1.38배). 예정 행(G-P07 4,947, G-P09 3,812, G-P10 2,173 등 약 1.1만 행)이 G-P05와 비슷한 비용(이 PC에서 3,166행 약 100초)이라면 CI 3.11에서 수십 분이 더해질 것으로 추정한다. 측정은 아니다.
- **판단**: 120분은 당분간 시간 초과로 인한 취소를 막기에 충분하다. 다만 상한만 올리면 다음 위험이 있다.
  1. hang 한 번이 러너 2시간을 쓰고 원인 stack 없이 취소된다.
  2. 시간 증가가 실패로 드러나지 않아 예산 관리가 사라진다.
  3. 실시간 녹음·mutex 보유를 재는 시험이 느린 러너에서 더 자주 경계값에 닿는다.
- **권고**(설치 없이 가능한 것부터):
  - pytest 내장 `faulthandler_timeout`(예: 600초)으로 hang 시 stack을 남긴다.
  - job 대신 시험 step에 `timeout-minutes`를 둔다.
  - `--durations=30` 기록과 함께 job 시간 예산(예: 60분)을 넘으면 경고하는 확인 단계를 둔다.
  - coverage는 3.13 한쪽에서만 측정하고 3.11은 coverage 없이 실행해 호환성만 확인하는 분리를 검토한다.
- **병렬화 시점**: 3.11 단독이 60분을 넘거나 예산 경고가 반복되면 병렬화가 필요하다고 본다.
  - 먼저 디렉터리·marker 기준으로 job을 나누는 방식(예: unit·property·contract / integration / ui·e2e)이 새 의존성 없이 가능하다. coverage는 artifact로 합친다.
  - pytest-xdist 같은 프로세스 내 병렬화는 위험하다. windows-latest(4 vCPU)에서 TRACE(자식 최대 16)·CRASH(자식 24 동시) 같은 자식 프로세스 시험, 실시간 녹음 PERF·LIVE 시험과 겹치면 CPU 과다 할당으로 시간 민감 시험이 더 불안정해진다. 시간 민감 시험은 별도 marker로 묶어 직렬 job에 두는 것이 먼저다.

### R3-6. 결론

**GC-P02: 0.5초 상한의 retry 행 판정과 120분 timeout은 수용 가능하다. 새 OPEN 1 (S0 0 / S1 0 / S2 1 / S3 0) — G05R-08(0.5초 공통 상한에서 X2 변이 6/6 생존, 목록 열거 위치를 지키는 시험 소실).** ORDER 0.3초 join·UI 0.1초 상한은 CI 민감 단언으로 관찰에 기록했고 결함으로 세지 않았다. 수정·수용은 C00이 결정한다.

## RECHECK 4 (GC-P02 구조 판정) — 2026-11-24, G05R-08 수정 재확인

같은 검토자(Claude 하위 에이전트)가 C00의 구조 판정 추가를 확인했다. 위 내용은 이력으로 보존한다.

**요약: G05R-08 RECHECKED.** 현재 코드에서 구조 판정은 거짓 양성이 없고, X1·X2를 모두 결정적으로 검출한다. 전역 `Path.iterdir` 교체는 관리 스레드만 기록하며 다른 스레드의 동작을 바꾸지 않는다. 다만 판정이 감시하는 함수(`Path.iterdir`·`library_module.remove_tree`)에 묶여 있다. 그래서 열거를 `os.scandir`로 바꾸는 동등 리팩터(G-P15에서 생길 수 있음)만으로 판정이 조용히 무력화되고, 그 위의 X2형 회귀가 시간·구조 판정을 모두 통과한다. **새 OPEN 1 (S3) — G05R-09.**

### R4-1. 입력

- 대상 tree `fa2470ee3cad5d2d0c12b5ec15a975f383b80ca1`(tree)이고 기준 HEAD는 `68fbbda`다.
- `git diff --stat b1b7ad72 fa2470ee`는 시험 1파일 29+/2-다. workflow는 b1b7ad72와 같다.
  - `tests/integration/test_pending_deletion_restart.py` LF `1a5ddd4e0ece2429e624df0fd4df5f443b62c04fafdccfe472426137f2685f70`
  - `.github/workflows/core.yml` LF `367fed16c3ee5067f8a1508c77fa748c8441cea9def1d35c7cd6d566829e0b74`
  - 둘 다 C00 지정 값과 일치한다.
- 추출: `git -c core.autocrlf=false archive fa2470ee | tar -x -C build/review-trees/gc02b`. probe는 `gc02b-probe/`, 변이 사본은 `gc02b-mut/`에 두었다. 작업 트리는 쓰지 않았다.
- 측정: `perf_mutants2.py`(LF `2375da4d…94e8`, 결과 `perf_mutants2.json` LF `5a62998e…d4e2`). 변이마다 사본을 만들어 PERF 행을 coverage 없음 2회·CI와 같은 `--cov --cov-branch` 2회 실행하고, 시험이 출력한 JSON에서 관리 최대 보유와 `management_fs_under_mutex`를 읽었다.

### R4-2. X1·X2 직접 재적용(요청 3)

| 사본 | 행 | 관리 최대 보유 ms(nocov ×2 / cov ×2) | fs_under_mutex | 결과 |
| --- | --- | --- | --- | --- |
| 정상본 | inventory-400 | 0.94, 0.62 / 2.09, 1.24 | 0 | PASS 4/4 |
| 정상본 | retry-10800 | 1.70, 1.38 / 4.87, 7.26 | 0 | PASS 4/4 |
| X1 폴더 제거를 mutex 안에서 | retry-10800 | 5,052, 5,008 / 6,089, 6,805 | 3,605(remove_tree 1 + iterdir 3,604) | **KILLED 4/4** |
| X2 목록 전체를 mutex 안에서 | inventory-400 | 180, 172 / 377, 384 | 1(journal 열거) | **KILLED 4/4**(시간 상한만으로는 통과했을 값) |
| S0 journal 열거만 `os.scandir`로(동작 동일 리팩터) | inventory-400 | 0.67, 0.82 / 1.57, 1.85 | 0 | PASS 4/4 |
| S2 S0 + X2 | inventory-400 | 179, 176 / 333, 348 | **0** | **SURVIVED 4/4** → G05R-09 |

X2는 이제 구조 판정으로 검출되고, 시간 판정보다 먼저 실패한다. 수치는 C00 확인값(정상 1.1·2.4ms, X1 3,605회·7.36초, X2 1회·0.23초)과 같은 범위다.

### R4-3. 거짓 양성 여부(요청 1)

- `library.py`·`_safe.py`·`_coordination.py`·`chunks.py`의 `iterdir`·`remove_tree` 호출을 전수 확인했다.
  - G05 관리 경로(`pending_deletions`, `retry_deletion` → `_progress_deletion` → admission 없는 `_session_operation` → `_remove_and_seal`)에서 mutex 안에 들어가는 열거 후보는 둘뿐이다.
    - `_deletion_history()` 대체 재읽기(library.py:217의 journal 열거): 선읽기가 실패했거나, 그 사이 이 Library가 의도를 게시해 `_history_version`이 바뀐 경우에만 일어난다.
    - `_session_operation`의 `StateConflict` 처리기(:433의 `_deletion_intents()`).
  - 두 경로 모두 PERF 두 행에서는 생기지 않는다. 정상본 fs 0(이번 8회와 RECHECK 3 probe)과 일치한다.
  - 나머지 열거(:661-:984)는 G-P04의 복구·확정·미확정 목록 경로로, 이 시험의 관리 스레드가 부르지 않는다.
- 선읽기가 일시적 open 거부(G05R-04와 같은 현상)로 실패하면 mutex 안 재읽기가 실제로 일어나 판정이 실패한다. 그것은 실제 O(N) 보유이므로 진단으로 맞는 결과이며 거짓 양성으로 보지 않는다.

### R4-4. 전역 monkeypatch 부작용(요청 2)

- `note_fs`는 thread 이름이 `g05-management`이고, 그 thread의 meter 깊이(`local.depth`)가 0보다 클 때만 기록한다. 다음 호출은 지나가기만 하고 기록되지 않는다.
  - 녹음 writer의 `check_write_allowed`(블록마다 journal `iterdir`, _coordination.py:33)
  - writer `register_chunk`의 전체 journal 읽기
  - 시험 본체(MainThread)의 열거
- 교체 함수는 실제 `Path.iterdir`가 돌려준 iterator를 그대로 돌려준다. 동작 변화는 없고, 추가 비용은 호출당 thread 이름 비교 정도다.
- 적용 범위: `monkeypatch`는 이 시험 함수 동안만 프로세스 전체에 적용되고, writer join·Library 종료 뒤 teardown에서 되돌린다. CRASH·TRACE 자식 프로세스에는 영향이 없다.
- Python 버전 차이: 이 PC에서 소스로 확인했다.
  - 3.13.1의 `Path.iterdir`는 `os.scandir`를 즉시 실행한다.
  - 3.11.18은 `os.listdir`를 쓰는 지연 generator다.
  - 기록은 `iterdir()` 호출 시점에 한다. 이 코드에서는 생성과 순회가 같은 블록이라 두 버전 모두 결과가 같다.

### R4-5. G-P15 이후 유효성(요청 4) — G05R-09

#### G05R-09 / S3 / OPEN — 구조 판정이 감시 함수에 묶여, 열거 API만 바꾼 리팩터에서 조용히 무력화된다

- **근거**: 판정은 `Path.iterdir`과 `library_module.remove_tree` 호출만 센다(test_pending_deletion_restart.py의 `counted_iterdir`·`counted_remove_tree`).
  - R4-2의 S0은 동작이 같은 리팩터(`os.scandir`로 journal 열거)인데 PASS하면서 fs 0이다.
  - 그 위에 X2를 얹은 S2는 보유 176~348ms·fs 0으로 **4/4 통과**한다.
  - G04-07 검토는 `os.scandir` 사용을 권고했고, G-P15 '삭제 의도 색인'은 바로 이 journal 읽기를 다시 짠다. 감시가 실제 열거를 보고 있는지 확인하는 장치가 없으면, 같은 변경으로 X2형 회귀가 다시 시험을 통과할 수 있다.
- **기대**:
  1. **양성 대조**: 관리 스레드의 mutex 밖 열거·제거도 세서, 각 행에서 0보다 큼을 단언한다. 정상본에서 inventory 행은 journal 선읽기 1회, retry 행은 iterdir 3,606회다. 열거 방식이 바뀌면 이 단언이 먼저 실패해 감시 대상을 고치게 만든다.
  2. 감시를 하위 수준(`os.scandir`·`os.listdir`, 필요하면 `shutil.rmtree`)으로 넓힌다. 3.11의 `Path.iterdir`(`os.listdir`)와 3.13(`os.scandir`)을 모두 덮는다.
  3. G-P15 검토에서 X1·X2와 위 S2형 변이를 다시 실행한다.
  - G-P15가 색인을 처음 사용할 때 mutex 안에서 전체 journal을 읽어 만들도록 설계하면, 이 판정은 그것을 실패로 잡는다. 그 실패는 O(N) mutex 보유라는 맞는 신호이므로 상한을 완화하지 말고, 색인을 open 시점이나 mutex 밖 선읽기로 만드는 쪽이 맞다.
- **등급**: 현재 tree에서는 X1·X2가 검출되고 제품 동작도 정상이다. 앞으로의 리팩터에 대한 시험 견고성 문제이므로 S3로 분류했다.

### R4-6. 결론

**G05R-08 RECHECKED. 새 OPEN 1 (S0 0 / S1 0 / S2 0 / S3 1) — G05R-09(구조 판정의 감시 함수 고정, 양성 대조 없음; S2형 변이 4/4 생존).** 0.5초 시간 상한·50ms 진단·workflow 120분은 RECHECK 3 판단 그대로다. G05R-02·04(기존 S1)는 G-P15 범위로 OPEN이다. 수정·수용은 C00이 결정한다.

## RECHECK 5 — 2026-11-24, G05R-09 수정 재확인

같은 검토자(Claude 하위 에이전트)가 짧게 확인했다. 위 내용은 이력으로 보존한다.

- **입력**: tree `ef6709a5f4d4bda3ee3d46a595b1c0f6b5974893`(tree)이고 기준 HEAD는 `68fbbda`다. `git diff --stat fa2470ee ef6709a5`는 시험 1파일 24+/3-다. 시험 LF `865e8fc229f54877ef07b37fd60c32f6e61d30da03cfa58939ca5d266c93fc46`, workflow `367fed16…9e0b74`로 지정 값과 일치한다. `build/review-trees/gc02c`에 풀어서 판정했다.
- **변경**: 감시 대상에 `os.scandir`·`os.listdir`를 더했다(관리 스레드 이름 필터는 그대로). 관리 스레드의 mutex 밖 폴더 작업 횟수 `management_fs_outside > 0`을 구조 판정보다 먼저 단언한다.
- **재실행**: RECHECK 4와 같은 앵커의 `perf_mutants3.py`(LF `ea400a7a…f6d4`, 결과 `perf_mutants3.json` LF `7ad7c123…dfe6`)로 coverage 없음·있음 각 1회 실행했다.

| 사본 | 행 | 관리 최대 보유 ms(nocov / cov) | mutex 안 / 밖 | 결과 |
| --- | --- | --- | --- | --- |
| 정상본 | inventory-400 | 0.87 / 1.97 | 0 / 2 | PASS |
| 정상본 | retry-10800 | 1.69 / 2.15 | 0 / 7,211 | PASS |
| X1 | retry-10800 | 5,450 / 6,967 | 7,209 / 2 | KILLED 2/2 |
| X2 | inventory-400 | 231 / 379 | 2 / 0 | KILLED 2/2 |
| S0 scandir 리팩터만 | inventory-400 | 0.80 / 1.91 | 0 / 1 | PASS 2/2 |
| S2 scandir + X2 | inventory-400 | 205 / 374 | 1 / 0 | **KILLED 2/2**(직전 4/4 생존) |

C00 확인값과 같다. 3.13에서 `Path.iterdir`는 내부에서 `os.scandir`를 부르므로 한 번의 열거가 2회로 세어진다(inventory 밖 2, retry 밖 7,211 = iterdir 3,606 + scandir 3,605). 판정은 0과 0보다 큼만 보므로 영향이 없다.

- **양성 대조가 정상 경로에서 0이 될 수 있는가**: 이 두 PERF 행에서는 생기지 않는다.
  - 두 행 모두 관리 호출이 처음에 mutex 밖 `_journal_prefetch` → `_read_journal`로 journal 폴더를 열거한다. 셈은 항목 수가 아니라 호출 기준이므로 목록이 비어도 1 이상이다.
  - retry 행은 여기에 더해 mutex 밖 `remove_tree`가 있다.
  - 0이 되는 경우는 journal 폴더가 없을 때뿐이다(`_read_journal`이 `is_dir()` 검사에서 열거 전에 실패). 그때는 `pending_deletions`·`retry_deletion`이 이력 확인 불가로 실패하므로 앞의 `result.get("ok")` 단언이 먼저 실패한다.
  - 3.11의 지연 generator(`os.listdir`)도 순회가 같은 블록의 mutex 밖에서 일어나므로 결과가 같다.

**판정: G05R-09 RECHECKED. 새 OPEN 0.** G05R-02·04(기존 S1)는 G-P15 범위로 그대로 OPEN이다.
