# G15R / G-P15 청크 seal의 root mutex 보유 축소 독립 검토

상태: **REVIEW_READY — 독립 검토 1차, 2026-11-24.** 작성자는 w5:p7 Claude이고, 검토자는 C00이 배정한 다른 하위 에이전트(Claude)다. 검토자는 코드를 고치지 않았다. 저장소 쓰기는 이 문서 하나다. 반례·측정 스크립트는 `build/review-trees/g15a-probe/`, 변이 사본은 `build/review-trees/g15a-mut/`, 비교용 HEAD 사본은 `build/review-trees/g15a-head/` 아래에만 두었다. 최종 수용과 push 게이트 판단은 C00이 한다.

**요약.** 코드 읽기, CI와 같은 전체 회귀(J1b: 15178 PASS, coverage 92.57%, 전 묶음 PASS), 검토자 probe 10종, HEAD 대조 측정과 검토자 변이 18종으로 확인했다. **S0·S1·S2는 찾지 못했다. OPEN은 S3 4건**이다.
- G15R-01: 살아 있는 capability의 공개 `descriptor`를 바꾸면 검증 없이 다른 묶음이 등록된다. root 조건 변이도 생존한다.
- G15R-02: 소비자 thread 시작이 실패하면 sealer가 남아 세션이 계속 live이고 프로세스가 끝나지 않는다.
- G15R-03: sealer 오류 경로(staging 보존·복구 prefix·FIFO 잔여 writer abort)가 시험에 없다. 동작은 검토자 probe로 맞음을 확인했다.
- G15R-04: capture 경로 이름 목록 캐시의 settle 조건을 지운 변이가 생존한다.

녹음 유실 측정(이 PC 단독, HEAD `0d846d6` 대 G15): G05R-02 조건(완료 삭제 1,000건 + UI tick, 1트랙)에서 HEAD는 544·470블록을 거부했고 G15는 0·0이었다. 2트랙에서는 HEAD 1,701·1,652 대 0·0, tombstone 0건 2트랙(O1)에서는 HEAD 146·139 대 0·0이었다. writer root 최장 보유는 HEAD 1.19~1.25초, G15 소비자 5~9ms, sealer 3~12ms였다. sealer 실패·FIFO 가득 상태의 크래시·live 삭제·`WRITER_ACK_PENDING`에서 수락해 append한 블록의 유실, 의도 뒤 게시·등록, 원본 부활은 0이었다.

## 1. 입력 고정

| 항목 | 값 |
| --- | --- |
| 대상 | tree `accb298644ac1a58583abdd24efb475347e248b3`(`git cat-file -t` = tree) |
| 기준 | HEAD `0d846d6`(G-P06b·GC-P02 포함). `git diff 0d846d6 accb2986 --stat` = 7파일 3660+/79- |
| 추출 | `git archive accb2986 \| tar -x -C build/review-trees/g15a`, 비교용 `git archive 0d846d6` → `build/review-trees/g15a-head` |
| 제출 6파일 LF SHA256 | 계약 문서 §16.5 표와 **6/6 일치**(library.py `4dd035d1…0136`, _coordination.py `46d76a8f…b8c9`, chunks.py `618a0e2a…f34f`, recording.py `1b6ee4fd…a1ea4`, test_seal_phases.py `362400d0…ecb4`, test_seal_mutex.py `23af1e55…7cae9`) |
| 계약·실행 기록 | `docs/testing/g15-seal-mutex-cases.md` LF `345b73e2971a817079f7216907599be672e198ff1dc5c551b9c8167cf5b73f88`(1,168행) |
| 환경 | Windows 11 Pro 10.0.26300, 저장소 `.venv` Python 3.13.1, offscreen Qt. 실제 장치·모델·네트워크·유료 호출·Credential Manager 쓰기 없음. 종료한 프로세스는 검토자 probe가 만든 자식뿐 |

작성자는 `68fbbda` 기준으로 판정했다. **`0d846d6` 기준 전체 회귀는 이 검토가 처음 실행했다(J1b).** 작성자 증거는 읽기만 했고 재사용하지 않았다.

검토 과정 고지:
- 전체 회귀의 `TEMP`를 만들 때 경로 구분자가 빠져 실제 위치가 `C:\Users\gangd\AppData\Local\Tempg15r-full-68432877`·`…\Tempg15r-full2-516419755`가 됐다(저장소 밖, 검토자 전용 새 폴더). 기존 시험 `test_storage.py::test_directory_reparse_point_*`가 두 basetemp에 junction을 하나씩 남겼고, 대상은 같은 basetemp 안의 `outside` 폴더다. 지우지 않고 그대로 두었다.
- 검토자 probe 하나(`probe_thread_start.py` 첫 판)가 JSON 직렬화 오류로 끝나지 못하고 멈췄다. 그 셸 작업만 `TaskStop`으로 끝냈고, 남은 python 프로세스가 없음을 확인했다. 이 멈춤 자체가 G15R-02의 관측이다.

## 2. 직접 실행한 명령과 결과

| # | 명령(사본 `g15a`에서, `.venv` Python) | 결과 |
| --- | --- | --- |
| J1 | CI core와 같은 `python -m pytest -q -p no:cacheprovider -W error::ResourceWarning --cov=recoryn --cov-branch --cov-report=term-missing --cov-report=json:coverage.json --cov-fail-under=85`, 고유 `TEMP`·`--basetemp`, `QT_QPA_PLATFORM=offscreen` | 15178 passed / 실패·오류·skip 0, 1114.95s. **coverage 54.08%로 FAIL — 검토 환경 결함이라 무효 처리.** `.venv`의 editable 설치(`__editable__…pth` = `D:\project\Recoryn\src`)와 `[tool.coverage.run] patch=["subprocess"]` 때문에, PYTHONPATH 없이 `python -m recoryn`을 띄우는 시험의 자식 프로세스가 **작업 트리 src**(미완성 G-P07 포함)를 import해 측정됐다(`D:\project\Recoryn\src\…` 75파일이 보고서에 섞임). 자식 프로세스 시험 결과도 이 tree의 것이 아니다. 기록만 남긴다(`full-run1-nopythonpath.log`, JUnit LF `bb8d155b…7743`) |
| J1b | J1과 같은 명령 + `PYTHONPATH=g15a\src`(자식 프로세스도 사본 import). 보고서에 `D:\project\Recoryn\src` 경로 0건 | **15178 passed / failure 0 / error 0 / skip 0, 1168.93s, exit 0, 전체 coverage 92.57%**. JUnit LF `2f1ff18511d19252bf340234aec95917e9e1a192a7b8930d2343379836d21bbf`, 로그 LF `62fb5b12c66a3a829126c8e9cf371fbf0b34bc991bc749c351b2d0935abde6b4`, `coverage.json` LF `c30e0932e9eecff61995e2b57ef663628f23cc3f5c20827d4bd9c01041fe4df6` |
| J1c | `python scripts/check_coverage.py coverage.json`(J1b 결과) | **전 묶음 PASS**: domain 100.00·100.00, capture 99.85·98.57, jobs 98.89·97.47, **storage 96.54·92.16**, security 98.11·94.43, content 99.59·98.75, all 93.98·88.29(line·branch %). 작성자 §16.3 값과 같다 |
| J2 | `ruff check --no-cache src tests scripts packaging` / `ruff format --no-cache --check …` / `MYPYPATH=src python -m mypy --no-incremental src/recoryn scripts packaging` | All checks passed / 170 files already formatted / **86 source files no issues** |
| J3 | 검토자 probe(아래 표, 모두 `-I`로 실행하고 대상 src를 `sys.path[0]`에 넣어 import 경로를 확인) | §3·§4 |
| J4 | `run_measure.sh`: `probe_g05r02.py`를 HEAD 사본과 G15 사본에 번갈아 순차 실행(다른 시험·변이 실행이 없을 때) | §5 |
| J5 | `mutate.py ../g15a-mut <log>`(검토자 작성 변이, 사본 sentinel로 import 확인, 복원 hash 대조) | §6 |

probe 스크립트(`build/review-trees/g15a-probe/`, LF SHA256 앞 16자):

| 파일 | 목적 | LF SHA256 |
| --- | --- | --- |
| `probe_cap_swap.py` | G15R-01 | d216f055ee04e05f… |
| `probe_thread_start.py` | G15R-02 | bc84965c05781ec6… |
| `probe_hb6_recovery.py` | G15R-03, 검증 실패 뒤 복구 prefix | 061b10c5bc5865f1… |
| `probe_sealer_failure.py` | sealer 준비·등록 실패 × FIFO 가득, 보존·복구 | 1f51e785b0ae6b61… |
| `probe_crash_full_fifo.py` | FIFO 4 + sealing + 소비자 대기 상태에서 자식 kill 뒤 복구 | 85c36f7dbffc8ab2… |
| `probe_delete_full_fifo.py` | FIFO에 청크가 쌓인 live 세션 삭제(I1·I3) | 2ae43b1b975368cf… |
| `probe_ack_pending.py` | sealer 대기 중 `WRITER_ACK_PENDING`과 live 유지 | 70331cccfea5b38e… |
| `probe_register_lock.py` | 거부된 두 번째 열기·재열기와 콜백 등록부 | 8351a285fc9f7f9f… |
| `probe_overlap_sql.py` | 겹침 SQL 대 HEAD Python 판정(독립 oracle) | 17a07b51f07faed1… |
| `probe_g05r02.py`, `run_measure.sh` | G05R-02·O1 조건 측정 | e2a2ad99f287e54e… / dedf0ef2fa8d786c… |
| `mutate.py` | 검토자 변이 | 949e3290083a6d15… |

## 3. 발견

### G15R-01 (S3, OPEN) — 살아 있는 `SealedChunk`가 발급 대상 묶음에 묶여 있지 않아, 공개 `descriptor` 속성만 바꾸면 검증 없이 다른 묶음이 등록된다

- 근거:
  - `chunks.py:323` `SealedChunk.__slots__`의 `descriptor`는 쓰기 가능한 공개 속성이다.
  - `chunks.py:343-353` `issued_descriptor()`는 capability 객체의 동일성(`_issued` 소속, `_writer._capability is candidate`, root)만 보고 **그 객체가 지금 들고 있는 `descriptor`를 그대로 돌려준다**. 발급 때의 descriptor나 writer의 `relative_path`·chunk_id와 대조하지 않는다.
  - `library.py:659-662` capability 경로는 돌려받은 descriptor로 값싼 동일성 검사(`descriptor.json` 바이트·`audio.pcm` 크기)만 하고 `verify_bundle`을 생략한다.
- 재현(J3, `probe_cap_swap.py ../g15a/src`):
  1. 같은 root에 고아 묶음을 만든다(seal 뒤 release, 미등록 = 크래시 C5 모양). 그 `audio.pcm` 첫 바이트를 뒤집는다(크기 불변).
  2. 공개 `register_chunk(orphan_descriptor)` → `ValidationError: Invalid journal record`(정상 거부).
  3. 다른 청크를 `hold()`+`seal()`해 살아 있는 capability를 얻고 `capability.descriptor = orphan_descriptor`로 바꾼 뒤 `register_chunk(capability)`.
  - 관측: **ACCEPTED**. 손상된 고아 묶음이 catalog에 들어가고, capability의 원래 청크는 등록되지 않는다. `verify_bundle(orphan)`은 여전히 `Invalid journal record`다.
- 기대: C00 결정 2의 조건("sealer만 만들 수 있는 객체, descriptor나 공개 데이터만으로 위조 불가")에 비추면, capability는 **발급한 그 묶음 하나**에만 재검증 생략을 허용해야 한다. 예: `issued_descriptor`가 writer가 발급 때 기록한 descriptor를 돌려주거나, `candidate.descriptor`가 발급 객체와 `is`로 같고 `relative_path`가 `_writer.relative_path`와 같은지 확인한다. 속성을 읽기 전용으로 둔다.
- 영향: 제품 경로(`recording.py:289`)는 descriptor를 바꾸지 않으므로 지금 사용자 경로에서는 발생하지 않는다. 같은 프로세스 코드의 오용이 필요하다. 그래서 S3다. 다만 시험의 CAP 4행(`test_sealed_chunk_capability_cannot_be_forged`)은 `is_issued()`만 보고, `register_chunk`에 변조된 capability를 넣는 행이 없다. 이 성질은 시험으로 고정돼 있지 않다.
- 같은 묶음의 시험 공백: `issued_descriptor`의 root 일치 조건(`chunks.py:350`)을 지운 변이 R5가 G15 2파일과 `test_storage.py` 223 node에서 **생존**했다(§6). 다른 root의 Library에 capability를 넘기는 행이 없다.

### G15R-02 (S3, OPEN) — 소비자 thread 시작이 실패하면 sealer thread가 영구히 남아 세션이 계속 live이고 프로세스가 끝나지 않는다

- 근거: `recording.py:157-158`은 sealer를 먼저 시작하고 소비자를 시작한다. 실패 정리(`:159-166`)는 `_transition(RECORDING)`만 감싼다. sealer는 `_STOP`을 받을 때만 끝나고(`:271-277`), `_STOP`은 소비자의 `finally`(`:269`)만 넣는다. 두 thread 모두 `daemon=False`(`:152`, `:155`)다.
- 재현(J3, `probe_thread_start.py`): `threading.Thread.start`를 `recoryn-writer-*` 이름에서만 `RuntimeError("can't start new thread")`로 바꿔 `service.start()`.

  | tree | `start()` | 남은 thread | `is_live()` | `recover_session` | `delete_session` | 프로세스 종료 |
  | --- | --- | --- | --- | --- | --- | --- |
  | HEAD `0d846d6` | RuntimeError | 없음 | False | CREATED(정상) | DELETED_LOCAL | 정상 |
  | G15 | RuntimeError | `recoryn-sealer-rec` | **True** | **StateConflict SESSION_LIVE** | **DELETE_PENDING(SESSION_LIVE)** | **멈춤**(첫 실행에서 faulthandler가 `threading._shutdown`이 sealer를 기다리는 것을 기록. probe가 마지막에 자기 FIFO에 `_STOP`을 넣어야 끝났다) |

- 기대: 시작 실패 뒤에는 HEAD처럼 thread가 남지 않고 세션이 live가 아니어야 한다. 예: 두 thread 시작을 같은 정리 구간에 넣고, 실패하면 `_seals.put(_STOP)`과 join을 한다.
- 영향: 녹음 데이터는 없다(수락 전). 계기가 thread 생성 실패(자원 고갈)라 드물다. 그래서 S3다. 그러나 그 프로세스에서는 세션의 복구·삭제가 계속 보류되고, 앱 종료가 멈춘다.

### G15R-03 (S3, OPEN) — sealer 오류 경로의 계약 oracle이 시험에 없다: HB6의 "staging 보존·INTERRUPTED·검증된 prefix만 복구"와 §3.4의 "FIFO에 남은 writer abort"

- 근거: 계약 §4.3 HB6 행(문서 177행)은 "검증 실패 청크는 게시 0, 등록 0, staging 보존. writer 오류로 INTERRUPTED. 복구는 검증된 prefix만 채택"이다. `test_hb6_failed_verification_and_delete`(test_seal_mutex.py:418-457)는 게시 0·등록 0·`storage_failed`·삭제만 확인하고, 네 위치 모두 세션을 지운다. pipeline 아래의 staging 보존과 복구 prefix는 어느 G15 node도 확인하지 않는다. 단위의 손상 staging 3행은 직접 `seal()`만 본다.
- 검토자 확인(J3): 동작 자체는 기대와 같다.
  - `probe_hb6_recovery.py`: 둘째 청크(블록 3~5)의 블록 5 payload 1바이트를 검증 직전에 뒤집는다. 실행 중 catalog `[0-2]`, 게시 1(첫 청크만), 상태 INTERRUPTED. 복구 뒤 catalog `[0-2],[3-4]`, 경고 `STAGING_TAIL_NOT_ADOPTED`. 손상 블록은 채택되지 않는다.
  - `probe_sealer_failure.py`(준비·등록 실패 × 1·3번째 청크, FIFO 가득): 소비자가 append에 성공한 프레임 = 복구 뒤 catalog 프레임, 바이트 일치, 재복구 0.
- 계약 §3.4 "오류: … FIFO에 남은 writer와 열린 writer는 abort한다(staging 보존)": 실패 뒤 FIFO writer를 abort하지 않는 변이 R10(`recording.py:280`의 `item.abort()` 제거)이 G15 129 node에서 **생존**했다(§6). HB6은 청크 하나뿐이라 실패 시점에 FIFO가 비어 있다. CPython에서는 writer가 참조를 잃을 때 파일이 finalizer로 닫혀 결과가 거의 같지만, 닫히기 전까지 `has_active_writer`가 참이고 `ResourceWarning`이 난다. 계약이 적은 동작을 시험이 고정하지 않는다.
- 기대: HB6 한 행 이상이 삭제 대신 복구를 수행하고 위 기대를 assert하고, FIFO에 2개 이상 쌓인 상태의 실패 행이 남은 writer의 비활성(`has_active_writer` 거짓)과 staging 보존을 assert해야 계약 oracle과 시험이 일치한다.

### G15R-04 (S3, OPEN) — capture 경로 이름 목록 캐시의 settle 조건이 시험에 고정돼 있지 않다

- 근거: `library.py:380`(`_writer_names`)은 색인이 현재가 아닐 때(외부 변경 뒤) 이름 목록을 캐시한다. 캐시는 settle된 목록(`cached[3]`)일 때만 재사용한다. settle 전 목록을 재사용하면, 같은 mtime tick 안의 외부 변경(예: 녹음 중 세션의 의도 파일 추가)을 append·seal 판정이 놓친다(I1 약화).
- 재현(J5): 조건 `and cached[3]`를 지운 변이 R16이 G15 2파일 + `test_storage.py` 223 node에서 **생존**했다. 같은 목적의 `_live` 쪽 행(`fc_same_tick_name_change`)은 있지만 writer 경로 행은 settle된 캐시(`fc_settled_listing_cache`)만 본다.
- 영향: 외부 도구가 journal을 직접 바꾸는 경우에만 해당한다(단일 writer 계약 밖, 계약 §14.3). 현재 코드는 맞다. 회귀를 막는 시험이 없다는 것이 발견이다. S3.

## 4. 중점별 판정

### 4.1 녹음 유실·원본 손상(중점 1)

- **sealer 오류**(`probe_sealer_failure.py`, `_prepare` 0.4초 지연으로 FIFO를 채움, 3-block 청크가 아니라 10-block 청크 40개 분량 제출):

  | 실패 위치 | 실패 청크 | 실패 뒤 상태 | 소비자가 append한 블록 | 복구 전 catalog 프레임 | 복구(recovered/adopted) | 복구 뒤 catalog = append 프레임 | 바이트 일치 | 재복구 |
  | --- | ---: | --- | ---: | ---: | --- | --- | --- | --- |
  | 등록(게시 뒤) | 1 | INTERRUPTED | 60 | 0 | 5 / 1(고아 bundle) | 28,800 = 28,800 | 예 | 0/0 |
  | 등록 | 3 | INTERRUPTED | 80 | 9,600 | 5 / 1 | 38,400 = 38,400 | 예 | 0/0 |
  | 준비(게시 전) | 1 | INTERRUPTED | 60 | 0 | 6 / 0 | 28,800 = 28,800 | 예 | 0/0 |
  | 준비 | 3 | INTERRUPTED | 80 | 9,600 | 6 / 0 | 38,400 = 38,400 | 예 | 0/0 |

  - FIFO에 남은 청크와 열린 writer는 abort되고 staging으로 남는다. 복구가 모두 채택한다. append에 성공한 블록 중 잃은 것은 없다.
  - HEAD와 다른 점: HEAD는 가득 찬 청크를 소비자가 즉시 seal·등록했으므로, 실패 시점에 catalog에 들어가 있던 청크가 G15에서는 최대 FIFO 4개 + 트랙별 열린 writer만큼 staging으로 남는다. 유실은 아니며, INTERRUPTED 뒤 복구·확정(`finalize_unfinished`는 복구를 먼저 한다)으로 채택된다.
  - 실패를 알아챈 뒤 캡처 큐에 남은 수락 블록은 쓰지 않는다(`pending.close()`). HEAD와 같은 의미다. G15에서는 소비자가 계속 append하므로 그 양은 HEAD보다 작다.
- **크래시**(`probe_crash_full_fifo.py`, 계약 C7을 넘어 FIFO 4 + sealing 1 + 소비자 `_hand_off` 대기 상태에서 자식 kill): 1트랙은 journal에 기록된 18블록, 2트랙은 트랙별 9블록을 정확한 바이트·연속 sequence로 복구했다(recovered 6, 재복구 0). 캡처 큐의 메모리 블록은 HEAD와 같이 크래시에서 사라진다.
- **정지**(`probe_ack_pending.py`, `_prepare` 1초, 5청크 대기): `stop(timeout=1.5)` → `WRITER_ACK_PENDING`. 그동안 `recover_session` → `Live writer cannot be recovered`, `finalize_unfinished` → `SESSION_LIVE`. `join_writer()` 뒤 다시 `stop()` → FINALIZED 5청크 60프레임. `WRITER_ACK_PENDING`이 sealer까지 넓어진 의미가 지켜진다. 같은 부하에서 HEAD는 블록을 거부하던 상황을 G15는 정지 지연으로 바꾼다. 기본 `stop(timeout=5.0)`과 `power.py`의 `pause()`는 과부하 때 이 코드를 더 자주 볼 수 있다(기존 처리 경로 있음).
- **backpressure 회계**: LAT·IDX-UI 시험이 저장 프레임 = (제출 − 거부) × 480을 모든 행에서 assert한다. 거부는 지금처럼 `QUEUE_DROP`으로 기록된다(`submit` 불변).
- **is_live**: FIFO의 writer는 파일이 열려 있어(`_pcm`) `has_active_writer`가 참이고, 준비 중에는 `_sealing`, 등록까지는 `hold()`로 참이다. sealer thread는 `_STOP`을 받기 전까지 살아 있다. 그래서 등록되지 않은 청크가 있는 동안 확정·복구는 거부된다(HB2·HB3, 위 probe). 작성자의 MU6 동등 판단에 동의한다. 예외는 G15R-02(시작 실패)다.

### 4.2 삭제 불변식 I1·I3(중점 2)

- **순서·잠금(코드 읽기)**: append(`chunks.py` append → `check_write_allowed` → `_append_check` → `_writer_intent`), seal 게시(`seal_chunk` 둘째 mutex 구간), 등록(`register_chunk` mutex 구간)과 의도 게시(`_publish_intent`: 파일 + 색인, 이어서 `_project_intent`)가 모두 같은 root RLock 안이다. 의도 게시 도중 색인은 무효(`_intent_journal=None`)이고 실패하면 무효로 남아 다음 판정이 전체 검증 또는 이름 목록으로 간다. 판정은 이름 목록·색인·DB 행 중 하나라도 의도를 보이면 거부한다. 반례를 찾지 못했다.
- **settle 규칙**: `_list_journal`은 stamp를 읽은 뒤 시각을 재고 목록을 만든다. 목록 관찰 시각이 mtime보다 2.5초 넘게 늦으면, 그 뒤의 변경은 반드시 더 늦은 mtime을 갖는다. 목록 직후 stamp 재확인(`== stamp`)은 저장된 `_intent_stamp`가 다음 질의에서 다시 비교되므로 방어 중복이다(변이 R9 참고). NTFS 가정에서 논리 결함은 찾지 못했다. FAT·exFAT·네트워크 볼륨은 계약대로 미검증 한계다(FAT는 디렉터리 mtime을 항목 추가 때 갱신하지 않을 수 있다).
- **live 세션 삭제, FIFO에 청크가 쌓인 상태**(`probe_delete_full_fifo.py`, 1·2트랙, 대기 3청크): 첫 답 `DELETE_PENDING(SESSION_LIVE)`, 의도 뒤 게시·등록 0/0, join 뒤에도 0/0, `retry_deletion` → `DELETED_LOCAL`, 폴더 없음, `recover_session` → `DELETE_PENDING`, 폴더 재생성 없음, 남은 thread 없음.
- **다른 Library 인스턴스·다른 프로세스**: 같은 프로세스의 두 번째 열기는 OS 잠금으로 거부되고, 그 실패한 생성자의 `close()`는 먼저 열린 Library의 콜백을 지우지 않는다(`probe_register_lock.py`: bound method 비교가 인스턴스 identity라서). 닫으면 항목이 지워지고 다시 열면 새로 등록된다. Library 없이 `ChunkWriter`만 쓰는 프로세스는 기존 durable 검사를 그대로 탄다(코드). 다른 프로세스 Library 동시 열기는 HEAD와 같이 잠금이 막는다(직접 다중 프로세스 probe는 하지 않았다).
- **fail closed**: `.tmp-` 항목은 writer 경로도 거부한다(`_writer_names`, 기존 `test_storage.py::test_writer_checks_durable_deletion_and_schema_before_open[unfinished_intent]`가 계속 통과). 미인식·손상 항목은 `_live`·관리 경로가 실패하고 writer는 이름만 보므로 계속 녹음한다(G05R-04 해소). 자기 세션 판정이 I/O 오류면 그 세션의 쓰기는 거부된다(IDX-IO3).
- **G05R-04형 일시 PermissionError**: capture 경로(append·seal·capability 등록)는 journal 파일을 하나도 열지 않는다(`_writer_intent`는 이름 목록·자기 세션 DB 행만, IDX-IO의 구조 assert `denied`에 `recoryn-*` thread 없음). 외부 손상으로 색인이 무효인 동안에도 writer는 계속 녹음하지만 GUI tick의 `_live`가 매번 전체 재검증을 한다(§5 손상 행, 남는 위험).

### 4.3 capability·재검증 생략·겹침 검사(중점 3)

- 위조: 직접 생성·복사·release된 객체는 거부된다(CAP 4행, 변이 R4). 그러나 **살아 있는 capability의 descriptor 바꿔치기**는 막지 못한다 → G15R-01.
- 외부 descriptor와 복구 채택은 `verify_bundle`을 거친다: `register_chunk`의 else 분기(library.py:663-668), `recover_session`은 `ChunkDescriptor`를 넘기고(:1048, :1084) salvage writer는 capability를 발급하지 않는 `_seal()`을 쓴다(:959).
- 겹침 검사 축소: `probe_overlap_sql.py`가 무작위 catalog 400개 × 후보 40개 = 16,000회에서 library.py의 SQL과 HEAD의 Python 판정(검토자가 다시 씀)을 비교했다. 같은 세션·트랙·epoch, 경계 일치(first = 이전 last), 포함, 다른 epoch·트랙, `2**63-1` 근처 값을 포함해 **불일치 0**. Python 3.11.15(SQLite 3.53.1)에서도 0. 손상된 catalog 행(키 누락 JSON)은 예전처럼 decode 오류로 막히지 않고 겹침 없음으로 보인다. catalog 손상 상태에 한정된 차이라 발견으로 올리지 않는다.

### 4.4 크래시 checkpoint(중점 4)

CRASH 7행이 J1b에서 통과했다(자식은 PYTHONPATH로 사본 src를 import). 검토자 추가 지점(FIFO 가득)은 §4.1에 있다. 게시 단계의 mkdir 뒤·rename 전 kill은 따로 만들지 않았다(빈 epoch 폴더만 남는 HEAD와 같은 순서다).

### 4.5 G-P04·G-P05 결합(중점 5)

- J1b에서 `test_unfinished_recovery.py`(G04 PERF 포함), `test_pending_deletions.py`, `test_pending_deletion_restart.py`(GC-P02 구조 판정 포함), G-P05 UI·CLI 시험이 모두 통과했다. 기존 시험 파일은 바뀌지 않았다(`git diff 0d846d6 accb2986 --stat`에 기존 시험 없음). G-P05의 live 삭제 보류(`SESSION_LIVE` 우선)와 재시도는 sealer pipeline 아래에서도 기대대로였다(HB1, `probe_delete_full_fifo.py`). G-P04 claim은 capability 경로에서도 `_is_live`가 참이라 녹음 writer의 claim 검사를 건너뛰는 기존 의미 그대로다.
- 관찰(발견 아님): GC-P02 구조 판정은 "관리 thread가 root mutex를 쥔 동안 `os.scandir` 금지"다. G15는 `_live`·`_publish_intent` 안에서 settle 전 journal 이름 목록(`os.scandir`)을 mutex 안에서 한다. 지금 GC-P02 시험의 관리 동작(`pending_deletions`, `retry_deletion`)은 선읽기 경로만 써서 충돌하지 않는다. 앞으로 `_live`를 부르는 관리 경로(예: `recover_session`의 `get_session`)를 같은 구조 판정에 넣으면 G15의 이름 목록 때문에 실패할 수 있다. 판정 규칙에 "journal 이름 목록 1회(N 항목)"를 예외로 둘지는 C00이 정한다.

### 4.6 시험 충분성(중점 6)

- 분모: 두 새 파일 143 node(`--co`)로 작성자 보고와 같다. 기존 시험 파일 수정 0.
- 시간 상한 0.5초와 구조 판정의 검출력(§6):
  - **검증을 mutex 안으로(R1·R1b)**: 구조 판정이 잡는다. HB4 6행(V 전·V 후 × 관리 3종)이 "관리가 seal을 기다림"으로 실패하고, HB2·HB3도 park가 mutex를 쥔 채 멈춰 실패한다. 시간으로는 지연 주입 1·3초 행 5개만 잡고, 지연 0·0.2초 행 5개는 0.5초 아래라 통과한다(작성자 §16.2 기록과 같다).
  - **seal·등록을 소비자로 되돌림(R2·R2b)**: LAT 10행 모두가 구조 판정(`consumer_seal_or_register_calls == 0`)으로 실패한다. HB2·HB3도 실패한다.
  - **색인 갱신 누락 + 이름 목록 누락(R3)**: `fc-same-tick-name-change`와 `IDX-HB-projection-failed`가 잡는다. 이름 목록만 지운 R14·settle 0(R8)도 잡힌다.
  - **capability 위조 허용(R4)**: `reg-released-capability-verifies` 한 행만 잡는다. 바꿔치기(G15R-01)와 다른 root(R5)는 시험이 없다.
  - **겹침 검사 제거(R6)**: 겹침 의도 행과 REG 3행이 잡는다.
- 생존 변이 4종: R5(G15R-01), R10(G15R-03), R16(G15R-04), R9(settle 직후 stamp 재확인 제거). R9는 저장된 stamp가 다음 질의에서 다시 비교되므로 동등 변이로 판단한다(§4.2).
- writer 경로의 DB 행(R13)과 `.tmp-`(R7)는 G15 파일이 아니라 기존 `test_storage.py`의 writer 시험이 잡는다. 겹쳐 있어 문제는 없지만 G15 분모에는 들어 있지 않다.
- 1트랙 거부 0 assert(LAT 1트랙 3행, IDX-UI 1트랙 2행)는 J1b(coverage 추적)에서도 통과했다. 이 PC 기준이다. CI 러너에서의 G15 시간 측정은 실행하지 않았다.

## 5. 측정 재현(중점 7, J4)

조건: 실제 `RecordingService`(48kHz mono, 10ms 블록 480프레임, 기본 청크 96,000프레임, 큐 256블록)에 12초 실시간 제출. 완료 tombstone N개는 G-P05가 남기는 모양(journal 의도 + DB `DELETED_LOCAL` 행)으로 만들고 3초 뒤(G15 settle 규칙 통과) Library를 연다. `tick`은 250ms마다 `library.chunks("rec")`를 부르는 thread(GUI `_tick` 대리), `mgmt`는 4초에 `list_sessions`·`pending_deletions`·`unfinished_sessions`, 8초에 다른 세션 `delete_session`을 부르는 thread다. root mutex는 최외곽 보유만 thread별로 쟀다. HEAD 사본과 G15 사본을 같은 스크립트로 번갈아 순차 실행했고, 그동안 다른 시험·변이 실행은 없었다. 결과 `measure.jsonl` LF `25a2f6881e658af50909bd5520be04eda82710275605a8716a0aed763be57e95`. 모든 행에서 저장 프레임 = (제출 − 거부) × 480이었다(HEAD의 손상 행 제외, 아래).

| 조건 | 회차 | HEAD 거부 블록 / 유실 프레임 | G15 거부 / 유실 | HEAD writer root 최장 | G15 writer(소비자) 최장 / sealer 최장 | HEAD tick 최장 | G15 tick 최장 |
| --- | ---: | --- | --- | ---: | --- | ---: | ---: |
| G05R-02: N=1000, 1트랙, tick | 1 | **544 / 261,120** | **0 / 0** | 1.240s | 7.9ms / 11.6ms | 0.612s | 1.6ms |
| 같음 | 2 | **470 / 225,600** | **0 / 0** | 1.204s | 5.1ms / 10.7ms | 0.593s | 1.6ms |
| N=1000, 1트랙, writer만 | 1 | **156 / 74,880** | **0 / 0** | 1.247s | 5.2ms / 2.9ms | – | – |
| N=1000, 2트랙, tick | 1 | **1,701 / 816,480** | **0 / 0** | 1.194s | 9.0ms / 11.8ms | 5.758s | 2.0ms |
| 같음 | 2 | **1,652 / 792,960** | **0 / 0** | 1.215s | 5.3ms / 9.9ms | 0.593s | 1.7ms |
| O1: N=0, 2트랙, tick | 1 | **146 / 70,080** | **0 / 0** | 0.511s | 8.7ms / 3.1ms | 1.8ms | 1.5ms |
| 같음 | 2 | **139 / 66,720** | **0 / 0** | 0.502s | 5.6ms / 4.2ms | 2.5ms | 1.6ms |
| N=1000, 2트랙, tick + 관리 작업 | 1 | **1,740 / 835,200** | **0 / 0** | 1.230s | 8.6ms / 10.6ms | 0.700s | 2.6ms |
| 같음 | 2 | **1,741 / 835,680** | **0 / 0** | 1.232s | 8.4ms / 11.4ms | 0.710s | 3.1ms |

- 관리 작업 thread의 root 최장 보유: HEAD 0.394~0.407s, G15 9.8~12.6ms. 소요 시간(G15): `list_sessions` 0.82s, `pending_deletions` 0.92s, `unfinished_sessions` 0.67s, `delete_session` 0.80s(HEAD 0.40·1.73·0.78·3.10s). G15에서 mutex 밖 선읽기가 GIL을 오래 써도 거부는 0이었다.
- **외부 손상 상태**(녹음 3초 뒤 journal에 정렬상 마지막인 `zzzz-unknown.txt` 추가, N=1000, tick):

  | 트랙 | tree | 거부 / 유실 | `storage_failed` | tick 최장 root 보유 | `stop()` |
  | --- | --- | --- | --- | ---: | --- |
  | 1 | HEAD | 771 / 576,000(저장 0) | True(다음 청크 등록에서 녹음 중단) | 0.584s | `DELETION_HISTORY_UNAVAILABLE` |
  | 1 | G15 | 0 / 0(`join_writer` 뒤 catalog 576,000) | False(녹음 계속) | **0.503s** | `DELETION_HISTORY_UNAVAILABLE` |
  | 2 | HEAD | 1,746 / 1,152,000 | True | 0.592s | 같음 |
  | 2 | G15 | 0 / 0 | False | **0.595s** | 같음 |

  - G15는 이 상태에서도 녹음을 멈추지 않는다(G05R-04형 개선). 다만 색인이 무효인 동안 `_live`가 호출마다 journal 전체를 root mutex 아래에서 다시 검증하므로(계약 §11.2가 정한 fail closed 동작), GUI tick 한 번이 0.50~0.60초 mutex를 잡는다. 이 PC에서는 거부 0이었지만 `HOLD_LIMIT_SECONDS`(0.5초)를 넘는 값이다. `stop()`은 첫 줄의 `get_session`에서 실패해 drain 없이 예외를 올린다(HEAD와 같은 동작. probe는 `join_writer()`로 저장을 끝냈다). 외부 손상이 전제라 발견으로 올리지 않고 남는 위험으로 둔다.
- 해석: G05R-02(1트랙 tick 1,000건, G05 검토 측정 923블록)와 관찰 O1(2트랙 기준선 유실)은 HEAD에서 재현되고 G15에서 이 PC 단독 실행 모든 회차가 거부 0이다. HEAD 수치는 G05 검토 때와 다르지만(OS 파일 캐시·부하 차이로 본다) 결론은 같다. G05R-04(다른 세션 journal 읽기 일시 `PermissionError`)는 따로 주입 측정하지 않았다. IDX-IO 5행이 J1b에서 통과했고, capture 경로가 journal 파일을 열지 않는다는 것은 코드와 위 손상 행(녹음 계속)으로 확인했다.

## 6. mutation(J5, 검토자 작성)

사본 `build/review-trees/g15a-mut`(`git archive accb2986 pyproject.toml src tests`)에서 하나씩 적용했다. sentinel로 사본 import를 확인했고, 모든 변이 뒤 3파일 LF hash가 원본(`4dd035d1…`, `618a0e2a…`, `1b6ee4fd…`)으로 복원됐다. 기준(변이 없음)은 J1b의 같은 node 전부 통과다. 실시간 행(LAT·IDX-UI)은 R1·R2·R1b·R2b에서만 돌렸고, 나머지는 `--maxfail=3`과 `-k "not test_injected_latency_keeps and not test_idx_ui_tick_and_recording"`를 썼다. 결과 `mutations.jsonl` LF `fbc60485fb32a45c18b9f1e4056ecdc2cecd72c6340cf7a3ed7ff0aa86ab8b6d`.

| ID | 변이 | 실행 대상 | 결과 | 잡은 node(대표) |
| --- | --- | --- | --- | --- |
| R1 | `_prepare`(검증)를 첫 root mutex 안으로 | G15 2파일 | 검출 | HB2 before/after-verify, HB3 before-verify |
| R1b | R1, LAT·HB4만 | integration -k | 검출 11/19 | HB4 6행(구조), LAT seal1·seal3 4행 + LAT2-seal1(시간). seal0·0.2 행 5개는 통과 |
| R2 | 가득 찬 청크를 소비자가 `seal()`·`register_chunk` | G15 2파일 | 검출 | HB2 before-release, HB3 before-register·release |
| R2b | R2, LAT만 | integration -k | 검출 10/10 | LAT 전 행(구조: 소비자 seal·등록 0회) |
| R3 | 게시가 색인에 세션을 넣지 않음 + 색인 현재 판정에서 이름 목록 제거 | G15(비실시간) | 검출 | fc-same-tick-name-change, IDX-HB-projection-failed |
| R4 | `issued_descriptor`가 `_issued`·capability identity 무시 | G15 + storage | 검출 | reg-released-capability-verifies |
| R5 | `issued_descriptor`가 root 무시 | G15 + storage | **생존** | — (G15R-01) |
| R6 | 겹침 검사 제거 | G15 | 검출 | overlap-older-chunk, REG n0·n900 |
| R7 | capture 경로가 `.tmp-` 무시 | G15 + storage | 검출 | test_storage `…before_open[unfinished_intent]` |
| R8 | settle 창 0 | G15 | 검출 | fc-same-tick-name-change |
| R9 | settle 판정 뒤 stamp 재확인 제거 | G15 | 생존(동등 판단) | — |
| R10 | 실패 뒤 FIFO writer abort 제거 | G15 | **생존** | — (G15R-03) |
| R11 | capability 경로의 값싼 동일성 검사 제거 | G15 | 검출 | reg-descriptor-json-changed, reg-pcm-size-changed |
| R12 | 닫힌 Library 콜백이 None 대신 False(의도 없음) | G15 + storage | 검출 | fc-closed-callback |
| R13 | capture 경로가 DB 의도 행 무시 | G15 + storage | 검출 | test_storage `…before_open[db_only_intent]`(G15 파일은 못 잡음) |
| R14 | capture 경로가 journal 이름 무시 | G15 + storage | 검출 | fc-settled-listing-cache, IDX-HB-projection-failed |
| R15 | sealer가 `unhold()`하지 않음 | G15 | 검출 | HB1 before-register·after-release, HB2 before-verify |
| R16 | capture 이름 목록 캐시가 settle 전 목록도 재사용 | G15 + storage | **생존** | — (G15R-04) |

## 7. 판정 요약과 남는 위험

- **S0 0, S1 0, S2 0, S3 4(G15R-01~04) OPEN.** S0·S1 OPEN이 없어 이 검토 기준으로는 push를 막는 발견이 없다.
- 제품 불변식: 녹음 저장 경로가 AI·관리 작업과 독립이라는 목표는 이 PC 측정에서 크게 개선됐다(§5). 원본 트랙 보존·삭제 뒤 원본 부활은 반례를 찾지 못했다(§4.1·§4.2).
- 검토하지 않았거나 확인하지 못한 것(놓쳤을 수 있는 영역):
  - CI 러너(Python 3.11·3.13)의 실제 실행. Python 3.11은 검토자 probe의 겹침 SQL만 uv 3.11.15(SQLite 3.53.1)로 돌렸다. CI의 python.org 3.11 번들 SQLite에서 JSON1 동작은 실행하지 않았다.
  - settle 규칙의 FAT·exFAT·네트워크 볼륨, 시스템 시계 급변(계약 미검증 한계 그대로).
  - 다중 프로세스 동시 실행(두 번째 프로세스의 Library 열기 거부는 코드로만 확인).
  - 실장비 WASAPI 2트랙, 느린 디스크·백신 검사 환경, 전원 장애 내구성(I5는 fsync 순서·횟수 유지만 주장).
  - 3,600청크를 넘는 긴 세션에서 GUI tick `chunks()`의 mutex 밖 decode 비용(GIL)은 G15 범위 밖이라 재지 않았다.
  - 게시 단계 mkdir 뒤·rename 전 kill, `_prepare`의 descriptor 기록 중 kill 같은 추가 크래시 지점.
  - 외부 손상으로 색인이 무효인 상태의 GUI tick 0.50~0.60초 root 보유(§5)는 계약상 fail closed 동작이지만, 더 느린 PC에서는 거부로 이어질 수 있다.

## RECHECK 1 (G-P15b)

상태: **RECHECKED — 독립 재확인 1차, 2026-11-24.** 검토자는 1차와 같은 C00 배정 하위 에이전트(Claude), 작성자는 w5:p7 Claude다. 코드는 고치지 않았다. 이 절 추가 말고 저장소 쓰기는 없다. probe·변이 스크립트는 `build/review-trees/g15b-probe/`, 변이 사본은 `build/review-trees/g15b-mut/`에 있다.

**판정 요약.** G15R-01~04는 모두 **RECHECKED**(해소)다. 원 probe와 원 변이(R5·R10·R16, 원래 결함을 되돌린 B1·S1)를 다시 실행해 확인했다. 새 판정(구조·sealer 0.5초·보존)은 G-P15를 되돌린 회귀 변이 4종(검증을 mutex 안으로, seal을 소비자로, `_live` 색인 우회, capture 경로 journal 읽기)을 소비자 시간 상한 없이 모두 잡았다. 보존 조건은 거부 블록 회계 누락과 수락 블록 유실 변이를 모두 잡았다. **새 OPEN은 S3 1건(G15R-05, G-P07 귀속)**이다. S0·S1·S2는 없다.

### R1.1 입력 고정

| 항목 | 값 |
| --- | --- |
| 대상 | tree `2722c672ac4bb0d58825e9f2273d0e1ddf096243`(`git cat-file -t` = tree). HEAD `a57a517`(G-P07, `library.py`에 `job_authority` 추가) + G-P15b 5파일. `git diff a57a517 2722c672 --stat` = 5파일 527+/70- |
| 추출 | `git archive 2722c672 \| tar -x -C build/review-trees/g15b`, 변이 사본 `git archive 2722c672 pyproject.toml src tests` → `build/review-trees/g15b-mut` |
| 5파일 LF SHA256 | 배정 값과 일치: chunks.py `e289f3fd…`, recording.py `7a379d10…`, test_seal_phases.py `b006ee9a…`, test_seal_mutex.py `9c5cfc91…`, g15 문서 `46e8d4a4…`(`library.py`는 HEAD판 `39e63c8e…`) |
| 기존 리뷰 문서 | 이 절을 붙이기 전 LF `4f7bf3f9355531ec0ebabcd4d854f36a40713564d9887eec4bc3f0a0e4a86a87`(`90c6123`판과 같음) |

작성자는 `90c6123`(G-P07 전) `library.py`로 검증했다. **G-P07 `library.py`와 결합한 정확한 tree의 전체 회귀는 이 재확인이 처음 실행했다(RJ1).**

### R1.2 실행 명령과 결과

| # | 명령(사본 `g15b`, `.venv` Python 3.13.1) | 결과 |
| --- | --- | --- |
| RJ1 | CI core와 같은 `python -m pytest -q -p no:cacheprovider -W error::ResourceWarning --cov=recoryn --cov-branch --cov-report=term-missing --cov-report=json:coverage.json --cov-fail-under=85`, `PYTHONPATH=g15b\src`(자식 프로세스도 사본 import, 보고서에 `D:\project\Recoryn\src` 경로 0건), 고유 `TEMP`(`C:\Users\gangd\AppData\Local\Temp\g15r-b-full-4633915`)·`--basetemp`, offscreen | **20376 passed / failure 0 / error 0 / skip 0, 1225.41s, exit 0, 전체 coverage 92.74%**. JUnit LF `f89d4f558f9815f3d6ad2011db72cc191adbdf9245f9b5d6f85191334643681d`, 로그 LF `fab82cfb8c8227c4bbc810d299c6a65856c062e0f06ba3791407a51da98ca854`, `coverage.json` LF `8ea64303741523e5d74f5e50f1c365ae37805e2e1359386fe80035c657eef74a` |
| RJ2 | `python scripts/check_coverage.py coverage.json` | **전 묶음 PASS**: domain 100.00·100.00, capture 99.85·98.57, jobs 99.10·96.04, **storage 96.52·92.43**, security 98.11·94.43, content 99.59·98.75, all 94.18·88.38(line·branch %) |
| RJ3 | `ruff check --no-cache src tests scripts packaging` / `ruff format --no-cache --check …` / `MYPYPATH=src python -m mypy --no-incremental src/recoryn scripts packaging` | All checks passed / 177 files already formatted / **88 source files no issues** |
| RJ4 | 1차 probe 재실행(대상 src만 바꿈, `-I`) + 새 probe 5개 | R1.3·R1.5 |
| RJ5 | `mutate_b.py ../g15b-mut mutations.jsonl`(검토자 변이 14종, `PYTHONPATH`=사본 src + probe 폴더) | R1.4. 결과 LF `7179babc77e7bc3e8e6531d0b91778593b72d7adefad6987256a117141aa3ab5`. 모든 변이 뒤 3파일 hash 원본 복원 |

새 probe(`build/review-trees/g15b-probe/`, LF SHA256 앞 16자): `probe_cap_swap2.py` `703e388f9b8e01cc`, `probe_job_authority_settle.py` `f1d9930eddec8d8c`, `probe_desktop.py` `4b732ba0e2193a66`, `probe_job_recording.py` `d5a22ebbe22e229c`, `mutate_b.py` `85b51162af99f364`, `g15r_slow_sync.py`(pytest plugin, 모든 `chunks.sync` 앞에 `G15R_SYNC_DELAY`초) `9812b6c526cc0e8f`.

과정 고지: 첫 변이 실행을 V3 선택을 줄이려고 `TaskStop`으로 멈췄을 때, 적용 중이던 V1이 사본 `chunks.py`에 남았다(LF `228383fe…`). `git archive 2722c672 src/recoryn/storage/chunks.py`로 사본 파일만 되살려 `e289f3fd…`를 확인한 뒤 처음부터 다시 돌렸다. 남은 python 프로세스는 없었다. S1 변이의 pytest 자식은 180초 시간 제한에서 `subprocess.run`이 종료시켰다(검토자 스크립트가 만든 프로세스).

### R1.3 G15R-01~04 재확인

| ID | 판정 | 근거 |
| --- | --- | --- |
| G15R-01 | **RECHECKED** | `chunks.py:316-364`: `descriptor`는 읽기 전용 property(slot `_descriptor`), 발급 때 `_sealed`에 봉인 descriptor를 `_capability`와 같은 `_writers_lock` 구간에서 기록, `_bound`가 `candidate._descriptor is writer._sealed`를 요구, `issued_descriptor`는 `writer._sealed`를 돌려준다(root 조건 유지). 원 probe `probe_cap_swap.py`: 공개 setter가 `AttributeError`. 우회판 `probe_cap_swap2.py`(`object.__setattr__(cap, "_descriptor", orphan)`): `register_chunk(cap)` → `ValidationError: Invalid journal record`, 손상 고아 catalog 0. 변이 R5(root 조건 제거) → `G15-U-reg-other-root-verifies` 실패, B1(결속 제거 + 호출자 값 반환 = 원래 결함) → `G15-U-reg-swapped-descriptor-verifies` 실패. 남는 경로는 `_descriptor`와 `_writer._sealed`를 함께 바꾸는 private 조작뿐이라 같은 프로세스 오용의 한계로 수용한다 |
| G15R-02 | **RECHECKED** | `recording.py:157-169`(`try` 157, 정리 159-169): 두 시작이 한 `try`, 실패 시 살아 있는 sealer에 `_STOP`·join, 큐 닫기, 핸들 None. 원 probe `probe_thread_start.py`: 남은 thread 0, `is_live` False, 복구 `CREATED`, 삭제 `DELETED_LOCAL`, 프로세스 정상 종료(HEAD `0d846d6`와 같음). 변이 S1(정리 제거) → START 2행 실패 후 남은 non-daemon sealer 때문에 pytest가 끝나지 않아 180초 시간 초과(원래 증상 그대로 재현·검출) |
| G15R-03 | **RECHECKED** | 새 node `test_hb6_failed_verification_recovers_only_the_verified_prefix`(검증 prefix, 채택 바이트 = 블록 3·4, staging 1, INTERRUPTED)와 `test_sealer_failure_aborts_every_queued_writer_and_loses_no_appended_block`(FIFO 3 + 열린 writer, writer 5개 모두 비활성, staging 5 보존, 복구 56프레임 바이트 일치)이 계약 oracle을 고정한다. 원 probe `probe_hb6_recovery.py`·`probe_sealer_failure.py`(준비·등록 × 3번째 청크) 재실행 결과도 1차와 같다. 변이 R10(abort 제거) → FIFO-abort node 실패 |
| G15R-04 | **RECHECKED** | 새 행 `G15-U-fc-unsettled-listing-not-reused`(같은 tick 외부 자기 세션 의도 → append 거부). 변이 R16(`cached[3]` 조건 제거) → 그 행 실패 |

### R1.4 새 판정의 검출력(요청 2·3, J5)

소비자 보유 상한과 1트랙 거부 0 assert가 없어진 시험판(현재 tree) 그대로 실행했다. 남은 시간 판정은 sealer·관리·GUI tick·catalog 경로의 0.5초 상한뿐이다.

| ID | 변이 | 실행 | 결과 | 잡은 판정(대표) |
| --- | --- | --- | --- | --- |
| V1 | `_prepare`(검증)를 첫 root mutex 안으로(G-P15 되돌림) | G15 2파일 151 | **20 실패** | 구조: HB4 V 전·후 6행(관리가 seal을 기다림), HB2·HB3 V 전·후 4행, HB5 V 전·후 2행, IDX-HB V 전·후 2행, FIFO-abort. sealer 0.5초 상한: LAT seal1·seal3 × append 0·5ms 4행 + LAT2-seal1. 지연 0·0.2초 LAT 행은 통과(시간·구조 모두 못 잡음, 1차와 같음) |
| V2 | 가득 찬 청크를 소비자가 `seal()`·`register_chunk`(G-P15 되돌림) | G15 2파일 151 | **24 실패** | 구조: **LAT 10행 전부**(지연 0 행 포함, 소비자 seal·등록·검증·decode ≠ 0), IDX-UI, HB2·HB3·HB5, CRASH C6·C7 |
| V3 | `_indexed_journal`이 매번 전체 재검증(색인 우회, IX4 종류) | G15 2파일 중 IDX-SCALE 제외 135 | 3 실패 | 구조: **IDX-UI n1000 1·2트랙**(mutex 안 journal 읽기 ≠ 0), IDX-FAIL inplace_rewrite-get |
| V3b | V3, IDX-SCALE n100만 | 4 | 2 실패 | 구조: `create_session`·`get_session` n100(mutex 안 journal 읽기) |
| V4 | capture 경로 `_writer_intent`가 journal 전체를 연다(색인 우회, IX5 종류) | G15 2파일 151 | 10 실패 | IDX-IO1~4(녹음 중단), IDX-UI n1000 2행·IDX-SCALE register 3행(구조), FC settled-listing-cache |
| B1·R5·S1·R10·R16 | R1.3 | — | 모두 검출 | R1.3 |
| C1 | 거부 블록을 `dropped_frames`에 더하지 않음 | G15 2파일 + `test_app_service.py` + `test_recording_control.py` 172 | 2 실패 | G15 파일은 **못 잡음**(이 PC는 거부 0이라 해당 분기가 안 돈다). 기존 `test_full_queue_close_preserves_last_drop_and_cutoff`·`test_pause_is_acknowledged_after_drain_and_resume_uses_new_epoch`가 잡음 |
| C1s | C1 + `chunks.sync` 50ms 지연(plugin) | LAT·IDX-UI 14 | **14 실패** | `assert_conserved`(수락 + 탈락 = 제출, 탈락 = 거부) |
| C2 | 소비자가 수락한 블록 하나(sequence 150)를 버림 | G15 2파일 151 | 17 실패 | `assert_conserved`(저장 = 수락): LAT 10행·IDX-UI 4행 등 |
| P0 | 변이 없음 + `chunks.sync` 50ms 지연 | LAT·IDX-UI 14 | **14 통과** | 거부 285~2,030블록, 소비자 최장 0.108~0.137초, sealer 3.5~35.2ms, 소비자 seal·등록·검증·decode·mutex 안 journal 읽기 모두 0, 보존 성립 |

보존 조건 `assert_conserved` 판단(요청 3):
- 트랙별 "수락 + 탈락 = 제출(시험이 센 수)"과 "탈락 = 시험이 센 거부 수"가 함께 있다. 그래서 거부 블록이 회계에서 빠지거나(C1s), `_accepting` 해제 같은 다른 이유로 거부된 블록이 탈락으로 둔갑하면 실패한다. gap 사유는 모두 `QUEUE_DROP`이어야 하고, 잘리지 않았으면 gap 프레임 합 = 탈락이다.
- "저장 프레임 = 수락 프레임 합"은 catalog(finalize 결과)와 큐 회계라는 서로 다른 두 기록을 대조한다. 그래서 수락 뒤 유실(C2)을 잡는다.
- 한계(발견 아님):
  - 저장은 **트랙 합**만 대조한다. 트랙별 저장 = 수락은 보지 않는다(트랙 사이에서 상쇄되는 오류는 못 잡는다. 겹침 검사가 중복을 막아 현실적 위험은 낮다).
  - 바이트 대조가 없다(프레임 수만 본다).
  - 거부가 없는 빠른 디스크에서는 탈락 회계 분기를 G15 파일이 실행하지 않는다(기존 시험이 덮는다).
  - 소비자 처리량 회귀(append 비용 증가)는 이제 어떤 시험도 실패시키지 않고 측정으로만 남는다. C00 결정대로이며 G-P17에서 다룬다. 다만 append당 SQLite 연결 재개 같은 구조적 회귀는 `test_append_deletion_check`의 연결 수 판정이 잡는다.

### R1.5 G-P07(a57a517)과의 결합(요청 4)

- **desktop STOPPING·ACK 경로**(`probe_desktop.py`, 실제 `DesktopRecorder` + 가짜 장치 1트랙, 400블록 = 2청크):

  | 경우 | `stop()` | 정지 직후 progress | `is_live` | 정지 대기 중 복구·확정 | `close()` 뒤 | thread | 저장 |
  | --- | --- | --- | --- | --- | --- | --- | --- |
  | `_prepare` 3초 지연 | `WRITER_ACK_PENDING` | STOPPING, ack_pending True | True | `Live writer cannot be recovered` / `SESSION_LIVE` | ENDED, ack_pending False, FINALIZED | 0 | 192,000 = 수락 192,000 |
  | 둘째 등록 실패 | `STORAGE_FAILED_PARTIAL_MEDIA_PRESERVED` | STOPPING, storage_failed True, ack_pending True | False | — | STOPPING·ack_pending True 유지(표시는 `storage_failed`가 우선) | 0 | 복구 뒤 192,000 = 수락 |

  sealer 수명·drain·`is_live`는 G-P07 control mode와 맞게 동작했다. 저장 실패 뒤 `close()`가 ack_pending을 지우지 않는 것은 G-P07의 표시 상태다. `capture_status`가 `storage_failed`를 먼저 보여 사용자 문구에는 영향이 없다고 판단해 발견으로 올리지 않는다.
- **Job 전이와 녹음**(`probe_job_recording.py`, 완료 삭제 1,000건, 12초 실시간): Job 스레드가 `claim`·`fail`·`resume`을 반복했다. 매번 `Library.job_authority`를 지나며, 실행마다 99~1,194회 root mutex를 잡았다. Job 스레드 최장 보유 1.7~3.7ms였고, 1·2트랙 모두 거부 0·유실 0·보존 성립이었다. 결과 LF `97360c688c28036c4cf1505133354d2f45076a9ab78d428b8211f1f7cbaf8b22`. probe의 Job 순환은 2회 뒤 `JOB_NOT_RESUMABLE`로 멈춰 대부분 `claim` 거부 경로였다. 그 경로도 `job_authority`를 지난다. 참고: `job_authority`는 호출자의 JobStore transaction(commit 포함)이 끝날 때까지 root mutex를 쥔다(`library.py:237-288`, mutex 구간 안의 `yield state`). 이 PC에서는 짧았지만 느린 디스크에서는 append fsync처럼 디스크 지연을 따른다(G-P17·G-P07 범위, 측정만).
- **G-P07이 G-P15 색인을 갱신하는 경로** → 아래 G15R-05.

### G15R-05 (S3, OPEN, G-P07 귀속) — `job_authority`가 G-P15 색인을 settle로 표시하는 기준 시각이 목록을 만든 뒤다

- 근거: `library.py:196-288`(a57a517 추가) `job_authority`는 mutex 밖 선읽기(`_journal_prefetch`, `:220`)로 journal을 읽는다. 그 뒤 mutex 안에서 `_history_version`과 stamp가 같으면 G-P15 색인(`_intent_journal`·`_intent_stamp`·`_intent_names`)을 그 결과로 바꾸고 `_intent_settled = settled`(`:255`)로 둔다. 그런데 `settled`는 선읽기가 **끝난 뒤** 시각으로 계산한다(`:236` `time.time_ns() - stamp[2] > _STAMP_SETTLE_NS`). G-P15의 settle 규칙(`_list_journal`)은 **목록을 만들기 전** 시각이 mtime보다 2.5초 넘게 늦어야 한다. 목록이 mtime과 같은 tick에서 시작되고 선읽기가 2.5초 넘게 걸리면(완료 삭제 1,000건 냉 읽기 2.4~4.0초, G05 검토 측정) 같은 tick의 외부 변경을 놓친 목록이 settle로 표시된다. 그 뒤 `_index_current()`는 stat 1회로 색인을 믿고, capture 경로(`_writer_intent`)도 그 이름 집합을 쓴다. `reuse` 경로에서도 `_intent_settled`를 덮어쓴다.
- 재현(`probe_job_authority_settle.py`, 외부 변경 시뮬레이션은 작성자 FC 시험과 같은 `os.utime` mtime 복원):
  1. 녹음 세션 `rec`의 writer가 열려 있다.
  2. 외부에서 `ext.json`을 추가한다.
  3. `job_authority`의 선읽기 안에서, 목록을 만든 뒤 외부가 같은 tick에 `rec.json`(녹음 중 세션의 삭제 의도)을 추가하고, 선읽기가 3초 걸린다.
  4. writer가 다시 append한다.

  | 모드 | 색인 settled | 색인 이름에 `rec.json` | 다음 append |
  | --- | --- | --- | --- |
  | control(`job_authority` 없음, 같은 외부 변경) | — | — | 거부 `Writer session has a deletion intent` |
  | `job_authority` 실행 | True | 없음 | **ACCEPTED — 의도 뒤 쓰기(I1 위반)** |

- 기대: G-P15 색인을 갱신하는 모든 경로는 settle 규칙(목록 전 시각 기준)을 따르거나 settle을 표시하지 않아야 한다. 예:
  - `job_authority`가 `_intent_settled = False`로만 두고, `_index_current`가 자기 목록으로 settle하게 한다.
  - 또는 선읽기 시작 전에 시각을 잰다.
- 영향: Library를 거치지 않는 외부 변경이 같은 mtime tick에 두 번 있고 선읽기가 2.5초를 넘을 때만 생긴다(계약 §14.3 단일 writer 계약 밖). 같은 프로세스 게시는 `_history_version` 대조가 막는다. 그래서 S3다. 코드 소유는 G-P07(`library.py`)이지만 G-P15의 I1 근거(§14.2·§14.3)를 약하게 하므로 여기에 기록한다. G-P07 검토 결과와 함께 처리 단위를 C00이 정해야 한다.

### R1.6 작성자 관찰 2건에 대한 의견(요청 6)

1. **외부 손상으로 색인이 무효일 때 GUI tick root 보유 0.5~0.6초**
   - 작성자 권고 (가) "같은 stamp 동안 실패 결과 캐시"에 동의한다. fail closed가 유지되고 비용이 stat 1회로 줄어든다.
   - 조건: 실패 캐시도 G-P15 settle 규칙을 따라야 한다. 실패를 관찰한 목록이 settle 전이면 질의마다 다시 시도한다. 그래야 같은 tick 안의 손상 복구가 보인다. 결과가 오래 실패 쪽으로 남는 것은 안전 쪽이라 괜찮다.
   - capture 경로(이름만 사용)에는 적용하지 않는다(G05R-04 해소 유지).
   - G15R-05와 같은 종류의 실수(목록 뒤 시각으로 settle)를 피해야 하고, `job_authority`가 이 캐시를 덮어쓰지 않게 해야 한다.
   - `library.py`가 이제 G-P07과 공유되므로 소유 단위를 정한 뒤 진행하는 것이 맞다.
2. **GC-P02 구조 판정과 `_live` 이름 목록 충돌 위험**
   - 작성자 권고(단기 (가) 예외, 후속 (나) mutex 밖 목록)에 동의한다.
   - (가)는 계수기에서 `deletion-journal` 경로의 `os.scandir` 이름 목록만 예외로 두는 좁은 규칙이어야 한다. 폴더 순회·`remove_tree`·다른 경로의 `iterdir`은 계속 금지한다.
   - (나)는 mutex 밖 목록을 쓰려면 "목록 전 시각 기록 → 목록 → mutex 안 stamp 재확인"을 지켜야 한다. G15R-05는 이 순서를 어긴 실제 사례다.

### R1.7 남는 위험과 놓쳤을 수 있는 영역

- CI 러너(3.11·3.13)에서의 실제 실행은 하지 않았다. 느린 디스크는 fsync 앞 지연 주입으로만 흉내 냈다(50ms, LAT·IDX-UI 14행).
- 소비자 append의 mutex 안 fsync가 정하는 처리량 한계(CI에서 1트랙도 거부)는 측정으로만 남았다. G-P17 전까지 실제 느린 디스크에서 녹음 유실이 날 수 있다는 것이 남는 제품 위험이다(유실은 `QUEUE_DROP`으로 기록됨).
- `job_authority`의 root mutex 보유가 JobStore commit을 포함하는 점은 이 PC에서만 쟀다(최장 3.7ms).
- 1차 §7의 미검증 항목(FAT·exFAT·네트워크 볼륨, 다중 프로세스, 실장비, 전원 장애, 추가 크래시 지점)은 그대로다.
