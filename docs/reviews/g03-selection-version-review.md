# G03-R / G-P03 선택 version CAS 독립 검토

2026-11-23, 검토자 w5:p8 Codex. 작성자 w5:p7 Claude와 다른 검토자이며 G01AR-01 원 반례 재현자다.

**S0/S1 발견 없음. OPEN 3건: S2 2건, S3 1건.** 원 ABA의 새 version 캡처 경로, 게시 transaction, 실제 앱 게시 호출부와 화자 구분 연결을 확인했다. 지정 tree의 전체 오프라인 회귀는 **8021 PASS**다. G03-02는 작성자가 이미 남긴 경합의 재현·등급 판단과 추가 결과 범위이며, R2 수용을 번복하는 지적이 아니다. 최종 수용/통합은 C00 결정이다.

## 입력 고정과 쓰기 경계

대상은 **`9538d283cfd82e9f49f6dec12fe90a6e01cd3959`**, 기준 HEAD는 확인 당시 **`0305306e256a39562244f63e42a627fc2e79bde9`**다. `git diff --stat HEAD 9538d283`을 직접 확인해 아래 6파일, **1522 insertions / 6 deletions**임을 대조했다.

| 검토 tree 파일 | SHA256(CR 제거·LF 기준) |
| --- | --- |
| src/recoryn/app/ai.py | `7322244b351b914e30a2d756d8b29c6534120674f380e32d665b818daef66e08` |
| src/recoryn/content/store.py | `3a00278f0f6558adf568a752208406eb059dd8c66b47ba9f9c086613d5cd0173` |
| src/recoryn/ui/ai_bridge.py | `e5c43dd38133ae7a38fd2d3f0c277264dbac7886182341e75c71660171a53981` |
| tests/unit/test_content.py | `fb068671182073c3abec41e6d899e39725ad31c1621c66b80a2e8cbc4eee0bf7` |
| tests/integration/test_selection_version_cas.py | `6917b8d729a34ef2aa29953f54f61e15ce4d510516b7bcdda7e278be0deb02b6` |
| docs/testing/g03-selection-version-cases.md | `9432dc264ae7f7ad6a7adb19a086aec388b481df099ef5f97bc7c311c7b6fc78` |

`git archive --format=tar 9538d283…`를 **OS TEMP의 새 디렉터리**에 추출했다. 이하 `R = C:/Users/gangd/AppData/Local/Temp/recoryn-g03r-7cvos7ko`, 정본 사본은 `R/tree`다. G-P02가 섞인 작업 트리에서 판정하지 않았다. 검토 끝에도 위 6파일의 hash가 모두 같았다. 저장소 쓰기는 이 문서 하나이며 제품/시험/공용 문서/Git은 수정하지 않았다. 추가 반례·변이는 TEMP에만 작성했다.

## 직접 실행 결과

환경은 기존 `.venv` Python, `-B`, `QT_QPA_PLATFORM=offscreen`, bytecode 억제, HF/transformers offline·telemetry 차단, 실행별 고유 OS TEMP basetemp, `-p no:cacheprovider`다. 설치·실제 장치·모델·네트워크·유료 호출·계정·vault 쓰기·하위 에이전트/pane은 사용하지 않았다. 추가 반례의 녹음은 작성자의 합성 PCM fixture다.

```powershell
# cwd: R/tree, R은 위 절대 경로의 축약 표기
D:/project/Recoryn/.venv/Scripts/python.exe -B -m pytest -q -p no:cacheprovider --basetemp R/pytest-full --junitxml R/full.xml --tb=short --durations=8
```

직접 결과 **8021 passed in 251.12s / exit 0**, 실패·error·skip·xfail 0이다. `R/full.xml` LF SHA256은 **`f701abf2d194a3afc2d6dadd389b13b734120b0490e89ab71305ab90077a0b99`**다. JUnit을 직접 집계해 다음을 확인했다.

- G03 통합 파일 **203개**, unit의 신규 `test_g03_*` **21개**로 선언 node 수와 같다. 기존 content unit을 신규 21개로 오인하지 않았다.
- `tests/ui` **49개** 전부 PASS. `test_live_ui.py` **10개**, `test_gpu_runtime_ui.py` **4개**도 이 tree에서 전부 PASS다. C00이 알려준 작업 트리의 G-P02 관련 11 FAIL과 구분한다.
- 작성자의 작업 트리 940/1350 등은 이 검토의 실행 수로 옮기지 않았다. 여기서는 지정 tree 전체를 한 번 실행했다.
- 사본에서 `ruff check --no-cache src tests scripts packaging`도 직접 PASS했다. 작성자의 mypy/format 전체 실행은 이 검토에서 다시 실행한 수치가 아니다.

## G01AR-01 원 반례 재확인

원 파일 `C:/Users/gangd/AppData/Local/Temp/recoryn-g01ar-miqmtpy2/test_cross_review.py`를 읽고 LF SHA256 **`1c7a248517ce2cd38255e33d6545a4946536f2ddc2b44fb4b4984975eb9362f7`**를 기록했다. 원 파일을 바꾸지 않았다.

두 TEMP 사본을 구분했다.

| 사본 | 변경 | 직접 결과 |
| --- | --- | --- |
| `R/test_original_legacy.py` | 작업 트리 절대 import를 `R/tree/src`로만 변경. 옛 게시 API 그대로 | **2 FAIL / 0.41s**. version 인자를 생략해 기존 ID-only 의미가 유지되는 대조군 |
| `R/test_original_with_versions.py` | 위 import + 작업 계획 시 `selection_state` 캡처 + 게시에 전사/요약 기대 version 전달. fault 순서·늦은 결과 후보 oracle는 유지 | **2 PASS / 0.39s**. 요약 ABA·전사 ABA 모두 다시 고른 S1 유지 |

새 사본 LF SHA256은 **`9d2b6370da1255f1593de97a0977c61a38857096e9d71f2aac9a7a85d081a3a4`**다. 실행은 각각 `-k selection_version --rootdir R -p no:cacheprovider --basetemp R/pytest-original-{legacy,versions}`로 두 행만 선택했다. `original-versions.xml` LF SHA256은 `7bf1356b75745905324e767ec9ca3d07aca79629e2c6be160c6bcd9c398bbadd`다.

새 API에 필요한 계획 시점 정보가 없는 원문을 무변경 실행해서 PASS했다고 쓰지 않는다. 신규 인자 기본값 None의 LEGACY 유지가 C00 승인 계약이므로 대조군의 2 FAIL은 새 회귀로 세지 않는다. 실제 제품의 비동기 게시 호출은 전수 검색해 **app/ai.py 전사 3곳·요약 1곳, ui/ai_bridge.py 화자 1곳** 모두 version 전달을 확인했다. 앱 A1/A2/A5와 D1은 전체 회귀에서 통과했다. TEMP 보강의 같은 ID 재선택(`S1→S1`, `T1→T1`) 2행도 PASS했다.

## 게시·DB·시험 oracle 확인

- `content/store.py:703` 이후의 publisher는 `jobs._publish_with`에 SQL connection을 받아 `_create_summary`를 호출한다. `jobs/__init__.py:597`과 `:191`의 transaction/fence 경계 안에서 ID·전사 version·요약 version·요청 설정 키를 함께 읽고 판정한다(`content/store.py:549`, `:562`, `:565`, `:567`). content/event/선택/Job 완료가 이 transaction을 공유한다. 단순히 미리 읽은 값을 게시 뒤에 검사하는 구조가 아니다.
- 전사도 `_create_transcript`에서 선택을 확정하기 전에 기대 version을 비교하고, complete/streaming draft/partial에 전달한다. 편집 보호용 기대 ID 불일치도 유지한다. 합성 취소·삭제·불완전 결과 보강은 아래에서 확인했다.
- `selection_state(:253)`의 ID·version·설정 읽기는 공유 root_mutex 아래다. 이는 협력하는 같은 프로세스의 ContentStore/Library 쓰기와 정합한다. 별도 SQLite snapshot transaction이나 임의의 외부 SQL writer까지 인증하는 API로 확대하지 않는다. Library OS writer 배제 계약도 함께 필요하다.
- 기존 DB의 테이블 없음→추가, 재열기 멱등, 요청 횟수/선택 version 불변, cascade, 삭제 의도 거부는 신규 unit 7개가 실제로 확인한다. G-P09 인계 의무도 문서에 있다.
- 추가로 기준 commit `0305306…`의 **src 전체를 `R/old-tree`에 별도 추출**했다. G03 코드로 만든 DB/설정 키 포함 요약을 구 코드의 별도 interpreter에서 열어 읽고, 모르는 요청 표를 유지하며, 구 Library로 삭제했을 때 그 표가 cascade되는 것을 확인했다. `R/check_old_compat.py`, `old-compat.stdout.log`에 PASS가 있다. 구버전에 새 ABA 보호가 생긴다는 뜻은 아니다.
- 주 결정 cube는 구현 predicate를 import하지 않고 이력(T0/AWAY/ABA/EDIT, S0/AWAY/ABA/PUB)으로 쓴 설계 술어다. HB 표는 최종 선택과 CAS 성공/실패를 literal로 둔다. 앱은 실제 AIService와 Event를 쓴다. fixture와 상태 조회를 제품에서 사용하는 사실이 그 자체로 oracle 종속은 아니다. mutation 결과도 비교 삭제를 실제로 구별함을 보강한다. 미래 키·임의 actor·무한 이력을 모두 증명한 것은 아니다.

## 독립 보강 반례와 미해결 판단

`R/test_independent_review.py`는 작성자의 합성 데이터/차단 provider fixture만 재사용하고 기대 결과는 별도로 적었다. LF SHA256은 **`8c8af68e4b5eff7ed7532963853aa99cee03fe0f174bff1332c9896bb6b5abc7`**다.

```powershell
# cwd: R/tree
D:/project/Recoryn/.venv/Scripts/python.exe -B -m pytest R/test_independent_review.py --rootdir R -q -p no:cacheprovider --basetemp R/pytest-independent --junitxml R/independent.xml --tb=short
```

직접 결과 **437 PASS / 1 FAIL in 41.79s**다. FAIL은 G03-01이며 나머지는 미실행 432조합·재선택 2·합쳐짐 3경로다. TEMP root에서 작성자 fixture를 import해 integration marker 등록이 없는 경고 1개가 있었고, 제품 회귀 실패나 import/수집 오류는 아니다. `independent.xml` LF SHA256은 `c98f5f12429f57aad2591e79dd6347d3119e56747a01012c95eb2ca17640b4ac`다.

### G03-01 / S2 / OPEN — 필수 설정 키 None이 domain 검증을 통과해 SQLite 오류로 노출됨

- **근거:** `src/recoryn/content/store.py:47`의 `_settings_key`는 선택 인자의 None을 허용한다. 필수 키인 `request_summary_settings(:268)`도 이 helper를 그대로 호출해 None을 거르지 않는다.
- **재현:** `test_required_settings_key_none_has_a_domain_validation_error`. 정상 `'known'` 키 기록 뒤 `content.request_summary_settings('s', None)` 호출. **실제 `sqlite3.IntegrityError: NOT NULL constraint failed: content_summary_requests.settings_key`**, 기대 ValidationError assertion FAIL. `R/none-key.json`에 실제 오류와 DB 행 `[["known",1]]`을 기록했다. transaction rollback은 유지된다.
- **기대:** 문서 §3.1의 필수 문자열 계약대로 SQL 전 `ValidationError`. publish_summary의 선택 인자 `settings_key=None`는 LEGACY 의미를 유지한다.
- **제안:** 필수 요청 메서드는 `text_value(..., maximum=256, empty=False)`로 직접 검증하거나 required validator를 분리하고 None 음성 시험을 추가한다. 앱은 `_key`의 문자열을 전달하므로 정상 제품 경로에서 관측한 데이터 손실/잘못된 게시가 아니다. S0/S1로 확대하지 않는다.

### G03-02 / S2 / OPEN — 합쳐짐 경합은 보수적이나 마지막 키와 다른 active가 남는 범위까지 고지·수용 필요

- **근거:** `app/ai.py:506`의 합쳐짐 판정과 `:509`의 키 기록은 분리된다. 작성자는 경우의 수 문서 `:230`, `:277`에 이 창을 남기고 ‘active는 이전 요약에 머문다’고 설명했다. **R2의 runner 거부 수용은 인정하며 별도 이견으로 세지 않는다.** 이 항목은 합쳐짐 창에 대한 독립 재현과 처리 결정을 요청한다.
- **재현:** `test_documented_merge_windows_preserve_results_and_manual_choice[scenario]` 3행. K1 작업을 막고 K2를 입장시킨 뒤, 세 번째 K1 요청의 실제 `_admit` 반환과 키 기록 사이에 Event로 완료를 강제했다. 결과는 각각 `R/merge-*.json`이다.

| 순서/조건 | 직접 결과 |
| --- | --- |
| 창에서 K1만 완료 → K1 기록 → K2 완료 | 두 결과 모두 후보, active는 초기 S1, 최근 요청 키 K1 |
| 창에서 K1과 K2 모두 완료 → K1 기록 | K1은 후보, **active는 K2**, 최근 요청 키는 K1 |
| 합쳐지기 전 사용자 S1→S2→S1 → K1 기록 → 완료 | 두 결과 후보, 사용자가 다시 고른 S1 유지 |

- 세 행 모두 작업 두 개 SUCCEEDED·revision 두 개 보존을 확인했다. 두 번째 경로에서 K2가 선택된 순간의 최신 키는 K2였으므로 과거 결과가 최신 정책을 우회해 게시됐다는 증거는 아니다. 세 번째는 **옛 기대 version을 갱신하지 않는 동작이 사용자의 선택을 지키는 것**이어서 그 자체를 S1 결함으로 보지 않는다.
- **기대/제안:** 이 보수적 결과를 R2와 같이 C00가 명시적으로 수용할지 결정하고 문서에 K2가 남는 변형도 적는다. 수용 시 명시 재시도/후보 접근 경로와 시험을 연결한다. 수정 시 captured version을 유지하면서 입장·키 기록의 조정 경계를 설계하거나 새 요청 nonce를 쓰는 방안을 검토한다. underlying DB는 같은 Library SQLite이므로 ‘동일 SQL transaction 외에는 어떤 조정으로도 닫을 수 없다’는 표현은 좁히는 것이 맞다. 사용자 재선택을 덮거나 결과가 없어지는 S1은 이번 반례에서 관측하지 않았다.

### G03-03 / S3 / OPEN — feasible 분모와 축소 실행 집합의 용어 혼용

- **근거:** 경우의 수 문서 `:125`는 Ω=576에서 ‘제약 후 실행 집합 F=144’라고 쓰지만, 축소 이유는 fixture 불가능성이 아니라 PARTIAL/취소/삭제 guard의 독립성 가정이다. `docs/testing/case-space.md`의 F는 fixture로 구성 가능한 조합이며 제품이 거부할 조합도 포함한다.
- **재현:** 독립 `test_all_432_feasible_omitted_combinations`에서 원 576중 기존 실행 144를 제외한 **432행 전부 구성·PASS**했다. 구성 불가 제외 0이다. ACTIVE+PARTIAL의 추가 80, CANCELLED 추가 176, DELETED 추가 176이다. 각 행은 raw SQL로 선택/두 version/row 수를 비교했다. PARTIAL은 선택 불변·revision 1개 증가·RUNNING checkpoint, 취소/삭제는 StateConflict·revision 증가 0이다.
- **기대/제안:** feasible F=576, 작성자 실행 부분집합 E=144로 구분하고 E의 축소 근거·미실행을 표시한다. 실제 통합 **203 node**와 신규 단위 **21 node** 집계는 맞으므로 그 숫자를 고칠 사안은 아니다. 검토자가 TEMP에서 실행한 432를 작성자의 저장소 시험 432개로 옮겨 쓰지 않는다. 문서가 이미 미검증 조합을 공개했고 추가 실행도 통과했으므로 S1 위험 증거가 아닌 S3 용어 정정이다.

## mutation 독립 재현

정확한 tree의 pyproject/src/tests/scripts/packaging을 함께 TEMP에 복사하고, 사본 cwd·사본 src import를 매번 확인했다. 정상 선택 node **PASS / 1.612초** 후 M1~M9를 하나씩 변이시켜 **9/9 목표 testcase FAIL, import/수집 error 0**을 직접 재현했다. 사본별 원본/변이 hash·명령·실패 node는 `R/mutations/results.json`, diff와 stdout은 같은 루트에 있다. JSON LF SHA256은 **`15207fb853f499b258fad2231faca3402682f65923d6162a4ec38aa405810b84`**다.

| 변이 | 직접 검출한 node/관측 |
| --- | --- |
| M1 전사 version 비교 제거 | G03-S-ABA-S0-SAME-VER: 후보 기대 위반 |
| M2 요약 version 비교 제거 | G03-S-T0-ABA-SAME-VER |
| M3 설정 키 비교 제거 | G03-S-T0-S0-NEWER-VER |
| M4 expected≤current로 완화 | G03-S-T0-ABA-SAME-VER |
| M5 전사 게시 version 비교 제거 | G03-T-ABA-VER-corrected |
| M6 요청 설정 기록 no-op | G03-S-T0-S0-NEWER-VER |
| M7 앱의 기대 version을 None 전달 | A1: 실제 앱 요약 ABA |
| M8 합쳐진 요청 기록 생략 | MG1: 마지막 K1 요청 처리 |
| M9 기록을 `_admit` 앞으로 이동 | R1: 입장 전 거부의 기록 0 |

작성자의 mutant별 전체 실패 수 4/5/6/…을 재현했다는 주장은 하지 않는다. 여기서는 각 변이당 위 목표 node를 선택해 검사 삭제가 검출되는지 확인했다. mutation 일부/선택 결과를 프로젝트 전체 coverage로 부르지 않는다.

## 인계

**G03-R REVIEW_READY / OPEN 3(S0 0 / S1 0 / S2 2 / S3 1)**. 핵심 version CAS와 실제 호출 연결은 검토 범위에서 확인됐으며, 남은 낮은 심각도 항목의 수정/수용은 C00와 작성자가 결정한다. 실제 장치·모델·전원 장애·임의 외부 writer의 내구성은 이번 자동 검증 결과가 아니다.

이 보고 이후에는 G-P03 커밋 완료 신호를 기다리며 G-P02 2단계 준비 상태로 돌아간다. **ai_bridge.py는 아직 수정하지 않는다.** G-P02 2단계 완료 조건에 C00이 통보한 live UI 7건·GPU runtime UI 4건 및 `tests/ui` 전체 PASS를 포함한다. 두 기존 파일의 fixture 변경이 필요해지면 쓰기 범위 추가를 먼저 요청한다. 이 리뷰를 위해 G-P02 문서나 코드를 바꾸지 않았다.

## RECHECK

2026-11-23, G03-R 재확인. **G03-01~03 모두 RECHECKED, OPEN 0(S0 0 / S1 0 / S2 0 / S3 0)**. G03-02는 결함 창을 제거했다는 판정이 아니라 **C00의 보수적 결과 수용과 문서 보강을 확인해 닫은 항목**이다. 새 G03-04 이상 발견은 없다. 앞의 1차 내용은 이력으로 보존한다.

### 대상 고정과 실행 격리

대상은 **`34a5ff0d3bd96e62542a064de49ab18e44261dec`**, 확인 당시 HEAD는 **`17f875246eb5ef9ffc73f17577ca5f1771a9af83`**다. `git diff --stat 17f8752 34a5ff0d…`은 G-P03의 6파일, **1617 insertions / 6 deletions**였다. 1차 tree와 G-P03 6파일만 비교한 명령은 다음과 같다.

```powershell
git diff --stat 9538d283 34a5ff0d3bd96e62542a064de49ab18e44261dec -- src/recoryn/app/ai.py src/recoryn/content/store.py src/recoryn/ui/ai_bridge.py tests/unit/test_content.py tests/integration/test_selection_version_cas.py docs/testing/g03-selection-version-cases.md
```

직접 결과는 **store.py·test_content.py·경우의 수 문서의 3파일만 변경, 112 insertions / 17 deletions**다. 이 밖의 차이는 이미 커밋된 assignments·GT01 검토 문서·test_diarization.py이며 G-P03 수정으로 세지 않았다. 나머지 app/ai.py·ui/ai_bridge.py·G03 통합 시험의 LF hash는 1차와 동일하다.

`git archive --format=tar 34a5ff0d…`의 출력만 OS TEMP에 풀었다. 이하 **R2 = `C:/Users/gangd/AppData/Local/Temp/recoryn-g03r2-s82xjueg`**, 판정 사본은 `R2/tree`다. 수정된 파일의 LF SHA256은 다음과 같다.

| 대상 파일 | SHA256(LF) |
| --- | --- |
| src/recoryn/content/store.py | `50c770f6f279455518e0d95fc42e7542c430146727ac85f1618b3234e29c14de` |
| tests/unit/test_content.py | `5b7e52bf5ee438e5b107c64299ead53053e24a466be6e519f1d22dad558a4293` |
| docs/testing/g03-selection-version-cases.md | `d3f52f683f376cadc9d9dc9aec3a7db425bed586bd37fed0f322195891010df4` |

실행은 기존 `.venv` Python, `-B`, bytecode 억제, `QT_QPA_PLATFORM=offscreen`, HF/transformers offline·telemetry 차단, `-p no:cacheprovider`, 실행별 OS TEMP basetemp를 사용했다. 사본의 `recoryn.content.store.__file__`을 직접 확인했다. 작업 트리의 G-P02와 섞어 판정하지 않았고 제품·시험·공용 문서·Git을 수정하지 않았다.

### 항목별 재판정

| 항목 / 판정 | 직접 확인한 근거·결과 |
| --- | --- |
| **G03-01 / RECHECKED(수정)** | `content/store.py:271`이 필수 키에 `text_value(settings_key, maximum=256, empty=False)`를 직접 호출한다. validator는 `content/models.py:10`에서 None/비문자열·빈/공백·길이 초과·NUL·잘못된 인코딩을 검사한다. 기존 `_settings_key`의 선택 인자 None 허용은 그대로다. 원 `test_required_settings_key_none_has_a_domain_validation_error`를 **내용 변경 없이** 새 tree에서 실행해 PASS. `R2/none-key.json`의 실제 예외는 `ValidationError: INVALID_CONTENT_TEXT`, 행은 `[["known",1]]`로 불변이다. 작성자 신규 `test_g03_required_settings_key_is_validated_before_sql[G03-KR-none/empty/257]` 3행도 PASS하고 정상 키·횟수·selection_state 불변을 검사한다 |
| **G03-02 / RECHECKED(C00 수용)** | 경우의 수 문서 `:310` 이후는 K1·K2가 모두 창에서 끝나면 active=K2·최근 키=K1인 변형을 정확히 명시한다. API로 후보를 고를 수 있지만 **현재 UI에는 요약 후보 선택 경로가 없음**을 `:320`·`:322`에 남겼다. `content/store.py:788`의 select_summary와 `ui/content.py:244`의 전사만 연결한 선택 동작을 대조했다. `:295`는 이 단위에서 창을 닫지 않는다고 범위를 좁혔다. 원 경합 시험 3행을 그대로 재실행해 모두 PASS: 두 결과 후보/초기 S1 유지, active K2 유지, 수동 S1 재선택 유지. 각 경로의 두 작업 SUCCEEDED·두 revision 보존도 실제 검사했다 |
| **G03-03 / RECHECKED(문서 정정)** | 경우의 수 문서 `:130`은 F=576·구성 불가능 제외0, `:134`는 작성자 E=144로 구분한다. E 밖 432는 저장소 미실행이며 guard 독립성 가정으로 축소했다고 쓴다. `:144`의 검토자 TEMP 432 PASS는 독립 증거로만 인용하고 작성자 시험 수에 더하지 않는다. `:157`은 통합203·신규 단위24(기존21+필수 키3)로 정정했다. 이번에는 그 432를 다시 실행하지 않았으며 1차 실행 증거를 보존한다 |

### 원 반례·경합·LEGACY 선택 실행

1차 `test_independent_review.py`와 `test_original_with_versions.py`를 R2에 그대로 복사했다. 전자의 LF SHA256은 1차와 같은 `8c8af68e4b5eff7ed7532963853aa99cee03fe0f174bff1332c9896bb6b5abc7`다. 두 파일이 `ROOT/tree/src`를 import하므로 새 사본을 보며, 원 None/경합 oracle를 수정하지 않았다.

`R2/recheck-run.json`에 실제 명령과 module origin을 기록했다. 선택 실행은 **13 PASS / 1.28s / exit 0**, error·skip·경고0이다. G03 관련 12개는 원 None1 + 원 경합3 + 같은 ID 재선택2 + 원 ABA2 + 신규 필수 키3 + LEGACY1이다. 원 ABA 파일에 함께 있던 복구/CLI 시험1도 실행돼 PASS했으며 이를 G03 추가 case로 세지 않는다. `R2/recheck.xml` LF SHA256은 **`1dbb40d933c02f8f48252ab8c667d535ba41c4fbcda9cb77e128002bdcaa6696`**다.

경합의 세 JSON은 `R2/merge-both_candidates.json`, `merge-newer_publishes_in_gap.json`, `merge-selection_changed_before_merge.json`이다. 앞의 1차 결과와 같고 C00 수용 설명과 일치한다. UI에서 후보를 고를 수 있다고 해석하지 않는다.

### M10 독립 mutation 재현

정확한 tree의 **pyproject/src/tests/scripts/packaging**을 `R2/M10/baseline/tree`와 `R2/M10/mutant/tree`에 함께 복사하고, 원 독립 반례도 각 부모 폴더에 복사했다. import origin이 각 사본 src인지 별도로 확인했다. mutant는 `request_summary_settings`의 필수 text_value 한 줄을 `_settings_key(settings_key)`로 되돌린 것 하나뿐이다. 정본 사본과 workspace는 바꾸지 않았다.

- 정상본: 신규 필수 키3 + LEGACY1 + 원 None1 = **5 PASS / 0.64s**.
- M10: **2 FAIL / 3 PASS / 0.70s**, error0. `G03-KR-none`은 기대 ValidationError 대신 SQLite IntegrityError가 나서 실패하고, 원 None 반례는 `AssertionError: IntegrityError`로 실패했다. 빈 문자열·257자·LEGACY는 계속 PASS했다.
- **M10 검출 확인**이다. 작성자의 M1~M10 전체 10/10을 이번에 전부 다시 실행한 것은 아니다. M1~M9의 1차 독립 재현 이력은 위에 남겼다.
- `R2/M10/results.json`에 명령·소스/변이 hash·실패 node·origin·시간을 기록했다. LF SHA256은 **`9a7e070bbf299de6ba164bdb54216fe122af2606e994cf059a785b9a30b0e8d3`**다.

변경된 Python 두 파일은 사본에서 `ruff check --no-cache`와 `ruff format --check --no-cache`를 직접 실행해 PASS했다. 작성자의 943 PASS·mypy83파일·전체 format152파일은 작성자 결과이며, 이 재확인의 직접 실행 숫자로 옮기지 않는다.

### 재확인 tree 전체 오프라인 회귀와 최종 인계

```powershell
# cwd: R2/tree, R2는 위 절대 경로의 축약 표기
# QT_QPA_PLATFORM=offscreen, PYTHONDONTWRITEBYTECODE=1,
# PYTHONPATH=R2/tree/src, HF_HUB_OFFLINE=1,
# TRANSFORMERS_OFFLINE=1, HF_HUB_DISABLE_TELEMETRY=1
D:/project/Recoryn/.venv/Scripts/python.exe -B -m pytest -q -p no:cacheprovider --basetemp R2/pytest-full --junitxml R2/full.xml --tb=short --durations=8
```

직접 결과 **8025 passed in 216.15s / exit 0**, 실패·error·skip·xfail0이다. JUnit을 별도로 집계한 `R2/full-audit.json`에서 **G03 통합203·신규 단위24·content 단위 전체103**을 확인했다. `tests/ui` **49 PASS**, 그중 live UI **10 PASS**·GPU runtime UI **4 PASS**다. 이 결과는 **G-P02 변경을 포함하지 않은** 재확인 tree의 결과이며 작업 트리의 G-P02 관련 11건 복구를 완료했다는 뜻이 아니다.

`R2/full.xml` LF SHA256은 **`e8fe94e29ec861ed61193d0cfafbaf7388d54e8bb47451db9a5a6524d8ebd82e`**다. 1차 8021과의 증가4는 필수 키3행 및 중간 GT-P01의 신규 느린 시작 시험1행과 일치한다. 검사 종료 시 대상 6파일의 LF hash가 추출 직후 `inputs.json`과 모두 같았다.

**최종: G03-01 RECHECKED / G03-02 RECHECKED(C00 수용) / G03-03 RECHECKED. OPEN 0, S0·S1 0.** 미해결 경합 창과 요약 후보 UI는 C00 수용/후속 사항으로 남으며 제거됐다고 보고하지 않는다. 실제 장치·모델·네트워크·설치·vault 쓰기·다른 세션 제어는 하지 않았다. 원 검토 문서의 앞부분은 그대로 보존했다.

G-P03 커밋 및 **C00의 G-P02 2단계 시작 신호를 기다린다**. 그전에는 ai_bridge.py를 수정하지 않는다. G-P06 구현도 G-P03/G-P02 커밋 뒤 별도 시작 신호 전까지 대기한다.
