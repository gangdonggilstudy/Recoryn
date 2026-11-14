# Recoryn

Recoryn은 Windows에서 마이크와 시스템 소리를 분리 녹음하고, 로컬 AI 또는 사용자가 선택한 제공업체로 전사·요약하는 오픈소스 데스크톱 앱을 목표로 합니다. 녹음 보존, 외부 전송에 대한 사용자 통제, 원본 시간 위치까지 확인할 수 있는 기록을 우선합니다.

현재 **Windows 캡처·AI·보안 엔진과 기본 데스크톱 화면을 통합하는 개발 단계**입니다. `0.2.0.dev2`는 개발 체크포인트이며 설계 v1.0 전체 구현·실장비·공식 릴리스 검증은 계속 진행합니다. [현재 구현 및 검증 기록](docs/implementation/product-results.md)에 완료 범위와 미검증 사항을 구분합니다. 저장소 소스 라이선스는 [Apache 2.0](LICENSE)이며 번들 의존성과 모델의 배포 조건은 별도로 검토합니다.

## 실행

Python 3.11 이상이 필요하며 로컬 개발 검증은 Windows의 Python 3.13.1에서 수행합니다. 기본 녹음 코어는 표준 라이브러리를 사용하고, 데스크톱과 로컬 AI는 선택 의존성입니다. 개발 도구 설치는 인터넷을 사용하지만 아래 합성 CLI 명령은 오디오 장치나 외부 API에 연결하지 않습니다.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt

$recorynData = Join-Path $env:TEMP ('recoryn-demo-' + [guid]::NewGuid().ToString('N'))
$recorded = .\.venv\Scripts\python.exe -m recoryn --root $recorynData simulate --seconds 2 | ConvertFrom-Json
.\.venv\Scripts\python.exe -m recoryn --root $recorynData list
.\.venv\Scripts\python.exe -m recoryn --root $recorynData inspect $recorded.session_id
.\.venv\Scripts\python.exe -m recoryn --root $recorynData recover $recorded.session_id

$recorynExport = Join-Path $env:TEMP ('recoryn-export-' + [guid]::NewGuid().ToString('N'))
.\.venv\Scripts\python.exe -m recoryn --root $recorynData export $recorded.session_id --output $recorynExport
```

`simulate`는 44.1 kHz mono 마이크 역할과 48 kHz stereo 시스템 역할의 테스트 신호를 생성합니다. 실제 주변 소리는 녹음하지 않습니다. `--root`를 생략하면 사용자 로컬 앱 데이터 경로를 사용합니다. 삭제하려는 세션 ID를 지정한 `delete` 명령은 라이브러리 내 원본·파생 자료를 삭제하고 최소 삭제 의도를 남깁니다. 이미 내보낸 복사본은 별개입니다.

export는 새 출력 디렉터리만 허용하고 트랙·epoch별 정수 PCM WAV를 만듭니다. sequence·장치 위치·backend flag의 불연속이 있으면 파일을 나누며 원본 구간과 출력 frame 매핑을 보존합니다. pause나 유실 구간을 숨겨 이어 붙이지 않습니다. `export.json`이 완료 표식과 출처 목록이며 중간 실패로 표식 없는 파일이 남을 수 있습니다. 현재 저장 경로 보호는 협력하는 프로세스의 잘못된 경로를 막는 수준이며 같은 사용자 권한의 악성 프로세스와 물리 디스크 장애에 대한 보호를 보장하지 않습니다.

## 개발 검증

데스크톱은 `python -m pip install -e '.[desktop]'` 후 `python -m recoryn gui`로 실행합니다. 장치 새로고침·선택 뒤 녹음 버튼을 눌러야 캡처를 시작합니다. 로컬 전사는 `.[local-ai]`와 이미 설치한 모델 폴더를 사용하며 모델을 암묵적으로 다운로드하지 않습니다. 클라우드 전사와 요약은 제공업체·endpoint·데이터 종류별 동의와 별도의 예산 설정이 필요합니다. 실제 모델·API 계정·Windows 오디오 장치 호환성은 아직 검증 전입니다.

확정 청크의 실시간 임시 전사, 전체 정정 전사와 사용자 편집본을 구분하며, 늦은 AI 결과로 선택한 편집본을 덮어쓰지 않습니다. 취소·원격 결과 미확인 작업은 자동으로 재전송하지 않고 명시 재실행을 요구합니다. 로컬 Ollama는 사용자가 지정한 실행 파일과 이미 설치된 로컬 모델을 검증한 뒤 앱이 직접 소유한 서버로 시작합니다. 준비·검사·AI 처리와 녹음 제어는 별도 worker에서 처리합니다.

선택 화자 구분은 `.[diarization]`으로 설치하며 Windows x64·Python 3.12 이상 CPU에서만 지원합니다. 사용자가 별도로 준비한 manifest·모델·라이선스와 선택한 5분 이하 오디오 범위를 사용하고, 익명·불확실 추정 라벨을 새 파생 전사 revision으로 저장합니다. 모델을 자동 다운로드하거나 사람 신원을 식별하지 않습니다. 실제 모델의 정확도와 음성 품질은 미검증입니다.

```powershell
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m mypy src/recoryn
$recorynTestRun = Join-Path $env:TEMP ('recoryn-tests-' + [guid]::NewGuid().ToString('N'))
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp $recorynTestRun --cov=recoryn --cov-branch --cov-report=json:coverage.json
.\.venv\Scripts\python.exe scripts/check_coverage.py coverage.json
```

독립 시험은 합성 PCM oracle, 실제 subprocess 종료 후 복구, 포화·cutoff, 작업 취소/게시 경쟁과 원본 불변을 확인합니다. 기본 pytest 임시 폴더를 여러 세션이 공유할 때는 위처럼 고유한 `--basetemp`를 사용합니다. Windows 실장비, 장시간·절전, 모델 품질, 설치 EXE의 검증을 이 결과로 대체하지 않습니다. 상세 범위는 [P0.1 구현 계약](docs/implementation/p0-contracts.md)에 있습니다.

## 설계 문서

- [아키텍처와 전문가 검토 v1.0](docs/architecture-v1.md)
- [사용자 설계 요구사항](docs/design-input-v1.md)
- [검증 계획과 릴리스 게이트](docs/validation-plan.md)
- [전문가 팀의 품질 및 교차 검증 체계](docs/quality-system.md)
- [P0.1 구현과 실행 검증 결과](docs/implementation/p0-results.md)
- 전문가 검토: [아키텍처](docs/reviews/architecture.md), [오디오와 복구](docs/reviews/audio-recovery.md), [AI와 UX](docs/reviews/ai-ux.md), [보안과 QA](docs/reviews/security-qa.md)

## 세션 협업

새 세션은 [AGENTS.md](AGENTS.md)와 [온보딩](docs/collaboration/onboarding.md)부터 읽고, [협업 규칙](docs/collaboration/workflow.md)과 [작업 배정표](docs/collaboration/assignments.md)에 따라 작업합니다. 작업 세션은 지정 파일만 수정하며, 오케스트레이터가 결과 통합과 최종 검증 후 commit 및 push를 수행합니다.
