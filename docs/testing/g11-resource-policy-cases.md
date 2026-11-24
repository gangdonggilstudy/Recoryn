# G11 / G-P11 요약 장치 정책·모델 메모리·자원 lease 계약안

상태: **C00 수정 승인 반영본 — 구현 시작 신호 대기, 제품 구현·신규 시험·mutation 미실행**. 작성자 w5:p8 Codex. 이번 쓰기는 이 문서 하나다. 최초 계약안 LF SHA-256은 `0f98183f55ab0b1959902a67e7afce1a69db105b975b05f896841e927c8d7e0f`였다. 이 판은 REMOTE의 장치 정책 제외·profile UNKNOWN 실행 허용·두 push 단위 결정을 반영한다. 독립 검토와 최종 통합은 별도다.

## 1. 정본·범위·순서

- 정본: `v1-gap-plan.md`의 G-P11/F-RES02·F-RES01, G01-B G01B-031·030, 교차 검토 G01BR-04·03, architecture의 자원 관리·고정 ExecutionPlan, L-P07 GPU 런타임 계약과 결과.
- 원 보고의 S1은 통합에서 **S2로 조정**됐다. 원본·게시·전송 사고를 이번에 관측했다는 뜻은 아니다. CPU 무동의 전환, 미상 GPU를 정상으로 표시, 실제 종료 전 재할당은 고위험 부정 시험으로 검증한다.
- 구현은 **G-P02·G-P06·G-P07 push 뒤 C00 신호**로 시작한다. G-P07 선행인 G-P04/P05와 G-P03의 게시 변경도 최종 tree에 포함돼야 한다. 착수 때 공유 `app/ai.py`·`ui/ai_bridge.py`·G-P07 오류 표와 최종 해시를 다시 고정한다.
- 순서는 **G-P11a 정책 admission → G-P11b 메모리·lease·priority·worker 수명**이다. 두 단위의 파일·의미 행·mutation 배분은 §10.1에 고정한다. P11a만으로 메모리/수명 gap까지 완료됐다고 보고하지 않는다.
- 네트워크·장치·모델·계정·vault·패키지 작업은 수행하지 않는다. 시험은 fake probe/source/model/process/transport만 사용한다. 모델별 실제 profile 추가와 실제 GPU 측정은 별도 근거/승인이 필요하다.

## 2. 직접 확인한 현재 경로

소스 조사 시 HEAD는 `21a58bfa99c3ab4a381b92a092d5981adc5c9632`다. 작업 트리에 G-P02/G-P04 변경이 섞여 있어 아래는 읽기 조사이며 정확한 최종 tree의 완료 증거가 아니다.

| 근거 | 현재 사실 | 변화 |
| --- | --- | --- |
| `ui/ai_bridge.py` 전사 준비 | probe 상태를 버리고 GPU0·고정1GiB로 choose. LocalSTTProcess를 runner의 heavy lease 이전에 만들 수 있음 | 모델/profile·관측 상태·UUID/논리 index 전달, 모델 생성은 lease 뒤 |
| 같은 파일 summarize | main.device_policy를 읽지 않고 provider 준비/요약 접수 | 준비 전 static 정책 검사와 실제 dispatch 직전 재검사 |
| 같은 파일 diarization | CPU-only provider도 전역 장치 정책 없이 접수, 기존 scheduler.acquire 사용 | CPU capability와 정책 대조, 공통 ResourceRequest/lease |
| `models/resources.py` | UNKNOWN/UNAVAILABLE/OBSERVED probe,512MiB GPU headroom, 한 heavy lock 존재. CPU RAM·profile·priority 없음 | 불확실성 보존·RAM/VRAM admission·lease 사실 |
| `app/ai.py` | STT/요약 task에서 공통 scheduler.acquire. runner worker는1개 | 입력/정책 snapshot→priority queue→실제 자원 획득→모델 생성 순서 |
| `app/inference.py`, `transcription/adapters.py` | worker는 device만 전달, adapter의 device_index 인자 없음 | 선택한 CUDA ordinal·정밀도 전달, 로드 객체 사실 대조 |
| `diarization/contracts.py`·`backend.py` | config.device는 cpu만 허용, sherpa 실행 provider도 cpu | GPU_ONLY에서 사전 차단. GPU 화자 구분을 새로 구현하지 않음 |
| `summarization/adapters.py` | Ollama num_ctx/num_predict 등 요청은 있으나 strict GPU/offload 통제 없음 | /api/ps 관측·옵션·로컬 egress proof를 GPU 강제 증거로 승격하지 않음 |

L-P07 결과 문서에는 고정 runtime 설치/활성화와 무작위 base 가중치의 GPU 실행 확인이 있다. 실제 Whisper weights의 전체 GPU 전사·다른 GPU/driver·장시간 메모리 상한은 같은 증거가 아니다. **이 문서는 L-P07 수치를 재측정하지 않았고 이를 메모리 profile 숫자로 사용하지 않는다.**

## 3. 장치 정책·서버 admission

### 3.1 정책 의미와 backend 표

GPU_ONLY/CPU_ONLY는 **이 PC의 모델 추론 자원**에 대한 약속이다. 기존 전처리·tokenization·제어 CPU 작업까지 없다는 뜻이 아니다. 적용 대상의 `GPU_WITH_CPU_FALLBACK_ALLOWED`만 CPU/GPU 둘 다 허용한다. REMOTE 클라우드는 세 정책 모두 장치 정책 적용 대상이 아니다. 한 번의 요청은 준비 시 선택한 정책과 적용 여부를 불변 snapshot으로 갖고, UI 선택 변경은 새 요청에 적용한다. 대기/실행 중인 작업에는 캡처한 정책을 표시하며 바꾸려면 명시 취소/재접수한다.

현재 세 가지 사용자 대상 위치 외에 실제 화자 backend를 구별하기 위해 **LOCAL_SHERPA**를 별도 case 축에 포함한다. CT2로 화자 구분이 된다고 가정하지 않는다.

| backend / 지원 작업 | CPU_ONLY | GPU_ONLY | GPU_WITH_CPU_FALLBACK_ALLOWED |
| --- | --- | --- | --- |
| LOCAL_CT2 / STT | cpu 강제+§4의 known/UNKNOWN 분기 | cuda 강제+§4의 메모리/runtime/identity 조건 | 검증 GPU 우선, 아니면 CPU 조건 충족 시만 CPU |
| LOCAL_SHERPA / 화자 | cpu 강제+§4의 known/UNKNOWN 분기 | RESOURCE_GPU_UNSUPPORTED | CPU 조건 충족 시 CPU |
| OLLAMA / 요약 | 현재 RESOURCE_POLICY_UNVERIFIED | 현재 RESOURCE_POLICY_UNVERIFIED | server_unknown으로 실행 가능, 별도 위치/동의/비용 guard 필요 |
| REMOTE / 해당 provider가 지원하는 STT·요약 | 장치 정책 적용 제외, 별도 동의/비용 guard | 장치 정책 적용 제외, 별도 동의/비용 guard | 장치 정책 적용 제외, 별도 동의/비용 guard |
| 그 밖의 작업/backend 조합 | CAPABILITY_UNSUPPORTED | CAPABILITY_UNSUPPORTED | CAPABILITY_UNSUPPORTED |

**C00 결정: REMOTE는 정책 세 종류 모두 장치 정책만으로 차단하지 않는다.** UI 문구는 “원격 실행 — 이 PC의 장치 정책 적용 안 됨”이다. 이 PC의 GPU·RAM 관측, 로컬 runtime·profile·identity 실패를 원격 요청의 차단 근거로 사용하지 않는다. provider 지원 기능·G-P02 동의·G-P06 비용 등 독립 guard는 그대로 적용한다. endpoint 문자열만으로 REMOTE/OLLAMA를 바꿔 우회하지 않고 등록한 provider/backend identity로 구별한다.

**OLLAMA는 로컬 loopback을 포함해 CPU_ONLY·GPU_ONLY에서 사전 차단**한다. fallback 허용 정책에서만 server_unknown으로 실행한다. 차단 화면에는 “AI 실행 정책에서 GPU_WITH_CPU_FALLBACK_ALLOWED를 명시 선택한 뒤 새 요청” 방법을 안내한다. 기본 CPU_ONLY와 기존 요청의 snapshot을 자동 변경하지 않는다.

Ollama의 `num_gpu`, /api/ps/응답의 GPU 비율, endpoint가 localhost라는 사실, `LocalModelAttestation.cloud_disabled`는 **사전 GPU-only/CPU-only 강제 증거가 아니다**. 공유 Ollama나 사용자 서버를 probe/취소 때문에 종료하거나 재시작하지 않는다. 장치 보장을 얻으려고 새 네트워크 조회를 하지 않는다. backend의 static 강제/적용 제외 계약은 소스에 고정한 표에서 얻고 서버의 자기 주장으로 바꾸지 않는다. 이번 단위는 strict Ollama 강제 프로토콜을 구현하지 않는다.

### 3.2 준비·접수·실행 경계

- 신규 `ResourceRequest`를 STT/요약/화자의 **제품 접수 API에 필수**로 전달한다. UI만 검사하고 직접 AIService 호출이 우회하는 경로를 허용하지 않는다. 모델 family·정책·입력 envelope·runtime/profile identity·priority·선호 GPU를 frozen 값으로 받는다. 누락을 고정1GiB·GPU0·임의 CPU로 보충하지 않는다.
- UI는 provider/backend/정책만 읽는 static 검사부터 한다. strict Ollama·미지원 작업은 **privacy.prepare_execution·키 읽기·비용 예약·provider 호출 전에** 거부한다. REMOTE의 장치 정책 적용 제외는 privacy/cost 준비를 건너뛰는 허가가 아니다. 준비 실패는 G-P07의 “실행 준비 차단·작업 미접수”이며 가짜 Job을 만들지 않는다.
- 입력 revision·동의/비용/요청 context는 G-P02/G-P06/G-P07 계약대로 한 snapshot을 준비한다. 자원 재관측 때문에 UI 값·endpoint·모델·grant를 다시 조합하지 않는다.
- 이미 QUEUED라면 G-P07 block_pending, RUNNING attempt라면 fail의 사유 표를 사용한다. dispatch/각 실제 추론 직전 요청의 backend 정책을 재검사하고, owned 경로만 profile/runtime identity와 lease를 재검사한다. Ollama의 사후 CPU/GPU 관측으로 사전 허용을 소급하지 않는다. REMOTE에는 로컬 모델 lease를 요구하지 않는다.
- 자원/정밀도 변경이 입력·모델·의미 설정을 바꾸면 G-P07의 CONTINUE_PLAN_CHANGED/새 Job을 따른다. 명시 fallback 정책 안에서 같은 입력·모델·의미 설정을 유지한 최초 장치 선택은 메모리 profile 부재만으로 막지 않는다. 같은 Job의 후속 장치 변경은 새 Attempt와 같은 의미 설정/fence를 요구하며, 알려진 profile의 호환 제한이 있으면 지킨다. 메모리 UNKNOWN을 검증된 의미 호환으로 표시하지 않는다. priority나 free memory 값은 semantic 설정 키에 넣지 않는다. G-P03 selection/settings CAS를 건드리지 않는다.

## 4. 모델 메모리 근거·관측·배정

### 4.1 offline profile

신규 `models/resource_catalog.py`는 실행 중 네트워크/임의 파일 로드가 없는 고정 catalog와 canonical digest를 제공한다. backend 강제 계약과 모델 메모리 profile을 구별한다.

| profile 필드 | 의미 |
| --- | --- |
| model_identity | 고정 모델 artifact/manifest digest. 모델명·디렉터리 이름만으로 동일 모델 취급 금지 |
| runtime_identity | backend/버전·source CUDA 또는 앱 runtime catalog digest·platform·정밀도 |
| input_envelope | audio frame/duration·batch·beam·context/output token 등 profile이 다루는 범위. 초과하면 재계획/차단 |
| host_ram_bytes / gpu_bytes | 해당 device 경로의 모델·runtime·workspace·해당 입력 buffer를 포함한 계획 요구량. CPU/GPU 경로의 host 요구량도 각각 구별 |
| evidence | 오프라인 근거 원문/측정 record hash·취득일·장비/runtime·방법·측정 범위·보수 margin |
| status / compatibility | MEASURED 또는 검토된 근거 상태, input/정밀도/장치의 의미 호환 범위. 미상은 UNKNOWN |

가중치 파일 크기×임의 계수, 기존1GiB, GPU 탐지 성공만으로 peak를 확정하지 않는다. 측정값+margin도 모든 GPU/driver/동시 외부 부하에 대한 상한 보증은 아니다. **profile 부재는 표시 상태 RESOURCE_ESTIMATE_UNKNOWN이며 실행 차단 코드가 아니다.** 알려진 profile의 artifact/runtime/envelope 불일치는 RESOURCE_PROFILE_MISMATCH로 차단한다. 유효한 profile을 못 찾았다는 부재와, 명시 적용한 profile이 불일치한다는 실패를 구별하고 후자를 부재로 낮춰 우회하지 않는다. GPU/CPU profile의 알려짐 여부는 device별로 보존하므로 GPU profile만 있고 CPU profile이 없더라도 명시 허용된 CPU 경로는 UNKNOWN으로 실행할 수 있다.

**C00 결정: 실제 근거 없는 항목은 넣지 않되 빈 production profile catalog도 owned 추론을 막지 않는다.** UNKNOWN은 “메모리 요구량 미확인”으로 계속 표시한다. 첫 실제 profile 항목은 고정 artifact/runtime·측정 근거·hash/취득일을 갖춘 별도 검증 단위이며 실제 모델/weights가 필요한 외부 게이트다. fake profile은 시험에만 주입한다. UNKNOWN 실행 허용을 모델별 메모리 검증 완료로 보고하지 않는다. 사용자 수동 숫자를 검증 profile로 승격하는 override는 이번에 넣지 않는다.

### 4.2 관측 상태와 GPU identity

`ResourceSnapshot`은 GPU와 host RAM 각각의 **OBSERVED / UNKNOWN / UNAVAILABLE**, monotonic 관측 시각·관측 source·검증한 장치 identity·free/total을 보존한다. UNAVAILABLE은 관측 수단 부재이지 실제 GPU 없음의 증거가 아니다. OBSERVED의 빈 장치 목록과 구별한다. 이전 성공값은 last_observed 캐시로 표시할 수 있지만 현재 배정에 사용하지 않는다. bool/음수/free>total/중복 identity/비유한 시각을 정상으로 받아들이지 않는다.

host RAM은 Windows의 읽기 전용 memory API를 감싼 주입 가능한 probe를 제안한다. GPU 메모리는 기존 nvidia-smi 계열의 읽기 관측을 사용하되 상태와 UUID를 보존한다. 이 문서 작성과 시험에서는 실제 API/subprocess를 호출하지 않는다.

GPU0 필터를 제거하되 **nvidia-smi index를 CUDA device_index와 같다고 가정하지 않는다**. 신규 `models/gpu_inventory.py`의 소유 probe가 검증 runtime의 논리 CUDA ordinal↔장치 UUID를 확인하고 host 관측과 join한다. 환경 remapping·MIG·누락/중복 identity 등으로 대응을 확인할 수 없으면 RESOURCE_GPU_IDENTITY_UNVERIFIED다. probe는 모델을 로드하지 않고, 실제 구현에서 지원 불가능한 대응은 GPU0으로 추정하지 않는다. 다른 GPU 하드웨어 확인은 외부 게이트다.

probe도 사용 중 runtime 핸들을 가질 수 있으므로 준비/취소·종료 ACK를 추적한다. L-P07의 다운로드/삭제 대기와 상호 배제하고 부모에 GPU runtime/모델을 import하지 않는다. 새 probe child에서도 **_activate_gpu 뒤 CTranslate2 import** 순서를 지킨다. source CUDA와 앱 runtime의 경로는 구분한다.

### 4.3 admission 산술

- 기본 headroom은 기존 GPU512MiB를 유지하고 host RAM에도 정책 reserve512MiB를 제안한다. 이는 모델 요구량 측정이 아니라 사용자 보호용 여유 정책이다.
- **known profile의 owned CPU**: 현재 RAM이 OBSERVED이고 `RAM.free >= profile.cpu_host_ram + RAM_headroom`이면서 CPU 강제가 확인될 때 허용한다.
- **known profile의 owned GPU**: 현재 RAM/VRAM이 OBSERVED이고 `RAM.free >= profile.gpu_host_ram + RAM_headroom`, 같은 UUID의 `VRAM.free >= profile.gpu_bytes + GPU_headroom`, CUDA 강제/runtime/identity가 모두 확인될 때 허용한다. 경계와 정확히 같으면 허용한다.
- **UNKNOWN profile의 owned CPU**: CPU 강제 조건과 기존 요청/입력 한도·lease를 지키며 실행한다. RAM 부족 예상치를 만들 수 없으므로 RAM UNKNOWN/UNAVAILABLE이나 관측 free 값만으로 새 메모리 차단을 만들지 않는다. RAM 관측 상태는 표시한다. 미상 요구량을0으로 바꿔 known 산술에 넣지 않는다.
- **UNKNOWN profile의 owned GPU**: 현재 VRAM이 OBSERVED이고 `VRAM.free >= GPU_headroom`, CUDA 강제/runtime/identity 조건을 만족해야 한다. host RAM 상태는 표시하지만 이 분기에서 RAM 예상량 기반 차단은 하지 않는다. GPU 관측 UNKNOWN/UNAVAILABLE·실제 장치 부재·identity 불확인은 여전히 GPU 실행을 막는다. GPU profile UNKNOWN 자체는 CPU fallback의 이유가 아니다.
- AUTO는 조건을 만족한 후보 중 여유가 큰 GPU를 선택하고 tie는 안정적인 UUID 순서다. pinned UUID는 다른 GPU로 바꾸지 않는다. 해당 GPU가 불가해도 CPU는 fallback 정책과 CPU의 독립 조건이 맞을 때만 가능하다.
- CPU_ONLY는 GPU probe/활성화를 하지 않는다. fallback 정책은 GPU 관측 UNKNOWN/부족/runtime 불가 등의 이유를 보존하고 CPU의 known/UNKNOWN 조건에 맞으면 CPU를 선택할 수 있다. GPU_ONLY는 어떤 실패에서도 CPU를 만들지 않는다.
- 서버 경로의 서버 RAM/VRAM은 NOT_CONTROLLED다. REMOTE는 장치 정책 NOT_APPLICABLE, 허용 Ollama는 device=server_unknown이다. Recoryn PC의 free memory로 서버 모델이 수용 가능하다고 판정하거나 미상을0byte라고 표시하지 않는다. 기존 client payload 한도·동의·비용 제한은 유지한다.
- snapshot TTL 기본2초를 제안한다. 큐에서 기다린 시간이 길면 기존 선택을 강행하지 않고 lease 시점에 새 관측으로 검증한다. expired/identity 변경은 재관측/차단하며 immutable 요청 의미를 바꾸지 않는다.

관측과 실제 할당 사이 외부 앱이 메모리를 쓸 수 있다. 예약은 OS의 VRAM 강제 확보가 아니다. 실제 OOM은 기존 RESOURCE_EXHAUSTED/BLOCKED로 드러내고 원본을 보존한다. OOM 뒤 같은 Attempt 안에서 자동 CPU 재시도/의미 변경을 하지 않는다.

복수 실패의 독립 oracle 순서는 DTO 타입/범위 거부 → 작업/backend capability → strict Ollama/화자 GPU 미지원 → owned 경로의 명시 profile 불일치 → GPU 경로의 L-P07 runtime 자격 → 적용할 관측의 시각 유효성/재관측 실패 → known profile만 host RAM 관측 UNKNOWN/UNAVAILABLE → GPU 관측 UNKNOWN/UNAVAILABLE·장치 부재 → GPU identity 대응 → known profile만 host RAM 부족 → VRAM 부족 순이다. known은 요구량+headroom, UNKNOWN은 GPU headroom만 비교한다. profile 부재는 이 실패 순서에 들어가지 않는다. 이미 만료된 적용 대상 snapshot은 한 번 새로 관측하고도 유효하지 않으면 SNAPSHOT_STALE다. UNKNOWN CPU에는 필수 메모리 관측 자체가 없으므로 stale RAM을 차단으로 승격하지 않는다. 실제 모델 device 불일치는 로드 뒤 추론 전 검사다. 알려진 장치 부재는 기존 RESOURCE_GPU_UNAVAILABLE이며 관측 수단 부재와 다르다. CPU_ONLY에서는 GPU 단계 전체, REMOTE/허용 Ollama에서는 owned 자원 단계 전체를 건너뛴다.

fallback은 GPU 가지를 위 순서로 판단한 뒤 runtime/관측/용량 등의 실패이면 CPU 가지를 별도로 판단한다. 선택 후보의 명시 profile 불일치는 재계획 전 차단하며 이를 UNKNOWN으로 낮춰 CPU로 우회하지 않는다. CPU도 실패하면 **CPU 가지의 첫 실패를 대표 코드로**, GPU 실패를 부가 근거로 남긴다. CPU profile 부재는 실행 가능한 UNKNOWN이며, CPU를 썼다는 사실과 미상 요구량을 표시한다. 이 준비 단계 우선순위는 이미 전송한 작업의 REMOTE_UNKNOWN·취소/삭제에 대한 G-P07 우선순위를 덮지 않는다. P/E/G의 expected는 이 순서를 손으로 쓴 결정표와 대조한다.

## 5. lease·worker 수명·priority

### 5.1 소유 heavy 추론

`ResourceScheduler.plan(request,snapshot)`과 `lease(request,attempt,cancel)`를 제안한다. plan은 부수효과 없는 판단, lease는 전역 owned-heavy slot1개와 조건 재확인·실제 owner의 수명을 관리한다. 기존 choose/acquire helper는 작은 기존 계약의 호환을 위해 남길 수 있지만 **제품 경로는 새 필수 request/lease만 사용**하며 helper로 우회하지 않는다.

순서는 **runner 입장→lease 획득/재관측→파생 입력 준비·모델 worker 생성/로드→추론→실제 worker 종료 ACK→lease 해제**다. 모델을 먼저 띄운 뒤 lock을 잡지 않는다. CPU/GPU 모두 같은 owned-heavy slot에 포함한다. 서버 호출은 로컬 heavy GPU lease를 점유하지 않으며 bounded runner/transport 제한을 따른다.

C00 승인대로 **Job/attempt 이후 owned model worker를 닫아 resident 메모리를 반환**한다. live STT의 한 Job 안에서는 재사용할 수 있으나 Job 사이 GPU warm cache는 유지하지 않는다. 향후 warm cache는 resident byte를 lease와 함께 관리하는 별도 단위다.

lease 메타데이터는 lease_id, job/attempt/session, request/profile/runtime digest, device/UUID/ordinal, 계획 RAM/VRAM과 estimate_status, priority, WAITING/ACTIVE/REAP_PENDING/RELEASED, 취소·ACK 사실을 읽기 모델로 제공한다. UNKNOWN의 계획 요구량은 None이며0이나 headroom을 모델 요구량으로 기록하지 않는다. DB의 영속 ExecutionPlan 전체를 이번 단위에서 구현했다고 하지 않는다.

close/취소 후 child가 살아 있으면 **lease를 유지**하고 INFERENCE_ACK_PENDING/DIARIZATION_ACK_PENDING·RESOURCE_LEASE_HELD로 표시한다. 다음 heavy 작업은 배정하지 않는다. 기존 G-P04의 다중 owner 등록 API에 소유 resource owner의 is_live를 등록해 G-P05 삭제/복구도 실제 child 종료를 기다리게 한다. Python task 반환만으로 child 종료를 추정하지 않는다. 객체/핸들은 실제 종료 ACK까지 보유하며 임의 TTL 만료로 GPU를 재할당하지 않는다. 재시작 고아 종료 증명 자동화를 해결했다고 주장하지 않는다.

### 5.2 큐 우선순위

priority는 **BoundedRunner의 pending 선택 지점 한 곳**에서 적용한다. ResourceScheduler는 이미 dispatch된 작업의 lease를 FIFO로 관리하며 실행 중 작업을 강제로 선점하지 않는다.

- INTERACTIVE=0: 사용자가 명시한 전사/요약/화자.
- LIVE=1: 실시간 전사.
- BACKGROUND=2: 명시적 backfill/자동 후속 작업.
- 같은 priority는 admission ordinal FIFO다. 기본 세 번의 우선 선택 뒤 네 번째 dispatch는 **priority와 무관하게 가장 오래 기다린 작업**을 선택한다. 취소 waiter는 먼저 제거한다.
- 따라서 작업들이 종료되고 큐가 유한하면 오래된 작업도 앞선 waiter 수에 비례한 dispatch 횟수 안에 진행한다. 시간 SLA·실시간 성능·영구 hang 상태의 진행 보증은 아니다. GPU 작업을 중단해 녹음 작업에 양도하는 모델이 아니며 녹음 writer는 이 큐 밖이다.

`BoundedRunner.submit(...,priority=INTERACTIVE)`는 기존 무지정 호출의 FIFO 의미를 유지한다. 큐 용량/취소/fence/reader ACK/UNKNOWN 규칙을 약화하지 않는다. UI priority 변경은 입력/모델 의미나 네트워크 동의를 바꾸지 않는다.

## 6. API·오류·UI·L-P07 경계

`ResourceRequest`/`ResourcePlan`/`ResourceSnapshot`은 models.resources의 frozen DTO로 두고 provider 계약을 순환 import하지 않는다. `ResourceRequest`는 kind/backend/model/runtime/profile/input envelope/policy/preferred UUID/priority를, Plan은 해당 요청의 digest·정책 적용 여부·실제 device/UUID/CUDA index·정밀도·근거·메모리 판단을 고정한다. profile 부재는 명시 None/UNKNOWN으로 표현하며 DTO 누락 호환 경로와 다르다. backend 강제/적용 제외 계약은 고정 catalog에서 읽고 서버 capability 자기 보고는 선언 정보로만 쓴다.

`AIService.transcribe/summarize`는 resource_request를 필수 keyword로 받고, 화자 bridge도 같은 공통 admission을 거친다. LocalSTTProcess/FasterWhisperProvider에는 device_index/compute_type을 전달한다. 로드 객체의 실제 device/index/compute_type이 계획과 다르면 **추론 전에 RESOURCE_DEVICE_MISMATCH**, 성공으로 표시하지 않는다. 기존 worker4인자/선택 runtime5인자 테스트 경계는 optional 인자 확장으로 보존하되 제품은 새 plan을 전달한다.

G-P07의 폐쇄 오류 표에 다음 **12개 차단 코드**를 명시 추가한다. prefix 추정은 하지 않는다. 기존 REMOTE_UNKNOWN 우선·취소/삭제·재개/시도 한도·reader 보호는 그대로다. 별도 **표시 상태 1개 RESOURCE_ESTIMATE_UNKNOWN**은 오류 결정 함수에 보내지 않고 block_pending/fail을 호출하지 않는다. 추정 상태와 Job 상태는 서로 다른 필드다.

| 코드 | G-P07 reason |
| --- | --- |
| RESOURCE_POLICY_UNVERIFIED, RESOURCE_GPU_UNSUPPORTED | CAPABILITY |
| RESOURCE_PROFILE_MISMATCH | RESOURCE |
| RESOURCE_GPU_PROBE_UNKNOWN, RESOURCE_GPU_PROBE_UNAVAILABLE | RESOURCE |
| RESOURCE_CPU_PROBE_UNKNOWN, RESOURCE_CPU_PROBE_UNAVAILABLE | RESOURCE |
| RESOURCE_MEMORY_INSUFFICIENT, RESOURCE_GPU_IDENTITY_UNVERIFIED | RESOURCE |
| RESOURCE_SNAPSHOT_STALE, RESOURCE_LEASE_HELD, RESOURCE_DEVICE_MISMATCH | RESOURCE |

기존 GPU_RUNTIME_*·RESOURCE_GPU_UNAVAILABLE·RESOURCE_EXHAUSTED·ACK_PENDING을 위 일반 코드로 뭉개지 않는다. G-P07 원래100코드의 역사적 분모를 G11 결과로 다시 쓰지 않고, 새12개 차단 코드는 C family, UNKNOWN 표시 상태는 P/S/Ub에서 검사한다. test의 독립 코드 집합 감사에는 G11 delta를 명시 반영한다. 표시 상태를 예외 코드로 던지는 호출자는 계약 위반이며, 문자열 prefix로 모든 RESOURCE_*를 차단하지 않는다.

UI는 선택 정책과 Job에 캡처한 정책, 모델/profile 근거·UNKNOWN 이유, RAM/VRAM free/필요/headroom·관측 시각, GPU 이름/논리 index·선택 근거, priority/lease/ACK 상태를 보여 준다. UNKNOWN 요구량은 “메모리 요구량 미확인”이며 실행 중·성공 뒤에도 추정 상태를 known으로 바꾸지 않는다. OOM이면 RESOURCE_EXHAUSTED/BLOCKED와 미확인 추정을 함께 보존한다. stale cache는 “이전 관측”이며 현재 가능 값으로 사용하지 않는다. REMOTE에는 “원격 실행 — 이 PC의 장치 정책 적용 안 됨”, 허용 Ollama에는 “장치 미보장·서버 메모리 통제 불가”를 표시한다. strict Ollama 차단은 정책 변경 방법을 안내하되 자동 변경하지 않는다. resource 정보 표시/탐색이 다운로드나 probe 네트워크가 되지 않는다.

L-P07은 다음을 그대로 유지한다.

- CPU_ONLY는 앱 GPU runtime을 활성화하지 않는다. GPU source는 검증된 source CUDA 또는 동의·검증된 앱 runtime이다.
- pending install/remove·이번 실행에서 같은 설치 세대의 명시적 GPU 실패는 **그 runtime만** 제외한다. 별개의 source CUDA를 잘못 차단하지 않는다. 저장된 과거 Job 오류를 새 실행의 runtime 실패로 재사용하지 않는다.
- _activate_gpu는 child의 CTranslate2 import보다 먼저다. parent GPU runtime·전역 PATH 변경·번들 CPU/GPU 혼합·cuDNN 추가·다운로드는 없다.
- UI idle 판정에 active/held lease와 probe owner도 포함한다. runtime 파일을 쥔 owner가 있으면 삭제가 완료됐다고 표시하지 않는다.
- 실제 다른 GPU·모델의 품질/메모리 상한·새 profiler 결과는 NOT_RUN이다. L-P07/P08의 검증 이력은 참조이며 이번 재실행이 아니다.

## 7. 경우의 수와 oracle

### 7.1 유한 대표 분모

수정 계획은 **12 family, 32,772 의미 행**이다. 실제 pytest node 수와 구별한다. 큰 순수 판단 cube는 batching하되 모든 tuple과 ID를 검사한다. 아래 각 family의 Ω=F이며 거부 입력을 분모에서 제거하지 않는다. 서버에서 무시해야 하는 로컬 자원 값도 P의 직적에 남겨 REMOTE가 로컬 관측 실패로 차단되지 않는지 확인한다. current probe가 없을 때 경계 값은 last_observed 캐시로만 주어 “미상을 현재값으로 사용하지 않음”을 검사한다. profile UNKNOWN과 probe UNKNOWN은 별개 축이다.

| family / ID | 입력 Ω=F | 계획 행 | oracle |
| --- | --- | ---: | --- |
| A / G11-A-01…36 | policy3 × kind{STT,요약,화자}3 × backend{CT2,SHERPA,OLLAMA,REMOTE}4 | 36 | §3 static 표. REMOTE 지원 기능은 정책 제외, strict Ollama/미지원은 준비 전 차단 |
| P / G11-P-00001…31104 | policy3 × kind3 × backend4 × GPUprobe3 × RAMprobe3 × GPU메모리경계6 × RAM메모리경계4 × profile{둘known,GPU만미상,CPU만미상,둘미상}4 | 31,104 | §3·§4. known 요구량 산술/UNKNOWN 실행, strict Ollama 차단, REMOTE 로컬 자원 무관 |
| E / G11-E-01…72 | owned kind{STT,화자}2 × device{cpu,cuda}2 × profile상태6 × input경계3 | 72 | profile 부재는 UNKNOWN 허용, 명시 적용한 모델/runtime/envelope·근거 불일치는 차단 |
| G / G11-G-001…120 | GPU적합배치4 × identity대응5 × 선호{AUTO,존재UUID,부재UUID}3 × policy{GPU_ONLY,fallback}2 | 120 | GPU0 편향·ordinal 오인 제거, pin/명시 CPU 허용 |
| R / G11-R-001…144 | policy3 × 앱runtime상태6 × sourceCUDA유무2 × GPU충족2 × CPU충족2 | 144 | L-P07 source 우선·설치 세대/동시 수정 보호 |
| Q / G11-Q-001…864 | 대기3개 priority조합3^3 × cancel mask2^3 × 이미실행중2 × 공정turn counter{0,3}2 | 864 | 독립 priority/FIFO·비선점·네번째 oldest |
| L / G11-L-01…96 | lease상태6 × event{성공결과,로컬오류,취소,미확인결과}4 × 다른waiter2 × policy2 | 96 | 불법 전이 거부·ACK 전 해제0·UNKNOWN 논리 보존 |
| Ua / G11-UA-001…144 | policy3 × kind3 × backend4 × UI단계{prepare,queued,active,blocked}4 | 144 | REMOTE 적용 제외/strict Ollama 변경 안내/캡처 정책 불변. 미지원 active callback은 거부 표시 |
| Ub / G11-UB-01…48 | policy3 × owned 경로{CT2-STT,SHERPA-화자}2 × 표시{queued,blocked,active,ACK대기}4 × profile{known,UNKNOWN}2 | 48 | 미확인 요구량·실제/계획 장치·ACK·관측 표시, 자동 설정 변경0 |
| C / G11-C-001…096 | 신규 차단 코드12 × retryable2 × outcome_known2 × 호출{직접fail,runner}2 | 96 | CAPABILITY/RESOURCE, REMOTE_UNKNOWN 우선·기존 게시 불변 |
| S / G11-S-01…20 | profile{known,UNKNOWN}2 × owned 경로2 × 시점{prepared,queued,active,success,OOM}5 | 20 | UNKNOWN은 접수/성공을 막지 않고 OOM만 RESOURCE_EXHAUSTED/BLOCKED, 추정 상태 보존 |
| T / G11-T-01…28 | §7.3 named28 | 28 | 타입·identity·lifetime·원격 독립 guard |
| **합계** | 36+31104+72+120+144+864+96+144+48+96+20+28 | **32,772** | 계획, 실행0 |

P의 근거 fixture는 CPU host 요구100/GPU host 요구100/GPU 요구80, RAM headroom20/GPU headroom10의 작은 정수다. **GPU경계6={9,10,11,89,90,91}**로 UNKNOWN의 headroom−1/=/+1과 known의 요구량+headroom−1/=/+1을 모두 확인한다. **RAM경계4={0,119,120,121}**로 UNKNOWN CPU는 free=0 관측/관측 실패 자체로 새 차단을 만들지 않음과 known의 경계를 함께 확인한다. UNKNOWN 요구량은 None이지0이 아니다. 미상 probe의 cached 값은 화면 관측용이며 GPU 배정에 쓰지 않는다. OBSERVED의 유효 GPU는 UUID와 ordinal 대응이 있는1개로 고정한다. empty GPU·장치 identity 등은 G/T에서 별도 확인한다. 실제 GiB 숫자를 측정값처럼 꾸미지 않는다.

E profile상태6은 matching/없음/artifact mismatch/runtime mismatch/envelope 조건 불일치/canonical digest 또는 근거 불량이다. input경계는 fake profile의 envelope 최대−1/=/+1이다. profile 부재에서는 그 envelope를 실제 상한으로 강요하지 않고 기존 요청 한도 안의 세 입력을 UNKNOWN으로 허용한다. matching의 +1과 나머지 명시 불일치는 PROFILE_MISMATCH다. 화자 cuda 등의 미지원 조합도 정상 거부 행으로 포함한다. E의 matching fixture는 CPU/GPU host 요구량도 서로 다르게 해 해당 device의 profile을 읽는지 대조한다.

G 적합배치4는 GPU0만충족/GPU1만충족/둘다/둘다부족이다. 대응5는 identity/논리ordinal과hostindex뒤바뀜/누락/중복UUID/계획뒤identity변경이다. index1 선택은 실제 worker factory 인자와 로드 객체 사실까지 대조한다. 모호한 대응은 정상 GPU0으로 보충하지 않는다.

R의 앱runtime6은 READY/NOT_INSTALLED/DAMAGED/UNSUPPORTED/IN_USE/이번세대실패또는수정대기다. source CUDA가 검증돼 있으면 앱runtime 제외가 source까지 번지지 않아야 한다. CPU_ONLY는 runtime 상태와 무관하게 GPU 활성화0이다.

Ua의 미지원 active 조합은 옛 요청/늦은 callback을 주입해 UI가 정상 실행으로 승격하지 않는지 확인하는 거부 행이다. C의 앞2코드(POLICY_UNVERIFIED/GPU_UNSUPPORTED)×8=16행은 C001~016, 나머지10코드×8=80행은 C017~096으로 고정한다. RESOURCE_ESTIMATE_UNKNOWN은 이 오류 분모에 넣지 않는다.

분모 변화는 원9 family의13,160에서 A36 신설, P11,664→31,104, U72→Ua144+Ub48, C104→96, S20 신설, T24→28이고 E/G/R/Q/L은 그대로다. 총 차이+19,612행이다. profile UNKNOWN을 거부 분모에서 빼지 않고 정상 허용 oracle로 바꿨으며 REMOTE의 자원 실패 교차도 전수 유지한다.

### 7.2 상태·경쟁·독립 expected

lease상태6은 QUEUED/GRANTED_NO_CHILD/CHILD_RUNNING/INFERENCE_REPLIED/REAP_PENDING/REAP_ACKED다. “success_result가 QUEUED에 도착” 같은 입력은 불법 전이 거부로 구성한다. logical UNKNOWN과 physical 종료는 별개여서, 실제 ACK 후 lease를 해제해도 Job UNKNOWN을 지우지 않는다. ACK 전에는 다른 waiter의 heavy factory 호출0이다.

Q oracle는 조건 관계로 고정한다: 취소 항목을 고르지 않음, 실행 중 비선점, 보통 turn의 최소priority/동률최소ordinal, 공정turn의 최소ordinal. 제품 queue 선택 함수를 expected에 import하지 않는다. 계속 들어오는 interactive 요청 앞에서 오래된 background가 네번째 oldest turn에 진행하는 trace도 포함한다. 이 bounded trace를 모든 장기 실행 시간 보증으로 확대하지 않는다.

L/G/R에서 barrier로 (lease 획득↔취소), (worker 종료↔다음 grant), (runtime 제거 요청↔추론/probe 시작), (snapshot 고정↔GPU identity 변경)의 양쪽 순서를 고정한다. 관련 의미 행에 실행 trace를 연결하고 파생 interleaving 수를 별도 PASS 수로 더하지 않는다. 다른 요청은 실제 ACK 전에 preload하지 않는다.

expected 정책/작업/backend 표는 손으로 작성하고 제품 catalog/decision 함수를 호출해 만들지 않는다. memory 비교는 known의120/90과 UNKNOWN GPU의10을 독립 상수로 대조한다. UNKNOWN CPU에는 RAM 비교 자체가 없어야 하며 None을0으로 치환한 known 결과와 상태를 구별한다. fake process는 생성·모델로드·device 사실·추론·close/ACK 순서를 기록하고 fake transport/vault/다운로더는 부적절한 준비/dispatch에서 호출0을 확인한다. REMOTE의 정책 제외는 유효 동의·비용 증명 fixture에서만 실제 fake dispatch까지 성공해야 하고, T27/T28은 독립 guard 거부를 확인한다. source PCM·선택 revision·비용 UNKNOWN은 실패 뒤 불변이어야 한다.

### 7.3 타입·부정28행

T01~28: 01 required bytes=True / 02 음수 bytes / 03 i64 overflow / 04 free>total / 05 중복host index / 06 중복UUID / 07 CUDA index=True / 08 없는 pinned UUID / 09 NaN 관측시각 / 10 미래·역행 관측시각 / 11 TTL 정확 만료 / 12 probe UNKNOWN에 current 값만 강요 / 13 CPU_ONLY에서 GPU probe 시도 / 14 명시 profile과 모델 digest 다름 / 15 명시 profile과 runtime 다름 / 16 compute_type 불일치 / 17 실제 모델device=cpu인데 계획cuda / 18 실제 device_index 불일치 / 19 Ollama 자기보고GPU100%로 strict 허용 시도 / 20 Ollama num_gpu 옵션을 strict증거로 제공 / 21 닫히지 않은 child에 RELEASE / 22 cancel된 waiter에 grant / 23 dtype/input 변경을 의미동일로 강요 / 24 잘못된 priority / 25 profile UNKNOWN CPU에 RAM 관측 UNKNOWN / 26 profile UNKNOWN GPU에 VRAM=headroom−1 / 27 REMOTE 유효 비용·동의 없음 / 28 REMOTE 유효 동의·비용 거부다. 잘못된 관측은 UNKNOWN/안전 코드로 보수화하거나 타입 거부하고 GPU 실행으로 승격하지 않는다.13/19/20은 미지원 전송0,21은 소유권/lease 보존,25는 메모리 미확인 표시와 실행 허용,26은 GPU 차단/CPU무단전환0,27/28은 장치 정책 제외가 동의/비용 우회가 아님이 핵심 oracle다. T27/T28은 세 정책을 차례로 적용하는 고정 trace이며 독립 의미 행은 각각1행으로 센다.

family별 tuple과 고유 case ID 집합을 별도 산출해 missing/duplicate/extra=0을 감사한다. 기존 G-P07 catalog 시험에 새12개 차단 코드 delta를 반영하되 G-P07의 과거 결과/분모를 덮지 않는다. UNKNOWN 표시 상태는 예외/오류 경로로 들어가지 않음을 별도로 확인한다. 순수 판단 행·실제 Job/Qt node·동시성 trace·실제 모델 미실행을 따로 보고한다.

## 8. 기존 시험·추가 계층

| 기존 node/범위 | 유지/보강 |
| --- | --- |
| `tests/unit/test_models.py::test_gpu_policy_has_no_silent_fallback` | 기존 helper의 경계/CPU 허용 의미 보존. 앱의 새 plan/lease 전체가 이미 검증됐다고 확대하지 않음 |
| 같은 파일 `test_gpu_probe_absence_vs_failure`, `test_cancelled_resource_lease_is_released` | 관측 실패/부재와 취소 의미 유지, 새 RAM/identity/child ACK 보강 |
| `tests/ui/test_gpu_runtime_ui.py::test_gpu_only_without_gpu_shows_the_reason` | GPU 전용의 worker 생성0. 새로운 probe/profile fixture를 명시 주입 |
| 같은 파일 설치 세대 실패·runtime 제거 양순서 | 저장된 과거 오류를 현재 실패로 쓰지 않음, source CUDA/앱runtime 분리 |
| L-P07/L-P08 inference/runtime 시험 | 검증 코드·import 순서·설치 동의·명시 오류 유지. 다운로드/실장비를 재실행하지 않음 |
| G-P02/G-P06/G-P07·provider 회귀 | ResourceRequest가 새 동의/예산 guard를 대신하지 않음. 새로운 error 사유도 UNKNOWN/취소 우선 유지 |
| G-P03/G-P04/G-P05 | 게시 CAS·원본 저장 독립·live owner·삭제 ACK 보존 |

신규 시험4파일은 `tests/unit/test_resource_policy.py`(A/P/E/C/T), `tests/property/test_resource_policy_case_space.py`(Q·manifest·독립 모델), `tests/integration/test_resource_policy.py`(G/R/L/S·service/worker/fence·T27/T28), `tests/ui/test_resource_policy_ui.py`(Ua/Ub·요약 차단·REMOTE 적용 제외·추정/정책 표시)다. 공통 fixture `tests/resource_fakes.py`는 실제 profile 아닌 fake backend/model/probe/clock을 제공한다. 기대 표와 fixture가 제품 구현 계산을 공유하지 않는다. 한 의미 행의 여러 계층 assertion은 추가 의미 행/PASS 수로 중복 합산하지 않는다.

필수 request 때문에 기존 직접 AIService 호출 fixture와 GUI fake provider도 명시 자원 context를 받아야 한다. 실제 producer 장치를 검증하지 못하는 fake를 통과시키려고 production의 정책/runtime/identity 검사를 낮추지 않는다. 현재 실사용 profile 부재는 UNKNOWN 실행/표시 결과로 검증하고 실제 profile 추가는 별도 모델 측정 게이트로 남긴다.

## 9. mutation 계획

수정 계획 **28개, 실행0**이다. 원24개 중 M02/M03/M08을 수정 결정에 맞추고 M25~28을 추가했다. 정상본 PASS 뒤 OS TEMP의 pyproject/src/tests/scripts/packaging 사본에 한 mutant씩 적용한다. cwd/pythonpath/실제 import origin을 확인하고 목표 assertion FAIL만 검출로 센다. import/수집 오류·timeout·권한 실패는 invalid다.

| ID | 결함 | 목표 |
| --- | --- | --- |
| M01 | summarize의 policy 검사 제거 | A/Ua GPU_ONLY×Ollama 사전 호출0 |
| M02 | 로컬GPU 관측으로 Ollama GPU 보장 처리 | A/T19 Ollama unverified 유지 |
| M03 | CPU_ONLY Ollama를 무조건 허용 | A/Ua Ollama 사전 차단 |
| M04 | GPU_ONLY 실패 시 CPU 실행 | P/G factory device 기록 |
| M05 | UNKNOWN probe에 cached free 사용 | P/T 현재 관측 구별 |
| M06 | probe UNKNOWN/UNAVAILABLE을 실제GPU없음으로 합침 | P/Ub 정확한 이유 |
| M07 | 모델 요구량을1GiB로 고정 | E/P의 독립 profile 요구량 |
| M08 | known CPU profile의 fallback RAM 검사 생략 | P의 known/UNKNOWN 교차와 RAM 부족 |
| M09 | headroom 검사 `>=`를 `>`로 | P의 정확 경계 허용 |
| M10 | GPU0만 필터링 | G GPU1-only 적합 |
| M11 | host index를 CUDA ordinal로 전달 | G remapping·actual index |
| M12 | profile/runtime digest mismatch 허용 | E/T14~16 |
| M13 | worker를 lease 전에 생성 | L factory/lease 순서 |
| M14 | child ACK 전에 lease 해제 | L 다른 waiter 생성0 |
| M15 | resource owner를 Library에 등록 안 함 | L 삭제/live 대기 |
| M16 | priority를 FIFO만으로 대체 | Q의 minpriority |
| M17 | 공정 oldest turn 제거 | Q starvation trace |
| M18 | 취소 waiter를 실행 | Q/L 생성0 |
| M19 | runtime 실패를 다른 설치/source에도 적용 | R 설치 세대/source 분리 |
| M20 | CPU_ONLY에서 앱runtime 활성화 | R/T13 활성화0 |
| M21 | 로드 객체 device/index 확인 제거 | G/T17~18 추론0 |
| M22 | 새 오류를 일반 FAILED로 소실 | C 직접fail/runner reason |
| M23 | resource 오류가 REMOTE_UNKNOWN을 known으로 바꿈 | C/L outcome 보존 |
| M24 | UI의 현재 선택으로 queued 요청 정책 덮기 | Ua의 캡처 정책 유지·명시 재접수 |
| M25 | profile UNKNOWN을 차단 예외로 던짐 | P/S/T25 접수·실행 허용 |
| M26 | REMOTE도 strict 장치 정책으로 차단 | A/Ua의 세 정책 적용 제외 |
| M27 | UNKNOWN GPU의 headroom 검사 생략 | P/T26 VRAM 부족 차단 |
| M28 | UNKNOWN 요구량을0으로 바꿔 known으로 표시 | P/S/Ub의 None·미확인 상태 보존 |

## 10. 정확한 후속 쓰기 범위·대안·수락

승인된 전체 쓰기 범위는 **34파일 = source12 + 신규 시험4/공통 fixture1 + 기존 시험16 + 이 문서1**이다. 넓은 목록 중16개는 필수 request/새 probe·profile을 기존 회귀에 명시하는 적응 범위다. C00 결정대로 G-P11a와 G-P11b 두 push로 나누며 아래 정본 목록의 합집합은 유지한다. 시작 신호 전 제품 구현은 시작하지 않는다.

| 구분 | 정확한 파일 |
| --- | --- |
| 신규 models2 | `src/recoryn/models/resource_catalog.py`, `src/recoryn/models/gpu_inventory.py` |
| models 수정2 | `src/recoryn/models/resources.py`, `src/recoryn/models/__init__.py` |
| app/adapter 수정4 | `src/recoryn/app/ai.py`, `src/recoryn/app/inference.py`, `src/recoryn/transcription/adapters.py`, `src/recoryn/diarization/process.py` |
| jobs 수정2 | `src/recoryn/jobs/runner.py`, `src/recoryn/jobs/failures.py`(G-P07 신규) |
| UI 수정2 | `src/recoryn/ui/ai_bridge.py`, `src/recoryn/ui/models.py` |
| 신규 시험4 | `tests/unit/test_resource_policy.py`, `tests/property/test_resource_policy_case_space.py`, `tests/integration/test_resource_policy.py`, `tests/ui/test_resource_policy_ui.py` |
| 공통 fixture1 | `tests/resource_fakes.py` |
| 기존 직접 service 시험7 | `tests/e2e/test_ai_workflow.py`, `tests/integration/test_ai_independent.py`, `tests/integration/test_desktop_independent.py`, `tests/integration/test_publication_independent.py`, `tests/integration/test_selection_version_cas.py`, `tests/unit/test_unfinished_sessions.py`, `tests/integration/test_unfinished_recovery.py` |
| 기존 UI 시험5 | `tests/ui/test_live_ui.py`, `tests/ui/test_gpu_runtime_ui.py`, `tests/ui/test_consent_scope_ui.py`, `tests/ui/test_cost_cap_ui.py`, `tests/ui/test_blocked_reason_ui.py` |
| 기존 후속 계약 시험4 | `tests/unit/test_blocked_reasons.py`, `tests/property/test_blocked_reason_case_space.py`, `tests/integration/test_cost_cap.py`, `tests/integration/test_blocked_reason_flow.py` |
| 문서1 | `docs/testing/g11-resource-policy-cases.md` |

### 10.1 두 push의 파일·분모·검토 경계

두 단위는 직렬이며 공유 파일은 P11a의 검토/commit을 보존한 뒤 P11b가 후속 diff를 만든다. 파일 개수를 더해34보다 큰 범위가 승인된 것으로 해석하지 않는다. 각 단위는 시작 시 기준 tree·파일 hash를 다시 고정하고 정상본/회귀/독립 검토를 별도로 닫는다.

| 단위 | 정확한 파일 배분 | 그 단위의 변경 |
| --- | --- | --- |
| **G-P11a / 29파일** | source7: `src/recoryn/models/resources.py`, `src/recoryn/models/resource_catalog.py`, `src/recoryn/models/__init__.py`, `src/recoryn/app/ai.py`, `src/recoryn/jobs/failures.py`, `src/recoryn/ui/ai_bridge.py`, `src/recoryn/ui/models.py` | 필수 ResourceRequest·불변 정책 snapshot·static backend 적용 표·REMOTE 적용 제외·Ollama 사전 차단/변경 안내. catalog는 backend 표만, failures는 정책 코드2개만 추가 |
| 같은 단위의 시험/문서22 | 위 정본의 **신규 시험4 + 공통 fixture1 + 기존 직접 service7 + 기존 UI5 + 기존 후속 계약4 + 문서1**, 각 그룹 파일 전부 | 필수 DTO caller 적응·fake context·A/Ua/C 앞16/T19·20·27·28, 분모 manifest의 P11a 부분. 다른 family는 구현 전 PASS로 집계하지 않음 |
| **G-P11b / 26파일** | source12: 위 P11a source7 **모두** + `src/recoryn/models/gpu_inventory.py`, `src/recoryn/app/inference.py`, `src/recoryn/transcription/adapters.py`, `src/recoryn/diarization/process.py`, `src/recoryn/jobs/runner.py` | RAM/VRAM 관측·known/UNKNOWN profile 분기·UUID/ordinal·실제 모델 사실·lease/Library owner·종료 ACK·priority/공정turn. failures는 나머지 차단 코드10개 추가 |
| 같은 단위의 시험/문서14 | 위 정본의 **신규 시험4 + 공통 fixture1 + 기존 UI5 전부** + `tests/unit/test_blocked_reasons.py`, `tests/property/test_blocked_reason_case_space.py`, `tests/integration/test_blocked_reason_flow.py` + 문서1 | 메모리/worker fake 적응·새 오류 delta·P/E/G/R/Q/L/Ub/C 나머지80/S/T 나머지24. P11a 시험도 전부 회귀 실행 |

P11a 29 = source7+시험/fixture21+문서1, P11b 26 = source12+시험/fixture13+문서1이다. **교집합21, 합집합34**다. P11a에만 쓰는8파일은 기존 직접 service7과 `tests/integration/test_cost_cap.py`다. 이8파일은 P11a에서 `tests/resource_fakes.py`의 명시 context/probe seam을 사용하도록 적응하고 P11b에서는 공통 fixture를 갱신한다. P11b에서 그8파일의 추가 수정이 실제 필요하면 실패·최소 diff와 함께 먼저 범위 조정을 보고한다.

P11a는 static 정책 admission만 완성하고 owned 메모리/worker 경로의 기존 제한을 유지하는 중간 단위다. ResourceRequest의 최종 필드 형식은 P11a에서 고정하고, P11b에서 같은 DTO로 관측/plan/lease를 연결한다. 중간 UI는 메모리/lease 미구현을 검증 완료로 표시하지 않는다. profile UNKNOWN의 새 실행 분기와 고정1GiB/GPU0 제거는 P11b 수락 대상이다. 두 단위에 걸쳐 기본 장치 정책을 자동 변경하거나 동의/비용 guard를 잠시 우회하는 호환 코드를 넣지 않는다.

| 단위 | 배정 case ID와 산식 | 의미 행 분모 | mutation |
| --- | --- | ---: | --- |
| G-P11a | A36 + Ua144 + C001~016의16 + T{19,20,27,28}4 | **200** | M01/M02/M03/M24/M26의 **5** |
| G-P11b | P31104+E72+G120+R144+Q864+L96+Ub48+C017~096의80+S20+T의 나머지24 | **32,572** | 앞5개 외 **23**, 최종에는 전체28개 재확인 |
| 합계 | 두 ID 집합의 교집합0·합집합 전체 | **32,772** | **28개**; 재실행을 새 mutant 수에 더하지 않음 |

신규4시험 파일은 두 단위가 직렬 확장한다. 각각의 실행 시간과 최종 합계를 측정하고, 어느 단계든60초를 넘으면 축약 전에 C00에게 측정값·축약/최적화안을 보고한다. P11b 최종 누락 감사는 전체32,772 ID, P11a/P11b 배정 누락·중복·extra 각0을 모두 확인한다. pure P cube의31,104행은 Qt/process를 매번 띄우지 않는 batching으로 검사하며 실제 factory/transport/ACK 경계는 통합/Qt family가 맡는다. 시간을 맞추려고 행을 임의 제거하지 않는다.

### 10.2 범위 밖·대안·최종 수락

storage/원본·content 게시·security 비용/동의·GPU runtime catalog/loader 본체·vault·공용 설정은 범위 밖이다. Library에는 이미 승인된 다중 owner 등록 API를 호출하며 새 schema를 만들지 않는다. app/status.py·ui/main.py·다른 fixture 적응이 실제 필요하면 실패/필요 범위와 함께 먼저 요청한다. UI는 기존 model/status 표시 경로에 연결한다.

| 대안 | 장점 | 한계/권고 |
| --- | --- | --- |
| Ollama GPU 사후 관측만으로 GPU_ONLY 허용 | 기존 서버 사용 쉬움 | CPU offload를 사전 막지 못함. strict Ollama 차단 결정 유지 |
| REMOTE에도 이 PC의 장치 정책 강제 | 일률적인 표 | 실제 자원 위치와 불일치. C00가 적용 제외 결정 |
| profile 부재 시 owned 추론 전부 차단 | 메모리 예측 없는 실행 제한 | 핵심 로컬 AI를 막음. C00가 UNKNOWN 표시/조건부 실행 결정 |
| file 크기×계수·고정1GiB 계속 사용 | 단순 구현 | 모델/input/runtime 근거와 불확실성 없음. known profile 산술/UNKNOWN 보존 채택 |
| 사용자 수동 메모리 숫자로 known 통과 | 지원 범위 넓음 | 검증 근거로 오인할 위험. 이번에는 override 제외 |
| Job 사이 warm GPU cache 유지 | 반복 live 지연 감소 | resident 자원·runtime 제거/ACK 관리 복잡. 초기에는 실제 종료까지 lease 유지·Job 뒤 close 권고 |
| GPU만 lease, CPU는 무제한 | GPU 구현 간단 | host RAM/CPU 모델 충돌·무동의 fallback 위험. owned-heavy 공통 slot 권고 |

후속 실행은 기존 오프라인/offscreen·bytecode 비활성·`-p no:cacheprovider`·OS TEMP 고유 basetemp에서 한다. **실제 nvidia-smi/driver/memory API·모델·서버·다운로드를 호출하지 않고** fake를 사용한다. 새4시험 파일, 기존 models/inference/provider/diarization/runtime·G-P02/P03/P04/P05/P06/P07·tests/ui 전체, ruff check/format check·`python -m mypy src/recoryn scripts packaging`을 포함한다. 선행 HEAD+승인 파일만 담은 사본의 전체 오프라인 회귀도 가능하면 한 번 실행한다.

수락은 정상본 PASS, case ID32,772 missing/duplicate/extra=0·skip0,28 mutant의 목표 assertion/invalid 구분, CPU 무동의 전환0·strict Ollama 호출0·REMOTE 장치 정책 차단0·ACK 전 재할당0·UNKNOWN 표시의 예외화0이다. REMOTE의 동의/비용 거부, known profile 불일치/용량 부족, UNKNOWN GPU의 headroom 부족은 정상 차단이어야 한다. 신규4파일 합계가60초를 넘으면 축약 전에 측정값·원인·행 보존 최적화안을 먼저 보고한다. 실제 모델 profile/다중 GPU/메모리 압박·장시간·실제 서버 강제는 별도 미검증 게이트다.

현재는 문서/소스·기존 시험 읽기와 계약·분모 설계 및 이번 수정만 수행했다. 제품 변경0·제품 시험 재실행0·mutation0이다. C00의 (a) REMOTE 적용 제외/Ollama strict 차단, (b) profile UNKNOWN 실행·표시/known 산술·불일치 차단, (c) 관측·identity·L-P07, (d) lease·ACK·priority, (e) 필수 DTO·12차단 코드+1표시 상태·34파일/2push, (f) 분모 재산출·시간 게이트를 반영했다. 새 계획은 P11a200행→P11b32,572행, 합계32,772행·mutation28이다. 착수는 선행 G-P02/P06/P07 push와 C00의 별도 시작 신호 뒤이며 이 재보고로 구현을 시작하지 않는다.

## §개정 요청(0d846d6·G-P07 계약 반영)

### 대조 기준과 수행 범위

2026-11-24 C00의 읽기 위주 재대조 배정에 따른 **계약 개정 요청**이다. 작성자는 w5:p7 Claude다. 앞의 승인 원문 322행(LF SHA-256 `813c534fce1e124df0dc069f1490fef14b9a1d42114e7d181aa3d640715127a4`)은 한 바이트도 바꾸지 않았다. 아래 추가 사항은 기존 승인(REMOTE 적용 제외, profile UNKNOWN 실행 허용, 두 push 분할)과 구별하여 다시 결정받는다.

- 코드 근거: `git show 0d846d6:<경로>`로 읽었다. 0d846d6에는 G-P03, G-P04, G-P05·05b, G-P06·06b가 들어 있다.
- G-P07 근거: 작업 트리의 미추적 계약 `docs/testing/g07-blocked-reason-cases.md`(읽은 판 LF SHA-256 `ad1d16296e673a6e8f9bbe228d52d9f81a9b55cbaf9a73661167a7c8adb5f57c`)를 대조했다. 원문 §3·§4, §개정 요청(110코드·5종 사유·암묵 resume 금지·`app/status.py`), C00 범위 결정 절을 포함한다.
- 쓰지 않은 근거: 작업 트리 src의 미완성 G-P07 변경과 미푸시 G-P15 변경은 근거로 쓰지 않았다.
- 아래 `파일:행`은 0d846d6 객체의 줄번호다.
- 직접 한 일: 소스와 시험 소스 읽기, 원문 §8의 기존 node 4개와 §10 범위 파일의 0d846d6 존재 확인, 코드 집합 대조, 분모 산술. **시험·mutation·정적 검사는 실행하지 않았다.**
- 원문 §2의 현황(21a58bf 기준)은 0d846d6에서도 그대로였다.
  - 전사의 GPU0 필터·고정 1GiB `choose`: `ui/ai_bridge.py:217-221`
  - lease 전 `LocalSTTProcess` 생성: 238행
  - 요약이 `device_policy`를 읽지 않음: 274-326행
  - worker 1개: `app/ai.py:85`
  - 공통 `scheduler.acquire`: 333·526행
  - headroom 512MiB: `models/resources.py:55`

### 1. G-P07 110코드·5종 사유와의 대조

| 점검 | 직접 확인한 근거 | 판정·개정 요청 |
| --- | --- | --- |
| 기준 코드 수 | 원문 §6·§7.3은 "G-P07 원래100코드"라고 쓴다. G-P07 §개정 요청에서 승인된 대표 집합은 **110개**(등록 109 + 미등록 대표 1)이고, 그룹은 C10/A3/P15/R17/B24/T8/F31/U2다 | 문구를 110으로 고친다. G11의 12개를 더하면 **P11a 뒤 112개, P11b 뒤 122개**다. 그룹 변화는 P/CAPABILITY 15→17(P11a +2), R/RESOURCE 17→27(P11b +10)이다. G-P07 D 가족(110×24=2,640행)은 G11이 다시 쓰지 않는다. G11의 C가 delta만 검사한다는 원문은 유지한다. G-P07 시험의 catalog 크기 고정 상수(G11 범위의 G-P07 시험 파일)는 단위마다 112·122로 갱신한다 |
| 신규 12코드의 충돌 | G11의 12개(RESOURCE_POLICY_UNVERIFIED … RESOURCE_DEVICE_MISMATCH)를 G-P07 110개와 문자열 집합으로 대조했다. 중복 0이다 | 그대로 추가할 수 있다. 사유 매핑(앞 2개 CAPABILITY, 나머지 10개 RESOURCE)은 G-P07 결정표의 C/A/P/R/B 열 규칙과 맞는다 |
| `RESOURCE_ESTIMATE_REQUIRED` | 0d846d6 `models/resources.py:64-65`의 `choose`는 required_bytes가 음이 아닌 int가 아니면 `ValidationError("RESOURCE_ESTIMATE_REQUIRED")`를 던진다. G-P07은 이 코드를 R(RESOURCE)로 분류하여 BLOCKED로 만든다 | profile UNKNOWN의 요구량(None)이 legacy `choose`로 흘러가면 원문 §4.1 결정("부재는 차단 아님")이 BLOCKED(RESOURCE)로 깨진다. **제품 경로가 UNKNOWN 요구량을 legacy helper에 넘기지 않음**을 명시하고 T29·M30을 추가한다. 이 코드의 G-P07 분류는 바꾸지 않는다(G-P07 소유) |
| `LOCAL_EXECUTION_UNVERIFIED`(G-P07 P) | 요약 준비(`ui/ai_bridge.py:281-285`)는 Ollama가 owned이면 `model_panel.checked_attestation()`을 먼저 부른다. 이 함수(`ui/models.py:256-272`)는 미검증이면 확인 요청을 시작하고 LOCAL_EXECUTION_UNVERIFIED를 던진다. 원문 §4.3의 실패 순서에는 attestation 단계가 없다 | strict Ollama 정책 차단(RESOURCE_POLICY_UNVERIFIED)을 **attestation 확인보다 먼저** 판정하도록 요청한다. 정책으로 막힌 요청은 attestation 확인 요청도 만들지 않는다(로컬 서버 접촉 0). fallback 정책에서는 기존 attestation 순서를 유지한다. T31·M31을 추가한다 |
| `block_pending` 경로 | 원문 §3.2는 "이미 QUEUED라면 G-P07 block_pending"이라고 쓰지만, C 가족의 호출축은 {직접 fail, runner} 2개뿐이다. G-P07 §3.4의 `block_pending`은 retryable/known 입력이 없다. reason은 code 범주와 정확히 일치해야 하며, 불일치는 `BLOCK_REASON_MISMATCH`다 | C에 **12코드 × {일치 사유, 불일치 사유}2 = 24행**을 추가한다(C097~C120). 일치하면 BLOCKED이고 attempt 수는 불변이다. 불일치하면 거부되고 상태·version이 불변이다. M29를 추가한다 |
| 준비 미접수 | G-P07 §3.4는 계획을 만들지 못한 준비 실패에 Job을 만들지 않고 "실행 준비 차단·작업 미접수"로 표시한다 | 원문 §3.2와 일치한다. 변경 없음 |

### 2. 로컬 Ollama의 CPU_ONLY·GPU_ONLY 사전 차단 결정과 실제 UI

- **현재 경로:** 요약 준비(`ui/ai_bridge.py:274-326`)의 순서는 attestation → `privacy.prepare_execution` → adapter 생성 → `service.summarize`다. 장치 정책은 읽지 않는다. 원문 §2와 같다.
- **기본값과 저장:**
  - `device_policy`는 `ui/main.py:267-269`의 QComboBox다. 첫 항목 CPU_ONLY가 기본값이다.
  - 0d846d6의 main.py에는 이 값을 저장하거나 복원하는 코드(QSettings 등)가 없다. 앱은 실행할 때마다 CPU_ONLY로 시작한다.
  - STT와 요약은 이 control 하나를 공유한다.
- **결과:** P11a 뒤 로컬 Ollama 요약은 **앱을 시작할 때마다**, 사용자가 GPU_WITH_CPU_FALLBACK_ALLOWED를 다시 고르기 전까지 준비 단계에서 차단된다.
  - 원문 결정("기본 CPU_ONLY 자동 변경 금지")의 직접 결과다.
  - 지금은 정책과 무관하게 실행되므로, 기존 사용자에게는 동작 변화다. 원문 §3.1의 안전 판단(strict Ollama는 CPU/GPU 강제 증거가 없다)은 근거와 맞는다.
- **확인 요청:**
  - (가) 수용: 매 실행 명시 선택
  - (나) 정책 값 저장을 별도 단위로 배정: main.py·설정, G11 범위 밖
  - (다) owned 추론 정책과 서버(Ollama) 정책을 분리하는 UI
  - 권고는 (가) 유지에 (나)의 후속 배정 검토다. G11은 어떤 경우에도 정책을 자동으로 바꾸지 않는다.
- **안내의 탐색 위치:**
  - 원문은 strict Ollama 차단 화면에 "AI 실행 정책에서 fallback을 명시 선택" 안내를 요구한다.
  - G-P07의 CAPABILITY 행동은 "모델·제공업체 설정 표시"이고, 모델·자원 위치는 MainWindow가 탐색한다(G-P07 §4).
  - 실행 정책 control은 MainWindow form에 있다. 원문 §10.2는 `app/status.py`·`ui/main.py`를 범위에서 뺐다.
  - 요청:
    - (가) G-P07(진행 중, 두 파일의 소유자)이 "실행 정책 위치" 행동 식별자와 MainWindow 탐색을 지금 추가한다.
    - (나) P11a 범위에 `app/status.py`·`ui/main.py`를 더한다.
  - 권고는 (가)다. P11a는 그 식별자만 사용한다.

### 3. 정책 snapshot과 G-P07 명시 계속의 경계

- **두 계약의 문장:**
  - G-P07 §3.5: 명시 계속은 "현재 정책·동의·가격/예산·인증·자원으로 새 불변 실행 준비 snapshot"을 만든다.
  - 원문 §3.1: 대기/실행 중 작업은 캡처한 정책을 유지하고, 바꾸려면 명시 취소/재접수한다.
  - 충돌 지점: BLOCKED(RESOURCE/CAPABILITY) Job에서 사용자가 정책을 바꾼 뒤 "계속"을 누르는 경우다.
- **추가로 확인한 사실:**
  - 0d846d6의 로컬 STT `config_key`는 `digest:device`다(`ui/ai_bridge.py:222`). 장치가 Job 입력 키에 들어간다.
  - G-P07 계속은 입력·의미 키가 같을 때만 허용된다. 따라서 cpu↔cuda 변경은 CONTINUE_PLAN_CHANGED이고 새 Job이 된다.
  - 원문 §3.2의 "같은 Job의 후속 장치 변경은 새 Attempt" 문장은 로컬 STT에서는 현재 키 구성상 도달할 수 없다.
  - G-P07은 `_admit`의 암묵 resume(`app/ai.py:103-111`)을 없앤다. 같은 키의 일반 재요청은 BLOCKED Job을 관찰만 한다(G-P07 A 가족). "재접수"하려면 취소 뒤 새 요청을 하거나 명시 계속을 눌러야 한다.
- **결정 요청:**
  - (가) 명시 계속을 원문의 "명시 재접수"로 간주한다. 계속할 때의 현재 정책을 새 Attempt snapshot으로 쓴다.
    - QUEUED·RUNNING의 캡처 정책은 바꾸지 않는다(M24 유지).
    - 장치가 입력 키에 들어가는 로컬 STT는 장치가 바뀌면 G-P07대로 새 Job이다.
    - 화면은 Job의 캡처 정책을 계속 전까지 그대로 보여 준다.
  - (나) 정책이 바뀌면 계속을 거부(CONTINUE_PLAN_CHANGED)하고, 취소 뒤 새 요청만 허용한다.
  - 권고는 (가)다. T30·M32를 추가한다.
- **유지하는 것:** config_key 구성과 G-P03 settings CAS는 G11이 바꾸지 않는다(원문 유지). 장치를 키에서 빼는 변경은 이번 범위 밖이다.

### 4. G-P06 비용 snapshot과의 대조

- G-P06 factory는 `CostRequest` 한 인자를 받는다. `privacy.prepare_execution`이 동의·비용 준비를 한다(G-P07 §개정 3). G-P07은 config_key에 비용 모드·cap·가격 digest를 넣지 않는다.
- 원문의 대응 규칙:
  - `ResourceRequest`는 별도 필수 keyword다.
  - priority·free memory를 의미 키에 넣지 않는다.
  - REMOTE 적용 제외가 `prepare_execution` 생략 허가가 아니다(T27·T28).
  - 이 세 규칙은 위 사실과 모두 맞는다.
- 로컬 Ollama 요약도 `prepare_execution`(`ui/ai_bridge.py:286`)을 거친다. strict 차단은 그 전에 하므로 동의·비용 준비 부수효과가 0이다.
- 판정: 변경 요청 없음.

### 5. G-P11a/b 분할의 대조

- **G-P07 push 뒤에만 존재하는 파일:** 0d846d6에는 G-P07 산출물이 없다.
  - `src/recoryn/jobs/failures.py`, `src/recoryn/app/status.py`
  - `tests/unit/test_blocked_reasons.py`, `tests/property/test_blocked_reason_case_space.py`, `tests/integration/test_blocked_reason_flow.py`, `tests/ui/test_blocked_reason_ui.py`
  - P11a source 7에 `jobs/failures.py`가 있고, P11a·P11b 시험에 G-P07 시험 4파일이 있다. 따라서 원문의 "G-P07 push 뒤 착수"는 필수 조건이다.
- **0d846d6에 있는 파일:**
  - 원문 §8의 기존 node 4개
  - 기존 직접 service 시험 7개, 기존 UI 시험 4개(`test_live_ui`, `test_gpu_runtime_ui`, `test_consent_scope_ui`, `test_cost_cap_ui`), `tests/integration/test_cost_cap.py`
  - `ui/models.py`·`app/inference.py`·`diarization/process.py`
  - 신규 예정인 `models/resource_catalog.py`·`models/gpu_inventory.py`·`tests/resource_fakes.py`는 없다. 충돌은 0이다.
- **G-P07과 겹치는 시험 파일:**
  - G-P07은 `tests/ui/test_gpu_runtime_ui.py`(GPU_RUNTIME_DAMAGED→RESOURCE/BLOCKED 기대)와 `tests/integration/test_publication_independent.py`(296행 fixture)를 수정한다.
  - 두 파일 모두 G11 범위다(전자 P11a·P11b, 후자 P11a 전용 8개 중 하나). G11은 G-P07의 결과 바이트 위에서 적응한다.
- **분할 표 갱신(아래 §6 반영):**
  - P11a: 200→**206**행, mutation 5→**8**
  - P11b: 32,572→**32,593**행, mutation 23→**24**
  - 합계: 32,772→**32,799**행, mutation 28→**32**
- **순서:** G-P15 → G-P07 → G-P11a → G-P11b를 권고한다. G-P12는 같은 `app/ai.py`·`ui/ai_bridge.py`를 쓰므로 그 뒤에 두거나, C00 결정에 따라 P11a와 P11b 사이에 직렬로 둔다(G12 §개정 요청 3과 같은 판단).

### 6. 분모·mutation 변화 요청

| 가족 | 원문 | 개정 | 차이 | 배정 |
| --- | ---: | ---: | ---: | --- |
| C | 96 | 96 + `block_pending` 12코드×{일치,불일치}2 = **120** | +24 | C097~C100(CAPABILITY 2코드)은 P11a, C101~C120(RESOURCE 10코드)은 P11b |
| T | 28 | 28 + T29·T30·T31 = **31** | +3 | T30·T31은 P11a, T29는 P11b |
| 나머지 10가족 | 32,648 | 그대로 | 0 | 원문 §10.1 배정 그대로 |
| **합계** | **32,772** | **32,799** | **+27** | P11a 206 = 200 + 4 + 2, P11b 32,593 = 32,572 + 20 + 1 |

- **T29:** owned 경로의 profile UNKNOWN 요구량(None)이 legacy `choose`에 전달되지 않는다. 결과는 BLOCKED(RESOURCE_ESTIMATE_REQUIRED)가 아니라 UNKNOWN 표시와 조건부 실행이다.
- **T30:** BLOCKED(CAPABILITY: RESOURCE_POLICY_UNVERIFIED)인 Ollama 요약에서 정책을 fallback으로 바꾸고 명시 계속을 누른다. 기대값은 §3 결정에 따른다. (가)면 새 Attempt가 fallback snapshot으로 실행되고, QUEUED였던 다른 요청의 캡처 정책은 불변이다.
- **T31:** CPU_ONLY에 attestation 미검증인 owned Ollama이면 RESOURCE_POLICY_UNVERIFIED가 먼저다. attestation 확인 요청, `prepare_execution`, adapter 생성 호출은 모두 0이다.
- 독립 기대는 다음을 손으로 쓴 표로 대조한다. 제품 catalog·결정 함수를 import하지 않는다.
  - 코드→사유 표
  - `block_pending` 거부 코드
  - fake attestation·privacy·legacy `choose` 호출 수

mutation은 원문 28개를 유지하고 다음 4개를 더해 **32개**를 요청한다.

| ID | 결함 | 목표 | 단위 |
| --- | --- | --- | --- |
| M29 | 새 코드의 범주를 잘못 등록(예: RESOURCE_POLICY_UNVERIFIED를 RESOURCE로) | C의 직접 fail·runner 사유와 `block_pending` 일치/불일치 행 | P11a |
| M30 | 제품 경로가 UNKNOWN 요구량을 legacy `choose`로 보냄 | T29·S의 접수·실행 허용 | P11b |
| M31 | attestation 확인을 정책 판정보다 먼저 수행 | T31의 attestation 요청·서버 접촉 0 | P11a |
| M32 | 명시 계속의 정책 처리를 §3 결정과 반대로 구현 | T30 | P11a |

- 배정 갱신: P11a는 M01·M02·M03·M24·M26·M29·M31·M32로 **8개**, P11b는 나머지 **24개**다. 최종에는 32개 전체를 다시 확인하되, 재실행을 새 mutant 수에 더하지 않는다.

### 7. C00 결정 요청

1. 코드 수를 110 기준으로 정정한다. P11a 뒤 112, P11b 뒤 122(P15→17, R17→27)이고, G-P07 시험의 catalog 상수를 단위마다 갱신한다
2. UNKNOWN 요구량의 legacy `choose` 금지를 명시한다(T29·M30). `RESOURCE_ESTIMATE_REQUIRED` 분류는 G-P07 그대로다
3. strict Ollama 정책 차단을 attestation보다 먼저 판정한다(T31·M31)
4. C에 `block_pending` 24행을 추가한다(M29)
5. 로컬 Ollama의 매 실행 기본 차단 결과 확인: (가) 수용 / (나) 정책 저장 후속 배정 / (다) 서버 정책 분리
6. "실행 정책 위치" 행동 식별자: (가) G-P07이 추가 / (나) P11a 범위에 `app/status.py`·`ui/main.py` 추가. 권고 (가)
7. 정책 변경 뒤 명시 계속: (가) 새 snapshot 허용 / (나) 거부. 권고 (가)(T30·M32)
8. 분모 32,772→**32,799**, mutation 28→**32**, 분할 P11a 206/8·P11b 32,593/24
9. 착수 순서: G-P15 → G-P07 → G-P11a → G-P11b, G-P12와의 상대 순서

쓰기 범위 34파일(P11a 29·P11b 26)은 결정 5(나)·6(나)를 고르지 않는 한 바꾸지 않는다. 제품 코드·제품 시험·mutation은 여전히 실행 0이다. 이 절 추가 외에 저장소 파일을 수정하지 않았다.

## §구현 결과(G-P11a, a57a517 기준)

### 기준과 범위

- 작성자: w5:p7 Claude. 배정: C00의 G-P11a 시작 신호(개정 결정 ①~⑨ 승인).
- 기준 HEAD는 `a57a517`(G-P07 푸시됨)이다. 시작할 때 §10.1의 G-P11a 29파일 hash를 고정했다. 시작 시점에 source·시험 28파일은 a57a517과 같았고, 이 문서는 미추적(LF SHA-256 `410fc260…`)이었다.
- 앞의 승인 원문과 §개정 요청 절은 한 바이트도 바꾸지 않았다. 이 절은 그 뒤에 덧붙인 것이다.
- 29파일 중 **24파일을 바꿨다**: source 7, 신규 시험 4, fixture 1, 기존 시험 11(`resource_request` 적응 10 + G-P07 catalog delta 1), 이 문서.
- 아래 5파일은 바꾸지 않았다. 직접 `AIService.transcribe/summarize` 호출이 없거나, G-P07 D 가족(110코드 × 24 = 2,640행)처럼 G11이 다시 쓰지 않는 분모만 쓰기 때문이다. 다섯 파일 모두 변경 없이 통과했다.
  - `tests/ui/test_live_ui.py`
  - `tests/ui/test_gpu_runtime_ui.py`
  - `tests/ui/test_cost_cap_ui.py`
  - `tests/integration/test_cost_cap.py`
  - `tests/property/test_blocked_reason_case_space.py`
- §10.1의 "이 8파일을 resource_fakes seam으로 적응"은 필요한 파일만 적용했다. 7개 직접 service 시험은 적응했고, `test_cost_cap.py`는 변경할 필요가 없었다.
- 범위 밖 파일(G-P08·G-P15b 파일, `app/status.py`, `ui/main.py`)은 쓰지 않았다.

### source 변경

| 파일 | 변경 |
| --- | --- |
| `models/resource_catalog.py`(신규) | §3.1의 고정 backend 표만 담는다. 지원 조합은 CT2/STT, SHERPA/화자, OLLAMA/요약, REMOTE/STT·요약이고 나머지는 `CAPABILITY_UNSUPPORTED`다. 그 밖에 거부 코드 3개, `MappingProxyType` 표와 canonical `CATALOG_DIGEST`, provider→backend registry(`faster_whisper`, `ollama`, `openai`, `gemini`, `anthropic`, 내부 식별자 `sherpa_onnx`)가 있다. 메모리 profile 항목은 없다(§4.1 C00 결정; 실제 profile은 외부 게이트) |
| `models/resources.py` | `ResourceRequest`는 frozen이며 kind/backend/policy/identity 3종/envelope/선호 GPU/priority를 엄격하게 검증하고 canonical digest를 낸다. 그 밖에 `ResourcePlan`, `plan_static`, priority 상수 `INTERACTIVE/LIVE/BACKGROUND`, 표시 상태 `RESOURCE_ESTIMATE_UNKNOWN`을 추가했다. legacy `choose`/`acquire`/`probe_gpus`는 바꾸지 않았다(P11b 대상) |
| `models/__init__.py` | 위 공개 이름을 export한다 |
| `jobs/failures.py` | CAPABILITY에 `RESOURCE_POLICY_UNVERIFIED`·`RESOURCE_GPU_UNSUPPORTED`를 추가했다. 등록 코드는 111개, 미등록 대표를 더하면 **112**(결정 ①)이고 CAPABILITY는 15→17이다 |
| `app/ai.py` | `transcribe/summarize`에 필수 keyword `resource_request`를 추가했다. static admission이 첫 문장이어서 session 읽기·Job 생성·provider 호출보다 먼저 실행된다. 요청은 admitted일 때만 캡처하므로 같은 키의 병합 요청은 캡처를 바꾸지 않는다(M24). 명시 계속(resume)은 새 admission이므로 새 snapshot으로 교체한다(결정 ⑦, M32). runner task의 첫 문장에서 dispatch 재검사를 한다(§3.2). 화자 bridge용 `admit_diarization`(Job 생성 전 admission)·`capture_diarization`과 읽기 접근자 `resource_request(job_id)`를 추가했다 |
| `ui/ai_bridge.py` | 클릭한 UI thread에서 정책을 한 번 읽는다. provider registry로 1차 static 검사를 한다. 이 검사는 attestation(T31, 결정 ③)·`privacy.prepare_execution`·adapter·Job보다 먼저다. 2차 검사는 준비된 `config.provider_id`로 한다. 정책 코드 2개는 G-P07의 `EXECUTION_POLICY_ACTION`으로 보낸다(결정 ⑥; `app/status.py`는 수정하지 않음). 안내 문구는 직접 선택 방법을 알려 주고, 자동 변경이 없으며 재시작 시 CPU_ONLY로 돌아간다고 밝힌다(결정 ⑤). tick에는 캡처 정책·"현재 선택 X은 새 요청부터 적용"을 표시하고, 표가 거부하는 옛 요청·늦은 callback은 거부로 표시한다. 화자 경로도 같은 gate·캡처·dispatch 재검사를 거친다. 로컬 STT 요청의 `model_identity`는 검증한 모델 digest다 |
| `ui/models.py` | Ollama 절에 고정 안내 label을 추가했다. 안내 내용은 다음과 같다. fallback 정책에서만 실행한다. 서버의 CPU·GPU·메모리는 통제하지 않는다. 자동 변경은 없고, 재시작하면 CPU_ONLY로 돌아간다. 원격은 장치 정책 대상이 아니다 |

### 개정 결정의 반영

1. 코드 수를 110 기준으로 정정했다. `tests/unit/test_blocked_reasons.py`는 승인된 G07 표(110행)를 그대로 두고, G11 delta 2개를 명시적으로 더해 111(+미등록 대표 = 112)을 감사한다.
2. UNKNOWN 요구량을 legacy `choose`에 넣지 않는다는 규칙(T29·M30)은 P11b 몫이다. P11a는 owned 경로의 기존 `choose` 호출을 바꾸지 않았다.
3. 정책 차단이 attestation보다 먼저 실행된다. T31·M31로 확인했다.
4. C에 `block_pending` 행을 추가했다. P11a 몫은 C097~C100(CAPABILITY 2코드 × {일치, 불일치})이다.
5. 매 실행 기본 차단: 차단 화면과 모델 패널에 명확히 안내한다. 자동 변경은 0이다. 정책 저장은 G-P16 몫이다.
6. G-P07의 `execution_policy` 행동 식별자를 사용했다. 탐색은 기존 `open_blocked_action`을 따른다.
7. 정책 변경 뒤의 명시 계속은 새 snapshot을 허용한다. T30·M32로 확인했다.
8. P11a 몫은 206행·mutation 8개다(아래 결과).
9. 순서 G-P15 → G-P07 → G-P11a를 지켰다(기준 a57a517).

### T30 문구 정정

§개정 요청 §6의 T30은 "BLOCKED(CAPABILITY: RESOURCE_POLICY_UNVERIFIED)인 Ollama 요약"을 전제로 한다. 그러나 strict 정책의 Ollama 요청은 admission에서 Job 생성 전에 거부되므로, 그런 Job은 정상 경로로 만들 수 없다. 도달 가능한 trace는 다음과 같고, 결정 ⑦의 의미(명시 계속은 새 admission)는 그대로 검사한다.

1. fallback 정책으로 캡처된 Ollama 요약 Job이 다른 사유(BUDGET)로 BLOCKED다.
2. 사용자가 CPU_ONLY로 바꾸고 계속을 누른다. 결과는 준비 차단(`RESOURCE_POLICY_UNVERIFIED`)이다. "기존 Job BLOCKED 유지"를 표시하고, Job·version·attempt는 불변이며 `prepare_execution`은 0회다.
3. 사용자가 fallback으로 다시 바꾸고 계속을 누른다. 결과는 resume이다. 캡처는 새 snapshot으로 교체되고 Job은 새 Attempt로 SUCCEEDED다.
4. QUEUED였던 다른 요청의 캡처 정책·상태는 불변이다.

### 시험

| 파일 | node | 의미 행 |
| --- | ---: | --- |
| `tests/unit/test_resource_policy.py` | 73 | A36(손으로 쓴 §3.1 표 대 `plan_static`, 직접 service 거부의 Job·provider 호출 0, 허용 행의 캡처), C001~016(직접 fail·runner), C097~100(`block_pending`), T19·T20. 보조: DTO 엄격성 11, `plan_static` 타입 거부, 필수·타입 일치 request, UNKNOWN 표시 상태가 오류가 아님 |
| `tests/integration/test_resource_policy.py` | 4 | T27·T28: 실제 MainWindow, PrivacyPanel, ConsentStore, CostLedger, Gateway, OpenAI adapter에 fake vault·wire를 붙이고 세 정책을 차례로 적용한다. 보조: dispatch 재검사, 병합 캡처 불변·명시 계속 교체 |
| `tests/ui/test_resource_policy_ui.py` | 149 | Ua144(정책3 × 작업3 × backend4 × {prepare, queued, active, blocked}), T30, T31. 보조: 분모, 준비된 provider로 하는 2차 gate, 캡처 기록 없는 정책 차단 Job 표시 |
| `tests/property/test_resource_policy_case_space.py` | 4 | 개정 전체 32,799 ID 산출, P11a 206 누락·중복·초과 0, P11b 32,593 미주장, digest 분리 |
| `tests/resource_fakes.py` | — | 직접 service 호출 적응용 요청 2개. CPU_ONLY의 LOCAL_CT2는 CPU 강제이고 REMOTE는 정책 대상 밖이어서 GPU·probe에 의존하지 않는다 |

- 기존 시험 적응: `resource_request=STT/SUMMARY` keyword와 import만 추가했다. tokenize 기반 script를 쓰고 diff를 검토했다. ruff format에 따른 줄바꿈 외에 assertion 변경은 0이다.
  - 직접 service 7파일
  - `test_blocked_reason_flow.py`
  - `test_blocked_reason_ui.py`
  - `test_consent_scope_ui.py`
- Ua의 주입 경계는 provider→backend registry 데이터다. 실제 UI provider로는 만들 수 없는 조합(예: STT×OLLAMA)도 bridge의 실제 gate에 도달시킨다. queued·active·blocked 단계의 거부 조합은 "옛 요청·늦은 callback"으로 주입한다(§7.1).
  - `prepare_execution`은 호출을 기록한 뒤 `CONSENT_REQUIRED`로 멈추는 fake다. 허용 행이 독립 guard에 도달했다는 증거로 쓴다.
  - `DiarizationConfig`는 호출을 기록한 뒤 거부하는 fake다.
  - `request_attestation_check`는 서버에 접촉하지 않는 counter다.

### 결과

- 모든 실행은 격리 사본(`git archive a57a517` + 29파일, PYTHONPATH = 사본 src, 자식 import 출처가 사본임을 확인)에서 했다. 작업 트리와 `.venv` editable 설치는 사용하지 않았다. 공통 옵션은 `-p no:cacheprovider`, OS TEMP의 고유 basetemp, offscreen, `-W error::ResourceWarning`이다.
- **신규 4파일 단독: 230 passed, 7.62초**(60초 게이트 안). 의미 행 206과 보조 24 node(unit 15, 통합 2, UI 3, property 4)다. 가장 긴 node는 T28 1.19초, T27 0.99초다.
- **case ID 감사**
  - 개정 전체 분모 32,799를 family 공식으로 산출했다.
  - P11a 몫 206은 시험이 실제로 parametrize하거나 명명한 ID와 대조했다. 누락·중복·초과는 각각 0이다.
  - P11b 몫 32,593은 P11a node가 주장하지 않는다. skip은 0이다.
- **CI core 동등**(`.github/workflows/core.yml` 단계와 flag 그대로): ruff check·format --check·mypy(89 source) 통과, 전체 pytest **20,598 passed**(failures·errors·skipped 0, 1,340.6초, JUnit LF SHA-256 `cbad27c2…`), 총 coverage 92.71%, `scripts/check_coverage.py` 묶음별 예산 전부 PASS(domain 100/100, capture 99.85/98.57, jobs 99.10/96.04, storage 96.51/92.43, security 98.11/94.43, content 99.59/98.75, all 94.17/88.31; line/branch %). 새 모듈은 `resource_catalog.py` 100%, `failures.py` 100%, `resources.py` 85%(미적중은 기존 `probe_gpus` 본문). CI 사본의 이 문서는 결과 절을 쓰기 전 판이며, 그 차이는 실행 대상이 아닌 문서뿐이다
- **1차 CI 실행의 실패 1건과 수정**
  - 실패: 첫 전체 실행(20,595건)에서 G11-C-004(runner, known, not retryable)가 BLOCKED가 아니라 CANCELLED였다.
  - 원인은 시험 하네스였다. 시험이 DB 상태(BLOCKED)만 보고 `runner.stop()`을 불렀다. 그 시점에 작업은 아직 runner의 `_active`에 있었고, `stop()`이 그 작업을 `jobs.cancel()`했다.
  - 확인: `_active` 정리 직전에 50ms 지연을 넣은 probe 사본에서 기존 대기 방식은 4건이 실패했다. `tests/unit/test_runner.py::idle`과 같은 runner idle 대기로 고친 뒤에는 16건이 모두 통과했다. 같은 사본에서 runner 행을 40회 반복 실행했을 때도 640회 모두 통과했다.
  - 수정 뒤 전체 실행은 20,595 passed였다. 보조 3건을 더한 최종 실행은 위 CI 결과다.
- **mutation 8/8 검출, invalid 0.** mutant마다 새 격리 사본에 하나만 적용했고, import 출처가 사본임을 확인했다. 검출로 센 것은 목표 node의 assertion 실패(또는 `pytest.raises` 기대 실패)뿐이다.

| ID | 결함 | 실행 node | 실패 | 목표 적중(예) |
| --- | --- | --- | ---: | --- |
| M01 | summarize의 두 정책 gate 제거 | 신규 4파일 | 11 | Ua prepare의 요약 거부 행 8(UA-017·021·025·065…) |
| M02 | 로컬 GPU 관측으로 Ollama GPU_ONLY를 cuda 처리 | T19·T20(probe fake인 node만) | 2 | T19 |
| M03 | CPU_ONLY Ollama 허용 | 신규 4파일 | 10 | A-07 외 Ua |
| M24 | 같은 키 병합 요청이 캡처를 덮음 | 신규 4파일 | 10 | Ua queued 9, AUX-CAPTURE |
| M26 | REMOTE를 strict 정책으로 차단 | 신규 4파일 | 25 | T27·T28, A, Ua |
| M29 | `RESOURCE_POLICY_UNVERIFIED`를 RESOURCE로 등록 | 신규 4파일 + `test_blocked_reasons.py` | 11 | C 6(C-003·004…), C097, G-P07 delta |
| M31 | attestation을 정책 판정보다 먼저 | 신규 4파일 | 1 | T31 |
| M32 | 명시 계속에서 새 snapshot 미캡처 | 신규 4파일 | 2 | T30, AUX-CAPTURE |

- **관찰(범위 밖, C00 판단 요청).** 위 원인은 제품 종료 경로에도 있다. `BoundedRunner.stop()`은 `_active`에 남은 작업을 `jobs.cancel()`한다. 그래서 `fail()`이 BLOCKED를 기록한 직후 종료(`service.close`)가 겹치면 BLOCKED Job이 CANCELLED로 바뀌어, 차단 사유와 계속 가능성을 잃을 수 있다. `jobs/runner.py`는 P11b 범위이고 G-P07 계약과 관련되므로 이번에 바꾸지 않았다.
- **coverage가 닿지 않은 새 경로**(최종 CI 기준)
  - privacy 패널·control 부재 시 provider 판정(`ui/ai_bridge.py` 276·278)
  - 준비 전 provider가 정해지지 않아 1차 gate를 생략하는 분기(295)
  - live 임시 전사의 gate 거부 뒤 재시도 억제 표시(470·484)
  - 화자 registry가 backend를 모를 때(755)
  - tick이 이미 걸러 낸 kind의 조기 반환(1115)
  - 이 경로들은 방어 분기다. 판정 근거는 coverage 수치가 아니라 위 의미 행과 mutation이다.

### 미검증·한계

- P11a는 static 정책 admission만 다룬다. owned 경로의 메모리·lease·GPU0 필터·고정 1GiB·실제 장치 사실·priority 큐와 나머지 10코드는 P11b 몫이며, 이번 결과를 그 검증으로 보고하지 않는다. UI도 메모리 요구량을 "미확인"으로만 표시한다.
- 실제 GPU, nvidia-smi, Ollama 서버, 모델, 원격 provider, 유료 호출은 실행하지 않았다. M02 mutant는 GPU probe가 fake인 T19·T20 node에서만 실행했다.
- offscreen Qt에서는 키보드 focus를 판정하지 않았다. 대신 "AI 실행 정책" control을 포함한 tab으로 바뀌는지를 확인했다.
- 정책 값 저장·복원(재시작 뒤 CPU_ONLY)은 G-P16 전까지 그대로다.
- 이번 단위는 원격 provider의 stream 단위 비용·동의 재검사를 새로 검증하지 않는다. 그 부분은 G-P02·G-P06의 기존 계약이다. T27·T28은 장치 정책 제외가 그 guard를 우회하지 않음만 확인한다.

## §구현 결과(G-P11b, b925520 기준)

### 기준과 범위

- 작성자는 w5:p7 Claude다. 배정은 C00의 G-P11b 착수 신호다. 기준 HEAD는 `b925520`(G-P11a 푸시됨)이다.
- 시작 때 §10.1의 G-P11b 26파일 hash를 고정했다. 26파일 모두 HEAD와 같았고, `models/gpu_inventory.py`는 신규였다.
- 이 문서의 앞 내용(LF SHA-256 `5977dd9a…`)은 한 바이트도 바꾸지 않았다. G-P11a 결과 절의 정정(G11R-07)도 아래에 덧붙이는 방식으로 적었다.
- 범위 밖 파일은 쓰지 않았다. 여기에는 G-P08 작업 파일(`app/status.py`, `ui/main.py`, `storage/library.py` 등)과 G-P11a 전용 8파일이 포함된다.
- G11R-04(공용 `status.py`의 행동 식별자)는 C00 지시대로 G-P08 push 뒤로 미뤘다.

- 26파일 중 **21파일을 바꿨다**: source 11(`ui/models.py` 제외), 신규 시험 4, fixture 1, 기존 UI 시험 3(`test_live_ui`·`test_gpu_runtime_ui`·`test_blocked_reason_ui`), `test_blocked_reasons.py`, 이 문서.
- 바꿀 필요가 없었던 5파일은 모두 변경 없이 통과했다: `ui/models.py`, `tests/ui/test_consent_scope_ui.py`, `tests/ui/test_cost_cap_ui.py`, `tests/property/test_blocked_reason_case_space.py`, `tests/integration/test_blocked_reason_flow.py`.
- 기존 UI 시험의 적응 내용은 다음과 같다.
  - Job별 worker에 맞춘 fake 서명(`device_index`·`compute_type`)
  - 관측기 seam(`make_observer`)
  - warm worker 단언을 "Job 뒤 종료됨"으로 바꿈
  - 보유 lease의 ACK 시험을 실제 scheduler로 바꿈
  - runner `submit`의 `priority` keyword
  - `test_live_ui`: worker 생성이 UI가 아니라 AI runner에서 일어나므로 "bridge busy" 단언을 "runner active"로 바꿈. 녹음 종료가 모델 준비를 기다리지 않는다는 원래 의미는 유지한다
- G-P11a 전용 8파일(직접 service 시험 7과 `test_cost_cap.py`)은 바꾸지 않았다. 공통 fixture `STT`는 CPU_ONLY의 LOCAL_CT2로 관측과 profile이 전혀 필요 없어, 그대로 통과한다.

### source 변경

| 파일 | 변경 |
| --- | --- |
| `models/resources.py` | 관측 DTO: `GpuDevice`(UUID·논리 CUDA ordinal·host index), `GpuObservation`, `MemoryObservation`(OBSERVED/UNKNOWN/UNAVAILABLE/NOT_OBSERVED), `ResourceSource`(L-P07 source), `ResourceSnapshot`(관측 시각, 미래 관측 거부, display 전용 cache). 순수 `plan_resources`는 §4.3 산술 그대로다: known/UNKNOWN 분기, 경계 동일 허용, AUTO 최대 여유와 UUID tie, pin 불변, GPU_ONLY는 CPU를 만들지 않음, fallback은 CPU 독립 조건, 의미 키 장치 고정. `resolve_profile`은 명시 profile 불일치·손상 기록을 MISMATCH로 처리하고 부재로 낮추지 않는다. `observation_needs`는 필요한 관측만 고른다. `Lease`는 6상태·4사건 전이표, lock 없는 `is_live`, 실제 종료 ACK 뒤에만 해제한다. `ResourceScheduler.observe/plan/prepare/lease/leases/held/reap_held`를 추가했다. G11R-06에 따라 `ResourcePlan.applies`를 `owned`(소유 자원 단계)와 `policy_applies`(REMOTE만 False)로 나눴다. legacy `choose`/`acquire`/`probe_gpus`는 그대로다 |
| `models/resource_catalog.py` | `MemoryProfile`(장치별 요구량, None이면 그 장치만 UNKNOWN), canonical `profile_digest`, `profile_intact`(digest·근거 hash·검토 상태)를 추가했다. 운영 `PROFILES`는 빈 tuple이다(§4.1 C00 결정) |
| `models/gpu_inventory.py`(신규) | 운영 관측기 `Inventory`(필요한 것만 관측). RAM은 `GlobalMemoryStatusEx`, GPU는 UUID·PCI bus·MIG를 포함한 nvidia-smi 읽기다. CUDA ordinal은 소유 probe child가 runtime을 활성화한 뒤 CTranslate2를 import해 `CUDA_DEVICE_ORDER=PCI_BUS_ID`로 센다. `join_identity`는 bus id 순서로 ordinal을 정하고, 아래 조건을 모두 만족할 때만 VERIFIED다: `CUDA_VISIBLE_DEVICES` 없음, MIG 없음, UUID 유일, CUDA 수 = host 수. 응답 없는 probe child는 `PROBE_OWNERS`로 추적한다. 시험은 이 파일의 probe를 모두 fake로 주입한다 |
| `jobs/failures.py` | RESOURCE에 10코드를 추가했다. 등록 121개, 미등록 대표를 더해 **122**다(결정 ①). RESOURCE는 17→27이다 |
| `jobs/runner.py` | `submit(..., priority=)`과 pending 선택점 `_take`(최소 priority → 최소 ordinal, 세 번째 우선 선택 뒤에는 가장 오래된 것, 실행 중 비선점). G11R-02: 결과 기록과 settle을 runner lock 안에서 하고, `stop()`은 settle된 작업을 취소하지 않는다. held lease를 `snapshot()["active"/"held"]`에 포함한다. 종료 ACK가 실패한 작업은 Job local reader를 유지한다(아래 해석 1) |
| `app/inference.py` | `LocalSTTProcess(device_index=, compute_type=)`, `load()`(추론 없이 로드한 실제 facts), lock 없는 `is_live()`를 추가했다. worker는 `CUDA_DEVICE_ORDER=PCI_BUS_ID`를 쓴다. 기존 4인자/runtime 5인자 계약은 그대로다(새 인자를 넘길 때만 7인자) |
| `transcription/adapters.py` | `FasterWhisperProvider(device_index=)`, `load()`, `facts()`(CTranslate2 객체가 보고하는 device/device_index/compute_type)를 추가했다. `device_index`는 지정했을 때만 factory에 넘긴다 |
| `diarization/process.py` | lock 없는 `is_live()`, CPU 전용 구성의 `device_facts()`를 추가했다 |
| `app/ai.py` | G11R-01: 등록 identity가 요청 backend와 다르면 `INVALID_RESOURCE_REQUEST`. 미등록 in-process 대역은 표지를 신뢰하고 이 규칙을 문서화했다. `owned_worker`는 dispatch 재검사 → lease → 첫 사용 때 worker 생성(`open(plan)`) → facts 확인 → 종료 ACK 뒤 해제 순서다. 요약(OLLAMA/REMOTE)은 로컬 lease를 쓰지 않는다. runner priority 전달, `resource_view`, `OwnedFactory` 형식을 추가했다 |
| `ui/ai_bridge.py` | GPU0 필터와 고정 1GiB `choose`를 없앴다. 준비 때 `scheduler.prepare`로 의미 키 `digest:device`를 정하고(G11은 키 구성을 바꾸지 않는다), dispatch lease가 그 장치를 유지하며 재관측한다. Job별 worker(`OwnedSTT`, `OwnedDiarization`)를 쓰고 warm worker는 없다. `local_source`(L-P07)를 두었다. 운영 관측기 seam은 `make_observer`다. 표시: 추정·장치·CUDA 논리 index·RAM/VRAM 여유와 기준·lease 단계·ACK 대기. held lease와 probe owner가 남아 있으면 runtime 제거를 거부한다 |

`ui/models.py`는 이번 단위에서 바꿀 필요가 없었다. 모델 패널의 "AI가 사용 중"은 bridge의 거부를 그대로 쓴다.

### 계약 해석과 C00 판단 요청

1. **Library live owner 대신 Job local reader 유지**(§5.1 문구와 다름)
   - 문제: lease를 `Library.register_live_owner`에 등록하면, AI 작업이 도는 동안 녹음 종료가 `FINALIZING`에서 멈췄다(`tests/ui/test_live_ui.py::test_slow_model_preparation_cannot_disable_or_delay_recording_stop`).
     - 이 hook은 writer 생존을 뜻하며 seal, finalize, recover, 등록이 모두 쓴다.
     - 녹음 독립 불변식에 어긋나므로 등록하지 않는다.
   - 대신:
     - 종료 ACK가 실패한 작업은 runner가 Job local reader를 끝내지 않는다.
     - 삭제·복구는 기존 `ACTIVE_READER_OR_WRITER`로 실제 child 종료를 기다린다.
     - 이후 reap이 성공하면 reader를 끝낸다.
   - M15는 이 reader 유지 제거로 바꿔 검출했다.
2. **필요한 관측만 수행**
   - CPU_ONLY와 CPU 전용 backend는 GPU를 관측하지 않는다.
   - RAM은 known 요구량의 후보 장치에만 읽는다. UNKNOWN 요구량에서는 RAM을 읽지 않고 "RAM 관측 NOT_OBSERVED"로 표시한다(§4.3 "RAM 관측 상태는 표시한다"의 해석).
   - 이유: 운영 catalog가 비어 있어 RAM 값이 어떤 판단에도 쓰이지 않는다. 또 범위 밖 기존 시험이 bridge를 지날 때 실제 OS API를 부르지 않게 하기 위해서다.
   - 실제 판단에 쓰지 않더라도 RAM 여유를 늘 보여 주기를 원하면 관측기 한 곳만 바꾸면 된다.
3. **STT 결과 게시 뒤 종료 ACK 실패**
   - 전사 task는 자기 fence로 결과를 게시한 뒤 lease 밖으로 나온다. 그래서 ACK가 실패해도 Job은 SUCCEEDED다.
   - 이때 lease는 REAP_PENDING으로 유지되고 reader도 유지되며, "작업자 종료 ACK 대기 · RESOURCE_LEASE_HELD"로 표시된다. 다음 무거운 작업은 `RESOURCE_LEASE_HELD`로 배정되지 않는다(§7.2 "logical과 physical은 별개").
   - 게시 전에 ACK를 요구하려면 task 구조를 바꾸는 별도 결정이 필요하다.
4. **mutation 수:** 지시문은 23이었다. 승인된 개정 ⑧(P11b 32,593/24)에 따라 M30을 포함한 24개를 실행했다.
5. **compute type 별칭:** CTranslate2가 CPU int8을 `int8_float32`로 보고할 수 있어 허용했다. 실제 로드 객체의 보고값은 외부 게이트다.
6. **Job별 worker:** live STT도 Job마다 모델을 다시 로드한다(§5.1 C00 승인 내용). 지연 증가는 측정하지 않았다.

### G11R 처리

| ID | 처리 |
| --- | --- |
| G11R-01 | 등록 identity와 backend 대조(`app/ai.py`). 시험: ollama→REMOTE, faster_whisper→REMOTE, openai→LOCAL_CT2 표지가 세 정책 모두에서 Job 0으로 거부된다 |
| G11R-02 | runner settle-under-lock(`jobs/runner.py`). 시험: `JobStore.fail` commit 직후 worker를 잡아 둔 barrier에서 `stop()`이 기다리고, RESOURCE·BUDGET·REMOTE_UNKNOWN BLOCKED가 모두 보존된다 |
| G11R-03 | 요약·화자 dispatch 재검사 행, 실제 `diarize()` submit의 admission(Job 생성 전)·capture·tick 행, DTO 중복 key와 `2**63` 경계 행을 추가했다 |
| G11R-04 | 미룸(G-P08 push 뒤 C00 결정) |
| G11R-05 | T27·T28은 `prepare_execution` wrapper가 기록한 예외 코드를 손으로 쓴 집합과 대조하고, 표시 문자열에는 그 코드가 보이는지만 확인한다 |
| G11R-06 | `owned`와 `policy_applies`로 분리했다. A 36행이 두 값을 모두 확인한다 |
| G11R-07 | 아래 "G-P11a 결과 절 정정" |

### G-P11a 결과 절 정정(G11R-07)

G-P11a 결과의 "coverage가 닿지 않은 새 경로" 목록은 실제와 달랐다.

- `ui/ai_bridge.py:470`은 기존 `prepare_execution` 예외 분기다. 새 1차 gate의 live 억제 줄은 458이었다.
- 화자 구분 submit의 `admit_diarization`(780)·`capture_diarization`(783)은 coverage와 판정 assertion이 둘 다 없었다. 이 줄들은 QThreadPool thread에서 돌아 coverage가 추적하지 못하는 측정 공백이었다.
- `resources.py`의 미적중은 기존 `probe_gpus`(52-61)와 legacy `acquire`(92-93)였다.

이번 단위의 `test_aux_diarize_submit_admits_and_captures`는 실제 `diarize()`에서 admission이 Job 생성 전에 1회 불리고 capture가 그 Job에 1회 불리는 것을 assertion으로 확인한다.

### 시험

| 파일 | node | 의미 행(P11b) |
| --- | ---: | --- |
| `tests/unit/test_resource_policy.py` | 299 | P 31,104(한 node에서 batching, 행마다 ID와 손 oracle 대조), E 72, C017~096(직접 fail·runner)·C101~120(`block_pending`), T01~15·21·22·24·25·26. 보조: lease 전이표 24, DTO 중복 key·`2**63`, 등록 identity 3, inventory 3(nvidia-smi 출력·결합 사유·필요 관측과 cache, 모두 주입) |
| `tests/integration/test_resource_policy.py` | 394 | G 120(실제 `join_identity`→plan→lease→bridge `OwnedSTT` 인자·facts), R 144(bridge `local_source`→plan→worker 인자), L 96(실제 scheduler의 waiter·ACK trace), S 20(AIService owned path), T16·17·18·23. 보조: stop barrier 3, 요약·화자 dispatch 재검사, 보유 lease 다음 Job, UNKNOWN+보유 worker |
| `tests/ui/test_resource_policy_ui.py` | 200 | Ub 48(실제 MainWindow tick 표시), T29(실제 bridge 로컬 STT의 legacy `choose` 0). 보조: 실제 `diarize()` submit의 admission·capture |
| `tests/property/test_resource_policy_case_space.py` | 6 | Q 864(행마다 실제 `BoundedRunner` trace, 한 node), 계속 도착하는 interactive 아래 background 진행 trace, 32,799 ID 감사 |

- 기대값은 모두 손으로 쓴 표와 규칙이다(P·E·G·R·L·Q·Ub·C 각 oracle). 제품의 plan·선택·전이 함수를 기대값 계산에 쓰지 않는다.
- fake는 관측(GPU·RAM)·worker·factory·profile만 바꾼다. plan·lease·runner·JobStore·AIService·bridge·tick은 제품 코드다.

### 결과

- 모든 실행은 격리 사본에서 했다: `git archive b925520` + 26파일, PYTHONPATH = 사본 src, 자식 import 출처가 사본임을 확인. 작업 트리의 G-P08 미완성 변경은 쓰지 않았다. 공통 옵션은 `-p no:cacheprovider`, OS TEMP 고유 basetemp, offscreen, `-W error::ResourceWarning`이다.
- **신규 4파일 단독: 899 passed, 18.21초**(60초 게이트 안). 가장 긴 node는 Q 1.56초, T27·T28 각 약 1초, P cube 0.44초다.
- **case ID 감사:**
  - 개정 전체 32,799를 확인했다.
  - P11a 206과 P11b 32,593이 각각 누락·중복·초과 0이고, 두 집합의 교집합은 0, 합집합은 전체다. skip은 0이다.
- **CI core 동등**(`.github/workflows/core.yml` 단계와 flag 그대로):
  - ruff check, format --check(184 files), mypy(90 source) 통과
  - 전체 pytest **21,275 passed**(failures·errors·skipped 0), 1,276.4초, JUnit LF SHA-256 `23601156…`
  - 총 coverage 92.29%
  - `scripts/check_coverage.py` 묶음별 예산 전부 PASS(line/branch %): domain 100/100, capture 99.85/98.57, jobs 99.29/96.23, storage 96.52/92.43, security 98.11/94.43, content 99.59/98.75, all 93.69/88.05
  - 새·변경 모듈 coverage: `resource_catalog.py` 100%, `failures.py` 100%, `resources.py` 89%(미적중은 legacy `probe_gpus` 본문과 방어·검증 분기), `gpu_inventory.py` 69%(실제 `GlobalMemoryStatusEx`·CUDA count child·child 실행은 계약상 시험에서 부르지 않음), `ai_bridge.py` 80%
  - CI 사본의 이 문서는 결과 절을 쓰기 전 판이다. 그 차이는 실행 대상이 아닌 문서뿐이다
- **mutation 24/24 검출, import·수집 오류에 따른 invalid 0.** mutant마다 새 격리 사본에 하나만 적용했고 import 출처를 확인했다. 실행 대상은 신규 4파일, `test_gpu_runtime_ui.py`, `test_blocked_reasons.py`다.

| ID | 결함 | 실패 | 목표 적중(예) |
| --- | --- | ---: | --- |
| M04 | GPU_ONLY 실패 시 CPU 실행 | 86 | G 45, P cube |
| M05 | UNKNOWN probe에 cache 값 사용 | 2 | T12, P cube |
| M06 | probe UNKNOWN/UNAVAILABLE을 GPU 없음으로 | 3 | T12, T23, P cube |
| M07 | 요구량 1GiB 고정 | 58 | E, P cube |
| M08 | known CPU의 fallback RAM 검사 생략 | 18 | R 17 |
| M09 | 여유 `>=`→`>` | 1 | P cube |
| M10 | GPU0만 사용 | 24 | G 12(GPU1만 적합) |
| M11 | host index를 CUDA ordinal로 | 33 | G 20(bus 순서 뒤바뀜) |
| M12 | 명시 profile의 runtime 불일치 허용 | 7 | E 7 |
| M13 | lease 전에 worker 생성 | 39 | S, Ub, 보유 lease 다음 Job |
| M14 | 종료 ACK 실패에도 slot 해제 | 61 | T21, L |
| M15 | ACK 전 Job local reader 해제 | 11 | Ub ACK 대기 10, 보유 lease 다음 Job |
| M16 | priority를 FIFO로 | 2 | Q, 진행 trace |
| M17 | 공정 oldest turn 제거 | 2 | Q, 진행 trace |
| M18 | 취소된 waiter에 grant | 5 | T22, L |
| M19 | runtime 실패를 source CUDA까지 | 6 | R(native+제외 runtime) |
| M20 | CPU_ONLY에서 runtime/source 확인 | 48 | R(CPU_ONLY 전부) |
| M21 | 로드 객체 facts 확인 제거 | 13 | T16·17·18, Ub blocked |
| M22 | 새 코드를 FAILED로 소실 | 8 | C 7, catalog delta |
| M23 | UNKNOWN을 ACK 코드로 덮음 | 1 | UNKNOWN+보유 worker |
| M25 | UNKNOWN을 차단 예외로 | 169 | T25, S, P cube |
| M27 | UNKNOWN GPU 여유 기준 생략 | 48 | T26, P cube |
| M28 | UNKNOWN을 0/known으로 | 28 | S, Ub, P cube |
| M30 | UNKNOWN 요구량을 legacy `choose`로 | 4 | T29 |

- M14의 첫 형태(close 실패를 무시)는 살아남았다. 별도의 child 생존 확인이 같은 slot을 계속 보유하게 해 결함이 가려졌기 때문이다(이중 방어). 그래서 계약 의미에 맞게 "ACK 실패에도 slot 반환"으로 다시 정의했고, 이 형태는 61건으로 검출됐다.
- M25의 setup 오류 240건은 import·수집 오류가 아니다. UI module fixture가 "UNKNOWN profile의 CPU Job은 성공해야 한다"고 단언한 assertion 실패다. 목표 행(T25·S)도 assertion으로 실패했다.
- M09의 첫 판정 "미검출"은 대상 이름 목록에 P cube node를 빠뜨린 harness 오류였다. 이름을 고쳐 다시 실행해 검출을 확인했다.
- mutation은 inventory 보조 시험 3건을 추가하기 전에 실행했다. 추가는 node를 늘릴 뿐이므로 검출 판정에 영향이 없다.

### 미검증·한계

- 실제 GPU·nvidia-smi·CUDA ordinal probe child·`GlobalMemoryStatusEx`·모델 로드·다중 GPU·MIG·remapping 환경은 실행하지 않았다. 모두 fake 주입으로 검증했다.
- CUDA ordinal↔UUID 대응 조건(PCI bus 순서)이 실제 드라이버에서 성립하는지는 외부 게이트다.
- 운영 profile catalog는 비어 있다. 첫 실제 profile은 측정 근거를 갖춘 별도 단위다. UNKNOWN 실행 허용은 모델별 메모리 검증 완료가 아니다.
- priority·공정 turn은 유한 trace의 진행만 보인다. 시간 SLA와 영구 hang 진행 보증은 아니다.
- 재시작 고아 child 종료 증명은 자동화하지 않았다. 재시작 뒤 캡처와 lease는 메모리에 없다.
- 정책 값 저장(G-P16)과 공용 `status.py` 행동 연결(G11R-04)은 남아 있다.
