# D14 독립 보안·QA 교차 검토: 오디오·복구와 통합 게이트

상태: **검토 제안 / 발견 사항 OPEN / 수정 후 동일 검토자 재확인 대기**. 2026-11-14.
검토 범위: 타 세션의 [D02](audio-recovery.md), [통합 설계](../architecture-v1.md), [검증 계획](../validation-plan.md), [품질 체계](../quality-system.md). 최신 AGENTS와 배정표를 읽었다. 쓰기는 이 파일만 허용된다.
독립성: D04 자기 작성물의 승인이나 D00 통합 수정의 승인을 대신하지 않는다. 아래 반례는 명세를 검토하기 위한 실행 순서이며 실제 제품 재현 결과가 아니다.

## 검토 기준과 확인한 계약

- 업무 상태는 SQLite, 미디어는 `audio.pcm + blocks.jsonl + descriptor` bundle, 게시 순서는 **bundle → DB → manifest generation snapshot**이다. 파일/DB 원자성을 가정하지 않는다.
- D02 O-A09 대안 A를 기준으로 보았다. `.rcpcm`·manifest delta 대안의 미채택 자체와 D02 제안 문서에 남은 대안 설명은 결함으로 계산하지 않았다.
- Session 완료 이름은 `FINALIZED`다. D01의 CLOSED 개념과 이름 차이는 지적하지 않는다. 통합 Job/Attempt 분리·fence, 원본 불변·파생 보정, 삭제 우선 복구, 실행 위치 미확인 차단을 확인했다.
- process kill과 물리 전원 장애의 주장이 분리되어 있으며 실행 시험은 모두 `NOT_RUN`이다. serializer의 바이트 형식·flush 조합, backend와 정량값은 후속 구현/실험 게이트다.
- 아래 S0/S1은 구현 결함 확정이 아니라 고위험 **계약/검증 공백의 심각도 제안**이다. G0에서는 계약·시험 설계 수정, G1~G4에서는 해당 실행 증거가 필요하다.

검토 스냅샷 SHA-256(이후 내용 변경 시 재확인 필요):

| 파일 | SHA-256 |
| --- | --- |
| `docs/architecture-v1.md` | `EA1F997FF20F50A217152D0A19EF0D1C5B259FF5052E36A2FE72A29008605272` |
| `docs/validation-plan.md` | `667D51B10B13D9A7F3447870378F75CA6359C973F87DF0488D550B1DFCE0F4A4` |
| `docs/quality-system.md` | `FE0AD8FF751143A6DC9AF77A510F56186E78DA0D22B2559CC532958442E2B044` |
| `docs/reviews/audio-recovery.md` | `7BCEB1DD8386F221321402750337244F7D7B28F98F00FE6ACD31DE4EB671F216` |

## 발견 사항과 해결 조건

### D14-01 / S1 / OPEN — journal의 논리적 prefix 유효성 및 독립 oracle 부족

- 위치: 통합 설계 「저장과 복구 계약」의 blocks journal·prefix 규칙; 검증 계획 F02/F03, U01/P01; D02 §3.1·§5.3의 sequence/중복 복구 요구.
- 반례: staging PCM이 `A+B`일 때 완성 journal 레코드 `R(A, offset=0, length=L)`를 append 재시도로 두 번 남긴다. 둘 다 checksum과 파일 범위 검사는 통과한다. 단순 합계는 `2L`로 PCM 길이와 같아도, salvage가 journal을 재생하면 `A+A`가 되고 B의 시간/프레임 대응을 잃는다. descriptor가 없는 crash 경로에서도 발생 가능한 상태다.
- 공백: 현재 열거된 중단 조건인 부분 레코드·범위 이탈 및 전체 hash만으로 offset 겹침·누락·식별자 충돌을 배제할 수 없다. serializer 미확정과 별개로 허용할 논리 상태를 먼저 고정해야 한다.
- 해결 조건: data 레코드의 PCM 범위가 `[0, verified_end)`를 중복 없이 연속 덮고 frame alignment·트랙/epoch/format·sequence/fragment 유일성이 맞아야 함을 명시한다. gap/event의 무payload 예외도 구분한다. 중복/겹침/역행/다른 epoch 및 payload↔journal 각각의 torn write를 F02에 추가하고 독립 입력 oracle과 두 번 복구 결과를 대조한다. G0에서 불변식·시험 조건, G1/G2에서 golden fixture·실제 fault 증거를 확인한다.

### D14-02 / S1 / OPEN — 삭제 의도의 DB·별도 journal 이중 기록 경계 누락

- 위치: 통합 설계 「비밀과 데이터 수명」의 deletion intent/journal 및 「저장과 복구 계약」의 DB 손상 복구; 검증 계획 F05/F06/S03.
- 반례: DB에 삭제 의도를 commit하고 UI에서 숨긴 직후, 별도 deletion journal의 완료 기록 전 kill한다. 이후 DB가 손상되어 미디어 재스캔에 진입하면 원본 bundle은 온전하고 별도 journal에는 삭제 근거가 없다. 반대 순서에서는 journal만 완료되고 DB가 이전 상태인 경우가 생긴다.
- 공백: 두 저장소의 원자성이 없다는 전제는 있으나 삭제 접수/실행 허용 시점, 각각의 권위·순서, journal 누락/손상과 진짜 미삭제의 구별이 정해지지 않았다. 정상 DB의 삭제 단계 kill만으로는 이 조합을 덮지 못한다.
- 해결 조건: 최소 삭제 기록의 내구성 경계와 DB 반영 순서를 정하고 어느 한쪽의 삭제 의도만 확인돼도 자동 재채택을 차단한다. 의도 이력의 완전성을 확인할 수 없으면 자동 복구/게시를 보류한다. `DB-only/journal-only/둘 다/손상·판정불가`와 동시 삭제↔복구 commit을 barrier로 시험하여 삭제 세대 재검사·재실행 멱등성·성공 오표시 부재를 F05/F06에 추가한다. 저장 API·물리 내구성은 후속 구현 게이트로 유지한다.

### D14-03 / S0 / OPEN — 정책 검사와 실제 송신·삭제 차단 사이의 경합 경계 누락

- 위치: 통합 설계 「전송 동의와 비용」의 송신 직전 검사 및 「비밀과 데이터 수명」의 삭제/lease 취소; 검증 계획 I07/F06/S01, 품질 체계의 무동의 요청 차단 불변식.
- 반례: 유효 grant로 gateway 검사를 통과한 요청을 **아직 DNS·연결·본문 write를 하지 않은 지점**에서 멈춘다. 동의 철회 또는 세션 삭제를 확정하고 취소 통지는 지연시킨 뒤 송신 barrier를 해제한다. 검사 시점의 grant/세션 상태를 재사용하면 철회·삭제 이후 새 전송이 시작될 수 있다. 이미 OS/TLS에 넘긴 바이트의 회수 문제와는 다르다.
- 공백: 「직전 검사」와 「lease 취소」만으로 검사/철회/삭제/새 송신의 선후를 결정하지 못한다. 현재 I07은 queued 철회, F06은 늦은 게시를 주로 검증하며 검사 통과 후 송신 전 경합과 재접속/분할 본문을 명시하지 않는다.
- 해결 조건: consent epoch·session deletion generation·permit 수명 및 철회/삭제와 새 송신 허용의 공통 직렬화 경계를 명시한다. 아직 전달 전인 새 요청/재시도/청크 write를 차단하고 이미 버퍼에 넘긴 부분은 별도 위험 상태로 기록한다. 위 barrier를 양 순서로 I07/F06/S01에 추가하여 socket/DNS observer로 검증한다. 전송 단위를 통제 못 하는 SDK는 검증된 취소 한계를 고지하고 지원 범위를 제한한다.

### D14-04 / S1 / OPEN — pause/stop의 privacy cutoff를 판정할 시험 조건 부족

- 위치: D02 §6의 트랙별 cutoff·전체 트랙 정지 확인·AI tap 금지; 통합 설계 「상태와 실행 계약」; 검증 계획 P01/W03/E02.
- 반례: mic 정지 확인 후 loopback 정지 확인을 지연시키고, 이전 callback과 cutoff 이후 신규 PCM을 서로 다른 표식으로 주입한다. 또는 한 엔진이 중단 확인을 반환하지 않게 한다. gap·시간·상태 전이만 검사하면 조기 PAUSED/정지 표시, cutoff 뒤 PCM 저장/AI 전달, 반대로 cutoff 전 큐의 잘못된 폐기를 놓칠 수 있다.
- 해결 조건: 트랙별 마지막 accepted sequence/cutoff와 저장·AI tap의 독립 oracle, 모든 필수 트랙의 중단 확인을 상태 표시 조건으로 명시한다. cutoff 전 큐 drain은 허용하되 cutoff 뒤 신규 입력은 금지한다. 미확인 정지를 완료로 표시하지 않는 경로와 late callback·stop timeout·resume 새 epoch를 P01/W03/E02의 필수 수락 조건으로 추가한다. ack 지연 수치와 backend 강제 종료 방법은 구현 실험에서 결정한다.

### D14-05 / S2 / OPEN — 모델 다운로드 supply-chain 시험의 최초 적용 게이트 모호

- 위치: 검증 계획 「요구사항 추적」의 공급망 S04/R01/R02 최초 게이트 `v1.0`; S04 설치 전 검증; 통합 설계 P1 모델/로컬 AI 및 「모델 다운로드」.
- 반례: v0.3/P1에서 새 모델을 내려받아 실행하고 M02의 중단/손상 시험만 통과시킨 뒤, 출처·digest·오염 cache·라이선스 검토가 있는 S04는 v1.0까지 미룬다. 현재 최초 게이트 표로는 이 누락을 일관되게 차단하기 어렵다.
- 해결 조건: S04 중 모델·다운로드 출처/무결성/라이선스 검사는 **첫 다운로드·로드 기능 도입 전**의 G1/G2/P1 필수로 이동하고, clean installer·배포물 R01/R02의 v1.0 게이트와 분리한다. 미실행이면 해당 다운로드/로드 기능을 제외하고 N/A 근거를 남긴다. S01은 첫 오프라인 녹음부터 SDK·worker·daemon의 송신 시도와 observer 양성 대조를 포함하도록 유지한다.

## 미검증과 재확인 절차

- 수치 제안의 차이(예: 청크/queue·soak 길이)는 비교 후보로 보았으며 실측 미달이나 계약 위반으로 판정하지 않았다. 채택값·지원 장비·고정 oracle은 ADR07/G3에서 결정해야 한다.
- 물리 전원 장애·고장 디스크·flush 보장, 실제 WASAPI/backend, blocks serializer/parser, Credential API, DNS/송신 observer, 모델·라이선스 실물은 검증하지 않았다. 소스 구현·원본 VoiceLocal·실장비 분석 및 실행 재현을 수행하지 않았다.
- 이번 검토는 문서 읽기·계약 대조·명세 반례 작성과 파일의 정적 형식/링크 검사에 한정한다. 제품 실행 시험은 NOT_RUN이며 기존 D04와 공용 파일은 수정하지 않는다.
- D00이 각 ID의 수정 위치·근거와 변경 digest를 제시하면 같은 D14 검토자가 반례·해결 조건을 재대조하여 RECHECKED 여부만 기록한다. 현재 어떤 ID도 FIXED/CLOSED로 승인하지 않으며 최종 G0·push 결정은 품질 체계에 따른다.

## D14 수정 후 독립 재확인 — 2026-11-14

이 절은 위 최초 OPEN 기록·반례·당시 digest를 보존한 후속 기록이다. 수정자 D00과 원 검토자 D14를 구분하며 [종결 기록](design-signoff.md)의 D14-01~05 대응표만 믿지 않고 정본의 새 문구와 원 해결 조건을 직접 대조했다. 본 절의 RECHECKED는 **해당 ID의 G0 문서상 해결 재확인**이다. 제품 시험 PASS, D04 자기 승인, 다른 검토자의 항목 종결, 전체 G0 최종 승인 또는 push 승인을 뜻하지 않는다.

사용자가 동결한 정본의 SHA-256을 실제 파일에서 확인했으며 모두 일치했다. 아래 A2/V2/Q2는 이 절 모든 ID에 공통 적용되는 재확인 snapshot이다.

| snapshot | 파일 | 새 SHA-256 |
| --- | --- | --- |
| A2 | `docs/architecture-v1.md` | `E08450D0899A5DCF4DDE5745B6BC58B1A7B6F0B2BF0867CAC4FF405D96DA7ABD` |
| V2 | `docs/validation-plan.md` | `DF1551A71C3BF55C6A4466B68443EFDE1673A7C22A1BBB867A69DD6F527601AB` |
| Q2 | `docs/quality-system.md` | `FE0AD8FF751143A6DC9AF77A510F56186E78DA0D22B2559CC532958442E2B044` |

### D14-01 / S1 / RECHECKED — A2/V2/Q2, G0 문서상 해결

- 확인 절·시험: A2 「저장과 복구 계약」의 유효 data prefix 불변식, V2 「장애 주입과 crash matrix」 F02/F03/F04, Q2 「유닛과 속성 시험 설계」의 독립 oracle 원칙.
- 원 반례 대조: `A+B`에 `R(A)`를 두 번 append하면 두 번째 레코드는 연속 offset·유일 sequence/fragment 조건을 위반한다. gap/event는 무payload kind로 분리되므로 PCM 진행을 위장할 수 없다. F02가 바로 이 fixture의 거부, 양 파일 torn write·부분 fragment, 독립 input oracle 및 두 번 복구 비교를 명시한다. 원래의 합계/hash만 맞는 허용 경로는 문서상 차단됐다.
- 남은 제한: serializer/parser·append 재시도·flush 조합과 실제 fixture 결과는 NOT_RUN이다. G1/G2에서 독립 입력과 저장/복구 결과를 검증해야 하며 구현 완료로 판정하지 않는다.

### D14-02 / S1 / RECHECKED — A2/V2/Q2, G0 문서상 해결

- 확인 절·시험: A2 「비밀과 데이터 수명」의 삭제 접수 순서·양 저장소 불일치 및 「저장과 복구 계약」의 읽기 전용 inventory, V2 F05/F06/S03.
- 원 반례 대조: 새 송신 동결 → deletion journal 검증·영속 게시 → DB DELETE_REQUESTED/삭제 세대·fence 반영으로 순서가 정해졌다. 양쪽 확인 전 접수 완료·파괴적 삭제는 금지된다. journal-only와 DB-only는 어느 쪽이든 재채택 금지이고 상호 복구하며, 이력 완전성 판정불가는 자동 복구/게시를 보류한다. F06은 두 단독 상태·둘 다·손상, 삭제↔복구 barrier와 삭제 세대 재검사·멱등성·성공 오표시 부재를 요구한다.
- 남은 제한: 실제 journal 내구성·동시 복구와 삭제 commit·DB 손상 주입은 NOT_RUN이다. G1/G2 실행 검증과 별도의 물리 내구성 증거가 필요하며 오래된 외부 사본의 완전 회수를 보장하지 않는다.

### D14-03 / S0 / RECHECKED — A2/V2/Q2, G0 문서상 해결

- 확인 절·시험: A2 「전송 동의와 비용」의 정책 coordinator/SendPermit 및 「비밀과 데이터 수명」의 송신 동결, V2 I07/F06/S01, Q2의 동의 없는 DNS·연결·SDK 호출 차단 원칙.
- 원 반례 대조: grant epoch·삭제 세대·input version·예산을 묶은 permit을 실제 transport 인도와 같은 직렬화 경계에서 재검사한다. 검사 통과 후 아직 DNS/연결/본문 전달 전인 요청, 재접속·retry·후속 write도 다시 통과해야 한다. 따라서 철회/삭제가 먼저 commit된 barrier 순서에서 과거 permit으로 새 단위를 시작할 수 없다. I07은 양 commit 순서·첫/후속 write와 미전달 신규 단위 0을, S01은 observer 양성 대조와 handoff 이전/이후 구분을 요구한다.
- 남은 제한: 실제 SDK·transport handoff 경계·관측 누락·원격 처리/과금 취소는 NOT_RUN이다. 이미 OS/TLS/SDK buffer에 넘긴 바이트는 회수 보장이 없으며, 송신 단위 통제가 불가능한 SDK의 지원 제한을 G1/G2 어댑터 검증에서 확인해야 한다.

### D14-04 / S1 / RECHECKED — A2/V2/Q2, G0 문서상 해결

- 확인 절·시험: A2 「상태와 실행 계약」의 pending pause·트랙별 gate/cutoff·writer ack, V2 P01/F01/W03/E02 및 Q2의 독립 기대값·barrier 원칙.
- 원 반례 대조: 모든 필수 capture gate와 이전 epoch drain/seal이 확인돼야 PAUSED이며 그 전 resume은 차단된다. 마지막 accepted sequence/fragment와 별도 제어 경로의 유실 누계를 사용하고 late callback도 gate를 검사한다. cutoff 전 큐는 보존하고 뒤 신규 입력/AI tap은 금지한다. W03은 한 트랙 ack 지연/누락·late callback·stop timeout을, E02는 미확인 정지를 완료로 읽지 않는 동작을 명시해 조기 성공 표시와 전후 데이터 혼동을 수락하지 않는다.
- 남은 제한: 표식 PCM·저장·AI tap의 독립 관측 oracle 구현, backend ack·timeout·강제 종료, Narrator/실장비 결과는 NOT_RUN이다. G1/G2의 제어 가능한 부정 시험과 G3의 실제 장치 검증이 필요하다.

### D14-05 / S2 / RECHECKED — A2/V2/Q2, G0 문서상 해결

- 확인 절·시험: V2 「요구사항 추적」의 모델/다운로드와 배포 공급망 분리, 「보안과 릴리스」 S01/S04/REL01/REL02 및 M02, A2의 모델 다운로드·개발 단계.
- 원 반례 대조: S04가 첫 다운로드·로드 기능 도입 전 G1/G2/P1 필수이고 출처·고정 digest·라이선스·오염 cache를 검증 전 설치/로드 금지 조건으로 명시했다. 미실행이면 기능 제외와 N/A 근거가 필요하므로 P1에서 실행한 뒤 v1.0까지 검증을 미루는 해석은 허용되지 않는다. 배포물 검토는 REL01/REL02로 별도 유지하고 S01은 startup부터 worker/daemon 및 observer 양성 대조를 요구한다.
- 남은 제한: 실제 모델·바이너리·license 원문과 hash/서명 검증은 NOT_RUN이다. G4의 실제 배포물 재검토가 최초 기능의 S04 검증을 연기하는 근거가 될 수 없다.

재확인 집계: **5/5 RECHECKED, D14 범위의 문서상 OPEN 0건(S0/S1 포함)**. 원래 위험의 실행 검증은 모두 NOT_RUN이며 G1~G4 게이트가 닫힌 것은 아니다. 사용자 제공 「문서 18개·링크 92개·시나리오 40개·이슈 0」는 전체 정적 검사 보고로 구분하고 제품 시험 증거나 본 검토자가 전부 재실행한 결과로 인용하지 않는다. 이번 재확인은 정본 문구/시험 정의와 반례의 대조이며 공용 파일·Git·다른 검토 기록은 변경하지 않는다. 정본 digest가 달라지면 영향받는 ID는 새 snapshot에서 다시 확인해야 한다.
