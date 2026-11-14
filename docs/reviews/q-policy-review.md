# Q-P01 정책 독립 검토

2026-11-15. 작성자 Q00/root, 독립 검토자 Q24. 기준 HEAD `30703feeb8b109dcfbf5093df58c964076e43ae9`. **REVIEW_READY — 정책 범위 추가 OPEN S0/S1/S2 0건.** 아래 일곱 정책 파일을 읽기 전용 검토하고 이 리뷰만 작성했다. 실제 stage/commit/push·원격 CI 통과는 root가 별도로 확인한다. 과거 1444 PASS는 이번 정책이나 후속 시험의 실행 결과가 아니다.

## 검토 범위와 판정

| 관점 | 독립 대조 및 판정 |
| --- | --- |
| 수학적 분모 | case-space는 Ω의 직적 크기와 feasible F의 분모를 구분하고 생성기와 별도 계산을 요구한다. 독립 손계산으로 6×6×3=108, 3!=6, 두 길이-2 chain의 순서 C(4,2)=6, 세 길이-2 chain의 순서 6!/(2!³)=90을 대조했다. 모두 정의 예시이며 실제 실행 주장으로 쓰지 않는다. t-wise는 인자 부분집합과 값 tuple을 함께 세므로 서로 다른 부분집합의 같은 값 tuple이 합쳐지지 않는다. |
| 과도한 feasible 제외 | 거부해야 할 입력·전이를 F에서 제거하지 않는다고 명시한다. fixture 자체 구성 불가능성의 제외에도 구체 근거와 독립 리뷰가 필요하다. 예컨대 owner 불일치와 철회가 함께 참이라는 이유만으로 해당 부정 행을 빼는 해석은 허용되지 않는다. |
| 전수·독립 oracle | 유한 대표 집합의 전수와 무한 구간/깊이 밖 검증을 구분한다. 기대 전이표를 제품에서 import하거나 같은 계산을 복제하는 시험은 독립 oracle가 아니다. 실제 유일 case ID·누락·중복·미검증과 기존 node 대응을 요구해 단순 시험 수 증가를 충분성으로 삼지 않는다. |
| mutant 검출 | 실제 workspace와 인덱스가 아닌 임시 사본을 사용한다. 정상 PASS와 명명한 목표 assertion FAIL을 요구하며 import/collection/권한/timeout만으로 검출 성공을 세지 않는다. 일부 mutant 검출을 전체 프로젝트 mutation coverage로 확대하지 않는다. 문서 전용 Q-P01에 의미 없는 제품 실행·mutant를 추가할 요구는 없다. |
| 예외 권한·소유권 | AGENTS의 최신 사용자 지시 우선과 root의 명시적 배정이 권한 기준이다. worker는 새 제품/기존 시험/공용 설정·Git을 수정할 수 없다. 제품 결함이 발견되면 원 반례를 보고하고 root가 원인 수정과 회귀의 파일 manifest를 먼저 재배정한다. 테스트 분모 축소·skip/xfail·실패 단독 push를 root 재량의 묵시적 예외로 만들지 않는다. |
| 공유 workspace와 정확한 tree | push-units 3항은 dirty/untracked 시험까지 사용한 실행을 부분 stage된 commit 검증으로 주장하지 못하게 한다. 명시 stage 파일의 검증 hash 일치와 필요한 stage/commit tree의 고유 임시 checkout 실행을 요구한다. 현재 commit에 없는 후행 Q-P03 시험으로 Q-P01/Q-P02 검증을 대체할 수 없다. |
| 의존성과 CI | Q-P01 → Q-P02 → Q-P03 직렬 공개와 각 선행 CI PASS가 명시돼 있다. CI 조회 불가면 UNVERIFIED로 공개를 보류한다. 계획·분석·고립된 로컬 작성은 계속할 수 있으므로 worker의 선행 작성 자체가 선행 CI를 우회한 push가 되지 않는다. 여러 commit을 한 번에 공개할 수 있다는 일반 문구도 선언된 선행 CI 게이트를 면제하지 않는다. 마지막 head만 CI가 돌면 각 선행 commit도 따로 검증됐다고 주장할 수 없다. |
| 명시 stage와 작은 push | Q-P01은 root 정책 7파일과 이 독립 리뷰의 정확한 8경로다. Q-P02/03은 각 목적의 새 시험·case 문서·다른 검토자의 리뷰·root 단위 결과로 나뉜다. `git add .`/`-A`, 타인 stash/reset/clean 및 미완성 시험 혼입이 금지된다. 실패 계약과 그 원인 수정/필요 회귀는 논리 단위를 유지한다. |
| 독립성 | Q24는 root 정책을 리뷰하고 자기 보안 시험은 Q22가 검토한다. Q21↔Q23, Q22↔Q24의 지정 대상/리뷰 파일 이름도 대조했다. 자기 작성·자기 발견의 수정 완료 보고가 단독 최종 승인이 될 수 없다. Q-P01의 정책 리뷰를 Q24 제품 보안의 독립 승인으로 전용하지 않는다. |

수학적 분모·거부 입력·권한·정확 tree·CI 선행·stage·독립성 사이에서 이번 작은 정책 push를 막는 모순은 발견하지 않았다. 실행 단계에서는 위 해석과 실제 manifest·hash·CI를 대조해야 하며 이 문서만으로 그 후속 절차를 완료했다고 보지 않는다.

## 검토 snapshot

LF 정규화(CRLF/CR→LF) 파일 SHA-256이다. 리뷰 파일 자체 hash를 본문에 반복 삽입하는 순환은 만들지 않으며 root가 이 리뷰를 포함한 정확한 8파일 stage/tree를 통합 시 고정한다.

| root 작성 정책 | SHA-256 |
| --- | --- |
| AGENTS.md | 83b6127a723a4b9edd94b05245870897b822b295fa59f1629dcb6a937c5d763f |
| docs/collaboration/onboarding.md | fee9ee2b69776c7b9caa059fdfe5b85509d3e3375e59e17df11ec2af70229c57 |
| docs/collaboration/workflow.md | 3cedda0893f4c47e921d89198813383927f455a3f5a7f544500c005a63609ebe |
| docs/collaboration/assignments.md | 4143b4e9be3eaa1bfc396f8a8a5a26537255003e418b438b586bda32c56024cb |
| docs/collaboration/push-units.md | 4554a4f3f8b1ce5465de344cd236dc8f5ea55be3252d8fbcc6c25e24735bbbf8 |
| docs/quality-system.md | 5029757e3751f2b070da010e8287a41d1771d330decbabf96f212ed65fdfe69f |
| docs/testing/case-space.md | 6abe0c3ac2eee4e909932301d447a1e74f738b7615e308f547375246e7077651 |

실제 검증은 문서 본문·현 diff·배정 표의 상호 대조, 위 산식 손계산, 일곱 정책 파일의 Markdown 상대 링크 존재 검사다. 누락 링크는 0개였다. `git diff --cached --name-only` 조회 시 인덱스 변경은 없었다. Git 전역 ignore 접근 거부 경고는 읽기 전용 조회의 환경 경고이며 정책/제품 실패로 집계하지 않았다. 제품 코드·기존 시험·Git은 수정하지 않았다.

root의 마지막 보완으로 Q-P01~03 manifest가 전체 저장소 상대 경로로 풀어 쓰인 배정표를 다시 읽고 위 digest를 갱신했다. Q-P01 8경로와 Q-P02/03 각각 7경로의 소유자·서로 다른 독립 검토자·선행 CI 조건은 일치한다. 다른 여섯 정책 digest는 그대로였다. 이 보완 후 판정도 REVIEW_READY, 추가 OPEN 0건이다.

문서 전용 정책 리뷰에 대한 구현 pytest·coverage·mutation은 NOT_APPLICABLE이다. Q-P02/03에서는 선언 분모·정상 시험·mutant·독립 리뷰와 정확한 통합 tree 검증을 실제 실행해야 한다. 원격 CI·push는 미실행/미확인이고 Q-P01 root 통합 단계로 남긴다. 실제 음성·장치·모델·서비스·계정·G3/G4 승인은 이 검토 범위가 아니다.
