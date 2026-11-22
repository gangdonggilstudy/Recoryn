# G01-B 보고서 독립 교차 검토 (G01-A 검토자)

- 대상: [G01-B 설계 v1.0 대비 AI·보안·UI 구현 재대조](g01-gap-ai-security-ui.md). 작성자는 w5:p8 Codex다.
- 대상 버전: LF 기준 sha256 `1e3cd7c11fe2fbafa7a1c9ab7e12af0735ae356653c493fbc865dddf6c7e3e0b`. 시작 시와 문서 작성 직전 모두 일치했다.
- 검토자: w5:p7 Claude(G01-A 작성자). 배정은 C00의 G01-A 교차 검토 지시이고, 쓰기 범위는 이 문서 하나다.
- 기준: commit `3f4ee9f2d56b5a7a97e8dccb49399b5637babd4e`. 실행 직후 `git diff --quiet HEAD -- src tests`로 `src/`와 추적 중인 `tests/`가 HEAD와 같음을 확인했다.
- 상태: 검토자 제출(REVIEW_READY). G01-B 보고서, 제품 코드, 시험, Git은 수정하지 않았다.

## 1. 검토 방법과 직접 확인한 증거

1. **기계 검사(전수):** scratchpad의 읽기 전용 파서로 G01B-001~083을 다시 셌다.
   - 판정 분포: DONE_VERIFIED 44, PARTIAL 26, MISSING 2, EXTERNAL_GATE 10, DEFERRED 1, 합계 83. 보고서 주장과 같다.
   - 구현 `file:line` 참조: 215개, 모두 파일 길이 안에 있다. `:행` 단축 표기와 `consent.py:230`처럼 디렉터리 없는 파일명은 같은 셀의 직전 파일 기준으로 해석했다.
   - test node: 117개, 모두 해당 파일에 `def test_...`가 실재한다.
2. **인용 시험 전수 실행:** 보고서가 인용한 node 117개 전체를 기존 시험 선택 실행으로 돌렸다.
   - G01-B가 "이번 미실행"으로 표시한 `tests/unit/test_gpu_runtime.py`, `tests/unit/test_diarization.py`, `tests/integration/test_diarization_independent.py`, `tests/integration/test_model_runtime_independent.py`, `tests/integration/test_desktop_independent.py`의 node도 포함했다.
   - 환경: Windows `.venv` Python 3.13.1, `QT_QPA_PLATFORM=offscreen`, `HF_HUB_OFFLINE=1`, `HF_HUB_DISABLE_TELEMETRY=1`, `DO_NOT_TRACK=1`, `-p no:cacheprovider`
   - basetemp: `%TEMP%\recoryn-g01br-3e2a886092a543a3877e0ff3a3ff9b4d`
   - 결과: **208 passed, 22.82s.** 매개변수 전개로 node 117개가 208개 시험이 됐다. JUnit 기준 errors 0, failures 0, skipped 0이다. JUnit sha256은 `7d6736cf63a20f46c50f01bdcfac6f84c8cd626e8c064f74eccbf30f0cf04835`다.
3. **DONE_VERIFIED 44행 의미 대조(전수):**
   - 각 행의 구현 줄 첫 문장과 인용 test 함수의 assert·raises 줄을 추출했고, 주장한 요구를 실제로 확인하는지 읽었다.
   - 결과: 44행 전부 구현과 시험 근거가 실재한다. 41행은 이견이 없다. 3행(G01B-016, 026, 060)은 행 문장 일부가 인용 시험으로 확인되지 않는다(G01BR-12, 13).
4. **PARTIAL·MISSING 28행 재현 추적(전수):**
   - 각 행이 가리키는 코드 위치를 열어 주장한 부재·결함을 따라갔다. 28행 모두 코드상 재현된다.
   - 판정 이견은 G01B-002 1건(MISSING→PARTIAL, G01BR-11)이다.
   - 위험 이견은 §2에 모았다. EXTERNAL_GATE 10행과 DEFERRED 1행은 자동 검증 범위 밖이라는 근거가 타당하다고 보았다.
5. **임시 반례(OS TEMP):**
   - 위치: `%TEMP%\recoryn-g01br-probe\probe_g01br.py`, sha256 `79294922596d085c3ec05aebf7dd657ef648ca993fc99bb423fdb5dd4efd1e91`
   - 조건: 제품 코드를 그대로 import하고, fake transport와 `TemporaryDirectory`만 쓴다. 네트워크·장치·모델은 쓰지 않는다. 실행은 `.venv\Scripts\python.exe -I probe_g01br.py D:/project/Recoryn/src`, exit 0이다.
   - P1(G01B-040): grant 1건으로 session A·B gateway가 모두 송신했다. A를 철회한 뒤에도 B는 같은 grant로 송신했다. 출력은 `opens_after_one_grant_two_sessions_and_revoke_a = 3`이다.
   - P2(G01B-024): 요약 작업이 (T1, S1)을 캡처한 뒤 사용자가 T1→T2→T1, S1→S2→S1로 선택을 바꿨다. 이 상태에서 늦은 `publish_summary`가 active로 선택됐다. 출력은 `late_summary_selected_after_ABA = True`, `user_reselected_S1_still_active = False`다.

## 2. 발견 사항

심각도는 [품질 체계](../quality-system.md)의 S0~S3를 쓴다. "등급 이견"은 G01-B가 매긴 위험과 다른 등급을 제안하는 경우다.

### 2.1 위험 등급(S0·S1) 이견

| ID | 대상 행 | 심각도 | 근거 | 제안 판정 |
| --- | --- | --- | --- | --- |
| G01BR-01 | G01B-040 | 등급 이견(S0 관련) | 결함 자체는 P1으로 재현된다. 그러나 quality-system의 S0는 "무동의 전송·비밀 유출·원본 대량 손실"이다. 이 결함은 그 정의에 맞지 않는다.<br>• 모든 송신에는 같은 실행 세대 안의 정확한 provider·endpoint·data type grant가 필요하다(`src/recoryn/security/consent.py:52-60`의 TTL 3600 s와 실행 세대, PK `:71`).<br>• UI는 동의 대상을 "동의할 데이터"·"동의"로만 보여주고 세션 범위를 제시한 적이 없다(`src/recoryn/ui/privacy.py:121,128`). 사용자가 동의한 범위를 넘어 송신한 것이 아니다.<br>• G01-B 스스로 "실제 무동의 전송 사고가 아니라 권한 모델 누락"이라고 적었다.<br>• 설계(architecture §전송 동의)가 요구한 세션·사용자 범위와 정책 version이 동의 키에 없는 계약 위반이므로 S1로 본다. 단, UI나 문서가 동의를 세션 한정으로 안내하는 증거가 나오면 S0가 맞다 | PARTIAL 유지, **S0→S1** |
| G01BR-02 | G01B-021, G01B-022 | 등급 이견(S1) | 내용 저장소가 provenance에서 basis를 결정적으로 다시 계산한다(`src/recoryn/content/store.py:462-476`). provider basis를 버리는 곳은 `src/recoryn/app/ai.py:512`다. 버려도 unresolved 정보는 잃지 않는다. provider는 unresolved 참조를 `model_inference`로 낮추고(`src/recoryn/summarization/adapters.py:44` 이하 parse_claims), 저장소는 `unresolved`로 남겨 오히려 설계에 더 가깝다. 따라서 021의 "의미가 동일 표현으로 보존되지 않는다"는 일부만 맞다. UI는 요약 머리에 검토 필요를 고지하고 claim마다 status를 표시한다(`src/recoryn/ui/content.py:322-334`). 자동 경로로는 `supported` 같은 확정 상태를 만들 수 없다(`src/recoryn/content/models.py:74-83`). 남은 결함은 basis 미표시와 검토 영역 미분리라는 표시 결함이고 잘못된 게시가 아니다 | PARTIAL 유지, **S1→S2** |
| G01BR-03 | G01B-030 | 등급 이견(S1) | 고정 1 GiB, GPU0 한정, 탐지 상태 폐기는 재현된다(`src/recoryn/ui/ai_bridge.py:206-210`). 실패하면 소유 child에서 RESOURCE 오류가 나거나 GPU 불가로 거부될 뿐이다. 원본·게시·전송에 영향이 없는 우회 가능한 품질 문제다 | PARTIAL 유지, **S1→S2** |
| G01BR-04 | G01B-031 | 등급 이견(S1) | `device_policy`는 "AI 실행 정책"으로 전체에 적용된다(`src/recoryn/ui/main.py:193-195`). 그런데 요약 경로(`src/recoryn/ui/ai_bridge.py:263` 이하)가 이를 읽지 않는 것은 사실이다. 그 결과는 사용자 정책을 어긴 로컬 CPU 사용이고, 데이터 전송·원본·게시에는 영향이 없다 | PARTIAL 유지, **S1→S2** |
| G01BR-05 | G01B-032 | 등급 이견(S1) + 계약 충돌 | 제품 계약 B13은 "local FasterWhisper는 명시적 로컬 모델 디렉터리만 받고"라고 명시해 수동 경로를 허용한다([product-contracts](../implementation/product-contracts.md) B13). 앱은 세 파일을 해시해 config key 정체성으로만 쓴다(`src/recoryn/ui/ai_bridge.py:183-189`). validation S04의 "로드 전 검증"과 충돌하므로 C00 결정이 먼저 필요하다. 대상 파일은 CTranslate2 binary와 JSON이며 pickle이 아니다. 사용자가 직접 고른 경로라는 점에서 S2다 | PARTIAL 유지, **S1→S2**, 계약 결정 선행 |
| G01BR-06 | G01B-012 | 등급 이견(S1) | 작업 동일성에 중요한 필드는 이미 묶여 있다. config key에 provider, model, endpoint, 실행 위치, artifact digest, context, 출력, 예산이 들어가고(`src/recoryn/ui/privacy.py:261-276`), 입력 snapshot과 nonce도 있다(`src/recoryn/app/ai.py:177,427`). grant는 gateway에서 고정된다(`src/recoryn/ui/privacy.py:322-366`). 빠진 것은 versioned plan 레코드와 영속 연결이며, 권한 상속이나 잘못된 게시의 재현 경로는 확인되지 않았다 | PARTIAL 유지, **S1→S2** |
| G01BR-07 | G01B-047 | 등급 이견(S1) | provider usage가 ledger에 자동으로 들어오지 않는 것은 사실이다. 하지만 그 결과 reserved나 unknown이 남아 보수적으로 차단할 뿐 과소 계상은 없다. 명시 확인을 거친 수동 정산도 있다(`src/recoryn/ui/privacy.py:421-424`). 예산을 넘겨 지출하는 위험은 G01B-046(S1, 동의)에서 다룬다 | PARTIAL 유지, **S1→S2** |
| G01BR-08 | G01B-066 | 등급 이견(S1) | `str(dict)` 표시(`src/recoryn/ui/main.py:406-418`)는 표시 결함이다. 복구 원본을 실제로 쓸 수 없게 만드는 원인은 storage·app에 확정 경로가 없는 것이고, G01-A의 [G1A-11](g01-gap-recording.md)(S1)이 이를 다룬다 | PARTIAL 유지, **S1→S2**. S1은 G1A-11로 일원화 |
| G01BR-09 | G01B-068 | 등급 이견(S1) | 검색표 seek이 `cellDoubleClicked`에만 연결된 것은 재현된다(`src/recoryn/ui/content.py:98`). 녹음 단축키(Ctrl+R 등)는 시험으로 확인된다. claim 링크는 `setOpenLinks(False)`와 `anchorClicked`로 연결돼 있고(`:129-130`), Qt 기본 QTextBrowser 상호작용상 키보드 링크 활성화가 가능하다. 다만 이를 확인하는 시험은 없다. 우회 가능한 접근성 결함으로 본다 | PARTIAL 유지, **S1→S2** |
| G01BR-10 | G01B-069 | 등급 이견(S1) | 동의 범위·만료·정책 version·예상 비용을 표시하지 않는 것은 표시 완전성 문제다. 근본인 권한 모델 결함은 G01B-040(G01BR-01)에서 다룬다 | PARTIAL 유지, **S1→S2** |

**동의하는 S1 판정:**

- **G01B-024:** P2로 실행 재현됐다. 사용자가 다시 고른 S1을 늦은 작업이 덮어썼다. 설계의 "늦은 작업이 최신 선택을 덮을 수 없다" 위반이며, 잘못된 버전 덮어쓰기라서 S1이 맞다. G01-A의 G1A-89(S3)는 ABA 부분을 과소 평가했다(§3, G01BR-19).
- **G01B-046:** 사용자 cap을 검증된 상한 없이 그대로 예약한다(`src/recoryn/ui/privacy.py:290,318`). strict 예산 요구가 실패하는 결함이다.
- **G01B-067:** 재시작하면 삭제 대기가 소실된다(`src/recoryn/ui/main.py:57,469-476`).

EXTERNAL_GATE의 S0·S1 등급은 게이트의 미검증 영향 표기라서 이견 없이 수용한다.

### 2.2 판정·근거 이견(S3)

| ID | 대상 행 | 심각도 | 근거 | 제안 판정 |
| --- | --- | --- | --- | --- |
| G01BR-11 | G01B-002 | S3 | 네트워크를 쓰지 않는 정적 `capabilities()`가 모든 provider 프로토콜에 이미 있다(`src/recoryn/providers/contracts.py:129-136,369-380`). 이는 설계의 정적 describe에 해당한다. 없는 것은 허가 후 probe와 DECLARED/OBSERVED/UNKNOWN 수준이다(`grep -rn "def probe\|DECLARED\|OBSERVED" src/recoryn/providers src/recoryn/transcription src/recoryn/summarization` 0건) | **MISSING→PARTIAL**(S2 유지) |
| G01BR-12 | G01B-060 | S3 | 저장 오류 경고가 녹음 표시보다 우선하는 기능과 수락 오디오 표시는 구현돼 있다(`src/recoryn/ui/main.py:549-567`). 그러나 인용 node 3개와 저장소의 어떤 시험도 이 표시를 assert하지 않는다(`grep -rln "저장 오류\|수락된 오디오" tests --include=*.py` 0건) | REC·미터·pause/stop은 DONE_VERIFIED. 저장 경고 우선·수락 오디오 하위 요구는 DONE_UNTESTED로 분리 |
| G01BR-13 | G01B-016, G01B-026 | S3 | 016: 5개 템플릿(`src/recoryn/summarization/adapters.py:25-31`) 중 시험은 meeting과 tasks만 쓰고, 템플릿 집합을 확인하지 않는다. 026: 계획 preview와 별도 동의 체크(`src/recoryn/ui/models.py:433,463`)를 확인하는 UI 시험이 없다. `tests/ui/test_models_ui.py`의 4개 시험은 모두 Ollama helper용이다. manager가 승인 없는 설치를 막으므로(`tests/unit/test_models.py::test_no_install_without_explicit_approval`) 우회 위험은 낮다 | DONE_VERIFIED 유지. 하위 주장에 시험 근거 부족을 주석으로 남김 |

### 2.3 누락(대상 범위 설계 요구 중 행이 없는 것)

| ID | 대상 범위 | 심각도 | 근거 | 제안 판정 |
| --- | --- | --- | --- | --- |
| G01BR-14 | architecture §모듈 경계 "UI는 앱 명령과 읽기 모델만 사용" | S3 | UI가 저장 계층과 CLI 내부 함수를 직접 쓴다. `from recoryn.storage import Library`(`src/recoryn/ui/main.py:39`), `recover_session`·`delete_session`·`chunks` 직접 호출(`:396-418,459,514`), `from recoryn.cli import _export`(`:430`) | 행 추가, PARTIAL S3 |
| G01BR-15 | architecture §비밀과 데이터 수명 "export/import 경로 정규화·root 이탈·symlink/reparse 검증"; validation S03 | S3 | 전사 내보내기가 대화상자 경로에 `path.open("x")`로 바로 쓴다(`src/recoryn/ui/content.py:352-372`). reparse·링크 검사나 라이브러리 내부 금지 같은 검증이 없다. CLI 오디오 내보내기는 이를 검사한다(`src/recoryn/cli.py:96-113`). 또 `"x"` 모드라서 대화상자에서 덮어쓰기를 확인해도 FileExistsError로 실패한다 | 행 추가, PARTIAL S3 |
| G01BR-16 | architecture §전송·UX의 구현됐지만 행이 없는 요구 | S3 | (a) 추론 라이브러리의 묵시 다운로드·telemetry 차단 환경변수를 소유 child에 설정한다(`src/recoryn/app/inference.py:54`, `src/recoryn/diarization/process.py:48`). (b) 녹음 동의·규정 안내(`src/recoryn/ui/main.py:146`). (c) 일시정지가 중단 구간을 되돌리지 않음을 표시(`src/recoryn/ui/main.py:357`). (d) 사용자 지정 로컬 서버의 신뢰 범위 안내는 찾지 못했다(`grep -rn "신뢰\|후속 전송" src/recoryn/ui`는 화자 구분 manifest 문구뿐) | (a)~(c)는 행 추가 후 근거에 따라 DONE·DONE_UNTESTED. (d)는 MISSING S3 |
| G01BR-17 | architecture §비밀과 데이터 수명 "실제 비밀은 요청 직전 최소 범위에서 읽는다" | S3 | vault 읽기가 요청 시점이 아니라 실행 문맥을 만들 때 일어난다(`src/recoryn/ui/privacy.py:293`). 이후 header가 작업이 끝날 때까지 `ExecutionContext`에 머문다(`:299,320`). G01B-044는 이 하위 요구를 판정하지 않았다 | G01B-044에 하위 요구로 추가, PARTIAL S3 |

## 3. G01-A와의 경계

| ID | 경계 | 심각도 | 근거 | 제안 |
| --- | --- | --- | --- | --- |
| G01BR-18 | G01B-067(S1) ↔ G1A-72(S2) | S1(정합) | 같은 근본 원인이다. storage에 DELETE_PENDING 목록 API가 없고(`src/recoryn/storage/library.py:203-212`), UI 대기 목록은 메모리에만 있다. 재시작 뒤에는 삭제를 요청한 원본이 남고 재시도할 진입점이 없다. 검토자로서 G01-B의 S1이 맞다고 판단한다. **G01-A 작성자로서 G1A-72의 S2를 S1로 정정한다** | C00 통합 시 S1 하나로 정합. GF-13(storage API)를 먼저 하고 F-LIFE02(UI 복원)를 한 단위 또는 연속 단위로 진행 |
| G01BR-19 | G01B-024(S1) ↔ G1A-89(S3) | S1(정합) | 같은 근본 원인(ID CAS에 version·설정 키가 없음)이다. P2가 사용자 재선택 덮어쓰기를 재현했다. **G1A-89의 ABA 부분을 S1로 정정한다.** latest pointer 분리·설정 키·OUTDATED 표시는 S3로 남긴다 | F-SUM02와 GF-15의 선택 version 부분을 하나로 묶음 |
| G01BR-20 | G01B-071 ↔ G1A-15 | S2 | G01B-071은 BLOCKED 사유별 다음 행동 UI를 요구한다. 그런데 CONSENT·AUTH·RESOURCE·BUDGET·CAPABILITY 사유를 기록하는 제품 경로가 없다(`src/recoryn/jobs/__init__.py:699-711`, `src/recoryn/jobs/runner.py:182-191`; G1A-15) | 순서 의존을 명시: GF-03 다음에 F-UX02 |
| G01BR-21 | G01B-066 ↔ G1A-11·G1A-62 | S1(G1A-11) | G01B-066의 "저장 복구 엔진 부재로 판단하지 않는다"는 salvage에 대해서는 맞다. 하지만 복구 뒤 INTERRUPTED·PAUSED 세션을 확정하거나 재개하는 전이가 storage·app 어디에도 없어 내보내기·전사가 막힌다(G1A-11) | F-RECUI01은 GF-01과 같은 단위 또는 바로 뒤에 둠 |
| G01BR-22 | G01B-050 ↔ G01-A | S2 | 보존 정책 엔진(범위별 자동 삭제, 활성 writer 제외)이 storage·app 어디에도 없다(`grep -rni retention src/recoryn/storage` 0건). G01-B는 UI만 PARTIAL로 판정하고 저장 실체를 G01-A에 넘겼으나, G01-A는 이를 G01-B 범위로 분류했다. 양쪽 모두 판정 행이 없다 | C00이 소유자를 하나로 정하고 storage+app+UI 단위로 배정 |
| G01BR-23 | G01B-021 ↔ G1A-122 | S3 | 저장소가 provenance로 basis를 재계산하는 것이 현재의 정본 동작이다. provider basis는 `src/recoryn/app/ai.py:512`에서 버려진다 | 공동 계약으로 정함: 재계산 규칙을 문서화하거나 provider basis를 저장할지 결정하고, UI가 basis를 표시 |

참고(이견 아님):

- G01B-065(요약 내보내기 없음)와 G1A-93(재내보내기 동일성 미시험)은 같은 내보내기 단위로 묶을 수 있다.
- G01B-083(DEFERRED)과 G1A-94(DEFERRED)는 고급 편집·템플릿으로 중복 판정이다.
- G01B-052와 G1A-101(둘 다 MISSING S2)은 진단 연결의 같은 축이다.
- 위험 열의 의미가 두 보고서에서 다르다. G01-B는 DONE 행에도 요구가 깨질 때의 영향을 적고, G01-A는 열린 gap만 적는다. 통합 집계 때 정규화가 필요하다.

## 4. 확인 범위 요약

| 항목 | 확인 수 | 결과 |
| --- | ---: | --- |
| 행·판정 재계수 | 83 | 일치 |
| 구현 `file:line` 범위 | 215 | 전부 유효 |
| test node 실재 | 117 | 전부 실재 |
| 인용 node 실행 | 117 node(208 시험) | 전부 통과. G01-B 미실행 node 포함 |
| DONE_VERIFIED 의미 대조 | 44 | 41 이견 없음, 3 하위 근거 부족(S3) |
| PARTIAL·MISSING 재현 추적 | 28 | 28 재현. 판정 이견 1(G01B-002) |
| EXTERNAL_GATE·DEFERRED | 11 | 근거 수용 |
| 임시 반례 | 2 | P1·P2 재현(G01B-040·024 결함 존재 확인) |

## 5. 이견 집계

G01-B 판정에 대한 이견은 17건이다(G01BR-01~17).

- **S0 관련 1건:** G01BR-01. G01B-040을 S0→S1로 제안한다.
- **S1 관련 9건:** G01BR-02~10. 10개 행(012, 021, 022, 030, 031, 032, 047, 066, 068, 069)을 S1→S2로 제안한다.
- **S3 7건:** G01BR-11~17. 판정 1, 근거 2, 누락 4.

경계 항목은 6건이다(G01BR-18~23). 그중 G01BR-18·19는 G01-B 판정에 동의하면서 G01-A 보고서의 등급을 S1로 올리는 자기 정정이다. 나머지 4건(20~23)은 순서·소유자 조정이다.

S0·S1 이견 10건(G01BR-01~10)은 모두 결함의 존재가 아니라 등급에 대한 이견이다. 해당 결함 자체는 전부 코드로 재현됐다. G01-B 작성자의 반론이나 C00 판정으로 닫아야 하며, 열린 S0·S1 이견을 0으로 만드는 것이 G-P01 수락 조건이다.

## 6. 미해결·참고

1. G01-A 보고서는 이번 배정의 쓰기 범위 밖이라 수정하지 않았다. G1A-72와 G1A-89의 S1 정정은 이 문서의 G01BR-18·19가 정본이다. C00의 v1-gap-plan 통합 때 반영을 요청한다.
2. G01BR-05(수동 로컬 모델)와 G01BR-01(동의 범위의 UI 고지)는 제품 계약과 설계 문구 사이의 결정이 필요하다. 작업자 권한 밖이다.
3. 임시 반례 스크립트는 OS TEMP에만 있고 저장소에 추가하지 않았다. 후속 구현 단위에서 정식 시험으로 옮길 것을 권한다.
4. 작업 트리에는 이 검토와 무관한 다른 세션의 변경(packaging, license 문서, l08 관련 파일)이 있다. 이 검토는 그 파일들을 읽거나 승인하지 않았다.

## G01-C 통합안 확인

- 대상: [v1-gap-plan](../implementation/v1-gap-plan.md), LF sha256 `9a75643e440b9c7d74c748a3c5da2eb016b24410f9acf9c34f3f9df80dbb9cf6`
- 확인자: w5:p7 Claude. G01-A 작성자이자 G01-B 교차 검토자다.
- 함께 읽은 문서: 통합안이 인용하는 [G01-A 교차 검토](g01-gap-recording-review.md)의 G01AR-01~05. 판정 근거가 된 코드도 다시 열었다.
- 결정 자체는 C00 몫이며, 아래는 사실·근거 확인 결과다.

### 반영 정확성

1. **입력 표:** 두 보고의 sha256과 집계가 맞다. G01-A는 `e7f4655a…bd6f`, 107행 분포가 일치한다. G01-B 교차 검토는 `ff7ebe94…ac26`, 이견 17건(등급 10, 판정·근거 3, 누락 4)과 경계 6건이 일치한다.
2. **등급 결정이 G01BR 제안과 일치한다.**
   - G01B-040: S0→S1
   - G01B-012, 021, 022, 030, 031, 032, 047, 066, 068, 069: S2
   - G01B-024+G1A-89: S1 통합
   - G01B-067+G1A-72: S1 통합
   - G01B-046: S1 유지
   - G01B-066의 S1을 G1A-11로 일원화
3. **후속 단위 대응이 빠짐없다.** G01-A의 S2 이상 gap은 모두 후속 단위에 들어갔다.

   | G01-A 행 | 후속 단위 |
   | --- | --- |
   | G1A-13·44 | G-P08 |
   | G1A-36 | G-P08 |
   | G1A-56 | G-P10 |
   | G1A-68 | G-P09 |
   | G1A-101~103 | G-P14 |
   | G1A-15·22 | G-P07 |
   | G1A-62 | G-P04 |
   | G1A-39·42·51·63·64 | 이후 |

   G01BR-20~23의 순서·소유자 제안도 반영됐다. G-P07은 GF-03을 먼저 하고 F-UX02를 뒤에 둔다. G-P04에는 F-RECUI01이 들어갔다. 보존 정책 엔진은 G-P14다. basis 공동 계약은 G-P12다.
4. **G01-A의 판정 오류 두 건을 정정한다.** G01AR-02와 G01AR-03을 코드로 다시 확인했고 둘 다 맞다.
   - G1A-73: `tests/unit/test_storage.py::test_delete_intent_before_files_and_no_resurrection`이 `remove_tree`에 PermissionError를 주입해 DELETE_PENDING을 확인한 뒤 재삭제로 DELETED_LOCAL을 확인한다. 나는 문자열 `MEDIA_REMOVAL_FAILED` 검색 0건만 보고 DONE_UNTESTED로 판정했다.
   - G1A-93: `tests/e2e/test_ai_workflow.py::test_record_transcribe_summary_edit_and_repeatable_srt`가 고정 revision의 SRT 재생성 동일성을 확인한다. 나는 이 node를 놓쳤다.
   - 통합안의 "해당 하위 요구 DONE_VERIFIED" 결정에 동의한다. G1A-35의 사전 할당 하위 요구 PARTIAL(G01AR-04)도 받아들인다.

### 확인 결과 이견과 보강

| ID | 대상 | 심각도 | 근거 | 제안 |
| --- | --- | --- | --- | --- |
| G01CR-01 | 설계 결정 G1A-22 | S2 | 결정문은 "첫 블록이 수락되기 전에는 UI가 REC를 표시하지 않음을 시험으로 고정"이라고 하는데, 현재 코드는 이 조건을 만족하지 않는다. UI는 `recorder.start()`가 장치 ready 뒤 반환하면 `started` callback에서 곧바로 "● REC"를 표시한다(`src/recoryn/ui/main.py:342-345`). 첫 블록 수락 여부는 보지 않는다. 따라서 시험만 추가하면 실패한다 | G-P07 범위에 `ui/main.py`의 표시 조건 변경을 명시한다. 장치 ready와 첫 수락 블록을 구분하는 관측이 필요하면 `app/desktop.py`도 포함한다 |
| G01CR-02 | G-P03 수락 기준의 "설정 키" 비교 | S2 | 게시 transaction에서 비교할 "현재 설정 키"가 DB 어디에도 영속되지 않는다. `content_selections`에는 transcript_id·summary_id·두 version만 있다(`src/recoryn/content/store.py:135-140`). 설정 키는 UI의 `PrivacyPanel.config_key`와 template에만 있다(`src/recoryn/ui/privacy.py:261-276`). 그런데 통합안은 schema migration(G-P09)을 G-P03보다 뒤에 둔다 | G03 계약안에서 다음 중 하나를 C00이 정한다: (a) content 전용 신규 테이블을 기존 additive 방식(`CREATE TABLE IF NOT EXISTS`, user_version 불변)으로 추가하는 것을 허용한다. (b) 설정 키는 게시자가 받은 기대값과 요약 body에만 기록하고 현재값 비교는 후속으로 미룬다. 선택 version 비교는 기존 열만으로 가능하다 |
| G01CR-03 | 등급 결정 "G1A-11·62·24 / 원 등급 S1" | S3 | G01-A의 원 등급은 G1A-11 S1, G1A-62 S2, G1A-24 S3(DONE_UNTESTED)이다. 한 단위로 묶어 S1로 처리한다는 결정에는 동의한다 | 원 등급 칸을 "S1/S2/S3"으로 정정 |
| G01CR-04 | 등급 결정 "백업·복원·import … 행 없음 → MISSING S2 추가" | S3 | 백업 생성 절차는 이미 G1A-69(MISSING S3)이고 migration은 G1A-68(MISSING S2)이다. 행이 없던 것은 복원·import의 안전한 재개(G01AR-05)와 보존 정책 엔진(G01BR-22)이다 | 백업은 G1A-69를 S2로 올려 새 행과 합치고 중복 계수를 피한다 |
| G01CR-05 | G01B-024+G1A-89 근거 | S3 | 근거로 G01AR-01만 인용했다. 같은 ABA 결함을 G01BR-19의 P2(`%TEMP%\recoryn-g01br-probe\probe_g01br.py`)도 독립 재현했다 | 근거에 두 독립 재현을 함께 적으면 증거가 완전해진다 |

**참고(이견 아님):** "이후"의 사전 할당 버퍼 단위는 domain 계약을 함께 바꿔야 한다. `PCMBlock`이 `type(payload) is bytes`를 강제하므로(`src/recoryn/domain/__init__.py:123-127`) 재사용 버퍼는 패킷마다 bytes 복사 없이는 domain을 통과할 수 없다. 단위를 시작할 때 domain(P01/B11 소유 경계)을 범위에 넣어야 한다.

**동의하는 결정:**
- G1A-15는 설계를 따른다. G1A-26·53·17은 현재 동작을 설계에 반영한다.
- G1A-46 DEFERRED를 수용한다. 나는 MISSING S3로 판정했지만 범위 결정은 C00 몫이다.
- G01B-032는 B13 유지와 digest 표시로 처리한다.
- G-P04를 push한 뒤 G-P05를 시작하는 순서, 그리고 GD-P01·GT-P01 배치에도 동의한다.

**집계:** 이견 5건(S0 0, S1 0, S2 2, S3 3)과 참고 1건이다. S0·S1 이견은 없다.
