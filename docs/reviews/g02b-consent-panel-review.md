# G02b / G-P02b 동의 패널 S3 후속 독립 검토

2026-11-23, 검토자 Claude(C00 지정 하위 에이전트, G-P02 검토 A와 같은 검토자). 작성자는 w5:p8 Codex이며 검토자는 이 단위의 코드·시험·문서를 작성하지 않았다.

**S0/S1/S2 발견 없음. OPEN 1건: S3 1건.** 대상 세 반례(G02A-09·10·11)는 이 tree에서 기대대로 통과한다. G02A-10·11 수정에서 새 동의 우회나 fail-open을 찾지 못했다. ResourceWarning 6건은 시험 fixture의 미종료 연결이라는 작성자 분석과 검토자 재현이 일치하며, 전체 회귀를 `-W error::ResourceWarning`으로 돌려 경고 0건이었다. 남은 것은 세션을 바꾼 뒤 상태 문구가 이전 세션 기준으로 남는 표시 결함 하나다(G02B-01). 최종 수용은 C00가 결정한다.

## 1. 입력과 추출

- 대상 tree는 **`0f655cae5e47f6f6593376c9ec22354dee3e957a`**(`git cat-file -t` = tree), 기준은 HEAD **`9284db0`**(G-P02 66f0a85 + GC-P01)다.
- `git diff --stat 9284db0 0f655cae` 결과는 5파일, 448 insertions / 44 deletions다.
  - 제품: `security/consent.py`, `ui/privacy.py`
  - 시험: `tests/ui/test_consent_scope_ui.py`, `tests/unit/test_consent_scope.py`
  - 문서: `docs/testing/g02-consent-scope-cases.md` §11
- 추출(작업 트리 판정 없음):
  - 판정·전체 회귀: `git -c core.autocrlf=false archive 0f655cae… | tar -x -C build/review-trees/g02b`
  - 변이: `… pyproject.toml src tests | tar -x -C build/review-trees/g02b-pristine`
  - 기준선 재현: `git archive 9284db0 pyproject.toml src tests | tar -x -C build/review-trees/g02b-head`
- 변경 Python 4파일의 LF SHA256은 문서 §11.6 표와 **4/4 일치**한다(consent `9b1f60ea…`, privacy `078e25b4…`, UI 시험 `1c3ede01…`, unit 시험 `7604e33f…`).
- 저장소 쓰기는 이 문서 하나뿐이다. 반례·변이 사본은 `D:/project/Recoryn/build/review-trees/` 아래에만 두었다. git 쓰기, 네트워크, 설치, 실제 장치·모델·vault, 추가 에이전트는 사용하지 않았다.

## 2. 직접 실행한 명령과 결과

모든 실행에 `.venv` Python, `-B`, `PYTHONDONTWRITEBYTECODE=1`, `QT_QPA_PLATFORM=offscreen`, `HF_HUB_OFFLINE=1`, `-p no:cacheprovider`, 실행별 새 `--basetemp`를 사용했다.

| # | 명령(cwd) | 결과 |
| --- | --- | --- |
| B1 | 전체 회귀(g02b, `PYTHONPATH=g02b/src`, `TRANSFORMERS_OFFLINE=1`, `HF_HUB_DISABLE_TELEMETRY=1`, **`-W error::ResourceWarning`**, `-rs --junitxml …/g02b-full.xml`) | **9119 수집 / 9117 passed / 2 skipped / failure 0 / error 0 / 경고 0, 229.45s, exit 0** |
| B2 | 기준선 `tests/unit/test_consent_scope.py tests/unit/test_content.py`(g02b-head, `PYTHONTRACEMALLOC=25`, `-W error::ResourceWarning`) | **209 passed, 6 warnings**. 경고 6건 모두 `unclosed database` |
| B3 | B2와 같은 명령(g02b) | **215 passed, 경고 0**(+6은 새 CLOSE 행) |
| B4 | 검토자 기존 반례 23 node(`test_g02a_probes.py`, `test_g02a_recheck.py` 무수정, `-W error::ResourceWarning`) | **20 passed, 3 failed**. 실패 3건 구성은 §3.1 |
| B5 | 검토자 새 probe `test_g02b_probes.py` 10 node(`-W error::ResourceWarning -W error::pytest.PytestUnraisableExceptionWarning`) | **9 passed, 1 failed**(G02B-01 반례) |
| B6 | `python -I build/review-trees/g02b-mutate.py` | baseline 404 passed, **변이 8/8 KILLED**, invalid 0 |
| B7 | 새 4파일 `--co` / `ruff check` / 4파일 `ruff format --check` / `mypy src/recoryn` | **1094 node** / PASS / 4 files already formatted / 70 source files no issues |

- B1의 2 skip은 이전 검토와 같은 `test_gpu_smoke.py:107`(D: 볼륨의 8.3 이름 미생성)이다. 작성자의 9119 PASS/skip 0과의 차이는 이것뿐이다.
- B1은 pytest unraisable을 오류로 바꾸지는 않았지만 경고 요약이 0건이다. 따라서 destructor의 ResourceWarning도 없었다. B5는 두 옵션을 모두 오류로 처리했다.
- 반례 파일은 B1 수집이 끝난 뒤 복사해 B1에 섞이지 않았다(JUnit에서 0건 확인).

증거 파일의 LF SHA256은 다음과 같다. 새 probe `eeb85f8cd5b4a4e0c3e558b318017b2688c088381e913723250e2bf348e470ed`, 변이 harness `8d04b184e552d77720b41fd1b1ccdddf2ee70124d40b3ab541cc49a8d4d5c815`, 변이 결과 `build/review-trees/g02b-mutations.json` `b3280219cd9fe2178fd117c41355a7c4a091308b3d4966fc07360a890f28d461`. 기존 probe 두 파일은 앞 16자 `01c1823a54ade313`, `21fb1f84e1198c56`로 G-P02 RECHECK 때와 같다.

## 3. 관점별 판단

### 3.1 세 반례의 결과

B4 결과는 다음과 같다.

- **G02A-09 RECHECKED**: `test_new_status_after_refresh_action_matches_active_grant` PASS. 비용 갱신 뒤 상태가 `동의 활성 — 실행 준비 시 세션·권한을 다시 확인합니다`이고, 범위 정보는 `… / 만료 …+09:00`로 서로 일치한다.
- **G02A-10 RECHECKED**: `…pending_gap…_with_session_grant`(`gap allowed`, settle 뒤도 허용)와 `…_with_library_grant`(`gap allowed`)가 모두 PASS다.
- **G02A-11 RECHECKED**: `test_new_deleted_row_disables_whole_privacy_group` PASS. `group_enabled`, `delete_key_effective`, `library_revoke_reachable`이 모두 True다.
- B4의 실패 3건은 이번 범위 밖이며 원인은 다음과 같다.
  - G-P02 1차 config_key 반례 2건은 G-P02에서 키가 같아진 수정 때문에 사전조건이 무효가 된 것이다(RECHECK 기록과 같다).
  - G02A-12 반례 `[policy]` 1건은 C00 결정으로 G-P07이 다룬다. 결과도 RECHECK 때와 같다(`REMOTE_OUTCOME_UNKNOWN, outcome_known False, opens 0`).

### 3.2 새 우회·fail-open 여부

- **G02A-10**(`privacy.py` `_selected_scope`: pending 검사를 `session_id is None`일 때만 적용)
  - 명시 `session_id`로 `_selected_scope`를 부르는 곳은 `_snapshot`(→ `prepare_execution`/`gateway_for`)뿐이다. pending 동안 `window.selected_session()`은 None이다. 그래서 bridge의 `_transcribe`/`summarize`는 화면 선택에서 세션을 얻지 못하고 조기 반환하며, 화면 기반 세션이 공백에 들어오는 경로는 없다(코드 읽기).
  - 검토자 독립 표 시험 `test_check_gap_fixed_session_matches_stable_decision` 8행이 PASS다. 콤보(SESSION/LIBRARY) × 기존 grant(없음/SESSION(R)/LIBRARY/둘 다)의 결과가 손으로 쓴 표와 같다. 허용은 SESSION+SESSION(R), SESSION+둘, LIBRARY+LIBRARY, LIBRARY+둘의 4행뿐이다. SESSION↔LIBRARY fallback은 양방향 모두 없다. 허용된 binding의 request는 R, scope는 콤보 그대로다. 같은 시점 `_selected_scope(kind)`(화면 기반)는 `CONSENT_REQUIRED`다.
  - 작성자 GAP 40행도 철회·만료·삭제(`SESSION_REVOKED`)의 계속 거부를 대조한다.
- **G02A-11**(`deleted` 상태에서 그룹 전체 비활성 제거, LIBRARY 선택 시 정상 표시)
  - 검토자 `test_check_deleted_selection_library_grant_never_reaches_deleted_session` PASS. 삭제 진행 중인 C를 볼 때 SESSION 허용은 비활성이고 클릭해도 grant 0이다. LIBRARY로 바꾸면 확인 창을 거쳐 LIBRARY grant가 생긴다. 그래도 `prepare_execution("stt","C")`는 `SESSION_REVOKED`이고 표시에 "삭제 진행 중"이 남는다.
  - 삭제 fence는 consent의 `_session`/`bind_session`이 담당하며 이번 diff는 consent 전송 규칙을 바꾸지 않았다(`git diff`: consent.py는 생성자 실패 정리만 변경).
- **G02A-09**: 상태 문구가 `allowed()` 대신 `scope_view` 표시 상태에서 나온다. 표시만 바뀌었고 권한 판정 경로(capture/permit)는 그대로다.
- 결론: 새 S0 경로나 fail-open을 찾지 못했다.

### 3.3 ResourceWarning 원인 분석

- **재현(B2)**: 기준 tree에서 `PYTHONTRACEMALLOC=25`로 할당 위치를 추적했다. 경고 6건의 allocation traceback 마지막 시험 줄은 `tests/unit/test_consent_scope.py`의 **79·87·94·119·125·182행**이다. 모두 `with sqlite3.connect(db) as connection:` fixture이고 `src` 할당은 없다.
  - CI(run 45098064324, 3.13)의 6건이 모두 다음 파일 `test_content.py`의 한 시험에 귀속된 것도 GC 시점이 늦은 결과로 설명된다.
  - 작성자 §11.3의 "79·87·94·119·125·182행"과 일치한다. sqlite3 context manager가 transaction만 끝내고 close하지 않는다는 원인 설명도 맞다.
- **수정 확인(B3)**: 같은 명령에서 경고가 0건이다. B1 전체 회귀도 `-W error::ResourceWarning`으로 경고 0건이다.
- **제품 경로**:
  - `ConsentStore.__init__` 실패 경로가 `try: ROLLBACK finally: close; _closed=True`로 보강됐다(rollback 실패 시 누수 경로 제거).
  - `scope_view`는 `contextlib.closing`을 쓴다.
  - `CostLedger.__init__`은 실패 시 무조건 close한다(코드 읽기).
  - 보안 계층의 연결 생성은 이 세 곳(`_core.connect` 2곳 + `scope_view`)뿐이다(grep). 남은 제품 누수를 찾지 못했다.
- **시험 품질**: 새 CLOSE 6행은 실제 `sqlite3.Connection` 하위 클래스로 open/close 횟수와 이후 SELECT의 `ProgrammingError`를 단언한다. 정리 단계에서 남은 연결을 닫아 늦은 GC 경고가 판정을 대신하지 않게 했다. 변이 B08r(close 제거)과 B09r(rollback 실패 시 close 생략)이 모두 CLOSE 행 assertion으로 검출됐다.

### 3.4 기대값 독립성과 mutation 재현

- 작성자 STATUS/GAP/DELETE/CHECKING 시험의 기대는 손으로 쓴 단어표, 상태 분기 표, DB 행 수, ledger 수치다. 제품 helper로 기대를 계산하지 않는다(시험 diff 확인).
- 새 ID 74행은 `G02B_CASE_IDS`에 따로 등록됐다. property manifest(18,463)는 바꾸지 않았다. 새 4파일 node 수 1094 = 1014 + 74 + 6으로 작성자 보고와 같다.
- 작성자 B01~B09 중 8개를 검토자가 직접 다시 만든 변이로 재현했다. 모두 KILLED다(B6).

| ID | 변이(검토자 작성) | 첫 실패 node |
| --- | --- | --- |
| B01r | 비발급 동작 상태를 항상 "동의 활성"으로 | `G02B-STATUS-02` |
| B02r | pending이면 fixed_session도 거부 | `G02B-GAP-01` |
| B03r | pending 검사 전체 제거(화면 기반 포함) | `G02B-GAP-11` |
| B04r | deleted에서 그룹 전체 비활성 재도입 | `G02B-DELETE-00` |
| B05r | deleted면 SESSION에서도 허용/철회 활성 | `G02-UI-FIX-06` |
| B07r | checking을 "확인 중 — 전송 불가"로 | `G02B-CHECKING-00` |
| B08r | 생성 실패 시 close 제거 | `G02B-CLOSE-00` |
| B09r | rollback 실패 시 close 건너뜀(옛 형태) | `G02B-CLOSE-04` |

### 3.5 전체 회귀

B1 결과는 9117 passed / 2 skipped(환경) / failure·error 0 / **경고 0**(`-W error::ResourceWarning`)이다.

## 4. 발견

### G02B-01 / S3 / OPEN — 세션을 바꾼 뒤 상태 문구가 이전 세션의 "동의 활성"으로 남는다

- **재현**: `test_new_status_follows_session_switch`(B5). 목록에서 A 선택 → 허용(SESSION(A)) → B 선택.
- **실제**: B 선택 뒤 상태는 `동의 활성 — 실행 준비 시 세션·권한을 다시 확인합니다`, 범위 정보는 `이 세션만: B / … / 기본 거부`다.
- **기대**: 상태 문구가 현재 선택(B)의 grant 사실과 일치한다(동의 없음). G-P02b §11.1은 "`_show_scope`의 read-only metadata와 일치하는 상태 문구"를 목표로 한다.
- **원인**: 상태 label은 `_action`의 else 분기에서만 `_show_scope` 반환값으로 갱신된다. `select_session`과 retry timer(`_retry_scope_views`)도 `_show_scope`를 호출하지만 반환값을 버린다. 상태 문구에 세션 ID가 없어서 B의 동의처럼 읽힌다.
- **영향**: 표시 결함이다. 실제 준비·전송은 fresh capture/permit으로 계속 거부된다(B 준비는 `CONSENT_REQUIRED`). 이 갱신 누락 자체는 G-P02 때부터 있었지만, 이번 단위가 상태 문구를 grant 사실과 맞추는 것을 목표로 했으므로 같은 계열의 잔여로 기록한다.
- **수정 제안**: `select_session`과 `_retry_scope_views`에서도 `control.status.setText(self._show_scope(kind))`를 적용한다. 또는 세션이 바뀔 때 상태를 초기 문구로 되돌리고, 상태 문구에 대상 세션/범위를 넣는다. A→B 전환 후 상태를 단언하는 시험 행을 추가한다.

## 5. 관찰(결함 아님)

- 검토 중 "동작 직후 coordinator가 잠겨 상태가 '동의 정보 확인 중'으로 남는다"는 가설을 시험했다. 그러나 모든 `_action`은 상태 계산 전에 `_refresh`의 `ledger.snapshot`이 같은 coordinator lock을 차단 대기한다. 그래서 그 창은 사실상 없었고, 해당 probe는 의미 있는 관측이 아니어서 삭제했다. 결함으로 세지 않는다. `_action`의 이 차단 대기는 정책 명령의 기존 설계(G-P02 이전부터)다.
- G02A-12는 C00 결정대로 이번 tree에서도 그대로다(G-P07).

## 6. 미검증·한계

- 실제 `MainWindow`·Windows 장치·네트워크·vault·Ollama는 쓰지 않았다. bridge는 `main.py`의 신호 연결 순서를 모사한 fake window로 시험했다.
- 작성자 R4 증거(전체 9119 PASS, 641 PASS 등)와 B06 관측은 재실행하지 않았다. 검토자 실행 결과만 위에 적었다.
- mypy는 `src/recoryn` 70파일 범위다.

## 7. 결론

**G02b REVIEW_READY / OPEN 1 (S0 0 / S1 0 / S2 0 / S3 1).** G02A-09·10·11 RECHECKED, ResourceWarning 원인 분석 확인. 남은 G02B-01의 수정 여부와 시점은 C00가 결정한다.
