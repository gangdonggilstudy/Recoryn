# G07 / G-P07 BLOCKED 사유·시작 표시 독립 검토

2026-11-24, 검토자 Claude(C00 지정 G-P07 독립 검토 하위 에이전트). 작성자는 w5:p8 Codex다. 검토자는 이 단위의 코드·시험·계약 문서를 작성하지 않았고, 이 문서 외에는 저장소 파일을 고치지 않았다.

**판정: OPEN 9건 — S0 0 / S1 0 / S2 2 / S3 7.** S0·S1이 없으므로 이 기준만으로는 push를 막지 않는다. 다만 G07R-01은 녹음 저장 경로를 계약 범위 밖에서 바꿔 원본 PCM을 버린다. 수정 비용이 작으므로 push 전 수정을 권고한다. 수용과 통합은 C00이 결정한다.

다음 반례는 찾지 못했다.

- BLOCKED(CONSENT·AUTH·CAPABILITY·RESOURCE·BUDGET·ABANDONED)에서 새 준비 snapshot과 명시 `expected_job_id/version` 없이 전송이 다시 시작되는 경로
- `_admit`의 암묵 resume(M25 재현 검출)
- factory typed 오류의 `outcome_known=False` 승격(M23 재현 검출)
- REMOTE_UNKNOWN 재개
- DB-only·journal-only·DB+journal·완료 tombstone·세션 소실·이력 확인 불가에서 claim·block_pending·resume·reader 시작이 허용되는 경로(M24 재현 검출)
- 수락된 frame 없이 REC를 표시하는 경로
- root mutex → Job 잠금 순서의 역전

열린 S2는 두 건이다.

1. **G07R-01:** `DesktopRecorder._submit`이 정지·일시정지 요청 직후(STOPPING)부터 PCM을 거부한다. 두 번째 트랙은 첫 source를 정지하는 동안 들어온 블록을 모두 잃는다. 이 손실은 RecordingService 건강 통계에도 남지 않는다.
2. **G07R-02:** gateway 경계에서 `outcome_known` 속성이 없는 오류의 기본값이 '미상'에서 '확인됨'으로 바뀌었다. 지금 제품 Gateway는 늘 속성을 붙이므로 현재 도달 경로는 없다.

## 1. 입력 고정과 범위 판정

- 검토 대상은 tree **`898fcc53e56602997046eed5349f83a3a7eb4192`**다(`git cat-file -t` = tree). 기준은 HEAD **90c6123**(G-P15 포함)이다.
- `git diff 90c6123 898fcc53 --stat`의 결과는 **22파일, 3631 insertions / 108 deletions**다. 계약 §9의 20파일에 C00이 추가 승인한 `tests/integration/test_publication_independent.py`와 `src/recoryn/storage/library.py`를 더한 목록과 같다. **범위 밖 변경은 0건이다.**
- `test_publication_independent.py`의 numstat은 `1 1`이다. 296행 `"RETRYABLE"→"TEMPORARY"` 한 문자열만 바뀌었다.
- `storage/library.py`의 변경은 네 가지뿐이다. C00이 허용한 '읽기 전용 공개 API 하나와 연결' 범위 안이다.
  - class 속성 `_job_authorities`(WeakValueDictionary)
  - `__init__` 끝의 등록(root mutex 안)
  - `job_authority` context manager
  - `close`의 자기 등록 해제
  - private journal parser나 잠금을 새로 만들지 않았다.
  - 메모리 색인(`_intent_journal/_stamp/_names/_settled`)은 갱신한다. G-P15의 `_indexed_journal`이 조회 중에 색인을 갱신하는 것과 같은 성격의 memo이며 영속 쓰기는 없다.
- 계약 문서 `docs/testing/g07-blocked-reason-cases.md`의 LF SHA-256은 `7eade9b39575cf42cf1d214a299a7f72258e617416c2340d3095082f51c09c4a`로 배정값과 같다.
- Python 21파일의 LF SHA-256을 문서 §'변경 파일과 LF SHA-256' 표와 대조했다. **21/21 일치.**
- 실행 위치는 다음과 같다. 작업 트리 `src`(G-P15b 미완성 변경 포함)로는 판정하지 않았다.
  - 판정: `git archive 898fcc53 | tar -x -C build/review-trees/g07a`
  - 기준 비교: `git archive 90c6123 | tar -x -C build/review-trees/g07a-base`
  - 변이: `build/review-trees/g07a-mut/*`, `g07a-mut6/*`(변이마다 pyproject·src·tests 사본)
  - 반례: `build/review-trees/g07a-probe/*`
- `.venv`의 editable 설치가 작업 트리를 가리키므로 모든 pytest에 `PYTHONPATH=<사본>\src`를 고정했다. 실행 전 `recoryn`, `recoryn.jobs`, `recoryn.storage.library`, `recoryn.app.status`의 `__file__`이 사본 안인지 확인했다. 반례 스크립트는 모두 `-I`로 실행하고, import 직후 `recoryn.__file__`이 지정 tree 안인지 assert한다. 변이 harness도 자식 프로세스의 import 경로를 사본 기준으로 assert한다.
- Git 쓰기, 설치, 네트워크, 실제 장치·모델·유료 호출, Credential Manager, 하위 에이전트, herdr는 사용하지 않았다.

## 2. 직접 실행한 명령과 결과

공통 조건: cwd는 사본, `.venv\Scripts\python.exe`(Python 3.13.1), `QT_QPA_PLATFORM=offscreen`, `PYTHONDONTWRITEBYTECODE=1`, `HF_HUB_OFFLINE=1`, `-p no:cacheprovider`, 실행별 새 `--basetemp`.

| # | 명령 | 결과 |
| --- | --- | --- |
| R1 | `pytest -q -p no:cacheprovider -W error::ResourceWarning --cov=recoryn --cov-branch --cov-report=json:coverage.json --cov-fail-under=85 --basetemp …/g07a-bt-full -rfE` (`g07a-probe/run-full.sh`) | **20293 passed, 2 skipped, 977.89s, exit 0.** 결합 coverage 92.49% |
| R1b | `python scripts/check_coverage.py coverage.json` | domain 100.00/100.00, capture 99.85/98.57, jobs 98.92/97.42, storage 96.51/92.43, security 98.11/94.43, content 99.59/98.75, **all 93.91/88.17**, 7묶음 모두 PASS |
| R2 | `ruff check src tests scripts packaging` / `ruff format --check …` / `MYPYPATH=src mypy src/recoryn scripts packaging` | All checks passed / 177 files already formatted / **88 source files no issues** |
| R3 | 신규 5파일 `--collect-only` → `g07a-probe/case_audit.py`(가족별 계획 수를 상수로 두고 기대 ID를 독립 생성) | 5117 node, 의미 ID **4947**. 14가족 모두 **누락 0 / 추가 0 / 중복 0**. 계획 밖 가족 0 |
| R4 | 신규 5파일 단독 `-W error::ResourceWarning` | **5117 passed, 7.91s**(벽시계 8.6s). 60초 게이트 충족 |
| R5 | 반례 스크립트 7개(§3) | G07R-01·02·04·08 재현. root mutex 보유는 기준 안(§4-2) |
| R6 | `g07a-probe/mutate.py`(변이마다 사본 1개, `-x`) | 계획 M23·M24·M25 **3/3 KILLED**. 검토자 변이 X1~X6b 8개 중 **1 KILLED / 7 SURVIVED**(§5) |

- **2 skip:** 둘 다 `tests/release/test_gpu_smoke.py:107: this volume does not create 8.3 names`다(`-rs` 재실행으로 확인). D: 볼륨 환경 차이이며 G-P07과 무관하다. 작성자의 20,295 PASS / skip 0과 다른 점은 이 2건뿐이다.
- **알려진 LAT 문제:** HEAD의 `tests/integration/test_seal_mutex.py` LAT·LAT2 행은 CI 러너에서 실패한 이력이 있다. 이번 R1에서는 이 PC에서 모두 통과했다. 따로 셀 실패는 없다.
- 증거 파일의 LF SHA-256(`build/review-trees/g07a-probe/`):

| 파일 | LF SHA-256 |
| --- | --- |
| `run-full.sh` | `42dc7a1b3362f67775c25dd8b3ea00650253cbdb773cc52170825bf114d0124e` |
| `full.log` | `9df2fb2bca278d9193ff0041243e9dd7e01e9ee25a8328413ac518874b871315` |
| `cov.log` | `201da297afd4c97014803f97f6b3a493dc44ac155ce22bf553a74e9b71d8e75b` |
| `g07a/coverage.json` | `a4ca4c4932cc26a7d4b55d55eaeb4276e9db1edb95621228376deba8323902cf` |
| `case_audit.py` | `f827b6067c5207caa0ccef3bfbb52d7f03530e6bc2c16ce06d20ca4fa0181c9e` |
| `codes_census.py` | `dbe2fe9f1e434121cd91706d332e08030b03fed129822c9feabfc76a9314555c` |
| `probe_boundary.py` | `0bd87daffcf6825af6d2d38d04089f30092a2f86edc9eb2d09fe3caff788baba` |
| `probe_stop_inflight.py` | `734047d102c12aa6a941bdfc4b6d1e77d7edf5bc4117c7796ce2ee4112684adb` |
| `probe_two_track_stop.py` | `a09d994d200f8660ad3cabe565656a5ca806d52ed0520483ad28cbb9460ff40c` |
| `probe_history_unavailable.py` | `b2ee1c14154fba06203484e078833cb72181c693c5ad6116c169432f38e4cb50` |
| `probe_root_hold.py` | `d0b6387a3c460a7ed8ac71d3e4cd602ec409294c06108bb5ec5f03ceaa8c98c0` |
| `probe_restart_failure.py` | `7aae0d674e7bea5b3c58de06ee75a98215d537f3b649dece96f46ac51d66c75c` |
| `mutate.py` | `7da0fb473bbcab26f8e70890188c2ca1d54920db994a236df95962069c18d4b7` |
| `covlines.py` | `82bc14bf63db81075fe009e85a167bb19c75293427a8ef3028dfcfab412e8ccc` |

반례 실행 명령의 형식은 `D:/project/Recoryn/.venv/Scripts/python.exe -I <script> <tree 경로> [<새 작업 폴더>] [인자]`다. tree 경로에는 `build/review-trees/g07a` 또는 `g07a-base`를 넘긴다.

## 3. 발견 사항

### G07R-01 / S2 / OPEN — STOPPING 동안 PCM을 거부해 원본 블록을 버린다. 두 번째 트랙은 첫 source 정지 시간 동안의 블록을 모두 잃고, 건강 통계에도 남지 않는다

- **근거:**
  - `src/recoryn/app/desktop.py:144` — `_submit`은 `_control_mode`가 `{"STARTING","ACTIVE"}`가 아니면 RecordingService에 넘기지 않고 `False`를 반환한다.
  - `desktop.py:245-247` — `_close_sources`는 첫 source의 `stop()`을 부르기 **전에** `STOPPING`으로 바꾼다. `desktop.py:229`의 시작 실패 경로도 같다.
  - source들은 차례로 정지되며 각각 최대 `timeout=5.0`까지 join한다. 그동안 아직 정지 신호를 받지 않은 뒤 source는 계속 PCM을 전달한다. RecordingService는 `recording.pause()/stop()` 전까지 수락 중이다.
- **재현 1(진행 중 블록):** `probe_stop_inflight.py`. 실제 WASAPI worker처럼 정지 확인을 통과한 블록이 `stop()` 도중 도착하는 순서를 결정적으로 만든다.

  | tree | `submit` 결과 | 저장 frame |
  | --- | --- | --- |
  | 90c6123 | `[true, true, true]` | stop·pause 모두 1440 |
  | 898fcc53 | `[true, true, false]` | **960** |

- **재현 2(두 트랙):** `probe_two_track_stop.py`. mic의 `stop()`이 join하는 동안 system이 10ms 블록 5개를 보낸다.

  | tree | system `submit` 결과 | 저장 frame |
  | --- | --- | --- |
  | 90c6123 | 모두 `true` | system **2880** |
  | 898fcc53 | `[true, false×5]` | system **480** |

  두 tree 모두 `capture_health`에 `dropped_frames` 기록이 없다. RecordingService에 도달하지 않았기 때문이다. UI의 '큐 포화 유실' 경고(`ui/main.py:1125`)도 나오지 않는다.
- **영향:**
  - 정지·일시정지 요청 직전에 캡처되어 장치 버퍼에 있던 backlog가 버려진다. 2트랙 녹음에서는 두 번째 트랙이 첫 source 정지(join·backend 정리) 시간만큼 잘린다. 첫 source 정지가 STOP_TIMEOUT까지 걸리면 최대 5초다.
  - 손실은 RecordingService 통계 밖이다. 일반 경로에서는 '모든 원본 보존'으로 보인다.
  - 계약 §1은 'WASAPI·PCM 저장 경로 변경은 범위 밖', §5.1은 '기존 PCM·epoch 검증과 원본 보존은 그대로 둔다'고 정했다. 표시 단위가 저장 수락을 바꾼 것이다.
- **시험:** 변이 X3(`STOPPING`도 수락)은 신규 5파일과 `test_desktop.py`·`test_desktop_independent.py`·`test_desktop_ui.py`의 5159건에서 **생존**한다. 거부 동작을 고정한 시험도 없고, 수락으로 고쳐도 REC 표시 시험이 깨지지 않는다.
- **기대:** 저장 수락의 거부 조건은 이전 run의 generation·epoch·session 불일치(늦은 callback)로 한정한다. STOPPING은 REC 표시만 억제하고, RecordingService가 epoch를 닫을 때까지 PCM이 원래 경로로 가야 한다. 거부가 꼭 필요하다면 C00 승인과 건강 통계 계상이 먼저다.
- **심각도:** S2. 경계 구간에 한정되고 쉽게 고칠 수 있다. 다만 복구할 수 없는 원본 손실이 통계 밖에서 생기므로 C00 판단으로 S1 상향 여지가 있다.

### G07R-02 / S2 / OPEN — gateway 경계에서 `outcome_known` 속성이 없는 오류를 '결과 확인됨'으로 승격한다

- **근거:**
  - `src/recoryn/providers/_common.py:278-288` — gateway 예외를 `normalize_failure(exc)`로 정규화한 뒤 `failure.outcome_known`을 그대로 전달한다.
  - `src/recoryn/jobs/failures.py:95` — 속성이 없으면 `True`가 기본값이다. 이 기본값은 계약 §3.1이 '로컬 예외 호환'을 위해 정한 것이다.
  - 90c6123의 gateway 경계는 `getattr(exc, "outcome_known", False) is True`였다. 속성이 없으면 미상이었다.
  - 그 밖에 `failures.py:90`의 StateConflict/ValidationError 단일 인자 코드 추출이 원격 경계에도 적용된다.
- **재현:** `probe_boundary.py`. 같은 fake gateway를 두 tree에서 실행했다.

  | 입력(gateway가 raise) | 90c6123 | 898fcc53 |
  | --- | --- | --- |
  | `.code="CONSENT_REVOKED"`, `outcome_known` 없음 | ProviderError known=False → **BLOCKED(REMOTE_UNKNOWN)** | known=True → **BLOCKED(CONSENT)**(계속 버튼 대상) |
  | `.code="TIMEOUT"`, 속성 없음 | BLOCKED(REMOTE_UNKNOWN) | known=True → FAILED |
  | `StateConflict("CONSENT_REVOKED")` | `REMOTE_OUTCOME_UNKNOWN` → BLOCKED(REMOTE_UNKNOWN) | `CONSENT_REVOKED` known=True → BLOCKED(CONSENT) |
  | `SecurityError(..., outcome_known=False)` | REMOTE_UNKNOWN | REMOTE_UNKNOWN(보존) |

- **영향:** 송신 여부를 밝히지 않은 원격 오류가 'known 실패'가 된다. 그 Job은 명시 계속으로 다시 전송될 수 있다(중복 송신·중복 과금 위험).
  - 현재 제품의 `security.gateway.Gateway.request`는 모든 예외를 `SecurityError(code, outcome_known=…)`로 감싼다(`security/gateway.py:300-308`). 그래서 지금 제품 경로의 도달은 없다. S1로 올리지 않은 이유다.
  - 계약 §3.1('gateway의 출처·결과가 불명확한 오류는 기존 REMOTE_OUTCOME_UNKNOWN으로 보수화')과 §개정 W('False를 True로 승격하지 않음')의 보수 원칙에 어긋난다.
- **시험:** W 172행의 fake gateway는 항상 `SecurityError(code, outcome_known=known)`을 던진다. 속성 부재 입력은 없다. 변이 X4(gateway 경계에서 속성이 없으면 미상)는 신규 5파일 5117건에서 **생존**한다. 수정해도 기존 시험과 충돌하지 않는다.
- **기대:**
  - gateway 경계는 `outcome_known is True`가 명시된 경우만 known으로 본다. 기존 의미를 유지하는 것이다.
  - 원격 경계에서는 StateConflict/ValidationError의 문자열 인자 코드를 신뢰하지 않는다.
  - W에 '속성 없음'·'로컬 예외형' 입력을 추가한다.

### G07R-03 / S3 / OPEN — 시작 실패·정지 실패의 ACK 대기 표시가 한 번도 실행되지 않는다. O 가족의 'start실패'는 pause로 대체되었다

- **근거:** 전체 회귀 coverage(R1)에서 다음 줄이 미실행이다.
  - `src/recoryn/app/desktop.py:239-242` — 부분 시작 실패 뒤 정지 ACK 실패. `_ack_pending=True`와 `CAPTURE_START_FAILED_ACK_PENDING`.
  - `desktop.py:277-280` — pause 실패.
  - `desktop.py:303-306` — stop 실패.
  - `ui/main.py:356-357` — 제어 작업 실패 뒤 `_capture_request` 해제와 재표시.
- `tests/ui/test_capture_start_ui.py:172`은 O 가족의 `"start-failure"` 종료를 `controller.pause()`로 실행한다. 실제 `_open_sources` 실패 경로가 아니다. 계약 §6.1 O의 '종료종류{…,start실패,…}' 분할을 이 대체로 채웠다는 사실이 문서에 공개되지 않았다.
- **변이:**
  - X1: `capture_status`가 `ack_pending`을 무시하도록 바꿈.
  - X2: 시작 실패의 ACK 대기를 `PAUSED`·`ack_pending=False`로 바꿈.
  - 둘 다 신규 5파일과 desktop 3파일 5159건에서 **생존**한다.
- **영향:** 계약 §개정 4의 'CAPTURE_START_FAILED_ACK_PENDING을 PAUSED나 정지 성공으로 표시하지 않음'을 시험이 보장하지 않는다. 구현은 코드 읽기로 확인한 바 기대대로 동작한다.
- **기대:** 실제 부분 시작 실패를 시험에 넣는다. 두 번째 source의 `start` 실패와 첫 source의 `stop` 실패를 조합하고, pause·stop 실패도 각각 다룬다. DTO·표시가 '종료 확인 대기'이고 REC·PAUSED·저장 완료가 아님을 assert한다.

### G07R-04 / S3 / OPEN — '삭제 이력 확인 불가'가 계약대로 표시되지 않는다. 일시적 거부 한 번으로 Job이 이번 실행 내내 QUEUED에 남는다

- **근거:**
  - `jobs/__init__.py:233-240`의 `DELETION_HISTORY_UNAVAILABLE`은 110코드 catalog에 없다. `ui/tasks.py`의 `Task.SAFE_CODES`에도 없다.
  - 명시 계속에서 이 코드가 나오면 `ui/ai_bridge.py:93-102`의 `guarded`가 TASK_FAILED로 보고 다시 raise한다. 화면은 `ui/tasks.py:70-83`을 거쳐 'AI 작업 중단: OPERATION_FAILED_MEDIA_PRESERVED'가 된다.
  - runner의 claim이 거부되면 `jobs/runner.py:242`에서 `JOB_UNAVAILABLE`로 삼키고 Job은 QUEUED로 남는다. 같은 요청을 다시 보내도 `app/ai.py:133`의 `_admitted`에 이미 있어 재제출하지 않는다.
  - claim 뒤 `reader_started`에서 거부되면 TASK_FAILED가 되어 Job이 terminal FAILED로 끝난다.
- **재현:** `probe_history_unavailable.py`. `Library.job_authority`가 첫 호출에만 `HISTORY_UNAVAILABLE`을 내게 했다. 세 번 연속 intent 변경 같은 일시적 상황의 대리다.
  - 결과: `state=QUEUED, attempts=0, runner last_error=JOB_UNAVAILABLE`
  - 이력이 정상으로 돌아온 뒤 같은 요청 → 같은 Job id, `QUEUED`, `provider_calls=0`
  - 표시 'AI: QUEUED ·  · 기존 원본·결과 보존', `can_continue=False`
- **영향:** 전송은 없다(fail closed). 사용자는 이유 없이 멈춘 QUEUED만 본다. 우회는 재시도(새 nonce)나 앱 재시작이다.
  - 계약 §개정 2.1은 '삭제 이력 확인 불가·준비 미접수/계속 불가'로 표시하라고 했다.
  - 원인이 되는 상황은 드물다: 소유 Library 종료, 세 번 연속 intent 변경, 정본 journal 손상.
- **기대:**
  - 이 코드를 표시용 사유로 매핑한다(catalog 확장 여부는 C00 결정).
  - runner의 입장 거부를 Job·표시에 남기거나 `_admitted`에서 빼서 다시 요청할 수 있게 한다.

### G07R-05 / S3 / OPEN — 기존 화자 Job의 '계속 제외'를 시험이 제품 코드가 아니라 시험 안의 복제 로직으로 확인한다

- **근거:**
  - 제품은 두 곳에서 화자 Job의 계속을 막는다: `ui/ai_bridge.py:860-861`(tick에서 `can_continue=False`)과 `ai_bridge.py:271-275`(continue의 kind 검사).
  - 전체 회귀 coverage에서 **두 곳 모두 미실행**이다.
  - `tests/ui/test_blocked_reason_ui.py:111-112`는 `if feature == "diarization": status = replace(status, can_continue=False)`를 시험 안에서 직접 수행한다. 그런 다음 비활성 버튼을 클릭한다.
- **변이:** X6a(tick의 화자 override 제거)와 X6b(continue의 kind 검사 제거)는 각각 신규 5파일과 `tests/ui` 전체 5617건에서 **생존**한다.
- **영향:** C00 결정('기존 화자 Job은 표시·탐색만, 같은 계획 계속 제외')을 시험이 보장하지 않는다. 두 guard를 모두 없애도 `_admit`의 kind 비교에서 `CONTINUE_PLAN_CHANGED`로 막히므로 전송은 없다.
- **기대:** U 가족의 화자 행은 `DesktopAI.tick()` 또는 `continue_blocked()`의 실제 분기를 거쳐 버튼 상태와 호출 0을 판정해야 한다.

### G07R-06 / S3 / OPEN — UI 명시 계속의 끝-끝 경로가 실행되지 않는다. F 가족 '권한 snapshot 폐기됨' 분할은 Job version stale로 대체되었다

- **근거:**
  - U 시험은 `bridge._transcribe`·`bridge.summarize`를 lambda로 바꾸고 호출 인자만 본다.
  - 실제 경로 `continue_blocked → _transcribe/summarize → privacy.prepare_execution(새 snapshot) → AIService.transcribe(expected_job_id…)`는 어떤 시험에서도 실행되지 않는다. coverage상 `ai_bridge.py:94-102`(guarded 예외 분기)와 `:449`(계속 성공 뒤 `_live_blocked` 해제)가 미실행이다.
  - 통합 시험의 계속은 `_admit`을 직접 부르거나 `context_factory` 없는 로컬 provider로 `AIService.transcribe`를 부른다(`test_blocked_reason_flow.py:180-219, 767-776`).
  - 계약 §6.1 F의 '준비{유효한 같은 계획, **권한 snapshot 폐기됨**, 의미/input 키 변경}'은 구현(`test_blocked_reason_flow.py:197`)에서 `expected_job_version = state_version - 1`로 바뀌었다. 동의·비용 snapshot 폐기와는 다른 입력이다.
  - D 가족 2,640행은 순수 함수 `failure_decision`만 판정한다. fence·reader·checkpoint 불변을 실제 `JobStore.fail`로 보는 행은 110코드 × (retryable=True, known=True, n=1, 유효)뿐이다. Attempt 행의 상태(FAILED/UNKNOWN)를 DB에서 직접 확인하는 D 행은 없다.
- **판정:** 코드 읽기로는 계속할 때마다 `prepare_execution`을 새로 부르고, 옛 grant·reservation을 재사용하지 않는다. 그래서 결함 반례는 없다. 다만 S0 민감 경로의 '새 snapshot' 요구를 시험이 고정하지 않는다.
- **기대:**
  - fake privacy·gateway로 UI 계속을 끝까지 실행하는 행을 둔다. 확인할 것: 새 snapshot 1회, 옛 reservation 재사용 0, 철회된 동의에서 dispatch 0, `CONTINUE_PLAN_CHANGED` 안내.
  - F의 middle 분할을 계약 문구대로 두거나, 변경 사실을 문서에 공개한다.

### G07R-07 / S3 / OPEN — 미확정 오디오·미완성 전사문 차단의 안내가 모델 설정으로 이동한다

- **근거:** `src/recoryn/app/status.py:69,76-104`. `TRANSCRIPTION_REQUIRES_FINALIZED_AUDIO`·`SUMMARY_REQUIRES_COMPLETE_TRANSCRIPT`는 CAPABILITY 기본 행동이다. 그래서 '모델·기능·언어·컨텍스트/사용 조건 확인'과 `model`(privacy의 모델 입력)로 연결된다.
- **기대:** 계약 §개정 1은 '실행 준비 차단·작업 미접수'로 표시하고 기존 확정/전사 화면으로 탐색하라고 했다. live이면 '녹음 종료 후 확정'을 안내해야 한다. 지금은 원인과 무관한 모델 설정으로 초점을 옮긴다. 부수효과는 없다.

### G07R-08 / S3 / OPEN — 녹음 표시 세부: 재시작 실패 뒤 '정지 중', 절전 문구 덮어쓰기, 최근 Job 하나만 투영

1. **재시작 실패:** `probe_restart_failure.py`. 녹음 하나를 정상 종료한 뒤 두 번째 `start`에서 `RecordingService.start()`가 실패하게 했다.
   - 결과: `control_mode=STOPPING`, 표시 **'정지 중 · 종료 확인 대기'**. 실제 세션은 CREATED이고 정지할 것이 없다.
   - 원인: `desktop.py:118`의 `self.close()`가 `_close_sources`에서 STOPPING을 남긴다. `_begin_run`(`:131`)은 실행되지 않는다.
   - tick(`ui/main.py:1120`)이 이 표시를 계속 다시 쓴다. REC 오표시는 아니다.
2. **절전 문구:** `ui/main.py:329`의 'Ⅱ 절전 일시정지 · 재개는 사용자 동작이 필요합니다'를 250ms tick의 `_show_capture_status()`(`:1120`)가 곧바로 일반 'Ⅱ 일시정지 …'로 덮는다. 90c6123에서는 tick이 저장 오류 때만 indicator를 바꿨다.
3. **최근 Job 하나만 투영:** `ui/ai_bridge.py:846-866`은 세션의 `jobs[-1]`만 투영한다.
   - 재생 검증(`ai_bridge.py:780-782`)은 seek마다 같은 세션에 `playback_verification` Job을 만든다. 그 뒤로는 BLOCKED 요약 Job의 안내·계속 버튼이 사라진다(`_blocked_target=None`).
   - 미등록 코드로 끝난 Job은 코드가 빈 칸으로 표시된다(`status.py:126-129`).
   - 근거는 코드 읽기다. 실제 위젯 재현은 하지 않았다.

### G07R-09 / S3 / OPEN — `_submit`이 DesktopRecorder 잠금을 쥔 채 RecordingService 잠금을 기다린다

- **근거:** `src/recoryn/app/desktop.py:139-148`. `with self._lock:` 안에서 `recorder.epochs.get(...)`을 부른다. `epochs` property는 `app/recording.py:82-84`에서 `_gate`를 잡는다. `_gate`는 `health_snapshot`이 쓰는 그 잠금이다.
- **판정:** 계약 §5.1('DesktopRecorder lock을 잡은 채 RecordingService.health_snapshot의 lock을 기다리는 반대 순서를 만들지 않는다')과 어긋난다. 역순(`_gate` 아래에서 DesktopRecorder 잠금 획득)은 찾지 못했으므로 deadlock 반례는 없다. 그래도 두 트랙 capture callback과 GUI의 `capture_progress`가 이 중첩을 통해 서로 기다린다.
- **기대:** 계약처럼 참조·token만 잠금 안에서 복사하고, epoch 조회는 잠금 밖에서 한 뒤 재확인한다.

## 4. 중점 검토 항목별 판정

1. **S0 경로(계속·암묵 resume·UNKNOWN):** 반례 없음.
   - `_admit`의 일반 경로는 BLOCKED를 관찰만 한다(`app/ai.py:120-136`). 명시 경로는 kind·input_key·세션 소속을 검사하고 `resume(expected_version)` CAS를 거친다(`:107-119`).
   - UI 계속은 매번 `prepare_execution`을 새로 부른다. REMOTE_UNKNOWN은 `resume`에서 거부되고 계속 버튼도 없다.
   - M25 재현 KILLED(`test_normal_request_cannot_implicitly_resume[G07-A-01]`). factory typed 오류의 unknown 보존은 M23 재현 KILLED(`G07-W-001`).
   - 90c6123은 factory의 `COST_CAP_EXCEEDED`(known=False)를 known으로 승격했지만, 이 tree에서는 REMOTE_UNKNOWN으로 고쳐졌다(probe_boundary). gateway의 속성 부재 기본값은 G07R-02다.
   - 제품에 `retryable=True`를 내는 코드가 없으므로 자동 BACKOFF 재송신 경로도 없다.
2. **삭제 권위:** L35는 7판정 × 입장 3·ACK 2를 실제 Library·JobStore로 판정한다. M24 재현 KILLED(`G07-L-07`). X5(reader 시작을 ACK처럼 허용)도 KILLED.
   - `probe_root_hold.py`(정본 intent 300건, 40 cycle)에서 lease 중 root mutex 최장 보유는 claim 2.72 / reader_started 1.97 / fail 2.14 / resume **3.56ms**였다. G-P15 기준(<50ms) 안이다. 환경 의존 측정값이며 assert는 아니다.
   - journal 전체 열거는 root 밖에서 한다. 구조 감시 시험(`test_authority_enumeration_is_outside_root_job_transaction_and_job_lock`)과 G05 PERF·G15 구조 시험이 R1에서 통과했다.
   - 잠금 순서 root → Job 잠금 → transaction은 ContentStore 게시(`content/store.py:645,703`: `with self._mutex, jobs._lock`)와 같은 방향이다. Job 잠금을 잡고 root를 기다리는 호출은 찾지 못했다(`_session_transaction`은 binding 복사 뒤 잠금을 놓는다).
   - `job_authority` 호출은 runner·AI pool(QThreadPool) 스레드뿐이다. GUI tick·render는 호출하지 않는다.
   - 표시 결함은 G07R-04다.
3. **110코드:** 시험 ORACLE은 손으로 쓴 표이고, 제품 `CODE_GROUPS`(109) + 미등록 대표 1과 같다.
   - `codes_census.py`로 src의 literal 오류 코드를 대조했다. catalog 밖 코드: ProviderError 18, SecurityError 23, StateConflict 47, ValidationError 91.
   - 이들은 모두 TASK_FAILED(known이면 FAILED, 미상이면 REMOTE_UNKNOWN)로 가며 자동 재시도는 없다. 계약의 fallback과 같다.
   - 사용자 문자열에서 코드를 추출하지 않는다(N06~09 canary 통과). 다만 원격 경계의 StateConflict 인자 추출은 G07R-02다.
   - 참고: `DIARIZATION_LICENSE_INVALID`·`INFERENCE_PROCESS_FAILED`·`CAPTURE_CLOCK_UNVERIFIED` 같은 제품 코드는 이제 TASK_FAILED로 기록된다. catalog 확장은 C00 결정 사항이다.
   - `SUMMARY_PARTIAL` 미등록을 확인했다.
4. **REC·시작 표시:**
   - V 288행은 REC 참 tuple 2개만 허용한다. O·E·실제 MainWindow 시험이 ready만·거부·무음·새 epoch·늦은 callback을 판정한다.
   - 수락 없는 REC 반례는 없다.
   - ACK 대기 표시는 구현은 맞지만 시험되지 않는다(G07R-03). 저장 수락 변경은 G07R-01, 잠금 중첩은 G07R-09, 표시 세부는 G07R-08이다.
5. **UI:**
   - render·open은 Job·동의·원장·정책에 부수효과 0이다(U 144행, 실제 PrivacyPanel 초점 16행, 실행 정책 초점 시험).
   - 오래된 선택은 `_current_blocked`(세션·state_version)와 store CAS가 이중으로 막는다.
   - 버튼의 accessibleName이 설정되어 있다. 비활성 사유는 `job_status` 문장에 나온다.
   - 시험 공백은 G07R-05·06, 안내 결함은 G07R-07·08이다.
6. **기존 기대값 변경:** 근거가 있다.
   - `test_app_service`의 OOM → BLOCKED(RESOURCE)와 `test_gpu_runtime_ui`의 GPU_RUNTIME_DAMAGED → BLOCKED(RESOURCE)는 계약 §7·§개정 4에 명시된 변경이다.
   - `test_gpu_runtime_ui`의 다음 실행은 `retry=True`(새 nonce)라서, BLOCKED가 된 뒤의 기대도 유지된다.
   - `test_jobs`의 SQL 강제 주입은 실제 `fail`·`block_pending`·`recover_abandoned`로 바뀌었다.
   - publication fixture는 한 문자열만 바뀌었다.
7. **시험 충분성:**
   - ID 감사는 4,947행 모두 0 오차(R3).
   - 독립 oracle은 대체로 지켜졌다. 예외: 화자 override 복제(G07R-05), F 분할 대체·D의 순수 함수 한정(G07R-06), O start실패 대체(G07R-03).
   - 계획 mutation 중 M23·M24·M25를 직접 재현해 모두 검출되었다.
   - `block_pending`은 제품 호출부가 없고 시험에서만 쓰인다. 현재 dispatch 전 재검사 호출부가 없어 계약 위반은 아니다.
8. **전체 회귀:** R1·R1b·R2 PASS(§2).

## 5. 변이(R6)

정상본은 신규 5파일 5117 passed, desktop 3파일 포함 5159 passed, `tests/ui` 포함 5617 passed다. 각 변이는 별도 사본에서 PYTHONPATH를 고정해 실행했다. 자식 import 경로가 사본 안임을 assert했다. pytest 종료 코드 1만 KILLED로 세었다. import·수집 오류(종료 코드 2 이상)는 0이다.

| ID | 변이 | 원본 → 변이 LF SHA-256(앞 16자) | 대상 | 결과 |
| --- | --- | --- | --- | --- |
| M23 | factory typed 오류를 `outcome_known=True`로 승격 | `686e659ecd2a2202` → `f7a61eb67866175d` | 신규 5 | **KILLED** `G07-W-001` |
| M24 | `JOURNAL_ONLY`를 `VALID`로 | `39e63c8e04f93165` → `b3d52ae6b634e078` | 신규 5 | **KILLED** `G07-L-07` |
| M25 | `_admit` 일반 경로에 알려진 BLOCKED 암묵 resume 복원 | `4442a3f6e79689bb` → `1a6b279546b9df5c` | 신규 5 | **KILLED** `G07-A-01` |
| X1 | `capture_status`의 ack_pending 분기 무시 | `eb0006d21258a5e4` → `0afa539d0828ceef` | 신규 5 + desktop 3 | SURVIVED(G07R-03) |
| X2 | 시작 실패 ACK 대기를 PAUSED로 | `7f49902d425f6457` → `c429ecba616ed34c` | 신규 5 + desktop 3 | SURVIVED(G07R-03) |
| X3 | STOPPING에서도 PCM 수락(G07R-01 수정안) | `7f49902d425f6457` → `1b017082c813949a` | 신규 5 + desktop 3 | SURVIVED(수정 호환) |
| X4 | gateway 경계 속성 부재를 미상으로(G07R-02 수정안) | `686e659ecd2a2202` → `f8cabd41ba664dc0` | 신규 5 | SURVIVED(수정 호환) |
| X5 | `reader_started`를 ACK처럼 비VALID 허용 | `aa0e5dfd4ba84603` → `55d3d77cf098e7c0` | 신규 5 | **KILLED** `test_intent_after_claim_blocks_reader_start_but_never_its_exit_ack` |
| X6a | tick의 화자 `can_continue=False` 제거 | `6c4927bc128fb8f4` → `01e4e6f70e76d32c` | 신규 5 + `tests/ui` | SURVIVED(G07R-05) |
| X6b | `continue_blocked`의 kind 검사 제거 | `6c4927bc128fb8f4` → `d7562d7da938aa37` | 신규 5 + `tests/ui` | SURVIVED(G07R-05) |

원본 hash는 작성자 표의 22파일 hash와 같다. 결과 원문은 `build/review-trees/g07a-mut/results.json`, `g07a-mut6/results.json`이다.

## 6. 반례를 찾지 못한 영역과 미검증 범위

- 실제 WASAPI 장치의 정지 join 시간과 그동안 버려지는 프레임 양은 측정하지 않았다. G07R-01은 fake source의 결정적 순서로만 재현했다.
- 실제 PrivacyPanel·ConsentStore·CostLedger·Gateway를 묶은 UI 계속(새 snapshot, 철회 경쟁)은 코드 읽기로만 판정했다(G07R-06).
- 다른 프로세스가 journal을 고치는 경우와 FAT·exFAT처럼 mtime 해상도가 거친 볼륨에서의 색인 settled 판정은 반례를 만들지 않았다. job_authority의 settled 계산 시점은 G-P15 `_list_journal`(나열 전 시각)과 달리 전체 읽기 후 시각이다.
- 원격 CI(windows-latest, Python 3.11·3.13)는 실행하지 않았다. 이 PC의 Python 3.13.1 결과만 있다.
- 실제 장치, 모델, 네트워크, 유료 호출, vault, 전원 이벤트, 장시간 녹음은 검증하지 않았다.

## RECHECK 1 — 2026-11-24, 같은 검토자(G-P07 FIX1 재확인)

**판정: G07R-01~09 9건 모두 RECHECKED. 새 OPEN 0건(S0 0 / S1 0 / S2 0 / S3 0).**

- C00은 G07R-01을 S1로 올렸다. 아래 근거로 이 상향 지적을 닫는다.
- 작성자 수정은 C00 결정과 일치한다.
  - 저장 수락은 이전 run의 generation·session·epoch 불일치와 recorder 교체일 때만 거부한다.
  - STOPPING·PAUSING은 REC 표시만 억제한다.
  - gateway 경계는 `outcome_known`이 bool `True`일 때만 known으로 본다.
- 작성자 보고('G-P07b로 미룬 항목 없음')와 이 재확인 결과가 서로 어긋나지 않는다.

### RC1-1. 입력과 범위

- 대상 tree는 **`8d455017eae3f206f0107d762f7b00eb680b22f0`**다(`git cat-file -t` = tree).
  - `git diff 90c6123 8d455017 --name-only`는 22파일로, 1차와 같은 목록이다.
  - `git diff 898fcc53 8d455017 --stat`은 14파일, 1482 insertions / 39 deletions다.
- 다음은 898fcc53과 byte 단위로 같다(`git diff --quiet`): `storage/library.py`, `jobs/__init__.py`, `ui/privacy.py`.
  - publication fixture는 90c6123 대비 numstat `1 1`이다.
  - library.py는 90c6123 대비 `105 0`이며 1차 범위 판정이 그대로 유효하다.
- 계약 문서의 LF SHA-256은 `bdf13ba4e71b1b02525eabe771d015b495db27ddc46cf2216b5e1f3b47b6d7d3`(863행)로 배정값과 같다. Python 21파일은 문서 §'FIX1 변경 파일과 SHA-256(LF)' 표와 **21/21 일치**한다.
- 작성자 manifest(`C:\Users\gangd\AppData\Local\Temp\recoryn-g07-fix1-zb_6bliv\…`)는 이 세션의 sandbox가 폴더 접근을 거부해 읽지 못했다(PermissionDenied). 제품 결함이 아닌 인프라 권한 문제다. 해시 대조는 문서 표로 대신했다.
- 실행 위치는 다음과 같다. 모든 pytest와 반례에 `PYTHONPATH=<사본>\src`를 고정하고 import 경로를 확인했다. 반례는 `-I -B`로 실행했다(작성자가 지적한 bytecode 생성 회피).
  - 판정: `git archive 8d455017 | tar -x -C build/review-trees/g07b`
  - 변이: `build/review-trees/g07b-mut/*`, `g07b-mutM/*`
  - 반례·로그: `build/review-trees/g07b-probe/*`

### RC1-2. 직접 실행

| # | 명령(cwd g07b) | 결과 |
| --- | --- | --- |
| RR1 | 1차 R1과 같은 CI 동등 명령(`g07b-probe/run-full.sh`: `pytest -q -p no:cacheprovider -W error::ResourceWarning --cov=recoryn --cov-branch --cov-report=json:coverage.json --cov-fail-under=85`, 고유 basetemp, offscreen) | **20366 passed, 2 skipped, 958.38s, exit 0.** 결합 coverage 92.68% |
| RR1b | `python scripts/check_coverage.py coverage.json` | domain 100.00/100.00, capture 99.85/98.57, jobs 99.10/95.54, storage 96.51/92.43, security 98.11/94.43, content 99.59/98.75, **all 94.14/88.28**, 7묶음 PASS |
| RR2 | `ruff check --no-cache src tests scripts packaging` / `ruff format --check --no-cache …` / `MYPYPATH=src mypy src/recoryn scripts packaging` | All checks passed / 177 files already formatted / **88 source files no issues** |
| RR3 | 신규 5파일 `--collect-only` → 1차 `case_audit.py` | 5190 node, 의미 ID **4947**. 14가족 누락·추가·중복 0. `G07-FIX1-` 접두 ID 67개(+명명 singleton 6 = 보강 73, 문서와 같음) |
| RR4 | 신규 5파일 단독 `-W error::ResourceWarning` | **5190 passed, 22.37s**(벽시계 23.3s). 60초 게이트 충족 |
| RR5 | 1차 반례 5개 재실행 + 새 경쟁 반례 1개 | 아래 RC1-3 |
| RR6 | 검토자 변이 14개(`g07b-probe/mutate_b.py`)와 계획 M23·M24·M25 재적용(1차 `mutate.py`) | **17/17 KILLED**, invalid 0(RC1-4) |

- **2 skip:** 1차와 같은 `tests/release/test_gpu_smoke.py:107`(8.3 이름 볼륨 조건)이다. 작성자의 20,368 PASS와 합계가 같다(20,366 + 2).
- jobs branch가 작성자 96.04%와 달리 95.54%다. 같은 tree에서 runner 경쟁 분기의 실행 여부가 달라진 정도로 보인다. 두 값 모두 기준(90%)을 넘는다.
- **1차 근거 정정:** 1차 G07R-06에서 coverage상 미실행으로 든 `ui/ai_bridge.py:94-102`(`guarded` 예외 분기)는 Qt `QThreadPool` 스레드에서 실행된다. `[tool.coverage.run]`에는 이 네이티브 스레드를 추적하는 설정이 없으므로 coverage로는 '미실행'을 증명할 수 없었다. 이번 RR1에서도 같은 줄이 미실행으로 나오지만, FIX1의 CONTINUE·HISTORY 행이 그 분기의 표시('새 작업 필요'·'삭제 이력 확인 불가')를 assert하므로 실제로는 실행된다. 1차 G07R-06의 결론(끝-끝 계속 시험 부재)은 시험 소스 읽기로도 성립했으므로 바뀌지 않는다.
- 증거 LF SHA-256:

| 파일 | LF SHA-256 |
| --- | --- |
| `g07b-probe/run-full.sh` | `fa48b38203fed4df3af0526e955c2d77418434b6aad356c07bd45ae640e98f75` |
| `g07b-probe/full.log` | `86db8c797a7725bda9836ac3861695a429751c52105a7eeba08a3cc97265a309` |
| `g07b-probe/cov.log` | `65f973ea04e1b8dd16ba6b532ff47a038cd9f68ed75151b4287e84d2b274ba79` |
| `g07b/coverage.json` | `ab5da2ed67c81365333f010007ae6f46c8b5e6f947a89e39ac9138fa47e6b5f6` |
| `g07b-probe/probe_epoch_race.py` | `aa1723a51a2020e74832b58b97ebe8ff184ed61238c1257af3ad3335f4d5e155` |
| `g07b-probe/mutate_b.py` | `622986097d92f4ff99dcbffcb6457a44f47ce0e730abb5e3e3b7196f69692fda` |
| `g07b-mut/results.json` | `149ce3c570723036306e7254c4cdd088bb4dfbb0e1c786a86e1bf9f3d38479fd` |

### RC1-3. 원 반례 재실행과 새 위험 탐색

| 반례 | 90c6123 | 898fcc53(1차) | **8d455017(FIX1)** |
| --- | --- | --- | --- |
| `probe_stop_inflight.py` stop·pause 저장 frame | 1440·1440 | 960·960 | **1440·1440**, submit 모두 `true` |
| `probe_two_track_stop.py` system 저장 frame | 2880 | 480 | **2880**, 6회 모두 `true` |
| `probe_boundary.py` 속성 없는 `.code` / `StateConflict` 인자 | REMOTE_UNKNOWN | BLOCKED(CONSENT) | **REMOTE_UNKNOWN**(기준과 같음). factory known=False 보존과 typed CONSENT_POLICY_CHANGED 전달은 1차 개선 유지 |
| `probe_history_unavailable.py` 일시적 거부 1회 → 같은 요청 | — | QUEUED 고착, provider 0 | 거부 뒤 QUEUED·attempt 0·`last_error=DELETION_HISTORY_UNAVAILABLE` → 같은 Job이 **SUCCEEDED·attempt 1·provider 1** |
| `probe_restart_failure.py` 두 번째 start 실패 | — | '정지 중 · 종료 확인 대기' | `START_FAILED`, **'시작 실패 · 기존 원본 보존 · 시작 조건을 확인하세요'** |

**새 경쟁 반례(요청 2): `g07b-probe/probe_epoch_race.py`.**

- 설계: WasapiSource처럼 각 source가 자기 worker 스레드에서 시작 identity로 10ms 블록을 계속 보낸다. `stop()`은 flag를 세우고 join한다. 주 스레드가 2트랙 녹음을 pause·resume한 뒤 stop한다.
- 독립 oracle(제품 health와 무관):
  - (트랙, epoch)별로 `submit()`이 `True`를 반환한 frame 합이 저장 chunk frame 합과 같아야 한다.
  - source worker에 예외가 가면 안 된다.
  - 쓰지 않은 epoch가 저장되면 안 된다.
  - 정지 뒤 각 source identity로 다시 보낸 블록은 수락되면 안 된다.
- 결과:

  | 실행 | epoch | 수락 = 저장 | 불일치 | worker 예외 | 정지 뒤 수락 |
  | --- | --- | --- | --- | --- | --- |
  | 15주기, 90c6123 | 32 | 170,880 | 0 | 0 | 없음 |
  | 15주기, FIX1 | 32 | 168,480 | 0 | 0 | 없음 |
  | 40주기, FIX1 | 82 | 435,360 | 0 | 0 | 없음 |

- 거부된 15,360 frame은 정확히 정지 뒤 일부러 보낸 블록 32개(480 × 32)다. 녹음 중에 건강 통계 밖으로 거부된 블록은 0이다(`rejected_not_in_health` = 늦은 블록 수, `health_dropped_frames` 0).
- 코드 판정(`app/desktop.py:140-166`):
  - 늦은 이전 run callback은 generation 불일치로 거부된다.
  - 이전 epoch 블록은 `recorder.epochs` 대조로 거부되고, RecordingService도 `_gate` 아래에서 epoch를 다시 검사한다.
  - 정지 뒤 PCM은 `_drain`이 `_accepting=False`로 만든 뒤라 `submit()`이 `False`를 반환한다. 닫힌 epoch에는 쓰이지 않는다.
  - 다른 세션의 recorder로 교체되면 identity 재확인으로 거부된다. 교체 직후 옛 recorder에 넘어간 블록은 옛 세션의 닫힌 epoch로만 가고 거부된다.
- 남는 이론상 창(결함 아님): `DesktopRecorder.resume()`(`desktop.py:293-298`)은 `recording.resume()` 다음에 `_begin_run()`을 부른다. 그 사이에는 이전 generation callback이 **새** epoch id를 가지고 오면 통과할 수 있다. 그러나 이전 run의 source는 pause에서 join된 뒤에만 `recording.pause()`가 실행된다. join에 실패하면 pause가 예외로 끝나 세션이 RECORDING에 머물고 resume이 거부된다. 또 source는 시작 때의 identity만 쓴다. 따라서 도달 경로를 찾지 못했다.

**요청 3(G07R-06):** `tests/ui/test_blocked_reason_ui.py`의 canonical F30(`:40-210`)과 `G07-FIX1-CONTINUE-01~10`(`:213-468`)을 읽고 RR4·RR1에서 통과를 확인했다.

- 실제로 쓰는 것: MainWindow·PrivacyPanel·ConsentStore·CostLedger·`security.Gateway`·adapter·runner.
- 바꾼 것: OS vault backend와 transport뿐이다(fake). vault 쓰기·삭제는 `pytest.fail`로 금지했다.
- 관찰하는 것:
  - 계속할 때마다 `prepare_execution`이 새로 호출되고 `expected_grants`가 바뀐다.
  - 옛 reservation factory는 철회 뒤 `SecurityError`로 거부된다.
  - 새 예약은 정상 계속에서만 1건이다(F에서는 `USER_CAP`).
- 철회 경쟁:
  - 준비 전 철회: `BLOCKED, attempt 1, transport open 1(최초 실패분)`, 새 예약 0, write 0.
  - 준비 후·worker 전 철회: `BLOCKED, attempt 2, open 1`, 새 예약 0, write 0. 둘 다 **추가 전송 0**이다.
- 의미 변경은 '새 작업 필요', 이력 불가는 '삭제 이력 확인 불가'로 표시되고 Job 수가 늘지 않는다.

**요청 4(G07R-09):**

- 정적 판정: `desktop.py`를 AST로 검사했다. `with self._lock:` 블록 안의 `epochs`·`health_snapshot`·`submit`·`pause`·`stop`·`resume`·`start` 속성 접근은 **0건**이다.
- 시험: `_submit`은 잠금 안에서 참조·token만 복사하고, epoch 조회는 잠금 밖에서 한 뒤 token을 다시 확인한다. `test_submit_reads_recording_epochs_without_holding_callback_lock`이 getter 안에서 `_lock.locked()`를 거부하고, 조회 중 generation 변경도 거부한다.
- 새 observer의 잠금:
  - `runner.on_admission_refused`는 runner `_condition`과 root mutex를 놓은 뒤 호출된다. 시험(`G07-FIX1-HISTORY`)이 `_is_owned()`로 이를 assert한다.
  - `AIService.close`는 `_admission_lock`을 놓은 뒤 `runner.stop`을 부르므로 observer와 교착하지 않는다.
  - 참고(결함 아님): `BoundedRunner._worker`는 `_execute`의 예외를 잡지 않는다. claim 거부 경로에서 observer가 예외를 내면 worker 스레드가 끝날 수 있다. 제품 observer는 `set.discard`뿐이라 실제 위험은 없다.

### RC1-4. 변이 재적용

각 변이는 별도 사본(pyproject·src·tests)에서 실행했다. 자식 `recoryn.app.status.__file__`이 사본 안임을 assert했고, `-x`로 돌렸다. pytest 종료 코드 1만 KILLED로 셌다.

| ID | 의도 | 원본 → 변이 LF SHA-256(앞 16자) | 결과(첫 실패 node) |
| --- | --- | --- | --- |
| M23 | factory unknown 승격 | (1차와 같은 패턴) | **KILLED** `G07-W-001` |
| M24 | JOURNAL_ONLY → VALID | 〃 | **KILLED** `G07-L-07` |
| M25 | `_admit` 암묵 resume | 〃 | **KILLED** `G07-A-01` |
| X1 | ack_pending 표시 무시 | `27e25a49d2cc5e89` → `cf7e9181b195f8a8` | **KILLED** `G07-FIX1-ACK-01` |
| X2 | 시작 실패 ACK 대기를 PAUSED로 | `5183ce23cf3a2a51` → `13d0d9cf04e1a217` | **KILLED** `G07-FIX1-ACK-01` |
| X3r | STOPPING 거부 복원(G07R-01 회귀) | `5183ce23cf3a2a51` → `81473e05f6b4ad06` | **KILLED** `G07-FIX1-PCM-01` |
| X4r | gateway 속성 부재 기본 known 복원 | `36fea38413511c0a` → `5a53a2aa02b38b7d` | **KILLED** `G07-FIX1-WIRE-01` |
| X4s | gateway에서 StateConflict 인자 추출 복원 | `36fea38413511c0a` → `4dc3b5913fe4ced2` | **KILLED** `G07-FIX1-WIRE-04` |
| X6a | tick의 화자 계속 비활성 제거 | `163affb7a3cc20a9` → `601e8b131dab6491` | **KILLED** `G07-U-013` |
| X6b | continue의 kind 검사 제거 | `163affb7a3cc20a9` → `fac6859817d51961` | **KILLED** `test_diarization_direct_continue_uses_the_product_kind_guard` |
| X9r | callback 잠금 안에서 epoch 조회 | `5183ce23cf3a2a51` → `def6a4bf4d18628f` | **KILLED** `test_submit_reads_recording_epochs_without_holding_callback_lock` |
| X10 | 입장 거부 뒤 `_admitted` 해제 제거 | `19707dc3b71a385d` → `58fb448e9e7d82c6` | **KILLED** `test_real_window_updates_a_queued_history_refusal_and_allows_explicit_readmission` |
| X11 | tick의 이력 불가 표시 제거 | `163affb7a3cc20a9` → `b64f41e3daa4fb85` | **KILLED** 위와 같은 node |
| X12 | 확정 안내를 모델 설정으로 되돌림 | `27e25a49d2cc5e89` → `531416fbca2cbc1c` | **KILLED** `G07-FIX1-NAV-01` |
| X13 | 절전 표시 덮어쓰기 복원 | `e63f7ed39c0ffbcc` → `2c4b511a68cc26c3` | **KILLED** `G07-FIX1-WINDOW-04` |
| X14 | 재생 검증 Job 필터 제거 | `163affb7a3cc20a9` → `2993a226cdbbf06b` | **KILLED** `test_playback_jobs_never_hide_a_blocked_ai_job_and_unknown_codes_are_safe` |
| X15 | START_FAILED 표시 제거 | `5183ce23cf3a2a51` → `3af55df840b33d29` | **KILLED** `test_restart_storage_failure_cannot_reuse_the_prior_stopping_indicator` |

원본 hash는 작성자 FIX1 표와 같다(status `27e25a49…`, desktop `5183ce23…`, failures `36fea384…`, ai_bridge `163affb7…`, ai `19707dc3…`, main `e63f7ed3…`).

### RC1-5. 1차 발견 상태

| ID | 1차 → C00 | 상태 | 근거 |
| --- | --- | --- | --- |
| G07R-01 | S2 → **S1** | **RECHECKED** | 원 반례 2개가 기준 tree와 같은 저장 frame(1440, 2880)을 낸다. 새 경쟁 반례 3회에서 수락 = 저장, 닫힌 epoch 기록 0, worker 예외 0. X3r이 PCM4로 검출된다. PCM4는 실제 `audio.pcm` bytes 연결과 `dropped_frames=0`까지 판정한다 |
| G07R-02 | S2 | **RECHECKED** | `failures.py:85-96`의 `remote_boundary`와 `_common.py:278`. 속성 없음·비bool·getter 실패·로컬 인자는 미상이다(WIRE6). X4r·X4s 검출. factory 경계는 계약의 '미등록 factory 오류 → BUDGET_BLOCKED' fallback(송신 전)을 유지한다 |
| G07R-03 | S3 | **RECHECKED** | O의 start-failure가 실제 resume start 실패가 되었다. ACK3(부분 시작·pause·stop)과 WINDOW 행이 생겼고 X1·X2 검출 |
| G07R-04 | S3 | **RECHECKED** | `runner.py:71-83,204-277`, `ai.py:93-101`, `status.py:126-131,183-195`, `ai_bridge.py:93-109,874-930`. 1회·지속 거부 모두 전송 0. 회복 뒤 같은 요청이 실제 입장 guard를 다시 거쳐 실행된다. 실제 Window가 '삭제 이력 확인 불가'를 표시한다. X10·X11 검출. catalog는 110 그대로다 |
| G07R-05 | S3 | **RECHECKED** | U 행이 실제 `bridge.tick()`을 거친다. 직접 continue 시험이 추가되었고 X6a·X6b 검출 |
| G07R-06 | S3 | **RECHECKED** | 위 요청 3. canonical F의 '철회된 권한' 분할이 복원되었고, 옛 Job version stale 30행은 `G07-FIX1-CAS`로 이름이 바뀌어 공개되었다. D 2,640행 모두 실제 SQLite의 Attempt 상태·reader·checkpoint까지 대조한다 |
| G07R-07 | S3 | **RECHECKED** | `status.py:78-82`가 `finalize`·`transcription`으로 탐색하고, '녹음 중이면 정지 후 세션 확정' 안내를 낸다. NAV3에서 실행 0, X12 검출 |
| G07R-08 | S3 | **RECHECKED** | (1) `START_FAILED`(`desktop.py:131-137`, `status.py:34-35`), X15 검출. (2) 절전 표시 유지(`main.py:1104-1111`), X13 검출. (3) `ai_bridge.py:883`이 재생 검증 Job을 AI 상태에서 빼고, 미등록 코드는 `TASK_FAILED`로 표시한다. X14 검출 |
| G07R-09 | S3 | **RECHECKED** | 위 요청 4. X9r 검출 |

### RC1-6. 새 발견

없다(새 OPEN 0). 다음은 결함이 아닌 참고 사항이다.

1. RC1-3의 `resume()` 호출 순서에 따른 이론상 창. 도달 경로가 없다.
2. RC1-3의 runner worker가 observer 예외로 끝날 수 있는 구조. 제품 observer는 예외를 내지 않는다.
3. RecordingService 생성자 자체가 실패하면 `self.recording`은 이전(종료된) 세션 객체로 남는다. 표시는 '시작 실패 · 기존 원본 보존'이 되며, 이전 원본에 대해 사실이다.

미검증 범위는 1차 §6과 같다: 실제 WASAPI 장치의 정지 join 시간, 원격 CI(Python 3.11), 실제 장치·모델·네트워크·유료 호출·vault·전원 이벤트.
