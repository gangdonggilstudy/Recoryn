# D02 — Windows 오디오 캡처·저장·복구 계약 검토

상태: **REVIEW_READY — 통합 채택 전 설계 제안**. 작성일: 2026-11-14. 역할은 Windows 오디오 전문가 관점의 검토이며 실제 자격·인증을 뜻하지 않는다. 구현, 의존성 설치, 장치 시험, 벤치마크를 수행하지 않았다. 저장소에는 VoiceLocal 소스가 없으므로 원본 구현 분석·호환성·마이그레이션 완료를 주장하지 않는다.

입력: [설계 입력](../design-input-v1.md), [협업 규칙](../collaboration/workflow.md), [배정표](../collaboration/assignments.md). 온보딩 시 통합 설계와 검증 계획은 미작성 상태였다. 이 문서의 계약·기본값·수치는 D00의 채택 및 구현 후 검증이 필요한 **D02 제안**이다. ‘해야 한다’는 표현은 제안 계약의 요구사항을 뜻한다.

## 1. 사용자 원칙과 제안의 경계

| 구분 | 근거와 준수 내용 |
| --- | --- |
| 사용자 원칙 R01 | STT·LLM 실패와 독립하여 녹음한다. 모델·네트워크·UI가 저장 큐의 소비자가 되어서는 안 된다. 저장 장애로 인한 녹음 중단은 별도 실패로 명시한다. |
| 사용자 원칙 R02 | 오디오·계측 정보의 외부 전송을 기본 차단한다. 모델 다운로드와 외부 전사는 별도 명시적 동작이다. |
| 사용자 원칙 R03 | 마이크와 시스템 트랙을 각각 보존한다. 리샘플링·믹스·정렬·AEC·잡음 제거는 버전이 있는 파생물이다. |
| 사용자 원칙 R04 | 재개·취소·부분 결과를 지원한다. 녹음 재개가 이미 누락된 소리의 복원을 뜻하지 않는다. |
| 사용자 제시 설계 방향 | 기본 rate/channels → 타임스탬프 PCM → bounded queue → 청크·manifest, 포화 가시화, 장치·디스크·절전·비정상 종료 처리. WAV 44바이트 고정 오프셋 snapshot은 사용하지 않는다. |
| D02 제안 | 공유 모드 WASAPI를 기준 구현 후보로 두고 capability 실험으로 최종 선택한다. 프레임 레코드 청크, drop-newest 포화 정책, 시계 epoch, manifest 우선 복구, 아래 수락 기준을 제안한다. |

## 2. native rate/channels 및 트랙 계약

여기서 **native**는 선택한 엔드포인트의 공유 모드에서 OS가 제공하는 캡처 포맷이다. 물리 ADC의 원신호, OS 효과 적용 전 데이터, 다른 앱의 원래 샘플과 bit-exact 동일하다는 뜻은 아니다. `GetMixFormat`은 공유 오디오 엔진의 포맷이며 하드웨어 포맷과 다를 수 있다. 따라서 ‘원본’은 **Recoryn이 전달받은 샘플 의미와 포맷을 변환 없이 보존한 것**으로 정의한다. [Microsoft GetMixFormat](https://learn.microsoft.com/en-us/windows/win32/api/audioclient/nf-audioclient-iaudioclient-getmixformat)

1. 마이크는 capture endpoint, 시스템은 사용자가 고른 render endpoint의 loopback을 별도로 연다. WASAPI loopback은 공유 모드에서 동작한다. 시스템 전체가 아니라 **선택한 출력 엔드포인트의 믹스**를 녹음한다는 점을 UI에 표시한다. 다른 출력 장치·보호 콘텐츠까지 캡처한다고 보장하지 않는다. [Microsoft Loopback Recording](https://learn.microsoft.com/en-us/windows/win32/coreaudio/loopback-recording)
2. 시작 전에 각 트랙에 `endpoint_id`, 역할, 선택 정책(`PINNED` 기본 / 사용자 허용 `FOLLOW_DEFAULT`), OS·드라이버·백엔드 버전, 실제 적용 포맷, 엔진 버퍼·서비스 주기를 기록한다. 백엔드 요청값과 실제값을 구분한다. 장치 이름만 식별자로 쓰지 않는다.
3. 포맷은 `rate_hz:uint32`, `channels:uint16`, `sample_kind:SIGNED_PCM|IEEE_FLOAT`, `container_bits`, `valid_bits`, `block_align_bytes`, `channel_mask`, `channel_order`, `interleaved`, `endianness`를 포함한다. `channel_mask` 부재는 `unknown`으로 보존하며 stereo나 채널 순서를 추정하지 않는다. PCM 프레임은 모든 채널의 같은 시점 샘플 묶음이다.
4. 트랙별 포맷은 독립적이다. 예: mic 44,100 Hz/mono와 loopback 48,000 Hz/stereo를 그대로 저장한다. 원본 경로에 강제 16 kHz·mono, gain, float→int 변환, 믹스, VAD 생략을 넣지 않는다. 백엔드가 내부 변환을 강제하면 그 변환을 공개하고 native 계약 충족 여부를 별도 판정한다.
5. 하나의 `stream_epoch_id`에서는 endpoint·포맷·device clock 해석이 불변이다. 장치 변경, 포맷 변경, 재초기화, pause 후 재개 시 새 epoch와 새 청크를 만든다. 한 청크 안에 서로 다른 포맷을 넣지 않는다.
6. 백엔드 포인터 수명 안에서 앱 소유 버퍼로 복사하고 엔드포인트 버퍼를 즉시 반환한다. 해당 API의 호출 스레드·해제 순서를 지킨다. 공유 포인터를 UI나 Python 작업에 넘겨 수명을 연장하지 않는다. [Microsoft Capturing a Stream](https://learn.microsoft.com/en-us/windows/win32/coreaudio/capturing-a-stream)
7. OS가 `SILENT`라고 명시한 패킷은 해당 frame_count의 0 샘플로 저장하고 플래그를 남긴다. 데이터 미도착은 SILENT와 다르다. loopback의 idle·백엔드 정지·장치 오류가 구별되지 않으면 `NO_PACKETS_UNKNOWN`으로 표시한다. 파생 재생의 무음 채움에는 반드시 근거·구간 표시를 붙인다.
8. 원본 모니터링 출력을 기본으로 만들지 않는다. 마이크가 스피커 소리를 다시 담는 음향 에코 및 두 트랙의 중복 음성은 가능한 입력 특성이다. AEC·중복 억제를 적용하려면 파생 작업으로 수행하고 원본 트랙을 교체하지 않는다.

## 3. PCM 블록, sequence, 시계 도메인

### 3.1 블록 스키마

| 필드 | 계약 |
| --- | --- |
| `schema_version`, `session_id`, `track_id`, `run_id` | 스키마·세션·트랙·실행 식별자. 재실행 시 run_id를 바꾼다. |
| `stream_epoch_id`, `format_id`, `clock_domain_id` | 포맷/장치 및 시계 해석 범위. 다른 epoch의 device position을 직접 비교하지 않는다. |
| `sequence:uint64` | 트랙 내 관측한 비어 있지 않은 패킷마다 증가한다. 큐에 넣지 못한 패킷도 번호를 소비한다. 재시작은 기존 저장 최대값 뒤에 예약한 새 범위로 시작하고 미확정 꼬리는 unknown으로 표시한다. 범위 예약값은 캡처 시작 전 manifest에 기록한다. |
| `frame_count:uint32`, `observed_frame_start:uint64` | 해당 epoch에서 앱이 받은 프레임의 누적 좌표. queue drop도 누적하고, 앱이 받지 못한 하드웨어 누락 프레임을 여기에 추정 삽입하지 않는다. |
| `device_frame_start:uint64` (nullable) | 첫 프레임의 백엔드 장치 위치. 지원 여부·유효성을 함께 기록한다. 관측 누적 프레임과 별도 좌표다. |
| `device_qpc_100ns:uint64` (nullable) | WASAPI가 제공한 첫 프레임의 QPC 연계 시각. **100 ns 단위**이고 raw QPC tick이 아니다. |
| `arrival_qpc_ticks:int64`, `qpc_frequency_hz:uint64` | 앱이 패킷을 받은 시점과 raw tick 변환 기준. 캡처 시각으로 위장하지 않는다. |
| `timestamp_quality` | `DEVICE_CORRELATED`, `ARRIVAL_ONLY`, `INVALID`; 플래그와 추정 불확실성을 보존한다. |
| `backend_flags`, `payload` | silent/discontinuity/timestamp error 등의 원본 플래그와 immutable PCM. 일반 패킷은 `len(payload)=frame_count*block_align_bytes`. |

`GetBuffer`의 device position은 프레임 단위이며 QPC position은 100 ns로 변환된 값이다. `TIMESTAMP_ERROR`이면 시각 상관관계를 신뢰하지 않는다. `DATA_DISCONTINUITY`는 단절 증거이며 정확한 유실 프레임 수를 자동으로 뜻하지 않는다. [Microsoft GetBuffer](https://learn.microsoft.com/en-us/windows/win32/api/audioclient/nf-audioclient-iaudiocaptureclient-getbuffer), [버퍼 플래그](https://learn.microsoft.com/en-us/windows/win32/api/audioclient/ne-audioclient-_audclnt_bufferflags)

큰 엔드포인트 패킷을 저장 레코드 한도로 나눌 때 `sequence`는 그대로 두고 `fragment_index`, `fragment_count`, `packet_frame_offset`을 추가한다. 중복 키는 `(track_id, sequence, fragment_index)`다. 일부 fragment만 보존되면 나머지는 정확한 프레임 범위의 gap이다. 패킷이 가변 길이일 수 있으므로 sequence 차이에 고정 블록 크기를 곱해서 유실 프레임을 계산하지 않는다.

sequence 예약은 예를 들어 트랙별 `2^32`개 번호 단위의 high-water 범위를 미리 영속화하고, 소진 전 제어 경로에서 다음 범위를 예약하는 방식이다. 예약되지 않은 번호를 발급하지 않는다. 재실행 후 사용하지 않은 이전 예약 번호는 `UNUSED_RESERVATION`이며 실제 유실 패킷으로 집계하지 않는다. 마지막 영속 관측점 이후에 무엇을 받았는지 모른다는 사실만 crash gap에 기록한다.

### 3.2 시간 좌표

- **Device clock**: epoch 내 device frame 좌표다. mic와 loopback은 같은 rate라도 별도 시계로 취급한다.
- **Monotonic/QPC**: 같은 유효 clock domain의 간격·순서·정렬 기준이다. raw tick은 `delta_ticks/frequency`로, WASAPI QPC 값은 `delta_100ns/10^7`로 초 단위에 맞춘다. 다른 런타임의 monotonic API와 원점·단위가 같다고 가정하지 않는다. QPC는 UTC와 동기화된 시계가 아니다. [Microsoft 고해상도 타임스탬프](https://learn.microsoft.com/en-us/windows/win32/sysinfo/acquiring-high-resolution-time-stamps)
- **Wall clock/UTC**: 파일 식별·감사·사람에게 보여 줄 시작 시각이다. `utc, qpc_before, qpc_after` anchor와 표본 폭을 저장한다. 시계 변경·NTP·시간대 변경으로 원본 타임라인을 재배열하지 않는다. UTC와 timezone을 분리한다.
- **Session timeline**: 0에서 시작하는 정수 ns 기반의 논리 좌표다. pause와 장치 부재도 구간으로 남긴다. `session_elapsed`, `captured_duration`, `user_paused_duration`을 별도로 제공한다. 프레임 시간 계산은 정수/유리수로 하고 매 블록 반올림 누적을 피한다.
- 프로세스 재시작·재부팅 후 새 `clock_domain_id`와 `timeline_segment_id`를 연다. 기존 QPC 절대값과 직접 빼지 않는다. 이어지는 논리 좌표에 복구 gap을 붙이고, 중단 길이는 신뢰할 수 있는 anchor가 없으면 `duration_unknown`으로 남긴다. wall clock으로 추정한 길이는 `WALL_ESTIMATE`와 불확실성을 붙인다.

### 3.3 드리프트와 gap mapping

유효한 표본 쌍 `(device_frame_i, qpc_seconds_i)`에 대해 epoch/연속 구간별 `T(n)=a+b*n`을 적합한다. 초기 10초는 nominal `b=1/rate`와 낮은 신뢰도를 사용하고, 이후 60초 이동 창에서 outlier를 제외한 회귀를 5초마다 갱신하는 것을 제안한다. `rate_effective=1/b`, `ppm=(rate_effective/rate_nominal-1)*10^6`의 부호를 고정한다. 구간별 계수·창·잔차 p95·표본 수·버전·신뢰도를 파생 alignment artifact에 저장한다.

- timestamp error·단절·역행·재연결·절전·pause를 가로질러 하나의 회귀를 만들지 않는다. device position이 없으면 arrival 기반 정렬만 허용하며 정확도 저하를 표시한다. 정확한 동기화가 필수인 제품 등급에서는 capability 실패로 판정한다.
- 회귀 잔차 p95가 5 ms를 넘거나 추정 드리프트 절댓값이 1,000 ppm을 넘으면 우선 `CLOCK_UNCERTAIN`으로 전환한다. 10초 이상 지속되면 새 연속 구간으로 분리한다. 정상 장치 범위라는 주장이 아니라 이상 탐지의 초기값이다.
- 공통 QPC에 매핑하더라도 물리 ADC·USB·Bluetooth·음향 지연을 제거했다고 보지 않는다. 허가된 공통 펄스/루프백 시험으로 별도의 고정 offset과 잔여 오차를 측정한다. 음성 cross-correlation은 보조 근거이며 에코를 동기화 기준으로 단정하지 않는다.
- 원본 frame/payload는 수정하지 않는다. 정렬 후 파생 리샘플링은 segment별로 수행하며 `source_chunk, source_frame_range → session_time_range → derived_frame_range`와 적용 계수·알고리즘 버전을 남긴다. gap을 넘어 보간하지 않는다.

Gap 레코드는 `gap_id`, 트랙·epoch·clock domain, 이유, 앞뒤 sequence, device/observed frame 범위(알 때만), session 시간 경계 및 경계 신뢰도, `frame_count_exact|null`, `duration_estimate|null`, `evidence`, `detected_at`, `mapping_version`을 갖는다. 이유는 `QUEUE_DROP`, `BACKEND_DISCONTINUITY`, `DEVICE_UNAVAILABLE`, `USER_PAUSE`, `SUSPEND`, `STORAGE_FAILURE`, `CRASH_TAIL_UNKNOWN`, `NO_PACKETS_UNKNOWN`을 구분한다.

예: 48 kHz 패킷 두 개가 각각 480 frames이고 큐에서 탈락했다면 `QUEUE_DROP=960 frames`는 정확하다. 이후 device 위치도 960 frames만큼 뛰었다는 이유로 다시 960을 더하지 않는다. 같은 device/시간 범위의 증거를 한 gap에 병합한다. 장치 분리 3초를 발견했어도 장치 frame 연속성이 없으면 ‘144,000 frames 유실’로 확정하지 않는다. raw frame 좌표, 추정 경과 시간, 파생 silence 좌표를 분리한다.

## 4. bounded queue와 nonblocking 포화 계약

캡처 critical path는 패킷 메타데이터 확보 → 사전 할당 버퍼 복사/zero-fill → 제한된 enqueue 시도 → 엔드포인트 버퍼 반환뿐이다. 추론, 리샘플링, checksum 전체 계산, 파일·DB·manifest I/O, 로그 포매팅, UI signal의 동기 대기, 동적 메모리 확장을 호출하지 않는다. Python queue의 `put_nowait`만으로 실시간 무대기 특성이 입증되는 것은 아니다. GIL·내부 lock·할당을 포함하여 계측하고 필요시 native SPSC ring/별도 캡처 경계를 선택한다.

| 항목 | D02 제안 기본값·동작 |
| --- | --- |
| 용량 | 트랙별 PCM 2초 + 가장 큰 엔진 패킷 여유분. byte cap과 slot cap을 모두 둔다. 2초는 `rate*block_align*2`로 계산하고 예상 최대 동시 트랙을 시작 전에 예약한다. |
| 메모리 상한 | 캡처 큐+버퍼 pool 합계 64 MiB를 초기 상한으로 제안한다. 고 rate/다채널에서 필요한 용량이 넘으면 시작 전 지원 불가 또는 명시적 설정 변경을 알린다. 조용히 rate/channels를 낮추지 않는다. writer·UI·AI 메모리 예산은 별도다. |
| 소비 | 트랙별 writer 또는 공정한 round-robin writer를 사용하고 한 트랙의 장치 실패가 다른 트랙 큐를 막지 않게 한다. AI는 확정 청크를 읽거나 별도 손실 허용 tap을 쓴다. AI tap 포화는 원본 queue drop이 아니다. |
| 포화 | **drop-newest**: 넣지 못한 새 패킷/fragment만 버리고 이미 큐에 들어간 순서를 유지한다. 캡처는 기다리지 않고 device buffer를 반환한다. pool 고갈도 동일 정책이다. 무한 재시도·메모리 증가·AI 소비 대기를 금지한다. |
| 유실 증거 | 별도 사전 할당 상태에서 누적 dropped_frames/packets, 첫/마지막 sequence, pending gap을 갱신한다. 다음 성공 블록에 이전 누적값을 snapshot하여 writer가 차분을 영속화한다. stop 시에도 최종 snapshot을 전달한다. 상세 gap ring도 차면 정확한 누적 frame 수는 유지하고 상세 범위 신뢰도를 낮춘다. |
| 신뢰성 한계 | drop 상태가 디스크에 기록되기 전 crash하면 마지막 확정 관측점 이후 유실 수는 알 수 없다. 정확한 카운터를 발명하지 않고 `CRASH_TAIL_UNKNOWN`을 남긴다. 오류를 같은 포화 큐에만 넣지 않는다. |
| 경고 | queue ≥50% 1초 지속: warning. ≥80% 또는 drop 1회: critical. 10초 안정 후 현재 상태는 회복시킬 수 있지만 세션 ‘유실 발생’ 배지는 유지한다. |

각종 카운터는 폭·원자성·overflow를 명시하고 UI가 독립적으로 읽는다. capture 상태 publisher도 대기하지 않아야 한다. nonblocking은 enqueue 경로의 설계 요구이며 일반 Windows에서 hard real-time deadline을 보장한다는 뜻이 아니다.

## 5. 청크 파일과 게시 순서

**통합 충돌 주의:** 작성 중 재확인한 D00의 `architecture-v1.md` 초안은 PCM+descriptor bundle → DB → manifest snapshot 순서와 DB의 업무 상태 권위를 채택하고 있다. 아래 `.rcpcm` 및 manifest delta → DB 순서는 D02의 대안 제안이며 공통 계약을 변경한 것이 아니다. 차이와 동등성 확인 조건은 9절 O-A09에 남긴다. DB의 업무 상태·동의·편집·삭제 의도 권위에는 이 제안도 이견이 없다.

### 5.1 복구 가능한 원본 컨테이너 제안

단일 장시간 WAV 대신 **프레이밍된 PCM 청크 `*.rcpcm` v1**을 원본 후보로 제안한다. 독자 포맷 비용 때문에 통합 채택이 필요하며 아래 논리·프레이밍 계약을 기준으로 serializer/reader를 함께 명세해야 한다. WAV가 필요하면 확정 청크에서 파생 내보내기한다. 확정된 원본 바이트를 나중에 WAV 헤더 보정 목적으로 변경하지 않는다.

- 세션 아래 `tracks/<track_id>/<stream_epoch_id>/<chunk_id>.part`를 배타적으로 생성한다. chunk_id는 재사용하지 않는다. 임시·확정 파일은 같은 로컬 볼륨/디렉터리를 사용한다. v1 지원 기준은 로컬 NTFS 제안이며 네트워크·동기화 폴더·이동식 미디어의 내구성은 별도 인증 전 보장하지 않는다.
- 청크는 **최대 5초의 수신 PCM 또는 총 파일 크기 64 MiB 중 먼저 도달하는 경계**에서 닫는다. idle/벽시계 5초에도 열린 비어 있지 않은 청크를 닫아 장기간 미확정 상태를 방지한다. stop·pause·epoch 종료 시 즉시 경계를 만든다. footer 공간을 미리 계산하여 크기 상한에 포함한다.
- 프리앰블: 8 ASCII bytes `RCPCM001`, `header_len:uint32le`, UTF-8 JSON header, `crc32:uint32le`. header는 세션·트랙·epoch·chunk·포맷·시계·sequence 예약 범위를 포함하며 최대 64 KiB다. CRC는 magic부터 header 끝까지 계산한다. 알 수 없는 version은 격리한다.
- 레코드: `metadata_len:uint32le`, `pcm_len:uint32le`, UTF-8 JSON metadata, PCM bytes, `crc32:uint32le`. CRC는 두 길이 필드부터 PCM 끝까지 계산하는 CRC-32/ISO-HDLC다. metadata ≤64 KiB, PCM ≤1 MiB로 제한하고 큰 패킷은 위 fragment 규칙으로 나눈다. JSON 중복 key·비정상 숫자·잘못된 UTF-8을 거부한다. 정수는 정수형으로만 허용하고 크기 상한 확인 전에 메모리를 할당하지 않는다.
- data metadata는 3.1의 필드 및 fragment 정보를 갖는다. silent 패킷도 zero-fill된 실제 PCM bytes와 정확한 길이를 저장한다. gap/event는 `kind`가 다른 PCM 길이 0 레코드다. 모든 레코드에 CRC를 적용한다.
- 마지막 footer 레코드는 `kind=footer`, PCM 길이 0이고 이전 전체 바이트의 SHA-256, data record 수·총 frame 수·sequence 범위·종료 이유를 갖는다. 완성 파일의 SHA-256은 footer까지 포함하여 별도로 manifest에 둔다. footer 자체 CRC도 검사한다. checksum과 schema 검증은 서로 대체하지 않는다.
- 복구 시 header와 순서대로 확인된 **연속 유효 레코드 prefix**만 후보로 인정한다. 첫 길이 오류·CRC 오류·미완성 레코드에서 멈추고 임의의 magic 검색으로 뒤쪽 바이트를 이어 붙이지 않는다. prefix를 새 recovered 청크로 복사하고 새 footer를 만든다. `.part` 증거는 정책에 따라 격리 보존하며 원본을 제자리 truncate하지 않는다.

### 5.2 정상 게시 프로토콜

캡처와 별개인 writer/commit coordinator가 아래를 수행한다. 단일 세션의 manifest 작성자는 한 명이고, 실행 간 소유권 충돌을 감지하면 새 녹음을 거부한다. 파일과 SQLite를 아우르는 원자적 transaction이 있다고 가정하지 않는다.

1. 시작 시 세션·트랙·epoch 메타데이터, 포맷, 시계 anchor, sequence 예약 범위를 manifest에 먼저 게시한다. 지속 가능한 저장소가 준비되지 않으면 REC를 시작하지 않는다. 기존 crash 세션을 덮어 열지 않는다.
2. `.part`에 header와 레코드를 쓴다. short write는 남은 바이트를 제한된 정책으로 처리하고 실패 시 해당 부분 이후를 확정하지 않는다. file offset·record 수·checksum 계산은 writer에서 한다.
3. footer를 기록한다. 언어 런타임 buffer flush 뒤 OS `FlushFileBuffers`에 해당하는 검증된 호출을 수행하고 반환값을 검사한 뒤 파일을 닫는다. flush 실패는 확정 성공이 아니다. [Microsoft FlushFileBuffers](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-flushfilebuffers)
4. 닫힌 파일을 다시 열어 길이·포맷·frame 정합성·CRC·SHA-256을 검증한다. 검증 실패는 quarantine 대상이다. 성공한 `.part`를 같은 볼륨의 고유 `.rcpcm` 이름으로 게시한다. 목적지 존재 시 덮어쓰지 않고 동일 identity/hash인지 확인한다. Windows rename/replace primitive와 공유 핸들 실패를 실제 빌드에서 검증한다. 다른 볼륨의 copy+delete는 이 단계로 허용하지 않는다. [Microsoft MoveFileExW](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-movefileexw)
5. `manifest/<generation>.json.part`에 새 **불변 commit delta**를 쓴다. 내용은 schema/session/세대 번호, 이전 generation/hash, 이번 chunks·gaps·epochs·clock segments, 종료 상태, 생성 시각이다. chunk entry는 상대 경로·크기·전체 SHA-256·frame 수·sequence/fragment 범위·포맷·recovery provenance를 포함한다. 동일한 flush→close→검증→고유 확정 이름 게시 절차를 쓴다. generation의 전체 파일 hash로 다음 delta가 연결된다. head 포인터는 cache일 뿐이다.
6. 확정 manifest generation을 기준으로 SQLite transaction에서 오디오 인덱스·세션 저장 상태·generation/hash를 idempotent upsert한다. unique chunk_id와 gap_id를 둔다. 오디오 인덱스 transaction 실패 시 미디어를 삭제하지 않고 `INDEX_PENDING`으로 재시도한다. 인덱스 반영 backlog는 디스크의 확정 delta와 단일 cursor로 보관하고, RAM의 미반영 목록을 무한 증식시키지 않는다. 디스크 임계 정책은 그대로 적용한다. 캡처 버퍼를 DB lock 동안 잡고 있지 않는다. 제어 상태·삭제 의도 등 필수 상태의 영속화까지 불가능하면 D00의 안전 종료 정책을 따르며 인덱스 복구를 근거로 녹음을 강행하지 않는다. SQLite의 transaction은 외부 PCM 파일까지 포함하지 않는다. 실제 journal/synchronous 설정과 전원 장애 보장은 D01/D04의 검증 대상이다. [SQLite Atomic Commit](https://sqlite.org/atomiccommit.html)
7. UI에는 `received → queued → written → verified_file → manifest_published → indexed` watermark를 따로 갱신한다. 최종 저장 완료는 모든 보존 청크 검증·manifest 게시·인덱스 반영이 끝난 후다. 누락/유실이 있으면 완료 여부와 독립적으로 `HAS_GAPS`를 유지한다.

manifest가 길어지면 120 commit마다 검증된 checkpoint를 추가하는 방안을 제안한다. checkpoint 검증 및 복구 시험 전에는 이전 delta를 제거하지 않는다. epoch·sequence 예약 commit은 캡처 시작 전에, 청크 commit은 준비되는 대로 진행하여 서로 다른 트랙을 한 청크 경계에 강제로 맞추지 않는다.

### 5.3 crash reconciliation

복구는 자동 녹음 재시작과 분리한다. 실행 소유권을 획득하고 삭제 tombstone/보존 정책을 확인한 다음 읽기 검사한다. 사용자가 삭제한 세션을 orphan 검색으로 부활시키지 않는 계약은 D04와 통합해야 한다.

| 발견 상태 | 복구 처리 |
| --- | --- |
| `.part` header/첫 레코드부터 손상 | 격리, 손상 근거 표시. 복원 성공으로 집계하지 않는다. |
| `.part`에 유효 레코드 prefix 존재 | 새 recovered 청크로 복사·검증·게시하고 source hash/보존 frame 범위/버린 꼬리 크기를 기록한다. 버린 꼬리의 frame 수를 알 수 없으면 unknown gap이다. |
| 완전한 footer를 가진 `.part` | 전체 검증 후 동일 identity로 정상 게시를 재시도한다. 재실행해도 청크·frame이 중복되지 않아야 한다. |
| `.rcpcm` 존재, manifest에 없음 | 자체 metadata/hash 검증 후 orphan 후보로 등록한다. 세션·epoch·sequence 충돌이 없을 때만 recovery commit에 편입한다. 다르면 격리하고 자동 overwrite하지 않는다. |
| 확정 manifest, DB 반영 없음 | manifest를 재생해 오디오 인덱스를 갱신한다. 전사 편집·다른 작업 데이터까지 삭제/재생성하지 않는다. |
| DB만 청크를 가리킴 | DB를 복구 근거로 파일 존재를 가정하지 않는다. manifest와 대조하고 미확인 인덱스를 비활성화한다. |
| manifest가 청크를 참조하지만 파일 부재/hash 불일치 | `MISSING/CORRUPT`와 재생 불가 구간을 기록하고 정상 완료로 표시하지 않는다. 다른 파일을 같은 이름으로 대입하지 않는다. |
| manifest delta 꼬리 미완성·체인 단절 | 마지막 연결되고 유효한 generation까지 사용한다. 후속 delta·청크는 orphan 검사 대상으로 남긴다. 같은 이전 hash에서 분기하면 자동 선택하지 않고 충돌을 보고한다. |
| 실행 중 상태만 남음 | 세션은 `INTERRUPTED/RECOVERY_REQUIRED`; RAM/queue 및 마지막 관측 이후는 `CRASH_TAIL_UNKNOWN`. 작업 재개는 새 run/clock/epoch로 수행한다. |

복구는 청크 identity+원본 hash+검증 범위로 idempotency를 판정한다. 두 번 실행해도 목록·재생 길이·gap 개수는 같아야 한다. 디스크 부족으로 복구 사본을 만들 수 없으면 읽기 전용 inventory와 필요한 공간을 보여주고 원본을 보존한다. gap/event가 먼저 기록되지 못했으면 근거 부족을 그대로 표시한다.

### 5.4 checksum·지속성의 한계

CRC는 잘린/손상된 레코드를 찾기 위한 것이고 SHA-256은 파일 바이트 변화 탐지다. 둘 다 실제 음성이 누락 없이 녹음됐다는 증명, 원본 화자의 진위 확인, 악의적 변조 방지 서명, 전원 장애 내구성 보증이 아니다. 같은 위치에 저장한 파일과 hash가 함께 변조되는 경우도 방어하지 않는다.

`write 성공`, 런타임 `flush 성공`, OS flush 요청 성공, 이름 게시, manifest 게시, SQLite commit을 다른 사건으로 기록한다. rename 성공을 저장매체의 전원 차단 내구성과 동일시하지 않는다. 파일 시스템·컨트롤러·디스크 캐시가 flush를 어떻게 이행하는지는 별도 시험 대상이다. 청크별 flush는 캡처 경로 밖에서 수행하고 지연을 계측한다. 파일·manifest·DB 전체의 원자적 내구성은 reconciliation으로 다루며 ‘한 번에 모두 저장’이라고 표시하지 않는다.

명시적 정상 부하에서 프로세스 강제 종료 시 **확정 watermark 이전 데이터 손실 0**, 미확정 꼬리 상한 목표 **8초**를 제안한다. 이는 청크 5초+queue 2초+게시 여유 1초의 예산이며 디스크 stall·장치 단절·전원 차단에는 적용하지 않는다. 지연이 예산을 넘으면 UI가 실제 미확정 시간과 경고를 표시해야 한다. 전원 차단 손실 범위는 하드웨어 시험 전 수치 보장을 하지 않는다.

## 6. 장애·사용자 동작별 처리

트랙 상태(`OPENING/RUNNING/PAUSED/RECONNECTING/UNAVAILABLE/STOPPED`)와 저장 상태(`OK/LAGGING/FAILED/FINALIZING/RECOVERY_REQUIRED`), AI 작업 상태를 독립적으로 보유한다. 아래 상태 이름은 D01 통합 시 매핑할 제안이다.

| 사건 | 필수 처리 및 사용자에게 보일 결과 |
| --- | --- |
| 장치 disconnect·오디오 서비스 재시작·포맷 변경 | 해당 트랙을 `RECONNECTING`, 열린 청크를 가능한 범위에서 닫고 gap을 연다. 다른 트랙은 계속한다. 제어 worker에서 재열거·인터페이스 해제·재초기화하며 capture thread에서 장치 탐색하지 않는다. 같은 장치 복구도 새 epoch다. |
| 장치 재연결 정책 | `PINNED`는 같은 endpoint만 재시도하고 다른 마이크로 자동 전환하지 않는다. `FOLLOW_DEFAULT`는 녹음 전 명시적 선택 시만 허용하고 전환 시 장치명·epoch·gap을 표시한다. 0.5/1/2/5초 backoff, 이후 5초 간격을 제안한다. cancel/stop으로 재시도를 즉시 취소한다. 장치 ID가 달라졌으면 사용자 재선택이 필요하다. |
| 접근 거부·OS 마이크 권한·장치 busy | OS/백엔드 오류를 보존하고 해당 트랙 실패를 명확히 표시한다. 권한을 대신 바꾸지 않는다. 시작 시 필수 트랙 하나라도 열리지 않으면 전체 REC 성공으로 보이지 않게 한다. 사용자가 승인한 단일 트랙 모드로만 계속한다. 실행 중 한 트랙 실패는 나머지 저장을 유지한다. |
| loopback 패킷 미도착·출력 변경 | stream heartbeat와 packet age를 분리한다. idle 가능 상태를 ‘무음 수신’ 또는 ‘정상 저장’으로 단정하지 않는다. 재생 중인 시험 신호가 있는데 누락되면 backend/device 오류로 처리한다. 기본 출력 변경도 선택 정책을 따른다. |
| 디스크 여유 부족 | 1초 간격으로 전체 원본 byte rate `R=Σ(rate*block_align)` 기준 여유 시간을 계산한다. warning=`max(1 GiB, R*600s)`, controlled stop 임계=`max(256 MiB, R*60s)`를 제안한다. 사전 계산과 무관하게 모든 write 오류를 처리한다. |
| ENOSPC·접근권한·I/O 오류 | shared volume 장애면 저장 불가한 모든 트랙을 정지 요청하고 `STORAGE_FAILURE`로 표시한다. RAM에 계속 쌓으며 REC를 표시하지 않는다. 남은 공간으로 가능한 청크/manifest 확정을 시도하되 기존 확정 파일을 지우지 않는다. 최종 이벤트 기록 자체가 실패하면 다음 실행에서 unknown tail로 복구한다. |
| 절전 진입 | OS 사전 통지를 받으면 캡처 정지·청크 확정을 시도하되 통지 도착·완료를 보장하지 않는다. `SUSPEND` 구간을 연다. 자동 절전 방지 요청 사용 여부는 별도 제품 결정이며 강제 절전·배터리 소진을 막는다고 보장하지 않는다. |
| 복귀 | 장치·포맷·시계를 재검사하고 새 epoch/연속 구간을 만든다. 같은 부팅 도메인의 검증된 QPC anchor로 gap 길이를 산정하거나 불확실성을 표시한다. 입력 범위가 같은 장치일 때만 복귀 재개를 제안하며, 자동 재개 정책은 통합 결정이 필요하다. 절전 중 소리를 복원하지 않는다. |
| 사용자 pause | 요청과 실제 capture cutoff를 별도 기록한다. 트랙별 cutoff 뒤의 새 입력은 저장/AI tap으로 보내지 않고 열린 청크·큐를 확정한다. pause 전 데이터가 큐에 남아 있으면 계속 저장될 수 있음을 상태에 반영한다. 모든 트랙 정지 확인 후 `PAUSED`를 표시한다. 재개 시 새 epoch, USER_PAUSE gap. |
| stop·cancel | 새 입력을 막고 마지막 accepted sequence를 고정한 뒤 queue drain→청크→manifest→DB 순으로 종료한다. AI 취소와 녹음 정지는 별도 명령이다. 10초 내 확정되지 않으면 ‘저장 중/저장 오류’를 표시하고 성공 종료로 바꾸지 않는다. 강제 종료는 복구 필요 상태로 남긴다. 취소가 원본 삭제를 뜻하지 않는다. |
| 장시간·카운터 overflow | frame/sequence/byte/timeline은 충분한 폭의 정수로 계산하며 32-bit byte/frame 누계를 쓰지 않는다. 다음 카운터 범위·파일 한계를 넘기 전에 새 epoch/청크 또는 명시적 정지를 선택한다. manifest 처리·메모리가 세션 길이에 선형으로 RAM에 누적되지 않게 한다. |
| WAV 용량·헤더 문제 | RIFF는 4-byte size 필드와 복수 chunk 구조를 사용하므로 단일 WAV가 무제한이거나 헤더가 항상 44 bytes라고 가정하지 않는다. 파생 WAV는 RIFF 한계 전에 분할하고 재생 목록/시간 맵을 제공한다. RF64/W64는 실제 라이브러리·내보내기 소비자 검증 후 선택 지원한다. [Microsoft RIFF](https://learn.microsoft.com/en-us/windows/win32/xaudio2/resource-interchange-file-format--riff-) |

장치 무효화 후 같은 endpoint를 다시 여는 경우와 기본 endpoint를 다시 선택하는 경우는 다른 복구 정책이다. 실제 원인은 오류 코드와 장치/세션 통지로 구분하되 통지 순서를 가정하지 않는다. [Microsoft Invalid-Device Recovery](https://learn.microsoft.com/en-us/windows/win32/coreaudio/recovering-from-an-invalid-device-error)

## 7. 실시간 UI 건강상태

UI의 REC 점멸만으로 건강을 판단하지 않는다. 상태 snapshot은 capture thread와 독립적으로 최소 5 Hz 갱신을 목표로 한다. UI가 느려져도 원본 경로는 계속 동작해야 한다.

- 트랙마다 endpoint/포맷/epoch, 신호 level·clip, packet age, backend heartbeat, 수신 frame 수, queue 점유율·초, 원본 drop frames, timestamp 품질, device reconnect 상태를 표시한다. level이 0이라는 사실과 입력이 끊겼다는 사실을 구분한다.
- 세션마다 마지막 verified/manifest/index watermark와 각 age, 미확정 오디오 시간, 디스크 잔여 용량·예상 분, 저장 처리량, 복구·유실 badge를 제공한다. AI 대기·초안 지연은 별도 표시한다.
- `정상 수신·저장`, `저장 지연`, `일부 트랙 끊김`, `입력 상태 확인 필요`, `녹음 중단`, `저장 확정 중`, `복구 필요`를 텍스트와 아이콘으로 구분하고 색상만 사용하지 않는다. 오류 발견 후 1초 내 UI 반영을 수락 목표로 한다.
- 마지막 manifest age >10초이고 그동안 PCM을 수신했다면 저장 지연 경고를 띄운다. 정상적인 idle loopback에는 이 조건을 그대로 적용하지 않는다. packet age >1초는 `NO_PACKETS` 단서이며 이것만으로 장치 실패로 확정하지 않는다.
- gap 목록은 구간·이유·정확한 frame 수/추정 여부·복구 결과를 보여준다. 일시 오류가 회복돼도 유실 배지는 세션 이력에 남긴다. 사용자 pause는 의도한 제외 구간이며 장애 유실과 별도로 표시한다.

## 8. 백엔드 선정 실험과 정량 게이트

### 8.1 후보와 실험 순서

라이브러리 이름·문서만으로 required capability를 충족한다고 판정하지 않는다. 아래는 후보 목록이며 **Recoryn에서의 기능·API 노출·호환성은 모두 미검증**이다. 정확한 버전/commit, Python/아키텍처, 빌드된 바이너리를 고정하고 upstream 문서와 실험 결과를 함께 보관한다.

| 후보 | 확인할 사항 |
| --- | --- |
| 직접 WASAPI 기반의 작은 native adapter | GetMixFormat/loopback/GetBuffer와 flags·device/QPC 위치를 실제로 그대로 노출하는 기준 후보. COM/스레드 수명, 패키징·유지보수 비용, Python 경계를 실험한다. |
| [SoundCard upstream](https://github.com/bastibe/SoundCard) | mic+loopback 동시 캡처, 기본 포맷 보존, 채널 정확성, 내부 변환·buffering, 시각·flag 노출 가능성을 검사한다. |
| [PyAudioWPatch upstream](https://github.com/s0d3s/PyAudioWPatch) | 후보 wheel의 loopback·동시 stream, 실제 PortAudio 포맷/타임스탬프 의미, device frame/QPC·오류 전달, 바이너리 재배포를 검사한다. |
| [python-sounddevice 공식 문서](https://python-sounddevice.readthedocs.io/en/latest/) | 비교 후보. 해당 버전/PortAudio 빌드에서 loopback 요구사항을 만족하는지 먼저 확인한다. WASAPI 선택 옵션 존재만으로 loopback·장치 시계 지원을 추정하지 않는다. |

실험 순서는 ① 포맷·타임스탬프·flags capability 확인 → ② 두 트랙 원본 비교·단절/idle 확인 → ③ GIL/CPU·디스크 부하·AI 분리 → ④ reconnect/pause/suspend → ⑤ 복구·장시간·패키징이다. 핵심 capability가 빠진 wrapper에 arrival time만 붙여 동등한 계약으로 채택하지 않는다. 보완 native bridge 비용 또는 낮은 지원 등급을 D00에 제시한다. 라이선스·배포 게이트는 D04와 함께 승인한다.

### 8.2 시험 행렬과 기록

정량값은 **미수행 수락 기준 제안**이다. 최소 사양과 지원 Windows 빌드는 D00/D04가 고정해야 한다. 모든 supported cell은 정상 부하 3회, 장애 반복은 아래 횟수를 충족한다. 최소 두 제조사의 물리 PC, 내장 오디오·독립 USB 장치·Bluetooth 조합을 포함하고 OS build, 전원 모드, 드라이버/펌웨어, 연결 프로파일, 실제 포맷, 백엔드·Python·앱 빌드, 디스크 종류·여유 공간, 부하 도구·설정, test seed를 기록한다. VM은 순수 복구 시험을 보조하며 물리 오디오 호환성 증거를 대체하지 않는다.

44.1/48 kHz와 mono/stereo, 서로 다른 rate의 mic+loopback, 지원할 경우 5.1/7.1, USB hotplug, Bluetooth 출력/입력 프로파일 변경, 기본 장치 변경, silent/idle→재생 전환을 포함한다. 장치가 제공하지 않는 포맷을 강제해 실패한 결과를 backend 결함으로 오해하지 않는다. `UNSUPPORTED`에는 근거와 제품 지원 범위를 명시하고 필수 cell을 임의 제외하지 않는다.

| 게이트 | 방법 | 제안 수락 기준 |
| --- | --- | --- |
| A01 포맷/원본 | 44.1/48 kHz mono/stereo 및 서로 다른 두 트랙, 채널별 식별 신호. 앱 입력 경계 bytes를 독립 oracle로 보관하여 확정 payload와 대조 | 요청·실제 포맷 기록 일치, 내부 미고지 변환 0, 채널 교환/누락 0, 앱 수신 경계→확정 원본 PCM 불일치 0. 이는 물리 ADC bit-exact 시험이 아니다. |
| A02 시계·정렬 | 합성 ±50/100/500 ppm, timestamp error·offset·device reset 주입; 물리 공통 펄스 60분 | 합성 rate 추정 오차 ≤5 ppm(60초 예열 후), gap 이외 구간 매핑 오차 ≤2 ms. 물리 정렬은 고정 전달 지연 보정 후 펄스 잔차 p95 ≤20 ms, 최대 ≤50 ms, 60분 후 누적 기울기 오차 ≤10 ms. Bluetooth가 실패하면 별도 실측 지원 등급으로 분리한다. |
| A03 정상/부하 캡처 | 60분 dual-track 3회, 고정된 최소 사양에서 CPU ≥80% 부하·메모리 압력·허용 AI 동시 실행; 알려진 디지털 신호로 누락 검출 | 원본 queue drop 0, 예상치 못한 backend discontinuity 0, 설명되지 않은 신호 누락 0. 단순 플래그 0만으로 통과하지 않는다. capture critical path p99.9 < 실제 서비스 deadline의 25%, 관측 최대 < deadline. hard real-time 보장은 아니다. |
| A04 bounded 포화 | queue 2초 설정에서 writer를 5초 정지, 서로 다른 10개 지점에 반복 | pool/queue byte·slot 상한 초과 0, capture 대기 0, 보존 순서 뒤바뀜 0. 정확한 drop frame 합=주입 oracle. gap 이벤트가 포화돼도 누적값 보존. UI critical ≤1초. |
| A05 AI 격리 | STT 10배 지연, 모델 exception/OOM, AI worker 종료, UI 10초 정지 | capture/manifest 진행 유지, 허용된 자원 예산에서 원본 drop 증가 0, AI tap 손실은 원본 gap에 포함하지 않음. |
| A06 장치·권한 | USB 제거/재연결·포맷/기본 장치 변경 각 20회, 접근 거부·오디오 서비스 중단 | 다른 트랙 drop 증가 0, 오류 UI ≤1초. 같은 endpoint usable 통지 이후 재개 ≤5초 목표, 새 epoch/gap 100% 기록. PINNED의 다른 endpoint 무단 전환 0. 거부된 입력을 REC 정상으로 표시 0. |
| A07 pause·절전 | pause/resume 100회; 일반 절전·지원 대상 Modern Standby 각각 20회 | 승인 cutoff 뒤의 수신 PCM 저장 0, pause 구간 provenance 100%. 복귀 usable 통지 후 재초기화 ≤5초 목표. 원본 중복·시계 역행 0, 중단 구간을 복원됐다고 표시 0. |
| A08 저장 장애 | ENOSPC, short write, flush/rename/DB 실패, 디스크 5초 stall 및 접근 거부를 게시 단계마다 주입 | 확정 파일 overwrite 0, false saved 0. 정상 보존 청크 100% 재검증 가능. 공유 볼륨 실패 시 저장 불가 REC 중단, 부분 결과 유지. DB 오류만으로 캡처 즉시 정지하지 않되 게시 backlog가 bounded해야 함. |
| A09 프로세스 crash | 5.2의 각 경계 직전/직후, 레코드 중간, manifest 게시 중, DB commit 전후 강제 종료; 총 ≥100 seed | 마지막 확정 watermark 이전 누락 0, 정상 부하 미확정 꼬리 ≤8초 목표, 유효 prefix 회수, 중복 chunk/frame 0. 복구 2회 결과 동일. 손상/unknown tail 은폐 0. |
| A10 전원 장애 | 승인된 비생산 시험 장치에서 각 저장 단계의 강제 전원 차단 ≥20회 | 결과로 내구성 지원 범위를 정한다. 손상 탐지/보고 100%, 무손실 약속은 시험 전 금지. 단순 프로세스 kill 결과를 이 시험의 대체 근거로 사용하지 않음. |
| A11 장시간/용량 | 24시간 dual-track 실장치, 별도 합성 ≥2^32 frame/byte 경계·WAV 한계 초과 fixture | overflow·frame 중복·silent truncation 0. 1시간 안정화 후 capture+writer working set 증가 ≤32 MiB/23시간, queue/pool 상한 준수. 원본은 chunk 한계 준수, WAV는 명시적 분할/지원 형식으로 완전 내보내기. |
| A12 사용자 건강상태 | 수신·저장·AI 상태를 독립 지연시키고 UI 계측 | 사건→경고 ≤1초, 완료 표시가 manifest/index보다 앞서지 않음. level 0/idle/장치 실패 구분, gap exact/estimate/unknown 표시 100%. |

정상 저장 처리량은 최악 지원 포맷의 합산 byte rate 대비 지속 3배 이상을 초기 디스크 게이트로 제안한다. 처리량만으로 flush/metadata tail latency를 대신하지 않는다. 청크 close→manifest 게시 p99 ≤1초를 정상 부하 목표로 하고, stall 시 8초 손실 예산을 정상치로 계속 표시하지 않는다. 모든 percentile은 표본 수·최대값·실패 횟수와 함께 보고한다.

### 8.3 설계 검토 수락 기준과 검증 상태

이 배정의 문서 수락은 native 포맷·블록/시계·gap·queue·게시/reconciliation·장애/UI·정량 게이트·미결정 소유자가 모두 존재하고 사용자 원칙과 제안을 분리했을 때다. **위 A01~A12는 모두 NOT_RUN**이다. 현재 검증은 입력 문서 대조, 계약 내부 일관성·상대 링크 검사, 본문의 공식 1차 자료 확인으로 제한된다. 소스 코드·장치·라이브러리 API를 실행 검증하지 않았다. 통합 초안과의 저장 계약 차이는 O-A09가 미해결이므로 제품 통합 완료로 표시하지 않는다.

## 9. 통합 시 결정해야 할 질문

| ID | 질문/제안 | 결정 소유자·닫기 조건 |
| --- | --- | --- |
| O-A01 | 어떤 Windows 빌드·CPU/RAM·최대 트랙/채널/rate와 장치 조합을 필수 지원하는가? | D00+D04: A01~A12 행렬과 최소 사양 고정. Bluetooth의 별도 정확도 등급 여부 포함. |
| O-A02 | native WASAPI adapter 또는 wrapper+bridge 중 어느 것을 채택할 것인가? | D00 구현 배정 후 D02 capability 결과·패키징·D04 라이선스 검토로 결정. 지금은 미선정. |
| O-A03 | 복구형 `.rcpcm` 독자 컨테이너를 채택할 것인가, 동등한 prefix 복구·metadata 보존을 입증하는 대안이 있는가? | D00+D01: reader/serializer schema, golden fixture, A08~A11 통과가 조건. 익숙한 WAV라는 이유만으로 복구 동등성을 가정하지 않음. |
| O-A04 | manifest 권위/DB 인덱스, generation 체인, sequence 예약, session 단일 writer를 공통 저장 계약으로 채택할 것인가? | D00+D01: 상태 모델·DB transaction/journal 설정·취소/재개와 일치시켜 기록. |
| O-A05 | 2초 queue·5초 chunk·64 MiB cap·8초 정상 부하 crash 꼬리·디스크 임계값을 기본값으로 채택할 것인가? | D00+D04: 최소 사양 실측 후 수치 승인. 설정 변경 시 UI 예산과 시험도 갱신. |
| O-A06 | pause 시 privacy cutoff의 UI 표현, 절전 복귀 자동 재개, FOLLOW_DEFAULT opt-in을 어떻게 노출할 것인가? | D00+D03: 실제 stop acknowledgment 및 새 endpoint 동의와 일치하는 UX 확정. |
| O-A07 | 삭제 tombstone·격리 `.part` 보존 기간·복구 사본 공간·전원 장애 내구성 등급은? | D00+D04: 삭제 세션 부활 방지·보존/삭제 정책 및 A10 승인된 시험 장치 결정. |
| O-A08 | clock 품질이 낮은 장치의 제품 지원 등급과 export gap 표현은? | D00+D03: ARRIVAL_ONLY 허용 범위·전사 시간 신뢰도·silence provenance·고정 offset calibration 정책 결정. |
| O-A09 | D00 초안의 raw PCM+descriptor / DB→manifest snapshot과 D02의 프레임 레코드 / manifest delta→DB 중 무엇을 채택할 것인가? | D00+D01: 공통 저장 ADR에서 선택하고 A08/A09 crash matrix를 그 순서로 고정한다. 대안 A는 기존 bundle 계약을 유지하되 staging에서도 블록 경계·sequence·시간 metadata와 CRC를 먼저 복구할 수 있도록 sidecar journal을 추가하는 것이다. 대안 B는 `.rcpcm`으로 해당 metadata를 in-band 보존한다. 게시 순서는 어느 쪽도 전체 원자성을 보장하지 않으며, 파일-only/DB-only/manifest-only 상태를 모두 재조정해야 한다. D02 권고는 미디어 복구 기준과 업무 DB 권위를 분리하고, 선택한 순서의 crash 불변식을 명시하는 것이다. 이 항목 미결정 상태에서 두 writer 계약을 혼용하면 안 된다. |

D00에게 제안할 타 파일 반영: `architecture-v1.md`에 원본/native 정의, 세 시계 도메인, 독립 트랙 상태, queue drop 및 파일→manifest→DB 계약을 채택/보류로 기록한다. `validation-plan.md`에는 A01~A12, 미수행 상태, 지원 행렬·최소 사양·계측 산출물 요구를 넣는다. `assignments.md`의 D02 상태 갱신은 오케스트레이터가 수행한다. 이 배정에서는 해당 파일을 수정하지 않았다.
