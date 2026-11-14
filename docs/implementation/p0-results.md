# P0.1 녹음 코어 구현 및 검증 결과

검증일: 2026-11-14. 버전: `0.2.0.dev1`. 상태: **P0.1 구현·로컬 검증·독립 리뷰 종결 완료**. 범위는 [구현 계약](p0-contracts.md)의 합성 녹음 코어다. 실제 WASAPI·PySide6·STT/LLM·클라우드 및 Windows 실장비 게이트는 완료하지 않았다.

## 구현한 실행 경로

44.1 kHz mono와 48 kHz stereo 합성 입력을 독립 트랙으로 생성하고 제한된 queue를 통해 writer thread에 전달한다. frame·byte 상한과 drop-newest 계수, 별도 close 경로 및 cutoff 이후 입력 거부를 구현했다. pause는 writer drain/seal 확인 뒤 영속 전이하고 resume은 새 epoch를 만든다. 시작·저장·건강 상태 영속화 실패를 성공 녹음으로 표시하지 않는다.

원본은 `audio.pcm + blocks.jsonl + descriptor.json` bundle이다. journal은 canonical JSON과 record/payload SHA-256, sequence·fragment·offset·format 검증을 사용한다. 파일 게시→SQLite 등록→manifest projection 순서를 지키며 manifest-only 실패는 원본 FINALIZED와 분리한다. 정상 packet prefix만 복구 산출물에 편입하고 미완성 fragment를 포함한 원 staging은 보존·격리해 정상 완료로 취급하지 않는다.

SQLite는 세션 전이·health·청크·삭제 의도와 Job/Attempt를 영속화한다. Job 취소/완료와 fence, 제한된 재시도, 오래된 attempt의 게시 차단 및 create 요청의 영속 receipt를 구현했다. 실제 추론 worker나 원격 호출은 없다. 삭제와 지연 writer는 공통 조정 경계에서 의도를 검사하고, 삭제 tombstone이 있는 미디어를 복구로 부활시키지 않는다.

CLI는 simulate/list/inspect/recover/export/delete를 제공한다. export는 검증된 정수 PCM만 새 디렉터리에 기록하고 원본을 바꾸지 않는다. 트랙·epoch 및 sequence/device position/backend flag의 불연속을 구분해 WAV를 나누며 원본 chunk frame↔출력 frame·capture time 매핑을 `export.json`에 남긴다. 완료 표식 없는 부분 export를 성공으로 표시하지 않는다.

## 최종 로컬 검증

환경은 Windows의 Python 3.13.1이다. Python 3.11 문법·타입은 검사했으며 별도 3.11 interpreter 실행과 GitHub Actions 원격 실행 결과는 이 로컬 증거에 포함하지 않는다. 개발 의존성의 확인 버전은 [requirements-dev.txt](../../requirements-dev.txt)에 고정했다.

| 검사 | 결과 |
| --- | --- |
| pytest 전체, warning 오류 처리 | 379 passed, 실패·skip 없음 |
| domain | line 100%, branch 100% |
| capture | line 100%, branch 100% |
| jobs | line 100%, branch 100% |
| storage | line 98.13%, branch 95.32% |
| 전체 runtime | line 98.02%, branch 94.55%; coverage의 결합 표시는 97.21% |
| 커버리지 게이트 | 핵심 package별 95/90, 전체 85/80을 분리 검사해 모두 PASS |
| Ruff lint 및 format | src/tests/scripts 통과 |
| mypy strict | runtime 15개 파일과 검증 script 1개 통과 |
| 2초 합성 CLI smoke | mic 88,200 frames, system 96,000 frames, drop 0, FINALIZED·manifest pending false |
| wheel 빌드와 격리 설치 | runtime 의존성 없이 새 venv·저장소 밖 cwd에서 실행·export·pip check 통과 |

실행한 전체 회귀 명령은 다음과 같다. `$recorynTestRun`과 coverage 파일은 매 실행 고유한 OS 임시 경로다. 기존 다른 세션의 pytest temp ACL이나 파일을 변경하지 않았다.

```powershell
$recorynTestRun = Join-Path $env:TEMP ('recoryn-root-final-' + [guid]::NewGuid().ToString('N'))
$env:COVERAGE_FILE = Join-Path $env:TEMP ('recoryn-root-final-' + [guid]::NewGuid().ToString('N') + '.coverage')
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp $recorynTestRun --tb=short -W error --cov=recoryn --cov-branch --cov-report=term-missing --cov-report=json:coverage.json --cov-fail-under=85
.\.venv\Scripts\python.exe scripts/check_coverage.py coverage.json
.\.venv\Scripts\python.exe -m ruff check src tests scripts
.\.venv\Scripts\python.exe -m ruff format --check src tests scripts
.\.venv\Scripts\python.exe -m mypy src/recoryn scripts/check_coverage.py
.\.venv\Scripts\python.exe -m pip wheel --no-deps --wheel-dir dist .
```

자동 시험은 실제 네트워크나 음성 장치를 사용하지 않는다.

## 독립 교차 검증과 발견 사항

| ID | 문제 | 수정과 재확인 |
| --- | --- | --- |
| P04-01 / S1 | health 저장 실패 뒤 RECORDING 잔류 | INTERRUPTED 전이, 원 QA 시험에서 RECHECKED → CLOSED |
| P04-02 / S1 | start 전이 실패 뒤 writer thread 잔류 | queue close와 join, 원 QA 시험에서 RECHECKED → CLOSED |
| P12-01 / S2 | dedup 생성 요청 재전달로 취소 뒤 새 Job 생성 | 영속 receipt, 원 P12의 다른 연결·재시작 oracle로 RECHECKED → CLOSED |
| P11-01 / S1 | 삭제 성공 뒤 지연 writer의 물리 원본 재생성 | 공통 mutex와 intent/세대 검사, 원 P11의 지연 open·양 순서 재현으로 RECHECKED → CLOSED |
| P11-02 / S2 | 마지막 fragment 누락을 정상 봉인 | strict 봉인 거부·완성 packet prefix와 staging 보존, 원 P11의 반복 복구로 RECHECKED → CLOSED |
| P11-03 / S2 | 손상 manifest가 재생성을 차단 | 손상 projection 격리·DB 재생성·미래 schema 보호, 원 P11의 재export로 RECHECKED → CLOSED |

P11~P14의 실제 재확인 결과와 최종 source digest를 대조해 6건을 통합 종결했다. 설계 단계의 24건과 구현에서 발견한 6건은 별도 기록이다. 과거 OPEN 기록은 이력으로 유지하며 해당 리뷰 후단의 재확인이 최신 판정이다.

| 독립 검토 | 직접 실행한 관련 시험 | 결과 |
| --- | --- | --- |
| [P11 저장·복구](../reviews/p0-storage-review.md) | 122 passed 및 별도 지연 writer/fragment/manifest probe | 원 발견 3/3 RECHECKED, 미해결 0 |
| [P12 domain/jobs](../reviews/p0-jobs-review.md) | 161 passed 및 별도 receipt/동시 연결 probe | 원 발견 1/1 RECHECKED, 미해결 0 |
| [P13 capture](../reviews/p0-capture-review.md) | 68 passed, 24개 허용 순서 oracle와 64회 concurrency probe | 신규 발견 0 |
| [P14 독립 QA](../reviews/p0-qa.md) | 독립 사례 49개와 전체 379 passed | 앱 발견 2/2 RECHECKED, 커버리지·타입·정적 검사 통과 |

각 행의 시험은 서로 겹치므로 합산하지 않는다. 최종 검토 digest는 실제 파일과 모두 일치했다. P14가 실행 전후 동일성을 확인한 src/tests/pyproject 30개 파일의 tree digest는 `030BDB839EB831693D74BF059CA68F305659489B00B2F716F00C0007C8EBFE18`이며 P00도 같은 산식으로 재현했다. 상세 산식과 독립 실행 근거는 P14 기록에 있다.

## 빌드와 검토 snapshot

wheel: `dist/recoryn-0.2.0.dev1-py3-none-any.whl`, 40,641 bytes. SHA-256: `8aae9d7c340e9a066accf8805c58aace834aa685d62b00d3104d2f21e57fb466`. 최종 README를 포함한 이 artifact를 격리 venv에 다시 설치해 simulate/export와 pip check를 확인했다.

runtime source 15개와 wheel 내부 Python 파일을 LF 정규화 후 모두 대조해 일치를 확인했다. runtime tree SHA-256은 `02607b32dcec2f3d6079a62040360a02f91ab7dcbae1ba1701e09b2a15dd88fd`다. 계산은 `src/recoryn/**/*.py`의 repository 상대 POSIX 경로→LF 정규화 파일 SHA-256 map을 정렬된 compact JSON으로 만든 뒤 그 UTF-8 bytes의 SHA-256을 취한다. 이 값은 비트 단위 재빌드 재현성 보장이 아니며 source가 바뀌면 시험·artifact 연결을 다시 확인해야 한다.

## 남은 게이트와 다음 배정

- 실제 WASAPI backend 선정과 native format/QPC 시계·장치 변경·절전·Bluetooth·장시간·드리프트 검증은 P0 후속이다. 현재 합성 시계 시험은 실제 장치 정확도 시험이 아니다.
- timestamp 정렬·리샘플링·파생 mix, 실제 AI 프로세스·GPU scheduling, provider 동의 gateway·vault와 PySide6 UI는 아직 구현하지 않았다.
- process kill·ENOSPC·flush 오류 주입은 물리 전원 차단·저장장치 고장 보장이 아니다. path 검사는 같은 사용자 권한의 악성 프로세스와 경합하는 OS sandbox를 제공하지 않는다.
- 명시적 create 요청의 receipt 외 모든 명령의 정확히 한 번 실행, 원격 과금·철회·삭제는 구현하지 않았다. JobStore는 실제 worker 수명·원격 상태를 추정하지 않는다.
- JobStore에 세션 연결 정보가 없는 초기 계약이므로 소유권 불명의 실행 중 작업이 있으면 세션 삭제를 보류한다. 자동 Job 정리나 원격 중단을 성공했다고 표시하지 않는다.
- G1 중 이 증분의 offline 코드·계약 회귀와 G2의 명시한 파일/DB/프로세스 장애만 검증했다. 전체 제품 P0, G3와 G4, VM·EXE·서명·SBOM/모델 재배포 검토는 열려 있다.
- [Windows CI](../../.github/workflows/core.yml)는 Python 3.11/3.13, 최소 권한과 고정 action commit으로 준비했다. 원격 실행 여부는 실제 run 결과로 따로 판정한다.
