# L06 / L-P06 CTranslate2 CPU 빌드 독립 검토

2026-11-15. 검토자 Codex(recoryn-arch), 작성자 C00/Claude. **REVIEW_READY — OPEN 3건(S0 0 / S1 0 / S2 2 / S3 1).** 이 문서는 기술 독립 검토이며 법률·G4·공개 릴리스 승인이 아니다. 기준은 [D9](../implementation/license-review.md), [L06 경우의 수](../testing/l06-ctranslate2-cpu-cases.md), [L-P06 결과](../implementation/license-results.md)다.

AGENTS.md와 온보딩 읽기 순서, workflow/quality-system, L06 배정, case-space/push-units 및 구현·결과 문서를 다시 읽고 ONBOARDING_READY를 보고했다. 이번 배정의 금지에 따라 제품·시험·설정·Git/index·빌드·pytest를 실행하거나 수정하지 않았다. 기존 구현·시험·고지·후보는 읽기 전용으로 확인했고 이 문서만 신규 작성했다. 후보의 PE import와 문자열은 `.venv/Scripts/python.exe`의 읽기 전용 `pefile`/`pathlib` 검사로 대조했다.

## 검토 대상과 hash

지시된 소스 및 시험 hash는 모두 제출값과 일치했다.

| 대상 | SHA-256 |
| --- | --- |
| scripts/build_ctranslate2_cpu.py | 34407106c536e031afc17daca82f5ed16b6137ca4ef58d093092a71c5baec6d7 |
| scripts/build_release.py | 87f555394b5dd9412c263bf535eef0aa8462aa0ae3998a142d6221ab95880a50 |
| packaging/release_manager.py | f1d846892b8017854eb4f54628df2bdc99a5a756507b1ecb1561fde736ecf0d6 |
| packaging/release_evidence.py | 51f49ef38476fdf5eeafe6a118b3124b96064e1fa2b0a2dbb7627b066e076917 |
| packaging/notices/SOURCES.json | cade4be0146a49482dc1749d39eacdb84af13c960a12b575ce1ebf9eefdff008 |
| packaging/notices/ct2-native.json | 4d95b51bf37264d9d674695e8973875b62f4e46702a6feacf58495b27b74b557 |
| packaging/notices/native-map.json | 7a2b7b40d14e25ad4815bb1b638f389a3e4839a7d4fdc1dca6a7242020ab1db4 |
| tests/release/test_evidence.py | d0e9277a1ca23214e15eb3f204b78dcfedadd3c2bdf32bef2566f2317bd17a47 |
| tests/release/test_release.py | b7857a97b5d460edbfb399de4914d94b8b5ce299268ee2c9284862b5e327786a |
| tests/release/test_spec.py | dd77ffea5d2dbb33095cfd7dc1e679ec32df1e35b02f56cb770f474faaadb61a |
| tests/release/test_build_inputs.py | a3b96173937938fe5668842640650a3b81407955ea1e2c61b9e804454bdbc37c |

저장된 자체 빌드 보고서는 `build/ct2-cpu-1794741153/ct2-cpu-build.json` SHA-256 `5d5ee76a189166f277d6089b31626e201783f7f2a2e0aeb75f9bfad8f78c5603`이다. 보고서의 CTranslate2 DLL SHA는 `c97c40498445706c5291d35fdf3a7c55402eafbc2e6a4a87f8fad1c4f6badab4`, vcomp140 SHA는 `036b9b3f7ece8dfd48aeccd77113721c5305043aaa9c64d1e72812252727aa7c`, wheel SHA는 `2413f776ae9ab013f71a612d575f1bd3181cd195e2f2a1ed0acd1f7dd3417c78`이다.

검토 후보 `build/l06-1794741522/dist/Recoryn`의 고지·증거 hash도 제출값과 일치했다.

| 후보 증거 | SHA-256 |
| --- | --- |
| NOTICE.txt | 2762f169fd8837e4370f706ea83435e540f5e7cb4f7627c852361b226b5d2794 |
| sbom.cdx.json | 646c414f7a662f68e4c60134d63d8609ecd1375a07731e3f53dbee29581a87e9 |
| native-origins.json | 097fef247d80658b9b6a55aa4003087e40e93e0fda9b85ccb695ecef41d695ad |
| build-provenance.json | b6f3ad404d8db4d1605589a05feda960e2adddc47f81097d140667f07987d9dc |
| smoke.stdout.json | 3365b214cc486611fdc6e5b876038f39997e30514ca8e61a644fc463a8f389a5 |

## 결정표와 독립 대조

고정 분모는 CTranslate2 본체·cpu_features·spdlog·oneDNN의 4 source commit, wheel backend 4개(pybind11/setuptools/wheel/packaging)의 버전·hash, CTranslate2 6개 핵심 옵션과 oneDNN 6개 옵션이다. 소스 commit 4/4와 backend hash 4/4가 보고서와 일치한다. `WITH_MKL=OFF`, `WITH_CUDA=OFF`, `WITH_CUDNN=OFF`, `WITH_DNNL=ON`, `OPENMP_RUNTIME=COMP`, `BUILD_CLI=OFF`, oneDNN `STATIC/OMP/INFERENCE` 및 examples/tests/graph OFF를 코드에서 확인했다.

후보 manifest는 1,102개 payload record이며 실제 파일과 record의 누락·초과(자기 manifest 제외) 및 size/hash 불일치가 0이다. `analysis-toc.json`의 binaries/datas에서 정책 위반 row는 0이다. `native-origins.json`과 native-map은 각각 105행이고 경로 집합·license·status가 완전히 일치한다. 상태는 DECLARED 91, REDISTRIBUTABLE_PROPRIETARY 14, UNMAPPED 0이다.

`ct2-native.json`은 9행이며 후보 SBOM의 CTranslate2 native 9개 구성요소와 NOTICE의 CTranslate2 절에 모두 대응한다. SOURCES.json은 61행이며 ct2 원문 9개와 hash가 일치한다. oneDNN, Xbyak, ittnotify, spdlog/fmt, cpu_features, avx_mathfun, SIMD_Utils가 정적 구성요소로 기록되어 있고, Intel oneMKL/OpenMP·CUDA runtime/cuRAND·CCCL 원문은 남아 있지 않다.

## 실제 DLL과 후보 판정

보고서와 후보의 `ctranslate2.dll` 및 `vcomp140.dll` bytes hash가 각각 정확히 일치했다. 후보 `ctranslate2.dll`의 일반·지연 import는 Windows CRT와 `vcomp140.dll`뿐이며 `libiomp5md`, CUDA/cuBLAS/cuDNN/NVIDIA import는 없다. 후보 전체 파일명에도 Intel/NVIDIA runtime 금지 basename이 없다.

DLL에는 `This CTranslate2 package was not compiled with CUDA support`, `This CTranslate2 binary was not compiled with Intel MKL`, `GenuineIntel` 및 CPU feature 이름이 문자열로 남아 있다. 이는 CPU 경로의 진단·CPU dispatch 데이터이며 CUDA runtime, oneMKL 또는 Intel OpenMP import/제품 marker가 아니다. 따라서 실제 후보에서 **금지된 Intel/NVIDIA runtime 잔존은 관측되지 않았다**. 다만 결과 문서의 넓은 표현인 “Intel·NVIDIA 문자열 없음”은 이 정상 진단 문자열까지 없다는 뜻으로 읽히지 않도록 범위를 `oneMKL/OpenMP/CUDA/cuRAND runtime marker 없음`으로 한정해야 한다.

NOTICE는 PyPI판의 Intel/NVIDIA 코드가 비배포임을 설명하고, oneDNN의 Intel 저작권과 vcomp140의 Microsoft 조건을 별도로 표시한다. SBOM에는 custom CTranslate2 4.9.0+recoryn.cpu1와 native 9행이 있고 Intel/NVIDIA runtime component는 없다. provenance gate는 `intel_runtime_conditions`/`nvidia_runtime_conditions`=`NOT_DISTRIBUTED_L01_D9`, Microsoft runtime은 `REVIEW_REQUIRED`다. 저장된 smoke는 CPU-only custom version, worker 시작·종료, network denied, `status=PASS`를 기록하지만 실제 음성·weights·추론·장치 검증은 NOT_RUN이다.

## 발견

### L06-01 / S2 / OPEN — 설치 wheel과 source-build evidence가 release gate에 암호학적으로 묶이지 않음

원 반례: `scripts/build_release.py`는 설치된 distribution의 metadata version이 `4.9.0+recoryn.cpu1`인지 확인하고, frozen 뒤 `ctranslate2.dll`에 6개 문자열과 일부 import가 없는지, `vcomp140.dll`이 존재하는지만 확인한다. `ct2-cpu-build.json`의 wheel/DLL/vcomp hash를 읽거나, PyInstaller가 실제로 수집한 package 경로가 그 report의 wheel에서 왔는지 확인하지 않는다. `release_evidence.py`와 native-map도 경로와 관측 hash를 기록하지만 기대 hash와 비교하지 않는다.

독립 hand-written 반례는 동일 metadata version을 가진 임의 wheel/패키지에 CRT·vcomp import만 있는 다른 `ctranslate2.dll`을 넣고, 알려진 6개 marker를 제거하는 것이다. 이 경우 `ctranslate2_cpu_violations()`는 빈 결과가 될 수 있고, vcomp가 임의 bytes여도 존재 검사만 통과한다. 현재 후보의 두 DLL hash는 source-build report와 일치하므로 **현재 artifact의 사실 판정은 PASS**지만, 동일 gate가 향후 stale/custom wheel 또는 바뀐 vcomp를 거부한다는 증거는 없다.

제안: release 입력에 검증된 wheel 또는 build report를 명시하고 wheel SHA, unpacked `ctranslate2.dll`/`vcomp140.dll` SHA와 PE import를 post-wheel 및 frozen 단계에서 다시 대조한다. vcomp의 허용 source/toolset hash 또는 검증된 Microsoft redist provenance도 고정한다. 그러면 version/marker 우회가 source-build identity를 대신하지 못한다.

### L06-02 / S2 / OPEN — 도구체인과 일부 CPU 옵션이 부동 상태라 재현성 기록이 불충분함

원 반례: `visual_studio()`는 `vswhere -latest`를 사용하고 `openmp_runtime()`는 설치된 redist 중 최신 후보를 선택한다. report에는 MSVC/CMake/Python의 정확한 toolset·버전·compiler hash가 없다. CTranslate2의 pinned CMake에서 `BUILD_TESTS`, `WITH_RUY`, `WITH_FLASH_ATTN` 등은 현재 source의 OFF 기본값이지만 script의 CMake 인자로 명시되지 않는다. 같은 commit이라도 VS/CMake가 업데이트되거나 기본값이 바뀐 빌드 환경에서는 결과 DLL과 vcomp가 달라질 수 있다.

현재 보고서의 source/options와 후보 hash가 일치한다는 사실은 이 한 번의 산출물에 대한 근거다. 반복 재빌드의 bit-for-bit 재현성은 이 검토에서 실행하지 않았다.

제안: MSVC toolset/redist와 CMake/Python 버전을 고정·기록하고, CPU 안전 옵션(BUILD_TESTS/OFF, WITH_RUY/OFF, WITH_FLASH_ATTN/OFF, WITH_HIP/OFF, WITH_MPS/OFF, WITH_OPENBLAS/OFF 등)을 명시한다. CMake cache/compile option digest를 report에 넣어 변경을 거부한다.

### L06-03 / S3 / OPEN — 새 CPU gate 시험이 PE·우회 변이를 충분히 검증하지 않음

시험의 정상 정책·경로 결정표와 고지 9행 대응은 기존 assertion을 약화하지 않았다. 그러나 새 `test_build_inputs.py`의 부정 oracle은 6개 hand-written byte marker와 “vcomp 파일 없음” 한 행에 집중하고, `ctranslate2_cpu_violations()`의 금지 import/지연 import를 합성 PE로 검사하지 않는다. 대소문자·UTF-16 marker, marker가 없는 stale/custom DLL, wheel unpack 후 DLL hash 변경도 시험하지 않는다. 문자열 목록이 구현의 `CT2_FORBIDDEN_STRINGS`와 같은 값으로 작성되어 있어 목록 자체의 누락을 독립적으로 잡지 못한다.

원 반례는 import가 `libiomp5md.dll`인 합성 PE 또는 marker의 대소문자 변형을 넣는 것이다. 현재 실제 후보의 PE 표는 깨끗하지만, 이 시험 분모만으로 향후 PyPI 재유입과 wheel 변조 경계를 전수 판정할 수 없다.

제안: 기존 정상 PASS를 유지한 별도 temporary fixture에서 import/지연 import 위반·case/encoding 변형·post-wheel hash 불일치 mutant를 만들고, 제품/원본을 건드리지 않은 상태에서 목표 assertion이 실패하는지 확인한다. 구현 marker를 그대로 복제한 목록만으로 통과하지 않도록 독립 expected set 또는 source-build report를 oracle로 연결한다.

## 제한과 마감

저장된 후보의 고지·manifest·native-map·SBOM·PE·문자열은 읽어 독립 대조했지만, 새 빌드·pytest·mutation 실행·실제 음성·weights·GPU·네트워크·clean VM·서명·법률 검토는 하지 않았다. C00이 보고한 전체 7,567 PASS와 smoke PASS는 작성자 증거로 구분하며 이 문서의 독립 실행 결과로 합산하지 않는다. 현재 후보의 Intel/NVIDIA **runtime** 부재와 기록된 증거 일치는 확인했지만, 위 세 gate/시험 설계 반례가 수정되기 전에는 L-P06을 독립 CLOSED로 판정하지 않는다.

**REVIEW_READY. 현재 OPEN 3건: L06-01(S2), L06-02(S2), L06-03(S3).** 수정 후 동일 검토자가 변경 hash·후보 evidence·원 반례를 재확인해야 한다. 최종 통합·commit·push와 릴리스 수락은 C00 책임이다.

## L06 재확인 — L-P06 수정 후보

2026-11-15 재확인. 제품·시험·설정 파일은 수정하지 않았고, 새 빌드·pytest·Git 명령도 실행하지 않았다. 허용된 리뷰 문서의 이 절만 추가했다. 다음 변경 hash를 읽기 전용으로 대조했다.

| 대상 | SHA-256 |
| --- | --- |
| `packaging/ctranslate2-cpu.json` | `a726a4ed02d41e84ffb0b6089c7cffe3931e638f86f3a75bced9a2bd7b4e710f` |
| `scripts/build_release.py` | `2283075433a4f89c95cae49aa2a693fb6ca70fa1c08a657a2f431be6abfa96f7` |
| `scripts/build_ctranslate2_cpu.py` | `47b8d4c5d902666978200eb1801bb7ed9d812313ae2fd56c6970820a95a1f6fc` |
| `tests/release/test_build_inputs.py` | `c67ce7e7eb3daf0e63f4d4d54f19396be96d8fd8eb4bd9fdbb183ff2c6c6a560` |

### 원 반례 재적용 판정

| 원 반례 | 재확인 근거 | 판정 |
| --- | --- | --- |
| L06-01: 같은 `4.9.0+recoryn.cpu1`인 임의 DLL·`vcomp140.dll` | pin에 CTranslate2 DLL(`b4eeffbe029d40f8977f79525847ef74eda416dc0512eb5b684c45f109cd5702`), `vcomp140.dll`(`036b9b3f7ece8dfd48aeccd77113721c5305043aaa9c64d1e72812252727aa7c`), `_ext`(`eff4ebf9bf2f1d899505f390e8cf885df3e0a0f7c627353ea20eb420b5f20e72`), wheel(`62149b888648d1c9aab856070f6240f542bb7612674b254e7116e9583dc60180`), build report(`cf036b056c6fef28e498c6f57d69832c2071d0b5784813f9a90a3e674622418e`)의 SHA-256이 고정되어 있다. `build_release.py`가 PyInstaller 전 설치 package와 후 frozen 사본을 같은 pin에 대조하고, pin을 입력 snapshot에 넣는다. 후보 `build/l06-final-1794743251`의 세 파일 hash가 pin과 모두 일치한다. | **RECHECKED / CLOSED** |
| L06-02: 부동 MSVC/CMake/redist와 암묵 CPU 옵션 | CPU build script가 MSVC `14.42.34433`, CMake `3.29.5-msvc4`, Python `3.13.1`, 고정 `vcomp140` 경로·hash를 요구한다. `vcvars`/`CMakeCXXCompiler.cmake`와 CMakeCache를 다시 대조하고, CTranslate2 16개·oneDNN 6개 옵션을 명시해 `TOOLCHAIN_MISMATCH`/`CMAKE_OPTION_MISMATCH`로 중단한다. 후보 build report의 source/toolchain/options와 pin이 일치한다. 비트 단위 재빌드를 주장하지 않고 단일 산출물 pin으로 결정한 범위도 문서화되어 있다. | **RECHECKED / CLOSED** |
| L06-03: PE·지연 import·대소문자/UTF-16·우회 변이 미시험 | `test_build_inputs.py`에 import 표 8행, 대소문자/UTF-16 4행, 정규·지연 import를 포함한 가짜 PE 1행, pin 변조/누락 및 pin 손상 경계가 추가되었다. 후보 `ctranslate2.dll`의 import는 CRT와 `vcomp140.dll`뿐이고 금지 Intel/NVIDIA runtime import·marker는 없다. exact pin 대조가 marker 우회만으로 통과하는 경로를 차단한다. | **RECHECKED / CLOSED** |

### 후보 산출물과 고지 대조

후보는 정확 tree `e84123ba83e8595410fef97d72fe9efd6be54412`에서 추출된 `build/l06-final-1794743251`이며, 저장된 결과는 native 105(DECLARED 91, REDISTRIBUTABLE_PROPRIETARY 14, UNMAPPED 0), 입력 149건 일치, smoke PASS다. 저장된 `NOTICE` SHA는 `2762f169fd8837e4370f706ea83435e540f5e7cb4f7627c852361b226b5d2794`, SBOM SHA는 `064e5e66eb3ebb1345f9bb11e0db0ce6b2de5cf4043b45265a07e9ca4a60ecd0`, `native-origins` SHA는 `e55fb6c4aef0529ef928ccd6e2ce5e80634bb7703186167b5020c8ac500f62e8`, provenance SHA는 `213a3ee4da54417f713b36741dcd549c9b2f5ae76761594e2280cf6465634ff7`다. native-map과 native-origins의 105개 경로·상태가 일치하고, SBOM/ct2-native/SOURCES의 CTranslate2 구성요소 귀속도 저장 후보와 일치한다.

후보 DLL에는 CPU 진단 문구(`not compiled with CUDA support`, `not compiled with Intel MKL`, `GenuineIntel`)가 남지만, 이는 dispatch/진단 데이터다. `libiomp5md`, CUDA/cuBLAS/cuDNN/NVIDIA 및 oneMKL/OpenMP runtime import·marker는 관측되지 않았다. 따라서 “Intel/NVIDIA 문자열 0”이 아니라 “금지 runtime marker·import 0”이라는 검증 범위로 기록한다. smoke의 worker/network 거부와 playback PASS는 저장 evidence이며, 실제 음성·weights·GPU·clean VM은 여전히 NOT_RUN이다.

### 독립성·잔여 한계

새 시험과 전체 7,590 PASS, line 93.62%, branch 87.16%, ruff/mypy PASS는 C00이 제공한 결과로 구분하며 이 재확인에서 재실행하지 않았다. 정상 oracle과 변이 경계의 assertion 약화는 코드·결정표에서 발견되지 않았다. `build_ctranslate2_cpu.py`의 pre-wheel 문자열 점검 자체는 기존 대소문자 목록을 사용하지만, release 단계의 UTF-8/UTF-16·대소문자 정규화, 설치 전/후 exact pin hash, PE import 및 frozen 재검사가 원래 세 반례의 우회 경계를 담당한다. 이는 bit-for-bit 재현성이나 실장비 검증을 의미하지 않는다.

**REVIEW_READY — RECHECKED. 최종 OPEN 0건(S0 0 / S1 0 / S2 0 / S3 0).** 원래 L06-01·L06-02·L06-03은 수정 후보와 저장 evidence에서 모두 CLOSED 판정이다. 최종 통합·commit·push 및 릴리스 수락은 C00 책임이다.
