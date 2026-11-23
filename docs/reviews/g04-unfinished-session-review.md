# G04-R / G-P04 미확정 세션 확정 독립 검토

2026-11-23, 검토자 w5:p8 Codex / 작성자 w5:p7 Claude.

**OPEN 5건: S0 0 / S1 1 / S2 3 / S3 1.** 지정 tree의 전체 오프라인 회귀는 **8,390 PASS**지만, 별도 독립 반례에서는 제품 조건 4종에 해당하는 **6 FAIL**이 재현됐다. S1인 G04-01을 해소하기 전에는 품질 체계의 push 게이트가 열려 있다. 일반 원인 사슬·확정·live 거부의 기존 시험 결과와 아래 추가 반례를 구별한다. 수정/수용·최종 통합은 C00 결정이다.

## 1. 대상·격리·직접 실행

검토 대상은 **`5a5f0316b227fb0bbc809fdc5d7c14522c154b19`**, 기준은 **`9d46b4a9a38de6f9c6fea38db35a440cbad7779f`**다. `git diff --stat 9d46b4a 5a5f0316…`을 직접 확인해 **10파일, 3318 insertions / 28 deletions**이었다.

`git archive --format=tar 5a5f0316…`를 OS TEMP에 풀었다. 이하 **R = `C:/Users/gangd/AppData/Local/Temp/recoryn-g04r-96ggil2d`**, 판정 사본은 `R/tree`다. 작업 트리의 G-P02나 다른 미커밋 파일은 포함하지 않았다. 대상 파일 LF SHA256은 다음과 같고, 검사 종료 시 열 파일 모두 추출 직후와 같았다(`R/inputs.json`).

| 대상 파일 | SHA256(LF, CR 제거) |
| --- | --- |
| docs/testing/g04-unfinished-session-cases.md | `ee3f2d6e5c73f1b8f7fc8c8d5847de33d9af2446bb9021fe56a9f7c5b49a4a2b` |
| src/recoryn/app/recording.py | `d591d87ef0dbe42f54142c72fa4b012bb9a6bda08b3cee6c30e9ca86a8947c61` |
| src/recoryn/app/recovery.py | `ba54132ecd48d2000285d940c0703016732e6d8c8422016db0c08670ef296658` |
| src/recoryn/cli.py | `f6faf78966f17ee3d00608ac1c75f98eccbeeacb3e2d507651d4ad21f348eae9` |
| src/recoryn/storage/library.py | `1b402e0890606a7532a1f3aee639203e68f62668d5119a9a033b83b6091775f6` |
| src/recoryn/ui/main.py | `b67e13785ccb69f7c0a2b1e99afae1eb637282d70113304cf709e0baf6ccbfe6` |
| tests/e2e/test_cli_finalize.py | `7c8d015c5c47c70a66e67d49105693863d793b518dcb147a454634a67678bb9a` |
| tests/integration/test_unfinished_recovery.py | `a62b2641ffe36aff5ff0fa7cf1ed5f847f59ee520ebe86192553cef216357411` |
| tests/ui/test_recovery_ui.py | `7ce5eaa320ab3704b7cf27374ceb6d68f9850e528750c0ac73340043dbc25251` |
| tests/unit/test_unfinished_sessions.py | `1342b8eaf79a0ac5a4e692ecac886b3d05952a8bbb686a80a151b4bfeaf3a528` |

기존 `.venv` Python, `-B`, bytecode 억제, `QT_QPA_PLATFORM=offscreen`, HF/transformers offline·telemetry 차단, `-p no:cacheprovider`, 실행별 고유 OS TEMP basetemp를 사용했다. 아래 R 표기는 이 절대 경로의 축약이다.

```powershell
# cwd: R/tree, PYTHONPATH=R/tree/src
D:/project/Recoryn/.venv/Scripts/python.exe -B -m pytest -q -p no:cacheprovider --basetemp R/full --junitxml R/full.xml --durations=8 --tb=short
```

직접 결과 **8390 passed in 316.82s / exit 0**, failure/error/skip/xfail0이다. `R/full.xml` LF SHA256은 **`b14db1223fd1cb71b12dcadefb7575fec50751bcf3118ffcf813fb2c792d7efe`**다. UI 전체67개도 포함한다. 이 결과에 G-P02의 새 scope 시험은 들어 있지 않다. 작성자의 관련722 PASS·작업 트리910 PASS를 이번에 직접 실행한 숫자로 옮기지 않는다.

사본에서 `ruff check --no-cache src tests scripts packaging`, 변경 Python9파일 `ruff format --check --no-cache`, `python -m mypy --cache-dir R/mypy src/recoryn scripts packaging`를 실행해 **모두 PASS, mypy84 source files**를 확인했다. 실제 장치·모델·네트워크·유료 호출·계정·설치·하위 에이전트·pane·Git 쓰기는 사용하지 않았다. 저장소 쓰기는 이 보고서 하나다.

## 2. 독립 보강 실행과 재현 방법

`R/test_independent_g04.py`는 작성자의 합성 PCM/창 수명 helper만 재사용하고, 기대값은 아래와 같이 따로 썼다. 제품 소스·작성자 시험은 바꾸지 않았다. 최종 LF SHA256은 **`289f9ffa640559a92f23ff697bf35d0e9f00a9febe6c182cc8ce381004ab9dfd`**다.

```powershell
# cwd: D:/project/Recoryn, PYTHONPATH=R/tree/src, offscreen/bytecode 억제
.venv/Scripts/python.exe -B -m pytest R/test_independent_g04.py -c R/tree/pyproject.toml --rootdir R -q -p no:cacheprovider --basetemp R/independent-report --junitxml R/independent-report.xml --tb=short
```

직접 결과 **6 failed, 5 passed in 2.12s / exit 1**, 수집/import error·skip0이다. `R/independent-report.xml` LF SHA256은 **`78a60781460f0f646129ec28c06501e53b93444d035ae0e42f2a58dc057ccbf0`**다. 실패6은 owner2·junction2·없는 미디어1·이전 AI 패널1이며 **발견4건**으로 묶는다. G04-05는 별도 문서 산식 문제다.

초기 반례 실행에서는 종료 정리 `_drain`이 이미 잘못된 FINALIZED 상태에서 추가 예외를 내 원 assertion을 가렸다. TEMP 정리에서 그 예외를 처리하고 worker 종료를 확인하도록 보완한 뒤 위 결과를 다시 얻었다. junction oracle도 예외만 요구하는 대신 **라이브러리 밖을 실제 열거하지 않았는지**를 관찰하게 했다. 정상적인 안전 skip도 수용할 수 있는 oracle다. 종료 정리를 위해서만 private drain을 사용했고, G04-01의 결함 유발 순서는 공개 API뿐이다.

## 3. 발견 사항

### G04-01 / S1 / OPEN — 다른 owner 등록이 실제 녹음 owner를 덮어 live 검사를 우회함

**근거:** `src/recoryn/storage/library.py:230`의 `register_live_owner`는 같은 ID의 기존 참조를 조건 없이 교체한다. `:238`의 `_is_live`는 새 참조 하나만 본다. 실제 `RecordingService.is_live`는 `app/recording.py:61`, 확정의 live 거부는 `library.py:789` 부근이다.

**재현 node:** `test_live_recording_cannot_be_hidden_by_another_owner[live]`와 `[paused-resumed]`.

1. 실제 RecordingService를 합성 형식으로 만들고 start한다. 실제 장치는 열지 않는다.
2. live 변형은 바로, paused-resumed 변형은 pause한 뒤, 같은 session ID에 `is_live() -> False`인 다른 정상 객체를 `register_live_owner`로 등록한다.
3. 두 번째 변형은 원래 서비스의 resume을 호출한다. 입력 수락/worker가 다시 live여도 registry는 다른 객체만 본다.
4. `finalize_unfinished`를 호출한 다음 원래 서비스에 합성 PCM 4프레임을 submit하고 정상 stop을 호출한다.

**직접 결과(두 변형 동일):**

```text
finalize_unfinished: FINALIZED, chunk_count=0, frame_count=0
submit after finalize: True, accepted_frames=4, catalog_frames=0
service.stop(): FINALIZED, frame_count=0, manifest_sync_pending=False
service.is_live() after stop: True
worker_alive after stop: True
```

`R/owner-replacement-live.json`, `R/owner-replacement-paused-resumed.json`에 사실을 기록했다. 기존 stop은 이미 FINALIZED인 경우 조기 반환하므로 실제 수락/worker 종료와 완료 응답이 어긋난다. 이 조건에서 원본이 물리적으로 전부 지워졌다고 주장하지 않는다. 관측한 문제는 **live 수락 중 잘못된 확정·정지 완료와 확정 목록 밖 프레임**이다. 핵심 녹음 기능의 상태/완료 불일치여서 S1이다.

**기대:** 다른 객체의 등록으로 기존 보유자의 생존을 잊지 않아야 한다. 등록 단계에서 안전한 domain 오류로 거부하거나 모든 유효 owner를 계속 관찰해 finalize가 SESSION_LIVE로 거부해야 한다. 일시정지 상태에서 덮은 뒤 재개하는 변형도 막아야 한다.

**제안:** 살아 있는 객체에 대한 등록 교체 규칙을 명시하고, 동일 객체 재등록은 멱등으로 두되 다른 객체는 기존 참조가 유효한 동안 거부하거나 약한 참조 집합으로 관리한다. **현재 live인지 한 번만 보고 교체를 허용하는 수정은 paused-resumed를 놓친다.** source/control 종료와 등록 해제를 결합할 필요가 있으면 계약을 먼저 정한다. 두 변형과 정상 동일-owner CE1을 정식 시험에 추가한다.

**범위 한계:** 현재 제품의 등록 호출자는 RecordingService 한 곳이다. 일반 GUI 사용만으로 중복 등록되는 경로를 관측한 것은 아니다. 새 공개 API가 허용하는 동일 ID/다른 객체 입력으로 재현했으며, 실제 source 코드를 덮거나 내부 dict를 직접 조작하지 않았다.

### G04-02 / S2 / OPEN — inventory가 중첩 reparse point를 따라 라이브러리 밖을 조회함

**근거:** `library.py:693`의 `_inventory_item`은 세션 base만 safe_path로 만들고, `:699` 이후 `staging.is_dir()/iterdir()`와 `tracks/track/epoch`의 is_dir/iterdir 앞에는 각 경로의 check_path가 없다. `_safe.py:114`는 reparse point를 거부하지만 이 경로에서는 호출하지 않는다.

**재현 node:** `test_inventory_rejects_nested_junction_before_listing[staging/tracks]`.

각 TEMP Library의 `sessions/s/staging` 또는 `sessions/s/tracks`에 **같은 TEMP 아래지만 라이브러리 밖** 디렉터리를 가리키는 실제 NTFS junction을 만들었다. 전자는 private-entry1개, 후자는 private-track/private-epoch/private-bundle1개를 두었다. Path.iterdir observer는 제품 결과를 만들지 않고 경로 열거 사실만 기록했다.

**직접 결과:** 두 경우 모두 예외 없이 `unfinished_sessions()`가 성공했고, 각각 **staging_entries=1 / uncatalogued_bundles=1**이었다. `R/junction-staging.json`, `R/junction-tracks.json`에는 junction을 통해 실제 열거한 경로가 있다. fixture setup 실패·skip은 없었다. 마지막에 reparse 속성0x400을 확인하고 junction만 rmdir해 외부 TEMP target이 남아 있음을 확인했다. 사용자 파일·원격 경로·네트워크는 사용하지 않았다.

**기대/제안:** 메타데이터 조회도 root 밖으로 따라가지 않아야 한다. staging/tracks/track/epoch에 is_dir·iterdir를 하기 전에 기존 check_path/safe_path 규칙을 적용한다. 안전 실패 또는 “검사할 수 없음” 경고를 남긴 skip을 허용하되 실제 외부 열거0을 검사한다. 재현은 외부 **항목 수 읽기**이며 외부 원본 수정/삭제나 네트워크 전송을 관측했다는 주장은 아니다.

### G04-03 / S2 / OPEN — 없어진 catalog 청크를 보존된 원본량에 합산함

**근거:** `src/recoryn/app/recovery.py:169`의 `recovery_view`는 전달받은 모든 catalog descriptor를 `:181`에서 preserved로 합산한다. recover_session의 missing/invalid 경고와 실제 검증 여부를 보존량에 반영하지 않는다. `:140`의 lines는 이를 “보존된 원본”으로 출력한다.

**재현 node:** `test_missing_catalog_payload_is_not_claimed_as_preserved`. 합성 청크8프레임을 정상 등록한 뒤 TEMP의 audio.pcm만 없애고 recover_session→recovery_view를 호출했다.

**직접 결과:** payload_exists=False인데 **preserved_frames=8 / 보존된 원본 청크1개**다. 같은 화면의 누락 영역에는 INVALID_BUNDLE·MISSING_OR_INVALID_CATALOG_MEDIA가 있고, manifest 동기화 안내에는 “원본은 보존”도 출력된다(`R/missing-media.json`). 누락 경고가 아예 사라진 문제는 아니지만 보존량과 상충한다. 제품이 이 payload를 삭제한 것이 아니라 시험이 만든 손상 입력이다.

**기대/제안:** 검증된 보존량과 catalog상의 예상량을 분리한다. 복구가 확인한 유효 청크 ID/범위를 read model에 전달하거나, missing/invalid 항목을 검증 보존 집계에서 제외하고 미확인/누락으로 표시한다. 단순히 descriptor 개수를 “확인된 원본”으로 쓰지 않는다. 없는 파일·손상된 파일 각각을 넣는 read model/UI 음성 시험을 추가한다.

### G04-04 / S2 / OPEN — DIRECTORY_ONLY 선택 후 이전 세션의 AI 편집 패널이 남음

**근거:** `ui/main.py:456`의 `_session_selected`는 DIRECTORY_ONLY에서 details만 바꾸고 `:467` 부근 return한다. 새 세션을 load하지 않는 것은 맞지만 기존 ContentPanel의 session_id/revision/편집 입력도 해제하지 않는다. `ui/content.py:248`의 `_edited`는 그 남은 session_id와 revision을 대상으로 저장한다.

**재현 node:** `test_directory_only_selection_clears_previous_ai_session`. 정상 a 세션에 전사1행을 만들고 선택한 뒤, DB 행 없이 합성 bundle만 있는 orphan 항목을 선택했다.

**직접 결과:** sidebar selected=`orphan`, details는 DIRECTORY_ONLY인데 **AI panel.session_id=`a`, revision은 a의 전사, table row1개**가 그대로다(`R/orphan-panel.json`). 작성자 U6은 처음부터 orphan 하나만 있는 창이어서 이 전환을 보지 못한다.

**기대/제안:** 이전 세션의 편집을 보존하는 정책을 적용한 뒤 AI 패널을 비우거나 명시적으로 비활성 상태로 바꿔 새 선택과 혼동하지 않게 한다. orphan을 ContentStore.load에 넘겨 KeyError를 만드는 수정은 피한다. 기존 삭제 완료 때의 패널 정리 패턴을 참고할 수 있다. **정상 세션→DIRECTORY_ONLY→다른 정상 세션** 전환 시험을 추가한다. 이 반례에서는 a의 실제 내용을 수정하지 않고 잔류 상태까지만 확인했다.

### G04-05 / S3 / OPEN — “생략922조합”은 서로 다른 가족의 수를 뺀 값이라 커버리지 분모가 아님

**근거:** `docs/testing/g04-unfinished-session-cases.md:294`·`:295`는 S×A×K의 무제약1008에서 T72와 K14를 빼 **922개 미검증 조합**이라고 쓴다. T 행은 (S,A), K 행은 원인별 여러 동작의 사슬로서 둘 다 3축 tuple의 부분집합으로 정의되지 않았다. 같은 우주의 집합을 뺀 것이 아니어서 이 계산은 누락 조합 수를 주지 못한다.

K1은 정의상 RECORDING 상태의 특정 kill checkpoint다. K1과 FINALIZED/NOT_FOUND 등의 독립 조합이 모두 그 원인 fixture로 구성된다는 근거도 없다. 원인 무관 가정으로 가족을 분리해 시험하는 선택 자체는 검토할 수 있지만, 그 가정을 1008−72−14라는 정확한 누락 분모로 표현할 수는 없다.

**기대/제안:** 실제 선언 가족의 **361과 실행365 node는 유지**한다. “S×A×K 전수는 하지 않았고 원인별 상태·동작 교차의 coverage는 계수하지 않았다”로 좁히거나, 각 K에서 가능한 시작 상태/동작과 실행한 tuple을 별도로 매핑해 Ω/F/E와 차집합을 다시 산출한다. 구성 불가능과 실행 생략을 구분한다. 이 지적은 361 자체를 부정하거나 임의922개 새 시험을 요구하는 것이 아니다.

## 4. 동의하는 구현·경계와 직접 근거

- **원본/복구:** `_salvage`의 복구 ID 공식은 source ID·verified records·payload digest를 사용하는 기존 공식과 같고, 복구 artifact는 새 경로다. 신규 `_staging_prefix`의 tail 계산은 읽기다. 정상 14개 K/F/D 사슬은 직접 PCM byte 연결·원본 파일 byte map·반복 복구/확정·FINALIZED 사건1개를 검사하며 전체 실행에서 전부 PASS했다. verify_bundle의 반환값만 복사해 원본 oracle로 쓰는 구조가 아니다. 최종 봉인 뒤 staging을 원위치에 남기고 ALREADY_RECOVERED로 분류하는 경로도 확인했다.
- **확정 직렬화:** `finalize_unfinished`의 root mutex 안에 의도/live/버전 검사→복구→FINALIZING→봉인 전체가 있다. 두 확정·복구와의 양순서·삭제와의 양순서 H1/H2/H3가 실제 barrier를 사용한다. 기존 domain 전이표는 수정하지 않았다.
- **정상 live와 녹음 시작 경쟁:** 원 CE1(before-first-block)·writer-open·after-seal 3행과 U7이 PASS했다. 추가 `test_recording_start_and_finalization_have_safe_boundary[finalize/start]` **2 PASS**: 확정이 먼저면 start가 START_REQUIRES_CREATED로 거부되고, start의 worker 생성이 먼저면 finalize가 SESSION_LIVE로 거부된다. 후자는 정상 stop에서4프레임을 확정한다. 따라서 G04-01을 정상 단일-owner의 모든 경우에 확대하지 않는다.
- **G-P05 삭제 경계:** 추가 `test_deletion_intent_stays_out_of_inventory_and_finalization[db_only/journal_only/completed]` **3 PASS**. 세 경우 모두 unfinished 목록 제외·finalize DELETE_PENDING·recover adopted/recovered0을 직접 확인했다. G04가 pending_deletions를 제공하지 않는 것은 승인된 G-P05 경계다. 초기 delete의 live-owner 보류 추가도 G-P05 승인 항목이며 이 검토에서 별도 G04 결함으로 중복 계산하지 않는다.
- **UI/CLI:** CLI 두 새 명령의 오류 code는 whitelist/안전 fallback이며 예외 본문을 그대로 출력하지 않는다. U4는 실제 Qt Return/Escape와 기본/escape No 버튼을 검사한다. 복구/확정 성공 callback이 refresh 뒤 결과를 쓰도록 한 §10 수정은 소스와 U2/U5에서 확인됐다. 시작 탐지가 recover/finalize를 자동 호출하지 않는 것도 U1·inventory 논리 행/파일 비교로 확인했다. G04-04는 별도의 이전 화면 전환 문제다.
- **보존 표시의 범위:** R-health의 durable 건강 기록 없는 epoch를 유실0으로 만들지 않는 oracle는 독립 literal이고 PASS했다. G04-03은 유실 누계와 별개인 **실제 미디어 존재/검증**의 누락이다.

## 5. 분모·oracle·mutation 재현

JUnit testcase의 파일/함수와 parameter ID를 별도 집계했다. `R/case-audit.json` LF SHA256은 **`89da2457b1a651e8a02a40871ec463b4c3c6f76ef26a18a58fb38bbd4c961c24`**다.

| 가족 | 선언 | 직접 실행 node |
| --- | ---: | ---: |
| T | 72 | 72 |
| I | 12 | 12 |
| Q | 195 | 195 |
| V | 13 | 13 |
| R | 23 | 23 |
| K(F/D 포함) | 14 | 14 |
| H | 10 | 10 |
| C | 5 | 5 |
| U | 17 | 17 |
| 합계 | **361** | **361 PASS** |

별도 manifest node4개를 포함하면 **신규365개**다(unit316/integration25/CLI6/UI18). 이 수는 선언과 맞는다. T는 손작성 상태×동작 표/SEALED_FRAMES, Q는 제품 전이표를 import하지 않는 닫힌 술어, K는 손작성 payload prefix/프레임·raw 파일 bytes를 사용한다. 상태를 조회하는 제품 helper를 쓰는 것과 기대값을 제품 predicate에서 가져오는 것을 구별했다. 다만 등록 owner 교체·nested reparse·손상 catalog 보존량·이전 AI 화면 전환은 이 선언 집합에서 빠져 있었다.

작성자의 M1~M10 중 **M1/M2/M4/M9 네 개**를 정확한 tree의 독립 TEMP 사본에서 재현했다. pyproject/src/tests/scripts/packaging을 함께 복사하고 사본의 library.__file__을 확인했다. **정상 선택4 PASS(실행 wall1.723초), 변이4/4 목표 testcase FAIL, error0**이다.

| 변이 | 직접 검출 node |
| --- | --- |
| M1 확정의 복구 생략 | `test_state_action_table[G04-T-RECORDING_STALE-FINALIZE]`의 보존 프레임 oracle |
| M2 recover의 owner 검사 제거 | `test_h4_live_recording_refuses_recovery_and_finalize[G04-H4-CE1-live-before-first-block]` |
| M4 inventory 삭제 의도 제외 제거 | `test_inventory_lists_unfinished_sessions_read_only[G04-I-DELETE_PENDING]` |
| M9 기대 버전 비교 제거 | `test_finalize_argument_values[G04-V-ver-plus1]` |

도구는 `R/run_mutation_review.py`, 변이 diff·실제 명령·소스/변이 hash·실패 node·origin은 `R/mutations`에 있다. `results.json` LF SHA256은 **`131f1697f4bcb99c4228cd74b94a0abd9ee58fbf9788aa102625bddb52e35267`**다. 이번에 네 개를 선택 실행한 사실을 작성자의 전체10/10 재실행이나 프로젝트 mutation coverage로 확대하지 않는다.

## 6. 인계

**G04-R REVIEW_READY / OPEN 5(S0 0 / S1 1 / S2 3 / S3 1)**. 우선 G04-01의 owner 등록 정합과 상태/정지 완료를 수정·재확인하고, G04-02~04의 경계/표시/선택 전환과 G04-05의 계수 표현은 C00가 수정 또는 수용을 결정한다. 재개·DIRECTORY_ONLY 삭제·삭제 pending 복원은 기존 승인 범위를 존중하며 이번에 구현하지 않았다. 실제 장치·모델·전원 장애·외부 backup 복원·실제 Narrator 판독의 검증 결과도 아니다.

G-P05/G-P06은 각 선행 push 및 C00 시작 신호 전까지 구현하지 않는다. G-P02·G-P04가 함께 적용된 최종 통합 tree의 검증은 별도 C00 게이트이며, 이 보고의 8390 PASS에 섞지 않았다. 다른 창에 입력하거나 검토 대상 제품/시험/문서를 수정하지 않았다.
