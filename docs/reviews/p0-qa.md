# P04 P0.1 독립 QA·보안 검토 및 실행 증거

상태: **REVIEW_READY — 독립 테스트·리뷰 완료, 전체 G1 종결은 별도**. 범위는 표준 라이브러리 runtime의 합성 녹음 코어이며 실제 Windows 오디오·API·비밀·모델은 사용하지 않는다. 정본은 [P0 계약](../implementation/p0-contracts.md)이다. P04는 owner 코드·pyproject·Git 인덱스를 수정하지 않는다. P11/P12의 발견 사항은 원 검토자가 재확인한다.

## 독립 oracle와 실행 범위

수학적으로 정한 PCM bytes·frame 수와 deque 모델을 기대값으로 사용한다. 원본 불변은 파일 bytes/hash, pause 전후는 별도 epoch와 표식 PCM, queue loss는 입력/accepted/drop의 독립 회계로 확인한다. subprocess는 셋째 payload만 fsync한 경계·셋째 journal 레코드 fsync 뒤·bundle 게시 뒤·카탈로그 commit 뒤에서 barrier로 정지시킨 후 실제 `kill()`하고 새 Library로 복구한다. 첫 경우에는 앞의 두 블록 8 frames만, 나머지는 세 블록 12 frames를 byte oracle과 대조하고 반복 복구의 중복도 검사한다. 이는 process kill 시험이며 물리 전원 장애 시험이 아니다.

네트워크 시험은 새 Python 프로세스에 audit hook을 import 전에 설치하고 DNS 양성 대조를 실제 resolver 진입 전에 차단하여 observer가 동작하는지 확인한다. 앱 import/help의 socket 시도와 파일 생성이 없어야 한다. 별도 subprocess에서 simulate/list/inspect/recover/export/delete/삭제 뒤 recover까지 실행하며 socket 시도 0을 확인한다. pytest 통합 fixture도 DNS·connect를 차단하며 예외가 삼켜져도 시도를 실패로 집계한다. OS packet capture·악성 native 코드의 비유출 증명으로 확대하지 않는다.

## 발견 사항과 수정 요청

| ID | 심각도·상태 | 재현·영향 | owner 수정 요청 / 회귀 시험 |
| --- | --- | --- | --- |
| P04-01 | S1 RECHECKED | drain 후 `record_capture_health`에 OSError 주입 시 writer가 종료되고 gate가 닫혔는데 Session이 RECORDING으로 남았음 | P00 수정 후 원 테스트 PASS. HEALTH_PERSISTENCE_FAILED와 INTERRUPTED 전이 시도를 코드·실행으로 확인. `test_capture_health_write_failure_cannot_leave_recording_state` |
| P04-02 | S1 RECHECKED | start의 RECORDING 전이에 OSError 주입 시 먼저 만든 non-daemon writer가 살아 남았음 | P00 수정 후 원 테스트 PASS. 실패 시 queue close+writer join 뒤 오류 반환 확인. `test_failed_start_does_not_leak_a_live_writer` |

최초 실행: `.venv/Scripts/python.exe -m pytest tests/integration tests/property -q -p no:cacheprovider` → **25 passed, 2 failed**. 위 두 실패는 실제 구현 준비 후 재현한 결과이며 초기 미완성 import 오류가 아니다. 테스트의 finally에서 writer를 정리하여 시험 자체가 프로세스를 남기지 않는다.

threshold seal/register의 writer 소유권 유지와 fragment 끝에서의 rotate 보강은 P00 수정 후 독립 회귀로 확인했다. chunk ID의 사전순과 반대인 source sequence의 WAV 순서, sequence overlap 거부도 P03 수정 후 실제 실행으로 확인했다. 이 항목들을 수정 전 실패까지 직접 실행한 것으로 기록하지 않는다.

엄격 warning 진단에서는 `tests/unit/test_storage.py`의 `sqlite3.connect` 할당을 추적하여 연결 미정리 ResourceWarning을 확인했다. 해당 owner가 `closing(...)`으로 정리한 뒤 ResourceWarning/PytestUnraisableExceptionWarning을 오류로 승격한 전체 실행이 통과했다. OS temp ACL의 전역 pytest temp 문제는 UUID basetemp로 분리했으며 제품 결함으로 집계하지 않는다.

## 소유 산출물과 독립 코드 리뷰

| 파일 | 검증 대상 |
| --- | --- |
| `tests/property/test_queue_model.py` | deque 기준 slot/byte 포화·drop-newest·close 뒤 privacy rejection, 100개 결정적 Hypothesis example |
| `tests/property/test_pcm_storage_oracle.py` | 4 PCM sample type·독립 rate/channel·가변 분할, 원본 bytes·frame 합·반복 복구, 30개 example |
| `tests/integration/conftest.py` | in-process DNS/connect 금지 및 삼킨 예외의 시도 감지 |
| `tests/integration/test_process_crash.py` | 실제 child kill 4경계, 새 Library prefix 복구·원본·중복·다른 프로세스 writer lock |
| `tests/integration/test_storage_integrity.py` | valid checksum을 재계산한 epoch/offset/sequence/frame 손상, prefix·삭제 intent·stale bundle·FINALIZED orphan·manifest 실패/손상 복구 |
| `tests/integration/test_job_publication.py` | 실제 공유 SQLite의 두 연결, 취소/완료 양 순서·stale fence·재시작·동시 claim |
| `tests/integration/test_app_service.py` | pause/resume epoch·cutoff·포화 drop 마지막 누계·ack timeout·저장/health/start 실패·jobs 격리·export PCM/경로/no-overwrite·gap mapping |
| `tests/integration/test_network_boundary.py` | import/help 부작용 부재와 전체 합성 CLI lifecycle의 audit observer·양성 대조 |

읽은 고위험 구현은 `app/recording.py`, `cli.py`, `storage/{_safe,_coordination,chunks,library}.py`, `jobs/__init__.py`, domain/capture 경계다. 최신 export의 정상 연속·sequence gap·device-position gap·backend discontinuity를 한 chunk 안의 독립 2-frame PCM 두 개로 시험했다. WAV part 수·샘플·frame 수·source chunk frame/output frame/capture time/sequence mapping이 맞고 원본은 불변이다. gap 위치를 조용히 압축한 하나의 연속 WAV를 수락하지 않는다.

P11 발견의 지연 writer 삭제 후 생성 금지·손상 projection 재생성을 독립 테스트에 추가하여 통과를 확인했으나, [P11 리뷰](p0-storage-review.md)의 원 반례·경합 재확인을 대신 종결하지 않는다. [P12 리뷰](p0-jobs-review.md)도 해당 검토자의 재확인이 필요하다. partial fragment는 정상 seal/strict verify와 보존할 복구 증거를 구분해야 하며 원 작성자·P11의 정책/회귀 확인을 따른다.

## 실행 증거와 G1 판단

환경은 Windows, Python 3.13.1, `.venv/Scripts/python.exe`다. pytest/Hypothesis/coverage/Ruff/mypy는 root가 설치한 dev 도구이며 runtime 의존성은 추가하지 않았다. 최소 Python 3.11 문법은 Ruff/mypy 설정으로 검사했고 3.11 interpreter 자체 실행은 미실시다.

실행 명령과 최종 snapshot/coverage 수치는 아래 최종 기록에 남긴다. source가 변경되면 관련 실행을 다시 요구한다. 핵심 domain/storage/jobs/security의 line 95%·branch 90%, 전체 line 85%·branch 80% 목표를 관측 결과에 맞춰 낮추지 않는다. security runtime 모듈은 이번 증분에 존재하지 않아 그 분모와 보안 전체 기능을 검증한 것으로 계산하지 않는다.

P04의 실행 반례 2건은 RECHECKED이며 P04가 직접 재현한 미해결 S0/S1은 없다. 그러나 coverage 목표 부족·다른 독립 리뷰의 열린 발견/재확인·최신 공통 snapshot의 전체 정적 검사가 남으면 **G1 전체 PASS를 선언하지 않는다**. 실제 장치 W01~W05/G3/G4, 물리 전원 장애, native 악성 코드·OS 수준 egress 격리, 모든 동시 reparse 교체, 장시간 성능은 이번 범위 밖의 열린 게이트다.

## 최종 실행 기록 — 2026-11-14

P04 소유 테스트는 **49개 수집**, 최신 export 보강까지 포함한 integration/property/e2e 부분 실행은 **63 passed in 12.25s**였다. 이어서 전체 unit/integration/property/e2e를 직접 실행한 결과는 **379 passed in 21.45s**, exit code 0이다. ResourceWarning과 PytestUnraisableExceptionWarning을 오류로 승격했으며 앞서 확인한 SQLite 연결 경고는 재발하지 않았다. 초기 25/2 실패 결과를 최종 통과로 덮어 쓰지 않고 위에 보존했다.

```powershell
$env:COVERAGE_FILE = 'D:\project\Recoryn\tests\integration\.coverage-p04'
$p04Base = Join-Path ([System.IO.Path]::GetTempPath()) ('recoryn-p04-release-check-' + [guid]::NewGuid().ToString('N'))
& .venv/Scripts/python.exe -m pytest tests --cov=recoryn --cov-report=term-missing --cov-report=json:tests/integration/.coverage-p04.json -q -p no:cacheprovider -W error::ResourceWarning -W error::pytest.PytestUnraisableExceptionWarning --basetemp $p04Base
& .venv/Scripts/python.exe scripts/check_coverage.py tests/integration/.coverage-p04.json
& .venv/Scripts/python.exe -m mypy src/recoryn tests/integration tests/property
& .venv/Scripts/python.exe -m ruff check src tests
& .venv/Scripts/python.exe -m ruff format --check src tests
```

결과: coverage gate PASS, mypy **23 source files PASS**, Ruff check PASS, format check **29 files PASS**. P04 소유 파일만 format했으며 타 소유 파일의 초기 import/format 지적은 owner 수정 후 위 읽기 전용 검사로 재확인했다.

| 실제 측정 분모 | line | branch | 목표 / 판정 |
| --- | --- | --- | --- |
| domain | 100.00% | 100.00% | 95% / 90% PASS |
| capture | 100.00% | 100.00% | 95% / 90% PASS |
| jobs | 100.00% | 100.00% | 95% / 90% PASS |
| storage(5개 파일, coordination 포함) | 98.13% | 95.32% | 95% / 90% PASS |
| 전체 recoryn runtime | 1637/1670 = 98.02% | 486/514 = 94.55% | 85% / 80% PASS |

coverage의 line+branch 종합 표시는 **97.21%**이며 위 두 비율과 혼동하지 않는다. 앞선 실행의 coverage 미달은 owner의 의미 있는 unit/fault 보강 이후 해소됐고 목표나 분모 제외를 낮춰 통과시키지 않았다. subprocess patch로 정상 CLI child 실행도 수집했다. 강제 kill child의 coverage 저장은 보장되지 않으므로 실제 frame/byte 복구 oracle과 분리한다. 실행 artifact는 `tests/integration/.coverage-p04.json`, SHA-256 `24C19A8A4296B650FFEB1E3DC48CC162131713DD4C9D52FF893F5D5F4D710EA3`이다.

실행 전후 `src/**/*.py`, `tests/**/*.py`, `pyproject.toml` **30개 파일의 SHA-256이 모두 동일**했다. 그 snapshot의 tree digest는 `030BDB839EB831693D74BF059CA68F305659489B00B2F716F00C0007C8EBFE18`이다. 산식은 각 파일의 `상대 POSIX 경로 + 공백 + 소문자 SHA-256`을 ordinal 정렬하고 LF로 연결한 뒤 마지막 LF를 포함한 UTF-8 bytes에 SHA-256을 적용한다. 이 범위에 문서·CI·coverage artifact·실장비는 포함하지 않는다.

정본 계약 문서는 실행 중 scripts 소유권/coverage gate를 명시하는 문구가 추가돼 별도 재독·대조했다. 기능 API 변경은 없으며 최종 계약 SHA-256은 `D8F5E36C4B5EAD9F9FC0FCE56EC7218302B8833E75103D9B3FA35E3608F3BDC2`다. 새 검사 스크립트를 읽고 위 artifact에 직접 실행하여 모듈별 line/branch의 원래 목표 통과를 확인했다.

**P04 인계 판단:** 독립 49개 사례, 앱 2건의 수정 재확인, 전체 실행·타입·정적 검사·현재 분모의 coverage 목표는 통과했다. 인계 직전 P11의 후단에서 P11-01~03 **3/3 RECHECKED**를 확인했으며 storage 4개 구현 파일의 실제 해시가 그 재확인 표와 일치했다. 앞서 남았던 P11 재확인 대기는 해소됐고 P12-01도 원 P12 검토자의 후단 RECHECKED 기록을 확인했다. 이 기록들의 종결을 P04가 대신 승인한 것은 아니다. 현재 P04 범위의 미해결 S0/S1·정적 검사·coverage 차단은 없다. D00은 최종 통합 snapshot과 원 검토자의 결과를 연결한 뒤에만 전체 G1/통합·출판 상태를 갱신해야 한다. P04는 Git 작업·최종 push·자기 코드의 단독 최종 승인을 수행하지 않았다.
