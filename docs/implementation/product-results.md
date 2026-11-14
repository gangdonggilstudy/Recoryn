# Recoryn 제품 구현 진행 및 검증 기록

상태: **개발 체크포인트 0.2.0.dev2의 교차 검토·오프라인 통합 검증 완료. 설계 v1.0 전체 구현·실장비·공식 릴리스 승인은 아니다.** 사용자는 설계 v1.0의 구현 완료까지 진행하도록 지시했다. [구현 계약](product-contracts.md)과 [작업 배정](../collaboration/assignments.md)을 따른다. 아래 수치는 각 시점의 실행 증거이며 서로 겹치는 시험 수를 합산하지 않는다. 최종 source digest·전체 회귀·패키지는 아래에 고정하며 원격 ref는 실제 push 결과로 별도 확인한다.

## 기존 기준과 현재 환경

- 기존 P0.1: commit e589410c40117ec86e4cdc0f809ca62e937e170b, 전체 379개 시험과 Windows Python 3.11/3.13 CI 통과. [코어 결과](p0-results.md)가 해당 snapshot의 정본이다.
- 개발 호스트: Windows, Python 3.13.1. 실제 음성 녹음·클라우드 계정·모델 가중치 다운로드는 수행하지 않았다.
- UI 개발 패키지 PySide6 6.12.0, 패키저 PyInstaller 6.22.3, 선택 로컬 AI 패키지 Faster-Whisper 1.2.1/NumPy 2.3.5를 개발 환경에 설치했다. 설치와 import는 실제 모델 추론 검증이 아니다.
- 실제 Windows에서 `list_devices()` 읽기 전용 실행은 exit 0, render 1/capture 1을 반환했다. 이 시험은 스트림 시작이나 W01 하드웨어 캡처 시험이 아니다.

## 강제 재부팅 후 복구 진행

2026-11-14 사용자 지시로 기존 Recoryn worker 탭 w5:t2의 네 Codex 세션을 재개했다. root가 AGENTS·온보딩 순서·배정·소유 파일·원본/AI/동의/비밀 불변식·작업자 Git 금지·추가 위임 금지·독립 리뷰·미검증 범위를 교육했다. ONBOARDING_READY 보고와 현재 파일/diff를 대조하고 [재개 배정](../collaboration/assignments.md)에 기록했다. staged/unstaged/untracked 작업은 보존했으며 Git 인덱스를 복구 도구로 초기화하지 않았다.

복구 직후 root 기준 선택 회귀는 122 PASS, 이어 전체 오프라인 회귀는 **1137 PASS (38.41s)**였다. `QT_QPA_PLATFORM=offscreen`, cacheprovider 비활성, 실행별 고유 TEMP basetemp와 `-W error::ResourceWarning`을 사용했다. 당시 Ruff 및 strict mypy 65파일도 통과했다. 이는 이후 작성 중인 코드·독립 반례를 포함한 최종 통과가 아니다. B22 구현과 새 guard 이후 최종 source digest·coverage·전체 회귀를 다시 고정한다.

후속 독립 검토에서 Ollama 수명·readiness 반례 **8 FAIL/28 PASS**, B22 cleanup ACK 동안 취소·close·deadline 반례 **3 FAIL**, 패키지의 추가 weights 형식/UNC source probe 반례 **9 FAIL**을 발견했다. 각 수정은 작성자에게 배정하고 원 반례는 다른 검토자가 유지한다. 실패를 skip/xfail로 숨기거나 앞선 전체 통과로 상쇄하지 않는다. root helper의 새 자체 시험 20 PASS에는 실제 소유 합성 프로세스/descendant·private Windows Job 종료 ACK·loopback listener 소유 관계가 포함되지만 실제 Ollama 검증은 아니다.

root가 선택 기능 검증을 위해 .venv에 sherpa-onnx 2.0.1, sherpa-onnx-core 2.0.1, onnx 1.23.2, ml_dtypes 0.6.0을 설치했다. weights는 다운로드/실행하지 않았다. 선택 diarization extra는 Windows x64·Python 3.12 이상 CPU 경로에 한정한다. 실제 모델·음성·품질은 계속 NOT_RUN이다.

Git SSH push dry-run은 현재 SSH 계정 gangdonggil의 repository 쓰기 권한 거부로 실패했다. 저장된 gangdonggilstudy HTTPS 자격증명으로 동일 GitHub repository의 main dry-run은 성공했다. origin 설정은 유지했고 실제 신규 commit/push는 최종 독립 검토·통합 검증 후 root가 수행한다. Herdr 관리자 접근·시험·빌드·의존성 설치·Git push에 필요한 도구 승인은 확보했으며 승인창을 다른 worker가 대신 수락하지 않았다.

## 구현 추적

이 표는 재부팅 후 현재 작성·독립 검토 상태다. 숫자는 각 배정의 중간 snapshot이며 합산하지 않는다. 최종 동결·artifact·commit/원격 상태는 후단의 통합 검증 기록으로 별도 고정한다.

| 범위 | 구현과 현재 증거 | 남은 게이트 |
| --- | --- | --- |
| 불변 원본·청크·복구 | P0.1 기반과 session-bound Job/reader 삭제 경계, BR24 게시·reader/UNKNOWN 독립 재확인 유지 | 최종 동결 전체 회귀, 실제 전원 차단·장비 장애 NOT_RUN |
| native WASAPI | ctypes MMDevice/IAudioClient/IAudioCaptureClient, native format·QPC·flags·ACK, BR11 시계 급변 원 반례 RECHECKED | 실제 캡처/분리/절전/장시간·성능 NOT_RUN |
| 파생 오디오 | PCM·미터·에너지 VAD·선형 리샘플·drift/source mapping·gap/unknown, B21 live 확정 청크·새 epoch 연결 | 신규 media 급변/음질 한계는 최신 BR12/13로 확인, 실제 정렬 품질 NOT_RUN |
| 내용·작업 | 불변 revision/선택 CAS/원자 Job 게시·취소·checkpoint·세션 바인딩, reader ACK와 BR24 경계 유지 | 최신 B21 편집·재개·삭제·diarization 연동 독립 리뷰 및 최종 회귀 |
| AI 어댑터 | 로컬 Whisper 및 Ollama/OpenAI/Anthropic/Gemini 기능 분리·Gateway 경유, BR14 checkpoint와 새 BR23 DTO guard 독립 검토 | 실제 모델·API 버전별 서비스 호환성 NOT_RUN |
| 보안·동의·비용 | endpoint/data·실행 세대·SendPermit·vault·UNKNOWN ledger, 고정 proof dispatch guard. R13 새 guard 독립 43 PASS/관련 92 PASS, 신규 OPEN 0 | root 최종 통합. 실제 vault/TLS·외부 daemon 트래픽 NOT_RUN |
| 녹음·전사·요약 UI | B21 live/VAD·고정 origin·편집/검색·근거 재생 reader·명시 재실행·power/meter·화자 추정·Ollama 연결, 최신 자체 372 PASS. BR12-09와 BR13-07 최종 hash/원 반례 RECHECKED | 실제 장비·Narrator·OS sleep·재시작 뒤 삭제 대기 UI 복원은 별도 검증/후속 범위 |
| 로컬 추론 격리 | owned spawn·명시 취소·종료·부모 종료 관측, BR30 checkpoint RECHECKED | 실제 모델 지연/메모리·품질 NOT_RUN |
| 모델 관리 | 명시 manifest/라이선스·URL·hash·크기·부분 재개·검증 후 활성화·UI, BR30-01~03 원 반례 RECHECKED | 실제 다운로드 origin/공급망·라이선스 법률 판단 NOT_RUN |
| Ollama 로컬 실행 | native suspended private Windows Job·고정 loopback listener/Job 소유·file identity·고정 proof 수명·descendant signal ACK. R14 BR30-04~09 RECHECKED/독립 66 PASS, 비동기 GUI/late proof는 BR13-07 RECHECKED | 실제 daemon·후속 트래픽·모델 NOT_RUN |
| 선택 화자 구분 | B22 로컬 ONNX/라이선스·hash 검증·5분 CPU·익명 추정·불변 파생 revision, 자체 55 PASS. BR41-01 ACK 중 취소/기한 원 반례 RECHECKED | 최신 B21 UI 연동 독립 검토, 실제 모델·음성·DER·정확도 NOT_RUN |
| 진단·보존·패키지 | redacted diagnostics, 사용자 범위 설치·갱신/rollback·검증된 제거·동적 Qt onedir·실제 포함 파일/SBOM/license/hash. BR42 2/2 RECHECKED/관련 90 PASS, 최종 frozen smoke·TEMP 설치/제거·snapshot 일치 PASS | clean VM·서명·전이 license/corresponding source·G3/G4 미완료 |

## 최종 오프라인 통합 검증과 종결

root는 작성자 결과와 원 검토자의 최종 hash/원 반례를 대조한 후 BR11/12/13/14/23/24/30/41/42/44의 이번 개발 증분 발견을 통합했다. BR12-09(삭제 보류 UI), BR13-07(GUI owner lock), BR30-04~09(owned helper), BR41-01(ACK 중 취소/기한), BR42-01~02(weights/UNC)와 BR44-01~03(CI·metadata·진행 기록)은 각각 다른 검토자의 RECHECKED 근거로 **CLOSED** 처리한다. 과거 OPEN/실패/hash는 각 리뷰에 이력으로 보존한다. 미실행 하드웨어·실모델·정식 릴리스 게이트를 닫는 판정이 아니다.

최종 독립 aggregate QA는 [R15 보고서](../reviews/product-final-qa.md)의 재동결 후 실행이 정본이다. 최초 1443 PASS/fixture 1 FAIL은 부모 supervisor가 status JSON을 쓰는 중 consumer가 읽은 race였다. root가 세 시험 파일의 coordination receipt 게시만 staging→replace로 교정했고 원 제품 코드·종료 assertion·timeout은 바꾸지 않았다. R15가 변경 diff와 새 전후 map을 독립 확인한 뒤 전체를 다시 실행했다. 최초 실패를 재실행 성공으로 덮어쓰지 않았다.

| 최종 검사 | 결과 |
| --- | --- |
| 전체 pytest / Windows Python 3.13.1 / offscreen | **1444 PASS, 71.82s, 실패·skip·xfail 0** |
| 전체 line / branch | **8071/8644=93.37% / 2419/2784=86.89%** |
| 핵심 package별 분리 예산 | domain/capture/jobs/storage/security/content 각각 95%/90% 이상 PASS |
| Ruff / format / strict mypy | src/tests/scripts/packaging lint·format 127파일, runtime/script/packaging 타입 75파일 PASS |
| source/test/config 전후 map | 132파일, 변경 0, compact JSON bytes 동일 |
| LF-normalized tree SHA256 | `c3a9df87b4545e016652ad13c01605bba1ac6870d8f594ad884a613b20673b64` |

위 tree 산식은 R15 보고서의 상대 POSIX 경로→LF-normalized SHA map을 sorted compact JSON UTF-8로 직렬화한 hash다. Git commit hash나 EXE 내부 inventory와 구별한다. 최종 QA 증거 root는 `C:/Users/gangd/AppData/Local/Temp/recoryn-r15-refreeze-7590e5ddbd7c4332b88d520e07f107b7`이며 정확한 명령·환경·seed·각 보고서 hash는 R15 문서에 있다. 원격 GitHub Actions의 Python 3.11/3.13 실행 결과는 이 로컬 증거에 포함하지 않는다.

## 최종 개발 후보의 패키지 검증

최신 B21 UI·metadata 동결 후 root가 `build/final-dev2-1794666063022`에 별도 후보를 생성했다. 이전 `build/recovery-dev2-1794665153965`의 frozen smoke 성공은 중간 후보의 이력이며 이 최종 후보와 혼합하지 않는다. `scripts/build_release.py --output <새 고유 경로> --smoke`는 exit 0이었다. runtime Python 67파일과 빌드 입력 79파일의 실제 SHA256을 현재 workspace와 전수 비교해 일치했다. 입력은 commit 전 workspace snapshot이며 clean commit의 재현 가능한 공식 릴리스 빌드라고 주장하지 않는다.

최종 frozen smoke는 Qt 6.12.0, Faster-Whisper 1.2.1/AV 16.1.0/CTranslate2 4.9.0/ONNX Runtime 1.32.0 및 선택 sherpa-onnx/core 2.0.1/ONNX 1.23.2의 import·metadata·무요청 production worker 시작/종료를 확인했다. 실제 모델을 로드하지 않았다. 합성 mic 4410/system 4800 frame, FINALIZED, 트랙별 WAV export 후 원본 hash 불변, 미동의 Gateway의 DNS 전 차단과 offscreen 종료 ACK가 PASS다. Python socket audit만 사용하므로 native DLL/daemon 전체 무송신 인증은 아니다.

동일 frozen CLI로 새 OS TEMP 하위의 지정 설치 경로에 실제 설치·제거를 실행해 성공했다. 원본 canary는 설치 디렉터리 밖의 별도 fixture에만 만들었으며 bytes 불변, 활성 current pointer 제거를 확인했다. 사용자 AppData 설치·registry·실계정·실제 사용자 미디어를 변경하지 않았다. clean Windows VM 시험과 실제 업데이트/rollback의 전체 환경 조합은 별도다.

wheel `recoryn-0.2.0.dev2-py3-none-any.whl`은 181366 bytes, SHA256 `b9a7c1eae7b534784246a3cf4d48c17c9a37c1f4d3fea85fc1e6907ac3fed134`다. 새 venv에 `--no-index --no-deps`로 설치한 후 `-I -m recoryn`의 합성 녹음/내보내기와 `pip check`가 통과했다. wheel 내부 runtime Python 파일을 LF 정규화해 현재 67파일과 전수 대조했다. 선택 AI 패키지를 wheel의 기본 runtime 의존성으로 바꾸지 않았다.

| 최종 로컬 후보 파일 | SHA256 |
| --- | --- |
| Recoryn.exe | `f85ef3a78d3936b0930c5a63717495f73e458b471beef27b65f8ac64c263309b` |
| Recoryn-CLI.exe | `ef51bdcdd0342c4a3f4a449950ad4abadf06ebb6c82b99def622cb0c44e5eef0` |
| release-manifest.json | `6de71283aeff9def75b83c9e2a87176b223eda2fb705bc66f3ca9e3020c44695` |
| sbom.cdx.json | `9ce82c4bb8fdccd374b24d2d41955c3c9b02b0ac84d44643bddd4c935543539f` |
| native-origins.json | `91841cef0254fadc2f6787f9b4f7fdb055024dda3bf159fc0bd62d6a3af91ab0` |
| build-provenance.json | `6821440826afb1991e4e9ac18b9f2fb69e6870a2a973d56ef4eb23b38463ebbb` |

manifest의 실제 파일 1176개·445023237 bytes와 SBOM 39개 component를 기록했다. 직접 native 출처가 미귀속인 2파일을 `REVIEW_REQUIRED`로 남겼다. Qt/FFmpeg corresponding source·빌드 옵션/notice 및 전이 native license·서명·clean VM·G3/G4도 미완료다. 이 로컬 개발 후보를 공개 배포하거나 Git에 EXE/weights를 올리지 않는다. 실제 증거는 후보 root의 `smoke.stdout.json`, `final-validation.json`과 bundle의 manifest/SBOM/NOTICE/provenance에 있다.

## 독립 검토와 중간 증거

BR12/BR13은 root 작성 코드에서 실제 실패 반례를 제출했다. Interrupted 상태의 장치 close, writer 실패 영속화, 클립 상한, clock quality, 정상 packet 경고, UI 예외 가림, manifest-only pending, UNKNOWN 결과와 취소/fence 경쟁, 중복 Job 제출, 시간 origin 작업 키, 모델 활성화 직전 취소를 수정했다. 두 독립 시험 파일을 `--runxfail`로 실행한 root 중간 결과는 **30 passed**다. 작성자 수정만으로 종결하지 않으며 해당 검토자의 문서 재확인과 최종 digest를 요구한다. 검토 중 추가 발견은 각 리뷰 문서에 남긴다.

중간 전체 실행은 797 passed/1 failed였다. 실패는 Job 바인딩 시험을 작성자가 동시에 수정하던 snapshot에서 관측됐으며 B11이 최신 선택 회귀로 재확인했다. 이 실행을 최종 전체 통과로 기록하지 않는다. 같은 시점 전체 line 88.93%/branch 81.70%, 기존 핵심 영역의 분리 예산은 통과했다. 새 security/content도 기존 품질 기준 95%/90%로 게이트에 추가했다. B14 별도 결과 security line 99.37%/branch 97.57%이며 root 전체 snapshot에서 재측정한다.

## 외부 검증과 배포 조건

실제 마이크·시스템 캡처, Bluetooth·장치 변경·절전·장시간 시험, 라이선스 corpus의 WER/CER·요약 사실성, 실제 GPU·Ollama·제공업체, Credential Manager 실제 계정 격리, clean VM 설치·제거와 서명은 별도 상태다. 합성/fixture 통과를 이들 검증으로 확대하지 않는다. 무손실·전원 장애 내구성·모든 Windows 호환성·실청구액 절대 상한을 주장하지 않는다.

API·Qt·Ollama 등 버전별 정본은 [제공업체 matrix](provider-matrix.md)와 모듈의 출처를 따른다. 모델 다운로드·재배포 권한과 binary/Qt/FFmpeg 조건은 실제 배포 파일 목록에 대한 검토가 필요하다. 공식 릴리스 G3/G4가 미충족이면 패키지는 검증용 후보로만 표시한다.
