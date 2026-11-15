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

## L-P03 고지·SBOM·native 대응표

선행 L-P02 `7a31a6ea95aeb64ec46aada59358a48673384c5c`의 원격 CI [43679833977](https://github.com/gangdonggilstudy/Recoryn/actions/runs/43679833977)은 core 3.11·3.13과 optional-runtime 세 job success다(C00 GitHub API 확인).

### 구현

- **고지 원문 고정:** `packaging/notices/`에 GNU LGPL-3.0·GPL-3.0·LGPL-2.1, CTranslate2 v4.9.0 MIT, tokenizers v0.23.3·sherpa-onnx v2.0.1 Apache-2.0 원문을 upstream 그대로 두고 `SOURCES.json`에 URL·SHA-256·적용 대상을 기록했다. `.gitattributes`가 줄바꿈 변환을 막고, 빌더 snapshot이 이 파일들을 입력에 포함하며, 생성 시 해시가 다르면 NOTICE_TEXT_HASH_MISMATCH로 중단한다.
- **Qt 표기 정정:** PySide6·shiboken6 wheel은 Qt 상용 라이선스 텍스트만 동봉한다. Recoryn이 실제로 쓰는 LGPL-3.0-only를 distributed license로 기록하고 LGPL-3.0·GPL-3.0 원문을 동봉하며 상용 텍스트는 복사하지 않는다. 선언 원문은 `recoryn:declared-license`에 그대로 남긴다.
- **누락·산문 선언 보충:** ctranslate2·tokenizers·sherpa-onnx-core 원문을 보충했다. colorama·numpy·pyinstaller·onnxruntime·protobuf·sherpa-onnx의 산문 또는 전문 선언은 각 wheel이 동봉한 텍스트와 같은 SPDX 식으로 정규화했다. 대응 규칙이 없는 긴 선언은 전문을 필드에 붙이지 않고 `LicenseRef-Declared-As-Full-Text`로 표시한다. CycloneDX 표준 `licenses` 필드를 채운다.
- **native 대응표:** 모든 EXE/DLL/PYD를 실제로 싣는 구성요소·라이선스·상태(DECLARED, REDISTRIBUTABLE_PROPRIETARY, CONDITIONS_UNCONFIRMED, PATENT_REVIEW_REQUIRED)로 귀속한다. 규칙이 없는 파일은 UNMAPPED이며 빌드가 NATIVE_LICENSE_UNMAPPED로 중단한다. 호스트 도구 이름(`libssl-3-x64.dll`)은 의도적으로 귀속하지 않는다.
- **NOTICE:** 제외 정책, LGPL 구성요소의 교체 가능성과 소스 위치, 공개 배포 시 corresponding source 게시가 남은 게이트라는 사실, 구성요소별 distributed license와 고지 파일, MPL-2.0(tqdm) Source Code Form 위치, 조건 미확인·특허 검토 대상 native 파일, Intel·Microsoft 조건을 적는다. 법률 승인처럼 표현하지 않는다.

### 독립 검토

[고지 검토](../reviews/license-notice-review.md)(recoryn-security, w5:p5)는 OPEN 4건을 냈다. L03-01 S2 디렉터리 포괄 규칙이 미확인 native를 DECLARED로 만듦 → 검토한 112개 실제 경로만 담은 `packaging/notices/native-map.json`으로 교체, 목록 밖은 UNMAPPED. L03-02 S2 모양만 보는 SPDX 판정 → `packaging.licenses` 파서로 검증, 실패 값은 `license.name`. L03-03 S3 긴 선언 전문이 SBOM property에 남음 → hash·길이만 기록. L03-04 S3 Microsoft 조건 미확인 미표기 → NOTICE와 gate `microsoft_runtime_conditions`·`intel_runtime_conditions`에 명시. 재확인 결과는 리뷰 후단이 정본이다.

같은 검토자가 원 반례를 그대로 재실행해 네 건 모두 RECHECKED/CLOSED, **OPEN 0**으로 판정했다(세 경로의 합성 DLL 모두 UNMAPPED, 부정 SPDX 3식은 `license.name`, numpy는 식별자·hash·47540자, 두 후보 NOTICE와 provenance의 Microsoft 문구·gate 확인). 검토자는 BR42 fixture 변경에서 oracle 약화를 찾지 못했다. 이전 TEMP 사본은 권한 제한으로 읽지 못해 과거 assertion과의 동일성은 주장하지 않았다. 이 부분은 C00이 `git diff --cached HEAD -- tests/integration/test_release_independent.py`로 보충 확인했다. 변경은 `import shutil` 1줄과 고지 폴더 복사 및 주석 3줄 추가뿐이며 삭제·수정된 assertion은 0줄이다.

### 검증

첫 정확 tree 실행(`b828b91e…`)은 7434 PASS / **1 FAIL**이었다. 기존 BR42 독립 시험 `test_sbom_uses_observed_distribution_and_records_exact_shipped_hashes`의 합성 source에 이번 단위가 필수로 만든 고지 입력이 없어 NOTICE_TEXTS_MISSING이 났다. 고지 요건을 완화하지 않고 그 fixture에 실제 `packaging/notices`만 복사했으며 SBOM·hash assertion은 바꾸지 않았다. 이 실패를 재실행 성공으로 덮지 않는다.

수정 후 정확한 L-P03 stage tree `f786ddc54b1373faa18ca945fce86143db5f1cfb`(211파일)를 `%TEMP%/recoryn-l-p03b-tree-nebxqjdp/tree`에 추출해 같은 방식으로 실행했다. 추출 bytes 불일치 0, import 출처 snapshot.

| 검사 | 결과 |
| --- | --- |
| 전체 pytest | **7435 PASS / 236.17초**, 실패·오류·skip 0 |
| 전체 line / branch | **8158/8731 = 93.44% / 2439/2804 = 86.98%**, 분리 예산 PASS, 측정 68파일 모두 snapshot |
| Ruff check·format / strict mypy | 135파일 / 77파일 PASS |

같은 tree의 frozen 후보 `build/l03-final-1794720823`: 빌드 입력 89파일(고지 원문·SOURCES·native-map 포함)이 tree bytes와 일치, 1054파일·네이티브 112개 전부 명시 귀속(DECLARED 92, REDISTRIBUTABLE_PROPRIETARY 13, PATENT_REVIEW_REQUIRED 5, CONDITIONS_UNCONFIRMED 2, UNMAPPED 0), 금지 파일 0, import closure 0, Qt 상용 텍스트 0, `verify`와 frozen smoke PASS.

| 후보 파일 | SHA-256 |
| --- | --- |
| Recoryn.exe | `6f216fd59d07914ae38077e419f3875d3900829355e1b4994e1b6d5581e774a0` |
| Recoryn-CLI.exe | `6002ed06a73311d9c3a58949923c62bb3ab3930b60dd4ab09a25c41f1b215518` |
| release-manifest.json | `7215d05b26325ee42ff8810b10eeac760fe117c28a45526125d958e773829d49` |
| NOTICE.txt | `6b6c01b833a36ffa49a9be6bcca1fcf09bc69e7d2460301cdfcac0f2b4253f08` |
| sbom.cdx.json | `3519a569088f0cf49e6153d3a04a3f3060782d426d5c023500c2bda39a75af88` |
| native-origins.json | `58b0daead3ab572bac9cb8eb7a42595e8081a984d087b19c78724677bd758c9f` |
| build-provenance.json | `dd96aebb57c995293e00904630866e1a93faa56f942162b5da85fd17c9b4f82c` |

NOTICE와 SBOM은 검토자에게 제출한 수정 후보 `build/l03-1794720123`과 bytes가 같다.

## L-P04 Qt 미디어 백엔드·FFmpeg 제외와 PCM 직접 재생

선행 L-P03 `cde8a7082051f7e8cd580fd564c6da337396315b`의 원격 CI [43694878703](https://github.com/gangdonggilstudy/Recoryn/actions/runs/43694878703)은 core 3.11·3.13과 optional-runtime 세 job success다(C00 GitHub API 확인).

### 첫 설계와 독립 검토

첫 후보 `build/l04-1794733273`은 FFmpeg만 빼고 재생을 Windows Media Foundation(WMF) 백엔드로 고정했다. 이 방식은 runtime hook `rthook_media_backend.py`, 제품 코드 무변경이었다. 네이티브 106개, smoke PASS였다. 두 독립 검토가 이 후보에서 다음을 찾았다.

- **[패키징 검토](../reviews/l04-packaging-review.md)(recoryn-arch):**
  - 금지 208·허용 96·TOC 216의 결정표 520행에서 누락·오제외 0이었다. 112개 대비 정확히 FFmpeg 6개만 빠졌다.
  - **L04-P01 S2:** 출력 장치가 없을 때 재생 probe의 NOT_RUN이 smoke 최상위 PASS로 감싸졌고, 빌더는 최상위 status만 봤다.
- **[재생 검토](../reviews/l04-playback-backend-review.md)(recoryn-desktop):**
  - **L04-D01 S2:** WMF는 16채널에서 위치 진행이 멈추고, 64채널은 InvalidMedia였다. 제품 클립은 1~64채널을 보존한다. C00 재현에서는 1~10채널 정상, 12~32채널 정지였다.
  - **L04-D02 S2:** 위치 지정 +500 ms에 재생 없음인 가짜 player도 smoke 진행 판정을 통과했다.
  - **L04-D03 S2:** 로드 전 위치 지정이 두 백엔드에서 각 6형식, 12/12 모두 무시됐다. 기존 제품 결함이다.
  - L04-P01과 같은 지적은 중복 집계하지 않았다.

C00은 이 결과에 따라 WMF 고정안을 폐기하고 D7을 Recoryn PCM 직접 재생으로 바꿨다.

새 후보 `build/l04b-1794734467`의 재확인 결과는 다음과 같다.

- **패키징:** OPEN 0이다. L04-P01을 RECHECKED했고, 112개 대비 정확히 FFmpeg 6개와 windowsmediaplugin 1개만 빠졌다.
- **재생:**
  - D01·D02·D03·P01을 RECHECKED했다.
  - 64채널×3 rate×4 위치, 768 고유행의 독립 Fraction oracle이 일치했다.
  - 실제 무음·볼륨 0 sink로 5형식(16 kHz 12/16/64채널, 48 kHz 16/64채널)에서 정확한 frame, 진행, Idle 해제가 PASS였다.
  - **L04-D04 S2:** 정상 시작 뒤 Qt가 sink를 StoppedState/IOError로 바꾸면 표시도 해제도 없었다. C00이 수정했다. 시작 뒤 Qt가 멈추면 sink와 버퍼를 해제하고, 오류가 있으면 상태 표시줄에 PLAYBACK_OUTPUT_FAILED를 띄운다. 원 반례 3행을 시험에 추가했다.
  - **D04 재확인:**
    - 현재/퇴역 sink × Idle/Stopped × NoError/IOError, 8 고유행에서 오류 표시 1회와 해제를 확인했다. 퇴역 sink의 늦은 신호는 추가 표시가 없었다.
    - 실제 무음 sink의 정상 종료·명시 stop·재선택에서 거짓 오류는 0이었다.
    - 최종 판정: 두 검토 모두 **OPEN 0**이다.
- **`test_live_ui` 보충 확인:** 검토자는 권한 제한으로 이전 TEMP 사본을 읽지 못했다. 그래서 C00이 `git diff HEAD -- tests/ui/test_live_ui.py`로 대신 확인했다. 바뀐 것은 첫 assertion 하나로, `(path, 0)` 비교를 검증된 PCM의 rate·채널·전체 bytes·시작 frame 비교로 강화했다. 변조 거부 두 행은 바뀌지 않았다.

### 구현

- **배포 제외:** `release_manager`의 basename 규칙에 다음을 더했다. spec 필터, 빌더의 TOC 재검사, `verify`, frozen smoke 검사가 같은 정의를 공유한다. 백엔드 고정 hook은 삭제했다.
  - FFmpeg: `ffmpegmediaplugin`과 FFmpeg 라이브러리 8종(`avcodec-`·`avformat-`·`avutil-`·`avdevice-`·`avfilter-`·`swresample-`·`swscale-`·`postproc-`)
  - Qt 미디어 백엔드: `windowsmediaplugin`
- **PCM 직접 재생(`src/recoryn/ui/pcm_playback.py`):**
  - `_verify_playback`가 reader lease 안에서 클립을 한 번 읽어 해시를 다시 확인한다. 상한은 8 MiB+4096 bytes다.
  - 16-bit PCM WAV만 허용하고 1~64채널을 받는다.
  - 요청 위치는 `position_ms × rate // 1000` frame에서 정확히 자른다.
  - 1~2채널은 bit 그대로, 3채널 이상은 동일 가중 mono 평균(ties-to-even)으로 만든다.
  - 결과 bytes를 `QAudioSink`로 출력한다. 출력 장치 없음·형식 미지원·시작 오류는 각각 오류 코드로 상태 표시줄에 알린다. 버퍼가 끝나면 장치를 해제한다.
  - 기존 결함(로드 전 위치 무시)과 WMF 채널 한계가 함께 사라진다. 재생하는 bytes가 해시를 검증한 bytes라서, 검증 뒤 player가 파일을 다시 여는 간격도 없어졌다.
- **고지·증거:** native 대응표에서 FFmpeg 그룹과 두 백엔드 플러그인을 빼 105개가 되었다. LGPL-2.1 원문과 SOURCES 항목, NOTICE의 FFmpeg 문단도 제거했다. NOTICE는 FFmpeg와 미디어 백엔드를 배포하지 않으며 Recoryn이 검증된 PCM을 Qt 오디오 출력으로 재생한다고 적는다. gate는 `NOT_DISTRIBUTED_L01_D1_D7`이다.
- **smoke와 빌더:**
  - **probe 대상:** frozen smoke는 제품의 `prepare_playback`·`SinkPlayback`으로 12채널 합성 무음 WAV를 2000 ms부터 볼륨 0으로 재생한다. 12채널은 WMF가 진행하지 못한 형식이다.
  - **진행 판정:** 150 ms와 600 ms 시점의 위치로 정확한 시작, 실제 진행, 벽시계 초과 없음을 판정한다.
  - **NOT_RUN 처리:** 최상위 status는 재생이 확인된 경우에만 PASS다. 빌더는 smoke 코드와 따로 playback 상태를 다시 확인한다.
  - 판정 기준은 [경우의 수](../testing/l04-media-backend-cases.md)에 있다.
- **PySide6 6.12 호환:**
  - `QAudioSink`가 반환하는 enum은 `QAudio` 별칭과 같다고 비교되지 않는다. 그래서 상태·오류를 이름으로 비교한다.
  - `stateChanged` 인자를 Python으로 변환하지 못하므로 인자 없는 slot에서 `sink.state()`를 읽는다. 두 문제 모두 개발 환경에서 관측했다.

### 검증

L-P04 stage tree `a6ad2c79e73ff6e261c94196bde1150323b7774c`(216파일)를 `%TEMP%/recoryn-l-p04-tree-ghn4d5a0/tree`에 `core.autocrlf=false`로 추출해 실행했다. 추출 bytes 불일치 0이고, `recoryn`과 `release_manager` 모두 추출 tree에서 import됐다.

| 검사 | 결과 |
| --- | --- |
| 전체 pytest(`--runxfail`, ResourceWarning 오류화) | **7535 PASS / 194초**, 실패·오류·skip 0 |
| 전체 line / branch | **8274/8836 = 93.64% / 2465/2828 = 87.16%**, 분리 예산 PASS, 측정 69파일 모두 추출 tree |
| Ruff check·format / strict mypy | PASS / 78파일 PASS |

같은 tree를 따로 추출해 frozen 후보 `build/l04-final-1794735342`를 만들었다.

- **입력:** 빌드 입력 89파일이 모두 tree bytes와 일치한다.
- **구성:** 1046파일, 네이티브 105개가 모두 명시 귀속됐다(DECLARED 90, REDISTRIBUTABLE_PROPRIETARY 13, CONDITIONS_UNCONFIRMED 2, UNMAPPED 0). FFmpeg와 미디어 백엔드 플러그인은 0이다.
- **smoke:** PASS다. 제품 경로로 12채널을 2000 ms부터 재생해 위치가 2198 → 2648 ms로 진행했다. stderr는 0 bytes다.
- **크기:** 303.2 MB로, L-P03의 324 MB보다 줄었다.

| 후보 파일 | SHA-256 |
| --- | --- |
| Recoryn.exe | `91c211e98d6a15cfe5783d1760355d6e845bb7c56d8d43500b4e7b3ab8c11754` |
| Recoryn-CLI.exe | `a38ea85a80493b4bc5892fb8d5a09bbc0600d0d4f7779b26adb6133612583bae` |
| release-manifest.json | `25cf4d056c455987aefbd0b91a2c8d316b5497623ed90fb84096e00e3b6a2d28` |
| NOTICE.txt | `ecb4e22ee4be6663e2fb7033b72eccb91bd62f6486346813fcf7978bdc8b9171` |
| sbom.cdx.json | `ad331b2b88335831fdfb833a90674421e3170e90e939cf6adff0ec832b0d803a` |
| native-origins.json | `4bf7845b86e0a2ccf555f3683e92606034e9364bbc308796783385bb926dbb94` |
| build-provenance.json | `1b5f0061664708a2be1ccca7db3a327fecc4fe38b0e0f6f2b32b4492efc4633f` |
| smoke.stdout.json | `bb6ea2d16a9f4a83811ca11196f7b073e3b8bb44028b984d056e5f8ad68256e5` |

NOTICE와 SBOM은 검토 후보 `build/l04b-1794734467`과 bytes가 같다. 이 결과 기록, 배정표 상태 갱신, 재생 검토 문서 외에는 검증 tree와 commit tree가 같다.

## L-P05 고지 완전성

선행 L-P04 `5e10becb61b6e11304c6013f7cca7940010b9ab7`의 원격 CI [43700323467](https://github.com/gangdonggilstudy/Recoryn/actions/runs/43700323467)은 core 3.11·3.13과 optional-runtime 세 job success다(C00 GitHub API 확인).

### 조사

배정된 조사 하위 에이전트가 upstream 원문과 출처를 수집했다. 각 파일은 tag의 git blob과 대조했고, 로컬 DLL은 문자열과 import 표로 확인했다. C00은 그중 zlib·FreeType·tlsf.h·oneDNN LICENSE를 다시 내려받고 qtbase 소스의 SHA-256 sidecar도 다시 받아 같은 hash임을 확인했다.

- **Qt:** qtbase·qtsvg·qtimageformats·qtmultimedia v6.12.0 tag의 qt_attribution.json(88개 파일, 103개 고유 행)을 조사했다. 동봉 파일 기준으로 47행을 골랐고, 이후 L05-02 판정으로 ES2 헤더 1행을 빼 46행을 포함했다. 그 밖에 다른 플랫폼·미배포 모듈·제외한 FFmpeg 플러그인·빌드와 시험 전용 항목은 제외했다. 판정 근거는 다음과 같다.
  - Qt6Core: zlib 1.3.2, PCRE2 10.48
  - Qt6Gui: FreeType, HarfBuzz, libpng 1.6.58, md4c
  - 플러그인: qjpeg의 libjpeg-turbo 3.2.0, qwindows의 wintab
  - Qt6Multimedia: dr_wav, tlsf
  - 이 라이브러리들은 외부 DLL로 import되지 않아, 모두 Qt DLL 안에 정적으로 들어 있다.
  - qtsvg는 attribution 파일이 없다. REUSE.toml이 명시한 XSVG 파생 코드(HPND-sell-variant)를 따로 넣었다.
  - Qt 공식 "Licenses Used in Qt 6.12" 페이지와 대조하면, XSVG 항목이 그 페이지에 없는 것 말고는 이름과 버전이 같다.
- **Intel:** 동봉한 `libiomp5md.dll`은 intel-openmp 2025.3.0 wheel의 파일과 bytes가 같다. CTranslate2 v4.9.0의 Windows 빌드 스크립트는 oneAPI Base Toolkit 2025.3.0을 설치한다. 라이선스는 다음과 같다.
  - OpenMP: Intel End User License Agreement for Developer Tools(August 2024)
  - oneMKL: Intel Simplified Software License(October 2022)
  - EULA가 말하는 재배포 목록(redist.txt)은 wheel에서도 공식 페이지에서도 찾지 못했다.
- **oneDNN:** `ctranslate2.dll`에 oneDNN 3.1.1이 정적으로 들어 있다(`-DONEDNN_LIBRARY_TYPE=STATIC`, `oneDNN-3.1.1` 경로 문자열). 기존 native 대응표는 이를 적지 않았다.
- **Microsoft:** VS 2022 Distributable Code 페이지는 `VC
edist` 아래 파일의 재배포를 허락한다. 단 "Distribution ... is limited to licensed Visual Studio users"라는 조건이 붙는다.
- **corresponding source:** download.qt.io가 게시한 SHA-256 sidecar로 Qt 6.12.0 submodule archive 4개와 pyside-setup 6.12.0 archive의 정확한 위치를 확인했다. PyPI에는 PySide6 6.12.0 sdist가 없다.

- **CTranslate2 내부(추가 조사):** CTranslate2 v4.9.0 Windows 빌드 스크립트 57행의 옵션은 WITH_DNNL=ON, WITH_CUDA=ON, CUDA_DYNAMIC_LOADING=ON, BUILD_CLI=OFF다. 스크립트는 CUDA 12.8.1을 설치한다. `ctranslate2.dll`에는 다음이 정적으로 들어 있다.
  - **NVIDIA CUDA runtime:** cudart 12.8.90이다. cudart DLL을 import하지 않고, "CUDA driver version is insufficient" 문자열이 있으며, NVCC 기본값이 static이다. CUDA EULA Attachment A가 `cudart_static.lib`를 재배포 가능으로 명시한다.
  - **cuRAND 장치 코드:** Philox, XORWOW precalc다. 이 헤더들은 "PROPRIETARY" 표시가 있고 Attachment A에 없다. **재배포 가능 여부는 미확인**이다.
  - **CCCL 2.7.0:** Thrust(Apache-2.0·Boost·BSD-2), CUB(BSD-3), libcu++(Apache-2.0 WITH LLVM-exception, NCSA 또는 MIT, 일부 NVIDIA Software License)다.
  - **기타 오픈소스:** spdlog 1.10.0과 fmt 8.1.1(MIT), cpu_features 0.7.0(Apache-2.0), avx_mathfun(MIT·Zlib), avx512_mathfun(SIMD_Utils, BSD-2)이다.
  - **oneDNN 3.1.1:** 내부에 Xbyak(BSD-3)와 ittnotify(BSD-3)가 있다. oneDNN과 CCCL에는 NOTICE 파일이 없다.
  - **번들에 없는 것:** cutlass·cxxopts·googletest·ruy는 빌드 옵션상 컴파일되지 않는다. cuDNN·cuBLAS DLL은 번들에 없다(D3).

### 구현

- **고정 원문:** 원문 73개를 새로 고정해 `packaging/notices`는 83개 파일이 되었다.
  - `qt/<repo>/<upstream 경로>` 47개
  - `ct2/` 아래 26개: Intel·oneDNN·CCCL·spdlog·cpu_features·SIMD_Utils·NVIDIA EULA와 cuRAND 주석 발췌
  - 모두 SOURCES.json에 URL·SHA-256·bytes를 적는다. wheel이나 archive 안의 파일은 member 경로와 wheel SHA-256도 함께 적는다.
  - `qt/**`·`ct2/**`는 `-text`로 줄바꿈 변환을 막는다.
  - 빌더 snapshot은 notices 하위 폴더 전체를 포함한다.
- **귀속표:** 세 파일을 둔다.
  - `qt-third-party.json`: Qt 47행(attribution 46 + XSVG 1)
  - `ct2-native.json`: CTranslate2 내부 16행
  - `corresponding-sources.json`: Qt submodule 4개와 pyside-setup archive의 URL·SHA-256
  - 생성기는 각 행의 SPDX·저작권·고정 원문을 검증한다. 문제가 있으면 QT_ATTRIBUTION_INVALID, CT2_ATTRIBUTION_INVALID, CORRESPONDING_SOURCES_INVALID로 거부한다.
- **NOTICE·SBOM:**
  - Qt 절과 CTranslate2 절은 행마다 머리줄·저작권·원문 경로를 적는다.
  - FreeType 크레딧, IJG 문장, cuRAND 헤더가 요구하는 NVIDIA 고지 원문을 넣는다.
  - PSL MPL-2.0 Source Code Form 위치, 정확한 upstream 소스 archive, Microsoft 재배포 조건과 공식 페이지를 넣는다.
  - SBOM에 Qt 47개와 CTranslate2 내부 16개 구성요소를 각자의 라이선스 식과 함께 추가했다.
- **native 대응표:**
  - `ctranslate2.dll`: 위 구성요소를 모두 적었다. 라이선스 식에 NVIDIA EULA·Intel ISSL 등이 들어가고, 상태는 CONDITIONS_UNCONFIRMED다.
  - `libiomp5md.dll`: Intel OpenMP 2025.3.0(Intel EULA for Developer Tools)이다.
  - 새 gate는 `nvidia_runtime_conditions`이고, Qt 소스 gate 값은 `TEXTS_INCLUDED_UPSTREAM_SOURCES_RECORDED_HOSTING_DECISION_REQUIRED`다.
- **이름 충돌:** 처음 붙인 이름 `curand-notices.txt`가 NVIDIA 런타임 제외 규칙에 걸려 후보가 거부됐다. 이름을 바꾸고 모든 고지 파일을 정책과 대조하는 시험을 추가했다.
- **NVIDIA 문구:** 배포하지 않는 목록에 "NVIDIA CUDA/cuDNN"만 적으면, `ctranslate2.dll` 안의 정적 CUDA runtime까지 배포하지 않는 것처럼 읽혔다. 그래서 "별도 CUDA/cuDNN runtime DLL"이라고 범위를 좁혀 적었다.

### 독립 검토

[고지 검토](../reviews/l05-notice-review.md)(recoryn-security, w5:p5)는 다음을 독립 확인했다.

- SOURCES 78개와 실제 원문 집합이 같고 bytes·SHA가 모두 일치한다.
- 공개 원문 6개를 고정 URL에서 다시 받아 bytes가 같았다.
- Qt·CTranslate2 귀속의 머리줄·저작권·사본이 후보와 일치한다.
- 실제 DLL의 문자열·import로 정적 포함 근거를 확인했다.
- NVIDIA 헤더는 발췌만 있고 코드는 없다.
- 미확인 조건이 승인처럼 표현되지 않았다.

발견과 수정은 다음과 같다.

- **L05-01:** libjpeg가 `qtiff.dll`에도 들어 있었다. 위치 두 곳을 기록했다.
- **L05-02:** 보수적으로 넣은 ES2 행의 미확인 상태가 NOTICE에 드러나지 않았다. LibGL 판정으로 이 행을 제외했다. 처음 적은 근거 문구 "동적 OpenGL 미지원"은 틀렸다. "Windows는 EGL·OpenGL ES 미지원"으로 정정했다.
- **L05-03:** 파일 수와 행 수가 섞여 있었다. 88개 파일, 103행에서 포함 46행, 제외 57행, REUSE 1행을 더해 47행으로 정리했다. JSON 매니페스트는 5종이다.
- **L05-04(재확인 중 발견):** libjpeg 저작권이 placeholder `None`이었다. 고정한 COPYRIGHT.txt의 15줄로 바꾸고, validator가 placeholder를 거부하게 했다.

네 건 모두 RECHECKED이고 **OPEN 0**이다.

### 검증

L-P05 stage tree `6422098e263437fd0c55c90efb90c8ad8b820979`(294파일)를 `%TEMP%/recoryn-l-p05b-tree-gli5fema/tree`에 추출해 실행했다. 추출 bytes 불일치 0이고, import 출처는 추출 tree다. 직전 tree `cd2189f`(7550 PASS)는 L05-02/04 수정 전이라 검증 근거로 쓰지 않았다.

| 검사 | 결과 |
| --- | --- |
| 전체 pytest(`--runxfail`, ResourceWarning 오류화) | **7551 PASS / 205초**, 실패·오류·skip 0 |
| 전체 line / branch | **8274/8836 = 93.64% / 2465/2828 = 87.16%**, 분리 예산 PASS, 측정 69파일 모두 추출 tree |
| Ruff check·format / strict mypy | PASS / 78파일 PASS |

같은 tree를 따로 추출해 frozen 후보 `build/l05-final-1794738362`를 만들었다.

- **입력:** 빌드 입력 165파일(고지 원문 78개와 매니페스트 포함)이 모두 tree bytes와 일치한다.
- **구성:** 1120파일, 303.9 MB다. 네이티브 105개가 모두 명시 귀속됐다(DECLARED 90, REDISTRIBUTABLE_PROPRIETARY 13, CONDITIONS_UNCONFIRMED 2, UNMAPPED 0).
- **SBOM:** 101개 구성요소다(기존 38 + Qt 내부 47 + CTranslate2 내부 16).
- **smoke:** PASS다. 위치가 2198 → 2648 ms로 진행했고 stderr는 0 bytes다.

| 후보 파일 | SHA-256 |
| --- | --- |
| Recoryn.exe | `dbe741d07600d8ae663a55354e689ab3cccf6019da60ad0884f7b0a0f9b05fac` |
| Recoryn-CLI.exe | `cadd91f5f9299ff9050991800f2e3a578b32a3d1d9d754a86863f5a3a74921bc` |
| release-manifest.json | `6bfa01690733418d8b1a1ec6453181b2c246c6d50374e7fa0010c878043cb0fd` |
| NOTICE.txt | `f5634bef77502b84c65f3498fb3413b681f32b7e478a75dabfaed1769f1e1461` |
| sbom.cdx.json | `e734a897831c92bc6c5048cad8f11151c07bb4179af65ddf53a5bcec68d52dee` |
| native-origins.json | `553fadac6de3ab0b822d036b737a9cf17ef3bf53d69901a1da8685d169e2d5f2` |
| build-provenance.json | `378837727ef1305e41dae41cea57fc2ad1099155b97a473b68a9ffb1fc983a43` |
| smoke.stdout.json | `487285ef672cdcf71fa76e6114459370992b1955d3c7e93aebd9fa984707053a` |

NOTICE와 SBOM은 최종 검토 후보 `build/l05d-1794738231`과 bytes가 같다. 이 결과 기록, 배정표 상태 갱신, 검토 문서 외에는 검증 tree와 commit tree가 같다.

## L-P06 CTranslate2 CPU 전용 자체 빌드

선행 L-P05 `15e70902d5ce1d6946c71a5328c4b27d7e5365eb`의 원격 CI [43704411295](https://github.com/gangdonggilstudy/Recoryn/actions/runs/43704411295)은 core 3.11·3.13과 optional-runtime 세 job success다(C00 GitHub API 확인). 사용자는 CTranslate2를 "직접 빌드(CPU 전용)"하기로 결정했다(D9). GPU 런타임은 "앱 안에서 받기"로 정했다(D10, L-P07).

### 빌드와 고정

`scripts/build_ctranslate2_cpu.py`를 깨끗한 폴더에서 한 번에 실행했다(`build/ct2-cpu-1794742636`, 보고서 SHA-256 `cf036b05…2418e`). 이 산출물을 `packaging/ctranslate2-cpu.json`에 고정했다.

- **소스:** CTranslate2 `v4.9.0` `a22ba1c6…`, cpu_features `8a494eb1…`, spdlog `76fb40d9…`, oneDNN `v3.1.1` `64f6bcbc…`다. 모두 commit이 일치했다.
- **도구체인(L06-02):** MSVC 14.42.34433, CMake 3.29.5-msvc4, Python 3.13.1로 고정한다. 셋 중 하나라도 다르면 TOOLCHAIN_MISMATCH로 거부한다. 실제 compiler 경로는 CMake 기록과 vcvars 환경에서 다시 읽어 같은 toolset인지 확인한다.
- **옵션(L06-02):** CTranslate2 16개와 oneDNN 6개 옵션을 모두 명시한다. CTranslate2 옵션은 BUILD_CLI/TESTS OFF, WITH_MKL/CUDA/CUDNN/RUY/OPENBLAS/ACCELERATE/HIP/MPS/FLASH_ATTN/TENSOR_PARALLEL OFF, WITH_DNNL ON, ENABLE_CPU_DISPATCH ON, OPENMP_RUNTIME COMP 등이다. configure 뒤 CMakeCache에서 값을 다시 읽어, 어긋나면 CMAKE_OPTION_MISMATCH로 거부한다. 모든 컴파일에 `/utf-8`을 준다.
- **`ctranslate2.dll`:** 26,077,696 bytes(SHA-256 `b4eeffbe…f5702`)다. PyPI판은 61.3 MB다. import는 Windows CRT·`msvcp140`·`vcruntime140(_1)`·`vcomp140`뿐이다.
- **`vcomp140.dll`:** VS 2022 `VC\Redist\MSVC\14.42.34433\x64\Microsoft.VC143.OpenMP`의 고정 파일이다(SHA-256 `036b9b3f…27aa7c`). 다른 파일이면 거부한다.
- **wheel:** `ctranslate2-4.9.0+recoryn.cpu1-cp313-cp313-win_amd64.whl`(SHA-256 `62149b88…60180`)이다. `_ext.cp313-win_amd64.pyd`는 `eff4ebf9…20e72`다. 빌드한 wheel 자체를 import해 버전과 CUDA 장치 0을 확인했다.
- **재현성:** 같은 소스·옵션으로 다시 빌드한 DLL은 크기는 같았지만 hash가 달랐다(`c97c4049…` → `b4eeffbe…`). 비트 단위 재현은 하지 않는다. 그래서 하나의 산출물을 고정해 쓴다.
- **pin 대조(L06-01):** 빌더는 PyInstaller를 실행하기 전에 설치된 패키지의 세 파일을 pin의 SHA-256과 대조한다. 결과 번들의 사본도 다시 대조한다. 이어서 import 표와 Intel·NVIDIA 표지를 검사한다. 표지는 대소문자를 무시하고 UTF-16도 본다. 하나라도 어긋나면 CTRANSLATE2_NOT_CPU_BUILD다. C00 확인 결과, PyPI DLL(vcomp 동봉)에서는 표지 위반 8개가 나왔고 고정 CPU DLL에서는 0이었다.
- **실패와 수정:** 앞선 시도 일곱 번이 실패했다. 실패 기록은 지우지 않았다.
  - 일시적인 PyPI 연결 재설정
  - 빌드 의존성 packaging 누락
  - setuptools의 MSVC 미탐지
  - cp949 컴파일로 인한 import UnicodeDecodeError
  - 단일 toolset에서 CMake `-T version=` 거부
  - VS generator가 compiler를 캐시에 남기지 않아 생긴 오탐
  - 시험 중단

### 공식판과 비교

`scripts/compare_ctranslate2_builds.py`로 비교했다. 모델은 내려받지 않고, seed 고정 무작위 가중치 Whisper 사양으로 만들었다. 입력은 2×80×3000이고, 인코딩과 greedy 생성을 실행했다. 크기는 두 가지다.

- small: d_model 64, 2층
- base: d_model 512, 6층, Whisper base급

L06-I01 지적에 따라 비교 하네스를 고쳤다.

- 결과마다 모델 파일 세 개와 입력 배열의 SHA-256, 차원, prompt를 담는다. 둘이 다르면 COMPARE_IDENTITY_MISMATCH로 거부한다.
- 인코더 출력 전체를 npz로 저장하고 그 hash를 대조한다. shape는 [2, 1500, d_model]이어야 하고 값은 유한해야 한다.
- 모든 원소를 비교한다(small 192,000, base 1,536,000).
- 원 반례인 `encoded_shape=[1,1,1]`도 거부하도록 시험했다.

환경은 세 가지이고, 같은 PC(AMD Family 25, AVX-512)에서 4스레드로 순서대로 실행했다(결과는 `build/ct2-compare2/`).

- PyPI 공식판 venv: `build/ct2-pypi-env`, DLL `a9009ad6…`
- 같은 venv에서 MKL 강제(`CT2_USE_MKL=1`)
- 자체 빌드 venv

- **PyPI 기본값과 비교:** 이 PC는 AMD CPU라 PyPI판도 기본값에서 MKL을 끄고 oneDNN(SGEMM·GEMM_S8 = DNNL)을 쓴다. CT2_VERBOSE로 확인했다. small과 base 모두 float32와 int8 인코더 출력 전체 배열이 bit 단위로 같았고(npz SHA-256 동일), 생성 토큰과 점수도 같았다. Intel CPU의 PyPI판은 기본값에서 MKL을 쓰므로 아래처럼 MKL을 강제한 비교를 따로 했다.
- **MKL 강제와 비교:**

| 모델 | 정밀도 | 최대 / 평균 절대 차이 (출력 최대값) | 생성 토큰 | 인코딩 중앙값 MKL / 자체 빌드 |
| --- | --- | --- | --- | --- |
| small | float32 | 2.26e-6 / 2.43e-7 (5.31) | 동일 | 0.051 / 0.049 s |
| small | int8 | 0.0202 / 7.56e-5 (5.30) | 동일, 점수 차 ≤0.0021 | 0.060 / 0.046 s |
| base | float32 | 6.26e-6 / 8.25e-7 (5.53) | 동일 | 1.12 / 0.842 s |
| base | int8 | 0.0861 / 0.0127 (5.47) | 첫 시퀀스가 9번째 토큰부터 다름, 점수 차 0.0205·0.0044 | 1.822 / 0.756 s |

- **해석(L06-I02·I03 반영):**
  - Recoryn의 `FasterWhisperProvider`는 CPU에서 compute_type `int8`, CUDA에서 `float16`을 명시해 넘긴다. `int16`은 허용 목록에 없다. 따라서 CPU 실제 경로는 int8이다.
  - Intel CPU에서는 이 경로가 PyPI판의 MKL int8에서 oneDNN int8로 바뀐다. AMD CPU에서는 PyPI판도 이미 oneDNN이라 이전과 같다.
  - float32는 수치적으로 같다.
  - int8은 MKL과 oneDNN의 양자화 GEMM 구현이 달라 출력에 차이가 있다. base 모델에서는 생성 토큰이 갈렸다. 그 인과 원인은 확정하지 않았다. 검토자의 측정에 따르면 무작위 모델의 단계별 logit 차이 여유는 0.0208~0.7455였다. 따라서 "logits가 평평해서"라는 처음 설명은 근거 없는 단정이라 철회한다.
  - 이 차이는 품질 허용치로 판정한 것이 아니다. Intel CPU에서의 속도와 실제 Whisper 가중치·실제 음성의 전사 차이는 NOT_RUN이며, 남은 위험이다.
  - 이 AMD PC에서는 자체 빌드가 MKL 강제보다 빠르거나 같았다.

비교 결과 SHA-256은 다음과 같다.

- npz: small `750da14f…112f0`(PyPI 기본·자체 빌드 동일), MKL `c533e074…5f161`; base `e796c988…de3f0`(동일), MKL `ea91cbfd…444db`

### 장치 선택

GPU가 있는 PC에서 GPU 정책을 고르면 CUDA가 없는 번들 CTranslate2로 모델 로드를 시도하게 된다. 이를 막기 위해 `cuda_runtime_available()`이 설치된 CTranslate2의 CUDA 장치 수를 확인한다. 0이거나 오류가 나면 GPU 후보를 비운다. 그 결과 CPU 폴백 정책은 CPU로 동작하고, GPU_ONLY는 RESOURCE_GPU_UNAVAILABLE로 알린다. 검토자는 정책 3 × 런타임 4 × GPU 5, 총 60 조합을 실제 `DesktopAI` 가짜 경로에서 확인했다.

### 독립 검토

- **[추론 검토](../reviews/l06-inference-review.md)(recoryn-ml, w5:p4):**
  - 처음 발견은 OPEN 3건이었다.
    - **L06-I01 S2:** 비교 하네스가 모델·입력 동일성과 shape를 확인하지 않았다. 그래서 `encoded_shape=[1,1,1]`인 가짜 결과도 차이 0으로 보고됐다.
    - **L06-I02 S3:** "compute_type 미지정"이라는 서술이 사실과 달랐다.
    - **L06-I03 S3:** 토큰이 갈린 원인을 근거 없이 단정했다.
  - 세 건 모두 고친 뒤 재확인에서 RECHECKED로 판정했고, **OPEN 0**이다. 확인 내용은 다음과 같다.
    - 새 시험 5개 통과
    - 원 반례 거부, 표본 밖 원소의 변경 검출
    - 실제 8개 결과의 전체 배열 재계산
  - 검토자가 확인한 비교 스크립트는 작업본 `0c6ab61e…`(CRLF)다. 요청서에 적은 `2d0f…`는 서식 정리 전 hash였다. C00은 작업본을 LF로 바꾼 hash가 stage blob `252665b2…`와 같음을 확인했다. 즉 내용이 같다.
- **[빌드 검토](../reviews/l06-build-review.md)(recoryn-arch, w5:p2):**
  - 처음 발견은 OPEN 3건이었다.
    - **L06-01 S2:** release gate가 버전 문자열과 일부 표지만 봐서, 빌드한 wheel과 암호학적으로 묶이지 않았다.
    - **L06-02 S2:** 도구체인이 "최신 설치본"으로 떠다녔고, 일부 옵션이 소스 기본값에 의존했다.
    - **L06-03 S3:** PE import·지연 import·대소문자·UTF-16·hash 변조를 다루는 부정 시험이 없었다.
  - 다음 수정으로 세 건을 고쳤고, 재확인에서 모두 RECHECKED/CLOSED, **OPEN 0**이다.
    - pin 파일, 설치 전·후 대조
    - 도구체인·옵션 고정과 CMakeCache 재대조
    - 결정표 시험 추가
  - 검토자는 시험과 회귀를 다시 실행하지 않았다. C00 실행 결과는 작성자 증거로 구분했다.

### 검증

L-P06 stage tree `e84123ba83e8595410fef97d72fe9efd6be54412`(283파일)를 `%TEMP%/recoryn-l-p06b-tree-ny6altjt/tree`에 추출해 실행했다. 추출 bytes 불일치 0이고, import 출처는 추출 tree다. 앞선 tree `dd43aeea`는 비교 스크립트 서식 검사 1건이 실패해 검증 근거로 쓰지 않았다. 차이는 ruff format으로 줄 1개를 더한 것뿐이다. 이 서식 정리는 빌드 입력에 포함되지 않는 파일에만 해당한다.

| 검사 | 결과 |
| --- | --- |
| 전체 pytest(`--runxfail`, ResourceWarning 오류화) | **7590 PASS / 198초**, 실패·오류·skip 0 |
| 전체 line / branch | **8280/8844 = 93.62% / 2465/2828 = 87.16%**, 분리 예산 PASS, 측정 69파일 모두 추출 tree |
| Ruff check·format / strict mypy | PASS / 80파일 PASS |

같은 내용의 tree `dd43aeea`를 따로 추출해 frozen 후보 `build/l06-final-1794743251`을 만들었다. 이 tree는 빌드 입력 149파일이 `e84123ba`와 같다.

- **입력:** 빌드 입력 149파일(pin 포함)이 tree bytes와 일치한다.
- **pin:** 번들의 CTranslate2 세 파일이 pin hash와 일치한다.
- **구성:** 1103파일, 266.9 MB다. 네이티브 105개 중 DECLARED 91, REDISTRIBUTABLE_PROPRIETARY 14이고 CONDITIONS_UNCONFIRMED와 UNMAPPED는 0이다. SBOM은 94개다.
- **smoke:** PASS다. ctranslate2 `4.9.0+recoryn.cpu1`이고 재생 위치는 2208 → 2658 ms였다. stderr는 0 bytes다.

| 후보 파일 | SHA-256 |
| --- | --- |
| Recoryn.exe | `81c84346ca27a2a800479248abd04137bc0cc77f098fe8d23d49058b92d6adb9` |
| Recoryn-CLI.exe | `1375db5e951afb1da389aacbc4874bd0c3a21abe59d377b03c308bf0c4af9838` |
| release-manifest.json | `55bd42349e15d931c3d80e9b6e506973afd45ad4ce854fc355c9ad6bb01fe9cc` |
| NOTICE.txt | `2762f169fd8837e4370f706ea83435e540f5e7cb4f7627c852361b226b5d2794` |
| sbom.cdx.json | `064e5e66eb3ebb1345f9bb11e0db0ce6b2de5cf4043b45265a07e9ca4a60ecd0` |
| native-origins.json | `e55fb6c4aef0529ef928ccd6e2ce5e80634bb7703186167b5020c8ac500f62e8` |
| build-provenance.json | `213a3ee4da54417f713b36741dcd549c9b2f5ae76761594e2280cf6465634ff7` |
| smoke.stdout.json | `0090435d548bf66d0bb7b07af1eccda8a72f7906d485e2e3fbc9602d1c098fba` |

이 결과 기록, 배정표 상태 갱신, 검토 문서 2개 외에는 검증 tree와 commit tree가 같다.

### GPU 가능성 확인 (L-P07 준비)

이 PC의 RTX 4070 Laptop(드라이버 576.57)에서 확인했다. PyPI 공식 CTranslate2 4.9.0과 NVIDIA `nvidia-cublas-cu12` 12.8.4.1 wheel만으로 무작위 가중치 base 모델이 GPU에서 실행됐다. cuDNN은 필요하지 않았다.

| 장치·정밀도 | 인코딩 | CPU float32 대비 최대 차이 | 토큰 |
| --- | --- | --- | --- |
| CPU float32 | 0.73 s | 기준 | 기준 |
| GPU float32 | 1.15 s(첫 실행 포함) | 1.3e-5 | 동일 |
| GPU float16 | 0.14 s | 0.0126 | 동일 |

받을 파일은 두 개, 합계 약 588 MB다.

- `ctranslate2-4.9.0-cp313-cp313-win_amd64.whl`: 20,408,731 bytes, SHA-256 `d009840a…ef095`
- `nvidia_cublas_cu12-12.8.4.1-py3-none-win_amd64.whl`: 567,544,208 bytes, SHA-256 `47e9b821…e35af`

## L-P07 GPU 런타임 앱 내 받기

선행 L-P06 `83dfb8f37f5c80b6bba867e0f337127997563574`의 원격 CI [43711709953](https://github.com/gangdonggilstudy/Recoryn/actions/runs/43711709953)은 core 3.11·3.13과 optional-runtime 세 job success다(C00 GitHub API 확인).

### 구현(2판, 1차 검토 반영)

1차 독립 검토의 OPEN 10건을 반영했다. 다운로드 검토는 S1 3건과 S2 2건, 화면 검토는 S2 4건과 S3 1건이다. 늦은 취소(L07-04와 L07-U05)는 같은 결함이며 한 번에 고쳤다.

- **`src/recoryn/models/gpu_runtime.py`:**
  - **신뢰 기준(L07-02):** wheel 2개의 pin에 더해, 풀 파일 11개의 경로·크기·SHA-256을 소스의 `CATALOG`에 고정했다. `scripts/gpu_runtime_catalog.py`가 고정 wheel에서 다시 계산해 일치를 확인한다(`--check` → CATALOG_MATCH). 디스크의 기록 파일(`runtime.json`)은 없앴고, 신뢰하지 않는다.
  - **압축 해제:** 각 wheel을 쓰기를 막는 handle로 열어 pin과 다시 대조하고, 같은 handle로 읽는다. catalog 파일만 풀며, 쓰는 동안 크기와 hash를 catalog와 대조한다. 경로 탈출, 절대 경로, 중복, symlink, 누락, CRC 손상, 바이트·크기 불일치는 GPU_RUNTIME_ARCHIVE_INVALID다.
  - **풀지 않는 파일:** `cudnn64_9.dll`(`ctranslate2.dll`은 cuBLAS와 드라이버만 동적으로 부르고 cuDNN은 이름으로도 참조하지 않는다), converters·specs, dist-info 나머지다.
  - **취소와 게시(L07-04/U05):** 다운로드 뒤, 압축 해제 중 블록마다, 게시 직전에 취소를 확인한다. 게시는 폴더 이름 바꾸기 한 번이며, 그 전의 취소는 활성 런타임과 staging을 남기지 않는다.
  - **정리와 재시도(L07-05):** 게시 뒤 받은 묶음 삭제 실패는 설치 결과에 영향을 주지 않는다. 재시도는 남은 검증 완료 묶음을 다시 hash해 재사용하고, 손상됐으면 지우고 다시 받는다. 남은 `.extract-*`·`.remove-*`는 다음 설치나 삭제가 정리한다.
  - **상태:** catalog와 정확히 같은 파일·폴더 집합이고 크기가 맞을 때만 READY다. 목록 밖 파일, `__pycache__`, 로컬 기록, `_rocm_sdk_*` 폴더, 링크가 있으면 DAMAGED다.
  - **활성화(L07-01/03):** catalog 파일을 모두, 쓰기·삭제·이름 바꾸기를 막는 handle로 연다. 이 handle은 프로세스가 끝날 때까지 유지한다. 그 handle로 읽은 바이트를 검증하고, 파일 집합이 정확한지 확인한다. Python 소스는 검증한 바이트를 메모리에서 compile해 실행하므로 bytecode cache를 읽지도 쓰지도 않는다. 공식 `__init__.py`의 Windows 블록은 실행 전에 한 줄로 바꾼다. 이 블록은 `_rocm_sdk_*`·`HIP_PATH`에서 DLL 폴더를 찾고 패키지 폴더의 모든 `*.dll`을 로드하는데, 그 시작·끝과 SHA-256을 고정해 두었다. 대신 System32의 `nvcuda.dll`과 런타임 DLL 4개를 절대 경로로, 의존 순서대로 로드한다. 이때 런타임 폴더는 DLL 검색 경로에 넣지 않는다. catalog 밖의 `ctranslate2.*` 이름은 다른 finder로 넘기지 않고 ModuleNotFoundError로 끝낸다.
  - **삭제:** 폴더 이름 바꾸기 뒤에 지운다. 작업자가 런타임을 쥐고 있으면 이름 바꾸기가 실패하고, GPU_RUNTIME_IN_USE와 함께 런타임은 그대로 남는다.
  - **위협 경계:** 같은 사용자 권한 프로세스는 Recoryn 프로세스 메모리에 직접 쓸 수 있으므로 sandbox가 아니다. 보장하는 것은 활성화 전에 있던 파일, 남은 파일, 활성화 전·중에 바뀐 파일이 검증 없이 로드되지 않는다는 것이다.
- **추론 프로세스(`app/inference.py`):**
  - `device="cuda"`이고 런타임 경로가 주어지면, faster-whisper를 import하기 전에 활성화한다. 실패하면 요청마다 명시적 코드로 답한다.
  - 부모 프로세스는 이를 `ProviderError(GPU_RUNTIME_*)`로 올리고, 그 코드를 `gpu_failure`에 기록한다.
  - 기존 작업자 인자 4개 계약은 유지하고, 런타임이 있을 때만 다섯 번째 인자를 준다.
- **장치 선택(`ui/ai_bridge.py`, L07-U01/U03):**
  - `gpu_source()`는 CPU_ONLY면 none, CUDA판 CTranslate2가 설치돼 있으면(소스 실행) native, 그 밖에 런타임이 READY이고 차단되지 않았으면 runtime이다.
  - **실패 차단:** 실패 차단은 이번 실행의 작업자가 직접 답한 GPU_RUNTIME_* 실패만 쓴다. 저장된 작업 이력은 쓰지 않는다. 차단 대상은 그 실패가 난 런타임 설치(폴더 세대)이며, 다시 받은 설치는 다시 고른다. 작업자 재사용 키에도 세대를 넣는다. 작업 설정 키는 모델과 장치로 그대로 둔다.
  - **변경 대기:** 모델 관리 탭에서 GPU 런타임 받기나 삭제가 대기 중이면, 이를 화면 thread에서 읽어 런타임을 고르지 않는다.
  - **작업자 놓기:** 런타임을 쥔 유휴 작업자를 닫는 `release_gpu_runtime()`을 두었다.
- **삭제 확인 중 AI 시작(L07-U06, 2차 화면 재확인):**
  - 삭제 확인 창은 중첩 event loop를 돌아서, 창이 떠 있는 동안 GPU 전사가 시작될 수 있다.
  - 창이 닫힌 뒤 AI 유휴와 모델 작업 없음을 다시 확인하고, 아니면 아무것도 하지 않는다.
  - bridge의 `release_gpu_runtime()`도 AI가 준비·대기·실행 중이면 AI_MODEL_CHANGE_REQUIRES_IDLE로 거부한다. 쓰는 중인 작업자는 어떤 경로로도 닫히지 않는다.
- **Task 경계(`ui/tasks.py`, L07-U02):** RESOURCE_GPU_UNAVAILABLE, MODEL_DOWNLOAD_REQUIRES_APPROVAL, GPU_RUNTIME_* 9개를 사용자에게 보일 고정 코드로 추가했다.
- **화면(`ui/models.py`, `ui/main.py`, L07-U03/U04):**
  - 삭제를 확인받으면, 대기열에 넣기 전에 GPU 작업자를 닫는다. 닫지 못하면 삭제하지 않는다.
  - 받기·삭제 작업이 대기하거나 실행 중이면 `gpu_busy`다.
  - 정책 문구는 "CPU 허용 정책은 CPU로, GPU 전용 정책은 전사를 시작하지 않음"으로 나눠 쓰고, 소스 실행의 native 경우를 밝혔다.
  - 실패 뒤에는 GPU 상태를 다시 읽는다.
- **문서:** D10 본문의 "cuBLAS·cuDNN wheel"을 실제와 맞게 고쳤다. 받는 것은 cuBLAS wheel뿐이며, CTranslate2 wheel에 든 cuDNN DLL은 풀지 않는다.

### 시험과 mutation

- **단위 시험:** `tests/unit/test_gpu_runtime.py` 99개다. 검토 반례마다 따로 시험을 두었다.
  - pyc(파일 집합 검사 실제·우회 2행), 목록 밖 DLL, HIP_PATH, 다운로드 확인 뒤 wheel 교체, catalog 밖만 다른 wheel
  - 검증 직후 쓰기·삭제·이름 바꾸기 4가지 차단, 취소 경계 5행과 큰 파일
  - 정리 실패, 재시도 재사용, 손상 묶음 재다운로드, 사용 중 삭제, Task 코드 4개, 패널 4개
- **창 경로 시험:** `tests/ui/test_gpu_runtime_ui.py` 4개는 실제 MainWindow·DesktopAI·Task·ResourceScheduler를 거친다.
  - U01은 실패, CPU, CPU, 재설치 뒤 GPU, 새 실행 GPU 순서다.
  - U02는 GPU 전용에서 작업자 0개와 RESOURCE_GPU_UNAVAILABLE 표시다.
  - U03은 AI 사용 중 삭제 차단, 삭제 대기 중 작업자 닫기와 CPU 선택이다.
  - U06은 확인 창 안에서 AI가 시작된 경우, 작업자 유지·삭제 미대기·bridge 거부다.
- **mutation:** 수정을 하나씩 되돌린 사본(pytest rootdir를 사본으로 둠)에서 21개 모두 시험에 걸렸다.
  - **런타임 관리 14개:** 게시 전 취소, 블록 취소, bytecode loader, 공유 모드, 활성화 파일 집합, catalog 대조, 초기화 블록 교체, finder 위임, 정리 실패, 재사용, 이름 바꾸기 삭제, 차단 무시, Task 코드, pin 재확인이다.
  - **창 경로 7개:** 변경 대기 무시, 세대 무시, 작업자 놓기 생략, 실패 관측 생략, Task 코드, 확인 창 뒤 재확인 생략, bridge 사용 중 거부 생략이다.
  - 처음 돌렸을 때는 블록 취소, finder 위임, pin 재확인 3개가 살아남았다. 각각에 대응하는 시험을 추가했다: 큰 파일 취소, 활성화 뒤 심은 하위 모듈, catalog 밖만 다른 wheel.

### 독립 검토

같은 검토자가 다시 확인했다(OPEN 0).

- **[다운로드 검토](../reviews/l07-gpu-download-review.md)(recoryn-security, raw SHA-256 `e0af2cf50b881a75afd0ee393f02a6db0a404839cc80313368400744f5cd7066`):**
  - 1차에서 L07-01~03(S1)과 L07-04~05(S2)를 찾았다.
  - 2판 재확인에서 원 반례를 다시 실행해 5건 모두 RECHECKED/CLOSED가 됐다.
  - 정확 tree의 mypy가 `scripts/gpu_runtime_catalog.py`의 루프 변수 재사용을 잡았다. 출력 루프 변수명 2줄만 바꿨고(`d8b290f2…` → `d425a4ee…`), 검토자가 그 2줄뿐임과 `--check` CATALOG_MATCH를 다시 확인했다.
- **[화면 검토](../reviews/l07-gpu-ui-review.md)(recoryn-desktop, raw SHA-256 `bd1b2486fd25ff421cbda717ee623dcd7ff74513dc7ce6dfffc6ba9c2ae4e62a`):**
  - 1차에서 U01·U02·U03·U05(S2)와 U04(S3)를 찾았다.
  - 2판 재확인에서 5건이 RECHECKED가 되고, U06(S2)이 새로 나왔다. 삭제 확인 창 안에서 AI가 시작되면 쓰는 중인 작업자를 닫는 문제였다.
  - 3판 재확인에서 U06도 RECHECKED가 됐다. 이때 실제 QEventLoop/QTimer와 busy×active×pending 8행을 확인했다.
- **현재 소스 후보:** `build/l07r3-1794749274`의 smoke는 PASS다. 입력 hash는 `ai_bridge.py` `9cd84982…`, `gpu_runtime.py` `407e2264…`로 현재 소스와 같다. 이전 후보 `build/l07r2-…`는 `getattr` 호환 수정 전의 `ai_bridge.py`로 만든 것이라 증거로 쓰지 않는다.

### 실제 장비 확인(2판)

이 PC(RTX 4070 Laptop, 드라이버 576.57)에서 수정된 제품 코드로 새 폴더 `build/gpu-e2e2`에 다시 확인했다.

- **설치:** `GpuRuntimeManager.install(approved=True)`로 PyPI에서 588 MB를 받아 pin을 다시 확인하고, catalog 11개만 풀었다(12.2초). 상태는 READY, 전체 검증은 1.2초였다. 남은 것은 런타임 폴더와 빈 downloads뿐이다.
- **활성화:** 새 프로세스(`-B`)에서 `_activate_gpu(root)`가 0.82초에 성공했다. `ctranslate2`와 `_ext`는 런타임 폴더에서 왔고 CUDA 장치 수는 1이었다. 실행 뒤 `.pyc`는 0개, 상태는 READY였다.
- **로드된 DLL:** 런타임에서 온 것은 `ctranslate2.dll`, `libiomp5md.dll`, `cublas64_12.dll`, `cublasLt64_12.dll`, `_ext.pyd` 5개다. cuDNN은 로드되지 않았다. NVIDIA 드라이버는 System32의 `nvcuda.dll`과 DriverStore의 드라이버 구성요소에서만 왔다.
- **실행:** 무작위 가중치 base 모델로 확인했다.
  - 인코딩은 GPU float16 0.035초, float32 0.047초였다. 자체 빌드 CPU float32와의 최대 차이는 float16 0.0126, float32 1.3e-5다.
  - 탐욕 생성 토큰(prompt `[[1,2,5,9],[1,3,5,9]]`, 24토큰)은 float16과 float32가 같았다.
- **확인하지 않은 것(NOT_RUN):**
  - 실제 음성, 실제 Whisper 가중치, faster-whisper 전체 경로의 GPU 전사
  - frozen 앱 안의 활성화
  - 다른 GPU·드라이버

## 미검증

실제 음성·Whisper 추론 품질, GPU, 장시간 입력의 메모리 상한, clean VM, 서명, Qt corresponding source 배포, Intel·Microsoft 조건의 법률 확인은 NOT_RUN 또는 G4 OPEN이다. L-P04가 공개되면 FFmpeg corresponding source와 코덱 특허 항목은 배포물에서 사라진다. 실제 스피커 청취, 음질, 재생 중 장치 변경은 확인하지 않았다. 3채널 이상의 mono 평균은 스피커 배치를 고려한 downmix가 아니다.
