# G08 / G-P08 트랙 건강·gap 범위·UNKNOWN_TAIL 계약안

상태: **계약 승인 대기 — 제품 구현·새 시험·mutation 미실행**. 작성자 w5:p8 Codex. 이번 쓰기는 이 문서 하나이며 아래 API·schema·시험 분모는 구현 승인 요청이다. 독립 검토·최종 통합은 별도다.

## 1. 정본·위험·착수 순서

- 정본: `docs/implementation/v1-gap-plan.md`의 G-P08, G01-A의 G1A-13·44·37/GF-04, G1A-36·V-F01/GF-05, `architecture-v1.md`의 시간·오디오/복구 계약.
- 기준 HEAD를 읽어 확인: `9f2cdf2978fa3a161fabdd3bdde5e850a1fcf930`(GD-P01 포함). 작업 트리의 G-P02/G-P04 미커밋 변경은 현 상태 조사에만 쓰며 이 HEAD의 완료 증거로 보지 않는다.
- G-P08 구현은 **G-P04·G-P05·G-P07 push 뒤 C00 신호**로 시작한다. G-P07은 G-P02/G-P06 뒤이므로 해당 변경도 최종 tree에 포함되어야 한다. 착수 시 tree·공유 파일 해시·선행 계약을 다시 고정한다. G04 RECHECK 등 새 요청이 오면 먼저 처리한다.
- 주요 기능 편차는 S2다. 원본 삭제/변조, 끊긴 구간의 정상 녹음 오표시, UNKNOWN을 0으로 확정, 늦은 콜백의 다른 epoch 변경은 S1 관점에서 검증한다. 새 트랙/세션 enum·모델·장치 자동 대체는 만들지 않는다.
- G-P04의 SESSION_LIVE·확정/복구·원본 보존, G-P05의 삭제 우선·재시도, G-P07의 run/epoch 차단과 REC 필요조건을 유지한다. 재부팅 후 미확정 세션 재녹음과 완전한 clock-domain 정렬(GF-06/GF-07)은 이 단위 밖이다.

## 2. 직접 읽어 확인한 현 상태

다음은 작업 트리의 소스/시험 읽기 결과다. 시험 PASS나 실제 장치 동작 관측이 아니다. G01 보고의 과거 시험 숫자는 이 단위의 결과에 합산하지 않는다.

| 근거 | 현재 사실 | 계약이 보강할 점 |
| --- | --- | --- |
| `app/recording.py`의 `_begin_epoch`·`submit`·`_drain` | accepted/dropped 누계를 메모리에서 관리하고 drain 뒤 `epochs`로 영속. QUEUE_DROP의 sequence/시작 시각만 있으며 상세 상한256 | 시작 전 OPEN 표식, 단조 checkpoint, 원인·범위·정확도와 미상 꼬리 |
| `app/desktop.py`의 `_on_health` | 일부 packet 정보를 안전 필터에서 버리고 이벤트 최근256개 보관. 트랙 상태 전이는 없음 | 현재 run/epoch의 안전한 사실을 별도 건강 모델로 전달 |
| `capture/wasapi.py`의 packet 이벤트 | sequence, accepted, frame_count, flags, capture/arrival 시각, device_frame_position을 이미 제공 | backend 변경 없이 활용. SILENT·TIMESTAMP_ERROR·불연속 구별 |
| `app/power.py` | suspend는 명시 pause, 자동 재개 없음 | PAUSE와 SUSPEND 원인 구별, 미완료 ACK 유지 |
| `storage/library.py`의 `record_capture_health`·`recover_session` | 기존 JSON 덮어쓰기, 복구에 UNKNOWN_TAIL 영속 없음. 삭제/live 검사는 존재 | v2 단조 기록·복구 멱등·삭제 우선 유지 |
| `storage/_safe.py:21,73` | 기존 JSON 기본 상한은 **64KiB**, 숫자·중복 키 검증 존재 | 전체 gap 이력을 한 JSON에 무제한 추가하지 않음 |
| G-P04 `app/recovery.py`의 `_known_epochs`·화면 문구 | legacy 누계가 없는 epoch를 `None`으로 표시하는 읽기 모델은 추가됨 | 알려진 prefix+미상 tail을 영속하고 구별하여 표시. 이 UI만으로 GF-05가 완료된 것은 아님 |
| `cli.py`의 `_export`·`_export_contiguous_runs` | export.json에 capture_health 복사, sequence/장치 위치/flag 불연속에서 WAV 분할 | v2 전체 건강 이력 동반, 미상 시간을 압축·보간하지 않음 |

## 3. 사실과 범위의 계약

### 3.1 서로 다른 세 종류를 합치지 않음

1. **미디어 유실 사실:** 큐가 실제 거부한 PCM의 알려진 frame 수, 같은 source 좌표에서 검증된 장치 누락 범위. 수락 frame과 디스크에 검증·보존된 frame도 별개다.
2. **입력 비활성 구간:** 사용자가 pause하거나 suspend 때문에 gate를 닫은 제어 구간. 실제 수집하지 않은 시간이며 “마이크가 잃은 frame 0개”나 복원 가능한 무음으로 바꾸지 않는다.
3. **관측 미상:** 장치 단절 시작점, 미도착 패킷, timestamp 불량, 마지막 영속 누계 뒤 비정상 종료. `lost_frames=None`, `complete=False` 등으로 명시하며 0을 넣지 않는다. UNKNOWN_TAIL은 손실이 반드시 있었다는 주장도 아니다.

모든 범위는 `[start,end)`다. `clock_ref`에는 process_clock_id/run/epoch와 좌표 종류를 둔다. source device frame, source QPC 상관 시각, 앱 제어 관측 monotonic 시각을 구별한다. `arrival_mono_ns`를 capture 시각에 대입하지 않는다. 같은 process_clock_id와 검증된 단조 관측만 제어 구간의 양 끝 비교에 사용하며 UTC 변경·다른 프로세스·재부팅의 값을 직접 빼지 않는다.

### 3.2 gap 사실 DTO

순수 DTO·검증·집계는 신규 `domain/capture_health.py`에 둔다. Qt/DB/장치 SDK 의존은 없다.

| 필드 | 의미 |
| --- | --- |
| session_id / capture_run_id / track_id / epoch_id | 정확한 대상. start/resume마다 새 capture_run_id와 epoch. 식별 불가 legacy tail만 session 범위 허용 |
| event_id / gap_id / ordinal | 중복 제거와 순서. 동일 ID·동일 사실 재전달은 멱등, 동일 ID·다른 사실은 HEALTH_EVENT_CONFLICT |
| reason | QUEUE_DROP, DEVICE_DISCONTINUITY, DEVICE_LOST, PAUSE, SUSPEND, STORAGE_FAILED, NO_PACKETS, UNKNOWN_TAIL의 폐쇄 목록 |
| source | APP_QUEUE / DEVICE / CONTROL / STORAGE / RECOVERY. AI_TAP은 별도 처리 유실이며 원본 오디오 유실에 합산하지 않음 |
| start / end / clock_ref | 같은 좌표의 양 끝 또는 None. 한쪽/양쪽 미상, 열린 gap을 허용. 관측 한계와 알려진 sequence/fragment 범위는 별도 보존 |
| range_quality | EXACT_SOURCE / OBSERVED_CONTROL / UNKNOWN. 실제 큐 거부 범위나 제어 gate 비활성 관측을 장치의 물리적 단절 시점으로 과장하지 않음 |
| lost_frames / count_quality | 음이 아닌 정확한 int 또는 None / EXACT 또는 UNKNOWN. bool·음수·overflow 거부 |
| observation_bounds | 마지막 수락/오류 수신/다음 정상 관측 등의 안전한 경계. 미상 범위의 실제 시작·끝으로 승격하지 않음 |
| open / detail_complete | gap 종료 여부, 상세 보존 완전성. tail/구간 상세가 빠졌으면 완전하다고 표시하지 않음 |

- QUEUE_DROP은 `queue.offer=False`인 실제 입력만 생성한다. frame 수는 정확하며 시간 상관이 없으면 범위는 미상일 수 있다. gate 종료 후 late 입력 거부를 큐 포화 유실로 세지 않는다.
- DEVICE_DISCONTINUITY는 같은 track/epoch·유효한 source 위치·같은 포맷의 앞뒤 사실이 있을 때만 source frame 누락을 계산한다. 위치 역행·포맷/epoch 변경·불확실한 시계는 미상이며 sequence 차이에 일정 packet 길이를 곱하지 않는다.
- DEVICE_LOST/NO_PACKETS는 콜백 수신 시각과 실제 단절 시점을 구별한다. 시작 미상은 유지하고 새 정상 관측은 가능한 종료 관측 경계로만 기록한다. 일반 SILENT는 정상 수락 PCM이다.
- TIMESTAMP_ERROR만으로 실제 오디오 구멍을 만들지 않는다. 수락 PCM과 원본 flag는 보존하고 시간 품질·건강만 낮춘다. DATA_DISCONTINUITY는 별도 장치 유실 관측으로 기록하며 정확한 누락 범위 근거가 없으면 미상이다.
- PAUSE/SUSPEND의 제어 gap은 실제 gate 종료와 명시 resume의 gate 개방 관측에 연결한다. pause 클릭 시각으로 cutoff를 대체하지 않는다. 서로 다른 run이라도 같은 process_clock_id의 관측 구간만 연결하며 sample 수를 추정하지 않는다. suspend 공지가 늦거나 시계 신뢰가 없으면 시작/끝 미상으로 남긴다.
- gap OPEN/CLOSE는 각각의 멱등 이벤트다. close는 기존 gap_id와 같은 좌표·대상을 검사한다. 다른 run의 제어 gap을 닫을 때도 기존 epoch 누계·원본을 수정하지 않는다. 영구 정지·재시작으로 끝을 알 수 없으면 닫힌 정확 범위를 만들어내지 않는다.

### 3.3 이중 합산 금지

기본 표시는 `확인된 앱 큐 유실`, `확인된 장치 유실`, `미상 구간`, `AI 처리 유실`을 **분리**한다. 소스별 누계끼리 단순 합한 “전체 유실”을 제공하지 않는다.

같은 track/epoch/source-frame 좌표에서 정확한 구간들이 있을 때만 interval union으로 알려진 원본 유실을 집계한다. 예: 큐 `[10,20)`, 장치 `[15,25)`는 union 15frame이며 20frame이 아니다. 동일 구간은 10, 인접 `[10,20)`·`[20,25)`는 15다. fragment별 중복 이벤트도 동일 원본 범위를 한 번만 센다. 서로 다른 clock/epoch이거나 위치가 없어 교집합을 모르면 total은 None, 알려진 하한과 소스별 정확 누계만 표시한다. 같은 트랙에서 위치 없는 큐6·장치4이면 알려진 하한은 최소6이지 정확한 합10이 아니다. AI_TAP 유실은 이 union에 포함하지 않는다.

두 트랙의 frame을 하나의 공통 시간 손실로 합치지 않는다. sample rate가 다르면 초 단위도 트랙별이다. 멀쩡한 system 트랙의 bytes·frames·sequence·상태는 mic의 DEVICE_LOST에 의해 변경되지 않는다.

## 4. 트랙 상태·제어·기록 지점

영속 건강 상태는 설계의 **OK / DEGRADED / UNAVAILABLE / STOPPED** 4종이다. 준비 중·장치 단절·저장 실패·일시정지·확정은 별도 reason/control 사실로 구별한다. 건강 OK가 첫 수락이나 원본 디스크 확정 성공을 뜻하지 않으며 REC는 G-P07의 더 강한 조건으로 판단한다.

### 4.1 전이 표

시험 입력 모델은 의미가 다른 7개 template을 사용한다: OK, DEGRADED, UNAVAILABLE(STARTING), UNAVAILABLE(DEVICE_LOST), UNAVAILABLE(STORAGE_FAILED), STOPPED(PAUSED), STOPPED(FINAL). 이벤트는 아래 표의 13종이다. 오래된 run/epoch 이벤트는 어느 상태에서도 새 사실을 쓰지 않는다. STOPPED(FINAL)은 현재 capture run의 종료이며 Session FINALIZED 성공을 뜻하지 않는다. 원본 확정·manifest pending·실패 표시는 기존 영속 상태로 판단한다.

| 입력 template | READY | ACCEPT_GOOD | QUEUE_REJECT / BAD_CLOCK / NO_PACKETS / DEVICE_DISCONTINUITY | DEVICE_LOST | PAUSE_CONFIRMED / SUSPEND_CONFIRMED | STOP_CONFIRMED | STORAGE_FAILED | BEGIN_RESUME | DUPLICATE_EVENT |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| OK | OK | OK | DEGRADED | UNAVAILABLE(단절) | STOPPED(PAUSED) | STOPPED(FINAL) | UNAVAILABLE(저장) | 거부 | 불변 |
| DEGRADED | DEGRADED | OK | DEGRADED | UNAVAILABLE(단절) | STOPPED(PAUSED) | STOPPED(FINAL) | UNAVAILABLE(저장) | 거부 | 불변 |
| UNAVAILABLE(STARTING) | OK | OK | DEGRADED | UNAVAILABLE(단절) | STOPPED(PAUSED) | STOPPED(FINAL) | UNAVAILABLE(저장) | 거부 | 불변 |
| UNAVAILABLE(DEVICE_LOST) | 거부 | 거부 | 거부 | 불변 | STOPPED(PAUSED) | STOPPED(FINAL) | UNAVAILABLE(저장) | 거부 | 불변 |
| UNAVAILABLE(STORAGE_FAILED) | 거부 | 거부 | 거부 | 저장 실패 유지 | 종료 ACK만 기록, PAUSED 성공 금지 | 종료 ACK만 기록, FINALIZED 성공 금지 | 불변 | 거부 | 불변 |
| STOPPED(PAUSED) | 거부 | 거부 | 거부 | 불변 | 불변 | STOPPED(FINAL) | late 오류로 상태 변경 금지 | 새 run/epoch의 UNAVAILABLE(STARTING) | 불변 |
| STOPPED(FINAL) | 거부 | 거부 | 거부 | 불변 | 거부 | 불변 | late 오류로 상태 변경 금지 | 거부 | 불변 |

ACCEPT_GOOD는 양의 PCM 실제 수락·정상 포맷/시계의 새 관측이다. 이 이벤트로 과거 gap/유실 기록을 지우지 않는다. 준비 중 first PCM이 ready보다 먼저 와도 전역 all_sources_ready는 별도이므로 REC를 켜지 않는다. PAUSE/SUSPEND/STOP의 CONFIRMED는 장치 해제와 writer drain/seal ACK가 모두 있다는 입력이며, 단순 요청/timeout을 이 이벤트로 만들지 않는다. 중간 요청은 G-P07 control 상태로 표시한다.

### 4.2 서비스별 책임

- `RecordingService`: 실제 offer/수락/거부, gate cutoff, per-track 누계와 건강 상태, run/epoch, writer 오류, 최종 ACK를 소유한다. hot path는 메모리 사실 갱신만 하고 SQLite·파일 I/O를 하지 않는다. 트랙 단절 시 그 트랙 intake만 닫고 이미 수락한 큐는 그대로 저장한다. 다른 트랙 gate/worker를 닫지 않는다. 전역 저장 실패만 기존 INTERRUPTED·전체 입력 차단 경로를 따른다.
- `DesktopRecorder`: source의 안전한 packet/error/idle 사실에 G-P07 session/run/epoch token을 붙여 전달한다. source wrapper가 고정한 token을 재검사한다. 콜백에서 DB를 쓰지 않는다. error/stopped를 reader 해제 ACK로 오인하지 않으며 실패 source 핸들은 기존 실제 종료 ACK까지 보유한다. 준비/장치 상태와 원본 수락 counter는 분리한다.
- `PowerCoordinator`: `pause(reason="SUSPEND")`를 명시해 일반 PAUSE와 구별한다. suspend 요청 자체와 성공 ACK를 따로 기록한다. wake는 자동 resume하지 않고, 사용자 resume만 새 run/epoch를 만든다.
- 재연결은 **기존 명시 pause→resume**으로 다시 연다. 장치 단절 동안 다른 트랙은 계속 녹음한다. 사용자가 전체 pause를 선택한 뒤 동일 장치·동일 포맷으로 resume하면 새 epoch로 재연결한다. 자동 장치 교체·단독 트랙 재시작 API는 이번 범위에 넣지 않는다. 포맷 변경은 기존대로 재선택/새 계획을 요구한다. 이것은 재부팅 뒤 미확정 세션 재개를 허용하는 변경이 아니다.
- `Library`: v2 사실의 CAS·삭제/live 우선·idempotency·복구를 소유한다. DB lock을 가진 채 capture gate를 기다리거나, capture gate를 가진 채 DB를 기다리는 역순을 만들지 않는다. snapshot 복사와 token 재확인 뒤 영속한다.

## 5. additive v2 저장과 UNKNOWN_TAIL

### 5.1 schema·API 제안

기존 `sessions.capture_health`와 legacy `epochs` 형식은 제거하지 않는다. 기존 JSON 한도64KiB를 공용 상수 변경으로 늘리지 않는다. 전체 사실은 다음 **신규 표 3개**에 두고 기존 JSON/manifest는 제한된 읽기 요약으로 사용한다. G-P09에 세 표·version·변환 상태를 인계한다. CREATE TABLE IF NOT EXISTS 방식의 additive 도입이며 user_version 일괄 변경·기존 행의 무조건 재작성은 하지 않는다.

| 표 | 핵심 키·내용 |
| --- | --- |
| capture_health_runs | PK(session_id,capture_run_id), schema_version=2, health_version, process_clock_id, checkpoint_seq, OPEN/CLOSED/RECOVERED_UNCLEAN, 시작/종료 관측·마지막 영속 watermark |
| capture_health_tracks | PK(session_id,capture_run_id,track_id,epoch_id), 4상태/reason, gate/ACK 사실, 알려진 accepted/queue loss prefix, count_complete, last sequence/fragment, 마지막 영속 관측 |
| capture_health_events | PK(session_id,event_id), run/track/epoch·ordinal·kind, 검증된 gap OPEN/CLOSE/UNKNOWN_TAIL 사실, 제한된 JSON payload, gap_id와 중복 검증 digest |

세 표는 session FK ON DELETE CASCADE를 사용한다. run/track 관계와 식별자를 검증하고, 삭제 tombstone/intent 이후 새 건강 쓰기를 거부한다. 건강 자료가 최소 삭제 journal로 이동하거나 삭제된 미디어를 다시 채택하는 근거가 되지 않는다. 임의 예외 본문·장치 경로·사용자 음성·비밀은 저장하지 않는다.

여기서 트랙의 `count_complete`는 **앱 큐 누계가 종료 cutoff까지 완전한지**를 뜻한다. 장치 유실·제어 구간·UNKNOWN_TAIL을 포함한 전체 오디오 유실의 완전성과 구별한다. CLOSED는 추가 미영속 큐 꼬리가 없다는 종료 사실이며 기존 장치 미상 gap을 지우거나 “전체 유실0”으로 만드는 상태가 아니다.

제안 API는 다음 의미를 갖는다. 세부 DTO는 신규 domain 모듈에 둔다.

- `begin_capture_health(session_id, start_snapshot, *, expected_state_version)`는 유효 CREATED/PAUSED에서 새 run·트랙 OPEN 표식과 RECORDING 전이를 **같은 transaction**에 기록한다. 기존 상태 version·세션 전이 이벤트 계약도 함께 지킨다. 영속 시작 확인 전 input gate를 열지 않는다. writer 시작 실패 시 gate를 열지 않고 소유 자원을 종료 확인한다.
- `checkpoint_capture_health(session_id, snapshot, *, expected_health_version)`는 현재 run/epoch·단조 checkpoint_seq·단조 소스별 누계를 검증하고 변경 사실을 원자 반영한다. 같은 이벤트는 한 번만 기록한다. 오래된 snapshot이 새로운 단절/UNKNOWN을 덮어쓰지 못한다. stale CAS는 재조회·병합하며 값을 조용히 낮추지 않는다.
- `finish_capture_health(session_id, final_snapshot, *, expected_health_version)`는 입력 차단·장치 해제·writer ACK 뒤에만 CLOSED/complete를 기록한다. 단순 thread timeout으로 CLOSED를 만들지 않는다. 상태 PAUSED/FINALIZING 전이는 이 완료 뒤 진행하며 실패 시 성공 표시하지 않는다.
- `capture_health(session_id)`는 v2가 있으면 canonical 사실에서 bounded 요약을 반환한다. `health_schema_version=2`, known prefix·미상 존재·현재 트랙 상태·health_version·상세 생략 여부를 명시한다. legacy epochs는 호환 투영이며 최신8개까지, gap 상세는 트랙당 최근16개까지만 투영할 수 있다. 생략 수와 `detail_complete=False`를 필수로 표시하고 v2 원본 행은 버리지 않는다. legacy-only session의 기존 반환/쓰기 의미는 보존한다.
- `capture_health_details(session_id, *, cursor=None, limit=128, expected_health_version=None)`는 고정 snapshot 기준의 페이징 상세 읽기다. run/track/event를 구별한 행으로 세 표의 사실을 모두 제공한다. limit은 1…256, event payload는 최대4KiB, 요약은 기존64KiB 한도 이내다. 페이지를 다시 요청해도 누락/중복이 없도록 안정적인 종류/ordinal/키를 사용한다. snapshot이 바뀌면 HEALTH_SNAPSHOT_CHANGED로 재조회한다. 현재 원본의 bytes/hash를 바꾸지 않는다.

health_version은 session 전체에서 단조 증가하며 run마다 0으로 초기화하지 않는다. canonical 변경과 sessions.generation/manifest_sync_pending을 같은 transaction에서 반영해 페이지·manifest·export가 같은 snapshot인지 대조할 수 있게 한다. 과거 run의 열린 PAUSE gap을 닫는 이벤트도 새 version을 갖는다.

종료 ACK는 신뢰된 제어 호출자가 실제 source.stop 반환·gate cutoff·writer join에서 얻은 구조화한 receipt로 확인한다. health callback의 running=False나 입력 JSON의 bool만으로 종료를 승인하지 않는다. 이것은 호출자 계약이며 임의 Python 코드에 대한 OS 인증 장치는 아니다. 직접 RecordingService를 쓰는 headless 경로는 외부 source 보유자가 없다는 실행 모드와 gate/writer 종료를 확인한다.

G-P09 인계에는 **세 신규 표, schema_version=2, legacy-only/v2 상태 구분, legacy 투영은 원본 이력의 대체가 아님, 미래 version 안전 거부, 향후 backup/import의 세 표 포함**을 명시한다. 이 단위에서 G-P09의 전체 migration/backup/import workflow를 구현하지 않는다.

### 5.2 checkpoint와 영속 실패

기본 제안은 별도 thread를 만들지 않고 **기존 writer 제어 경로**에서 약1초 간격의 기회성 checkpoint를 기록하는 것이다. PCM 포화 큐의 marker 하나에 의존하지 않고 별도의 bounded 제어 사실/누계 snapshot을 사용한다. source callback·submit에서는 I/O를 하지 않는다. writer가 막히면 1초 내 영속을 보장하지 않으며 마지막 영속 prefix 이후는 미상으로 남길 수 있어야 한다.

한 번에 최대256개 이벤트를 drain하고 남은 사실은 다음 checkpoint로 넘긴다. 상세 버퍼 한도에 닿으면 연속 동일 원인의 구간을 안전하게 coalesce하거나 “상세 일부 미상” 사실을 남긴다. source별 **정확 누계는 버리지 않는다**. 합칠 수 없는 상세가 사라지면 detail_complete=False와 미상 범위를 표시한다. OPEN/CLOSED/UNKNOWN_TAIL 표식은 버퍼 overflow 때문에 버리지 않는다. writer/메타데이터 실패가 있으면 기존 gate 차단·INTERRUPTED·원본 보존 경로를 따르며 정상 저장 완료로 표시하지 않는다.

누계 checkpoint가 원본 파일보다 앞서도 accepted_frames를 “보존된 원본”으로 사용하지 않는다. 보존 frame은 검증된 청크·복구 prefix에서 별도 계산한다. final close marker는 마지막 누계와 실제 종료 ACK 뒤에만 commit한다. 모든 SQLite/파일 commit은 해당 시스템의 flush 가정을 가지며 전원 장애 내구성은 외부 게이트다.

### 5.3 복구 판정

`recover_session`은 기존 G-P04/G-P05의 삭제 이력 확인과 live owner/writer 거부를 **건강 수선보다 먼저** 수행한다. 조회만으로 이력을 고치지 않는다.

| 발견 상태 | 건강 복구 결과 |
| --- | --- |
| 유효 OPEN run | 트랙마다 마지막 영속 prefix를 보존하고 이후에 UNKNOWN_TAIL. lost_frames=None, count_complete=False, 끝 시각 미상. run은 RECOVERED_UNCLEAN |
| 이미 RECOVERED_UNCLEAN | 기존 tail ID/누계 유지. 재복구로 tail 추가·하한 증가·정확값 승격 없음 |
| 유효 CLOSED run | 추가 tail 없음. Session state가 아직 RECORDING이어도 close marker의 ACK 사실을 보존. 세션의 기존 중단/확정 처리와 구별 |
| legacy drain epoch와 PAUSED/FINALIZED | 기존에 영속한 큐 누계는 보존. 실제 유실 정확성의 범위는 legacy 큐 누계뿐이며 장치 유실 전체0으로 확대하지 않음 |
| legacy active 또는 누계 없는 catalog/staging epoch | 확인된 prefix만 보존하고 식별 가능한 track/epoch에 UNKNOWN_TAIL. 아무 track/epoch도 식별 못 하면 session 범위의 UNKNOWN_TAIL. mic/system ID를 임의 생성하지 않음 |
| 삭제 의도/tombstone | 기존 DELETE_PENDING/삭제 경로. 건강 쓰기·미디어 채택0 |
| live owner/writer | SESSION_LIVE 등 기존 안전 거부, 건강 쓰기0 |
| 손상/미지원 미래 건강 version | HEALTH_UNREADABLE / HEALTH_VERSION_UNSUPPORTED로 건강 수선·완료 판정을 보류. 정상 건강0건으로 표시하지 않으며, 원본은 보존 |

tail ID는 session/run/track/epoch/마지막 영속 checkpoint의 안정된 키에서 정한다. tail의 알려진 하한과 frame 누계는 누적 prefix를 복사하되, 미상 tail 자체를 그 숫자나 0으로 바꾸지 않는다. 새 tail 기록·run 상태·필요한 INTERRUPTED 전이는 같은 transaction으로 처리하고 그 뒤 manifest를 투영한다. 복구 도중 kill 후 재시도도 멱등이어야 한다. marker 영속 실패 시 HEALTH_RECOVERY_PENDING을 반환하고 건강 확인 완료로 표시하지 않는다.

현재 커밋에 OPEN marker가 없던 legacy 세션에는 v2와 같은 영속 순서 보증을 소급 적용하지 않는다. CLOSED marker가 없다는 이유로 기록된 정확 prefix를 삭제하지도 않는다. epoch 시작 전에 kill되어 원본 자체가 없을 수 있다는 미상과, 실제로 손상/유실을 확인한 사실을 구별한다.

## 6. UI·복구·내보내기

- MainWindow에 트랙별 상태·원인·확인된 큐 유실·장치 유실·미상 구간을 표시한다. mic 단절/system 지속이면 그 사실과 실제 저장 지속을 함께 표시한다. G-P07의 전체 장치 ready 필요조건을 낮춰 전역 REC를 강제로 켜지 않는다. 일부 트랙 수락은 별도 “system 원본 수락 중 / mic 사용 불가”로 표현한다.
- 단절 후 다음 행동은 명시 pause→장치 확인→resume이다. 자동 대체·자동 resume는 없다. 원본에 인공 무음을 채우거나 gap을 압축하지 않는다. health 상태 표시·이력 조회는 녹음/복구/삭제를 자동 수행하지 않는다.
- 복구 읽기 모델은 “확인된 큐 유실 6frame + 이후 미상”과 “유실 누계 전체 미상”을 구별한다. 검증된 보존 frame·확인된 유실 prefix·UNKNOWN_TAIL은 별도 수치다. 재복구·확정 뒤에도 tail은 남는다. 손상 건강 이력을 “미상 없음”으로 표시하지 않는다.
- 요약에서 생략된 옛 epoch는 “상세 미조회”로 구별하고 상세 API로 읽는다. UI의 페이지 미조회 사실을 실제 유실 미상이나 유실0으로 바꾸지 않는다. 상세 조회는 worker에서 고정 snapshot으로 수행하며 Qt 스레드에서 전체 이력을 동기 읽지 않는다.
- live 화면의 메모리 누계와 마지막 영속 checkpoint는 구별한다. 원본 파일 보존량·영속 누계로 아직 확인되지 않은 관측을 저장 완료로 표현하지 않는다.
- CLI 기존 list/recover/finalize는 안전한 상태 요약을 재사용한다. 새 별도 CLI 명령은 추가하지 않는다. 원본 export는 계속 FINALIZED만 허용하고 기존 불연속 분할을 유지한다.
- v2가 있는 export는 `capture-health.jsonl` 상세 파일을 새 출력 디렉터리에 쓰고 `export.json`에 파일명·SHA-256·행 수·고정 health snapshot version과 bounded 요약을 넣는다. 마지막 export.json은 기존대로 완료 marker다. 상세/요약 중 실패하면 complete를 내지 않는다. 한 readonly snapshot의 상세·요약을 사용하고 삭제/세대 변경을 재검사한다. 새 보호 우회나 Library lock 장기 점유로 녹음 I/O를 막지 않는다.
- legacy-only export는 기존 JSON을 유지하되 건강 정보 부재를 명시한다. UI 표시용 제한된 요약을 전체 이력이라 부르지 않는다. schema를 모르는 옛 소비자의 지원 범위를 과장하지 않으며 미래 버전/누락은 보수적으로 안내한다.

## 7. 경우의 수·분모

### 7.1 유한 대표 집합

아래는 **10개 family의 실행 가능한 대표 의미 행 950개 계획**이다. 실제 pytest node 수·실행 수와 구별한다. family 간 모든 인자의 직적이나 모든 장기 이력의 전수 증명이 아니다. 거부 입력은 분모에서 제거하지 않는다. K의 fixture 인과상 불가능한 24조합만 구체적으로 제외하며 그 근거를 독립 감사한다.

| family / 고유 case ID | 입력·Ω | feasible F | 독립 oracle |
| --- | --- | ---: | --- |
| S / G08-S-001…364 | 상태 template7 × 이벤트13 × token{현재,오래됨}2 × 트랙수{1,2}2 =364 | 364 | §4.1 손으로 쓴 전이·거부 표, 다른 트랙 불변·late 쓰기0 |
| G / G08-G-01…64 | 원인8 × 범위{정확,미상}2 × frame{알려짐,미상}2 × 트랙수2 =64 | 64 | §3 사실 규칙. 인과 근거 없는 “정확”·큐 drop frame 미상·의도적 PAUSE의 손실 수 확정은 거부/명시 미상 |
| D / G08-D-001…144 | 구간관계6 × 출처조합3 × frame확실성2 × 좌표일치2 × 트랙수2 =144 | 144 | interval union·소스별 누계·미상 총계, AI 유실 원본 합계 제외 |
| K / G08-K-01…36 | kill시점10 × 마지막 현재 run checkpoint{없음,0,6}3 × 트랙수2 =60 | **36** | §7.2 인과 제약. OPEN이면 prefix+UNKNOWN, CLOSED이면 tail 없음, 원본 hash 불변 |
| R / G08-R-001…224 | 건강{OPEN,UNCLEAN,CLOSED,LEGACY유효,LEGACY누락,미래,손상}7 × 삭제{없음,DB의도,journal의도,tombstone}4 × live2 × {첫복구,재복구}2 × 트랙수2 =224 | 224 | 삭제/live 우선 쓰기0, UNKNOWN 멱등·미래/손상 안전 보류 |
| O / G08-O-01…16 | barrier 경쟁4 × 양순서2 × 트랙수2 =16 | 16 | §7.3의 선형화·counter/event 단조성 |
| U / G08-U-01…30 | 표시{확인0,확인6+tail,tail만,선택트랙단절,legacy미상}5 × 트랙수2 × 경로{live,복구,export}3 =30 | 30 | 미상≠0, 일부 트랙 지속·G-P07 REC 조건, export 전체 이력·hash |
| T / G08-T-01…24 | §7.4 타입/identity/손상 named case24 | 24 | 안전한 거부·기존 사실/원본 불변 |
| C / G08-C-01…24 | 시계6 × gap{PAUSE,DEVICE_LOST}2 × 트랙수2 =24 | 24 | 같은 시계의 관측 구간만 연결. 물리적 단절 시작을 관측 시점으로 확정하지 않음 |
| B / G08-B-01…24 | 한도 경계{−1,정확,+1}3 × 대상4 × tail존재2 =24 | 24 | payload/버퍼/요약/페이지 한도·detail_complete·tail 보존 |
| **합계** | 364+64+144+36+224+16+30+24+24+24 | **950** | 계획 수치, 실행 증거 아님 |

S의 token 과거는 같은 세션의 이전 run 또는 epoch 콜백 대표다. 상태 표의 13종은 READY/ACCEPT_GOOD/QUEUE_REJECT/BAD_CLOCK/NO_PACKETS/DEVICE_DISCONTINUITY/DEVICE_LOST/PAUSE_CONFIRMED/SUSPEND_CONFIRMED/STOP_CONFIRMED/STORAGE_FAILED/BEGIN_RESUME/DUPLICATE_EVENT다. source template의 제어 전제를 fixture에 고정하며 정상 거부도 F에 포함한다. 운영상 후속 이력은 별도 제한 상태 모델로 보강하고 이 364가 모든 상태 이력을 덮는다고 하지 않는다.

G의 정확 범위는 source-frame 또는 검증된 제어 관측 범위의 근거를 함께 주는 입력이다. DEVICE_LOST 콜백만 주고 물리 단절 시작을 정확히 아는 것으로 만들지 않는다. PAUSE/SUSPEND의 frame 알려짐 대표는 손실 수를 확정하려는 잘못된 입력으로 구성하여 거부를 검증한다. UNKNOWN_TAIL의 알려진 frame 대표도 거부 대상이다.

D의 구간관계는 분리/인접/동일/포함/부분중첩/위치없음, 출처조합은 큐+장치/큐+AI/큐+장치+AI다. 서로 다른 epoch/clock은 숫자 범위가 같아도 같은 원본으로 dedup하지 않는다. 위치없음·미상 frame은 정확한 전체 합을 내지 않는다. 두 트랙 fixture는 첫 트랙에 해당 사실을 주고 다른 트랙의 정상 수락을 별도 oracle로 관측한다.

### 7.2 kill 지점과 feasible 산식

소유한 자식 프로세스·합성 PCM·fake source·실제 임시 SQLite만 사용한다. 아래 경계에 원자 ready marker/Event를 놓고 자식 PID를 확인한 뒤 kill한다. 기존 사용자 프로세스를 종료하지 않는다. 기본 두 트랙의 sample rate는 같게 두어 원본 bytes oracle를 단순화하며, 별도 C/D/T에서 좌표·포맷 차이를 시험한다.

| 시점 | 의미 | 가능한 현재 run의 마지막 checkpoint |
| --- | --- | --- |
| K0 | begin transaction commit 전 | 없음만. gate 미개방·현재 run 수락0 |
| K1 | OPEN commit 뒤 첫 block 전 | 0만 |
| K2 | PCM 수락 뒤 미봉인 | 0 또는6 |
| K3 | 큐 거부 뒤 다음 checkpoint 전 | 0 또는6 |
| K4 | checkpoint commit 직후 | 0 또는6 |
| K5 | 청크 게시 뒤 최신 누계 checkpoint 전 | 0 또는6 |
| K6 | gate 종료 뒤 writer ACK 전 | 0 또는6 |
| K7 | 실제 writer ACK 뒤 CLOSED commit 전 | 0 또는6 |
| K8 | CLOSED commit 뒤 PAUSED 상태 commit 전 | 0 또는6 |
| K9 | CLOSED와 PAUSED 상태 commit 뒤 | 0 또는6 |

6은 **앞서 이미 영속한 큐 유실6frame**이다. K2~K9 fixture는 그 뒤 새 입력/종료를 진행할 수 있다. K0/K1에서 현재 run 누계6이 있을 수 없고, K1 이후 OPEN 표식 없이 현재 run을 시작할 수도 없다. 따라서 각 시점 허용 checkpoint 수는 `1+1+8×2=18`, 트랙수2를 곱해 **F=36**, Ω60 중 제외24다. 이전 완료 epoch의 누계는 이 차원의 “현재 run checkpoint”에 섞지 않는다.

K0는 새 tail을 만들지 않는다. K1~K7은 관측된 손실이 0처럼 보여도 OPEN 이후의 완전성을 증명하지 못하므로 UNKNOWN_TAIL이다. K8/K9는 정상 close 사실이 있어 추가 tail이 없다. 기존 media prefix kill 지점(payload fsync/journal fsync/bundle 게시/catalog commit)은 기존 시험의 원본 보존 증거와 연결하되, 그 시험이 이 신규 36개 건강 경계를 실행했다는 주장으로 쓰지 않는다.

### 7.3 경쟁·시계·버퍼

O의 경쟁4는 (1)checkpoint snapshot↔장치 단절 이벤트, (2)단절 콜백↔다른 정상 트랙 packet, (3)pause cutoff↔마지막 submit, (4)CLOSED commit↔늦은 checkpoint다. 각각 두 내부 단일 이벤트의 선행 순서를 barrier로 고정해 2가지씩 실행한다. submit 선행이면 수락 후 보존, cutoff 선행이면 신규 수락0이다. 장치 실패가 checkpoint 이후여도 미영속 tail을 허용할 뿐 이전 사건으로 상태를 정상화하지 않는다. CLOSED 뒤의 낡은 checkpoint는 거부한다. 삭제↔복구 양순서는 R의 부정 fixture와 기존 G-P05 시험을 함께 재사용하며 추가 실행은 별도 증거로 기록한다.

C의 시계6은 같은 clock 증가/같은 시각/역행/새 process_clock_id/anchor 없음/source 시각 무효다. 시각이 같으면 관측 제어 구간 길이0은 가능하지만 유실 frame0을 뜻하지 않는다. 재부팅/시계 역행에서는 정확 duration을 만들지 않는다.

B의 대상4는 checkpoint 상세 버퍼256개, 이벤트 payload4KiB, 기존 요약64KiB, 페이지 limit256이다. 경계 초과는 안전한 거부 또는 명시 상세 불완전 표시이며 기준을 숨겨 전체 이력처럼 보이지 않는다. 알려진 누계·CLOSED/OPEN·UNKNOWN_TAIL 표식과 canonical event는 보존한다. summary 생략이 원본 이벤트 삭제가 되지 않는다.

### 7.4 타입·손상 24행

T01~24는 순서대로 (01)frame=True, (02)frame 음수, (03)frame>2^63−1, (04)frame="0", (05)NaN 시각, (06)음수 시각, (07)끝<시작, (08)같은 범위의 clock 불일치, (09)빈 track ID, (10)다른 session ID, (11)과거 epoch, (12)미래 run token, (13)동일 event ID/동일 payload, (14)동일 event ID/다른 payload, (15)checkpoint_seq 감소, (16)known 누계 감소, (17)누락된 close ACK, (18)필수 구조화 receipt를 bool로 대체한 snapshot, (19)미래 schema version, (20)손상 JSON/중복 key, (21)절단 event payload, (22)삭제 의도 뒤 건강 쓰기, (23)legacy record_capture_health로 v2 표식을 지우려는 입력, (24)UNKNOWN_TAIL lost_frames=0이다. 13은 완전 멱등, 나머지는 거부/관측 미상·기존 사실 불변을 검증한다. bool 입력을 OS 종료 증명으로 승인하지 않으며 실제 caller의 종료 ACK 사실을 검사하는 통합 시험을 결합한다.

### 7.5 독립 oracle와 수치 감사

- 상태 기대 표·gap 허용 조합·kill 기대 결과·구간 tuple은 시험에 **손으로 고정**한다. 제품 전이표/validator/renderer를 import하여 expected를 생성하지 않는다. 제품 interval union을 기대값으로 다시 호출하지 않는다.
- interval oracle는 작은 정수 source frame을 집합으로 펼쳐 union 크기를 계산한다. bytes/hash/frame/sequence 관측은 fake 제출 기록·파일 파서·독립 checksum에서 얻는다. accepted counter와 실제 보존량을 같다고 가정하지 않는다.
- UNKNOWN은 `None`·count_complete·tail marker와 “0을 주장하지 않음”을 모두 확인한다. known prefix6을 없애지 않으며 새 tail을 여러 번 더하지 않는다. 재복구 후 이벤트 ID 집합·누계·원본 hash는 불변이다.
- K의 기대 허용 조합 목록은 생성기와 별도 상수로 고정하고 60−24=36을 독립 산출한다. family별 tuple→case ID manifest로 missing/duplicate/extra=0을 감사한다. overlap하는 요구를 다른 family에서 확인해도 기존 시험 node 수나 과거 PASS를 합산해 숫자를 부풀리지 않는다.
- 추가 무작위 상태열은 고정 seed/bound와 실패 trace를 기록하는 보강이다. 장시간 실장비, power-loss, OS의 실제 절전·장치 교체·드라이버 시계 정확도는 미검증 외부 게이트다.

## 8. 기존 시험과 새 계층

| 기존 node | 유지/보강 관계 |
| --- | --- |
| `tests/integration/test_app_service.py::test_full_queue_close_preserves_last_drop_and_cutoff` | 큐 유실6·수락6·late 입력 거부·writer ACK 보존. v2 known prefix와 정확 구간을 추가 대조 |
| 같은 파일 `test_storage_failure_interrupts_without_claiming_finalized`, `test_capture_health_write_failure_cannot_leave_recording_state` | INTERRUPTED·원본 보존 유지. 영속 실패 주입 지점이 새 canonical API로 옮겨가면 기존 실패 계약을 유지해 fixture 적응 |
| `tests/integration/test_desktop_independent.py::test_disconnect_and_timestamp_health_remain_visible_without_replacement` | 현재 단일 트랙 이벤트 표시만. 신규 두 트랙 통합으로 다른 트랙의 수락/파일 지속 검증 |
| 같은 파일 `test_pause_resume_keeps_simulated_suspend_gap_and_epoch_source_map` | 새 epoch·기존 원본/분할 보존. 신규 PAUSE/SUSPEND 관측 범위와 미상 구별 |
| `tests/unit/test_power.py::test_suspend_requires_explicit_new_epoch_resume_and_keeps_originals` | 자동 resume 금지와 새 epoch 유지. suspend 이유를 별도 기록 |
| `tests/integration/test_process_crash.py::test_actual_process_kill_preserves_exact_prefix` | 기존 네 미디어 경계의 bytes oracle 유지. 신규 K는 건강 marker/counter 경계로 별도 실행 |
| `tests/unit/test_storage.py::test_health_and_cross_thread_writes_survive_reopen` | legacy-only health round trip·manifest 의미 유지. v2 추가가 legacy 값을 몰래 재해석하지 않음 |
| `tests/e2e/test_recording_control.py::test_export_splits_a_source_gap_inside_one_chunk` | 원본 불연속을 WAV로 압축하지 않는 기존 oracle 유지. v2 상세/요약·hash 동반 검증 |
| G-P04/G-P05/G-P07 시험 | live/삭제 우선, 복구 멱등·검증된 보존량·ACK, REC 시작 조건과 run/epoch 늦은 입력 차단 회귀 |

위 node는 소스를 확인한 연결이며 이번 문서 단계에서 재실행하지 않았다. 새 시험 파일6개를 제안한다: `tests/unit/test_track_health.py`(S/G/T/B), `tests/property/test_track_health_case_space.py`(D/C·manifest·제한 모델), `tests/integration/test_track_health.py`(두 트랙·O/R), `tests/integration/test_health_crash.py`(K 소유 자식), `tests/ui/test_track_health_ui.py`(U live/복구·G-P07 표시), `tests/e2e/test_health_export.py`(U export·snapshot/hash/완료 marker). 의미 행과 pytest node는 따로 보고한다.

## 9. mutation 계획

**24개 계획, 실행0.** 정상본 PASS 뒤 OS TEMP 사본에 pyproject·src·tests·필요 scripts/packaging을 복사하고 실제 import origin을 확인한다. 각 mutant는 한 번에 하나씩 적용하며 목표 assertion FAIL만 검출로 센다. import/수집 실패·timeout·권한 오류는 검출에서 제외한다.

| ID | 결함 | 목표 |
| --- | --- | --- |
| M01 | mic 단절 때 모든 트랙 gate 닫기 | S/O의 다른 트랙 bytes·수락 지속 |
| M02 | stale run/epoch callback 허용 | S/T의 새 상태·counter 불변 |
| M03 | SILENT를 DEVICE_LOST로 취급 | S/U의 정상 무음과 REC 조건 |
| M04 | READY로 단절 상태를 같은 epoch에서 정상화 | S의 UNAVAILABLE(단절) 거부 |
| M05 | PAUSE 요청 시각을 ACK 전 cutoff로 확정 | O/C의 실제 gate·ACK 우선 |
| M06 | SUSPEND를 일반 PAUSE로 저장 | G/C의 원인·명시 resume |
| M07 | 큐 거부 frame 대신 sequence 차이×고정길이 | G/D의 가변 packet·정확 누계 |
| M08 | 큐+장치 유실 단순 합 | D의 중첩 union15 |
| M09 | 다른 epoch의 동일 좌표를 dedup | D의 좌표 분리 |
| M10 | AI_TAP 유실을 원본 유실에 더함 | D의 원본 합계 불변 |
| M11 | 미상 frame을 0으로 변환 | G/U/T24 |
| M12 | OPEN 표식 전에 input gate 개방 | K0 및 begin 실패의 수락0 |
| M13 | 복구 시 OPEN run에 tail 생성 안 함 | K1~7/R |
| M14 | tail 생성 때 known prefix6 지움 | K/R/U |
| M15 | 재복구 때 tail 중복 추가 | R의 이벤트 ID·누계 멱등 |
| M16 | writer ACK 전에 CLOSED commit | K6~7/O의 tail·성공 미표시 |
| M17 | RECORDING 상태면 CLOSED에도 tail 추가 | K8의 tail 없음 |
| M18 | 늦은 checkpoint가 누계를 낮춤 | O/T15~16 |
| M19 | legacy 누계 부재를 known0으로 표시 | R/U의 legacy 미상 |
| M20 | 삭제/live 검사 전에 건강 복구 쓰기 | R/T22의 쓰기0·원본 부활0 |
| M21 | 버퍼 초과 시 UNKNOWN 표식/정확 누계 버림 | B의 canonical 이력·하한 보존 |
| M22 | 다른 clock의 gap 시각 직접 차감 | C의 미상 유지 |
| M23 | export 상세 실패 뒤 완료 marker 기록 | U/E2E의 complete 미생성 |
| M24 | 요약의 상세 생략 flag 제거 | B/U의 제한 요약과 전체 이력 구별 |

## 10. 정확한 후속 쓰기 범위·대안·수락 게이트

요청 범위는 **17파일 = source9 + 신규 시험6 + 기존 시험1 + 문서1**이다. 제품 구현은 이 계약 및 범위 승인과 선행 push/C00 착수 신호 전에는 시작하지 않는다.

| 구분 | 파일 |
| --- | --- |
| 신규 domain 1 | `src/recoryn/domain/capture_health.py` |
| app 수정 5 | `src/recoryn/app/recording.py`, `src/recoryn/app/desktop.py`, `src/recoryn/app/power.py`, `src/recoryn/app/recovery.py`, `src/recoryn/app/status.py`(G-P07에서 신규 도입 예정) |
| 저장/UI/CLI 수정 3 | `src/recoryn/storage/library.py`, `src/recoryn/ui/main.py`, `src/recoryn/cli.py` |
| 신규 시험 6 | `tests/unit/test_track_health.py`, `tests/property/test_track_health_case_space.py`, `tests/integration/test_track_health.py`, `tests/integration/test_health_crash.py`, `tests/ui/test_track_health_ui.py`, `tests/e2e/test_health_export.py` |
| 기존 시험 1 | `tests/integration/test_app_service.py` |
| 계약·결과 1 | `docs/testing/g08-track-health-cases.md` |

`capture/wasapi.py`·`capture/queue.py`·`domain/__init__.py`·`storage/_safe.py`·원본 journal/serializer·audio 정렬·content/security/provider·공용 pyproject는 범위 밖이다. 기존 시험 추가 수정은 실제 실패와 필요한 수정 범위를 보고하고 먼저 승인받는다. 세 신규 표 인계 사항은 이 문서에 남기고 G-P09 정본 수정은 C00 소유다.

| 대안 | 장점 | 한계/권고 |
| --- | --- | --- |
| 기존 JSON에 모든 이력 추가 | 초기 연결 단순 | 현재64KiB 한도와 장시간 이력에 부적합. 공용 한도 일괄 증가는 피함 |
| 마지막 drain만 기록 + crash 때 전부 unknown | 작은 변경 | 알려진 prefix가 없어 원인 분석이 약함. 시작 marker+기회성 checkpoint 권고 |
| 모든 packet마다 SQLite 기록 | 누계 최신성 향상 | hot path I/O·캡처 지연·DB 경합. 채택하지 않음 |
| 원본 block journal에 gap/event kind 도입 | 원본 옆에서 복구 가능 | serializer·기존 parser·무결성/호환 범위 확대. 이번에는 additive 건강 표 권고 |
| 단절 트랙 자동 재연결/대체 | 수동 조작 감소 | 장치·epoch·권한·다른 트랙 저장 경합이 커짐. 기존 명시 pause/resume로 제한 권고 |
| 원인별 누계 단순 합 | 표시 간단 | 중첩/AI/미상 과대·과소계상. 소스별 표시+검증 가능한 union만 권고 |

후속 구현은 offscreen·기존 오프라인 환경·`-p no:cacheprovider`·OS TEMP 고유 basetemp·bytecode 비활성으로 실행한다. 신규6파일, 기존 recording/desktop/storage/power/process crash/export, `tests/ui` 전체와 선행 G-P04/P05/P07 회귀를 포함한다. 정상본 PASS·case ID950 missing/duplicate/extra=0·K의 제외24 독립 감사·skip0, mutation24 결과의 killed/survived/invalid 구분, ruff check/format check·`python -m mypy src/recoryn scripts packaging`을 요구한다. 가능하면 정확한 선행 HEAD+승인 파일 사본에서 전체 오프라인 회귀도 실행한다.

신규6파일 합계 시간을 측정하고 **60초 초과 시 분모를 축약하기 전에 측정값·원인·최적화안을 먼저 보고**한다. 자식 fixture는 소유 PID·원자 barrier·종료 확인을 사용한다. 네트워크·실제 장치·모델·계정·설치 없이 실행하고 실제 절전/장치/전원 차단 증거와 구별한다.

현재 수행 결과는 문서·코드·시험 소스 조사와 계약·분모 설계뿐이다. 제품 변경0, 신규/기존 시험 재실행0, mutation0, 장치 검증0이다. C00 요청 결정은 (a) 제어 구간/유실/미상 분리와 union oracle, (b) additive 표3개·기존64KiB 요약·G-P09 인계, (c) OPEN/checkpoint/CLOSED·UNKNOWN_TAIL 멱등과 실패 정책, (d) 명시 전체 pause/resume 재연결·다른 트랙 지속, (e) UI/상세 export·17파일 범위, (f) 계획950행/24 mutation·시간/회귀 게이트다.

## §개정 요청

### 대조 기준·직접 확인한 범위

2026-11-23 C00의 G08 재대조 배정에 따른 추가 계약 요청이다. 승인 원문 **307행, LF SHA-256 `8f8c31f4ff91c32220bd1fa2b7f164b28acac9ec23211f12264c6a403a1345f1`**은 바이트 그대로 보존한다. 원문의 “승인 대기”는 당시 이력이며 C00의 (a)~(f) 승인은 유효하다. 아래 개정은 별도 승인을 요청하며 제품·시험 구현 권한을 앞당기지 않는다.

- 실제 코드·시험 소스는 `git show 8e09b62:<경로>`, `git show 5317e250:<경로>`에서 읽었다. 관련 13파일(app의 recording/desktop/power/recovery, storage의 library/chunks/_coordination, capture의 queue/wasapi, cli, ui/main, test_app_service, test_unfinished_sessions)을 각각 저장해 비교했고 **13파일 모두 두 tree에서 동일**했다. G-P06의 다른 변경이나 전체 tree가 같다는 뜻은 아니다.
- G-P05는 승인 계약 §2·§3과 배정표 G05 행을 기준으로 읽었다. live delete는 의도 기록 뒤 DELETE_PENDING/SESSION_LIVE로 보류하며 G04-T-RECORDING_LIVE-DELETE의 기대를 바꾸기로 C00이 결정했다. 문서 뒤의 작성자 구현 설명은 최종 push tree의 직접 검증과 구별한다. 작업 트리 G-P05 src를 구현 근거로 사용하지 않았다.
- G-P07은 승인된 개정 `aea79c0ef55e5f417641412107a1b585134b2f3d450ab470c508a3aaaed81b85`와 배정표 G07 행을 기준으로 했다. G-P15는 통합 계획 G-P15 행과 배정표 G15 행의 문제·소유권을 기준으로 했다. 추가로 읽은 `g15-seal-mutex-cases.md`의 pipeline은 **계약 초안**이지 승인·구현 완료 사실이 아니다.
- 아래 `tree:파일:행`은 해당 Git 객체의 줄번호다. 직접 수행한 것은 소스·문서 읽기, 두 tree의 해당 파일 비교, 분모·쓰기 목록 산술 감사다. 이번 배정에서 제품 변경·시험 실행·mutation·정적 검사·성능 재측정은 하지 않았다. G-P04·GT-P03·G-P15 문서/채팅의 측정값을 이번 G08 실측으로 옮기지 않는다.

### 1. QUEUE_DROP의 생산자·누계·원인 경계

| 실제 근거 | 확인한 사실 | 계약 보강 요청 |
| --- | --- | --- |
| `8e09b62:src/recoryn/capture/queue.py:43` | 포화로 새 입력을 거부할 때 55~57행에서 drop을 센다. 닫힌 큐의 False(49~50행)는 drop을 세지 않음 | False 하나만으로 QUEUE_DROP을 만들지 않는다. 실제 열린 intake에서 용량 초과로 offer가 거부한 사실이 근거다 |
| `8e09b62:src/recoryn/app/recording.py:139` | gate 비활성이면 141~142행에서 즉시 False. 실제 offer 뒤 154행 accepted, 157행 dropped를 누계하고 166행에 QUEUE_DROP 기록 | 현재 gate와 offer의 선형화 관계를 유지. gate 종료 뒤 late 입력은 queue loss에서 제외. 변수 길이 packet의 실제 frame_count를 합산하고 거부 건수×고정 길이로 대체하지 않음 |
| `8e09b62:src/recoryn/capture/wasapi.py:417` | submit 반환 뒤 accepted와 frame_count를 packet health로 다시 알린다(425~435행). stopped도 accepted/rejected 누계를 제공(458~465행) | backend의 accepted=False 또는 rejected_frames를 APP_QUEUE 누계에 다시 더하지 않음. RecordingService의 실제 offer 관측이 앱 큐 유실 정본. backend 반복 통지는 관측 대조에만 사용 |
| `8e09b62:src/recoryn/app/desktop.py:93` | meter는 submit 결과와 별개로 갱신(101행). `_on_health`는 packet의 많은 위치/시각 필드를 버리고 최근 256개만 보관(121~139행) | G-P07 token을 고정한 건강 경로에 필요한 typed 위치·시각을 전달하되 meter·최근 경고 목록을 정확 누계 원장으로 사용하지 않음. backend 변경 권한은 추가하지 않음 |
| `8e09b62:src/recoryn/app/recording.py:159` | 인접 sequence drop을 합치고, 상세 256개 초과는 gap_detail_truncated로 표시. 총 dropped_frames는 계속 증가 | 기존 legacy gap과 신규 canonical 이벤트를 둘 다 다시 더하지 않음. checkpoint는 누적 prefix의 단조 교체/CAS이며 checkpoint별 누계를 합산하지 않음. 상세 생략은 정확 소스 누계를 지우지 않음 |

앱 큐 유실·장치 보고 유실·입력 비활성·AI 처리 유실의 구분 및 원문 §3.3의 interval union은 그대로 유지한다. 같은 sequence의 queue 거부와 backend packet 통지를 두 gap으로 세지 않는다. 장치의 실제 source-frame 구간과 큐 구간이 같은 좌표임을 증명한 경우만 union한다. 장치 packet 위치가 없으면 큐 누계와 장치 누계를 더한 “정확 전체 손실”을 만들지 않는다.

G-P15 문제의 **코드 경로**도 직접 확인했다. `8e09b62:src/recoryn/app/recording.py:201`은 소비자 thread에서 seal과 등록을 동기로 수행한다. `8e09b62:src/recoryn/storage/chunks.py:395`는 root mutex를 잡아 `_seal`을 호출하고, 423~435행에 sync·descriptor 기록·scan_prefix·rename·verify_bundle이 있다. 이 시간이 길어져 포화된 큐에서 발생한 실제 거부도 QUEUE_DROP이다. G08이 이를 숨기거나 STORAGE_FAILED/DEVICE_LOST로 바꾸지 않는다. 구체적인 0.9~1.9초 보유 등은 C00·기존 문서의 관측이며 이번에는 재측정하지 않았다.

시험 oracle는 환경 부하에서 “QUEUE_DROP 0”을 보편 조건으로 두지 않는다. 제어한 fake offer·합성 PCM 입력 기록으로 `거부 frame 합 = 앱 큐 유실`, 성공 drain 뒤 `저장 frame 합 = 수락 frame 합`, `저장 bytes = 수락 입력의 순서 있는 bytes`를 비교한다. writer 실패·불완전 drain에서는 마지막 등식을 성공으로 주장하지 않고 검증된 보존량을 따로 표시한다. queue loss가 있더라도 수락 후 누락과 구별해야 한다.

### 2. G-P04 복구·확정 결과를 건강 집계에 연결하는 방법

| 실제 근거 | 보강 요청 |
| --- | --- |
| `8e09b62:src/recoryn/app/recovery.py:92`의 `_known_epochs`는 dropped_frames 누락을 0으로 읽고(105행), 잘못된 타입·음수를 0으로 바꾸며(106행), 같은 epoch 값을 합함(108행) | legacy도 정확한 int 누계 근거가 있어야 known0/known6이다. 누락·bool·음수·문자열·충돌한 중복은 “미상/확인 불가”로 표시하고 원래 legacy 저장 행은 수정하지 않음. v2가 있으면 canonical 자료를 정본으로 사용하며 bounded legacy 투영을 다시 더하지 않음 |
| `8e09b62:src/recoryn/app/recovery.py:182`·`:204`는 catalog 예상량과 `verified_chunk_ids`에 속한 보존량을 분리 | 이 G-P04 수정을 유지. 건강 accepted counter·lost prefix·UNKNOWN_TAIL을 verified_chunk_ids나 복구 frame으로 대체하지 않음. 검증된 청크만 보존량에 포함하고 missing/candidate·ALREADY_RECOVERED 정보 유지 |
| `8e09b62:src/recoryn/storage/library.py:712`는 세션 claim 아래에서 삭제/live를 먼저 확인하고, `:848`에서 검증된 ID를 반환 | 건강 복구도 같은 claim과 짧은 상태 재확인 경계에 연결. 검증/열거/해시는 root mutex 밖에 두고, 건강 tail commit 직전에 삭제 권위를 다시 확인. 복구량이 0이어도 OPEN marker가 있으면 해당 식별자의 tail이 필요할 수 있음 |
| `8e09b62:src/recoryn/storage/library.py:1027`은 recover_session 뒤 바로 FINALIZING·finalize_session을 진행 | 건강 수선 실패/손상/미래 version으로 DEFERRED이면 이 결과를 무시하고 확정 성공으로 진행하지 않도록 원문 §5.3의 보류 의미를 확정 호출부까지 명시. 단순 UNKNOWN_TAIL 존재는 확정 금지가 아님: 미상임을 정상 기록한 복구와 건강 판정 자체를 못 한 경우를 구별 |
| `8e09b62:src/recoryn/app/recovery.py:257`의 finalize_lines는 세션 확정 결과와 nested recovery를 함께 표시 | 건강 결과를 additive 구조화 필드로 전달하고 UI·CLI가 같은 결과를 표시. “미디어 검증 완료”, “건강 prefix+미상 tail”, “건강 판정 보류”를 별개로 표현. 읽기 모델이 tail을 새로 쓰거나 건강 정상0건으로 추정하지 않음 |

구조화한 건강 복구 결과에는 상태와 닫힌 code를 둔다. 유효 CLOSED, RECOVERED_UNCLEAN, legacy 미상은 관측 의미가 서로 다르다. HEALTH_RECOVERY_PENDING·HEALTH_UNREADABLE·HEALTH_VERSION_UNSUPPORTED는 건강 판정 보류다. 기존 media 경고·details·verified_chunk_ids·manifest_sync_pending·G-P04 확정 멱등 결과는 삭제하거나 같은 필드로 덮어쓰지 않는다. 건강 보류 중 이미 보존·검증한 bytes도 그대로 둔다.

UNKNOWN_TAIL 판단은 Session state나 catalog 청크 개수로 대신하지 않는다. OPEN이면 마지막 **영속 checkpoint prefix 뒤**가 미상이며, accepted_frames−verified_frames를 계산해 tail 손실량으로 확정하지 않는다. 누계 checkpoint가 미디어 게시보다 앞설 수 있고 반대도 가능하다. 정상 CLOSED에도 장치 유실 미상 gap은 남는다. FINALIZED라는 사실만으로 기존 미상 tail을 없애지 않는다. 재복구·이중 확정·프로세스 재시작 후에도 안정된 tail ID와 prefix는 유지한다.

내보내기 연결도 기존 경계를 보존한다. `8e09b62:src/recoryn/cli.py:142`는 FINALIZED만 허용하고, 174행에 bounded capture_health를 복사하며 177행에서 마지막 export.json을 쓴다. G08은 같은 health snapshot의 상세 JSONL·hash·행 수를 먼저 완성하고 완료 marker를 마지막에 게시한다. 도중 삭제 권위나 health_version이 바뀌면 완료로 표시하지 않는다. 미상 tail을 무음 frame으로 채우거나 WAV 시간을 압축하지 않는다. 4GiB 분할은 G-P10 소유이며 이번 개정으로 가져오지 않는다.

### 3. checkpoint·종료 ACK와 G-P15의 선후 관계

현재 `_drain`은 단일 writer join 뒤 235행 history를 만들고 238행 건강 자료를 기록한다(`8e09b62:src/recoryn/app/recording.py:224`). G-P15 초안은 소비자 밖 sealer/publisher를 제안하며 `_drain`의 종료 의미도 넓힌다. **그 초안의 채택과 구현 여부는 C00 결정 사항**이다. G08은 다음 의미를 기준으로 연결한다.

1. OPEN commit은 현재 run의 input gate 개방보다 먼저다. begin/finish 및 checkpoint의 DB·journal·manifest I/O 동안 capture gate나 Desktop lock을 잡고 기다리지 않는다. snapshot 복사→잠금 해제→권위/DB 처리→token 재확인을 사용하고 G-P07 잠금 순서를 지킨다.
2. checkpoint는 마지막 영속 prefix를 주는 기회성 제어 작업이며 1초 내 영속을 보장하지 않는다. 저장이 지연되면 미영속 범위를 허용하고 UNKNOWN_TAIL로 남긴다. G-P15가 게시 pipeline을 도입하면 누가 checkpoint를 실행하는지와 같은 run의 순서를 최종 API에서 고정하되, source callback·submit에서 DB I/O를 하지 않는다. 건강 기록을 위해 별도 새 thread를 추가하지 않는 원문 원칙도 유지한다.
3. CLOSED의 필요조건은 **현재 run의 모든 source 해제 ACK + input gate cutoff + 모든 수락 저장 작업의 완료 ACK**다. G-P15가 소비자와 sealer/publisher를 나누면 소비자 join만으로는 부족하다. 해당 run의 대기·봉인·게시·catalog 등록까지 성공해야 한다. pending이나 실패이면 CLOSED/count_complete=True·PAUSED/FINALIZED 성공 표시를 하지 않는다.
4. is_live는 저장 작업이 남은 동안 참이어야 하며 G-P04/G-P05는 그 수명 전체에서 복구·확정·파일 제거를 보류해야 한다. G08은 새 worker가 있다는 이유로 live owner를 임의 교체하거나 원래 owner의 종료 조건을 축소하지 않는다. 실제 저장 ACK가 없는 “running=False” 통지는 완료 증명이 아니다.
5. root mutex는 건강 version·권위·행의 짧은 확인/commit에 한정한다. 상세 열거·JSONL 출력·검증·대형 manifest 투영을 넣지 않는다. G-P05 최종 삭제 권위 API를 먼저 대조하고 journal의 전체 열거를 GUI thread·capture gate·root mutex 안에서 반복하지 않도록 연결한다. 이력 확인 불가는 건강 정상으로 우회하지 않는다.

G-P15는 저장 처리량/긴 seal 보유를 고치는 소유자이며 G08은 유실 관측·영속·표시 소유자다. mutex 축소만으로 모든 큐 거부가 사라진다고 주장하지 않고, G08 checkpoint 추가로 G-P15의 비차단 입력·게시 ACK·원본 보존 불변식을 되돌리지 않는다.

### 4. G-P05·G-P07·G-P06과 공유 파일 순서

| G08 파일 | 겹치는 단위·보존할 계약 | 순서 요청 |
| --- | --- | --- |
| app/recording.py | G-P04 live owner, G-P15 writer/publisher 수명·drain·오류 전달 | G-P15 최종 push 위에서 건강 계층 연결 권고. G-P15가 미채택/분리되면 C00이 연결 기준을 먼저 지정 |
| app/desktop.py | G-P07 run_generation/epoch callback 고정·REC 수락 조건 | G-P07 push 뒤 같은 token을 사용. 새 건강 token 체계를 독립으로 만들어 늦은 callback 방어를 우회하지 않음 |
| app/power.py | 기존 suspend→명시 pause, wake 자동 재개 금지. G-P07의 제어/ACK 표시와 연결 | G-P07 후 SUSPEND 사유만 구조화해 전달. 저장·source ACK가 없으면 pause 성공으로 표시하지 않음 |
| app/recovery.py | G-P04 검증 보존량/예상량 분리·경고·DIRECTORY_ONLY 표시 | G-P04 push 위에서 additive 건강 결과 투영. 미확정 세션 재녹음 기능 추가 없음 |
| app/status.py | G-P07에서 생성 예정인 순수 표시 모델 | G-P07 push 뒤 확장. 트랙 OK/DEGRADED와 Job BLOCKED를 같은 상태로 합치지 않음 |
| storage/library.py | G-P04 claim·삭제 우선·검증, G-P05 DB/journal 권위·live delete 보류, G-P15 등록/게시 | 세 단위의 최종 push 뒤 직렬 수정. pending 또는 tombstone이면 tail 쓰기·미디어 채택·새 건강 행0. HEALTH 오류를 live/삭제 검사를 우회하는 경로로 만들지 않음 |
| ui/main.py | G-P04/G-P05 비동기 목록·조회 세대·선택 None 전달, G-P07 REC/시작 중/ACK 대기 표시 | 해당 push 뒤 건강 worker/표시를 추가. 늦은 건강 결과는 session/run/epoch/조회 세대로 폐기. GUI에서 전체 건강 이력 동기 조회 없음 |
| cli.py | G-P04 finalize·unfinished, G-P05 pending list·retry-only와 exit 의미 | 해당 push 뒤 기존 응답에 건강 사실을 additive 반영. 건강 보류는 확정 성공 exit로 오표시하지 않고 기존 삭제·재시도 의미 보존 |

G-P06 검토 tree에서 위 13개 대조 파일은 8e09b62와 같았다. 비용/동의의 실패를 트랙 STORAGE_FAILED나 DEVICE_LOST로 연결하지 않으며, 비용 snapshot·grant·ledger·config_key는 G08 쓰기 대상이 아니다. G-P07의 110코드/5종 BLOCKED 사유·암묵 resume 금지·권한 자동 완화 금지를 유지한다. HEALTH_*를 provider 오류나 새 Job BLOCKED 사유로 자동 등록하지 않는다.

원문 선행 조건 `G-P04·G-P05·G-P07 push + C00 시작 신호`에 **G-P15의 저장 수명 변경까지 먼저 확정·push**하는 순서를 추가하도록 요청한다. 권고 순서는 `G-P04 → G-P05 → G-P15`, 별도 가지 `G-P02·G-P06 → G-P07`을 모두 닫은 뒤 G-P08이다. 이는 G-P15 구현이 이미 승인됐다는 뜻이 아니다. C00이 다른 순서를 택하면 app/recording.py·library.py의 소유권과 ACK API를 먼저 고정하고 동시 수정하지 않는다. 착수 때 최종 HEAD·17파일 hash·G-P05 삭제 권위·G-P07 token/status·G-P15 ACK를 재대조한다.

### 5. 경우의 수·mutation 개정 요청

원문 분모는 직접 재계산해 `364+64+144+36+224+16+30+24+24+24=950`과 일치했다. K의 `Ω60−불가능24=F36`도 유지한다. 기존 S/G/D/K/R/U/T/C/B 가족과 그 934행은 유지하고, O 경쟁을 16→24행으로 보강한다. 다음 네 가족을 더해 **14가족 1,024행(950+8+18+16+12+20)**을 요청한다. 이는 계획 의미 행이며 실제 수집 node·PASS 수가 아니다.

| 가족 | 추가·변경 분할과 feasible 분모 | 행 수·증분 |
| --- | --- | ---: |
| O 확장 | 기존 경쟁4에 (5)checkpoint 영속 대기↔submit, (6)tail commit↔삭제 의도 추가. 경쟁6 × 양순서2 × 트랙수2 | 24 / +8 |
| Q 신규 | offer 결과{수락,열린 큐 포화 거부,gate 닫힌 뒤 거부}3 × 입력열{고정480frame,가변120/480/960frame,정상 무음480frame}3 × 트랙수2 | 18 / +18 |
| H 신규 | legacy 건강{정상0,정상6,해당 epoch 기록 없음,dropped 필드 없음,bool,음수,문자열,같은 epoch의 충돌 중복}8 × 표시경로{recovery_view,finalize_lines}2 | 16 / +16 |
| P 신규 | 전체 저장 작업{대기,성공 ACK,실패 ACK}3 × source 해제 ACK{있음,없음}2 × 트랙수2 | 12 / +12 |
| F 신규 | 초기 건강{유효 OPEN,유효 CLOSED,tail 영속 실패,손상,미래 version}5 × 동작{복구,확정}2 × 관측{첫 호출,재호출}2 | 20 / +20 |

각 추가 가족은 다음 독립 oracle를 고정한다.

- **O5:** checkpoint용 불변 snapshot을 복사한 뒤 영속 경로를 Event로 멈춰도 capture gate를 점유하지 않는다. 큐에 여유가 있는 다른 트랙의 submit은 checkpoint 해제 전에 반환하고 수락된다. snapshot 이후 사실은 다음 checkpoint/tail 대상이며 옛 snapshot이 새 누계를 덮지 않는다. **O6:** 삭제 의도가 먼저 확정되면 tail commit/신규 건강 쓰기0, tail commit이 먼저면 이후 명시 삭제 완료 시 행은 cascade로 제거되고 tombstone은 유지된다. 미디어 부활0. 두 동작의 권위 재확인 순서를 barrier로 고정한다.
- **Q:** source는 실제 장치 없는 fake다. 독립 입력열은 frame 수·bytes·수락 여부를 보관한다. packet health를 한 번 더 전달해도 queue drop이 두 배가 되지 않는다. 무음도 수락/보존 frame으로 센다. 전체 packet만 사용해 불완전 fragment 저장 문제와 섞지 않는다. 정상 drain 시 수락 bytes의 순서 연결과 실제 오디오를 비교하며, gate 거부는 drop 누계·gap을 늘리지 않는다. 환경 부하의 자연 거부 건수 0을 요구하지 않는다.
- **H:** 정상0만 정확0이며, 정상6은 정확6이다. 나머지 6입력은 누락/손상/충돌을 정상0으로 표시하지 않는다. 입력 legacy dict·DB 행은 불변이다. 기대값은 제품 `_known_epochs`나 renderer를 다시 호출해 만들지 않는다. v2의 확인 prefix+tail과 bounded legacy 투영의 중복 금지는 기존 R/U와 연결한다.
- **P:** 외부 source를 소유하는 Desktop fixture에서 consumer는 끝난 것으로 고정하되 전체 저장 작업의 receipt를 별도로 주입한다. source ACK가 있고 전체 저장 성공일 때만 CLOSED 허용. 대기·미확인 source·저장 실패는 완료 아님이며, 실제 실패는 원본 보존/저장 실패 표시를 유지한다. G-P15가 pipeline을 도입하면 실제 consumer/sealer 수명 통합 시험으로 연결하며, fake bool을 OS 종료 증명으로 승인하지 않는다.
- **F:** 유효 OPEN은 비live INTERRUPTED 세션, 유효 CLOSED는 PAUSED 세션으로 시작한다. OPEN의 첫 복구는 안정된 tail, 재호출은 같은 tail·prefix다. 정상 확정 후에도 tail을 지우지 않는다. tail 영속 실패는 첫·재호출 모두 같은 실패 주입을 유지하고, 손상/미래 version과 함께 건강 DEFERRED·확정 성공 아님을 요구한다. media 검증량·기존 경고·원본 hash를 별도로 보존한다. 정상 CLOSED에는 tail을 추가하지 않는다.

가족별 고정 분모는 `S364/G64/D144/K36/R224/O24/U30/T24/C24/B24/Q18/H16/P12/F20`이다. 고유 ID manifest는 원문 방식에 Q/H/P/F를 추가하고 O 범위를 확장한다. 누락·중복·추가·skip0을 감사하며 fixture를 공유해도 run·legacy dict·counter·DB 상태를 다음 행으로 흘리지 않는다. 새 가족은 선택한 경계의 대표 곱이며 모든 권위×모든 건강 상태×전체 동작 이력의 직적 전수라고 주장하지 않는다.

원문 mutation 24개에 아래 6개를 추가해 **30개**를 요청한다. 정상본 PASS 뒤 TEMP 사본에서 목표 assertion 실패로 확인하며 import 실패·권한 실패·timeout만으로 검출이라 세지 않는다.

| ID | 추가 결함 | 목표 |
| --- | --- | --- |
| M25 | packet health의 accepted=False를 RecordingService drop에 다시 더함 | Q의 입력 frame 회계·중복 gap 없음 |
| M26 | legacy 누락/잘못된 dropped 값을 0으로 표시 | H의 미상과 정상0 구별 |
| M27 | consumer 종료만으로 전체 저장 ACK를 대체 | P의 대기·실패 상태 CLOSED 금지 |
| M28 | finalize_unfinished가 건강 DEFERRED를 무시하고 확정 | F의 확정 성공 미표시·원본 보존 |
| M29 | checkpoint I/O 동안 capture gate 보유 | O5의 영속 대기 중 다른 트랙 submit 완료 |
| M30 | tail 기록 직전 삭제 권위 재확인 제거 | O6의 삭제 선행 시 쓰기0·부활0 |

### 6. 쓰기 범위·수락 게이트·C00 결정 요청

정확한 쓰기 범위는 **17파일 그대로 = source9 + 신규 시험6 + 기존 시험1 + 문서1**다. 목록 중복 0을 대조했다.

| 구분 | 파일 |
| --- | --- |
| domain 1 | src/recoryn/domain/capture_health.py |
| app 5 | src/recoryn/app/recording.py, src/recoryn/app/desktop.py, src/recoryn/app/power.py, src/recoryn/app/recovery.py, src/recoryn/app/status.py |
| storage/UI/CLI 3 | src/recoryn/storage/library.py, src/recoryn/ui/main.py, src/recoryn/cli.py |
| 신규 시험 6 | tests/unit/test_track_health.py, tests/property/test_track_health_case_space.py, tests/integration/test_track_health.py, tests/integration/test_health_crash.py, tests/ui/test_track_health_ui.py, tests/e2e/test_health_export.py |
| 기존 시험 1 | tests/integration/test_app_service.py |
| 문서 1 | docs/testing/g08-track-health-cases.md |

capture/queue.py·capture/wasapi.py·storage/chunks.py·storage/_coordination.py·G-P04/GT-P03 기존 시험·security/provider·설계 정본은 수정하지 않는다. G-P15의 저장 기구를 G08에서 다시 구현할 권한도 추가하지 않는다.

C00 결정 요청은 ①실제 offer를 근거로 QUEUE_DROP을 한 번만 계상하고 legacy 잘못된 값을 UNKNOWN으로 표시, ②G-P04 구조화 복구 결과 연결과 건강 DEFERRED 시 확정 보류, ③전체 저장 ACK를 CLOSED 조건으로 하고 G-P15를 먼저 닫는 공유 순서, ④계획 950→1,024행·mutation 24→30개다. 17파일·표3개·G-P09 인계·명시 pause/resume만의 재연결·신규 시험 6파일 60초 게이트는 유지한다. 60초 초과 시 축약 전에 측정값과 안을 보고한다. 제품 변경·시험 실행은 C00 시작 신호까지 하지 않는다.


## 11. 구현 진행과 기준 고정(319a05f)

상태: **구현·검증 진행 중, IMPLEMENTATION_READY 아님**. 원문과 승인 개정까지의 67,718 bytes(LF SHA-256 `8ee33b46612d7b1cf90c4ae078a10e08ace70ef9c5f39834b44f8771b86ee017`)를 보존하고 이 절만 추가했다. 기준은 `319a05ff5f8a31dd8c9154fab5b08dca34318db7`이다. 공유 작업 트리에는 G-P11a 변경이 있으므로 최종 수락은 HEAD+승인 파일만인 TEMP 사본에서 판단한다.

### 11.1 기준과 연결

17파일의 착수 LF hash는 OS TEMP `recoryn-g08-gtfe_b_o/baseline17.json`에 고정했다. 신규 파일은 없음을 기록했고 기존 8개 제품 파일과 test_app_service는 해당 HEAD와 LF 기준 일치했다. 문서는 위 승인 hash의 신규 파일이다. Git 쓰기·하위 agent·장치·weights·네트워크·유료 호출·설치는 하지 않았다.

- G-P15b의 consumer+sealer FIFO/등록까지의 is_live·_join_workers·WRITER_ACK_PENDING을 유지한다. 건강 전용 thread를 추가하지 않았고 consumer의 기존 제어 경로에 기회성 checkpoint를 연결했다. source callback/submit은 메모리 사실만 갱신한다.
- 시작 OPEN과 RECORDING 전이를 같은 transaction에서 기록한 뒤 gate를 연다. 종료는 source.stop 실제 반환·gate cutoff·두 worker join을 호출자 receipt로 확인한 뒤에만 CLOSED를 기록한다. receipt는 임의 Python 호출자의 진술을 OS 인증으로 바꾸는 장치가 아니다. 저장 오류의 prefix/사실을 기록할 수 있어도 CLOSED는 만들지 않는다.
- DesktopRecorder는 기존 run_generation에 고정 epoch를 함께 검사하고 callback lock 아래 recording gate를 기다리지 않는다. 일부 source 단절은 그 트랙 intake만 보류한다. 다른 트랙 수락·저장은 지속하며 자동 장치 교체/자동 재연결은 없다.
- 기존 health_snapshot의 tracks는 accepted_frames/dropped_frames 두 누계의 호환 형태를 유지한다. 새 상세 메모리 상태·소스별 유실·미상·구간 union은 별도 track_health에 있다. G-P07 REC의 필요조건은 완화하지 않는다.
- 캡처 메타데이터는 G-P15 writer와 같은 **해당 세션** 삭제 권위를 사용한다. journal 이름을 root 밖에서 준비하고 version/stamp·해당 DB intent를 root 안에서 짧게 확인한다. 다른 세션 journal 본문의 읽기 오류가 녹음을 중단시키지 않는다. 복구·확정·상세 관리 조회는 G-P07 job_authority의 전체 이력 검증을 유지한다. 어느 경로든 해당 세션 삭제 의도/불명은 쓰기 허용으로 바꾸지 않는다.
- capture_health_runs/tracks/events 3표와 조회/phase 인덱스를 additive로 추가했다(user_version은 기존1 유지). event의 gap_id/kind/digest·부모 run/track 관계를 검사한다. G-P09에 이 실제 열·인덱스·schema_version2 및 legacy-only/v2 혼재 구분을 인계한다. digest는 보고의 인증이나 공격자 권한 방어가 아니다.
- 상세 API는 고정 health_version과 version1 JSON 문자열 cursor(phase+마지막 tuple key)를 쓴다. PK/복합 인덱스 keyset 질의로 제한된 페이지를 읽고 JSON 검사·digest 계산·출력은 root 밖에서 한다. 전체 이력 UNION 정렬/OFFSET을 root 안에서 반복하지 않는다. run 상태/version·track identity·event 사실을 모두 제공한다.
- 복구는 기존 session claim·삭제/live 거부와 검증된 청크 보존량을 유지한다. OPEN의 마지막 영속 prefix 뒤에는 안정된 UNKNOWN_TAIL(lost_frames=None)을 추가하며 재복구는 멱등이다. 건강 수선 실패·손상·미래 형식은 구조화한 DEFERRED이며 새 확정을 진행하지 않는다. UI·CLI도 이를 성공으로 표시하지 않는다.
- v2 요약의 canonical epoch는 최신8개, event 상세는 트랙별16개로 제한하고 생략을 명시한다. **기존 legacy epoch dict는 장식/정규화/삭제하지 않고 그대로 보존**한다. 혼재한 legacy 이력이8개를 넘는다는 이유로 과거 prefix를 버리지 않는다. 전체 호환 JSON의64KiB 상한은 유지하며 이력을 보존한 새 투영이 한도를 넘으면 수선을 보류한다. 소리 없이 legacy를 자르는 fallback은 없다.
- export는 같은 snapshot의 capture-health.jsonl을 먼저 완성하고 실제 bytes SHA-256·행 수/version을 export.json에 적는다. 상세 실패/버전 변경 때 완료 marker를 내지 않는다. UNKNOWN을 무음 frame·0 유실로 치환하지 않는다.

### 11.2 중간 실측(최종 수락과 구별)

다음은 직접 실행한 결과다. 다른 문서의 과거 PASS를 합산하지 않는다. 이후 source 변경이 있으면 최종 hash와 일치하는 사본에서 재확인한다.

| 실행/사본 | 관측 결과 | 한계 |
| --- | --- | --- |
| 최초 신규6파일(isolated1) | 1,026 PASS·29.63초 | 당시 계약1,024+보조2; 최종본 아님 |
| 신규6파일(isolated3) | 1,083 PASS·35.97초(pytest), runner36.66초 | 당시 계약1,024+보강59, skip/실패0; 이후 legacy12행 보존 보강은 재확인 대상 |
| case-audit.json | canonical1,024·누락/중복/추가0, 당시 보강51 별도 | 이후 보강은 최종 audit에서 다시 분리 |
| mutation2-results.json | 목표 assertion으로30/30 검출 | source가 이후 보강됐으므로 최종 mutation 재확인이 필요 |
| 최초 관련+UI 사본(isolated1, 대기 fixture1파일 제외) | 6,110 PASS·10 FAIL·630.79초 | 전체 오프라인/최종 PASS라고 보고하지 않음 |
| 위 회귀가 드러낸 제품 회귀 | G15 IDX-IO1/2/4와 G07 PCM4건 | 전체 이력 오류의 캡처 전파, 기존 tracks 호환 형태를 고침. 해당 9개(기존 IO5+PCM4) 직접 재실행 PASS·20.73초; 기존 시험 변경 없음 |
| TEMP draft20 정적 검사 | ruff check·format check·mypy PASS | 원래17파일+승인 대기 fixture제안3파일의 TEMP 사본, 공유3파일은 미수정. 전체 CI 동등 시험/coverage는 실행 중 |

K36은 소유한 자식 프로세스를 실제 건강 transaction/worker/CLOSED 경계에서 멈춘 뒤 PID를 종료·확인한 시험이다. source import origin을 부모의 사본 src와 비교했고 PYTHONPATH를 고정했다. 물리 전원 차단·실장비 절전/장치 정확도 결과로 확대하지 않는다. 신규6파일60초 게이트는 유지한다.

### 11.3 범위 추가 요청과 공유 파일 상태

현재 공유 작업 트리에서 본 작업자는 **승인17파일만** 수정한다. 필요한 다음3파일은 실제 실패를 근거로 C00에 요청했으며 아직 승인 응답을 받지 않았다. TEMP의 scope-request-proposal.patch/fixture-proposals는 검토용 제안이다. 이를 공유 파일에 적용하거나 승인된 단위의 최종 검사라고 보고하지 않는다.

1. tests/ui/test_capture_start_ui.py: G07-O-001이 source.entered.wait(3)에서 실패(앞선288 PASS). FakeRecording 생성자가 source_managed를 받지 못한다. 새 observe_health의 현재 token 수락 반환·sources_released·pause(reason) fixture만 적응하고 기존 REC/PCM oracle은 유지할 제안이다.
2. tests/integration/test_unfinished_recovery.py: G04-F3-health-write-failure의 기존 record_capture_health 주입이 이제 호출되지 않아 DID NOT RAISE. finish_capture_health의 one-shot 실패로 옮겨 같은 원인 사슬·원본 보존을 검증할 제안이다. 이 파일에는 현재 **G-P11a의 별도 resource_request fixture 변경**도 있으므로 C00가 소유/커밋 순서를 정해야 한다. 해당 변경을 덮어쓰지 않았다.
3. tests/integration/test_pending_deletion_restart.py: G05-ORDER-0000/0004는 복구/확정이 먼저인 새 삭제의 기대 generation을 그 전 시점으로 고정해 실제 tombstone7과 기대6이 다르다. 건강 수선의 generation 증가 자체는 승인 계약이다. 이 두 경계에서 새 삭제 직전에 기대 세대를 고정하고, 이미 pending인 intent의 세대 불변 oracle은 그대로 둘 제안이다.

G04/G05의 위 세 실패 node는 isolated2에서 단독 재실행해 동일 실패를 확인했다. UI fixture 실패는 당시 작업 트리에서 선택 실행한 결과이며 이를 isolated2 실행으로 바꿔 기록하지 않는다. 범위 밖 fixture를 조용히 바꾸거나 제품의 정당한 health generation 증가를 제거해 시험을 통과시키지 않는다. C00 승인 및 공유 파일 소유권 확인 뒤 최소 diff만 적용하고 최종 exact-tree 검증·hash·미해결을 보고한다.


## 12. 범위 승인 대기 보고 — 실행 증거 갱신

상태: **SCOPE_NEEDED / 최종 IMPLEMENTATION_READY 전**. 제품9파일과 승인 시험/문서는 유지하며, 아래 추가3 fixture를 공유 작업 트리에 적용하지 않았다. 이 절은 중간 실패를 덮어쓰지 않는다.

- 최신 원래17파일의 TEMP `isolated6`에서 신규6파일 **1,085 PASS·28.32초**, 실패/skip/ResourceWarning0이다. 1,024 canonical 의미 행과 보강61건을 구별한다. 별도 수집 감사의 canonical1,024 누락/중복/추가0은 그대로이며 이후 바뀐 ready 게시 방식은 case ID를 바꾸지 않는다.
- 파일별 testcase 시간 합은 unit1.263 / property0.003 / integration14.409 / crash8.298 / UI2.355 / e2e0.844초다. pytest wall28.32초·runner28.89초와 구별한다. 단독6파일 명령이며60초 게이트를 통과했다.
- 최신 제품9파일은 `isolated5`에서 수행한 mutation **30/30 목표 assertion 검출**과 LF hash가 같다(`mutation5-results.json`). 테스트 ready marker는 그 뒤 원자 게시로 보강했다. 수집/권한/timeout 실패를 KILLED로 세지 않았다.
- 건강 관리 구조 계측: 관리 root 최장 **1.835ms**, root 소유 중 iterdir/scandir/listdir0, root 밖 호출11. 다른 세션에66블록/198frame 수락·확인된 큐 유실0을 관측했다. 이 소형 합성 실행을 모든 부하의 무유실 보장으로 확대하지 않는다. 대형·경쟁 회귀는 아래 실행 범위와 구별한다.
- TEMP draft20(당시17파일+fixture제안3)의 전체 CI 동등 실행은 **21,457 PASS·2 FAIL·1,272.63초**다. pytest coverage85 게이트는 통과했고 check_coverage의7묶음도 모두 PASS였다. 이 실행 뒤 legacy12개 보존·device prefix 감소 거부·동일 세션 조회 멱등 보강이 있으므로 최신17파일의 최종 전체 회귀 PASS로 보고하지 않는다.
- 그2실패는 K-31 ready JSON을 쓰는 순간 부모가 빈 파일을 읽은 fixture race, G07-FIX1-ACK-02 중첩 FakeRecording.pause의 reason 인자 누락이었다. 신규 kill fixture는 소유 TEMP에 쓰기 완료 후 os.replace로 ready를 원자 게시하도록 고쳤고 최신 K36이 포함된 신규6파일에서 PASS했다. UI 기존 fixture는 TEMP 제안에서만 중첩 override까지 적응했다.
- 최신 TEMP `proposed20-final`에서 해당 UI 파일 전체493건+G04/G05 실패3건 **496 PASS·2.87초**다. 공유3파일은 미수정이며, 이496을 원래17파일만의 실행으로 표현하지 않는다. 제안 diff는 `scope-request-proposal.patch`다.
- ruff check/format check 및 TEMP draft20의 `mypy src/recoryn scripts packaging`은 PASS했다. 최종 승인 tree의 전체 오프라인/CI 동등 회귀·정적 검사·파일 hash는 범위/공유 소유권 결정 뒤 다시 고정한다.

당시 check_coverage 출력은 다음과 같다. 기준은 위 draft20의 coverage.json이며 최신 tree 수치가 아니다.

```text
domain: line=99.44%/95% branch=98.37%/90% PASS
capture: line=99.85%/95% branch=98.57%/90% PASS
jobs: line=99.10%/95% branch=96.04%/90% PASS
storage: line=95.56%/95% branch=90.42%/90% PASS
security: line=98.11%/95% branch=94.43%/90% PASS
content: line=99.59%/95% branch=98.75%/90% PASS
all: line=93.97%/85% branch=88.15%/80% PASS
```

C00 확인이 필요한 것은 **§11.3의 기존 fixture3파일에 대한 제한된 쓰기 승인과 G-P11a가 함께 변경 중인 test_unfinished_recovery.py의 소유/커밋 순서**다. 후속 정확한 사본은 그 결정에 맞춰 구성하며 G-P11a의 resource_request 변경을 덮거나 G08 결과에 섞지 않는다. 현재 phase manifest와 제안은 OS TEMP `recoryn-g08-gtfe_b_o`에 보관했다. 독립 검토·Windows 장치/절전·전원 장애 검증은 완료하지 않았다.

현재17파일 LF hash(문서 자신의 hash는 외부 manifest/창 보고로 제공):

| 파일 | SHA-256(LF) |
| --- | --- |
| `src/recoryn/domain/capture_health.py` | `383aae7af3c73743d2f986934593f6f3cbf545cef7ea3678f53a1c37d6d08b52` |
| `src/recoryn/app/recording.py` | `3c6756e85c6693d9027e96d55ddf44d3e67fc44b90e64790d86d868575963d0a` |
| `src/recoryn/app/desktop.py` | `16c5c357cec6c75043de657f24b33be64b92bda6b3dc80cd07cdb272be5a0108` |
| `src/recoryn/app/power.py` | `717c55cd27e92f2e0d4b9b135e49d95e0c887f5db96e000629f1e010fde8e81f` |
| `src/recoryn/app/recovery.py` | `5986d4012bb331ef1b2efe797db3afa47ec0aad6c8a47ca476ab2d59b918a558` |
| `src/recoryn/app/status.py` | `f6a46c297406ef9f30156ae1a20ae1cd4ff8563838763391704745d055bbecef` |
| `src/recoryn/storage/library.py` | `6ca2d449de8d441e3ce420611657e504bce9701333d007dc7dac3c25be2f4645` |
| `src/recoryn/ui/main.py` | `2ee00a15fbb8b2e4d681f2c7eaead7c7a6728ec02e04fca58c1e9720f760ed0c` |
| `src/recoryn/cli.py` | `d69f791115b7c66a16586d2416dcc9380e59835e840bfc8075b510bb3d94442a` |
| `tests/unit/test_track_health.py` | `76a8fe475a992d5766340822014c8848db1703ac9fec67b713b27259fee69a0d` |
| `tests/property/test_track_health_case_space.py` | `e03b34e0361783e77c519f889bff2268c2af6d0ef7a1ab946acda5167064b39d` |
| `tests/integration/test_track_health.py` | `a29528c5de7057673fe8f106b9f972ae88281dc9a071d582db399901fae5f474` |
| `tests/integration/test_health_crash.py` | `93acccfb525a73378bb107355ff2325f2916d7bf5f1b2a50c9e53e2ee7959a9f` |
| `tests/ui/test_track_health_ui.py` | `1e2df68954668f720c2edaa98fa9c577e4c8e7cb62664077ed913fea96c21132` |
| `tests/e2e/test_health_export.py` | `24edb1f4e0ac36bb6598c77eef3dc6058c737e52e7f744cfeb90055381518044` |
| `tests/integration/test_app_service.py` | `0dc5fc087251a6090874e53fa8e09dc2ce3dfe92cd78be00dc09a077ba42a10e` |

## §13 C00의 fixture 3파일 추가 승인과 적용 순서

C00이 §11.3의 실제 실패를 근거로 기존 시험 3파일의 최소 fixture 적응을 승인했다. 승인 범위는 기존 17파일에 아래 3파일을 더한 **20파일**이며, 기존 단언·기대값 의미를 약화하지 않는다. `tests/integration/test_unfinished_recovery.py`는 G-P11a 독립 검토 중인 공유 파일이므로 **G-P11a push 신호 전에는 수정하지 않는다**. 최종 전체 검증도 그 신호 뒤 새 기준 위에서 수행한다. 이 절은 §11·§12의 승인 대기 상태를 갱신하며, 이전 실행 결과는 이력으로 보존한다.

| 파일 | 실제 실패 원인 | 승인에 따른 최소 diff 및 현재 상태 |
| --- | --- | --- |
| `tests/ui/test_capture_start_ui.py` | G-P08의 실제 `DesktopRecorder`가 넘기는 `source_managed` 생성 인자와 건강 관측·소스 해제 ACK 메서드가 fake에 없어 시작 단계에서 실패했다. `pause(reason=...)`를 받지 않는 중첩 fake도 ACK 오류 대신 `TypeError`를 발생시켰다. | fake 생성자의 keyword 인자, `observe_health`·`sources_released`, 기본·중첩 fake의 `pause(reason=...)` 전달만 추가했다. 상태·frame·REC·ACK 단언과 오류 주입은 그대로다. **공유 파일 적용 완료**. |
| `tests/integration/test_pending_deletion_restart.py` | `G05-ORDER-0000`·`0004`는 새 삭제 의도보다 먼저 수행한 복구·확정에서 건강 이력이 보강되어 세대가 증가했는데도, 보강 이전 세대로 tombstone을 기대했다. | `mode == "new"`이면서 선행 동작이 `recover`·`finalize`인 두 행에만 새 삭제 입장 직전 `generation_of(library) + 1`을 기대 세대로 잡는다. 이미 존재하는 삭제 의도·stale·pending·tombstone 기대값은 변경하지 않았다. **공유 파일 적용 완료**. |
| `tests/integration/test_unfinished_recovery.py` | 건강 영속 실패 주입이 옛 `record_capture_health`에 걸려, 새 원자 종료 경로 `finish_capture_health`에서 오류가 발생하지 않았다. | 격리 사본에서만 주입 대상·복원 대상을 `finish_capture_health`로 바꾸고 가변 인자를 받게 준비했다. 오류·`INTERRUPTED`·원본 보존 단언은 그대로다. 공유 파일의 G-P11a `resource_request=STT` 변경을 덮지 않으며 **push 신호 대기**다. |

GC-P02의 `test_pending_management_never_blocks_another_recording` 함수 소스는 변경 전후 SHA-256이 모두 `1487c77abd3247a1e202949bec44c20d45b34b9ca28faaf2196e8ad089181cbd`로 일치한다. 관리 스레드의 root mutex 안 파일 시스템 열거·삭제 금지, mutex 보유 상한 및 기존 측정 단언은 변경하지 않았다. 이번 적응으로 canonical 1,024행·추가 보강 61행 및 mutation 30개 분모는 바뀌지 않는다.

준비 사본은 OS TEMP `recoryn-g08-gtfe_b_o/proposed20-final`이며, `319a05f` archive에 G-P08 제품 9파일과 승인 fixture를 적용했다. 세 번째 fixture는 공유 파일이 아닌 준비 사본의 변경이다. 제품 9파일의 LF bytes가 현재 공유 G-P08 파일과 같음을 확인했다. 이 사본의 `ruff check`·`ruff format --check`(Python 19파일)와 `mypy src/recoryn scripts packaging`(89 source files)은 PASS다. 전체 `tests/ui` 및 G-P04·G-P05·G-P15·G-P07 관련 선택 회귀를 `-W error::ResourceWarning`, offscreen, no cache, 고유 TEMP basetemp로 실행 중이다. 이는 최종 G-P11a push 뒤의 정확한 tree 전체 검증을 대신하지 않는다.

### §13.1 승인 후 선택 회귀 완료

위 실행은 **6,613 PASS / 실패·skip·경고 0, pytest 682.56초**(runner 690.861초)로 끝났다. 실행 대상은 `tests/ui` 전체, `test_app_service.py`, G-P04의 unit/integration/CLI, G-P05의 unit/property/integration/CLI, G-P15의 seal unit/integration, G-P07의 blocked reason unit/property/integration이다. 명령·종료 코드·경과 시간은 TEMP `approved20-related-result.json`, 출력은 `approved20-related.log`에 남겼다. 이는 G-P11a 적용 전 기준 `319a05f` 위 준비 사본에서 수행한 선택 회귀이며, 최종 전체 오프라인 회귀로 표현하지 않는다.

신규 6파일의 직전 단독 실행은 **1,085 PASS / 28.32초**, canonical case ID는 **1,024 / 누락·추가·중복 0**, 별도 보강은 61개다. mutation 기준 제품 9파일과 현재 제품 파일의 LF bytes가 모두 같음을 다시 확인했고 `mutation5-results.json`의 **30/30 검출** 근거를 유지한다. 승인 fixture 적응은 이 제품 경로나 신규 행의 oracle을 바꾸지 않는다. G-P11a push 신호 뒤 `test_unfinished_recovery.py`에 준비한 최소 적응을 얹고, 새 기준 + G-P08 20파일의 정확한 TEMP archive 사본에서 CI 동등 coverage·정적 검사·최종 전체 회귀를 수행한다.


## §14 G-P11a push 뒤 최종 기준과 검증

C00의 착수 신호에 따라 기준을 **`b92552059ef3b19b038e97cba3e3c44996fc5ee1`**로 갱신했다. 이 기준과 `319a05f` 사이에서 G-P08 20파일에 해당하는 변경은 `test_unfinished_recovery.py`의 G-P11a fixture 적응뿐이었다. 공유 파일은 새 기준과 같음을 확인한 뒤 §13의 주입 대상만 `finish_capture_health`로 바꿨다. `tests.resource_fakes.STT` import와 `resource_request=STT`는 보존했다. 기존 실패·원본 보존 단언은 변경하지 않았다. §13의 대기 표기는 이력이며 이 변경으로 적용 완료했다.

`git archive b92552059ef3b19b038e97cba3e3c44996fc5ee1`을 OS TEMP `recoryn-g08-gtfe_b_o/final-b925520`에 풀고 승인된 20파일만 덮었다. 시작 시 각 파일의 기준 hash·적용 LF hash는 `final-b925520-manifest.json`으로 고정했다. `PYTHONPATH`는 사본 `src`, `PYTHONDONTWRITEBYTECODE=1`, `QT_QPA_PLATFORM=offscreen`으로 고정하고 자식 Python의 `recoryn` 및 `recoryn.models.resources.__file__`가 모두 그 사본을 가리키는 것을 확인했다. 다른 작업자의 G-P11b 작업 트리는 이 검증에 포함하지 않는다.

단독 신규 6파일은 **1,085 PASS / 33.34초**(runner 34.003초), 실패·skip·경고 0으로 60초 예산 안에 들었다. `final-new-six.xml`을 독립적으로 읽어 계획의 닫힌 ID 집합과 대조한 `final-case-audit.json`은 canonical **1,024 / 누락 0 / 추가 0 / 중복 0**, 별도 보강 61개다. 실행 결과에서 측정한 관리 root mutex 최대 보유는 **1.302ms**, 관리 파일 시스템 작업은 mutex 안 **0건**·밖 **11건**이었다. 이 합성 시험의 51블록/153frame 수락·유실 0은 해당 실행의 측정값이며 일반 무유실 보장은 아니다.

사본 전체 `ruff check --no-cache .`와 `ruff format --check --no-cache .`가 PASS이고, `mypy src/recoryn scripts packaging`도 **90 source files PASS**다. 최종 CI 동등 전체 회귀·coverage 및 동일 기준 mutation의 완료 결과는 아래에 이어 기록한다.


### §14.1 최종 전체 실행 결과

최종 CI 동등 명령은 사본에서 다음과 같이 실행했다. source 및 자식 실행의 `PYTHONPATH`는 위 사본 `src`로 고정했다.

```text
python -m pytest -q -p no:cacheprovider -W error::ResourceWarning --basetemp <OS TEMP>/recoryn-g08-gtfe_b_o/final-b925520-full-base --junitxml <OS TEMP>/recoryn-g08-gtfe_b_o/final-b925520-full.xml --cov=recoryn --cov-branch --cov-report=json:coverage.json --cov-fail-under=85
python scripts/check_coverage.py coverage.json
```

**21,691 PASS / 실패 0 / 오류 0 / skip 0 / 경고 0**, pytest **1,312.40초**(runner 1,322.955초)였다. `-W error::ResourceWarning`을 사용했으며 ResourceWarning도 없었다. `final-b925520-full.xml`을 읽은 독립 집계의 전체 21,691건·UI 전체 **1,409건**·실패/오류/skip 0이 출력과 일치한다. G-P04·G-P05·G-P15·G-P07 및 새 기준 G-P11a의 기존 시험을 포함한 전체 오프라인 회귀다. §12의 옛 사본 실패 2건은 이 실행에서 모두 통과했다.

`--cov-fail-under=85` 통합 수치는 **92.52% PASS**, `check_coverage.py` 출력 전문은 다음과 같다.

```text
domain: line=99.45%/95% branch=98.39%/90% PASS
capture: line=99.85%/95% branch=98.57%/90% PASS
jobs: line=99.10%/95% branch=96.04%/90% PASS
storage: line=95.56%/95% branch=90.45%/90% PASS
security: line=98.11%/95% branch=94.43%/90% PASS
content: line=99.59%/95% branch=98.75%/90% PASS
all: line=94.01%/85% branch=88.19%/80% PASS
```

coverage JSON의 77개 파일은 모두 `src/recoryn/` 아래이며, 옛 ledger TEMP fixture나 다른 임시 소스 파일이 측정 분모에 들어가지 않았다. 정확한 출력·명령·종료 코드·시간은 TEMP `final-b925520-full.log`, `final-b925520-coverage-check.log`, `final-b925520-results.json`에 남겼다.

### §14.2 최종 mutation·fixture 경계 감사

`final-b925520`의 pyproject·src·tests·scripts·packaging을 별도 TEMP `mutant-final-b925520`로 복사하고, 변이마다 제품 파일을 복원하면서 M01~M30을 다시 적용했다. 결과는 **30/30 KILLED / SURVIVED 0 / INVALID 0**이다. `PYTHONPATH`는 변이 사본 src였으며, syntax/import/collection 실패나 timeout을 검출로 세지 않았다. 각 변이의 반례 단언 실패·목표 node·변형 hash·시간은 `mutation-final-b925520-results.json`과 `final-mut-M01.log`~`final-mut-M30.log`에 남겼다. 중간 사본의 mutation 결과와 합산하지 않는다.

추가 승인된 기존 fixture 3파일을 `b925520`과 AST 대조한 결과, 기존 `assert` 노드가 각각 **59개 / 115개 / 130개**로 전후 동일했다(`final-fixture-assert-audit.json`). GC-P02 보호 함수 소스 hash도 §13 값과 동일하다. 이는 단언을 제거·완화하지 않았다는 구조 증거이며, 세대 기대값의 입장 시점 보정 및 실패 주입 API 적응의 의미는 §13의 파일별 원인·diff 설명과 위 실제 회귀 결과로 확인했다. canonical 분모는 **1,024**, 추가 보강은 **61**, fixture 적응으로 새 ID를 만들지 않았다.

### §14.3 인계와 최종 LF hash

제품·시험 19파일은 실행 시작 manifest와 최종 공유 파일의 LF hash가 모두 같음을 확인했다. 결과 문서만 이 최종 실행 기록을 덧붙였고, 최종 사본에도 같은 문서를 복사했다. 아래는 최종 변경 20파일 중 자기 자신을 제외한 19파일의 LF hash이며, 이 문서 자신의 hash는 최종 창 보고와 TEMP `g08-final-ready-manifest.json`으로 제공한다. 원 승인 문서의 첫 67,718 bytes hash는 `8ee33b46612d7b1cf90c4ae078a10e08ace70ef9c5f39834b44f8771b86ee017`로 유지된다.

| 파일 | SHA-256(LF) |
| --- | --- |
| `src/recoryn/domain/capture_health.py` | `383aae7af3c73743d2f986934593f6f3cbf545cef7ea3678f53a1c37d6d08b52` |
| `src/recoryn/app/recording.py` | `3c6756e85c6693d9027e96d55ddf44d3e67fc44b90e64790d86d868575963d0a` |
| `src/recoryn/app/desktop.py` | `16c5c357cec6c75043de657f24b33be64b92bda6b3dc80cd07cdb272be5a0108` |
| `src/recoryn/app/power.py` | `717c55cd27e92f2e0d4b9b135e49d95e0c887f5db96e000629f1e010fde8e81f` |
| `src/recoryn/app/recovery.py` | `5986d4012bb331ef1b2efe797db3afa47ec0aad6c8a47ca476ab2d59b918a558` |
| `src/recoryn/app/status.py` | `f6a46c297406ef9f30156ae1a20ae1cd4ff8563838763391704745d055bbecef` |
| `src/recoryn/storage/library.py` | `6ca2d449de8d441e3ce420611657e504bce9701333d007dc7dac3c25be2f4645` |
| `src/recoryn/ui/main.py` | `2ee00a15fbb8b2e4d681f2c7eaead7c7a6728ec02e04fca58c1e9720f760ed0c` |
| `src/recoryn/cli.py` | `d69f791115b7c66a16586d2416dcc9380e59835e840bfc8075b510bb3d94442a` |
| `tests/unit/test_track_health.py` | `76a8fe475a992d5766340822014c8848db1703ac9fec67b713b27259fee69a0d` |
| `tests/property/test_track_health_case_space.py` | `e03b34e0361783e77c519f889bff2268c2af6d0ef7a1ab946acda5167064b39d` |
| `tests/integration/test_track_health.py` | `a29528c5de7057673fe8f106b9f972ae88281dc9a071d582db399901fae5f474` |
| `tests/integration/test_health_crash.py` | `93acccfb525a73378bb107355ff2325f2916d7bf5f1b2a50c9e53e2ee7959a9f` |
| `tests/ui/test_track_health_ui.py` | `1e2df68954668f720c2edaa98fa9c577e4c8e7cb62664077ed913fea96c21132` |
| `tests/e2e/test_health_export.py` | `24edb1f4e0ac36bb6598c77eef3dc6058c737e52e7f744cfeb90055381518044` |
| `tests/integration/test_app_service.py` | `0dc5fc087251a6090874e53fa8e09dc2ce3dfe92cd78be00dc09a077ba42a10e` |
| `tests/ui/test_capture_start_ui.py` | `f42e90052032eb0d70e71c7e3b5fd692ba9d295a840af7cf859686d42230068b` |
| `tests/integration/test_pending_deletion_restart.py` | `1c0a8cb6778fc40a820ef7f2c6ec71604af4898082c41dcc5c4432170daea8bc` |
| `tests/integration/test_unfinished_recovery.py` | `80168fa81bc09d97456877ad701ab0d76fa33d27eea48f3b0f05e6e5add74e42` |

미해결 구현 항목은 없다. 독립 검토는 C00이 지정할 검토자 몫이며 작성자가 최종 승인하지 않는다. 실제 장치 분리·재연결·절전·Windows 전원 장애 내구성은 실행하지 않은 외부 검증이다. 이번 실행은 fake source·합성 PCM·소유한 자식 프로세스 kill·임시 SQLite/파일 장애로 검증한 범위다. G-P09 인계 표 3개·schema_version=2·legacy/v2 구분과 G-P07/G-P15 수명 경계는 원 계약 및 §11에 유지한다.


## §15 G-P08 독립 검토 FIX1 계획(C00 결정)

기준은 b925520 + 이 단위 20파일이다. 검토 문서 g08-track-health-review.md의 G08R-01~10을 모두 이번 범위에서 수정한다. G-P17 계약은 보존하고 이 수정을 우선한다. 건강 시작·checkpoint·종료·backend 투영 실패는 저장 writer 오류로 승격하지 않으며 녹음은 계속한다. 해당 run은 DEFERRED/미상으로 표시하고 canonical OPEN prefix 또는 복구용 보류 표식으로 tail 미상을 유지한다. 호환 JSON은 byte 예산 안의 축약 read model이며 canonical 사실을 대신하지 않는다.

FIX1 추가 유한 행은 G08-FIX1-01..40이다. 01~06 건강 실패 6종(begin/checkpoint/finish/backend read/backend write/CAS), 07~10 투영 누적·legacy·큰 시각·문자열 4종, 11~13 장치 위치 정상/없음/TIMESTAMP_ERROR, 14~16 legacy 다중 트랙 원자성·실패·재시도, 17~19 idle gap 합침·닫힘·종료, 20~22 확정 표시·메모리/영속 구분·legacy export, 23~27 생존 변이 X04/X05/X06/X07/X09의 실제 경계, 28~29 gate 종료 뒤 진단/old generation, 30~31 PAUSE/SUSPEND 재시도, 32~33 복구 경합/삭제 코드, 34~35 포화 경로 회계·bounded 비용, 36~40 marker publish/read의 PermissionError 일시/기한·다른 오류 전파다. 기대는 수락 PCM bytes 전량 보존, storage_failed 거짓, 정상 pause/stop ACK와 건강 DEFERRED 분리, 근거 없는 장치 유실 0 금지, 모든 legacy 트랙 tail의 한 transaction/멱등, stale 통지의 상태·이벤트·다른 트랙 불변이다. 실제 case ID와 결과는 구현 뒤 감사하며 실행 전 이 40행을 PASS로 세지 않는다.

기존 S364는 이벤트·트랙수·stale을 실제 구동에 사용하고, R224의 legacy/missing도 지정 트랙수를 구성한다. 분모를 같은 입력 반복으로 채우지 않는다. 기존 canonical 1,024와 보강 61은 보존하며 FIX1 40행을 별도 감사한다. 새 시험 단독 60초 게이트·전체 회귀 2회·CI 동등 coverage·기존 mutation30 및 검토자 X01~X11을 TEMP 사본에서 다시 확인한다. 추가 범위가 필요하면 실제 실패와 함께 먼저 보고한다.


### §15.1 구현 중 보강·검토 반례 재현

건강 callback 처리 자체의 예외도 source/submit을 중단시키면 안 되므로 G08-FIX1-X-SUBMIT·X-OBSERVE 2행을 추가했다. source 경로는 RAM 보류 표식만 남기고 DB 작업은 기존 consumer 제어 경로에서 한다. 미래/손상 건강 자료에서 stop이 부가 manifest 읽기 때문에 실패하지 않도록 X-FUTURESTOP·X-CORRUPTSTOP 2행도 추가했다. 추가 분모는 최초 FIX1 40 + 4 = 44이며 canonical 1,024·기존 보강61과 분리한다.

중간 사본의 검토 원본 probe에서 headless·Desktop 각 10 run/20 cycle을 모두 마쳤다. headless는 stopped_at=null, accepting=true/storage_failed=false였고, Desktop도 result=null·PAUSED로 끝났다. 요약은 각각 최대 57,631B·61,440B였다. legacy 두 번째 commit 실패는 첫 실행 DEFERRED, 다음 실행에서 mic·system tail과 tracks가 모두 채워졌고 이후 멱등이었다. 이 수치는 최종 전체 회귀와 합산하지 않는다.

포화 원본 probe는 submit+전체 health_snapshot이라는 같은 관측으로 다시 실행했다. 최신 사본의 최근200회 평균 0.019ms(초기200회0.042ms), gate 최대0.060ms, health_record0.036ms였다. 검토 원문0.282ms/health_record약2.12ms와 구별한 이 PC 단독 관측이다. GapFact 재귀 복사 제거·닫힌 RAM DTO의 얕은 안전 복사·동일 좌표 interval 병합·상세 버퍼 포화 후 불필요 직렬화 생략·Desktop의 저장 실패 단일 사실 조회를 적용했다. 어느 단계에서도 거부 frame 누계를 줄이거나 무한 queue로 바꾸지 않았다.

변이 X06은 첫 새 oracle가 다른 version 검사에서 먼저 거부되어 여전히 SURVIVED였다. 마지막 details page 반환 **뒤**에 실제 DB의 snapshot version을 바꾸는 barrier로 고쳤다. 이때 정상본은 마지막 재확인에서 거부·완료 marker 없음, 재확인 제거 mutant만 완료되어 명시 단언으로 검출됐다. 이 중간 생존을 숨기지 않고 최종 변이 결과와 따로 기록한다.

### §15.2 기존 시험 계약 변경 승인 대기

현재 기존 fixture 한정 승인과 새 C00 결정이 충돌하는 실제 실패는 3건이다. G04-F3-health-write-failure는 건강 쓰기 예외/INTERRUPTED를 기대하지만 새 정책에서 정상 저장·미상 tail 복구 뒤 FINALIZED가 된다. test_app_service의 test_capture_health_write_failure_cannot_leave_recording_state도 같은 기대를 갖는다. test_failed_start_does_not_leak_a_live_writer는 이전 적응에서 begin_capture_health 실패를 session 시작 실패와 같게 보았으나, 이제 건강 실패만으로는 시작을 거부하지 않는다.

이 세 건의 공유 파일 단언은 승인 전 변경하지 않았다. 첫 두 건은 건강 실패와 저장 오류를 분리하고 수락 bytes 보존·미상·worker 종료를 assert하는 안, 세 번째는 건강 시작 실패와 fallback의 실제 session transition 실패를 함께 주입하여 원래의 시작 실패 cleanup 단언을 유지하는 안을 이 창에 요청했다. TEMP g04-f3-proposed.patch·app-service-proposed.patch로 최소 diff를 준비했다. ENOSPC·seal·commit 실패의 중단 단언과 G04 원본 보존 체인은 유지한다. 승인/최종 결과는 이어 기록한다.


### §15.3 현 수정 결과와 승인 경계

**현재 상태는 ASSERTION_SCOPE_NEEDED_3이며 FIX1_READY가 아니다.** 앞선 fixture 최소 적응·단언 의미 불변 조건 때문에 §15.2의 기존 시험 3건에 대한 계약 변경 승인을 이 창에서 요청한 상태다. 파일 추가 요청은 아니며, 이미 목록에 있는 test_app_service.py의 2건과 test_unfinished_recovery.py의 F3 한 건에 한정한다. 공유 파일의 그 단언은 아직 변경하지 않았다. 승인 뒤 최종 CI 동등 coverage 및 전체 오프라인 회귀 2회를 진행한다.

| 검토 ID | 현재 구현 및 국소 검증 |
| --- | --- |
| R01 | 건강 시작/checkpoint/종료/backend 기록·source bookkeeping 실패를 저장 오류와 분리. 해당 run은 DEFERRED, PCM 수락·consumer·sealer는 유지한다. 필수 session 상태 입장 자체의 실패는 별개로 cleanup한다. summary는 60KiB 예산 아래로 오래된 상세를 묶음 축약하고 생략을 표시한다. |
| R02 | 위치 없음/TIMESTAMP_ERROR 뒤는 media_loss_unknown과 None loss fact로 보존. 장치 유실 미상·확인 하한 표시, 증명 없는 union 0 금지. |
| R03 | 재복구가 원래 legacy 및 canonical archive에서 미수선 track/epoch를 다시 계산한다. 먼저 수선된 key는 중복 생성하지 않고 요약은 모든 legacy 트랙을 유지한다. 두 번째 commit 실패·Library 재열기 뒤도 양 트랙 복구/멱등을 확인했다. |
| R04 | marker publish와 첫 read의 PermissionError만 기한 안 재시도. 다른 오류/기한 뒤 원 예외 전파. K36과 새 좁은 retry 5행을 실행했다. |
| R05 | S stale 182행에서 실제 이벤트 13종·상태·트랙수를 모두 사용한다. non-stale의 순수 전이 oracle와 실제 source token 거부 시험을 구분한다. R legacy/missing은 실제 지정 트랙수를 구성한다. X04/X05/X06/X07/X09를 포함한 검토자 11변이 전부 검출했다. |
| R06 | 이미 FINALIZED인 결과의 건강 보류는 기존 확정 상태 유지로 표시. 실제 UI 완료 처리와 read model을 확인했다. |
| R07 | 연속 NO_PACKETS는 열린 구간 1개, 정상 수락/종료 cutoff에서 CLOSE. PAUSE/SUSPEND retry는 같은 cutoff당 OPEN 1개다. |
| R08 | StateConflict를 ValueError 손상으로 합치지 않음. 삭제/이력 코드는 유지하고 일시 경쟁은 HEALTH_RECOVERY_PENDING으로 표시. |
| R09 | live 메모리 누계와 마지막 영속 checkpoint 번호·큐 유실 prefix를 구분. legacy export의 상세 부재를 명시. |
| R10 | 같은 run/epoch의 종료 후 경고·meter 정리를 건강 모델 반영 여부와 독립시킴. 오래된 generation은 여전히 거부. |

호환 JSON에서 큰 legacy epoch 목록을 생략해야 하면 원본 값은 최초 canonical run의 optional `legacy_projection`에 보존하고 archive run ID를 참조한다. 작은 legacy 요약은 그대로 유지한다. canonical run/detail 읽기 한도는 8MiB, GapFact는 기존4KiB, 호환 요약은 기존64KiB 상한이다. raw legacy JSON의 UTF-8/ASCII 재인코딩 차이를 수용하며 수락 원본 PCM은 변경하지 않는다. 이 optional payload 필드를 G-P09의 capture_health 구성요소 인계에 포함한다. 표 3개와 schema_version=2는 유지된다.

건강 자료가 계속 손상/미래 version이면 명시 stop은 저장 ACK 뒤 PAUSED·finalized=False·health DEFERRED를 돌려준다. 종료 ACK 대기와 건강 확정 보류를 혼동하지 않는다. 일시적 건강 실패가 복구 가능한 경우 명시 stop에서 검증 prefix/tail을 수선한 뒤 기존 확정 경로를 사용한다. 실패 run 뒤 정상 run 재개·초기 건강 기록 실패로 canonical run이 없던 새 epoch의 tail도 별도 회귀로 확인했다.

- 최신 신규6파일 단독: **1,130 PASS / pytest53.80초 / runner54.470초**, 실패·skip·경고0, 60초 예산 통과. 앞선64.70초 초과를 먼저 보고한 뒤 JSON 항목별 반복 인코딩을 묶음 축약으로 바꿨으며 행·반복 횟수는 줄이지 않았다.
- ID 감사: **canonical1,024 / 누락·추가·중복0**, 기존 보강61 + FIX1의 40행/추가5행 = 보강106, 신규 전체1,130. `final-case-audit.json`에 기록했다.
- 관련 선택/전체 UI 중간 실행: **6,764 PASS / 기존 계약 불일치2 FAIL / F3 한 행 deselect, 682.19초**. 이 사본의 app_service 두 기존 단언이 §15.2의 실제 실패이며, 이 실행을 최종 전체 PASS로 보고하지 않는다.
- 최신 사본 전체 ruff check·format(190파일)·mypy(90 source files) PASS. 일반 사본과 변이 사본 3곳 모두 자식 recoryn import origin이 해당 TEMP src임을 확인했다.
- 최신 사본의 변이: **기존 의도 M01~M30 30/30, 검토자 원본 X01~X11 11/11, 추가 Y01~Y10 10/10 KILLED**, 최종 SURVIVED/INVALID0. 저장된 초기 INVALID/생존 실행과 합산하지 않는다. M11은 얕은 DTO 직렬화, M24는 최종 bounded projection, M29는 분리한 checkpoint write helper를 겨냥하도록 같은 결함 의도를 갱신했다. 이동한 함수의 들여쓰기/중복 guard 때문에 처음 INVALID였던 M03/M21/M25는 수정한 harness에서 다시 실행했다.
- 추가 Y는 checkpoint 예외를 writer 실패로 승격, bound 제거, 위치 미상 사실 제거, partial legacy 재탐색 제거, idle 합침/닫힘 제거, cutoff 멱등 제거, StateConflict 오분류, 종료 진단 누락, live DEFERRED 미상 제거다. Y02의 첫 생존은 입력이 실제 상한을 넘지 않은 공백이어서 >64KiB backend projection과 명시 무오류 단언으로 보강했고, Y03의 IndexError는 presence 단언으로 고쳐 명시 assertion에서 검출했다.

명령·정상본/변이 소스 hash·실패 node·출력은 OS TEMP `recoryn-g08-fix1-lrxd4ba2`에 보관했다. 주요 기록은 six-5.xml/log/result.json, related-1.log/result.json, author-final-results.json, reviewer-final-results.json, fix-final-results.json, probe-results.json, probe-overload-latest.log다. 현 제품·시험19파일은 단독 PASS 사본과 LF bytes가 같다. 문서 결과만 후속 기록했다. G-P08b로 미루기로 한 기능 항목은 현재 없지만, 독립 재확인·기존3건 승인·최종 전체2회와 coverage가 아직 남아 있다. 실제 장치/절전/전원 장애는 여전히 외부 검증이다.


### §15.4 C00의 세 단언 변경 승인(2026-11-25)

C00이 G08 SCOPE_NEEDED 3건을 승인했다. 근거 결정은 **“건강 기록 실패는 녹음을 멈추지 않음”**이며, 건강 실패를 예외·INTERRUPTED로 기대하던 시험은 그 결정과 일치하도록 바꾼다. §15.2~§15.3의 승인 대기는 이력이고 현재는 해소됐다.

- `test_unfinished_recovery.py`의 G04-F3만 비차단 stop·실제 FINALIZED·건강 has_unknown·storage_failed=False를 확인한다. 기존 원본 bytes·재복구·이중 확정·내보내기 체인은 `sealed=True` 경로로 그대로 실행한다. ENOSPC·seal·commit 실패의 예외/상태 기대는 유지했다.
- `test_app_service.py::test_capture_health_write_failure_cannot_leave_recording_state`는 정상 stop·건강 미상·worker 종료·저장 frame3을 확인한다.
- `test_failed_start_does_not_leak_a_live_writer`는 기존 건강 시작 실패 주입에 실제 fallback `Library.transition` 실패를 더했다. 건강 실패만으로 시작을 거부하지 않는 새 계약에서, 필수 session 입장 실패 시 예외/worker 종료라는 기존 성질을 유지한다.

G04 파일에서 위 수정 대상 두 함수 외의 모든 top-level AST는 변경 전후 동일하다(SHA-256 `4e1045da5910461e1e12c2cc7200b1f03c5cd31ef2d3dd5bcc941b0c4d14cb1f`). 관리 mutex·구조 판정·claim 경쟁·G-P11a resource_request 연결을 수정하지 않았다. 최종 기준 b925520 + 승인20파일을 새 TEMP archive로 고정한 뒤 세 단언 회귀·정적 검사·CI 동등 전체 회귀/coverage를 두 번 실행한다.


### §15.5 전체 1회차 관측과 coverage 보강 계획

b925520+승인20파일의 새 사본에서 승인3건은 3 PASS, 정적 검사 PASS였다. 첫 전체 실행은 **21,736 PASS / 1,294.47초**, 실패·skip·경고0으로 K36도 통과했다. 그러나 storage 묶음은 line94.89%/95%·branch89.70%/90%여서 CI coverage 예산이 실패했다. 다른6묶음은 PASS였다. 이 실행을 CI 전 묶음 PASS나 요구된 최종 두 번 중 하나로 기록하지 않는다.

미실행 새 코드의 의미를 확인하는 별도 `G08-FIX1-COV01..06` 6행을 unit 파일에 추가한다. 01 트랙 상세만으로 byte 예산 초과(최신 항목·누계 보존/입력 불변), 02 큰 비정본 top-level 메타데이터의 fallback 제거(트랙 누계 보존), 03 큰 legacy 트랙 항목의 명시 생략(정상 트랙/입력 보존), 04 실제 checkpoint의 17개 gap/range(요약16·canonical17·손계산 union51), 05 defer marker 선읽기 뒤 body CAS 경합(상대 메타데이터를 덮지 않음), 06 defer marker 선읽기 뒤 DB-only 삭제 의도(쓰기0·원래 prefix 보존)다. 실제 정상/거부 결과와 bytes를 assert하며 pragma·coverage 기준은 바꾸지 않는다. canonical1,024·기존61·FIX1 45와 별도 감사하고, 신규 합계 예상1,136을 단독 측정한다. 제품 코드는 이 보강으로 바꾸지 않는다.


## §16 FIX1 최종 검증 결과와 인계(2026-11-25)

기준은 **b92552059ef3b19b038e97cba3e3c44996fc5ee1 + 승인20파일**이다. OS TEMP의 새 archive 사본에서 실행했고, PYTHONPATH를 사본 src로 고정해 부모·자식 import origin을 확인했다. G-P11b 등 다른 작업자의 제품·시험 변경은 넣지 않았다. §15.2~§15.3의 세 단언 승인 대기와 §15.5의 coverage 보강 대기는 해소됐으며, 이전 실행 결과는 이력으로 보존한다. 작성자는 독립 재확인이나 최종 통합 승인을 대신하지 않는다.

### 16.1 검토 지적별 최종 처리

| 지적 | 수정·검증 근거 |
| --- | --- |
| G08R-01 | RecordingService._checkpoint_health의 실패는 DEFERRED로 분리하고 PCM·writer·sealer를 유지한다. begin/finish/backend/source bookkeeping 실패도 같은 계약이다. 호환 요약은 60KiB 예산으로 묶음 축약하고 상세는 canonical 표에 둔다. 검토자 headless·Desktop 원 반례 각10 run/20 cycle 및 실패 주입 행으로 녹음 계속·원본 bytes를 확인했다. |
| G08R-02 | 위치 없음·TIMESTAMP_ERROR 뒤에는 장치 유실 미상과 None loss fact를 남긴다. 확인된 interval union으로 승격하지 않고 QUEUE_DROP과 단순 합산하지 않는다. 세 위치 조건과 영속·표시 oracle를 실행했다. |
| G08R-03 | legacy 원래 키와 canonical archive에서 미수선 track/epoch를 다시 계산한다. 두 번째 commit 실패 뒤 재열기·재복구에서 빠진 트랙을 채우며 두 트랙 요약·tail 멱등을 확인했다. 별도 transaction의 실패를 허용하되 불완전 상태를 성공으로 고정하지 않는 구조다. |
| G08R-04 | ready marker 게시·첫 읽기의 PermissionError만 기한 안 재시도한다. 기한 뒤 원 예외와 다른 예외 전파를 단언했고 최종 두 전체 실행에서 K36을 모두 통과했다. |
| G08R-05 | S stale182행이 실제 event13종·상태·트랙 수를 사용하고, R legacy/missing도 실제1/2트랙을 구성한다. X04~X07·X09를 실제 public 경계의 독립 oracle로 검출했다. |
| G08R-06 | 이미 FINALIZED인 세션의 건강 보류를 기존 확정 상태 유지로 표시한다. 새 확정 보류와 구분하는 read model·UI 행을 통과했다. |
| G08R-07 | NO_PACKETS는 트랙당 열린 구간 하나로 합치고 다음 수락 또는 cutoff에서 닫는다. PAUSE/SUSPEND 재시도는 같은 cutoff 구간을 중복 생성하지 않는다. |
| G08R-08 | 삭제·이력 StateConflict 코드를 유지하고 일시 복구 경합은 HEALTH_RECOVERY_PENDING으로 구분한다. HEALTH_UNREADABLE로 합치지 않는다. |
| G08R-09 | live 메모리 누계와 마지막 영속 checkpoint의 번호·prefix를 별도 표시한다. legacy export는 건강 상세 부재를 명시한다. |
| G08R-10 | 현재 run/epoch의 gate 종료 뒤 건강 통지는 Desktop 경고·meter 정리에 반영한다. 이전 generation은 계속 거부한다. |

큐 포화 원 probe는 submit과 전체 health_snapshot을 함께 관측하는 동일 방식으로 재실행했다. 최근200회 평균 **0.019ms**, 최대0.023ms, 첫200회 평균0.042ms, capture gate 최대0.060ms, health_record0.036ms였다. 검토 원문의0.282ms와 구분되는 이 PC의 관측치이며 CI 성능 보장은 아니다. 불변 fact의 불필요한 깊은 복사·포화 버퍼의 상세 직렬화·전체 상태 재계산을 줄였고, 거부 frame 회계나 queue 한도는 완화하지 않았다.

### 16.2 최종 시험·분모·변이

신규6파일 단독은 **1,136 PASS / pytest54.13초 / runner54.711초**, 실패·skip·경고0으로 **60초 게이트 PASS**다. 기존 의미 분모1,024행의 누락·추가·중복은0이며, family별 개수는 S364/G64/D144/K36/R224/O24/U30/T24/C24/B24/Q18/H16/P12/F20이다. 별도 보강은 기존61 + FIX1 45 + COV6 =112행이며 canonical 분모에 섞지 않는다. 최종 감사는 final-case-audit.json이다.

변이는 최종 제품 코드에서 **기존 M01~M30 30/30 + 검토자 X01~X11 11/11 + 추가 Y01~Y10 10/10 =51/51 KILLED**다. 최종 SURVIVED·INVALID는0이며, 중간 harness 오류·생존 결과는 §15.1·§15.3과 TEMP 원문으로 보존했다. 이후 변경은 승인된 기존 단언3건·보강COV6뿐이고 변이 대상 제품 코드는 동일하다.

최종 CI 동등 명령은 다음과 같다. 두 실행은 서로 다른 basetemp를 썼고 --cov-append 없이 각자 coverage를 새로 수집했다.

```text
python -m pytest -q -p no:cacheprovider -W error::ResourceWarning --basetemp <OS TEMP 새 폴더> --junitxml <회차별 XML> --cov=recoryn --cov-branch --cov-report=json:coverage.json --cov-fail-under=85
python scripts/check_coverage.py coverage.json
```

최종 1회차(2번 로그): **21742 passed in 1279.98s (0:21:19)**, 실패·skip·경고0. tests/ui 1414건과 K 36행을 포함한다. check_coverage 출력 전문:

```text
domain: line=99.18%/95% branch=97.89%/90% PASS
capture: line=99.85%/95% branch=98.57%/90% PASS
jobs: line=99.10%/95% branch=96.04%/90% PASS
storage: line=95.85%/95% branch=91.19%/90% PASS
security: line=98.11%/95% branch=94.43%/90% PASS
content: line=99.59%/95% branch=98.75%/90% PASS
all: line=94.16%/85% branch=88.46%/80% PASS
```

최종 2회차(3번 로그): **21742 passed in 1419.50s (0:23:39)**, 실패·skip·경고0. tests/ui 1414건과 K 36행을 포함한다. check_coverage 출력 전문:

```text
domain: line=99.18%/95% branch=97.89%/90% PASS
capture: line=99.85%/95% branch=98.57%/90% PASS
jobs: line=99.10%/95% branch=96.04%/90% PASS
storage: line=95.85%/95% branch=91.19%/90% PASS
security: line=98.11%/95% branch=94.43%/90% PASS
content: line=99.59%/95% branch=98.75%/90% PASS
all: line=94.16%/85% branch=88.46%/80% PASS
```


두 coverage JSON 모두 제품 src/recoryn 아래77파일만 포함하며 TEMP fixture·외부 경로 오염은0이었다. ruff check·format(190파일)·mypy src/recoryn scripts packaging(90 source files)도 모두 PASS다. 승인된 세 기존 시험은 별도3 PASS 후 전체 두 번에 포함했다. G04 수정 대상 두 함수 이외 top-level AST SHA-256은4e1045da5910461e1e12c2cc7200b1f03c5cd31ef2d3dd5bcc941b0c4d14cb1f로 유지했고 GC-P02 구조 판정과 G-P11a resource_request 연결도 유지했다.

### 16.3 변경 파일과 LF SHA-256

제품9 + 시험10 + 본 문서1 = **20파일**이다. 아래는 자기 참조를 피한19파일 해시이며, 본 문서 최종 hash는 FIX1_READY 보고와 TEMP g08-fix1-ready-manifest.json에 함께 기록한다. 검증 시작 manifest와 제품·시험19파일이 동일한지 확인한 뒤 결과 문단만 추가했다.

| 파일 | SHA-256(CR 제거 LF) |
| --- | --- |
| `src/recoryn/domain/capture_health.py` | `b224c531f47d14db1261f40cc8ede721b452a8fd431e3692cdc09e2b06b18108` |
| `src/recoryn/app/recording.py` | `1ac2d24453060fe27448f42657c5887b5b915c92f73cd57388b637233fb8cc62` |
| `src/recoryn/app/desktop.py` | `5cf35b4d5f39f8e8712c0ee22828ea9597923d3e832113f2ab5ae75463255464` |
| `src/recoryn/app/power.py` | `717c55cd27e92f2e0d4b9b135e49d95e0c887f5db96e000629f1e010fde8e81f` |
| `src/recoryn/app/recovery.py` | `2ce3198c9ab5b3a7a9cfd2e3765e757c953d1b16628bb469420352767b8059bf` |
| `src/recoryn/app/status.py` | `8e03ab6718843e178400255b80215c63e9dcd65680992275ebd4e2c1de0bddf5` |
| `src/recoryn/storage/library.py` | `66db2974102c3147565807c1d7f5a80ee1da5985e49f646644044b716b4b17bb` |
| `src/recoryn/ui/main.py` | `6af04c961a9b930af2673e910dfb344100d580c01a658c7ca0f5fa8c48df32b4` |
| `src/recoryn/cli.py` | `11fead0e1705c70caa19f8f7ba86881598ac45641612b594344a160ddcf8c593` |
| `tests/unit/test_track_health.py` | `d7f51f78e39a720fe020a27ead2f29d1977d852ae3a7dc3c6788ed012f1f7a2c` |
| `tests/property/test_track_health_case_space.py` | `e03b34e0361783e77c519f889bff2268c2af6d0ef7a1ab946acda5167064b39d` |
| `tests/integration/test_track_health.py` | `8ae33498c1101347e376c7f319d639b5c273c8661088772ed32a5c2d5a7d1ff5` |
| `tests/integration/test_health_crash.py` | `af2cc7f8e46ed6a24fe0819d9425a29d230adf8861b5998d3fe4428532a4f1b6` |
| `tests/ui/test_track_health_ui.py` | `31d6ccaf353333ebffe5aec807709b5c118db1ff313d5db851652ddd717a331b` |
| `tests/e2e/test_health_export.py` | `24edb1f4e0ac36bb6598c77eef3dc6058c737e52e7f744cfeb90055381518044` |
| `tests/integration/test_app_service.py` | `18340895ed084635c1aac2435b2c68dd0042ae35676b8d5eae0639d533b5271d` |
| `tests/ui/test_capture_start_ui.py` | `f42e90052032eb0d70e71c7e3b5fd692ba9d295a840af7cf859686d42230068b` |
| `tests/integration/test_pending_deletion_restart.py` | `1c0a8cb6778fc40a820ef7f2c6ec71604af4898082c41dcc5c4432170daea8bc` |
| `tests/integration/test_unfinished_recovery.py` | `bd0c7f0afb9be80dd405cc424de3d51d4a5d99dd4516ec5265887c28d6fcfeca` |


명령·정상본·원 반례·변이 hash·실패 node·출력·XML·coverage는 OS TEMP `recoryn-g08-fix1-lrxd4ba2`에 보관했다. 핵심은 final-validation-pass-results.json, final-full2/3.log·xml, final-coverage2/3.log, coverage-full2/3.json, six-6.log·xml, final-case-audit.json, author-final-results.json, reviewer-final-results.json, fix-final-results.json, probe-results.json, probe-overload-latest.log다.

G-P08b로 미룬 검토 지적은 없다. 독립 재확인은 C00 지정 검토자가 담당한다. 실제 음성 장치·절전·장치 분리·실제 전원 장애 시험은 수행하지 않았으며 외부 검증으로 남는다. 건강 기록은 파일 저장 완료나 전원 장애 내구성의 증명이 아니다. G-P09 인계는 기존3표·schema_version2 외에 optional legacy_projection archive/8MiB canonical reader 한도와 DEFERRED 관측 의미를 포함한다. G-P17에는 저장 ACK와 부가 건강/DB 관측 실패를 구분하는 결정을 별도 계약에 인계한다.

## §17 FIX2 계획: G08R-11·12(2026-11-25)

C00은 G08R-11을 S1(실패 run 뒤 새 run이 미상 사실을 지우는 핵심 오표시), G08R-12를 S3(수선 성공 뒤 보류 표시 잔류)로 판정했다. 기준은 계속 b925520+승인20파일이며 GS-P02 계약은 보존하고 이 수정을 우선한다. 원 반례는 build/review-trees/g08b-probe의 F6/F7이다. 이번 계획·결과는 §16의 FIX1 이력과 분리한다.

권고 구현은 run별 checkpoint 실패와 세션 전체의 미해결 보류를 분리한다. 다음 run은 정상 checkpoint를 계속할 수 있지만 세션의 미상 사실은 수선 성공 전까지 지우지 않는다. marker는 성공 뒤에만 pending에서 빼고 최대 횟수/시간 예산 안에서 시도하며 실패하면 다음 consumer/control 기회에 재시도한다. source callback/submit에서 DB 쓰기를 추가하지 않는다. marker가 영속되지 못해도 현재 Library의 읽기 모델과 live view는 세션의 보류를 미상으로 표시한다.

stop은 요약 marker뿐 아니라 canonical OPEN run도 확인하고, 저장 종료 ACK 뒤 recover/확정 보류 경로를 사용한다. 건강 수선 실패를 예외로 올려 FINALIZING에 남기지 않는다. tail 수선이 끝나고 OPEN이 없다는 사실을 재확인한 뒤에만 DEFERRED marker를 해제한다. has_unknown·UNKNOWN_TAIL·count_complete=False는 유지한다. 수선/marker 쓰기 자체가 다시 실패하면 읽기 모델은 계속 보류다.

별도 보강 ID는 G08-FIX2 접두사를 사용한다. 계획은 **28행**: F6/F7 계열(실패2종×트랙1/2×다음 정상 run1/2×최종 수선 가능/계속 실패=16), marker 재시도/기한/다음 기회/삭제 우선4, marker·메모리와 별개인 canonical OPEN 확인2, 최종 표시(marker 성공/실패×복구 run 순서2=4), 수선 결과의 경합/재시도2다. 기존 canonical1,024와 FIX1 보강을 줄이지 않는다. 실제 수집 node·추가 case ID는 별도 감사한다.

독립 oracle는 run별 입력 bytes를 트랙별 이어 붙인 값, 명시한 OPEN→RECOVERED_UNCLEAN/CLOSED 표, 실패 동안 has_unknown=True·DEFERRED, 성공 뒤 보류 해제와 unknown tail 유지다. 제품 health 계산으로 기대값을 다시 만들지 않는다. barrier/fake clock으로 marker 실패→pause→resume→정상 run→stop 순서 및 marker 수선과 삭제 경쟁을 고정한다. 원본·worker 종료·G04 claim/GC-P02 구조 단언은 유지한다.

변이는 기존 전체에 더해 세 원인(성공 전 pending 해제, begin에서 세션 보류 초기화, stop의 OPEN 검사 제거)과 최종 marker 해제/너무 이른 해제/읽기 모델 미상 삭제/재시도 상한 삭제를 각각 겨냥한다. 세 원인은 서로 다른 독립 시험으로 검출해야 한다. 검토자 X/Z 및 원 F6/F7도 TEMP 사본에서 재실행한다. 기존 신규6파일60초 게이트·관련/UI·정적 검사·CI 동등 전체2회는 그대로 수행한다. 실행 결과는 아직 없다.

### §17.1 중간 관측과 추가 oracle 2행

기존 FIX1 사본에서 원 F6/F7의 FINALIZING·has_unknown=False를 직접 재현했다. 수정 사본의 원 F1~F8은 모두 수락 bytes 보존·FINALIZED·has_unknown=True·UNKNOWN_TAIL과 최종 보류 해제를 확인했다. 신규6파일 중간 실행은 1,164 PASS/44.49초였다. 이 숫자는 아래 추가 단언/보강과 최종 전체 검증을 대신하지 않는다.

중간 변이에서는 정상 marker 재시도가 먼저 성공해 projection의 세션 보류 누락(W11)이 숨겨졌다. 따라서 별도 G08-FIX2-X-PROJECTION 1행은 marker 실패를 다음 정상 run까지 계속 유지하고, 메모리 읽기 모델이 아닌 DB의 실제 호환 요약 has_unknown/DEFERRED를 확인한다. G08-FIX2-X-DRAIN 1행은 consumer checkpoint를 통제한 상태의 실제 source bookkeeping 실패를 pause/drain이 영속 보류로 기록하는지 확인한다. 계획28행 외 보강2행이며 최종 신규 합계는 예상1,166행이다. 정본1,024는 유지한다.

marker 재시도는 최대2회·50ms의 다음 시도 출발 예산을 사용한다. SQLite busy 대기는 건강 transaction에서만 0으로 설정한 뒤 기존 값을 복원한다. 이미 진행 중인 OS I/O를 50ms에 강제 중단하거나 실제 fsync 지연까지 상한 보장한다는 의미는 아니다. 실패한 pending은 다음 consumer/control 기회에 남긴다.

### §17.2 소비자 재시도 빈도 보강 계획

소비자는 블록마다 _checkpoint_health를 부를 수 있으므로, 기회당2회만 제한하면 marker 실패 시 블록 수에 비례하는 재시도가 가능하다. 고정 시계의 G08-FIX2-X-RETRY-RATE 1행을 추가한다. 같은 1초 구간의 반복 consumer 호출은 추가 저장을 하지 않고, 다음1초 경계에서는 재시도하며, force checkpoint·pause/stop/resume 제어 기회는 즉시 재시도할 수 있어야 한다. source callback/submit에 DB I/O는 추가하지 않는다. 기존1초 checkpoint 주기와 같은 재시도 간격을 사용하고 pending/미상은 계속 보존한다.

정본1,024·계획28행은 그대로이며 FIX2 별도 보강은3행, 신규6파일 예상 합계1,167이다. 재시도 주기 guard 제거 변이를 W12로 추가하고, 최종 코드에서 mutation 전체·신규 시간 게이트·전체 CI 동등2회를 다시 고정한다. 앞선 전체 회귀는 변경 전 코드의 중간 증거로 보존한다.

#### §17.2.1 시간 게이트 측정·예산 결정 대기

최종 신규6파일은 **1,167 PASS / pytest69.76초 / runner70.417초**, 실패·skip·경고0이지만 승인60초를 초과했다. 행을 줄이지 않았다. testcase 합은 unit1.563/property<0.001/integration47.174/crash14.473/UI4.017/e2e1.374초다. 직전 실행은 unit0.726/integration27.469/crash12.216/UI2.540/e2e0.918초였고 신규 RETRY-RATE 행은0.122초다. 기존 파일 전반의 지연으로 부하/디스크 영향을 추정하지만 원인을 특정한 새 시스템 측정은 없다. 이 세션의 다른 무거운 검증이 끝난 뒤 단독으로 실행한 값이다.

같은 행을 유지한90초 예산 또는60초 유지 최적화/재측정 중 C00 결정을 이 창에 요청했다. 시간 게이트를 승인된 것으로 처리하지 않는다. 정책 결정과 독립적인 전체 회귀·coverage·정적 검사는 계속할 수 있으며 최종 준비 보고 전 시간 게이트의 상태를 명시한다.

#### §17.2.2 같은 코드 단독 재측정

최종 전체2회가 끝난 뒤 같은 코드·같은1,167행을 새 basetemp로 한 번 더 단독 실행했다. **1,167 PASS / pytest47.53초 / runner48.124초**, 실패·skip·경고0으로 기존60초 범위였다. 제품·시험·분모·fixture·assert를 바꾸지 않았고, argv 차이는 basetemp/XML 출력 경로뿐이다. 공통 필수 환경(PYTHONPATH·offscreen·bytecode 쓰기 금지)은 같다. 첫 runner는 HF_HUB_OFFLINE=1·MYPY_CACHE_DIR도 명시했고 재측정은 이 두 변수의 부모 환경을 상속했다. 따라서 완전히 같은 환경의 통제 A/B나 지연 원인 증명으로 해석하지 않는다. 둘 다 승인된 오프라인 시험 경로이며 실제 모델·네트워크 호출은 하지 않았다. 반복은 시간 변동을 확인하기 위한1회이며 초과 기록을 버리고 가장 빠른 숫자만 고른 결과로 기록하지 않는다.

따라서 예산을90초로 올리는 변경은 적용하지 않는다. 기존60초 예산의 최신 단독 측정은 PASS이며, 첫69.76초/70.417초 초과도 함께 인계한다. 이 변동의 시스템 원인은 특정하지 못했다. CI 러너나 실제 장비의 실행 시간 상한 보장은 아니며, C00 독립 검토·시간 예산 판단의 입력으로 두 측정 모두 제공한다. 기록은 time-repeat.log·xml·result.json과 기존 final-six.log·six-final.xml이다.


### §17.3 FIX2 최종 결과

기준은 계속 **b92552059ef3b19b038e97cba3e3c44996fc5ee1 + G-P08 승인20파일**이다. Git archive의 다른 tracked 파일은 기준 commit bytes와 같음을 확인했다. 공유 작업 트리의 G-P11b 등 다른 작업자 변경은 넣지 않았다. PYTHONPATH와 부모·자식 import origin은 TEMP 사본 src로 고정/확인했다. §17의 실행 전 상태와 §17.1의 중간 관측은 이력이며 아래가 이번 최종 결과다.

| 지적 | 수정과 직접 확인 |
| --- | --- |
| G08R-11(S1) | recording.py의 _deferred_health_runs/_pending_health_markers는 새 epoch에서 지우지 않는다. _health_deferred는 현재 run의 checkpoint만 구분하므로 다음 정상 run의 checkpoint는 계속된다. marker pending은 성공 뒤에만 제거하고, 2회/50ms 다음 시도 예산을 넘으면 다음 기회로 유지한다. Library의 메모리 보류 사실이 marker 쓰기 실패 동안 읽기 모델의 has_unknown=True/DEFERRED를 지키며 새 정상 projection에도 보류를 영속한다. stop은 capture_health_pending의 canonical OPEN 검사와 세션 보류를 함께 사용한다. 수선 불가 시 저장 ACK 뒤 PAUSED·finalized=False·DEFERRED를 반환하고 finalize_unfinished로 회복할 수 있다. |
| G08R-12(S3) | _resolve_capture_health_deferred가 canonical OPEN 없음과 삭제 권위·body CAS를 재확인한 뒤 보류 metadata/메모리 표식만 해제한다. has_unknown·UNKNOWN_TAIL·불완전 계수는 유지한다. 성공 marker 유무·run ID 정렬 순서와 무관하게 같은 최종 사실로 표시한다. |

건강 SQLite transaction은 권위/root 구간 안에서만 busy_timeout을 잠시0으로 바꾸고 finally에서 원래 값을 복원한다. 일반 저장/세션 transaction의 timeout은 바꾸지 않는다. 실제 별도 SQLite write lock으로 marker 재시도·다음 기회 수선·timeout 복원을 확인했다. 기존 시작/저장 실패의 fatal 동작은 바꾸지 않았다. 최대 재시도 예산은 이미 실행 중인 OS fsync까지 강제 중단하는 실시간 보장이 아니다.

원 반례는 FIX1 사본에서 F6/F7 모두 stop의 HEALTH_RECOVERY_PENDING·FINALIZING과 has_unknown=False를 재현했다. 수정 사본의 검토자 **F1~F8 모두** 수락/저장 bytes 일치·FINALIZED·has_unknown=True·UNKNOWN_TAIL(mic/system)·최종 DEFERRED 해제를 확인했다. F6/F7의 마지막 canonical 상태는 RECOVERED_UNCLEAN+CLOSED이고 OPEN은0이다. 이 probe 실행은 formal case 수에 합산하지 않는다.

독립 보강은 계획 G08-FIX2-01..28과 X-PROJECTION/X-DRAIN/X-RETRY-RATE의3행으로 **31행**이다. 신규6파일 최종 **1167 passed in 47.53s / runner48.124초**, 실패·skip·경고0이다. 기존 승인 예산 60초의 최신 단독 측정은 PASS다. 예산90초 확대는 적용하지 않았다. 첫69.76초/70.417초 초과와 재측정47.53초/48.124초를 함께 인계한다. 정본1,024의 누락·추가·중복0, 기존 보강61·FIX1 51·FIX2 31을 별도 감사했다. source callback/submit에 DB 쓰기나 새 thread를 추가하지 않았다.

변이는 **M30+Y10+X11+Z10+W12=73/73 KILLED**, 최종 SURVIVED/INVALID0이다. 세 원인은 각각 W01(pending 조기 제거, FIX2-18), W02(begin에서 세션 보류 초기화, FIX2-01), W03(canonical OPEN 검사 누락, FIX2-21)이 검출했다. W04/W05는 marker 해제 누락/조기 해제, W06/W10은 읽기 모델/메모리 사실 누락, W07/W08/W09는 상한/다음 기회/SQLite timeout 복원, W11은 영속 projection의 보류 누락, W12는 소비자 재시도 주기 누락을 검증했다. 소비자 호출100회에 marker202회였던 중간 회귀를 고정 시계로 재현한 뒤, 소비자 재시도는1초 주기로 제한했다. 명시 제어 기회는 즉시 재시도한다. 앞선 두 전체 실행은 이 주기 보강 전의 중간 증거이며 아래 최종 두 번과 구분한다.

중간 W11 생존은 §17.1의 X-PROJECTION으로 보강했다. Z10은 이동된 drain 조건을 AST로 제거하도록 harness를 고쳤다. Z07/Z08은 의도대로 제품이 건강 오류를 잘못 전파해 해당 정상 동작 시험이 failed가 된 결과임을 로그에서 확인하고, 정상본 PASS·pytest failed/error 구분으로 재실행해 검출했다. fixture/collection 오류를 검출로 계산하지 않았다. 이 중간 결과와 원문을 지우지 않고 final-mutations.json에 최종73개를 따로 모았다.

최종 CI 동등 명령은 다음이며 서로 다른 basetemp로 두 번 실행했다. 각 실행은 --cov-append 없이 새 coverage를 수집했다.

```text
python -m pytest -q -p no:cacheprovider -W error::ResourceWarning --basetemp <OS TEMP 새 폴더> --junitxml <회차 XML> --cov=recoryn --cov-branch --cov-report=json:coverage.json --cov-fail-under=85
python scripts/check_coverage.py coverage.json
```

전체 1회: **21773 passed in 1461.87s (0:24:21)**. tests/ui 1414건·K 36행 포함. 실패0, 환경 skip 0건. check_coverage 출력 전문:

```text
domain: line=99.18%/95% branch=97.89%/90% PASS
capture: line=99.85%/95% branch=98.57%/90% PASS
jobs: line=99.10%/95% branch=96.04%/90% PASS
storage: line=95.92%/95% branch=91.16%/90% PASS
security: line=98.11%/95% branch=94.43%/90% PASS
content: line=99.59%/95% branch=98.75%/90% PASS
all: line=94.19%/85% branch=88.51%/80% PASS
```

전체 2회: **21773 passed in 1361.30s (0:22:41)**. tests/ui 1414건·K 36행 포함. 실패0, 환경 skip 0건. check_coverage 출력 전문:

```text
domain: line=99.18%/95% branch=97.89%/90% PASS
capture: line=99.85%/95% branch=98.57%/90% PASS
jobs: line=99.10%/95% branch=96.04%/90% PASS
storage: line=95.92%/95% branch=91.16%/90% PASS
security: line=98.11%/95% branch=94.43%/90% PASS
content: line=99.59%/95% branch=98.75%/90% PASS
all: line=94.19%/85% branch=88.51%/80% PASS
```


두 coverage JSON은 모두 src/recoryn의77파일뿐이며 TEMP fixture 오염0이다. ruff check·format(190파일)·mypy src/recoryn scripts packaging(90 source files)은 PASS다. G04 보호 AST 해시4e1045da5910461e1e12c2cc7200b1f03c5cd31ef2d3dd5bcc941b0c4d14cb1f를 유지했다. GC-P02와 G-P11a fixture를 이번 FIX2에서 수정하지 않았다.

### §17.4 FIX2 파일·LF hash·인계

FIX1 대비 제품2파일(recording.py·library.py), 시험1파일(test_track_health.py), 본 문서1파일만 바뀌었다. b925520 대비 전체 범위는 계속 승인20파일이다. 아래19개와 본 문서 최종 hash(FIX2_READY/manifest)를 함께 고정한다. 검증 시작 이후 제품·시험19파일의 LF bytes는 변하지 않았다.

| 파일 | SHA-256(LF) |
| --- | --- |
| src/recoryn/domain/capture_health.py | b224c531f47d14db1261f40cc8ede721b452a8fd431e3692cdc09e2b06b18108 |
| src/recoryn/app/recording.py | ba8224af9b03605b859942151dc65126295ebe431885cc19eb3a65554573e0af |
| src/recoryn/app/desktop.py | 5cf35b4d5f39f8e8712c0ee22828ea9597923d3e832113f2ab5ae75463255464 |
| src/recoryn/app/power.py | 717c55cd27e92f2e0d4b9b135e49d95e0c887f5db96e000629f1e010fde8e81f |
| src/recoryn/app/recovery.py | 2ce3198c9ab5b3a7a9cfd2e3765e757c953d1b16628bb469420352767b8059bf |
| src/recoryn/app/status.py | 8e03ab6718843e178400255b80215c63e9dcd65680992275ebd4e2c1de0bddf5 |
| src/recoryn/storage/library.py | baf06bd0d1151c7197912fc8479585c7c450c5c213bd5f5807dae30aac01ae29 |
| src/recoryn/ui/main.py | 6af04c961a9b930af2673e910dfb344100d580c01a658c7ca0f5fa8c48df32b4 |
| src/recoryn/cli.py | 11fead0e1705c70caa19f8f7ba86881598ac45641612b594344a160ddcf8c593 |
| tests/unit/test_track_health.py | d7f51f78e39a720fe020a27ead2f29d1977d852ae3a7dc3c6788ed012f1f7a2c |
| tests/property/test_track_health_case_space.py | e03b34e0361783e77c519f889bff2268c2af6d0ef7a1ab946acda5167064b39d |
| tests/integration/test_track_health.py | dff40c839ee1e4adfc96f7ac566fa86f5dfbd77cae26104adaf78cf7bd106951 |
| tests/integration/test_health_crash.py | af2cc7f8e46ed6a24fe0819d9425a29d230adf8861b5998d3fe4428532a4f1b6 |
| tests/ui/test_track_health_ui.py | 31d6ccaf353333ebffe5aec807709b5c118db1ff313d5db851652ddd717a331b |
| tests/e2e/test_health_export.py | 24edb1f4e0ac36bb6598c77eef3dc6058c737e52e7f744cfeb90055381518044 |
| tests/integration/test_app_service.py | 18340895ed084635c1aac2435b2c68dd0042ae35676b8d5eae0639d533b5271d |
| tests/ui/test_capture_start_ui.py | f42e90052032eb0d70e71c7e3b5fd692ba9d295a840af7cf859686d42230068b |
| tests/integration/test_pending_deletion_restart.py | 1c0a8cb6778fc40a820ef7f2c6ec71604af4898082c41dcc5c4432170daea8bc |
| tests/integration/test_unfinished_recovery.py | bd0c7f0afb9be80dd405cc424de3d51d4a5d99dd4516ec5265887c28d6fcfeca |


명령·XML·coverage·정상본·변이 source hash/실패 node·probe는 OS TEMP recoryn-g08-fix2-0r0tb65y/final에 보관했다. 핵심은 final-validation-results.json, final-six.log, six-final.xml, full1/2.xml, final-full1/2.log, final-coverage1/2.log, coverage-full1/2.json, child-origin.log, scope-audit.json, final-case-audit.json, final-mutations.json, ../reviewer-baseline-f6f7.log, probe_fault_matrix.py.log, probe_tail_prefix.py.log, reviewer-fixed-results.json이다. 최종20파일 hash는 g08-fix2-ready-manifest.json이다.

G08R-11/12의 제품 수정은 위 반례에서 확인했으며 독립 재확인은 C00 지정 검토자가 담당한다. 시간 게이트는 위에 기재한 상태로 인계한다. 실제 장치·전원 장애·계정·모델·네트워크는 수행하지 않았다. G-P09에는 canonical OPEN 상태 보존/복원 후 tail 수선과 보류 표시의 의미를 인계한다. 새 메모리 보류 set는 backup 구성요소나 새 영속 표가 아니다. G-P17은 저장 종료 ACK와 건강 기록/관측의 성공을 구분하는 기존 계약을 유지한다. GS-P02 계약 파일은 이번 수정에서 변경하지 않았으며 그 승인 대기로 돌아간다.

## §18 FIX3 계획: 호환 gap 생략 표식 누락

C00 정확한 tree eec1615d(기준8ca52f8)의 G15-IDX-UI-n0-tracks2가 rejected139 상태에서 gap 상세 합9,120과 dropped_frames63,360의 불일치를 검출했다. 이는 C00 측정 인용이다. 시작 시 승인20파일이 eec1615d의 LF hash와 같음을 확인하고, **8ca52f8+G08 20파일** 새 TEMP archive를 준비했다. 제품·시험 쓰기는 계속 이20파일뿐이며 test_seal_mutex.py를 바꾸지 않는다.

직접 읽은 원인 후보는 storage/library.py의 _store_health가 epoch/top-level의 gaps를16개로 줄이면서 gap_detail_truncated를 설정하지 않는 점이다. _bounded_health_projection의 byte 축약/필드 제거도 같은 구체 표식이 필요하다. 단순히 G15 단언을 없애거나 dropped_frames를 남은 상세 합으로 낮추지 않는다. 원본 snapshot·canonical event/track 누계는 그대로 보존하고 호환 view의 생략만 표시한다.

추가 계획은 **8행**, ID G08-FIX3-I01..I04와 U01..U04다. 통합4행은 두 트랙의 비인접 거부 {132개/checkpoint8,40개/중간 checkpoint 없음/2epoch,16개 경계,17개 첫 초과}를 실제 BoundedCaptureQueue.offer의 용량 거부로 주입한다. queue 자체 거부 회계·저장 bytes·epoch별 accepted/dropped·gap 합/표식·canonical QUEUE_DROP 합을 손계산과 대조한다. 132개 거부는 트랙당63,360frame이고, checkpoint를 나눠 canonical RAM buffer가 포화하지 않게 한다. 단위4행은 byte 예산에서 gap 축약, gap 전체 제거, gap 이외 상세만 축약, 축약 불필요의 경계다. 입력 불변도 확인한다.

정본1,024·기존 보강은 유지하며 새8행은 별도 감사한다. 전체 이벤트/누계가 보존되는 조건과 RAM 상세 포화로 이미 불완전하다고 표시하는 조건을 혼동하지 않는다. 이 반례는 이벤트 buffer 범위 안 또는 중간 checkpoint로 모든 QUEUE_DROP을 canonical에 영속하고 그 합을 확인한다. 상세를 생략한 view를 완전한 상세로 해석하는 불일치를 막는 시험이다.

변이 표적은 epoch16개 축약 표식 제거, top-level16개 표식 제거, byte 축약 표식 제거, 전체 필드 제거 표식 제거, dropped 누계를 상세 합으로 덮기, canonical QUEUE_DROP 기록 누락이다. G15 해당 행 반복·관련/G08/G04/G05/G07/G15·UI·정적 검사·CI 동등 전체 검증을 수행한다. 아직 새 시험 실행 결과는 없다.


### §18.1 FIX3 직접 재현과 원인 확정

새 정상본은 기준 **8ca52f8**의 archive에 승인20파일만 덮은 사본이다. 시작20파일은 eec1615d와 같았다. eec1615d 제품에 새 시험을 붙인 첫 실행은 6FAIL/2PASS였으며, 그중 U03은 시험 입력160event가 실제60KiB 미만인 준비 오류였다. 이를256event로 고쳐 실제 byte 경계를 넘기고, 제품 수정 전후를 같은 최종 시험으로 다시 대조한다. 준비 오류를 제품 결함 수로 세지 않는다.

수정 전 `red2-temp/test_gap_projection_marks_omis0/library.sqlite`를 mode=ro로 직접 읽었다. 양쪽 트랙 각각 호환 epoch의 dropped_frames=63,360, gaps16개 합=7,680, gap_detail_truncated 없음이었다. 반면 canonical track의 gap 합=63,360, canonical QUEUE_DROP132건 합=63,360이었다(original-db-observation.json). C00의9,120은 C00 원 측정 인용이며, 여기서 직접 측정한 일정한 비인접 거부 패턴의 상세 합은7,680이다. 이를 같은 측정값처럼 쓰지 않는다.

원인은 **storage/library.py의 _store_health(epoch16개 축약·top-level16개 축약)** 와 **_bounded_health_projection(byte 축약)** 가 detail_complete=False만 쓰고 기존 소비자가 보는 gap_detail_truncated를 빠뜨린 것이다. epoch 분할이나 checkpoint 병합으로 canonical 누계가 사라진 것이 아니다. 수정은 세 지점에서 gaps를 실제로 줄일 때만 기존 gap_detail_truncated=True를 더한다. dropped_frames·정확 union 계산·canonical event/track 저장 경로는 바꾸지 않는다. events/loss_ranges만 줄이면 gap 표식을 새로 만들지 않는다.

fallback의 필드 전체 제거 직전까지 byte 축약 while이 남은 gaps를 이미 빈 목록으로 만들고 그때 표식을 남긴다. 따라서 별도 fallback 표식 코드는 중복 방어가 되어 추가하지 않았다. '전체 필드 제거 표식 제거' 변이 대신 완전한 gaps에도 표식을 강제로 붙이는 거짓 생략 변이를 넣는다. 계획 분모8행은 그대로이며, canonical 누계를 상세 합으로 낮추거나 canonical QUEUE_DROP을 생략하는 변이도 포함한다.

새8행 정상본은 **8PASS/4.10초**다. I01은 두 트랙 각각132회 거부·63,360frame 누계, 보이는 상세7,680frame+생략True, canonical132건 합63,360, 수락 PCM bytes 일치를 확인했다. I02의2epoch도 각 epoch/트랙별 canonical 합·표식·저장 순서를 확인했다. I03의16회는 상세 합=누계·생략False, I04의17회는 누계8,160·상세7,680·생략True다. U01~04는 byte 축약·전체 제거·event만 축약·축약 없음 및 입력 불변을 확인한다.

신규6파일 단독은 **1,175PASS**, pytest57.41초/runner58.045초로 기존60초 예산 안이다. 정본1,024와 종전 보강143은 그대로이고 별도 FIX3-ID8개가 늘었다(1,024+143+8=1,175). 새8ID 누락·중복0, test_seal_mutex.py 원문 불변, 사본 범위 밖 제품·시험 변경0, 부모·자식 import가 모두 사본/src인 것을 확인했다. 이 절 작성 시 관련·전체 회귀와 변이 결과는 아직 진행 중이며 아래 결과 절에서 완료값을 구분한다.


### §18.2 이전 epoch의 정확 union 보존 보강

최초 표식 수정 뒤 I02 DB를 더 읽어 **이전 epoch known_loss_frames/known_lower_bound가19,200→7,680으로 감소**함도 직접 확인했다(epoch-union-observation.json). _store_health가 이전 epoch의 이미16개로 줄인 loss_ranges에 track_loss를 다시 적용했기 때문이다. canonical은 그대로였으나 '상세 생략이 정확 누계를 지우지 않는다'는 이번 수락 조건을 충족하지 못하므로 같은 허용 파일에서 고친다.

I01~I04의 epoch별·top-level 단언에 손계산 union까지 추가했다(새 ID 추가나 기존 기대 약화 없음). 표식만 고친 중간 제품에서는 I02가7680==40*480으로 **1FAIL**했고(union-red.xml), 보강 뒤8행은 **8PASS/3.86초**다(final-green.xml). _store_health는 새 snapshot의 tracks를 만들 때 완전한 loss_ranges에서 union을 한 번 계산하며, 기존 epoch를 호환 view에 옮길 때는 줄인 ranges에서 다시 계산하지 않는다. canonical 저장은 계속 원 snapshot을 사용한다. union 재계산을 되살리는 변이 V07을 추가해 FIX3 변이는7개로 한다.

§18.1의6파일58.045초와 G15 반복3회는 표식만 고친 중간 제품의 관찰이다. 그 뒤 진행 중이던 관련 회귀는 끝나기 전에 중단했으며 완료 PASS로 세지 않는다. **최종 검증은 새 final/tree(8ca52f8+20파일)**에서 모든 시험·정적·coverage를 다시 실행한다. 최종값은 다음 절에 별도 기록한다.


### §18.3 최종 반례·변이·관련 회귀

최종 제품/시험은 **final/tree(8ca52f8+20파일)** 에서 실행했다. 부모·자식 import 모두 사본/src인 것을 다시 확인했다. 정상8행8PASS, eec1615d 제품+같은 최종8행은 **5FAIL/3PASS**였다. 오류/collection 실패0이며 실패는 gap 표식·이전 epoch union 단언이다. 첫 U03 준비 오류는 최종 재현에서 제거됐다.

| 변이 | 단일 변경 | 검출 ID |
| --- | --- | --- |
| V01 | epoch의16개 gap 생략 표식 제거 | G08-FIX3-I01 · G08-FIX3-I02 · G08-FIX3-I04 |
| V02 | top-level의16개 gap 생략 표식 제거 | G08-FIX3-I01 · G08-FIX3-I02 · G08-FIX3-I04 |
| V03 | byte 축약 gap 표식 제거 | G08-FIX3-U01 · G08-FIX3-U02 |
| V04 | dropped 누계를 남은 gap 합으로 축소 | G08-FIX3-I01 · G08-FIX3-I02 · G08-FIX3-I04 |
| V05 | canonical QUEUE_DROP insert 생략 | G08-FIX3-I01 · G08-FIX3-I02 · G08-FIX3-I03 · G08-FIX3-I04 |
| V06 | 생략하지 않은 gaps에도 표식 강제 | G08-FIX3-U01 · G08-FIX3-U03 · G08-FIX3-U04 · G08-FIX3-I03 |
| V07 | 이전 epoch의 축약 ranges에서 union 재계산 | G08-FIX3-I02 |

**FIX3 변이7/7 검출**, 정상8행 PASS다. FIX2까지의73/73은 이전 절의 과거 실행 근거이며 이번에73개를 재실행했다고 집계하지 않는다. 이번 제품 변경과 연관된 축약·정확 누계·canonical 보존의7개를 새로 실행했다. source hash·실패 node·XML은 fix3-mutations.json과 V01~07.xml/log에 있다.

TEMP 플러그인으로 G15 원 시험의 queue offer에 seq%10==1일 때 실제 용량 거부를 주입했다. 원 시험 파일·단언은 그대로다. eec1615d 제품에서는 같은 gap 합 단언으로1FAIL, 최종 제품에서는 **1PASS**, 두 트랙 각각120회/총240회 거부·저장1,036,800frame·수락 회계 일치를 확인했다. 정상 디스크의 우연한 거부0만으로 반례를 닫지 않았다. forced.py·forced-results.json·g15-forced-original/fixed.log가 근거다.

같은 G15 원 행을 주입 없이도 최종 제품에서 **3회 각1PASS**했다(19.331/21.248/19.389초, runner). 주입 정상본은 tick root최대1.9ms·sealer4.7ms·writer12.2ms, consumer seal/register/verify/decode 및 mutex 안 journal read0, 장기 보유0이었다. 이는 이 PC TEMP/fake PCM 측정이며 실제 장치·전원 장애·전체 디스크 성능 보장은 아니다.

최종 신규6파일 **1,175PASS·pytest57.57초/runner58.247초**, 기존60초 예산 이내다. 관련/G-P04·G-P05·G-P15·G-P07·UI 묶음 **2,164PASS·실패/오류/skip0**(623.44초 pytest,632.220초 runner). 그중 tests/ui 전체는 **1,465PASS**다. 선택 파일 목록·명령은 validation-results.json에 있다. ruff check PASS, format191파일 PASS, mypy91source파일 PASS.

정본1,024행 누락·추가·중복0, 기존1,167node 유지+FIX3별도8node=1,175다(case-audit.json). 기존 시험 두 파일은 새 함수 각각1개를 뺀 AST가 eec1615d와 동일하다(existing-test-ast-audit.json). G15 원 시험은 수정하지 않았다. CI 동등 전체·coverage 완료값은 다음 절에 기록한다.


### §18.4 CI 동등 전체·최종 인계

최종 전체 오프라인은 **22,450PASS / 실패0 / 오류0 / skip0 / 경고0**, runner **1480.407초**다. 동일 실행의 coverage와 check_coverage 전7묶음이 PASS했다. coverage 대상은 사본 src/recoryn의 **78파일**뿐이며 임시 legacy fixture 모듈0이다. 전체의 정확한 명령·원출력은 validation-results.json·full.log·full.xml·coverage-full.json·coverage.log에 있다.

```text
domain: line=99.18%/95% branch=97.89%/90% PASS
capture: line=99.85%/95% branch=98.57%/90% PASS
jobs: line=99.29%/95% branch=96.23%/90% PASS
storage: line=95.92%/95% branch=91.20%/90% PASS
security: line=98.11%/95% branch=94.43%/90% PASS
content: line=99.59%/95% branch=98.75%/90% PASS
all: line=93.70%/85% branch=88.20%/80% PASS
```

부모·자식 import는 child-origin.log에 기록했다. 8ca52f8 archive 대비 사본의 범위 밖 제품·시험 변경0, G15 시험 원문 불변, 검증 시작 뒤 제품·시험19파일 LF hash 불변을 확인했다. 문서는 결과 절만 추가하고 사본에 마지막으로 동기화한다. FIX2(eec1615d) 대비 변경은 library.py·시험2파일·본 문서의 **4파일**이며 나머지16파일은 같다. 기존 문서 bytes의 LF 기준 prefix도 보존했다.

| 파일(본 문서 제외19개) | SHA-256(LF) |
| --- | --- |
| src/recoryn/domain/capture_health.py | b224c531f47d14db1261f40cc8ede721b452a8fd431e3692cdc09e2b06b18108 |
| src/recoryn/app/recording.py | ba8224af9b03605b859942151dc65126295ebe431885cc19eb3a65554573e0af |
| src/recoryn/app/desktop.py | 5cf35b4d5f39f8e8712c0ee22828ea9597923d3e832113f2ab5ae75463255464 |
| src/recoryn/app/power.py | 717c55cd27e92f2e0d4b9b135e49d95e0c887f5db96e000629f1e010fde8e81f |
| src/recoryn/app/recovery.py | 2ce3198c9ab5b3a7a9cfd2e3765e757c953d1b16628bb469420352767b8059bf |
| src/recoryn/app/status.py | 8e03ab6718843e178400255b80215c63e9dcd65680992275ebd4e2c1de0bddf5 |
| src/recoryn/storage/library.py | 81e6e70287fec836071dda03a2935d72168d36e0ff348a1c374dd24d10c2f1e2 |
| src/recoryn/ui/main.py | 6af04c961a9b930af2673e910dfb344100d580c01a658c7ca0f5fa8c48df32b4 |
| src/recoryn/cli.py | 11fead0e1705c70caa19f8f7ba86881598ac45641612b594344a160ddcf8c593 |
| tests/unit/test_track_health.py | a453b8726548cc313a99c0bd33bbc51c74e07744dbd84f75726a0adb128448f7 |
| tests/property/test_track_health_case_space.py | e03b34e0361783e77c519f889bff2268c2af6d0ef7a1ab946acda5167064b39d |
| tests/integration/test_track_health.py | 5629123372cd467ba7d4c9ba933966c5db4a64adbb5ee8f27254f8ee683250ff |
| tests/integration/test_health_crash.py | af2cc7f8e46ed6a24fe0819d9425a29d230adf8861b5998d3fe4428532a4f1b6 |
| tests/ui/test_track_health_ui.py | 31d6ccaf353333ebffe5aec807709b5c118db1ff313d5db851652ddd717a331b |
| tests/e2e/test_health_export.py | 24edb1f4e0ac36bb6598c77eef3dc6058c737e52e7f744cfeb90055381518044 |
| tests/integration/test_app_service.py | 18340895ed084635c1aac2435b2c68dd0042ae35676b8d5eae0639d533b5271d |
| tests/ui/test_capture_start_ui.py | f42e90052032eb0d70e71c7e3b5fd692ba9d295a840af7cf859686d42230068b |
| tests/integration/test_pending_deletion_restart.py | 1c0a8cb6778fc40a820ef7f2c6ec71604af4898082c41dcc5c4432170daea8bc |
| tests/integration/test_unfinished_recovery.py | bd0c7f0afb9be80dd405cc424de3d51d4a5d99dd4516ec5265887c28d6fcfeca |

본 문서의 최종 SHA-256은 FIX3_READY와 **g08-fix3-ready-manifest.json**에 기록한다. 최종20파일 manifest·최종 감사는 아래 OS TEMP에 있다.

C:/Users/gangd/AppData/Local/Temp/recoryn-g08-fix3-34k3mgso/final

초기 red2/green/union-red의 원본 DB·중간 실행은 위 폴더의 상위(recoryn-g08-fix3-34k3mgso)에 보존했고, 핵심 관찰 JSON/실패 log·XML은 final에도 복사했다.


확인 범위는 fake PCM·실제 TEMP SQLite/파일·기존 오프라인 시험이다. 실제 장치·모델·계정·네트워크·전원 장애 검증은 하지 않았다. 새로운 schema/API/표는 추가하지 않았다. 이번 독립 재확인은 C00 지정 검토자가 맡으며, 작성자 실행을 최종 승인으로 집계하지 않는다. GS-P02 구현은 G-P08 push와 C00 시작 신호 전까지 대기한다.
