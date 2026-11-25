# G11 / G-P11c 자원 정책 후속 수정 독립 검토

2026-11-25, 검토자 Claude(C00 지정 G-P11c 독립 검토 하위 에이전트). 작성자는 w5:p7 Claude다. 검토자는 이 단위의 코드·시험·계약 문서를 작성하지 않았고, 이 문서 외에는 저장소 파일을 고치지 않았다. 대상 발견 G11BR-01~06은 이 검토자가 G-P11b 검토(`docs/reviews/g11b-resource-policy-review.md`)에서, G11R-04는 G-P11a 검토에서 낸 것이다.

**판정: 대상 발견 7건은 모두 RECHECKED다**(G11BR-01·02·03·04·06, G11R-04, 그리고 G11R-02 유지). G11BR-05는 범위 밖이다. **새 OPEN은 3건이며 모두 S3다**(S0 0 / S1 0 / S2 0 / S3 3). S0·S1이 없으므로 이 기준만으로는 push를 막지 않는다. 수용과 통합은 C00이 결정한다.

- **G11CR-01:** identity와 지정 장치 부재의 순서는 UUID·bus id 결함에서는 작성자 판단이 옳다. 반면 remapping·MIG·CUDA 수 불일치에서는 계약 문장이 더 정확하다. 문서 두 절의 기술도 서로 어긋난다. 계약 정정이 필요하다.
- **G11CR-02:** reaper가 `AIService.close()` 뒤에도 남는다. worker가 끝나면 닫힌 JobStore에 reader 종료를 시도하고, 그 실패는 소리 없이 삼켜진다(다음 시작의 복구가 정리).
- **G11CR-03:** 새 경쟁 방어 두 곳과 계약 경계 하나를 시험이 보지 않는다.
  - stop의 "같은 항목" 재확인(Q01). 지우면 BLOCKED→CANCELLED가 재발하는 것을 반례로 확인했다.
  - stop의 `settling` 대기(Q06). 지우면 BACKOFF Job이 stop 뒤에도 BACKOFF로 남는 것을 반례로 확인했다.
  - UNKNOWN GPU에 RAM stale 비적용(Q03).
  - 이 밖에 reaper의 생존 사전 확인(Q05)도 관측되지 않는다.

새 경쟁(이중 기록·교착·BLOCKED→CANCELLED 회귀)은 제품 코드에서 찾지 못했다(§4.1). 위 두 반례도 제품 tree에서는 올바른 결과를 낸다.

## 1. 입력 고정과 범위 판정

- 검토 대상은 tree **`f8bae24e31cd1983e1d60e779e96e07a63af8e8b`**다(`git cat-file -t` = tree). 기준은 HEAD **8126c1f**(G-P08·GS-P02 포함)다.
- `git diff 8126c1f f8bae24e --stat`: **7파일, 938 insertions / 36 deletions**다.
  - source 3: `jobs/runner.py`, `models/resources.py`, `app/status.py`
  - 시험 3: 기존 `test_resource_policy.py`, 신규 `tests/unit/test_resource_followup.py`·`tests/integration/test_resource_followup.py`
  - 문서 1
  - 계약 §G-P11c "쓰기 범위" 안이며, `app/inference.py`·bridge·`jobs/__init__.py`는 바뀌지 않았다.
- 계약 문서 LF SHA-256은 `1f02ae13f4293e3d3aac45c3681a2680870825a8a3a04d27ca9adf16b1610985`로 배정값과 같다. 앞 내용(`655e606e…`) 뒤에 §G-P11c 범위·결과 두 절이 추가됐다.
- 실행 위치는 다음과 같다. 작업 트리(G-P12 수정·G-P17a 혼재)는 쓰지 않았다.
  - 판정: `git archive f8bae24e | tar -x -C build/review-trees/g11c`
  - 변이: `build/review-trees/g11c-probe/mutants-work/m-*`(변이마다 사본, 실행 뒤 삭제)
  - 반례·로그: `build/review-trees/g11c-probe/*`
- 모든 실행에 `PYTHONPATH=<사본>\src`를 고정했다. 반례는 import 직후 경로를 assert한다. 전체 회귀 직전 import 위치를 기록했다(`full-import.txt`). 변이 harness는 사본마다 import 위치를 확인했다.
- 실제 GPU·nvidia-smi·CUDA probe child·모델·네트워크·유료 호출, Git 쓰기, 설치, Credential Manager, 하위 에이전트, herdr는 사용하지 않았다.

## 2. 직접 실행한 명령과 결과

공통 조건: cwd는 사본, `.venv\Scripts\python.exe`(Python 3.13.1), `QT_QPA_PLATFORM=offscreen`, `HF_HUB_OFFLINE=1`, `-p no:cacheprovider`, 실행별 OS TEMP의 새 `--basetemp`.

| # | 명령 | 결과 |
| --- | --- | --- |
| R1 | `pytest -q -p no:cacheprovider -W error::ResourceWarning --basetemp=%TEMP%\g11c-review-full-bt --cov=recoryn --cov-branch --cov-report=json:coverage.json --cov-fail-under=85 -rfEs` (`g11c-probe/run_full.sh`, CI core와 같은 flag) | **22887 passed, failure·error·skip 0, 1668.45초(27:48), exit 0.** 총 coverage 92.34% |
| R1b | `python scripts/check_coverage.py coverage.json` | domain 99.18/97.89, capture 99.85/98.57, jobs 99.19/95.61, storage 95.95/91.41, security 98.11/94.43, content 99.59/98.75, **all 93.73/88.28**(line/branch %), 7묶음 모두 PASS |
| R2 | `ruff check src tests scripts packaging` / `ruff format --check …` / `MYPYPATH=src mypy src/recoryn scripts packaging` | All checks passed / 195 files already formatted / **91 source files no issues** |
| R3 | 변경 모듈 coverage(R1 JSON) | `jobs/runner.py` line 265/270·branch 83/92, `models/resources.py` 532/578·161/198, `app/status.py` 124/128·71/76 |
| R4 | 대상 9파일(변이 harness 정상본) | **1173 passed, 56.59초** |
| R5 | G-P11b 반례 재실행 5개 + 새 반례 4개(§3·§4·§6) | §3 RECHECKED 근거, G11CR-01~03 |
| R6 | `mutate.py`(검토자 변이 12개 + 정상본) | **8 KILLED / 4 SURVIVED**(§5) |

- 작성자 보고(22,539 PASS)는 기준 31bc88b의 사본에서 낸 수다. 이 tree는 HEAD 8126c1f(GS-P02 포함)라 node 수가 더 많다.
- 실행 시간이 긴 것은 같은 시각에 변이·반례를 함께 돌렸기 때문으로 보인다.

## 3. 재확인(RECHECK)

| ID | 판정 | 직접 근거 |
| --- | --- | --- |
| G11BR-01 | **RECHECKED**(계약 문장 정정 필요, G11CR-01) | `probe_order.py` 6행이 모두 SAME이다(GPU UNKNOWN+RAM UNKNOWN → CPU_PROBE_UNKNOWN, VRAM 부족+RAM UNKNOWN → CPU_PROBE_UNKNOWN, identity 미검증+RAM UNKNOWN → CPU_PROBE_UNKNOWN, GPU UNKNOWN+RAM stale → SNAPSHOT_STALE). `probe_order_count.py`는 이 검토자가 계약 순서로 쓴 독립 P oracle과 작성자 새 oracle을 비교하며, 차이는 **0/31,104행**이다. TTL 기본값은 2초다(`models/resources.py:429`). 남은 것은 identity와 지정 장치 부재의 순서다(G11CR-01) |
| G11BR-02 | **RECHECKED** | `probe_runner_lock.py`를 그대로 다시 돌렸다. root mutex를 1.5초 잡는 동안 `admission_error()` **0.000초**다(G-P11b 1.518초, 기준 b925520 0.000초). runner 파일의 `with self._condition:` 블록 안에서 `self.jobs.*` 호출은 `start()`의 `_ensure_open()` 하나뿐이다(awk 확인) |
| G11R-02 유지 | **RECHECKED** | `recheck_stop_race.py`(G-P11a 반례 원본). RESOURCE_POLICY_UNVERIFIED·COST_CAP_EXCEEDED·REMOTE_UNKNOWN 모두 BLOCKED 유지, `cancel_requested` False다 |
| G11BR-03 | **RECHECKED** | `probe_lazy_reap.py`. ACK 실패 뒤 worker가 스스로 끝나면 2초 안에 reader가 풀리고(`False`), slot이 해제되고, runner active가 `()`가 되며, 삭제가 진행된다(`None`). 이전에는 `ACTIVE_READER_OR_WRITER`였다 |
| G11BR-04 | **RECHECKED** | `probe_unknown_reader.py`. UNKNOWN + worker 생존에서 `reader active True`, 삭제 `ACTIVE_READER_OR_WRITER`다(이전 False·None). job은 BLOCKED/REMOTE_UNKNOWN을 유지한다 |
| G11BR-05 | 범위 밖(실장비 게이트) | — |
| G11BR-06 | **RECHECKED** | G-P11b에서 살아남은 N03·N07·N11·N12와 N02를 같은 패턴으로 다시 돌렸다. 5개 모두 KILLED(§5). 새 R·F 행이 목표를 직접 맞힌다 |
| G11R-04 | **RECHECKED** | 사본에서 `ai_status(preparation=NormalizedFailure(code))`를 부르면 POLICY_UNVERIFIED·GPU_UNSUPPORTED → `execution_policy`, CAPABILITY_UNSUPPORTED → `model`이다. bridge override는 남아 있고, 결과가 같아 표시 차이는 없다(후속 제거는 G-P12 뒤) |

## 4. 새 경쟁·수명·판단 요청

### 4.1 결과 기록을 lock 밖으로 옮긴 뒤의 경쟁

`jobs/runner.py:185-230`(stop), `262-284`(`_claim_settle`·`_end_settle`·`_ack_stop`), `290-375`(`_execute`)을 읽고 경우를 나눴다.

| 경우 | 동작 | 판정 |
| --- | --- | --- |
| worker가 먼저 `settling` | stop은 `settling`이 끝날 때까지 condition으로 기다린다(`deadline`까지). 그 뒤 `settled`면 취소하지 않는다 | BLOCKED·FAILED·SUCCEEDED 보존. S "기록 중·기록 뒤" 10행 |
| stop이 먼저 `cancelling` | stop은 lock 밖에서 `jobs.cancel` → `item.cancel.set()`. worker는 `_claim_settle` False → `_ack_stop`(cancel 대기 후 `_ack_cancelled(known)`) | known은 CANCELLED, UNKNOWN은 BLOCKED/REMOTE_UNKNOWN. S "기록 전" 5행 |
| 이중 기록 | 단계 표시가 상호 배제한다(`settling`이면 stop은 owned=False, `cancelling`이면 worker는 결과를 쓰지 않음) | 없음 |
| stop이 목록을 잡은 뒤 worker가 끝내고 active에서 빠짐 | `self._active.get(id) is item` 재확인 | 작성자가 닫은 기존 창. 검토자 Q01 결과는 §5 |
| BACKOFF 대기 중 stop | `_end_settle(settled=False)`로 단계가 비어 있으므로 stop이 owned → CANCELLED, worker는 `cancel.wait`에서 깨어나 종료 | 의도대로(이전과 같음) |
| settle이 stop의 deadline보다 오래 걸림 | stop은 deadline에 대기를 끝내고 owned=False(`settling`)이므로 취소하지 않는다 → join 0 → `RUNNER_STOP_TIMEOUT` | 결과 보존. 종료 timeout은 기존 의미와 같다 |
| `_ack_stop`의 10초 대기보다 stop의 `jobs.cancel`이 오래 걸림 | SQLite busy timeout이 5초(`jobs/__init__.py:105`)라 cancel은 5초 안에 commit하거나 예외를 낸다. 예외면 job은 RUNNING이고 `_ack_cancelled`는 no-op다(`jobs/__init__.py:746-751`). 다음 시작의 `recover_abandoned`가 처리한다 | 결과 위조 없음 |
| 교착 | lock 안에서 DB·root mutex·scheduler를 기다리지 않는다(`snapshot`의 `held()`는 메모리만). stop의 대기는 `condition.wait`로 lock을 풀고, worker의 `_end_settle`이 `notify_all`한다 | 찾지 못했다 |

- **관찰(기존 동작, 이번 변경과 무관):** worker의 `jobs.get`과 `jobs.fail` 사이에 사용자 `runner.cancel()`이 끼어들 수 있다. 그러면 `fail`이 fence 불일치로 StateConflict를 낸다. 이 예외는 바깥 `except (StateConflict, KeyError)`로 가고, CANCEL_REQUESTED Job이 이 실행에서 취소 ACK를 받지 못한다. 창은 두 호출 사이뿐이고, 다음 시작의 복구가 정리한다. b925520 이전부터 같은 순서다.

### 4.2 reaper 수명

`probe_reaper_lifetime.py`로 확인했다. AIService 두 개에 각각 ACK가 실패한 worker를 두었다.

```text
held per service: [True, True]
reaper threads while held: 2
reaper threads after AIService.close() with live workers: 2
after worker 0 exited: held0 () held1 True reaper threads 1
after worker 1 exited: reaper threads 0
thread exceptions: []
```

- scheduler마다 한 개이고, slot은 하나다. 보유가 끝나면 스스로 끝난다(`_reaper = None`을 lock 안에서 결정하고, `_watch_held`가 같은 lock에서 확인하므로 놓치는 재시작이 없다).
- 살아 있는 worker가 남은 채로 `AIService.close()`하면 reaper는 daemon으로 계속 0.25초마다 `child_live()`를 본다. worker가 끝나면 `on_ack`가 이미 닫힌 JobStore에 `reader_finished`를 시도한다. 그 예외는 `_released`가 삼킨다. DB의 reader는 다음 시작의 `recover_abandoned(coordinator_exclusive=True)`가 정리한다. 프로세스 종료 때 daemon으로 사라진다. → G11CR-02(S3).
- 주기 확인은 lock 없이 `child_live()`만 본다. 살아 있는 worker는 해제하지 않는다(작성자 C06, 검토자 Q05). close/terminate를 다시 시도하는 일은 다음 grant의 `_try_ack`(N03)가 맡는다.

### 4.3 판단 요청: identity를 지정 장치 부재보다 먼저

`probe_identity_order.py`(제품 `join_identity`에 행을 주입, UNKNOWN profile, GPU_ONLY):

```text
verified, pinned GPU-Z absent: … -> RESOURCE_GPU_UNAVAILABLE
CUDA_VISIBLE_DEVICES set (host rows complete), pinned GPU-Z absent: verified=False reason=CUDA_VISIBLE_DEVICES devices=2 -> RESOURCE_GPU_IDENTITY_UNVERIFIED
duplicate UUID, pinned GPU-Z: verified=False reason=UUID devices=0 -> RESOURCE_GPU_IDENTITY_UNVERIFIED
observed empty list, no remap, AUTO: verified=True … -> RESOURCE_GPU_UNAVAILABLE
observed empty list, CUDA_VISIBLE_DEVICES set, AUTO: verified=False … -> RESOURCE_GPU_IDENTITY_UNVERIFIED
```

- **UUID·bus id 결함(`reason` UUID/BUS_ID):** 작성자 판단이 옳다. `join_identity`는 장치 목록을 비워 보낸다. 지정 UUID가 "없다"는 판단이 성립하지 않으므로 IDENTITY_UNVERIFIED가 정확하다.
- **remapping·MIG·CUDA 수 불일치:** host 목록(nvidia-smi)은 `CUDA_VISIBLE_DEVICES`와 무관하게 완전하다. 그래서 지정 UUID의 부재나 빈 목록은 알 수 있다. 계약 문장대로 GPU_UNAVAILABLE이 더 정확하고 행동 가능한 안내다.
- **영향:** 두 코드 모두 RESOURCE·GPU 거부이고 fallback에서는 CPU로 같게 간다. 지정 UUID는 지금 UI에서 정할 수 없다. 그러므로 제품에서 차이가 나는 것은 "nvidia-smi는 있으나 GPU 0개 + `CUDA_VISIBLE_DEVICES` 설정"뿐이다.
- **권고:** 구현 순서를 수용하고 계약 §4.3 문장을 정정한다. 정정할 내용은 "identity가 UUID·bus id 결함으로 미검증이면 장치 부재보다 먼저 IDENTITY_UNVERIFIED"다. remapping·MIG·count 사유에서 장치 부재를 먼저 볼지도 함께 정하면 된다. 정정 전에는 결과 절의 "계약 정정 여부는 C00 결정"과 범위 절 결정표의 "계약 정정은 요청하지 않는다"가 서로 어긋난다 → G11CR-01.

### 4.4 범위 밖 관찰 2건의 심각도 의견

1. **root mutex가 `fail`만 막고 `complete`·`_ack_cancelled`는 막지 않음(`jobs/__init__.py`).** 결함으로 보지 않는다. 의견은 S3 미만이며 문서화만 권고한다.
   - `complete`는 runner가 task 반환 뒤 부른다. 전사·요약·화자 결과는 그보다 앞서 ContentStore가 fence와 세션 확인 아래 게시하면서 Job을 이미 끝낸다. 그래서 runner의 `complete`는 대부분 멱등 확인이다(`jobs/__init__.py:610-624`).
   - `_ack_cancelled`는 CANCEL_REQUESTED·fence+1일 때만 쓰며 내용을 쓰지 않는다.
   - `fail`이 authority를 쓰는 이유는 삭제 중에 retry/FAILED를 갈라야 해서이며(G-P07), 나머지 둘에는 그 판단이 없다.
2. **claim 직후 `reader_started` 전 사용자 취소가 task 없이 취소 ACK로 끝남.** 정상 동작이다. 결함으로 보지 않는다.
   - 취소가 읽기 시작보다 앞섰으므로 원본을 읽지 않고 끝나는 것이 맞다.
   - attempt 수가 하나 늘지만, 취소된 Job은 resume 대상이 아니다.

## 5. 검토자 변이

`build/review-trees/g11c-probe/mutate.py`를 썼다. 변이마다 새 사본(pyproject·src·tests)을 만들었고, import 위치를 확인했다(13/13 사본 안). 대상은 9파일이다.

- 신규 2파일
- G11 4파일(`test_resource_policy` unit·property·integration·ui)
- `test_gpu_runtime_ui`, `test_runner`, `test_blocked_reasons`

검출은 모두 assertion 실패였고, import·수집 오류와 ERROR는 0이다.

| ID | 변이 | 결과 |
| --- | --- | --- |
| R00 | 정상본 | 1173 PASS, 56.59초 |
| N02 | stop이 settle된 작업도 취소(`not in self._settled` 제거) | **KILLED** 6(AUX-STOP, S) |
| N03 | 보유 slot에서 다음 grant의 ACK 재시도 제거 | **KILLED** 6(G11C-R-04…) |
| N07 | CPU `device_index` 사실 무시 | **KILLED** 2(G11C-F-3…) |
| N11 | close 성공 뒤 `child_live()` 확인 제거 | **KILLED** 12(G11C-R-13…) |
| N12 | held를 `snapshot()["active"]`에서 제외 | **KILLED** 21(G11C-R-02…) |
| Q01 | stop의 "같은 항목이 아직 active" 재확인 제거 | **SURVIVED** |
| Q02 | UNKNOWN 분기에서 reaper를 띄우지 않음 | **KILLED** 2(G11C-R-03…) |
| Q03 | known RAM stale 검사를 UNKNOWN GPU에도 적용 | **SURVIVED** |
| Q04 | TTL 기본값을 5초로 되돌림 | **KILLED** 4(G11C-TTL-3…) |
| Q05 | reaper가 생존 확인 없이 매 주기 `_try_ack` | **SURVIVED** |
| Q06 | stop이 `settling`을 기다리지 않음 | **SURVIVED** |
| Q07 | 공용 status의 정책 코드 행동 연결 제거 | **KILLED** 4(G11C-A-01…) |

합계: **8 KILLED / 4 SURVIVED**(G11BR-06 재확인 5개는 모두 KILLED). 생존 4개는 G11CR-03에서 다룬다.

- Q01·Q06은 결정적 반례로 생존의 의미를 확인했다.
  - 제품 tree는 올바르다.
  - 변이 사본(`q01-copy`, `q06-copy`. src만 복사해 한 줄만 바꿈)에서는 결과가 틀어지는데도 시험이 통과한다.
- 작성자의 C03("stop이 기록 중 작업을 기다리지 않음")은 검출됐다고 보고됐다. 그러나 이 검토자의 Q06(대기 loop만 제거)은 살아남았다.
  - 대기 loop를 지워도 `owned` 조건이 `settling`을 보고 취소를 막는다. 이어서 thread join이 worker를 기다린다. 그래서 S의 다섯 결과(SUCCEEDED·BLOCKED×2·FAILED·UNKNOWN)에서는 차이가 나지 않는다.
  - 차이는 기록이 settle되지 않고 끝나는 경우(BACKOFF)에만 생긴다.

## 6. 발견 사항

| ID | 심각도 | 상태 | 요약 |
| --- | --- | --- | --- |
| G11CR-01 | S3 | OPEN | identity와 지정 장치 부재의 순서가 계약 §4.3 문장과 다르고, 문서 두 절의 기술이 어긋난다. 계약 정정 필요 |
| G11CR-02 | S3 | OPEN | reaper가 `AIService.close()` 뒤에도 남아, 닫힌 JobStore에 reader 종료를 시도하고 실패를 삼킨다 |
| G11CR-03 | S3 | OPEN | 새 방어 두 곳(stop의 같은 항목 재확인, `settling` 대기)과 UNKNOWN GPU의 RAM stale 비적용, reaper 생존 사전 확인을 시험이 보지 않는다 |

### G11CR-01 (S3) identity와 장치 부재의 순서

- **재현:** `build/review-trees/g11c-probe/probe_identity_order.py`. 관측은 §4.3에 적었다.
- **근거:**
  - 구현: `models/resources.py:525-567`(`_gpu_plan`). 시각 → known RAM 관측 → GPU 관측 → identity → 장치 부재 → RAM 부족 → VRAM 부족 순이다.
  - 계약 §4.3 103행은 "GPU 관측 UNKNOWN/UNAVAILABLE·장치 부재 → GPU identity 대응" 순이다.
  - 같은 문서에서 §G-P11c 범위 절(749행)은 "계약 §4.3 문장 순서로 맞춘다 … 계약 정정은 요청하지 않는다"고 쓴다. 결과 절(818행 이하)은 "identity를 먼저 … 계약 정정 여부는 C00 결정"이라고 쓴다.
- **기대:** 구현·oracle·계약 문장이 하나의 규칙을 가리켜야 한다.
- **권고:** UUID·bus id 결함에서는 identity가 먼저라는 작성자 판단을 수용하고, 계약 §4.3에 정정 문장을 덧붙인다. remapping·MIG·CUDA 수 불일치에서는 host 목록이 완전하므로 장치 부재를 먼저 볼 수도 있다. 둘 중 하나를 정하면 된다. 현재 사용자 영향은 GPU_ONLY의 대표 코드뿐이다(지정 UUID는 UI에서 정할 수 없음).

### G11CR-02 (S3) reaper가 서비스 종료 뒤에도 남음

- **재현:** `build/review-trees/g11c-probe/probe_reaper_lifetime.py`. 관측은 §4.2에 적었다. `AIService.close()` 뒤에도 reaper 2개가 남고, worker가 끝날 때마다 하나씩 사라지며, thread 예외는 0이다.
- **근거:**
  - `models/resources.py:955-983`(`_watch_held`·`_reap_loop`)
  - `986-998`(`_released`가 `on_ack` 예외를 삼킴)
  - `app/ai.py:756-760`(`close()`는 runner만 멈추고 scheduler·reaper는 다루지 않음)
- **기대:** 서비스를 닫은 뒤에는 그 서비스의 JobStore에 쓰는 thread가 남지 않거나, 그 사실이 문서화되어야 한다.
- **판단:**
  - reaper는 daemon이고 프로세스 종료와 함께 사라진다.
  - 닫힌 JobStore에 대한 `reader_finished` 실패는 삼켜지고, DB의 reader는 다음 시작의 `recover_abandoned(coordinator_exclusive=True)`가 정리한다.
  - 데스크톱 앱은 `DesktopAI.close()` 뒤 종료하므로 사용자 영향은 없다.
  - 같은 프로세스에서 서비스를 다시 만드는 경로(시험·향후 재시작 UI)에서는 옛 reaper가 새 서비스와 같은 DB에 늦게 쓸 수 있다.
- **권고:** `ResourceScheduler.close()`를 두어 reaper를 멈추게 한다. 이때 slot은 해제하지 않는다. `AIService.close()`에서 이를 부르거나, 이 수명을 계약 결과 절에 적는다.

### G11CR-03 (S3) 시험이 보지 않는 새 방어와 경계

1. **stop의 "같은 항목이 아직 active" 재확인(`jobs/runner.py:216`, Q01 생존).**
   - 작성자가 이번에 닫았다고 보고한 기존 창이다.
   - `build/review-trees/g11c-probe/probe_stop_window.py`는 결정적이다. stop이 대기 중 Job의 cancel을 처리하는 동안 active Job이 BLOCKED로 끝나고 active에서 빠지게 한다.
   - 결과:
     - 제품 tree: `active job after stop: BLOCKED RESOURCE RESOURCE_EXHAUSTED`
     - Q01 사본: `CANCELLED RESOURCE RESOURCE_EXHAUSTED`. G11R-02가 재발한다.
   - 기존·신규 시험 1,173개가 Q01 사본에서 모두 통과한다.
2. **stop의 `settling` 대기(`jobs/runner.py:210`, Q06 생존).**
   - `build/review-trees/g11c-probe/probe_stop_backoff.py`. worker가 재시도 가능 실패(BACKOFF)를 기록하는 중에 stop이 온다.
   - 결과:
     - 제품 tree: `after stop: CANCELLED cancel_requested True`
     - Q06 사본: `BACKOFF cancel_requested False`. 앱 종료 뒤 durable Job이 재시도 대기로 남는다.
   - G11C-S의 결과 축에 BACKOFF가 없다.
3. **UNKNOWN GPU 요구량에 RAM stale을 적용하지 않음(`models/resources.py:544`, Q03 생존).** 계약 §4.3은 UNKNOWN 분기에서 RAM 기반 차단을 하지 않는다고 한다. TTL 6행은 known 장치만 다룬다. 운영 catalog가 비어 RAM을 관측하지 않으므로 현재 도달 경로는 없다.
4. **reaper의 생존 사전 확인(`models/resources.py:976`, Q05 생존).**
   - 이 확인을 지우면 reaper가 0.25초마다 살아 있는 worker의 `close()`를 부른다. 제품 `LocalSTTProcess.close`라면 매번 terminate와 최대 약 2.2초 join이 반복된다.
   - fake close는 곧바로 예외를 내므로 시험이 이 차이를 보지 못한다.
   - 해제는 여전히 일어나지 않으므로 결과는 안전하다.

- **기대:** 이번 단위가 추가하거나 정정한 방어는 각각 목표 assertion으로 검출돼야 한다(case-space·mutation 원칙).
- **권고:**
  - 1·2는 위 두 반례를 G11C-S 보조 행으로 옮긴다. 결과 축에 BACKOFF를, 시점 축에 "stop 목록 고정 뒤 worker 종료"를 추가한다.
  - 3은 TTL 또는 P 보조 행에 "UNKNOWN GPU + stale RAM → 허용"을 추가한다.
  - 4는 reaper 주기 동안 close 호출 수 0을 단언한다.

## 7. 미검증·한계

- reaper 주기와 실제 child 종료의 상호작용은 fake `is_live`로만 봤다. 실제 `LocalSTTProcess`·`LocalDiarizationProcess`의 지연 종료는 실행하지 않았다.
- 작성자 mutation 13개는 재실행하지 않았다. 검토자 변이 12개(G11BR-06 재확인 5 + 새 7)로 다른 위치를 시험했다.
- L의 "0.1초 안 응답"은 이 장치의 측정이며 부하 아래 SLA가 아니다.
- G-P12 검토 중인 bridge override 제거와 G-P12 변경(`app/ai.py`·`ui/ai_bridge.py`)과의 결합은 보지 않았다.
- G11BR-05(live STT 재기동 지연)는 실장비 게이트로 남는다.

## 8. 증거 파일

모두 `build/review-trees/g11c-probe/` 아래 파일이며, 해시는 LF 기준 SHA-256이다. 변이 사본(`mutants-work/`, `q01-copy/`, `q06-copy/`)은 실행 뒤 삭제했다.

| 파일 | SHA-256 |
| --- | --- |
| `run_full.sh` | `867001297b4a759f111a2cec06830d090abf15110b2fe284876b9f110c206c61` |
| `full-import.txt` | `5bfcadfe64b4d3359e53914a3ef2f5193235c63bd23723321587830aa580903c` |
| `full.log` | `2c88361f74dd83284a6edc777d00e3ce7b38193bb1a48349b2683a338eb8cb2e` |
| `coverage-check.txt` | `49225a9fa6300a388c00604314a482695ac79c7ecaf7e7e25082c0dbabf549ad` |
| `../g11c/coverage.json` | `1230fdb7c9537dc4902e0aace0bc48f6f0ad22273b2ebad2dbb44a51755afbb9` |
| `probe_order.py` | `d367f8a7da393c9abd9997920a07a0ad9797d29126a4f0cdd78b74ef97e9329c` |
| `probe_order_count.py` | `ecf4a9d781832b1012e902fea7e44abea9ff8b82785453cf7da6444984a3c66e` |
| `probe_runner_lock.py` | `70de8423a353d1e335f80c93d61d2c1b8e0255aac5541375f4015b77379d4f03` |
| `probe_lazy_reap.py` | `44ab0b52b44a2bc1e0d24f59a056135eb43046d33dd587ebe333af45384767e7` |
| `probe_unknown_reader.py` | `280df2bef49296d861e16f69cee1ccb4277d3c3cb1e9587808bb0f9fd9406cef` |
| `recheck_stop_race.py` | `a9aaf5bc13ddacc95b7bfcf94972d51ba46e4b8f9b31b0317d56b04dda78a688` |
| `probe_identity_order.py` | `fff665eae816b20854ffe451225a991f3dc1f6d2d934ae7f2db3ab98c65beb86` |
| `probe_reaper_lifetime.py` | `ff5e52e99385e734dfcab7f9e3a5bd1dac30f7df43103514fb3b69bbb7e4a790` |
| `probe_stop_window.py` | `db2e4d9d96b8622b9f687498150ad64bbc33f6852c738ee057143d1a45beabb1` |
| `probe_stop_backoff.py` | `2866bf027d5e7569dd4bc4e15f499c6c6cedda43706974e1c0fb482373f57675` |
| `mutate.py` | `af78ddf25944723911bb25ad4db83900a5182caebef6a307caf8786d714bc790` |
| `mutants/summary.txt` | `b1c766454c502692495bbfdb3222730aff23b343aeb563fff2809aa71a2e6912` |
