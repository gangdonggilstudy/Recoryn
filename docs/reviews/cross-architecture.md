# D12 — 아키텍처·통합 계약 독립 오디오 교차 검토

작성일: 2026-11-14. 상태: **REVIEW_READY / 발견 사항 OPEN / D00 수정 후 재확인 대기**. D02의 1차 문서 작성은 완료했으며 이 문서는 타 세션 D01과 통합 명세만 검토한다. D02 작성물 또는 D00 수정을 대신 승인하지 않는다.

## 범위와 검토 기준

[D01 아키텍처](architecture.md) §2~4·7~11, [통합 설계](../architecture-v1.md)의 상태·시간·저장/복구·ADR03, [검증 계획](../validation-plan.md) U02/P01/P02/I03/F01~F05/W01~W04, [품질 체계](../quality-system.md), AGENTS.md와 배정표를 읽었다. 라이브 수정 중인 공용 문서는 아래 digest의 내용을 기준으로 한다.

| 검토 파일 | SHA-256 |
| --- | --- |
| `docs/reviews/architecture.md` | `324E8C422970C7A0694560F20CA4D5B40D937BDC0164B4A2D19F387BD7A951DE` |
| `docs/architecture-v1.md` | `EA1F997FF20F50A217152D0A19EF0D1C5B259FF5052E36A2FE72A29008605272` |
| `docs/validation-plan.md` | `667D51B10B13D9A7F3447870378F75CA6359C973F87DF0488D550B1DFCE0F4A4` |
| `docs/quality-system.md` | `FE0AD8FF751143A6DC9AF77A510F56186E78DA0D22B2559CC532958442E2B044` |
| `AGENTS.md` | `15722FEF93EE7C57B3344E5AF90E7CC79E8FEDFBDFCC459BA2AB98735CB56D6F` |
| `docs/collaboration/assignments.md` | `35AC1AB1517AB6558D4F1BE0B930A0FC0B679E19275F7547F21C3CF20B7FB5A2` |

## 확인한 계약

- 업무 상태·동의·삭제 의도는 SQLite 기준, 미디어는 raw PCM + `blocks.jsonl` + 최종 descriptor bundle이다. bundle→DB→manifest generation snapshot을 검토 기준으로 삼고 `.rcpcm` 채택을 요구하지 않는다. 파일/DB 전체 원자성은 가정하지 않는다.
- 최종 Session 명칭은 `FINALIZED`; D01의 `CLOSED`는 개념 대응으로 읽었다. Job/Attempt 분리도 통합 채택 사항이므로 명칭 차이 자체를 결함으로 세지 않는다.
- native는 앱에 전달된 OS endpoint 포맷, mic/system은 별도 원본이다. QPC 단위·run clock domain/UTC anchor·새 epoch·파생 드리프트 보정과 known/unknown gap을 구분한다.
- critical path의 제한된 enqueue, drop-newest, slot/byte cap, 별도 유실 누계, fragment 키, SILENT/미도착 구분은 최신 통합안에 반영되어 있다. 수치 크기와 backend 성능은 아직 입증되지 않았다.
- 독립 검토→D00 수정→동일 검토자 재확인 절차를 따른다. 아래는 문서 반례이며 실행 결함을 재현했다고 주장하지 않는다.

## 발견 사항 — 모두 OPEN

### D12-01 · S1 · manifest 실패 뒤 Session 종료 판정이 일치하지 않음

- 위치: 통합 설계 「상태와 실행 계약」 stop 순서·timeout, 「저장과 복구 계약」 4~5단계; D01 §3.1·4.2(4~6); 검증 F03/F04.
- 반례: 마지막 bundle 검증과 AudioRevision/최종 상태 DB commit은 성공 → manifest 교체만 접근 거부 → stop timeout. D01은 DB 결과를 유지하며 `manifest_sync_pending`을 표시하지만, 통합안의 DB→manifest 전체 종료 순서와 ‘확정 실패 시 INTERRUPTED’는 이 상황의 최종 상태를 구별하지 않는다. 저장된 원본의 실패와 snapshot projection 실패가 다른 결과로 구현될 수 있다.
- 해결 조건: `FINALIZED`의 필요조건과 stop 응답 시점을 명시한다. 권고는 media+DB 확정을 유지하고 manifest만 pending/실패로 분리하며 해당 snapshot export를 차단하는 것이다. 다른 정책이면 final 상태 commit과 projector 순서를 일관되게 정의한다. manifest 실패만으로 정상 원본/DB를 rollback하지 않는다.
- 검증 연결: F03/F04에 최종 DB commit 후 manifest 실패·재시작·재시도를 넣고 Session/health/stop 응답/export 가능 여부의 기대값을 하나로 고정한다. D00 수정 후 D12가 문서 재확인한다.

### D12-02 · S1 · PAUSED와 이전 epoch drain/봉인 완료의 경계가 다름

- 위치: 통합 설계 「상태와 실행 계약」 PAUSED 정의·resume; D01 §3.1 `RECORDING→PAUSED`; 검증 P01/F01/W03.
- 반례: E1의 accepted 블록이 큐에 남은 상태에서 엔진 중단 ack → 통합안대로 PAUSED 표시 → 즉시 resume하여 E2 시작. D01은 PAUSED 이전에 E1 청크 봉인을 요구한다. writer를 barrier로 멈춰 E1 꼬리를 놓치거나, E1 close를 기다리는 중 E2 블록을 어느 청크로 보낼지 구현마다 달라진다. epoch 키가 존재한다는 사실만으로 drain 완료가 확인되지는 않는다.
- 해결 조건: 트랙별 cutoff, 마지막 accepted sequence/fragment, 최종 유실 누계와 writer drain/seal ack를 제어 경로에서 전달한다. PAUSED가 캡처 중단만 뜻하면 `seal_pending`과 resume의 epoch별 처리 규칙을 명시하고, 봉인 완료까지 뜻하면 pending pause 상태를 둔다. stop도 큐의 빈 공간을 기다려야 하는 유일한 stop marker에 의존하지 않으며, 모든 트랙의 보존/유실을 확인한 뒤 성공한다.
- 검증 연결: barrier로 writer를 정지하고 포화→pause→즉시 resume→stop을 양 순서로 실행한다. E1/E2 혼입·accepted 꼬리 누락·중복 0, 후속 성공 블록 없이 stop해도 마지막 known drop 보존, 최종 누계 미영속 crash만 unknown으로 처리하도록 P01/F01을 구체화한다.

### D12-03 · S1 · FINALIZED 세션의 뒤늦은 orphan 채택과 AudioRevision 관계가 빠짐

- 위치: 통합 설계 「저장과 복구 계약」 고아 재등록·「메타데이터와 산출물 버전」; D01 §4.3 ACTIVE 세션 채택·§6~7; 검증 I03/P01.
- 반례: lifecycle=ACTIVE, capture=FINALIZED, 봉인 AudioRevision R1=[C1], R1의 전사가 준비된 fixture에 같은 세션/epoch의 유효한 미등록 C2를 둔다(이전에 격리된 crash 꼬리를 되찾은 경우). 복구를 두 번 실행한다. 현재 orphan 채택 조건은 ACTIVE이므로 C2가 카탈로그에는 추가될 수 있지만 R1 목록을 바꿀지, 새 revision을 만들지, 기존 `transcript_ready`를 유지할지 정하지 않았다.
- 해결 조건: lifecycle ACTIVE와 녹음 미봉인을 구별한다. FINALIZED 뒤 발견한 미디어는 기본 후보/격리로 두거나 명시적 채택 시 새 AudioRevision/timeline을 생성한다. R1을 제자리 변경하지 않고 기존 전사의 입력 참조를 유지하며 최신 오디오 대비 readiness/freshness를 재계산한다. 삭제 의도와 현재 writer 소유권 검사는 그대로 우선한다.
- 검증 연결: I03/P01에 위 fixture 및 반복 복구를 추가한다. C2 중복 0, R1 hash 불변, R1 전사를 R2 전체 처리 완료로 표시하지 않음, 사용자 편집 보존을 기대값으로 둔다.

### D12-04 · S2 · capture_mono_ns의 관측 시점과 timestamp 오류 사용 규칙이 미정

- 위치: 통합 설계 「시간과 오디오 계약」 PCMBlock·epoch별 매핑; D01 §2 audio 위임; 검증 U02/P02/W01.
- 반례: 같은 epoch에서 seq1의 첫 sample 시각 1.000초 → seq2 timestamp 오류로 첫 sample 대신 도착 시각 1.060초를 낮은 품질 `capture_mono_ns`에 기록 → seq3의 유효 첫 sample 시각 1.020초. 필드가 sample 시각인지 arrival인지 고정되지 않으면 낮은 품질 표시만으로 회귀 오염 또는 시간 역행을 막지 못한다. run domain을 나누는 기존 규칙만으로는 같은 epoch의 오류를 다루지 못한다.
- 해결 조건: 첫 sample의 유효 상관 시각과 arrival 시각을 구분하고 단위·clock domain·nullable/quality 의미를 고정한다. timestamp 오류 표본은 drift 적합에서 제외하고 arrival 대체 추정은 별도 근거로 남긴다. 같은 epoch의 위치/시각 역행은 연속 매핑 구간 분리 또는 명시적 unknown 처리를 정의한다. 임계 수치·회귀 알고리즘 선정은 구현 실험으로 남겨도 된다.
- 검증 연결: U02/P02에 위 3블록, 도착 jitter, 잘못된 device position, 마지막 timestamp 오류 후 stop을 추가한다. 거짓 정밀도·음수 구간·오류 표본의 정상 적합 사용을 금지하고 unknown 경계를 보존한다.

### D12-05 · S2 · 채택된 블록 journal의 독립 장애가 검증 matrix에 추적되지 않음

- 위치: 통합 설계 「저장과 복구 계약」 `blocks.jsonl`; 검증 F02는 여전히 PCM/descriptor 작성·flush만 열거; 품질 체계 G1/G2.
- 반례: PCM 쓰기 성공 후 journal 부분 append, 또는 journal 레코드는 완성됐으나 해당 PCM 쓰기/flush가 실패한 두 fixture가 필요하다. PCM/descriptor만 kill하는 F02 실행으로는 journal checksum·범위 검사·prefix 중단을 전혀 실행하지 않고도 시험 통과를 보고할 수 있다. 이는 형식 채택의 반대가 아니라 증거 범위 누락이다.
- 해결 조건: F02/F04에 journal append/flush/close, 잘린 JSONL, 레코드·payload checksum 불일치, offset 겹침/역행, fragment 일부 누락을 명시한다. 독립 PCM/journal 잔존 조합에서 마지막 유효 prefix만 새 artifact로 보존하고 원본 staging을 덮어쓰지 않는 oracle을 둔다. descriptor 봉인 시 양 파일 검증도 명시한다.
- 게이트 구분: G0에서는 위 불변식·시험 ID·담당 연결을 문서화하면 된다. checksum canonicalization·레코드 크기 한도·실제 flush 순서·golden serializer fixture와 실행 통과는 구현 G1/G2 게이트이며 이번 설계 리뷰의 실행 합격 조건으로 요구하지 않는다.

## 미검증 및 재확인 절차

- 구현·라이브러리/API 실행·VoiceLocal 분석·실장치·전원 차단·성능 시험은 수행하지 않았다. 위 반례의 실제 결과는 NOT_RUN이다. 정량 예산·backend 채택은 ADR06/07 및 G3, journal 구현은 G1/G2, 배포는 G4에 남긴다.
- 현재 판단은 S1 3건, S2 2건의 검토 제안이다. D00이 수정한 파일/절·digest와 대응 근거를 연결하면 D12가 각 반례의 문서상 해소를 재확인한다. 실행 시험의 NOT_RUN은 문서 재확인으로 PASS가 되지 않는다.
- 자신의 1차 문서나 D00 변경의 최종 승인·설계 전체 종결은 하지 않았다. 이번 변경은 이 파일 하나이며 기존 1차 문서·공용 파일·Git 인덱스/브랜치를 수정하지 않았다.

## D12 수정 후 독립 재확인 — 2026-11-14

현재 판정: **D12-01~D12-05 모두 RECHECKED, G0 문서상 해결 확인**. 위 OPEN 표기·반례·당시 digest는 최초 검토의 이력으로 보존한다. 이 후단의 판정이 아래 동결 snapshot에 대한 최신 D12 결과다. CLOSED 전환과 전체 G0 종결 집계는 D00 소유다.

### 동결 snapshot D12-R1

사용자 지정 SHA-256과 실제 파일 hash의 일치를 확인했다. 각 ID의 재확인은 공통으로 이 snapshot을 대상으로 하며, 줄 번호도 이 digest 기준이다.

| 정본 | SHA-256 |
| --- | --- |
| A — `docs/architecture-v1.md` | `E08450D0899A5DCF4DDE5745B6BC58B1A7B6F0B2BF0867CAC4FF405D96DA7ABD` |
| V — `docs/validation-plan.md` | `DF1551A71C3BF55C6A4466B68443EFDE1673A7C22A1BBB867A69DD6F527601AB` |
| Q — `docs/quality-system.md` | `FE0AD8FF751143A6DC9AF77A510F56186E78DA0D22B2559CC532958442E2B044` |

[D00 수정 대응표](design-signoff.md)의 D12 5행도 읽었으며, 그 FIXED 표기만으로 판정하지 않고 아래 정본 문구와 시험 기대값을 직접 대조했다. 대응표 열람 시 SHA-256은 `BC0728442A4E6D69F75BB609E3F7DC66CC4854721D8D3BAA0A9D1866A983CBFC`였다.

### D12-01 — RECHECKED · S1 · D12-R1 A/V/Q

- 확인 절: A 「상태와 실행 계약」 83행은 원본/DB 실패와 manifest-only 실패를 분리하고, 후자는 `FINALIZED` 유지·`manifest_sync_pending`·재시도·원본 성공 rollback 금지·해당 project export 차단을 명시한다.
- 반례 대조: 마지막 DB commit 뒤 manifest 접근 거부가 발생해도 원본 저장 결과를 INTERRUPTED로 뒤집지 않는다. stop 응답도 원본 확정과 projection pending을 구별하므로 원래의 두 종료 해석이 문서상 해소됐다.
- 시험 ID/기대값: V F03/F04(62~63행)는 바로 그 순서와 재시작 후 projection 재시도, media 유지·rollback/중복 금지를 고정한다. **G0 해결 확인**. 남은 제한: 실제 transaction·projector·export 차단과 장애 복구 실행은 G1/G2의 NOT_RUN이다.

### D12-02 — RECHECKED · S1 · D12-R1 A/V/Q

- 확인 절: A 「상태와 실행 계약」 79~83행은 모든 필수 트랙의 capture gate와 이전 epoch drain/seal ack가 끝나야 PAUSED가 되며, 그 전에는 `pending_command=PAUSE`를 표시하고 resume을 막는다. 트랙별 cutoff·마지막 accepted sequence/fragment·최종 유실 누계·writer ack는 별도 제어 경로로 전달한다.
- 반례 대조: E1 accepted 꼬리가 남은 동안 E2를 시작할 수 없다. 포화된 PCM stop marker에 의존하지 않고 수락/유실 회계 확인 전 성공을 금지하며 late callback과 cutoff 뒤 AI tap도 gate로 차단한다.
- 시험 ID/기대값: V P01/F01/W03(37·60·73행)에 포화→pause→즉시 resume→stop, 후속 성공 블록 없음, 필수 ack 지연/누락이 포함됐다. 최종 known drop 영속화·E1/E2 혼입 0·미영속 crash만 unknown이라는 기대가 원 해결 조건과 일치한다. **G0 해결 확인**. 남은 제한: ack의 실제 동시성·backend stop 동작·privacy cutoff 실측은 G1/G2 및 G3의 NOT_RUN이다.

### D12-03 — RECHECKED · S1 · D12-R1 A/V/Q

- 확인 절: A 「저장과 복구 계약」 158~160행은 소유권·삭제 의도를 먼저 검사하고 FINALIZED 이후 orphan의 자동 편입을 금지한다. 기본 후보/격리, 명시 채택 시 새 AudioRevision/필요 timeline revision, 기존 목록/hash·전사/편집 입력 유지와 readiness 재계산을 명시한다. 「메타데이터와 산출물 버전」 182행은 선택 AudioRevision/timeline에 맞는 전체 coverage를 준비 조건으로 둔다.
- 반례 대조: R1=[C1] 뒤 C2를 찾더라도 R1을 변경하지 않는다. 사용자가 R2로 채택한 경우 R1 전사를 R2의 전체 처리 완료로 승격하지 않으며 삭제 이력 판정불가 시 자동 채택을 보류한다.
- 시험 ID/기대값: V I03/P01(48·37행)이 FINALIZED R1, orphan C2, 반복 복구, R1/hash/전사·편집 불변과 R2 readiness를 직접 열거한다. **G0 해결 확인**. 남은 제한: 새 revision 게시의 멱등성·CAS·반복 복구 결과는 G1/G2의 NOT_RUN이다.

### D12-04 — RECHECKED · S2 · D12-R1 A/V/Q

- 확인 절: A 「시간과 오디오 계약」 114~118행은 run clock domain/단위를 구별하고 `capture_mono_ns`를 유효한 첫 sample 상관 시각의 nullable 값으로 한정한다. arrival는 별도 필드/domain이고 timestamp 오류·무효 위치는 적합에서 제외한다. 같은 epoch의 역행은 mapping 구간 분리/unknown, 참조 끝 시각 부재는 정밀 범위 생성 금지로 처리한다.
- 반례 대조: 1.000→오류 arrival 1.060→유효 sample 1.020에서 중간 arrival를 capture에 대입하거나 정상 drift 표본으로 사용할 수 없으므로 원래의 의미 혼합이 문서상 차단됐다.
- 시험 ID/기대값: V U02(30행)가 정확한 3블록 oracle과 마지막 오류 뒤 stop/unknown을 포함하며 P02는 단조성·gap·역참조 정합성을 검증하도록 연결돼 있다. **G0 해결 확인**. 남은 제한: 회귀 알고리즘·임계 수치·장치 timestamp 품질과 정렬 오차는 G1/G2/G3의 NOT_RUN이다.

### D12-05 — RECHECKED · S2 · D12-R1 A/V/Q

- 확인 절: A 「저장과 복구 계약」 146~148행은 data의 연속 PCM prefix·offset/length/frame alignment·identity/fragment 유일성과 순서를 요구한다. 중복 append도 위반이며 gap/event는 payload 없는 별도 kind다. torn write/다른 epoch/부분 fragment를 독립 검증하고 봉인 시 PCM·journal·descriptor를 함께 검사한다.
- 반례 대조: PCM만 남은 경우와 journal이 완성돼도 PCM이 손상된 경우를 같은 성공 상태로 취급하지 않는다. 검증된 연속 prefix만 새 artifact로 보존하며 staging을 덮어쓰지 않는 oracle이 시험에 명시됐다.
- 시험 ID/기대값: V F02/F04(61·63행)는 세 파일 각각의 append/flush/close kill, JSONL 절단·hash 오류·중복/겹침/역행·다른 epoch·일부 fragment와 독립 잔존 조합을 열거한다. F02는 2회 복구 비교·독립 input oracle도 요구한다. **G0 해결 확인**. 남은 제한: checksum 직렬화 규칙·레코드 한도·실제 flush 순서·golden fixture 및 crash 실행은 계속 G1/G2의 NOT_RUN이다.

### 범위와 결과

- 재확인 **5/5건**, 이 snapshot에서 D12 원 지적의 문서상 미해결 **S0/S1 0건, S2 0건**. 이는 타 세션 D01에서 이어진 문제와 D00 정본의 수정 대조 결과이며 자신의 1차 문서 승인 또는 전체 설계/제품 합격 선언이 아니다.
- 제품 유닛·통합·장치·성능·전원 장애 시험은 모두 NOT_RUN이다. Q의 독립성·발견 상태·G0~G4 구분을 유지한다. 사용자가 보고한 문서 18개/로컬 링크 92개/시험시나리오 40개·이슈 0건은 정적 검사 현황이며 실행 시험 통과의 근거로 사용하지 않았다.
- 이 재확인에서는 기존 67줄과 당시 hash를 보존하고 이 후단만 추가했다. 정본 수정·Git 변경·재위임 없이 지정 교차 검토 파일만 갱신했다. snapshot 변경 시 영향받는 ID는 새 digest에 대한 재확인이 필요하다.
