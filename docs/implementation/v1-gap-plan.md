# 설계 v1.0 대비 구현 gap 통합 계획 (G01-C)

2026-11-22, 작성 C00. 기준 commit `3f4ee9f2d56b5a7a97e8dccb49399b5637babd4e`. 이 문서는 G01 분석 결과를 하나로 합쳐 등급을 정하고, 설계와 구현이 어긋난 항목을 결정하고, 후속 push 단위의 순서와 배정을 정한다. **구현 완료나 실장비 검증 완료를 선언하는 문서가 아니다.**

## 입력

| 문서 | 작성 / 검토 | sha256(LF) | 요약 |
| --- | --- | --- | --- |
| [G01-A 녹음·저장 gap](../reviews/g01-gap-recording.md) | w5:p7 Claude | `e7f4655a…bd6f` | 설계 요구 107행: DONE_VERIFIED 61, DONE_UNTESTED 6, PARTIAL 30, MISSING 6, EXTERNAL_GATE 3, DEFERRED 1. 시나리오 22행 별도 |
| [G01-A 교차 검토](../reviews/g01-gap-recording-review.md) | w5:p8 Codex | `cbe2b493…fbac` | DONE_VERIFIED 71행 전수 대조. 이견 5건(S1 1, S2 2, S3 2). 선택 version 반례 2건 실행 재현 |
| [G01-B AI·보안·UI gap](../reviews/g01-gap-ai-security-ui.md) | w5:p8 Codex | `1e3cd7c1…3e0b` | 83행: DONE_VERIFIED 44, PARTIAL 26, MISSING 2, EXTERNAL_GATE 10, DEFERRED 1 |
| [G01-B 교차 검토](../reviews/g01-gap-ai-security-ui-review.md) | w5:p7 Claude | `ff7ebe94…ac26` | 이견 17건(등급 10, 판정·근거 3, 누락 4)과 경계 6건. 결함 존재에는 이견 없음 |

두 작성자는 서로의 보고서를 보지 않고 썼다. 교차 검토는 상대 보고서만 대상으로 했다.

## 등급 결정

교차 검토의 등급 이견은 모두 "결함이 있느냐"가 아니라 "몇 등급이냐"였다. 결함은 모두 코드로 재현된다. 등급은 [품질 체계](../quality-system.md)의 정의로 정한다.

| 대상 | 원 등급 | 결정 | 근거 |
| --- | --- | --- | --- |
| G01B-040 동의 범위 | S0 | **S1, 최우선** | S0는 무동의 전송·비밀 유출·원본 대량 손실이다. 현재 모든 송신은 같은 실행 세대 안의 정확한 provider·endpoint·데이터 종류 grant를 요구하고, TTL·철회도 검사한다. 그 범위 밖으로는 보내지 않으므로 무동의 전송으로 보지 않는다. 다만 UI가 세션 범위·만료·정책 version을 고지하지 않았다는 사실이 사용자가 전체 세션에 동의했다는 증거는 아니다(G01CC-B01). 설계가 요구한 세션·기능 범위와 정책 version이 grant에 없어, 한 번의 동의가 TTL 안의 다른 세션 요청에 재사용된다. 권한 모델의 계약 위반이므로 S1로 두고 가장 먼저 고친다 |
| G01B-024 + G1A-89 선택 version | S1 / S3 | **S1 하나로 통합** | 사용자가 다시 고른 요약을 늦은 작업이 덮어쓰는 것을 공개 API로 두 번 독립 재현했다(G01AR-01, G01BR-19의 P2). 잘못된 게시다. 비교할 설정 키가 DB에 없으므로(G01CR-02) G-P03에서 영속화한다. latest pointer 분리·설정 키 표시·OUTDATED 표시는 S3로 남긴다 |
| G01B-067 + G1A-72 재시작 뒤 삭제 대기 | S1 / S2 | **S1 하나로 통합** | 같은 원인이다. storage에 DELETE_PENDING 목록 API가 없고 UI 목록은 메모리에만 있다. 사용자가 삭제를 요청한 원본이 재시작 뒤 남고 재시도할 길이 없다. G01-A 작성자도 S1로 정정했다(G01BR-18) |
| G1A-11·62·24 미확정 세션 | S1 / S2 / S3 | **한 단위로 묶어 S1** | 비정상 종료로 INTERRUPTED·PAUSED·CREATED가 된 세션을 사용자 경로(CLI·UI)로 확정·재개할 수 없다. 원본은 남지만 내보내기·전사가 막힌다. 교차 검토도 동의했다. G01B-066(복구 결과 표시)의 S1은 이 행으로 일원화하고 표시는 S2로 둔다 |
| G01B-046 비용 상한 | S1 | **S1 유지** | 사용자 cap을 검증된 요청 상한 없이 그대로 예약한다. strict 예산 요구가 실패한다 |
| G01B-012, 021·022, 030, 031, 032, 047, 066, 068, 069 | S1 | **S2로 조정** | G01BR-02~10의 근거를 받아들인다. 원본·게시·전송에 영향이 없는 우회 가능한 품질·표시·정책 문제이거나, 근본 결함이 다른 S1 행에서 다뤄진다 |
| G1A-35 사전 할당 버퍼 | DONE_VERIFIED | **해당 하위 요구만 PARTIAL S2** | 설계는 capture critical path의 사전 할당 버퍼 복사를 요구한다. 현재는 패킷마다 bytes를 새로 만든다. 성능 실패를 관측한 것은 아니다(G01AR-04) |
| G1A-73, G1A-93 일부 | DONE_UNTESTED | **해당 하위 요구 DONE_VERIFIED** | 기존 시험이 직접 확인한다(G01AR-02·03). 재시작 뒤 진입점, 서로 다른 폴더로의 오디오 반복 내보내기는 그대로 남는다 |
| 복원·import의 안전한 재개, 보존 정책 엔진 | 행 없음 | **MISSING S2 행 추가** | 두 보고서가 서로의 범위로 넘겨 양쪽에 판정 행이 없었다(G01AR-05, G01BR-22). 백업 생성은 이미 G1A-69(MISSING S3)이므로 새 행을 만들지 않고 S2로 올려 합친다(G01CR-04). 소유권은 아래 단위에서 정한다 |
| G01BR-11~17 | — | **받아들임(S3)** | 정적 describe는 PARTIAL로, 표시·경로 검증·비밀 읽기 시점 등 누락 행을 추가한다 |

## 설계·구현 불일치 결정

G01-A가 요청한 C00 결정이다. 설계 문서 개정은 아래 GD 단위에서 한다.

| 행 | 현재 구현 | 결정 |
| --- | --- | --- |
| G1A-15 BLOCKED 사유 | 동의·인증·capability·자원·예산 오류가 FAILED로 끝남. 기존 시험이 이 편차를 고정 | **설계를 따른다.** 오류 코드→BLOCKED(reason) 결정표를 구현하고, 편차를 고정한 시험의 기대값을 바꾼다(G-P07) |
| G1A-22 시작 실패 | RECORDING을 먼저 영속하고 장치 시작 실패 시 PAUSED로 둠 | **현재 동작을 설계에 반영한다.** 일부 트랙이 이미 수락됐을 수 있어 원본 보존을 우선한다. 대신 첫 블록이 수락되기 전에는 UI가 REC를 표시하지 않게 한다. 지금 UI는 장치 ready 직후 REC를 표시하므로(G01CR-01) 시험만이 아니라 구현이 필요하다(G-P07에 포함) |
| G1A-26 lease 만료 | 단일 재시작 coordinator 증명 | **현재 동작을 설계에 반영한다**(product-contracts B12와 일치). 다중 프로세스 worker를 도입할 때 다시 본다 |
| G1A-53 전사·요약 저장 위치 | SQLite `content_revisions` | **현재 동작을 설계에 반영한다**(product-contracts B11과 일치). 배치도를 고친다 |
| G1A-17 CANCEL_UNCONFIRMED | BLOCKED(REMOTE_UNKNOWN)+cancel_requested | **의미가 같으므로 현재 표현을 유지**하고 설계에 대응 관계를 적는다 |
| G1A-46 에코 완화 | 없음 | **v1.0 이후(DEFERRED).** 선택 파생 처리이며 v1.0 단계표에 없다 |
| G01B-032 수동 로컬 모델 | 세 파일 해시를 config key로만 사용 | **수동 디렉터리 허용(B13)을 유지한다.** 실행 전 digest를 고정·표시하고 "사용자 지정 모델"로 구분한다. 차단하지 않는다(S2). 다만 자체 해시 표시는 신뢰된 digest·출처·license와 대조하는 로드 검증(validation S04)과 다르다. 수동 모델의 신뢰 책임, 명시 확인, 검증 상태 표시, S04의 적용 또는 예외를 GD-P01과 G-P13에서 정한다(G01CC-B02) |

## 후속 push 단위

각 단위는 [push 단위 규칙](../collaboration/push-units.md)을 따른다. 순서는 경우의 수 문서, 구현, 상대 작업자의 독립 검토, RECHECK, C00 정확한 tree 검증, commit·push다. 작성자와 검토자는 서로 다른 세션이다. 공용 API·schema를 바꾸는 단위는 작성자가 계약안을 먼저 C00에 보고한다.

### 1차(S1)

| push | 대상 | 작성 / 검토 | 예상 파일 | 핵심 수락 기준 |
| --- | --- | --- | --- | --- |
| G-P02 | 동의 범위 F-SEC01 (G01B-040, 069 일부) | w5:p8 Codex / w5:p7 Claude | security/consent.py·gateway, ui/privacy.py, 관련 시험 | grant에 세션(또는 명시적 전체) 범위·기능·정책 version을 넣는다. 범위가 다른 요청은 송신 전에 차단한다. 기존 철회·세대 무효화 회귀를 유지한다. 실행 세대·철회 양순서와 범위 조합의 경우의 수를 둔다 |
| G-P03 | 선택 version CAS F-SUM02 (G01B-024, G1A-89 ABA) | w5:p7 Claude / w5:p8 Codex | content/store.py, app/ai.py, 관련 시험 | 게시 transaction이 전사·요약 선택 version과 설정 키를 기대값과 비교한다. 다르면 후보로 보존한다. G01AR-01의 반례 2행(선택 이동 후 같은 ID로 복귀)이 통과해야 한다 |
| G-P04 | 미확정 세션 확정 GF-01 (G1A-11·62·24), 복구 결과 표시 F-RECUI01 | w5:p7 Claude / w5:p8 Codex | storage/library.py, app/recording.py, app/recovery.py(신규), cli.py, ui/main.py | 상태별 허용·거부 표. 자식 프로세스 kill→recover→finalize→export에서 원본 SHA 불변, 재복구 멱등. 녹음 중인 세션의 복구·확정은 SESSION_LIVE로 거부(계약 단계 반례 G04-CE1). 복구 범위·누락·후보를 읽을 수 있게 표시. **재개는 제외**: 다른 실행·재부팅 뒤 이어 녹음하면 시계 기준이 달라 시각 정렬이 틀어지므로 GF-06과 함께 다룬다(C00 결정) |
| G-P05 | 재시작 뒤 삭제 대기 복원 GF-13 + F-LIFE02 (G01B-067, G1A-72) | w5:p8 Codex / w5:p7 Claude | storage/library.py(`pending_deletions`), ui/main.py | 재시작 뒤 목록과 재시도. 제거 실패 주입 뒤 멱등 완료. tombstone 유지 |
| G-P06 | 비용 상한 F-COST01 (G01B-046) | w5:p8 Codex / w5:p7 Claude | ui/privacy.py, security 비용 ledger, 관련 시험 | 모델·요청별 검증된 상한이 없거나 가격이 미상이면 strict 모드에서 차단한다. 보수적 UNKNOWN 유지를 보존한다 |

G-P04와 G-P05는 둘 다 `storage/library.py`와 `ui/main.py`를 바꾼다. 동시에 진행하지 않고 G-P04 push 뒤 G-P05를 시작한다. 1차 동안 C00은 아래 GD-P01과 시험 보강을 맡는다.

### 2차(S2)

| push | 대상 | 비고 |
| --- | --- | --- |
| G-P07 | BLOCKED 사유 결정표 GF-03 (G1A-15), 시작 실패 REC 표시(G1A-22), 사유별 다음 행동 UI F-UX02 | GF-03 뒤 F-UX02 |
| G-P08 | 트랙 건강·gap 범위 GF-04, 비정상 종료 유실 누계 GF-05 | 같은 schema 협의 |
| G-P09 | schema migration·backup GF-11, 백업 복원·import의 안전한 재개(G01AR-05) | GF-02·GF-06·GF-15의 선행 |
| G-P10 | 4 GiB 초과 내보내기 분할 GF-09 | 대용량 실파일 없이 경계 시험 |
| G-P11 | GPU_ONLY 정책의 요약 적용 F-RES02, 모델별 메모리 예산 F-RES01 | |
| G-P12 | 요약 basis 보존·표시 F-SUM01, 키보드 근거 탐색 F-A11Y01 | |
| G-P13 | 수동 로컬 모델 digest 고정·표시 F-MOD02 | 위 결정 반영 |
| G-P14 | 보존 정책 엔진(G01BR-22), 진단 연결 GF-12·F-OBS | 소유권은 단위 시작 때 확정 |
| G-P15 | 청크 seal의 root mutex 보유 축소(S2, G-P04 검증에서 발견) | 녹음 writer가 `storage/chunks.py`의 seal에서 root mutex를 잡은 채 fsync 3회·scan_prefix·rename·verify_bundle(재해시)을 한다. 부하 시 1초 이상 보유해 큐가 넘치며 블록 거부가 날 수 있다(G-P04 정확한 tree 검증 중 동시 부하에서 관측, 단독 실행은 유실 0). fsync·검증은 mutex 밖, rename과 catalog 기록만 mutex 안으로 옮기는 방향. 삭제·복구·확정 claim과의 불변식을 함께 검증 |
| G-P16 | 장치 실행 정책 저장(G-P11 재대조에서 발견) | 장치 정책(AUTO·CPU_ONLY·GPU_ONLY)이 저장되지 않아 매 실행 CPU_ONLY로 시작한다. G-P11a 뒤 로컬 Ollama 요약은 CPU_ONLY·GPU_ONLY에서 차단되므로 앱을 켤 때마다 기본으로 막힌다. 비밀이 아닌 일반 설정으로 정책을 저장·복원하고, 손상·미래 version은 CPU_ONLY로 fail safe, 정책 변경은 실행 snapshot에만 반영(config_key 불변). G-P11a 뒤 |
| G-P17 | 녹음 append의 fsync 내구성 단위 재검토(G-P15 CI에서 발견, S2) | 녹음 소비자는 블록(10ms)마다 root mutex 안에서 fsync 2회를 한다. CI 러너 디스크에서 1트랙 append 보유 p99 0.79초·최장 1.04초, 6초 동안 46블록 거부(run 45234308753). 느린 HDD·네트워크·백신 검사 볼륨에서 녹음 유실 위험. 대안: fsync를 mutex 밖으로(삭제 의도 뒤 쓰기 0 유지), N블록·시간 묶음 fsync와 전원 장애 손실 창 명시, 파일 저장 완료와 전원 장애 내구성 구분(제품 불변식). 계약에서 측정·선택 |
| 이후 | GF-02 고아 채택, GF-06 clock domain과 미확정 세션 재개(G-P04에서 분리), GF-07 정렬 연결, GF-10 inventory, GF-14 동기화 폴더, 사전 할당 버퍼, UI의 요약 후보 선택(G-P03 검토에서 확인: 지금은 API로만 고를 수 있음), 실제 유료 가격 catalog 항목(G-P06 뒤, 공식 출처 고정. G06R-07: billing profile version·최소 청구량·증분, 텍스트 상한 모델, Gemini 음성 과금 표현을 첫 항목 전 게이트로. G06R-08: 시계 되돌림·재설정 뒤 이전 기준으로 만료된 가격이 다시 유효해지지 않게 하고 재설정 확인 창에 안내), 고아 reader 종료 증명 자동화와 별도 library.sqlite의 DB-only 삭제 기록을 ConsentStore가 직접 보지 못하는 경계(G-P05 계약에서 분리), S3 묶음과 G15c는 [S3 묶음 계획](s3-bundle-plan.md)의 GS-P01~GS-P10으로 나눠 진행(GF-17은 S2, G01BR-11은 S2 기능 단위) | 선행 단위 뒤 |

### C00 단위

| push | 대상 |
| --- | --- |
| GD-P01 | 위 결정을 architecture·product-contracts에 반영(GF-19). G1A-22·26·53·17·46 |
| GT-P01 | `tests/unit/test_diarization.py::test_owned_hung_child_ack_before_return[timeout]`의 시간 제한에서 자식 시작 시간을 분리. L-P08 1판 정확한 tree에서 부하 중 1회 실패했고 단독 재실행 3회는 통과했다 |

## 통합안 확인

두 작성자가 이 통합안을 확인했다. 각자의 교차 검토 문서 끝 'G01-C 통합안 확인' 절에 있다.

- **w5:p7 Claude:** 이견 5건(S2 2, S3 3). G1A-22 REC 표시에 구현이 필요하다는 점, 설정 키가 DB에 없다는 점, 원 등급 표기, 백업 행 중복, 두 번째 독립 재현을 지적했다. 모두 위에 반영했다.
- **w5:p8 Codex:** 이견 2건(S2 2). 동의 범위 등급 근거의 표현, 수동 모델과 S04의 관계를 지적했다. 모두 위에 반영했다.
- 두 확인 모두 S0·S1 이견은 없다.

## 외부 게이트(이 계획으로 닫지 않음)

실장비 캡처 W01~W04, 전원 차단, 실제 모델·weights·음성 품질, 실제 Ollama·제공업체·계정·TLS·vault, 다른 GPU, clean VM, 서명, 법률 확인, VoiceLocal 소스는 EXTERNAL_GATE다. 두 보고서의 EXTERNAL_GATE 13행은 개발 gap과 합산하지 않는다.


## G09a D12: current-F2 wire 타입 기반 증분

기준 공개0c42의 복구 CI 세 작업 성공은 인수했다. 다음 정확10파일 단위는 순수 관리6종 codec과 canonical DTO 기반의 제품 결속이며 현재 작성 중이다. 원 S1 20행을 보존하고 local CAW26/CAN14 대상40을 계획하되 원70의 CAN08/13/14/15·CAM01~06 열 행과 실제 유지보수·권위·legacy/LOP는 남긴다. private 후보269/독립82·legacy296/29는 새 제품 PASS가 아니다. 새 제품 tree의 선택·독립검토·정확 full/coverage7/wheel·공개/원격 결과는 후속 인수하며 이 기록은 G09a 전체 또는 설계 v1 구현/실장비 완료를 뜻하지 않는다. 세부 범위와 경계는 [관리 계약의 D12 절](../testing/g09-migration-backup-cases.md) 및 [작업 배정표](../collaboration/assignments.md)를 따른다.

### D12 통합 준비 상태 갱신(전체 검증 전 스냅샷)

앞선 ‘현재 작성 중’은 최초 D12 초안의 상태다. 이후 후보5파일의 작성·322건/6목표/정적3종과 비작성자의 제품결속322건·독립 손9건·선택감사·타입 단언 민감도 검토를 인수했다. 기존 S1 의미20과 원70의 local대상40/보류10은 유지한다. 정확10 tree의 full core·coverage7·offline wheel·새 SHA 원격 CI는 이 갱신 작성 시점에 아직 실행하지 않았다. 이 문단은 전체 검증 전 준비 스냅샷이며 후속 전체 결론·공개 SHA/원격 run은 실제 Git/CI와 오케스트레이터 검증 기록으로 따로 결속한다. [제품 결속 독립 검토](../reviews/g09a-type-integration-review.md)의 한정 판정을 전체 G09a·실제 권위·Windows 실장비 완료로 확대하지 않는다.

## G09a D13 준비와 앞선 D12 실행 결과

앞선 D12의 검증 전 스냅샷은 그 작성 시점의 사실로 보존한다. 이후 정확 tree `d0b7dc0eb43f1fff91ed156f711213d1d069c3b5`에서 로컬30,467건이 오류/skip/xfail0으로 통과했고, coverage7·offline wheel Python87 raw 및 실제 부모/spawn 출처·독립 공개 증거 감사를 인수했다. 같은 tree를 commit `60f4dc6a1d26c6f074ebbbbe1d83d3cbdb63b6f3`으로 normal push해 실제 원격 일치를 확인했다. 이 문단 준비 시 CI45944181518의 optional-runtime은 성공, core3.11/3.13은 진행 중이었다. 최종 원격 결론은 같은 SHA의 실제 run과 X00 후속 인수 기록으로 별도 확인한다.

다음 D13은 legacy OUTPUT local wire 조합 하나만 추가하는 증분이다. caller의 profile 문자열·physical0/1·ABSENT·정확 jobs.core/1/FP·NULL3/빈 sidecar·hex64 digest 선언을 검사하며 실제 whole-file/DB/등록/복구 권위는 검사하지 않는다. BINDINGS/PLAN/S1 registry30·COMPLETE·공개 타입/서명은 유지한다. 기존322+손27=계획349와 예상 전체30494는 새 실행이 필요하고 formal70/4105/245·보류10은 변하지 않는다. 이 문단은 구현 전 준비 상태이며 새 제품 PASS·선행/신규 CI 성공·전체 G09a/v1/실장비 완료를 뜻하지 않는다. [관리 계약 D13 절](../testing/g09-migration-backup-cases.md)과 [작업 배정표](../collaboration/assignments.md)의 정확 범위·독립 검토·통합 게이트를 따른다.

### D13 통합 준비 상태 갱신(전체 검증 전 스냅샷)

앞선 D13의 ‘구현 전 준비’와 D12 CI 진행 중 문구는 그 문단 작성 시점의 사실이다. 이후 D12 공개60f4의 실제 원격 CI45944181518 세 작업 성공·ref/tree/message/trailer0을 재확인해 선행 게이트를 닫았다. D13 후보4의 작성349건/7.431초·단일목표2·정적3종과 비작성자의 새 제품결속 직접349건·독립 손27건·기존 control2건·실제목표2/control3·17.103초·OPEN0을 인수했다. 원27/기존322·formal70/보류10/4105/245는 보존했다. [제품 결속 독립 검토](../reviews/g09a-legacy-output-integration-review.md)는 local OUTPUT 조합과 실제 pytest/fixture 결속의 한정 판정이다. 이 스냅샷의 최종 정확8 tree·전체수집 예상30494/core/coverage7/offline wheel·공개/새SHA CI는 아직 실행하지 않았다. 후속 결과는 실제 tree/commit/ref/원격 run과 X00 인수 증거로 별도 결속하며 실제 whole-file/LOP/권위·전체 G09a/v1·실장비 완료로 확대하지 않는다.
