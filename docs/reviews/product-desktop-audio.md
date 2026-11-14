# BR12 데스크톱·오디오 통합 독립 검토

검토자: B12 Windows 오디오 담당. 작성자·수정자·최종 통합자: B10. 날짜: 2026-11-14.
범위는 B10의 `app/desktop.py`, `recording.py`, `media.py`, `ui/main.py`, `tasks.py`, `meter.py`와 관련 시험이다. B12의 native/audio 자체 구현 승인이 아니다.
작성 허용 결과는 이 문서와 [독립 통합 시험](../../tests/integration/test_desktop_independent.py)뿐이다. 검토 대상 소스는 수정하지 않았다.

## 방법과 계약

- 실제 임시 Library·SQLite·PCM bundle을 사용하되 캡처는 `ControlledSource`로 대체했다. UI는 Qt offscreen과 Event/QEventLoop로 제어했다.
- 기존 작성자 시험의 성공을 oracle로 복사하지 않았다. 48 kHz의 48,000 frame=1초, 정확한 source frame offset, 실제 worker/device ACK, DB 상태와 예외 경계를 독립 기대값으로 사용했다.
- DB의 INTERRUPTED/FINALIZED와 source/writer 종료 확인은 별개다. ACK 실패는 성공이 아니며 핸들과 Library 소유권을 유지해야 한다.
- manifest만 실패하면 확정 PCM·DB FINALIZED와 `manifest_sync_pending=True`를 보존한다. 원본 성공을 후속 projection 예외로 실패 처리하지 않는다.
- unknown/arrival-only/invalid 시계는 숫자 timestamp가 있어도 correlated offset으로 승격하지 않는다. pause/resume은 새 epoch와 실제 시간 gap을 유지한다.
- 임의 예외 문자열은 표시 가능한 안전 code가 아니다. 정상 ready/packet/SILENT는 녹음 실패 경고가 아니다.

## 최초 발견 기록

첫 읽기 snapshot의 SHA256이다. 병렬 통합 중 개별 수정이 진행됐으므로 아래 전체를 하나의 동결 tree로 주장하지 않는다.

| 파일 (`src/recoryn/` 기준) | 최초 읽기 SHA256 |
| --- | --- |
| app/desktop.py | `7A5693B0C8754F801F161BDFA6C77F1E3B8706B6865FF70F07A6B75FDB0372D2` |
| app/recording.py | `1248C50007172A7721A159E3D626568254079AE5222F93876A1470F951F14353` |
| app/media.py | `9BED8444A871B1E8C6E8C5C6E9BCF6D0B9C9BEFDB98A49744B4D53B1CB3DEA0D` |
| ui/main.py | `451505C4313D6D7A95DD7ECB1077CD66928DCA19446402667AC0532B4240382E` |
| ui/tasks.py | `EDA34DADE770DD03A291C098B9B9272DE712C07EF455A7AC1F62EDC697C3062B` |
| ui/meter.py | `954D036F3DB983CA2438DCDF524EB82F8A34826A0FB2C14A622C0974EEF3FFB8` |

### BR12-01 / S1 / source 종료 누락

위치: `app/desktop.py:DesktopRecorder.close`.
반례: 녹음 시작→DB를 적법하게 INTERRUPTED로 전이→close. 기존 구현은 DB active 상태일 때만 stop을 호출하여 live source를 둔 채 반환했다.
시험: `test_interrupted_session_close_must_still_ack_live_sources`; 실제 실패는 `close returned while the source was still live`.
해결 조건: DB 상태와 무관하게 모든 소스 종료 ACK를 얻고 writer를 join한다. 실패하면 종료 성공으로 반환하지 않는다.

### BR12-02 / S1 / writer 실패 후 RECORDING 유지

위치: `app/recording.py:RecordingService._consume`, `app/desktop.py:_submit`, `ui/main.py:_tick`.
반례: `register_chunk`에 OSError 주입→96,000 frame 제출→writer 종료. 사용자가 pause/stop 하기 전에는 DB가 RECORDING이고 UI가 계속 REC였다.
시험: `test_live_writer_failure_is_visible_without_user_pause_or_stop`; 실제 DB 값 RECORDING, 기대 INTERRUPTED.
해결 조건: 입력 gate 닫기·queue close·저장 가능한 INTERRUPTED 즉시 반영. DB까지 실패하면 메모리 health에 실패를 보존하고 UI에 지속 녹음을 보장하지 않는 상태를 표시한다.

### BR12-03 / S2 / 단일 PCM record가 clip 상한 우회

위치: `app/media.py:prepare_clips`의 record 처리.
반례: 48 kHz 96,000 frame 단일 record에 `max_seconds=1`. 기존 출력은 96,000 frame WAV 하나였다.
시험: `test_single_large_packet_cannot_bypass_clip_duration_or_source_mapping`; 기대 길이 `[48000,48000]`, source 시작 `[0,48000]`, output 시작 `[0,0]`, offset `[0,1000]` ms.
해결 조건: record 내부에서도 duration/byte 상한으로 나누고 각 조각의 source offset·timestamp를 정확히 이동한다.

### BR12-04 / S2 / 불확실한 시계의 정밀 시간 승격

위치: `app/media.py:prepare_clips`의 origin/valid timestamp 판단.
반례: non-None capture timestamp에 clock_quality UNKNOWN/ARRIVAL_ONLY/INVALID를 각각 사용. 기존 offset은 모두 0 ms였다.
시험: `test_uncertain_clock_is_not_promoted_to_correlated_clip_time` 3개 parameter. 기대 offset None, timing_quality unknown.
해결 조건: trusted correlated 품질과 TIMESTAMP_ERROR 부재를 함께 요구하며 origin과 clip 계산에 동일 판단을 적용한다.

### BR12-05 / S2 / 정상 native 상태의 오류 표시

위치: `app/desktop.py:_on_health`, `ui/main.py:_tick`.
반례: fake native ready→정상 packet→UI tick. event 이름이 제거된 track-only health가 CAPTURE_WARNING으로 표시됐다.
시험: `test_normal_native_status_is_not_presented_as_capture_failure`.
해결 조건: 정상 lifecycle/packet을 경고로 승격하지 않는다. SILENT와 예외적 discontinuity/timestamp/release 실패는 구분한다.

### BR12-06 / S1 / 임의 예외 문자열의 UI 유출

위치: `ui/tasks.py:Task.run`의 safe code 분류.
반례: `RuntimeError("BR12SECRETCANARY123")`를 발생시키면 대문자·숫자라는 이유로 문자열 전체가 failed signal에 전달됐다. 실제 비밀은 사용하지 않은 canary다.
시험: `test_arbitrary_uppercase_exception_text_is_not_a_trusted_ui_code`; 기대 OPERATION_FAILED_MEDIA_PRESERVED.
해결 조건: 명시한 고정 code만 허용한다. 신뢰 domain 예외의 ACK code 전달은 보존하되 문자열 모양만으로 허용하지 않는다.

### BR12-07 / S1 / FINALIZED 후 projection 재실패

위치: `app/desktop.py:DesktopRecorder.stop`의 추가 health/manifest 쓰기.
반례: 모든 write_manifest 호출에 OSError 주입→48 frame 녹음→stop. 내부 finalize는 pending 성공인데 Desktop의 재쓰기 예외가 호출자까지 전파됐다.
시험: `test_desktop_stop_preserves_manifest_only_failure_contract`.
해결 조건: health를 finalize 전에 반영하고 단일 finalize 결과를 유지한다. 반환 FINALIZED+pending True, 48 frame 보존, source 종료를 함께 충족한다.

## 1차 독립 재확인: BR12-01~07

B10 수정 후 위 7건과 아래 양성 경계 시험을 직접 실행했다. 15 PASS, 4.05초, xfail 강제 해제·warning 오류화, 실행 전후 아래 여섯 파일 SHA256 일치.

| 파일 (`src/recoryn/` 기준) | 재확인 snapshot A SHA256 |
| --- | --- |
| app/desktop.py | `132DE2B9A030D62E3167363C98826CC2EAEEE66FB5A3077719AB32C91D6CC9D4` |
| app/recording.py | `F26715CD6176BEB446E6C8FF5A5F64C8630E0B0120649C8C372AD55ECA0C8A74` |
| app/media.py | `E1AE8E6A1583963719A62500F69591D61E9A9819658A598C22AB6CAE0204F736` |
| ui/main.py | `999E4003702CF484B4FC4F6DEED3C2CE0A9F2C25EFDF00DE7529327BEA2EAD07` |
| ui/tasks.py | `78CD474D17C03403AA175524C19AA389F870F1176C0DCBAF363476D1308D8A9A` |
| ui/meter.py | `954D036F3DB983CA2438DCDF524EB82F8A34826A0FB2C14A622C0974EEF3FFB8` |

| ID | 상태 | 코드와 독립 oracle 대조 결과 |
| --- | --- | --- |
| BR12-01 | RECHECKED | close가 상태 조회 전에 `_close_sources` 수행; INTERRUPTED의 live fake source 종료 확인. |
| BR12-02 | RECHECKED | `_consume` 오류에서 gate/queue 종료와 `_mark_interrupted`; 실패 메모리 health·UI 처리 확인. register 실패 후 DB INTERRUPTED 실측. |
| BR12-03 | RECHECKED | packet_offset 루프로 duration 및 8 MiB-derived-payload 예산 적용; 2개 WAV의 frames/source/시간 손계산 기대값 모두 일치. |
| BR12-04 | RECHECKED | `_correlated`가 DEVICE_CORRELATED/SYNTHETIC만 허용하고 TIMESTAMP_ERROR 배제; 3개 부정 품질 모두 unknown. |
| BR12-05 | RECHECKED | 정상 ready/packet/stopped와 SILENT를 경고에서 제외; UI 정상 시작 후 CAPTURE_WARNING 없음. |
| BR12-06 | RECHECKED | 고정 SAFE_CODES 및 신뢰 domain 예외만 허용; canary 차단과 MODEL_DOWNLOAD_ACK_PENDING 양성 전달 모두 통과. |
| BR12-07 | RECHECKED | `RecordingService.stop(health_extra=...)`로 finalize 전 health 게시; Desktop 재쓰기 제거. FINALIZED/pending/media/source 기대값 모두 일치. |

추가 양성 확인: 부분 start 실패 시 두 소스 stop과 48 frame 보존, stop ACK timeout 시 RECORDING·Library lock 유지 후 재시도 성공, worker 작업 중 Qt 응답과 GUI thread 완료, pause/resume 새 epoch와 60초 모의 gap, health 개수 상한 256. 모델 shutdown ACK 실패 시 ContentStore를 먼저 닫지 않고 UI polling을 차단하며 재시도 종료에 성공했다.

정확한 실행 명령(PowerShell):

```powershell
$br12RunTemp = Join-Path $env:TEMP ('recoryn-br12-recheck-' + [guid]::NewGuid().ToString('N'))
$env:QT_QPA_PLATFORM = 'offscreen'
$env:PYTHONDONTWRITEBYTECODE = '1'
& .venv/Scripts/python.exe -m pytest -q tests/integration/test_desktop_independent.py --runxfail --basetemp $br12RunTemp -p no:cacheprovider --tb=short -W error
```

당시 basetemp: `C:\Users\gangd\AppData\Local\Temp\recoryn-br12-recheck-0a50bb4154a04ba3a72e8a949d40c89a`. 수정 전 실행은 별도 고유 TEMP에서 실제 assertion 실패를 확인했다. 초기 중간 실행의 7FAIL/3PASS, 8FAIL/5PASS, root 일부 수정 후 6FAIL/9PASS를 수정 후 성공으로 덮어쓰지 않는다.

## 추가 발견: BR12-08 / S1 / 새 start의 이전 source 소유권 유실

발견 snapshot: 위 A, `app/desktop.py:66`의 `start`.
반례: start→DB INTERRUPTED→이전 fake source의 stop을 STOP_TIMEOUT으로 설정→같은 DesktopRecorder.start 재호출. 기존 코드는 상태가 active가 아니므로 `_sources={}`와 `recording=`을 덮어쓰고 새 소스를 시작했다. 이전 소스/worker의 제어 핸들을 잃는다.
시험: `test_new_start_cannot_orphan_an_interrupted_source_with_missing_ack`; 실제 결과 `DID NOT RAISE any of (RecordingError, StateConflict)`, 1 FAIL/15 deselected, 0.30초.
명령은 위와 같되 `-k new_start_cannot` 적용, 고유 basetemp prefix `recoryn-br12-start-`, warning 옵션 제외.
해결 조건: 이전 DB 상태와 무관하게 source/writer 소유권을 해소한 뒤에만 신규 세션을 시작한다. ACK 실패 시 예외와 기존 recorder/session/source 핸들을 유지하고 새 소스를 열지 않는다.
상태: OPEN. B10에 반례·시험·해결 조건 전달, 수정 및 같은 검토자의 재확인 필요. 기존 7건 재확인이 이 새 S1의 통과를 뜻하지 않는다.

추가 실행: `-k 'missing_stop_ack or timestamp_error_flag or disconnect_and_timestamp'`로 5 PASS/15 deselected, 0.97초. pause·stop·close 각각 STOP_TIMEOUT에서 기존 RECORDING/source/Library lock 보존 후 재시도 성공, TIMESTAMP_ERROR가 DEVICE_CORRELATED 표기를 무효화, fake 장치 오류·timestamp 경고 보존 및 대체 장치 미선택을 확인했다. 이는 물리 disconnect 시험이 아니다.

## 검증 한계

- 실제 microphone/loopback, 물리 disconnect, 장시간·성능·peak RSS, 실제 절전/복귀, Windows UI 접근성·배포물은 NOT_RUN이다. 60초 gap은 timestamp fixture이며 OS power notification 검증이 아니다.
- 이 시험은 제어된 source 실패/ACK와 SQLite·파일·Qt 통합을 검증한다. native COM/driver 적합성은 B11의 별도 검토와 G3 하드웨어 게이트다.
- media의 clip 단위 duration과 source mapping을 실행 검증했다. 8 MiB 경계의 모든 channel/format 조합, 세션 전체 메모리 상한, fault injection의 모든 파일 게시 단계는 이 리뷰의 실행 범위가 아니다.
- API/ABI 변경이나 외부 라이브러리 기능을 새로 단정하지 않았다. 이 통합 리뷰에는 외부 문서 검색이 필요하지 않았으며 B12 native ABI 출처는 별도 구현 보고에 남겼다.
- BR12-08 추가 직후 독립 파일 Ruff check 및 format --check PASS, `$env:MYPYPATH='src'; .venv/Scripts/python.exe -m mypy tests/integration/test_desktop_independent.py` PASS. 이후 추가 시험을 포함한 최종 파일 정적 검사와 최종 통합 tree 동결은 후속 기록으로 구분한다. 최종 통합 승인·G3/G4·commit/push는 B10 책임이다.

## 후속 독립 재확인: BR12-08 및 전체 8건

B10은 `DesktopRecorder.start`가 이전 recorder를 교체하기 전에 `self.close()`로 source ACK와 writer join을 확보하도록 수정했다. 원래 반례는 실패→통과했다. ACK 실패 동안 동일 recorder/session과 live source가 보존됐으며, ACK 허용 후 재시도는 이전 source·writer 종료를 확인하고 다른 session으로 새 source를 시작했다.

BR12-08: **RECHECKED**. BR12-01~07도 동일 전체 파일 실행에서 다시 통과했다. 이번 범위의 OPEN S0/S1/S2/S3은 0건이며 최종 CLOSED/통합 승인은 B10이 판단한다. 위 OPEN 표기는 발견 당시 기록이다.

최종 재확인 snapshot B: `app/desktop.py` SHA256 `8692790FC80693954E31F13FE51A788B8CBC832449413990D4F1D203D06BC600`. 나머지 다섯 대상 파일은 snapshot A와 동일하다. 대상 여섯 파일 모두 시험 실행 전후 해시가 일치했다. 저장소 전체 tree의 동결·승인을 뜻하지 않는다.

최종 독립 시험 SHA256: `38D908994276D22C077332766F7E2048281EA2087323E5416FAF491664BA3365`.
환경: Windows 11 build 26300, CPython 3.13.1 AMD64, PySide6 6.12.0, pytest 9.2.0, Qt offscreen.

실행 명령은 1차 재확인과 동일하며 prefix만 `recoryn-br12-final-`로 변경했다. 실제 basetemp는 `C:\Users\gangd\AppData\Local\Temp\recoryn-br12-final-625f54aff5a34902ba5c34deeb8f9d68`.
결과: **20 PASS, 2.27초**, `--runxfail`, `-W error`, `-p no:cacheprovider`. 임의 skip/xfail로 발견 사항을 숨기지 않았다.

최종 시험 파일에 다음 정적 검사를 별도 실행해 모두 통과했다.

```powershell
& .venv/Scripts/python.exe -m ruff check tests/integration/test_desktop_independent.py
& .venv/Scripts/python.exe -m ruff format --check tests/integration/test_desktop_independent.py
$env:MYPYPATH = 'src'
& .venv/Scripts/python.exe -m mypy tests/integration/test_desktop_independent.py
```

이 재확인은 소스·가짜 캡처·실제 로컬 저장소·offscreen Qt 경계의 실행 증거다. 위 하드웨어/OS sleep/전체 메모리/릴리스 NOT_RUN 제한은 유지한다. 실제 캡처, enumeration, 모델 다운로드, 외부 전송, 의존성 설치, 공용 설정 변경, Git 변경은 이 리뷰에서 수행하지 않았다.

## 2026-11-14 R11 최신 B21 독립 재배정

R00이 BR12 리뷰/시험의 쓰기 소유권을 R11로 이전했다. 새 작성자는 R12/B21이며 R11은 B21 소스를 수정하지 않는다. 위 BR12-01~08의 최초 발견·checkpoint·재확인을 이력으로 유지한다. R11 자신의 패키징과 B11 구현 승인이 아니다. AGENTS·온보딩·제품 계약·품질 체계·새 배정과 B21 runtime/diff·관련 시험을 읽고 ONBOARDING_READY를 보고했다.

| 최신 읽기 파일 (`src/recoryn/`) | SHA256 |
| --- | --- |
| app/ai.py | E3E981C00354ACF7BCC87770365DE5FEB2554D98484AA01A6EBAE3B3C55D124C |
| app/media.py | 25808336F6DAFA3E555B780A1B64ED08AD37C5F718A15A17A9BDA32C7FE7BA6D |
| app/desktop.py | D36ADBD4A635643E9BC88B5E595FE512B2084102AE902961C22DB24139C954F1 |
| ui/main.py | C68CB205D55E2374BBE96EA6388E865BE4138EF65CA44E77936AC35141275C4B |
| ui/ai_bridge.py | B0716E8C5DAD3A845097A5C0124C11CFE1B113A71943A29ECB6421CEA4DC1591 |
| ui/meter.py | 954D036F3DB983CA2438DCDF524EB82F8A34826A0FB2C14A622C0974EEF3FFB8 |

새 독립 대조군 8건과 이전 20건은 **28 PASS / 5.25s**였다. AI 준비를 Event로 붙잡은 상태에서도 recording control lane이 source stop ACK와 48 frame FINALIZED를 완료하고, 늦은 AI 예외가 원본/hash나 UI 비밀을 바꾸지 않았다. pause/error/stopped 뒤 미터가 50→0이 되고, control 작업 중 suspend/resume 알림은 capture ACK를 기다려 PAUSED가 되며 재개 알림만으로 source/epoch를 열지 않았다. 사용자 재개만 새 epoch다. 현재 세션 삭제의 source ACK 실패는 핸들·DB RECORDING을 보존하고 재시도 성공 뒤 recorder 참조를 해제하여 tick/control 갱신이 삭제 세션을 읽지 않았다.

실제 임시 청크와 독자 fake STT를 사용한 증분 반례에서는 두 epoch를 60초 모의 gap으로 분리하고 요청 offset `[0,60000]`, 중복 제출의 추가 provider call 0, draft/complete=False, checkpoint origin=1초, 원본 SHA 불변을 확인했다. 모델·음성·GPU·네트워크는 사용하지 않았다. power 시험은 UI 정책 호출이며 실제 OS 절전 또는 native notification 수신 시험이 아니다.

### BR12-09 · S2 · OPEN — DELETE_PENDING 반환을 UI에서 숨김

- 위치: `MainWindow.delete_selected`의 완료 callback `lambda value: self.refresh_sessions()`.
- 반례: FINALIZED 세션에 session-bound reader active=1을 영속 기록하고 논리 결과는 REMOTE_UNKNOWN으로 보존한다. UI 삭제 확인을 실행하면 Library는 원본을 보존하고 DELETE_PENDING을 반환한다. 정상 정책대로 세션은 일반 목록에서 숨지만 warning은 기본 녹음 동의 안내 그대로이며 삭제 대기/진행 상태를 전달하지 않는다. reader ACK·원본 bytes 보존은 정상이다.
- 독립 시험: `test_b21_delete_pending_reader_is_visible_as_pending_not_silent_disappearance`. 실제 **1 FAIL / 28 deselected / 0.70s**. 첫 삭제 후 source 참조는 해제되고 원본은 그대로 남으며 tick도 예외 없이 실행되지만 pending 안내 assertion이 실패했다. fixture 정리는 정확한 reader ACK 뒤 명시 Library 삭제를 실행한다.
- 영향/해결 조건: 삭제 요청의 수락과 물리 삭제 완료를 구분해 `state/deleted/reason`을 표시하고, 대기 중인 삭제의 명시적 재시도 또는 안전한 자동 후속 정리 경로를 제공한다. 일반 목록 숨김·원본 reader 보호를 완화해서 해결하지 않는다. 실제 삭제가 끝나기 전 완료로 표시하지 않는다.
- R12에 제품 수정을 요청했다. root의 Herdr 승인 UI가 blocked인 시점에는 대리 승인·입력을 하지 않고 저장된 리뷰와 R12 보고로 근거를 남겼다. R12/root 수정 뒤 R11이 원 반례와 새로운 상태 흐름을 재확인한다.

이번 실행도 고유 TEMP/cache-off, ResourceWarning 오류 처리를 사용했다. 기존 checkpoint를 현재 전체 통과로 재사용하지 않았으며 새로운 OPEN S2 1건 때문에 최신 B21을 최종 승인하지 않는다. 실제 장치·모델·접근성·대형 패키지와 G3/G4 제한은 유지한다.

## R12 수정 후 BR12-09 독립 재확인

수정자 R12, 재확인자 R11. R12가 `_delete_result`에서 state/deleted/reason을 분리하고 삭제 대기 상태·숨겨진 ID 추적·명시 재시도 버튼을 추가했다. 원 reader 보류 assertion을 유지한 채 반례를 강화했다. 첫 삭제 및 ACK 전 재시도는 원본 bytes와 reader active=1을 유지하고 대기 안내가 tick 후에도 보인다. 정확한 reader ACK 뒤 재시도 버튼을 누르면 원본 제거·완료 안내·버튼 비활성화가 확인되며 논리 REMOTE_UNKNOWN은 보존된다. 소스 보호나 일반 목록 숨김을 제거하지 않았다.

BR12-09: **RECHECKED / root CLOSED 후보**. 최신 BR12 독립 **29 PASS**. live UI/power 관련 시험까지 포함한 안정 snapshot 실행은 **43 PASS / 6.43s / 0 FAIL / 0 SKIP**였고 아래 여섯 runtime hash가 실행 전후 일치했다. 앞선 42개 실행 뒤 R12가 live UI에 자체 재시도 시험 1개를 추가했으며 두 수치를 합산하지 않는다. 독립 시험 Ruff check/format·mypy PASS다.

| 최종 snapshot (`src/recoryn/` 기준) | SHA256 |
| --- | --- |
| app/ai.py | E3E981C00354ACF7BCC87770365DE5FEB2554D98484AA01A6EBAE3B3C55D124C |
| app/media.py | 25808336F6DAFA3E555B780A1B64ED08AD37C5F718A15A17A9BDA32C7FE7BA6D |
| app/desktop.py | D36ADBD4A635643E9BC88B5E595FE512B2084102AE902961C22DB24139C954F1 |
| ui/main.py | 2E40C70110BB052F30E507D50308C0B926D278A55CD6A0E41026DB0138EBEAF2 |
| ui/ai_bridge.py | 3729DCFA48BE282BEDC1884C2CA4B17669EA8C29798F885DBF1431F347E4F809 |
| ui/meter.py | 954D036F3DB983CA2438DCDF524EB82F8A34826A0FB2C14A622C0974EEF3FFB8 |

독립 시험 SHA256: `4F175B4ED878BE0D3BB4279B4B989A0FD669173CD1A9164FB1DFC583CD9E3D77`.

ui/ai_bridge의 후속 차이는 GUI tick에서 managed Ollama 검증을 동기 실행하는 대신 model panel의 비동기 attestation 요청으로 넘기는 연결이다. 이 독립 실행은 daemon 없이 동작했고 helper/dispatch proof 자체 승인은 BR44/BR30의 별도 검토다. 이번 pending 삭제 UI 검증은 같은 앱 실행 중의 ACK/명시 재시도 흐름이며 재시작 후 삭제 대기 UI 복원·모든 파일 접근 실패 조합·실제 장치/모델/접근성·G3/G4를 승인하지 않는다.

현재 BR12-01~09 지정 반례의 OPEN S0/S1/S2는 **0건**, 전체 제품 통합·최종 릴리스 판단은 root가 수행한다. 문서 앞선 OPEN 기록은 발견 당시 이력이다. R11은 대상 코드·Git 인덱스·공용 계약을 수정하지 않았다.

## R00 최종 runtime 동결 snapshot 재확인

R00이 기존 `2E40...` 뒤의 최종 main `952457...`에서 BR12-09 원 reader/재시도 반례를 다시 실행하도록 요청했다. 변경된 삭제 결과 안내는 원본 제거 미완료와 결과 미확인을 구분하고, 일반 목록에서 숨긴 세션의 이전 content view를 정리한다. 해당 코드를 읽기 전용으로 대조했으며 runtime/test와 원 assertion은 수정하지 않았다.

| 동결 파일 | SHA256 |
| --- | --- |
| src/recoryn/ui/main.py | 952457B561732CB13B12002390944EE4BCE3A50EE63B400B4040099666DE11CD |
| src/recoryn/ui/ai_bridge.py | 3729DCFA48BE282BEDC1884C2CA4B17669EA8C29798F885DBF1431F347E4F809 |
| src/recoryn/ui/models.py | 67C06B2EB42500D3BF6FFDA1F7F2BB7B78CA5F2AC5CA32C5766BB9ED6BA5B384 |
| tests/integration/test_desktop_independent.py | 4F175B4ED878BE0D3BB4279B4B989A0FD669173CD1A9164FB1DFC583CD9E3D77 |

Windows / Python3.13.1 / Qt offscreen, 고유 TEMP/cache-off/ResourceWarning 오류 처리로 원 `test_b21_delete_pending_reader_is_visible_as_pending_not_silent_disappearance`만 실행해 **1 PASS / 28 deselected / 0.57s**, exit 0을 확인했다. 위 네 파일의 실행 전후 hash가 모두 같았다. reader active 동안 원본/삭제 대기 안내·재시도를 보존하고 정확한 ACK 뒤 원본 제거·완료 안내·버튼 비활성화, REMOTE_UNKNOWN 이력 유지 assertion을 그대로 통과했다.

```powershell
$br12FrozenTemp = Join-Path $env:TEMP ('recoryn-br12-frozen-' + [guid]::NewGuid().ToString('N'))
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:QT_QPA_PLATFORM = 'offscreen'
.venv/Scripts/python.exe -m pytest tests/integration/test_desktop_independent.py -q -k test_b21_delete_pending_reader_is_visible_as_pending_not_silent_disappearance -p no:cacheprovider --basetemp $br12FrozenTemp -W error::ResourceWarning --tb=short
```

실제 basetemp: `C:\Users\gangd\AppData\Local\Temp\recoryn-br12-frozen-a3374a73a54b43aea3b71a10fe832fba`. **BR12-09 RECHECKED 유지 / root CLOSED 후보**, 새 발견 없음. 이전 43 PASS는 앞선 snapshot의 이력이며 이번 최종 main 전체 회귀로 재사용하지 않는다. 이번 쓰기는 이 리뷰 후단뿐이고 runtime/test 동결을 유지한다. 최종 candidate 재생성·전체 QA·실장비/실모델·G3/G4는 root의 별도 통합 게이트다.
