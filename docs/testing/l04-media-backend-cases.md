# L04 Qt 미디어 백엔드 제외·PCM 직접 재생 경우의 수

2026-11-15, 작성 C00. 배정 L04 / push L-P04. 근거는 [라이선스 검토 L01](../implementation/license-review.md)의 D7이다. 이 문서는 시험 설계와 분모를 정의하며 통과 결과는 [L 결과](../implementation/license-results.md)에 기록한다.

## 이력

처음에는 FFmpeg만 빼고 재생을 Windows Media Foundation(WMF) 백엔드로 고정하려 했다. 그 후보(`build/l04-1794733273`)에 대한 독립 검토에서 세 가지가 나와 폐기했다.

- **다채널 회귀:** WMF는 12~32채널에서 위치가 진행하지 않았고, 64채널은 InvalidMedia였다.
- **smoke 거짓 통과(진행):** smoke가 위치 지정 뒤 재생 진행량을 재지 않았다. 위치 지정에 +500 ms를 더하고 재생은 하지 않는 가짜 player도 통과했다.
- **smoke 거짓 통과(NOT_RUN):** 출력 장치가 없어 재생을 확인하지 못한 NOT_RUN이 최상위 PASS로 감싸졌다. 빌더도 최상위 status만 봐서 이를 받아들였다(L04-P01).

현재 설계는 다음과 같다. Qt의 미디어 백엔드 플러그인 두 개를 모두 빼고, 재생은 Recoryn이 직접 PCM을 해석해 `QAudioSink`로 출력한다.

## 요구사항과 위험

- **잔존 금지:** FFmpeg 라이브러리나 Qt 미디어 백엔드 플러그인이 하나라도 남으면 D7을 위반한다.
- **재생 범위:** 제품이 만드는 근거 클립(`app.media`)은 16-bit PCM WAV다. 원 채널 수(1~64)와 rate를 보존하고, 클립 하나는 최대 8 MiB다. 어느 형식이든 선택한 위치부터 재생해야 한다.
- **검증 bytes와 재생 bytes:** 재생하는 bytes는 해시를 검증한 그 bytes여야 한다. 해석 실패, 형식 위반, 해시 불일치는 재생하지 않는다.
- **장치 문제:** 출력 장치가 없거나 형식을 지원하지 않으면 조용히 실패하지 않고 오류 코드를 낸다.

## PCM 준비 R (`prepare_playback`)

oracle은 세 가지다.

- **손계산:** 아래 반올림 7행처럼 기대값을 직접 적는다.
- **정확한 분수 평균:** frame마다 표본 합을 채널 수로 나눈 `Fraction`을 `round()`(ties-to-even)로 반올림한다. 제품의 `array` 기반 평균과 공유하는 코드가 없다.
- **기존 `recoryn.audio` 도우미와 대조:** decode → equal-weight mono → 16-bit encode 결과와 비교한다. 이 도우미는 1/6, 1/12 같은 float 가중치가 정확하지 않아, 평균이 정확히 .5인 frame에서 1 LSB 다를 수 있다. 처음 시험에서 6·12채널 6행이 바로 이 이유로 실패했다. 따라서 이 대조는 ".5 동률 frame에서만 최대 1 LSB 차이, 그 외 완전 일치"로 판정한다.

- **채널·rate 조합:** 채널 C={1,2,3,6,12,16,64} × rate S={8000,44100,48000} = 21행이다. 2의 거듭제곱이 아닌 6·12채널이 동률 차이를 드러낸다.
  - 각 행은 결정적 의사난수 16-bit 표본(전 범위, 최솟값·최댓값 포함) 40 ms를 만든다.
  - 기대값: C≤2는 원 data bytes의 정확한 꼬리, C≥3은 정확한 분수 평균이다. 기존 도우미와의 대조는 위 기준으로 따로 판정한다.
  - 시작 위치는 전체 길이의 절반이다.
- **위치 분할:** 44100 Hz stereo 1초 클립에서 8행이다. 0, 1 ms(44.1 frame → 44 내림), 333 ms, 마지막 frame 직전, 정확히 끝(빈 결과), 끝 초과(빈 결과로 고정), 음수(0으로 고정), 10 ms 배수의 정확 경계다. 기대 frame은 `position_ms × S // 1000`을 끝으로 자른 값이다.
- **mono 반올림 손계산 7행:**
  - 3채널 (1,2,4) → 2
  - 3채널 (−1,−2,−4) → −2
  - 4채널 (1,1,0,0) → 0(0.5, ties-to-even)
  - 4채널 (3,1,0,0) → 1
  - 4채널 (1,2,0,0) → 1(0.75)
  - 64채널 모두 −32768 → −32768
  - 64채널 모두 32767 → 32767
- **거부 9행(PLAYBACK_SOURCE_INVALID):** 해시 불일치, 상한+1 byte 파일, 8/24/32-bit 정수 PCM, IEEE float WAV, RIFF가 아닌 bytes, 선언 frame보다 짧은 data, 65채널이다.
- **원본 불변:** 원본 파일 bytes는 바뀌지 않는다.

## 출력 O (`SinkPlayback`, 가짜 Qt 경계)

`PySide6.QtMultimedia`를 메모리 가짜로 바꿔 Qt의 실제 장치 없이 판정한다. 13행이다.

- **오류:** 기본 출력 장치가 없으면 PLAYBACK_OUTPUT_UNAVAILABLE이다. 형식을 지원하지 않으면 PLAYBACK_FORMAT_UNSUPPORTED다. 시작 직후 sink 오류가 나면 PLAYBACK_OUTPUT_FAILED이고 자원을 해제한다.
- **시작:** sink 형식(rate·채널·Int16), 버퍼 bytes가 payload와 같은지, 볼륨을 확인한다.
- **정리:**
  - IdleState(버퍼 소진)가 오면 sink를 멈추고 해제한다.
  - 이미 교체된 sink의 늦은 상태 신호는 무시한다.
  - 두 번째 시작은 첫 sink를 먼저 멈춘다.
  - stop은 여러 번 불러도 안전하다.
  - **시작 뒤 Qt가 멈춘 경우(L04-D04):** 정상 시작 뒤 Qt가 sink를 StoppedState로 바꾸면, 오류가 있든 없든 sink와 버퍼를 해제한다. 오류(IOError)가 있으면 PLAYBACK_OUTPUT_FAILED를 오류 callback으로 알린다. 원 반례는 표시 없음, sink·버퍼 보유였다. 오류 있음·없음 2행과 실제 `DesktopAI._play` 경로에서 상태 표시줄 문구가 바뀌는 1행이다.
- **위치:** `position_ms = start_frame×1000//S + processedUSecs//1000`이다.

## 데스크톱 경로 D

- **기존 UI 시험 강화:** 기존 시험은 `_play`에 경로와 위치가 전달되는지만 봤다. 이제는 해시를 검증한 클립의 정확한 PCM(시작 frame 0, data bytes 전체)이 `_play`에 전달되는지를 본다. 파생 클립이나 원본이 변조되면 `_play`를 부르지 않는 기존 행도 유지한다.
- **기존 독립 시험 유지:** `test_ai_independent`의 reader lease 시험은 `_verify_playback(session, source)` 호출 형태를 그대로 쓴다. 새 위치 인자의 기본값은 0이다.

## 정책 P와 spec S

결정표는 시험 안에 손으로 적는다.

- **금지 11행:** 실제 Qt FFmpeg 6개(`ffmpegmediaplugin.dll`, avcodec-63, avformat-63, avutil-61, swresample-7, swscale-10), Qt가 싣지 않는 FFmpeg 3종(avdevice·avfilter·postproc)을 다른 디렉터리에 둔 경우, 대문자·역슬래시 1행, `windowsmediaplugin.dll` 1행이다.
- **허용 6행:** `Qt6Multimedia.dll`, `Qt6MultimediaWidgets.dll`, `QtMultimedia.pyd`, 디렉터리 `avcodecs/`, `swscale.txt`, `postprocessing/filters.dll`, `ffmpeg-notes.txt`다.
- **규칙 대표성:** 새 규칙 10개 각각에 거부 행이 있어야 한다.
- **spec:** 목적지·출처·평탄화된 출처로 걸리는 FFmpeg 3행과 WMF 플러그인 1행을 제거하고, Qt6Multimedia를 유지한다. runtime hook은 `rthook_no_av.py` 하나다(백엔드 고정 hook은 폐기).

## 증거 E

- **native 대응표:** 105개이고 중복이 없다. FFmpeg 그룹과 백엔드 플러그인이 없고, 금지 정책에 걸리는 경로가 없다. LGPL-2.1 원문도 없다.
- **결정표:** FFmpeg 파일과 두 플러그인은 UNMAPPED다.
- **NOTICE와 gate:** NOTICE에 백엔드 비배포와 "No FFmpeg code is distributed."를 적는다. gate는 `NOT_DISTRIBUTED_L01_D1_D7`이다.
- **재유입:** Qt FFmpeg DLL이나 플러그인이 다시 들어오면 UNMAPPED이고 `verify`도 거부한다.

## smoke·빌더 판정 F

- **probe:** frozen smoke는 제품의 `prepare_playback`과 `SinkPlayback`으로 합성 무음 12채널 16 kHz 16-bit WAV 3초를 2000 ms부터 볼륨 0으로 재생한다. 12채널은 WMF가 진행하지 못한 형식이다.
  - **준비:** payload가 정확히 1초 mono 32000 bytes, 시작 frame 32000이다.
  - **진행:** 시작 뒤 150 ms의 위치 p1, 600 ms의 위치 p2를 잰다. 다음을 모두 만족해야 한다. 2000 ≤ p1 ≤ 2400, p2 − p1 ≥ 200, p2 ≤ 2900, 끝까지 sink 활성. 개발 환경 6회 실측은 p1 2198~2210, p2 2648~2660이었다. sink가 약 50 ms를 먼저 버퍼링한다.
  - 이 기준이면 위치를 부풀리고 재생하지 않는 가짜(p1=p2=2500)와 위치를 건너뛰는 가짜가 모두 실패한다.
- **장치 없음:** 출력 장치가 없으면 probe는 NO_AUDIO_OUTPUT_DEVICE_NOT_RUN을 낸다. 이때 smoke 최상위 status는 PASS가 아니라 PLAYBACK_NOT_VERIFIED다.
- **빌더 판정 6행:** smoke 코드와 독립적으로 판정한다. 정상, 최상위가 PASS가 아님, playback NOT_RUN, playback 누락, playback이 dict가 아님, 다른 상태 값이다. 정상 외에는 각각 FROZEN_SMOKE_FAILED 또는 FROZEN_SMOKE_PLAYBACK_NOT_VERIFIED로 거부한다.

## 주장하지 않는 것

- 실제 스피커 청취, 음질, 장치 전환, 장시간 재생은 확인하지 않는다.
- 3채널 이상의 mono 평균은 스피커 배치를 고려한 surround downmix가 아니다.
- 재생 중 출력 장치가 사라지는 경우는 Qt sink 상태로만 다루며 실기 시험하지 않는다.
