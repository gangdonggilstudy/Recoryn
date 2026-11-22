# GT02-R — GT-P02 e2e 정지·완료 대기 상한 독립 검토

2026-11-23, 검토자 w5:p8 Codex, 작성자 C00. **코드 변경에 대한 차단 결함은 발견하지 않았다. OPEN 1건(S3): CI 원문 로그 대조 미완결**이다. 정상본·독립 fake·격리 mutation과 동일 패턴 목록은 아래에 직접 확인한 증거를 적었다.

## 1. 대상과 증거 경계

- 고정 tree: `ce56575b4bcbc713ced525deef17afaa917bd5bf`.
- 비교 기준: `9f2cdf2978fa3a161fabdd3bdde5e850a1fcf930`.
- `git diff --stat 9f2cdf2 ce56575b`: **2파일, +5/−2**. `tests/e2e/test_ai_workflow.py` +4/−2, assignments의 GT02 행 +1이다. 제품 코드·CI workflow는 바뀌지 않았다.
- 시험 파일 LF SHA-256: `74689cac30d7c208dd04741873398f89b35c7476f82822778d684635108bc5eb`.
- 고정 tree를 `git archive`로 풀어 검증했다. 증거 루트는 `C:/Users/gangd/AppData/Local/Temp/recoryn-gt02-review-iqdet3iw`, 실행 소스는 그 아래 `tree/src`다. 작업 트리의 G-P02/G-P04 변경은 사용하지 않았다.
- 이번 환경은 Windows/Python **3.13.1**이다. 원격 core(3.13)와 같은 minor 계열이지만 같은 부하·패치 버전·디스크 조건을 재현했다고 하지 않는다.
- CI 실패 1회·8024 PASS·전체638초와 기존 로컬8025 PASS/약260초는 **C00가 제공한 사실**이다. run `45076718852`의 원문은 아직 직접 열어 대조하지 못했다. 이를 직접 확인한 실행 결과로 표기하지 않는다.

## 2. 발견

### GT02-01 — CI 원문 로그 대조가 남음

- **심각도 S3 / OPEN(검증 증거 보강).** 대상: assignments GT02 행의 실패 원인 설명과 CI run `45076718852` core(3.13).
- **직접 확인한 코드:** `src/recoryn/app/recording.py:213-222`는 `_thread.join(timeout)` 뒤에도 writer가 살아 있으면 WRITER_ACK_PENDING을 낸다. `stop`의 제품 기본값은 `:250-251`의 5초이며, 변경 전 `recording()` 도우미가 이 기본값으로 stop을 호출한 것도 diff에서 확인했다. 따라서 제공받은 traceback 설명과 코드 경로는 맞는다. 이 실패가 `recording()` 안이라면 취소 시험의 모델 호출·cancel·게시 assertion에 도달하기 전이다.
- **미확인:** 실패 traceback의 정확한 프레임·job/commit·예외·실행 요약·638초 원문, 요청된 CI 재실행 결과. 로컬 저장본을 찾으려 했으나 사용 가능한 로그를 확보하지 못했고 TEMP의 일부 경로는 접근 거부여서 해당 탐색을 중단했다. 네트워크 금지 조건을 유지하며 원문 로컬 경로를 이 창에서 요청했다. 계정/원격 CI 조회나 권한 우회는 하지 않았다.
- **판정:** WRITER_ACK_PENDING 자체는 “5초 뒤에도 writer가 살아 있었다”는 증거다. 원격 부하·I/O 지연 설명은 전체 소요시간·다른 실행의 성공과 정합하는 가설이지만, 그것만으로 deadlock 등 다른 원인을 배제했다고 할 수 없다. 로컬 정상본 통과도 원격 실패 원인의 증명은 아니다.
- **제안:** 해당 실패 job의 traceback/종료 요약을 저장한 로그와 재실행 결과를 제공하면 원문을 대조해 닫는다. 최소한 `test_cancel... → recording → stop → _drain → WRITER_ACK_PENDING`, 기준 commit, 실패/통과 개수와 소요시간을 확인한다. CI 재실행 성공은 간헐성 근거로 구별하고, 실패가 반복되면 writer stack/진행 단계 관측을 별도 단위로 추가한다. 제품 timeout 확대나 모든 시험의 일괄 완화를 요구하는 지적은 아니다.

## 3. 시간 상한 변경과 취소 oracle 확인

| 변경/관측 | 직접 확인한 내용 | 판정 |
| --- | --- | --- |
| `recording()`의 `stop(timeout=60)` (`tests/e2e/test_ai_workflow.py:46`) | writer join의 최대 대기만 늘림. ACK 뒤 health 기록·FINALIZED 절차, 오류 전달은 동일 | 고정 60초 sleep이 아니며 끝나면 바로 반환 |
| `finished()`의 deadline 60초 (`:50-57`) | monotonic deadline과 5ms polling 유지. 네 종료 상태를 읽자마자 반환하고 끝내 종료하지 않으면 pytest.fail | 성능 상한 assertion이 없는 기능 시험의 외부 대기 여유 |
| 취소 시험 (`:181-198`) | 모델 진입 Event 확인→cancel_session→release→CANCELLED 정확 비교→revision 빈 목록→원본 청크1개 확인 순서 유지 | FAILED/BLOCKED/SUCCEEDED로 끝나도 통과시키지 않음 |
| FakeSTT (`:60` 이후) | 취소 token을 검사하지 않고 release 뒤 결과를 돌려주는 동작 유지 | 완료 결과를 무시/게시 차단하는 제품 fence 계약을 계속 시험 |
| 제품의 ACK 보호 | `RecordingService.stop` 기본5초·`_drain`의 alive 검사·fence/게시 구현 모두 변경 없음 | 60초가 지나도 writer가 살아 있으면 완료 처리하지 않음 |
| 아직 남은 단기 대기 | provider release.wait(5), entered.wait(5), `emit_epoch`의 pause 기본5초, 느린 변환 시험의 future.result(timeout=2) 등은 그대로 | 이번 수정이 모든 부하성 실패를 없앴다고 하지 않음. timeout 목적별로 별도 판정 필요 |

`.github/workflows/core.yml`의 core job은 Windows, Python3.11/3.13, job 전체 상한15분, ResourceWarning 오류화·coverage를 켠다. 이번 로컬 선택 실행을 그 CI 전체 실행/coverage의 대체로 보지 않는다. finished()의 넓은 상한을 의도적인 writer/AI 분리 지연 assertion이나 취소 barrier의 순서 검증에 전파하지 않는 것이 맞다.

## 4. 직접 실행한 검증

### 정상본과 독립 대조

모든 pytest는 고정 tree의 cwd에서 실행했다. bytecode 비활성, `QT_QPA_PLATFORM=offscreen`, HF/Transformers 오프라인·telemetry 비활성, `-p no:cacheprovider`, 증거 루트 아래 고유 basetemp를 사용했다. 실제 장치·모델·네트워크·계정·설치를 사용하지 않았다.

1. `python -B -m pytest -q -p no:cacheprovider tests/e2e/test_ai_workflow.py tests/e2e/test_recording_control.py tests/integration/test_app_service.py --basetemp <증거>/pytest-selected --junitxml <증거>/selected.xml` → **30 PASS, 4.34초**. 파일별9/7/14 node다.
2. 독립 TEMP 시험 `R/test_gt02_independent.py`와 `tests/e2e/test_ai_workflow.py`를 함께, 추가로 `-W error::ResourceWarning`을 지정 → **17 PASS, 1.85초**. 독립8개+원래9개 재실행이며, 30+17개의 서로 다른 제품 시험이라고 합산하지 않는다.
3. 변경 파일 `ruff check --no-cache`, `ruff format --check --no-cache` → **PASS**, 형식 변경 필요0.

독립8개는 helper 정의만 대상 소스 AST에서 불러오고 기대값은 별도로 정했다. fake clock으로 4종 종료 상태의 즉시 반환4개, **5.5초에 끝나는 Job의 허용**, **60초까지 미완료인 Job의 실패**, fake recording의 **stop 인자60 전달**, 실제 `_drain`을 사용하는 fake thread의 **60 전달 후 alive이면 WRITER_ACK_PENDING 유지**를 확인했다. 마지막 시험은 input gate 닫힘과 동일 thread 핸들 보존도 assert한다. 실제60초를 자거나 실제 writer 지연을 재현한 것이 아니다.

### 격리 mutation 3개

각 사본에 pyproject·src·tests·scripts·packaging을 복사하고 import origin이 해당 사본 src인지 확인했다. 원본 tree와 작업 트리는 바꾸지 않았다. 정상본의 목표 assertion PASS 뒤 mutant를 하나씩 실행했다.

| 변이 | 목표 node | 실제 결과 |
| --- | --- | --- |
| M1 cancel_session 호출 제거 | 기존 `test_cancel_revokes_publication_even_when_model_ignores_cancel` | **FAIL**: 기대 CANCELLED, 실제 SUCCEEDED (`test_ai_workflow.py:193`), 0.43초 |
| M2 finished 상한을5초로 복원 | 독립 `test_finished_accepts_completion_after_the_old_five_second_bound` | **FAIL**: AI job did not finish, 0.11초 |
| M3 helper stop을 기본5초 호출로 복원 | 독립 `test_recording_helper_passes_the_sixty_second_upper_bound` | **FAIL**: 기대60, 실제5, 0.10초 |

**3/3 목표 assertion 검출**이며 import/수집 오류·timeout으로 센 결과는 없다. M1은 바뀐 timeout 아래서도 원래 취소 assertion이 취소 누락 결함을 검출한다는 근거다. 전체 취소 경쟁/프로젝트 mutation coverage를 의미하지 않는다.

## 5. 같은 기본 상한 패턴의 다른 시험 목록

고정 tree의 AST에서 직접 생성한 RecordingService/ DesktopRecorder 변수와 timeout을 생략한 stop 호출을 연결했다. **RecordingService 25곳, DesktopRecorder 7곳**이다. UI fixture의 간접 `window.recorder.stop()` **5곳**도 별도 읽었다. 이는 정적 호출 지점 수이며 매개변수 확장 후 시험 node 수가 아니다. 기본 stop이 있어도 PAUSED/FINALIZED이거나 writer 종료를 이미 확인했다면 그 호출에서 새 5초 writer 대기를 만들지 않는다.

### RecordingService 직접 호출25곳

| 파일:행 | 함수/시험 | 같은 위험의 범위 |
| --- | --- | --- |
| `tests/e2e/test_ai_workflow.py:274` | `test_streaming_accumulates_only_fresh_chunks_and_protects_edits_and_config` | 직전 emit_epoch가 pause하므로 이 stop은 PAUSED 경로. emit_epoch의 pause 기본5초는 별도 위험 |
| `tests/e2e/test_recording_control.py:91` | `test_pause_is_acknowledged_after_drain_and_resume_uses_new_epoch` | resume 후 정상 종료, 활성 writer 대기 가능 |
| 같은 파일 `:108` | `test_storage_failure_is_not_reported_as_finalized` | 저장 장애 기대 경로. 이미 종료됐을 수 있어 정상 종료와 구별 |
| 같은 파일 `:142` | `test_pause_timeout_keeps_gate_closed_until_actual_writer_ack` | 앞서 pause 완료 후 stop. 의도적인 pause(timeout=0)는 유지 |
| 같은 파일 `:162` | `test_rotation_failure_releases_writer_for_prefix_recovery` | 장애/종료 경로. 단순히60초로 바꾸기 전에 기대 오류 의미 확인 |
| 같은 파일 `:178,179` | `test_empty_session_and_idempotent_stop_keep_finalized_state` | PAUSED→FINALIZED와 FINALIZED 반복 호출. 이 stop들은 새 writer 대기 없음 |
| 같은 파일 `:193` | `test_rotation_does_not_split_a_fragmented_packet` | 정상 활성 writer의 drain 대기 가능 |
| 같은 파일 `:213` | `test_export_splits_a_source_gap_inside_one_chunk` | 정상 활성 writer의 drain 대기 가능 |
| `tests/integration/test_app_service.py:62` | `test_pause_resume_preserves_separate_track_epochs_and_privacy` | resume 후 정상 종료, 대기 가능 |
| 같은 파일 `:112` | `test_full_queue_close_preserves_last_drop_and_cutoff` | 앞서 join_writer 완료. 그 stop의 writer는 이미 종료. pause(timeout=0.01) 검증은 유지 |
| 같은 파일 `:146` | `test_storage_failure_interrupts_without_claiming_finalized` | 저장 실패 주입·RecordingError 기대, 정상 종료와 구별 |
| 같은 파일 `:166` | `test_capture_health_write_failure_cannot_leave_recording_state` | writer 종료 후 metadata 실패 주입까지 가야 하므로, 먼저 join 상한에 걸릴 위험은 남음 |
| 같은 파일 `:206` | `test_job_failure_and_cancel_do_not_end_recording` | AI 오류 뒤 녹음의 정상 종료, 대기 가능 |
| 같은 파일 `:226` | `test_cli_export_samples_no_overwrite_and_original_invariance` | export 준비용 원본 정상 종료, 대기 가능 |
| 같은 파일 `:313` | `test_rotation_waits_for_the_complete_fragment_group` | 정상 활성 writer drain 대기 가능 |
| 같은 파일 `:337` | `test_threshold_seal_failure_releases_writer_and_preserves_prefix` | barrier 해제 뒤 seal 실패/종료 경로. 예상 오류까지 도달하는지 별도 확인 필요 |
| `tests/integration/test_ai_independent.py:61` | `_record` 도우미 | 여러 AI 계약 시험의 녹음 준비에 재사용, 정상 drain 대기 가능 |
| `tests/integration/test_desktop_independent.py:232` | `store_block` 도우미 | 정상 drain 대기 가능 |
| 같은 파일 `:431` | `test_pause_resume_keeps_simulated_suspend_gap_and_epoch_source_map` | 원본 종료 경로의 기본 상한. pause/resume 단계 대기도 따로 존재 |
| 같은 파일 `:791` | `test_b21_incremental_stt_reuses_origin_across_gap_epochs_and_preserves_originals` | streaming 세션 종료의 기본 상한 |
| `tests/integration/test_selection_version_cas.py:468` | `record` 도우미 | 선택 CAS 경우의 수 시험의 원본 준비에 재사용 |
| `tests/unit/test_media.py:39` | `record` 도우미 | 미디어 시험의 원본 준비에 재사용 |
| 같은 파일 `:136` | `test_vad_derived_clip_keeps_absolute_source_frames_and_wav_checksum` | 정상 원본 종료, 대기 가능 |
| 같은 파일 `:170` | `test_forward_clock_jump_cannot_be_compressed_into_one_correlated_clip` | 정상 원본 종료, 대기 가능 |

### DesktopRecorder와 UI 간접 호출

DesktopRecorder.stop은 `app/desktop.py:201-210`에서 장치 종료 뒤 RecordingService.stop에 timeout을 넘기지 않아 기본5초를 사용한다. fake 장치가 곧바로 닫혀도 이후 파일 writer의 대기 위험은 남을 수 있다.

| 파일:행 | 함수/시험 |
| --- | --- |
| `tests/integration/test_desktop_independent.py:124` | `test_missing_stop_ack_preserves_source_ownership_and_library_lock` — 의도적인 ACK 누락을 해제한 뒤 정상 stop |
| 같은 파일 `:488` | `test_desktop_stop_preserves_manifest_only_failure_contract` |
| 같은 파일 `:813` | `test_b21_delete_pending_reader_is_visible_as_pending_not_silent_disappearance` |
| `tests/unit/test_desktop.py:59` | `test_pause_resume_stop_new_epoch_and_original_preservation` |
| 같은 파일 `:112` | `test_empty_and_duplicate_track_rejected` — NO_RECORDING 거부 경로라 writer 대기 위험 아님 |
| 같은 파일 `:134` | `test_native_ready_metadata_survives_pause_finalization_and_idle_meter` |
| `tests/unit/test_power.py:52` | `test_suspend_requires_explicit_new_epoch_resume_and_keeps_originals` |
| `tests/ui/test_gpu_runtime_ui.py:139` | `world` fixture |
| `tests/ui/test_live_ui.py:247` | `test_deleting_current_finalized_session_releases_polling_and_close_handles` |
| 같은 파일 `:262` | `test_delete_pending_keeps_visible_reason_and_retries_hidden_session_after_reader_ack` |
| 같은 파일 `:304` | `test_playback_verifies_derived_and_original_hashes_before_player` |
| 같은 파일 `:349` | `test_optional_diarization_publishes_new_scoped_revision_and_preserves_parent` |

이 목록은 **같은 잠재 위험**이며 해당 지점 모두에서 CI 실패를 관측했다는 뜻이 아니다. 특히 timeout 거부·ACK 순서·느린 AI와 저장 분리의 지연 assertion을 일괄 완화하지 않는다. 필요하면 원본 준비 도우미의 상한과 의도적 시간 시험을 나누는 후속 단위로 다룬다. 이번 검토에서는 다른 시험이나 제품 기본값을 수정하지 않았다.

## 6. 산출물과 미검증 사항

증거 루트 아래 파일의 LF SHA-256:

| 파일 | SHA-256 |
| --- | --- |
| `R/test_gt02_independent.py` | `ec7cdfb1d80f2a9296ff82cdb47b1da5a809e6d14231671b529550a1fa661104` |
| `default-stop-inventory.json` | `0379829e4584acbe23abf80381a223f4e4285221f4ca8503083f6bf7d9a236b2` |
| `mutation-results.json` | `d0c76cbc802bb1fb98e73b70c7b39d9820bbc86e6f3cf18466b6df3326fb6983` |
| `selected.xml` | `6758ab182a0883a5dc2b639bc08077d83487fd6eb65e96d03b96a44065763c95` |
| `independent.xml` | `a55d903f0b3daa3cf1409ce19ffb76970251d7e0ffe031f9c10c11a61377b696` |

미확인 항목은 CI 원문·재실행 결과, 실제 원격 부하의 실패 재현, 전체 회귀·coverage·전체 mypy다. 다른 단위의 기존 PASS로 대신하지 않는다.

이번 수정은 기능 시험의 대기 상한만 늘리고 취소·원본·ACK 검증을 유지한다. **OPEN 1건(S3, GT02-01 CI 원문 대조), S0/S1/S2 0**이다. 저장소에는 이 검토 문서만 추가했다.

## RECHECK

2026-11-23, 같은 검토자 w5:p8 Codex. C00가 보관한 두 로컬 CI 원문을 읽어 **GT02-01을 RECHECKED**로 판정한다. 기존 검토는 이력으로 보존했다. 추가 전 문서 LF SHA-256은 최초 제출값 `1f55af68cbf75f4036a773cf153262079d71d6a3f4a37463bbcb1ec2f9fa0b95`와 일치했다.

### 원문 식별과 직접 대조

두 파일은 읽기만 했으며 변경하지 않았다. 아래 해시는 로그의 **원시 바이트 SHA-256**이다. CRLF를 LF로 바꿔 산출한 검토 문서의 해시와 구별한다. 1차 파일은 C00가 준 `149b5acd…3623`과 일치한다.

| 시도·로컬 파일 | 원시 바이트 SHA-256 | 원문 결과 |
| --- | --- | --- |
| 1차 `build/ci-evidence/run-45076718852-core313-attempt1.log` | `149b5acddbf177f0ced889abf4ab84c05bbc412a197f45cb90c9518c17343623` | `:517` **1 failed, 8024 passed in 638.97s**; `:518` pytest 프로세스 exit1 |
| 재실행 `build/ci-evidence/run-45076718852-core313-attempt2.log` | `c34cdb359703633c895e5cce3cfb76867b21011e9bf7e0519394ab64afbf094e` | `:481` **8025 passed in 379.00s** |

두 로그의 `:33`에서 `core (3.13)`, `:145`에서 CPython **3.13.17**, `:106`에서 동일 checkout commit **`9f2cdf2978fa3a161fabdd3bdde5e850a1fcf930`**를 직접 확인했다. `:277`의 pytest 명령도 동일하며 ResourceWarning 오류화·coverage를 포함한다. run `45076718852` 및 job `137375470616`/`137379179035` 대응은 C00가 전달한 식별 정보다. 로그 본문에는 이 숫자 ID가 없어, 서버 API로 그 대응을 추가 인증했다는 주장은 하지 않는다.

1차 원문의 `:403-435`에서 다음 경로를 확인했다.

1. `test_cancel_revokes_publication_even_when_model_ignores_cancel`이 `session = recording(library)`에서 실패(`:407-412`).
2. `recording`의 **기본 인자 `service.stop()`** 호출(`:414-415`) → `RecordingService.stop`의 `_drain(timeout)`(`:416-417`).
3. `_drain`의 **timeout=5.0**(`:421`) → `_thread.join(timeout)` 뒤 `_thread.is_alive()` 검사(`:428-430`) → **WRITER_ACK_PENDING**(`:432-435`).

따라서 원래 취소·게시 assertion 이전에 원본 준비용 writer 종료 대기에서 실패했다는 C00 설명과 최초 코드 대조가 맞는다. 638.97초와 379.00초는 각각 **pytest 실행 요약의 소요시간**이며 설치·lint 등까지 포함한 workflow 전체 시간으로 확대하지 않는다.

### 재실행의 의미와 종결

재실행은 실패했던 **core job을 다시 실행하여 pytest 전체 8025개가 통과한 것**이다. 문제의 시험 하나만 골라 다시 통과했다는 뜻이 아니다. 두 시도는 모두 **GT-P02 변경 전 commit 9f2cdf2**이므로, 재실행 성공을 상한60초 수정본의 원격 CI 검증으로 세지 않는다.

같은 commit·Python 패치 버전·명령에서 한 번 실패하고 다음 실행은 통과했다는 사실은 **관측된 간헐성의 근거**다. 환경 부하/스케줄링/I/O 지연과 정합하지만 writer stack이나 진행 단계 관측이 없으므로 특정 지연 원인의 확정·다른 hang 원인의 일반적 배제·향후 무실패 보장은 하지 않는다. 이 한계는 기존 상한 변경의 기능 oracle 유지 판정과 구별한다.

로그 대조만 추가했으므로 제품 시험·mutation·정적 검사는 반복하지 않았다. 최초 고정 tree의 30 PASS·독립8 PASS·3개 변이 검출 증거는 그대로이며 새 실행 결과로 중복 집계하지 않는다. 네트워크·계정 조회나 Git 쓰기는 없었고 지정 검토 문서 끝에 이 절만 추가했다.

**GT02-01 RECHECKED, 신규 발견0, OPEN 0(S0 0·S1 0·S2 0·S3 0)**이다.
