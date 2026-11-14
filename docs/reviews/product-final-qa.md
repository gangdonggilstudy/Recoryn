# R15 최종 동결 snapshot 독립 aggregate QA

2026-11-14, R00 재배정 / R15(기존 R14) 실행. **REVIEW_READY — root fixture 교정·재동결 뒤 전체 1444 PASS, coverage/정적 검사 PASS, 전후 132파일 map 동일.** 최종 tree SHA-256은 `c3a9df87b4545e016652ad13c01605bba1ac6870d8f594ad884a613b20673b64`다. 첫 실행 1443 PASS/fixture 1 FAIL과 그 당시 증거는 아래에 보존하며 최신 판정은 마지막 재확인 절을 따른다. 전체 구현 완료·공식 릴리스 승인 문서가 아니다.

## 범위와 독립성

쓰기 허용은 이 문서 하나다. src/tests/scripts/packaging/config와 Git 인덱스를 수정하지 않는다. R13의 최종 test freeze 신호 뒤 기존 전체 pytest, coverage branch/JSON과 별도 budget 검사, Ruff check/format, MYPYPATH=src mypy를 직접 실행했다. 앞선 예비 정적 검사는 최종 동결 후 다시 실행했다.

R15는 이전 R14에서 security/gateway.py·ui/privacy.py를 작성했다. 해당 작성분의 독립 승인은 [R13 BR23 후단](product-egress-review.md)의 43 PASS/관련 92 PASS, 실행 전후 제품 digest 대조 및 추가 발견 0건을 근거로 연결한다. 이번 전체 실행으로 자신의 보안 작성물을 단독 최종 승인하지 않는다. helper 원 반례와 digest는 [BR30 기록](product-model-runtime.md)에 보존했다. BR12-09 및 BR13-07의 원 반례 재확인과 전체 aggregate QA도 별도 증거다.

## 환경과 동결 입력

- Windows 11 `10.0.26300-SP0`, AMD64, Python `3.13.1` / MSC v.1942 64bit.
- interpreter: `D:\project\Recoryn\.venv\Scripts\python.exe`.
- pytest 9.2.0, pytest-cov 7.1.0, coverage 7.17.3, Hypothesis 6.170.15, Ruff 0.15.22, mypy 1.20.2.
- PySide6 Essentials/Addons·Shiboken6 6.12.0, NumPy 2.3.5, sherpa-onnx 2.0.1, onnx 1.23.2, PyInstaller 6.22.3. 설치/metadata 조회는 실제 모델 실행이 아니다.
- `QT_QPA_PLATFORM=offscreen`, `HF_HUB_OFFLINE=1`, `HF_HUB_DISABLE_TELEMETRY=1`, `PYTHONDONTWRITEBYTECODE=1`, Hypothesis seed `20261114`. Hypothesis/coverage/mypy 임시 상태와 모든 증거는 아래 고유 TEMP에 둔다.
- R13 최종 시험 `test_ai_independent.py`의 실제 raw SHA-256이 전달받은 `d72ad3372143925bcbd459f1fb6a441b0d7609b508a4671a55fcb5b6b96f601d`와 일치함을 시작 전에 확인했다.
- runtime 원시 바이트 hash: main.py `952457b561732cb13b12002390944ee4bce3a50ee63b400b4040099666de11cd`, models.py `67c06b2eb42500d3bf6ffda1f7f2bb7b78ca5f2ac5ca32c5766bb9ed6ba5b384`, ai_bridge.py `3729dcfa48be282bedc1884c2ca4b17669ea8c29798f885dbf1431f347e4f809`. root 동결 신호와 일치한다.

## Snapshot 산식 및 실행 전후 동일성

`rg --files --hidden --no-ignore src tests scripts packaging`으로 목록을 얻고 각 root 아래 `.py`와 `.spec`만 선택한다. 저장소 root의 파일인 `requirements*`, `pyproject.toml`, `.github/workflows/core.yml`을 추가한다. 경로는 저장소 상대 POSIX 형태다. 파일 bytes의 CRLF/CR을 LF로 정규화해 각 SHA-256을 구하고, `{relative_path: lowercase_sha256}` map을 `json.dumps(sort_keys=True,separators=(',',':'),ensure_ascii=True)`의 UTF-8 bytes로 저장한다. tree SHA-256은 그 compact JSON bytes의 hash다. map에는 마지막 LF가 없다.

| 첫 최종 동결 실행 | 실행 전 | 실행 후 |
| --- | --- | --- |
| 파일 count | 132 | 132 |
| tree SHA-256 | `9c7c12f0838362ae558d97220579ae1bfcf2ad7d494d755a6a6d3b2a949ae479` | `9c7c12f0838362ae558d97220579ae1bfcf2ad7d494d755a6a6d3b2a949ae479` |
| map 비교 | 변경 경로 0, bytes 동일 | PASS |

문서 마감과 root의 build/install 작업은 이 source/test/config map과 구분한다. 이 map은 최종 EXE 내부 파일 목록 또는 전체 저장소 commit/tree hash가 아니다.

## 첫 동결 실행 결과

| 검사 | 관측 결과 | 판정 |
| --- | --- | --- |
| 전체 pytest | 1443 PASS / 1 FAIL, 78.20s, skip/xfail 0 | FAIL |
| coverage 결합 표시 | 91.79%, `--cov-fail-under=85` 충족 | PASS |
| separate coverage gate | 아래 핵심 6영역 및 전체 모두 기준 충족 | PASS |
| Ruff check: src tests scripts packaging | All checks passed | PASS |
| Ruff format --check: 같은 범위 | 127 files already formatted | PASS |
| MYPYPATH=src mypy: src/recoryn scripts packaging | 75 source files, no issues | PASS |
| 전후 LF-normalized map | 132/132, 변경 0 | PASS |

| coverage 분모 | line | branch | 기준 |
| --- | --- | --- | --- |
| domain | 100.00% | 100.00% | 95/90 PASS |
| capture | 99.85% | 98.57% | 95/90 PASS |
| jobs | 98.89% | 97.47% | 95/90 PASS |
| storage | 97.92% | 94.72% | 95/90 PASS |
| security | 98.97% | 96.12% | 95/90 PASS |
| content | 99.56% | 98.68% | 95/90 PASS |
| 전체 | 93.37% | 86.89% | 85/80 PASS |

### QA-R15-01 · S2 · OPEN — supervisor status fixture의 부분 JSON 게시 race

실패 시험은 `tests/integration/test_model_runtime_independent.py::test_parent_watch_retires_actual_owned_idle_worker_after_parent_death`다. `_owned_supervisor`가 `Path(status).write_text(...)`로 최종 status 파일을 직접 만들고, `_await_file`은 파일 존재만 확인한다. consumer가 그 사이 빈 파일을 읽어 253행의 `json.loads`에서 `JSONDecodeError: Expecting value: line 1 column 1 (char 0)`가 발생했다. 제품 parent watcher/child 종료 ACK assertion에는 도달하지 못했다. source가 실행 중 변경된 결과도 아니다.

R00에 원인과 수정안을 즉시 보고했다. sibling 임시 파일에 JSON을 완성한 뒤 `replace()`로 게시하는 fixture 교정을 제안했다. R15는 문서만 쓰도록 배정됐고 시험 변경은 먼저 root에 보고하라는 동결 규칙을 따르므로 이 시험을 직접 수정하지 않았다. 제품 결함·인프라 권한 오류로 오분류하지 않으며, 실패한 전체 실행을 최종 PASS로 삼지 않는다. root의 교정과 새 시험 동결 신호 뒤 새로운 전후 map·전체 실행으로 재확인해야 한다. 이전 실패와 당시 map/log는 보존한다.

## 실제 명령과 증거

고유 증거 root는 `C:\Users\gangd\AppData\Local\Temp\recoryn-r15-461406a4510b4d329f2aaf960605e531`이다. 아래 `$r15Evidence`는 이 실제 경로로 설정했다. `snapshot.py`는 위 산식을 구현한 TEMP 전용 스크립트이며 저장소 source를 변경하지 않는다. 모든 native 명령의 `$LASTEXITCODE`는 해당 `*-result.json`에도 기록했다.

```powershell
$r15Evidence = 'C:\Users\gangd\AppData\Local\Temp\recoryn-r15-461406a4510b4d329f2aaf960605e531'
.venv/Scripts/python.exe "$r15Evidence\snapshot.py" "$r15Evidence\before-map.json"
$env:QT_QPA_PLATFORM = 'offscreen'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:HF_HUB_OFFLINE = '1'
$env:HF_HUB_DISABLE_TELEMETRY = '1'
$env:HYPOTHESIS_STORAGE_DIRECTORY = "$r15Evidence\hypothesis"
$env:COVERAGE_FILE = "$r15Evidence\.coverage"
.venv/Scripts/python.exe -m pytest tests -q -p no:cacheprovider --basetemp "$r15Evidence\pytest" --hypothesis-seed=20261114 -W error::ResourceWarning --cov=recoryn --cov-branch --cov-report=term-missing --cov-report="json:$r15Evidence\coverage.json" --cov-fail-under=85 --tb=short
.venv/Scripts/python.exe scripts/check_coverage.py "$r15Evidence\coverage.json"
.venv/Scripts/python.exe -m ruff check --no-cache src tests scripts packaging
.venv/Scripts/python.exe -m ruff format --no-cache --check src tests scripts packaging
$env:MYPYPATH = 'src'
.venv/Scripts/python.exe -m mypy --cache-dir "$r15Evidence\mypy-final-cache" src/recoryn scripts packaging
.venv/Scripts/python.exe "$r15Evidence\snapshot.py" "$r15Evidence\after-map.json"
```

`before-map.json`, `after-map.json`, `comparison.json`, `snapshot.py`, `environment.json`, `pytest.log`, `coverage.json`, `coverage-gate.log`, `final-ruff-check.log`, `final-ruff-format.log`, `final-mypy.log`과 각 exit 결과는 위 TEMP에 보관했다. `evidence-summary.json`은 해당 산출물 raw SHA-256과 coverage 총계를 담는다. 로그는 PowerShell Tee-Object로 수집했다. source/test/config map은 위에 명시한 UTF-8 compact JSON이다.

## 미검증 한계와 통합 경계

합성/fake/offscreen 및 해당 시험이 직접 만든 자식 프로세스만 사용한다. 실제 사용자 음성 캡처, weights/모델 다운로드, 실계정/vault 변경, 실네트워크 AI·유료 호출은 수행하지 않았다. 실제 WASAPI 장비·절전/장시간·Narrator·모델 품질/GPU·실제 daemon 후속 egress·clean VM·서명·G3/G4를 통과 처리하지 않는다.

root가 별도로 최종 candidate build/frozen smoke, 설치·제거, wheel 격리 검증과 Git 통합을 수행한다. 해당 artifact에 대한 root의 실행 결과를 이 source QA의 독립 실행으로 계산하지 않는다. 최종 commit/push와 제품·릴리스 판정은 root 전담이다. 첫 실행 직후에는 fixture 교정·재동결을 기다렸으며 당시 실패를 최종 통과로 삼지 않았다. 아래는 교정 후 새 snapshot의 실제 재확인이다.

## QA-R15-01 수정 후 재동결 최종 실행

수정자 R00, 재확인자 R15. root가 명시 재배정받은 세 시험 파일의 네 writer만 sibling `.tmp` 완성→`replace()` 게시로 바꿨다. `test_model_runtime_independent.py`의 plain PID `.ready` 및 JSON status, `test_ollama_runtime_independent.py`의 합성 descendant status, `test_ollama.py`의 합성 native listener status다. R15는 이 파일들을 수정하지 않았다.

첫 동결 map과 새 시작 map의 변경 경로는 정확히 아래 세 파일뿐이다. 해당 atomic writer 변경을 메모리에서 역적용한 각 파일의 LF 정규화 SHA-256이 첫 map의 각 값과 **모두 일치**했다. 따라서 원 assertion·timeout·나머지 시험 내용, 제품 source/config 변경이 없음을 root 설명과 별도로 확인했다. 점검 코드 `audit.py`와 결과 `refreeze-diff-audit.json`은 새 TEMP 증거 root에 보관했다. 원 테스트를 skip/xfail 처리하거나 재시도로 실패를 숨기지 않았다.

- `tests/integration/test_model_runtime_independent.py`
- `tests/integration/test_ollama_runtime_independent.py`
- `tests/unit/test_ollama.py`

**QA-R15-01: RECHECKED.** 첫 실패가 난 parent-watch 시험이 실제 종료 ACK assertion까지 포함해 통과했고, 아래 전체 기존 pytest도 새 동결 snapshot에서 완료했다. 첫 실패의 132파일 map·로그·coverage는 앞선 TEMP 경로에 그대로 보존한다.

| 최종 재동결 검사 | 결과 | 판정 |
| --- | --- | --- |
| 전체 pytest | **1444 PASS / 71.82s**, 실패·skip·xfail 0 | PASS |
| coverage | line **8071/8644=93.37%**, branch **2419/2784=86.89%**, 결합 표시 91.79% | PASS |
| scripts/check_coverage.py | domain/capture/jobs/storage/security/content 및 all: 위 표와 같은 수치, 전부 기준 충족 | PASS |
| Ruff check | src tests scripts packaging | PASS |
| Ruff format --check | 같은 범위 127 files already formatted | PASS |
| MYPYPATH=src mypy | src/recoryn scripts packaging, 75 source files | PASS |
| 실행 전후 count | **132 / 132** | PASS |
| 실행 전후 tree SHA-256 | 양쪽 모두 **`c3a9df87b4545e016652ad13c01605bba1ac6870d8f594ad884a613b20673b64`** | PASS |
| compact JSON map 비교 | bytes 동일, 변경 경로 0 | PASS |

최종 실행 환경·seed·명령 인자는 위 첫 실행과 같다. root의 TEST REFREEZE 뒤 새 고유 TEMP `C:\Users\gangd\AppData\Local\Temp\recoryn-r15-refreeze-7590e5ddbd7c4332b88d520e07f107b7`를 만들고, 위 명령 블록의 `$r15Evidence`를 이 경로로 지정해 실제 전체 명령을 다시 실행했다. pytest의 basetemp, coverage 파일/JSON, Hypothesis 및 mypy cache도 모두 이 새 root를 사용했다. 세 정적 검사는 새 시작 map 뒤 독립 병렬 실행했고 종료 map은 pytest·coverage gate 및 정적 검사 완료 후 생성했다. 모든 명령 exit code는 0이다.

최종 증거 경로와 raw SHA-256:

| 새 TEMP root 아래 파일 | SHA-256 |
| --- | --- |
| before-map.json / after-map.json | c3a9df87b4545e016652ad13c01605bba1ac6870d8f594ad884a613b20673b64 |
| comparison.json | b4cf84c849421a9e00d22dfcd32040b61bcc4441e448eb0d8b7a315e799d6074 |
| pytest.log | ff36cc1435131f8982e7b73fe4520a8c7aa76dc8f6ba4adbad8231957a390dcc |
| coverage.json | 137572e7a1df978939e6566834fd0b9e771098b890cfa39c32b9217a12f2d204 |
| coverage-gate.log | 83ce0b00e412f07f345558c75ba50164f86a6a3af3d50d51bec67d719d82c81e |
| refreeze-diff-audit.json | 63489b3280cea00fb577aca140472f85bb426f686399a92f857e831ac54e39c2 |
| snapshot.py | 25c0f1224f892bbe1267827b6e4cc2560816a98dea142651ea05e0d6aa5e9549 |

`environment.json`, `final-ruff-check.log`, `final-ruff-format.log`, `final-mypy.log`와 exit 결과 JSON은 같은 root에 있다. 나머지 산출물 hash는 `evidence-summary.json`에 기록했다. 별도 root의 첫 실행 증거를 덮어쓰지 않았다.

지정 QA 범위의 남은 OPEN S0/S1/S2는 0건이다. R13의 BR23 독립 검토 근거와 R15 aggregate 실행을 연결하며 자신의 보안 작성분을 단독 최종 승인하지 않는다. **R15는 이 문서만 수정하고 REVIEW_READY로 제출한다.** 제품·시험·config·Git 수정 및 commit/push는 수행하지 않았다. 위 미검증 한계는 그대로 유지한다. root의 artifact 설치/제거·최종 후보·최종 Git snapshot 통합과 원격 push가 이 QA의 뒤 단계다.
