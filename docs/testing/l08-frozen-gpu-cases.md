# L08 패키지 앱 GPU 활성화 확인의 경우의 수

2026-11-22, 작성 C00. 대상 push 단위는 L-P08이다. L-P07은 GPU 런타임 활성화를 소스 실행에서만 실장비로 확인했고, 패키지(frozen) 앱 안의 활성화는 NOT_RUN으로 남겼다. 이 단위는 그 항목을 확인하는 도구와 시험을 더하며 제품 동작은 바꾸지 않는다. 2판은 독립 검토 L08-01~05를, 3판은 재확인에서 나온 L08-06을 반영했다.

## 목적과 경계

- **확인할 것:**
  - 패키지 앱의 spawn 작업자 프로세스가 제품과 같은 `_activate_gpu`로 사용자 런타임을 활성화하는가.
  - 그 뒤 `ctranslate2`와 faster-whisper가 런타임의 정해진 파일을 쓰는가.
  - 번들 안의 CPU 전용 CTranslate2(L-P06)나 런타임 밖의 cuBLAS가 같은 프로세스에 올라오지 않는가.
  - 로드한 모델 객체가 스스로 보고하는 장치가 CUDA이고 정밀도가 요청과 같은가. float16과 float32가 같은 token을 내는가.
- **도구:** `Recoryn-CLI.exe --release-gpu-smoke --runtime-root <폴더> --model <폴더>`가 사실을 보고한다(`packaging/release_smoke.py`의 `gpu_probe`). 판정은 빌더 쪽 `scripts/gpu_frozen_smoke.py`의 `verdict`가 별도 규칙으로 한다.
- **판정의 한계:** probe의 PASS 문자열 대신 보고된 사실을 따로 판정한다는 뜻이다. 보고 자체의 진위를 외부에서 인증하지는 않는다.
- **하지 않는 것:** 다운로드하지 않는다. 런타임은 이미 설치돼 있어야 하며, 스크립트는 실행 전후에 catalog 대조(`verify`)를 한다. 모델은 seed를 고정한 무작위 가중치 소형 Whisper이며 weights를 받지 않는다. 실제 음성과 품질, 다른 GPU·드라이버는 범위 밖이다.

## A. probe 입력 분할

| 축 | 값 | 실행 위치 |
| --- | --- | --- |
| 실행 형태 | frozen / 소스 | frozen: 실장비. 소스: 단위 시험과 mutation |
| 런타임 | 설치·검증됨 / 없음 | 설치: 실장비. 없음: 단위 시험 |
| Python | 3.13(지원) / 3.11(미지원) | 단위 시험이 두 기대값을 모두 가진다 |
| GPU | 있음(RTX 4070) / 없음 | 있음만 실행. 없음은 L-P07의 activate 시험이 덮는다 |
| 모델 객체의 실제 장치 | 요청대로 / CPU로 떨어짐 | 가짜 CTranslate2 객체로 단위 시험 |
| 모듈 이름 해석 | 전부 됨 / 하나라도 실패 | 단위 시험 |
| 자식 응답 | 시간 안 / 시간 초과 | 둘 다 단위 시험 |

손상·LATE·드라이버 없음 같은 activate 실패는 L-P07의 `tests/unit/test_gpu_runtime.py`가 이미 덮는다. 여기서 반복하지 않고, probe가 그 코드를 그대로 전달하는지만 본다.

## B. 판정(verdict) 결함 표

정상 보고와 단일 결함 보고를 손으로 쓴 기대 코드와 대조한다. 판정은 세 단계다.

1. 필수 사실 11개가 모두 있는지 본다. 하나라도 없으면 `MISSING_<이름>`만 낸다.
2. 사실의 정확한 타입을 본다. bool은 int로 인정하지 않는다. 하나라도 틀리면 `BAD_TYPE_<이름>`만 낸다.
3. 나머지 조건을 모두 본다.

단일 결함 표의 각 행은 결함 하나만 넣으며, 기대값은 그 코드 하나뿐이다.

| 분류 | 결함 | 기대 코드 |
| --- | --- | --- |
| 활성화 | activate 코드 있음 | ACTIVATION_FAILED |
| 실행 형태 | frozen=False / bundle 빈 문자열 | NOT_FROZEN |
| 자식 | exitcode 1 / 누락 / False / 0.0 | CHILD_EXIT_NONZERO |
| 모듈 위치 | module이 번들 안 / 이름만 비슷한 형제 폴더 / 런타임 안 다른 파일 | MODULE_NOT_RUNTIME_FILE |
| 모듈 위치 | `_ext`가 번들 안 / 런타임 안 다른 파일 | EXT_NOT_RUNTIME_FILE |
| 버전 | `4.9.0+recoryn.cpu1`(번들 CPU 빌드) | VERSION_MISMATCH |
| faster-whisper | 다른 ctranslate2 모듈 사용 | FASTER_WHISPER_OTHER_MODULE |
| 실제 실행 | float16 또는 float32가 CPU에서 실행 / device 사실 없음 | RUN_NOT_ON_CUDA |
| 실제 실행 | float16이 float32로 실행 / float32가 int8로 실행 | RUN_COMPUTE_TYPE_MISMATCH |
| 실제 실행 | 장치 번호 범위 밖 / 빈 목록 / bool | RUN_DEVICE_INDEX_INVALID |
| 실제 실행 | 실행 기록이 하나뿐 / dict 아님 | RUNS_MALFORMED |
| 출력 | fp16≠fp32 | FLOAT16_FLOAT32_TOKENS_DIFFER |
| 출력 | 비어 있음, 빈 sequence, compute 하나, 문자열, 평평한 목록, prompt 1개, 3개, bool·None·문자열 token, 음수 token | TOKENS_MALFORMED |
| 로드 집합 | 런타임 DLL 누락 / 런타임의 추가 파일 | RUNTIME_MODULE_SET_MISMATCH |
| 로드 집합 | 번들 `ctranslate2.dll` / 번들 `_ext` / 외부 `libiomp5md.dll` / 외부 `cublas64_12.dll` / 외부 `cublasLt64_12.dll` / 다른 버전 `cublas64_11.dll` / 이름만 비슷한 형제 폴더의 `ctranslate2.dll` | FOREIGN_RUNTIME_LOADED |

- **정확한 타입(14행):** activate 정수, frozen 1, bundle None·정수, module None, ext 정수, version 실수, cuda_devices True·문자열, faster-whisper 1, runs 목록, tokens 목록, loaded None, loaded 안 정수. 각각 `BAD_TYPE_<이름>` 하나만 난다.
- **두 코드가 함께 나는 경우:**
  - 런타임 폴더 안에 cuDNN이 올라오면 집합 불일치와 CUDNN_LOADED가 함께 난다. 런타임 밖 cuDNN은 CUDNN_LOADED 하나만 난다(cuDNN 위치 2행).
  - CUDA 장치가 0개면 어떤 장치 번호도 유효하지 않으므로 NO_CUDA_DEVICE와 RUN_DEVICE_INDEX_INVALID가 함께 난다.
- **필수 사실 누락:** 11개를 하나씩 빼면 각각 `MISSING_<이름>` 하나만 난다. 필수 목록, 기대 런타임 모듈 목록, 외부 금지 이름 목록은 손으로 쓴 목록과 같아야 한다.
- **로컬이 아닌 경로(L08-06):** 보고된 module·ext·loaded 경로 중 로컬 드라이브 경로가 아닌 것이 있으면 NON_LOCAL_PATH_REPORTED를 낸다. UNC(`\\server\share`), `\\?\` 확장 경로, `\\.\` 장치 경로, 상대 경로, 네트워크 매핑 드라이브(GetDriveTypeW가 원격)가 여기에 든다. 이런 경로는 OS 경로 해석기(`realpath`)에 넘기지 않고 문자열로만 비교한다. 7행(UNC cuBLAS는 FOREIGN_RUNTIME_LOADED도 함께, UNC module은 MODULE_NOT_RUNTIME_FILE도 함께)과 매핑 드라이브 1행에서, 해석기 감시 함수에 그 경로가 한 번도 전달되지 않아야 한다. 로컬 경로는 여전히 해석된다(1행).
- **경로 비교:** 대소문자를 무시하고, 로컬 드라이브의 8.3 짧은 이름은 긴 이름과 같은 폴더로 본다(`realpath`). 정상 보고를 전부 대문자로 바꿔도, 런타임 폴더를 8.3 이름으로 줘도(판정 쪽·보고 쪽 각각) 통과해야 한다. 8.3 이름을 만들지 않는 볼륨에서는 이 2행을 건너뛴다.
- **기대 런타임 모듈:** 5개는 L-P07의 import 표에서 손으로 옮겼다. `_ext` pyd, `ctranslate2.dll`, `libiomp5md.dll`, `cublas64_12.dll`, `cublasLt64_12.dll`이다. `gpu_runtime.DLL_LOAD_ORDER`에서 파생하지 않는다.

분모는 정상 4(원본, 대문자, 8.3 두 방향), 단일 결함 45, 타입 14, 장치 0개 1, cuDNN 위치 2, pyc 1, 로컬 아닌 경로 9, 필수 누락 11, 목록 고정 3, 자식 실패 1이다.

## C. probe와 배포 진입점

| 경우 | 기대 |
| --- | --- |
| 런타임 없음, 소스 실행 | activate = NOT_INSTALLED(3.13) 또는 UNSUPPORTED(3.11). frozen=False, bundle 빈 문자열, exitcode 0. module·runs·tokens 없음. ctranslate2 계열 모듈이 로드되지 않음 |
| 자식이 시간 안에 답하지 않음 | GPU_SMOKE_CHILD_FAILED |
| 모델 객체가 CPU float32로 떨어짐(가짜 객체) | runs가 요청값이 아니라 객체가 보고한 cpu·float32 |
| 모듈 이름 하나를 해석하지 못함 | `module_paths`가 MODULE_NAME_UNRESOLVED로 실패. 자식 보고는 loaded=None과 loaded_error를 담아 판정이 BAD_TYPE_LOADED로 거부 |
| 모듈 이름 전부 해석 | 순서대로 목록 반환 |
| 진입점: activate None | 종료 코드 0, probe 보고를 그대로 출력 |
| 진입점: activate 코드 / activate 키 없음 | 종료 코드 2 |
| 진입점: 경로 인자 누락 | argparse 종료 코드 2 |
| `loaded_modules` | 현재 프로세스의 `_ctypes` pyd 경로를 포함 |

분모는 런타임 없음 1, 시간 초과 1, 가짜 객체 1, 이름 해석 4(None, 빈 문자열, 전부 해석, 자식 보고), 진입점 4, `loaded_modules` 1이다. B와 합치면 L08 시험 파일의 103개와 같다.

## D. 실장비 실행

빌더 스크립트를 정확한 tree의 frozen 번들로 실행한다. 런타임은 L-P07 실장비 확인 때 앱 경로로 설치한 `build/gpu-e2e2`를 쓰고, 실행 전후에 catalog 대조를 한다. 결과는 판정 PASS, 실패 코드 0개, 종료 코드 0이어야 한다. 실제 보고의 로드 경로, 실행 장치·정밀도, token은 [라이선스 결과](../implementation/license-results.md)의 L-P08 절에 기록한다.

## mutation

임시 사본에서 `verdict`의 각 검사와 진입점 종료 코드 조건을 하나씩 지운다. B·C 표의 해당 행이 실패해야 한다. probe 쪽은 소스 실행의 실제 GPU 판정으로 확인한다. faster-whisper 사실 반전, 로드 목록 비움, 모델 생성 장치를 CPU로 바꾼 사본을 판정이 거부해야 한다. 실행 기록을 객체 대신 요청 상수로 채운 사본은 가짜 객체 시험이 잡아야 한다. 결과는 결과 문서에 적는다.
