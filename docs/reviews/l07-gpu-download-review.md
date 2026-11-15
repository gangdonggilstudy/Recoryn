# L07 / L-P07 GPU 런타임 보안 독립 검토

2026-11-15. 검토 L07/Codex, 작성 C00/Claude. **REVIEW_READY — OPEN 5건(S0 0 / S1 3 / S2 2 / S3 0).** 기준은 [D10](../implementation/license-review.md), [경우의 수](../testing/l07-gpu-runtime-cases.md), [작성자 결과](../implementation/license-results.md)다. 제품·GPU·법률·릴리스 최종 승인이 아니다.

AGENTS·온보딩·L07 배정 및 현 변경을 확인하고 ONBOARDING_READY를 보고했다. 쓰기는 이 리뷰뿐이며 제품/시험/설정/인덱스를 수정하지 않았다. Git은 status/diff의 읽기만 수행했다. 네트워크 다운로드·실음성·모델 weights·실 GPU·유료·계정·위임은 사용하지 않았다.

## 검토판과 실행

| 파일 | raw SHA-256 |
| --- | --- |
| src/recoryn/models/gpu_runtime.py | b8c7613373dd4e60530304518ebde27b0b9dd4158bd4edbfc21b7edfc240457a |
| src/recoryn/app/inference.py | 902b5198adc3f4bc0b7b47e54620324a10fc6966fe89e8ac00fd4df44f911cb9 |
| tests/unit/test_gpu_runtime.py | 363e3de1bfe39cedad5cac4278af385f3745820c2109e8ccbc62f3cdf3e11d19 |
| docs/testing/l07-gpu-runtime-cases.md | dc932aed91b7ba4cdfeb6732ce41e1a05e31c13de42936dff7c965f81fc5daa3 |

- Windows/CPython 3.13, `.venv`. `QT_QPA_PLATFORM=offscreen`, `PYTHONDONTWRITEBYTECODE=1`에서 `.venv/Scripts/python.exe -B -W error::ResourceWarning -m pytest -p no:cacheprovider --basetemp C:\Users\gangd\AppData\Local\Temp\recoryn-l07-review-176a9cbe220a44e3b55a1f38a48e5750 tests/unit/test_gpu_runtime.py -q` → **65 PASS / 0.82초**.
- 별도 합성 반례는 `.venv/Scripts/python.exe -B -X utf8 -W error::ResourceWarning -`로 실행했다. FileSpec/ModelSpec만 작은 합성 wheel의 크기/hash로 바꾸고, 실제 ModelManager·GpuRuntimeManager 설치/검증/활성화 경로를 호출했다. socket/getaddrinfo/create_connection은 예외로 막았다. DLL 등록과 ctypes.CDLL은 spy로 대체했고 CUDA 장치 수는 가짜 패키지가 1을 반환했다. 실제 DLL·GPU는 실행하지 않았다.
- 정상 기준은 같은 설치 경로에서 `ORIGIN='verified-source'`가 실행되는 것이다. 반례에서는 무해한 `ORIGIN='unverified-witness'` 또는 `archive-replaced` 표지만 사용했다. 65 PASS에 아래 반례를 합산하거나 제품 거부 성공으로 기록하지 않는다.
- 증거 A: `C:\Users\gangd\AppData\Local\Temp\recoryn-l07-independent-iip95fcq/results.json`과 같은 부모의 각 합성 런타임. 검토판 세 파일 사본은 그 아래 `reviewed-source/`에 보존했다.
- 증거 B: `C:\Users\gangd\AppData\Local\Temp\recoryn-l07-more-_h0scc5r/results.json`.
- 증거 C: `C:\Users\gangd\AppData\Local\Temp\recoryn-l07-dll-path-c_4xds13/results.json`.

## 발견

### L07-01 / S1 / OPEN — 검증 목록 밖 Python/DLL이 실행 경로에 들어온다

원 반례 A/extra_pyc:

1. 합성 wheel을 승인 설치하고, 기록된 `__init__.py`와 runtime.json은 그대로 둔다.
2. `importlib.util.cache_from_source(init)` 경로에 별도의 timestamp pyc를 추가한다. 헤더는 현재 MAGIC_NUMBER + flags 0 + 원 소스의 정수 mtime/size이며, code는 다른 ORIGIN을 반환하는 무해한 코드다.
3. `verify()`는 성공한다. `activate()`도 성공하지만 실제 ORIGIN은 **unverified-witness**다. runtime.json은 전후 동일하고 module.__file__도 검증한 .py 경로로 보인다. `-B`는 bytecode 쓰기만 막으며 이 읽기를 막지 못했다.

원 반례 B/extra_dll_selection은 기존 `build/gpu-e2e`의 실제 `ctranslate2/__init__.py` Windows 초기화 부분을 합성 패키지에 사용했다. 미기록 `ctranslate2/UNKNOWN-VENDOR.dll`을 추가해도 verify가 통과하고, 공식 초기화 코드의 `glob('*.dll')`이 그 파일을 ctypes.CDLL 대상으로 선택한다. spy 관측은 ctranslate2.dll/libiomp5md.dll/**UNKNOWN-VENDOR.dll**이며 실제 DLL 실행은 하지 않았다.

증거 C에서는 기록 파일을 바꾸지 않고 HIP_PATH만 TEMP 외부 폴더로 지정했다. 공식 초기화 부분이 관리 런타임 밖 `foreign/bin`을 DLL 폴더로 추가했다. activate가 직접 등록한 두 폴더만으로 실제 패키지의 DLL 검색 경로를 제한하지 못한다.

실제 `build/gpu-e2e` 읽기에서도 기록 34파일과 달리 추가 pyc 5개가 있었다. 기록 파일의 hash 불일치는 0이었다. 이 실제 pyc가 악성이라는 판정은 아니며, 미기록 실행 경로가 현실적으로 생기는 예다.

제안: 검증 대상 파일/디렉터리의 정확한 집합을 확인하고, import가 검증한 소스 bytes만 사용하도록 bytecode 경로를 통제한다. Python import·동적 DLL·환경 변수/외부 SDK 경로를 함께 다룬다. 필요한 DLL은 검증한 절대 경로로 묶고, 실제 로드 경로를 확인하는 독립 반례를 추가한다. 예상 밖 파일을 단순 무시하면서 “전부 검증”이라고 하지 않는다.

### L07-02 / S1 / OPEN — 설치/사용 증거가 고정 archive pin에 계속 묶이지 않는다

원 반례 B/wheel_after_verification: 실제 ModelManager.install이 원래 크기/hash 검증을 마치고 wheel 폴더를 반환한 직후 합성 CT2 wheel을 다른 합성 ZIP으로 교체했다. GpuRuntimeManager는 이 경로를 다시 열어 추출하지만 archive pin을 다시 대조하지 않는다. 설치가 성공하고 그 교체본에서 생성한 runtime.json으로 verify도 통과하며 **archive-replaced** 코드가 실행됐다.

원 반례 A/manifest_rewrite: 설치 후 __init__.py와 runtime.json의 해당 size/hash를 함께 바꾸면 verify/activate가 모두 통과한다. `_manifest()`는 runtime.json이 SPEC의 고정 wheel에서 유래했다는 외부 기준 없이 로컬의 자기 신고를 신뢰한다. ModelManager의 정확한 원 archive 검증만으로 이 이후 연결이 증명되지는 않는다.

제안: 검증한 archive의 동일 열린 객체에서 추출하고, 추출 파일의 신뢰 기준을 고정 계획에 연결한다. 예를 들어 고정 wheel에 묶인 검토된 member catalog를 사용하고 runtime.json은 그 기준의 캐시/설치 기록으로 다룬다. 단순히 바뀐 로컬 manifest에 맞춰 다시 hash하는 것은 진위 검증이 아니다. wheel 삭제·수동 복사/복구 시의 신뢰와 승인 기록 경계도 명시한다.

### L07-03 / S1 / OPEN — verify와 import 사이 교체를 막지 못한다

원 반례 A/verify_import_swap: 실제 verify는 그대로 실행했다. 첫 DLL 디렉터리 등록 경계를 Event로 표시하고 다른 스레드가 __init__.py를 교체한 뒤 진행하도록 했다. runtime.json은 전후 동일하다. 이어지는 import에서 **unverified-witness**가 실행되고 activate는 성공했다.

현재 `_sha256_file`의 fd는 각 hash 뒤 닫히며, verify 후 import/지연 import 동안 파일의 동일성·쓰기/삭제를 고정하는 수명이 없다. 검증 시점 직전 재hash만 추가해도 같은 시간 틈이 남는다.

제안: 검증된 source bytes를 직접 로드하고, native 파일과 후속 import의 파일 소유/수명도 보호한다. Windows에서는 쓰기·교체를 막는 열린 핸들과 실제 로더 경로를 포함한 방안을 검토하고, barrier를 유지한 독립 재확인을 받는다. 사용 중 remove/재설치의 순서도 같은 수명 계약에 연결한다.

**L07-01~03의 위협 전제:** 실행 경로에 파일을 추가/교체할 수 있는 주체가 있는 경우다. 공유·복구 폴더, stale cache, 같은 사용자 권한의 다른 프로세스 등을 포함한다. 다른 사용자 권한 상승이나 원격 침투를 재현했다는 뜻은 아니다. `_safe.check_path`도 같은 사용자 권한의 공격자에 대한 OS sandbox는 아니라고 명시한다. 현재 관리 root는 library.root/gpu-runtime이고 해당 API가 ACL/소유자 독점을 검증하지 않는다. 필요한 신뢰/권한 전제를 명시하더라도, 검증 밖 파일 실행과 pin 연결의 실제 공백을 구별해야 한다.

### L07-04 / S2 / OPEN — 다운로드 완료 뒤 취소는 무시되고 READY가 된다

원 반례 A/late_cancel: 실제 ModelManager.install을 끝까지 호출한 다음 반환 경계에서 cancel Event를 설정했다. GpuRuntimeManager.install(cancel=event)는 예외 없이 활성 폴더를 만들고 READY가 됐다. 다운로드 중 취소는 검사하지만 추출/최종 publish에는 cancel이 전달·재확인되지 않는다.

제안: 추출 중과 publish 직전의 취소 선형화 지점을 정의하고 확인한다. 완료 전 취소는 활성 경로를 만들지 않고 staging을 정리한다. 기존의 “처음부터 취소됨” 시험과 별도로 다운로드/추출/commit 경계의 결정적 반례를 추가한다.

### L07-05 / S2 / OPEN — 실패 상태와 활성화/재시도 상태가 일치하지 않는다

원 반례 A/cleanup_failure: os.replace로 publish한 뒤 `_downloads.delete`에 합성 PermissionError를 주면 install은 오류를 내지만 상태는 **READY·active 있음**이다. “실패하면 활성 런타임 없음”과 다르고 UI/호출자가 실패로 처리할 수 있다.

원 반례 B/retry_after_extract_failure: 실제 다운로드 검증 뒤 extract에 일시적 합성 ENOSPC를 주었다. staging은 정리되어 NOT_INSTALLED지만, 같은 관리자의 즉시 재시도는 남아 있는 완료 wheel 폴더 때문에 **MODEL_ALREADY_INSTALLED**로 막힌다.

제안: publish 이후 정리 실패와 설치 실패를 구별해 일관된 완료 결과를 반환하거나 안전하게 rollback한다. 검증 완료 다운로드를 재사용/정리하는 retry 계약을 정하고, 원 오류·활성 상태·남는 다운로드를 함께 시험한다. 위 증거는 실제 디스크 고갈/권한 변경이 아닌 결정적 장애 주입이다.

## 나머지 수락 기준과 한계

- **기본 무전송:** 승인 false/미지원 환경에서 다운로더 0회인 기존 시험을 독립 재실행했다. plan은 두 files.pythonhosted.org HTTPS URL·크기·SHA에 고정되고 ModelManager는 redirect·비정상 Range/encoding을 거부한다. 개인정보/비밀을 요청 payload로 넣는 새 경로는 찾지 못했다. 로컬 변조 반례를 동의 없는 실제 네트워크 전송으로 잘못 부르지 않는다.
- **ZIP 경계:** 상대 경로·드라이브/절대 경로·역슬래시·중복·CRC·chosen symlink·개별/합계 크기 및 필수 파일 검사를 읽고 기존 시험을 재실행했다. 임의 zip은 내려받지 않았다. 선택하지 않은 정상 파일은 추출하지 않는다. extract 단독 호출의 부분 파일과 install의 staging rollback은 구별한다. 모든 ZIP 이름/압축 조합을 전수 검증한 것은 아니다.
- **실행 경로:** cuda일 때만 activate하고 이미 최상위 ctranslate2가 import된 경우 거부하며 GPU_RUNTIME_*를 부모에 돌려주는 기존 시험은 통과했다. root source run에서 gpu_runtime=None을 허용하는 경로와 관리 런타임 경로는 구별한다. 실제 Windows DLL 검색/이미 로드된 동일 basename의 모든 혼합을 이번 fake 관측으로 보장하지 않는다.
- **약관·재배포 주장:** UI의 네 약관 이름/URL·용도와 CT2/cuBLAS 원 배포처 직접 GET 구조는 일치한다. 설치 위치는 번들 밖 library.root/gpu-runtime이고 기본 배포의 CPU 빌드를 교체하지 않는다. 이는 사용자 직접 받기의 기술 구조이지, Intel/NVIDIA 조건 충족이나 사용자가 읽은 약관 버전·법률 승인 증명이 아니다. 기존 G4를 자동 종결하지 않는다.
- **oracle:** 65 PASS에는 직접 고정 pin·추출 집합·다운로더 호출 수·hash 손상·late import 관측이 있다. U의 36조합은 유일한 3×2×2×3 열거지만 기대식이 구현 분기와 유사하므로 이것만으로 독립성/보안을 증명하지 않는다. 특히 activation 시험의 최소 가짜 __init__는 공식 패키지의 bytecode·DLL glob·SDK 환경 경로를 재현하지 않으며, 새 반례를 가리는 중요한 범위 차이다. 취소도 시작 전만 다뤄 경계 반례가 빠졌다.
- **작성자 실측:** RTX 4070·588MB 설치/검증 시간·CUDA 1·GPU float16/32 수치 결과는 C00 근거다. 이번 검토는 기존 build/gpu-e2e를 읽기만 했으며 그 측정을 재실행/승인하지 않았다. 실장비 실행과 모든 독립 위협 반례 통과는 별개다.

**REVIEW_READY. OPEN: L07-01(S1), L07-02(S1), L07-03(S1), L07-04(S2), L07-05(S2). 원 반례와 hash를 보존했으며, C00 수정 후 같은 검토자가 재확인한다.**

## L07 재확인 — 2026-11-15, 2판

C00의 동일 검토자 재배정에 따라 이 절만 추가했다. 최초 발견과 반례는 이력으로 보존하며 현재 판정은 아래와 같다. 제품/시험/설정/인덱스/Git을 수정하지 않았고 다운로드·실음성·weights·실 GPU·유료·계정·위임을 사용하지 않았다.

재확인 raw SHA-256:

| 파일 | SHA-256 |
| --- | --- |
| src/recoryn/models/gpu_runtime.py | 407e22642dc9120cb18b66ee16692cd83f842d59ad246d5292dd8989a969af5e |
| src/recoryn/app/inference.py | a8c54f53666056e9863850164dfb3857f742a1f713740e54295767e9101da079 |
| scripts/gpu_runtime_catalog.py | d8b290f27055a49982c82668979f829f6e3b8ddc8b023fed4363bf3305822431 |
| tests/unit/test_gpu_runtime.py | 15faa45e26edb7698ac2c059e9fcf3e032040ccbe2369d3cc385ff23f6a6d250 |
| docs/testing/l07-gpu-runtime-cases.md | 3eb2a2da09fd14cd194b941a271a5d92171391a60722d41bf4ee1fa2317c5ffe |
| docs/implementation/license-results.md | db9678b295cf10c9576ddddc06589f1dd7b31bc44befb7f438a9f3fc4e2cef13 |
| docs/implementation/license-review.md | a37966f45b6e45aa0376708d481a44e8d7454129ba70cf4705f4e27d40a79604 |

### 독립 재실행

1. `QT_QPA_PLATFORM=offscreen`, `PYTHONDONTWRITEBYTECODE=1`에서 `.venv/Scripts/python.exe -B -W error::ResourceWarning -m pytest -p no:cacheprovider --basetemp C:\Users\gangd\AppData\Local\Temp\recoryn-l07-r2-review-5def44c240b64264a4b9862f9afbe052 tests/unit/test_gpu_runtime.py -q` → **99 PASS / 2.03초**, skip 표시 없음.
2. `.venv/Scripts/python.exe -B -W error::ResourceWarning scripts/gpu_runtime_catalog.py build/gpu-wheels --check` → exit 0, **CATALOG_MATCH**. 기존 고정 wheel 두 개만 읽었다. 11개 member와 초기화 블록 SHA `1cf2cac0a98a9a00eff4b3f0a1cb86385b2fce8c4751df92d185c268fb8d5087`을 확인했다.
3. 별도 inline Python은 `.venv/Scripts/python.exe -B -u -X utf8 -W error::ResourceWarning -`로 실행했다. 원 반례와 같은 합성 ZIP/다운로더에 재판의 11경로를 갖는 작은 가짜 catalog를 적용했다. 초기화 블록은 기존 build/gpu-e2e2의 원 bytes를 읽어 실제 블록 pin과 대조한 것을 사용했다. 네트워크는 socket 함수에서 거부하고, driver 및 DLL 로더만 spy로 대체했다. 파일 공유 잠금은 Windows의 실제 `_hold/CreateFileW` 경로를 사용했다.

반례 원본별 관측은 `C:\Users\gangd\AppData\Local\Temp\recoryn-l07-r2-independent-m4o3fywz/results.json`과 같은 부모의 합성 런타임에 보존했다. 정상 기준은 verified-source 실행, DLL 로드 spy 5회, DLL 디렉터리 등록 0회였다. 실제 DLL이나 CUDA를 실행한 결과가 아니다.

| 원 반례 | 재판에서의 독립 관측 |
| --- | --- |
| A/extra_pyc | 유효한 mtime/size timestamp pyc 추가 시 GPU_RUNTIME_DAMAGED, DLL 로드 0회 |
| B/extra_dll_selection | UNKNOWN-VENDOR.dll 추가 시 GPU_RUNTIME_DAMAGED, DLL 로드 0회 |
| C/HIP_PATH | 외부 bin을 지정해도 verified-source 실행, 등록 0회, 정상과 같은 5개 절대 로드 경로 |
| B/wheel_after_verification | ModelManager 반환 직후 ZIP 교체 시 GPU_RUNTIME_ARCHIVE_INVALID, NOT_INSTALLED, active 없음 |
| A/manifest_rewrite | 소스와 자기 신고 runtime.json을 함께 바꿔도 GPU_RUNTIME_DAMAGED, DLL 로드 0회 |
| A/verify_import_swap | 첫 DLL 로드 경계에서 별도 스레드의 소스 쓰기·DLL 삭제·소스 rename·runtime 폴더 rename 모두 BLOCKED. 실행은 verified-source |
| A/late_cancel | 다운로드 반환 직후 취소 시 MODEL_DOWNLOAD_CANCELLED, NOT_INSTALLED, active 없음 |
| A/cleanup_failure | 게시 후 묶음 정리 PermissionError에도 설치 성공·READY |
| B/retry_after_extract_failure | 첫 합성 ENOSPC 후 재시도 성공·READY. 다운로더 호출은 전후 2회로 같아 재다운로드 없음 |

### 판정

| 발견 | 수정 근거와 현재 판정 |
| --- | --- |
| L07-01 / S1 | 정확한 파일 집합, 검증 bytes의 메모리 source loader, 고정 Windows 블록 교체 및 절대 DLL 경로로 원 pyc/DLL/HIP_PATH 반례가 차단됐다. catalog 밖 ctranslate2 이름을 다른 finder로 위임하지 않는 코드와 관련 시험도 확인했다. **RECHECKED / CLOSED** |
| L07-02 / S1 | 신뢰 기준이 소스 CATALOG로 이동했고 runtime.json은 더 이상 허용/신뢰하지 않는다. 고정 wheel을 쓰기 차단한 동일 handle로 재hash/추출하며, 교체 archive 및 자기 신고 manifest 반례가 거부됐다. **RECHECKED / CLOSED** |
| L07-03 / S1 | 검증한 11파일의 handle이 프로세스 수명 동안 유지되고 source는 해당 handle의 bytes에서 실행된다. 원 import 경계의 실제 Windows 쓰기/삭제/rename 네 시도가 모두 막혔다. **RECHECKED / CLOSED** |
| L07-04 / S2 | 다운로드 뒤·추출 블록·publish 직전 취소를 확인한다. 원 다운로드 완료 직후 취소 반례가 더 이상 READY를 만들지 않는다. publish 뒤 취소는 이미 성공한 설치라는 선형화 계약과 구분했다. **RECHECKED / CLOSED** |
| L07-05 / S2 | 게시 뒤 정리 실패는 성공으로 처리하고, 남은 검증 묶음을 재hash해 재사용한다. 두 원 상태 불일치/재시도 반례가 해소됐다. **RECHECKED / CLOSED** |

실제 `build/gpu-e2e2/ct2-cuda-4-9-0`를 읽기만 해 추가 대조했다. 파일 집합은 catalog와 같은 **11개**, member hash 불일치 0, pyc 0이었다. 실제 source compile/GPU/DLL 실행은 하지 않았다.

위협 경계는 같은 사용자 권한의 프로세스 메모리 변조까지 막는 sandbox가 아니라 파일 삽입/교체를 검증 없이 로드하지 않는 것으로 명시됐다. 확인한 원 반례와 재판 코드 범위에서 새 OPEN 결함은 찾지 못했다. 모든 Windows/native loader 상태·다른 GPU/드라이버·실장비를 전수 검증했다는 뜻은 아니다. mutation 14개 kill, 전체 7692 PASS, 실장비 encode/generate 및 후보 smoke는 C00의 별도 작성자 증거이며 이번 독립 실행에 합산하지 않았다. 마지막 확인에서 위 7개 대상 hash는 그대로였다.

**REVIEW_READY — L07-01~05 모두 RECHECKED/CLOSED. 현재 OPEN 0건(S0 0 / S1 0 / S2 0 / S3 0). 최종 통합·릴리스·법률 판단은 C00 및 해당 게이트에 남긴다.**

### catalog 스크립트 변수명 정리 확인 — 2026-11-15

현재 `scripts/gpu_runtime_catalog.py` raw SHA-256 `d425a4ee4022f644812a28f58c9aea3f6ed60909e73c173910bec1cb58692804`를 확인했다. 출력 루프의 `for wheel, listed in found.items():`와 `for row in listed:` 두 줄만 원래 rows로 역치환한 bytes의 SHA가 검토판 `d8b290f27055a49982c82668979f829f6e3b8ddc8b023fed4363bf3305822431`과 정확히 같았다. unified diff도 해당 두 줄뿐이다. 계산·검증·출력 내용의 변경은 없다.

`.venv/Scripts/python.exe -B -W error::ResourceWarning scripts/gpu_runtime_catalog.py build/gpu-wheels --check`를 기존 wheel 두 개에 재실행해 **exit 0 / CATALOG_MATCH**를 확인했다. 다운로드·제품/시험/설정·Git/인덱스 수정은 하지 않았다.

**REVIEW_READY — 소규모 변경 RECHECKED, OPEN 0건. 기존 L07-01~05 종결 판정 유지.**
