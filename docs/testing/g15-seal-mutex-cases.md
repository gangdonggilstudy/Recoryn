# G15 / G-P15 청크 seal의 root mutex 보유 축소: 계약안과 경우의 수

- 배정: G15 / push G-P15, 계약 단계. 작성자는 w5:p7 Claude다. 독립 검토자는 C00이 정한다.
- 상태: **G-P15 push `90c6123`. G-P15b(§17, 독립 검토 S3 4건과 main CI 판정 정정) READY — 기준 HEAD `90c6123`, 독립 검토 전이다.** G-P15 본체는 PART1(`storage/chunks.py`·`app/recording.py`)과 PART2(`storage/library.py`·`storage/_coordination.py`)다. 신규 시험은 2개다. C00 결정(§15.3 (가), §11.6 수용)을 반영했다.
  - 결정은 §10.3·§12.4, 추가 범위는 §11에 있다.
  - PART1의 구현 반영은 §12, 실행 결과는 §13에 있다.
  - PART2의 구현 반영은 §14, 실행 결과는 §15에 있다.
- 기준: commit `8e09b62`(HEAD). 근거 코드는 모두 `git show HEAD:<path>`로 읽었다. 작업 트리에 섞여 있는 미완성 G-P05·G-P06 변경은 근거로 쓰지 않았다.
- 정본: [통합 계획](../implementation/v1-gap-plan.md) G-P15 행(S2), [G04 경우의 수](g04-unfinished-session-cases.md) §16, `tests/integration/test_unfinished_recovery.py::test_management_never_blocks_another_recording`.
- 아래 행 번호는 모두 HEAD 기준이다.

## 1. 요구와 위험

- 관측(C00 보고, G04 §16에 인용):
  - G-P04 정확한 tree 검증 중, 동시 부하에서 녹음 블록 거부 133~432개가 관측됐다.
  - 50ms 이상 root mutex를 보유한 기록은 모두 `recoryn-writer-rec` thread의 `_consume → seal → __exit__`였고, 0.9~1.9초였다.
  - 단독 실행에서는 유실 0이었다.
- G04 FIX5의 직접 재측정(§16.1)에서도 같은 양상이 나왔다.
  - 전체 root 최장은 부하 없는 반복에서도 1.0~1.2초였다.
  - 거부는 다른 세션의 무거운 관리 작업(확정 900묶음)이나 별도 pytest 부하와 겹칠 때만 났다(9~263블록).
- 위험 **S2**: 원본 손실이 아니라 수락 단계의 결정적 유실이다. 거부 블록은 건강 정보의 `QUEUE_DROP` gap으로 기록된다. 다만 사용자가 느끼는 녹음 품질 저하이고, 부하에 따라 재현된다.
  - 같은 root mutex를 GUI의 250ms 갱신도 쓴다(`ui/main.py` `_tick`의 `library.chunks`, `:831` 부근). 그래서 seal이 mutex를 잡는 동안 화면 갱신도 멈출 수 있다. 이번 계약에서 직접 측정하지는 않았다.

## 2. 직접 확인한 근거

### 2.1 코드 경로

| 위치 | 사실 |
| --- | --- |
| `capture/queue.py:43-58` | `offer`는 비차단이다. 블록 수나 바이트가 상한이면 새 블록을 버리고 False를 돌려준다 |
| `app/recording.py:177-222` `_consume` | **하나의 소비자 thread**가 모든 트랙의 append, 그리고 청크가 차면 `seal()`과 `register_chunk()`를 동기로 처리한다(`:194`, `:201`, `:204-205`). 그동안 큐를 비우지 않는다 |
| `storage/chunks.py:342-393` append | root mutex 안에서 `check_write_allowed`(매번 SQLite 읽기 연결), payload write+fsync, journal write+fsync를 한다 |
| `storage/chunks.py:395-437` seal | root mutex 안에서 순서대로: `check_write_allowed` → pcm·journal fsync → descriptor write+fsync → `abort()`(파일 닫기, `_pcm=None`) → **`scan_prefix(strict)` 전체 재검증** → mkdir → rename → **`verify_bundle` = 두 번째 전체 재검증** |
| `storage/chunks.py:43-47` | `has_active_writer`는 `_pcm is not None`일 때만 참이다. seal의 `abort()` 뒤에는 이미 거짓이다 |
| `storage/library.py:427-466` `register_chunk` | `verify_bundle`(세 번째 전체 재검증)은 mutex 밖이지만 소비자 thread에서 돈다. mutex 안의 겹침 검사는 `self.chunks()`로 그 세션의 **모든 이전 descriptor를 디코딩**한다(`:450-457`) |
| `storage/library.py:1043-1113` `delete_session` | 삭제 의도 기록과 판단(claim, `has_active_writer`, 활성 작업)은 root mutex 안이다. **트리 삭제는 mutex 밖**(`_session_operation`)이다 |
| `storage/_coordination.py:18-54` | 프로세스 안 root별 RLock 하나를 모든 세션·writer·Library가 공유한다. `check_write_allowed`는 journal 의도와 `deleted_sessions` 세대를 검사한다 |
| `app/recording.py:61-68` `is_live` | 입력 수락 중이거나 소비자 thread가 살아 있으면 참이다 |

### 2.2 직접 측정(계약 단계 probe, 저장소 미수정)

- HEAD의 `src`와 `pyproject.toml`을 `git archive`로 `%TEMP%\recoryn-g15-head-fb891b23e1cf488b8f4caf66f6903409`에 풀고, `PYTHONPATH`로 그 사본을 import해 실행했다.
- import 경로가 사본의 `chunks.py`인지 확인했다. 부하를 걸지 않은 개발 PC의 수치이며 상한이 아니다.

**probe 1: 기본 청크 하나(200블록 × 480프레임 = 96,000프레임), 5회**
- 파일: `C:\Users\gangd\AppData\Local\Temp\claude\e47d15555ed7cfa9\d9354f5a-75d0-44dc-8069-db32589569d1\scratchpad\g15probe\probe_seal_phases.py`, LF sha256 `d14cc8c5…2f27`
- 결과 sha256: `aa8884b3…10a1`

| 구간 | 5회 범위 | 중앙값 | 비고 |
| --- | --- | ---: | --- |
| append 200블록 | 0.378~0.445초 | 블록당 1.9ms | 그중 fsync 0.147~0.176초(블록당 2회) |
| seal 전체 | 0.434~0.655초 | 0.467초 | `scan_prefix` 합계 0.42~0.64초(직접 1회 + `verify_bundle` 안 1회), fsync 0.7~1.9ms |
| `register_chunk` | 0.205~0.325초 | 0.289초 | 거의 전부 `verify_bundle` |

해석:
- 소비자 thread는 2초 분량 오디오마다 약 1.1초를 쓴다(append 0.38 + seal 0.47 + register 0.29).
- seal의 root mutex 보유는 **fsync가 아니라 중복 재검증(CPU)**이 대부분이다.
- 부하로 CPU·디스크가 느려지면 소비자가 실시간을 따라가지 못하고, 큐(256블록 = 2.56초)가 넘친다.

**probe 2: 기존 청크 n개가 있을 때 다음 `register_chunk`의 root mutex 최장 보유**
- 파일: `…\g15probe\probe_register_scaling.py`, LF sha256 `6cf341f2…cf40b`
- 결과 sha256: `52df88c8…61a1`

| 기존 청크 n | 등록 전체 | root 최장 보유 |
| ---: | ---: | ---: |
| 0 | 4.3ms | 1.6ms |
| 900(30분) | 45.1ms | 42.4ms |
| 3,600(2시간) | 170.5ms | 167.9ms |

- 겹침 검사가 n에 선형이다. 2시간 녹음에서는 청크마다 mutex를 약 0.17초 잡는다.

### 2.3 C00 초안 방향의 검증

- **맞는 점:** 무거운 일을 root mutex 밖으로 빼야 한다. 그래야 관리 작업, 다른 세션, GUI 갱신이 writer를 기다리지 않는다(경합 문제).
- **바로잡을 점 1:** 긴 보유의 주성분은 fsync가 아니라 **같은 청크를 두세 번 다시 해시·파싱하는 검증**이다(probe 1).
- **바로잡을 점 2:** 블록 거부의 직접 원인은 **소비자 thread 자신이 seal·등록을 동기로 처리하며 큐를 비우지 못하는 시간**이다. mutex를 잡든 안 잡든 같은 thread가 같은 시간을 쓰면 거부는 그대로다. 그래서 mutex 축소만으로는 거부가 사라지지 않는다. 아래 계약은 다음 세 가지를 함께 다룬다.
  1. 검증 1회
  2. 소비자 밖 게시 pipeline
  3. mutex 축소

## 3. 권고 계약

### 3.1 불변식(바뀌지 않음)

- **I1 삭제 의도 뒤 새 게시 0:** 삭제 의도가 commit된 뒤에는 그 세션의 `tracks/`에 새 bundle이 생기지 않고, catalog에 새 행도 생기지 않는다.
- **I2 봉인 청크 유실 0:** seal이 성공을 돌려준 청크는 catalog에 등록되거나, 크래시라면 복구에서 채택된다. 예외는 사용자가 요청한 삭제가 끝난 경우뿐이다.
- **I3 원본 부활 0:** 삭제가 완료된 세션 디렉터리를 writer·복구·확정이 다시 만들지 않는다.
- **I4 크래시 복구 가능성:** 아래 §5의 모든 지점에서 프로세스가 죽어도, 복구가 손계산한 prefix를 정확히 채택한다. 중복 frame도 없다.
- **I5 내구성 의미 불변:** append마다 payload와 journal을 fsync하는 현재 순서와 횟수를 유지한다. 전원 장애·디스크 캐시 내구성은 주장하지 않는다(기존과 같음).
- **I6 G-P04 claim 의미 불변:** live 세션의 복구·확정은 `SESSION_LIVE`로 거부한다. 관리 작업은 녹음 writer를 기다리게 하지 않는다.

### 3.2 seal을 준비와 게시로 나눔(`storage/chunks.py`)

- **writer 상태:** OPEN → SEALING → PUBLISHED, 실패하면 ABORTED.
  - `has_active_writer`는 **OPEN 또는 SEALING**이면 참이다.
  - 지금처럼 파일을 닫는 순간(`_pcm=None`) 비활성으로 보이지 않게 한다. seal이 mutex 밖에서 검증하는 동안 `delete_session`이 "활성 writer 없음"으로 판단해 staging을 지우는 것을 막기 위해서다.
- **준비 단계(mutex 밖, writer 전용 staging만 다룸):**
  - pcm·journal 마지막 fsync, descriptor 작성+fsync, 파일 닫기
  - **`scan_prefix(strict)` 1회**로 staging을 검증하고, writer가 누적한 descriptor와 같은지 비교한다
  - 최종 경로에서 할 위치 검사(`relative_path`의 마지막 6요소)도 미리 계산한다
- **게시 단계(root mutex 안, 짧게):**
  - `check_write_allowed`(I1) → 대상 상위 디렉터리 mkdir → 대상 부재 확인 → rename
  - 게시 뒤 `verify_bundle`은 하지 않는다. rename은 바이트를 바꾸지 않고, 준비 단계에서 같은 검사를 이미 했다.
  - 결과로 **`SealedChunk`**(descriptor + 이 프로세스의 writer가 검증했다는 내부 capability)를 돌려준다.
- **실패 처리:**
  - 준비 단계 검증이 실패하면 게시하지 않는다. ABORTED, staging 보존, 예외를 올린다.
  - 게시 단계에서 의도가 있으면 rename하지 않는다. ABORTED, staging 보존, `StateConflict`를 올린다.
- **SEALING에서 PUBLISHED로 바뀌는 시점:** 게시를 넘어 **catalog 등록 완료 시점까지** writer를 활성으로 본다(§3.3). 그동안의 삭제는 `DELETE_PENDING(ACTIVE_READER_OR_WRITER)`로 미뤄진다.
- **append(선택 항목 §10-4):** check+write는 mutex 안에 그대로 둔다(I1). fsync만 mutex 밖으로 뺀다. 순서는 payload write(안) → fsync(밖) → journal write(안) → fsync(밖)다.

### 3.3 등록(`storage/library.py`, **G-P05 push 뒤**)

- **녹음 경로:** `register_chunk`가 `SealedChunk`를 받으면 전체 재검증을 생략한다. 대신 mutex 밖에서 값싼 동일성 검사를 한다(descriptor.json 바이트, 파일 크기).
  - 공개 `register_chunk(descriptor)`의 의미는 그대로다. 외부 descriptor와 복구 채택은 지금처럼 `verify_bundle`을 거친다.
- **mutex 안:** claim·`_live`(I1) 검사, 같은 ID 충돌 검사, **겹침 검사를 같은 (트랙, epoch)의 인접 범위만 보도록 축소**(§10-3), insert·commit.
  - 겹침 검사 축소의 후보: SQLite JSON1 질의 또는 (session, track, epoch)별 마지막 sequence 조회. probe 2의 선형 증가를 상수 또는 로그 시간으로 줄인다.
- 등록이 끝나면 writer를 PUBLISHED로 바꾼다(삭제가 이제 진행 가능해진다).

### 3.4 소비자 밖 게시 pipeline(`app/recording.py`)

- 청크가 기준에 도달하면 소비자는 그 writer를 **분리**해, 서비스당 하나인 **sealer thread**의 제한 FIFO에 넘긴다. 용량은 §10-5로 정하며, 기본 제안은 청크 4개(8초)다.
- 소비자는 즉시 다음 블록을 위한 새 writer를 연다. 분리된 writer는 소비자가 더 만지지 않는다.
- sealer는 FIFO 순서로 준비 → 게시 → 등록을 한다. 그래서 같은 (트랙, epoch)의 등록 순서가 seal 순서와 같다.
- **backpressure:** FIFO가 가득 차면 소비자는 공간이 날 때까지 기다린다. 그동안 큐 초과는 지금처럼 `QUEUE_DROP`으로 기록된다. 메모리는 제한된 채로 남는다.
- **`is_live()`:** 수락 중 OR 소비자 thread 생존 OR **sealer thread 생존 또는 FIFO 비어 있지 않음**. 등록되지 않은 청크가 있는 동안 복구·확정은 `SESSION_LIVE`로 거부된다(I6).
- **`_drain`:** 큐를 닫고, 소비자가 남은 writer를 FIFO에 넣은 뒤, sealer가 FIFO를 모두 처리할 때까지 기다린다. 시간 초과 의미는 기존 `WRITER_ACK_PENDING`을 sealer까지 넓힌다. 건강 기록과 FINALIZING은 그 뒤에만 한다.
- **오류:** sealer 오류는 `_writer_error`로 소비자에게 전달한다. 수락을 멈추고, FIFO에 남은 writer와 열린 writer는 abort한다(staging 보존). 상태는 INTERRUPTED다. 지금의 실패 의미와 같다.

### 3.5 바꾸지 않는 것

- 삭제 journal·tombstone·`deleted_sessions` 형식, G-P05의 삭제 대기 목록과 재시도, G-P04의 claim·inventory·확정 API, UI·CLI는 바꾸지 않는다.
- 공개 `ChunkWriter.seal()`의 반환 타입은 `ChunkDescriptor` 호환을 유지한다. 기존 직접 호출자(시험과 `test_process_crash.py`의 자식 script)가 그대로 동작해야 한다.

## 4. 경우의 수

### 4.1 차원과 동치류

| 차원 | 동치류 | 크기 |
| --- | --- | ---: |
| P: seal 위치 | V(mutex 밖 검증 중) / P(게시: 의도 검사+rename) / G(등록 commit) | 3 |
| X: 경쟁자 | 같은 세션 삭제 / 같은 세션 확정 / 같은 세션 복구 / 다른 세션 관리(목록·확정·복구) / 같은 세션 다른 트랙 append / seal 검증 실패(abort) | 6 |
| C: 크래시 지점 | §5의 C1~C7 | 7 |
| L: 주입 지연 | seal 준비 단계 {0, 0.2, 1.0, 3.0초} × append fsync {0, 5ms} | 8 |
| N: 기존 청크 수 | {0, 900, 3,600} | 3 |
| W: writer 상태 × 동작 | {OPEN, SEALING, PUBLISHED, ABORTED} × {append, seal, abort, has_active} | 16 |

### 4.2 분모

| 집합 | 정의 | 분모 |
| --- | --- | ---: |
| HB1 seal ∥ 삭제 | 사슬 V<P<G와 단일 사건 D의 linear extension 4개(D<V, V<D<P, P<D<G, G<D) | 4 |
| HB2 seal ∥ 같은 세션 확정 | 같은 4위치 | 4 |
| HB3 seal ∥ 같은 세션 복구 | 같은 4위치 | 4 |
| HB4 seal ∥ 다른 세션 관리 | 관리 3종 × seal 위치 3(V, P, G) | 9 |
| HB5 같은 세션 다른 트랙 append | 트랙 A seal 중 트랙 B append의 위치 3(P 전, P와 G 사이, G 뒤) | 3 |
| HB6 검증 실패 abort ∥ 삭제 | abort 사슬(V 실패 → ABORTED)과 D의 위치 4 | 4 |
| CRASH | C1~C7, 자식 프로세스 kill | 7 |
| LAT | L 8행 | 8 |
| REG | N 3행 | 3 |
| UNIT | W 16 + 검증 1회 계수 1 + 손상 staging 3(비트 뒤집기, 잘린 journal, 기록 없는 PCM 꼬리) + fsync 횟수 불변 1 | 21 |
| **합계** | | **67** |

- 무제약 P×X×C×L×N = 3×6×7×8×3 = 3,024다. 이를 합하지 않고 위처럼 나눈 근거는 다음과 같다.
  - 크래시(C)는 경쟁(X)이 없는 한 프로세스의 지점이다.
  - 지연(L)과 청크 수(N)는 측정 축이며, 결과 판정(I1~I6)이 지연에 따라 달라지지 않는다는 것이 이 계약의 주장이다.
  - 그래서 생략한 교차 조합은 **독립성 가정에 기댄 미검증 조합**으로 남긴다. 독립 검토 대상이다.
- HB의 순서는 sealer thread에 넣은 hook(Event로 V·P·G 직전과 직후에 멈춤)으로 강제한다. 긴 sleep에 기대지 않는다.

### 4.3 독립 oracle(손으로 쓴 기대)

| 집합 | 기대 |
| --- | --- |
| HB1 | D<V·V<D<P: P가 의도를 보고 거부한다. `tracks/`에 새 bundle 0, catalog 새 행 0. 삭제는 그동안 `DELETE_PENDING(ACTIVE_READER_OR_WRITER)`이고, writer 정지 뒤 재시도하면 `DELETED_LOCAL`이다. P<D<G: bundle은 의도 전에 게시됐다. D는 활성 writer 때문에 미뤄지고, G가 `_live`로 거부돼 catalog 새 행 0이다. 재시도 뒤 디렉터리가 없다. G<D: 정상 등록 뒤 삭제한다. **네 순서 모두 최종 디렉터리 부재, tombstone 유지, 이후 복구가 세션을 다시 만들지 않는다(I3)** |
| HB2·HB3 | 네 위치 모두 `SESSION_LIVE`. 상태·파일 불변. 녹음은 계속되고 정지가 성공한다 |
| HB4 | 관리 작업 결과가 손계산과 같다(G04 PERF와 같은 기대). 관리 thread의 root 최장 보유 <50ms, writer의 root 최장 보유 <50ms |
| HB5 | 두 트랙 모두 손계산 frame 전체가 등록되고, 겹침 오류는 0 |
| HB6 | 검증 실패 청크는 게시 0, 등록 0, staging 보존. writer 오류로 INTERRUPTED. 복구는 검증된 prefix만 채택한다. 삭제는 재시도 뒤 완료된다 |
| CRASH | 손계산 prefix frame 수 = 복구 뒤 등록 frame 합. 원본 바이트 불변(hashlib 직접 계산), 재복구 멱등, 중복 0 |
| LAT | (a) writer thread의 root 최장 보유 <50ms(8행 모두). (b) 구조 검사: `seal`·`register_chunk`가 **소비자 thread에서 한 번도 호출되지 않음**(8행 모두). (c) 거부 블록 수는 기록한다. seal 지연 ≤1.0초이고 append fsync 지연 0인 3행에서는 0을 assert한다. 3.0초 행은 FIFO 상한 이하 유지만 assert한다. append fsync 5ms 행은 측정만 한다(§9) |
| REG | n=900·3,600에서도 등록의 root 최장 보유 <50ms(§10-3 승인 시). 미승인이면 측정만 하고 §9 한계에 둔다 |
| UNIT | W 표는 손으로 쓴다: OPEN은 append·seal·abort 허용, SEALING은 append 거부·abort 허용·active 참, PUBLISHED·ABORTED는 모두 거부·active 거짓. seal 1회당 `scan_prefix` 호출 1, 게시 뒤 `verify_bundle` 0. 손상 staging 3종은 게시 0. append당 fsync 2, seal당 descriptor fsync 1(I5) |

- 기대값은 구현의 상태 함수나 검증 함수를 import해 만들지 않는다. frame 수와 바이트는 시험의 합성 블록에서 손으로 계산한다.

## 5. 크래시 checkpoint

자식 프로세스는 READY 표식을 원자 게시(임시 파일 + `os.replace`)하고 멈춘다. 부모는 그 뒤 kill한다(G04 K 사슬과 같은 방식).

| ID | 지점 | 손계산 결과 |
| --- | --- | --- |
| C1 | append payload fsync 뒤, journal write 전 | journal 기록 수만큼만 채택한다(기존 K1과 같음) |
| C2 | 청크가 FIFO에 분리됐고 아직 준비 전 | staging 전체를 복구로 채택한다(`recovered-…`) |
| C3 | descriptor 작성+fsync 뒤, 검증 전 | C2와 같다(descriptor가 있는 staging도 살린다) |
| C4 | 검증 뒤, 게시 mutex 진입 전 | C2와 같다 |
| C5 | rename 뒤, 등록 전 | 고아 bundle로 채택한다(기존 K3) |
| C6 | 등록 commit 뒤 | catalog 그대로다(기존 K4) |
| C7 | 청크 n은 SEALING, 청크 n+1은 OPEN | 두 staging 모두 채택한다. sequence 범위가 서로 겹치지 않는다 |

## 6. 기존 시험과의 관계

| 기존 node | 관계 |
| --- | --- |
| `tests/integration/test_process_crash.py::test_actual_process_kill_preserves_exact_prefix[4 phase]` | 직접 `ChunkWriter`를 쓰는 기존 4지점. 공개 seal 호환이 유지되면 그대로 통과해야 한다. C1·C5·C6과 같은 의미 |
| `tests/integration/test_unfinished_recovery.py::test_management_never_blocks_another_recording[3]` | 관리 보유 <50ms를 이미 assert한다. 이번 단위 뒤에는 writer 최장 보유도 함께 출력되며, LAT에서 writer 보유를 따로 assert한다. 이 node의 거부 블록 수는 계속 측정값이다 |
| `…::test_f3_claim_competitors` 등 G-P04 claim 시험 | I6 회귀 |
| `tests/unit/test_storage.py`의 seal·삭제 계열(`test_p11_late_writer_is_fenced_after_delete`, `test_delete_and_recover_do_not_race_live_writer`, `test_storage_faults_preserve_verified_prefix`, `test_short_write_and_failed_atomic_replace_preserve_old_result`) | I1·I2·I4 회귀. 특히 삭제 뒤 늦은 writer 차단 의미를 유지한다 |
| `tests/integration/test_storage_integrity.py`, `tests/property/test_pcm_storage_oracle.py` | 원본 바이트·prefix oracle 회귀 |
| `tests/integration/test_app_service.py`, `tests/e2e/test_recording_control.py` | 저장 실패 뒤 INTERRUPTED와 복구, rotation 실패. pipeline 오류 전달이 같은 의미인지 확인한다 |

- 기존 시험 파일은 수정하지 않는 것을 원칙으로 한다. 기존 시험이 내부 구현(seal 안의 `verify_bundle` 호출 등)을 직접 가정해 실패하면, 그 실패를 근거로 C00에 재배정을 요청한다.

## 7. mutation 계획

구현 뒤 OS TEMP 사본(`pyproject.toml`, `src`, `tests` 함께)에서 하나씩 적용한다. sentinel로 사본 import를 확인하고, 하위 프로세스의 `PYTHONPATH`도 사본 `src`로 둔다.

| ID | 변이 | 잡아야 할 assertion |
| --- | --- | --- |
| MU1 | 게시 단계의 `check_write_allowed` 제거(검사 없이 rename) | HB1 D<V·V<D<P의 새 bundle 0 |
| MU2 | 파일을 닫는 순간 비활성으로 표시(지금처럼) | HB1 V<D<P에서 삭제가 `DELETE_PENDING`이 아니라 즉시 제거를 시도 |
| MU3 | 준비 단계 검증 생략 | UNIT 손상 staging 3행의 게시 0 |
| MU4 | 등록의 mutex 안 `_live` 재검사 생략 | HB1 P<D<G의 catalog 새 행 0 |
| MU5 | `_drain`이 sealer FIFO를 기다리지 않음 | 정지 뒤 확정 목록 frame 수(LAT 0행, HB5) |
| MU6 | `is_live`가 sealer FIFO를 보지 않음 | HB2·HB3의 `SESSION_LIVE` |
| MU7 | 준비 단계 검증을 다시 mutex 안으로 | LAT 0.2·1.0·3.0초 행의 writer 보유 <50ms |
| MU8 | 겹침 검사를 마지막 청크 하나와만 비교(축소 구현 결함) | UNIT에 추가할 의도적 겹침 행(같은 트랙·epoch의 이전 청크와 겹침) |

## 8. 측정 방법

- **root 보유 계측:** G04 PERF 시험의 `RootHoldMeter`와 같은 방식이다. 최외곽 보유만 thread별로 기록하고 대기 시간은 제외한다. 새 시험 파일에 작게 다시 쓰며 G04 시험을 import하지 않는다.
- **결정적 부하(LAT):**
  - `chunks.sync`와 준비 단계 검증 함수에 지연을 주입해 CPU·디스크가 느린 상황을 흉내 낸다.
  - 생산자는 100블록/초로 정해진 수(예: 600블록)를 제출한다.
  - 기록 항목: writer와 관리 thread별 최장 보유, 50ms 이상 보유 목록, 소비자 thread에서의 seal·등록 호출 수, 거부 블록, FIFO 최대 길이, 등록 frame 합.
- **실부하(보고만):** G04 PERF 3행을 별도 pytest 부하와 동시에 실행해, 구현 전후의 writer 최장 보유와 거부 블록을 비교 기록한다. 환경 의존이므로 assert하지 않는다.
- **청크 수 확장(REG):** probe 2와 같은 일괄 catalog fixture로 n=0·900·3,600에서 다음 등록의 mutex 보유를 잰다.
- 모든 실행은 `-p no:cacheprovider`, OS TEMP의 고유 basetemp, offscreen, `-W error::ResourceWarning`을 쓴다.

## 9. 미검증 한계

- 전원 장애, OS 크래시, 디스크 쓰기 캐시의 내구성은 주장하지 않는다. fsync 순서·횟수를 유지할 뿐이다(I5).
- **append당 fsync 2회가 정하는 처리량 한계:** fsync 지연이 블록 간격의 절반(10ms 블록이면 5ms)을 넘으면, pipeline이 있어도 소비자가 실시간을 따라가지 못한다. 이를 고치려면 fsync 묶음(group commit) 같은 **내구성 단위 변경**이 필요하다. 이 단위에서 하지 않고 §10-6의 결정 대상으로 둔다.
- 실장비 캡처의 실제 블록 간격과 장치 버퍼, CI 부하별 거부 수, 3,600청크를 넘는 세션은 검증하지 않는다.
- 다중 프로세스는 Library OS 잠금이 막으므로 범위 밖이다.
- GUI 갱신 정지(§1)는 원인으로 추정할 뿐이다. 이번 계약에서 직접 측정하지 않았다.

## 10. C00 결정 요청

1. **범위:** 권장은 §3 전체다(검증 1회 + 준비·게시 분리와 mutex 축소 + 소비자 밖 sealer pipeline). C00 초안처럼 mutex 축소만 하면 경합(관리, 다른 세션, GUI)은 줄지만, 소비자 thread의 동기 처리 시간이 남아 부하 시 블록 거부가 계속된다(§2.3).
2. **`SealedChunk` 경로로 등록 재검증 생략:** 공개 `register_chunk` 의미는 유지하고, 녹음 경로만 프로세스 안 capability로 재검증을 건너뛴다. `storage/library.py`를 바꾸므로 **G-P05 push 뒤**에 한다.
3. **겹침 검사 축소:** probe 2의 선형 증가(2시간에 0.17초)를 이 단위에서 고칠지, 별도 단위로 둘지. 권장은 이 단위다. 녹음 중 등록마다 mutex를 잡는 같은 원인이기 때문이다.
4. **append의 fsync를 mutex 밖으로:** check+write는 안에 두어 I1을 지킨다. 포함할지, LAT 측정 뒤로 미룰지.
5. **sealer FIFO 용량과 backpressure:** 기본 제안은 청크 4개다. 가득 차면 소비자가 기다리고, 큐 초과는 `QUEUE_DROP`으로 기록한다.
6. **fsync 묶음(내구성 단위 변경):** 이 단위에서 제외하고, LAT의 append fsync 행 결과를 보고 별도 결정한다.

### 10.1 구현 쓰기 범위(승인 요청)

| 파일 | 변경 | 순서 |
| --- | --- | --- |
| `src/recoryn/storage/chunks.py` | writer 상태, 준비·게시 분리, `SealedChunk`, (선택) append fsync 위치 | 즉시 가능 |
| `src/recoryn/app/recording.py` | sealer pipeline, `is_live`, `_drain`, 오류 전달 | 즉시 가능(G-P05·G-P06 범위 밖임을 착수 때 다시 확인) |
| `src/recoryn/storage/library.py` | `SealedChunk` 등록 경로, 겹침 검사 축소 | **G-P05 push 뒤** |
| `src/recoryn/storage/_coordination.py` | append 판정이 열린 Library의 색인을 쓰는 등록부(§12.4 (1), C00 추가 승인) | G-P05 push 뒤 |
| `tests/unit/test_seal_phases.py`(신규) | UNIT 21 | — |
| `tests/integration/test_seal_mutex.py`(신규) | HB 28, CRASH 7, LAT 8, REG 3 | — |
| `docs/testing/g15-seal-mutex-cases.md` | 이 문서(결과 갱신) | — |

- 쓰지 않는 파일: `ui/main.py`, `cli.py`, `app/ai.py`, security·providers·adapters·`ui/privacy.py`·`ui/ai_bridge.py`(G-P06), 기존 시험 파일. `storage/_coordination.py`는 처음에 이 목록에 있었으나 C00이 PART2 범위로 추가 승인했다.
- 기존 시험이 내부 구현 가정 때문에 실패하면, 실제 실패를 근거로 먼저 재배정을 요청한다.

### 10.2 대안과 기각 사유

| 대안 | 기각 사유 |
| --- | --- |
| mutex 축소만(C00 초안) | 경합은 줄지만 소비자 동기 처리(약 1.1초/2초)가 남아 거부의 직접 원인을 못 없앤다 |
| 검증 완전 생략(writer가 계산한 해시를 신뢰) | 설계의 "writer drain과 청크 검증" 단계를 없앤다. 디스크에서 다시 읽어 확인하는 유일한 검사다 |
| 캡처 큐만 키우기(예: 10초) | 정지를 가릴 뿐 경합을 못 고친다. 메모리 상한(16MB) 설계와 충돌한다. 보조 수단으로는 별도 결정 가능하다 |
| fsync 묶음 | 내구성 단위를 바꾼다. 측정상 seal의 fsync는 1~2ms이고 append fsync는 블록당 약 0.75ms라 주원인이 아니다. §10-6 |
| 세션별 mutex로 root mutex 대체 | 삭제 journal·tombstone이 root 단위라 조정 구조 전체를 다시 설계해야 한다. 이 단위 범위를 넘는다 |

### 10.3 C00 결정(승인)

1. 범위: §3 전체 승인.
2. `SealedChunk`로 등록 재검증 생략: 승인. 조건은 다음과 같다.
   - capability는 `chunks.py`의 sealer만 만들 수 있는 프로세스 안 객체여야 한다. descriptor나 공개 데이터만으로 위조할 수 없어야 한다.
   - mutex 밖의 값싼 동일성 검사(descriptor.json 바이트·크기)는 유지한다.
   - 공개 `register_chunk`와 복구 채택은 지금처럼 `verify_bundle`을 거친다.
3. 겹침 검사 축소: 이 단위에 포함.
4. append fsync를 mutex 밖으로: 기본은 지금처럼 안에 둔다. LAT 측정으로 효과와 I1 증명을 보고한 뒤 C00이 따로 결정한다.
5. sealer FIFO 용량 4, 가득 차면 소비자 대기와 `QUEUE_DROP` 기록: 승인.
6. fsync 묶음: 이 단위에서 제외.
7. 추가 범위: `_deletion_intents()`의 root mutex 아래 journal 전체 읽기를 포함한다(§11).

순서: `storage/library.py` 변경(§3.3, §11)은 G-P05 push 뒤 C00 신호를 받고 시작한다. 시험과 mutation은 `git archive HEAD` 격리 사본에 G-P15 파일만 덮어써서 실행한다.

## 11. 추가 범위(삭제 의도 색인, C00 결정 7)

### 11.1 문제와 근거

- `storage/library.py:206-227`(HEAD) `_deletion_intents()`는 root mutex 아래에서 두 가지를 매번 한다.
  - `deleted_sessions` 전체 행을 읽는다.
  - `deletion-journal/`의 **모든 JSON을 읽어 schema·identifier·세대를 검증**한다.
- 이를 부르는 곳: `_live`(`register_chunk`, `get_session`, `create_session`, `register_live_owner` 등), `list_sessions`, 복구·삭제·inventory·claim admission.
- tombstone journal은 영구 보존되므로 비용이 삭제 기록 수 N에 비례해 계속 커진다.
  - C00 전달: G-P05 구현자가 삭제 기록 400건에서 `create_session` 등의 보유를 최대 2.6초로 관측했고, writer의 `register_chunk`도 길어졌다.
  - **G-P05 독립 검토자의 측정**(`docs/reviews/g05-pending-deletion-review.md`의 G05R-02, LF sha256 `b49ac4582f3b84b1…`, C00 전달로 인용, 이 문서의 직접 측정 아님):
    - HEAD 2933573과 G-P05를 번갈아 측정했고 두 값이 같았다. 따라서 기존 결함(S1)이다.
    - 같은 journal 전체 읽기가 writer `register_chunk`에서 청크당 3회, GUI `_tick`의 `chunks()`에서 250ms마다 반복된다.
    - 1트랙 실시간 12초(576,000프레임) 기준 거부 블록/유실 프레임:

      | 조건 | 거부 블록 | 유실 프레임 |
      | --- | ---: | ---: |
      | 완료 삭제 0·100·200건 | 0 | 0 |
      | writer만, 1000건 | 344 | 165,120 |
      | UI tick 포함, 400건 | 543 | 260,640 |
      | UI tick 포함, 1000건 | 923 | 443,040 |

    - 이 PC의 임계는 200~400건 사이다.
    - 관찰 O1: 2트랙 녹음은 tombstone 0건에서도 HEAD에서 378,240프레임이 유실됐다. writer 처리량(§3 pipeline 범위)일 가능성이 있어 PART1 LAT에 2트랙 행을 더했다(§12.2).
- 녹음 중 청크 등록마다 같은 root mutex를 잡는 같은 원인이라 G-P15에 포함한다.

### 11.2 설계(권고)

- **색인:** Library가 메모리 색인 `_intent_index`(journal의 유효한 의도 세션 집합)와 journal 디렉터리 stamp(`st_mtime_ns`, 항목 수)를 가진다.
  - 열 때 한 번 journal 전체를 지금과 같은 규칙으로 검증해 만든다. 생성자 안이라 다른 thread가 기다리지 않는다.
  - 검증이 실패하면(`.tmp`, 미인식 항목, 손상 JSON, journal 부재) 색인을 "무효"로 둔다. 그러면 모든 의도 질의가 지금처럼 매번 `ValidationError`로 실패하고(fail closed), 그때만 매번 재검증한다. 열기 자체는 지금처럼 성공한다(UI 시작 의미 불변).
- **mutex 안 질의(O(1)에 가깝게):**
  - journal 디렉터리 `os.stat` 한 번으로 stamp를 비교한다.
  - stamp가 같으면 `sid in _intent_index` 또는 `deleted_sessions` PK 조회(`WHERE session_id=?`)로 판정한다. DB 행과의 합집합 의미는 그대로다(journal이 사라진 DB-only 기록도 의도로 본다).
  - stamp가 다르면(이 프로세스의 삭제 경로가 아닌 외부 변경) 전체를 재검증해 색인을 다시 만든다. 드문 경로이며 그 보유 시간은 따로 측정한다.
- **삭제 경로:** `delete_session`은 mutex 안에서 의도 파일을 원자 기록한 직후, 색인에 sid를 넣고 stamp를 갱신한다. I1을 위해 같은 mutex 구간에서 한다. 이후 모든 `_live`·`register_chunk`·`check_write_allowed`가 즉시 의도를 본다.
- **전체 집합이 필요한 호출**(`list_sessions`, inventory): 색인 ∪ `deleted_sessions` 전체 행을 쓴다. SQL 한 번이고 파일 읽기는 없다.
- **녹음 writer 경로는 journal 파일 I/O 오류로 멈추지 않음**(G05R-04, C00 전달):
  - 근거: G-P05 재확인 `docs/reviews/g05-pending-deletion-review.md` 'RECHECK 1'의 G05R-04(LF sha256 `07edfe8f…`), 인용이며 직접 측정 아님.
    - 녹음 writer의 `register_chunk`가 `_live` → `_deletion_intents`로 **모든 세션의** journal 파일을 연다.
    - Windows에서는 방금 rename으로 게시한 파일을 처음 열 때 잠깐 `PermissionError`가 날 수 있다.
    - 녹음 중 다른 세션을 삭제한 직후 그 journal 읽기에 `PermissionError`를 한 번 주입하면, 녹음이 멈추고 400블록 중 294블록이 거부됐다(HEAD 295블록).
    - 자연 발생은 같은 프로세스 3,000회 게시 동안 0회, 프로세스 간 1회 관측이었다.
  - 설계:
    - writer 경로(`register_chunk`, 그리고 §12.4가 승인되면 append)의 의도 판정은 **자기 세션**만 본다: 색인 소속, `deleted_sessions` PK 조회, 자기 세션 의도 파일의 존재. 다른 세션의 journal 파일은 열지 않는다. stamp가 달라도 writer 경로에서는 전체 재검증을 하지 않는다.
    - 자기 세션의 의도 판정 자체가 I/O 오류로 확인되지 않으면, 그 세션의 등록은 거부한다(I1 쪽으로 fail closed).
    - 열기와 관리 경로(`create_session`, `list_sessions`, inventory, 복구·확정 admission, 삭제)의 journal 검증은 지금처럼 fail closed다. 오류는 그 관리 작업만 실패시키고 다른 세션의 녹음은 멈추지 않는다.
- **`check_write_allowed`(`_coordination.py`):** 바꾸지 않는다. 그 세션의 의도 파일 존재와 DB 세대만 보며 N에 비례하지 않는다. append마다 SQLite 읽기 연결을 여는 비용은 LAT 측정값으로만 남긴다.
- **의미 차이 하나(C00 확인 요청 §11.6):**
  - 이미 유효했던 의도 파일의 **내용만** 외부에서 손상되면 디렉터리 stamp가 바뀌지 않아, 다음 열기 때까지 감지하지 못한다.
  - 그동안 그 세션은 계속 의도 있음(차단)으로 남으므로, 그 세션에 대해서는 fail closed다.
  - 지금은 매 호출 `ValidationError`로 Library 전체가 실패한다.
  - 항목마다 stat하면 감지할 수 있지만 N에 비례하는 syscall이 mutex 안으로 돌아온다.

### 11.3 분모

| 집합 | 정의 | 분모 |
| --- | --- | ---: |
| IDX-SCALE | 삭제 기록 N {0, 100, 400, 1000} × 동작 {`create_session`, `get_session`, `register_chunk`, `list_sessions`} | 16 |
| IDX-FAIL | journal 상태 7(정상 / 열린 뒤 `.tmp` 추가 / 열린 뒤 미인식 파일 추가 / 열린 뒤 손상 의도 파일 추가 / 의도 파일 외부 삭제 / journal 디렉터리 제거 / DB 행만 있고 journal 파일 없음) × 질의 2(`_live(sid)` 경유 `get_session`, `list_sessions`) | 14 |
| IDX-HB | N=400 tombstone이 있는 상태에서 HB1(seal ∥ 삭제) 4위치 | 4 |
| IDX-OPEN | 열 때 상태 3(정상 N=400 / `.tmp` 있음 / 손상 의도 있음) | 3 |
| IDX-UI | 실시간 녹음 12초 + 250ms마다 `chunks()`를 부르는 GUI tick 대리 thread, 완료 삭제 N {0, 1000} × 트랙 {1, 2} (G05R-02 권고) | 4 |
| IDX-IO | G05R-04 반례와 경계 5행: IO1 녹음 중 다른 세션 삭제 직후 그 journal 읽기에 `PermissionError` 1회 주입 / IO2 같은 파일에 지속 주입 / IO3 자기 세션 의도 확인에 I/O 오류 / IO4 외부 journal 변경 뒤 관리 `list_sessions`에 `PermissionError` / IO5 열 때 journal 파일 `PermissionError` | 5 |
| **합계** | | **46** |

### 11.4 독립 oracle

- **IDX-SCALE:** 결과 집합은 시험이 `json` 모듈로 journal과 DB를 직접 읽어 계산한 집합과 같아야 한다. 각 동작의 root 최장 보유 <50ms이고, N이 늘어도 상한을 넘지 않는다.
- **IDX-FAIL:**
  - `.tmp`, 미인식 파일, 손상 의도 추가, journal 제거: `ValidationError`(지금과 같은 fail closed)
  - 의도 파일 외부 삭제: 그 세션이 더는 의도로 보이지 않는다(지금과 같음). 단 DB 행이 있으면 계속 의도다.
  - DB 행만 있음: 의도로 본다.
- **IDX-HB:** HB1 기대(§4.3)를 그대로 쓴다. tombstone이 많아도 의도 반영이 즉시 이루어지는지 본다.
- **IDX-OPEN:** 열기는 성공한다. 정상이면 색인이 oracle 집합과 같고, 손상이면 첫 질의부터 `ValidationError`다.
- **IDX-IO:**
  - IO1·IO2: 녹음은 계속된다. 400블록 중 거부 0, `storage_failed` 거짓, 삭제된 세션은 그대로 차단된다.
  - IO3: 그 세션의 등록은 거부되고 writer 오류로 INTERRUPTED가 된다. 의도 뒤 새 행은 0이다(I1).
  - IO4: 관리 작업만 `ValidationError`(또는 비민감 오류)로 실패한다. 동시에 녹음 중인 다른 세션은 거부 0이다.
  - IO5: 열기는 성공한다. 첫 관리 질의부터 fail closed이고, 새 세션 생성도 거부된다.
- **IDX-UI:** 네 행 모두 다음을 만족한다.
  - GUI tick 대리 thread와 writer·sealer의 root 최장 보유 <50ms
  - 거부 블록 0, 유실 프레임 0
  - 저장 프레임 = 제출 프레임(1트랙 576,000, 2트랙 1,152,000)

### 11.5 mutation

| ID | 변이 | 잡아야 할 assertion |
| --- | --- | --- |
| IX1 | 삭제 경로가 색인을 갱신하지 않음 | IDX-HB D<V·V<D<P의 새 bundle 0, P<D<G의 catalog 새 행 0 |
| IX2 | stamp 비교 제거(외부 변경을 재검증하지 않음) | IDX-FAIL의 열린 뒤 `.tmp`·미인식·손상 추가 행 |
| IX3 | DB 행 합집합 제거(색인만 사용) | IDX-FAIL의 DB 행만 있음 행 |
| IX4 | 매 호출 전체 재검증(회귀) | IDX-SCALE N=1000 행의 보유 <50ms |
| IX5 | writer 경로가 지금처럼 모든 세션의 journal을 연다 | IDX-IO IO1·IO2의 거부 0(G05R-04 반례) |

### 11.6 C00 확인 요청

- §11.2의 의미 차이: 기존 유효 의도 파일의 내용만 손상된 경우 다음 열기까지 감지하지 않는다. 그 세션은 계속 차단된다. 이를 수용할지, 항목별 stat(N에 비례)을 택할지 정해 주세요.
- 측정 수치는 G-P05 독립 검토자의 결과를 받은 뒤 이 절에 덧붙인다.
- 구현 상태(PART2): 답을 받기 전에, 차이를 `_live`와 writer 경로로만 좁혀 구현했다. 관리 경로는 내용 손상을 계속 매번 감지한다. 자세한 내용은 §14.3·§14.4-10에 있다.

**C00 결정: 수용**(IMPLEMENTATION_READY 보고 뒤)
- 수용한 범위:
  - 색인 판정은 `_live`와 writer 경로에 한정한다(`get_session`, `chunks`, `create_session`, 외부 `register_chunk`, append·seal·capability 등록).
  - 관리 경로는 journal 내용 손상을 계속 매 호출 감지한다: `list_sessions`, inventory, 복구·확정·seal admission, 삭제·재시도·대기 목록.
- 수용 근거:
  - 그 세션은 차단된 채로 남는다. 제자리 손상은 항목 이름을 바꾸지 않아 색인과 이름 목록이 계속 의도를 보이므로, 녹음·등록·조회는 fail closed다(`inplace_rewrite` 2행).
  - 손상은 관리 작업에서 드러난다. 목록·삭제·복구·확정이 `DELETION_HISTORY_UNAVAILABLE`로 실패하고, 다음 열기는 전체 검증한다.
  - 항목별 stat(A5)은 N에 비례하는 syscall을 mutex 안으로 되돌린다. G05R-02·G05R-04(녹음 정지)를 다시 만든다.
- 남는 한계(외부 도구가 journal을 직접 바꾸는 경우, §14.3 표):
  - 기존 의도 파일의 제자리 내용 손상과 다른 세션 DB 행의 손상은 `_live`와 writer 경로가 감지하지 않는다. 관리 작업이나 다음 열기까지 남는다.
  - 파일 시스템 시계를 믿을 수 없는 볼륨에서는 같은 tick의 외부 변경을 놓칠 수 있다. settle 규칙(2.5초)은 이 PC의 NTFS에서만 확인했다. FAT·exFAT·네트워크 볼륨은 미검증 한계로 둔다(C00 결정 (3)).

## 12. PART1 구현 반영(2026-11-23, `chunks.py`·`recording.py`)

### 12.1 구현

- **`storage/chunks.py`:**
  - writer 상태: `_sealing`(seal 시작부터 release까지), `_held`(소유자가 등록까지 붙잡음), `_capability`.
  - `has_active_writer`는 `_pcm is not None or _sealing`이다.
  - `seal_chunk()` 흐름:
    1. mutex 안: 삭제 검사, 봉인 가능 확인, SEALING 시작
    2. mutex 밖: `_prepare` — fsync, descriptor, 파일 닫기, 1회 검증
    3. mutex 안: 삭제 재검사, mkdir, rename, capability 발급
  - `seal()`은 `seal_chunk()` 뒤 붙잡혀 있지 않으면 바로 release한다. 기존 직접 호출자와 호환된다.
  - 게시 뒤 `verify_bundle`은 없앴다. 1회 검증은 `verify_bundle`과 같은 검사를 최종 위치 기준으로 한다(`_verified(path, location)`로 공통화).
  - 복구의 비공개 `_seal()`은 잠금 없는 전체 seal 의미를 유지한다. HEAD `library.py`의 `_salvage`가 이 비공개 메서드를 직접 부르고, `library.py`는 G-P05 뒤에만 바꿀 수 있기 때문이다.
  - capability: `SealedChunk`는 모듈 `WeakSet` `_issued`에 등록된 **바로 그 객체**이고, writer의 `_capability`가 같은 객체일 때만 `is_issued()`가 참이다. descriptor, 직접 생성한 객체, 복사본, release된 객체는 거짓이다(단위 시험 CAP 4행).
- **`app/recording.py`:**
  - 소비자는 append만 한다. 청크가 차면 `SEAL_CAPACITY=4` FIFO로 넘긴다.
  - sealer thread는 FIFO 순서로 `hold()` → `seal()` → `register_chunk()` → `unhold()`를 한다.
  - `is_live`와 `worker_alive`는 두 thread를 모두 본다. `_drain`과 `join_writer`는 두 thread를 같은 시간 제한으로 join한다(`WRITER_ACK_PENDING` 의미 유지).
  - 오류는 첫 오류만 `_writer_error`에 남기고 수락을 멈춘다. 이후 FIFO의 writer는 abort(staging 보존), 상태는 INTERRUPTED다.
- **sealer가 `seal_chunk()` 대신 `hold()`+`seal()`을 쓰는 이유:** 기존 시험 여러 개(`test_app_service.py`, `test_recording_control.py`, G04 시험)가 `ChunkWriter.seal`을 monkeypatch해 seal 실패를 주입한다. 주입 지점을 그대로 살려 기존 시험의 의미를 바꾸지 않으려는 것이다. 기존 시험 파일은 수정하지 않았다.

### 12.2 계약과 달라진 점

1. **UNIT 분모 21 → 25:** C00 결정 2의 capability 위조 불가 조건을 시험하는 CAP 4행(발급 / release 뒤 / 직접 생성 / 복사)을 더했다.
2. **W 표의 abort:** 계약 §4.3의 "PUBLISHED·ABORTED는 모두 거부"는 abort를 포함하지 않는다. abort는 어느 상태에서도 예외 없이 열린 것만 닫는다. SEALING에서 abort해도 붙잡힌 seal은 활성으로 남는다.
3. **HB 위치를 mutex 밖에서만 멈추게 정의:**
   - HB1: D<V(`_prepare` 직전), V<D<P(`_prepare` 직후), P<D<G(`register_chunk` 직전), G<D(release 뒤 정지·삭제)
   - HB2·HB3: 앞 세 위치 + release 직전(`unhold` 직전). 정지(drain)를 별도 thread로 진행하는 동안 시도한다.
   - HB4: V 전·V 후·등록 전 3위치
   - HB5: 같은 3위치. 다른 트랙의 청크가 FIFO에 들어가는지로 소비자가 막히지 않음을 확인한다.
   - HB6: 검증 전 / 검증 중 / 실패 처리 뒤 / 정지 뒤
4. **MU6 동등성과 MU6b 추가:**
   - MU6(`is_live`가 sealer를 보지 않음)은 동등 mutant로 예상했다. 붙잡힌 writer가 `has_active_writer`로 이미 live이므로, 확정·복구 거부가 그대로 나기 때문이다. 결과는 §13에 적는다.
   - 대신 MU6b(sealer가 `hold()` 없이 seal → 등록 전에 비활성)를 추가했다.
5. **LAT 지연 주입 위치:** 청크당 한 번, `_prepare` 앞(mutex 밖)에 넣었다. backpressure를 만들려고 청크를 1초(48,000프레임)로 줄였다.
   - G05R-02의 관찰 O1에 따라 2트랙 행 2개(`G15-LAT2-two-tracks-seal0`, `-seal1`)를 더했다. 그래서 LAT는 8 → 10이다. 두 행 모두 거부 0을 assert한다.
6. **MU4·MU8과 REG:** `library.py` 범위라 PART2로 넘긴다.
7. **보유 상한 oracle을 경로별로 나눔:**
   - 계약 §4.3은 "writer thread의 root 최장 보유 <50ms(LAT 전 행)"였다. 그런데 G15 뒤 소비자(`recoryn-writer-*`) thread가 root mutex를 잡는 곳은 **append뿐**이다. 소비자의 seal·등록 호출 0회는 구조 검사가 따로 확인한다.
   - append는 C00 결정 4에 따라 fsync 2회를 mutex 안에 남겼으므로, 그 꼬리는 디스크 지연을 따른다.
   - 최종 실행 1회차에서 `G15-LAT2-two-tracks-seal1`의 소비자 최장 보유가 **50.3ms**로 상한을 넘어 실패했다(§13). 원인은 append fsync의 꼬리이며 seal 경로가 아니다.
   - 그래서 다음과 같이 나눴다.
     - sealer와 관리 경로: <50ms(`SHORT_BOUND`)
     - append 전용 소비자: <0.2초(`APPEND_ONLY_BOUND`). seal이 소비자로 돌아오면 0.4초 이상(§2.2)이므로 이 상한과 구조 검사가 둘 다 잡는다.
   - 결정 4의 판단 근거로 소비자 보유의 p99도 기록한다.
   - HB4의 `recoryn-*` 보유 검사도 같은 기준으로 나눴다.
8. **지연 0일 때 시험 wrapper의 양보 제거:** 처음 LAT wrapper는 지연이 0이어도 `time.sleep(0)`을 불렀다. 이 호출은 GIL을 내놓고 thread를 양보해, 소비자가 append마다 두 번씩 sealer에 자리를 내줬다. 지연이 있을 때만 sleep하도록 고쳤다(시험 코드의 교란이며 제품 결함이 아니다).
9. **2트랙 LAT 행은 거부 수를 측정만 함:**
   - LAT2 두 행(2트랙, 1초 청크, 초당 200블록)은 단독 반복 실행에서도 거부가 0·23·29·35·48·57블록으로 흔들렸다(§13.3). FIFO 최대는 1~4로 상한 안이었고, sealer 보유도 짧았다.
   - 병목은 소비자의 append다. probe 3에서 append 중앙값 1.82ms 가운데 `check_write_allowed`가 0.98ms(블록마다 SQLite 읽기 연결을 새로 엶), fsync 2회가 0.72ms였고, 둘 다 mutex 안이다.
   - 이 비용은 PART1 범위(seal pipeline) 밖이다. 그래서 LAT2는 구조 검사와 보유 상한만 assert하고, 거부 수는 측정값으로 남긴다. 1트랙 행의 거부 0 assert는 유지한다(모든 실행에서 0).
   - 같은 조건을 2초 청크·12초로 재면 HEAD 510·540블록 대 PART1 0·0이었다(§13.3, probe 4). G05R-02의 관찰 O1은 PART1이 크게 줄인다. 다만 포화 여유는 좁다.

### 12.4 PART2 전 추가 결정 요청

- **append의 삭제 검사 비용:**
  - 현상: `check_write_allowed`는 append마다 SQLite 읽기 연결을 열어 `deleted_sessions`를 조회한다(블록당 중앙값 약 1ms, append의 54%, root mutex 안). 2트랙에서는 소비자 포화의 주원인이다.
  - 제안: §11 색인을 만든 뒤, 같은 프로세스의 Library가 root별 메모리 의도 집합을 `_coordination`에 등록한다. append는 그 집합을 O(1)로 보고, durable 검사는 writer 열기와 게시(seal)에서만 한다. Library가 없는 직접 사용은 지금처럼 durable 검사를 한다.
  - 필요한 일: `storage/_coordination.py` 수정(지금 승인 범위 밖)과 `library.py`의 삭제 경로 갱신. 같은 mutex 구간에서 집합을 갱신하므로 I1은 유지된다.
  - 포함 여부를 정해 주세요.
- **append fsync를 mutex 밖으로(결정 4):** LAT의 소비자 보유 p99(§13.3)와 probe 3을 근거로 판단해 주세요. 바뀌는 범위는 `chunks.py` append뿐이다. check+write는 mutex 안에 두므로 I1(의도 뒤 write 0)은 유지된다.

**C00 결정(PART1 보고 뒤)**
1. `storage/_coordination.py`를 쓰기 범위에 더한다. 색인을 append 판정에도 쓰되, 다음 두 가지를 문서에 적는다.
   - 같은 프로세스 안에서 I1을 어떻게 보장하는지(색인 갱신과 의도 기록의 순서·잠금) → §14.2
   - 단일 writer 계약 밖에서 기존보다 약해지는 점과 대안 → §14.3
2. append fsync는 mutex 안에 둔다. (1) 뒤 2트랙을 다시 재고, 거부가 남을 때만 근거와 함께 다시 요청한다 → §15
3. 2트랙 거부는 측정값으로 둔다. (1) 뒤 안정적으로 0이면 assert로 올린다. 경로별 상한(sealer·관리 <50ms, append 전용 소비자 <0.2초)은 승인한다. CI 러너가 이 PC보다 1.4~1.7배 느린 점(GT-P04 50.2ms 사례)에 대한 여유 근거를 적는다 → §15

### 12.3 분모 재집계

| 단계 | 집합 | 분모 |
| --- | --- | ---: |
| PART1(실행) | UNIT 25 + HB 28 + CRASH 7 + LAT 10 | 70 |
| PART2(대기) | REG 3 + 겹침 의도 행 1 + §11 IDX 46 | 50 |
| **합계** | | **120** |

## 13. PART1 실행 결과(2026-11-23)

- 환경: Windows `.venv` Python 3.13.1, `QT_QPA_PLATFORM=offscreen`, `-p no:cacheprovider`, OS TEMP 아래 고유 basetemp, `-W error::ResourceWarning`.
- 모든 실행은 **`git archive HEAD` + G-P15 파일 4개만 덮어쓴 격리 사본**에서 했고, import 경로가 사본 `src`임을 매번 확인했다.
- 작업 중 HEAD가 2933573에서 `d26f974`(GT-P04, 시험 1개만 변경)로 바뀌었다. 두 commit 사이에 `chunks.py`·`recording.py`·`library.py` 차이는 없다. 최종 시험(§13.1 3회차)과 최종 mutation(§13.4)은 둘 다 `d26f974` 기준이다.

### 13.1 시험

| 실행 | 결과 |
| --- | --- |
| 신규 2파일 + 기존 관련 시험: `test_storage.py`, `test_process_crash.py`, `test_storage_integrity.py`, `test_pcm_storage_oracle.py`, `test_app_service.py`, `test_recording_control.py`, `test_desktop_independent.py`, `test_desktop.py`, `test_unfinished_sessions.py`, `test_unfinished_recovery.py`(G04 PERF 포함), `test_cli.py`, `test_cli_finalize.py`, `tests/ui` 전체 | **1025 passed**(482.96s), 실패·오류·skip 0. 사본 `%TEMP%\recoryn-g15-final3-…`, JUnit sha256 `3c3064f9…37cfc13e` |
| 분모 | UNIT 25 + HB 28 + CRASH 7 + LAT 10 = 70. 분모 대조 node 2개(단위 1, 통합 1)가 누락·중복 0을 확인했다 |
| 기존 시험 파일 | 수정 없음. seal 실패 주입(`ChunkWriter.seal` monkeypatch)을 쓰는 기존 시험도 그대로 통과했다 |

최종 실행까지의 경과(숨기지 않음):
- 1회차: 1024 passed, 1 failed. `G15-LAT2-two-tracks-seal1`에서 소비자 root 최장 보유가 50.3ms로 50ms 상한을 넘었다. 원인과 oracle 분리는 §12.2-7이다.
- 2회차: 1024 passed, 1 failed. `G15-LAT2-two-tracks-seal0`에서 거부가 233블록이었다. 원인과 측정 전용 전환은 §12.2-8·9다.
- 3회차(최종): 1025 passed.

### 13.2 측정: 변경 전후

**probe 4: 같은 seal 지연을 변경 전 HEAD에 주입**(1트랙, 1초 청크, 6초)
- 파일: `…\g15probe\probe_head_latency.py`, LF sha256 `75110a71…f786`
- 결과 sha256: `0b3b4d32…a726`

| seal 지연 | 변경 전 writer root 최장 | 변경 전 거부 블록 | 변경 후(LAT 최종) writer 최장 | 변경 후 sealer 최장 | 변경 후 거부 |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 0초 | 0.415초 | 0 | 39ms | 5ms | 0 |
| 1초 | 1.351초 | 35 | 16ms | 37ms | 0 |
| 3초 | 3.370초 | 144 | 22ms | 37ms | 0 |

**probe 5: 2트랙, 2초 청크, 12초, 지연 주입 없음**(G05R-02 관찰 O1 재현)
- 파일: `…\g15probe\probe_two_tracks.py`, LF sha256 `b144ae62…348a`

| 코드 | 회차 | 거부 블록 | 유실 프레임 | writer root 최장 |
| --- | ---: | ---: | ---: | ---: |
| HEAD | 1 | 510 | 244,800 | 0.811초 |
| HEAD | 2 | 540 | 259,200 | 0.724초 |
| PART1 | 1 | 0 | 0 | 0.105초 |
| PART1 | 2 | 0 | 0 | 0.022초 |
| PART1 + 등록 재검증 생략(PART2 흉내) | 1 | 0 | 0 | 0.029초 |
| PART1 + 등록 재검증 생략(PART2 흉내) | 2 | 0 | 0 | 0.028초 |

### 13.3 LAT 최종 측정(최종 사본, 10행)

`lat_final.jsonl` sha256은 §13.5 표에 있다. 모든 행에서 소비자 thread의 seal·등록 호출은 0회였고, 저장 프레임 = 제출 프레임이었다.

| 행 | 트랙 | seal 지연 | append 지연 | writer 최장 | writer p99 | sealer 최장 | 거부 | FIFO 최대 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| LAT-seal0-append0ms | 1 | 0 | 0 | 39.4ms | 10.9ms | 5.0ms | 0 | 0 |
| LAT-seal0.2-append0ms | 1 | 0.2초 | 0 | 21.3ms | 12.3ms | 4.7ms | 0 | 0 |
| LAT-seal1-append0ms | 1 | 1초 | 0 | 16.1ms | 9.3ms | 36.9ms | 0 | 2 |
| LAT-seal3-append0ms | 1 | 3초 | 0 | 22.1ms | 9.2ms | 36.6ms | 0 | 3 |
| LAT-seal0-append5ms | 1 | 0 | 5ms | 26.2ms | 21.4ms | 4.6ms | 0 | 0 |
| LAT-seal0.2-append5ms | 1 | 0.2초 | 5ms | 25.1ms | 22.2ms | 4.5ms | 0 | 0 |
| LAT-seal1-append5ms | 1 | 1초 | 5ms | 30.2ms | 21.5ms | 5.2ms | 0 | 0 |
| LAT-seal3-append5ms | 1 | 3초 | 5ms | 41.1ms | 21.8ms | 35.7ms | 0 | 2 |
| LAT2-two-tracks-seal0 | 2 | 0 | 0 | 19.9ms | 12.4ms | 9.8ms | 0 | 1 |
| LAT2-two-tracks-seal1 | 2 | 1초 | 0 | 14.7ms | 5.9ms | 13.2ms | 0 | 4 |

- 2트랙 행의 이전 단독 반복(시험 wrapper 교란 제거 뒤 3회): 거부가 23·57, 0·0, 0·29블록이었다. 같은 PC에서 다른 세션이 작업 중이었다. 그래서 2트랙의 거부 0은 assert하지 않는다(§12.2-9).

**probe 3: append 한 번의 비용**(1트랙, 1,000블록, 결정 4 근거)
- 파일: `…\g15probe\probe_append_cost.py`, LF sha256 `489462b9…e376`
- 결과 sha256: `be8fe334…d64f`

| 구간 | 중앙값 | p99 | 최대 |
| --- | ---: | ---: | ---: |
| append 전체(mutex 안) | 1.822ms | 3.031ms | 15.642ms |
| `check_write_allowed` | 0.976ms | 1.505ms | 10.691ms |
| fsync 2회 | 0.718ms | 1.625ms | 3.726ms |

### 13.4 mutation

방법:
- 사본은 `%TEMP%\recoryn-g15-mut-a830268d48ee47759368583ebf1c7cd7`(HEAD `d26f974` + G-P15 4파일)이다. sentinel exit 0으로 사본 import를 확인했다.
- 대상은 신규 2파일 72 node(분모 70 + 대조 2)다.
- 정상본: 72 passed. 정상본 LF sha256은 `chunks.py` `ae40822e…942a`, `recording.py` `2159eb07…ff7e`이며, 모든 mutant 뒤 복원 hash가 같았다.
- 보고서 sha256: `413b0ba47b98de1477df1a84f60453116d459063ff172f9112a9d0da8649aadd`

| mutant | 변이 | 실패 수 | 목표 검출 | 대표 실패 node |
| --- | --- | ---: | --- | --- |
| MU1 | 게시 단계의 삭제 재검사 제거 | 2 | 예 | HB1 before-verify·after-verify |
| MU2 | 파일 닫는 순간 비활성(`_sealing` 무시) | 8 | 예 | HB1 after-verify·before-register, HB3 3행, HB6 during-verify, W SEALING 2행 |
| MU3 | 준비 단계 검증 생략 | 6 | 예 | 손상 staging 3행, HB6 2행, verify-once |
| MU5 | `_drain`이 sealer를 기다리지 않음 | 34 | 예 | HB1~HB6 다수, LAT 다수 |
| MU6 | `is_live`가 sealer를 보지 않음 | 0 | **아니오(동등)** | — |
| MU6b | sealer가 `hold()` 없이 seal(등록 전 비활성) | 3 | 예 | HB1 before-register, HB3 before-register·before-release |
| MU7 | 준비 단계 검증을 다시 mutex 안으로 | 25 | 예 | LAT의 sealer 보유, HB4 관리 대기, HB1·HB2·HB3 일부 |

- **MU6은 동등 mutant다.**
  - sealer가 청크를 처리하는 동안 writer는 붙잡혀(`hold`) 있어 `has_active_writer`가 이미 참이다. 그래서 확정·복구 거부가 `is_live`와 무관하게 난다.
  - 마지막 청크를 등록하고 release한 뒤 sealer가 STOP을 받기 전까지의 구간에는, 등록되지 않은 청크가 없다.
  - 따라서 `is_live`의 sealer 포함은 방어 중복이다. 첫 실행(HEAD 2933573, 보고서 `77c876e0…f2d2`)에서도 같은 결과였다.
- MU4(등록의 `_live` 재검사)와 MU8(겹침 검사 축소 결함)은 `library.py` 범위라 PART2에서 실행한다.

### 13.5 제출 파일과 sha256(LF)

| 파일 | sha256(LF) |
| --- | --- |
| `src/recoryn/storage/chunks.py` | `ae40822e3018d4c08f51a8cab229a827afb6364253dc5de6652f0af052c8942a` |
| `src/recoryn/app/recording.py` | `2159eb07b14c4a17f20bed61d3045946ac703a5efaa33f3aae314f2b1e84ff7e` |
| `tests/unit/test_seal_phases.py`(신규) | `390b04fb2bfee5468e80d3328783d362329a20e9ea951c5a69dec2234b8d6974` |
| `tests/integration/test_seal_mutex.py`(신규) | `895f434c7bc910bbd2868b5bdb611e3852c2f187a45fb6530eba4fedab9c315d` |
| LAT 최종 측정 `lat_final.jsonl`(scratchpad의 `g15probe`) | `3eaec58737142068629d833dbae4b28d78c4600c7414aa468094119227f15a03` |

- 이 문서 자체의 hash는 자기 참조를 피하려고 PART1_READY 보고에 적는다.

### 13.6 정적 검사(최종 사본 안)

- `ruff check --no-cache src tests scripts packaging`: 통과
- `ruff format --no-cache --check src tests scripts packaging`: 159파일 통과
- `python -m mypy src/recoryn scripts packaging`: 84파일 이상 없음

## 14. PART2 구현 반영(2026-11-23, 기준 HEAD `133b010`)

- C00 신호(G-P05 push `133b010`) 뒤 `storage/library.py`를 바꿨다. C00 결정(§12.4 (1))으로 `storage/_coordination.py`가 쓰기 범위에 더해졌다.
- 착수 전 `_coordination.py`가 HEAD와 같음을 확인했다. 다른 단위가 고치고 있지 않았다.
- `chunks.py`·`recording.py`는 PART1 위에 각각 함수 하나, 줄 하나를 더했다.

### 14.1 구현

**등록(§3.3, `register_chunk`)**
- 인자로 `ChunkDescriptor`나 `SealedChunk`를 받는다.
- `chunks.issued_descriptor(candidate, root)`는 이 프로세스의 sealer가 **이 root에** 발급한, 살아 있는 capability만 받아들인다.
- capability 경로는 mutex 밖에서 값싼 동일성 검사만 한다.
  - `descriptor.json` 바이트가 `canonical(descriptor) + "\n"`과 같은지 본다.
  - `audio.pcm` 크기가 `byte_count`와 같은지 본다.
  - 다르면 `ValidationError("Sealed chunk changed before registration")`이다.
- 나머지는 지금처럼 `verify_bundle` 뒤 `_live`를 거친다: 공개 descriptor, release·복사·직접 생성한 capability, 복구 채택.
- mutex 안의 순서는 다음과 같다.
  1. claim 검사
  2. 의도 검사: capability는 자기 세션만(§14.1 writer 경로), 그 밖은 `_live`
  3. 같은 ID 충돌 검사
  4. 세션 상태 확인. `get_session` 대신 직접 SELECT해 `_live`의 중복 호출을 없앴다.
  5. 겹침 검사
  6. insert
- 겹침 검사는 같은 세션·트랙·epoch에서 범위가 겹치는 행 하나를 SQLite JSON1(`json_extract`) 질의로 찾는다.
  - Python에서 세션의 모든 행을 decode하지 않는다.
  - 스키마와 색인은 바꾸지 않았다(이주 없음). 질의는 여전히 그 세션의 행을 훑지만, 그 일을 C에서 한다. 비용은 REG 측정(§15)에 있다.

**삭제 의도 색인(§11)**
- 상태:
  - `_intent_journal`: 검증된 journal(세션 → 세대)
  - `_intent_stamp`: journal 디렉터리의 `(st_dev, st_ino, st_mtime_ns)`
  - `_intent_names`: 색인이 뜻하는 항목 이름 집합
  - `_intent_settled`: settle된 이름 목록이 그 stamp에서 색인과 일치했는지
- 열 때 journal 전체를 지금과 같은 규칙으로 한 번 검증한다. 실패하면 색인을 무효로 두고 열기는 성공한다. 그 뒤 모든 질의가 전체 재검증을 시도하고, 실패하면 `DELETION_HISTORY_UNAVAILABLE`이다.
- `_index_current()`:
  - stat 1회로 stamp를 비교한다.
  - stamp가 아직 settle되지 않았으면 항목 이름 목록(`os.scandir`)을 색인과 비교한다. 항목은 열지 않는다.
- **settle 규칙**(probe 6, §15):
  - 디렉터리 mtime은 tick 단위로 바뀐다. 이 PC의 NTFS에서는 약 0.5~1ms, FAT에서는 2초다. 같은 tick 안의 두 번째 변경은 stamp를 바꾸지 않는다.
  - 그래서 stamp만 믿는 것은 이름 목록을 그 mtime보다 `_STAMP_SETTLE_NS`(2.5초) 넘게 뒤에 관찰했을 때뿐이다. 그 뒤의 변경은 반드시 더 늦은 tick에 떨어진다.
  - 그 전에는 질의마다 이름 목록을 본다(1,000항목에 약 0.74ms).
- `_live(session)`:
  - 색인과 자기 세션의 `deleted_sessions` 행(PK 조회)으로 판정한다. DB 행과의 합집합 의미는 그대로다.
  - 색인이 현재가 아니면 전체 재검증한다.
  - `get_session`, `chunks`(GUI tick), `create_session`, 외부 `register_chunk`가 이 경로다.
- **관리 경로는 매 호출 전체 검증한다**(§14.4-2):
  - 대상: `list_sessions`, inventory, 복구·확정·seal admission, `recover_session`, `finalize_unfinished`, 그리고 삭제·재시도·대기 목록(G-P05 그대로)
  - G-P05의 선읽기(`_journal_prefetch`)로 mutex 밖에서 읽는다. 이 Library가 그 사이 의도를 게시했으면 mutex 안에서 다시 읽는다.
- `_publish_intent`는 한 root mutex 구간에서 다음을 차례로 한다.
  1. `_history_version` 증가
  2. 색인 무효화
  3. 의도 파일 원자 기록(`atomic_json`)
  4. 색인에 세션 추가와 새 stamp 기록. 이때 stamp는 settle 전이다.
  - 기록이 실패하면 색인은 무효로 남고, 다음 질의가 다시 검증한다.
- **writer 경로 `_writer_intent(session)`**(G05R-04):
  - 항목 **이름**과 자기 세션의 DB 행만 본다. journal 파일은 하나도 열지 않는다.
  - 색인이 현재면 `_intent_names`, 아니면 stamp별로 캐시한 이름 목록을 쓴다.
  - `.tmp-` 항목이 있으면 `ValidationError("Incomplete deletion intent")`다. 기존 `check_write_allowed`와 같다.
  - 자기 세션의 답을 확인할 수 없으면 `ValidationError("Cannot verify writer deletion intent")`로 그 쓰기를 거부한다(I1 쪽 fail closed).
- `_append_check`는 `_coordination`에 등록하는 콜백이다. 닫힌 Library면 `None`을 돌려 durable 검사로 넘긴다.

**`storage/_coordination.py`**
- root별 약참조 콜백 등록부(`register_intent_check`, `unregister_intent_check`)를 더했다. Library는 열기 끝에 등록하고 `close()` 첫 단계에 해제한다.
- `check_write_allowed`의 동작:
  - 콜백이 `True`/`False`를 주면 그 답을 쓴다. SQLite 연결을 새로 열지 않는다.
  - 콜백이 없거나 `None`이면 기존 durable 검사를 그대로 한다(의도 파일 존재와 SQLite 읽기 연결).

**`chunks.py`·`recording.py`**
- `issued_descriptor(candidate, root)`: `is_issued`와 같은 조건에 writer root 일치를 더했다.
- sealer는 `register_chunk(item.capability or descriptor)`를 부른다.

### 14.2 같은 프로세스에서 I1을 보장하는 방법(순서와 잠금)

- 쓰기 판정과 의도 게시는 모두 **같은 root mutex**(프로세스 전역 RLock) 안에서 한다.
  - append: `ChunkWriter.append`가 root mutex를 잡은 채 `check_write_allowed` → 콜백 `_writer_intent` → payload·journal 기록과 fsync를 끝낸 뒤 놓는다.
  - seal 게시: mutex 안에서 재검사한 뒤 mkdir·rename한다.
  - 등록: mutex 안에서 `_writer_intent`를 확인한 뒤 insert·commit한다.
  - 의도 게시: `_progress_deletion`이 mutex 한 구간에서 `_publish_intent`(파일 + 색인)와 `_project_intent`(DB 행)를 모두 한다.
- 그래서 어떤 쓰기 판정도 "의도 파일은 있는데 색인에는 없는" 중간 상태를 볼 수 없다.
  - 판정이 mutex를 먼저 잡으면, 그 쓰기는 게시 전에 끝난다.
  - 게시가 먼저면, 다음 판정은 색인과 DB 행 모두에서 의도를 본다.
- 판정은 서로 독립한 세 근거 중 하나라도 의도를 보이면 거부한다.
  - (a) 색인의 세션 소속
  - (b) settle 전 이름 목록. 게시 직후 stamp는 언제나 settle 전이라, 다음 판정은 실제 항목 이름을 본다.
  - (c) `deleted_sessions` PK 조회
- 콜백 해제와 경쟁하는 경우도 막는다. 콜백을 꺼낸 직후 Library가 닫히면 콜백이 `None`을 돌려 durable 검사로 넘어간다(`G15-U-append-closed-library-durable`).
- mutation 확인(§15):
  - MU4(등록 재검사 제거)는 검출된다.
  - IX1(게시가 색인에 세션을 넣지 않음)은 (b)·(c)가 막아 동등이다.
  - IX1b(IX1 + 즉시 settle 표시)는 (c)가 없는 DB 투영 실패 행에서만 검출된다. 세 근거가 실제로 겹쳐 있음을 보인다.

### 14.3 단일 writer 계약 밖(다른 프로세스·외부 변경)

- 다른 프로세스가 같은 라이브러리를 Library로 여는 것은 OS 잠금(`.writer.lock`)이 막는다. 따라서 다른 프로세스의 Library가 의도를 게시하는 경우는 생기지 않는다(기존과 같다).
- 다른 프로세스가 `ChunkWriter`만 직접 쓰는 경우는 약해지지 않는다. 그 프로세스에는 Library 콜백이 없어 기존 durable 검사를 그대로 한다.
- 기존보다 약해지는 점은 Library를 거치지 않는 **외부 변경**(사람이나 다른 도구가 `deletion-journal/`을 직접 바꿈)에 있다.

| 외부 변경 | G15 전 | G15 뒤 |
| --- | --- | --- |
| 항목 추가·삭제·이름 변경(`.tmp`, 미인식 파일, 새·손상 의도, 의도 삭제, 디렉터리 제거) | 다음 질의에서 감지 | 다음 질의에서 감지: stamp가 바뀌거나, settle 전이면 이름 목록이 다르다(IDX-FAIL 12행) |
| 기존 의도 파일의 **제자리 내용 변경** | 모든 `_live` 질의가 `DELETION_HISTORY_UNAVAILABLE` | 관리 경로만 감지한다(목록·삭제·복구·확정). `_live`와 writer 경로는 감지하지 않지만, 그 세션은 이름이 남아 계속 차단된다(`inplace_rewrite` 2행) |
| 다른 세션 DB 행의 손상 | 모든 `_live` 질의가 실패 | 관리 경로만 실패한다. `_live`는 자기 세션 행만 검증한다 |
| 시계 가정이 깨지는 볼륨(원격 공유의 서버 시계, 시스템 시계 급진) | 영향 없음 | settle 판정이 틀려 같은 tick의 외부 변경을 놓칠 수 있다. 시계 역행은 settle을 늦출 뿐이라 안전하다 |

- 위 표의 근거는 직접 확인했다.
  - probe 6: 제자리 다시 쓰기는 디렉터리 mtime을 바꾸지 않았다(TEMP·`D:` 모두).
  - 같은 디렉터리의 연속 생성 400회 가운데 167회(TEMP)와 304회(`D:`)가 직전과 같은 mtime이었다. 해상도는 약 0.5~1ms였다.
- 대안(제안):
  - **A1 열 때 감지 + fail closed(구현함):** 열 때 전체 검증하고, 실패하면 모든 의도 질의가 fail closed다(IDX-OPEN, IO5).
  - **A2 관리 경로 전체 검증(구현함):** 내용 손상은 목록·삭제·복구·확정에서 드러나고, 그 작업만 실패한다.
  - **A3 주기적 전체 검증:** 예를 들어 GUI tick이 N초마다 mutex 밖에서 선읽기와 대조한다. 제자리 변경을 감지하는 지연에 상한이 생긴다. 비용은 mutex 밖 O(N) 파일 읽기다. 구현하지 않았다.
  - **A4 시계를 믿을 수 없는 볼륨:** settle을 끄고 매번 이름 목록을 비교한다(1,000항목 약 0.74ms). 또는 열 때 그런 볼륨을 거부한다. 구현하지 않았다.
  - **A5 항목별 stat(§11.6 원안):** 제자리 변경까지 본다. 대신 N에 비례하는 syscall이 mutex 안으로 돌아온다. 기각을 권고한다.

### 14.4 계약과 달라진 점

1. **stamp 정의:**
   - §11.2는 `(st_mtime_ns, 항목 수)`였다. 항목 수를 알려면 목록이 필요하다(O(N)).
   - 대신 `(st_dev, st_ino, st_mtime_ns)`에 settle 규칙을 더하고, settle 전에는 이름 목록을 본다.
   - 이유는 probe 6이다. mtime만으로는 같은 tick의 두 번째 변경을 놓친다. 시험의 외부 변경이 대부분 열기 직후 같은 tick에서 일어나므로, 이 규칙 없이는 IDX-FAIL이 불안정해진다.
2. **전체 집합 질의:**
   - §11.2는 "색인 ∪ DB 전체 행, 파일 읽기 없음"이었다.
   - 구현은 G-P05 선읽기로 매 호출 전체 검증한다(mutex 밖). 그 이유는 다음과 같다.
     - 내용 손상 = 관리 실패라는 기존 의미를 지킨다. §11.6의 의미 차이를 `_live`와 writer 경로로 좁힌다.
     - G-P05의 손상 시험(제자리 내용 손상을 포함한 HISTORY 표)을 수정 없이 통과한다.
   - 비용은 `list_sessions`, inventory, admission이 mutex 밖에서 N개 파일을 읽는 것이다. IDX-SCALE은 root 보유만 잰다.
3. **`check_write_allowed`:** §11.2는 "바꾸지 않음"이었다. C00 결정(§12.4 (1))에 따라 색인을 append 판정에도 쓴다.
4. **등록의 세션 상태 확인:** `get_session`(`_live` 재호출) 대신 직접 SELECT한다. 의도는 바로 앞의 `_writer_intent`나 `_live`가 이미 확인했다.
5. **자기 세션 확인 실패의 오류 문구:** `Cannot verify writer deletion intent`(ValidationError)다. Library가 닫힌 뒤의 durable 검사는 기존 문구(`Cannot verify writer deletion generation`)를 그대로 쓴다.
6. **`133b010` 의미 반영(G15 신규 시험만 수정):**
   - G-P05는 살아 있는 녹음 소유자를 첫 삭제 차단 사유(`SESSION_LIVE`)로 둔다. 회귀 1회차에서 G15 시험 4개가 실패했다(§15).
     - HB1 3행의 첫 삭제 사유를 `ACTIVE_READER_OR_WRITER`에서 `SESSION_LIVE`로 고쳤다.
     - HB6 after-failure의 첫 삭제를 `DELETED_LOCAL`에서 `DELETE_PENDING`으로 고쳤다. sealer가 join될 때까지 녹음은 live다.
   - 기존 시험 파일은 고치지 않았다.
   - MU2의 목표 node를 HB1에서 W 표 SEALING 2행으로 옮겼다. HB1에서는 `SESSION_LIVE`가 먼저 막아 MU2가 가려진다.
7. **분모 추가:**
   - IDX-FAIL 14 → 16: 제자리 내용 변경 상태를 더해 §11.6의 수용 차이를 시험으로 고정했다.
   - IDX-HB 4 → 5: DB 투영 실패 행. 색인과 이름 목록만으로 막는지 본다.
   - UNIT +19:
     - 겹침 의도 행 1(§7 MU8 계획)
     - 등록 경로 5: C00 결정 2의 조건. capability만 `verify_bundle`을 생략하고, 동일성 검사는 남는다.
     - append 판정 2: 열린 Library는 색인, 닫힌 Library는 durable 검사
     - fail closed 11(FC): CI와 같은 coverage 검사에서 storage 묶음 여유가 줄어(§15.6), 새 코드의 오류 경로마다 손으로 쓴 기대를 가진 행을 더했다.
       - 같은 mtime tick의 이름 변경
       - 재검증 중의 변경
       - journal 폴더 소실(질의와 capture 모두 거부)
       - 지원하지 않는 DB 상태
       - settle된 이름 목록 캐시와 그 뒤 자기 세션 의도
       - close 뒤 콜백
       - 행 없는 세션의 capability
       - 준비 단계 read-back 불일치
       - 최종 폴더가 이미 있음
       - 게시 중 색인 확인 실패
       - 게시 뒤 stamp 읽기 실패
8. **mutation 추가:** IX1b, 그리고 CO1(append가 등록된 콜백을 무시).
9. **REG 3행:** §4.3은 "결정 승인 시 <50ms"였다. §10.3-3에서 승인됐으므로 assert한다.
10. **§11.6:** 수용 차이를 `_live`·writer 경로로 좁혀 구현했다. 관리 경로는 내용 손상을 계속 감지한다. C00이 수용했다(근거와 한계는 §11.6).
11. **시간 상한과 구조 판정(C00 결정 §15.3 (가)):**
    - 관리·sealer·GUI tick·catalog 경로의 판정 상한을 50ms(`SHORT_BOUND`)에서 0.5초(`HOLD_LIMIT_SECONDS`)로 바꿨다. append 전용 소비자 0.2초는 유지한다.
    - 50ms 이상 보유는 각 MEASURE 행의 `long_holds`에 진단으로만 남는다.
    - 상한을 넓히면 시간으로만 잡던 회귀를 놓칠 수 있다(HEAD 등록은 3,600청크에서 168ms, IX4의 `get_session`은 0.44초). 그래서 기존 행에 구조 판정을 더했다. 분모는 그대로다.
      - REG 3행: 등록 중 catalog descriptor decode 0회, `verify_bundle` 0회
      - IDX-SCALE 16행: root mutex를 쥔 채 journal 파일 읽기 0회(측정 동작과 거부 확인 반복 모두)
    - mutation RG1(겹침 검사를 HEAD의 Python 반복으로 되돌림)을 더했다. 새 구조 판정이 잡는지 본다.

### 14.5 분모 재집계

| 단계 | 집합 | 분모 |
| --- | --- | ---: |
| PART1 | UNIT 25 + HB 28 + CRASH 7 + LAT 10 | 70 |
| PART2 | UNIT 19(겹침 1, 등록 경로 5, append 판정 2, FC 11) + REG 3 + IDX 49(SCALE 16, FAIL 16, HB 5, OPEN 3, UI 4, IO 5) | 71 |
| **합계** | | **141** |

- 분모 대조 node 2개(단위 1, 통합 1)가 누락·중복 0을 확인한다. 그래서 두 파일의 시험 node는 143개다(단위 45, 통합 98).

## 15. PART2 실행 결과(2026-11-23)

- 환경: Windows `.venv` Python 3.13.1, `QT_QPA_PLATFORM=offscreen`, `-p no:cacheprovider`, OS TEMP 아래 고유 basetemp, `-W error::ResourceWarning`.
- 모든 실행은 **`git archive 133b010` + G-P15 파일 6개만 덮어쓴 격리 사본**에서 했다. import 경로가 사본 `src`임을 매번 확인했다.
- 작업 트리에 섞여 있는 다른 단위의 미완성 변경(G-P05b, G-P06)은 사본에 들어가지 않는다.

### 15.1 시험

| 실행 | 결과 |
| --- | --- |
| 최종: G15 2파일 + 관련 기존 시험(`test_storage.py`, `test_process_crash.py`, `test_storage_integrity.py`, `test_pcm_storage_oracle.py`, `test_app_service.py`, `test_recording_control.py`, `test_desktop_independent.py`, `test_desktop.py`, `test_unfinished_sessions.py`, `test_unfinished_recovery.py`, `test_cli.py`, `test_cli_finalize.py`, G-P05 5파일, `tests/ui` 전체) | **1476 passed**(597.36s), 실패·오류·skip 0. 사본 `%TEMP%\recoryn-g15-p2final-fde8b1ea573741318fc8a74a266fe3d9`, JUnit sha256 `a55f91e8d23cedd9dcb392d5160518f3f9720a9a98df3155833a565de51bfc2a`, 전체 로그 sha256 `5cc8f6d44bfa80a463ebfc8cde6f4dae20739d02649c0f563928e39e5e0c1774` |
| 재실행: HEAD가 `6072ef1`(G-P05b: `ui/main.py`, `tests/ui/test_pending_deletion_ui.py`, 문서)로 바뀐 뒤 같은 목록 | **1480 passed**(610.07s), 실패·오류·skip 0. 사본 `%TEMP%\recoryn-g15-p2final2-df1ccfb97320466d8b4d001c9efa9213`, JUnit sha256 `11327255cce45fb6ffbcfdaf8c1dcb71ddf91af9fa3be2a728e213b3e3fa15ee`, 로그 sha256 `b0ce2ca930fb575830198ddfaefd64d6c0b2306bd38238586be945930d3f69e3`. 늘어난 4 node는 G-P05b의 UI 시험이다 |
| G15 2파일 | 위 두 실행에서는 132 node(단위 34, 통합 98)가 모두 통과했다. FC 11행을 더한 최종판 143 node(단위 45, 통합 98)는 단위 파일 단독(45 passed)과 CI 동등 실행(§15.6)에서 모두 통과했다 |
| G-P05 5파일(`test_pending_deletions.py` 141, `test_pending_deletion_restart.py` 137, `test_pending_deletion_case_space.py` 6, `test_cli_pending_deletions.py` 39, `tests/ui/test_pending_deletion_ui.py`(HEAD판) 68) | 391 node 모두 수정 없이 통과. 버전 대조 선읽기와 짧은 mutex 보유 동작도 그대로다 |
| 기존 시험 파일 | 수정 없음 |

최종 실행까지의 경과(숨기지 않음):
- 1회차(settle 규칙 전 `library.py`, LF `4297d2bf…`): 1412 passed, 4 failed. 4건 모두 G15 신규 시험이었다(HB1 3행, HB6 after-failure). 원인은 `133b010`의 `SESSION_LIVE` 우선순위다(§14.4-6).
- 그 사이 probe 6으로 stamp의 같은 tick 결함을 찾아 settle 규칙을 넣었다(§14.4-1).
- 2회차(G15 2파일만): 130 passed, 2 failed. 새 append 판정 2행의 fixture 결함이었다.
  - append 전의 writer는 활성이 아니어서 삭제가 바로 끝났다. 그래서 append 뒤 삭제하도록 고쳤다.
  - G-P05에서는 활성 writer도 `SESSION_LIVE`로 보고된다. 기대값을 그에 맞췄다.
- 그 뒤 단위 파일 34 passed, 최종 1476 passed.

### 15.2 측정(최종 실행 로그의 MEASURE 행)

**REG: 기존 청크 n개 뒤 등록의 root 보유**(capability 경로)

| n | PART1(probe 2, HEAD 등록) | PART2 |
| ---: | ---: | ---: |
| 0 | 1.6ms | 3.1ms |
| 900 | 42.4ms | 4.4ms |
| 3,600 | 167.9ms | 11.4ms |

- 겹침 질의는 여전히 n에 비례하지만 기울기가 약 15분의 1이다. 3,600 청크(2시간) 뒤에도 11ms다.

**IDX-SCALE: 완료 삭제 N개에서 각 동작의 root 보유**

| N | `create_session` | `get_session` | `register_chunk` | `list_sessions` |
| ---: | ---: | ---: | ---: | ---: |
| 0 | 4.1ms | 0.9ms | 3.1ms | 0.3ms |
| 100 | 4.6ms | 1.8ms | 3.4ms | 0.8ms |
| 400 | 4.5ms | 1.2ms | 3.4ms | 1.9ms |
| 1,000 | 19.9ms | 2.1ms | 3.9ms | 5.9ms |

- G05R-02의 HEAD 관측은 400건에서 최대 2.6초였다(인용). `create_session` 1,000건의 19.9ms는 commit 1회를 포함한 한 번의 측정값이다.

**IDX-UI: 실시간 12초 + GUI tick 대리(250ms마다 `chunks()`)**

| N | 트랙 | tick 최장 | sealer 최장 | writer 최장 | writer p99 | 거부 | 저장 프레임 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 1 | 1.8ms | 6.0ms | 15.7ms | 7.8ms | 0 | 576,000 |
| 0 | 2 | 2.0ms | 4.4ms | 12.8ms | 7.6ms | 0 | 1,152,000 |
| 1,000 | 1 | 2.3ms | 3.9ms | 33.1ms | 2.9ms | 0 | 576,000 |
| 1,000 | 2 | 1.8ms | 4.3ms | 10.8ms | 2.8ms | 0 | 1,152,000 |

- G05R-02의 HEAD 관측(인용)은 UI tick 포함 1,000건에서 923블록 거부, 443,040프레임 유실이었다.

**HB4(9행):** 관리 thread 최장 0.5~4.3ms, sealer 최장 3.4~4.4ms, writer 최장 6.4~13.1ms.

**LAT(10행, 최종 실행):** 모든 행에서 소비자 thread의 seal·등록 호출이 0회이고, 저장 = 제출이다.

| 행 | writer 최장 | writer p99 | sealer 최장 | 거부 | FIFO 최대 |
| --- | ---: | ---: | ---: | ---: | ---: |
| LAT-seal0-append0ms | 47.9ms | 8.5ms | 4.6ms | 0 | 0 |
| LAT-seal0.2-append0ms | 14.3ms | 8.2ms | 5.4ms | 0 | 0 |
| LAT-seal1-append0ms | 18.2ms | 7.5ms | 4.0ms | 0 | 1 |
| LAT-seal3-append0ms | 12.9ms | 7.8ms | 4.2ms | 0 | 3 |
| LAT-seal0-append5ms | 54.0ms | 19.6ms | 3.9ms | 0 | 0 |
| LAT-seal0.2-append5ms | 19.5ms | 18.1ms | 35.2ms | 0 | 0 |
| LAT-seal1-append5ms | 20.0ms | 18.1ms | 4.1ms | 0 | 0 |
| LAT-seal3-append5ms | 57.5ms | 18.3ms | 3.9ms | 0 | 2 |
| LAT2-two-tracks-seal0 | 11.2ms | 8.4ms | 5.6ms | 0 | 1 |
| LAT2-two-tracks-seal1 | 14.6ms | 8.0ms | 35.3ms | 0 | 4 |

**C00 결정 (2)·(3)의 재측정: 2트랙 거부**(별도 사본 `%TEMP%\recoryn-g15-measure2-8376c9a8…`)
- 스크립트: `…\scratchpad\g15_measure2.py`(LF `259f32b3…e3a6`)
- 결과: `measure2.jsonl` sha256 `57b88956053df711c329358597564b6ad036fb9b50d2cbbf0b499fd7d0a78af6`

| 측정 | 회차 | 거부 블록 |
| --- | ---: | --- |
| LAT2 2행(2트랙, 1초 청크, 6초) | 5회 × 2행 | 10/10행 0 |
| probe 5(2트랙, 2초 청크, 12초) | 3회 | 3/3회 0. writer 최장 4.6~11.7ms |
| IDX-UI 2트랙 행(최종 실행) | 2행 | 2/2행 0(그중 1행은 완료 삭제 1,000건) |
| PART1 참고(§13.3) | 3회 × 2행 | 0~57블록 |

- 판단:
  - 결정 (1) 뒤 이 PC에서는 2트랙 거부가 안정적으로 0이었다. 그래서 결정 (3)에 따라 LAT2 두 행의 거부 0을 assert로 올렸다. 조건은 append 지연 0이고 seal 지연 ≤1초인 행이며, 1트랙과 같다.
  - **뒤에 되돌렸다(§16.1):** CI 명령(전체 시험 + coverage 추적)에서 IDX-UI 2트랙 행이 3·81블록을 거부했다. 따라서 "안정적으로 0"이라는 승격 조건이 CI 조건에서 성립하지 않는다.
  - 결정 (2)의 재요청(append fsync를 mutex 밖으로)은 하지 않는다. 거부가 남지 않았기 때문이다.

**probe 3 재측정: append 한 번의 비용**(1,000블록)
- 파일: `…\g15probe\probe_append_cost.py`. `--settle` 옵션을 더했다(LF는 §15.5).
- settle 결과: `append_cost_settled.json` sha256 `f145d14f…ca34`

| 구간 | HEAD(§13.3) | PART2, journal 생성 직후(settle 전) | PART2, settle 뒤 |
| --- | ---: | ---: | ---: |
| append 전체 중앙값 | 1.822ms | 1.371ms | 1.178ms |
| `check_write_allowed` 중앙값 | 0.976ms | 0.558ms | 0.332ms |
| `check_write_allowed` p99 | 1.505ms | 0.996ms | 0.755ms |
| fsync 2회 중앙값 | 0.718ms | 0.689ms | 0.744ms |

- settle 뒤 `check_write_allowed` 0.28ms(직접 2,000회 중앙값)의 내역은 다음과 같다.
  - `_check_version` 0.088ms. 그 안의 `_db` 속성 경로 검사가 0.063ms다.
  - journal stamp 0.088ms. 대부분 `safe_path`다.
  - 자기 세션 PK 조회 0.076ms
- 더 줄이려면 journal 경로 캐시와 `_db` 이중 접근 제거로 약 0.15ms를 더 뺄 수 있다. 2트랙 거부가 0이라 이번에는 하지 않았다(후속 선택).

**probe 6: 디렉터리 mtime 해상도**(§14.4-1의 근거)
- 파일: `…\g15probe\probe_dir_mtime.py`, LF `b2a736f9353a30b78e828f1331209575ae56c76f4838074299f37b3541b02041`
- 출력은 터미널에서 확인했다. 결과 파일은 남기지 않았다.

| 위치 | 연속 생성 400회 중 직전과 같은 mtime | 변화 간격 최소 | 변화 간격 중앙값 | 제자리 다시 쓰기가 디렉터리 mtime을 바꿈 |
| --- | ---: | ---: | ---: | --- |
| OS TEMP | 167 | 0.503ms | 1.006ms | 아니오 |
| `D:\project` 아래 임시 폴더 | 304 | 0.504ms | 1.000ms | 아니오 |

- `D:` 측정은 저장소 밖 `D:\project` 아래에 임시 폴더를 만들었다가 지웠다. 저장소 파일은 건드리지 않았다. 그 뒤 측정은 모두 OS TEMP에서만 했다.

### 15.3 경로별 보유 상한과 CI 여유(C00 결정 (3))

- C00 근거: CI 러너는 이 PC보다 1.4~1.7배 느리다(GT-P04 50.2ms 사례).
- 아래 표의 "이 PC 최장"은 이번 최종 실행과 재측정 가운데 최댓값이다.

| 경로 | 상한 | 이 PC 최장 | ×1.7 | 여유(상한 ÷ 최장) |
| --- | ---: | ---: | ---: | ---: |
| append 전용 소비자(LAT·IDX-UI·HB) | 0.2초 | 57.5ms | 97.8ms | 3.5배 |
| sealer(LAT·IDX-UI·HB) | 50ms | 35.3ms | 60.0ms | **1.42배** |
| 관리(HB4) | 50ms | 4.3ms | 7.3ms | 11.6배 |
| GUI tick 대리(IDX-UI) | 50ms | 2.3ms | 3.9ms | 21.7배 |
| IDX-SCALE 각 동작 | 50ms | 19.9ms | 33.8ms | 2.5배 |
| REG | 50ms | 11.4ms | 19.4ms | 4.4배 |

- **sealer 상한의 여유가 부족하다.**
  - sealer는 10행 중 2행에서 35ms대였다. PART1에서도 37ms였다(§13.3).
  - sealer의 mutex 구간은 게시(stat·mkdir·rename·의도 검사)와 등록(insert + SQLite commit)이다. 긴 값은 commit의 fsync이거나, mutex를 쥔 채 GIL을 기다린 시간으로 본다. GT-P04의 50.2ms도 같은 종류의 commit fsync였다.
  - 따라서 1.7배 느린 러너에서는 50ms를 넘을 수 있다(오탐 위험).
- **나머지 경로는 여유가 있다.** append 전용 0.2초 상한도 1.7배 러너에서 약 2배 여유가 남는다.
- **결정 요청(sealer 상한):** 다음 중 하나를 정해 주세요. 바꾸기 전까지 승인대로 50ms를 유지한다.
  - (가) GT-P04처럼 sealer 판정 상한을 0.5초(`MANAGEMENT_HOLD_LIMIT_SECONDS`와 같은 값)로 둔다. 50ms 이상은 진단 기록으로 남긴다.
    - 보존하는 성질: 한 번의 보유가 녹음 큐(2트랙 공유 약 1.28초)를 넘치게 하지 않는다.
    - 구조 검사(소비자의 seal·등록 0회, mutex 밖 검증)는 그대로 assert한다.
    - 검출력: MU7(검증을 mutex 안으로) 변이의 sealer 보유는 §15.4에 적는다.
  - (나) 50ms를 유지하고, CI에서 넘으면 그때 재조정한다.

**C00 결정: (가) 채택.** 시험(`tests/integration/test_seal_mutex.py`)을 다음과 같이 바꿨다. 상한의 근거는 그 파일의 상수 주석에도 적었다.

| 상수 | 값 | 쓰는 판정 | 근거 |
| --- | ---: | --- | --- |
| `HOLD_LIMIT_SECONDS` | 0.5초 | sealer(HB4·LAT·IDX-UI), 관리(HB4), GUI tick(IDX-UI), catalog 동작(REG, IDX-SCALE) | 녹음 큐보다 작다: 2트랙 공유 약 1.28초의 2.5분의 1, 1트랙 2.56초의 5분의 1. 이 PC 최장 35.3ms에 CI 1.7배를 곱해도 60ms라 약 8배 여유다. 시간으로 판정되는 변이보다 작다: MU7은 주입한 1초·3초 이상, IX4는 1.07초(§15.4) |
| `APPEND_ONLY_BOUND` | 0.2초(유지) | append 전용 소비자(HB4·LAT·IDX-UI) | seal이 소비자로 돌아오면 0.4초 이상이다(§2.2). 이 PC 최장 57.5ms(fsync 5ms 주입 행)에 1.7배를 곱하면 98ms라 약 2배 여유다. 구조 판정(소비자의 seal·등록 0회)이 같이 잡는다 |
| `DIAGNOSTIC_SECONDS` | 50ms | 판정 없음 | 50ms 이상 보유를 MEASURE 행의 `long_holds`에 남긴다(GT-P04의 long_holds와 같은 방식) |

- 50ms가 판정에 쓰이던 곳은 모두 정리했다: HB4 2곳, LAT 1곳, REG 1곳, IDX-SCALE 1곳, IDX-UI 2곳. 단위 파일에는 시간 상한이 없다.
- 상한을 넓힌 대신, 시간으로만 잡던 회귀는 구조 판정이 잡는다(§14.4-11).
  - REG: 등록 중 descriptor decode 0회와 `verify_bundle` 0회. HEAD 방식(3,600청크에서 168ms)은 0.5초보다 짧아 시간으로는 놓친다.
  - IDX-SCALE: mutex 안 journal 파일 읽기 0회. IX4의 `get_session`(0.44초)도 0.5초보다 짧다.

### 15.4 mutation

방법:
- 사본: `%TEMP%\recoryn-g15-mut-1e3fa146bb7c4d649c0564d58ef2fa18`(HEAD + G-P15 6파일). sentinel exit 0으로 사본 import를 확인했다.
- 실행 중 HEAD가 `133b010`에서 `6072ef1`(G-P05b)로 바뀌어, 이 사본의 기준은 `6072ef1`이다. 두 commit 사이에는 G15 파일이나 `storage/`·`app/recording.py`의 차이가 없다(문서, `ui/main.py`, `tests/ui/test_pending_deletion_ui.py`만 다르다).
- 정상본: G15 2파일 132 passed. 모든 mutant 뒤 복원 hash가 정상본과 같았다.
- 실시간 행(LAT, IDX-UI, 약 2분)은 그 행을 겨냥한 mutant에서만 돌렸다. 나머지 mutant는 118 node를 실행했다.
- 보고서 sha256: `ef382cf3167f874c24b791bf0881d854ba00f1b7ff2e6188c7b3c3222561466a`

| mutant | 변이 | 실행 node | 실패 | 판정 | 실패 node |
| --- | --- | ---: | ---: | --- | --- |
| MU1 | 게시 단계의 삭제 재검사 제거 | 118 | 4 | 검출 | HB1·IDX-HB의 before-verify·after-verify |
| MU2 | 파일 닫는 순간 비활성(`_sealing` 무시) | 118 | 5 | 검출 | W SEALING 2행, HB3 3행 |
| MU3 | 준비 단계 검증 생략 | 118 | 8 | 검출 | 손상 staging 3행, HB6 3행, verify-once, C3 |
| MU5 | `_drain`이 sealer를 기다리지 않음 | 118 | 25 | 검출 | HB1~HB5 다수 |
| MU6 | `is_live`가 sealer를 보지 않음 | 118 | 0 | **동등**(§13.4와 같은 이유) | — |
| MU6b | sealer가 `hold()` 없이 seal | 118 | 3 | 검출 | HB3 before-register·before-release, IDX-IO4 |
| MU7 | 준비 단계 검증을 다시 mutex 안으로 | 19(LAT·HB4) | 16 | 검출 | LAT 10행, HB4 6행 |
| MU4 | 등록의 mutex 안 의도 재검사 제거 | 118 | 3 | 검출 | HB1 before-register, IDX-HB before-register·projection-failed |
| MU8 | 겹침 검사를 같은 트랙·epoch의 마지막 청크와만 | 118 | 3 | 검출 | 겹침 의도 행, REG n900·n3600 |
| IX1 | 게시가 색인에 세션을 넣지 않음(stamp는 갱신) | 118 | 0 | **동등**(§14.2의 (b)·(c)가 막음) | — |
| IX1b | IX1 + 게시 직후 settle 표시 | 118 | 1 | 검출 | IDX-HB projection-failed |
| IX2 | stamp·이름 비교 제거 | 118 | 5 | 검출 | IDX-FAIL get 5행(tmp·미인식·손상 추가, 의도 삭제, 디렉터리 제거) |
| IX3 | `_live`의 DB 행 합집합 제거 | 118 | 1 | 검출 | IDX-FAIL db_only-get |
| IX4 | 매 호출 전체 재검증(회귀) | 16(IDX-SCALE) | — | 900초 시간 초과. 다시 돌려 검출(아래) | — |
| IX5 | writer 경로가 모든 journal을 엶(HEAD 방식) | 9(IDX-IO·IDX-UI) | 6 | 검출 | IO1·IO2·IO3·IO4, IDX-UI n1000 2행 |
| CO1 | append가 등록된 콜백을 무시(매번 durable) | 118 | 1 | 검출 | append-open-library-index |

- 판정을 다룬 방식(숨기지 않음):
  - **MU8:** 스크립트의 목표 이름을 docstring의 ID(`G15-U-overlap-older-chunk`)로 적어, 자동 판정이 "아니오"로 나왔다. 실제 node(`test_overlap_with_an_older_chunk_of_the_same_track_and_epoch`)는 실패 목록에 있다. 목표 이름을 고쳐 다시 돌렸다(아래).
  - **MU6b:** 계획한 목표 HB1 before-register는 통과했다. G-P05의 `SESSION_LIVE`가 활성 writer 여부와 무관하게 삭제를 먼저 막기 때문이다(MU2와 같은 가림). HB3 2행과 IO4가 검출했다. 목표를 HB3 2행으로 바꿔 다시 돌렸다.
  - **IX5의 IO3:** 이 변이에서는 자기 세션 확인에 주입한 오류 대신 journal 전체 읽기가 먼저 실패해 오류 문구가 달라진다.
  - **MU6과 IX1:** 동등 mutant다. IX1이 살아남는 것은 설계대로다. 세 근거가 겹쳐 있어, 색인 갱신 하나가 빠져도 이름 목록과 DB 행이 막는다. IX1b가 그 겹침이 실제로 일함을 보인다.
**재실행(목표 이름 정정·선택 축소, HEAD `6072ef1`)**
- 사본: `%TEMP%\recoryn-g15-mut-a3df79000e2b4617ac0f5b08345bb1b4`. 정상본 132 passed, sentinel exit 0, 복원 hash 일치.
- 보고서 sha256: `1dd6f12e666bcaf74aa3ec1116105e69f764d1e51513032f3229f4ffe0e80473`

| mutant | 실행 node | 실패 | 판정 | 근거 |
| --- | ---: | ---: | --- | --- |
| MU6b | 118 | 3 | 검출(목표 HB3 2행 모두) | HB3 before-register·before-release, IDX-IO4 |
| MU8 | 118 | 3 | 검출(목표 3개 모두) | 겹침 의도 행, REG n900·n3600 |
| IX4 | 2(IDX-SCALE n1000의 `get_session`·`create_session`) | 2 | 검출 | root 보유 `create_session` 1.066초, `get_session` 0.440초(상한 50ms). 정상본은 같은 행에서 2~20ms |

- IX4의 첫 실행이 시간 초과였던 이유: 이 변이에서는 1,000개 tombstone 각각에 대한 거부 확인이 매번 journal 1,000개를 읽는다. 16행 전체는 900초를 넘었다. 두 행만 고른 재실행은 1,010초 걸렸다(스크립트 시간 제한 1,800초).

- (가) 제안(sealer 상한 0.5초)에서의 MU7: LAT seal1·seal3 행은 1초·3초 지연이 mutex 안으로 들어가므로 0.5초를 넘는다. HB4는 보유 시간이 아니라 "관리가 seal을 기다렸는가"로 판정한다. 따라서 (가)에서도 MU7은 검출된다.

### 15.5 제출 파일과 sha256(LF)

| 파일 | 변경 | sha256(LF) |
| --- | --- | --- |
| `src/recoryn/storage/library.py` | PART2 | `4dd035d128f388acb805ac9eea9faceb6ca5be660e58734cebdeb77180dd0136` |
| `src/recoryn/storage/_coordination.py` | PART2 | `46d76a8f86ef7438a12dea7f5a201d87244b1c89e37707878c47a8e23eabb8c9` |
| `src/recoryn/storage/chunks.py` | PART1 + `issued_descriptor` | `618a0e2a12c2ec1cbacc36fa7f3bb3370663258249ae27689ee2ca83ce63f34f` |
| `src/recoryn/app/recording.py` | PART1 + capability 등록 1줄 | `1b6ee4fd4edacd5750393bf7b07e8c96a28ef1137758ef61ebd58174007e1ea4` |
| `tests/unit/test_seal_phases.py`(신규) | 45 node | `362400d001043230450c55ea225b966a4d148f35d92f3f65c55bc306428becb4` |
| `tests/integration/test_seal_mutex.py`(신규) | 98 node | `d24566a7573d8004fe02b0cd7bf1afdd606dcc43988a24661954efb7ee5dd7ad` |

도구와 probe(scratchpad, 저장소 밖):

| 파일 | sha256(LF) |
| --- | --- |
| `g15_copy.py`(격리 사본 실행) | `de78b044c62865a822a098c767b1428898f7b87b828266247491a45a09c7bd30` |
| `g15_mutation.py`(첫 실행 판) | `96f29e159e319724f226e80b30b4b8ac8ed9a2aa6aee30c015a517af93450aed` |
| `g15_measure2.py` | `259f32b330608b0da75300df7e6482901be1b89b3d05a2579c9c9a9a8b68e3a6` |
| `g15probe/probe_append_cost.py`(`--settle` 추가 판) | `38497bf571262bed8cdfc11be2ab602fcc24da53e3278a18f5483c71e8f8bf7e` |
| `g15probe/probe_two_tracks.py` | `b144ae629ff38e75abb2cac2d8e0a06e5506c96735b10a5de2c7b7209015348a` |
| `g15probe/probe_dir_mtime.py` | `b2a736f9353a30b78e828f1331209575ae56c76f4838074299f37b3541b02041` |
| `g15_mutation.py`(재실행 판) | `597b41df273aff57066b4d2f4f2395983de6f39e8f4292bbe8305965c7f93601` |
| `g15_ci.py`(CI 동등 실행) | `8d3f8ccafc11fce895a095e77a2d8ab030e7d699bcb40207c480221984735065` |

- `g15_mutation.py`의 재실행 판은 첫 실행 판에 목표 이름 정정, IX4 선택 축소, `-s`와 측정 수집, 시간 제한 1,800초를 더한 것이다.
- mutation은 FC 11행을 더하기 전 시험으로 돌렸다. 시험을 더하는 것은 검출을 줄이지 않으므로 §15.4의 판정은 그대로다.
- 이 문서 자체의 hash는 자기 참조를 피하려고 IMPLEMENTATION_READY 보고에 적는다.

### 15.6 CI 동등 실행(정적 검사·전체 시험·coverage 예산)

- C00 요청(G-P06 되돌림 뒤): CI와 같은 명령으로 전 묶음 PASS를 확인한다.
- 방법:
  - `g15_ci.py`가 `git archive 6072ef1` + G-P15 6파일만 덮어쓴 사본에서 `.github/workflows/core.yml`의 core job 단계를 같은 순서·같은 옵션으로 돌린다.
  - 더한 것은 OS TEMP 아래 고유 `--basetemp` 하나다.
  - 사본에는 sentinel 모듈을 넣지 않았다. 그래서 coverage 분모는 HEAD의 `src`와 덮어쓴 파일뿐이다.
  - G15 시험은 원문 코드를 tmp에 써서 `recoryn.*`로 싣지 않는다. CRASH 자식 프로세스는 `PYTHONPATH`로 사본의 실제 `src`를 import한다.
- 사본: `%TEMP%\recoryn-g15-ci-a3145328fe5e48919cfb1f6626bb57cd`

| 단계 | 명령(CI와 같음) | 결과 |
| --- | --- | --- |
| Lint | `ruff check src tests scripts packaging` | 통과 |
| Formatting | `ruff format --check src tests scripts packaging` | 164파일 통과 |
| Types | `MYPYPATH=src mypy src/recoryn scripts packaging` | 84파일 이상 없음 |
| 시험 | `pytest -q -p no:cacheprovider -W error::ResourceWarning --cov=recoryn --cov-branch --cov-report=term-missing --cov-report=json:coverage.json --cov-fail-under=85` | **10085 passed**(1066.72s), 전체 coverage 92.29% |
| 예산 | `python scripts/check_coverage.py coverage.json` | **전 묶음 PASS**(아래) |

| 묶음 | line(예산) | branch(예산) | 판정 |
| --- | --- | --- | --- |
| domain | 100.00%(95) | 100.00%(90) | PASS |
| capture | 99.85%(95) | 98.57%(90) | PASS |
| jobs | 98.89%(95) | 97.47%(90) | PASS |
| **storage** | **96.54%(95)** | **92.16%(90)** | PASS |
| security | 98.09%(95) | 93.95%(90) | PASS |
| content | 99.59%(95) | 98.75%(90) | PASS |
| all | 93.74%(85) | 87.77%(80) | PASS |

- `coverage.json` sha256: `cb6857e19b9873dd2b0cae6c3cd63c79dcbe36c8c7bc6a6f02ba792d66d9a166`
- 단계 로그 sha256: tests `110fba8f…67be`, 예산 `e0254357…908c`
- **storage 묶음의 경과(숨기지 않음):**
  - FC 11행 전 같은 실행(사본 `recoryn-g15-ci-eaf4cfc8…`, 10074 passed)에서 storage는 line 95.66%, branch 90.30%였다. 모두 PASS지만, C00이 알려 준 직전 값(96.30·91.56)보다 여유가 줄었다.
  - 원인은 PART2 새 코드의 fail closed 분기였다(library.py 12줄·9분기, chunks.py PART1 2줄·2분기).
  - FC 11행(§14.4-7)으로 그 줄을 모두 덮어 96.54·92.16이 됐다. 새 코드에 남은 미검사 분기는 `finalize_unfinished`의 admission 뒤 재확인 1개(1259→1260)다. admission이 같은 조건을 먼저 거부하므로, 경쟁 없이는 도달하지 않는다.
- security 묶음 값은 G-P06이 되돌려진 HEAD 기준이다.

### 15.7 미해결 위험과 확인 요청

1. **sealer 보유 상한(해결):** C00이 (가)를 채택했다. 판정 상한은 0.5초이고, 50ms 이상은 진단 기록이다(§15.3).
2. **§11.6 의미 차이(수용):** C00이 수용했다. 근거와 남는 한계는 §11.6에 있다.
   - 기존 의도 파일의 제자리 내용 손상과 다른 세션 DB 행의 손상은 `_live`와 writer 경로가 감지하지 않는다.
   - 관리 경로는 계속 감지한다.
3. **단일 writer 계약 밖의 약화(미검증 한계로 유지)**(§14.3):
   - 시계 가정이 깨지는 볼륨에서는 같은 tick의 외부 변경을 놓칠 수 있다.
   - 대안 A3(주기적 전체 검증)·A4(그런 볼륨에서 settle 끄기 또는 거부)는 구현하지 않았다.
   - settle 규칙(2.5초)의 근거는 이 PC의 NTFS 측정뿐이다. FAT·exFAT·네트워크 볼륨은 미검증이다(C00 결정 (3)).
4. **동등 mutant 2종(MU6, IX1):** 방어 중복이라 살아남는다. 근거는 §13.4·§14.2다.
5. **검증하지 않은 것:** 실장비 캡처, CI 러너에서의 G15 시간 측정, 전원 장애 내구성(I5는 fsync 순서·횟수 유지만 주장), 3,600청크를 넘는 세션, 완료 삭제 1,000건을 넘는 라이브러리
6. **후속 선택(성능):** append 판정에서 journal 경로 캐시와 `_db` 이중 접근 제거로 약 0.15ms를 더 줄일 수 있다(§15.2). 이 PC에서는 2트랙 거부가 0이라 이번에는 하지 않았다. CI 조건의 2트랙 여유는 §16.1에 있다.
7. **작업 과정 고지:** probe 6의 `D:` 측정이 저장소 밖 `D:\project` 아래에 임시 폴더를 만들고 지웠다(§15.2). 저장소와 다른 작업자 파일은 건드리지 않았다.

## 16. FINAL_READY 반영과 검증(HEAD `68fbbda`)

- 기준: HEAD `68fbbda`(G-P06 push). `6072ef1..68fbbda`는 G15 파일과 `storage/`·`app/recording.py`를 바꾸지 않는다.
- 모든 실행은 `git archive 68fbbda` + G-P15 7파일(코드 4, 시험 2, 이 문서)만 덮어쓴 격리 사본에서 했다. 이 문서는 시험이 읽지 않는다. 사본에 들어간 문서는 실행 시점의 판이다.

### 16.1 바꾼 것

1. **시간 상한(C00 결정 (가))**과 **구조 판정:** §15.3과 §14.4-11에 적었다. 분모는 그대로다(141 + 대조 2).
2. **2트랙 거부 assert를 측정으로 되돌림(C00 결정 (3)의 조건):**
   - 경과: 첫 CI 동등 실행(사본 `%TEMP%\recoryn-g15-ci-3d1d996cee294f0287610a76b52cc67b`, 15172 node)에서 2 failed였다. 두 행 모두 보유는 짧았고(`long_holds` 없음), 거부만 났다.

     | 행 | 거부 | 저장 프레임 | writer 최장 | sealer 최장 |
     | --- | ---: | ---: | ---: | ---: |
     | `G15-IDX-UI-n0-tracks2` | 3 | 1,150,560 | 33.7ms | 27.2ms |
     | `G15-IDX-UI-n1000-tracks2` | 81 | 1,113,120 | 23.4ms | 5.2ms |

   - 해석:
     - coverage 줄 추적 아래에서는 소비자의 append당 비용이 커진다. 그래서 초당 200 append(2트랙)의 여유가 없다.
     - n1000 행은 tombstone 파일을 녹음 직전에 만들었다. 그래서 처음 2.5초 동안 append마다 이름 목록(1,000항목)을 비교한다(settle 전). 시험 fixture가 만든 조건이지만, 실제로도 삭제 직후 2.5초 동안 같은 비용이 든다.
     - 같은 사본·같은 명령의 앞선 두 실행(`6072ef1`)에서는 이 행들이 통과했다. coverage 없는 실행에서는 모든 회차가 0이었다.
   - 결정 (3)은 "안정적으로 0이면 assert"였다. CI 조건에서 그 조건이 깨졌으므로 2트랙(LAT2 2행, IDX-UI 2행)의 거부를 다시 측정값으로 돌렸다.
   - 유지하는 assert:
     - 1트랙 행의 거부 0. coverage 실행을 포함해 모든 회차에서 0이었다.
     - 모든 행의 보존 조건: 저장 프레임 = (제출 블록 − 거부 블록) × 480
     - 보유 상한, 구조 판정
   - 2트랙 처리량을 CI 조건에서도 0으로 만들려면 소비자 비용을 더 줄여야 한다. 후보는 §16.4에 있다.

### 16.2 mutation(새 상한, HEAD `68fbbda`)

- 사본: `%TEMP%\recoryn-g15-mut-b67b861b4aac46309fbc6392060b741a`. 정상본 143 passed, sentinel exit 0, 복원 hash 일치.
- 보고서 sha256: `1ebf23bb17da84ee24fa554a7e235e154f04834c2d72f5fecf13090b1a44b7b1`
- 이 mutation은 2트랙 되돌림 전 시험판(LF `676f57aa…8b72`)으로 돌렸다. 되돌림은 2트랙 거부 assert만 측정으로 바꾼다. 아래 mutant의 검출 node는 어느 것도 2트랙 거부 assert에 기대지 않는다.

| mutant | 실행 node | 실패 | 판정 | 근거(측정) |
| --- | ---: | ---: | --- | --- |
| MU7(검증을 mutex 안으로) | 19(LAT·HB4) | 11 | 검출 | HB4 6행(관리가 seal을 기다림, 구조). LAT seal1·seal3 4행과 LAT2-seal1의 sealer 보유 1.17~3.20초 > 0.5초 |
| IX4(매 호출 전체 재검증) | 16(IDX-SCALE) | 6 | 검출 | mutex 안 journal 읽기 100~2,000회(구조, n100부터). n1000 보유 `create_session` 1.054초·`get_session` 0.518초 |
| RG1(겹침 검사를 HEAD의 Python 반복으로) | 29(REG 포함) | 2 | 검출 | REG n900·n3600의 descriptor decode 900·3,600회(구조). 보유 37ms·152ms는 0.5초보다 짧다. 시간 판정만으로는 놓치는 회귀다 |
| MU8(겹침 검사를 마지막 청크와만) | 129 | 3 | 검출 | 겹침 의도 행, REG n900·n3600 |

- **MU7 자동 판정이 "아니오"인 이유:**
  - 미리 정한 목표 중 LAT seal0.2-append0ms 행은 sealer 보유 0.366초로 새 상한 0.5초 아래다. (가)를 고를 때 예상한 결과다(§15.4 끝).
  - 그 대신 seal1·seal3 행과 HB4가 검출한다. 목표 선정의 문제이고 검출력의 문제는 아니다.
- 합계(정정): 첫 실행은 **16종**이었다(§15.4 표의 행 수). 앞선 보고의 "17종 중 15종"은 잘못 센 것이다. RG1을 더해 지금은 17종이다.
  - 검출 15종: MU1~MU5, MU6b, MU7, MU8, IX1b, IX2~IX5, CO1, RG1
  - 동등 2종: MU6, IX1

### 16.3 시험·회귀·CI 동등 실행

| 실행 | 시험판 | 결과 |
| --- | --- | --- |
| 관련 회귀(§15.1 목록) | 2트랙 되돌림 전(`676f57aa…`) | **1547 passed**(678.65s), 실패 0. 사본 `%TEMP%\recoryn-g15-g15final-f78bc9a87d7d4672b6fee2d8e17bc6bf`, JUnit `02a44b34…c452` |
| CI 동등 1회차 | 되돌림 전 | 15172 node 중 2 failed(§16.1). 예산은 전 묶음 PASS(storage 96.54·92.16) |
| G15 2파일(최종판, `-s`로 측정 수집) | 최종 | **143 passed**(268.76s). 사본 `%TEMP%\recoryn-g15-g15final2-d4af038b9e774b06851b21338edb6f71`, JUnit `6c6d0bb90b7a87b266f5918599e12ed635048020a4d11885c48ec81cceccb2ea`, 로그 `5d3d0de9e5709a35b10bad040f88d929df6393ea5c1ea79f5cb4ed26334c6923`. 2트랙 4행 모두 거부 0. 모든 MEASURE 행의 `long_holds`가 비었다(50ms 이상 보유 0) |
| CI 동등 2회차(최종판) | 최종 | 아래 표 |

CI 동등 2회차(사본 `%TEMP%\recoryn-g15-ci-d8f15f43aafb4ef0bfd1e215a15dadd5`, `g15_ci.py`)의 결과:

| 단계 | 결과 |
| --- | --- |
| Lint / Formatting / Types | 통과 / 170파일 통과 / 86파일 이상 없음 |
| 시험(CI 명령, coverage 포함) | **15174 passed**(1193.18s), 실패 0, 전체 coverage 92.57% |
| 예산 `check_coverage.py` | **전 묶음 PASS** |

| 묶음 | line(예산) | branch(예산) |
| --- | --- | --- |
| domain | 100.00%(95) | 100.00%(90) |
| capture | 99.85%(95) | 98.57%(90) |
| jobs | 98.89%(95) | 97.47%(90) |
| **storage** | **96.54%(95)** | **92.16%(90)** |
| security | 98.11%(95) | 94.43%(90) |
| content | 99.59%(95) | 98.75%(90) |
| all | 93.98%(85) | 88.29%(80) |

- `coverage.json` sha256 `7317bd69fdd2ba1641ee69b1d6a9d826b7f129993faa6c5a80fbfe1e4a15426b`. 시험 단계 로그 `6c161251…abfa2`, 예산 로그 `29032836…aa01`.

### 16.4 남은 위험과 후속 후보

1. **CI 조건의 2트랙 처리량:** 거부를 측정으로 되돌렸다(§16.1). 후보는 다음과 같다(C00 결정 대상).
   - (a) append 판정 경로 비용 축소: journal 경로 캐시, `_db` 이중 접근 제거. 약 0.15ms 절감(§15.2)
   - (b) settle 창을 파일 시스템 해상도에 맞춤: 미세 mtime이면 약 0.1초, 짝수 초 mtime이면 2.5초. 삭제 직후의 이름 목록 비용 구간이 줄어든다.
   - (c) 결정 4(append fsync를 mutex 밖으로) 재검토
2. **§11.6 수용 범위의 한계**(외부 도구가 journal을 직접 바꾸는 경우): §11.6에 남겼다.
3. **미검증:**
   - settle 규칙의 FAT·exFAT·네트워크 볼륨
   - CI 러너에서의 G15 시간 측정
   - 실장비 캡처
   - 전원 장애 내구성
   - 3,600청크 또는 완료 삭제 1,000건을 넘는 규모

### 16.5 최종 제출 파일과 sha256(LF)

| 파일 | sha256(LF) |
| --- | --- |
| `src/recoryn/storage/library.py` | `4dd035d128f388acb805ac9eea9faceb6ca5be660e58734cebdeb77180dd0136` |
| `src/recoryn/storage/_coordination.py` | `46d76a8f86ef7438a12dea7f5a201d87244b1c89e37707878c47a8e23eabb8c9` |
| `src/recoryn/storage/chunks.py` | `618a0e2a12c2ec1cbacc36fa7f3bb3370663258249ae27689ee2ca83ce63f34f` |
| `src/recoryn/app/recording.py` | `1b6ee4fd4edacd5750393bf7b07e8c96a28ef1137758ef61ebd58174007e1ea4` |
| `tests/unit/test_seal_phases.py`(45 node) | `362400d001043230450c55ea225b966a4d148f35d92f3f65c55bc306428becb4` |
| `tests/integration/test_seal_mutex.py`(98 node) | `23af1e55ad509403aafb8b2bfd69c3ff5c3af05d1fc91245f31e1c8c0ef7cae9` |

- 코드 4파일과 시험 2파일은 §16.3의 최종 두 실행에 덮어쓴 hash와 같다.
- 이 문서의 hash는 FINAL_READY 보고에 적는다. 사본에 들어간 문서는 그보다 앞선 판이다. 시험은 문서를 읽지 않는다.
- 도구의 최종판(scratchpad, 저장소 밖, 7파일 덮어쓰기):

  | 파일 | sha256(LF) |
  | --- | --- |
  | `g15_mutation.py`(RG1 추가) | `b564bb5bfb7b895a1395b3cdfe5426d9acfc31289fece15f917e64ca1e4e38dc` |
  | `g15_ci.py` | `f83c2c08850f6bdb98fffb931d1e9ce80a0a7157b1a178e558b2f9b5fb2375ff` |
  | `g15_copy.py` | `8d0aec029dd57b86885a0b78d911ba4f8b6f68ea8adc4f839eaf6ba39912f016` |

## 17. G-P15b: 독립 검토 S3 4건과 main CI 실패 반영(기준 HEAD `90c6123`)

- 입력은 세 가지다.
  - G-P15 push `90c6123`
  - 독립 검토 `docs/reviews/g15-seal-mutex-review.md`(LF `4f7bf3f9…6a87`): S0·S1·S2 0, S3 4(G15R-01~04)
  - main CI run 45234308753: core 3.11·3.13 실패, optional-runtime 성공
- C00 배정 범위는 `storage/chunks.py`, `app/recording.py`, 신규 시험 2파일, 이 문서다.
  - `storage/library.py`는 G-P07이 수정 중이어서 건드리지 않았다.
  - 격리 사본은 `library.py`·`_coordination.py`를 HEAD에서 가져오고, G-P15b 5파일만 덮어쓴다(`g15_copy.py` 등의 목록을 그렇게 바꿨다).
- C00 결정에 따라 CI 실패에 대해서는 제품 코드를 바꾸지 않았다. append fsync의 처리량 한계는 후속 G-P17(내구성 단위 재검토)로 넘어간다.

### 17.1 검토 발견의 수정

| 발견 | 원인 | 수정 | 고정 시험 | 검출 변이 |
| --- | --- | --- | --- | --- |
| G15R-01 | `SealedChunk.descriptor`가 쓰기 가능한 공개 속성이었다. `issued_descriptor`는 그 값을 그대로 돌려줬다. 그래서 descriptor를 바꾼 capability가 손상된 고아 묶음을 검증 없이 등록시켰다 | `chunks.py`. ① descriptor를 읽기 전용 property로 바꿨다(slot `_descriptor`). ② 발급할 때 writer가 봉인한 descriptor를 `_sealed`에 기록한다. `_capability`와 같은 `_writers_lock` 구간에서 한다. ③ `_bound`가 `candidate._descriptor is writer._sealed`를 요구한다. ④ `issued_descriptor`는 호출자가 넣은 값이 아니라 `writer._sealed`를 돌려준다. root 조건은 그대로다. `library.py`는 바뀌지 않는다. 바뀐 capability는 None을 받아 기존 전체 검증 경로(`verify_bundle`)로 간다 | 단위 BINDING 3행: 읽기 전용, `object.__setattr__`로 우회한 바꿔치기 → ValidationError·catalog 0, 다른 root의 같은 상대 경로에 둔 손상 사본 → ValidationError·catalog 0 | R5(root 조건 제거), B1(결속 제거 + 호출자 값 반환 = 원래 결함) |
| G15R-02 | 소비자 thread 시작이 실패하면 이미 시작한 sealer가 `_STOP`을 받지 못해 남았다. 세션은 live로 고착되고 프로세스 종료가 멈췄다 | `recording.py`. 두 시작을 한 `try`에 넣었다. 실패하면 살아 있는 sealer에 `_STOP`을 넣고 join한다. 캡처 큐를 닫고 두 thread 핸들을 None으로 둔다 | 통합 START 2행(소비자·sealer 시작 실패). RuntimeError, `recoryn-*` thread 0, `is_live()` 거짓, `join_writer` 무동작, 복구 `CREATED`, 삭제 `DELETED_LOCAL`(HEAD `0d846d6`와 같음) | S1(정리 제거): 두 행 실패. 그 뒤 남은 non-daemon sealer 때문에 pytest 프로세스가 끝나지 않아 1,800초 시간 초과로 종료됐다(G15R-02 증상 그대로) |
| G15R-03 | sealer 오류 경로의 계약 oracle(HB6의 staging 보존·검증된 prefix만 복구, §3.4의 FIFO 잔여 writer abort)이 시험에 없었다 | 제품 변경 없음. 동작은 검토자 probe대로 맞았다 | ① HB6R: 둘째 청크 블록 5의 바이트를 검증 직전에 뒤집는다. 실행 중 catalog [(0,2)], 게시 1, staging 1, INTERRUPTED. 복구 뒤 [(0,2),(3,4)], `STAGING_TAIL_NOT_ADOPTED`, 재복구 0, 채택 바이트 = 블록 3·4. ② FIFO-abort: 청크 1이 준비 전에 멈췄다가 실패한다. 그동안 청크 2~4는 FIFO(qsize 3)에, 블록 12~13은 열린 writer에 있다. 실패 뒤 INTERRUPTED, 게시·catalog 0, writer 5개 모두 비활성, staging 5개 보존. 복구 프레임 = append 14블록×4 = 56, 바이트 일치, 재복구 0 | R10(FIFO writer abort 제거) |
| G15R-04 | capture 경로 이름 목록 캐시의 settle 조건을 고정하는 시험이 없었다 | 제품 변경 없음 | 단위 FC 1행: 외부 `ext.json`이 생기면 settle 전 stamp에서 이름 목록을 한 번 만든다. 그다음 자기 세션 의도 파일을 같은 tick에 둔다(디렉터리 mtime 복원). 그러면 다음 append가 거부된다 | R16(`library.py`의 `cached[3]` 조건 제거, 사본에서만) |

### 17.2 main CI 실패와 판정 정정(C00 결정)

- **실패:** `test_injected_latency_keeps_the_root_mutex_short`의 714행 `assert measurement["writer_root_max_s"] < APPEND_ONLY_BOUND`(0.2초)다.
  - 3.13: seal3-append0ms 0.26, seal0-append5ms 0.59, seal0.2-append5ms 1.04, seal1-append5ms 0.69, seal3-append5ms 0.23, LAT2-two-tracks-seal0 0.50초
  - 3.11: seal3-append5ms 0.81초
  - 예를 들어 seal0.2-append5ms 1트랙은 writer p99 0.79초, sealer 최장 0.14초, 거부 46블록이었다. 소비자의 seal·등록 호출은 0이었다.
- **원인:** CI 디스크에서는 소비자 append의 mutex 안 fsync(블록당 2회, C00 결정 4)만으로 보유가 0.2~1초가 된다. 그래서 1트랙도 거부가 난다. seal을 소비자 밖으로 옮긴 G-P15의 성질(소비자 seal·등록 0, sealer 보유 짧음)은 CI에서도 성립했다.
- **정정:**
  - LAT·LAT2·HB4·IDX-UI·IDX-IO에서 소비자(append) 보유와 거부 수를 측정값으로만 기록한다. `APPEND_ONLY_BOUND`와 1트랙 거부 0 assert는 없앴다. IDX-IO의 "거부 0" 판정도 같은 원칙으로 측정값이 됐다. 이 행의 목적은 "녹음이 멈추지 않음(`storage_failed` 거짓)"이고, 그 판정은 남는다.
  - 판정은 다음으로 한다.
    - **구조:** 소비자 thread의 seal·등록·검증(`_verified`)·decode(`ChunkDescriptor.from_dict`) 호출 0, 어느 thread든 root mutex를 쥔 채 deletion journal 파일 읽기 0, seal·등록은 sealer가 했다(LAT에서 seal 수 = 등록 수 ≥ 1)
    - **sealer 보유:** 0.5초 상한(`HOLD_LIMIT_SECONDS`)
    - **보존:** `assert_conserved`. 지속 capture health의 트랙별 수락 + 탈락 = 제출, 탈락 = 거부 블록, 모든 gap은 `QUEUE_DROP`이고 그 프레임 합 = 탈락, 저장 프레임 = 수락 프레임 합
  - 관리·GUI tick·catalog 경로의 0.5초 상한과 HB·IDX의 결과 판정은 그대로다.
- **이 PC의 근거(주입 지연 없는 행, 측정 기록으로 남김):**
  - §15.2와 재측정에서 1트랙은 모든 회차가 거부 0이었다. LAT seal0-append0ms, IDX-UI 1트랙 n0·n1000, IDX-IO 4행이다.
  - 2트랙도 이 PC 단독 실행에서는 0이었다. LAT2 10/10행, 12초 probe 3/3회, IDX-UI 2트랙이다.
  - 소비자 최장 보유는 지연 없는 행에서 6~48ms였다. 이것은 CI 디스크에서의 보장이 아니다.

### 17.3 관찰 두 가지에 대한 판단

1. **외부 손상으로 색인이 무효일 때 GUI tick의 root 보유 0.50~0.60초**(검토 §5)
   - 원인: 미인식 항목 등으로 `_read_journal`이 실패하면 색인은 None으로 남는다. 그러면 `_live`(GUI tick의 `chunks()`)가 호출마다 `_refresh_intent_index`로 journal 전체를 root mutex 아래에서 다시 검증한다. 계약 §11.2의 fail closed 동작이다.
   - 판단: 이번에는 고치지 않는다(`library.py`는 G-P07 작업 중). 영향은 외부 손상이 있는 열화 상태에 한정되고, 녹음은 계속된다(capture 경로는 이름만 본다, 검토 §5 거부 0). G15 시험은 이 상태의 보유를 판정하지 않는다. IDX-FAIL은 결과만 본다.
   - 후속 제안(C00 결정):
     - (가) **실패 결과 음성 캐시(권고):** settle된 stamp에서 전체 검증이 실패하면, 같은 stamp 동안 재검증 없이 곧바로 `DELETION_HISTORY_UNAVAILABLE`로 답한다(stat 1회, fail closed 유지). 항목이 추가·삭제되어 stamp가 바뀌거나 다시 열면 재검증한다. 한계는 제자리 내용 수정으로 손상을 고친 경우다. 다시 열기 전까지 실패가 이어지지만 fail closed 쪽이다.
     - (나) 전체 재검증을 G-P05 선읽기처럼 mutex 밖으로 옮긴다. `_live` 호출자가 mutex를 쥔 채 부르므로 구조 변경이 크다.
     - (다) UI tick 백오프: 이력 확인 불가를 본 tick이 다음 `chunks()` 호출을 늦춘다. `ui/main.py`는 G-P07 소유다.
2. **GC-P02 구조 판정과 `_live`의 journal 이름 목록**
   - 사실: GC-P02(`tests/integration/test_pending_deletion_restart.py`)는 관리 thread가 root mutex를 쥔 동안 `Path.iterdir`·`os.scandir`·`os.listdir`·`remove_tree` 호출 0을 판정한다.
   - G15의 `_index_current`는 settle 전 stamp에서 `os.scandir`로 journal 이름 목록을 mutex 안에서 만든다(`_live`, `_publish_intent`, capture 경로). 지금 GC-P02의 관리 동작은 선읽기만 써서 충돌하지 않는다(`90c6123` 정확한 tree 15178 PASS).
   - 위험: 앞으로 `_live`를 거치는 관리 경로를 같은 판정에 넣거나, journal이 바뀐 직후(settle 전) 관리 thread가 `_live`를 부르면 판정이 실패한다. 실패는 거짓 양성이다. 열거는 이름만이고 항목을 열지 않으며, 1,000항목에 약 0.74ms다.
   - 선택지(C00 결정):
     - (가) 판정 규칙에 "journal 이름 목록 1회(항목 열지 않음)"를 예외로 둔다.
     - (나) 이름 목록을 mutex 밖에서 만들고, mutex 안에서는 stamp만 대조한다. 외부 변경에 대한 보장은 지금과 같다. settle 전에는 다음 질의가 다시 목록을 본다. in-process 게시와 경쟁하면 이름이 달라 재검증 쪽으로 떨어진다. `library.py` 변경이므로 G-P07 뒤 별도 단위다.
     - (다) 판정 범위를 넓힐 때 함께 정한다.
     - 권고는 (나)를 후속으로 두되, 그전까지 (가)를 적용하는 것이다.

### 17.4 분모와 mutation

- 분모는 141에서 **149**가 됐다.
  - 단위 +4: BINDING 3, FC 11→12
  - 통합 +4: START 2, HB6R 1, FIFO-abort 1
  - 대조 node 2개를 더한 시험 node는 **151**이다(단위 49, 통합 102).
  - 판정 정정은 행을 줄이거나 늘리지 않았다.
- mutation(사본 `%TEMP%\recoryn-g15-mut-dc4d6135d9524399844608c7109658cb`, HEAD `90c6123` + G-P15b 5파일, `library.py`는 HEAD판, 보고서 `bb3454d0…fed8`):
  - 정상본 151 passed, sentinel 0, 복원 hash 일치
  - 이 사본은 §17.2 판정 정정 전의 시험판이다. 아래 검출 node는 정정과 무관하다.

| 변이 | 대상 | 결과 | 잡은 node |
| --- | --- | --- | --- |
| R5(검토자) | `issued_descriptor`의 root 조건 제거 | 검출 | `G15-U-reg-other-root-verifies` |
| B1 | 결속 제거 + 호출자 descriptor 반환(원래 G15R-01) | 검출 | `G15-U-reg-swapped-descriptor-verifies` |
| R10(검토자) | 실패 뒤 FIFO writer abort 제거 | 검출 | `test_sealer_failure_aborts_every_queued_writer_and_loses_no_appended_block` |
| S1 | 시작 실패 정리 제거(원래 G15R-02) | 검출(JUnit: START 2행 실패 `assert ['recoryn-sealer-s'] == []`). 남은 sealer 때문에 프로세스가 끝나지 않아 스크립트는 TIMEOUT으로 기록했다 | START 2행 |
| R16(검토자) | capture 이름 목록 캐시가 settle 전 목록 재사용 | 검출 | `G15-U-fc-unsettled-listing-not-reused` |

### 17.5 실행 결과

- 모든 실행은 `git archive 90c6123` + G-P15b 5파일 사본에서 했다.
  - 하위 프로세스(CRASH 자식)를 포함해 `PYTHONPATH`를 사본 `src`로 고정했다. `.venv`의 editable 설치가 작업 트리 src를 불러오지 않도록 하기 위해서다.
  - `library.py`·`_coordination.py`는 HEAD판이다.

| 실행 | 결과 |
| --- | --- |
| G15 2파일(`-s`, 측정 수집) | **151 passed**(270.87s). 사본 `%TEMP%\recoryn-g15-g15b-46b3ebc7bb094136bd3ae44afa76c19a`, JUnit `c7fc990e…a8dcf`, 로그 `1c8d3565…d024`. 주입 지연 없는 행은 모두 거부 0이었다: LAT 1트랙·2트랙, IDX-UI 4행, IDX-IO 3행 |
| 느린 디스크 흉내(`g15_slowdisk.py`, plugin `g15_slow_sync.py`가 모든 `chunks.sync` 앞에 지연) | 아래 표. **모든 행 통과**. 결과 `slowdisk.jsonl` sha256 `d342e2dafff9f602b63e750cdab438c2018673d54f773f08123275a2af0608ab`, 사본 `%TEMP%\recoryn-g15-slowdisk-a389f659622a46efb87c475782a49b87` |

| sync 지연 | 실행 행 | 통과 | 소비자 최장 보유 | sealer 최장 | 관리 최장(HB4) | GUI tick 최장 | 거부 블록 | 소비자 seal·등록·검증·decode / mutex 안 journal 읽기 |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 50ms | LAT 10, HB4 9, IDX-UI 4 | 23/23 | 0.109~0.151초 | 3.5~36.2ms | 0.5~3.1ms | 1.7~2.7ms | 285~2,030 | 모두 0 / 0 |
| 100ms | LAT 10, HB4 9 | 19/19 | 0.210~0.221초 | 3.1~5.5ms | 0.6~4.0ms | — | 314~914 | 모두 0 / 0 |
| 200ms | LAT seal0-append0ms, LAT2-seal0, HB4-inventory 3 | 5/5 | 0.410~0.421초 | 3.2~5.3ms | 0.5~0.6ms | — | 329~929 | 모두 0 / 0 |

- 해석:
  - 소비자의 보유는 지연의 약 2배(append당 fsync 2회)로 디스크를 그대로 따른다. CI의 0.23~1.04초와 같은 종류이며, 거부도 그만큼 난다.
  - 그래도 새 판정은 흔들리지 않았다.
    - 구조: 소비자는 seal·등록·검증·decode를 하지 않는다.
    - sealer·관리·tick 보유는 짧다.
    - 보존: 모든 탈락이 QUEUE_DROP gap으로 기록되고, 저장 = 수락이다.
  - 이 처리량 한계는 G-P17(append fsync의 위치·묶음, 전원 장애 창)의 근거다.

| 실행 | 결과 |
| --- | --- |
| 관련 회귀(§15.1 목록: G15 2파일 + storage·crash·app service·desktop·G-P04·G-P05 5파일·CLI·`tests/ui` 전체) | **1555 passed**(622.10s), 실패 0. 사본 `%TEMP%\recoryn-g15-g15bregress-15d1bdb99cba4a959f663aa7bfcc64de`, JUnit `33a942a4…6534`, 로그 `b7bb65b4…362d` |
| CI 동등(`g15_ci.py`: core job 순서·옵션, `--basetemp`만 추가) | lint 통과, format 170파일 통과, mypy 86파일 이상 없음. 시험 **15186 passed**(1173.26s), 전체 coverage 92.64%. 사본 `%TEMP%\recoryn-g15-ci-ad66511d74b04c2b86b0737cb96f0f71`, `coverage.json` `3f37a52c…5564` |
| coverage 예산 | **전 묶음 PASS**: domain 100.00/100.00, capture 99.85/98.57, jobs 98.89/97.47, **storage 96.56/92.16**, security 98.11/94.43, content 99.59/98.75, all 94.03/88.40(line/branch %) |

### 17.6 제출 파일과 sha256(LF)

| 파일 | G-P15b 변경 | sha256(LF) |
| --- | --- | --- |
| `src/recoryn/storage/chunks.py` | capability 결속(G15R-01) | `e289f3fd8b3f83b58b059cd537211eb12de2007b198e4cade03dd26dce4df6d5` |
| `src/recoryn/app/recording.py` | 시작 실패 정리(G15R-02) | `7a379d10ad794066cb62177c99316535f4138d77eeadee5e123c240488680c29` |
| `tests/unit/test_seal_phases.py` | BINDING 3, FC +1(49 node) | `b006ee9aa1394143d6090d08b8bec0e849dc654e885b62b60cca43bc9fe319e1` |
| `tests/integration/test_seal_mutex.py` | START 2·HB6R·FIFO-abort, CI 판정 정정(102 node) | `9c5cfc918a5031764bef654970663aba1eda498af5f45f76e64ec6c22281113e` |

도구(scratchpad, 저장소 밖):

| 파일 | sha256(LF) |
| --- | --- |
| `g15_copy.py`(5파일 덮어쓰기) | `97213258fb8d32e26feae1406c7e9e429ebac6c14a44191f85e33968b89510ab` |
| `g15_mutation.py`(R5·B1·R10·S1·R16) | `dbef867f37b843db87ec43a5f2970e0ab07be449a350323d0d88dc3be103c801` |
| `g15_ci.py` | `e0ff4502bbf44e5eea4c4d4b07baa6edcfdffedeef605f04f08e028c0764be2e` |
| `g15_slowdisk.py` | `fd60b3f9f3872a5262fd78103ea10cf66be07521d6dabb2c0f13460e9907b0f3` |
| `g15_slow_sync.py`(pytest plugin) | `a19cb6ea3741508e9e0a89f41bd94490234c76e7e7e805dc944c000433dd14d3` |

- `storage/library.py`·`storage/_coordination.py`는 G-P15b에서 바꾸지 않았다. 작업 트리의 `library.py` 차이는 G-P07의 것이며, 모든 사본은 HEAD판을 썼다.
- 이 문서의 hash는 G15b READY 보고에 적는다.
