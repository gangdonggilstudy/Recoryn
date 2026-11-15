# L05 / L-P05 고지 독립 검토

2026-11-15. 검토 L05/Codex, 작성 C00/Claude. **REVIEW_READY — OPEN 3건(S0 0 / S1 0 / S2 0 / S3 3).** 법률·G4·공개 배포 승인이 아니다. 기준은 [D8](../implementation/license-review.md), [경우의 수](../testing/l05-notice-cases.md), [L-P05 결과](../implementation/license-results.md)다.

AGENTS·온보딩·협업/품질 규칙·L05 배정을 재확인하고 ONBOARDING_READY를 보고했다. 이번 지시의 명시 금지에 따라 Git·인덱스·빌드·pytest·제품 실행을 하지 않았다. 제품·시험·설정은 읽기 전용이며 이 리뷰만 작성했다. 후보/원문 검사는 `.venv/Scripts/python.exe -B -X utf8 -`의 pathlib/json/hashlib/re 및 읽기 전용 pefile로 수행했다. 다운로드한 파일은 실행하지 않았다.

## 대상 판

raw SHA-256:

| 파일 | SHA-256 |
| --- | --- |
| packaging/release_evidence.py | 53b5542b89979de62f6eaa5a9317f977d95a2f0def811297d11071c51b682074 |
| packaging/notices/SOURCES.json | 35c5072e6d9688bdc94f8992ae21da0ea6eb164c7495249020515336fa7280d1 |
| packaging/notices/native-map.json | 516caf022b4939abecafdd53e4a265d01124924f079ed661a0cd138a772aab7d |
| packaging/notices/qt-third-party.json | fdf80c039cd438b9b209a3ff2cde34490c46f6d0f19a29fee7e1312eac0e665a |
| packaging/notices/ct2-native.json | 46f62a403dbf329005a18dc9e84050b0ba711112b377be1a1f2833c77716bff0 |
| packaging/notices/corresponding-sources.json | 3defdb24f00521c5ce84044df43448fd84f1ec6295cd332e3970702c2a9da105 |
| scripts/build_release.py | 354609b141d62d1dae4eb5e85f294263a159bc98d27e3d63389d90ec84e1cf7d |
| tests/release/test_evidence.py | aed684a744089b56ae588839d0a595f886c172319b7dbc42f06dc032f125fcba |
| tests/release/test_build_inputs.py | 97d0f8e92d2d87261f033c04345812ff0c7b93965e023e74487a47a2902bc517 |
| .gitattributes | be459f59929151ab31a3cf1f5c43a5dd7793e03e4edd8e46907141028f73fc74 |

실제 후보 `build/l05b-1794737025/dist/Recoryn`의 다음 hash는 C00 제출값과 독립 대조해 일치했다.

| 파일 | SHA-256 |
| --- | --- |
| NOTICE.txt | b6831dcfd057515b90c64f01e9c666779331bce7f04f774cca6d2283628a3e69 |
| sbom.cdx.json | d7a75bece9c523a94a346786af65104243bd821081b9530d8521195de32b4340 |
| native-origins.json | a0374f61e2ec5639475651e93b52d6f0f2c9d318ff2a3017376eb69998342ba5 |
| build-provenance.json | 5e546540449b104897c60085a70134109cc3e2cc6fd22655fe06424c2a654d17 |

## 발견

### L05-01 / S3 / OPEN — libjpeg의 실제 포함 위치가 귀속표에서 빠진다

원 반례: `qt-third-party.json`의 `(qtbase, libjpeg)`는 `plugins/imageformats/qjpeg.dll`만 `shipped_in`으로 기록한다. 후보의 **qtiff.dll에도** `libjpeg-turbo version 3.2.0 (build )`, libjpeg-turbo 저작권, JPEG 구조체/디코딩 진단 문자열이 함께 있다. pefile import 표에는 외부 JPEG DLL이나 qjpeg.dll이 없고 Qt6Gui/Core 및 Windows 런타임만 있다. qjpeg.dll과 qtiff.dll 양쪽에서 동일한 버전·저작권/진단 문자열 묶음을 확인했다.

따라서 구성요소 자체의 고지 누락은 아니지만, D8의 실제 내부 구성요소 대응 위치가 불완전하다. NOTICE와 SBOM도 같은 단일 위치를 복사한다.

제안: libjpeg의 포함 위치에 qtiff.dll도 기록하고 두 PE의 근거를 연결한다. 위치가 여럿인 표현을 시험의 기대값에서도 명시한다. 새 유료 의무나 법률 위반을 발견했다는 뜻은 아니다.

### L05-02 / S3 / OPEN — 보수적으로 포함한 ES2 항목의 미확인 상태가 배포 고지에 사라진다

원 반례: `(qtbase, opengl-es2-headers)`의 note는 `whether compiled on Windows desktop-GL build UNCONFIRMED; same license file`이다. 경우의 수 문서도 실제 컴파일 여부가 미확인이라고 적는다. 그러나 `_qt_notice()`는 Qt 행의 note를 출력하지 않는다. 실제 NOTICE는 “Third-party code inside the shipped Qt” 아래 해당 항목을 싣고, SBOM도 다른 확인된 내부 구성요소와 같은 방식으로 표시한다. 후보 NOTICE에 위 UNCONFIRMED 문구가 없음을 확인했다.

제안: 실제 빌드 근거로 포함 여부를 확정하거나, 확인 전에는 원문을 보수적으로 동봉한다는 상태와 이유를 NOTICE/SBOM에 보존한다. 미확인 항목의 원문을 무조건 삭제하라는 제안은 아니다. MIT라는 원문 식 자체를 부정하지 않는다.

### L05-03 / S3 / OPEN — 집계 문서의 파일 수와 행 수를 구분해야 한다

원 반례: 경우의 수 문서의 “목록 완전성”은 매니페스트 JSON을 **4종** 제외한다고 쓰지만, 실제 JSON은 SOURCES/native-map/qt-third-party/ct2-native/corresponding-sources의 **5종**이다. 실제 notices 디렉터리는 83파일 = 원문 78 + JSON 5다.

또한 허용된 조사 원자료 `l05-research/attr`의 `qt_attribution.json`은 **88파일 안에 103개 유일 (repo, Id) 행**이 있다. 행 단위로 선택된 것은 47행이며 37개 JSON 파일에 분포한다. 제외는 56행이고, qtsvg REUSE 추가 1행을 합쳐 현재 48행이 된다. D8/결과/경우의 수의 “88개 중 47개”는 파일/행 단위가 섞여 읽힌다.

제안: JSON 5종을 정확히 적고, 입력 88파일/103행 → 포함 47행·제외 56행 → REUSE 1행 추가 → 48행을 명시한다. 최종 48행·유일 ID가 틀렸거나 거부 입력을 누락했다고 판정한 것은 아니다. 원자료의 개행을 허용하기 위해 JSON 파싱에는 `strict=False`를 사용했다.

## 독립 대조 결과

- **원문 집합:** SOURCES 78개 유일 경로와 실제 원문 파일 집합이 같고, 모든 bytes/SHA가 일치한다. 누락·초과·해시 불일치 0. Qt 47파일·CT2 26파일 신규를 포함한다. URL과 archive member/발췌 기록은 존재하지만 이것만으로 출처 진위를 확정하지 않았다.
- **공개 원문 표본:** urllib HTTPS GET으로 Qt zlib/LICENSE, FreeType/docs/FTL.TXT, libpsl/PSL-LICENSE.txt, oneDNN/LICENSE, CCCL/libcudacxx/LICENSE.TXT, spdlog/LICENSE를 각각 SOURCES의 고정 URL에서 다시 읽었다. **6/6 원격 bytes = 저장소 bytes**. 각 SHA는 SOURCES와 같으며 결과와 받은 원문은 `C:\Users\gangd\AppData\Local\Temp\recoryn-l05-upstream-jv2cm7i6/results.json` 및 같은 부모에 보존했다. 첫 샌드박스 시도 `recoryn-l05-upstream-ozw1ru8c`의 WinError 10013 소켓 제한은 별도 인프라 실패다. 허용된 공개 원문 읽기만 권한 재시도했고 실행하지 않았다.
- **생성물 대조:** Qt 48행/유일 ID 48, CT2 16행/유일 ID 16의 머리줄·모든 저작권 줄·모든 원문 사본을 실제 후보와 대조해 불일치 0. SBOM은 **전체 102개 = 기존 38 + Qt 48 + CT2 16**이며, “64개”는 추가 내부 구성요소 수다. native는 105개, 상태는 DECLARED 90 / REDISTRIBUTABLE_PROPRIETARY 13 / CONDITIONS_UNCONFIRMED 2다.
- **정적 포함 근거:** ctranslate2.dll의 import에는 libiomp5md와 Windows 런타임이 있고 cudart/cuBLAS/cuDNN DLL은 없다. 문자열에서 oneDNN-3.1.1 소스 경로, MKL, CUDA runtime 진단, Philox, precalc_xorwow, CUB_200700, THRUST_200700, spdlog 및 ittnotify를 확인했다. 연구 원자료의 v4.9.0 Windows 빌드 스크립트는 CUDA 12.8.1, oneAPI 2025.3.0, static oneDNN, WITH_DNNL/WITH_CUDA 및 CUDA_DYNAMIC_LOADING을 지정한다. 숫자 버전·내부 코드 전체의 완전성을 문자열만으로 전수 증명하지 않는다.
- **Qt 포함/제외 표본:** Qt6Core의 zlib/PCRE2/BLAKE, Qt6Gui의 FreeType/HarfBuzz/libpng/QRhiVulkan/D3D12 allocator, Qt6Multimedia의 dr_wav/tlsf, qjpeg/qtiff의 JPEG, qwebp와 qwindows의 해당 문자열/import를 읽었다. 연구 원자료에서 제외된 플랫폼·빌드/시험·FFmpeg/공간 오디오 등의 QtUsage도 대조했다. 문자열이 없다는 사실 하나로 코드 부재를 확정하지 않는다. 모든 48항목의 컴파일 포함을 독립 재현 빌드로 증명한 것은 아니다.
- **NVIDIA 헤더:** 로컬 조사 원본 `curand_philox4x32_x.h`의 SHA가 SOURCES의 header_sha256과 같고, LF 경계 기준 1~78행의 raw bytes가 발췌 4128bytes와 정확히 같다. C 주석을 제거하면 공백만 남고 지시문/코드가 없다. 후보에는 독점 헤더 세 파일명이 없으며 발췌가 NOTICE에 보존된다. 이는 헤더 코드의 배포 권한을 승인하는 판정이 아니다.
- **bytes/snapshot:** 후보 provenance가 포함한 notices 하위 83개 입력 모두 현재 파일 hash와 일치한다. `.gitattributes`의 루트 txt·qt/**·ct2/** -text와 빌더의 하위 전체 수집을 코드로 확인했다. Git 명령은 실행하지 않았다.
- **조건 미확인:** CT2 두 native의 CONDITIONS_UNCONFIRMED, Intel redist 목록을 찾지 못했다는 note, NVIDIA cuRAND 장치 헤더가 Attachment A에 없다는 note, licensed Visual Studio users 조건 및 실제 충족 미확인이 남아 있다. Intel/Microsoft/NVIDIA gate는 모두 REVIEW_REQUIRED다. source archive URL·SHA 5개는 게시/호스팅 완료와 구별하며 Qt gate도 HOSTING_DECISION_REQUIRED다. G4 승인처럼 바뀐 점은 찾지 못했다.
- **필수 고지와 oracle:** 실제 FreeType/IJG 문구·PSL MPL 소스 위치·cuRAND 원문이 존재한다. 시험은 FreeType/IJG에 별도 리터럴 기대값을 쓰고, 수작업 Qt 13개/CT2 13개 기대행과 부재 집합, 원문 SHA, 잘못된 행 거부 및 manifest 부재를 검사한다. 행별 생성/복사 검사는 귀속 원자료를 기대값으로 쓰므로 원자료 자체의 정확성은 별도 독립 조사로 보완해야 한다. 기존 미확인 문구를 삭제/완화한 oracle 약화는 현재 코드에서 찾지 못했다. 최초 조사 중 제기했던 필수 문구 oracle 우려는 상세 코드를 읽고 철회했으며 OPEN에 집계하지 않았다.

## 제한과 마감

C00 보고의 작업트리 7550 PASS(문구 수정 전), 관련 251 PASS 및 저장된 smoke는 이번 독립 실행 결과가 아니다. pytest·mutation·제품·빌드 실행 금지에 따라 원문/코드/후보를 읽어 검토했으며 별도 전체 회귀를 주장하지 않는다. 연구 자료의 출처 전체·83개 파일의 모든 원격 원본·5개 source archive bytes를 전부 재다운로드하지 않았다. 별도 과거 Git blob과 assertion diff는 Git 금지로 확인하지 않았다. 실제 음성·모델·계정·유료 호출·추가 위임은 하지 않았다.

**REVIEW_READY. OPEN: L05-01(S3), L05-02(S3), L05-03(S3). 수정 후 동일 검토자가 변경 hash·근거를 재확인한다. 법률·G4·릴리스 판단은 이 검토로 종결하지 않는다.**

## L05 재확인 — 2026-11-15

C00 재배정에 따라 이 절만 추가했다. 앞선 발견은 이력이며 현재 판정은 아래와 같다. Git·인덱스·빌드·pytest·Recoryn 실행 없이 코드/문서/후보를 읽고, 명시적으로 허용된 Qt 빌드 유형만 별도 offscreen QGuiApplication에서 조회했다. 제품·시험·설정은 수정하지 않았다.

재확인 raw SHA-256:

| 파일 | SHA-256 |
| --- | --- |
| packaging/notices/qt-third-party.json | 6e7b345b3a31fac85effbc4b89cbdd97b437931dba2dbcf0af0c9fa5f3e20a7c |
| tests/release/test_evidence.py | 5e0dce25c7329a65478fde190868594d077fb09f5e3e9ed4b91c2aa7786de47e |
| docs/testing/l05-notice-cases.md | 50e02def2042eaa1d30da683b248e9053bf47ff409c16768bd59ad641126447e |
| docs/implementation/license-results.md | 07cab73c0a3734c7e8982317b74c5322ad2d7332b59935df1f9d40ca8c76a129 |
| docs/implementation/license-review.md | 0c6eca7bde8f8420e8186846bb9bb4318b91f434c387c7e21a12c014d5b6de26 |

나머지 여덟 대상(release_evidence/SOURCES/native-map/ct2-native/corresponding-sources/build_release/test_build_inputs/.gitattributes)의 hash는 최초 검토판과 동일했다. 새 후보 `build/l05c-1794737798/dist/Recoryn`의 NOTICE SHA `58f4d52bebbe716dd4525de6a0450a6f49bbae898fcb8529bffdcb0802a9ff5b`, SBOM SHA `e734a897831c92bc6c5048cad8f11151c07bb4179af65ddf53a5bcec68d52dee`를 독립 확인했다.

| 발견 | 원 반례 재대조 | 현재 판정 |
| --- | --- | --- |
| L05-01 / S3 | 귀속표·NOTICE·SBOM의 libjpeg 위치가 qjpeg.dll과 qtiff.dll을 모두 명시한다. 두 PE의 버전 문자열 및 외부 JPEG DLL import 부재 근거가 note에 있고, 시험의 별도 기대 위치도 두 경로로 바뀌었다. | RECHECKED / CLOSED |
| L05-02 / S3 | ES2 행이 실제로 제외됐고 Khronos 원문·저작권은 opengl-headers 행에 남았다. 후보에 ES2 머리줄이 없고 Qt 47행/전체 SBOM 101개다. LibGL 조회와 Qt의 Windows EGL/ES 미지원 설명은 제외를 뒷받침한다. 다만 아래의 동적 OpenGL 설명 오류가 남았다. | RECHECKED(제외) / OPEN(근거 문구) |
| L05-03 / S3 | JSON 5종 명시를 확인했다. 원자료를 다시 세어 88파일/103행 → 포함 46행/제외 57행 → REUSE 1행 추가 → 최종 47행을 독립 확인했고 수정 문서와 일치한다. | RECHECKED / CLOSED |

### L05-02에 남은 문구 오류

경우의 수 문서는 “Qt 6은 Windows에서 동적 OpenGL을 지원하지 않으므로”라고 쓰지만, [Qt 공식 Windows graphics 설명](https://doc.qt.io/qt-6/windows-graphics.html)은 dynamic OpenGL의 선택/로딩을 지원한다고 설명한다. Windows에서 지원하지 않는 것은 **EGL 및 OpenGL ES**다. desktop OpenGL 구현의 동적 선택과 ES 지원을 구별해야 한다. ES2 원문을 보수적 포함에서 제외한 결과 자체를 거부하는 것이 아니라, 이 잘못된 근거 문장을 EGL/ES 미지원 및 해당 빌드 조건의 근거로 고치도록 요청한다.

독립 조회는 `QT_QPA_PLATFORM=offscreen`과 `.venv/Scripts/python.exe -B -u -X utf8 -W error::ResourceWarning -`에서 QGuiApplication을 만든 뒤 `QOpenGLContext.openGLModuleType()`을 읽었으며 **LibGL**이었다. 사용한 설치본과 후보의 QtGui.pyd/QtCore.pyd/Qt6Gui.dll/Qt6Core.dll 네 파일의 SHA가 각각 동일함을 먼저 확인했다. frozen 후보를 일반 Python package처럼 직접 import하려던 첫 시도는 설치본으로 해석되어 출처 assertion에서 제외했다. 무앱 조회도 최종 근거로 쓰지 않았으며, 위 동일 bytes 확인과 offscreen 조회만 유효 근거다. 렌더링·오디오·제품 GUI·실장비 검증으로 확대하지 않는다.

### L05-04 / S3 / OPEN — libjpeg 저작권 placeholder가 NOTICE에 출력된다

재확인 중 추가 발견했다. 현재 `qt-third-party.json`의 libjpeg 행은 `copyright: ["None"]`이고, 새 후보 NOTICE의 해당 머리줄 바로 다음 줄도 실제로 `    None`이다. `_attributions()`의 비어 있지 않은 목록 조건과 행 복사 시험은 이 placeholder를 저작권 줄처럼 허용한다. 이는 최초 검토에서 잡지 못한 데이터 표시 오류다.

제안: 이미 고정·동봉된 `qt/qtbase/src/3rdparty/libjpeg/COPYRIGHT.txt`의 실제 저작권 줄을 근거로 귀속표를 채우거나, 저작권이 별도 파일에 있음을 명시적으로 참조한다. `None`/null/공백 같은 placeholder를 유효 저작권으로 다루지 않는 독립 부정 기대값을 둔다. 원 COPYRIGHT.txt 전체와 IJG 고지는 후보에 있으므로, 원 저작권 전문 자체가 배포물에서 빠졌다는 판정이나 법률 위반 단정은 아니다.

관련 251 PASS·새 smoke PASS는 C00 실행 보고이며 이번 독립 재실행으로 합산하지 않았다. 원문 재다운로드/새 빌드/전체 회귀를 반복하지 않았다. G4·Intel/NVIDIA/Microsoft 조건·소스 호스팅·법률·실장비 승인 보류는 그대로다.

**REVIEW_READY. 현재 OPEN 2건: L05-02(S3, 근거 문구), L05-04(S3, 저작권 placeholder). L05-01·L05-03은 RECHECKED/CLOSED.**

## L05 추가 재확인 — 2026-11-15

C00의 L05-02·L05-04 재배정에 따라 이 절만 추가했다. 앞선 OPEN 기록은 이력이며 현재 판정은 아래와 같다. Git·인덱스·제품·빌드·pytest를 실행하거나 제품/시험/설정을 수정하지 않았다. 이번 확인은 파일 읽기·원문 행 대조·hash 및 실제 생성물 관측에 한정한다.

재확인 raw SHA-256:

| 파일 | SHA-256 |
| --- | --- |
| packaging/notices/qt-third-party.json | ddfeb0a1c27086521f2efedb3504237e2137f5d2887adadbd68584e2ea2f6729 |
| packaging/release_evidence.py | 6f66d3bb44f423f6739970b9d69953dac83512ac638944af7e0ef1fa1a197fac |
| tests/release/test_evidence.py | aa9db300dcece1e6cea2b5a0980731d8b636df35b41b9015095b3ab107115c2c |
| docs/testing/l05-notice-cases.md | ad87e59d4457af083cbe84bad90660bfec707189d86d680aecc65e96accb66ac |

| 발견 | 원 반례 재대조 | 현재 판정 |
| --- | --- | --- |
| L05-02 / S3 | 귀속표 note와 경우의 수 문서가 Windows의 EGL/OpenGL ES 미지원과 desktop OpenGL 구현의 동적 선택을 구분한다. 잘못된 이전 문장은 오류 이력으로 명시되고 현재 근거로 사용되지 않는다. 앞선 동일 bytes Qt의 LibGL 조회·공식 설명과 충돌이 해소됐다. ES2 제외 및 Khronos 원문 보존 판정은 유지한다. | RECHECKED / CLOSED |
| L05-04 / S3 | libjpeg copyright 배열은 고정 COPYRIGHT.txt의 실제 15줄과 순서까지 같고, 첫 줄은 D. R. Commander의 2009–2026 표기다. 새 후보 NOTICE에 15줄이 모두 출력되며 종전 `    None` 줄은 없다. `_attributions`는 strip/lower 후 빈 문자열·none·null·n/a·하이픈·unknown·noassertion을 거부한다. 원 반례 None을 넣는 부정 행, 실제 첫 줄/15줄 수 손기대값 및 표 전체 placeholder 검사도 확인했다. | RECHECKED / CLOSED |

새 후보 `build/l05d-1794738231/dist/Recoryn`의 NOTICE raw SHA-256은 `f5634bef77502b84c65f3498fb3413b681f32b7e478a75dabfaed1769f1e1461`로 제출값과 일치한다. SBOM raw SHA-256은 `e734a897831c92bc6c5048cad8f11151c07bb4179af65ddf53a5bcec68d52dee`로 직전 후보와 동일하다. 후보 판정은 원 반례가 실제 생성물에서 사라졌음을 읽어 확인한 결과이며 validator 부정 시험을 이번에 실행했다고 주장하지 않는다. C00의 관련 252 PASS·smoke PASS도 별도 작성자 증거로 구분한다.

**REVIEW_READY — L05-01~04 모두 RECHECKED/CLOSED. 현재 OPEN 0건(S0 0 / S1 0 / S2 0 / S3 0). G4·법률·소스 호스팅·Intel/NVIDIA/Microsoft 조건·서명·실장비·최종 통합/공개 승인은 별도다.**
