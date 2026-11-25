# Recoryn 오케스트레이터 임시 인계서 H02

2026-11-26. 사용자 명시 지시: "codex 중 하나에 오케스트레이터 임시로 이관하고 작업도 codex들만 하도록 이관". 작성 C00/Claude(w5:p6, 세션 a8d89c62). 임시 후임 **X00 = w5:p9 Codex**. 이관 시작 기준은 `main` / `7420a4e247274f3a6ed3c67e842c3406a566df0e`(G-P17c)이다. 이 문서는 [H01 인계서](orchestrator-handoff.md)의 절차와 불변식을 그대로 승계하고, 그 뒤 바뀐 상태만 적는다. 임시 이관의 종료나 C00 복귀는 사용자 지시로만 정한다.

## 1. 단일 작성자와 전환 절차

1. X00은 아래 필독 문서, 현재 Git·Herdr 상태, 이 문서를 읽고 Git·제품·공유 파일을 쓰지 않은 상태로 `HANDOFF_REVIEW_READY`와 확인 결과를 C00에 보고한다.
2. C00이 `TRANSFER_EFFECTIVE`를 보낸 순간부터 C00은 공유 Git·배정표·공용 계약에 쓰지 않는다. X00이 `ORCHESTRATOR_ACCEPTED`로 인수한다. 그 뒤 유일한 오케스트레이터이자 공유 Git 작성자는 X00이다.
3. 이 문서와 C00이 남긴 `docs/collaboration/assignments.md` 작업 트리 변경은 커밋되지 않은 상태로 넘긴다. X00이 첫 단위 H-P02로 검증·커밋·push한다. 단, 진행 중인 G-P17c CI(아래 §3)가 끝나 통과를 확인하기 전에는 push하지 않는다.
4. "작업은 Codex만": Claude 세션(w5:p6 C00, w5:p7)과 Claude 하위 에이전트는 작성·검토·위임에 쓰지 않는다. 둘 다 읽기 전용으로 대기한다. 서버·pane은 종료하지 않는다.

## 2. 역할과 독립 검토

| 세션 | 역할 |
| --- | --- |
| w5:p9 Codex | X00. 요구·배정·결정·독립 검토 종결·최종 QA·정확한 commit/push·CI·사용자 보고 |
| w5:p8 Codex | 작업자(GS-P11a 작성 중). X00의 명시 배정 범위만 쓴다 |
| w5:p7 Claude | 읽기 전용 대기. 이전 G-P12b·GS-P04a 리드 역할 종료 |
| w5:p6 Claude(C00) | 읽기 전용 대기. 사용자 지시가 있으면 복귀 |

작성자는 자기 결과를 최종 승인하지 않는다. Codex가 둘뿐이므로 다음처럼 교차한다. X00이 w5:p8 결과(GS-P11a 등)를 독립 검토하고, w5:p8이 X00의 이전 작성물(GS-P04a)을 독립 검토한다. 다른 Codex 세션이나 하위 에이전트를 새로 쓰려면 사용자 요청 범위와 [AGENTS](../../AGENTS.md)의 재위임 규칙을 따른다.

## 3. Git·CI 체크포인트(이번 C00 구간)

| 단위 | commit | 원격 CI |
| --- | --- | --- |
| G-P11d | f4f94b7 | 45630230099 success |
| G-P13 | 3566862 | 45657820277 success |
| G-P17a | 6156b65 | 45666749228 success |
| G-P12b | de27a81 | 45685959530 success |
| GS-P06 | 5aa988e | 45696240558: core 3.13·optional-runtime success, **core 3.11 cancelled**. 시험 433~504번째 구간(G17-R-03/R-04 포함)에서 출력이 멈춰 120분 제한. 로그는 `build/ci-evidence/gs06-core311.log` |
| G-P17c | 7420a4e | **45714605921 진행 중**. GS-P06 내용도 함께 다시 검증한다. 통과를 확인한 뒤 다음 단위를 push한다 |

GS-P06의 3.11 정지는 G17R-06 시험 결함이 예측대로 나타난 것이다. 원인은 시험이 공유 SQLite 연결에 Python trace 콜백을 단 채 mutex 없이 같은 연결을 읽은 GIL·연결 mutex 순환이다. 제품 교착은 아니다. 근거는 `docs/reviews/g17a-append-durability-review.md`의 'HANG 조사'와 'RECHECK 3'이다. G-P17c CI가 다시 멈추거나 실패하면 X00이 로그를 받아 원인을 판정한다.

## 4. 진행 중 단위와 다음 행동

| 단위 | 상태 | X00의 다음 행동 |
| --- | --- | --- |
| G-P17c CI | 진행 중 | 결과를 확인하고 배정표 G17 행을 DONE으로 갱신 |
| GS-P04a | 작성 w5:p9 완료, 리드 w5:p7 검증 완료: 28,839 PASS·coverage 92.88% 7묶음 PASS·offline wheel PASS·변이 58/58(리드 11/12, L05 동등). 송신 경로 0, 생산 route registry 빔, NOT_RUN 유지 | **X00이 작성자이므로 직접 승인하지 않는다.** w5:p8에 독립 검토를 배정한다. 결정 A~G는 배정표 GS04 행 참고 |
| GS-P11a | w5:p8 **SCOPE_NEEDED 2차**. 21파일로 확장 요청: G05 integration fixture 적응·unit pending 파일 추가, seal_phases·storage·unfinished_recovery 시험 제한 적응, C1 kill이 남기는 root staged 파일의 quarantine 처리·위치 단언·G09 인계, 신규 시험 예산 360초(428 PASS·332.5초, 행 축소 없음). 계약 문서 §17~18(43523617…) | X00이 결정한다. C00의 1차 결정(배정표 GS11 행: 12→17파일, 목표 90초·상한 150초)은 기록돼 있다. C00 의견: 기존 시험 적응은 단언 약화 0과 행별 이유 표가 조건이다. 360초는 CI 41분에 비해 크므로, H=10,000 데이터 공유와 호출 수 기반 판정으로 먼저 줄이고 남는 값을 측정 근거와 함께 승인하는 편이 낫다 |
| GS-P04b | 보류 | 정본 metadata route·비용 정책 승인과 GS-P05(비밀 수명) 합의 뒤 |

이후 큐(배정표·[S3 묶음 계획](../implementation/s3-bundle-plan.md)·[v1 gap 계획](../implementation/v1-gap-plan.md) 기준):

- **저장소:** GS-P11a → G-P09a → G-P17b → GS-P01 → GS-P11b → G-P09b → GS-P11c → G-P10 → G-P14
- **AI:** GS-P04a → GS-P05 → GS-P07·GS-P09 → GS-P04b
- **S3 후속 행:** G-P08b(G17R-03 인계 포함), G-P12c, G-P13b, GS-P06b, G-P16b, GS-P03, GS-P08, 마지막 GS-P10

## 5. 커밋되지 않은 C00 소유 변경

| 파일 | 내용 | 처리 |
| --- | --- | --- |
| `docs/collaboration/assignments.md` | G11d·G13·G17·G12b·GS06 결과 갱신, GS04·GS11 결정, G13b·GS06b 등 행 | H-P02에 포함 |
| `docs/collaboration/orchestrator-handoff-h02.md` | 이 문서 | H-P02에 포함 |
| `docs/implementation/v1-gap-plan.md`, `docs/implementation/s3-bundle-plan.md`(미추적) | G-P15~17 행, S3 묶음 연결, 실제 가격 게이트 | 승인 문서. 관련 단위나 H-P02에 포함 |
| `docs/testing/g09-…`, `g10-…`, `g14-…`(미추적) | 승인된 계약안 | 각 구현 단위 커밋에 포함 |
| `docs/testing/gs04-…`, `gs11-…` 및 GS-P04a·GS-P11a 제품·시험 파일 | 작업 중 단위 | 각 단위 커밋에 포함 |

## 6. 절차·도구

- push 단위 규칙은 [푸시 단위](push-units.md)와 H01을 따른다. 순서는 계약 → 승인 → 구현 → 다른 세션의 독립 검토 → FIX/RECHECK → 정확한 tree 검증 → commit → push → CI 확인이다.
- C00 도구 사본은 `build/orchestrator-tools/`(gitignore)에 있다. 읽고 나서 사용하며 수정은 자유다.
  - `unit_tree.py <repo> <files…>`: HEAD에 지정 파일만 얹은 tree를 만든다. 임시 index만 쓴다.
  - `row_tree.py <repo> --rows "| ID / …" … -- <files…>`: 위와 같고, 배정표의 지정 행만 반영한다.
  - `exact_tree.py <repo> <tree> <label>`: tree를 풀어 CI와 같은 pytest+coverage, check_coverage, ruff, format, mypy를 돌린다. origin 검사 포함. 로그는 `%TEMP%\recoryn-<label>-tree-*`에 남는다.
  - `ci_job_log.py <run> "<job>" <out>`: 실패 또는 취소된 job의 로그를 받는다.
- 커밋은 `git commit-tree <tree> -p <HEAD> -F <msg>` → `git update-ref refs/heads/main <C> <P>` → `git reset -q` 순서로 한다.
- push는 `git push https://github.com/gangdonggilstudy/Recoryn.git <C>:refs/heads/main`으로 한다. SSH origin은 쓰기 권한이 없다. `gh`는 설치돼 있지 않다.
- CI는 `.venv/Scripts/python build/q-ci-read.py <sha> --jobs`로 읽는다.
- **commit trailer 금지**(사용자 지시). push 전에 `git interpret-trailers --parse` 결과가 비어 있는지, `co-authored|signed-off|generated with|claude.com`이 0건인지 확인한다.
- 작업 트리는 여러 세션이 공유한다. 단위의 파일 해시를 작성자 보고, 작업 트리, tree에서 서로 대조한다(LF 기준).

## 7. 사용자 결정 대기와 외부 게이트

- G-P17b 녹음 동기화 기본값: 블록마다(현재) 대 BATCHED(N=100블록 또는 T=1초). G-P13 측정에서 AI 없이도 이 PC의 2트랙 writer 처리량은 111~175 block/s로, 필요한 200에 못 미쳤다.
- G4 항목(Microsoft 조건, Qt 소스 호스팅, 서명, 법무, clean VM), Git 이력 삭제(보류), D:\d 폴더 삭제(사용자 직접).
- 실장비·실음성·weights·유료·계정·실서비스는 계속 자동 실행하지 않는다.

## 8. 인수 확인 형식

X00의 `HANDOFF_REVIEW_READY`와 `ORCHESTRATOR_ACCEPTED`에는 다음을 적는다. 받은 숫자를 직접 재실행한 결과처럼 쓰지 않는다.

- 역할과 쓰기 범위
- 실제 HEAD와 원격 ref, G-P17c CI 상태
- 작업 트리 변경 수와 위 §5 대조
- 진행 중 단위와 첫 배정 계획
- 작성자·검토자 교차 방식
- trailer 금지 확인
- Claude 세션 사용 중지 확인
