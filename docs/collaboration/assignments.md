# Recoryn 작업 배정표

현재 단계: 사용자 지시에 따라 설계 v1.0의 구현 완료까지 개발한다. 아래 D/P 배정은 완료 이력이며 B 배정이 현재 활성 범위다. 배정 없는 신규 세션은 온보딩 후 대기한다. 오케스트레이터만 이 표를 수정한다. pane ID는 조회 시점의 식별자이며 재접속 후 재조회한다.

## 2026-11-15 L: 배포물 라이선스 검토와 개선

사용자는 오픈소스 중 무료로 쓸 수 없는 라이선스의 전수 검토, 개선 계획과 작업 진행을 지시했다. 기준 commit은 H-P01 `0cf9cdd730eae4fccb9e67446f58ffa1ebb61439`이며 원격 CI 43675045600 세 job PASS를 C00이 확인했다. 판정·결정·push 단위는 [라이선스 검토 L01](../implementation/license-review.md)이 정본이다. C00이 작성하며 아래 검토자가 독립 검토한다. 이 표의 C00 쓰기 범위는 해당 배정 동안 기존 B13/B23 소유권보다 우선한다.

| 배정 / push | 작성 쓰기 범위 | 독립 검토자와 검토 쓰기 범위 | 상태 |
| --- | --- | --- | --- |
| L01 / L-P01 | docs/implementation/license-review.md, 이 표, docs/collaboration/push-units.md | recoryn-security(w5:p5): docs/reviews/license-plan-review.md만 | VERIFIED — L01-01~03 RECHECKED, C00 CLOSED |
| L02 / L-P02 | src/recoryn/transcription/audio_input.py(신규), src/recoryn/transcription/adapters.py, packaging/recoryn.spec, packaging/release_manager.py, packaging/release_smoke.py, packaging/rthook_no_av.py(신규), scripts/build_release.py, tests/unit/test_stt_audio_input.py(신규), tests/unit/test_providers.py, tests/release/test_spec.py, tests/release/test_release.py, tests/release/test_build_inputs.py, docs/testing/l02-stt-input-cases.md(신규), docs/implementation/license-results.md(신규) | recoryn-ml(w5:p4): docs/reviews/l02-stt-input-review.md·tests/integration/test_stt_input_independent.py만. recoryn-arch(w5:p2): docs/reviews/l02-packaging-review.md만 | VERIFIED — STT·패키징 독립 검토 OPEN 0(L02-STT-01·02, L02-P01~03 RECHECKED, C00 CLOSED), 정확 tree 7386 PASS·frozen smoke PASS |
| L03 / L-P03 | packaging/release_evidence.py, packaging/notices/*(신규), scripts/build_release.py, tests/release/test_evidence.py, tests/release/test_build_inputs.py, docs/implementation/license-results.md | recoryn-security(w5:p5): docs/reviews/license-notice-review.md만 | PLANNED |

검토자는 대상 제품·시험·설정과 Git을 수정하지 않는다. 발견은 원 반례와 함께 자기 리뷰 문서에 남기고 C00이 수정한 뒤 같은 검토자가 재확인한다. 실음성·모델 weights·GPU·네트워크 서비스·유료 호출·추가 위임·승인 UI 대리 입력은 금지한다. worker는 ONBOARDING_READY로 범위와 미검증을 보고한 뒤 시작한다.

## 2026-11-15 오케스트레이터 인수인계 H01 / C00

사용자가 Recoryn 영역의 Claude 세션으로 오케스트레이터 업무 전체를 이전하도록 명시했다. 조회한 후임은 **w5:t3/w5:p6 Claude**, cwd `D:/project/Recoryn`이다. 상세 권한·현재 정본·작업자·남은 게이트와 인수 절차는 [오케스트레이터 인계서](orchestrator-handoff.md)를 따른다. 기존 Codex root/w5:p1은 H-P01 인계 문서 단위를 마감한 뒤 읽기 전용으로 전환하고, 후임의 `ORCHESTRATOR_ACCEPTED` 회신으로 단일 오케스트레이터 권한을 전환한다. 그전에는 후임이 Git/제품/공유 문서를 쓰지 않는다. 전환 후 C00/Claude가 요구사항·설계·배정·리뷰 종결·최종 검증·commit/push·CI와 사용자 보고를 전담한다. 기존 문서의 root/Q00/B10은 과거 작성자 또는 오케스트레이터 역할이며 영구적인 Codex 전용 권한이 아니다. **계속 활성인 B10의 WORKING 상태와 root 소유 app/ui/models/cli/packaging/CI/협업 문서 범위도 C00/w5:p6이 승계하며, 아래 표의 기존 w5:p1 표기는 이력이다.** worker의 별도 소유 파일은 새 명시 배정 없이 덮어쓰지 않는다.

Q21~Q24 및 관련 독립 리뷰는 **VERIFIED·파일 동결·읽기 전용 대기**다. 아래 Q 절의 ASSIGNED/배정 경로는 최초 계획 이력으로 보존하며 새 쓰기 허가가 아니다. 현재 결과는 [Q-P02](../testing/q-core-results.md), [Q-P03](../testing/q-policy-results.md)와 Git/해당 head의 CI가 정본이다. 최신 제품/시험 head `74b1167fb6c5c4957b51891511cdfa2629dc3874`의 원격 CI `43612561745`는 세 job 모두 success다. 사용자 후속 지시인 **commit trailer 금지**도 AGENTS 및 인계서에 반영한다.

H-P01은 기준74b1167의 문서 전용 단위다. 정확한 manifest는 AGENTS.md, docs/collaboration/assignments.md, docs/collaboration/orchestrator-handoff.md의 3파일이며, 작성자는 기존 Codex/Q00, 독립 검토자는 후임 Claude/C00이다. 내용·상대 링크·권한 충돌·diff/commit trailer 검사를 수행한다. commit/push·원격 ref/CI 상태와 최종 수락 회신은 인계 절차에 연결하고, 이 문서 변경에 제품 시험을 추가하지 않는다.

## 2026-11-15 Q: 경우의 수 기반 시험과 push 단위 적용

사용자는 경계·조합·상태·순서의 경우의 수를 계산한 촘촘한 시험과 필요한 시험 계층의 적극 적용, push 단위의 사전 설계·체계화를 지시했다. 기준 commit은 30703fe이며 시작 작업 트리는 clean이다. root/Q00은 AGENTS·온보딩·workflow·quality-system·case-space/push-units 문서와 이 표, 단위 결과·통합 Git/CI를 소유한다. [경우의 수 규칙](../testing/case-space.md)과 [Q-P01~03 push 계획](push-units.md)을 먼저 읽는다.

| 배정 / 실제 pane | 쓰기 허용 파일 | 수락 기준 | 독립 검토 / push |
| --- | --- | --- | --- |
| Q21 상태·작업 / w5:p2 | tests/property/test_job_case_space.py, docs/testing/q21-state-cases.md | 기존 시험과 중복을 조사하고 명시 event alphabet/제약/깊이의 유한 명령열·경계/fence를 독립 모델과 대조, 선언 분모·실제 실행 및 핵심 mutant 검출 | Q23 / Q-P02 |
| Q22 오디오·수치 / w5:p3 | tests/property/test_audio_case_space.py, docs/testing/q22-audio-cases.md | PCM/분할·frame/byte·시계 경계의 유한 조합과 metamorphic/property, 분모·오차·원본 불변·핵심 mutant 검출 | Q24 / Q-P02 |
| Q23 게시·ML 계약 / w5:p4 | tests/property/test_publication_case_space.py, docs/testing/q23-publication-cases.md | 편집/취소/게시/선택의 happens-before와 feasible 순서 전수, 원본/active/CAS/late-result 독립 oracle·핵심 mutant 검출 | Q21 / Q-P03 |
| Q24 보안·예산 / w5:p5 | tests/property/test_security_case_space.py, docs/testing/q24-security-cases.md | scope/세대/철회/owner/예약의 feasible 결정표·시간/비용 경계, 미송신/UNKNOWN·원본 불변·핵심 mutant 검출 | Q22 / Q-P03 |

Q24는 Q-P01의 root 정책을 먼저 독립 검토하며 docs/reviews/q-policy-review.md만 추가 작성한다. Q21/Q22/Q23/Q24의 독립 검토자는 각각 docs/reviews/q23-test-design.md, q24-test-design.md, q21-test-design.md, q22-test-design.md만 추가 작성한다. 즉 파일명 qNN은 검토 대상 배정 ID이며 검토자 본인의 번호가 아니다. 대상 제품/시험 코드는 직접 수정하지 않는다. 자기 작성 결과를 단독 종결하지 않는다.

배정은 ASSIGNED이며 ONBOARDING_READY 뒤 충돌이 없으면 진행한다. 문서에 인자/제약/분모/oracle/기존 node·추가 node/실행/미검증을 구분한다. 최소 한 개의 명명한 핵심 mutant는 임시 소스 사본에서 검사하며 정상본과 목표 assertion 실패를 확인한다. 실제 workspace 제품 코드·공용 config·기존 시험·Git은 worker 읽기 전용이다. 발견한 제품 결함은 root에 원인·원 반례를 먼저 보고한다. 실제 장치·음성·weights 다운로드·실계정·유료 호출·추가 pane/agent 생성은 금지한다. 첫 policy push의 리뷰 외 상호 코드 리뷰는 작성 제출 뒤 root 재배정으로 시작한다.

Q-P01 정확한 포함 경로: AGENTS.md, docs/collaboration/onboarding.md, docs/collaboration/workflow.md, docs/collaboration/assignments.md, docs/collaboration/push-units.md, docs/quality-system.md, docs/testing/case-space.md, docs/reviews/q-policy-review.md. Q-P02는 tests/property/test_job_case_space.py, tests/property/test_audio_case_space.py, docs/testing/q21-state-cases.md, docs/testing/q22-audio-cases.md, docs/reviews/q21-test-design.md, docs/reviews/q22-test-design.md, docs/testing/q-core-results.md를 포함한다. Q-P03는 tests/property/test_publication_case_space.py, tests/property/test_security_case_space.py, docs/testing/q23-publication-cases.md, docs/testing/q24-security-cases.md, docs/reviews/q23-test-design.md, docs/reviews/q24-test-design.md, docs/testing/q-policy-results.md를 포함한다. 제품 수정이 필요하면 이 manifest를 먼저 변경한다. 각 commit·push/CI의 실제 상태는 해당 단위 결과와 Git/원격 run에 연결한다.

## 2026-11-14 강제 재부팅 후 재개

사용자가 worker 탭의 Codex 4세션과 메인 오케스트레이터 재개를 요청했다. 실제 재조회한 Recoryn workspace는 w5, main은 w5:t1/w5:p1, worker는 w5:t2의 기존 4개 pane이다. 저장소의 staged/unstaged/untracked 변경은 복구 입력으로 보존한다. 이전 검증 수치를 현재 snapshot의 통과로 재사용하지 않는다.

| 재개 배정 | 담당 pane | 이번 쓰기 범위 | 수락 기준 및 시작 순서 | 상태 |
| --- | --- | --- | --- | --- |
| R00 / B10 | root / w5:p1 | 협업·공용 계약·구현 증거, 공용 패키지·CI·CLI, models/*, app/inference.py 및 관련 기존 root 시험. 아래 worker 소유 파일 제외 | 배정 복구, 기준 회귀, API 조정, 독립 리뷰 통합. 실제 장치·모델·외부 서비스는 미실행 유지 | VERIFIED |
| R11 / B11·B23·BR11 | w5:p2 | 기존 B11 content/jobs 및 전용 unit 시험, B23 scripts/build_release.py·packaging/*·tests/release/*·release-checklist.md, BR11 기존 지정 리뷰·독립 시험 | 현 reader/remote-intent/resume 및 BR11 재확인 상태를 먼저 점검하고 남은 수정 후 패키징 재개. 원본 보존·무캡처 offscreen/synthetic 시험 | VERIFIED |
| R12 / B21·B12 | w5:p3 | 기존 B21 전체 지정 파일 및 tests/unit/test_power.py, B12 capture/devices.py·wasapi.py·audio/* 및 전용 unit 시험 | 저장된 부분 구현을 확인하고 B21 증분 전사·편집 보호·power/epoch·미터·Ollama UI·명시 재실행 연결을 이어간다. 공개 API는 root와 조정 | VERIFIED |
| R13 / B22·BR13·BR23 | w5:p4 | B22 diarization/*·test_diarization.py·test_diarization_contract.py·diarization.md, BR13/BR23 기존 지정 리뷰·독립 시험 | BR23 RECHECKED 증거를 현재 코드와 확인하고 B22의 로컬 전용·선택 의존성·취소·원문 불변 계약 구현 재개. B21과 UI 파일 공유 금지 | VERIFIED |
| R14 / B14·BR14·BR24·BR30 | w5:p5 | 기존 B14/B14U security/*·diagnostics/*·ui/privacy.py 및 지정 시험, BR14/24/30 기존 리뷰·독립 시험, tests/integration/test_ollama_runtime_independent.py | 보안·게시·모델 검토의 현재 미해결 항목 확인, ManagedOllama 독립 반례·owned-process 종료·attestation 검토. 대상 root 코드 직접 수정 금지 | VERIFIED |

새 worker는 온보딩 후 현재 diff를 읽고 이 배정 범위에서 이어간다. 추가 세션 생성·위임과 Git 인덱스/commit/push 조작은 금지한다. 작성자는 자체 시험과 REVIEW_READY를 보고하고 독립 검토자가 재확인한다. 인프라 권한 오류는 제품 실패와 분리한다.

R11과 R13의 ONBOARDING_READY를 root가 수신했다. 두 세션 모두 문서·담당 diff 확인, 기존 변경 보존, 소유권 충돌 없음과 핵심 규칙·미검증 범위를 보고했다. R11은 복구 후 관련 회귀 352 PASS를 보고했으며 최종 통합 수치로 합산하지 않는다. 사용자는 배정 범위의 지시를 재확인 없이 전달하고 작업 결과를 오케스트레이터가 받아 검증 후 서버로 push하도록 재확인했다. worker의 Git 조작 금지는 유지한다.

R12도 ONBOARDING_READY와 관련 197 PASS를 보고했다. 기존 API로 B21 배선을 이어가며 ManagedOllama의 readiness·수명 수정은 root/R14 경계에서 조정한다. R14의 독립 Ollama 후속 반례는 root가 8 FAIL/28 PASS로 재현했다. 이를 위한 추가 배정: root는 models/ollama.py·새 models 하위 수명 모듈·전용 unit 시험과 providers/contracts.py·_common.py의 선택 실행 guard 계약을 작성한다. R14는 security/gateway.py의 선택 dispatch_guard 및 for_session 보존, ui/privacy.py의 고정 proof guard 연결과 전용 시험을 작성한다. guard 순서는 consent → ledger → owner이며 owner는 consent를 역호출하지 않는다. R14 작성분은 R13이 독립 재확인하며 root helper는 R14가 기존 원 반례로 재확인한다. 기존 trusted static attestation API는 호환하고 managed proof는 종료·owner 교체·파일 변경 시 무효화한다.

R13의 B22는 자체 55 PASS·strict mypy 9파일과 함께 REVIEW_READY다. R11의 B23은 자체 371 PASS 및 source smoke/정적 검사 보고를 수신했으며 대형 frozen build는 root의 최종 snapshot에서 수행한다. 교차 검토를 추가 배정했다: BR41/R11은 diarization 읽기 전용, docs/reviews/product-diarization-review.md·tests/integration/test_diarization_independent.py만 작성한다. BR42/R13은 packaging 및 build_release.py 읽기 전용, docs/reviews/product-release-review.md·tests/integration/test_release_independent.py만 작성한다. R13은 BR42 전 새 B14 guard의 BR23 독립 재확인도 수행한다. 작성자 단독 종결은 금지한다.

R12/B21은 변경 runtime 6파일·관련 시험과 자체 350 PASS를 제출해 REVIEW_READY로 동결했다. 최신 B21의 BR13 AI/편집/모델·근거 검토는 R13에게 기존 BR13 리뷰·독립 시험 범위로 재배정했다. 최신 desktop/power/control lane의 BR12는 B21 작성자가 아닌 R11에게 기존 BR12 리뷰·독립 시험 범위를 이전했다. R12는 root 작성 CI·pyproject·공용 계약·복구 증거만 독립 검토하는 BR44를 맡으며 docs/reviews/product-integration-review.md만 작성한다. 자신의 B21 작성분 최종 승인과 분리한다.

후속 판정: BR41-01은 R11 원 반례 재확인으로 RECHECKED, BR30-01~09는 R14의 독립 66 PASS/관련 297 PASS와 최종 hash로 RECHECKED다. BR23 새 guard/DTO는 R13 독립 43 PASS로 REVIEW_READY, 신규 OPEN 0건이다. R13은 BR42 수정 원 반례 포함 90 PASS를 보고했으며 문서 재확인 마감 중이다. BR13-07 S2(GUI tick에서 in-flight owner handoff lock 대기)는 R13 독립 1 FAIL로 발견되어 R12/B21을 WORKING으로 되돌리고 비동기 attestation 검사·늦은 결과 세대 보호를 재배정했다. R12의 BR44 독립 문서 역할과 B21 수정자 역할은 분리한다. root 최종 artifact·전체 회귀는 이 수정과 리뷰가 끝난 snapshot에서 다시 고정한다.

최종 재동결: BR12-09/R11 및 BR13-07/R13의 최종 runtime hash·원 반례가 RECHECKED이고 BR44-01~03도 RECHECKED다. R15는 R14에게 docs/reviews/product-final-qa.md만 추가 배정해 독립 전체 실행·coverage·전후 source/test/config map·정적 검사를 수행한다. 첫 R15 실행은 1443 PASS/fixture 1 FAIL이며 통과로 마감하지 않는다. QA-R15-01의 status JSON 존재/쓰기 경쟁을 교정하기 위해 root에 test_model_runtime_independent.py·test_ollama_runtime_independent.py·test_ollama.py의 합성 coordination receipt 게시 부분만 임시 재배정했다. 같은 디렉터리의 staging→replace로만 교정하고 제품/원 oracle·종료 assertion·timeout은 변경하지 않는다. R15가 새 시험 map으로 전체 재확인하며 최초 실패/이력을 보존한다. runtime/config와 최종 EXE/wheel 입력은 변경하지 않는다.

최종 통합 판정: R15 재동결 실행 1444 PASS/실패·skip·xfail 0, line 93.37%/branch 86.89%, 핵심 package 분리 예산·Ruff/format/mypy 모두 PASS다. source/test/config 132파일의 전후 LF tree SHA는 `c3a9df87b4545e016652ad13c01605bba1ac6870d8f594ad884a613b20673b64`이며 root도 같은 값을 독립 재현했다. 원 검토자의 RECHECKED와 실제 hash를 대조해 이번 개발 증분 발견을 root가 CLOSED 처리한다. root 최종 EXE 후보의 frozen smoke·TEMP 설치/제거·원본 canary·wheel 격리 실행과 runtime 67/build input 79파일 일치도 PASS다. R00/R11~R14 및 B11~B23의 VERIFIED는 이 개발 증분의 코드·오프라인 계약 검증이며 전체 설계 v1.0·실장비·실모델·G3/G4/공식 릴리스 완료가 아니다. B10의 전체 제품 개발 책임은 계속 활성이다. 후속 상태와 실제 Git 출판 결과는 product-results 후단 및 commit/원격 ref로 확인한다. worker 4세션은 추가 배정 대기 상태로 유지하며 root만 commit/push한다.

## 활성 제품 구현 배정

상세 파일·API·수락 기준은 [제품 구현 계약](../implementation/product-contracts.md)을 따른다. 이번 단계의 작성자 배정이며 독립 리뷰는 작성 완료 후 다른 세션에 다시 배정한다.

| 배정 | 역할 / pane | 수정 허용 범위 | 핵심 수락 기준 | 상태 |
| --- | --- | --- | --- | --- |
| B10 | 오케스트레이터·UX·릴리스 / w5:p1 | 계약·협업 문서, app/*, ui/*, models/*, cli.py, 패키지·CI·scripts, UI/E2E/model 시험 | 전체 기능 연결, 실제 검증 범위·근거 기록, 독립 리뷰 통합, 최종 commit/push | WORKING |
| B11 | 아키텍트·데이터 / w5:p2 | content/*, jobs/__init__.py 및 runner.py, 전용 content/runner/jobs 유닛 시험 | immutable revision, CAS·삭제·취소 경쟁, Job 결과 단일 transaction 게시, bounded runner | VERIFIED |
| B12 | Windows 오디오 / w5:p3 | capture/wasapi.py 및 devices.py, audio/*, 전용 wasapi/audio 유닛 시험 | native format·packet timestamp·stop ack, fake COM 경계, gap·정렬·VAD·파생 변환 | VERIFIED |
| B13 | ML·AI / w5:p4 | providers/*, transcription/*, summarization/*, 전용 provider/contract 시험, provider-matrix.md | 선택 로컬 모델, STT/요약 분리, Gateway 경유, 부분·근거·긴 문서 계약 | VERIFIED |
| B14 / B14U | 보안·QA·동의 UX / w5:p5 | security/*, diagnostics/*, ui/privacy.py, 전용 security/diagnostics 유닛 및 test_gateway.py, tests/ui/test_privacy_ui.py | DNS 전 기본 차단, 철회·원격 UNKNOWN·비용 영속, Windows vault, 비밀 가림, 독립 제공업체·동의·예산 UI | VERIFIED |

모든 세션은 추가 위임·Git 변경·승인 대리·실사용자 녹음·유료 호출을 하지 않는다. 공개 API 변경은 root에 제안하고 배정 확정 후 반영한다. 기존 P0.1 증거는 새 코드까지 승인한 것으로 계산하지 않는다.

### 제품 독립 리뷰 배정

작성 파일 수정과 리뷰 종결은 분리한다. 아래 리뷰는 작성 완료 후 시작하고 대상 수정은 작성자에게 돌린다. 리뷰어는 지정 리뷰 문서와 독립 반례 시험만 수정한다.

| 리뷰 | 검토자 | 읽기 전용 대상 | 수정 허용 결과 | 상태 |
| --- | --- | --- | --- | --- |
| BR13 | B13 ML / w5:p4 | B10 app/ai.py, inference.py, media.py, models/*, ui/ai_bridge.py·content.py 및 관련 시험 | docs/reviews/product-ai-integration.md, tests/integration/test_ai_independent.py | VERIFIED |
| BR12 | R11 아키텍트 / w5:p2 | B10 app/desktop.py·recording.py, ui/main.py·tasks.py·meter.py, media.py 및 관련 시험 | docs/reviews/product-desktop-audio.md, tests/integration/test_desktop_independent.py | VERIFIED |
| BR11 | B11 아키텍트 / w5:p2 | B12 capture/devices.py·wasapi.py, audio/* 및 관련 시험 | docs/reviews/product-native-audio.md, tests/integration/test_native_independent.py | VERIFIED |
| BR14 | B14 보안·QA / w5:p5 | B13 providers/*, transcription/*, summarization/* 및 관련 시험 | docs/reviews/product-provider-security.md, tests/integration/test_provider_security_independent.py | VERIFIED |
| BR23 | B13 ML·보안 / w5:p4 | B14 security/*·diagnostics/*·ui/privacy.py 및 관련 시험 | docs/reviews/product-egress-review.md, tests/integration/test_egress_independent.py | VERIFIED |
| BR24 | B14 QA·아키텍처 / w5:p5 | B11 jobs/*·content/* 및 B10 library._active_jobs 연동 | docs/reviews/product-publication-review.md, tests/integration/test_publication_independent.py | VERIFIED |
| BR30 | B14 보안·QA / w5:p5 | B10 models/*·app/inference.py, model/inference 유닛 | docs/reviews/product-model-runtime.md, tests/integration/test_model_runtime_independent.py | VERIFIED |

이후 B11/B12/B14의 작성 완료에 따라 다른 세션의 리뷰를 추가한다. B10의 native capture 생명주기는 B12 오디오 검토, 삭제·전송 UI는 B14 외 검토자가 별도로 검증한다. B10에 storage/library.py의 _active_jobs만 추가 배정한다. 영속 job_sessions 바인딩이 있는 해당 세션 Job 또는 미바인딩 Job만 삭제를 차단하며 기존 미바인딩 계약은 유지한다. 기존 storage 회귀와 독립 검토를 요구한다.

### 후속 기능 구현 배정

이 표의 파일 소유권은 해당 배정 동안 이전 B10/B12 소유권보다 우선한다. 기존 교차 검토는 이전 snapshot의 증거이며 새 작성분에는 다른 세션의 리뷰가 필요하다.

| 배정 | 작성자 | 수정 허용 파일 | 수락 기준 | 상태 |
| --- | --- | --- | --- | --- |
| B21 | 오디오·데스크톱 UX / w5:p3 | app/ai.py·desktop.py·media.py, app/power.py, ui/main.py·ai_bridge.py·content.py·models.py·meter.py·power.py, tests/e2e/test_ai_workflow.py, tests/unit/test_desktop.py·test_media.py·test_power.py, tests/ui/test_desktop_ui.py·test_content_ui.py·test_models_ui.py·test_live_ui.py | 확정 신규 청크만 증분/VAD 임시 전사, 편집 보호·전체 정정본, AI 준비와 녹음 제어 분리, power/sleep 후 새 epoch, 메타데이터·미터, local Ollama helper UI 연결, 취소·UNKNOWN 명시 재실행, 근거 재생 무결성 | VERIFIED |
| B23 | 아키텍트·릴리스 / w5:p2 | scripts/build_release.py, packaging/*, tests/release/*, docs/implementation/release-checklist.md | frozen spawn entry, 동적 Qt onedir EXE·사용자 범위 설치/제거·원본 유지, 실제 포함 파일 inventory/SBOM/license/hash, 조용한 합성·offscreen smoke | VERIFIED |
| B22 | ML·선택 화자 구분 / w5:p4 | diarization/*, tests/unit/test_diarization.py, tests/contract/test_diarization_contract.py, docs/implementation/diarization.md | 검증된 로컬 ONNX만 선택 로드, 미설치·미지원 capability, 익명 speaker·겹침/불확실·범위 명시, 원문 불변 파생 revision, owned process 취소·무전송 fake 시험 | VERIFIED |

B21의 privacy.py, models/*, app/inference.py, jobs/*, content/*, capture/*, audio/*는 읽기 전용이다. 공개 API 변경은 제안 후 root 확정을 받는다. B23은 현재 reader/remote-intent/resume 및 BR11 재확인을 완료한 뒤 시작한다. 버전·공용 CI·README·최종 artifact 생성과 배포 승인은 root가 통합한다.

B22는 BR23 독립 재확인 후 시작한다. sherpa-onnx 등 공식 offline ONNX API와 모델 라이선스를 확인해 구체 버전·필수 파일을 먼저 제안한다. pickle/임의 remote code/SDK 자동 다운로드는 허용하지 않는다. capability의 최대 처리 범위와 CPU/GPU 지원을 사실대로 표시하고 모델 정확도·화자 신원 식별을 주장하지 않는다. 실제 가중치·음성·원격 서비스 시험은 실행하지 않는다. 의존성·UI 연결은 root/B21이 통합한다.

## 완료한 설계 배정

| 배정 ID | 역할 | 현재 pane | 소유 파일 | 수락 기준 | 상태 |
| --- | --- | --- | --- | --- | --- |
| D00 | 오케스트레이터와 통합 설계 | w5:p1 | AGENTS.md, README.md, docs/design-input-v1.md, docs/architecture-v1.md, docs/validation-plan.md, docs/quality-system.md, docs/collaboration/*, docs/reviews/design-signoff.md | 여섯 관점 통합, 요구사항 추적, 새 세션 규칙과 최종 문서 검증. Git 출판 결과는 별도 확인 | VERIFIED |
| D01 | 수석 아키텍트 | w5:p2 | docs/reviews/architecture.md | 경계, 상태 분리, 영속 계약, 마이그레이션과 취소 정책 | VERIFIED |
| D02 | Windows 오디오 전문가 | w5:p3 | docs/reviews/audio-recovery.md | 캡처 시계, 청크 저장·복구, 포화·장치·절전·디스크 장애 기준 | VERIFIED |
| D03 | ML 엔지니어와 UX 전문가 | w5:p4 | docs/reviews/ai-ux.md | 제공업체 계약, 근거 연결, 전사 버전, 비용·GPU·접근성 | VERIFIED |
| D04 | 보안 및 라이선스 전문가와 QA 릴리스 전문가 | w5:p5 | docs/reviews/security-qa.md | 동의, 비밀, 보존·삭제, 라이선스와 측정 가능한 검증 게이트 | VERIFIED |
| D11 | 독립 아키텍처 교차 검토 | w5:p2 | docs/reviews/cross-ai-ux.md | D03와 통합 계약·품질 체계의 반례와 종결 조건 | VERIFIED |
| D12 | 독립 오디오 교차 검토 | w5:p3 | docs/reviews/cross-architecture.md | D01와 통합 시간·저장 계약의 반례와 종결 조건 | VERIFIED |
| D13 | 독립 ML·UX 교차 검토 | w5:p4 | docs/reviews/cross-security-qa.md | D04와 정책·비용·취소·품질 계획의 반례와 종결 조건 | VERIFIED |
| D14 | 독립 보안·QA 교차 검토 | w5:p5 | docs/reviews/cross-audio-recovery.md | D02와 통합 장애·복구·보안 및 검증 게이트 확인 | VERIFIED |

모든 작업자는 `docs/design-input-v1.md`와 협업 규칙을 읽는다. D01~D04는 병렬로 독립 문서를 작성하고, 공용 계약 충돌은 문서에 결정 제안으로 남긴다. D00은 네 리뷰를 읽고 통합한 뒤 완료 보고와 수락 기준을 대조한다. 보류 결정은 통합 설계의 결정 기록에 소유자와 검증 조건을 남긴다.

D11~D14는 1차 작성자와 다른 세션의 교차 검토다. 검토자는 통합 문서와 타 담당 문서만 읽고 자신의 교차 검토 문서에 발견 사항을 기록한다. D00의 통합 수정 후 검토자가 같은 문서에 재확인을 남긴다. 설계 종결 기록은 D00 소유의 `docs/reviews/design-signoff.md`다. 검토 요청 자체는 검토 통과가 아니다.

설계 단계 결과: D01~D04 통합 및 D11~D14 재확인 완료. 24건의 문서상 발견 사항을 종결했다. 상세 근거와 한계는 [설계 검토 종결 기록](../reviews/design-signoff.md)에 둔다. 오케스트레이터가 최종 Git 검증과 push를 전담하며 실제 출판 결과는 commit과 원격 참조로 확인한다. 제품 실행 검증의 현재 결과는 구현 증거에서 별도 기록한다.

## P0.1 구현 배정

공통 API와 수락 조건은 [구현 계약](../implementation/p0-contracts.md)을 따른다.

| 배정 | 역할과 pane | 소유 파일 | 수락 기준 | 상태 |
| --- | --- | --- | --- | --- |
| P00 | 오케스트레이터 w5:p1 | 패키징·CI·문서, recoryn 루트/cli.py/app/*, tests/e2e/*, scripts/* | 합성 녹음→복구→WAV 실행, 통합 검사. 출판 결과는 commit/원격 ref로 별도 확인 | VERIFIED |
| P01 | 아키텍트 w5:p2 | domain/*, jobs/*, tests/unit/test_domain.py, test_jobs.py | PCM·전이 계약, 영속 Job·Attempt·fence·취소 자체 시험 | VERIFIED |
| P02 | 오디오 w5:p3 | capture/*, tests/unit/test_capture.py | 제한 queue/drop/close·합성 포맷/시간 자체 시험 | VERIFIED |
| P03 | 저장 엔지니어 w5:p4 | storage/*, tests/unit/test_storage.py | journal·manifest·DB·복구·삭제·lock 자체 시험 | VERIFIED |
| P04 | 독립 QA·보안 w5:p5 | tests/integration/*, tests/property/*, docs/reviews/p0-qa.md | 독립 oracle와 subprocess fault·보안/원본 회귀, 통합 코드 리뷰 | VERIFIED |

P01~P03 작성 완료 후 상호 독립 리뷰를 새 배정으로 진행한다. 작업자는 Git 인덱스와 공용 파일을 수정하지 않는다. 실제 장치 캡처와 실장비 검증은 후속 게이트다.

| 리뷰 배정 | 검토자 | 대상 | 소유 리뷰 파일 | 상태 |
| --- | --- | --- | --- | --- |
| P11 | P01 아키텍트 | storage와 저장·복구 테스트 | docs/reviews/p0-storage-review.md | VERIFIED |
| P12 | P02 오디오 | domain/jobs와 작업 상태 테스트 | docs/reviews/p0-jobs-review.md | VERIFIED |
| P13 | P03 저장 엔지니어 | capture와 포화/cutoff 테스트 | docs/reviews/p0-capture-review.md | VERIFIED |
| P14 | P04 QA·보안 | app/CLI·네트워크·export와 전체 회귀 | docs/reviews/p0-qa.md | VERIFIED |

실행 결과: 전체 379개 시험과 core별 line/branch 기준, lint·format·타입 검사 통과. 원 검토자의 재확인을 받아 구현 발견 6건을 종결했다. [P0.1 결과](../implementation/p0-results.md)의 snapshot과 한계가 기준이다. 전체 P0·Windows 실장비·G3/G4는 미완료다.
