# BR11 Windows native/audio 독립 검토

- 검토자: B11 수석 아키텍트. 대상 작성자 B12와 별도 세션이며 B11 content/jobs 작성물은 이 검토의 승인 대상이 아니다.
- 일자: 2026-11-14. 최초 상태: **수정 요청 — BR11-01(S2) OPEN**. 현재 판정은 후단 **RECHECKED** 기록이다. 검토자가 타인 소스는 수정하지 않았다.
- 범위: `capture/devices.py`, `capture/wasapi.py`, `audio/*`, 관련 unit 시험과 제품 계약 B12. 저장·UI 전체 동작이나 실제 녹음 품질을 승인하지 않는다.
- 독립 산출물: [시험](../../tests/integration/test_native_independent.py). DLL 접근 금지 autouse fixture, 독자 fake COM/vtable·backend, 유리수/비트·시계 oracle를 사용했다. 작성자의 fixture와 자체 통과 판정을 복사하지 않았다.

## 확인한 계약과 증거

| 경계 | 독립 확인 내용 |
| --- | --- |
| ABI | Microsoft 헤더와 대조한 IAudioClient 슬롯 3/8/10/11/14, IAudioCaptureClient 3/4/5, IMMDevice/Enumerator 순서와 Windows 폭·stdcall. fake vtable이 Initialize 인수, 64bit device/QPC 위치, GetService IID를 실제 ctypes 호출로 검사한다. |
| format | 독자 WAVEFORMATEXTENSIBLE fixture(32bit container/24 valid bits/FL·FR)를 원문 bytes로 Initialize에 넘기는 것을 확인했다. 정규화는 container 기준이다. |
| 버퍼 | GetBuffer 뒤 owned bytes 복사, ReleaseBuffer가 원 메모리를 바꿔도 반환 payload 유지, release와 COM 종료의 순서·스레드를 검사했다. 실제 driver ABI 적합성 증명은 아니다. |
| 시계 | GetBuffer의 100ns 값을 ns로 변환하고 QPC tick은 frequency로 정수 변환한다. TIMESTAMP_ERROR는 capture 시각 unknown, arrival은 별도이며 정렬 대체값이 아니다. |
| 수명 | worker 전체가 같은 thread에 있고 stop timeout 동안 release ACK가 발생하지 않는다. 지연 read 완료 후 packet을 제출하지 않으며 close barrier 해제 후에만 ACK한다. |
| 단절 | fake DEVICE_UNAVAILABLE/일반 native 오류에서 error·close를 확인하고 자동 endpoint 대체와 epoch 재사용을 금지하는 것을 검사했다. 실제 절전 이벤트 전달/드라이버 동작은 미검증이다. |
| 처리 | s16/s24/s32 랜덤·극값 bytes 왕복, f32 범위·비유한 거부, 반대 위상 stereo VAD, meter, 유리수 선형 리샘플링 oracle와 원본 bytes 불변을 검사했다. 선형 보간에 anti-alias 품질을 부여하지 않는다. |
| 정렬 | 음의 시각/위치 reset, sequence 유실, epoch와 DATA_DISCONTINUITY는 적합 구간을 분리한다. 큰 anchor에서 정확한 100ppm 시계 oracle와 두 트랙 공통 원점을 확인했다. 양의 시간 급변에는 아래 결함이 남았다. |

## 발견 사항

### BR11-01 — S2 / OPEN: 양의 QPC 급변이 drift로 흡수되어 gap과 시간 품질을 왜곡

- 위치: [alignment.py](../../src/recoryn/audio/alignment.py) `_contiguous`(25–49행), `estimate_drift`(73–116행), `align_blocks.emit`(161–191행).
- 반례: 48kHz, 480frame씩 3개, 같은 session/track/epoch, sequence 0/1/2, device frame 0/480/960, capture ns `1_000_000_000 / 1_010_000_000 / 61_020_000_000`, flags 없음. 도착 시각은 oracle와 무관하게 둔다. 절전 복귀 또는 잘못된 clock 상관의 **합성 입력**이며 실제 하드웨어에서 관찰했다고 주장하지 않는다.
- 현재 결과(origin=1s): `[-10s,20.01s)`, `[20.01s,50.02s)`, `[50.02s,80.03s)`로 mapping한다. 모두 segment=0, quality=`DEVICE_CORRELATED`, drift≈−999666.78ppm이다. fit residual=20s는 AlignedSpan에 전달되지 않는다. 실제 10ms 블록과 60s 공백이 약 30초씩의 오디오로 잘못 표현된다.
- 원인: frame 위치·sequence와 timestamp 증가만 연속성으로 인정하고, nominal sample duration과 timestamp 차이의 불일치/fit 품질을 검사하지 않는다. 회귀가 첫 anchor를 −9s로 옮겨 공통 원점 앞에 유효 오디오를 만들어낸다.
- 재현: `test_br11_01_forward_clock_jump_cannot_be_hidden_as_correlated_drift`는 현재 수정 전 실패한다. 양의 급변을 무조건 정상 drift로 게시하지 않는 독립 oracle다.
- 해결 조건: 시계 급변과 허용 가능한 drift를 구분하는 명시 정책으로 구간을 분리하거나 해당 mapping을 unknown/오류로 차단한다. 수치 한도는 장비 측정값으로 주장하지 말고 구성/정책임을 명시한다. 큰 residual/외삽의 불확실성을 결과에서 숨기지 않는다. 급변 반례·2표본 급변(회귀 residual=0)·정상 수백 ppm·반대 방향 reset을 회귀로 확인한다. 알려진 host-clock gap을 오디오 신장으로 채우지 않아야 한다.
- 소스 수정과 최초 해결 주장은 B12 담당, 동일 BR11 검토자가 새 digest와 반례로 재확인한다. 현재 최종 통과로 취급하지 않는다.

## 실행 기록

```powershell
$reviewTemp = Join-Path $env:TEMP ('recoryn-br11-' + [guid]::NewGuid().ToString('N'))
.venv/Scripts/python.exe -m pytest tests/integration/test_native_independent.py tests/unit/test_wasapi.py tests/unit/test_audio.py -q -p no:cacheprovider --basetemp=$reviewTemp --tb=short
.venv/Scripts/python.exe -m mypy src/recoryn/audio src/recoryn/capture/devices.py src/recoryn/capture/wasapi.py tests/integration/test_native_independent.py
.venv/Scripts/python.exe -m ruff check tests/integration/test_native_independent.py
```

- 결과: **109 passed, 1 failed (BR11-01)** / 0.39s. 독립 시험 27건 중 26통과·1실패, 기존 대상 unit 83통과. mypy 6파일 통과. Ruff check 통과. 실패를 xfail/skip 처리하지 않았다.
- 첫 실행의 fake COM 포인터 구성 오류 2건은 독립 시험 작성 오류로 수정 후 통과했다. 제품 결함 수에 포함하지 않는다. 단일 test 파일만 지정한 mypy의 editable import 경로 오류는 소스 경로를 함께 지정해 해결했다.

## 검토 snapshot SHA256

| 파일 | SHA256 |
| --- | --- |
| capture/devices.py | 025C72E89058A61C472B535DC7FEDE1CAF8986E4D600AC1417A7D74D82916F05 |
| capture/wasapi.py | 5A585507062C4889D189B44136E123304ED179C6D23B9FD3CEE4342F95607D10 |
| audio/__init__.py | A35966E2248F461CFAA712AD43127547E029A4F761C73D1FD1D5D4E76A041F02 |
| audio/alignment.py | 0F19A71B239BD4CA8C31ABCF1BEF9FA9FD5F67F53BA58338038308D26CF4A91B |
| audio/processing.py | EC826DF3CB12E12F92D2E60F14A33A0A6951BAF20993C29D4832FC0922DEE6B6 |

## 정본 대조 자료와 미검증 한계

- 공식 [Audioclient.h](https://raw.githubusercontent.com/microsoft/win32metadata/main/generation/WinSDK/RecompiledIdlHeaders/um/Audioclient.h), [mmdeviceapi.h](https://raw.githubusercontent.com/microsoft/win32metadata/main/generation/WinSDK/RecompiledIdlHeaders/um/mmdeviceapi.h): vtable·인수 폭 대조. 최신 main의 문서 확인이지 특정 SDK 바이너리 호환성 인증은 아니다.
- Microsoft [GetBuffer](https://learn.microsoft.com/en-us/windows/win32/api/audioclient/nf-audioclient-iaudiocaptureclient-getbuffer), [ReleaseBuffer](https://learn.microsoft.com/en-us/windows/win32/api/audioclient/nf-audioclient-iaudiocaptureclient-releasebuffer), [buffer flags](https://learn.microsoft.com/en-us/windows/win32/api/audioclient/ne-audioclient-_audclnt_bufferflags): 위치 단위·소유 수명·오류 의미.
- Microsoft [CoInitializeEx](https://learn.microsoft.com/en-us/windows/win32/api/combaseapi/nf-combaseapi-coinitializeex), [Initialize](https://learn.microsoft.com/en-us/windows/win32/api/audioclient/nf-audioclient-iaudioclient-initialize), [WAVEFORMATEXTENSIBLE](https://learn.microsoft.com/en-us/windows/win32/api/mmreg/ns-mmreg-waveformatextensible): apartment count·초기화·포맷. Windows 8 첫 STA 주의문을 Windows 10 지원 코드의 재현된 결함으로 확대하지 않는다.
- Microsoft [QPC](https://learn.microsoft.com/en-us/windows/win32/sysinfo/acquiring-high-resolution-time-stamps): host clock과 절전 포함 여부 대조. 다른 부팅/host의 clock domain을 직접 비교할 수 없으며 align_blocks의 동일 host/run 호출자 전제가 남는다.
- 실제 capture/장치 open/probe는 실행하지 않았다. B10의 read-only enumeration 1 render/1 capture exit0는 전달받은 별도 증거이며 이 검토자가 재실행하지 않았다. 실제 disconnect/sleep·8시간·ADC/드라이버/음향 지연·성능·x86/ARM64 하드웨어는 NOT_RUN이다.

## BR11-01 수정 후 독립 재확인 — RECHECKED

- B12 수정, BR11 동일 검토자가 2026-11-14 재확인했다. 위 원 발견·실패 결과·당시 digest는 이력으로 보존한다. **이 snapshot에서 BR11-01 문서·코드상 해결, OPEN S0/S1/S2 0건**이다. 제품 전체나 실제 캡처 승인은 아니다.
- 새 `audio/alignment.py` SHA256: **56EA82F997ECC395BE30EAE8BAE66BE8047D5D3B15B032846B974C2A1A24B6ED**. 위 devices/wasapi/processing digest는 동일했다.
- `_clock_step_ok`가 frame 경과와 시각 증가의 불일치를 검사하고, `estimate_drift`가 rate·residual 상한을 검사한다. 상한 1%/step rounding 1µs/fit residual 1ms는 코드의 보수적 거부 정책이며 하드웨어 측정 정확도나 확정 채택 수치가 아니다.
- `align_blocks`는 급변 전후를 분리하고 해당 identity를 새 epoch까지 `UNCERTAIN_CLOCK`으로 유지한다. 불확실 구간은 관측된 시작 시각과 nominal packet 길이를 보존하고 fitted drift를 게시하지 않는다. 큰 fit residual도 같은 품질로 하향하며 원본을 변경하지 않는다.
- 원 3블록 반례는 `[0,10ms) / [10ms,20ms) / [60.02s,60.03s)`가 됐다. 마지막 block은 UNCERTAIN_CLOCK/drift=None이며 60초 관측 공백을 오디오로 늘리지 않는다. 이 공백이 실제 sample 유실량이라는 측정 주장은 하지 않는다.
- 새 독립 시험: `test_br11_recheck_two_point_zero_residual_jump_and_epoch_taint`(250ms/60s, 2표본 residual=0인 급변 거부·invalid timestamp 뒤 taint 유지·새 epoch 복원), `test_br11_recheck_hundreds_ppm_remains_correlated`(−300/+500ppm 근방 정상 시계), `test_br11_recheck_global_bad_fit_cannot_hide_residual_with_valid_local_steps`(국소 step 정상이나 전역 affine fit 불량)을 추가했다. 기존 음의 reset·sequence gap·TIMESTAMP_ERROR·원본 불변 시험도 재실행했다.
- 실행: 위 unique TEMP/cache-off pytest 명령에 `-W error` 추가 → **122 PASS / 0 FAIL / 0 SKIP**(독립 32건 포함), 0.41s. 같은 6파일 mypy PASS, 독립 시험 Ruff check/format PASS. 초기 실패의 xfail/skip 완화 없이 같은 원 oracle가 통과했다.
- 남은 제한: clock-domain 동일 host/run 호출자 전제, 상한의 장비별 검증, 실제 절전·분리 이벤트/8시간·포맷별 음성 품질은 계속 NOT_RUN이다. 이 재확인은 B11 자신의 jobs/content 구현 승인과 분리한다.

## 2026-11-14 재부팅 복구 R11 대조

R11은 문서의 최초 OPEN 기록과 후단 RECHECKED를 구분해 읽고, 현재 devices/wasapi/audio 5파일 SHA256을 실제 바이트와 대조했다. alignment는 `56EA82F997ECC395BE30EAE8BAE66BE8047D5D3B15B032846B974C2A1A24B6ED`, 나머지 4파일은 위 재확인과 동일했다. 원 급변 반례와 재확인 oracle를 포함한 지정 native/audio/wasapi 시험을 재부팅 후 고유 TEMP/cache-off pytest로 실행했다. B11 및 release 회귀와 함께 최종 **371 PASS / 0 FAIL**, ResourceWarning 오류 처리였다. 이 합산 실행을 과거 122건에 더해 세지 않는다.

오디오 소스·독립 시험은 이번 복구에서 수정하지 않았다. 기존 BR11 지정 snapshot의 재확인 근거를 복원했으며 새 실장비 승인이나 B11/패키징 자기 승인을 수행하지 않았다. 실제 캡처·장치 probe·weights/모델·네트워크·vault·전원 장애 시험은 NOT_RUN이다. root가 이후 audio 코드를 변경하면 새 diff와 시험을 별도로 대조한다.
