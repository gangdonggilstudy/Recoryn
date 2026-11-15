# Recoryn commit·push 단위

상태: 2026-11-15 사용자 요청으로 채택하는 통합 규칙. 기존 commit은 이력으로 보존하며 재작성하지 않는다. root만 공유 Git 인덱스·commit·push를 제어한다.

## 단위의 경계

한 단위는 하나의 사용자 동작·실패 계약·원인 수정 또는 독립된 정책을 갖는다. 구현과 필요한 회귀·직접 관련 문서를 함께 묶고, 무관한 정리·다른 기능·생성 binary를 함께 싣지 않는다. 파일 개수나 날짜·worker 수로 경계를 정하지 않는다. review가 어려울 정도로 커지면 계약/의존성 경계로 나누거나 분리할 수 없는 이유를 기록한다. 실행을 깨뜨리는 stub·실패하는 시험만 선행 공개하지 않는다.

| 유형 | 포함 | 필수 검증 |
| --- | --- | --- |
| 정책·설계 | 규칙·계약·배정·직접 관련 리뷰 | 링크/내용/권한·서로 모순되는 규칙의 독립 검토 |
| 기능·오류 수정 | 구현·필요한 회귀·API/사용 문서 | 위험별 시험 계층·case matrix·정적 검사·독립 리뷰 |
| 시험 보강 | 기존 계약의 누락 조합·oracle·증거 | 정상본 PASS·분모/실행 대조·mutation/부정 대조·독립 리뷰 |
| 패키지·릴리스 | 빌드 설정·증거·실제 artifact 연결 | 동결 입력·포함 파일 hash·SBOM/license·해당 smoke/릴리스 게이트 |

단위는 가능한 한 독립적으로 검토·revert할 수 있어야 한다. 외부 호출·schema migration·공용 API처럼 외부 효과/선행 의존성이 있으면 rollback 조건과 순서를 따로 적는다. 테스트와 문서가 연결된 원인 수정은 줄 수를 줄이려고 쪼개지 않는다.

## 사전 manifest와 상태

push ID, 목적과 제외 범위, 기준 commit, 정확한 포함 파일, 작성자·다른 세션의 검토자, 선행 단위/DAG, 수락 기준·실행할 검사, case 설계/증거 경로, 위험·rollback을 배정표 또는 해당 단위 기록에 먼저 적는다. 완료 후 검증된 파일/tree digest, 실제 검사·독립 판정, commit SHA, push 응답/원격 ref, CI 상태와 URL을 연결한다. 자기 commit SHA를 본문에 넣기 위한 무한 후속 commit은 만들지 않는다. 최종 단위의 SHA/CI는 Git ref·원격 run이 정본이며 다음 기록 갱신에서 링크할 수 있다.

상태는 PLANNED → WORKING → REVIEW_READY → VERIFIED → COMMITTED → PUSHED이며 원격 CI는 별도로 QUEUED/RUNNING/PASS/FAIL/UNVERIFIED를 기록한다. local VERIFIED·push 성공·CI 성공·공식 릴리스는 각각 다른 상태다. CI 실패는 다음 의존 단위 진행을 막고 root가 원인을 수정/재검증한다. 기존 미관계 실패도 실제 원인과 영향·해소 조건을 남긴다.

## 공유 workspace의 통합

1. worker는 자기 파일과 case 설계/결과만 작성하고 인덱스·Git 이력을 조작하지 않는다. root가 단위와 파일 소유권을 배정한다.
2. root는 리뷰·실패/보류·선행 단위를 확인하고 해당 단위의 파일만 명시 stage한다. 기본 `git add .`/`-A`, 타인의 변경 stash/reset/clean 또는 부분 구현을 몰래 끼우는 방식은 사용하지 않는다.
3. 작업 디렉터리의 추가 변경까지 사용한 전체 pytest를 부분 stage된 commit의 검증이라고 주장하지 않는다. stage된 파일이 검증 hash와 같은지 확인하고, 필요한 실행은 stage/commit tree의 고유 임시 checkout에 한정해 수행한다. dirty 파일·추가 untracked 테스트·환경 PYTHONPATH가 검증을 대신하지 않게 한다.
4. 의존 단위의 파일이 검증에 필요하면 그 의존성을 먼저 통합하거나 같은 논리 단위로 재설계한다. 고위험 변경과 batch 마지막 단위는 정확한 통합 tree의 전체 오프라인 회귀/coverage를 실행한다. 앞서 정상인 문구 변경 등에 무의미한 전체 재시험은 반복하지 않는다.
5. root가 commit을 만들고 대상 branch/remote의 예상 부모와 비교한다. normal push 후 remote ref와 commit 동일성을 확인한다. 실패/미확인 push를 성공으로 기록하지 않고 강제 push하지 않는다.
6. 원격 CI의 실제 head SHA·run 결과를 읽고 다음 의존 단위의 게이트로 사용한다. 원격 확인이 불가능하면 UNVERIFIED로 남기고 의존 단위 공개를 보류한다. 고립된 계획/분석/로컬 구현은 계속할 수 있다.

독립 단위라도 하나의 main에 직렬 통합하면 이전 원격 상태를 확인한 뒤 다음 단위를 공개한다. 한 번의 push에 여러 commit을 보낼 때도 각 commit의 단위와 검증을 보존하고 선행 순서를 지킨다. CI가 마지막 head만 검증한 경우 그 사실을 명시한다.

## 이번 적용 순서

| push ID | 목적·파일 범위 | 선행·검토·게이트 |
| --- | --- | --- |
| Q-P01 | 시험 경우의 수/푸시 규칙: AGENTS.md, onboarding/workflow/quality-system, case-space.md, 이 문서, Q 배정 및 독립 정책 리뷰 | 기준 30703fe; root 작성, Q24 worker 정책 독립 검토; 문서·링크·권한 검증 |
| Q-P02 | 상태/오디오의 수학적 시험 보강: Q21/Q22 전용 새 시험·case 문서와 해당 독립 리뷰·단위 결과 | Q-P01/CI PASS; Q23/Q24 독립 검토; stage tree의 관련 시험·정적 검사·선언 분모/mutant 결과 |
| Q-P03 | 게시/보안의 조합 시험 보강: Q23/Q24 전용 새 시험·case 문서와 해당 독립 리뷰·단위 결과 | Q-P02/CI PASS 후 직렬 공개; Q21/Q22 독립 검토; 정확한 통합 tree의 전체 오프라인 회귀/coverage·정적 검사 |

2026-11-15 라이선스 개선 L-P01~L-P03의 목적·선행·검토·게이트는 [라이선스 검토 L01](../implementation/license-review.md)의 push 단위 표를 따른다. L-P01 → L-P02 → L-P03 순서로 각 선행 CI PASS 뒤 공개한다.

구체 파일과 현재 배정은 [작업 배정표](assignments.md)에 둔다. 시험으로 제품 결함이 발견되면 root가 해당 원인 수정+원 반례를 별도 단위 또는 현재 관련 단위에 재배정하고 검증을 마친다. 실패를 xfail/skip으로 숨기거나 실패하는 시험만 main에 push하지 않는다. 이 계획을 실제 push 완료나 모든 경우의 수 검증으로 기록하지 않는다.
