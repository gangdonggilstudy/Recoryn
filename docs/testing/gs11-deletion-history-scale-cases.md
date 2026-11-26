# GS-P11 삭제 이력 누적 비용·검증 시점·정본 압축 계약안

## 1. 배정·상태·결정의 성격

2026-11-25, 작성 w5:p8 Codex. C00의 GS-P11 계약 배정으로 이 문서 하나만 신규 작성한다. 제품·시험·공용 설정·다른 문서 수정과 새 성능 시험 실행은 없다. 상태는 **CONTRACT_READY 제안**이며, 아래 검증 시점 변경·저장 형식·파일 범위·분모는 승인 전이다. 자신의 결과를 최종 승인하지 않는다.

근거 코드는 `31bc88b26304eea569d0735857fe0ca0e90b8778`과 GS-P02 검토 tree `4a6b2953`의 `git show <tree>:<path>`로 읽었다. 공유 작업 트리의 G-P12 등 미완성 변경을 구현 근거로 사용하지 않았다. GS-P02 독립 검토의 수정 요청이 오면 그것을 먼저 처리한다.

S2 성능 단위이지만 삭제 의도 뒤 쓰기·게시 금지, 삭제 원본 부활 금지, 권위 불명 시 허용 금지의 변경 위험은 S1 관점으로 독립 검토한다. tombstone의 논리적 삭제·TTL 만료·세션 ID 재사용은 제안하지 않는다.

## 2. 직접 확인한 코드와 인계된 수치

아래 줄번호의 기준은 별도 표시가 없으면 **31bc88b**다. 범위 표기는 해당 함수를 찾기 위한 근거이며 실행했다는 뜻이 아니다.

| 근거 file:line | 직접 확인한 사실·계약 영향 |
| --- | --- |
| `src/recoryn/storage/library.py:283`, `:425`, `:447` | job_authority는 root 밖 journal 전체 선읽기 뒤 root 안에서 권위와 세션 상태를 확인한다. parser는 파일명·schema·세대·상태와 미완성 항목을 검사한다. 열거를 밖으로 옮겨도 정상 조회의 O(H)는 남는다. |
| `4a6b2953:src/recoryn/storage/library.py:298`, `:430`, `:465`, `:477` | GS-P02는 관찰 시작 시각·version·stamp·관찰 세대 검증과 settled 실패 재사용을 추가했다. 성공한 본문 검증은 여전히 매번 새로 한다. 성공 cache를 이미 승인된 기능처럼 전제할 수 없다. |
| `src/recoryn/storage/library.py:588`, `:619`, `:690` | 관리 조회는 journal뿐 아니라 deleted_sessions 전체를 모아 집합으로 만든다. list_sessions는 그 뒤 전체 sessions를 반환한다. H=삭제 이력 수와 S=반환 가능한 세션 수를 분리해야 한다. |
| `src/recoryn/storage/library.py:2598`, 특히 `:2611` | 삭제 의도를 게시할 때 검증된 journal dict 전체를 복사한다. 조회 cache만 고쳐도 삭제 H건 누적 작업의 제곱 증가 원인이 남는다. |
| `src/recoryn/storage/library.py:2630`, `:2641`, `:2730`, `:2781` | 완료 판정은 DB tombstone·자기 journal·미디어 부재를 함께 본다. 최대 세대·live/reader/claim 보류를 지키며, 완료 뒤에도 최소 journal을 남긴다. |
| `src/recoryn/storage/library.py:535`, `:625` | capture는 자기 세션 이름·DB 행을 보는 별도 fence다. 다른 세션의 손상 본문 때문에 이미 진행 중인 녹음을 멈추게 해서는 안 된다. |
| `src/recoryn/storage/_coordination.py:40`, `:60`, `:72` | 열린 Library가 없으면 자기 journal 파일과 deleted_sessions를 직접 검사한다. 압축으로 개별 파일을 없애면서 이 fallback을 그대로 두면 journal-only 삭제 의도를 놓칠 수 있다. 구형 format 거부도 함께 바꿔야 한다. |
| `src/recoryn/jobs/__init__.py:202`, `:230`, `:319`, `:390`, `:476`, `:523`, `:782` | claim·reader_started·block_pending·resume·fail의 세션 transaction이 권위를 묻는다. 순서는 root → Job이고, fail의 acknowledgement=True는 권위 불명에도 정리 ACK를 허용한다. |
| `src/recoryn/jobs/__init__.py:610`, `:690` | 단순 complete와 publisher 경로는 위 세션 transaction과 같지 않다. 측정한 claim 비용을 모든 완료 함수의 비용으로 일반화하지 않는다. 권위 receipt를 게시 경계에 연결할 때도 Job → root 역순 취득은 금지한다. |
| `tests/integration/test_blocked_reason_flow.py:704` | 같은 디렉터리 stamp로 과거 journal 본문만 손상시킨 뒤 다음 claim이 즉시 HISTORY_UNAVAILABLE이어야 한다는 기존 시험이 있다. 성공 cache의 승인에는 이 **검출 시점 계약 변경**을 명시해야 한다. |
| `tests/integration/test_blocked_reason_flow.py:724` | Job 권위 조회의 열거가 root·Job 잠금·Job transaction 밖이라는 구조 시험이 있다. GS-P02의 capture 전용 이름 목록 예외를 Job에 확대하지 않는다. |
| `src/recoryn/ui/main.py:490`, `:541`, 특히 `:547` | refresh_sessions의 _render_sessions가 GUI thread에서 list_sessions를 호출한다. 조회만 worker로 옮겨도 대량 QListWidget 구성 비용이 남으므로 페이지 반영도 bounded여야 한다. |
| `src/recoryn/ui/main.py:502`, `:918`, `:949` | 미확정·삭제 대기 목록은 Task worker, queued 결과, 조회 세대 검사로 반영한다. 삭제 대기 조회 실패를 대기 0건으로 바꾸지 않는 방식도 재사용할 수 있다. |
| `src/recoryn/ui/main.py:1274`, `src/recoryn/ui/tasks.py:69` | 현재 GUI 진입은 Library를 먼저 연 뒤 창을 만든다. 새 전체 검증을 생성자에서 동기 실행하면 시작 화면까지 느려진다. 검증 worker와 준비 상태가 필요하다. |

측정의 출처를 구분한다.

| 출처 | 삭제 0 / 100 / 1000건 | 해석·한계 |
| --- | --- | --- |
| 이 작성자가 앞 GS-P02에서 직접 실행해 `docs/testing/gs02-index-failure-cases.md:268` 이하에 기록 | 최종 claim 중앙값 1.943 / 45.256 / 598.982ms. 비교 기준 31bc88b는 1.592 / 48.328 / 605.839ms | 각 3회 claim의 소수 표본. complete는 전체 journal을 읽지 않았고 최종 0.609 / 0.669 / 0.672ms였다. 이번 계약 단계에서 재측정한 값이 아니다. |
| C00의 이번 배정·G-P12 검토 인계 | Job 약 492ms, GUI list_sessions 약 460ms/1000건, 삭제 누적 비용 제곱 증가 | 다른 검토자의 관측으로 인계받았다. 여기서 로그 재실행·수치 재현을 했다고 주장하지 않는다. |

10,000건·압축률·새 구현 성능·실제 장치의 안전성은 미측정이다. 위 숫자를 미래 수락 결과로 사용하지 않는다.

## 3. 권고 A: 검증된 권위와 조회를 분리

### 3.1 바꾸는 보장과 유지하는 보장

임의의 H개 본문 중 어디든 같은 stamp·같은 길이로 변조할 수 있고, 외부 변경 통지까지 누락될 수 있다고 가정하면, **매 요청에서 모든 변조를 즉시 검출하는 보장과 본문을 읽지 않는 O(1) 조회를 동시에 제공할 수 없다.** 디렉터리 mtime·hash 목록·watcher만으로 이 차이를 없앴다고 하지 않는다. hash 목록 자체를 매번 전체 대조하면 다시 O(H)다.

권고는 **검증 유효기간을 둔 정확한 메모리 색인**이다. 임의의 같은-stamp 변경을 다음 Job에서 즉시 검출한다는 기존 전역 보장을, 열기/복원/명시 검사 시 전체 검증 + 실행 중 제한된 검증 유효기간으로 바꾼다. 이는 시험 최적화가 아니라 무결성 정책 변경이며 **C00의 명시 승인 없이는 구현하지 않는다**.

- 정상 삭제 API가 받아들인 의도는 같은 프로세스의 세션별 fence에 즉시 반영한다. 의도 뒤 새 append·seal·등록·Job 입장·게시 0이라는 I1은 완화하지 않는다. 영속 의도 전에는 미디어를 제거하지 않는다.
- 검증된 tombstone의 정확한 ID·최대 세대는 메모리에 유지한다. 디스크 항목이 지워지거나 깨져도 이전에 삭제된 ID가 허용 집합으로 돌아가지 않는다. 불명은 빈 집합이 아니다.
- 유효기간 안에서 통지 없는 **다른 항목의** 손상은 아직 발견되지 않을 수 있고, 삭제되지 않은 세션의 Job 입장이 허용될 수 있다. 이 창을 0초라고 주장하지 않는다. 새 외부 삭제 의도의 제자리 주입 역시 통지 없이 즉시 검출한다고 보장하지 않는다.
- 단일 정상 writer의 OS 소유권 잠금·협력 API를 전제로 한다. 동일 권한 악성 프로세스가 DB·manifest·이력을 함께 바꾸거나 과거 root 전체를 되돌리는 공격을 hash만으로 인증하지 못한다. 외부 삭제 API를 새로 허용하지 않으며, 지원되지 않는 동시 외부 편집은 발견 시 보류한다.
- 이 창을 허용할 수 없다면 §10 B안(요청마다 전체 검증)을 유지한다. 파일을 압축해 상수를 줄일 수는 있어도 Job의 H 독립 비용은 보장하지 못한다.

### 3.2 권위 receipt와 검증 수명

기본 제안: **검사 요청 간격 5초, 최대 유효기간 L=30초**. 정확한 숫자는 제품의 무결성 검출 지연을 정하는 C00 결정 항목이다. 30초가 디스크 검사 완료 시간 보장은 아니다.

Library가 소유하는 불변 receipt는 root 정체성·실행 instance·history_version·관찰 세대·검증 cut·검사 시작 monotonic/UTC 시각·검증된 정확 집합의 버전을 결속한다. 파일 내용·경로·세션 ID를 로그나 진단으로 복제하지 않는다. 메모리 구조는 실행 전용이며 SQLite에 유효한 권한으로 저장하지 않는다.

1. 열기/재열기/복원/명시 검사는 전체 canonical 이력과 DB 권위를 worker에서 검증한다. 검증 완료 전 receipt는 없음이다. 창은 ‘삭제 이력 확인 중’으로 먼저 표시할 수 있으나 Job·복구·확정·내보내기 등 이력 의존 동작은 보류한다. 자동 복구/재전송은 하지 않는다.
2. 만료는 **검사 시작 시각**부터 센다. 끝난 시각부터 새 30초를 주지 않는다. 검사에 30초 이상 걸렸다면 성공 결과라도 현재 허용 receipt가 될 수 없다. 검사 중 최신 정상 쓰기 delta를 검증해 이어 붙일 수 있는 일관된 cut을 사용한다.
3. 판단할 때 두 시계의 경과를 확인한다. monotonic 역행·UTC 역행/불일치·절전 재개 통지·관찰 불연속·root 교체·종료는 무효다. worker가 밀려도 timer가 마지막 성공을 계속 연장하지 않는다. 유효기간이 끝나면 해당 호출은 즉시 HISTORY_UNAVAILABLE이며 GUI에서 동기 재검사를 하지 않는다.
4. 정상 writer의 원자 갱신은 history_version과 자기 ID의 정확한 상태를 O(1)~O(log H)로 수정한다. **전체 본문을 읽지 않은 갱신은 전역 검증 시작 시각을 갱신하지 않는다.** 계속 삭제한다고 이전 손상 검사 시한이 무한히 미뤄지지 않는다.
5. stamp 변화·watcher 사건·overflow·통지 중단은 신속한 무효화/재검사 힌트다. watcher의 ‘사건 없음’은 검증 증명이 아니다. 파일명 변경 통지와 자기 원자 게시를 version/cut으로 구분하되 외부 사건을 자기 쓰기로 흡수하지 않는다. watcher가 없어도 유효기간 검사는 동작한다.
6. 같은 stamp 손상을 deep 검사에서 발견하면 전역 관리 권위는 보류한다. 수선 뒤 **명시 fresh 검증 성공**으로만 회복한다. 오래된 성공·실패 관찰이 새 결과를 덮지 못한다. GS-P02의 실패 cache는 실패를 빠르게 돌려줄 수 있으나 성공 receipt를 발급하지 않는다.
7. G15R-05의 settle 기준은 별개다. 이름 목록 **전** 시각·동일 stamp/version/관찰 세대를 유지한다. settle은 메타데이터 관찰의 안정성이고, 같은-stamp 본문 검증 유효기간을 대신하지 않는다.

전체 감사는 기존 관리 worker/control lane에서 합쳐 한 건만 수행한다. capture callback·submit·writer·sealer에서 감사 예약/DB 쓰기/검사 대기를 하지 않는다. 정상 쓰기 때문에 감사가 영구히 취소되지 않게, 검사 대상의 고정 cut과 이후 신뢰된 delta를 대조한다. 최종 대조에서 version이 맞지 않으면 허용을 연장하지 않고 bounded 재시도/보류한다. Library의 기존 SQLite 연결을 여러 스레드에서 root 없이 동시에 사용하지 않는다. receipt·감사 시각·검증 정책은 실행 권위 metadata이며 결과 config_key에 넣지 않는다.

### 3.3 입장·종료·게시와 녹음 경계

| 경로 | 새 계약 |
| --- | --- |
| claim·reader_started·block_pending·resume | 짧은 root 구간에서 receipt 유효성 + 해당 세션 DB/색인 최대 세대 + Job 결속 확인, 기존 root → Job transaction 순서 유지. 본문 읽기/열거/해시 0. |
| fail/reader 종료 등 실제 종료 ACK | 권위 불명으로 worker 정리를 막지 않는다. 기존 acknowledgement 의미 유지. ACK가 새 입장·재전송·결과 게시 권한을 만들지 않는다. |
| 결과 게시 | 기존 세션 삭제 fence를 유지하고 권위 보류 상태에서는 새 게시를 하지 않는다. Job 잠금을 잡기 전에 권위 lease를 얻는 공개 경계로 연결한다. 단순 complete와 publisher 경로를 각각 시험하며, publisher 안에서 전체 감사 또는 Job → root 취득을 하지 않는다. |
| 이미 시작된 원격 요청 | 동의·비용·자기 세션 삭제 fence·UNKNOWN 보존을 그대로 유지한다. 감사 유효기간 만료를 동의 철회/미전송 증명으로 해석하지 않으며 자동 재전송하지 않는다. 전역 receipt는 새 Job 입장과 새 결과 게시의 조건이다. 이 계약은 만료 시 이미 발급된 모든 원격 write를 소급 취소하는 새 보장을 추가하지 않는다. |
| capture append·seal·등록 | 전역 감사 실패 cache/유효기간 때문에 다른 세션의 진행 녹음을 중단시키지 않는다. 자기 삭제 의도·자기 권위 불명은 기존 fence대로 거부한다. 전역 손상 시 신규 녹음의 입장 정책은 기존 자기 세션 검증을 유지하며, 편의를 위해 이력 전체를 빈 값으로 대체하지 않는다. |
| 관리 조회·복구·확정·export·retention | 정합이 필요한 동작은 유효한 receipt와 자기 세션 재검사를 요구한다. 오래된 화면 결과를 실행 권한으로 쓰지 않는다. 삭제 대기·tombstone·claim·live 거부를 약화하지 않는다. |

닫힌 외부 오류는 기존 `DELETION_HISTORY_UNAVAILABLE`/`HISTORY_UNAVAILABLE`을 유지하고, 화면의 확인 중·검사 필요·권위 보류는 read model로 구분한다. 예외 원문·절대 경로·본문을 표시하지 않는다. 코드 추가가 필요하면 구현 전 G-P07/G-P12 표시 표와 함께 C00에 요청한다.

## 4. 정상 경로 비용과 GUI 계약

### 4.1 H·S·P·k를 구분한 복잡도

H=영구 삭제 이력 ID 수, S=현재 일반 목록 대상 세션 수, P=삭제 대기 수, k=한 페이지 행 수(상한 **128**), D=현재 증분 log 크기다. 파일 시스템·SQLite·디스크 지연 자체가 상수 시간이라고 보장하지 않는다.

| 동작 | 권고 비용·필수 구조 |
| --- | --- |
| 유효 receipt의 자기 Job 권위 | 정확 메모리 map 조회 평균 O(1) + DB PK 조회 O(log(H+S)). H개 파일 열기·행 수집·dict 복사·전체 이름 목록 0. |
| 목록 한 페이지 | keyset cursor와 적절한 가시 행 index로 O(log S+k), 숨겨진 삭제 이력 H 전체를 읽지 않음. 단순 OFFSET 또는 전체 목록을 만든 뒤 잘라 반환하는 구현은 불합격. |
| list_sessions 호환 전체 반환 | 출력 하한 O(S)를 인정한다. H 독립이며 GUI thread에서는 호출하지 않음. CLI의 전체 출력도 worker/호출자 제어 경로에서 스트리밍 페이지로 처리. |
| 한 삭제의 게시·완료·retry | 자기 키·최대 세대만 조회/갱신. O(H) snapshot dict 복사·deleted_sessions 전체 set 작성·감사 강제 실행 0. 전경 요청들의 누적 작업량은 O(H log H) 이하 목표이며 감사 총비용과 구별. |
| 전체 감사·압축 | O(H+D) 순차 검증/처리. 요청마다 실행하지 않음. RAM은 정확한 이력 때문에 O(H)를 수용하며, 메모리 한계는 무검증 허용 대신 보류/명시 정비로 안내. |
| pending 목록 | 출력 P의 비용은 남음. 완료 H를 다시 읽지 않는 별도 상태 index/페이지. 같은 세션 최대 세대·DB/journal 합집합 규칙은 유지. |

DB-only·journal-only·양쪽 이력은 정확 map/PK로 함께 판정한다. 완료 ID의 Bloom filter만으로 권위를 대신하지 않는다. 목록 SQL에 삭제 상태 NOT EXISTS를 쓰면 각 키 조회가 PK임을 query plan으로 확인하고, 숨겨진 대량 행을 LIMIT 앞에서 선형 건너뛰지 않도록 가시성 index를 원자 갱신한다. 가시성 index는 파생물이며 깨졌다고 삭제된 세션을 표시/채택하면 안 된다.

**잔여 하한:** 고정 주기로 모든 본문을 재검증하면 감사 한 번은 O(H)이고 실행 전체 비용은 `Σ O(H_at_audit)`다. 이력이 계속 늘어나는 긴 실행에서는 그 합이 제곱으로 늘 수도 있다. A안이 이를 O(1)로 없앴다고 하지 않는다. 이번 목표는 요청마다 중복하던 전경 O(H)와 GUI/root 보유를 제거하고, 감사는 합친 worker 작업과 순차 pack 읽기로 줄이는 것이다. 전경 시간·감사 bytes·감사 포함 총 삭제 시간을 따로 보고하며, 유효기간을 무단 연장하거나 감사를 누락해 총량을 숨기지 않는다. 고정 검출 지연과 임의 크기 이력의 전체 감사 비용까지 동시에 상수화하는 요구는 수락하지 않는다.

권고 내부 API는 `authority_view(session_id)`와 `session_page(cursor, limit, expected_catalog_version)`다. 외부 Job용 context manager는 기존 `Library.job_authority`를 유지해 root → Job 원자 경계를 보존한다. UI/JobStore가 private parser·journal·두 번째 root lock을 복제하지 않는다. cursor는 root instance·catalog version·마지막 키·필터를 결속하고 세대가 다르면 stale로 재조회한다. cursor는 권한이나 삭제 근거가 아니다.

### 4.2 GUI와 시작 경로

- MainWindow 생성과 세션 선택·tick·refresh에서 전체 journal/DB scan/감사/파일 읽기 0. 필요하면 준비된 Library handle과 비활성 read model로 창을 먼저 만들고 Task가 초기 검증을 끝내도록 한다. 일반 녹음 시작 권한을 준비 전 임의로 열지 않는다.
- G-P04 inventory·G-P05 pending의 worker/queued signal/세대 패턴을 재사용한다. 한 종류의 목록 조회는 실행 1개 + 최신 요청 1개로 합친다. 취소했다고 작업 thread가 종료했다고 가정하지 않는다.
- 결과는 root instance·조회 generation·선택 ID를 검사해 GUI thread에 반영한다. 늦은 완료·실패가 새 목록/다른 root를 덮지 않는다. 검사 중에는 ‘확인 중’, 실패하면 ‘삭제 이력 확인 불가 — 검사/수선 필요’와 마지막 성공 행의 미확인 표시를 유지한다. 빈 목록 성공으로 바꾸지 않는다.
- 한 GUI callback에서 최대 k행만 구성한다. 다음 페이지·키보드 선택은 비차단이고, 동일 ID의 재통지는 G-P02의 LIBRARY 동의 선택을 초기화하지 않는다. 실제 행 제거는 AI 고정 작업의 fixed_session 판단과 분리한다.
- 전체 검사는 worker의 명시 ‘이력 다시 검사’로 요청한다. 손상 수선은 링크 제거·권위 백업 대조 등 실제 조치 안내로 구분하며, ‘초기화/이력 지우기’ 버튼으로 복구하지 않는다. 진단에는 안전한 상태/건수/시간만 남긴다.

## 5. 완료 tombstone의 손실 없는 압축 표현

### 5.1 정본과 파생물

권고: **완료 이력의 불변 정렬 pack + 순서가 있는 증분 log + manifest**. 첫 단계 GS-P11a/b는 기존 format 1 파일을 유지하고 조회만 개선한다. 아래 저장 형식은 GS-P11c에서 G-P09 migration/backup을 승계한 뒤 별도 승인·구현한다.

첫 판의 pack은 UTF-8 JSONL, 공통 header 1행 + 정렬된 정확 record이며 `codec=none`으로 고정하는 안이다. 공통 schema/lineage 반복과 개별 파일 수를 줄이는 집약 표현이고, byte 압축률을 약속하지 않는다. byte codec을 추가하려면 별도 decoder/크기 한도 계약을 승인받는다. manifest는 `schema_version=2`, history identity, cut sequence, pack ID·정확 bytes·레코드 수·SHA-256, delta ID·시작 sequence, operation ID를 갖는다. 참조는 지정 디렉터리의 닫힌 ID→파일명 규칙으로만 만들고 임의 경로·부모 이동·reparse를 허용하지 않는다. pack/log header의 history identity와 cut을 manifest와 대조한다. 줄별 길이·정수 타입/범위·전체 예상 bytes/개수를 검사하며 bool을 generation으로 받지 않는다. 알려지지 않은 codec/필드는 미래 형식 정책으로 보류한다. G-P09a의 실제 component 규격과 타입 한도는 착수 때 재대조해 고정한다.

논리 키는 `(원본 library lineage, session_id)`이며 값은 최소한 최대 generation, DELETE_REQUESTED/완료 여부, 권위 출처·필요한 완료 증거 참조다. 현재 journal에 없던 생성 시각·완료 시각을 추정해 만들지 않는다. 완료 flag는 원본 제거·reader/sealer ACK·DB 봉인이 증명될 때만 올린다. pending을 파일이 없다는 이유로 완료 pack에 넣지 않는다.

- 기존 deleted_sessions DB는 독립 권위로 보존하고 journal pack/log와 **합집합·최대 세대**로 대조한다. 세션 generation이 권위보다 높으면 conflict이며 허용으로 계산하지 않는다.
- 단순한 gzip 묶음만으로 random lookup이 빨라진다고 주장하지 않는다. pack은 정확 레코드·버전·길이·건수·정렬 키·내용 digest를 갖고 검증 후 정확 색인을 만든다. 압축 codec은 선택 사항이고 bounded decoder/크기 한도를 요구한다. 먼저 레코드 pack으로 파일 수를 줄이고 byte 압축률은 측정한다.
- log는 연속 sequence·이전 cut 결속·레코드 길이·검사값으로 prefix를 확인한다. 잘린 tail·중간 누락·중복 충돌·미래 형식은 미완성/보류이지 정상 빈 이력이 아니다. 정상 반복 record는 같은 값의 멱등만 허용한다.
- 세션 ID를 버리고 건수/hash만 남기거나, 충돌 가능 확률 집합으로 대체하거나, 기간 만료로 삭제하지 않는다. 이미 존재하는 최소 논리 기록을 불필요하게 확장해 원문·비밀·절대 경로를 추가하지 않는다.
- manifest/pack/log/진행 journal은 **새 canonical 구성요소**다. RAM map·가시성 SQL index·watcher·receipt·mtime cache는 파생물이다. 양자를 backup/retention 규칙에서 혼동하지 않는다. digest는 전송/저장 손상 검출이고 출처 인증·전체 rollback 방지 서명은 아니다.

### 5.2 생성·게시·재시작

압축 cut C를 고정한 뒤 worker에서 새 pack을 만든다. 신뢰된 정상 삭제의 delta는 C 뒤에 이어진다. 구 표현과 신 표현의 **정확한 키·최대 세대·상태·필수 증거가 같음**을 독립 비교한 뒤에만 manifest를 바꾼다. 개수만 같거나 제품 hash 함수 두 번이 같다는 조건으로 승인하지 않는다.

권고 첫 버전은 **명시 유지보수에서만 최종 전환**한다. live 상태에서 준비/검증은 가능하나 source·writer·sealer·reader 실제 ACK 전에는 manifest 전환/구 정본 제거를 하지 않는다. 자동 정지를 하지 않고 BUSY/사용자 취소를 허용한다. 따라서 ‘녹음 중 압축 성공’ 측정은 준비 비용과 최종 전환을 구분한다. 온라인 최종 교체는 별도 대안이며 첫 구현에 넣지 않는다.

단계는 PLAN → PREPARED → PACK_WRITTEN → VERIFIED → MANIFEST_COMMITTED → OLD_RETIRED → DONE이다. 유지보수 operation journal에 cut·구/신 구성요소·기대 세대를 남긴다. 새 manifest를 마지막으로 원자 게시하고, 새 정본의 영속 완료·검증·참조 reader ACK 전에는 구 파일을 제거하지 않는다. 중단 후 구/신 중 완전성이 증명되는 권위 또는 보수적 합집합으로 재개한다. 어느 쪽도 증명 못 하면 QUARANTINED다. 임시 파일을 보고 기존 정본이 없다고 간주하지 않는다.

삭제 의도 자체의 내구성을 G-P17b 음성 BATCHED 설정으로 완화하지 않는다. 삭제의 세션별 fence 예약 → 의도 영속 게시 → DB/메모리 반영의 순서를 유지하고, 실패/부분 commit 뒤에는 거부를 보존한다. 무거운 fsync/해시/전체 map 복사를 root 안으로 옮기지 않는다. 기존 공유 SQLite 연결을 잠금 밖에서 몰래 쓰는 방식은 금지하며, G-P17a의 제어 수명과 G-P09a 유지보수/persistence 경계 위에서 정확한 cut을 게시한다. 이 범위에서 지키지 못하면 먼저 SCOPE_NEEDED를 보고한다.

구형 앱이 pack을 모르는 상태로 writer를 시작하면 안 된다. G-P09 형식 2와 deletion-history component 버전으로 구버전 쓰기를 사전 차단한다. `_coordination.check_write_allowed`의 Library 없는 fallback도 pack/log/DB 권위를 읽거나 지원 불가로 거부해야 한다. ‘개별 sid.json이 없음 → 의도 없음’으로 통과시키지 않는다.

### 5.3 G-P09·G-P14 인계

| 단위 | 반드시 승계할 경계 |
| --- | --- |
| G-P09a schema/migration | 삭제 이력 component의 v1 개별 파일 → v2 pack/log/manifest 전환과 operation journal을 버전 목록에 추가. 미래/부분 형식 무변경·명시 재개·구버전 차단. 승인된 G-P09 계약에 자동 포함됐다고 간주하지 않고 개정 인계. |
| G-P09b backup/restore/import | 같은 정지 cut의 deleted_sessions·manifest·모든 참조 pack·유효 delta·진행 이력 포함. pending-only backup 금지. receipt/색인은 복원하지 않고 전체 검증해 새로 생성. source lineage는 새 root/실행 ID와 별개로 보존. 현재 삭제 권위와 최대 세대로 대조하여 오래된 backup이 삭제 원본을 되살리지 못하게 하고, 완전성 불명은 QUARANTINED. 비용 ledger/witness/high-water는 기존 별도 정본 그대로 보존. |
| G-P14 retention | tombstone·삭제 의도·필수 진행 이력은 KEEP/TTL 제외. 압축 후 중복 물리 파일을 검증된 교체로 retire하는 것은 논리 tombstone 삭제가 아님. 필수 ID/세대를 잃는 정리 금지. 현재·진행 backup이 참조하는 pack은 임의 축출하지 않음. |
| G-P17a/b·G-P08 | capture의 자기 삭제 fence와 종료 ACK/건강 미상 보존. 전역 감사·압축 오류 때문에 원본 녹음을 멈추거나 UNKNOWN_TAIL을 0으로 바꾸지 않음. 오디오 내구성 watermark와 삭제 정본 checkpoint는 다른 receipt. |
| GS-P01·G-P12·G-P16 | 목록 read model/worker 소유권을 직렬화. 진단/표시 변경이 동의·비용·장치 정책 snapshot/config_key를 바꾸지 않음. |

압축 후에도 원래보다 최신 권위가 사라진 전체 root rollback을 단독 backup의 자체 hash만으로 증명할 수 없다. 현재 권위/외부 보관 증거가 없으면 완전성을 주장하지 않는 G-P09 결정을 유지한다.

## 6. 경우의 수·계획 분모

`docs/testing/case-space.md` 방식의 **계획 F=703행**이다. family tag로 구분한 후보 공간 Ω는 739행이고, E의 no-op에서 도달하지 않는 checkpoint 36행을 제외한다. 제품 시험 실행 수가 아니다. 각 family는 독립 ID `GS11-<family>-<번호>`를 쓰며 생성 기대값은 제품 parser/cache/판정 함수를 가져오지 않는다. H=0인 정상 빈 이력도 이력 파일/DB 존재 검증은 필요하다.

| family | 입력 분할·feasible 곱 | F | 단위 |
| --- | --- | ---: | --- |
| A 무결성·검출 시점 | 아래 A12 × 시점5(최초 열기/유효기간 안/만료/감사 worker 지연/재열기) × 관찰3(claim/목록 page/명시 검사) | 180 | 11a |
| B 권위·동작 | B14 × 동작7(claim/reader_started/block_pending/resume/fail ACK/단순 complete/publisher) | 98 | 11a |
| C 순서 | C8 순서 × 경합 상대3(정상 삭제/감사 완료/수선) × 조회 시작 receipt 유무2 | 48 | 11a |
| D 화면 | 자료6(빈/일반/대기 혼합/큰 현재 목록/큰 과거 삭제 이력/권위 보류) × UI열5(새로고침/선택 변경/조회 역전/root 교체/닫기) × 결과2(성공/실패) | 60 | 11b |
| E 압축·중단 | 전환 자료8 × E11 checkpoint × 재시작2 + no-op 자료2 × 도달 checkpoint2 × 재시작2 | 184 | 11c |
| F 형식 음성 | F11 잘못된 표현 × 진입3(일반 open/Library 없는 writer/명시 검사) | 33 | 11c |
| G 인계 | G8 자료 × 동작3(full backup/restore/import) | 24 | 11c |
| H 녹음 병행 | H4(삭제 0/100/1000/10000) × 트랙2(1/2) × 관리4(Job 전이/페이지 목록/삭제 연속/압축 준비) | 32 | a16/b8/c8 |
| I 누적 작업량 | H4 × 작업3(반복 hot Job/목록 페이지/연속 삭제) | 12 | a8/b4 |
| J 유효기간 | J8 시각 경계 × 사건4(무통지/정상 의도 게시/watcher overflow/늦은 감사 완료) | 32 | 11a |
| 합계 | 180+98+48+60+184+33+24+32+12+32 | **703** | a382/b72/c249 |

A12는 정상, malformed JSON, 같은 길이·같은 stamp의 유효 JSON 값 변조, 파일 누락, 외부 의도 추가, journal 디렉터리 누락, 미완성 tmp, reparse/link, DB 권위 손상, 미래 schema/sequence, watcher overflow만 발생, 읽기 I/O 실패다. 삭제된 자기 ID와 무관한 ID 두 관측을 한 행에서 함께 단언한다. 외부 의도 추가/변조의 디렉터리 및 파일 stamp 복원도 명시한다. 손상 사실을 미리 기대표에 넣되 제품에 알려 주지 않은 행과 통지를 준 행을 구별한다.

| 독립 입력 사실 | claim/목록에 쓰는 권위 기대 | fresh 검사 기대 |
| --- | --- | --- |
| 정상 전체 검증 완료·유효기간 안·현재 root | 일반 ID VALID, 이미 삭제된 ID 거부 | 성공해 시작 시각이 결속된 새 receipt |
| 유효기간 안·아직 통지/검사하지 않은 같은-stamp 본문 변경 | 이전 일반 ID는 허용될 수 있음. 이전 삭제 ID는 계속 거부. 이를 즉시 검출한 PASS로 세지 않음 | 변경/손상 검출 후 보류, 원래 값으로 제자리 수선해도 자동 허용하지 않음 |
| 통지/metadata 변화로 무효화 또는 최초/만료/worker 지연 | 새 receipt 게시 전 HISTORY_UNAVAILABLE, UI는 미확인 | 정상 자료면 새 검사 시작 기준으로만 발급, 손상/지연 초과면 발급 0 |
| malformed/tmp/link/DB 손상/미래 형식을 실제 검사해 발견 | HISTORY_UNAVAILABLE, 성공 빈 목록 0 | 거부, 닫힌 분류·기존 권위 보존 |
| watcher overflow만 있고 본문은 정상 | 사건을 받은 뒤 검사 완료 전 보류 | 새 전체 검사와 cut 대조 뒤에만 회복 |

유효 JSON의 의미 변경은 이전 검증 digest/cut과 대조한다. 외부 변경 값을 새 정상 의도처럼 자동 승격하지 않는다. 단, 초기부터 DB·파일·증거 전체가 함께 일관되게 바뀐 상태는 독립한 과거 증거 없이 원 진위를 인증할 수 없다는 §3.1의 한계가 있다.

B14는 VALID, DB-only pending, journal-only 의도, 양쪽 같은 세대 pending, 완료 tombstone, DB가 더 최신, journal이 더 최신, 세션 세대가 더 최신, 세션 소실, 전역 미검증, receipt 만료, 감사 실패, root 교체 receipt, 같은 값 반복 record다. 동작별 전제 Job을 별도로 만든다. 단순 complete가 지금 권위 경로를 안 거친다는 사실을 숨기지 않고, 새 게시와 종료 ACK의 차이를 명시 기대표로 고정한다.

C8은 각각 Event barrier로 고정한다: 조회 전에 변경 완료, snapshot 뒤 root 재확인 전에 변경, root lease 중 변경 대기, 무효화 뒤 이전 감사 완료, 새 감사 완료 뒤 옛 감사 완료, 실패 뒤 수선 완료, 수선 뒤 옛 실패 완료, close/root 교체 뒤 결과 완료. 가능한 선후관계만 정의한 8개 schedule이며 모든 thread interleaving 전수라고 하지 않는다. 상대가 삭제/수선/감사일 때 해당 mutation과 원자점이 다른 것은 행의 기대표에서 구분한다.

E의 자료10은 빈 이력, 완료 1개, 완료 다수, pending만, 완료+pending, 같은 키의 여러 세대가 든 정상 이력, 기존 pack 재압축, 기존 pack+정상 delta, 완료 pack+pending delta, 다른 lineage의 같은 session_id다. 빈/pending-only는 no-op 계획이므로 E01(계획 전)·E11(no-op 완료 뒤)만 도달하며 각각 재시작2를 적용한다. 나머지 8자료는 완료 레코드를 포함하고 완전성이 검증된 입력으로 고정해 E11 지점에 도달한다. 도달하지 않는 36조합은 실행 행으로 부풀리지 않는다. DB-only/journal-only·손상·불일치로 전환 자체를 보류해야 하는 음성은 B/F/G에서 별도로 검사한다. 도달성을 만들려고 제품이 불명 이력을 임의 수선하게 하지 않는다.

F11은 manifest 누락, pack 누락, digest 불일치, 중복 키 충돌, 감소 generation, delta sequence 틈, delta tail 잘림, 미래 component, reparse 경로, 허용 크기 초과, 구 앱/새 형식 조합이다. codec이 도입되면 decoder 팽창 한도 음성을 이 목록의 허용 크기 초과 행에 포함하되 별도 확대 시 분모를 다시 보고한다.

G8은 정상 완료, pending 포함, 원본보다 최신 현재 tombstone, DB/journal 불일치, 부분 전환, 미래 형식, 삭제 권위 부재, 비용 정본 불일치다. project bundle은 전체 권위가 아닌 NOT_INCLUDED 정책을 별도 상수 oracle로 검사하고, 해당 workflow를 추가 구현 범위로 넓히면 G family를 개정한다.

J8은 `(monotonic age, UTC age)`의 `(0,0)`, `(L−1,L−1)`, `(L,L)`, `(L+1,L+1)`, `(−1,정상)`, `(정상,−1)`, `(정상,L+1)`, `(L+1,정상)`이다. 정확히 L은 만료다. 숫자는 시험용 ns 정수이며 30초 sleep을 하지 않는다. 같은 stamp metadata settle 경계의 기존 GS-P02 시험은 별도로 유지한다.

703은 한정된 분할의 feasible 계획이지 모든 OS·DB·시각·GUI 상태의 전수 곱이 아니다. 손상 입력은 거부 사례이므로 F에서 제외하지 않는다. power loss의 실제 물리 persistence, HDD/백신/네트워크 파일 시스템 전반, 임의 악성 동시 writer는 이 분모에 포함하지 않는다. 관리 경로는 로컬 지원 root를 사용하고 네트워크는 실행하지 않는다.

## 7. 독립 oracle·중단 지점·기존 시험

### 7.1 독립 oracle

시험 fixture가 손으로 만든 `(lineage, ID) → 최대 g/요청됨/완료/증거` 사전과 Event 순서 기록을 정본 기대값으로 가진다. 제품 manifest/index/parse 결과에서 expected를 만들지 않는다.

1. 삭제 ID와 최대 세대는 어떤 재시작·압축·복원 뒤에도 줄지 않는다. DB-only/journal-only를 합치고, 충돌은 보류한다. 관리 성공 표시는 모든 필요한 단계를 실제 마친 경우뿐이다.
2. 정상 writer의 의도 fence 뒤 자기 세션 append·seal·등록·입장·게시 0. fence 전에 받아들인 PCM은 저장량/건강 QUEUE_DROP 회계로 보존한다. 다른 세션의 감사 실패가 기존 녹음을 끊지 않는다.
3. 유효기간 안 무통지 손상의 관측 허용과, 만료/명시 감사 뒤 보류를 기대표에서 구분한다. ‘기존 tombstone 부정 결과 유지’와 ‘아직 안 본 외부 손상의 즉시 검출’을 혼동하지 않는다.
4. hot Job/페이지당 본문 bytes/파일 열기/전체 행 fetch/전체 dict copy 계수를 계측한다. 값이 H와 비례하면 wall time이 빨라도 불합격. 관리자 root·Job lock/transaction 안 열거·해시·pack decode·전체 SQLite scan 0.
5. GUI thread에서 worker를 Event로 멈춘 채 선택·refresh·tick이 완료해야 한다. Qt 객체 반영은 GUI thread이고 stale 결과는 적용 0. 성공 0건과 실패/미조회는 다르다.
6. 압축 전후 정확한 사전·필수 근거가 같다. 개수/hash 일치만으로 승인하지 않는다. 실패 주입 후 원본 바이트·삭제 권위·비용 노출은 줄지 않는다. backup 목록은 manifest의 canonical 구성요소와 실제 bundle 목록으로 대조한다.

### 7.2 E11 크래시 checkpoint

| 번호 | kill/실패 주입 위치 | 재시작 oracle |
| --- | --- | --- |
| 01 | 계획 확인 전 | 원본 권위 불변, 자동 압축 0 |
| 02 | PREPARED 기록 뒤 | 명시 재개/안전 롤백, 권위 감소 0 |
| 03 | pack 본문 중간 | 불완전 pack 미채택, 구 권위 유지 |
| 04 | pack 쓰기 끝·내구성 ACK 전 | 완료 영속이라고 단정하지 않음 |
| 05 | pack ACK 뒤·독립 대조 전 | 검증 전 새 manifest 게시 0 |
| 06 | VERIFIED 뒤·quiescence 전 | live/reader면 전환 대기, 강제 종료 0 |
| 07 | delta cut 대조 중 | 누락 prefix를 완료로 채택하지 않음 |
| 08 | manifest 임시 게시 중 | 구/신 중 완전한 권위 또는 보류 |
| 09 | MANIFEST_COMMITTED 뒤·retire 전 | 구/신 중복을 멱등 병합, 논리 tombstone 유지 |
| 10 | 구 파일 retire 중 | 새 정본 검증, 삭제 ID 재허용 0 |
| 11 | DONE 직후 | 재실행 멱등, 같은 정본·다음 감사 새 receipt |

합성 persistence injector는 fsync/rename의 프로그램 순서와 재개 모델을 검증한다. 실제 전원 장애·컨트롤러 cache·directory entry 내구성 보장은 Windows 장치 외부 게이트이며 위 성공으로 대체하지 않는다.

### 7.3 기존 시험과의 관계

- `test_in_place_corrupt_history_is_not_hidden_by_an_unchanged_directory_index`는 삭제하지 않는다. C00 승인 뒤 ‘유효기간 중 이전 정확 tombstone은 계속 거부 → fresh 검사/만료 후 모든 새 입장 보류 → 수선 fresh 성공’으로 **검출 시점 기대를 명시 개정**하고, 같은 즉시 거부가 필요한 정상 API 의도 게시 시험을 나란히 유지한다.
- `test_authority_enumeration_is_outside_root_job_transaction_and_job_lock`과 G-P15/GC-P02의 구조 시험은 약화하지 않는다. settled 실패 cache·목록 전 시각·같은 tick·미래 mtime의 GS-P02 280행도 유지한다.
- G-P04/G-P05 worker·늦은 조회·live/delete pending·tombstone 시험, G-P07 권위 불가·ACK·계속·UNKNOWN, G-P08 건강 미상/원본 보존, G-P17a 삭제 fence 시험을 회귀에 포함한다.
- 기존 시험 fixture가 새 초기 검증 상태를 준비해야 하면 실제 실패와 최소 diff를 먼저 C00에 보고한다. 아래 명시한 기존 G-P07 시험 외의 기대값은 선승인 없이 수정하지 않는다.

## 8. 성능 측정·수락·시간 예산

### 8.1 H/I 측정 계획

H=0/100/1000/10000에서 현재 세션 S=32·대기 P=8을 고정한다. cold open/전체 감사와 warm 전이를 별도 기록한다. 정확히 H개의 합성 최소 tombstone을 미리 만들며, 각 삭제의 순차 실행 비용을 재는 I-delete는 준비 시간을 제외하고 **실제 공개 API의 추가 삭제**를 측정한다. 공개 API 전후 권위 사전을 함께 검증한다.

- Job은 claim·reader_started·block_pending·resume·fail ACK와 단순 complete 대조를 따로 측정한다. 평균 하나로 합쳐 차이를 숨기지 않는다. 각 warm 표본 최소 100회, median/p95/p99/max·본문 bytes·file open·SQL row·map-copy 작업량을 기록한다.
- page는 k=128, keyset 처음/중간/끝, 선택 유지와 실패를 측정한다. 별도 기술 측정으로 S=32/1000/10000의 페이지·전체 반환 시간을 기록해 O(S) 출력 비용을 H 비용으로 오해하지 않는다. 이 추가 S 측정은 703 canonical 분모 밖의 `GS11-X-PAGE-*`로 감사한다.
- 합성 PCM 48kHz·480frame, 1/2트랙으로 수락·저장·거부·건강 회계를 검사한다. 관리 동작은 원본 bytes와 트랙 분리를 바꾸지 않는다. 녹음/부가 관리 각각의 root 보유 시간을 thread별로 분리한다.
- 관리 I/O에 50/500ms 지연을 주어 GUI/Job의 hot 조회가 이를 기다리지 않는지 Event/구조 oracle로 확인한다. 10,000행 순회 자체를 작은 입력으로 바꾸어 빠른 척하지 않는다.
- 압축은 ‘녹음 중 준비/검증’과 ‘실제 종료 ACK 뒤 최종 전환’을 분리 기록한다. 1/2트랙 중 최종 교체를 강행하지 않는다. 폐기 bytes/파일 수, peak RAM, 증분 크기, 감사 전체 지연을 함께 기록한다.

### 8.2 수락 기준

| 항목 | 필수 기준·측정 목표 |
| --- | --- |
| H 독립 hot 조회 | Job 권위당 전체 journal body 읽기/열거/전체 tombstone fetch/전체 map 복사 **0**. 페이지는 반환 k와 query plan으로 한정. 관리 스레드의 root 안 전체 순회/해시/직접 파일 fsync/worker ACK 대기 **0**. 기존 짧은 SQLite transaction commit 시간은 별도 측정하며 이를 무I/O라고 부르지 않음. |
| 시간 목표 | 이 PC warm 권위 전이 p95≤10ms/p99≤25ms, GUI 조회 요청 callback≤16ms를 초기 목표로 제안. Job transaction 자체 commit·OS 지연은 별도 항목으로 기록하고 원인 귀속. 미달하면 구조 PASS만으로 완료 처리하지 않고 측정값/대안을 C00에 보고. |
| GUI 구조 | 실제 파일 검사 worker를 멈춰도 GUI callback은 반환. 전체 목록/widget 생성 대신 bounded page. 실패/늦은 결과의 허용·빈 목록 오표시 0. |
| 녹음 | 1/2트랙 거부 0 목표. CI에서는 writer 자체 디스크 부하에 따른 QUEUE_DROP을 측정값으로 두되 **수락한 PCM 보존·거부 회계·관리 스레드 장기 root 보유 0**은 단언. 관리가 mutex를 쥔 채 500ms 멈추는 변이는 반드시 검출. |
| 누적 삭제 | 완료 H가 늘어도 각 전경 삭제의 전체 이력 읽기/복사 0. 전경 논리 레코드 처리량은 O(N log N) 이내이며 H² 작업 계수 금지. 메타데이터 영속 I/O·주기 감사 총량·감사 포함 실제 완료 시간도 반드시 나란히 집계하고 §4.1의 잔여 하한을 보고. |
| 검증 시한 | fresh 검사 지연/worker 고갈 중에도 L 이후 허용 0. 승인된 L 이내 검출을 ‘항상 검사가 완료됨’과 혼동하지 않음. 10,000건 cold 검사가 L을 넘으면 보류가 정상이며 pack/주기를 다시 설계. |
| 정합·호환 | 삭제 권위 감소/원본 부활/미완성 전환 성공 표시 0. 구형 writer 새 형식 쓰기 0. canonical backup/복원 일치·비용 노출 감소 0. |

CI의 안정성 판정은 구조·독립 값·경합 순서 중심이다. 위 PC 수치 목표를 임의로 CI의 절대 시간 assertion으로 바꾸지 않는다. 실제 HDD·백신·Windows 전원 장애는 외부 게이트로 별도 승인/사용자 조작 때 수행한다.

새 correctness 시험 파일 합계 **단위별 60초 게이트**를 제안한다. 10,000건 병행/반복 측정 H/I는 포함/별도 실행 시간을 둘 다 먼저 측정한다. 초과 시 canonical 행을 축소하지 않고 측정값과 별도 성능 job/예산안을 C00에 보고한다. 아직 실행하지 않았으므로 60초 충족을 주장하지 않는다.

## 9. mutation 계획 32개

임시 archive에 pyproject·src·tests를 함께 복사하고 PYTHONPATH를 사본 src로 고정한다. 자식 import 경로도 확인한다. 변이별 독립 assertion 실패로 검출해야 하며 collection 오류·권한 오류·timeout은 검출로 세지 않는다.

| M | 변이 | 검출 oracle |
| --- | --- | --- |
| 01 | stamp 일치만으로 receipt 영구 허용 | A/J 만료 뒤 차단 |
| 02 | 유효기간을 검사 종료 시각부터 계산 | 지연 감사의 J 시각 경계 |
| 03 | 정상 delta 게시가 전역 감사 시각 연장 | 연속 삭제 중 옛 손상·J 만료 |
| 04 | expired receipt를 fallback VALID로 변환 | A 만료 claim 실패·Job 불변 |
| 05 | watcher overflow 무시 | J 즉시 보류/재검사 |
| 06 | 수선 뒤 옛 실패/성공 관찰 게시 | C 관찰 역전 |
| 07 | 새 root에 이전 receipt 재사용 | B root 교체·G 복원 |
| 08 | tombstone을 디스크 손상 시 메모리에서도 제거 | A 자기 삭제 ID 재허용 금지 |
| 09 | 자기 의도 fence를 영속 게시 뒤까지 늦춤 | C I1 쓰기·게시 순서 |
| 10 | 최대 generation 대신 낮은 값 채택 | B·E 정확 사전 |
| 11 | fail ACK를 권위 불명으로 거부 | B worker 종료·ACK 허용 |
| 12 | 만료 권위로 publisher 성공 | B 결과 미게시 |
| 13 | hot Job마다 _read_journal 호출 | H/I 본문 읽기 계수 |
| 14 | 삭제마다 전체 map 복사 | I 누적 작업량 |
| 15 | list page가 전체 목록을 만들어 slice | D/H 반환 전 처리 행 수 |
| 16 | GUI에서 list_sessions 직접 호출 | D worker barrier·thread spy |
| 17 | 실패를 성공 빈 목록으로 표시 | D 마지막 행 미확인·실패 상태 |
| 18 | 늦은 worker가 새 root/선택 덮음 | D 역전/root/닫기 |
| 19 | offset page로 변경/삭제 사이 누락·중복 | D cursor version·정확 행 집합 |
| 20 | 관리 scan/hash를 root/Job lock 안으로 이동 | 구조 spy·H 지연 주입 |
| 21 | 과거 ID를 건수/hash만 남기는 압축 | E 정확 키 사전 비교 |
| 22 | pending을 완료 pack으로 승격 | E 상태·완료 증거 |
| 23 | pack digest/길이 대조 제거 | F 손상/크기 음성 |
| 24 | delta 중간 틈/잘린 tail을 무시 | F 권위 보류 |
| 25 | 새 manifest를 pack 검증보다 먼저 게시 | E05/08 순서 |
| 26 | 전환 완료 전 구 정본 제거 | E08/10 재시작 권위 |
| 27 | 미래 component를 빈 이력으로 열기 | F 미래 형식 거부·바이트 불변 |
| 28 | Library 없는 writer가 pack을 무시 | F fallback 쓰기 0 |
| 29 | backup에서 완료 pack 또는 delta 제외 | G 구성요소·복원 사전 일치 |
| 30 | import 때 source lineage를 새 ID로 치환 | G 이전 삭제 ID 부활 금지 |
| 31 | retention이 완료 pack을 TTL 삭제 | G canonical KEEP·정확 권위 유지 |
| 32 | 전역 감사 실패가 다른 트랙 capture 중단 | H 원본 수락·저장·건강 회계 |

단위별 기본 분담은 11a M01~14·20·32(16), 11b M15~19(5), 11c M21~31(11)이다. M31은 G-P14가 아직 없으면 손으로 만든 보존 계획 adapter가 canonical 목록을 제외하는 계약 시험으로 고정하고, 실제 엔진 연결 시험은 G-P14 착수 시 인계한다. 그것을 제품 retention 통합 검출로 과장하지 않는다.

## 10. 대안·push 경계·정확한 제안 파일

### 10.1 대안

| 안 | 장점 | 비용·한계 | 권고 |
| --- | --- | --- | --- |
| A 검증 유효기간 + 정확 색인 + worker 감사 | 정상 Job/페이지 H 독립, 정상 API I1 유지, 검출 지연을 수치로 명시 | 무통지 같은-stamp 손상의 즉시 전역 검출을 완화, O(H) RAM·주기 감사 비용 | **C00 승인 조건 권고** |
| B 매 요청 전체 본문 검증 유지 | 기존 G-P07 즉시 검출 의미 유지 | H 비례 Job 비용 잔류. pack으로 파일 수를 줄여도 O(H) bytes 검증 | 검출 창을 승인하지 않으면 선택 |
| C mtime 또는 watcher만으로 성공 cache | 구현이 작음 | 같은-stamp 손상·overflow·누락 통지를 증명하지 못하고 만료도 없음 | 거부 |
| D OS 접근 제어/불변 handle·변경 journal로 강한 변경 증명 | 성공 snapshot의 외부 변경 탐지 강화를 시도 가능 | 동일 권한 writer/플랫폼·파일 시스템·handle 수명 검증 필요, 전역 body 손상의 인증은 별도. 현재 근거 없이 즉시 보장을 선언할 수 없음 | 별도 외부 게이트 연구 |
| E DB 하나로 journal 폐기 | 관리 구조 단순화 | 기존 DB-only/journal-only 합집합·재시작·백업 권위 계약 변경, 단일 실패 지점 | 이번 단위 제외 |
| F 논리 이력 유지한 pack/증분 | 파일 수·전체 감사 상수 개선, 정확 키 유지 | migration·backup·fallback·retention 인계 필요 | 11c로 분리 권고 |

### 10.2 세 push로 분리 제안

이 파일 작성 허용이 아래 제품 파일의 구현 승인이라는 뜻은 아니다. 착수 시 최종 tree·해시·실제 API를 재고정하고, C00가 각 범위를 승인한다. 기존 시험 범위 추가는 실제 실패와 최소 diff를 먼저 보고한다.

| 단위 | 목적·분모·mutation | 정확한 제안 쓰기 파일 | 선행·공유 순서 |
| --- | --- | --- | --- |
| **GS-P11a** | 검증 시점/receipt·정확 색인·자기 키 갱신·Job 경계. **382행/16변이**, 12파일 | `src/recoryn/storage/library.py`, 신규 `src/recoryn/storage/deletion_history.py`, 신규 `src/recoryn/app/history.py`, `src/recoryn/jobs/__init__.py`, `src/recoryn/ui/main.py`의 초기 검증/감사 worker 연결, `src/recoryn/cli.py`의 초기 검증 연결; 신규 `tests/unit/test_deletion_history_index.py`, `tests/property/test_deletion_history_index.py`, `tests/integration/test_deletion_history_authority.py`, `tests/integration/test_deletion_history_races.py`; 기존 `tests/integration/test_blocked_reason_flow.py`의 위 검출 시점 계약 시험과 필요한 fixture만; 이 문서 | GS-P02 검토/push와 G-P17a 뒤. G-P09a의 Library/Job/schema 착수와 직렬화. GUI/CLI 연결도 이 push에서 닫아 새 receipt 요구 때문에 기존 앱이 영구 미준비가 되지 않게 한다. G-P12/GS-P01/G-P16의 실제 파일 소유권을 착수 때 재대조하고 먼저 승인. 기존 format 1 유지. |
| **GS-P11b** | 초기 검증/목록 page worker·GUI bounded 반영·CLI 페이지. **72행/5변이**, 6파일 | 신규 `src/recoryn/app/library_view.py`, `src/recoryn/ui/main.py`, `src/recoryn/cli.py`; 신규 `tests/ui/test_deletion_history_scale_ui.py`, `tests/integration/test_session_page_scale.py`; 이 문서 | 11a 뒤, GS-P01/G-P09 UI·CLI/G-P16의 main.py 소유권과 직렬화. ui/content.py·ai_bridge.py·privacy.py는 직접 수정하지 않고 기존 signal 계약 유지. 불가능하면 먼저 요청. |
| **GS-P11c** | canonical pack/증분·명시 migration·backup/restore. **249행/11변이**, 12파일 | `src/recoryn/storage/deletion_history.py`, `storage/library.py`, `storage/_coordination.py`, `schema.py`, `maintenance/migration.py`, `maintenance/backup.py`, `maintenance/restore.py`(모두 src/recoryn 아래); 신규 `tests/unit/test_deletion_history_compaction.py`, `tests/property/test_deletion_history_compaction.py`, `tests/integration/test_deletion_history_compaction.py`, `tests/integration/test_deletion_history_backup.py`; 이 문서 | 11a/b 및 **G-P09a→G-P09b 뒤**. G-P14 구현 전에 새 canonical 목록을 인계. 미래 파일을 미리 만들지 않으며 승인된 G-P09의 실제 API 위에 연결. |

합계 382+72+249=703행, mutation 16+5+11=32. 12+6+12=30 파일 출현, 공유 library.py/deletion_history.py/main.py/cli.py/문서의 중복을 빼면 **24개 고유 파일**이다. 다른 선행 단위의 파일 쓰기는 이 계약으로 위임되지 않는다. 순서 제안은 GS-P02 → G-P17a → GS-P11a/b와 G-P09a/b를 C00가 직렬 배치 → GS-P11c이며, 11a의 format 1 구현이 G-P09 완료를 기다리는 순환 의존을 만들지 않는다.

단위별 검증은 격리 `HEAD + 승인 파일만` archive, PYTHONPATH 사본 src 고정·자식 import 확인, offscreen/no cache/OS TEMP 고유 basetemp로 수행한다. 새 계획 ID 누락·중복 0, 원 반례/삭제 권위·UI·Job·capture 회귀, 해당 mutation, ruff check/format, `python -m mypy src/recoryn scripts packaging`, CI 동등 `--cov=recoryn --cov-branch --cov-fail-under=85`와 `scripts/check_coverage.py` 전 묶음, 전체 오프라인 회귀를 요구한다. 경고와 임시 fixture coverage 오염도 확인한다. 계약 단계에서는 실행하지 않았다.

## 11. C00 결정 요청

1. **검출 시점**: 권고 A를 승인하는가. 같은-stamp 손상을 다음 Job마다 즉시 전역 검출하는 기존 기대를 ‘초기/fresh 전체 검사 + 실행 중 유효기간’으로 바꾼다는 사실과, 유효기간 안 무통지 외부 의도/변조를 즉시 검출하지 못하는 창을 명시 승인해야 한다. 거부하면 B를 유지하고 H 독립 목표를 조정한다.
2. **시각·실행 경계**: 5초 검사 요청/L=30초, 검사 시작 기준·만료 즉시 fail closed·정상 delta로 유효기간 연장 금지·ACK 허용·capture 자기 fence 분리를 승인하는가. 기존 원격 요청의 소급 취소 보장을 추가하지 않는 경계도 확인한다.
3. **복잡도·UI**: 정확 map/PK, 페이지 k≤128, GUI worker/세대·실패 표시, 한 삭제마다 전체 copy/검증 금지와 초기 검증 준비 상태를 승인하는가. 새 성능 목표·703행·32변이·단위별 60초 측정 게이트를 승인하는가.
4. **정본 압축**: 논리 tombstone 영구 보존·정확 pack/증분, 첫 버전 최종 전환은 명시 유지보수/실제 ACK 뒤, 형식 2·fallback/구버전 차단·G-P09/G-P14 인계를 승인하는가. 자동 TTL·pending-only 축소·실행 중 강제 전환은 허용하지 않는다.
5. **분할·소유권**: GS-P11a/b/c의 12/6/12파일과 분모 382/72/249를 승인하는가. GS-P02→G-P17a 뒤 11a/b와 G-P09a/b의 정확한 직렬 순서는 C00가 정하며, GS-P11c는 G-P09b 뒤로 둔다. 이 문서 승인만으로 제품·시험 구현을 시작하지 않고 별도 신호를 기다린다.

## 12. 계약 자체 점검

- 직접 확인: 지정 두 tree의 코드/기존 시험 경계, GS-P02 정상 선읽기 잔류, root→Job 순서, GUI 동기 list_sessions, 자기 키 갱신의 전체 dict 복사, canonical backup/retention 인계 문서.
- 기존 측정 인용: GS-P02의 0/100/1000 claim 소수 표본과 C00의 G-P12/GUI 관측. 이번 신규 측정·제품 시험·mutation 실행은 0.
- 계획: 703행·32변이·성능/물리 장치 외부 게이트·세 push/24 고유 파일. 아직 구현/검증 완료로 집계하지 않는다.
- 미승인 핵심: 기존 즉시 전역 손상 검출의 시점 변경, L 값, 새 canonical 형식과 구현 범위. C00 승인과 독립 검토를 기다린다.

## 13. GS-P02 독립 검토 의견 반영·추가 결정 요청

2026-11-25, C00의 GS-P02 FIX1 요청에 따라 덧붙인다. 앞 문서 LF SHA256 `061d58ee73a94e0eec3e7efd8b488f4a616cb75d56d245f371c195784a251523`의 본문은 이력으로 보존했다. 제품·시험 구현은 하지 않는다. GS-P02의 수정·검증은 별도 `gs02-index-failure-cases.md` §15~16이며, 그 변경을 GS-P11 구현 성과로 세지 않는다.

### 13.1 의견의 출처와 검출 범위 구분

`docs/reviews/gs02-index-failure-review.md:122~125`는 다음 네 방향을 제안한다: 항목별 metadata 지문 대조, 열 때·주기 전체 검증, 완료 tombstone의 checksum ledger/DB 표현, GUI 목록 worker. 이는 검토자의 설계 의견이며 ‘1,000 stat 수 ms’는 이번 작성자가 실측한 결과가 아니다. metadata 비용도 H=0/100/1000/10000에서 측정해야 한다.

**디렉터리 stamp D와 항목 지문 F를 구분한다.** 기존 G-P07 시험의 제자리 본문 쓰기는 D를 바꾸지 않아도 보통 파일 크기/mtime을 바꾼다. 이 경우 항목별 F 대조로 다음 입장에 변화를 발견할 수 있다. 그러나 같은 길이 쓰기·거친 시각 해상도·파일 mtime 복원·같은 파일 ID 등으로 F까지 같으면 stat만으로 본문 변조를 증명하지 못한다. ‘같은 D를 잡는다’와 ‘모든 metadata가 같은 손상도 즉시 잡는다’를 같은 보장으로 쓰지 않는다.

### 13.2 A0: 항목 지문을 쓰는 과도기 대안

원 권고 A와 비교할 **A0 대안**을 추가한다. 최초 전체 검증 때 각 알려진 항목의 `(file ID/dev, size, st_mtime_ns)`와 canonical 논리 값/digest를 결속한다. 이름과 경로는 기존 safe_path/reparse/hard-link 검사를 거친다. 실행 중 Job/관리 입장은 worker에서 알려진 항목별 stat을 대조하고, 달라진 항목만 다시 읽되 이전 권위와 정상 writer delta를 함께 검증한다. 단순히 새 지문을 저장하고 ‘변경 없음’으로 승격하지 않는다.

- 지문 목록 복사/순회·항목 stat·재파싱은 root·Job 잠금/transaction·GUI thread 밖이다. root 안에서는 root instance/history_version/관찰 세대와 현재 cut을 짧게 대조한다. snapshot을 만들려고 root 안에서 H개 dict를 복사하지 않는다.
- 정상 원자 쓰기는 자기 키와 version을 함께 갱신한다. 외부 변화와 자기 쓰기를 같은 사건으로 섞지 않는다. 관찰 중 version이 달라지면 bounded 재시도/보류한다. 부재/링크/오류를 빈 이력으로 해석하지 않는다.
- 같은 D 아래 크기/mtime/file ID가 바뀐 본문 손상은 다음 입장에서 검사한다. F까지 같은 손상과 D까지 복원한 새 이름 추가는 전체 감사 시점까지 놓칠 수 있다. 이 한계를 C00가 승인해야 한다. 알려진 tombstone 부정 결과는 계속 유지한다.
- A0도 최초·재열기·복원·명시 검사와 주기 전체 검증이 필요하다. ‘idle일 때만 수 분마다’로 운용한다면 연속 녹음/계속 바쁜 worker에서 검출 지연 상한을 보장하지 못한다. 원문의 5초 요청/L=30초 제안은 아직 미승인이고, 다른 주기를 고르면 지연/만료 계약도 함께 재승인한다.
- 항목 stat의 O(H)는 없어지지 않는다. A0는 반복 본문 파싱을 줄이는 **과도기**이며, GS-P11의 O(1)~O(log H) 완료 조건을 만족했다고 닫지 않는다. stat에 지연을 주입해도 녹음/GUI가 이를 기다리지 않아야 한다.

이 전역 metadata 대조를 provider의 64KiB write마다 연결하지 않는다. G-P06의 요청당 1회 비용/본문 검증과 O(1) write guard, 기존 자기 세션 삭제 fence를 유지한다. Job 입장/관리 조회 개선이 원격 STT 전송의 반복 O(H) 지연을 새로 만드는 변형은 불합격이다. 해당 G-P06 성능/가드 회귀를 후속 검증에 포함한다.

선택지는 **A(유효기간 안 O(1) snapshot), A0(항목 stat + 전체 감사), B(매번 전체 본문)** 세 가지다. 원문 A의 승인 요청을 자동 승인으로 취급하지 않는다. A0는 일반적인 같은-D 본문 쓰기의 즉시 검출을 더 유지하지만 전경 O(H)가 남는다는 점까지 포함해 C00가 선택한다. 첫 구현 전 A0 지문의 10,000건 비용을 재고, 최종 canonical 전환까지 필요한 임시안인지 결정할 것을 권고한다.

### 13.3 완료 ledger/DB와 최종 복잡도

검토자의 ‘진행 journal만 남기고 완료는 ledger/DB로’는 **완료 이력 제거가 아니라 저장 표현 전환**으로 수용한다. 원문 §5의 정확한 완료 pack이 checksum tombstone ledger 역할을 하고, deleted_sessions DB와 독립 권위를 유지한다. 진행 의도는 delta/개별 항목으로 보존한다. 최종 hot 경로가 완료 H개 파일을 열거나 stat하지 않게 해야 한다. 활성 pack·delta의 metadata와 정확 메모리 map/PK를 사용하되 pack 수/P/D가 새 선형 분모가 되면 그 수를 따로 계측한다. 과도기 A0의 H개 파일 stat을 최종 구현에도 숨겨 남기지 않는다.

물리 전환에는 G-P09의 component/version·backup·restore/import·구버전 writer 차단, G-P14 canonical KEEP, 실제 reader/작업 ACK가 필요하다. 최소 ID·최대 세대·상태·필수 근거는 영구 보존한다. 원래 개별 journal 파일을 retire하는 행위는 모든 논리 권위가 새 정본에 있고 내구성/참조 검증을 마친 뒤의 명시 유지보수에 한한다. pending-only backup이나 TTL 기반 tombstone 축출로 바꾸지 않는다.

checksum은 손상 검출이며 출처 인증/rollback 방지 서명이 아니다. 서명 manifest를 택하려면 신뢰 키의 소유·보관·회전·복원 계약을 별도로 승인받아야 한다. 이 배정으로 Credential Manager/vault 쓰기나 새 서명 키를 도입하지 않는다. 독립된 현재 권위가 없는 전체 과거 root rollback의 한계도 유지한다.

### 13.4 GS-P01 GUI 소유권과 GS02R-01 회귀 방지

GUI 목록은 검토 의견대로 G-P04/G-P05의 worker·조회 세대·queued 반영 방식을 유지한다. **GS-P01이 공통 worker/read model을 먼저 만들면 그것을 재사용**하고, GS-P11b가 두 번째 목록 pool/parser를 만들지 않는다. GS-P11b는 페이지·가시성·이력 준비 상태 연결을 소유하며, 실제 파일 경계는 GS-P01 push tree 위에서 재대조해 C00가 확정한다.

새 감사/receipt/지문이 **GS02R-01을 다시 만들면 안 된다**. PermissionError/OSError는 그 호출에서 fail closed하고 다음 호출에 재시도하며, 내용 손상 memo로 승격하거나 영구 ‘이력 없음’으로 저장하지 않는다. 전역 Job/관리 권위의 유효기간과 기존 녹음 상태/자기 삭제 fence를 구분한다. get_session/chunks·새 녹음 생성·stop이 단 한 번의 전역 감사 I/O 오류 때문에 수동 fresh 버튼을 누를 때까지 막히면 불합격이다. 자기 세션 삭제 의도·실제로 확인 불가한 자기 권위를 무시해 허용한다는 뜻은 아니다. 글로벌 receipt를 기존 _live 전체에 단순 접합하지 않는다. 이 분리가 승인 파일 안에서 불가능하면 구현 전에 SCOPE_NEEDED를 낸다.

### 13.5 추가 oracle·분모·mutation 제안

원 계획703행에 회귀 **K8**을 공통 추가한다: PermissionError/OSError2 × 로컬 동작4(get_session/chunks/create_session/stop). 한 행은 ‘전역 감사/지문 I/O 한 번 실패 → 해당 호출은 필요하면 거부 → 다음 로컬 동작 회복·원본 보존·자기 삭제 fence 유지’의 상태열이다. `GS11-K-001~008`, 기대값은 제품 receipt 상태를 복사하지 않고 입력한 1회 오류와 실제 바이트로 판정한다.

A0를 선택하면 **L48**을 추가한다: 지문 상황8 × 소비자3(Job/페이지/명시 검사) × receipt 시점2(유효기간 안/만료). 상황8은 정상 일치, 크기 변경, 같은 크기 mtime 변경, 같은 크기·mtime 파일 ID 변경, 본문만 바꾸고 지문 전체 유지, 알려진 파일 누락, stat 일시 거부, 같은 D의 새 이름 추가다. 변경 상황은 손상 본문을 별도로 고정하며 정상/손상 여부를 제품 parser에서 기대값으로 가져오지 않는다. 지문 유지/미지 이름의 검출 지연은 §13.2대로 정직하게 관측한다. 알려진 삭제 ID는 어느 경우에도 재허용하지 않는다.

| 선택 | 계획 F | 11a/11b/11c | 후보 Ω·제외 | mutation |
| --- | ---: | --- | --- | ---: |
| A | 703+8=**711** | 390/72/249 | 747−36=711 | 33 |
| A0 | 703+8+48=**759** | 438/72/249 | 795−36=759 | 37 |
| B | hot O(1) 목표 수정과 시험 분모를 다시 계약 | 미확정 | 원 703을 그대로 완료 분모로 쓰지 않음 | 미확정 |

공통 M33은 ‘한 번의 감사 I/O 오류를 녹음 경로의 영구 거부로 저장’이다. A0의 M34~37은 mtime 지문 대조 생략, stat 오류를 VALID로 승격, 지문 불일치를 본문 검증 없이 새 정상으로 기록, 항목 stat loop를 root/GUI 안으로 이동이다. 원 M01~32와 합쳐 각각33/37개다. 기존 E의 불가능 no-op checkpoint36개 제외는 그대로다. 단위별 새 시험60초 gate는 유지하며 이번 계약 단계에서 추가 제품 시험/변이는 실행하지 않았다.

### 13.6 최종 결정 요청의 보완

§11의 ①~⑤에 더해 **A/A0/B 선택과 검출 지연, GS-P01과 GUI 소유권, 완료 checksum ledger/DB 전환, GS02R-01 회귀 금지, F711 또는759·변이33 또는37**을 함께 결정해 달라. 원문 703/32는 이전 제안 이력이며 새 실행 실적으로 집계하지 않는다. 12/6/12파일·고유24파일의 제안 범위는 유지하되, GS-P01/G-P09의 최종 API나 로컬/전역 권위 분리 때문에 목록 밖 파일이 필요하면 착수 전 추가 승인을 받는다. 구현 시작 신호를 기다린다.

## 14. GS-P11a 착수 준비 — 계약 재대조·시험 설계만

### 14.1 이번 준비의 권한·읽기 기준

C00은 G-P17a를 검토 tree `2fd2bbf8`로 독립 검토에 넘겼고, 그 push 전까지 `storage/library.py`를 수정하지 말고 GS-P11a 계약 재대조·시험 설계만 준비하도록 배정했다. 이 절만 추가한다. **제품·시험 코드 작성/수정/실행·mutation·성능 재측정은 하지 않았다.** G-P17a 재확인 요청이 오면 그쪽을 우선한다.

C00이 선택한 정본은 **A안**이다. A0의 항목별 O(H) stat·B의 매 호출 전체 검증을 새 정상 경로에 섞지 않는다. 검증 시작 기준 L=30초·5초 검사 요청·만료 즉시 fail closed·delta로 연장 금지·ACK 허용·capture 자기 fence·원격 write 소급 취소 추가 없음·정확 map/PK·k≤128·GS-P01 재사용·compaction은 11c라는 결정이 앞 제안 문구에 우선한다.

직접 코드 대조는 고정 commit `47530a2b1772b911555ee0b5124f32792dfbea23`와 G-P17a 검토 tree `2fd2bbf8`의 `git show`다. 공유 작업 트리의 G-P13/G-P11d/G-P12b 제품 변경은 구현 정본으로 사용하지 않았다. 배정표와 해당 단위의 문서로 파일 소유권만 확인했다. G-P17a 최종 push tree가 아직 없으므로 **실제 구현 기준·12파일 hash는 시작 신호 뒤 다시 고정**한다.

### 14.2 12파일과 진행 단위 충돌

| 승인 GS-P11a 파일 | 현재 상태·소유권 대조 | 준비 경계 |
| --- | --- | --- |
| `src/recoryn/storage/library.py` | **G-P17a 검토 중**. 이번 준비에서 읽기만 | G-P17a push·C00 시작 신호 전 수정0 |
| 신규 `src/recoryn/storage/deletion_history.py` | HEAD 없음, 현재 파일 없음 | receipt·정확 index·검증/상태 모델. format1만 |
| 신규 `src/recoryn/app/history.py` | HEAD 없음, 현재 파일 없음 | core coordinator·요청 합치기. 독립 GUI pool/parser 생성 금지 |
| `src/recoryn/jobs/__init__.py` | G-P11d의 `jobs/runner.py`와 **다른 파일** | 기존 공개 Job 호출 서명 유지, root→Job 순서·실제 ACK 계약 보존 |
| `src/recoryn/ui/main.py` | G-P16은 HEAD에 반영됨. G-P13은 ui/main을 바꾸지 않는 배정 | 초기 준비/감사 연결만. 모델/정책 제어·공통 경고 우선순위 보존 |
| `src/recoryn/cli.py` | 제시한 진행 단위와 직접 중복 없음 | CLI 초기 검증은 control lane, GUI/전송 자동 재개 없음 |
| 신규 `tests/unit/test_deletion_history_index.py` | 없음 | A·J·K의 순수/상태값·정확 코드·clock/cut |
| 신규 `tests/property/test_deletion_history_index.py` | 없음 | 손으로 쓴 exact-map 모델·delta·복잡도 계수 |
| 신규 `tests/integration/test_deletion_history_authority.py` | 없음 | 실제 Library·JobStore·publisher·capture 경계 |
| 신규 `tests/integration/test_deletion_history_races.py` | 없음 | C barrier·H/I 구조·재열기/중단·원본 보존 |
| `tests/integration/test_blocked_reason_flow.py` | 제시한 진행 단위의 직접 변경에 없음 | 승인된 검출 시점 시험 및 필요한 fixture만. 다른 기존 시험 실패는 먼저 보고 |
| 이 문서 | 기존 계약 원문 보존 | 준비·실행 근거를 끝에 추가 |

G-P13 검토 tree `e447958c`를 HEAD47530a2와 diff한 변경 집합과 위12파일의 **직접 교집합0**을 확인했다. G-P11d 문서는 runner·scheduler reaper 종료/ACK 시험을, G-P12b는 ui/content.py·basis UI/property 시험을 소유한다. 그 파일을 GS-P11a가 수정하지 않는다. 소유권 표가 바뀌거나 필요 파일이 늘면 착수 전에 다시 보고한다.

직접 중복은 없어도 기능 경계는 있다. G-P11d가 확정하는 reader/reaper ACK를 권위 만료로 막거나, runner.stop 뒤 JobStore.close 순서를 바꾸지 않는다. G-P13의 모델 확인·snapshot/config_key 규칙도 receipt/config_key로 대신하지 않는다. G-P12b의 후보 상태·SELECTION_CONFLICT와 GS-P01의 공통 실패 표시를 새 오류 문자열/새 GUI parser로 복제하지 않는다.

### 14.3 최신 코드의 근거와 실제 남은 변경

| 고정 근거 | 직접 확인한 현재 동작 | GS-P11a 준비 결론 |
| --- | --- | --- |
| 47530a2 `storage/library.py:288`·`:290` | 생성자에서 Root를 가진 채 초기 index 검증 | GUI run의 초기 검증을 준비 상태/worker로 분리해야 함. DB open 자체와 O(H) 감사 비용을 구별 |
| `:299`·`:315`·`:331` | job_authority가 매번 `_journal_prefetch`를 거쳐 Root를 유지한 채 상태 문자열 yield | Root→Job 원자 경계는 유지하고 hot O(H) 선읽기를 유효 snapshot/자기 PK로 교체 |
| `:433`·`:465` | 실패 cache만 재사용하고 정상 journal 본문은 재독 | A안은 명시적인 성공 검증 수명 계약 변경. same-stamp 즉시 검출을 그대로 주장하지 않음 |
| `:673`·`:702`·`:716` | DB tombstone 전체 fetch·dict·합집합 | 검증 worker의 한 번 O(H)와 hot 자기 키/페이지 경로를 분리 |
| `:783`·`:785` | list_sessions가 항상 fresh 전체 journal 검증 뒤 전체 반환 | 호환 전체 O(S)는 남길 수 있으나 H 비용·GUI 동기 호출은 제거. page는 storage 기반을 a에서 준비하고 UI paging은 b |
| `:2699`·`:2704`·`:2709` | 정상 의도마다 전체 dict 복사, atomic_json이 Root 안 | 단순 성공 cache만으로 누적 삭제의 제곱 증가가 해결되지 않음. 자기 key delta·영속 게시 순서도 같은 단위에서 다룸 |
| 2fd2bbf8 `library.py:934` | G-P17a public 등록은 busy0·Root 밖 bounded 재시도·매 시도 권위/active capability 재확인 | 최종 push판 구현/시험을 그대로 보존하고 새 index의 자기 fence와 연결. 기존 기한을 snapshot TTL로 바꾸지 않음 |
| 47530a2 `jobs/__init__.py:202`·`:230` | authority를 Job transaction/잠금 전에 받아 Root→Job 유지 | 감사/I/O는 Job transaction 밖, transaction 끝의 신선도 점검도 Root 재취득 역순 없이 수행 |
| `:610`·`:615`·`:690`·`:704` | complete·publisher는 아직 직접 Job transaction | 두 경로 모두 신규 게시 조건을 연결해야 함. 과거 idempotent 결과 조회와 신규 게시/실제 종료 ACK를 구별 |
| `ui/main.py:577`·`:585`·`:628`·`:634` | inventory worker는 있지만 render에서 GUI 동기 list_sessions 호출 | 기존 worker가 있다고 GUI scan0이라고 판정하면 안 됨. a는 초기 준비/감사, 목록 read model은 GS-P01/b 순서로 |
| `ui/main.py:140`·`:163`·`:171`·`:1414` | 제어·inventory·정책 pool과 worker ACK shutdown이 존재 | policy/control pool을 장기 감사로 막지 않음. 기존 Task/queued/세대 합치기를 재사용하고 GS-P01에 인계 |
| `cli.py:408`·`:417` | GUI와 달리 명령 control lane에서 Library open·목록 실행 | 최초 검증 완료/보류를 명령 결과로 명시. UI용 초기 검증 경로와 혼동하지 않음 |
| `test_blocked_reason_flow.py:704`·`:717` | 같은 directory stamp 본문 손상 다음 claim의 즉시 실패 기대 | 승인된 A 정책대로 유효기간 중 창/명시 검사/만료 뒤 실패로 개정. 정상 API D의 즉시 차단은 그대로 |
| `:724`·`:754`·`:756` | 열거가 Root/Job lock/Job transaction 밖인지 계측 | 기존 구조 단언은 약화하지 않음. hot 경로는 열거 자체0을 추가 |

### 14.4 설계 시 먼저 닫을 경계

**로컬 capture와 전역 관리 권위는 별도다.** 기존 `_live` 전체에 receipt를 붙이는 구현은 하지 않는다. get_session/chunks/create/stop은 자기 canonical fence와 알려진 삭제 floor를 지키고, 다른 ID의 감사 I/O 오류·만료가 그 경로를 영구 거부하지 않게 한다. 관리/Job의 불명은 여전히 허용 아님이다.

특히 HEAD `app/recording.py:832`~`:864`는 stop의 건강 보류 복구에 `Library.recover_session`을 호출하고 그 뒤 `finalize_session`을 호출한다. 같은 `library.py:2187` recover API는 CLI/UI 관리 복구에도 사용한다. 둘에 전역 receipt를 무조건 요구하면 기존 건강 보류 stop이 전역 감사 오류 때문에 수동 fresh까지 지연될 수 있다. 반대로 전역 검사를 UI/CLI에만 두고 public 관리 API를 무조건 self-only로 만들면 승인된 관리 권위 계약과 다르다.

이 경계를 **구현 전 결정 요청**으로 남긴다. 권고는 명시적인 capture 제어 문맥/ACK 근거를 Library API에 전달하고 관리 호출의 기본은 global-required로 유지하는 안이다. 그러려면 `app/recording.py`의 해당 호출 연결을 추가 파일로 승인받을 가능성이 있다(현재12파일 밖, 현재 수정0). 12파일 안에서 해결하려면 public 관리/로컬 API 책임을 어떻게 분리하는지 먼저 C00과 확정해야 한다. owner 존재만으로 암묵 승격하거나 caller stack을 보고 권한을 바꾸지 않는다. 지금 단계에서 13파일 구현을 승인받았다고 간주하지 않는다.

나머지 구현 선택은 다음 원칙으로 준비한다.

- `deletion_history.py`가 immutable 검증 base·현재 exact lookup·신뢰된 delta cut·시작 시각을 소유한다. 매 정상 삭제의 전체 dict copy를 제거하되 검증 worker가 동시에 바뀌는 mutable dict를 잠금 없이 순회하지 않는다. Root는 O(1) token/cut 포착·단일 key 반영·결과 게시만, O(H) 비교/복사는 밖에서 한다.
- 별도 readonly SQLite 연결로 audit의 DB snapshot을 읽는 경우에도 연결 생성/수명/정리와 cut 일치를 명시한다. Library의 공유 `_db`를 Root 밖에서 쓰지 않는다. read snapshot과 신뢰된 정상 delta의 정확 합집합을 손 사전으로 대조하고, 계속된 삭제가 감사 시한/진행을 무한히 미루지 못하게 한다.
- 정상 의도의 staged write/fsync와 최종 canonical 게시를 나눌 때는 자기 세션 보수적 fence를 먼저 예약하고, 최종 Root에서 현재 세대·상태를 재확인한 뒤 원자 게시·exact key delta를 함께 반영한다. 실패는 새 허용/삭제 완료로 바꾸지 않는다. format1의 canonical 파일을 pack으로 바꾸거나 temp를 권위로 채택하지 않는다.
- receipt TTL은 실제 검사 **시작** 기준이다. 5초는 요청 간격, 30초는 권한 최대 수명이다. scanner 지연/고갈/실패·정상 delta는 이 시한을 연장하지 않는다. 만료 여부는 각 호출에서 판단하므로 GUI timer가 밀려도 허용이 늘지 않는다.
- G-P17a의 시계 fixture 문제를 재발시키지 않게, 감사의 monotonic/UTC 관측을 명시 Clock 입력 쌍으로 설계한다. journal wall-clock fake와 I/O 기한을 한 모듈 monkeypatch로 뒤섞지 않는다. J는 정수 ns 경계로 확인하고 30초 sleep을 하지 않는다.
- controller는 Qt에 의존하지 않는 scan 요청/합치기/결과 버전 상태를 준비한다. UI는 기존 Task·queued·generation·실제 종료 ACK를 재사용하고 새 pool/parser를 늘리지 않는다. GS-P01 뒤 11b가 공통 read model로 연결한다. 자체 receipt 상태 DTO를 세션 목록 read model의 대체품으로 만들지 않는다.

### 14.5 a의 분모·ID·시험 계층 준비

정본 §13.5/배정표는 **a390 = 기존382 + K8**, 전체711이다. C00 이번 메시지의 ‘390+K8’가 추가8을 뜻하는지 확인 질문을 보냈다. 답 전에는 **기존 승인 산식390(K포함)**을 준비 기준으로 두고,398을 승인받았다고 기록하지 않는다. 아래는 실행 실적이 아닌 산술·매핑 점검이다.

| family | a 계획 | 입력·독립 기대 | 주 계층 |
| --- | ---: | --- | --- |
| A | 180 | A12×시점5×관찰3. 사전에 손상/변경 사실을 고정하고 자기 삭제 ID·무관 ID를 함께 확인. 창 안 허용과 fresh/만료 뒤 보류를 구분 | unit·authority integration |
| B | 98 | B14×공개 동작7. 현재 Job/attempt/fence·state_version을 fixture에서 고정하고 정확한 상태/오류·publisher 실행0/1·ACK를 직접 대조 | authority integration |
| C | 48 | Event schedule8×상대3×receipt 시작 유무2. 전체 interleaving 전수가 아닌 정의된 feasible schedule | races integration |
| H-a | 16 | H4×트랙2×관리2(Job 전이/연속 삭제). 실제 수락 bytes·frame·QUEUE_DROP 회계·Root 역할 분리 | races/구조·별도 성능 측정 |
| I-a | 8 | H4×작업2(hot Job/연속 삭제). body bytes/open/full fetch/map copy 계수. 빠른 wall time만으로 PASS 금지 | property·구조 |
| J | 32 | 시각쌍8×사건4. 정확히 L은 만료, 역행·delta·overflow·늦은 감사에 허용 연장0 | unit·property |
| K | 8 | 오류2×로컬 동작4의 상태열. 전역 실패1회 뒤 자기 경로 회복·원본 보존·자기 D 차단을 동시에 확인 | unit·authority/races |
| 합계 | **390** | 180+98+48+16+8+32+8 | 신규4파일 |

전역 H ID는 H4→tracks(1,2)→관리(job,page,delete,compact) 순, I는 H4→(job,page,delete) 순으로 고정할 제안이다. a는 H의 job/delete16행과 I의 job/delete8행을 택한다. a용으로 H/I 전체를 다시 번호 매겨 b/c의 ID와 충돌시키지 않는다. A001~180·B001~098·C001~048·J001~032·K001~008과 이 H/I 부분집합을 열거해 **390·중복0**을 확인했다. 세부 fixture/node는 실제 코드 API 확정 후 고정한다.

시험 파일의 역할은 unit(Clock/receipt·실패 상태·정확 분류), property(수동 참조 모델·delta/lookup 작업량), authority integration(실제 Library/JobStore/SQL publisher/로컬 capture), races integration(Event 순서·재열기·원본·관리 구조)다. 제품 parser/authority/cache/‘VALID’ 문자열을 expected 생성기로 쓰지 않는다.

B의 기본 표는 유효한 일반 세션만 입장/게시 허용, DB/journal/양쪽/tombstone은 거부, 세션 소실은 MISSING, 전역 미준비·만료·감사 실패·다른 root receipt는 HISTORY_UNAVAILABLE다. 실제 fail/reader 종료 ACK는 권위 불명에도 정리 가능하되 신규 게시/재전송을 만들지 않는다. 이미 commit된 idempotent 결과 읽기는 새 publisher 실행과 분리해 추가 회귀로 확인한다.

K의 stop 행에는 건강 정상 경로와 건강 보류 복구 경계의 차이를 숨기지 않는다. §14.4의 API 결정 뒤 두 번째 경계는 별도 보강 ID로 추가/필요 분모를 C00에 보고하며, 동일 입력을 두 node로 복제해 K를 부풀리지 않는다.

### 14.6 mutation·측정·착수 체크리스트

A안 a는 기존 M01~14·M20·M32의16 + 공통 M33 = **17개 의미 변이**다. b5·c11을 합쳐 전체33이며, a에서 전체33을 검출했다고 보고하지 않는다. 초기 검증/worker 같은 구현 경계가 정해지면 각 변이의 정확 치환·독립 assertion node를 먼저 고정한다. 수집/권한 오류·process timeout은 검출 아님이다.

60초 게이트는 신규4파일을 단독 선택 실행해 실측한다. H/I의 실제10,000행 준비/복제·닫기 비용을 숨기지 않고, correctness와 별도 반복 성능 H/I의 포함/분리 시간을 함께 기록한다. 읽기 전용 기준 snapshot을 재사용할 수 있어도 변이/삭제 뒤 다음 행의 H·S·P를 실제 확인하고, 삭제 이력을 지워 가짜 O(1) 결과를 만들지 않는다. 초과하면 행을 줄이기 전에 실측·fixture 최적화/별도 성능 job·예산안을 C00에 보고한다.

성능 수락은 claim/reader/block/resume/fail ACK·단순 complete·publisher를 분리한 계수와 시간, 0/100/1000/10000H·1/2트랙·H와 S/P 차이, 관리 Root 장기 보유0·본문/H scan0·수락 PCM 보존·정확 queue 회계다. 실제 디스크 탓의 CI QUEUE_DROP은 측정값이며, 0거부 목표 달성/17a 소비자 처리량 해결로 무단 일반화하지 않는다. G-P17a의 native3초 잠금·18변이·ACK/fence·GS02/GC02/G04/G05/G07/G08 구조 회귀는 유지한다.

실제 착수 때 해야 할 순서는 (1) G-P17a 최종 push/검토 폐쇄 신호·base/hash 재고정 (2) 이 절의 분모·capture 제어 경계 결정 (3) 같은 시점 파일 소유권 교집합 재대조 (4) 공개 API/Clock·unit oracle 먼저 (5) Job·capture·startup 연결 (6) 격리 source·자식 import·기존 회귀·mutation·CI 동등 coverage·ruff/format/mypy·전수다. 지금은1~6을 실행한 것이 아니라 계획한 상태다.

새 성능 실측·제품 pytest·mutation 실행0이며, 문서 열거 산술만 직접 확인했다. 준비 산출물의 단독 최종 승인을 주장하지 않는다. G-P17a 재확인이 오면 준비 작업보다 우선한다.


## 15. GS-P11a 구현 착수 — 6156b65 기준

C00의 착수 신호에 따라 HEAD `6156b6514116be510426efed69bfd549e876b345`를 기준으로 승인12파일의 초기 LF 해시를 build의 새 gs11a-evidence 폴더/input.json에 고정했다. GS-P06 11파일과 직접 교집합0이다. GS-P06 검토 FIX 요청이 오면 우선한다. GS-P11b/c·GS-P01·G-P09의 제품 파일은 이번 범위에 포함되지 않는다.

정본 분모는 배정표대로 **a390(K8 포함), 전체711**이며 a의 의미 변이는 M01~14·M20·M32·M33 **17개**다. §14.5의398 가능성 질문은 과거 준비 이력이며 현재 실행 분모를 늘리지 않는다. 신규4파일 합계60초는 실측하고 초과하면 행 축소 전에 보고한다. 성능 측정은 C00 최신 요청의 H=0/1,000/10,000/100,000을 별도 확장 측정으로 준비하되, canonical H family의0/100/1,000/10,000 입력도 실제 검증한다. cold 감사가30초를 넘으면 receipt 발급0을 정상으로 기록하고 유효기간을 늘려 O(1) 성공처럼 보이지 않는다.

### 15.1 capture 제어 경계 추가 승인 요청

6156b65의 RecordingService.stop():862·884는 관리와 같은 Library.recover_session/finalize_session을 호출한다. library.py:2088의 finalize_session은 관리 operation·건강 페이지·manifest를, :2236의 recover_session은 관리 복구를 소유한다. 전역 snapshot 요구를 그대로 붙이면 건강 기록이 연기된 녹음 종료도 전역 감사 오류/만료 때문에 막힐 수 있다. 반대로 관리 API 전체를 self-only로 낮추지 않는다.

C00에게 app/recording.py를13번째 파일로 추가하고, root·실행 instance·세션·등록 owner·실제 source/writer/sealer 종료 ACK를 검증하는 명시 capture 제어 문맥을 stop 호출에만 연결하는 범위를 요청했다. 이 파일은 GS-P06 검토 대상이므로 승인과 직렬 착수 신호 전에는 수정0이다. owner 존재만으로 승격하거나 caller stack으로 분기하지 않는다. 이 결정을 기다리는 동안 승인된 순수 권위 모델·clock·oracle를 먼저 준비한다.

### 15.2 초기 구현·독립 oracle 설계

모델은 불변 scan ticket/receipt와 정확한 부정 floor, 신뢰된 O(1) 자기 키 delta를 분리한다. hot 조회에서 전체 map 복사/본문/이름 목록은0이며, full scan과 과거 cut/delta의 비교는 Root·Job transaction 밖이다. 정상 delta는 기존 검증 시작 시각을 연장하지 않는다. 실패/만료/close/root 교체 뒤에도 알려진 tombstone은 양성 허용으로 돌아가지 않는다. I/O 실패는 내용 손상 sticky 상태로 바꾸지 않고 다음 검사를 허용한다.

시계는 monotonic ns·UTC ns의 명시 쌍으로 주입하고 sleep으로30초 경계를 만들지 않는다. 실제 관측은 mono-before/UTC/mono-after 구간과1ms 관측 오차를 기록한다. 오차는 시계 일치 판정에만 쓰며30초 만료를 연장하지 않는다. 두 경과가 음수이거나 어느 한쪽이30초 이상이면 즉시 거부한다. J8의 손 시각쌍은 오차0으로 고정해 정확히 L인 경계를 검증하고, 실제 관측 오차/불일치는 별도 보강 ID로 감사한다.

A·B·C·H-a·I-a·J·K의 입력/ID 매핑은 §14.5를 유지한다. 테스트 expected는 제품 parser·receipt 판정 함수를 복사하지 않고 hand map·사전 오류 사실·Event 선후 관계·실제 원본 bytes·작업량 계수로 만든다. 아직 제품/시험 실행·성능 수락·mutation 검출 결과를 주장하지 않는다.

### 15.3 진행 중 직접 확인 — 배포 완료 보고가 아님

현재 기준은 계속 `6156b65`이며 격리 사본은 `build/gs11a-evidence-f775b59cea/dev-input.json`에 기록했다. 작업 트리의 GS-P06·G-P12b 변경은 이 사본에 포함하지 않았다. GS-P06 11파일은 수정하지 않았다.

- 순수 clock/receipt·controller 보강과 공개 Library/JobStore의 A180·B98 선택 실행은 320 PASS였다. A의 무통지 window와 fresh/만료 뒤 보류를 구분한다. 첫 열기/재열기 때 과거 digest 증거가 없는 유효 schema-1 값·DB-only 의도는 과거 진위를 인증할 수 없으며, 해당 행은 그 한계를 명시한다. 이미 알려진 tombstone을 다시 허용하지 않는 단언은 별도로 유지한다.
- 신규 네 파일의 첫 통합 선택 실행은 **400행(정본 390 + 보강 10), 398 PASS·2 FAIL, 312.51초**였다. 정본 ID는 삭제하지 않았다. 실패는 K004·K008의 전역 감사 I/O 실패 뒤 stop→finalize→관리 건강 조회 경계다. §15.1의 명시 capture 제어 연결 범위 요청과 같은 경계이며, 녹음 정지가 회복되었다고 집계하지 않는다.
- testcase 시간 합은 unit 0.072초, property 0.020초, authority 17.538초, races 294.129초였다. 실제 H=10,000 파일을 행마다 복제·검증하는 H025/027/029/031이 62.269~70.286초를 차지했다. **60초 게이트 초과를 C00에 보고했으며 축약하지 않았다.** 남은 제품 순회와 fixture 준비 비용을 분리한 뒤 다시 측정한다. 전체 XML은 같은 증거 폴더의 `new1.xml`이다.
- 선택 UI 회귀의 첫 대조는 87 PASS·24 FAIL이었다. 초기/주기 감사 완료마다 불필요하게 inventory를 다시 예약하는 자체 연결을 고치고 재검증 중이다. 초기 미검증·이력 충돌 상태에서는 `ContentStore.__init__`의 기존 `library.list_sessions()` 생성 검사 때문에 창 자체가 열리지 않는 별도 범위 문제가 확인됐다. 기존 시험의 단언을 바꿔 이 실패를 숨기지 않는다.

현재 추가 범위 요청은 (1) §15.1의 app/recording.py 명시 stop 문맥 연결, (2) tests/unit/test_index_failure.py·tests/integration/test_index_failure.py의 승인된 검출 시점·capture/관리 구분 최소 적응, (3) tests/integration/test_pending_deletion_restart.py의 C0~C2 hook 위치 최소 적응, (4) content/store.py 생성 검사 한 곳의 로컬 열림 검사 분리다. **아직 이 다섯 파일에 쓰지 않았다.** 관련 결정과 직렬 착수 신호를 받은 뒤 적용한다. C0~C2는 기존 hook을 새 공개 삭제 경로에 붙여 각각 `hits=[]`, `DELETED_LOCAL`로 통과해 버림을 직접 확인했다. staged fsync의 위치가 달라졌으므로 kill/unwind 기대표를 약화하지 않고 주입 지점만 옮겨야 한다.

정본 형식 1과 `user_version=1`은 유지한다. 구현 중 추가한 `storage_visible_sessions`·`storage_pending_deletions`·`storage_catalog_meta`는 권위가 아닌 **재구축 가능한 조회 투영**이다. canonical journal·deleted_sessions·검증된 process-local floor를 대체하지 않는다. G-P09는 이 파생 표를 버전 목록에 식별하고 복원 뒤 재구축하며, 파생 표만으로 삭제·미삭제나 권위 완전성을 승인해서는 안 된다. page cursor는 root instance·catalog version·마지막 key에 결속하고 k≤128을 검사한다. 정상 delta는 정확 키만 변경하며 full-audit 시작 시각을 연장하지 않는다.

### 15.4 범위 결정 대기 시점의 검증

`new1.xml`의 실제 node에서 정본 **390개·고유390개**를 감사했다(A180·B98·C48·H16·I8·J32·K8). 이후 cursor 타입/범위·root/catalog 결속·관측 시계 실패의 보강10행을 추가했다. 현재 계획은 정본390과 별도 보강20이며, 보강을 정본 분모에 합쳐 승인 행 수로 쓰지 않는다.

최신 소유 파일만 같은 사본에 반영한 선택 실행은 **386 PASS·24 deselected, 19.10초**였다(`fast2.xml`). 제외한 것은 H16 및 K8이며, 전체 PASS가 아니다. 이 시점의 격리 사본 `mypy src/recoryn scripts packaging`은 **97파일 PASS**, 소유 실행 파일의 ruff check/format도 PASS였다. GS-P06 제출 manifest의 **11파일 LF hash 불일치0**을 재확인했다(`progress-scope.json`). 임시 사본 mutation17·규모별 최종 측정·CI 동등 전체 coverage/회귀는 아직 완료하지 않았다.

따라서 IMPLEMENTATION_READY가 아니라 **SCOPE_NEEDED**다. 범위 요청 파일 다섯 개는 여전히 수정0이며, 승인 전에는 GS-P06 소유 app/recording.py와 다른 단위의 content/store.py를 수정하지 않는다. 특히 capture stop의 문제를 관리 API 전체의 허용 fallback으로 덮거나, ContentStore 생성 검사를 성공 빈 목록으로 속이지 않는다. 두 경계의 실제 호출을 명시적으로 분리한 뒤 K8·초기 미검증 GUI·기존 회귀를 다시 실행해야 한다. 312.51초 시간 게이트 초과는 행 축소 없이 보고했으며, 남은 H 순회 제거와 fixture/측정 비용 분리 뒤의 실측으로 예산 결정을 요청했다.

## 16. C00 범위 승인과 GS-P06 푸시 뒤 재개

### 16.1 승인 이력과 기준

C00은 §15.1~15.4를 검토한 뒤 추가 다섯 파일을 승인했다. 범위는 **12→17파일**, 정본은 **390행(K8 포함)**으로 유지한다. 신규 네 파일은 단독 목표90초·상한150초로 바뀌었으며 초과하면 행을 줄이기 전에 다시 보고한다. H=10,000 데이터는 모듈 범위에서 한 번 만들고 실제 독립 파일로 빠르게 복제한다. O(1) 판정은 H=1,000/10,000의 파일시스템·SQLite 호출 수가 같다는 구조 oracle이며, 시간은 측정값이다.

G-P17c 우선 배정 동안에는 GS-P11a 17파일 LF 해시가 그대로 보존됐다. 이후 C00의 **GS-P06 푸시 신호(5aa988e)**를 받아 app/recording.py의 직렬 수정 조건이 닫혔다. 재개 기준은 `5aa988eefacc5c249e0a3abbd534e6666894a672`이며 17파일 기준 해시와 새 격리 사본은 `build/gs11a-evidence-f775b59cea/phase2-input.json`에 고정했다. 최종 제출 검증 때 HEAD를 다시 고정하며, G-P17c의 미커밋 파일을 이 단위 소유 파일로 취급하지 않는다.

### 16.2 명시 capture 문맥과 관리 권위의 분리

RecordingService는 생성 당시 root·Library 실행 instance·세션과 별도 controller 등록 토큰을 저장한다. stop은 source 종료 ACK·consumer 종료·sealer 종료를 관측하고 동일 root/instance/session인지 확인한 뒤 Library에 문맥 발급을 요청한다. Library는 등록된 같은 owner·현재 run·호출 thread·자기 삭제 fence·활성 writer/sealer 부재를 root mutex 안에서 다시 검증한다. 단순 owner 존재나 caller stack으로 승격하지 않는다.

문맥은 **stop 내부 recover_session/finalize_session 호출에만** 전달한다. 기본 관리 API 호출, CLI/UI 확정, Job 입장과 게시에는 전역 snapshot 요구가 남는다. capture 종료가 전역 감사 I/O 오류·만료 때문에 막히지 않아도 새로운 전역 receipt는 발급되지 않는다. resume 뒤 run 변경, root/instance 교체, 다른 thread, source/consumer/sealer ACK 누락은 문맥 재사용을 거부한다. 관측 메서드는 root에서 호출되므로 gate·다른 잠금·I/O·대기를 하지 않는다.

### 16.3 승인된 기존 파일 최소 적응과 oracle 변경 이유

아래는 승인된 기존 fixture/단언 적응의 의미별 목록이다. 기존 파일을 통째로 새 oracle로 바꾼 것이 아니다. 새 공개 경로의 A/B/C/J/K 시험과 구조 계측이 별도로 승인된 검출 시점·권한 경계를 검증한다.

| 파일·변경 단위 | 실제 실패 원인과 변경 | 유지·강화한 기대 |
| --- | --- | --- |
| `content/store.py` 생성 검사 한 곳 | list_sessions가 전역 권위를 요구하면서 초기 미검증/이력 충돌 시 창 생성까지 실패했다. 생성 검사를 `check_local_catalog()`로 분리 | 단 한 줄 변경. 빈 목록 성공을 반환하지 않으며 목록/게시의 전역·자기 삭제 검사는 유지. G-P09 후속은 이 생성/관리 구분을 보존 |
| `unit/test_index_failure.py` 환경·consume fixture | 과거 get/chunks/Job가 전역 cold 검사를 암묵 실행하던 가정이 A 정책과 다르다. 기존 실패 cache 판정은 명시 control 관찰 adapter로 실행하고, Job은 공개 deep 검증 뒤 hot lease로 관측 | content 실패/같은 tick/미래 mtime/수선/실패 관찰 순서의 기존 기대 유지. 새 K8은 adapter 없이 get/chunks/create/stop을 직접 호출 |
| 같은 파일의 Job I/O 계수 | 실패 cache 수선과 명시 전역 재검증이 각각 읽으므로 기존2회가3회가 된다 | 실측 reader 호출 수를 정확히3회로 검사. hot Job의 본문/열거0은 별도 H/I 구조 oracle로 검사 |
| 같은 파일의 같은 tick·새 유효 의도 | 무통지 외부 변경은 명시 검사에서 채택/거부된다. 손상·관찰 역전 fixture가 control 검출 시점을 명시하도록 변경 | `HISTORY_UNAVAILABLE`과 자기 삭제 fence 거부를 구분하고 세션 재허용0 유지. 새 이력의 진위를 자동 인증했다고 쓰지 않음 |
| 같은 파일의 root/Job 구조 계측 | 성공 hot 경로는 과거 cold 본문 예외를 사용할 이유가 없다 | root 예외는 deletion-journal 이름 목록뿐, Job 경로에서는 열거0. mutex 안 본문 읽기 허용을 제거하여 강화 |
| `integration/test_index_failure.py` actor·수선·재열기 | 관리 호출이 이제 자체 검사하지 않으므로 외부 손상/수선 뒤 명시 fresh 검사를 호출하고 해당 결과로 fail closed 확인 | 원본 보존·정확 권위·자기 삭제 거부·실제 동작 결과 단언 유지. 재열기 뒤에는 로컬 get이 아닌 관리 권위의 상태를 확인 |
| 같은 파일 LIFE의 일시 I/O 오류 | 승인 K8에 따라 한 번의 감사 공유 위반이 녹음 종료를 막아서는 안 된다 | 검사 결과 UNAVAILABLE, 녹음 수락 유지, stop 정상·원본 보존을 확인. capture가 전역 권한을 새로 발급하지 않음 |
| 같은 파일 PCM의 이력 seed | 라이브 Library 밖에서 기록한 다수 tombstone을 즉시 신뢰하던 fixture가 됐다 | seed 뒤 닫기/재열기로 최초 검증 시점을 명시. 생성한 이력 수·PCM 보존·계측 단언은 유지 |
| `integration/test_pending_deletion_restart.py` C0~C2 주입 hook | 공개 삭제가 root의 staged 파일 sync 뒤 canonical rename으로 게시되면서 과거 atomic_json hook이 실행되지 않았다 | C0는 staged 기록 전, C1/C2는 canonical rename 전/후로 이동. kill/unwind 기대표와 GC-P02의 `management_fs_under_mutex == []`·0.5초 상한은 그대로 |

이 절은 승인된 변경 근거를 남기는 중간 이력이다. 최신 신규 시험 시간·정상본 전수·mutation·규모별 성능·CI 동등 coverage가 완료되기 전에는 IMPLEMENTATION_READY로 집계하지 않는다. 추가 범위가 필요한 기존 fixture 실패는 실제 결과와 최소 diff를 먼저 C00에 요청한다.

## 17. 재개 뒤 직접 검증과 추가 결정 요청 — 중간 보고

### 17.1 신규 행과 시간 게이트

`5aa988e + 승인17파일`의 새 사본에서 명시 capture 제어 연결 뒤 신규 네 파일 **419 PASS·520.14초**를 직접 확인했다(`new2.xml`). testcase 합은 unit1.082초·property0.040초·authority19.279초·races498.205초였다. H=10,000 네 행은177.878/137.063/68.923/70.859초였다. 정본390행을 줄이지 않고150초 상한 초과를 C00에 보고했다.

fixture의 물리적 독립성은 유지하면서 Windows에서는 CopyFileW를 사용하고 다른 플랫폼은 shutil.copyfile을 사용하도록 복제를 바꿨다. 하드 링크나 제품 parser/권위 판정 우회는 없다. 복제된 실제 파일은 그대로 공개 Library 초기 검증을 거친다. 재측정은 **428 PASS·332.52초**였다(`new3.xml`, `new3-scale.json`). H=10,000의 복제는 각각7.084/7.022/7.178/7.523초로 줄었지만, 네 독립 사본의 최초 검증은53.026/55.595/73.505/72.347초였다. 따라서 아직150초 상한을 통과한 것이 아니다. **실제 최초 검증을 유지하는360초 예산을 C00에 요청했으며 미승인 상태**다.

실제 node의 정본 감사는 A180·B98·C48·H16·I8·J32·K8 = **390개·고유390개·누락/중복0**이다(`new3-audit.json`). 이때 보강은38개로 정본 분모에 합치지 않았다. 이후 관찰 역전2·시작 UI3·감사 중 반복 거부 조회2를 별도 X ID로 보강해 현재 수집 예정 수는 **정본390+보강45=435**다. 이 최신435행을 한 번에 통과했다고 집계하지 않는다.

H=1,000과10,000에서 같은 트랙/관리 동작의 OS·SQL 호출 수가 정확히 같았다. 세 차례 claim/fail의 본문·열거·전체SQL scan은0, SQL156회·stat256회였고, 세 차례 삭제는 자기 journal 본문3회·열거0·전체SQL scan0, SQL129회·stat1048회였다. 모든 H16행에서 1·2트랙의 실제 수락 bytes/frame·저장 bytes/frame·QUEUE_DROP 회계를 직접 대조했다. 이 실행의 거부0은 측정값이며17b 처리량 해결이나 실제 장치 보장을 뜻하지 않는다.

### 17.2 실제 창·장치 모사 경계와 관찰 세대 수정

새 offscreen 시험은 최초 미검증·감사 I/O 오류·다른 ID의 손상 이력 세 상태에서 실제 MainWindow·ContentStore·DesktopRecorder를 사용한다. policy 저장 위치는 TEMP로 지정하고 credential backend 접근은 실패시키며, 장치는 합성4frame만 제공하는 source다. 감사 worker를 Event로 멈춘 상태에서도 창이 열리고, 목록은 미검증을 오류로 알리며, 실제 source 종료 ACK·writer/sealer ACK 뒤 stop과 원본 bytes 보존이 성공하는지 확인한다. 실제 장치·음성·vault·네트워크를 쓰지 않는다.

이 과정에서 최초 감사가 끝나기 전 단순 거부 조회도 stamp 불일치로 관찰 세대를 계속 올려, 정상 감사 결과를 버리는 구현 결함을 직접 확인했다(`ui-startup.xml`, `ui-startup2.xml`). 수정은 **마지막으로 관측한 metadata stamp와 검증된 stamp를 분리**하는 것이다. 실제 새 stamp 관측만 한 번 무효화하고, 미검증이라는 사실 자체로 같은 scan을 반복 취소하지 않는다. 권한은 여전히 검증된 stamp 일치·현재 receipt·30초 시한을 모두 요구한다. 정상 delta는 TTL을 연장하지 않는다.

수정 뒤 창3행 **3 PASS·1.97초**, 최신 신규 선택 실행은 **419 PASS·H16 deselected·38.34초**였다(`ui-startup3.xml`, `fast-observation.xml`). 최초/metadata 변경 뒤 감사 worker와 겹쳐 다섯 번씩 Job·page 거부 조회를 해도 epoch가 변하지 않고, 완료된 fresh 감사 뒤에만 첫 claim이 가능함을 추가로 확인했다. 부모·자식 import는 새 사본 src, 정적 검사는 ruff PASS·format223파일 PASS·mypy97파일 PASS다(`phase3-imports.json`, `static-epoch.json`).

G-P05 파일을 제외한 기존 관련/UI 회귀는 앞 버전에서4,429 PASS·새 STAGE 보강1 FAIL이었다. 실패는 lazy writer가 파일을 만들기 전 크기를 읽은 시험 준비 오류였으며, 먼저 prefix를 쓴 뒤 추가 쓰기 거부와 bytes 불변을 검사하도록 고쳐 `new3.xml`에서 통과했다. 이를 기존 전체 회귀 PASS로 바꾸어 쓰지 않는다. 최신 전체/UI·CI 동등 coverage 검증은 아직 남았다.

### 17.3 변이의 직접 결과와 재검증 경계

이 시점의 임시 사본17개에서 a의 **M01~14·M20·M32·M33 17/17**을 독립 단언으로 검출했다. 정상 대조군154 PASS, collection 오류0이며 각 사본의 실제 package/library/index import 경로를 확인했다. `mutation-plan.json`, `mutation-results.json`, M별 XML/로그에 정확한 치환·검출 node·결과를 남겼다. PYTHONPATH는 각 사본 src이며 pyproject·src·tests·scripts·packaging을 함께 복사했다.

이 변이 결과는 §17.2의 관찰 stamp 수정 **전 이력**이다. 최종 제품 코드가 고정되면 치환 위치를 갱신해17개 전부 다시 확인한다. 이전 결과를 최종본 재실행으로 주장하지 않는다. 삭제가 영속화되기 전 예약 fence, publisher 안에서 시한 만료 시 SQL rollback, 실제 source ACK 없는 stop 거부, 늦은 성공/실패 관찰의 repair 덮기 금지를 별도 X oracle로 보강했다.

### 17.4 G-P05 fixture 범위와 중단된 staged 의도 결정 요청

관련 실행은 **20 FAIL·779 PASS**에서 중단됐다(`related2.xml`). G07 journal-only5행은 독립 seed 뒤 cold Library를 재열도록 준비를 고쳐 기존 JOURNAL_ONLY·거부/ACK 단언을 유지했다. 남은 G05 RETRY/LIVE의 외부 journal seed와 PERF 준비는 현재 승인된 C0~C2 hook 범위를 넘으므로 아직 고치지 않았다. 별도 unit 실행에서도 `test_pending_deletions.py`의 INV10행이 같은 준비 문제로 실패했다(2,936 PASS 뒤 중단, `unit4.xml`). 이 unit 파일은 **현재17파일 밖**이므로 수정0이다.

C00에게 다음 추가 결정을 요청했고 답을 기다린다.

1. `integration/test_pending_deletion_restart.py`에서 C0~C2 외의 fixture 준비 시점만 초기 열기 전 seed/명시 재열기로 적응. 기존 기대표·readonly·원본/세대/권위·GC-P02 구조와0.5초 상한은 유지.
2. `unit/test_pending_deletions.py`를18번째 파일로 추가하되 같은 fixture 준비만 적응. 단언 변경이 필요하면 다시 요청.
3. C1 kill이 root의 `.deletion-stage-*.json`을 남기는데 현재 재시작 검사가 이를 누락하는 실제 반례의 처리. 제안은 owner 없는 staged/atomic 임시 파일을 control 최초/fresh 검사에서 미완료 의도로 검출하여 전역 권위를 UNAVAILABLE로 두고, 식별 가능한 대상에는 부정 fence를 유지하는 것이다. **temp를 완료 tombstone·허용 권한으로 채택하거나 자동 제거하지 않는다.** 진행 중인 이 프로세스의 파일은 등록된 작업과 대조해 다른 세션 capture를 전역 차단하지 않는다. C1의 HISTORY_UNAVAILABLE 기대표는 유지하되 임시 파일 위치 단언만 새 프로토콜에 맞추며, G-P09에 이 미완료 증거의 backup/restore 보존·quarantine 인계를 기록할 제안이다. 아직 제품 수정/단언 변경을 적용하지 않았다.

결정 전까지 staged 처리·G05의 위 추가 범위 파일은 수정하지 않는다. 이는 요청한 쓰기 제한 때문에 필요한 승인이다. 보류 사실을 정상 빈 목록이나 삭제 완료로 바꾸지 않는다.

### 17.5 규모 비교의 증거와 남은 게이트

OS TEMP의 실제 format1 journal·SQLite를 H=0/1,000/10,000/100,000으로 늘리며 `5aa988e`와 작업 사본의 공개 Job claim/fail·목록·모사1/2트랙을 비교 중이다. source/cwd/PYTHONPATH와 각 actor 결과는 `scale-base.json`, `scale-data.json`, `scale-results.json`, `scale-*-before/after.json/log`에 남긴다. 작은 S 차이는 각 결과의 listed_sessions로 명시한다. fake clock으로 실제 권한 수명을 늘려 성능 성공을 만들지 않으며, 30초를 넘긴 실제 감사는 UNAVAILABLE로 따로 기록한다.

이 비교 사본의 runtime 해시는 `scale-runtime-hashes.json`으로 별도 고정했다. §17.2의 최신 관찰 stamp 수정 사본과 혼동하지 않는다. H=100,000 비교는 이 절 작성 시 아직 진행 중이다. 기존 문서의1.94/45.26/598.98ms를 이번 직접 측정값으로 가져오지 않는다.

현재는 **SCOPE_NEEDED/시간 예산 결정 대기**다. 남은 것은 승인된 추가 fixture·staged 처리, 최신본 전 변이/관련/UI 회귀, 최종 HEAD+소유 파일만인 새 사본의 CI 동등 전체 coverage/check_coverage·전체 오프라인 회귀·파일 범위/최종 LF 해시 감사다. G-P17c 커밋도 그때의 HEAD 기준에 반영하며, 이 문서의 중간 PASS 수치로 단독 최종 승인하지 않는다.

## 18. 승인 대기 중 보강과 규모 비교 완료 — READY 아님

### 18.1 최신 제품 보강과 선택 검증

§17.2의 관찰 stamp 수정 뒤, 실행 인터프리터가 보고하는 time/monotonic 해상도를 관측 오차의 하한에 반영했다. 1ms를 무조건 실제 해상도로 간주하지 않으며, 이 오차는 두 시계 비교에만 사용한다. 어느 쪽의30초 만료 상한도 늘리지 않는다. 조악한 UTC tick이 그대로인12ms 관측과 정확히30초인 만료를 손 시각으로 대조하는 X 시험을 추가했다.

승인된 절전/복귀 통지의 무효화도 기존 UI·감사 controller에 연결했다. suspend는 receipt를 무효화하고 기존 controller의 요청을 보류하며, resume는 다시 무효화한 뒤 같은 executor에 검사를 요청한다. 내용 손상의 fresh 요구를 자동 완화하지 않는다. 실행 중/대기 중 worker의 실제 ACK는 그대로 기다리며 새 pool/thread를 만들지 않는다. `verify_deletion_history`의 순수 `can_publish` 관측 gate를 Root에서 입장·게시 직전에 확인하여, 통지/종료와 교차한 감사가 새 receipt를 게시하지 못하게 했다. gate는 잠금·I/O·대기를 하지 않는 호출자 관측값만 받는다.

추가 기존 회귀(`unit-rest.xml`)는 **4,745 PASS·10 FAIL**이었다. 이 중 missing-history가 FileNotFoundError로 새던2행과 자기 DB status 검증을 SELECT1로 생략한1행은 제품 Library 안에서 보강했다. metadata 접근 실패는 닫힌 HISTORY_UNAVAILABLE로 정규화하고, 자기 DB generation/status를 검증하며, 발견한 권위 오류는 기존 receipt를 무효화한다. 해당 기존3행과 최신 unit/창/절전 선택은 **76 PASS·2.37초**였다(`power-guards.xml`). 기존 시험 파일은 이 보강을 위해 수정하지 않았다.

최신 사본의 ruff PASS·format223파일 PASS·mypy97파일 PASS다(`static-current.json`). 변이는 최신 관찰·절전 guard가 있는 사본에서 정상 대조157 PASS 후 **계약17/17 + 보강 X01/X02 2/2**를 검출했다(`epoch/mutation-results.json`). X01은 게시 직전 취소 관측 제거, X02는 절전 통지 때 기존 권한 무효화 제거다. 이 결과도 아직 미구현인 staged 처리의 최종 검증으로 쓰지 않는다.

현재 새 시험의 수집 예정 수는 **정본390+보강50=440**이다. §17.1의428행 단독 시간은 그 당시의 실측 이력이며 최신440행의 전체 단독 실행 시간으로 바꾸어 쓰지 않는다.

### 18.2 추가로 필요한 세 시험 파일의 제한적 적응 요청

§17.4의 pending-deletions unit 추가 요청에 더하여, 실제 실패를 근거로 아래 세 파일을 요청했다. 전부 답을 기다리며 아직 수정0이다. 모두 승인되면17→21파일이며, 제품 파일 추가 요청은 없다.

| 파일 | 실제 실패와 최소 변경 제안 | 유지할 단언 |
| --- | --- | --- |
| `tests/unit/test_seal_phases.py` | same-tick/changed-while-reading의 전역 손상 판정을 승인된 명시 관리 검사에서 대조하고, 로컬 self 조회는 분리. publish wrapper2행은 새 prepared_path를 전달 | 전역 불명 거부·자기 I1·capture 이름 fence는 유지. 이미 제품에서 고친 자기 DB status 행의 기대는 변경0 |
| `tests/unit/test_storage.py` | journal-only seed의 최초 검증 준비. P11 false 분기는 append 성공이면 DELETE_PENDING, 정확한 삭제 의도 오류로 append가 거부되고 실제 writer/파일이 남지 않았으면 DELETED_LOCAL도 가능한 선후로 제안 | 임의 예외 허용 금지·seal 거부·abort·재삭제·staging/final 부재 유지. 이전 G-P17a의 DELETE_PENDING 고정과 달라 C00 결정을 요청 |
| `tests/integration/test_unfinished_recovery.py` | 900묶음 입력 준비 중 최초 receipt가 만료되어 관리 동작이 입장 즉시 거부됨. 준비 뒤 명시 검증하는 최소 적응 | 관리 mutex 보유·파일시스템 구조·claim 경쟁·보존·측정 종료까지의 기존 단언 유지 |

즉, fixture/단언을 임의로 약화하여 PASS를 만들지 않았다. 900묶음 관리 작업 자체가30초를 넘는 경우의 계속 조건은 실제 재실행으로 확인하며, 추가 계약 판단이 필요하면 다시 보고한다.

### 18.3 실제 규모 비교 완료와100,000건의 운영 한계

§17.5의 비교는 완료됐다. 1트랙의 직접 관측값은 다음과 같다. H≤10,000은 각3표본 중앙값, H=100,000은1표본이다. S는 작은 양의 세션 수이며 각 JSON에 별도 남겼다. 단순 시간 비교만으로 복잡도를 승인하지 않고 앞의 H/I 호출 수 oracle과 함께 본다.

| 완료 이력 H | HEAD claim / fail / 목록 (ms) | 작업 사본 claim / fail / 목록 (ms) | 작업 사본 결과 |
| ---: | --- | --- | --- |
| 0 | 5.015 / 4.756 / 1.678 | 3.153 / 3.723 / 0.959 | 성공, hot 전체 canonical 읽기0 |
| 1,000 | 646.566 / 612.852 / 565.232 | 3.168 / 3.084 / 1.360 | 성공, hot 전체 canonical 읽기0 |
| 10,000 | 6,862.177 / 6,066.529 / 6,098.813 | 1.728 / 1.615 / 2.525 | 성공, hot 전체 canonical 읽기0 |
| 100,000 | 89,674.165 / 79,618.661 / 89,631.025 | claim·목록 모두 HISTORY_UNAVAILABLE, fail 미실행 | **차단**. 빠른 거부를 빠른 성공으로 집계하지 않음 |

H=100,000의 작업 사본 최초 검증은58.366초, 명시 전체 재검사2회는60.593/60.418초였다. 세 번 모두 검증 시작 기준30초를 넘어 receipt가 없었으므로 Job·목록을 거부했다. L을 늘리거나 fake clock을 주입하지 않았다. 이 PC/format1에서의 큰 H 운영 한계이며, 압축11c나 승인된 별도 검사 구조가 필요함을 C00에 보고한다. 이를 근거로 이번 단위에서 성공 cache를 무기한 허용하거나 A의 보안 결정을 바꾸지 않는다.

각 H의 HEAD·작업 사본 × 1/2트랙, 총16개 모사 녹음에서 실제 수락 bytes와 저장 bytes를 대조했고 거부0·수락 저장 일치를 관측했다. H=100,000의 Job·목록이 차단된 작업 사본에서도 녹음·stop은 정상 종료했다. 녹음 도중 Library 관리 mutex 최장은 H=10,000에서 HEAD70.433/72.576ms 대 작업 사본3.143/3.376ms, H=100,000에서 HEAD663.474/1,215.893ms 대 작업 사본의 **거부 경로**0.204/0.205ms였다. 뒤 수치를 허용된 관리 작업의 성공 보유 시간으로 해석하지 않는다.

여전히 이 규모 비교는 §17.5의 고정 runtime 사본에 대한 직접 결과다. 최신 관찰 stamp·clock 해상도·절전 guard 및 승인 대기인 staged 처리의 최종 성능 결과로 소급하지 않는다. 최종본 검증 때 필요한 작업 사본 재측정을 하며, HEAD의25분짜리100,000건 비교를 다시 실행했다고 주장하지 않는다.

### 18.4 안전한 중간 상태

진행 중 시험/benchmark 프로세스는 모두 실제 종료를 회수했다. staged 처리·추가 네 시험 파일·360초 예산은 C00 결정 대기다. 승인17파일의 중간 LF 해시와 상태는 build 증거 폴더에 별도 고정하며, G-P17c 세 파일과 다른 작업자 파일은 수정하지 않았다. 최종 CI 동등 coverage·전체 회귀는 아직 남았고 현재 판정은 계속 **SCOPE_NEEDED**다.

## 19. H02/X00 승인 뒤 재개 — b77cc102 기준

### 19.1 결정과 정확한 쓰기 범위

X00의 GS04-R1 인수 및 GS11a 재개 신호를 받았다. 정본은 배정표 GS11의 APPROVED_SCOPE다. 시작 HEAD는 `b77cc102a9db818a8c1d1a2840933ffa28e1b14c`이며, 시작21파일 LF 해시는 `build/gs11a-resume-64393bb3e6/start.json`에 고정했다. 기존17파일은 동결 시 해시와 모두 일치했다. 아래21파일 외 제품·시험·공용 문서는 수정하지 않는다. GS04a 파일과 리뷰는 별도 소유이며 검증 사본에 섞지 않는다.

| 구분 | 정확한 파일 |
| --- | --- |
| 제품8 | `src/recoryn/storage/library.py`, `src/recoryn/storage/deletion_history.py`, `src/recoryn/app/history.py`, `src/recoryn/jobs/__init__.py`, `src/recoryn/ui/main.py`, `src/recoryn/cli.py`, `src/recoryn/app/recording.py`, `src/recoryn/content/store.py` |
| 신규 시험4 | `tests/unit/test_deletion_history_index.py`, `tests/property/test_deletion_history_index.py`, `tests/integration/test_deletion_history_authority.py`, `tests/integration/test_deletion_history_races.py` |
| 기존 시험8 | `tests/integration/test_blocked_reason_flow.py`, `tests/unit/test_index_failure.py`, `tests/integration/test_index_failure.py`, `tests/integration/test_pending_deletion_restart.py`, `tests/unit/test_pending_deletions.py`, `tests/unit/test_seal_phases.py`, `tests/unit/test_storage.py`, `tests/integration/test_unfinished_recovery.py` |
| 문서1 | 이 문서 |

신규4파일의 최신 정본390+보강50=440은 실제 수집·실행과 누락/중복을 다시 감사한다. 새 staged/P11 보강은 별도 ID 목록으로 구분하며 정본390의 분모를 바꾸지 않는다. fixture를 포함한 새 단독 command wall의 목표150초·조건부 상한360초를 적용하며 초과하면 먼저 보고한다. 과거428건/332.52초를 최신 결과로 소급하지 않는다. H16의 손 시각 기능 행과 실제30초 검증 권한 발급 성능을 구분한다.

### 19.2 staged 분류와 손 oracle

최초/fresh 관리 검사에서 알려진 삭제 프로토콜의 미완료 staged/atomic 파일을 발견하면 전역 UNAVAILABLE로 닫고 원위치 bytes를 보존한다. 온전한 staged 본문에서 식별한 자기 세션에는 부정 fence를 남기되, 이 파일을 완료 journal·tombstone이나 허용 권위로 채택하지 않는다. 손상 본문은 식별을 발명하지 않는다. 자동 이동·삭제·복구는 하지 않는다. 현재 root instance의 정확한 파일·nonce·등록 수명이 일치하는 자기 in-flight만 검사 예외로 삼으며 PID/이름 유사성으로 제외하지 않는다. 다른 세션의 capture는 전역 감사 경로로 되돌리지 않는다.

손 oracle는 (a) kill C1 뒤 재열기/fresh의 UNAVAILABLE, (b) 남은 파일의 위치와 원본 bytes 불변, (c) 식별 가능한 대상의 쓰기/게시 거부, (d) 무관 세션의 명시 capture 종료 ACK 허용, (e) 등록된 자기 진행 중 파일만 예외, 등록 해제·nonce/instance 불일치는 차단, (f) staged 내용만으로 미디어 제거·완료 상태 생성0이다. 최초/fresh의 파일 열거·해시·읽기는 root mutex/GUI/Job transaction 밖에서 수행한다. L30초·5초 요청·정상 delta로 TTL 연장 금지·K8·실제 ACK·hot 호출 수 oracle는 불변이다.

G-P09 인계: `deletion-journal/*.json` 정본과 함께 root의 알려진 `.deletion-stage-<nonce>.json` 및 해당 atomic 임시 파일을 위치·bytes 그대로 보존/복원해야 한다. 미완료라는 분류와 허용 권위가 아님을 유지한다. 실제 이동·수선·복원은 명시 유지보수 단위에서 결정하며 G09 문서는 이 단위가 수정하지 않는다.

### 19.3 기존 시험의 제한적 적응 사유

| 파일 | 수정 전 실제 근거·허용 적응 | 유지할 oracle |
| --- | --- | --- |
| `test_pending_deletion_restart.py` | §17.4의 RETRY/LIVE/CRASH fixture 실패. 외부 seed를 최초 열기 전으로 옮기거나 공개 fresh 검사로 준비하고 C0~C2 주입을 staged fsync 위치에 연결 | kill/unwind 기대표·삭제 권위·최대 세대·원본·GC-P02 mutex 안 FS 호출0·0.5초·live ACK 유지. C1은 원위치 미완료 분류 |
| `test_pending_deletions.py` | §17~18 unit INV의 열린 뒤 외부 seed가 새 receipt 정책과 불일치. seed-before-open/공개 fresh 준비로 한정 | 정합 표·보류 사유·목록/재시도·tombstone 단언 유지 |
| `test_seal_phases.py` | §18.2의 same-tick/changed-while-reading2행과 publish wrapper2행 | same-stamp 손상은 명시 관리 검사에서 검출. capture 자기 fence/I1 유지. wrapper는 prepared_path만 전달 |
| `test_storage.py` | §18.2의 journal-only 준비 및 P11 False 합법 선후 | append가 정확히 `Writer session has a deletion intent` StateConflict로 거부되고 active writer·staging/final 부재를 직접 확인한 경우만 DELETED_LOCAL. append 성공 또는 writer 존재 시 DELETE_PENDING. seal 거부·abort·재삭제·최종 부재 유지 |
| `test_unfinished_recovery.py` | §18.2의 900묶음 입력 준비 중 receipt 만료 | 준비 뒤 공개 fresh 검증. 관리 mutex·FS 구조·claim 경쟁·원본 보존·측정 종료 상한 단언 불변 |
| 기존 승인 `test_index_failure.py` 2파일·`test_blocked_reason_flow.py` | §16~18에 기록한 검출 시점/fixture 준비 차이만 유지 | 명시 관리 전역 실패 폐쇄·capture 자기 fence·Job transaction 보호·철회/삭제 우선순위 유지 |

기존 단언을 임의 예외나 느슨한 허용 집합으로 치환하지 않는다. 최신17+2 변이와 staged/제한된 P11 선후의 새 변이를 정상본 PASS 뒤 목표 assertion 실패로 확인한다. 최종 검증은 시작 BASE+승인21파일만인 새 archive 사본, 사본 src PYTHONPATH·부모/spawn import 확인, offscreen·고유 TEMP·cache 비활성·ResourceWarning error·CI 동등 coverage7묶음·offline wheel로 수행한다. 이 절은 승인·시험 설계 기록이며 새 PASS 결과는 아직 없다.

### 19.4 재개 뒤 확인한 최소 적응과 X00 보충 승인

- `adapted-first`는354 PASS·116 FAIL이었다. 대부분 열린 뒤 외부 seed가 이미 검증된 map과 불일치한 fixture였다. fresh가 임의 외부 본문을 승격하도록 제품을 완화하지 않고, seed 뒤 새 Library 최초 관측으로 준비했다. LIVE fixture의 원래 owner/reader/writer와 강한 참조는 유지하고 새 Library에 같은 관찰 owner를 다시 등록했다. GEN의 실제 세대 충돌은 전역 권한 UNAVAILABLE를 유지한 채 pending/retry의 기존 DELETE_HISTORY_CONFLICT 진단으로 전달한다.
- G15 same-tick/읽기 중 변경은 명시 전체 검사 뒤 전역 목록 거부를 단언하고, 로컬 self 조회는 따로 성공시켜 capture/관리 경계를 고정한다. G05의 완료 tombstone 경로 검사는 명시 관리 검사에서 다시 관찰한다. 완료 후보의 경로 확인도 control lane/root 밖에서 수행하며, 경로 불명을 완료로 추정하지 않는다.
- `adapted-first`의 G04-K5-stop-finalizing은 자식이 finalize_session의 옛1인자 lambda에서 capture_control keyword TypeError를 내어 장벽 전에 종료했다. X00은 실제 재현을 확인하고 **기존 허용 파일의 이 시그니처1곳** 적응을 별도 승인했다. 대역은 필수 keyword-only capture_control을 받고 기존 pause()에 도달한다. 제품·중단 지점·상태/원본/claim 단언·timeout은 변경하지 않는다.
- 준비 쓰기는 root의 `.deletion-atomic-<nonce>.json`에서 fsync한 뒤 `.deletion-stage-<nonce>.json`으로 옮긴다. 두 이름·실제 파일 ID·root instance·nonce·토큰의 등록 수명을 대조한다. 현재 actor의 정상 unwind가 정확히 소유한 파일을 정리하는 기존 C1-unwind=NO_INTENT 의미는 유지하며, kill 뒤 남은 파일은 검사자가 이동/삭제하지 않는다. 구형 root `.tmp-<32hex>`도 알려진 atomic 프로토콜의 미완료로 보존한다. G09는 이 세 root 프로토콜과 canonical journal을 위치/bytes 그대로 인계받는다.
- 초기 신규4 선택은 옛 atomic 주입점1곳으로423 PASS·1 FAIL이었다. 새 staged 선택의6 FAIL·19 PASS는 Windows FileIO.name을 경로로 가정한 시험 장벽 오류였다. 새 준비 함수/원자 rename 장벽으로 고정한 뒤25 PASS였으며, 이후 소유 등록이 미확인인 분기를 추가했다. 최종 단독 최신 행수·시간은 아직 새 실행으로 확인해야 한다.

### 19.5 재개 보강 분모·mutation의 추가 설계

정본은 §14.5대로 A180+B98+C48+J32+H16+I8+K8=390이다. H/I는 전역 ID의 승인된 부분집합이며 재번호화하지 않는다(H001/003/…/031, I001/003/004/006/007/009/010/012). 재개 전 보강50은 별도 node 목록으로 보존한다. 이번 추가는 orphan18(프로토콜 stage/atomic/legacy3×본문 valid/partial/future3×initial/fresh2), owned8(none/instance/nonce/identity/unproven/unregistered/lifetime/late_lifetime), 최종 관측 뒤 새 경로 경합1, P11 write-first/delete-first2로 총29행이다. 최종 계획은 **정본390+보강79=469**이며 primary ID를 재번호화하지 않는다. 실행 전후 XML에서390의 독립 literal 집합과79개 보강 node를 따로 감사한다.

등록 수명 경합의 손 oracle: 실제 준비 쓰기의 원자 rename 전 장벽에서 파일 ID와 등록을 유지한다. 전체 검사 두 번째 staged 관찰을 마친 뒤 등록 수명만 철회하고 stage epoch를 바꾸되 root directory stamp와 bytes는 유지한다. 최종 게시가 UNAVAILABLE이어야 하고, 권한을 발급하지 않아야 한다. 이는 시각/stamp 검사만으로 통과하는 생존 변이를 막는다. 기존 새 경로 경합은 반대로 epoch를 바꾸지 않고 실제 root 경로/stamp를 변경하여 독립 조건을 확인한다.

최신17+2 변이에 추가할 단일 결함은 S01 프로토콜 검사 생략, S02 instance 생략, S03 nonce 생략, S04 수명 생략, S05 파일 ID 생략, S06 등록 미확인을 영구 내용 실패로 처리, S07 고아의 식별 가능한 자기 fence 누락, S08 고아 자동 삭제, S09 최종 stage epoch 검사 누락, S10 최종 root stamp 검사 누락, S11 active writer의 pending 응답을 완료로 오표시다. 각각 정상본 PASS 뒤 독립 손 oracle의 목표 assertion 실패·error0을 요구하며 동등/수집 오류를 검출 수에 넣지 않는다. 합계는17+2+11=30개다.

지금 완료한 `new-standalone`은 **468 PASS·pytest343.67초/command wall344.23초**다. 이는 late_lifetime1행 추가 전의 직접 관측이며 최종469행 시간으로 소급하지 않는다. 최종 정상본에서 fixture 포함 단독 wall을 다시 재며360초 초과는 먼저 보고한다.

### 19.6 계측 구분·명시 허용 오라클 보강

X00은 G05-PERF에서 inventory 대상 stat의 inside0/outside 양성을 추가 승인했다. retry에서는 기존 `_remove_and_seal`의 **단일 `_media_present` 완료 확인**의 stat만 별도 측정하고, 나머지 잠금 안 대상 stat은 계속 거부한다. 실행 문맥 표시는 시험용 wrapper/thread-local에만 두며 제품 권한 판정에 caller stack을 사용하지 않는다. 기존 iterdir/scandir/listdir/remove_tree 감시·under0·outside 양성·0.5초·원본/완료 단언을 유지한다. 승인 후 두 행은2 PASS였고, inventory는 stat outside800/inside0·관리 root34.47ms, retry는 완료 확인1회/stat2회·그 외 inside0·삭제 outside1·관리 root1.96ms였다. 두 행 모두 거부0·수락=저장이었다.

`new-latest`는469 PASS·pytest345.54초/pytest command wall346.28초/사본 준비와 import 확인을 포함한 harness wall347.37초였다. 독립 감사에서 A180/B98/C48/H16/I8/J32/K8=390의 누락·중복·초과0, 보강79의 중복0을 확인했다. 첫 감사 스크립트의 H/I 연속 ID·K 누락 가정은 §14.5의 승인된 전역 부분집합으로 고쳤으며 제품/시험 ID를 바꾸지 않았다.

30개 변이의 첫 재실행은 정상 대조 PASS 뒤27개가 명시 assertion으로 실패했고, M10/M11/M32는 예상치 않은 제품의 닫힌 예외로 실패했다. 이3개를 엄격한 assertion 검출로 합산하지 않는다. 기존 성공 계약(정상 delta 수락, 삭제/만료 뒤 ACK 허용, 전역 실패 뒤 건강한 로컬 동작 허용)에 대해 해당 도메인 예외를 관찰값으로 받아 **예외 없음**을 명시 단언하도록 보강한다. 정상 결과·거부 결과·fence·기존 상태/원본 단언은 그대로이며 다른 예외/수집 오류를 검출로 숨기지 않는다. 행수469는 불변이고 변경된 정상본·단독 시간·30개 변이를 다시 실행한다. 앞의347.37초를 이 보강본 시간으로 소급하지 않는다.


### 19.7 명시 허용 오라클 보강 뒤 직접 검증

최신 정상본 `new-final.xml`은 **469 PASS·failure/error/skip0**이었다. 시험 명령 wall은334.5642초, Git archive·21파일 적용·부모/spawn import 확인까지 포함한 harness wall은335.6446초다. 두 값 모두 X00의 조건부360초 이내이며 목표150초는 달성하지 못했다. 앞의428/468/469 초기 시간과 이 결과를 구분한다. `new-final-id-audit.json`에서 정본390(A180/B98/C48/H16/I8/J32/K8)의 누락·초과·중복0, 보강79의 중복0을 직접 확인했다.

같은 제품/시험 정상본으로 `mutation-results.json`을 다시 생성했다. 중복 목표를 합친 정상 대조26 PASS 뒤 **계약17 + 기존 보강2 + staged/P11 보강11 =30/30**이 목표 단언 실패로 검출되었고 error0이었다. M10/M11/M32도 이번에는 성공 계약의 명시 assertion으로 실패했다. 이전의 제품 예외3건을 검출로 소급하지 않는다. 변경 대상·치환 전후·목표 node·정상/변이 사본 경로·로그·XML·입력 해시는 `build/gs11a-resume-64393bb3e6/mutation-plan.json`, `mutation-input-hashes.json`, `mutation-results.json`에 남겼다.

규모 측정은 실제 기본 clock을 사용한다. 첫 probe가 만료된 목록 조회의 닫힌 ValidationError를 관찰값으로 처리하지 못한 것은 probe 결함으로 별도 보존했다(`scale-first-*`). 제품을 완화하지 않고 Job/목록의 닫힌 오류를 각각 관찰하도록 수정했다. 재측정 및 CI 동등 전체/coverage/wheel의 최종 판정은 아직 완료되지 않았으므로 아래 최종 결과로 별도 기록한다.


### 19.8 최신 제품의 실제 clock 규모 측정 — 초기 검증 한계 포함

최신 제품20파일이 정상/변이 검증과 같음을 해시로 확인한 별도 격리 사본에서 실제 기본 clock으로 측정했다. 각 규모에서 Job은 미리 만든 서로 다른3개를 claim→fail했고 목록도3회 요청했다. 1·2트랙 각각300×480frame의 합성 PCM을10ms 간격으로 제출했다. 새 seed/사본 경로·명령·원시3표본·상태·본문 읽기·수락/거부·잠금 측정은 `scale-final-input.json`, `scale-final-results.json`, `scale-final-summary.json`, `scale-final-origin.log`에 남겼다. 수치는 아래와 같으며 최초 열기 시간은 constructor 전체 wall이고 감사 함수 단독 시간으로 바꾸어 쓰지 않는다.

| 완료 이력 H | 최초 열기 wall(초) | 1트랙 claim / fail / 목록 중앙값(ms) | 실제 전역 권한 |
| ---: | ---: | --- | --- |
| 0 | 0.01561 | 2.750 / 3.694 / 1.155 | READY,3회 모두 성공 |
| 1,000 | 5.56385 | 2.685 / 4.335 / 0.844 | READY,3회 모두 성공 |
| 10,000 | 52.82660 | 성공값 없음 | UNAVAILABLE. claim·목록 각3회 거부, fail 미실행 |
| 100,000 | 618.75664 | 성공값 없음 | UNAVAILABLE. claim·목록 각3회 거부, fail 미실행 |

1·2트랙×4규모의8개 조합에서 거부0·수락 bytes=저장 bytes·정상 FINALIZED 종료였다. 이 중 H=10,000/100,000의 녹음은 전역 권한 미검증 상태였으며, 로컬 종료 문맥의 실제 ACK로 닫혔다. hot 관리 호출의 canonical journal 본문 읽기는8조합 모두0회였다. 전체 경로 root 최대는13.9641ms, 관리 호출 root 최대도13.9641ms였다. H가 큰 차단 경로의 짧은 보유/거부 시간을 허용된 성공 성능으로 계산하지 않는다.

실제 clock에서 **10,000건도 검사 시작 기준30초를 초과**했다. §18.3의 이전 제품 단계에서1만 건이 성공했던 결과를 최신본으로 소급하지 않는다. 완료 tombstone의 미디어 부재 확인을 포함한 control-lane 전체 비용을 별도 프로파일로 확인하고 인계한다. L을 늘리거나 정상 delta/fake clock으로 권한을 승격하지 않았다. H16의 고정 손 시각은 hot 호출 수·기능 oracle이며 실제30초 안 검증 성공의 근거가 아니다. GUI 시작 경로는 defer_history=True와 기존 worker를 쓰므로 이 constructor 측정을 GUI thread 정지 시간으로 해석하지 않는다.

비교용 HEAD 측정은 §18.3과 `build/gs11a-evidence-f775b59cea/scale-*`의 과거 직접 결과를 재사용한다. `git diff 5aa988e b77cc102 -- src/recoryn` 출력0으로 기준 제품 소스 동일성을 확인했으나, 그25분 측정을 이번에 재실행했다고 주장하지 않는다. 이전 작업 사본의 after 성능은 최종 비교값에서 제외했다. 최신 before/after를 동시에 측정한 통제 실험으로 과장하지 않는다.


### 19.9 GS11A-G11C-L 추가 승인과 실제 실패

BASE+21 전체 실행에서 G11C-L-01/02가 실패했고, 같은 사본의 두 행 단독 실행도2 FAIL이었다(`resource-followup.log/xml`). 실패는 표시 조회가 아니라 `l_write_waits`의 대기 양성 표였다. 기존 표는 SUCCEEDED 게시가 root를 기다리지 않는다고 가정했으나 승인된 §14.2/§14.5에 따라 complete의 새 결과 게시에도 현재 삭제 권위 lease를 확인한다. 실제 대기는 약0.403초였고 표시조회100ms/최종상태/attempt 단언은 유지됐다.

X00은 **GS11A-G11C-L**로 `tests/integration/test_resource_followup.py`를22번째 파일에 추가하고, SUCCEEDED 한 항목과 인접 설명만 적응하도록 승인했다. HOLD/QUICK·차단 양성·표시 비차단·최종 상태·다른 oracle·ID24는 불변이다. 적응 후 L군24행은24 PASS·pytest12.07초/command12.60초였다(`g11c-l.xml`). 시작21파일 목록은 이력으로 보존하고 승인22파일 목록/기존 시작 해시는 `scope-approved22.json`으로 구분했다. 22파일 정확 사본의 CI 동등 전체/coverage/wheel은 새로 실행해야 하며, 진행 중21파일 실행을 최종 PASS로 쓰지 않는다.

### 19.10 G-P15 기존 검사 경계 적응 요청 — 승인 전 수정0

진행 중 전체 실행에서 `test_seal_mutex.py`의 IDX-FAIL7행·IDX-OPEN1행이 추가 실패했다. BASE+22의 해당19행을 단독 실행해 **11 PASS·8 FAIL·error0**으로 재현했다(`g15-idx-before.xml`). 해당 파일은 현재 범위 밖이므로 아래 최소 적응을 X00에게 요청하며 승인 전 수정0이다. 나머지 구조/성능/건강/봉인/삭제/원본 단언은 변경하지 않는다.

권고: 이 파일을23번째로 추가하고 `FAIL_TABLE`, `test_idx_fail_outside_changes_are_revalidated`, `test_idx_open_validates_once_and_fails_closed`의 검사 시점/손 oracle만 적응한다. 외부 변경 뒤 **명시 fresh 전체 검사**를 먼저 관찰하여 같은 stamp 변조를 확실히 검출한다. 로컬 자기 조회와 전역 관리 결과를 별도로 고정한다. 변경 ID/분모는 기존16+3 그대로이며 scope를 넓혀 다른 시험 단언을 고치지 않는다.

| 외부 상태 | 자기 get a / b / j 손 기대 | 명시 전체 검사 / 관리 list 손 기대 | 근거 |
| --- | --- | --- | --- |
| normal | OK / OK / INTENT | READY / {a,b} | 기존 정상 권위 |
| tmp_added | UNAVAILABLE / UNAVAILABLE / INTENT | UNAVAILABLE / UNAVAILABLE | 미완료 canonical 이름은 자기 쓰기 보류, 기존 j 부정 권위는 더 정확하게 유지 |
| unknown_added | OK / OK / INTENT | UNAVAILABLE / UNAVAILABLE | 전역 실패를 무관 로컬 열람으로 확대하지 않음 |
| corrupt_added | OK / OK / INTENT | UNAVAILABLE / UNAVAILABLE | 동일, 이미 아는 j 의도 유지 |
| intent_removed | OK / OK / INTENT | UNAVAILABLE / UNAVAILABLE | 외부 삭제로 이미 검증한 삭제 의도를 없애거나 j를 목록에 부활시키지 않음 |
| journal_removed | UNAVAILABLE / UNAVAILABLE / INTENT | UNAVAILABLE / UNAVAILABLE | 정본 부재는 보류하되 기존 j 부정 권위 유지 |
| db_only | OK / INTENT / INTENT | READY / {a} | DB의 보수적 부정 권위 |
| inplace_rewrite | OK / OK / INTENT | UNAVAILABLE / UNAVAILABLE | hot 목록이 본문 전체를 읽도록 되돌리지 않고 fresh에서 내용 변조 검출 |

IDX-OPEN의 corrupt-intent는 최초 전체검사 UNAVAILABLE와 관리 목록 거부를 유지한다. 무관 a의 get와 새 로컬 세션 생성은 K8처럼 허용하고, 완료 tombstone ID 재생성 거부·손상 bytes 보존을 별도 단언한다. tmp-present는 기존 보류 의미를 유지한다. 이 변경은 성공/정확성 oracle를 없애는 것이 아니라 승인된 검출 시점·capture/관리 경계와 삭제 의도 부활 금지에 맞추는 요청이다.


### 19.11 전체1의 실제 결과와 추가 fixture 승인

BASE+21 전체1은 **28,769 PASS·236 FAIL·error0**이었다(pytest2313.19초/명령2328.32초). 실패 파일별 수는 G11C resource_followup2, G15 seal_mutex12, storage_integrity1, G08 track_health56, G12 basis_a11y_ui165다. 원문·XML과 분류는 `ci-full.log/xml`, `ci-failures-detail.json`에 보존한다. wheel은PASS였으나 전체/커버리지는 실패했으므로 IMPLEMENTATION_READY가 아니다. `check_coverage`는 storage line94.52%/95·branch88.24%/90 FAIL이고 나머지6묶음은PASS다. pragma/예산 변경 없이 의미 있는 손 oracle를 신규4파일 안에 추가해 보강한다.

X00의 GS11A-RECOVERY-FIXTURES/DB-CUT로 `tests/integration/test_storage_integrity.py`, `tests/integration/test_track_health.py`를 추가하여 총25파일이 됐다. P04 한 시험은 실제 대상 canonical rename 직후·DB projection 전의 진짜 OSError 주입으로 옮기며 journal-only/재시작/원본 oracle를 유지한다. G08은 실패한 R×journal56행만 첫 Library 닫기→raw 입력→재열기로 준비하고 같은 live owner를 새 instance에 등록한다. 224개 ID와 건강/권위/반복 oracle는 그대로다. 두 대표행을 별도 실행해2 FAIL을 직접 재현했다(`extra-first.xml`). G12 UI165행은 모듈 fixture의30초 뒤 준비 claim이 거부된 경우다. 이 파일은 GS05의 dirty 수정과 겹치므로 p8은 수정하지 않으며 pB의 격리 fixture 패치를 기다린다.

§19.10에서 제안했던 db_only의 fresh READY는 잘못된 예상이었다. 런타임 raw DB 추가는 trusted delta가 아니므로 `DeletionHistoryIndex.prepare:319~352`가 거부한다. X00의 DB-CUT 결정에 따라 로컬 b는INTENT, fresh/관리 목록은UNAVAILABLE로 정정한다. 최초 열기에서 DB-only를 읽는 기존 B14는 바꾸지 않는다. 제품을 완화하지 않는다.

### 19.12 G15 IO2~5 행별 최소 적응 요청 — 승인 전 수정0

기존 승인23의 IDX-FAIL/OPEN 외에 전체1에서 IO2~5 네 행이 실패했다. 이 함수는 아직 승인 범위 밖이므로 수정하지 않는다.

| 행 | 직접 확인한 원인 | 제안 최소 변경·유지할 oracle |
| --- | --- | --- |
| IO2 | warm 관리 목록은 본문을 매번 읽지 않으므로 PermissionError 주입만으로 기존 receipt를 자동 폐기하지 않음 | index250 관리 검사 지점에 명시 fresh UNAVAILABLE를 먼저 단언하고 목록 거부. fault 해제 뒤 공개 fresh READY. 녹음 지속/원본/큐 회계·다른 세션 의도 거부 유지 |
| IO3 | 자기 fence의 `_writer_names` 오류가 writer 실패뿐 아니라 자동 상태 기록의 자기 조회도 거부해 DB가 RECORDING에 남음. storage_failed/정확 writer_error/catalog1은 그대로 | fault 해제와 실제 writer ACK 뒤 명시 stop이 정확한 STORAGE_FAILED_PARTIAL_MEDIA_PRESERVED를 내는지 관찰한 다음 기존 INTERRUPTED를 단언하는 안을 요청. 원본·catalog1·새 쓰기0·실패 폐쇄 유지. 자동 상태 시점을 바꾸는 제안이므로 X00 결정을 기다림 |
| IO4 | 외부 raw ext.json 추가로 관리 권한이 무효. fault 해제만으로 unknown external delta를 허용 권위로 채택하지 않음 | index250 명시 fresh의 I/O 실패/목록 거부. stop은 명시 capture 문맥으로 계속. 실제 종료 ACK 뒤 새 Library 최초검증에서 기존 최종 목록을 확인(기존 root/bytes·거부·수락 보존 유지) |
| IO5 | 최초 감사 I/O 실패를 무관 a 열람/새 로컬 세션 생성 차단으로 확대하지 않는 K8 계약 | 전역 UNAVAILABLE와 관리 목록 거부를 단언하고 무관 local get/create는 허용. fault 해제 뒤 fresh READY와 정확 목록{a,new}, 기존 tombstone ID 전부INTENT. 비밀/미디어/삭제 이력 변경 없음 |

네 행은 기존 건강/원본/정확 큐 회계/성능/봉인 구조 단언을 지우지 않는다. 승인 전 이 함수 수정0이며, 새 원격 요청이나 실행 권한을 부여하는 제품 경로를 만들지 않는다.

### 19.13 최초 열기 프로파일 — 원인 추정 정정

전체1 뒤 별도1천 건 사본에서 cProfile을 사용했다(`profile-open.json/log/pstats`). constructor6.3872초 중 verify_deletion_history6.3656초, read_format_one6.0294초, read_json1000회5.7095초, open_file1000회5.6347초였다. `_media_present`1000회는0.2924초였다. 따라서 앞의 ‘미디어 부재 확인이 주원인’ 추정은 이 관측으로 지지되지 않아 정정한다. 이 수치는 profiler가 켜진 별도 진단이며 무계측 성능표와 섞지 않는다. 초기 전체 정본 파일 읽기 비용이 큰 상태임을 인계하며 원인을 백신/디스크/제품 변경으로 단정하지 않는다.


### 19.14 커버리지 보강 입력·독립 oracle 설계

정본390과 기존 보강79를 바꾸지 않고 `GS11-COV-*` 별도 ID로 보강한다. 입력은 (a) HistoryEntry의 빈 권위·잘못된 digest·빠진 component·타입/상태 위반10행, (b) 닫힌 index의 scan/delta2행, (c) 실제 observer OSError/OverflowError2행, (d) 다른 실행 cut1행·최초 부정 floor 병합1행·prepare 뒤 trusted delta1행, (e) 없는 canonical journal1행, (f)129세션 keyset/list 연속성1행·파생 catalog meta 소실1행·입장 전 취소1행이다. 계획21행으로, 추가 시 실제 node 감사와 단독 wall을 다시 측정한다.

손 oracle는 잘못된 값의 정확 ValidationError/권한 발급0·기존 사실 불변, observer 실패의 허용권한False·부정 floor 유지, 다른 instance cut 거부, 최초 floor와 prepare 뒤 음성 delta가 둘 다 보존됨, 없는 정본 거부, 손으로 만든129개 ID의 정렬/합집합과128상한, metadata 부재의 목록 안전 실패, 취소된 관측의 새 receipt/본문 읽기0이다. 예외를 삼키는 assert 없는 호출이나 예산 변경/pragma로 미실행을 숨기지 않는다.


COV 보강21행의 첫 선택은 helper 반환값 수를 잘못 가정한 시험 준비 오류로19 PASS·2 FAIL이었다. 반환된3값을 정확히 받아21 PASS로 다시 확인했다. 제품 오류를 숨긴 결과가 아니며 첫 실행을 보존한다. 이어 component별 세대 역행1행, 공개 authority_view의 valid/tombstone/missing/closed4행, 미검증 관리 preflight1행, 내용 실패의 비fresh 자동 회복 금지1행을 추가한다. 손 oracle는 각 component의 음성 사실 감소 거부, 정확 상태/세대 DTO, 닫힌 instance 허용권한0, 로컬 열림과 관리 권한의 분리, 명시 fresh 전까지0회 본문 재개다. 합계 COV28, 정본390+기존보강79+COV28=497 계획이다. 이는 중간 coverage JSON의 실행선/분기 합집합으로 보강 후보를 고른 것이며 최종 CI 동등 PASS로 주장하지 않는다.


추가 COV029~032는 parser handoff 부재, 실행 중 미래 schema로 바뀜, Job 권위의 일시 stamp I/O 오류, 닫힌 Library의 관리 preflight다. 손 oracle는 각각 UNAVAILABLE/권한0·미디어/세션 불변, 미래 버전 보존/자동 down-migration0, 실패한 호출만 거부하고 fault 해제 뒤 VALID, 닫힌 연결 허용0이다. 총 COV32, 최신 계획은390+79+32=501행이며 분모는 정본과 분리한다. 중간 합집합은 진단 도구일 뿐 최종7묶음 판정은 새 정확 사본의 전수 coverage로 확인한다.


COV033~035는 root를 보유한 caller의 전체 검사 거부(무거운 작업 진입0), 기존 DB의 canonical journal 소실을 빈 정본으로 오인하지 않음, 실제 삭제 actor의 reserve→prepare 장벽에서 Job 입장 권한 거부다. 마지막은 손 장벽/실제 삭제 thread와 공개 Job 권위를 사용하며 삭제 완료 뒤 tombstone으로 전이하는지 확인한다. 계획은 COV35, 최신 신규4 분모는390+79+35=504다. 정본390 ID는 유지한다.


### 19.15 추가 승인 반영·최신 단독 결과와 26파일 사본

X00은 GS11A-G15-IO로 §19.12 IO2~5의 최소 적응을 승인했다. IO3은 fault를 실제 writer/sealer ACK까지 유지한 뒤 해제하고, 명시 stop의 정확 STORAGE_FAILED_PARTIAL_MEDIA_PRESERVED와 기존 INTERRUPTED/catalog1을 확인한다. IO1과 원본/수락/큐 회계/후속 쓰기0 oracle는 유지한다. 관련5파일 첫 재실행은1838 PASS·1 FAIL이었다. 마지막 IO5는 fault 중 이미 생성한 new를 fault 해제 뒤 다시 생성한 시험 준비 오류였다. 정상 생성을 재생성 허용으로 완화하지 않고 get(new)로 관찰했으며, 승인 적응 대상249행은 **249 PASS·pytest44.73초/command45.19초**였다(`adapted-last.xml`).

공유 작업 트리 소유는 §19.1의21 + G11C resource_followup + G15 seal_mutex + storage_integrity + track_health = **25파일**이다. 이에 X00이 승인한 pB의 접근성 fixture 패치를 **TEMP에서만** 추가해 최종 검증 입력을26파일로 만든다. 공유 `test_basis_a11y_ui.py`는 GS05 dirty 소유라 읽어 복사하거나 수정하지 않는다. 고정 b77cc102 원문 LF `53f209aba242f53644e5d5cac479c0c9bee4fcd32d508864e4062c59a88b3dbc`에 `build/gs11a-review-prep/basis-a11y-gs11.patch`를 적용한 뒤 LF `c36ac6dc761f5d2548096d25c54f8792bddc64b3c883244ae5e96500b6560a13`을 직접 대조한다. overlay 경로·patch·전후 해시를 `scope-approved25.json`에 구분했다. X00/pB의1254 PASS는 참고 이력이며 p8이 재실행한 결과와 혼합하지 않는다.

COV35는35 PASS이며, 신규4 최신 정상본은 **504 PASS·failure/error/skip0**이었다(`new504.xml`). 실제 시험 command wall332.1066초, archive·25파일 overlay·TEMP UI patch·부모/spawn import 확인 포함 harness wall333.2081초다. 목표150초는 미달, 승인 상한360초는충족했다. `new504-id-audit.json`에서 정본390의 누락/중복/초과0, 기존 보강79 node 변경0, 독립 COV001~035의 누락/중복/초과0을 확인했다. 469행의335.64초를504 결과로 소급하지 않는다.

제품8파일은469/규모측정 때와 동일하다. 최신26파일 사본에서 정적 검사는 ruff PASS·format223파일 PASS·mypy97파일 PASS였다. 30변이와 전수CI/7묶음/wheel은 같은 구성으로 재실행하며, 최종 정상본의 storage 예산은 전수 커버리지로 판정한다. 첫 전체 실패 증거는 `build/gs11a-resume-64393bb3e6/ci-first/`에 별도 보존했다. 중간 합집합95.23/90.02는 보강 진단치이며 전수 PASS가 아니다.


### 19.16 GS11A-STAGED-CASE 자가 반례와 추가 설계

자가 점검에서 Windows의 동일 파일 대소문자 별칭을 재현했다(`stage-case-probe.json/log`). 소문자 stage는 전역UNAVAILABLE·대상INTENT였으나 이름 전체/nonce를 대문자로 만든 두 경우는 `os.path.samefile=True`인데 READY·대상허용이었다. 원본 bytes는 유지됐다. 원인은 root staged 프로토콜 정규식의 대소문자 구별이다. 이 결함을 남긴 채 READY로 보고하지 않는다.

X00의 GS11A-STAGED-CASE로 **ASCII 대소문자만** 보수적으로 인식하도록 수정하고, 자기 예외의 instance/nonce/등록 수명/실제 파일 ID 대조는 완화하지 않는다. 계획6행은 stage/atomic/legacy3×upper_name/upper_nonce2다. 손 oracle는 Windows에서 같은 파일 별칭임을 직접 확인, 최초 검사의 전역UNAVAILABLE, 식별 가능한 대상의 정확INTENT, canonical 채택/삭제0·원위치 bytes 유지, 무관 세션의 합성4frame 수락/저장·실제 종료 ACK와 FINALIZED, 종료 뒤에도 새 전역권한0이다.

기존390+79+COV35=504에 별도 GS11-X-CASE6을 더해 **510행**이다. 단일 변이S12는 ASCII 대소문자 flags만0으로 되돌려 upper_name stage의 목표 전역거부 assertion 실패로 검출한다. 합계 **31개**다. 변경 후 시간 상한360초·31변이·정확26파일 CI/coverage7/wheel을 다시 실행한다. 대체되는 사본은 제품/시험을 변경하지 않고 부분/완료 상태를 보존한다. source가 바뀌었으므로 앞의 제품8파일 동일 주장은 이 수정 전 단계의 이력으로 한정한다.


### 19.17 STAGED-CASE 수정 뒤 정상본·중단 이력

최신 정상본은 **510 PASS·failure/error/skip0**이었다(`new510.xml`). 시험 command wall334.7442초, archive·overlay·TEMP patch·부모/spawn 확인 포함 harness wall335.8606초로 상한360초 이내였다. `new510-id-audit.json`에서390 정본의 누락/중복/초과0, 기존79 node 변경0, COV35 누락/중복/초과0, CASE6 중복/누락0을 확인했다. 정상 대조27 PASS 뒤 **31/31 목표 assertion 실패·error0**으로 재검출했다. S12는 case flags만0으로 되돌린 단일 변이이며 대문자 stage 행이 검출했다. 최신 ruff/format223/mypy97도PASS였다.

X00은 대체되는 검증의 본인 PID/세션을 확인한 안전 중단을 승인했다. 기본 샌드박스의 CIM 조회는 권한 거부됐으며, 사용자에게 읽기 전용 조회 승인을 요청하고 허용된 뒤 실제 명령행/부모 관계를 확인했다. 본인 pytest 실제PID22732(부모37952, 고유 root recoryn-gs11a-ci-du9xzzr4)만 중단했고 다른 pane/서버/세션을 건드리지 않았다. 실행 wall1126.7672초, 실제 exit4294967295를 `ci-case-before/interrupted.json`과 부분 로그/명령에 보존했다. 이 중단은 제품 failure/PASS 어느 쪽으로도 집계하지 않는다. 새 XML이 없으므로 오래된 XML을 이 실행의 결과로 복사하지 않았다. 중단 뒤 coverage JSON 부재에 따른 check 실패도 완료된 커버리지 결과로 부르지 않는다.

§19.8~19.13의 대량 기본 clock 측정/프로파일은 이 **case flags 수정 전** 제품 해시에 대한 직접 이력이다. 최신 해시의 대량 성능으로 소급하지 않는다. 변경은 root의 알려진 파일 이름 인식이며 canonical journal parser는 바꾸지 않았지만, 이전 시간을 최신 실측으로 주장할 근거로 쓰지는 않는다. 최신510행의 H16은 고정 손 시각의 기능/호출 수와 모사 원본 보존 증거다. 실제 대량 정본 읽기·30초 만료 운영 한계는 후속 압축/구조 검토에 인계하며 L을 완화하지 않는다.


## 20. GS-P11a 검토 제출 결과 — 최종 26파일 사본

### 20.1 구현 결과와 정본 범위

GS11a는 검증된 삭제 권위 snapshot의30초 유효기간 안에서 정확 map/PK를 조회한다. 전역 최초/fresh/주기 전체 검사는 기존 control worker를 사용하고, 정상 delta는 유효기간을 늘리지 않는다. 세션 목록은128개 이하 keyset 페이지, 권한 미검증/만료/확인 실패는 관리 입장/새 게시를 거부한다. 실제 종료 ACK와 명시 자기 capture 종료 문맥은 전역 감사 실패와 분리된다. tombstone/알려진 음성 사실은 permission이 만료돼도 유지한다.

미완료 root stage/atomic/legacy 프로토콜은 ASCII 대소문자 별칭을 포함하여 최초/fresh에서 전역 보류로 분류한다. 식별 가능한 대상의 부정 fence와 bytes를 보존하며 자동 이동·삭제·완료채택은 하지 않는다. 자기 진행 중 예외는 현재 instance·nonce·등록 수명·실제 파일 ID를 모두 요구한다. G09는 해당 파일/정본 journal/DB 음성 사실을 보존 인계받아야 한다. 이 단위는 G09 파일이나 공유 계약/배정표/Git을 수정하지 않았다.

기준은 `b77cc102a9db818a8c1d1a2840933ffa28e1b14c`다. 공유25파일과 X00 승인 pB TEMP patch1파일을 적용한 정확26파일 사본에서 검증했다. 실제 사본 경로/입력26해시/명령/시간은 `build/gs11a-resume-64393bb3e6/ci.json`, 부모/spawn import는 `ci-origin.log`, 정상/변이/전수 입력 일치는 `input-consistency.json`에 있다. GS04/GS05의 공유 dirty 제품·시험은 복사하지 않았으며 공유 접근성 UI도 수정하지 않았다.

### 20.2 최종 직접 검증

| 검증 | 실제 결과 | 근거 |
| --- | --- | --- |
| 신규4 정상·ID | 510 PASS·failure/error/skip0. 390정본+기존79+COV35+CASE6, 누락/중복/초과0 | new510.xml, new510-id-audit.json |
| 신규4 단독 시간 | command334.7442초, 준비/import 포함335.8606초. 목표150초 미달·승인360초 이내 | new510.json |
| 최신 단일 변이 | 정상 대조27 PASS 뒤31/31 목표 assertion 실패·teardown error0. 동등/수집/예외 오류를 검출로 합산하지 않음 | mutation-plan.json, mutation-results.json |
| 관련 적응 | 승인된 복구/IDX/IO 등249 PASS. 최초 전체 실패와 관련1838+1 준비오류는 이력으로 보존 | adapted-last.xml, related26.xml, ci-first/ |
| CI 동등 전체 | **29,046 PASS·failure/error/skip0**, pytest2435.77초·command2451.36초 | ci-full.xml/log, ci.json |
| 정적 | ruff PASS·format223파일 PASS·mypy97파일 PASS | ci-ruff/format/mypy.log |
| coverage | 아래7묶음 모두PASS. tmp/fixture 오염 파일0, pragma/예산 변경0 | coverage.json, ci-coverage.log |
| 오프라인 wheel | PIP_NO_INDEX=1, no-deps/no-build-isolation/no-cache-dir로PASS. 제품8파일 wheel bytes=사본 bytes | ci-wheel.log, final.json |

```
domain: line=99.18%/95% branch=97.89%/90% PASS
capture: line=99.73%/95% branch=98.29%/90% PASS
jobs: line=98.95%/95% branch=94.92%/90% PASS
storage: line=95.23%/95% branch=90.02%/90% PASS
security: line=98.11%/95% branch=94.43%/90% PASS
content: line=98.31%/95% branch=99.02%/90% PASS
all: line=93.89%/85% branch=88.50%/80% PASS
```

모든 최종 제품/시험 해시는 단독/변이/전수 사본 사이에 동일하다. 문서의 최종 결과 절은 CI 뒤 append한 기록이며, CI 사본 문서가 현재 문서의 정확 prefix인지 별도 확인한다. 최종 LF 해시는 본문에 자기 해시를 순환 기입하지 않고 delivery manifest와 이 창 보고로 제시한다. 기존 원문 prefix의 시작 LF 해시43523617a372cfda76f12830698f07f0b42bee72b017c9579f9193b4bcfeb02d도 보존한다.

### 20.3 변경 파일과 LF SHA-256

공유 작업 트리25파일은 아래와 같다. 해시는 CR 제거 기준이다. TEMP 전용 UI는 별도 표기하며 공유 파일을 이 해시로 덮어쓰지 않는다.

| 공유 파일 | LF SHA-256 |
| --- | --- |
| `src/recoryn/storage/library.py` | `3e8bbfd7218411556d8cf268bbdd9ab796f25d4c8c8fa025a90bc429970f45e9` |
| `src/recoryn/storage/deletion_history.py` | `6a49661843a0fdfa1e509d60c70053403db2eb48a630db4a13ae536ce919abcf` |
| `src/recoryn/app/history.py` | `24cd678d2a83b31cb042c132f62793ab96627a64907d260f28a6706f3748f320` |
| `src/recoryn/jobs/__init__.py` | `6765d522c9ea13413fe8177bbbea40a3ff942186a13c0750ae6b3473aaca29d2` |
| `src/recoryn/ui/main.py` | `194d6ae983b1e415665657ec619ec94ae2684aa6e10ea09e0192bd20877a6d64` |
| `src/recoryn/cli.py` | `67e538bb23be6d704ecb2237a5594ee1b437fe293840ed9fbd60195040e732e4` |
| `tests/unit/test_deletion_history_index.py` | `a8481e38c864437cb562812942b4303b5cd59e802a148c9d7671104b32040236` |
| `tests/property/test_deletion_history_index.py` | `caf59c9a3b2a717e812fe94e11e2be221a216b539edc54afc68e44ed6328d2fa` |
| `tests/integration/test_deletion_history_authority.py` | `42667ff7568f02c07eaf64b2e930a29e3a46ab39d38c0cf0e0bf3d2769ace9e4` |
| `tests/integration/test_deletion_history_races.py` | `c68135bace4d9d411d0a6c29f245af5c2f27ad9def6c5115f2437c921b56ba89` |
| `tests/integration/test_blocked_reason_flow.py` | `abe860d0d8104d14da6cbbe295248d6e2afb10754cbe728ad3f8977ef618f50b` |
| `docs/testing/gs11-deletion-history-scale-cases.md` | 최종 append 후 `delivery-shared25-hashes.json`에서 산출 |
| `src/recoryn/app/recording.py` | `a4eeee93b61c33aff58cd885ede1597091db6431e38c835e4990184d41a2732e` |
| `src/recoryn/content/store.py` | `758381909c4f1d1729bbbd85a7f38f2bc7c19f1bdb0b9756371f9fb9676c8e69` |
| `tests/unit/test_index_failure.py` | `b155f4bdaecc738f796ec7eba8beb282a5ed671c51e4cacb8b184f246bc2ef1f` |
| `tests/integration/test_index_failure.py` | `4b3a4c864059caaffa9b39fe4cadaacd9a168a23cb1da199a06662ca8b34122a` |
| `tests/integration/test_pending_deletion_restart.py` | `7034c9b578ad52a216bf0affeb5a29635aad26256a419ced8ad51f2d2b98cd2b` |
| `tests/unit/test_pending_deletions.py` | `dd5628e8376afe2cd97a2d9a78010661ae9c85c11d67e9a8ecac00df6d5f441c` |
| `tests/unit/test_seal_phases.py` | `7b5d0000fb57a84cf3b567fa1169a11d0219b38d285e95370223a1c75ff8e558` |
| `tests/unit/test_storage.py` | `5f0aba8a3a694f05a3afe19ca2ca829c5b46f53bcbb09fd35202cd805577ddb4` |
| `tests/integration/test_unfinished_recovery.py` | `7e0f82b866d2df000cc5d5e6d05c835062977e7e41ab3c6f786a4720c3cfeaa0` |
| `tests/integration/test_resource_followup.py` | `52b50fcce7d3b64fed7147a41d88050aa364ddaa5e1484ca649b56c4f0c6d6b2` |
| `tests/integration/test_seal_mutex.py` | `424927dfc7e971f60ef34d7b8a469784d6116f9d14c5f4e07f1fd4ea85d79f85` |
| `tests/integration/test_storage_integrity.py` | `3b7d7c764d1064986b3e39defa311afb32ad17d76abbc1d655de11c47eb6fc54` |
| `tests/integration/test_track_health.py` | `8dfa06b23efbd7678c97798171a1cdb7f8d61f186e227f1954b9b4c7a5c7508b` |

| TEMP 전용 추가 파일 | LF SHA-256 / 적용 방식 |
| --- | --- |
| `tests/ui/test_basis_a11y_ui.py` | `c36ac6dc761f5d2548096d25c54f8792bddc64b3c883244ae5e96500b6560a13`, X00 승인 `build/gs11a-review-prep/basis-a11y-gs11.patch`를 고정 BASE에 적용. 공유 GS05 파일 변경0 |

`delivery-hashes.json`은 공유25/TEMP1을 구분하고, `delivery-shared25-hashes.json`과 `delivery-effective26-hashes.json`은 각 해시 목록을 별도로 제공한다. 임시 증거 경로를 읽을 수 없는 검토자도 ignored build의 로그/JSON/XML/patch로 근거를 확인할 수 있다.

### 20.4 남은 운영 한계·미검증·검토 요청

- 독립 최종 승인은 아직 아니다. X00 또는 지정된 다른 Codex가 검토·정확 tree 통합·push를 결정한다. 작성자 본인은 Git/배정표를 쓰지 않았다.
- §19.8의 실제 기본 clock 규모 측정은 case flags 수정 전 해시에 대한 이력이다. H=10,000/100,000 최초 열기52.8266/618.7566초로30초 권한을 발급하지 못했다. 그 빠른 거부를 관리 성공 성능에 합산하지 않는다. 해당8개 모사 녹음은 거부0/수락저장 일치/정상 종료였다. 최신 flags 수정 뒤 같은 대량 기본 clock 재측정은 **NOT_RUN**이다. 최신 H16은 고정 손 시각 기능/호출 수 oracle이며30초 권한 발급 성능이 아니다.
- 별도1천 건 프로파일은 journal parser/open_file 비용이 지배적이었다. `_media_present` 주원인 추정은 정정했다. 큰 이력의 정본 전체 검사/30초 운영 한계는 GS11c 압축/후속 구조로 인계하며 L을 자동 완화하지 않는다.
- 실제 장치·실음성·모델/weights·외부 서비스·유료 호출·vault 쓰기·다운로드·설치는 실행하지 않았다. Python3.11/원격CI는 이 작업자가 재실행하지 않았고 X00의 후속 게이트다.
- 원본/삭제 권위/세대/GC-P02 구조/0.5초/claim·seal oracle는 승인된 적응 외에 약화하지 않았다. 첫 실패·준비 오류·중단과 정상 결과를 분리해 보존했다.

## §GS11a CI 회복 — 공개 494342a 기준

원격 실행45810798432는 Python3.13에서 G12 출판91 FAIL·29,258 PASS, Python3.11에서 G12 출판87과 G04-F3-PERF-finalize-900 한 행의88 FAIL·29,261 PASS였다. optional-runtime은 통과했다. 로컬 이전 정확 tree의 성공과 원격 실패를 각각 보존한다. 원격 실패 로그는 build/gs11a-x00-review/에 있다.

### 수명과 제품 경계

G12 publication 모듈의 공용 Library는 실제30초 뒤 정상 Job claim을 거부한다. 정상 준비 P·T·D 세 지점에만 공개 fresh와 정확 READY를 확인한다. 기존44개 단언 및386 ID(P288/D96/T2), 선택 snapshot·의도된 취소/삭제·compete 순서를 보존한다. 이 변경은 새 의미 ID를 추가하지 않는다.

확정900묶음의 38.33초 작업은 마지막 일반 권위 검사에서 기간 만료로 거부됐다. 관리 finalize 작업의 두 경계(복구 반환 뒤와 최종 manifest 검증 뒤)에서 기존 권위가 두 clock 연속성을 만족한 채 L30에 도달한 경우만 root·DB transaction 밖의 실제 전역 검사를 수행한다. 새로운 scan의 시작 시각과 일반 L30을 그대로 적용한다. 최초 일반 입장의 만료·명시 무효화·clock 역행/불일치·fresh 필요는 자동 회복하지 않는다. 감사 자체가 권한을 발급하지 못하면 확정을 보류하고 정본을 보존한다.

첫 자동 재감사의 instance/epoch binding은 동일 확정 작업의 seal 입장과 최종 commit까지 보존한다. 감사 시작/게시의 can_publish 및 마지막 root 안 binding·현재 권위·I1·generation/version·live 검사를 유지한다. 다른 epoch에 별도 새 READY가 생겨도 옛 작업의 binding을 대체하지 않는다. 자기 capture 종료는 기존 실제 owner/run/ACK 문맥으로 동작한다.

### 입력 공간·독립 손 oracle

실제 1묶음·480 mono s16 frame·literal payload와 독립 clock sample을 사용한다. 아래 named trace13이 입력 공간이며 제외0이다. 원 F3 PERF3·capture 종료4 및 GS11 기존510행을 그대로 회귀한다. 신규13은 tests/integration/test_unfinished_recovery.py의 전용 primary로 각1회 소유한다. 기존 파일의 원 시험과 단언을 보존한다.

| ID (G04-F3-AUTH-) | 입력 | 손 oracle |
| --- | --- | --- |
| 01 | 기간 내 정상 확정 | FINALIZED·1묶음/480frame·추가 감사0 |
| 02 | 최초 입장 전31초 만료 | 정확 DELETION_HISTORY_UNAVAILABLE·INTERRUPTED·감사0 |
| 03 | 실제 복구 반환 뒤31초 | root 밖 실제 READY1·FINALIZED |
| 04 | 마지막 manifest 검증 뒤31초 | root 밖 실제 READY1·FINALIZED |
| 05 | 04와 손상된 canonical 파일 | UNAVAILABLE1·정확 오류·FINALIZING·손상 bytes 보존 |
| 06 | 마지막 manifest 뒤 명시 무효화 | 정확 오류·FINALIZING·감사0 |
| 07 | guard 뒤 감사 본체 입장 전 invalidate | UNAVAILABLE1·실제 scan0·새 receipt0·정확 오류·FINALIZING |
| 08 | 실제 scan 시작 뒤 읽기 전 invalidate | UNAVAILABLE1·scan1·새 receipt0·정확 오류·FINALIZING |
| 09 | mono101s/UTC99s, 시작100s/100s | 정확 오류·FINALIZING·감사0 |
| 10 | mono101s/UTC131s, 시작100s/100s | 정확 오류·FINALIZING·감사0 |
| 11 | 마지막 감사 READY 뒤 invalidate 및 별도 fresh READY | 옛 감사READY1·현재 새receipt 유효·정확 오류·FINALIZING |
| 12 | 복구 뒤 첫 감사 반환 직전 invalidate 및 별도 fresh READY | 정확 오류·INTERRUPTED·현재 새receipt 유효 |
| 13 | 첫 helper 반환 뒤 공개 seal 호출 진입 직전 같은 사건 | 정확 오류·FINALIZING·현재 새receipt 유효 |

거부 행은 FINALIZED event0, 성공 행은 event1이다. 모든 행은 실제 PCM bytes와 chunk identity를 보존한다. 12는 FINALIZING 전이 전,13은 전이 뒤의 서로 다른 단계를 관측한다. fake clock 기능과 실제900묶음 wall을 각각 보고한다. 손 oracle를 제품의 분류 결과로 생성하지 않는다.

### 변이·검증·쓰기

원 변이7은 두 helper 호출, L30 도달 조건, clock 연속성, can_publish binding, 마지막 epoch, 마지막 기존 권위 검사 각각의 단일 결함이다. 첫 binding 전달·최종 첫 binding 대조·전이 전 대조의 후보3을 더하되 실제 위치가 같거나 다른 방어로 가려지는지 감사한다. 정상본 PASS 뒤 정확한 목표 call assertion FAIL만 검출이다. import/수집/권한/미도달/timeout/teardown 오류는 별도다.

제품·시험의 정확 범위는 src/recoryn/storage/library.py, tests/integration/test_unfinished_recovery.py, tests/integration/test_basis_publication.py다. 작성은 pA, 제품/시험의 독립 검토는 pB 및 X00이며 X00 작성 후보에는 pB 검토가 필요하다. 공유 GS05는 제외한다. 고정 공개 archive+최종 세 파일로 부모/실spawn 출처·분모/선택 실행·새13·기존386·F3/capture/저장 회귀·전체 core flags·coverage7·offline wheel을 검증한다. 기대 전체는29,362로 실제 collection과XML을 대조한다. 검토·통합·원격 회복 성공은 각각 별도로 기록한다. 현재 이 절은 실행 결과를 추가하지 않는다.

### R3 독립 입장 경합 보강

w5:p8의 별도 TEMP 반례 `recoryn-f3-r3-review-d8qwxyci/entry-gap-observation.json`에서 마지막 독립 binding 검사 뒤 root를 놓은 간격에 다른 스레드가 invalidate+명시 fresh READY를 실행했다. 최종 FINALIZED는0이었지만 stale seal admission·claim·manifest가 각각1회 실행됐다. binding 대조는 해당 admission·claim과 동일 root critical section에서 수행한다.

`G04-F3-AUTH-14`를 추가한다. 첫 helper의 binding 이후, 마지막 entry 검사와 실제 seal admission 사이에 위 사건을 강제한다. 새 receipt는 실제 유효해야 한다. 정확 ValidationError·FINALIZING·FINALIZED event0·seal admission0·claim쓰기0·manifest읽기0·PCM bytes 보존을 손 oracle로 고정한다. 장벽은 root 밖에 두고, 생산 함수의 검증을 대신하지 않는다. 신규 입력은 named14·제외0, 기존13 ID는 그대로 유지한다. 기대 전체 수집은29,363이다. 원자 입장 결속을 제거하면14의 입장0 assertion이 실패하는 단일 변이를 확인한다. 이전13/10 성공을 이 변경 후의 검증으로 소급하지 않는다.

### 최종14 입력과 변이 대응 확정

공개494342a에 아래 세 파일만 적용한다. 작성 pA, 독립 검토 pB, 통합 X00이다. 위13행 설계와 이전 후보는 이력이고 현재 수락 분모는 AUTH14·제외0, 기존29349+14=29363이다.

| 파일 | 최종 LF SHA-256 |
| --- | --- |
| src/recoryn/storage/library.py | `9f1e625c073afb9ef619e0f2d36af3f0c7b8ad6c396ebf3086ea28c4b3f8c939` |
| tests/integration/test_unfinished_recovery.py | `9c9747d5bfe950e427d9b10b21deac3e27353b3f9bb488f6ae9e4470deeb7f3b` |
| tests/integration/test_basis_publication.py | `dad7ac1c18d461267df4e92986bf5a58264b5165ec850c3471062012b5e4bb07` |

M01~M07은 위 기존7 결함을 유지한다. M08은 첫 binding의 seal 인자 전달 제거→AUTH13, M09는 `_session_operation`의 같은 root 안 입장 binding 검사 제거→AUTH14의 실제 admission/claim/manifest0, M10은 FINALIZING 전 첫 binding 검사 제거→AUTH12의 INTERRUPTED다. 이전 후보의 최종 첫 binding 검사만 제거하는 변이는 새 입장 차단에 가려져 독립 검출로 세지 않는다. 현재 총10개의 서로 다른 단일 결함이며 각 사본의 목표 assertion 실패만 검출로 센다.

X00은 최종 공유3파일과 실행 사본의 해시 일치, AUTH14 PASS·원 PERF/캡처7 PASS·관련771 PASS 및 최종10변이 목표 FAIL(error/skip0)을 대조했다. pB 독립 검토 `build/gs11a-x00-review/f3-r4-cross-review.md`(LF `0606aaf9299ed1a2269581de8dbaae3479c72e3ae866a3b2aeab5fbbe40696b5`)는 새 제품 OPEN0이다. 검토자는 구13 반례의 실제 입장/claim/manifest 각1→최종14 각0, 최종14 직접 실행, M09 직접 검출과 capture/API 경계를 독립 확인했다. D96 준비의 독립 검토와 직접2변이도 별도 유지한다. 전체 core·coverage7·wheel·원격 성공은 이 기록에서 아직 완료로 세지 않는다.

### 최종14의 로컬 검증 완료

위 정확3파일의 공개494342a 격리 사본에서 전체 **29,363 PASS**, 실패·오류·skip0을 확인했다. 원29349 ID 제거0·신규AUTH14만 추가, 전체 JUnit 다중집합과 수집 ID가 일치하고 각각1회였다. AUTH14·원 F3 PERF/캡처7·관련771 및 publication386도 최종 전체 결과에 포함된다. process wall2340.344초이며 fake-clock 경계 시험과 실제 관리900묶음의 측정을 구분한다.

원7+재매핑3의 단일10변이는 최종 정상본 뒤 각각 목표 call assertion에서 실패했고 INVALID/생존0이다. Ruff·format·mypy, 원 core.yml flags의 coverage85와 `scripts/check_coverage.py` 7묶음, offline wheel을 모두 통과했다. Storage line95.20%/branch90.16%, 전체 line94.14%/branch88.79%다. wheel SHA-256은 `62c3c2174aca0881bf29c38f3f13143bc3b8fd63c17002a5961e655e89ba9d17`이며 package Python85개와 모든 package member가 검사한 source bytes와 일치한다. 부모/실제spawn9모듈 출처는 사본 src이고 archive 비소유426파일 raw bytes와 공유 GS05 원32는 불변이다.

작성자 증거는 `build/gs11a-f3-r3/report.md` LF `af93c570595b93aba7a67e0672a83e93afe553b9e5349e9ba2f0062a5051193c`, `evidence.json` LF `adf4905d1f02c4ad0db006867504276b05bbbd6787f431d9205dc71cae5c5cda`다. X00은 실제 XML/수집/선택·변이·제품 해시·wheel을 읽어 `build/gs11a-x00-review/recovery-final-acceptance.json`에 인수 결과를 남겼다. 이는 로컬 완료이며 정확 commit tree·정상 push·복구본 원격3job 성공은 별도 게이트다. Python3.11 로컬, 실장비·실음성·모델·vault·실서비스·전원 장애 검증은 하지 않았다.
