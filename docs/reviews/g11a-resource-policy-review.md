# G11 / G-P11a 요약 장치 정책 admission 독립 검토

2026-11-24, 검토자 Claude(C00 지정 G-P11a 독립 검토 하위 에이전트). 작성자는 w5:p7 Claude다. 검토자는 이 단위의 코드·시험·계약 문서를 작성하지 않았고, 이 문서 외에는 저장소 파일을 고치지 않았다.

**판정: OPEN 7건 — S0 0 / S1 0 / S2 0 / S3 7.** S0·S1이 없으므로 이 기준만으로는 push를 막지 않는다. 수용과 통합은 C00이 결정한다.

다음 반례는 찾지 못했다.

- CPU_ONLY·GPU_ONLY의 Ollama 요약이 attestation 확인 요청, `privacy.prepare_execution`, adapter 생성, Job 생성, provider 호출 중 하나라도 거치는 제품 경로
- GPU_ONLY의 화자 구분이 manifest 읽기(`DiarizationConfig`)나 Job 생성까지 가는 경로
- REMOTE STT·요약이 세 정책 중 하나에서 장치 정책 코드로 막히는 경로
- REMOTE의 장치 정책 제외가 동의·비용 준비를 건너뛰는 경로(T27·T28의 fake wire 접촉 0)
- 같은 키의 병합 요청이 QUEUED·BLOCKED Job의 캡처 정책을 덮는 경로(검토자 R13·R14 검출)
- 정책 변경이 대기·실행 중인 Job에 소급되는 경로, `config_key` 구성 변경
- 녹음 경로 변경(이 단위는 `app/recording`·`desktop`·`storage`를 건드리지 않는다)

S3 7건의 요지는 다음과 같다.

1. **G11R-01:** `AIService`가 호출자가 적은 backend를 provider 실체와 대조하지 않는다. 직접 호출에서 Ollama provider에 REMOTE를 붙이면 CPU_ONLY에서도 실행된다. 제품 호출자(bridge)는 같은 `config.provider_id`로 요청과 adapter를 함께 정하므로 지금은 사용자 도달 경로가 없다.
2. **G11R-02:** 작성자 관찰을 재현했다. `BoundedRunner.stop()`이 이미 BLOCKED(known)를 쓴 작업을 CANCELLED로 바꾼다. 이 단위가 만든 결함이 아니며 REMOTE_UNKNOWN은 보존된다.
3. **G11R-03:** 검토자 변이 15개 중 5개가 살아남았다. summarize dispatch 재검사, bridge 화자 구분 capture·서비스 admission, DTO envelope 경계 2개다.
4. **G11R-04:** 정책 코드 2개의 행동 식별자 연결이 공용 표(`app/status.py`)가 아니라 bridge에만 있다.
5. **G11R-05:** T27·T28 oracle이 Job이 없을 때 표시 문자열에서 코드를 꺼내 쓰고, 이어서 같은 문자열에 그 코드가 있다고 단언한다.
6. **G11R-06:** `ResourcePlan.applies`가 허용 Ollama(server_unknown)와 REMOTE(not_applicable)에서 같은 False다.
7. **G11R-07:** 결과 문서의 coverage 미적중 목록이 실제와 다르다. 새 화자 admission·capture 줄은 coverage와 assertion이 둘 다 없다.

## 1. 입력 고정과 범위 판정

- 검토 대상은 tree **`c65413b1a1024a51b436b69af96cc675f1c87f8a`**다(`git cat-file -t` = tree). 기준은 HEAD **319a05f**(G-P15b 포함)다.
- `git diff 319a05f c65413b1 --stat`의 결과는 **24파일, 2476 insertions / 82 deletions**다. 모두 계약 §10.1의 G-P11a 29파일 안에 있다. 범위 밖 변경은 0건이다. 바뀌지 않은 5파일(`test_live_ui`, `test_gpu_runtime_ui`, `test_cost_cap_ui`, `test_cost_cap`, `test_blocked_reason_case_space`)은 결과 문서의 목록과 같다.
- `jobs/runner.py`, `app/status.py`, `ui/main.py`는 319a05f와 같다. `git diff --stat a57a517 319a05f`로 확인하면 G-P15b는 P11a의 source 7파일을 건드리지 않았다.
- 계약 문서 `docs/testing/g11-resource-policy-cases.md`의 LF SHA-256은 `5977dd9ad11ae0686902d61c1edfa6cddb38826bc0bf9adbb9fa715e47a49a33`으로 배정값과 같다.
- 작업 트리의 같은 24파일을 LF로 정규화하면 tree blob과 24/24 일치한다. 작성자가 작업 트리에 둔 판과 검토 판이 같다.
- 실행 위치는 다음과 같다. 작업 트리 `src`(G-P08 미완성 변경 포함)로는 판정하지 않았다.
  - 판정: `git archive c65413b1 | tar -x -C build/review-trees/g11a`
  - 변이: `build/review-trees/g11a-probe/mutants-work/m-*`(변이마다 pyproject·src·tests 사본, 실행 뒤 삭제)
  - 반례·로그: `build/review-trees/g11a-probe/*`
- `.venv`의 editable 설치가 작업 트리를 가리키므로 모든 실행에 `PYTHONPATH=<사본>\src`를 고정했다. 전체 회귀 직전 `recoryn.__file__`이 사본 안임을 기록했다(`full-import.txt`). 반례 스크립트는 import 직후 경로를 assert한다. 변이 harness는 변이 사본마다 `import recoryn`의 위치를 따로 읽어 사본 안인지 확인했다(15/15).
- Git 쓰기, 설치, 네트워크, 실제 GPU·Ollama·모델·유료 호출, Credential Manager, 하위 에이전트, herdr는 사용하지 않았다.

## 2. 직접 실행한 명령과 결과

공통 조건: cwd는 사본, `.venv\Scripts\python.exe`(Python 3.13.1), `QT_QPA_PLATFORM=offscreen`, `HF_HUB_OFFLINE=1`, `-p no:cacheprovider`, 실행별 OS TEMP의 새 `--basetemp`.

| # | 명령 | 결과 |
| --- | --- | --- |
| R1 | `pytest -q -p no:cacheprovider -W error::ResourceWarning --basetemp=%TEMP%\g11a-review-full-bt --cov=recoryn --cov-branch --cov-report=json:coverage.json --cov-fail-under=85` (`g11a-probe/run_full.sh`, CI core와 같은 flag) | **20606 passed, skip 0, 1182.66s(19:42), exit 0.** 총 coverage 92.77% |
| R1b | `python scripts/check_coverage.py coverage.json` | domain 100.00/100.00, capture 99.85/98.57, jobs 99.10/96.04, storage 96.52/92.43, security 98.11/94.43, content 99.59/98.75, **all 94.22/88.40**(line/branch %), 7묶음 모두 PASS |
| R2 | `ruff check src tests scripts packaging` / `ruff format --check …` / `MYPYPATH=src mypy src/recoryn scripts packaging` | All checks passed / 183 files already formatted / **89 source files no issues** |
| R3 | 신규 4파일 `--collect-only`(`collect.txt`) | 230 node. ID 감사는 §3.7 |
| R4 | 신규 4파일 단독(변이 harness의 정상본 R00) | **230 passed, 6.67s**. 60초 게이트 충족 |
| R5 | 반례 스크립트 `probe_mislabel.py`, `probe_stop_race.py` | G11R-01·02 재현 |
| R6 | `ast_adapt_check.py`(기존 시험 11개 AST 대조) | 적응 10파일 AST 차이 0, `test_blocked_reasons.py`는 delta 함수만(§3.5) |
| R7 | `mutate.py`(검토자 변이 15개 + 정상본 2) | **10 KILLED / 5 SURVIVED**(§5) |
| R8 | `cov_lines.py`, `cov_branches.py`(R1의 coverage.json에서 신규 영역 미적중 줄·분기) | G11R-07 |

- 작성자 보고는 20,598 PASS(a57a517 기준)다. node 수가 8개 다른 것은 기준 HEAD 차이(319a05f에 들어온 G-P15b 시험)로 보인다. 그 8개를 하나씩 대조하지는 않았다. 이 tree에서 실패·skip은 0이다.
- 결합 coverage의 묶음 수치는 작성자 보고와 ±0.1% 안에서 같다.

## 3. 중점 검토 결과

### 3.1 정책 차단의 위치(로컬 서버·GPU 접촉 전)

- **요약.** bridge `summarize`의 1차 gate(`ui/ai_bridge.py:625-633`)는 privacy control의 provider 값과 클릭 시점 정책만 읽는다. 이 gate는 `checked_attestation()`, `prepare_execution`, adapter 생성, `service.summarize`보다 앞이다. 2차 gate(648)는 준비된 `config.provider_id`로 다시 본다. 실제 UI의 provider 값은 등록 6개뿐이라 1차 gate가 늘 판정한다.
  - 검토자 R01(1차 gate 제거)은 Ua 10행에서 검출됐다. 2차 gate만 남으면 `prepare_execution`이 먼저 불린다.
  - T31은 owned Ollama에서 attestation 요청 0, prepare 0, adapter 0을 확인한다. fallback 대조 행에서는 기존 attestation 순서가 그대로다.
- **직접 서비스 API.** `AIService.transcribe/summarize`의 첫 문장이 `_admit_resources`(`app/ai.py:249`, `515`)다. 세션 읽기·Job 생성보다 먼저 refusal을 던진다. 검토자 R02(서비스 admission에서 표 검사 제거)는 A 27행에서 검출됐다.
- **화자 구분.** GPU_ONLY 거부(`ui/ai_bridge.py:753`)는 `DiarizationConfig`(manifest 읽기)보다 앞이다. `admit_diarization`은 Job 생성보다 앞이다(780).
- **REMOTE.** `plan_static`은 REMOTE STT·요약을 세 정책에서 `not_applicable`로 통과시킨다. 이 PC의 GPU·RAM 관측은 읽지 않는다. T27·T28은 실제 PrivacyPanel·ConsentStore·CostLedger·Gateway·OpenAI adapter로 세 정책을 차례로 적용한다. 각 정책에서 동의 거부·비용 거부 때 wire 0, 유효 대조에서 wire 1이다. 검토자 R09(REMOTE STT의 GPU_ONLY 칸 하나만 차단)는 A·T27·T28·Ua 8행에서 검출됐다.
- **profile 부재.** P11a에는 profile catalog가 없다. owned 경로의 계획 상태는 `RESOURCE_ESTIMATE_UNKNOWN`이고, 표시 문구는 "메모리 요구량 미확인"이며 오류 코드가 아니다(`test_estimate_unknown_is_a_display_state_not_an_error_code`). 기존 고정 1GiB `choose`는 그대로다. 결과 문서도 이를 P11b 몫으로 적었다.
- **범위 밖 관찰.** `DesktopAI.tick()`의 첫 줄(`ui/ai_bridge.py:1024`)은 정책과 무관하게 매 tick `model_panel.request_attestation_check()`를 부른다. 앱이 시작한 owned Ollama가 있으면 CPU_ONLY에서도 이 확인이 돈다. 이 확인은 `ManagedOllama.attestation()`(`models/ollama.py:211`)이 캐시한 proof의 `execution_guard`를 보는 것이며 추론이나 GPU 사용은 아니다. 기존 동작이다. T31이 증명하는 "attestation 0"은 **거부된 요청 한 건의 범위**라는 점만 기록한다.

### 3.2 계약 밖 추가

- **`admit_diarization`·`capture_diarization`.** 계약 §3.2("STT/요약/화자의 제품 접수 API에 필수")와 §3.1 표의 LOCAL_SHERPA 행을 따른 것이다. 새 의미는 없다.
  - CPU_ONLY·fallback에서는 화자 구분 동작이 그대로다. 등록 문구 끝에 캡처 정책 note가 붙는다.
  - GPU_ONLY에서는 이제 준비 단계에서 거부된다. 기존에는 CPU로 실행했다. 이는 §3.1 표가 정한 변화이며, 계약 §2가 고칠 대상으로 적은 현황("CPU-only provider도 전역 장치 정책 없이 접수")이다.
  - 화자 구분에는 동의·비용 경로가 없다. 바뀐 경계도 없다.
  - bridge 경로의 capture와 서비스 admission은 시험이 관측하지 않는다(G11R-03).
- **`sherpa_onnx` registry 항목.** privacy 화면에 노출되지 않는 내부 식별자다. `_selected_provider("diarization")`이 상수로 돌려준다. 화자 backend가 하나뿐인 현재 사실과 맞는다.
- **정책 코드의 행동 연결을 bridge에서 처리.** 사용자 표시 경로는 모두 bridge를 지나므로 Ua·T30·AUX-NOCAPTURE에서 `execution_policy`로 확인된다. 공용 표와 갈라진 점은 G11R-04에 적었다.

### 3.3 실행 snapshot 불변성

- 캡처는 `_admit`이 admitted를 돌려준 경우에만 한다(`app/ai.py:286`, `592`). 병합 요청은 캡처를 바꾸지 않는다. 검토자 R13(STT)·R14(요약)는 캡처를 병합 앞으로 옮긴 변이이며 AUX-CAPTURE와 Ua queued 행에서 검출됐다.
- runner task는 호출 시점의 frozen `resources`를 closure로 쓴다. UI 정책 값을 다시 읽지 않는다. STT 로컬 경로의 `gpu_source(policy, …)`와 `choose(policy, …)`도 클릭 때 읽은 같은 `policy` 변수를 쓴다.
- 명시 계속(`expected_job_id`)은 `_admit_resources`가 먼저 통과해야 `jobs.resume`에 닿는다. 거부되면 Job·version·attempt가 그대로다(T30 1단계). 통과하면 새 요청으로 캡처를 교체한다(T30 2단계, 결정 ⑦). `jobs.resume`은 BLOCKED만 받으므로 QUEUED·RUNNING의 캡처를 계속으로 바꿀 수 없다.
- `config_key`: 로컬 STT의 `digest:device`(`ui/ai_bridge.py`의 `key = digest + ":" + device`)와 privacy의 `_config_key`는 바뀌지 않았다. ResourceRequest·priority·정책은 Job input key에 들어가지 않는다.
- 캡처는 프로세스 메모리에만 있다. 재시작 뒤에는 "이 실행에서 접수한 기록 없음"으로 정직하게 표시한다(AUX-NOCAPTURE). 영속 ExecutionPlan은 계약상 이번 범위가 아니다.

### 3.4 112코드 감사

- `jobs/failures.py`의 등록 코드는 C10/A3/P17/R17/B24/T8/F31/U1 = 111개다. 미등록 대표를 더하면 **112**다. CAPABILITY만 15→17로 늘었다.
- `tests/unit/test_blocked_reasons.py`는 승인된 G07 표 110행을 그대로 두고 G11 delta 2개를 별도로 더해 비교한다. 겹침 0도 단언한다. 검토자 AST 대조로 이 파일의 변경은 이 함수와 delta 상수 하나뿐이다.
- `block_pending`은 두 코드를 CAPABILITY로만 받는다. RESOURCE로 주면 `BLOCK_REASON_MISMATCH`이고 상태가 바뀌지 않는다(C097~C100).
- 사용자 문자열에서 코드를 꺼내는 제품 코드는 없다. `_with_resources`의 `str(error)`는 `plan_static`이 던진 자체 StateConflict(REFUSALS 3개 중 하나)의 인자다. 시험 쪽 예외는 G11R-05에 적었다.

### 3.5 기존 시험 11개 적응

`build/review-trees/g11a-probe/ast_adapt_check.py`로 두 판을 AST로 대조했다. 새 판에서 `resource_request=` keyword와 `tests.resource_fakes` import만 지운 뒤 비교했다.

| 파일 | 지운 keyword | 지운 import | 남은 AST 차이 |
| --- | ---: | ---: | ---: |
| `tests/e2e/test_ai_workflow.py` | 15 | 1 | 0 |
| `tests/integration/test_ai_independent.py` | 15 | 1 | 0 |
| `tests/integration/test_blocked_reason_flow.py` | 6 | 1 | 0 |
| `tests/integration/test_desktop_independent.py` | 2 | 1 | 0 |
| `tests/integration/test_publication_independent.py` | 1 | 1 | 0 |
| `tests/integration/test_selection_version_cas.py` | 21 | 1 | 0 |
| `tests/integration/test_unfinished_recovery.py` | 1 | 1 | 0 |
| `tests/ui/test_blocked_reason_ui.py` | 3 | 1 | 0 |
| `tests/ui/test_consent_scope_ui.py` | 2 | 1 | 0 |
| `tests/unit/test_unfinished_sessions.py` | 1 | 1 | 0 |
| `tests/unit/test_blocked_reasons.py` | 0 | 0 | G11 delta 상수와 `test_closed_catalog_matches_independent_table`(§3.4) |

assertion 약화는 0이다. 적응 fixture는 `STT=LOCAL_CT2/CPU_ONLY`와 `SUMMARY=REMOTE/CPU_ONLY`다. 둘 다 장치 정책을 통과하는 조합이라 기존 시험의 의미를 바꾸지 않는다. 다만 fake 요약 provider에 REMOTE 표지를 붙이는 방식은 G11R-01의 신뢰 가정에 기대고 있다.

### 3.6 작성자 관찰(stop의 BLOCKED→CANCELLED)

G11R-02로 재현했다. 심각도 의견은 **S3, 범위 밖 기존 결함**이다.

### 3.7 시험 충분성

- **case ID:** 신규 4파일 `--collect-only`는 230 node다. parametrize ID는 A 36, C 20(C001~016 + C097~100), T 4(T19·T20·T27·T28), UA 144이고, 이름 붙은 T30·T31 2개를 더하면 **206**이다. 중복 0, 계획 밖 ID 0이다(AUX 11은 DTO 보조). 32,799 전체 분모 산식과 P11b 32,593 미주장은 property 시험이 확인한다.
- **독립 oracle:** A·Ua의 기대 표는 손으로 쓴 `TABLE`이다. 제품 catalog를 import하지 않는다. 계약 §3.1 표와 12조합×3정책을 대조해 일치했다.
- **검토자 변이:** 15개 중 10개 검출, 5개 생존(§5, G11R-03).
- **작성자 변이 8개**는 재실행하지 않았다. 검토자 R01·R02·R09·R13·R14가 M01·M03·M26·M24와 겹치는 영역을 다른 위치에서 검출했다.

## 4. 발견 사항

| ID | 심각도 | 상태 | 요약 |
| --- | --- | --- | --- |
| G11R-01 | S3 | OPEN | 서비스 admission이 호출자 주장 backend를 provider 실체와 대조하지 않음 |
| G11R-02 | S3 | OPEN(범위 밖) | `BoundedRunner.stop()`이 BLOCKED(known)를 CANCELLED로 바꿈 |
| G11R-03 | S3 | OPEN | 검토자 변이 5개 생존: dispatch 재검사·bridge 화자 capture·서비스 admission·DTO 경계 2 |
| G11R-04 | S3 | OPEN | 정책 코드의 `execution_policy` 연결이 공용 표가 아닌 bridge에만 있음 |
| G11R-05 | S3 | OPEN | T27·T28이 표시 문자열에서 코드를 꺼내 같은 문자열과 비교 |
| G11R-06 | S3 | OPEN | `ResourcePlan.applies`가 허용 Ollama와 REMOTE를 구분하지 않음 |
| G11R-07 | S3 | OPEN | 결과 문서의 coverage 미적중 목록·수치 불일치 |

### G11R-01 (S3) 서비스 admission이 backend 표지를 provider와 대조하지 않음

- **재현:** `build/review-trees/g11a-probe/probe_mislabel.py`. `PYTHONPATH=<사본>\src`, cwd는 probe 폴더다.
  - 입력: `capabilities().provider_id == "ollama"`인 fake 요약 provider에 `ResourceRequest("summary", "REMOTE", "CPU_ONLY"/"GPU_ONLY")`을 붙여 `AIService.summarize`를 직접 호출한다. 대조로 같은 provider에 정직한 OLLAMA 표지를 붙인다. `faster_whisper` fake STT에는 REMOTE/GPU_ONLY 표지를 붙인다.
  - 관측:

    ```text
    local STT labelled REMOTE under GPU_ONLY -> SUCCEEDED
    CPU_ONLY honest OLLAMA label -> RESOURCE_POLICY_UNVERIFIED
    CPU_ONLY REMOTE label on ollama provider -> SUCCEEDED provider calls 1
    GPU_ONLY honest OLLAMA label -> RESOURCE_POLICY_UNVERIFIED
    GPU_ONLY REMOTE label on ollama provider -> SUCCEEDED provider calls 2
    ```

- **기대:** 계약 §3.1은 "endpoint 문자열만으로 REMOTE/OLLAMA를 바꿔 우회하지 않고 등록한 provider/backend identity로 구별한다"고 쓴다. §3.2는 "UI만 검사하고 직접 AIService 호출이 우회하는 경로를 허용하지 않는다"고 쓴다. 서비스가 `request.backend`를 provider의 등록 identity와 대조해 불일치를 `INVALID_RESOURCE_REQUEST`로 거부해야 한다. 그러지 않을 거라면 "서비스는 in-process 호출자의 표지를 신뢰한다"를 계약에 명시해야 한다. 대조 수단으로는 요약 adapter의 순수 함수 `capabilities().provider_id`(`summarization/adapters.py:103-104`)와 `PROVIDER_BACKENDS`가 이미 있다.
- **근거:** `app/ai.py:150-160`은 type과 kind만 확인한다. 제품 호출자는 `ui/ai_bridge.py` 하나뿐이다. 요약은 648행과 678행이, STT는 472-477행과 576행이 같은 `config.provider_id`로 요청과 adapter를 정한다. 따라서 지금은 사용자 도달 경로가 0이다.
- **심각도 사유:** 현재 사용자 영향은 없다. 그러나 P11b가 backend로 owned lease·메모리 단계를 고르면, 같은 신뢰 가정이 lease 우회로 커진다. P11b 착수 전 결정을 권고한다.

### G11R-02 (S3, 범위 밖 기존 결함) stop()이 known BLOCKED를 CANCELLED로 바꿈

- **재현:** `build/review-trees/g11a-probe/probe_stop_race.py`. 결정적 재현이다.
  - 방법: `JobStore.fail`을 감싸 BLOCKED commit 직후 worker를 event로 잡아 둔다. 그동안 작업은 `_active`에 남아 있다. 그 사이 다른 thread가 `runner.stop()`을 부른다.
  - 관측:

    ```text
    RESOURCE_POLICY_UNVERIFIED known -> ('BLOCKED/CAPABILITY', 'CANCELLED', 'CAPABILITY', True)
    COST_CAP_EXCEEDED known -> ('BLOCKED/BUDGET', 'CANCELLED', 'BUDGET', True)
    REMOTE_OUTCOME_UNKNOWN unknown -> ('BLOCKED/REMOTE_UNKNOWN', 'BLOCKED', 'REMOTE_UNKNOWN', True)
    ```

- **기대:** 실행 attempt가 이미 논리 종료되어 BLOCKED(known)가 된 Job은 종료 처리에서 상태·사유·계속 가능성을 유지해야 한다. REMOTE_UNKNOWN은 이미 보존된다.
- **근거:**
  - `jobs/runner.py:171`은 `_queue`와 `_active`를 그대로 모으고, 176행은 각 항목에 `jobs.cancel`을 부른다.
  - `_active`에서 빠지는 것은 196행(`_worker`의 finally)이다. 이것은 `_execute`의 finally가 `jobs.get`을 마친 뒤다.
  - `jobs/__init__.py:451-456`은 REMOTE_UNKNOWN이 아닌 BLOCKED를 CANCELLED로 바꾼다.
  - 제품 진입점은 `AIService.close`(`app/ai.py:662`)다. 창 닫기에서 `DesktopAI`가 부른다(`ui/ai_bridge.py:1223`).
- **심각도 의견:** S3다.
  - 창은 `fail()` commit에서 `_active.pop`까지의 짧은 구간이다. 앱 종료와 겹칠 때만 열린다.
  - 원본·게시·전송·과금 영향은 0이다. UNKNOWN 논리도 보존된다.
  - 사용자는 차단 사유와 '계속'을 잃고, 새 요청으로 같은 작업을 다시 해야 한다.
  - `jobs/runner.py`는 319a05f와 같으므로 G-P11a가 만든 결함이 아니다.
  - 수정은 `jobs/runner.py` 범위(P11b)나 G-P07 후속이다. 방법은 두 가지다. stop이 cancel 직전 상태를 다시 읽어 RUNNING·QUEUED·BACKOFF만 취소하게 하거나, 이미 논리 종료된 항목을 `_active`에서 먼저 빼면 된다.
  - G11-C-004의 시험 하네스 수정(private `_condition/_queue/_active` idle 대기)은 시험 경쟁을 정당하게 없앤 것이다. 다만 제품 경쟁을 검증하지는 않는다. 수정 단위에 위와 같은 barrier 제품 시험이 필요하다.

### G11R-03 (S3) 검토자 변이 5개 생존

| 변이 | 위치 | 결과 | 의미 |
| --- | --- | --- | --- |
| R03 summarize의 dispatch 재검사 제거 | `app/ai.py:596` | 230 PASS | AUX-DISPATCH는 transcribe만 본다. bridge 화자 task의 재검사(`ui/ai_bridge.py:792`)도 같은 상태다 |
| R04 bridge 화자 구분의 `capture_diarization` 제거 | `ui/ai_bridge.py:783` | 479 PASS(신규 4 + 화자 경로 3파일) | Ua의 `admit()` helper가 capture를 직접 부르고, 실제 `diarize()`가 submit까지 가는 기존 시험은 캡처를 보지 않는다. 실제 화자 Job 표시가 "이 실행에서 접수한 기록 없음"으로 바뀌어도 통과한다 |
| R05 bridge 화자 구분의 `service.admit_diarization` 제거 | `ui/ai_bridge.py:780` | 479 PASS | UI gate가 먼저 거부하므로 이중 방어가 중복된다. 서비스 API 자체는 unit이 직접 확인한다 |
| R11 envelope 중복 key 허용 | `models/resources.py`의 `len({item[0]…}) != len(envelope)` 제거 | 230 PASS | DTO 시험 목록에 중복 key가 없다 |
| R12 envelope 상한 `< 2**63`→`<= 2**63` | 같은 파일 | 230 PASS | i64 경계 시험이 없다(계약 T03은 P11b 몫) |

- **기대:** dispatch 재검사(§3.2)와 화자 구분 캡처 표시(§6)는 이 단위가 추가한 행동이다. 각각 목표 assertion으로 검출돼야 한다.
- **권고:** AUX-DISPATCH를 summary와 화자 구분에도 적용한다. `diarize()`가 submit까지 가는 행 하나에서 `service.resource_request(job)`과 tick 문구를 확인한다. DTO의 중복 key와 `2**63` 경계를 보조 행에 추가한다(T03과 연결해 P11b에서 해도 된다).
- P11a의 dispatch 재검사는 frozen 요청과 불변 표를 다시 보는 것이라 지금은 실패할 수 없다. 이 공백의 현재 사용자 영향은 0이다.

### G11R-04 (S3) 정책 코드의 행동 식별자가 공용 표와 갈림

- **재현:** 사본에서 `ai_status(preparation=NormalizedFailure(code))`를 직접 부른다.
  - `RESOURCE_POLICY_UNVERIFIED`·`RESOURCE_GPU_UNSUPPORTED` → `reason='CAPABILITY', action_id='model'`
  - `RESOURCE_GPU_UNAVAILABLE` → `action_id='execution_policy'`
- **기대:** 결정 ⑥은 G-P07이 추가한 "실행 정책 위치" 행동 식별자를 쓰라고 정했다. G-P07은 그 연결을 공용 `app/status.py:_action`에 두었다.
- **근거:** `app/status.py:66-87`, `ui/ai_bridge.py:36-58`(`POLICY_CODES`·`policy_block_status`), `ui/ai_bridge.py:229-230`, `ui/ai_bridge.py:1103-1139`.
- **판단:**
  - 현재 사용자 표시는 모두 bridge를 지난다. `open_blocked_action`도 tick이 저장한 `_blocked_target[3]`을 쓴다. 따라서 Ua·T30·AUX-NOCAPTURE에서 `execution_policy`로 확인된다.
  - 그러나 `status.py`를 직접 쓰는 다른 소비자가 생기면 같은 코드가 '모델 설정'을 가리킨다. 예를 들어 G-P08이 `status.py`를 바꾸고 있다.
  - `status.py`는 P11a 범위 밖이므로 작성자가 공개한 선택이다. `status.py` 소유 단위(G-P16 등)에서 `_action`으로 옮기고 bridge override를 지우는 것을 권고한다.

### G11R-05 (S3) T27·T28의 코드 판정이 표시 문자열에 기댐

- **근거:** `tests/integration/test_resource_policy.py:164`. Job이 생기지 않으면 `next((c for c in CONSENT_OR_AUTH | COST if c in text), None)`로 표시 문자열에서 코드를 찾는다. 190행은 이어서 `code in text`를 단언하는데, 이는 동어반복이다.
- **판단:** 실제 판정력은 정책별 `wire.opens` 불변과 `prepare_execution` 호출 수에 있다. 이 둘은 유효하다. G-P07은 "문자열 포함 검색으로 범주를 추정하지 않는다"고 쓴다. 이 시험 oracle은 그 원칙에 어긋나는 형태다.
- **권고:** `prepare` wrapper에서 발생한 예외의 `code`를 직접 기록해 손으로 쓴 집합과 대조한다. 표시 문자열에는 그 코드가 보이는지만 확인한다.

### G11R-06 (S3) `ResourcePlan.applies`의 의미

- **재현:** 두 요청에 `plan_static`을 부른다.
  - `ResourceRequest("summary","OLLAMA","GPU_WITH_CPU_FALLBACK_ALLOWED")` → `applies=False, device='server_unknown'`
  - `ResourceRequest("summary","REMOTE","GPU_ONLY")` → `applies=False, device='not_applicable'`
- **기대:** 계약 §4.3·§6은 "REMOTE는 장치 정책 NOT_APPLICABLE, 허용 Ollama는 device=server_unknown"으로 구분한다. 허용 Ollama에도 장치 정책은 적용된다. CPU_ONLY·GPU_ONLY에서 막는 것이 바로 그 정책이다.
- **근거:** `models/resources.py:189`.
- **판단:** `device`로 구분되므로 현재 영향은 0이다. P11b가 `applies`를 "정책 적용 여부"로 읽으면 Ollama를 정책 비적용처럼 다룰 위험이 있다. 필드 이름을 owned 자원 단계 여부로 바꾸거나, docstring을 그 의미로 고정할 것을 권고한다.

### G11R-07 (S3) 결과 문서의 coverage 기록

- **재현:** R1의 `coverage.json`에 `cov_branches.py`를 돌려, 이 단위가 추가한 영역의 미적중 줄·분기를 뽑는다.
- **관측과 결과 문서의 차이:**
  - 결과 문서는 "live 임시 전사의 gate 거부 뒤 재시도 억제 표시(470·484)"라고 쓴다. 그러나 `ui/ai_bridge.py:470`은 새 gate가 아니다. 기존 `prepare_execution` 예외 분기의 live 억제 줄이다. 새 1차 gate의 live 억제 줄은 **458**이고, 이 줄도 미적중이다(분기 457→458).
  - 결과 문서의 목록에 없는 미적중도 있다. 화자 구분 `submit` closure(`ui/ai_bridge.py:772-785`)에는 새 `admit_diarization`(780)과 `capture_diarization`(783)이 들어 있는데, 이 줄들이 미적중이다. 같은 경로의 runner task 줄(792)은 적중한다. 따라서 이 미적중은 coverage가 QThreadPool thread를 추적하지 않아 생긴 측정 공백으로 보인다. 그래도 G11R-03의 R04·R05 생존과 겹친다. 새 화자 admission·capture 줄에는 coverage와 판정 assertion이 **둘 다** 없다.
  - "resources.py 85%(미적중은 기존 probe_gpus 본문)": 미적중은 52-61(`probe_gpus`)과 92-93(legacy `acquire`의 취소 대기)이다. 둘 다 기존 코드다. 신규 영역(100행 이후)은 줄·분기 미적중이 0이다. 결론은 맞고 설명만 일부 빠졌다.
  - `app/ai.py`의 신규 미적중은 173(`capture_diarization`의 kind 불일치 거부)뿐이다.
- **기대:** 결과 문서의 "coverage가 닿지 않은 새 경로" 목록이 실제 미적중과 일치해야 한다. 측정 공백(Qt pool thread)은 그 사실을 따로 적어야 한다.
- **판단:** 판정 근거를 의미 행·mutation에 두라는 작성자의 문장은 옳다. 이 항목은 기록 정확성 문제다.

## 5. 검토자 변이

`build/review-trees/g11a-probe/mutate.py`를 썼다. 변이마다 새 사본(pyproject·src·tests)에 하나만 적용했다. 각 사본에서 `import recoryn` 위치를 확인했고(15/15 사본 안), 실패는 모두 목표 node의 assertion 실패였다. import·수집 오류는 0이다. 대상 node는 신규 4파일이다. R04·R05에는 화자 구분 bridge 경로를 실제로 타는 기존 3파일(`test_ai_independent`, `test_selection_version_cas`, `test_live_ui`)을 더했다.

| ID | 변이 | 결과 |
| --- | --- | --- |
| R00 | 정상본: 신규 4파일 / 화자 경로 3파일 | 230 PASS 6.67s / 249 PASS 21.50s |
| R01 | bridge 요약의 1차 gate 제거(2차 gate만 남김) | **KILLED** 10(UA-017·021·025…) |
| R02 | `_admit_resources`에서 `plan_static` 제거 | **KILLED** 27(A-02·03·05…) |
| R03 | summarize task의 dispatch 재검사 제거 | SURVIVED |
| R04 | bridge 화자의 `capture_diarization` 제거 | SURVIVED |
| R05 | bridge 화자의 `admit_diarization` 제거 | SURVIVED |
| R06 | `resource_note`가 현재 선택 정책을 표시 | **KILLED** 15(UA-002·003…) |
| R07 | tick이 표가 거부하는 옛 요청·늦은 callback을 정상 표시 | **KILLED** 72 |
| R08 | 표에서 LOCAL_SHERPA GPU_ONLY를 cpu로 | **KILLED** 5(A-22, UA-085…) |
| R09 | 표에서 REMOTE STT의 GPU_ONLY만 차단 | **KILLED** 8(A-16, T27·T28…) |
| R10 | 정책 코드 준비 거부에서 `execution_policy` 연결 제거 | **KILLED** 6(UA-025·073…) |
| R11 | envelope 중복 key 허용 | SURVIVED |
| R12 | envelope 상한 off-by-one | SURVIVED |
| R13 | STT 병합 요청이 캡처를 덮음 | **KILLED** 7(AUX-CAPTURE, UA-002…) |
| R14 | 요약 병합 요청이 캡처를 덮음 | **KILLED** 3(UA-030·078…) |
| R15 | bridge STT의 1차 gate 제거 | **KILLED** 6(UA-005…) |

## 6. 미검증·한계

- 실제 GPU·nvidia-smi·Ollama 서버·모델·원격 provider·유료 호출은 실행하지 않았다.
- offscreen Qt에서는 키보드 초점과 스크린리더 낭독을 판정하지 않았다.
- 작성자 mutation 8개는 재실행하지 않았다. 같은 영역의 검토자 변이로 대신했다(§3.7).
- P11b 몫(관측·profile 산술·UUID/ordinal·lease·ACK·priority, 나머지 10코드)은 이 검토 범위가 아니다. 이번 결과를 그 검증으로 쓰지 않는다.
- 작업 트리의 G-P08 변경(`app/status.py` 등)과의 의미 충돌은 판정하지 않았다. 텍스트 겹침은 없다(P11a는 `status.py`를 쓰지 않는다).
- 정책 안내 문구 "앱을 다시 시작하면 기본값 CPU_ONLY로 돌아갑니다"(`ui/ai_bridge.py:41`, `ui/models.py:35-41`)는 이 tree에서는 사실이다. G-P16이 정책을 저장하게 되면 같은 단위에서 고쳐야 한다.

## 7. 증거 파일

모두 `build/review-trees/g11a-probe/` 아래 파일이며, 해시는 LF 기준 SHA-256이다.

| 파일 | SHA-256 |
| --- | --- |
| `run_full.sh` | `ae2306377f8412aebb3b3cb5f356ed60a82fb086aca6db4ae0e60972b78ebb38` |
| `full.log` | `2f091269045a64ec483d6e0aa3fb6c16335f6deeb9d9a069855da6b6ecda717a` |
| `coverage-check.txt` | `b08055c8efd46c65e494382b855865228543348a63fd2f6ec7f2d6b4bcc16426` |
| `../g11a/coverage.json` | `b70faf8cfc8398c7397152012e311f3fc12c4b727f828313263a51b85ef2fa54` |
| `collect.txt` | `875f6a4571fdd83df0acc08bfd878194bd43eae12b8ec744ae1ec984dd4e3cb9` |
| `ast_adapt_check.py` | `7fe13d4d56d7a5557b11a200029c20de913fb39dd152ab827c996c6fa5d6e1e4` |
| `probe_mislabel.py` | `51f4d0959e3828dbc6c02f2dbcd476ff982b15f8bcd94c6fc30e32b57a107896` |
| `probe_stop_race.py` | `a9aaf5bc13ddacc95b7bfcf94972d51ba46e4b8f9b31b0317d56b04dda78a688` |
| `mutate.py` | `2ce90b813e0204acd981fec2d3864b2b1a03174d7e413dd2ec9f4337dcce0366` |
| `mutants/summary.txt` | `b583c7cd34d9e3fc9d7e48e1074b0cd453584423ef3ffd9a91821bdaf4d8f341` |
| `cov_lines.py` | `a63f90dce65707cc11f24fc9cd1a4ef3631ba9e4ab4e4cd652449cffedca25bd` |
| `cov_branches.py` | `18d91a23933c33f55ddfcd15615fb5ea4c4a7defa2b307185d167e9d86391f91` |
