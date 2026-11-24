# G11 / G-P11b 모델 메모리·자원 lease·priority 독립 검토

2026-11-25, 검토자 Claude(C00 지정 G-P11b 독립 검토 하위 에이전트). 작성자는 w5:p7 Claude다. 검토자는 이 단위의 코드·시험·계약 문서를 작성하지 않았고, 이 문서 외에는 저장소 파일을 고치지 않았다.

**판정: OPEN 6건 — S0 0 / S1 0 / S2 0 / S3 6.** S0·S1이 없으므로 이 기준만으로는 push를 막지 않는다. 수용과 통합은 C00이 결정한다.

다음 반례는 찾지 못했다.

- lease·종료 ACK·probe가 녹음 경로(seal·finalize·recover)를 기다리게 하는 경로. lease는 Library live owner로 등록되지 않고, Job local reader는 삭제 판정(`_active_jobs`)에서만 읽힌다.
- GPU_ONLY에서 CPU worker를 만드는 경로, CPU_ONLY에서 GPU를 관측하거나 runtime을 확인하는 경로
- UUID 중복·MIG·`CUDA_VISIBLE_DEVICES`·CUDA 수 불일치에서 GPU를 VERIFIED로 보고 실행하는 경로, host index를 CUDA ordinal로 넘기는 경로(검토자 N05·N06 검출)
- 고정 1GiB·GPU0 필터가 제품 경로에 남은 곳(bridge는 legacy `choose`를 부르지 않는다. T29)
- UNKNOWN 요구량을 0이나 known으로 바꾸는 경로, profile 부재를 차단 코드로 만드는 경로
- runner lock 변경에 따른 교착. lock 순서는 runner `_condition` → root mutex → JobStore `_lock`이고, 역순으로 잡는 호출자는 찾지 못했다(§3.3).
- 122코드 catalog와 G-P07 표의 불일치

S3 6건의 요지는 다음과 같다.

1. **G11BR-01:** 복수 실패의 대표 코드 순서가 계약 §4.3의 독립 oracle 순서와 다르다. 시험 oracle도 구현 순서를 따라 적혀 있어 P cube 256행에서 계약과 다른 값을 기대한다. snapshot TTL도 제안값 2초가 아니라 5초이며 문서에 없다.
2. **G11BR-02:** runner가 결과 기록을 runner lock 안에서 하면서, UI tick의 `admission_error()`가 root mutex·SQLite 대기 시간만큼 막힌다(기준 0.000초 → 1.518초 재현).
3. **G11BR-03:** 종료 ACK가 실패한 뒤 worker가 스스로 끝나도 reap을 다시 시도하는 주기 경로가 없다. 그래서 Job local reader·slot·삭제 대기·모델 관리 비활성이 다음 무거운 작업이나 GPU runtime 제거 시도 전까지 남는다. 다음 grant에서 다시 시도하는 유일한 자동 경로는 시험이 없다(검토자 N03 생존).
4. **G11BR-04:** 결과가 UNKNOWN이고 worker도 끝나지 않으면 Job local reader가 풀려, 삭제가 살아 있는 worker를 기다리지 않는다. 지금의 제품 worker는 UNKNOWN을 만들지 않으므로 도달 경로는 없다.
5. **G11BR-05:** Job마다 worker를 새로 띄우는 비용의 하한을 쟀다. spawn 0.2초에 faster_whisper import 0.4~1.9초가 더해지고, 모델 로드는 재지 못했다. live STT 갱신마다 이 비용이 든다. 계약이 승인한 선택이지만 실제 지연은 미측정이다.
6. **G11BR-06:** 검토자 변이 19개 중 4개(N03·N07·N11·N12)가 살아남았다. 모두 다른 방어가 있어 현재 사용자 영향은 없지만, 그 방어 하나를 직접 보는 시험 행이 없다(§5).

## 1. 입력 고정과 범위 판정

- 검토 대상은 tree **`0caa69d318f973195b9f503760f02373bbe13a5d`**다(`git cat-file -t` = tree). 기준은 HEAD **b925520**(G-P11a)이다.
- `git diff b925520 0caa69d3 --stat`: **21파일, 4366 insertions / 264 deletions**. 모두 계약 §10.1의 G-P11b 26파일 안이다. 범위 밖 변경은 0건이다. 바뀌지 않은 5파일(`ui/models.py`, `test_consent_scope_ui`, `test_cost_cap_ui`, `test_blocked_reason_case_space`, `test_blocked_reason_flow`)은 결과 문서의 목록과 같다.
- 계약 문서의 LF SHA-256은 `655e606e0655b60df78bcfbae9579e85a6e9edb84e3f5a41d62bb767c5342fde`다. 앞 절(LF `5977dd9a…`)은 바뀌지 않았고 "§구현 결과(G-P11b)" 절만 덧붙었다(diff가 추가 153줄뿐).
- 실행 위치는 다음과 같다. 작업 트리 `src`(G-P08 미완성 변경 포함)로는 판정하지 않았다.
  - 판정: `git archive 0caa69d3 | tar -x -C build/review-trees/g11b`
  - 비교 기준: `git archive b925520 | tar -x -C build/review-trees/g11b-base`(G11BR-02 대조에만 사용)
  - 변이: `build/review-trees/g11b-probe/mutants-work/m-*`(변이마다 pyproject·src·tests 사본, 실행 뒤 삭제)
  - 반례·로그: `build/review-trees/g11b-probe/*`
- 모든 실행에 `PYTHONPATH=<사본>\src`를 고정했다. 전체 회귀 직전 `recoryn.__file__`을 기록했다(`full-import.txt`). 반례 스크립트는 import 직후 경로를 assert한다. `probe_cold_start.py`는 spawn된 inference child도 사본 src에서 import했음을 출력으로 확인했다. 변이 harness는 사본마다 import 위치를 확인했다.
- 실제 GPU·nvidia-smi·CUDA probe child·`GlobalMemoryStatusEx`·Ollama·모델·네트워크·유료 호출, Git 쓰기, 설치, Credential Manager, 하위 에이전트, herdr는 사용하지 않았다.
  - 예외는 하나다. G11BR-05 측정을 위해 CPU `LocalSTTProcess`를 빈 폴더로 띄웠다. 이 child는 모델 파일 확인에서 `MODEL_MISSING`으로 끝나며 faster_whisper도 import하지 않는다.
  - 또 새 interpreter에서 `import faster_whisper`만 실행했다.
  - 둘 다 모델·GPU·네트워크를 쓰지 않는다.

## 2. 직접 실행한 명령과 결과

공통 조건: cwd는 사본, `.venv\Scripts\python.exe`(Python 3.13.1), `QT_QPA_PLATFORM=offscreen`, `HF_HUB_OFFLINE=1`, `-p no:cacheprovider`, 실행별 OS TEMP의 새 `--basetemp`.

| # | 명령 | 결과 |
| --- | --- | --- |
| R1 | `pytest -q -p no:cacheprovider -W error::ResourceWarning --basetemp=%TEMP%\g11b-review-full-bt --cov=recoryn --cov-branch --cov-report=json:coverage.json --cov-fail-under=85 -rfEs` (`g11b-probe/run_full.sh`, CI core와 같은 flag) | **21275 passed, failure·error·skip 0, 1430.47초(23:50), exit 0.** 총 coverage 92.29% |
| R1b | `python scripts/check_coverage.py coverage.json` | domain 100.00/100.00, capture 99.85/98.57, jobs 99.29/96.23, storage 96.52/92.43, security 98.11/94.43, content 99.59/98.75, **all 93.69/88.05**(line/branch %), 7묶음 모두 PASS |
| R2 | `ruff check src tests scripts packaging` / `ruff format --check …` / `MYPYPATH=src mypy src/recoryn scripts packaging` | All checks passed / 184 files already formatted / **90 source files no issues** |
| R3 | 변경 모듈 coverage(R1 JSON) | `resource_catalog.py` 100%, `failures.py` 100%, `runner.py` 96%, `resources.py` 89%, `adapters.py` 89%, `diarization/process.py` 89%, `ai_bridge.py` 80%, `inference.py` 78%, `gpu_inventory.py` 69%(실제 API·nvidia-smi·count child는 계약상 미실행) |
| R4 | 신규 4파일 + `test_gpu_runtime_ui` + `test_runner`(변이 harness 정상본) | **934 passed, 26.90초**(신규 4파일만 따로 재지는 않음; 작성자 보고는 899 PASS·18.2초) |
| R5 | 반례 6개(§4) | G11BR-01~05 재현 또는 측정 |
| R6 | G11R 재확인 2개(§3.5) | G11R-01·02 RECHECKED |
| R7 | `mutate.py`(검토자 변이 19개 + 정상본) | **15 KILLED / 4 SURVIVED**(§5) |

- 작성자 보고(21,275 PASS, coverage 92.29%, 묶음 수치)와 node 수·coverage가 모두 같다.
- 실행 시간이 작성자 보고(1,276초)보다 긴 것은 같은 시각에 검토자 변이·반례를 함께 돌렸기 때문으로 보인다.

## 3. 중점 검토 결과

### 3.1 lease·종료 ACK와 녹음·삭제 경로

- **녹음 경로:** `Lease`는 `Library.register_live_owner`에 등록되지 않는다. Job local reader를 읽는 곳은 `Library._active_jobs`뿐이다(`storage/library.py:1498`, `1569`). 이 함수는 삭제 판정과 pending deletion 목록에서만 쓰인다. seal·finalize·recover는 reader나 lease를 기다리지 않는다.
  - `test_live_ui::test_slow_model_preparation_cannot_disable_or_delay_recording_stop`의 적응은 "bridge busy"를 "runner active"로 바꾼 것이다. 녹음 정지가 모델 준비를 기다리지 않는다는 원래 판정은 그대로 남아 있다.
  - worker 생성·모델 로드·CUDA count child·nvidia-smi는 runner 또는 QThreadPool thread에서 일어난다. 녹음 thread에서는 일어나지 않는다.
- **삭제가 실제 종료를 기다리는가:**
  - 정상 종료: runner가 task 반환 뒤 reader를 끝낸다.
  - 종료 ACK 실패: `StateConflict(reader_retained=True)`로 runner가 reader를 유지한다. 삭제는 `ACTIVE_READER_OR_WRITER`로 기다린다. reap이 성공하면 `on_ack`가 reader를 끝낸다.
  - 검토자 `probe_lazy_reap.py`로 SUCCEEDED + 보유 lease에서 reader 유지와 삭제 대기를 확인했다. 그러나 worker가 그 뒤 스스로 끝나도 reader가 풀리지 않는다(G11BR-03).
  - UNKNOWN 결과와 ACK 실패가 겹치면 reader가 풀린다(G11BR-04).
- **slot·lease 누수와 교착:**
  - 정상 경로에서 lease는 reap 성공 뒤에만 해제된다.
  - 보유 lease는 다음 grant가 `_try_ack`로 한 번 다시 시도한다. 실패하면 새 lease를 `RESOURCE_LEASE_HELD`로 거부하고, 그 factory는 부르지 않는다.
  - workers=1인 제품에서 grant 대기자는 보유 lease 외에는 생기지 않는다.
  - `Lease.reap`은 `_reaping` lock으로 직렬화된다. `_released`는 holder identity를 확인하므로 두 번 해제되지 않는다.
  - 누수나 교착은 찾지 못했다.
- **작성자 해석 (1) 판정: 타당하다.** live owner hook은 writer 생존을 뜻하며 seal·finalize·등록이 쓴다. 여기에 AI lease를 등록하면 녹음 독립 불변식을 깨뜨린다. reader 유지로도 §5.1의 목적("삭제/복구도 실제 child 종료를 기다림")을 대부분 달성한다. 남은 구멍은 G11BR-03·04다. 계약 §5.1의 문구와 다르므로 C00이 계약 정정을 수용해야 한다.

### 3.2 관측·UNKNOWN 경계·GPU identity

- **fail closed:**
  - GPU 관측 UNKNOWN·UNAVAILABLE, 장치 부재, identity 미검증은 GPU 실행을 막는다.
  - UNKNOWN GPU 요구량은 `VRAM.free >= GPU headroom`일 때만 통과한다.
  - known은 요구량 + headroom이며, 경계와 정확히 같으면 허용한다.
  - `MemoryObservation`·`GpuObservation`은 UNKNOWN에 현재 값이 들어오면 거부한다. cache는 `last_*`에만 있고 plan은 읽지 않는다.
  - P cube 31,104행과 검토자 반례로 확인했다. 단, 대표 코드 순서는 G11BR-01을 보라.
- **UNKNOWN 허용 경계:** UNKNOWN CPU는 RAM을 비교하지 않고 RAM을 관측하지도 않는다(`observation_needs`). profile 부재는 차단 코드가 아니며 `RESOURCE_ESTIMATE_UNKNOWN` 표시 상태다.
- **UUID/ordinal:**
  - `join_identity`는 PCI bus id 순서로 ordinal을 정한다. 아래 조건 중 하나라도 해당하면 VERIFIED가 아니다.
    - `CUDA_VISIBLE_DEVICES`
    - MIG
    - UUID 누락·중복
    - bus id 중복
    - CUDA 수 미확인·불일치
  - inference child와 count child는 모두 `CUDA_DEVICE_ORDER=PCI_BUS_ID`를 설정한다.
  - AUTO는 여유가 가장 큰 GPU를 고르고, 동률이면 UUID 순서다(검토자 N04 검출). 고정 UUID는 다른 GPU로 바꾸지 않는다.
- **장치 고정:** 준비 때 정한 `digest:device`를 lease의 `device` 제한으로 유지한다. 실행 직전 관측이 달라도 다른 장치로 바꾸지 않고 거부한다. 검토자 N13(고정 제거)이 T23에서 검출됐다.
- **작성자 해석 (2) 판정: 타당하다.**
  - 운영 profile catalog가 비어 있어 RAM 값을 쓰는 판단이 없다.
  - "RAM 관측 NOT_OBSERVED"는 관측하지 않은 사실을 정직하게 표시한 것이다.
  - §4.3 "RAM 관측 상태는 표시한다", §6 "RAM free 표시"와 문구상 차이가 있으므로 C00의 계약 정정 수용이 필요하다.
- **작성자 해석 (5) 판정: 수용 가능하다.** 이 `.venv`의 CTranslate2 4.9.0 CPU build는 `get_supported_compute_types("cpu")`가 `{'float32', 'int8_float32', 'int8'}`이다(모델 없이 조회). CPU에서 int8을 요청하면 보고값이 int8 또는 int8_float32일 수 있다는 가정과 맞는다. 실제 로드 객체의 보고값은 외부 게이트로 남는다.
- **관찰(재현 안 함):** GPU가 두 개이고 그중 하나가 CUDA에서 보이지 않으면(예: 지원하지 않는 구형 GPU), CUDA 수 ≠ host 수가 되어 모든 GPU가 미검증이 된다. fail closed이므로 결함은 아니지만 사용성 제한이다.

### 3.3 priority·공정 turn·runner lock

- `_take`는 취소되지 않은 대기자 중에서 고른다.
  - 보통 turn: 최소 priority, 그다음 최소 ordinal
  - 우선 선택 세 번 뒤: 가장 오래된 대기자
  - 실행 중 작업은 선점하지 않는다.
  - Q 864행은 실제 `BoundedRunner` trace를 손 규칙과 대조한다. 검토자 N01(공정 turn off-by-one)이 검출됐다.
  - 계속 도착하는 interactive 아래에서도 background가 네 번째 dispatch에 진행한다는 trace가 있다. 유한 trace일 뿐 시간 보증은 아니다.
- **lock 순서:**
  - worker: runner `_condition` → (`fail`·`_ack_cancelled`의) `Library.job_authority`의 root mutex → JobStore `_lock`
  - `snapshot()`: runner `_condition` → scheduler `_condition`(`held()`)
  - scheduler는 자기 lock을 잡은 채 runner를 부르지 않는다.
  - root mutex를 잡은 채 runner 메서드를 부르는 호출자는 `src` 전체 grep에서 0건이다(`cancel_session`은 Task 또는 직접 호출이며 root mutex 밖이다).
  - 교착은 찾지 못했다.
- **성능:** G11BR-02.

### 3.4 122코드 감사

- 사본에서 `CODE_GROUPS`를 세면 121개다. C10/A3/P17/R27/B24/T8/F31/U1이고, 미등록 대표를 더하면 **122**다.
- `models/resources.py`의 `RESOURCE_*` 상수 중 catalog 밖에 있는 것은 표시 상태 `RESOURCE_ESTIMATE_KNOWN`·`RESOURCE_ESTIMATE_UNKNOWN` 두 개뿐이다.
- `test_blocked_reasons.py`는 G07 110행을 그대로 두고 G11 delta 12개(CAPABILITY 2 + RESOURCE 10)를 별도로 대조한다.
- C017~096(직접 fail·runner)과 C101~120(`block_pending`)이 있다.

### 3.5 G11R RECHECK

| ID | 판정 | 근거 |
| --- | --- | --- |
| G11R-01 | **RECHECKED** | `recheck_mislabel.py`. 다음 다섯 경우가 모두 `INVALID_RESOURCE_REQUEST`, Job 0이다: faster_whisper→REMOTE/GPU_ONLY, ollama→REMOTE/CPU_ONLY·GPU_ONLY, openai→OLLAMA, openai→LOCAL_CT2. 등록된 REMOTE(anthropic)와 미등록 대역은 통과한다(작성자가 문서화한 신뢰 규칙) |
| G11R-02 | **RECHECKED** | `recheck_stop_race.py`(G-P11a 반례를 그대로 재실행). RESOURCE_POLICY_UNVERIFIED·COST_CAP_EXCEEDED·REMOTE_UNKNOWN 모두 BLOCKED가 유지되고 `cancel_requested`도 False다. 비용은 G11BR-02 |
| G11R-03 | **RECHECKED** | 검토자 R03·R04·R05·R11 변이가 이제 검출된다(§5). R12는 §5 |
| G11R-04 | 보류(C00 결정) | — |
| G11R-05 | **RECHECKED** | T27·T28은 `prepare_execution` wrapper가 기록한 예외 코드(`raised`)를 손 집합과 대조한다(`tests/integration/test_resource_policy.py:120-200`) |
| G11R-06 | **RECHECKED** | `ResourcePlan.owned`·`policy_applies`(`models/resources.py:324-377`). 허용 Ollama는 `owned=False, policy_applies=True`, REMOTE는 `policy_applies=False`다 |
| G11R-07 | **RECHECKED** | 계약 문서 "G-P11a 결과 절 정정"이 458·780·783·52-61·92-93을 정확히 적었다 |

### 3.6 작성자 판단 (1)~(6)

| # | 판정 | 숨은 위험 |
| --- | --- | --- |
| (1) live owner 대신 reader 유지 | 타당 | G11BR-03(자동 재시도 없음), G11BR-04(UNKNOWN 분기) |
| (2) 필요한 관측만 | 타당 | 계약 문구(§4.3·§6 RAM 표시)의 정정 수용 필요 |
| (3) STT 게시 뒤 ACK 실패를 SUCCEEDED로 | 타당(§5.1·§7.2 "논리와 물리 분리") | 사용자 영향은 아래와 같다. 원인 해소 뒤에도 자동으로 풀리지 않는다(G11BR-03) |
| (4) mutation 24 | 타당(개정 ⑧) | — |
| (5) int8_float32 별칭 | 수용 가능 | 실제 로드 객체의 보고값은 외부 게이트 |
| (6) live STT도 Job마다 재로드 | 계약(§5.1)대로 | G11BR-05. 모델 로드가 들어간 실제 지연 측정이 출시 전 게이트로 필요 |

(3)의 사용자 영향은 다음과 같다.

- 전사 결과는 게시되어 쓸 수 있다.
- Job 표시에 "작업자 종료 ACK 대기 · RESOURCE_LEASE_HELD"가 붙는다.
- 같은 세션 삭제는 `ACTIVE_READER_OR_WRITER`로 대기한다.
- `snapshot()["active"]`에 held가 포함되므로 모델 관리(`_models_idle`)와 GPU runtime 제거가 막힌다.
- 다음 로컬 STT·화자 구분은 한 번 reap을 다시 시도한다. 그래도 worker가 살아 있으면 `BLOCKED(RESOURCE_LEASE_HELD)`다.

## 4. 발견 사항

| ID | 심각도 | 상태 | 요약 |
| --- | --- | --- | --- |
| G11BR-01 | S3 | OPEN | 복수 실패 대표 코드 순서와 TTL이 계약 §4.3과 다르고, oracle이 구현 순서를 따름 |
| G11BR-02 | S3 | OPEN | runner lock 안의 결과 기록이 UI tick 조회를 root mutex·DB 대기만큼 막음 |
| G11BR-03 | S3 | OPEN | ACK 실패 뒤 worker가 끝나도 reap을 다시 시도하는 주기 경로가 없고, 유일한 자동 경로는 시험 없음 |
| G11BR-04 | S3 | OPEN | UNKNOWN + worker 미종료에서 Job local reader 해제(현재 도달 불가) |
| G11BR-05 | S3 | OPEN | Job별 worker 재기동 지연 미측정(live STT 매 갱신) |
| G11BR-06 | S3 | OPEN | 검토자 변이 생존(N03·N07) 등 시험 공백 |

### G11BR-01 (S3) 복수 실패 순서와 TTL이 계약과 다름

- **재현 1:** `build/review-trees/g11b-probe/probe_order.py`.
  - 입력: `ResourceRequest("stt","LOCAL_CT2","GPU_ONLY", model/runtime fixture)`에 known profile(CPU 100, GPU host 100, VRAM 80)을 적용하고, headroom RAM 20·GPU 10으로 `plan_resources`를 부른다.
  - 관측:

    ```text
    DIFF GPU UNKNOWN + RAM UNKNOWN: implementation=RESOURCE_GPU_PROBE_UNKNOWN contract=RESOURCE_CPU_PROBE_UNKNOWN
    DIFF VRAM short + RAM UNKNOWN: implementation=RESOURCE_MEMORY_INSUFFICIENT contract=RESOURCE_CPU_PROBE_UNKNOWN
    DIFF identity unverified + RAM UNKNOWN: implementation=RESOURCE_GPU_IDENTITY_UNVERIFIED contract=RESOURCE_CPU_PROBE_UNKNOWN
    DIFF GPU UNKNOWN + RAM stale: implementation=RESOURCE_GPU_PROBE_UNKNOWN contract=RESOURCE_SNAPSHOT_STALE
    SAME VRAM short + RAM short: …MEMORY_INSUFFICIENT
    ```

- **재현 2:** `probe_order_count.py`는 P cube 31,104행을 계약 순서로 다시 손으로 모델링한다. 작성자 oracle과 비교하면 **256행이 다르다**. 모두 GPU_ONLY × LOCAL_CT2 × GPU known profile이다(예: G11-P-10465). 작성자 oracle(`tests/unit/test_resource_policy.py:405-417`의 `gpu()`)은 GPU 관측 → VRAM → host RAM 관측 순이다. 이는 구현(`models/resources.py:521-575`, `_gpu_plan`이 관측·identity·VRAM 다음에 `_ram_fit`)과 같은 순서다. 그래서 P cube는 이 순서를 독립적으로 판정하지 못한다.
- **기대:** 계약 §4.3(103행)의 독립 oracle 순서를 따른다: 시각 유효성 → known profile의 host RAM 관측 UNKNOWN/UNAVAILABLE → GPU 관측 UNKNOWN/UNAVAILABLE·장치 부재 → identity → host RAM 부족 → VRAM 부족. 순서를 바꿀 근거가 있다면 계약을 정정해야 한다. §4.3(99행)은 snapshot TTL 기본값을 2초로 제안하는데, 구현은 5초다(`models/resources.py:434`, `821`). 결과 문서에는 이 차이가 없다.
- **판단:**
  - 대표 코드만 다르고 범주(RESOURCE)·BLOCKED·장치 결정은 같다.
  - 운영 catalog가 비어 known profile이 없으므로, 지금은 사용자 도달 경로가 0이다.
  - TTL은 lease 직후 관측·계획을 연달아 하므로 영향이 작다.
  - 첫 실제 profile 단위가 들어오기 전에 구현이나 계약 중 하나로 맞추고, oracle을 계약 문장에서 다시 쓸 것을 권고한다.

### G11BR-02 (S3) runner lock 안의 결과 기록이 UI 조회를 막음

- **재현:** `build/review-trees/g11b-probe/probe_runner_lock.py`. 결정적 재현이다.
  - 방법: 세션에 묶인 Job의 task가 실패한다. reader ACK 직후 다른 thread가 `root_mutex(library.root)`를 1.5초 잡는다. worker는 `with runner._condition:` 안의 `JobStore.fail` → `Library.job_authority`에서 root mutex를 기다린다. 그동안 주 thread가 표시 조회 `runner.admission_error()`를 부르고 걸린 시간을 잰다.
  - 관측:
    - 기준 b925520(`g11b-base`, `PROBE_TREE`·`PYTHONPATH`만 바꿔 같은 스크립트): `admission_error() blocked 0.000s`
    - 이 tree: `admission_error() blocked 1.518s while the root mutex was held 1.5s`
    - 두 경우 모두 최종 상태는 `BLOCKED RESOURCE RESOURCE_EXHAUSTED`다.
- **근거:**
  - `jobs/runner.py:284-292`(complete·`_ack_cancelled`)와 `295-317`(get·fail)이 runner `_condition` 안에서 DB transaction과 `_session_transaction`(→ `job_authority`의 root mutex·journal prefetch)을 실행한다.
  - `DesktopAI.tick()`(`ui/ai_bridge.py:1144`, `1159`)은 UI thread에서 매번 `runner.admission_error()`를 부르는데, 이것이 같은 `_condition`을 잡는다(`jobs/runner.py:84-87`). `snapshot()`, `submit()`, `_models_idle()`도 같다.
  - 기준 코드는 이 기록을 lock 밖에서 했다. G-P07의 주석("Cache release must not wait for an app admission lock while holding the runner condition")이 지키던 성질이다.
- **판단:**
  - 교착은 찾지 못했다. root mutex를 잡은 채 runner를 부르는 호출자가 없다(§3.3).
  - UI thread가 막히는 시간은 root mutex를 다른 곳이 잡은 시간(녹음 seal·삭제·복구 구간)과 SQLite busy 대기(`timeout=5.0`, `jobs/__init__.py:105`)로 제한된다.
  - 녹음 writer thread는 runner lock을 쓰지 않으므로 저장 경로는 막히지 않는다. 다만 정지·일시정지 버튼과 상태 표시가 그동안 멈출 수 있다.
- **권고:** stop()과의 경쟁을 닫는 데 DB I/O 전체를 lock으로 감쌀 필요는 없다. 방법은 둘이다.
  - worker가 lock 안에서 `settling` 표시만 하고 I/O는 lock 밖에서 한다. stop()은 그 표시가 풀릴 때까지 condition으로 기다린다.
  - 표시 조회(`admission_error`, `snapshot`)를 별도 lock으로 분리한다.

### G11BR-03 (S3) 종료 ACK 실패 뒤 자동 reap 재시도가 없음

- **재현:** `build/review-trees/g11b-probe/probe_lazy_reap.py`. 제품 AIService·ResourceScheduler·runner·JobStore·Library를 쓰고, owned worker factory만 fake다.
  - 첫 close에서 ACK가 실패한다. 그 뒤 worker가 스스로 끝난다(`is_live()` False).
  - 관측:

    ```text
    job SUCCEEDED reader active True
    held True closes 1
    2s after the worker exited: reader active True held True runner active ('…',)
    deletion: ACTIVE_READER_OR_WRITER
    after an explicit reap_held(): reader active False held ()
    deletion retry: … 'active_reader_or_writer': False, 'reason': 'RETRY_REQUIRED'
    ```

- **근거:**
  - reap 재시도는 두 곳뿐이다.
    - 다음 lease grant(`models/resources.py:974-978`, `_try_ack`)
    - `DesktopAI.release_gpu_runtime()`(`ui/ai_bridge.py:1342`)
  - tick·삭제 화면·모델 패널에는 재시도가 없다.
  - `snapshot()["active"]`에 held가 포함된다(`jobs/runner.py:114`). 그래서 `_models_idle()`(`ui/main.py:1076-1083`)도 그동안 False다.
- **기대:** 계약 §5.1의 원칙은 "실제 종료 ACK까지 보유"다. worker가 실제로 끝난 뒤에는 사용자가 무관한 작업을 하지 않아도 reader·slot이 풀려야 한다. 정확한 시점은 tick이나 삭제 재시도의 다음 확인이다.
- **판단:**
  - 보수적인 방향(살아 있다고 증명되지 않으면 기다림)이라 데이터 위험은 없다.
  - 다만 사용자가 세션 삭제를 끝내려면 무관한 로컬 AI 작업을 시작하거나 앱을 다시 시작해야 한다는 사실을 알 수 없다. 작성자 판단 (3)의 "SUCCEEDED + lease 잔류"가 원인이 사라진 뒤에도 남는 것이다.
  - 다음 grant에서 재시도하는 유일한 자동 경로는 검토자 N03(재시도 제거)이 934 PASS로 살아남았다. 시험이 없다.
- **권고:** tick에서 lock 없는 `child_live()`로 종료를 확인하고, 끝났으면 background Task로 `reap_held()`를 부른다. close는 최대 약 2.2초 걸리므로 UI thread에서 부르지 않는다. 그리고 "worker 종료 뒤 다음 grant가 reap하고 진행" 행을 추가한다.

### G11BR-04 (S3) UNKNOWN + worker 미종료에서 reader 해제

- **재현:** `build/review-trees/g11b-probe/probe_unknown_reader.py`. 작성자 시험 `test_unknown_outcome_survives_a_held_worker`와 같은 `tests.resource_fakes.Factory`를 쓰고, 그 시험이 보지 않는 reader·삭제 사실을 더해 확인했다.
  - 관측:

    ```text
    known local error: job BLOCKED/RESOURCE/INFERENCE_ACK_PENDING, worker live True, held True, reader active True, deletion ACTIVE_READER_OR_WRITER
    unknown outcome: job BLOCKED/REMOTE_UNKNOWN/REMOTE_OUTCOME_UNKNOWN, worker live True, held True, reader active False, deletion None
    ```

    `deletion None`은 삭제가 막히지 않고 진행됐다는 뜻이다.
- **근거:** `models/resources.py:1029-1037`. reap이 실패해도 원래 실패가 `outcome_known=False`이면 원래 예외를 그대로 올린다(UNKNOWN 보존, M23). 이 예외에는 `reader_retained`가 붙지 않으므로 runner가 reader를 끝낸다(`jobs/runner.py:268-276`).
- **기대:** 논리 UNKNOWN과 물리 종료는 별개다(§7.2). UNKNOWN을 보존하면서 reader도 유지해야 한다. 예를 들어 원래 예외에 `reader_retained=True`를 붙여 다시 올린다.
- **판단:** 지금의 owned 제품 worker(`LocalSTTProcess`, `LocalDiarizationProcess`)는 `outcome_known=False`를 만들지 않는다. local 결과는 모두 known이다. 따라서 사용자 도달 경로는 0이다. owned backend가 UNKNOWN을 낼 수 있게 되면 이 구멍은 S2가 된다.

### G11BR-05 (S3) Job별 worker 재기동 지연 미측정

- **측정:** `build/review-trees/g11b-probe/probe_cold_start.py`. 모델·GPU를 쓰지 않는 하한이다.
  - CPU `LocalSTTProcess`를 빈 폴더로 띄우고 `load()`를 부른다. `MODEL_MISSING`까지 **0.19~0.21초**(spawn + recoryn import), close는 0.01초다.
  - 새 interpreter에서 `import faster_whisper`만 하면 **1.93초(첫 실행)·0.36초(캐시 후)**다.
  - 실제 모델 로드 시간은 재지 않았다(금지 범위).
- **근거:**
  - `ui/ai_bridge.py`의 `OwnedSTT.open`은 lease마다 `LocalSTTProcess`를 새로 만든다. warm worker는 없다.
  - live STT는 chunk 묶음이 바뀔 때마다 새 provisional Job을 만든다. 그러므로 갱신마다 spawn + import + 모델 로드가 반복된다.
  - fallback·GPU_ONLY에서는 갱신마다 nvidia-smi 관측도 두 번 한다(준비와 lease). CUDA count child는 설정별로 cache된다.
- **판단:** 계약 §5.1(C00 승인)이 정한 선택이며, 작성자도 "지연 미측정"으로 공개했다. 출시 전 게이트로 실제 모델(small·large-v3, CPU·GPU)의 live 갱신 지연을 재고 허용 기준을 정할 것을 권고한다. 결함 판정은 그 측정 뒤로 미룬다.

### G11BR-06 (S3) 시험 공백

검토자 변이 19개 중 4개가 살아남았다(§5). 목록은 다음과 같다. 모두 제품 코드에 다른 방어가 있어 현재 사용자 영향은 없다.

| 변이 | 위치 | 의미 |
| --- | --- | --- |
| N03 보유 slot에서 다음 grant가 ACK를 다시 시도하지 않음 | `models/resources.py:978` | G11BR-03의 유일한 자동 재시도 경로가 시험되지 않는다 |
| N07 CPU의 실제 `device_index` 사실 무시 | `models/resources.py:625` | T18은 CUDA index만 본다. CPU index 불일치 행이 없다 |
| N11 close 성공 뒤의 `child_live()` 확인 제거 | `models/resources.py:752-754` | 제품 worker 둘은 close가 살아 있으면 예외를 낸다. 그래서 이중 방어 중 하나가 빠져도 통과한다. "Python 반환만으로 종료를 추정하지 않음"(§5.1)을 이 확인 단독으로 보는 행이 없다 |
| N12 held lease를 `snapshot()["active"]`에서 뺌 | `jobs/runner.py:114` | `release_gpu_runtime`의 `reap_held()`가 대신 거부하므로 runtime 제거는 막힌다. 그러나 `_models_idle()`(모델 관리)은 held 중에도 idle로 보이게 된다. §6 "UI idle 판정에 active/held lease 포함"을 직접 보는 행이 없다 |

R12(envelope `2**63` 경계)는 이번 tree에서 검출됐다. G11R-03에서 요청한 DTO 행이 들어왔다.

## 5. 검토자 변이

`build/review-trees/g11b-probe/mutate.py`를 썼다. 변이마다 새 사본(pyproject·src·tests)에 하나만 적용했다. 각 사본에서 `import recoryn` 위치를 확인했다(20/20 사본 안). 대상 node는 신규 4파일 + `tests/ui/test_gpu_runtime_ui.py` + `tests/unit/test_runner.py`다. 검출은 모두 assertion 실패였고, import·수집 오류와 ERROR는 0이다.

| ID | 변이 | 결과 |
| --- | --- | --- |
| R00 | 정상본 | 934 PASS, 26.90초 |
| R03 | 요약 task의 dispatch 재검사 제거 | **KILLED** 1(`test_dispatch_recheck_guards_summary_and_diarization`) |
| R04 | bridge 화자의 `capture_diarization` 제거 | **KILLED** 1(`test_aux_diarize_submit_admits_and_captures`) |
| R05 | bridge 화자의 `admit_diarization` 제거 | **KILLED** 1(같은 node) |
| R11 | envelope 중복 key 허용 | **KILLED** 1(AUX-DTO-duplicate-key) |
| R12 | envelope 상한 `<`→`<=` | **KILLED** 1(AUX-DTO-i64-bound) |
| N01 | 공정 turn `>=`→`>` | **KILLED** 2(Q, 진행 trace) |
| N02 | stop()이 settle된 작업도 취소 | **KILLED** 2(AUX-STOP) |
| N03 | 보유 slot에서 다음 grant의 ACK 재시도 제거 | SURVIVED |
| N04 | AUTO가 여유가 가장 작은 GPU를 고름 | **KILLED** 6(G-061…) |
| N05 | MIG를 검증으로 허용 | **KILLED** 1(inventory join) |
| N06 | ordinal을 host index 순서로 | **KILLED** 21(inventory, G) |
| N07 | CPU `device_index` 사실 무시 | SURVIVED |
| N08 | ACK 뒤 Job local reader를 끝내지 않음 | **KILLED** 11(AUX-HELD-NEXT, UB-07…) |
| N09 | CPU_ONLY도 GPU 관측 | **KILLED** 1(T13) |
| N10 | TTL 정확 만료를 허용 | **KILLED** 1(T11) |
| N11 | close 성공 뒤 `child_live()` 확인 제거 | SURVIVED |
| N12 | held lease를 `snapshot()["active"]`에서 제외 | SURVIVED |
| N13 | lease의 의미 키 장치 고정 제거 | **KILLED** 1(T23) |
| N14 | 등록 identity 대조 제거(G11R-01) | **KILLED** 3(AUX-ID) |

합계: **15 KILLED / 4 SURVIVED**(N03·N07·N11·N12, G11BR-06).

## 6. 미검증·한계

- 실제 GPU·nvidia-smi·CUDA count child·`GlobalMemoryStatusEx`·모델 로드·다중 GPU·MIG·remapping은 실행하지 않았다. 모두 작성자 시험의 fake와 검토자 반례로만 판단했다.
- 작성자 mutation 24개는 재실행하지 않았다. 검토자 변이 19개로 다른 위치를 시험했다.
- offscreen Qt에서는 키보드 초점과 낭독을 판정하지 않았다.
- 작업 트리의 G-P08 변경과의 의미 충돌은 판정하지 않았다. P11b는 `status.py`·`storage/library.py`를 쓰지 않는다.
- **관찰(재현 안 함):** bridge의 GPU runtime 실패 추적(`observe_gpu_failure`)은 마지막 factory(`_local_factory.last`)만 본다. 로컬 STT Job 두 개가 함께 대기하다가 앞 Job이 runtime 실패를 내면, 뒤 submit이 factory와 `_local_generation`을 이미 바꿨을 수 있다. 그러면 그 실패가 이번 실행의 runtime 제외로 기록되지 않는다(이전에는 warm worker 하나여서 이 경우가 없었다). 다음 실패에서 다시 기록되므로 영향은 반복 실패 1회 정도로 보인다.
- 재시작 고아 child, 장시간 메모리, 실제 OOM 경로는 외부 게이트다.

## 7. 증거 파일

모두 `build/review-trees/g11b-probe/` 아래 파일이며, 해시는 LF 기준 SHA-256이다.

| 파일 | SHA-256 |
| --- | --- |
| `run_full.sh` | `d2c4f2c5f3493eafb7f0a3eddc2ea5f0d19cf1c48d45af31f60d2a114a5bd201` |
| `full.log` | `5a3fb253d4f25386a1596e7c3fab0add907fbacfbb0f0d1e670a6f3e9967de96` |
| `coverage-check.txt` | `dba2801a1c3adb1b4041aa9c8ed8114bb8e55ff972cb8d5ecf071734414b81b7` |
| `../g11b/coverage.json` | `2c3eb5a774150a7d85efaddc2c982eb7503e851f32ef3361369133c0d4c38e31` |
| `probe_order.py` | `4a248198ccb6f4ffba1bf71fc0f7364685f33207889299d2d81f029c8f11a7ed` |
| `probe_order_count.py` | `ca5520ebd2ccea589b491575680e6d4f31e25318dc33fc95b69f6354882c6af4` |
| `probe_runner_lock.py` | `1d6b19512e72a5ce31e878b3ced6ba2111bcd68efcba194c3142d202ed94070f` |
| `probe_lazy_reap.py` | `9dba91b86577a17006a0ce46a9254e5941fe810a83e3036f7af06bed06c59c48` |
| `probe_unknown_reader.py` | `6b92ad433d1d1d151584ef5cd81301e098ca49cde4859b42d888286ec20f07a1` |
| `probe_cold_start.py` | `061c888298123961b18be57e5d1ad17f6c55d135c6f78eb991e2567d25395d7d` |
| `recheck_mislabel.py` | `93132931e69f2d611d33c1e6d1748a98f26793ee95e3a502fc457494f072e2e9` |
| `recheck_stop_race.py` | `a9aaf5bc13ddacc95b7bfcf94972d51ba46e4b8f9b31b0317d56b04dda78a688` |
| `mutate.py` | `0b2477685211dcba86a85a84f5942b300b7a6d7676ee86b064ed6da6ea0886f4` |
| `mutants/summary.txt` | `946a56ff34d5e0bb4f899cc7247c8503f096c3f348a40708a24f856b4bba0d92` |
