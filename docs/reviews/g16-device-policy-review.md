# G16 / G-P16 장치 실행 정책 저장·복원 독립 검토

상태: **독립 검토 완료 — S0 0 · S1 0 · S2 0 · S3 4 OPEN**. 검토자는 C00이 지정한 하위 에이전트(Claude)다. 작성자는 C00 지정 구현 하위 에이전트다. 이 문서 외에는 저장소 파일을 쓰지 않았다. 코드 수정·Git 쓰기·네트워크·설치·실장비·모델·유료 호출·추가 에이전트는 없었다.

## 1. 대상·기준·방법

- 대상 tree `6b6b9ad4446f6066af72fba98f0c034a9de7cfa3` = HEAD `b6da7e0` + 8파일이다(`git diff b6da7e0 6b6b9ad4` +3,134/−6). `tests/ui/test_resource_policy_ui.py`는 변경이 없다.
- 8파일 LF SHA-256 앞 12자리:
  - source: `app/device_policy.py` `5d0921c9b50b`, `ui/main.py` `38fddf21240c`, `ui/ai_bridge.py` `9cae00172d45`
  - 시험: unit `30d132948f4e`, integration `fdfa86eb4218`, ui `09fd6668d030`, `tests/ui/conftest.py` `04a0614f7862`
  - 계약 `c7600109c07f`(전체 `c7600109c07f80874e5aa9a3599318507022feadcd537d84926afee4011493cd`)
- 계약 `docs/testing/g16-device-policy-cases.md` 1–10절과 C00 결정·설계 승인 조건을 기준으로 했다. C00 조건은 다음과 같다.
  - `run()`만 실제 store를 넘긴다. store=None은 메모리 전용이다.
  - conftest가 창마다 TEMP 실제 store를 쓴다.
  - AUTO는 별칭이고 currentText는 enum을 낸다. 프로그램 선택은 현재 실행에만 적용하며, 저장은 사용자 activated에서만 한다.
  - X-01·M19를 둔다.
- 실행 위치는 `build/review-trees/g16a`(`git archive 6b6b9ad4 | tar -x`)다. PYTHONPATH는 사본 `src`로 고정했고, 반례 자식 프로세스·변이 사본의 import 출처가 사본임을 출력으로 확인했다.
- 실제 사용자 프로필은 쓰지 않았다.
  - 모든 실행에서 `LOCALAPPDATA`·`APPDATA`를 TEMP로 돌렸다.
  - 실행 전 실제 `%LOCALAPPDATA%\Recoryn`은 **없음**이었다(읽기 전용 확인). 실행 뒤 상태는 §2에 적었다.
- 반례·스크립트·로그는 `build/review-trees/g16a-probe/`에 있다.
  - 반례: `probe_g16.py`·`probe_arrows.py`, 자식 `child_hold.py`, 출력 `probe_g16.out`·`probe_arrows.out`
  - 변이: `mutate.py`, 결과 `mut/report.json`
  - conftest 비교: `run_ui_compare.sh`, `ui-conf.xml`, `ui-noconf.xml`
  - 전체 회귀: `run_full.sh`, `full.log`, `checkcov.log`

## 2. 실행 증거

| 항목 | 결과 |
| --- | --- |
| CI 동등 전체 회귀(`python -m pytest -q -p no:cacheprovider -W error::ResourceWarning --cov=recoryn --cov-branch --cov-report=json:coverage.json --cov-fail-under=85`, `-rs`, OS TEMP basetemp) | **25,306 passed, skip 0, failures·errors 0**, 1,556.3초, 총 coverage 92.62%. 작성자 보고와 같은 수다 |
| `scripts/check_coverage.py coverage.json` | 전부 PASS(line/branch %): domain 99.18/97.89, capture 99.85/98.57, jobs 99.19/95.61, storage 95.95/91.41, security 98.11/94.43, content 98.98/99.02, all 93.96/88.66 |
| ruff check / format --check / `MYPYPATH=src python -m mypy src/recoryn scripts packaging` | All checks passed / 205 files already formatted / no issues in 93 source files |
| 신규 3파일 정상본(변이 하네스 BASE) | **650 passed, 15.5초**(60초 게이트 안) |
| conftest 유무 비교(`tests/ui`에서 G-P16 UI 파일만 제외) | conftest 있음 2,686 passed / 없음 2,686 passed. JUnit 노드 집합이 같고 결과가 다른 노드 0. 두 실행 모두 TEMP로 돌린 프로필에 파일 생성 0 |
| 실제 사용자 경로 | 전체 회귀·반례·변이·비교 실행을 모두 마친 뒤에도 실제 `%LOCALAPPDATA%\Recoryn`은 **없음**이다. 전체 회귀가 TEMP로 돌린 `LOCALAPPDATA`·`APPDATA`에 만든 파일도 0이다(`redirected-profile-files.txt` 빈 목록) |

## 3. 발견 사항

| ID | 심각도 | 상태 | 요약 |
| --- | --- | --- | --- |
| G16R-01 | S3 | OPEN | 시작 때의 일시적 읽기 실패(잠금 경합·공유 거부)는 그 실행 내내 UNAVAILABLE로 남는다. 다시 읽지 않으며, 이어진 저장은 revision 비교 없이 다른 프로세스의 새 값을 덮는다 |
| G16R-02 | S3 | OPEN | 설정 위치의 상위 구성요소가 일반 파일이면 "저장된 설정 없음 · 기본값"(DEFAULT)으로 표시된다. 저장은 그때서야 실패한다. 계약은 위치 문제를 UNAVAILABLE로 둔다 |
| G16R-03 | S3 | OPEN | replace 공유 위반의 상한 안 재시도(GS02R-01 교훈 반영 코드)를 지키는 시험이 없다. 재시도를 지운 변이 GM8이 생존한다 |
| G16R-04 | S3 | OPEN | 닫힌 콤보에서 화살표로 항목을 훑기만 해도 매번 저장되고 "저장됨"이 알려진다(Qt `activated` 의미). 낭독기 사용자가 항목을 듣는 동작과 선택이 구별되지 않는다 |

### G16R-01 (S3) 일시적 읽기 실패의 고착과 revision 비교 생략

- 반례 A(`probe_g16.py`): 실제 자식 프로세스가 제품 `PolicyIo.try_lock`으로 협력 잠금을 4초 잡은 상태에서, GPU_ONLY 파일이 있는 창을 만들었다.
  - 창 생성 0.191초, 상태 LOADING, 녹음 버튼 활성, busy False. 녹음·시작은 독립이다.
  - 2초 뒤 UNAVAILABLE/CPU_ONLY로 안전 실패한다.
  - 잠금이 풀린 뒤에도 그 실행은 다시 읽지 않는다. 저장된 GPU_ONLY는 이번 실행에서 복원되지 않는다.
- 반례 B: 자식이 설정 파일을 공유 없이(CreateFileW share 0) 1.5초 열었다.
  1. load가 `IO_ERROR`로 UNAVAILABLE이 된다. `_tick` 5회 뒤에도 그대로다.
  2. 그 사이 다른 협력 writer가 파일을 AUTO로 저장했다.
  3. 이 창에서 사용자가 CPU_ONLY를 고르면 **SAVED**가 되고, AUTO를 CONFLICT 없이 덮는다.
  - 원인: load 실패 결과의 revision이 None이고, `_write_locked`는 `observed is None`이면 비교를 건너뛴다.
- 판단:
  - 안전한 쪽(CPU_ONLY)으로 실패하고 지속 상태를 남기지 않으므로, 다음 시작은 정상이다. 그래서 GS02R-01 같은 영구 고착은 아니다.
  - 다만 계약 §2.2의 "다른 앱/worker가 원본을 바꿈 → CONFLICT, 새 파일을 옛 UI 확인으로 덮지 않음"이 "시작 읽기 실패" 하위 경우에는 지켜지지 않는다.
  - replace와 달리 읽기의 일시 공유 거부에는 상한 재시도가 없다.
  - 덮는 값이 사용자의 명시 선택이라 피해가 작아 S3로 둔다.
- 권고:
  - 읽기 PermissionError에 replace와 같은 상한 재시도를 둔다.
  - UNAVAILABLE에서 사용자가 선택할 때 저장 직전 관측을 "확인 전"으로 표시하거나, 파일이 존재하고 다르면 CONFLICT로 보고한다.
  - 또는 UNAVAILABLE 동안 주기적·수동 재조회를 둔다. 셋 중 하나를 계약에 적는다.

### G16R-02 (S3) 위치 상위가 일반 파일이면 DEFAULT로 표시

- 반례 D: `LOCALAPPDATA\Recoryn`을 일반 파일로 만들었다.
  - load는 `DEFAULT`이고 "현재 실행: CPU_ONLY · 저장된 설정 없음 · 기본값"을 보인다.
  - 사용자 선택 저장은 `SAVE_FAILED`다.
- 원인: Windows에서 중간 구성요소가 파일이면 열기가 경로 없음(FileNotFoundError)이 된다. `PolicyIo.read`와 잠금 열기가 이것을 "파일 부재"로 처리한다.
- 계약과의 차이: §2.1·§2.2는 "안전한 로컬 경로로 판정할 수 없으면 CPU_ONLY·저장 위치 확인 필요", §5 F는 "읽을 수 없는 파일을 정상 부재로 취급하지 않는다"고 한다.
- 안전한 기본값과 저장 실패 표시가 있으므로 S3다.
- 권고: 부재 판정 전에 부모 디렉터리들이 디렉터리인지(또는 없는지) 확인하고, 파일이면 UNAVAILABLE(`PATH_UNSAFE`)로 둔다.

### G16R-03 (S3) replace 재시도 무시험

- 변이 GM8: `_replace`의 PermissionError 재시도를 첫 실패에서 바로 raise로 바꿨다. 신규 3파일 **650 passed(생존)**.
- 원인: W 가족의 replace fault는 영구 PermissionError라, 재시도가 있든 없든 FAILED다. 일시 거부가 상한 안에서 풀려 SAVED가 되는 행이 없다.
- 실제 동작은 반례 C로 확인했다. 자식이 파일을 삭제 공유 없이 연 경우:
  - 0.8초 보유: SAVED
  - 3.5초 보유: SAVE_FAILED이고, 원본 bytes는 보존되며 TEMP는 남지 않는다.
  - 해제 뒤 재선택: SAVED. 일시 거부가 지속 상태로 굳지 않는다.
- 제품 동작은 맞다. 그러나 GS02R-01 교훈을 반영한 바로 그 코드가 회귀 보호를 받지 못하므로, fake monotonic으로 "N회 거부 뒤 성공" 행을 추가하기를 권고한다.

### G16R-04 (S3) 화살표 훑기의 저장·알림

- Qt는 닫힌 콤보의 화살표 키마다 `activated`를 보낸다. 반례 `probe_arrows.py`(출력 `probe_arrows.out`)에서 실제 창의 콤보에 초점을 두고 ↓를 두 번 눌렀다.
  - 저장이 2회(GPU_ONLY, 이어서 AUTO) 일어났다. 멱등 생략은 같은 값에서만 동작한다.
  - 현재 실행 정책이 그때마다 바뀌었다.
  - polite "현재 실행: … · 저장됨 · 다음 시작에도 유지" 알림이 2회 나갔다.
- 설계 결정 6(키보드 화살표 선택도 사용자 선택)과 U 화살표 행이 의도한 동작이다. 쓰기·정책 결과도 마지막 선택과 같아 안전성 문제는 없다.
- 다만 낭독기 사용자에게 장황하고, "탐색"과 "선택"이 구별되지 않는다.
- Narrator 실사용 게이트에서 확인할 항목으로 남기고, 필요하면 Alt+↓ 목록을 연 뒤 Enter로 확정할 때만 저장하는 방식을 검토하기를 권고한다.

## 4. 중점 항목별 판정

1. **녹음·시작·AI guard와의 독립: 충족.**
   - 설정 I/O는 전용 `QThreadPool(최대 1)`에서만 실행되고, 창 생성은 기다리지 않는다(반례 A 0.19초·녹음 버튼 활성).
   - 잠금 경합·공유 거부·위치 오류·손상·미래 형식 모두 CPU_ONLY로 안전 실패한다(반례 A·B·D, L·F·P 가족).
   - 복원은 AI 요청·준비·Job·dispatch를 만들지 않는다(X-03, 작성자 M14).
   - 종료 때는 녹음기를 먼저 닫고, 정책 pool은 시작된 쓰기만 기다린다.
   - 녹음 독립(N, 실제 `RecordingService`+fake PCM)은 작성자 시험으로 확인했고, 검토자는 실제 장치로 재현하지 않았다.
2. **소급 금지·config_key 불변·G-P07 계속: 충족.**
   - `_selected_policy()`는 요청마다 한 번 `currentText()`(enum)를 캡처한다.
   - S 180행은 QUEUED·RUNNING·BLOCKED·REMOTE_UNKNOWN의 capture 동일성, Job 기록·dispatch 불변, 선택 단독 요청 0을 손 표로 대조한다.
   - CAPABILITY(PV)로 BLOCKED된 Ollama의 명시 계속은 다음과 같다. G-P11 T30·결정 ⑦(가)와 같다.
     - AUTO에서는 새 snapshot으로 재접수된다.
     - CPU_ONLY·GPU_ONLY에서는 준비 전 PV로 기존 BLOCKED를 유지한다.
   - 작성자 M10~M13이 이를 검출한다.
3. **원자 쓰기·충돌·손상·미래·잠금**
   - 같은 디렉터리 TEMP → short write 검사 → fsync → replace 순서다.
   - FUTURE는 save·reset 모두 REFUSED이고, INVALID는 확인된 reset만 같은 revision에서 교체한다(GM2 검출).
   - 실제 자식 프로세스 잠금은 X-04(작성자)와 반례 A(검토자)에서 확인했다.
   - 일시 replace 거부는 상한 안 재시도 후 굳지 않는다(반례 C).
   - 남은 문제: 읽기 쪽 일시 실패(G16R-01)와 위치 판정(G16R-02).
   - 디렉터리 fsync 없음(전원 장애)과 협력 잠금 한계는 계약대로 공개되어 있다.
4. **conftest 전역 적용: 의미 변화 0.**
   - conftest 유무로 `tests/ui` 2,686 노드의 결과가 같다.
   - conftest는 `default_policy_store`와 LOCALAPPDATA만 TEMP로 바꾼다. 실제 load는 그대로 돌고 DEFAULT에서는 알림이 없다.
   - 시험이 실제 사용자 경로를 건드리지 않음은 변이 하네스 프로필 파일 0과 §2 실제 경로 확인으로 보았다.
   - tests/ui 밖(integration·e2e)의 `MainWindow(library)`는 store가 없어 NO_STORE이며 읽기·쓰기 0이다.
5. **run() 배선(X-01)·M19: 충족.**
   - `run()` → `user_window()` → `DevicePolicyStore.for_user()`이고, X-01이 두 번 실행해 저장·복원을 확인한다.
   - 검토자 변이 GM10(초기 load 제거)은 X-01·U·S에서 검출됐다. 다만 fixture 안 assertion이 setup error 181건으로 나타나므로 "assertion 실패" 판정 범위 안에서만 셌다.
6. **접근성·키보드**
   - 콤보는 별칭("AUTO — GPU 우선, CPU 사용 허용")을 표시·낭독하고 API는 enum이다.
   - 정책 control의 이름·설명(새 요청에만 적용, 진행 중 작업 유지, 저장 위치), 상태 label 이름·설명이 있다.
   - 손상·미래·위치·실패·충돌은 assertive, 나머지는 polite이며 같은 (상태, 정책)은 다시 알리지 않는다.
   - 재설정 버튼은 손상 상태에서만 활성이고, Enter·Space·기본 아니요·Esc를 지킨다.
   - G-P07 정책 탐색은 초점만 옮기고 저장하지 않는다(S 준비 행).
   - 남은 문제: G16R-04. Narrator 실사용은 NOT_RUN(외부 게이트)이다.
7. **회귀·정적 검사** — §2.
8. **변이**(사본마다 하나, 신규 3파일, LOCALAPPDATA TEMP, import 출처 확인)

| 변이 | 결함 | 결과 |
| --- | --- | --- |
| GM1 | 경로 reparse·hardlink 검사 생략 | 검출 6(P 행) |
| GM2 | 일반 선택이 손상 파일을 덮음 | 검출 7(F 행) |
| GM3 | 4,096 bytes 경계 off-by-one | 검출 4(L 4096·4097 행) |
| GM5 | 프로그램·복원 선택도 저장 | 검출 43(U·X-02 등) |
| GM8 | replace 재시도 제거 | **생존** → G16R-03 |
| GM9 | 충돌 표시 전 대기 저장의 자동 덮어쓰기 차단 제거 | 생존(**동등 변이**로 판정) |
| GM10 | 초기 load 제거 | 검출(failed 9·setup error 181, X-01 assertion) |

GM9를 동등 변이로 본 이유: 이 차단이 없어도, 대기한 저장은 갱신되지 않은 chain revision으로 store의 revision 비교에서 다시 CONFLICT가 된다(X-10 그대로 통과). 실질 차이는 다른 writer가 값을 바꿨다가 원래 bytes로 되돌린 ABA에서만 생긴다. 그 경우 덮는 대상도 원래 bytes라 손실이 없다.

## 5. 작성자 판단·편차에 대한 의견

- store=None 메모리 전용과 `run()`만 실제 store를 넘기는 배선은 타당하다(C00 조건 충족). 도구·통합 시험이 사용자 설정을 건드릴 수 없다.
- conftest가 store factory와 LOCALAPPDATA만 바꾸고 제품 load를 우회하지 않는 것은 타당하며, 비교 실행으로 의미 변화 0을 확인했다.
- U 행이 행마다 controller를 새로 묶는 fixture는 생성자 배선을 직접 거치지 않는다. 그러나 S·CLOSED·X-01이 실제 생성자로 배선을 고정하므로 허용 가능하다.
- 손상·미래 파일에서 일반 선택 시 잠시 "저장 중"이 보이는 것(§10.8)은 거부 결과가 곧 표시되므로 S3 이하로 보며, 별도 ID는 두지 않는다.

## 6. 미검증·한계

- Narrator 실사용, 실제 네트워크 드라이브·폴더 리디렉션·로밍 프로필, 다른 Windows 사용자, GPU 실장비, 다른 PC 복원, 실제 G-P09 backup/restore 대조는 하지 않았다(외부 게이트·G-P09b 인계).
- 녹음 독립은 작성자 N 가족(fake PCM)과 반례 A의 창 상태로만 보았다. 실제 장치 녹음은 없다.
- 변이는 검토자가 고른 7개뿐이다. 작성자 19개는 다시 실행하지 않았다.
- 전원 장애(디렉터리 fsync 없음)와 비협력 프로그램의 파일 치환은 계약대로 보장 밖이다.
- 반례 A·B·C는 실제 자식 프로세스와 실제 Windows 공유 모드를 썼다. 시간 상한(2초)은 실시간이며, 부하가 큰 장치에서의 경계 흔들림은 측정하지 않았다.
