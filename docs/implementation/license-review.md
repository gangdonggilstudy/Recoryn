# Recoryn 배포물 라이선스 검토와 개선 계획 L01

2026-11-15, 작성 C00(오케스트레이터). 사용자 지시: 오픈소스 중 무료로 쓸 수 없는 라이선스를 전수 검토하고 개선을 계획·진행한다. 기준 commit `0cf9cdd730eae4fccb9e67446f58ffa1ebb61439`(제품 source tree `21291eb8786d93bba9c8f7307b0cbaf05e7295ee`). 검토 대상은 로컬 ignored 개발 후보 `build/final-dev2-1794666063022/dist/Recoryn`(0.2.0.dev2)이다. **이 문서는 기술 검토이며 법률 판단·G4 승인이 아니다.**

## 판정 기준과 방법

"무료가 아닌 경우"를 서로 다른 세 축으로 구분한다. ① 사용료 또는 상용 라이선스 구매가 필요한 조건, ② 구체적 결합 근거가 있어 현재 배포 정책에서 제외하는 copyleft 결합(예: PyAV FFmpeg가 x264/x265를 import하는 경우), 또는 결합 조건을 아직 확인하지 못한 구성요소, ③ 저작권과 별도인 코덱 특허 확인 필요. GPL 의무는 구매 대가와 같은 사실이 아니며, 독립 저작물의 단순 동봉만으로 Recoryn 전체의 라이선스가 정해진다고 보지 않는다(GPLv3 §5의 집합물 구분, PyInstaller·GCC 런타임 예외). LGPL/MPL은 무상이지만 고지·소스 제공·교체 가능성 의무가 있는 약한 copyleft로 분리한다. 오픈소스가 아닌 배포 조건의 바이너리도 별도로 분류하되, 제작자 정보만으로 조건을 확정하지 않는다(L01-01 반영).

증거는 실제 배포 파일에서 얻었다. native 243개(EXE/DLL/PYD)의 PE 버전 정보와 import 표(pefile), 동봉 FFmpeg 두 벌의 `avutil_license()`·`avutil_configuration()`, 설치 배포판의 `License-Expression`/`License`/분류자, 후보의 `sbom.cdx.json`·`licenses/`·`NOTICE.txt`를 대조했다. 코드가 실제 import하는 Qt 모듈은 QtCore/QtGui/QtWidgets/QtMultimedia이며, faster-whisper는 PyAV를 `decode_audio` 함수 안에서만 사용하고 `numpy.ndarray` 입력에서는 호출하지 않는다.

## A. 배포 제외 대상 (GPL 단독·상용 필수·특허)

| 구성요소 | 근거 | 결정 |
| --- | --- | --- |
| `av.libs/libx264-*.dll` | x264, GPL-2.0-or-later(또는 상용). PyAV `avcodec-62`가 정적 import | D1 제외 |
| `av.libs/libx265-*.dll` | DLL 버전 정보 "Multicoreware: GPLv2 or commercial", HEVC 특허 | D1 제외 |
| `av.libs/libopenh264-*.dll` | 코드 BSD-2, H.264 특허. Cisco 특허 부담은 Cisco가 배포한 바이너리를 앱이 실행 중 받거나 사용자가 받는 경우에만 적용된다. PyAV가 빌드해 동봉한 이 파일은 해당하지 않는다 | D1 제외 |
| PyAV FFmpeg(`avcodec-62` 등) | `avutil_license()`는 "LGPL version 3 or later"이나 `--enable-libx264 --enable-libx265`로 구성되어 FFmpeg 문서상 결합물이 GPL이 된다 | D1 PyAV 전체 제외 |
| `Qt6VirtualKeyboard.dll`, `platforminputcontexts/qtvirtualkeyboardplugin.dll` | Qt Virtual Keyboard는 GPLv3 또는 상용만 제공(LGPL 없음). 코드 미사용 | D2 제외 |

Recoryn은 오디오 전용이므로 H.264/HEVC/영상 코덱이 필요 없다. 향후 영상이 필요하면 Cisco OpenH264를 사용자 동의 하의 명시 다운로드로 받는 방식이 기존 다운로드 동의 원칙과 맞는다. x264/x265는 Cisco 조건과 무관하다.

## B. 오픈소스가 아닌 배포 조건의 구성요소

아래 Intel 항목은 제작자 정보와 정적 포함 관측까지 확인했다. 적용 조건은 Intel이 해당 패키지에 동봉한 조건을 기준으로 하므로 원문을 확보하기 전까지 "무상 재배포 확정"으로 분류하지 않는다. LLVM upstream 라이선스도 이 Intel 바이너리의 조건을 대신하지 않는다.

| 구성요소 | 근거 | 결정 |
| --- | --- | --- |
| Intel MKL | `ctranslate2.dll` 내부 문자열 "Intel(R) Math Kernel Library"(정적 포함) | 유지 후보. 적용 조건 원문 확보 D5, 미확인이면 G4 OPEN D6 |
| Intel OpenMP `ctranslate2/libiomp5md.dll` | 버전 20250910, 제작자 Intel Corporation. `ctranslate2.dll`의 유일한 정적 비시스템 import | 유지 후보. 적용 조건 원문 확보 D5, 미확인이면 G4 OPEN D6 |
| NVIDIA cuDNN 9 `ctranslate2/cudnn64_9.dll` | 버전 정보 NVIDIA. `ctranslate2.dll`이 정적 import하지 않으며 CUDA runtime/cuBLAS는 미동봉 | D3 제외 |
| MSVC/UCRT (`vcruntime140*`, `msvcp140*`, `ucrtbase`, `api-ms-win-*` 39개) | Microsoft 재배포 가능 런타임 | 유지, 고지 D5 |

## C. 약한 copyleft·예외 조항 (무상, 의무 이행)

- Qt 6.12.0 Core/Gui/Widgets/Multimedia/Network/OpenGL/Svg 및 PySide6/shiboken6: LGPL-3.0(또는 GPL). 동적 링크 onedir를 유지하고 LGPL·GPL 전문, 정확한 버전의 소스 입수 방법, 사용자 DLL 교체 가능성을 고지한다.
- Qt 동봉 FFmpeg(`PySide6/avcodec-63` 등): `avutil_license()` "LGPL version 2.1 or later", 외부 코덱 import 없음. 유지하고 LGPL-2.1 고지.
- Qt PDF(`Qt6Pdf.dll`, `imageformats/qpdf.dll`)와 Qml/Quick 계열: LGPL이지만 미사용이며 Virtual Keyboard 경로로만 필요하다. 고지 범위를 줄이기 위해 D2에서 함께 제외한다.
- tqdm(MPL-2.0 AND MIT): 수정 없이 사용, 고지와 소스 위치 안내.
- PyAV 쪽 libiconv/libmp3lame(LGPL), GCC 런타임(GPL-3 + Runtime Library Exception): D1로 함께 사라진다. numpy의 OpenBLAS 동봉 런타임은 numpy 고지에 포함돼 있다.
- PyInstaller bootloader(`Recoryn.exe`, `Recoryn-CLI.exe`): GPL-2.0-or-later + bootloader 예외. 배포 앱 라이선스에 영향이 없으며 native 귀속을 PyInstaller로 기록한다.

## D. 허용형

CPython(PSF), OpenSSL 3(Apache-2.0), SQLite(public domain), libffi, numpy/OpenBLAS(BSD), CTranslate2(MIT), ONNX Runtime 두 벌(MIT), sherpa-onnx/sherpa-onnx-core(Apache-2.0), onnx(Apache-2.0), protobuf(BSD-3), tokenizers/hf-xet(Apache-2.0), ml_dtypes(Apache-2.0), faster-whisper(MIT), huggingface_hub(Apache-2.0), 기타 순수 Python 의존성(MIT/BSD/Apache). 선언 라이선스 기준으로 고지만 필요하다. native 묶음 내부의 정적 구성요소는 D5 대응표에서 따로 확인한다.

**미확인:** `PySide6/opengl32sw.dll`은 Mesa core(MIT) 외에 `LLVM_VERIFY_MACHINEINSTRS`, `llvm.global_ctors` 등 LLVM 계열 정적 코드 문자열이 관측된다. Mesa는 구성요소별로 다른 라이선스를 두므로 PE 전체를 MIT 하나로 확정하지 않는다. 정확한 구성·버전·조건 확인 전까지 G4 OPEN이다(L01-02 반영).

## E. 현재 고지·SBOM 결함

1. `NOTICE.txt` 635바이트에 LGPL/GPL 전문, Intel·Microsoft·OpenSSL·SQLite 언급이 없다.
2. PySide6/shiboken6 wheel이 `LicenseRef-Qt-Commercial.txt`만 동봉해 `licenses/`의 Qt 네 폴더에 **상용 라이선스 텍스트만** 복사됐다. 실제 사용 조건 LGPL-3.0과 다르다.
3. ctranslate2·tokenizers·sherpa-onnx-core는 wheel에 라이선스 파일이 없어 `licenses/`에서 누락됐다. tokenizers의 선언 라이선스는 `NOASSERTION`이다.
4. 선언 라이선스는 SBOM property `recoryn:declared-license`에만 있고 CycloneDX 표준 `licenses` 필드는 비어 있다.
5. SBOM 귀속에는 공유 `PySide6/__init__` 때문에 생긴 `PySide6_WebEngine` 1항목 같은 잡음이 있다. `pytest`(_pytest 3모듈)·Pygments·setuptools는 실제 일부가 포함된다(모두 허용형).
6. `native-origins.json`의 두 EXE는 `REVIEW_REQUIRED`로 남아 있다.

## 결정

- **D1** frozen 배포물에서 PyAV와 그 FFmpeg를 제외한다. Recoryn이 검증된 WAV PCM을 직접 float32 mono로 해석하고 16 kHz로 대역 제한 리샘플해 `numpy.ndarray`를 faster-whisper에 전달한다. faster-whisper 패키지의 `import av`는 frozen runtime hook의 사용 불가 stub이 충족하며 실제 사용 시 명시 오류를 낸다. 개발·소스 설치에서 PyPI의 av가 설치되는 것은 Recoryn의 재배포가 아니다.
- **D2** Qt Virtual Keyboard와 이를 위한 Qml/Quick 계열, 미사용 Qt PDF와 qpdf 플러그인을 제외한다.
- **D3** NVIDIA CUDA/cuDNN DLL을 동봉하지 않는다. CPU가 기본이며 GPU는 사용자가 설치한 CUDA/cuDNN을 쓴다. GPU 실행은 계속 NOT_RUN이다.
- **D4** 금지 목록을 한 곳에서 정의해 spec의 TOC 필터·재검사, 설치 verify, frozen 결과 검사가 공유한다. 남은 PE의 import 대상이 번들 또는 시스템에 있는지 import closure를 검사한다.
- **D5** 라이선스 전문을 출처 URL과 SHA-256과 함께 저장소에 고정하고, Qt를 LGPL-3.0으로 정정 표기하며, 누락 고지·CycloneDX `licenses`·전면 NOTICE를 생성한다. native 귀속은 **실제 경로·hash → 정적/동적 내부 구성요소 → 버전·출처·적용 전문·예외 → 유지/제외/미확인**의 대응표로 만든다. Mesa/LLVM(`opengl32sw.dll`)과 Intel MKL/OpenMP를 명시 조사 항목으로 두고, 확인하지 못한 조건은 미확인으로 표시한다(L01-02 반영).
- **D6** 남는 G4: Qt/PySide6/Qt FFmpeg의 corresponding source 제공 위치와 방식, Qt 모듈별 제3자 구성요소 전문의 완전성, Intel·Microsoft·Mesa/LLVM 조건의 확인, **유지하는 Qt FFmpeg에 정적으로 포함된 코덱의 특허 확인**(실제 코덱·용도·관할 기준), 서명. Recoryn은 Qt Multimedia를 WAV/PCM 근거 재생에만 쓰지만, 외부 코덱 import가 없다는 관측이나 LGPL 표기만으로 특허 검토 완료를 선언하지 않는다(L01-03 반영). 자동 수집으로 종결하지 않는다.

## push 단위

| push ID | 목적과 정확한 범위 | 작성 / 독립 검토 / 게이트 |
| --- | --- | --- |
| L-P01 | 이 검토와 계획: 이 문서, [배정표](../collaboration/assignments.md), [push 단위](../collaboration/push-units.md), docs/reviews/license-plan-review.md | C00 / recoryn-security(w5:p5) / 링크·내용·권한 검토, 선행 H-P01 CI PASS |
| L-P02 | D1~D4 배포 제외와 PyAV 비의존 STT 입력. 파일은 배정표 L 절 | C00 / recoryn-ml(STT·리샘플), recoryn-arch(패키징) / 경우의 수 문서·독립 oracle·mutation, frozen 빌드·smoke·금지 파일 0·import closure, 정확한 tree 전체 회귀 |
| L-P03 | D5 고지·SBOM 보완과 최종 후보 증거 | C00 / recoryn-security / 고지 생성 시험, frozen 빌드의 고지 전수 대조, 정확한 tree 전체 회귀·coverage·정적 검사 |

각 단위는 선행 단위의 원격 CI PASS 뒤에 공개한다. 로컬 작성과 검증은 병행할 수 있다. rollback은 각 commit의 revert이며 schema/runtime migration은 없다. 실음성·모델 weights·GPU·clean VM·서명·법률 판정은 이 계획으로 실행하거나 통과 처리하지 않는다.

## 출처

- [Qt Virtual Keyboard](https://doc.qt.io/qt-6.5/qtvirtualkeyboard-index.html), [Licenses Used in Qt](https://doc.qt.io/qt-6.3/licenses-used-in-qt.html), [Qt PDF Licensing](https://doc.qt.io/qt-6.8/qtpdf-licensing.html)
- [pyav-ffmpeg](https://github.com/pyav-org/pyav-ffmpeg), [PyAV 설치 문서](https://pyav.basswood-io.com/docs/13.1/overview/installation.html)
- [OpenH264](https://en.wikipedia.org/wiki/OpenH264), [Debian libopenh264-cisco copyright](https://metadata.ftp-master.debian.org/changelogs/main/o/openh264/stable_libopenh264-cisco7.copyright)
- [CTranslate2](https://pypi.org/project/ctranslate2)
