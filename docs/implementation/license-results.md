# Recoryn 라이선스 개선 결과 L02·L03

[라이선스 검토 L01](license-review.md)의 결정 D1~D6을 구현한 단위의 실제 증거다. 작성·통합 C00. 각 단위의 정확한 commit tree 검증과 원격 CI는 해당 단위의 Git ref·실제 run이 정본이며, 자기 commit SHA를 넣기 위한 반복 commit은 만들지 않는다. 법률 판단·G4 승인이 아니다.

## L-P02 배포 제외와 PyAV 비의존 STT 입력

선행 L-P01 `d567ee217cec0b72e3103dfdd49002928a67ed0a`의 원격 CI [43678177012](https://github.com/gangdonggilstudy/Recoryn/actions/runs/43678177012) 세 job success를 C00이 GitHub API로 확인했다.

### 구현

- **STT 입력(D1):** `transcription/audio_input.py`가 검증된 정수 PCM WAV(1~4바이트, 1~64채널)를 채널 평균 float64로 해석하고, Kaiser windowed sinc polyphase(ROLLOFF 0.94, 16 zero crossings, β 8.6, phase별 DC 정규화)로 16 kHz float32를 만든다. 출력 길이는 ⌈16000N/S⌉다. `FasterWhisperProvider`는 WAV bytes 대신 이 배열을 넘기며 numpy가 없으면 DEPENDENCY_MISSING이다. 변환 블록마다, 그리고 변환 직후 모델 진입 전에 취소·기한을 검사한다(L02-STT-01). 원본 WAV bytes는 바꾸지 않는다.
- **품질 관측(합성 신호):** 6 kHz 이하 통과대역 최대 오차 약 3e-5, 9 kHz 이상 대표 tone 감쇠 약 −98 dB 이하, 6~9 kHz는 전이대역이다. 10분 48 kHz 입력 변환 약 6.8초(개발 PC). 실제 음성 전사 품질과 PyAV/swresample 대비 차이는 NOT_RUN이다.
- **배포 제외(D1~D3):** `release_manager`의 단일 정책이 PyAV 디렉터리·dist-info(경로의 모든 디렉터리 구성요소, L02-P01), x264/x265/OpenH264, Qt Virtual Keyboard·Qml·Quick·PDF·qpdf, Mesa/LLVM `opengl32sw.dll`, NVIDIA CUDA/cuDNN/TensorRT 계열(L02-P02)을 거부한다. spec은 TOC의 목적지와 원본을 모두 검사해 제거하고(L02-P03), 빌더는 기록된 TOC를 다시 검사하며, 설치 `verify`와 frozen smoke도 같은 정책을 적용한다.
- **PyAV stub:** frozen runtime hook이 `import av`를 사용 불가 모듈로 충족하고 속성 사용은 `RECORYN_PYAV_NOT_BUNDLED`로 실패한다. 이미 import된 모듈은 교체하지 않는다.
- **빌드 위생:** 빌더가 PyInstaller에 Python·Windows 경로만 넘긴다. 첫 시도 `build/l02-1794717923`은 Git Bash PATH의 Git mingw64 OpenSSL(`libssl-3-x64.dll`, `libcrypto-3-x64.dll`)이 TOC에 수집되어 evidence 단계의 하드링크 거부로 중단됐다. 남은 PE의 import closure가 번들 또는 Windows로 모두 해소되는지 빌드에서 검사한다.

### 독립 검토

| 검토 | 검토자 | 발견과 판정 |
| --- | --- | --- |
| [STT 입력](../reviews/l02-stt-input-review.md) | recoryn-ml(w5:p4) | L02-STT-01 S2 전처리 직후 취소의 추론 진입 → FIXED/RECHECKED. L02-STT-02 S3 블록 경계 분모(27 label/25 고유) 문서 정정 → RECHECKED. 독립 시험 60건, 관련 331 PASS, 독립 mutant 1 검출. OPEN 0 |
| [패키징](../reviews/l02-packaging-review.md) | recoryn-arch(w5:p2) | L02-P01 중첩 PyAV 경로, L02-P02 NVIDIA 계열 누락, L02-P03 목적지만 검사하는 spec 필터 → 모두 S2 FIXED/RECHECKED. 금지 186·허용 94 고유 경로의 독립 분모에서 누락·오제외 0, 독립 M6 검출, 기존 후보 직접 smoke 재실행 PASS. OPEN 0 |

### mutation

임시 source 사본에서 하나씩 적용했다. 처음 두 실행은 하네스가 `-o pythonpath=`에 Windows 역슬래시 경로를 넘겨 pytest가 snapshot을 무시하고 editable workspace를 import했으므로 **무효**다(모든 변이가 통과로 보임). 이후 슬래시 경로와 실행마다 snapshot import 출처 확인을 추가한 실행이 정본이다.

| ID | 변이 | 결과 |
| --- | --- | --- |
| M1 | 차단 주파수의 target 비율 제거 | 저지대역 21행 FAIL |
| M2 | 24비트 부호 확장 제거 | 디코더 W=3 4행 FAIL |
| M3 | 채널 평균→합 | 디코더 C>1 12행 FAIL |
| M4 | phase별 DC 정규화 제거 | DC 8행 FAIL(항등 rate 1행은 정상 통과) |
| M5 | 출력 길이 올림→내림 | 길이 46행 FAIL |
| M6 | spec 금지 TOC 필터 제거 | spec 제거 시험 FAIL |
| M7 | 모델 진입 전 취소 검사 제거 | 경계 4행 FAIL |

증거: `%TEMP%/recoryn-l02-mutation-02wlukmh/evidence.json`(M1~M6), `%TEMP%/recoryn-l02-mutation-hzuj2s_h/evidence.json`(M7). 각 행은 정상 PASS, errors 0, 목표 assertion FAIL을 요구했다. 일부 mutant 검출을 전체 mutation coverage로 주장하지 않는다.

### 빌드 증거

중간 후보 `build/l02-1794718201`(STT-01·P01~P03 수정 전 snapshot): 네이티브 243→112개, 전체 445→324 MB, 금지 파일 0, import closure 미해결 0, 호스트 도구 DLL 0, frozen smoke PASS(`av`=NOT_BUNDLED_STUB, STT 입력 16 kHz mono float32, 추론 없는 production worker 시작/종료). 최종 판정은 아래 정확한 tree 실행이다.

정확한 L-P02 stage tree `ad3fa4391380989d73d949967eef9d52054e1ec2`(202파일)을 `git -c core.autocrlf=false archive`로 `%TEMP%/recoryn-l-p02-tree-evisijv0/tree`에 추출했다. 추출 bytes와 tree blob 불일치 0, `recoryn` import 출처는 snapshot `src`였다. cwd·pytest config·PYTHONPATH·MYPYPATH·pythonpath를 snapshot으로 고정했다.

| 검사 | 결과 |
| --- | --- |
| 전체 pytest(Windows/CPython 3.13.1, offscreen, `--runxfail`, 고유 basetemp, ResourceWarning 오류) | **7386 PASS / 196.16초**, 실패·오류·skip 0 |
| 전체 line / branch | **8158/8731 = 93.44% / 2439/2804 = 86.98%**, 패키지별 95%/90% 분리 예산 PASS |
| coverage 측정 파일 | 68개 모두 snapshot `src/recoryn` 아래, 외부 0 |
| Ruff check·format / strict mypy | 135파일 / 77파일 PASS |

기존 7111건에 L-P02의 새 시험(STT 입력 156, 어댑터 6, release 정책·spec·빌더, 독립 STT 60 등)이 더해진 수다. 같은 tree에서 만든 frozen 후보 `build/l02-final-1794719192`은 빌드 입력 81파일이 tree bytes와 모두 일치했고 1044파일·네이티브 112개, 금지 파일 0, import closure 미해결 0, 호스트 도구 DLL 0, `verify` 통과, frozen smoke PASS였다.

| 후보 파일 | SHA-256 |
| --- | --- |
| Recoryn.exe | `4d97d61c541becb90c29dc6f0dda4ab71d72d46c27b82e276a4760dc4b9bd0af` |
| Recoryn-CLI.exe | `e847536cd41b431f8808af6bd84aa8550804565da7ba446a8a2ff24b0c324ebc` |
| release-manifest.json | `683e88540f6e9bd9d5ec4c854f2e3b29ff0262651965dc34a96e0aec8f3062ff` |
| native-origins.json | `326c6d9babe7191750940c3b518b1f96be3436989552abb4c83d4833fd40808a` |
| smoke.stdout.json | `2c1b0b6d670006abaa73aee143b29579bcbdc0201eeb0d410c99a6402d8398f3` |

증거: `%TEMP%/recoryn-l-p02-tree-evisijv0`의 report.json, pytest.xml(`7c2872cc…6340`), coverage.json(`8b3fd6ef…1538`), 정적 검사 log. 이 결과 기록과 배정표 상태 갱신 외에는 검증 tree와 commit tree가 같다. 로컬 ignored 후보는 공개 배포물이 아니며 EXE를 Git에 올리지 않는다.

## 미검증

실제 음성·Whisper 추론 품질, GPU, 장시간 입력의 메모리 상한, clean VM, 서명, Qt/FFmpeg corresponding source 배포, 코덱 특허, Intel·Microsoft 조건의 법률 확인은 NOT_RUN 또는 G4 OPEN이다.
