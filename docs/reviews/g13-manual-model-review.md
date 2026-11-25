# G13 / G-P13 수동 로컬 모델 digest·신뢰 확인·고정 bundle 독립 검토

상태: **검토 완료 — OPEN S0 0 · S1 1 · S2 2 · S3 7**. S1 1건(G13R-01)이 푸시를 막는다. 검토자: C00 지정 독립 검토 하위 에이전트. 작성자(C00 지정 구현 하위 에이전트)와 다른 세션이다. 코드를 고치지 않았고 이 문서 하나만 썼다.

## 1. 대상·기준·환경

- 대상 tree **`e447958c73a46ebe47baa4a2a6085b4930277954`** = HEAD `47530a2`(G-P16 포함) + G-P13 29파일. `git archive e447958c | tar -x`로 `build/review-trees/g13a`에 풀어 그곳에서만 실행했다. 작업 트리의 G-P17a·G-P11d·G-P12b 미완성 변경은 쓰지 않았다.
- PYTHONPATH는 사본 `src`로 고정했고 `recoryn.__file__`를 실행마다 확인했다(전체 회귀: `build\review-trees\g13a\src\recoryn\__init__.py`, 변이: `g13a-probe\mut\src\…`). spawn 자식은 같은 환경 변수를 물려받는다.
- 계약: `docs/testing/g13-manual-model-cases.md` LF SHA-256 `3cc127dd1339025ed727326a8a0f3006190b9d3be2bed64dbf0864994c4e1477`(사본·작업 트리 동일, 471행). 앞 40,538 bytes의 LF SHA-256이 승인 원문 `56dc2fef…0007`과 같아 원문이 바이트 단위로 보존됐다. 정본은 architecture ADR17(288행), validation-plan S04(113행), 배정표 G13 행의 C00 결정이다.
- 실제 모델 다운로드·실제 가중치 로드·GPU·nvidia-smi·네트워크·사용자 모델 폴더·Credential Manager 쓰기는 쓰지 않았다. 반례는 합성 bytes, fake io, OS TEMP 파일만 썼다. UNC·장치 경로는 OS에 넘기지 않았다. 모든 파일시스템 호출을 예외로 바꾼 fake io로 `local_path`만 호출했다. 반례 스크립트는 `build/review-trees/g13a-probe/`(probe_paths·probe_managed·probe_guard·probe_display·probe_vocab·mutate)에 있다.
- 실행 사고 1건(제품 무관): 첫 전체 회귀의 `--basetemp` 문자열 조합에서 구분자가 빠졌다. 그 결과 `%LOCALAPPDATA%` 바로 아래 `Tempg13a-review-full-43519` 폴더가 생겼다. 18%에서 내 pytest 프로세스만 멈추고, 내 시험 산출물만 있던 그 폴더를 지웠다. 그 뒤 OS TEMP basetemp로 처음부터 다시 실행했다. 아래 숫자는 다시 실행한 결과다.

## 2. 실행 결과

| 검사 | 명령·조건 | 결과 |
| --- | --- | --- |
| CI 동등 전체 회귀 | `python -m pytest -q -p no:cacheprovider -W error::ResourceWarning --cov=recoryn --cov-branch --cov-report=json:coverage.json --cov-fail-under=85`, `QT_QPA_PLATFORM=offscreen`, `PYTHONDONTWRITEBYTECODE=1`, basetemp `%TEMP%\g13a-review-full-46708` | **26,980 passed**, failed·error·skip·warning 0, 1,828.96초, 전체 coverage **92.33%** |
| `python scripts/check_coverage.py coverage.json` | 위 결과 | 7묶음 PASS. domain 99.18/97.89, capture 99.85/98.57, jobs 99.19/95.61, storage 95.95/91.41, security 98.11/94.43, content 98.98/99.02, all 93.69/88.29(line/branch %) |
| 신규·변경 모듈 coverage | 같은 coverage.json | artifacts 90.25 · _artifact_io 84.82 · adapters 94.81 · diarization/process 90.00 · backend 90.38 · models 86.32 · ui/models 74.05 · ui/ai_bridge 81.05 · app/inference 72.03(child `_worker`는 별도 프로세스) · manager 90.30 |
| `python -m ruff check src tests scripts packaging` / `ruff format --check` | ruff 0.15.22 | All checks passed / 211 files already formatted |
| `python -m mypy src/recoryn scripts packaging` | mypy 1.20.2, cache는 OS TEMP | Success: no issues found in 95 source files |
| 신규 4파일 수집 | `--collect-only` | 1,674 node. case ID는 §5 분모 항목 참조 |

변이는 사본 `g13a-probe/mut`에서 한 번에 하나씩 적용했다. 대상은 신규 4파일, `test_providers`·`test_inference`·`test_diarization`·`test_diarization_contract`로 1,854 node다. 기준(변이 없음)은 1,854 passed였다. KILLED 판정은 종료 코드 1, failed>0, error 0, assertion 줄이 있을 때만 했다. 원본·변이 hash는 `mutate.log`에 있다.

| ID | 변이 | 결과 | 검출 node |
| --- | --- | --- | --- |
| M09(작성자) | load 응답 digest 대조 제거 | KILLED 1 | T22 |
| M24(작성자 재정의) | freeze 실패를 무시하고 원 폴더로 child 시작 | KILLED 2 | X-06, `test_inference` |
| M26(작성자) | 대기 Job evidence를 현재 확인으로 교체(`_start`) | KILLED 1 | X-06 |
| M27(작성자) | `model_request`에서 known profile 버림 | KILLED 1 | T25 |
| M24b(검토자) | adapter가 `whisper_files` 실패를 삼키고 빈 files로 loader 호출 | **SURVIVED** (범위 밖 provider 보안·STT 입력·runtime 3파일 101 node 추가 실행에서도 생존) | 없음 → G13R-09 b |
| MX1(검토자) | guard의 handle-이름 identity·reparse·link 대조 제거 | **SURVIVED** | 없음 → G13R-09 i |
| MX5(검토자) | seal 직후 bundle 재검증 제거 | **SURVIVED** | 없음 → G13R-09 h |
| MX9(검토자) | 관리 eligible에서 license NOT_PROVIDED 조건 제거 | 생존(동치 변이: `ModelSpec`이 license_id·url을 필수로 요구해 도달 불가) | — |
| MX10(검토자) | `hash_file` 앞뒤 크기·mtime·identity 대조 제거 | KILLED 1 | T17 |
| MX11(검토자) | 화자 `_seal`의 root identity 대조 제거 | KILLED 4 | L-018·L-020·R-070·R-072 |

작성자가 보고한 얇은 검출(M09·M24·M26·M27이 1~2 node)은 그대로 재현됐다. 정상본은 BASE 실행 2회 모두 1,854 passed였다.

## 3. 범위·적응 판정

- `git diff 47530a2 e447958c --stat`은 29파일이다. 내역은 문서 1, src 10, 신규 시험 4, 승인 fixture 7, C00 승인 범위 밖 7이다. src는 계약 12파일 중 `models/__init__.py`·`diarization/contracts.py`가 무변경이고, 승인 fixture는 `tests/ui/test_models_ui.py`가 무변경이다. `storage/_safe.py`·`ui/main.py`·`jobs/*`·정본 문서 변경은 0이다. **범위 밖 변경 0.**
- 범위 밖 7파일은 같은 fixture만 추가했다. `whisper_snapshot`/`verified_bundle`를 실제로 계산하고, 그 실행 registry에 Yes와 책임 확인을 기록하고, evidence/bundle을 넘긴다. 항상 통과하는 gate나 우회 monkeypatch는 없다. fake 생성자 3곳은 `model_evidence.valid()`를 **추가로** 단언한다.
- 기대값 변경은 `tests/ui/test_device_policy_ui.py`의 CT2 key oracle 하나다. 새 oracle은 domain tag와 canonical JSON을 f-string으로 손으로 쓴 것이고 제품 helper를 쓰지 않는다. 나는 이 oracle을 `json.dumps(sort_keys, separators)` 출력과 글자 단위로 대조했다.
- `test_model_runtime_independent.py`는 receipt 위치만 bundle 폴더 옆으로 옮겼다. 정지·ACK 단언은 그대로다. `test_diarization_independent.py`의 parametrize decorator도 원래 시험에 붙어 있다. 판정: **최소 적응, 기존 단언 약화 없음.**
- 기존 단언이 지워진 곳은 승인 범위 안의 세 파일이다.
  - `tests/unit/test_inference.py`: “load 오류 뒤 child 재사용”.
  - `tests/unit/test_providers.py`: provider 단계 MODEL_MISSING이 확인 단계 MODEL_MISSING으로 바뀜.
  - `tests/ui/test_live_ui.py`: manifest SHA를 fixture 값과 비교.
  - 셋 다 의도된 새 동작에 따른 이동이다. 다만 첫째는 대체 시험이 없다(G13R-09 a).

## 4. 발견 사항

### G13R-01 · S1 · OPEN — 고정 SDK 자신의 모델 형식인 `vocabulary.txt`를 지원 안 되는 load 입력으로 거부

- 근거
  - `models/artifacts.py:40`이 `WHISPER_UNSUPPORTED = ("shared_vocabulary.json", "shared_vocabulary.txt", "vocabulary.txt")`를 둔다.
  - `whisper_snapshot`(`_artifact_io.py:308-310`)은 이 이름이 하나라도 있으면 `CAPABILITY_UNSUPPORTED/LOADER_INPUT_UNSUPPORTED`로 snapshot부터 거부한다. 이 함수는 수동과 관리 설치(`managed_snapshot`)가 함께 쓴다.
  - 반례 `probe_vocab.py`: config·model·tokenizer와 `vocabulary.txt`가 있는 합성 폴더는 `REFUSED CAPABILITY_UNSUPPORTED LOADER_INPUT_UNSUPPORTED`다.
  - 시험 `G13-B-*` `new_metadata`는 바로 이 `vocabulary.txt`를 “새 load metadata”로 보고 거부를 기대값으로 고정했다.
- 왜 결함인가
  - 고정한 faster-whisper 1.2.1의 `faster_whisper/utils.py:91-97`은 자기 모델 목록(`_MODELS`의 Systran tiny…large-v3, distil, turbo)을 받을 때 `"vocabulary.*"`를 허용 패턴으로 쓴다. 고정 SDK 자신이 두 형식을 모두 load 입력으로 다룬다는 뜻이다.
  - 설치된 CTranslate2 4.9 DLL에 `.txt`·`shared_vocabulary`·`load_vocabulary` 문자열이 있다. 텍스트 어휘 load fallback이 남아 있는 것으로 보인다(DLL 문자열 기반 추정). converter(`specs/model_spec.py:624-625`)만 `.json`으로 저장한다.
  - 기준 `47530a2`는 원 폴더를 넘겼으므로 이런 폴더도 실행됐다. G-P13 뒤에는 수동·관리 로컬 STT 모두 미리보기 단계에서 막힌다.
  - 대상은 구 CT2 변환본이다. 내가 아는 범위에서는 Systran faster-whisper tiny…large-v2가 `vocabulary.txt`를 담는다. 이 검토는 네트워크 금지라 그 파일 목록을 확인하지 못했다.
- 영향
  - 핵심 기능 실패다. ADR17이 허용한 로컬 Whisper 디렉터리 실행이 표준 모델 한 계열에서 동작하지 않는다.
  - 안전 측 실패라 무동의 전송·다른 bytes 실행은 없다.
  - 계약 §4.1의 열거(vocabulary.json만 선택 입력)를 그대로 구현한 결과이므로 **계약 결함**이기도 하다.
- 권고
  - `vocabulary.txt`를 `vocabulary.json`과 같은 선택 입력으로 옮긴다. 있음/없음을 digest에 넣고 bundle·files 매핑으로 제공한다.
  - 둘이 함께 있으면 거부한다. 예외 이름은 `shared_vocabulary.*`만 남긴다.
  - B 가족 `new_metadata`는 `shared_vocabulary.json`으로 바꾼다. `vocabulary.txt` 행은 정상 입력 행으로 둔다.
- 하향 조건: C00가 승인된 방법으로 실제 대상 모델의 **파일 목록만** 확인한다(가중치 로드 불필요). 그 결과 지원 대상 모델 중 `vocabulary.txt`를 쓰는 것이 없으면 S3로 내린다.

### G13R-02 · S2 · OPEN — 관리 설치의 현재 판정이 INVALID여도 같은 실행의 이전 확인으로 접수·봉인·실행된다

- 근거
  - `ConfirmationKey` 8필드에 `integrity`가 없다.
  - bridge `_model_evidence`(`ui/ai_bridge.py:562-566`)는 key만으로 evidence를 찾고 현재 snapshot의 `integrity`/`eligible`을 보지 않는다.
  - 실행 직전 `recheck_whisper`(`_artifact_io.py:434-454`)는 **확인 당시 integrity 값을 그대로 넘겨** `whisper_snapshot`만 다시 계산한다. 관리 spec·pin 대조는 다시 하지 않는다.
- 반례 `probe_managed.py` B
  - 관리 설치를 pin과 MATCH로 확인했다.
  - 그 뒤 installed.json의 파일 하나의 다운로드 URL만 바꿨다. 여전히 verify를 통과하고 license id/url은 그대로다.
  - 현재 snapshot은 `INVALID`이고 표시는 `CHANGED_INVALID`(“변경됨 또는 검증 실패 — 실행하지 않습니다”)다. 그런데 key가 같아 `registry.evidence(current)`가 evidence를 돌려주고, `freeze`도 성공한다.
- 반례 B2: installed.json을 지워도 이미 받은 evidence의 `freeze`가 성공한다. 대기 Job의 실행 직전 재검사가 관리 판정을 보지 않는다.
- 영향
  - 계약 §3.1의 “CHANGED/INVALID → 해당 계획 실행 거부”와 §4.2의 “각 새 Job은 원 source를 다시 검사”가 관리 판정에서 우회된다.
  - 화면은 “실행하지 않습니다”인데 실행된다.
  - 실행 bytes는 사용자가 확인한 bytes와 같다. 따라서 다른 가중치 로드나 수동 강등은 아니다. 그래서 S2로 판정했다.
- 권고
  - bridge는 evidence 사용 전에 `art.eligible(snapshot)`을 요구하고, 현재 integrity가 evidence의 integrity와 같아야 한다. 또는 `integrity`를 key에 넣는다.
  - `recheck_whisper`는 MANAGED일 때 `managed_snapshot(manager, model_id, reference)`를 다시 계산해 MATCH를 요구한다.
  - A/R 가족에 “확인 뒤 installed.json만 변경·삭제” 행을 추가한다.

### G13R-03 · S2 · OPEN — bundle 복제가 녹음과 같은 기본 볼륨의 여유 공간·I/O를 확인 없이 쓰고, 실시간 전사는 Job마다 반복한다

- 근거
  - `freeze`는 `tempfile.mkdtemp(dir=None)`, 즉 `%TEMP%`에 load 입력 전체(model.bin 포함)를 복제한다. 여유 공간 확인은 없다.
  - 제품 전체에 디스크 여유 공간 정책이 없다(`disk_usage`·`GetDiskFreeSpace` 검색 0).
  - `OwnedSTT.open`은 Job마다 새 `LocalSTTProcess`를 만든다(G-P11b, Job 사이 warm cache 없음). 따라서 Job마다 원본 재hash 1, 복제 읽기·쓰기 1, seal 재검증 1, child 재hash 1이 추가된다.
  - 실시간 전사는 녹음 중 청크(`chunk_frames=96_000`)가 늘 때마다 다음 provisional Job을 만든다(`_live_tick`). 대형 모델은 녹음 내내 모델 크기만큼 TEMP 쓰기와 삭제를 되풀이한다.
  - 기본 라이브러리와 `%TEMP%`는 같은 시스템 볼륨이다.
- 영향
  - 녹음 경로와의 코드 결합은 없다. 별도 프로세스·스레드이고 recording writer를 호출하지 않음을 확인했다.
  - 대신 자원 결합이 새로 생겼다. 여유 공간이 모델 크기 근처이면 복제와 녹음 writer가 같은 볼륨에서 ENOSPC를 다툰다. 녹음 중 디스크 쓰기 부하와 SSD 쓰기량도 Job 수에 비례한다.
  - 불변식 “AI 실패/실행이 녹음을 중단시키지 않는다”를 자원 측면에서 검토하지 않았다. 측정도 0이다.
  - 계약 §5는 복제의 **자기** 실패(ENOSPC → RESOURCE_EXHAUSTED)만 다룬다.
- 권고(C00 결정)
  - (a) 복제 전 대상 볼륨 여유 공간이 “모델 크기 + 녹음 예비량” 미만이면 복제하지 않고 RESOURCE_EXHAUSTED로 닫는다.
  - (b) 복제 대신 원본 파일 자체에 같은 FILE_SHARE_READ guard를 걸고 identity·hash를 재대조하는 방안을 비교한다. 이 방안은 복제가 없고, 실행 중 원본 수정만 막힌다.
  - (c) 같은 실행·같은 evidence의 봉인 bundle을 실시간 Job 사이에 재사용할지 정한다. 모델 worker 재사용이 아니라 봉인 사본의 재사용이다.
  - 실측 게이트(녹음 중 실시간 전사 + 대형 모델)를 추가한다.

### G13R-04 · S3 · OPEN — 관리 snapshot의 MATCH가 hash한 bytes에 묶이지 않는다

- 근거: `managed_snapshot`(`_artifact_io.py:354-391`)은 `verified_spec`(파일별 size/hash 검증)과 `whisper_snapshot`(Whisper 입력 hash)을 **별도 읽기**로 수행한다. 그리고 entries를 spec 파일 hash와 대조하지 않은 채 `integrity=MATCH`를 붙인다.
- 반례 `probe_managed.py` C: 두 읽기 사이에 model.bin을 바꿨다. 결과는 `integrity MATCH`, snapshot model.bin ≠ spec, eligible True, 확인 후 표시 `MANAGED_PIN_MATCH`(“관리 설치 — 확인한 manifest와 파일 일치”)였다. freeze도 성공했고 bundle model.bin ≠ spec이었다.
- 영향: 사용자가 확인한 digest는 그 바뀐 bytes이므로 “확인 뒤 다른 bytes”는 아니다. 다만 “manifest와 일치” 표시가 사실과 다르다. 같은 폴더의 동시 쓰기가 있어야 생긴다.
- 권고: snapshot entries 각각을 spec의 같은 이름 FileSpec(size, sha256)과 대조하고, 다르면 INVALID로 한다. G13R-02와 같은 수정에서 닫을 수 있다.

### G13R-05 · S3 · OPEN — 라이선스 파일 처리 두 가지가 정상 모델을 막는다

- (a) 0바이트 `LICENSE`
  - `whisper_snapshot`은 크기 0인 license 파일을 terms에서 뺀다(`_artifact_io.py:343-345`의 `if size:`). 그런데 `freeze`의 입력 이름 집합 재대조(`_inputs` vs `_expected_inputs`, `:628-633`)는 그 이름을 센다.
  - 반례 `probe_managed.py` A: 확인은 기록되지만 `freeze`가 매번 `MODEL_CHECKSUM_MISMATCH/SOURCE_CHANGED`다. 사용자는 “모델이 바뀌었다”는 잘못된 안내를 받고 절대 실행할 수 없다.
- (b) 소문자 `license.txt`
  - loader 입력이 아닌 license 파일에도 정확한 대소문자를 요구한다(`:338-342`, `variants[0] != name`). 그래서 `CAPABILITY_UNSUPPORTED/NAME_CASE`로 모델 전체를 거부한다(`probe_vocab.py`).
- 권고: (a) 빈 license 파일은 snapshot과 재대조에서 같은 규칙으로 다룬다(둘 다 제외하거나 둘 다 포함). (b) license 이름은 casefold 일치를 허용하고, 실제 이름을 entry 이름으로 기록하거나 license digest에만 넣는다.

### G13R-06 · S3 · OPEN — 수동 Whisper에 LICENSE 파일이 있으면 “라이선스 원문 없음”으로 표시한다

- 근거: `Terms.license_state`는 파일만 있고 id/url이 없으면 `METADATA_ONLY`다. 수동 Whisper는 항상 id/url이 None이다. 그래서 `ui/models.py` 확인 화면은 `라이선스: 메타데이터만(라이선스 원문 없음)`이라고 쓴다. 그런데 바로 아래 줄에 `LICENSE · 22 bytes · SHA256 …`를 나열한다(`probe_display.py`).
- 영향: 같은 화면 안의 모순 표시다. 실행 자격과 상태 문구(“조건 미확인 — 사용자 책임”)는 맞다.
- 권고: “라이선스 파일 있음(SHA256 표시) — 식별자·URL 미제공, 조건 확인은 사용자 책임” 상태를 따로 둔다. 또는 수동 경로에서는 파일 유무를 문구에 반영한다.

### G13R-07 · S3 · OPEN — 임시 사본 정리 대기가 사용자·진단에 보이지 않는다

- 근거: 정리 실패는 worker 객체 속성 `bundle_cleanup_pending`에만 남는다. 제품 코드에서 이 값을 읽는 곳은 0이다. 계약 §5의 “삭제 실패는 ‘임시 모델 사본 정리 대기’로 남긴다”가 구현되지 않았다.
- 실측(`probe_guard.py`): 봉인 중 쓰기·삭제·이름 변경(파일·bundle 폴더·상위 폴더)은 거부된다. 자식 프로세스 읽기는 허용되고, 정리 후 원본은 그대로다. 그러나 봉인된 bundle 폴더 안의 **새 파일 생성은 허용**된다. 그런 파일이 하나 있으면 `close()`는 소유 이름만 지우고 `CLEANUP_PENDING`이 된다. 이는 남의 파일을 지우지 않는 안전한 동작이다.
- loader는 목록에 있는 이름만 읽으므로 새 파일은 실행 입력이 되지 않는다. 화자는 ONNX 외부 tensor를 거부한다.
- 영향: 고아 정리가 없는 상태에서 수 GB 사본이 남아도 알 길이 없다. G13R-03과 결합된다.
- 권고: 정리 대기를 Job/모델 패널 상태나 진단에 노출하고, 안내 문구를 계약대로 둔다.

### G13R-08 · S3 · OPEN(인계) — 확인 세대와 라이브러리 결속이 결선되지 않았다

- 근거: `ConfirmationRegistry.library_instance`는 실제 Library와 무관한 난수다. `new_generation()`의 제품 호출은 0이다.
- 현재 tree에는 실행 중 restore·import·라이브러리 전환이 없다. 새 실행은 새 `ModelPanel`이므로 지금의 결함은 아니다.
- C 가족의 restore 행은 시험이 `new_generation()`을 직접 호출하므로 이 결선을 검증하지 않는다.
- 권고: G-P09(실행 중 restore·import) 배정에 “restore·import·라이브러리 전환 때 `model_panel.confirmations.new_generation()` 호출, library_instance를 실제 Library 식별자로”를 인계 항목으로 넣는다.

### G13R-09 · S3 · OPEN — 시험 충분성의 구멍

- (a) `test_inference.py::test_missing_model_is_safe_child_failure_and_child_is_reusable`는 이름과 달리 이제 child 재사용을 보지 않는다. “load 단계 오류 뒤 같은 child 재사용” 대체 시험이 없다.
- (b) **변이 M24b 생존.** adapter가 `whisper_files` 검증 실패를 삼키고 빈 files로 loader를 부르도록 바꿨는데 신규 4파일, 관련 기존 4파일, provider 보안·STT 입력·runtime 독립 시험이 모두 통과했다. 실제 SDK에서는 빈 files가 원 경로나 Hub 분기로 간다. 다만 child의 `HF_HUB_OFFLINE`·`local_files_only` 때문에 네트워크는 없다. 위조 설명 시험은 `_check_model_files`의 MODEL_MISSING에서 먼저 멈춘다. 그래서 “bundle 대조 실패 → loader 0” 순서를 직접 보는 시험이 없다.
- (c) I 가족 queued의 `queued.evidence is evidence`는 대입 동어반복이다. bridge 수준에서 대기 Job이 접수 evidence를 유지하는지(현재 패널 확인으로 바뀌지 않는지)는 X-06이 `LocalSTTProcess`를 직접 부르는 형태로만 확인한다.
- (d) G13R-02·G13R-04 시나리오가 분모에 없다.
- (e) C의 Esc는 monkeypatch된 `QMessageBox.question`의 No이고, 세션 변경 축은 `processEvents()`뿐이다.
- (f) T27은 “처리한 청크 재전송 0·원격 key 불변”을 공개 경로로 관찰하지 않는다.
- (g) T22 결속은 Whisper load에만 있다. 화자 응답은 config의 manifest SHA를 되돌리므로 bundle 결속이 없다.
- (h) **변이 MX5 생존.** seal 직후 bundle 재검증(`_verify_bundle`)을 지워도 모두 통과했다. R 가족의 copy 시점 주입은 **원본**만 바꾸고, 복제 완료와 guard 획득 사이의 **bundle** 변경을 주입하는 행이 없다. 계약 §7.2가 요구한 copy→seal 경계 양쪽 barrier 중 한쪽이 비어 있다. 실제로는 child 재hash가 뒤에서 잡는 다중 방어다.
- (i) **변이 MX1 생존.** guard의 handle-이름 identity·reparse·link 대조를 지워도 통과했다. 위와 같은 창(복제 뒤 bundle 이름 치환)을 주입하는 시험이 없다. 이 역시 다중 방어로 덮인다(`check_path` hardlink 거부, 재hash).
- 권고: (a)·(b)·(d)에 시험을 추가한다. 나머지는 범위를 문서에 명시한다.

### G13R-10 · S3 · OPEN — 확인 화면과 계약 문구의 작은 불일치

- 확인 화면(`confirmation_text`)에 대상 폴더 경로가 없다. key는 root identity에 묶이지만 사용자는 어떤 폴더를 확인하는지 볼 수 없다. 늦은 preview나 bridge 상태가 화면을 바꿔도 구별할 수 없다(다른 bytes 실행은 아님).
- 계약 §6 표의 “adapter 우회 호출 → CAPABILITY_UNSUPPORTED, detail=MODEL_CONFIRMATION_REQUIRED”는 adapter·inference·process에서 주석으로만 있다. `ProviderError`에는 detail이 없다.
- 권고: 경로(또는 축약 경로)를 표시하고, detail을 문서와 맞춘다.

## 5. 결함 없음으로 확인한 사항

- **비로컬 경로(S0 후보)**: 26개 문자열을 drive type 3·4·0의 fake io로 시험했다. UNC, `//`, 혼합 구분자 `/\`·`\/`, `\\?\`, `\\.\`, `\\?\UNC\`, `\??\`, `C:rel`, `C:`, 상대, `\x`, ADS 세 형태, `\\localhost\C$`가 모두 **파일시스템 호출 0**으로 거부된다. 원격·불명 드라이브는 drive 조회 한 번 뒤에 거부된다. junction·hardlink는 실제 OS TEMP에서, symlink는 OS 응답 fake로 P 가족이 확인한다. `hash_file`·`whisper_files`·`diarization_files`도 각각 `local_path`를 먼저 부른다.
- **원본 무손상**: bundle 정리는 `mkdtemp`가 만든 폴더 안의 소유 이름만 지운다. 실패 경로도 같다. 사용자 원본·관리 모델·남의 파일 삭제 경로가 없다(실측 포함).
- **확인 우회(S1 후보)**: 확인이 없으면 `LocalSTTProcess._start`·`LocalDiarizationProcess._seal`·`FasterWhisperProvider._ensure_model`·`backend.compute`가 모두 자식 생성이나 loader 전에 거부한다. bridge는 STT·실시간·명시 계속·화자에서 Job을 만들지 않는다(X-02~05).
- registry는 메모리 전용이고, Yes·미선택 기본 확인란·보여 준 key 일치일 때만 기록한다. 늦은 응답은 token으로 거부한다. 관리 설치는 reference가 없으면 INVALID이고(T12), INVALID는 확인할 수 없다. 수동 채택은 별도 버튼이다.
- 화자는 `verified_bundle` 엄격 재검증 → 확인 snapshot 대조 → 같은 bytes seal → child 재hash 순서다. manifest·model·license hash와 ONNX 외부 tensor 거부가 그대로 유지된다.
- **변조·교체**: 확인 뒤 원본이 바뀌면 직전 재검사와 복제 대조가 거부한다. seal 뒤 원본이 바뀌어도 현재 실행은 옛 사본을 쓰고, 다음 Job이 거부한다. bundle 자체 변경은 Windows guard가 거부하고 child가 다시 hash한다. child 응답 digest가 다르면 load에서 MODEL_CHECKSUM_MISMATCH로 닫는다.
- **files 매핑**: 고정 SDK `WhisperModel.__init__`은 `files`가 비어 있지 않으면 경로·Hub로 가지 않는다. tokenizer bytes가 있고 preprocessor 기본 `b"{}"`가 truthy라 디스크 조회가 없다. 식별자는 경로가 아닌 bundle id다.
- **lease·ACK**: 복제·seal은 lease 안(`use()` → `check_facts` → `load` → `_start`)에서 한다. bundle은 child join 뒤에만 해제한다. ACK가 없으면(INFERENCE_/DIARIZATION_ACK_PENDING) 해제 전에 예외를 내서 봉인을 유지하고, G-P11c reaper의 재수거 때 해제된다(T23).
- **결과 키**: 로컬 STT는 `artifact_digest:device`다. trust·terms·root·세대·정책은 키에 없다. 업그레이드 시 연결 hash에서 canonical digest로 한 번 바뀐다. 옛 BLOCKED 로컬 STT의 명시 계속은 CONTINUE_PLAN_CHANGED이고 새 로컬 전사가 필요하다. 원격 전송·비용은 0이다. 원격·요약 경로의 config_key는 G-P13이 건드리지 않는다.
- **분모**: 수집 1,674 node. G13 ID 고유 집합은 A192·B72·C144·D48·I64·J64·K512·L100·P112·R144·T28(T01~T28 연속)·U180 = 1,660이고, 중복·누락·초과 0, 보강 X-01~06이다. B·T05의 digest oracle은 손으로 쓴 canonical JSON이고, J는 G-P07 표를 손으로 옮긴 것이다.

## 6. 놓쳤을 수 있는 영역

- 실제 faster-whisper·CTranslate2가 `files` 매핑(특히 model.bin reader와 `vocabulary.txt`)으로 실가중치를 읽는지는 보지 않았다. CT2 내부의 전체 메모리 복사, lazy read 수명, 대형 모델 복제 시간(600초 timeout 대비), RAM·디스크 peak도 외부 게이트로 남는다.
- guard의 ReFS·Dev Drive·FAT·exFAT 동작이 그렇다. Python 3.12+ `st_ino`가 128비트이면 `GetFileInformationByHandle` 64비트 index와 달라 GUARD_IDENTITY로 안전 측 실패할 수 있다. NTFS TEMP에서만 실측했다. `%TEMP%`가 네트워크 경로인 비정상 구성에서는 `freeze`가 복제를 쓴 뒤에야 `_verify_bundle`의 `local_path`가 거부한다.
- 같은 사용자 권한의 경쟁도 있다. 검사와 `os.open` 사이 component를 UNC symlink로 바꾸면 열기 전에 SMB 접근이 생길 수 있다. 이는 `_safe.py`가 명시한 협력 경계와 같다. guard 해제와 삭제 사이에 bundle 폴더를 junction으로 바꾸는 경쟁도 있다. `_remove_owned`는 삭제 전에 `check_path`를 하지 않는다.
- Qt 실제 키 입력의 Esc, 접근성 읽기 도구, Narrator는 보지 않았다.
- J 가족 기대값(G-P07 폐쇄 표)은 G13 계약 §개정 3의 표와만 대조했다. G-P07 계약 원문에서 다시 도출하지는 않았다.
- 변이는 작성자 29개를 재실행하지 않았다. 얇은 4개(M09·M24·M26·M27)와 내 변이 7개만 실행했다.
- G-P11 resource_catalog의 실제 profile, `ui/main.py`의 화자 manifest 위젯(범위 밖), 관리 모델 삭제 확인 창과 사용 중 guard의 상호작용(L 가족은 `shutil.rmtree`로 대체)은 깊게 보지 않았다.

## RECHECK 1 (FIX1)

상태: **재확인 완료 — OPEN S0 0 · S1 0 · S2 0 · S3 6**(이전 이월 2 + 새 4). 푸시를 막는 항목은 없다. 같은 검토자이고, 이 절만 추가했다. 위 본문은 바꾸지 않았다(직전 LF SHA-256 `f6ff6938…66d9`).

### R1. 대상·환경

- 대상 tree **`2d25249b556b4521cbf7e45e91dc2f1ce32af69f`**.
  - 구성: 현재 HEAD `f4f94b7`(G-P11d) + G-P13 29파일. `git diff f4f94b7 2d25249b`가 정확히 이 29파일이다.
  - 겹침: G-P11d의 7파일(`jobs/runner.py`·`models/resources.py`·문서 3·시험 2)과 G-P13 파일의 겹침은 0이다.
  - FIX1의 G-P13 변경: e447958c 대비 16파일이다. src 8, 시험 7, 계약 문서 1.
- 계약 문서: LF SHA-256 `daf3f2d2c6ad997dbdf35d0c106b1af5ffb74538470b53f0cc81ca97917b2905`(703행).
  - 직전 판(`3cc127dd…`, 471행)이 바이트 그대로 앞부분이다.
  - 승인 원문 40,538 bytes 해시는 `56dc2fef…`로 그대로다.
- 실행 환경
  - `build/review-trees/g13b`에 풀었다. PYTHONPATH와 `recoryn.__file__`은 사본 src이고, 변이 사본도 각각 그 src였다.
  - basetemp는 `C:\Users\gangd\AppData\Local\Temp\g13b-review-full-11332`다. 스크립트가 `\Temp\g13b-review-full-` 형식이 아니면 실행을 멈추도록 했다(지난번 사고 재발 방지).
  - 실제 모델·네트워크·GPU는 쓰지 않았다. 반례는 `build/review-trees/g13b-probe/`(probe_reuse·probe_ct2_vocab·mutate)에 있다. 기존 반례 5종은 `g13a-probe/*.py`를 바꾸지 않고 g13b src로 다시 돌렸다.

### R2. 실행 결과

| 검사 | 결과 |
| --- | --- |
| CI 동등 전체 회귀(§2와 같은 명령) | **27,036 passed**, failed·error·skip 0, 1,753.53초, coverage **92.48%**. 출력에 경고 줄이 하나도 없다 |
| `check_coverage.py` | 7묶음 PASS. domain 99.18/97.89, capture 99.85/98.57, jobs 99.20/95.65, storage 95.95/91.41, security 98.11/94.43, content 98.98/99.02, all 93.81/88.53 |
| 변경 모듈 coverage | artifacts 90.46 · _artifact_io 87.77 · adapters 94.83 · inference 82.20 · process 90.00 · backend 90.45 · ui/models 74.32 · ai_bridge 81.17 |
| ruff check / format --check | All checks passed / 211 files already formatted |
| `mypy src/recoryn scripts packaging` | no issues found in 95 source files |
| 신규 4파일 단독(`-W error::ResourceWarning`) | **1,690 passed, 30.62초**(60초 게이트 안) |
| case ID 감사(`--collect-only`) | 1,690 node. A192·B72·C144·D48·I64·J64·K512·L100·P112·R144·T28·U180 = 1,660, 중복 0, 보강 X-01~X-22 |

변이 재적용: 사본 `g13b-probe/mut`, 대상 8파일 1,870 node. 기준은 1,870 passed였고, 판정 규칙은 §2와 같다.

| ID | 결과 | 검출 node |
| --- | --- | --- |
| M24b | **KILLED 2**(FIX1 전 생존) | X-19, `test_inference` child 재사용 |
| MX5 | **KILLED 2**(FIX1 전 생존) | X-20, X-22 |
| MX1 | 생존(G-P13b 이관과 일치) | — |
| MX10 | KILLED 1 | T17 |
| MX11 | KILLED 4 | L-018·L-020·R-070·R-072 |
| MY7(새): `_retire`가 사용 중 사본도 닫음 | KILLED 2 | L-015·L-019 |
| MY9(새): `release_idle`이 사용 중 사본도 닫음 | KILLED 62 | L 가족 |
| MY8(새): `_sweep`이 교체·무효 판정 때 사용 중 사본도 닫음 | **생존** | — → G13R1-03 |
| MY1(새): `_sweep`이 무효 evidence의 대기 사본을 정리하지 않음 | **생존** | — → G13R1-03 |

### R3. 이전 지적 판정

| ID | 판정 | 근거 |
| --- | --- | --- |
| G13R-01 S1 | **CLOSED** | 아래 정리 참조 |
| G13R-02 S2 | **CLOSED** | probe_managed B·B2 재실행 |
| G13R-03 S2 | **CLOSED**(원 지적). 잔여는 G13R1-01 | 아래 정리 참조 |
| G13R-04 S3 | **CLOSED** | probe_managed C 재실행 |
| G13R-05 S3 | **CLOSED** | probe_managed A, probe_vocab |
| G13R-06 S3 | **CLOSED** | probe_display |
| G13R-07 S3 | **CLOSED**(원 지적). 잔여는 G13R1-02 | 아래 정리 참조 |
| G13R-08 S3 | **OPEN(인계)** | G-P09 인계(§FIX1 F5)에 `new_generation()`·실제 library 식별자·`release_idle()` 세 항목이 정확히 들어 있다. 코드는 바뀌지 않았다. G-P09 배정표 반영 전까지 이월 |
| G13R-09 S3 | (a)(b)(c)(d)(h) **CLOSED** · (e)(f)(g)(i) **OPEN(G-P13b 이관)** | 아래 정리 참조 |
| G13R-10 S3 | **CLOSED** | 확인 화면 둘째 줄에 `대상 폴더: <root>`가 있다(X-13). 확인 없음은 adapter·inference·process·backend 모두 `ArtifactError(..., "MODEL_CONFIRMATION_REQUIRED")`를 싣는다(X-18) |

- **G13R-01 근거**
  - probe_vocab: `vocabulary.txt` 폴더 snapshot OK, 소문자 `license.txt` OK.
  - 실제 SDK 확인(probe_ct2_vocab): 저장소 `scripts/compare_ctranslate2_builds.py`의 **무작위 가중치 합성 Whisper**(실모델 아님, CPU, CT2 4.9.0+recoryn.cpu1)로 시험했다.
    - `vocabulary.txt`만 있으면 폴더 로드도, `files` 매핑(bytes와 model.bin reader)도 그 어휘로 로드된다.
    - 따라서 §FIX1 F1의 "실제 CTranslate2가 files의 vocabulary.txt를 읽는지는 NOT_RUN"은 합성 가중치 수준에서 실행됐다. 실가중치는 여전히 외부 게이트다.
- **G13R-02 근거**: installed.json의 URL만 바꾸면 current INVALID·`CHANGED_INVALID`, same key False, evidence None이다. installed.json을 삭제하면 freeze가 `MODEL_CHECKSUM_MISMATCH/SOURCE_CHANGED`다. 실행 직전 MANAGED 재판정이 동작한다.
- **G13R-03 근거**
  - Job마다 원본을 재검사한 뒤 같은 evidence의 봉인 사본을 재사용하고, 복제 전에 공간 예비를 검사한다.
  - probe_reuse 6의 경계 실측: 100 GiB 볼륨은 정확히 같으면 OK, 1 byte 부족이면 `RESOURCE_EXHAUSTED/DISK_RESERVE`다. 4 GiB 볼륨은 1 GiB 하한이 적용되어 정확히 같으면 OK, −1이면 거부다. 10 GiB+9는 정수 나눗셈으로 정확히 같으면 OK다. 볼륨 조회 실패는 `DISK_UNKNOWN`이다.
  - 녹음 경로: `app/recording.py`·`app/desktop.py`·capture는 `_artifact_io`를 참조하지 않는다. `_reserve`의 호출자는 `freeze` 하나뿐이다.
- **G13R-04 근거**: 두 읽기 사이 변경은 integrity INVALID, eligible False, `CHANGED_INVALID`다. 이후 probe의 `freeze(None)` 예외는 확인이 기록되지 않은 결과로 기대대로다.
- **G13R-05 근거**: 0바이트 LICENSE는 license_files에 기록되고 freeze OK다. 소문자 license.txt OK다.
- **G13R-06 근거**: 이제 `FILE_ONLY`이고 화면 문구는 “라이선스 파일 있음(SHA256 표시) — 식별자·URL 미제공…”이다. 0바이트 LICENSE도 FILE_ONLY가 되지만 같은 화면에 `0 bytes`가 보이므로 별도 지적하지 않는다.
- **G13R-07 근거**
  - 정리 대기 표시: `cleanup_status`와 bridge tick이 표시한다(X-17·X-21).
  - 새 이름: seal 검증과 child 이름 목록 검사가 loader 전에 거부한다(X-16·X-22). probe_guard에서 남의 파일은 남는다.
  - 대기 사본에 대한 잔여는 G13R1-02.
- **G13R-09 근거**
  - (a) 실제 child 재사용 시험이 복원됐다.
  - (b) M24b KILLED.
  - (c) I 가족 queued가 제품 `OwnedSTT.open`/`OwnedDiarization.open`의 worker evidence를 본다.
  - (d) X-09~X-11.
  - (h) MX5 KILLED.
  - (e) Esc 실제 모달, (f) T27 공개 경로, (g) 화자 응답 digest 결속, (i) MX1은 §FIX1 F6의 근거가 타당하다. 모두 S3 시험 범위로 G-P13b에 이관됐다.

### R4. 새 코드 경쟁 확인(probe_reuse, 합성 TEMP)

1. **사용 중 원본 변경**: Job1이 사본을 쓰는 동안 원본이 바뀌었다.
   - 두 번째 Job은 `MODEL_CHECKSUM_MISMATCH/SOURCE_CHANGED`로 거부된다.
   - Job1의 사본은 봉인과 bytes를 유지한다.
   - Job1 release 뒤에도 사본은 표에 남는다(지연 폐기). 다음 획득 시도 때 같은 거부와 함께 닫히고 폴더도 삭제된다.
2. **사용 중 모델 삭제**(`release_idle`): 사용 중 사본은 유지되고 대기 0이다. release 뒤 `release_idle`에서 CLOSED되고 폴더가 삭제된다.
3. **사용 중 확인 교체**
   - 옛 사본은 봉인을 유지하고, 새 확인은 별도 사본을 만든다. 두 사본이 동시에 존재하며 각 복제는 예비 검사를 거친다.
   - 옛 사본은 release 뒤 새 확인의 다음 획득에서 CLOSED된다. 새 사본은 재사용된다.
4. **재검사와 사용자 수 증가 사이에 `release_idle`**: 옛 사본은 CLOSED되고 새 봉인 사본을 받는다. 닫힌 사본은 쓰이지 않는다.
5. **guard 해제와 정리 순서**: `close()`는 guard를 놓은 뒤 소유 이름만 지운다. 실패하면 `CLEANUP_PENDING`으로 대기 목록에 들어가고 `sealed`가 False가 되어 다시 쓰이지 않는다. 재시도는 획득·`release_idle` 때 같은 `close()`로 한다.
   - 사용 중 사본을 닫는 경로는 코드상 없다. `_sweep`·`_retire`·`release_idle`은 users==0일 때만 닫는다.
   - 실제 제품에서는 G-P11 owned-heavy lease가 단일 holder라 두 Job의 동시 획득이 생기지 않는다.

**vocabulary 두 파일 동시 존재(질문 3)**
- probe_ct2_vocab 실측 결과는 다음과 같다.
  - CT2는 두 파일이 다 있으면 `vocabulary.json`을 쓰고 `vocabulary.txt`는 무시한다. txt를 깨뜨려도 로드되고 생성 토큰은 json 쪽이다. 폴더 로드와 `files` 매핑 모두 같다.
  - json만 깨뜨리면 로드가 실패한다(`ValueError: vector too long`). txt로 fallback하지 않는다.
- 판정: FIX1의 `VOCABULARY_AMBIGUOUS` 거부는 **SDK 동작과 같지 않고 더 엄격한 G13 정책**이다. 다만 SDK가 쓰지 않는 파일을 확인 digest에 넣지 않으려는 안전 측 선택이라 결함은 아니다. 문서 근거 문구만 고친다(G13R1-04).

### R5. C00 결정에 대한 검토

- **(a) 사용자 0 뒤 봉인 사본 유지**
  - 실시간 Job마다 하던 복제·삭제(쓰기)가 사라지는 효과는 맞다. probe_reuse와 X-15로 확인했다.
  - 질문 “녹음 볼륨 공간을 실행 내내 점유하는 것이 녹음 공간 부족을 앞당기나”에 대한 답은 **그렇다**이다. 최대 모델 크기만큼, 대기 기간 내내 앞당긴다.
    - 예비 검사는 **복제 시점에만** 한다. 대기 사본은 여유 공간이 줄어도, 실시간 전사가 꺼져도, 녹음이 시작돼도 풀리지 않는다.
    - 사본이 풀리는 것은 교체·무효·원본 변경 뒤 다음 획득, 모델 삭제, bridge 종료 때뿐이다.
    - 예: 한 번 로컬 전사를 쓴 뒤 같은 실행에서 STT 없이 장시간 녹음하면, 그 기간에 3 GiB급 사본이 녹음 볼륨을 계속 차지한다.
    - 2트랙 48 kHz PCM은 시간당 약 1 GB라 대략 3시간 분량이다.
    - 이 실행 중 crash가 나면 그 사본은 고아로 남는다. 고아 정리는 아직 없다.
  - 승인 자체는 타당하다. 다만 대기 사본 해제 조건이 필요하다(G13R1-01).
- **(b) 확인 key 9필드(integrity)**: 동의한다. K 가족 8축을 유지하고 integrity 축은 X-09가 본다. 작성자 F04 KILLED와 내 probe B로 행동을 확인했다. `ConfirmationKey.integrity`의 기본값 MATCH는 제품 경로가 항상 `registry.key()`로 채우므로 영향이 없다.
- **(c) 2트랙 writer 처리량**: G-P13 범위 밖이라는 데 동의하고 G-P17b 이관에 동의한다.
  - §FIX1 F2의 표에서 AI 없는 run에도 거부(0~590)가 나고, 조건보다 run 순서와 동시 부하를 따른다. 복제 I/O 영향은 이 측정으로 판정할 수 없다는 작성자 결론이 맞다.
  - 1트랙은 모든 조건에서 0이다.
- **(d) coverage 결합 단계의 `SQLITE_CORRUPT`·`ResourceWarning`**: **재현되지 않았다.**
  - 같은 PC, 단독 실행의 같은 tree 전체 회귀에서 경고 줄이 0이다. §2의 e447958c 실행에도 없었다.
  - 판단: 시험 종료 뒤 병렬 coverage 데이터 결합에서 강제 종료된 자식의 데이터 파일이 깨진 동시 실행 부산물이다. 작성자 기록상 python 프로세스 12개가 동시 실행 중이었다. 제품·시험 결함으로 보지 않는다.
  - 근거: 경고는 실패 0의 결합 단계에서만 났고, `-W error::ResourceWarning`이 시험 본문에는 걸리지 않았다.
  - CI에서 재발하면 그때 조사한다.

### R6. 새 지적

#### G13R1-01 · S3 · OPEN — 대기 봉인 사본이 녹음 볼륨 여유 공간과 무관하게 실행 내내 남는다

- 근거: `_artifact_io.release`는 사용자 수만 줄이고 사본을 유지한다. `_reserve`는 `freeze`(새 복제)에서만 호출된다. 대기 사본 해제는 `_sweep`(다음 획득)·`_retire`·`release_idle`(모델 삭제·bridge 종료)뿐이다.
- 영향
  - 위 R5 (a)와 같다. 최대 모델 크기만큼 녹음 가능 공간이 줄고, crash 시 고아가 된다.
  - 녹음 경로 코드 결합은 여전히 없다. 조건은 디스크가 거의 찬 경우로 한정된다. C00가 승인한 trade-off의 잔여라 S3로 둔다.
- 권고
  - 대기 사본(users 0)은 bridge tick에서 사본 볼륨의 `free < 예비량`이면 `release_idle()`로 푼다. 이 검사는 녹음 경로가 아니라 AI 쪽 tick이다.
  - 실시간 전사가 꺼지거나 일정 시간 쓰이지 않으면 푸는 조건도 비교한다.
  - 시험: fake `disk_usage`로 대기 사본 해제 행 1개를 추가한다.

#### G13R1-02 · S3 · OPEN — 대기 사본에 남의 이름이 생기면 그 확인의 로컬 실행이 실행 내내 막힌다

- 근거: 재사용 경로 `acquire`는 **원본**만 재검사하고, 봉인 사본의 이름 목록은 다시 보지 않는다. child의 `_exact_listing`은 매번 `BUNDLE_CHANGED`로 거부하는데, 부모는 그 사본을 폐기하지 않는다.
- 반례 probe_reuse 5: 대기 사본 폴더에 `stray.tmp`를 만든 뒤 세 번 획득했다. 세 번 모두 같은 사본을 받고, 세 번 모두 `MODEL_CHECKSUM_MISMATCH/BUNDLE_CHANGED`였다.
- 확인 버튼은 이미 확인된 snapshot에서 꺼져 있어 사용자가 다시 확인할 수도 없다. 재시작·모델 삭제(`release_idle`, 남의 파일 때문에 `CLEANUP_PENDING`)·원본 변경 뒤에만 풀린다.
- 안전 측 실패이고(다른 bytes 실행 0), 같은 사용자 권한의 쓰기가 있어야 생긴다.
- 권고: 재사용 직전에 `_exact_listing(bundle.directory, 소유 이름)`(listdir 1회)을 하고 다르면 `_retire`한다. 또는 child의 `BUNDLE_CHANGED` 응답 때 그 record를 폐기한다. 시험 행 1개를 추가한다.

#### G13R1-03 · S3 · OPEN — 재사용 수명 규칙 두 갈래가 시험되지 않는다(변이 MY8·MY1 생존)

- MY8: `_sweep`이 교체·무효 판정 때 **사용 중** 사본도 닫게 바꿔도 1,870 node가 모두 통과한다. “쓰는 Job이 있는 동안 어떤 경로도 사본을 닫지 않는다”의 이 갈래는 지금은 단일 lease holder라 제품에서 도달하지 않는다. 그러나 모듈 보장이 시험되지 않았다. probe_reuse 3이 정상 동작을 보였을 뿐이다.
- MY1: 무효 evidence(새 실행 세대)의 대기 사본을 다음 획득에서 정리하지 않게 해도 통과한다. G-P09가 `new_generation()`을 붙이면 도달한다. 인계 항목의 `release_idle()` 호출이 함께 들어가면 덮인다.
- 권고: X 행 2개를 추가한다. 하나는 사용 중 옛 확인 + 새 확인 획득 → 옛 사본 봉인 유지이고, 다른 하나는 `new_generation()` 뒤 다른 확인 획득 → 옛 대기 사본 CLOSED다.

#### G13R1-04 · S3 · OPEN — vocabulary 동시 존재 거부와 외부 게이트 문구를 실제 SDK 동작에 맞춘다

- 근거는 R4의 실측이다. 두 파일이 다 있으면 CT2는 json만 쓰고 txt를 무시한다.
- §FIX1 F1은 load 입력을 “둘 중 하나만”이라 쓰고 근거로 SDK를 든다. 거부는 SDK 동작이 아니라 G13 정책이다. 또 “files의 vocabulary.txt 읽기는 NOT_RUN”은 합성 가중치 수준에서 실행됐다.
- 권고(문서만)
  - “둘 다 있으면 SDK는 json을 쓰고 txt를 무시한다. G13은 쓰이지 않는 입력을 확인 digest에 넣지 않으려고 거부한다”로 정정한다.
  - 외부 게이트를 “실가중치·실모델 파일 목록”으로 좁힌다.
  - 사용성을 바꾸고 싶다면 대안이 있다. 둘 다 있을 때 txt를 digest·사본·매핑에서 빼고 json만 쓰는 방식이며, C00 결정 사항이다.

### R7. 이번 재확인에서 보지 않은 것

- 작성자 변이 60개 전체는 재실행하지 않았다. 내 변이 5개 재적용과 새 변이 4개만 실행했다.
- §FIX1 F2의 녹음 처리량 측정은 재현하지 않았다. 표와 결론만 검토했다.
- 실가중치 `files` 로드(대형 model.bin reader), 대기 사본의 수 GB 실측 점유, ReFS·FAT TEMP, 실제 모달 Esc·Narrator는 여전히 외부 게이트·이관 범위다.
