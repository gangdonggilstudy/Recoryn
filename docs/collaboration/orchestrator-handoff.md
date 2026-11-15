# Recoryn 오케스트레이터 인계서 H01

2026-11-15. 사용자 명시 지시: Recoryn 영역의 Claude 세션으로 오케스트레이터 업무 전체를 인계하고, **commit에 trailer를 넣지 않는다**. 작성 Q00/Codex(w5:p1), 후임 C00/Claude(w5:t3/w5:p6). 인계 시작 기준은 `main` / `74b1167fb6c5c4957b51891511cdfa2629dc3874`이며 당시 index/working tree는 clean이고 origin/main과 같았다. 실행 환경은 `D:/project/Recoryn`, Windows PowerShell, `.venv/Scripts/python.exe` 3.13.1이다.

## 단일 작성자와 전환 절차

1. 기존 Q00이 H-P01 문서 3파일만 준비한다. C00은 아래 필독 문서와 현재 Git/Herdr 상태를 읽고, Git·제품·공유 파일을 쓰지 않은 상태로 `HANDOFF_REVIEW_READY`와 검토 결과를 보고한다. 이것은 아직 소유권 전환 회신이 아니다.
2. Q00이 리뷰를 반영하고 H-P01의 정확한 3파일만 검증·commit·normal push한다. commit 메시지 trailer가 없음을 확인하고 원격 ref/CI의 실제 상태를 전달한다. C00은 그 상태를 확인한다.
3. Q00이 `TRANSFER_EFFECTIVE`로 쓰기를 종료하고, C00이 `ORCHESTRATOR_ACCEPTED`로 인수한다. 이후 유일한 오케스트레이터/공유 Git 작성자는 C00이다. Q00과 네 worker는 별도 명시 재배정 전 읽기 전용이다. 사용자 세션·서버는 종료하지 않는다.
4. C00은 문서 전용 H-P01의 진행 중 CI도 인수해 최종 결과를 확인하고, 해당 head의 선행 CI가 통과하기 전 다음 의존 단위를 공개하지 않는다. 인계 문서에 자기 commit SHA/CI를 넣기 위한 반복 commit은 만들지 않는다. Git ref·실제 run과 인수 회신이 전환 결과의 정본이다.

인수 후 H-P01 CI가 FAIL 또는 UNVERIFIED이면 C00이 원인·영향을 판정하고 필요한 수정/검증 단위를 정한다. Q00은 임의로 쓰기를 재개하지 않으며 명시 재배정 전 읽기 전용을 유지한다. 이전 Q00 세션의 도구 승인은 C00 harness에 상속되지 않는다. 사용자 작업 범위 동의와 세션별 도구 승인 상태를 구분하고, 필요한 도구 절차를 직접 따른다.

인계 확인은 단순 수신 확인이 아니다. 역할/쓰기 범위·실제 head/dirty 상태·최신 QA·남은 게이트·worker 통제·trailer 금지·Git 단일 작성자를 명시해 회신한다. 이전 대화나 전달받은 숫자를 직접 재실행한 결과처럼 쓰지 않는다.

## 권한·제품 불변식

- C00이 요구사항, 통합 설계·공용 계약, 배정표/파일 소유권, 전문가 검토 배정, 독립 리뷰의 종결, 최종 QA, 정확한 commit/push 단위와 원격 CI, 사용자 보고를 전담한다. 필요하면 기존 네 worker를 명시 배정으로 재개한다. 소유 파일이 겹치면 먼저 조정한다.
- 사용자는 전체 설계 v1.0 구현 진행과 검증 후 오케스트레이터의 원격 push를 승인했다. 승인된 범위의 통상 작업·지시를 불필요한 재확인으로 멈추지 않는다. 실제 음성 캡처/weights 다운로드/실서비스/유료 호출/계정 변경은 기존 승인으로 자동 실행하지 않는다.
- 녹음 저장과 STT/LLM은 독립한다. 마이크/시스템 원본은 분리·불변 보존하며 변환·믹스·편집은 파생이다. 네트워크는 기본 무전송, 제공업체/endpoint/데이터별 동의와 다운로드 동의를 구분한다. 비밀은 Windows Credential Manager 계약을 지키고 DB/설정/로그/export에 넣지 않는다.
- worker는 배정 파일만 쓰며 Git add/commit/push/merge/reset/clean/stash와 다른 변경 취소를 하지 않는다. 추가 위임·pane 생성은 후임의 명시적 배정이 필요하다. 타 workspace/Codaryn·서버 재시작/종료·승인 UI 대리 입력은 하지 않는다.
- **commit 메시지는 trailer 없이 작성한다. `Co-authored-by`, `Signed-off-by`와 Claude/Codex 자동 attribution을 모두 추가하지 않는다.** push 전에 실제 메시지 전체와 `git interpret-trailers --parse`가 비었는지 확인하고, 대소문자 무시 `co-authored-by|signed-off-by|generated with` 자동 생성/서명 문구도 0건인지 검사한다. parse만으로 trailer 블록 밖 attribution을 놓치지 않는다. 과거 이력을 고치는 지시가 아니므로 amend/rebase/force push하지 않는다.

## 필독 순서와 현재 정본

먼저 [AGENTS](../../AGENTS.md)와 [onboarding](onboarding.md)의 전체 순서를 따른다. 특히 아래 문서를 빠뜨리지 않는다.

1. [설계 입력](../design-input-v1.md), [통합 설계](../architecture-v1.md).
2. [협업 규칙](workflow.md), [배정표](assignments.md), [검증 계획](../validation-plan.md), [품질 체계](../quality-system.md).
3. [제품 계약](../implementation/product-contracts.md), [기존 코어 계약](../implementation/p0-contracts.md), [제품 결과](../implementation/product-results.md), [코어 결과](../implementation/p0-results.md).
4. [경우의 수 규칙](../testing/case-space.md), [푸시 단위 규칙](push-units.md), [Q-P02 결과](../testing/q-core-results.md), [Q-P03 결과](../testing/q-policy-results.md).
5. `docs/reviews/`의 product-final-qa 및 BR11/12/13/14/23/24/30/41/42/44 관련 product 리뷰, q-policy-review 및 q21~q24-test-design. 실제 제품/시험 변경 전에는 관련 파일의 현재 diff와 후단 최신 hash/RECHECKED를 대조한다.

일부 문서는 초기 NOT_RUN·OPEN과 과거 hash를 보존한다. 최신 후단의 root 통합 판정/현재 입력에 맞는 근거를 확인해야 한다. 오래된 worker 제출의 NOT_RUN만으로 이미 마친 frozen smoke를 미실행이라고 되돌리거나, 과거 PASS를 새로운 diff 승인으로 확대하지 않는다. 새 세션은 AGENTS/onboarding과 현재 배정을 다시 확인한다.

## 현재 Git·CI 체크포인트

| 단위 | commit | 원격 CI |
| --- | --- | --- |
| 개발 체크포인트 0.2.0.dev2 | 30703feeb8b109dcfbf5093df58c964076e43ae9 | [43606895142](https://github.com/gangdonggilstudy/Recoryn/actions/runs/43606895142) success |
| Q-P01 시험/푸시 정책 | 29e18b28d137f9478a139ec28ef086bb6d36e0d3 | [43608939380](https://github.com/gangdonggilstudy/Recoryn/actions/runs/43608939380) success |
| Q-P02 Job/audio 보강 | ee15a81b604c3d5084329b56ced232b96407d3b3 | [43611961848](https://github.com/gangdonggilstudy/Recoryn/actions/runs/43611961848) success |
| Q-P03 publication/security 보강 | 74b1167fb6c5c4957b51891511cdfa2629dc3874 | [43612561745](https://github.com/gangdonggilstudy/Recoryn/actions/runs/43612561745) success |

Q-P01~03은 순차 공개했고 각 선행 CI PASS 뒤 다음 단위를 push했다. 현재 제품 source subtree는 30703fe와 같으며 Git object는 `21291eb8786d93bba9c8f7307b0cbaf05e7295ee`다. 시험/정책 변경을 제품 구현 변경이나 새 EXE 생성으로 표현하지 않는다. H-P01은 이 위에 문서만 더하는 별도 인계 단위다.

원격 origin은 SSH `git@github.com:gangdonggilstudy/Recoryn.git`다. 기존 SSH 계정의 쓰기 권한은 실패했고, 저장된 HTTPS 자격증명으로 다음 normal push/fetch가 성공했다. remote 설정을 바꾸거나 토큰을 출력/파일 저장하지 않는다.

```powershell
git push https://github.com/gangdonggilstudy/Recoryn.git HEAD:refs/heads/main
git fetch https://github.com/gangdonggilstudy/Recoryn.git main:refs/remotes/origin/main
git ls-remote https://github.com/gangdonggilstudy/Recoryn.git refs/heads/main
```

원격 조회·인증이 실패하면 실패 상태를 보존하고 다른 사람의 계정/SSH 설정을 임의 변경하지 않는다. 커밋 후 GitHub API에서 정확한 head SHA의 실제 workflow/job 결론을 확인한다. `build/q-ci-read.py`는 로컬 ignored 보조 도구이며 코드 검토 후 사용할 수 있다. 저장된 credential은 메모리에서만 사용하고 출력하지 않는다. 이 파일·TEMP는 Git 정본이 아니므로 없어도 공식 API로 재확인할 수 있어야 한다.

## 최신 QA·수학적 공간

- Q-P03의 정확한 stage blob을 `git -c core.autocrlf=false archive`로 추출해 `.venv` interpreter/명시 src/config/cwd로 격리 실행했다. Git의 기본 Windows 줄바꿈 변환을 켠 첫 사본과 구분하며 최종 파일 bytes는 index blob과 맞았다.
- 전체 **7111 PASS / 221.49s**, 실패·error·skip·xfail 0. Ruff/format **131파일**, strict mypy **79파일** PASS. 전체 line **8071/8644=93.37%**, branch **2419/2784=86.89%**, domain/capture/jobs/storage/security/content의 95%/90% 분리 예산 PASS다.
- coverage 67파일이 모두 정본 snapshot/src/recoryn 아래였고 mutant/타 workspace 경로는 0이었다. 이전 line/branch 값과 같으며 입력 조합의 보강을 줄 커버리지 증가로 주장하지 않는다.
- Q21 1432행(H6⁴+D2³+F96+K32), H 유일 prefix1555. Q22 3391행(PCM raw1024 중 동일 singleton API alias16 제외 canonical1008 등12가족). Q23 315DAG×2모드=630행+실제 SQL 경합4행, 초기/7prefix5040. Q24 권한/시각/비용198행. 선언 유한 **5655행**의 실제 ID 누락/중복0. Hypothesis 및 auxiliary node는 별도이며 무한 공간 전수 주장이 아니다.
- 핵심 mutant6개는 정상 PASS→지정 assertion FAIL로 독립 확인했다. import/collection/권한/timeout만의 실패를 kill로 세지 않았다. Q21↔Q23, Q22↔Q24는 서로 작성/리뷰를 분리했다.
- Q23-COV-01(자식 계측 혼입)과 DAG-02(EW→SR 과도한 제약)는 원 반례를 보존하고 수정·독립 RECHECKED 후 root가 CLOSED했다. 최신 hash는 해당 q23 리뷰 후단과 Q-P03 결과가 정본이다.

주요 실제 증거: `%TEMP%/recoryn-q-p02-tree-dd5uhkvo`, `%TEMP%/recoryn-q-p03-tree-habqtnf7`의 report.json/pytest.xml/pytest.log/coverage.json/정적 검사 log. 오래된 TEMP의 ACL/소멸 가능성이 있으므로 직접 읽지 못한 증거를 열람했다고 주장하지 않고 필요 시 새 고유 TEMP에서 재현한다. 미래 변경 뒤에는 이전 숫자를 복사하지 않는다.

시험은 `.venv`, `QT_QPA_PLATFORM=offscreen`, `HF_HUB_OFFLINE=1`, 고유 TEMP basetemp, cache-off, `-W error::ResourceWarning`, 필요 시 `--runxfail`로 실행한다. 필요한 검사만 선택하고 통과 후 변경/발견 없이 반복하지 않는다. finite 분모/feasible 제외/독립 oracle/실제 유일 ID를 먼저 설계하며 중요한 결함은 결정적 경쟁·장애 주입·mutation까지 적용한다. 거부할 입력을 feasible 집합에서 빼지 않는다.

## 네 worker와 파일 소유권

| pane / name | 기존 전문·작성 범위 | Q 작성 / 독립 검토 |
| --- | --- | --- |
| w5:p2 / recoryn-arch | B11 content/jobs, B23 packaging/build/release; BR11/12/41 | Q21 Job 시험 / Q23 게시 시험 리뷰 |
| w5:p3 / recoryn-desktop | B12 capture/audio, B21 app/UI; BR44 | Q22 audio 시험 / Q24 security 시험 리뷰 |
| w5:p4 / recoryn-ml | B22 diarization, BR13/23/42 | Q23 publication 시험 / Q21 Job 시험 리뷰 |
| w5:p5 / recoryn-security | B14 security/privacy, BR14/24/30, R15 aggregate QA | Q24 security 시험 / Q22 audio 시험 및 Q-P01 정책 리뷰 |

전원 완료·동결·읽기 전용 대기다. 예전 소유 범위는 참고 이력이며 재배정 없이 자동 쓰기 재개하지 않는다. 제품 작성과 같은 제품 독립 리뷰를 한 사람이 최종 승인하지 않는다. 재배정 시 AGENTS/onboarding·범위·수락 기준·현 diff·미검증을 교육하고 ONBOARDING_READY를 받는다. 기존 worker는 추가 위임·Git·승인 UI 대리 입력 금지를 이해하고 있다.

Herdr는 `HERDR_ENV=1` 확인→`herdr --skill`/`--help`/관련 그룹→현재 목록 재조회→get/read→prompt 순서다. 현재 서버의 w5만 제어한다. pane ID는 영구 ID가 아니므로 재접속/이동 뒤 재조회한다. timeout/stalled는 미전송 증거가 아니며 읽고 중복 지시 여부를 결정한다. worker 탭 w5:t2와 기존 세션을 유지한다. Claude 후임은 w5:t3/w5:p6에서 kind/cwd를 직접 조회해 구별했다. 세션 UUID는 공개 인계 문서에 보관하지 않는다.

## 개발 artifact와 실제 남은 업무

개발 체크포인트의 최종 frozen EXE/wheel, 합성 frozen smoke·TEMP 설치/제거·wheel 격리 설치는 완료 이력이다. 상세 hash/실행은 product-results 및 product-final-qa에 있다. 로컬 ignored 후보는 `build/final-dev2-1794666063022/dist/Recoryn`이다. 존재/manifest/source hash를 재확인한 뒤 사용하고, source/의존성/서명/포함 파일 변경 후에는 inventory/SBOM/provenance와 필요한 smoke를 새로 생성한다. weights를 포함하거나 설치/추론을 검증했다고 주장하지 않는다.

**설계 v1.0 전체 구현·실장비·정식 릴리스 완료는 아니다.** 다음 업무를 구분한다.

1. 제품 계약/설계와 현재 코드의 gap을 다시 대조해 후속 구현·배정을 정한다. 개발 체크포인트 VERIFIED를 모든 기능 완성으로 확대하지 않는다. 재시작 뒤 삭제 대기 UI 복원 등 product-results의 후속 항목을 확인한다.
2. Windows 실제 장치 캡처/분리/재생·장시간·OS sleep/resume·전원/장애·Narrator·성능 및 호환성 matrix는 미검증이다. 사용자 조작 없는 실제 음성 실행은 하지 않는다.
3. 실제 Whisper/diarization/Ollama 모델·weights/다운로드·품질/DER/GPU/메모리/장기 수명·daemon 후속 트래픽·실제 외부 제공업체/계정/TLS/vault 검증은 미실행이다. 선택 diarization은 문서의 Windows x64/Python>=3.12 CPU capability/pin 계약을 보존한다.
4. clean Windows VM, 서명, license/corresponding source 법률 검토·공식 배포 G3/G4는 남아 있다. 합성 smoke를 이 gate 완료로 바꾸지 않는다.

후임의 첫 업무는 온보딩/정본 상태 인수·H-P01 CI 확인·후속 gap/우선순위와 새로운 파일 소유 배정을 정하는 것이다. 실장비/모델/유료 실행을 임의로 시작하는 지시가 아니다. 원래 전체 구현 목표는 유지하되 승인 범위와 실제 미검증을 구분한다.

## H-P01 검증·인수 기록

문서 전용 manifest: **AGENTS.md, docs/collaboration/assignments.md, docs/collaboration/orchestrator-handoff.md**. 작성 Q00, 독립 검토 C00. 기준74b1167/CI43612561745 success. 상대 링크·권한 충돌·내용·현재 Git/worker/CI 대조·`git diff --check`·commit trailer 검사를 수행한다. 의미 없는 제품 시험을 재실행하지 않는다. rollback은 문서 commit revert이며 사용자 인수 지시 자체를 임의 취소하지 않는다.

후임 C00이 `HANDOFF_REVIEW_READY`를 회신했다. 읽기 전용으로 필독 문서와 현재 Git/CI·worker·QA JUnit/report·링크를 직접 대조했고, 제품 시험/coverage/정적 검사를 재실행하지 않았음을 구분했다. 권한 전환을 막는 S0/S1/S2는 없었고 아래 보완을 반영했다.

| 독립 검토 항목 | 반영/판정 |
| --- | --- |
| H-R01 / S3 B10 권한 명확성 | B10 WORKING 및 root 소유 범위가 C00으로 승계되고 기존 w5:p1은 이력임을 배정표에 명시 |
| H-R02 / S3 worker 목록 | p5의 BR14 및 Q-P01 정책 리뷰 추가 |
| H-R03 / S3 CI 실패 책임 | 인수 뒤 FAIL/UNVERIFIED도 C00 담당, Q00 자동 쓰기 재개 금지 명시 |
| H-R04 / 선택 S3 trailer 검사 | parse뿐 아니라 메시지 전체의 자동 attribution/생성 문구 검사 추가 |
| H-R05 / 탐색성 정보 | 필독 배정표에서 인계서 링크로 도달 가능하므로 3파일 manifest 유지 |
| H-R06 / 공개 범위 정보 | 불필요한 session UUID 제거, TEMP는 환경변수 표기로 변경; 비밀/토큰 기재 없음 |

보완 후 C00이 **H-R01~R04 RECHECKED, H-R05/06 수락, 문서3파일 수락 가능**을 회신했다. 재확인에서도 파일/Git/메모리/타 pane에 쓰지 않았고, 현재 diff·링크·줄바꿈·UUID 제거·candidate 경로 존재를 직접 확인했다. Q00은 이 독립 판정을 수락해 인계 문서 발견을 종결한다.

현재 **VERIFIED — C00 독립 재확인 및 문서 게이트 수락, H-P01 commit/push와 최종 인수는 별도 확인**. 최종 문서/트리 검증·commit 메시지 trailer 0·정상 push/remote 일치·새 CI 상태를 전달한 뒤 Q00이 쓰기를 종료한다. C00의 최종 ACCEPTED 회신과 해당 Git/Herdr 기록으로 전환 결과를 확인한다. 인계서 자기 hash/commit/최종 회신을 다시 넣기 위한 반복 commit은 하지 않는다.
