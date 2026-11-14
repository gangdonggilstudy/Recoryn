# Q22 오디오·수치 경우의 수

상태: **REVIEW_READY — 작성자 자체 검증 완료, Q24 독립 검토 대기**. 작성 Q22/w5:p3, 독립 검토 Q24, push Q-P02. 기준 30703fe의 1444 PASS는 과거 증거다. 쓰기는 이 문서와 tests/property/test_audio_case_space.py뿐이며 제품·기존 시험·config·Git은 읽기 전용이다. 작성자의 결과는 REVIEW_READY까지만 제출한다.

## 목적과 기존 대응

R03/U01/U02/P02: PCM bytes/frame/channel 의미, 분할과 fragment 경계, 파생 수치, VAD source frame, 불확실 시계·epoch 경계를 검사한다. 실제 장치·음성·AI 모델·전송·품질 시험을 뜻하지 않는다.

| 기존 node | 이미 있는 근거 | 추가할 차이 |
| --- | --- | --- |
| tests/property/test_pcm_storage_oracle.py::test_original_pcm_is_exact_concatenation | 생성된 여러 block의 저장 bytes·복구 보존, 30 examples | 저장 시험을 복제하지 않는다. 고정 신호의 모든 분할과 packet/fragment 표현을 decoder/encoder/clock에 교차한다. |
| tests/unit/test_audio.py::test_integer_decode_and_encode_extremes 및 test_float_samples_are_preserved_and_nonfinite_is_rejected | integer 극값, float 초과진폭·비유한 | 모든 분할·channel 최대 대표치, 음/양의 반올림 ties, IEEE 비유한 bit 위치를 교차한다. |
| tests/unit/test_domain.py::test_pcm_exact_format_lengths 및 test_pcm_invalid_shape | 일부 exact 길이·거부 | format/channel/frame count × byte 길이 차이의 수락/거부 결정표 전체를 검사한다. |
| tests/unit/test_audio.py::test_energy_vad_preserves_source_frames_and_detects_opposite_phase 및 test_vad_padding_merges_only_regions_inside_the_same_block | 특정 반대위상·padding·minimum 사례 | 5-frame 모든 신호 패턴과 window/minimum/padding·표현/위상 교차를 집합 oracle로 검사한다. |
| tests/integration/test_native_independent.py::test_resampling_count_and_linear_rational_oracle | 몇 개 rate pair의 유리수 기준 | 두 rate 위치의 타입/거부 cube와 더 넓은 유리수 polyline 생성·affine 변환으로 보강한다. |
| tests/unit/test_audio.py::test_jump_taint_survives_invalid_packet_but_resets_at_new_epoch 및 native BR11 재확인 | 특정 jump/invalid/new epoch | clock 품질·timestamp flag·device 좌표·epoch·jump의 결정표와 taint→invalid→reset의 고차 조합을 검사한다. |

## 유한 공간 사전 분모

6-frame signal의 인접 경계는 5개다. 각각 자르거나 유지하므로 partition은 2^5=32개다. 대부분 가족은 무제약 직적을 실행하며 PCM의 동일 표현 alias만 아래처럼 canonicalize한다. 제품 거부 행도 포함한다. 고차원을 한 개의 거대한 곱으로 주장하지 않고 아래 계약별로 분리한다. 같은 fixture 불가능성을 빌미로 제품 거부 입력을 제외하지 않는다.

| 가족 | 인자 / 제약 | 독립 분모 |
| --- | --- | --- |
| pcm_partition | s16/s24/s32/f32 × channels 1/2/3/64 × 32 partitions × packet/fragment. 무분할 1조각에서는 두 표현의 실제 API 입력이 같으므로 canonical packet 한 번만 센다. | raw 4×4×32×2=1024, alias 16개 제거 후 4×4×(1+31×2) = 1008 |
| byte_shape | 4 formats × 4 channel 수 × 선언 frames 1/6 × 길이 차이 −frame_bytes/−1/0/+1/+frame_bytes | 4×4×2×5 = 160 |
| quantization | 3 integer formats × channels 1/3 × signed ties/포화/끝점 12개 | 3×2×12 = 72 |
| float_nonfinite | ±Inf/±quiet NaN/±signaling NaN × c1의 1위치+c2의 2위치+c64의 3위치 | 6×(1+2+3) = 36 |
| vad_patterns | 5-frame 이진 신호 32개 × s16/f32 × mono/반대위상 stereo × window 1/2ms × minimum 0/2/4ms × padding 0/1ms | 32×2×2×2×3×2 = 1536 |
| vad_equal | integer negative full scale와 float 반대위상 full scale의 정확한 0dBFS threshold 등호 | 2 |
| vad_rate_rounding | rates 11025/44100/48000 × 1ms window frame 수의 −1/0/+1 speech 길이 × minimum 0/1ms × padding 0/1ms × mono/반대위상 stereo | 3×3×2×2×2 = 72 |
| vad_guards | threshold 10개 × window 3개 × minimum 3개 × padding 3개; 유효·다중 무효 조합 포함 | 10×3³ = 270 |
| rate_guards | source/target 각각 invalid 6종·valid 1/3의 8종 | 8² = 64 |
| sample_guards | bool/None/text/NaN/±Inf/float 변환 overflow × meter/downmix/resample/s16 encode/f32 encode | 7×5 = 35 |
| clock_cube | 정상/+60s/−15ms × same/new epoch × timestamp flag 2종 × quality 5종 × device 좌표 present/None | 3×2×2×5×2 = 120 |
| clock_taint | ±jump 2종 × invalid packet 4종 × 다음 same/new epoch | 2×4×2 = 16 |
| 합계 | 유한 row, pytest node 수·Hypothesis examples와 구분 | 3391 |

생성된 row 목록의 길이·유일 ID를 닫힌 산식과 비교하고, 각 유한 시험의 실제 진입 ID를 별도 ledger에 기록해 마지막 검증에서 expected/observed/누락/중복을 대조한다. PCM은 추가로 SUT에 전달한 실제 format·channel·각 block의 sequence/frame/payload/time/device/fragment signature를 저장해 중복이 없는지도 검사한다. singleton 표현 alias 제거는 제품 거부 행의 면제가 아니며 동일한 API 입력을 두 번 세지 않기 위한 canonicalization이다. 독립 검토자 Q24의 확인을 요구한다. subset 실행은 전체 분모 충족으로 주장하지 않는다.

## 독립 oracle와 오차

- PCM은 생산 encoder로 입력을 만들지 않는다. 원래 signed integer/IEEE bytes와 정확한 dyadic 값을 사용한다. 채널 번호의 base-6 자리와 frame 위치로 6-frame 신호를 만들며 모든 채널의 6값 signature가 서로 다른지 확인한다. 각 partition의 decode 값·encode bytes·frame/byte 합 및 source metadata가 불변인지 확인한다. packet과 같은 packet의 fragments 모두 source 시간 범위를 덮어야 한다.
- byte 길이 −frame/+frame/정확 길이는 decoder에서 다른 수의 완전 frame으로 수락하고 ±1 byte는 거부한다. PCMBlock은 선언한 frame 수와 일치하는 경우만 수락한다. 빈 decoder 입력과 0-byte PCMBlock 불일치를 구분한다.
- quantization ties는 명시한 signed 정수 표다. VAD는 window에 신호가 하나라도 있으면 threshold를 넉넉히 초과하는 0/±0.5를 쓰고, frame 집합의 연결 성분·최소 길이·집합 팽창으로 기대 범위를 만든다. 실제 RMS 코드의 조건문을 복사하지 않는다. 정확 threshold 등호는 별도 full-scale fixture다.
- VAD ms→frame 변환은 Fraction의 floor(window)/ceil(minimum,padding)로 계산한다. rate 경계 가족은 가장 긴 48-frame window에서 신호 한 개도 충분히 threshold를 넘도록 −40dBFS를 사용한다. 높은 rate에서 무조건 any-sample=voice라고 가정하지 않는다.
- resampling은 Fraction 시각 knot의 piecewise-linear 값과 ceil의 유리수 수학을 사용한다. affine 변환은 부가 metamorphic 관계다. float 결과 허용 오차는 수치 범위에 맞춰 명시하고 bandlimited/anti-alias 품질을 주장하지 않는다.
- clock은 trusted 품질·유효 timestamp/device의 명시 결정표, epoch 경계의 독립성, jump 이후 unknown의 영향과 taint의 새 epoch 해제를 기대값으로 둔다. arrival는 대체 oracle가 아니다. source frame/bytes와 metadata도 보존해야 한다.

## 무한/제한 생성 및 mutation 계획

Hypothesis는 integer 전체 범위·유한 float32·분할 및 rate/polyline을 deterministic bounded examples로 보강한다. 이는 무한 영역·모든 긴 시계 이력의 전수 증명이 아니다. 유한 5/6-frame 및 clock 3/4-block bound 밖은 미검증이다.

Q22-M01은 임시 source의 integer `round(clipped * scale)`을 truncation으로 바꿔 양의 odd tie assertion을 확인한다. Q22-M02는 VAD의 `>= threshold`를 `> threshold`로 바꿔 exact threshold assertion을 확인한다. 정상 사본 PASS·mutant 목표 assertion FAIL을 모두 확인하며 import/수집 오류는 검출로 세지 않는다. 원본 소스 hash와 사본 import 경로를 검사하고 workspace 제품·인덱스를 변경하지 않는다.

## 실행 결과

2026-11-15 Windows 11 build 26300 / CPython 3.13.1 AMD64 / Hypothesis 6.170.15에서 최종 선택 회귀 **3592 PASS / 8.95초**, skip/xfail 0이다. 새 파일은 유한 3391 row + ledger 1 + Hypothesis 3 + mutation 2 = 3397 pytest node이며 기존 네 파일의 195개와 묶었다. Hypothesis examples와 mutant 자식의 결과를 pytest node 수에 가산하지 않는다. 제품 결함은 이 실행에서 관측하지 않았으며 제품 파일을 수정하지 않았다.

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
$q22RunTemp = Join-Path $env:TEMP ('recoryn-q22-canonical-' + [guid]::NewGuid().ToString('N'))
.venv/Scripts/python.exe -m pytest tests/property/test_audio_case_space.py tests/unit/test_audio.py tests/unit/test_domain.py tests/integration/test_native_independent.py tests/property/test_pcm_storage_oracle.py -q -p no:cacheprovider --basetemp $q22RunTemp -W error::ResourceWarning --tb=short --capture=tee-sys --hypothesis-show-statistics
.venv/Scripts/python.exe -m ruff check tests/property/test_audio_case_space.py
.venv/Scripts/python.exe -m ruff format --check tests/property/test_audio_case_space.py
$env:MYPYPATH = 'src'
.venv/Scripts/python.exe -m mypy tests/property/test_audio_case_space.py
```

실제 basetemp는 `C:/Users/gangd/AppData/Local/Temp/recoryn-q22-canonical-37618aff827a4e71afd9718d7db3317f`다. Ruff lint·format 및 strict mypy 1파일은 PASS다. 처음 mypy는 MYPYPATH 없는 editable import 경계와 새 시험 두 타입 표기를 지적했다. 환경 경로와 새 시험 타입만 수정한 뒤 통과했으며 제품·공용 config의 예외 처리는 추가하지 않았다.

| 가족 | 닫힌 분모 | 실제 유일 row ID | 누락 | 중복 |
| --- | --- | --- | --- | --- |
| pcm_partition | 1008 | 1008 | 0 | 0 |
| byte_shape | 160 | 160 | 0 | 0 |
| quantization | 72 | 72 | 0 | 0 |
| float_nonfinite | 36 | 36 | 0 | 0 |
| vad_patterns | 1536 | 1536 | 0 | 0 |
| vad_equal | 2 | 2 | 0 | 0 |
| vad_rate_rounding | 72 | 72 | 0 | 0 |
| vad_guards | 270 | 270 | 0 | 0 |
| rate_guards | 64 | 64 | 0 | 0 |
| sample_guards | 35 | 35 | 0 | 0 |
| clock_cube | 120 | 120 | 0 | 0 |
| clock_taint | 16 | 16 | 0 | 0 |
| 합계 | 3391 | 3391 | 0 | 0 |

`test_finite_case_ledger_matches_closed_denominators_and_unique_executed_ids`가 최종 `Q22_CASE_SPACE` JSON을 출력했다. PCM의 실제 block 입력 signature도 1008개 유일했다. 이는 명시한 family-tagged 시험 프로토콜의 합이며 제품의 모든 가능한 입력 공간을 3391개로 축소했다는 주장이 아니다. byte_shape의 decoder 수락/거부는 96/64, 선언 PCMBlock은 32/128이다. vad_guards는 유효 3/거부 267, rate_guards는 유효 4/거부 60이며 다중 무효 행도 그대로 실행했다.

작성 중 최초 3341 PASS와 중간 3608 PASS는 별도 snapshot이다. self-review에서 PCM singleton packet/fragment의 동일 입력 alias 16개를 확인해 canonicalization하고 실제 입력 signature 검사를 추가했다. 64채널의 식별 가능한 base-6 신호와 rate-rounding 72행도 보강했다. 이전 실행 수치를 현재 분모의 실행 증거로 재사용하거나 더하지 않는다.

### 생성 시험 관측

| node 축약 | 설정 bound | 관측 passing / failing / 엔진 invalid |
| --- | --- | --- |
| test_generated_integer_full_range_partition_round_trip | 각 integer format의 허용 값 범위, channels 1..4, frames 1..16, 모든 cut mask를 생성 영역으로 포함, max_examples 120 | 120 / 0 / 11 |
| test_generated_finite_float32_preserves_ieee_bytes_and_signed_zero | 유한 float32, 길이 1..16, max_examples 100 | 100 / 0 / 50 |
| test_generated_resampling_matches_rational_knots_and_affine_transform | 0..20개 dyadic samples, rates 1..64, affine scale −1/0.5/2와 shift −8..8, max_examples 120 | 120 / 0 / 20 |

세 시험 모두 `derandomize=True`, `database=None`, `deadline=None`이다. Hypothesis의 invalid는 내부 생성 폐기 통계이며 제품이 받아 거부한 입력 수가 아니다. 이 통계를 유한 거부 행을 제외하는 근거로 사용하지 않았다. 특히 비유한 float는 생성 시험이 아닌 별도의 raw IEEE 36행 및 sample_guards에서 검사한다. 유한 큰 공간의 표본 또는 제한된 생성이므로 전수 증명이 아니다. resampler의 수치 오차 한도는 해당 작은 신호 범위에서 absolute/relative 각 1e-12이며 음질·anti-alias·실장비 정확도 보장이 아니다.

### 격리 mutation 관측

| named mutant | 정상 사본 | 변이 사본 | 목표 node / assertion |
| --- | --- | --- | --- |
| Q22-M01_TRUNCATE_TIES | 1 PASS, exit 0 | 1 FAIL, exit 1 | test_integer_ties_clipping_and_channel_identity[Q22-quantization-s16le-1-pos_odd_tie] / Q22_ROUND_TIES_EVEN |
| Q22-M02_DROP_THRESHOLD_EQUALITY | 1 PASS, exit 0 | 1 FAIL, exit 1 | test_vad_threshold_equality_is_inclusive[Q22-vad_equal-f32le-2] / Q22_VAD_EQUAL_THRESHOLD |

두 실패 모두 실제 AssertionError이며 import/수집 오류가 아니다. child는 `sys.executable -I -c ...`로 실행하고 임시 copied src를 먼저 넣은 뒤 processing.__file__이 해당 사본 아래인지 검사한다. 임시 pytest config와 정확한 위 leaf node만 실행하므로 mutation 시험 자체를 재귀 실행하지 않는다. 일반 파일 실행에는 이 bounded harness 두 개가 포함되며 child 4회는 정상/변이 각각 두 번뿐이다. pytest plugin autoload·부모 coverage/PYTHONPATH 전달을 끄고 cache-off/각 child 고유 basetemp/ResourceWarning-error를 유지했다.

실행 증거는 위 basetemp 아래 `test_named_mutant_is_killed_by0/`와 `...by1/`의 mutation.json, normal/result.txt, mutant/result.txt다. 원본 processing SHA256은 두 검사 전후 `ec826df3cb12e12f92d2e60f14a33a0a6951baf20993c29d4832fc0922dee6b6`으로 같았다. M01 사본 hash는 `8aa02d405f2c5100b1597de367ccc3e72f15abcebe91949dd783250342cba8e8`, M02 사본은 `05ffeb67725759b9e093b35933e34b0853ebe456bd39ae5cc292559a34b0ac1c`다. 이 두 mutant의 검출을 프로젝트 전체 mutation coverage로 표시하지 않는다.

### 동결 입력과 제한

| 파일 | SHA256 |
| --- | --- |
| tests/property/test_audio_case_space.py | B52B3B7E75A86DF2B84CC215D1510ABF802F512D5EEACE18F2B55D85C2A99E2E |
| src/recoryn/audio/processing.py (읽기 전용) | EC826DF3CB12E12F92D2E60F14A33A0A6951BAF20993C29D4832FC0922DEE6B6 |
| src/recoryn/audio/alignment.py (읽기 전용) | 56EA82F997ECC395BE30EAE8BAE66BE8047D5D3B15B032846B974C2A1A24B6ED |
| src/recoryn/domain/__init__.py (읽기 전용) | D39B8F48E4F834656CBB204593C021F50CAD4281E40EC7F96F9DAA278CEC6968 |

현재 HEAD는 Q-P01 정책 commit 29e18b28d137f9478a139ec28ef086bb6d36e0d3이며 runtime 기준은 30703fe와 같다. src의 현 diff는 없다. 이 실행은 아직 untracked Q22 시험 파일을 대상으로 한 작성자 working-tree 검증이다. Q21/Q23/Q24의 다른 dirty 시험은 실행 목록에 넣지 않았다. Q-P02의 정확한 stage/commit tree 검증·선행 CI·commit/push는 root가 확인하며 이 결과로 대신하지 않는다.

Q24 독립 검토와 root 통합은 대기 중이다. 작은 정수 대표치·frame bound 밖, 모든 긴 clock 이력·float64 전체·장치/OS/실제 음성·VAD 탐지 품질·실모델·실서비스·license·G3/G4는 이 유한/생성 시험으로 통과시키지 않는다. 작업자 Git 조작·추가 위임·비밀/계정 접근·실제 녹음/weights 다운로드는 수행하지 않았다.
