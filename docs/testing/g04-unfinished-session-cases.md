# G04 / G-P04 미확정 세션 확정·재개: 경우의 수와 계약안

- 배정: G04 / push G-P04, 계약 단계. 작성자는 w5:p7 Claude, 독립 검토자는 w5:p8 Codex다.
- 상태: **IMPLEMENTATION_READY — C00 계약 승인(2026-11-23, §9) 뒤 구현했다. 독립 검토 전이다.** 구현 반영과 계약안과 달라진 점은 §10, 실행 결과는 §11에 있다.
- 기준: commit `0305306e256a39562244f63e42a627fc2e79bde9`. 정본은 [통합 계획](../implementation/v1-gap-plan.md)의 G-P04 행이다. 관련 근거:
  - [G01-A 보고서](../reviews/g01-gap-recording.md)의 G1A-11·G1A-62·G1A-24와 GF-01
  - [G01-A 교차 검토](../reviews/g01-gap-recording-review.md)의 G1A-11 확인과 경계 행
  - [G01-B 교차 검토](../reviews/g01-gap-ai-security-ui-review.md)의 G01BR-08·G01BR-21. F-RECUI01(복구 결과 표시)도 이 단위에 포함한다.
- 아래 행 번호는 모두 위 commit 기준이다.

## 1. 요구와 위험

- 설계 정본([architecture-v1](../architecture-v1.md) `:73`): "프로세스 종료·저장 중단은 `INTERRUPTED`, 복구 후 PAUSED 또는 FINALIZING. 재녹음은 명시적 사용자 동작과 새 epoch로만 시작."
- 복구 화면([architecture-v1](../architecture-v1.md) `:247`, `:251`): 보존된 범위, 누락·불확실 구간, 복구 후 가능한 다음 작업을 보여야 한다. 복구 검토·닫기는 키보드·Narrator 필수 흐름이고, Esc는 허용으로 동작하지 않는다.
- 탐지(G1A-62): 비정상 종료 세션을 탐지해 복구 대상으로 표시해야 한다.
- 위험 **S1**(통합 계획 `:25`): 비정상 종료나 저장 실패로 CREATED·RECORDING·PAUSED·FINALIZING·INTERRUPTED에 남은 세션을 사용자 경로(CLI·UI)로 확정할 수 없다. 원본은 남지만 내보내기·전사가 막힌다. 복구 결과는 `str(dict)`로만 보인다(표시 결함 자체는 S2).

## 2. 현재 동작

### 2.1 상태와 전이

- `SessionState`는 CREATED, RECORDING, PAUSED, FINALIZING, FINALIZED, INTERRUPTED 6개다(`domain/__init__.py:189-195`).
- 전이표(`domain/__init__.py:211-222`)는 이미 다음을 허용한다.
  - CREATED·PAUSED·INTERRUPTED → FINALIZING
  - INTERRUPTED → PAUSED
  - FINALIZING → FINALIZED만 `finalize_session`으로 간다(`storage/library.py:223-224`, `:363-395`).
- DELETE_PENDING은 `SessionState`가 아니다. 삭제 의도(journal·`deleted_sessions`)로 표현된다.
  - `list_sessions`는 삭제 의도를 숨긴다(`library.py:203-212`).
  - `recover_session`은 이때 의사 상태 `"DELETE_PENDING"`을 돌려준다(`:464-473`).
- DB 행 없이 `sessions/<id>/` 폴더만 있는 세션(이하 DIRECTORY_ONLY)은 `list_sessions`에 보이지 않는다. `recover_session`이 CREATED 행을 만들어 채택한다(`:476-482`).

### 2.2 복구

- `recover_session`(`library.py:461-547`)이 하는 일:
  - catalog 밖의 검증된 bundle을 채택한다.
  - staging의 검증된 prefix를 새 ID(`recovered-…`)로 복사·등록한다(`_salvage`, `:416-459`). staging 자체는 바꾸지 않는다.
  - 상태 전환: RECORDING·FINALIZING → INTERRUPTED(`:533-536`). CREATED·PAUSED·INTERRUPTED·FINALIZED는 그대로 둔다.
  - FINALIZED 세션의 catalog 밖 bundle·staging은 채택하지 않는다. 결과에는 "quarantined"로 세지만 파일을 옮기지는 않는다(`:501-504`, `:519-522`).
- 살아 있는 writer는 `has_active_writer`(`chunks.py:43-47`, 같은 프로세스 registry)로만 거부한다(`library.py:474-475`). 이 registry에는 chunk writer가 열려 있는 동안만 올라간다. writer는 첫 블록에 열리고, seal 뒤 다음 블록 전까지는 닫혀 있다(`app/recording.py:180-192`).
- 다른 프로세스는 Library 잠금(`.writer.lock`, `library.py:104-125`)으로 막힌다.

### 2.3 사용자 경로

| 경로 | 현재 | 근거 |
| --- | --- | --- |
| `RecordingService` | 생성자가 항상 새 세션을 만든다. `stop`은 CREATED·RECORDING·PAUSED만 받는다 | `app/recording.py:57`, `:256-257` |
| `DesktopRecorder` | 새 세션 시작만 있다. close는 CREATED·RECORDING·PAUSED만 stop으로 확정하고, INTERRUPTED는 source 종료·writer join만 한다 | `app/desktop.py:67-91`, `:216-222` |
| CLI | `inspect`·`recover`·`export`·`delete`·`list`. 확정 명령이 없다. export는 FINALIZED만 받는다 | `cli.py:47-51`, `:116-122`, `:290-291` |
| UI | "복구 검토"는 `recover_session` 결과를 `str(result)`로 보이고 경고 한 줄을 띄운다. 확정 동작이 없다. 시작 시 탐지가 없다 | `ui/main.py:166`, `:406-418`, `:378-386` |
| 전사 | 비임시 전사는 FINALIZED를 요구한다. 청크가 0개면 `TRANSCRIPTION_AUDIO_EMPTY`로 거부한다 | `app/ai.py:190-199` |

### 2.4 이번 계약 단계에서 새로 찾은 반례 G04-CE1(S2)

- 내용: 같은 프로세스의 녹음이 진행 중일 때 chunk writer가 없는 순간에 `recover_session`을 부르면, 살아 있는 녹음이 INTERRUPTED가 된다. 이후 결과:
  - 블록은 계속 수락·등록된다.
  - `stop`은 `STOP_REQUIRES_ACTIVE_SESSION`으로 거부된다.
  - 세션은 사용자 경로로 확정할 수 없는 INTERRUPTED에 남는다.
- UI 재현 경로: "복구 검토" 버튼은 녹음 중에도 눌린다. `operation`은 busy일 때만 막기 때문이다(`ui/main.py:258-262`).
- probe(OS TEMP, 장치·모델 없음): `C:\Users\gangd\AppData\Local\Temp\claude\e47d15555ed7cfa9\d9354f5a-75d0-44dc-8069-db32589569d1\scratchpad\g04probe\probe_live_recover.py`
- 실행 결과:

  ```json
  {"before": "RECORDING", "accepting_before": true, "recover_state": "INTERRUPTED", "accepting_after_recover": true, "submit_after_recover": true, "stop": "STOP_REQUIRES_ACTIVE_SESSION", "final_state": "INTERRUPTED", "chunks": 1}
  ```

- 원본은 보존된다. 하지만 사용자가 녹음 중 복구 검토를 누르면 녹음이 정상 정지할 수 없게 된다. 계약 §3.2의 live 보유자 검사로 닫는다.

## 3. 계약안(승인 요청)

### 3.1 Library 공개 API

모든 신규 인자는 keyword-only다. 기존 메서드의 기존 인자·반환 키는 바꾸지 않는다.

```python
class LiveOwner(Protocol):
    def is_live(self) -> bool: ...

def register_live_owner(self, session_id: str, owner: LiveOwner) -> None:
    """Weakly remember the in-process owner of a session. A dead reference is not live."""

def unfinished_sessions(self) -> list[dict[str, Any]]:
    """Read-only inventory of sessions a user may need to finalize."""

def finalize_unfinished(self, session_id: str, *, expected_version: int | None = None) -> dict[str, Any]:
    """Recover, then seal an unfinished session; idempotent for FINALIZED."""
```

**`unfinished_sessions()`**
- 읽기 전용이다. DB·파일·`storage_events`에 쓰지 않고, DIRECTORY_ONLY에 행을 만들지 않는다.
- 각 항목의 키:
  - `session_id`
  - `state`: CREATED / RECORDING / PAUSED / FINALIZING / INTERRUPTED / DIRECTORY_ONLY
  - `state_version`: DIRECTORY_ONLY면 `None`
  - `live`: bool
  - `catalog_chunks`
  - `staging_entries`
  - `uncatalogued_bundles`
- 제외: FINALIZED, 삭제 의도(DELETE_PENDING·DELETED_LOCAL tombstone).
  - **삭제 대기 목록은 G-P05 범위**라서 이 API에 넣지 않는다.
- 이름이 identifier 규칙에 맞지 않는 폴더는 건너뛰고 따로 센다. 이 개수는 반환 dict와 구분된 `inventory_warnings`로 돌려준다. 정확한 형태는 구현 때 정하고 검토로 고정한다.
- 삭제 기록이 없거나 손상되면 `list_sessions`와 같게 `ValidationError`로 실패한다(fail closed).

**`finalize_unfinished(session_id, *, expected_version=None)`**

한 번의 `root_mutex` 구간에서 아래 순서로 처리한다.

1. **거부 검사**(이 순서로 확인하고, 상태와 파일은 바꾸지 않는다)
   - 삭제 의도가 있으면 `StateConflict("DELETE_PENDING")`
   - 살아 있는 보유자나 writer가 있으면 `StateConflict("SESSION_LIVE")`
   - DB 행도 폴더도 없으면 `KeyError`
2. **이미 FINALIZED면** 복구 보고만 만들고 `already_finalized=True`로 돌려준다.
   - `state_version`·`finalized_chunks`·FINALIZED 사건은 바꾸지 않는다.
   - `expected_version`은 비교하지 않는다. 결과가 사용자의 의도와 같기 때문이다.
3. **버전 비교:** `expected_version`이 주어졌는데 복구 전 `state_version`과 다르면 `StateConflict("STALE_SESSION_VERSION")`.
4. **복구:** `recover_session`을 실행한다. staging을 살리고 고아 bundle을 채택한다. RECORDING·FINALIZING은 INTERRUPTED가 된다.
5. **확정:** CREATED·PAUSED·INTERRUPTED면 FINALIZING으로 전이한 뒤 `finalize_session`을 호출한다. FINALIZING이면 4단계에서 INTERRUPTED가 됐으므로 같은 경로를 탄다.
6. **반환 dict 키:** `session_id`, `state="FINALIZED"`, `already_finalized`, `previous_state`, `recovery`(4단계 보고), `chunk_count`, `frame_count`, `manifest_sync_pending`.

부분 실패는 다음과 같이 처리한다.
- 4단계 뒤 5단계가 실패하면 상태는 INTERRUPTED나 FINALIZING에 남고 예외가 올라간다. 확정됐다고 보고하지 않는다(G1A-24와 같다). 다시 호출하면 이어서 진행한다.
- manifest 쓰기만 실패하면 기존 `finalize_session`처럼 FINALIZED와 `manifest_sync_pending=True`를 돌려준다.

**`recover_session` 변경(추가만)**
- live 보유자가 있으면 `StateConflict("SESSION_LIVE")`로 거부한다. G04-CE1을 닫는 변경이다.
  - 기존 `has_active_writer` 거부는 메시지를 포함해 그대로 둔다.
- 반환 dict에 키 두 개를 추가한다. 기존 키와 그 의미, 개수 세는 법은 바꾸지 않는다.
  - `previous_state`: 복구 전 상태
  - `details`: 항목별 목록. 각 항목은 `kind`(bundle/staging), `source`(디렉터리 이름), `status`, `chunk_id`(있을 때), `frames`, `tail_bytes`(staging에서 채택하지 않은 바이트 수)를 가진다.
- `status` 닫힌 집합: `ADOPTED`, `RECOVERED`, `TAIL_NOT_ADOPTED`, `INVALID`, `CANDIDATE_NOT_ADOPTED`, `ALREADY_RECOVERED`.
  - `ALREADY_RECOVERED`는 FINALIZED 세션의 staging 중 같은 복구 ID의 chunk가 이미 확정 목록에 있는 경우다. staging을 읽기만 해서 판정한다.
  - 지금은 이런 staging도 매번 "quarantined"로 세서, 확정 뒤 재복구가 격리처럼 보인다. 기존 개수는 유지하고 표시만 바로잡는다.

**live 판정**
- 아래 둘 중 하나면 live다.
  - `has_active_writer`
  - 등록된 보유자의 `is_live()`가 참
- `RecordingService.is_live()`는 `self._accepting`(입력 수락 중)이거나 writer thread가 살아 있을 때 참이다.
- 저장 실패로 INTERRUPTED가 되고 writer가 끝난 서비스는 live가 아니다. 그래서 기존 `tests/integration/test_app_service.py::test_threshold_seal_failure_releases_writer_and_preserves_prefix`가 `join_writer` 전에 복구하는 흐름이 그대로 통과한다.
- 다른 프로세스는 Library 잠금이 막으므로 파일 잠금을 따로 두지 않는다.

### 3.2 RecordingService·DesktopRecorder

- **`RecordingService`(`app/recording.py`):**
  - `create_session` 직후 `library.register_live_owner(session_id, self)`를 호출한다(약한 참조).
  - 위 정의의 `is_live()`를 더한다. 그 밖의 동작은 바꾸지 않는다.
- **`DesktopRecorder`(`app/desktop.py`):** **이 단위에서 바꾸지 않을 것으로 예상한다.**
  - 현재 세션이 저장 실패로 INTERRUPTED일 때 UI가 확정하려면, 삭제 흐름(`ui/main.py:454-458`)처럼 먼저 `recorder.close()`(source ack, writer join) 후 `recording=None`으로 정리하고 확정한다.
  - 재개를 이 단위에 넣으면(§9 결정 1의 대안 B) 이 파일도 쓰기 범위에 들어간다.
- **재개(기존 세션 attach와 새 epoch): 이 단위에서 제외할 것을 권장한다(§9 결정 1).** 이유:
  1. `app/media.py:110-122`는 세션 전체 `capture_mono_ns`의 최솟값 하나를 공통 origin으로 써서 epoch 사이를 뺀다. 다른 프로세스·재부팅의 monotonic 시계는 서로 무관하다. 그래서 재개한 세션의 전사·화자 구분·clip 시각이 조용히 틀어진다. 이는 GF-06(clock domain, G1A-39)의 범위다.
  2. `_drain`은 `capture_health`를 이번 서비스의 기록(`{"epochs": self._history}`, `app/recording.py:227`)으로 덮어쓴다. `DesktopRecorder._persist_backend_health`도 이번 실행의 `backend_events`로 덮어쓴다(`app/desktop.py:180-186`). attach하면서 이전 기록을 합치지 않으면 첫 drain에서 이전 실행의 건강 정보가 사라진다.
  3. S1의 원인(내보내기·전사 차단)은 확정 경로만으로 닫힌다. 설계는 "PAUSED **또는** FINALIZING"이다. 재개는 PARTIAL로 남기고 GF-06과 한 단위로 다룬다.
- 같은 프로세스 안의 일시정지·재개(PAUSED live)는 지금 그대로 동작한다.

### 3.3 CLI(`cli.py`)

| 명령 | 출력(JSON 한 줄) | 종료 코드 |
| --- | --- | --- |
| `recoryn finalize <session_id>` | `finalize_unfinished` 반환 dict(`recovery` 포함, 경로 없음) | 성공 0. 이미 FINALIZED여도 0이고 `already_finalized: true` |
| `recoryn list --unfinished` | `unfinished_sessions()` 목록 | 0 |
| 위 두 명령의 거부·오류 | `{"error": <예외 타입>, "code": <닫힌 코드>, "message": "Operation failed; media preserved"}` | 1 |

- 닫힌 코드: `SESSION_LIVE`, `DELETE_PENDING`, `STALE_SESSION_VERSION`, `NOT_FOUND`, `STATE_CONFLICT`(그 밖의 상태 충돌), `STORAGE_ERROR`(OSError·sqlite3.Error·ValidationError).
  - 예외 메시지 원문은 출력하지 않는다(`cli.py:305-308`의 원칙 유지).
- `code` 키는 이 두 명령에만 붙인다. 기존 명령의 출력은 바꾸지 않는다.
- `recover`·`export`·`inspect`·`list`(옵션 없음)·`delete`의 동작과 출력은 그대로다.
  - `recover` 결과에는 §3.1의 추가 키 두 개가 함께 나온다.
  - export는 계속 FINALIZED만 받는다. 확정 전 내보내기 거부는 회귀 행으로 둔다.
- 기각한 대안: `recover --finalize`. 복구(검증된 데이터 채택)와 확정(이후 추가 녹음 불가, 되돌릴 수 없음)은 의미가 다르므로 동사를 분리한다. `finalize`는 내부에서 복구를 먼저 실행한다.

### 3.4 UI(`ui/main.py`, F-RECUI01)

**시작 시 탐지(G1A-62)**
- `refresh_sessions` 안에서 `unfinished_sessions()`를 동기로 읽는다. DB 질의와 `sessions/` 한 단계 나열뿐이다.
- 새 라벨 `recovery_status`(접근 이름 "미확정 세션 안내")에 다음을 표시한다: "이전 실행에서 확정되지 않은 세션 N건이 있습니다. 목록에서 선택해 ‘복구 검토’ 또는 ‘세션 확정’을 고르세요. 자동으로 바꾸지 않습니다."
  - live 항목은 세지 않는다.
- 자동 복구·자동 확정은 하지 않는다.
- 기존 `warning` 라벨 문구와 busy 상태는 건드리지 않는다. 시작 때 operation을 띄우면 busy가 되어 직후의 사용자 동작을 막기 때문이다(`ui/main.py:261-262`).

**목록**
- 미확정 항목에는 상태 코드와 함께 "미확정"을 붙인다. 예: `INTERRUPTED · 미확정  ab12…`
- DIRECTORY_ONLY 항목은 DB 세션 뒤에 `폴더만 있음 · 복구 필요  ab12…`로 덧붙인다. 기존 시험의 `setCurrentRow(0)`가 가리키는 첫 행은 바뀌지 않는다.
- DIRECTORY_ONLY를 선택하면 `get_session`의 KeyError 없이 inventory 정보만 보인다. AI 패널 선택(`ai_bridge.selection`)은 부르지 않는다.

**복구 검토**
- 결과를 `str(dict)`가 아니라 새 read model(§3.5)로 구조화해 보여 준다.
  - 복구 전후 상태
  - 보존 범위: 트랙·epoch별 청크 수와 시간
  - 이번 복구: 채택·복원·격리 수
  - 누락·불확실: 채택하지 않은 끝부분 바이트, 손상 항목, catalog에는 있는데 파일이 없는 청크, 건강 기록이 없는 epoch(유실 누계 "알 수 없음")
  - 후보: 확정 목록 밖에 보존된 것
  - 다음 행동
  - 마지막 줄: "중단·누락 구간은 복원되지 않습니다."
- `SESSION_LIVE` 거부는 "녹음 중인 세션은 정지 후 복구할 수 있습니다"로 보인다.

**세션 확정**
- 새 버튼이다(접근 이름 "선택한 미확정 세션을 확정").
- 사용 가능 조건: busy가 아니고, 선택 항목이 미확정(DIRECTORY_ONLY 포함)이며, live가 아니다. 현재 녹음기 세션이면 INTERRUPTED일 때만 가능하다. 현재 녹음기의 PAUSED는 기존 "정지"를 쓴다.
- 누르면 확인 대화상자를 띄운다. 기본값은 "아니요"이고, Esc는 "아니요"다.
  - 문구: "확정하면 이 세션에 더 녹음할 수 없습니다. 검증되지 않은 끝부분과 중단 구간은 복원되지 않습니다. 확정할까요?"
- 승인하면 operation으로 `finalize_unfinished(session_id, expected_version=<표시한 버전>)`을 호출한다.
  - 현재 녹음기의 INTERRUPTED 세션이면 먼저 `recorder.close()` 후 `recording=None`으로 정리한다.
- 완료되면 구조화한 결과와 다음 행동(내보내기·전사 가능)을 보이고 목록을 새로 고친다.
- `STALE_SESSION_VERSION`이면 목록을 새로 고치고 다시 확인하라고 안내한다.

**접근성**
- 대화상자를 닫으면 초점이 목록으로 돌아간다.
- 결과 텍스트는 기존 `details`(읽기 전용 QPlainTextEdit)에 줄 단위로 넣어 Narrator가 읽을 수 있게 한다.
- 실제 Narrator 판독은 외부 게이트(E02)로 남긴다.

**바꾸지 않는 것**
- `ui/ai_bridge.py`·`ui/privacy.py`(G-P02), 삭제 대기 표시(G-P05)는 바꾸지 않는다.

### 3.5 read model(신규 `src/recoryn/app/recovery.py`)

Qt 없는 순수 함수다. UI가 이를 쓰고, 단위 시험이 직접 검사한다.
- `describe(code) -> (category, label)`
  - 경고 코드를 닫힌 표로 분류한다. 분류는 보존·누락·후보·불명·정보다.
  - 모르는 코드는 "불명"으로 둔다. 원문 코드도 함께 보인다.
- `recovery_view(result, chunks, health) -> RecoveryView`
  - 보존 범위를 계산한다.
  - `capture_health["epochs"]`에 없는 epoch는 유실 누계를 0이 아니라 "알 수 없음"으로 둔다. 비정상 종료 실행은 drain 때만 쓰는 건강 기록을 남기지 못하기 때문이다(GF-05 범위).
- `next_actions(state, *, live) -> tuple[str, ...]`: 상태별 다음 행동을 닫힌 표로 돌려준다(§4.3).
- 새 파일을 두는 이유:
  - `ui/main.py`에 두면 offscreen Qt 없이 시험할 수 없다.
  - `app/desktop.py`는 녹음 제어 책임이라 섞지 않는다.

### 3.6 상태 전이 표 변경과 기존 호출자 영향

- **전이표(`domain/__init__.py:211-222`)는 바꾸지 않는다.** 필요한 전이(CREATED·PAUSED·INTERRUPTED → FINALIZING → FINALIZED)가 이미 있다. 새 `SessionState` 값(예: RECOVERED)도 만들지 않는다.

| 호출자 | 영향 |
| --- | --- |
| `RecordingService` 사용처 전부(앱·시험·CLI simulate) | 생성 시 live 보유자를 등록하는 것 말고는 바뀌지 않는다 |
| `recover_session` 호출자(CLI `recover`, UI 복구 검토, 시험) | live 보유자가 있을 때만 새 거부. 반환 dict에 키 2개 추가. 기존 시험 중 반환 dict 전체를 비교하는 곳은 없다(`grep` 확인, `test_storage.py:325`는 `warnings` 키만 비교) |
| `tests/unit/test_storage.py::test_recovery_prefix_is_new_id_and_repeat_is_idempotent` | 복구 뒤 INTERRUPTED를 기대한다. `recover_session`의 상태 의미를 바꾸지 않으므로 그대로 통과해야 한다. 확정은 별도 API다 |
| `tests/integration/test_app_service.py::test_threshold_seal_failure_releases_writer_and_preserves_prefix`, `tests/e2e/test_recording_control.py::test_rotation_failure_releases_writer_for_prefix_recovery` | 저장 실패 뒤 서비스가 live가 아니므로 그대로 통과해야 한다 |
| `ui/main.py` 기존 시험(`setCurrentRow(0)`, `warning` 문구 검사) | 목록 첫 행과 `warning` 문구가 바뀌지 않게 설계했다. 회귀로 확인한다 |
| `content/store.py`·`app/ai.py`(G-P03), `ui/ai_bridge.py`·`ui/privacy.py`(G-P02) | 쓰지 않는다. 전사 수락 행은 `app/ai.py`를 읽기만 하는 시험으로 확인한다 |

### 3.7 쓰기 범위(구현 단계 예정)

| 파일 | 변경 |
| --- | --- |
| `src/recoryn/storage/library.py` | `register_live_owner`, `unfinished_sessions`, `finalize_unfinished`, `recover_session`의 live 거부와 키 2개 추가 |
| `src/recoryn/app/recording.py` | live 보유자 등록, `is_live()` |
| `src/recoryn/app/recovery.py`(신규) | read model |
| `src/recoryn/cli.py` | `finalize`, `list --unfinished`, 두 명령의 닫힌 오류 코드 |
| `src/recoryn/ui/main.py` | 시작 탐지 라벨, 목록 표시, 구조화한 복구 결과, 세션 확정 버튼·확인 대화상자, 사용 가능 조건 |
| `tests/unit/test_unfinished_sessions.py`(신규) | 상태×동작 표, 상태열 모델, 값 검증, read model |
| `tests/integration/test_unfinished_recovery.py`(신규) | 원인별 kill·실패 → 복구 → 확정 → 내보내기, 경쟁 순서 |
| `tests/e2e/test_cli_finalize.py`(신규) | CLI 전체 흐름 |
| `tests/ui/test_recovery_ui.py`(신규) | UI 행 |
| `docs/testing/g04-unfinished-session-cases.md` | 이 문서(결과 갱신) |

- 쓰지 않는 파일: `app/desktop.py`(재개 제외 시), `domain/__init__.py`, `content/store.py`, `app/ai.py`, `ui/ai_bridge.py`, `ui/privacy.py`.
- 기존 시험 파일은 수정하지 않는다. `test_process_crash.py`의 자식 프로세스 helper는 import하지 않고 새 파일에 작게 다시 쓴다. 시험 모듈 사이 import는 `--import-mode=importlib`에서 불안정하기 때문이다.

### 3.8 대안과 기각 사유

1. **재개를 이번에 포함(§9 결정 1의 대안 B):** attach 때 `capture_health`의 이전 `epochs`·`backend_events`·`native_formats`를 합치고, 실행 경계를 기록해 media가 실행을 넘는 차감을 거부하게 한다. 사실상 GF-06의 일부를 끌어오는 것이고 `app/desktop.py`·`app/media.py`까지 범위가 커진다.
2. **시작 시 자동 복구·자동 확정:** 확정은 되돌릴 수 없고, 탐지는 표시만 요구된다. 그래서 기각했다.
3. **항목별 채택·격리 선택 UI:** 채택은 검증된 데이터의 append-only 등록이라 원본을 바꾸지 않는다. 격리는 지금도 "제자리에 둠"이다. 선택지가 보존을 늘리지 않으므로 기각했다. 후보는 표시만 한다.
4. **세션별 파일 잠금으로 live 판정:** 프로세스 사이는 이미 Library 잠금이 배타적이다. 프로세스 안 registry로 충분하다.
5. **확정 뒤 staging 정리:** 채택하지 않은 끝부분 바이트는 staging에만 있다. 정리는 보존 정책(G-P14) 범위다. 이 단위는 남기고 보고만 한다.
6. **DIRECTORY_ONLY 삭제 지원:** 지금 `delete_session`은 행이 없으면 NOT_FOUND를 돌려주고 폴더를 지우지 않는다(`library.py:556-557`). 삭제 의미를 바꾸는 일이므로 이 단위에 넣지 않는다. UI는 "복구 후 삭제"로 안내한다(§9 결정 5).

## 4. 경우의 수

### 4.1 차원과 동치류

| 차원 | 동치류 | 크기 |
| --- | --- | ---: |
| S: 동작 시점 세션 상태 | CREATED(이전 실행) / RECORDING(이전 실행) / RECORDING(live) / PAUSED(이전 실행) / PAUSED(같은 프로세스, live 아님) / FINALIZING(이전 실행) / INTERRUPTED(이전 실행) / INTERRUPTED(같은 프로세스 저장 실패, live 아님) / FINALIZED / DELETE_PENDING / DIRECTORY_ONLY / NOT_FOUND | 12 |
| A: 동작 | 확정 / 재개 / 내보내기 / 전사 요청(비임시) / 삭제 / 재복구 | 6 |
| K: 원인(통합) | 프로세스 kill 8(K1~K8) / 저장 실패 4(F1~F4) / 장치 시작 실패 2(D1~D2) | 14 |
| V: 값 | session_id 6 / expected_version 7 | 13 |

### 4.2 분모

| 집합 | 정의 | 분모 |
| --- | --- | ---: |
| T 상태×동작 | S×A 전수. 거부해야 하는 행을 빼지 않는다 | 72 |
| I inventory | S 각 상태가 `unfinished_sessions`에 나오는지·`live` 표시 | 12 |
| K 원인 사슬 | 각 원인 → 재복구 → 확정 → 재확정 → 내보내기 → 재복구. O1~O7을 한 행에서 모두 확인 | 14 |
| Q 상태열 | 시작 상태 {CREATED, RECORDING, PAUSED, FINALIZING, INTERRUPTED}(모두 이전 실행) × {재복구, 확정, 내보내기}의 길이 1~3 명령열(3+9+27=39) | 195 |
| H 경쟁 | §4.5 | 10 |
| V 값 검증 | session_id {정상, "", "../x", NUL 포함, 256자 초과, 문자열 아님} + expected_version {None, −1, 현재, 현재+1, 현재−1, True, 1.0} | 13 |
| R read model | 경고 코드 9(INVALID_BUNDLE, INVALID_STAGING, STAGING_TAIL_NOT_ADOPTED, MISSING_OR_INVALID_CATALOG_MEDIA:<id>, FINALIZED_ORPHAN, FINALIZED_STAGING, MANIFEST_SYNC_PENDING, DELETION_INTENT, 모르는 코드) + 건강 기록 유무 2 + 다음 행동 12 | 23 |
| U UI | U1 시작 탐지, U2 구조화 표시, U3 버튼 사용 가능 조건 10, U4 확인 대화상자 2(기본값, Esc), U5 확정 뒤 내보내기, U6 DIRECTORY_ONLY 선택, U7 live 복구 거부 | 17 |
| C CLI e2e | C1 `list --unfinished`, C2 `finalize` 2회(성공·이미 확정), C3 거부 2(DELETE_PENDING, NOT_FOUND), C4 자식 kill → `recover` → `finalize` → `export` | 5 |
| **합계** | | **361** |

- S×A×K의 형식상 곱은 12×6×14 = 1008이지만, K는 특정 시작 상태·중단 지점으로 정의한 원인 사슬이다. 이 곱을 실행 가능한 조합 F라고 확정하지 않는다. T의 상태×동작72와 K의 원인 사슬14는 서로 다른 가족이며 같은 3축 tuple 집합의 부분집합으로 정의하지 않았다.
- **S×A×K 전수는 하지 않았고 원인별 상태·동작의 교차 coverage는 계수하지 않았다.** 1008에서 서로 다른 가족72·14를 빼 누락 조합 수로 쓰지 않는다. 선언 가족의 합361과 실행 node365(별도 manifest4 포함)는 유지한다. 원인 무관 가정과 구성 불가능/실행 생략은 독립 검토의 한계다.
- U3 사용 가능 조건 10행: 다른 세션 7개(CREATED, RECORDING 이전 실행, PAUSED 이전 실행, FINALIZING, INTERRUPTED, FINALIZED, DIRECTORY_ONLY) + 현재 녹음기 세션 3개(RECORDING live, PAUSED live, INTERRUPTED live 아님). 기대값은 각각 사용 가능, 사용 가능, 사용 가능, 사용 가능, 사용 가능, 불가, 사용 가능 / 불가, 불가, 사용 가능이다.

### 4.3 T 상태×동작 기대 결과(손으로 쓴 표)

약어: 허용 → 결과 상태, 거부 → 코드(상태·파일 불변).

| S \ A | 확정 | 재개 | 내보내기 | 전사 요청 | 삭제 | 재복구 |
| --- | --- | --- | --- | --- | --- | --- |
| CREATED(이전) | 허용 → FINALIZED. 청크 0개 허용(기존 stop과 같다) | 경로 없음 | 거부: 미확정 | 거부: `TRANSCRIPTION_REQUIRES_FINALIZED_AUDIO` | 기존대로 DELETED_LOCAL | 허용, CREATED 유지, 채택 |
| RECORDING(이전) | 허용 → 복구로 INTERRUPTED → FINALIZED | 경로 없음 | 거부 | 거부 | 기존대로 | 허용 → INTERRUPTED. 두 번째부터 불변 |
| RECORDING(live) | **거부 `SESSION_LIVE`** | 기존 규칙: `RESUME_REQUIRES_PAUSED` | 거부 | 거부 | 기존대로(UI는 녹음기 close 뒤 삭제) | **거부 `SESSION_LIVE`**(G04-CE1) |
| PAUSED(이전) | 허용 → FINALIZED | 경로 없음 | 거부 | 거부 | 기존대로 | 허용, PAUSED 유지 |
| PAUSED(같은 프로세스) | API 허용 → FINALIZED(정지와 같은 결과). UI 버튼은 불가, "정지" 사용 | 기존 재개 허용(새 epoch) | 거부 | 거부 | 기존대로 | 허용, PAUSED 유지 |
| FINALIZING(이전) | 허용 → INTERRUPTED → FINALIZED | 경로 없음 | 거부 | 거부 | 기존대로 | 허용 → INTERRUPTED |
| INTERRUPTED(이전) | 허용 → FINALIZED | 경로 없음 | 거부 | 거부 | 기존대로 | 허용, 불변 |
| INTERRUPTED(같은 프로세스) | 허용 → FINALIZED(UI는 녹음기 close 먼저) | 현재 녹음기의 `resume`도 기존 규칙으로 거부: `RESUME_REQUIRES_PAUSED` | 거부 | 거부 | 기존대로 | 허용, 불변 |
| FINALIZED | 허용, **no-op** `already_finalized=True`, 사건·버전 불변 | 경로 없음 | 허용, 완료 표식 `export.json` | 청크 ≥1이면 수락. 0이면 `TRANSCRIPTION_AUDIO_EMPTY` | 기존대로 | 허용, 상태·목록 불변, 후보만 보고 |
| DELETE_PENDING | **거부 `DELETE_PENDING`** | 경로 없음 | 거부(삭제 의도) | 거부(삭제 의도) | 기존 재시도 | 허용, 의사 상태 DELETE_PENDING 반환(기존) |
| DIRECTORY_ONLY | 허용 → CREATED 행 생성·채택 → FINALIZED | 경로 없음 | 거부: `KeyError` | 거부: `KeyError` | **기존: NOT_FOUND, 폴더 유지**(§3.8 6번) | 허용 → CREATED 행 생성 |
| NOT_FOUND | 거부 `KeyError`(CLI `NOT_FOUND`) | 경로 없음 | 거부 | 거부 | 기존: NOT_FOUND | 거부 `KeyError` |

- "경로 없음"(구현 반영): 기존 세션에 붙어 재개하는 사용자 경로가 없다는 뜻이다.
  - 시험은 CLI에 `resume` 하위 명령이 없음(argparse 종료 코드 2)과 상태·파일 불변으로 확인한다.
  - UI의 일시정지/재개 버튼은 원래부터 현재 녹음기 세션에만 작동한다(`ui/main.py`의 `pause_resume`). 이 단위는 그 버튼을 바꾸지 않았다.
  - 재개는 C00 결정 1에 따라 GF-06과 한 단위로 다룬다.
- "기존대로" 삭제 행은 G-P05 경계라서, 지금 동작을 회귀 oracle로 고정만 한다.
- **I inventory 기대값:**
  - 나옴: CREATED, RECORDING(이전), PAUSED(이전), FINALIZING, INTERRUPTED(두 종류), DIRECTORY_ONLY
  - 나오되 `live=True`: RECORDING(live)
  - 나오되 `live=False`: PAUSED(같은 프로세스). UI 탐지 라벨은 현재 녹음기 세션을 세지 않는다.
  - 안 나옴: FINALIZED, DELETE_PENDING, NOT_FOUND
  - 위 판정은 구현의 전이표를 import하지 않고 이 표 literal로 둔다.
- **R 다음 행동 기대값**(`next_actions`):
  - 미확정이고 live 아님: (복구 검토, 세션 확정, 세션 삭제)
  - live: (정지 후 가능)
  - FINALIZED: (내보내기, 전사 요청, 세션 삭제)
  - DIRECTORY_ONLY: (복구 검토, 세션 확정)
  - DELETE_PENDING: (삭제 대기 재시도). 재시도 목록과 UI는 G-P05 범위다
  - NOT_FOUND: ()

### 4.4 K 원인 사슬

| ID | 원인 | 사슬 시작 상태 | 손계산 보존 프레임 |
| --- | --- | --- | --- |
| K1 | payload fsync 3회 뒤 kill(기존 phase) | RECORDING | 8 |
| K2 | journal fsync 3회 뒤 kill(기존 phase) | RECORDING | 12 |
| K3 | bundle 게시 뒤, catalog 전 kill(기존 phase) | RECORDING | 12 |
| K4 | catalog commit 뒤 kill(기존 phase) | RECORDING | 12 |
| K5 | 정지 경로에서 FINALIZING commit 뒤, 확정 commit 전 kill | FINALIZING | 12 |
| K6 | 확정 DB commit 뒤, manifest 쓰기 전 kill | FINALIZED + `manifest_sync_pending=1` | 12 |
| K7 | `finalize_unfinished`의 복구 단계에서 `recovery-work` 쓰는 중 kill | RECORDING(복구 전) | 12 |
| K8 | `finalize_unfinished`가 FINALIZING으로 전이한 뒤, 확정 commit 전 kill | FINALIZING | 12 |
| F1 | append 중 ENOSPC(저장 실패, 같은 프로세스) | INTERRUPTED | 실패 전까지 fsync된 블록 |
| F2 | rotation seal 실패 | INTERRUPTED | 기존 시험과 같은 값 |
| F3 | drain 때 건강 기록 실패 | INTERRUPTED | 수락·seal된 블록 |
| F4 | 확정 SQLite COMMIT 거부 | FINALIZING | 전부 |
| D1 | 첫 장치 시작 실패 → PAUSED(G1A-22 결정), 그 뒤 kill | PAUSED, 청크 0 | 0 |
| D2 | 두 번째 장치 시작 실패, 첫 트랙 블록 수락 뒤 → PAUSED, 그 뒤 kill | PAUSED | 첫 트랙의 수락 블록 |

- 자식 프로세스 kill은 기존 `test_process_crash.py`처럼 READY 표식과 `threading.Event().wait()`로 정확한 경계에서 멈춘 뒤 kill한다. 긴 sleep에 기대지 않는다.
- K5·K6·K8의 경계는 자식 안에서 해당 함수를 감싸 표식을 쓰고 멈추게 해 강제한다.
- K 사슬 각 행에서 확인할 oracle:
  - **O1 원본 불변:** 시험이 hashlib로 직접 계산한다(`verify_bundle`에 기대지 않는다).
    - 확정 전후·재복구 전후에 모든 sealed bundle의 `audio.pcm`·`blocks.jsonl`·`descriptor.json` 바이트가 같다.
    - staging 디렉터리 파일 바이트가 같다(기존 `test_storage.py:184` 방식).
  - **O2 보존량:** 등록된 프레임 합 = 위 표의 손계산 값. PCM 바이트 연결 = 자식 스크립트가 쓴 블록 바이트의 prefix.
    - 구현 때 보강: 사슬은 원인 직후의 라이브러리를 OS TEMP에 복사한다. 사본에서는 별도 복구 없이 바로 `finalize_unfinished`를 호출해도 같은 보존량이 나오는지 확인한다(사용자가 `recoryn finalize`만 실행하는 경로).
    - 원본 사슬은 그대로 재복구부터 시작한다.
    - 보강 이유: 원본 사슬만으로는 확정 전에 복구가 이미 끝나서, 확정 안의 복구 단계를 빼는 M1을 K 행이 구별하지 못했다(§11).
  - **O3 재복구 멱등:**
    - 두 번째 `recover_session`: `adopted=0`, `recovered=0`, 상태·청크 목록·파일 바이트 불변.
    - FINALIZED 뒤 연속 두 보고는 `details`까지 같다.
  - **O4 이중 확정 방지:**
    - 두 번째 `finalize_unfinished`: `already_finalized=True`, `state_version` 불변.
    - `storage_events`의 FINALIZED 사건 수 = 1, `finalized_chunks` 바이트 불변.
  - **O5 확정 목록:** `finalized_chunks` = 확정 시점 catalog. 확정 뒤 새 bundle은 `CANDIDATE_NOT_ADOPTED`로만 보고되고 목록은 바뀌지 않는다.
  - **O6 내보내기:**
    - `export.json`이 생기고, `wave` 모듈로 읽은 PCM data가 해당 연속 구간 청크 payload 연결과 같다.
    - 확정 전 내보내기는 거부된다.
  - **O7 전사 수락:** fake STT로 비임시 전사 요청이 확정 뒤 수락되고, 확정 전 거부된다. `app/ai.py`는 읽기만 한다.
- K6은 `finalize_unfinished`가 이미 FINALIZED 경로로 manifest를 다시 써서 `manifest_sync_pending=0`이 되는지도 확인한다.

### 4.5 H 경쟁 순서

각 연산은 Library `root_mutex` 한 구간으로 선형화된다. 그래서 순서는 연산 단위로 강제한다. barrier로 두 thread의 진입 순서를 정하고, 앞 연산이 끝난 뒤 뒤 연산을 놓아준다.

| ID | 사건 | 분모 | 손계산 결과 |
| --- | --- | ---: | --- |
| H1 | 확정 ∥ 확정(같은 세션) | 2 | 두 순서 모두: 하나는 `already_finalized=False`, 다른 하나는 True. FINALIZED 사건 1 |
| H2 | 확정 ∥ 재복구 | 2 | 두 순서 모두 최종 FINALIZED, 원본·청크 목록 같음 |
| H3 | 확정 ∥ 삭제 | 2 | 확정 먼저 → 삭제가 DELETED_LOCAL. 삭제 먼저 → 확정이 `DELETE_PENDING` 또는 `KeyError`(삭제 완료 뒤)로 거부, 원본 재생성 없음 |
| H4 | live 녹음 중 재복구, writer 경계 위치 {첫 블록 전, writer 열림, seal 직후 다음 블록 전} | 3 | 세 위치 모두 거부(writer 열림은 기존 메시지, 나머지는 `SESSION_LIVE`). 상태 RECORDING 유지, 이후 stop 성공 |
| H5 | GUI 실행 중 CLI `finalize` | 1 | 두 번째 프로세스가 Library 잠금으로 실패, exit 1, 상태 불변 |

### 4.6 Q 상태열 oracle(닫힌 술어)

시작 상태 s0와 명령열 w에 대해 구현과 독립인 술어로 판정한다.
- 최종 상태:
  - w에 "확정"이 있으면 FINALIZED
  - 없고 "재복구"가 있으며 s0 ∈ {RECORDING, FINALIZING}이면 INTERRUPTED
  - 그 밖에는 s0
- 각 "내보내기"의 성공 조건: 그보다 앞에 "확정"이 있을 때만 성공. 나머지는 거부되고 상태·파일은 불변이다.
- 모든 명령 뒤 O1(원본 바이트 불변)이 성립해야 한다.
- 상한 L=3 밖의 명령열은 미검증이다. 상태 모델을 코드로 다시 구현하지 않는다(구현과 독립이 아니기 때문이다).

### 4.7 기존 시험과의 관계

| 기존 node | 관계 |
| --- | --- |
| `tests/integration/test_process_crash.py::test_actual_process_kill_preserves_exact_prefix[4 phase]` | K1~K4가 같은 자식 스크립트 구조와 손계산 값(8/12)을 쓰고, 그 뒤 확정·내보내기·재확정까지 이어 간다. 기존 node는 그대로 둔다 |
| `…::test_library_writer_lock_excludes_a_second_process` | H5의 근거. 그대로 |
| `tests/unit/test_storage.py::test_recovery_prefix_is_new_id_and_repeat_is_idempotent` | 복구는 INTERRUPTED로 끝난다는 의미를 유지한다. G1A-11의 편차 재현이 아니라 복구 단계의 계약으로 남는다 |
| `…::test_sqlite_commit_failure_not_reported_finalized` | F4의 앞부분. FINALIZING에 남은 뒤 확정 경로는 새 행에서 잇는다 |
| `…::test_orphan_adoption_and_finalized_orphan_is_not_adopted`, `…::test_future_staging_and_finalized_candidate_preserved`, `tests/integration/test_storage_integrity.py::test_finalized_orphan_cannot_change_the_sealed_original_list` | O5의 근거. quarantined 개수 의미는 바꾸지 않고 `details`만 더하므로 그대로 통과해야 한다 |
| `tests/integration/test_storage_integrity.py::test_finalize_recovery_never_mutates_original`, `::test_recovery_uses_only_verified_prefix_without_changing_staging` | O1의 근거 |
| `…::test_journal_only_deletion_intent_blocks_recovery_and_can_resume`, `tests/unit/test_storage.py::test_corrupt_deletion_history_blocks_auto_recovery` | DELETE_PENDING 행과 inventory fail-closed의 근거 |
| `tests/integration/test_app_service.py::test_threshold_seal_failure_releases_writer_and_preserves_prefix`, `tests/e2e/test_recording_control.py::test_rotation_failure_releases_writer_for_prefix_recovery` | live 판정이 저장 실패 뒤 서비스를 live로 보지 않음을 지키는 회귀 |
| `tests/e2e/test_recording_control.py::test_empty_session_and_idempotent_stop_keep_finalized_state` | 청크 0개 확정과 FINALIZED 멱등의 기존 근거 |
| `tests/integration/test_desktop_independent.py::test_interrupted_session_close_must_still_ack_live_sources` | UI가 현재 INTERRUPTED 세션을 확정하기 전에 녹음기 close로 source ack를 받는 흐름의 근거 |
| `tests/e2e/test_cli.py::test_two_track_recording_export_and_delete` | CLI 기존 명령 회귀 |
| Codex 독립 반례 `test_cross_review.py::test_recovered_media_is_present_but_cli_cannot_export`(TEMP, 읽기만) | "확정 전 export 거부"는 유지하고, 확정 뒤 export 성공이 새 C4·K 행이다 |

- 같은 계산식을 복사하는 시험은 만들지 않는다. 기존 node가 이미 확인하는 복구 prefix 정확성은 K 행에서 O2로 다시 확인하되, 새 가치는 확정·내보내기·멱등까지 잇는 데 있다.

## 5. mutation 계획

구현 뒤 `pyproject.toml`, `src`, `tests`를 OS TEMP 사본으로 복사하고, mutant를 하나씩 적용한다. 방법은 G03과 같다: sentinel import 확인, 정상본 PASS, 소스 hash 기록, import·수집 오류는 검출로 세지 않음.

| mutant | 변이 | 잡아야 할 assertion |
| --- | --- | --- |
| M1 | `finalize_unfinished`가 복구 단계를 건너뜀 | K1·K2(staging에만 있던 프레임 누락), T-RECORDING(이전)-확정. 구현 때 두 가지를 보강했다. T 행에는 확정 프레임 손계산 표(`SEALED_FRAMES`)를 더했고, K 사슬에는 사본에서 바로 확정하는 확인을 더했다(§4.4 O2). 이 보강이 없으면 각각 이 mutant를 구별하지 못한다 |
| M2 | `recover_session`의 live 보유자 검사 제거 | H4 두 위치, U7, T-RECORDING(live)-재복구 |
| M3 | 이미 FINALIZED일 때도 전이를 시도(멱등 분기 제거) | O4(K 전 행), C2 두 번째 호출, H1 |
| M4 | inventory가 삭제 의도를 제외하지 않음 | I-DELETE_PENDING(G-P05 경계) |
| M5 | inventory의 폴더 나열 제거 | I-DIRECTORY_ONLY, U6 |
| M6 | read model이 건강 기록 없는 epoch를 유실 0으로 표시 | R 건강 기록 없음 행, U2 |
| M7 | UI 세션 확정 버튼이 live와 현재 녹음기 조건을 모두 무시(구현 반영: 계약안의 "live만 무시"는 UI에서 동등 mutant다. 앱 안에서 live인 세션은 현재 녹음기 세션뿐이고, 현재 녹음기 조건이 이미 그 행을 막기 때문이다) | U3의 현재 녹음기 RECORDING·PAUSED 행 |
| M8 | CLI `finalize`가 거부를 exit 0으로 출력 | C3 두 행 |
| M9 | `expected_version` 비교 제거 | V expected_version 현재±1 행 |
| M10 | inventory가 쓰기를 함(DIRECTORY_ONLY에 `create_session`) | I 읽기 전용 행(파일·DB 바이트 불변) |

## 6. 수락 기준과 미검증

**수락 기준**
- 선언 분모 361이 실행 node와 일치하고 누락·중복이 0이다(분모 대조 시험).
- K 14행 모두에서 O1~O7이 성립한다. 특히 자식 프로세스 kill → 복구 → 확정 → 내보내기에서 원본 SHA가 불변이고, 재복구가 멱등이다(통합 계획 `:57`).
- G04-CE1이 `SESSION_LIVE`로 닫힌다.
- §4.7의 기존 node가 모두 통과한다.
- M1~M10이 모두 목표 assertion으로 검출된다.
- ruff, format, `python -m mypy src/recoryn scripts packaging`이 통과한다.

**미검증**
- 계수하지 않은 원인별 상태·동작 교차(§4.2), 명령열 길이 3 초과
- 재개(C00 결정 1로 제외): 기존 세션 attach와 새 epoch. GF-06과 함께 다룬다. G1A-11의 "PAUSED 재개" 부분은 PARTIAL로 남는다
- 비정상 종료된 실행의 유실 누계(GF-05). read model은 "알 수 없음"으로만 표시한다
- DIRECTORY_ONLY 삭제(§3.8 6번), 삭제 대기 목록(G-P05)
- 실장비 장치 시작 실패(W01~W04). D1·D2는 fake source다
- 실제 Narrator 판독(E02 외부 게이트). offscreen에서는 접근 이름·초점·Esc만 확인한다
- 전원 장애 중 내구성(기존 외부 게이트)

## 7. 실행 기록(계약 단계)

| 항목 | 결과 |
| --- | --- |
| G04-CE1 probe | 위 §2.4 JSON. 실행 환경은 Windows `.venv` Python 3.13.1이고 장치·모델·네트워크는 쓰지 않았다. 사본 루트는 `%TEMP%\recoryn-g04-probe-f479f603848e4aeda684710cc2dae2fa` |
| 제품·시험 코드 | 수정 없음 |

## 8. 파일 공유 주의

- 이 단위는 G-P05와 `storage/library.py`·`ui/main.py`를 공유한다. 통합 계획 `:61`대로 G-P04 push 뒤 G-P05를 시작한다.
- 이 단위는 삭제 대기 목록 API(`pending_deletions`)와 그 UI를 만들지 않는다. `unfinished_sessions`는 삭제 의도를 제외하는 것 말고는 삭제 상태를 다루지 않는다.
- G-P02(`ui/ai_bridge.py`·`ui/privacy.py`)와 G-P03(`content/store.py`·`app/ai.py`)의 파일은 쓰지 않는다.
  - DIRECTORY_ONLY 선택 때 `ai_bridge.selection`을 부르지 않는 것은 `ui/main.py` 안의 분기다.
  - 전사 수락 행(O7)은 `app/ai.py`를 읽기만 한다.

## 9. C00 결정 요청과 결정

**C00 결정(2026-11-23): 아래 6건 모두 승인.**
- 쓰기 범위는 §3.7의 10파일 그대로다. `app/desktop.py`, domain, `content/store.py`, `app/ai.py`, `ui/ai_bridge.py`, `ui/privacy.py`는 범위 밖이다.
- 기존 시험 파일은 수정하지 않는다. 삭제 대기 목록 API는 넣지 않는다(G-P05).
- 결정별 조건:
  - 결정 1: 재개는 제외하고, GF-06과 한 단위로 다룬다.
  - 결정 2: 같은 프로세스 호출자의 동작 변화를 문서에 적고, G04-CE1 원 반례를 시험 행으로 고정한다(§10).

요청했던 항목(이력):

1. **재개 범위:** 권장은 이 단위에서 기존 세션 attach·재개를 제외하는 것이다(§3.2). S1은 확정 경로로 닫고, 재개는 GF-06과 한 단위로 미룬다. 대안 B(포함)를 고르면 `app/desktop.py`가 쓰기 범위에 들어간다. 그 경우 이전 `capture_health` 병합과 실행 경계 기록을 추가하고 경우의 수를 다시 쓴다.
2. **live 보유자 registry와 `recover_session`의 새 거부:** 같은 프로세스 호출자에게 동작이 바뀐다(G04-CE1 수정). 승인을 요청한다.
3. **신규 파일 `src/recoryn/app/recovery.py`:** 지정 예상 파일 목록 밖이다. 이유는 §3.5다.
4. **CLI 형태:** `finalize <id>`와 `list --unfinished`를 두고, 두 명령에만 닫힌 `code`를 붙인다.
5. **DIRECTORY_ONLY 삭제를 이 단위 밖에 둘지:** 권장은 밖에 두는 것이다. 지금 동작은 NOT_FOUND이고 폴더가 남으며, UI는 "복구 후 삭제"로 안내한다.
6. **확정 뒤 staging 유지와 `ALREADY_RECOVERED` 표시:** 개수 의미는 유지하고 `details`만 더한다.

## 10. 구현 반영과 계약안과 달라진 점(2026-11-23)

### 10.1 같은 프로세스 호출자의 동작 변화(C00 결정 2)

- `RecordingService`는 생성 직후 `library.register_live_owner(session_id, self)`로 자신을 약한 참조로 등록한다.
- `is_live()`는 입력 수락 중이거나 writer thread가 살아 있을 때 참이다. Library가 root mutex 안에서 부르므로 capture gate를 잡지 않는다. gate를 잡은 쪽이 mutex를 기다릴 수 있어서, 잡으면 교착이 생길 수 있다.
- `recover_session`과 `finalize_unfinished`는 live 보유자가 있으면 `StateConflict("SESSION_LIVE")`로 거부하고 아무것도 바꾸지 않는다.
  - 기존 `has_active_writer` 거부(메시지 "Live writer cannot be recovered")는 그대로다. UI는 두 메시지를 같은 안내로 보인다.
- 바뀌는 호출:
  - 녹음이 진행 중인 세션의 복구 요청이 이제 거부된다. 이전에는 chunk writer가 없는 순간이면 녹음을 INTERRUPTED로 바꿨다(G04-CE1).
  - 저장 실패로 writer가 끝난 서비스, 일시정지로 drain한 서비스는 live가 아니므로 이전처럼 복구할 수 있다.
  - 기존 `test_app_service.py::test_threshold_seal_failure_releases_writer_and_preserves_prefix`와 `test_recording_control.py::test_rotation_failure_releases_writer_for_prefix_recovery`가 그대로 통과한다(§11).
- G04-CE1 원 반례는 `tests/integration/test_unfinished_recovery.py`의 `G04-H4-CE1-live-before-first-block`로 고정했다.
  - probe와 같은 순서다: 시작 직후 복구 → 이제 `SESSION_LIVE`. 이어서 블록 수락, 정지 성공, 최종 FINALIZED를 확인한다.
  - UI 경로는 `G04-U7`이 고정한다.

### 10.2 계약안과 달라진 점

1. **`inventory_warnings()`:** 계약안은 건너뛴 폴더 수의 형태를 "구현 때 정한다"고 했다.
   - `unfinished_sessions()`는 목록만 돌려주고, 건너뛴 수는 별도 메서드 `inventory_warnings() -> {"skipped_entries": n}`으로 준다.
   - UI 탐지 라벨이 이 수를 보인다. CLI `list --unfinished`는 계약대로 목록만 출력한다.
2. **`details`의 staging 상태:**
   - 끝부분을 채택하지 못한 staging은 재복구 때도 `TAIL_NOT_ADOPTED`로 남는다(누락 정보가 계속 보이게).
   - 끝부분까지 완결된 staging은 처음에 `RECOVERED`, 다시 복구하면 `ALREADY_RECOVERED`다.
   - FINALIZED 세션의 staging은 복구 ID를 읽기만 해서 계산하고 `ALREADY_RECOVERED` 또는 `CANDIDATE_NOT_ADOPTED`로 분류한다. 기존 `quarantined` 개수와 경고는 그대로다.
   - staging 순회는 결과 순서가 재현되도록 이름순으로 바꿨다.
3. **이미 확정된 세션의 `finalize_unfinished` 개수:** `finalized_chunks`(확정 목록) 열에서 센다. 계약 단계의 "manifest 재계산"은 bundle을 다시 검증해서, 파일 하나가 없어도 멱등 호출이 실패할 수 있었다.
4. **UI 결과가 덮어써지던 기존 결함:**
   - 원인: 복구 검토의 `done`이 결과를 쓴 뒤 `refresh_sessions()`를 불렀다. 그러면 현재 항목이 다시 선택되며 `_session_selected`가 세부 정보를 덮어썼다.
   - 영향: 원래 코드의 `str(result)`도 바로 지워졌다. U2 시험을 처음 돌렸을 때 드러났다.
   - 수정: 새로 고침을 먼저 하고 결과를 쓴다(복구 검토와 세션 확정 모두).
5. **T 표 "재개" 열:** INTERRUPTED(같은 프로세스)도 현재 녹음기의 `resume`이 `RESUME_REQUIRES_PAUSED`로 거부한다. 계약안의 "경로 없음" 대신 이것을 기대값으로 썼다(§4.3).
6. **T 확정 행의 프레임 oracle:** 상태별 확정 프레임 손계산 표 `SEALED_FRAMES`를 더했다. 이것이 없으면 T 표가 M1(복구 생략)을 구별하지 못한다(§5).
7. **M7 정의:** live 조건만 지우는 변이는 UI에서 동등 mutant라서, live와 현재 녹음기 조건을 함께 지우는 변이로 바꿨다(§5).
8. **시험 상태 파일:** 자식 프로세스의 READY 표식은 임시 파일에 쓴 뒤 `os.replace`로 원자 게시한다. 처음에는 표식이 생기자마자 부모가 빈 내용을 읽는 경합이 2행에서 났다. 시험 fixture의 경합이며 제품 결함이 아니다.
9. **UI 시험 수명:** 창을 Library fixture보다 먼저 닫는다. 처음에는 Library가 닫힌 뒤 창을 닫아 closeEvent가 실패했고, 그때 남은 non-daemon writer thread 때문에 pytest가 끝나지 않았다. 시험 코드 문제이며 제품 결함이 아니다.

### 10.3 변경 파일

| 파일 | 변경 |
| --- | --- |
| `src/recoryn/storage/library.py` | `LiveOwner`, `register_live_owner`, `_is_live`, `unfinished_sessions`, `inventory_warnings`, `finalize_unfinished`. `recover_session`에 live 거부, `previous_state`, `details` 추가. `_salvage`의 복구 ID 계산을 `_recovery_id`·`_staging_prefix`로 분리(공식 불변) |
| `src/recoryn/app/recording.py` | live 보유자 등록, `is_live()` |
| `src/recoryn/app/recovery.py`(신규) | `describe`, `next_actions`, `recovery_view`, `finalize_lines`, `directory_only_lines`, `unfinished_notice` |
| `src/recoryn/cli.py` | `finalize`, `list --unfinished`, 두 명령의 닫힌 `code` |
| `src/recoryn/ui/main.py` | `recovery_status` 라벨, 목록 표시(미확정, 폴더만 있음), 구조화한 복구·확정 결과, 세션 확정 버튼과 확인 대화상자, 사용 가능 조건, 거부 안내 |
| `tests/unit/test_unfinished_sessions.py`(신규) | T 72, I 12, Q 195, V 13, R 23 + 분모 대조 1 |
| `tests/integration/test_unfinished_recovery.py`(신규) | K 14, H 10 + 분모 대조 1 |
| `tests/e2e/test_cli_finalize.py`(신규) | C 5 + 분모 대조 1 |
| `tests/ui/test_recovery_ui.py`(신규) | U 17 + 분모 대조 1 |

## 11. 실행 결과(2026-11-23)

환경: Windows `.venv` Python 3.13.1, `QT_QPA_PLATFORM=offscreen`, `-p no:cacheprovider`, OS TEMP 아래 고유 basetemp, `-W error::ResourceWarning`. 기준은 commit `9d46b4a`(G-P03 포함) 위 작업 트리다.

### 11.1 판정: HEAD+G04 사본

- 사본 구성:
  - pyproject·src·tests를 복사했다.
  - 작업 트리의 다른 단위 변경을 HEAD 내용(`git show`)으로 되돌렸다. 대상은 G-P02의 `security/*`, `ui/ai_bridge.py`, `ui/privacy.py`와 관련 시험 9개다.
  - G-P02 미추적 시험 4개를 뺐다.
- 사본 위치: `%TEMP%\recoryn-g04-head-dc7a5abe170546b2b02449cfa4873afa`

| 실행 | 결과 |
| --- | --- |
| 관련 시험 전체: 신규 4개 + `test_process_crash.py`, `test_storage.py`, `test_storage_integrity.py`, `test_pcm_storage_oracle.py`, `test_app_service.py`, `test_recording_control.py`, `test_desktop_independent.py`, `test_desktop.py`, `test_capture.py`, `test_power.py`, `test_pcm_playback.py`, `test_cli.py`, `tests/ui` 전체 | **722 passed**(75.97s), 실패·오류·skip 0. JUnit sha256 `6ec4bc0730dffb31a6bdcd33602c22ce68dce34a6dc295045106f5a8978c3a1e` |
| 분모 대조(JUnit 집계) | T 72, I 12, Q 195, V 13, R 23, K 14, H 10, C 5, U 17 = **361**. 누락·중복 0. 별도 분모 대조 node 4개도 통과 |
| G04-CE1 | `G04-H4-CE1-live-before-first-block`, `G04-U7` 통과 |

### 11.2 작업 트리(참고)

- 같은 시험 목록: **910 passed**(80.04s).
- 작업 트리에는 G-P02 변경과 그 미추적 UI 시험(`tests/ui/test_consent_scope_ui.py` 등)이 있어서 node 수가 사본과 다르다. 판정은 §11.1로 한다.

### 11.3 mutation(M1~M10)

방법:
- 사본 위치는 `%TEMP%\recoryn-g04-mut-83640d05dfb443e7bf81aa94d2d1c462`다. `pyproject.toml`, `src`, `tests`를 복사했다.
- sentinel 시험(exit 0)으로 두 가지를 먼저 확인했다. 사본 rootdir의 pytest가 사본 `src`를 import한다. 시험 안의 하위 프로세스도 `PYTHONPATH=<사본>/src`로 사본을 import한다.
- 대상은 신규 시험 4개 파일(365 node)이다.

결과:
- 정상본: 365 passed.
- 정상본 LF sha256: `storage/library.py` `1b402e08…75f6`, `app/recovery.py` `ba54132e…6658`, `cli.py` `f6faf789…eae9`, `ui/main.py` `b67e1378…bfe6`. 모든 mutant 뒤 복원 hash가 같았다.
- 보고서 sha256: `40fcd112499e32e10537c1c65d9224f6da9db9712440ffa562e234e1186d9a55`

| mutant | 실패 수 | 목표 assertion 검출 | 대표 실패 node |
| --- | ---: | --- | --- |
| M1 | 12 | 예 | K1·K2·K3·K7·F1·F2, T의 RECORDING_STALE·INTERRUPTED_STALE·INTERRUPTED_INPROC·DIRECTORY_ONLY 확정 행, H2 두 행 |
| M2 | 4 | 예 | H4 CE1·after-seal, U7, T-RECORDING_LIVE-RECOVER |
| M3 | 58 | 예 | 모든 K·F 사슬의 재확정(O4), C2, H1, T-FINALIZED-FINALIZE, F를 두 번 이상 포함한 Q 명령열 |
| M4 | 1 | 예 | I-DELETE_PENDING |
| M5 | 4 | 예 | I-DIRECTORY_ONLY, U1, U3-DIRECTORY_ONLY, U6 |
| M6 | 2 | 예 | R-health-unknown, U2 |
| M7 | 2 | 예 | U3 현재 녹음기 RECORDING·PAUSED |
| M8 | 3 | 예 | C3 두 행, H5 |
| M9 | 2 | 예 | V ver-plus1·ver-minus1 |
| M10 | 3 | 예 | I-DIRECTORY_ONLY, U1, U6 |

- 10개 모두 수집·import 오류 없이(errors 0) assertion 실패로 검출됐다.
- 첫 실행에서는 M1의 K1·K2 목표가 통과했다. 원본 사슬이 확정 전에 복구를 먼저 끝내기 때문이었다. 그래서 K 사슬에 사본에서 바로 확정하는 확인을 더한 뒤(§4.4 O2) 10개를 모두 다시 돌렸다. 위 표가 재실행 결과다.
- 첫 실행 보고서(sha256 `9a876a1de28e428be5161035192e2fd9c04dfc468bf58f7043b7fa3cdcb8fb5c`)에서 M1은 7건 실패였고, 나머지 9개의 결과는 재실행과 같았다.

### 11.4 정적 검사

- `ruff check src tests scripts packaging`: 통과
- `ruff format --check src tests scripts packaging`: 157파일 통과
- `python -m mypy src/recoryn scripts packaging`: 84파일 이상 없음
- `git diff --check`(변경 소스 4개): 이상 없음

### 11.5 미해결

- §6 미검증 목록 그대로다: 계수하지 않은 원인별 상태·동작 교차, 재개(GF-06과 함께), 비정상 종료 실행의 유실 누계(GF-05), DIRECTORY_ONLY 삭제·삭제 대기 목록(G-P05), 실장비, 실제 Narrator 판독, 전원 장애. 과거의 생략922 산식은 G04-05에 따라 위 §4.2에서 바로잡았다.
- 전체 오프라인 회귀는 돌리지 않았다. 지시 범위가 관련 시험이었다. 작업 트리에 G-P02 변경이 함께 있어 전체 결과를 G04 판정에 그대로 쓸 수도 없다.

## 12. G04 검토 지적 수정 — 재배정과 경우의 수

2026-11-23, C00이 수정 작성 권한을 w5:p8 Codex에게 재배정했다. 기존 작성 결과는 §11의 이력이고 수정의 독립 재확인은 C00 지정 새 검토자가 맡는다. G04-R 검토자의 역할에서 이번 수정 작성자로 전환했으며 자신이 최종 독립 승인하지 않는다.

기준 HEAD **9284db071b36773b5681e8b8f5ff59c0f8e2c677**. 착수 전에 승인10파일의 LF SHA256을 검토 tree5a5f0316b227fb0bbc809fdc5d7c14522c154b19와 대조해 **10/10 일치**했다. 증거 루트 **R2=`C:/Users/gangd/AppData/Local/Temp/recoryn-g04-fix-h9rn7203`**, inputs.json에 양쪽 hash를 보존했다. 쓰기 범위는 기존10파일이며 G-P02b/security/privacy/ai_bridge/content.py는 변경하지 않는다.

### 12.1 수정 계약

- G04-01: 세션별 owner는 객체 identity를 키로 한 약한 참조 집합으로 유지한다. 동일 객체 등록은 멱등이며 서로 다른 owner도 함께 관찰한다. hash 불가능한 owner도 허용한다. 현재 live인지를 등록 때 한 번만 보는 방식은 쓰지 않는다. `_is_live`는 현재 살아 있는 owner 중 하나라도 live면 참이며 dead ref는 정리한다.
- G04-02: inventory의 staging/tracks/track/epoch를 is_dir/iterdir하기 전에 safe_path/check_path로 검사한다. reparse이면 안전 실패하며 외부 디렉터리를 열거하지 않는다. 기존 협력 프로세스 경계이며 같은 사용자에 의한 경로 교체 race의 OS 격리 보장은 아니다.
- G04-03: recover_session이 실제 검증과 catalog 일치를 확인한 `verified_chunk_ids`를 보고한다. 새 채택/복구 청크도 이 집합에 넣는다. recovery_view는 catalog 예상량과 검증 보존량을 별도 필드/영역으로 표시한다. 검증 사실이 없는 legacy 결과는 보존량 미확인으로 표시한다. manifest 동기화 안내만으로 원본 보존을 단정하지 않는다.
- G04-04: DIRECTORY_ONLY 선택 시 기존 AI 패널 전체를 비활성화한다. 이전 편집 입력과 revision은 보존하고 조작은 막는다. 정상 세션을 다시 고르면 활성화해 실제 세션을 load한다. orphan을 ContentStore.load에 넘기지 않는다. ui/content.py는 수정하지 않는다.
- G04-05: 위 §4.2·§6·§11.5의 잘못된 누락922 표현을 정정했다. 원래361행/365 node를 바꾸거나 S×A×K 전수라고 확대하지 않는다.

### 12.2 추가 입력 분할과 독립 oracle

| 보강 가족 | 입력 분할·분모 | 독립 기대값 |
| --- | --- | --- |
| G04-FIX-OWNER | 실제 녹음 owner의 live/paused→다른 owner 등록→resumed/동일 owner 재등록3 = **3** | recover·finalize 모두 SESSION_LIVE, 다음 합성4frame 수락·정상 정지 후 정확히4frame 확정, writer 종료 |
| G04-FIX-WEAK | 동일 객체 중복/GC된 owner/hash 불가능 owner3 = **3** | 멱등·실제 약한 수명·등록 후 동적 live 판정 |
| G04-FIX-PATH | staging/tracks/track/epoch4 = **4** | 실제 로컬 NTFS junction, 링크/그 아래로 향하는 Path.iterdir 관측0. 안전 실패 허용, 외부 target 불변 |
| G04-FIX-MEDIA | valid/missing/corrupt3 × 단일/정상 청크 혼합2 + 검증 정보 없는 legacy1 + 유효 bundle과 catalog 불일치1 = **8** | 손작성 예상/검증 frame 수 분리, 없는 파일·손상·불일치는 보존 합산 제외, 원본 파일 byte 불변 |
| G04-FIX-UI-MEDIA | missing/corrupt2 = **2** | 실제 UI 복구 결과의 예상량과 검증량이 구분되고 누락 경고 유지 |
| G04-FIX-UI-SELECT | 정상A→orphan→정상B × 편집 없음/저장된 편집 있음2 = **2** | orphan load0·이전 패널/편집 비활성·A 입력 보존, B 선택 뒤 활성·B revision, 부정 편집으로 원문 변경 없음 |
| 합계 | **22** | 모든 거부 입력도 분모에 포함, 실제 장치·모델 사용 없음 |

원래361행은 별도 집계로 유지한다. 새22행을 포함하면 대표행383·manifest4를 포함한 신규4파일 실행 node387이다. 기존 R-health2행은 실제로 검증한 fixture 청크 ID를 새 결과 사실에 명시하며 유실 미상≠0 기대값을 유지한다. 새 metadata가 없는데 보존량을 만들어 내는 호환 fallback은 두지 않는다.

mutation 계획: 기존 M1~M10을 현재 구조에서 확인하고, (N1) owner를 마지막 객체 하나로 축소, (N2) paused 때 기존 owner 교체 허용, (N3) owner 강한 참조 유지, (N4) inventory 중첩 경로 검사 제거, (N5) read model이 catalog 전부를 보존 합산, (N6) 복구 결과가 모든 catalog ID를 검증으로 표기, (N7) orphan 비활성 생략, (N8) 정상 세션 재활성 생략. 정상본 PASS 뒤 TEMP의 pyproject/src/tests/scripts/packaging 사본에 한 변이씩 적용하고 실제 사본 import를 확인한다. import/수집 오류·timeout은 검출로 세지 않는다.

### 12.3 직접 실행과 원 반례 재확인

격리 판정 사본은 **R2/isolated = HEAD9284db0 git archive + 승인 G-P04 10파일**이다. 작업 트리의 다른 변경을 복사한 뒤 일부를 되돌리는 방식으로 만들지 않았다. `PYTHONPATH=R2/isolated/src`와 pytest pythonpath를 고정했다. 기존 venv·`-B`·bytecode 억제·offscreen·HF/transformers offline·telemetry 차단·no:cacheprovider·새 OS TEMP basetemp를 쓴다. pytest에는 **`-W error::ResourceWarning -W error::pytest.PytestUnraisableExceptionWarning`**를 적용했다.

```powershell
# cwd R2/isolated. R2는 위 증거 루트의 축약 표기다.
D:/project/Recoryn/.venv/Scripts/python.exe -B -m pytest tests/unit/test_unfinished_sessions.py tests/integration/test_unfinished_recovery.py tests/e2e/test_cli_finalize.py tests/ui/test_recovery_ui.py -q -p no:cacheprovider -W error::ResourceWarning -W error::pytest.PytestUnraisableExceptionWarning --basetemp R2/new-four-bt --junitxml R2/new-four.xml --durations=5 --tb=short
```

직접 결과 **387 passed in 51.05s / exit0**, failure/error/skip0이다. 원래361행+manifest4와 보강22행을 구분한다. 파일별 unit331/integration28/CLI6/UI22다. 기존4개 manifest를 유지했고 실제 JUnit을 독립 집계한 **R2/case-audit.json**에서 T72/I12/Q195/V13/R23/K14/H10/C5/U17 및 새22의 ID 누락·중복0을 확인했다. 기존 test 함수 AST는 health2행의 새 검증 사실 추가를 제외하고 그대로다. 원본 T·Q·K 기대값이나 기존361을 축소하지 않았다.

초기 선택 실행은 새22+기존 health2 **24 PASS / 2.16s**였다. staging/tracks/track/epoch의 **실제 NTFS junction4행 모두 PASS·skip0·외부 열거0**이다. Windows 이외 환경에서는 이4행을 명시 skip하도록 표시했으며 이번 Windows 실행을 가짜 path 시험이나 skip 결과로 대체하지 않았다.

기존 독립 probe `recoryn-g04r-96ggil2d/test_independent_g04.py`의 TEMP 사본을 다시 실행해 **11 PASS / 1.49s**를 얻었다. source/helper 경로를 이번 isolated로 바꾸고, orphan의 기대 조건 한 줄은 C00 결정인 **비우기 또는 비활성**을 수용하도록 바꿨다. 원 probe는 비우기만 기대했다. 이 변경을 원본 무수정 실행으로 기록하지 않는다. 원 probe·검토 문서는 변경하지 않았다. 원 owner 두 변형은 기대값 변경 없이 모두 `refused=SESSION_LIVE, recorder_live=True`였으며 JSON도 R2에 보존했다.

UI의 정상A→orphan→정상B 정식2행은 이전 revision/입력 보존·패널과 표의 비활성·키 입력 무변경·orphan load0·B의 활성/정확한 revision을 함께 확인한다. main.py의 분기만 바꿨고 ContentStore.load/ui/content.py/ai_bridge.py를 바꾸지 않았다. catalog missing/corrupt를 실제 UI recover 경로로 실행한2행도 누락과 검증 보존량의 구분을 확인했다.

### 12.4 mutation과 정적 검사

도구 **R2/run_mutations.py**, diff·명령·실패 node·source hash·origin·JUnit은 **R2/mutations**에 있다. pyproject/src/tests/scripts/packaging을 함께 복사하고 매 실행 library.__file__이 해당 TEMP src인지 확인했다. 정상 선택 baseline **2.884초 PASS** 뒤 **M1~M10 + N1~N8 = 18/18 KILLED, survived/invalid/error0**이다. 모두 testcase 실패이며 import/수집 오류·timeout을 검출로 세지 않았다.

| 변이 | 직접 실패 관측 |
| --- | --- |
| M1 복구 생략 | T-RECORDING_STALE-FINALIZE |
| M2 recover live 거부 제거 | H4-CE1-live-before-first-block |
| M3 이미 확정 멱등 분기 제거 | T-FINALIZED-FINALIZE |
| M4 삭제 의도 inventory 제외 제거 | I-DELETE_PENDING |
| M5 폴더 나열 제거 | I-DIRECTORY_ONLY |
| M6 미상 유실0 표시 | R-health-unknown |
| M7 live/current 확정 버튼 제한 제거 | U3-current-RECORDING-live |
| M8 CLI 거부 exit0 | C3-finalize-delete-pending |
| M9 기대 version 대조 제거 | V-ver-plus1 |
| M10 inventory가 세션 생성 | I-DIRECTORY_ONLY |
| N1 owner를 마지막 하나만 보존(수정 제거) | FIX-OWNER-0 |
| N2 paused 때 기존 owner 대체 | FIX-OWNER-1 |
| N3 owner 강한 참조 보존 | FIX-WEAK-1 |
| N4 중첩 경로 검사 제거 | FIX-PATH-0의 실제 junction 외부 열거 |
| N5 catalog 전부를 보존 합산 | FIX-MEDIA-2 |
| N6 검증하지 않은 catalog ID도 검증 표기 | FIX-MEDIA-2 |
| N7 orphan 비활성 생략 | FIX-UI-SELECT-0 |
| N8 정상 세션 재활성 생략 | FIX-UI-SELECT-0 |

격리 사본의 `ruff check --no-cache .` PASS, `python -m mypy src/recoryn scripts packaging` **84 source files PASS**다. format은 승인된 Python9파일에만 적용했다. 정적 검사 뒤 제품 코드와 시험의 의미를 더 바꾸지 않았다.

### 12.5 지정 기준의 관련 회귀와 추가 전체 검증

**지정 기준9284db0+G-P04만의 사본**에서 §11.1과 같은 관련 계층 및 tests/ui 전체를 다음과 같이 실행했다. UI에는 기준에 커밋된 G-P02까지 포함하며 당시 미커밋 G-P02b는 섞지 않았다.

```powershell
# cwd R2/isolated, 기준9284db0 + G-P04 승인10파일. 환경은 §12.3과 같다.
D:/project/Recoryn/.venv/Scripts/python.exe -B -m pytest tests/unit/test_unfinished_sessions.py tests/integration/test_unfinished_recovery.py tests/e2e/test_cli_finalize.py tests/ui tests/integration/test_process_crash.py tests/unit/test_storage.py tests/integration/test_storage_integrity.py tests/property/test_pcm_storage_oracle.py tests/integration/test_app_service.py tests/e2e/test_recording_control.py tests/integration/test_desktop_independent.py tests/unit/test_desktop.py tests/unit/test_capture.py tests/unit/test_power.py tests/unit/test_pcm_playback.py tests/e2e/test_cli.py -q -p no:cacheprovider -W error::ResourceWarning -W error::pytest.PytestUnraisableExceptionWarning --basetemp R2/related-final-bt --junitxml R2/related-final.xml --tb=short
```

직접 결과 **962 passed in 100.79s / exit0**, failure/error/skip0이다. **UI 전체289 PASS**(scope UI218·기존49·G04 UI22)와 원래 저장·복구·원본 바이트·writer 종료·녹음 제어·CLI 회귀가 포함된다. 새4파일387도 이962에 포함되며 서로 더해 고유 node 수라고 쓰지 않는다.

그 전에 같은 기준 사본에서 관련 범위를 넘어 **전체 오프라인 시험을 두 경고 오류화 옵션으로 실행**했다. 직접 결과는 **9425 passed·1 failed / 352.85s**, 실패는 `tests/unit/test_consent_scope.py::test_malformed_scope_context[G02-TYPE-11]`에서 뒤늦게 GC된 **기존 SQLite fixture 연결6건의 ResourceWarning/unraisable**이다. G04 assertion 실패가 아니며 G04 밖의 그 파일은 수정하지 않았다. 9284db0의 해당 파일이 누수를 재현한66f0a85와 raw bytes가 같음도 확인했다(LF SHA256 `ccdb419f…69d7`). 실패 원문은 R2/full.log·full.xml, 대조는 baseline-full-failure.json에 보존했다. 초기 관련 명령의 pcm_playback 경로 오기는 시험 시작 전 수정했고 통과 수에 넣지 않았다.

이 경고는 C00이 검증 중 별도 커밋한 **G-P02b 234dd31a32426367268b3c8710a11ca82a010e6f**에 이미 수정돼 있다. 따라서 지정 기준의 관련962 PASS를 보존하면서, **추가**로 그 커밋을 git archive한 R2/integrated-234에 G04 10파일만 덧씌워 전체 검증한다. 지정 기준을 몰래 바꾸거나 옛 기준 전체가 경고 없이 통과했다고 기록하지 않는다. G-P02b의 privacy/consent/bridge/unit/UI/문서6파일은 커밋과 일치하며 건드리지 않았음을 R2/g02b-untouched.json으로 확인했다.

### 12.6 추가 통합 결과·최종 인계

```powershell
# cwd R2/integrated-234. 기준234dd31 + 동일한 G-P04 승인10파일만.
# PYTHONPATH=R2/integrated-234/src. 나머지 환경은 §12.3과 같다.
D:/project/Recoryn/.venv/Scripts/python.exe -B -m pytest -q -p no:cacheprovider -W error::ResourceWarning -W error::pytest.PytestUnraisableExceptionWarning --basetemp R2/integrated-full-bt --junitxml R2/integrated-full.xml --durations=8 --tb=short
```

직접 결과 **9506 passed in 321.95s / exit0**, failure/error/skip0이다. **UI 전체363, G-P03 content103·selection203, G04 신규4파일387**이 모두 포함된다. G-P02b가 해결한 fixture 경고까지 오류화한 전체 결과이며, 옛 기준의 실패를 경고 억제나 같은 기준 재시도로 가린 것이 아니다. 집계와 source 대조는 R2/full-audit.json에 있다.

통합 사본의 `ruff check --no-cache .`와 `python -m mypy src/recoryn scripts packaging`도 다시 실행해 PASS(**84 source files**)했다. 지정 기준 사본의 Python9파일 `ruff format --no-cache --check`도 **9 files already formatted**였다. 작업 트리·9284 사본·234 사본의 Python9파일 LF hash가 모두 같다. 실행 뒤 제품 코드·시험은 변경하지 않았고 문서에 결과만 추가했다.

| 직접 증거(R2 기준) | SHA256(LF, CR 제거) |
| --- | --- |
| new-four.xml | `d571ceb5e82a9ccf2662b8d5a4d5066d395780a119566b2d64839423728aba88` |
| review-replay.xml | `3a991013641e73db9a06bc0ec7a4e07d6a0853f2009f703336248e16f513124c` |
| case-audit.json | `2f457a51139baec98fa90eb4326d6a4b342a2a6072b4ebf7bc52c1b52dfb9af4` |
| mutations/results.json | `fb7dec6ee75cade29a52da60e9588f6b0104ee094ab8bce8f53fcadbd28bb441` |
| related-final.xml(9284) | `4f6d3099e92c0f489a948950d697e33306ee04a6e3b27178aa407cf19e2a363f` |
| integrated-full.xml(234) | `728535036cbc52ce44ffa3ac5d1843f4e8bbd79911f3788c721704e8bae908cf` |

**G04-01~05의 수정 작성 완료**이며 이 단위의 미해결 구현 반례는0이다. 원본 검토/작성 역할을 겸했으므로 새 독립 검토자의 재확인과 C00 통합을 기다린다. 이전 작성자의 시험 결과를 이번 직접 결과로 옮기지 않았고, 지정 기준의 전체 경고 실패도 위에 보존했다. 재개·G-P05 삭제 대기·G-P08 건강 누계·실장비/Narrator/전원 장애는 기존 후속/외부 게이트로 남긴다.

승인된 제출10파일의 현재 해시는 아래 Python9파일과 최종 창의 문서 해시로 고정한다. 이번 수정에서 검토 tree 대비 실제 바뀐 것은 library.py·recovery.py·main.py·unit/integration/UI 시험·이 문서의7파일이다. recording.py·cli.py·CLI 시험3파일은 기존 G04 내용을 유지했다. 문서 해시는 자기 참조를 피하며 R2/implementation-files.json에도 최종10파일을 기록한다.

| 제출 파일 | SHA256(LF, CR 제거) |
| --- | --- |
| src/recoryn/storage/library.py | `fb2e465f632c724189838a580425e6eb4a82926c106f0208b9c76d2f9c4fcc93` |
| src/recoryn/app/recording.py | `d591d87ef0dbe42f54142c72fa4b012bb9a6bda08b3cee6c30e9ca86a8947c61` |
| src/recoryn/app/recovery.py | `fb18dc062ffeb1e7906b6fbd8fdcc9fa265212472aaaff125375edf3310fff36` |
| src/recoryn/cli.py | `f6faf78966f17ee3d00608ac1c75f98eccbeeacb3e2d507651d4ad21f348eae9` |
| src/recoryn/ui/main.py | `ce6677c5b726315711a87c8fe8ecf1d478164f052143c93b5a6e03bd59859baf` |
| tests/unit/test_unfinished_sessions.py | `7646c227046d8a87b2583012f953c51d51034faaf5b2a8f8407bb40f8f1793e7` |
| tests/integration/test_unfinished_recovery.py | `52ee3203b155e9ee4ca52cee1e730c31862a3b19237ea1894742aba11aec52d6` |
| tests/e2e/test_cli_finalize.py | `7c8d015c5c47c70a66e67d49105693863d793b518dcb147a454634a67678bb9a` |
| tests/ui/test_recovery_ui.py | `e2f63da0020454e89a340c0be01602d668ce7b00a47ac7ee86877fd3d271b587` |

## 13. G04-06 후속 수정(FIX2)

C00은 재확인에서 G04-01~05를 RECHECKED로 수용하고, 한 세션의 경로 검사 실패가 전체 목록을 막는 G04-06(S2)을 고치도록 지시했다. §12의 전역 안전 실패 수용은 이 결정으로 대체한다. G-P06은 cost DTO·빈 catalog·계약 문구만 작성한 지점에서 멈췄으며 해당3파일 hash를 동결하고 이 단위를 먼저 처리한다. 쓰기는 G04 기존10파일 안으로 한정한다.

### 13.1 계약과 입력 분할

inventory 항목의 실제 DB state는 보존하고 `inspection_error`에 닫힌 코드 `INSPECTION_UNSAFE`(junction/reparse/hard link) 또는 `INSPECTION_UNAVAILABLE`(I/O 접근 실패)를 붙인다. 검사하지 못한 개수는 None이며 0건으로 표시하지 않는다. 정상 항목은 inspection_error=None이다. 각 세션의 경로 검사를 따로 실패 처리하고 다른 세션 목록/확정을 계속한다. 삭제 의도 이력처럼 라이브러리 전체의 권위를 결정하는 오류를 이 규칙으로 숨기지 않는다.

문제 세션의 recover/finalize는 같은 경로 preflight로 상태·청크를 바꾸기 전에 해당 코드로 거부한다. UI는 검사 불가 표시·그 세션 확정 비활성·복구 거부와 해결 안내(링크/하드 링크 제거, 권한 확인 후 새로고침)를 제공한다. 정상 세션의 버튼과 실제 확정은 계속 작동한다. staging/bundle 항목 및 알려진 미디어 파일도 따라가기 전 metadata로 검사한다. 외부 경로 열거는0이어야 한다.

| 새 가족 | 분모 | 독립 oracle |
| --- | ---: | --- |
| G04-FIX2-PAIR | 실제 NTFS junction/hard link2 | bad+good 목록 동시 유지·bad의 recover/finalize 닫힌 거부·good의4frame 확정·외부 열거0·원본 불변 |
| G04-FIX2-IO | 주입한 세션별 OSError1 | bad만 INSPECTION_UNAVAILABLE, good은 정상 목록·확정 |
| G04-FIX2-UI | 실제 NTFS junction/hard link2 | bad 표시/해결 안내/버튼 거부, good의 UI 확정 성공 |
| G04-FIX2-CLI | 실제 NTFS junction/hard link2 | list는 두 항목과 code를 반환하고 exit0, bad recover/finalize는 닫힌 거부, good finalize는 성공 |
| 합계 | **7** | 기존361+보강22는 유지. 새4파일은387+7=394 node이며 대표행은390 |

추가 mutation 계획: (F2-01) 세션별 ValidationError 격리 제거, (F2-02) preflight의 차단 제거, (F2-03) UI가 검사 불가도 확정 허용, (F2-04) 닫힌 거부 코드의 CLI 전달 제거. 기존 중첩 경로 검사 제거(N4)의 외부 열거 검출도 유지 확인한다. source/hash·실행 결과는 아래에 별도 기록한다.

### 13.2 직접 검증과 FIX2 제출

증거 루트 **R3=`C:/Users/gangd/AppData/Local/Temp/recoryn-g04-fix2-pj9mhada`**. 착수 시 G04 10파일이 직전 제출 hash와 전부 같음을 확인했다. **234dd31 git archive+G04 10파일만**의 R3/isolated에서 검증했고 G-P06 작업 중인 cost.py·cost_catalog.py·G06 문서는 포함하지 않았다. 그3파일의 동결 hash가 그대로임도 확인했다.

§12.5와 같은 관련 파일 목록과 tests/ui 전체에 `-p no:cacheprovider`, `-W error::ResourceWarning -W error::pytest.PytestUnraisableExceptionWarning`, offscreen·bytecode 억제·offline·고유 OS TEMP basetemp를 적용했다. **1043 passed in 95.87s / exit0**, failure/error/skip0이다. 신규4파일 **394**, UI 전체 **365**가 포함된다. 기준 커밋은 G-P02b가 포함된234dd31이며 §12의 옛9284 결과와 구분한다.

새7행은 모두 통과했다. 실제 NTFS junction/hard link 각각에 대해 backend·UI·CLI가 정상 세션의 실제 확정을 완료하고, 문제 세션은 검사 불가·닫힌 코드로 거부하는 것을 관측했다. backend observer의 외부 열거는0이며 target의 canary bytes와 bad 세션 상태가 유지됐다. CLI의 recover에도 닫힌 code를 전달했다. 최초 I/O fixture의 mkdir에 부모 생성이 빠진 시험 준비 오류1건은 parents=True로 고쳤으며 최종1043에 포함돼 PASS했다.

검토자의 `test_g04_recheck_probes.py`를 TEMP에 복사하고 UI helper 경로만 이번 사본으로 바꿔 **13 PASS / 1.50s**, 기대값 변경0을 확인했다. 초기 probe 실행의 pytest 설정 누락에 따른 unknown mark 경고는 정확한 pyproject를 `-c`로 지정해 최종 실행에서 제거했다. 경고를 ignore 처리하지 않았다. 원본 probe/검토 문서는 수정하지 않았다.

추가 mutation은 R3/run_mutations.py·mutations에 있다. pyproject/src/tests/scripts/packaging을 함께 복사하고 library.__file__을 사본 src로 대조했다. 정상 선택 **2.324초 PASS**, **F2-01~04+N4의 5/5 KILLED**, survived/invalid/error0이다. 각 목표는 세션별 예외 격리·backend 닫힌 거부·UI 버튼·CLI code·외부 열거 assertion이며 import/수집 오류·timeout을 검출로 세지 않았다.

격리 사본 ruff 전체 PASS, Python9파일 format check PASS, `python -m mypy src/recoryn scripts packaging` **84 source files PASS**다. G-P06 파일과 섞인 작업 트리 전체의 정적 결과로 기록하지 않는다. 작업 트리와 사본의 G04 Python9파일 LF hash가 일치한다.

| 증거(R3 기준) | SHA256(LF, CR 제거) |
| --- | --- |
| related.xml | `197f6ef7498ce31aa7a4dddcbb99d362491fe91710f23b691a75a72131d343a7` |
| probe-final.xml | `32331d54ee8b6b5eba8c50ab2403f2be8befbd6921d1a74e2143f7469cff2fdb` |
| mutations/results.json | `8fcce2bb1fded109960e5e3b72e498fb1fdfd4d78113cdfc001963e2dc5a5dcd` |

G04-06의 수정 작성 완료이며 같은 검토자의 독립 재확인은 대기다. FIX2에서는 관련1043을 실행했고 전체 오프라인9506을 다시 실행한 것으로 확대하지 않는다. G-P06은 동결 지점에서 이어간다. 제출10파일은 아래9파일과 최종 창의 이 문서 hash, R3/implementation-files.json에 고정한다.

| 제출 파일 | SHA256(LF, CR 제거) |
| --- | --- |
| src/recoryn/storage/library.py | `b4448c7b67930361eb441b7d5935effc80b5704aea59ad48c2a4f34ac634b270` |
| src/recoryn/app/recording.py | `d591d87ef0dbe42f54142c72fa4b012bb9a6bda08b3cee6c30e9ca86a8947c61` |
| src/recoryn/app/recovery.py | `90b269b26b50dd355d6532eebb7fe0924a66223f0431b16d8b308a090cc197be` |
| src/recoryn/cli.py | `3889ba65974c90a7966ba3f807e736e49bb1772b707daaf819958416412e0ccd` |
| src/recoryn/ui/main.py | `ba610b50e53b7209b908a610e522d701152be287546f9cd09f484fb1517feb77` |
| tests/unit/test_unfinished_sessions.py | `896463906bef9873cf2c401b93b7c6ea5bc80446bd4dd27b6d7ef4f62fa4889d` |
| tests/integration/test_unfinished_recovery.py | `52ee3203b155e9ee4ca52cee1e730c31862a3b19237ea1894742aba11aec52d6` |
| tests/e2e/test_cli_finalize.py | `e303a96b546d6c2a12de8be407492c94ccc1cc9952839ef95614a27309a8a0b3` |
| tests/ui/test_recovery_ui.py | `3b1fb1f3ee7441ea72befa27dff1469c506f0e9962acc55a0970614504619ec9` |

## 14. G04-07·08 후속 수정(FIX3)

G-P06의 29파일은 별도 LF hash로 동결했다. 이번 수정은 기존 G-P04 10파일 안에서만 수행한다. 목록은 root mutex 아래에서 DB·live 상태만 스냅샷하고 폴더 검사를 밖에서 수행하는 조회 시점의 관찰이다. UI는 한 번 얻은 목록과 경고를 함께 사용한다. 실행은 관찰을 권한으로 삼지 않고 다시 검사한다.

복구·확정은 프로세스 내 세션별 재진입 claim으로 직렬화한다. claim을 기다릴 때 root mutex를 보유하지 않는다. 파일 열거·경로 검사·해시·manifest 게시를 root mutex 밖으로 옮기고 DB 변경과 최종 generation 대조만 짧게 잠근다. 다른 스레드의 같은 세션 상태 변경·녹음 재개는 claim 동안 거부한다. 삭제 의도는 즉시 기록하고 파일 제거는 claim 종료 뒤 명시 재시도로 넘긴다. 삭제 의도가 먼저 기록되면 진행 중 확정은 FINALIZED를 게시하지 않는다. claim은 메모리 전용이며 프로세스 종료 후 남지 않는다.

입력 분할과 독립 oracle(기존 390행·manifest 4행은 유지):

| 추가군 | 분모 | 독립 oracle |
| --- | ---: | --- |
| F3-PERF | 목록 7,200묶음 / 확정 900묶음 / 복구 900묶음 = 3 | 다른 세션에 합성 48kHz PCM을 10ms 간격으로 제출. 거부·유실 frame 0, 원본 합계 일치, 관리 스레드의 실제 root mutex 연속 보유 최대 100ms 미만. 대기 시간은 제외하며 writer 자체 봉인 보유 시간은 별도로 관측·보존 |
| F3-CLAIM | 확정/복구 × 삭제/복구/두 번째 확정/재개 = 8 | 파일 검증을 barrier로 멈춘 동안 다른 세션 writer가 진전. 같은 세션 두 작업은 claim 직렬화, 삭제는 의도 선접수·파일 보존·확정 중단, 재개는 수락 전 거부 |
| F3-FAIL | 검증 예외/최종 commit 예외 = 2 | 예외 후 claim 해제, 이후 재시도 가능, 실패를 확정 완료로 표시하지 않음 |
| F3-UI | 목록 조회 1 | UI 갱신 1회에 폴더 검사 1회, 조회 시점 관찰 표시 |
| F3-LOCK | 목록/복구/봉인 3 | 실제 폴더 검사·verify_bundle 진입 시 root mutex 미보유를 직접 관측 |
| F3-VERSION | 최종 snapshot 변경 1 | 해시 뒤 generation을 바꾸면 봉인 commit 거부, FINALIZED 이벤트 0, 다음 재시도 성공 |
| F3-PROJECTION | manifest와 청크 등록 1 | 일반 projection은 같은 세션의 청크 등록을 거부하지 않음. generation 변경으로 projection만 안전 실패, 청크 frame 합 유지 |

추가 계획 분모 19, 전체 의미 행 409와 manifest 4행이다. 기존 H3의 확정 중 삭제 순서는 C00가 승인한 새 계약(삭제 의도 우선·확정 포기)으로 기대값을 변경한다. mutation은 목록/복구/봉인 검증의 root mutex 밖 이동 되돌리기 3개, claim 제거, 삭제 중 claim 무시, 쓰기 claim guard 제거, 최종 generation 재검사 제거, UI 중복 조회 복원, projection을 배타 claim으로 바꾸기 9개다. G04-01의 단일 owner 덮어쓰기, G04-02 중첩 경로 검사 제거, G04-06 세션별 예외 격리 제거 3개도 재검출한다. 실제 node 수와 측정·mutation 결과는 실행 뒤 별도 기록한다. 검사 상한을 맞추기 위한 입력 분모 축약은 하지 않는다.

초기 계측에서 모든 스레드의 root 보유 시간을 합쳐 상한을 적용하면 기존 `recoryn-writer-rec → ChunkWriter.seal`의 약 1초 봉인 때문에 실패했다. 이 스택은 녹음 writer 자체이며 G04 관리 경로와 다르다. 이번 수락 oracle은 관리 스레드의 보유 상한과 실제 동시 녹음 유실 0으로 명시하고, 전체 스레드의 최대 보유 시간도 결과에서 숨기지 않는다. 기존 ChunkWriter 내부 잠금의 별도 개선은 승인 10파일 밖이다. 일반 manifest projection은 삭제의 파일 제거와는 상호 배제하지만 녹음 청크 등록에는 배타 claim을 적용하지 않고 generation 비교로 신선도를 확인한다.

### 14.1 구현 경계와 직접 계측

증거 루트 **R4=`C:/Users/gangd/AppData/Local/Temp/recoryn-g04-fix3-80vdcllw`**. 착수 전 10파일이 FIX2 제출 hash와 같음을 확인했다. G-P06 29파일의 hash/부재 상태는 `g06-frozen.json`에 보존했으며 FIX3 동안 수정하지 않는다. 작업 트리를 시험하는 대신 **234dd31 git archive + 승인 G04 10파일**만 R4/isolated와 최종 R4/final에 얹었다. Python import 경로도 각 사본 src로 고정했다. 검토자의 g04b 측정 스크립트는 읽기만 했고 같은 분모·10ms 합성 PCM의 정식 시험을 별도로 작성했다. 실제 WASAPI 장치·모델·네트워크는 쓰지 않았다.

Library는 세션별 RLock을 기다리는 동안 root mutex를 잡지 않는다. claim 아래서 다른 스레드의 같은 세션 transition·chunk 등록·health 변경을 막는다. 복구 전용 ChunkWriter의 파일 작업도 세션 claim 아래서 수행한다. 삭제는 journal과 DB 의도를 먼저 기록하고 claim이 있으면 `DELETE_PENDING / SESSION_OPERATION_IN_PROGRESS`를 반환하여 파일 제거를 미룬다. 원본 제거는 claim을 얻은 뒤 root mutex 밖에서 한다. manifest는 DB 행을 복사한 뒤 descriptor 해석·정렬·검증·파일 게시를 밖에서 수행하며, 봉인 commit 직전에 generation·state_version·삭제 의도를 다시 대조한다. 일반 manifest projection은 청크 등록을 막지 않는 비배타 claim이며, 복구·확정 내부에서는 기존 배타 claim을 유지한다. 새 DB 표나 schema version 변경은 없다.

최종 코드의 `full-bt/**/measurement.json`에서 직접 얻은 수치다. 아래 시간은 관리 동작 자체이며 준비한 900묶음의 생성·시험 종료 시 녹음 봉인 시간은 포함하지 않는다. 관리 동작이 끝날 때까지 녹음을 계속했으므로 입력 제출 기간은 6초보다 길어질 수 있다.

| 동작 | 입력 | 관리 동작 시간 | 관리 스레드 root 최대 | 모든 스레드 root 최대 | 거부 블록 / 유실 frame |
| --- | --- | ---: | ---: | ---: | ---: |
| 목록 | 7,200 placeholder 묶음, 이전 세션 2트랙 | 6.039013초 | 1.114800ms | 1.109412초 | 0 / 0 |
| 확정 | 실제 900묶음 × 96,000frame = 30분 mono | 18.804878초 | 5.407200ms | 0.955675초 | 0 / 0 |
| 복구 | 같은 실제 900묶음 | 9.400352초 | 3.088700ms | 0.974564초 | 0 / 0 |

실제 녹음 writer와 동일한 기본 queue 256블록·기본 96,000frame 청크를 썼다. 세 행 모두 제출 frame 합과 확정된 녹음 청크 frame 합이 일치한다. 전체 root 최대의 긴 구간은 `long_holds`의 thread 이름과 stack으로 **기존 녹음 writer의 `_consume → ChunkWriter.seal`**임을 확인했다. 관리 스레드는 100ms 미만이지만 모든 root 보유가 100ms 미만이라는 주장은 하지 않는다. UI 목록 검사는 여전히 동기식이며 큰 폴더의 GUI 응답 지연 자체를 없앴다는 주장도 하지 않는다. 두 경계의 별도 개선 여부는 C00 판단 대상이다.

G-P05는 claim 동안 접수한 삭제 의도를 유지하고 명시 재시도에서 파일 제거를 이어가야 한다. G-P09의 유지보수 ACK는 진행 중 claim과 writer 종료를 기다려야 한다. 메모리 claim의 소멸은 별도 reader·다른 프로세스 종료의 OS 증명이 아니며 기존 coordinator의 명시 확인 계약을 대체하지 않는다.

보유 시간 상한의 범위를 확인하기 위해 **G04 파일을 전혀 얹지 않은 234dd31**도 별도 R4/baseline-src에 추출하여 실제 RecordingService로 합성 PCM 6초를 녹음했다(`baseline_writer.py`, `baseline-writer.json`). 관리 작업 없이도 writer의 `ChunkWriter.seal`에서 최대 **0.595734초**, 기존 `register_chunk`에서 0.288837초가 측정됐고 거부·유실 0, 기록량 288,000frame이었다. 이 기준 시험과 위 대용량 시험은 폴더 깊이·동시 I/O가 달라 절대 속도 비교로 쓰지 않는다. **100ms를 넘는 writer 자체 구간이 G04 없이도 존재한다**는 사실만 대조했다. FIX3의 register_chunk는 묶음 검증을 root 밖으로 옮겼지만 ChunkWriter.seal 자체는 수정하지 않았다.

### 14.2 최종 검증과 제출

최종 사본의 명령은 다음과 같다. 환경은 `PYTHONDONTWRITEBYTECODE=1`, `QT_QPA_PLATFORM=offscreen`, `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, `HF_HUB_DISABLE_TELEMETRY=1`, `PYTHONPATH=R4/final/src`이다. basetemp는 모두 OS TEMP의 고유한 새 경로다.

```powershell
# cwd R4/final, 234dd31 + G04 10파일. 작업 트리의 G-P06은 포함하지 않음.
D:/project/Recoryn/.venv/Scripts/python.exe -B -m pytest -q -p no:cacheprovider -W error::ResourceWarning -W error::pytest.PytestUnraisableExceptionWarning --basetemp R4/full-bt --junitxml R4/full.xml --durations=8 --tb=short
D:/project/Recoryn/.venv/Scripts/ruff.exe check --no-cache .
# 아래 Python 9파일에 대해 format --no-cache --check
D:/project/Recoryn/.venv/Scripts/python.exe -B -m mypy --cache-dir R4/mypy-final src/recoryn scripts packaging
```

**직접 결과: 9532 passed in 426.95s / exit0**, failure/error/skip/경고 0이다. **tests/ui 전체 366**, G-P02·G-P02b·G-P03 content/selection 시험과 기존 G04-01~06의 실제 NTFS junction·hard link 시험을 포함한다. 새 G04 4파일은 **334 + 46 + 8 + 25 = 413 node**이며 의미 행 409+manifest 4와 일치한다. node 중복 0이다. 네 파일의 JUnit testcase 시간 합은 **170.656초**다. 큰 디스크 fixture 생성과 합성 실시간 녹음이 포함된 수치이며, 분모를 줄이지 않았다. 대용량 측정 3행의 testcase 시간은 18.82·55.09·41.18초이고 위 관리 동작 시간과 구별한다.

최종 descriptor 해석을 mutex 밖으로 추가 이동하기 전 R4/isolated에서도 관련 시험과 전체 UI **1062 passed in 215.91s**를 직접 확인했다(`related.xml`). 그 뒤 코드는 위 최종 전체 9532 결과로 검증했다. 초기 선택 실행의 2건은 새 삭제 우선 계약에 맞춘 H3 기대값과 K7의 복구 전용 writer 강제 종료 hook을 조정했고, 초기 성능 3건은 모든 스레드의 mutex 상한을 적용한 결과였다. 이를 숨기거나 최종 정상본 PASS로 세지 않았다(`first.log`, `new.log`). 관련 실행 명령을 준비할 때 파일 경로 오기 때문에 collection 전에 종료한 두 번도 최종 집계에서 제외했다.

**mutation 12/12 KILLED**, survived/invalid/error 0이다. R4/mutations-final은 pyproject·src·tests·scripts·packaging을 함께 복사하고 실제 import 파일이 해당 사본 src 안인지 확인했다. 정상 선택은 PASS이고 각 mutant는 지정 기능 assertion 실패로 검출됐다. root mutex 밖 이동 되돌리기 3개는 실제 파일 검사 진입 시 mutex 미보유 assertion이 잡는다. claim 등록 제거·삭제 중 claim 무시·재개 guard 제거·최종 generation 검사 제거·UI 중복 조회·projection 배타 전환 6개, 그리고 기존 owner 덮어쓰기·세션별 경로 예외 격리 제거·중첩 경로 검사 제거 3개도 각각 검출했다. timeout·import·문법 오류를 KILLED로 세지 않았다. 이전 R4/mutations 12개와 중복 합산하지 않는다.

최종 사본 **ruff 전체 PASS, format Python9파일 PASS, mypy 84 source files PASS**다. `audit_final.py`가 234dd31 archive의 승인 범위 밖 추적 파일 차이 0, 작업 트리/최종 사본의 G04 Python9파일 LF hash 일치, G-P06 29파일의 hash/부재 상태 불변을 확인했다. 제품·시험 검증 뒤에는 결과 문서만 보강했다.

| 직접 증거(R4 기준) | SHA256(LF, CR 제거) |
| --- | --- |
| full.xml | `b2abf462a855af238a128c36dce142d9253d148bb43f39b6e36d66d5ef63fa5a` |
| mutations-final/results.json | `b48d7ebc10696ed8cab3419df264b3f5cf2e413837034c5b092e7ac318ee4428` |

수정 작성 결과는 G04-07·08의 독립 재확인을 기다린다. 관리 경로의 100ms 상한과 1트랙 합성 PCM 유실 0을 확인했으며, 실장비·느린 저장 장치·전원 장애 내구성·모든 writer 구간의 100ms 상한을 보장하지 않는다. 기존 writer 봉인과 동기식 대용량 UI 조회의 후속 판단은 위 §14.1처럼 분리한다. G-P06은 보존한 중간 지점에서 다시 진행한다.

제출 10파일은 아래 Python9파일과 최종 창의 이 문서 hash 및 R4/implementation-files.json으로 고정한다. FIX2 대비 이번에 바꾼 파일은 library.py·main.py·integration/UI 시험·이 문서의 5개다. 다른 5파일은 FIX2 내용 그대로다.

| 제출 파일 | SHA256(LF, CR 제거) |
| --- | --- |
| src/recoryn/storage/library.py | `6597485f11545683d8b2f9c7cfaf3e4568a848ac1c1a262dd0d1d958514f1745` |
| src/recoryn/app/recording.py | `d591d87ef0dbe42f54142c72fa4b012bb9a6bda08b3cee6c30e9ca86a8947c61` |
| src/recoryn/app/recovery.py | `90b269b26b50dd355d6532eebb7fe0924a66223f0431b16d8b308a090cc197be` |
| src/recoryn/cli.py | `3889ba65974c90a7966ba3f807e736e49bb1772b707daaf819958416412e0ccd` |
| src/recoryn/ui/main.py | `52cbd46a1df5aec37d41b7b426ff1b2485604054ea6a5fb60fbcf027be177f0c` |
| tests/unit/test_unfinished_sessions.py | `896463906bef9873cf2c401b93b7c6ea5bc80446bd4dd27b6d7ef4f62fa4889d` |
| tests/integration/test_unfinished_recovery.py | `4794b7f9a355233e9d3143b846e3c366a9fb050d5d912a111d15fd543b9d5bb1` |
| tests/e2e/test_cli_finalize.py | `e303a96b546d6c2a12de8be407492c94ccc1cc9952839ef95614a27309a8a0b3` |
| tests/ui/test_recovery_ui.py | `9f391d615ac6facae678e121641e2cb7e7b4b8d848fc958a7251327ff368b960` |

## 15. G04-09·10 후속 수정(FIX4)

C00 재확인 3은 G04-01~08을 유지하고, live 거부보다 앞서는 배타 claim(G04-10 S1)과 GUI thread 동기 조회(G04-09 S3)를 수정 대상으로 지정했다. G-P06의 비용 DTO·UI 및 새 시험 작성 지점에서 29파일의 hash/부재를 다시 동결한다. 이번 범위는 기존 G04 10파일이다.

계약 보강: 삭제 의도·live·version 거부는 claim을 기록하는 **같은 root mutex 구간에서, 기록보다 먼저** 판정한다. 녹음 owner가 live인 청크 등록은 다른 작업의 claim으로 거부하지 않는 방어선도 둔다. 조회는 별도 worker에서 수행하고 GUI는 ‘확인 중’을 표시한다. 요청 세대로 늦은 결과를 버리며 연속 요청은 최신 한 건으로 합친다. 녹음 제어 worker와 조회 worker를 분리하여 Stop이 조회 뒤에서 대기하지 않게 한다. 닫기 때는 조회 종료 ACK 뒤에 DB를 닫는다.

추가 입력 분할과 독립 oracle(409 의미 행+manifest4 유지):

| 군 | 분모 | oracle |
| --- | ---: | --- |
| F4-LIVE | recover/finalize 2 | 480frame마다 봉인하며 10ms 간격 3초 PCM + 반복 요청. 배타 claim 기록 0, 거부 블록·유실 0, 녹음 지속, 확정 수락 0 |
| F4-ADMIT | live×2, deleted×2, stale finalize, missing finalize = 6 | 거부될 요청은 claim set 관찰 0. recover에는 expected_version이 없어 stale 조합을 만들지 않음 |
| F4-WRITER | 잘못된 다른 claim 강제 주입 1 | live RecordingService의 청크 등록은 실패하지 않음. 이 시험은 사전 판정의 별도 방어선 검증 |
| F4-UI | background/세대 역전/연속 요청/실패/close ACK/제어 독립 6 | GUI thread 열거 0, 즉시 ‘확인 중’, 최신 결과만 게시, 조회 오류를 0건으로 표시 금지, DB 수명과 Stop 독립 |

mutation 계획: live 사전 판정 제거, writer 방어선 제거, version 사전 판정 제거, GUI 동기 조회로 되돌림, 세대 비교 제거, close ACK 제거. root mutex 표는 FIX3와 같은 7,200/900/900 입력으로 다시 측정한다. 행 수·시험 node·최종 결과는 구현 후 별도 기록하며 비결정적 클릭 시험만으로 사전 판정 검출을 주장하지 않는다.

### 15.1 구현·분모와 원 반례

증거 루트 **R5=`C:/Users/gangd/AppData/Local/Temp/recoryn-g04-fix4-heu075fs`**. 착수 시 10파일이 FIX3 제출 hash와 같음을 확인했다. G-P06은 비용 DTO·UI 및 새 시험 작성 지점에서 멈췄으며 29파일의 hash/부재 상태를 R5/g06-frozen.json에 동결했다. **234dd31 git archive + G04 10파일**만 R5/isolated에 얹어 판정했다.

`_admit_session`은 `_session_operation`의 claim 기록과 같은 root mutex 구간에서 삭제·live·expected_version·없는 세션·직접 seal의 잘못된 상태를 먼저 판정한다. 삭제된 recover의 기존 DELETE_PENDING 반환도 claim 없이 유지한다. `register_chunk`는 live owner/writer가 있으면 다른 작업의 claim으로 거부하지 않는다. 비 live 세션의 claim과 봉인 전 generation 대조는 유지한다.

목록 폴더 검사는 녹음 제어 pool과 다른 단일 worker pool에서 수행한다. 연속 조회는 실행 중 한 건과 최신 대기 한 건으로 합친다. GUI의 세대 검사로 오래된 성공·실패 결과를 버리고 ‘확인 중’을 유지한다. 조회 중에는 확정만 보류하며 녹음·일시정지·Stop 제어를 막지 않는다. 닫기는 capture를 먼저 종료하고 **제어 worker에서** 조회 pool의 종료 ACK를 기다린 뒤 나머지 store를 닫는다. GUI thread에서 waitForDone을 호출하지 않는다.

비동기 결과가 기존 G04-03/04의 상세 복구·확정 결과를 덮지 않도록 명시 검토 결과를 세션·state_version에 연결해 유지한다. 상태 버전이 달라지거나 다른 세션을 선택하면 일반 상세 표시로 돌아간다. 목록 재구성 중의 일시적 선택 신호는 차단하고 마지막 선택을 한 번 반영한다. DIRECTORY_ONLY에 ContentStore.load를 호출하지 않는 기존 경계도 유지한다.

추가 **15행**, 전체 **424 의미 행 + manifest4 = 428 node**다. 파일별 node는 unit340 / integration49 / CLI8 / UI31이다. F4-ADMIT의 publication 관측은 거부된 요청이 나중에 writer 방어선 덕분에 무해해졌다는 사실과 독립적으로 claim 기록 0을 검증한다.

실제 RecordingService, 480frame마다 봉인, 48kHz·10ms 간격 300블록·3초 제출에서 직접 얻은 값이다. 두 경우 모두 제출 PCM와 최종 청크 bytes가 같고 **300청크·144,000frame**이다.

| 반복 요청 | 거부된 호출 | ACCEPTED | 배타 claim 기록 | 거부 블록 / 유실 frame | 3초 뒤 녹음 |
| --- | ---: | ---: | ---: | ---: | --- |
| recover | SESSION_LIVE808 + 기존 Live writer 코드16 | 0 | 0 | 0 / 0 | accepting=True, storage_failed=False |
| finalize | SESSION_LIVE838 | 0 | 0 | 0 / 0 | accepting=True, storage_failed=False |

검토자의 원 `test_g04c_live_claim_race.py`(LF SHA256 `d492577c3634bf58ca18dde43e4b35d093a9cba67bd848fbab3070033014a7f6`)를 내용 변경 없이 TEMP에 복사해 **4 passed / 42.74s**를 재확인했다. 반복 recover/finalize 2행과 느린 journal 단일 클릭 2행이다. 원본 파일·검토 문서는 수정하지 않았다.

### 15.2 root mutex 재측정

FIX3와 같은 입력·meter이며 관리 스레드의 연속 보유와 전체 thread 최대를 구별한다. 100ms를 넘는 전체 최대는 이전처럼 기존 writer의 `ChunkWriter.seal` 스택에서 관측됐다. 아래 관리 동작 시간에는 대량 fixture 생성과 종료 후 녹음 봉인 시간이 들어 있지 않다.

| 동작 | 입력 | 관리 동작 시간 | 관리 root 최대 | 전체 root 최대 | 거부 / 유실 |
| --- | --- | ---: | ---: | ---: | ---: |
| 목록 | 7,200 placeholder 묶음 | 7.215448초 | 1.634700ms | 1.291876초 | 0 / 0 |
| 확정 | 실제 900묶음·30분 mono | 20.909382초 | 3.864800ms | 1.057051초 | 0 / 0 |
| 복구 | 같은 실제 900묶음 | 9.794169초 | 3.363900ms | 1.160406초 | 0 / 0 |

관리 스레드는 세 행 모두 100ms 미만이며 제출 frame 합과 저장 frame 합이 같다. 이 시간 값을 장치·디스크 전반의 보장으로 확대하지 않는다. GUI 응답성은 별도의 gate/heartbeat/thread ID 시험으로 검증했으며 이 표는 GUI 시간을 재는 표가 아니다.

### 15.3 실행·mutation·제출

환경은 §14.2처럼 offscreen·bytecode 억제·HF/transformers offline·telemetry 차단이고, `PYTHONPATH=R5/isolated/src`, `-p no:cacheprovider`, **`-W error::ResourceWarning -W error::pytest.PytestUnraisableExceptionWarning`**, 고유 OS TEMP basetemp를 사용했다.

관련 명령은 §14의 신규 4파일·storage/integrity/PCM oracle·app_service·recording_control·desktop·capture·power·playback·CLI·process_crash·tests/ui 전체에 **tests/unit/test_content.py와 tests/integration/test_selection_version_cas.py**를 함께 지정했다. **1383 passed in 288.26s / exit0**, failure/error/skip/경고0이다. **UI 전체372, G-P03 content103·selection203**을 포함한다. 네 G04 파일의 testcase 시간 합은 231.483초다. FIX4에서는 전체 9,000여 node를 다시 돌린 것으로 기록하지 않는다.

정상 관련 실행 후 ACK oracle을 더 강하게 만들었고 **최종 UI31 / 5.11s PASS**를 별도로 실행했다. 다른 제품·시험 파일은 바꾸지 않았다. 초기 선택 실행은 17 PASS·기존 U5/U6 상세 덮어쓰기 실패2였고 제품을 보완했다. 다음 UI+unit 실행은 710 PASS·소유한 FIX2 UI의 비동기 완료 대기 누락2였고, 정상 세션을 고르기 전 조회 완료를 기다리도록 시험을 적응했다. 이 실패를 정상본 PASS로 합산하지 않았다.

**최종 mutation 12/12 KILLED**, survived/invalid/error0이다. pyproject/src/tests/scripts/packaging을 함께 복사하고 각 실제 import 위치가 사본 src인지 확인했다. 정상 선택은 18.61초 PASS다. F4-M01은 live 사전 판정을 제거하되 writer 방어선은 남긴 mutant이며 **실제 반복 클릭 G04-10 시험의 claim publication assertion이 검출**한다. writer 방어선·version 사전 판정·GUI worker 이동·세대 검사·reader ACK 제거도 각각 검출했다. FIX3의 root 밖 이동 3개, 기존 owner 덮어쓰기·예외 격리·중첩 경로 검사 3개도 재검출했다.

초기 ACK 제거 mutant **1개가 살아남았음**을 R5/mutations에 보존한다. 기존 시험은 종료 시작 직후 busy만 봐서 control worker가 아직 진행하지 않은 경우를 구별하지 못했다. 최종 시험은 실제 wait 진입과 다음 shutdown 단계의 이벤트를 관측하고 reader 완료 전 다음 단계 진입을 거부한다. 강화한 정상 시험 PASS 후 R5/mutations-final에서 12개를 다시 실행해 ACK 제거도 assertion 실패로 검출했다. timeout·import·구문 오류를 검출로 세지 않는다.

최종 **ruff 전체 PASS, format Python9파일 PASS, mypy 84 source files PASS**다. 결과 보강은 문서와 강화한 UI 시험뿐이며 제품 Python 파일은 정적 검사 후 바꾸지 않았다. `audit.py`는 승인 범위 밖 추적 파일 차이0, 작업 트리/사본 Python9파일 LF hash 일치, 428node와 중복0, G-P06 29파일 불변을 확인했다.

| 직접 증거(R5 기준) | SHA256(LF, CR 제거) |
| --- | --- |
| related.xml | `7e77edc6025c93bd4da1c65f3ff850afe6fdeb05dabb2cfed652515cd4256fbb` |
| ui-final.xml | `93fe5a8658d51bedc9a702550f113725e6f38e675e57b726c57651938672eace` |
| probe.xml | `983a53290f874368b4e31097575d2c89c567e462732274e798a2a7aa32b59fda` |
| mutations-final/results.json | `82122d3a11b40b75e276783ca72c280dcfd4e9c4975e9dd4c2dd5c1c9338f585` |

G04-09·10의 수정 작성 결과는 같은 검토자의 독립 재확인을 기다린다. 실제 음성·GPU·모델·네트워크·vault 쓰기는 하지 않았다. 기존 writer 봉인 자체의 긴 root 구간과 실장비·전원 장애는 §14처럼 이번 보장 밖이다. G-P06은 동결한 지점으로 돌아간다.

FIX3 대비 바뀐 파일은 library.py·main.py·unit/integration/UI 시험·이 문서의 6개다. 제출 10파일은 아래 Python9파일과 최종 창의 문서 hash, R5/implementation-files.json으로 고정한다.

| 제출 파일 | SHA256(LF, CR 제거) |
| --- | --- |
| src/recoryn/storage/library.py | `962f34bcbad5aaf1a719ca35d4eccf0e9589951e800de0755328f39e7143ac0c` |
| src/recoryn/app/recording.py | `d591d87ef0dbe42f54142c72fa4b012bb9a6bda08b3cee6c30e9ca86a8947c61` |
| src/recoryn/app/recovery.py | `90b269b26b50dd355d6532eebb7fe0924a66223f0431b16d8b308a090cc197be` |
| src/recoryn/cli.py | `3889ba65974c90a7966ba3f807e736e49bb1772b707daaf819958416412e0ccd` |
| src/recoryn/ui/main.py | `8503ecc3546ca965dc834cec067ee19bc46b77537e96fd1f451cf9c11a316680` |
| tests/unit/test_unfinished_sessions.py | `d6d54873dd2255141d02286d2102844dceccea5af61a95b5ae9234ecb39fcc3d` |
| tests/integration/test_unfinished_recovery.py | `9fb3d5b0a392996bf36709f4a0976a72b90a60eda639f8db2667b51161d51ff0` |
| tests/e2e/test_cli_finalize.py | `e303a96b546d6c2a12de8be407492c94ccc1cc9952839ef95614a27309a8a0b3` |
| tests/ui/test_recovery_ui.py | `fb7381d89bc03711e731924520851dde0f45add5a26996d1cc7b19c00cf102ea` |

## 16. 관리 작업 보유 시간 oracle 정정(FIX5)

C00의 정확한 tree `00cf4ce9` 전체 실행에서 PERF 3행은 거부 블록 309/432/133으로 실패했으나 같은 세 행의 단독 재실행 두 번은 모두 PASS였다는 보고를 받았다. C00이 관측한 관리 root 최대는 1.6~6.4ms이며, 0.9~1.9초의 긴 보유는 writer의 `_consume → seal → __exit__`였다. 이 수치는 C00 보고에서 옮긴 것이며 이번 작업자의 직접 재측정과 구별한다. 기존 §15.2 및 검토자의 유실 0 측정은 해당 실행의 관측으로 보존한다.

입력·분모는 기존 `G04-F3-PERF-inventory-7200/finalize-900/recover-900` **3행 그대로**다. 독립 oracle은 (1) 관리 스레드의 최장 연속 root 보유 <50ms, (2) 50ms 이상 보유 이력 중 관리 스레드 0건, (3) 손으로 정한 목록 7,200묶음·확정 900묶음/86,400,000frame·복구 900묶음의 결과 성공이다. 거부 블록·유실 frame·저장 frame·전체 root 최장은 측정하고 출력하되 관리 작업과 무관한 writer seal 지연까지 유실 0으로 단정하지 않는다. writer의 fsync·scan·rename·재해시 구간 개선은 C00이 분리한 저장 계층 S2 후속이다.

승인된 시험·문서 두 파일만 바꾼다. `234dd31 git archive + G04 10파일` 사본에서 정상 3행 반복과 다른 무거운 시험 동시 실행을 계획한다. 임시 사본에서 각 관리 동작 전체를 root mutex 안으로 되돌리는 mutant 3개를 새 보유 시간 assertion으로 검출한다. 정상/부하/변이 결과 및 ruff·format·G-P06 동결 hash 대조는 실행 뒤 이 절에 기록한다. 시험 분모를 축소하거나 제품 코드를 바꾸지 않는다.

### 16.1 직접 실행 결과

증거 루트 **R6=`C:/Users/gangd/AppData/Local/Temp/recoryn-g04-fix5-j17ie7p3`**. 착수 전 G04 10파일은 C00의 tree `00cf4ce9`와 LF hash가 전부 같았다(`starting-tree-match.json`). G-P06 29파일은 `g06-frozen.json`으로 동결했다. R6/isolated는 **234dd31 git archive + G04 10파일**이며 그 밖의 추적 파일 차이 0을 직접 대조했다. 실제 import 위치가 사본 src임을 매 실행 확인했다.

명령은 `D:/project/Recoryn/.venv/Scripts/python.exe -B -m pytest tests/integration/test_unfinished_recovery.py::test_management_never_blocks_another_recording -q -s -p no:cacheprovider -W error::ResourceWarning -W error::pytest.PytestUnraisableExceptionWarning --basetemp <R6의 실행별 고유 폴더> --junitxml <R6의 실행별 XML>`이다. `run.py`와 `results.json`에 실제 전체 인자를 보존했다. offscreen·bytecode 억제·HF/transformers offline 환경이며 실제 장치·모델·네트워크를 쓰지 않았다.

| 실행 | 동작 | 관리 시간(초) | 관리 root 최대(ms) | 전체 root 최대(초) | 거부 블록 | 유실 frame | 관리 ≥50ms 건수 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| repeat-1 | 목록 | 6.101822 | 1.117600 | 1.122999 | 0 | 0 | 0 |
| repeat-1 | 확정 | 20.569377 | 4.423700 | 1.072686 | 0 | 0 | 0 |
| repeat-1 | 복구 | 9.572575 | 4.004800 | 1.015792 | 0 | 0 | 0 |
| repeat-2 | 목록 | 6.146646 | 1.142200 | 1.202815 | 9 | 4320 | 0 |
| repeat-2 | 확정 | 18.382939 | 4.717100 | 1.008385 | 233 | 111840 | 0 |
| repeat-2 | 복구 | 8.757544 | 4.045600 | 0.981206 | 0 | 0 | 0 |
| under-load | 목록 | 6.811393 | 1.112700 | 1.236325 | 37 | 17760 | 0 |
| under-load | 확정 | 20.476407 | 6.126500 | 1.008439 | 263 | 126240 | 0 |
| under-load | 복구 | 10.133753 | 3.880500 | 1.012628 | 21 | 10080 | 0 |

단독 3행을 두 번 돌려 **6 PASS**였다. 부하 조건에서는 같은 사본에서 별도 pytest 프로세스가 `tests/property/test_pcm_storage_oracle.py`와 동일 PERF 3행을 실행하는 동안 주 프로세스도 PERF 3행을 실행했다. 주 프로세스 **3 PASS**, 부하 프로세스 **4 PASS**로 합계 **13 PASS**, failure/error/skip/경고 0이다. 전체 회귀를 새로 돌렸다는 뜻은 아니다.

| 실행 | PASS node | pytest 시간(초) |
| --- | ---: | ---: |
| repeat-1 | 3 | 114.657 |
| repeat-2 | 3 | 127.227 |
| under-load | 3 | 143.137 |
| load-worker | 4 | 146.342 |

부하 프로세스 자체의 관리 root 최대도 19.738700ms였고 관리 ≥50ms 이력은 0건이다. 정상 12개 PERF 실행에서 50ms 이상 보유한 thread는 모두 `recoryn-writer-rec`, 스택은 `_consume → seal → __exit__`였다. 유실이 관측된 실행도 숨기지 않고 위 표와 각 `measurement.json`에 남겼으며 이를 G04가 만든 유실 또는 저장 계층 전체의 유실 0 보장으로 해석하지 않는다.

검토자 원 측정은 `docs/reviews/g04-unfinished-session-recheck.md`의 RECHECK 4/R4-5에서 목록 7,200묶음 **8.989초·유실 0**, 30분 세션 확정 **15.636초·유실 0**이었다(검토 문서 인용, 이번 직접 실행 아님). 이 증거 및 §15.2의 직접 유실 0 관측은 이력으로 그대로 보존한다.

### 16.2 mutation·정적 검사·범위

각 mutant는 별도 TEMP 사본에 pyproject/src/tests/scripts/packaging을 함께 복사하고 실제 import 위치를 검사했다. 한 관리 함수 전체를 `with self._mutex:`로 감싼 변이이며 나머지 두 함수는 바꾸지 않았다.

| 변이 | 되돌린 함수 | 해당 관리 root 보유(초) | 목표 assertion | 결과 |
| --- | --- | ---: | --- | --- |
| F5-M01 | `unfinished_inventory` | 4.269691 | `max(meter.management_holds) < 0.05` | KILLED |
| F5-M02 | `finalize_unfinished` | 12.680310 | `max(meter.management_holds) < 0.05` | KILLED |
| F5-M03 | `recover_session` | 6.216239 | `max(meter.management_holds) < 0.05` | KILLED |

**3/3 KILLED**, survived/invalid/import 오류/timeout 0. 정상본이 통과한 같은 case ID의 실제 assertion 실패로 검출했다. 변이 diff·원본/변이 source SHA·실행 인자·실패 node는 R6의 `mutant-*.diff`, `results.json`, `mutation-*.xml/log`에 보존했다.

`ruff check tests/integration/test_unfinished_recovery.py`와 `ruff format --check tests/integration/test_unfinished_recovery.py`는 PASS다. 제품 코드는 바꾸지 않았으며 이 두 파일 외 G04 8파일과 G-P06 29파일은 착수 hash 그대로다. 최종 사본도 지정 10파일 이외에는 234dd31 그대로다. 독립 재확인과 C00 승인을 기다리며 G-P06을 동결 지점에서 재개한다.

| 증거(R6 기준) | SHA256(LF, CR 제거) |
| --- | --- |
| repeat-1.xml | `27218891ad33f5f9405ce0d05449b73b67bfeeab603027a5599bfe8a497fec3a` |
| repeat-2.xml | `7ee76161290c5be563fd0c89e663d5a25c6145e3e661eb2bb4b5064f6e60c7be` |
| under-load.xml | `1dd1521f2547d923717a2a6f69de218c2789a86a6c5e9e9749aee0a1ece198f1` |
| load-worker.xml | `02b538116a4f278563bd595149db3954d3c4088848aa4e265e5ae96753783332` |
| results.json | `3aece937066a105a6788f3b0fbc8a5732be132fe34d4b35d697ba9d4047c29f4` |

### 16.3 측정 완료 대기와 추적성 보강(FIX6 / G04-12)

C00의 최종 tree `ce060567` 전체 실행에서 확정 900묶음 행이 기존 30초 창을 넘겨 실패했고 나머지 9,546건은 PASS였다는 보고를 받았다. 동시 부하로 전체가 710초까지 늘었다는 관측은 C00 보고이며 이번 직접 측정과 구별한다. 관리 동작이 30초 안에 끝나야 한다는 요구는 G04 계약이 아니므로, 생성 frame 수에 의한 30초 제한을 없애고 관리 작업이 끝날 때까지 10ms 합성 블록 제출을 계속한다. 무한 대기 방지용 wall clock 상한만 **300초**로 둔다. 기존 입력 3행·case ID·관리 root <50ms·관리 장기 보유 0건·결과 성공 oracle은 그대로다.

writer seal의 fsync·scan·rename·재해시 root 구간은 **G-P15(S2, `docs/implementation/v1-gap-plan.md`의 2차 후속 단위)**다. 이번 수정은 그 저장 계층 결함을 고친 것이 아니며 거부·유실은 계속 측정값으로 남긴다. RECHECK 5의 문서 지적 **G04-12**에는 이 ID와 아래 최종 시험 LF hash를 보강하여 대응한다. 문서 자체의 최종 LF hash는 제출 창과 TEMP 파일 목록에 남긴다.

확인 계획은 `234dd31+G04 10파일` 사본에서 3행 반복과 별도 PCM/대용량 시험 동시 부하다. 실제 관리 작업 전에 TEMP에서 32초 지연을 주는 추가 선택 실행으로 30초를 넘겨도 합성 녹음이 계속되고 실제 900묶음 확정이 성공하는지도 확인한다. 제품이나 CI 시험에 고정 지연을 넣지 않는다. 실행 결과·변경 시험 hash·ruff·format·G-P06 29파일 불변 대조는 완료 후 이 절에 기록한다.

| FIX6 변경 시험 | SHA256(LF, CR 제거) |
| --- | --- |
| tests/integration/test_unfinished_recovery.py | `7871d9415ab921e3f4a7a7c99d20bf505c1afbef8c6da7e445281b524f73ecee` |

이 문서의 최종 hash는 제출 창 및 증거 루트의 `implementation-files.json`에 기록한다. 문서에 자신의 최종 hash를 삽입하지 않으며, 위 시험 hash와 기존 FIX5 증거 hash를 구별한다.

### 16.4 FIX6 직접 실행 결과

증거 루트 **R7=`C:/Users/gangd/AppData/Local/Temp/recoryn-g04-fix6-glvlsrg5`**. 착수 시 G04 10파일은 `ce060567`과 LF hash가 모두 같았고(`starting-tree-match.json`), R7/isolated는 **234dd31 git archive + G04 10파일**로 만들었다. G-P06 29파일은 `g06-frozen.json`으로 동결했다. 수정은 이 문서와 integration 시험 두 파일뿐이다. ruff check·format --check는 PASS다.

기존과 같은 offscreen·bytecode 억제·HF/transformers offline, `-p no:cacheprovider`, 고유 TEMP basetemp, `-W error::ResourceWarning -W error::pytest.PytestUnraisableExceptionWarning`를 사용했다. 각 실행의 실제 import 위치가 해당 사본 src인지 확인했다. 실제 음성·장치·모델·네트워크를 쓰지 않았다.

| 실행 | PASS node | pytest 시간(초) | 구성 |
| --- | ---: | ---: | --- |
| repeat-1 | 3 | 127.910 | 기존 PERF 3행 |
| under-load | 3 | 128.766 | 같은 3행, 아래 부하 프로세스와 동시 |
| load-worker | 4 | 130.204 | PCM oracle + 기존 PERF 3행 |
| over-30-seconds | 1 | 92.543 | 실제 900묶음 확정 앞에 TEMP 전용 32초 지연 |

합계 **11 PASS**, failure/error/skip/경고 0이다. 고정 지연은 R7의 별도 pytest plugin `g04_fix6_delay.py`에만 있고 제품·CI 시험에는 없다. 전체 회귀를 새로 실행한 수치가 아니다. 관리 ≥50ms 이력은 모든 정상 실행에서 0건이다.

| 실행 | 동작 | 관리 시간(초) | 관리 root 최대(ms) | 전체 root 최대(초) | 거부 블록 | 유실 frame |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| repeat-1 | 목록 | 5.798155 | 1.155 | 1.159693 | 0 | 0 |
| repeat-1 | 확정 | 19.033938 | 13.364 | 1.041765 | 144 | 69120 |
| repeat-1 | 복구 | 9.522084 | 3.684 | 1.122028 | 0 | 0 |
| under-load | 목록 | 7.292192 | 1.609 | 1.244671 | 0 | 0 |
| under-load | 확정 | 23.363396 | 4.254 | 1.239644 | 174 | 83520 |
| under-load | 복구 | 11.704887 | 2.066 | 1.186736 | 24 | 11520 |
| 32초 인위 지연 | 확정 | 51.290560 | 3.970 | 0.962786 | 0 | 0 |

32초 지연 행에서는 관리 작업 완료까지 합성 **2,486,400frame**을 제출했고 같은 수가 저장됐다. 30초를 넘긴 후에도 제출을 계속했다는 직접 관측이며 원본 보존·유실 0의 일반 보장으로 확대하지 않는다. 다른 실행의 유실은 위 표에 그대로 기록했고, 긴 writer 보유는 G-P15와 구별한다. 부하 프로세스의 별도 측정도 R7/load-worker-bt의 `measurement.json`에 보존했다.

추가 대조로 별도 TEMP 사본에서 옛 `index < 3000` 조건만 복원했다. 동일 32초 plugin과 실제 900묶음 입력에서 **`assert 3000 < 3000`으로 1 FAIL / 75.818초**, 수집/error/skip 0이다(`old-window-control.xml/log`). 지연 전 fixture 생성과 실패 후 reader/writer 정리가 포함된 총 시간이며, 300초 상한 실패로 오인하지 않는다. 새 조건의 51.29초 성공과 옛 조건의 실패를 대조했다. 기존 mutex oracle은 변경하지 않았으므로 FIX5의 변이·검토 증거도 이력으로 유지한다.

R7/run.py·results.json에 실제 명령과 import 위치를, 각 실행 XML/log와 basetemp에 관측을 남겼다. 최종 `implementation-files.json`과 `final-audit.json`은 G-P06 29파일 불변·G04 나머지 8파일 불변·사본의 비소유 추적 파일 차이 0을 대조한다. G04-12의 작성자 조치와 FIX6의 독립 재확인은 C00에게 넘기고 G-P06을 재개한다.

| 증거(R7 기준) | SHA256(LF, CR 제거) |
| --- | --- |
| repeat-1.xml | `e4bcf4fa588cd48aeeb7f72135c6bb7ffbd2023d20c43838fade8595299042c9` |
| under-load.xml | `20f3cbb364866cd28787901f97e2e28e0811d537d0fb44d4855a1f0cdc37b59e` |
| load-worker.xml | `eeb8ce86afa765489267d6d92031ce139c4a46932f61f375d1901f6ff912f70a` |
| over-30-seconds.xml | `ac0085fd6b2cab1eb1048c27c513044241c40c6ba683b950f64e0de080e9918d` |
| old-window-control.xml | `73d47e51808d7904b757dbac571c168413d74a584828b632410a1df1d336bfb1` |
| results.json | `338e303b7ae840cb56487964c4b1759e9dbdd10002ca4c1c436c85c08bec8d85` |

## 17. GT-P03 / GT03 — live 반복 거부 시험의 수락 회계

C00이 CI run45129655909의 core3.11/3.13 실패를 GT-P03으로 배정했다. 저장한 원문 `build/ci-evidence/g04-core3.11.log`에서 recover/finalize의 `rejected == 0`이 각각 3/4로 실패했고 나머지 9545건은 PASS, 3.13 원문에서는 finalize가 38로 실패하고 나머지 9546건은 PASS였음을 직접 대조했다. 이는 사용자 로그 사본의 관측이며 실제 GitHub runner를 여기서 재실행한 것은 아니다. 공격적 `chunk_frames=480`과 300회·10ms 제출은 유지한다.

입력 분할은 recover/finalize 2종, 자연 실행/동시 부하, 제출 수락/QUEUE_DROP이다. 기존 의미 행 `G04-F4-LIVE-recover/finalize` **2행**과 독립 writer 방어 행 **1행**을 유지한다. 반복 실행을 새 의미 행으로 세거나 300개 수락/거부 열의 전수 실행으로 부르지 않는다. 별도 TEMP gate는 첫 블록을 writer가 꺼낸 뒤 첫 seal을 300번째 제출까지 대기시켜 기본 큐256에서 수락257·거부43을 강제한다. 이 제어 trace는 새 회계 assertion이 거부0에서만 통과하는지 확인하는 보강이며 제품·CI 시험에는 gate를 넣지 않는다.

독립 oracle은 제출300·frame480·고정 PCM data에서 손계산한다. 거부 R은 측정·출력하고, 수락 N=300−R에 대해 dropped_frames=R×480, 저장 descriptor 수=N, 저장 frame=N×480, 이어 붙인 audio=data×N이어야 한다. health gap의 reason은 모두 QUEUE_DROP이며 합계도 R×480이다. worker 종료, 허용된 live 거부 코드만, ACCEPTED 없음, claim publications=[], writer_error 없음, 종료 전 accepting=True·storage_failed=False는 그대로 검사한다. QUEUE_DROP 자체는 writer seal 지연 **G-P15**의 관측이고, claim 회귀는 publications·writer_error/저장 실패로 판정한다.

기준은 **8e09b62**의 TEMP archive + 지정 시험/문서 두 파일뿐이다. G-P05가 수정 중인 storage/library.py·ui/main.py·cli.py를 작업 트리에서 복사하지 않는다. G-P06 29파일도 hash로 동결한다. 정상 반복·실제 무거운 시험 동시 실행·TEMP gate 보강, 거부 전 live 사전 판정 제거 mutant, writer의 claim 방어를 되돌린 mutant, ruff·format을 확인한 뒤 아래에 실제 결과와 hash를 기록한다.

### 17.1 CI 원문과 판정 범위

두 로그의 실패 위치는 기존 `rejected == 0 and …`의 첫 항이며, 그 뒤 flags·writer_error assertion까지 CI가 통과했다고 해석하지 않는다. QUEUE_DROP 원인 판단은 C00 결정·RECHECK 4의 클릭 없는 대조·RecordingService.submit의 큐 거부 회계 경로에 근거한다. 로컬 제어 trace와 아래 변이로 queue 거부와 claim 오류를 분리했다. 실제 CI 3.11/3.13 재실행은 C00의 후속 검증이며 여기서는 **Windows 로컬 Python3.13.1**로 실행했다.

| 읽은 CI 로그 | SHA256(LF, CR 제거) |
| --- | --- |
| build/ci-evidence/g04-core3.11.log | `bac5c9125bf72163de33fc6a7dcd0de1e9d0ffed06fe16ea55296a2061207e96` |
| build/ci-evidence/g04-core3.13.log | `6bd0b35f9c1aed4ac16c803b392d03ad8266bc32b98daf52faab25da5a430ac5` |

### 17.2 직접 실행 결과

증거 루트 **T=`C:/Users/gangd/AppData/Local/Temp/recoryn-gt03-66n18lq3`**. 착수 전 두 소유 파일은 8e09b62와 LF hash가 같았다. T/isolated는 그 commit archive에 수정한 두 파일만 복사했다. G-P06 변경이나 G-P05 작업 트리를 복사하지 않았으며 제품 코드를 바꾸지 않았다. 실제 import는 각 사본 src로 확인했다.

명령은 절대 Python 경로의 `-B -m pytest <선택 node> -q -s -p no:cacheprovider -W error::ResourceWarning -W error::pytest.PytestUnraisableExceptionWarning --basetemp <T의 실행별 고유 폴더> --junitxml <T의 실행별 XML> --tb=short`다. offscreen·bytecode 억제·HF/transformers offline이며 실제 장치·모델·네트워크·계정·vault 쓰기·설치를 하지 않았다. 실제 전체 인자와 import 경로는 T/run.py 및 실행별 result.json에 있다.

| 실행 | PASS node | JUnit suite 시간(초) | 구성 |
| --- | ---: | ---: | --- |
| normal | 3 | 36.009 | live2 + 독립 writer 방어1 |
| repeat | 2 | 33.690 | 같은 live2 반복 |
| under-load | 2 | 36.330 | 아래 별도 무거운 프로세스와 동시 live2 |
| load-worker | 4 | 136.628 | PCM oracle + 목록7200·확정900·복구900 |
| controlled-drop | 2 | 34.249 | TEMP queue gate + 같은 live2 |

합계 **13 PASS**, failure/error/skip/경고 0이다. 부하 프로세스의 첫 시험 실행 신호를 확인한 뒤 target을 시작했고 target 종료 때도 부하 프로세스가 실행 중이었다. 시간은 subprocess 전체 경과와 구별한 XML의 suite 시간이다. 전체9547건을 다시 돌렸다는 뜻은 아니다.

| live 관측 | 행 수 | 거부 R | 수락 N | dropped/gap frame | descriptor | 저장 frame | 저장 bytes |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| normal/repeat/under-load의 recover·finalize | 6 | 0 | 300 | 0 | 300 | 144000 | 288000 |
| controlled-drop recover | 1 | 43 | 257 | 20640 | 257 | 123360 | 246720 |
| controlled-drop finalize | 1 | 43 | 257 | 20640 | 257 | 123360 | 246720 |

모든 정상 live 관측에서 claim 게시0·writer_error=None·종료 전 accepting=True/storage_failed=False였고 허용된 거부 코드만 있었다. 제어 행의 gap은 QUEUE_DROP 한 구간이며 frame 합20640이었다. health_snapshot의 accepted/dropped와 stop 후 영속 capture_health의 gap을 대조하고 실제 descriptor·frame·이어 붙인 PCM 전체를 손계산한 N과 비교했다. 제어 gate는 T/gt03_queue_gate.py에만 있으며 CI 시험에는 지연이나 큐 크기 변경을 넣지 않았다. 자연 실행에서 이번에 거부0이었던 사실을 CI의 유실0 보장으로 확대하지 않는다.

### 17.3 mutation과 제출

동일 archive를 각 TEMP 사본에 pyproject/src/tests/scripts/packaging과 함께 복사하고 한 결함씩 주입했다. 제품 원본과 G-P05 파일은 수정하지 않았다.

| 변이 | 실제 검출 node | 실패 근거 | 결과 |
| --- | --- | --- | --- |
| A: _admit_session의 live 사전 판정 제거, writer 방어 유지 | G04-F4-LIVE-recover | publications374건, `publications == []` 실패 | KILLED |
| B: live writer도 다른 작업 claim에 막히도록 등록 방어 되돌림 | test_live_writer_admission_has_an_independent_claim_defense | writer_error가 `StateConflict('SESSION_OPERATION_IN_PROGRESS')`, None assertion 실패 | KILLED |

**2/2 KILLED**, survived/invalid/import 오류/timeout 0이다. 정상 목표 선택이 먼저 PASS했으며 위 assertion 실패를 각각 확인했다. T의 diff·results.json·mutation XML/log에 원본/변이 hash와 명령을 보존했다. ruff check·format --check도 PASS다. `final-audit.json`은 비소유 추적 파일의 archive 대비 차이0, G-P06 29파일 불변, 작업 트리/사본 시험 hash 일치를 대조한다.

| GT-P03 변경 시험 | SHA256(LF, CR 제거) |
| --- | --- |
| tests/integration/test_unfinished_recovery.py | `3f64331e31397266cf500f3cd1bf7978a9fbab0d7b1b533bfc61cc53fc1c2bbd` |

이 문서의 최종 hash는 제출 창과 T/implementation-files.json에 기록한다. GT-P03 작성자 검증 결과이며 독립 재확인·원격 CI 재실행은 C00에게 넘긴다. G-P15의 writer seal 개선은 이 단위 밖에 그대로 남는다.

| 직접 증거(T 기준) | SHA256(LF, CR 제거) |
| --- | --- |
| normal.xml | `9f01a55277f77b1e5b0bf88bae01265af14d715a0143f660f15c836090c8d0c5` |
| repeat.xml | `9bcac266164e059a1674e32014ee501420d13280d35fe447e598545f369c84f9` |
| under-load.xml | `ecfddff87d263914bbd1f2f1cf91d0456854de90d76e4f3cdc0985734cab45f0` |
| controlled-drop.xml | `b80a009b3aa844015590695ac59b169c63187dc5690b18ca23c432dffece2f99` |
| load-worker.xml | `fc8f0a739a14e39642f9a0fdaa4e3b43510115ed6bfa40af2da0e1866bfd2b8f` |
| results.json | `e50643bdfc4b1062d7b81840c55010ce080e6150631edd68a79bd0e571d483ce` |

