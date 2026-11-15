# L03 / L-P03 고지·SBOM 독립 검토

2026-11-15. 검토자 L03/Codex, 작성자 C00/Claude. **REVIEW_READY — 수정 후 재확인 필요. OPEN 4건(S0 0 / S1 0 / S2 2 / S3 2).** 기술 증거 검토이며 법률·G4·릴리스 승인이 아니다. [L01 계획](../implementation/license-review.md)의 D5/D6와 [선행 독립 판정](license-plan-review.md)을 기준으로 삼았다.

## 검토판과 방법

AGENTS·온보딩 순서·협업/품질 규칙·L03 배정을 재확인하고 ONBOARDING_READY를 보고했다. `git status --short`, `git diff --stat`, 대상 코드·시험의 `git diff`, 신규 고지/attributes의 전문을 읽었다. 쓰기는 이 리뷰만 수행했다. 선행 commit/CI 상태는 C00 보고이며 이번 검토자가 원격 확인한 결과가 아니다.

대상 raw SHA-256:

| 파일 | SHA-256 |
| --- | --- |
| packaging/release_evidence.py | c995d26b247a0c38754c61f634055310d59178d81b4fe7270e20cf8fcccc9553 |
| scripts/build_release.py | 7b28b74471b12ec1a7d7bf7cdcce9eded18b8063489c4e8fdc5425fd9c0b2b6d |
| tests/release/test_evidence.py | 7e96ebfa8299fbca9152e022569833569c01932786c0c1ff5cdda5f6d5537421 |
| tests/release/test_build_inputs.py | 3c796054b8b9a8adc6fc037ad009313f230e1f747b122434c7d205a3a6cd3078 |
| .gitattributes | 34191a3c1c5e8246d0add7441ae7eb2c2e30e37f5bda5d096ad54f85260fe9eb |
| packaging/notices/SOURCES.json | 09427f58208f0a29fb416df39e14d8285c38028df59e5218244787ceee0f86d9 |

실제 검토 후보는 `build/l03-1794719526/dist/Recoryn`이다. 후보 증거의 raw SHA-256:

| 파일 | SHA-256 |
| --- | --- |
| NOTICE.txt | 47d0798352e30b15a458efaaeded5a7037a3b85bcdc89e7d8f8cff1b0ef7f758 |
| sbom.cdx.json | 0300ee7bbc760ad4f9756cd868c25edf33907708f081d074fcf6870775bd864a |
| native-origins.json | fd783f90deb72b37ffaa67ed4bc20d999452224899ffdcff4aefd8f932b53f47 |
| build-provenance.json | b24cf15f83ff96f08db1def167159e2aeda625c6494d2919cfa37ba7fba6011d |

검사는 CPython 3.13.1/Windows, 저장소 `.venv`에서 수행했다. 제품·시험·설정·인덱스는 수정하지 않았고 새 빌드·음성·모델·네트워크 다운로드를 실행하지 않았다.

## 발견

### L03-01 / S2 / OPEN — 경로 포괄 규칙으로 미확인 native가 DECLARED가 된다

근거: `NATIVE_RULES`는 `_internal/pyside6/plugins/.+\.dll`, `qt6[a-z]+\.dll`, `_internal/shiboken6/.+\.(dll|pyd)`를 실제 구성/출처와 무관하게 LGPL/DECLARED로 반환한다. 합성 동일 bytes `MZ-SYNTHETIC-UNKNOWN-VENDOR`를 각각 다른 경로에 둔 독립 TEMP 후보에서 `generate()` → `verify()` → `license_gaps()`를 실행했다.

| 합성 파일 | 관측 상태 | license_gaps |
| --- | --- | --- |
| _internal/newvendor/unknown.dll | UNMAPPED | 해당 경로 1개 |
| _internal/PySide6/plugins/newvendor/unknown.dll | DECLARED/LGPL-3.0-only | 빈 목록 |
| _internal/shiboken6/unknown-vendor.dll | DECLARED/LGPL-3.0-only | 빈 목록 |

모든 후보는 manifest verify를 통과했다. 따라서 새 파일이 위 디렉터리에 들어오면 `scripts/build_release.py`의 `if license_gaps(bundle): ... NATIVE_LICENSE_UNMAPPED` 조건이 이를 잡지 못한다. 현재 112파일에 미지 파일이 있다는 주장은 아니다. 이미 알려진 구성과 이후 미확인 파일을 구별하지 못하는 게이트 반례다.

제안: 검토한 모듈/플러그인 파일명을 명시한 규칙이나 검증된 배포 입력의 구성 manifest로 제한하고, 해당 범위 밖 파일은 UNMAPPED로 남긴다. 위 세 경로의 동일 bytes 반례와 실제 112파일의 귀속을 함께 회귀 검증한다. 단순 directory prefix를 구성요소 라이선스의 증명으로 삼지 않는다.

### L03-02 / S2 / OPEN — SPDX처럼 생긴 문자열을 유효 expression으로 확정한다

근거: `_SPDX`는 문자 모양만 검사한다. `cyclonedx_licenses('MIT AND AND')`, `cyclonedx_licenses('Proprietary')`, `cyclonedx_licenses('Apache-2.0-or-later')`가 모두 `[{"expression": 입력}]`을 반환했다. 별도의 `packaging.licenses.canonicalize_license_expression`은 세 입력 모두를 거부한다. 알 수 없는 metadata도 이 함수로 유입되므로 표준 `licenses.expression`에 잘못된 식을 만들 수 있다. 현재 후보의 구성요소/native 식은 별도 파서 검사에서 모두 유효했다.

제안: SPDX grammar와 알려진 식별자/LicenseRef를 검증하고, 비표준 선언은 CycloneDX `license.name` 또는 명시적인 미확인 표기로 보존한다. 거부해야 할 식을 임의로 허용형으로 바꾸지 않는다. 위 부정 입력과 현재 식/예외/복합식에 대한 독립 oracle 시험을 추가한다.

### L03-03 / S3 / OPEN — 전문을 필드에 붙이지 않는다는 정책과 실제 SBOM property가 다르다

근거: `generate()`는 distributed-license를 정규화하지만 `recoryn:declared-license`에는 원 선언을 그대로 넣는다. 실제 후보 numpy property는 **47,540자·950개 개행**의 전문이다. `test_l03_full_license_text_in_metadata_is_not_pasted_into_fields`는 NOTICE와 정규화 식만 확인해 이 property를 관측하지 않는다. SBOM 형식 위반이라는 판정은 아니지만 “긴 선언 전문을 필드에 붙이지 않는다”는 수락 기준/주석과 불일치한다.

제안: 원문은 고지 파일 또는 별도 raw evidence에 보존하고 property에는 hash·참조·짧은 식별자를 넣는다. 원 선언 전문을 property에 유지할 의도라면 그 예외와 제한을 명시적으로 결정하고 시험도 실제 정책에 맞춘다. 원 근거를 버리거나 잘라 놓고 완전한 원문처럼 표시하지 않는다.

### L03-04 / S3 / OPEN — Microsoft 조건 미확인 상태가 NOTICE에 명시되지 않는다

근거: NOTICE는 Intel의 exact governing text 미확인을 명시하지만 Microsoft에는 `redistributed under Microsoft's redistribution terms`만 적는다. native 13파일의 REDISTRIBUTABLE_PROPRIETARY는 분류이며, 정확한 파일의 재배포 조건을 확인했다는 증거가 아니다. D6 및 현재 결과 문서는 Microsoft 조건의 법률 확인을 여전히 G4 OPEN으로 둔다. NOTICE 독자에게도 그 상태가 보여야 한다.

제안: Microsoft exact runtime의 조건 확인이 남아 있음을 NOTICE와 관련 gate에 명시하거나, 확인 완료한 근거를 연결한다. 원문/확인 없이 상태를 승인으로 올리지 않는다. 후보 전체의 일반적인 법률 승인 부인 문구는 유지한다.

## 통과 근거와 범위

- **관련 시험:** PowerShell에서 `$env:QT_QPA_PLATFORM='offscreen'; $env:PYTHONDONTWRITEBYTECODE='1'` 설정 후 `.venv/Scripts/python.exe -B -W error::ResourceWarning -m pytest -p no:cacheprovider --basetemp C:\Users\gangd\AppData\Local\Temp\recoryn-l03-review-a9f7e82398af430ea4443c0da90a15bc tests/release/test_evidence.py tests/release/test_build_inputs.py -q` → **42 PASS / 1.23초**. 전체 회귀·coverage 결과로 확대하지 않는다.
- **실물 대응:** stdlib pathlib/json/hashlib로 실제 EXE/DLL/PYD 집합과 native 표를 독립 대조했다. **실물 112 / 표 112 / 유일 경로 112, 누락·초과·중복·hash 불일치 0**. 상태는 DECLARED 92 / REDISTRIBUTABLE_PROPRIETARY 13 / PATENT_REVIEW_REQUIRED 5 / CONDITIONS_UNCONFIRMED 2. 규칙의 완전성을 이 숫자만으로 승인하지 않는다.
- **Qt·누락 전문:** 상용 고지 파일 0. LGPL-3.0/GPL-3.0은 Qt 계열 각 6곳, Qt FFmpeg LGPL-2.1은 1곳, CTranslate2 MIT/tokenizers Apache/sherpa-onnx-core Apache는 각 1곳에 존재하며 모두 SOURCES의 SHA와 일치한다. Qt의 선택 식과 별도 선언 근거를 구분한 표기는 적절하다. upstream URL·버전·고지 내용은 로컬 기록과 대조했으며 원격 원문을 재다운로드해 출처 진위를 증명한 것은 아니다.
- **bytes 고정:** SOURCES의 6개 bytes/SHA 일치, build-provenance build_inputs의 고지 6개+SOURCES 총 7개 bytes/SHA와 현재 입력 일치. `git check-attr text --`의 6개 `.txt` 결과 모두 `unset`(-text). TEMP 사본에서 원문 6개를 각각 변조한 여섯 실행 모두 `NOTICE_TEXT_HASH_MISMATCH`였다. 저장소 원문은 변조하지 않았다.
- **독립 반례:** `.venv/Scripts/python.exe -B -X utf8 -W error::ResourceWarning -`에서 pathlib/tempfile와 일시적인 metadata mock만 사용했다. 원 native 반례 후보와 여섯 변조 결과는 `C:\Users\gangd\AppData\Local\Temp\recoryn-l03-independent-cadhasst/witness.json` 및 같은 부모의 TEMP 파일에 남았다. 최초 TEMP `recoryn-l03-independent-to0m3udb` 실행은 진입 EXE를 빠뜨려 RELEASE_ENTRY_MISSING으로 중단한 **하네스 준비 오류**이며 제품 실패나 유효 반례로 집계하지 않았다.
- **남은 게이트:** 실제 provenance는 source offer/Qt FFmpeg source·patent 미확인, native MAPPED_WITH_OPEN_CONDITIONS, signing/clean VM/hardware NOT_RUN을 유지한다. LGPL 교체 가능성·소스 게시 미결과 tqdm 정확 버전의 MPL 소스 위치는 NOTICE에 있다. 모델 없음·무서명·비인증 서술도 유지된다.
- **smoke 제한:** 저장된 smoke.stdout.json의 status PASS와 합성 녹음·분리 원본 보존·PyAV stub 경로를 읽었다. 이번 검토에서 재실행하지 않았으며 기존 smoke도 모델 추론/실장비 NOT_RUN, 네트워크 관측은 PYTHON_SOCKET_AUDIT_ONLY로 한정한다. Qt/native의 실제 모든 전송 부재를 보장하지 않는다.

**REVIEW_READY. OPEN: L03-01(S2), L03-02(S2), L03-03(S3), L03-04(S3). 작성자 수정 후 동일 검토자가 변경 hash·반례를 재확인한다.**

## L03 재확인 — 2026-11-15

C00의 명시 재배정에 따라 이 절만 추가했다. 최초 OPEN 기록은 이력이며 현재 판정은 아래와 같다. Git·인덱스·빌드·pytest를 실행하지 않았고 제품·시험·설정을 수정하지 않았다. 요청된 원 반례는 `.venv/Scripts/python.exe -B -X utf8 -W error::ResourceWarning -`의 inline Python으로 TEMP 합성 입력에 한정해 재실행했다. EXE/DLL은 합성 bytes 파일이며 실행하지 않았다.

재확인 raw SHA-256:

| 파일 | SHA-256 |
| --- | --- |
| packaging/release_evidence.py | f6d730a8cd37ad4889dfb482d21f897ed025b2cc401ef395cefb4457c020ffed |
| packaging/notices/native-map.json | c48a7491a7731c984e19dda3c65bdb3a51fdf0c04ede8c44abe3c0abb865a4f0 |
| tests/release/test_evidence.py | bc7acd6528c3e31bd0d1bb4bda23958a3858289536c5df0f52a77b1e0e507087 |
| tests/integration/test_release_independent.py | d9b1747704f47ba6e17d4b253e0cab1543a70e3a7bb2b87a5b32ae7982bdb79f |

`scripts/build_release.py`, `tests/release/test_build_inputs.py`, `.gitattributes`, `SOURCES.json`의 raw hash는 최초 검토판과 동일함을 확인했다. C00 보고의 stage tree는 `f786ddc54b1373faa18ca945fce86143db5f1cfb`이며 이번 검토에서 Git으로 확인한 값은 아니다.

| 발견 | 재실행·대조 결과 | 현재 판정 |
| --- | --- | --- |
| L03-01 / S2 | 원래의 동일 합성 bytes를 세 경로에 각각 넣고 `generate → verify → license_gaps`를 재실행했다. `_internal/newvendor/unknown.dll`, `_internal/PySide6/plugins/newvendor/unknown.dll`, `_internal/shiboken6/unknown-vendor.dll` 모두 UNMAPPED이며 gaps가 각각 해당 경로 1개다. 새 exact map은 26그룹·112개 유일 경로이고 두 실물 후보의 112경로 집합과 일치한다. 모든 실물 native hash도 각 후보의 표와 일치한다. `native_license`에 과거 포괄 경로 추론이 남아 있지 않다. | RECHECKED / CLOSED |
| L03-02 / S2 | `MIT AND AND`, `Proprietary`, `Apache-2.0-or-later` 세 식이 모두 `[{"license":{"name":원입력}}]`로 보존되고 expression으로 출력되지 않는다. 정규식 대신 SPDX grammar/식별자 검증을 사용한다. | RECHECKED / CLOSED |
| L03-03 / S3 | 두 후보 numpy의 declared-license는 `LicenseRef-Declared-As-Full-Text`, chars는 `47540`이다. sha256 `d3309e95bfdf13c17f999d8a1a007ceb216c5bd91bca85bf162202e56ba5b463`은 설치 배포판 metadata 원 선언을 독립적으로 UTF-8 hash한 값과 일치한다. 전문 property 대신 식별자·hash·문자 수를 기록하는 수정과 추가 assertion을 확인했다. | RECHECKED / CLOSED |
| L03-04 / S3 | 두 후보 NOTICE에 `are not yet confirmed (release gate microsoft_runtime_conditions)`가 실제로 존재하며, 각 provenance의 `microsoft_runtime_conditions`가 REVIEW_REQUIRED다. Intel 조건과 Qt/FFmpeg source·patent 관련 미결 gate도 유지된다. | RECHECKED / CLOSED |

TEMP 증거: `C:\Users\gangd\AppData\Local\Temp\recoryn-l03-recheck-vq7uqbvx/witness.json`과 같은 부모의 합성 후보 3개. 현재 unknown 파일은 manifest verify 자체에서는 허용되지만 `license_gaps`에 남으므로, 기존 빌드의 NATIVE_LICENSE_UNMAPPED 차단 조건이 이를 거부한다. 실제 빌드 호출은 하지 않았다.

두 후보 `build/l03-1794720123/dist/Recoryn`, `build/l03-final-1794720823/dist/Recoryn`의 NOTICE hash `6b6c01b833a36ffa49a9be6bcca1fcf09bc69e7d2460301cdfcac0f2b4253f08`, SBOM hash `3519a569088f0cf49e6153d3a04a3f3060782d426d5c023500c2bda39a75af88`이 각각 일치함을 독립 확인했다. 이는 두 후보의 EXE bytes까지 같다는 판정은 아니다.

### BR42 fixture와 제한

현재 BR42 코드를 읽어 notices 복사가 필수 입력을 채우는 준비 단계임을 확인했다. 선택/미동봉 두 가짜 배포판·관측 TOC는 별도로 구성하고, 실제 포함 구성요소 집합, 선택 고지 내용, 전체 파일 size/SHA, native의 shipped/source SHA 동등성, clean VM NOT_RUN 및 DEVELOPMENT_CANDIDATE를 계속 명시적으로 검사한다. 고지 복사는 이 기대값을 생성 함수에서 가져오거나 실패를 무시하게 만들지 않는다. **이 변경 범위에서 oracle 약화를 찾지 못했다.**

과거/최종 exact-tree TEMP의 BR42 파일을 읽어 역사적 assertion diff도 대조하려 했으나 두 경로 모두 PermissionError였다. 따라서 과거 assertion의 byte/AST 동일성을 별도로 입증했다고 주장하지 않는다. 이는 인프라 읽기 제한이며 제품 실패가 아니다. 위 oracle 판정은 현재 코드의 독립 관측과 C00이 명시한 fixture 변경 범위에 한정한다.

첫 exact-tree의 7434 PASS/1 FAIL(NOTICE_TEXTS_MISSING) 및 fixture 보충 후 7435 PASS·coverage·최종 smoke는 [결과 문서](../implementation/license-results.md)의 C00 실행 근거다. 이번 재확인 실행 수나 독립 전체 회귀로 합산하지 않았다. G4·법률 조건·실장비·모델·서명·clean VM을 승인하지 않는다.

**REVIEW_READY — L03-01~04 모두 RECHECKED/CLOSED. 현재 OPEN 0건(S0 0 / S1 0 / S2 0 / S3 0). 최종 통합·Git/CI·공개 판단은 C00 책임이다.**
