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

## 미검증

실제 음성·Whisper 추론 품질, GPU, 장시간 입력의 메모리 상한, clean VM, 서명, Qt corresponding source 배포, Intel·Microsoft 조건의 법률 확인은 NOT_RUN 또는 G4 OPEN이다. L-P04가 공개되면 FFmpeg corresponding source와 코덱 특허 항목은 배포물에서 사라진다. 실제 스피커 청취, 음질, 재생 중 장치 변경은 확인하지 않았다. 3채널 이상의 mono 평균은 스피커 배치를 고려한 downmix가 아니다.
