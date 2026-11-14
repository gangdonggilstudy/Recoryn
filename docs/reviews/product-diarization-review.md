# BR41 선택 화자 구분 독립 검토

검토자 R11/B11, 작성자 R13/B22. 2026-11-14. 상태: **REVIEW_READY / BR41-01 S2 RECHECKED, root CLOSED 후보**. B22 제품 소스는 읽기 전용으로 대조했고 신규 쓰기는 이 문서와 `tests/integration/test_diarization_independent.py`뿐이다. R11의 B23 패키징 자기 승인과 분리한다. 실제 weights·음성·모델 inference·daemon·네트워크·계정 변경은 수행하지 않았다.

## 최초 snapshot과 발견

AGENTS/onboarding 읽기 순서의 설계·협업·품질·제품/코어 계약/결과, R00의 BR41 추가 배정, `diarization.md`, B22 7개 runtime과 unit/contract를 읽었다. 최초 9개 대상 hash는 B22 제출표와 일치했다. 최초 `process.py` SHA256은 `A035FA671B755F7C7C8785C7CB00A00679122923FF5CB91597D5BDD207AC4C42`였다.

### BR41-01 · S2 · 최초 OPEN — 종료 ACK 중 취소/close/기한 초과 뒤 성공 반환

위치: `LocalDiarizationProcess.diarize`의 decoded reply → `_check` → `return result` → `finally: _reap` 순서. 성공 reply를 먼저 해석하고 `_reap`의 소유 child 종료 ACK를 기다리는 사이 external cancel, instance close 또는 deadline이 바뀌면 후단 재검사가 없어 `complete=True`가 반환됐다.

독립 fake Process의 `join`을 정확한 barrier로 사용해 세 경계를 각각 실행했다. fake PID는 OS에 전달하지 않고 Guard도 독자 fake다. 실제 파일은 작은 합성 WAV뿐이다. 최초 독립 **20 PASS / 3 FAIL**였으며 세 실패는 `test_result_during_child_cleanup_respects_cancellation_and_deadline[cancel/close/deadline]`다. 실패를 skip/xfail 처리하거나 원 oracle를 완화하지 않았다.

해결 조건: reply는 owned child/handle의 종료 ACK 전에는 임시 결과다. ACK 후 external cancel/closed/deadline을 재검사하고 취소/기한 초과를 complete로 반환하지 않아야 한다. ACK 실패의 예외·소유 핸들 보존도 유지한다. R13/root에 반례를 전달하고 R13이 제품 코드를 수정했다.

### BR41-01 · RECHECKED

수정 `process.py` SHA256: **9060D883F8C6DC35C2B5B2EB0B4135D4D6D684B2BDFC7FBC1D078E209C75A0CC**. 반환 직전 `_reap()` → `_check(execution, deadline)`을 추가한 실제 코드를 대조했다. 원 cancel/close/deadline 세 반례 모두 각각 `complete=False`, `CANCELLED/CANCELLED/TIMEOUT`을 반환한다. child/guard/reply 정리 순서와 핸들 ACK도 그대로 검사했다. root가 이 근거를 최종 통합해 CLOSED를 판정한다.

## 독립 대조 경계

| 경계 | 직접 검증한 근거 |
| --- | --- |
| 선택 import/capability | 새 interpreter의 meta-path guard가 onnx/sherpa/numpy/onnxruntime import를 금지한 채 package import·구성·capabilities를 허용한다. absent model 파일은 생성/읽지 않고 model_state=not_checked, quality=NOT_RUN을 유지한다. |
| 로컬 bytes·license | 중복 manifest key, 고정 hash 뒤 바꾼 모델/동봉 license, 올바른 hash를 가진 공백 license를 모두 거부한다. 입력은 실제 ONNX weights가 아닌 canary bytes다. |
| 외부 tensor | optional package 없이도 5깊이 × external_data/data_location **10개 fake oracle**를 필수 실행한다. 설치된 ONNX 1.23.2 protobuf parser에는 initializer/attribute graph/sparse/function/training 5경로의 metadata-only synthetic message를 전달해 외부 tensor를 거부하고 marker를 지운 대조군은 통과한다. 모델 엔진에는 전달하지 않는다. |
| core/optional 분리 | Python<3.12 또는 ONNX 미설치/버전 미지원에서는 실제 parser oracle를 명시 N/A로 분리하고 capability 미지원/미설치 차단을 assert한다. pytest skip이 아니며 parser 통과로 계산하지 않는다. fake 10개는 어느 경로에서도 유지한다. 이번 Windows/Python3.13.1 환경은 ONNX1.23.2가 설치돼 실제 parser 5경로를 모두 실행했다. |
| 불변·범위·익명 | 합성 턴의 중복 합집합 coverage 80%/81% oracle, track 분리, 순차 두 화자 모호성, user_assertion/unresolved 비승격과 원문·시간·provenance·ID 불변을 검사했다. parent byte reply의 audio/manifest hash·track·시작/끝·bool 완료·부분 턴·추정 표시 위반을 모두 거부한다. |
| gate | production `_worker`를 closed gate/precancel로 호출할 때 compute·모델 파일 접근·reply를 시작하지 않는다. gate 허용 대조군에서만 독자 fake compute가 실행되며 실제 모델은 요청하지 않는다. |
| Windows Job parent death | 테스트가 생성한 supervisor와 child를 base Python으로 직접 실행한다. supervisor가 guard를 attach한 뒤 종료되면 정확한 owned child handle이 signaled이고 별도 소유 bystander는 생존한다. cleanup은 이 테스트의 handle/Popen만 사용하며 PID 탐색·다른 세션 종료는 없다. |
| 제품 spawn executable | production provider의 spawn/Job/ACK 경로에서 worker body만 fake로 대체한다. 자식의 실제 PID와 provider PID가 같고 `QueryFullProcessImageNameW`가 `sys._base_executable`과 일치한다. `spawn.get_executable()`의 venv 문자열만으로 launcher 문제가 제품에도 있다고 판단하지 않는다. |

Windows venv redirector는 추가 interpreter를 만들 수 있어 ACTIVE_PROCESS_LIMIT=1 fixture에 부적합할 수 있다. R00 지시에 따라 parent-death fixture는 존재를 확인한 base exe를 직접 사용했다. 최초 fixture 결과로 launcher의 기존 descendants 전체 종료를 주장하지 않으며 최종 direct-base 실행과 제품 spawn image 관측을 근거로 삼는다.

## 실행·한계

Windows / Python3.13.1 / 고유 TEMP, cache provider 비활성, ResourceWarning 오류 처리. B22 자체 결과를 복사하지 않고 독립 시험을 실행했다. 증분 확장 시점 B22/BR41/B23/BR42 결합 **179 PASS / 0 FAIL / 0 SKIP**였고, gate 대조군 추가 후 최종 결과는 후단에 기록한다. 초기 23건에 강화 시험 수를 더해 중복 집계하지 않는다.

```powershell
$br41Temp = Join-Path $env:TEMP ('recoryn-br41-' + [guid]::NewGuid().ToString('N'))
.venv/Scripts/python.exe -m pytest tests/integration/test_diarization_independent.py tests/unit/test_diarization.py tests/contract/test_diarization_contract.py -q -p no:cacheprovider --basetemp $br41Temp -W error::ResourceWarning --tb=short
.venv/Scripts/python.exe -m ruff check tests/integration/test_diarization_independent.py
.venv/Scripts/python.exe -m ruff format --check tests/integration/test_diarization_independent.py
$env:MYPYPATH = (Resolve-Path src).Path
.venv/Scripts/python.exe -m mypy src/recoryn/diarization tests/integration/test_diarization_independent.py
```

공식 대조: [sherpa2.0.1 Python binding의 callback·config](https://github.com/k2-fsa/sherpa-onnx/blob/v2.0.1/sherpa-onnx/python/csrc/offline-speaker-diarization.cc), [ONNX1.23.2 bytes parser](https://github.com/onnx/onnx/blob/v1.23.2/onnx/__init__.py), [Windows Job 할당 권한](https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-assignprocesstojobobject). fake SDK 통과를 native 모델 호환성이나 실제 segmentation/embedding 품질로 확대하지 않는다. 라이선스 법률 판단·모델 공급망 진위·native 전체 egress 관측·실제 음성/DER·GPU·nested Job 모든 환경·frozen/clean VM·G3/G4는 NOT_RUN이다.

현재 BR41 범위 원 발견 **1/1 RECHECKED, OPEN S0/S1/S2 0건**, 제품 전체 승인과 R11 패키징 승인은 아니다.

## 최종 증분 실행

gate 3대조군 추가 후 BR41 **37 PASS**, 작성자 B22 55건과 함께 **92 PASS**이며 B23/BR42까지 포함한 결합은 **182 PASS / 0 FAIL / 0 SKIP / 7.49s**였다. Ruff check/format PASS, packaging/script/tests와 B22/BR41을 지정한 strict mypy **20파일 PASS**다. 실제 ONNX parser 5개를 이번 환경에서 모두 실행했고 필수 fake 10개도 통과했다. 원 세 취소 oracle의 assertion은 유지했다. 후속 B21/패키징 작성 변경은 이 BR41 승인 범위가 아니다.

최종 독립 시험 SHA256: `01EB5B929FE870D02F62304CFA2AB59463CA090ADF347FCA3452B3E5621EF8BD`.
