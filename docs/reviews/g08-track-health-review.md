# G08 / G-P08 트랙 건강·UNKNOWN_TAIL 독립 검토

2026-11-24, 검토자 Claude(C00 지정 G-P08 독립 검토 하위 에이전트). 작성자는 w5:p8 Codex다. 검토자는 이 단위의 코드·시험·계약 문서를 작성하지 않았다. 이 문서 외에는 저장소 파일을 고치지 않았다. Git 쓰기·네트워크·설치·실장비·모델·유료 호출·Credential Manager 쓰기·herdr 조작·추가 에이전트는 사용하지 않았다.

**판정: OPEN 10건 — S0 0 / S1 2 / S2 1 / S3 7.** S1이 열려 있으므로 이 기준으로는 **push를 막는다.** 수용과 통합은 C00이 결정한다.

1. **G08R-01(S1):** 녹음 중 v2 호환 요약(`sessions.capture_health`)이 기존 64KiB JSON 상한을 넘는다. 그러면 기회성 checkpoint 실패가 writer 실패로 처리된다. 두 트랙 녹음이 함께 멈추고 세션은 INTERRUPTED가 된다. 같은 입력에서 기준 tree는 녹음을 멈추지 않는다.
2. **G08R-02(S1, 판정 기준에 따름):** 장치 위치 연속성 근거가 끊긴 뒤의 장치 누락을 미상으로 남기지 않는다. 대신 "확인된 장치 유실 0 · 같은 좌표의 확인된 유실 union 0"으로 표시하고 영속한다. 끊기는 경우는 위치 없음, 또는 TIMESTAMP_ERROR packet 다음이다.
3. **G08R-03(S2):** legacy 세션 UNKNOWN_TAIL 수선이 track/epoch마다 별도 transaction이다. 중간 실패 뒤 재복구가 남은 tail을 만들지 않으면서 RECOVERED_UNCLEAN(성공)으로 보고한다.

다음 반례는 찾지 못했다(근거는 §4).

- 정지·일시정지 중 in-flight PCM 거부(G07R-01 회귀)
- backend packet 통지로 QUEUE_DROP을 이중 계상하는 경로
- WRITER_ACK_PENDING·sealer 미완료·source ACK 없음에서 CLOSED를 기록하는 경로
- 삭제 의도가 tail commit보다 먼저일 때 건강 쓰기나 미디어 채택이 일어나는 경로
- 녹음 중 다른 세션 관리 작업 때문에 거부·유실이 기준보다 늘어나는 경우(정상 부하, 1·2트랙)
- suspend 뒤 자동 resume
- 기준 라이브러리 업그레이드 실패

## 1. 입력 고정과 범위 판정

- 대상은 tree **`bd060c4d92ca818cfe6b3543047eff7745451281`**이다(`git cat-file -t` = tree). 기준은 HEAD **b925520**(G-P11a 포함)이다.
- `git diff b925520 bd060c4d --stat`은 **20파일, 4273 insertions / 84 deletions**다. 계약 §6의 17파일에 C00 승인 fixture 3파일을 더한 목록과 같다. **범위 밖 변경은 0건이다.**
- 계약 `docs/testing/g08-track-health-cases.md`의 LF SHA-256은 `2f4b89a5b48efd2d961dbe8795a3805b2113a0fef788e8cd90cd92b4c99dcf5c`로 배정값과 같다.
- 계약 §14.3 표의 19파일 LF SHA-256을 사본과 대조했다. **19/19 일치.**
- fixture 3파일의 판정은 다음과 같다. 셋 모두 **최소 적응**이다.
  - `tests/ui/test_capture_start_ui.py`: fake 생성자 keyword, `observe_health`·`sources_released`, `pause(reason=...)` 전달만 바뀌었다.
  - `tests/integration/test_pending_deletion_restart.py`: `mode == "new"`이고 선행 동작이 recover·finalize인 두 경우의 기대 generation만 입장 직전 값으로 바뀌었다(+2행).
  - `tests/integration/test_unfinished_recovery.py`: 주입 대상만 `record_capture_health`에서 `finish_capture_health`로 바뀌었다. `tests.resource_fakes.STT`·`resource_request=STT`(G-P11a) 2곳은 보존됐다.
- GC-P02 보호 함수 `test_pending_management_never_blocks_another_recording`의 AST 소스 SHA-256은 기준·대상 모두 `1487c77a…181cbd`로 같다.
- 실행 위치는 `git archive bd060c4d | tar -x -C build/review-trees/g08a`다. 기준 비교는 `git archive b925520` → `build/review-trees/g08a-base`에서 했다. 변이는 `build/review-trees/g08a-mut`(pyproject·src·tests·scripts·packaging 사본)에서 했다.
- 모든 실행에 `PYTHONPATH=<사본>\src`를 고정했다. 전체 회귀 시작 시 `recoryn`과 `recoryn.domain.capture_health`의 `__file__`이 사본 안임을 확인했다. 반례는 `-I -B`로 실행하고, import 직후 `recoryn.__file__`이 지정 tree 안인지 assert했다. 변이 harness도 자식 import origin(`g08a-mut\src\recoryn\__init__.py`)을 assert했다.

## 2. 실행 결과

공통 조건은 다음과 같다. `.venv\Scripts\python.exe`(Python 3.13.1), `QT_QPA_PLATFORM=offscreen`, `PYTHONDONTWRITEBYTECODE=1`, `HF_HUB_OFFLINE=1`, `-p no:cacheprovider`, 실행별 새 `--basetemp`.

| ID | 명령 | 결과 |
| --- | --- | --- |
| R1 | `pytest -q -p no:cacheprovider -W error::ResourceWarning --cov=recoryn --cov-branch --cov-report=json:coverage.json --cov-fail-under=85 --basetemp …/g08a-bt-full -rfE`(`g08a-probe/run-full.sh`) | **21,688 passed, 1 failed, 2 skipped, 1093.04초, exit 1.** 결합 coverage 92.53%(85% 게이트 통과). 실패는 `G08-K-18`의 fixture 경쟁(G08R-04). skip 2는 `tests/release/test_gpu_smoke.py:107` "this volume does not create 8.3 names"(D: 볼륨 환경, 제품 무관) |
| R2 | `python scripts/check_coverage.py coverage.json` | 7묶음 PASS: domain 99.45/98.39, capture 99.85/98.57, jobs 99.10/95.54, storage 95.56/90.45, security 98.11/94.43, content 99.59/98.75, all 94.02/88.19(line/branch %) |
| R3 | `ruff check .` | All checks passed |
| R4 | `python -m mypy src/recoryn scripts packaging` | Success: no issues found in 90 source files |
| R5 | `tests/integration/test_health_crash.py` 단독 3회 | 37 passed ×3(7.7~7.9초) |
| R6 | 변이 정상본(신규 6파일 + app_service·desktop_independent·unit desktop·power) | 1,137 passed, 27.76초 |

작성자 보고와 다른 점은 다음과 같다. 21,691 PASS·skip 0이 아니라 실패 1·skip 2다. skip은 볼륨 환경 차이다. 실패는 제품이 아닌 시험 fixture의 Windows 경쟁이다.

## 3. 발견

### G08R-01 / S1 / OPEN — 호환 요약이 녹음 중 64KiB를 넘으면 기회성 checkpoint 실패가 두 트랙 녹음을 멈춘다

**재현 1 — headless 두 트랙.** `g08a-probe/probe_projection_size_real.py <tree> <work> 10 20`

- 입력: `RecordingService(max_blocks=1)`. run마다 트랙당 20회 고립 큐 거부를 만든다. probe가 root mutex를 잠깐 잡아 consumer의 다음 append를 멈춘다(관리 작업이나 디스크 지연과 같은 효과). 매 run 끝에 명시 pause/resume을 한다.
- 시각·장치 위치는 실제 크기를 쓴다(monotonic 3일, 48kHz 3시간 위치).
- 관측(대상 tree): run 0~6은 pause 성공이다(요약 29,773→63,050 B). **run 7의 `pause()`에서 `RecordingError: HEALTH_PERSISTENCE_FAILED_MEDIA_PRESERVED`가 난다.** 원인은 `ValidationError('JSON size limit exceeded')`, 세션은 **INTERRUPTED**다.
- 관측(기준 b925520, 같은 입력): 10 run 모두 PAUSED다. 요약은 52,316 B이고 실패는 없다.

**재현 2 — DesktopRecorder와 fake source, 녹음 중 중단.** `g08a-probe/probe_desktop_size_warn.py <tree> <work> 10 20 128`

- 입력: 재현 1과 같은 고립 거부에 더해, 매 run 트랙당 TIMESTAMP_ERROR packet 128개를 보낸다(Desktop이 pause마다 `backend_events`로 영속하는 경고).
- 관측(대상): run 0~3은 성공이다(pause 뒤 요약 48,895→62,368 B). **run 4의 cycle 15, 즉 녹음 도중에 `accepting=False`, `storage_failed=True`가 된다.** `writer_error=ValidationError('JSON size limit exceeded')`, 세션은 INTERRUPTED다. 이 시점 뒤의 mic·system 오디오는 수집되지 않는다.
- 관측(기준, 같은 입력): run 0~8은 정상이다. run 9의 pause에서 backend 건강 쓰기만 실패하고 세션은 **PAUSED로 남는다.** 녹음 도중 중단은 없다.

**원본 보존 확인.** `g08a-probe/probe_finalize_after.py`로 확인했다. 두 재현 모두 `finalize_unfinished`가 RECOVERED_UNCLEAN → FINALIZED(검증 청크 16·10개)를 만든다. 중단 이전 원본은 보존된다. 손실은 중단 이후 녹음되지 않은 구간이다.

**원인.**

- `_store_health`는 매 checkpoint마다 `{**old, ...}` 투영을 만든다(`src/recoryn/storage/library.py:1215-1231`). 투영에는 다음이 들어간다.
  - legacy epoch 전부
  - v2 epoch 최근 8개(트랙별 gaps·loss_ranges 16개)
  - top-level 트랙별 GapFact 16개(개당 약 600~700 B, `:1266`)
  - Desktop이 `record_capture_health`로 넣은 `backend_events`(최대 256, `src/recoryn/app/desktop.py:295-300`). 이 값은 이후 모든 투영에 그대로 실린다.
- 이 투영을 `strict_json(projection_body)`(기본 64KiB, `library.py:1275-1276`)로 검사한다.
- consumer의 `_checkpoint_health`(`src/recoryn/app/recording.py:344-379`)는 `HEALTH_SNAPSHOT_CHANGED`만 보류한다. 다른 예외는 `_consume`의 `except Exception`(`recording.py:511-512`)으로 간다. 거기서 `_fail`이 전체 gate를 닫는다.
- 크기 예산이 없으므로, pause/resume과 상세 사실이 쌓인 장시간 세션은 결정적으로 이 경로에 들어간다.

**기대.**

- 계약 §5.2는 checkpoint를 "기회성"으로 정의한다. "writer가 막히면 … 마지막 영속 prefix 이후는 미상으로 남길 수 있어야" 하고 "상세 버퍼 한도에 닿으면 … 생략 표시"해야 한다.
- 호환 요약은 상한 안에서 생략을 명시해 축약해야 한다(`detail_complete=False`, events/epochs/backend_events 생략 수). canonical 행만 전체를 보존해야 한다.
- 요약 크기 때문에 녹음·pause·stop이 실패해서는 안 된다.
- 회귀 시험이 필요하다. 상한 경계(8 epoch × 2트랙 × 상세 16 + backend 경고 256, 실제 크기의 시각·위치)에서 checkpoint·finish·`record_capture_health`·stop이 모두 성공해야 한다.
- 계약의 B family 'summary 64KiB −1/정확/+1'은 이 누적 경로를 실행하지 않는다.

### G08R-02 / S1 / OPEN — 연속성 근거가 끊긴 장치 누락을 미상이 아닌 "확인된 유실 0"으로 표시·영속한다

**재현.** `g08a-probe/probe_misc.py`의 A1~A3. 단일 트랙 headless, 480-frame 블록 4개를 모두 수락한 뒤 stop한다. live와 영속 요약에 `track_health_lines`를 적용해 비교했다.

| probe | 장치 위치(플래그) | 실제 위치 근거 | 표시(live·영속 동일) |
| --- | --- | --- | --- |
| A3 대조 | 0, 480, 4800, 5280 | 960~4800 누락 3840 frame | 확인된 장치 유실 **3840**, union **3840** |
| A2 | 0, 480(TIMESTAMP_ERROR), 4800, 5280 | 같은 3840 frame 누락 | 확인된 장치 유실 **0**, 같은 좌표의 확인된 유실 union **0**. 미상 문구 없음 |
| A1 | 모두 None(`NativePacket`이 허용) | 연속성 검사 불가 | 확인된 장치 유실 **0**, union **0**. 미상 문구 없음 |

**원인.**

- `submit`은 위치가 없거나 TIMESTAMP_ERROR인 블록에서 `_last_positions`를 지운다(`recording.py:456-461`). 다음 정상 블록은 비교 대상이 없어 불연속 검사를 건너뛴다.
- 이때 `media_loss_unknown`을 세우지 않는다. `track_loss`(`src/recoryn/domain/capture_health.py:264-272`)는 0을 확인값으로 낸다. `status.track_health_lines`(`src/recoryn/app/status.py:73-90`)는 0을 그대로 표시한다.
- `has_unknown`도 False로 남는다. 그러므로 export.json 요약에도 `known_loss_frames: 0`이 실린다.

**기대.** 계약을 따르면 연속성 사슬이 끊긴 구간은 `media_loss_unknown=True` 또는 UNKNOWN 범위의 DEVICE_DISCONTINUITY 관측으로 남겨야 한다. 0을 넣지 않고 "미상"으로 표시해야 한다.

- §3.1(3): "timestamp 불량 … `lost_frames=None` … 0을 넣지 않는다"
- §3.2: "불확실한 시계는 미상"
- §6 U: 미상≠0

**심각도 근거.** 배정 기준의 "잘못된 '유실 0' 표시"에 해당하므로 S1로 둔다. 도달성 제약도 있다.

- 실제 WASAPI glitch는 보통 DATA_DISCONTINUITY를 함께 세운다. 그 경로는 미상으로 처리된다.
- 위치 None을 내는 native backend가 있는지는 실장비에서 확인하지 않았다.

C00이 도달성을 근거로 S2로 낮출 수 있다.

### G08R-03 / S2 / OPEN — legacy 다중 track/epoch tail 수선이 원자적이지 않다. 부분 실패 뒤 재복구가 남은 tail 없이 성공을 보고한다

**재현.** `g08a-probe/probe_legacy_partial.py`

- 입력: legacy(v2 행 없음) RECORDING 세션. epochs에 mic(dropped 6)·system(dropped 0)이 있다.
- fault 모드: 첫 recover의 두 번째 `_store_health`에서 `sqlite3.OperationalError`를 1회 낸다. 두 commit 사이 kill과 같은 상태다.
- 관측(fault 모드):
  - 1차: `DEFERRED/HEALTH_RECOVERY_PENDING`, tail [mic]
  - 2차·3차(주입 없음): **`RECOVERED_UNCLEAN`, tail은 [mic]뿐이다.** system tail은 영구히 생기지 않는다.
- 관측(clean 모드): tail [mic, system]이 정상으로 생긴다. 그러나 요약 `tracks`에는 **["system"]만** 남는다(마지막 key의 run만 투영). 트랙별 건강 표시는 mic를 잃는다.

**원인.**

- legacy 분기는 unknown key마다 별도 run을 만들고 `_store_health`를 따로 commit한다(`library.py:1397-1465`).
- 재시도 시 `if not rows:`(`library.py:1367`)는 run 행이 하나라도 있으면 legacy 분기 전체를 건너뛴다.
- 오류 분류(`library.py:1472`)는 1차 실패를 보류로 보고하지만, 2차는 남은 작업을 모르고 성공으로 보고한다.

**기대.** 계약 §5.3을 따라야 한다. "새 tail 기록·run 상태·필요한 INTERRUPTED 전이는 같은 transaction으로 처리", "복구 도중 kill 후 재시도도 멱등". 모든 식별 track/epoch의 tail을 한 transaction으로 기록하거나, 재시도가 누락 key를 다시 계산해야 한다.

**시험 공백.** R family의 LEGACY·MISSING 행은 `tracks` 인자를 쓰지 않고 mic 한 트랙만 만든다(`tests/integration/test_track_health.py:68-77`). F family의 FAIL은 v2 OPEN만 다룬다.

**S2인 이유.** 세션 수준 `has_unknown=True`는 남는다. 세션 전체를 "미상 없음"으로 표시하지는 않는다. 다만 system 트랙의 미상 tail과 트랙별 표시가 빠진다.

### G08R-04 / S3 / OPEN — K36 kill fixture가 Windows에서 ready marker를 읽다가 간헐적으로 PermissionError를 낸다

- 재현: R1 전체 회귀에서 `tests/integration/test_health_crash.py::test_actual_health_boundary_kill[G08-K-18]`이 실패했다(stage 5, prefix 0, 2트랙).
- 관측: `marker.read_text`(`tests/integration/test_health_crash.py:132`)에서 `PermissionError: [Errno 13] … ready.json`.
  - 자식은 `os.replace(temporary, marker)`(`:37`)로 게시한다. 부모는 `marker.exists()` 직후 바로 연다.
  - 단독 3회(37×3)는 모두 PASS다. 부하 아래 rename 직후 공유 위반이 드물게 나는 것으로 보인다.
- 기대: 제품 결함은 아니다. CI 신뢰도를 위해 PermissionError 짧은 재시도, 또는 stdout 한 줄 handshake를 권고한다. 작성자의 "실패 0"은 이 환경에서 재현되지 않았다.

### G08R-05 / S3 / OPEN — 시험 충분성: 분모 일부가 같은 입력의 반복이고, 독립 변이 5개가 생존한다

**(a) S family의 stale 182행.** `tests/unit/test_track_health.py:124-148`이 대상이다.

- 이벤트 열(13)과 트랙 수(2)를 쓰지 않는다. 늘 1트랙 fake에 `"error"` 하나만 보낸다. 182개 ID가 상태 template 7개의 서로 다른 입력일 뿐이다.
- 비-stale 182행은 `SimpleNamespace`에 `_track_event`를 호출해 `transition_track`만 검사한다. 실제 submit/observe 경로의 "late 쓰기 0"과 "다른 트랙 불변"은 확인하지 않는다.

**(b) R family.** LEGACY·MISSING이 `tracks`를 무시한다(G08R-03).

**(c) 독립 변이.** `g08a-probe/mutate.py`로 11개를 실행했다. 작성자의 M01~M30과 다른 결함이다. 결과는 KILLED 6, **SURVIVED 5**, INVALID 0이다.

| 생존 변이 | 놓친 의미 |
| --- | --- |
| X04 `finalize_session`의 OPEN run 거부 제거(`library.py:1712-1717`) | 방어 검사가 시험되지 않음 |
| X05 capture 권위에서 DB 삭제 의도 확인 제거(`library.py:974`) | journal 없는 DB-only intent의 checkpoint 거부 미시험. writer append가 별도로 거부하므로 영향은 작음 |
| X06 export 마지막 `health_version` 재확인 제거(`src/recoryn/cli.py:269`) | 마지막 페이지 뒤 변경 미시험 |
| X07 `media_loss_unknown` 경고 줄 제거(`status.py:87`) | union 줄의 "미상"과 중복되어 미검출 |
| X09 checkpoint의 HEALTH_SNAPSHOT_CHANGED 보류를 예외로 바꿈(`recording.py:355`) | **보류 경로가 녹음을 멈추지 않는다는 점이 시험되지 않음.** G08R-01과 같은 위험군 |

KILLED는 X01(legacy unclean tail), X02(live union 미상), X03(source ACK), X08(DEVICE_LOST 뒤 수락), X10(stale epoch), X11(PAUSE gap 제거)다. 종료 코드 1이면서 요약에 failed가 있고 error가 없을 때만 KILLED로 셌다. 작성자의 M01~M30은 재실행하지 않았다.

**기대.** 생존 변이별 반례 시험을 추가해야 한다. stale·트랙 열을 실제로 사용하거나, 분모 설명을 "상태 7 × stale 대표 1"로 정정해야 한다.

### G08R-06 / S3 / OPEN — 이미 FINALIZED인 세션의 건강 DEFERRED를 "확정하지 않았습니다"로 표시한다

- 재현: `probe_misc.py` B. 정상 stop으로 FINALIZED가 된 세션의 `capture_health_runs.schema_version`을 3으로 바꾼 뒤 `finalize_unfinished`를 호출한다.
- 관측: 결과는 `already_finalized=True`, `finalized=False`, state FINALIZED다. `finalize_lines` 첫 줄은 "건강 판정 보류 · 확정하지 않았습니다. 원본을 보존합니다."다. UI 경고(`src/recoryn/ui/main.py:809-813`)도 같은 문구다.
- 근거: `library.py:2157`, `src/recoryn/app/recovery.py:270-274`
- 기대: 이미 확정된 세션임을 유지해서 표시해야 한다. 예: "이미 확정됨 · 건강 판정 보류". 사용자가 확정이 풀렸다고 오인하지 않아야 한다.

### G08R-07 / S3 / OPEN — 관측·제어 gap 수명: NO_PACKETS gap은 닫히지 않고 매초 새로 열리며, pause 재시도는 PAUSE gap을 중복으로 만든다

- 재현: `probe_misc.py` D. idle 통지 5회 뒤 정상 수락을 한다. 결과는 NO_PACKETS 이벤트 5개, 모두 `open=True`, CLOSE 0이다.
- WASAPI는 packet이 없는 동안 1초마다 idle을 보낸다(`src/recoryn/capture/wasapi.py:375-378`). 무음 loopback 동안 트랙당 시간당 약 3,600개의 열린 gap이 쌓인다. 해당 코드는 `recording.py:334-336`다.
- 계약 §3.2의 "새 정상 관측은 가능한 종료 관측 경계로만 기록"이 구현되지 않았다.
- 재현: `probe_misc.py` H. 첫 pause의 join이 WRITER_ACK_PENDING인 뒤 재시도하면 PAUSE gap이 **2개**다. `_drain`이 호출마다 `_gap`을 만든다(`recording.py:577-581`).
- 기대: 같은 원인의 연속 idle은 하나의 열린 gap으로 합치고, 다음 정상 수락에서 관측 경계로 CLOSE해야 한다. control gap은 cutoff 1회에만 만들어야 한다.

### G08R-08 / S3 / OPEN — 복구 중 StateConflict가 건강 보류 code에서 "HEALTH_UNREADABLE"로 바뀐다

- 근거: `library.py:1472-1480`. `StateConflict`는 `ValueError`의 하위 클래스다. 그래서 `_recover_capture_health`의 except가 다음 예외를 모두 받는다.
  - `_store_health`의 `DELETE_PENDING`
  - `HEALTH_SNAPSHOT_CHANGED`(일시적 경쟁)
  - `DELETION_HISTORY_UNAVAILABLE`
- 위 예외의 `str`은 허용 집합에 없고 OSError도 아니다. 그래서 code가 `HEALTH_UNREADABLE`(손상 의미)가 된다. recovery_view는 "건강 판정 보류 · HEALTH_UNREADABLE"로 표시한다.
- 관측: `probe_misc.py` C(tail commit 직전 DB 삭제 의도)에서는 뒤이은 `write_manifest`가 `DELETE_PENDING`으로 전체 복구를 거부했다. tail 0, run OPEN 유지, 미디어 채택 0이다. **삭제 우선은 지켜진다.** 표시 code만 부정확하다. 일시 경쟁의 오표시는 코드 읽기로만 확인했다.
- 기대: 일시 경쟁은 HEALTH_RECOVERY_PENDING이어야 한다. 삭제·이력 불가는 해당 code를 유지해야 한다.

### G08R-09 / S3 / OPEN — live 메모리 누계와 마지막 영속 checkpoint를 구분하지 않고, legacy export는 건강 상세 부재를 명시하지 않는다

- live 표시(`ui/main.py:1195-1197`, `status.py:59-99`)는 `health_snapshot()`의 메모리 누계만 "확인된 앱 큐 유실 N"으로 보인다. 마지막 영속 checkpoint와의 차이(미영속 tail 가능성)는 보이지 않는다. 계약 §6 "live 화면의 메모리 누계와 마지막 영속 checkpoint는 구별한다"에 어긋난다.
- legacy-only export(`probe_upgrade.py`, 기준 tree가 만든 FINALIZED 세션)의 export.json 키는 `capture_health, files, schema_version, session_id`뿐이다. 상세 파일·부재 표식이 없다. 계약 §6 "legacy-only export는 … 건강 정보 부재를 명시한다"에 어긋난다.

### G08R-10 / S3 / OPEN — gate가 닫힌 뒤의 source 건강 통지를 Desktop 진단에서 버린다

- 근거: `desktop.py:183-185`. `observe_health`는 `not self._accepting`이면 False다(`recording.py:325`). `_on_health`는 그 경우 즉시 return한다.
- 저장 실패로 gate가 먼저 닫히면, 이후 오는 `"error"`나 `"stopped"`(`release_ack=False` → DEVICE_RELEASE_UNCONFIRMED)가 `backend_events`에 남지 않는다. meter 정리도 하지 않는다.
- 기준 tree는 이 경고를 보관했다.
- ACK 자체는 `source.stop()` 예외로 계속 강제되므로 기능 손실은 없다. 진단 사실만 잃는다.
- 기대: health 모델 반영과 별개로 Desktop의 경고 보관·meter 정리는 run token 검사만으로 수행해야 한다.

## 4. 확인한 항목(결함 없음)

- **G07R-01 회귀 없음.** `probe_stop_inflight.py`·`probe_two_track_stop.py`(G07 검토 원본, LF hash 동일)를 기준·대상 모두에서 실행했다. 결과는 stop·pause 저장 1440·1440 frame, system 2880 frame, submit 모두 true로 같다.
- **녹음 부하 측정.** `probe_recording_load.py`, 단독 실행이다.
  - 조건: 8초, 10ms 블록 실시간 pacing, 중간 pause/resume 1회
  - 관리 thread 작업: 다른 세션 create/delete, list, inventory, pending deletions, Job claim/fail/resume
  - 8조합(1·2트랙 × 관리 유무 × 기준·대상) 모두 거부 0, 저장 frame = 수락 frame, 최종 FINALIZED였다(대상은 run CLOSED).

  | 지표(max) | 기준 b925520 | 대상 bd060c4d |
  | --- | --- | --- |
  | writer root mutex 보유 | 1.20~2.76ms | 1.29~3.75ms |
  | sealer root mutex 보유 | 2.73~4.93ms | 2.72~3.61ms |
  | capture gate 보유 | 2.21~2.79ms | 0.10~0.20ms |
  | submit 지연 | ≤0.070ms | ≤0.091ms |
  | 관리 thread root 보유 | 8.0~10.4ms | 7.0~8.5ms |

  관리 thread의 보유는 기존 관리 작업의 값이며 G08 변경과 무관하다.
- **포화 비용.** `probe_overload_cost.py`. consumer를 멈춘 상태에서 3,000회 거부를 만들었다. 거부 1회당 비용(submit + Desktop식 `health_snapshot`)은 다음과 같다.
  - 대상: 평균 0.282ms, gate 최대 2.05ms(`_health_record` 256 pending deep copy 2.12ms)
  - 기준: 평균 0.010ms, gate 최대 0.015ms

  10ms packet 주기 안이라 결함으로 올리지 않았다. 다만 hot path 비용이 28배다. 장시간 포화에서는 재측정을 권고한다.
- **QUEUE_DROP 1회 계상.** 실제 `offer=False`에서만 누계·이벤트를 만든다. `observe_health`는 packet의 accepted·rejected_frames를 다시 더하지 않는다. gate가 닫힌 뒤의 late 입력은 계상하지 않는다. 가변 frame_count를 합산한다. Q 18행 PASS와 코드(`recording.py:381-431`)로 확인했다.
- **CLOSED 조건.** `_join_workers`(consumer+sealer FIFO 등록까지)가 끝나기 전에는 WRITER_ACK_PENDING으로 finish를 호출하지 않는다. receipt는 cutoff·`sources_released`·worker 종료·저장 실패 없음을 모두 요구한다(X03 KILLED). writer 오류가 있으면 CLOSED 없이 checkpoint만 남긴다.
- **삭제 우선.** probe C, R family, X01·X05 결과로 확인했다. tail commit 직전 권위 재확인 경로(`library.py:1288-1296`)가 있다.
- **업그레이드·export.** `probe_upgrade.py`로 확인했다.
  - 기준 tree가 만든 라이브러리를 대상이 열면 표 3개·인덱스 2개가 additive로 생긴다(user_version 1 유지).
  - legacy PAUSED를 확정하면 LEGACY·tail 없음이다.
  - legacy export는 성공한다.
  - 새 녹음 export는 `capture-health.jsonl`(rows 3, sha256, health_version 2)과 export.json이 같은 snapshot이다.
- **power.** suspend는 `pause(reason="SUSPEND")`만 호출하고 wake 경로는 바뀌지 않았다(`src/recoryn/app/power.py:28`).

## 5. 놓쳤을 수 있는 영역(미검증)

- 실제 WASAPI의 TIMESTAMP_ERROR·DATA_DISCONTINUITY·위치 None 빈도와 loopback 무음의 idle 빈도. 이 빈도가 G08R-02·G08R-07의 실제 도달성을 정한다.
- 실장비의 장치 분리·재연결·절전·Windows 전원 장애 내구성. checkpoint commit fsync가 느린 HDD에서 consumer를 막는 시간. 이번 부하 측정은 SSD 한 대의 합성 실행이다.
- 작성자 M01~M30 재실행, 그리고 1,024행 case-ID 독립 감사 재계산. 수집 node 수는 R6의 1,137(보강 포함)만 확인했다.
- 다른 프로세스(CLI)가 같은 라이브러리에 쓰는 동안의 SQLITE_BUSY. checkpoint가 매초 쓰므로 노출이 기준보다 크다.
- 64KiB 경계의 다른 누적원: 트랙 수 >2, 긴 ID, legacy epoch가 많은 업그레이드 세션.

## 6. 반례 스크립트(LF SHA-256)

모두 `build/review-trees/g08a-probe/` 아래에 있다. 실행 형식은 `python -I -B <script> <tree> <work> …`다.

| 파일 | SHA-256 |
| --- | --- |
| `run-full.sh` | `aaf00b1d212e643dada3698b970410bdc0f89e2282877b4131b7f0496e0c0a29` |
| `probe_projection_size.py` | `cca08bd9781524ff4796612b82d29a83c0d9c1e98737317bf5a877a7ac5504c8` |
| `probe_projection_size_real.py` | `d54ec4e9d79dccad85c59ae1d99f08e726727e4705aa0c997e044b3620cac743` |
| `probe_desktop_size.py` | `fe43e27b1922d5c7ddb5e2ef44dd31c22950555f44ca05b6abd882b8fc9a99d7` |
| `probe_desktop_size_warn.py` | `4144cda7c4b2baeff39a7fb65405f28706de27b8e8074977315d1ac0b85a3ce9` |
| `probe_finalize_after.py` | `f6c59a172627b4b5f1d1f995397ed8829a6391c4ba4b6de507fb143766618761` |
| `probe_legacy_partial.py` | `0654a19db3619a553021d546ef24702b75eb169f9aa8f41047ba76e4d1936022` |
| `probe_misc.py` | `71e9ff649fa6e18c02912a95006ca73e76ae459df5e911f28cc23bbbe0994ae4` |
| `probe_recording_load.py` | `3de98b86ba67439254201a89a57db842fe88ac461c5690d5eccf2c3a3af4790f` |
| `probe_overload_cost.py` | `c0f1afeb02510537c7fa7f21fa03175cc8dd29336ace58c821d67fc5c17361c3` |
| `probe_upgrade.py` | `4c9f71f942fedbeb646944630e2a6639a8d27ecb40a3cd13ebc3b225ddea5fe8` |
| `probe_stop_inflight.py`(G07 원본) | `734047d102c12aa6a941bdfc4b6d1e77d7edf5bc4117c7796ce2ee4112684adb` |
| `probe_two_track_stop.py`(G07 원본) | `a09d994d200f8660ad3cabe565656a5ca806d52ed0520483ad28cbb9460ff40c` |
| `mutate.py` | `c354b8e7edd060d0c7e257a871b655b7a496c1bdf52ebfd511ff895edb424565` |

## RECHECK 1 — FIX1 tree `beae7991` 재확인

2026-11-25, 같은 검토자. 대상은 tree **`beae7991ce26779c84e278078944c394ba238ea3`**(HEAD b925520 + G-P08 20파일)이다. 직전 tree bd060c4d 대비 변경은 **15파일, 1495 insertions / 193 deletions**다. 범위 밖 변경은 0건이다.

**판정: G08R-01~10 10건 모두 RECHECKED.** 새 OPEN은 **2건 — S0 0 / S1 0 / S2 1 / S3 1**이다. S0·S1이 없으므로 이 기준으로는 push를 막지 않는다. 다만 G08R-11은 C00 결정 "건강 실패는 판정 보류·미상"이 다중 run에서 지켜지지 않는 경로다. push 전 수정을 권고한다.

### R1-0. 입력 고정과 실행 위치

- `git archive beae7991 | tar -x -C build/review-trees/g08b`에서만 판정했다. 모든 실행의 `PYTHONPATH`는 사본 `src`로 고정했다.
  - 전체 회귀: 시작 시 `recoryn`·`recoryn.domain.capture_health`의 `__file__`이 사본 안임을 기록했다.
  - 반례: `-I -B`로 실행하고, import 직후 `recoryn.__file__`이 지정 tree 안인지 assert했다.
  - 변이: 사본 `build/review-trees/g08b-mut`에서 했다. 자식 import origin `g08b-mut\src\recoryn\__init__.py`를 assert했다.
- 계약 문서 LF SHA-256은 `cb2cd2a4801005706cfc53cbbb5f953010c07d9d94aac875bb70081dcfb8e10e`로 배정값과 같다. §16.3 표의 19파일 LF SHA-256은 사본과 **19/19 일치**했다.
- 반례와 harness는 `build/review-trees/g08b-probe/`에 있다(해시는 R1-10).

### R1-1. 실행 결과

| ID | 명령 | 결과 |
| --- | --- | --- |
| RR1 | 1회차 CI 동등 전체 회귀(`run-full1.sh`: `pytest -q -p no:cacheprovider -W error::ResourceWarning --cov=recoryn --cov-branch --cov-report=json:coverage.json --cov-fail-under=85`, 고유 basetemp) | **21,740 passed, 2 skipped, 0 failed, 1101.28초, exit 0.** 결합 coverage 92.70% |
| RR2 | RR1 직후 `check_coverage.py` | 7묶음 PASS: domain 99.18/97.89, capture 99.85/98.57, jobs 99.10/95.54, storage 95.85/91.19, security 98.11/94.43, content 99.59/98.75, all 94.17/88.46 |
| RR3 | 2회차 같은 명령(`run-full2.sh`, 다른 basetemp, 측정 뒤 단독 실행) | **21,740 passed, 2 skipped, 0 failed, 1033.02초, exit 0.** 결합 coverage 92.70%, `check_coverage` 7묶음 PASS(RR2와 같은 수치). 간헐 실패 0 |
| RR4 | `ruff check .` | All checks passed(2회) |
| RR5 | `python -m mypy src/recoryn scripts packaging` | Success: no issues found in 90 source files(2회) |

skip 2건은 1차 검토와 같다(`tests/release/test_gpu_smoke.py:107`, D: 볼륨이 8.3 이름을 만들지 않음). 작성자 보고의 21,742 PASS·skip 0과의 차이 2는 이 환경 skip이다.

### R1-2. 원 지적 재확인

| ID | 재실행·근거 | 판정 |
| --- | --- | --- |
| G08R-01 | headless 원 반례 `probe_projection_size_real.py 10 20`: 10 run 모두 pause 성공, 요약 최대 57,630 B. Desktop 원 반례 `probe_desktop_size_warn.py 10 20 128`: 10 run 모두 성공(원래 run 4 cycle 15 중단), 요약 최대 61,320 B, run 10개 모두 CLOSED, 녹음 중단 0. 축약은 `detail_complete=False`·`epochs_omitted`·`backend_events_omitted`로 표시된다(`library.py`의 `_bounded_health_projection`, 60KiB 예산). 실패 주입 행렬은 R1-3 | **RECHECKED** |
| G08R-02 | `probe_misc.py` A1(위치 없음)·A2(TIMESTAMP_ERROR 뒤 3840 frame 점프): 이제 live·영속 모두 "장치 유실 미상 · 확인된 하한과 구별", "전체 유실 미상 · 확인 하한 0 frame", 세션 "미상 구간 있음"이다. A3(정상 시계 같은 점프)는 확인된 3840·union 3840으로 유지된다 | **RECHECKED** |
| G08R-03 | `probe_legacy_partial.py`: 두 번째 commit 실패 뒤 1차 `DEFERRED/HEALTH_RECOVERY_PENDING`, tail [mic]. 2차 재복구에서 **[mic, system]**이 채워지고 3차는 멱등이다. 요약 tracks도 두 트랙이다. 구현은 별도 transaction에 멱등 재탐색을 더한 방식으로, C00 결정의 '(또는 멱등 재탐색)'에 해당한다 | **RECHECKED** |
| G08R-04 | ready marker 게시·첫 읽기에서 PermissionError만 기한 안에서 재시도한다. 기한이 지나면 원 예외와 다른 예외를 전파한다(G08-FIX1-36~40). 전체 2회 모두 K36 실패 0 | **RECHECKED** |
| G08R-05 | S stale 182행이 이벤트 13종·트랙 수를 실제로 사용한다. R의 LEGACY·MISSING은 1·2트랙을 구성한다. 1차 생존 변이 X04·X05·X06·X07·X09를 포함해 X01~X11 **11/11 KILLED**(R1-5) | **RECHECKED** |
| G08R-06 | `probe_misc.py` B: FINALIZED 뒤 건강 미래 version이면 "이미 확정됨 · 건강 판정 보류 · 기존 확정 상태와 원본을 유지합니다."로 표시된다 | **RECHECKED** |
| G08R-07 | `probe_misc.py` D: idle 5회 → NO_PACKETS OPEN 1·CLOSE 1. H: WRITER_ACK_PENDING 뒤 재시도 → PAUSE gap 1. 상한 측정은 R1-4 | **RECHECKED** |
| G08R-08 | `probe_defer_code.py`: tail commit에 `HEALTH_SNAPSHOT_CHANGED`·`HEALTH_EVENT_CONFLICT`를 주입하면 bd060c4d는 `HEALTH_UNREADABLE`, beae7991은 `HEALTH_RECOVERY_PENDING`이다. 삭제 의도 선행(`probe_misc.py` C)은 계속 `DELETE_PENDING`으로 거부되고 tail 0·run OPEN 유지다 | **RECHECKED** |
| G08R-09 | live 요약에 "메모리 관측 누계 · 마지막 영속 checkpoint: N"과 영속 prefix가 따로 표시된다. 기준 tree가 만든 legacy FINALIZED 세션의 export.json에 `capture_health_details={"available": false, "reason": "LEGACY_HEALTH_DETAILS_UNAVAILABLE"}`가 있다(`probe_upgrade.py`). v2 export는 jsonl rows 3·sha256·health_version 2다 | **RECHECKED** |
| G08R-10 | `probe_desktop_closed_gate.py`: 저장 실패로 gate가 닫힌 뒤의 error·stopped(release_ack=False)가 bd060c4d에서는 0건이고, beae7991에서는 `CAPTURE_FAILED`·`DEVICE_RELEASE_UNCONFIRMED` 2건이 보관된다. 다른 epoch 통지는 계속 무시된다 | **RECHECKED** |

G07R-01 반례 2개도 다시 실행했다. 결과는 stop·pause 1440/1440, system 2880, submit 모두 true로 기준과 같다.

### R1-3. checkpoint 실패 주입 — 녹음 비차단과 건강 정직성

`probe_fault_matrix.py`는 두 트랙 headless 세션을 쓴다.

1. 10블록/트랙을 보내고 정상 checkpoint 1회를 남긴다.
2. 건강 경로에만 장애를 넣고 2.4초 동안 20블록/트랙을 보낸다. 이 동안 매초 checkpoint가 실패한다.
3. 장애를 걷고 stop한다.

| 시나리오(주입 지점) | 수락·저장 | live | stop 뒤 |
| --- | --- | --- | --- |
| F1 DB commit(consumer의 `_transaction` OperationalError) | 60/60 수락, 두 트랙 bytes = 수락 입력 | accepting 유지, **DEFERRED**, 마지막 영속 checkpoint 1 표시, `media_loss_unknown` | FINALIZED, RECOVERED_UNCLEAN, UNKNOWN_TAIL [mic, system], `has_unknown=True`, `count_complete=False` |
| F2 journal(capture 권위 OSError) | 같음 | 같음 | 같음 |
| F3 크기 초과(`strict_json` ValidationError) | 같음 | 같음 | 같음 |
| F4 snapshot 검증 실패 | 같음 | 같음 | 같음, 요약 `health_status=DEFERRED` 잔존(G08R-12) |
| F5 checkpoint + 보류 marker 동시 실패 | 같음 | 같음 | 같음 |
| F8 F4 뒤 pause/resume·정상 run | 70/70, bytes 일치 | DEFERRED | FINALIZED, run1 RECOVERED_UNCLEAN + run2 CLOSED, tail [mic, system] |
| **F6** F5 뒤 pause/resume·정상 run | 70/70, bytes 일치 | DEFERRED | **stop 예외 `StateConflict: HEALTH_RECOVERY_PENDING`, 상태 FINALIZING**, 요약 `has_unknown=False`·`run_status=CLOSED`·`detail_complete=True`, runs [OPEN, CLOSED], tail 0(G08R-11) |
| **F7** F1 뒤 pause/resume·정상 run | 같음 | 같음 | F6과 같음(G08R-11) |

- **녹음 비차단은 모든 지점에서 성립한다.** 거부 0, `storage_failed` False, 원본 bytes가 수락 입력과 같다.
- 실패 뒤 tail의 의미는 `probe_tail_prefix.py`로 확인했다.
  - 입력: 영속 prefix 큐 유실 6 뒤 checkpoint가 실패하고 메모리 누계가 18이 된다.
  - live: DEFERRED, 메모리 18, 영속 checkpoint 1의 prefix 6을 따로 표시한다.
  - stop 뒤 요약: 확인된 앱 큐 유실 6, "전체 유실 미상 · 확인 하한 6", `count_complete=False`, UNKNOWN_TAIL(`lost_frames=None`, UNKNOWN).
  - 미영속 누계 18을 확인값으로 올리지 않는다. 계약에 맞다.

### R1-4. gap 수 상한

`probe_gap_bound.py`(두 트랙) 결과다.

- idle 통지 3,600회(1Hz 한 시간)를 보낸 뒤 packet 1개를 보내면 NO_PACKETS는 **OPEN 1·CLOSE 1**이다.
- idle→packet 교대 20회는 OPEN·CLOSE가 교대 수 이하다(20/20). 큐 거부로 수락되지 않은 packet은 구간을 닫지 않아 합쳐진다.
- WRITER_ACK_PENDING 재시도를 섞은 pause/resume 10회는 PAUSE **OPEN 20·CLOSE 20**(10회 × 2트랙)이다. 재시도로 중복되지 않는다.

gap 수는 시간이 아니라 상태 전환 수에 비례한다.

### R1-5. 변이 재적용

정상본(신규 6파일 + app_service·desktop_independent·unit desktop·power·unfinished_recovery)은 1,237 passed, 170.69초다.

- 1차 검토 X01~X11: **11/11 KILLED**. 1차에서 생존한 X04·X05·X06·X07·X09도 모두 검출된다.
- FIX1 수정을 겨냥한 새 변이 Z01~Z10: **10/10 KILLED**.
  - Z01 checkpoint 실패 재전파 / Z02 요약 무제한 / Z03 위치 근거 없는 구간 미상 제거 / Z04 NO_PACKETS 매번 재개 / Z05 drain마다 제어 gap
  - Z06 legacy 재탐색 제거 / Z07 stop의 보류 확인 제거 / Z08 begin 건강 실패로 시작 중단 / Z09 live DEFERRED 미상 숨김 / Z10 drain의 보류 marker 누락
- 여러 줄 변이 6개는 CRLF 사본에서 첫 harness(`mutate2.py`)가 원문을 찾지 못해 INVALID였다. CRLF 대응 `mutate3.py`로 다시 실행했다. 검출로 센 것은 rc 1이면서 요약에 failed가 있고 error가 없는 경우뿐이다. 최종 SURVIVED·INVALID는 0이다.
- 작성자 M01~M30·Y01~Y10은 재실행하지 않았다.

### R1-6. 승인된 기존 시험 단언 변경 3건

| 파일 | AST 비교 | 판정 |
| --- | --- | --- |
| `tests/integration/test_unfinished_recovery.py` | top-level 함수 중 `_storage_failure`·`test_storage_failure_cause_chain`만 변경, 추가·삭제 0. assert 130→133 | health_failed에서만 기대가 'RecordingError·INTERRUPTED'에서 'FINALIZED·`has_unknown`·storage_failed 아님'으로 바뀌었다. `chain(..., sealed=True)`의 `sealed` 인자는 b925520에 이미 있던 helper 인자다. O1 원본 불변·O2 bytes/frame·O4 확정 멱등·`is_live` 거부는 그대로 실행된다. 확정 전 export 거부(O7 사전)만 이미 FINALIZED이므로 건너뛴다. seal·register 실패 원인의 INTERRUPTED 기대는 변하지 않았다 |
| `tests/integration/test_app_service.py` | `test_capture_health_write_failure_cannot_leave_recording_state`·`test_failed_start_does_not_leak_a_live_writer`만 변경. assert 77→79 | 건강 실패 기대가 FINALIZED·`has_unknown`·`not storage_failed`·`not worker_alive`·frame 3으로 바뀌었다(RECORDING 잔류 금지 성질 유지). 시작 실패 시험은 `begin_capture_health`에 더해 `transition` 실패도 주입한다. `pytest.raises`와 `not worker_alive` 단언은 유지된다 |

G-P04 성질 단언은 약화되지 않았다. 바뀐 것은 C00이 승인한 건강 실패 의미뿐이다. GC-P02 보호 함수 해시 `1487c77a…181cbd`와 G-P11a `resource_request=STT`(2곳)도 유지된다.

### R1-7. 녹음 측정(단독 실행, 기준 b925520 대비)

`probe_recording_load.py` 조건은 1차와 같다: 8초, 10ms 실시간 pacing, 중간 pause/resume, 관리 thread는 다른 세션 create/delete·list·inventory·pending deletions·Job claim/fail/resume. 8조합 모두 거부 0, 저장 frame = 수락 frame, FINALIZED였다(대상 run CLOSED).

| 지표(max) | 기준 | beae7991 |
| --- | --- | --- |
| writer root mutex 보유 | 1.16~2.95ms | 1.26~3.72ms |
| sealer root mutex 보유 | 2.68~2.83ms | 2.64~3.26ms(1조합 17.34ms 단발 이상값) |
| capture gate 보유 | 2.13~4.57ms | 0.09~0.16ms |
| submit 지연 | ≤0.069ms | ≤0.082ms |

- sealer의 17.34ms 이상값은 1트랙·관리 없음 조합의 단발 값이다. sealer 경로는 FIX1이 바꾸지 않았다. 디스크 fsync 변동으로 본다.
- 큐 포화(`probe_overload_cost.py`, consumer 정지, 거부 3,000회, 거부마다 `health_snapshot` 포함)의 거부 1회 비용:

  | tree | 평균 | gate 최대 | `_health_record` |
  | --- | --- | --- | --- |
  | bd060c4d(1차) | 0.282ms | 2.05ms | 2.12ms |
  | beae7991 | **0.019ms** | 0.657ms | 0.039ms |
  | 기준 | 0.009ms | 0.012ms | – |

- Desktop `_submit`은 이제 거부마다 `health_snapshot`을 부르지 않고 `storage_failed` 속성만 읽는다. 실제 경로 비용은 위 값보다 작다.

### R1-8. 새 발견

#### G08R-11 / S2 / OPEN — 보류 marker 쓰기가 실패한 run 뒤 정상 run이 이어지면, stop이 HEALTH_RECOVERY_PENDING으로 실패하고 요약은 미상 없음으로 남는다

**재현.** `probe_fault_matrix.py`의 F6·F7. run 1에서 checkpoint와 보류 marker가 함께 실패한다(DB가 잠깐 잠긴 경우와 같음). 장애를 걷은 뒤 pause/resume으로 run 2를 정상 기록하고 stop한다.

**관측.**

- 녹음은 끝까지 계속된다. 70/70 수락, bytes 일치.
- `RecordingService.stop()`이 `StateConflict: HEALTH_RECOVERY_PENDING`을 내고 세션은 **FINALIZING**에 남는다.
- 그 사이 요약은 `has_unknown=False`, `run_status=CLOSED`, `detail_complete=True`, `count_complete=True`다. capture_health_runs는 [OPEN(run 1), CLOSED(run 2)]이고 UNKNOWN_TAIL은 0이다.
- 세션 수준 "미상 구간 있음"이 표시되지 않는다.
- 이후 `finalize_unfinished`(`probe_finalize_after.py`)는 RECOVERED_UNCLEAN·FINALIZED·검증 청크 4로 정상 회복된다.

**원인.**

- `_defer_health`(`src/recoryn/app/recording.py:172-182`)는 쓰기 전에 `_defer_marker_pending=False`로 바꾼다. 쓰기 실패는 삼키므로 drain과 다음 checkpoint 모두 marker를 다시 쓰지 않는다.
- `_begin_epoch`가 `_health_deferred=False`로 초기화한다(`:228`). run 2의 begin·checkpoint 투영은 run 1의 보류를 모른다(`has_unknown`은 old 값을 따른다).
- `stop()`의 보류 판단(`:798-806`)은 현재 run의 메모리 플래그와 요약 marker만 본다. 남아 있는 OPEN run은 확인하지 않는다. 그래서 FINALIZING 전이 뒤 `finalize_session`의 OPEN run 거부(`src/recoryn/storage/library.py:1847`)에 걸린다.

**기대.** C00 결정 "어떤 실패도 녹음을 멈추지 않음(판정 보류·미상)"을 따라야 한다.

- 보류 marker는 성공할 때까지 pending으로 남겨 drain·다음 begin에서 다시 써야 한다. 또는 새 run begin에서 이전 OPEN run의 존재를 `has_unknown`/DEFERRED로 투영해야 한다.
- `stop()`은 OPEN run이 남아 있으면 기존 보류 경로(PAUSED → recover → finalize 또는 DEFERRED 반환)를 따라야 한다. 예외로 FINALIZING에 남기지 않아야 한다.
- 회귀 시험이 필요하다: marker 실패 → 다음 run 정상 → stop. 기존 FIX1 시험(G08-FIX1-03 등)은 marker가 성공하는 경우만 다룬다.

**S2인 이유.**

- 녹음 유실·원본 손상이 없다.
- 기존 `finalize_unfinished`로 우회 복구할 수 있다.
- 잘못된 요약은 stop이 실패한 미확정 세션에서만 나타난다. 그 세션은 미확정 목록에 오른다.

C00이 세션 수준 미상 누락을 '잘못된 미상 없음 표시'로 보면 S1로 올릴 수 있다.

#### G08R-12 / S3 / OPEN — 복구로 UNKNOWN_TAIL을 기록한 뒤에도 요약의 `health_status=DEFERRED`가 남아 "건강 판정 보류"로 표시된다

**재현.**

- `probe_tail_prefix.py`: stop이 recover → RECOVERED_UNCLEAN → FINALIZED까지 성공한 뒤에도 요약 첫 줄이 "건강 판정 보류 · 마지막 영속 prefix 이후 미상 · 녹음 저장과 별개"다.
- F4·F8도 FINALIZED 뒤 `health_status=DEFERRED`가 남는다.
- 반면 marker 쓰기가 실패했던 F1~F3은 같은 최종 상태인데 `health_status`가 없다. 같은 사실이 marker 성공 여부에 따라 다르게 표시된다.

**근거.**

- `defer_capture_health`(`src/recoryn/storage/library.py`)는 `health_status`·`health_error`·`deferred_run_id`를 요약에 넣는다.
- 이후 `_store_health(status="RECOVERED_UNCLEAN")` 투영은 `{**old, ...}`로 이 키들을 그대로 옮긴다.
- `track_health_lines`(`src/recoryn/app/status.py`)는 키가 있으면 보류 줄을 낸다.

**기대.** 계약 개정 §2는 "건강 prefix+미상 tail"과 "건강 판정 보류"를 구별한다. tail 수선에 성공하면 보류 표식을 해제하거나 '보류 이력'으로 바꿔야 한다. 다만 미상 tail·`count_complete=False`는 유지해야 한다.

### R1-9. 놓쳤을 수 있는 영역

1차 §5의 실장비·전원·SQLITE_BUSY 항목은 그대로 미검증이다. 추가로 다음을 확인하지 않았다.

- 작성자 M01~M30·Y01~Y10 재실행, 1,024행 case-ID 감사 재계산(수집 node는 변이 정상본 1,237만 확인)
- 3트랙 이상·긴 ID에서 60KiB 예산의 tracks 생략 경로가 실제 UI 표시에 주는 영향
- 보류 marker와 G-P05 삭제 의도가 동시에 오는 경쟁(단위 시험 COV05/06만 확인)

### R1-10. 재확인 반례·harness(LF SHA-256)

1차 반례 중 `probe_projection_size_real.py`·`probe_desktop_size_warn.py`·`probe_misc.py`·`probe_legacy_partial.py`·`probe_recording_load.py`·`probe_overload_cost.py`·`probe_upgrade.py`·G07 원본 2개는 내용이 1차 §6 해시와 같다. `g08b-probe/`에 복사해 재사용했다.

| 파일 | SHA-256 |
| --- | --- |
| `run-full1.sh` | `52a518ac6707af7ddc1015bcd23d97290f7cc1e1785f1b20d4e48cf8f5eea70c` |
| `run-full2.sh` | `29cf0354a2a1910a0a606ba09685cc786a9390f9e93d52653a5f32bdaa63b9be` |
| `probe_fault_matrix.py` | `fad642ab1e86a6e0775e6c0e02c09dae19eff3d964ac468edf7d37e8d15fba80` |
| `probe_tail_prefix.py` | `59e70ab8915ba4e06229ac8554b80f7b9c797baaa80e88d8fc8e960f00ecca55` |
| `probe_gap_bound.py` | `1bc1aab0700eede0f845f5e51d53a7cae9c89a3a562093cc469b5a66ea20817b` |
| `probe_desktop_closed_gate.py` | `ea2a10f8e7efc0ffa889aa422a37616a702c7a5f6bc9ffc4f4edc3287d61f3ce` |
| `probe_defer_code.py` | `7e58e39a6d241413e3782a04555087ffb168768b593abb9bedeac1297b4eea4d` |
| `mutate2.py` | `7c40dcbd95d7b90b116edfa139cfe479904d2a8701bb07ba08077aed592d443d` |
| `mutate3.py` | `a1abbfa620981f95acfc74b71202bdea4f29605156add50fbf7035aadf79e8b5` |
| `mutants_fix1.py` | `5e24de3cc7d4c56fdae1988f44a712bbabaedc2dff5f9c9b490462ea46ea7d64` |

## RECHECK 2 — FIX2 tree `8253e8d7` 재확인

2026-11-25, 같은 검토자. 대상은 tree **`8253e8d76908b101f207f416143641623897855a`**(현재 HEAD 8ca52f8(G-P11b 포함) + G-P08 20파일)이다. C00은 G08R-11을 S1로 올렸다.

**판정: G08R-11·G08R-12 모두 RECHECKED. G08R-01~10은 RECHECKED 상태가 유지된다.** 새 OPEN은 **1건 — S0 0 / S1 0 / S2 0 / S3 1**(G08R-13, 시험 공백)이다. S0·S1·S2가 없으므로 이 기준으로는 push를 막지 않는다.

### R2-0. 입력 고정과 범위

- `git diff --name-only 8ca52f8 8253e8d7`은 `git diff --name-only b925520 beae7991`의 G-P08 20파일과 **같은 집합**이다. 기반 변경(G-P11b)과 겹치는 G-P08 파일은 없다.
- FIX1 대비 실제 변경은 4파일(713 insertions / 19 deletions)이다: `src/recoryn/app/recording.py`, `src/recoryn/storage/library.py`, `tests/integration/test_track_health.py`, 계약 문서. 작성자 보고와 같다.
- 계약 문서 LF SHA-256은 `3d014d99560cec70b041e3b6d4637ac8929a7f208028d0fc6a8b2e1ff7aad6cd`로 배정값과 같다. §17.4 표의 19파일 LF SHA-256은 사본과 **19/19 일치**했다.
- 실행 위치는 다음과 같다.
  - 판정: `git archive 8253e8d7 | tar -x -C build/review-trees/g08c`
  - 기준 비교: `git archive 8ca52f8` → `g08c-base`
  - 변이: `g08c-mut`(pyproject·src·tests·scripts·packaging 사본)
  - 모든 실행에 `PYTHONPATH=<사본>\src`를 고정했다. 회귀 시작 시 `recoryn`·`capture_health`의 `__file__`이 사본 안임을 기록했다. 반례는 `-I -B`와 import 위치 assert로 실행했다. 변이 harness는 자식 import origin `g08c-mut\src\recoryn\__init__.py`를 assert했다.
- 반례는 `build/review-trees/g08c-probe/`에 있다(해시는 R2-8).

### R2-1. 실행 결과

| ID | 명령 | 결과 |
| --- | --- | --- |
| RT | 신규 6파일 단독(`-W error::ResourceWarning`, offscreen, 고유 basetemp). 다른 실행보다 먼저 혼자 실행 | **1,167 passed in 38.78초** — 60초 게이트 PASS |
| RA1 | 1회차 CI 동등 전체(`run-full1.sh`: `pytest -q -p no:cacheprovider -W error::ResourceWarning --cov=recoryn --cov-branch --cov-report=json:coverage.json --cov-fail-under=85`) | **22,440 passed, 2 skipped, 0 failed, 1130.15초, exit 0.** 결합 coverage 92.29% |
| RA2 | RA1 직후 `check_coverage.py` | 7묶음 PASS: domain 99.18/97.89, capture 99.85/98.57, jobs 99.29/96.23, storage 95.92/91.16, security 98.11/94.43, content 99.59/98.75, all 93.70/88.19 |
| RA3 | 2회차 같은 명령(`run-full2.sh`, 다른 basetemp) | **22,440 passed, 2 skipped, 0 failed, 1169.28초, exit 0.** 결합 coverage 92.29%, `check_coverage` 7묶음 PASS(RA2와 같은 수치). 간헐 실패 0 |
| RA4 | `ruff check .` | All checks passed(2회) |
| RA5 | `python -m mypy src/recoryn scripts packaging` | Success: no issues found in 91 source files(2회) |

**G-P11b 결합.** 수집 node 수로 합산을 확인했다.

- 8ca52f8은 21,275, 대상은 22,442(= 21,275 + 신규 6파일 1,167, 실행 22,440 + skip 2)다.
- b925520은 20,606이다. 20,606 + 1,167 = 21,773이 작성자 보고 수치다. 차이 669건이 G-P11b 시험이다.
- 새 기준의 G-P11b 시험 전체가 G-P08과 함께 통과했다.
- skip 2건은 이전과 같은 D: 볼륨 8.3 이름 환경 문제다.

### R2-2. G08R-11 재확인

`probe_fix2.py`를 FIX1 tree와 FIX2 tree에서 같은 입력으로 실행했다.

| 시나리오 | FIX1(beae7991) | FIX2(8253e8d7) |
| --- | --- | --- |
| P1: run 1의 checkpoint·marker 실패(건강 경로만) → 장애 제거 → pause/resume → 정상 run 2 → stop | run 1 pause 뒤·run 2 동안 요약 `has_unknown=False`, live OBSERVED, **stop `HEALTH_RECOVERY_PENDING`·FINALIZING**(원 결함 재현) | run 1 pause 뒤와 run 2 동안 읽기 모델·DB 원문 모두 `DEFERRED`·`has_unknown=True`, live DEFERRED. stop은 FINALIZED, runs [RECOVERED_UNCLEAN, CLOSED], 원본 bytes 일치 |
| P2: 건강 쓰기(store·defer·resolve)가 stop 이후까지 계속 실패 | (해당 API 없음) | **stop이 317ms에 반환**한다: PAUSED, `finalized=False`, DEFERRED. 녹음 종료가 막히지 않는다. 실패 동안 읽기 모델은 `DEFERRED`·`has_unknown=True`다(DB 원문은 marker를 못 써 `has_unknown=False`). 장애를 걷은 뒤 `finalize_unfinished`는 FINALIZED·RECOVERED_UNCLEAN·미상 유지 |
| P3: 실제 외부 SQLite EXCLUSIVE lock 3초(녹음 중) | live OBSERVED. 건강 쓰기가 busy 대기 뒤 성공 | live DEFERRED, 거부 0, stop 667ms → FINALIZED·tail [mic, system]·`has_unknown=True` |
| P4: 외부 lock 3초를 stop 직전에 시작 | stop 3.30초, FINALIZED·CLOSED | stop 3.25초(일반 세션·등록 transaction의 busy 대기), FINALIZED·CLOSED |
| P5: P2처럼 marker가 계속 실패한 채 run 2까지 pause → Library를 닫고 다시 염(메모리 보류 사실 소실) | (해당 API 없음) | 다시 연 뒤에도 읽기 모델은 `DEFERRED`·`has_unknown=True`다(OPEN run + PAUSED 상태). `capture_health_pending=True`. `finalize_unfinished`가 FINALIZED·RECOVERED_UNCLEAN으로 회복 |

검토자 F1~F8(`probe_fault_matrix.py`)도 다시 실행했다.

- 8개 모두 수락 60/60·70/70, 원본 bytes 일치, live DEFERRED, stop FINALIZED, `has_unknown=True`, UNKNOWN_TAIL [mic, system]이다.
- F6·F7은 runs [RECOVERED_UNCLEAN, CLOSED]이다(1차의 FINALIZING·`has_unknown=False`는 사라짐).

**원인별 변이**(R2-4의 C 계열)

| 원인 | 변이 | 결과 |
| --- | --- | --- |
| ① marker 재시도 없음 | C01 실패한 marker를 pending에서 제거 | KILLED(G08-FIX2-17~20 계열 `test_marker_retry_is_bounded…`) |
| ② 다음 run이 보류 초기화 | C02 서비스 측 set 초기화 | KILLED |
| ② 〃 | C03 새 run 투영이 이전 OPEN·보류 무시 | KILLED(`G08-FIX2-X-PROJECTION`) |
| ② 〃 | C04 읽기 모델이 OPEN·세션 보류 무시 | KILLED |
| ② 〃 | C10 = C02+C03+C04 | KILLED |
| ③ stop의 OPEN run 미확인 | C05 stop이 현재 run 플래그만 사용(FIX1 형태) | **SURVIVED** |
| ③ 〃 | C06 `capture_health_pending`의 canonical OPEN 검사 제거 | KILLED(`G08-FIX2-21`) |
| ③ 〃 | C09 = C05+C06 | KILLED |

C05의 생존은 시험 공백이 아니라 중복 방어 때문이다. stop은 `capture_health_pending`(세션 보류 메모리 사실 + canonical OPEN)도 확인하므로 C05 단독으로는 동작이 바뀌지 않는다. 두 경로를 함께 제거한 C09는 검출된다.

**판정: RECHECKED.**

### R2-3. G08R-12와 G08R-01~10 유지

- **G08R-12: RECHECKED.**
  - F1~F8, P1~P5, `probe_tail_prefix.py`의 최종 요약에 `health_status`가 남지 않는다. marker 성공 여부와 관계없이 같은 최종 상태로 표시된다.
  - `has_unknown=True`·`count_complete=False`·UNKNOWN_TAIL은 유지된다.
  - tail 반례의 첫 줄은 이제 "입력 중지 · 확인된 앱 큐 유실 6 frame …"이며 "판정 보류"가 아니다.
  - 해제 경로 제거 변이 C07은 KILLED다.
- **G08R-01~10: 유지.** 같은 반례를 FIX2 tree에서 다시 실행했다.

| ID | 결과 |
| --- | --- |
| G08R-01 | headless 10 run·Desktop 10 run 모두 정상. 녹음 중단 0 |
| G08R-02 | A1·A2 미상, A3 확인 3840 |
| G08R-03 | 부분 실패 뒤 재복구로 [mic, system] |
| G08R-04 | K36이 전체 회귀에서 실패 0 |
| G08R-06 | 이미 확정 문구 |
| G08R-07 | idle 3,600회에 NO_PACKETS OPEN·CLOSE 각 1, 재시도 섞인 pause 10회에 PAUSE 20/20 |
| G08R-08 | 일시 경합은 HEALTH_RECOVERY_PENDING, 삭제 선행은 DELETE_PENDING |
| G08R-09 | legacy export에 `available=false` 표식 |
| G08R-10 | 닫힌 gate 뒤 경고 2건 보관 |
| G07R-01 | 1440/1440, 2880 |

G08R-05는 R2-4의 변이 결과로 확인했다.

### R2-4. 변이 재적용

정상본(신규 6파일 + app_service·desktop_independent·unit desktop·power·unfinished_recovery)은 **1,268 passed, 182.7초**다. `mutate4.py`는 CRLF를 인식해 원문을 정확히 치환하고, 변이를 한 번에 하나씩 적용한 뒤 복원한다. 검출로 센 것은 rc 1이면서 요약에 failed가 있고 error가 없는 경우뿐이다.

| 변이 묶음 | 결과 |
| --- | --- |
| X01~X11(X04는 문구가 3곳으로 늘어 finalize 위치 X04b로 적응) | 11/11 KILLED |
| Z01~Z10(Z10은 FIX2 drain 문구로 Z10b 적응) | 10/10 KILLED |
| C01~C10 | 8 KILLED, 2 SURVIVED(C05 중복 방어로 동작 동일 — C09로 검출, C08 → G08R-13) |
| **합계 31** | **29 KILLED / 2 SURVIVED / 0 INVALID** |

작성자 M01~M30·Y01~Y10·W01~W12는 재실행하지 않았다.

### R2-5. 새 발견

#### G08R-13 / S3 / OPEN — 건강 transaction의 `busy_timeout=0`이 시험되지 않는다

**재현.** 변이 C08(`src/recoryn/storage/library.py`의 `_health_transaction`에서 `PRAGMA busy_timeout=0`을 `=5000`으로 바꿈)이 1,268건 모두 통과해 생존한다. 작성자 W09는 timeout 원복만 검사한다.

**영향 측정.** `probe_lock_realtime.py`: 두 트랙 10ms 실시간 녹음 중 외부 연결이 EXCLUSIVE lock을 3초 잡는다. 2회차 전체 회귀가 동시에 돌던 중이라 단독 측정이 아니다.

| tree | 트랙당 거부 | root mutex 최장 보유 | live |
| --- | --- | --- | --- |
| 대상 | 111·110 | sealer 2,381ms | DEFERRED |
| C08 사본 | 133·133 | **writer 2,604ms** | OBSERVED, checkpoint가 busy 대기 |
| 기준 b925520 | 99·100 | sealer 2,277ms | – |

**판단.**

- C08이 되돌아오면 consumer의 checkpoint가 root mutex를 잡은 채 SQLite busy를 기다린다. FIX2가 의도한 "건강 쓰기는 녹음 경로를 기다리게 하지 않음"이 깨진다.
- 다만 지금은 기존 sealer 등록 경로가 같은 lock을 root mutex 안에서 기다린다. 그래서 차이가 일부 가려진다.
- 회귀 방지를 위해 "외부 write lock 동안 건강 checkpoint가 즉시 보류되고 consumer root 보유가 짧다"는 시험을 권고한다.

**관찰(G08 범위 밖).** 외부 SQLite lock 동안 sealer 등록이 root mutex를 2.3초 잡아 기준 tree에서도 트랙당 약 100블록이 거부된다. G-P15c·G-P17 영역의 기존 동작이며 G-P08 회귀가 아니다.

### R2-6. 놓쳤을 수 있는 영역

- 1차·RECHECK 1의 미검증 항목(실장비·전원·장기 SQLITE_BUSY·작성자 변이 재실행·1,024행 ID 감사 재계산)은 그대로다.
- 5초를 넘는 외부 lock은 sealer 등록 자체가 실패한다. 이것은 저장 실패 경로이며 건강 보류와 무관하므로 G08 판정에 넣지 않았다.
- 메모리 보류 set(`_deferred_health_sessions`)는 프로세스 수명뿐이다. 재시작 뒤에는 canonical OPEN run과 세션 상태로 미상을 유지한다(P5). 시작 transaction이 아예 남지 않은 run(begin 실패, run 행 없음)은 재시작 전까지 메모리 사실에만 의존하고, 재시작 뒤 legacy 경로 tail로 회복된다. 이 경로는 코드 읽기로만 확인했다.

### R2-7. 측정 메모

- 시간 게이트(RT)는 다른 실행이 없을 때 측정했다.
- `probe_lock_realtime.py`의 세 측정은 2회차 전체 회귀와 동시에 실행했다. 절대값이 아니라 상대 비교로만 사용한다.

### R2-8. 재확인 반례·harness(LF SHA-256)

RECHECK 1의 반례(`probe_fault_matrix.py`·`probe_tail_prefix.py`·`probe_gap_bound.py`·`probe_desktop_closed_gate.py`·`probe_defer_code.py`·`probe_misc.py`·`probe_legacy_partial.py`·`probe_projection_size_real.py`·`probe_desktop_size_warn.py`·`probe_upgrade.py`)는 내용이 같다. `g08c-probe/`에 복사해 재사용했다.

| 파일 | SHA-256 |
| --- | --- |
| `run-full1.sh` | `1aba12db1277214599a6fafb94754365d4f83e8ce9ce33f70ae071e83435550c` |
| `run-full2.sh` | `282dcedc00cf0f8a99a5adae2f236cb538483eff9993c7c6ca4d8504258e07b5` |
| `probe_fix2.py` | `34398fb8e0e567ffa76a6f3806e74e6b19a87261ea8ffac54b65050267c51975` |
| `probe_lock_realtime.py` | `00f8af5c39c5c13fe5a33d61f272a663589aab30ec9dd65b1b7d0233172d0dc2` |
| `mutate4.py` | `3a7bdb752daf307635fe1c0ff2b40499f0dce3236682abd476a1bdffcad626ed` |
| `mutants_fix2.py` | `f33b3400532ab3ca35d659083124da8e53bfb339a680a1b4785d1b36562a0125` |

## RECHECK 3 (FIX3) — tree `c4e2ee1d` 재확인

2026-11-25, 같은 검토자. 대상은 tree **`c4e2ee1db97dee31c99579c0d754b6e8e9e2a65e`**(HEAD 8ca52f8 + G-P08 20파일)다.

- `git diff 8253e8d7 c4e2ee1d` 변경은 4파일(295 insertions / 3 deletions)이다. 제품 변경은 `src/recoryn/storage/library.py` 10줄뿐이고, 나머지는 시험 2파일과 계약 문서다. 계약 문서 LF SHA-256은 `952ea9f06caf2e07ad2113503463a545a17cc4173d45599009546a33f81f838e`다.
- 판정은 `git archive c4e2ee1d | tar -x -C build/review-trees/g08d`에서만 했다. 반례·변이는 PYTHONPATH를 사본 src로 고정하고 import 위치를 assert했다. 비교 대상은 직전 FIX2 사본 `g08c`다.
- 전체 회귀는 요청대로 생략했다. C00이 최종 tree로 돌린다.

**판정: FIX3 수정은 정확하다.** 원인 분석이 맞고, 수정은 "축약 시 표시 + canonical 정확 누계"를 보장한다. G08R-02와 충돌하지 않는다. **새 OPEN 0건**이다. 이전 OPEN G08R-13(S3)은 이번 범위 밖이라 상태를 바꾸지 않는다.

### R3-1. 원인 분석 확인

작성자가 든 원인은 두 가지다. 둘 다 FIX2 사본에서 직접 재현했다.

1. **gap 생략 표식 누락.** `_store_health`의 epoch 16개 축약·top-level 16개 축약과 `_bounded_health_projection`의 byte 축약이 `detail_complete=False`만 쓰고 기존 소비자가 보는 `gap_detail_truncated`를 남기지 않았다.
2. **이전 epoch union 재계산.** 이전 epoch를 호환 view에 옮길 때, 이미 16개로 줄인 `loss_ranges`에 `track_loss`를 다시 적용해 `known_loss_frames`가 작아졌다.

`probe_gap_conservation.py`가 매 checkpoint·pause·복구·재복구·재열기 뒤의 저장 요약(`tracks`와 v2 `epochs[*]`) 전 항목을 검사한 불변식은 다음과 같다.

- I1: `gap_detail_truncated`가 있거나, gaps 합 = `dropped_frames`
- I2: 생략이 없으면 loss_ranges union = `known_loss_frames`
- I3: `media_loss_unknown`이면 `known_loss_frames=None`
- I4: 정확·비중첩 큐 거부만 있을 때 `known_loss_frames` = `dropped_frames`

입력은 고립 큐 거부(consumer를 root mutex로 정지), 실제 크기의 시각·위치, 끝에 비정상 종료 → 복구 2회 → Library 재열기 → 재복구다.

| 시나리오 | FIX2(8253e8d7) | FIX3(c4e2ee1d) |
| --- | --- | --- |
| 2트랙 × 10 run × 20 cycle | **위반 400**(I1 248, I4 152). 예: `tracks.t0 gaps=7680 dropped=9600` | **위반 0** |
| 6트랙 × 9 run × 18 cycle(요약 61.2~61.3KB, `epochs_omitted` 30, 64KiB 경계 근처) | **위반 132**(I1) | **위반 0** |

I4 위반 152건이 원인 2를, I1이 원인 1을 독립적으로 보여 준다. 복구·재열기·재복구 경로에서도 FIX3 위반은 없다.

### R3-2. 다른 축약 경로

`probe_bounded_unit.py`로 `_bounded_health_projection`을 직접 호출해 확인했다.

| 경우 | FIX2 | FIX3 |
| --- | --- | --- |
| B1 halving(트랙당 events 48개) | 표식 없는 불일치 0(gaps가 줄지 않음) | 0 |
| B2 거대 비목록 필드 때문에 마지막 keep-set fallback으로 가는 경우 | 두 트랙 모두 gaps가 사라지고 표식 없음(불일치 2) | 0 — fallback 전 halving 루프가 gaps를 비우며 표식을 남긴다 |
| B2b 거대 트랙 하나(`tracks_omitted=1`) | 불일치 2 | 0 |
| B3 64트랙 × gaps 16 | 불일치 55 | 0(61,306 B, 60KiB 예산 안) |

작성자가 fallback에 별도 표식 코드를 두지 않은 판단(halving이 먼저 표식을 남김)은 B2·B2b로 확인했다.

### R3-3. G08R-02와의 관계

- union은 이제 새 snapshot의 완전한 `loss_ranges`·`media_loss_unknown`에서 한 번만 계산하고, 이전 epoch는 저장값을 그대로 옮긴다.
- `probe_misc.py`의 A1(위치 없음)·A2(TIMESTAMP_ERROR 뒤 점프)는 live·영속 모두 "장치 유실 미상"을 유지한다. A3(정상 시계)는 확인 3840을 유지한다.
- 위 반례의 I3 위반은 0이다.
- `defer_capture_health`·`_deferred_health_view`의 재계산은 `media_loss_unknown=True`를 먼저 세운 뒤 하므로 축약 범위로 확인값을 만들지 않는다(코드 확인).
- **충돌 없음.**

### R3-4. G15 행 반복과 관련 회귀

`g08d_reject_plugin.py`(pytest `-p` 플러그인)는 각 캡처 큐의 N번째 offer마다 포화 거부를 주입한다. 시험 파일은 바꾸지 않았다.

| 주입 | FIX2 | FIX3 |
| --- | --- | --- |
| N=12(`test_idx_ui_tick_and_recording_among_tombstones` 4행, 주입 600회) | **3/3회 FAIL** — `assert 7680 == 48000`·`7680 == 96000`, C00 실패와 같은 `assert_conserved` 386행 | **3/3회 4 passed**(각 70초) |
| N=3(주입 2,400회) | 4 passed | 4 passed |

N=3에서 FIX2도 통과한 이유는 트랙당 거부가 256을 넘어 메모리에서 이미 `gap_detail_truncated`가 켜지기 때문이다. 결함은 고립 거부가 17~256개일 때만 드러난다. 이는 거부 0이던 이전 실행에서 보이지 않은 이유와도 맞는다.

관련 회귀(`tests/unit/test_seal_phases.py`, `tests/integration/test_seal_mutex.py`·`test_app_service.py`·`test_desktop_independent.py`·`test_unfinished_recovery.py`·`test_pending_deletion_restart.py`, `tests/unit/test_desktop.py`·`test_power.py`, `tests/ui` 전체)는 **1,854 passed, 463.45초, 실패 0**이다.

### R3-5. 변이(FIX3 겨냥 4개)

`mutate5.py`, 정상본은 신규 6파일 1,175 passed다.

| 변이 | 결과 |
| --- | --- |
| V1 epoch 축약 표식 제거 | KILLED(G08-FIX3-I01) |
| V2 top-level 축약 표식 제거 | KILLED(I01) |
| V3 byte 축약 표식 제거 | KILLED(U01) |
| V4 이전 epoch union 재계산 복원 | KILLED(I02) |

4/4 KILLED, SURVIVED·INVALID 0이다.

### R3-6. 시간 게이트

신규 6파일 단독(다른 Python 프로세스 0개 확인 뒤, `-W error::ResourceWarning`, offscreen, 고유 basetemp)은 **1,175 passed in 42.34초**(runner 43초)로 60초 게이트 PASS다. 작성자의 58.25초는 이 측정보다 길다. 부하 차이로 보이며 원인은 측정하지 않았다.

### R3-7. 반례·harness(LF SHA-256, `build/review-trees/g08d-probe/`)

`probe_misc.py`는 1차 해시와 같다.

| 파일 | SHA-256 |
| --- | --- |
| `probe_gap_conservation.py` | `ab7148cd4007184d477023c651faa55abe2600c7c1120e0f6ac31b568773f2ee` |
| `probe_bounded_unit.py` | `8df7f7994482c435e4045980a21c2062d49c64f12ad53059f9dbd7794d4fdd04` |
| `g08d_reject_plugin.py` | `2c696718ec0d3616e5d0feb47eba9dba5c2d75fc9a4d041b165377dc5f97f84e` |
| `mutate5.py` | `ef11a6aa749036c16586c5b31a61b3681ce253e9316fd08c0ee63b5a11e53558` |
