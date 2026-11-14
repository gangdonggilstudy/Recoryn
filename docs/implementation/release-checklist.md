# B23 Windows 개발 후보 패키징 체크리스트

상태: **REVIEW_READY — 자체 검증 및 BR42의 두 발견 RECHECKED, root 통합 대기. 공식 릴리스·G4 승인이 아니다.**
R11/B23 작성자는 패키징 코드와 시험을 제출하고 root가 독립 검토·공용 연동·최종 artifact 생성·commit/push를 통합한다. 저장소의 staged/unstaged/untracked 복구 입력을 보존했으며 worker는 Git 인덱스를 변경하지 않았다. B11 reader/remote-intent/resume 및 BR11 현재 snapshot을 먼저 대조했다. P0.1의 과거 379건을 현재 통과로 재사용하지 않는다.

## 구현 경계

- `scripts/build_release.py`: 기존 경로를 덮어쓰지 않는 Windows 빌더. `build/`·`dist/` 아래 또는 별도 지정 경로에 고유 출력을 생성한다. 코드·frozen entry·spec·빌드 스크립트·설정·requirements·LICENSE를 복사하고 전후 SHA256을 확인한다. 입력 복사 중 수정은 실패하며 살아 있는 workspace를 reset하지 않는다.
- `packaging/entry_gui.py`, `entry_cli.py`: `freeze_support()`가 앱/Qt/CLI import보다 먼저 실행된다. 일반 import는 앱을 시작하지 않는다. GUI/CLI EXE는 동적 Qt를 포함하는 공유 onedir이며 UPX/onefile을 사용하지 않는다.
- 선택 로컬 AI baseline은 Faster-Whisper/AV/CTranslate2/ONNX Runtime/tokenizers다. 모델/VAD weights를 포함하지 않는다. 최초 data filter 뒤 hook이 추가한 weights도 EXE 생성 전에 거부한다. STT는 별도 사용자 설치 모델을 요구하고 제품 어댑터의 `vad_filter=False` 계약을 유지한다.
- `release_manager.py`: 기본 `%LOCALAPPDATA%\Programs\Recoryn`에 소유 marker·파일 잠금·version 디렉터리·원자 current pointer를 사용한다. 갱신은 복사/검증 후 활성화하고 실패하면 이전 pointer를 유지한다. 손상된 현재 앱에서도 검증된 이전 버전으로 rollback할 수 있다. DB downgrade/migration은 수행하지 않는다.
- 제거는 활성화를 해제하고 검증된 소유 파일만 삭제한다. 잠긴 파일은 `pending`으로 보존하고 외부 후보 CLI로 재시도한다. 변조·추가 파일이나 미디어가 섞인 버전은 전체를 보류한다. 재귀 강제 삭제, 다른 프로세스 종료, 기존 키/계정·원본·설정·모델 삭제는 하지 않는다.
- UNC·parent traversal·link/reparse·hardlink·ADS·예약명·중복 경로/JSON key·미지원 schema를 거부한다. 이는 같은 사용자 권한의 공격자가 경로를 동시에 교체하는 상황에 대한 OS sandbox 보장은 아니다.
- 설치는 지정 디렉터리의 CLI 방식이다. 반환 `launch` 경로로 GUI를 실행한다. Start 메뉴·바탕화면 shortcut, registry 등록, 자동 업데이트는 구현하지 않는다. 기본 설치 위치는 미디어의 기본 `%LOCALAPPDATA%\Recoryn`과 분리된다. 명시 destination은 사용자 선택 위치이며 관리자 승격을 요청하지 않는다.

## 빌드 입력과 증거

현재 개발 환경 baseline: Windows Python 3.13.1, PyInstaller 6.22.3, PySide6-Essentials/Addons 6.12.0, Faster-Whisper 1.2.1, AV 16.1.0, CTranslate2 4.9.0, ONNX Runtime 1.32.0, NumPy 2.3.5, tokenizers 0.23.3, huggingface-hub 2.4.0. root 추가 배정으로 **sherpa-onnx/core 2.0.1, ONNX 1.23.2**도 포함한다. 빌더는 Windows/Python3.13과 이 직접 pin을 요구한다. spec은 정확한 pin이 설치된 경우에만 선택 모듈·DLL/data·실제 dist-info metadata를 수집한다. source smoke는 실제 native import와 model_state=not_checked인 capability를 확인했지만 frozen 포함/import는 대형 빌드 후 별도 검증한다. 모든 전이 패키지의 wheel hash lock과 깨끗한 빌드 commit은 root의 후속 게이트다.

| 산출물 | 실제 관측과 한계 |
| --- | --- |
| `inputs/build-inputs.json` | 복사한 전체 입력의 상대 경로·크기·SHA256. 빌드는 이 snapshot에서 실행한다. |
| `analysis-toc.json` | GUI/CLI 실제 PyInstaller pure/binaries/datas 분석 결과. 절대 빌드 경로가 있으므로 내부 빌드 증거이며 배포물에 복사하지 않는다. |
| `release-manifest.json` | 실제 포함 파일 전수의 상대 경로·크기·SHA256. 변경/추가/누락 검출 기준이며 manifest 자체의 진위 서명이 아니다. |
| `sbom.cdx.json`, `licenses/`, `NOTICE.txt` | TOC에 관측된 실제 package input의 배포판 이름·버전·선언 license·source hash·수집 notice를 연결한다. 빌드 환경에 설치됐다는 이유로 모든 package를 runtime SBOM에 넣지 않는다. |
| `native-origins.json` | 실제 포함 EXE/DLL/PYD hash와 binary/data TOC 출처 hash를 연결한다. 직접 귀속 없는 파일은 `REVIEW_REQUIRED`. EXE 내 bootloader·codec/Qt 내부 전이 구성의 완전한 법률 SBOM을 보장하지 않는다. |
| `build-provenance.json` | Python/platform/패키저/hooks 버전, 소스·빌드 입력과 분석 TOC hash, 미실행/검토 대기 게이트. |

공식 자료 대조: [PyInstaller 6.22.3 multiprocessing/freeze_support](https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html#multi-processing), [spec/Analysis·EXE·COLLECT](https://pyinstaller.org/en/stable/spec-files.html), [Qt for Python 제3자 license](https://doc.qt.io/qtforpython-6/licenses.html). 설치된 PyInstaller multiprocessing runtime hook과 AV/ONNX Runtime 수집 hook도 읽었다. Qt/FFmpeg의 해당 바이너리 빌드 옵션·notice·corresponding source·교체 의무, 전이 native license 및 서명 결정은 **REVIEW_REQUIRED/NOT_RUN**이며 자동 수집으로 종결하지 않는다.

## 자체 시험과 root 실행 절차

온보딩 후 재부팅 복구 기준 회귀: B11 jobs/content/runner와 BR24 publication, BR11 native/audio/wasapi 및 초기 release 시험을 합쳐 **352 PASS / 0 FAIL**. 고유 TEMP basetemp, cache provider 비활성, ResourceWarning 오류 처리. 이 수치는 아래 새 packaging 시험과 중복되므로 합산하지 않는다.

패키징 새 자체 시험은 **41 PASS**이며 B11/BR24/BR11과 함께 최신 **371 PASS / 0 FAIL**(6.73초)다. Ruff check/format 및 `MYPYPATH=src`의 packaging/scripts mypy 7파일이 통과했다. 소유 디렉터리 설치·갱신·롤백·잠금·실패·반복 제거, 원본 canary 보존, inventory/hash/TOC/SBOM 귀속, concurrent source edit, spawn 선행 dispatch와 hook weights 거부를 synthetic fixture로 검사했다. 실제 AppData 설치/계정 변경은 하지 않았다.

소스 smoke는 별도 자식에서 실행한다. 실제 가중치 없이 spawn import와 production inference worker의 요청 없는 시작/종료를 확인하고, 0.1초 합성 mic 4410/system 4800 frame을 분리 저장·WAV export한다. 원본 hash 불변, 기본 Gateway의 DNS 전 거부, offscreen UI 종료 ACK를 검사하며 native device/capture/vault 접근 시 실패한다. Python socket audit guard를 사용하며 외부 native DLL/daemon 트래픽 전체를 관측한 무송신 인증은 아니다.

```powershell
$r11Temp = Join-Path $env:TEMP ('recoryn-r11-release-' + [guid]::NewGuid().ToString('N'))
.venv/Scripts/python.exe -m pytest tests/release -q -p no:cacheprovider --basetemp $r11Temp -W error::ResourceWarning
$env:MYPYPATH = (Resolve-Path src).Path
.venv/Scripts/python.exe -m mypy packaging scripts/build_release.py
.venv/Scripts/python.exe -m ruff check packaging scripts/build_release.py tests/release
.venv/Scripts/python.exe -m ruff format --check packaging scripts/build_release.py tests/release
$env:PYTHONPATH = ((Resolve-Path packaging).Path + ';' + (Resolve-Path src).Path)
.venv/Scripts/python.exe -c "import json; from release_smoke import run; print(json.dumps(run(),sort_keys=True))"
```

최종 대형 빌드는 root가 B21/B22 의존성·동적 import·공용 CI/CLI 정책을 통합하고 독립 리뷰어를 배정한 뒤 진행한다. worker가 공용 CI/pyproject/CLI/__main__을 수정하지 않는다. 제안 명령:

```powershell
$candidate = Join-Path (Get-Location).Path ('build/release-' + [guid]::NewGuid().ToString('N'))
.venv/Scripts/python.exe scripts/build_release.py --output $candidate --smoke
# 이후 개발 도구/Python/모델 없는 clean Windows VM에서 동일 artifact로 검사한다.
& "$candidate/dist/Recoryn/Recoryn-CLI.exe" --release-install --destination '<사용자 범위 설치 위치>'
& "$candidate/dist/Recoryn/Recoryn-CLI.exe" --release-rollback --destination '<같은 설치 위치>'
& "$candidate/dist/Recoryn/Recoryn-CLI.exe" --release-uninstall --destination '<같은 설치 위치>'
```

## 남은 게이트

최종 frozen 빌드·frozen smoke·clean VM 설치/제거·서명·license/corresponding source 검토, Windows 장치/장시간/절전, 실제 모델 품질·GPU·외부 서비스는 **NOT_RUN**이다. 실제 캡처·모델/weights 다운로드·유료 호출·실계정 변경을 자동 시험하지 않는다. 소스 smoke를 frozen artifact 통과로 바꾸지 않는다. 최종 artifact와 시험·증거 hash가 같아야 하며 파일 변경/서명 뒤에는 inventory를 재생성하고 smoke를 다시 실행해야 한다.

## 제출 snapshot

2026-11-14 R11 자체 제출. 마지막 test_evidence의 모듈 monkeypatch 타입 경로 정리 후 해당 4시험을 다시 실행해 PASS, runtime/script/test의 mypy **12파일 PASS**, Ruff check/format PASS였다. 동작은 앞선 371건과 같다. code freeze·helper/guard 통합 후 root가 대형 빌드를 수행하며 R13이 패키징을 독립 검토한다. 작성자가 최종 승인하지 않는다.

| 파일 | SHA256 |
| --- | --- |
| packaging/release_manager.py | 2e606b9487c16d8a10ec03aa792ea876024415f425f3298af10c91c0c97a131d |
| packaging/release_evidence.py | fe8a263f412f8070783fc23b19c8521fdc5e740a72282cdaf6e2e3b74283ce98 |
| packaging/release_smoke.py | 68a06e0154f228cdf865dcd7ec99ffb33e561329b5669b4a48f48f5d50ceeba1 |
| packaging/recoryn.spec | 35ff12c1613e8bfcaaaf0194592759cb4336eaa0f784fcc9d00a4c7da0b40458 |
| scripts/build_release.py | 08a1e88ffa3aaa3a0c471e88ed2255a043a5fef20f53f0239b1000d62b07bb27 |

## BR42-01/02 수정 및 선택 화자 런타임 추가

R13 독립 검토가 알려진 다른 모델 포맷 8반례와 UNC metadata 선조회 1반례를 제출했다. R00 배정 후 작성자가 수정했다. 원 발견·실패·최초 digest는 [BR42 리뷰](../reviews/product-release-review.md)에 보존하고 R13 재확인 전 독립 종결하지 않는다.

- BR42-01: `release_manager.WEIGHTS` 하나를 spec 사전 data 필터·Analysis hook 뒤 검사·설치 verify에서 공유한다. `.ort/.ckpt/.tflite/.pkl/.pickle/.joblib/.h5/.hdf5/.pb/.npy/.npz` 등 알려진 모델/직렬화 suffix를 거부하고 `.dll/.exe/.pyd` runtime은 허용한다. 확장자를 바꾸거나 새 형식으로 위장한 임의 bytes의 부재를 증명하지 않으며 실제 inventory 공급망 검토가 필요하다.
- BR42-02: TOC 및 distribution locate 경로는 UNC/device 문자열 검사와 lexical 정규화 → `safe` 검증 뒤에만 `resolve/is_file/stat/open`에 도달한다. distribution RECORD의 로컬 `../Scripts` 표현은 lexical 정규화로 처리하며 network probe를 먼저 하지 않는다. 원 반례에서 probe 0과 로컬 정상 SBOM을 확인했다.
- 원 BR42 반례+초기 release **68 PASS**. 후속 모델/직렬화 suffix 대문자 전수 차단과 native runtime 허용, 선택 package 수집을 보강했다. frozen에 필요한 metadata도 수집하여 capability가 단순 import 성공이나 모델 준비와 혼동되지 않게 한다.
- 선택 source smoke는 onnx1.23.2/sherpa2.0.1을 실제 import하고 core metadata2.0.1 및 capability를 검사한다. inference/weights 요청은 없다. native ORT DLL의 동시 번들 경로·버전 호환성은 실제 frozen smoke와 inventory에서 추가 확인한다.

후속 source smoke와 B22/BR41/BR42/release 결합 회귀·정적 검사 최종 결과는 root에 전달한다. 대형 EXE 빌드·frozen smoke·clean VM은 여전히 NOT_RUN이다. 위 이전 제출 digest는 변경 이력이고 root의 최종 artifact는 새 source digest에서 생성해야 한다.

최종 결합 **182 PASS / 0 FAIL / 0 SKIP / 7.49s**(B22 55, BR41 37, release 63, BR42 27; 중복 없는 이 실행의 구성)와 Ruff check/format·strict mypy 20파일 PASS를 확인했다. 추가 source smoke도 PASS이며 onnx1.23.2/sherpa2.0.1/core metadata2.0.1, cpu capability=True/model_state=not_checked, 합성 mic4410/system4800 frame·WAV 원본 불변·offscreen ACK를 확인했다. source import는 frozen 포함이나 모델 품질 증거가 아니다. R13에게 새 spec/수정 코드의 독립 재확인을 요청했다.

| 최종 제출 파일 | SHA256 |
| --- | --- |
| packaging/release_manager.py | 3c6670d2db494a80f7eacb0fdceba15c56ad355fc24ea0f4e7475cf78e61f6c3 |
| packaging/release_evidence.py | 681458db72811bd4050ca08f155cfc37b78aadfecda20c0b15c27a5dec2238f1 |
| packaging/release_smoke.py | df9a03754d306e33758236d1c055e8ad2239f4af1f803234ad7c9de4967f89e4 |
| packaging/recoryn.spec | cd1807963719bf2e51f4d4d54942f13d87b3dcce187f28fb1dfc5cc9c30a037c |
| scripts/build_release.py | b8b88e67b03cdf6885e0b219ac528f499ab92ba90be8680cc446a926a793812d |

R13의 [수정 후 독립 재확인](../reviews/product-release-review.md)에서 원 BR42 반례를 포함한 **90 PASS**, 2/2 RECHECKED와 위 수정 대상 digest 일치를 확인했다. 이 독립 코드 재확인은 최종 frozen artifact의 검증을 대신하지 않는다.
