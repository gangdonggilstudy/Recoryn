# G03 / G-P03 선택 version CAS: 경우의 수와 계약안

- 배정: G03 / push G-P03. 작성자는 w5:p7 Claude, 독립 검토자는 w5:p8 Codex다(검토 문서 `docs/reviews/g03-selection-version-review.md`).
- 상태: **FIX_READY(3판) — C00 계약 승인(2026-11-23) 뒤 구현했다. 2판에서 C00 보완을, 3판에서 Codex 독립 검토(G03-01~03)에 대한 C00 결정을 반영했다. 재확인 전이다.**
  - 승인 결정과 반영은 §8, 보완 결정은 §8.1, 검토 반영은 §8.2에 있다.
  - 실행 결과는 §9(1판), §9.5(2판), §9.6(3판)에 있다.
- 기준: commit `3f4ee9f2d56b5a7a97e8dccb49399b5637babd4e`. 정본은 [통합 계획](../implementation/v1-gap-plan.md)의 G-P03 행과 [배정표](../collaboration/assignments.md)의 G03 행이다.

## 1. 요구와 위험

- 대상 gap: G01B-024와 G1A-89의 ABA 부분을 S1 하나로 통합한 항목이다.
- 재현:
  - [G01AR-01](../reviews/g01-gap-recording-review.md): 공개 API 반례 2행 FAIL
  - [G01BR-19](../reviews/g01-gap-ai-security-ui-review.md): `%TEMP%\recoryn-g01br-probe\probe_g01br.py`의 P2
- 설계 정본([architecture-v1 메타데이터와 산출물 버전](../architecture-v1.md)): "SummaryRevision 게시도 현재 선택과 분리하며 expected transcript-selection version, summary-selection version과 설정 키를 같은 게시 transaction에서 비교한다. 다르면 결과를 원 입력의 후보로 보존하고 현재 요약을 교체하지 않는다. … 같은 전사라도 예전 템플릿 작업이 늦게 완료돼 최신 선택을 덮을 수 없다."
- 위험 S1: 잘못된 게시다. 사용자가 다시 고른 요약을 늦은 작업이 덮어쓴다. revision 자체는 보존되므로 원본·내용 손실은 없다.

## 2. 현재 동작과 결함

- 선택 상태: `content_selections`에 `transcript_id`, `summary_id`, `transcript_version`, `summary_version`이 이미 있다(`src/recoryn/content/store.py:135-140`). version은 선택이 바뀔 때마다 오른다(`:336`, `:510`, `_select` `:657-682`).
- 비교 대상: 게시 선택 조건은 ID만 비교한다.
  - 전사: `active == expected_active`(`:317`)
  - 요약: `active_transcript == expected_transcript == transcript_revision_id and active_summary == expected_summary`(`:488-493`)
- 기대값 캡처: 앱은 제출 시점에 ID만 캡처한다.
  - 전사: `src/recoryn/app/ai.py:203-206`. 현재 active가 edited면 임의 UUID로 바꿔 항상 후보가 되게 한다.
  - 요약: `src/recoryn/app/ai.py:441`
- 결과 1(ABA): 선택을 다른 revision으로 옮겼다가 같은 ID로 되돌리면, 그 사이 시작된 늦은 작업이 다시 선택된다.
- 결과 2(오래된 요청 우선): 설정 키가 없어서 서로 다른 설정의 두 요약 작업 중 **먼저 끝난 오래된 요청이 active가 된다**. 새 요청은 기대 ID가 달라져 후보가 된다.
- 이 단위에서 다루지 않는 기존 결함(G03 범위 밖, 별도 보고 대상):
  - 같은 ID만 비교하는 동작은 `create_transcript`, `create_summary`, `edit_segment`, `select_*` 같은 즉시 사용자 동작에도 있다. 다만 이들은 늦은 결과가 아니므로 이 단위의 결함이 아니다(§4.6).
  - 진행 중인 실시간 전사 tick은 사용자가 수동으로 선택한 비편집 revision을 다음 tick에서 다시 덮을 수 있다. 이는 현재 ID 의미 그대로의 동작이다.

## 3. 계약안(승인 요청)

### 3.1 공개 API

`ContentStore`에 다음을 추가한다. 모든 신규 인자는 keyword-only이고 기본값 `None`이다.

```python
def selection_state(self, session_id: str) -> dict[str, Any]:
    """One consistent read: transcript_id, transcript_version, summary_id,
    summary_version, summary_settings_key (None when never requested)."""

def request_summary_settings(self, session_id: str, settings_key: str) -> None:
    """Durably record the latest requested summary settings for the session."""

def publish_transcript(..., expected_transcript_version: int | None = None) -> str
def publish_summary(..., expected_transcript_version: int | None = None,
                    expected_summary_version: int | None = None,
                    settings_key: str | None = None) -> str
```

| 인자 | 형식 | 거부 |
| --- | --- | --- |
| `expected_*_version` | `int` 0 이상 2^63 미만. 캡처 시점의 `selection_state` 값을 그대로 넘긴다 | `bool`, 음수, 정수 아닌 값은 `ValidationError` |
| `settings_key`, `request_summary_settings.settings_key` | 비어 있지 않은 문자열, 최대 256자(`text_value` 규칙). 앱은 `_key([config_key, template])`의 SHA-256 hex를 쓴다 | 위반 시 `ValidationError` |

### 3.2 선택 규칙

선택 규칙은 게시 transaction 안에서 평가한다. 즉 JobStore의 `BEGIN IMMEDIATE`와 같은 직렬화 경계에서 기존 publisher callback 안에 있다.

- 게시 결과는 다음을 **모두** 만족할 때만 active로 선택된다. 하나라도 다르면 revision은 후보로 저장되고 active는 바뀌지 않는다. 이는 현재의 ID CAS 불일치와 같은 처리다.
  1. 기존 ID 조건
  2. `expected_*_version`이 `None`이 아니면 현재 version과 같다
  3. `settings_key`가 `None`이 아니면, 저장된 최근 요청 키가 없거나 그 키와 같다
- 그 밖의 처리는 지금과 같다.
  - complete 게시의 Job은 지금처럼 SUCCEEDED이고, `content_events.selected=0`이다. 부분 게시(`complete=False`)는 지금처럼 선택되지 않는다.
- `settings_key`가 주어지면 요약 body에 `"settings_key"`로 기록한다. 후속 S3인 OUTDATED 표시가 이 값을 쓸 수 있다. 이번 단위에서는 stale 계산을 바꾸지 않는다.
- `request_summary_settings`는 세션 생존·삭제 의도를 확인하고, 자기 content transaction으로 키를 덮어쓴다. 선택 version은 바꾸지 않는다.

### 3.3 schema(추가만, user_version 불변)

```sql
CREATE TABLE IF NOT EXISTS content_summary_requests (
    session_id TEXT PRIMARY KEY REFERENCES sessions(session_id) ON DELETE CASCADE,
    settings_key TEXT NOT NULL,
    request_count INTEGER NOT NULL DEFAULT 1
);
```

- 기존 content 테이블과 같은 additive 방식이다. Library가 소유한 `user_version`을 올리지 않는다.
  - [G01-C 확인 G01CR-02](../reviews/g01-gap-ai-security-ui-review.md)의 선택지 (a)다. G-P09 migration 프레임 전에 이 방식을 허용할지 C00 승인을 요청한다.
- 세션을 삭제하면 기존 content 테이블처럼 cascade로 함께 지워진다.
- 호환:
  - 새 앱이 기존 DB를 열면 테이블을 만들고 행이 없는 상태로 시작한다. 이때 설정 검사는 통과하므로 지금과 같다.
  - 구버전 앱이 새 DB를 열면 이 테이블을 무시한다.
  - 기존 요약 body에 `settings_key`가 없어도 읽기에 영향이 없다.
- `request_count`는 관측·시험용이며 비교에 쓰지 않는다. 설계가 비교 대상을 "설정 키"로 정했기 때문이다.
- **G-P09 인계 의무(C00 결정 1의 조건 b):** G-P09의 migration 프레임은 이 테이블(`content_summary_requests`)을 content 소유 버전 목록에 인계해야 한다. 그 뒤로 이 테이블의 생성·변경은 migration 단계로 관리하고, 지금의 `CREATE TABLE IF NOT EXISTS` 추가 방식은 그 첫 버전으로 기록한다.
- 기존 DB(테이블 없음)를 새 코드로 열 때와 다시 열 때의 멱등은 `tests/unit/test_content.py::test_g03_pre_g03_database_gains_the_table_and_reopen_is_idempotent`로 고정했다(조건 a).

### 3.4 호출자 영향

| 호출자 | 변경 | 비고 |
| --- | --- | --- |
| `app/ai.py` transcribe(`:203-206` 캡처, `:374·399·411` 게시) | 제출 시점에 `selection_state`를 읽어 `expected_transcript_version`을 세 게시 호출에 전달 | 편집 보호용 임의 UUID 규칙은 유지 |
| `app/ai.py` summarize(`:441` 캡처, `:524` 게시) | 입장 통과 뒤 ① `request_summary_settings(session_id, _key([config_key, template]))`, ② `selection_state`로 두 version과 기대 요약 ID 캡처, ③ `publish_summary`에 version 2개와 `settings_key` 전달. 기존 작업으로 합쳐진 요청(`admitted=False`)은 ①만 하고 그 작업 ID를 돌려준다 | **C00 승인**. 기록 시점과 거부 경로는 §8의 결정 2, 합쳐진 요청은 §8.1 |
| `ui/ai_bridge.py:433` 화자 구분 `publish_transcript` | 기대 ID를 읽던 두 줄을 `selection_state` 한 번 읽기로 바꾸고, 게시 호출에 `expected_transcript_version` 전달 | **C00 승인**(이 호출부만). 다른 부분은 바꾸지 않았다 |
| `ui/content.py` 선택·편집, 기존 시험의 직접 호출 | 변경 없음 | 신규 인자 기본값 `None` = 기존 의미 |

### 3.5 대안과 기각 사유

1. **version을 필수로 만들기**(기대 ID를 주면 version도 요구): ABA를 구조적으로 막는다. 그러나 기존 호출자인 `ui/ai_bridge.py`와 다수의 시험이 깨진다. 이 단위의 쓰기 범위를 넘으므로 기각했다. 화자 구분 경로까지 옮긴 뒤 후속 단위에서 기본값 제거를 제안한다.
2. **불투명 SelectionToken 객체 하나로 전달:** 인자 수는 줄지만 새 공개 타입이 생기고, 편집 보호용 임의 ID 규칙과 섞인다. 설계 문구(version 비교)와 대응이 명확한 정수 인자를 택했다.
3. **설정 키를 현재 선택된 요약의 키와 비교:** 사용자가 새 설정으로 요청만 한 상태(아직 결과 없음)를 표현하지 못한다. 템플릿 전환 결과가 영원히 선택되지 않는 경우도 생긴다. 기각했다.
4. **`content_selections`에 열 추가(ALTER TABLE):** 역시 additive이지만 기존 테이블을 변경한다. 신규 테이블이 되돌리기와 검토가 쉬워서 기각했다.
5. **설정 키 비교를 후속으로 미루기:** version만으로는 §2의 "오래된 요청 우선"이 남는다. 설계가 세 값을 같은 transaction에서 비교하라고 정하므로 기각했다. C00이 schema 추가를 승인하지 않으면 이 안으로 축소한다.

## 4. 경우의 수

### 4.1 인자와 동치류

| 차원 | 동치류(대표값) | 크기 |
| --- | --- | ---: |
| H_T: 캡처 뒤 전사 선택 이력 | T0 변화 없음 / AWAY 다른 revision 선택 후 유지 / ABA 다른 revision 선택 후 원 ID로 복귀 / EDIT 사용자 편집(새 edited revision 선택) | 4 |
| H_S: 캡처 뒤 요약 선택 이력 | S0 변화 없음 / AWAY 기존 후보 요약을 수동 선택 / ABA 다른 요약 선택 후 원 ID로 복귀 / PUB 다른 작업의 요약이 선택 게시됨 | 4 |
| K: 설정 | NONE 저장된 요청 없음 / SAME 최근 요청 키 = 작업 키 / NEWER 최근 요청 키 ≠ 작업 키 | 3 |
| M: 기대값 방식 | VER version·설정 키 전달 / LEGACY 신규 인자 없음(ID만) | 2 |
| C: 완결성 | COMPLETE / PARTIAL | 2 |
| J: 게시 시점 작업 | ACTIVE / CANCELLED(캡처 뒤 취소) / DELETED(캡처 뒤 세션 삭제 의도) | 3 |

**값 검증:**
- version ∈ {−1, 0, 1, 2^63−1, 2^63, True, 1.0, "1"}, settings_key ∈ {"", 공백, 256자, 257자, NUL 포함, 정상}. 경계 −1/0/최댓값과 그 바로 위, 타입 혼동을 포함한다. 유효·거부를 합쳐 14 case다.
- 3판(G03-01)에서 필수 키 3 case를 더했다. `request_summary_settings`의 settings_key ∈ {None, "", 257자}이고, 정상 키를 기록해 둔 뒤 SQL 전에 `ValidationError`가 나고 기록 행이 그대로인지 본다.
- `publish_summary`의 선택 인자 `settings_key=None`은 ID만 비교하는 LEGACY 의미를 유지한다. 이는 기존 `test_g03_legacy_publication_records_no_settings_key`가 확인한다.

### 4.2 분모

- 무제약 |Ω| = 4×4×3×2×2×3 = 576이다.
- **feasible 집합 F = 576**(3판에서 정정, G03-03).
  - 576개 조합은 모두 fixture로 구성할 수 있다. 구성할 수 없어서 뺀 조합은 0개다.
  - 제품이 거부해야 하는 조합(취소·삭제)도 F에 들어간다.
  - 2판까지 "제약 후 실행 집합 F=144"라고 쓴 것은 [경우의 수 규칙](case-space.md)의 F(구성 가능한 조합)와 맞지 않는 용어였다.
- **작성자 실행 부분집합 E = 144:**
  - **결정 cube**: (H_T×H_S×K×M) × COMPLETE × ACTIVE = 96. 선택 결정에 영향을 주는 네 축이라 전수로 둔다.
  - **PARTIAL**: H_T×H_S × (K=SAME, M=VER) × ACTIVE = 16.
  - **CANCELLED**: H_T×H_S × SAME × VER = 16. 게시 transaction이 fence 검사로 거부해야 한다(`jobs/__init__.py:451-464`).
  - **DELETED**: H_T×H_S × SAME × VER = 16. 삭제 의도 검사로 거부해야 한다.
- **E로 줄인 근거는 fixture 불가능성이 아니라 독립성 가정이다.** 가정의 내용:
  - PARTIAL guard(`content/store.py`의 `select=complete`), 취소 fence, 삭제 의도 guard는 선택 이력(H_T·H_S), 설정(K), 기대값 방식(M)과 무관하게 결과를 정한다.
  - 그래서 세 guard 행은 K·M을 하나로 고정했고, 취소·삭제 행은 C도 COMPLETE로 고정했다.
- **E 밖 432개 조합**은 저장소 시험으로 실행하지 않는다. 구성은 ACTIVE+PARTIAL 추가 80, CANCELLED 추가 176, DELETED 추가 176이다. 위 가정에 기대는 미실행 조합으로 둔다.
- **독립 검토 증거**(저장소 시험 수가 아니다):
  - Codex 검토([g03-selection-version-review.md](../reviews/g03-selection-version-review.md), LF sha256 `0b6ef4d871cc2747ea311e381df8cdd0ea7590802eb0c077d64486adb078249a`)의 `test_all_432_feasible_omitted_combinations`가 TEMP에서 432행을 모두 구성·실행해 통과했다.
  - 이는 위 가정에 대한 독립 증거로만 인용한다. 이 저장소의 시험 node 수나 E에 더하지 않는다.
- **전사 게시 cube**: H_T × M × {corrected complete, streaming draft complete, partial} = 4×2×3 = 24.
- **앱 경로**(AIService와 fake provider, 차단 Event): A1 요약 ABA, A2 요약 작업 중 전사 ABA, A3 설정 K1 작업 진행 중 K2 요청, A4 간섭 없음 회귀, A5 전사 작업 중 전사 ABA = 5.
- **입장 거부**(C00 결정 2): R1 입장 전 거부(서비스 종료) → 키를 남기지 않음, R2 입장 뒤 runner 거부(capacity) → 키가 남고 진행 중인 오래된 요청은 후보로 보존 = 2.
- **화자 구분 경로**(C00 결정 3): D1 `ui/ai_bridge.py` 게시 중 전사 ABA → 후보 = 1.
- **합쳐진 요청**(2판, §8.1) = 3:
  - MG1: K1 → K2 → K1 순서에서 세 번째가 진행 중인 K1 작업으로 합쳐짐 → K1 결과 active, K2 결과 후보
  - MG2: 같은 요청이 열린 서비스에서는 종료된 작업으로 합쳐지며 기록되고, 입장 전 거부(R1과 같은 서비스 종료)에서는 아무것도 기록하지 않음
  - MG3: 합쳐짐 기록이 실패해도 기존 작업은 취소되지도 잊히지도 않음(다음 같은 요청도 합쳐지고 작업은 SUCCEEDED)
- **분모 대조** 1: 선언 집합의 크기·고유성과 happens-before linear extension 일치.
- **값 검증** 17(14 + 필수 키 3)과 **저장 계약** 7:
  - 저장 계약 7: `selection_state` 기본값, 테이블 없는 기존 DB의 열기·재열기 멱등(C00 결정 1의 조건 a), 요청이 선택 version을 바꾸지 않음과 요청 횟수, LEGACY 게시는 `settings_key`를 남기지 않음, cascade 삭제, 삭제 의도 중 `request_summary_settings` 거부, 두 연결의 일관된 읽기.
- **합계:** 통합 시험 203(E 144 + 24 + 23 + 5 + 2 + 1 + 3 + 1), 단위 시험 24(17 + 7).
  - 1판은 합쳐짐 3행이 없어 통합 200이었다.
  - 2판까지는 필수 키 3행이 없어 단위 21이었다.

### 4.3 happens-before 조합

작업 chain은 캡처 C 다음 게시 P이고, 사용자 chain은 길이 2다. 두 chain의 linear extension은 C(4,2)=6이다. 각 순서는 단일 transaction 연산을 지정한 순서로 실행해 강제한다. scheduler의 우연에 기대지 않는다.

| 집합 | 사건 | 분모 | 손계산 결과(VER) |
| --- | --- | ---: | --- |
| HB1 요약 ABA | 작업 {C<P}, 사용자 {s1: S1→S2, s2: S2→S1} | 6 | C P s1 s2 → P 선택, s1·s2는 자기 CAS로 실패, 최종 P / C s1 P s2 → P 후보, 최종 S1 / C s1 s2 P → P 후보, 최종 S1 / s1 C P s2 → P 선택, s2 실패, 최종 P / s1 C s2 P → P 후보, 최종 S1 / s1 s2 C P → P 선택 |
| HB2 전사 ABA(요약 게시) | 작업 {C<P}, 사용자 {t1: T1→T2, t2: T2→T1} | 6 | C와 P 사이에 사용자 사건이 하나라도 있으면 후보, 없으면 선택. 선택은 순서 1·4·6, 후보는 2·3·5. 전사 선택(t1·t2)은 요약 게시와 무관하게 항상 성공한다 |
| HB3 설정 | 오래된 작업 J1(K1) {C1<P1}, 새 요청 r(K2) | 3 | C1 r P1 → P1 후보 / C1 P1 r → P1 선택 / r C1 P1 → C1이 K1을 다시 요청하므로 P1 선택 |
| HB4 두 작업 | J1(K1) {C1<P1}, J2(K2) {C2<P2}. 각 C가 자기 키를 요청 | 6 | 최종 active: C1 C2 P1 P2 → J2 / C1 C2 P2 P1 → J2 / C1 P1 C2 P2 → J2 / C2 C1 P1 P2 → J1 / C2 C1 P2 P1 → J1 / C2 P2 C1 P1 → J1 |
| HB4-LEGACY 대조 | HB4의 C1 C2 P1 P2를 ID만 비교하는 호출로 수행 | 1 | 최종 J1(오래된 요청 우선). 설정 키가 고치는 결함을 기록하는 행 |
| HB5 두 연결 | HB1의 순서 3을 사용자 선택만 다른 ContentStore 연결로 수행 | 1 | P 후보, 최종 S1 |

happens-before 분모는 6+6+3+6+1+1 = 23이다. 계약안 단계에서 22로 적었으나 LEGACY 대조를 별도 node로 두면서 23이 됐다. 축약은 없다. 각 연산이 SQLite `BEGIN IMMEDIATE` 하나로 선형화되므로 연산 단위 순서가 결과를 결정한다. transaction 내부 원자성은 기존 `tests/property/test_publication_case_space.py::test_three_connections_observe_atomic_first_commit`의 범위다.

### 4.4 독립 oracle

- **cube(96)**: 구현을 import하지 않고 설계 문장에서 쓴 닫힌 술어로 판정한다.
  - VER: 선택 ⇔ H_T=T0 ∧ H_S=S0 ∧ K≠NEWER.
  - LEGACY: 선택 ⇔ H_T∈{T0,ABA} ∧ H_S∈{S0,ABA}. K는 무관하며, 이 술어가 기존 결함의 동작이다.
  - 모든 case에서 다음이 성립해야 한다.
    - 새 revision이 존재하고 원 입력(전사 revision ID와 hash)에 고정된다.
    - Job은 SUCCEEDED다.
    - 비선택이면 active ID와 두 version이 게시 전과 같다.
    - 선택이면 `summary_version`이 정확히 1 오른다.
- **PARTIAL·CANCELLED·DELETED**:
  - PARTIAL: 선택 0, revision 존재, Job은 RUNNING(checkpoint)이다.
  - CANCELLED: `StateConflict`, 새 revision 0, active 불변.
  - DELETED: `StateConflict`, 새 revision 0.
- **HB1~5**: 위 표의 손계산 최종 active와 각 사용자 CAS의 반환값을 literal로 둔다.
- **전사 cube(24)**:
  - VER: 선택 ⇔ H_T=T0 ∧ C≠partial(streaming draft는 streaming Job일 때만).
  - LEGACY: 선택 ⇔ H_T∈{T0,ABA} ∧ C≠partial.
  - EDIT은 VER·LEGACY 모두 비선택이다. 기대 ID가 다르기 때문이다.
- 작은 상태 모델로 결과를 다시 계산하지 않는다. 같은 규칙을 코드로 옮긴 모델은 구현과 독립적이지 않아서다.

### 4.5 기존 시험과의 관계

- LEGACY 의미 유지를 보증하는 기존 node는 그대로 통과해야 한다.
  - `tests/unit/test_content.py::test_summary_is_pinned_stale_and_late_summary_cannot_replace`, `::test_atomic_summary_late_candidate`, `::test_summary_none_expectation_is_not_unconditional_overwrite`, `::test_two_connections_compete_without_losing_candidate`, `::test_history_selection_cas_and_session`, `::test_atomic_job_edit_cas_orders`
  - `tests/property/test_publication_case_space.py` 전체
  - `tests/e2e/test_ai_workflow.py` 전체, `tests/integration/test_ai_independent.py` 전체
  - `tests/ui/test_content_ui.py`, `tests/ui/test_live_ui.py`: 앱 캡처가 바뀌므로 회귀 확인
- 기존 node는 "다른 ID로 남은" 경합만 확인하고 ID 복귀 이력은 확인하지 않는다. 그래서 신규 VER cube와 HB가 그 공백을 채운다.
- G01AR-01의 반례 파일은 읽기만 하며 옮기지 않는다. 같은 시나리오인 HB1의 순서 3과 HB2의 순서 3을 위 oracle로 독립 작성한다.
- 배치:
  - `tests/integration/test_selection_version_cas.py`: cube, 전사 cube, HB1~5, A1~A5, R1·R2, D1, MG1~MG3, 분모 대조. 실제 SQLite와 임시 디렉터리만 쓰고, D1만 offscreen Qt를 쓴다.
  - `tests/unit/test_content.py`: 값 검증 17(필수 키 3 포함), 저장 계약 7.
- case ID는 `G03-<집합>-<값들>` 형식으로 고유하게 두고, 실행 ID 집합이 선언 분모와 일치하는지(누락·중복 0) 시험으로 대조한다.

### 4.6 범위에서 제외한 경로

- `create_transcript`, `create_summary`, `edit_segment`, `select_transcript`, `select_summary`의 즉시 사용자 동작은 version 비교를 추가하지 않는다. 늦은 결과가 아니고, 사용자가 화면에서 본 ID로 즉시 CAS하기 때문이다.
- latest pointer 분리, OUTDATED의 설정 반영, 전사 설정 키는 통합안의 S3 묶음으로 남긴다.

## 5. mutation 계획

방법:
- 승인 뒤 구현 정상본에서 신규·관련 시험이 PASS하는지 먼저 확인한다.
- `pyproject.toml`, `src`, `tests`를 OS TEMP의 고유 디렉터리로 복사한다. pyproject의 `pythonpath=["src"]`가 PYTHONPATH보다 우선하므로, 복사본 안에서 pytest를 실행한다.
- 아래 mutant를 하나씩 적용한다.
- 정상본과 변이본의 소스 hash, 실패 node를 기록한다. import·수집 오류만 난 경우는 mutant를 잡은 것으로 세지 않는다.

| mutant | 변이 | 잡아야 할 assertion |
| --- | --- | --- |
| M1 | 요약 게시의 transcript version 비교 제거 | HB2 순서 3, cube (ABA, S0, SAME, VER) |
| M2 | 요약 게시의 summary version 비교 제거 | HB1 순서 3, cube (T0, ABA, SAME, VER) |
| M3 | 설정 키 비교 제거 | HB3 순서 1, HB4 순서 1, A3 |
| M4 | version 비교를 `expected <= current`로 완화 | HB1 순서 3, HB2 순서 3. 계약안의 "HB1 순서 2·3·5"는 틀렸다. 순서 2·5는 기대 ID가 달라 ID 조건만으로 후보가 되므로 M4를 구별하지 못한다 |
| M5 | 전사 게시의 version 비교 제거 | 전사 cube (ABA, VER, corrected), A5, D1 |
| M6 | `request_summary_settings`를 no-op으로 | HB3 순서 1, A3 |
| M7 | `app/ai.py`의 version 캡처 제거(None 전달) | A1, A2, A5 |
| M8(2판) | 합쳐진 요청의 설정 기록 제거 | MG1, MG2 |
| M9(2판) | 설정 기록을 `_admit` 앞으로 옮김(입장 전 거부도 기록) | R1, MG2 |
| M10(3판) | `request_summary_settings`의 필수 검증을 선택 helper `_settings_key`(None 허용)로 되돌림 | `G03-KR-none` |

## 6. 수락 기준과 미검증

- 수락 기준:
  - G01AR-01의 두 시나리오(HB1·HB2의 순서 3)가 후보 보존으로 통과한다.
  - 선언 분모(통합 203, 단위 24)가 실행 결과와 일치하고 누락·중복이 0이다.
  - 기존 LEGACY node가 모두 통과한다.
  - M1~M9가 모두 목표 assertion으로 검출된다.
  - ruff, format, `python -m mypy src/recoryn scripts packaging`이 통과한다.
- 미검증:
  - E 밖 432개 조합(§4.2). 저장소 시험으로는 실행하지 않는다. 독립 검토가 TEMP에서 모두 통과시켰다는 사실은 증거로만 인용한다
  - UI의 후보 표시 문구 변화. UI에서 요약 후보를 고르는 경로도 없다(§8.2의 G03-02 (b))
  - 합쳐짐 판정과 기록 사이의 경합 창(§8.1, §8.2의 G03-02). 결과는 모두 보존되고 사용자의 재선택은 유지되지만, active가 마지막 요청 키와 다를 수 있다. C00이 이 보수적 결과를 수용했다. 이 순서를 강제하는 시험은 저장소에 없고, 독립 검토가 TEMP에서 세 경로를 재현했다
  - 합쳐진 요청은 기존 작업이 입장 때 캡처한 기대값을 갱신하지 않는다. 합쳐지기 전에 사용자가 선택을 바꿨다면 그 작업의 결과는 후보가 된다(보수적 동작, 시험 행 없음)
  - 전원 장애 중 transaction 내구성(기존 외부 게이트)

## 7. C00 결정 요청(계약안 단계, 이력)

1. `content_summary_requests` 신규 테이블을 additive 방식으로 추가해도 되는가(user_version 불변, G-P09보다 먼저). 거부되면 §3.5의 5번 안(설정 키 비교 후속)으로 축소한다.
2. `app/ai.py` summarize의 제출 시점 `request_summary_settings` 호출을 쓰기 범위로 인정하는가. 이 호출은 "기대값 캡처"를 넘어서는 쓰기다.
3. `ui/ai_bridge.py:433` 화자 구분 게시에 version 전달을 추가하도록 쓰기 범위를 넓힐 것인가, 아니면 후속으로 돌릴 것인가.

## 8. C00 결정(2026-11-23)과 반영

1. **신규 테이블 승인.** 조건 (a) 기존 DB 열기·재열기 멱등 시험은 `tests/unit/test_content.py::test_g03_pre_g03_database_gains_the_table_and_reopen_is_idempotent`로 고정했다. 조건 (b) G-P09 인계 의무는 §3.3에 적었다.
2. **summarize의 설정 기록 승인. 조건은 "입장 검사 통과 뒤·작업 생성 전 기록"이다.**
   - **구조상 "작업 생성 전"은 불가능하다.**
     - `AIService._admit`(`app/ai.py`)은 입장 판단의 일부로 `JobStore.create`를 호출한다. 같은 요청의 중복 판정과 영속 receipt가 작업 생성에 묶여 있어서다.
     - 마지막 입장 관문인 runner 용량 검사(`_submit`의 `runner.submit`)는 작업 생성 **뒤**에 온다.
     - 따라서 모든 입장 관문을 통과한 뒤이면서 작업 생성 전인 시점이 존재하지 않는다. 순서를 바꾸려면 `_admit`·`_submit` 구조를 고쳐야 하는데, 이는 이 단위의 쓰기 범위(게시 호출부와 기대값 캡처) 밖이다.
   - **택한 대안:**
     - `_admit`이 새 작업을 입장시킨 직후(종료 검사·중복 판정·실행 가능 판정 통과), runner 제출 **전**에 기록한다. 그다음 `selection_state`로 기대값을 캡처한다.
     - 기록을 캡처보다 먼저 하므로, 그 사이 끝난 오래된 작업은 새 키와 달라 후보가 된다.
     - 기록이나 캡처가 실패하면 `_submit`의 거부 경로와 같게 입장 표시를 지우고, 새로 만든 작업은 취소한 뒤 예외를 올린다.
     - 이는 계약안의 "제출 시점 기록"보다 좁다. 입장 전 거부는 키를 남기지 않는다.
   - **거부 시험 행:**
     - R1: 입장 전 거부(종료된 서비스)는 키를 남기지 않는다.
     - R2: 입장 뒤 runner 용량 거부는 키를 **남긴다.** 그 결과 진행 중이던 오래된 요청들은 후보로 보존되고 active는 이전 요약에 머문다. 결과 손실은 없고, 거부된 새 작업은 CANCELLED다.
     - R2의 동작을 없애려면 compare-and-restore API(예: 기록 토큰으로 되돌리기)나 runner 용량 사전 검사가 필요하다. 이는 C00 판단 대상으로 남겼고, §8.1에서 현재 동작을 수용했다.
   - **중복 입장:** 1판은 기존 작업으로 합쳐진 요청(`admitted=False`)을 기록하지 않았다. §8.1에서 기록하도록 고쳤다.
3. **화자 구분 게시 경로 포함.** `ui/ai_bridge.py`에서 기대 ID를 읽던 두 줄을 `selection_state` 한 번 읽기로 바꾸고, 게시 호출에 `expected_transcript_version`만 추가했다. 다른 부분은 바꾸지 않았다. 시험은 D1이다.

계약안과 달라진 점:
- `app/ai.py` transcribe는 기대 ID와 version을 같은 읽기에서 얻으려고 `selection_state`와 `transcript()`로 active revision을 읽는다.
- summarize의 기대 요약 ID 캡처는 입장 뒤 `selection_state`로 옮겼다.
- 전사 게시의 version 조건은 기존 선택식 한 줄을 그대로 두고 뒤에 별도 `if`로 붙였다(`content/store.py` `_create_transcript`). 이유는 기존 Q23 mutation 시험(`tests/property/test_publication_case_space.py::test_named_cas_mutant_is_killed_by_target_assertion`)이 그 줄을 문자열로 찾아 변이시키기 때문이다. 처음에 여러 줄 식으로 합쳤을 때 이 시험이 실패했다(§9.2).
- 그 밖의 공개 API·schema는 §3과 같다.

### 8.1 C00 보완 결정(2026-11-23, IMPLEMENTATION_READY 확인 뒤)

1. **R2 수용(C00 수용 결정).** 입장 뒤 runner 용량 거부가 설정 키를 남기는 현재 동작을 그대로 둔다. 진행 중인 오래된 요청의 결과는 후보로 보존되고 active는 이전 요약에 머문다. 결과 손실이 없는 보수적 동작이므로 compare-and-restore API나 용량 사전 검사는 도입하지 않는다. 시험 R2가 이 동작을 고정한다.
2. **합쳐진 요청도 기록한다.**
   - 결함: K1 → K2 → K1 순서에서 세 번째 요청이 진행 중인 K1 작업으로 합쳐지면, 1판은 기록하지 않아 최근 요청이 K2로 남았다. 그 결과 사용자가 마지막에 원한 K1 결과가 후보로 밀리고 K2 결과가 active가 됐다.
   - 수정(`app/ai.py` summarize만):
     - 설정 키 계산을 `_admit` 앞으로 옮겼다. 계산은 순수 함수라 부작용이 없다.
     - `_admit`이 `admitted=False`를 돌려주면 `request_summary_settings`를 호출한 뒤 기존 작업 ID를 돌려준다.
     - 대상은 `admitted=False` 전부다. 진행 중인 작업에 합쳐진 경우와 종료된(SUCCEEDED 등) 작업에 합쳐진 경우가 모두 들어간다. `JobStore.create`는 FAILED·CANCELLED 작업에는 합치지 않고 새 작업을 만들기 때문에, 그 경우는 입장 경로를 그대로 탄다.
   - 입장 전 거부와의 구분: 서비스 종료(`AI_SERVICE_CLOSED`)와 완결 전사 없음(`SUMMARY_REQUIRES_COMPLETE_TRANSCRIPT`)은 `_admit`이 돌아오기 전에 예외로 끝난다. 그래서 합쳐짐 기록에 닿지 않는다. MG2가 같은 요청으로 두 경로를 대조한다.
   - 실패 처리: 합쳐진 작업은 이 요청이 만든 것이 아니다. 그래서 기록이 실패해도 입장 표시를 지우거나 작업을 취소하지 않고 예외만 올린다. 입장 표시를 지우면 다음 같은 요청이 실행 중인 작업을 다시 제출하려 하므로 지우지 않는다. MG3가 이를 고정한다.
   - 남는 경합: 합쳐짐 판정(`_admit`)과 기록 사이에 합쳐진 작업이 게시를 마칠 수 있다. 그때 결과는 이전 최근 키와 달라 후보가 되고, 그 뒤 기록된 키 때문에 다른 키의 작업도 후보가 된다. 결과 손실은 없다. K1·K2가 모두 이 창에서 끝나는 변형은 §8.2의 G03-02를 본다. 이 창은 **이 단위 범위에서는 닫지 않는다**(3판에서 표현을 좁혔다, §8.2).

### 8.2 Codex 독립 검토 반영(2026-11-23, 3판)

- 검토 문서: [g03-selection-version-review.md](../reviews/g03-selection-version-review.md), LF sha256 `0b6ef4d871cc2747ea311e381df8cdd0ea7590802eb0c077d64486adb078249a`
- 검토 결과: OPEN 3건(S2 2, S3 1), S0·S1 없음.

**G03-01 / S2 / 고침**
- 결함: 필수 키 None이 `ValidationError` 없이 SQLite `NOT NULL` 오류로 드러났다.
  - 원인: `request_summary_settings`가 선택 인자용 helper `_settings_key`(None 허용)를 그대로 썼다.
- 수정: `request_summary_settings`가 `text_value(settings_key, maximum=256, empty=False)`로 직접 검증한다(`content/store.py`). `publish_summary`의 선택 인자 `settings_key=None`의 LEGACY 의미는 그대로다.
- 시험: `tests/unit/test_content.py::test_g03_required_settings_key_is_validated_before_sql`의 3행(`G03-KR-none`, `G03-KR-empty`, `G03-KR-257`).
  - 정상 키 `"known"`을 기록한 뒤 잘못된 키를 넣으면 `ValidationError`가 나고, 기록 행이 `[("session", "known", 1)]` 그대로여야 한다.
  - 수정 전 코드에서 None 행은 Codex 반례와 같은 `sqlite3.IntegrityError`로 실패했다(§9.6). 빈 문자열과 257자 행은 수정 전에도 통과했다.

**G03-02 / S2 / C00 수용(코드 변경 없음)**

C00은 합쳐짐 판정과 키 기록 사이 경합 창의 보수적 결과(결과 보존, 사용자 재선택 유지)를 수용한다.

- **(a) K2가 남는 변형:**
  - 상황: 창 안에서 합쳐진 K1 작업과 K2 작업이 **모두** 끝난 뒤에 K1이 기록되는 경우.
  - 결과: K1 결과는 후보가 되고, **active는 K2 결과로 남으며**, 최근 요청 키는 K1이다.
  - 해석: K2가 선택된 순간의 최근 키는 K2였으므로, 과거 결과가 최신 정책을 우회해 게시된 것은 아니다. 두 작업 모두 SUCCEEDED이고 revision 두 개가 보존된다.
  - 독립 검토가 이 경로와 다른 두 경로(창에서 K1만 완료, 합쳐지기 전 사용자 재선택)를 TEMP에서 재현했다.
- **(b) 후보 선택 경로:**
  - 후보로 남은 요약은 기존 요약 선택 API `ContentStore.select_summary(session_id, revision_id, expected_active=…)`로 고를 수 있다. 이 선택은 CAS로 동작한다.
  - 이 API는 기존 시험이 확인한다: `tests/unit/test_content.py::test_history_selection_cas_and_session`, `tests/integration/test_selection_version_cas.py`의 HB1 사용자 사건과 A1.
  - **다만 현재 UI에는 요약 후보 목록이나 선택 동작이 없다.** UI는 전사 버전 선택만 연결한다(`ui/content.py`의 `select_transcript`). 따라서 사용자가 화면에서 요약 후보를 고르는 경로는 이 단위 밖의 미구현 사항이다. §6의 "UI의 후보 표시"와 함께 남긴다.
- **(c) 표현을 좁힘:** "두 저장소를 한 transaction으로 묶지 않는 한 닫을 수 없다"(2판 §8.1)를 "**이 단위 범위에서는 닫지 않는다**"로 바꿨다.
  - 이유: JobStore와 content 테이블은 같은 Library SQLite에 있다. 그래서 입장과 키 기록을 조정하는 다른 설계(예: 같은 transaction 경계, 새 요청 nonce)가 불가능하다고 단정할 근거가 없다.

**G03-03 / S3 / 고침**
- §4.2에서 feasible 집합 F=576과 작성자 실행 부분집합 E=144를 구분했다.
- 축소 근거는 PARTIAL·취소·삭제 guard의 독립성 가정이라고 적었다.
- 검토자가 TEMP에서 나머지 432행을 모두 통과시킨 결과는 독립 검토 증거로만 인용했다. 저장소 시험 수(통합 203, 단위 24)에는 넣지 않았다.

## 9. 실행 결과(2026-11-23)

환경: Windows `.venv` Python 3.13.1, `QT_QPA_PLATFORM=offscreen`, `-p no:cacheprovider`, OS TEMP 아래 고유 basetemp. 기준은 commit `3f4ee9f` 위 작업 트리다. `src/`·`tests/`의 다른 변경은 C00의 GT-P01(`tests/unit/test_diarization.py`)과 미추적 `tests/release/test_gpu_smoke.py`(다른 세션)뿐이다.

### 9.1 G03 시험과 기존 관련 시험

| 실행 | 결과 |
| --- | --- |
| `tests/unit/test_content.py` + `tests/integration/test_selection_version_cas.py` | 300 passed. 신규 통합 200, 신규 단위 21. 선언 분모와 같다 |
| 위 두 파일 + `tests/property/test_publication_case_space.py` | 937 passed |
| G01AR-01 대응 | `G03-HB1-C-s1-s2-P`, `G03-HB2-C-t1-t2-P` PASS(늦은 결과는 후보, 최종 S1) |

### 9.2 전체 오프라인 회귀

`tests` 전체를 실행했고 다른 세션의 미추적 `tests/release/test_gpu_smoke.py`만 제외했다. 옵션은 `-W error::ResourceWarning`이다.

1. **1차: 1 failed, 7914 passed.**
   - 실패 node: `tests/property/test_publication_case_space.py::test_named_cas_mutant_is_killed_by_target_assertion`
   - 원인: 이 시험은 `_create_transcript`의 선택식 한 줄을 원문 문자열로 찾아 ID 비교를 빼는 Q23 mutant를 만든다. 내가 version 조건을 넣으면서 그 줄을 여러 줄 식으로 바꿔 문자열이 사라졌다.
   - 조치: 시험은 쓰기 범위 밖이므로 고치지 않았다. 제품 쪽에서 원문 줄을 유지하고 version 조건을 별도 문장으로 분리했다. Q23 mutant는 LEGACY 호출(ID만)을 쓰므로 분리 뒤에도 같은 목표 assertion으로 검출된다.
2. **최종: 7915 passed in 211.86s.** JUnit 기준 errors 0, failures 0, skipped 0이다. JUnit sha256은 `45303ce560f230d148da380372ca078703618a81e8810c4adef103e7c56f5955`다.

### 9.3 mutation(M1~M7)

방법:
- 사본 위치는 `%TEMP%\recoryn-g03-mut-792293b857b7432390305d56a5ee3ab1`이다. `pyproject.toml`, `src`, `tests`를 복사하고, 사본 rootdir에서 pytest를 돌렸다.
- 사본에만 있는 sentinel 모듈 시험(exit 0)으로 pytest가 사본 `src`를 import함을 먼저 확인했다.
- 대상 시험은 위 두 파일(300건)이다.

결과:
- 정상본: 300 passed.
- 정상본 LF sha256: `content/store.py` `3a00278f…0173`, `app/ai.py` `e5f12d65…bcff`. 모든 mutant 뒤 복원 hash가 같았다.
- 보고서: `mutation-report.json`, sha256 `2cd5116a60087a521a95e7d74eb7574aa2e77966b896c6baddecbf1b64ec6899`.

| mutant | 실패 수 | 목표 assertion 검출 | 대표 실패 node |
| --- | ---: | --- | --- |
| M1 | 4 | 예 | HB2 순서 3, cube ABA-S0-{NONE,SAME}-VER, A2 |
| M2 | 5 | 예 | HB1 순서 3, cube T0-ABA-{NONE,SAME}-VER, HB5, A1 |
| M3 | 6 | 예 | HB3 순서 1, HB4 (C1 C2 P1 P2)·(C2 C1 P2 P1), cube T0-S0-NEWER-VER, A3, R2 |
| M4 | 11 | 예 | HB1·HB2 순서 3, HB5, cube의 ABA 행 6개, A1, A2 |
| M5 | 6 | 예 | 전사 cube ABA-VER-{corrected,streaming}, 경계 V-0·V-max, A5, D1 |
| M6 | 12 | 예 | HB3 순서 1, HB4 2행, A3, A4, R2, 저장 계약 3, 키 경계 2 |
| M7 | 3 | 예 | A1, A2, A5 |

7개 모두 수집·import 오류 없이(errors 0) assertion 실패로 검출됐다.

### 9.4 정적 검사

- `ruff check src tests scripts packaging`: 통과
- `ruff format --check src tests scripts packaging`: 148파일 통과
- `python -m mypy src/recoryn scripts packaging`: 83파일 이상 없음

### 9.5 2판 보완 결과(2026-11-23)

기준은 commit `0305306` 위 작업 트리다. 작업 트리에는 G03 변경 말고도 Codex의 G-P02 변경과 C00의 GT-P01이 함께 있다. G-P02 변경은 `src/recoryn/security/*`, `src/recoryn/ui/privacy.py`, 관련 시험 9개, 미추적 consent scope 시험 4개다. GT-P01은 `tests/unit/test_diarization.py`다.

| 실행 | 결과 |
| --- | --- |
| 작업 트리: `test_content.py` + `test_selection_version_cas.py` + `test_publication_case_space.py` | 940 passed. 통합 203, 단위 21로 선언 분모와 같다 |
| 작업 트리: summarize·AIService를 부르는 시험 전체와 `tests/ui` | 1523 passed, 11 failed, 2 skipped |
| HEAD+G03 사본: 위와 같은 시험 목록 | **1350 passed**, 실패 0. 사본은 G-P02 추적 파일을 HEAD 내용(`git show`)으로 되돌리고 G-P02 미추적 시험을 뺀 것이다. JUnit sha256 `359e6a7e2b5b04a8210bd3a4e2e8587b9193d07d13bba2c0a79db5f9e38464b5` |
| mutation M1~M9 | 9개 모두 목표 assertion으로 검출, errors 0 |
| `ruff check src tests scripts packaging` | 통과 |
| `ruff format --check src tests scripts packaging` | 152파일 통과 |
| `python -m mypy src/recoryn scripts packaging` | 83파일 이상 없음 |

작업 트리 실패 11건의 귀속:
- 대상: `tests/ui/test_live_ui.py` 7건, `tests/ui/test_gpu_runtime_ui.py` 4건. 단독 재실행에서도 같은 11건이 실패하므로 부하 때문이 아니다.
- 격리 사본 두 개로 갈랐다.
  - HEAD+G03(G-P02 되돌림): 두 파일 14 passed
  - HEAD+G-P02(G03 되돌림): 같은 11건 실패
- 결론: 실패는 진행 중인 G-P02 작업 트리 변경에서 오며, G03 변경과는 무관하다. skip 2건은 G-P02의 `tests/ui/test_consent_scope_ui.py`다. 사유는 "G-P03 commit signal pending; ai_bridge connection is phase 2"이며, G-P03 commit을 기다리는 G-P02 쪽 의존이다.
- HEAD+G03 사본은 시험 행 이름을 MG1~MG3으로 바꾸기 전에 만들었다. 이름 말고 시험 내용은 같으며, 이름을 바꾼 뒤의 G03 시험은 위 940건과 mutation 기준선에서 다시 통과했다.

mutation 방법:
- 사본 위치는 `%TEMP%\recoryn-g03-mut-52c17519e8dd46abb22fc839dc6081f7`다. 방법은 §9.3과 같고, sentinel exit 0을 먼저 확인했다.
- 정상본은 303 passed다. 정상본 LF sha256은 `content/store.py` `3a00278f…0173`, `app/ai.py` `7322244b…6e08`이며, 모든 mutant 뒤 복원 hash가 같았다.
- 보고서 sha256은 `20ea7796e401a7ea62d27eb049e62d7da842ea5115d9b1bf1159f3611ca9530b`다.

| mutant | 실패 수 | 비고 |
| --- | ---: | --- |
| M1 | 4 | 1판과 같다 |
| M2 | 5 | 1판과 같다 |
| M3 | 6 | 1판과 같다 |
| M4 | 11 | 1판과 같다 |
| M5 | 6 | 1판과 같다 |
| M6 | 14 | 1판 12건에 MG1·MG2가 더해졌다 |
| M7 | 3 | 1판과 같다 |
| M8 | 3 | MG1, MG2, MG3. MG3은 주입한 기록 실패가 올라오지 않아서 실패한다 |
| M9 | 3 | R1, MG2, MG1. MG1은 같은 요청이 두 번 기록돼 요청 횟수가 달라서 실패한다 |

전체 오프라인 회귀는 2판에서 다시 돌리지 않았다. 지시 범위가 관련 시험이었다. 또 작업 트리에 진행 중인 G-P02 변경이 있어 전체 결과를 G03 판정에 그대로 쓸 수 없다. 다른 세션과 동시에 돌리면 GT-P01 같은 시간 의존 시험을 흔들 수도 있다.

### 9.6 3판 검토 반영 결과(2026-11-23)

3판에서 바뀐 것은 `content/store.py`의 `request_summary_settings` 검증 한 줄(주석 포함 2줄), `tests/unit/test_content.py`의 새 시험 1개(3행), 그리고 이 문서다. `app/ai.py`, `ui/ai_bridge.py`, 통합 시험 파일은 2판과 같다.

| 실행 | 결과 |
| --- | --- |
| 수정 전 코드 + 새 시험(`-k required_settings_key`) | 1 failed, 2 passed. 실패는 `G03-KR-none`의 `sqlite3.IntegrityError: NOT NULL constraint failed: content_summary_requests.settings_key`로, Codex 반례와 같다 |
| 수정 뒤: `test_content.py` + `test_selection_version_cas.py` + `test_publication_case_space.py` | **943 passed**(112.25s). 통합 203, 단위 24로 선언 분모와 같다 |
| 형식 정리 뒤 `test_content.py` | 103 passed |
| mutation M1~M10 | 10개 모두 목표 assertion으로 검출, errors 0(아래) |
| `ruff check src tests scripts packaging` | 통과 |
| `ruff format --check src tests scripts packaging` | 152파일 통과 |
| `python -m mypy src/recoryn scripts packaging` | 83파일 이상 없음 |

mutation 방법:
- 사본 위치는 `%TEMP%\recoryn-g03-mut-beca7af1106742d38583643acd4f8729`이고, sentinel exit 0을 먼저 확인했다.
- M6의 변이 위치를 새 검증 줄에 맞췄다. 변이 내용(기록을 no-op으로)은 같다.
- 정상본은 306 passed다. 정상본 LF sha256은 `content/store.py` `50c770f6…14de`, `app/ai.py` `7322244b…6e08`이며, 모든 mutant 뒤 복원 hash가 같았다.
- 보고서 sha256은 `6af6fd406111f14ab81e4648b2e6b24484f07f74b6b7d7150b7fa3849c1dda0e`다.

| mutant | 실패 수 | 비고 |
| --- | ---: | --- |
| M1~M5, M7~M9 | 4, 5, 6, 11, 6, 3, 3, 3 | 2판과 같다 |
| M6 | 17 | 2판 14건에 필수 키 3행이 더해졌다. 기록이 no-op이면 미리 넣은 `"known"` 행이 없기 때문이다 |
| M10 | 1 | `G03-KR-none`만 실패한다. 빈 문자열·257자는 선택 helper도 거부하므로 이 mutant를 구별하지 못하며, 그 자체로 정상이다 |

전체 오프라인 회귀는 3판에서도 다시 돌리지 않았다. 이유는 §9.5와 같다. 검토 tree에서 Codex가 돌린 전체 회귀(8021 PASS)는 2판 tree 기준이다.
