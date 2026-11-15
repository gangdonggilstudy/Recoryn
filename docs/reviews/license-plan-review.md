# L01 / L-P01 라이선스 계획 독립 검토

2026-11-15. 작성: L01 보안·라이선스 검토자(Codex). 대상 작성자: C00(Claude). 상태: **REVIEW_READY — 수정 후 재확인 필요**. OPEN **3건(S0 0 / S1 0 / S2 2 / S3 1)**. 이 문서는 계획의 기술 근거 검토이며 법률 판정이나 배포 승인이 아니다.

## 대상과 재현 범위

- 기준: H-P01 `0cf9cdd730eae4fccb9e67446f58ffa1ebb61439`. CI 성공은 C00 인계 근거이며 이번 검토자가 재실행한 결과가 아니다.
- [계획](../implementation/license-review.md) raw SHA-256: `b2e2efa06943bd5cbd068559d24ffbb21ace0814df1149e1eb3ab43c1ed31808`.
- [배정표](../collaboration/assignments.md) raw SHA-256: `f0dd9613e0a4dcdf4d533b0d8e65e07cb108974175e092ba7383e153d5511f6d`.
- [push 규칙](../collaboration/push-units.md) raw SHA-256: `09699d37e323551acc5eb4ec16e8d6e27279e47c7525c4fe591e68706fe0c6b5`.
- 로컬 후보: `build/final-dev2-1794666063022/dist/Recoryn`. SBOM SHA-256 `9ce82c4bb8fdccd374b24d2d41955c3c9b02b0ac84d44643bddd4c935543539f`, native 귀속표 SHA-256 `91841cef0254fadc2f6787f9b4f7fdb055024dda3bf159fc0bd62d6a3af91ab0`.
- PowerShell에서 `git status --short`, `git diff -- docs/collaboration/assignments.md docs/collaboration/push-units.md`, `Get-Content -Encoding UTF8 docs/implementation/license-review.md`로 현 변경을 확인했다. 신규 계획은 untracked이므로 git diff만으로 검토하지 않았다. 기존 변경을 수정하지 않았다.
- `.venv/Scripts/python.exe -X utf8 -`의 표준 라이브러리 `pathlib/json/hashlib/re`로 후보 inventory·고지·SHA와 상대 링크를 읽었다. `pefile.PE(..., fast_load=True)`와 `parse_data_directories(directories=[1,13,2])`로 import/delay-import/버전 정보를 읽었다. PE의 ASCII configure/license/LLVM 문자열도 읽었으며 DLL·앱·모델은 실행하지 않았다.
- 대상은 기존 후보의 **native 243파일 / SBOM 39구성요소**다. 이는 라이선스 의무의 분모가 39라는 뜻이 아니다. 정적 포함 구성요소·예외 조건을 별도로 추적해야 한다.

## 발견

### L01-01 / S2 / OPEN — GPL 배포 정책과 비용·적용 범위를 분리해야 한다

근거: 계획의 판정 기준 ②는 GPL 구성요소를 함께 배포하면 Recoryn 배포물 전체에 GPL 의무가 생긴다고 일반화하고 이를 “무료가 아닌 경우”에 포함한다. 그러나 후보 `licenses/numpy/LICENSE.txt:510`의 GPLv3 §5는 독립 저작물의 단순 집합과 더 큰 결합 프로그램을 구별한다. PyInstaller 예외와 GCC 런타임 예외도 계획 C가 이미 별도로 인정한다. GPL 의무와 구매 대가를 같은 사실로 표시할 근거는 아니다.

제안: “사용료/구매 필요”, “현재 배포 정책에서 제외할 copyleft 또는 결합 조건 미확인”, “특허 확인 필요”를 구분한다. PyAV가 x264/x265를 import하는 구체적 결합 근거로 D1을 유지하되, 단순 동봉만으로 전체 Recoryn의 라이선스가 확정된다는 표현은 고친다. 이는 GPL 사용을 허용하자는 제안이나 개별 결합물의 법률 결론이 아니다.

### L01-02 / S2 / OPEN — 허용형 묶음 판정의 내부 구성요소 근거가 부족하다

근거: 계획 D는 `opengl32sw.dll`을 Mesa(MIT)로만 분류한다. 실제 `_internal/PySide6/opengl32sw.dll`에는 `LLVM_VERIFY_MACHINEINSTRS`, `llvm.global_ctors` 등 다수의 LLVM 문자열이 있으며 정적 import는 Windows 시스템 DLL만이다. 이 관측은 LLVM 계열 코드의 정적 포함 조사가 필요함을 보여 주지만 정확한 버전·라이선스까지 확정하지는 못한다. [Mesa 공식 설명](https://docs.mesa3d.org/license.html)은 core의 MIT와 구성요소별 다른 라이선스를 구별한다. 따라서 PE 전체의 의무를 MIT 하나로 확정할 수 없다.

또한 B의 Intel OpenMP는 실제 `libiomp5md.dll` 버전 `20250910`과 Intel 제작자 정보까지 확인되지만, 제작자명만으로 독점/무상 재배포 조건이 확정되지는 않는다. [Intel 공식 안내](https://www.intel.com/content/www/us/en/developer/articles/license/end-user-license-agreement.html)는 해당 패키지 동봉 조건을 기준으로 삼도록 설명한다. LLVM upstream 라이선스 역시 이 Intel 바이너리의 적용 조건을 대신 증명하지 못한다. D6의 법률 확인 보류는 적절하나 B의 확정적 분류와 구별해야 한다.

제안: D5/L-P03 전수 대조에 **실제 native 경로·hash → 정적/동적 내부 구성요소 → 버전/출처·적용 전문·예외 → 유지/제외/미확인** 대응을 포함한다. Mesa/LLVM과 Intel OpenMP를 명시 조사 항목으로 넣고 미확인 조건은 G4 OPEN으로 유지한다. 이미 C에 기재한 numpy/OpenBLAS 내부 GCC 예외를 새 누락으로 중복 집계하지 않는다. 이 발견은 유료 의무나 위반을 입증했다는 뜻이 아니라 “전수 허용형” 판정의 근거 부족이다.

### L01-03 / S3 / OPEN — 남기는 Qt FFmpeg의 특허 검토 상태를 명시해야 한다

근거: 후보 `_internal/PySide6/avutil-61.dll`의 문자열은 LGPL-2.1-or-later와 `--enable-network`를 포함한 configure를 보여 준다. 외부 코덱 DLL import가 없다는 관측은 정적으로 들어간 코덱의 특허 조건을 판정하지 못한다. [FFmpeg 공식 legal 설명](https://ffmpeg.org/legal.html)은 소프트웨어 라이선스와 관할·사용에 따른 코덱 특허 문제를 구별한다. 계획은 특허를 판정 축으로 삼지만 D6의 잔여 확인에는 유지하는 Qt FFmpeg의 코덱 특허가 명시되어 있지 않다.

제안: 유지 FFmpeg의 실제 코덱/용도/관할에 따른 특허 확인을 G4 미결 항목에 명시하거나 현재 사용 범위에서 제외하는 근거를 남긴다. LGPL 표기나 영상용 PyAV 제거만으로 특허 검토 완료를 선언하지 않는다. 실제 사용료 발생 여부·적용 특허·법률 적합성은 이번 검토에서 판정하지 않았다.

## 나머지 수락 기준

- **A/C 대조:** PyAV `av.libs`의 x264/x265/OpenH264 존재와 avutil의 `--enable-libx264 --enable-libx265` 및 LGPLv3 문자열 공존을 확인했다. 이 불일치를 무시하지 않고 PyAV 묶음 전체를 제외하려는 D1은 보수적 기술 대안이다. [Qt Virtual Keyboard 공식 문서](https://doc.qt.io/qt-6/qtvirtualkeyboard-index.html)의 commercial/GPLv3 설명과 A의 분류가 일치한다. Qt PDF의 LGPL 설명도 [해당 모듈 공식 문서](https://doc.qt.io/qt-6/qtpdf-licensing.html)와 일치한다. 전체 Qt wheel 선언만으로 Virtual Keyboard를 LGPL로 취급하지 않은 점은 적절하다.
- **E 대조:** NOTICE 635바이트, Qt 계열 동봉 고지의 상용 전문 문제, ctranslate2/tokenizers/sherpa-onnx-core 고지 폴더 누락, SBOM의 선언 property와 표준 licenses 차이, native 두 EXE 귀속 미결을 확인했다. 고지를 생성하는 것과 적용 조건을 충족하는 것은 D6에 따라 구별해야 한다.
- **D1~D6 불변식:** 계획 자체에서 원본 수정·AI 실패에 따른 녹음 중단·비밀 저장 위치 변경·자동 다운로드를 요구하는 충돌은 찾지 못했다. PCM→float32/mono/16kHz는 파생 STT 입력으로만 한정해야 한다. L-P02에서는 원본 hash 불변, 변환/취소 실패와 녹음 저장 독립, PyAV stub 명시 실패, 네트워크 fallback 0을 기존/추가 시험에 대응시켜 확인해야 하며 여기서는 구현 통과로 판정하지 않는다. `--enable-network` 문자열만으로 실제 무동의 전송이 발생했다고 판정하지 않는다. 미래 OpenH264 다운로드도 별도 동의 없이는 허용되지 않는다.
- **범위·독립성·게이트:** C00 작성과 L01 검토 세션은 분리되어 있다. L-P02 ML/아키텍처 검토, L-P03 보안 검토, 선행 원격 CI와 정확한 tree 회귀 요구에 모순을 찾지 못했다. 공유 `scripts/build_release.py`/결과 문서는 같은 C00 작성자이나 단위별 snapshot을 분리해야 한다. 관측 중 L-P02 source 변경이 시작되었으므로 이 workspace 전체를 L-P01 문서 commit의 검증 tree로 주장하면 안 된다. Git 통합·정확한 stage tree 검증은 C00 책임이다.
- **상대 링크:** 계획 2개, 배정표 전체 10개, push 규칙 전체 2개를 각각 문서 부모 경로에서 해석해 누락 **0**. 표의 미래 파일명은 링크 통과로 구현 존재를 주장하지 않는다.

## 제한과 마감

문서 검토이므로 구현 시험·전체 회귀·coverage를 재실행하지 않았다. 새 제외 후보의 빌드·STT 품질·원본 보존·오프라인 실행·GPU·clean VM·서명·법률 적합성은 미검증이다. 공식 설명은 읽기 조회만 했으며 바이너리/소스/모델 다운로드는 하지 않았다. GNU FAQ 웹 조회는 timeout으로 실패했으므로 L01-01은 로컬 동봉 GPL 전문을 근거로 삼았다. 후보 전체의 적법성·모든 특허의 부재는 확인하지 못했다.

**REVIEW_READY. OPEN: L01-01(S2), L01-02(S2), L01-03(S3). 작성자 수정 후 L01 검토자가 대상 hash와 변경 근거를 재확인한다.**

## L01 재확인 — 2026-11-15

대상 계획 raw SHA-256 `cb681eaabe8453f992fbca44d52a211bdce953dfde97fe8fae31ba23ec945bef`를 `.venv/Scripts/python.exe -X utf8 -`의 `hashlib.sha256(Path(...).read_bytes())`로 확인하고 전문을 원 발견·근거와 대조했다. 배정표·push 규칙의 hash는 위 최초 검토판과 동일하다. 최초 OPEN 기록은 이력이며 현재 판정은 아래와 같다.

| 발견 | 재확인 근거 | 현재 판정 |
| --- | --- | --- |
| L01-01 / S2 | 판정 기준이 사용료·구체 결합의 copyleft/조건 미확인·특허 확인을 분리했다. GPL 의무와 구매 대가가 다름, 단순 동봉만으로 전체 Recoryn의 라이선스를 확정하지 않음, 집합물·예외 구분을 명시했다. 로컬 GPLv3 §5 근거와 충돌하던 일반화가 제거됐다. | RECHECKED / CLOSED |
| L01-02 / S2 | Intel MKL/OpenMP는 적용 원문 확보 전 유지 후보·미확인으로 바뀌었다. Mesa/LLVM 묶음을 MIT 확정 목록에서 분리해 G4 OPEN으로 두었고, D5에 실제 경로·hash부터 내부 구성요소·버전·출처·전문·예외·최종 분류까지의 대응표를 요구한다. 기존 PE 문자열·제작자 정보 관측의 한계를 인정한다. | RECHECKED / CLOSED |
| L01-03 / S3 | D6가 유지 Qt FFmpeg의 정적 코덱을 실제 코덱·용도·관할 기준으로 특허 확인하도록 명시한다. WAV/PCM 용도 설명과 별개로 LGPL 표기·외부 import 부재만으로 검토 완료를 선언하지 않는다. | RECHECKED / CLOSED |

`git status --short`와 `git diff --stat`에서 L-P02 작성 변경의 공존을 확인했다. 이번 재확인은 L-P01 계획에 한정하며 L-P02 구현·후보 빌드 검증으로 합산하지 않는다. 정확한 4파일 stage tree 확인과 Git/CI는 C00 책임으로 유지한다. 상대 링크는 재검사하며, 문서 전용 수정이므로 제품 시험을 실행하지 않았다. 기존 원본 보존·기본 무전송·Credential Manager·AI/녹음 분리 및 작성자/독립 검토자 구분에 새 충돌을 찾지 못했다.

**REVIEW_READY — L-P01 계획 독립 검토 재확인 완료. 현재 OPEN 0건(S0 0 / S1 0 / S2 0 / S3 0). L01-01~03 모두 RECHECKED/CLOSED. D5 구현·D6/G4 확인은 후속 미결이며 이번 종결로 법률 적합성이나 릴리스를 승인하지 않는다.**
