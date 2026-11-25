# G13 / G-P13 수동 로컬 모델 digest·신뢰 확인·로드 범위 계약안

상태: **C00 계약 승인 대기 — 문서만 작성, 제품 구현·제품 시험·mutation 미실행**. 작성자 w5:p8 Codex. 수동 디렉터리 허용은 유지한다. 이 문서의 S04 예외·확인 수명·고정 bundle·API·파일·시험 분모는 제안이며 독립 검토/최종 통합은 별도다.

## 1. 정본·의존성·현재 쓰기

- 정본: `v1-gap-plan.md`의 G01B-032 결정/G-P13, architecture ADR17, G01B-032/F-MOD02, G01BR-05, G01CC-B02, validation S04, product-contracts B13. 통합 등급은 S2다. 자체 hash와 신뢰 출처/라이선스 인증을 구별하며 수동 모델 전체 차단으로 이 gap을 닫지 않는다.
- 이번 쓰기는 **docs/testing/g13-manual-model-cases.md 하나**다. 구현은 계약 승인과 C00 시작 신호 뒤다. 공유 `ui/ai_bridge.py`·`ui/models.py`·`models/*`·`transcription/adapters.py` 때문에 **G-P02/P06/P07 뒤, G-P11a/P11b의 자원/worker 계약이 반영된 tree 위**에서 직렬 구현하는 안을 제안한다. G-P12가 먼저 app/bridge/접근성을 바꾸면 그 변경도 보존한다. 정확한 통합 순서·기준 tree/hash는 C00가 착수 시 고정한다.
- G-P11의 worker 생성 전 lease·실제 종료 ACK·Job 사이 warm cache 없음, CPU 무동의 전환 금지, `_activate_gpu` 뒤 CTranslate2 import를 유지한다. G-P03 게시 CAS·G-P02 동의·G-P06 비용도 그대로다. 새 model 확인은 전송 grant나 다운로드 동의가 아니다.
- 현재 실제 모델/weights·장치·네트워크·설치·계정·vault 쓰기·추가 agent/pane·Git 쓰기를 수행하지 않는다. 모델별 공급망/실제 license 법률 판정과 SDK 실모델 검증은 외부 게이트다. 기존 binary/GPU runtime 라이선스 이력을 모델 가중치 승인으로 옮기지 않는다.

## 2. 직접 확인한 경로

조사 시 HEAD는 `21a58bfa99c3ab4a381b92a092d5981adc5c9632`다. 작업 트리에 다른 단위 변경이 섞여 있다. 아래는 현재 소스와 기존 시험을 읽은 사실이고 새 제품 실행 증거는 아니다.

| 근거 | 확인한 사실 |
| --- | --- |
| `src/recoryn/ui/ai_bridge.py`의 local 전사 준비 | model.bin/config.json/tokenizer.json bytes를 경계 구분 없이 이어 SHA256으로 만든다. config/process key에는 쓰지만 사용자 확인 기록·신뢰 ModelSpec 대조는 없음 |
| `src/recoryn/models/manager.py` ModelSpec/install/verify | caller-reviewed manifest·명시 승인·파일별 size/hash·경로/전체 파일 집합 검사. verify는 설치 폴더 installed.json의 spec을 읽는다. docstring도 hash가 게시자를 인증하지 않는다고 명시 |
| `src/recoryn/ui/models.py` choose_manifest/download/choose_installed | URL/license/크기/hash preview와 승인 checkbox가 있다. 설치 후 SHA256 확인 표시는 실제로 manifest 파일과의 기술적 대조이지 독립 게시자 인증이 아님 |
| `src/recoryn/transcription/adapters.py` FasterWhisperProvider | 명시 로컬 Path/필수3파일·lazy import·local_files_only. native factory에는 원 디렉터리 경로를 넘기며 확인한 bytes와 native가 읽는 bytes를 같은 사본으로 고정하지 않음 |
| 설치된 `.venv/Lib/site-packages/faster_whisper/transcribe.py:631,674,700,729` | files 인자와 tokenizer/preprocessor bytes 경로가 있다. preprocessor_config.json은 디렉터리에서 추가로 읽을 수 있음. tokenizer bytes가 없으면 from_pretrained 경로도 있으므로 필수 tokenizer 보존이 중요함 |
| `scripts/compare_ctranslate2_builds.py:120` | synthetic CT2 모델의 model.bin/config.json/**vocabulary.json**를 다룬다. 세 파일 hash만으로 실제 load 입력 전체를 대표할 수 있다고 단정하지 않음 |
| `src/recoryn/diarization/models.py` verified_models | 사용자 고정 manifest SHA·role별 모델 size/hash·license text hash·URL·허용 runtime·필수 이름을 확인. manual 예외로 이 검사를 풀면 안 됨 |
| `src/recoryn/diarization/backend.py` compute | 모델 bytes 검증→ONNX external tensor 감사→소유 TEMP 사본→sherpa native 경로. 원 모델을 native가 직접 재개방하는 경로는 아님. TEMP 파일의 로드 수명도 이번에 고정할 대상 |
| `tests/contract/test_diarization_contract.py::test_model_change_between_snapshot_and_child_is_denied` | 이름과 달리 실제 assertion은 compute에 잘못된 **audio hash**를 주어 DIARIZATION_AUDIO_CHANGED를 확인한다. 이를 모델 weights TOCTOU 검증 증거로 재사용하지 않음 |
| `src/recoryn/storage/_safe.py` root_path/check_path/open_file | UNC·reparse/hardlink·열기 중 file identity 대조가 있다. 같은 사용자 권한의 경쟁 공격에 대한 OS sandbox가 아니라는 한계를 이미 명시 |

## 3. 신뢰 등급·license 표시·S04 개정 제안

### 3.1 출처와 기술 검증을 분리

| source_kind / 표시 | 실행 자격 | 보장하지 않는 것 |
| --- | --- | --- |
| MANAGED_PIN_MATCH / “관리 설치 — 확인한 manifest와 파일 일치” | ModelManager root/ID/파일 집합 검증, **확인 화면에 고정한 ModelSpec digest**와 installed spec 대조, 현재 파일 size/hash, 출처/license 명시 확인 | installed.json 존재나 hash만으로 게시자 신원·법률 적합성·모델 품질 인증 아님 |
| MANUAL_USER_CONFIRMED / “사용자 지정 모델 — 출처 인증 안 됨” | 지원 data-only 모델 구조·로컬 경로·고정 load digest, 사용자 책임/license 고지와 해당 digest 명시 확인, 실행 전 재검사/고정 bundle | 자체 digest는 공식 digest 대조가 아님. S04의 관리 공급망 인증과 다름 |
| UNCONFIRMED | preview/읽기만, native factory0 | 폴더 선택·자체 hash 계산이 실행 동의가 아님 |
| CHANGED/INVALID/UNSUPPORTED | 해당 계획 실행 거부, 현재 원본/기존 결과 보존, 재선택·재확인 안내 | 자동으로 새 bytes를 채택하거나 관리 오류를 수동 성공으로 낮추지 않음 |

`source_authenticity`, `integrity_state`, `license_state`를 서로 다른 표시로 둔다. 관리 설치라도 공식 원문/서명/독립 검토 근거가 없으면 source_authenticity=UNVERIFIED다. managed 경로 밖의 폴더에 installed.json이 있어도 관리 설치로 승격하지 않는다. managed 손상은 “검증 실패”로 남긴다. 수동으로 쓰려면 사용자가 **별도 수동 채택**을 선택하고 새 고지/확인을 거쳐야 하며 자동 fallback은 없다.

관리 실행의 expected reference는 설치 전 UI가 고정한 검토 ModelSpec 또는 사용자가 모델 폴더와 별개로 제시/확인한 manifest다. **현재 installed.json을 읽고 그 값을 자기 자신의 기대값으로 삼는 것만으로 실행 증거를 발급하지 않는다.** 새 실행에 reference가 없으면 미확인 상태로 두고 manifest 재제시/확인을 요청하거나 명시 수동 채택을 안내한다. 기존 ModelManager.verify의 목록용 구조 검사는 호환으로 유지할 수 있지만 제품 native gate는 reference 대조를 추가로 요구한다. 사용자가 제시한 manifest 자체의 진위는 앱의 자동 인증 범위가 아니다.

라이선스는 관리 ModelSpec의 license_id/URL 및 선언된 license 파일 hash를 표시한다. 사용자가 조건을 확인했다는 기록은 **USER_ACKNOWLEDGED**, 그 자체가 법률 승인/재배포 허가가 아니다. license text가 없으면 METADATA_ONLY로 구별하고 S04의 법률/출처 검증까지 완료됐다고 표시하지 않는다.

수동 Whisper는 license 정보/파일이 없더라도 “조건 미확인 — 사용 권한 확인은 사용자 책임”을 보여 주고 **별도 명시 책임 확인**으로 사용할 수 있게 하는 예외를 제안한다. None을 “MIT/허용”으로 채우지 않는다. license 파일이 있으면 고지 digest에 포함하며 변경 시 재확인한다. **화자 모델은 예외로 완화하지 않는다**: 고정 manifest·두 ONNX·두 license 파일 검증과 license_accepted가 모두 필요하다. 표시 등급은 사용자 고정 manifest 일치이며 게시자 인증 완료가 아니다.

### 3.2 S04/ADR17에 C00가 반영할 문구안

> S04 관리 설치·로드는 사용자가 출처와 라이선스를 검토해 고정한 manifest, 선언된 파일 size/hash·license 정보, 설치/로드 전 검증을 요구한다. 설치 폴더의 자기 기술만으로 신뢰 등급을 올리지 않는다. digest 일치는 게시자 인증·법률 검토와 구별한다. 수동 로컬 Whisper 디렉터리는 B13 예외로 허용하되 사용자 지정 모델로 표시하고, 최초·digest/출처/고지 변경 시 사용자 책임과 license 미확인 상태를 명시 확인한다. 실행 bytes를 고정하고 재검사하며 자동 다운로드·remote code·묵시 fallback을 허용하지 않는다. 이 예외를 관리 공급망 검증 완료로 집계하지 않는다. 화자 구분의 기존 manifest/model/license hash·ONNX 외부 데이터 거부는 예외에서 완화하지 않는다.

이는 **개정 제안**이며 현재 validation-plan을 이미 고친 것이 아니다. C00가 별도 정본 문서 단위로 validation S04·ADR17/B13 적용 범위를 반영한 뒤 제품 구현 수락에 사용한다. 이 worker의 미래 쓰기 목록에도 정본 문서 수정은 포함하지 않는다. 모델별 공식 digest·출처/license/실제 가중치 검증이 없는 경우 그 외부 게이트는 OPEN/NOT_RUN으로 유지한다.

## 4. digest·확인 기록·API

### 4.1 읽을 수 있는 입력 집합과 hash

Whisper load 입력은 기존 필수 **model.bin/config.json/tokenizer.json**과 존재하는 **vocabulary.json/preprocessor_config.json**을 고정한다. 선택된 SDK의 파일 mapping 안에서만 제공하고, 인식하지 못하는 추가 load 요구는 CAPABILITY_UNSUPPORTED로 중단한다. 원 폴더에 없는 vocabulary가 해당 모델에 필수이면 native의 안전한 형식 실패이며 자동 취득하지 않는다. README 등 실제 로더에 제공하지 않는 파일은 실행 digest에 넣거나 TEMP로 무차별 복사하지 않는다. 부가 license 파일은 별도의 terms digest 대상이다.

optional 파일의 **있음/없음도 입력**이다. preprocessor가 없으면 고정 loader 계약의 기본 `{}` bytes를 제공해 원 폴더/상대 경로로 찾지 않게 한다. tokenizer는 누락/빈값을 허용하지 않고 from_pretrained fallback0이다. 관리 ModelSpec가 추가 파일을 선언했으면 manager의 전체 집합 검사는 계속 수행한다. 소스의 임의 Python/pickle/custom-op DLL을 로드하지 않는다. ONNX 외부 tensor/remote code 거부도 유지한다.

신규 `models/artifacts.py`의 frozen DTO는 `ModelSourceSnapshot`, `ModelUseEvidence`, `FrozenModelBundle`의 안전 metadata를 정의한다. artifact digest는 **version·kind·loader-contract·정렬된 (정규 상대 이름, size, SHA256, optional 존재/기본 표시)**의 canonical JSON에 domain tag를 붙여 계산한다. 단순 bytes 연결을 폐기하고 파일명·경계 변경도 다른 identity로 본다. runtime/device/정밀도는 G-P11의 별도 계획 identity이고 모델 digest와 섞어 현재 free memory에 따라 바뀌게 하지 않는다.

`terms_digest`는 표시한 source/license metadata·license bytes hash와 UNKNOWN 표식을 고정한다. URL을 열지 않고 미제공을 표시한다. 같은 content라도 role/loader 계약이 다르면 서로의 증명을 재사용하지 않는다. file identity/경로는 승인 binding의 별도 필드이고 content hash와 구별한다.

### 4.2 명시 확인·수명

ModelPanel은 전체 artifact SHA256·파일별 이름/size/hash·source_kind·인증 범위·license 상태·role·복제 공간 안내를 preview한다. 큰 파일 hash는 기존 독립 AI/모델 lane에서 chunk 단위 취소 가능하게 수행하며 GUI/녹음 writer에서 동기 실행하지 않는다. 확인 창은 기본 No·Esc 거부다. 책임/조건 checkbox는 미선택이고, **표시한 digest/terms를 immutable snapshot으로 Yes에 연결**한다. 확인 중 bytes/경로/세션 context가 바뀌면 그 화면으로 새 bytes를 승인하지 않는다.

확인은 현재 실행 세대의 메모리에만 둔다. key는 `(library_instance, execution_generation, source root identity, kind, loader_contract, artifact_digest, terms_digest, source_kind)`다. source root identity는 검증한 volume/file identity와 정규 경로를 포함한다. 별도 audio session의 데이터 전송 권한은 포함하지 않으며 모델 확인을 세션/LIBRARY 전송 grant로 승격하지 않는다.

최초 사용·content/optional 입력/terms 변화·다른 root/출처 모드·새 앱 실행/restore/import 뒤에는 다시 확인한다. 같은 현재 key는 여러 요청에서 쓸 수 있지만 **각 새 Job은 원 source를 다시 검사**한다. UI poll·같은 모델 재표시로 승인/알림을 반복하지 않는다. 기록을 모델 폴더·installed.json·설정/DB에 “영구 신뢰”로 저장하지 않는다. G-P09 backup/restore가 실행 권한을 복원하지 않으므로 새 표/migration도 없다.

ModelUseEvidence는 검증된 record ID·고정 snapshot/key를 참조한다. trusted app 내부 coordinator가 발급하며 모델 폴더의 자기 assertion으로 만들지 않는다. child IPC는 앱이 만든 frozen metadata이며 외부 모델 pickle 역직렬화가 아니다. 객체가 같은 사용자 프로세스의 악성 코드까지 막는 암호 인증이라고 주장하지 않는다.

## 5. 실행 직전 검사·고정 bundle·TOCTOU

### 5.1 경로 검사 순서

신규 `models/_artifact_io.py`는 먼저 lexical 절대 drive 경로/namespace/ADS 검사와 GetDriveTypeW의 로컬 종류 판정을 한다. UNC·device/extended namespace·상대/drive-relative·network mapping은 **stat/open/resolve/realpath 전에 거부**한다. 드라이브 정보 불명도 안전 실패다. 링크/junction/reparse·hardlink·상위 구성요소 치환을 열기 전/후 identity로 검사한다. 별칭·8.3/case 정규화는 로컬 판정 뒤의 실제 handle identity로만 한다. 테스트는 fake path API/감시 함수를 사용하고 원격 경로를 실제 접근하지 않는다.

### 5.2 native에 원 source 경로를 주지 않음

1. 준비 단계는 source snapshot/hash/확인 record를 고정한다. 모델 확인이 없으면 **Job 미접수·native0**으로 모델 확인 화면을 안내한다. 동의/키/비용 준비를 모델 책임 확인으로 대체하지 않는다.
2. G-P11 runner/lease 입장 뒤, **native 직전** original source의 identity·입력 집합·hash·terms를 다시 대조한다. queued 동안 바뀌면 기존 계획을 실패시키고 새 확인/새 요청을 요구한다. 대기 task가 현재 UI의 새 모델 경로를 다시 읽지 않는다.
3. chunk 단위로 **소유 TEMP bundle**에 필요한 load/license 파일만 복제하고, 복제한 bytes/크기·manifest를 승인 snapshot과 대조한다. source 열기 전/후 file identity와 입력 집합도 대조한다. 중간 변경·취소·short write·ENOSPC이면 native0이며 부분 사본은 다음 실행에 재사용하지 않는다. “해시 확인 후 원 경로로 재열기” fallback은 없다.
4. bundle의 파일/디렉터리 identity를 seal하고 읽기 handle을 유지한다. Windows에서는 snapshot 파일의 write/delete 공유를 허용하지 않는 guard를 유지하며 이름 치환 방지도 검사한다. 특히 sherpa가 이름으로 재개방하는 snapshot 경로는 상위 구성요소도 handle identity/이름 변경 방지 guard로 고정한다. 이를 지원/확인할 수 없으면 capability 실패로 남긴다. child가 실제 사용할 snapshot을 다시 확인한 뒤에만 loader에 전달한다. 파일만 readonly attribute로 설정하고 안전하다고 하지 않는다.
5. Whisper에는 **pinned SDK의 files mapping**으로 작은 metadata bytes와 snapshot의 file-like reader를 제공한다. identifier는 파일 경로로 해석하지 않는 bundle ID다. tokenizer bytes와 preprocessor bytes/고정 기본을 반드시 제공해 Python 계층의 원 경로/Hub fallback을 차단한다. SDK가 이 계약을 지원하지 않으면 명시 capability 실패이며 원 디렉터리 재시도0이다. 큰 model.bin 전체를 Python bytes로 이중 복사하는 구현을 기본으로 삼지 않는다. 실제 native의 메모리 사용은 별도 게이트다.
6. 화자 모델은 기존 manifest/model/license 검증과 ONNX byte 감사를 먼저 하고, 그 bytes로 만든 **guarded snapshot 경로**만 sherpa에 준다. manifest/user hash·모델/라이선스가 달라지면 새 사용자 확인으로도 자동 면제하지 않는다. 기존 guarded child·Windows Job gate·CPU-only를 보존한다.
7. bundle guard/worker reply의 artifact/manifest digest와 승인 계획을 대조한다. parent G-P11 lease와 소유 객체는 **실제 child 종료 ACK 뒤** 해제한다. model lazy read 가능성 때문에 생성자가 끝났다는 이유로 snapshot 파일을 지우거나 lock을 풀지 않는다. live 한 Job 안 재사용은 같은 고정 bundle이며 Job 사이 warm cache는 없다.

seal 뒤 original source 변경은 **현재 native 입력을 바꾸지 않는다**. 현재 Job은 확인한 옛 digest 사본으로 계속 실행하며 그 digest를 표시한다. 다음 Job은 원본 재검사로 변경을 발견하고 재확인한다. snapshot 자체 변경 시도는 guard로 거부하거나 검사에서 실패해야 하고 새 bytes로 성공해서는 안 된다. 모든 동일 권한 공격/SDK 내부 동작을 OS sandbox로 증명했다고 하지 않는다. fake/native-boundary 시험과 실제 가중치/대형 I/O 성능 게이트를 구별한다.

TEMP 복제는 다운로드·관리 설치가 아니다. 공간이 부족하면 원본을 지우지 않고 실패한다. 정상/취소 시 ACK 후 소유 경로만 정리하고 삭제 실패는 “임시 모델 사본 정리 대기”로 남긴다. crash 뒤 잔존 TEMP는 권한 증거로 재사용하지 않는다. 광범위 경로 검색/삭제·관리 모델 삭제·사용자 원본 삭제는 하지 않는다. 고아 정리 자동화는 별도 후속이다.

## 6. 오류·자원·공유 경계

| 상황 | 제품 의미/기존 닫힌 Job 코드 |
| --- | --- |
| 준비 시 미확인/옛 확인 | 미접수, MODEL_CONFIRMATION_REQUIRED는 UI 상태. native/키 읽기/전송0 |
| 미확인 증명으로 low-level adapter 호출 | CAPABILITY_UNSUPPORTED, detail=MODEL_CONFIRMATION_REQUIRED. 생성자는 lazy 유지, native factory 전에 거부 |
| queued/복제/child에서 source·model proof 불일치 | MODEL_CHECKSUM_MISMATCH 또는 기존 DIARIZATION_MANIFEST_CHECKSUM/DIARIZATION_MODEL_CHECKSUM. 입력/무결성 실패·원본/기존 결과 보존·재확인 후 새 요청 |
| 필수 파일 없음/지원 안 되는 로더 입력 | MODEL_MISSING 또는 CAPABILITY_UNSUPPORTED. 자동 다운로드/파일 경로 fallback 없음 |
| license 거부/불명 상태 미확인 | 준비 미접수. 화자는 기존 DIARIZATION_LICENSE_REQUIRED/LICENSE_INVALID 유지 |
| 실제 OOM/종료 ACK 미확인 | 기존 RESOURCE_EXHAUSTED/INFERENCE_ACK_PENDING/DIARIZATION_ACK_PENDING. CPU 자동 전환·완료 오표시 없음 |
| snapshot 공간/권한/일반 I/O 실패 | 안전한 INPUT_INVALID/TASK_FAILED 등 해당 기존 코드와 단계 표시. 임의 SDK 오류를 일시 오류로 승격하거나 guard 없이 재시도하지 않음 |

새 UI 검증 상태를 G-P07의 무조건 prefix 오류 분류에 넣지 않는다. 기존 UNKNOWN·취소/삭제 우선순위는 보존한다. 실제 source 변경은 모델/입력 identity 변경이므로 같은 Job 계속 실행으로 자동 승인하지 않는다. license 미확인은 **수동 Whisper 책임 확인 예외**인지, **필수 manifest/license 거부**인지 구별한다.

native 직전 bundle 복제/guard와 resident model은 G-P11 owned-heavy lease 수명 안에 있다. worker의 snapshot 준비 owner도 라이브러리 사용 owner로 등록해 G-P05 삭제/유지보수 ACK 경계와 연결한다. source profile UNKNOWN을 가짜0byte로 바꾸지 않고 G-P11 정책 그대로 실행한다. known profile에 로더/복제 메모리 envelope가 맞지 않으면 profile mismatch로 처리한다. 복제 공간·RAM/native peak를 실제 측정했다고 하지 않는다.

제품 경로는 `LocalSTTProcess(..., model_evidence=...)`·화자 config의 동등 증거·FasterWhisperProvider의 bundle gate를 사용한다. optional None 생성자 호환은 lazy 객체 생성만 허용하고 native 성공 호환 우회가 아니다. tests의 model_factory도 증거 검증 후에만 호출한다. worker 인자/제어 reply 확장은 G-P11 device/index/compute_type과 `_activate_gpu` 순서를 보존한다. 공급업체 공용 DTO·보안 store·Job schema는 변경하지 않는다.

## 7. 경우의 수·독립 oracle

### 7.1 유한 대표 분모

계획은 **10 family, 1,528 의미 행**이다. 실제 pytest node 수와 구별한다. 아래 각 Ω=F이며 거부 입력을 제거하지 않는다. path/권한 경쟁·native는 synthetic bytes와 fake source/factory/clock/파일 API로 구성하고 실제 가중치·네트워크는 사용하지 않는다.

| family / ID | 입력 Ω=F | 행 | 독립 기대 |
| --- | --- | ---: | --- |
| A / G13-A-001…192 | source8 × role{Whisper,화자}2 × 확인4 × license3 | 192 | 출처/확인/license 표, 거부 native0·자동 관리 승격0 |
| B / G13-B-01…72 | Whisper optional preprocessor 유무2 × vocabulary 유무2 × 파일집합상태6 × 시점{선택,실행직전,실행중}3 | 72 | load 집합/없음 기본·독립 digest·부분 파일/경계 변경 |
| R / G13-R-001…144 | 변경시점6 × 변경종류6 × managed/manual2 × role2 | 144 | seal 전 변경 거부, seal 뒤 원본 변경은 현재 pinned 사본 불변·다음 요청 재확인 |
| P / G13-P-001…112 | path종류14 × 단계{preview,hash,copy,child읽기}4 × role2 | 112 | 비로컬은 filesystem 접근 전 거부·별칭/identity·링크 보호 |
| C / G13-C-001…144 | role2 × 확인사건{최초,동일,새digest,새root/출처}4 × 버튼{Yes,No,Esc}3 × 세대{동일,새실행,restore/import}3 × 세션유지/변경2 | 144 | 첫/변경 재확인·기본 거부·옛 callback 승인0·전송 grant 부수효과0 |
| L / G13-L-001…100 | 수명상태5 × 사건5 × 다른waiter2 × role2 | 100 | snapshot/lease/owner·ACK·공간 부족·취소, 원본/관리폴더 삭제0 |
| D / G13-D-01…48 | 화자검증상태8 × 확인{없음,현재,옛digest}3 × 단계{parent,child}2 | 48 | 기존 manifest/model/license·외부 tensor 거부 유지 |
| U / G13-U-001…180 | 표시상태5 × role2 × action{Tab,Enter,Space,Esc,poll,늦은callback}6 × 출처표시{수동,관리,사용자pinmanifest}3 | 180 | 신뢰/미확인/license·전체 digest·중복/키보드·과장 표시0 |
| K / G13-K-001…512 | 확인 key의8필드 각각 match/mismatch인2^8 × role2 | 512 | 하나라도 다르면 native용 증명 재사용 거부·record0/1 발급 분리 |
| T / G13-T-01…24 | §7.3 named24 | 24 | 타입/SDK·프로토콜·경계·복제 실패 |
| **합계** | 192+72+144+112+144+100+48+180+512+24 | **1,528** | 계획, 실행0 |

A의 source8은 managed 정상/manual/managed 변조/부분 파일/symlink/상위 reparse/UNC/network mapping이다. 확인4는 없음/현재digest/옛digest/옛실행 세대다. license3은 명시 조건확인/거부/정보미제공에 대한 책임확인이다. 마지막은 **수동 Whisper 예외만** 허용하며 managed의 필수 license metadata 부재·화자의 license text/hash 부재는 거부한다. 해당 role의 managed 정상 fixture는 외부 고정 reference가 있는 경우로 구성한다.

B의 파일집합6은 정상/필수누락/필수0bytes/경계가 바뀐 bytes/새 load metadata/README만 추가다. 필수누락/0bytes는 기존 필수3이 각각 누락되는 trace를 확인하되 추가 행으로 더하지 않는다. vocabulary가 없는 supported mapping은 자동 취득하지 않으며 fake factory는 받은 집합만 읽는다. 실제 SDK가 그 모델의 vocabulary를 필수로 요구하면 안전한 형식 실패다. README는 수동 load digest/사본에 포함하지 않는다. 관리 전체 집합의 선언 검사는 별도로 유지한다.

R의 시점6은 preview후Yes전/Yes후접수전/queued후lease전/복제중/seal후native전/native실행중이다. 변경6은 모델bytes/role별 metadata/optional 집합/license/크기같은변경/root identity다. 화자 metadata는 manifest, optional 집합의 부적합 추가는 manifest 계약 거부로 구성한다. license 변화가 terms만 바뀌어도 기존 확인을 재사용하지 않는다.

P의 path14는 로컬 fixed/removable/RAMdisk/relative/UNC/device namespace/extended namespace/network mapped/symlink/상위 junction/hardlink/ADS/case별칭/8.3별칭이다. GetDriveType와 최종 handle identity는 fake로 주고 감시 stat/open/realpath가 비로컬 경로를 한 번도 받지 않는지 확인한다. 로컬 별칭은 같은 실제 root면 같은 identity이며 다른 형제 폴더를 prefix로 허용하지 않는다.

L의 상태5는 QUEUED/SEALED/NATIVE_RUNNING/REAP_PENDING/CLOSED, 사건5는 취소/로드실패/디스크부족/사용자모델삭제요청/source교체다. 도달할 수 없는 순서의 늦은 사건도 정상 거부 행으로 구성한다. queue에는 모델 worker가 없어야 하고 REAP_PENDING에는 다른 heavy factory0·bundle 정리0이어야 한다.

L의 모델 삭제 요청은 사용 중 guard와 기존 기본 거부 확인 창까지 확인한다. 별도로 사용자가 승인한 기존 관리 모델 삭제 workflow는 회귀로 보존하며, snapshot 정리에서 사용자 원본을 지우지 않는 oracle와 구별한다. C의 “동일” 확인 행은 사용자가 확인 화면을 명시 재열람한 경우다. No/Esc는 그 화면에서 새 record/Job을 만들지 않고 기존 유효 record도 암묵 폐기하지 않는다. 정상 반복 요청의 같은 key 빠른 재사용과 poll의 무확인 동작은 A/U에서 따로 확인한다.

D의 상태8은 정상/사용자manifest hash불일치/model hash불일치/license누락·불일치/미래schema/ONNX외부tensor/잘못된role파일/license거부다. U의 표시5는 UNCONFIRMED/MANUAL_USER_CONFIRMED/MANAGED_PIN_MATCH/CHANGED_INVALID/LICENSE_UNCONFIRMED다. 존재하지 않는 출처/role 조합은 정상 승격하지 않고 오류/미지원으로 표시하는 부정 입력이다.

K의8필드는 library_instance/execution_generation/root_identity/kind/loader_contract/artifact_digest/terms_digest/source_kind다. 확인 키 검사는 artifact bytes 검사와 별개라 content가 같아도 root/역할/세대가 다르면 자동 재사용하지 않는다. 이 key 전수를 전체 시스템 MC/DC·공급망 인증으로 부르지 않는다.

### 7.2 독립 oracle·race·상태열

synthetic 파일은 짧은 고정 문자열이며 실제 모델 포맷/weights가 아니다. 기대 파일 목록·license 상태·native 허용/거부 표는 손으로 고정한다. SHA256 primitive는 표준 hashlib를 쓸 수 있으나 제품의 inventory/canonical/hash helper를 expected에 import하지 않는다. canonical JSON fixture의 정확한 bytes와 사전 계산 digest, 서로 다른 파일 경계의 동일 연결 bytes 예제로 단순 연결 결함을 잡는다. fake factory는 **실제로 받은 mapping/snapshot bytes**를 읽어 기대값과 비교하고 원 source 경로 접근/Hub/native 전 승인 우회를 감시한다.

native 허용 oracle는 “사용자가 확인한 digest의 로컬 고정 bytes만 읽음”이다. 출처 진위·품질·license 법률 적합성이 검증됐다는 oracle가 아니다. UI/confirmation 읽기와 No/Esc에는 승인record/다운로드/native/전송/비용예약0이다. 같은 현재 key의 명시 재사용만 가능하고 bytes나 terms 변경은 새 고지를 요구한다. managed 변조를 manual로 자동 재분류하면 실패다.

R/L에서 preview→확인, 원 source검사→copy, copy→seal, seal→native, close→ACK→cleanup의 내부 순서를 고정하고 source mutation/cancel을 각 경계 양쪽에 barrier로 넣는다. 이벤트 DAG는 `확인 < lease < copy < seal < native < ACK < 정리`이며 queued 취소는 copy/native를 만들지 않는 분기다. source 변조와 snapshot 변조를 서로 다른 target으로 주입한다. seal 뒤 source만 바뀌는 경우 fake native가 옛 bytes를 읽는지와 다음 Job 차단을 둘 다 확인한다. sleep 우연성으로 양순서를 주장하지 않는다.

행별 trace 반복 수·실제 Qt node·API fault 수는 의미 행 수에 더하지 않는다. 상태 모델은 위5상태와5사건의 합법/거부 전이·중복 close/cancel을 검사하며 더 긴 임의 이력/외부 앱 경쟁·실제 SDK 파일 I/O는 별도 한계다. fake I/O에서는 readonly bit만으로 쓰기를 허용하는 mutant와 실제 공유 guard 차이를 대조한다. 실제 Windows의 synthetic 파일 share/delete guard 통합은 구현 시 승인 범위의 OS TEMP에서만 수행하며 실제 모델을 열지 않는다.

### 7.3 명명 부정24행

T01 SHA bool/비문자열 / T02 잘못된 길이·대문자 digest / T03 size=True/음수 / T04 파일명 case 충돌 / T05 파일 bytes 경계만 바뀌어 연결 hash 동일 / T06 optional preprocessor 등장 / T07 tokenizer 누락 시 Hub fallback 감시 / T08 GetDriveType 불명 / T09 비로컬 realpath 감시 / T10 모델 경로 형제 prefix / T11 같은 installed.json·weights 동시변경과 외부pin 불일치 / T12 reference 없는 관리 설치를 자기승인 금지 / T13 library/실행 세대 증명 치환 / T14 role 증명 교차 / T15 terms 변경만으로 재확인 / T16 같은크기·같은mtime 파일 변경 / T17 파일 open중 identity 치환 / T18 copy short write / T19 snapshot ENOSPC / T20 file mapping 미지원 SDK의 path 재시도 금지 / T21 snapshot seal후 변조·이름치환 / T22 native reply digest 치환 / T23 child ACK 누락 때 guard 유지 / T24 legacy None evidence의 lazy 생성 허용·native0.

family별 tuple/고유 ID 집합과 실제 assertion ID를 별도 대조해 missing/duplicate/extra=0을 감사한다. 거부 source·미상 license·SDK 지원 불가를 시험 분모에서 빼지 않는다. 실제 trained weights·추론 품질·공식 provenance가 없는 synthetic PASS를 S04 전체 통과로 집계하지 않는다.

## 8. 기존 시험과 신규 계층

| 기존 실제 node/범위 | 관계 |
| --- | --- |
| `tests/unit/test_models.py::test_no_install_without_explicit_approval`, `::test_verified_install_corruption_and_delete`, `::test_download_faults_never_activate` | 기존 관리 설치·취소/변조/다운로드 경계 유지. 이것만으로 실행 source pin/수동 확인을 검증했다고 하지 않음 |
| `tests/unit/test_providers.py::test_local_missing_files_dependency_and_cancel_never_download`, `::test_local_model_is_lazy_local_files_only_and_keeps_partial_results` | local_files_only/lazy·partial 유지. 승인 fake bundle 뒤 factory가 files mapping을 받도록 명시 적응 |
| `tests/integration/test_provider_security_independent.py::test_missing_tokenizer_is_denied_before_optional_model_import` | 필수 tokenizer와 import 전 거부 유지. source folder→native 재개방을 새 R/P/T로 보강 |
| `tests/unit/test_inference.py::test_missing_model_is_safe_child_failure_and_child_is_reusable` | missing 구조 오류와 lazy 생성 유지. 증명 없음을 성공 호환 경로로 만들지 않음 |
| `tests/contract/test_diarization_contract.py::test_manifest_failure_before_native_loader`, `::test_onnx_nested_external_tensor_is_denied` | 기존 manifest/license/ONNX 검사를 완화하지 않음. 새 evidence/bundle gate 보강 |
| 같은 파일 `test_model_change_between_snapshot_and_child_is_denied` | 현재는 audio hash 불일치 시험임을 유지하며 모델 file race의 새 증거로 세지 않음 |
| G-P11/L-P07/L-P08 관련 시험 | 자원/lease/ACK/device·GPU runtime import/설치 세대 보호 회귀. 이번에 실제 GPU 모델을 재실행하지 않음 |

신규4파일은 `tests/unit/test_manual_models.py`(A/B/K/T의 순수 정책·digest), `tests/property/test_manual_model_case_space.py`(독립 분모/ID·상태/불변·같은bytes 재해시), `tests/integration/test_model_bundle.py`(R/P/L/D·실제 TEMP 파일/guard와 fake native), `tests/ui/test_manual_model_ui.py`(C/U·고지/키보드/세대/늦은callback)다. 겹치는 계층 assertion은 같은 case ID로 연결하고 의미 행 수에 중복 합산하지 않는다.

네이티브 importer·다운로더·socket·vault는 spy/실패 fake로 주입한다. 파일/license fixtures는 의미 없는 synthetic bytes 또는 작은 가짜 manifest며 실제 가중치/계정/ONNX 모델 실행은 없다. 새4파일 합계가60초를 넘으면 축약 전에 측정값·느린 family/node·최적화/축약안을 C00에게 보고한다. 파일별 spawn/Qt 생성 비용을 batching하되 실제 guard/키 입력/ACK 경계는 handler 호출만으로 대체하지 않는다.

## 9. mutation 계획

계획 **24개, 실행0**이다. 정상본 PASS 뒤 pyproject/src/tests/scripts/packaging을 함께 복사한 OS TEMP 사본에서 한 번에 하나씩 변이한다. import origin·원본/변이 hash·목표 node를 기록한다. assertion FAIL만 검출이며 수집/import/권한/timeout은 invalid다.

| ID | 결함 | 독립 검출 목표 |
| --- | --- | --- |
| M01 | 파일 이름/size 경계 없이 bytes만 이어 hash | B/T05의 독립 digest |
| M02 | preprocessor/vocabulary 또는 optional 없음 표식 누락 | B/R/T06 입력 집합 |
| M03 | 실행 직전 source 재검사 제거 | R의 queued 변조 native0 |
| M04 | 첫 사용 확인 없이 evidence 발급 | A/C의 UNCONFIRMED native0 |
| M05 | old digest 확인을 새 digest에 재사용 | A/K·변경 고지 |
| M06 | 실행 generation 검사 제거 | C/K 재시작/restore 미승계 |
| M07 | files mapping 대신 original path fallback | R/T20 원본 재개방0 |
| M08 | copy 뒤 digest/집합 대조 제거 | R/T18의 복제 중 변조 |
| M09 | child/native reply digest 대조 제거 | T22 바인딩 |
| M10 | snapshot share/identity guard 조기 해제 | L/T21 snapshot 변경 차단 |
| M11 | child ACK 전에 snapshot 정리 | L/T23 held lease/파일 유지 |
| M12 | seal 뒤 source 변경을 현재 native에 반영 | R 현재 pinned bytes 불변 |
| M13 | 다음 Job의 source 재검사 생략 | R 변경후 새 요청 재확인 |
| M14 | 옛 root/세션 callback으로 현재 승인 | C/K 세대·현재target |
| M15 | No/Esc를 Yes 처리 | C/U record·native0 |
| M16 | 수동 자체 hash를 공식 검증으로 표시 | U의 source_authenticity=UNVERIFIED |
| M17 | license 책임 확인 자동 체크 | A/C 기본 미선택 |
| M18 | 관리 변조를 자동 manual 성공으로 낮춤 | A/U 명시 수동 채택 필요 |
| M19 | hardlink/reparse 보호 제거 | P 경로 거부 |
| M20 | 로컬 판정 전에 realpath/stat | P/T09 비로컬 접근0 |
| M21 | installed.json을 유일 expected reference로 사용 | T11/T12 외부pin 대조 |
| M22 | 화자 manifest 고정 hash 생략 | D 부모/child 실패 |
| M23 | 화자 license hash 검사 생략 | D 기존 license 검증. 외부 tensor 거부는 D와 기존 독립 계약 시험으로 회귀 |
| M24 | snapshot 실패 후 native path로 계속 | L/T18/T19 실패시 factory0 |

## 10. 정확한 후속 쓰기 범위·대안·수락

제안은 **25파일 = source12 + 신규 시험4 + 기존 fixture 적응8 + 이 문서1**이다. 지금 허용은 이 문서 하나다. native proof/mapping이 필수가 되므로 기존 fake factory/manifest의 명시 승인 fixture를 함께 적응한다. 목록 밖 수정이 실제 필요하면 실패·원인·최소 파일과 함께 먼저 요청한다. 내부 작업 순서는 정책/DTO·digest → 확인 UI → snapshot/native → 기존 회귀·mutation·독립 검토다. push 분할이 필요하면 C00가 파일/검토 경계를 별도로 확정한다.

| 구분 | 정확한 파일 |
| --- | --- |
| 신규 models2 | `src/recoryn/models/artifacts.py`, `src/recoryn/models/_artifact_io.py` |
| models 기존2 | `src/recoryn/models/manager.py`, `src/recoryn/models/__init__.py` |
| UI2 | `src/recoryn/ui/models.py`, `src/recoryn/ui/ai_bridge.py` |
| STT2 | `src/recoryn/app/inference.py`, `src/recoryn/transcription/adapters.py` |
| 화자4 | `src/recoryn/diarization/contracts.py`, `src/recoryn/diarization/models.py`, `src/recoryn/diarization/backend.py`, `src/recoryn/diarization/process.py` |
| 신규 시험4 | `tests/unit/test_manual_models.py`, `tests/property/test_manual_model_case_space.py`, `tests/integration/test_model_bundle.py`, `tests/ui/test_manual_model_ui.py` |
| 기존 fixture8 | `tests/unit/test_providers.py`, `tests/unit/test_inference.py`, `tests/unit/test_diarization.py`, `tests/contract/test_diarization_contract.py`, `tests/integration/test_provider_security_independent.py`, `tests/ui/test_live_ui.py`, `tests/ui/test_gpu_runtime_ui.py`, `tests/ui/test_models_ui.py` |
| 문서1 | `docs/testing/g13-manual-model-cases.md` |

ui/main.py·app/ai.py·content·storage·security·jobs·GPU runtime 본체·공용 설정·실제 license 결과·배정표·설계 정본은 범위 밖이다. G-P09에는 영속 신뢰 표가 없고 실행 세대 확인이 복원되지 않는다는 인계만 필요하다. G-P11의 resource_catalog 실제 profile 추가도 별도 단위이며 이 작업으로 측정값을 만들지 않는다.

| 대안 | 장점 | 한계/제안 |
| --- | --- | --- |
| 수동 디렉터리 전부 금지 | 단순 공급망 정책 | B13/ADR17 결정과 핵심 기능에 어긋남. 채택하지 않음 |
| 자체 hash만 표시하고 바로 load | 변경 작음 | 확인/출처 구분·로드 TOCTOU가 없음. 이번 gap을 닫지 못함 |
| source를 hash한 뒤 같은 path로 native 재열기 | 복제 공간 절약 | native 입력이 다른 bytes일 수 있음. 고정 bundle/mapping 권고 |
| model.bin 전체를 Python bytes로 유지 | 경로 경쟁 단순화 | 대형 모델 RAM peak 증가. stream copy+guarded file-like 권고, 실제 SDK peak는 외부 게이트 |
| 영구 trust DB/자동 재승인 | 재시작 UX 편리 | 복원·이전 승인·정책 version/migration 복잡. 현재 실행 메모리 key 권고 |
| 수동도 실제 출처/license 인증 전 차단 | 일관된 엄격 정책 | 실모델 외부 게이트 때문에 모든 수동 실행이 막힘. Whisper 예외+책임 고지, 화자는 기존 strict 유지 권고 |

후속 수락은 정상본 PASS, 1,528 case ID missing/duplicate/extra=0·skip0, mutation24 검출/invalid 구분, 새4시험 합계60초 게이트, ruff check/format check·`python -m mypy src/recoryn scripts packaging`이다. 시험은 offscreen·bytecode 비활성·`-p no:cacheprovider`·OS TEMP 고유 basetemp다. 기존 models/provider/inference/화자 계약·G-P11과 GPU runtime·G-P02/P06/P07·tests/ui 전체·관련 AI workflow를 회귀하고 가능하면 선행 HEAD+승인파일 사본에서 전체 오프라인 회귀를 한 번 한다.

실제 weights 로드/files API 호환·Whisper 품질·GPU/대형 메모리·디스크 복제 성능·공식 출처/가중치 license·서명 검증은 **NOT_RUN/외부 게이트**다. 설치된 SDK 소스/타입과 fake native 경계 PASS는 그 실측을 대체하지 않는다. 확인한 digest와 다른 bytes native0·원본 삭제0·무승인 다운로드/전송0·관리오류 자동수동승격0·ACK 전 guard해제0을 별도 확인한다.

C00 승인 요청은 (a) trust/무인증 표시·현재 실행 key, (b) 수동 Whisper의 license 미확인 책임 확인 예외와 화자 strict 유지, (c) S04/ADR17/B13 정본 문구안, (d) 실제 load 입력 closure·실행 직전 재검사·guarded bundle/files mapping·ACK 수명, (e) 25파일·1,528행·mutation24·60초/회귀/외부 실모델 게이트다. 제품 변경·제품 시험·mutation은 현재0이며 승인과 별도 시작 신호를 기다린다.


## §개정 요청(90c6123·G-P07 계약·G-P11 개정 반영)

### 1. 대조 범위·승인 이력·근거 구분

2026-11-24 C00의 계약 재대조 배정이다. 앞의 승인 원문 **40,538 bytes, LF SHA-256 `56dc2fefa06329df440552a8a948aa8a625b7f5786a9a75c1fbd8f3ab4aa0007`**은 바이트 단위로 보존했다. 원문의 “승인 대기/개정 제안”은 당시 이력이며 C00가 (a)~(e)를 승인한 사실을 이 절에서 보완한다. 아래 추가 계약·분모 변화는 다시 결정받는 요청이고 제품 구현·시험·mutation 실행 결과가 아니다.

- 코드 기준: **`90c612378e0cdb991319098124f9139fac4817fd`**, `git show 90c6123:<path>`로 확인했다. 작업 트리 G-P15b·검토 중 G-P07을 커밋된 코드 근거로 섞지 않았다.
- G-P07 계약: `docs/testing/g07-blocked-reason-cases.md`, 읽은 판 LF SHA-256 `7eade9b39575cf42cf1d214a299a7f72258e617416c2340d3095082f51c09c4a`. 110코드·UNKNOWN 우선·명시 계속·새 snapshot·삭제 권위·execution_policy 행동을 대조했다. 독립 검토 tree 898fcc53의 검토 결과를 미리 합격 처리하지 않는다.
- G-P11 계약·승인된 개정: `docs/testing/g11-resource-policy-cases.md`, LF SHA-256 `410fc260c56d099453cadd799ae4b75e4545b4a90095b029fdbd39568e5e2fcc`. 원격 적용 제외·Ollama strict 차단·UNKNOWN 요구량 실행 허용·P11a 206/P11b 32,593행·명시 계속 새 snapshot을 포함한다.
- G-P12 개정: `docs/testing/g12-basis-a11y-cases.md`, LF SHA-256 `b1db19300523c5e4de745159ff918417cacf8859a9351267e9b6ff57402d618d`. 배정표 G12 행의 C00 결정은 비용 확인 창 2개를 포함한 2,506행·mutation28·장치 control 소유 정정·직렬 순서다. model 책임 확인을 claim basis로 삼거나 새 계속/취소 API를 만드는 변경은 없다.

| 직접 확인한 기준 file:line | 사실과 계약 영향 |
| --- | --- |
| `90c6123:docs/validation-plan.md:113`, `90c6123:docs/architecture-v1.md:288` | S04·ADR17에는 수동 Whisper 책임 확인 예외·고정 실행 bytes·직전 재검사·화자 strict 유지와 “구현 G-P13”이 이미 반영됐다. 원문 §3.2의 정본 개정 요청은 GD-P02에서 닫혔으며 G13이 정본을 다시 쓰지 않는다 |
| `90c6123:docs/implementation/product-contracts.md:99`, `90c6123:docs/implementation/provider-matrix.md:20` | B13/provider 계약에도 관리 설치와 사용자 지정 예외가 구분돼 있다. 설계 문구 반영과 제품 검증 완료를 구별한다 |
| `90c6123:src/recoryn/ui/ai_bridge.py:194`, `:222`, `:226` | 세 파일 연결 hash, 모델 digest+실제 device의 결과 키와 runtime 세대가 붙는 process key가 여전히 있다. 모델 입력 closure·명시 확인·guarded bundle은 아직 구현되지 않았다 |
| `90c6123:src/recoryn/transcription/adapters.py:120`, `:139` | 필수 파일 확인 뒤 원 디렉터리를 factory에 넘긴다. local_files_only만으로 G13 고정 bytes 경계가 충족됐다고 판정하지 않는다 |
| `90c6123:src/recoryn/models/manager.py:281` | verify는 installed.json에서 spec을 읽는다. 원문 외부 pin/사용자 확인 기준을 추가할 이유가 그대로다 |
| `90c6123:src/recoryn/app/inference.py:65`, `:95`, `:128` | GPU 활성화→adapter import 순서와 lazy child 생성 경계가 있다. G11 device_index/compute_type 확장 위에 evidence/bundle을 연결하며 원 디렉터리 로드로 되돌리지 않는다 |
| `90c6123:src/recoryn/diarization/contracts.py:43`, `:60`; `90c6123:src/recoryn/diarization/models.py:30`, `:87`, `:92` | 화자는 CPU-only config, manifest/model/license 검증과 서로 다른 오류를 사용한다. G11 GPU 미지원과 G13 strict 검증을 둘 다 유지한다 |
| `90c6123:src/recoryn/diarization/backend.py:95`, `:102` | 검증한 모델 bytes의 TEMP 사본을 native에 제공한다. 원문 guard/ACK 보강은 유지하되 이미 있는 사본 경계를 새로 발명한 기능처럼 쓰지 않는다 |
| `90c6123:src/recoryn/ui/ai_bridge.py:398`, `:408`, `:416` | 화자는 이미 fenced Job/runner를 쓰며 별도 process를 닫는다. G-P07의 같은 계획 계속 UI 대상은 STT/요약이고 화자는 표시·탐색만이다. G13이 화자의 새 계속 UI/API를 범위에 추가하지 않는다 |
| `90c6123:src/recoryn/storage/library.py:451`, `:459` | 다중 owner의 약한 참조 등록과 lock을 잡지 않는 is_live 관찰 계약이 있다. bundle 준비/child owner의 강한 참조를 실제 ACK까지 유지해야 한다 |
| `90c6123:src/recoryn/app/ai.py:95` | 기준 코드의 _admit에는 BLOCKED 암묵 resume가 남아 있다. G-P07이 이를 없애는 것이 선행 조건이며 G13은 옛 동작을 복원하지 않는다 |

### 2. 확인 key·모델/결과 key·자원 snapshot의 경계 요청

C00 승인 (a)의 **현재 실행 key에 trust·digest 포함**을 유지하되, 어느 key인지 분명히 하도록 요청한다.

1. **확인/실행 증거 key**에는 원문 §4.2의 8필드, source_kind/trust·artifact_digest·terms_digest를 그대로 포함한다. source/terms/root/실행 세대가 바뀌면 새 확인·새 evidence가 필요하다. 같아 보이는 bytes만으로 확인을 생략하지 않는다. worker/process 재사용도 다른 증거·bundle guard를 섞지 않는다.
2. **결과 config_key**는 실제 loader에 제공할 artifact digest·loader/output 의미 계약과 기존의 실제 device 구분을 따른다. 모델 bytes/optional 입력·loader 의미가 달라지면 새 의미 키다. trust 표시·책임 확인/terms·root 경로·실행 세대·정책 enum·profile 관측·priority만 변한 경우를 결과 변경으로 취급하지 않는다. 이 값들은 실행 evidence/ResourceRequest snapshot에 남긴다. 이는 G-P02/G-P06의 정책 값 변경으로 실시간 청크를 재전송하지 않도록 한 결정과 같은 이유다. 고지 변경 뒤 새 확인을 요구하는 것과 이미 처리한 같은 bytes 청크를 다시 보내는 것은 별개다.
3. **실제 device/정밀도/runtime identity**는 G-P11의 계획·호환 규칙을 유지한다. G13이 `digest:device`에서 device를 빼거나 장치 간 의미 호환을 새로 인증하지 않는다. STT의 실제 device가 바뀌어 기존 키와 다르면 명시 계속은 CONTINUE_PLAN_CHANGED이고 새 Job 선택을 요구한다. CPU_ONLY→fallback처럼 같은 실제 device·같은 의미 키를 유지한다면 G-P07 계속에서 현재 정책·현재 model evidence를 새 snapshot으로 받을 수 있다. QUEUED/RUNNING의 evidence/ResourceRequest를 현재 UI 값으로 덮어쓰지 않는다.
4. 모델 pin/책임 확인은 grant/permit/비용·key 재연결도, G-P12의 supported/user_assertion claim basis도 아니다. provider_basis 보존 경로를 모델 신뢰 확인 저장소로 재사용하지 않는다. content schema/게시 CAS는 범위 밖으로 유지한다.

권고는 위 분리다. 대안인 trust/terms/실행 세대까지 결과 키에 넣기는 단순하지만 같은 bytes의 재전사·중복 원격 전송/비용·checkpoint 단절 위험이 있다. 원문 “현재 실행 key”를 결과 config_key로 해석하려면 그 동작 변경과 분모를 C00가 별도로 결정해야 한다. 지금 제품 키를 바꾸지 않았다.

### 3. G-P07 오류·미접수·계속 계약 보강

원문 §6의 설명을 다음 정확한 표로 보완한다. 아래는 **G-P07 승인된 폐쇄 표의 기대값**이며 90c6123의 기존 FAILED 동작을 재확인한 시험 결과가 아니다.

| 상황/typed code | 준비 중 | Job attempt에서 outcome_known=True | outcome_known=False |
| --- | --- | --- | --- |
| MODEL_CONFIRMATION_REQUIRED | UI 상태·Job 미접수·native0 | adapter 우회 호출은 기존 CAPABILITY_UNSUPPORTED로 거부, BLOCKED(CAPABILITY) | 실제 미확인 실행 결과가 있으면 REMOTE_UNKNOWN 우선 |
| MODEL_MISSING / LOCAL_MODEL_REQUIRED | 준비 차단·미접수 | BLOCKED(RESOURCE), 원본·이전 결과 유지 | BLOCKED(REMOTE_UNKNOWN) |
| MODEL_CHECKSUM_MISMATCH / DIARIZATION_MODEL_CHECKSUM | 재확인·미접수 | FAILED, blocked_reason 없음. 자동 BACKOFF/새 bytes 채택0 | BLOCKED(REMOTE_UNKNOWN) |
| DIARIZATION_LICENSE_REQUIRED | strict 거부·미접수 | BLOCKED(CAPABILITY) | BLOCKED(REMOTE_UNKNOWN) |
| DIARIZATION_MANIFEST_CHECKSUM / DIARIZATION_LICENSE_INVALID | strict 거부·미접수 | 현재 폐쇄 표에서 미등록이므로 TASK_FAILED/FAILED. adapter 원래 기술 검증을 생략하지 않음 | BLOCKED(REMOTE_UNKNOWN) |
| RESOURCE_EXHAUSTED | 준비 전에 알면 미접수 | BLOCKED(RESOURCE), CPU 자동 전환0 | BLOCKED(REMOTE_UNKNOWN) |
| INFERENCE_ACK_PENDING / DIARIZATION_ACK_PENDING | 종료 확인 필요 | BLOCKED(RESOURCE), 실제 owner/lease/guard 유지 | BLOCKED(REMOTE_UNKNOWN), 실제 ACK 필요는 그대로 |

위 표에서 미등록 코드를 prefix로 CAPABILITY/RESOURCE로 승격하지 않는다. G13은 jobs/failures.py를 수정하거나 110→112→122라는 선행 단위의 catalog 분모를 다시 쓰지 않는다. 필요하면 향후 별도 코드 등록 단위로 결정한다. 표의 두 미등록 manifest/license 코드를 사용자 확인 예외로 통과시키는 뜻도 아니다.

G-P07의 같은 계획 계속은 expected_job_id/version·동일 input/config·reader ACK를 모두 요구한다. checksum/실제 입력 변경에 “계속”을 자동 제공하지 않는다. 일반 재요청으로 BLOCKED를 재개하거나 새 nonce를 발급하지 않는다. G-P07 삭제 권위 guard는 입장·재개를 보호하고, G13의 모델 파일 검증을 대체하지 않는다. 폐쇄 코드·outcome_known은 trusted typed 경로로 전달하며 미확인을 참으로 승격하지 않는다. 임의 경로/SDK 문장을 code/safe_message로 복사하지 않는다.

### 4. G-P11 model identity·profile·lease 연결 보강

- G-P11a 필수 ResourceRequest/backend 정책 입장 검사를 먼저 사용한다. 화자의 GPU_ONLY 미지원은 모델 확인 dialog·복제·native를 시작하기 전에 거부한다. 사용자 확인이 GPU 미지원·서버 정책 차단을 면제하지 않는다. REMOTE/Ollama를 사용자 지정 모델 bundle 경로로 재분류하지 않는다.
- 새로운 **artifact/loader digest를 ResourceRequest.model_identity와 같은 snapshot에서 고정**한다. 직접 적용한 known profile이 옛 digest/runtime/envelope를 가리키면 RESOURCE_PROFILE_MISMATCH다. profile을 버리고 UNKNOWN으로 낮춰 통과시키지 않는다. production profile가 비어 있으면 원문대로 RESOURCE_ESTIMATE_UNKNOWN 표시와 G11 조건부 실행이며, 메모리0/legacy 1GiB 추정·RESOURCE_ESTIMATE_REQUIRED 차단으로 되돌리지 않는다.
- 순서: 모델 preview/명시 확인(모델 bytes를 실행하지 않음) → Job/runner 입장 → 공통 owned-heavy lease → source 재검사·bundle 복제/guard → child의 GPU 활성화/실제 loader → 추론 → 실제 child 종료 ACK → guard/owner/lease 정리다. preview는 별도 취소 가능한 모델 lane에서 하고, heavy worker와 bundle 준비는 lease 전 생성하지 않는다. 긴 hash/복제·path 열거를 GUI·녹음 제어 lane·Library root mutex·JobStore transaction 안에 넣지 않는다.
- strong parent owner는 준비부터 REAP_PENDING까지 살아 있고 `register_live_owner`에는 추가 등록한다. is_live는 별도 lock을 기다리지 않는 안전 관찰이다. native 반환·Python task 반환·논리 Job terminal만으로 실제 child 종료를 추정하지 않는다. 삭제 시 새 입력/게시가 막혀도 종료 ACK·owned cleanup은 계속 가능해야 한다. 고아 프로세스 자동 종료 증명을 이 단위의 성과로 확대하지 않는다.
- profile에 실제 측정이 없으므로 guarded copy의 peak RAM·디스크 공간을 실측 상한으로 꾸미지 않는다. 기존 known profile에 새 loader/buffer envelope가 적용 불가하면 mismatch이며, 첫 실제 profile/실모델 files mapping·lazy read 수명은 외부 게이트다. G-P11b가 warm cache를 없애면 G13이 bridge의 옛 LocalSTTProcess 재사용을 되살리지 않는다. live 한 Job 안에서만 같은 guard/evidence로 재사용한다.

### 5. 분모·독립 oracle·mutation 개정 요청

원문 10가족 **1,528행**을 직접 재계산해 일치함을 확인했다. 기존 A/B/R/P/C/L/D/U/K 9가족은 유지하고 T를 확장하며 두 통합 가족을 추가하는 **12가족 1,660행**을 요청한다. 실제 실행 node/PASS 수가 아니다.

| 가족 | 기존 | 개정 산식/내용 | 개정 | 차이 |
| --- | ---: | --- | ---: | ---: |
| 기존 A/B/R/P/C/L/D/U/K | 1,504 | 입력 분할 유지. license/ACK·profile UNKNOWN의 기대만 위 정합 표로 구체화 | 1,504 | 0 |
| T / G13-T-01…28 | 24 | 원문24 + 아래 T25~28 | 28 | +4 |
| I / G13-I-01…64 | 0 | key 구성요소8 × role2 × 단계{준비,QUEUED}2 × 값{동일,변경}2 | 64 | +64 |
| J / G13-J-01…64 | 0 | 명명 오류8 × role2 × 경로{runner,직접 JobStore.fail}2 × outcome_known2 | 64 | +64 |
| **합계** | **1,528** | 1,504+28+64+64 | **1,660** | **+132** |

I의 8요소는 artifact_digest/loader_contract/source_kind/terms_digest/root_identity/execution_generation/device_policy/actual_device다. I는 원문 K의 승인 key 유효성 전수와 별개로 **결과 키·실행 증거·큐의 불변 snapshot을 서로 비교**한다. same row는 부수효과0, changed row는 손작성 표로 key 변화·증거 재확인·queued 실행 자격을 따로 판정한다. source_kind/terms/root/세대만 달라도 evidence 재사용은 금지하지만 동일 bytes/loader의 결과 키는 유지한다. queued는 접수 시 고정한 증거를 유지하며 원 source가 달라지면 직전 재검사에서 차단한다. 실제 device 변경이 허용되지 않는 화자/GPU 조합도 구성 가능한 부정 입력이므로 분모에서 빼지 않는다.

J의 오류8은 CAPABILITY_UNSUPPORTED/MODEL_MISSING/MODEL_CHECKSUM_MISMATCH/DIARIZATION_MODEL_CHECKSUM/DIARIZATION_LICENSE_REQUIRED/DIARIZATION_LICENSE_INVALID/RESOURCE_EXHAUSTED/role별 ACK_PENDING이다. 마지막은 Whisper의 INFERENCE_ACK_PENDING, 화자의 DIARIZATION_ACK_PENDING이다. 모든 행의 retryable=True로 두어 checksum/미등록 오류가 일시 오류가 되지 않는 것도 확인한다. role에 맞지 않는 코드를 fake native가 내는 행도 안전 분류 입력으로 포함하며 실제 backend가 그 오류를 반드시 낸다는 주장은 아니다. 실제 결과 불명(false)이면 모두 REMOTE_UNKNOWN이며 reader inactive를 위조하지 않는다. G-P07 순수 결정 함수를 expected에 import하지 않고 Job/Attempt/reader·선택 결과·원본 bytes·정확한 code를 공개 경로로 관찰한다.

- **T25:** G13 artifact/loader digest가 바뀐 요청에 명시 known profile을 그대로 적용 → RESOURCE_PROFILE_MISMATCH, UNKNOWN 강등·native0. fake profile이며 실측 profile 추가가 아니다.
- **T26:** profile가 없음 → 요구량 None/RESOURCE_ESTIMATE_UNKNOWN 유지, 유효한 CPU 강제 조건에서는 실행 허용, legacy choose 호출0. GPU는 별도 G11 runtime/관측/identity 조건을 갖춘 fake만 사용한다.
- **T27:** 동일 bytes/실제 device에서 terms·source 책임 확인만 갱신한 뒤 새 evidence로 STT/요약 관련 기존 계획을 대조한다. 처리한 실시간 청크 재전송0·기존 checkpoint 유지·새 확인은 필요. 수동 모델이 없는 원격/요약 경로의 config_key를 G13이 바꾸지 않음도 확인한다.
- **T28:** STT의 실제 device 변경 뒤 명시 계속 → CONTINUE_PLAN_CHANGED, 새 Job/attempt 암묵 생성0. 화자에 없는 계속 UI를 새로 만들지 않는다. QUEUED의 기존 snapshot은 현재 UI 변경과 독립한다.

기존 독립 digest/file mapping oracle와 R/L의 barrier·실제 TEMP 공유 guard는 그대로다. I/J는 public bridge/adapter 또는 공개 runner/JobStore 경로를 지나며 제품의 key 생성·failure 분류 표를 expected에 복사하지 않는다. 1,660 ID 누락·중복·extra=0, 보강은 별도 G13-X- 접두사, 실제 assertion/수집 node 수를 분리한다. 네 신규 시험 파일·합계60초 게이트를 유지하고 초과 시 축약 전 실측·안을 보고한다.

mutation은 기존24개를 유지하고 아래5개를 추가한 **29개**를 요청한다. 각 변이는 G13이 수정하는 경계의 source 사본에 적용한다. 선행 jobs/resource 코드 자체의 변이는 해당 단위의 회귀 결과와 구별한다.

| ID | 추가 결함 | 독립 검출 목표 |
| --- | --- | --- |
| M25 | terms/승인 세대·정책을 결과 config_key에 추가 | I/T27 청크 재전송0·checkpoint/결과 키 불변 |
| M26 | queued 모델 evidence를 현재 UI/현재 확인으로 교체 | I/R queued snapshot·변경 source native0 |
| M27 | G13 request 조립에서 불일치 known profile를 None으로 버림 | T25 정확한 RESOURCE_PROFILE_MISMATCH·native0 |
| M28 | G13 UNKNOWN 요구량을 legacy choose/0byte·차단 코드로 변환 | T26 실행 허용·None/표시 유지 |
| M29 | G13 오류 wrapper에서 outcome_known=False를 True로 승격 | J의 REMOTE_UNKNOWN·Attempt UNKNOWN·ACK 보존 |

### 6. 쓰기 범위·순서·C00 결정 요청

**승인 25파일은 유지**한다. 새 I/J/T는 원문 신규4시험에 추가하고 선행 JobStore/failures/ResourceRequest를 공개 API로 호출한다. 원문의8개 기존 fixture는 선행 G-P11의 필수 DTO/새 worker 종료 규칙과 새 G13 evidence를 모두 갖추도록 적응한다. 다른 G11/G07 시험 파일의 fixture 실패가 실제로 나오면 파일·실패·최소 적응을 먼저 요청한다. 메모리 profile 항목·정본 문서·security/content/Job schema는 추가하지 않는다.

권고 순서는 **G-P15 → G-P07 → G-P11a → G-P11b → G-P12 → G-P13**이다. G-P02/P06은 이미 push됐으며 model evidence와 독립된 fresh binding을 유지한다. G-P11a/b가 app/inference·transcription/adapters·ui/ai_bridge·ui/models·diarization/process를 바꾼 뒤 그 파일을 인계받는다. G-P12가 app/bridge·접근성·후보 선택을 먼저 바꿔도 G13은 후보 CAS/키보드·알림 세대를 보존한다. 새 G-P16은 main/bridge의 장치 정책 저장을 제안한 단계이며 승인·구현을 가정하지 않는다. G16이 먼저 push되면 현재 실행 정책의 공개 snapshot을 사용하고 모델 확인을 일반 설정 파일에 영구 저장하지 않는다. bridge 동시 쓰기는 C00가 순서를 정한다.

C00 결정 요청: **①확인/실행 key의 trust·digest는 유지하되 metadata-only 변경은 결과 config_key에서 분리, ②G-P07 정확한 오류 표·미접수/명시 계속 경계, ③G-P11 model_identity/profile·lease/ACK 접속, ④분모1,660·mutation29·25파일/60초 유지, ⑤직렬 착수 순서와 GD-P02 정본 반영 완료 사실 확인**이다. 아직 구현 착수 신호가 없으며 제품·시험·mutation은 이 배정에서 실행하지 않았다.

## §구현 결과 (G-P13, 기준 `47530a2`)

상태: **구현 완료 — G13 IMPLEMENTATION_READY, 독립 검토·C00 통합 대기**. 구현 Claude(C00 배정 G-P13). 위의 승인 원문과 §개정 요청은 바이트 단위로 그대로 두고 이 절만 추가했다. 실제 weights 로드·files API 실호환·Whisper 품질·GPU/대형 메모리·디스크 복제 성능·공식 출처/라이선스·서명 검증은 계속 NOT_RUN/외부 게이트다.

### 1. C00 결정과 범위

- 계약 승인 (a)~(e)와 §개정 ①~⑤를 반영했다. 착수 보고에서 배정 문구의 `storage/_safe.py`는 C00가 "계약 §10의 25파일이 정본"으로 정정했다. `_safe.py`는 수정하지 않았고 `check_path`·`open_file`은 읽기 전용으로 재사용한다. 비로컬 판정·Windows 공유 거부 guard·디렉터리 handle guard는 신규 `models/_artifact_io.py`에 두었다.
- **canonical digest 1회 변경(C00 승인)**: 로컬 STT 결과 키는 계속 `artifact_digest:device`다. 다만 digest가 세 파일 연결 hash에서 canonical artifact digest로 바뀌어, 업그레이드하면 같은 모델의 결과 config_key가 한 번 바뀐다. 근거는 원문 §4.1의 "단순 bytes 연결 폐기"다(경계·이름 변경을 다른 identity로 본다). 사용자 영향은 다음과 같다. 업그레이드 전 BLOCKED 로컬 STT Job의 명시 계속은 CONTINUE_PLAN_CHANGED가 되고 새 요청으로 다시 전사해야 한다. 로컬 전사이므로 원격 전송·비용은 없다.
- **범위 밖 7파일(C00 승인, 25+7=32파일)**: 확인 없이는 child·loader를 만들지 않는다는 의도된 새 동작 때문에 깨진 기존 fixture만 적응했다(§4). 기대값 변경은 C00 조건대로 `tests/ui/test_device_policy_ui.py`의 CT2 key 손계산 oracle 하나뿐이다. `tests/unit/test_gpu_runtime.py`는 `LocalSTTProcess._start()`의 무인자 시그니처를 유지해 수정하지 않았다.
- 실제로 바뀌지 않은 승인 파일: `models/__init__.py`, `diarization/contracts.py`, `tests/ui/test_models_ui.py`(적응 없이 통과).

### 2. 파일별 구현

- `models/artifacts.py`(신규): `FileEntry`, canonical artifact digest(domain tag + 정렬된 `(이름, 크기, SHA-256, PRESENT/ABSENT_DEFAULT/ABSENT)`의 canonical JSON), `Terms`·terms digest(출처 종류·license id/URL·license 파일 hash·reference, 미제공은 UNKNOWN/NONE), `ModelSourceSnapshot`(생성 시 digest를 다시 계산해 위조 설명을 거부, source_authenticity는 항상 UNVERIFIED), 8필드 `ConfirmationKey`, `ModelUseEvidence`, 현재 실행 세대 `ConfirmationRegistry`(메모리 전용, Yes+미선택 기본 확인란+보여 준 key 일치일 때만 기록, `new_generation`이면 전부 무효, 표시 상태 5종).
- `models/_artifact_io.py`(신규): `local_path`(UNC·`\\?\`·`\\.\`·상대·ADS를 문자열로, 네트워크·불명 드라이브를 GetDriveTypeW로 먼저 거부하고, 그 뒤 `check_path`로 링크/reparse/hardlink를 거부), identity·크기·mtime을 앞뒤로 대조하는 `hash_file`, Whisper load 집합 snapshot(필수 3·선택 2·license 파일, case 충돌·지원 안 되는 load 입력·0바이트 거부), 관리 설치 snapshot(폴더 밖에서 고정한 spec digest와 일치할 때만 MATCH, 아니면 INVALID이며 자동 수동 강등 없음), 화자 snapshot, 실행 직전 재검사, `freeze`(소유 TEMP로 chunk 복제하며 대조 → root identity·입력 이름 집합 재대조 → 파일·폴더 공유 거부 guard → seal된 bytes 재검증), child 쪽 `whisper_files`/`diarization_files`, `ArtifactError`(outcome_known/retryable을 그대로 전달).
- `models/manager.py`: 검토 spec의 `spec_digest`와 `verified_spec`을 추가했다. `verify`는 목록용 구조 검사로 유지한다.
- `transcription/adapters.py`: `FasterWhisperProvider(bundle=...)`. bundle이 없으면 lazy 생성만 하고 loader에 도달하지 않는다(CAPABILITY_UNSUPPORTED). bundle이 있으면 pinned SDK의 `files` 매핑(tokenizer bytes 필수, 선택 입력 없음은 고정 기본 `{}`, model.bin은 bundle 사본의 reader)과 경로가 아닌 bundle id를 넘긴다. `files`를 모르는 SDK(TypeError)는 원 폴더로 다시 시도하지 않고 CAPABILITY_UNSUPPORTED로 닫는다. facts에 받은 artifact digest를 담는다.
- `app/inference.py`: `LocalSTTProcess(model_evidence=...)`. lease 안 `_start`에서 재검사·seal한 bundle 폴더와 설명만 child에 준다. load 응답의 digest가 확인한 digest와 다르면 MODEL_CHECKSUM_MISMATCH로 닫는다. bundle은 child 종료 ACK 뒤에만 해제하고, ACK가 없으면(INFERENCE_ACK_PENDING) 봉인을 유지한다.
- `diarization/models.py`·`backend.py`·`process.py`: `verified_bundle`이 같은 엄격 검사(manifest·두 ONNX·두 license)로 전체 bytes를 돌려준다. 부모 `_seal`이 실행 직전 엄격 재검증 → 확인한 snapshot과 대조 → 같은 bytes로 seal하고, child `compute`는 seal된 bundle만 읽는다(bundle 없으면 CAPABILITY_UNSUPPORTED). ONNX 외부 tensor 감사·CPU 전용·Job guard는 그대로이고, bundle은 `_reap` 종료 ACK 뒤 해제한다.
- `ui/ai_bridge.py`: 로컬 Whisper·화자 요청은 AI lane에서 snapshot을 만들고 현재 실행 확인이 없으면 Job 없이 `MODEL_CONFIRMATION_REQUIRED` UI 상태(G-P07 prefix 분류 밖, action `model_confirmation`)로 멈춘다. 같은 bytes를 ModelPanel에 보여 주고 모델 관리 탭으로 안내한다. 접수 시 evidence를 `OwnedSTT`/`OwnedDiarization`에 고정한다(대기 Job은 현재 UI로 바꾸지 않음). `local_result_key`·`model_request`(artifact digest를 같은 snapshot에서 ResourceRequest.model_identity로 결합, 명시 profile 유지)를 모듈 함수로 분리했다.
- `ui/models.py`: ModelPanel 확인 화면(역할·출처·인증 범위 "출처 인증 안 됨"·license 상태·전체/파일별 SHA-256·복제 공간 안내, 미선택 확인란, 기본 아니요 확인 창, 늦은 응답·바뀐 화면 기록 거부, 같은 key 재표시 무변화). 검토 manifest의 pin, 관리 설치의 명시 수동 채택 버튼도 여기 있다. hash는 패널 모델 lane에서 수행한다.

### 3. 설계 결정

1. 확인/실행 증거 key(8필드)와 결과 config_key를 분리했다(§개정 2). 결과 키는 artifact digest와 실제 device뿐이다. trust·terms·root·실행 세대·정책·profile·priority는 evidence/ResourceRequest에 남는다. 화자는 license hash가 고정 manifest 안에 있어서 terms만 따로 바뀌는 경우가 없고, manifest(artifact 입력)와 결과 식별이 함께 바뀐다.
2. 관리 설치의 기대 reference는 ModelPanel이 검토 manifest를 고를 때 고정한 `spec_digest`다(이 실행 메모리). 재시작 뒤에는 manifest를 다시 제시하거나 명시 수동 채택을 해야 한다. installed.json만으로는 실행 증거가 되지 않는다(T11·T12).
3. seal은 Windows `CreateFileW(GENERIC_READ, FILE_SHARE_READ)` handle을 파일마다, 폴더에는 BACKUP_SEMANTICS로 유지한다. 실측 결과 쓰기·삭제·이름 변경(파일·폴더)은 거부되고 읽기·자식 프로세스 읽기는 허용된다. 비 Windows는 guard를 지원하지 않으므로 CAPABILITY_UNSUPPORTED다.
4. child는 받은 bundle을 다시 hash한 뒤에만 loader에 넘기고, 부모는 응답 digest를 대조한다(T22). 대형 model.bin을 Python bytes로 이중 복사하지 않는다.
5. 화자 복제의 원본은 부모가 실행 직전에 엄격 검증한 메모리 bytes다. 그 뒤 원본이 바뀌어도 현재 실행은 확인한 bytes로 진행하고 다음 요청이 거부한다(R의 copy 시점 화자 행).

### 4. 기존 fixture 적응(승인 8 + 범위 밖 7)

모든 적응은 실제 snapshot 계산 → 해당 실행 registry 기록(Yes+책임 확인) → evidence/bundle 전달이다. 항상 통과하는 gate나 우회 monkeypatch는 쓰지 않았다.

| 파일 | 실패 원인 | 적응 요약 |
| --- | --- | --- |
| tests/unit/test_providers.py | bundle 없는 FasterWhisperProvider | `confirmed()` fixture가 봉인 bundle을 만든다. 누락 파일은 확인 단계 MODEL_MISSING, 확인 없음은 CAPABILITY_UNSUPPORTED로 고정하고, fake factory가 bundle id·files 매핑을 받는지 확인한다 |
| tests/unit/test_inference.py | evidence 없는 LocalSTTProcess | 확인 없음 → child 0(두 번), 확인 뒤 원본 변경 → MODEL_CHECKSUM_MISMATCH·bundle 잔존 0 |
| tests/unit/test_diarization.py, tests/contract/test_diarization_contract.py | evidence/bundle 없는 child·compute | 엄격 합성 manifest와 확인 evidence, fake child에 bundle 인자. audio hash 계약 시험은 그대로 유지 |
| tests/integration/test_provider_security_independent.py | 같은 원인 | 확인 fixture. 누락 tokenizer는 확인 거부·확인 없음 CAPABILITY·위조 설명 MODEL_MISSING이며 import 0 |
| tests/ui/test_live_ui.py, tests/ui/test_gpu_runtime_ui.py | 창이 확인 없는 모델로 실행 | 창 ModelPanel registry에 실제 snapshot 확인을 기록. 화자 manifest hash oracle은 fixture 입력 값과 같은 의미로 비교 |
| (범위 밖) tests/integration/test_stt_input_independent.py | bundle 없는 provider 7건 | `confirmed()` fixture만 추가. 시간축·실패 분류 assertion은 그대로 |
| (범위 밖) tests/integration/test_model_runtime_independent.py | evidence 없는 정지·부모 사망 시험 3건 | 합성 폴더 확인 evidence와 bundle 부모 폴더. hung worker 인자를 확장하고 receipt는 bundle 옆에 둔다. 정지·ACK assertion은 그대로 |
| (범위 밖) tests/integration/test_diarization_independent.py | evidence 없는 child 4건 | 확인 helper(+child bundle 인자). helper 삽입이 기존 parametrize를 시험에서 떼어 놓던 실수를 바로잡아 원래 decorator를 보존 |
| (범위 밖) tests/integration/test_ai_independent.py, test_selection_version_cas.py | bridge 화자 미접수 4건 | 엄격 합성 manifest를 창에 입력하고 창 registry에 확인. Runtime fake가 evidence를 받는지 확인. 선택 CAS assertion은 그대로 |
| (범위 밖) tests/ui/test_resource_policy_ui.py | T29 로컬 STT·aux 화자 2건 | 창 registry 확인. fake Local이 evidence를 받아 빼낸 뒤 원래 kwargs assertion 유지 |
| (범위 밖) tests/ui/test_device_policy_ui.py | G16 S CT2 명시 계속 4건 | SEnv 창 registry 확인 + **유일한 기대값 변경**: CT2 key 손계산 oracle을 연결 hash에서 canonical JSON+domain tag digest로 교체(f-string 손작성 bytes, 시험 주석에 근거) |

### 5. 시험 배치·감사·시간

| 파일 | 가족 | 수집 node |
| --- | --- | ---: |
| tests/unit/test_manual_models.py | A192·B72·K512·T27(T10 제외) | 804 |
| tests/property/test_manual_model_case_space.py | 독립 분모·축 곱·생성 불변·같은 bytes 재해시·registry 상태 모델 | 5 |
| tests/integration/test_model_bundle.py | R144·P112·L100·D48·I64·J64, X-01·X-06 | 535 |
| tests/ui/test_manual_model_ui.py | C144·U180·T10, X-02~X-05 | 330 |
| 합계 | 정식 1,660 + 보강 X 6 + 분모·불변 8 | **1,674** |

정식 1,660 ID 감사 결과: 누락·중복·초과 0, skip 0(가족별 A192·B72·C144·D48·I64·J64·K512·L100·P112·R144·T28·U180). 보강 행(분모 밖): X-01 형제 prefix root, X-02~X-05 확인 없음 → native·child·dispatch 0(로컬 STT·화자·live STT·명시 계속, C00 조건 ③), X-06 대기 Job이 더 새로운 확인으로 바꿔 실행하지 않음. 신규 4파일은 정확한 사본에서 1,674 passed, **42.4초**다(60초 게이트).

구현 중 시험이 찾아 고친 제품 결함: T14(Whisper evidence에 화자 bytes를 주면 역할 불일치로 거부), 원본 폴더 소실 시 MODEL_MISSING, `hash_file`의 로컬 판정 선행, 복제 중 새 load 입력 등장 시 seal 전 거부, 바뀐 bytes를 재확인한 뒤의 표시 순서, 필수 파일 자리의 폴더 → MODEL_MISSING, SDK TypeError → CAPABILITY_UNSUPPORTED. 첫 전체 회귀가 드러낸 결함도 고쳤다. loader에 넘긴 model.bin reader가 provider 수거 때 닫히지 않던 ResourceWarning 20건이다(provider finalizer가 reader를 닫음). 이 수정 뒤 관련 4파일을 `-W error::pytest.PytestUnraisableExceptionWarning`으로 다시 돌려 1,002 passed를 확인했다.

### 6. mutation (29개)

정확한 사본(`git archive 47530a2` + 32파일)의 OS TEMP 복제본에서 하나씩 적용했다. 매번 `recoryn.__file__`이 복제본 src인지 확인했다. 대상은 신규 4파일이고, M07에는 `tests/unit/test_providers.py`, M25에는 `tests/ui/test_device_policy_ui.py`를 더했다. KILLED는 종료 코드 1·failed>0·error 0·assertion 실패 줄(`AssertionError`/`assert`/`DID NOT RAISE`)이 있을 때만이다. 감시 io는 UNC·장치 경로를 운영체제에 넘기지 않고 assertion으로 거부하므로, 변이가 실제 네트워크에 닿지 않는다.

| ID | 변이 | 결과 | 검출 예 |
| --- | --- | --- | --- |
| M01 | 이름·크기 없이 SHA만 이어 hash | KILLED 62 | B 손작성 digest |
| M02 | 선택 입력 없음 표식 누락 | KILLED 46 | B 손작성 digest |
| M03 | 실행 직전 재검사 제거 | KILLED 6 | P copy의 비로컬 접근 감시, R queued |
| M04 | 확인 없이(아니요/미선택) evidence 발급 | KILLED 58 | A refused |
| M05 | key에서 artifact digest 제외(옛 확인 재사용) | KILLED 43 | K·A old_digest |
| M06 | 실행 세대 검사·무효화 제거 | KILLED 49 | A old_generation·K·상태 모델 |
| M07 | files 매핑 대신 원 경로로 loader 호출 | KILLED 62 | T20·B·providers |
| M08 | 복제 뒤 대조·입력 집합·seal 재검증 제거 | KILLED 10 | R copy |
| M09 | child 응답 digest 대조 제거 | KILLED 1 | T22 |
| M10 | seal 직후 guard 해제 | KILLED 74 | T21·L |
| M11 | child ACK 전 bundle 정리 | KILLED 11 | T23·L REAP_PENDING |
| M12 | seal 뒤 원본을 현재 native 입력으로 사용 | KILLED 59 | T21·R sealed/native |
| M13 | 다음 요청의 원본 재검사 생략(snapshot 재사용) | KILLED 95 | B·R 다음 요청 |
| M14 | 바뀐 화면·늦은 응답으로 기록 | KILLED 13 | U late |
| M15 | 아니요/Esc를 Yes로 처리 | KILLED 53 | C No/Esc |
| M16 | 자체 digest를 공식 검증으로 표시 | KILLED 150 | U 표시 문구 |
| M17 | 책임 확인란 자동 선택 | KILLED 25 | U Space |
| M18 | 관리 설치 변조를 수동 성공으로 강등 | KILLED 25 | A managed_tampered |
| M19 | hardlink/reparse 보호 제거 | KILLED 9 | A parent_reparse·P |
| M20 | 로컬 판정 전 realpath | KILLED 50 | T08·T09·P 감시 |
| M21 | installed.json을 유일 기대값으로 사용 | KILLED 2 | T11·T12 |
| M22 | 화자 manifest 고정 hash 생략 | KILLED 32 | D manifest_hash |
| M23 | 화자 license hash 생략 | KILLED 2 | D license |
| M24 | snapshot 실패 뒤 원 폴더로 native 계속 | KILLED 1 | X-06 |
| M25 | terms를 결과 config_key에 추가 | KILLED 4 | G16 S CT2 명시 계속(같은 의미 키) |
| M26 | 대기 Job evidence를 현재 확인으로 교체 | KILLED 1 | X-06 |
| M27 | 불일치 known profile을 None으로 버림 | KILLED 1 | T25 |
| M28 | UNKNOWN 요구량에 legacy profile 부여 | KILLED 2 | T26 |
| M29 | wrapper에서 outcome_known=False를 True로 승격 | KILLED 16 | J runner |

29/29 KILLED, error 0. M24 첫 정의는 변이 자체가 `None` 속성 접근으로 터져(AttributeError) invalid였다. 그래서 "freeze 실패를 무시하고 원 폴더 경로로 child를 띄우는" 변이로 다시 정의해 X-06이 검출했다. M24·M26·M09·M27은 각각 한두 행만 검출한다(가장 얇은 검출).

### 7. 회귀·coverage·정적 검사

정확한 사본은 `git archive 47530a2`에 승인 32파일만 덮어쓴 OS TEMP 트리다. 기준과의 차이는 신규 6파일과 수정 23파일이고, 바뀌지 않은 승인 3파일은 기준과 같다. PYTHONPATH와 `recoryn.__file__`은 사본 src이며, mutation의 자식 import도 사본에서 확인했다.

| 검사 | 결과 |
| --- | --- |
| CI 동등 전체(`--cov=recoryn --cov-branch --cov-fail-under=85`, 최종본) | **26,980 passed**, failures·errors·skipped·warnings 0, 1,920.9초, 전체 coverage 92.31% |
| `scripts/check_coverage.py coverage.json` | domain·capture·jobs·storage·security·content·all 전부 PASS(all line 93.68%·branch 88.26%) |
| 신규 4파일 | 1,674 passed, 42.4초 |
| 신규 모듈 coverage | artifacts 90.25%·_artifact_io 84.82%·adapters 94.81%·diarization/process 90.00%·ui/models 74.05%·app/inference 72.03%(child `_worker`는 별도 프로세스) |
| ruff check·format --check | 통과(211파일) |
| `python -m mypy src/recoryn scripts packaging` | 95 source files, issue 0 |

G-P02/P06/P07/P11/P12/P16 회귀와 tests/ui 전체는 전체 실행에 포함된다.

### 8. 남은 위험·미검증

- 외부 게이트(NOT_RUN): 실제 faster-whisper/CTranslate2가 `files` 매핑으로 실가중치를 읽는지, lazy read 수명, Whisper 품질, GPU, 대형 model.bin 복제의 디스크·RAM peak, 공식 출처·가중치 license·서명, Narrator 실사용.
- 공유 거부 guard는 협력 경계다. 같은 사용자 권한의 악성 코드·관리자 권한 변경이나 SDK 내부 동작까지 OS sandbox로 증명하지 않았다. 비 Windows는 guard 미지원(CAPABILITY_UNSUPPORTED)이다.
- 고아 bundle(crash 뒤 남은 TEMP)의 자동 정리는 없다. 정리 실패는 `bundle_cleanup_pending`으로만 남고, 재사용하지 않는다.
- 관리 설치의 기대 reference(검토 spec pin)는 현재 실행 메모리에만 있다. 재시작 뒤 관리 모델은 manifest 재제시 또는 명시 수동 채택이 필요하다(의도된 UX 비용).
- J 표의 기대값은 G-P07 폐쇄 표를 손으로 옮긴 것이며 현재 분류와 일치했다. G-P07이 코드를 등록·변경하면 표도 함께 바뀌어야 한다.
- 화자 manifest 경로·hash·승인 위젯은 ui/main.py(범위 밖)에 그대로 있다. 확인 화면은 ModelPanel이 맡는다.

## §FIX1 (G13 독립 검토 반영, 기준 `47530a2` → 최종 확인 `f4f94b7`)

상태: **G13 FIX1_READY — 같은 검토자의 재확인 대기**. 구현 Claude(C00 배정 G-P13 FIX1). 근거 검토는 `docs/reviews/g13-manual-model-review.md`(LF sha256 `f6ff6938145cbd88…`)다. 위의 승인 원문·§개정 요청·§구현 결과는 그대로 두고 이 절만 추가했다. 이 절이 §구현 결과와 다르면 이 절이 현재 상태다.

쓰기는 G-P13 32파일 안에서만 했다. 실제로 바뀐 파일은 16개다: 제품 8, 시험 7, 이 문서. `storage/_safe.py`·`ui/main.py`·`jobs/*`·`models/resources.py`·`ui/content.py`·정본 문서는 바꾸지 않았다. 작업 중 main이 `f4f94b7`(G-P11d)로 올라갔다. 그 커밋의 7파일(jobs/runner·models/resources·g11 문서 3·resource_followup 시험 2)과 G-P13 32파일의 겹침은 0이다. 그래서 최종 확인은 `git archive f4f94b7` + 32파일 사본에서 다시 했다.

### F1. 지적별 처리

| ID | 등급 | 처리 | 시험 |
| --- | --- | --- | --- |
| G13R-01 | S1 | `vocabulary.txt`를 `vocabulary.json`과 같은 **선택 load 입력**으로 옮겼다. 있음/없음을 digest 행에 넣고 bundle 복제·`files` 매핑으로 child에 준다. 둘 다 있으면 `CAPABILITY_UNSUPPORTED/VOCABULARY_AMBIGUOUS`로 거부한다. 지원 안 되는 load 입력은 `shared_vocabulary.json`·`shared_vocabulary.txt`만 남았다. B `new_metadata`는 `shared_vocabulary.json`으로 바꿨다 | X-07(수동·관리 수락, child에 bytes 전달), X-08(둘 다 → 거부), B 손 oracle |
| G13R-02 | S2 | `ConfirmationKey`에 9번째 필드 `integrity`를 넣었다. 현재 판정이 INVALID면 key가 달라 evidence가 없고, 화면 `CHANGED_INVALID`와 실행 판정이 같은 snapshot을 쓴다. 실행 직전 `recheck_whisper`는 MANAGED이면 `managed_snapshot`을 관리 spec·pin과 다시 계산한다. 그리고 root identity·항목·artifact/terms digest·integrity가 확인 당시와 모두 같아야 한다 | X-09(installed.json URL만 변경 → evidence 없음·freeze 거부), X-10(installed.json 삭제 → 대기 Job 거부) |
| G13R-03 | S2 | (a) 재사용·(b) 공간 예비·(c) 측정. 아래 F2 | X-14·X-15·L 가족, F2 측정 |
| G13R-04 | S3 | `managed_snapshot`이 hash한 snapshot 항목(PRESENT 입력과 license 파일)을 spec의 같은 이름 `FileSpec(size, sha256)`과 하나씩 대조한다. 하나라도 다르면 INVALID다 | X-11(두 읽기 사이 model.bin 변경 → INVALID) |
| G13R-05 | S3 | license 파일은 casefold로 찾고 실제 이름으로 기록한다. 0바이트도 snapshot에 넣어 seal 전 입력 이름 재대조와 규칙이 같다 | X-12(0바이트 LICENSE·소문자 license.txt → 확인·실행 가능) |
| G13R-06 | S3 | license 상태 `FILE_ONLY`를 더했다. 문구는 "라이선스 파일 있음(SHA256 표시) — 식별자·URL 미제공, 조건 확인은 사용자 책임"이다. 실행 자격은 바뀌지 않는다(수동 Whisper는 책임 예외, 관리는 spec이 id·URL을 강제, 화자는 DECLARED만) | X-12, X-13 |
| G13R-07 | S3 | (a) 정리 실패 사본을 모듈 대기 목록에 남긴다. ModelPanel `cleanup_status`("임시 모델 사본 정리 대기 N개 — 다음 정리 때 다시 시도합니다", 접근성 이름 "임시 모델 사본 정리 상태")와 bridge tick이 보여 준다. 다음 Job 획득·모델 삭제·종료 때 다시 시도한다. (b) seal 검증과 child `whisper_files`/`diarization_files`가 bundle 폴더의 **정확한 이름 목록**을 요구한다(폴더 guard가 막지 못하는 새 파일 생성 → `MODEL_CHECKSUM_MISMATCH/BUNDLE_CHANGED`, loader 0). 남의 파일은 지우지 않는다 | X-16, X-17, X-22, X-13, X-21 |
| G13R-08 | S3 | **G-P09 인계(코드 변경 없음)**. 아래 F5 | — |
| G13R-09 | S3 | (a) `test_inference.py`에 실제 child 재사용 시험을 되살렸다. 이름이 맞고 config.json digest만 틀린 설명을 child가 받으면 loader 전 `MODEL_CHECKSUM_MISMATCH`이고, 같은 child가 살아서 두 번째 요청에도 재사용된다. (b) X-19: bundle digest 실패 → loader 0(M24b 검출). (c) I 가족 queued는 이제 제품의 `OwnedSTT.open`/`OwnedDiarization.open`이 만든 worker의 `model_evidence`를 본다. 패널이 새 bytes를 확인한 뒤에도 접수 evidence이고, 실행 거부는 그 worker의 evidence로 판정한다. (d) X-09~X-11. (h) X-20(복제 뒤 guard 직전 bundle bytes 변경)과 X-22(guard 직전 새 이름)로 MX5를 검출한다. (e)(f)(g)(i)는 F6에 범위로 적었다 | 위 |
| G13R-10 | S3 | 확인 화면 둘째 줄에 `대상 폴더: <root>`를 표시한다. 확인 없음은 adapter·inference·화자 process·backend 모두 `CAPABILITY_UNSUPPORTED`이며 `detail=MODEL_CONFIRMATION_REQUIRED`를 실제로 싣는다(`ArtifactError`) | X-13, X-18, unit 확인 없음 행의 `.detail` 단언 |

**검토자 반례 재실행**(`build/review-trees/g13a-probe/*.py`를 바꾸지 않고 FIX1 정확한 사본 src로 실행):

| probe | FIX1 전(검토 기록) | FIX1 뒤 |
| --- | --- | --- |
| probe_vocab | `vocabulary.txt` 폴더 REFUSED LOADER_INPUT_UNSUPPORTED, 소문자 license.txt REFUSED NAME_CASE | snapshot OK, 소문자 license.txt OK |
| probe_managed A | 0바이트 LICENSE: 확인은 되나 freeze가 매번 SOURCE_CHANGED | license_files에 0바이트 LICENSE 기록, freeze OK |
| probe_managed B/B2 | installed.json 변경 뒤에도 같은 key·evidence·freeze OK, 삭제 뒤에도 freeze OK | current INVALID·`CHANGED_INVALID`, same key False, evidence None. 삭제 뒤 freeze REFUSED `MODEL_CHECKSUM_MISMATCH/SOURCE_CHANGED` |
| probe_managed C | 두 읽기 사이 변경: integrity MATCH·eligible True·`MANAGED_PIN_MATCH` | integrity INVALID·eligible False·`CHANGED_INVALID`. 확인이 기록되지 않아 probe의 다음 `freeze(None)`이 `CAPABILITY_UNSUPPORTED/MODEL_CONFIRMATION_REQUIRED`로 끝난다(probe는 성공을 가정해 예외를 잡지 않음) |
| probe_display | `METADATA_ONLY`("라이선스 원문 없음")와 LICENSE 줄이 함께 표시 | `FILE_ONLY`, "라이선스: 라이선스 파일 있음(SHA256 표시) — 식별자·URL 미제공, 조건 확인은 사용자 책임" + LICENSE 줄(콘솔 cp949로는 em dash 출력이 막혀 `PYTHONIOENCODING=utf-8`로 실행) |
| probe_guard | 쓰기·삭제·이름 변경 DENIED, 새 파일 생성 ALLOWED, close → CLEANUP_PENDING(남의 파일만 남김) | 같다. 새 이름은 이제 seal 검증·child 이름 목록 검사가 loader 전에 거부한다(X-16·X-22) |
| probe_paths | 비로컬 26문자열 파일시스템 호출 0 | 같다(로컬 drive type 3만 `check`에 도달) |

**계약 §4.1 정정(G13R-01)**: 원문 §4.1이 Whisper 선택 load 입력을 `vocabulary.json` 하나로 열거한 것은 고정 SDK와 다르다. 고정 faster-whisper 1.2.1은 자기 모델을 받을 때 `faster_whisper/utils.py:91-97`의 `allow_patterns`로 `config.json`·`preprocessor_config.json`·`model.bin`·`tokenizer.json`·`vocabulary.*`를 읽는다. `files` 매핑을 받으면 `transcribe.py:674-696`에서 `tokenizer.json`·`preprocessor_config.json`만 꺼내고 나머지(`config.json`·`model.bin`·vocabulary)를 CTranslate2에 넘긴다. 따라서 G13의 Whisper load 입력 집합은 **필수 `config.json`·`model.bin`·`tokenizer.json`, 선택 `preprocessor_config.json`(없으면 고정 `{}`)·`vocabulary.json`·`vocabulary.txt`(둘 중 하나만)**이다. `shared_vocabulary.*`는 지원하지 않는 입력으로 거부한다. 실제 CTranslate2가 `files`의 `vocabulary.txt`를 읽는지는 실가중치 외부 게이트(NOT_RUN)다.

**digest 영향**: 모든 Whisper snapshot에 `vocabulary.txt` 행(대개 ABSENT)이 하나 늘어 canonical digest가 G13 첫 구현과 다르다. 아직 push 전이므로 사용자 기준 변경은 `47530a2` 대비 1회 그대로다. `tests/ui/test_device_policy_ui.py`의 CT2 손 oracle에 `("vocabulary.txt", "ABSENT")` 한 행을 더했다(같은 승인 기대값 변경의 연장).

### F2. G13R-03 결정 이행과 측정

(a) **같은 확인의 봉인 사본 재사용**(C00 결정). `_artifact_io.acquire`가 Job마다 원본을 먼저 다시 검사한다. Whisper는 `recheck_whisper`, 화자는 부모가 방금 엄격 검증한 bytes와 snapshot을 대조한다. 같은 evidence(`record_id`)의 봉인 사본이 있으면 복제 없이 재사용한다. guard는 유지한다. Job은 child 종료 ACK 뒤에만 `release`한다. 그 뒤 사본은 사용자 0의 대기 상태로 봉인된 채 남는다. 사본이 정리되는 경우는 다음과 같다.
- 같은 폴더의 다른 확인이 사본을 획득할 때
- evidence가 무효가 될 때(새 실행 세대)
- 원본이 바뀌어 재검사가 실패할 때
- 모델 삭제·bridge 종료(`release_idle`) 때

쓰는 Job이 있는 동안에는 어떤 경로도 사본을 닫지 않는다. "마지막 사용 Job의 child 종료 ACK 뒤 해제"는 이렇게 해석했다. 사용자 수가 0이 된 뒤 다음 Job에 재사용할 수 없게 된 시점(교체·무효·원본 변경·종료·삭제)에 해제하고, 그 전에는 다음 실시간 Job을 위해 봉인을 유지한다. 대기 사본은 실행 동안 모델 크기만큼 TEMP를 쓴다. C00가 "사용자 0이 되면 즉시 해제"를 원하면 `release`의 한 분기만 바꾸면 된다. 다만 그 경우 실시간 Job마다 복제가 되살아난다.

(b) **복제 전 대상 볼륨 공간 예비**. 복제 대상 폴더(`bundle_parent` 또는 TEMP)의 볼륨이 `free >= 복제 bytes 합 + max(1 GiB, 볼륨 전체의 10%)`이어야 복제한다. 아니면 `RESOURCE_EXHAUSTED/DISK_RESERVE`로 AI 실행만 거부하고, 아무것도 만들지 않는다(조회 실패는 `DISK_UNKNOWN`). 녹음 경로는 이 검사를 호출하지 않으므로 녹음은 막지 않는다. 예비량은 녹음이 쓸 공간이다. 경계는 X-14가 손계산으로 고정한다: 100 GiB 볼륨에서 예비 10 GiB의 −1 byte 거부·정확히 같으면 허용, 4 GiB 볼륨에서 1 GiB 하한. 재사용 시에는 복제가 없어 검사하지 않는다.

(c) **녹음 중 복제 I/O 측정**(실장비 캡처 아님, TEMP 합성, `47530a2` + 32파일 사본. `f4f94b7`은 녹음·저장·복제 코드를 바꾸지 않았다). `RecordingService` 기본 큐(256 block/16 MiB)와 2초 chunk를 썼다. 10 ms block을 실시간 속도로 넣었다. 부하 조건은 세 가지다: AI 없음, FIX1 전 방식(매 Job 새 1 GiB `freeze`+`close` 연속 반복, 최악), FIX1 재사용(매 Job 원본 재검사만 하는 `acquire`/`release` 연속 반복). 각 조건을 1트랙(mic 48 kHz mono)과 2트랙(mic mono + system stereo)으로 돌렸다.

합성 model.bin은 1 GiB다. TEMP 볼륨은 1,862.1 GiB 중 1,003.8 GiB가 비어 있었다. 1회차는 30초씩 none→copy→reuse 순서로 돌렸다. 2~4회차는 20초씩 돌렸고, 순서를 rep마다 회전했다(rep0 none·copy·reuse, rep1 copy·reuse·none, rep2 reuse·none·copy). 표의 값은 submit 거부 block 수와 그때 잃은 frame(mic/system)이다.

| 트랙 | 조건 | 1회차(30초) | rep0 | rep1 | rep2 | AI 반복(회/run) |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| 1 | AI 없음 | 0 | 0 | 0 | 0 | — |
| 1 | 매 Job 새 복제(FIX1 전) | 0 | 0 | 0 | 0 | 복제 6~10 |
| 1 | 봉인 사본 재사용(FIX1) | 0 | 0 | 0 | 0 | 재검사 20~30 |
| 2 | AI 없음 | 590 (16,320/266,880) | 430 | 0 | 0 | — |
| 2 | 매 Job 새 복제(FIX1 전) | 407 (28,320/167,040) | 711 | 366 | 0 | 복제 7~10 |
| 2 | 봉인 사본 재사용(FIX1) | 2 (0/960) | 247 | 289 | 127 | 재검사 20~31 |

가장 느린 submit은 모든 run에서 0.25 ms 이하였다. 2트랙 거부는 **AI가 전혀 없는 run에서도** 났다. 그래서 같은 조건의 writer 자체 처리량을 따로 쟀다. 큰 큐로 거부 없이 2트랙 6,000 block을 넣고 drain까지의 block/s를 보았다.
- AI 없음: 111.3 · 120.6 · 174.7 block/s
- 매 Job 새 복제: 149.9 · 153.9 block/s
- 재사용: 156.5 · 128.5 block/s
- 1트랙 AI 없음: 115.3 block/s

실시간 요구량은 트랙당 100 block/s다. 기준 `47530a2`의 `ChunkWriter._append`는 block마다 PCM과 journal을 각각 `fsync`한다(10 ms block당 2회). 이 PC에서는 그 처리량이 2트랙 요구량 200 block/s 근처이거나 아래다. 같은 PC에서 다른 세션의 시험이 동시에 돌고 있었다(측정 중 확인한 python 프로세스 12개).

판정은 다음과 같다.
- 1트랙: 모든 조건 12 run에서 거부 0이다.
- 2트랙: 거부는 AI 조건보다 **run 위치와 동시 부하**를 따랐다. rep마다 앞쪽 run일수록 거부가 많았고(조건과 무관), 같은 조건도 0~711로 흩어졌다. writer 처리량도 복제 부하가 있을 때 오히려 높은 run이 있었다.
- 이 측정으로는 복제 I/O가 녹음 거부를 늘린다는 근거도, 늘리지 않는다는 보장도 얻지 못했다.
- FIX1의 재사용은 Job당 쓰기(복제 1 GiB 쓰기·삭제)를 0으로 만든다. 재검사 읽기만 남는다. 공간 예비는 녹음 볼륨이 꽉 차는 경로를 닫는다.
- **AI와 무관한 2트랙 writer 처리량 한계**는 G13 범위 밖이다. C00에 별도로 보고한다. 진행 중인 append 내구성 작업(G-P17a, `storage/chunks.py`)에 인계할 것을 권고한다.

이 측정은 이 개발 PC의 단일 NVMe·합성 bytes·Python 공급원 기준이다. 실제 WASAPI 캡처·HDD·저사양 PC·대형(수 GB) 모델의 실장비 게이트는 NOT_RUN이다.

### F3. 보강 시험(정식 1,660 분모 밖)

| ID | 파일 | 내용 |
| --- | --- | --- |
| X-07·X-08 | unit | vocabulary.txt 수락·전달, 두 vocabulary 거부 |
| X-09·X-10·X-11 | unit | 관리 판정 변경·installed.json 삭제·MATCH 결속 |
| X-12 | unit | 0바이트·소문자 license, FILE_ONLY |
| X-14 | unit | 공간 예비 경계(손계산) |
| X-15 | unit | 재사용(복제 1회)·Job별 재검사·원본 변경 시 대기 사본 폐기·다른 확인이 대기 사본 폐기 |
| X-16·X-22 | unit | 봉인 bundle·seal 직전 새 이름 → loader 0, 남의 파일 보존 |
| X-17 | unit | 정리 실패 집계·다음 획득 때 재시도·원본 무손상 |
| X-18 | unit | detail `MODEL_CONFIRMATION_REQUIRED`(화자 backend·process) |
| X-19·X-20 | unit | bundle digest 실패 → loader 0(M24b), seal 직전 bundle bytes 변경 거부(MX5) |
| X-13·X-21 | ui | 확인 화면 대상 폴더·FILE_ONLY 문구·정리 대기 표시와 해제, bridge tick 표시 |

기존 시험의 FIX1 적응은 다음과 같다.
- L 가족 수명 oracle: Job 사용 종료와 대기 사본 봉인 유지를 구분하고, `release_idle` 뒤에는 사용 중인 사본만 남는지 확인한다.
- `test_inference.py`: child 재사용 시험 복원.
- I queued: 제품 worker 생성 경로 사용.
- 화자 unit·독립 시험: 행마다 대기 사본을 정리하는 autouse fixture를 추가하고 bundle 부모를 시험 TEMP로 지정.
- bundle을 직접 `close`하던 시험 3곳: 제품과 같은 `release`로 변경.

기존 단언은 약화하지 않았다.

ID 감사(`--collect-only`)는 정식 1,660행에서 누락·중복·초과 0, skip 0이다(A192·B72·C144·D48·I64·J64·K512·L100·P112·R144·T28·U180). 보강 X는 22행(X-01~X-22), 분모·불변 시험은 8개다. 신규 4파일은 정확한 사본에서 **1,690 passed**다(`-W error::ResourceWarning`). 시간은 `47530a2` 사본 32.4초, `f4f94b7` 사본 42.3초로 60초 게이트 안이다. 같은 PC에서 다른 세션의 시험이 함께 돌았다. K 가족(2^8×2)은 계약의 8필드 축을 그대로 둔다. 9번째 key 필드 `integrity`의 변화는 X-09가 본다.

### F4. mutation

정확한 사본(`git archive <기준>` + 32파일)의 OS TEMP 복제본에서 하나씩 적용했다. KILLED 판정 기준(assertion 실패만, error 0)은 §구현 결과 §6과 같다. 대상은 신규 4파일이다. 검토자 변이(M24b·MX1·MX5·MX9·MX10·MX11)에는 검토자 목록(providers·inference·diarization·contract)을 더했다. M09·M24에는 `test_inference.py`, F01에는 `test_device_policy_ui.py`를 더했다. FIX1 코드 위치로 옮긴 anchor는 M03(freeze와 재사용 재검사 두 곳)·M24·M26(`freeze` → `acquire`)이다.

`47530a2` 사본의 1차 실행에서 4개가 판정 규칙에 걸렸다.
- F02·F08·F11(INVALID): 수락해야 할 행이 거부 예외(KeyError·ProviderError)로 끝나 assertion 실패로 세지지 않았다. X-07·X-12·X-14의 수락 단계를 `accepted()`로 감쌌다. 거부되면 그 행의 assertion 실패가 된다.
- F22(SURVIVED): 첫 정의는 adapter `_ensure_model`의 방어 중복 검사를 바꿨다. 이 검사는 공개 `load`/`transcribe`에서 항상 `_check_model_files`가 먼저 같은 detail로 거부한다. 그래서 공개 경로로는 도달할 수 없는 동치 변이다(F22u로 기록). 도달 가능한 `_check_model_files` 검사를 바꾸는 변이를 F22로 다시 정의했다.

아래 표는 시험을 고친 뒤 **`f4f94b7` + 32파일** 사본에서 60개 전체를 다시 돌린 결과다.

| ID | 변이 | 결과 | 첫 검출 |
| --- | --- | --- | --- |
| M01 | 이름·크기 없이 SHA만 이어 hash | KILLED 63 | `tests/unit/test_manual_models.py:428` |
| M02 | 선택 입력 없음 표식 누락 | KILLED 62 | `tests/unit/test_manual_models.py:428` |
| M03 | 실행 직전 재검사 제거(freeze·재사용 두 곳) | KILLED 11 | `tests/unit/test_manual_models.py:1101` |
| M04 | 확인 없이(아니요/미선택) evidence 발급 | KILLED 58 | `tests/unit/test_manual_models.py:359` |
| M05 | key에서 artifact digest 제외 | KILLED 43 | assertion 실패(긴 repr로 위치 줄 잘림) |
| M06 | 실행 세대 검사·무효화 제거 | KILLED 49 | `tests/unit/test_manual_models.py:359` |
| M07 | files 매핑 대신 원 경로로 loader 호출 | KILLED 64 | `tests/unit/test_manual_models.py:796` |
| M08 | 복제 뒤 대조·입력 집합·seal 재검증 제거 | KILLED 12 | `tests/unit/test_manual_models.py:1329` |
| M09 | child 응답 digest 대조 제거 | KILLED 1 | `tests/unit/test_manual_models.py:847` |
| M10 | seal 직후 guard 해제 | KILLED 93 | `tests/unit/test_manual_models.py:818` |
| M11 | child ACK 전 bundle 정리 | KILLED 29 | `tests/unit/test_manual_models.py:890` |
| M12 | seal 뒤 원본을 native 입력으로 사용 | KILLED 74 | `tests/unit/test_manual_models.py:818` |
| M13 | 다음 요청의 원본 재검사 생략(snapshot 재사용) | KILLED 100 | `tests/unit/test_manual_models.py:583` |
| M14 | 바뀐 화면·늦은 응답으로 기록 | KILLED 13 | `tests/ui/test_manual_model_ui.py:424` |
| M15 | 아니요/Esc를 Yes로 처리 | KILLED 53 | `tests/ui/test_manual_model_ui.py:290` |
| M16 | 자체 digest를 공식 검증으로 표시 | KILLED 150 | assertion 실패(긴 repr로 위치 줄 잘림) |
| M17 | 책임 확인란 자동 선택 | KILLED 25 | `tests/ui/test_manual_model_ui.py:389` |
| M18 | 관리 설치 변조를 수동 성공으로 강등 | KILLED 25 | `tests/unit/test_manual_models.py:359` |
| M19 | hardlink/reparse 보호 제거 | KILLED 9 | `tests/unit/test_manual_models.py:359` |
| M20 | 로컬 판정 전 realpath | KILLED 50 | `tests/unit/test_manual_models.py:644` |
| M21 | installed.json을 유일 기대값으로 사용 | KILLED 3 | `tests/unit/test_manual_models.py:673` |
| M22 | 화자 manifest 고정 hash 생략 | KILLED 32 | `tests/integration/test_model_bundle.py:881` |
| M23 | 화자 license hash 생략 | KILLED 2 | `tests/integration/test_model_bundle.py:881` |
| M24 | 획득 실패 뒤 원 폴더로 native 계속 | KILLED 2 | `tests/integration/test_model_bundle.py:634` |
| M25 | terms를 결과 config_key에 추가 | KILLED 4 | `tests/ui/test_device_policy_ui.py:445` |
| M26 | 대기 Job evidence를 현재 확인으로 교체 | KILLED 1 | `tests/integration/test_model_bundle.py:634` |
| M27 | 불일치 known profile을 None으로 버림 | KILLED 1 | `tests/unit/test_manual_models.py:949` |
| M28 | UNKNOWN 요구량에 legacy profile 부여 | KILLED 2 | `tests/unit/test_manual_models.py:949` |
| M29 | wrapper에서 outcome_known 승격 | KILLED 16 | `tests/integration/test_model_bundle.py:1122` |
| M24b | (검토자) adapter가 whisper_files 실패를 삼키고 빈 files로 loader 호출 | KILLED 2 | `tests/unit/test_manual_models.py:1305` |
| MX1 | (검토자) guard의 handle-이름 identity·reparse·link 대조 제거 | SURVIVED (1870 passed) | — |
| MX5 | (검토자) seal 직후 bundle 재검증 제거 | KILLED 2 | `tests/unit/test_manual_models.py:1329` |
| MX9 | (검토자) 관리 eligible의 NOT_PROVIDED 조건 제거 | SURVIVED (1870 passed) | — |
| MX10 | (검토자) hash_file 앞뒤 크기·mtime·identity 대조 제거 | KILLED 1 | `tests/unit/test_manual_models.py:755` |
| MX11 | (검토자) 화자 _seal의 root identity 대조 제거 | KILLED 4 | `tests/integration/test_model_bundle.py:381` |
| F01 | G13R-01 vocabulary.txt를 다시 지원 안 되는 입력으로 | KILLED 2 | `tests/unit/test_manual_models.py:1043` |
| F02 | G13R-01 vocabulary.txt를 loader에 넘기지 않음 | KILLED 1 | `tests/unit/test_manual_models.py:1060` |
| F03 | G13R-01 두 vocabulary 동시 허용 | KILLED 1 | `tests/unit/test_manual_models.py:1074` |
| F04 | G13R-02 key에서 integrity 제외 | KILLED 1 | assertion 실패(긴 repr로 위치 줄 잘림) |
| F05 | G13R-02 실행 직전 관리 판정 생략 | KILLED 2 | `tests/unit/test_manual_models.py:1101` |
| F06 | G13R-04 MATCH를 hash한 bytes에 결속하지 않음 | KILLED 1 | `tests/unit/test_manual_models.py:1129` |
| F07 | G13R-05 0바이트 license 제외 | KILLED 1 | `tests/unit/test_manual_models.py:1139` |
| F08 | G13R-05 license 이름 대소문자 엄격 | KILLED 1 | `tests/unit/test_manual_models.py:1043` |
| F09 | G13R-06 FILE_ONLY를 METADATA_ONLY로 | KILLED 2 | `tests/unit/test_manual_models.py:1144` |
| F10 | G13R-03 b 공간 예비 검사 제거 | KILLED 1 | `tests/unit/test_manual_models.py:1168` |
| F11 | G13R-03 b 예비 경계 off-by-one(<→<=) | KILLED 1 | `tests/unit/test_manual_models.py:1043` |
| F12 | G13R-03 b 1 GiB 하한 제거 | KILLED 1 | `tests/unit/test_manual_models.py:1173` |
| F13 | G13R-03 a 재사용 제거(Job마다 새 복제) | KILLED 1 | `tests/unit/test_manual_models.py:1195` |
| F14 | G13R-03 a 재사용 시 원본 재검사 생략 | KILLED 3 | `tests/unit/test_manual_models.py:1201` |
| F15 | G13R-03 a 다른 확인이 대기 사본을 폐기하지 않음 | KILLED 1 | `tests/unit/test_manual_models.py:1212` |
| F16 | G13R-03 a Job 종료가 공유 사본을 즉시 닫음 | KILLED 37 | `tests/unit/test_manual_models.py:1196` |
| F17 | G13R-07 b child Whisper 이름 목록 검사 제거 | KILLED 1 | `tests/unit/test_manual_models.py:1224` |
| F18 | G13R-07 b seal 검증의 이름 목록 검사 제거 | KILLED 1 | `tests/unit/test_manual_models.py:1348` |
| F19 | G13R-07 a 정리 실패를 집계하지 않음 | KILLED 3 | `tests/unit/test_manual_models.py:1262` |
| F20 | G13R-07 a bridge tick이 정리 대기를 갱신하지 않음 | KILLED 1 | `tests/ui/test_manual_model_ui.py:700` |
| F21 | G13R-10 확인 화면 대상 폴더 줄 제거 | KILLED 1 | assertion 실패(긴 repr로 위치 줄 잘림) |
| F22 | G13R-10 adapter가 detail을 버림(공개 경로의 첫 검사) | KILLED 1 | `tests/unit/test_manual_models.py:906` |
| F22u | G13R-10 같은 변이를 _ensure_model 방어 중복 검사에(공개 경로 도달 불가) | SURVIVED (1690 passed) | — |
| F23 | G13R-03 a 원본이 바뀐 대기 사본 유지 | KILLED 1 | `tests/unit/test_manual_models.py:1203` |
| F24 | G13R-07 a 다음 획득 때 정리 재시도 안 함 | KILLED 1 | `tests/unit/test_manual_models.py:1269` |

결과: **57/60 KILLED, INVALID 0**. 원래 29개·검토자 M24b·MX5·MX10·MX11·FIX1 F01~F24가 모두 KILLED다. 생존 3개는 모두 같은 범위에서 도달할 수 없거나 다중 방어로 덮인다.
- MX9: `ModelSpec`이 id·URL을 강제해 도달 불가한 동치 변이다.
- F22u: 공개 경로에서 앞선 검사가 같은 detail로 거부해 도달 불가한 방어 중복이다.
- MX1: 다중 방어로 덮이며 G-P13b로 보낸다(F6).
검토자 정의 그대로의 M24b·MX5는 FIX1 전 생존에서 KILLED로 바뀌었다(X-19, X-20·X-22). `47530a2` 사본의 1차 전체 실행도 같은 판정이었다(29개 KILLED, 검토자 MX1·MX9 생존, F02·F08·F11 INVALID와 F22 생존은 위처럼 시험·정의를 고친 뒤 KILLED).

### F5. G-P09 인계(G13R-08)

restore·import·라이브러리 전환을 실행 중에 구현하는 배정(G-P09)에 다음을 넣어야 한다.
- 그 시점에 `model_panel.confirmations.new_generation()`을 호출한다.
- `ConfirmationRegistry.library_instance`를 실제 Library 식별자로 바꾼다.
- 세대 교체 뒤 `release_idle()`을 호출해 이전 세대의 대기 사본을 정리한다.

현재 tree에는 실행 중 restore·import·전환이 없고 새 실행은 새 ModelPanel이므로 지금의 결함은 아니다. C 가족 restore 행은 `new_generation()`을 직접 부른다.

### F6. G-P13b로 미룬 항목과 남은 위험

G-P13b 후보는 모두 S3이고 제품 결함이 아닌 시험 범위다. 같은 범위에서 고치지 않은 이유를 함께 적는다.

| 항목 | 내용 | 미룬 근거 |
| --- | --- | --- |
| G13R-09 (e) | C 가족 Esc는 monkeypatch한 `QMessageBox.question`의 No다. 세션 변경 축은 `processEvents()`뿐이다 | 실제 모달 창을 QTimer로 구동하는 시험 harness가 필요하다. 기록 판정(Yes만 기록, 늦은 응답 token 거부)은 C·U·M14·M15가 검출한다 |
| G13R-09 (f) | T27 "처리한 청크 재전송 0·원격 key 불변"을 공개 경로로 관찰하지 않는다 | 원격 STT 재개 경로(G-P06/G-P07 공개 API)의 bridge 수준 시험이 필요하고, 로컬 모델 확인과 독립이다 |
| G13R-09 (g) | 화자 응답에는 bundle digest 결속(T22)이 없다(config의 manifest SHA를 되돌린다) | 화자 child가 seal된 bundle을 `diarization_files`로 다시 hash한 뒤에만 compute한다(이름 목록·digest 불일치 → 거부). 부모 쪽 응답 digest 대조는 승인 파일 안이다. 다만 화자 응답 계약(`diarization/contracts.py`)과 기존 계약 시험의 기대값을 함께 바꾸므로 이번 S3 범위에서 떼어 G-P13b로 둔다 |
| G13R-09 (i) / MX1 | guard의 handle-이름 identity·reparse·link 대조 제거가 생존한다 | 다중 방어(`check_path` hardlink·reparse 거부, seal 재hash, 정확한 이름 목록, child 재hash)가 같은 창을 닫는다. Win32 handle 정보만 다르게 주입하려면 guard에 새 seam이 필요하다 |
| MX9 | 관리 eligible의 NOT_PROVIDED 조건 제거 | 동치 변이다. `ModelSpec`이 license id·URL을 필수로 요구해 도달할 수 없다 |
| 고아 사본 | crash 뒤 TEMP에 남은 `recoryn-model-bundle-*`의 시작 시 정리 | 남의 파일을 지우지 않는다는 소유 증명(세션 marker 등)이 새로 필요하다. 보존·진단(G-P14) 범위와 겹친다 |

- 외부 게이트(NOT_RUN)는 §구현 결과 §8과 같다. 추가로 실제 CTranslate2의 `vocabulary.txt` `files` 읽기, 수 GB 모델 재사용 사본의 실행 내내 TEMP 점유, 실장비 녹음+실시간 전사+대형 모델 동시 게이트가 있다.
- 대기 사본은 프로세스 메모리 목록이다. crash 뒤 남은 고아 사본의 자동 정리는 여전히 없다(§구현 결과 §8 유지).
- 정확한 이름 목록 검사와 child 재hash는 seal 뒤 새 파일을 loader 입력에서 배제한다. 다만 seal 검증과 child 목록 검사 사이에 생긴 파일이 같은 사용자 권한 코드에 의해 계속 추가되는 것까지 OS 수준에서 막지는 않는다(협력 경계, §구현 결과 §8).

### F7. 회귀·coverage·정적 검사

정확한 사본은 OS TEMP에 만들었다. `git archive <기준>`에 G-P13 32파일만 덮어썼다. PYTHONPATH와 `recoryn.__file__`은 사본 src였고, mutation 복제본의 import도 매번 확인했다.

| 검사 | `47530a2` + 32 | `f4f94b7` + 32(최종) |
| --- | --- | --- |
| CI 동등 전체(`-W error::ResourceWarning --cov=recoryn --cov-branch --cov-fail-under=85`) | 26,996 passed, failures·errors·skipped 0, 2,318.6초, coverage 92.45% | **27,036 passed**, failures·errors·skipped 0, 2,285.0초, coverage **92.48%** |
| `scripts/check_coverage.py` | 7개 예산 전부 PASS(all line 93.79%·branch 88.48%) | 7개 예산 전부 PASS(all line 93.81%·branch 88.53%) |
| 32파일 시험 + test_gpu_runtime·test_models(+G-P11d resource_followup 2파일) | 2,839 passed(FIX1 중간) | 2,984 passed, 215초 |
| 신규 4파일 | 1,690 passed, 32.4초 | 1,690 passed, 30.1초(최종 시험본) |
| ruff check·format --check | 통과(211파일) | 통과(211파일) |
| `mypy src/recoryn scripts packaging` | 95파일 issue 0 | 95파일 issue 0 |

`f4f94b7` 전체 실행에는 경고 두 줄이 있었다. 둘 다 시험 종료 뒤 coverage 결합 단계에서 나왔고, 실패는 0이다.
- 한 자식 프로세스의 병렬 coverage 데이터 파일이 손상됐다(`CoverageWarning: ... SQLITE_CORRUPT`). 종료당한 자식의 기록 중단으로 보인다.
- coverage 자신의 sqlite 연결에서 `ResourceWarning`이 났다.

`47530a2` 실행에는 둘 다 없었다. 전체 실행 뒤에는 시험 전용 변경 하나만 했다. `test_manual_models.py`의 `.detail` 단언 8개를 `getattr(..., "detail", None)`으로 바꿨다(속성 없는 오류도 assertion 실패가 되도록, F22). 그 뒤 신규 4파일을 다시 돌렸다.

변경 모듈 coverage(`f4f94b7` 최종 실행): artifacts 90.46%, _artifact_io 87.77%, adapters 94.83%, diarization/process 90.00%, ui/models 74.32%, app/inference 82.20%, ui/ai_bridge 81.17%.
