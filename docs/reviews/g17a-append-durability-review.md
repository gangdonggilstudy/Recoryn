# G17R / G-P17a 녹음 append의 fsync를 root mutex 밖으로 독립 검토

상태: **REVIEW_READY — 독립 검토 1차, 2026-11-25.** 작성자는 w5:p8 Codex이고, 검토자는 C00이 배정한 하위 에이전트(Claude)다. 검토자는 코드를 고치지 않았다. 저장소 쓰기는 이 문서 하나다. 반례·측정·변이 스크립트는 `build/review-trees/g17a-probe/`, 변이 사본은 `build/review-trees/g17a-mut/`, 비교용 HEAD 사본은 `build/review-trees/g17a-head/`에 있다. 최종 수용과 push 게이트 판단은 C00이 한다. C00 지시에 따라 녹음 유실·원본 손상·I1 위반·원본 부활은 S1 이상으로 분류했다.

**요약.**
- 확인 수단: 코드 읽기, CI와 같은 전체 회귀(26488 PASS, coverage 92.66%, 7묶음 PASS), 검토자 probe 9종, HEAD `47530a2` 대조 측정, 검토자 변이.
- I1(삭제 의도 뒤 새 미디어 쓰기 0)·원본 부활 0·크래시 prefix 복구·잠금 순서·외부 SQLite 잠금 해소는 확인했다. 외부 잠금 3초에서 HEAD는 1트랙 14·26블록, 2트랙 287·285블록을 거부했고, 17a는 모두 0이었다.
- **OPEN은 S1 2건**이다.
  - G17R-01(S1, 17a 회귀): 느린 fsync에서 소비자의 블록당 비용이 HEAD보다 약 1ms(약 10%) 늘어, HEAD가 거부 0인 조건에서 17a는 거부한다. 1트랙 fsync 5ms 주입 시 HEAD 0·0·0·0 대 17a 27·40·46·203블록이다.
  - G17R-02(S1, **기존 결함 — 17a 회귀 아님**, HEAD 동일): 봉인 직후 등록의 동일성 검사나 seal read-back이 한 번의 일시 `PermissionError`를 만나면 녹음 전체가 중단된다.
- S2·S3는 없다.
- 변이는 실행 중이다(이 문서 작성 시점에 A1~A3 검출, 나머지 진행 중. 결과 파일 `mutations.jsonl`).
- 신규 4파일 단독 시간: **83.50초·80.62초**(1,182 PASS). 60초 예산 초과이고 작성자 요청 90초 안이다.

## 1. 입력 고정

| 항목 | 값 |
| --- | --- |
| 대상 | tree `2fd2bbf8a26899f920c865f33c0c353727712310`(`git cat-file -t` = tree) = HEAD `47530a2` + 9파일. `git diff 47530a2 2fd2bbf8 --stat` = 9파일 3160+/85- |
| 9파일 LF SHA256 | chunks.py `ef000edf…c7cb5`, _coordination.py `5bac3d36…be5d`, library.py `c391a4e1…f45`, test_storage.py `c1c96ede…792a68`, 문서 `b476d049ae79b34eaf77ffca07b0672307d0c568cb8fac08e6264f17b505d737`. 작성자 §20.4·배정 값과 일치 |
| 추출 | `git archive 2fd2bbf8 \| tar -x -C build/review-trees/g17a`, HEAD `git archive 47530a2` → `g17a-head`, 변이 사본 `git archive 2fd2bbf8 pyproject.toml src tests` → `g17a-mut` |
| 환경 | Windows 11 Pro 10.0.26300, `.venv` Python 3.13.1, offscreen Qt. 실제 장치·모델·네트워크·유료 호출·Credential Manager 쓰기 없음. kill한 프로세스는 검토자 probe가 만든 자식뿐 |

## 2. 실행 명령과 결과

| # | 명령(사본 `g17a`) | 결과 |
| --- | --- | --- |
| J1 | CI core와 같은 `python -m pytest -q -p no:cacheprovider -W error::ResourceWarning --cov=recoryn --cov-branch --cov-report=term-missing --cov-report=json:coverage.json --cov-fail-under=85`(+`--durations=25`), `PYTHONPATH=g17a\src`(자식도 사본 import, 보고서에 `D:\project\Recoryn\src` 0건), 고유 `TEMP`·`--basetemp`, offscreen | **26488 passed / failure 0 / error 0 / skip 0, 1992.04s, exit 0, 전체 coverage 92.66%**. JUnit LF `4c59609418eb19c5eeef7e5e6e8bf9cdcfa5faada21a47ddc8495455026d60ea`, 로그 LF `16c9d3baebd03e75cc242c9cb7e84af0053cd7a277cccf45de61adee6c0a49c4`, `coverage.json` LF `27a9c9a51c8a1252f3b3fad0f35223c18dd9adf4f24d4e58b055c22b86f5bc15` |
| J2 | `python scripts/check_coverage.py coverage.json` | **7묶음 PASS**: domain 99.18·97.89, capture 99.85·98.57, jobs 99.19·95.61, storage 96.15·91.46, security 98.11·94.43, content 98.98·99.02, all 94.01·88.68(line·branch %) |
| J3 | `ruff check --no-cache src tests scripts packaging` / `ruff format --no-cache --check …` / `MYPYPATH=src python -m mypy --no-incremental src/recoryn scripts packaging` | All checks passed / 209 files already formatted / **93 source files no issues** |
| J4 | 신규 4파일 단독(`-p no:cacheprovider -W error::ResourceWarning`, coverage 없음, 다른 실행 없음) 2회 | **1182 passed, 83.50s / 80.62s**. 파일별 합: fencing 48.2·46.5s, crash 28.4·27.5s, property 5.2·5.1s, unit 0.9·0.9s. JUnit LF `11af58aa816b2643…`, `39de40824df11ce9…` |
| J5 | 검토자 probe(§3)와 HEAD 대조 측정(§4). 측정은 다른 시험·변이가 돌지 않을 때 순차 교대 실행 | 아래 |
| J6 | `mutate_g17.py ../g17a-mut mutations.jsonl`(검토자 변이 8종) | §5(진행 중) |

probe(`build/review-trees/g17a-probe/`, LF SHA256 앞 16자): `probe_g17_fence.py` `f11651869acc6bf1`, `probe_g17_crash.py` `31308ea5189bf60d`, `probe_g17.py` `22f3ab5026d96910`, `run_measure.sh` `0ca44053113d366d`, `probe_g17_append_cost.py` `c6c13a6b9c2f4d27`, `probe_g17_append_cost2.py` `dfef985a752e27bc`, `probe_g17_identity_transient.py` `fea1c46cf3ea95e3`, `probe_g17_readback_transient.py` `8a24fa0a5f4833ab`, `mutate_g17.py` `43483c51e4d75638`.

## 3. 중점별 판정

### 3.1 I1과 원본 부활 0(중점 1)

- 코드(chunks.py `_append`):
  - root 안 검사 + `WP` → 밖 `SP` → root 안 재검사 + `WJ` → 밖 `SJ` → root 안 재검사 + 상태 갱신 순서다.
  - `_open`(staging mkdir·파일 생성), descriptor 생성·쓰기, `_publish`(mkdir·rename)도 root 안에서 `_check_media_write`(삭제 권위 + closing) 뒤에 한다.
  - 파일 handle은 `open_file`의 unbuffered FileIO라 fsync·close가 새 논리 바이트를 쓰지 않는다. 계약 §3.1의 "D 전에 넘긴 바이트의 fsync 완료 허용"과 맞다.
- `probe_g17_fence.py`: 블록 1의 `SP`·`SJ` 안에서 멈춘 채 다른 thread가 사건을 일으켰다.

  | 지점 | 사건 | 관찰 |
  | --- | --- | --- |
  | SP | 삭제 | 첫 답 `DELETE_PENDING`. 의도 시점 크기 [pcm 16, journal 563] → 해제 뒤 **[16, 563] 그대로**. append는 `StateConflict: Writer session has a deletion intent`. abort 뒤 재시도 `DELETED_LOCAL`, 폴더 없음, 복구 `DELETE_PENDING`·폴더 재생성 없음 |
  | SJ | 삭제 | 의도 시점 [16, 1134] → **[16, 1134] 그대로**, append `StateConflict`, 이하 같음 |
  | SP·SJ | abort | abort가 멈춘 sync가 끝나기 전에 반환하지 않았다(handle을 sync 중에 닫지 않음). 그동안 `has_active_writer` 참, append는 `Writer is closing` |
  | SP·SJ | 복구·확정 | `Live writer cannot be recovered` / `SESSION_LIVE`. 해제 뒤 append OK |

- G-P15 sealer의 seal(`_prepare`의 `_sync` → descriptor → read-back → publish)도 같은 guard를 지난다.
- 다른 트랙 writer는 각자 작업 잠금이라 서로 기다리지 않는다(작성자 L·HB family, J1 통과).
- 판정: 반례를 찾지 못했다.

### 3.2 크래시 지점(중점 2)

`probe_g17_crash.py`: 자식이 블록 0~2를 append한 뒤 블록 3의 지점에서 멈추고, 부모가 kill한 뒤 복구했다.

| 지점 | staging pcm·journal 기록 | 복구 | catalog frame(손계산) | 바이트 | 재복구 |
| --- | --- | --- | --- | --- | --- |
| SP 안(payload 3 쓰기 뒤) | 32B·3 | `STAGING_TAIL_NOT_ADOPTED` | 12(12) | 일치 | 0 |
| WJ 전(payload 3 sync 뒤) | 32B·3 | `STAGING_TAIL_NOT_ADOPTED` | 12(12) | 일치 | 0 |
| SJ 안(journal 3 쓰기 뒤) | 32B·4 | 경고 없음 | 16(16) | 일치 | 0 |
| SJ 뒤·완료 갱신 전 | 32B·4 | 경고 없음 | 16(16) | 일치 | 0 |

journal에 없는 payload 꼬리는 채택하지 않고, 검증된 prefix만 보존한다. 작성자의 C family 78행(실제 kill 26회)도 J1에서 통과했다. 전원 장애는 검증하지 않았다(계약대로 NOT_RUN).

### 3.3 잠금 순서·교착(중점 3)

- 순서는 writer 작업 RLock → root → `_writers_lock`(registry)이다. 역순 경로는 찾지 못했다.
  - `abort`는 registry를 잠깐 잡아 closing만 표시하고 놓은 뒤 작업 잠금을 기다린다.
  - `has_active_writer`(root 아래)는 registry만 쓴다.
  - Library는 root를 쥔 채 writer 작업 잠금을 기다리지 않는다. `_salvage`는 `writer.append`·`seal`을 root 밖에서 부른다.
  - RecordingService `_gate`를 쥔 채 writer 호출하는 경로는 없다(`_fail`은 root 밖).
- G-P15 결합: `_seal_in_progress`가 read-back 동안 active를 유지한다. 실패 시 hold된 writer는 `unhold`까지 `_sealing`을 유지한다(G15 시험 전부 J1 통과).
- G-P08 건강 checkpoint는 소비자 thread에서 root 밖으로 Library 호출을 한다. 외부 잠금 측정(§4)에서 거부 0이라 이 경로가 소비자를 멈추지 않음을 확인했다.

### 3.4 register_chunk bounded 재시도(중점 4)

- 시도마다 다음을 root 안에서 처음부터 다시 판정한다: capability 재확인(`issued_descriptor(candidate) != sealed`이면 거부), claim, `_writer_intent`, 같은 ID·FINALIZED·겹침, insert.
- `busy_timeout=0`으로 바로 실패하고, `finally`에서 원래 값을 복원한다. BUSY·LOCKED만 재시도하고, 기다림은 root 밖 10ms다. 기한은 원래 busy_timeout(5초)을 monotonic으로 잰다.
- 그동안 sealer는 writer를 hold하므로 active·`WRITER_ACK_PENDING` 의미가 유지된다.
- 등록 순서: FIFO의 다음 청크는 같은 sealer thread라 앞 등록이 끝나야 시작한다.
- 일시 오류의 고착: 재시도 상태를 저장하지 않는다. 기한을 넘기면 그 호출만 실패한다(기존 저장 실패 경로).
- 다만 SQLite가 아닌 일시 `OSError`(동일성 검사의 파일 열기)는 재시도 대상이 아니다. 그 한 번으로 녹음이 멈추는 것은 기존 결함이다 → G17R-02.

### 3.5 test_storage.py 적응(중점 5)

`test_p11_open_delete_barrier[False]` 한 곳만 바뀌었다(5줄): `future.result()`를 감싸 "성공 또는 정확히 `Writer session has a deletion intent`"를 허용한다. 삭제 `DELETE_PENDING`, 봉인 거부, abort 뒤 삭제 완료, 경로 부재의 기존 단언은 그대로다. 최소 적응이며 승인 범위와 같다.

## 4. 측정 재현(중점 6)

- 조건: 실제 `RecordingService`, 100블록/초/트랙 × 480프레임, 기본 2초 청크, 큐 256, 250ms GUI tick 대리, 12초 실시간.
- HEAD 사본과 17a 사본을 같은 스크립트로 번갈아 순차 실행했다(다른 실행 없음).
- 모든 행에서 저장 = (제출 − 거부) × 480이었고, 거부가 있는 행의 gap 사유는 모두 `QUEUE_DROP`이었다.
- 결과 LF: `measure.jsonl` `1dabcd895048e04780ec2575b0341315a5f6e8bd8df2a18cec9a8c76cd3e9ba0`, `measure2.jsonl` `a506e4635b3c35d6f06efeb827add9165da710823564f532d8aa1a6860af6c7e`, `cost.jsonl` `074df8472396e179740a519799634ff11577efac59e0cd15e95469edb2737385`, `cost2.jsonl` `fd6c25638dc3081be90ad547ec2b06d44aa59c611624337c0c047fcbeff17a3a`.

| 조건 | HEAD 거부(회차별) | 17a 거부 | HEAD sealer root 최장 | 17a sealer root 최장 | 소비자 root p50 HEAD / 17a |
| --- | --- | --- | ---: | ---: | --- |
| 외부 `BEGIN EXCLUSIVE` 3초, 1트랙 | 14, 26 | **0, 0** | 2,698.8·2,830.0ms | 44.4·3.3ms | 4.14·1.44 / 0.51·0.48ms |
| 외부 잠금 3초, 2트랙 | 287, 285 | **0, 0** | 2,693.1·2,698.5ms | 33.9·6.9ms | 4.48·1.38 / 0.43·0.39ms |
| fsync 앞 5ms 지연, 1트랙 | **0, 0, 0, 0** | **27, 40, 46, 203** | 3.2~3.8ms | 3.9~4.5ms | 12.0 / 0.4~0.5ms |
| fsync 5ms, 2트랙 | 1,224 | 1,476 | 3.8 | 4.6 | — |
| fsync 20ms, 1트랙 | 693 | 699 | 3.9 | 6.2 | — |
| 지연 없음, 2트랙(반복 4) | 159, 0, 0, 0 | 256, 0, 0, 0 | — | — | — |
| 지연 없음, 2트랙, 완료 삭제 1,000 | 196 | 322 | — | — | — |

append 1회 비용(`probe_g17_append_cost2.py`, 단일 writer 2,000회, Library 열림):

| fsync 지연 | HEAD 중앙값 | 17a 중앙값 | 17a root 보유/append |
| --- | --- | --- | --- |
| 0 | 5.43·6.22ms | 6.25·5.92ms | 1.33·1.43ms(HEAD 5.47·5.79) |
| 5ms | 12.08·11.92ms | **13.17·12.79ms** | 1.57·1.23ms(HEAD 12.95·12.01) |

`check_write_allowed` 1회(Library 콜백) 중앙값은 0.40ms였다. 17a는 블록당 3회, HEAD는 1회 부른다.

## 5. mutation(중점 8, J6 — 진행 중)

| ID | 변이 | 결과 |
| --- | --- | --- |
| A1 | journal 쓰기 전 권위 재검사 제거 | **검출**(5 실패에서 중단, maxfail 5) |
| A2 | payload fsync를 root 안으로 | **검출**(5 실패) |
| A3 | abort가 작업 잠금을 기다리지 않고 닫음 | **검출**(5 실패) |
| A4 | `has_active_writer`가 `_seal_in_progress` 무시 | 실행 중 |
| A5 | 완료 갱신 전 권위 재검사 제거 | 실행 중 |
| A6 | 등록 재시도가 capability를 다시 확인하지 않음 | 실행 중 |
| A7 | 등록 뒤 busy_timeout 복원 안 함 | 실행 중 |
| A8 | BUSY·LOCKED가 아닌 OperationalError도 재시도 | 실행 중 |

최종 결과는 `build/review-trees/g17a-probe/mutations.jsonl`·`mutate.log`에 남는다. 이 문서의 판정은 A1~A3까지만 근거로 한다.

## 6. 발견

### G17R-01 (S1, OPEN, 17a 회귀) — 느린 fsync에서 소비자 블록당 비용이 늘어 HEAD가 거부 0인 조건에서 녹음 블록을 거부한다

- 근거:
  - 17a의 `_append`는 블록마다 root를 세 번 잡고, 매번 `_check_media_write` → `check_write_allowed`(Library 콜백 `_writer_intent`: `PRAGMA user_version`·journal stat·자기 세션 DB 조회)를 부른다(chunks.py `_append`의 세 `with root_mutex` 구간). HEAD는 블록당 한 번이다.
  - 검사 1회가 0.40ms이므로 2회가 늘면 약 0.8ms다. 여기에 잠금 재획득·`hash.copy()`가 더해진다.
  - 실제로 fsync 5ms 주입 시 append 중앙값이 HEAD 11.9~12.1ms에서 17a 12.8~13.2ms로 약 1ms(약 9%) 늘었다.
  - 소비자는 여전히 블록당 두 fsync를 직렬로 기다린다(17a 계약). 그래서 실시간 예산(10ms/블록) 근처에서는 이 증가가 그대로 큐 적체로 간다.
- 재현(§4 표, `run_measure.sh`·반복 3회): 1트랙, 각 `chunks.sync` 앞 5ms 지연, 12초 실시간.
  - HEAD 거부 0·0·0·0, 17a 거부 27·40·46·203블록(0.27~2.03초 녹음 유실, `QUEUE_DROP`으로 기록, 보존 조건은 성립).
  - 2트랙 5ms(1,224 대 1,476)와 완료 삭제 1,000건 2트랙(196 대 322)도 17a가 더 많다. 20ms에서는 둘 다 포화라 비슷하다(693 대 699).
- 기대: 17a는 처리량 개선을 주장하지 않지만(17b 몫), 저장 경로의 처리량을 **떨어뜨려서는 안 된다**. 계약 §15.2에도 "소비자 thread는 여전히 블록마다 두 sync를 직렬로 기다린다"고만 적었고, 손실 증가는 계약에 없다.
- 영향: HDD·백신 검사처럼 fsync가 수 ms인 환경의 포화 직전 구간에서, HEAD보다 녹음 유실이 늘어난다. HEAD도 5ms에서는 블록당 12ms로 이미 예산을 넘는다. 그래서 더 긴 녹음에서는 둘 다 유실하고, 17a가 더 빨리·더 많이 유실한다. C00 기준(녹음 유실 S1 이상)에 따라 S1이다.
- 권고(I1 유지):
  - WJ 앞·완료 앞 재검사를 값싼 형태로 바꾼다. 예: 첫 검사(WP 앞, 전체 권위 판정) 때 Library의 in-process 의도 세대(`_history_version` 또는 동등한 단조 카운터)를 기록하고, 이후 두 검사는 root 안에서 그 세대가 같고 closing이 아닌지만 본다(정수 비교).
  - 같은 프로세스의 의도 게시는 모두 root 안에서 세대를 올린다(§14.2 G15). 그러므로 같은 세대이면 그 사이 새 의도가 없었음이 보장된다. 외부 변경은 단일 writer 계약 밖이고, 다음 블록의 첫 검사가 그대로 본다.
  - 수정 뒤 이 측정(1트랙 5ms, 2트랙 지연 없음·완료 삭제 1,000)을 HEAD 대비 같거나 나은 값으로 다시 확인해야 한다.

### G17R-02 (S1, OPEN, **기존 결함 — 17a 회귀 아님**) — 봉인 직후 파일을 다시 여는 단계의 일시 `PermissionError` 한 번으로 녹음 전체가 중단된다

- 근거:
  - sealer는 publish(rename) 직후 `Library._check_sealed_identity`로 `descriptor.json`·`audio.pcm`을 연다. 그 직전에는 `_prepare`의 read-back(`scan_prefix`)으로 staging의 `blocks.jsonl`·`audio.pcm`을 다시 연다.
  - 이 열기의 `OSError`는 재시도 없이 sealer 실패 → `_fail` → 녹음 중단(`storage_failed`, INTERRUPTED)이다.
  - G05R-04는 Windows에서 rename으로 게시한 파일의 첫 열기가 잠깐 `PermissionError`를 내는 현상을 실제로 관측했다. C00은 같은 계열의 일시 오류가 핵심 기능을 막은 GS02R-01을 S1로 올렸다.
  - 17a는 SQLite BUSY·LOCKED만 bounded 재시도로 바꿨고, 이 파일 열기는 그대로다.
- 재현(1트랙, 3블록 청크, 60블록 제출):

  | 주입 | tree | 결과 |
  | --- | --- | --- |
  | `probe_g17_identity_transient.py`: sealer의 첫 `descriptor.json` 열기 1회 `PermissionError` | HEAD | `storage_failed`, INTERRUPTED, 수락 6블록 뒤 **54블록 거부**(녹음 중단). 복구 뒤 수락 24프레임 보존 |
  | 같음 | 17a | 같음 |
  | `probe_g17_readback_transient.py`: seal read-back의 `blocks.jsonl` 열기 1회 | HEAD | 수락 4블록 뒤 **56블록 거부** |
  | 같음 | 17a | 같음 |

- 기대: 일시 파일 열기 거부는 그 시도만 실패해야 하고, 녹음을 끝내면 안 된다. 예: 동일성 검사·read-back의 `PermissionError`·sharing violation을 SQLite busy와 같은 bounded 재시도(root 밖, 짧은 기한)로 처리한다. 기한을 넘긴 경우만 지금처럼 저장 실패로 처리한다.
- 영향: 수락한 원본은 보존된다(복구 일치). 그러나 그 뒤의 녹음이 끝난다. HEAD와 같으므로 17a의 push 차단 여부와 처리 단위는 C00이 정할 일이다. 17a 회귀는 아니다.

## 7. 남는 위험과 놓쳤을 수 있는 영역

- 신규 4파일 단독 80.6~83.5초: 60초 예산을 넘는다. 90초 요청 안이며, 대부분 fencing(약 47초)·crash(약 28초)다.
- CI 러너, 실제 HDD·백신·전원 장애, 다중 프로세스는 실행하지 않았다.
- 오늘 이 PC의 디스크는 지연 없이도 append 5~6ms로 느렸다. 지연 없는 2트랙 행의 첫 회(HEAD 159·17a 256)는 이 상태의 영향이고 이후 3회는 둘 다 0이었다. 그래서 G17R-01의 판정은 주입 지연 행과 append 비용 측정에 둔다.
- 변이 A4~A8의 결과는 이 문서 작성 시점에 확정되지 않았다(아래 RECHECK 1의 갱신 표 참고).

## RECHECK 1 (G-P17a FIX1)

상태: **RECHECKED — 독립 재확인 1차, 2026-11-26.**
- 작성자는 w5:p8 Codex, 검토자는 1차와 같은 C00 배정 하위 에이전트(Claude)다. 코드는 고치지 않았다. 저장소 쓰기는 이 절뿐이다(앞서 붙인 "중간 기록"을 이 최종 판정으로 바꿨다).
- probe·변이·측정은 `build/review-trees/g17b-probe/`, 변이 사본은 `g17b-mut/`, 비교용 HEAD 사본은 `g17b-head/`(f4f94b7)에 있다.

**판정 요약.**
- **G17R-01·G17R-02 모두 RECHECKED**(해소)다.
  - 1트랙 fsync 5ms 4회에서 HEAD 0·0·0·0 대 FIX1 0·0·0·0이다.
  - 일시 공유 거부 원 반례 2개는 녹음 지속·거부 0이다.
- 지속 거부 상한 재시도의 "수락 뒤 손실"(C00 항목 4)은 기본 설정에서 HEAD 대비 증가 근거가 없어 **기록만** 남긴다.
- **새 OPEN은 S2 1건(G17R-03)과 S3 1건(G17R-04)**이다. S0·S1은 없다.
  - G17R-03(S2): G17 자체 시험 `G17-R-02`가 블록 거부가 겹치면 실패한다. 원인은 G-P08 최종 건강 기록의 drop 0과 시험 oracle의 불일치이고, HEAD도 같다. CI에서 실패할 위험이 높다.
  - G17R-04(S3): 변이 A4가 생존한다. 1차의 "A4 검출"은 R-02의 부하 실패를 잘못 센 것이다.

### R1.1 입력 고정

| 항목 | 값 |
| --- | --- |
| 대상 | tree `e81be084212e213af3b4ae30706939c96c474741` = **HEAD `f4f94b7`(G-P11d)** + G-P17a 9파일. `git diff f4f94b7 e81be084 --stat` = 9파일. 배정 메시지의 47530a2는 C00이 오기로 정정했다 |
| 수정 6파일 LF SHA256 | chunks.py `e499f0bdd5c7bb8c2b427836159edda5508ec0d3a63df3be9b6e9b158986f316`, _coordination.py `b0d86a066d80f6e1af45a80e31cd90101d9ca060dacd4ea18e17551a414fda15`, library.py `df54dcb336db11c472eb3197b867a82061d29f8ae96aa5e62cc14c38a732d3dd`, test_append_durability.py `791dada1b800fbd6…7113`, test_append_fencing.py `9596e2909bde4eec…f60e`, 문서 `b9d82752aedbd6c5…6b82`. test_storage.py `c1c96ede…`는 1차와 같다 |
| 추출 | `git archive e81be084 \| tar -x -C build/review-trees/g17b`. HEAD 사본 `git archive f4f94b7` → `g17b-head`. 변이 사본 `git archive e81be084 pyproject.toml src tests` → `g17b-mut` |

### R1.2 실행 명령과 결과

| # | 명령(사본 `g17b`) | 결과 |
| --- | --- | --- |
| RJ1 | CI core와 같은 pytest 명령(`--cov … --cov-fail-under=85`, `-W error::ResourceWarning`, `-p no:cacheprovider`), `PYTHONPATH=g17b\src`(보고서에 `D:\project\Recoryn\src` 0건), 고유 `TEMP`·`--basetemp`. **다른 세션의 pytest 두 묶음과 검토자 변이 실행이 함께 돌았다(CPU 40~100%)** | **26549 passed / 1 failed / error 0 / skip 0, 2340.51s, 전체 coverage 92.71%**. 실패는 `test_append_fencing.py::test_external_sqlite_lock_does_not_own_the_capture_root[G17-R-02]`(→ G17R-03). JUnit LF `1de2dce36f018e5f507ebcfc570dc9c808468d2cbb5e13e0e09d134a11cc0964`, 로그 LF `28035530881a90aaf0a05cf59ce42268b8715a2df243f537c491f993e0015b5b`, `coverage.json` LF `6cd911f47dd6382fc773072a4fa18c33a0147994feb2d4e2cb179ebec5f76b2c` |
| RJ1b | 실패 node 2개(R-01·R-02) 단독 재실행 2회 | **2 passed ×2**(31.44s·30.08s). 단독에서는 거부가 없어 실패 분기가 실행되지 않는다(G17R-03) |
| RJ2 | `python scripts/check_coverage.py coverage.json` | **7묶음 PASS**: domain 99.18·97.89, capture 99.85·98.57, jobs 99.20·95.65, storage 96.21·91.55, security 98.11·94.43, content 98.98·99.02, all 94.05·88.77 |
| RJ3 | `ruff check --no-cache …` / `ruff format --no-cache --check …` / `MYPYPATH=src python -m mypy --no-incremental src/recoryn scripts packaging` | All checks passed / 209 files already formatted / **93 source files no issues** |
| RJ4 | 신규 4파일 단독(coverage 없음) 2회, 시작·끝 CPU 부하 기록(`run_rest.sh`) | **1204 passed, 93.21s / 75.79s**. 시작 부하 59%·40%, 다른 pytest 프로세스 4개(다른 세션 2묶음) |
| RJ5 | `run_measure.sh`: HEAD f4f94b7과 FIX1을 번갈아 실행(측정 시작 부하 11%, 다른 pytest 4 프로세스) | R1.3 |
| RJ6 | `mutate_g17b.py ../g17b-mut mutations.jsonl`(A1~A8 재적용 + 새 G1~G4, 사본 파일 hash 복원 확인) | R1.6. 결과 LF `41e27c6678b5ad7dc25f78fafd4a107c7943203446756e692920245fdd49fb84` |

새 probe·스크립트(`g17b-probe/`, LF 앞 16자): `probe_retry_edges.py` `83e0dcdb1705116f`, `probe_persistent_default.py` `8df705d895cc3c2e`, `probe_health_drops.py` `73f37c13422ec3ab`, `run_measure.sh` `6c08cd9c2ecb65ce`, `run_rest.sh` `5065afd69210aa52`, `mutate_g17b.py` `90417050e830ae11`. 측정 결과 LF: `measure.jsonl` `138569341bdea7e5ffb74b01800b292c9a21cbe5a023e343c35bcefdc2fa042a`, `cost.jsonl` `8ce41e66f1c2a8c90907c308a9723a99233bc1933f838e50f08c236f50fd31fe`, `persistent.jsonl` `4afdd1b88da825b7…`, `persistent_default.jsonl` `8f3f1b5f793eade0f872d451c0f8185b37b44ddc570ddd19b7e4cac0bd086774`, `health.jsonl` `4f18aa25656a20824d2a19e08238ad82303f07c41c3356966bad170ae2f99619`.

### R1.3 G17R-01 — **RECHECKED**

- 코드:
  - 첫 검사(WP 앞)는 전체 권위 판정이고, 같은 root 구간에서 `write_generation(root)` = (Library 콜백 WeakMethod, `_history_version`)을 기록한다.
  - WJ 앞·완료 앞(`_check_media_continuation`, chunks.py:432-437)은 이 쌍이 같고 closing이 아니면 통과한다. 다르거나 없으면 전체 판정이다.
- I1 근거:
  - 같은 프로세스의 의도 게시(`_publish_intent`)는 root 안에서 `_history_version`을 올린다.
  - Library를 닫거나 다시 열면 WeakMethod가 달라지거나 사라져 전체 판정으로 간다.
  - 다른 Library 인스턴스는 OS 잠금 때문에 동시에 있을 수 없다.
  - 외부 프로세스·도구의 journal 직접 변경은 계약 §3.1의 단일 writer 범위 밖이다. 같은 블록의 WP~WJ 사이에는 보지 못하지만, 다음 블록의 첫 전체 판정이 본다.
  - DB만 고치는 `_project_intent`는 세대를 올리지 않는다. 그러나 그 경우 journal 의도가 이미 있어 첫 판정이 거부한다.
  - 변이 G1(세대 무시)·G2(상수 세대)는 모두 D family 등에서 검출됐다.
- 측정(HEAD f4f94b7 대 FIX1, 교대, 12초 실시간, 모든 행 보존 성립·gap `QUEUE_DROP`):

  | 조건 | HEAD 거부 | FIX1 거부 | 1차(2fd2bbf8) 참고 |
  | --- | --- | --- | --- |
  | 1트랙 fsync 5ms ×4 | 0·0·0·0 | **0·0·0·0** | 27·40·46·203 |
  | 2트랙 fsync 5ms | 1,192(206+986) | 1,189(203+986) | 1,224 대 1,476 |
  | 1트랙 fsync 20ms | 666 | 666 | 693 대 699 |
  | 2트랙 지연 없음 | 0 | 0 | — |
  | 2트랙 지연 없음 + 완료 삭제 1,000 | 0 | 0 | 196 대 322 |
  | 외부 `BEGIN EXCLUSIVE` 3초, 1트랙 | 25 | **0** | — |
  | 외부 잠금 3초, 2트랙 | 237 | **0** | — |

- append 1회 비용(단일 writer 2,000회):
  - fsync 지연 없음: HEAD 1.31·1.39ms, FIX1 1.67·1.35ms. root 보유/append는 HEAD 1.32·1.41ms, FIX1 0.65·0.47ms.
  - fsync 5ms: HEAD 12.06·12.12ms, FIX1 12.11·11.97ms. root 보유/append는 HEAD 12.06·12.14ms, FIX1 0.52·0.47ms.
  - 1차의 약 1ms 증가가 없어졌다.
- 외부 잠금 때 sealer root 최장은 HEAD 2,456·2,819ms, FIX1 3.8·8.4ms다.

### R1.4 G17R-02 — **RECHECKED**

- 코드: `retry_sealed_read`(_coordination.py:67-84)가 `PermissionError`·winerror 32/33만 1.0초 상한 안에서 10ms 간격으로 재시도한다. 손상(`ValidationError`)·없음(`FileNotFoundError`)·기타 `OSError`는 즉시 전달하고, 상한을 넘으면 원래 예외를 낸다. 쓰는 곳은 seal read-back(`_prepare`, 작업 잠금만 쥠)과 등록 동일성 검사(root 밖)다.
- 원 반례: `probe_g17_identity_transient.py`·`probe_g17_readback_transient.py` 모두 `storage_failed` 거짓, 60블록 수락·거부 0, 복구 뒤 240 = 수락 240프레임이다(1차 54·56블록 거부).
- 경계(`probe_retry_edges.py`):

  | 경우 | 관찰 |
  | --- | --- |
  | 1.5초 지속 거부 | 1.017~1.058초에 fail closed(시도 94~97회) |
  | `FileNotFoundError` 1회 | 0.03초에 실패, 재시도 없음 |
  | descriptor 손상 | 0.031초에 실패, 재시도 없음 |
  | 0.3초 거부 중 같은 세션 삭제 | 첫 답 `DELETE_PENDING`, 의도 뒤 catalog 행 0, 재삭제 `DELETED_LOCAL`, 폴더 없음, 복구 `DELETE_PENDING`, 부활 0 |

- fence·크래시 probe 재실행: SP·SJ × 삭제·abort·복구·확정, kill 4지점 모두 1차와 같다. 의도 뒤 크기 증가 0, abort는 sync 종료까지 대기, 손계산 prefix 12·12·16·16프레임 일치.

### R1.5 지속 거부 상한 재시도와 "수락 뒤 손실"(C00 항목 4) — **기록만**

기준: 같은 지속 거부(동일성 열기가 1.5초 동안 계속 `PermissionError`)에서, HEAD(재시도 없음)와 FIX1(1초 재시도)의 "수락했지만 복구 뒤에도 저장되지 않은 프레임"을 비교했다.

| 설정 | 트랙 | HEAD(회차별) | FIX1(회차별) |
| --- | ---: | --- | --- |
| **기본**(2초 청크, FIFO 4, 큐 256; `probe_persistent_default.py`) | 1 | 0, 0 | 0, 0 |
| 기본 | 2 | 60,960(mic 60,480·system 60,960), 22,080 | 36,960, 32,160·32,640 |
| 비기본 3블록(30ms) 청크(`probe_retry_edges.py`) | 1 | 0, 0, 0 | 20, 24, 16 |

- 해석:
  - 기본 설정에서는 1트랙은 둘 다 0이다. 2트랙은 양쪽 모두 손실이 있고 회차별 대소가 엇갈린다(HEAD 60,960·22,080 대 FIX1 36,960·32,160). 재시도 때문에 손실이 늘었다는 근거가 없다.
  - 기본 청크에서는 FIFO 4개가 8초 분량이라 1초 재시도로 소비자가 막히지 않는다. 그래서 C00 기준(같거나 줄면 기록만)에 따라 발견으로 올리지 않는다.
  - 청크를 30ms로 줄인 비기본 설정에서만 FIFO가 1초 안에 차서 손실이 늘어난다(0 → 16~24프레임). 제품 경로(`RecordingService`·`DesktopRecorder`)는 청크 크기를 바꾸지 않는다.
- 관찰(기존 의미, 17a와 무관): 저장 실패로 녹음이 끝나면 소비자는 캡처 큐에 남은 **이미 수락한** 블록을 쓰지 않고 버린다(`_consume`의 `pending.close()`). 그래서 기본 2트랙에서 HEAD도 수락 뒤 22,080~60,960프레임(0.46~1.27초)을 잃는다. 이 기존 의미(실패 시 수락분 폐기와 그 건강 표시)를 별도 단위에서 판단할지는 C00이 정한다.

### R1.6 mutation(A1~A8 재적용 + G1~G4, `--maxfail=5`)

| ID | 변이 | 결과 | 잡은 node(대표) |
| --- | --- | --- | --- |
| A1 | journal 쓰기 앞 연속 검사 제거 | 검출 5 | G17-F1-COST, F1-CLOSE-payload, G17-D-002 |
| A2 | payload fsync를 root 안으로 | 검출 5 | G17-W-001·005·006 |
| A3 | abort가 작업 잠금을 기다리지 않음 | 검출 5 | G17-W-012·016·025 |
| A4 | `has_active_writer`가 `_seal_in_progress` 무시 | **생존**(1,435 PASS) | — (G17R-04) |
| A5 | 완료 앞 연속 검사 제거 | 검출 5 | F1-COST, F1-CLOSE-journal, G17-HB-019 |
| A6 | 등록 재시도가 capability 재확인 안 함 | 검출 2 | `test_released_capability_is_not_reused_on_registration_retry`(+R-02) |
| A7 | 등록 뒤 busy_timeout 복원 안 함 | **TIMEOUT**(50분, 시험 묶음이 끝나지 않음) | — 검출로 세지만 실패가 아니라 정지로 드러난다 |
| A8 | BUSY·LOCKED 외 OperationalError도 재시도 | 검출 1 | `test_registration_does_not_retry_readonly_failures` |
| G1 | 연속 검사가 세대를 무시(closing만) | 검출 5 | `test_continuation_owner_close_cannot_reuse…`, G17-D-002·003 |
| G2 | Library 세대가 상수 | 검출 5 | G17-D-002·003·005 |
| G3 | 일시 거부 재시도 없음(G17R-02 되돌림) | 검출 5 | G17-F1-READ-per·sha·loc |
| G4 | 모든 OSError를 재시도 | 검출 2 | G17-F1-READ-io(clears·expires) |

**1차 §5·"갱신 표"의 A4 정정**: 1차 tree에서 A4를 잡은 node는 `G17-R-02` 하나였다. 이번 재확인에서 R-02가 부하 아래 변이 없이도 실패함을 확인했다(G17R-03). 그래서 그 "검출"은 변이와 무관한 실패였을 가능성이 높아 생존으로 정정한다.

### G17R-03 (S2, OPEN) — `G17-R-02`가 블록 거부가 겹치면 실패한다(최종 건강 기록 drop 0, HEAD도 같음)

- 근거: test_append_fencing.py:575-582는 메모리 건강 상태가 `DEFERRED`가 아니면 지속 건강의 drop이 거부 수와 정확히 같아야 한다고 판정한다.
- 재현:
  - RJ1(동시 부하): 거부 mic 95·system 77인데 `assert 0 == 172*480`로 실패했다.
  - `probe_health_drops.py`(2트랙, 외부 잠금 3초 + fsync 5ms로 거부 유도):

    | tree | 거부·메모리 drop | 메모리 상태 | 지속 drop | `has_unknown` | stop |
    | --- | --- | --- | --- | --- | --- |
    | HEAD | 575,040 | `OBSERVED` | **0** | True | FINALIZED |
    | FIX1 | 570,240 | `OBSERVED` | **0** | True | FINALIZED |
    | 대조(잠금 없음, fsync 5ms) | HEAD 583,680 / FIX1 601,920 | `OBSERVED` | 거부와 같음 | False | FINALIZED |

  - 단독 실행은 거부가 0이라 이 분기가 돌지 않는다(RJ1b 통과).
- 기대: 시험 oracle과 G-P08 최종 기록 의미가 일치해야 한다. 둘 중 하나를 고쳐야 한다.
  - (가) 외부 잠금으로 health checkpoint가 미뤄졌던 run은 정상 stop 뒤에도 `has_unknown=True`와 마지막 확정 컷을 남긴다는 것이 G-P08 계약이라면, 시험이 `has_unknown`을 기준으로 판정해야 한다.
  - (나) 정상 stop 때 메모리의 정확한 drop을 지속해야 한다면, 최종 기록이 drop 0을 남기는 것은 건강 기록의 과소 보고다(G-P08 귀속).
- 영향: CI 러너는 디스크가 느려 1트랙도 거부가 났다(90c6123 CI 기록). 그래서 이 G-P17a 신규 시험이 CI에서 실패할 가능성이 높다. 제품 쪽은 `has_unknown=True`로 불확실성은 표시하지만, drop 수를 0으로 남긴다. 녹음 데이터 자체는 보존된다. S2로 본다.

### G17R-04 (S3, OPEN) — `_seal_in_progress`의 활성 보호가 시험에 고정돼 있지 않다(변이 A4 생존)

- `has_active_writer`에서 `_seal_in_progress`를 빼도 1,435 node가 통과한다.
- hold된 sealer writer는 `unhold`까지 `_sealing`이 참이라 대부분 겹친다. 남는 창은 hold 없는 `seal()`(공개 경로·salvage)이 실패해 `_cleanup_failure`가 `_sealing`을 내린 뒤 `finally`까지뿐이다. 이 창에서는 새 쓰기가 없어 제품 영향은 거의 없다.
- 계약이 "read-back 중 active 유지"를 명시했으므로 이 조건을 직접 고정하는 행이 필요하다. 작성자가 언급한 A4 TEMP 반례를 정식 시험으로 넣으면 된다. S3.

### R1.7 남는 위험·측정 조건

- 신규 4파일 단독 시간은 다른 세션의 pytest 2묶음이 도는 동안 75.8~93.2초였다(작성자 96.76초, 요청 100초). 부하 없는 단독 값은 이 PC에서 확보하지 못했다. 1차의 80.6~83.5초(1,182건)를 함께 참고한다.
- 전체 회귀는 무거운 동시 부하 아래 실행됐다. 실패 1건은 G17R-03의 부하 의존 분기다.
- A7은 시험 묶음이 끝나지 않는 형태로만 드러난다(CI 시간 초과).
- 1차 §7의 미검증 항목(CI 러너, 실제 HDD·백신·전원 장애, 다중 프로세스)은 그대로다.

## RECHECK 2 (FIX2)

상태: **RECHECKED — 집중 재확인, 2026-11-26.**
- 검토자는 같은 C00 배정 하위 에이전트(Claude)다. 코드는 고치지 않았다. 저장소 쓰기는 이 절 추가뿐이다.
- probe·반복 결과는 `build/review-trees/g17c-probe/`, 변이 사본은 `g17c-mut/`(사용 뒤 원본 hash로 되돌림)에 있다.

**판정 요약.**
- **G17R-03·G17R-04 모두 RECHECKED**다.
- **새 OPEN은 S3 1건(G17R-05)**이다: 미상 분기 판정이 `any`라 트랙 단위 정직성을 다 잡지 못한다. 지금 제품은 더 강한 판정도 만족한다. S0·S1·S2는 없다.
- 전체 회귀는 C00 지시에 따라 생략했다.

### R2.1 입력

| 항목 | 값 |
| --- | --- |
| 대상 | tree `9ab4be12645923d2841b18595e144c1bd7e75e20` = HEAD `f4f94b7` + 9파일. `git diff e81be084 9ab4be12 --stat` = 시험 2·문서 1(141+/5-). 제품 코드 불변: chunks.py `e499f0bd…`, library.py `df54dcb3…`가 FIX1과 같다 |
| 바뀐 파일 LF SHA256 | test_append_durability.py `c10ff966d28b51cf84e819d18352c93418abf3497d4c38a3c06c4588db63c5fb`, test_append_fencing.py `57e116486a8c0d025f8c4acfcc6cc2b7070e92ff52b3e39fd4db8dda255d2b0e`, 문서 `1fc36c674fc286ecf02806d08a8df03d68aad3395147232e6f4bed955ee3a001` |
| probe(LF 앞 16자) | `run_r_loop.sh` `d32b234acfac9811`(fsync 지연 plugin `g15b-probe/g15r_slow_sync.py` + 선택 CPU 부하, JUnit user property에서 측정값 추출), `probe_health_tracks.py` `13f8d18c6c04ad5f`. 결과 `rloop.jsonl` `657f5c76342833a2`, `health_tracks.jsonl` `d0a43bb295cb9b9a`, `gate.log` `9959b084e9c54583` |

### R2.2 G17R-03 — **RECHECKED**(시험 판정), 다만 G17R-05

- 바뀐 판정(test_append_fencing.py:577-589):
  - 영속 `has_unknown`이 False면 지속 drop = 시험이 센 거부 × 480.
  - True면 drop ≤ 그 값, `detail_complete` False, 그리고 `any(트랙이 media_loss_unknown ∧ known_loss_frames None ∧ count_complete False)`.
  - 별도로 메모리가 `DEFERRED`면 영속 `has_unknown`은 True여야 한다.
  - C00 결정의 세 조건과 대응한다. 0을 완전 확정으로 받아들이지 않는다는 G-P08 원칙도 반영했다.
- 부하·거부 조건 반복(`run_r_loop.sh`, 각 `chunks.sync` 앞 5ms로 블록 거부를 강제):

  | 조건 | 회차 | R-01 | R-02(거부 mic·system) | 분기 |
  | --- | ---: | --- | --- | --- |
  | 주변 부하 22~45% | 3 | 통과(거부 0) | 통과(285·250, 255·266, 275·244) | `has_unknown` True(미상) |
  | CPU 부하 프로세스 2개 추가(측정 시 8~83%) | 2 | 통과 | 통과(262·259, 290·231) | 미상 |

  - 10회 모두 통과했다. R-02는 매번 거부가 있었다(FIX1에서 실패하던 조건).
  - **"정확" 분기(`has_unknown` False)는 R-01·R-02에서 한 번도 실행되지 않았다.** 3초 외부 잠금은 1초 간격 health checkpoint를 반드시 미뤄 영속 미상을 만들기 때문이다. 이 분기의 정확 누계 판정은 잠금 없는 다른 보존 시험(G15 `assert_conserved` 등)이 맡는다. 잠금 없는 fsync 5ms 대조에서 지속 drop = 거부, `has_unknown` False임을 RECHECK 1에서 확인했다.
- 연기 뒤 정상 stop에서도 정확 누계가 최종 기록되지 않는 제품 동작은 C00이 G-P08b(S2)로 배정했으므로 여기서 다시 세지 않는다.

### G17R-05 (S3, OPEN) — 미상 분기의 트랙 판정이 `any`라 한 트랙의 "0 확정" 거짓 표시를 놓칠 수 있다

- 근거: 판정이 "어느 한 트랙이라도 미상이면" 통과한다. 그래서 2트랙에서 한 트랙만 미상이고, 실제로 거부가 있던 다른 트랙이 `count_complete` True·`known_loss_frames` 0(완전 0 확정)으로 남아도 통과한다. C00 결정("완전·0 확정 표시가 아니어야")과 G-P08 원칙은 트랙마다 적용돼야 한다.
- 사실 확인:
  - `defer_capture_health`(library.py:1160-1162)와 `_deferred_health_view`(:1191-1193)는 **모든** 트랙을 미상으로 바꾼다.
  - 실측(`probe_health_tracks.py`, 외부 잠금 3초): 2트랙 fsync 5ms, 1트랙 fsync 5ms, 2트랙 지연 없음 모두에서 영속 기록의 모든 트랙이 `media_loss_unknown` True, `known_loss_frames` None, `count_complete` False였다.
  - 그러므로 더 엄격한 판정도 지금 제품에서 통과한다.
  - 검토자가 두 함수를 "첫 트랙만 미상"으로 바꾼 변이로 차이를 보이려 했지만, 최종 영속 기록은 여전히 두 트랙 모두 미상이었다(최종 기록의 미상 표시가 다른 경로에서도 만들어짐). 그래서 `any`의 약점을 실행으로 드러내지는 못했다. 판정은 논리 근거다.
- 기대: 트랙별 판정이 정확하다. 영속 drop < 그 트랙의 정확 누계(`rejected[track] × 480`)인 트랙마다 미상 3조건을 요구한다. 또는 연기 표시의 실제 의미대로 `all`을 요구한다. 시험이 트랙별 `rejected`를 이미 세므로 바로 바꿀 수 있다.
- 영향: 시험 oracle이 계약보다 약할 뿐 제품은 맞다. S3.

### R2.3 G17R-04 — **RECHECKED**

- 새 시험 `test_published_capability_release_still_waits_for_the_seal_exit`(test_append_durability.py:590-645):
  - seal이 게시를 마치고 `finally`(registry)로 나가기 직전에서 멈춘다.
  - 그 사이 capability를 release해 `_sealing` False·`_seal_in_progress` True 상태를 만든다.
  - 이 상태에서 `has_active_writer` 참, 삭제 `DELETE_PENDING`, bundle 유지를 판정한다.
  - root를 쥐지 않았음도 확인한다.
- 변이 A4(`has_active_writer`가 `_seal_in_progress` 무시)를 이 tree에 다시 넣었다:
  - 새 시험 단독 **5/5 실패**.
  - 신규 4파일 전체에서 **1 failed(이 시험), 1204 passed**.
  - 사본 chunks.py는 원본 `e499f0bd…`로 되돌렸다.
- 결정성(정상본): CPU 부하 프로세스 3개를 붙인 상태(시작 부하 38%)에서 단독 **20/20 통과**(0.28~0.52초). barrier가 Event 기반이라 시간 경쟁에 기대지 않는다.

### R2.4 신규 4파일 단독 시간(측정 조건 포함)

| 회차 | 시작 시 CPU 부하·다른 pytest 프로세스 | 결과 |
| ---: | --- | --- |
| 1 | 62%, 4개(다른 세션 2묶음) | 1205 passed, 88.26s |
| 2 | 34%, 4개 | 1205 passed, 77.04s |
| 3 | 30%, 2개 | 1205 passed, 72.50s |

- 범위는 **72.5~88.3초**로, 승인된 100초 안이다.
- 부하 없는 단독 값은 이 PC에서 확보하지 못했다. 작성자 71.45초(첫 실행 102.79초)와 같은 범위다.
