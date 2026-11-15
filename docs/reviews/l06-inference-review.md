# L06 추론 동등성·장치 선택 독립 검토

작성 C00 / 독립 검토 recoryn-ml(w5:p4) / L-P06 / 2026-11-15.

상태: **REVIEW_READY / OPEN 3건(S2 1, S3 2)**. 쓰기는 이 문서 하나다. 제품·시험·설정·Git은 읽기 전용이다. 무작위 가중치 합성 Whisper만 실행하며 실제 음성·사전학습 weights·다운로드·GPU·외부 서비스는 사용하지 않는다.

## L06-I01 / S2 / OPEN — 비교 artifact의 identity·shape를 검증하지 않아 거짓 동등 보고 가능

지정 하네스 SHA256 `544dba5e4514ba6902a20a6d84685f7ba7698aea2aa5b4b25c902c25992b44bc`의 `compare`는 encoded 표본·토큰·점수만 비교한다. 기존 PyPI small JSON의 사본에서 float32/int8의 encoded_shape를 `[1,1,1]`로 바꾸고 encoded_sum에100을 더해도 max_abs_diff0/same_tokens=true/score_diff0으로 보고한다. 서로 다른 tensor라는 저장 증거를 무시한다. model hash/크기/seed, feature hash/shape, threads/backend 설정도 artifact에 없어서 동일 입력·동일 모델 비교임을 기계적으로 확인할 수 없다. `--size`와 기존 `--model`을 다르게 지정해도 파일이 있으면 그대로 재사용한다.

이는 제품 추론 결함이 아닌 검증 하네스 결함이다. encoded 표본의 비교를 full tensor 동등성으로 확대할 수 없다. small의192000개 중4174개, base의1536000개 중4096개만 저장한다. 비관측 위치의 차이는 알 수 없다. 최소 해결 조건은 모델/입력/구성 fingerprint와 shape·길이·finite 검사 및 불일치 거부, 표본 비교라는 보고 범위의 명시다. full tensor 최대 차이를 주장하려면 full 결과를 별도 artifact로 저장·대조해야 한다. int8 토큰 차이를 무조건0으로 강제하라는 요구는 아니다.

고정 반례는 TEMP `recoryn-l06-ml-724cee703eaf4e44b21b7929a9cc2d6a/evidence.json`의 `shape_and_sum_negative_control`에 있다. 명령은 `.venv/Scripts/python.exe -`에서 compare 모듈을 importlib로 읽고, `deepcopy(pypi-small)`의 두 필드만 바꿔 `compare(original,changed)`를 실행했다. seed 없음. 실제 원본 파일은 바꾸지 않았다.

## L06-I02 / S3 / OPEN — 실제 compute_type 전달 설명이 코드와 다름

결과 문서 L-P06은 “Recoryn은 compute_type을 지정하지 않아 [int16을] 쓰지 않는다”고 한다. 실제 `FasterWhisperProvider`는 CPU 기본 int8 / CUDA 기본 float16을 정하고 factory에 명시 전달한다. `app/inference.py`의 worker도 이 provider를 기본 인자로 생성한다. int16을 사용하지 않는 결론은 맞지만 근거는 provider 허용 목록에 int16이 없다는 점이다. 특히 CPU 기본이 int8이므로 MKL↔DNNL int8 차이는 사용하지 않는 경로로 치부할 수 없다. 설명을 CPU int8·명시 형식 전달·int16 미지원으로 정정해야 한다.

## L06-I03 / S3 / OPEN — 평평한 logits가 토큰 변경 원인이라는 설명은 증거보다 강함

기존 artifact는 선택 토큰의 집계 score만 기록하며 step별 top1/top2 margin을 저장하지 않는다. 따라서 “무작위 가중치는 logits가 거의 평평해 그래서 base int8 토큰이 달라졌다”는 인과 결론은 현재 증거로 확정할 수 없다. 독립 CPU/DNNL base int8 실행의 첫 hypothesis 12step에서 raw logit 범위는6.70~8.63, top1−top2 margin은0.0208~0.7455였다. “모든 logits가 거의 평평”이라고 일반화할 수 없으며 MKL의 같은 prefix에서 margin/perturbation을 대조한 결과도 아니다.

제안은 반올림·양자화 backend 차이의 가능성과 실제 관측(최대 절대차·일치/불일치)을 구분하고 원인 단정을 제거하는 것이다. 0.0623/4.14≈1.5%는 표본 최대 절대값으로 나눈 비율이며 token 또는 음성 품질의 허용 오차가 아니다. 같은 AMD DNNL 경로의 일치와 MKL 경로의 차이를 분리하고 실제 품질·Intel 성능 미검증을 유지해야 한다. 이 리뷰는 실제 음성 품질의 악화를 증명한 것이 아니다.

## 현재 재현

`.venv` 자체 빌드4.9.0+recoryn.cpu1로 small 합성 모델을 독립 재실행했다. 기존 PyPI 기본 DNNL artifact 대비 float32/int8 표본 차0, 토큰·점수 동일이었다. median encode는 float32 약0.0517s/int8 약0.0518s이며 단일PC 재현을 성능 보장으로 확대하지 않는다. base int8에서는 features를 −features로 바꾸면 full encoder 최대 차4.7083으로 입력에 반응했다. 실제 conv/encoder 경로를 실행했으며 generate도 decoder attention/GEMM/score 경로를 실행한다. 다만 이것이 전체 faster-whisper 기능·모든 backend·모든 입력의 동등성 증명은 아니다.

위 TEMP의 cpu-small.json/evidence.json에 결과·모델/feature hash를 보존했다. 장치 정책의 독립 matrix와 최종 hash·회귀·한계는 마감 시 후단에 기록한다.

## 최종 대상·증거 연결

AGENTS·onboarding·L06 배정과 인계, workflow/quality/case-space/push 단위, D9와 L-P06 E/D/결과를 대조했다. 기존 원본 불변·AI/녹음 독립·기본 무전송·Credential Manager·작성자/검토자 분리는 유지한다. 지정 파일 hash는 검토 전후 동일했다.

| 읽기 전용 대상 | raw SHA256 |
| --- | --- |
| scripts/compare_ctranslate2_builds.py | 544dba5e4514ba6902a20a6d84685f7ba7698aea2aa5b4b25c902c25992b44bc |
| src/recoryn/transcription/adapters.py | 129b8db5496152159688b096c0a540fb49fc6b0ac4f9316b53613ce39bd08474 |
| src/recoryn/transcription/__init__.py | c4a906a106493ceab6e82bebc2c503155280c4ae18cbc8c5b9a1ff05c6057bd6 |
| src/recoryn/ui/ai_bridge.py | ef7824f4dcec667235fefe6fe608980ef8313b68e8937adef33f9af619efed7a |
| tests/unit/test_providers.py | f804e969598143c0a86fc7cdb5f669faf5952a4f152e50da6aaad46b2fce80a2 |
| docs/testing/l06-ctranslate2-cpu-cases.md | 5e94e93116ac75a6ffcdb1fc36368f72f3eb8739938535b5a62dd9b4356b75a4 |
| docs/implementation/license-results.md | a3b183eb392f7716b6cb2f696dd37f7ee9a89df4d8e5d2c67bac0a7229b085ea |

증거 root는 `C:/Users/gangd/AppData/Local/Temp/recoryn-l06-ml-724cee703eaf4e44b21b7929a9cc2d6a`다. `cpu-small.json`/`second-env-small.json`은 각 자체 빌드 환경의 새 실행, `evidence.json`은 원 반례·base 입력 감도·logits, `comparison-matrix.json`은 저장된6개 artifact의 hash와8개 비교 cell, `policy.json`은 실제 UI 경로60행, `features.json`은 실제 합성 모델 기능 probe다. 원 PyPI 환경을 새로 설치·실행한 것으로 쓰지 않으며 기존 artifact를 사용했다.

실제 새 실행 명령:

```powershell
.venv/Scripts/python.exe scripts/compare_ctranslate2_builds.py --model build/ct2-compare/model --threads 4 --out <evidence>/cpu-small.json
build/ct2-cpu-env/Scripts/python.exe scripts/compare_ctranslate2_builds.py --model build/ct2-compare/model --threads 4 --out <evidence>/second-env-small.json
```

두 환경 모두4.9.0+recoryn.cpu1, float32/int8 표본·토큰·점수 동일이었다. 독립 base 실행은 int8 encoder 전체와 generate를 실제 실행했고 모델 SHA256 `94ab3dc9c11e192ed47de7d0aefab10887d2347ab2d09d5d1d3147d5235ce100`, seed7 feature SHA256 `85f08b222a4fcdb7398fde72aa643b1a9dbba9f8cd16704da81f8c4e2c5718e1`를 기록했다.

기존 artifact의 독립 비교 분모는 **2크기 ×2참조backend ×2정밀도 =8 cell**이며 실제 유일 ID8/누락0/중복0이었다. 표본 최대 차는 MKL 대비 small/base float32 1.4305e−6/4.52995e−6, int8 0.0130738/0.0623109였고 base int8만 토큰이 달랐다. 기본 DNNL 참조는 네 cell 모두 차0/동일 토큰이었다. I01에 따라 이 값은 full tensor 최대 차이가 아니다. 보관 artifact 계산과 새 추론 실행을 구분하며8개를8번 새 모델 추론이라고 부르지 않는다.

## 하네스가 실제 검사하는 경로와 경계

설치된 CT2 WhisperSpec/attention spec과 실제 실행을 대조했다. encoder의 conv1/conv2와 transformer attention/FFN, decoder self/cross-attention·projection 및 생성 score 경로를 실행했다. 입력 부호 반전의 full encoder 차4.7083으로 입력 감도도 확인했다. softmax·score 경로의 수치 결과는 생성 토큰·score로 간접 관측하며 primitive별 오차를 분리 측정한 것은 아니다.

그러나 seed1개, batch2, mel80, head4/8, d_model64/512, 두 layer 구성과 제한된 prompt/greedy 길이의 합성 공간이다. beam5·no_speech·기본 suppression은 별도 probe로 실행했지만 공식판과 수치 대조하지 않았다. 어휘64 모델의 `is_multilingual=False`이고 detect_language는 `detect_language can only be called on multilingual models`로 거부됐다. 이 거부는 자체 빌드의 다국어 기능 제거 증거가 아닌 fixture 한계다. 다국어 감지·mel128·alignment·전체 faster-whisper fallback/타임스탬프·긴 context와 실제 품질은 NOT_RUN이다.

실제 지원 compute type은 float32/int8/int8_float32다. 세 형식에서 encode→beam5 generate, suppression, no_speech score가 동작했고 batch2의 score가 유한했다. CPU float16/int8_float16 요청은 efficient computation 미지원으로 거부됐다. 보관한 PyPI 기본 AMD 지원 목록도 같은3개이므로 새 회귀로 판정하지 않는다. MKL 강제의 추가 int16은 provider에서 허용하지 않는다. CUDA 전체는 의도적으로 배제했고 별도 L-P07·GPU 검증이 필요하다. 이 probe는 실제 학습 Whisper weights를 사용하지 않았다.

## 장치 선택 D 독립 분모·판정

**3정책 ×4런타임 상태 ×5GPU 경계 =60행**을 실제 `DesktopAI._transcribe` 경로에서 고정 fake로 실행했다. 정책은 CPU_ONLY/GPU_ONLY/GPU_WITH_CPU_FALLBACK_ALLOWED, 런타임은 count0/count1/driver exception/missing module, GPU pool은 empty/인덱스1만/인덱스0 메모리 threshold−1/exact/+1이다. threshold는 요구1GiB+headroom512MiB다. actual60/unique60/missing0/duplicate0이며 결과를 `policy.json`에 기록했다. 런타임 probe 자체4행과 이 합성 교차60행은 별도 분모다.

모듈 import/GPU discovery/LocalSTTProcess/service를 fake로 바꾸고 실제 하드웨어·자식·모델 실행을 하지 않았다. production policy·필터·ResourceScheduler는 그대로 실행했다. CPU_ONLY는 runtime import·GPU probe 모두0회다. 런타임 불가/부재/예외에서 fallback은CPU, GPU_ONLY는 RESOURCE_GPU_UNAVAILABLE이었다. count1이며 인덱스0 exact/+1일 때만cuda를 골랐다. 인덱스1만 있으면 의도된 GPU0 바인딩에 따라 GPU_ONLY 거부/fallback CPU였다. GPU pool을 실제 장치로 탐지한 증거가 아니다.

이 범위에서 새 장치 정책 결함은 없었다. count>0은 모든 CUDA 라이브러리·모델·메모리·드라이버 작업 성공을 보장하지 않으며 그 후 모델 실패의 자동 CPU 재시도까지 검증한 것은 아니다. CPU 전용 번들에서 count0을 반환하는 실제 런타임도 확인했다.

## 관련 회귀·한계·인계

관련 기존 시험 **144 PASS / 0.93s**:

```powershell
$l06Base = Join-Path $env:TEMP ('recoryn-l06-regression-' + [guid]::NewGuid().ToString('N'))
$env:QT_QPA_PLATFORM = 'offscreen'
.venv/Scripts/python.exe -m pytest tests/unit/test_providers.py tests/unit/test_models.py -q -p no:cacheprovider --basetemp $l06Base -W error::ResourceWarning --tb=short
```

초기 TEMP feature driver에서 반환 속성 `logits_vocab`를 잘못 읽은 오류와, policy driver의 importlib mock 순서 오류가 있었다. 올바른 `logits` 속성과 object patch로 고친 실제 재실행만 증거로 사용한다. detect_language 거부는 위와 같이 미검증으로 남긴다. 오류를 제품 결함이나 통과 case로 세지 않는다. pytest 수와60개 driver assertion/8 artifact cell을 합산하지 않는다.

float32의 작은 오차와 이 AMD DNNL 기본경로의 일치는 선언한 합성 조건에서의 수치 근거다. Intel MKL→DNNL 기본 int8 경로 변경의 실제 음성 품질 허용 여부는 아직 입증하지 못했다. L06 CPU 빌드의 개발 통합과 실제 음성 품질/G3/G4 수락을 구분하고 I01~03 수정 뒤 같은 검토자가 새 hash로 재확인해야 한다. 실제 Whisper 모델·다운로드·실음성·유료 호출·실GPU·외부 서비스·추가 위임·제품/시험/설정/Git 수정은 없었다.

**REVIEW_READY — OPEN: L06-I01(S2), L06-I02(S3), L06-I03(S3). 최종 수락·수정 배정·Git·CI는 단일 오케스트레이터 C00 책임이다.**


## L06 ??? ? I01~I03 (2026-11-15)

C00 ?? ???? ?? ?? ???4015e350?? bytes? ???? ? ?? ????. ?? ??? compare ???? hash? **0c6ab61e53ecf638b1f7eeb2a6ca9008b20d9629599684b6e8f1de128284c70b**?. ?? ????2d0f288e?? ?? ?? ?? ??? ??? ?? ? ?? hash?? ??? ????. ?? ??? b07c283faa70142d26ca91e91f3a014f4e0f27dc0b4fd1e43fb15499d478aade, ?? ??? ef8db6662d3449d23be1106d6c6d39df5bfba48967ea9e5ccd8a552988541b26, case ???53c6cab6600d9e3fd750dd975cd506a49a6d8d9af2b86ad57870f6842e77d630?? ?? hash? ????.

| ?? | ?? ??? | ?? |
| --- | --- | --- |
| I01/S2 | ??3???feature SHA/shape????prompt identity ??? ??, npz hash??? shape?finite ??? ?? ?? ??? ????. ? [1,1,1] ??? TEMP ??? ???? COMPARE_SHAPE_OR_FINITE_INVALID ??? ????. ?? ????? ??? flat index1? +0.25? ?? npz hash? ???? ?? ??? ???0.25? ????. ?? ??/identity/shape/NaN/npz?? **5 PASS**. | RECHECKED |
| I02/S3 | CPU int8/CUDA float16 ?? ??, int16? ?? ?? ?, Intel? ?? CPU int8 ??? MKL?DNNL? ??? ????? ? ???? ????. | RECHECKED |
| I03/S3 | flat logits ?? ?? ??, ?? margin ??? ?? ?????? ??? ????? ???/??/Intel ?? NOT_RUN? ????. | RECHECKED |

build/ct2-compare2?2???2???2??? **8 cell**? ? compare? ?? ?????. small192000/base1536000? ??? ?? ???? PyPI ?? ???4 cell? ?0/?? ?????. MKL base int8? ??0.0861/??0.0127? ?? ???? ???? ?? ?? ?? PASS? ??? ???. ? PyPI ??? ??? ?? ??? ?? ? artifact ?? ??? ?? ??? ???. ?? small/base ?? ???? ?? full tensor ???? ???? ???.

??: `C:/Users/gangd/AppData/Local/Temp/recoryn-l06-recheck-2e3afd6143ac439486034d2d5bea80f3/evidence.json`. ?? pytest ??:

```text
.venv/Scripts/python.exe -m pytest tests/release/test_ct2_compare.py -q -p no:cacheprovider --basetemp C:/Users/gangd/AppData/Local/Temp/recoryn-l06-recheck-2e3afd6143ac439486034d2d5bea80f3/pytest-final -W error::ResourceWarning --tb=short
```

QT_QPA_PLATFORM=offscreen. ? ??? ?? TEMP ?? ??? ?? ??? ??5 setup error? ?? ?? ??? ?? ???. ?? ?? ?? ? ?? basetemp? ?? ???5 PASS? ?? ???. ?????????Git? ???? ???. ?? ????? weights??????GPU????? ???? ???. ?? ??? ???/?? ??/Intel ?? ? ??? ?? ????.

**REVIEW_READY / ?? OPEN 0?. I01~I03 ?? RECHECKED?? ?? CLOSED/??? tree ?? ???Git?CI? C00 ????. ?? hash? ?? script hash ??? C00 ?? ? ??? ????.**
