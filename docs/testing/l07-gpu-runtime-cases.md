# L07 GPU 런타임 앱 내 받기 경우의 수

2026-11-15, 작성 C00. 배정 L07 / push L-P07. 근거는 [라이선스 검토 L01](../implementation/license-review.md)의 D10이다. 이 문서는 시험 설계와 분모를 정의하며 통과 결과는 [L 결과](../implementation/license-results.md)에 기록한다. 1차 독립 검토([다운로드 검토](../reviews/l07-gpu-download-review.md) L07-01~05, [화면 검토](../reviews/l07-gpu-ui-review.md) L07-U01~U05)를 반영한 2판이다.

## 요구사항과 위험

- **재배포 금지:** Recoryn은 NVIDIA·Intel 코드를 재배포하지 않는다. GPU를 원하는 사용자가 앱에서 약관을 확인하고 동의한 뒤, 공식 배포처(PyPI)에서 직접 받는다.
- **동의 없는 전송 금지:** 동의 전에는 어떤 네트워크 요청도 하지 않는다(기본 무전송).
- **신뢰 기준은 소스:** 받은 파일과 풀린 파일은 소스에 고정한 값(wheel pin, 파일별 catalog)으로만 판정한다. 디스크에 있는 기록(예: 예전 `runtime.json`)은 신뢰하지 않는다.
- **검증한 바이트만 실행:** 실행되는 Python 소스와 DLL은 검증한 그 바이트여야 한다. 검증 뒤에 바뀌거나, 검증 목록 밖 파일이 끼어들거나, bytecode cache·환경 변수 경로를 거쳐 다른 코드가 실행되면 안 된다.
- **기존 경로 보호:** 번들의 CPU 전용 CTranslate2와 섞이지 않는다. GPU를 고른 추론 프로세스만 이 런타임을 쓴다.
- **실패 처리:** 실패는 명시적 오류 코드로 사용자에게 보인다. CPU 허용 정책이면 CPU로 전사하고, GPU 전용 정책이면 전사를 시작하지 않는다.

**위협 경계:** 같은 사용자 권한의 프로세스는 Recoryn 프로세스 메모리에 직접 쓸 수 있으므로, 이 설계는 그에 대한 sandbox가 아니다(`storage._safe.check_path`와 같은 경계). 대신 다음을 보장 대상으로 한다. 활성화 전에 있던 파일, 남은 파일, 활성화 전·중에 바뀐 파일은 검증 없이 로드되지 않는다.

## 고정 계획 M

- **받을 파일 2개:**
  - `ctranslate2-4.9.0-cp313-cp313-win_amd64.whl`: 20,408,731 bytes, SHA-256 `d009840a…ef095`
  - `nvidia_cublas_cu12-12.8.4.1-py3-none-win_amd64.whl`: 567,544,208 bytes, SHA-256 `47e9b821…e35af`
  - 둘 다 `https://files.pythonhosted.org/` 주소다.
- **catalog 11개:** 소스의 `CATALOG`에 파일마다 경로·크기·SHA-256을 고정한다. `scripts/gpu_runtime_catalog.py <wheel 폴더> --check`가 고정 wheel에서 다시 계산해 일치를 확인한다.
  - CTranslate2 wheel 8개: `__init__.py`, `_ext.cp313-win_amd64.pyd`, `ctranslate2.dll`, `libiomp5md.dll`, `extensions.py`, `logging.py`, `models/__init__.py`, `version.py`
  - cuBLAS wheel 3개: `cublas64_12.dll`, `cublasLt64_12.dll`, `License.txt`
- **일부러 풀지 않는 것:** `cudnn64_9.dll`(`ctranslate2.dll`이 이름으로도 참조하지 않는다), `converters`·`specs`(모델 변환용이며 torch 필요), dist-info 나머지다.
- **초기화 블록:** 공식 `__init__.py`의 Windows 블록은 다음 일을 한다. 패키지 옆의 `_rocm_sdk_*` 폴더와 `HIP_PATH`에서 DLL 폴더를 찾고, 패키지 폴더의 모든 `*.dll`을 로드한다. 이 블록의 시작·끝 표지와 SHA-256(`1cf2cac0…5087`)을 고정해 두고, 실행 전에 한 줄로 바꾼다.
- **약관 4개:** 화면에 보일 약관 목록에 다음이 URL과 함께 있다.
  - NVIDIA CUDA Toolkit EULA
  - Intel Simplified Software License(oneMKL)
  - Intel EULA for Developer Tools(OpenMP)
  - CTranslate2 MIT
- **적용 조건:** Python 3.13, Windows x64에서만 쓴다. 다른 환경에서는 GPU_RUNTIME_UNSUPPORTED다.

## 동의·다운로드·취소 D

가짜 다운로더로 판정한다.

- 승인 없이 설치하면 MODEL_DOWNLOAD_REQUIRES_APPROVAL이고, 다운로더 호출은 0회다. 미지원 환경도 0회다.
- 다운로드 hash가 틀리면 활성화하지 않는다.
- **취소 경계 5행(L07-04/U05):** 취소가 게시(폴더 이름 바꾸기) 전에 관측되면 활성 런타임이 없고 staging도 남지 않는다. 게시 뒤의 취소는 늦은 것이며 설치는 성공한다.

| 취소 시점 | 결과 |
| --- | --- |
| 시작 전 | MODEL_DOWNLOAD_CANCELLED, 다운로더 0회 |
| 다운로드 반환 직후 | MODEL_DOWNLOAD_CANCELLED, NOT_INSTALLED |
| 압축 해제 중 | MODEL_DOWNLOAD_CANCELLED, NOT_INSTALLED |
| 게시 직전 | MODEL_DOWNLOAD_CANCELLED, NOT_INSTALLED |
| 게시 뒤 | 설치 성공, READY |

- **큰 파일:** 취소하면 큰 파일도 1 MiB 블록 하나 안에서 멈춘다.
- **정리·재시도 3행(L07-05):**
  - 게시 뒤 받은 묶음 삭제가 실패해도 설치는 성공이고 READY다. 남은 묶음은 다음 설치나 삭제가 지운다.
  - 압축 해제가 일시 실패하면 NOT_INSTALLED다. 재시도는 남은 검증 완료 묶음을 다시 hash한 뒤 재사용하므로, 다시 받지 않는다.
  - 남은 묶음이 손상됐으면 지우고 다시 받는다.

## 압축 해제 X

손으로 만든 zip과 그에 맞춘 가짜 pin·catalog로 판정한다.

- **pin 재확인:** 압축 해제 직전에 각 wheel을 쓰기를 막는 handle로 열어 pin과 다시 대조하고, 그 handle로 읽는다(L07-02).
  - 다운로드 확인 뒤 다른 zip으로 바뀌면 GPU_RUNTIME_ARCHIVE_INVALID다.
  - catalog 밖만 다른 zip도 GPU_RUNTIME_ARCHIVE_INVALID다.
  - Windows에서는 압축 해제 중 wheel에 쓰기를 시도하면 막힌다.
- **catalog 대조:** catalog 파일만 풀고, 쓰는 동안 크기·SHA-256을 catalog와 대조한다.
- **거부 9행(GPU_RUNTIME_ARCHIVE_INVALID):**
  - `../` 경로 탈출
  - 절대·드라이브 경로
  - 역슬래시로 쓴 경로 탈출. Windows의 zipfile은 `\`를 `/`로 바꾸므로 탈출 검사를 받는다.
  - 같은 이름 중복
  - catalog 파일이 symlink 항목
  - catalog 파일 누락
  - CRC 손상
  - 같은 크기에 다른 바이트
  - 크기가 다름
- **목록 밖 항목:** 풀지 않는다. 대상은 cudnn, converters, nvblas, 헤더, dist-info 나머지다.
- **staging과 게시:** staging에서 정확한 파일 집합을 확인한 뒤 한 번의 폴더 이름 바꾸기로 게시한다. 로컬 기록 파일은 만들지 않는다.

## 상태 S와 검증 V

- **상태 판정:** catalog와 정확히 같은 파일·폴더 집합이고 크기가 맞으면 READY다. 런타임이 없으면 NOT_INSTALLED다. 다음 6행은 DAMAGED다.
  - 파일 누락
  - 크기 변경
  - 목록 밖 DLL 추가
  - `__pycache__` 추가
  - `runtime.json` 같은 로컬 기록 추가
  - `_rocm_sdk_core/bin` 폴더 추가
- **전체 검증:** 위 6행에 더해, 같은 크기로 1 byte가 바뀌어도 GPU_RUNTIME_DAMAGED다.

## 활성화 A

가짜 런타임 패키지와 DLL 로드 spy로 판정한다. 실제 DLL은 실제 장비 절에서 따로 확인한다.

- **정상:**
  - Python 소스는 검증한 바이트에서 실행된다(loader는 `_SourceLoader`, bytecode cache를 쓰지 않음).
  - 공식 Windows 블록은 실행되지 않는다.
  - DLL 로드 순서는 System32의 `nvcuda.dll`, `cublasLt64_12`, `cublas64_12`, `libiomp5md`, `ctranslate2.dll`이며 모두 절대 경로다.
  - DLL 폴더 등록은 0개다.
  - 활성화 뒤 `.pyc`가 생기지 않는다.
- **bytecode cache(L07-01 A):** 같은 mtime·크기의 유효한 timestamp pyc를 심는다.
  - 파일 집합 검사로 DAMAGED가 되고, DLL 로드는 0개다.
  - 파일 집합 검사를 일부러 우회해도 실행된 것은 검증한 소스다.
- **목록 밖 DLL(L07-01 B):** 패키지 폴더에 DLL을 추가하면 DAMAGED이고, 드라이버를 포함해 아무것도 로드하지 않는다.
- **환경 경로(L07-01 C):** `HIP_PATH`가 다른 폴더를 가리켜도 DLL 폴더 등록은 0개이고 로드 목록은 정상과 같다.
- **섞임 없음:** sys.path에 다른 `ctranslate2`가 있어도 런타임 것이 import된다. 활성화 뒤 런타임 폴더에 새로 만든 하위 모듈(잠금으로 막을 수 없는 경우)도 import되지 않는다(ModuleNotFoundError).
- **검증과 import 사이(L07-03):** 첫 DLL 로드 시점(검증 직후)에 4가지를 시도하며, 모두 막힌다(Windows).
  - `__init__.py`에 쓰기
  - DLL 삭제
  - 소스 이름 바꾸기
  - 런타임 폴더 이름 바꾸기
- **오류 코드:**
  - `ctranslate2`나 그 하위 모듈이 이미 import됐으면 GPU_RUNTIME_LATE이고 로드는 0개다.
  - 드라이버가 없으면 GPU_RUNTIME_UNAVAILABLE이고 로드는 0개다.
  - 파일이 손상됐으면 GPU_RUNTIME_DAMAGED이고 로드는 0개다.
  - 런타임이 없으면 GPU_RUNTIME_NOT_INSTALLED다.
  - CUDA 장치가 0개면 GPU_RUNTIME_UNAVAILABLE이다.
  - 초기화 블록 hash가 다르면 GPU_RUNTIME_DAMAGED이고 로드는 0개다.

## 삭제 R

- 삭제는 폴더 이름 바꾸기 뒤에 지운다. 남은 `.remove-*`·`.extract-*`는 정리한다.
- 활성화한 작업자가 런타임을 쥐고 있으면 GPU_RUNTIME_IN_USE이고, 런타임은 그대로 READY다(Windows). 놓은 뒤에는 삭제된다.

## 추론 프로세스 W와 장치 선택 U

- **추론 프로세스:**
  - `device="cuda"`인데 런타임이 없으면 요청마다 GPU_RUNTIME_NOT_INSTALLED로 답한다.
  - 부모는 그 코드를 ProviderError로 올리고 `gpu_failure`에 기록한다.
  - CPU 경로와 기존 4인자 작업자 계약은 바뀌지 않는다.
- **후보 판정 `gpu_source`:** 정책 3 × native 2 × 런타임 상태 3 × 런타임 차단 2 = 36행이다. oracle은 구현과 따로 쓴다.
  - CPU_ONLY면 none이다.
  - native가 있으면 native다.
  - 그 밖에 런타임이 READY이고 차단되지 않았으면 runtime이고, 아니면 none이다.
- **실제 창 경로(L07-U01·U02·U03):** 실제 MainWindow·DesktopAI·Task·ResourceScheduler를 거친다. 가짜로 바꾼 것은 GPU 탐지, CUDA 출처, 런타임 상태·세대, 작업자뿐이다.
  - **U01:** 같은 설치에서 작업자 자신의 GPU 실패가 나면, 이번 실행에서는 그 설치를 다시 고르지 않는다. 이후 성공으로도 지워지지 않는다. 다시 받은 설치(세대 변경)는 고른다. 새 실행은 저장된 실패 이력이 있어도 고른다.
  - **U02:** GPU 전용 정책에 GPU가 없으면 작업자를 만들지 않고, 상태 줄에 RESOURCE_GPU_UNAVAILABLE이 보인다. GPU 설치 오류 코드도 Task 경계를 통과한다.
  - **U03:** AI 사용 중에는 삭제 확인을 열지 않는다. 삭제가 대기 중이면 먼저 쥐고 있던 GPU 작업자를 닫는다. 그 사이 시작한 전사는 런타임을 고르지 않는다(CPU 허용 정책이면 CPU).
  - **U06:** 삭제 확인 창은 중첩 event loop를 돈다. 창이 떠 있는 동안 AI 작업이 시작되면, Yes를 눌러도 작업자를 닫거나 삭제를 대기열에 넣지 않는다(창이 닫힌 뒤 다시 확인한다). bridge의 `release_gpu_runtime()`도 AI가 준비·대기·실행 중이면 AI_MODEL_CHANGE_REQUIRES_IDLE로 거부한다.
- **화면(U04):**
  - 약관·크기·위치·동의 칸을 보인다. 동의하지 않으면 작업이 0개이고, 중복 요청은 작업 1개다.
  - 정책 문구는 CPU 허용과 GPU 전용을 나눠 쓰며, 무조건 CPU로 돌아간다는 표현이 없다.

## mutation

수정마다 되돌린 사본이 시험에 걸리는지 확인한다. 런타임 관리 14개, 창 경로 7개다. 목록과 결과는 결과 문서에 기록한다.

## 실제 장비 R

이 PC(RTX 4070 Laptop, 드라이버 576.57)에서 수동으로 확인한다. 결과는 증거로 기록하고, CI에서는 실행하지 않는다.

- **설치:** 실제 PyPI에서 제품 관리자로 588 MB를 받아 검증하고, catalog 11개만 푼다.
- **실행:** 새 프로세스에서 활성화한 뒤 무작위 가중치 Whisper로 GPU float16·float32 인코딩과 생성을 하고, CPU 결과와 비교한다.
- **로드 확인:** 프로세스에 로드된 DLL 목록으로 런타임에서 온 파일과 NVIDIA 드라이버 출처를 확인한다.
- **하지 않는 것:** 실제 음성과 실제 가중치는 쓰지 않는다.

## 주장하지 않는 것

- 다른 GPU나 다른 드라이버 버전, 장시간 사용, 메모리 부족 상황은 확인하지 않는다.
- frozen 앱 안에서 GPU 런타임을 활성화하는 것은 확인하지 않는다(소스 실행에서만 확인).
- 같은 사용자 권한 프로세스의 실행 중 메모리 변조는 막지 않는다.
- 사용자가 약관에 동의한 것이 법률 검토를 대신하지 않는다.
