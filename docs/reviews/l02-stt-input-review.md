# L02 STT 입력 독립 검토

2026-11-15 / 작성 C00, 독립 검토 recoryn-ml(w5:p4) / L-P02.

상태: **REVIEW_READY — L02-STT-01/02 독립 RECHECKED, 현재 OPEN 0건**. 전단 OPEN은 발견 당시 이력이며 현재 판정은 후단 재확인이다. 제품·기존 시험·설정·Git은 읽기 전용이며 이 리뷰와 독립 시험 두 파일만 작성한다. 실제 음성·weights·모델 추론·네트워크·계정·유료 호출은 실행하지 않는다.

## L02-STT-01 / S2 / OPEN — 전처리 종료 후 취소를 모델 호출 전에 재검사하지 않음

`FasterWhisperProvider.transcribe`는 `prepare_whisper_audio(..., check=run.check)` 반환과 `_model.transcribe(samples, ...)` 사이에 `run.check()`가 없다. 16 kHz 항등 변환 및48 kHz 실제 변환 각각에서 전처리 반환 직전 cancel을 set하면, fake 모델은 cancel이 이미 set된 상태에서 호출된다. 최종 DTO는 CANCELLED지만 불필요한 실제 모델 실행은 시작할 수 있다. 모델 진입 후의 협력 취소 한계와 구분되는, 이미 관측 가능한 취소를 dispatch 전에 확인하지 않는 문제다. 외부 전송·원본 손실로 과장하지 않는다.

원 반례: `C:/Users/gangd/AppData/Local/Temp/recoryn-l02-handoff-race-eeb2b0c2424c48b9b5102e1cfc6d96df/evidence.json`. seed 없음. 300프레임 16-bit mono synthetic WAV를 두 rate로 만들고, monkeypatch한 adapter의 prepare 함수가 실제 원 함수를 실행한 뒤 cancel.set()하고 반환한다. fake transcribe는 호출 당시 cancel 상태만 기록하고 빈 iterator를 반환한다. 실제 두 행 모두 model_calls=1/cancel_already_set=true, DTO CANCELLED/source 동일이었다. 원 기대 `L02_NO_INFERENCE_AFTER_PREPROCESS_CANCEL` assertion은 FAIL했다. 실패 시험을 저장소 필수 시험에 남기지 않았다.

재현 명령은 `.venv/Scripts/python.exe -`의 고정 입력 driver였으며 원 반례의 핵심은 다음과 같다.

```python
original = adapters.prepare_whisper_audio
def at_handoff(*args, **kwargs):
    samples = original(*args, **kwargs)
    cancel.set()
    return samples
adapters.prepare_whisper_audio = at_handoff
result = provider.transcribe(STTRequest(path), ExecutionContext(cancel=cancel))
assert model_calls == []  # 현재 두 rate 모두 FAIL
```

제안/해결 조건: 전처리 반환 뒤 모델 호출 직전에 `run.check()`를 실행하고, 항등/비항등 두 rate의 cancel과 같은 위치의 deadline 만료에 대해 모델 호출0 및 안전한 CANCELLED/TIMEOUT을 검증한다. C00이 제품·기존 시험을 수정하며 검토자는 직접 수정하지 않는다.

원 반례 제품 raw SHA256: audio_input.py `ad14a371a2996192653430a30b10764bd7e98138e1fc8400e95a7ee6cb9f6a62`, adapters.py `e6751d18293c1f678e4120544cdc1c85821b334c0e1b0587bf4454bb022a2a99`.

## 진행 증거

독립 시험은 작은 신호의 각 출력 시각을 Fraction으로 직접 열거하고 scalar sin(x)/x 및 별도 Bessel 급수로 Kaiser window를 합산한다. 제품 phase table/offset/gather/einsum/출력길이 helper를 oracle로 사용하지 않는다. PCM은 수동 RIFF/JUNK 헤더와 정수 극값·Fraction 채널 평균, STT는 fake 모델로 입력 의미·시간축·원본을 확인한다.

초기 실행: 독립 시험과 `tests/unit/test_stt_audio_input.py`, `tests/unit/test_providers.py` 합계 **327 PASS / 2.48s**. 명령: `.venv/Scripts/python.exe -m pytest tests/integration/test_stt_input_independent.py tests/unit/test_stt_audio_input.py tests/unit/test_providers.py -q -p no:cacheprovider --basetemp C:/Users/gangd/AppData/Local/Temp/recoryn-l02-independent-b321cd71a44e4b999bea9b6de5872bf1 -W error::ResourceWarning --tb=short`, `QT_QPA_PLATFORM=offscreen`.

C00 mutation evidence는 일반 권한에서 ACL 실패 후 읽기 승격으로 실제 확인했다. M1~M6의 normal exit0 / mutant exit1과 failures>0/errors0, 현재 audio_input 정상 hash 일치를 확인했다. 앞선 pythonpath 문제 두 실행은 무효 이력이며 통과 증거에 포함하지 않는다. M6 패키징 판정은 별도 arch 검토자 범위다. 독립 mutant 재현 및 최종 분모·hash·한계는 후단에 기록한다.

## L02-STT-02 / S3 / 문서 표현

블록 경계표의 27개는 requested target label이며 실제 `(rate,N)` 고유 입력 분모와 구분해야 한다. 독립 정수 산식으로 전체27 label을 구성하면 **25 고유 입력**이다. 8 kHz는 wanted16383/16384가 모두 N8192→출력16384이고, 11.025 kHz는 같은 두 wanted가 모두 N11289→출력16384다. 따라서 이 두 rate의 BLOCK−1 출력을 직접 관측한 증거가 아니다. 모든 label이 실행돼도 이 두 쌍의 중복을 숨겨서는 안 된다. 제품 거부 행을 제거한 문제는 아니다.

검토자가 처음26으로 잘못 전달했고 독립 실행의 고유 집합 cardinality25를 확인한 직후 C00에 정정했다. 중간 문서 f3f28f7d…의26은 최종 수락 근거가 아니다. 해결 조건은27 label/25 고유 입력과 두 rate의 매핑을 명시하는 것이다. 또한 유한 tone의 −60 dB 감쇠는 aliasing의 절대0을 증명하지 않으므로 저지대역 표를 대표 tone 감쇠로 표현하도록 요청했다. 새 제품 결함이나 새 시험 증설 요구는 아니다.

## 독립 공간과 oracle 결론

| 가족 | 독립 분모 | 실제 관측 |
| --- | --- | --- |
| 작은 신호 scalar sinc | 7 rate × N={0,1,7,31} + 15999/16001 Hz의 N7 =30 | 30 ID 각각1회 |
| 수동 RIFF/JUNK PCM | W4 × C={1,2,64} =12 | 12 ID 각각1회 |
| decoder 거부 | garbage/float/width5/rate0/truncated =5 | 안정 code 정확 일치 |
| 전이대역 | (22050,6500)/(44100,7500)/(48000,8000)/(96000,8500) =4 | 직접 sinc 합과 일치 |
| fake Whisper 시간축 | (8000,7)/(11025,31)/(44100,31)/(96000,31) =4 | mono float32·시간축·duration·offset·원본 불변 |
| 취소 예외 identity | 1 | resampler 예외를 그대로 전파 |
| 오류 격리 | numpy 부재/decoder/backend =3 | 안전 code·원본 불변·canary 비노출 |
| 실제 ID census | 1 | 위 핵심30+12=42개와 독립 기대집합 일치, 중복0 |

독립 시험 최상위 합계는 **60**이다. 핵심42개의 Counter는 성공 실행 뒤 기록하며, 별도 고정 축으로 구성한 기대 ID와 누락/중복을 비교한다. 인자별 독립 곱을 주장하며 모든 축의 완전 직적 전수라고 주장하지 않는다. 기존 C00 decoder16/DC9/통과33/저지21/길이45를 그대로 복제하지 않는다. 독립 산식으로 통과는 2+3+7×4=33, 저지는 2+3+4×4=21, 길이9×5=45를 대조했다. Nyquist보다 높은 입력 tone을 제외한 것은 그 주파수를 해당 rate의 서로 다른 이산 tone으로 만들 수 없기 때문이며 제품 거부 입력을 면제한 것이 아니다.

직접 oracle는 각 j/16000<N/rate를 Fraction으로 열거하고, 무한 zero padding을 유한 support에서 scalar 합산한다. Kaiser의 I0는 수렴 급수, sinc는 scalar sin(x)/x를 사용한다. 위상별 DC 분모에는 입력 밖의 kernel weight도 포함해 경계 zero padding과 내부 DC 정규화를 구별한다. 제품의 phase table/offset/gather/einsum·output_length helper를 재사용하지 않는다. float32 반올림 허용 오차는 최대 절대/상대 6e−8(전이대역8e−8), decoder는 절대2⁻⁵¹다. 입력은 정수 modular열·고정 위상 사인이며 random seed나 sleep이 없다.

16k 항등 경로는 필터를 거치지 않는다. 6~9 kHz 전이대역은 임의 amplitude 하한/상한을 보장하는 계약이 아니며 위4점은 구현된 커널과 독립 합의 일치를 확인한 것이다. 짧은 신호의 경계에서는 zero padding 때문에 상수의 가장자리 감쇠가 있어도 내부 DC 유지 계약과 모순되지 않는다. ceil 출력 개수의 마지막 sample 시각은 원본 interval 안이고, 배열 길이/16000은 원 duration보다 최대1/16000초 미만 길 수 있다. provider의 processed_ms는 원본 ceil duration을 사용하며 segment의 offset/끝시각과 일치했다.

## 독립 named mutant

`L02-I-M5-CEIL-TO-FLOOR`: TEMP 전체 src 사본에서 `return -(-count * target // rate)`만 `return count * target // rate`로 변경했다. 독립 `test_small_signal_matches_direct_scalar_sum[r44100-n7]` 정상 **1 PASS**, 변이 **1 FAIL**이며 목표 `L02_SCALAR_LENGTH` assertion의 실제 shape2/기대3에서 실패했다. import/수집 오류가 아니며 TEMP import 경로를 child에서 검사했다.

증거: `C:/Users/gangd/AppData/Local/Temp/recoryn-l02-independent-mutant-c0c054bc99df4225ab62870269a93c72/{evidence.json,normal.log,mutant.log}`. child는 COVERAGE*/COV_CORE*/PYTEST* 환경을 제거하고 plugin 자동적재를 끈 `-I -B` Python에서 TEMP src를 명시 삽입했다. 정확한 확장 argv는 evidence.json에 있다.

```text
.venv/Scripts/python.exe -I -B -c <TEMP-import-guard-and-pytest-bootstrap> <TEMP>/src <TEMP>/test_stt_input_independent.py::test_small_signal_matches_direct_scalar_sum[r44100-n7] -c <TEMP>/pytest.ini -q -p no:cacheprovider --basetemp <TEMP>/<normal|mutant> -W error::ResourceWarning --tb=short
```

정상 audio_input hash는 ad14a371…a6f62로 전후 같고 독립 변이 raw hash는 `b33ab6a723c6c602de6d9d4612341728f56402845032fa90ca04938f76529c53`이다. C00 M5와 같은 의미 변이지만 raw bytes 동일이라고 주장하지 않는다. 독립 시험 사본 hash는 후속 import 정리 전이며 목표 oracle 본문·입력은 동일하다. 이 한 mutant 검출을 전체 mutation coverage로 확대하지 않는다. Git 인덱스를 수정하지 않았고 별도 index 관측 창을 요구하지 않았다.

## L02-STT-01 재확인

C00이 prepare 반환 뒤 모델 진입 직전에 `run.check()`를 추가했다. 원 handoff 반례를 동일 실제 변환 wrapper로 재실행하고 deadline 경계도 추가했다. **16000/48000 × cancel/deadline =4행 모두 모델 호출0, CANCELLED/TIMEOUT, 원본 동일**이었다. 최종 독립/관련 기존 시험 **331 PASS / 2.62s**와 구분되는 driver assertion4행이며 pytest PASS 수에 더하지 않는다. L02-STT-01은 **RECHECKED**, 최종 CLOSED 수락은 C00에게 맡긴다.

증거 root `C:/Users/gangd/AppData/Local/Temp/recoryn-l02-review-final-cdfd12f745664199aa3fbeb6d78ac8a9/evidence.json`은 pytest exit0, 아래 대상6개 전후 hash 동일, 실제42 핵심 ID·중복0 및4개 재확인 결과를 보존한다. 일반 실행 명령은 위 초기 명령과 같으며 basetemp만 이 root의 `/pytest`였다. QT_QPA_PLATFORM=offscreen, ResourceWarning-error와 cache-off를 유지했다. 331은 독립60 + C00 입력/기존provider271이며 최초327과 합산하지 않는다.

| 최종 실행 대상 | raw SHA256 |
| --- | --- |
| src/recoryn/transcription/audio_input.py | ad14a371a2996192653430a30b10764bd7e98138e1fc8400e95a7ee6cb9f6a62 |
| src/recoryn/transcription/adapters.py | 4d9e6b6ee39424b74c8771a3d2bc2454b62c9f021810ad2b488da2206ab81294 |
| tests/unit/test_stt_audio_input.py | a7ff955f80c7eb127d00579f9e988764e407c356dc51a3e9fd6df78a7c21d0a8 |
| tests/unit/test_providers.py | bc1c6ce1fcaf0d7af7377dbd7eb60814efdabeaccfa2e5990b401e3698012c83 |
| tests/integration/test_stt_input_independent.py | 85b37b62e14fdf89916b83a745ddd862d27a7d79eefa4e8305514a238493b48f |

실행 당시 case 문서는75464481…5918b였고, 후속 문서만의 정정은 별도 hash로 재확인한다. Ruff check/format 및 strict mypy 독립1파일 PASS. 전체 회귀·frozen 빌드/실제 faster-whisper 추론은 C00 게이트이며 이 결과로 대신하지 않는다. 설치된 faster_whisper/transcribe.py의 ndarray 분기·feature_extractor sampling rate 코드를 읽었으며 av.decode를 실행하지 않았다. 장시간·이상한 rate의 메모리/성능 상한, 모든 연속 주파수/입력, 실음성 품질·GPU·모델·G3/G4는 미검증이다. 원본/AI 저장 분리·기본 무전송·Credential Manager 계약을 변경하지 않는다.

## L02-STT-02 재확인 및 최종 인계

case 문서 최종 raw SHA256 **f6db276bc1d2b73e8e3f85f528537d8b10efa4097a2d7e39ce3ed8663f373e30** 전문의 R 표를 재확인했다. 27 label/25 고유 입력, 8 kHz와11.025 kHz의 두 중복, 8 kHz BLOCK+1이16386으로 매핑됨과 정확한 경계 길이 직접 관측의 제한을 명시했다. −60 dB는 대표 tone 감쇠이며 aliasing 절대0이 아님도 반영됐다. 독립 최소 입력 산식 `floor((wanted−1)×rate/16000)+1`의27 label/25 집합 계산은 위 final 증거 root의 `boundary-denominator.json`에 보존했다. 제품·시험 변경 없이 문서만 수정됐으므로 전체 pytest를 무의미하게 재실행하지 않았다. L02-STT-02 **RECHECKED**.

**REVIEW_READY / 현재 OPEN 0 (S0 0 / S1 0 / S2 0 / S3 0)**. L02-STT-01/02의 원 발견 이력은 유지한다. 허용된 독립 시험·이 리뷰 두 파일을 동결 제출하며 최종 CLOSED/통합/정확한 tree 회귀·Git·CI는 단일 오케스트레이터 C00 책임이다. 자기 작성 구현의 최종 승인이나 L01 법률 판단·G4 승인으로 확대하지 않는다.
