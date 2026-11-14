# Q-P03 게시·보안 시험 통합 증거

2026-11-15. 통합 Q00/root. **VERIFIED — 독립 재검토·정확한 통합 tree 전체7111 PASS·coverage/정적 검사 PASS, 선행 Q-P02 원격 CI PASS.** Q23/Q24의 새 시험·case 문서, 다른 세션의 독립 리뷰 및 이 단위 결과를 포함한다. 생산 코드·기존 시험·의존성·CI를 변경하는 단위가 아니다. 이 단위 자체의 commit/push/원격 CI는 별도 확인한다.

## 경계·선행·파일 manifest

Q-P01 정책→Q-P02 상태/오디오→Q-P03 게시/보안의 순서로 통합한다. 기준 부모 Q-P02는 `ee15a81b604c3d5084329b56ced232b96407d3b3`이며 root가 HTTPS normal push 성공 및 origin/main 일치를 직접 확인했다. [Q-P02 원격 CI](https://github.com/gangdonggilstudy/Recoryn/actions/runs/43611961848)는 이 head에서 **completed/success**다. core Python3.11/3.13 및 optional-runtime 세 job 모두 success임을 GitHub API로 직접 읽었다. 고립된 로컬 검증은 CI 실행 중 병행했으나 Q-P03 공개는 이 선행 성공 확인 뒤 진행한다. Q-P01 `29e18b28d137f9478a139ec28ef086bb6d36e0d3`의 [CI](https://github.com/gangdonggilstudy/Recoryn/actions/runs/43608939380)도 root 확인 success다. Q23 작성/Q21 독립 검토, Q24 작성/Q22 독립 검토, root 통합이다.

- tests/property/test_publication_case_space.py
- tests/property/test_security_case_space.py
- docs/testing/q23-publication-cases.md
- docs/testing/q24-security-cases.md
- docs/reviews/q23-test-design.md
- docs/reviews/q24-test-design.md
- docs/testing/q-policy-results.md

이 7파일만 명시 stage한다. Q-P02를 선행으로 통합하고 이 정확한 통합 tree를 TEMP로 추출해 전체 오프라인 회귀/coverage·정적 검사를 실행한다. 검증한 실행 파일 hash와 최종 index를 대조한다. rollback은 이 시험·문서 commit의 revert이며 schema/runtime migration은 없다. 기존 개발 artifact의 입력 source tree는 변경하지 않지만 이 시험 단위가 새 공식 릴리스를 승인하는 것은 아니다.

## 분모·oracle·재작업

| 영역 | 유한 가족과 독립 분모 | 별도 관측 |
| --- | --- | --- |
| Q23 게시 | 최소 의존 ER→EW→SW, SR→SW, PR→PW. edit/selection 내부 3순서 × C(7,4) × C(3,2)=315 DAG; full/partial 2모드로 630행 | 초기+7prefix=5040 불변식 checkpoint; 실제 SQLite 경합4행 별도 |
| Q24 권한·예산 | admission2⁷=128 + handoff2×2⁴=32 + expiry4×3=12 + exposure4×3=12 + integer2×7=14 =198행 | 유한 actual IDs와 독립 JUnit audit; 비용 분할 property30 passing examples는 비전수 |

Q23 초기 105순서/210행은 EW→SR을 불가능 제약으로 잘못 설명했다. Q21의 독립 반례가 SR-before-EW도 실행 가능하고 stale selection은 제품이 거부함을 확인했다. root는 단일 UI 부분공간으로 축소 수용하지 않고 최소 데이터 의존으로 확장하도록 반환했다(Q23-DAG-02). 또한 mutation child의 coverage 환경 상속으로 TEMP 사본 67파일이 부모 coverage에 섞이는 Q23-COV-01을 발견했다. 두 원증거와 판정은 [독립 리뷰](../reviews/q23-test-design.md)에 보존했다. 수정 후 Q21의 독립 636 PASS/104.28s와 원 반례 두 모드의 stale SW 거부, 별도 coverage 포함 mutant1 PASS/1.58s·foreign/isolated 경로0을 확인했다. root는 대상 hash 일치와 원 assertion 유지의 독립 근거를 대조해 **두 발견을 CLOSED**로 종결한다. 이는 시험 설계·계측 발견의 종결이며 제품 전체 승인과 구분한다. 정상 mutant harness의 통과를 깨끗한 coverage 통과로 오해하지 않는다.

Q23의 CAS 비교 제거, Q24의 고정 grant binding 검사 제거 및 inclusive budget >→>= mutant는 각각 TEMP source 사본의 정상 PASS→목표 assertion FAIL을 요구한다. 실제 workspace·Git index는 변경하지 않는다. 일부 mutant 검출을 전체 프로젝트 mutation coverage로 주장하지 않는다. Q24의 복합 오류는 계약상 허용한 안전 오류 집합으로 확인하며 구현의 우연한 총순서를 oracle로 복사하지 않는다. 실제 open/write, known/UNKNOWN 및 exposure를 별도로 assert한다.

세부 입력·제약·거부행·독립 oracle·기존 node 대응·실험 hash/명령은 [Q23 설계](q23-publication-cases.md), [Q24 설계](q24-security-cases.md), [Q23 리뷰](../reviews/q23-test-design.md), [Q24 리뷰](../reviews/q24-test-design.md)에 기록한다. finite count와 pytest node, Hypothesis examples, SQL 경합 및 prefix 관측은 서로 다른 분모다.

## 동결 입력과 독립 수락

| 파일 | raw SHA-256 |
| --- | --- |
| test_publication_case_space.py | 5191e14a0b772d71e82584fda7780c6fd8331ca1c55c67865efd6a2e88e4d77a |
| test_security_case_space.py | 7f99e7f85aeb7ab47db722130e023eacf65a374bdd25597c1d6888dbff0800d4 |
| q23-publication-cases.md | efc68f92aea2e3c84408f3f33250b39f1520b7bdea53b4f5c27853946e49ec65 |
| q24-security-cases.md | 1bd4e606fb9dd733b37d8ea727cb44117651631a9c56f36f2328148e811926d7 |
| q23-test-design.md | 3c673c3d000c66630b1c41b231fb1ec023b7c69ac5c797302a0b10e915d6a3c9 |
| q24-test-design.md | 9bd07d69d2c6d8f9ac1c585f9cfff3b28c761eb37210b72161c59b7be89d4595 |

Q24는 Q22의 독립 선택 회귀350 PASS와 198행 JUnit ID audit 누락/중복/추가0, 격리 정상2 PASS·두 목표 mutant 각각 assertion1 FAIL을 확인했다. 계약에 없는 진단 총순서를 강제하지 않으면서 실제 handoff/known/UNKNOWN/exposure를 검사함을 대조했다. root는 이 hash판의 두 독립 리뷰를 수락하며 선언 범위의 추가 OPEN S0/S1/S2는 0건이다. Q23 finite630+SQL4와 Q24 finite198은 총832행이고, 최상위 새 pytest는 Q23의637 + Q24의200 =837개다. 선행 Q-P02의 4823행과 합친 유한 가족은5655행이며 auxiliary census/property/mutation node와 구분한다.

## 통합 검증·공개 상태

검사 stage tree `610e5547f3108becf5fbbf3a68a72672cedce0cb`를 `git -c core.autocrlf=false archive`로 `C:/Users/gangd/AppData/Local/Temp/recoryn-q-p03-tree-habqtnf7/tree`에 추출했다. manifest7파일의 raw bytes가 인덱스 blob과 같음을 확인했다. source/config/cwd/PYTHONPATH/MYPYPATH는 이 snapshot으로 고정했고 실제 recoryn import origin도 snapshot/src였다. dirty workspace의 파일을 추가 import하거나 후행 파일로 결과를 대신하지 않았다.

Windows/CPython3.13.1에서 **전체7111 PASS / 221.49초**, JUnit error/failure/skip 0이었다. 기존1444 + Q21/Q22 신규4830 + Q23/Q24 신규837 =7111이며 중복 회귀나 mutant child 결과를 가산하지 않는다. `--runxfail`·고유 basetemp·cache-off·ResourceWarning-error로 실행했다. Ruff check/format **131파일**, strict mypy **79파일**도 PASS다.

| 예산 | line 실제/최소 | branch 실제/최소 | 판정 |
| --- | --- | --- | --- |
| domain | 100.00% /95% | 100.00% /90% | PASS |
| capture | 99.85% /95% | 98.57% /90% | PASS |
| jobs | 98.89% /95% | 97.47% /90% | PASS |
| storage | 97.92% /95% | 94.72% /90% | PASS |
| security | 98.97% /95% | 96.12% /90% | PASS |
| content | 99.56% /95% | 98.68% /90% | PASS |
| 전체 | 8071/8644 =93.37% /85% | 2419/2784 =86.89% /80% | PASS |

coverage JSON의 67개 파일 경로가 **모두 이 snapshot의 src/recoryn 아래**임을 assertion으로 확인했다. 외부 workspace·TEMP mutant source 혼입은 0이다. line/branch 수치는 기존 개발 snapshot과 같으며 이번 보강의 증거는 선언한 조합·순서·경계의 실행 ID 대조와 핵심 mutant 검출이다. 이미 실행된 줄의 다른 입력 조합을 추가한 사실을 line coverage 증가로 표현하지 않는다.

```text
D:/project/Recoryn/.venv/Scripts/python.exe -m pytest -c <snapshot>/pyproject.toml -o pythonpath=<snapshot>/src -q -p no:cacheprovider --runxfail --basetemp <evidence-root>/pytest-temp -W error::ResourceWarning --junitxml=<evidence-root>/pytest.xml --cov=recoryn --cov-branch --cov-report=term --cov-report=json:<evidence-root>/coverage.json --cov-fail-under=85
D:/project/Recoryn/.venv/Scripts/python.exe scripts/check_coverage.py <evidence-root>/coverage.json
```

`<evidence-root>`는 위 TEMP의 tree 상위다. report.json에 base/tree/manifest·검증 파일 hash·정확한 argv/exit·JUnit·coverage totals를, pytest.xml/pytest.log/coverage.json 및 각 정적 검사 log에 실제 출력을 보존한다. 검사 후 이 결과문서만 갱신하며 다른6파일·실행 source/test의 최종 index blob이 검사 tree와 같음을 재확인한다. Markdown 링크/공백 오류·manifest·예상 부모/remote를 확인한 뒤 normal commit/push한다. 최종 자기 commit SHA/CI의 정본은 Git ref와 실제 해당 head의 run이며 이를 본문에 넣기 위한 반복 commit은 만들지 않는다.

선택한 유한 대표 집합과 제한 길이 밖, 모든 scheduler·장치·실음성·실모델·weights·실서비스·장시간·전원 장애·G3/G4는 미검증이다. 기본 무전송·원본 분리·Credential Manager 계약은 기존 제품 경계를 유지한다.
