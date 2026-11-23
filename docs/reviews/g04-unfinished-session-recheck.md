# G04-RR / G-P04 미확정 세션 확정 독립 재확인

2026-11-23, 재확인 검토자 Claude(C00 지정 하위 에이전트). 구현 작성은 w5:p7 Claude, 1차 검토는 w5:p8 Codex(`docs/reviews/g04-unfinished-session-review.md`, LF SHA256 `75e5e286034f4ced34e88ce38fa1c5f17be703b0dfe3ae51e430f421a69fafeb`), 수정 작성은 재배정된 w5:p8 Codex다. 이 검토자는 G-P04의 작성·1차 검토·수정에 관여하지 않았다.

**G04-01~05 모두 RECHECKED. 새 OPEN 1건: S2 1건(G04-06).** 원 반례 6건을 문서 절차대로 다시 작성해 실행했고 모두 기대대로 통과한다. G04-01의 약한 참조는 writer thread가 살아 있는 동안 owner를 유지하므로 GC 시점 때문에 live가 사라지지 않는다. 다만 G04-02 수정의 경로 검사 예외가 세션별 처리 밖으로 새어 나간다. 그래서 한 세션 폴더의 이상 항목(junction 또는 hard link)만으로 미확정 목록 전체가 실패하고, UI에서 다른 정상 세션의 확정도 막힌다(G04-06). 원 검토가 놓친 S0/S1은 찾지 못했다. 최종 수용은 C00가 결정한다.

## 1. 입력과 추출

- 대상 tree는 **`482a78f930f727bb792f122bc244873060eb8fd2`**(`git cat-file -t` = tree), 기준은 HEAD **`234dd31`**(G-P02b까지)다.
  - `git diff --stat 234dd31 482a78f9` 결과는 10파일, 3750 insertions / 29 deletions로 C00 지정 10파일과 같다.
  - 1차 검토 tree `5a5f0316`과 비교한 G-P04 파일 변경은 `recovery.py`·`library.py`·`ui/main.py`·시험 3파일·문서다.
  - `9d46b4a..234dd31` 사이에 G-P04 제품 5파일은 바뀌지 않았다(`git diff --stat` 출력 없음).
- 추출(작업 트리 판정 없음):
  - 판정·전체 회귀: `git -c core.autocrlf=false archive 482a78f9… | tar -x -C build/review-trees/g04`
  - 변이: `… pyproject.toml src tests | tar -x -C build/review-trees/g04-pristine`
- Python 9파일의 LF SHA256은 계약 문서 마지막 표(720~728행)와 **9/9 일치**한다(`build/review-trees/g04-hashes.txt`). 문서 자체는 `abbc4974fcfb9a717062d00c240cdec6013f1445f15a7252628273f8f268eb59`다.
- **원 반례 파일**: `C:/Users/gangd/AppData/Local/Temp/recoryn-g04r-96ggil2d/`가 이 세션에서 `Permission denied`라 읽지 못했다. 1차 검토 문서 §2·§3의 재현 절차로 **새로 작성**했다(`build/review-trees/g04/tests/review_g04/test_g04_recheck_probes.py`, LF SHA256 `8fc3c23666589f52943e46ecfd56a41f23c3093946a8475beb3b8a05387e167c`). 원 파일과 byte 동일성은 주장하지 않는다.
- 저장소 쓰기는 이 문서 하나뿐이다. git 쓰기, 네트워크, 설치, 실제 장치·모델, 추가 에이전트는 사용하지 않았다.
- **junction 정리**:
  - 이 검토의 junction은 모두 `build/review-trees/` 아래 TEMP에만 만들었고, 각 시험의 finally에서 reparse 속성을 확인한 뒤 junction만 `rmdir`했다.
  - 별도로, 기존 시험 `tests/unit/test_storage.py::test_directory_reparse_point_blocks_external_writes`가 이번과 이전 검토의 전체 회귀 basetemp에 남긴 junction 5개를 찾았다. 각각 reparse 속성을 확인한 뒤 junction만 제거했다. 대상 폴더 `outside`는 남아 있음을 `ls`로 확인했다.

## 2. 직접 실행한 명령과 결과

모든 실행에 `.venv` Python, `-B`, `PYTHONDONTWRITEBYTECODE=1`, `QT_QPA_PLATFORM=offscreen`, `HF_HUB_OFFLINE=1`, `-p no:cacheprovider`, 실행별 새 `--basetemp`를 사용했다.

| # | 명령(cwd) | 결과 |
| --- | --- | --- |
| G1 | 전체 회귀(g04, `PYTHONPATH=g04/src`, `TRANSFORMERS_OFFLINE=1`, `HF_HUB_DISABLE_TELEMETRY=1`, **`-W error::ResourceWarning`**, `-rs --junitxml …/g04-full.xml`) | **9506 수집 / 9504 passed / 2 skipped / failure 0 / error 0 / 경고 0, 263.08s, exit 0** |
| G2 | 검토자 probe 13 node(`-W error::ResourceWarning`) | **11 passed, 2 failed**. 실패 2건은 새 반례 G04-06이다 |
| G3 | `python -I build/review-trees/g04-mutate.py` | baseline 381 passed, **변이 8/8 KILLED**, invalid 0 |
| G4 | 새 4파일 `--co` / `ruff check` / 9파일 `ruff format --check` / `mypy src/recoryn` | **387 node**(작성자 보고와 같음) / PASS / 9 files already formatted / 71 source files no issues |

- G1의 2 skip은 앞 검토들과 같은 `test_gpu_smoke.py:107`(D: 볼륨의 8.3 이름 미생성)이다. 작성자의 9506 PASS/skip 0과의 차이는 이것뿐이다.
- probe 파일은 G1 수집에 포함되지 않았다(JUnit 0건).
- 변이 harness LF `ff128ad2c23ffc37271f963a8b506988c00eb136b5bff553c50cb59f11ea215e`, 결과 `build/review-trees/g04-mutations.json` LF `3cb6b4a2c4555588c2a1ac7e175d71e44e1a46be98a41892fa6b6228098c5569`.

## 3. G04-01~05 재확인

### G04-01 / RECHECKED — owner 등록은 모든 owner를 관찰한다

- **원 반례 재실행**: `test_orig_live_recording_cannot_be_hidden_by_another_owner[live/paused-resumed]` **2 PASS**. 두 변형 모두 다른 `is_live()=False` 객체를 등록한 뒤 `finalize_unfinished` → `SESSION_LIVE`다. 이어서 원래 서비스에 4프레임 submit → `stop(timeout=60)` 결과는 `frames 4`, `is_live False`, `worker_alive False`다. 1차의 "FINALIZED, frame 0, stop 뒤 live/worker True"와 반대다.
- **코드**: `library.py:230-252`. `_live_owners[session][id(owner)] = weakref.ref(owner)`로 같은 객체 재등록은 멱등이고, 다른 객체는 추가된다. `_is_live`는 죽은 참조만 정리하고 살아 있는 owner를 모두 조회해 하나라도 live면 live다. "교체 시점에 한 번만 보고 허용"하는 경로는 없다.
- **약한 참조 수명·GC**: `test_check_weak_owner_survives_while_writer_thread_runs` PASS.
  - 호출자의 유일한 강한 참조를 지우고 `gc.collect()`해도 writer thread의 bound target(`self._consume`) 때문에 owner가 살아 있고, `finalize/recover`가 `SESSION_LIVE`다.
  - stop 뒤 참조를 지우면 참조가 사라지고 확정은 멱등 결과(`already_finalized True`)를 낸다.
  - `RecordingService.is_live`는 `_accepting` 또는 writer thread 생존이다(`recording.py:61-68`). 입력을 받는 동안에는 thread가 살아 있다.
- **일시정지 owner**: `test_check_paused_owner_finalize_keeps_sealed_bytes_and_blocks_resume` PASS. 일시정지(입력 중단·writer join)한 owner는 live가 아니므로 확정할 수 있다. 확정 전후의 PCM bytes는 같고, 확정 뒤 `resume`은 `RESUME_REQUIRES_PAUSED`로 거부된다. 이는 C00의 CE1 범위("녹음 중" 거부)와 맞는다. UI는 현재 녹음기의 일시정지 세션 확정을 따로 막는다(`main.py:337-339`).
- **변이**: N1r(마지막 owner 하나만 보관) → `G04-FIX-OWNER-0`, N3r(강한 참조 보관) → `G04-FIX-WEAK-1`이 KILLED됐다.

### G04-02 / RECHECKED(원 결함) — 중첩 reparse를 따라 외부를 열거하지 않는다

- **원 반례 재실행**: `test_orig_inventory_rejects_nested_junction_before_listing[staging/tracks]` **2 PASS**. 실제 NTFS junction으로 같은 TEMP의 라이브러리 밖 폴더를 가리켜도 외부 경로 `iterdir` 관측이 0건이다(`listed []`). 결과는 `ValidationError`다.
- **코드**: `library.py:714-724`. `safe_path(base,"staging")`, `safe_path(base,"tracks")`를 쓰고, track/epoch 항목마다 `check_path`를 `is_dir/iterdir` 앞에서 호출한다.
- **변이**: N4a(staging의 safe_path 제거) → `G04-FIX-PATH-0`, N4b(epoch 검사 제거) → `G04-FIX-PATH-3`이 KILLED됐다.
- **단, 실패 범위가 세션 하나에 머물지 않는다.** 정상 세션까지 실패시키는 부작용은 새 발견 G04-06으로 따로 기록한다.

### G04-03 / RECHECKED — 검증된 청크만 보존량으로 센다

- **원 반례 재실행**: `test_orig_missing_catalog_payload_is_not_claimed_as_preserved[missing/corrupt]` **2 PASS**. 8프레임 청크의 audio.pcm을 지우거나 손상시키고 복구하면 `preserved 0`, `catalog [8]`이다. "원본은 보존" 문구는 없다.
- **코드**:
  - `recover_session`이 디스크 검증(`verify_bundle` 일치, 또는 staging 복구 artifact의 sha/byte 대조)을 통과한 ID만 `verified_chunk_ids`로 반환한다(`library.py:603-695`).
  - `recovery_view`는 예상량(catalog)과 보존량(verified)을 분리한다. 검증 정보가 없으면 "보존량을 확인하지 못했습니다"를 표시한다(`recovery.py:182-210`).
  - 삭제 대기 응답도 `verified_chunk_ids: []`를 포함한다.
- **변이**: N5r(catalog 전부를 보존 합산), N6r(복구가 모든 catalog ID를 검증으로 표기)이 `G04-FIX-MEDIA-2`에서 KILLED됐다.

### G04-04 / RECHECKED — DIRECTORY_ONLY 선택 시 이전 AI 패널이 비활성화된다

- **원 반례 재실행**: `test_orig_directory_only_selection_clears_previous_ai_session` PASS. a(전사 있음) → orphan 선택에서 details는 DIRECTORY_ONLY다. 패널은 `session_id 'a'`를 유지하지만 `panel/table` 모두 비활성이다. 이어서 b를 선택하면 다시 활성화되고 `session_id 'b'`, 내용 "text b"가 로드된다.
- **코드**: `main.py:461-470`. orphan에서 `ai_bridge.panel.setEnabled(False)`, 정상 세션에서 `setEnabled(True)` 뒤 `selection`. orphan은 `ContentStore.load`에 넘기지 않는다(작성자 시험의 load 관찰도 확인).
- C00가 허용한 "비우기 또는 비활성" 중 비활성 방식이다. 비활성 패널에는 이전 세션 a의 내용이 회색으로 남는다. 관찰로만 적고 결함으로 세지 않는다.
- **변이**: N7r(비활성 생략)·N8r(재활성 생략)이 `G04-FIX-UI-SELECT-0`에서 KILLED됐다.

### G04-05 / RECHECKED — 문서 표현이 정정됐다

계약 문서 §4.2(294~295행)는 "1008은 실행 가능 조합 F가 아니고 T72·K14는 같은 tuple 집합의 부분집합이 아니며, S×A×K 전수와 원인별 교차 coverage는 계수하지 않았다"로 바뀌었다. 선언 361 / 실행 365 node는 유지된다. "922"는 601·616행의 정정 이력에만 남아 있다.

## 4. 새 발견

### G04-06 / S2 / OPEN — 한 세션 폴더의 경로 이상이 미확정 목록 전체를 실패시켜 다른 정상 세션의 확정을 막는다

- **재현**: `test_new_one_unreadable_session_hides_other_unfinished_sessions[staging_junction/tracks_hardlink]`(2 FAIL). 두 INTERRUPTED 세션 `bad`, `good`(각 청크1)을 만들고, `bad`에만 다음 중 하나를 둔다.
  - `sessions/bad/staging`을 라이브러리 밖 TEMP 폴더로 가리키는 실제 NTFS junction
  - `sessions/bad/tracks/` 안의 hard link 파일 한 쌍(`os.link`)
- **실제(두 변형 동일)**:
  - `library.unfinished_sessions()` → `ValidationError`
  - 실제 `MainWindow`에서 `good`을 선택해도 `_finalize_allowed() False`. 안내는 "미확정 세션을 확인하지 못했습니다. ‘새로고침’으로 다시 확인하세요."다.
  - CLI `list --unfinished`도 같은 예외 경로(`cli.py:327-333`)로 실패한다(코드 읽기).
- **기대**: 이상 항목이 있는 세션만 "검사할 수 없음"으로 표시하거나 건너뛴다(외부 열거 0 유지). 다른 정상 미확정 세션은 계속 목록에 남고 확정할 수 있어야 한다. 1차 검토도 "안전 실패 또는 ‘검사할 수 없음’ 경고를 남긴 skip"을 기대로 적었고, 세션 하나의 이상으로 전체 기능을 끄는 것까지 요구하지 않았다.
- **원인**:
  - `_inventory_item`(`library.py:713-731`)은 세션별 `try … except OSError: pass`로 개별 실패를 흡수하려 한다. 그러나 새로 넣은 `safe_path/check_path`는 `ValidationError`(`ValueError` 하위, `domain/__init__.py:22`)를 던져 이 except를 빠져나간다. 그 결과 `_inventory()` 전체가 실패한다.
  - 같은 함수의 DIRECTORY_ONLY 루프는 `(ValueError, OSError)`를 잡아 `skipped`로 센다(`library.py:766-771`). 즉 세션별 허용이 기존 패턴이다.
  - UI는 예외 시 `_inventory`를 비워(`main.py:423-430`) `_finalize_allowed`가 모든 세션에서 False가 된다(`main.py:334-336`).
- **회귀 여부**: hard link 변형은 수정 전에는 `track.is_dir()` False로 건너뛰던 항목이다. 즉 이번 수정이 새로 만든 실패 경로다. junction 변형은 수정 전 외부 열거(G04-02)를 안전 실패로 바꾼 대가다.
- **영향과 등급**: 이상 항목(사용자나 다른 도구가 만든 reparse/hard link/특수 파일)이 있을 때만 발생한다. fail closed이고 외부 열거·원본 변경은 없다. 우회로는 CLI `recoryn finalize <id>`나 이상 항목 제거다. 하지만 G-P04의 핵심 기능(UI에서 미확정 세션을 찾아 확정)이 라이브러리 전체에서 꺼지고, 안내 문구의 "새로고침"으로는 풀리지 않는다. 그래서 S2로 분류했다. C00가 전체 안전 실패를 설계로 수용하면 S3 이하로 조정할 수 있다.
- **수정 제안**: `_inventory_item`의 except를 `(ValueError, OSError)`로 넓히고, 그 세션 항목에 `"inspect_failed": True` 같은 비민감 표지를 두어 개수를 미확인으로 표시한다. UI·CLI는 그 세션을 "검사할 수 없음"으로 보이고 나머지는 정상 처리한다. 정상 세션 + 이상 세션 혼재 시험(junction/hard link)을 추가한다.

## 5. 관점별 추가 점검

### 5.1 수정이 만든 다른 결함 여부

- **G04-01**: id 기반 키는 살아 있는 객체 사이에서 충돌하지 않는다(id 재사용은 이전 객체가 죽은 뒤에만 가능하며 그 참조는 이미 None). 정리는 `_is_live` 호출 때 이루어지고, 모든 접근은 root mutex 아래다. 다른 owner의 `is_live` 예외 처리는 바뀌지 않았다.
- **G04-02**: 정상 세션의 inventory 수치는 G1 전체 회귀(작성자 I/Q 가족 포함)와 원 반례 PASS로 확인했다. 거짓 실패 문제는 위 G04-06이다.
- **G04-03**: staging에서 이미 복구된 artifact를 디스크에서 다시 만드는 경우는 sha/byte를 대조해 검증에 넣는다. 다만 같은 결과의 앞쪽 bundle 반복에서 남긴 `MISSING_OR_INVALID_CATALOG_MEDIA` 경고는 그대로 남는다. 이는 "없어졌다가 staging에서 재구성됨"이라는 사실과 모순되지 않아 관찰로만 둔다.
- **G04-04**: 추가 결함을 찾지 못했다.

### 5.2 원 검토가 놓친 S0/S1 여부

다음 항목을 코드 읽기와 실행으로 확인했고 새 S0/S1을 찾지 못했다.

- **원본 bytes 보존**: 일시정지 owner 확정 전후 PCM bytes가 같다(5.1·3절 시험).
- **이중 확정**: FINALIZED 경로는 재봉인 없이 `already_finalized`로 응답하고 복구는 quarantine만 한다(`library.py:816-833`).
- **확정 중 삭제·녹음 시작 경쟁**: `finalize_unfinished`가 root mutex 안에서 의도 → live → 버전 → 복구 → 봉인을 수행한다. `resume`/`start`는 thread를 먼저 띄운 뒤 같은 mutex의 상태 전이를 하므로, 확정이 먼저면 전이가 실패하고, thread가 먼저면 `SESSION_LIVE`다(`recording.py:106-136`, `library.py:799-850`).
- **CLI·UI 오류 코드**: CLI는 예외 본문 없이 `type`·whitelist code만 출력한다(`cli.py:62`, `327-333`).

### 5.3 G-P05 경계(§3.1)

- `test_check_deletion_intent_stays_out_of_inventory_and_finalize[journal_only/completed]` **2 PASS**. 두 경우 모두 미확정 목록 제외, `finalize` → `DELETE_PENDING`, `recover` → `DELETE_PENDING`(채택·복원 0, `verified_chunk_ids []`)이고, 완료 tombstone은 폴더를 되살리지 않는다.
- 코드상 확정은 삭제 의도를 live보다 먼저 검사한다(`library.py:803-806`). `_is_live`는 세션별이어서 다른 세션을 막지 않는다. G-P05 §3.1의 요구와 일치한다. pending 목록 제공은 G-P05 범위로 남아 있다.

### 5.4 시험 독립성·변이 재현

- 새 FIX 시험의 기대는 손으로 쓴 프레임 수(8·4), 상태 문자열, 실제 파일 bytes 비교, `iterdir` 관측, 버튼 활성 상태다. 제품 helper로 기대를 계산하지 않는다(시험 diff 확인).
- 작성자 계획의 N1~N8과 같은 의도의 변이 8개를 검토자가 직접 작성해 8/8 KILLED를 확인했다(G3). 작성자의 18개 전체와 M1~M10은 재실행하지 않았다.

## 6. 관찰(결함으로 세지 않음)

- 기존 시험 `test_storage.py::test_directory_reparse_point_blocks_external_writes`는 만든 junction을 정리하지 않아 basetemp에 남긴다. G-P04 파일이 아니고 TEMP 위생 문제이므로 관찰로만 남긴다. 이번에 남은 것은 위 §1처럼 제거했다.
- G04-04의 비활성 패널은 이전 세션 내용을 표시한 채 회색으로 남는다. 혼동을 더 줄이려면 "다른 세션의 내용" 표지를 고려할 수 있다.

## 7. 미검증·한계

- 원 반례 TEMP 파일을 읽지 못해 문서 절차로 다시 작성했다.
- 실제 장치·전원 장애·실제 Narrator 판독·외부 backup 복원은 검증하지 않았다.
- 작성자 R 증거(9506 PASS, mutation 18/18)는 재실행하지 않았고, 검토자 실행 결과만 적었다.
- mypy는 `src/recoryn` 71파일 범위다.

## 8. 결론

**G04-RR REVIEW_READY: G04-01 RECHECKED / G04-02 RECHECKED(원 결함) / G04-03 RECHECKED / G04-04 RECHECKED / G04-05 RECHECKED. 새 OPEN 1 (S0 0 / S1 0 / S2 1 / S3 0)** — G04-06(세션 하나의 경로 이상으로 미확정 목록 전체 실패·UI 확정 불가). 수정 또는 수용은 C00가 결정한다.

## RECHECK 2 — 2026-11-23, G04-06 수정(FIX2) 재확인

같은 검토자(Claude)가 C00의 재확인 요청으로 작성자 Codex의 FIX2를 확인했다. 위 내용은 이력으로 보존한다.

**요약: G04-06 RECHECKED, G04-01~05 유지. 그러나 새 S1 2건을 찾았다. OPEN 2 (S0 0 / S1 2 / S2 0 / S3 0).**

- **G04-07**: FIX2가 만든 성능 회귀가 녹음 프레임 유실로 이어진다. FIX2는 미확정 목록 조회 때 세션의 모든 묶음과 그 안의 파일마다 경로 검사를 한다. 이 조회가 root mutex를 잡은 채 약 70배 느려졌다. 같은 mutex를 블록마다 쓰는 녹음 writer가 그동안 멈춰 진행 중 녹음의 프레임이 유실된다.
- **G04-08**: 1차 G-P04 tree부터 있던 결함이며, 원 검토와 이 검토자의 직전 재확인이 놓친 것이다. 다른 세션을 녹음하는 중에 오래된 큰 세션을 확정하면 같은 방식으로 프레임이 유실된다.

두 항목 모두 G04-06 기능 판정(세션 격리)과는 별개다. 기능은 C00 결정대로 동작한다.

### R2-1. 입력 고정

- 대상 tree는 **`98c20f8740a551a28c630145a575e43d792e278d`**(`git cat-file -t` = tree), 기준은 HEAD `234dd31`이다. `git diff --name-only 234dd31 98c20f87`은 G-P04 10파일이다. 직전 tree 대비 변경은 `git diff --stat 482a78f9 98c20f87 -- src tests docs/testing/g04-unfinished-session-cases.md` 기준 8파일 316+/13-다.
- 추출: `git -c core.autocrlf=false archive 98c20f87… | tar -x -C build/review-trees/g04b`(판정·회귀·측정).
- 제출 Python 9파일의 LF SHA256은 문서 §13(13.2 표 포함)의 기록과 **9/9 일치**한다. 문서 자체는 `eb654abfd97d324b4283e3eec8ea8d5e0220333640157e375ae06b829c7c1cc4`다.
- 쓰기는 이 문서 끝에 이 절을 추가한 것뿐이다. 측정 스크립트·반례·junction/hard link는 `build/review-trees/` 아래에만 두었다. 각 시험의 finally에서 링크만 제거했고 대상 파일·폴더는 남았다. 기존 storage 시험이 전체 회귀 basetemp에 남긴 junction 1개도 reparse 속성 확인 뒤 junction만 제거했다(대상 존재 확인).

### R2-2. 직접 실행 결과

| # | 명령(cwd) | 결과 |
| --- | --- | --- |
| H1 | 전체 회귀(g04b, `PYTHONPATH=g04b/src`, offscreen, HF/transformers offline·telemetry 차단, **`-W error::ResourceWarning`**, `-rs --junitxml …/g04b-full.xml`) | **9513 수집 / 9511 passed / 2 skipped / failure 0 / error 0 / 경고 0, 264.96s, exit 0** |
| H2 | 직전 재확인 probe 13 node(`test_g04_recheck_probes.py`, LF `8fc3c236…`, **무수정**) + 새 probe `test_g04b_probes.py` 5 node(LF `8667bb1efd6d060b74675b24d8ee0418f98d1682685ed1bfe3a0d853f861df60`), `-W error::ResourceWarning` | **18 passed, 0 failed** |
| H3 | 새 4파일 `--co` / `ruff check` / 변경 7파일 `ruff format --check` / `mypy src/recoryn` | **394 node** / PASS / 7 files already formatted / 71 source files no issues |
| H4 | 목록 조회 시간 비교 `python -I build/review-trees/g04b-perf.py <src> <work> N 3`(LF `27198ebc…`), 직전 tree `g04`와 이 tree `g04b` | 아래 표 |
| H5 | 녹음 중 refresh식 조회의 유실 `g04b-drop.py`(LF `1500de3d…`) | 아래 표 |
| H6 | 녹음 중 오래된 세션 확정의 유실 `g04b-drop2.py`(LF `1060d5cc…`) | 아래 표 |

H1의 2 skip은 앞 절과 같은 `test_gpu_smoke.py:107`(D: 볼륨의 8.3 이름 미생성)이다. probe 파일은 H1 수집에 포함되지 않았다(JUnit 0건). H4~H6은 다른 시험이 돌지 않는 상태에서 직렬로 실행했다.

### R2-3. G04-06 판정 — RECHECKED

- **원 반례**: `test_new_one_unreadable_session_hides_other_unfinished_sessions[staging_junction/tracks_hardlink]`가 **2 PASS**다(직전 2 FAIL). 목록은 `['bad','good']`이고, UI에서 `good`을 선택하면 `_finalize_allowed True`다. 안내에는 미확정 1건과 "검사할 수 없는 세션 1건은 복구·확정을 보류합니다. 해당 세션을 선택해 링크·하드 링크 또는 접근 권한을 확인한 뒤 새로고침하세요."가 함께 나온다.
- **새 probe**: `test_unsafe_session_is_isolated_refused_and_recoverable_after_fix` 4행 PASS. 실제 NTFS의 staging junction / tracks 아래 junction / tracks 아래 hard link / catalog 묶음의 `audio.pcm` hard link를 각각 넣었다.
  - `bad`: `inspection_error INSPECTION_UNSAFE`, 개수 `None`
  - `good`: `inspection_error None`, `finalize_unfinished("good")` → `FINALIZED, 4프레임`
  - `bad`의 `recover_session`·`finalize_unfinished` 모두 `INSPECTION_UNSAFE`. `bad`의 상태와 폴더 bytes(링크 제외)는 그대로이고, 외부 canary도 그대로다.
  - 외부 경로의 `iterdir` 관측은 0건이다.
  - UI: `bad` 선택 시 확정 불가, 상세 안내에 링크 제거와 새로고침 지시가 있고, `recover_selected` 뒤에도 `INTERRUPTED`다.
  - 링크만 제거하면 같은 `bad`가 다시 검사 가능해지고 확정 `FINALIZED, 4프레임`이다. 즉 해결 경로가 실제로 동작한다.
- **fail-open 점검**:
  - `test_refusal_precedence_keeps_deletion_and_live_first` PASS. junction이 있는 세션에 삭제 의도가 있으면 목록 제외, 확정 `DELETE_PENDING`, 복구 `DELETE_PENDING`이다.
  - 코드상 검사 순서는 삭제 의도 → writer/live → `_require_inspection_safe` → 상태다(`library.py:579-582`, `823-826`). 검사 실패는 `StateConflict`로 거부되고 복구·확정 본체에 들어가지 않는다.
  - `_inventory_item`은 `ValidationError`를 `INSPECTION_UNSAFE`, `OSError`를 `INSPECTION_UNAVAILABLE`로 세션 안에서 닫고 개수를 `None`으로 바꾼다.
  - staging 항목과 묶음은 `check_path` 뒤에만 `is_dir`를 호출하고, 하위 세 파일도 `check_path`로 검사한다. 외부 열거를 다시 허용하는 경로는 찾지 못했다.
  - CLI는 `recover`에도 닫힌 code를 붙인다(`cli.py` `_REFUSAL_CODES`).

### R2-4. G04-01~05 유지

H2에서 직전 재확인의 13 node가 무수정으로 모두 PASS다. 각 항목은 다음과 같다.

- **G04-01**: 두 owner 변형 모두 `SESSION_LIVE`이고, 정지 후 4프레임으로 확정된다. GC 중에도 owner 생존이 유지되고, 일시정지 확정 시 bytes가 보존된다.
- **G04-02**: junction 2행에서 외부 열거 0건이다. 결과는 이제 예외가 아니라 해당 세션 항목의 `INSPECTION_UNSAFE`다.
- **G04-03**: 손상·없음 2행 모두 보존량 0이다.
- **G04-04**: DIRECTORY_ONLY 비활성 후 정상 세션이 재활성화된다.
- **G-P05**: 삭제 의도 경계 2행이 그대로다.
- **G04-05**: 문서 §4.2는 바뀌지 않았다.

### R2-5. 새 발견

#### G04-07 / S1 / OPEN — FIX2의 목록 조회 검사가 root mutex 안에서 약 70배 느려져 진행 중 녹음의 프레임을 유실시킨다

- **근거(코드)**:
  - `_inventory()`는 전체 조회 동안 `self._mutex`(= `root_mutex(root)`)를 잡는다(`library.py:762` 부근).
  - FIX2의 `_inspect_media_path`는 staging 항목과 모든 묶음마다 `check_path`를 1회, 하위 `audio.pcm`·`blocks.jsonl`·`descriptor.json`에 3회 더 호출한다. `check_path`는 매번 모든 상위 경로 구성요소를 `lstat`한다(`storage/_safe.py:114-131`).
  - 녹음 writer의 `ChunkWriter.append`와 `seal`은 **블록마다 같은 root mutex**를 잡는다(`storage/chunks.py:343`, `396`).
  - `MainWindow.refresh_sessions`는 GUI thread에서 `unfinished_sessions()`와 `inventory_warnings()`를 연달아 호출하므로 `_inventory()`가 **두 번** 실행된다(`main.py` refresh_sessions). refresh는 녹음 시작 직후(`started`), 일시정지·재개, 절전 복귀, 새로고침 버튼, 복구·확정·삭제 결과에서 호출된다.
  - 조회 대상은 녹음 중인 세션을 포함한 모든 미확정 세션이다.
- **측정 H4(조회 3회, 초)**:

  | 묶음 수 | 직전 tree 482a78f9 | 이 tree 98c20f87 |
  | --- | --- | --- |
  | 1,800 | 0.008 | 0.66 |
  | 7,200 | 0.043 | 2.86~3.08 |

  7,200은 기본 2초 청크 기준 2시간·2트랙 세션의 묶음 수다.
- **재현 H5**: 묶음 7,200개의 미확정 이전 세션이 있는 라이브러리에서 새 세션을 실제 `RecordingService`(48 kHz mono 1트랙)로 녹음한다. 10 ms 블록을 실시간 속도로 6초 submit하고, 0.5초 시점에 다른 thread가 refresh와 같은 두 호출을 실행한다.
  - **이 tree**: refresh 5.897초, **거부 293블록 / 유실 140,640프레임(약 2.93초)**
  - **직전 tree**: 0.073초, 유실 0
  - 묶음 1,800개: 이 tree 1.356초, 유실 0(1트랙 기준)
- **영향**:
  - 사용자 조작(이전의 긴 미확정 세션이 있는 상태에서 새 녹음 시작, 긴 녹음 중 재개·새로고침)만으로 진행 중 녹음의 원본 프레임이 복구 불가능하게 유실된다. 유실은 health의 QUEUE_DROP gap으로 기록되지만 음성은 남지 않는다.
  - 실제 앱은 마이크와 시스템 2트랙이 같은 큐(256블록)를 나눠 쓴다. 그래서 버퍼 시간은 1트랙 측정보다 짧다. 이는 추정이며 실장비로 측정하지 않았다.
  - 녹음 저장 경로의 독립성(제품 불변식)을 깨는 핵심 기능 실패이므로 S1로 분류했다.
- **기대**: 미확정 목록 조회나 화면 갱신이 녹음 writer를 녹음 큐 용량 이상 멈추게 하지 않는다.
- **수정 제안**(C00 결정):
  1. 파일 시스템 검사를 root mutex 밖에서 수행한다. mutex 안에서는 DB 행만 snapshot한다.
  2. 상위 경로를 반복 `lstat`하는 `check_path` 대신 `os.scandir`의 `DirEntry` 속성(reparse 여부)으로 항목만 검사한다. hard link 검사는 실제 복구·확정 단계로 미룬다.
  3. 녹음 중(live) 세션은 조회 검사에서 제외한다.
  4. refresh 한 번에 `_inventory()`를 한 번만 실행한다.
  5. 대량 묶음 + 동시 녹음의 유실 0을 단언하는 시험을 추가한다.

#### G04-08 / S1 / OPEN — 다른 세션을 녹음하는 중 오래된 큰 세션을 확정하면 복구 검증 전체가 root mutex 안에서 실행돼 프레임이 유실된다

- **근거(코드)**:
  - `finalize_unfinished`는 root mutex를 잡은 채 `recover_session` 전체(모든 묶음의 `verify_bundle` 읽기·hash, staging 복구)를 실행하고 봉인까지 한다(`library.py:813-870` 부근, `561-706`).
  - UI의 `_finalize_allowed`는 현재 녹음기 세션이 아니면 **녹음 중에도** 다른 미확정 세션의 확정을 허용한다(`main.py:331-343`).
  - writer는 같은 mutex를 블록마다 잡는다(G04-07 근거와 같다).
- **재현 H6**: 실제 봉인 묶음 900개(각 96,000프레임, 30분 mono)의 INTERRUPTED 이전 세션이 있다. 다른 세션을 실시간 속도로 10초 녹음하는 중, 0.5초 시점에 `finalize_unfinished("old")`를 다른 thread에서 실행한다. MainWindow는 이 호출을 worker에서 실행한다.
  - **직전 tree**: 확정 9.49초, 거부 693블록 / **유실 332,640프레임(약 6.9초)**
  - **이 tree**: 확정 10.48초, **같은 유실**
- **범위**:
  - finalize는 G-P04 신규 기능이며 1차 tree부터 같은 구조다. 원 검토와 이 검토자의 직전 재확인(§5.2 "새 S0/S1 없음")이 놓쳤다. FIX2가 만든 결함은 아니다.
  - 기존 `recover_selected`의 복구도 같은 mutex 구조다. 코드로는 녹음 중 복구도 같은 위험이 있다고 판단하지만 직접 측정은 확정 경로만 했다.
- **영향**: G04-07과 같은 원본 프레임 유실이며 S1이다. 우회는 녹음 중에는 확정·복구를 하지 않는 것이다.
- **수정 제안**(C00 결정):
  1. 녹음이 진행 중이면 다른 세션의 확정·복구를 UI·CLI에서 보류한다(가장 작은 수정).
  2. 또는 무거운 검증을 mutex 밖에서 수행하고 봉인 직전에만 mutex 안에서 재검사한다. 이 경우 writer와 삭제 fence의 잠금 구조 변경 여부를 먼저 계약으로 정한다.
  3. 대량 세션 확정 + 동시 녹음 유실 0 시험을 추가한다.

### R2-6. 미검증·한계

- 유실 측정은 합성 PCM과 이 PC의 SSD·warm cache에서 했다. 실제 WASAPI 2트랙, 느린 디스크, 백신 검사 환경의 수치가 아니다. 시간 값은 환경마다 다르다. 직전 tree와 같은 스크립트로 비교한 상대 차이와 유실 유무를 근거로 삼는다.
- H4의 묶음은 빈 placeholder 파일이며 경로 검사 비용만 잰다. H6은 실제 봉인 묶음이다.
- 작성자 R 증거(1,043 PASS, mutation 5/5)는 재실행하지 않았다.

### R2-7. RECHECK 2 결론

**G04-06 RECHECKED / G04-01~05 유지. 새 OPEN 2 (S0 0 / S1 2 / S2 0 / S3 0)** — G04-07(FIX2 조회 검사의 mutex 보유 시간 증가로 녹음 프레임 유실), G04-08(녹음 중 큰 세션 확정의 mutex 보유로 프레임 유실, 1차 tree부터 존재). S1이 열려 있으므로 품질 체계의 push 게이트 판단은 C00가 한다.

## RECHECK 3 — 2026-11-23, G04-07·08 수정(FIX3) 재확인

같은 검토자(Claude)가 작성자 Codex의 FIX3(root mutex 축소 + 세션 단위 claim)를 확인했다. 위 내용은 이력으로 보존한다.

**요약: G04-07 RECHECKED, G04-08 RECHECKED, G04-01~06 유지. 그러나 claim 설계에서 새 S1 1건, 화면 정지 S3 1건을 찾았다. OPEN 2 (S0 0 / S1 1 / S2 0 / S3 1).**

- **G04-10(S1)**: 녹음 중인 세션에 대한 복구·확정 요청은 결국 거부된다. 그런데 거부되기 전에 그 세션에 배타 claim을 먼저 건다. 그 순간 녹음 writer가 청크를 등록하면 등록이 거부되어 녹음이 중단된다.
- **G04-09(S3)**: 미확정 목록 조회는 여전히 GUI thread에서 동기로 약 3초 걸린다. 녹음은 막지 않는다.

### R3-1. 입력 고정

- 대상 tree는 **`27eca03fe4c97c9eff99abb14a876cac3a60099d`**(`git cat-file -t` = tree), 기준은 HEAD `234dd31`이다. `git diff --name-only 234dd31 27eca03f`는 G-P04 10파일이다. 직전 tree 대비 변경은 5파일 792+/141-로 C00 설명과 같다.
- 추출: `git -c core.autocrlf=false archive 27eca03f… | tar -x -C build/review-trees/g04c`.
- 제출 Python 9파일의 LF SHA256은 문서 §14(14.2 포함)의 기록과 **9/9 일치**한다. 문서 자체는 `86659370c267b1cb4c86c99aae82a89b781f7a64f3b40091cef79193bda82117`다.
- 쓰기는 이 절 추가뿐이다. 측정·반례는 `build/review-trees/` 아래에만 두었다. junction은 시험 finally에서 링크만 제거했다. 기존 storage 시험이 전체 회귀 basetemp에 남긴 junction 1개도 링크만 제거했고 대상 존재를 확인했다.

### R3-2. 직접 실행 결과

| # | 명령 | 결과 |
| --- | --- | --- |
| J1 | 전체 회귀(g04c, `PYTHONPATH=g04c/src`, offscreen, HF/transformers offline·telemetry 차단, **`-W error::ResourceWarning`**, `--junitxml …/g04c-full.xml`) | **9532 수집 / 9530 passed / 2 skipped / failure 0 / error 0 / 경고 0, 369.34s, exit 0** |
| J2 | 검토자 probe 30 node(직전 13 + `test_g04b_probes.py` 5 + 새 `test_g04c_claim_probes.py` 8(LF `6116c6bb949cdc60bc43dd1393b677df1f7887f6cc14338e274564901741a759`) + `test_g04c_live_claim_race.py` 4(LF `d492577c3634bf58ca18dde43e4b35d093a9cba67bd848fbab3070033014a7f6`)), `-W error::ResourceWarning` | 최종 실행 **29 passed, 1 failed**. 실패는 G04-10 반례이고 비결정적이다(첫 실행에서는 recover·finalize 2변형 모두 실패) |
| J3 | 새 4파일 `--co` / `ruff check` / 변경 4파일 `ruff format --check` / `mypy src/recoryn` | **413 node** / PASS / 4 files already formatted / 71 source files no issues |
| J4 | `g04b-perf.py`, `g04b-drop.py`, `g04b-drop2.py`(RECHECK 2와 같은 파일·조건, 직렬 실행) | 아래 R3-3 |
| J5 | `g04c-live-rate.py`(LF `5e638b4eb583e06be5cd66af65952b7e02ee2a8b22c906558b0f964ecdb5efaf`) | 아래 G04-10 |

J1의 2 skip은 앞 절과 같은 `test_gpu_smoke.py:107`이다. 수행 시간이 앞 실행들보다 긴 것은 검토자 probe를 일부 병행했고 작성자의 대량 성능 시험이 추가됐기 때문으로 보며, 실패와는 무관하다.

### R3-3. G04-07·G04-08 재측정 — 둘 다 RECHECKED

| 측정(같은 스크립트·조건) | 482a78f9 | 98c20f87(FIX2) | **27eca03f(FIX3)** |
| --- | --- | --- | --- |
| `unfinished_sessions()` 1회, 묶음 1,800 / 7,200(초) | 0.008 / 0.043 | 0.66 / 2.86~3.08 | **0.67~0.69 / 2.94~3.11** |
| 녹음 중 refresh식 조회(2회 호출), 묶음 1,800: 시간 / 유실 | 0.018s / 0 | 1.356s / 0 | **1.456s / 0** |
| 같은 조건, 묶음 7,200: 시간 / 거부 / 유실 | 0.073s / 0 / 0 | 5.897s / 293 / **140,640** | **8.616s / 0 / 0** |
| 녹음 중 30분 세션(실제 봉인 묶음 900) 확정: 시간 / 거부 / 유실 | 9.49s / 693 / **332,640** | 10.476s / 693 / **332,640** | **13.828s / 0 / 0** |

- **G04-07 RECHECKED**: 조회 비용(약 3초/7,200묶음)은 그대로지만 root mutex 밖에서 실행된다. 같은 조건의 녹음 유실이 140,640프레임에서 0으로 바뀌었다.
  - 코드: `_inventory()`는 mutex 안에서 삭제 의도, 행, catalog ID, live 여부만 snapshot하고, 폴더 검사는 밖에서 한다.
  - UI는 refresh당 `unfinished_inventory()`를 한 번만 호출한다.
- **G04-08 RECHECKED**: 확정은 더 오래 걸리지만 다른 세션의 녹음 유실이 332,640프레임에서 0으로 바뀌었다.
  - 코드: `finalize_unfinished`와 `recover_session`은 세션 claim 아래에서 검증(`verify_bundle`), 복구 기록, manifest 계산을 mutex 밖에서 한다.
  - `register_chunk`의 hash 검증도 mutex 밖으로 옮겨졌다. mutex 안에서는 상태 확인과 짧은 commit만 한다.

### R3-4. claim 설계 점검

다음은 `test_g04c_claim_probes.py`로 확인했다. 대부분의 시험은 `verify_bundle` 호출 중간(mutex 밖 구간)에서 작업 thread를 멈춘 뒤 경쟁 동작을 넣는다.

- **확정·복구 중 삭제**: `[finalize/recover]` 2 PASS.
  - 삭제는 0.01초 안에 반환한다(mutex가 비어 있음). 결과는 `DELETE_PENDING / SESSION_OPERATION_IN_PROGRESS`로 보류되고 파일을 지우지 않는다.
  - 재개된 확정은 `DELETE_PENDING`으로 포기한다(FINALIZED 사건 0). 원본 `audio.pcm` hash는 그대로다.
  - 목록에서는 제외되고, 삭제를 재시도하면 `DELETED_LOCAL`로 폴더가 제거된다.
- **두 번째 확정**: PASS. 두 번째 호출은 세션 잠금에서 대기한다. 첫 번째는 `already_finalized False`, 두 번째는 `True`이고 프레임이 같으며 FINALIZED 사건은 1개다. bytes는 그대로다.
- **녹음 재개(녹음 시작 경쟁)**: PASS. 일시정지 owner의 `resume()`은 `StateConflict: SESSION_OPERATION_IN_PROGRESS`로 거부되고 writer가 남지 않는다. 확정은 일시정지 전 3블록(1,440프레임)으로 완료되고 bytes는 그대로다.
- **TOCTOU(검사 뒤 생긴 junction)**: 확정 도중 `tracks/late` junction을 새로 만들어도 외부 열거는 0건이다. 확정은 catalog 묶음 6개만 봉인한다. 해당 bundle 열거가 이미 끝난 뒤라 새 항목을 따라가지 않았기 때문이며, 외부를 읽거나 목록에 넣지 않으므로 fail-open이 아니다. 봉인된 세션 폴더에는 그 링크가 남는다. 그 세션의 이후 복구는 `INSPECTION_UNSAFE`로 거부된다(관찰).
- **프로세스 kill 뒤 claim 잔류**: `[2/9/15]` 3 PASS. 별도 Python 프로세스가 확정 중
  - 복구 검증(호출 2),
  - 복구 manifest 계산(호출 9),
  - FINALIZING 전이 뒤 봉인 manifest 계산(호출 15)

  에 멈춘 상태에서 프로세스를 kill했다. 부모가 같은 라이브러리를 다시 열 수 있었다(OS 잠금 해제). kill 직후 상태는 각각 INTERRUPTED/INTERRUPTED/FINALIZING이고 FINALIZED 사건은 0이다. 재시도 확정은 `FINALIZED`, 원래 프레임 2,880, 사건 1개이고 원본 hash가 같으며, 그 다음 확정은 `already_finalized`다. claim은 프로세스 메모리에만 있어 재시작 뒤 남지 않는다.
- **이중 확정·fail-open**: 위 시험과 코드 읽기로 찾지 못했다. 봉인 commit은 mutex 안에서 manifest의 generation·state_version 재확인, claim, 삭제 의도, live를 확인한 뒤에만 실행된다(`finalize_session`, `_manifest_current`).
- **경계**: 아래 G04-10은 이 claim 설계가 **live 세션의 writer**와 상호작용하는 경로의 결함이다.

### R3-5. G04-01~06 유지

J2에서 직전 재확인 13 node와 `test_g04b_probes.py` 5 node가 모두 PASS다. 각 항목은 다음과 같다.

- G04-01: owner 2변형, GC, 일시정지 확정
- G04-02: junction 2행, 외부 열거 0
- G04-03: 손상·없음 2행에서 보존량 0
- G04-04: DIRECTORY_ONLY 전환
- G04-06: 문제 세션 4종 격리, 정상 세션 확정, 링크 제거 뒤 재확정
- G-P05: 삭제 의도 경계
- G04-05: 문서는 바뀌지 않았다.

### R3-6. 새 발견

#### G04-10 / S1 / OPEN — 녹음 중인 세션에 대한 (거부될) 복구·확정 요청이 claim을 먼저 걸어 그 세션의 녹음 writer를 중단시킬 수 있다

- **근거(코드)**:
  - `_session_operation`은 세션 잠금을 얻은 뒤 mutex 안에서 **배타 claim을 먼저 기록**한다.
  - live·삭제 의도 검사는 그 뒤 본문에서 별도의 mutex 구간으로 한다(`recover_session`, `finalize_unfinished`). 거부 예외 처리기도 별도 mutex 구간에서 삭제 의도를 다시 읽는다. 그동안 claim은 유지되고 `finally`에서야 해제된다.
  - 녹음 writer의 `register_chunk`는 mutex를 얻은 뒤 `_check_claim`에서 **다른 thread의 배타 claim이 있으면 `StateConflict("SESSION_OPERATION_IN_PROGRESS")`**를 던진다.
  - `RecordingService._consume`은 이 예외로 `_writer_error`를 세우고 입력 수락을 끈다. 즉 녹음이 중단된다(`recording.py:205-221`).
  - UI의 `recover_selected`는 녹음 중인 행에서도 라이브러리 호출을 실행하고 거부 메시지로 응답한다(U7 경로).
- **재현**:
  - `test_g04c_live_claim_race.py::test_refused_operation_on_live_session_does_not_fail_its_writer[recover/finalize]`: 실제 `RecordingService`로 블록마다 청크를 봉인하는 공격적 설정(`chunk_frames=480`)을 쓴다. 3초 동안 실시간 submit하면서 다른 thread가 같은 세션에 `recover_session`/`finalize_unfinished`를 반복 호출한다.
    - 첫 실행(두 변형 모두 실패): recover는 `writer_error StateConflict('SESSION_OPERATION_IN_PROGRESS')`, `storage_failed True`, 거부 216/300블록. finalize는 거부 287/300블록이다.
    - writer가 죽은 뒤에는 세션이 live가 아니게 되어 이후 요청이 `ACCEPTED`(recover 17회, finalize 75회)로 바뀌었다. finalize는 중단 시점까지의 내용으로 세션을 봉인했다.
    - 최종 실행에서는 recover 변형만 실패했다(비결정적).
  - `g04c-live-rate.py`(같은 공격적 설정, 연속 클릭):
    - **FIX3 tree**: 96번째 클릭에서 writer 실패, 거부 262블록
    - **직전 tree 98c20f87**: 218회 클릭에도 실패 0. FIX3가 만든 경로다.
  - **기본 설정(2초 청크)**: 30초 동안 50ms 간격 387회, 20초 동안 연속 25,420회 클릭에서 실패를 관측하지 못했다. 청크 등록이 몇 초에 한 번이라 겹칠 확률은 매우 낮다.
  - 지연 주입(삭제 journal 목록 0.3초)한 단일 클릭 결정적 재현은 성공하지 못했다(2 PASS). GIL·잠금 재획득 순서상 writer가 그 틈을 얻지 못했다.
- **영향과 등급**: 발생하면 진행 중 녹음이 중단되어 그 뒤 입력이 모두 거부된다(health에 저장 실패로 기록, 음성 손실 복구 불가). 핵심 기능 실패이므로 정의상 S1로 분류했다. 다만 기본 2초 청크에서는 재현하지 못할 정도로 확률이 낮다. 등급 조정은 C00가 판단한다.
- **기대**: 거부될 요청(live·삭제 의도)은 claim을 남기지 않는다. 다른 세션 관리 동작이 live writer의 청크 등록을 실패시키지 않는다.
- **수정 제안**:
  1. `_session_operation`에서 claim을 기록하는 같은 mutex 구간 안에서 삭제 의도·live를 먼저 확인하고, 거부면 claim을 기록하지 않는다.
  2. 또는 live owner/writer의 `register_chunk`는 claim 검사 대상에서 빼고, live가 아님을 확인한 뒤에만 claim을 건다.
  3. 공격적 청크 설정과 반복 요청에서 writer 실패 0을 단언하는 시험을 추가한다.

#### G04-09 / S3 / OPEN — 미확정 목록 조회가 GUI thread에서 동기로 실행되어 큰 미확정 세션이 있으면 화면이 수 초 멈춘다

- **근거**: `MainWindow.refresh_sessions`는 GUI thread에서 `unfinished_inventory()`를 호출한다. FIX2의 묶음별 경로 검사 비용(묶음 7,200개에 약 3초)은 FIX3에서도 그대로다(R3-3 표). mutex 밖이라 녹음은 막지 않지만, refresh(녹음 시작 직후, 일시정지·재개, 새로고침, 작업 결과) 동안 화면이 멈춘다. 녹음 중 세션 자신도 조회 대상이라 긴 녹음 중의 재개·새로고침에도 적용된다.
- **영향**: 녹음 유실은 0이다(위 측정). 화면 반응성만 떨어진다(482a78f9의 0.043초 대비 약 70배).
- **수정 제안**: 조회를 worker에서 실행하고 결과만 GUI에 반영한다. 또는 `os.scandir` 속성을 써서 항목 단위 검사로 비용을 줄이고, live 세션은 조회 검사에서 제외한다.

### R3-7. 미검증·한계

- 측정은 합성 PCM과 이 PC의 SSD·warm cache 기준이며, 실제 WASAPI 2트랙·느린 디스크·백신 환경이 아니다.
- G04-10의 실제 사용 빈도는 측정하지 않았다. 기본 설정에서 관측 0이라는 사실과 공격적 설정의 재현만 근거로 한다.
- 작성자 R 증거(9,532 PASS, mutation 12/12, mutex 최대 시간)는 재실행하지 않았다.

### R3-8. RECHECK 3 결론

**G04-07 RECHECKED(유실 140,640→0) / G04-08 RECHECKED(유실 332,640→0) / G04-01~06 유지. 새 OPEN 2 (S0 0 / S1 1 / S2 0 / S3 1)** — G04-10(거부될 복구·확정의 선행 claim이 live writer를 중단시킬 수 있음, 확률 낮음), G04-09(GUI thread 동기 조회 정지). push 게이트 판단은 C00가 한다.

## RECHECK 4 — 2026-11-23, G04-09·10 수정(FIX4) 재확인

같은 검토자(Claude)가 작성자 Codex의 FIX4를 확인했다. 위 내용은 이력으로 보존한다.

**요약: G04-10 RECHECKED, G04-09 RECHECKED, G04-01~08 유지. FIX4의 목록 재구성 신호 차단 때문에 새 S3 1건(G04-11)을 찾았다. OPEN 1 (S0 0 / S1 0 / S2 0 / S3 1).**

### R4-1. 입력 고정

- 대상 tree는 **`8aca05533d23fe7c22f2bc5d25f0250990798d1c`**(`git cat-file -t` = tree), 기준은 HEAD `234dd31`이다. `git diff --name-only 234dd31 8aca0553`은 10파일이다. 직전 tree 대비 변경은 6파일 707+/30-로 C00 설명과 같다.
- 추출: `git -c core.autocrlf=false archive 8aca0553… | tar -x -C build/review-trees/g04d`.
- 제출 Python 9파일의 LF SHA256은 문서 §15의 기록과 **9/9 일치**한다. 문서 자체는 `0b44077ee7f4f9e4397d4059d686f2d1cf05eeb336e43bbe1f5cd7466a233b45`다.
- 쓰기는 이 절 추가뿐이다. 측정·반례는 `build/review-trees/` 아래에만 두었다. 기존 storage 시험이 전체 회귀 basetemp에 남긴 junction 1개는 링크만 제거했고 대상 존재를 확인했다.

### R4-2. 직접 실행 결과

| # | 명령 | 결과 |
| --- | --- | --- |
| K1 | 전체 회귀(g04d, `PYTHONPATH=g04d/src`, offscreen, HF/transformers offline·telemetry 차단, **`-W error::ResourceWarning`**, `--junitxml …/g04d-full.xml`) | **9547 수집 / 9545 passed / 2 skipped / failure 0 / error 0 / 경고 0, 404.81s, exit 0** |
| K2 | 검토자 probe 34 node(이전 30 + 새 `test_g04d_ui_probes.py` 4, LF `788c6769f143c6c94ee8ff73448d9e1707958c2e994c3fcae09db071d7ad4de3`), `-W error::ResourceWarning` | **33 passed, 1 failed**(G04-11 반례) |
| K3 | 새 4파일 `--co` / `ruff check` / 변경 5파일 `ruff format --check` / `mypy src/recoryn` | **428 node**(작성자 보고와 같음) / PASS / 5 files already formatted / 71 source files no issues |
| K4 | `g04c-live-rate.py`, `g04b-drop.py`, `g04b-drop2.py`, `g04b-perf.py`(이전과 같은 파일·조건, 직렬), `g04d-gui-timing.py`(LF `d818bbf5…`), `g04d-privacy-check.py`(LF `acaf2ad0…`) | 아래 |

- K1의 2 skip은 앞 절과 같은 `test_gpu_smoke.py:107`이다.
- K2의 이전 UI probe 3개(`test_new_one_unreadable…` 2행, `test_orig_directory_only…`, `test_unsafe_session_is_isolated…` 4행)는 FIX4로 목록이 worker에서 비동기로 채워진다. 그래서 창 생성 직후 `_inventory_loading`이 끝날 때까지 이벤트를 처리하는 대기 6줄만 추가했다(LF `e0399d8f…`, `be8dbbab…`). 기대값은 바꾸지 않았다. 대기 없이 그대로 실행하면 목록이 아직 비어 있어 7건이 실패하며, 이는 제품 결함이 아니다.

### R4-3. G04-10 — RECHECKED

- **코드**:
  - `_session_operation(admission=…)`이 claim을 기록하는 **같은 root mutex 구간**에서 `_admit_session`으로 삭제 의도, live, version, 행·폴더 존재, seal 상태 전이 가능성을 먼저 판정한다. 거부면 claim을 기록하지 않는다.
  - 복구의 삭제 의도 응답은 claim 없이 읽기 전용으로 반환한다.
  - `register_chunk`는 live 세션이면 claim 검사를 건너뛴다.
- **재측정(블록마다 봉인하는 `chunk_frames=480` + 연속 거부 클릭)**:
  - `test_g04c_live_claim_race[recover/finalize]`(3초): recover 1,130회·finalize 1,126회가 모두 거부됐고 `writer_error None`, 거부 블록 0이다(FIX3에서는 216/287블록 거부와 writer 중단).
  - `g04c-live-rate.py` 3초: 1,411회 클릭, writer 실패 0, 거부 0.
  - 10초: 4,131회와 4,243회 클릭에서 writer 실패 0, 거부 502·495블록.
  - **대조군**: 같은 10초를 클릭 없이 돌리면 468·469블록이 거부되고, 직전 tree 98c20f87에서도 478블록이다. 즉 10초 거부는 초당 100회 봉인이라는 공격적 설정에서 writer 처리량이 실시간을 따라가지 못해 생기는 것이다. 클릭이나 claim 때문이 아니다.
- **단일 클릭 지연 주입**: `test_single_click…` 2 PASS(writer 실패 0).

### R4-4. G04-09 — RECHECKED

- **GUI thread 비차단**: `g04d-gui-timing.py`로 실제 `MainWindow`에서 묶음 7,200개 미확정 세션을 두고 측정했다.
  - `refresh_sessions()` 호출 반환 **0.6ms**
  - worker 조회 완료 3.75~3.77초(초기·재조회)
  - 직전 FIX3는 같은 조회 약 3초를 GUI thread에서 동기로 실행했다.
- **조회 중 동작**: `test_gui_thread_returns_while_large_inventory_runs_and_finalize_waits` PASS.
  - 조회 중 상태 문구는 "미확정 세션 확인 중"이고 확정 버튼은 비활성이다.
  - 그 사이 `finalize_selected()`를 확인 대화 통과로 호출해도 실행되지 않는다(`INTERRUPTED` 유지).
  - 완료 뒤 확정 버튼이 다시 활성화된다.
  - 코드상 `_finalize_allowed`는 `_inventory_loading` 동안 False다. 확정은 여전히 `expected_version`으로 라이브러리에서 재검사한다.
- **늦은 결과**: `test_late_result_never_overwrites_newer_request_or_selection` PASS.
  - 세대 N의 조회가 도는 중에 새 미확정 세션 `fresh`를 만들고 세대 N+1을 요청했다.
  - 렌더 기록은 `(N, 기존 목록) → (N+1, 기존 목록) → (N+1, fresh 포함)`이다. N의 완료 결과로는 렌더하지 않았다(세대 불일치로 폐기).
  - 조회 중 사용자가 b를 선택하면 완료 뒤에도 선택과 AI 패널이 b로 유지된다.
- **조회와 삭제의 새 경쟁**: `test_inventory_worker_does_not_make_deletion_of_scanned_session_fail` PASS. 묶음 7,200개 세션을 별도 thread가 연속 조회하는 동안 그 세션을 삭제했다. 결과는 `DELETED_LOCAL`이고 조회 예외 0, 폴더 제거를 확인했다. 삭제 의도가 기록된 뒤에는 조회가 그 세션을 건너뛴다.

### R4-5. G04-01~08 유지

- K2에서 이전 30 node 중 G04-11 반례 1건을 제외한 29 node가 PASS다(UI 3개는 위 대기만 추가). 범위는 owner 2변형·GC·일시정지 확정, junction 2행, 보존량 0, DIRECTORY_ONLY 전환, 문제 세션 4종 격리, 삭제 의도 경계, claim 경쟁·kill 3지점이다.
- **G04-07**(녹음 중 refresh식 조회): 묶음 1,800개 1.514s/유실 0, 7,200개 8.989s/거부 0/유실 0이다. 조회 1회는 1,800개 0.67~0.71s다.
- **G04-08**(녹음 중 30분 세션 확정): 15.636s/거부 0/**유실 0**이다.

### R4-6. 새 발견

#### G04-11 / S3 / OPEN — FIX4의 목록 재구성이 선택 변경 신호를 막아, 선택 세션이 사라져도 privacy 패널이 이전 세션을 대상으로 유지한다(G-P02 §2.4 회귀)

- **근거(코드)**:
  - `_render_sessions`는 `QSignalBlocker(self.sessions)`로 `clear()`와 재선택 동안 `currentItemChanged`를 막은 뒤 `self._session_selected()`만 직접 호출한다.
  - `_session_selected`는 선택이 None이면 조기 반환한다.
  - G-P02가 `DesktopAI.attach_privacy`에 연결한 `currentItemChanged` 처리기(목록 비움·선택 해제를 privacy에 None으로 전달)는 이 경로에서 호출되지 않는다. G-P02 계약 §2.4는 "목록 비움/선택 해제를 반드시 None으로 전달한다"고 정한다.
- **재현**: `g04d-privacy-check.py`(같은 스크립트로 직전 tree와 비교)와 `test_refresh_after_selected_session_disappears_clears_privacy_target`(FAIL). 실제 `MainWindow`에서 세션 a를 선택하고, UI와 같은 `before_delete("a")` 뒤 `delete_session("a")` → `refresh_sessions()` → 완료를 기다렸다.
  - **FIX4(8aca0553)**: 목록 선택은 None인데 `privacy._selected_session='a'`, 표시는 `이 세션만: a / … / 기본 거부`, **허용 버튼 활성**이다.
  - **FIX3(27eca03f)**: `privacy None`, 표시 `이 세션만: 선택 없음`, 허용 비활성이다.
- **영향**: 삭제된 세션 a가 privacy 패널의 동의 대상으로 남고 허용 버튼이 켜져 있다. 다만 a는 철회·삭제되어 이후 작업 준비(`bind_session`)가 거부되므로 전송은 일어나지 않는다(fail closed). 다른 세션을 선택하면 정상으로 돌아온다. 표시와 계약의 회귀이므로 S3로 분류했다.
- **수정 제안**: 재구성 뒤 선택이 바뀌었으면(특히 None) privacy에도 전달한다. 예를 들어 unblock 뒤 실제 이전/현재 선택이 다르면 `currentItemChanged`를 한 번 발생시키거나, `_session_selected`의 None 분기에서 `ai_bridge`/privacy에 None을 알린다. 실제 `MainWindow`에서 선택 세션 삭제 → privacy None을 단언하는 시험을 추가한다.

### R4-7. 미검증·한계

- 측정은 합성 PCM과 이 PC의 SSD 기준이다. 실제 WASAPI 2트랙·느린 디스크·백신 환경이 아니다.
- 10초 공격적 설정의 거부 블록은 클릭 없는 대조군과 같은 수준이라 결함으로 세지 않았다.
- 작성자 R 증거(관련 1,383 PASS, mutation 12/12, mutex 최대 시간)는 재실행하지 않았다.

### R4-8. RECHECK 4 결론

**G04-10 RECHECKED / G04-09 RECHECKED / G04-01~08 유지. 새 OPEN 1 (S0 0 / S1 0 / S2 0 / S3 1)** — G04-11(목록 재구성 신호 차단으로 선택 세션 삭제 뒤 privacy 대상이 남음, fail closed). 수정 또는 수용은 C00가 결정한다.

## RECHECK 5 — 2026-11-23, PERF 시험 oracle 정정(FIX5) 재확인

같은 검토자(Claude)가 작성자 Codex의 FIX5를 짧게 확인했다. C00 지시에 따라 전체 회귀는 생략했다. 위 내용은 이력으로 보존한다.

**요약: 새 assertion은 G-P04 성질(관리 작업이 root mutex를 길게 잡지 않음)을 여전히 검출하고, G04-07·08형 회귀(관리 작업 전체를 mutex 안으로 되돌림)를 놓치지 않는다. 유실 0도 단독 측정에서 재현된다. 새 OPEN 1 (S3 1): 문서 추적성(G04-12). RECHECK 4의 G04-11(S3)은 FIX5 범위 밖이라 그대로 OPEN이다.**

### R5-1. 입력

- 대상 tree **`65b493ceaebaa0a43bb258c5efc08076405c4569`**(tree). `git diff --stat 8aca0553 65b493ce` 결과는 `tests/integration/test_unfinished_recovery.py`(17줄)와 문서 §16(61줄)뿐이다. `-- src` diff는 비어 있어 제품 코드는 FIX4와 같다.
- 추출: `build/review-trees/g04e`(판정), `build/review-trees/g04e-pristine`(변이).
- 바뀐 시험 파일의 LF SHA256은 `a58f078cb3138796f8fce65f0ff786074e0eda98cc3271affefaf8f195ce3524`, 문서는 `9e13e9bf5992a163cae6cef52b3e5fb4e56154ba1f53acfc8941c8302abcfcdf`다. `ruff check`와 `ruff format --check`는 PASS다.
- 쓰기는 이 절 추가뿐이다.

### R5-2. assertion 변경 확인(코드 읽기)

- 제거: `rejected == 0 and dropped_frames == 0`, `stored == submitted`
- 측정값으로 유지: 거부 블록, 유실 frame, 저장 frame, 전체 root 최대
- 판정:
  - 관리 결과 성공(목록 7,200묶음 / 확정 900묶음·86,400,000frame / 복구 900묶음)
  - `max(meter.management_holds) < 0.05`(이전 0.1에서 강화)
  - 관리 thread의 50ms 이상 보유 0건
- `RootHoldMeter`는 대기 시간을 빼고 바깥쪽 보유 시간만 thread 이름별로 기록한다.

### R5-3. 변이 재현(검토자 작성 diff, `python -I build/review-trees/g04e-mutate.py`)

harness LF `27c210d1175216bc734f6a9a8f0d526b4dde1608e085da75d4e1cedd9a8b1ef7`, 결과 `g04e-mutations.json` LF `09462b54bcf44ec1681f2157a2cd410f32a2ca80f7d8dcef1911c77dbffee963`. baseline 3행은 3 PASS(97.98s)다.

| 변이 | 내용 | 대상 행 | 결과 |
| --- | --- | --- | --- |
| MA | `unfinished_inventory()` 전체를 `with self._mutex:` 안에서 실행(G04-07형) | inventory-7200 | **KILLED**(관리 보유 assertion) |
| MB | `finalize_unfinished`의 `recover_session` 호출을 mutex 안에서 실행(G04-08형) | finalize-900 | **KILLED** |
| MC | 복구 루프의 `verify_bundle`만 묶음마다 짧게 mutex 안에서 실행 | recover-900 | SURVIVED |

MC 판단:
- 작성자 시험의 측정은 관리 root 최대 6.8ms, 관리 50ms 이상 0건, 거부 0, 유실 0이고, 50ms 이상 보유는 `recoryn-writer-rec`만이다.
- 같은 변이 src로 `g04b-drop2.py`를 실행하면 확정 17.551s, 거부 0, **유실 0**이다.

즉 MC는 녹음 유실을 만들지 않는 **동등 변이**로 본다. 50ms 미만의 짧은 보유가 쌓여 writer를 굶기는 경우는 이 시험의 판정으로 잡히지 않는다. 그러나 이번 측정에서는 그런 유실이 관측되지 않았으므로 결함으로 세지 않는다. 필요하면 관리 동작 구간의 거부만 귀속해 판정하는 보조 assertion(C00 결정의 선택지)을 후속으로 둘 수 있다.

### R5-4. 유실 0 단독 재현(같은 측정 스크립트, 직렬)

| 측정 | FIX5(65b493ce) |
| --- | --- |
| G04-07: 묶음 7,200개 세션이 있는 상태에서 녹음 중 refresh식 조회(`g04b-drop.py`) | 8.573s, 거부 0, **유실 0** |
| G04-08: 녹음 중 30분 세션 확정(`g04b-drop2.py`) | 13.994s, 거부 0, **유실 0** |

### R5-5. 문서의 G-P15 구분

- §16은 긴 보유가 writer의 `_consume → seal → __exit__`이고 "writer의 fsync·scan·rename·재해시 구간 개선은 C00이 분리한 저장 계층 S2 후속"이라고 적는다. 관리 작업 귀속(관리 ≥50ms 0건)과 저장 계층 유실을 구분하고, 유실이 관측된 실행도 숨기지 않고 표에 남겼다. 내용상 구분은 정확하다.
- 단 후속 단위 ID **G-P15**를 명시하지 않았고, 이번에 바뀐 시험 파일의 제출 hash도 §16에 없다(G04-12).

### R5-6. 새 발견

#### G04-12 / S3 / OPEN — §16이 writer seal 후속을 ID 없이 서술하고 변경 시험 파일 hash를 기록하지 않는다

- **근거**: `grep "G-P15"` 결과 0건이다. §16.1·16.2의 증거 표에는 XML/JSON hash만 있고, `tests/integration/test_unfinished_recovery.py`의 제출 LF hash(`a58f078c…`)가 없다(검토자 계산으로는 위 값).
- **영향**: 추적성 문제다. 판정·제품에는 영향이 없다.
- **수정 제안**: "C00이 분리한 저장 계층 S2 후속"을 "G-P15(S2)"로 명시하고, 변경 2파일의 LF hash 표를 추가한다.

### R5-7. RECHECK 5 결론

**FIX5 시험 정정 수용 가능**: 관리 작업의 G04-07·08형 회귀를 검출하고(MA·MB KILLED), 유실 0도 단독으로 재현했다. **새 OPEN 1 (S0 0 / S1 0 / S2 0 / S3 1)** — G04-12(문서 추적성). 기존 G04-11(S3)은 FIX5에서 다루지 않아 계속 OPEN이다. 최종 판정과 전체 회귀는 C00가 최종 tree로 수행한다.

## RECHECK 6 — 2026-11-23, 측정 창 정정과 G04-12 보강(FIX6) 재확인

같은 검토자(Claude)가 작성자 Codex의 FIX6를 짧게 확인했다. C00 지시에 따라 전체 회귀는 생략했다. 위 내용은 이력으로 보존한다.

**요약: FIX6 수용 가능. G04-12 RECHECKED. 새 OPEN 0. RECHECK 4의 G04-11(S3)은 FIX6 범위 밖이라 계속 OPEN이다.**

### R6-1. 입력과 diff 검토

- 대상 tree **`a0ead0aecb3e845636d872b814efaf091b0b9dbb`**(tree). `git diff --stat 65b493ce a0ead0ae` 결과는 시험 1파일(6줄)과 문서 §16.3~(54줄)뿐이고 제품 코드는 그대로다.
- 추출: `build/review-trees/g04f`(판정), `build/review-trees/g04f-pristine`(변이).
- **시험 diff**:
  - docstring 갱신
  - `assert index < 3000`(10ms 간격 기준 약 30초)을 `assert time.perf_counter() - started < 300`으로 교체
- **판정 assertion은 바뀌지 않았다.** 관리 결과 성공, 관리 thread root 최대 보유 50ms 미만, 관리 thread 50ms 이상 보유 0건이 그대로다. 루프는 여전히 `index < 600 or not done.is_set()`이므로 관리 작업이 끝날 때까지 측정한다.
- **hang 경로**:
  - 관리 작업이 끝나지 않으면 300초에 assertion이 실패한다.
  - `finally`의 `service.stop(timeout=60)`과 `worker.join(60)`은 시한이 있어 시험 자체가 무한 대기하지 않는다.
  - 관리 thread가 non-daemon이라 실제로 멈춘 경우 프로세스 종료가 지연될 수 있다. 이는 FIX6 이전부터 같은 구조이며 FIX6가 새로 만든 위험이 아니다.

### R6-2. G04-07·08형 회귀 검출 유지(재확인 5의 변이 재적용)

`python -I build/review-trees/g04f-mutate.py`(재확인 5 harness에서 대상 사본만 바꾸고 MC는 제외; LF `0f2ce41af3cd06d343d85d681b2087a7d766ff29ee6f9513a297bd618d68a71d`, 결과 `g04f-mutations.json` LF `3beebc948199ffa3fb250e9b2a7eda30f992aea3f4344f64040d4a9d6b648902`)를 실행했다. baseline 2행은 2 PASS다.

| 변이 | 결과 | 실패 원인(직접 확인) |
| --- | --- | --- |
| MA: `unfinished_inventory()` 전체를 mutex 안으로 | **KILLED** | `assert 3.8526… < 0.05`(관리 보유 3.853초, 관리 장기 보유 1건, 거부 130) |
| MB: 확정의 `recover_session` 호출을 mutex 안으로 | **KILLED** | 관리 보유 6.942초, 관리 장기 보유 1건, 거부 509 |

두 변이 모두 300초 창이 아니라 관리 보유 assertion(시험 359행)에서 실패했다. 300초 상한은 이 회귀의 검출에 영향을 주지 않는다.

### R6-3. 해당 시험 3행 단독 1회

`pytest …::test_management_never_blocks_another_recording -W error::ResourceWarning`(g04f, `PYTHONPATH=g04f/src`) 결과 **3 passed, 102.78s**다. 각 `measurement.json`의 값은 다음과 같다.

| 동작 | 관리 시간(s) | 관리 root 최대(ms) | 전체 root 최대(s) | 거부 | 유실 | 제출=저장 frame | 관리 ≥50ms |
| --- | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| 목록 | 4.766 | 0.9 | 1.067 | 0 | 0 | 288,000 = 288,000 | 0 |
| 확정 | 18.344 | 6.8 | 0.942 | 0 | 0 | 904,800 = 904,800 | 0 |
| 복구 | 8.822 | 4.2 | 0.947 | 0 | 0 | 447,840 = 447,840 | 0 |

50ms 이상 보유는 모두 `recoryn-writer-rec`(G-P15 범위)였다.

### R6-4. G04-12 — RECHECKED

- §16.3이 writer seal의 fsync·scan·rename·재해시 root 구간을 **"G-P15(S2, `docs/implementation/v1-gap-plan.md`의 2차 후속 단위)"**로 명시했다.
- FIX6 변경 시험의 LF SHA256 표에 `7871d9415ab921e3f4a7a7c99d20bf505c1afbef8c6da7e445281b524f73ecee`를 기록했다. 검토자가 추출 사본에서 계산한 값과 같다.
- 문서 자체 LF hash는 `4dda0a746ad269f9df6a3a2e6e2401c0edb50f4f452cfe958765b2729d00d8d6`(검토자 계산)이다.
- 참고: 대상 tree(234dd31 기준)의 `v1-gap-plan.md`에는 아직 `G-P15` 문자열이 없다. 현재 작업 트리의 같은 파일에는 1건 있다. 참조가 유효하려면 C00 통합 때 그 문서 변경도 함께 반영되어야 한다(관찰).

### R6-5. RECHECK 6 결론

**FIX6 수용 가능 / G04-12 RECHECKED / 새 OPEN 0.** 남은 OPEN은 RECHECK 4의 **G04-11(S3)** 1건이다. 최종 판정과 전체 회귀는 C00가 최종 tree로 수행한다.

## RECHECK 7 (GT-P03) — 2026-11-23, live 반복 거부 시험의 수락 회계 oracle 재확인

같은 검토자(Claude)가 작성자 Codex의 GT-P03을 짧게 확인했다. 전체 회귀는 C00 지시로 생략했다. 위 내용은 이력으로 보존한다.

**요약: GT-P03 수용 가능. 새 oracle은 G04-10 회귀를 계속 검출하고, 수락한 블록의 저장 손실과 QUEUE_DROP 외 사유의 거부를 숨기지 않는다. 느린 디스크 모사(거부 28블록)에서도 정상본은 PASS, G04-10 변이는 FAIL이다. 새 OPEN 0. 개선 제안 1건은 결함으로 세지 않는다.**

### R7-1. 입력

- 대상 tree **`45c5f70ee3bff6b4509c01207aa972d92cd9962e`**(tree), 기준 `8e09b62`(G-P04 커밋). `git diff --stat 8e09b62 45c5f70e`는 시험 1파일(63줄 변경)과 문서 §17(69줄)뿐이다.
- 작업 트리의 G-P05·G-P06 미완성 변경을 피하려고 `git archive`로 `build/review-trees/gt03`(판정)과 `build/review-trees/gt03-pristine`(변이)에 새로 풀어 판정했다.
- 시험 LF SHA256 `3f64331e31397266cf500f3cd1bf7978a9fbab0d7b1b533bfc61cc53fc1c2bbd`, 문서 `39771053586f4a32f2778ab8d2e79722174df02c95dc89167fce0f41c11ebc73`. 둘 다 C00 제시값과 같고, 시험 hash는 §17 표(1125행)와도 같다.
- 쓰기는 이 절 추가뿐이다. 검토자 wrapper·변이는 `build/review-trees/` 아래에만 두었다.

### R7-2. oracle 검토(코드 읽기)

- **유지된 판정**:
  - 클릭 worker 종료
  - outcomes ⊆ {SESSION_LIVE, Live writer cannot be recovered}, ACCEPTED 없음
  - `publications == []`(ClaimRecorder로 claim 게시 자체를 관측)
  - 정지 전 `accepting`, `not storage_failed`, `_writer_error is None`
- **바뀐 판정**: `rejected == 0` 대신 다음 회계 일치를 요구한다.
  - `dropped_frames == rejected×480`
  - 저장 health gap의 reason이 모두 QUEUE_DROP이고 gap frame 합이 `rejected×480`
  - `accepted_frames == (300−rejected)×480`
  - descriptor 수 == 300−rejected
  - 저장 frame 합 == 수락×480
  - 이어 붙인 audio == `data×수락`
- **QUEUE_DROP 외 거부가 숨을 수 있는가**: `RecordingService.submit`이 False를 돌려주는 경로는 두 가지다.
  - 비수락(`_accepting False`): drop 회계를 하지 않는다.
  - 큐 `offer` 실패: `dropped_frames`와 QUEUE_DROP gap을 기록한다.

  따라서 writer 중단처럼 비수락으로 거부되면 `dropped == rejected×480`이 깨지고, `accepting`·`_writer_error` 단언도 실패한다. writer 실패 처리는 gate 안에서 `_accepting=False`를 먼저 세운 뒤 큐를 닫으므로, 닫힌 큐가 QUEUE_DROP으로 위장되는 창도 없다(`recording.py` `_consume` 예외 처리).
- **수락 블록 무손실**: 수락 수와 descriptor 수·frame 합·이어 붙인 bytes가 모두 같아야 하므로, 수락했는데 저장하지 않은 블록이 있으면 실패한다.
  - **한계(개선 제안, 결함 아님)**: 모든 블록의 payload가 같은 `data`라서 **어느** 블록이 저장됐는지(순서·sequence)는 확인하지 않는다. 블록별 서로 다른 payload를 쓰거나, descriptor의 sequence 집합을 수락 index 집합과 대조하면 더 정확해진다. 현재 경로에서 손실과 중복이 정확히 상쇄될 메커니즘은 찾지 못했다(chunk_id 단위 등록).

### R7-3. 변이 재현(검토자 작성 diff, `python -I build/review-trees/gt03-mutate.py`)

harness LF `2b71f9e837c79ec740d12973129664304722af4303a3632370207290856e2d7d`, 결과 `gt03-mutations.json` LF `86bd67ad6a3a4057542edd12d2e460bff3362f528699eb02024d1de368f261ad`. baseline(대상 2행 + 느린 seal wrapper 1행)은 3 PASS다.

| 변이 | 내용 | 결과 | 실패 assertion(직접 확인) |
| --- | --- | --- | --- |
| V1 | FIX4 이전 동작: `_session_operation`이 claim을 먼저 게시하고, 별도 mutex 구간에서 admission(거부 시 claim 제거) | **KILLED**(2/2행) | `a refused live request published a claim`(게시 1,153/1,092건) |
| V3 | V1 + `register_chunk`가 live여도 claim을 검사(FIX3 동작 재현) | **KILLED**(2/2행) | writer `SESSION_OPERATION_IN_PROGRESS`로 중단, 이후 ACCEPTED 8/43회, 거부 168/277블록(ACCEPTED 단언에서 먼저 실패) |
| V2 | `register_chunk`의 live 우회만 제거 | SURVIVED | live 세션에 claim이 게시되지 않으므로 관측 가능한 차이가 없는 방어층 변이(동등). V3에서 결합 효과를 확인했다 |
| A1 | writer가 sequence 100의 수락 블록을 등록하지 않고 폐기 | **KILLED** | `assert 299 == 300`(descriptor 수) |
| A2 | submit이 sequence 150을 비수락 사유로 조용히 거부 | **KILLED** | `assert 0 == 1*480`(dropped 회계) |

### R7-4. 느린 디스크 모사

- `tests/review_gt03/test_slow_seal_wrapper.py`(LF `f4b094ef0728b2f0ef3a46d9a1e918c18d470f0944d0d2b505e360e45a9ceab9`)는 대상 시험 함수를 **수정 없이** 호출하되, `ChunkWriter._seal`마다 0.15초 지연을 주입한다(root mutex 안의 seal 지연을 모사). 그리고 거부가 실제로 생겼는지 단언한다.
- **정상본**: PASS. 거부 28블록, 유실 13,440frame, gap 2건 모두 QUEUE_DROP, 수락 272 = descriptor 272, 저장 261,120 bytes(=272×960), claim 게시 0, writer 오류 없음이다.
- **V1**(같은 지연): 거부 29, 게시 231건 → **FAIL**(publications 단언)
- **V3**(같은 지연): 거부 28, 게시 235건 → **FAIL**(publications 단언). 이 실행에서는 seal이 느려 writer 중단까지는 일어나지 않았지만, claim 게시 단언으로 검출됐다.

### R7-5. 대상 시험 단독 반복

`pytest …::test_repeated_live_refusals_preserve_every_recording_block -W error::ResourceWarning`(gt03, `PYTHONPATH=gt03/src`)를 실행했다.

- 반복 4~6: 각 **2 passed**(34.26s / 29.13s / 27.73s)
- 반복 1~3: 검토자의 출력 파서 오류로 pass 줄을 수집하지 못했다. 각 `live-measurement.json`은 recover/finalize 모두 요청 1,036~1,268회, 거부 0, 게시 0, 수락 300 = 저장 300, 288,000 bytes, writer 오류 없음으로 단언 조건과 일치한다.

### R7-6. RECHECK 7 결론

**GT-P03 수용 가능 / 새 OPEN 0 (S0 0 / S1 0 / S2 0 / S3 0).** G04-10 회귀(V1·V3)는 자연 실행과 느린 seal 모사 모두에서 검출되고, 회계 oracle은 수락 블록 손실(A1)과 비QUEUE_DROP 거부(A2)를 검출한다. 블록별 payload 식별 강화는 선택 개선 제안이다. RECHECK 4의 **G04-11(S3)**은 이 단위 범위 밖이며 그 뒤 처리 여부는 C00 기록을 따른다.
