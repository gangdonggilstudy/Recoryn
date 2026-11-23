# G06 / G-P06 비용 상한 독립 검토

2026-11-23, 검토자 Claude(C00 배정 G-P06 독립 검토). 작성자는 w5:p8 Codex이며 검토자는 이 단위의 코드·시험·계약 문서를 작성하지 않았다.

**판정: OPEN 7건 — S0 0 / S1 2 / S2 2 / S3 3. S1 두 건이 열려 있으므로 push 불가다.**

무동의·무예약 전송, 상한 초과 예약, catalog 누락·가격 미상·통화 불일치·정책 변경 뒤의 연결은 반례를 찾지 못했다. 모두 fail closed다. 동시 예약 이중 지출과 같은 예약의 중복 dispatch도 찾지 못했다.

열린 S1은 다음 두 건이다.

1. 한 번 앞선 벽시계가 high-water로 영속되면 비용 ledger만이 아니라 **데스크톱 앱 시작(녹음 UI) 자체가 실패**한다.
2. 64 KiB write마다 다음을 반복한다: 본문 전체 해시, wire 재해석, ledger 전체 상태 해시, witness fsync, DB commit. 그 결과 **실제 경로의 OpenAI STT 업로드가 30초 Gateway 기한을 넘는다.** 첫 write 뒤 `REMOTE_OUTCOME_UNKNOWN`으로 실패하고 노출액이 남는다.

두 건 모두 전송 범위를 넓히지는 않지만 핵심 기능을 막는다. S2는 계약 §5의 정확한 코드 oracle 미이행과, G06이 추가한 fail-closed 가드 다수에 대응 시험이 없는 문제다. 최종 수용과 통합은 C00이 결정한다.

## 1. 입력 고정과 범위 판정

- 검토 tree는 **`5317e250d51ea7a79f42ac277e747bac66ed7596`**이다(`git cat-file -t` = tree). 기준은 HEAD **8e09b62**(G-P04 포함)다.
- `git diff --name-status 8e09b62 5317e250…`의 결과는 **26파일(A 7 / M 19), 4754 insertions / 148 deletions**다.
  - 계약 §8의 승인 29파일과 대조했다. **승인 목록 밖 변경은 0건이다.**
  - 바뀌지 않은 승인 파일은 3개다: `src/recoryn/ui/ai_bridge.py`, `tests/unit/test_security.py`, `tests/integration/test_ai_independent.py`. `git diff --quiet 8e09b62 5317e250 -- <3파일>`로 8e09b62와 byte 단위로 같음을 확인했다.
  - 작성자가 말한 '29파일'은 승인 범위의 수다. 계약 §12.6·§13.2는 '실제 변경 26 + 동일 3'으로 정확히 적었으므로 문서상 불일치는 없다.
- 계약 문서 `docs/testing/g06-cost-cap-cases.md`의 LF SHA256은 `54a197d1bb67033d89f3085437806198732299792876e5774b2baf4091d4788e`로, 배정값과 일치한다.
- Python 28파일의 LF SHA256을 직접 계산했다. **28/28이 계약 §12.6 표와 일치한다.**
- 검토 시점 작업 트리의 G06 26파일도 tree와 LF hash 차이가 0이다.
- 추출과 실행 위치는 다음과 같다. 작업 트리 `src`로는 판정하지 않았다.
  - 판정·전체 시험: `git archive 5317e250 | tar -x -C build/review-trees/g06a`
  - 기준 비교: `git archive 8e09b62 | tar -x -C build/review-trees/g06a-base`
  - 변이: `build/review-trees/g06a-mut`(g06a 복사본)
  - basetemp: `build/review-trees/g06a-bt/*`
  - 반례 스크립트: `build/review-trees/g06a-probe/*`
- `build/`는 `.gitignore` 대상이다. 저장소에 추적되는 쓰기는 이 문서 하나뿐이다. Git 쓰기, 설치, 네트워크, 실제 장치·모델, vault 쓰기, 유료 호출, 하위 에이전트와 herdr는 사용하지 않았다.

## 2. 직접 실행한 명령과 결과

모든 pytest는 cwd를 사본으로 두고 저장소 `.venv` Python으로 실행했다. 공통 옵션은 `QT_QPA_PLATFORM=offscreen`, `PYTHONDONTWRITEBYTECODE=1`, `-p no:cacheprovider`, 실행별 새 `--basetemp`다.

| # | 명령(cwd g06a) | 결과 |
| --- | --- | --- |
| R1 | `pytest -q -W error::ResourceWarning --basetemp …/full -rs --junitxml …/g06a-full.xml` | **14405 passed, 2 skipped, 555.99s, exit 0** |
| R1b | R1에 `PYTHONPATH=g06a/src`, `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, `-W error::pytest.PytestUnraisableExceptionWarning`를 더함, `--junitxml …/g06a-full2.xml` | **14405 passed, 2 skipped, 565.39s, exit 0**. JUnit testcase 14407, node 중복 0 |
| R2 | 신규 4파일만, `--junitxml …/g06a-new4.xml` | **4860 passed, 74.33s** — 승인된 이 PC 120초 예산 안 |
| R3 | `python -I g06a-probe/audit_ids.py g06a-full2.xml`(계약 §6.2 상수로 기대 ID를 독립 생성) | 의미 행 **4834 고유, 누락 0 / 중복 0 / 추가 0**. 차이는 zero-padding 관례뿐이다(DB는 `01..16`, LOCAL은 `000..002`). 비가족 node는 26개다(auxiliary 22 + manifest 4, 작성자 주장과 같음). 4860 모두 passed. 전체 실행 안의 4파일 testcase 시간 합은 77.33s |
| R4 | `ruff check --no-cache .` / `ruff format --check --no-cache .` / `mypy src/recoryn scripts packaging`(cache는 basetemp 아래) | All checks passed / 163 files already formatted / **86 source files, no issues** |
| R5 | 반례 스크립트 6개(§3, §4) | G06R-01·02 재현. 동시성 반례 없음 |
| R6 | `python -I mutate.py`(변이마다 사본 1개, `-x`, 선택 10파일, 정상본 **5068 passed**) | 검토자 변이 R01~R15: **3 KILLED / 12 SURVIVED**, invalid 0. 작성자 변이와 같은 의도의 A-M09·M17·M18·M28: **3 KILLED / 1 SURVIVED(A-M17)**. §5 참조 |

- **2 skip 사유:** 둘 다 `tests/release/test_gpu_smoke.py:107: this volume does not create 8.3 names`다. D: 볼륨이 8.3 이름을 만들지 않는 환경 차이이며 G-P06과 무관하다. 작성자의 14407 PASS / skip 0과 다른 점은 이 2건뿐이다.
- **R1b를 정본으로 삼는 이유:** venv의 `__editable__.recoryn-0.2.0.dev1.pth`가 `D:\project\Recoryn\src`를 가리킨다. PYTHONPATH를 고정하지 않으면 subprocess 시험이 작업 트리(G-P05 미완성 변경 포함)를 import할 수 있다.

증거의 LF SHA256은 다음과 같다.

- 시험 결과: `g06a-full.xml` `351fddbe52d3022c358c50dc7e52c72fbe204b4047255873e9d9f13ee5a4e373`, `g06a-full2.xml` `f1374add5c37b78b2ee3a16a2a062b167cea11985273c19a0ee90d2415fbe7e8`, `g06a-new4.xml` `687fcd2feb079f02436cc2153c1ad4196d99475d8bd69781385032b2b039add7`
- 반례 스크립트(`build/review-trees/g06a-probe/`):

| 파일 | LF SHA256 |
| --- | --- |
| `probe_common.py` | `204f51101a757d0bf1b2712a5f66255d0ea7a2fc09083894e0fa691d1e8741df` |
| `probe_clock.py` | `de8c9f37bfd7278a1359544914daf1ae9865b1208658d30ff696bb340adbb71b` |
| `probe_perf.py` | `1a4ba61cd587384724afc5a12a08c06de7088040b0d5cb2ab27b45d6dfa60a02` |
| `probe_perf_base.py` | `93285fa70ef852dc403be415f270b8e6dce3085f69032242206b1d29bb7e1a9f` |
| `probe_perf_openai.py` | `f61c9904f7b671d90537dc4cd1ce26efefd20b9878263c295c6b1d2e5fac5720` |
| `probe_concurrency.py` | `a266b6993d91564639f49cf39802d0f61bdba9a9e9817c7db9bf015b1164efa9` |
| `audit_ids.py` | `00c9a2810c1daaf104d58d95cae6fae6c59f11f75357790f5fbab6af837af28a` |

반례 스크립트는 `probe_common.py`에서 import 직후 `recoryn.security.ledger.__file__`가 g06a 사본 안인지 assert한다. 실행 명령은 `cd build/review-trees/g06a-probe && D:/project/Recoryn/.venv/Scripts/python.exe <script> <새 출력 폴더> [인자]`다. `probe_clock.py`는 `QT_QPA_PLATFORM=offscreen`이 필요하다.

## 3. 발견 사항

### G06R-01 / S1 / OPEN — 한 번 앞선 벽시계가 high-water로 영속되면 CostLedger를 열 수 없고 MainWindow(녹음 UI) 생성이 실패한다

**재현** — `probe_clock.py <폴더>`

1. 새 DB를 `CostLedger(db, clock=lambda: real+3600)`로 한 번 열고 닫는다. 예약·정책 적용·원격 호출은 하지 않는다.
   - 관측: `first open (no reservation, no policy) persisted high-water - real = 3600.0`
2. 시계를 바로잡은 뒤(`real+5`) 다시 연다.
   - 관측: **`COST_CLOCK_INVALID`**
3. 같은 방식으로 1시간 앞선 시계로 library의 `security.sqlite`를 한 번 연다. 그 뒤 실제 시계로 `MainWindow(library)`를 생성한다.
   - 관측: **`MainWindow construction: SecurityError COST_CLOCK_INVALID`**
   - 앱 진입점 `run()`(`src/recoryn/ui/main.py:887-896`)에는 이 예외를 처리하는 곳이 없다. 앱이 시작되지 않고 녹음도 할 수 없다.
4. 기준 8e09b62의 CostLedger에는 시계 검사가 없어 같은 상황에서도 정상 시작한다.

**원인** — 근거는 `src/recoryn/security/ledger.py`의 다음 지점이다.

- `:52` 생성자가 `self._last_now = clock_value(clock())`를 기록한다.
- `:159-161` `_initialize_v2`가 이 값을 `clock_high_water_utc`로 **첫 열기(마이그레이션) 때 영속**한다.
- `:289-293` 모든 `_change`가 high-water를 현재 시각으로 올린다. 매 dispatch 검사에서도 `:930-936`을 통해 올린다.
- `:60-64` v2 DB의 **생성자 경로가 `self._now()`를 호출**한다. `:169-177`은 저장값보다 이른 시각이면 `COST_CLOCK_INVALID`를 던진다.
- `src/recoryn/ui/main.py:91-92` MainWindow 생성자가 `CostLedger(...)`를 보호 없이 연다.

**영향**

- 다음 경우 한 번이면 시계를 바로잡은 뒤에도 그 시각이 될 때까지 앱이 시작되지 않는다.
  - 업그레이드 뒤 첫 실행이 시계가 앞선 상태에서 일어난 경우. 예: dual boot의 RTC/현지시각 혼동(KST이면 9시간), 잘못된 수동 시각.
  - 그 상태에서 비용 동작을 한 번이라도 한 경우.
- 시계가 며칠·몇 년 앞섰다면 사실상 영구 장애다.
- 복구 경로가 없다.
  - `security.sqlite`만 지우면 witness가 남아 `:54-55`의 `LEDGER_ROLLBACK_DETECTED`로 여전히 시작하지 않는다.
  - 둘 다 지우면 동의·비용 기록을 잃는다.
- NTP가 몇 초 되돌린 경우에도 그 몇 초 동안 앱 시작과 모든 ledger 동작이 실패한다.
- 제품 불변식 "AI 실패가 녹음을 중단시키지 않는다"(AGENTS.md)를 위반한다.
- 계약 §4.3은 시계 역행 시 **비용 송신**을 `COST_CLOCK_INVALID`로 막으라고 할 뿐, ledger 열기나 앱 시작의 차단은 요구하지 않는다.

**시험 공백**

- 재시작 뒤의 시계 역행을 검증하는 시험이 없다. high-water 영속을 제거한 변이 R11이 **SURVIVED**했다(§5).
- PRICE-TIME의 역행 행은 같은 인스턴스의 메모리 `_last_now`만 검사한다(`tests/integration/test_cost_cap.py:463-469`).

**기대**

- 시계 역행은 비용 판정(reserve/open/write)에서만 `COST_CLOCK_INVALID`로 막는다.
- ledger 열기, 녹음, 로컬 경로와 앱 시작은 영향을 받지 않는다.
- 앞선 high-water에서 벗어나는 명시적 복구 절차를 정한다. 예: 사용자 확인 뒤 새 high-water 기준을 정하고 미정산 노출을 보존한다.
- 비용 ledger 초기화 실패(시계·rollback·마이그레이션)가 MainWindow 생성을 막지 않도록 하고, 비용 기능만 차단 상태로 표시한다.
- 재시작 역행 시험과 MainWindow 시작 시험을 추가한다.

### G06R-02 / S1 / OPEN — write마다 수행하는 비용 재검증이 본문 크기와 ledger 이력에 비례하고 fsync 두 번을 포함해, 실제 STT 업로드가 30초 기한 안에 끝나지 않는다

**재현** — 모두 메모리 transport다. 네트워크 시간은 0이므로 실제 환경보다 유리하다.

- **(a) 현재 배포 경로:** 빈 catalog, 일반 모드 USER_CAP, 실제 OpenAI multipart STT 본문. `probe_perf_openai.py <폴더> <분> <이력>`의 결과는 다음과 같다.

| 녹음 길이(16 kHz mono WAV) | 본문 | ledger 이력 | write 진행 | 경과 | 결과 |
| --- | ---: | ---: | --- | ---: | --- |
| 10분 | 19,200,441 B | 0 | 72/293 | 30.16s | `REMOTE_OUTCOME_UNKNOWN outcome_known=False`, write당 418.91 ms |
| 10분 | 19,200,441 B | 300 | 72/293 | 30.37s | 같은 실패 |
| 5분 | 9,600,441 B | 0 | 138/147 | 30.02s | 같은 실패 |

- **(b) VERIFIED opaque 20 MiB(`probe_perf.py <폴더> 0,500,1000,2000 20`)와 기준 비교:**

| ledger 이력 | G06(5317e250) | 기준 8e09b62(`probe_perf_base.py`) |
| ---: | --- | --- |
| 0 | 16.26s, 50.83 ms/write, OK | 0.12s, 0.37 ms/write, OK |
| 500 | 22.93s, OK | — |
| 1000 | **292/320에서 30.07s `REMOTE_OUTCOME_UNKNOWN`** | — |
| 2000 | **195/320에서 30.02s `REMOTE_OUTCOME_UNKNOWN`** | 0.13s, 0.40 ms/write, OK |

- 두 경우 모두 해당 요청의 상태는 `UNKNOWN`으로 남았다.

**원인** — 근거는 `src/recoryn/security/gateway.py`와 `src/recoryn/security/ledger.py`다.

- `gateway.py:197-212, 268-276`: 매 64 KiB 조각 전에 `validate_dispatch(phase="write")`를 호출한다. 첫 조각은 `:327-330`에서 `check_reservation`과 `mark_unknown`도 실행한다.
- `validate_dispatch` 한 번이 하는 일(ledger.py):
  - `:846` `_verify()`가 v1·v2 전체 상태를 정규화하고 해시한다.
  - `:856` `digest(body)`가 본문 전체를 해시한다.
  - `:864-875` `CostRequest` 재구성과 `fingerprint`로 본문 전체를 다시 해시한다.
  - `:876` `_eligible_account`가 `legacy_unscoped`를 거쳐 `:680` `_verify()`를 **한 번 더** 실행한다.
  - `:887` VERIFIED이면 `quote()`를 재실행한다(`inspect_wire`와 본문 해시 포함).
  - `:891-893` USER_CAP이면 `inspect_wire`가 **multipart 전체 MIME 파싱과 WAV 전체 읽기**를 한다(`cost.py:379-414`, `:339-355`).
  - `:930-936` 벽시계가 high-water보다 크면(사실상 항상) `_change(lambda: None)`를 실행한다. 그 안에서 `_verify()`를 다시 하고, witness를 **fsync**하고, SQLite를 `synchronous=FULL`로 **commit**한다.
- 결과적으로 조각당 비용은 O(본문)+O(이력)+fsync 2회다. 요청 전체로는 본문 크기에 대해 **이차**다. 이력은 정리되지 않으므로 사용할수록 단조 증가한다.
- Gateway 기한은 요청 전체에 대해 30초다(`src/recoryn/ui/privacy.py:670`, `gateway.py:178`).

**영향**

- 원격 STT는 녹음 전체를 한 요청으로 보낸다(`src/recoryn/transcription/adapters.py:222-260`). 이 PC에서는 **약 5분 이상 녹음의 OpenAI STT가 네트워크가 무한히 빨라도 결정적으로 실패**한다.
- 실패는 첫 write 이후에 일어나므로 `outcome_known=False`와 UNKNOWN 노출액(USER_CAP이면 cap)이 남는다.
- 재시도할 때마다 예산을 새로 소모한다. 수동 정산 전까지 기간 예산이 고갈되고, 다음 기간도 `COST_UNRESOLVED_EXPOSURE`로 막힌다.
- 작은 본문도 이력이 쌓이면 느려진다.
- 추가 위험(미측정): witness 선행 → commit 사이의 crash/전원 손실 창이 요청당 약 2회에서 **조각 수만큼**으로 늘어난다. 이 창에 걸리면 `LEDGER_ROLLBACK_DETECTED`로 영구 차단된다(계약 수용 범위). G06R-01과 같은 결합 때문에 이 경우에도 앱이 시작되지 않는다.

**시험 공백**

- 실제 wire 형식으로 여러 조각을 보내는 시험이 없다.
- 통합 fixture는 `chunk_bytes=3`과 수십 byte 본문을 쓴다(`tests/integration/test_cost_cap.py:294-312`).
- 계약 §10의 시간 게이트는 시험 실행 시간만 다룬다.

**기대**

- 계약 §2와 §3.3의 매 write 재검사는 유지한다. 대신 같은 dispatch에서 변하지 않는 사실(본문 digest, wire 해석, fingerprint)은 open 전에 한 번만 계산해 재사용한다.
- 매 write에서는 철회, 정책 version, 가격 만료, 시계, 잔액만 O(1)에 가깝게 확인한다.
- witness 게시와 commit은 상태 전이에서만 한다.
- 최대 본문(20 MiB) 실제 wire의 dispatch 시간 예산 시험과 이력 수천 행에서의 회귀 시험을 둔다.

### G06R-03 / S2 / OPEN — 단일 원인 거부 행이 정확한 코드를 검사하지 않는다. 신규 COST 코드 15개 중 10개는 한 번도 assertion되지 않는다

**재현과 근거**

- 신규 4파일에서 각 코드 문자열의 등장 횟수가 **0**인 코드: `COST_CAP_REQUIRED`, `COST_REQUEST_INVALID`, `COST_BOUND_UNVERIFIED`, `COST_QUOTE_EXPIRED`, `COST_CURRENCY_MISMATCH`, `COST_PERIOD_CHANGED`, `COST_AMOUNT_OVERFLOW`, `COST_UNRESOLVED_EXPOSURE`, `COST_CLOCK_INVALID`, `COST_PLAN_UNDERESTIMATED`.
- `COST_QUOTE_MISMATCH`는 catalog digest 시험(`tests/unit/test_cost_cap.py:432`) 한 곳에만 나온다.
- 다음 가족의 거부 판정은 코드 없이 `pytest.raises(SecurityError)`만 쓴다.
  - TEXT `tests/property/test_cost_cap_case_space.py:188`
  - NUMERIC `tests/unit/test_cost_cap.py:412`
  - AUDIO `tests/integration/test_cost_cap.py:353`
  - BIND `:404`
  - PRICE-TIME `:496`
  - PERIOD `:539`
  - DB `:747`, `:772`
  - UI `tests/ui/test_cost_cap_ui.py:182`
- 코드를 바꿔치기한 변이 R13(`COST_CAP_REQUIRED`→`COST_CAP_EXCEEDED`), R14(`COST_UNRESOLVED_EXPOSURE`→`BUDGET_EXCEEDED`), R15(기간 밖 `COST_PERIOD_CHANGED`→`BUDGET_POLICY_CHANGED`)는 **셋 다 SURVIVED**했다(§5, 각 5068 passed).

**기대**

- 계약 §5는 "단일 원인 행은 위 정확한 코드를 검사한다"고 정한다.
- `docs/testing/case-space.md:21`은 비용에 대해 "진단 우선순위도 확인한다"고 정한다.
- 사용자 다음 행동은 코드에 따라 갈린다. 예: cap 증가로 해결되지 않는 `COST_BOUND_UNVERIFIED`, 정산이 필요한 `COST_UNRESOLVED_EXPOSURE`. G-P07의 BLOCKED 사유 분류도 이 코드에 의존한다.
- 단일 원인 행은 정확한 코드를 검사하고, 복합 행은 허용 코드 집합을 검사해야 한다. 지금은 차단 여부만 보므로 원인 표시가 바뀌어도 검출되지 않는다.

### G06R-04 / S2 / OPEN — G06이 추가한 fail-closed 가드 다수가 제거돼도 시험이 실패하지 않는다

검토자 변이에서 SURVIVED한 가드는 다음과 같다(§5).

| 변이 | 제거한 가드(근거 위치) | 계약 근거 | 다른 층의 방어 |
| --- | --- | --- | --- |
| A-M17 | Gateway가 매 write 전에 호출하는 비용 재검사(`gateway.py:197-212`, `:273`) | §3.3, §4.3 "가격 유효성은 reserve/open/각 write 전에 재검사 … first write 뒤 만료면 새 write를 막고" | 동의 철회는 `_write`의 `consents.validate`로 계속 막힌다. 비용 쪽(정책 version, 한도 축소, 가격 만료, 시계, 잔액)의 write 단계 차단은 Gateway 경로에서 검증되지 않는다. 작성자 M17 KILLED 주장과 대상 위치가 다르다(§5) |
| R02 | ledger 없는 Gateway가 `openai/anthropic/gemini`에 보내는 것을 막는 `LEDGER_REQUIRED`(`gateway.py:244-245`) | §3.3, S0 경로의 방어선 | 현재 앱은 `privacy.py:668`에서 원격에 항상 ledger를 넘긴다. 다른 생성 경로가 생기면 비용 검사 없이 전송된다 |
| R04 | 과소 예약 뒤 `COST_PLAN_UNDERESTIMATED` 차단(`ledger.py:735-736`) | §4.3 "다음 송신을 차단" | 없음. 실제 금액이 예약을 넘은 뒤에도 다음 송신이 허용된다 |
| R05 | 일반 모드의 명시 확인 필수(`cost.py:536-537`) | §2.1 | UI가 확인 창을 거쳐 `general_acknowledged`를 만든다. 비용 계층 가드는 시험되지 않는다 |
| R11 | high-water 영속(`ledger.py:291-292`) | §4.3 시계 역행 | 같은 인스턴스의 메모리 값만 남는다. 재시작 뒤 역행은 검출되지 않는다(G06R-01과 연결) |
| R01 | `reserve_quote`의 재계산 quote 일치 검사(`ledger.py:765-767`) | §3.3 "quote와 일치하는 요청을 원자 예약" | dispatch에서 재계산·비교하므로 위조 quote는 송신 전에 막힌다. 다만 위조 금액으로 **예약 승인(잔액 판정)** 이 이뤄진다 |

**기대**

- 각 가드에 단일 원인 시험을 둔다:
  - **Gateway 경로**에서 첫 write 뒤 가격 만료나 정책 version 변경이 일어났을 때 다음 write가 0이어야 한다.
  - ledger 없는 원격 Gateway
  - final > 예약 뒤의 다음 예약
  - ack 없는 general 정책
  - 시계 역행 뒤 재열기
  - 위조 quote의 reserve 거부
- 작성자 28 변이는 이 가드들을 포함하지 않았다.

### G06R-05 / S3 / OPEN — 다층 방어로 영향이 작은 변이 생존과 계획된 v2 동시 예약 시험의 부재

**영향이 작은 생존 변이**

- R03: open 단계의 `dispatch_id` 재사용 금지 제거(`ledger.py:913`). 상태 검사와 write의 `dispatch_id` 일치 검사가 남아 중복 송신은 막힌다.
- R08: USER_CAP dispatch의 모드 검사 제거(`:895-897`). reserve의 재계산 때문에 strict에서는 USER_CAP 행이 생기지 않는다.
- R09: UI reserve의 모델 대조 제거(`privacy.py:602`).
- R10: 같은 정책 version으로 한도를 바꾸는 것 허용(`ledger.py:590-592`). 옛 계획은 `amount_limit` 비교로 막힌다.
- 넷 모두 S0 경로가 열리지는 않았지만 해당 검사는 미검증 상태다.

**계획된 v2 동시 예약 시험의 부재**

- 계약 §7은 `test_cost_concurrent_reservations_have_one_winner`를 "v2에서 두 ledger/동일 계정 동시 예약"까지 확장한다고 했다. 그러나 `tests/unit/test_security.py`는 8e09b62와 같고 v1만 검사한다(`:256-270`). 신규 4파일에도 thread·process 경쟁 시험이 없다.
- 검토자 반례 `probe_concurrency.py`로 동작은 확인했다.
  - v2 `reserve_quote` 7/한도 10을 두 ledger 인스턴스의 16 thread로 경쟁: **승자 1, reserved 7**.
  - 4 process × 4회: **승자 1, reserved 7**, exit 0.
  - 같은 예약을 두 Gateway thread가 barrier로 동시에 보냄: `['OK', 'RESERVATION_NOT_DISPATCHABLE']`, **open 1회**, 300,000 B를 한 번만 보냄.
- 동작에는 결함이 없으나 회귀 시험이 없다.

### G06R-06 / S3 / OPEN — 비용 UI 표시와 안내의 누락

1. **과소 예약 차단 표시와 해제:**
   - 계정의 `blocked`(과소 예약)는 잔액 표시에 나오지 않는다(`privacy.py:786-829`, `account_snapshot`에 필드 없음).
   - "제공업체·통화·기간 한도 적용"을 누르면 `_cost_policy(advance=True)`로 version이 올라가고 `apply_policy`가 `blocked=0`으로 **조용히 해제**한다(`privacy.py:900-901`, `ledger.py:598-603`).
   - 계약 §4.3의 "계획 오류를 표시 … 명시 재설정 전 숨기지 않는다"에서 '표시'가 빠졌다. 해제가 같은 버튼의 부수효과라는 안내도 없다.
2. **일반 모드 확인 창의 누락 문구:** 확인 창(`privacy.py:721-733`)에는 계약 §5가 요구한 "중복 청구 위험"과 "이 선택은 전송 동의를 대신하지 않음"이 없다.
3. **예산 미적용 시의 오도:** 예산을 아직 적용하지 않은 통화·기간으로 실행하면 계정이 없어 `BUDGET_POLICY_CHANGED`가 표시된다(`ledger.py:728-734`). 실제로는 "적용 필요"인데 "정책 변경"으로 안내된다.

### G06R-07 / S3 / OPEN(실가격 최초 항목 게이트 인계) — catalog·상한 모델이 계약 §3의 일부를 표현하지 못한다

배포 catalog가 비어 있어 지금은 영향이 없다. 실제 가격 항목을 넣는 게이트의 전제로 기록한다.

- `PriceEntry`(`cost.py:198-291`)와 key(`:284-291`)에 다음이 없다: `billing_profile_version`, 최소 청구량·청구 증분, tier 최대 단가. 같은 key의 조직별 billing profile을 분리할 수 없다(§3.1).
- 텍스트 상한은 `text_bytes`(입력 UTF-8 bytes + 상수 overhead) 하나뿐이다(`cost.py:581-586`).
  - §3.2가 금지한 "토큰 <= bytes" 가정을 profile 종류로 고정했다.
  - Anthropic 메시지 수에 비례하는 framing이 반영되지 않는다(`:445-452`).
- Gemini STT의 음성 경로는 텍스트 part의 bytes를 버리고(`:485-487`) 출력 단가 0을 요구한다(`:591`). 프롬프트·출력이 과금되는 profile은 정확히 표현할 수 없다.
- 시험 전용 wire 프로토콜 `text-fixture-v1`·`audio-fixture-v1`·`opaque-fixture-v1`가 제품 `inspect_wire`에 있다(`:362-377`). `opaque`는 본문을 해석하지 않고 출력 한도를 1로 둔다. 리뷰 실수로 실제 항목에 쓰이면 과소 예약이 된다.

## 4. 중점 검토 항목별 판정

1. **S0 경로(fail closed, 순서, TOCTOU) — 반례 없음.**
   - 차단 시점: strict의 가격 미상·만료·상한 미검증, cap 0, 통화 불일치, catalog digest 불일치는 모두 `quote` 단계에서 예외가 된다. 따라서 `Run.request`가 Gateway를 호출하기 전에 막힌다(`_common.py:197-221`).
   - Gateway의 처리 순서:
     1. `permit`(동의)
     2. `check_reservation`
     3. consent → ledger lock 아래에서 `consents.validate`와 `validate_dispatch(open)`
     4. open
     5. 매 write마다 같은 lock 아래에서 `validate_dispatch(write)`
   - 원격 3사는 ledger가 없으면 `LEDGER_REQUIRED`다(단, R02 시험 공백).
   - privacy의 reserve는 동의 lock 안에서 binding을 확인한 뒤 quote·reserve를 수행한다(consent → ledger 순서).
   - 정책·잔액 재검사: 다음 항목은 reserve, open, 매 write 시점에 다시 검사된다.
     - 정책 version·한도: `apply_policy`가 version을 올리면 옛 계획은 `BUDGET_POLICY_CHANGED`
     - 기간
     - 가격 만료: `COST_QUOTE_EXPIRED`
     - 시계
     - 잔액
   - 위 재검사는 코드상 모두 존재한다. 다만 Gateway가 write마다 재검사를 호출하는 연결은 시험되지 않는다(A-M17, G06R-04).
   - 작성자 시험 AUX-P1·PRICE-TIME·BIND·ORDER는 R1b에서 PASS였고, 코드 읽기로 위 순서를 따로 확인했다. 실가격 catalog가 비어 있으므로 strict에서는 유료 원격이 모두 사전 차단된다(AUX-EMPTY-strict PASS).
2. **동시성 — 이중 지출 반례 없음(G06R-05 참조).**
   - 동시 예약은 프로세스 공용 RLock과 파일 lock 아래 `_verify` → 판정 → 쓰기로 원자적이다. 검토자 반례 `probe_concurrency.py`(thread·process·중복 dispatch)로 확인했다.
   - kill 뒤에는 RESERVED가 노출액으로 남는다(fail closed). release UI는 없고 확인 금액 0 정산으로만 해소된다. 이는 기존 동작이다.
   - witness 선행 crash 창의 빈도 증가는 G06R-02에 적었다.
3. **저장 — additive·fail closed 확인.**
   - v1 세 표는 DROP·ALTER 없이 그대로이고, 새 표는 4개다.
   - v2 witness는 v1 상태와 v2 표·스키마(PRAGMA)·meta를 함께 해시한다. 스키마 해시를 빼는 변이 R06은 KILLED됐다.
   - 구버전 앱은 schema_version 2 witness를 해석하지 못해 차단된다(DB-15).
   - 손상 행·타입 오류: witness 불일치는 `LEDGER_ROLLBACK_DETECTED`, 타입 오류는 `safe_operation`의 `SECURITY_STATE_UNAVAILABLE`로 막힌다.
   - 저장 범위:
     - 비밀: `cost_headers` allowlist(`content-type`, `anthropic-version`)로 인증 header가 `request_json`에 들어가지 않는다.
     - 본문: hash와 길이만 저장한다.
     - 내보내기·진단: `security.sqlite`를 다루는 코드는 없다(grep).
   - 결함은 시계 영속(G06R-01)이다.
4. **정책 snapshot — 확인.**
   - `config_key`에서 비용 cap과 한도가 제거됐다(`privacy.py:511-521`, 시험 `test_user_cost_edit_revokes_old_binding_without_changing_result_identity`).
   - cap·한도·모드·통화·기간 위젯을 편집하면 `_changed`가 동의를 철회한다. 따라서 옛 계획은 `CONSENT_REVOKED`로 막힌다.
   - signal을 막은 메모리 변경에서도 worker는 고정 snapshot을 쓴다(UI-0xx, 작성자 M27).
   - 같은 설정이면 결과 키가 같아 재전송이 없다는 G02A-05 결정과 일치한다.
5. **UI — 판정과 표시의 출처가 같다.**
   - 표시는 worker가 받은 실제 `CostQuote` 또는 오류 코드를 signal로 보여 주고 "마지막 요청 기준(현재 설정과 다를 수 있음)"이라고 밝힌다.
   - 실행은 표시가 아니라 snapshot을 읽으므로 오래된 표시로 실행되는 경로는 없다.
   - 결함은 G06R-06이다.
6. **시험 충분성.**
   - case ID 4834는 완전하고, 시간은 74.33s로 120초 예산 안이다.
   - 독립 oracle:
     - TEXT는 Fraction 손계산이다.
     - STATE는 SQL과 무관한 자동자로, 모든 행을 재열기한다.
     - 둘 다 구현 산식을 import하지 않음을 확인했다.
   - 공백: 정확한 코드 oracle 부재(G06R-03), 가드 시험 공백(G06R-04), 대용량·이력 성능 시험 부재(G06R-02), 재시작 시계 시험 부재(G06R-01).
7. **회귀·정적 검사 — 통과(R1b, R4).**

## 5. 변이(R6)

작성자 diff를 재사용하지 않고 검토자가 직접 작성했다.

- 변이마다 사본에서 한 곳만 바꾸고 결과를 기록한 뒤 원래대로 되돌렸다. 바꿀 패턴이 정확히 1회 나오는지 확인했다.
- 사본 import 경로는 `build/review-trees/g06a-mut/src/recoryn/security/ledger.py`였다.
- 선택 10파일: 신규 4파일, `test_gateway`, `test_provider_contracts`, `test_privacy_ui`, `test_security`, `test_egress_independent`, `test_provider_security_independent`.
- 정상본은 **5068 passed**다.
- harness와 결과는 `build/review-trees/g06a-probe/`에 보존했다(LF SHA256):
  - `mutate.py` `60ed128c86f64e8be873e045f68a8489a75220c7e8c2ce8988aae50978429dbf`. 최종본이며, R01~R12 패턴은 첫 실행 뒤 바꾸지 않고 R13~R15와 A-M*만 추가했다.
  - `mutations1.json` `82190cee7475b990e6d648574122a183986a3533fe4e10a6f3046611feb0d442`
  - `mutations2.json` `cc453ec449961845dff182429451aeec7c1f6211cd193d937194f945289e3945`
  - `mutations3.json` `5cc12b83219b1e753dc9af17f8363d87c082de3c208478010bdd58c0edf94e57`
  - 각 실행 로그 `mutate*.log`

| ID | 변이 | 결과 / 첫 실패 node |
| --- | --- | --- |
| R01 | `reserve_quote`의 재계산 quote 일치 검사 제거 | **SURVIVED**(5068 passed) → G06R-04 |
| R02 | Gateway의 원격 3사 ledger 필수 제거 | **SURVIVED** → G06R-04 |
| R03 | open의 `dispatch_id` 재사용 금지 제거 | **SURVIVED** → G06R-05 |
| R04 | `COST_PLAN_UNDERESTIMATED` 차단 제거 | **SURVIVED** → G06R-04 |
| R05 | general 모드 ack 필수 제거 | **SURVIVED** → G06R-04 |
| R06 | witness 상태에서 PRAGMA 스키마 제외 | KILLED, `test_gateway.py::test_real_process_restart_denies_old_consent_and_preserves_unknown` |
| R07 | usage 이벤트 통화 검사 제거 | KILLED, `G06-EVENTS-024` |
| R08 | USER_CAP dispatch의 모드 검사 제거 | **SURVIVED** → G06R-05 |
| R09 | UI reserve의 모델 대조 제거 | **SURVIVED** → G06R-05 |
| R10 | 같은 version의 한도 변경 허용 | **SURVIVED** → G06R-05 |
| R11 | `_change`의 high-water 영속 제거 | **SURVIVED** → G06R-01, G06R-04 |
| R12 | 다른 기간의 UNKNOWN을 미정산 판정에서 제외 | KILLED, `G06-PERIOD-012` |
| R13 | `COST_CAP_REQUIRED` → `COST_CAP_EXCEEDED` | **SURVIVED**(5068 passed) → G06R-03 |
| R14 | `COST_UNRESOLVED_EXPOSURE` → `BUDGET_EXCEEDED` | **SURVIVED** → G06R-03 |
| R15 | 기간 밖 `COST_PERIOD_CHANGED` → `BUDGET_POLICY_CHANGED` | **SURVIVED** → G06R-03 |

작성자 28 변이 가운데 같은 의도의 4개(M09·M17·M18·M28)는 검토자가 별도로 작성해 아래와 같이 실행했다.

| ID | 변이 | 결과 |
| --- | --- | --- |
| A-M09 | 계정 잔액에서 UNKNOWN 제외 | KILLED, `G06-BALANCE-012`(작성자와 같은 행) |
| A-M17 | Gateway write의 비용 재검사 생략(`gateway.py:273` `write_remaining` → `remaining`) | **SURVIVED**(5068 passed) → G06R-04 |
| A-M18 | 첫 write 전 `mark_unknown` 제거(`gateway.py:330`) | KILLED, `G06-BIND-000`(작성자는 ORDER-035) |
| A-M28 | `_now`의 high-water 비교 제거(`ledger.py:174-175`) | KILLED, `G06-PRICE-TIME-003`(작성자는 PRICE-TIME-018) |

A-M17은 작성자 표의 M17("각 write의 비용 재검사 생략", PRICE-TIME-044 KILLED)과 의도가 같지만 결과가 반대다. 원인은 시험 구조에 있다. PRICE-TIME의 second-write 행은 `ledger.validate_dispatch(..., phase="write")`를 **직접** 호출한다(`tests/integration/test_cost_cap.py:474-491`, `wire`는 Gateway 없이 직접 조작). 따라서 ledger 함수의 write 분기는 시험되지만, Gateway가 실제로 매 write마다 그 함수를 호출하는 연결은 어떤 시험으로도 검출되지 않는다. 작성자의 M17은 ledger 쪽을 바꾼 변이로 보인다.

## 6. 반례를 찾지 못한 영역과 미검증 범위

- **반례를 찾지 못한 영역:**
  - 무동의·무예약 원격 전송
  - 다른 body·endpoint·data_type·header로의 retarget(BIND)
  - 예약 뒤 정책·한도·기간·가격 변경 후의 송신
  - 통화 혼합
  - 다른 기간 미정산 우회
  - 이벤트 중복·역순·상충
  - legacy 자동 승격
  - v2 표 손실 은폐
  - 구버전 앱의 v2 DB 사용
  - 동시 이중 지출
  - 같은 예약의 중복 dispatch
- **이번에 검증하지 않은 범위:**
  - 실제 가격, 공급자 청구, 환율
  - 실제 네트워크·TLS 업로드 시간(G06R-02는 네트워크 0초 조건의 하한이다)
  - 전원 손실 내구성
  - Windows 절전·최대 절전에서 monotonic deadline의 동작
  - Gemini STT inline JSON의 대용량 시간(OpenAI multipart만 측정)
  - 실제 사용자 dual boot 시계 환경(G06R-01은 시계를 주입해 재현)
  - G-P09 정본 migration과 backup 상호작용
  - 접근성(읽기 도구·키보드)으로 본 신규 비용 위젯
  - 작성자 변이 28개 중 위 4개를 제외한 24개는 재실행하지 않았다

## RECHECK 1 — 2026-11-23, 같은 검토자(Claude, G-P06 독립 검토)

C00이 G-P06 FIX1(작성자 w5:p8 Codex)의 재확인을 요청했다. 위 1차 내용(LF SHA256 `d947a628…`)은 이력으로 보존한다.

**판정: G06R-01~06 6건 모두 RECHECKED. G06R-07은 C00이 지정한 부분(시험 전용 wire 프로토콜 차단)은 RECHECKED, 나머지는 통합 계획에 인계됐다.**

- 새 OPEN은 2건이며 모두 S3다(G06R-08, G06R-09). 새 S0·S1·S2는 없다.
- 1차의 원 반례(미래 high-water 뒤 앱 시작, 10분·5분 STT, 20 MiB·이력 1000행 이상)는 모두 닫혔다.
- 검토자 변이 R01~R15와 A-M17은 16/16 KILLED다.

### RC1-1. 입력과 범위

- 대상 tree는 **`840f5961605f1ea1babf3860e68f62cce0e9937a`**(`git cat-file -t` = tree)다. 새 기준은 HEAD **`6072ef1dfbb5c69490812ca1b103e248dbf78743`**(G-P04·GT-P03·GT-P04·G-P05·G-P05b 포함)다.
- `git diff --stat 6072ef1 840f5961`의 결과는 **27파일, 6521 insertions / 159 deletions**다.
  - 승인 30파일(1차 29 + `src/recoryn/ui/main.py`)과 대조했다. **범위 밖 변경은 0건이다.**
  - 바뀌지 않은 승인 파일은 3개다: `ui/ai_bridge.py`, `tests/unit/test_security.py`, `tests/integration/test_ai_independent.py`.
  - `ui/main.py`의 변경은 `-CostLedger(...)` → `+CostLedger.open_for_ui(...)` 한 줄(+1/−1)뿐이다(`src/recoryn/ui/main.py:118`).
- 1차 이후의 수정은 G-P06 경로로 한정한 `git diff 5317e250 840f5961 -- <27파일>`로 봤다. 제품 쪽 변경은 `security/ledger.py`(+408), `ui/privacy.py`, `security/gateway.py`, `security/cost.py`, `security/cost_catalog.py`, `providers/_common.py`다. 이 diff에 `ui/main.py`가 +367로 잡히는 것은 기준 차이(G-P05) 때문이며, 6072ef1 대비 변경은 위 한 줄이다.
- 계약 문서 LF SHA256은 `45fd8b82c9987e471b4d50726180493429166e04c8f1b2e10fcdcf0107e1f238`로 배정값과 일치한다. §16.5 표의 Python 26파일은 **26/26 일치**한다.
- 작업 트리의 27파일도 tree와 LF 차이가 0이다(검토 시점).
- 추출과 실행 위치(작업 트리 `src`로는 판정하지 않음):
  - 판정·전체 시험: `git archive 840f5961 | tar -x -C build/review-trees/g06b`
  - 기준 비교: `git archive 6072ef1 | tar -x -C build/review-trees/g06b-base`
  - 변이: `build/review-trees/g06b-mut`
  - basetemp: `build/review-trees/g06b-bt/*`
  - 반례 스크립트: `build/review-trees/g06b-probe/*`
  - 모두 `.gitignore` 대상이다. 저장소 쓰기는 이 절 추가뿐이다.

### RC1-2. 직접 실행

모든 pytest는 cwd를 사본으로 두고 실행했다. 공통 조건: `PYTHONPATH=g06b/src`(editable `.pth` 우회), offscreen, `PYTHONDONTWRITEBYTECODE=1`, `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, `-p no:cacheprovider`, `-W error::ResourceWarning`, `-W error::pytest.PytestUnraisableExceptionWarning`, 새 basetemp.

| # | 명령 | 결과 |
| --- | --- | --- |
| RR1 | 전체 `pytest -q -rs --junitxml …/g06b-full.xml` | **14848 passed, 2 skipped, 663.21s, exit 0**. testcase 14850, failure·error 0. UI 500, G-P05 pending deletion 395, G06 신규 4908 포함. 2 skip은 1차와 같은 `test_gpu_smoke.py:107` 8.3 이름 환경 skip이다(작성자 14850 PASS와의 차이는 이것뿐) |
| RR2 | 신규 4파일 단독 | **4908 passed, 86.45s**. 120초 예산 안. RR1 안의 4파일 testcase 합은 90.10s |
| RR3 | `audit_ids.py g06b-full.xml` | 의미 행 **4834 고유, 누락·중복·추가 0**(zero-padding 관례만 다름). 비가족 node 74(작성자 주장과 같음) |
| RR4 | `ruff check --no-cache .` / `ruff format --check --no-cache .` / `mypy src/recoryn scripts packaging` | All checks passed / **168 files** already formatted / **86 source files** no issues |
| RR5 | 반례 스크립트 10개(RC1-3) | 아래 표 |
| RR6 | `python -I mutate_g06b.py mutations_g06b.json`(사본별 1변이, `-x`, 1차와 같은 선택 10파일, 정상본 **5116 passed**) | **29변이 중 26 KILLED / 3 SURVIVED**, invalid 0 |

증거의 LF SHA256은 다음과 같다.

- 시험 결과: `g06b-full.xml` `b93df217f2146aedff688941ae945043e9fee5a7aed22f202036021015288468`, `g06b-new4.xml` `8f7c84b49ee5c1bf350891cacdacd14d0b3f23fdf2fee85b4f2f528d5ce0dd44`
- 반례 스크립트와 변이 결과(`build/review-trees/g06b-probe/`):

| 파일 | LF SHA256 | 비고 |
| --- | --- | --- |
| `probe_common.py` | `f8de1171556355325245d6d12acf580aa672d8b33a07b9f4d5b62d0274c49c56` | 1차본에서 COPY를 g06b로 바꾸고, 시험과 같은 방식의 test loader 주입을 추가했다(production loader가 fixture 프로토콜을 거부하므로) |
| `probe_recheck_clock.py` | `2b211ef0e4280b8c956f11f13f95125ac4b329b4e25c3e814cfa37ca4eea85d8` | |
| `probe_recheck_delete.py` | `ee8c4fc529f4c65321e8ff2c88a6faaa53ffee335a33e3218b9e2432d14cf95c` | |
| `probe_recheck_boundary.py` | `b178fc9d2db60606f9ee62dbc23532773bf21757f65291f31da62d760cf3ccf5` | |
| `probe_recheck_verify_count.py` | `cd972a4c413ca322305d3d24b707d77b02eecb3889ebe603a2eb0a172b581bae` | |
| `probe_recheck_midwrite_tamper.py` | `9172a4bf7f97c9979d846c902cde08f25b5e9a21d979aec053dd995192726ed4` | |
| `probe_perf_base.py` | `3a8b44eef4761ff85c41b064753071ea6fe8dab0b43db90c86b10af63d1d9d94` | 기준 경로만 g06b-base로 바꿨다 |
| `probe_perf.py`, `probe_perf_openai.py`, `probe_concurrency.py`, `audit_ids.py` | 1차와 같음 | |
| `mutate_g06b.py` | `8de85ec31bd55e4d93a61319cc555265fa4f434543d1d2522cf072039708ea62` | |
| `mutations_g06b.json` | `266963975d7a314df34b9b8b5cc50aefa1aaa3ae6e7bcd04f7d0e9f49f3ced8b` | |
| `mutate_g06b.log` | `b3c08cf6eadefbc0437834887b744b1e511914dda27bf565c207e340c6a271c5` | |

### RC1-3. 원 반례 재실행과 새 위험 탐색

| 반례(스크립트) | 관측 |
| --- | --- |
| A. 미래 1시간 high-water / 깨진 witness → MainWindow와 fake 장치 녹음(`probe_recheck_clock.py`) | 두 장애 모두 `MainWindow=CONSTRUCTED`, `record_enabled=True`. 시작→정지 뒤 **세션 FINALIZED, frames 48**. `availability`는 `COST_CLOCK_INVALID` / `LEDGER_ROLLBACK_DETECTED`였다. 잔액란에 "유료 원격 전송 차단"이 표시됐다. 시계 재설정 버튼은 시계 장애에서만 활성이다. 작성자 시험은 버튼 활성만 보지만 이 반례는 실제 녹음 완료까지 확인했다 |
| B1. 시계 교정 직후 | ledger 열기 OPENED. `quote_request`와 `apply_policy`는 `COST_CLOCK_INVALID`. `reset_clock(confirmed=False)`도 `COST_CLOCK_INVALID` |
| B2. 재설정 | `reset_clock(confirmed=True)` 뒤 `availability=None`. 감사 행 `{"event_id":…,"previous_high_water":5000.0,"utc":2500.0}`이 meta_v2에 남는다. 이 행은 witness 해시 대상이다 |
| B3. 지출 보존 | 과거 기간 확정 40 + 시계가 앞섰을 때 쓴 "미래" 기간 확정 30이 있다. 재설정 뒤 현재 기간 계정은 **confirmed 70, available 30**이다. 이어서: 60 예약 `BUDGET_EXCEEDED` → 30 예약과 Gateway 전송 OK(정확히 100) → 시계를 더 되돌려 **두 번째 재설정**을 해도 노출액이 같다 → 30 추가 예약 `BUDGET_EXCEEDED`. **재설정 반복으로 상한을 우회하지 못한다** |
| B4. 미래 기간의 UNKNOWN | 재설정 뒤에도 현재 기간 예약이 `COST_UNRESOLVED_EXPOSURE`로 막히고, 미래 기간 UNKNOWN 30이 보존된다 |
| C. 만료 가격 | 시계 3500(가격 valid_until 3000)에서는 `COST_PRICE_EXPIRED`다. 2500으로 되돌리면 `COST_CLOCK_INVALID`, **재설정 뒤에는 OK** → G06R-08 |
| D. 구 G06 reader | 재설정한 DB를 1차 tree(5317e250) 코드로 열면 `LEDGER_ROLLBACK_DETECTED`(fail closed) |
| 10분·5분 OpenAI multipart STT(배포 경로: 빈 catalog, 일반 USER_CAP), `probe_perf_openai.py` | 10분: 이력 0 / 1200 / 3000에서 **293/293 OK**(0.19 / 0.30 / 0.76s). 5분: 이력 0 / 1200에서 **147/147 OK**. **REMOTE_OUTCOME_UNKNOWN 0** |
| 20 MiB VERIFIED opaque(`probe_perf.py`) | 이력 0 / 1000 / 2000 / 5000에서 **320/320 OK**(0.30 / 0.47 / 0.66 / 1.34s). 기준 6072ef1(v1 ledger)은 0.23 / 0.24s |
| write 비용 분리(`probe_recheck_verify_count.py`, 20 MiB) | 이력 0 / 1200 / 5000에서 write 검사 평균 **0.121 / 0.121 / 0.120 ms**(이력과 무관한 상수). dispatch당 전체 재인증은 **9회**, witness 게시는 **2회**(claim, 최초 UNKNOWN)로 본문·이력과 무관하다. 이력에 따른 증가는 요청당 고정 비용이다(5000행에서 1 MiB 0.79s, 20 MiB 1.34s) |
| multipart·WAV 경계(`probe_recheck_boundary.py`) | 조각 경계를 multipart 첫 part 끝, file part 머리, WAV 44 B 헤더 끝, 소수 4093 B, 본문 전체에 맞췄다. **송신 byte 열이 quote 본문과 정확히 같고**(`sent_equals_body=True`) write 수는 ceil(len/chunk)와 같다. 1 B 조각은 G-P02의 30초 permit lease(`consent.py:783`)로 46,297/96,441에서 `PERMIT_REVOKED` 중단됐다. 순서대로 slice를 보내므로 송신분은 본문의 접두부이고 초과 전송은 없다(G06와 무관한 기존 동의 경계). 직접 API 부정: 같은 내용의 다른 bytes 객체 `COST_QUOTE_MISMATCH`, `bytes_sent=len+1` `COST_PLAN_UNDERESTIMATED`, `None`·`True` `COST_REQUEST_INVALID` |
| 동시성(`probe_concurrency.py`) | thread 승자 1·reserved 7, process 4×4 승자 1·reserved 7·exit 0, 중복 dispatch `['OK','RESERVATION_NOT_DISPATCHABLE']`·open 1 |
| G-P05 결합(`probe_recheck_delete.py`) | 실제 Library 세션으로 첫 write 직후 `revoke_session` + `delete_session`을 실행했다(MainWindow 삭제 worker 순서): `SESSION_REVOKED outcome_known=False`, **writes 1/5**, 삭제 `DELETED_LOCAL`, UNKNOWN 60 보존. 재열기 뒤 늦은 final 40으로 원 계정 confirmed 40. 시계·무결성 장애 ledger 상태에서도 세션 삭제는 `DELETED_LOCAL`로 완료됐다. MainWindow의 삭제·재시도 경로(`ui/main.py:775`, `:1017`)는 동의만 쓰고 ledger를 호출하지 않는다 |
| dispatch 중 외부 DB 변경(`probe_recheck_midwrite_tamper.py`) | 첫 write 뒤 별도 sqlite 연결로 예약액을 바꾸면 다음 write에서 `LEDGER_ROLLBACK_DETECTED`, writes 1/5. 정상본은 막지만 시험이 없다 → G06R-09 |

### RC1-4. 변이 재적용(RR6)

1차 변이는 의도를 유지하고 패턴만 새 위치로 옮겼다. 정상본 5116 passed 뒤 실행했다.

| 변이 | 결과 / 첫 실패 node |
| --- | --- |
| R01 위조 quote 예약 | KILLED, `test_reservation_admission_rejects_forged_quote_before_creating_a_row` |
| R02 ledger 없는 원격 | KILLED, `test_gateway_requires_ledger_and_refuses_underestimated_account` |
| R03 open claim 재사용 | KILLED, `test_reserved_dispatch_claim_is_exclusive_before_the_first_write` |
| R04 과소 예약 차단(입장 위치만) / R04b(입장·write 둘 다) | KILLED / KILLED(`G06-FIX1-WRITE-underestimate`) |
| R05 general ack | KILLED |
| R06 스키마 witness | KILLED, `test_witness_authenticates_empty_table_schema_as_well_as_rows` |
| R07 usage 통화 | KILLED, `G06-EVENTS-024` |
| R08 USER_CAP 모드 | KILLED, `test_gateway_rejects_stored_user_cap_in_strict_policy_even_with_valid_witness` |
| R09 UI 모델 대조 | KILLED, `test_worker_model_scope_rejection_has_its_own_code` |
| R10 같은 version 한도 변경 | KILLED, `test_same_version_cannot_change_limit_or_clear_spending` |
| R11 high-water 영속 | KILLED, `test_restart_clock_high_water_and_explicit_reset_keep_future_spending` |
| R12 다른 기간 UNKNOWN | KILLED, `G06-PERIOD-012` |
| R13 / R14 / R15 코드 바꿔치기 | KILLED(`G06-FIX1-CODE-COST_CAP_REQUIRED` / `G06-PERIOD-010` / `G06-PERIOD-000`) |
| A-M17 Gateway write 재검사 연결 | KILLED, `G06-FIX1-WRITE-expiry` |
| A-M09 UNKNOWN 잔액 제외 | KILLED, `G06-BALANCE-012` |
| N02 write 누적 byte 상한 | KILLED |
| N04 확인 없는 재설정 | KILLED |
| N05 재설정 뒤 전 기간 합산 제거 | KILLED |
| N06 write의 새 미정산 무시 | KILLED |
| N07 fixture 프로토콜 허용 | KILLED, `G06-FIX1-CATALOG-text-fixture-v1` |
| N08 write의 정책 version 무시 | KILLED |
| N09 write의 만료 무시 | KILLED, `G06-PRICE-TIME-044` |
| N11 write의 시계 무시 | KILLED, `G06-PRICE-TIME-008` |
| **N01** write의 본문 identity·메타 대조 제거(`ledger.py:1161`) | **SURVIVED** → G06R-09 |
| **N03** 변경 stamp 뒤 전체 재인증 생략(`ledger.py:401`) | **SURVIVED** → G06R-09 |
| N10 `_change` 뒤 dispatch 잔액 선계산 제거(`:422-423`) | SURVIVED. **등가 변이**다: `_change`가 cache를 비우고 `_validate_write`가 없으면 다시 계산한다(`:1204-1207`). 결함으로 세지 않는다 |

작성자의 변이 46개와 수명 2개는 재실행하지 않았다.

### RC1-5. 1차 발견 상태

| ID | 상태 | 근거 |
| --- | --- | --- |
| G06R-01 / S1 | **RECHECKED** | 반례 A·B·D. v2 열기는 시계 역행으로 실패하지 않는다(`ledger.py` 생성자의 `_ensure_clock_audit`). 무결성 실패는 `open_for_ui`가 비용 전용 불능 객체로 격리한다. 녹음이 실제로 완료된다. 유료 경로는 `COST_CLOCK_INVALID`로 차단된다. 명시 확인 재설정(UI 기본 No)이 감사를 남기고 지출을 줄이지 않는다. R11·N04·N05 KILLED |
| G06R-02 / S1 | **RECHECKED** | 10분·5분 STT와 20 MiB, 이력 0~5000에서 REMOTE_OUTCOME_UNKNOWN 0. write 검사는 이력과 무관하게 0.12 ms이고, 전체 재인증·witness·fsync는 요청당 고정 횟수다 |
| G06R-03 / S2 | **RECHECKED** | 신규 COST 15코드가 모두 assert된다(파일 합계 2~12회). R13~R15 KILLED |
| G06R-04 / S2 | **RECHECKED** | R01·R02·R04·R04b·R05·R11·A-M17 모두 KILLED. 공개 Gateway 경로 시험(`G06-FIX1-WRITE-*`)이 추가됐다 |
| G06R-05 / S3 | **RECHECKED** | R03·R08·R09·R10 KILLED. `test_v2_thread_reservations_and_duplicate_dispatch_have_one_winner`, `test_v2_separate_process_reservations_have_one_winner`가 추가됐다 |
| G06R-06 / S3 | **RECHECKED** | 과소 예약 표시와 한도 적용 뒤 유지(`apply_policy`의 `blocked=0` 제거, `tests/ui/test_cost_cap_ui.py:315-319`), 확인 창의 "중복 청구 위험"·"전송 동의를 대신하지 않습니다"(`:232`), 계정 부재 `BUDGET_REQUIRED`와 "예산 미적용"(`:304-308`) |
| G06R-07 / S3 | **RECHECKED(차단 부분) / 인계** | production `load_catalog`가 세 fixture 프로토콜을 `COST_BOUND_UNVERIFIED`로 거부한다(`cost_catalog.py:14-18`, N07 KILLED). billing profile version·최소 청구량/증분·텍스트 framing·Gemini 음성 과금은 `docs/implementation/v1-gap-plan.md:76`의 '첫 항목 전 게이트'에 기록됐다. 표현 한계 자체는 남아 있으므로 CLOSED 여부는 C00이 판단한다 |

### RC1-6. 새 발견

#### G06R-08 / S3 / OPEN(실가격 첫 항목 게이트 인계) — 시계 재설정이 이전 high-water 기준으로 이미 만료된 가격을 다시 유효하게 만든다

- **재현:** `probe_recheck_clock.py` C행. 시계 3500에서 `valid_until=3000` 가격은 `COST_PRICE_EXPIRED`다. 시계를 2500으로 되돌리면 `COST_CLOCK_INVALID`이고, `reset_clock(confirmed=True)` 뒤에는 같은 요청이 VERIFIED로 예약된다.
- **근거:** `reset_clock`이 high-water를 현재 시각으로 내린다(`ledger.py:232-258`). 가격 유효성은 현재 시각으로만 판정된다(`cost.py`의 `quote`, `ledger.py`의 `_validate_write`).
- **영향:** 배포 catalog가 비어 있어 현재는 없다. 실제 가격 항목이 생기면, 사용자가 뒤처진 시각을 확인해 재설정한 경우 오래된 가격으로 strict VERIFIED 상한이 계산될 수 있다. 시계 자체를 신뢰할 수 없다는 계약 §4.3의 한계 안에 있다. 확인 창(`privacy.py`의 reset 확인)은 지출 보존만 설명하고 가격 판정 시각이 바뀐다는 점은 말하지 않는다.
- **기대(첫 가격 항목 게이트):** 재설정 감사의 `previous_high_water`보다 이른 시각에는 가격 유효 판정을 하지 않는다(재설정 이후 strict VERIFIED는 가격 `valid_from`이 이전 high-water 이후인 항목만 허용하거나 재검토 요구). 아니면 확인 창에 이 영향을 명시한다.

#### G06R-09 / S3 / OPEN — FIX1이 추가한 write 단계 방어선 두 개에 대응 시험이 없다

- **N01 SURVIVED:** `_validate_write`의 본문 identity와 (reservation, provider, target, data_type, operation, headers) 대조(`ledger.py:1161-1176`)를 제거해도 5116 passed다.
  - 정상본은 같은 내용의 다른 bytes 객체를 `COST_QUOTE_MISMATCH`로 거부한다(RC1-3 경계 반례).
  - Gateway는 open과 write에 같은 인자를 넘기므로 현재 Gateway 경로로는 도달하지 않는다. 직접 API 방어선만 무시험이다.
- **N03 SURVIVED:** stamp 변화 뒤의 전체 재인증(`ledger.py:400-402`)을 생략해도 통과한다.
  - 정상본은 dispatch 중 외부 연결의 DB 변경을 다음 write에서 `LEDGER_ROLLBACK_DETECTED`로 막는다(RC1-3).
  - 계약 §14.1의 "revision 변경 시에만 전체 무결성과 노출 요약을 재인증"이 시험되지 않는다. 생략되면 dispatch 도중의 변조·rollback과 다른 연결의 미정산·legacy 변화가 cache로 가려질 수 있다.
- **부수 관찰:** `test_v2_separate_process_reservations_have_one_winner`의 자식 프로세스(`tests/integration/test_cost_cap.py:1684-1727`)는 `env=os.environ.copy()`로 실행되고 import 경로를 assert하지 않는다. 이 venv처럼 editable `.pth`가 있는 환경에서 PYTHONPATH를 고정하지 않으면 작업 트리 코드를 시험할 수 있다(RR1은 고정해 실행했다).
- **기대:** 직접 API의 다른 본문 객체·메타 부정 행, dispatch 중 외부 변경(변조/다른 연결의 정산·legacy 생성) 뒤 다음 write 0과 정확한 코드 행을 추가한다. 자식 프로세스는 import 경로를 확인한다.

### RC1-7. 관찰(발견 아님)

- 재설정은 1회만 해도 그 제공업체·통화의 예산 판정이 **영구히 전 기간 누적 확정액 기준**이 된다(`ledger.py:761-773`). 확인 창이 이를 밝히고 있고 C00 결정("이미 쓴 금액을 줄일 수 없게")과 일치한다. 되돌리는 경로는 없다.
- 과소 예약 `blocked`는 이제 같은 기간 안에서 해제할 방법이 없다. 새 기간 계정은 영향을 받지 않는다. 보수적이며 표시된다.
- `open_for_ui`가 만든 불능 객체는 그 실행 세션 동안 재시도하지 않는다. 일시적인 I/O 실패도 재시작 전까지 비용 기능을 막는다. fail closed이며 녹음에는 영향이 없다.
- 불능 객체의 `validate_dispatch(phase="write")`는 `_witness` 속성이 없어 `AttributeError`가 날 수 있다. 그러나 open 단계가 먼저 `SecurityError`로 막히므로 도달 경로는 없다.
- 요청당 고정 비용(전체 재인증 9회)은 이력에 비례한다. 5000행에서 약 0.75s이고, 이보다 훨씬 큰 이력의 30초 기한 여유는 측정하지 않았다.

### RC1-8. 미검증 범위

- 실제 네트워크·TLS 업로드 시간, 전원 손실 내구성(이제 요청당 witness 2회)
- Windows 절전 중 monotonic deadline
- Gemini inline JSON 대용량 시간
- 실제 dual boot 시계
- G-P09 migration(`clock_reset_audit` 열·witness 확장 인계)
- 접근성
- 작성자 변이 46개와 수명 2개의 재실행
- 5000행을 넘는 이력의 요청당 고정 비용

## RECHECK 2 (FIX2) — 2026-11-23, 같은 검토자(Claude, G-P06 독립 검토)

C00이 FIX2(작성자 w5:p8 Codex, CI 커버리지 예산 실패 수정)의 짧은 재확인을 요청했다. 위 1차·RECHECK 1 내용(LF SHA256 `6af59281…`)은 보존한다.

**판정:**

- CI와 같은 커버리지 명령과 `check_coverage`가 모든 묶음에서 PASS다. coverage 분모에 tmp 사본은 0개다.
- 보강 181행은 실제 oracle(앵커 고정 정확 코드·금액·상태·witness 불변)로 판정한다. 검토자 변이 15개 중 14개를 보강 행만으로 잡았다.
- fixture 변경은 옛 원문 hash 검사와 legacy adoption 시험의 의미를 유지한다.
- RECHECK 1의 G06R-09는 RECHECKED다.
- **새 OPEN은 S3 1건(G06R-10)**이다. 새 S0·S1·S2는 없다. 앞선 G06R-08(S3, 실가격 게이트 인계)은 이번 수정 범위 밖이라 그대로 OPEN이다.

### RC2-1. 입력과 범위

- 대상 tree는 **`e58f3b616a5ef0d8aba9fdfbe3df20514711e948`**(`git cat-file -t` = tree)다. 기준은 HEAD **6072ef1**이다.
- `git diff --stat 840f5961 e58f3b61`의 결과는 **3파일**이다: `docs/testing/g06-cost-cap-cases.md` +128, `tests/integration/test_cost_cap.py` +476, `tests/unit/test_cost_cap.py` +561.
  - `git diff --quiet 840f5961 e58f3b61 -- src`가 성공한다. **제품 코드 변경은 0이다.**
  - 6072ef1 대비로는 27파일이다.
- 계약 문서 LF SHA256은 `d8823f466184281bdc4d2201ab31c471aee391a52cf30921e99af46244563aa5`다. §17.7 표의 Python 26파일 해시는 **26/26 일치**한다.
- 추출 위치: `git archive e58f3b61 | tar -x -C build/review-trees/g06c`. 변이 사본은 `g06c-mut`, basetemp는 `g06c-bt`, 스크립트는 `g06c-probe`다.

### RC2-2. CI 커버리지 명령 = 전체 회귀(RR1)

- cwd는 g06c다. `.github/workflows/core.yml`의 "Offline core tests" 단계와 같은 옵션에 `PYTHONPATH=g06c/src`, 고유 basetemp, `--junitxml`, `-rs`만 더했다:

  ```text
  pytest -q -p no:cacheprovider -W error::ResourceWarning --cov=recoryn --cov-branch --cov-report=term-missing --cov-report=json:<json> --cov-fail-under=85
  ```

- 결과: **15029 passed, 2 skipped, 753.17s, exit 0**. testcase는 15031이고 failure·error는 0이다.
  - 2 skip은 앞선 회차와 같은 `test_gpu_smoke.py:107` D: 볼륨 8.3 환경 skip이다. 작성자의 15,031 PASS와 다른 점은 이것뿐이다.
  - 출력은 "Required test coverage of 85% reached. Total coverage: 92.53%"였다.
- `python scripts/check_coverage.py <json>`(exit 0) 출력 전문:

  ```text
  domain: line=100.00%/95% branch=100.00%/90% PASS
  capture: line=99.85%/95% branch=98.57%/90% PASS
  jobs: line=98.89%/95% branch=97.47%/90% PASS
  storage: line=96.30%/95% branch=91.56%/90% PASS
  security: line=98.11%/95% branch=94.43%/90% PASS
  content: line=99.59%/95% branch=98.75%/90% PASS
  all: line=93.95%/85% branch=88.20%/80% PASS
  ```

- coverage.json의 측정 파일은 **73개, 모두 `src/recoryn/` 아래**다. `ledger-v1`·`_g06_v1`·fixture·Temp 경로는 **0개**다. 수치는 작성자 §17.5와 같다.
  - `cost.py` 349/350문장·161/162분기
  - `ledger.py` 647/662문장·228/246분기
- ID 감사:
  - JUnit에서 의미 행 **4834 고유, 누락·중복·추가 0**을 확인했다.
  - **G06-COV2 181개 고유, 중복 0**이다. 가족별 수는 REQ 16, POLICY 7, PRICE 28, HEADERS 6, CURRENCY 3, CLOCK 9, CATALOG 3, WIRE 51, QUOTE 10, POS 7, WRITE 14, EXTERNAL 4, OPEN 5, TYPED 4, CACHE 1, OLDV2 1, IO 2, WITNESS 3, AVAILABILITY 1, CLOSED 1, USAGE 4, MANIFEST 1이다. §17.2·§17.3 계획과 같다.
  - 신규 4파일은 5089 node다.
- 증거 LF SHA256:
  - `build/review-trees/g06c-full.xml` `1dc6b2dea00066c6d474dd4e3b061c6826df7935736d0c656aa0a0406e8260d6`
  - coverage json `1aef420b2027e5a5916f77e0804fec4f7496d82e5ce3124718fb02a6a061031a`
- **coverage json 위치 주의:** Git Bash가 `json:/d/...` 인자를 경로 변환하지 않아 json 파일이 의도와 달리 `D:\d\project\Recoryn\build\review-trees\g06c-coverage.json`에 쓰였다. 검토자가 만든 저장소 밖 경로이며 다른 내용은 없다. 삭제 명령은 안전 검사로 실행되지 않았으므로 사용자나 C00이 `D:\d` 폴더를 지워야 한다. `check_coverage`는 그 파일을 그대로 읽어 실행했다.

### RC2-3. 보강 181행의 oracle 표본 검사

- **구조 검사:** `tests/integration/test_cost_cap.py`의 `test_cov2_*` 11개 함수를 AST로 검사했다. `tests/unit/test_cost_cap.py`의 추가 15개 함수는 diff 추가분으로 검사했다.
  - 모든 함수에 `assert`가 있거나, `pytest.raises(SecurityError, match="^CODE$")` 형태의 **앵커 고정 정확 코드** 검사가 있다.
  - `try`는 sqlite 연결 `finally` 정리뿐이다. 예외를 삼키는 `except`, `assert True`, `pragma: no cover`는 없다.
  - 유일한 `pass`는 `with Legacy(db): pass`로 DB를 만드는 용도다.
- **입력 설계:**
  - WIRE 51행은 `cov2_wire`가 유효 기준 envelope 하나에서 결함 하나만 바꾸는 구조다.
  - 같은 기준의 정상 5종(POS-wire)은 literal 상한·금액(19/22/21/11/11)으로 판정한다.
  - REQ·POLICY·PRICE는 단일 필드 위반이다.
  - CLOCK은 정상 0과 12.25를 포함해 일괄 거부를 막는다.
  - POS-fingerprints는 제품 함수를 쓰지 않고 수작업 JSON과 `hashlib`로 기대 SHA를 만든다(`"abc"` → `ba7816bf…`).
- **상태 oracle:**
  - WRITE 14행은 거부 코드와 함께 요청 행(state/금액/actual/dispatch_id/quote_json)과 witness bytes가 변하지 않음을 비교한다.
  - EXTERNAL의 정상 갱신 행은 (confirmed, reserved) = (7, 13)을 확인한다.
  - USAGE는 event 0행, witness 불변, RESERVED 유지를 확인한다.
  - CACHE는 금액 [13, 14, 14, 15, 16, 16], 합 88, 행 6개를 확인한다.
- **약한 점:** COV2-OPEN-003(catalog)은 아래 L6처럼 행이 가리키는 방어선을 실제로 구별하지 못한다. 다른 표본에서는 같은 문제를 찾지 못했다.

### RC2-4. 새로 덮인 분기의 변이(보강 행만으로 판정)

harness는 `build/review-trees/g06c-probe/mutate_g06c.py`다.

- 사본별로 한 곳만 바꿨다. 선택은 바뀐 시험 2파일의 `-k cov2`, 즉 보강 181행뿐이다(정상본 **181 passed**).
- 따라서 KILLED는 G06-COV2 oracle이 잡았다는 뜻이다.

| 변이 | 결과 / 첫 실패 행 |
| --- | --- |
| C1 header CR/LF 허용(`cost.py:80-81`) | KILLED, COV2-HEADERS-003 |
| C2 비유한 clock 허용(`:62`) | KILLED, COV2-CLOCK-003 |
| C3 catalog 중복 key 허용(`:304`) | KILLED, COV2-CATALOG-002 |
| C4 Gemini mime 미검사(`:474`) | KILLED, COV2-WIRE-gemini-mime |
| C5 multipart 중복 part 허용(`:405`) | KILLED, COV2-WIRE-multipart-duplicate |
| C6 audio 출력 단가 무시(`:593`) | KILLED, COV2-QUOTE-bound-4 |
| C7 anthropic-version 미대조(`:443`) | KILLED, COV2-WIRE-anthropic-version |
| C8 가격 출처 https 미검사(`:277`) | KILLED, COV2-PRICE-022 |
| L1 write의 quote_json 대조 제거(`ledger.py:1193`) | KILLED, COV2-WRITE-010 |
| L2 write의 잔액 초과 검사 제거(`:1210-1214`) | KILLED, COV2-WRITE-012 |
| L3 usage version 0·final 타입 검사 제거(`:1254`) | KILLED, COV2-USAGE-000 |
| L4 구 v2 audit 열 전환 생략(`:202`) | KILLED, COV2-OLDV2 |
| L5 witness 4096 B 상한 제거(`:132`) | KILLED, COV2-WITNESS-000 |
| **L6** open의 catalog digest 대조 제거(`:1072`) | **SURVIVED.** 신규 4파일 전체와 `test_gateway`(5120 passed)로도 생존 → G06R-10 |
| L7 `availability`의 I/O 실패를 정상으로 보고(`:229`) | KILLED, COV2-AVAILABILITY |

RECHECK 1의 생존 변이 N01·N03도 같은 선택으로 다시 판정했다. 각각 **COV2-WRITE-000**과 **COV2-EXTERNAL-000**에서 KILLED다. 결과 LF SHA256은 다음과 같다.

- `mutate_g06c.py` `63032d836671433bc799c151edfe966167e9d969733bf2c3b10c697c976b5222`
- `mutations_g06c.json` `64a97f2cdc696e0a14ebe3fd4687922ad57bcba3a3fadc2623c77c17645a89c7`
- `mutate_g06c.log` `ae11f77a0b34aa2496382db39daa872d9dcad5ad58a8f2cb23c9a27ada1e91d4`

### RC2-5. fixture 변경의 의미 유지

- `LEGACY_V1_SHA256 = 890baaf7…`(`tests/integration/test_cost_cap.py:933`)와 원문은 FIX1과 같다. 이 값은 `git show 8e09b62:src/recoryn/security/ledger.py`(그리고 234dd31)의 LF SHA256과 **일치**한다.
- `legacy_class`는 원문 hash를 계속 assert한다. 바뀐 것은 적재 이름뿐이다(`g06_legacy_v1_fixture.ledger`, 실제 `recoryn.security._core`를 `g06_legacy_v1_fixture._core`로 alias).
  - 원문의 `from ._core import …`는 이전(`recoryn.security._g06_v1_fixture`)과 같은 실제 `_core`로 해석된다. 옛 코드의 동작은 같고 coverage 분모에서만 빠진다.
- 의미 검증: 제품의 `legacy_unscoped`를 항상 False로 바꾼 변이를 DB·legacy 선택에 적용했다. **G06-DB-03·04·05**, FIX1-WRITE-foreign_period, COV2-EXTERNAL-003이 실패했다(5 failed). legacy 차단 oracle은 새 fixture를 거쳐도 살아 있다.
- 관찰(발견 아님): `legacy_class`가 `sys.modules`에 두 항목을 정리하지 않고 남긴다. 같은 실행 안의 다른 시험에는 영향이 없다.
- 프로세스 경쟁 시험의 자식은 이제 부모가 import한 src로 `PYTHONPATH`를 고정하고 `ledger.__file__`을 assert한다(G06R-09 부수 관찰 해소).

### RC2-6. 1차·RECHECK 1 발견 상태 갱신

| ID | 상태 |
| --- | --- |
| G06R-01~07 | RECHECK 1 판정 유지. 제품 코드가 바뀌지 않았고, 전체 회귀가 다시 PASS했다 |
| G06R-08 / S3 | OPEN 유지(실가격 첫 항목 게이트 인계, 이번 범위 밖) |
| G06R-09 / S3 | **RECHECKED.** N01→COV2-WRITE-000, N03→COV2-EXTERNAL-000 KILLED. 자식 import 경로 고정 |

### RC2-7. 새 발견

#### G06R-10 / S3 / OPEN — COV2-OPEN-003(catalog)은 `ledger.py:1072` 문장을 덮지만 그 방어선을 제거해도 시험이 실패하지 않는다. USER_CAP의 open 단계 catalog 대조는 무시험이다

- **재현:** L6 변이(`if catalog.sha256 != policy.catalog_digest:` → `if False:`). 보강 181행, 신규 4파일 전체, `test_gateway`에서 모두 PASS다(5120 passed).
- **원인:** 해당 행은 VERIFIED 가격의 예약을 쓴다. 대조가 빠져도 곧이어 `quote()`가 자체 digest 검사(`cost.py:534-535`)에서 같은 `COST_QUOTE_MISMATCH`를 낸다. 같은 코드라서 시험이 두 방어선을 구별하지 못한다.
  - USER_CAP 경로(`ledger.py`의 open 분기, `quote()`를 다시 부르지 않음)에서는 이 대조가 유일한 catalog 결합 검사다. 이를 고정하는 행이 없다.
- **영향:** 현재 catalog는 compiled-in이고, 예약 ID는 요청마다 새로 만들어진다. 따라서 앱 갱신 전후에 같은 USER_CAP 예약을 다시 dispatch하는 경로는 확인되지 않았다. 보강 행이 coverage는 채우되 검출은 하지 못하는 사례로 기록한다.
- **기대:** USER_CAP(일반 모드) 예약의 policy_json catalog digest를 바꾼 open 부정 행을 둔다. 기대는 정확한 코드, `dispatch_id` NULL, RESERVED 유지다. 또는 COV2-OPEN-003의 의도를 문서에서 정정한다.

### RC2-8. 123초 초과에 대한 의견

- 이 검토 tree의 신규 4파일을 검토자 쪽에서 다른 실행 없이 두 번 돌렸다(coverage 없음, 같은 옵션·PYTHONPATH 고정). 결과는 **5089 passed, 84.78s / 85.46s**였다.
- coverage를 켠 전체 회귀 안의 4파일 testcase 합은 92.39s였다.
- 보강 181행 자체는 약 2초다(작성자 2.05초).
- 따라서 작성자의 123.10s·144.56s는 분모 증가가 아니라 측정 환경 차이(동시 작업·볼륨·부하)로 보는 것이 맞다. 같은 PC의 조용한 실행에서는 120초 예산 안이다.
- 검토자 의견:
  - 시험 시간 게이트는 제품 위험이 아니다. 축약이나 예산 증액은 필요하지 않다.
  - C00이 "동시 실행 없는 단독 실행, 측정 볼륨·명령 명시"를 측정 절차로 고정해 이 수치로 판정하기를 권한다.
  - 작성자가 초과를 숨기지 않고 보고한 점은 적절하다.

### RC2-9. 미검증 범위

- 작성자 FIX2 변이 2개 외의 기존 변이(46개) 재실행
- coverage 미실행으로 남은 `ledger.py` 방어 경로(§17.6 표)의 도달 가능성 개별 증명
- CI runner(Windows matrix)에서의 실제 시간과 coverage(이 PC에서만 실행)

## RECHECK 3 (G-P06b) — 2026-11-23, 같은 검토자(Claude, G-P06 독립 검토)

G-P06은 commit 68fbbda로 push됐다. C00이 RECHECK 2의 G06R-10을 다룬 후속 G-P06b(작성자: C00 지정 구현 하위 에이전트)의 짧은 재확인을 요청했다. 앞 절들(LF SHA256 `a84a8c01…`)은 보존한다.

**판정:**

- **G06R-10 / S3는 RECHECKED**다. RECHECK 2의 자식 import 부수 관찰도 해소됐다.
- 새 OPEN은 0건이다.
- G06R-08(S3, 실가격 첫 항목 게이트 인계)은 범위 밖이라 OPEN 유지다.

### RC3-1. 입력

- 대상 tree는 **`8e7403bb21218294c03b5e8f8c8dd1bb78277033`**(`git cat-file -t` = tree)다. 기준은 HEAD **68fbbda**이다.
- `git diff --stat 68fbbda 8e7403bb` 결과는 2파일, +138/−3이다.
  - `git diff --quiet 68fbbda 8e7403bb -- src tests/unit`이 성공한다. **제품 코드와 `tests/unit/test_cost_cap.py`의 변경은 0이다.**
- LF SHA256은 다음과 같다. 둘 다 배정값과 일치한다.
  - `tests/integration/test_cost_cap.py` `bfa21139dacda930c10fa2f6134080206a00b316f2944153765b70a1ae027637`
  - 계약 문서 `54aa5443fc37ead9eedfff248d704ddb6165af3ee6cfef96e92c278142273730`
- 작성자 증거 R5(`C:\Users\gangd\AppData\Local\Temp\recoryn-g06b-CsfWs5ts`)는 읽기만 했다. `l6-results.json`, `new-four.xml`, `g06-audit.json`의 LF SHA256이 §18.3 기재값과 일치한다.
- 추출과 실행 위치: `git archive 8e7403bb | tar -x -C D:\project\Recoryn\build\review-trees\g06d`. 변이 사본은 `g06d-mut`, basetemp는 `g06d-bt`, 스크립트는 `g06d-probe`다.
- 모든 출력 경로는 Windows 형식 `D:\project\Recoryn\build\review-trees\…`로 지정했고 저장소 밖 쓰기가 없음을 확인했다. RECHECK 2의 `D:\d\…` 오기록은 반복하지 않았다.

### RC3-2. G06R-10 — L6 직접 재적용과 판별력

harness는 `g06d-probe\mutate_g06d.py`다(LF `1e97a586c0685acb29163bad94362b0c61b7c03fdf67eacfc52a3c5e2ed2c0a3`).

- 결과는 `mutations_g06d.json`(`1c89329495a4467f5df1bcc08bd3fd64071f0418729097ae275fa996372a679e`)과 `mutate_g06d.log`(`e3665570969f3d8055d86bb634bf886bc2d2389e5b583c453010e9abb2910138`)다.
- 사본 import 위치는 `g06d-mut\src`임을 확인했다.
- 정상본은 `-k "cov2 or cov3"`에서 **185 passed**(181 + 4)였다.

| 변이 | 선택 | 결과 |
| --- | --- | --- |
| L6: `ledger.py`의 open 단계 `if catalog.sha256 != policy.catalog_digest:` → `if False:`(RECHECK 2와 같은 패턴) | `-k "cov2 or cov3"` | **3 failed / 182 passed**: COV3-OPEN-001·002·003. 대조군 000은 통과 |
| 같은 L6 | 신규 4파일 전체 | **3 failed / 5090 passed**(같은 3행) |
| Q: `cost.py`의 `quote()` 자체 digest 검사(`:534-535`) 제거 | `-k cov3` | **4 passed** |

- Q 결과의 의미: COV3 행은 `quote()`의 자체 검사에 의존하지 않는다. 즉 RECHECK 2에서 지적한 "다른 방어선이 같은 코드로 막아 줌"이 아니다.
- 코드 경로도 대조했다(`ledger.py`의 `validate_dispatch` open 분기). USER_CAP 예약은 open에서 `quote()`를 다시 부르지 않는다.
  - 001은 policy_json의 digest가 바뀌어 재사용 cache가 빠진다.
  - 002·003은 같은 인스턴스 cache로 재사용된다.
  - 두 경우 모두 `_eligible_account`, 지문 대조, 모드·cap 대조는 통과한다. 남는 catalog 결합은 open 단계 대조 하나다.
- 대조군 000이 같은 예약의 정상 open(`dispatch_id='cov2'`)을 보이므로, 부정 행이 다른 이유로 실패한 것이 아님도 확인된다.
- 부정 행의 oracle: `^COST_QUOTE_MISMATCH$`, `dispatch_id` NULL, RESERVED 13, 예약 합 13, UNKNOWN 0, witness 불변. 003은 여기에 transport open 0·write 0을 더한다. 기대값은 literal이고 제품 함수로 만들지 않는다.

### RC3-3. 자식 import 확인의 판별력

같은 harness로 `test_v2_separate_process_reservations_have_one_winner`(`-k separate_process`)를 변형했다. 정상본은 1 passed다.

| 변형 | 결과 |
| --- | --- |
| P1: 자식 `PYTHONPATH`를 작업 트리 `D:\project\Recoryn\src`로 | **1 failed.** 자식의 `AssertionError: D:\project\Recoryn\src\recoryn\security\ledger.py`가 부모의 조기 종료 보고(stdout/stderr)로 표시됨 |
| P2: 자식 `PYTHONPATH` 제거(venv editable `.pth`가 작업 트리를 가리킴) | **1 failed**, 같은 메시지 |
| P3: P1에 더해 자식 쪽 두 origin assert 제거 | **1 passed** |

- P3 결과는 혼동을 잡는 장치가 자식 쪽 assert임을 보여 준다. 즉 새 assert가 실제로 검출력을 가진다.
- 부모 쪽은 시험 파일 기준 `tree_src`와 자기 `ledger.__file__`을 대조한다. PYTHONPATH를 고정하지 않고 pytest의 `pythonpath=["src"]`만 쓴 실행에서도 경쟁 시험과 COV3가 **5 passed**였다. 부모가 다른 사본을 import하는 경우는 코드 읽기로만 확인했다.

### RC3-4. 실행

- G-P06 신규 4파일 단독(cwd g06d, PYTHONPATH 고정, `-W error::ResourceWarning -W error::pytest.PytestUnraisableExceptionWarning`): **5093 passed, 97.50s**. 120초 예산 안이다.
  - JUnit `D:\project\Recoryn\build\review-trees\g06d-new4.xml`, LF `0a4b5cb06d5a7d114a48eebc49617678630c61c0985bfaf1a765b7bb002d310b`
  - testcase 합은 94.92s다.
- ID 감사: 의미 행 **4834 고유, 누락·중복·추가 0**. G06-COV2 181개, **G06-COV3-OPEN-000~003 4개**, 모두 고유다.
- `ruff check`와 `ruff format --check`(`tests/integration/test_cost_cap.py`): PASS.
- 전체 오프라인 회귀와 coverage는 제품 코드 불변이므로 이번에 다시 실행하지 않았다. 작성자 R5의 15035 PASS와 check_coverage 전 묶음 PASS(§18.3)는 해시만 대조했다.

### RC3-5. 상태

| ID | 상태 |
| --- | --- |
| G06R-10 / S3 | **RECHECKED.** L6 → COV3-OPEN-001~003 KILLED. COV3는 `quote()` 자체 검사와 독립적이다 |
| RECHECK 2 부수 관찰(자식 import 경로) | 해소. P1·P2 검출, P3로 검출 장치 확인 |
| G06R-08 / S3 | OPEN 유지(실가격 첫 항목 게이트 인계, 범위 밖) |
| 새 발견 | 없음 |
