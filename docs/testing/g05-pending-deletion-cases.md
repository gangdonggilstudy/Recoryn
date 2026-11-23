# G05 / G-P05 재시작 뒤 삭제 대기 복원: 계약안과 경우의 수

상태: **FIX1_READY — 독립 검토 G05R 1차 지적(G05R-01 S2, G05R-03 S3) 수정, 같은 검토자 재확인 대기**. 2026-11-23 C00이 §8 승인 요청 (1)~(7)을 권고안대로 승인했고, 구현 작성 권한을 w5:p8 Codex에서 Claude 하위 에이전트로 재배정했다. 계약 작성(Codex)과 구현 작성(Claude)·독립 검토(C00 지정 다른 세션)는 서로 다르며 작성자는 단독 최종 승인하지 않는다. 구현·실행 결과는 §10~§11에 있고, 아래 §1~§9의 계약 본문은 승인 당시 문장을 그대로 둔다.

## 1. 요구·위험·직접 확인한 근거

정본은 [통합안 G-P05](../implementation/v1-gap-plan.md), [architecture 삭제 계약](../architecture-v1.md#비밀과-데이터-수명), [경우의 수 규칙](case-space.md), [G-P04 계약안](g04-unfinished-session-cases.md)이다. G01B-067/F-LIFE02와 G1A-72/GF-13은 같은 원인이며 G01BR-18에 따라 **S1 하나로 정합**한다. G1A-73의 제거 실패·멱등 재삭제 전체가 미시험이라는 과거 주장은 채택하지 않는다.

다음은 현재 작업 트리의 **코드 읽기 결과**다. G-P04는 구현 중이므로 함수·줄 번호는 관찰 시점의 위치이며, 그 코드가 독립 검토·push됐다고 뜻하지 않는다. 구현 시작 때 실제 G-P04 commit을 다시 고정한다.

| 직접 확인한 근거 | 관찰 | G05에서 닫을 부분 |
| --- | --- | --- |
| `src/recoryn/storage/library.py:202` `_deletion_intents` | `deleted_sessions`와 journal의 합집합으로 숨긴다. journal 디렉터리 부재·손상·미완성 `.tmp-`는 fail closed | 숨긴 이유와 대기 상태를 별도 읽기 API로 제공 |
| `library.py:837` `delete_session` | journal→DB DELETE_PENDING→reader/writer 확인→파일 제거→DB 정리/DELETED_LOCAL 순. 파일 제거 실패면 대기. 재호출 가능 | 재시작 inventory와 의도 한정 retry, 중단 단계·잔여물 판정 |
| `library.py:887` 부근 최종 정리 | 완료 후 journal은 삭제하지 않으며 내용은 여전히 DELETE_REQUESTED다 | journal 존재를 대기와 동일시하지 않고 완료 tombstone과 함께 판정 |
| `src/recoryn/ui/main.py:71`, `:636`, `:656`, `:678` | `_pending_deletions`는 새 창에서 빈 dict. 같은 창 결과만 보관하고 이 dict의 ID만 재시도 | 새 창/재시작에서 storage inventory 복원, 실패를 빈 목록으로 숨기지 않음 |
| `library.py:230`·`:238`, `:761`·`:774` | G-P04가 live owner·미확정 목록·확정 API를 추가 중. 삭제 의도는 미확정 목록에서 제외 | 두 목록 분리, SESSION_LIVE와 삭제 우선순위 보존 |
| `src/recoryn/storage/_safe.py:192`, `:220` | journal 원자 게시와 재귀 제거는 다른 동작. Windows directory fsync·전원 장애 내구성을 보장하지 않음 | 실제 owned process kill·파일 제거 예외를 구분, 성공 오표시 방지 |

[G01AR-02](../reviews/g01-gap-recording-review.md)의 정정대로 `tests/unit/test_storage.py::test_delete_intent_before_files_and_no_resurrection`은 PermissionError→DELETE_PENDING→같은 프로세스 재삭제 완료를 이미 검사한다. `tests/integration/test_storage_integrity.py::test_journal_only_deletion_intent_blocks_recovery_and_can_resume`도 journal 게시 직후 예외와 재열기를 검사한다. 두 node의 본문 존재를 이번에 직접 읽었다. **이 계약 단계에서 다시 실행한 것은 아니며**, 과거 검토의 402 PASS나 다른 문서의 시험 숫자를 새 관측으로 쓰지 않는다. 새 핵심 증거는 목록 복원·실제 제거 중 kill·UI 재시작·새 API의 잘못된 완료 방지다.

## 2. 권고 계약

### 2.1 최소 삭제 기록의 의미

- 삭제 의도는 DB 또는 유효 journal **어느 한쪽이라도** 있으면 효력이 있다. 정상 세션 목록·복구 재채택·확정·새 작업의 대상으로 되돌리지 않는다.
- `deleted_sessions.status`의 지원 값은 DELETE_PENDING / DELETED_LOCAL이다. `SessionState`에 삭제 상태를 추가하지 않는다. 기존 journal v1의 session_id·generation·DELETE_REQUESTED 의미를 유지한다. 새 테이블·공용 schema version 변경은 제안하지 않는다.
- 완료는 **세션 폴더 부재 + 세션/청크 등 기존 삭제 계약의 DB 정리 + DELETED_LOCAL tombstone + 유효한 최소 journal**을 확인한 경우만 보고한다. 파일 없음만으로 완료를 추측하지 않는다. 정상 완료 tombstone은 라이브러리 수명 동안 보존한다.
- 정상 완료 뒤 남는 journal은 대기 항목이 아니다. 반대로 DELETED_LOCAL 행이 있어도 폴더/세션 행이 남거나 journal 보강이 필요하면 확인·정리 대상으로 보인다. 완료 이력을 없애거나 ID를 재사용하지 않는다.
- 세션 폴더만 있고 DB/journal 의도가 없으면 삭제 대기로 **추정하지 않는다**. G-P04의 DIRECTORY_ONLY 처리와 분리한다. 유효 journal만 있는 폴더는 기존 의도가 있으므로 세션 행을 복구·생성하지 않고 재삭제할 수 있다.
- 완료는 해당 라이브러리의 로컬 제거다. 외부 export·백업·원격 사본·SSD의 물리적 소거 완료를 뜻하지 않는다. 비용 ledger·UNKNOWN 및 최소 삭제 기록은 세션 삭제와 함께 제거하지 않는다.

### 2.2 `Library.pending_deletions()`

```python
def pending_deletions(self) -> list[dict[str, Any]]:
    """Read-only inventory of durable deletion intents requiring completion or repair."""

def retry_deletion(self, session_id: str, *, expected_generation: int) -> dict[str, Any]:
    """Retry an existing intent only; never turn an unknown ID into a new deletion."""
```

`pending_deletions`는 root mutex 아래 DB와 journal을 한 번의 일관된 관찰로 합친다. 같은 프로세스의 협력 API와 라이브러리 단일 writer 계약을 전제로 하며 임의 외부 파일 조작과 두 저장소의 물리적 원자성을 보장하지 않는다. 오디오·staging 내용이나 전체 모델 폴더를 읽지 않고 journal 한 단계와 해당 세션 폴더 존재만 확인한다. 조회가 DB/journal을 수선하거나 삭제·Job 복구·동의를 수행하지 않는다. session_id 기준 정렬, 중복 ID0이다.

반환 행은 다음 필드로 고정한다. 제목·절대 경로·OS 예외 문자열은 포함하지 않는다.

| 필드 | 의미 |
| --- | --- |
| session_id / generation | 검증된 ID와 현재 삭제 의도 세대. generation은 양의 정확한 int, bool 제외 |
| state / deleted | 목록에서는 DELETE_PENDING / False. DELETED_LOCAL은 retry의 확인된 완료 결과에만 사용 |
| db_status / intent_sources | DB 상태 또는 None, `("db",)` / `("journal",)` / `("db","journal")` |
| session_present / media_present | 해당 세션 DB 행과 폴더의 현재 존재. 폴더 존재가 곧 원본 전체 보존이라는 뜻은 아님 |
| live / active_reader_or_writer | G-P04의 live 판정과 기존 `_active_jobs`/writer 판정. 조회가 ACK를 만들지 않음 |
| reason | SESSION_LIVE / ACTIVE_READER_OR_WRITER / JOURNAL_REPAIR_REQUIRED / CATALOG_CLEANUP_REQUIRED / RETRY_REQUIRED 등의 닫힌 현재 관찰 코드 |
| repair_required | 한쪽 의도만 존재하거나 세대/완료 투영 보강이 필요한지. 조회는 수선하지 않음 |

재시작 후 예전 PermissionError가 원인이었다는 정보는 현재 schema에 없다. 그래서 **RETRY_REQUIRED(이전 제거 실패 사유 미보존)**로 정직하게 표시한다. 현재 재시도에서 관측한 MEDIA_REMOVAL_FAILED는 그 실행 결과로 표시한다. 이 단위에서 파일 경로·예외 본문을 영속 오류 이력에 추가하지 않는다.

단일 reason의 우선순위는 이력 오류(전체 조회 실패) → 세대 충돌(전체 조회 실패) → SESSION_LIVE → ACTIVE_READER_OR_WRITER → JOURNAL_REPAIR_REQUIRED → 파일 없는 미완료 기록의 CATALOG_CLEANUP_REQUIRED → RETRY_REQUIRED다. 여러 사실은 bool 필드로 함께 남긴다. UI는 같은 generation에서 이번 실행이 직접 관측한 마지막 시도 오류를 별도로 붙일 수 있지만, 그 메모리를 목록 포함/완료 판정의 근거로 쓰지 않는다. 재시작·세대 변경 뒤 과거 오류로 이식하지 않는다.

**정합 표**에서 D는 유효 DB 삭제 행, J는 유효 journal이다. 정상 세션 행/폴더는 S/M이다.

| D / J / 잔여 상태 | 목록/재시도 계약 |
| --- | --- |
| D 없음, J 없음 | 삭제 대기 아님. 폴더만 있어도 새 의도를 만들지 않음 |
| DELETE_PENDING, J 있음 | 대기. 파일이 이미 없어도 DB 정리·tombstone 확인 전 완료 아님 |
| DELETE_PENDING, J 없음(디렉터리 자체는 정상) | 대기, JOURNAL_REPAIR_REQUIRED. 명시 retry에서 먼저 journal 보강 |
| D 없음, J 있음 | 대기. 명시 retry에서 DB 의도·세대/fence 투영을 먼저 반영. 세션 복구/원본 재생성 금지 |
| DELETED_LOCAL, J 있음, S/M 없음, 세대 정합 | 정상 완료. pending 목록 제외, 같은 세대 retry는 already_deleted=True로 멱등 |
| DELETED_LOCAL인데 S/M 잔존, J 없음 또는 세대 보강 필요 | 완료를 재선언하지 않고 정리/기록 보강 대상으로 표시. tombstone을 지우거나 DELETE_PENDING으로 강등하지 않음 |
| journal 디렉터리 유실·잘못된 타입·손상 항목·미완성 tmp·미지원 DB 상태 | 조회 전체를 안전한 ValidationError로 실패. 정상 빈 목록으로 바꾸지 않음. 자동 수선/삭제 금지 |

세대는 유효한 D/J 중 **최댓값 g**를 사용한다. J가 D보다 앞선 정상 중단 창과 D-only를 수용한다. 명시 retry에서 양쪽을 g로 보강하고, 세대 감소·재시도마다 새 세대 생성은 하지 않는다. 같은 ID를 가리키는 유효 기록끼리의 숫자 차이와 손상/신원 불일치를 구별한다. S의 generation이 g보다 크면 `DELETE_HISTORY_CONFLICT`로 보류해 새 상태를 덮지 않는다. bool·음수·overflow·다른 ID·미지원 형식은 최댓값 병합으로 정상화하지 않는다.

이 g는 **Library의 삭제 의도 세대**다. G-P04의 state_version이나 G-P02 ConsentStore의 세션/실행 세대와 같은 번호라고 가정하지 않는다. UI가 별도 세션 철회를 반복해 security 세대가 증가해도, 같은 삭제 의도의 expected_generation을 그 값으로 교체하지 않는다.

### 2.3 명시 재시도와 완료

root mutex 한 구간에서 다음 순서를 보장한다.

1. ID·expected_generation 형식과 삭제 이력의 완전성을 검사한다. 의도가 없으면 `NOT_PENDING, deleted=False`다. 기존 정상 세션에 새 삭제 의도를 만들지 않는다.
2. 표시 당시 세대와 현재 g가 다르면 `StateConflict("STALE_DELETE_GENERATION")`. UI는 재조회하고 사용자가 다시 선택해야 한다. 입력 오류·stale/충돌 거부는 파일과 기록을 바꾸지 않는다.
3. 양쪽 최소 의도·DB 세대/fence를 보강한 뒤에만 파괴적 제거를 허용한다. journal 보강 실패·DB commit 실패면 완료 아님. 기존 DELETED_LOCAL tombstone은 유지한다.
4. G-P04 `_is_live`와 기존 reader/writer가 남아 있으면 DELETE_PENDING/False 및 해당 이유다. source를 임의 중지하거나 reader ACK를 조작하지 않는다. 실제 owner 종료/ACK 뒤 다시 호출한다.
5. 세션 폴더 제거를 재시도한다. 일부만 제거한 뒤 예외여도 MEDIA_REMOVAL_FAILED/False이며 남은 파일을 새 파일로 복원하지 않는다. 다음 재시도는 남은 부분을 대상으로 한다. 폴더가 없으면 기존 DB 정리 단계로 진행한다.
6. 기존 삭제 계약대로 chunks·세션 관련 metadata를 정리하고 DELETED_LOCAL을 commit한다. 비용 ledger와 journal/tombstone은 보존한다. 새 retry의 DB 정리 실패는 rollback 후 비민감 `ValidationError("DELETION_METADATA_PENDING")`로 보고하고 **완료 dict를 반환하지 않는다**. UI는 해당 항목에 정리 실패를 표시하고 재조회하며, 재조회도 실패하면 확인 불가로 남긴다. 기존 delete_session의 저장 예외 호환은 변경하지 않는다.
7. 확인된 완료만 `state="DELETED_LOCAL", deleted=True, already_deleted=bool, generation=g`를 반환한다. 같은 g로 다시 호출해도 삭제 세대·완료 기록을 늘리지 않는다. JSON 응답을 받기 전 kill돼도 재열기에서 같은 사실을 확인할 수 있다.

기존 `delete_session`의 호출 서명과 정상 삭제/NOT_FOUND 의미는 유지한다. 내부 삭제 진행부를 공유하되 새 retry가 미확인 ID에 일반 delete를 무조건 호출하는 wrapper가 되지 않게 한다. 기존 intent를 처리할 때만 g 보존·완료 fast path를 적용한다. **초기 delete도** live owner가 writer 사이에 있는 틈을 무시하고 제거하지 않도록 G-P04 `_is_live`를 제거 전 guard에 합친다. 기존처럼 의도는 먼저 기록하고 live면 대기를 반환한다. 이 추가 guard는 승인 대상 행동 변화이며 녹음기를 강제 종료하는 기능은 아니다.

## 3. G-P04·Job·보안 경계

### 3.1 미확정 세션과 동시에 존재하는 화면

- `unfinished_sessions()`는 삭제 의도와 tombstone을 계속 제외한다. pending 목록이 그 API에 섞이지 않는다. 정상 세션 목록도 숨김을 유지한다.
- `finalize_unfinished`는 삭제 의도 우선으로 DELETE_PENDING을 거부한다. live지만 삭제 의도가 없으면 SESSION_LIVE다. `recover_session`의 삭제 의도 응답(채택0/DELETE_PENDING)과 live 거부도 유지한다. G-P04의 확정·내보내기 허용 조건을 완화하지 않는다.
- 삭제가 먼저 선형화되면 복구/확정으로 폴더나 catalog 행을 되살리지 않는다. 복구·확정이 먼저 끝난 경우 그 결과까지 사용자가 요청한 삭제 범위에 포함될 수 있다. 지워진 원본을 복원해서 삭제를 완성하지 않는다.
- `_is_live`는 `has_active_writer` 또는 등록된 owner의 is_live를 사용한다. 같은 세션의 live 여부를 이유로 **다른 세션**의 삭제/녹음/확정을 막지 않는다. 기존 식별 불가능한 legacy Job은 안전하게 보류할 수 있으며 이유를 고지한다.
- export가 먼저 완성한 외부 사본은 남는다. 삭제 뒤 새 export는 거부한다. 진행 중 export는 파일 잠김/입력 소실/최종 catalog 검사 때문에 실패할 수 있으므로 부분 출력은 완료가 아니다. 세션 폴더 부활0과 `export.json` 완료 표식의 사실 일치를 검사하며 export 전체를 새로 설계하지 않는다.

### 3.2 ACK와 재시작을 혼동하지 않음

현재 `_active_jobs`는 영속 reader receipt도 본다. 단순 Library 재열기나 pending 목록 복원은 실제 reader 종료 증명이 아니다. `JobStore.recover_abandoned(coordinator_exclusive=True)`도 **호출자가 이전 작업/자식의 종료를 증명한다는 기존 계약**이다(`jobs/__init__.py:723`). G05 inventory나 retry가 플래그를 임의로 True로 만들어 blocker를 없애지 않는다. 현재 UI의 `_history` 생성만으로 그 정리가 자동 수행된다고 가정하지 않는다.

UI retry는 기존 `ai_bridge.stop_playback`·`before_delete`를 사용해 현재 실행의 취소·세션 전송 철회를 먼저 요청한다. 실제 ACK가 없으면 대기로 남긴다. 재시작 시험의 독립 observer가 owned 프로세스 종료를 확인하고 기존 정상 reader 복구/ACK가 적용된 경우에만 제거 진행을 기대한다. **고아 reader 정리의 새 자동화/새 종료 증명 UI는 이 단위 기본 범위 밖**이다. 이전 reader 판정이 남아 끝내 진행할 수 없는 실제 반례가 나오면 C00에게 Job/앱 추가 범위를 요청하며 성공으로 덮지 않는다.

### 3.3 별도로 남기는 증거 범위

G-P02 이후 `security/consent.py`의 `_session`은 같은 디렉터리 journal과 **ConsentStore 자신이 연 DB의** deleted_sessions를 검사한다. 실제 MainWindow는 security.sqlite와 library.sqlite를 분리한다. 기존 `test_session_deletion_evidence_blocks_already_issued_permit`의 DB tombstone fixture는 ConsentStore의 같은 DB에 표를 만든다. **별도 library.sqlite의 DB-only tombstone까지 이 node가 검증한 것은 아니다.** 이는 코드 읽기로 확인한 시험 범위 차이이며 이번에 새 Gateway 반례를 실행한 결과는 아니다.

G05 UI/CLI retry는 기존 세션 철회와 의도 보강을 거치고, storage의 어느 한 의도 우선/부활 금지를 검사한다. 별도 DB 구성의 임의 직접 Gateway 호출까지 신규 송신0을 보장했다고 확대하지 않는다. 이 경계까지 G05에 묶으려면 `security/consent.py`와 보안 시험 추가 및 G-P02 커밋 이후 순서가 필요하다. **권고는 기본 G05 9파일을 유지하고 C00이 보안 경계 후속 단위 여부를 명시하는 것**이다.

## 4. UI와 CLI

### 4.1 UI 복원

MainWindow 초기 구성/정상 세션 목록 갱신에서 `pending_deletions()`를 읽어 `_pending_deletions`를 **영속 목록의 화면 캐시**로 갱신한다. 메모리 dict가 정본이 되지 않는다. 시작·조회만으로 삭제 재시도/AI/다운로드를 실행하지 않는다. G-P04의 복구 안내와 별도 영역에 ID의 짧은 표시, 현재 이유, 잔여 폴더 유무, 보강 필요, 대기 건수를 보여준다. 전체 ID는 비민감 상세에서 확인할 수 있다.

기존 버튼을 선택 항목의 **삭제 대기 재시도**로 연결하고, 여러 항목에는 **모두 재시도**를 제공한다. 실행 중에는 중복 클릭을 막는다. 표시한 `(session_id,generation)`을 고정하며 다른 세션을 삭제하지 않는다. 이미 승인된 의도를 완료하는 동작이므로 정상 retry에 일반 세션 삭제 확인을 다시 띄우지 않는다. stale이면 자동으로 새 세대에 재시도하지 않고 재조회·재선택한다.

- 실패 시 목록에서 사라지게 하거나 삭제 완료 문구를 쓰지 않는다. 현재 MEDIA_REMOVAL_FAILED / SESSION_LIVE / reader 종료 대기 / metadata 정리 대기 / 이력 확인 필요를 구분한다.
- 폴더가 없고 기록 보강만 남으면 “원본이 남아 있다”고 단정하지 않는다. “삭제 기록 확인/정리 대기”라고 표시한다.
- 조회 실패는 “삭제 이력 확인 불가” 상태다. 마지막 성공 목록이 있다면 확인 전 목록으로 남기고 retry를 막는다. 최초 실패면 **대기0건**으로 표시하지 않는다. 재조회 버튼은 허용한다.
- 배치의 한 항목 실패는 다른 항목 결과를 지우지 않는다. 각 결과와 재조회 결과를 반영한다. 늦은 callback이 더 새 generation의 항목을 완료 처리하지 못하게 한다.
- 정상 완료 확인 후에만 항목을 제거하고 완료 건수를 표시한다. 접근성 이름·키보드 선택·실패 이유 텍스트를 제공한다. 기존 녹음 저장 오류 경고의 우선순위와 G-P04 미확정 세션 안내를 유지한다.

### 4.2 CLI도 노출하는 권고안

| 명령 | 결과/호환 |
| --- | --- |
| `recoryn list --delete-pending` | pending_deletions의 비민감 JSON 목록. --unfinished와 상호 배타. 조회만 수행하고 ConsentStore 실행 세대를 바꾸지 않음 |
| `recoryn delete ID --retry-only [--expected-generation N]` | 기존 의도만 retry. N 생략 시 현재 inventory의 g를 캡처하고 API에 전달. 의도 없음은 NOT_PENDING으로 거부 |
| 기존 `list`, `list --unfinished`, `finalize`, `delete ID` | G-P04/기존 의미와 출력 호환 유지. 새 retry 성공 정책을 옛 delete의 exit 의미에 소급하지 않음 |

새 `--retry-only`는 완료0, 대기/NOT_PENDING2, 이력 손상·stale·저장 오류1을 제안한다. 정상 list는0, 조회 실패1이다. 두 목록 flag 동시 사용, retry-only 없는 expected-generation, 잘못된 N은 parser 오류2이며 Library를 열기 전에 거부한다. 예외 본문/절대 경로 대신 닫힌 코드로 출력한다. DELETION_HISTORY_UNAVAILABLE / DELETE_HISTORY_CONFLICT / STALE_DELETE_GENERATION / DELETION_METADATA_PENDING과 현재 대기 이유를 사용하며 다른 명령의 기존 안전 오류 계약은 보존한다. 실제 CLI 명령명·새 exit2 정책은 C00 승인 항목이다.

## 5. 경우의 수·분모·독립 oracle

### 5.1 유한 대표 집합

아래는 **계획**이다. Ω/F/실행 부분집합 E를 구별하며 현재 E=0이다. 가족별 Ω=F, 구성 불가능 제외0이다. 물리 상태와 모순되는 DB/journal 조합도 손상 fixture로 구성 가능하므로 거부 대상으로 포함한다. “필요 시 발생하도록 설정한 다음 제거 결과”는 해당 단계에 도달하지 않으면 **호출0**을 oracle로 삼으며 그 행을 제거하지 않는다. 가족 간 모든 차원의 직적을 시험했다는 주장은 하지 않는다.

| 가족 / 계층 | 입력 분할·분모 | Ω=F / E |
| --- | --- | --- |
| INV / unit | DB 없음/PENDING/LOCAL 3 × journal 없음/정상/손상/tmp 4 × 세션 행 유무2 × 폴더 없음/전체/부분3. live blocker는 없는 고정 fixture | **72 / 0** |
| GEN / unit | D 상태2 × 세대 형태(동일2, J3>D2, D3>J2, S3>J2=D2, 모두 MAX)5 × 폴더3. S 행과 양쪽 의도는 항상 존재. MAX=2^63−1 | **30 / 0** |
| RETRY / integration | 의도 DB-only/J-only/둘다3 × 정상 제거/첫 제거 전 PermissionError/파일1개 제거 뒤 PermissionError/metadata commit 실패/다른 actor가 먼저 완료5 × 같은 Library/닫고 재열기2. 초기에는 실제 파일2개 이상 | **30 / 0** |
| CRASH / owned subprocess·재열기 | 아래 삭제 checkpoint8 × 예외 후 정상 close·reopen/owned child 강제 종료2 × 다음 제거 주입 정책(정상/다시 잠김/호출 시 이미 파일 없음)3 | **48 / 0** |
| LIVE / unit·integration | 없음/owner만 live/등록 owner 종료/실제 synthetic writer/활성 local reader/REMOTE_UNKNOWN이지만 local ACK 완료6 × 의도 출처3 × 종료·ACK 전/후2. writer fixture에는 실제 임시 폴더가 존재 | **36 / 0** |
| ORDER / barrier integration | 같은 세션의 다른 동작 recover/finalize/export/다른 삭제 actor4 × 새 삭제(기존 FINALIZED)/기존 PENDING retry2 × A먼저/B먼저2 | **16 / 0** |
| EXPORT / integration | 아래 별도 명시한 복사/삭제 경계4 | **4 / 0** |
| TRACE / bounded state model | 명령 delete/retry/reopen/unlock/recover/finalize/export 7종, 길이0..4 전수. `1+7+49+343+2401` | **2,801 / 0** |
| HISTORY / unit·fault | 아래 손작성 손상 fixture22 | **22 / 0** |
| TYPE / unit | ID 오류5 + expected_generation 오류7의 단일 변경 fixture | **12 / 0** |
| UI / offscreen | inventory 빈/대기/오류3 × 기존 창/새 Library·새 창2 × 조회/선택retry/모두retry3 × retry 완료/다시잠김/그사이이미완료3 =54, 다항목·늦은 callback 명시6 추가 | **60 / 0** |
| CLI / e2e | 기본list/unfinished list/pending list/retry4 × 정상세션/pending/완료/손상이력4 × main 호출/새 subprocess2 =32, parser 음성3 추가 | **35 / 0** |
| 합계 | 대표 집합 합계. 실제 pytest node 수는 아직 미확정 | **3,166 / 0** |

### 5.2 CRASH checkpoint의 정확한 의미

| checkpoint | 강제 종료 직후 예상되는 사실 |
| --- | --- |
| C0 의도 파일·tmp 작성 전 | 영속 의도 없음. 삭제 완료·대기 접수를 추정하지 않음. 원본 그대로 |
| C1 tmp fsync 뒤, journal rename 전 | kill이면 `.tmp-`가 남아 이력 확인 불가. 예외 후 정상 unwind는 atomic_json의 finally로 tmp가 제거되므로 의도 없음. 두 mode의 차이를 oracle에 명시 |
| C2 유효 journal 게시 뒤, DB pending commit 전 | J-only. 목록에 대기, 자동 복구 재채택0 |
| C3 DB pending commit 뒤, 첫 media unlink 전 | 양쪽 의도·원본 잔존, 완료 아님 |
| C4 세션 폴더 내 첫 unlink 뒤 | 일부 잔존, 남은 파일 hash 유지, 다음 retry로 진행 |
| C5 폴더 제거 뒤, metadata 정리 transaction 전 | 파일 없음·DB pending, 완료 아님 |
| C6 metadata DELETE/UPDATE 뒤, COMMIT 전 | kill 시 transaction rollback. 파일 없음·pending을 재발견하고 정리 가능 |
| C7 tombstone COMMIT 뒤, 응답/GUI callback 전 | 실제 완료. 재열기 pending에서 제외, 같은 g retry는 already_deleted=True |

kill은 테스트가 만든 자식만 대상으로 하며 별도 프로세스/원자 checkpoint 파일로 정확한 도달을 확인하고 wait/종료 확인 뒤 연다. 타인의 worker·pane·서비스를 종료하지 않는다. checkpoint는 테스트 사본의 monkeypatch/connection proxy로 만들고 제품에 전용 test hook을 추가하지 않는다. 정상 예외와 kill을 같은 결과로 가정하지 않는다. 전원 차단·스토리지 controller cache 내구성의 대체 시험이 아니다.

CRASH의 세 번째 축은 **제거 단계에 도달했을 때만** 적용하는 시험 주입 정책이다. C0/손상 C1처럼 retry 자격이 없으면 세 정책 모두 remover 호출0이며, 그 축을 이유로 새 삭제 의도를 만들거나 tmp를 정리하지 않는다. 이미 파일 없음 정책도 의도 검사 전에 원본을 없애는 fixture가 아니다. 다른 삭제 actor의 실제 선행 완료·같은 generation 멱등은 RETRY/ORDER에서 별도로 검사한다. UI54의 다음 retry 결과 축도 호출 자격이 없으면 callback 호출0을 확인하는 같은 방식이다.

### 5.3 동시성·export·상태열 oracle

ORDER는 Library 동작의 root mutex 구간 전후에 Event/barrier를 두고 양 순서를 강제한다. 새 삭제 전 recover/finalize/export가 완료될 수 있지만 삭제 이후 새 복구/확정/내보내기 성공은 허용하지 않는다. pending retry를 시작하는 행에서는 상대 동작도 이미 의도 아래 있으므로 거부/채택0이 맞다. 삭제 actor가 둘이면 첫 완료 뒤 두 번째는 멱등이다. scheduler sleep으로 순서를 전수 실행했다고 쓰지 않는다.

LIVE의 각 행도 inventory/retry만 보지 않고 같은 세션 recover/finalize/export의 삭제 의도 우선 결과를 함께 확인한다. live owner/실제 writer 양성 fixture에서는 의도 작성 전 G-P04의 SESSION_LIVE(기존 live writer 거부 포함)도 대조한다. 이는 같은 행의 선후 assertion이며 별도 case 수로 늘리지 않는다. weak owner fixture는 ACK 전까지 강한 참조를 유지해 GC로 live가 사라진 것을 정상 종료로 오인하지 않는다. 별도 정상 세션에 대한 작업도 함께 관찰해 전역 차단으로 시험을 통과하지 못하게 한다.

EXPORT4는 (E1) 복사와 export.json 게시가 먼저 끝남→삭제 후 외부 사본 보존, (E2) 삭제가 먼저→새 export 거부, (E3) snapshot 뒤 첫 입력 open 전에 삭제→안전 실패·완료 표식 없음, (E4) 파일을 읽는 동안 삭제가 잠김/부분 실패→삭제 대기·ACK 후 retry 완료다. 마지막은 owned 합성 reader/복사 barrier로 Windows 파일 소유를 제어한다. export의 최종 검사 전 실패를 complete로 올리거나 외부 사본 회수를 약속하지 않는다.

TRACE의 독립 모델은 `영속의도, g, DB세션존재, 파일존재, tombstone, 제거잠김, 정상세션확정여부`만 보유한다. 초기에는 유효한 합성 세션/원본과 제거 PermissionError blocker가 있다. unlock은 이 test blocker만 해제한다. reopen은 UI 캐시·프로세스 상태를 지우지만 **영속 의도와 잠김 조건**을 지우지 않는다. reader ACK를 생성하는 사건이 아니다.

- delete는 최초에 의도를 남기고, 잠김이면 pending, 해제됐으면 로컬 완료다. 이미 완료된 ID에 새 의도를 생성하지 않는다.
- retry는 의도가 없으면 NOT_PENDING, pending+잠김이면 pending, pending+해제면 완료, 완료면 멱등이다.
- recover는 의도 있으면 채택0·삭제 상태, finalize/export는 의도 있으면 거부다. 의도 없는 세션의 확정/복구는 G-P04의 손작성 상태 규칙으로 검사한다.
- 원본 부활0, completed 이후 pending 강등/세대 감소0, 오류를 성공으로 표시0, tombstone 자동 소실0을 매 prefix에서 검사한다.

모델은 제품 전이표나 `_deletion_intents`를 oracle로 import하지 않는다. 우선 trace마다 독립 TEMP fixture로 실행한다. prefix 공유 최적화를 쓰려면 파일 삭제·journal·DB·시계·owner 복원이 동치임을 입증하고 별도 검토받는다. SQLite rollback만으로 지워진 파일까지 복구됐다고 가정하지 않는다. 깊이4 밖은 미검증이며 delete→reopen→unlock→retry 같은 핵심 길이4를 포함한다.

### 5.4 손상·타입·다항목 명시 행

HISTORY22는 H01 journal 디렉터리 유실, H02 남은 tmp, H03 JSON 구문 손상, H04 중복 JSON 키, H05 파일명/ID 불일치, H06 traversal ID, H07 미래 schema, H08 잘못된 state, H09 generation0, H10 음수, H11 JSON bool, H12 정수 overflow, H13 generation 누락, H14 DB 미지원 status, H15 DB generation0, H16 DB generation 문자열, H17 DB generation REAL, H18 JSON 최상위 list, H19 journal 경로가 일반 파일, H20 알 수 없는 확장자/항목, H21 열린 DB의 deleted_sessions 표 소실, H22 journal 읽기 PermissionError다. 전부 **빈 목록·완료로 바꾸지 않음**, destructive call0, 원래 기록 불변을 검사한다. 실제 symlink/reparse 권한이 필요한 경우는 기존 경로 안전성 회귀에 연결하고 성공하지 않은 OS fixture를 PASS로 세지 않는다.

TYPE12는 ID의 빈값/traversal/절대경로/None/bool 5개, expected_generation의 0/−1/True/1.5/문자열/None/MAX+1 7개다. 정상 ID·양의 정수 g를 기준으로 하나씩 바꾼다. TYPE와 journal 저장 데이터 오류는 다른 경계를 검사한다. SQLite가 bool을 정수로 변환한 뒤 원래 bool임을 알아낼 수 있다고 주장하지 않는다.

UI 추가6은 U1 A실패/B완료, U2 모두완료, U3 옛 generation의 늦은 완료 callback, U4 마지막 성공 목록 뒤 조회 실패, U5 pending A 복원이 live B 녹음/미확정 안내를 방해하지 않음, U6 완료 후 마지막 항목 제거·버튼 비활성·다음 새 창에서도 빈 목록이다. CLI 추가3은 상호 배타 목록 flag/잘못된 expected-generation 사용 위치/숫자 파싱 오류다.

### 5.5 파일·DB 사실과 case ID 감사

독립 oracle는 baseline 상대 파일명→SHA256 map, 세션 폴더 존재, raw SQL의 sessions/chunks/deleted_sessions와 해당 세대/상태, 원자 게시된 journal bytes를 비교한다. 삭제 중에는 남은 파일 hash가 baseline과 같아야 하며, 지운 파일은 의도 후 허용한 부분 집합이어야 한다. 완료면 해당 폴더 없음·관련 catalog 정리·양쪽 최소 의도 보존이 맞아야 한다. 사본을 다시 열어 list/unfinished에서 부활하지 않고 recover adopted/recovered0, 새 create_session 같은 ID 거부를 확인한다.

읽기 API 전후에는 **논리 SQL 행·사건·파일 목록/hash**를 비교한다. SQLite WAL/checkpoint 때문에 DB raw 파일 hash가 달라질 수 있는 것을 읽기 API의 쓰기라고 단정하지 않는다. UNKNOWN ledger 행·금액·witness는 보존하고, 기존 UI/CLI 세션 철회로 consent DB가 달라지는 것은 허용한 별도 동작이다.

ID는 `G05-{family}-{고정폭 ordinal}`이며 CRASH에는 checkpoint/mode/outcome을 property로 적는다. 생성기와 별개의 고정 분모 상수 `72,30,30,48,36,16,4,2801,22,12,60,35` 및 정수 ordinal 복원으로 기대 집합을 만들고 registry와 실행 JUnit/loop 고유 ID를 대조한다. 누락·중복·추가·skip0을 요구한다. loop 내부 행·pytest node·property 예제·kill 횟수를 한 숫자로 합산하지 않는다. 아직 수집·생성·실행하지 않았으므로 현재 관측수0이다.

## 6. 기존 시험과 새 증거의 관계

| 존재/본문을 확인한 기존 node | 보존할 근거 / 새 목적 |
| --- | --- |
| `tests/unit/test_storage.py::test_delete_intent_before_files_and_no_resurrection` | PermissionError 후 대기·복구 채택0·동일 창 재삭제는 기존 직접 시험. 새 API·재시작 UI·실제 kill로 보강 |
| 같은 파일 `::test_deletion_history_and_single_intent_priority` | DB-only/J-only·손상 이력 우선. INV/GEN은 목록·세대·완료 제외를 추가 |
| `tests/integration/test_storage_integrity.py::test_journal_only_deletion_intent_blocks_recovery_and_can_resume` | journal 게시 직후 예외·재열기. CRASH는 kill과 제거/DB commit 중단도 추가 |
| 같은 파일 `::test_deleted_media_cannot_be_resurrected_from_a_stale_bundle`, `::test_delayed_writer_cannot_recreate_media_after_successful_delete` | stale 파일·늦은 writer의 부활 방지 회귀 |
| `tests/ui/test_live_ui.py::test_delete_pending_keeps_visible_reason_and_retries_hidden_session_after_reader_ack` | 같은 창/실제 reader ACK 의미 보존. 새 창 복원으로 대체됐다고 쓰지 않음 |
| `tests/integration/test_desktop_independent.py::test_b21_delete_pending_reader_is_visible_as_pending_not_silent_disappearance` | 같은 실행의 대기 표시/완료 구별 유지 |
| `tests/integration/test_publication_independent.py::test_logical_completion_cannot_delete_live_reader_but_ack_allows_deletion` | logical 완료와 local ACK 구별. UNKNOWN을 임의로 풀지 않음 |
| `tests/integration/test_gateway.py::test_unknown_cost_survives_failed_write_restart_and_session_delete` | 삭제 후 비용 UNKNOWN 보존 회귀. G05가 비용 정산을 구현하는 것은 아님 |
| G-P04 `tests/integration/test_unfinished_recovery.py::test_h3_finalize_and_delete_linearize`, `::test_h4_live_recording_refuses_recovery_and_finalize` | 현재 작성 중 node의 존재 확인만 했다. push 뒤 정확한 G-P04 기준에서 실행해 선행 게이트로 삼음 |

기존 보안·Job·content 삭제 fence 및 G-P02/G-P03·G-P04 새 시험과 tests/ui 전체를 회귀한다. 기존 시험 node를 신규3166행으로 합산하지 않는다. PermissionError 한 번으로 실제 kill·전원 장애 검증을 대체하지 않는다.

## 7. mutation 계획

정상본이 통과한 뒤 OS TEMP의 pyproject/src/tests/scripts/packaging 사본에 한 번에 하나씩 적용한다. 실제 사본 import 경로·원본/변이 hash·명령·실패 node·case ID를 기록한다. import/수집 오류·권한·timeout은 invalid이며 검출로 세지 않는다. 다음 **22개 계획**, 실행0이다.

| ID | 결함 | 독립 관측 |
| --- | --- | --- |
| M01 | inventory에서 journal-only 누락 | INV의 J-only 대기 |
| M02 | inventory에서 DB-only 누락 | INV의 D-only 대기 |
| M03 | 모든 journal을 pending으로 취급 | 정상 완료 tombstone 제외 |
| M04 | DELETED_LOCAL이면 잔여물과 무관하게 숨김 | INV의 세션/폴더 잔존 |
| M05 | inventory가 자동 제거 수행 | 조회 전후 파일/논리 DB 불변 |
| M06 | retry에 의도가 없어도 새 delete 수행 | 정상 세션 NOT_PENDING·원본 보존 |
| M07 | expected_generation 비교 제거 | GEN/UI stale 거부 |
| M08 | 한쪽의 더 낮은 generation으로 보강 | GEN의 최댓값·세대 감소0 |
| M09 | 완료 후 journal/tombstone 제거 | 재열기·같은 ID/고아 재채택 거부 |
| M10 | 폴더 없으면 DB 정리 없이 완료 | C5/C6·DB pending 제거 |
| M11 | 제거 예외에서 deleted=True | RETRY/CRASH/UI 완료 오표시 금지 |
| M12 | 파일 제거보다 DB 정리 먼저 | C3/C4·남은 원본과 catalog 사실 |
| M13 | live owner 무시하고 writer만 검사 | LIVE의 첫 블록 전·writer 사이 |
| M14 | local reader ACK 무시 | LIVE/기존 reader 회귀 |
| M15 | UI 시작 시 메모리 빈 dict만 사용 | 새 창 pending 복원 |
| M16 | 목록 오류를 []로 변환 | UI/HISTORY의 확인 불가 표시 |
| M17 | 배치 한 실패에서 나머지 결과 누락 | UI-U1의 A실패/B완료 |
| M18 | 옛 generation callback을 현재 행에 적용 | UI-U3의 새 행 보존 |
| M19 | CLI pending list를 정상 list로 대체 | CLI의 숨긴 pending 노출 |
| M20 | CLI retry pending을 성공 exit0 | 신규 retry exit2 |
| M21 | recover의 삭제 의도 우선 검사 제거 | ORDER/TRACE 부활0 |
| M22 | 손상/tmp 이력을 무시하고 진행 | HISTORY/C1의 destructive call0 |

## 8. 승인 요청하는 정확한 쓰기 범위·대안

후속 구현 권고 범위는 **9파일(제품3·신규 시험5·이 문서1)**이다. G-P04 push 뒤 동일 파일을 넘겨받는다. G-P04 기능·계약을 되돌리지 않는다.

| 파일 | 제안 변경 |
| --- | --- |
| `src/recoryn/storage/library.py` | 읽기 inventory, 기존 의도 전용 retry·세대/완료 정합, 공유 제거 진행부와 live guard |
| `src/recoryn/ui/main.py` | 시작 복원·선택/모두 재시도·조회 실패·다항목 표시, G-P04 영역 보존 |
| `src/recoryn/cli.py` | 새 목록 flag·retry-only·닫힌 JSON/exit, 기존 명령 호환 |
| `tests/unit/test_pending_deletions.py`(신규) | INV/GEN/HISTORY/TYPE와 read-only/완료 oracle |
| `tests/property/test_pending_deletion_case_space.py`(신규) | TRACE/manifest·상태 모델 |
| `tests/integration/test_pending_deletion_restart.py`(신규) | RETRY/CRASH/LIVE/ORDER/EXPORT, owned child·실제 TEMP 파일 |
| `tests/ui/test_pending_deletion_ui.py`(신규) | UI60·새 창/다항목·늦은 callback |
| `tests/e2e/test_cli_pending_deletions.py`(신규) | CLI35·새 프로세스/파싱/exit |
| `docs/testing/g05-pending-deletion-cases.md` | 승인·실행·한계·독립 검토 인계 |

기존 API는 additive이므로 기존 시험 파일 수정은 지금 요청하지 않는다. 실제 실패로 fixture 적응이 필요하면 수정 전에 파일·실패·변경안을 C00에게 요청한다. `ui/ai_bridge.py`, `ui/privacy.py`, `app/ai.py`, `app/recovery.py`, `app/recording.py`, Job·security·content·공용 설정은 **기본 쓰기 범위 밖**이다. §3.2/3.3의 추가 경계 해결을 C00이 요구하면 별도 범위·의존 순서를 승인받는다.

| 대안 | 장점 | 한계/권고 |
| --- | --- | --- |
| UI 메모리 목록을 별도 설정 파일에 저장 | UI만 바꿀 수 있음 | DB/journal과 제3 정본이 어긋남. 권고하지 않음 |
| 시작 때 모든 pending 자동 삭제 | 재시도 클릭 불필요 | 실행 중 reader·불완전 이력·잘못된 성공 위험. **조회만 복원+명시 retry 권고** |
| journal 존재만으로 목록 생성 | 구현 단순 | 정상 완료 tombstone도 매번 대기로 보임. DB/잔여물 정합 필요 |
| Library 조회+기존 delete_session 재사용만 | 변경량 적음 | ID 오인 시 새 삭제, stale 세대, 완료 기록 불일치 우려. 의도 한정 retry API 권고 |
| UI만 제공, CLI 없음 | 공유 파일 하나 감소 | headless에서 목록 발견 경로 없음. CLI additive flag 권고, C00이 제외하면 CLI35와 파일2개의 계획 변경을 명시해야 함 |
| 오류 사유를 새 DB 표에 영속화 | 재시작 뒤 이전 오류의 정확한 설명 가능 | migration/보존·일관성 범위 증가. 이번에는 현재 이유와 과거 사유 미보존을 구분 |

C00 승인 요청: (1) 9파일·G-P04 push 이후 순서, (2) 읽기 inventory 정합표·세대 max 보강과 S가 더 새로우면 보류, (3) required expected_generation과 no-intent NOT_PENDING, (4) 초기 delete의 live-owner 보류 강화, (5) UI/CLI 명령·새 retry exit2, (6) **3166행·22 mutant 계획**, (7) 고아 reader 종료 증명 자동화와 별도 DB-only 보안 경계는 기본 범위 밖이라는 한계·후속 소유자. 이 승인 요청은 구현 완료나 독립 검토 승인이 아니다.

## 9. 구현 후 제출 게이트와 현재 결과

G-P04 push/CI와 C00 시작 신호 뒤 정확한 기준 commit·파일 hash를 기록한다. 정상본에서 선언3166행의 누락/중복/추가/skip0, 원본 부활0·완료 오표시0·tombstone 유지·재시도 멱등을 직접 보고한다. 고비용 subprocess/상태 모델의 실제 시간도 기록하고, 축소가 필요하면 **측정값·새 분모·제외 근거를 먼저 C00에게 제시**한다. 파일/전이 guard를 stub해 속도를 맞추지 않는다.

기존 삭제·Job reader·Gateway/비용·G-P02/G-P03/G-P04와 tests/ui 전체, TEMP mutation, ruff check·승인 파일 format check, `python -m mypy src/recoryn scripts packaging`를 검증한다. 최종적으로 **HEAD(G-P04 포함)+G-P05 승인 파일만**인 TEMP archive 사본에서 전체 오프라인 회귀를 실행한다. `-p no:cacheprovider`, 고유 OS TEMP basetemp, bytecode 억제, `QT_QPA_PLATFORM=offscreen`, 실제 장치/모델/네트워크/vault 쓰기 차단을 적용한다.

현재는 **계약 문서와 기존 코드/시험 본문 읽기·분모 산술 확인 단계**다. 새 코드0·새 시험 실행0·mutation0·process kill0이다. 실제 제품 동작/Windows 파일 잠김·전원 장애·외부 백업 복원을 검증했다고 주장하지 않는다. C00 승인과 작성자 외 독립 검토 전 G-P05를 완료 처리하지 않는다.

## 10. 구현 반영(2026-11-23)

기준 HEAD **8e09b62ad1bb94475b5895e53438dbbe45a8b18d**(G-P04 포함). 증거 루트 **R=`C:/Users/gangd/AppData/Local/Temp/recoryn-g05-mslXHyqS`**. 개발·mutation 사본 R/iso와 판정 사본 R/final은 `git archive 8e09b62`에 아래 10파일만 덧씌운 것이다(R/iso는 dotfile 3개를 옮기지 않았다, §11.4). 같은 작업 트리에서 진행 중인 G-P06(security/providers/adapters/app/ai·ui/privacy 등)·GT-P03(test_unfinished_recovery.py, g04 문서) 변경은 사본에 넣지 않았고 그 파일들을 수정하지 않았다.

### 10.1 C00 결정

- §8 (1)~(7)을 권고안대로 승인. 고아 reader 종료 증명 자동화와 별도 library.sqlite의 DB-only 기록을 ConsentStore가 직접 보지 못하는 경계는 통합 계획 '이후' 항목으로 남긴다.
- G-P04 교훈: live owner 추적·세션 claim·삭제 의도 우선을 되돌리지 않고 그 위에 얹는다. 폴더 제거·파일 시스템 열거·경로 검사는 root mutex 밖, mutex는 짧은 상태 확인·기록에만 쓴다. 관리 스레드 root mutex 최대 보유 ≤50ms·50ms 이상 보유 0건·결과 ok를 시험한다. 대기 목록 조회는 GUI thread가 아닌 worker에서 세대 번호로 늦은 결과를 버린다. 목록 재구성에서 선택이 사라지면 privacy 패널 등에 None이 전달되는 G-P02 §2.4 계약을 지킨다.
- **G04-T-RECORDING_LIVE-DELETE 기대값을 G-P05 (4)로 대체(DELETED_LOCAL → DELETE_PENDING/SESSION_LIVE), C00 승인.** 쓰기 범위에 `tests/unit/test_unfinished_sessions.py`를 추가하되 `_DELETE` 표의 한 항목과 그 행의 SESSION_LIVE 사유·journal 의도 기록·원본 보존 확인만 허용했다. REFUSALS 집합·원본 보존 검사·다른 행 기대값은 바꾸지 않았다. 수정 전 LF SHA256 `d6d54873dd2255141d02286d2102844dceccea5af61a95b5ae9234ecb39fcc3d`(HEAD), 수정 후 §11.6 표.

### 10.2 제품 변경

| 파일 | 변경 |
| --- | --- |
| `storage/library.py` | `pending_deletions()`, `retry_deletion(id, *, expected_generation)`, 읽기 전용 `deletion_generation(id)` 추가. `delete_session`과 retry가 공유 진행부 `_progress_deletion`을 쓴다. 이력 엄격 검증 `_deletion_history`(journal + DB 행의 ID·양의 정확한 int 세대·지원 status), journal 선읽기 `_journal_prefetch`, live/reader/claim 보류 `_deletion_blocker`, 제거·tombstone 단계 `_remove_and_seal` |
| `ui/main.py` | 삭제 대기 목록·상세·‘삭제 대기 재시도’(선택)·‘모두 재시도’, 시작/새로고침 때 worker 조회와 세대 번호, 조회 실패의 확인 전 표시, 재시도 결과·늦은 결과 처리, 목록 재구성 중 사라진 선택의 신호 발신 |
| `cli.py` | `list --delete-pending`(--unfinished와 상호 배타), `delete ID --retry-only [--expected-generation N]`, 닫힌 코드·exit |

### 10.3 계약안과 달라졌거나 구체화한 점

1. **이력 오류 표현.** 기존 `_deletion_intents()`도 같은 엄격 검증을 쓰므로 G-P04 경로(목록·복구·확정·get_session)의 이력 실패 메시지가 `DELETION_HISTORY_UNAVAILABLE` 하나로 바뀌었다. 예외 형식(ValidationError⊂ValueError)은 같다. DB의 미지원 status·세대 0/TEXT/REAL과 열린 DB의 표 소실·journal 읽기 PermissionError(OSError·sqlite3.Error)도 이제 모든 경로에서 같은 ValidationError로 안전 실패한다. `DELETE_HISTORY_CONFLICT`·`STALE_DELETE_GENERATION`은 StateConflict, `DELETION_METADATA_PENDING`은 ValidationError다.
2. **delete_session의 기존 의도 처리.** 결과 dict 형태(키)는 그대로다. 기존 의도가 있으면 세대 g=max(D,J)를 보존한다(이전에는 D-only에서 J를 새 세대로 썼다). 완료 tombstone을 DELETE_PENDING으로 잠시 강등하지 않는다(이전에는 upsert가 강등했다). 정상 완료 기록에는 빠른 경로로 DELETED_LOCAL을 돌려준다. 저장 예외는 delete_session에서 원래 형식 그대로 전파한다.
3. **보류 사유 순서.** 목록·retry·초기 delete 모두 SESSION_LIVE(`_is_live`: 열린 writer 또는 live owner) → ACTIVE_READER_OR_WRITER(`_active_jobs`) → SESSION_OPERATION_IN_PROGRESS(다른 claim)다. 그래서 열린 writer가 있을 때 delete_session의 reason이 이전 ACTIVE_READER_OR_WRITER에서 SESSION_LIVE로 바뀐다(state/deleted 동일, 이 값을 검사하는 기존 시험 없음). 목록 reason은 그 뒤 JOURNAL_REPAIR_REQUIRED(journal 없음·g보다 낮음) → CATALOG_CLEANUP_REQUIRED(폴더 없음) → RETRY_REQUIRED다. J-only의 DB 보강 필요는 repair_required로 표시하고 reason은 폴더 유무를 따른다.
4. **root mutex 경계.** 이력 확인·의도 기록(journal 원자 게시+DB commit)·최종 정리 commit만 root mutex 아래에 둔다. 폴더 제거는 세션 claim 아래·mutex 밖이며 claim을 얻은 뒤 완료·보류를 다시 확인한다. journal 디렉터리 읽기는 mutex 밖에서 먼저 하고, 이 Library가 journal을 쓸 때마다 mutex 아래에서 올리는 `_history_version`이 그 사이 바뀌었으면 mutex 안에서 다시 읽는다(같은 프로세스 협력 계약, 외부 임의 파일 조작은 보장 밖). 목록은 DB 행·journal·catalog 세대를 한 번의 mutex 구간에서 관찰하고, owner/reader/claim 플래그는 64건씩 짧은 구간으로, 폴더 존재는 mutex 밖에서 본다. 따라서 live/active/폴더 값은 시점 관찰이며 retry가 다시 판정한다. `_active_jobs`는 호출자가 넘긴 연결을 쓸 수 있게 했다(조회 결과 동일, 경로 검사 반복만 줄임).
5. **CLI N 생략.** 완료 기록에도 retry가 멱등이어야 하므로 pending 목록 대신 읽기 전용 `deletion_generation(id)`로 현재 g를 캡처한다. 의도가 없으면 NOT_PENDING·exit 2이며 ConsentStore를 열지 않는다. 의도가 있으면 기존 세션 철회 뒤 retry한다. 확인된 DELETED_LOCAL만 exit 0, DELETE_PENDING/NOT_PENDING은 2, 이력·stale·충돌·저장 오류는 1과 닫힌 code다. 잘못된 ID는 `INVALID_SESSION_ID`. 기존 `delete ID`는 대기여도 exit 0을 유지한다.
6. **UI.** 목록은 저장소 관찰의 화면 캐시이며, delete/retry worker도 작업 뒤 관찰을 함께 돌려준다. 그 사이 더 새 조회가 요청됐으면 그 관찰을 버린다. 조회 중(확인 중)에도 표시한 (ID, g)로 retry할 수 있고 stale이면 자동 재시도 없이 재조회 결과로 바꾼다. 조회 실패 뒤에는 retry를 막고 마지막 성공 목록을 ‘확인 전’으로 남긴다. retry에는 새 확인창이 없고, `stop_playback`·`before_delete`(세션 전송 철회·취소 요청)를 먼저 부른다. 현재 녹음 세션이면 기존 delete와 같이 recorder를 닫는다. 한 항목의 예외는 그 항목 결과로만 남는다. 목록 재구성 뒤 선택이 바뀌었으면 `currentItemChanged`를 내보내 privacy 패널이 None을 받는다(바뀌지 않았으면 기존처럼 `_session_selected`만 호출).
7. **이력 손상과 새 창.** journal이 손상된 라이브러리는 기존 ContentStore 생성자의 안전 실패로 MainWindow 자체가 열리지 않는다(대기 0건 표시는 생기지 않음). 이 동작은 바꾸지 않았다. UI 오류 행은 창이 열리는 목록 전용 실패인 세대 충돌(S>g)로 구성했고, 열린 창에서의 journal 손상(tmp)은 U4가 확인한다.
8. **E4(읽는 중 삭제).** 실제 export가 audio.pcm을 연 동안 삭제는 MEDIA_REMOVAL_FAILED로 대기하고, export는 끝 무렵의 catalog 확인(capture_health)에서 의도를 보고 StateConflict로 실패한다. export.json 완료 표식은 없다. 계약의 ‘실패할 수 있다’ 범위의 관측이며, 이후 retry로 완료된다.
9. **TRACE 실행 방식.** 2,801 trace마다 독립 TEMP 사본에서 실행하며 prefix를 공유하지 않는다. 같은 프로세스 스레드 풀은 GIL 때문에 252.34초였으므로 자식 프로세스 최대 16개로 나눠 실행한다(각 자식은 배정된 trace를 차례로 독립 사본에서 실행하고 결과·ID를 원자 게시). 자식은 `-W error::ResourceWarning`이며 경고·예외 출력이 있으면 실패다.
10. **CRASH kill.** kill 24행은 행마다 자기 사본과 자식을 쓰되 동시에 시작하고, 각자의 checkpoint 표식이 원자 게시된 뒤에만 그 자식을 kill·wait한다. checkpoint hook 소스는 unwind 행과 자식이 같은 문자열을 실행한다. 제품에 test hook은 없다.
11. **시험 외 추가 node(case ID 아님).** 파일별 분모 manifest 5, TRACE 깊이별 실행 node 5, C00 요구 PERF 2(목록 400건·10,800파일 retry), UIX 2(선택 소멸 시 privacy None, worker 조회·세대), CLI 기존 delete exit 호환 1.

### 10.4 남은 범위·미검증

실제 Windows 파일 잠김은 E4의 열린 읽기 handle 한 경우만 관측했다. 그 밖의 잠김은 시험 blocker(PermissionError)다. 전원 차단·controller cache·외부 백업/원격 사본 소거, 실장비 녹음, 같은 사용자의 경로 교체 경쟁, 다른 프로세스 reader의 OS 종료 증명은 검증하지 않았다. TRACE 깊이 5 이상, 같은 세션 이외 동작과의 전체 직적은 미검증이다. 녹음 writer 자체의 긴 seal 보유와 그로 인한 거부·유실은 G-P15 범위로 측정만 했다. ConsentStore(security.sqlite)가 별도 library.sqlite의 DB-only 삭제 기록을 직접 보지 못하는 경계(§3.3)는 범위 밖이다.

## 11. 실행 결과(작성자 자체 검증, 2026-11-23)

환경: Windows 11 Pro 10.0.26300, Python 3.13.1(저장소 .venv), `PYTHONDONTWRITEBYTECODE=1`, `QT_QPA_PLATFORM=offscreen`, `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, `HF_HUB_DISABLE_TELEMETRY=1`, `-p no:cacheprovider`, `-W error::ResourceWarning -W error::pytest.PytestUnraisableExceptionWarning`, 실행마다 R 아래 새 basetemp. 실제 장치·모델·네트워크·vault 쓰기는 쓰지 않았다. venv의 recoryn은 경로 기반 editable(.pth)이므로 사본 cwd의 pyproject `pythonpath=["src"]`가 사본 src를 먼저 import한다(직접 확인). 전체 회귀·mutation·TRACE/CLI/CRASH 자식은 PYTHONPATH도 사본 src로 고정했고, mutation과 R/final은 실제 import 파일 위치를 기록했다.

### 11.1 새 시험 5파일·case ID 감사·시간

```powershell
# cwd R/iso (8e09b62 + 승인 10파일)
D:/project/Recoryn/.venv/Scripts/python.exe -B -m pytest tests/unit/test_pending_deletions.py tests/property/test_pending_deletion_case_space.py tests/integration/test_pending_deletion_restart.py tests/ui/test_pending_deletion_ui.py tests/e2e/test_cli_pending_deletions.py -q -p no:cacheprovider -W error::ResourceWarning -W error::pytest.PytestUnraisableExceptionWarning --basetemp R/bt-new5 --junitxml R/new-five.xml
```

직접 결과 **380 passed in 96.54초**, failure/error/skip 0. 이 PC 기준 120초 이내이며 행을 줄이지 않았다.

| 파일 | node | testcase 시간 합 |
| --- | ---: | ---: |
| unit `test_pending_deletions.py` (INV72·GEN30·HISTORY22·TYPE12 + manifest) | 137 | 5.12초 |
| property `test_pending_deletion_case_space.py` (TRACE 2,801을 깊이별 5 node + manifest) | 6 | 30.66초 |
| integration `test_pending_deletion_restart.py` (RETRY30·CRASH48·LIVE36·ORDER16·EXPORT4 + PERF2 + manifest) | 137 | 50.44초 |
| UI `test_pending_deletion_ui.py` (UI60 + UIX2 + manifest) | 63 | 7.97초 |
| CLI `test_cli_pending_deletions.py` (CLI35 + manifest + 기존 delete exit 호환) | 37 | 1.60초 |

독립 감사 `R/audit_cases.py`는 생성기와 별개로 고정 상수 72,30,30,48,36,16,4,2801,22,12,60,35에서 기대 ID 3,166개를 만들고, JUnit node 이름의 `G05-{family}-{NNNN}`과 TRACE 자식 프로세스가 원자 게시한 `trace-ids.json` 5개를 대조했다. **관측 고유 3,166 / 누락 0 / 추가 0 / 중복 0 / skip 0**, 가족별 수가 분모와 같다. case ID가 없는 node 15개(manifest 5, TRACE 깊이 node 5, PERF 2, UIX 2, CLI 호환 1)는 따로 센다. 이전 스레드 풀 TRACE의 252.34초 실행은 같은 2,801 trace 전부 PASS였으나 최종 방식이 아니므로 위 수치에 넣지 않았다.

불변식 직접 보고: **원본 부활 0**(RETRY·CRASH·LIVE·ORDER·EXPORT의 `assert_no_resurrection`·`assert_complete`, TRACE의 매 prefix 폴더 부재), **완료 오표시 0**(제거 실패·metadata 실패·live/reader 보류에서 deleted=False·완료 dict 미반환, UI는 완료 확인 뒤에만 항목 제거), **tombstone 유지**(완료 뒤 D=(g, DELETED_LOCAL)·J=g, TRACE의 강등·세대 감소 0), **재시도 멱등**(같은 g 재호출 already_deleted=True와 논리 행·journal bytes 불변: GEN·RETRY·CRASH C7·ORDER·UI between).

### 11.2 관리 스레드 root mutex 측정(C00 요구)

녹음 writer는 실제 RecordingService, 48kHz mono 10ms 블록을 관리 작업 종료까지 제출(최소 600블록, 상한 300초). 관리 스레드 이름 `g05-management`의 최외곽 보유만 따로 잰다. writer seal의 긴 보유와 거부·유실은 G-P15 범위로 기록만 한다.

| 실행 | 동작 | 관리 시간 | 관리 root 최대 | 관리 보유 횟수 / ≥50ms | 전체 root 최대(스레드) | 거부 / 유실 frame |
| --- | --- | ---: | ---: | ---: | --- | ---: |
| new-five | 목록 400건 | 0.505초 | 0.888ms | 9 / 0 | 2.585초(MainThread create_session, writer seal·register_chunk) | 0 / 0 |
| new-five | retry 10,800파일 | 10.030초 | 1.838ms | 7 / 0 | 1.115초(writer seal) | 0 / 0 |
| 전체 회귀(iso) | 목록 400건 | 0.478초 | 0.876ms | 9 / 0 | 2.571초(같은 스레드) | 0 / 0 |
| 전체 회귀(iso) | retry 10,800파일 | 9.676초 | 1.736ms | 7 / 0 | 1.052초(writer seal) | 0 / 0 |

목록 행의 전체 최대 2.5초는 관리 스레드가 아니라 시험 준비의 `create_session`·`get_session`과 writer의 `register_chunk`다. G-P04의 `_live`→`_deletion_intents()`가 root mutex 아래에서 journal 전체(400개)를 읽기 때문이다. 이 경로는 이번에 바꾸지 않았다(§11.7 위험 1).

### 11.3 mutation

`R/run_mutations.py`가 mutant마다 R/mutations/<ID>에 pyproject/src/tests/scripts/packaging을 복사하고 한 곳만 바꾼 뒤(원본/변이 LF SHA256·명령·실패 node·import 위치를 `results.json`에 기록) `-x`로 실행했다. 정상본은 §11.1에서 PASS다. **계약 22개 + C00 교훈 4개 = 26/26 KILLED**, 전부 pytest exit 1의 assertion 실패이며 survived/invalid/import·수집 오류/timeout 0이다.

| ID | 결함 | 첫 검출 node |
| --- | --- | --- |
| M01 | 목록이 journal-only 누락 | G05-INV-0006 |
| M02 | 목록이 DB-only 누락 | G05-INV-0024 |
| M03 | 모든 journal을 대기로 표시 | G05-INV-0057 |
| M04 | DELETED_LOCAL이면 잔여물과 무관하게 숨김 | G05-INV-0048 |
| M05 | 목록이 원본을 직접 제거 | G05-INV-0007 |
| M06 | 의도 없는 retry가 새 삭제 수행 | G05-TRACE-depth-1(TRACE-0002) |
| M07 | expected_generation 비교 제거 | G05-GEN-0000 |
| M08 | 더 낮은 DB 세대로 보강 | G05-GEN-0003 |
| M09 | 완료 때 tombstone 제거 | G05-GEN-0000 |
| M10 | 폴더 없으면 catalog 정리 없이 완료 | G05-GEN-0000 |
| M11 | 제거 예외에서 deleted=True | G05-TRACE-depth-1(TRACE-0001) |
| M12 | 파일 제거 전 catalog 정리 | G05-TRACE-depth-1 |
| M13 | live owner 무시(열린 writer만 검사) | G05-LIVE-0006 (별도 실행: G04-T-RECORDING_LIVE-DELETE도 실패) |
| M14 | local reader ACK 무시 | G05-LIVE-0024 |
| M15 | UI 시작 시 메모리 빈 dict만 사용 | G05-UI-0020 |
| M16 | UI가 목록 오류를 []로 변환 | G05-UI-0036 |
| M17 | 배치의 한 실패 뒤 나머지 누락 | G05-UI-0054 |
| M18 | 옛 세대 늦은 결과를 새 행에 적용 | G05-UI-0056 |
| M19 | CLI 대기 목록을 정상 list로 대체 | G05-CLI-0016 |
| M20 | CLI 대기 retry exit 0 | G05-CLI-0024 |
| M21 | recover의 삭제 의도 우선 검사 제거 | G05-TRACE-depth-2(TRACE-0012) |
| M22 | 손상/tmp 이력 무시 | G05-INV-0018 |
| X1 | 폴더 제거를 root mutex 안에서 수행 | G05-PERF-retry-10800(관리 보유 6.427초) |
| X2 | 목록 전체(journal·폴더 검사 포함)를 root mutex 안에서 수행 | G05-PERF-inventory-400(관리 보유 0.314초) |
| X3 | 목록 재구성에서 사라진 선택을 알리지 않음 | UIX privacy None |
| X4 | 대기 조회를 GUI thread에서 수행 | UIX worker/세대 |

### 11.4 관련 회귀·정적 검사·전체 오프라인 회귀

관련 회귀는 아래 전체 실행에 포함된다. 같은 실행에 **tests/ui 전체 435**, G-P04 4파일 428(승인된 한 행만 바뀐 unit 파일 포함), G-P05 새 5파일 380, G-P02/G-P03 관련(consent_scope·content·selection_version) 1,403 node가 들어 있으며, 이 수를 서로 더해 고유 node 수라고 하지 않는다.

```powershell
# cwd R/final = git archive 8e09b62 + 승인 10파일만(그 밖의 추적 파일 차이 0, R/implementation-files.json)
D:/project/Recoryn/.venv/Scripts/python.exe -B -m pytest -q -p no:cacheprovider -W error::ResourceWarning -W error::pytest.PytestUnraisableExceptionWarning --basetemp R/final-bt --junitxml R/final-full.xml --durations=10 --tb=short
```

- **판정: R/final 9927 passed in 607.81초 / exit 0**, failure/error/skip 0. 관리 스레드 측정은 목록 400건 0.748ms(9회, ≥50ms 0)·retry 10,800파일 3.670ms(7회, ≥50ms 0), 거부·유실 0이었다.
- 같은 내용의 앞선 R/iso 실행도 9927 passed in 681.92초 / exit 0이었다. R/iso는 처음 추출 때 `.gitattributes`·`.gitignore`·`.github/workflows/core.yml` 세 dotfile을 옮기지 않았다(시험·scripts·packaging에서 읽는 곳 없음을 grep으로 확인). 정확한 사본 기준을 지키려고 R/final을 새로 만들어 다시 실행했고 판정은 R/final로 한다.
- R/final의 `ruff check --no-cache .` PASS, 승인 Python 9파일 `ruff format --no-cache --check` PASS, `python -m mypy src/recoryn scripts packaging` **84 source files PASS**.

### 11.5 새 HEAD와의 호환(참고)

작업 중 C00이 **2933573 (GT-P03, test_unfinished_recovery.py와 문서만 변경)**을 커밋했다. 승인 10파일과 겹치지 않는다. 판정 기준(8e09b62)을 바꾸지 않고, 참고로 `git archive 2933573 + 승인 10파일` R/gt에서 G-P04 4파일(GT-P03판 test_unfinished_recovery.py 포함)을 실행해 **428 passed in 216.69초 / exit 0**을 얻었다(`R/gt.xml` LF SHA256 `cb60d83139df2fab9153be93be6919438c1c6be78c4bcd9238ef4477b3630897`). 2933573 기준 전체 회귀는 실행하지 않았다.

### 11.6 제출 파일

| 제출 파일 | SHA256(LF, CR 제거) |
| --- | --- |
| src/recoryn/storage/library.py | `86ea0d1f4ff4c3de59b5e483dc646cf707b8df1523043fa9f4b1be42ca9ef499` |
| src/recoryn/ui/main.py | `7ea902167f2616820b15f8ef4f24be774bb3a5ab7f13fd2a566a3e3ec738675f` |
| src/recoryn/cli.py | `6572ea1700cddd90363a410fc83f6e5ba5b8f57a68dceee8ac014f04f0849b71` |
| tests/unit/test_pending_deletions.py | `3b0ab4af601b7f22e97abd98baec399032f87055e6ef0c983d6678ad8917d1d7` |
| tests/property/test_pending_deletion_case_space.py | `4c475e6154ea62f395365e384e105f76d52fdde6dd366676c6029b7ae10006f7` |
| tests/integration/test_pending_deletion_restart.py | `3bbdde5a5d3b6784913041f6e7255d14acad3a91883ebe63281c3d2ee1d9b458` |
| tests/ui/test_pending_deletion_ui.py | `c789ba6d2b43d789e24d91fb53c0d2abde407c99abb4b13a4be1e78e1760f5f9` |
| tests/e2e/test_cli_pending_deletions.py | `cfa477abdbe5a5125ad98c5413fea4af755fc6f14207accf387001b60534e699` |
| tests/unit/test_unfinished_sessions.py (C00 승인 1행 대체) | `a648c008ad4a5b09451babcc4d8618a68cd3f9435877374fb3d8390f8ba8d838` |

이 문서의 최종 hash는 자기 참조를 피해 제출 보고와 R/implementation-files.json에 둔다. 정적 검사·전체 회귀 뒤에는 이 문서의 결과 기록만 바꿨다.

| 직접 증거(R 기준) | SHA256(LF, CR 제거) |
| --- | --- |
| new-five.xml | `9e4c1a30e7466030c1fac18c8d34a70fe8fa978f8544f0260de4f3b4c1482f55` |
| full.xml(R/iso) | `dc0edb34e20b61c44a11c9d26240668285f56c5a85e5ca4b7c2dbafdb9e3fb44` |
| final-full.xml(R/final, 판정) | `4e2a712b208d146111427f6d351c426d75aac8bd349f3c0497eff5cd19adf835` |
| mutations/results.json | `7b9fa7b4aaded3c5691c089635c925a54434cf861f62ebc22d66313188911e0c` |

### 11.7 남은 위험·독립 검토 인계

1. **삭제 기록이 늘수록 G-P04 경로의 root mutex 보유가 길어진다(G05 이전부터 있던 구조).** `_live`/`_admit_session`/`list_sessions`의 `_deletion_intents()`는 root mutex 아래에서 journal 전체를 읽는다. 완료 tombstone은 라이브러리 수명 동안 남으므로 삭제한 세션 수에 비례해 커진다. 400건 측정에서 시험 준비의 create_session·get_session 보유가 최대 2.6초, writer의 register_chunk도 길어졌다(관리 스레드는 1ms 미만). G05의 새 목록·retry는 버전 대조 선읽기로 이를 피했지만 기존 경로는 바꾸지 않았다. G-P15와 함께 캐시·선읽기 적용 여부를 C00이 정하기를 권한다.
2. 열린 writer가 있을 때 delete_session의 reason이 ACTIVE_READER_OR_WRITER → SESSION_LIVE로 바뀌었다. 이력 실패 메시지도 하나로 통일됐다(§10.3).
3. 실제 Windows 파일 잠김은 E4의 열린 읽기 handle 한 경우만 관측했다. 나머지 잠김은 시험 blocker이며 전원 장애·SSD 물리 소거·외부 사본 회수는 검증하지 않았다.
4. 세션 폴더가 junction 등으로 검사 불가이면 목록은 media_present=True(부재로 추정하지 않음)로 보고 retry는 MEDIA_REMOVAL_FAILED로 보류한다. 이 경로의 실제 NTFS junction 시험은 이번 3,166행에 없다.
5. journal 선읽기의 일관성은 같은 프로세스 협력 계약(이 Library만 journal을 씀)에 기대며 외부 임의 조작은 보장하지 않는다.
6. UI는 ‘확인 중’에도 표시한 (ID, g)로 retry를 허용한다. 세대가 바뀌었으면 StateConflict로 거부되고 재조회 결과를 보여 준다. 조회 실패 상태에서만 retry를 막는다.
7. 독립 검토자는 작성자의 로그를 복사하지 말고 §5 분모·§10.3 차이·§11.7 위험을 먼저 확인하기를 권한다. 특히 (a) 공유 진행부의 claim 획득 뒤 재확인과 tombstone 비강등, (b) 목록의 버전 대조 선읽기, (c) UI 늦은 결과·조회 실패 처리, (d) G04 대체 행의 SESSION_LIVE 근거를 별도 반례로 확인하기를 권한다.

## 12. G05R 검토 지적 수정(FIX1, 2026-11-23)

검토 문서 [G05R](../reviews/g05-pending-deletion-review.md)(LF `b49ac4582f3b84b1a06fac54e82543b6e58b281e453d4cb1f6ba0c720f23b741`, 검토 tree 32081c80 = 2933573 + 제출 10파일). C00 결정: G05R-01(S2)·G05R-03(S3)은 고친다. G05R-02(S1, 기존 결함: 완료 tombstone 증가 시 `_live`의 journal 전체 읽기)는 G-P15 '삭제 의도 색인'으로 넘기며 이번 수정은 그 경로(library.py)를 건드리지 않는다. N4·N5·N7은 같은 프로세스에서 도달할 수 없는 방어 코드로 결함이 아니다. 증거 루트 **R2=`C:/Users/gangd/AppData/Local/Temp/recoryn-g05fix-qz9BGOIn`**, 판정 사본 R2/iso = `git archive 2933573` + 승인 10파일(그 밖의 추적 파일 차이 0).

### 12.1 수정 계약

- **G05R-01 경고 우선순위.** 녹음 유실·저장 실패·장치 상태 경고는 `_tick`이 쓰는 alert로 기록하고, 삭제 대기 안내는 전용 영역 `deletion_status`에만 갱신한다. `_tick`과 백그라운드 목록 조회는 공용 `warning` 칸을 쓰지 않는다. 사용자가 직접 한 삭제·재시도의 결과만 `warning`에 알리되, 지금 그 칸이 녹음·장치 alert를 보여 주고 있으면 덮지 않는다(그때도 `deletion_status`에는 표시). 기존 같은 창 삭제 대기 문구·시험 동작은 유지한다. 쓰기만 하던 `_pending_observed`는 제거했다(관찰 O5).
- **G05R-03 시험 공백 4.** 동작 변경 없이 성질을 고정한다: 검사할 수 없는 세션 경로를 완료로 보지 않음(N6), 완료 tombstone을 보강 중에도 DELETE_PENDING으로 강등하지 않음(N1), UI 재시도가 항목마다 `stop_playback` 뒤 `before_delete`(세션 전송 철회·실행 취소)를 retry보다 먼저 부름(N3), CLI 명시 `--expected-generation`을 바꾸지 않고 전달함(N8).

### 12.2 추가 행(FIX1, 3,166과 별도 집계)

| ID | 파일 | 입력 | 독립 oracle |
| --- | --- | --- | --- |
| G05-FIX1-0000/0001 | unit | DELETED_LOCAL(g=2) + 더 새 journal(3) + 잔여 폴더 + 제거 잠김, retry / 초기 delete | MEDIA_REMOVAL_FAILED, DB `(3, DELETED_LOCAL)`·journal 3, 목록 db_status DELETED_LOCAL, 원본 hash 불변 |
| G05-FIX1-0002 | unit | 완료 tombstone 뒤 세션 경로 검사 실패 주입(`safe_path` ValidationError) | 목록 media_present=True·RETRY_REQUIRED, retry MEDIA_REMOVAL_FAILED, tombstone 유지, remover 호출 0 |
| G05-FIX1-0003 | unit(Windows) | 완료 tombstone 뒤 세션 경로가 실제 NTFS junction | 목록에 남음, retry 미완료, 외부 파일 hash 보존, junction만 제거 |
| G05-FIX1-0004/0005 | UI | 선택 재시도 1건 / 모두 재시도 2건 | 호출 순서 `stop_playback` → (`before_delete` a, retry a, `before_delete` b, retry b), consent DB의 세션 revoked=1 |
| G05-FIX1-0006 | UI | 재시작 뒤 복원된 대기 + 다른 세션 녹음 큐 포화(max_blocks=1), **실제 250ms timer 동작** + 백그라운드 조회 | 유실 경고가 표시된 뒤 `warning`은 끝까지 유실 경고뿐, `deletion_status`에 대기 1건 |
| G05-FIX1-0007 | UI | 복원된 대기 + 일회성 장치 경고, tick 3회·새로고침 | 장치 경고 유지, 대기 안내는 `deletion_status` |
| G05-FIX1-0008 | UI | 복원된 대기 + 장치 경고 표시 중 사용자 재시도(잠김) | 장치 경고 유지, 항목은 '원본 파일 제거 실패', `deletion_status` 대기 1건 |
| G05-FIX1-0009/0010 | CLI | job로 보류된 대기 + `--expected-generation` 일치 / g+1, in-process와 새 프로세스 각각 | 일치: exit 2·generation g 그대로, 불일치: exit 1·`STALE_DELETE_GENERATION`, 원본 불변 |

수정 전 재현: 이전 main.py(LF `7ea90216…675f`)를 얹은 사본에서 FIX1 UI 5행 중 경고 3행(0006~0008)이 실패했고 철회 2행은 통과했다(동작은 원래 맞았고 시험 공백이었음). 수정본에서는 모두 통과한다.

### 12.3 실행 결과

- 새 5파일: 첫 측정 391 passed in 98.11초(unit 4.28초/141, property 28.84초/6, integration 47.15초/137, UI 13.93초/68, CLI 3.13초/39). 아래 fixture 보강 뒤 최종 측정 **391 passed in 101.58초**(120초 예산 이내), failure/error/skip 0. `R2/new-five-b.xml` LF `a720e08040f444cb2cf8b0f482a2162ed99540940731ffa45b4011d1c398bed4`.
- case 감사(최종 측정 기준): 고정 분모 3,166 + FIX1 11 = **3,177 / 누락·추가·중복·skip 0**, case ID 없는 node 15(변동 없음).
- UI 전체 + desktop 독립: 464 passed(수정 직후, 시험 추가 전).
- mutation(`R2/run_mutations_fix1.py`, 변이마다 pyproject/src/tests/scripts/packaging 사본, import 위치 확인): **12/12 KILLED**, 전부 exit 1 assertion. 검토자 원문 패턴 N1→FIX1-0000, N3→FIX1-0004, N6→FIX1-0002, N8→FIX1-0010. 수정본 기준 G05R-01 되돌림 N9(대기 안내가 다시 `warning`을 덮음)→FIX1-0006, N9b(alert 표시 중 결과가 덮음)→FIX1-0008. main.py가 바뀌어 영향을 받는 기존 M15·M16·M17·M18·X3·X4도 재실행해 모두 같은 node에서 검출했다. 검토자 원래 N9(`_tick`의 재표시 제거)는 수정본에서 `_tick`이 경고 칸을 쓰지 않으므로 해당 코드가 없다. `R2/mutations/results.json` LF `cd0f47a7e57746fc67109ec131dfb7f4ed6370053c6ee0908d02347b72cc3b4b`.
- 정적 검사(R2/iso): ruff check 전체 PASS, 승인 Python 9파일 format PASS, mypy 84 source files PASS.
- 전체 오프라인 회귀 첫 실행(R2/iso, 2933573 + 10파일)은 **9890 passed, 48 errors / 669.19초**였다. 48건은 모두 CRASH 행의 module fixture setup error였고, 원인은 자식이 원자 게시한 marker를 부모가 읽을 때 Windows가 첫 open을 잠깐 거부한 `PermissionError`(새로 rename된 파일을 다른 프로세스가 검사하는 동안)였다. 제품 assertion 실패가 아니며 이전 3회 실행에서는 나지 않았다. 시험 fixture만 고쳤다: CRASH 자식의 marker rename과 부모의 marker 읽기, TRACE 자식의 결과 rename과 부모의 결과 읽기에서 그 `PermissionError`만 30초/fixture 기한 안에서 재시도한다(내용은 원자 게시라 부분 읽기는 없다). 이를 성공으로 덮지 않고 결과를 그대로 남긴다(`R2/full.log`).
- **전체 오프라인 회귀 재실행(판정): 9938 passed in 736.75초 / exit 0**, failure/error/skip 0, 경고 오류화. tests/ui 440, G-P04 4파일 428(GT-P03판 포함), G-P05 새 5파일 391. `R2/full2.xml` LF `cf7a8bf59b5bfee97c83b75f23a3387efa1810b42c149ba1e1424a2c0513e433`. 같은 실행의 관리 스레드 root 최대는 목록 400건 0.969ms·retry 10,800파일 3.081ms, ≥50ms 0건이다. retry 행에서는 녹음 writer 쪽 거부 61블록/유실 29,280프레임이 기록됐다(writer seal 보유, G-P15 범위로 측정만 함. 관리 스레드 보유는 상한 이내).

### 12.4 FIX1 제출 파일

이번에 바뀐 파일은 `ui/main.py`, 새 시험 5개 전부, 이 문서다. library.py·cli.py·test_unfinished_sessions.py는 §11.6 hash 그대로다.

| 파일 | SHA256(LF) |
| --- | --- |
| src/recoryn/ui/main.py | `b42fdd11c10183ce86424f8c0111a0a350b9344ad94fdbfdb580c72e8a9a28ee` |
| tests/unit/test_pending_deletions.py | `b1ee3e536b8b248026eda8c354e1d6a61184564e209a6edde3afd56e3b26a52a` |
| tests/ui/test_pending_deletion_ui.py | `899668bc0786c0ae49de097554173159d852c9186a426c7eff5f02c42e6a6dd3` |
| tests/e2e/test_cli_pending_deletions.py | `ad8fd045deebb716801248250ed91a69570c1478792ead33648a3de90547f2ce` |
| tests/integration/test_pending_deletion_restart.py | `a2752b02451ef343d8775eea11650f89ac703134cc2a985e1570635be620f7bc` |
| tests/property/test_pending_deletion_case_space.py | `f22dc8f7b1aa7defc7e83911dd300677fe77bb88696b496cb93a7a2f14ce1ac4` |

남은 범위: G05R-02는 G-P15에서 다룬다. 사용자 동작 결과는 녹음·장치 alert가 표시 중이면 `warning`에 쓰지 않으므로 그동안의 삭제 결과는 `deletion_status`와 목록 항목으로만 보인다. 실제 장치·전원 장애·다른 프로세스 reader 종료 증명은 여전히 미검증이다.
