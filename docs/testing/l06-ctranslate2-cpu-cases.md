# L06 CTranslate2 CPU 전용 자체 빌드 경우의 수

2026-11-15, 작성 C00. 배정 L06 / push L-P06. 근거는 [라이선스 검토 L01](../implementation/license-review.md)의 D9다. 이 문서는 시험 설계와 분모를 정의하며 통과 결과는 [L 결과](../implementation/license-results.md)에 기록한다.

## 요구사항과 위험

- **잘못된 빌드 재진입:** 번들에 PyPI 공식판이 다시 들어오면 L-P05에서 미확인이던 Intel·NVIDIA 조건이 그대로 돌아온다. PyPI 공식판에는 Intel oneMKL·OpenMP와 NVIDIA CUDA runtime·cuRAND가 들어 있다. 공식판과 자체 빌드는 이름(`ctranslate2.dll`)과 버전 4.9.0이 같아 겉으로 구별되지 않는다.
- **기능 저하:** 자체 빌드가 공식판과 다른 결과를 내거나 크게 느리면 전사 품질과 사용성이 떨어진다.
- **재현성:** 소스나 옵션이 바뀌어도 알아차리지 못하면 재현할 수 없다.

## 빌드 B (`scripts/build_ctranslate2_cpu.py`)

- **소스 고정:** 다음을 고정 commit과 대조한다. 하나라도 다르면 SOURCE_COMMIT_MISMATCH 또는 SUBMODULE_COMMIT_MISMATCH로 중단한다.
  - CTranslate2 `v4.9.0` = `a22ba1c6…`
  - CPU 빌드에 필요한 submodule 2개: cpu_features `8a494eb1…`, spdlog `76fb40d9…`. CUDA·CLI·시험용 submodule은 받지 않는다.
  - oneDNN `v3.1.1` = `64f6bcbc…`
- **옵션:** WITH_MKL=OFF, WITH_CUDA=OFF, WITH_CUDNN=OFF, WITH_DNNL=ON, OPENMP_RUNTIME=COMP, BUILD_CLI=OFF다. oneDNN은 STATIC·OMP·INFERENCE로 빌드한다. CTranslate2는 MKL이 없을 때 oneDNN의 `dnnl_sgemm`과 int8 GEMM을 쓰므로, 공식판처럼 CONVOLUTION·REORDER만 켜지 않고 전체 primitive를 켠다.
- **DLL 자체 검사:** 빌드한 `ctranslate2.dll`을 다음 기준으로 검사하고, 어긋나면 CPU_BUILD_CHECK_FAILED다.
  - import(일반·지연)에 `libiomp5md`·`cudart`·`cublas`·`cudnn`·`nvcuda` 접두가 없다.
  - 문자열에 CUDA runtime 진단·`cudaGetDeviceCount`·`nvcuda.dll`·`cublas64_`·Intel oneMKL 제품 문자열·`libiomp5md`가 없다.
  - `vcomp140.dll`(MSVC OpenMP)을 import한다.
- **wheel:** wheel에는 이 DLL과 VS `VC\Redist`의 `vcomp140.dll`을 넣는다. 버전은 `4.9.0+recoryn.cpu1`이다. 소스·DLL·vcomp·wheel의 hash는 `ct2-cpu-build.json`에 남긴다.

- **빌드 의존성 고정:** wheel 빌드 backend 의존성 4개를 버전과 SHA-256으로 고정해 받는다(`--require-hashes`). 대상은 pybind11 2.13.6, setuptools 84.2.1, wheel 0.48.0, packaging 26.3이다. 빌드는 그 폴더에서만 오프라인(`--no-index`)으로 설치한다. 처음 시도에서는 build isolation이 PyPI에 접속하다 일시적인 연결 재설정으로 실패했고, 다음에는 wheel 0.48.0이 요구하는 packaging이 빠져 실패했다.
- **컴파일 환경:**
  - setuptools가 MSVC를 찾지 못했다. 그래서 확장 모듈은 `vcvars64.bat`의 개발자 환경에서 컴파일한다.
  - 모든 컴파일에 `CL=/utf-8`을 준다. 이것 없이 만든 시험 wheel은 한국어 code page(cp949)로 소스를 읽어 docstring이 깨진 UTF-8이 되었다. 그 결과 import할 때 `PyType_Ready failed: UnicodeDecodeError`가 났다.
- **wheel import 확인:** 빌드한 wheel 자체를 풀어 import한다. import되는 파일이 그 폴더에서 왔는지, 버전이 `4.9.0+recoryn.cpu1`인지, `get_cuda_device_count()`가 0인지 확인한다. 하나라도 다르면 WHEEL_IMPORT_CHECK_FAILED다.

## 동등성 E (`scripts/compare_ctranslate2_builds.py`)

모델은 내려받지 않는다. Whisper 사양을 seed 고정 무작위 가중치로 채운 소형 모델을 쓴다. 차원은 d_model 64, 4 head, 인코더·디코더 각 2층, 80 mel, 어휘 64다. 같은 모델과 입력(2×80×3000)으로 공식판 환경과 자체 빌드 환경에서 각각 실행하고 비교한다.

- **비교 대상의 동일성(L06-I01):** 결과마다 모델 파일 3개와 입력의 SHA-256, 차원, prompt를 기록한다. 이것이 다르면 COMPARE_IDENTITY_MISMATCH다. 인코더 출력 전체를 npz로 저장하고 그 hash, shape([2, 1500, d_model]), 유한성을 확인한다. 어긋나면 COMPARE_ARRAYS_HASH_MISMATCH 또는 COMPARE_SHAPE_OR_FINITE_INVALID다. 비교는 표본이 아니라 모든 원소다. 이 거부 5행(정상, identity, 원 반례 [1,1,1], NaN, npz 변조)은 `tests/release/test_ct2_compare.py`가 합성 결과로 판정한다.
- **float32:** 인코더 출력 전체의 최대·평균 절대 차이를 잰다. greedy 생성 토큰은 같아야 하고, 점수 차이를 기록한다.
- **int8:** Recoryn이 CPU에서 실제로 쓰는 정밀도다. `FasterWhisperProvider`가 int8을 명시해 넘기고, int16은 허용 목록에 없다(L06-I02). 양자화 GEMM 구현이 달라(MKL과 oneDNN) 반올림이 다를 수 있다. 토큰 동일 여부, 처음 갈리는 위치, 차이를 그대로 보고한다. 토큰이 갈린 원인을 추정하는 내용은 관측과 분리해 적는다(L06-I03). 품질 허용치로 판정하지 않는다.
- **속도:** 같은 PC, 같은 스레드 수에서 인코딩 3회의 중앙값을 기록한다. 실제 크기에 가까운 차원(d_model 512, 6층)도 측정한다.
- **주장하지 않는 것:** 실제 음성과 실제 Whisper 가중치에서의 품질·속도는 모델 다운로드가 필요해 NOT_RUN이다.

## 배포 gate G

- **배포 정책:** `libiomp5md`를 금지 basename에 추가한다. 공식판 wheel이 빌드 환경에 남아 있으면 spec·TOC·`verify`가 거부한다.
- **빌더:** 설치된 ctranslate2 배포판 버전이 정확히 `4.9.0+recoryn.cpu1`이어야 한다. 아니면 BUILD_DEPENDENCY_VERSION_MISMATCH다.
- **pin(L06-01):** 리뷰된 산출물을 `packaging/ctranslate2-cpu.json`에 고정한다. 대상은 `ctranslate2.dll`·`vcomp140.dll`·`_ext.cp313-win_amd64.pyd`의 SHA-256이다. 빌더는 PyInstaller 실행 전 설치된 패키지를, 실행 뒤 번들 사본을 이 pin과 대조한다. 이어서 금지 import(일반·지연)와 문자열을 검사한다. 문자열은 대소문자를 무시하고 UTF-8과 UTF-16LE를 모두 본다. 하나라도 어긋나면 CTRANSLATE2_NOT_CPU_BUILD다. pin 파일 자체도 빌드 입력 snapshot에 들어간다.
- **빌더 검사 시험(L06-03):** 손으로 쓴 결정표로 판정한다.
  - import 표 8행: 정상, 대문자 LIBIOMP5MD, cudart(지연), nvcuda, cublasLt, cudnn, mkl_rt, vcomp 부재
  - 대소문자·UTF-16 표지 4행
  - 가짜 pefile로 일반·지연 import 결합과 해제 확인 1행
  - pin 일치·변조·누락 1행
  - pin 기록 손상 3행
  - 저장소 pin이 빌드 스크립트의 버전·vcomp hash·도구체인·commit과 일치하는지 1행
  - 이와 별도로 실제 PE 해석은 frozen 후보에서 PyPI DLL(위반 8)과 CPU DLL(0)로 확인한다.

## 장치 선택 D

번들 CTranslate2에는 CUDA가 없다. 그래서 GPU가 있는 PC에서 GPU 정책을 고르면 지금은 모델 로드가 실패하고, CPU 폴백 정책도 작동하지 않는다. 이를 막기 위해 `cuda_runtime_available()`로 설치된 CTranslate2의 `get_cuda_device_count()`를 확인한다. 0이거나, 오류가 나거나, 패키지가 없으면 GPU 후보를 비운다. 그 결과 GPU_WITH_CPU_FALLBACK_ALLOWED는 CPU로 동작하고, GPU_ONLY는 RESOURCE_GPU_UNAVAILABLE로 알린다. 분모는 4행이다.

| 상황 | 판정 |
| --- | --- |
| CPU 빌드(0) | False |
| CUDA 런타임(1) | True |
| 드라이버 오류 예외 | False |
| 모듈 없음 | False |

사용자가 받은 GPU 런타임을 실제로 쓰는 경로는 L-P07에서 다룬다.

## 고지 N

- **native 대응표:**
  - `ctranslate2.dll`: CPU 자체 빌드(oneDNN·cpu_features·spdlog/fmt·avx_mathfun·SIMD_Utils)로 DECLARED다.
  - `vcomp140.dll`: Microsoft 재배포 OpenMP로 REDISTRIBUTABLE_PROPRIETARY다.
  - `libiomp5md.dll`: 대응표에서 뺀다.
- **고지 원문:** Intel·NVIDIA·CCCL 원문과 ct2-native 행을 제거한다. 남는 행은 CTranslate2, oneDNN과 그 하위(Xbyak·ittnotify), spdlog, fmt, cpu_features, avx_mathfun, avx512_mathfun이다.
- **NOTICE:** 배포하지 않는 목록에 PyPI 공식판의 Intel·NVIDIA 코드를 적고, GPU는 사용자가 직접 받는다고 적는다(D10).
- **gate:** `intel_runtime_conditions`·`nvidia_runtime_conditions`는 `NOT_DISTRIBUTED_L01_D9`다.

## frozen 후보 F

- **구성:** 번들의 ctranslate2 배포판은 `4.9.0+recoryn.cpu1`이다. `libiomp5md.dll`과 NVIDIA 표지는 0이고, `vcomp140.dll`이 있다.
- **검사 통과:** native 전부 명시 귀속, import closure 미해결 0, smoke PASS다. smoke는 기존대로 ctranslate2 import·worker 시작·종료를 확인한다.
