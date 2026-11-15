# L07 GPU 받기 화면·장치 선택 독립 검토

2026-11-15, recoryn-desktop(w5:p3) 검토 / C00 작성·통합. 배정 L07 / push L-P07. **REVIEW_READY / OPEN 5건(S2 4건: L07-U01·U02·U03·U05, S3 1건: L07-U04, S0·S1 0)**. 다운로드 검토와 동일한 취소 발견이 있으면 C00이 중복 연결해야 한다. 이 문서는 제품 전체·실제 GPU·법률·릴리스 승인이 아니다.

## 교육·범위·검토 snapshot

AGENTS·onboarding·현재 L07 배정표, workflow·품질 체계·case-space/push 규칙, 기존 제품 계약·결과와 관련 모델/추론 리뷰를 확인했다. 추가 정본은 license-review D10, l07-gpu-runtime-cases, license-results L-P07이다. git status/diff를 읽고 ONBOARDING_READY를 보고했다. 현재 staged/unstaged/untracked 변경을 보존했다. 쓰기는 이 신규 문서 하나이며 제품·시험·설정·인덱스·Git 이력은 수정하지 않았다. 추가 위임·pane/서버 제어·승인 UI 입력도 하지 않았다.

실제 GPU 탐지·런타임 다운로드·실제 CUDA/Whisper 실행·모델 weights·음성 캡처·계정·유료 호출은 하지 않았다. 실제 GPU/다운로더/런타임/provider 대신 fake를 주입하고 offscreen Qt와 고유 TEMP를 사용했다. 삭제 확인은 fake runtime에 연결한 메모리 내 QMessageBox 응답 대조이며 실제 설치·삭제 승인 대행이 아니다. 작은 model.bin/config/tokenizer placeholder는 유효 모델이 아닌 고정 문자열이고 fake adapter가 읽거나 추론하지 않는다. 원본 불변·녹음/AI 분리·기본 무전송·Credential Manager 계약을 유지했다.

| 검토 대상 | raw SHA-256 |
| --- | --- |
| src/recoryn/ui/models.py | 2c4a777ecc60001dd9383b0f2c08836fca0a31f9f9c89fcc722612cdf4add77b |
| src/recoryn/ui/ai_bridge.py | 6afc3958d49d6fdfc18ff16a2dd4a856a14f28850e91d0734364371fafd09cbe |
| src/recoryn/models/gpu_runtime.py | b8c7613373dd4e60530304518ebde27b0b9dd4158bd4edbfc21b7edfc240457a |
| src/recoryn/app/inference.py | 902b5198adc3f4bc0b7b47e54620324a10fc6966fe89e8ac00fd4df44f911cb9 |
| tests/unit/test_gpu_runtime.py | 363e3de1bfe39cedad5cac4278af385f3745820c2109e8ccbc62f3cdf3e11d19 |
| docs/testing/l07-gpu-runtime-cases.md | dc932aed91b7ba4cdfeb6732ce41e1a05e31c13de42936dff7c965f81fc5daa3 |

모두 배정 hash와 일치하고 독립 driver 전후에도 동일했다. 인덱스 raw hash도 driver 전후 동일했다. 후보 build/l07-1794744757의 smoke PASS·GPU 런타임 미동봉·native105는 C00 제출 증거로 구분한다. 후보 EXE/빌드는 실행하지 않았으며, CPU/no-inference smoke가 아래 GPU 화면 경계를 검증한 것으로 취급하지 않는다.

## 독립 분모와 실행 경계

실제 DesktopAI._transcribe → DesktopAI.operation → 실제 Task.run → 실제 ResourceScheduler.choose를 통과시키고, GPU 탐지/native 지원/사용자 runtime/provider만 fake로 바꿨다. 실제 프로세스·추론은 없다. 별도 expected oracle는 정책과 명시 GPU 조건의 conjunction이고 구현 gpu_source의 반환값을 기대값으로 재사용하지 않는다.

| 가족 | 분모·실제 대조 |
| --- | --- |
| 장치·runtime 경로 | 정책3 × 상태3 × GPU 유무2 × 이전 실패2 × native 지원2 = **72행**. 실제 유일72, 별도 binary ID 집합과 대조해 누락0·중복0·추가0 |
| 받기 화면 guard | 동의2 × AI idle2 × 모델 작업 busy2 = **8행**. 실제 유일8, 정상 시작1·차단7 |
| 실패 이력 | 명명한6개 trace: 현재 마지막 GPU 실패, 앞선 GPU 실패+뒤 다른 작업, 다른 세션, 이전 실행 이력, 다른 작업종류의 GPU 코드, 일반 타 작업 실패 |
| 삭제 확인 | AI 사용 중·모델 작업 중·idle+No·idle+Yes의4개 대조 |
| 취소 게시 경계 | 다운로드 전·다운로드 반환 직후·압축 해제 중의3시점 |
| worker 인자 | CPU/CUDA2 × runtime 없음/있음2 = **4행** |

실패·취소·GPU_ONLY 거부를 구성 불가능으로 제외하지 않았다. 다만 위 가족은 선언한 대표 집합이며 모든 파일·스케줄·작업 이력의 전체 직적이 아니다. 특히 실패 이력6개는 명명한 trace로, 임의 길이 상태 모델의 전수 증명이라고 하지 않는다.

72행의 raw 결과는 **CPU44 / CUDA8 / RESOURCE_GPU_UNAVAILABLE20**이며 계약과 전부 일치했다. CUDA+사용자 runtime일 때만 runtime root가 LocalSTTProcess로 전달되고 native 경로는 None이었다. 이 raw 선택 성공과 UI 표시 성공은 분리해야 한다(U02).

## 통과한 화면·계약 경계

동의 없는 화면 요청은 작업을 queue하지 않고 fake install 호출0이었다. 동의·idle·비busy일 때만 실제 _run이 한 task를 만들며, 중복 요청은 두 번째 task를 만들지 않았다. 완료 후 동의 칸은 해제됐다. UI 취소 단추가 실제 cancel Event를 설정하고, queue된 fake install을 시작하기 전 취소하면 MODEL_DOWNLOAD_CANCELLED로 끝나 활성 상태가 생기지 않았다. 늦은 취소는 U05와 구분한다.

AI가 이미 사용 중이거나 모델 작업이 이미 있으면 GPU 삭제 확인 자체를 열지 않았다. idle 확인의 기본 선택은 No이며 No는 작업0, Yes는 fake remove1회였다. 이는 클릭 시점 guard의 통과이고, 삭제를 queue한 뒤 새 AI 작업이 들어오는 역순은 U03으로 남는다.

화면에는 약관4개의 URL·적용 대상, 587952939 bytes, 설치 위치와 동의 칸이 있다. 실제 약관 수락의 법적 효과나 upstream 원문의 완전성은 판정하지 않는다. 한국어 정책 안내 중 잘못된 일반화는 U04에 기록한다.

LocalSTTProcess._start의 fake spawn context4행에서 CPU는 runtime 인자를 받아도 유효 runtime=None·worker4인자, CUDA+runtime 없음도4인자, CUDA+runtime 있을 때만5인자였다. 실제 기존 독립 `_hanging_owned_worker(model_path, device, requests, replies)`의 timeout/cancel2행도 통과했다. 기존4인자 API 호환은 유지된다.

## L07-U01 / S2 / OPEN — 실패 추적이 선택 세션의 마지막 작업에 종속됨

**원 반례:** 실제 DesktopAI.tick에 fake JobStore history를 주고, 이후 실제 _transcribe를 실행했다. native=False, 사용자 runtime READY, GPU0/충분한 메모리, CPU fallback 허용 정책으로 고정했다.

| 이력/선택 | 기대 | 실제 |
| --- | --- | --- |
| 현재 선택 세션 마지막 GPU_RUNTIME_DAMAGED | 이후 GPU 제외·CPU | _gpu_failed=True·CPU(양성 대조) |
| 같은 세션 `[GPU 실패, 다른 작업 성공]` | GPU 실패가 이후 작업 때문에 사라지지 않음 | _gpu_failed=False·다음 CUDA |
| A에서 GPU 실패, B가 선택됨 | 앱 실행 중 runtime 실패 관측이 선택에 의존하지 않음 | A 이력을 읽지 않아 False·다음 CUDA |
| 새 DesktopAI + 이전 실행의 실패 이력, runtime READY | 현재 실행의 새 실패와 구분 | 즉시 True·다음 CPU |
| 다른 작업종류(summary)에 같은 GPU prefix 코드 | 대상 GPU 전사 실행과 구분 필요 | kind 확인 없이 True·CPU |
| 일반 타 작업 INFERENCE_PROCESS_FAILED | GPU 후보 유지 | False·CUDA(음성 대조) |

이력은 공개 JobRecord와 같은 소비 형태의 dataclass fake다. 이전 실행 이력의 재시작 DB 복구까지 새로 실행한 것은 아니며, fresh bridge가 기존 history를 소비하는 제어 경로를 확인했다. 오래된 실패 뒤 runtime을 다시 받아 READY인 경우에도 tick가 그 오래된 마지막 실패를 새 실패처럼 사용한다.

원인은 tick가 `list_for_session(selected)[-1]` 하나의 error prefix만 보고 전역 boolean을 갱신하는 점이다. 작성자 문서의 “이번 실행 중 GPU 실패”와 일치하지 않으며 다른 세션/작업·이전 실행의 관계를 판정하지 않는다. 화면 선택과 무관한 실제 GPU 실행 오류 관측, 실행 identity/세대와 이미 처리한 실패 구분이 필요하다. 임의 과거 이력을 모두 scan하는 것만으로 오탐이 해결됐다고 보지 않는다.

## L07-U02 / S2 / OPEN — GPU 준비·설치 오류 코드가 Task 경계에서 사라짐

72행 중 GPU_ONLY에서 raw RESOURCE_GPU_UNAVAILABLE인20행 모두 실제 Task.run을 거치면 상태 줄은 **OPERATION_FAILED_MEDIA_PRESERVED**였다. 예외를 driver 바깥에서 따로 잡아 UI를 흉내 낸 결과가 아니라, 실제 operation의 예외를 기록한 뒤 그대로 Task의 sanitizer로 다시 올려 실제 failed signal/UI를 확인한 것이다.

또한 실제 ModelPanel.download_gpu → _run → Task에 fake install이 `StateConflict('GPU_RUNTIME_UNSUPPORTED')`를 내게 하면 상태는 **모델 작업 중단: OPERATION_FAILED_MEDIA_PRESERVED · 검증 전 파일은 활성화되지 않습니다.**가 됐다. 설치 불가 플랫폼과 일반 저장/작업 실패가 구별되지 않는다.

공통 ui/tasks.py의 SAFE_CODES에 해당 준비/설치 코드가 없어 지워진다. Job history에 이미 기록된 GPU_RUNTIME_*를 tick가 직접 보여주는 경로와는 별개다. 안전한 고정 오류 코드만 허용하는 원칙을 유지하면서 RESOURCE_GPU_UNAVAILABLE 및 GPU runtime 실패 이유를 사용자에게 전달해야 한다. 기존 공통 Task 경계와 연결된 문제이므로 수정 범위 조정은 C00 책임이다.

## L07-U03 / S2 / OPEN — GPU 삭제 대기 뒤 새 AI 시작을 막지 못함

**결정적 원 순서:** (1) 실제 MainWindow._models_idle이 True인 상태에서 실제 ModelPanel.remove_gpu를 요청하고 fake 확인 Yes로 _run에 삭제 task를 queue한다. (2) 모델 pool의 실행만 보류한 채 실제 DesktopAI._transcribe를 실행한다. (3) READY runtime을 고른 CUDA fake provider 작업이 등록되어 runner.active=1이 된다. (4) 보류한 삭제 Task.run을 실행하면 fake remove가 **ai_active=1** 상태에서 호출된다.

holding pool은 thread scheduler의 우연을 대신해 이 허용 순서를 고정한 barrier다. 실제 GPU 프로세스나 실제 runtime 파일을 삭제하지 않았다. 서로 다른 실제 UI/AI 작업 경로를 사용했으며 can_modify를 무조건 True로 고정해 만든 반례가 아니다. MainWindow._models_idle을 그대로 연결했다.

AI가 먼저 active일 때 삭제가 차단되는 정상 대조는 통과했다. 반대 순서에서는 _transcribe가 model_panel.task를 검사하지 않고, queue된 변경이 AI 시작과 직렬화되지 않아 “AI 사용 중 삭제 차단”을 보장하지 못한다. 사용 중 runtime 제거/활성화 실패로 이어질 수 있는 S2다. 원본 손실이나 무동의 전송으로 확대하지 않는다. 수정 후 양쪽 순서를 다시 확인해야 한다.

## L07-U04 / S3 / OPEN — CPU 복귀 안내가 GPU_ONLY 정책과 다름

모델 관리 탭에는 “실패하면 CPU로 돌아갑니다”, NOT_INSTALLED의 “전사는 CPU로 합니다”, DAMAGED의 “그동안 CPU로 합니다”, 삭제 확인의 “이후 전사는 CPU로 합니다”가 있다. 그러나 GPU_ONLY에서 runtime/GPU가 없으면 raw 결과는 RESOURCE_GPU_UNAVAILABLE이며 CPU 실행은 등록되지 않았다.

안내를 CPU 허용 정책에서만 fallback한다는 조건과 맞춰야 한다. 문구를 맞추기 위해 GPU_ONLY를 자동 CPU 전환으로 바꾸면 명시 정책을 위반하므로 허용할 수정이 아니다. 현재 READY 표시는 cheap 상태 검사이며 전체 hash/GPU 가용성·실행 성공 보장으로 해석되지 않도록 해야 한다.

## L07-U05 / S2 / OPEN — 다운로드 뒤 취소는 활성 게시를 막지 못함

**원 반례:** 실제 GpuRuntimeManager.install에 fake 다운로드와 fake extract만 주입했다. 네트워크0, 실행 불가능한 작은 stub만 고유 TEMP에 만들었다. fake extract는 필수 파일의 정상 manifest shape/hash를 만들되 실제 바이너리를 로드하지 않는다.

| 취소 시점 | 실제 결과 |
| --- | --- |
| 다운로드 시작 전 | MODEL_DOWNLOAD_CANCELLED, active 없음, NOT_INSTALLED(대조) |
| fake 다운로드가 반환되는 경계 | cancel=True인데 install 정상 반환, active 존재, READY |
| fake 압축 해제 중 | cancel=True인데 install 정상 반환, active 존재, READY |

install이 `_downloads.install` 이후 및 extract/활성 게시 전에 cancel을 다시 검사하지 않는다. UI 취소 Event는 전달되지만 받은 뒤 해제·게시 단계에서는 무시된다. 이는 실제 archive 해시/안전성 검사에 대한 반례가 아니라 취소 의도와 게시 순서에 대한 반례다. case 문서의 “취소하면 활성 런타임이 생기지 않는다”를 현재 시험의 이미-set된 취소1행만으로 충족했다고 할 수 없다.

압축 해제·검증 중 취소 관측과 최종 활성화의 명시 순서가 필요하다. 다운로드 독립 검토에서 같은 원인이 나오면 이 ID를 그 발견에 연결하고 하나의 결함으로 통합한다. 취소를 이유로 검증 전 파일을 활성화하거나 원 반례 조건을 완화하지 않는다.

## 시험 oracle 검토·실행 증거

새 unit의 gpu_source 표는 helper 반환만 검사하고 실제 GPU 유무·ResourceScheduler·Task/UI 경계를 지나지 않는다. panel fixture는 _run을 monkeypatch하므로 실제 중복 guard·오류 sanitizer·AI와 변경의 역순을 검증하지 않는다. 취소 시험은 시작 전 이미-set된 Event만 다룬다. 이 때문에 관련 시험 PASS와 위 OPEN은 모순되지 않는다.

읽은 diff에서 기존 독립 시험의 assertion 삭제·조건 완화를 발견하지 않았다. 기존 worker4인자 계약 수정의 독립 timeout/cancel 반례도 통과했다. 이 판단은 현재 배정 diff/선택 시험 범위이며 전체 source·archive 보안·실장비 품질의 승인으로 확대하지 않는다.

독립 pytest 명령:

```powershell
$l07TestEvidence = 'C:\Users\gangd\AppData\Local\Temp\recoryn-l07-ui-tests-88f1aec38d5945e087fb23c0fc19a10a'
$env:QT_QPA_PLATFORM = 'offscreen'
$env:PYTHONDONTWRITEBYTECODE = '1'
.venv/Scripts/python.exe -m pytest tests/unit/test_gpu_runtime.py tests/integration/test_model_runtime_independent.py::test_hung_owned_inference_child_exits_before_error_ack -q -p no:cacheprovider --basetemp "$l07TestEvidence/pytest" -W error::ResourceWarning --junitxml "$l07TestEvidence/result.xml" --tb=short
```

**67 PASS / 4.75초**, JUnit failure/error/skip0. GPU unit65 + 기존 독립 worker2다. 작성자 전체 회귀·후보 smoke와 합산하지 않는다. 72행과 UI trace는 별도 Python assertion driver이며 pytest node 수가 아니다. 열린 문제를 관측한 JSON을 남기는 driver의 exit0도 제품 PASS로 해석하지 않는다.

독립 fake/UI 증거 root: `C:\Users\gangd\AppData\Local\Temp\recoryn-l07-ui-review-5091861c14ce454d911b27af6b5fa7d5`. `review.py`/`extra.py`를 `.venv/Scripts/python.exe -W error::ResourceWarning <script> <새 TEMP>`로 실행했다. review.py는 Qt offscreen과 socket/DNS 차단을 사용하고 실제 탐지/다운로드/provider는 fake로 대체했다. extra.py도 다운로드·추출·프로세스 생성은 fake만 호출한다. 재현은 증거를 덮어쓰지 말고 새 TEMP에 scripts를 복사해 수행한다.

| 증거 | raw SHA-256 |
| --- | --- |
| review.py | 29fcdd72c98506c75f5b4150a6a0e963487ad04de1db2209ec51aef28e056103 |
| result.json | 101ebae7061a49ddd9cecc52bedbebacffc974a51e46f46bc9d2e828acb3c1aa |
| extra.py | c3bd96afafd8adb6f47db780eb1f70b5ceb793042dd918702b411f58932acf32 |
| extra.json | a8705fe27cc2b0da7ea0a01ca62264d10eec742a0e93016d0f2bf14f36a76ff7 |
| case-audit.json | eb278e5732953cb935698acfa0920e6aaa1c52611cf0b2074c154102e24fe58f |
| 위 pytest root/result.xml | 7f870ec0c0f3f49af0813fd6b25fd851cf3ed20e0b7a2f226c8e7f0fb3202a8e |

최종 **REVIEW_READY / OPEN 5건(S2 4, S3 1)**. 원 반례·검토 hash를 C00에 전달했으며 제품을 직접 고치지 않았다. C00의 수정 후 동일 검토자 재확인과 정확한 통합 tree/후보·원격 CI가 필요하다. 실제 음성·weights·GPU/드라이버·네트워크 다운로드·실계정·법률·G3/G4는 이 리뷰에서 NOT_RUN이다. C00의 별도 실장비 관측은 작성자 증거로 남기고 이 오프라인 검토와 혼합하지 않는다.


## L07 2판 재확인 — 기존 U01~U05 RECHECKED, U06 OPEN

C00 명시 재배정으로 같은 검토자가 원 반례를 다시 실행했다. **이 절이 최신 판정이며 앞선 OPEN 5건과 초기 증거는 이력으로 보존한다.** AGENTS·L07 변경 배정·case 문서 2판·license-results를 재확인하고 ONBOARDING_READY를 보고했다. 쓰기는 이 문서 후단 추가뿐이다. 제품·시험·설정·인덱스·Git 이력은 변경하지 않았다. 실음성·실제 weights·GPU/런타임 다운로드·실제 CUDA 실행·계정·유료 호출·추가 위임·승인 UI 대행은 하지 않았다.

### 재확인 입력

| 대상 | raw SHA-256 |
| --- | --- |
| src/recoryn/ui/ai_bridge.py | 3f5818e243af3fa494970cb51bb4e6c918c32ec7be6953295c3f28037435aad7 |
| src/recoryn/ui/models.py | eb1c96452bddcfa90fc88388345ba07ccea55738a86b5599d6e72f6edfe8edaf |
| src/recoryn/ui/main.py | 653bf9eaacba79398acaacf229633cd50fb83641f5fb754390b789cc929c966d |
| src/recoryn/ui/tasks.py | 6ac4d61b4fd3bf03a283d92297d7782b7ae07cc16adfd6ae6419a2721f24fbdc |
| src/recoryn/models/gpu_runtime.py | 407e22642dc9120cb18b66ee16692cd83f842d59ad246d5292dd8989a969af5e |
| src/recoryn/app/inference.py | a8c54f53666056e9863850164dfb3857f742a1f713740e54295767e9101da079 |
| tests/unit/test_gpu_runtime.py | 15faa45e26edb7698ac2c059e9fcf3e032040ccbe2369d3cc385ff23f6a6d250 |
| tests/ui/test_gpu_runtime_ui.py | fdf08794621a07f6e086133d762cb3905620c5c539ac10a6c8caf5e31c563c91 |
| docs/testing/l07-gpu-runtime-cases.md | 3eb2a2da09fd14cd194b941a271a5d92171391a60722d41bf4ee1fa2317c5ffe |
| docs/implementation/license-results.md | db9678b295cf10c9576ddddc06589f1dd7b31bc44befb7f438a9f3fc4e2cef13 |

모두 제출 hash와 일치했고 driver 전후 10개 입력도 동일했다. 인덱스 hash도 driver 전후 같았다. C00의 전체7692 PASS·mutation19개·실장비 검증은 작성자 보고로 구분한다.

### 72행과 원 반례 재실행

원래72개 ID를 모두 유지했다. 정책3 × runtime 상태3 × GPU 유무2 × 이번 실행의 동일 runtime 세대 실패2 × native 유무2의 독립 분모72와 실제 ID를 대조해 유일72·누락0·중복0·추가0이었다. 실제 DesktopAI._transcribe → operation → Task → ResourceScheduler를 거치며 GPU 탐지/runtime/provider만 fake로 대체했다.

2판의 명시 계약에서는 실패가 차단하는 대상이 **사용자 runtime뿐이며 native는 유지**된다. 이에 해당하는6행만 1판과 기대 장치가 다르다. GPU_ONLY의3행은 거부→native CUDA, CPU fallback 정책의3행은 CPU→native CUDA다. 이6행을 제외하지 않고 전72행을 실행했으며 변경 ID를 case-audit-r2.json에 기록했다. raw 결과는 **CPU41 / CUDA14 / RESOURCE_GPU_UNAVAILABLE17**로 계약과 일치했다.

원 U02의20개 거부 조건도 전부 다시 실행했다. 위3행은 새 계약상 정상 native CUDA, 나머지17행은 모두 RESOURCE_GPU_UNAVAILABLE이 실제 상태 줄에 표시됐고 일반 오류 변환은0이었다. 설치 GPU_RUNTIME_UNSUPPORTED도 실제 ModelPanel._run/Task를 거쳐 표시되며 실패 후 GPU 상태가 갱신됐다.

| 원 발견 | 독립 재확인 | 판정 |
| --- | --- | --- |
| U01 실패 추적 | 원6개 trace를 재실행. 첫3개는 현재 worker 자신의 GPU 실패를 주어 세션 선택/후속 작업과 무관하게 CPU. 이전 실행 이력·타 kind·일반 실패만으로는 차단하지 않음 | RECHECKED |
| U02 원인 코드 소거 | 위17개 거부와 설치 오류가 고정 code로 실제 UI에 표시 | RECHECKED |
| U03 삭제 대기→새 AI 역순 | 기존 GPU worker를 먼저 닫음. 삭제 task 대기 중 새 AI는 CPU이며 runtime을 쓰지 않음. AI가 먼저 busy면 삭제 확인을 열지 않음 | 원 반례 RECHECKED. 확인 중 별도 경계는 U06 |
| U04 무조건 CPU 문구 | 약관·상태·삭제 확인에 CPU 허용/GPU 전용 정책과 소스 native 예외를 구분 | RECHECKED |
| U05 늦은 취소 | 원3시점에 게시 직전/직후를 추가 확인. 게시 전 취소는 차단, 게시 후 취소는 이미 성공 | RECHECKED, 다운로드 검토 L07-04와 동일 원인 |

현재 worker 실패→CPU→CPU→runtime 세대 변경→CUDA를 확인했다. runtime 실패 뒤 native가 가능하면 CUDA이며 runtime 인자는 None이었다. 별도로 실패 없는 warm CUDA→다른 세대 CUDA에서 기존 worker를 닫고 새 worker를 만들면서 job config_key는 같은 model:device로 유지했다. 프로세스 재사용 key에만 세대가 반영된다.

### 취소·화면·release 경계

실제 GpuRuntimeManager.install에 fake `_wheels`·extract/catalog 집합 확인을 주입했다. 게시/취소 순서의 대조이며 실제 archive pin/catalog 검증을 대신 승인하지 않는다. 실행 불가능한 stub만 TEMP에 만들고 실제 runtime을 받거나 로드하지 않았다.

| Event를 설정하는 시점 | 결과 |
| --- | --- |
| 다운로드 시작 전 | MODEL_DOWNLOAD_CANCELLED, 다운로드 호출0, active/staging 없음 |
| 다운로드 반환 직후 | MODEL_DOWNLOAD_CANCELLED, active/staging 없음 |
| 압축 해제 중 | MODEL_DOWNLOAD_CANCELLED, active/staging 없음 |
| 집합 검사 후·게시 직전 | MODEL_DOWNLOAD_CANCELLED, active/staging 없음 |
| 게시 후 다운로드 정리 시 | 설치 성공, active 있음, staging 없음(2판 성공 시점 계약) |

취소 기대값을 시작 전에 이미 설정된 Event로 축소하지 않았다. 블록 취소·실제 catalog의 unit 시험도 아래 선택 실행에서 통과했지만 전체 보안 검토는 별도 담당이다.

원8개 동의/idle/busy guard와4개 삭제 확인을 유지했다. release callback이 예외면 삭제 task를 만들지 않고 gpu_busy=False이며 worker를 닫지 못한 안내가 나왔다. 약관4개 URL·587952939 bytes·설치 위치가 표시되고, GPU_ONLY에 무조건 CPU를 약속하던 원 문구는 대상 항목에서 제거됐다. READY는 구성/크기 확인이며 실행 직전 전체 검증한다는 구분도 있다.

### L07-U06 / S2 / OPEN — 삭제 확인 중 시작된 AI worker를 닫음

**새 원 반례 순서:**

1. 실제 MainWindow._models_idle=True에서 ModelPanel.remove_gpu를 호출한다. 아직 gpu_busy=False다.
2. fake QMessageBox.question 안에서 **실제 QEventLoop와 QTimer.singleShot(0, …)**를 실행한다. timer callback이 실제 DesktopAI._transcribe/Task/ResourceScheduler로 CUDA fake 작업을 등록해 runner.active=1이 된다.
3. question이 Yes를 반환하면 remove_gpu가 can_modify/task를 다시 확인하지 않고 release_gpu_runtime을 호출한다.
4. runner.active=1인 CUDA worker에 close가 호출되고 삭제 task도 queue된다.

관측은 `qt_timer_during_confirmation=[device:cuda, active:1, model_task_pending:false]`, `closed_workers=[runner_active:1, device:cuda]`, delete_queued=True/gpu_busy=True다. 실제 MainWindow의 can_modify를 연결했으며 처음부터 busy이거나 무조건 True인 guard를 만들어낸 반례가 아니다. 최초 확인은 idle이고 확인 중 재진입으로 상태가 변했다.

question은 실제 사용자 승인을 조작하는 UI가 아닌 무창 시험용 대체다. 그 안에서 실제 Qt 중첩 이벤트 루프를 실행해, 실제 QMessageBox 대기 중 timer/queued callback이 진행되는 경계를 표현했다. 예를 들어 live STT의 기존 timer 기반 자동 준비도 이 대기 중 시작할 수 있다. 실제 GPU 처리·음성·weights는 사용하지 않았다.

새 gpu_busy 스냅샷은 **삭제가 queue된 뒤**의 새 AI를 막지만 확인 중에는 아직 False다. 확인에서 돌아온 시점의 상태 재검사 또는 확인부터 변경 완료까지의 명시 fence가 필요하다. release_gpu_runtime도 유휴 상태라고 가정해 현재 worker를 닫으므로 이미 시작된 GPU 작업이 중단될 수 있다. S2이며 원본 손실·무동의 전송으로 확대하지 않는다.

U03 원 역순 해결과 이 추가 modal 경계는 구분한다. 제품은 수정하지 않았고 C00에 원 반례를 보고했다. 원 조건을 유지한 동일 검토자의 재확인이 필요하다.

### 시험·후보·증거

```powershell
$l07r2Tests = 'C:\Users\gangd\AppData\Local\Temp\recoryn-l07r2-ui-tests-6b24cb2e7cbd4f26b49e72c061e979d3'
$env:QT_QPA_PLATFORM = 'offscreen'
$env:PYTHONDONTWRITEBYTECODE = '1'
.venv/Scripts/python.exe -m pytest tests/unit/test_gpu_runtime.py tests/ui/test_gpu_runtime_ui.py tests/integration/test_model_runtime_independent.py::test_hung_owned_inference_child_exits_before_error_ack -q -p no:cacheprovider --basetemp "$l07r2Tests/pytest" -W error::ResourceWarning --junitxml "$l07r2Tests/result.xml" --tb=short
```

**104 PASS / 6.73초**(unit99 + 실제 창3 + 기존4인자 worker2), JUnit failure/error/skip0. 이전67개와 합산하지 않는다. 새 창3시험은 실제 MainWindow를 거치지만 삭제 확인 중 재진입을 확인하지 않아 U06을 잡지 못한다. 읽은 시험에서 원 실패 기대를 skip/xfail이나 일반 성공으로 약화한 변경을 찾지 못했다. native6행의 기대 변경은 위 명시 계약 변경으로 구분한다. 작성자의 mutation19개/전체7692 PASS를 독립 재실행한 숫자로 기록하지 않는다.

후보 `build/l07r2-1794747580/smoke.stdout.json`은 PASS, raw hash `ef2ecdd092e92c520a56bc6bf39d80e102fb719ea0497f087cfd9abad0e2904a`다. 다만 후보 inputs의 ai_bridge.py는 **366dec5e7153d96f530a2bbcace3020fcf646781f9c0838f755d07e5b9c8f73d**로 이번 검토 3f5818…과 다르다. read-only diff에서 gpu_failure/gpu_runtime을 getattr로 읽는 호환 수정3곳만 확인했다. 다른3개 입력(models.py/inference.py/gpu_runtime.py)은 제출 hash와 같다. 이 후보를 이번 전체 검토 bytes나 앞으로의 U06 수정을 포함한 artifact 증거로 확대하지 않는다. 최종 재생성·대응 확인은 C00 게이트다.

독립 driver root: `C:\Users\gangd\AppData\Local\Temp\recoryn-l07r2-ui-review-22b3ee4ced9c40f6837e931f512e3836`. review_r2.py·extra_r2.py·modal_timer.py·warm_worker.py를 `.venv/Scripts/python.exe -W error::ResourceWarning <script> <새 TEMP>`로 실행했다. fake GPU/runtime/provider, Qt offscreen을 사용했고 실제 다운로드는 없다. modal driver는 새 OPEN을 관측해 JSON에 남기므로 exit0을 제품 성공으로 해석하지 않는다. 재현은 scripts와 무효 모델 placeholder를 새 TEMP에 두고 기존 증거를 덮어쓰지 않는다.

| 증거 | raw SHA-256 |
| --- | --- |
| review_r2.py | 64ac3e869373a0d1d79a613e6f98538d52ca5d67ac7150aec8d5cf010d21c0e0 |
| result.json | ead67f71209b7f16c05a45bad5c1b1bcd0010f512c9d3de3f05528eda50641e0 |
| case-audit-r2.json | 7eae93326ad4ea9ed35a0852c7b4922f57f2f6e8fac8075504940e9e7761221d |
| extra_r2.py | 4092758c8231ef62ad9f23fb37676fd24a60740a7b633266a8940c1855f54b49 |
| extra_r2.json | 83ab6a0b0f03bebfd2e4073eeae73a3a5ed44f39cf9b313c12778e5135705e74 |
| modal_timer.py | f818893bb900b644aab3395e4a5e5242bf91609e12a08a3c707bf0b16e365254 |
| modal_timer.json | 8560b388d92fc6d9959de88852b93225f6f2b879a803fbb8fa3805a1d6683582 |
| warm_worker.py | 5300ae66e4259cadd9cb08b04745e8faa559020fdec1a9c40965493677f02cf4 |
| warm_worker.json | 4f3919d6b6f5e55a6bd8125fe5860c249b57284bb110e09613fe6ef11ced1044 |
| 위 pytest root/result.xml | 391f7533df83217d42ed9bc771b84f7caf92988af4c86279d6b2fd30c9873659 |

**REVIEW_READY / U01~U05 RECHECKED / 최신 OPEN 1건(S2 L07-U06, S0·S1·S3 0)**. 동일 검토자의 U06 재확인과 C00 최종 통합이 남는다. 실제 음성·GPU/드라이버·weights·네트워크 수신·계정·G3/G4는 이 오프라인 검증으로 통과 처리하지 않는다.

## L07-U06 수정 재확인 — RECHECKED / 최신 OPEN 0

C00 명시 재배정으로 같은 검토자가 원 direct modal 반례와 실제 Qt 이벤트 루프·timer 반례를 재실행했다. **이 절이 최신 판정이며 기존 U06 OPEN과 원 반례는 이력으로 보존한다.** ONBOARDING_READY 뒤 기존 문서 후단만 추가했다. 제품·시험·설정·인덱스·Git 이력 수정, 실제 GPU/음성/weights/네트워크/계정/유료 호출·추가 위임·승인 UI 대행은 하지 않았다.

### 수정 입력

| 대상 | raw SHA-256 |
| --- | --- |
| src/recoryn/ui/models.py | 7e143d2f64ecccd4c2eb9b288518e4b3a093e46206a7d3fca6006c760907f6ff |
| src/recoryn/ui/ai_bridge.py | 9cd8498298c70b37b7705cd1d30de1e73533d4fefc9742a343800193d05a18fe |
| tests/ui/test_gpu_runtime_ui.py | 66cd8d91e349a22f390bc742c078ad0e1ecf15f2ec892b0e345a5755ad80a197 |
| docs/testing/l07-gpu-runtime-cases.md | f32b73e9058ab06c97692d928d755d1a559a945f9d51d460fee6cfb9854b753f |
| docs/implementation/license-results.md | 025d9874010315b4bd5c8f0a012c1dc90c633aaa2f1a4e902e0d3654732fdd18 |

제출 hash와 일치했다. 유지 대상 gpu_runtime.py=407e2264…, inference.py=a8c54f53…, tasks.py=6ac4d61b…, main.py=653bf9ea…도 2판과 같았다. 독립 driver 전후9개 입력과 인덱스 raw hash가 동일했다.

### 원 반례와 이중 방어

이전 반례의 시작 조건과 중간 상태를 유지했다. 최초 can_modify=True, model task 없음에서 삭제 확인에 진입하고, 질문 안에서 실제 DesktopAI._transcribe/Task/ResourceScheduler가 CUDA fake 작업을 등록해 runner.active=1이 된 뒤 Yes를 반환했다. direct 재진입과 **실 QEventLoop/QTimer.singleShot(0)** 재진입을 각각 실행했다.

| 관측 | direct 원 반례 | Qt timer 원 반례 |
| --- | --- | --- |
| 확인 중 장치/active/task | CUDA / 1 / 없음 | CUDA / 1 / 없음 |
| 확인 후 release callback 호출 | 0 | 0 |
| 활성 worker close | 없음 | 없음 |
| 삭제 task / gpu_busy | 없음 / False | 없음 / False |
| 상태 안내 | AI 사용 중 작업 완료·취소 뒤 삭제 안내 | 동일 |
| bridge 직접 release 호출 | AI_MODEL_CHANGE_REQUIRES_IDLE | 동일 |

확인 직후 상태를 다시 검사해 사용자 worker를 보존했다. panel을 통하지 않는 직접 bridge 호출도 active 작업자를 닫지 않았다. fake 질문은 실제 사용자 승인을 입력하는 UI가 아니고, 실제 GPU/runtime/provider는 사용하지 않았다.

독립 bridge 대조는 **busy2 × runner active2 × pending2 = 8행**이다. 별도 binary ID 집합과 실제 유일8행을 대조해 누락0·중복0이었다. 세 값이 모두 False인1행만 정상 해제했고, 나머지7행은 모두 AI_MODEL_CHANGE_REQUIRES_IDLE로 거부하며 같은 worker와 참조를 유지했다. 이는 선언한8행의 검증이며 임의 스레드 스케줄 전체의 증명은 아니다.

확인 중 다른 모델 task가 생기는 추가 재진입에서도 기존 task를 그대로 두고 release0·새 queue0이었다. 반대로 아무 작업도 없는 정상 삭제는 GPU worker를 닫고 task1개를 queue해 fake remove1회로 완료됐으며 task/gpu_busy가 정리됐다. 원 반례를 막기 위해 정상 삭제를 항상 거부하는 수정은 아니었다.

### 관련 회귀와 증거

새 UI 시험은 확인 중 busy가 생기면 worker 유지·삭제 미대기와 직접 bridge 거부를 assert한다. 이 조건을 제거하거나 완화하지 않은 것을 읽기로 확인했다. 독립 driver는 busy 설정 대체에 그치지 않고 원 반례의 실제 CUDA fake 작업 등록과 Qt timer 순서를 그대로 유지했다. C00의 UI mutation7개 검출은 작성자 증거이며 검토자가 독립 mutation을 다시 실행했다고 기록하지 않는다.

```powershell
$u06Evidence = 'C:\Users\gangd\AppData\Local\Temp\recoryn-l07-u06-recheck-dc8ee44dcfe84382ba47857207117946'
$env:QT_QPA_PLATFORM = 'offscreen'
$env:PYTHONDONTWRITEBYTECODE = '1'
.venv/Scripts/python.exe -W error::ResourceWarning "$u06Evidence/recheck_u06.py" $u06Evidence
.venv/Scripts/python.exe -m pytest tests/unit/test_gpu_runtime.py tests/ui/test_gpu_runtime_ui.py tests/integration/test_model_runtime_independent.py::test_hung_owned_inference_child_exits_before_error_ack -q -p no:cacheprovider --basetemp "$u06Evidence/pytest" -W error::ResourceWarning --junitxml "$u06Evidence/pytest.xml" --tb=short
```

driver exit0, 선택 회귀 **105 PASS / 7.54초**(unit99 + 실제 창4 + 기존4인자 worker2), JUnit failure/error/skip0이었다. 이전104개와 합산하지 않는다. 위 경로는 실제 증거이며 재현은 새 TEMP로 옮겨 기존 파일을 덮어쓰지 않는다. driver는 fake GPU/runtime/provider와 offscreen만 사용하고 실제 모델을 로드하지 않는다.

| 증거 | raw SHA-256 |
| --- | --- |
| recheck_u06.py | e9967778698272231d1d7613bb345a9536f6dfa9deadf3b7f68569ccba278c8a |
| result.json | 956a3d99cde1425a387640a4e7db50fd3dc3d53a19ae63b84039066394b3f89f |
| pytest.xml | 86f03626b50a029ce51c07fdc41bab2a374f07b1d6dd7adc7372d7e0fc2a8a09 |

**L07-U06 RECHECKED / 기존 U01~U05 RECHECKED 유지 / REVIEW_READY / 최신 OPEN 0건(S0·S1·S2·S3 모두0)**. 이전 후보의 hash 차이 기록은 유지하며, 이번 수정 hash와 연결한 새 후보 증거는 아직 이 절에서 확인하지 않았다. 후보 재생성·정확한 통합 tree·최종 CLOSED·Git/원격 CI는 C00 책임이다. 실제 GPU·음성·weights·네트워크 수신·계정·장시간·G3/G4는 미검증으로 남긴다.
