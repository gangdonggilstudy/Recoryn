# GS06 / GS-P06 큰 캡처 packet frame 정렬 분할 독립 검토

2026-11-26, 검토자 Claude(C00 지정 하위 에이전트, G-P08 검토자). 계약은 w5:p7 Claude, 구현은 w5:p8 Codex다. 검토자는 이 단위의 코드·시험·계약을 쓰지 않았다. 이 문서 외에는 저장소 파일을 고치지 않았다. Git 쓰기·네트워크·설치·실장비 캡처·실음성·추가 에이전트는 사용하지 않았다.

**판정: OPEN 1건 — S0 0 / S1 0 / S2 0 / S3 1.** S0·S1이 없으므로 이 기준으로는 push를 막지 않는다. C00 승인 조건 (1)~(9)는 모두 직접 확인했다.

## 1. 입력 고정과 범위

- 대상은 tree **`3d708d3c6ea5bfa4a23b0c6cc29d44228e12e845`**(HEAD 6156b65, G-P17a까지)다. `git diff --stat 6156b65 3d708d3c`는 **11파일, 1704 insertions / 79 deletions**로 배정 목록과 같다.
- `storage/chunks.py`·`storage/library.py` 등 G-P17a 저장 모듈의 변경은 0이다(조건 (7)).
- 배정의 해시 접두 8개(`queue.py b73673e3`, `wasapi.py ec9a5ba1`, `recording.py 2289f5e5`, `desktop.py 5744c21a`, `media.py 6512a120`, `domain/__init__.py 1fbba261`, `_safe.py 5f368d98`, 계약 `9f5170bc`)는 LF SHA-256과 모두 일치했다.
- 실행 위치는 다음과 같다.
  - 판정: `git archive 3d708d3c | tar -x -C build/review-trees/gs06`
  - 기준 비교: `git archive 6156b65` → `gs06-base`
  - 변이: `gs06-mut`(pyproject·src·tests·scripts·packaging 사본)
  - 모든 실행에 `PYTHONPATH=<사본>\src`를 고정했다. 회귀 시작 시 `recoryn`·`capture.queue`·`app.media`의 `__file__`이 사본 안임을 기록했다. 반례는 `-I -B`와 import 위치 assert로 실행했다. 변이 harness는 자식 import origin(`gs06-mut\src\recoryn\__init__.py`)을 assert했다.
  - basetemp는 OS TEMP(세션 scratchpad) 아래다.
- 실제 장치·실음성은 쓰지 않았다. 모든 packet은 `NativePacket`/`split_packet` 또는 `PCMBlock`으로 만든 합성 입력이다.

## 2. 실행 결과

공통 조건: `.venv\Scripts\python.exe`(Python 3.13.1), `QT_QPA_PLATFORM=offscreen`, `PYTHONDONTWRITEBYTECODE=1`, `HF_HUB_OFFLINE=1`, `-p no:cacheprovider`, 실행별 새 basetemp(OS TEMP).

| ID | 명령 | 결과 |
| --- | --- | --- |
| R1 | CI 동등 전체(`run-full.sh`: `pytest -q -p no:cacheprovider -W error::ResourceWarning --cov=recoryn --cov-branch --cov-report=json:coverage.json --cov-fail-under=85`) | **완료하지 못함.** 다른 에이전트의 전체 회귀·검토자 변이와 동시에 돌던 중, 약 1% 지점(G-P17a의 `tests/integration/test_append_fencing.py::test_registration_busy_keeps_live_capabilities_and_withholds_pause_ack`)에서 20분 이상 CPU 진행 0으로 멈췄다. 검토자가 만든 이 pytest만 종료했다. §6 관찰 참조 |
| R2 | R1과 같은 명령 + 진단용 `-o faulthandler_timeout=900`만 추가(`run-full-fh.sh`) | **28,503 passed, 0 failed, 0 skipped, 2205.23초, exit 0.** 결합 coverage 92.56%. faulthandler 출력 없음 |
| R3 | `python scripts/check_coverage.py coverage.json` | 7묶음 PASS: domain 99.18/97.89, capture 99.73/98.29, jobs 99.20/95.65, storage 96.21/91.55, security 98.11/94.43, content 98.98/99.02, all 93.89/88.59 |
| R4 | `ruff check .` | All checks passed |
| R5 | `python -m mypy src/recoryn scripts packaging` | Success: no issues found in 95 source files |
| R6 | 신규 2파일 단독(`-W error::ResourceWarning`, 다른 Python 프로세스 없음) | **247 passed in 21.13초**(runner 22초). 다른 전체 회귀와 겹친 첫 측정은 38.26초 |
| R7 | `test_append_fencing.py` 파일 전체, 기준·GS06 교대 4회씩(`repeat_fencing.sh`, `faulthandler_timeout=180`) | 8회 모두 173 passed(41~63초), 멈춤 0 |

R2는 작성자 보고(28,503 PASS)와 같다. 이전 G08 검토의 skip 2건(D: 볼륨 8.3 이름)은 basetemp를 C: OS TEMP로 둬 이번에는 없다.

## 3. 요청 항목별 판정

### 3.1 원자 수락(조건 (1))

`probe_atomic.py` 결과다.

| 항목 | 입력 | 관측 | 판정 |
| --- | --- | --- | --- |
| A1 slot 경계 | `BoundedCaptureQueue(4, 600)`에 단일 2개 뒤 3-fragment packet | 2+3>4라 packet 전체 거부(dropped_blocks 3, frames 150, bytes 300). 이어서 2-fragment packet은 수락(queued 4) | 전부 또는 전무 |
| A1 byte 경계 | `(16, 300)`에 정확히 300B packet, 이어 +4B packet | 300B 수락, 초과 packet 전체 거부(dropped_blocks 2, bytes 4) | 같음 |
| A2 두 producer 경쟁 | 서로 다른 트랙 2 thread × 3,000 packet(3 fragment), 7 slot queue, 동시 consumer | 소비 fragment 36개 중 불완전·순서 어긋난 packet 0, packet 안 다른 트랙 끼어듦 0, accepted/dropped 계수 = 관측 | 같음 |
| A3 gate 닫힌 뒤 late tuple | pause 뒤 `submit(tuple)` | False, accepted·dropped 변화 0 | G-P08 의미 유지 |
| A4 잘못된 tuple(다른 sequence 혼합) | `submit` | `ValidationError`, 회계·queue 변화 0 | 회계 0 |
| A6 stop 중 계속 제출 | producer thread가 3-fragment tuple을 제출하는 동안 `stop()` | FINALIZED. 저장 bytes = 수락 packet bytes를 이은 값, 모든 chunk strict scan 통과, 건강 수락 frame 900 = 입력 300×3 | 불완전 packet 저장 0 |

- 큐의 `_offer`는 slot·byte 검사, 추가, 회계를 한 condition 구간에서 한다(`src/recoryn/capture/queue.py:95-118`).
- `RecordingService.submit`은 tuple 검증(`packet_blocks`)을 gate 진입 전에 하고, gate 안에서 `offer_packet`을 한 번 부른다(`src/recoryn/app/recording.py:536-566`).
- 변이 R01(slot 검사를 단일 block 식으로), R02(drop frame을 fragment 0만), R11(identity에서 sequence 제외)은 모두 KILLED다(§4).
- 예외 경로 하나는 GS06R-01로 남겼다. 단일 `PCMBlock`으로 넘긴 fragment(`fragment_count>1`)나 16MiB 초과 block은 검증 없이 수락된다.

### 3.2 저장 규칙과 복구(조건 (4)(5))

- **뒤 fragment 시각.** `capture_ns + offset×10⁹ // sample_rate` 정수식이고 quality는 packet과 같다. 위치·시각이 2⁶³ 이상이면 그 fragment부터 None이다(`src/recoryn/capture/wasapi.py:73-154`). 변이 R04(뒤 fragment가 packet 시작 시각 재사용)는 1,280행 산술 시험이 검출했다.
- **flag.** 상태 flag(SILENT·TIMESTAMP_ERROR)는 모든 fragment에, 사건 flag(DATA_DISCONTINUITY·RAW_*)는 fragment 0에만 둔다. 변이 R03(사건 flag 전 fragment 복제)은 KILLED다.
- **불완전 마지막 packet.** G-P17a의 `scan_prefix`가 비엄격이면 마지막 완결 packet까지 자르고, 엄격이면 `Incomplete final packet fragments`로 거부한다(`src/recoryn/storage/chunks.py:259-264`). 이 경로는 변경되지 않았고 GS06-C 6행이 실제 `ChunkWriter`로 확인한다.
  - A6에서 stop과 경쟁해도 strict scan이 모두 통과했다. 소비자는 packet 끝에서만 chunk를 넘기고(`recording.py:675-681`), seal은 불완전 packet을 거부한다.
- **16MiB 최종 방어.**
  - 정본은 domain의 `MAX_PCM_BLOCK_BYTES`이고, `storage/_safe.py`의 `MAX_BLOCK_BYTES`가 같은 값을 재노출한다(조건 (3)).
  - `validate_fragments`가 fragment마다 16MiB를 검사한다. writer의 기존 16MiB 검사는 그대로다.

### 3.3 건강(조건 (6), G-P08 연결)

- **packet 이벤트.** WASAPI worker는 packet당 `packet` 이벤트를 1개 내고 `frame_count`(packet 전체)·`fragment_count`를 싣는다(`wasapi.py:483-494`).
  - 변이 R10(frame_count를 fragment 0 값으로)은 GS06-H-007이 검출했다.
  - Desktop `_on_health`의 CAPTURE_PACKET_FLAGS 경고도 packet당 1회다.
- **QUEUE_DROP.** 거부 packet은 `dropped_frames += N`이고 gap은 하나다. 범위는 fragment 0 위치부터 N frame이다.
  - 이후 위치 기준이 `position + N`이므로 다음 packet이 거짓 불연속을 만들지 않는다.
  - 변이 R05(서비스 회계가 fragment 0만)는 GS06-R-013, R12(fragment마다 checkpoint)는 GS06-G 계열이 검출했다.
- **G-P08 미상≠0.** 위치가 2⁶³을 넘으면 None이 되어 G-P08의 위치 근거 없음 → 장치 유실 미상 경로를 탄다(`recording.py:573-574`, `_observe_block`의 else 분기). TIMESTAMP_ERROR packet은 fragment 0의 상태 flag로 BAD_CLOCK과 미상 표시가 유지된다.

### 3.4 app/media.py(조건 (8))

`probe_media_partition.py`로 손 oracle을 확인했다.

입력은 한 트랙 48kHz mono s16 packet 10개(각 480 frame)다. 표시한 packet은 `split_packet(max_block_bytes=320)`으로 160 frame씩 3분할했다. 시각은 위치와 일치하는 QPC다.

| seq | 성질 |
| --- | --- |
| 0 | 정상, 비분할 |
| 1 | 정상, 분할 |
| 2·3 | TIMESTAMP_ERROR, 분할 |
| 4 | 정상, 비분할 |
| 5 | DATA_DISCONTINUITY, 분할 |
| 6 | 정상, 분할 |
| 7 | RAW flag 8, 분할 |
| 8 | 위치 +100 점프, 분할 |
| 9 | SILENT, 분할 |

**GS06 결과 — clip 8개**

| clip | 구성 | offset_ms | 시각 |
| --- | --- | --- | --- |
| 1 | seq 0 + seq 1의 3조각 | 0 | correlated |
| 2 | seq 2의 3조각 | None | unknown |
| 3 | seq 3의 3조각 | None | unknown |
| 4 | seq 4 | 40 | correlated |
| 5 | seq 5 + seq 6 | 50 | correlated |
| 6 | seq 7 | 70 | correlated |
| 7 | seq 8 | None | unknown |
| 8 | seq 9 | None | unknown |

seq 8의 위치·시각 점프는 기존 clock-jump 규칙으로 이후를 미상 처리한다. 기준 tree와 같은 규칙이다.

**기준 tree 결과(같은 chunk 사본) — clip 15개.** 미상 packet이 fragment마다 clip으로 쪼개진다(seq 2·3·8·9가 각 3개). RAW packet seq 7은 seq 5·6 clip에 합쳐진다.

**판정**

- 차이는 두 가지뿐이고 둘 다 조건 (8)의 의도와 맞는다.
  - 같은 packet의 검증된 연속 fragment가 unknown 그대로 묶인다.
  - 사건 flag(RAW)가 경계가 된다.
- 다른 packet을 합친 경우는 0, 시각을 발명한 경우는 0이다. unknown clip의 offset·source range 시각은 모두 None이다.
- `cli._export` 결과 WAV 9개의 SHA-256은 두 tree에서 완전히 같다. export 불변이다.
- 변이 R07(`contiguous` 조건 제거)·R08(뒤 fragment 사건 flag 허용)은 생존했다. 둘 다 동치 변이로 판단한다.
  - R07: 한 packet은 한 chunk 안에서만 연속 기록된다(소비자 hand-off·seal·`_next` 보장). 그래서 같은 identity·index+1이면서 비연속인 저장 자료가 만들어지지 않는다.
  - R08: `split` 식의 `bool(set(flags) − 상태 flag)`가 사건 flag를 따로 경계로 만든다. 그래서 continuation guard 하나를 지워도 동작이 같다. 작성자 XMUT07이 두 guard를 함께 지운 복합 변이로 검출한 것과 일치한다.

### 3.5 예산식 경계(조건 (2)(9))

`queue_byte_budget` 직접 계산이다.

| 포맷 | 2×P | 예산 |
| --- | --- | --- |
| 48kHz×1ch×s16 | 0.04MiB | **16MiB** |
| 48k×2×f32 | 0.15MiB | 16MiB |
| 192k×8×s32 | 2.34MiB | 16MiB |
| 384k×32×f32 | 18.75MiB | **18.75MiB** |
| 768k×64×s16 | 37.5MiB | 37.5MiB |
| 지원 최대 768k×64×f32 | 75.00MiB | **75.00MiB** |

- 768001Hz·65ch은 `AudioFormat`이 거부하므로 128MiB 상한은 지원 범위 밖 방어로만 남는다(B008 대체 문구와 일치).
- 빈 목록·비포맷 입력은 ValidationError다.
- 메모리 영향: queue는 backlog가 있을 때만 그만큼 쓴다. 일반 포맷은 종전 16MiB 그대로다. 지원 최대 포맷에서 최악 75MiB다.
- 변이 R09(2P→P)는 GS06-B-002가 검출했다.

### 3.6 1·2트랙 녹음 거부 측정(기준 6156b65 대비, 순차 교대)

- 도구: `probe_recording_load.py`(G08 검토와 같은 도구).
- 조건: 8초, 10ms(480 frame) 실시간 pacing, 중간 pause/resume 1회. 관리 thread는 다른 세션 create/delete·list·inventory·pending deletions·Job claim/fail/resume이다.
- 실행 순서: 기준→GS06을 1트랙·2트랙에 대해 2라운드 교대했다. 다른 Python 프로세스는 없었다.

| 지표 | 기준 | GS06 |
| --- | --- | --- |
| 거부 블록(8실행 모두) | 0 | 0 |
| 저장 frame = 수락 frame | 모두 일치 | 모두 일치 |
| submit 최대 | 0.061~0.079ms | 0.068~0.095ms |
| writer root 보유 최대 | 3.27~4.72ms | 2.58~4.51ms |
| sealer root 보유 최대 | 3.24~3.95ms | 3.19~4.83ms |
| capture gate 최대 | 0.105~0.167ms | 0.112~0.157ms |

이 부하는 비분할(K=1) 경로다. submit의 0.02ms 내외 증가는 tuple 판별·검증 비용으로 보인다. 분할 packet의 실시간 부하는 측정하지 않았다(§7).

G07R-01 반례(`probe_stop_inflight.py`·`probe_two_track_stop.py`)도 같은 결과다: 정지 중 in-flight PCM 수락, 저장 1440·1440, system 2880.

## 4. 변이(검토자 독립 12개)

`mutate_gs06.py`. 정상본(새 2파일 + test_wasapi·test_media·desktop_independent·unit desktop·app_service·track_health)은 **764 passed, 99.4초**다. 검출로 센 것은 rc 1이면서 요약에 failed가 있고 error가 없는 경우뿐이다.

| 변이 | 결과(검출 시험) |
| --- | --- |
| R01 slot 검사 `len >= max` | KILLED(GS06-A-049) |
| R02 drop frame을 fragment 0만 | KILLED(GS06-A-037) |
| R03 사건 flag 전 fragment 복제 | KILLED(S 1,280행) |
| R04 뒤 fragment 시각을 packet 시작으로 | KILLED(S 1,280행) |
| R05 서비스 회계가 fragment 0만 | KILLED(GS06-R-013) |
| R06 Desktop 수락 frame이 fragment 0만 | KILLED(GS06-W-013) |
| R07 media contiguity 조건 제거 | SURVIVED(동치, §3.4) |
| R08 media 뒤 fragment 사건 flag 허용 | SURVIVED(중복 guard, §3.4) |
| R09 예산 2P→P | KILLED(GS06-B-002) |
| R10 건강 이벤트 frame_count를 fragment 0으로 | KILLED(GS06-H-007) |
| R11 packet identity에서 sequence 제외 | KILLED(GS06-T-008) |
| R12 fragment마다 checkpoint | KILLED(GS06-G 계열) |

**10 KILLED / 2 SURVIVED(동치) / 0 INVALID.** 작성자 MU01~18·XMUT01~08은 재실행하지 않았다.

## 5. 발견

### GS06R-01 / S3 / OPEN — 단일 PCMBlock 경로가 "packet 전체" 불변식을 검사하지 않아 호출자 실수가 저장 실패(전 트랙 녹음 중단)로 바뀐다

**재현.** `probe_atomic.py` A5.

1. `RecordingService.submit`에 `fragment_count=2`인 fragment 0을 단일 `PCMBlock`으로 넘긴다 → 수락(True).
2. 다음 packet을 넘긴다 → 수락.
3. consumer의 `ChunkWriter.append`가 `ValidationError('Invalid block sequence/fragment boundary')`를 낸다.
4. 결과: `storage_failed=True`, `accepting=False`, 세션 INTERRUPTED, 다른 트랙도 녹음 중단.

같은 입력에서 기준 6156b65도 같은 결과다. **기존 동작이며 GS06 회귀가 아니다.** 16MiB 초과 단일 `PCMBlock`도 같은 경로를 탄다. queue 예산이 16MiB를 넘는 포맷에서는 queue를 통과해 writer에서 거부된다.

**근거.**

- `packet_blocks`는 `PCMBlock`을 `(item,)`으로 그대로 통과시킨다(`src/recoryn/capture/queue.py:39-44`).
- `offer()`도 fragment 수·크기를 보지 않는다.
- 계약 §3.3은 K=1 packet만 단일 `PCMBlock`으로 넘기도록 정했다. §3.1 I2는 "소비자와 writer는 불완전한 packet을 받지 않는다"이다.

**영향.** 제품 producer(`WasapiSource`는 tuple 사용, `SyntheticSource`는 단일 비분할 block)에는 도달 경로가 없다. 그래서 S3로 둔다.

**권고.** `packet_blocks`/`offer`에서 단일 `PCMBlock`이 `fragment_count==1`이고 payload가 `MAX_PCM_BLOCK_BYTES` 이하인지 확인하라. 위반이면 회계 0으로 `ValidationError`를 내야 한다. 호출자 실수가 writer의 최종 방어에서 전 트랙 중단으로 번지지 않게 하는 것이 목적이다.

## 6. 관찰(OPEN 아님)

- **G-P17a 시험의 1회 멈춤(GS06 회귀로 판단하지 않음).**
  - 상황: R1에서 `test_registration_busy_keeps_live_capabilities_and_withholds_pause_ack`(G17-R-03)가 20분 이상 진행이 없었다. 다른 에이전트의 전체 회귀와 검토자 변이 12개가 동시에 돌던 고부하 상태였다.
  - 재현 시도: 같은 시험 단독 3회×2 tree, 파일 전체 4회×2 tree(R7), 진단 옵션을 켠 전체 재실행(R2)에서 모두 재현되지 않았다.
  - GS06 변경 중 이 경로에 닿는 것은 단일 block의 기존 경로뿐이다. 시험 파일도 바뀌지 않았다.
  - 멈춘 프로세스의 스택은 얻지 못했다. 고부하에서만 나타나는 G-P17a 시험(또는 경로)의 경쟁 가능성으로 C00·G-P17 담당에 전달한다. 증거는 `gs06-probe/run1-hung/`(로그)와 basetemp의 마지막 시험 폴더 시각이다.

- **RAW flag 경계 변화.** 비분할 packet에서도 RAW_* flag가 이제 clip 경계가 된다. 기존 녹음의 clip을 다시 만들면 경계가 달라질 수 있다. 조건 (8)의 "사건 flag는 분리"에 해당하며 데이터 손실은 없다.
- **신규 시험 수 표기.** 신규 2파일 단독 수집은 247 node다. 작성자 표기 262는 test_wasapi의 GS06-H 등을 더한 수로 보인다. 분모 1,526 감사는 재계산하지 않았다.

## 7. 미검증

- 실제 WASAPI의 16MiB 초과 packet 발생률·상한 포맷 장치의 메모리 압박·장기 세션·HDD·백신 환경
- 작성자 변이 18+8 재실행, 1,526행 case-ID 재감사
- 2트랙 상한 포맷(75MiB 예산)에서의 실시간 backlog 메모리 측정

## 8. 반례·harness(LF SHA-256, `build/review-trees/gs06-probe/`)

| 파일 | SHA-256 |
| --- | --- |
| `run-full.sh` | `5e2210c8df23104fa9c1180f5dfa1dd40f3309a052195eeb53943c1d78dcb61b` |
| `run-full-fh.sh` | `74bacd1aeb6b1a42ec982bfcab05ae311e22d9d4b838452c02e6f97f54b44954` |
| `repeat_fencing.sh` | `cb68f55c852dab057bb3b07540559f8603638fb7b5df05e48407046812194acc` |
| `probe_atomic.py` | `76fb1bcb5b11d4b83de09d68645ecabb62c5173303f0145b31176591a51fc628` |
| `probe_media_partition.py` | `7f89071d9763fadcf11b9de06e5375f19a46b43bf8265c0f22c4f3711281b1d7` |
| `mutate_gs06.py` | `85193414e1366302070c9ce6638eec77a68bc5beaee379b159483241116f4da1` |
| `probe_recording_load.py` | `3de98b86ba67439254201a89a57db842fe88ac461c5690d5eccf2c3a3af4790f` |
| `probe_stop_inflight.py`(G07 원본) | `734047d102c12aa6a941bdfc4b6d1e77d7edf5bc4117c7796ce2ee4112684adb` |
| `probe_two_track_stop.py`(G07 원본) | `a09d994d200f8660ad3cabe565656a5ca806d52ed0520483ad28cbb9460ff40c` |
