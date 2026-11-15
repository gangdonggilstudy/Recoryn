# L02 STT 입력·배포 제외 경우의 수

2026-11-15, 작성 C00. 배정 L02 / push L-P02. 근거는 [라이선스 검토 L01](../implementation/license-review.md)의 D1~D4다. 이 문서는 시험 설계와 분모를 정의하며 통과 결과는 [L 결과](../implementation/license-results.md)에 기록한다.

## 요구사항과 위험

- PyAV 없이 local Whisper가 같은 의미의 입력(16 kHz mono float32)을 받아야 한다. 잘못 해석한 표본 형식, 채널 합산, 반올림 길이, 고주파의 aliasing은 전사 품질을 조용히 떨어뜨린다.
- 원본 WAV bytes와 hash는 변하지 않는다. 디코딩·리샘플은 메모리 안의 파생 변환이다.
- 금지 구성요소가 배포물에 다시 들어오거나, 필요한 구성요소가 잘못 빠지면 라이선스 위반 또는 실행 실패가 된다.

## 디코더 D

인자는 표본 폭 W={1,2,3,4}바이트(`wave`가 쓰는 정수 PCM 전부)와 채널 C={1,2,3,6}이다. 3은 홀수 채널, 6은 다채널 대표다. 각 폭마다 최솟값, −1 LSB, 0, +1 LSB, 최댓값 다섯 code의 정확한 분수 값을 손으로 적는다. 프레임 f의 채널 c는 code (f+c) mod 5를 쓰고, 기대값은 채널 분수의 산술 평균이다. 분모는 |W|×|C|=16행이다. 거부 행은 IEEE float WAV(format 3), RIFF가 아닌 bytes, 선언 프레임보다 짧은 data(INPUT_INVALID) 3행이며 빈 data는 길이 0 결과 1행이다.

## 리샘플러 R

입력 rate S는 8000, 11025, 16000(항등), 22050, 32000, 44100, 48000, 88200, 96000의 9개다. 업샘플·비정수 비율·정수 비율·항등을 모두 포함한다.

| 가족 | feasible 정의 | 행 수 | 독립 oracle |
| --- | --- | --- | --- |
| 통과대역 | f∈{100,1000,4000,6000} 중 f<S/2 | 33 | 16 kHz에서 해석적으로 표본화한 같은 위상의 사인. 경계 0.05초 제외 최대 오차 ≤1e-3 |
| 저지대역 | S>16000, f∈{9000,10000,12000,20000} 중 f<S/2 | 21 | 대표 tone의 경계 제외 RMS 감쇠 ≤ −60 dB. aliasing이 0이라는 주장이 아니라 이 대표 주파수들의 감쇠 보장이다 |
| DC | S 9개 | 9 | 상수 0.25 유지, 오차 ≤1e-7 |
| 길이 | S×N, N∈{0,1,2,3,1000} | 45 | n/16000 < N/S인 정수 n의 개수 = ⌈16000N/S⌉(Fraction) |
| 블록 경계 | S×{BLOCK−1, BLOCK, BLOCK+1} 요청 출력 | 27 label / 25 고유 (S, N) 입력 | 같은 개수 정의. 각 요청 길이에 도달하는 최소 N을 쓴다. 업샘플 rate는 모든 출력 길이를 만들 수 없어 8 kHz N=8192와 11.025 kHz N=11289가 각각 BLOCK−1·BLOCK 두 label에서 출력 16384로 중복된다. 8 kHz의 BLOCK+1은 출력 16386이다. 이 rate들의 BLOCK−1(및 8 kHz BLOCK+1) 길이는 직접 관측하지 않는다(L02-STT-02, 검토자가 26→25로 정정한 독립 정수 계산과 C00 재계산 일치) |

통과대역 상한 6 kHz와 저지대역 하한 9 kHz 사이는 전이대역이다. 그 구간의 감쇠량은 계약하지 않는다. 유한 대표 주파수 밖의 모든 신호에 대한 전수 증명은 주장하지 않는다.

추가 행: 취소 check는 블록당 1회 호출되고 예외를 그대로 전달한다. 항등 rate는 블록 처리 없이 반환한다. rate 0과 2차원 입력은 거부한다. 48 kHz stereo 상수 0.125의 WAV 전체 경로는 길이 8000과 값 0.125를 확인한다.

## 어댑터 A

기존 faster-whisper 어댑터 시험의 가짜 모델이 받은 인자를 기록한다. 48 kHz stereo 입력이 float32 1차원 배열, 기대 길이 ⌈16000N/48000⌉, 기대 상수값으로 전달되는지 확인한다. numpy가 없으면 DEPENDENCY_MISSING이다. 기존 lazy·local_files_only·취소·부분 결과 행은 변경하지 않는다.

## 배포 정책 P

금지 결정표는 시험 안에 손으로 적는다. 금지 대표 경로 18행(PyAV 패키지·FFmpeg DLL·dist-info, x264/x265/OpenH264, Qt Virtual Keyboard·plugin·Qml·QmlModels·Quick·Pdf·qpdf, 조건 미확인 Mesa/LLVM `opengl32sw.dll`, NVIDIA 네 종)은 `verify`가 LICENSE_EXCLUDED_COMPONENT로 거부한다. 유지해야 할 유사 이름 9행(Qt FFmpeg avcodec/avutil, `available/`, `avx-` dist-info, Qt6Multimedia·Qt6Svg·qjpeg, Intel OpenMP, ctranslate2)은 허용한다. 정책의 모든 규칙이 최소 한 거부 행으로 대표되는지도 검사한다. spec은 가짜 Analysis 결과에서 금지 8행을 제거하고 필요한 4행을 GUI·CLI 양쪽에 유지하며, `excludes`에 `av`, runtime hook에 `rthook_no_av.py`가 있어야 한다. hook은 `import av`를 충족하고 속성 사용은 RECORYN_PYAV_NOT_BUNDLED로 거부하며 이미 import된 모듈은 교체하지 않는다.

실제 frozen 후보에서는 금지 파일 0개, 남은 PE의 import closure 미해결 0개, frozen smoke의 PyAV stub과 STT 입력 디코딩을 확인한다.

## mutation

임시 source 사본에서 하나씩 적용하고 정상 PASS와 목표 assertion FAIL을 확인한다. import·수집·timeout 실패는 검출로 세지 않는다.

| ID | 변이 | 기대 검출 |
| --- | --- | --- |
| M1 | 차단 주파수에서 `min(1, target/rate)` 제거 | 저지대역 행 |
| M2 | 24비트 부호 확장 제거 | 디코더 W=3 행 |
| M3 | 채널 평균을 합으로 변경 | 디코더 C>1 행 |
| M4 | phase별 DC 정규화 제거 | DC 행 |
| M5 | 출력 길이 올림을 내림으로 변경 | 길이 행 |
| M6 | spec의 금지 TOC 필터 제거 | spec 제거 행 |

## 미검증

실제 음성의 전사 품질 차이, 실제 Whisper 모델 추론, GPU, 장시간 입력의 메모리 상한은 NOT_RUN이다. 리샘플러 품질은 위 합성 신호 기준이며 PyAV/swresample 출력과의 비트 동일성을 주장하지 않는다.
