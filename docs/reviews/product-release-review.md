# BR42 Windows 후보 패키징 독립 검토

검토자 R13/B13, 작성자 R11/B23. 상태: **REVIEW_READY — BR42-01·BR42-02 S2 OPEN, 수정 요청**. 제품 소스는 읽기만 했고 쓰기는 이 문서와 `tests/integration/test_release_independent.py`에 한정했다. 대형 PyInstaller 빌드·실제 EXE·AppData 설치·사용자 데이터·계정·음성·weights·외부 네트워크는 실행하지 않았다. fake TOC/EXE bytes·작은 임시 설치 디렉터리·합성 license만 사용했다.

## 범위와 기준

재개 계약, product-contracts, quality-system과 B23 release-checklist를 기준으로 `scripts/build_release.py`, `packaging/*`, `tests/release/*`를 읽었다. 원본/설정/키를 보존하는 version-directory 설치·업데이트·삭제, traversal/link/hardlink, frozen spawn 선행 dispatch, 실제 포함 inventory/SBOM/license와 가중치 차단, 오프라인/synthetic/offscreen 한계를 검토했다. 작성자 자체 시험 41 PASS는 이 독립 검토의 승인 근거를 대신하지 않는다.

## BR42-01 · S2 OPEN — 알려진 다른 모델 형식이 hook/설치 검증을 통과

- 위치: `packaging/recoryn.spec`의 data filter와 Analysis 이후 weights 검사, `release_manager.py`의 `WEIGHTS`/`verify`.
- 반례: fake Analysis의 `datas`에 `model.ort`, `weights.ckpt`, `model.tflite`, `weights.pkl`을 각각 넣는다. 차단 없이 두 fake EXE가 생성되고 analysis TOC가 기록된다. 같은 파일을 정확한 size/SHA256으로 등재한 임시 bundle도 `verify`가 정상 수락한다. bytes는 `synthetic-weight`뿐이며 실제 모델/역직렬화/빌드는 실행하지 않았다.
- 실제 결과: 네 확장자 × spec/verify **8 FAIL**. `.onnx` 양성 차단 대조군 2건은 PASS다. 현재 deny set은 `.onnx/.bin/.safetensors/.pt/.pth/.gguf`에 한정되어 있다.
- 영향: 임의 hook/package data가 해당 알려진 형식의 모델을 포함해도 "No model weights are bundled" 후보를 만들 수 있다. pickle 파일이 실제 실행되었다는 주장이 아니다.
- 해결 조건: 두 경계의 동일 정책으로 알려진 모델/객체 직렬화 형식을 거부하고 해당 반례를 통과시킨다. 정책이 감지할 수 있는 형식/이름의 범위를 명시하고 모든 임의 bytes가 모델이 아님을 증명한다고 확대하지 않는다. 단순 확장자 교체/새 형식의 한계와 개별 포함 파일 공급망 검토는 별도다.

## BR42-02 · S2 OPEN — TOC source의 UNC 경로를 로컬 경로 검사 전에 probe

- 위치: `packaging/release_evidence.py` `generate`의 `source_paths` comprehension(`Path(row[1]).is_file()`), 뒤 native source 순회도 같은 선검사 순서다.
- 반례: local TOC의 source 한 개를 `\\br42-never-contact.invalid\share\runtime.dll`로 둔다. `Path.is_file`을 관측 fake로 바꿔 실제 UNC 접근을 금지했는데, 로컬 경로 거부 전에 그 fake가 호출된다. 기대 `NETWORK_PATH_FORBIDDEN` 대신 `UNC_METADATA_PROBE_BEFORE_LOCAL_PATH_VALIDATION`로 실패했다.
- 영향: SDK/package 분석 입력이 네트워크 share를 참조하면 가중치 다운로드·오디오 전송이 아니더라도 SMB 파일 metadata 접근을 시도할 수 있다. TOC는 내부 빌드 입력이며 원격 공격자의 공개 API라고 가정하지 않는다. 실제 DNS/SMB/자격증명 전달은 실행·관측하지 않았다.
- 해결 조건: source TOC와 배포판 locate 경로를 `.is_file/stat/resolve/open` 등의 filesystem 작업 전에 `safe` 등 동일 로컬 경로 정책으로 확인한다. UNC/device namespace·reparse 등 거부와 정상 로컬 TOC/SBOM 회귀를 함께 확인한다. 잘못된 입력은 유효 manifest를 게시하지 않는다.

## 통과한 독립 경계와 한계

- manifest traversal/ADS/예약명/절대 경로/정규화되지 않은 경로는 destination 생성 전에 거부한다.
- 업데이트 복사 중 torn write와 예외가 발생해도 기존 current bytes·외부 원본·소스 후보를 유지하고 불완전 stage를 비활성으로 남긴다.
- 버전 안에 추가한 원본/변경 binary/hardlink가 있으면 제거 전체를 보류하고 외부 원본을 유지한다. 사용자 설치 디렉터리는 사용하지 않았다.
- GUI/CLI 양쪽은 fake spawn dispatch가 앱 import 전에 종료함을 확인했고 일반 import는 앱을 실행하지 않았다. 실제 frozen child의 성공을 뜻하지 않는다.
- fake 배포판 중 TOC에 관측된 것만 SBOM에 포함되고 설치만 된 배포판은 제외된다. 동봉 notice bytes·모든 포함 파일의 size/SHA·native source SHA·후보/NOT_RUN gate를 독립 계산했다. license의 법률 적합성이나 native 전이 구성의 완전성을 승인하지 않는다.
- spec의 onedir·dynamic Qt·UPX 비활성, source snapshot의 hash 비교, smoke의 합성 트랙·offscreen·장치/vault 접근 차단을 읽기 전용 확인했다. source smoke 및 native 라이브러리 import를 재실행하지 않았으며 Python audit만으로 native 전체 무송신을 증명하지 않는다.

## 실행과 snapshot

Windows / Python 3.13.1 / `.venv`. 독립 **18 PASS / 9 FAIL**, 작성자 release 시험 41개를 함께 실행한 결과 **59 PASS / 9 FAIL / skip·xfail 0**, 1.44s. 실패를 xfail/skip으로 바꾸지 않았다. 초기 독립 fixture의 Windows 파일명 정렬 오류 4건은 fixture 수정 후 통과했으며 제품 결함으로 집계하지 않는다.

```powershell
$br42Run = Join-Path $env:TEMP ('recoryn-br42-' + [guid]::NewGuid().ToString('N'))
.venv/Scripts/python.exe -m pytest tests/integration/test_release_independent.py tests/release -q -p no:cacheprovider --basetemp $br42Run -W error::ResourceWarning --tb=short
.venv/Scripts/python.exe -m ruff check tests/integration/test_release_independent.py
.venv/Scripts/python.exe -m ruff format --check tests/integration/test_release_independent.py
```

| 검토 파일 | SHA256 |
| --- | --- |
| scripts/build_release.py | 08A1E88FFA3AAA3A0C471E88ED2255A043A5FEF20F53F0239B1000D62B07BB27 |
| packaging/release_manager.py | 2E606B9487C16D8A10EC03AA792EA876024415F425F3298AF10C91C0C97A131D |
| packaging/release_evidence.py | FE8A263F412F8070783FC23B19C8521FDC5E740A72282CDAF6E2E3B74283CE98 |
| packaging/recoryn.spec | 35FF12C1613E8BFCAAAF0194592759CB4336EAA0F784FCC9D00A4C7DA0B40458 |
| packaging/entry_gui.py | 5EE21BF1BA4D18963AF7CE35ED2E5CF68B580E212D1A57FDCF1DC7E8243235EC |
| packaging/entry_cli.py | 13D0E276AE5FCCB29F50A98204BE88A8D15559AFAB7365CC7071C0B9B8509757 |
| packaging/recoryn_release.py | D94D467560F275C7DEFD812DB04ED98EB42A892CDCCBF58BA1D5FB72C6F156DB |
| packaging/release_smoke.py | 68A06E0154F228CDF865DCD7EC99FFB33E561329B5669B4A48F48F5D50CEEBA1 |
| tests/integration/test_release_independent.py | 8087D4027FE3377D4EB1DB31FE450ADACE86F7F9F29ED88FACEC297B2A07F89D |

판정: 두 S2는 R11 수정과 같은 독립 반례의 재확인이 필요하다. 현 후보 패키징을 최종 승인하지 않는다. clean Windows VM·최종 EXE/frozen smoke·서명·Qt/FFmpeg corresponding source·실제 모델/음성/하드웨어·G3/G4는 NOT_RUN이다. B22 자기 작성분의 독립 승인은 별도 BR41 담당이며 이 검토로 대체하지 않는다.

## R11 수정 후 동일 독립 검토자 재확인

R11 FIXED 보고 뒤 코드와 원 반례를 다시 대조했다. 최초 실패/hash/OPEN 기록은 위에 이력으로 보존한다. R13은 대상 소스를 수정하지 않았다.

| ID | 현재 판정 | 확인 근거 |
| --- | --- | --- |
| BR42-01 | RECHECKED | manager의 공유 `WEIGHTS` 21개 suffix를 spec의 수집 전 필터·Analysis 이후 거부·최종 verify가 함께 사용한다. `.ort/.ckpt/.tflite/.pkl` 원 8개 실패가 모두 PASS로 바뀌었다. `.onnx` 차단 대조군과 일반 `.exe/.dll/.pyd` 허용은 유지된다. 이름을 바꾼 임의 bytes의 판별 보장으로 확대하지 않는 한계도 코드에 명시됐다. |
| BR42-02 | RECHECKED | TOC/metadata source는 `_local`에서 UNC 문자열을 거부하고 lexical abspath→safe를 통과한 뒤 resolve/is_file/stat를 호출한다. 원 UNC fake probe에 도달하지 않고 `NETWORK_PATH_FORBIDDEN`으로 끝난다. 정상 로컬 source의 SBOM/native/notice/hash 회귀도 유지된다. 실제 네트워크 접근을 실행한 검증이 아니다. |

원 독립 27개와 현 release 시험을 함께 실행해 **90 PASS / 2.24s / skip·xfail 0**을 확인했다. 실패의 skip/xfail 전환 없이 원 oracle가 통과했다. 독립 파일 Ruff check/format PASS다. writer의 후속 전체 179 PASS 자체 보고와 이 독립 실행은 중복 가능해 합산하지 않는다.

후속 선택 diarization 패키징도 읽기 전용 확인했다. spec이 onnx/sherpa-onnx/sherpa-onnx-core/numpy의 고정 버전과 실제 RECORD 기반 dist-info, data/DLL을 수집하며 builder가 네 package pin을 확인한다. mock Analysis/hook 실행 회귀도 통과했다. 실제 frozen metadata/import·DLL 로딩·EXE spawn은 아직 실행하지 않았고 source smoke PASS를 그 승인으로 바꾸지 않는다.

| 수정 후 대상 | SHA256 |
| --- | --- |
| packaging/release_manager.py | 3C6670D2DB494A80F7EACB0FDCEBA15C56AD355FC24EA0F4E7475CF78E61F6C3 |
| packaging/release_evidence.py | 681458DB72811BD4050CA08F155CFC37B78AADFECDA20C0B15C27A5DEC2238F1 |
| packaging/recoryn.spec | CD1807963719BF2E51F4D4D54942F13D87B3DCCE187F28FB1DFC5CC9C30A037C |
| scripts/build_release.py | B8B88E67B03CDF6885E0B219AC528F499AB92BA90BE8680CC446A926A793812D |

**BR42 2/2 RECHECKED, 이번 두 지적의 남은 OPEN S0/S1/S2 0건.** 최종 codefreeze·실제 포함 artifact·동일 hash의 frozen smoke·서명/clean VM/라이선스 조건은 root가 통합한다. 후보 코드의 재확인과 공식 릴리스/G4를 구분한다.
