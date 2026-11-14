# D13 독립 ML·UX 교차 검토 — 보안·QA 및 통합 계약

작성일: 2026-11-14. 상태: **REVIEW_READY / 발견 사항 OPEN / D00 수정 후 동일 검토자 재확인 대기**. 설계 검토 제안이며 승인·제품 시험 PASS가 아니다.

## 검토 범위와 확인한 계약

- 최신 AGENTS·배정표·품질 체계·통합 설계·검증 계획과 타 세션의 [D04 보안·QA](security-qa.md)를 읽었다. D03 본인 작성물의 승인이나 재심사를 수행하지 않았다. 이번 D13에서 Git 명령·재위임·다른 파일 수정은 하지 않았다.
- 기준은 SQLite 업무 상태, raw PCM+`blocks.jsonl`+봉인 descriptor bundle, `bundle → DB → manifest generation snapshot`, D02 O-A09 대안 A다. 파일/DB 원자성을 가정하지 않으며 초기 `.rcpcm` 미채택을 결함으로 보지 않는다.
- Session 최종 상태는 `FINALIZED`이며 D01의 CLOSED는 개념 대응이다. Job/Attempt 분리, 기존 fence의 늦은 결과 차단, 원본 보존과 삭제 우선, 불변 전사·근거를 확인했다.
- loopback 전송과 실제 추론 위치 분리, 위치 미확인 모델 차단, cloud 구성 확인·후속 트래픽 관측, CPU 동의 및 strict GPU 미지원 차단을 확인했다. 이는 설계 계약 확인이며 실제 차단 효과는 미검증이다.
- 검토 중 반영된 실행 계획 고정·permission generation·비용 ledger·core span coverage 규칙은 누락 지적에서 제외했다. 아래 반례는 이를 포함한 스냅샷에 남은 경계 문제를 향후 재현할 event 순서이며 실제 실행 결과가 아니다.

## 발견 사항

### D13-01 / S0 / OPEN — 철회와 실제 송신의 직렬화 경계 누락
- 파일/절: [통합 설계](../architecture-v1.md) 「전송 동의와 비용」·「AI 제공업체와 자원 관리」, [검증 계획](../validation-plan.md) U06/I07; D04 §3.2·QA-S03/04.
- 반례: gateway가 generation G의 동의를 검사 → barrier 대기 → UI 철회가 G+1을 영속화하고 성공 표시 → 과거 검사 결과로 SDK가 첫 본문을 송신. 단순한 “전송 직전 검사”와 실행 계획 고정만으로는 이 순서를 배제하지 못한다. queued 철회 시험만으로도 발견되지 않는다.
- 해결 조건: 최종 SendPermit 소비/송신 handoff와 철회 기록의 공통 직렬화 지점, 허용하는 in-flight 바이트의 경계를 통합 계약에 명시한다. 검사 직후·첫 write 직전·후속 application write 직전 barrier 시험에서 철회 이후 새 송신을 차단하고 이미 OS/TLS로 넘긴 바이트와 분리 집계한다. D04의 경합 계약 채택 여부를 명시하고 권한 DB 기록 실패 시 성공 UI를 금지한다. 영향: G0 계약, P1/P2 전송 게이트.

### D13-02 / S0 / OPEN — 정상 백업 복원이 철회한 grant를 되살릴 수 있음
- 파일/절: 통합 설계 「저장과 복구 계약」·「메타데이터와 산출물 버전」·「전송 동의와 비용」, 검증 계획 F05/I07; D04 §3.1·§6.2.
- 반례: 승인·queued 요청이 있는 정상 DB 백업 B 생성 → 현재 DB에서 승인 철회 → 손상 없는 B를 같은 PC·같은 credential 환경에 복원 → 복원된 활성 grant로 전송 직전 검사. DB 손상 때만 동의를 없어진 것으로 처리하는 규칙은 이 정상 복원 경로를 정의하지 않는다. 낡은 grant를 기준으로 검사하면 철회를 역행할 수 있다.
- 해결 조건: 백업/프로젝트 import/라이브러리 복원은 실행 권한 복원이 아님을 명시하고 새 라이브러리 실행 세대에서 기존 grant/permit 및 자동 원격 재개를 비활성화한다. F05에 정상 백업·동일 PC·유효 키·철회 후 rollback 반례를 추가해 재동의 전 송신 0건을 확인한다. tombstone rollback의 한계와 별도로 안내한다. 영향: G0 계약, 복원 기능 도입 게이트.

### D13-03 / S1 / OPEN — 취소와 active revision 게시의 공통 DB 판정 부족
- 파일/절: 통합 설계 「상태와 실행 계약」·「메타데이터와 산출물 버전」, 검증 계획 I04/I05; D04 §3.2·QA-S09.
- 반례: 현 attempt/fence가 결과 검증 완료 → 취소가 DB에 먼저 기록되나 fence/부모 revision은 유지 → worker가 부모만 비교하여 active pointer 갱신 → Job 성공 전이는 거부되어도 취소한 결과가 활성화됨. “이전 fence 차단”, “부모 비교”, 개별 상태 CAS만으로는 동일 fence의 이 경합을 배제하지 못한다.
- 해결 조건: 게시 DB transaction에서 현재 Job 취소/상태·유효 lease/fence·삭제 generation·입력/예상 부모를 함께 검사하여 artifact 등록과 active pointer 변경을 판정한다. 취소 우선/게시 우선 각각 barrier로 재현하고 DB 포인터·게시 이벤트·UI를 함께 검증한다. 먼저 만든 파일은 DB 실패 시 고아/격리로 처리하며 파일/DB 원자성을 가정하지 않는다. `CANCEL_REQUESTED → BLOCKED(CANCEL_UNCONFIRMED)` 및 이후 로컬 종료/원격 UNKNOWN 표시도 전이표에 명시한다. 영향: G0 계약, P1 게시·취소 게이트.

### D13-04 / S1 / OPEN — 세션 삭제와 미정산 비용 예약의 수명 충돌
- 파일/절: 통합 설계 「전송 동의와 비용」·「비밀과 데이터 수명」, 검증 계획 U08/I06/F06; D04 §6.2·QA-S06/09.
- 반례: 기간 한도 10에서 A 요청의 상한 8 예약 → 접수 불명으로 unknown_exposure=8 유지 → A 전체 삭제 → A의 작업·관련 metadata 정리 → 같은 기간 B가 8 예약. 세션 소유 예약까지 cascade 삭제하면 기존 위험 8이 사라져 예산을 우회한다. 반대로 전체 작업·본문을 보존하면 삭제 완료 계약을 위반한다. 현재 ledger 식과 “재시작 초기화 금지”는 삭제 수명을 정하지 않는다.
- 해결 조건: 미정산 예약/전송 의도는 세션 본문·작업 이력과 수명을 분리하고 삭제 후에도 비밀·원문·경로 없는 최소 요청 식별자/금액/상태로 계산에 남긴다. 예약 영속화→송신→정산 kill 지점 및 삭제→재시작→새 작업에서 exposure 보존과 금지 본문 제거를 함께 시험한다. ledger 손상·복원 불일치 시 엄격 예산 모드는 재구성/명시적 정산 전 새 요청을 차단한다. 영향: G0 수명 계약, P2 예산·삭제 게이트.

### D13-05 / S1 / OPEN — coverage 기록과 “전체 요약 완료” 판정이 연결되지 않음
- 파일/절: 통합 설계 「AI 제공업체와 자원 관리」·SummaryRevision 필드, 검증 계획 C01/M01/E01; D04 QA-S09·QA-H06.
- 반례: core A/B/C 중 B만 timeout → A/C의 유효 claim으로 통합 → coverage에 B 실패를 기록하되 Job SUCCEEDED 및 일반 완료 화면으로 게시. claim reference가 100% 유효하고 사실성 검사도 맞을 수 있지만 B의 결정은 빠진다. 실패 coverage 기록은 요구하나 부분 요약과 전체 성공의 필수 구별은 정의하지 않는다.
- 해결 조건: SummaryRevision의 partial/complete·미처리 범위와 Job 성공의 의미를 명시하고 전체 완료에는 계획 core 범위 전부의 처리·검증을 요구한다. C01/M01/E01에 중간 구간 실패·취소·재개를 넣어 실패 경고, 부분 결과 보존, 영향 상위 통합 재계산을 검증한다. 이는 품질 임계값 수치가 아니라 결과 완전성 계약이다. 영향: G0 계약, 요약 최초 도입 게이트.

### D13-06 / S2 / OPEN — 사람 사실성 평가의 독립 oracle가 불충분
- 파일/절: 검증 계획 M01 및 「AI 품질과 UX」, [품질 체계](../quality-system.md) 「유닛과 속성 시험 설계」·G3, D04 B08·QA-H06.
- 반례: “일정 변경을 논의했다”와 “일정 변경을 확정했다”가 같은 유효 segment를 인용. 한 평가자는 주제 일치로 supported, 다른 평가자는 확정 발언 부재로 unsupported 판정. corpus/분할과 사람 검토만 고정하면 같은 게이트에서 반대 결론을 낼 수 있다. claim이 거의 없는 요약은 reference 비율만 높일 수도 있다.
- 해결 조건: claim 분할·판정 단위, supported/unsupported/uncertain/상충·사용자 주장 기준, 무주장/빈 결과 처리, 핵심 결정·할 일 누락의 분모를 정한다. 비민감 고정 예시의 독립 라벨·불일치 조정·평가자 간 일치도를 증거에 포함한다. corpus 수/합격 임계값은 예정대로 P1 전 실험 게이트에서 고정하되 프로토콜 없는 주관 평가를 통과 근거로 삼지 않는다. 영향: P1 이전 평가 프로토콜, G3 품질 게이트.

### D13-07 / S2 / OPEN — 권한·비용·복구의 키보드/읽기 도구 시험 경로 부족
- 파일/절: 통합 설계 「UX와 관측」, 검증 계획 E01/E02, D04 G-P1·QA-V06·B02.
- 반례: 녹음/정지/seek의 키보드 경로와 일반 오류 읽기는 성공하지만 동의창에서 거부 버튼 이동 불가·Esc가 허용 처리, 예산 BLOCKED에서 취소 불가, 복구 알림이 포커스를 탈취. E01 정상 처리 순서와 E02의 일반 판정만으로 이 경로의 필수 실행을 보장하지 않는다. D04의 명시적 읽기 도구 matrix는 P3에 있으나 권한 UI는 P1이다.
- 해결 조건: P1 E02 필수 절차에 동의 허용/거부/철회, CPU 전환 거부, 비용 대기 취소, 원격 취소 미확인 설명, 복구 검토·닫기를 명시한다. Narrator·키보드에서 수신자/범위/비용 읽기, 거부 기본값·Esc 비허용, 포커스 복귀·복구 gap 낭독을 각각 기대 결과로 둔다. B02/취소 목표는 UI 수신·정책 기록·로컬 종료·원격 미확인 시점을 분리하며 수치는 측정 전 제안으로 유지한다. 영향: P1 권한·복구 UX 게이트.

## 버전 증거와 미검증 범위

아래 SHA-256은 각 파일을 한 번 읽은 bytes와 결합한 검토 스냅샷이다. 이후 변경은 자동 재확인으로 간주하지 않는다.
- `AGENTS.md`: `15722FEF93EE7C57B3344E5AF90E7CC79E8FEDFBDFCC459BA2AB98735CB56D6F`
- `docs/quality-system.md`: `FE0AD8FF751143A6DC9AF77A510F56186E78DA0D22B2559CC532958442E2B044`
- `docs/validation-plan.md`: `667D51B10B13D9A7F3447870378F75CA6359C973F87DF0488D550B1DFCE0F4A4`
- `docs/architecture-v1.md`: `EA1F997FF20F50A217152D0A19EF0D1C5B259FF5052E36A2FE72A29008605272`
- `docs/collaboration/assignments.md`: `35AC1AB1517AB6558D4F1BE0B930A0FC0B679E19275F7547F21C3CF20B7FB5A2`
- `docs/reviews/security-qa.md`: `182B92F572574DA02B1E92309A39CC7016F2EE075C5E75333C855B8B01A6DBD6`

- 블록 journal serializer/flush·golden fixture, 오디오 backend, 청크/큐·지연 수치, 품질 corpus 크기/임계값은 구현·측정 게이트다. 미구현 자체를 위 발견의 근거로 쓰지 않았다.
- 이번 검증은 문서 계약과 event 순서의 정적 대조뿐이다. 제품 시험·barrier 실행·API/네트워크·비용 청구·Credential Manager·모델/VoiceLocal 분석·Windows 접근성/복구/하드웨어 시험은 모두 NOT_RUN이다. 외부 API의 새 기능 가정을 사용하지 않아 추가 웹 조회는 하지 않았다.
- 수정 담당은 D00, 재확인은 D13 동일 검토자다. D00은 수정 위치/새 digest·반례 차단 근거를 제시하고 검토자는 각 ID를 다시 대조한 후 별도로 상태를 남긴다. 이 문서는 D03 자체 승인, D00 수정 승인, 이슈 종결이나 G0 통과를 선언하지 않는다.

## D13 수정 후 독립 재확인 — 2026-11-14

이 후단이 D13의 최신 판정이다. 앞의 OPEN 기록·원 반례·당시 digest는 역사 기록으로 보존한다. 재확인 전 이 파일 SHA-256은 `1D9357A2F5B093A997E1DC4312AD0862CF5C32DA28409A3725BD4313D933576C`다. 검토자는 같은 D13 세션이며 수정자는 D00이다. D01~D04의 자기 작성물을 승인하거나 D00의 통합·push 승인을 대신하지 않는다.

### 동결 스냅샷 G0-D13-R1

아래 A/V/Q 묶음이 각 ID 재확인의 새 digest다. 파일 bytes에서 계산한 SHA-256은 사용자 지정값과 모두 일치했다.
- A — `docs/architecture-v1.md`: `E08450D0899A5DCF4DDE5745B6BC58B1A7B6F0B2BF0867CAC4FF405D96DA7ABD`
- V — `docs/validation-plan.md`: `DF1551A71C3BF55C6A4466B68443EFDE1673A7C22A1BBB867A69DD6F527601AB`
- Q — `docs/quality-system.md`: `FE0AD8FF751143A6DC9AF77A510F56186E78DA0D22B2559CC532958442E2B044`
- 수정 대응표 — [design-signoff.md](design-signoff.md): `BC0728442A4E6D69F75BB609E3F7DC66CC4854721D8D3BAA0A9D1866A983CBFC`. 24건 중 D13-01~07의 FIXED 주장과 A/V 실제 문구를 대조했다. 다른 검토자의 17건은 이 재확인의 판정 대상이 아니다.

### D13-01 / RECHECKED — G0 문서상 해결
- 새 digest: G0-D13-R1(A/V/Q). 확인 절: A 「전송 동의와 비용」 L215~217; V U06/I07/S01.
- 대조: 최종 permit 재검사와 transport handoff를 철회·삭제와 같은 직렬화 경계에서 수행한다. DNS/연결/첫·후속 write 이전에도 재검사하며 commit 이후 신규 단위는 시작하지 않는다. I07은 원 반례의 검사 직후 barrier와 양 commit 순서, 정책 기록 실패의 성공 표시 금지를 요구한다. S01에는 observer 양성 대조가 있다. 과거 G permit으로 철회 후 첫 송신하는 순서는 새 계약에서 허용되지 않는다.
- 남은 제한: 잠금·transport/SDK별 실제 handoff 단위, 이미 넘긴 버퍼 바이트 계수와 무송신 관측은 G1/G2 및 해당 어댑터 게이트의 실행 증거가 필요하다. 제품 시험 NOT_RUN.

### D13-02 / RECHECKED — G0 문서상 해결
- 새 digest: G0-D13-R1(A/V/Q). 확인 절: A 「메타데이터와 산출물 버전」 L186~188·「저장과 복구 계약」 L158~160; V F05/I07.
- 대조: 정상 백업/import에도 새 library execution generation을 만들고 grant/permit·자동 외부 재개를 비활성화한다. 같은 PC·유효 credential도 예외가 아니며 키 참조 재연결과 범위별 재동의가 필요하다. F05는 원 반례인 철회 후 정상 과거 백업 복원과 유효 키 조건을 명시하고 재동의 전 egress 0을 요구한다. 삭제·ledger 완전성 불명확 시 자동 복구/엄격 예산 전송도 보류한다.
- 남은 제한: 실제 restore/import 진입점 전부에서 generation 교체·비활성화·무송신을 확인해야 한다. 오래된 외부 백업의 삭제 이력 자체를 복원했다는 보장은 하지 않는다. 제품 시험 NOT_RUN.

### D13-03 / RECHECKED — G0 문서상 해결
- 새 digest: G0-D13-R1(A/V/Q). 확인 절: A 「상태와 실행 계약」 L87~102·「메타데이터와 산출물 버전」 L178~180·「UX와 관측」 L251; V I04/I05/C02/E02.
- 대조: Job 취소·attempt/fence·삭제 세대·입력을 검사하고 artifact/revision·선택 포인터·Job/Attempt 완료·outbox를 같은 DB transaction에서 commit한다. 취소도 같은 경계에서 fence를 회수하므로 부모 비교만 통과한 동일 attempt의 게시가 불가하다. 게시 우선은 ALREADY_SUCCEEDED, 취소 우선은 active 불변·새 dispatch 0이며 I04가 양 순서와 취소 직후 crash를 명시한다. 취소 미확인 BLOCKED(CANCEL_UNCONFIRMED), UNKNOWN 우선순위와 UI 완료 시점 분리도 본문에 정의되어 있다.
- 남은 제한: 실제 DB 조건식·lease/fence·선택 CAS와 UI 투영, 취소 미확인 이유 코드의 일관성을 G1/G2에서 시험해야 한다. 파일 선행 게시 뒤 DB 실패는 비활성 후보이며 파일/DB 원자성이나 원격 중단 성공으로 확대하지 않는다. 제품 시험 NOT_RUN.

### D13-04 / RECHECKED — G0 문서상 해결
- 새 digest: G0-D13-R1(A/V/Q). 확인 절: A 「전송 동의와 비용」 L225~231·「메타데이터와 산출물 버전」 L188; V U08/I06/F06.
- 대조: ledger는 세션/Job과 수명이 분리된 라이브러리 기록이며 삭제 cascade로 예약을 풀지 않는다. 삭제 후 남는 것은 본문·비밀·제목·경로 없는 최소 ID/통화/기간/금액/상태다. I06에 한도 10·UNKNOWN 8·A 삭제 뒤 B의 새 8 차단이라는 원 반례, 예약→dispatch→정산 각 kill 및 금지 본문 제거를 넣었다. 손상/rollback/불일치 시 엄격 전송을 막으며 U08은 중복 정산·재시작의 독립 수치 oracle를 제공한다.
- 남은 제한: ledger 스키마·영속 순서·삭제 정리·정산 재구성의 실제 장애 시험과 최소 잔존 정보의 UI 고지가 필요하다. 제공업체 최종 청구액 상한이나 원격 취소/환불을 보장하지 않는다. 제품 시험 NOT_RUN.

### D13-05 / RECHECKED — G0 문서상 해결
- 새 digest: G0-D13-R1(A/V/Q). 확인 절: A 「메타데이터와 산출물 버전」 L182~184·「상태와 실행 계약」 L91; V C01/M01/E01.
- 대조: partial/complete·실패/미처리 범위가 필수이며 complete와 전체 Job SUCCEEDED는 모든 계획 core span 및 필요한 통합 성공을 요구한다. 일부 성공은 부분 revision으로 보존하되 부모 Job은 실제 실패/대기/취소 상태다. 따라서 A/C만으로 B 실패를 숨긴 전체 성공은 금지된다. C01/M01/E01은 1/10 성공과 빈 결과·정상 무음을 구별하고 실패 9/10을 전체 완료로 표시하지 못하게 한다. 새 부분 범위 계획도 원래 전체 범위를 완료한 것으로 표시할 수 없다.
- 남은 제한: 실제 segment coverage oracle·중간 실패/취소·재개 시 checkpoint 호환과 영향 상위 통합 재계산은 G1/G2 시험이 필요하다. 문서상 완전성 확인은 요약의 의미 정확성 통과가 아니다. 제품 시험 NOT_RUN.

### D13-06 / RECHECKED — G0 문서상 해결
- 새 digest: G0-D13-R1(A/V/Q). 확인 절: V 「AI 품질과 UX」 M01 및 L102~104; Q 「유닛과 속성 시험 설계」·G3.
- 대조: 원자 claim·핵심 결정/할 일 단위, supported/unsupported/uncertain/disputed 및 user_assertion 분리, “논의→확정”의 unsupported 예시가 명시됐다. 두 독립 평가자와 고정 비민감 예시, 불일치 사유·조정·일치도 기록을 요구한다. 빈/무주장 결과는 reference 만점이 아니며 누락률 분모를 corpus의 사람 정의 핵심 항목 수로 고정한다. 프로토콜·표본수·임계값 확정 전 G3 종결 금지로 원래의 판정 재현성 공백을 해소했다.
- 남은 제한: corpus·평가자 라벨·정규화·표본수·임계값 및 실제 일치도/품질 수치는 아직 없다. 예정된 P1 전 확정 및 G3 평가 게이트를 유지하며 임의 PASS를 부여하지 않는다. 제품 시험 NOT_RUN.

### D13-07 / RECHECKED — G0 문서상 해결
- 새 digest: G0-D13-R1(A/V/Q). 확인 절: A 「UX와 관측」 L249~251; V E02 및 「정량 목표 제안」의 종료·취소; Q G2/G3.
- 대조: P1부터 Narrator/키보드로 동의 허용·거부·철회, CPU 거부, 예산 대기 취소, 원격 취소 미확인 설명, 복구 검토·닫기를 필수화했다. 수신자/범위/비용 읽기, 기본 거부·Esc 허용 금지, focus 복귀·gap 읽기·trap 없음과 ack 미확인 정지의 완료 낭독 금지가 E02에 명시됐다. UI 입력/정책 기록/로컬 ack/원격 미확인 시점도 분리되어 일반 녹음 경로만 시험하고 통과시키는 해석을 배제한다.
- 남은 제한: 실제 Windows Narrator·키보드·고대비/배율·부하에서 조작/낭독/포커스와 응답시간을 시험해야 한다. 수치 목표는 측정 전 제안이며 원격 취소 완료 deadline이 아니다. 제품 시험 NOT_RUN.

### 재확인 범위의 결론

- D13-01~D13-07 **7건 RECHECKED, 문서상 미해결 OPEN 0건(S0/S1 포함)**. 이는 동결 A/V/Q의 원 반례 및 해결 조건에 대한 D13 범위의 G0 문서상 해결 재확인이다. 상태를 CLOSED로 대신 변경하거나 전체 24건·전체 G0·구현·릴리스를 승인하지 않는다. D00이 다른 검토 결과와 함께 통합 종결을 판단한다.
- serializer/flush golden fixture·backend·수치·품질 corpus/임계값은 기존 구현/측정 게이트에 남는다. 모든 제품 실행 시험은 NOT_RUN이며 정적 링크·형식 검사와 분리한다. 사용자가 전달한 문서 18개·링크 92개·시나리오 40개 검사 결과를 D13의 실행 결과로 재기록하지 않는다.
