# D11 독립 교차 검토: AI·UX 통합 계약

2026-11-14 / 검토자 D11(아키텍트, D03 작성 세션과 별도) / 상태: **검토 제안·발견 OPEN / D00 수정 후 동일 검토자 재확인 예정**.
자신의 D01 작성물과 D00 수정안을 승인하지 않는다. 이번 변경은 이 파일에 한정한다.

## 범위와 검토 기준

- [최신 규칙](../../AGENTS.md), [품질 체계 Q](../quality-system.md), [검증 계획 V](../validation-plan.md), [통합 설계 A](../architecture-v1.md), [배정표](../collaboration/assignments.md), [타 세션 AI·UX U](ai-ux.md)를 읽었다.
- Job/Attempt, 취소·재시도, revision/근거, 자원·비용·provider DTO를 문서 반례로 대조했다. 아래 반례는 실행 재현 결과가 아니다.
- 사용자 원칙 R01~R06은 제약이다. 필드·상태 보강은 D11 제안이며 D00의 채택·수정과 재확인이 필요하다. 1차 대안의 우열이나 CLOSED/FINALIZED 명칭 차이를 결함으로 세지 않았다.

## 확인한 통합 계약

- 업무 상태의 기준은 SQLite다. raw PCM + 블록별 `blocks.jsonl` + 최종 descriptor bundle은 미디어 복구 기준이며 manifest는 DB generation snapshot이다.
- D02 O-A09 대안 A의 bundle→DB→manifest 순서를 기준으로 검토했다. 파일/DB 전체 원자성을 가정하지 않으며 `.rcpcm`은 초기 보류다.
- Session 최종 이름은 FINALIZED다. Job terminal과 Attempt terminal은 분리되고 자동 retry는 새 Attempt, 수동 재실행은 새 Job이다. 이전 fence의 게시를 거부한다.
- 불변 전사와 고정 revision 근거, queued 요청의 권한 재검사, 자동 CPU/클라우드 전환 금지, unknown 처리 위치 차단은 A에 반영되어 있다.

## 발견 사항: 모두 OPEN

### D11-01 / S1 / 취소와 게시의 트랜잭션 경계 누락

- 파일/절: A 「상태와 실행 계약」「메타데이터와 산출물 버전」, U §2.2·8.2, V I04·U03.
- 반례: 유효 Attempt의 결과가 준비됨 → 결과 handler가 유효성 확인 → 취소 전이 commit → 별도 transaction이 active revision 교체 → Job 완료 전이만 version 충돌. 취소된 결과가 현재 포인터에 남는다. 각 전이의 CAS만으로 포인터 transaction까지 묶인다는 계약은 없다.
- 해결 조건: Job의 실행/취소 의도·현 fence·삭제 세대 검사, artifact/revision/선택 포인터, Job/Attempt 완료를 같은 DB transaction으로 규정한다. 취소와 성공 중 먼저 commit한 결과를 따르고 취소 수락 후 재시도·하위 dispatch를 막는다. worker 상실 복구도 취소 의도를 보존해야 한다.
- 재확인 조건: I04에 두 commit 순서, 포인터 갱신 직전 취소 barrier, 취소 직후 crash/복구를 추가하고 기대 포인터·Job·Attempt 상태를 명시한다.

### D11-02 / S1 / 늦은 요약의 현재 선택 덮어쓰기 방지 불충분

- 파일/절: A 「메타데이터와 산출물 버전」「AI 제공업체와 자원 관리」, U §3.1·4.1, V I05.
- 반례: 전사 T1의 요약 S1 시작 → 사용자가 T2 편집·선택 → T2 요약 S2 완료·선택 → S1 완료. 입력 고정·유효 claim·부모 비교를 모두 통과해도 요약 선택 포인터의 CAS가 없어 S1을 현재 요약으로 선택할 수 있다. 같은 T2라도 옛 템플릿 결과가 최신 선택을 덮는 경우가 남는다.
- 해결 조건: 요약의 입력 revision/hash와 설정 키를 고정하고, 게시와 현재 선택을 분리한다. 기대 전사 선택 버전·요약 선택 버전/설정 키 비교 실패 시 후보로 보존하고 OUTDATED를 계산한다. 전사 CAS와 별개인 요약 CAS 규칙을 A에 둔다.
- 재확인 조건: I05에 T1/T2 역순 완료와 같은 전사·다른 템플릿 역순 완료를 추가하고 선택 유지·후보 보존을 기대 결과로 적는다.

### D11-03 / S2 / 비용 정산의 중복 방지와 crash oracle 부족

- 파일/절: A 「전송 동의와 비용」「메타데이터와 산출물 버전」, U §7·AU13/AU14, V U08·I06/I07.
- 추가 반영 확인: A에 원자 한도식, unknown_exposure 유지, 재시작 시 예산 유지가 추가되었다. 기존 “timeout 예약 자동 해제 허용” 지적은 최신 A의 누락으로 주장하지 않는다.
- 반례: 한도 100, 요청 R 상한 60이 UNKNOWN으로 남음 → 확정 비용 40 정산 → 재시작 후 같은 usage 이벤트 재수신. request/reservation 기준의 단일 정산 계약과 oracle이 없으면 confirmed를 80으로 이중 반영하거나 차액을 두 번 반환할 수 있다. V의 “청구 미상 표시/한도 유지”만으로 이 회귀를 판별하기 어렵다.
- 해결 조건: 영속 request/reservation ID에 정산을 귀속하고 중복/역순·잠정/최종 usage의 허용 전환을 명시한다. U08/I06/I07에 전송 직후 crash, UNKNOWN→확정, 중복 정산을 넣고 잔액·범주·새 Job의 추가 dispatch 허용 여부를 수치 oracle로 정한다.

### D11-04 / S2 / 편집 provenance의 부정 시험 수락 기준 누락

- 파일/절: A 「메타데이터와 산출물 버전」「AI 제공업체와 자원 관리」, U §3.2·3.3·AU06, V U04·M01.
- 추가 반영 확인: A에 user_assertion/model_inference, unresolved, unreviewed와 음성 근거 승격 금지가 추가되었다. 이 정책 자체의 부재는 최신 A에 대한 지적으로 유지하지 않는다.
- 반례: 원 음성 “예산 검토 예정”의 edited segment에 “철수가 500만 원 승인”을 삽입하고 기존 source frame을 유지한다. 구현이 잘못된 음성 근거 배지를 붙여도 revision/segment 존재와 reference 유효성 100%는 만족하므로 V U04/M01/E01의 기대 결과만으로 위반을 잡는 독립 oracle이 불충분하다.
- 해결 조건/재확인: U의 AU06을 V에 명시 매핑하고 삽입·부분 교체·분할/병합의 basis/span provenance 보존, user_assertion/unresolved 표시, 발화 검증 배지 금지를 기대 결과로 적는다. 구조 참조 유효성과 의미 검토를 별개로 판정한다.

### D11-05 / S1 / 부분 성공과 READY·전체 완료의 계산 조건 누락

- 파일/절: A 「상태와 실행 계약」「메타데이터와 산출물 버전」「AI 제공업체와 자원 관리」, U §3.1·4.1·AU07, V C01·M01·E01.
- 반례: 입력 10개 core span 중 1개만 요약 성공, 나머지 9개 실패. A에 추가된 core coverage·실패 범위를 기록하고 claim도 모두 유효하지만, 필수 completeness와 READY/전체 완료 계산식이 없어 이를 전체 완료로 표시하는 구현을 판별할 수 없다. 무음의 정상 빈 전사와 실패한 빈 전사도 구별되지 않는다.
- 해결 조건: 계획 대상·성공·실패/미처리 coverage와 partial/complete를 revision에 필수화하고 전체 성공 판정을 정의한다. 원본 확정·전사 준비·요약 준비를 별도 계산하며 선택하지 않은 요약은 차단하지 않는다. 요약 통합이 일부 결과만 읽을 때도 누락 범위를 승계한다.
- 재확인 조건: C01/M01/E01에 1/10 성공, 정상 무음, gap 포함 전사, 요약 미선택을 넣고 각 준비 상태와 UI 문구의 독립 oracle을 적는다.

### D11-06 / S2 / 자원 변경 시 실행 계획·재시도 동일성 경계 미정

- 파일/절: A 「상태와 실행 계약」「AI 제공업체와 자원 관리」, U §2.2·5·AU09/AU16, V U03·I02·M02.
- 반례: GPU OOM 뒤 batch/context를 줄이거나 CPU 허용으로 새 Attempt를 만든다. U는 같은 Job 재시도를 허용하면서 checkpoint의 설정·계획은 모두 같아야 한다고 요구한다. A의 Job 설정 digest/idempotency key를 바꿀지, 이전 checkpoint를 재사용할지, 새 Job으로 만들지 공통 규칙이 없어 어댑터별 재개 결과가 달라진다.
- 해결 조건: 입력/출력 의미를 바꾸는 설정과 실행 장치·batch 같은 실행 설정의 구분, 버전 있는 Attempt별 ExecutionPlan, checkpoint 호환 키와 Job/run idempotency 범위를 정한다. 모델·전사·템플릿 변경은 새 Job으로, 허용된 실행 조정은 새 Attempt로 처리하는 조건을 명시한다.
- 재확인 조건: AU09/AU16과 U03/I02의 매핑 및 같은/다른 checkpoint 키 예시를 추가한다. 이전 CPU 허용이 모델/외부 전송 허용으로 확대되지 않아야 한다.

### D11-07 / S2 / provider 오류→대기 상태·UI 매핑 미정

- 파일/절: A 「상태와 실행 계약」「AI 제공업체와 자원 관리」, U §2.1·2.2·5·7, V C01/C02.
- 반례: 자원/예산 부족에서 U가 요구하는 WAITING_USER를 Job 상태로 저장하면 A enum 밖이다. NETWORK_TIMEOUT에 retryable=true가 붙고 outcome_known=false인데 dispatcher가 retryable만 보면 자동 BACKOFF 재호출을 할 수 있다. A의 금지 정책을 DTO→전이로 실현하는 우선순위가 없다.
- 해결 조건: A에 describe/probe·ExecutionPlan·이벤트 필터가 추가된 것은 확인했다. 남은 Error/JobContext를 포함한 버전 있는 provider DTO의 정본을 지정하고 WAITING_USER를 BLOCKED(reason)의 UI 투영으로 매핑한다. outcome 불명·동의·예산·취소 검사 우선순위를 오류→Job/Attempt/ledger/사용자 행동 표로 고정한다. SDK 자동 retry도 이 경계를 우회하지 못하게 한다.
- 재확인 조건: C01/C02에 unknown·retryable의 조합, OOM/동의/예산 오류의 기대 영속 상태와 UI 표시를 표로 추가한다. 실제 SDK 지원은 구현 시 확인한다.

## 검토 버전과 미검증 범위

작성 중 A/V/Q 변경을 감지해 다시 대조했다. 아래 SHA-256을 검토 기준으로 고정하며 이후 변경은 별도 재확인 대상이다. 이는 수정안 승인 기록이 아니다.

- A `EA1F997FF20F50A217152D0A19EF0D1C5B259FF5052E36A2FE72A29008605272`
- U `08F0D9086A6F4B156FB91A3B29A4D3D440E6BB701B7D206FCBB8D87A6CC5D168`
- V `667D51B10B13D9A7F3447870378F75CA6359C973F87DF0488D550B1DFCE0F4A4`
- Q `FE0AD8FF751143A6DC9AF77A510F56186E78DA0D22B2559CC532958442E2B044`
- AGENTS `15722FEF93EE7C57B3344E5AF90E7CC79E8FEDFBDFCC459BA2AB98735CB56D6F` / 배정표 `35AC1AB1517AB6558D4F1BE0B930A0FC0B679E19275F7547F21C3CF20B7FB5A2`

실행 시험·음성/원본 분석·실장비·provider/API 호환·정량 성능·접근성 검증은 미수행이다. 블록 journal serializer/flush의 golden fixture와 crash 시험, 수치 예산, backend 선택은 구현 게이트이며 그 보류 자체를 설계 결함으로 기록하지 않았다.
Q의 심각도 기준을 적용해 S1 3건/S2 4건을 제안한다. 각 반례를 A/V에 보강한 뒤 D00이 FIXED 근거를 제시하고 동일 D11이 재확인해야 한다. 현재 RECHECKED/CLOSED 또는 G0 통과를 선언하지 않는다.

## D11 독립 재확인 기록 — 2026-11-14

재확인자: 원 교차 검토자 D11. 대상은 타 세션 D03의 AI·UX 제안과 D00 공용 명세의 문서상 해결 여부다. D01 등 자신의 1차 작성물을 승인하지 않았다. 앞부분의 OPEN·당시 digest는 역사 기록이며, 아래 상태가 이번 동결 snapshot에 대한 최신 D11 판정이다.

검토 시작 시 실제 파일 SHA-256이 사용자 지정 세 값과 일치함을 확인했다.

- A / `docs/architecture-v1.md`: `E08450D0899A5DCF4DDE5745B6BC58B1A7B6F0B2BF0867CAC4FF405D96DA7ABD`
- V / `docs/validation-plan.md`: `DF1551A71C3BF55C6A4466B68443EFDE1673A7C22A1BBB867A69DD6F527601AB`
- Q / `docs/quality-system.md`: `FE0AD8FF751143A6DC9AF77A510F56186E78DA0D22B2559CC532958442E2B044`
- [D00 수정 대응표](design-signoff.md)의 확인 시 digest: `BC0728442A4E6D69F75BB609E3F7DC66CC4854721D8D3BAA0A9D1866A983CBFC`. 대응표의 FIXED 표기를 그대로 승인하지 않고 A/V의 실제 문구와 원 반례를 대조했다.
- 추가 전 본문: 10,819 bytes, SHA-256 `65400DF867511936B734E5497BF06F5A85634FA19580AD40A45AABDEA641B553`. 기존 기록 보존 확인의 기준이다.

### D11-01 — RECHECKED / 문서상 해결

A 「상태와 실행 계약」의 결과 게시 transaction 문단(89행)은 실행·취소 의도, attempt/fence, 삭제 세대·입력 버전 검사와 artifact/revision·포인터·Job/Attempt 완료·outbox를 한 DB transaction에 묶는다. 취소도 같은 직렬화 경계에서 fence를 회수한다. 따라서 원 반례의 “취소 commit 뒤 포인터만 별도 commit”은 계약 위반으로 판별 가능하다.
V **I04**는 포인터 직전 barrier, 양 commit 순서, 취소 직후 crash와 의도 보존을 명시한다. 성공 우선이면 ALREADY_SUCCEEDED, 취소 우선이면 active 불변·새 dispatch 0이라는 독립 기대값을 확인했다.
남은 제한: transaction/권한 회수 구현과 프로세스 재시작 경쟁은 NOT_RUN. 파일 게시까지 DB transaction에 포함되었다고 판단하지 않는다.

### D11-02 — RECHECKED / 문서상 해결

A 「메타데이터와 산출물 버전」의 요약 선택 문단(180행)은 게시와 현재 선택을 분리하고 전사 선택 버전·요약 선택 버전·설정 키를 같은 transaction에서 비교한다. 불일치는 원 입력 후보 보존이며 현재 선택을 바꾸지 않는다. OUTDATED 계산과 옛 템플릿의 늦은 덮어쓰기 금지도 명시되어 있다.
V **I05**는 T1/S1→T2/S2 선택 뒤 S1 완료와 같은 T2의 옛 템플릿 완료를 모두 포함한다. S2 유지·S1 후보+OUTDATED·원 입력 seek라는 기대 결과가 원 반례를 직접 다룬다.
남은 제한: 선택 CAS, 동시 완료, 근거 seek의 실제 동작은 NOT_RUN.

### D11-03 — RECHECKED / 문서상 해결

A 「전송 동의와 비용」의 정산 문단(229행)은 영속 request/reservation ID와 usage event/version, 잠정·최종 구분, 범주의 원자 전환, 역순·상충 최종 정보 보류를 명시한다. limit=100, UNKNOWN=60→최종 40이면 confirmed=40/unknown=0/available=60이고 중복 수신·재시작에도 동일하므로 원 반례의 이중 가산·이중 반환을 금지한다.
V **U08**에 같은 수치 oracle과 중복/역순 usage가 있고, **I06**은 예약→dispatch→정산 각 kill과 세션 삭제 뒤 exposure 유지·새 요청 차단을 포함한다. **I07**은 접수 불명의 자동 retry를 금지한다.
남은 제한: 실제 ledger crash consistency, 제공업체 usage 의미·조회 기능·최종 청구는 미검증이다. 문서의 앱 예산 통제를 외부 청구 보장으로 확대하지 않는다.

### D11-04 — RECHECKED / 문서상 해결

A 「AI 제공업체와 자원 관리」의 claim 문단(211행)은 사용자 삽입의 음성 근거 승격 금지, user_assertion/unresolved, unreviewed와 구조 검증·supported의 구분을 유지한다.
V **U04**는 음성에 없는 삽입·교체·분할/병합, provenance 유지, user_assertion/unresolved와 발화 검증 배지 금지를 명시하며 D03/**AU06**에 연결한다. **M01/E01**도 AU06·사용자 삽입 및 basis 보존을 반영해 “참조 ID가 존재하므로 발화 증거”인 구현을 부정할 수 있다.
남은 제한: 편집 span 추적, UI 배지, 사람의 의미 지지 판정 정확도는 NOT_RUN. 원 음성이나 사용자 편집 자료를 실제 분석하지 않았다.

### D11-05 — RECHECKED / 문서상 해결

A 「메타데이터와 산출물 버전」의 coverage/Job 성공 문단(182·184행)은 대상·성공·실패/미처리와 partial/complete를 필수화한다. 모든 core span 검증·필요 통합 성공이 complete 조건이며 부모 전체 Job의 SUCCEEDED도 이에 일치해야 한다. 선택 오디오·전사·설정에 따른 준비 계산, 정상 무음과 실패한 빈 결과, 요약 미선택도 분리한다.
V **C01/M01/E01**에 1/10 성공·9/10 미처리, 부모 전체 성공 금지, 정상 무음의 complete 빈 전사, 요약 미선택의 audio 완료 허용이 들어갔다. gap/오디오 변경 시 입력 일치는 A의 AudioRevision 계약과 V **I03/P02**로 교차 확인했다.
남은 제한: coverage 계산·분할/통합 승계·readiness/UI 구현은 NOT_RUN. complete는 내용 정확성이나 원본 무손실을 뜻하지 않는다.

### D11-06 — RECHECKED / 문서상 해결

A 「상태와 실행 계약」의 동일성 문단(91행)은 논리 Job 의미 키와 versioned Attempt ExecutionPlan을 분리한다. 동일 의미의 장치/batch/worker 조정은 새 Attempt, 모델·입력·출력/context 분할 의미 변경은 새 Job이며 체크포인트는 별도 호환 키로 검사한다. CPU 허용의 외부 전송·모델 변경 권한 확대도 금지한다.
V **U03**은 같은 의미/호환 키에서 GPU→허용 CPU·batch 조정과, 다른 모델/전사/템플릿·의미 변경의 새 Job·체크포인트 재사용 금지를 대조한다. **I02/M02**는 OOM·CPU 허용/거부와 암묵 fallback 금지를 연결한다. 이는 D03의 AU09/AU16이 다룬 경계를 정본 시험으로 구체화한 것이다.
남은 제한: 실제 모델에서 batch/장치 조정의 의미·체크포인트 호환성은 검증 전 추정할 수 없다. 검증된 동일 의미 조정에만 해당하며 canonical 키 직렬화와 backend 동작은 구현 게이트다.

### D11-07 — RECHECKED / 문서상 해결

A 「상태와 실행 계약」의 오류 우선순위 표와 DTO 문단(93~102행)은 취소·삭제, outcome 불명, 권한/capability, 자원/예산, 알려진 일시 오류를 구분한다. outcome_known=false는 retryable=true보다 우선하여 Attempt UNKNOWN·Job BLOCKED(REMOTE_UNKNOWN)이며 WAITING_USER는 BLOCKED의 UI 투영이다. Request/ExecutionPlan/Event/Error의 정본 의미와 SDK 우회 금지도 지정한다.
V **C02**는 unknown/retryable 조합, OOM→RESOURCE, 동의→CONSENT, 예산→BUDGET과 WAITING_USER 투영을 직접 기대값으로 둔다. **C01**의 동일 DTO 및 **I04/I07**의 취소·불명 재호출 금지와 모순되지 않는다.
남은 제한: DTO 직렬화·어댑터 계약 시험, SDK retry 차단, 원격 취소/과금 확인은 NOT_RUN. 표의 정책을 실제 API 기능 지원으로 간주하지 않는다.

### 범위 한정 결론과 다음 게이트

D11-01~07 **7/7 RECHECKED**, D11 범위의 문서상 OPEN **0건**, 미해결 S0/S1 **0건**이다. 위 동결 A/V/Q에 한해 원 반례와 해결 조건의 문서상 보강을 확인했으며, D00 대응표의 다른 17건이나 팀 전체 G0 종결을 대신 판정하지 않는다. 최종 CLOSED·통합 G0 기록은 D00이 각 독립 검토 결과를 연결해 처리한다.
제품 실행 시험은 모두 **NOT_RUN**이다. 이번 결과는 G0 문서상 해결 근거이며 G1/G2의 transaction·fault injector·serializer golden fixture/crash 시험, G3의 장비/backend·수치 예산·AI corpus와 품질, G4의 패키지·라이선스·배포 검증을 통과한 기록이 아니다.
사용자가 제시한 “문서 18개·링크 92개·시나리오 40개·형식 이슈 0건”은 전달받은 전체 검사 결과로 구분하며, 이 재확인의 독립 실행 결과로 복사하지 않는다. 이번 자체 정적 검사는 이 파일의 기존 본문 보존·상대 링크·추가된 시험 ID와 동결 정본 digest 확인에 한정한다.
