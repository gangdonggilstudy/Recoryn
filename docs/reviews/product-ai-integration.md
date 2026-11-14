# BR13 AI 통합 독립 검토

검토자: B13(ML·UX), 작성 대상: B10. B13 provider 자체 구현에 대한 승인 문서가 아니다. 허용된 이 문서와 `tests/integration/test_ai_independent.py`만 수정했다. 실제 장치·모델·네트워크·유료 호출은 실행하지 않았다.

## 범위와 초기 snapshot

`app/ai.py`, `app/inference.py`, `app/media.py`, `models/*`, `ui/ai_bridge.py`, `ui/content.py`와 관련 unit/E2E/UI 시험을 읽었다. `product-contracts.md`의 불변 revision·CAS·fence·삭제·bounded runner 계약 및 architecture의 UNKNOWN 우선 규칙을 기준으로 검토했다. B10이 병렬 수정 중이므로 아래 초기 digest와 후단 재확인 digest를 구분한다.

| 초기 대상 | SHA256 |
| --- | --- |
| app/ai.py | `6777A3DB6B3A6BF112A2C60B7E30A30BEBEBB0C96A9B784D750E7EDEA5B69B2A` |
| app/inference.py | `81DCBAEB8F648AE0082AA1E50D5E932962CA22764B27D800A4895A5E0C5398BB` |
| app/media.py | `C9BB66487A81FBAC95EBA988EE0C9DEBD540CEAFC98B281C7D79339DA0937825` |
| models/manager.py | `2CE21B0981DFA3CD566201510E2355323B318CE726EE7EC663A18ACAB1F18AAE` |
| models/resources.py | `B2341953770D0485D7E5373432CDBB6509AD03B271EC17C0B2AF817DAE3BF6A1` |
| models/ollama.py | `D38D20C77FB0C6B668E92D4F3C28ADE50F9814F06BB80BC93F6DDA50353CF651` |
| ui/ai_bridge.py | `56132FDD8EEAC55AD9368FF7B6CD578F89E99CF47701282FB2E610DE05F5989E` |
| ui/content.py | `257555F8B5348A36EC75B4CD3AC9FA60F046860461860F894E06EF9294DAF849` |

## 발견 사항 — 초기 재현 기록

각 ID는 아래 독립 시험의 함수명으로 재현한다. S1은 원격 상태·비용 해석 오류, S2는 기능·자원·취소 계약 오류다.

### BR13-01 · S1 · ai.py transcribe/summarize의 provider 결과→게시 순서

- 반례: fake provider 진입 event → `cancel_session`의 durable fence → provider가 `complete=False, outcome_known=False` 반환. `publish_*`의 stale-fence 오류가 원래 원격 불명 정보를 가려 runner가 `CANCELLED/blocked_reason=None`으로 확정한다. STT·요약 모두 관측했다. 미취소 대조군은 올바르게 `BLOCKED(REMOTE_UNKNOWN)`이다.
- 시험: `test_cancelled_unknown_result_remains_remote_unknown[stt/summary]`.
- 해결 조건: 관측한 원격 UNKNOWN은 이후 변환·게시·취소 오류보다 우선 보존하고 Attempt UNKNOWN / Job BLOCKED(REMOTE_UNKNOWN)으로 남긴다. 취소 fence 이후 revision을 게시하지 않으며 자동 재전송하지 않는다. ledger 정산 검증과는 별도다.

### BR13-02 · S2 · ai.py 중복 Job 제출 실패 분기

- 반례: provider를 event로 멈춰 첫 작업이 RUNNING인 동안 같은 입력·config를 다시 제출한다. JobStore가 기존 ID를 반환하고 runner가 중복 submit을 거부하자 `jobs.cancel`이 첫 작업을 CANCEL_REQUESTED로 만든다. STT·요약 모두 관측했다. 새 작업에 대한 진짜 queue 포화는 기존 작업을 보존하는 대조군으로 별도 검사했다.
- 시험: `test_duplicate_submission_preserves_running_job[stt/summary]`.
- 해결 조건: 중복은 기존 ID 반환 또는 기존 작업을 변경하지 않는 거부로 처리한다. 새 작업의 queue 포화 정리와 구분하고 동시 제출에도 기존 실행을 취소하지 않는다.

### BR13-03 · S2 · ai.py transcribe 입력 identity

- 반례: 동일 봉인 오디오에 `origin_ns=1_000_000_000`으로 성공(시작 0ms) 후 `origin_ns=0`으로 재요청한다. 클립 offset은 1000ms가 되어야 하나 같은 SUCCEEDED Job을 재사용하여 0ms 결과가 남는다. 원점은 초기 job key에서 빠져 있다.
- 시험: `test_changed_clock_origin_does_not_reuse_old_result`.
- 해결 조건: 고정 timeline mapping의 의미가 job identity에 포함되어 서로 다른 원점의 결과를 재사용하지 않는다. 불변 오디오 snapshot과 처리 계획의 identity를 구분한다.

### BR13-04 · S2 · models/manager.py install 최종 활성화

- 반례: fake downloader로 모든 bytes가 도착한 최종 progress callback에서 `cancel.set()`한다. 설치가 취소 오류 없이 target으로 rename되어 설치 목록에 활성화된다. 실제 다운로드는 없다.
- 시험: `test_model_cancel_before_activation_preserves_only_partial`.
- 해결 조건: 마지막 파일 검증 이후 취소와 최종 활성화의 경계를 정의하고, 활성화 전 관측된 취소는 부분 자료만 보존한다. 이미 활성화된 모델을 취소가 소급 삭제한다고 주장하지 않는다.

### BR13-05 · S2 · app/media.py prepare_clips의 단일 block 처리

- 반례: 8kHz 단일 3초 block에 `max_seconds=1`을 주면 3초 clip 하나가 생성된다. 기본값에서도 31초 block이 30초 상한을 넘는다. 기존 코드는 block 전체를 추가하기 전 flush만 하며 block 내부를 분할하지 않는다.
- 시험: `test_clip_limit_splits_oversized_source_block_without_loss[3-1/31-30]`.
- 해결 조건: 각 clip을 상한 이내로 나누고 source chunk frame offset·출력 offset·시각을 보존한다. 분할로 누락·중복·gap 압축을 만들지 않고 원본 hash·총 frame 수를 유지한다.

### BR13-06 · S2 · AI UNKNOWN·로컬 worker ack와 삭제의 통합

- 후속 반례: STT·요약 결과 UNKNOWN으로 Job BLOCKED(REMOTE_UNKNOWN) → `cancel_session` → `runner.stop`으로 모든 로컬 worker 종료 ack → `library.delete_session`. 실제 결과는 DELETE_PENDING이며 반복해도 원격 UNKNOWN Job을 active reader로 취급한다. worker가 없는데도 로컬 음성과 파생물을 삭제할 수 없다.
- 시험: `test_remote_unknown_does_not_prevent_local_media_deletion_after_worker_ack[stt/summary]`. 실제 SQLite·파일·worker를 사용하고 원격은 fake다. 기본 실행에서 strict XFAIL, `--runxfail` 독립 실행에서 STT·요약 두 FAIL을 확인했다.
- 해결 조건: 원격 UNKNOWN·비용 노출 이력은 보존하면서, 로컬 reader/worker ack가 끝난 경우 로컬 세션 삭제를 완료한다. 실제 media를 읽는 worker가 살아 있는 경우에는 삭제를 계속 보류해야 한다. UNKNOWN을 CANCELLED로 덮거나 살아 있는 reader의 보호를 일괄 해제하는 수정은 해결이 아니다. `_active_jobs`는 B10의 추가 소유 경계이므로 검토자는 수정하지 않는다.

## 실행 근거와 제한

초기 독립 시험은 5 PASS / 7 strict XFAIL이었다. `--runxfail` 독립 재실행으로 7 FAIL / 5 PASS와 위 실제 차이를 확인했다. 이후 원본 revision으로의 Qt 근거 탐색·사용자 편집의 재생 차단, 기본30초 상한과 실제 queue 포화 대조군을 추가했다. XFAIL은 미해결 기록이며 통과나 릴리스 승인이 아니다. 수정 반례가 통과하면 strict XPASS로 실패시켜 같은 검토자의 재확인을 요구한다.

미취소 UNKNOWN 부분 후보·자동 재시도 없음, 취소→삭제 intent→늦은 알려진 결과 차단→물리 삭제, 삭제 뒤 derive 재생성 금지, 원본 hash·트랙·clip 시간 품질·source frame 보존, 오래된 요약이 당시 revision으로 이동하는 Qt signal을 독립 검사한다. local process의 실제 missing-model spawn 경로는 기존 연관 시험으로 재실행한다.

~~~powershell
$br13Temp = Join-Path ([IO.Path]::GetTempPath()) ('recoryn-br13-' + [guid]::NewGuid().ToString('N'))
.venv/Scripts/python.exe -m pytest tests/integration/test_ai_independent.py -p no:cacheprovider --basetemp $br13Temp -q -rx -W error::ResourceWarning
# 초기 OPEN 반례를 일반 FAIL로 재현할 때 --runxfail을 추가한다.
~~~

실제 Faster-Whisper 모델 추론·GPU/CPU 부하·CER/WER·원격 계정·Ollama 후속 무전송·음성 품질·물리 재생·다운로드 서버와 전원 장애 내구성은 NOT_RUN이다. fake provider의 UNKNOWN은 전달 계약 검증이며 실제 외부 중단 성공을 증명하지 않는다. UI 키보드·스크린리더 전체 검증이나 설치물 인증도 이 검토로 승인하지 않는다.

## 수정 후 재확인

2026-11-14, 수정 전 기록을 보존하고 변경 코드와 같은 반례를 독립 대조했다. 초기 8개 실패 예상 case는 일반 회귀 시험으로 전환했다. 후속 barrier 반례 2개만 strict XFAIL로 남겼다. 이 시점 실행은 **17 PASS / 2 XFAIL**, Ruff lint·format 통과이며 ResourceWarning을 오류로 처리했다. 전체 제품 승인은 아니다.

| 수정 snapshot | SHA256 |
| --- | --- |
| app/ai.py | `FD8A04401AE6F1BBB910C4109C67C2978E1A90D3BD32EDC26401FFFBA1A133B9` |
| app/media.py | `E1AE8E6A1583963719A62500F69591D61E9A9819658A598C22AB6CAE0204F736` |
| models/manager.py | `B4667B420C882CD51710123E2BA317E6AD529584D4CA0AC12BC7718084E095AD` |

| ID | 재확인 상태 | 확인 코드·시험·남은 제한 |
| --- | --- | --- |
| BR13-01 | RECHECKED | `_OutcomeGuard`와 provider 결과 직후 unknown 관측이 게시 오류보다 앞선다. 취소 전후 STT·요약 모두 Job BLOCKED(REMOTE_UNKNOWN), SQLite Attempt UNKNOWN, 무게시·단일 호출을 확인했다. 별도 강제 publication 오류 2 case도 UNKNOWN을 보존한다. 실제 원격 중단·비용 정산은 NOT_RUN이다. |
| BR13-02 | OPEN | `_session_jobs` 조회는 순차 중복을 해결했으나 조회→등록→submit의 직렬화가 없다. `test_simultaneous_duplicate_submission_preserves_one_execution[stt/summary]`에서 두 caller의 최초 absent 조회 직후를 barrier로 맞추면 첫 Job이 CANCEL_REQUESTED/CANCELLED가 된다. 사전 조회 사이의 정상적인 thread switch를 재현한 계측이며 target source는 수정하지 않았다. 둘을 동시에 입장시키지 않는 구현에서는 barrier timeout을 허용한다. 신규 입장과 중복 판별을 직렬화하고 같은 반례 통과 후 종결한다. |
| BR13-03 | RECHECKED | transcribe의 job key에 `origin_ns`가 포함됐다. 원점만 바꾼 두 요청이 다른 Job이며 0ms→1000ms 새 결과를 선택하는 시험을 통과했다. 이후 mapping 정책 변경도 identity에 반영해야 한다. |
| BR13-04 | RECHECKED | install의 descriptor 작성 및 rename 직전 cancel 재검사를 확인했다. 최종 progress 취소 시 비활성·부분 보존, 취소 해제 뒤 같은 plan으로 무결성 검증·설치 성공을 독립 확인했다. 취소가 rename과 동시에 발생할 때 이미 commit된 활성화의 소급 취소를 보장하는 시험은 아니다. |
| BR13-05 | RECHECKED | media의 packet 내부 frame 분할과 WAV byte 상한을 확인했다. 3초/max1·31초/max30의 clip 상한, 총 frame, 정확한 PCM, 각 clip의 source 시작 frame·출력 frame 0·보정 capture 시각·timeline offset을 손계산 oracle로 확인했다. 원본 읽기와 물리 재생 장치 검증은 구분한다. |

후속 BR13-06은 OPEN이다. 해당 반례의 `storage/library.py` SHA256은 `837CBB79E16E135827420E03920280A6A9FE5E7CC1AE21EC92948772D46F7C3C`다. 이후 독립 시험과 기존 AI E2E·media·inference·models를 묶은 실행은 **60 PASS / 4 strict XFAIL**(독립 17 PASS / 4 XFAIL)이며 위 수정 digest 3개는 그대로였다. 현재 종결 수는 **4/6**, 미해결은 **BR13-02·06 S2**다. 재확인 digest 이후 B10의 live 전사·UI 통합 변경은 별도 snapshot 재검사가 필요하다.

### BR13-02 2차 재확인 · RECHECKED

`app/ai.py` SHA256 `27325F040694DA27D5312A7A8C5AD79F886BEBBA22034ECAFA054BB2939A9825`의 `_admit`은 RLock 내 Job 생성·바인딩·중복 판별·입장 예약을 수행한다. `_submit`은 실제 새 Job의 거절만 취소하며 기존 dedup Job은 취소하지 않는다. 요청 UUID와 반환 ID로 신규 여부를 구분하는 코드를 대조했다. 위 동시 반례 STT·요약과 진짜 capacity 포화 대조군을 독립 재실행하여 **3 PASS**를 확인하고 해당 2개 XFAIL을 해제했다. 단일 AIService 내 입장 경쟁 범위의 재확인이며 다중 서비스 인스턴스의 소유권 전체를 승인하지 않는다. 현재 종결 **5/6**, 미해결 **BR13-06 S2**다.

### BR13-06 2차 재확인 · RECHECKED

B10/B11 변경의 reader 시작·종료 영속 계약을 대조했다. runner는 task I/O 전에 reader_started, task의 finally에서 reader_finished를 호출한다. Library는 terminal 상태에도 명시 active=1이면 삭제를 보류하고, 세션 바인딩과 inactive=0이 있는 BLOCKED만 삭제에서 제외한다. legacy/미상 reader는 보수적으로 보류한다. `recover_abandoned(coordinator_exclusive=True)`는 호출자의 이전 reader 종료 증명에 대한 명시적 선언이며 독립 OS 생존 확인이 아니라는 제한을 유지한다.

원래 UNKNOWN→취소→worker stop ACK→로컬 삭제 반례 STT·요약을 독립 재실행하여 **2 PASS**를 확인했다. 두 XFAIL을 해제하고 독립 21개 및 기존 AI E2E/media/inference/models를 묶어 **64 PASS**, skip/xfail 0, ResourceWarning 오류 처리를 확인했다. 원격 UNKNOWN 상태는 삭제 후에도 BLOCKED(REMOTE_UNKNOWN)으로 보존하며 재전송하지 않았다. 기존 취소→DELETE_PENDING→늦은 결과 차단→삭제 완료의 STT·요약 대조군도 함께 통과했다.

| 재확인 코드 | SHA256 |
| --- | --- |
| storage/library.py | `852A9F680C8BA17C1144435190946C8EF3392C08F68AC06BF679E784FC77F48C` |
| jobs/__init__.py | `C1C2379665CCB249293EC7604EE83A2115307CBA7259F81333FBFD06A56E2F44` |
| jobs/runner.py | `69BA48589F0C255B2069E949C42BA891FD359AE6941B04AB075BEEC58DD54D95` |

위 3개 digest는 원반례 실행 전후 같았다. 통합 app/ai.py는 병렬 작업 중 변경되었고 묶음 실행 종료 때 `058F10877C0F778AF5D1AE0134699737AD7F1A750D9B364D8AD65C4A34AAB27A`였다. 따라서 이 기록은 6개 지적의 반례 해결에 대한 재확인이며 아직 동결하지 않은 B10 전체 최종 tree의 승인이 아니다. **BR13 6/6 RECHECKED, 해당 지적에 남은 OPEN S0/S1/S2 0건**이다. 실제 장치·모델·서비스·parent-death kill·G3/G4는 별도다.

## B21 변경분 체크포인트 재확인

2026-11-14, B10이 동결한 아래 3파일을 읽고 기존 반례를 재실행했다. 검토자는 해당 제품 코드를 수정하지 않았다.

| 동결 대상 | SHA256 |
| --- | --- |
| app/ai.py | `051CEC24F83AAD1E164CF0C9495E0A867570C61FF1197DE301E7FE15E9310428` |
| app/media.py | `BE10216897F73600AED244627CE067C6005D8B7E707AFFEC8891291301AE06C8` |
| app/desktop.py | `D36ADBD4A635643E9BC88B5E595FE512B2084102AE902961C22DB24139C954F1` |

전사 준비가 runner의 durable reader lease 안으로 이동했고, control 쪽은 고정 descriptor만 선택한다. media는 짧은 root lock으로 세션/출력 경계를 확인하고 무거운 변환/VAD는 recorder writer lock 밖에서 처리한다. 이 변경은 현재 AIService가 reader를 보유해 호출한다는 계약 범위에서 확인했다. 임의의 외부 호출자가 reader lease 없이 같은 helper로 삭제와 경쟁하는 전체 API를 승인하는 것은 아니다.

`_OutcomeGuard`의 unknown 우선, RLock 입장 예약·기존 Job 무취소, reservation 이후 Gateway 이전 remote-intent 영속화, origin/config가 다른 입력 key, 편집 active를 보호하는 CAS가 유지됨을 대조했다. live draft는 같은 config/language/origin 범위의 완료 checkpoint만 누적하고 신규 봉인 chunk만 선택하며 VAD silence도 처리 범위에 남긴다. native format metadata는 별도 capture_health에 저장되고 경고·미터와 구분된다.

독립 `test_ai_independent.py`와 AI E2E/media/desktop/독립 desktop 회귀 묶음은 **63 PASS**, 별도 publication 독립 파일은 **19 PASS**였다. 둘 다 skip/xfail 0, ResourceWarning 오류 처리다. 앞 묶음은 원본 hash·track/time 품질·UNKNOWN 취소·동시 중복·origin·편집 경쟁·삭제 보호를 재검사했다. VAD 원본 frame/offset/hash 대조, 누적 draft 중복 방지·다른 scope 비병합, silent 처리, 느린 변환 중 녹음 drain을 확인했다. 뒤 묶음은 remote-intent가 transport open 전에 별도 SQLite에서 보이며 marker 실패 때 열지 않는 반례를 포함한다.

위 3파일 digest는 읽기 및 두 실행 후 동일했다. 이 체크포인트 변경분에서 추가 OPEN S0/S1/S2를 발견하지 않았으며 기존 6건의 종결을 유지한다. 실제 VAD/화자/음성 정확도·장치 시계 품질·native 장비·실모델·parent-death kill·배포 검증은 이 synthetic/fixture 재실행으로 통과시키지 않는다.

## R12 최신 B21 동결분 독립 재검토

R00이 R12 REVIEW_READY 뒤 새로 배정한 검토다. R12 자체 350 PASS는 독립 승인으로 인용하지 않는다. 아래 여섯 runtime 파일과 관련 UI/E2E/media 시험을 읽었으며 대상 제품 코드는 수정하지 않았다. BR13 과거 6/6 RECHECKED와 이번 새 지적을 구분한다. B22의 자기 작성 수정과도 별개 역할이다.

| B21 재검토 snapshot | SHA256 |
| --- | --- |
| app/ai.py | E3E981C00354ACF7BCC87770365DE5FEB2554D98484AA01A6EBAE3B3C55D124C |
| app/media.py | 25808336F6DAFA3E555B780A1B64ED08AD37C5F718A15A17A9BDA32C7FE7BA6D |
| ui/ai_bridge.py | B0716E8C5DAD3A845097A5C0124C11CFE1B113A71943A29ECB6421CEA4DC1591 |
| ui/content.py | 341C952DDD4EB67C3847E4A14DCAC4D0AFB32CB65D50FEB4F6FA390992C6455A |
| ui/models.py | 56E1BA1B249895C9321719052BD004CE934F99C55051D74666458A4F5DBE81FC |
| ui/main.py | C68CB205D55E2374BBE96EA6388E865BE4138EF65CA44E77936AC35141275C4B |

### BR13-07 · S2 OPEN — 준비 이후 owner lease에서도 GUI 동기 getter가 대기

위치: `ui/ai_bridge.py` `DesktopAI.tick`/`summarize`, `ui/models.py` `checked_attestation`. helper의 `ManagedOllama.attestation`은 owner lock을 보유해 처리하며 Gateway handoff도 같은 lock을 취한다.

재현: helper 준비 작업이 끝나 `ModelPanel.task is None`인 상태에서 AI worker의 owner handoff lease를 합성 thread가 보유한다. 실제 `DesktopAI.tick → ModelPanel.checked_attestation → ManagedOllama.attestation` 경로를 GUI thread에서 호출한다. helper는 정적 synthetic proof만 가지며 실제 프로세스/모델/listener/네트워크를 호출하지 않는다. GUI에 예약한 QTimer heartbeat가 진행되지 않고 테스트의 rescue gate가 owner lock을 해제해야만 tick이 돌아온다.

`test_br13_07_gui_tick_cannot_wait_for_inflight_owner_handoff_lock`는 현재 **FAIL**이다. 250ms는 결함을 유한 시간에 풀어 pytest를 보호하는 rescue timeout이며 제품의 측정된 지연 수치가 아니다. 운영에서는 transport timeout/owner 검증 대기까지 GUI 조작이 지연될 수 있다. 기존 준비 중 `task is not None` 거부만으로 실제 추론 중 owner lease를 피하지 못한다.

해결 조건: GUI tick/요약 준비가 owner lock·OS 소유 검증을 기다리지 않도록 별도 worker/비차단 조회 또는 고정 cached proof+dispatch 검증을 사용한다. 실제 전송의 frozen owner guard·TTL·동의 검사는 약화하지 않는다. GUI heartbeat·녹음 stop/pause lane과 오래된 proof 거부를 함께 확인한다. R12가 UI를 수정하고 helper 공개 API 변경이 필요하면 root가 조정한다. 검토자는 제품 파일을 고치지 않는다.

### 추가 독립 경계와 실행

기존 21개에 9개 case를 추가해 최종 **29 PASS / 1 FAIL / 4.79s**, skip/xfail 0, ResourceWarning 오류 처리다. 유일 실패는 BR13-07이며 기존 6개 지적의 원 반례는 통과했다. 독립 파일 Ruff check/format PASS다. 새 fixture 작성 중 draft 편집본의 명시 선택을 빠뜨린 오류는 `select_transcript`로 실제 사용자 선택을 표현해 수정했으며 제품 결함으로 계산하지 않는다.

- 합성 1kHz PCM의 400~600frame 발화를 VAD가 선택한 300~700frame bytes와 독립 대조했다. silent 봉인 chunk는 provider 호출 없이 processed 목록에 남으며, service 재시작 뒤에도 최초 origin 1s를 복원해 후속 5s chunk의 offset 4300ms를 유지한다. 같은 snapshot 중복 실행·원문 bytes·명시 선택한 edited active 보존을 확인했다.
- STT/요약 UNKNOWN은 같은 계획으로 새 요청을 보내지 않으며 명시 nonce가 있는 새 실행만 provider를 다시 호출한다. 이전 Job BLOCKED(REMOTE_UNKNOWN)과 이력은 그대로다.
- 실제 SQLite reader lease 아래 playback 검증을 event로 정지하고 삭제와 경쟁시켰다. reader ACK 전 DELETE_PENDING과 원본 보존, 검증 종료 뒤 로컬 삭제 완료를 확인했다. 실제 QMediaPlayer 출력·오디오 장비는 실행하지 않았다.
- fake diarization runtime의 편집 경쟁·취소·잘못된 audio hash 3경우에서 원 parent 불변·후보 revision·edited active CAS·취소/불일치 무게시를 독립 확인했다. 실제 B22 모델 실행이나 B22 자기 승인이 아니다.
- 편집 저장 입장 거부 뒤 입력을 유지하고 새 corrected active가 도착해도 refresh로 지우지 않는다. 명시 저장 재시도는 원 parent의 edited 후보로 남기고 새로운 active를 덮지 않는다.

```powershell
$br13Run = Join-Path $env:TEMP ('recoryn-br13-current-' + [guid]::NewGuid().ToString('N'))
.venv/Scripts/python.exe -m pytest tests/integration/test_ai_independent.py -q -p no:cacheprovider --basetemp $br13Run -W error::ResourceWarning --tb=short
```

현재 새 지적 BR13-07 S2 OPEN 1건으로 R12 수정·같은 반례 재확인이 필요하다. 과거 RECHECKED를 현재 B21 전체 승인으로 확대하지 않는다. root의 shared coverage/대형 build는 별도 동시 변경 snapshot이며 최종 증거가 아니다. 실제 모델·음성·화자 품질·GPU·원격 비용·장치·G3/G4는 NOT_RUN이다.

## BR13-07 수정 후 최종 동결 재확인 — RECHECKED

R12 수정, R13 독립 재확인. R00이 전달한 최종 models/bridge/main 3개 digest와 실제 파일이 모두 일치했다. 기존 지적과 실패 기록은 위에 이력으로 보존한다. 검토자는 대상 제품 코드를 수정하지 않았다.

GUI `checked_attestation`은 세대·TTL이 맞는 고정 snapshot만 읽으며 helper lock/OS 검증에 들어가지 않는다. `DesktopAI.tick`은 단일 model worker로 coalesce된 조회를 요청한다. 비동기 완료는 owner identity·generation·shutdown을 확인한 뒤에만 proof를 수락하고, stop/shutdown은 조회 완료를 기다리기 전에 proof를 무효화한다. 원 GUI heartbeat 반례가 수정 후 PASS로 바뀌었으며, 원 30개 독립 시험도 **30 PASS / 4.77s**였다.

R00의 사전 승인과 최종 QA 대기 조정을 받고 별도 late-race 6case를 추가했다. stop/replacement/shutdown × 이전 getter 성공/실패를 fake owner Event로 고정했다. 실제 PrivacyPanel과 ConsentStore/Gateway를 연결하되 transport·vault·owner는 fake다. 같은 endpoint·model·artifact를 가진 replacement에서도 오래된 callback이 privacy proof를 복원하거나 새 동의를 철회하지 않는다. cached getter는 GUI에서 helper에 재진입하지 않고 20개 polling 요청은 한 번의 worker 조회로 coalesce된다. 실제 네트워크·OS listener·모델을 호출하지 않았다.

양성 대조는 이전/새 계획의 fake transport handoff가 해당 owner의 frozen lifetime guard 안에서 이뤄짐을 확인했다. 퇴역 계획은 다시 보내지 못하고 새 계획은 replacement guard를 사용한다. GUI cache가 남아 있어도 owner guard를 무효화하면 이후 dispatch는 연결/body 전에 막힌다. 비동기 UI 전환이 TTL·현재 동의·actual dispatch guard를 우회하지 않는다.

최종 동결 실행은 **BR13 독립 36 PASS**, BR23 독립 43개를 함께 실행해 **79 PASS / 6.66s / skip·xfail 0**, ResourceWarning 오류 처리다. 아래 runtime 6개 digest는 실행 전후 프로그램 비교로 동일했고, 새 3개는 R12/R00 freeze와도 일치했다. 독립 시험 Ruff check/format PASS다. 새 fixture의 replace import 누락은 검토자 시험 작성 오류로 고친 뒤 6case를 별도 실행해 모두 통과했으며 제품 결함으로 집계하지 않는다.

| 최종 독립 재확인 동결 파일 | SHA256 |
| --- | --- |
| app/ai.py | E3E981C00354ACF7BCC87770365DE5FEB2554D98484AA01A6EBAE3B3C55D124C |
| app/media.py | 25808336F6DAFA3E555B780A1B64ED08AD37C5F718A15A17A9BDA32C7FE7BA6D |
| ui/content.py | 341C952DDD4EB67C3847E4A14DCAC4D0AFB32CB65D50FEB4F6FA390992C6455A |
| ui/models.py | 67C06B2EB42500D3BF6FFDA1F7F2BB7B78CA5F2AC5CA32C5766BB9ED6BA5B384 |
| ui/ai_bridge.py | 3729DCFA48BE282BEDC1884C2CA4B17669EA8C29798F885DBF1431F347E4F809 |
| ui/main.py | 952457B561732CB13B12002390944EE4BCE3A50EE63B400B4040099666DE11CD |
| tests/integration/test_ai_independent.py | D72AD3372143925BCBD459F1FB6A441B0D7609B508A4671A55FCB5B6B96F601D |

```powershell
$br13FinalRun = Join-Path $env:TEMP ('recoryn-br13-final-freeze-' + [guid]::NewGuid().ToString('N'))
.venv/Scripts/python.exe -m pytest tests/integration/test_ai_independent.py tests/integration/test_egress_independent.py -q -p no:cacheprovider --basetemp $br13FinalRun -W error::ResourceWarning --tb=short
```

**BR13-07 RECHECKED, 이번 BR13 지적의 남은 OPEN S0/S1/S2 0건.** 원 BR13-01~06의 재확인을 유지하며 총 7개 지적의 코드/합성 반례 재확인이다. `test_ai_independent.py`는 위 최종 SHA로 동결했고 root 최종 QA와 충돌하는 추가 쓰기를 하지 않는다. B22 자기 작성분의 최종 승인은 별도 BR41이며 이 판정에 포함하지 않는다. root 최종 build·R14 독립 전체 회귀/coverage·실제 모델/음성/장치·G3/G4는 별도 게이트다.
