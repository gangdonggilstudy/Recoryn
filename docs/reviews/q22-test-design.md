# Q22 오디오·수치 시험 설계 독립 검토

2026-11-15. 작성 Q22 / 검토 Q24 / Q-P02. **REVIEW_READY — 지정 범위 추가 OPEN S0/S1/S2 0건.** Q00의 최종 hash 동결 신호를 받은 뒤 아래 판을 직접 실행·대조했다. 대상 제품/시험/문서는 읽기 전용이고 이 리뷰만 작성했다. Q24 자신의 보안 시험의 단독 승인이 아니다. 정확한 Q-P02 stage/commit tree·선행 CI·push 판정은 root에 남긴다.

## 동결 snapshot 및 독립 실행

| 파일 | raw SHA-256 |
| --- | --- |
| tests/property/test_audio_case_space.py | b52b3b7e75a86df2b84cc215d1510abf802f512d5eeace18f2b55d85c2a99e2e |
| docs/testing/q22-audio-cases.md | b67ae3cec27debe3e98713609bb6622c992efff748f3cecd1fe4c782bda69b1c |
| src/recoryn/audio/processing.py | ec826df3cb12e12f92d2e60f14a33a0a6951baf20993c29d4832fc0922dee6b6 |
| src/recoryn/audio/alignment.py | 56ea82f997ecc395be30eae8bae66be8047d5d3b15b032846b974c2a1a24b6ed |
| src/recoryn/domain/__init__.py | d39b8f48e4f834656cbb204593c021f50cad4281e40ec7f96f9daa278cec6968 |

이 다섯 파일과 `.git/index`의 hash map을 실행 전후 값별로 비교해 **변경 0**을 확인했다. 인덱스 hash도 양쪽 `f09828d68b4ab586204c5f8e4f1419b73b8395abfdc401f3e85ab346d64c9dfe`다. before/after JSON은 직렬화 형식이 달라 파일 bytes 자체가 같다는 주장은 하지 않는다.

Windows 11 build 26300 / CPython 3.13.1 AMD64 / pytest 9.2.0 / Hypothesis 6.170.15 / coverage 7.17.3. 고유 TEMP/cache-off/ResourceWarning 오류 처리로 **3591 PASS / 8.88s, skip/xfail 0**을 관측했다. 새 Q22 파일 3397개와 기존 audio/domain/native 세 파일 194개다. 작성자 3592 PASS 명령에는 기존 `test_pcm_storage_oracle.py` 1개가 추가로 있으며 이번 선택 목록에는 넣지 않았다. 서로 다른 선택 실행의 숫자를 같다고 쓰거나 합산하지 않는다.

## 유한 분모·거부 행·실제 ID

닫힌 분모를 손계산하고, TEMP의 별도 `independent_audit.py`에서 시험 모듈의 SPACES/DENOMINATORS/_ids를 import하지 않은 기대 ID 집합을 만들었다. 실제 JUnit의 Q22 node·실패/skip 태그·Counter를 대조했다. 본문의 차원 이름/값과 숫자 범위로 집합을 구성하며 생산 결과로 행을 걸러내지 않는다.

| family | 독립 분모 | 실제 유일 ID | 누락/중복/추가 |
| --- | --- | --- | --- |
| pcm_partition | 4×4×(1+31×2)=1008 | 1008 | 0/0/0 |
| byte_shape | 4×4×2×5=160 | 160 | 0/0/0 |
| quantization | 3×2×12=72 | 72 | 0/0/0 |
| float_nonfinite | 6×(1+2+3)=36 | 36 | 0/0/0 |
| vad_patterns | 32×2×2×2×3×2=1536 | 1536 | 0/0/0 |
| vad_equal | 2 | 2 | 0/0/0 |
| vad_rate_rounding | 3×3×2×2×2=72 | 72 | 0/0/0 |
| vad_guards | 10×3³=270 | 270 | 0/0/0 |
| rate_guards | 8²=64 | 64 | 0/0/0 |
| sample_guards | 7×5=35 | 35 | 0/0/0 |
| clock_cube | 3×2×2×5×2=120 | 120 | 0/0/0 |
| clock_taint | 2×4×2=16 | 16 | 0/0/0 |
| 합계 | **3391** | **3391** | **0/0/0** |

3391은 서로 다른 명명된 대표 부분 공간의 합이지 모든 계약 축의 거대한 직적이 아니다. 3397 pytest node는 여기에 ledger 1개·Hypothesis 3개·mutation harness 2개를 더한 값이다. Hypothesis examples나 child pytest 실행을 새 node 수에 더하지 않는다.

byte_shape는 decoder의 완전 frame 수락 96/부분 frame 거부 64, 선언 PCMBlock의 정확 길이 수락 32/불일치 거부 128을 모두 유지한다. vad_guards 270행 중 유효 3·거부 267, rate_guards 64행 중 유효 4·거부 60이며 다중 무효 입력도 실제 실행했다. bool을 정수 0/1로 편의 수락하는 행, nonfinite나 overflow 표본을 feasible에서 제거한 부분은 없다.

### PCM 1024 표현과 1008 API 동치류

6-frame의 다섯 cut 위치를 각각 선택하면 32 partitions다. raw 표기 공간은 format 4×channel 4×partition 32×mode 2=1024다. Q22의 사전 생성은 mask=0일 때만 packet을 canonical mode로 선택한다. SUT 성공/실패 뒤 임의 중복 제거를 하는 방식이 아니다.

독립 audit에서 **raw 1024개 모두를 별도로 구성**했다. 생산 encoder나 Q22 fixture 함수를 쓰지 않고 signed words/IEEE bytes로 payload를 만들고, 실제 PCMBlock의 **전체 to_metadata와 payload**를 signature로 삼았다. 결과는 992 singleton + 16개의 2원소 동치류 = 1008 API 입력이다. 중복 16쌍은 format×channel의 각 조합에서 mask=0의 packet/fragment 쌍뿐이었다.

무분할에서는 양쪽의 sequence=0, fragment_index=0, fragment_count=1, frame_count=6, payload·capture/arrival 시각·device frame·format·session/track/epoch가 모두 같다. mode 문자열은 API에 전달하지 않으므로 같은 입력에 다른 분기 정보가 숨지 않는다. 분할된 mode는 sequence 및 fragment metadata가 달라 같은 signature로 합쳐지지 않았다. canonical 선택은 raw 모든 동치류를 정확히 한 번 대표했다. 별도 실제 pytest의 PCM_INPUTS 1008 유일 검사, 원본 bytes/metadata·decode/encode·align 결과 assertion도 통과했다.

따라서 alias 16개를 전수 입력 중 빠진 거부 case로 취급할 근거가 없으며, 정책의 거부 입력 제외 금지와 모순되지 않는다. 다만 **raw 표기 1024개를 각각 별도 pytest node로 실행했다는 주장**은 하지 않는다. 최종 분모가 예전 계획 3407보다 16 작은 이유를 이 API 표현 동치로 한정한다.

## Oracle·기존 시험 대응 검토

- **PCM/IEEE:** 입력은 원 signed byte word·struct IEEE fixture이고 생산 encode 결과로 decode 기대값을 만들지 않는다. integer normalization은 Fraction의 dyadic 값, signed ties는 −2.5→−2/−1.5→−2/±0.5→0/+1.5→2/+2.5→2의 명시 표다. 64채널을 같은 신호로 복제하지 않고 base-6 채널 signature를 달리해 채널 혼합·순서 오류를 감지한다. ±Inf/qNaN/sNaN은 exponent-all-ones와 sign/mantissa의 독립 bit 집합으로 원시 입력을 대조했다.
- **분할:** 모든 인접 cut을 열거하고 packet/fragment의 frame 합·byte 합·시간 범위·원본 metadata를 확인한다. 기존 저장 property의 청크 복구/bytes 시험을 새 파일에서 복제하지 않고 decoder/encoder/alignment 프로토콜을 교차한다.
- **VAD:** window의 점유 frame 집합→연결 성분→minimum 필터→집합 팽창으로 기대 region을 만들고 생산 RMS/분기 코드를 호출해 기대값을 구하지 않는다. 0/±0.5 fixture의 RMS가 threshold와 충분히 떨어지는 조건을 검토했다. high-rate 최대 48-frame window의 한 voiced sample도 RMS≥0.5/√48>0.01이므로 −40dBFS의 binary occupancy oracle가 유효하다. 정확한 0dBFS 등호는 별도 full-scale fixture다.
- **ms rounding:** 11025/44100/48000Hz의 1ms window floor와 minimum/padding ceil을 Fraction으로 계산하며 speech 길이 −1/0/+1을 교차한다. window floor와 minimum/padding ceil을 같은 방향으로 처리하는 계산 복제가 아니다. 낮은 모든 VAD rate까지 열거했다는 주장은 하지 않는다.
- **Resampling:** Fraction 시간 knot와 독립 piecewise-linear 보간, 마지막 sample hold와 ceil 길이를 사용한다. affine 관계는 보조 property로 분리했다. abs/rel 1e-12는 작은 dyadic 신호와 해당 rate 범위에 한정되고 고품질 resampling/anti-alias 보장은 아니다.
- **Clock:** trusted 품질 두 종류와 timestamp/device 유효성, same/new epoch, ±jump의 명시 결정표를 대조했다. arrival는 900초의 별도 값으로 둬 source timestamp 대체 oracle가 되지 않는다. jump 뒤 invalid packet의 unknown과 새 epoch에서 taint 해제를 3/4-block bound로 검사한다. 구현 private predicate/fit 계수를 기대값으로 import하지 않는다.
- **기존 node:** 문서의 unit audio 극값/float/shape/VAD/clock, domain의 PCM shape 및 native resample·BR11 node가 실제 존재하고 해당 기존 시험이 이번 선택 회귀에서 통과했다. sample rate/type 거부와 VAD guard의 복합 부정은 ValidationError만 요구하며 계약에 없는 오류 문구 우선순위를 만들지 않는다.

관측 Hypothesis 통계는 integer 120 PASS/8 engine-invalid, float32 100 PASS/50 invalid, resample 120 PASS/20 invalid다. 작성자의 integer invalid 11과 다른 실행 관측이며 이 수치를 합치지 않는다. 모두 failing 0, 설정 max_examples 도달 종료다. engine-invalid를 제품 거부 행으로 세거나 유한 분모 제외에 쓰지 않는다. 유한 5/6-frame, clock 3/4-block, 생성 길이/rate 범위 밖은 전수 증명이 아니다.

## Named mutant 및 coverage/env 격리

| mutant | 정상 | 변이의 목표 관측 |
| --- | --- | --- |
| Q22-M01_TRUNCATE_TIES | 1 PASS/exit 0 | 양의 odd tie node `Q22-quantization-s16le-1-pos_odd_tie`: Q22_ROUND_TIES_EVEN **AssertionError**, 1 FAIL/exit 1 |
| Q22-M02_DROP_THRESHOLD_EQUALITY | 1 PASS/exit 0 | exact threshold node `Q22-vad_equal-f32le-2`: Q22_VAD_EQUAL_THRESHOLD **AssertionError**, 1 FAIL/exit 1 |

각 parent harness가 실제 정상·변이 leaf node만 선택하므로 mutant harness 자체를 child에서 재귀 호출하지 않는다. 생산 processing 원본은 위 hash로 유지됐다. mutant raw hash는 M01 `8aa02d405f2c5100b1597de367ccc3e72f15abcebe91949dd783250342cba8e8`, M02 `05ffeb67725759b9e093b35933e34b0853ebe456bd39ae5cc292559a34b0ac1c`다. 실제 result.txt에서 목표 메시지·AssertionError·정상 PASS·변이 FAIL을 읽고 import/collection 오류가 아님을 대조했다.

child는 `sys.executable -I`로 시작해 copied src를 수동으로 맨 앞에 넣고 processing.__file__이 사본 아래임을 검사한다. 별도 pytest.ini·cwd·basetemp를 사용하고 `COVERAGE*`, `COV_CORE*`, `PYTHONPATH`, `PYTEST_ADDOPTS`를 부모 환경에서 제거하며 plugin autoload를 끈다. 이 정적 구조뿐 아니라 **실제 부모 coverage를 켠 전체 선택 실행**에서 혼입을 검증했다.

coverage JSON의 파일은 repository `audio/__init__.py`, `alignment.py`, `processing.py` 세 개뿐이다. 실제 `.coverage`의 CoverageData.measured_files도 같은 repository 세 절대 경로였고 TEMP copied/mutant source는 0개였다. 따라서 이번 환경에서 Q23과 같은 child coverage 혼입은 재현되지 않았다. scoped audio coverage는 line 287/288=99.65%, branch 119/120=99.17%이며 전체 프로젝트 수치로 확대하지 않는다.

## 명령·증거 및 최종 상태

고유 증거 root: `C:\Users\gangd\AppData\Local\Temp\recoryn-q22-review-21f741b46d8c409ca22fbe55c96a2636`.

```powershell
$q22Review = 'C:\Users\gangd\AppData\Local\Temp\recoryn-q22-review-21f741b46d8c409ca22fbe55c96a2636'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:HYPOTHESIS_STORAGE_DIRECTORY = "$q22Review\hypothesis"
$env:COVERAGE_FILE = "$q22Review\.coverage"
.venv/Scripts/python.exe -m pytest tests/property/test_audio_case_space.py tests/unit/test_audio.py tests/unit/test_domain.py tests/integration/test_native_independent.py -q -s -p no:cacheprovider --basetemp "$q22Review\pytest" -W error::ResourceWarning --junitxml "$q22Review\result.xml" --hypothesis-show-statistics --cov=recoryn.audio --cov-branch --cov-report=term --cov-report="json:$q22Review\coverage.json" --tb=short
.venv/Scripts/python.exe "$q22Review\independent_audit.py"
.venv/Scripts/python.exe -m ruff check --no-cache tests/property/test_audio_case_space.py
.venv/Scripts/python.exe -m ruff format --no-cache --check tests/property/test_audio_case_space.py
$env:MYPYPATH = 'src'
.venv/Scripts/python.exe -m mypy --cache-dir "$q22Review\mypy" tests/property/test_audio_case_space.py
```

Ruff check/format 및 strict mypy 1파일 모두 PASS다. pytest.log와 JUnit, 독립 전체 ID/PCM 동치류 audit, before/after hash map, coverage 원자료/JSON, 두 mutation.json 및 normal/mutant result.txt는 이 TEMP 아래에 보존했다.

| 증거 root 상대 파일 | raw SHA-256 |
| --- | --- |
| pytest.log | 6d89e6c3e59de54b4a96af0ac1d4d206864467b50c4c45b1b4b372fed2629b12 |
| result.xml | 1b6bbbaeacb81f0cdfdf5dd6f9eb70a110772077aaf053403633188ce30ea252 |
| coverage.json | 72585af462b80944bacf50e7178e25979d2c4fd63ebb717379de9173f07c0ec4 |
| independent-audit.json | 895df7305d29f4af0050f7de1fa8b22c69c32dd1181d7c02766d2f4d1a10789e |

최종 판정은 **REVIEW_READY, 추가 OPEN S0/S1/S2 0건**이다. 실제 음성/장치·모델/서비스·품질/G3/G4는 미실행이다. 대상 작성자의 3592 PASS를 복사해 독립 실행으로 삼지 않았고, 다른 단위의 dirty 시험을 Q-P02 검증에 포함하지 않았다. 정확한 통합 tree의 필수 검사·stage/commit·원격 CI와 push는 root 책임이다. Q24 자신의 동결 보안 두 파일도 수정하지 않았다.
