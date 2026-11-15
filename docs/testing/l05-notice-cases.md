# L05 고지 완전성 경우의 수

2026-11-15, 작성 C00. 배정 L05 / push L-P05. 근거는 [라이선스 검토 L01](../implementation/license-review.md)의 D8이다. 이 문서는 시험 설계와 분모를 정의하며 통과 결과는 [L 결과](../implementation/license-results.md)에 기록한다.

## 요구사항과 위험

- **고지 누락:** 배포물 안에 정적으로 들어간 제3자 코드의 저작권 표시나 라이선스 원문이 빠지면 고지 의무 위반이다. 예로 Qt 내부의 zlib·FreeType·libpng·libjpeg, CTranslate2 내부의 Intel·oneDNN·NVIDIA·spdlog가 있다.
- **원문 변형:** 원문이 바뀌거나 출처를 추적할 수 없으면 고지의 근거가 사라진다.
- **허위 표시:** 배포하지 않는 구성요소를 고지하거나, 미확인 조건을 확인된 것처럼 적으면 안 된다.
- **필수 문구:** 특정 문구를 문서에 넣어야 하는 라이선스가 있다. FTL은 FreeType 크레딧, IJG는 libjpeg 문장을 요구한다.

## 고정 원문 T

- **SOURCES.json 대조:** 모든 원문 파일의 bytes 수와 SHA-256이 SOURCES.json과 일치한다.
- **목록 완전성:** 디렉터리의 고지 원문(매니페스트 JSON 5종 SOURCES·native-map·qt-third-party·ct2-native·corresponding-sources 제외, L05-03)과 SOURCES 목록이 정확히 같은 집합이다. 고정되지 않은 원문도, 원문 없는 고정 항목도 없다.
- **URL:** 모든 출처 URL은 https다.
- **줄바꿈 고정:** 새 하위 폴더 `qt/**`·`intel/**`·`onednn/**`는 `-text`로 줄바꿈 변환을 막는다.
- **빌더 snapshot:** 빌더 입력 snapshot은 중첩 폴더의 확장자 없는 원문(예 `qt/qtbase/src/3rdparty/zlib/LICENSE`)도 bytes 그대로 포함한다.
- **조사 출처 재확인:** 원문은 L05 조사에서 tag의 git blob과 대조한 사본이다. C00이 zlib·FreeType·tlsf.h·oneDNN LICENSE와 qtbase 소스 SHA-256 sidecar를 다시 내려받아 같은 hash임을 확인했다.

## Qt 귀속표 Q

- **분모:** 47행이다. Qt 6.12.0 tag의 qt_attribution.json은 88개 파일에 103개 고유 (repo, Id) 행이 있다. 이 중 실제로 동봉한 모듈·플러그인의 Windows 빌드에 들어가는 46행을 포함하고 57행을 제외했다. 여기에 qtsvg REUSE.toml이 명시한 XSVG 파생 코드 1행을 더했다(L05-03).
- **행 조건:** 행마다 (repo, id)가 유일하고, SPDX 식은 정규형 그대로이며, 저작권 줄이 비어 있지 않고, 원문 파일이 모두 고정되어 있다. `None`·`null`·`N/A`·공백 같은 placeholder는 저작권 줄로 인정하지 않는다(L05-04). 처음에 libjpeg 행이 `None` 한 줄이었다. 지금은 고정한 `COPYRIGHT.txt`의 15줄을 그대로 쓴다.
- **손으로 적은 기대행 13개:** 라이선스 식과 들어가는 파일을 확인한다. zlib·PCRE2·FreeType·HarfBuzz·libpng·libjpeg·PSL·wintab·libtiff·libwebp·dr_libs·tlsf·XSVG다.
- **부재 12개:** 배포하지 않는 구성요소는 표에 없어야 한다. FFmpeg 계열 3, signalsmith, pffft, eigen, resonance-audio, opengl-es2-headers, sqlite, forkfd, pixman, libdbus다.
- **ES2 제외(L05-02):** `opengl-es2-headers`는 처음에 보수적으로 넣었다. 검토에서 미확인 상태가 NOTICE에 드러나지 않는다는 지적을 받아 근거로 판정했다. 동봉 Qt는 `QOpenGLContext.openGLModuleType()`이 LibGL인 desktop OpenGL 빌드다. Qt 6은 Windows에서 EGL과 OpenGL ES를 지원하지 않는다. 동적으로 고르는 것은 desktop OpenGL 구현뿐이다. 따라서 opengles2 기능과 `qopengles2ext.h`는 컴파일되지 않는다. 처음에는 "동적 OpenGL 미지원"이라고 잘못 적었고, L05-02 재확인에서 정정했다. 같은 Khronos 원문과 저작권은 opengl-headers 행으로 남는다.
- **libjpeg 위치(L05-01):** `qjpeg.dll`과 `qtiff.dll` 두 곳이다. 둘 다 `libjpeg-turbo version 3.2.0` 문자열이 있고 JPEG DLL을 import하지 않는다(libtiff의 JPEG 압축).

## 생성 G

l03 후보(PySide6_Essentials 포함)에서 다음을 확인한다.

- **행별 확인:** 47행 각각에 대해 NOTICE의 머리줄(이름·버전·SPDX·들어간 파일), 모든 저작권 줄, `licenses/Qt-third-party/` 아래 사본의 bytes 동일성을 본다.
- **필수 문구:** FreeType 크레딧, IJG 문장이 있다. PSL의 MPL-2.0 Source Code Form 위치(code.qt.io의 qtbase libpsl 폴더, v6.12.0)도 있다.
- **소스 위치:** 정확한 upstream 소스 archive 5개가 URL과 SHA-256으로 적혀 있다.
- **Microsoft:** 공식 재배포 페이지 URL과 "licensed Visual Studio users" 조건이 있다.
- **SBOM:** Qt 제3자 구성요소 47개가 각각 라이선스 식을 갖는다. NOTICE의 패키지 목록에 NOASSERTION 행으로 중복 표시되지 않는다.
- **gate:** `TEXTS_INCLUDED_UPSTREAM_SOURCES_RECORDED_HOSTING_DECISION_REQUIRED`다.
- **Qt가 없는 후보:** Qt 절과 사본을 만들지 않는다.

## 거부 R

- **QT_ATTRIBUTION_INVALID:** 고정되지 않은 원문 참조, 잘못된 SPDX, 빈 저작권, placeholder 저작권(`None`), 중복 행이다.
- **CORRESPONDING_SOURCES_INVALID:** download.qt.io가 아닌 소스 URL, 64자리가 아닌 SHA-256이다.
- 각 행은 독립적으로 거부되며 manifest를 만들지 않는다. 원문 변조는 기존 NOTICE_TEXT_HASH_MISMATCH 행이 담당한다.

## CTranslate2 내부 N

근거는 CTranslate2 v4.9.0의 Windows 빌드 스크립트와 실제 DLL의 문자열·import다. 빌드 스크립트는 CUDA 12.8.1, oneAPI 2025.3.0을 쓰고, 옵션은 WITH_DNNL=ON, WITH_CUDA=ON, CUDA_DYNAMIC_LOADING=ON, BUILD_CLI=OFF다.

- **분모와 행 조건:** 16행이다. 행마다 id가 유일하고, SPDX 식은 정규형이며, 저작권 줄이 있고, 원문이 고정되어 있다.
- **손으로 적은 기대행 13개:** 라이선스 식과 들어가는 파일을 확인한다.
  - Intel: oneMKL(ISSL), OpenMP(Intel EULA, `libiomp5md.dll`)
  - oneDNN·Xbyak
  - NVIDIA: CUDA runtime(NVIDIA EULA), cuRAND 장치 코드(NVIDIA EULA AND BSD-3-Clause)
  - CCCL: Thrust, CUB
  - 기타: CTranslate2, spdlog·fmt, cpu_features, avx_mathfun
- **부재 6개:** 컴파일되지 않거나 번들에서 제외된 것은 표에 없다. cutlass, cxxopts, googletest, ruy, cudnn, cublas다.
- **native 대응표:** `ctranslate2.dll`은 CONDITIONS_UNCONFIRMED다. 라이선스 식에 NVIDIA EULA와 Intel ISSL이 모두 들어 있다.
- **NVIDIA 헤더:** NVIDIA 독점 헤더의 소스(`curand_kernel.h`·`curand_philox4x32_x.h`·`curand_precalc.h`)는 재배포하지 않는다. 헤더가 사용자 문서에 넣으라고 요구하는 주석 1~78행만 bytes 그대로 발췌한다. 발췌본은 `#` 지시문 없이 주석으로만 되어 있다. NVIDIA 고지와 D. E. Shaw Research 고지를 모두 담고, NOTICE에 그대로 실린다.
- **배포 정책 충돌 방지:** 고지 원문 파일명이 배포 금지 정책에 걸리면 안 된다. 처음 `curand-notices.txt`라는 이름이 NVIDIA 런타임 제외 규칙(접두사 `curand`)에 걸려 `verify`가 후보를 거부했다. 이름을 `NVIDIA-cuRAND-notices.txt`로 바꾸고, 모든 고지 파일에 대한 시험 행을 추가했다.
- **생성:** 16행의 머리줄·저작권·원문 사본(`licenses/ctranslate2-native/`)을 확인한다. SBOM에 16개 구성요소가 있다. gate `nvidia_runtime_conditions`와 `intel_runtime_conditions`는 REVIEW_REQUIRED다.
- **거부:** 고정되지 않은 원문을 참조하면 CT2_ATTRIBUTION_INVALID다.
- **기존 oracle 유지:** 기존 L03-04 시험 문구 "is not yet confirmed"는 그대로 두고, NOTICE 문단을 이 문구가 한 줄에 오도록 다시 배열했다.

## 주장하지 않는 것

- 원문을 동봉한 것이 법률 승인은 아니다.
- 공개 배포 때 소스를 직접 호스팅할지, Microsoft·Intel·NVIDIA 조건을 충족하는지는 사용자 결정(G4)이다.
