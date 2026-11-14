# BR30 모델 설치·런타임 독립 검토

검토자 B14 / 작성자 B10. 2026-11-14. **체크포인트 3건 및 후속 helper 6건 RECHECKED, 지정 검토 범위 미해결 0건**. 아래 최초 실패·중간 OPEN은 이력이며 최신 판정은 마지막 재확인 절과 digest를 따른다. B14가 작성한 gateway/privacy guard는 R13의 별도 독립 검토 근거를 연결한다. 제출 상태는 **REVIEW_READY**이며 전체 제품 최종 승인은 오케스트레이터 책임이다.

## 범위와 실행 조건

AGENTS, onboarding, workflow, assignments, product-contracts, quality-system, product-results와 models/*, app/inference.py 및 model/inference 유닛 시험을 읽었다. 실제 시험은 합성 파일·fake HTTP backend·제가 생성한 자식 프로세스만 사용했다. 사용자 모델/daemon/키/음성·실제 모델 추론·외부 서비스/다운로드는 사용하지 않았다. 통합 fixture가 DNS/연결 접근을 금지한다.

쓰기 허용 결과는 이 문서, [체크포인트 독립 시험](../../tests/integration/test_model_runtime_independent.py), B10이 추가 승인한 [후속 Ollama 시험](../../tests/integration/test_ollama_runtime_independent.py)이다. 제품 코드·공용 파일·Git 인덱스는 수정하지 않았다. 마지막 Ollama 파일은 이번 stage/체크포인트에서 제외하며 core 시험은 그 모듈을 import하지 않는다.

## 최초 발견과 수정 재확인

처음 10개 반례는 **4 PASS / 6 FAIL**이었다. 실패를 skip/xfail 처리하지 않고 수정자에게 전달했다. 최초 manager.py SHA-256은 `b4667b420c882cd51710123e2ba317e6ad529584d4ca0ac12bc7718084e095ad`, inference.py는 `5616d643a09214bd3017e8873d37bb9992261dc4a731e5b50c204b9ac68eadcc`다.

### BR30-01 · S1 · RECHECKED — manifest 밖의 파일이 활성 모델에 혼입

- 최초 위치: ModelManager.install/verify. 승인 manifest의 파일만 hash 검사한 뒤 staging/files 전체를 rename하여 미등재 파일을 포함할 수 있었고 verify도 이를 정상으로 표시했다.
- 반례: staging/files에 미등재 preprocessor_config.json(canary)을 미리 두고 정상 model.bin manifest를 설치한다. 미검증 파일이 target에 활성화된다. 설치 후 같은 파일을 추가해도 verify가 성공했다. 추가 파일이 실제 backend에서 실행·사용됐다고 주장하는 반례는 아니다.
- 최초 시험: test_manifest_unlisted_artifact_cannot_be_activated_or_verified[partial/installed] **2 FAIL**.
- 새 코드 확인: 활성화 전과 verify에서 _verify_file_set을 호출하여 승인 파일/설치 receipt 및 필요한 부모 디렉터리 외 파일·디렉터리를 거부한다. 모든 기존 항목의 링크/reparse/hardlink를 검사하고 4096개/32깊이 제한을 둔다.
- 재확인: 원 2반례 PASS. reject 시 target 미생성, 정상 설치·정확 prefix 재개는 유지된다. 이 검사도 동일 사용자 권한으로 경로를 동시에 갈아끼우는 공격에 대한 OS sandbox 보장은 아니다.

### BR30-02 · S2 · RECHECKED — 설치 manifest의 미래 schema를 허용

- 최초 위치: ModelManager.verify. installed.json의 spec은 검사하지만 외부 schema_version을 확인하지 않았다.
- 반례: 정상 설치 receipt에서 schema_version만 99로 바꿔도 verify 성공. 최초 **1 FAIL**.
- 새 코드 확인: schema(data)와 정확한 {schema_version,spec} key 집합 검사 후 spec/파일 검증으로 진행한다.
- 재확인: 미래 버전·필드 누락·bool 버전·미지 필드 4경우 모두 ValidationError로 거부하며 원 receipt를 변경하지 않는다. 손상/미지원 계약을 정상 설치로 승격하지 않는다.

### BR30-03 · S2 · RECHECKED — 비유한 timeout이 실행 기한을 무력화

- 최초 위치: LocalSTTProcess.__init__의 timeout<=0 검사.
- 반례: NaN/Infinity/bool을 수락했다. NaN은 deadline 비교가 참이 되지 않아 timeout 경로를 보장할 수 없었다. 실제 무한 모델을 실행한 것이 아니라 생성자 수락으로 재현했다. 최초 **3 FAIL**.
- 새 코드 확인: bool/숫자 외 타입/비유한 값을 거부하고 0<timeout<=86400을 적용한다.
- 재확인: 원 3반례 PASS. 별도의 실제 소유 hung child에서 finite timeout 및 취소가 ProviderError를 반환하기 전에 프로세스 object의 종료 신호가 관측되는지도 PASS다.

## 추가 통과 경계

- 승인 없는 install은 downloader 호출 0·root 미생성이다. 마지막 수신/progress 경계에서 취소하면 활성 target이 없으며, 다음 명시 재개는 받은 전체 prefix를 재다운로드하지 않고 hash 검사 후 설치한다.
- 부분 수신 후 license/source/hash를 변경하면 PLAN_MISMATCH로 새 요청 전에 거부한다. 크기·SHA는 artifact 무결성이고 manifest 게시자의 진위나 라이선스 법률 판단은 아니다.
- 실제 기본 HTTP backend에 fake HTTPSConnection을 주입해 full/resume, redirect, 무시한 Range, 잘못된 Range 시작, gzip 응답을 확인했다. GET 1회, 정확 Range, 직접 지정 origin, proxy 환경 미사용, 임의 인증 header 없음, 성공/오류 모두 close다. 외부 endpoint에는 접속하지 않았다.
- 소유 hung inference child는 fake worker이며 weights를 import/로드하지 않는다. timeout/cancel 후 Windows process handle이 종료 신호 상태이고 LocalSTTProcess의 자식 참조도 해제된다.
- 별도 소유 supervisor가 실제 production idle worker를 spawn하되 inference 요청은 보내지 않는다. supervisor를 강제 종료한 뒤 parent watcher가 worker를 종료하는 것을 열린 Windows handle로 관측했다. 실패 cleanup도 이미 열어 둔 해당 소유 process handle만 대상으로 하며 PID/프로세스 이름 전체 검색·무차별 종료를 하지 않는다.
- 관측 API의 ABI와 종료 ACK 판정은 Microsoft [OpenProcess](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-openprocess), [WaitForSingleObject](https://learn.microsoft.com/en-us/windows/win32/api/synchapi/nf-synchapi-waitforsingleobject), [TerminateProcess](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-terminateprocess) 정본에 대조했다. 이 OS 수명 시험은 오디오 장비/GPU/실모델 검증이 아니다.

## 재확인 snapshot과 명령

| 파일 (`src/recoryn/` 기준, 시험은 저장소 기준) | SHA-256 |
| --- | --- |
| models/manager.py | 069267e584a5f4cf31b18f79b459083542d92ea6a7024c9277d81804a469a343 |
| app/inference.py | a41b3be2d4d283ed9a37566ca80d96447cd03ff2df3b83f83b3fa865c537c0bb |
| tests/integration/test_model_runtime_independent.py | 07ea8440e0269b4dd37019657cb2548692ad8d24e28fb8a17c8c72e9e9efe9f7 |

Windows / Python 3.13.1 / .venv. 체크포인트 독립 **22 PASS**, model/inference 유닛 포함 **52 PASS**, skip/xfail 0, ResourceWarning을 오류로 처리했다. Ruff lint/format 및 MYPYPATH=src mypy PASS. 위 64자리 digest는 실제 파일 바이트와 프로그램 비교했다.

```powershell
$br30Run = Join-Path $env:TEMP ('recoryn-br30-' + [guid]::NewGuid().ToString('N'))
.venv/Scripts/python.exe -m pytest tests/unit/test_models.py tests/unit/test_inference.py tests/integration/test_model_runtime_independent.py --basetemp $br30Run -p no:cacheprovider -q --tb=short -W error::ResourceWarning
.venv/Scripts/python.exe -m ruff check tests/integration/test_model_runtime_independent.py
.venv/Scripts/python.exe -m ruff format --check tests/integration/test_model_runtime_independent.py
$env:MYPYPATH = 'src'
.venv/Scripts/python.exe -m mypy tests/integration/test_model_runtime_independent.py
```

## 명시적 후속 범위

ManagedOllama Windows Job/owned-process 종료·bind/readiness·attestation의 실제 프로세스 수명 결합 및 UI 연결은 작성 중이므로 **미검증**이다. 로컬 manifest/blob 합성 fixture 5경우는 로컬 준비 시험에서 통과했지만 별도 파일로 보존하고 이번 checkpoint 증거 수에는 넣지 않았다. 실제 daemon·cloud-disabled 후속 egress·실모델 품질·weights 라이선스·다운로드 origin TLS의 live 동작·모든 G3/G4는 NOT_RUN이다. 작성 중 helper 부재를 이미 고친 3건과 합쳐 통과 처리하지 않는다.

## R14 재부팅 후 복원 및 Ollama 후속 독립 검토

2026-11-14, R14/B14. 상태 **REVIEW_READY — helper 수정 요청**. 앞선 BR30-01~03의 checkpoint RECHECKED 판정은 유지하며, 이 절의 새로운 helper 발견과 합쳐 완료로 표시하지 않는다. 제품 코드는 root/B10 소유로 수정하지 않았다. 작성 결과는 이 문서와 `tests/integration/test_ollama_runtime_independent.py`뿐이다.

온보딩 읽기 순서와 2026-11-14 재개 표를 확인했다. 기존 staged/unstaged/untracked 변경을 보존했다. BR11 alignment, BR23 consent/gateway/privacy, BR24 jobs/runner/content, BR30 manager/inference의 실제 파일 SHA-256이 각각 후단 RECHECKED 표와 일치했다. 지정 BR14/BR24/BR30 checkpoint 및 기존 Ollama manifest fixture를 재실행하여 **65 PASS**를 확인했다. P0.1의 과거 379개를 현 전체 회귀로 재사용하지 않는다.

Herdr 환경은 `HERDR_ENV=1`이고 현재 CLI skill/help 및 agent/pane/workspace 명령을 읽었으나, root 대상 get/read 및 w5 pane 조회가 elevated server의 `PermissionDenied / os error 5`로 거부됐다. root에 직접 메시지를 전달한 것으로 기록하지 않는다. 권한·서버 설정·pane을 변경하지 않고 이 저장소 결과와 채팅으로 보고한다. 제품 실패 8건과 이 인프라 실패를 분리한다.

### BR30-04 · S1 · OPEN — 시작 성공이 owned endpoint readiness를 증명하지 않음

- 위치: `ManagedOllama.start`. 임시 bind로 얻은 포트를 닫고 `Popen` 직후 1시간 유효 proof를 발급한다. 자식 poll, bind/listen 준비, 실제 응답 및 endpoint 소유권 확인이 없다.
- 독립 재현: fake Popen이 이미 exit=17인 프로세스를 반환해도 start가 proof를 반환한다. 별도 fake는 살아 있지만 어떤 listener도 만들지 않는데 start가 역시 proof를 반환한다. `test_start_cannot_attest_exited_or_unready_process[exited/no_listener]` **2 FAIL**.
- 위험: 실행 파일이 없거나 서버 준비에 실패한 상태를 로컬 검증 완료로 승격한다. 예약 socket close→server bind 사이 다른 listener로 바뀔 수 있는 창도 정적 검토에서 확인했다. 실제 포트 탈취·외부 전송을 실행한 것은 아니다.
- 수정 조건: 기존 공개 API를 가능한 보존하면서 finite deadline/취소 가능한 준비 절차를 수행하고, 예상 model/digest와 owned endpoint의 준비를 확인하기 전 proof를 발급하지 않는다. 다른 PID/listener나 잘못된 응답을 readiness로 수락하지 않아야 한다. 실패 시 owned tree를 회수하고 재시작 가능 상태를 남긴다. bind 확인은 listen 응답과 동일하지 않다.

### BR30-05 · S1 · OPEN — Windows descendant가 close ACK 뒤 생존

- 위치: `ManagedOllama.start/close`. 직접 자식의 terminate/wait/kill만 사용하고 Windows Job에 의한 owned tree 수명 관리가 없다.
- 독립 재현: Popen만 주입해 Ollama 대신 Python sleeper parent를 실행하고 그 parent가 다른 Python sleeper를 만든다. owner.close 뒤 직접 parent는 종료되지만 descendant의 열린 Windows handle은 3초 후에도 `WAIT_TIMEOUT(258)`이다. `test_close_terminates_owned_descendant_before_ack` **1 FAIL**.
- 관측과 정리: fake parent가 보고한 정확한 PID를 parent 생존 중 OpenProcess(SYNCHRONIZE|PROCESS_TERMINATE)로 열어 유지했다. 실패 후 바로 그 handle만 TerminateProcess/WaitForSingleObject/CloseHandle로 정리했다. 프로세스 이름 검색·사용자 daemon·다른 세션 종료는 없다. 자식은 모델을 읽거나 소켓을 열지 않는다.
- 수정 조건: owned Windows Job 등의 검증된 tree 경계에 runner를 포함하고, runner가 descendant를 만들기 전 소유권 설정을 보장한다. 종료 ACK는 전체 owned tree 종료 관측 뒤에만 한다. parent 비정상 종료와 Job 할당 실패도 fail-closed여야 한다. 사용자 소유/shared daemon은 종료 대상이 아니다. parent crash 자체는 이번 반례에서 실행하지 않았다.

### BR30-06 · S1 · OPEN — 보관된 proof가 owned process 종료 뒤 dispatch를 허용

- 위치: `LocalModelAttestation`, `providers/_common.py`의 local proof 검증, `ManagedOllama.close/attestation`의 연동 경계. DTO는 endpoint/model/hash/cloud flag/만료 시각만 고정하며 owner의 현재 수명과 연결되지 않는다.
- 독립 재현: start의 proof를 `ProviderConfig(execution_location='local')`에 고정한 후 owner.close 또는 fake 자식 exit=17을 적용한다. 실제 OllamaSummarizer에 fake Gateway를 주면 각각 1회 dispatch에 도달한다. `test_frozen_proof_cannot_dispatch_after_owner_lifetime[closed/exited]` **2 FAIL**. 같은 DTO의 시간 만료 대조군은 dispatch 0건으로 PASS다.
- 위험: UI의 getter 재확인만으로 이미 worker에 고정한 proof의 종료/교체 race를 막을 수 없다. 포트가 재사용되면 새로운 listener에게 콘텐츠를 넘길 수 있는 권한 판단 창이 남는다. 실제 네트워크 전송이나 원격 listener는 사용하지 않았다.
- 수정 조건: root가 frozen plan과 owner generation을 dispatch 직전 검증하는 계약을 확정해야 한다. 다른 owner/generation/종료된 proof는 철회 후 재grant와 관계없이 거부하며, 이미 허용한 바이트의 잔여 위험은 구분한다. model/readiness UI 배선만으로 종결하지 않는다. B13 provider 공용 계약 변경이 필요하면 root가 소유권을 조정한다.

### BR30-07 · S2 · OPEN — 발급 뒤 모델 파일 변경을 getter가 감지하지 못함

- 위치: `ManagedOllama.attestation`. process poll/TTL만 확인하고 모델 경로 및 verified artifact의 동일성을 다시 검사하지 않는다.
- 독립 재현: 정상 합성 manifest/blob으로 proof 발급 뒤 manifest 또는 blob을 `changed-after-proof`로 교체한다. getter가 여전히 원 proof를 반환한다. `test_model_mutation_invalidates_live_attestation[manifest/blob]` **2 FAIL**.
- 수정 조건: 실제 런타임이 읽는 artifact snapshot과 proof를 결합한다. 재검증 또는 불변 소유 snapshot 등으로 검증 후 파일 변경을 탐지/차단하고 새 digest는 새 proof/계획을 요구한다. 단순히 manifest hash를 기존 DTO에 남기는 것으로는 충분하지 않다. 같은 사용자 악성 코드와의 모든 경로 교체 race에 대한 OS sandbox를 요구하거나 주장하는 것은 아니다.

### BR30-08 · S2 · OPEN — 종료 오류 뒤 getter가 여전히 proof를 제공

- 위치: `ManagedOllama.close`. terminate 예외가 `_attestation=None`보다 먼저 발생한다.
- 독립 재현: fake terminate가 OSError를 내고 poll은 계속 running을 반환하게 한다. close 실패 뒤 `owner.attestation()`이 proof를 반환한다. `test_termination_error_cannot_leave_attestation_usable` **1 FAIL**.
- 수정 조건: 종료 의도부터 proof를 무효화하고 종료 미확인 자식 handle은 안전한 재시도용으로 보존한다. 종료 실패를 완료로 표시하거나 handle을 버려서는 안 된다. 정상 close, timeout→kill→wait 및 반복 close 대조군은 현재 PASS다.

### 실행 결과와 수정자 인계

후속 helper 독립 시험 **36개: 28 PASS / 8 FAIL, skip/xfail 0**. 실패한 8개 assertion은 위 5개 발견에 대응한다. 초기 fixture 작성 중 Summarizer 인자 오류는 시험 코드에서 수정했으며 제품 발견으로 세지 않았다. 이후 타입·lint·format 검사를 통과한 fixture로 다시 재현했다.

후속 최초 재현 snapshot SHA-256:

| 파일 (저장소 상대 경로) | SHA-256 |
| --- | --- |
| src/recoryn/models/ollama.py | d38d20c77fb0c6b668e92d4f3c28ade50f9814f06bb80bc93f6dda50353cf651 |
| src/recoryn/providers/_common.py | 14733236f8e52edea435ae407976248e6d010274980e569ad62137a6ad8e2184 |
| src/recoryn/providers/contracts.py | 289df70e55e625f551d9384bec7073b4e20b362c702d870f7f51246c31890251 |
| tests/integration/test_ollama_runtime_independent.py | 6f86ac3131d8ddeaadadf7e3cea9d6096c1252d9cac4a6abc2adeb308a873723 |

추가 PASS 경계는 생성자 무부작용, 잘못된 실행 경로·누락/손상 모델·cloud 모델 이름의 bind/spawn 전 거부, 미래/중복 JSON·잘못된 digest/size/config 거부 및 원본 미변경, 미설치 모델 자동 fetch/디렉터리 생성 없음, launch 실패의 미게시, 정확한 host/models/no-cloud 및 proxy 제거, 별도 동의 없는 loopback/remote Gateway 요청의 DNS 전 차단, 중복 start 거부, 정상/kill fallback 종료와 getter 무효화다. 환경변수와 Gateway 정책 관측이 외부 daemon 후속 egress의 OS 격리를 입증하지는 않는다.

```powershell
$r14Run = Join-Path $env:TEMP ('recoryn-r14-helper-' + [guid]::NewGuid().ToString('N'))
.venv/Scripts/python.exe -m pytest tests/integration/test_ollama_runtime_independent.py --basetemp $r14Run -p no:cacheprovider -q --tb=short -W error::ResourceWarning
.venv/Scripts/python.exe -m ruff check tests/integration/test_ollama_runtime_independent.py
.venv/Scripts/python.exe -m ruff format --check tests/integration/test_ollama_runtime_independent.py
$env:MYPYPATH = 'src'
.venv/Scripts/python.exe -m mypy tests/integration/test_ollama_runtime_independent.py
```

root/B10 수정 후 readiness/Job 주입 seam이 바뀌면 fixture를 실제 새 API에 맞추되, 같은 의미의 음성 없는 원 반례와 독립 handle oracle를 유지한다. 사전 합의 없는 새 API 부재를 제품 결함으로 추가 집계하지 않는다. start의 cancel/timeout은 아직 공개 인자가 없으므로 실제 취소 가능한 준비 절차 검증은 후속으로 남긴다. 실제 daemon·실모델·다운로드·vault·유료 호출·G3/G4는 계속 NOT_RUN이며 전체 제품 G1/G2 승인도 아니다.

## R00 수정 후 새 seam 재확인 및 남은 descendant ACK

이 절이 helper 후속 범위의 최신 기록이다. 앞선 28 PASS/8 FAIL과 그 당시 API·hash는 최초 이력으로 보존한다. root가 `OwnedServer`, `listener_matches`, 선택 `cancel`, 유한 `startup_timeout` 및 `LocalModelAttestation.execution_guard`를 확정했다. 독립 fixture는 Popen 주입에서 이 명시 seam으로 옮겼다. fake OwnedServer는 pid/job_handle/poll/close만 제공하며 listener fake는 새 Job 인자를 받는다. 실제 프로세스 시험은 생산 `OwnedServer`의 CreateProcessW(SUSPENDED)→Job assign→ResumeThread→close를 그대로 실행하고, 명령 payload만 Python 합성 코드로 바꾼다. 검증 목표를 fake close로 낮추지 않았다.

초기 native 수정에서 Job active=0 뒤 root handle이 아직 미신호이면 즉시 STOP_ACK_PENDING이던 반례는 실제 프로세스와 독립 fake kernel 모두에서 재현했다. root가 남은 deadline으로 root handle을 기다린 뒤 두 반례 중 false pending 경계는 해소했다. 해당 중간 `_owned.py` SHA-256은 `507a0ab805c0f8794a8f1279816ed92c5baa225c22d32d68cbbc58f4abea16e0`이다. 시험 cleanup도 이미 종료 진행 중인 프로세스에 TerminateProcess를 무조건 성공 assertion하던 부분을 교정해 원 제품 예외를 가리지 않게 했다. 시험 작성 중 syntax/import 오류는 교정했으며 제품 결함으로 집계하지 않는다.

| 기존 발견 | 현재 재확인 |
| --- | --- |
| BR30-04 | **RECHECKED**. exited/no-listener 반례 거부, 유한 timeout 및 시작 전/준비 중 취소의 미게시·owned cleanup PASS. 실제 OS loopback listener의 PID/port, 다른 PID, 잘못된 table/address/state/port 및 OS 조회 실패를 독립 확인했다. Job descendant listener는 해당 private Job에서만 수락하며 별도 빈 Job은 거부한다. 확인 범위는 OS listen 준비이며 실제 Ollama API 응답·실모델 추론 준비는 NOT_RUN이다. |
| BR30-05 | private Job의 descendant 종료 및 parent-death 수명 구현을 확인했다. 실제 supervisor를 kill하면 native owned parent/descendant handle 모두 5초 내 신호다. 다만 성공 close의 즉시 descendant ACK는 아래 BR30-09 때문에 아직 최종 RECHECKED로 닫지 않는다. |
| BR30-06 | **RECHECKED**. root DTO/require_endpoint의 managed execution guard로 보관된 proof의 close/death/expiry 후 fake Gateway dispatch가 0건이다. 실제 송신 단위 보호에 필요한 B14 작성 gateway/privacy는 R13이 별도로 독립 검토했다([BR23 후단](product-egress-review.md)). R14가 자기 보안 작성분을 승인한 것이 아니다. |
| BR30-07 | **RECHECKED**. manifest/blob/executable 변경과 listener 소유 상실은 getter 및 고정 proof guard에서 거부한다. 시작 때 hash 검증, 실행 때 dev/ino/size/mtime/ctime identity 검사이며 대형 weights 재hash를 write lock에 넣지 않는다. 동일 권한 공격자의 stamp 조작·경로 교체에 대한 OS sandbox 보장은 아니다. |
| BR30-08 | **RECHECKED**. close 오류 전 proof를 revoke한다. fake close 실패/ACK_PENDING 뒤 getter·고정 proof를 차단하고 소유 process 참조를 보존하며 정상화 후 명시 cleanup retry가 성공한다. 이전 generation proof의 거부가 새 proof를 무효화하지 않는 대조군도 PASS다. |

### BR30-09 · S1 · OPEN — 성공 close 뒤 descendant handle의 종료 ACK 미완료

- 최신 안정화 snapshot의 `_owned.py`는 Job active=0 이후 **root handle만** bounded WaitForSingleObject하고 성공한다. 위 중간 false pending 오류와 다른 반례다.
- 시험: `test_close_terminates_owned_descendant_before_ack`. native owned parent가 Python sleeper descendant를 생성하고, parent 생존 중 정확한 descendant handle(SYNCHRONIZE|PROCESS_TERMINATE)을 확보한다. `owner.close()`가 성공 반환하고 parent.poll()!=None임을 확인한 바로 뒤 `WaitForSingleObject(descendant,0)`을 검사한다. 기대 0, 실제 258(WAIT_TIMEOUT)이다. OS Job 회계 active=0을 모든 개별 process handle의 신호와 같은 관측으로 취급할 수 없다는 재현이다.
- 최초 단독 새 seam 실행은 **63 PASS**였다. 이어 coverage를 포함한 확대 묶음은 **293 PASS / 1 FAIL**, 실패는 이 즉시 ACK assertion 한 개다. 관련 제품/시험 9파일의 digest는 실행 전후 동일했다. 간헐 실패를 성공한 실행만으로 덮어쓰지 않는다.
- 수정 요청: 종료 직전 private Job의 정확한 member handles를 확보하고 해당 owned descendants의 bounded signal ACK까지 확인하는 등, 성공 응답이 실제 종료 확인과 일치하도록 보강한다. 어떤 프로세스가 여전히 미신호/확인 불가인지 fail-closed로 보존하고 handle을 잃지 않아야 한다. 다른 Job·사용자 프로세스의 이름 검색이나 무차별 종료는 금지한다.
- cleanup은 열린 그 handle의 종료를 먼저 1초 기다리고, 계속 살아 있으면 같은 handle에만 TerminateProcess를 요청한 뒤 5초 내 신호를 확인한다. 정리의 추가 terminate 호출 여부는 별도 로그로 수집하지 않았다. physical power failure, 모델 취소 지연 및 사용자 daemon은 시험하지 않았다.

이 실패가 난 최신 9파일 snapshot:

| 파일 (저장소 상대 경로) | SHA-256 |
| --- | --- |
| src/recoryn/models/ollama.py | 4aa33de2ba562da872a3eae2dd2c7ff771ff1efc0d69a802585676572dd43e54 |
| src/recoryn/models/_owned.py | 48cf0b513b79f97cf1c93b8bcfdecbe7d4ee2c75502b5a60ef11a3e555f484b1 |
| src/recoryn/providers/contracts.py | 07325cf5f0d9273ded8b49b23664fad1e83ad992476688ed1e641a306a28357b |
| src/recoryn/providers/_common.py | 72c3fd838a3369c0c45fd848ffeade5c617dc9820e4ec3a573d1d98cac4ffb23 |
| src/recoryn/security/gateway.py | b98a134f9deaef3730ec6d4593be4ad6c2f82f27be40db524443935db9536983 |
| src/recoryn/ui/privacy.py | 285cd7561da2ae401a2f1c3857dcedf0a03e0bfd6f0185717b4b7ae6f0c4c1dc |
| tests/integration/test_gateway.py | ecffa64f29049532729b9d44983d06ce6ff9ef0d702095078353219bf31e0032 |
| tests/ui/test_privacy_ui.py | e229bf311b2a0999d3a91f5f159c91de6087dcbb2a4ab5c29b1e101bca2e3a0d |
| tests/integration/test_ollama_runtime_independent.py | 9a102c080ddfa7cd96b6474fece0e05c0384e8ae47fe9f697b0c71f58a67cba7 |

실제 확대 검증 명령:

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
$r14Final = Join-Path $env:TEMP ('recoryn-r14-final-' + [guid]::NewGuid().ToString('N'))
$env:COVERAGE_FILE = $r14Final + '.coverage'
$r14Cov = $r14Final + '-coverage.json'
.venv/Scripts/python.exe -m pytest tests/unit/test_security.py tests/unit/test_diagnostics.py tests/integration/test_gateway.py tests/ui/test_privacy_ui.py tests/integration/test_egress_independent.py tests/integration/test_provider_security_independent.py tests/integration/test_publication_independent.py tests/integration/test_model_runtime_independent.py tests/integration/test_ollama_runtime_independent.py --basetemp $r14Final -p no:cacheprovider -q --tb=short -W error::ResourceWarning --cov=recoryn.security --cov-branch --cov-report=term --cov-report="json:$r14Cov"
```

위 실패 확대 실행의 coverage는 security line **869/878=98.97%**, branch **223/232=96.12%**다. coverage 수치가 helper의 실패를 상쇄하지 않는다. 실제 관측 artifact는 TEMP의 `recoryn-r14-final-66f50e03a6aa44c5b9157a465e5ef3bf-coverage.json`이며 원본/비밀을 포함하지 않는다. Microsoft [TerminateJobObject](https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-terminatejobobject), [QueryInformationJobObject](https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-queryinformationjobobject), [WaitForSingleObject](https://learn.microsoft.com/en-us/windows/win32/api/synchapi/nf-synchapi-waitforsingleobject)의 상태 조회/대기 계약을 대조했다. 실제 ACK 실패 판정은 위 독립 Windows handle 관측을 근거로 한다.

### B14 guard 작성 범위와 독립성

R00이 명시 재배정한 `security/gateway.py`, `ui/privacy.py`, `test_gateway.py`, `test_privacy_ui.py`를 추가 작성했다. Gateway의 선택 dispatch_guard 기본 None과 for_session 보존, consent→ledger→owner lock 순서, open/각 write/최종 반환 guard를 적용했다. hook entry/exit 오류를 안전하게 가리고 write 후 오류와 예외 suppression에서도 UNKNOWN·비용 exposure를 유지한다. PrivacyPanel은 고정 config/proof/endpoint/data types를 closure로 묶고 base guard도 보존한다. worker가 GUI에서 새 proof를 읽지 않는다.

작성자 자체 관련 묶음 **177 PASS**, 변경 4파일 Ruff/format/mypy PASS다. 후속 확대 실행에서 R13의 새 독립 13건이 추가되어 이 관련 부분은 **190 PASS**이며, 중복되는 수치를 합산하지 않는다. R13의 별도 기록은 **독립 43 PASS / 관련 92 PASS, 추가 발견 0건**이며 위 gateway/privacy/DTO 4제품 digest와 일치한다. 최종 통합·push 권한은 root에만 있다. 현재 R14 상태는 **REVIEW_READY — BR30-09 수정/동일 검토자 재확인 필요**, 제품 전체/공식 릴리스 승인 아님이다.

## BR30-05/09 최종 수정 후 동일 검토자 재확인

수정자 R00/B10, 재확인자 R14/B14. root는 close 직전 JobObjectBasicProcessIdList(class 3)를 조회하고 해당 private Job membership을 확인한 정확한 descendant handles를 유지한다. TerminateJobObject 뒤 active=0, 각 보존 descendant handle의 신호, root handle의 신호를 확인한 뒤에만 닫는다. ACK_PENDING이면 보존 handle과 Job/process 참조를 남겨 명시 재시도를 허용한다. 모델/비공개 사용자 process를 검색·종료하는 기능이 아니다.

- **BR30-05 RECHECKED:** 실제 native owned parent→descendant의 close 성공 직후 열린 descendant handle을 `WaitForSingleObject(handle,0)`로 확인하여 즉시 0을 관측했다. 이전 3초 기다림 oracle보다 강화한 즉시 ACK oracle를 유지했다. 별도 supervisor 강제 종료의 private Job child/descendant 신호도 확인했다.
- **BR30-09 RECHECKED:** 원래 coverage 확대 실행의 실패 조건을 유지한 채 재실행하여 통과했다. 새 독립 fake kernel은 Job active=0/root signaled 상태에서도 descendant handle이 258이면 close가 ACK_PENDING이고 handle을 버리지 않음을 확인한다. 신호 도착 후 같은 handle로 retry가 성공하며 OpenProcess를 다시 하지 않는다. foreign membership·OpenProcess 접근 실패도 성공으로 표시하지 않는다. class 3가 추가되며 기존 fake가 class 1 accounting만 가정했던 AttributeError는 빈 PID 목록 응답을 넣어 교정했으며 제품 실패로 집계하지 않는다.

현재 helper 독립 **66 PASS**. security/diagnostics/gateway/privacy 및 BR14·BR23·BR24·BR30 checkpoint를 함께 실행한 지정 묶음은 **297 PASS / 13.67s, skip/xfail 0**이다. 위 coverage 포함 명령을 그대로 다시 사용했으며 고유 TEMP basetemp와 `-p no:cacheprovider -W error::ResourceWarning`을 유지했다. 앞선 293 PASS/1 FAIL을 지우거나 같은 snapshot의 통과로 재분류하지 않는다. 수정 후 security는 line **869/878=98.97%**, branch **223/232=96.12%**로 목표 95%/90%를 충족한다. 새 artifact는 TEMP의 `recoryn-r14-final-aabc7ba3763d4d1db537d2921816ca7c-coverage.json`이다.

실행 전후 10파일(앞선 9파일 + R13 독립 시험)의 SHA-256 map이 프로그램 비교로 모두 동일했다. 앞선 9파일 표 중 변경된 두 파일과 추가 독립 시험의 최종 값은 다음과 같으며 나머지 7개는 그 표와 동일하다.

| 최종 변경/추가 snapshot | SHA-256 |
| --- | --- |
| src/recoryn/models/_owned.py | 71d2cd7013e397e6d17d60d9e391276de3498e22ebd28c594ce43d464ce3551f |
| tests/integration/test_ollama_runtime_independent.py | 25f4b6afd4545d1eb825479e5a9d82d56bebb6228631220f84d91652a9ae6113 |
| tests/integration/test_egress_independent.py | 1efeab64296eb6ca7b0c3624467945c1c553b5d166ef93a34a6806ec3e696990 |

작성/변경한 Python 5파일 `security/gateway.py`, `ui/privacy.py`, `test_gateway.py`, `test_privacy_ui.py`, `test_ollama_runtime_independent.py`의 Ruff check/format 및 MYPYPATH=src mypy 모두 PASS다. 최종 작성 파일은 이 다섯 파일과 이 리뷰 문서의 **6개**다. models/*, app/inference.py, providers/*, assignments.md 및 Git 인덱스는 R14가 수정하지 않았다.

BR30-01~09는 지정 범위에서 RECHECKED이며 남은 OPEN S0/S1/S2는 0건이다. 보안 작성분은 위 R13의 독립 검토를 근거로 연결하며 R14 단독 승인이 아니다. **R14 제출 상태는 REVIEW_READY**다. 실제 Ollama daemon/API 응답·weights/모델 품질·음성 캡처·다운로드·실계정/vault·유료 호출·daemon 후속 egress와 G3/G4는 계속 NOT_RUN이다. 전체 오프라인 회귀, 통합 codefreeze·commit·원격 push 및 제품/릴리스 판정은 root의 후속 작업이다.
