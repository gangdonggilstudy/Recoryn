# GS06 / GS-P06 큰 캡처 packet의 frame 정렬 분할 — 계약안

작성: 2026-11-25, w5:p7 Claude(C00 배정). 배경은 `docs/implementation/s3-bundle-plan.md`의 P06(GF-17, C00이 S2로 재분류)이다. 이 문서는 계약안이며 제품·시험 파일은 바꾸지 않았다. 코드 근거는 모두 `git show b925520:<경로>`의 줄번호다. 작업 트리의 미완성 G-P08 변경은 근거로 쓰지 않았다.

## 1. 요구와 위험

- **요구(G1A-33):** 큰 packet은 분할하고, fragment 수와 frame offset을 기록한다. 원본 frame은 잃지 않는다.
- **현황:**
  - WASAPI source는 packet 하나를 PCMBlock 하나로 보낸다. 분할하지 않고, 64MiB를 넘을 때만 `PACKET_TOO_LARGE`로 중단한다.
  - 녹음 queue와 저장 writer는 block 하나를 16MiB까지 받는다.
  - 따라서 16MiB 초과 64MiB 이하 packet은 source를 통과하지만, 저장 경로에서 버려지거나 녹음을 중단시킨다(§2.2).
- **위험의 크기:** 한 장치 packet이 16MiB를 넘으려면 매우 큰 포맷과 큰 packet이 함께 필요하다. 예: 768kHz × 64ch × 4B는 196,608,000B/s다.
  - 이 앱은 shared-mode **polling**으로 100ms buffer를 요청한다(`capture/wasapi.py:133,141`).
  - 보통 packet은 장치 주기 하나다. 다만 API는 buffer 크기 외에 packet 상한을 약속하지 않는다.
  - **실제 장치의 발생률은 측정하지 않았고 주장하지 않는다.** 등급은 C00의 S2 재분류를 따른다. 지원 포맷 안에서 기능 실패가 우회 가능하기 때문이다.
- **해결로 세지 않는 것:** source 한도를 16MiB로 낮춰 packet 전체를 버리거나 중단하는 것은 해결이 아니다(s3-bundle-plan P06). fragment마다 따로 수락하는 분할도 해결이 아니다. 아래 P3처럼 녹음을 중단시킨다.

## 2. 직접 확인한 근거

### 2.1 코드 경로(b925520)

| 위치 | 사실 |
| --- | --- |
| `capture/wasapi.py:43` | `_MAX_PACKET_BYTES = 64MiB` |
| `capture/wasapi.py:188-194` | native read는 크기 검사를 `ct.string_at` 복사보다 먼저 한다. 초과 시 복사 0 |
| `capture/wasapi.py:383-386` | worker도 같은 한도를 검사한다. SILENT면 0 bytes payload를 만든다 |
| `capture/wasapi.py:405-417` | packet 하나 → `PCMBlock` 하나(`fragment_index=0`, `fragment_count=1` 기본값) → `submit(block)` |
| `capture/wasapi.py:425-437` | packet마다 건강 이벤트 1개, sequence는 수락 여부와 무관하게 packet마다 1 증가 |
| `domain/__init__.py:60-73` | `AudioFormat` 상한: 768,000Hz, 64ch, 최대 4B/sample. frame은 최대 256B |
| `domain/__init__.py:99-135` | `PCMBlock`에 `fragment_index`·`fragment_count`가 있고 검증된다. packet 안 frame offset 필드는 없다(fragment 순서로 유도). payload 크기 상한은 domain에 없다 |
| `storage/_safe.py:19` | `MAX_BLOCK_BYTES = 16MiB`(저장 block 상한의 유일한 정의) |
| `storage/chunks.py:143-166` | `_next`: 같은 sequence는 `fragment_index`가 정확히 +1이고 `fragment_count`가 같아야 한다. 새 sequence는 직전 packet의 fragment가 완결돼야 한다. 아니면 `ValidationError` |
| `storage/chunks.py:426-431` | `append`는 `0 < len(payload) <= MAX_BLOCK_BYTES`만 받는다(정확히 16MiB 허용) |
| `storage/chunks.py:236-254` | 복구 scan은 불완전한 마지막 packet의 fragment를 잘라 완결 packet까지만 남긴다(strict는 거부) |
| `storage/chunks.py:535-538` | 불완전한 fragment로는 seal을 거부한다 |
| `capture/queue.py:43-67` | `offer`는 block 하나 단위다. `queued_bytes + bytes > max_bytes`나 slot 초과면 그 block만 drop하고 센다 |
| `app/recording.py:48,134` | queue 기본 `max_blocks=256`, `max_bytes=16MiB` |
| `app/recording.py:180-216` | `submit(block)` → `offer` → 수락/drop frame 누계, `QUEUE_DROP` gap(인접 sequence 병합, 상세 256개) |
| `app/recording.py:248-259` | 소비자는 chunk를 packet 끝(`fragment_index + 1 == fragment_count`)에서만 넘긴다 |
| `app/desktop.py:17-29` | `CaptureSource.start(..., submit: Callable[[PCMBlock], bool], ...)` |
| `app/desktop.py:129-131,140-166` | `RecordingService`를 기본 queue 크기로 만든다. `_submit`은 block 하나를 전달하고 meter·수락 frame을 갱신한다 |
| `app/media.py:36-54` | 시각 상관 판정과 1%/1µs clock step 판정 |
| `app/media.py:223-253` | 같은 sequence의 `fragment_index + 1`은 연속으로 본다. 다만 각 fragment에 상관된 `capture_mono_ns`가 있고 `device_frame_position`이 정확히 이어져야 한다. 아니면 clip을 나눈다 |
| `app/media.py:269-271` | packet 안 조각의 시각은 `stamp + offset × 1e9 // rate`(정수)로 유도한다 |

### 2.2 직접 측정(계약 단계 probe, 저장소 미수정)

- 실행 환경: `git archive b925520` 격리 사본, `python -I`, import 출처가 사본임을 확인했다. 장치·네트워크는 쓰지 않았다.
- probe 스크립트: `scratchpad/gs06/probe.py`(LF SHA-256 `f6c45d0518fd2972d31e7df3d19810b0edc8b265ce2c93276af1e6addc37047b`).
- 결과(경로 줄 제외 SHA-256 `035fcb850344f9e1918a839ebc59296852966174600301dd0b510d032e2c36ae`). 포맷은 48kHz mono s16le(2B/frame)이다.

| 행 | 입력 | 관측 |
| --- | --- | --- |
| P1 | 기본 queue(16MiB), 16MiB + 1frame block | `submit=False`, dropped_frames 8,388,609, 세션 **FINALIZED, 저장 frame 0** |
| P2 | queue 64MiB, 같은 block | 수락 → writer 거부 → storage_failed, 세션 **INTERRUPTED**, 저장 0 |
| P3 | 기본 queue, sequence 0을 2 fragment로 나눴는데 둘째가 수락되지 않음 → sequence 1 전체 | 첫 fragment 수락 → 다음 packet에서 `_next` 위반 → **INTERRUPTED**, 저장 0 |
| P4 | 기본 queue, 정확히 16MiB block | 수락·저장 8,388,608 frame, FINALIZED |

### 2.3 GF-17 기록 정정

`docs/reviews/g01-gap-recording.md`의 G1A-33 산술은 "writer가 거부하고 세션은 INTERRUPTED"라고 썼다. 실제 경로는 그와 다르다.

- 데스크톱 기본 구성(queue 16MiB)에서는 16MiB 초과 packet이 **writer에 닿기 전에 매번 QUEUE_DROP**이 된다(P1). 녹음은 정상 종료로 보이지만 그 트랙 원본이 남지 않는다.
- INTERRUPTED는 queue가 16MiB보다 클 때의 경로다(P2).
- 정확히 16MiB packet은 queue가 비어 있을 때만 들어간다. backlog가 있으면 같은 이유로 drop된다.
- 또 G1A-33의 "100ms packet ≈ 19.7MB"는 packet이 buffer 전체 크기라는 가정이다. polling shared mode의 보통 packet은 장치 주기다(§1).

등급(S2)의 근거는 "지원 포맷 안의 기능 실패"이며 위 정정으로 바뀌지 않는다.

## 3. 권고 계약

### 3.1 불변식

- **I1 원본 frame 보존:** 수락된 packet의 저장 bytes는 원래 packet bytes를 순서대로 이은 것과 같다(SILENT는 0 bytes). 분할로 frame이 생기거나 사라지지 않는다.
- **I2 packet 원자 수락:** packet의 fragment는 **모두 수락되거나 모두 거부된다.** 소비자와 writer는 불완전한 packet을 받지 않는다. 그 결과 G-P17a writer guard(`_next`, 16MiB 상한, seal 거부, 복구 절단)는 마지막 방어선으로 그대로 남고 우회하지 않는다.
- **I3 회계 1회:** 거부된 packet은 frame 수 정확히 한 번, QUEUE_DROP gap 하나로 센다(sequence 범위 `[s, s]`). fragment 수만큼 두 번 이상 세지 않는다. 수락 회계도 같다. G-P08 원칙("fragment별 중복 이벤트도 동일 원본 범위를 한 번만 센다")과 맞는다.
- **I4 녹음 독립:** 분할·수락은 source callback 안의 메모리 작업이다. 파일·DB I/O나 대기를 넣지 않는다. capture gate와 queue lock의 보유는 offer 한 번 길이로 제한한다.
- **I5 한도 단일 정본:** 분할 상한은 저장 block 상한과 같은 정본 상수에서 읽는다. 두 곳에 숫자를 따로 두지 않는다.

### 3.2 분할 규칙(`capture/wasapi.py`)

packet 하나에서 아래 값이 주어진다.

- N frame, frame 크기 b bytes
- 장치 위치 `pos`(없을 수 있음), QPC 시각 `c0`(TIMESTAMP_ERROR이거나 없으면 None)
- packet flag 집합 Φ, 분할 상한 L(= 정본 16MiB)

| 항목 | 규칙 |
| --- | --- |
| fragment 크기 | `F = floor(L / b)` frame(항상 1 이상, b ≤ 256). `K = ceil(N / F)`. fragment k(0부터)는 `min(F, N − kF)` frame이며 **frame 경계에서만** 자른다. payload는 `[kFb, (kF + n_k)b)` slice다. `N ≤ F`면 K=1이고 지금과 바이트·메타데이터가 완전히 같다 |
| 한도 | packet 전체 검사(`PACKET_TOO_LARGE`, 64MiB)는 그대로 둔다. 64MiB 이하만 분할한다. fragment payload ≤ L이 수학적으로 보장된다 |
| sequence·순번 | 모든 fragment는 packet의 같은 sequence를 쓴다. `fragment_index = k`, `fragment_count = K`다. sequence는 packet마다 1 증가한다(지금처럼 수락과 무관) |
| 장치 위치 | `pos_k = pos + kF`(pos가 None이면 None). 2^63 이상으로 넘치면 그 fragment부터 None이다(되감기·포화 금지) |
| capture 시각 | `c_k = c0 + (kF × 1_000_000_000) // sample_rate`. media의 조각 시각 공식(`app/media.py:270`)과 같은 정수식이다. c0가 None이면 모두 None. 넘침이면 그 fragment부터 None. 같은 packet 안 sample은 정의상 연속이므로 추정 연장이 아니다 |
| clock_quality | 모든 fragment가 packet과 같다(`DEVICE_CORRELATED` 또는 `INVALID`) |
| arrival | 모든 fragment가 packet의 `arrival_mono_ns`와 같다 |
| 상태 flag | `SILENT`, `TIMESTAMP_ERROR`는 모든 fragment에 둔다(payload·시각의 성질) |
| 사건 flag | `DATA_DISCONTINUITY`와 `RAW_FLAGS_*`는 **fragment 0에만** 둔다. packet 앞의 사건이므로, fragment마다 두면 media가 fragment 경계마다 clip을 나눈다(`app/media.py:246`) |
| 건강 이벤트 | packet마다 `packet` 이벤트 1개다. 기존 필드에 `fragment_count`를 더하고 `frame_count`는 packet 전체다. `accepted`는 원자 결과다. fragment별 이벤트는 내지 않는다 |
| stopped 누계 | `accepted_frames`·`rejected_frames`는 packet 단위 원자 결과의 합이다 |

media 연속성 확인(손 산술): 연속 fragment 사이 `elapsed − nominal ∈ {0, 1}`ns이고 판정 허용치는 `max(1000, nominal/100)`이다. 위치 차는 정확히 F다. 따라서 분할 packet은 분할하지 않은 packet과 같은 clip이 된다(§4 M family로 확인).

### 3.3 원자 수락(`capture/queue.py`, `app/recording.py`, `app/desktop.py`)

- **callback 계약:** `submit(item: PCMBlock | tuple[PCMBlock, ...]) -> bool`.
  - tuple은 **한 packet의 K ≥ 2 fragment 전부를 순서대로** 담는다. K=1 packet은 지금처럼 `PCMBlock` 하나를 넘긴다. 기존 source, fake, 시험의 단일 block 호출은 바뀌지 않는다.
  - tuple 검증(어기면 `ValidationError`, 회계 0): 비어 있지 않음, K ≥ 2, 같은 session·track·epoch·format·sequence·`fragment_count = K`, `fragment_index = 0..K−1`.
- **queue:** `BoundedCaptureQueue.offer_packet(fragments) -> bool`.
  - **하나의 lock 구간에서** `slot 여유 ≥ K`이고 `byte 여유 ≥ Σpayload`이면 K개를 연속으로 넣는다. 아니면 하나도 넣지 않는다.
  - drop 누계는 blocks += K, frames += N, bytes += Σ로 한 번에 더한다. 닫힌 queue는 지금처럼 False이며 회계 0이다.
  - 다른 트랙의 offer가 packet 중간에 끼어들 수 없다.
- **RecordingService:**
  - `submit`은 tuple을 받아 gate 안에서 `offer_packet`을 한 번 부른다.
  - 수락이면 `accepted_frames += N`, `last_accepted_sequence = s`다.
  - 거부면 `dropped_frames += N`이고 gap 하나다(기존 인접 병합 규칙 그대로).
  - gate가 닫혀 있으면 False이며 drop으로 세지 않는다(G-P08).
- **DesktopRecorder:**
  - `_submit`은 tuple을 그대로 넘긴다. generation·epoch 재검사는 fragment 0 기준이다.
  - meter는 마지막 fragment, 수락 frame은 N이다. storage_failed 처리는 지금과 같다.
- **소비자와 writer:** 바꾸지 않는다. packet 끝에서만 chunk를 넘기는 기존 규칙(`recording.py:253`)과 writer 검증이 분할 packet에도 그대로 적용된다.

### 3.4 queue byte 예산

원자 수락만으로는 부족하다. queue가 16MiB면 16MiB보다 큰 packet은 **결코** 들어가지 못해, P1처럼 전부 drop된다. 그래서 세션 queue byte 예산을 트랙 포맷에서 정한다.

- 권고식: `max_bytes = max(16MiB, min(128MiB, 2 × P(f*)))`. `P(f) = ceil(f.sample_rate × 0.2) × f.frame_bytes`로, 요청한 100ms buffer의 두 배다. f*는 frame 속도가 가장 큰 트랙이다.
- 일반 포맷(예: 48kHz stereo s16le, P ≈ 38KB)에서는 지금과 같은 16MiB다.
- 상한 포맷에서는 128MiB까지 쓴다. queue는 미리 할당하지 않으므로 backlog가 있을 때만 메모리를 쓴다.
- 예산을 넘는 packet은 원자적으로 거부되고 정확히 QUEUE_DROP으로 센다. 숨기거나 중단하지 않는다.
- slot 상한 256은 유지한다. 64MiB packet 검사 때문에 K ≤ 5다(64MiB/16MiB = 4에 frame 정렬 나머지가 더해진다). 예: b=192이면 F=87,381, N 최대 349,525, K=5다.
- 수치(0.2s, 128MiB)는 측정값이 아닌 정책값이며 C00 결정 대상이다(§10).

### 3.5 한도 정본(공통 한도 소유)

- `MAX_PCM_BLOCK_BYTES = 16MiB`를 domain(`domain/__init__.py`, PCMBlock 옆)이 소유한다.
- `storage/_safe.py`는 `MAX_BLOCK_BYTES = MAX_PCM_BLOCK_BYTES`로 같은 값을 다시 노출한다. 이름과 동작은 그대로다.
- capture는 domain만 import한다. storage를 import하지 않는 지금의 계층을 유지한다.
- `PCMBlock` 생성에 이 상한을 새로 강제하지는 않는다. 기존 큰 block 시험과 데이터를 깨지 않기 위해서이며, writer가 최종 guard다.

### 3.6 바꾸지 않는 것

- 저장 형식, journal, 복구, seal: `storage/chunks.py`(G-P17a·b 소유)는 쓰지 않는다.
- WASAPI buffer 요청(100ms, polling), 64MiB packet 검사, 복사 전 크기 검사.
- sequence·epoch·QUEUE_DROP·gate 의미(G-P08), 소비자의 chunk 회전 규칙.

## 4. 경우의 수

### 4.1 차원과 동치류

- **frame 크기 b:** 2(s16 mono, L을 나눔), 4(s16 stereo, 나눔), 9(s24 × 3ch, 나누지 않음), 192(s24 × 64ch, 나누지 않음).
- **상한 나머지:** `L mod b ∈ {0, b−1}`. 시험에서는 L을 작은 값으로 주입한다(F=3). 실제 16MiB 경계는 B family에서 확인한다.
- **packet frame N:** 1, F−1, F, F+1, 2F−1, 2F, 2F+1, 5F.
- **flag:** 없음, SILENT, DATA_DISCONTINUITY, TIMESTAMP_ERROR, DATA_DISCONTINUITY + RAW.
- **시계:** pos·QPC 모두 있음, pos만, QPC만, 둘 다 없음.
- **queue 여유:** byte {P−1, P, P+1} × slot {K−1, K, K+1}. gate {열림, 닫힘}. 다른 트랙 offer의 끼어들기 {없음, 동시}.

### 4.2 분모

| family | 입력 | 행 | 수준 |
| --- | --- | ---: | --- |
| S 분할 산술 | b4 × 나머지2 × N8 × flag5 × 시계4 | 1,280 | 순수, batching |
| O 넘침 | pos 2^63 근처 {fragment 1에서 넘침, 안 넘침} × QPC 근처 {넘침, 안 넘침} × K{2, 3} | 8 | 순수 |
| A 원자 수락 | K{1, 2, 3} × byte3 × slot3 × gate2 × 끼어들기2 | 108 | 실제 `BoundedCaptureQueue` |
| R 서비스 회계 | K{1, 2, 3} × {수락, 거부} × 직전 gap{없음, 인접, 비인접} × {열린 gate, 닫힌 뒤 늦은 입력} | 36 | 실제 `RecordingService` |
| W source→writer | K{1, 2, 3} × packet 끝과 `chunk_frames`의 관계{앞, 같음, 뒤} × 트랙{1, 2} × 종료{stop, pause→resume} | 36 | 합성 source → 실제 writer·sealer·scan |
| C 복구 절단 | (K=2: k=1)·(K=3: k=1, 2) × scan{strict, 비strict} | 6 | 실제 staging scan(G-P04 경로 재사용) |
| B 실제 한도 | fragment 정확히 16MiB 저장 1. L+1 미생성 1. packet {64MiB − b, 64MiB, 64MiB + b} 3. queue 예산식 {16MiB 하한, 계산값, 128MiB 상한} 3 | 8 | 실제 크기, 소수 행 |
| M media 메타모픽 | 시계{상관, TIMESTAMP_ERROR, 위치 없음} × 불연속{없음, 다음 packet} × K{2, 3} | 12 | 분할본 대 비분할본 파생 clip |
| H 건강 이벤트 | K{1, 3} × 수락{T, F} × flag{없음, SILENT, DISC} | 12 | fake backend worker |
| G G-P08 대조 | G-P08 push 뒤 확정(잠정: 수락·거부 × K{1, 3} × checkpoint 전·후) | 8 | push 뒤 재산출 |
| T 부정·타입 | 분할: L < b, bool·비정수 L, payload 길이 불일치, N=0. tuple: 빈 tuple, K=1 tuple, sequence 혼합, index 결손·중복, track·epoch·format 혼합, PCMBlock 아닌 항목, `fragment_count` 불일치 | 12 | 순수·서비스 |
| **합계** | | **1,526** | 계획, 실행 0 |

신규 시험의 단독 실행 게이트는 60초다. S는 한 node에서 1,280 tuple과 ID를 모두 검사한다. 넘으면 행을 줄이기 전에 측정값과 최적화안을 보고한다.

### 4.3 독립 oracle(손으로 쓴 기대)

- **S·O:** 위 §3.2 표를 시험 파일에 손으로 옮긴 규칙으로 기대 fragment 목록을 만든다. 제품 분할 함수를 기대값 계산에 쓰지 않는다. 기대 fragment 목록의 내용은 다음과 같다.
  - K, n_k, payload slice
  - `pos_k`, `c_k`(정수식), quality, arrival, sequence, index·count
  - flag 배치(상태는 전부, 사건은 0번만)
  - 이어 붙인 bytes = 원본(SILENT는 0)
- **A·R:** 수락은 "여유 byte ≥ P 이고 여유 slot ≥ K"일 때뿐이다(닫힌 gate면 False, 회계 0). 수락이면 FIFO 안에 연속 K개, 거부면 queue 불변이다. 회계는 packet당 frame N 1회, gap 1개이고 인접 sequence는 기존 병합 규칙을 따른다. 끼어들기 행은 다른 트랙 block이 fragment 사이에 없음을 queue 순서로 확인한다.
- **W:** 입력 기록 원장(packet별 bytes·수락 여부)과 비교한다.
  - 저장 frame 합 = 수락 frame 합
  - 저장 bytes = 수락 packet bytes의 순서 연결
  - 모든 chunk의 마지막 record가 packet 끝(index + 1 = count)
  - strict scan 통과, 세션 FINALIZED(정상 종료 행)
- **C:** k개 fragment 뒤 중단한 staging을 scan한다.
  - 비strict: 직전 완결 packet까지만 남는다.
  - strict: `Incomplete final packet fragments`로 거부한다.
- **B:**
  - 실제 writer는 정확히 16MiB fragment를 저장한다.
  - 분할 결과에 L+1 bytes fragment가 없다.
  - 64MiB + b packet은 복사 전에 `PACKET_TOO_LARGE`다(native 경로는 `string_at` 호출 0).
  - 예산식 3행은 손 산술 값과 같다.
- **M:** 같은 합성 오디오를 비분할 packet과 F 크기 분할 packet으로 저장한 두 세션을 비교한다. 파생 clip의 PCM bytes, clip 수, source_ranges의 frame 합, `timing_quality`, 시작 시각이 같다. 분할 경계에서 clip이 새로 나뉘지 않는다.
- **H:** packet당 이벤트 정확히 1개다. `frame_count`는 N, `fragment_count`는 K, `accepted`는 원자 결과다. stopped 누계는 수락·거부 packet frame 합과 같다.
- **G:** G-P08 최종 건강 모델에서 확인한다.
  - accepted·queue loss 누계, gap 하나
  - 마지막 sequence/fragment가 `(s, K−1)`
  - fragment 이벤트 중복 계상 0
  - checkpoint가 packet 중간 상태를 기록하지 않음

## 5. 기존 시험과의 관계

- `tests/unit/test_wasapi.py`:
  - `test_fake_silent_packet_ignores_null_pointer_and_buffer_errors_release`의 `PACKET_TOO_LARGE`(0xFFFFFFFF frame)는 그대로 유효하다.
  - packet 단위 회계를 확인하는 `test_worker_packet_units_flags_rejection_and_thread_owned_cleanup`는 K=1 행에서 바뀌지 않아야 한다.
  - 분할 worker 행(H, B의 packet 경계)은 이 파일의 `FakeBackend`로 추가한다.
- `tests/unit/test_capture.py`(queue)·`tests/unit/test_storage.py::test_fragment_and_sequence_rules`(writer `_next`): 기존 기대를 바꾸지 않는다. writer 규칙은 이번 단위의 기대가 아니라 보존 대상이다.
- 녹음 경로에 `submit(block)`을 부르는 기존 시험: K=1 경로가 같으므로 적응이 없어야 한다. 적응이 필요하면 먼저 보고한다.
- G-P08의 Q family는 "전체 packet만 사용해 불완전 fragment 저장 문제와 섞지 않는다"고 적었다(g08 계약). 이 단위의 G family가 그 공백을 G-P08 최종판 위에서 닫는다.

## 6. mutation 계획 18개

| ID | 결함 | 목표 |
| --- | --- | --- |
| MU01 | frame 대신 byte 경계로 자름 | S(b=9·192, 나머지 b−1) |
| MU02 | F를 ceil로 계산(상한 초과) | S·B(L+1 미생성) |
| MU03 | 마지막 fragment 크기 off-by-one | S(N = kF ± 1) |
| MU04 | fragment마다 sequence 증가 | S·W(`_next`) |
| MU05 | fragment_index가 1부터 시작하거나 count가 틀림 | S·T |
| MU06 | 장치 위치를 offset하지 않음 | S·M(clip 분리) |
| MU07 | capture 시각을 float로 계산하거나 arrival로 대체 | S·M |
| MU08 | DATA_DISCONTINUITY를 모든 fragment에 둠 | S·M |
| MU09 | SILENT를 fragment 0에만 둠 | S·H |
| MU10 | TIMESTAMP_ERROR를 fragment 0에만 둠(뒤 fragment에 유도 시각) | S·M |
| MU11 | fragment별 offer(원자성 제거) | A·W(P3형 중단) |
| MU12 | 여유 검사를 fragment별 크기로 | A |
| MU13 | 거부 packet을 fragment마다 gap·frame 계상 | R·H |
| MU14 | 건강 이벤트를 fragment마다 냄 | H |
| MU15 | 분할 상한을 정본 대신 별도 숫자(16MiB + b)로 | B |
| MU16 | `PACKET_TOO_LARGE` 검사를 복사 뒤로 옮기거나 제거 | B |
| MU17 | queue 예산을 16MiB 고정 | B·W(상한 포맷 packet 전부 drop) |
| MU18 | 소비자 회전을 packet 중간에 허용 | W(seal 거부) |

실행 방식은 이전 단위와 같다: 격리 사본에 mutant 하나씩 적용, PYTHONPATH와 import 출처 확인, 목표 assertion 실패만 검출로 센다.

## 7. 구현 쓰기 범위·순서(승인 요청)

**10파일**을 제안한다. s3-bundle-plan의 후보는 wasapi·한도 모듈·`test_wasapi`·통합 시험이었다. 원자 수락(§3.3)과 예산(§3.4) 때문에 queue·recording·desktop이 필요하다(결정 1).

1. `src/recoryn/capture/wasapi.py`: 분할, tuple submit, packet 건강 이벤트.
2. `src/recoryn/capture/queue.py`: `offer_packet`.
3. `src/recoryn/app/recording.py`: tuple 수락, packet 회계, 예산 인자. **G-P08·G-P17b 파일.**
4. `src/recoryn/app/desktop.py`: callback 형식, tuple 전달, 예산 계산. **G-P08·G-P17b 파일.**
5. `src/recoryn/domain/__init__.py`: `MAX_PCM_BLOCK_BYTES`.
6. `src/recoryn/storage/_safe.py`: 정본 재노출 1줄(G-P17a 목록에 없음. 겹치면 보고).
7. `tests/unit/test_wasapi.py`: H·B worker 행.
8. `tests/unit/test_packet_split.py`(신규): S·O·A·T와 ID 감사.
9. `tests/integration/test_packet_split.py`(신규): R·W·C·B·M·G.
10. `docs/testing/gs06-capture-packet-split-cases.md`: 결과.

권고 순서는 **G-P08 push → G-P17a(chunks.py만) → GS-P06 → G-P17b**다. P06과 G-P17b는 `recording.py`·`desktop.py`를 함께 쓰므로 직렬화해야 한다. P06이 더 작고 G-P17b의 cutoff·A 회계가 packet 원자 수락 위에서 정의되면 단순해지므로 P06을 먼저 둘 것을 권고한다. 시작 때 기준 tree와 파일 hash를 다시 고정한다.

## 8. 대안과 기각 사유

| 대안 | 장점 | 한계 |
| --- | --- | --- |
| source 한도를 16MiB로 낮춰 중단하거나 drop | 한 줄 | 원본 손실. s3-bundle-plan이 해결로 세지 않는다 |
| 분할 + fragment별 submit | wasapi만 수정 | 부분 수락으로 writer가 깨진다(P3 실측 INTERRUPTED) |
| 소비자가 fragment를 모았다가 불완전하면 버림 | callback 불변 | 수락된 frame을 나중에 버린다. G-P08·G-P17의 A·W 회계(수락 후 누락 구별)와 충돌 |
| writer block 상한을 64MiB로 | 분할 불필요 | 저장 형식·복구 메모리·G-P17 범위 변경. queue 16MiB 문제도 남음 |
| WASAPI buffer를 줄여 packet을 작게 | 발생 가능성 감소 | packet 상한을 보장하지 못함(장치·loopback 의존). 보완책일 뿐 |
| 시작 때 상한 포맷 거부 | 정직, 단순 | G1A-33 분할 요구를 충족하지 않음. 분할 구현 전까지의 임시책으로만 의미 |

## 9. 미검증 한계

- 실제 장치에서 16MiB 초과 packet의 발생 여부와 빈도, 장치별 packet 크기.
- 상한 포맷에서 128MiB backlog의 실제 메모리 압박.
- 장기 세션 성능.
- CTranslate2·STT에 미치는 영향. 파생 clip은 M으로 동일성만 확인하며 실제 모델 실행은 하지 않는다.
- G family는 G-P08 최종 API에 따라 행과 기대를 다시 고정해야 한다.

## 10. C00 결정 요청

1. **원자 수락과 범위 확대:**
   - `submit(PCMBlock | tuple[PCMBlock, ...])`와 `offer_packet`(전부 또는 전무)를 채택하는가.
   - 이에 따라 쓰기 범위를 §7의 10파일로 넓히는가(queue·recording·desktop 포함, G-P08 push 뒤).
2. **queue byte 예산:** `max(16MiB, min(128MiB, 2 × P(f*)))`(P = 200ms 분량)를 승인하는가. 다른 선택지는 16MiB 유지 + 상한 포맷 시작 경고, 또는 다른 계수다.
3. **한도 정본:** `MAX_PCM_BLOCK_BYTES`를 domain이 소유하고 `storage/_safe.py`가 재노출하는가. 다른 선택지는 별도 상수 + 동등성 시험이다.
4. **fragment 시각:** 뒤 fragment에 정수 유도 `capture_mono_ns`(media 공식)와 packet과 같은 quality를 두는가. 대안은 유도 표시 flag 추가, 또는 None이다. None은 media가 fragment마다 clip을 나눈다.
5. **flag 배치:** 상태 flag(SILENT, TIMESTAMP_ERROR)는 모든 fragment, 사건 flag(DATA_DISCONTINUITY, RAW_*)는 fragment 0만으로 하는가.
6. **건강:** packet당 이벤트 1개 + `fragment_count` 필드로 하고, G family는 G-P08 push 뒤 재산출하는가.
7. **순서:** G-P08 → G-P17a → GS-P06 → G-P17b 직렬화를 승인하는가. 또는 G-P17b를 먼저 둘 것인가.
8. **GF-17 기록 정정(§2.3):** 기본 구성의 실제 경로(QUEUE_DROP, 저장 0)를 원 리뷰에 반영하는가. 반영은 C00 문서 단위다.
9. **분모와 게이트:** 1,526행(G 8행 잠정), mutation 18개, 신규 시험 단독 60초 게이트를 승인하는가.

이 문서 외에 저장소 파일을 수정하지 않았다. 제품 코드·시험은 실행하지 않았고 mutation도 0이다. 위 probe는 격리 사본에서만 실행했다.

## 11. 구현 착수 재대조 — f4f94b7 + G-P17a

C00이2026-11-25 GS-P06 구현을 배정했다. 기준은 `f4f94b7`이며 최종 검증은 G-P17a push 뒤 HEAD에서 한다. 그전에는 HEAD+G17a9파일+GS06승인10파일의 TEMP 사본이다. G-P17a 재확인 수정이 우선이며 storage/chunks.py·_coordination.py·library.py는 읽기만 한다. 승인10파일은 기존 제품/시험7파일이 HEAD와 LF 기준 같고 신규 시험2파일·이 문서만 미추적임을 확인했다. 계약 원문 LF SHA256은3f00e490…와 일치한다. G-P13·G-P11d·G-P12b의 공유 변경 파일과 직접 교집합0이다.

입력·해시·원문 사본은 OS TEMP `recoryn-gs06-vacmk4sw/input.json`·`before/`에 고정했다. 구현 전 독립 반례는 같은 TEMP의 `probe_media_boundary.py`다. 실제 장치·음성·모델·전송은 쓰지 않는다.

### 11.1 재대조 결정 대기

- **M/범위:** 같은6frame packet을 상관 시각으로 저장하면 비분할/3fragment 모두clip1이다. TIMESTAMP_ERROR는 비분할unknown clip1 대3fragment unknown clip3으로 계약 M의clip 수 동일 요구가 실패했다. app/media.py의 미상 시각마다 flush하는 경로다. 같은 packet 안 검증된 연속 fragment만 합치고 시각은unknown으로 유지하는 최소 변경을 위해 app/media.py 추가 범위를 C00에게 요청했다. 승인 전에는 쓰지 않는다. `_clock_step`의 실제 사용은 부정 조건이므로 상관 시각 경로가 반대로 동작한다는 주장은 하지 않는다.
- **B/입력:** 지원 최대 포맷768000Hz×64ch×4B에서 승인 식은78,643,200B(75MiB)다.128MiB cap은 이 유효 입력 범위에서 도달 불가다. B의 세 번째 예산 행을 지원 최대75MiB 및128MiB 이하 확인으로 대체해 B8·전체1,526을 유지하는 안을 C00에게 질문했다. 공식 식 자체는 바꾸지 않는다.

### 11.2 G8·T12와 구현 독립 oracle

G8은 K{1,3}×수락/거부×관찰 시점{소비자 drain 전 checkpoint, drain 후}다. 실제 G-P08 accepted/dropped/gap·canonical 이벤트·소스 packet 이벤트를 비교하고, 마지막fragment는 저장 journal의 `(sequence, fragment_index=K−1)`로 확인한다. 건강 schema에 허용되지 않은 새 필드를 넣지 않는다. submit은 packet 전체를 gate 안에서 반영하며 소비자 checkpoint는 새 tuple packet의 마지막fragment append 뒤에만 한다. checkpoint 전후의 수락 의미와 실제 저장 완료를 혼동하지 않는다. 기존 수동 단일PCMBlock fragment 호출의 호환은 유지한다.

T12는 L<frame, bool L, 비정수 L, payload 길이 불일치, N0의5행과 tuple empty/K1/sequence 혼합/index 결손·중복/identity 혼합/non-PCM/count 불일치의7행이다. index 결손·중복과 identity(track/epoch/format)는 그 행 안의 명시 하위 변형을 모두 실행하며 개별 ID/입력 설명을 남긴다. 주 분모12와 하위 assertion 수를 분리한다.

A108은 capacity near-boundary와 두 producer의 실제 barrier 경합을 사용한다. 기대는 packet→다른track 또는 역순 두 합법 선형화의 손 원장이다. 제품 queue 상태로 expected를 생성하지 않는다. R36은 실제 service/queue의 바이트 한도를 통제해 수락/거부를 만들고 수락된 항목을 버리는 fixture를 쓰지 않는다. W36은 source→실제 consumer/sealer→strict scan에서 원본 bytes·packet 끝 회전을 확인한다. C6은 실제 불완전 마지막 packet을 scan하며 마지막 완결 packet 바이트와 직접 대조한다.

S1280은 소규모 limit의 수동 정수 oracle로 배치1node에서 모든ID를 검사한다. O8·A108·R36·W36·C6·B8·M12·H12·G8·T12를 합쳐 원 분모1,526을 유지한다(위 결정 대기 포함). MU01~18은 사본 pyproject/src/tests를 함께 두고 하나씩 치환한다. 수집 실패·시간 초과는 검출로 세지 않는다. 새 시험 단독60초를 실측하며 초과 시 축약 전에 보고한다.

원자 API는 tuple의 완결성·같은 packet identity·순서를 검증하고 ValidationError면 회계0이다. 기존 단일PCMBlock 호출은 기존 fragment 스트림 호환을 유지한다. source는 K1일 때 단일block, K≥2일 때 tuple을 보낸다. 64MiB packet 검사와 storage16MiB 최종 방어는 그대로다. 정책식 때문에 정상 포맷의16MiB queue보다 큰 packet은 여전히 원자 QUEUE_DROP일 수 있으며 무조건64MiB packet을 수락한다고 보장하지 않는다.

### 11.3 부정 입력·예산의 추가 대조

T의 identity 혼합은 session도 포함하고 non-PCM은 첫 항목/중간 항목을 모두 확인한다. 별도 X001은 실제 RecordingService의 비정상 tuple/list/None이 queue·frame 회계0으로 거부됨을, X002는 부정 format 예산이 세션 생성 전에 거부됨을 확인한다. X는 주 분모1,526에 합산하지 않는다. B006~008은 순수 예산식뿐 아니라 실제 RecordingService 기본 queue 설정을 확인하고, 고포맷에서는16MiB를 조금 넘는 실제 packet의 원자 수락·저장도 대조한다. B007 손 산술은2×153600frame×192B=58,982,400B다. 예산은RecordingService에서 단일 계산하며 Desktop이 중복 max_bytes 인자를 보내 기존 source/factory override를 깨지 않게 했다.

기존 capture/wasapi/app_service 선택 회귀는 전부 PASS였다. 최초 새 통합 실행의37실패는 작성 시험의CaptureProgress 필드명 오기36건과 B007 손 산술 오기1건이었다. 정본 current_accepted_frames와 위 산술로 고친 뒤 M12·결정 대기B008을 제외한91행이 PASS(16.68초)했다. 제품 단언을 약화하거나 기존 시험을 수정하지 않았다.

## 12. 중간 구현·검증 결과 — 추가 범위 결정 대기

상태는 **SCOPE_NEEDED**이며 IMPLEMENTATION_READY/전수 PASS가 아니다. 현재 기준은 f4f94b7+G-P17a9파일+GS-P06승인10파일이고, 최종 검증은 G-P17a push 뒤 HEAD에서 해야 한다. 제품·시험 코드의 쓰기는 승인10파일뿐이다. app/media.py와 G-P17a3개 저장 모듈은 수정하지 않았다.

### 12.1 직접 실행 결과

- 기존 capture/wasapi/app_service 선택 회귀 PASS. 단일PCMBlock의 기존 `_observe_block(block, accepted)` 호출 형태도 유지하고, tuple만 전체 frame 수를 전달한다. G-P08 unit/property/integration와 기존 capture/wasapi/app_service 관련 합계 **1,232 PASS·46.95초**다.
- 중간 사본의 UI 전체 **2,949 PASS·196.66초**. ruff check·format check·mypy(src/recoryn scripts packaging) PASS. UI 실행은 단일 block 호출 형태의 마지막 호환 보강 전이고 관련1,232행은 그 뒤다. 최종 HEAD 전수에서 모두 다시 확인한다.
- 신규 선택 묶음은250 node(S1280을1node로배치, 나머지주분모246node+X3)이며 첫 실행 **246 PASS·4 FAIL·29.57초**, 현재 코드 재실행도 **246 PASS·4 FAIL·19.66초**다. 실패는 M005~008 네 행뿐이다. 정상본 단독 PASS라고 집계하지 않는다. C00의60초 목표를 넘기지는 않았고 행 축소0이다.
- 원 계획 **1,526행**을 JUnit의S ID 속성과 나머지행 ID로 독립 대조했다. 누락·예상 밖 ID·중복0이다. 주 분모는1,522행 통과·M4행 실패이고 X001~003은 별도다(`case-audit1.json`, `case-audit2.json`).
- MU01~18을 현재 코드 사본에서 모두 재검출했다. pyproject/src/tests를 함께 복사했고 import가 사본 src임을 확인했다. 목표 AssertionError/정확 DID NOT RAISE만 검출로 셌다. 수집 오류·timeout은 없다(`mutate.py`, `mutation-results.json`).
- B002는frame252B(768000Hz·63ch·s32le)의64MiB−4B 실제 packet을5fragment로 나눠 기본 queue(77,414,400B)에 원자 수락·단일 완결 chunk 저장·전체 PCM 일치를 확인했다. B007·B008도 지원 고포맷의16MiB 초과 packet이 실제 기본 queue에 수락·저장되는지 확인했다. B008의원문 '128MiB도달' 표현은 지원 범위에서 불가능하여 C00 문구 결정을 기다린다. 제품 정책식은 승인 그대로다.
- X003은 원 Native QPC100ns 값이ns로 표현할 수 없는 경우 모든 fragment의 시각None·quality INVALID·원본 bytes 보존을 확인한다. S의폭 oracle는 제품 frame_bytes 계산을 expected로 쓰지 않고2/4/9/192의 손 표를 사용한다.

### 12.2 1·2트랙 순차 측정

검토자의 기존 probe_g17.py를 그대로 사용했다.100blocks/s/track·480frame·12초, 모델/장치/전송 없음, 자체 UI/시험/변이를 동시에 돌리지 않았다. 기준은 raw HEAD 단독이 아니라 **f4f94b7+G-P17a9파일**이며 수정본은 여기에GS06을 얹었다. 이 측정은 마지막 단일block 호출 형태 호환 보강 전이므로 최종 HEAD 측정과 구분한다(`measurement-phase1-hashes.json`).

| 트랙 | 기준 거부 | GS06 거부 | 기준/GS06 저장frame | 양쪽 보존 |
| --- | --- | --- | --- | --- |
| 1 | 0 | 0 | 576,000 / 576,000 | 저장=수락·정상 종료 |
| 2 | mic0/system0 | mic0/system0 | 1,152,000 / 1,152,000 | 저장=수락·정상 종료 |

원시 결과는TEMP `recoryn-gs06-vacmk4sw/measurements.json`이다. 실제 장치의 큰packet 발생률·HDD·백신·장기세션·상한포맷 메모리압박은 NOT_RUN이다.

### 12.3 C00 결정이 필요한 실제 경계

1. **app/media.py 추가 또는 M 계약 수정.** 상관 시각은 비분할/분할이 같지만 TIMESTAMP_ERROR의 같은6frame packet은 clip1→3이 된다. M005~008의 실패는 이 경로로 재현했다. 같은 packet의 검증된 연속 fragment 안에서만 unknown을 유지하며 묶고 다른packet·DATA_DISCONTINUITY·장치 위치gap은 계속 분리하는 최소 diff를 TEMP `proposed-media.patch`에 준비했다. 정본 파일에는 적용하지 않았다. 승인10파일만으로 이를 '시각 발명/잘못된quality/16MiB초과block' 없이 우회할 수 없다.
2. **B008 표현.** 지원 최대768000×64×4에서2×P=78,643,200B(75MiB)다.128MiB cap 도달 대신 지원 최대75MiB·상한128MiB 이하를 확인하는 것으로 B8·전체1,526을 유지하는 안이다. 수학적으로 정해지는 결과이며 제품 예산식을 바꾸지 않는다.
3. G-P17a push 신호 뒤 새HEAD로 다시 고정해 신규·관련·UI·변이·측정·CI 동등 coverage와 전수 회귀를 마친 뒤 IMPLEMENTATION_READY를 보고한다. 아직 CI 동등 전수/coverage를 실행 완료했다고 주장하지 않는다.


## 13. C00 추가 범위·B008 승인 반영

C00은 §12.3의 두 요청을 승인했다. 쓰기 범위는 기존10파일에 `src/recoryn/app/media.py`를 추가한11파일이다. G-P10도 이 파일을 쓰므로 GS-P06의 미상 시각 packet 연속 fragment 보존 변경을 그 단위에 인계한다. 앞 §1~12는 이력으로 원 바이트를 보존한다.

- **M 계약 유지:** 분할은 저장 단위 사정이므로 분할/비분할의 clip 수·경계·시각 품질이 같아야 한다. 같은 bundle의 검증된 연속 byte/frame 범위에서 session·track·epoch·sequence·fragment_count·format·quality·상태 flag·arrival가 같고 index가1씩 증가할 때에만 packet 내부 연속으로 본다. 장치 위치가 알려졌으면 frame 수만큼 정확히 이어져야 하고, 둘 다 없으면 검증된 파일/frame 연속성만 사용하며 시각은 unknown 그대로다. 한쪽만 위치가 있거나 mid-packet 사건 flag·quality·상태 flag 변화가 있으면 나눈다. packet 첫 fragment의 사건은 그 packet 앞의 경계이므로 뒤 fragment까지 복제하지 않는다. 미상인 다른 packet을 합치거나 시각을 발명하지 않는다. 기존 상관 시각의 packet 간 연속 동작은 유지한다.
- **독립 oracle 보강:** 기존 M12의 분할/비분할 대조와 함께 손 기대(미상이면 packet별2clip·offset None, 상관이면 불연속 없음1clip/있음2clip·offset0, 총2Nframe·원본 PCM·정규화 source frame 경계)를 확인한다. 허용 범위·flag·quality·위치·packet 경계를 실제 seal/prepare_clips로 확인하는 X-M 보강행을 별도 감사한다. 기존 media/export 시험 단언 변경0이다.
- **B008 교체 문구:** 지원 최대768000Hz×64ch×4B에서2×P=78,643,200B(75MiB)이며128MiB 상한 이하다.128MiB cap은 지원 범위 밖 방어다. 제품 예산식과 B8·전체1,526행은 바꾸지 않는다.
- **검증 순서:** G-P17a push 전에는 현재 HEAD3566862에 승인 G-P17a9파일과 GS-P06 11파일만 더한 TEMP 사본에서 중간 검증한다. 최종 IMPLEMENTATION_READY는 G-P17a push 신호 뒤 새 HEAD를 고정하고 전수 검증한 다음 보고한다. 핵심 증거는 C00이 읽을 수 있도록 build의 새 gs06-evidence 폴더와 이 문서에 남긴다.


### 13.1 승인 반영 중간 검증 — G-P17a push 신호 대기

현재 상태는 **PRE_PUSH_VALIDATED**다. SCOPE_NEEDED 두 건은 위 C00 결정으로 해소됐고 app/media.py 변경까지 구현했다. 아직 최종 IMPLEMENTATION_READY는 아니다. 중간 격리 입력은 HEAD `35668622a8c2471315e838ddd42e098a9de39aa2` + G-P17a9파일(FIX2) + GS-P06 11파일이다. 부모·자식 media import가 모두 사본 src임을 확인했다. 제품/시험 실행 입력 해시는 아래 build 증거의 phase1-inputs.json에 고정했다.

- **새 시험:** 262 PASS·28.98초(60초 게이트 이내), 기존 WASAPI60행은 이 선택 명령에서 deselect이며 신규 skip은 없다. 주 분모1,526행이 실행 node247개(S1280은1node)이며, 별도 X3+XM12=15node를 합쳐262다. ID 누락·예상 밖·중복0이다. M12의 손 기대와 M005~008이 모두 PASS다.
- **새 media 구현:** 같은 bundle에서 strict scan으로 검증된 byte/frame 연속 fragment만 묶는다. 상관 시각은 기존 clock-step 조건도 지켜 가짜 점프를 같은 packet이라는 이유로 합치지 않는다. 미상 시각은 끝까지 None이며, 실제 WAV PCM·clip 수·quality·offset·duration·정규화 source frame 경계를 손 기대와 비교했다. quality·상태 flag·mid-packet 사건·위치 gap/부재·arrival·clock jump 보강12행도 실제 seal→prepare_clips로 검증했다. packet 첫 사건은 packet 앞의 경계라 뒤 fragment에 복제하지 않으며, mid-packet 사건은 경계로 유지한다.
- **기존 회귀:** media·STT 입력·건강 export·WASAPI157 PASS·4.98초. 기존 세 파일(test_media·test_stt_input_independent·test_health_export)의 diff0이며 단언 변경0이다. G-P08 건강 unit/property/integration·capture·app_service1,157 PASS·49.53초다. 중간 실행은 모두 `-p no:cacheprovider -W error::ResourceWarning`, offscreen, 고유 TEMP basetemp다.
- **변이:** 계획 MU01~18은 현 코드 사본에서18/18 재검출했다. media의 허용/거부 경계를 확인하는 별도 XMUT01~08도8/8 검출했다(계획18의 분모에 합치지 않는다). XMUT07은 사건 guard 두 군데를 함께 제거하는 복합 변이임을 changes에 기록했다. 수집 실패·timeout은 검출로 세지 않았다. 사본 pyproject/src/tests를 함께 복사했다.
- **정적 검사:** ruff check·format check(217파일)·mypy src/recoryn scripts packaging(95source) PASS다.
- **B008 정정:** 원문 §3.5의 '상한 포맷128MiB'와 B 표의 '128MiB 도달'은 이 승인으로 대체된다. 실제 지원 최대는75MiB이고128MiB cap은 지원 범위 밖 방어다. 예산식·B8·전체1,526은 불변이다. B008은 실제 기본 queue 설정과16MiB 초과 packet 수락·저장까지 PASS다.

C00이 private TEMP를 읽지 못한 문제를 피하도록 핵심 증거를 **build/gs06-evidence-c0c04699d2/**에 내보냈다. gate.xml/log·case-audit.json·media-regression.xml/log·related.xml/log·정적 검사 로그·변이별 입력과 결과/로그·실행 입력 해시·현재11파일 사본·diff를 포함한다. 이전 M4 실패와 앞 단계 측정은 history-before-approval에 별도 이력으로 보존했고 현재 PASS와 혼합하지 않는다. README.md에서 재현 명령과 파일별 의미를 안내한다.

G-P17a push 신호 뒤 새 HEAD와11파일 해시를 다시 고정하고, 신규·관련·UI전체·변이·1/2트랙 HEAD 대조·CI 동등 coverage/check_coverage·전체 오프라인 회귀를 최종 실행한다. 현재 단계에서 그 최종 결과를 완료로 주장하지 않는다. G-P17a 저장3모듈이나 다른 단위 파일은 이 승인 반영 과정에서 수정하지 않았다.


## 14. G-P17a push 뒤 최종 검증 입력 고정

C00이 G-P17a `6156b65` push 신호를 보냈다. 최종 기준은 full HEAD `6156b6514116be510426efed69bfd549e876b345`(G-P13 `3566862` 포함)다. archive 원본 사본과 여기에 GS-P06 승인11파일만 더한 사본을 만들고 파일별 HEAD/제출 LF 해시를 `build/gs06-evidence-c0c04699d2/final-inputs.json`에 고정했다. G-P17a9파일은 별도 overlay하지 않으며 새 HEAD에 포함된 것을 그대로 쓴다. 미완성 G-P12b 등 다른 작업 트리 변경은 복사하지 않는다. GS-P11a의 library.py는 읽기만 한다.

신규 묶음은 단독 시간 게이트60초, 1·2트랙 HEAD 대조 측정은 다른 자체 시험과 겹치지 않고 실행한다. 계획 MU18·별도 media 보강8은 모두 새 입력 사본으로 재검증한다. 전체 오프라인 회귀를 CI 동등 coverage 명령으로 실행하며, 전체 UI·G-P04/05/07/08/15/17a·media/export 회귀를 그 전수에 포함해 직접 JUnit으로 계수한다. 부모·자식 import 경로와 coverage 파일 경계를 확인한다. 새 fixture 적응이 범위 밖에서 필요하면 실제 실패를 먼저 보고한다.


### 14.1 최종 기준에서 직접 확인한 선행 결과

- 신규 묶음 **262 PASS·30.11초**, 기존 WASAPI60행은 선택 제외다. 주 분모1,526행·실행262node(주247+보강15), 누락·예상외·중복0. M005~008을 포함한 M12 PASS이며 최종 전체 회귀에서도 다시 실행한다.
- 계획 변이 MU01~18 **18/18 검출**, media 보강 XMUT01~08 **8/8 검출**. 입력과 목표 node·실제 AssertionError/기대 예외 미발생을 로그로 남겼으며 수집 오류·timeout은 검출로 세지 않았다. XMUT07은 명시한 사건 guard2곳의 복합 변이다.
- ruff check·format check·mypy PASS. 실행 사본의 제품/시험/스크립트/packaging diff를 archive baseline과 직접 대조했고 승인11파일 밖 변경0이다(`final/scope-audit.json`). 부모·자식 wasapi import는 사본 src다.
- 아래 측정은 `final/probe_g17.py`(검토자 원 스크립트 복사)로 각12초·트랙당100blocks/s·480frame·기본2초 chunk·250ms GUI tick 모사를 썼다. 외부 SQLite잠금0·추가fsync지연0·tombstone0이며 실제 장치/음성은 쓰지 않았다. 1트랙은HEAD→GS06,2트랙은GS06→HEAD 순서로, 다른 자체 시험·변이와 겹치지 않았다. 모두 저장=수락·정상stop·tick오류0·gap0이었다.

| 트랙 | 대상 | 거부 | 저장frame | writer root p99/최장(ms) | sealer root 최장(ms) |
| --- | --- | --- | ---: | --- | ---: |
| 1 | HEAD6156b65 | 0 | 576,000 | 1.19 / 3.71 | 4.48 |
| 1 | GS06 | 0 | 576,000 | 1.18 / 4.00 | 3.04 |
| 2 | GS06 | mic0/system0 | 1,152,000 | 1.01 / 10.38 | 3.85 |
| 2 | HEAD6156b65 | mic0/system0 | 1,152,000 | 1.08 / 6.34 | 3.70 |

이 유한 측정으로 모든 디스크·장기세션의 거부0을 보장하지 않는다. PER_BLOCK 소비자 처리량 문제는17b 범위다. 대조 원시 JSON·각 실행 stdout·명령/시간은 build 증거 final/measurements.json·measure-*.log에 보존한다. 최종 CI 동등 전체 회귀가 진행 중이므로 아직 IMPLEMENTATION_READY는 아니다.


### 14.2 CI 동등 전체 오프라인 검증 완료

정확한 `6156b6514116be510426efed69bfd549e876b345 + GS-P06 11파일` 사본에서 Python3.13.1·Windows·offscreen으로 아래 명령을 직접 실행했다. PYTHONPATH는 사본 src, COVERAGE_FILE과 basetemp는 고유 OS TEMP로 고정했다.

```text
python -m pytest -q -p no:cacheprovider -W error::ResourceWarning --cov=recoryn --cov-branch --cov-report=json:coverage.json --cov-fail-under=85 --basetemp=<고유OS_TEMP>/ci-bt --junitxml=<증거>/final/ci.xml
python scripts/check_coverage.py coverage.json
```

**28,503 PASS / failure0·error0·skip0 / 경고 요약 없음**, pytest **2,141.11초**, process **2,155.42초**다. combined coverage는 **92.56%**이고 아래7묶음이 모두 PASS다. coverage.json의82파일은 전부 사본 src/recoryn 아래이며 작업 트리 src·TEMP fixture 혼입0이다.

JUnit 직접 합산: contract56·e2e81·integration5,453·property14,457·release363·**UI전체3,281**·unit4,812. 전체 기본 오프라인 수집을 실행해 G-P04/05/07/08/15/17a와 media·STT·export·WASAPI 회귀를 모두 포함했다. 예를 들어 미확정 세션340/복구49·pending deletion141/재시작137·seal mutex102·append 네 파일1,205·capture start UI493·track health unit/integration911·health case-space168·health UI43·health export11·기존 media11·STT 독립60이 실제 JUnit에 있다. 이는 문서의 과거 숫자를 옮긴 값이 아니다. 개별 명세는 final-audit.json에 보존한다.

전체 실행에서도 주 분모1,526 ID를 독립 기대 집합과 다시 대조해 누락·예상외·중복0이다(full-case-audit.json). 신규262node(보강15 포함)는 전수 안에서도 모두 PASS다. 실행이 끝난 뒤 archive baseline과 소스를 다시 대조해 승인11파일 밖 제품/시험/스크립트/packaging 변경0이며, 제출 제품·시험10파일은 검증 사본과 바이트 단위로 같다.

check_coverage 출력 전문:

```text
domain: line=99.18%/95% branch=97.89%/90% PASS
capture: line=99.73%/95% branch=98.29%/90% PASS
jobs: line=99.20%/95% branch=95.65%/90% PASS
storage: line=96.21%/95% branch=91.55%/90% PASS
security: line=98.11%/95% branch=94.43%/90% PASS
content: line=98.98%/95% branch=99.02%/90% PASS
all: line=93.89%/85% branch=88.59%/80% PASS
```

ruff check·format check(217파일)·`mypy src/recoryn scripts packaging`(95source)도 최종 사본에서 모두 PASS다. 원시 로그·JUnit·coverage JSON·변이·측정·명령/시간·경계 감사는 **build/gs06-evidence-c0c04699d2/final/**에 저장했다. 기존 중간 검증과 최종 결과를 구분하며, 이 최종 전체 실행은1회다.

### 14.3 제출 파일·검토 인계

현재 상태는 **IMPLEMENTATION_READY**다. 승인 범위11파일 모두 HEAD 대비 변경이며 제품7·시험3·문서1이다. 새 파일은 두 packet 시험과 이 문서3개다. app/media.py 추가와 B008 수정은 C00 승인대로 반영했다. 원 계약과 앞 단계 결과는 이력으로 보존했고, 기존 media/export 시험 단언 변경0이다. G-P17a 소유의 chunks.py·_coordination.py·library.py와 다른 작업자 파일은 수정하지 않았다.

| 제품/시험 파일 | SHA256(LF) |
| --- | --- |
| `src/recoryn/capture/queue.py` | `b73673e3bc9033a6aa9672d20c7c67d7dc241a73c93af30199712153695693d1` |
| `src/recoryn/capture/wasapi.py` | `ec9a5ba1c81bfe35634b15193552b4a5e433a72da545b22a5bc2ad777ed6384e` |
| `src/recoryn/app/recording.py` | `2289f5e5cad05e27addd01ed8171654a119dc3b90213df61bd59e8751648e474` |
| `src/recoryn/app/desktop.py` | `5744c21aac44d0fd9b0286076230bf216ee5a20f4b64e47a74437e3bdaaa0b02` |
| `src/recoryn/domain/__init__.py` | `1fbba261bc49ae45f5c1aa2b9f36d6783d4e18f5207db34ed6358c0ecf329ed5` |
| `src/recoryn/storage/_safe.py` | `5f368d98c8f3c86617af4aa44e82d26cdd8cb236a7551b4745228aaaf3761eb0` |
| `tests/unit/test_packet_split.py` | `bc08f440cbea6ecda3cbc5f5eb97097117603f1f7594aca283b136ce1222c655` |
| `tests/integration/test_packet_split.py` | `39da6f7c9c3de36695223b6ce899f990aeb47aae9fa8406e009787ce1bb84f2a` |
| `tests/unit/test_wasapi.py` | `37917d025c9008cbd3c3558f070ec5bb005b8726477842b71efc62dba08d2cbf` |
| `src/recoryn/app/media.py` | `6512a12078b692c7f8296d756a5340be560497ffc3c448212946612c1928f330` |

문서 자체 최종 해시와 전체11파일 명세는 이 창 및 `final/delivery-hashes.json`에 보고한다. 검증 시점 문서의 해시는 final-inputs.json에 남기고, 실행 후 결과 절만 추가한 최종 문서 해시와 구분한다. 공유 검토자를 위해 최종11파일 사본도 build 증거의 final/submitted/에 내보냈다.

- 독립 검토/통합 승인 전이며 작성자가 자체 최종 승인하지 않는다. 현재 작성자 확인의 구현 미해결0이다.
- 실제 큰 WASAPI packet 발생률·장치·실음성·HDD/백신·장기세션·상한 포맷 메모리 압박은 NOT_RUN이며 외부 게이트다. 12초 모사 결과로 그 전체를 보장하지 않는다. 실제 모델·네트워크·다운로드·설치·vault 쓰기는 실행하지 않았다.
- G-P10 인계: media의 미상 시각 연속 fragment·사건/위치/시각 품질 경계와 source frame mapping 보존을 유지해야 한다. G-P17b 인계: 원자 packet 수락과 소비자 last-fragment checkpoint·packet 끝 회전 규칙, 기존 G17R-05 후속은 별도다.
- GS-P11a는 C00의 다음 시작 신호 전까지 계약 재대조만 한다. 이번 단위에서 library.py의 삭제 권위·cache 정책은 바꾸지 않았다.
