# L08-R 패키지 GPU 확인 도구 독립 검토

작성일: 2026-11-22. 검토자: L08-R / w5:p8 Codex. 작성자: C00. 판정 대상은 작업 트리가 아닌 **tree `98f6ee980688e69cd693ef1313ea18ec0740ad28`**, 비교 기준은 commit `3f4ee9f2d56b5a7a97e8dccb49399b5637babd4e`다. `git diff --stat 3f4ee9f 98f6ee980688e69cd693ef1313ea18ec0740ad28`를 직접 확인했으며 8파일, 691삽입/2삭제였다. 제품·시험·설정·Git 인덱스·번들·설치된 런타임은 수정하지 않았다. 저장소에서는 이 문서 하나만 신규 작성했다.

**판정: 수정 및 재검토 필요. OPEN 5건(S1 3건, S2 2건), S0 0건, S3 0건.** 기존 정상 frozen 실행의 성공은 재현했다. 아래 발견은 그 실행에서 혼입이나 잘못된 GPU 사용이 실제 발생했다는 주장이 아니라, 판정 도구의 반례·관측 누락과 시험 공백이다. 자기 작성 결과를 최종 승인하지 않으며 C00 수정 후 같은 반례 재확인이 필요하다.

## 검토 입력 고정과 실행

`git archive --format=tar 98f6ee980688e69cd693ef1313ea18ec0740ad28`를 Python subprocess로 읽어 OS TEMP의 고유 폴더에 추출했다. 이후 코드 읽기·시험·mutation은 이 사본을 사용했다. 공유 작업 트리의 G01 배정 절과 다른 변경을 검토 입력으로 섞지 않았다.

증거 루트(이하 `R`): `C:/Users/gangd/AppData/Local/Temp/recoryn-l08r-wrzv2i0z`. 정본 사본은 `R/tree`, 입력 map은 `R/snapshot.json`, 독립 반례는 `R/test_independent.py`다. TEMP는 영구 보존을 보장하지 않으므로 아래에 주요 입력·기대·실제 결과와 정확한 변이도 함께 적었다.

| 정본 파일 | SHA256(CR 제거·LF 기준) |
| --- | --- |
| packaging/release_smoke.py | `bd26b1acfb164fbedcf62f523712bc28eebbd887b96ae3230769fa6cca789cd0` |
| packaging/recoryn_release.py | `077f3da7b166d7d53b5be59c34b11c7294f656153cdfea505154ee6aabd031a5` |
| scripts/gpu_frozen_smoke.py | `69c0cfd1fcd9dc1a4ddf6d9f9b3d22946d372aeb1248f5bf0f128abebb148a60` |
| tests/release/test_gpu_smoke.py | `d5caf2e7167d6bceda939193ec28105738cce132a216eedccc27c8cdf1023d81` |
| docs/testing/l08-frozen-gpu-cases.md | `0d58eb0c9a1415ccbdbd9e70cd0d709f8dde0ab85dcd26cb3aca8b168444ac93` |
| docs/implementation/license-review.md | `4dade361a721163b3b420f6460d5351a02545fe64618a4d7eaf747c5186ecc8f` |
| docs/implementation/license-results.md | `427de6134699355bcab94d8c77a3c9da19eb5b1251b008a8282ec1c948afcc1a` |
| docs/collaboration/assignments.md | `3c266fc353f8c109dee90147268c0d31b18ce103a23e02219907e8854b1fe4e9` |

문서 두 개는 L-P08 관련 변경, 배정표는 L08 행만 범위로 검토했다. 아래 행 번호는 모두 위 tree의 파일 기준이다.

실행 환경은 기존 `.venv/Scripts/python.exe`의 Windows CPython 3.13 계열이다. 새 패키지 설치·다운로드·외부 API·음성·실제 Whisper 가중치는 사용하지 않았다. 선택 시험은 `QT_QPA_PLATFORM=offscreen`, `HF_HUB_OFFLINE=1`, `HF_HUB_DISABLE_TELEMETRY=1`, `DO_NOT_TRACK=1`, `PYTHONDONTWRITEBYTECODE=1`, `-B`, `-p no:cacheprovider`와 실행마다 다른 OS TEMP basetemp를 사용했다.

정본 사본 cwd에서 실행한 기존 회귀:

```powershell
D:/project/Recoryn/.venv/Scripts/python.exe -B -m pytest tests/release/test_gpu_smoke.py tests/release/test_smoke.py tests/release/test_build_inputs.py -q -p no:cacheprovider --basetemp C:/Users/gangd/AppData/Local/Temp/recoryn-l08r-wrzv2i0z/pytest-base --tb=short -W error::ResourceWarning
```

**102 passed in 1.93s / exit 0**, 실패·skip·xfail 없음. 별도 `--collect-only`로 L08 파일 **48 tests collected in 0.27s**를 확인했다(`R/collect.log`). 이 48개는 102개 안에 포함되므로 합산하지 않는다.

독립 반례 최종 명령은 cwd `R`에서 다음과 같다.

```powershell
D:/project/Recoryn/.venv/Scripts/python.exe -B -m pytest test_independent.py --rootdir C:/Users/gangd/AppData/Local/Temp/recoryn-l08r-wrzv2i0z -q -p no:cacheprovider --basetemp C:/Users/gangd/AppData/Local/Temp/recoryn-l08r-wrzv2i0z/pytest-independent-4 --tb=short
```

**16 failed / 5 passed in 0.41s**였다. 실패는 거부/정상 별칭 수락을 기대한 독립 assertion에서 발생했다. 분모는 정상 1 + 외부 cuBLAS 2 + 잘못된 module/ext 2 + token 구조 6 + 필드 타입 4 + namespace 외부 경로 2 + 형제 폴더 1 + 대소문자 1 + 모듈 이름 조회 실패 1 + 8.3 별칭 1 = **21행**이다. 최초 helper 실행의 pytest 상위 디렉터리 수집 권한 오류와 helper의 문자열 문법 오류는 각각 rootdir 고정·임시 helper 수정으로 해소했다. 이 두 수집 실패를 제품 반례나 mutation 검출로 세지 않았다. helper 최종 LF SHA256은 `c09f564550b4e31ee9ccaaac85a04af97ebb9ebafd6b8e0080c815d39abd2d29`다.

## 발견 사항

### L08-01 / S1 / OPEN: 외부 cuBLAS가 함께 로드돼도 판정이 PASS

근거: `scripts/gpu_frozen_smoke.py:41`, `:96`, `:106`. 런타임 **내부** 모듈은 기대 5개와 비교하지만 외부 금지 이름은 `ctranslate2.dll`, `libiomp5md.dll`, `_ext.cp313-win_amd64.pyd` 세 개뿐이다. 외부 `cublas64_12.dll`·`cublasLt64_12.dll`을 추가해도 내부 집합은 그대로이고 cuDNN 검사에도 걸리지 않는다.

재현 입력은 손으로 쓴 정상 보고(필수 사실, 런타임 내부 5개, 2개 정수 token sequence, exitcode=0)를 기준으로 다음 한 줄만 바꾸는 것이다.

```python
report["loaded"].append(r"C:\outside\cublas64_12.dll")
# 별도 행: C:\outside\cublasLt64_12.dll
failures = verdict(report, active, [])
```

실제: 두 행 모두 `failures == []`. 독립 node `test_independent.py::test_foreign_cublas_must_fail`의 두 매개변수 행이 assertion FAIL했다. 기대: 외부 런타임 구성요소가 섞인 보고는 PASS하지 않아야 한다. 현재 실제 frozen 정상 보고에서 이 혼입을 관측한 것은 아니다.

제안 수정: 외부 금지 검사를 같은 런타임의 cuBLAS 두 이름까지 확장하고, 정규화·실파일 identity 정책과 함께 적용한다. 기존 내부 누락/추가 파일 시험을 유지하고 **내부 5개 모두 정상 + 외부 DLL 하나 추가** 조합을 독립 oracle로 추가한다.

### L08-02 / S1 / OPEN: 모듈 이름 조회 실패를 조용히 생략해 ‘부재’ 증거가 불완전

근거: `packaging/release_smoke.py:135`~`:139`. EnumProcessModules가 반환한 handle의 GetModuleFileNameW 결과가 0이면 그 항목을 생략한 정상 목록을 반환한다. 목록의 완전성 상태를 report에 넣지 않는다. 따라서 알 수 없는 한 모듈이 cuDNN/외부 CPU DLL일 가능성을 배제하지 못한 채 부재 판정을 할 수 있다.

재현: 임시 반례에서 ctypes API만 fake로 바꿨다. EnumProcessModules는 **6 handles**를 반환하고, 처음 5개의 이름은 정상 런타임 구성요소 5개, 여섯 번째의 GetModuleFileNameW는 0을 반환하게 했다. 실제 `loaded_modules()`는 예외 없이 5개 목록을 반환했다. 그 목록을 정상 report에 넣은 실제 verdict도 `[]`였다.

직접 기록한 `R/enumeration-evidence.json`:

```json
{"enum_handles": 6, "resolved_paths": 5, "verdict": []}
```

독립 node `test_independent.py::test_enumerated_but_unresolved_module_must_fail_closed`는 `DID NOT RAISE OSError`로 FAIL했다. 기대: 모듈 이름 하나라도 불명·잘림이면 부재 검증을 완료로 보지 않고 안전한 오류 또는 `enumeration_complete=False`를 보고해 verdict가 거부해야 한다.

제안 수정: API 반환 길이 0 및 buffer 길이 이상을 실패로 처리하고, 열거 개수/해석 개수·완전성 사실을 검사한다. 이름 조회 실패·잘림·열거 buffer 확장·정상 목록을 fake WinAPI 계약 시험으로 고정한다. 특정 DLL이 실제로 로드됐다는 반례는 아니며, 관측 실패를 PASS 근거로 취급하는 분기 반례다.

### L08-03 / S1 / OPEN: 실제 생성 장치·정밀도를 확인하지 않아 CPU 실행 mutant가 살아남음

근거: `packaging/release_smoke.py:173`, `:180`~`:192`; `scripts/gpu_frozen_smoke.py:82`~`:95`. CUDA 장치 수와 런타임 DLL 로드는 **활성화**의 증거다. `tokens["float16"]`/`tokens["float32"]`라는 키는 요청 이름이며 실제 Whisper 객체의 실행 장치/compute_type을 보고하지 않는다.

임시 사본 `R/probe-cpu`에서 **생성자 한 곳만** 다음과 같이 바꿨다. 원본 tree·번들·런타임은 건드리지 않았다.

```python
# 정상
whisper = ctranslate2.models.Whisper(model, device="cuda", compute_type=compute)
# mutant
whisper = ctranslate2.models.Whisper(model, device="cpu", compute_type="float32")
```

`R/probe-cpu/review_probe_driver.py`가 같은 제품 `_activate_gpu`, 이미 설치된 런타임, 정상 frozen 확인에서 생성한 `R/gpu-real/model-small`을 사용해 소스 spawn probe를 실행했다. 기록은 `R/probe-cpu.log`, `R/probe-cpu.json`이다.

실제:

- 정상 소스 probe: `failures == ["NOT_FROZEN"]`.
- **CPU float32로 두 번 생성한 mutant**: `failures == ["NOT_FROZEN"]`로 동일. 두 token 배열도 서로 같았다. 다른 GPU 관련 실패가 추가되지 않았다.

기대: GPU float16/float32 실행을 확인한다는 판정이라면 CPU 실행·정밀도 바뀜을 별도로 검출해야 한다. 소스 실행을 frozen PASS로 위장하지 않았으며, 변이 frozen EXE를 빌드/실행한 것도 아니다. 정상/변이 모두 소스라는 공통 실패를 유지한 상태에서 **GPU 실행 사실을 검사하는 oracle가 변이를 구분하지 못함**을 직접 확인했다.

제안 수정: 각 인스턴스에서 런타임이 실제 노출하는 `device`, `device_index`, `compute_type`을 관측해 report에 넣고 builder가 기대값과 비교한다. 생성 전에 요청한 상수를 그대로 사실로 복사하면 같은 공백이 남는다. CPU·두 번 float32·다른 GPU index 변이를 검사한다. 문서가 L-P08의 목적을 ‘활성화만 확인’으로 제한하려면 ‘실제 GPU float16/float32 실행 확인’ 주장을 그 범위에 맞춰 조정해야 한다.

### L08-04 / S2 / OPEN: 보고 구조·타입·정확한 모듈 위치가 잘못돼도 PASS

근거: `scripts/gpu_frozen_smoke.py:72`, `:74`, `:77`, `:82`, `:86`~`:96`. 타입 검증이 부분적이다. 동일한 잘못된 token 값은 참 여부와 동등 비교만 통과하면 된다. module/ext도 런타임 아래라는 조건만 있고 해당 catalog 위치와 일치할 필요가 없다.

손으로 쓴 정상 보고에서 아래 값을 **각각 독립적으로** 바꿨다. 실제 결과는 12행 모두 `verdict(...) == []`였다.

| 분할 | 입력 | 행 수 |
| --- | --- | ---: |
| 모듈 위치 | module=`<active>/other/__init__.py`, ext=`<active>/other/unrelated.pyd` | 2 |
| token 값 | 양쪽 값이 각각 문자열 `"success"`, `[1]`, `[[False]]`, `[[None]]`, `[["pretend"]]`, `[[1],[2],[3]]` | 6 |
| 필드 타입 | cuda_devices=True, exitcode=False, exitcode=0.0, bundle=42 | 4 |

독립 nodes: `test_module_identity_must_match_catalog_location`, `test_tokens_must_be_two_integer_sequences`, `test_report_fields_have_exact_types`. 모두 기대 거부 assertion에서 FAIL했다. 이 입력들은 **판정 함수의 합성 보고 반례**이며, 정상 probe가 지금 이 값을 생성했다거나 manager.verify가 존재하지 않는 파일을 허용한다는 뜻은 아니다.

기대: 고정 2 prompts의 결과는 길이 2의 sequence 목록이고 각 sequence는 비어 있지 않은 정수 token 목록이어야 한다. bool/None/문자열/잘못된 batch 수는 거부한다. module과 ext는 각각 정해진 catalog 파일, loaded 목록의 extension과 일관돼야 한다. exit/device/bundle도 명시 타입을 검사한다.

제안 수정: report schema 검증을 선행하고 타입 오류는 안정된 실패 코드로 반환한다. `type(n) is int` 등 bool 구별, path exact identity, token shape/범위를 독립 fixture로 고정한다. 기존 required-key·빈 token 시험은 유지한다.

### L08-05 / S2 / OPEN: 같은 실폴더의 8.3 별칭을 다른 런타임으로 오판

근거: `scripts/gpu_frozen_smoke.py:56`~`:61`, `:98`. normcase(abspath)와 문자열 prefix는 8.3 별칭을 canonical long path와 같은 경로로 만들지 않는다.

재현: TEMP 아래 긴 이름 폴더를 만들고 실제 GetShortPathNameW로 얻은 짧은 경로가 `Path(short).samefile(active) == True`임을 확인했다. 보고 경로들은 long path, verdict의 active는 이 동일 폴더의 short path로 전달했다. 런타임 폴더를 복사·변경하지 않고 별도 임시 폴더로만 확인했다.

실제: `MODULE_OUTSIDE_RUNTIME`, `EXT_OUTSIDE_RUNTIME`, `RUNTIME_MODULE_SET_MISMATCH`, `FOREIGN_CTRANSLATE2_LOADED` 네 오류가 났다. `test_independent.py::test_short_path_alias_should_not_change_verdict`는 **skip 없이 assertion FAIL**했다. 기대: 같은 실폴더·동일 허용 파일이면 같은 판정이어야 한다. 이는 거짓 PASS가 아닌 **거짓 FAIL**이다.

제안 수정: 허용된 local 경로의 canonical/파일 identity를 기준으로 비교하거나, 지원하지 않는 별칭을 CLI 입력에서 명시적으로 차단한다. 자동으로 symlink/UNC까지 허용하는 확장은 피한다. long/short 양방향, 대소문자, 형제 폴더, `..` 정규화와 링크 거부를 분리해 시험한다.

## 확인한 정상 경로와 제한

### 제품과 같은 활성화 순서

정본 `packaging/release_smoke.py:152`~`:167`은 `_block_network()` 후 `recoryn.app.inference._activate_gpu`를 호출하고 **성공 뒤** numpy/faster_whisper를 import한다. `src/recoryn/app/inference.py`의 제품 `_worker`도 offline 환경 지정 뒤 `_activate_gpu`, 이후 FasterWhisperProvider lazy 경로를 사용한다. probe가 별도의 GPU 활성화 구현으로 우회하지 않는 것을 확인했다. GPU smoke는 부모에서 CTranslate2를 먼저 올린 뒤 재사용하는 경로가 아니라 새 spawn child 안에서 실행한다.

현재 frozen 실행에서도 `faster_whisper.transcribe.ctranslate2 is sys.modules["ctranslate2"]`가 True였다. 다만 실제 FasterWhisperProvider/WhisperModel의 tokenizer·PCM·전체 전사 경로는 이 probe가 실행하지 않으며 문서도 NOT_RUN으로 구분한다. L08-03의 실제 device/precision 관측 공백은 별개다.

### 무전송·기존 smoke·배포 증거

- 새 builder는 `GpuRuntimeManager.status/verify`만 사용하며 `install`, `_wheels`, downloader를 호출하지 않는다. 모델은 기존 `compare_ctranslate2_builds.build_model`의 seed 고정 무작위 spec 생성이다. 정본 경로를 읽어 외부 다운로드 호출을 찾지 못했다.
- 새 child와 probe 부모에는 기존 `_block_network`의 Python socket audit와 offline 환경이 적용된다. 이번 실행에서 다운로드·외부 계정/API 사용은 하지 않았다. **native DLL/driver 후속 트래픽의 OS 수준 무전송 인증은 수행하지 않았다.** Python audit가 OS/native 전체를 관측한다는 주장을 추가하면 안 된다.
- `packaging/release_smoke.py`의 변경은 새 helper/함수/상수 추가이고 기존 `run`, `_child`, playback 판정 본문은 diff상 불변이다. `recoryn_release.py`의 기존 `--release-smoke` 분기는 그대로이며, 새 옵션이 첫 인자일 때만 별도 분기로 간다.
- `scripts/build_release.py`의 기본 smoke 판정·release evidence generator·manifest/SBOM/NOTICE 규칙은 이번 tree에서 바뀌지 않았다. 기존 smoke/빌드 입력 선택 회귀를 포함한 102 PASS를 확인했다. 다만 packaging helper bytes가 바뀌므로 **기존 artifact hash를 새 tree의 artifact hash로 재사용할 수 없다**. 새 정본 빌드의 inventory/provenance/hash는 C00 최종 게이트다.
- 이번 검토에서 기본 frozen `--release-smoke`를 다시 실행하지 않았다. 그것은 실제 음소거 재생 경로를 포함하므로, 허용된 GPU 실행만 수행했다. 기존 `build/l08-1795356679/smoke.stdout.json`은 빌드 작성자의 이력이며 새 직접 실행으로 계산하지 않는다.

### Windows 경로 관점

| 관점 | 직접 확인 | 판정 |
| --- | --- | --- |
| 대소문자 | 기존 시험 및 독립 `test_case_change_is_valid` PASS | 해당 경계 정상 |
| 같은 접두사 형제 폴더 | 기존 시험 및 독립 `test_sibling_prefix_never_passes` PASS | separator 경계 정상 |
| 8.3 이름 | 실제 WinAPI 별칭 + samefile, 독립 assertion FAIL | L08-05 |
| UNC/device namespace | `GpuRuntimeManager(Path(r"\\localhost\C$\fake-runtime"))`를 local 검증 경계에서 호출 | `ValidationError: UNC and device namespace roots are not supported`; 원격 서버 조회 없이 차단 |
| 링크/reparse | TEMP에서 빈 대상과 NTFS junction을 만든 뒤 그 경로로 manager 생성 | `ValidationError: Links and reparse points are not supported` |
| 외부 namespace 보고 | `\\?\outside...`, `\\localhost\C$\outside...`를 module 필드에 넣은 두 합성 행 | 모두 verdict 거부, 독립 시험 PASS |

링크 행은 일반 symlink와 동일한 `check_path`의 reparse 거부 분기를 **실제 NTFS junction**으로 확인한 것이다. 일반 symlink를 별도로 만들었다고 주장하지 않는다. junction·빈 대상은 `R` 아래에만 생성했고 기존 런타임·번들의 링크/ACL을 변경하거나 정리하지 않았다. `_inside` 단독은 실파일 identity 검사가 아니므로 main의 기존 manager guard와 혼동하지 않는다.

## 시험 분모와 mutation 대조

정본 시험의 결함 표·기대 코드가 구현의 EXPECTED_RUNTIME_MODULES/DLL_LOAD_ORDER에서 자동 파생되지 않고 손으로 쓰인 것을 확인했다. 특히 test의 RUNTIME_FILES와 builder의 고정 목록을 대조하는 node가 있다. 다음 합계는 실제 48개 수집과 맞는다.

| 가족 | 정의 분모 | 실제 대응 |
| --- | ---: | --- |
| 정상 보고·대문자 | 2 | 2 |
| FAULTS 단일 결함 | 23 | 23 매개변수 행 |
| cuDNN 외부/내부 | 2 | 2 |
| pyc | 1 | 1 |
| 필수 사실 누락 | 10 | 10 매개변수 행 |
| 필수/모듈 목록 고정 | 2 | 2 |
| 자식 실패 보고 | 1 | 1 |
| probe 없음/timeout·진입점 3행·인자 누락·현재 모듈 열거 | 7 | 7 |
| 합계 | **48** | **48** |

문서의 ‘복합 2’ 중 외부 cuDNN 행은 실제로 CUDNN_LOADED 하나만 기대하고, 내부 cuDNN만 두 코드를 기대한다. 분모 오류는 아니지만 분류 명칭은 ‘cuDNN 위치 2행’으로 쓰면 명확하다. 이 표는 정의된 대표 집합의 수이며 Windows 경로·보고 schema·모듈 해석 실패의 전수 분모는 아니다. 빠진 경계는 L08-01/02/04/05에서 재현했다.

작성자의 ‘판정 18 + 진입점 1 + probe 2 = 21’ 주장을 전부 재실행한 것으로 기록하지 않는다. **그중 판정 3 + 진입점 1 + probe 2 = 6개**를 별도 임시 사본에서 직접 재현했고, 추가 CPU 변이 1개가 살아남았다. 원본 baseline은 앞서 102 PASS, 소스 probe baseline은 NOT_FROZEN만 발생했다.

| 독립 변이 | 정확한 변경 | 실제 검출·결과 |
| --- | --- | --- |
| 판정/version | `if report["version"] != "4.9.0":` → `if False:` | `test_each_single_fault_fails_with_its_own_code[cpu build version]` 1 assertion FAIL |
| 판정/foreign | 외부 `FOREIGN_NAMES and not _inside` 조건을 False로 | `[bundled ct2 dll]` 1 assertion FAIL |
| 판정/required | `if missing:` → `if False:` | missing-key 10 assertion FAIL |
| 진입점 | activate 조건 분기 반환을 `return 0`으로 | dispatch 매개변수 2 FAIL/1 PASS |
| probe/동일 모듈 | `transcribe.ctranslate2 is ctranslate2` → False | 정상 소스의 NOT_FROZEN에 `FASTER_WHISPER_OTHER_MODULE` 추가 |
| probe/로드 목록 | `report["loaded"] = loaded_modules()` → `[]` | 정상 소스의 NOT_FROZEN에 `RUNTIME_MODULE_SET_MISMATCH` 추가 |
| 추가 probe/실제 장치 | 생성자 `device="cuda", compute_type=compute` → `device="cpu", compute_type="float32"` | **survived**, NOT_FROZEN 하나만 유지; L08-03 |

변이 실행 driver는 `R/run_mutations.py`, 결과는 `R/mutation-results.json`, 판정/진입점 로그는 `R/mutant-{version,foreign,required,entry}.log`, 소스 probe 로그는 `R/probe-{normal,identity,loaded}.log`다. CPU 변이는 별도 `R/probe-cpu.json`에 보존했다. 변이는 제품 workspace가 아닌 정본의 임시 복사본에서 각각 하나씩 적용했다. import/collection/timeout 실패를 검출로 집계하지 않았다.

## 실제 frozen GPU 재실행과 문서 대조

정본 사본의 builder 스크립트를 사용해 다음을 직접 실행했다. 대상 bundle과 runtime은 절대 경로로 고정했고 output만 새 TEMP 경로다.

```powershell
# cwd: R/tree
D:/project/Recoryn/.venv/Scripts/python.exe -B scripts/gpu_frozen_smoke.py --bundle D:/project/Recoryn/build/l08-1795356679/dist/Recoryn --runtime-root D:/project/Recoryn/build/gpu-e2e2 --output C:/Users/gangd/AppData/Local/Temp/recoryn-l08r-wrzv2i0z/gpu-real
```

직접 결과: **exit 0 / status PASS / failures=[] / returncode=0**. `R/gpu-real/gpu-smoke.json` LF SHA256은 `bc266f6dafafce4956ec2284a160befb99df8d683172dee4a76649874350189d`다. report는 frozen=True, child exitcode=0, runtime 4.9.0, CUDA 장치 1, faster-whisper 동일 모듈 True, 로드 모듈 **108개**, runtime 구성요소 **5개**였다. cuDNN·번들 vcomp140이 없고 runtime 내부 pyc 목록은 비었다. 두 precision token 배열은 같았다.

```text
sequence 1: [18,18,18,18,18,18,18,18,16,18,16,51]
sequence 2: [18,18,18,18,18,18,18,18,16,18,39,51]
```

기존 `build/l08-gpu-try1/gpu-smoke.json`도 직접 읽었다. LF SHA256이 문서의 `65c478c1f447a7d68478eb26b79398f0786f0286c583382b6074640b361a7b23`과 같았고 108개/5개/버전/경로/두 token 배열도 일치했다. 기존 결과를 새로 생성한 것으로 표시하지 않았다. 장비/driver의 표기는 결과 문서 이력을 인용하며 이번에 nvidia-smi로 다시 조회하지 않았다.

**정확한 tree 빌드와 구분할 사항:** `build/l08-1795356679/inputs`와 검토 tree의 LF hash를 직접 대조했다.

| 빌드 입력 | tree와 동일 여부 |
| --- | --- |
| packaging/release_smoke.py | 동일 |
| src/recoryn/app/inference.py | 동일 |
| src/recoryn/models/gpu_runtime.py | 동일 |
| packaging/recoryn_release.py | **불일치: 종료 코드 조건 한 줄** |

번들 입력은 `return 0 if report.get("activate") is None else 2`, 검토 tree는 `return 0 if "activate" in report and report["activate"] is None else 2`다. 번들 입력의 LF SHA256은 `fa6a1b09845f453309037d9b755a6408fb5494b8c60bef1104c71361d4e41095`다. 따라서 재실행 PASS는 **지정된 커밋 전 작업 트리 번들**의 결과다. `license-results.md`의 ‘정확한 tree 빌드에서는 다시 확인’이라는 NOT_RUN 구분은 타당하며 이 체크포인트를 닫지 않았다. 새 frozen 빌드·전체 입력 전수 대조·정확한 tree GPU 재실행은 C00 통합 게이트로 남긴다. 이 차이는 문서에서 이미 명시한 미완료 조건이므로 별도 신규 OPEN으로 중복 집계하지 않는다.

문서 표현 중 ‘probe의 자기 보고를 믿지 않고’는 **자기 PASS 문자열 대신 별도 규칙으로 사실을 판정한다**는 범위로 읽어야 한다. 현재 report의 진위·완전성·GPU 실제 실행을 외부에서 독립 인증하는 것은 아니다. L08-02/03/04 수정 및 설명 축소가 필요하다. 실제 음성·실제 Whisper weights·WhisperModel 전체 전사·GUI 동의/설치 조작·다른 GPU/driver·native 전체 무전송은 이번에도 NOT_RUN이다.

## 인계 상태

OPEN: **L08-01 S1, L08-02 S1, L08-03 S1, L08-04 S2, L08-05 S2**. 제품 행동을 바꾼 결함이나 런타임 오염·다운로드 발생을 관측한 것은 아니다. 확인 도구의 거짓 PASS/관측 실패 및 경로 거짓 FAIL을 수정하고 독립 원 반례를 재실행해야 한다. 작성자 21개 mutation의 일부 재현 성공을 전체 oracle 충분성으로 확대하지 않는다. 이 문서는 REVIEW_READY이며 최종 CLOSED/통합 판정은 C00이 재확인 근거를 받아 수행한다.

## RECHECK

2026-11-22, 같은 검토자 L08-R / w5:p8 Codex. 정본은 **2판 tree `d9e344de6238169b4e154e5e25f9df6872566ef2`**, 비교 기준은 `3f4ee9f2d56b5a7a97e8dccb49399b5637babd4e`, 1판은 `98f6ee980688e69cd693ef1313ea18ec0740ad28`다. 위 1차 내용과 당시 OPEN 판정은 이력으로 보존한다. 아래가 최신 독립 판정이다.

**L08-01~05 모두 RECHECKED. 신규 L08-06/S2 OPEN 1건. 현재 OPEN은 S0 0 / S1 0 / S2 1 / S3 0이다.** RECHECKED는 같은 검토자의 원 반례 확인이며 최종 CLOSED 처리는 C00 통합 절차에 따른다.

### 재확인 입력과 실행 고정

`git show d9e344de:<경로>`로 변경을 읽고, 해당 tree를 `git archive`로 새 OS TEMP에 추출해 시험·반례·변이를 실행했다. `git diff --stat 2c7d260b d9e344de`도 직접 확인했다. 차이는 `docs/implementation/license-results.md` 하나이며 코드·시험·경우의 수 문서는 같았다. 작업 트리의 다른 변경은 사용하지 않았다.

새 증거 루트(이하 `R2`): `C:/Users/gangd/AppData/Local/Temp/recoryn-l08r-recheck-e6swm4sq`. 정본 사본은 `R2/tree`다. 재확인 시작 시 기존 리뷰 LF SHA256은 `20908762a5d41582f5c19d688e553e19bf1b3bcea6a1e18a3afd3bcea79f1b73`였으며, `R2/review-before.bin`으로 첫 문서 bytes를 보존했다.

| 2판 입력 | SHA256(CR 제거·LF 기준) |
| --- | --- |
| packaging/release_smoke.py | `9d03100db00bd999583c636c14868d8c78eecf007945f7a62ba7416b76fb18b2` |
| packaging/recoryn_release.py | `077f3da7b166d7d53b5be59c34b11c7294f656153cdfea505154ee6aabd031a5` |
| scripts/gpu_frozen_smoke.py | `56c53e5fd082bdd0f6c5323ad0f33fa1e9d409a62a82ec50357db8ac0306f95a` |
| tests/release/test_gpu_smoke.py | `903cad63f80898b7e56a5a6fb1ed326245c623d9d93c318c609c58e838619c82` |
| docs/testing/l08-frozen-gpu-cases.md | `e950ad3e48c9a895e5f5631fd2de11c212c9fe65646a458d420a973a08d18e61` |
| docs/implementation/license-results.md | `3a53e0a078421a9de7485b0fb4048d9adb8b249024bad646a4979c90d46c45ae` |

기존과 같은 interpreter·offscreen·offline/telemetry 차단 환경·`-B`·`-p no:cacheprovider`·고유 TEMP basetemp를 사용했다. 런타임·번들은 수정/삭제하지 않았고 다운로드·설치·실음성·외부 API를 사용하지 않았다.

```powershell
# cwd: R2/tree
D:/project/Recoryn/.venv/Scripts/python.exe -B -m pytest tests/release/test_gpu_smoke.py tests/release/test_smoke.py tests/release/test_build_inputs.py -q -p no:cacheprovider --basetemp C:/Users/gangd/AppData/Local/Temp/recoryn-l08r-recheck-e6swm4sq/pytest-existing --junitxml C:/Users/gangd/AppData/Local/Temp/recoryn-l08r-recheck-e6swm4sq/existing.xml --tb=short -W error::ResourceWarning
```

직접 결과: **148 passed in 2.56s / exit 0**, 실패·skip·xfail 없음. L08 시험 94개와 기존 smoke/빌드 입력 회귀 54개다. 경우의 수 문서의 B 분모 **82**(4+45+14+1+2+1+11+3+1), C 분모 **12**(1+1+1+4+4+1)의 합계 **94**와 일치한다. 8.3 두 방향도 이번 환경에서 skip 없이 통과했다. 작성자의 전체 7788 PASS·정적 검사·단위 mutation 34/34는 이번에 전부 재실행한 수치가 아니며 결과 문서의 이력으로만 구분한다.

### 1차 독립 반례 21행 재실행

원 `R/test_independent.py`가 여전히 존재하고 LF SHA256이 1차 기록의 `c09f564550b4e31ee9ccaaac85a04af97ebb9ebafd6b8e0080c815d39abd2d29`와 같은 것을 확인했다. 이를 **새 TEMP 사본** `R2/test_independent_recheck.py`로 옮겼다. 변경은 정본 import 경로, 정상 fixture에 2판 필수 `runs` 사실 추가, 그리고 원 결함의 거부 여부를 새 코드명과 정확히 대조하는 assertion뿐이다. 입력 fault 21행은 유지했다. `runs`가 없어서 모든 행이 MISSING_RUNS로 거부되는 결과를 수정 검증으로 오인하지 않았다. 정상 대조군의 runs는 손으로 쓴 CUDA/[0]/요청 정밀도 두 건이며 대상의 상수에서 생성하지 않았다.

재확인 helper LF SHA256: `ec1f39aec00fe32f0cfe82df9867d6f754d5231208da32907a19166972a73e4b`.

```powershell
D:/project/Recoryn/.venv/Scripts/python.exe -B -m pytest C:/Users/gangd/AppData/Local/Temp/recoryn-l08r-recheck-e6swm4sq/test_independent_recheck.py --rootdir C:/Users/gangd/AppData/Local/Temp/recoryn-l08r-recheck-e6swm4sq -q -p no:cacheprovider --import-mode=importlib --basetemp C:/Users/gangd/AppData/Local/Temp/recoryn-l08r-recheck-e6swm4sq/pytest-original-counterexamples --junitxml C:/Users/gangd/AppData/Local/Temp/recoryn-l08r-recheck-e6swm4sq/counterexamples.xml --tb=short
```

**21 passed in 0.57s / exit 0**, skip 0. 아래 기대값과 실제 결과가 행별로 일치했다. `[]`는 정상 PASS, 오류 목록은 의도한 거부여서 해당 반례 시험의 PASS다.

| 원 행 | 1차와 같은 입력/관점 | 2판 기대 및 실제 | 재확인 |
| --- | --- | --- | --- |
| 1 | 정상 보고 | `[]` | PASS |
| 2 | 내부 정상 5개 + 외부 cublas64_12.dll | `[FOREIGN_RUNTIME_LOADED]` | PASS |
| 3 | 내부 정상 5개 + 외부 cublasLt64_12.dll | `[FOREIGN_RUNTIME_LOADED]` | PASS |
| 4 | module=`active/other/__init__.py` | `[MODULE_NOT_RUNTIME_FILE]` | PASS |
| 5 | ext=`active/other/unrelated.pyd` | `[EXT_NOT_RUNTIME_FILE]` | PASS |
| 6 | token 양쪽이 문자열 `success` | `[TOKENS_MALFORMED]` | PASS |
| 7 | token 양쪽이 `[1]` | `[TOKENS_MALFORMED]` | PASS |
| 8 | token 양쪽이 `[[False]]` | `[TOKENS_MALFORMED]` | PASS |
| 9 | token 양쪽이 `[[None]]` | `[TOKENS_MALFORMED]` | PASS |
| 10 | token 양쪽이 `[["pretend"]]` | `[TOKENS_MALFORMED]` | PASS |
| 11 | token 양쪽이 `[[1],[2],[3]]` | `[TOKENS_MALFORMED]` | PASS |
| 12 | cuda_devices=True | `[BAD_TYPE_CUDA_DEVICES]` | PASS |
| 13 | exitcode=False | `[CHILD_EXIT_NONZERO]` | PASS |
| 14 | exitcode=0.0 | `[CHILD_EXIT_NONZERO]` | PASS |
| 15 | bundle=42 | `[BAD_TYPE_BUNDLE]` | PASS |
| 16 | module이 외부 device namespace 경로 | `[MODULE_NOT_RUNTIME_FILE]` | PASS |
| 17 | module이 외부 localhost UNC 경로 | `[MODULE_NOT_RUNTIME_FILE]` | PASS |
| 18 | module이 이름 접두사만 같은 형제 폴더 | `[MODULE_NOT_RUNTIME_FILE]` | PASS |
| 19 | 정상 경로의 대소문자 변경 | `[]` | PASS |
| 20 | fake WinAPI 6 handles 중 마지막 이름 조회 반환 0 | `OSError(MODULE_NAME_UNRESOLVED)` | PASS |
| 21 | 실제 GetShortPathNameW·samefile로 확인한 같은 폴더 별칭 | `[]` | PASS, skip 없음 |

16~17행의 판정 거부 자체는 통과했다. **거부하기 전에 경로 해석을 수행하는 부작용**은 1차 assertion의 관측 대상이 아니었으며 아래 신규 L08-06으로 분리했다.

### 원 발견별 RECHECK 판정

| ID | 판정 | 직접 재확인 근거 |
| --- | --- | --- |
| L08-01 | **RECHECKED** | 위 2·3행이 정상 내부 집합을 그대로 둔 외부 cuBLAS 혼입을 정확히 FOREIGN_RUNTIME_LOADED로 거부. 새 기존 시험의 다른 버전 cuBLAS·손으로 쓴 FOREIGN_NAMES 대조도 148 PASS에 포함 |
| L08-02 | **RECHECKED** | 위 20행의 실제 loaded_modules fake WinAPI 경로가 부분 목록을 반환하지 않고 MODULE_NAME_UNRESOLVED로 실패. 2판 module_paths의 None/빈 이름, `_gpu_child`의 loaded=None/loaded_error 및 schema BAD_TYPE_LOADED 시험도 직접 실행 |
| L08-03 | **RECHECKED** | 아래의 원 CPU 생성 mutant가 정상 소스와 다른 RUN_NOT_ON_CUDA·RUN_COMPUTE_TYPE_MISMATCH로 거부됨. 실제 객체 대신 요청 상수로 runs를 채우는 mutant도 fake 객체 시험 assertion에서 FAIL |
| L08-04 | **RECHECKED** | 위 4~15행 12개가 정확한 파일 위치·token 구조·정확한 타입별 코드로 거부. 정상 대조군 통과. 모델 객체 runs도 별도 구조 검사로 연결됨 |
| L08-05 | **RECHECKED** | 위 21행과 정본의 8.3 양방향 시험이 skip 없이 통과. 대소문자/형제 폴더 경계도 유지. realpath의 별도 부작용은 신규 L08-06이지 원 거짓 FAIL의 미해결로 중복 집계하지 않음 |

원 CPU 생성 변이는 1차와 정확히 같은 한 줄로 `R2/source-cpu`의 임시 사본에만 적용했다.

```python
# 정상
whisper = ctranslate2.models.Whisper(model, device="cuda", compute_type=compute)
# 원 반례 mutant
whisper = ctranslate2.models.Whisper(model, device="cpu", compute_type="float32")
```

같은 설치 런타임과 `R2/gpu-exact/model-small`의 무작위 가중치로 소스 spawn probe를 실행했다. `R2/run_recheck_mutations.py`, `R2/mutation-results.json`과 각 로그에 남겼다.

| 실행 | 실제 runs | 실제 판정 |
| --- | --- | --- |
| 정상 소스 | 두 건 모두 cuda/[0], 각각 float16·float32 | `[NOT_FROZEN]` |
| 원 CPU mutant | 두 건 모두 cpu/[0]/float32 | `[NOT_FROZEN, RUN_NOT_ON_CUDA, RUN_COMPUTE_TYPE_MISMATCH]` |
| 요청 상수 복사 mutant | device/index/compute_type 사실을 객체 property 대신 cuda/[0]/반복문의 compute로 채움 | `test_the_probe_reports_what_the_model_runs_on_not_what_it_asked_for` **1 assertion FAIL in 0.48s** |

소스 실행은 frozen이 아니므로 두 경우에 공통 NOT_FROZEN을 유지했다. 타입 단계에서만 멈춘 결과가 아니며 모델 실제 장치 관측으로 원 변이를 구분했다. 새 34개 단위 mutant 전체나 다른 두 실제 GPU probe mutant까지 이번에 모두 재실행했다는 주장은 하지 않는다.

### L08-06 / S2 / OPEN: UNC 보고 경로를 거부하기 전에 realpath가 Windows 경로 해석기에 넘김

**신규 변경 근거:** 2판 `scripts/gpu_frozen_smoke.py:84`~`:95`의 `_norm`은 이제 `os.path.realpath(path)`를 호출한다. `:144` 이후 verdict는 `module`, `ext`, `loaded`의 문자열 타입을 검사하지만 UNC 경로를 파일시스템 해석 전에 차단하지 않는다. loaded 집합·외부 이름 검사에서 `_inside`를 호출하면서 보고 경로가 Windows native 최종 경로 해석기로 들어간다. 원래 1판 abspath 정규화에는 이 OS 해석이 없었다.

**입력·절차:** 정상 report에 `loaded.append(r"\\review.invalid\share\cublas64_12.dll")`만 추가했다. 실제 네트워크 접근을 하지 않도록 **`ntpath._getfinalpathname`의 해당 UNC 호출을 spy가 가로채고 입력 문자열을 그대로 반환**하게 했다. 다른 로컬 경로 처리는 기존 함수를 사용했다. spy가 원 함수를 해당 UNC에 호출하지 않으므로 원격 호스트 접속은 실행하지 않았다.

TEMP 독립 node `R2/test_new_boundary.py::test_unc_loaded_path_must_not_reach_windows_path_resolution`의 oracle:

1. report는 최종적으로 FOREIGN_RUNTIME_LOADED로 거부해야 한다.
2. 그 전에 UNC가 OS 최종 경로 해석기에 전달되면 안 된다.

**실제:** 첫 assertion은 통과했지만 두 번째가 FAIL했다. 실제 verdict 호출에서 spy가 동일 UNC를 **2회** 관측했다. 별도로 같은 `_inside(UNC, local_active)`를 1판/2판에서 비교한 `R2/boundary-comparison.json` 결과는 다음과 같다.

```text
1판: inside=False, UNC용 OS resolver 호출 0회
2판: inside=False, UNC용 OS resolver 호출 1회
```

재현 명령:

```powershell
D:/project/Recoryn/.venv/Scripts/python.exe -B -m pytest C:/Users/gangd/AppData/Local/Temp/recoryn-l08r-recheck-e6swm4sq/test_new_boundary.py --rootdir C:/Users/gangd/AppData/Local/Temp/recoryn-l08r-recheck-e6swm4sq -q -p no:cacheprovider --import-mode=importlib --basetemp C:/Users/gangd/AppData/Local/Temp/recoryn-l08r-recheck-e6swm4sq/pytest-new-boundary --tb=short
```

**1 failed in 0.30s**, `UNC path reached the OS final-path resolver before rejection` assertion. helper LF SHA256: `d18770f7c3964d3a6f60ab63e1841b3cced4ee627a81fb32c025f988d048d829`.

**영향·한계:** 이는 정상 frozen 실행의 거짓 PASS나 실제 원격 전송 관측이 아니다. 로컬 경로만 받는 manager의 guard를 통과한 **active root**와 달리, probe가 보고한 외부 module 경로에는 그 guard가 적용되지 않는다는 새 부작용이다. UNC native 경로 해석은 원격 파일시스템 조회가 가능한 경계이고, Python socket audit가 이를 차단한다고 보장할 수 없다. 검증용 보고의 외부 경로를 거부하려고 해석하는 과정에서 외부 파일시스템 접근까지 시도하지 않아야 한다. 실장비 OS 수준 무전송 인증을 새로 요구하는 것이 아니라 **명시적으로 배제할 입력을 OS에 넘기기 전 거부**하라는 수정 제안이다.

**제안 수정:** `_norm` 또는 그 호출 전 공통 경계에서 UNC/remote device namespace를 순수 문자열 검사로 거부하고, 지원하는 로컬 drive/namespace에 대해서만 realpath를 호출한다. 실패는 안정된 경로 오류 코드로 반환한다. 8.3 양방향 정상·대소문자·형제 폴더 시험을 유지하면서, UNC와 `\\?\UNC\...`·상대 경로가 UNC cwd로 귀결되는 경우를 fake native resolver로 검사한다. 제품/번들/런타임 수정 없이 도구·시험 경계에서 처리할 수 있다.

### 정확한 tree 번들 실제 GPU 결과

요청한 기존 설치 런타임과 **2판 정확한 tree 번들**로 다음을 직접 실행했다. output만 새 TEMP 폴더다.

```powershell
# cwd: R2/tree
D:/project/Recoryn/.venv/Scripts/python.exe -B scripts/gpu_frozen_smoke.py --bundle D:/project/Recoryn/build/l08b-exact-1795358709/dist/Recoryn --runtime-root D:/project/Recoryn/build/gpu-e2e2 --output C:/Users/gangd/AppData/Local/Temp/recoryn-l08r-recheck-e6swm4sq/gpu-exact
```

**직접 결과: PASS / failures=[] / returncode=0 / exit 0.** `R2/gpu-exact/gpu-smoke.json`의 LF SHA256은 `507c667efe8b493130dd82584eedd7a8fda0e2babc055ae4f85a69c8f783b522`다.

- frozen=True, child exitcode=0, runtime 4.9.0, CUDA 장치 1, faster-whisper 동일 모듈 True.
- 실제 객체가 보고한 runs: float16은 cuda/[0]/float16, float32는 cuda/[0]/float32.
- 로드 모듈 108개, runtime 내부는 기대 5개. runtime 내부 pyc 목록은 `[]`, 실행 전후 manager.verify가 성공했다.
- 두 precision token은 서로 같고 1차에 기록한 두 sequence와 같았다.

`build/l08b-exact-1795358709/inputs/build-inputs.json`의 **150개 입력**은 실제 파일의 raw SHA256·size와 모두 일치했다. 같은 150개 입력 파일을 검토 tree와 LF 기준으로 전수 비교해 **불일치 0개**였다. 1차에서 달랐던 `packaging/recoryn_release.py`도 이번에는 같았다. 이 대조는 빌드 입력 연결이며 서명·clean VM·모든 배포물 진위 인증으로 확대하지 않는다.

결과 문서의 2판 작업 범위·NOT_RUN 구분과, PASS 문자열 대신 사실을 별도 규칙으로 판단하되 보고 자체를 인증하지 않는다는 표현 축소는 타당하다. 작성자의 GPU 결과 hash `f55fb870...`는 별도 실행 이력이며 이번 직접 실행의 hash로 쓰지 않았다. 실제 음성·Whisper weights·전체 WhisperModel 전사·GUI 동의/설치 조작·다른 GPU/driver·native 전체 무전송은 이번에도 검증하지 않았다.

### RECHECK 인계

원 발견 **5/5 RECHECKED**, 원 독립 반례 **21/21 PASS**, 기존 선택 **148 PASS**, 원 CPU 생성 mutant 및 요청 상수 복사 mutant 검출을 확인했다. 새 **L08-06/S2 1건 OPEN**이므로 ‘OPEN 0’으로 종결하지 않는다. C00이 경로 해석 전 차단을 수정하면 같은 native resolver spy와 기존 8.3 시험으로 재확인한다. 이 절 추가 외 저장소 파일과 설치 runtime·bundle은 변경하지 않았다.

## RECHECK 2

2026-11-23, L08-R / w5:p8 Codex. 대상은 **3판 tree `043de2aa57afaa533f05b6ef34eea2f101e7429b`**이며 2판 `d9e344de6238169b4e154e5e25f9df6872566ef2`와 비교했다. 기존 1차·RECHECK 내용은 이력으로 보존한다.

**L08-06 RECHECKED. 새로 재현한 결함 없음. 현재 OPEN은 S0 0 / S1 0 / S2 0 / S3 0이다.** RECHECKED는 원 반례에 대한 독립 확인이며 최종 CLOSED/통합 결정은 C00 소유다. 아래 SKIP과 미검증 범위를 전체 무전송 인증으로 확대하지 않는다.

### 입력과 실행 고정

`git diff --stat d9e344de 043de2aa57afaa533f05b6ef34eea2f101e7429b` 결과를 직접 확인했다. 변경은 `scripts/gpu_frozen_smoke.py`, `tests/release/test_gpu_smoke.py`, `docs/testing/l08-frozen-gpu-cases.md`, `docs/implementation/license-results.md` **4파일, 119 insertions / 10 deletions**뿐이다. packaging·src는 2판과 같다.

해당 tree를 읽기 전용 `git archive`로 OS TEMP의 새 사본에 추출했다. 이하 `R3 = C:/Users/gangd/AppData/Local/Temp/recoryn-l08r-recheck3-qbb2y0yr`, 정본 사본은 `R3/tree`다. 작업 트리의 다른 변경으로 판정하지 않았다. 추가 전 리뷰 bytes를 `R3/review-before.bin`에 보존했으며 LF SHA256은 **`82477f122246f2445d6863eb30468866f8dd873e1262294d9b27e4c043a81774`**다.

| 3판 입력 | SHA256(CR 제거·LF 기준) |
| --- | --- |
| scripts/gpu_frozen_smoke.py | `f1d151405e3c046c972b61b82d46a91557eda3f6adb373c5333e7c6a99881226` |
| tests/release/test_gpu_smoke.py | `20dea5b8821cb9bd69b4129721e746672b811945b26c39ebf0499689d8c880db` |
| docs/testing/l08-frozen-gpu-cases.md | `89cc42d9cb0906682062f96915edaea7cad569894fac934b962bf67043e04d46` |
| docs/implementation/license-results.md | `9694047ec27e3d05e9ade8d1d133a102daddd87eb2e080fe8a14392e86c6252c` |

실행은 기존 venv interpreter, `-B`, `QT_QPA_PLATFORM=offscreen`, bytecode 억제, Hugging Face/transformers offline·telemetry 차단 환경, `-p no:cacheprovider`, 각 실행별 고유 TEMP basetemp를 사용했다. 설치·다운로드·유료 호출·실음성·vault 쓰기는 하지 않았다. 실제 GPU는 이번 요청에서 허용한 기존 번들·런타임만 사용했다.

### L08-06 원 반례 재실행과 판정

원 `R2/test_new_boundary.py`를 **내용 변경 없이** `R3/test_new_boundary.py`로 복사했다. 원 helper의 LF SHA256 **`d18770f7c3964d3a6f60ab63e1841b3cced4ee627a81fb32c025f988d048d829`** 일치를 확인했다. 함께 복사한 `test_independent_recheck.py`의 상대 `tree` import가 3판 사본을 가리킨다. 원 assertion을 새 결과에 맞춰 완화하지 않았다.

```powershell
# cwd: R3/tree, R3는 위의 절대 경로
D:/project/Recoryn/.venv/Scripts/python.exe -B -m pytest R3/test_new_boundary.py --rootdir R3 -q -p no:cacheprovider --import-mode=importlib --basetemp R3/pytest-original-boundary --junitxml R3/boundary.xml --tb=short
```

직접 결과 **1 passed in 0.26s / exit 0**. 이 명령의 `R3`는 경로 축약 표기이며 실행 시에는 위 절대 경로를 넣었다.

정상 report에 원래와 같은 `loaded += [r"\\review.invalid\share\cublas64_12.dll"]`를 적용했다. native `ntpath._getfinalpathname` spy는 해당 UNC를 실제 OS에 넘기지 않고 가로채도록 유지했다. 추가 관측을 `R3/observed.json`에 기록했다.

| 관측 | 2판의 원 관측 | 이번 3판 직접 관측 |
| --- | --- | --- |
| 오류 목록 | `[FOREIGN_RUNTIME_LOADED]` | `[NON_LOCAL_PATH_REPORTED, FOREIGN_RUNTIME_LOADED]` |
| 해당 UNC의 native 최종 경로 해석기 호출 | 2회 | **0회** |
| 원 반례 node | FAIL | **PASS** |

근거는 3판 `scripts/gpu_frozen_smoke.py:85`의 drive 문자/구분자 검사, `:89`의 GetDriveTypeW, `:95`의 허용 drive 종류 2/3/6 판정, `:104`의 비로컬 문자열 비교 분기, `:176`의 module/ext/loaded 전체 NON_LOCAL_PATH_REPORTED 검사다. 타입 검사 뒤 경로 검사가 실행되고, 비로컬은 verdict의 후속 파일/집합 비교에서도 realpath로 보내지 않는다. 따라서 **L08-06의 명시 UNC 보고 경로 원 반례는 RECHECKED**다.

### 기존 시험과 추가 경계 확인

```powershell
# cwd: R3/tree
D:/project/Recoryn/.venv/Scripts/python.exe -B -m pytest tests/release/test_gpu_smoke.py -q -p no:cacheprovider --basetemp R3/pytest-existing --junitxml R3/existing.xml --tb=short -W error::ResourceWarning
```

직접 결과 **103 passed in 8.54s / exit 0**, skip·xfail·실패 없음. 8.3 양방향·대소문자·형제 폴더 회귀도 포함한다. 문서의 B 분모 **91**(`4+45+14+1+2+1+9+11+3+1`) + C 분모 **12** = **103**과 실제 node 수가 일치한다. 새 경로 9개는 7개 비로컬 입력 + 매핑 드라이브 1 + 정상 로컬 해석 1이다.

추가 TEMP 독립 시험 `R3/test_independent_paths.py`는 제품의 허용 drive 집합이나 경로 판정 helper에서 기대값을 만들지 않았다. 손으로 쓴 API enum 기대값을 사용했다.

| 추가 공간 | 분모와 기대 | 직접 결과 |
| --- | --- | --- |
| 비로컬 입력 × 필드 | UNC/확장 UNC/확장 drive/device/상대/drive-relative/root-relative 7 × module/ext/loaded 3 = **21**. NON_LOCAL_PATH_REPORTED, 해당 realpath 호출 0 | 21 PASS |
| drive 종류 × 필드 | enum 0~7의 8 × 필드 3 = **24**. 2/3/6만 로컬 해석, 나머지는 거부·해석 0. Z 드라이브는 가짜 분류와 가짜 resolver로 실제 접근 차단 | 24 PASS |
| 로컬 symlink의 UNC 대상 | TEMP 안에 symlink fixture를 만들고 native resolver를 가로채는 추가 실험 1 | **1 SKIP**, 생성 단계 Windows 오류 1314(필요 privilege 없음) |

```powershell
# cwd: R3/tree
D:/project/Recoryn/.venv/Scripts/python.exe -B -m pytest R3/test_independent_paths.py --rootdir R3 -q -rA -p no:cacheprovider --import-mode=importlib --basetemp R3/pytest-independent-paths --junitxml R3/independent-paths.xml --tb=short
```

직접 결과 **45 passed, 1 skipped in 0.67s / exit 0**. helper LF SHA256은 `bf8653f8622690d6d8e4f1bef5ee59a5d3850ecdd202385005aff612b2a52cd5`다. symlink fixture는 생성하지 못했으며 승격·권한 변경·우회를 시도하지 않았다. 이를 확인 완료나 새 결함 재현으로 세지 않는다. 로컬 drive 아래 재파스 경로 전체의 원격 접근 방지는 이번 결과로 보장하지 않는다.

이번에 새 ID를 부여할 재현된 결함은 없다. 원 반례 21행 전체·다른 smoke 54개·작성자의 37개 mutation은 이번에 다시 실행하지 않았다. **37/37은 작성자의 결과 문서 이력**이며 이번 독립 결과는 위 103+1+45 PASS 및 1 SKIP이다.

### 3판 판정으로 기존 정확한 tree 번들 GPU 재실행

```powershell
# cwd: R3/tree
D:/project/Recoryn/.venv/Scripts/python.exe -B scripts/gpu_frozen_smoke.py --bundle D:/project/Recoryn/build/l08b-exact-1795358709/dist/Recoryn --runtime-root D:/project/Recoryn/build/gpu-e2e2 --output R3/gpu-exact
```

직접 결과 **PASS / failures=[] / returncode=0 / exit 0**. output은 새 TEMP 폴더이며 번들·런타임은 수정/삭제하지 않았다. `R3/gpu-exact/gpu-smoke.json`의 LF SHA256은 **`bbbfc8923a4db0a4d2270ce4cd4026d5de468bc41d25568baa8b674a1df42b54`**다.

- frozen=True, child exitcode=0. 실제 객체 runs는 cuda/[0]/float16과 cuda/[0]/float32다.
- loaded **108개** 모두 `_local=True`, module/ext 2개를 더한 검사 입력 **110개**도 비로컬 0개다. 런타임 내부 pyc는 `[]`다.
- 이 결과는 **2판과 packaging/src가 같은 지정 번들에 3판 판정 스크립트를 적용한 관측**이다. 앞선 150개 입력 대조를 이번에 다시 수행한 숫자로 쓰지 않는다.

실제 Whisper weights·전체 WhisperModel 음성 전사·다른 GPU/driver·clean VM·전체 native 무전송 인증은 이번에도 NOT_RUN이다. 결과 문서의 작성자 GPU PASS·mutation 수와 이번 직접 실행을 구분한다.

### RECHECK 2 인계

L08-06 **RECHECKED**, 현재 OPEN **0(S0 0 / S1 0 / S2 0 / S3 0)**. 기존 L08-01~05의 RECHECK 이력은 보존했다. 검토 문서의 기존 bytes 뒤에 이 절만 추가한다. G02 계약안/제품 코드·시험은 바꾸지 않았으며, 이 재확인 보고 후 **G02 계약안에 대한 C00 승인 대기 상태**로 돌아간다.
