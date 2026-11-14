# Q23 시험 설계 독립 검토

상태: **REVIEW_READY / Q23-COV-01·Q23-DAG-02 OPEN, 작성자 재작업 대기**. 2026-11-15 검토 Q21(w5:p2), 작성 Q23(w5:p4), 통합 Q00(w5:p1), push Q-P03. 제품 결함 판정이나 제품 전체 승인이 아니다. Q21의 과거 JobStore 작성 이력과 구분해 Q23의 새 시험 설계·분모·oracle·증거만 검토한다. Q21 자신의 새 시험 최종 판정은 Q23의 별도 역리뷰에 맡긴다.

## 교육·범위·검토 snapshot

AGENTS, onboarding 필수 순서, workflow, 2026-11-15 Q 배정표, quality-system, case-space, push-units, 제품 계약과 기존 구현 결과·관련 게시 리뷰를 읽고 현재 status/담당 파일을 확인했다. 추가 쓰기 허용은 이 문서뿐이며 Q23 시험·문서와 모든 runtime/config/기존 시험은 읽기 전용이다. 기존 변경을 덮어쓰거나 Git 조작·추가 위임을 하지 않았다. 원본 불변, AI/녹음 분리, 기본 무전송, Credential Manager 계약을 유지하고 synthetic PCM/임시 SQLite/소유 thread·subprocess만 사용했다.

| 검토한 파일 | SHA256 / 역할 |
| --- | --- |
| tests/property/test_publication_case_space.py | 89507f4f4188d94913cdcbde614cb924c9a9c69b68cae4ee6da50b63d506bde1; 최초 검토 snapshot |
| docs/testing/q23-publication-cases.md | 최초 105 DAG/210행·4935 제외·217 PASS 제출 문서; 아래 발견 후 작성자 수정 대상 |
| src/recoryn/content/store.py | d2c4f3d7fa99ccc7c132ea61a664ca598377997d864d9ee390642c1918835f5c; 읽기 전용 대조 |
| src/recoryn/jobs/__init__.py | 7949f880b00b894aaa6896c117563f3a6473bf851521f143710848033446af89; 읽기 전용 대조 |

이 snapshot은 제품 기준 30703fe와 대조했다. 아직 생성되지 않은 Q-P03 commit의 검증으로 workspace 실행을 표현하지 않는다. 원격 CI/정확한 tree 검증과 commit/push는 root 책임이다.

## Q23-COV-01 — OPEN: mutant 사본이 부모 coverage 데이터에 포함됨

대상은 `test_named_cas_mutant_is_killed_by_target_assertion`의 subprocess 환경 복제다. source-path guard는 TEMP runtime import를 확인하지만 부모 계측의 격리를 보장하지 않는다. 현재 pyproject의 `[tool.coverage.run] patch=["subprocess"]`, 설치 coverage 7.17.3과 pytest-cov 환경에서 다음을 독립 실행했다.

```powershell
$env:COVERAGE_FILE = '<고유 TEMP>/.coverage'
.venv/Scripts/python.exe -m pytest tests/property/test_publication_case_space.py::test_named_cas_mutant_is_killed_by_target_assertion --cov=recoryn --cov-report= -q -s -p no:cacheprovider --basetemp '<고유 TEMP>/pytest' -W error::ResourceWarning --tb=short
```

실제 실행은 별도 Python driver의 child 환경에만 COVERAGE_FILE/PYTHONDONTWRITEBYTECODE를 설정했다. workspace나 공유 세션 환경을 변경하지 않았다. parent exit0/1 PASS였으나 부모 `.coverage`의 `CoverageData.measured_files()`에 **TEMP isolated/src/recoryn 67파일**이 들어갔다. 사본 `content/store.py`에는 **417 실행 line / 625 arc**가 기록됐다. 67파일 모두 실제 실행됐다는 뜻은 아니며 미실행 파일도 포함된 계측 파일 수다. 정상 사본과 변이 사본이 같은 TEMP 경로를 사용하므로 이 결과를 정본 제품 coverage로 사용할 수 없다. 전체 회귀의 최종 백분율 변화량까지 측정한 결과는 아니다.

원 증거: `C:/Users/gangd/AppData/Local/Temp/recoryn-q21-q23-cov-f6gh5h12/`의 `evidence.json`, `run.log`, `.coverage`. evidence에는 정확한 argv, exit, 각 foreign path의 line/arc 수와 원본 전후 hash가 있다. 원본 store/test/index hash는 전후 같았다. 인덱스는 `f09828d68b4ab586204c5f8e4f1419b73b8395abfdc401f3e85ab346d64c9dfe`였다. root에 관측 구간 시작·종료를 알렸으며 이 검토자는 stage하지 않았다.

수정 요청은 Q23에 반환했다: child의 COVERAGE*/COV_CORE* 등 계측 환경을 격리하고 필요시 `-I`와 명시 source-path 설정을 사용한다. TEMP import guard와 정상 PASS/원 목표 assertion FAIL은 유지해야 한다. 단순히 mutant를 skip하거나 부모 coverage 대상에서 정본 파일을 빼는 해결은 수락하지 않는다. 재확인은 같은 `--cov=recoryn` 조건에서 부모 데이터의 사본 파일0 및 목표 mutant 검출을 함께 확인한다. root는 작성자 두 파일 안의 수정을 배정했다.

## Q23-DAG-02 — OPEN: 4935 제외 중 실행 가능한 순서가 있음

선언한 chain `ER→EW→SR→SW`, `PR→PW`, 독립 C의 linear extension은 7!/(4!·2!)=105가 맞다. 순열 필터와 위치 조합의 서로 다른 생성 방식 및 full/partial 교차210도 일치한다. 문제는 `EW→SR`을 fixture 구성 불가능성으로 해석한 점이다. SR은 공개 `active_transcript` 읽기이며 편집본 ID를 아직 필요로 하지 않는다. 편집본 ID는 SW 시점에만 있어야 한다.

원 시험 파일을 바꾸지 않고 TEMP root를 전달해 다음 두 추가 행을 실행했다.

```text
partial:ER-SR-EW-SW-PR-PW-C -> PASS
full:ER-SR-EW-SW-PR-PW-C    -> PASS
```

동일 `test_publication_dag` 함수가 초기+각 prefix oracle와 실제 SQLite/원본 hash를 실행하고 완료 ID를 기록했다. SR은 base를 읽고 EW가 edit를 만든 뒤 SW는 이전 base expectation 때문에 정상적으로 거부된다. 따라서 이 순서는 제품 거부 결과를 포함한 실행 가능한 client-history이며 4935 전체를 구성 불가로 설명할 수 없다. 이 반례는 제품 결함이 아닌 시험 제약·분모 결함이다.

최소 의존성은 ER→EW, EW→SW, SR→SW, PR→PW다. 편집/선택 네 사건 안의 가능한 순서는 `ER EW SR SW`, `ER SR EW SW`, `SR ER EW SW`의3개다. 별도 산식은 **3×C(7,4)×C(3,2)=315 DAG**, full/partial 교차 **630행**이다. 순열 필터로도315를 대조했으며 기존105 밖에210 DAG가 있었다. 이 검토에서 추가210 DAG 전부를 제품 실행한 것은 아니며 원 반례2행을 직접 실행했다.

원 증거: `C:/Users/gangd/AppData/Local/Temp/recoryn-q21-q23-dag-zv27wywy/evidence.json`에 산식/실제 집합 수/두 완료 ID를 보존했다. 재현은 읽기 전용 원 모듈을 importlib로 로드하고, `test_publication_dag(full, ("ER","SR","EW","SW","PR","PW","C"), <고유 TEMP>, [])`를 모드별로 호출하는 방식이다. pytest 최상위 PASS 수에 이 직접 호출2개를 합산하지 않았다.

2026-11-15 Q00 결정: 범위를105로 축소해 수락하지 않고 최소 의존 DAG315×2=630행 확장을 작성자에게 배정했다. 새 denominator/실행 census/문서와 기존 원 반례 통과를 독립 재확인할 때까지 OPEN이다. target을 검토자가 직접 수정하지 않았다.

## 확인된 oracle·실행 census·실제 SQL 경합

- 모델은 `base/edit/machine` label과 독립 captured state를 사용한다. 제품 전이표·선택 함수·SQL 결과를 기대값으로 복사하지 않는다. 실제 read를 명령 인자로 사용하는 한편 매 read prefix도 모델 active와 대조하므로 잘못된 실제 read가 다음 기대값에 숨지 않는다.
- 초기와7 prefix마다 active/선택 집합, revision 본문·parent·edited provenance, Job/Attempt 상태·fence/result, content event 수·성공 event 수·checkpoint를 관측한다. 봉인 PCM/journal/descriptor/manifest와 base 본문 불변도 검사한다. complete/partial, 취소 선행 게시 거부, stale selection 거부가 선언 공간 안에 남아 있다.
- 하위 ContentStore의 명시 expected CAS와 AIService 자동 게시의 상위 edited 보존 정책을 구분한 것은 제품 계약과 맞는다. 단일 source·단일 attempt·7사건 한 회씩이라는 bound 밖을 전수 증명하지 않는다. state_version/전체 감사 payload/여러 Job/summary 이중 포인터의 별도 검증을 이 oracle가 대신한다고 주장하지 않는다.
- 실제 완료 ID는 성공한 DAG/SQL 실행 뒤 append한다. census가 expected IDs의 누락·예상 밖·중복을 확인하고 별도 분모 audit가 generator를 검산한다. 전체 파일의 순차 실행이 전제이며 부분 node 선택·분산 실행에서 census 결과를 전체 coverage로 해석할 수 없다.
- 실제 SQL4행은 first writer publish/cancel × full/partial이다. leading transaction의 content/event INSERT trace에서 보유하고 별도 SQLite reader가 이전 Job/Attempt/content/selection commit만 보는지 확인한다. rival의 BEGIN IMMEDIATE trace와 call Event 뒤에 release하므로 단순 sleep 경쟁이 아니다. editor는 호출 직전 Event와 future 미완료를 관측하며 SQLite lock에 들어갔다는 증거로 확대하지 않는다. leading 이후 editor/cancel의 상대 순서를 전부 강제하지 않지만 이 고정 fixture에서는 별개 결과 또는 성공 terminal no-op이라 최종 관측이 commute한다.
- 기존 cancel/completion·edit CAS·partial·select·다른 세션·event failure rollback node가 실제 존재함을 확인했다. 새 시험이 이 기존 오류 주입을 재실행한 것으로 기록하지 않았다.

검토자의 실제 재실행:

| 실행 | 결과 |
| --- | --- |
| Q23 파일, `-k 'not named_cas_mutant'` | **216 PASS / 1 deselected / 35.44s**; DAG210, SQL4, missing0/unexpected0/duplicate0 |
| Q23 원 named mutant 단일 node, coverage 없이 | **1 PASS / 2.00s**; normal child0 / mutant child1 / 원 Q23_ACTIVE_CAS assertion |
| 같은 named mutant 단일 node, `--cov=recoryn` | **1 PASS / 2.70s**이나 COV-01 혼입 발견; clean coverage 수락 아님 |

모든 pytest 실행은 `.venv/Scripts/python.exe`, `-p no:cacheprovider`, 고유 TEMP basetemp, `-W error::ResourceWarning`을 사용했다. 비mutation basetemp는 `C:/Users/gangd/AppData/Local/Temp/recoryn-q21-review-q23-f4ebb4ecf5e54ee4b39f157b69840dbb`, 원 mutation은 `recoryn-q21-q23-mutant-5a55a092a10c4b2b8e8a5539174f4d2d`다. 분할216+1의 node 범위는 제출217과 대응하나 새로운 단일 전체 실행217이라고 표현하지 않는다.

`PUB_CAS_DROP_EXPECTED`가 TEMP `_create_transcript`의 expected 비교만 제거함을 확인했다. 정상 source hash는 위 표, mutant hash는 `b9cf32f6662c30533f11a6de5c7de6eba0c18c60445b6790272eded47e7c1a10`와 일치했다. 같은 목표 `test_publication_dag[full:PR-ER-EW-SR-SW-PW-C]`가 정상 PASS·변이 Q23_ACTIVE_CAS AssertionError/1 failed를 요구하며 import/수집 오류는 kill로 세지 않는다. 이 mutant의 의미 검출은 확인했지만 계측격리는 COV-01로 별도 OPEN이다.

## 인계와 제한

Q21 자신은 전용 test/doc를 먼저 동결해 root에 REVIEW_READY로 보고했다. Q23 검토의 두 발견·반례·재작업 요청도 기존 Q23/root pane에 전달했다. root는 두 건을 작성자에게 반환했으며 새 hash FIXED 제출 뒤 재확인을 요청할 예정이다. 이 문서는 원 snapshot과 원 반례를 보존하고 후단에 재확인을 덧붙인다.

실제 장치/음성/weights/계정/네트워크/실서비스/전원 장애/모든 OS scheduler는 실행하지 않았다. 제품 수정이나 runtime 승인, 자기 작성 JobStore의 독립 최종 승인, Q-P03 commit/CI 승인으로 해석하지 않는다. 현재 **REVIEW_READY / 두 발견 OPEN**이다.

## 2026-11-15 FIXED snapshot 독립 재확인 — 후단 현재 판정

위 OPEN/원 반례/최초 실행은 당시 기록으로 보존한다. 이 후단의 현재 판정은 **REVIEW_READY — Q23-COV-01·Q23-DAG-02 RECHECKED / CLOSED 후보**다. 두 시험 설계 발견의 원 oracle를 유지한 재확인이며 최종 종결·정확한 Q-P03 tree 수락은 Q00 책임이다. Q21 자기 작성분이나 제품 전체 승인으로 확대하지 않는다.

Q00이 명시한 새 시험 hash에서 읽기 전용 재확인을 시작했고, 작성자의 최종 FIXED 문서 갱신 뒤 다음 바이트를 다시 대조했다.

| 최종 읽기 전용 대상 | SHA256 |
| --- | --- |
| tests/property/test_publication_case_space.py | 5191e14a0b772d71e82584fda7780c6fd8331ca1c55c67865efd6a2e88e4d77a |
| docs/testing/q23-publication-cases.md | efc68f92aea2e3c84408f3f33250b39f1520b7bdea53b4f5c27853946e49ec65 |

원 검토 시험 사본89507f…와 새 시험의 실제 diff를 대조했다. 독립 Oracle/상태·원본 assertion과 mutant의 Q23_ACTIVE_CAS 목표 assertion은 완화되지 않았다. 변경은 최소 의존 DAG와 독립 분모/생성 검산, 실제 prefix·early read·stale 거부 census, child 계측 격리에 집중한다. 최초105/210 snapshot을 현재 결과로 재사용하지 않았다.

### COV-01 재확인

원 재현과 같은 기존 pyproject `patch=["subprocess"]` 및 `--cov=recoryn --cov-report=`로 named mutant 단일 node를 독립 실행했다. 고유 TEMP 데이터 파일을 child driver 환경에만 지정했고 부모 coverage 측정 대상이나 공용 config는 수정하지 않았다.

결과는 **1 PASS / 1.58s**다. normal child exit0, mutant child exit1이며 원 목표 `Q23_ACTIVE_CAS` AssertionError/동일 node 1 failed의 검출을 유지했다. 부모 `.coverage`를 직접 읽은 실제 **67개 measured path 전부가 정본 `D:/project/Recoryn/src` 아래**였고 foreign **0**, isolated **0**이었다. 경로 목록 전체를 검사했으며 단순히 foreign 문자열이 출력되지 않은 것을 근거로 삼지 않았다. measured path 수를 모든 파일 실행이나 전체 coverage 백분율로 표현하지 않는다.

새 child는 대소문자를 정규화해 COVERAGE*/COV_CORE*/PYTEST*를 제거하고 plugin autoload를 막으며, `-I` 후 TEMP src를 명시 삽입한다. 제품 import 전에 `Coverage.current() is None`과 TEMP import guard를 실행한다. 실제 계측 혼입0과 목표 검출의 동시 관측으로 이 snapshot의 COV-01을 **RECHECKED / CLOSED 후보**로 판정한다.

독립 증거: `C:/Users/gangd/AppData/Local/Temp/recoryn-q21-q23-cov-recheck-ocpj657h/`의 `evidence.json`, `run.log`, `.coverage`. evidence에 실제 measured paths 전체·argv·전후 hash를 보존했다. source/store hash d2c4f3d7…·시험5191e14a…·index f09828d6…는 짧은 구간 전후 같았다. root에 실행 전 시작과 실행 직후 종료를 알렸다. **이 구간은 종료됐고 이후 회귀는 index를 관측하지 않았다. root stage를 더 보류할 요청은 없다.**

### DAG-02 최소 의존·제외·원 반례 재확인

제품 생성기를 호출해 분모를 얻지 않고 7! 순열에서 첫 의존 위반의 서로 겹치지 않는 분할을 별도 계산했다.

| 첫 위반(앞선 조건은 만족) | 별도 실행 검산 수 |
| --- | --- |
| ER이 EW 뒤 | 2520 |
| EW가 SW 뒤 | 1680 |
| SR이 SW 뒤 | 210 |
| PR이 PW 뒤 | 315 |
| 위반 없음 | 315 |

제외 **4725** + feasible **315** =5040이며, 독립 산식 **3×C(7,4)×C(3,2)=315**, full/partial **630행**과 맞았다. 별도 feasible 집합과 실제 histories 집합이 정확히 같고 실제 CASES도630개 유일했다. 제품 거부 행을 제외하지 않는 최소 데이터 의존으로 바뀌었으며 EW→SR 과잉 제약과4935 구성 불가 주장은 최종 문서에서 철회됐다.

원 `ER-SR-EW-SW-PR-PW-C`를 full/partial 각각 임시 fixture에서 직접 실행했다. 두 경우 모두 초기+7prefix 8회 관측, 완료 ID, SR-before-EW 기록, **실제 stale SW 거부**를 확인했다. fixture·oracle·target을 수정하지 않았으며 이 직접 호출2개를 최상위 pytest PASS에 더하지 않았다. 증거는 `C:/Users/gangd/AppData/Local/Temp/recoryn-q21-q23-dag-recheck-gt2wzvf0/evidence.json`이다.

이후 같은 시험 hash에서 전체 비mutation 회귀를 독립 실행해 **636 PASS / 1 deselected / 104.28s**를 확인했다. 정상 SQLite와 synthetic 원본을 사용했으며 모든 pytest는 `.venv/Scripts/python.exe`, cache-off, 고유 TEMP basetemp, ResourceWarning-error였다.

```text
.venv/Scripts/python.exe -m pytest tests/property/test_publication_case_space.py -k "not named_cas_mutant" -q -s -p no:cacheprovider --basetemp <독립 고유 TEMP>/pytest -W error::ResourceWarning --tb=short
```

실제 성공 후 census는 DAG **630**, 실제 SQL **4**, missing/unexpected/duplicate 각각 **0**, 초기+prefix 고유 관측 **5040**, SR-before-EW **420**, 실제 stale SW 거부 **416**이었다. 원 반례 두 ID도 거부 집합에 포함됐다. 636은 DAG630+분모 audit1+SQL4+census1이며, 별도 coverage 포함 mutant1과 합쳐 단일 실행637이라고 기록하지 않는다. 시험 hash는 전체 실행 전후5191e14a…로 같았다. Ruff check/format도 독립 PASS다.

전체 회귀 독립 증거: `C:/Users/gangd/AppData/Local/Temp/recoryn-q21-q23-full-recheck-m9oyroto/{evidence.json,run.log}`. 최종 문서의 작성자 실행636/106.48s와 독립 실행636/104.28s를 구분한다. 최종 문서 hash는 실행 후에도 위 efc68f92…였다. 이 결과로 DAG-02를 **RECHECKED / CLOSED 후보**로 판정한다.

새 제품 결함이나 추가 열린 시험 설계 발견은 이번 재확인에서 없었다. 기존 실제 SQL barrier 관측의 범위, 단일 Job/Attempt·L=7 밖 이력 및 실제 장치/서비스 미검증은 앞선 제한 그대로다. 이번 추가 쓰기는 이 문서 후단뿐이며 Q23 target·제품·config·Git을 수정하지 않았다. **현재 REVIEW_READY, 두 발견 독립 RECHECKED이며 root 최종 종결·Q-P03 tree/CI 수락 대기**다.
