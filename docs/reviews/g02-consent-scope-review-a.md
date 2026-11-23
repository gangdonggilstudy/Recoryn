# G02-A / G-P02 전송 동의 범위 독립 검토

2026-11-23, 검토자 Claude(C00 배정 독립 검토 A). 작성자는 w5:p8 Codex이며 검토자는 이 단위의 코드·시험·문서를 작성하지 않았다.

**S0/S1 발견 없음. OPEN 8건: S2 4건, S3 4건.** 원 P1(세션 A 동의로 B 전송)은 제품 코어에서 fail closed로 닫혔다. 명시 LIBRARY는 A/B 모두 허용한다. fallback, 철회 뒤 부활, 옛 binding 재사용, 다른 기능·데이터·endpoint, 정책 변경 뒤 옛 계획, 실행 세대 변경, 삭제 fence 우회는 반례를 찾지 못했다. 남은 결함은 UI 상태 관리, 표시, config_key 설계 부작용, GUI 대기와 시험 oracle 품질이다. 모두 전송을 넓히지 않는 방향의 결함이다. 최종 수용과 통합은 C00가 결정한다.

## 1. 입력 고정과 추출

- 검토 tree: **`9c7a0d86ba3962fab9efbe26c3b18790d6a6f4ae`**(`git cat-file -t` = tree). 기준 commit 9d46b4a의 tree는 `044d240ffec01c1b73cdb2be8093dce3a06509e3`이며 작성자 §9.5의 주장과 같다.
- `git diff --stat 9d46b4a 9c7a0d86…` 결과는 **19 files, 4166 insertions / 311 deletions**다. 파일 목록은 §6의 승인 19파일과 같다.
- 추출 위치(작업 트리 판정 없음):
  - 판정·전체 시험용: `git -c core.autocrlf=false archive 9c7a0d86… | tar -x -C build/review-trees/g02-sub-a`
  - 변이용 원본: `git -c core.autocrlf=false archive 9c7a0d86… pyproject.toml src tests | tar -x -C build/review-trees/g02a-pristine`
- 제출 Python 18파일의 LF SHA256을 직접 계산했다. 결과 18/18이 작성자 문서 §9.6 표와 일치한다(`build/review-trees/g02a-hashes.txt`).
- 저장소 쓰기는 이 문서 하나뿐이다. 반례 시험·변이 harness·사본은 `D:/project/Recoryn/build/review-trees/` 아래에만 두었다. Git 쓰기, 설치, 네트워크, 실제 장치·모델, vault 쓰기, 유료 호출과 하위 에이전트는 사용하지 않았다.

## 2. 직접 실행한 명령과 결과

모든 실행에 저장소 `.venv` Python, `QT_QPA_PLATFORM=offscreen`, `HF_HUB_OFFLINE=1`, `-p no:cacheprovider`, 실행별 새 `--basetemp`(`build/review-trees/g02a-bt/*`)를 사용했다.

| # | 명령(cwd) | 결과 |
| --- | --- | --- |
| R1 | `python -m pytest -q -p no:cacheprovider --basetemp …/g02a-bt/full -x` (g02-sub-a) | **9007 passed, 2 skipped, 209.42s, exit 0** |
| R2 | R1 + `PYTHONPATH=g02-sub-a/src`, `PYTHONDONTWRITEBYTECODE=1`, `TRANSFORMERS_OFFLINE=1`, `HF_HUB_DISABLE_TELEMETRY=1`, `--ignore=tests/review_g02a`, `-rs --junitxml …/g02a-full2.xml` | **9009 수집 / 9007 passed / 2 skipped / failure 0 / error 0, 206.87s, exit 0** |
| R3 | `pytest -rs tests/release/test_gpu_smoke.py` | 2 skip은 모두 `test_gpu_smoke.py:107: this volume does not create 8.3 names` |
| R4 | `pytest --co -q` 새 시험 4파일 (g02a-pristine) | **984 node**(고유 984), parametrize ID 978개 고유 |
| R5 | `ruff check --no-cache src tests` / `ruff format --no-cache --check` 18파일 / `mypy --cache-dir … src/recoryn` | All checks passed / 18 files already formatted / **70 source files no issues** |
| R6 | 반례 `tests/review_g02a/test_g02a_probes.py` 12 node (g02-sub-a, `PYTHONPATH` 고정) | **7 failed(반례), 5 passed(확인)** |
| R7 | `python -I build/review-trees/g02a-mutate.py` (사본별 1변이) | baseline 1309 passed. 12변이 중 **10 KILLED, 2 SURVIVED**, invalid 0 |

R2는 subprocess 시험이 작업 트리 `src`를 import하지 않도록 `PYTHONPATH`를 고정해 다시 실행한 것이다. 이 venv의 editable `.pth`가 `D:\project\Recoryn\src`를 가리키므로 R2를 정본 결과로 삼는다. 작성자의 9009 passed/skip 0과 다른 점은 2건의 8.3 이름 skip뿐이다. 이 skip은 추출 위치가 8.3 이름을 만들지 않는 D: 볼륨이기 때문에 생겼고 G-P02와 무관하다. 작성자는 C: TEMP에서 실행했다.

R4의 분포는 FROZEN 504, HB 180, TIME 72, MIG 12, TYPE 22, UI-ACTION 144, UI-CANCEL 12, UI-SNAPSHOT 24, UI-DEFAULT 2다. 그 밖에 loop node 4개(GATE/PICK/BIND/TRACE), manifest 1개, 원 P1 1개, bridge 2개, 만료 보강 4개가 있다. 합계 984로 작성자의 §9.2 주장과 같다.

증거 파일의 LF SHA256은 다음과 같다. probe `01c1823a54ade313d7cd90ab4099195632a1c6b392972bbff383de4875528181`, harness `16d0f4c75d1f7cca8540fd01010535fcb8467906a21d7f337889610b4ae861ac`, 변이 결과 `build/review-trees/g02a-mutations.json` `8d0543508a078ee9ace941676b093a0dbafea0bf343c08beda24fdcf5c02e024`.

### 변이 결과(R7)

작성자 diff를 재사용하지 않았다. 같은 의도의 변이를 검토자가 직접 작성했다. 각 사본에서 `consent.__file__`/`privacy.__file__`가 사본 `src`를 가리키는지 확인했다.

| ID | 변이(검토자 작성) | 결과 / 첫 실패 node |
| --- | --- | --- |
| M01 | `_grant`의 SESSION ID 비교를 `False`로 | KILLED, `test_authorization_case_space` |
| M02 | SESSION 행이 없거나 철회됐으면 LIBRARY 행으로 fallback | KILLED, `test_selected_scope_case_space` |
| M04 | `_grant`의 요청 정책 비교 제거 | KILLED, `HB-015` |
| M08 | `validate`에서 LIBRARY이면 삭제 fence 생략 | KILLED, `HB-096` |
| M12-confirm | LIBRARY 확인 창 생략 | KILLED, `UI-CANCEL-00` |
| M17 | STT `prepare_execution`에 fixed_session 대신 화면 선택 사용 | KILLED, `bridge…[stt]` |
| X06 | `permit`의 expected_grant 대조 제거 | KILLED, `FROZEN-009` |
| X29 | privacy가 SESSION capture 실패 시 LIBRARY로 재capture(UI 계층 fallback) | KILLED, `UI-ACTION-056` |
| X30 | Store key에서 data_type 상수화 | KILLED, `test_selected_scope_case_space` |
| X09f | `for_session` 재바인딩 검사 제거, `-x` 없이 전수 | KILLED(192 failed/312 passed). **first 경계 96행은 모두 PASS** → G02A-07 |
| X20 | "전체 허용 유지 중" 표시 줄 제거 | **SURVIVED**(tests/ui 237 passed) → G02A-04 |
| X21 | 범위 정보의 만료 표시 제거 | **SURVIVED**(tests/ui 237 passed) → G02A-04 |

작성자의 22변이 중 6개(M01·M02·M04·M08·M12-confirm·M17)를 독립 재현했다. 실패 node는 작성자 표와 같거나 인접한 행(M08: 작성자 HB-097, 검토자 HB-096)이다. 나머지 16개는 재실행하지 않았다.

## 3. 발견 사항

### G02A-01 / S2 / OPEN — 같은 세션의 목록 갱신만으로 LIBRARY 선택이 SESSION으로 초기화된다

- **재현**: `test_defect_refresh_same_session_resets_library_scope`. 실제 `DesktopAI.attach_privacy`와 실제 `PrivacyPanel`을 쓰고, `ui/main.py:378-386`의 `refresh_sessions`(clear → 재추가 → 같은 A를 `setCurrentItem`)를 그대로 흉내 냈다. 순서: A 선택 → LIBRARY 선택 → 확인 Yes → LIBRARY grant 활성 → 새 세션 R은 `prepare_execution("stt","R")` 성공 → 같은 A로 refresh.
- **실제**: refresh 뒤 선택이 `('session', 'CONSENT_REQUIRED')`다. 콤보가 SESSION으로 돌아가 R 작업이 SESSION(R)을 요구하고 거부된다.
- **기대**: `('library', 'allowed')`. 계약 §2.4는 "동일 ID의 중복 통지는 idempotent하게 처리해 전체 범위 선택을 매번 초기화하지 않는다"고 정한다.
- **원인**: `QListWidget.clear()`가 `currentItemChanged(None)`을 보낸다. 이 신호가 `ai_bridge.py:106-108` 람다를 거쳐 `select_session(None)`을 부르고, `privacy.py:243-245`가 scope를 index 0으로 바꾼다. 이어 A가 다시 들어오므로 `privacy.py:238`의 "직전과 같은 ID" 비교는 효과가 없다.
- **영향**:
  - `refresh_sessions`는 녹음 시작(`main.py:346`), 일시정지·재개(359), 정지(374), 절전(254), 복구(416), 삭제 결과(479)와 새로고침 버튼(165)에서 호출된다.
  - 확인 창이 "현재·새 세션 전체"라고 고지한 LIBRARY grant가 녹음 시작 직후 새 세션의 실시간 전사에 쓰이지 않는다. 그 세션은 `_live_blocked`(`ai_bridge.py:155-156`)로 막혀 명시 재개가 필요하다.
  - fail closed이므로 무동의 전송은 아니다.
- **설계 참고(C00 결정)**: 승인된 "세션 전환 시 기본값 복귀"는 그대로다. 그래도 실시간 전사는 provisional 준비 때마다 현재 콤보 값을 읽는다(`ai_bridge.py:704`→`148`, `privacy.py:428`). 그래서 사용자가 다른 세션을 보기만 해도 녹음 중 세션의 LIBRARY 계획이 끊긴다. 고정 대상은 세션만이고 범위는 고정되지 않는다.
- **수정 제안**: (a) `refresh_sessions`가 재구성 동안 신호를 막고 마지막에 한 번만 통지한다. `ui/main.py`는 19파일 밖이므로 재배정이 필요하다. 또는 (b) privacy가 None 뒤 같은 ID가 다시 오면 선택을 보존한다. 실시간 전사 stream은 시작할 때 범위를 고정하는 방안도 C00 결정 대상이다. 실제 refresh 순서를 쓰는 회귀 시험을 추가한다.

### G02A-02 / S2 / OPEN — `select_session`의 `bind_session` 예외가 세션 선택 처리를 중단한다

- **재현 1**: `test_defect_selection_of_revoked_session_aborts_ui_update`. 목록에 A, C가 있고 A를 선택한 상태에서 `revoke_session("C")`를 실행한다. 이는 `before_delete`가 끝났지만 삭제가 실패해 C가 목록에 남은 상황이다. 이어 `bridge.selection("C")`를 호출한다.
  - **실제**: `SESSION_REVOKED`가 전파된다. `panel.load("C")`와 상세 갱신이 실행되지 않는다. privacy는 `_selected_session='A'`, 표시 `이 세션만: A …`를 유지한다. 이때 허용 버튼을 누르면 **SESSION(A) grant가 생긴다**(`granted_for_A=True`). 화면에서 강조된 행은 C다.
- **재현 2**: `test_defect_pending_deletion_tmp_blocks_selection_of_other_session`. `deletion-journal/.tmp-*`가 있으면(다른 세션의 `atomic_json` 진행 중, `storage/_safe.py:200`) 무관한 B 선택도 같은 방식으로 실패한다.
- **기대**: 세션 표시는 계속 갱신된다. 철회·삭제 중인 세션은 privacy에서 "선택 없음/철회됨"으로 표시하고 동의·전송만 비활성화한다. 이전 세션을 대상으로 남기지 않는다.
- **원인**:
  - `privacy.py:240-242`는 상태를 갱신하기 전에 `bind_session`을 부른다(`consent.py:585-586`, `602-613`).
  - `ai_bridge.py:116-119`는 `panel.load`보다 먼저 privacy를 호출한다.
  - `main.py:392-398`은 `ai_bridge.selection` 뒤에 상세를 갱신한다.
- **발생 경로**: `main.py:452-459`는 먼저 철회하고 나서 `delete_session`을 부른다. 의도 기록 전에 실패하면 세션이 목록에 남는다. 원인은 `_deletion_intents` ValidationError, `atomic_json` OSError, `recorder.close` 실패 등이다. `list_sessions`는 의도 파일이 있는 세션만 숨긴다(`library.py:203-212`).
- **회귀 여부**: 9d46b4a의 `selection`은 `panel.load`만 호출했다. 이번 단위가 만든 회귀다. 전송은 C의 bind/permit에서 계속 차단된다. 동의 UX에서는 grant가 이전 세션에 붙을 수 있다.
- **수정 제안**: 선택 경로에서 `SecurityError`를 잡는다. 그 경우 `_selected_session`을 None 또는 비활성 상태로 바꾸고 scope 초기화와 label 갱신을 수행한다. 등록(bind)은 `prepare_execution`에서만 한다. bridge는 privacy 실패와 무관하게 `panel.load`를 수행한다.

### G02A-03 / S3 / OPEN — 철회됐거나 이전 실행의 비활성 grant에 "만료 <시각>"을 표시한다

- **재현**: `test_defect_scope_info_shows_expiry_for_revoked_grant`는 SESSION(A) 허용 뒤 철회 버튼을 누른다. `…_previous_run_grant`는 이전 Store에서 발급한 뒤 새 Store와 Panel로 재시작한다.
- **실제**: 두 경우 모두 `이 세션만: A / 기능 stt / 정책 version 2 / 현재 실행만 / 만료 2026-11-23T02:07:48+00:00`이다. `allowed`=False이고 `grant_info.active`=False다.
- **기대**: 활성 grant에만 만료를 표시한다. 그 밖에는 "철회됨", "이전 실행 — 다시 동의 필요", "만료됨"을 표시한다.
- **원인**: `privacy.py:289` `if info:`가 `info["active"]`를 확인하지 않는다.
- **수정**: `if info and info["active"]`로 바꾸고 비활성 사유를 표시한다.

### G02A-04 / S3 / OPEN — 범위 정보 label의 만료·전체 잔여 표시를 검증하는 assertion이 없다(문서 주장과 불일치)

- **근거**: `scope_info`에 대한 assertion은 `"정책" in text`뿐이다(`tests/ui/test_consent_scope_ui.py:252-254`). "만료"는 확인 창 본문에서만 검사한다(같은 파일 220행). 변이 X20(전체 허용 유지 표시 제거)과 X21(만료 표시 제거)이 tests/ui 237건 PASS로 **SURVIVED**했다.
- **기대**: 문서 §3.8은 "label·accessible name·현재 범위/만료/정책·전체 잔여 grant 표시도 assertion에 포함한다"고 주장한다. §1은 이 표시의 누락을 S2로 분류한다.
- **수정**: 세션 ID 표시, 활성 grant에만 붙는 만료, LIBRARY 잔여 표시, G02A-03의 비활성 사례를 assertion으로 추가하고 X20/X21을 검출하게 한다.

### G02A-05 / S2 / OPEN(계약 결정 필요) — config_key에 동의 범위·정책을 넣어 이미 처리한 실시간 청크를 재전송한다

- **재현**: `test_defect_scope_in_config_key_resends_processed_live_chunks`.
  - provider·모델·endpoint·한도가 같아도 SESSION과 LIBRARY의 `prepare_execution(...).config_key`가 다르다.
  - 실제 `AIService`+`RecordingService`+합성 PCM과 fake STT로 실행했다. 첫 provisional 작업은 SESSION 키로 1청크를 보냈다. 두 번째 작업은 LIBRARY 키로 **2청크(기존 1 + 신규 1)를 다시 보냈다.**
  - 같은 키를 쓴 대조군은 신규 1청크만 보낸다(`[True]` PASS).
- **원인**:
  - `privacy.py:397-425`가 `scope.kind/scope_id/version`을 config_key에 넣는다.
  - 이 키는 `app/ai.py:219`(admission 키), `224-236`(stream checkpoint 일치), `476`(요약 checkpoint 재개), `500-504`(G-P03 settings_key, admission)에서 쓰인다.
- **영향**:
  - 동의된 데이터의 중복 원격 처리와 중복 비용이 생긴다. S0은 아니다.
  - G02A-01로 범위가 바뀐 뒤 SESSION 동의로 이어 가면 지금까지의 청크를 다시 보낸다.
  - 요약 checkpoint 재개가 사라진다.
  - 결과가 같은 설정도 G-P03의 다른 settings로 취급된다(후보/선택 판정).
- **계약 관계**: §2.4 96행이 "config_key에 … 선택 범위·정책 … 포함"을 승인했으므로 이 결함은 승인 계약의 부작용이다. 같은 문단은 "grant ID/epoch 검증은 binding이 담당"한다고 적었다. 보안상 config_key에 범위를 넣을 필요는 없다.
- **수정 제안**: 결과·checkpoint 식별(config_key)은 provider/model/endpoint/한도/기능(+세션)으로 한정한다. 범위·정책은 동의 snapshot에만 둔다. 계약 문구 변경이므로 C00가 결정한다.

### G02A-06 / S2 / OPEN — 세션 목록 이동·갱신이 GUI thread에서 consent coordinator를 기다린다

- **재현**: `test_defect_session_selection_waits_for_inflight_network_write`. worker thread의 `Gateway._write` 안에서 fake write가 멈춘 상태로 GUI thread가 `sessions.setCurrentItem(B)`를 호출한다.
- **실제**: watchdog가 0.5초 뒤 write를 풀어줄 때까지 반환하지 않았다(`elapsed 0.503`, `forced True`). watchdog가 없으면 write timeout(기본 최대 30초)까지 기다린다.
- **기대**: 목록 탐색·표시는 원격 write를 기다리지 않는다. coordinator 문서는 "slow network call can delay policy commands"라고 적었지만 세션 선택은 정책 명령이 아니다.
- **원인**:
  - `select_session` → `bind_session`(`consent.py:580`)과 `_show_scope` → `policy_version`/`grant_info`(`consent.py:248`, `494`)가 `coordinator.hold()`를 잡는다.
  - `gateway.py:282-296`은 `connection.write` 동안 같은 coordinator를 유지한다.
- **회귀 여부**: 9d46b4a의 선택 경로는 consent를 읽지 않았다. 비슷한 경로가 원래도 있었다(live tick → 준비 → capture). 이번 단위는 그 범위를 일반 탐색과 녹음 시작·정지 뒤 refresh까지 넓혔다.
- **수정 제안**: 선택 때 bind하지 않는다. 표시 정보는 비차단으로 갱신한다(try-acquire 실패 시 "확인 중", 또는 worker 조회 후 GUI 반영). 준비 단계만 coordinator를 잡게 한다.

### G02A-07 / S3 / OPEN — FROZEN의 first 경계 96행은 재바인딩 허용 결함을 검출하지 못하는 oracle이다

- **재현**: 변이 X09f(`gateway.py:93-99`의 재바인딩 검사 제거)를 전수 실행했다. change∈{1,2,5,6} × first 96행이 **전부 PASS**했고 reserve/open 192행만 FAIL했다(`g02a-mutations.json`의 `failed_ids`를 행으로 복원해 집계).
- **원인**: first 경계에서는 `attempt()`가 패치된 `_write` 안에서 실행된다. `for_session`이 변경을 받아들여 테스트가 `AssertionError`를 던져도, `Gateway.request`의 `except Exception`이 그 오류를 `SecurityError("TRANSPORT_FAILED")`로 바꾼다. 그래서 `pytest.raises(SecurityError)`가 그대로 통과한다.
- **영향**: M09 계열은 다른 행이 잡는다. 하지만 §3.4/§9.2의 "504행 모두가 재지정 거부를 관측"이라는 의미는 과장이다.
- **수정**: attempt 결과를 Gateway 밖의 리스트에 기록하고 `PERMIT_REVOKED` 등 기대 코드를 직접 비교한다. AssertionError가 변환되지 않게 한다.

### G02A-08 / S3 / OPEN — 만료 시각을 UTC로 표시한다

- **근거**: 범위 정보(`privacy.py:290-292`)와 LIBRARY 확인 창(`privacy.py:303`)이 `datetime.fromtimestamp(…, UTC).isoformat()`을 쓴다. 예: `2026-11-23T02:07:48+00:00`. 한국 사용자가 보는 벽시계 시각과 9시간 다르다. 오프셋은 표시하므로 오해 가능성이 낮아 S3로 분류했다.
- **수정**: 로컬 시간대와 오프셋을 함께 표시한다. 확인 창과 label에 같은 형식을 쓴다.

## 4. 관점별 확인 근거

1. **P1과 우회**
   - **실행**: 작성자 원 P1 node가 R2에서 PASS했다. 검토자 `test_check_consent_core_bypass_attempts` PASS로 다음을 확인했다.
     - SESSION(A) grant로는 B에 대한 binding이 SESSION(A)·LIBRARY 어느 표시로도 생기지 않는다.
     - SESSION(A) 범위에 요청 B를 넣은 위조 `ConsentBinding`은 `validate_binding`과 Gateway에서 거부된다.
     - A 철회 뒤 LIBRARY를 발급해도 옛 SESSION 계획은 부활하지 않는다(fallback 없음). 같은 키를 재동의해도 `PERMIT_REVOKED`다.
     - 다른 기능(summary/diarization)·데이터·endpoint는 두 범위 모두 불허다.
     - 정책 3 증가 후 새 정책 LIBRARY grant가 있어도 옛 계획은 `CONSENT_POLICY_CHANGED`다.
     - `revoke_session(B)`는 B의 LIBRARY 요청을 막고 `bind_session(B)`로 재활성화되지 않는다. A는 유지된다.
     - 재시작 뒤 LIBRARY는 소멸한다.
   - **코드**: `consent.py:452-460`(SESSION ID·allowed·세대·만료·local proof)과 `_policy`, 정확한 7열 key, `_session` 재검사(allowed/capture/validate_binding/permit/validate)를 읽었다.
   - **변이**: M01/M02/M04/M08/X06/X29/X30이 KILLED됐다.
2. **S0**
   - 새 무동의 경로를 찾지 못했다.
   - Gateway는 `_request/_scope`와 비어 있지 않은 expected_grants를 요구한다(`gateway.py:196-208`). `permit`은 expected binding과 현재 행 전체를 대조한다. 연결 전·각 write·최종 반환에서 `validate`가 범위·요청·세션 fence를 다시 검사한다(`consent.py:626-679`, `gateway.py:225-256`, `282-296`).
   - 예약 closure는 `validate_binding` 뒤에만 `ledger.reserve`를 호출한다(`privacy.py:505-510`).
   - `src`의 Gateway 생성은 `privacy.py:549` 하나이고 CLI에는 원격 전송 경로가 없다(grep).
3. **UI**
   - 기본값이 SESSION이고(`privacy.py:102-104`) 세션 전환 시 기본값으로 돌아간다.
   - LIBRARY 확인 창 본문은 현재·새 세션, 현재 실행, 만료, 기능, 데이터, endpoint, 정책 version을 보여준다(코드 + UI-ACTION assertion).
   - **실제 QMessageBox에 Esc와 Enter(기본 No)를 키 입력으로 보낸 검토자 시험이 PASS했고 grant는 0건이다.** 작성자의 UI-CANCEL "escape" 행은 `question`을 Cancel 반환으로 대체한 모의 시험이라, 검토자 실키 시험으로 보강 확인했다.
   - fixed_session 사용은 `ai_bridge.py:142,148`과 M17 KILLED로 확인했다. 요약은 `prepare_execution`을 한 번만 사용한다.
   - 결함은 G02A-01·02·03·06·08이다.
4. **회귀**
   - 철회 양순서(HB 180과 기존 `test_gateway`/`test_egress_independent` 노드), UNKNOWN 보존(HB의 `unknown_exposure` 단언), consent→ledger→owner 순서(`gateway.py:209-230`, `282-296` 무변경 구조)가 R2에서 모두 PASS했다.
   - 로컬 경로는 검토자 `test_check_local_paths` PASS로 확인했다. faster-whisper는 grant와 Gateway가 필요 없다. Ollama loopback은 proof가 있어도 grant가 없으면 `CONSENT_REQUIRED`이고, 허용 뒤 ledger는 None이며 B는 거부된다.
   - 기존 9파일의 assertion 줄은 제거/추가 수가 대응한다(`git diff`로 집계). 옛 3인자 호출을 새 명시 문맥으로 바꾼 적응이며, 약화된 기대값은 찾지 못했다.
5. **분모와 oracle**
   - 실제 node 984와 parametrize 분포가 주장과 같다(R4). GATE 9216(허용 9), PICK 288(108), BIND 576(96), TRACE 7381(재시작 가지 820)은 loop 안 assertion으로 확인된다.
   - **주의 1**: GATE/PICK/BIND의 registry ID는 `range`로 만든 문자열이다. manifest 검사는 그 목록의 길이만 대조하므로 동어반복이다. 실질 증거는 loop 안의 `len(seen)`/허용 수 assertion이다. TRACE만 실제 관측 ID 집합을 대조한다.
   - **주의 2**: GATE의 provider/endpoint/data 불일치 축은 Store에 닿기 전에 Gateway binding 조회(`gateway.py:198-208`)에서 거부된다. 정책 축은 capture에서 거부된다. Store key의 data_type 보호는 X30이 PICK에서 KILLED되어 확인됐다.
   - 기대값은 손으로 쓴 predicate·표·정수 모델이며(GATE 228-238행 predicate, PICK oracle 표, TRACE `_model_live`) 제품 helper를 쓰지 않는다.
   - 작성자 변이 6개 독립 재현은 KILLED, 검토자 추가 변이는 4 KILLED·2 SURVIVED(G02A-04)다. FROZEN 공허 행은 G02A-07이다.
6. **전체 시험**: R2 기준 9007 passed / 2 skipped(환경) / failure·error 0이다.

## 5. 미검증·한계

- 실제 `MainWindow` 전체가 아니라 `main.py`의 신호 연결과 `refresh_sessions` 순서를 그대로 재현한 fake window로 확인했다(G02A-01·02·06). 실제 Windows 장치·네트워크·vault·Ollama·모델은 사용하지 않았다.
- 작성자의 나머지 16변이, 작성자 변이 script와 JSON, 60초 시간 예산은 재실행하지 않았다. 참고로 baseline 1309 node는 45초였다.
- mypy는 `src/recoryn` 70파일만 검사했다(작성자는 scripts/packaging 포함 83파일).
- 무제한 식별자 공간, 깊이 4를 넘는 이력, 실제 GUI 접근성 도구 호환은 이번 검토의 보장 범위가 아니다.

## 6. 결론

**G02-A REVIEW_READY / OPEN 8 (S0 0 / S1 0 / S2 4 / S3 4).**

- S2: G02A-01(refresh 시 LIBRARY 선택 초기화), G02A-02(철회 세션 선택 예외로 UI 갱신 중단·이전 세션 유지), G02A-05(config_key 범위 포함으로 청크 재전송, 계약 결정 필요), G02A-06(선택 경로의 GUI 대기)
- S3: G02A-03(비활성 grant 만료 표시), G02A-04(표시 assertion 부재), G02A-07(FROZEN first 공허 행), G02A-08(UTC 표시)

## RECHECK — 2026-11-23, 같은 검토자(Claude, G02-A)

C00의 재확인 요청에 따라 같은 검토자가 1차 원 반례로 다시 확인했다. 위 1차 내용은 이력으로 보존한다.

**요약: G02A-01~08 모두 RECHECKED. 재확인 중 새 S3 4건(G02A-09~12)을 찾았다. OPEN 4 (S0 0 / S1 0 / S2 0 / S3 4).** 새 항목은 모두 전송을 넓히지 않는 방향(fail closed·표시·분류)의 결함이다. G02A-12는 1차 tree에도 있던 결함을 1차 검토에서 놓친 것이며, 이번 수정이 만든 결함이 아니다.

### R-1. 입력 고정

- 대상 tree는 **`8f71d9eebab1c414cd488b714483ca9a87d716e7`**(`git cat-file -t` = tree)다. `git diff --name-only 7ffc8dc 8f71d9ee`로 G-P02 승인 19파일만 바뀌었음을 확인했다.
- 1차 tree 대비 G-P02 변경은 `git diff 9c7a0d86 8f71d9ee -- src tests docs/testing/g02-consent-scope-cases.md`로 보았다. 출력의 `tests/e2e/test_ai_workflow.py`는 HEAD 커밋 21a58bf(GT-P02)에서 온 차이이며 G-P02 파일이 아니다.
- 추출은 `git -c core.autocrlf=false archive 8f71d9ee… | tar -x -C build/review-trees/g02-sub-a2`(판정·전체 회귀)와 `… pyproject.toml src tests | tar -x -C build/review-trees/g02a2-pristine`(변이)로 했다.
- Python 18파일의 LF SHA256은 문서 §10.6과 **18/18 일치**한다(`build/review-trees/g02a2-hashes.txt`).

### R-2. 직접 실행 결과

| # | 명령 | 결과 |
| --- | --- | --- |
| RR1 | 전체 오프라인 회귀(cwd g02-sub-a2, `PYTHONPATH=g02-sub-a2/src`, `PYTHONDONTWRITEBYTECODE=1`, offscreen, HF/transformers offline·telemetry 차단, 새 basetemp, `-rs --junitxml …/g02a2-full.xml`) | **9039 수집 / 9037 passed / 2 skipped / failure 0 / error 0, 212.27s, exit 0** |
| RR2 | 새 시험 4파일 `--co` | **1014 node**(작성자 주장과 같음) |
| RR3 | `ruff check --no-cache src tests` / 18파일 `ruff format --check` / `mypy src/recoryn` | PASS / 18 files already formatted / 70 source files no issues |
| RR4 | 1차 반례 12 node(`test_g02a_probes.py`, LF SHA256 `01c1823a…` 1차와 동일, **무수정**) | **10 passed, 2 failed**. 실패 2건은 config_key 반례의 사전조건 `key_session != key_library`가 수정으로 거짓이 된 것이다(아래 G02A-05) |
| RR5 | 재확인 반례 `test_g02a_recheck.py`(LF SHA256 `21fb1f84e1198c56ffde0f46c5f2a59896ab9e6e92e25b13ecef643189f18507`) 11 node | **6 passed(v2·확인), 5 failed(새 반례 G02A-09~12)** |
| RR6 | `python -I build/review-trees/g02a2-mutate.py`(harness LF `b074455c…`, 결과 `g02a2-mutations.json` LF `3b1002da06df36f736ddabe524b2fc35e22b244bcf995a66995df052842b5259`) | baseline 771 passed, **변이 11/11 KILLED**, invalid 0 |

RR1의 2 skip은 1차와 같이 `test_gpu_smoke.py:107`(D: 볼륨의 8.3 이름 미생성)이다. 작성자의 9039 PASS/skip 0과의 차이는 이 환경 skip뿐이다. 반례 파일은 전체 회귀 수집이 끝난 뒤 복사해 RR1에 섞이지 않았다(JUnit에서 0건 확인).

RR6 변이 목록(모두 검토자 작성, 모두 KILLED):

| ID | 변이 | 첫 실패 node |
| --- | --- | --- |
| X09f | `for_session` 재바인딩 검사 제거, 전수 실행 | 288 failed. **재바인딩 4종 × reserve/open/first 각 96행 전부 FAIL**, 나머지 216행 PASS |
| X20 | "전체 허용 유지 중" 표시 제거 | `UI-FIX-12` |
| X21b | 활성 만료 표시 제거 | `UI-FIX-12` |
| X21c | 만료 표시를 UTC로 되돌림 | `test_library_confirmation_freezes_expiry[stt-1800]` |
| N1 | `select_session`에서 항상 기본값 복귀 | `UI-FIX-00` |
| N2 | bridge의 None 지연 처리 제거(즉시 `select_session(None)`) | `UI-FIX-00` |
| N3 | `scope_view`의 비차단 lock을 차단 acquire로 | `UI-FIX-20` |
| N5 | config_key에 범위 종류를 다시 추가 | `UI-FIX-22` |
| N6 | `scope_view`가 철회(allowed=0)를 무시 | `UI-FIX-13` |
| N7 | `select_session`에서 `bind_session` 재도입 | `UI-FIX-00` |
| N8 | `scope_view`의 삭제 의도(journal) 검사 제거 | `UI-FIX-07` |

### R-3. G02A-01~08 판정

- **G02A-01 / RECHECKED**: 1차 반례 `test_defect_refresh_same_session_resets_library_scope`가 PASS다. 같은 A로 refresh한 뒤에도 `library`가 유지되고 R 준비가 허용된다. 선택 행이 첫 행이 아닌 순서와 마지막 행인 순서도 확인했다(`test_new_refresh_preserves_library_regardless_of_row_order[selected_first/last]` PASS). N1·N2가 KILLED됐다. 1차의 설계 참고(실시간 전사 stream이 시작 시 범위를 고정하지 않고, 사용자가 다른 세션으로 실제 이동하면 LIBRARY가 기본값으로 돌아감)는 C00의 "실제 변경 시 복귀" 결정으로 유지되며 OPEN으로 세지 않는다.
- **G02A-02 / RECHECKED**: 1차 반례 2건이 PASS다. 철회된 C를 선택하면 예외 없이 `panel.load("C")`가 실행된다. privacy 대상은 C이고 표시는 `이 세션만: C / 기능 stt / 삭제 진행 중 — 전송 불가`이며, 허용 클릭으로 SESSION(A) grant가 생기지 않는다(`granted_for_A=False`). `.tmp-` 상황의 B 선택도 예외 없이 로드된다. N7·N8이 KILLED됐다.
- **G02A-03 / RECHECKED**: 1차 반례 2건이 PASS다. 철회는 "철회됨", 이전 실행은 "이전 실행"으로 표시되고 "만료 "는 표시하지 않는다. N6이 KILLED됐다.
- **G02A-04 / RECHECKED**: X20·X21b가 `UI-FIX-12`에서 KILLED됐다. 1차의 SURVIVED 2건이 해소됐다.
- **G02A-05 / RECHECKED**: 1차 반례는 사전조건에서 실패한다. 같은 설정의 SESSION/LIBRARY config_key가 이제 같기 때문이며, 이것이 수정 내용이다. 같은 절차를 새 계약에 맞춘 `test_v2_config_key_ignores_scope_and_live_chunk_is_not_resent`가 PASS다. 실제 `AIService`+`RecordingService`+합성 PCM에서 두 번째 provisional 작업은 신규 1청크만 보냈다(`first_calls 1, second_calls 1`, 1차는 2). N5가 KILLED됐다. §2.4의 C00 계약 수정 문구도 확인했다. 부작용 점검은 R-5에 적었다.
- **G02A-06 / RECHECKED**: 1차 반례 `test_defect_session_selection_waits_for_inflight_network_write`가 PASS다(`forced False, elapsed 0.0`). 원격 write가 coordinator를 잡은 동안에도 목록 선택이 즉시 반환한다. N3가 KILLED됐다.
- **G02A-07 / RECHECKED**: X09f에서 first 경계 96행이 모두 FAIL로 바뀌었다(1차는 전부 PASS). 재바인딩 결과를 Gateway 예외 경계 밖에서 `["PERMIT_REVOKED"]`로 비교하도록 바뀌었다.
- **G02A-08 / RECHECKED**: 범위 정보가 `만료 2026-11-23T11:51:02+09:00`처럼 현지 오프셋으로 표시된다(RR5 출력). X21c가 KILLED됐다.

### R-4. 새 발견

#### G02A-09 / S3 / OPEN — 선택 때 bind하지 않아 비발급 동작 뒤 상태 문구가 활성 grant와 모순된다

- **재현**: `test_new_status_after_refresh_action_matches_active_grant`. A 선택 → 허용 → "비용 갱신" 클릭.
- **실제**: 상태가 `거부됨 — 실행 대상 세션과 범위를 확인하세요`다. 같은 시점 범위 정보는 `… / 만료 2026-11-23T11:51:02+09:00`(활성)이다.
- **원인**: G02A-06 수정으로 `select_session`이 `bind_session`을 호출하지 않는다. 그런데 `_action`의 grant 외 분기(revoke/save/delete/budget/settle/refresh)는 여전히 `consents.allowed(...)`로 상태를 계산한다(`privacy.py` `_action` 끝부분). `allowed`의 `_session`은 미등록 세션을 거부한다. grant 분기만 "동의 기록됨" 문구로 우회됐다.
- **부가**: `checking` 상태 문구 "확인 중 — 전송 불가"는 coordinator가 실제 전송 중이라 잠겨 있을 때도 표시된다. 진행 중인 전송과 문구가 모순되므로 "동의 정보 확인 중"처럼 바꾸는 것을 권고한다.
- **기대**: 상태 문구가 범위 정보(`scope_view`)와 같은 판단을 쓰거나, 등록 전에는 "실행 준비 시 확인"으로 일관되게 표시한다.

#### G02A-10 / S3 / OPEN — 선택 행이 사라진 refresh 뒤 한 event-loop 동안 모든 고정 세션 작업이 거부된다

- **재현**:
  - `test_new_pending_gap_rejects_fixed_session_job_with_session_grant`: R 선택 → SESSION(R) 허용 → A로 이동 → A가 사라지는 refresh. 대기 `singleShot(0)`가 처리되기 전 `prepare_execution("stt","R")`이 `CONSENT_REQUIRED`다. 처리 뒤에는 허용된다(`after_settle_allowed True`).
  - LIBRARY 변형(`…_with_library_grant`)도 공백 구간에서 `CONSENT_REQUIRED`다.
- **원인**: `selection_pending()` 동안 `_selected_scope`가 `session_id` 인자와 무관하게 `CONSENT_REQUIRED`를 던진다(`privacy.py` `_selected_scope` 첫 줄). 화면 선택 공백을 작업의 고정 세션 판단에까지 적용한 것이다.
- **영향**: 메인 timer(250ms, `main.py:84`)의 `_live_tick`이 이 공백에 걸리면 원격 실시간 전사가 `_live_blocked`(`ai_bridge.py:155-156`)로 멈추고 명시 재개가 필요하다. fail closed이고 공백이 짧아 발생 확률은 낮다.
- **수정 제안**: pending 검사를 화면 선택 기반 동작(`session_id is None`)에만 적용하고, 명시 `session_id`를 받은 준비는 콤보 범위로 판단한다.

#### G02A-11 / S3 / OPEN — 삭제 진행 중 세션을 선택하면 privacy 그룹 전체가 비활성화된다

- **재현**: `test_new_deleted_row_disables_whole_privacy_group`. 철회된 C를 선택하면 `group_enabled False`가 되어 "키 삭제·권한 철회", LIBRARY 범위 선택·철회, 예산과 정산 조작이 모두 막힌다.
- **원인**: `_show_scope`가 `deleted` 상태에서 `control.setEnabled(False)`로 `_Controls` 그룹 전체를 끈다.
- **영향**: 다른 세션을 선택하거나 선택을 해제하면 다시 켜진다. 다만 그 세션을 보는 동안에는 세션과 무관한 철회·키 폐기·UNKNOWN 정산도 막힌다.
- **수정 제안**: 세션 한정 허용/철회만 비활성화하고, 키·endpoint 철회, LIBRARY 철회, 예산과 정산은 유지한다.

#### G02A-12 / S3 / OPEN(잠재) — 전송 전 `CONSENT_POLICY_CHANGED`가 adapter에서 REMOTE_OUTCOME_UNKNOWN으로 분류된다

- **재현**: `test_new_presend_policy_change_is_not_reported_as_remote_unknown`. 예약 직후 정책을 3으로 올리고 `OpenAITranscriber(...).transcribe(...)`를 호출한다.
  - 실제: `error_code REMOTE_OUTCOME_UNKNOWN, outcome_known False, opens 0, writes 0`. 아무것도 보내지 않았는데 결과 미확인으로 분류된다.
  - 대조군(정책 대신 철회)은 `CONSENT_REQUIRED, outcome_known True`로 PASS다.
- **원인**: G-P02가 새로 만든 `CONSENT_POLICY_CHANGED`가 `providers/_common.py:223-245`의 safe code 목록에 없다. 그래서 251행에서 `REMOTE_OUTCOME_UNKNOWN`으로 바뀐다. 작업 계층은 이 결과를 `BLOCKED(REMOTE_UNKNOWN)`/attempt UNKNOWN으로 기록한다(`jobs/__init__.py:697-702`, 코드 읽기).
- **잠재인 이유**: 현재 제품에는 `advance_policy_version`을 런타임에 호출하는 곳이 없다(grep). 재시작으로 정책이 오르는 경우는 `EXECUTION_CHANGED`가 먼저 걸린다. 정책 증가 경로가 생기면 S2가 된다.
- **수정 제안**: `_common.py`는 19파일 밖이므로 재배정이 필요하다. safe code에 추가하는 방안과 분류 시험을 함께 권고한다.

### R-5. config_key 변경의 부작용 점검(C00 요청)

- **실시간 checkpoint**: 범위만 바뀌어도 `stream_scope`가 같으므로 처리한 청크를 다시 보내지 않는다(RR5 v2 시험).
- **admission 중복 판정**: `test_check_admission_merge_across_scope_uses_only_running_job_bindings` PASS. SESSION 계획으로 실행 중인 작업에 LIBRARY 계획의 같은 요청이 들어오면 같은 job ID로 병합된다. 두 번째 계획의 provider·gateway는 호출되지 않는다(`calls ["session-plan"]`). 실행 중 작업은 자기 binding만 쓰고 그 binding은 매 경계에서 재검사되므로 무동의 전송 경로가 아니다. `_admit`(`app/ai.py:94-123`)은 CONSENT/AUTH 등으로 BLOCKED된 작업만 새 task로 재개한다. FAILED·SUCCEEDED 작업은 nonce 명시 재실행 전까지 반환만 한다. HEAD(9d46b4a)의 config_key에도 범위가 없었으므로 이 동작은 HEAD와 같다.
- **요약 checkpoint 재개·G-P03 settings_key**: 범위·정책만 바꾼 요청도 같은 checkpoint와 settings로 취급된다. 이것이 C00가 의도한 동작이다. 복원된 checkpoint는 이미 받은 결과이며 원문을 다시 보내지 않는다(코드 읽기, `app/ai.py:467-504`).
- **관찰(결함 아님)**: HEAD의 config_key에는 기능과 작업 세션이 없었다. 업그레이드 직전 HEAD 빌드로 만든 미완료 요약 checkpoint나 실시간 draft는 업그레이드 뒤 키가 달라 재개되지 않고, 한 번 다시 보낼 수 있다. 출시 전 개발 데이터에만 해당한다. 필요하면 G-P09 migration 메모로 남긴다.
- **비차단 표시의 늦은 결과**: `scope_view`는 동기 호출이며 실패하면 즉시 `checking`을 반환한다. 재시도 timer는 그 시점의 `_selected_session`으로 다시 계산한다. `test_new_late_checking_retry_shows_current_session_only` PASS: lock을 잡은 채 A → B로 이동하고 해제하면 최종 표시는 B만이고 허용 버튼이 다시 켜진다. 이전 세션 결과가 다른 세션 표시를 덮는 경로는 찾지 못했다.

### R-6. 미검증·한계

- 실제 `MainWindow`·Windows 장치·네트워크·vault·Ollama는 사용하지 않았다. fake window는 `main.py`의 신호 연결 순서를 그대로 모사했다.
- 작성자의 32변이 script와 결과는 재실행하지 않았다. 검토자 변이 11개만 실행했다.
- mypy는 `src/recoryn` 70파일 범위다.

### R-7. RECHECK 결론

**G02-A RECHECK: G02A-01~08 RECHECKED, OPEN 4 (S0 0 / S1 0 / S2 0 / S3 4).** OPEN은 G02A-09(상태 문구 모순), G02A-10(refresh 공백 구간의 고정 세션 거부), G02A-11(삭제 진행 중 선택 시 그룹 전체 비활성), G02A-12(전송 전 정책 변경의 UNKNOWN 분류, 잠재)다. 이 항목들의 수용 여부와 수정 순서는 C00가 결정한다.
