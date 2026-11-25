# GS02R / GS-P02 삭제 의도 색인 실패 cache·settle 독립 검토

상태: **REVIEW_READY — 독립 검토 1차, 2026-11-25.** 작성자는 w5:p8 Codex이고, 검토자는 C00이 배정한 하위 에이전트(Claude, G-P15·G-P15b 검토자)다. 검토자는 코드를 고치지 않았다. 저장소 쓰기는 이 문서 하나다. 반례·측정·변이 스크립트는 `build/review-trees/gs02a-probe/`에 있다. 변이 사본은 `build/review-trees/gs02a-mut/`, 비교용 HEAD 사본은 `build/review-trees/gs02a-head/`다. 최종 수용과 push 게이트 판단은 C00이 한다.

**요약.**
- 확인 수단: 코드 읽기, CI와 같은 전체 회귀(22744 PASS, coverage 92.33%, 7묶음 PASS), 검토자 probe 7종, HEAD `31bc88b` 대조 측정, 검토자 변이 8종.
- **G15R-05는 RECHECKED**다. 같은 tick 외부 변경 두 번 + 3초 선읽기 조건에서 의도 뒤 append가 거부된다.
- 승인 A안의 핵심 규칙은 실제 NTFS에서도 지켜진다: settled 실패만 재사용, 미래 mtime fail closed, fresh 관리 조회의 우회·수선, capture 미적용.
- **OPEN은 S2 2건·S3 1건이고, S0·S1은 없다.**
  - GS02R-01(S2): 한 번의 일시 I/O 오류가 `_live`·Job 경로의 고착 실패가 된다.
  - GS02R-02(S2): 외부 손상 직후 settle 전 창의 반복 cold 검증이 2트랙 녹음 블록을 거부시킨다. 승인된 잔여지만 녹음과 겹친 측정이 없었다.
  - GS02R-03(S3): 동시 fresh 관리 조회 때 Job 권위가 거짓 `HISTORY_UNAVAILABLE`을 낸다.

## 1. 입력 고정

| 항목 | 값 |
| --- | --- |
| 대상 | tree `4a6b29533bded04831d8aa68c09eb502abbbeaa3`(`git cat-file -t` = tree) = HEAD `31bc88b`(G-P08) + 4파일. `git diff 31bc88b 4a6b2953 --stat` = 4파일 1174+/96- |
| 추출 | `git archive 4a6b2953 \| tar -x -C build/review-trees/gs02a`. 비교용 `git archive 31bc88b` → `gs02a-head`. 변이 사본 `git archive 4a6b2953 pyproject.toml src tests` → `gs02a-mut` |
| 4파일 LF SHA256 | library.py `572094e82c5a25bd…2966`, test_index_failure.py(unit) `1f452fd37261dbaf…796b`, test_index_failure.py(integration) `1b831a5e0ee672bb…3590`. 계약 문서 §14.5 표와 일치. 문서 `gs02-index-failure-cases.md` LF `353e9d1bf112a8223ae9e0e4317491946cfafa6ce7c1f03ee2a20c9bf2f442b3`(299행) |
| 환경 | Windows 11 Pro 10.0.26300, `.venv` Python 3.13.1, offscreen Qt. 실제 장치·모델·네트워크·유료 호출·Credential Manager 쓰기 없음. 종료한 프로세스는 검토자 스크립트가 만든 자식뿐 |

과정 고지: 첫 경쟁 probe(GS02R-03)를 전체 회귀가 도는 동안 실행했다. 전체 회귀는 그래도 실패 0이었다. 측정 표(§4)와 GS02R-03의 판정 값은 다른 실행이 없을 때 순차로 다시 잰 값이다. 동시 실행 값은 따로 표시했다.

## 2. 직접 실행한 명령과 결과

| # | 명령(사본 `gs02a`, `.venv` Python) | 결과 |
| --- | --- | --- |
| J1 | CI core와 같은 `python -m pytest -q -p no:cacheprovider -W error::ResourceWarning --cov=recoryn --cov-branch --cov-report=term-missing --cov-report=json:coverage.json --cov-fail-under=85`, `PYTHONPATH=gs02a\src`(자식도 사본 import, 보고서에 `D:\project\Recoryn\src` 경로 0건), 고유 `TEMP`(`C:\Users\gangd\AppData\Local\Temp\gs02r-full-…`)·`--basetemp`, offscreen | **22744 passed / failure 0 / error 0 / skip 0, 1512.82s, exit 0, 전체 coverage 92.33%**. JUnit LF `bde43c3973c5bcb0b498bc54abb566e434771df4137ded33f13db24f8ccaf1b7`, 로그 LF `6cd40b899114fc34e5896012675a3db2ac85e6c7116e6a90c33b7659128a572c`, `coverage.json` LF `b491598aa1b3e758b28058df7a1d9e9afd4fac5537eeb4db7d5bc1cb2c99890c` |
| J2 | `python scripts/check_coverage.py coverage.json` | **전 묶음 PASS**: domain 99.18·97.89, capture 99.85·98.57, jobs 99.29·96.23, storage 96.05·91.43, security 98.11·94.43, content 99.59·98.75, all 93.72·88.24(line·branch %). 작성자 §14.2와 같다 |
| J3 | `ruff check --no-cache src tests scripts packaging` / `ruff format --no-cache --check …` / `MYPYPATH=src python -m mypy --no-incremental src/recoryn scripts packaging` | All checks passed / 193 files already formatted / **91 source files no issues** |
| J4 | 검토자 probe(§3·§4), 모두 `-I`로 실행하고 대상 src를 `sys.path[0]`에 넣었다 | 아래 |
| J5 | `mutate_gs.py ../gs02a-mut mutations.jsonl`(검토자 변이 8종, `PYTHONPATH`=사본 src) | §5. 결과 LF `f7ea0a62b4136dd5ebe2200e71d402998c1e6a00ae70a91609c85e4b6f32344e`. 변이마다 library.py hash가 원본 `572094e8…`으로 복원됐다 |

probe(`build/review-trees/gs02a-probe/`, LF SHA256 앞 16자):

| 파일 | 목적 | LF SHA256 |
| --- | --- | --- |
| `probe_job_authority_settle2.py` | G15R-05 재실행(선읽기 wrapper만 새 시그니처) | `054c0d9489f62148` |
| `probe_cache_rules.py` | 미래 mtime·settled 재사용·같은 stamp 수선·capture 미적용(실제 NTFS) | `c6cfbfc466cbe8b1` |
| `probe_transient_failure.py` | GS02R-01 | `c4cc147d0f8eccfe` |
| `probe_g05r02_gs.py`, `run_measure.sh` | GUI tick 보유·녹음·관리 측정(G05R-02 조건 + 외부 손상) | `ffe85402c7f7fb1b` / `39eea07e22f682bf` |
| `probe_authority_contention.py` | GS02R-03 | `4eb952ba28065750` |
| `mutate_gs.py` | 검토자 변이 | `4702af009119ccce` |

G15 검토 때의 probe(`build/review-trees/g15a-probe/probe_delete_full_fifo.py`, `probe_crash_full_fifo.py`)도 이 tree에서 다시 돌렸다(§3.4).

## 3. 요청별 판정

### 3.1 G15R-05(요청 1): **RECHECKED**

`probe_job_authority_settle2.py`의 순서는 다음과 같다.
1. 녹음 세션 `rec`의 writer가 열려 있다.
2. 외부에서 `ext.json`을 추가한다.
3. `job_authority`가 선읽기를 한다. 목록을 만든 뒤, 같은 tick에 외부가 `rec.json`을 추가한다(`os.utime`로 mtime 복원). 선읽기는 3초 걸린다.
4. writer가 append한다.

| tree | 색인 settled | 다음 append |
| --- | --- | --- |
| HEAD `31bc88b` | True | **ACCEPTED(I1 위반)** |
| GS-P02 | **False** | 거부 `Writer session has a deletion intent` |
| GS-P02 control(`job_authority` 없음) | — | 거부 |

근거: `_journal_prefetch`(library.py:430-463)가 stamp를 읽은 직후, 열거 전에 `started`를 잰다. settled는 `started - mtime > 2.5초`일 때만 참이다. `_accept_observation`(:477-495)은 게시 때 version·epoch·현재 stamp를 다시 대조한다. 변이 G1(완료 뒤 시각으로 settle)은 J 14행이 잡았다(§5).

### 3.2 실패 cache 규칙(요청 2)

`probe_cache_rules.py`(실제 디렉터리 mtime, fake clock 없음, tombstone 20 + 미인식 `zz.txt`):

| 경우 | 관찰 | 판정 |
| --- | --- | --- |
| journal mtime 1시간 미래 | `get_session` 5회 모두 `DELETION_HISTORY_UNAVAILABLE`, 본문 검증 **5회**(재사용 없음) | 미래 mtime fail closed·비재사용 ✓ |
| mtime 60초 전(settled) | 5회 모두 거부, 본문 검증 **0회**(열 때의 실패 memo 재사용) | settled 실패만 hot ✓ |
| settled 뒤 `zz.txt` 제거 + mtime 복원(같은 stamp) | `get_session`은 계속 거부. `list_sessions`(fresh) **OK**, 그 뒤 `get_session` **OK** | fresh 관리 조회가 우회·수선 ✓ |
| settled 실패 memo 상태에서 live 세션 `ChunkWriter.append` | **OK**(memo settled=True) | capture 미적용 ✓ |

- 같은 tick 변경: G15R-05 행(§3.1)과 작성자 J·I family의 fake clock 행으로 확인했다.
- `.tmp`는 capture에서도 거부된다(작성자 C 행, G15 `test_storage.py` writer 행이 J1에서 통과).
- 판정: 승인된 규칙은 지켜진다.
- 예외: 일시 I/O 오류를 지속 실패와 같이 cache하는 점이다(GS02R-01).

### 3.3 GUI tick 보유 재측정(요청 3)

조건: 완료 삭제 1,000건(settled), 녹음 3초 뒤 journal에 정렬상 마지막 미인식 항목(`zzzz-unknown.txt`)을 추가한다. 250ms GUI tick 대리(`chunks()`), 12초 실시간. HEAD와 GS-P02를 같은 스크립트로 번갈아 순차 실행했다.
- 결과 `measure.jsonl` LF `5c48cce6c302546eebae3c057172e75ce3ebe8077df42a634ac7edb86959fc61`
- 반복 `measure2.jsonl` LF `d77027e0cd1cdd1baf2c430ba0d6c16b1526db3494a291f42b329731b33854d0`

| tree | 트랙 | tick root 보유 p50 | 50ms 이상 보유 수 / 상위 | 거부 블록 | 녹음 |
| --- | ---: | ---: | --- | --- | --- |
| HEAD | 1 | 554.9ms | 17 / 652·655·665ms | 62 | 계속(`storage_failed` 거짓) |
| GS-P02 | 1 | **0.65ms** | **4** / 553·576·706ms | **0**, 반복 0 | 계속 |
| HEAD | 2 | 524.3ms | 18 / 593·605·657ms. 반복 14 / 589·589·591ms | 1,078, 반복 26 | 계속 |
| GS-P02 | 2 | **0.5~0.7ms** | **4** / 539·554·555ms. 반복 4 / 546·571·583ms, 4 / 543·577·586ms | **229, 15, 12** | 계속 |
| (참고) G15 사본 g15a | 2 | 413.3ms | 15 / 556·578·587ms | 4(1차 검토 때 0) | 계속 |

- 결론: hot 반복 비용(0.5~0.6초 → 1ms 미만)은 해소됐다.
- 남은 것은 외부 변경 직후 settle 전 약 2.5초 동안의 cold 전체 검증 4~5회(각 0.41~0.71초, root mutex 안)다. 이 창이 2트랙 녹음과 겹치면 블록 거부가 난다 → GS02R-02.
- `stop()`은 HEAD와 같이 이 상태에서 `DELETION_HISTORY_UNAVAILABLE`이다(fail closed, 이 단위의 변경 아님).

### 3.4 I1·원본 부활·녹음 거부(요청 4)

| 측정 | HEAD | GS-P02 |
| --- | --- | --- |
| N=1000 + tick + 관리 작업(4초에 `list_sessions`·`pending_deletions`·`unfinished_sessions`, 8초에 다른 세션 삭제), 1트랙 | 거부 0, 관리 root 최장 14.1ms | **거부 0**, 관리 root 최장 18.3ms, tick 최장 3.4ms |
| 같은 조건, 2트랙 | 거부 0, 관리 17.8ms | **거부 0**, 관리 19.2ms, tick 3.0ms. 소비자 최장 93.2ms(측정만) |
| N=0, 2트랙 + tick | 거부 0 | 거부 0 |
| FIFO에 청크가 쌓인 live 세션 삭제(`probe_delete_full_fifo.py`, 1·2트랙) | — | 첫 답 `DELETE_PENDING(SESSION_LIVE)`, 의도 뒤 게시·등록 0/0, 재시도 `DELETED_LOCAL`, 폴더 없음, 복구 `DELETE_PENDING`·폴더 재생성 없음 |
| FIFO 4 + sealing 상태 kill 뒤 복구(`probe_crash_full_fifo.py`, 2트랙) | — | 트랙별 9블록 바이트 일치·연속, 재복구 0 |

- 모든 측정 행에서 저장 프레임 = (제출 − 거부) × 480이었다.
- I1·원본 부활 0이 유지된다. 정상 상태(손상 없음)의 녹음 거부도 0이다.

### 3.5 정상 claim O(N)과 GUI `list_sessions` 460ms(요청 5) — 의견

- **현재 심각도: S3(성능 부채)**. 이 단위의 결함으로 보지 않는다.
  - 근거 1: 비용은 root mutex 밖이다. N=1000에서 관리 작업을 녹음과 겹쳐도 거부 0이었다(§3.4). G-P15b 재확인에서도 Job 전이 반복 중 거부 0, Job 스레드 root 최장 3.7ms였다.
  - 근거 2: 같은 stamp 안 본문 손상 검출(G-P07 시험)을 지키기 위한 의도된 비용이다.
- **S2로 커지는 조건**:
  - GUI thread의 `list_sessions`(`_render_sessions`)가 0.46~0.8초 화면을 멈추는 것(GS-P01 범위).
  - tombstone이 수천 건으로 늘어나는 경우. 보존 정책 G-P14가 삭제를 자동화하면 늘어난다. 그러면 Job 전이마다 수 초가 걸리고, mutex 밖 Python 파싱이 GIL을 오래 잡아 2트랙 소비자 여유를 줄인다.
- **해결 방향**(같은 stamp 손상 검출을 유지하는 순서):
  1. **단기 — 항목 metadata 지문**: 검증 성공 때 각 journal 항목의 (크기, `st_mtime_ns`, 파일 ID)를 함께 기록한다. 이후 Job·관리 입장은 root 밖에서 항목별 `stat`만 대조하고(1,000건 수 ms 수준), 지문이 바뀐 항목만 다시 파싱한다. 제자리 다시 쓰기는 파일 자체의 mtime·크기를 바꾸므로 G-P07 시험의 "같은 디렉터리 stamp 아래 본문 손상"을 계속 잡는다. 한계는 mtime까지 되돌리는 도구이므로, 그 한계를 계약으로 적는다.
  2. **열 때·주기 전체 검증**: 앱 열기와 일정 주기(예: idle일 때 수 분마다)에 root 밖 worker가 전체 본문 검증을 해서 1의 지문 정본을 갱신한다. 검출 지연의 상한이 생긴다.
  3. **장기 — 완료 tombstone을 per-call 파싱 대상에서 빼기**: journal에는 진행 중 의도만 남긴다. `DELETED_LOCAL` 이력은 DB 행과 checksum 있는 단일 tombstone ledger(또는 DB 손실 대비 서명 manifest)로 옮겨 N을 "진행 중 삭제 수"로 줄인다. 영속 형식·backup(G-P09)과 G-P05 "라이브러리 수명 동안 journal 보존" 계약의 변경이라 별도 계약이 필요하다.
  4. GUI `list_sessions`는 GS-P01 worker read model로 옮긴다(위 1~3과 독립).
- 1을 택해도 실패 memo(이 단위)와 capture 경로 규칙은 그대로 둘 수 있다.

## 4. 발견

### GS02R-01 (S2, OPEN) — 한 번의 일시 I/O 오류가 settled 실패 memo로 고착돼 `_live`·Job 경로가 계속 거부된다

- 근거:
  - `_journal_prefetch`(library.py:449-454)는 `_read_journal`의 모든 `ValueError`·`OSError`를 같은 실패 관찰(journal None)로 만든다. stamp가 settled면 `_accept_observation`이 `_intent_failure`로 게시한다.
  - 그 뒤 `_indexed_journal`(:549-)·`_journal_prefetch(fresh=False)`(Job)는 `_failure_current()`가 참인 동안 다시 읽지 않고 거부한다.
  - 해제 조건은 stamp·version 변경, fresh 관리 조회 성공, 다시 열기뿐이다.
  - 그래서 G05R-04에서 관측된 종류의 **일시 공유 거부**(스캐너·백업 도구가 파일을 잠깐 잡는 `PermissionError`)도 지속 손상과 같이 고착된다.
- 재현(`probe_transient_failure.py`, 완료 삭제 50건 settled, `t0025.json` 읽기 한 번만 `PermissionError`):

  | 지점 | tree | 이후 `get_session`×5 | `chunks`×5 | 새 세션·녹음 시작 | 녹음 중 `RecordingService.stop()` | `list_sessions`(fresh) 뒤 |
  | --- | --- | --- | --- | --- | --- | --- |
  | 열 때 | HEAD | OK×5 | OK×5 | OK | OK | — |
  | 열 때 | GS-P02 | **거부×5** | — | **`create_session`·`RecordingService` 생성 거부** | — | `create_session` OK |
  | 외부 변경 뒤 재검증 | HEAD | 첫 1회만 거부, 이후 OK | OK×5 | — | OK | — |
  | 외부 변경 뒤 재검증 | GS-P02 | **거부×5** | **거부×5** | — | **`DELETION_HISTORY_UNAVAILABLE`** | `get_session`·`stop()` OK |

- 영향:
  - fail closed라 I1·원본에는 위험이 없다. 녹음 쓰기도 계속된다(capture는 memo를 보지 않음).
  - 그러나 다음 fresh 관리 조회 전까지 새 녹음 시작(CLI `record`처럼 열자마자 세션을 만드는 경로), 녹음 정지, GUI tick, Job 전이가 실패한다.
  - GUI 시작은 목록 새로고침(`list_sessions`)이 곧 지울 수 있다. CLI와 녹음 중 정지는 사용자가 새로고침하거나 다시 실행해야 한다.
  - 우회는 가능하다. 계기는 드물다(G05R-04: 프로세스 간 1회 관측). 그래서 S2로 본다.
- 기대: 실패 memo는 결정적인 내용 실패에만 둔다(`ValueError` 계열: 손상 JSON·schema·미인식 이름·`.tmp`·이름 불일치). 그러면 hot 비용 해소와 고착 회피를 함께 얻는다. `OSError`는 다음 중 하나로 다룬다.
  - (가) 지금처럼 매 호출 다시 검증한다(fail closed 유지).
  - (나) 짧은 연속 실패 횟수나 시간 조건을 넘을 때만 memo로 승격한다.
  - 계약 N family의 "본문 PermissionError"는 지속 거부만 모형화했다. 일시 거부 행(한 번 실패 → 다음 호출 회복)을 분모에 더해야 한다. C00 승인 범위(권한 수선은 보수적으로 실패 유지)와 겹치므로 결정이 필요하다.

### GS02R-02 (S2, OPEN) — 외부 손상 직후 settle 전 창의 반복 cold 검증이 2트랙 녹음 블록을 거부시킨다

- 근거:
  - settle 전 실패는 재사용하지 않는다(계약 §3.3 "아직 settle 전 실패 → settled 실패 cache로 재사용하지 않음"). 그래서 외부 변경 뒤 약 2.5초 동안 GUI tick의 `_live`마다 `_refresh_intent_index` → `_journal_prefetch(fresh=True)`가 **root mutex 안에서** 전체 본문 검증을 한다.
  - 승인된 A안의 "cold·settle 전 비용 잔여 수용" 범위다. 작성자 측정(§14.4)은 cold를 PCM 제출 전에 했으므로 녹음과 겹친 영향은 재지 않았다.
- 재현(§3.3 표): N=1000, 2트랙.
  - tick 보유 4~5회가 0.41~0.71초다. 거부 **229·15·12블록**, 저장은 (제출 − 거부)와 일치한다.
  - 1트랙은 0·0이다. HEAD는 같은 조건에서 26·1,078블록(전 구간 반복)이다.
- 영향:
  - 녹음 유실(`QUEUE_DROP` 기록)이다. 다만 전제가 단일 writer 계약 밖의 외부 journal 손상이다(디스크 오류, 사용자·도구가 넣은 파일, 동기화 도구의 충돌 사본 등). 유실은 그 뒤 약 2.5초 창으로 한정되고, HEAD보다 크게 줄었다.
  - 그래서 S1이 아닌 S2로 기록한다. 외부 손상 계기를 현실적이라 보면 S1로 올릴지 C00이 판단해야 한다.
- 기대·대안: settle 전에도 **같은 stamp이고 이름 목록이 같으면** 실패 관찰을 재사용한다. 이름 목록은 `os.scandir` 1회, 1,000건 약 0.7ms다.
  - 실패 재사용은 언제나 fail closed 쪽이라 I1을 약하게 하지 않는다.
  - 같은 tick의 이름 수선(손상 항목 제거)은 이름 비교로 보인다.
  - 제자리 내용 수선은 settled 경우와 같이 fresh 관리 조회·다시 열기로 반영된다.
  - 이렇게 하면 cold 검증은 첫 1회만 남는다. 그 1회도 줄이려면 대안 B(root 밖 검증)가 필요하다.

### GS02R-03 (S3, OPEN) — 동시 fresh 관리 조회가 있으면 Job 권위가 재시도를 소진해 거짓 `HISTORY_UNAVAILABLE`을 낸다

- 근거:
  - `job_authority`(library.py:313-330)는 `_accept_observation`이 거절하면 다시 선읽기해 3회까지 재시도한다.
  - `_accept_observation`은 자기보다 늦게 시작한 관찰이 먼저 게시되면(`observed.epoch < _published_observation`) 거절한다.
  - `_deletion_history`는 이 경우 "같은 version·stamp의 더 새 검증 결과를 그대로 쓴다"(:649-660)가, `job_authority`에는 그 분기가 없다.
  - 그래서 `list_sessions`·`pending_deletions` 같은 fresh 조회가 겹치면 Job의 O(N) 선읽기가 반복되고, 3회 안에 이기지 못하면 이력이 그대로인데도 `HISTORY_UNAVAILABLE`이 된다.
  - HEAD `31bc88b`의 `job_authority`는 내부 의도 게시(version 변경)에서만 재시도했다.
- 재현(`probe_authority_contention.py`, 완료 삭제 1,000건, 세션 `s` 유효, `job_authority(db, "s")` 20회 + `list_sessions` 루프 thread):

  | readers | HEAD | GS-P02 |
  | ---: | --- | --- |
  | 1 | VALID 20(21.98s) | VALID 20(22.73s) |
  | 2 | VALID 20(26.40s) | VALID 20, **42.15s**(재시도로 느려짐). 전체 회귀와 동시 실행 때는 **HISTORY_UNAVAILABLE 2/20** |
  | 3 | VALID 20(48.59s) | **HISTORY_UNAVAILABLE 1/20**, VALID 19 |

  결과 LF `a665e033443411952f7bc071ddaa06091bac94d60937e2c535bd8de367be0ec2`.
- 영향: 녹음·원본과 무관하다. AI Job 전이가 삭제 이력 확인 불가로 거부·차단된다. 목록 새로고침 중에 AI 작업이 돌면 드물게 생긴다. 재시도나 새로고침으로 회복된다. S3.
- 기대: `job_authority`도 같은 version·stamp에서 더 새 관찰이 성공으로 게시돼 있으면 그 결과(더 최근에 시작한 전체 검증이라 신선도 요구를 만족한다)로 답한다. 실패로 게시돼 있으면 그 실패로 답한다. 그러면 거짓 거부와 중복 O(N) 읽기가 함께 없어진다.

## 5. mutation(요청 7, J5)

대상: 신규 2파일 + `tests/integration/test_blocked_reason_flow.py`(G-P07 권위 시험) 651 node. G6만 G15 2파일(실시간 행 제외)을 더해 802 node로 돌렸다.

| ID | 변이 | 결과 | 잡은 node(대표) |
| --- | --- | --- | --- |
| G1 | 관찰 settle을 읽기 완료 시각으로(G15R-05 종류) | 검출 14 | GS02-J-019~ |
| G2 | 관리 실패 memo를 capture(`_writer_intent`)에도 적용 | 검출 29 | GS02-L-029, GS02-C-001~ |
| G3 | settle 전 실패도 memo 재사용 | 검출 30 | GS02-N-002~ |
| G4 | `list_sessions`가 fresh가 아님(memo 재사용) | 검출 16 | GS02-I-025~(수선 반영) |
| G5 | 실패 memo가 stamp 변경을 무시 | 검출 6 | GS02-I-009·010, GS02-L-008·009 |
| G6 | 게시 때 history version 대조 제거 | 검출 21 | GS02-J-003~ |
| G7 | 선읽기 뒤 이름 목록 재대조(`listed != names`) 제거 | **생존** | — |
| G8 | settled 실패 memo가 있어도 `_live`가 매번 재검증 | 검출 27 | GS02-N-008~ |

G7은 동등 변이로 판단한다. 선읽기 중 이름이 바뀌는 경우는 다음 셋 중 하나가 막는다.
- in-process 게시: version 대조.
- 다른 tick의 외부 변경: 게시 때 stamp 대조.
- 같은 tick의 외부 변경: 그 관찰이 settle 전이 되어 다음 `_index_current`가 이름을 다시 본다.

방어 중복이다. 작성자 변이 18종은 실행하지 않았다(작성자 기록만 읽음).

## 6. 남는 위험과 놓쳤을 수 있는 영역

- CI 러너(3.11·3.13) 실행은 하지 않았다.
- 시간 경계(정확히 2.5초, ±1ns)는 작성자의 fake clock 행에 기댔다. 실제 NTFS에서는 미래·60초 전 mtime만 확인했다.
- 외부 손상 상태의 첫 cold 검증(1회 0.4~0.7초)은 GS02R-02의 대안을 써도 남는다. 대안 B(root 밖 검증) 또는 GS-P01 범위다.
- `job_authority`는 호출자의 JobStore transaction(commit 포함)이 끝날 때까지 root mutex를 쥔다(G-P07 계약 그대로). 이 PC에서는 짧았다(G-P15b 재확인 최장 3.7ms). 느린 디스크에서는 commit 지연을 그대로 따른다.
- 다중 프로세스, FAT·exFAT·네트워크 볼륨의 settle은 G15 이래 미검증 한계 그대로다.
- §3.5의 성능 방향은 의견이다. 실제 구현·측정은 하지 않았다.

## RECHECK 1 (GS-P02 FIX1)

상태: **RECHECKED — 독립 재확인 1차, 2026-11-25.**
- 작성자는 w5:p8 Codex, 검토자는 1차와 같은 C00 배정 하위 에이전트(Claude)다. 코드는 고치지 않았다. 저장소 쓰기는 이 절 추가뿐이다.
- probe·변이 스크립트는 `build/review-trees/gs02b-probe/`, 변이 사본은 `build/review-trees/gs02b-mut/`에 있다. 1차 probe(`gs02a-probe/`)는 대상 src만 바꿔 다시 실행했다.

**판정 요약.**
- GS02R-01(C00이 S1로 올림)·GS02R-02·GS02R-03은 모두 **RECHECKED**(해소)다.
- G15R-05도 계속 해소 상태다. 내용 손상은 계속 fail closed다.
- **새 OPEN은 0건**이다(S0·S1·S2·S3 모두 0).
- 남는 위험: 지속되는 I/O 오류 동안은 호출마다 cold 재검증이 일어난다. C00 결정(호출마다 fail closed)의 대가이며, R1.6에 측정값으로 남긴다.

### R1.1 입력 고정

| 항목 | 값 |
| --- | --- |
| 대상 | tree `1f432417f25c2b2a25d8640344cadc7486698b63`(`git cat-file -t` = tree) = HEAD `31bc88b` + 4파일. 직전 tree 대비 `git diff 4a6b2953 1f432417 --stat` = 4파일 449+/28- |
| 4파일 LF SHA256 | library.py `7e9a1c126409bfdd…8f79`, unit 시험 `d01155a3bd55e45a…c637`, integration 시험 `28ce40270ba97a9c…8485`, 문서 `1ad96627044304c0…6f02`(§16 포함). 배정 값과 일치 |
| 추출 | `git archive 1f432417 \| tar -x -C build/review-trees/gs02b`, 변이 사본 `git archive 1f432417 pyproject.toml src tests` → `gs02b-mut` |
| 이 문서 | 이 절을 붙이기 전 LF `fb00d48024fd0bbfa2cfcecc2340ec8e56f4bc4592b9793d3222d294b38ab8c3` |

### R1.2 실행 명령과 결과

| # | 명령(사본 `gs02b`) | 결과 |
| --- | --- | --- |
| RJ1 | CI core와 같은 pytest 명령(`--cov=recoryn --cov-branch … --cov-fail-under=85`, `-W error::ResourceWarning`, `-p no:cacheprovider`), `PYTHONPATH=gs02b\src`(보고서에 `D:\project\Recoryn\src` 경로 0건), 고유 `TEMP`·`--basetemp`, offscreen | **22798 passed / failure 0 / error 0 / skip 0, 1360.73s, exit 0, 전체 coverage 92.32%**. JUnit LF `b5c71a12029a639213fb0f073e4c62b389dceec1f6d4514b12046aaee11ba468`, 로그 LF `b8162dc2a9664256109fb4f792690264c12724227cf2602a0ba4c3153d6d8f80`, `coverage.json` LF `07fbde4899bc7ae20199fc2ffbe706a729d356f95350031e62f22b5ad3183325` |
| RJ2 | `python scripts/check_coverage.py coverage.json` | **7묶음 PASS**: domain 99.18·97.89, capture 99.85·98.57, jobs 99.29·96.23, storage 95.95·91.41, security 98.11·94.43, content 99.59·98.75, all 93.71·88.24(작성자 §16.4와 같음) |
| RJ3 | `ruff check --no-cache …` / `ruff format --no-cache --check …` / `MYPYPATH=src python -m mypy --no-incremental src/recoryn scripts packaging` | All checks passed / 193 files already formatted / **91 source files no issues** |
| RJ4 | probe(아래). 측정 `run_measure.sh`는 다른 시험·변이가 돌지 않을 때 순차 실행 | R1.3~R1.6 |
| RJ5 | `mutate_fix.py ../gs02b-mut mutations.jsonl`(검토자 변이 6종, 신규 2파일 + `test_blocked_reason_flow.py` 705 node) | R1.7. 결과 LF `a5ec07367e99eb00d5ea2d1e4b65feefe93d28c840cb9583e98d250ae5732dfa`. 변이마다 library.py 원본 `7e9a1c12…`로 복원 |

새 probe(`gs02b-probe/`, LF SHA256 앞 16자): `probe_transient2.py` `e5b2417c59876e1a`, `probe_inplace.py` `35e373d1ff9e5406`, `probe_g05r02_gs.py`(일시 거부 창 옵션 추가) `e36a34a5cedc9937`, `run_measure.sh` `056a96b1254e0af9`, `mutate_fix.py` `313103a04ee00898`. 측정 결과 `measure.jsonl` LF `fbb2b85680d11dec6eaf155c787731f2ed1eedac63f9f51ccf1410787303d98c`, `contention.jsonl` LF `4eecb17dda219c06fd180cb84744219cc119e45de6101854691a6cf720757ed5`.

### R1.3 GS02R-01(S1로 상향) — **RECHECKED**

- 코드(library.py):
  - `_journal_prefetch`(:433-485)는 `_read_journal`의 `ValueError`만 `content_failure=True`로 둔다. 목록·읽기의 `OSError`는 content_failure 없는 관찰(journal None)이다.
  - `_accept_observation`(:531)은 `content_failure`인 관찰만 `_intent_failure`로 게시한다.
  - `_failure_current`(:487-505)는 `content_failure`를 요구한다.
  - 그래서 I/O 오류 관찰은 그 호출에서만 `DELETION_HISTORY_UNAVAILABLE`이다. 색인은 무효로 남고, 다음 호출이 다시 검증한다.
- 1차 반례 재실행(`gs02a-probe/probe_transient_failure.py`):
  - 열 때(open): 한 번 거부 뒤 `create_session`·`RecordingService`·`get_session`×5·`chunks`×5·`stop()`이 모두 OK다(fresh 조회 없음).
  - 재검증 때(refresh): 첫 `get_session`만 거부되고 이후 전부 OK다(HEAD와 같다).
- 연속 거부 확장(`probe_transient2.py`, 완료 삭제 50건 settled, `t0025.json` 다음 K회 읽기 `PermissionError`):

  | 지점 | K | 1차 tree `4a6b2953` | FIX1 |
  | --- | ---: | --- | --- |
  | 열 때 | 1 | (probe가 녹음 생성 실패로 중단) | 열기에서 1회 소비. `create_session` OK·OK, `chunks` OK, Job `VALID`, `stop` OK(FINALIZED), 새 녹음 생성 OK |
  | 열 때 | 3 | 같음 | `create_session` 거부·거부(남은 거부를 소비)·OK·OK, 이후 `chunks`·Job `VALID`·`stop` FINALIZED·새 녹음 OK |
  | 녹음 중 재검증 | 1 | `get_session` 거부×2, `chunks` 거부, Job `HISTORY_UNAVAILABLE`, **`stop` 거부(RECORDING에 남음)**, 새 녹음 거부 | `get_session` 거부·OK, `chunks` OK, Job `VALID`, `stop` OK(FINALIZED), 새 녹음 OK |
  | 녹음 중 재검증 | 3 | 거부×4(남은 거부 2 = 고착), 이하 같음 | `get_session` 거부×3·OK(남은 거부 0), 이후 모두 OK |

  거부를 만난 호출만 fail closed이고, 거부가 끝난 뒤 첫 호출부터 수동 새로고침 없이 회복한다.
- 내용 손상 대조(같은 probe의 control, 미인식 항목 + settled mtime): `get_session` 3회와 Job 권위 모두 계속 거부된다(fail closed 유지).
- 녹음 중 3초 지속 거부 창(R1.6): 창이 끝난 뒤 `stop()`이 성공했다.

### R1.4 GS02R-02 — **RECHECKED**, 그리고 요청 2(I1)

- 코드: `_failure_current`는 settle 전이면 현재 이름 목록이 실패 관찰의 이름 목록과 같을 때만 재사용한다(`names == failed.names`). `time.time_ns() >= started_ns >= stamp.mtime` 조건으로 미래 mtime은 제외된다. Job 선읽기의 이름 비교는 root 밖에서 하고, root 안에서는 재확인만 한다.
- 2트랙 녹음 + 외부 손상(1차의 229·15·12블록 조건: N=1000, 3초 뒤 미인식 항목, 250ms tick, 12초, 다른 실행 없음):

  | tree | 회차 | 거부 블록 | 50ms 이상 tick 보유 수 / 최장 | tick p50 | 보존 |
  | --- | ---: | ---: | --- | ---: | --- |
  | FIX1 | 3 | **0·0·0** | **1·1·1** / 406·409·413ms | 1.8~2.0ms | 성립 |
  | 1차 tree | 3 | 0·0·2 | 5·5·5 / 555·577·553ms | 0.6~0.7ms | 성립 |
  | FIX1, 1트랙 | 1 | 0 | 1 / 454ms | 2.0ms | 성립 |

  - 반복 cold 검증 4~5회는 첫 1회로 줄었다.
  - 이번 회차의 1차 tree 거부(0·0·2)는 1차 측정(229·15·12)보다 작아 PC 부하 차이가 크다. 판정 근거는 cold 횟수(5 → 1)다.
  - tick p50이 1차 tree보다 약 1ms 큰 것은 settle 전 hot 경로가 이름 목록(`os.scandir`, 1,000건)을 보기 때문이다. 설계대로다.
- I1 판단(요청 2):
  - **실패 재사용은 거부 쪽**이다. settle 전 재사용은 `_live`·Job 거부만 만든다. 녹음 쓰기 경로(`_writer_intent`)는 실패 memo를 보지 않는다(변이 G2·1차 확인). 허가를 늘리는 경로가 없다.
  - **성공 재사용은 늘지 않았다.**
    - 관리·Job이 쓰는 남의 관찰은 `_newer_observation_current`(:507-516)뿐이다. 같은 version·stamp에서 자기보다 늦게 시작해 먼저 게시된 전체 검증이라 더 신선하다.
    - `_live`의 성공 색인 재사용은 G15 이래 규칙(이름 목록·stamp)이 그대로다.
  - `probe_inplace.py` A(settle 전 내용 실패 → 같은 이름·stamp로 제자리 수선): `get_session` 계속 거부. `list_sessions`(fresh) OK, 그 뒤 `get_session` OK.
  - `probe_inplace.py` B(유효 색인 → 같은 이름·stamp로 제자리 본문 손상):
    - `_live`는 G15 §11.6 수용 한계대로 감지하지 못한다(`get_session` OK).
    - fresh `list_sessions` 거부, Job 권위 `HISTORY_UNAVAILABLE`, 관계없는 live 세션의 capture append OK.
    - 이 동작은 FIX1이 바꾼 것이 아니다.

### R1.5 GS02R-03 — **RECHECKED**

- 코드: `job_authority`(:318-328)는 자기 관찰이 게시되지 못해도 `_newer_observation_current`가 참이면 재시도하지 않는다. 그때는 현재 색인으로 답하고, 색인이 None(최신이 실패)이면 `HISTORY_UNAVAILABLE`이다. `_deletion_history`도 같은 함수를 쓴다(:690).
- `probe_authority_contention.py`(완료 삭제 1,000건, Job 권위 20회 + fresh `list_sessions` reader):

  | readers | FIX1 | 1차 tree(이번 회차) |
  | ---: | --- | --- |
  | 2 | VALID 20, 22.71s | VALID 20, 35.56s |
  | 3 | VALID 20, 47.87s | VALID 20, 50.13s |

  - 이번 회차는 1차 tree도 거짓 거부가 나지 않았다(1차 검토 때 1/20·2/20). 비결정적이라 재현 횟수만으로는 판정하지 않았다.
  - 판정 근거는 세 가지다: 공유 경로 코드, 소요 시간 감소(재시도로 인한 중복 O(N) 읽기 감소), 작성자 F1-AUTH 행과 검토자 변이 F4·F6의 검출(R1.7).

### R1.6 남는 위험(발견 아님)

- **지속 I/O 오류 동안의 반복 cold 검증**:
  - 측정: 녹음 3초 뒤 유효한 외부 의도를 추가해 재검증을 유도하고, `t0500.json` 읽기를 3초 동안 `PermissionError`로 막았다(`GS02R_DENY_SECONDS=3`, 2트랙, N=1000).
  - 결과: FIX1·HEAD 모두 tick 보유 50ms 이상이 7회(최장 527·479ms)였고, 거부 0, 창이 끝난 뒤 `stop()` 성공이었다.
  - C00 결정("OSError는 호출마다 재검증")의 대가로, I/O 오류가 이어지는 동안 GUI tick마다 cold 전체 검증이 root 안에서 반복된다. 오래 지속되면 1차 GS02R-02와 같은 종류의 블록 거부가 날 수 있다.
  - 첫 cold 1회(약 0.4~0.5초)는 내용 손상에서도 남는다. 대안 B(root 밖 검증)와 GS-P01 범위로 인계한다.
- 정상 입장의 O(N)(작성자 §14.3, 1차 §3.5 의견)은 그대로다.

### R1.7 mutation(검토자 작성, J5)

| ID | 변이 | 결과 | 잡은 node(대표) |
| --- | --- | --- | --- |
| F1 | 목록·읽기 `OSError` 관찰을 `content_failure=True`로(GS02R-01 되돌림) | 검출 28 | GS02-N-049~051 등 |
| F2 | settle 전 실패 재사용에서 이름 비교 제거 | 검출 10 | GS02-I-023·024, GS02-F1-NAMES-07 |
| F3 | 미래 mtime(`started_ns >= stamp.mtime`) 조건 제거 | 검출 2 | GS02-F1-NAMES-05·06 |
| F4 | Job이 더 새 관찰을 쓰지 않고 재시도(GS02R-03 되돌림) | 검출 3 | GS02-F1-AUTH-01·05·09 |
| F5 | 모든 내용 실패를 settled로 취급(settle 규칙 제거) | 검출 10 | GS02-I-023·024, GS02-F1-NAMES-07 |
| F6 | 더 새 관찰 공유에서 stamp 대조 제거 | 검출 3 | GS02-F1-AUTH-02·06·10 |

생존 0. 작성자 변이 24종은 실행하지 않았다(기록만 읽음).
