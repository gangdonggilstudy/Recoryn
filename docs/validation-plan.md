# Recoryn 검증 계획과 수락 기준

상태: 검증 시나리오 명세. 여기에 나오는 수치와 환경은 초기 제안이며 측정 결과가 아니다. [품질 체계](quality-system.md)는 역할과 승인 절차를, 이 문서는 구체 시나리오와 통과 조건을 정의한다. 설계 작성 당시 모든 실행 시험은 `NOT_RUN`이었으며 현재 구현의 실제 범위는 [제품 진행 기록](implementation/product-results.md)과 연결된 실행 증거를 따른다. 전체 시나리오 통과를 선언하는 문서가 아니다.

## 요구사항 추적

| 요구사항 또는 위험 | 계약 | 필수 시험 ID | 관점 / 최초 게이트 |
| --- | --- | --- | --- |
| R01 AI와 녹음 독립 | 별도 worker·queue, AI 실패는 job 상태만 변경 | I01, I02, F01 | 오디오·ML·QA / P0 |
| R02 기본 전송 차단 | provider/endpoint/data별 gateway 검사와 다운로드 분리 | U06, C02, I07, S01 | 보안·ML / P0 정책 기반, P1·P2 어댑터 |
| R03 분리 원본과 파생 | 불변 청크, source mapping, revision | U01, U02, I03, W01 | 오디오·아키텍트 / P0 |
| R04 취소·재개·부분 보존 | attempt, lease, staging/게시, 복구 | U03, P01, I04, F02~F06 | 아키텍트·QA / P0 |
| R05 비밀 보호 | vault reference와 가림 | U07, S02, W05 | 보안 / P1 |
| R06 선택 어댑터 | capability와 오류 계약, 미설치 경로 | C01, C02, I02 | ML·아키텍트 / P0~P2 |
| 시간·드리프트·유실 | epoch, 3종 시계, gap과 frame accounting | U02, P02, F01, W01~W04 | 오디오·QA / P0 |
| 전사·요약 근거와 편집 | revision pointer, claim refs | U04, U05, I05, M01, E01 | ML·UX / P1~P2 |
| 비용·GPU·자원 | 예약과 정산, 사용자 허용 fallback | U08, C02, I06, M02 | ML·보안 / P1~P2 |
| 삭제·보존·복구 충돌 | tombstone 우선, lease와 게시 차단 | P01, F06, S03 | 보안·아키텍트 / P0 저장 기반, P1 UI |
| 접근성·복구 안내 | 상태 표시와 조작, 근거 seek | E01, E02 | UX·QA / P1 |
| 모델·다운로드 공급망 | 출처, 고정 digest, 검증과 라이선스 | S04, M02 | 보안·ML / 첫 다운로드·로드 도입 전 G1/G2, P1 |
| 배포 공급망 | 실제 배포물 SBOM/license와 clean build | REL01, REL02 | 보안·릴리스 / v1.0 |

유닛·통합·하드웨어가 다른 주장을 검증한다. 예를 들어 U02의 시간 계산 통과는 실제 장치의 timestamp 정밀도를 보장하지 않는다. 범위 표기의 `F02~F06`은 해당 범위의 모든 ID를 뜻한다.

## 유닛과 속성 시험

| ID | 입력과 경계 | 기대 결과 |
| --- | --- | --- |
| U01 | s16/float PCM, mono/stereo, 빈 입력·잘못된 길이·끝 frame | 포맷별 byte/frame 일치, 잘못된 frame 거부, 정상 무음 flag 처리, 원본 불변 |
| U02 | 44.1/48 kHz, QPC 변환, reset/큰 counter, 유효 1.000초→오류 arrival 1.060초→유효 sample 1.020초 | epoch·단위 혼합 없음, 오류 표본은 적합 제외, arrival는 별도, 거짓 정밀도·음수 범위 없음, 마지막 오류 뒤 stop도 unknown 유지 |
| U03 | 합법/불법 전이, version 경쟁, retry/lease, GPU→허용 CPU·batch와 model/template 변경 | 불법 전이 거부, terminal attempt 불변. 장치·batch만 조정하고 의미/호환 키 같으면 새 Attempt; 모델/전사/템플릿·의미 변경은 새 Job·checkpoint 재사용 금지 |
| U04 | draft/corrected/edited, 늦은 결과, 음성에 없는 사용자 삽입·교체·분할/병합 | 편집·provenance 유지, 원자 게시, AU06의 user_assertion/unresolved 표시와 발화 검증 배지 금지. 구조 참조 유효성과 의미 지지를 별개 판정 |
| U05 | SRT 0·hour 경계·음수·정렬·유니코드, 동일 revision export | 형식과 시간 정밀도 정책 일치, 동일 콘텐츠 재생성, traversal 경로 거부 |
| U06 | scope 변경, endpoint·redirect·proxy·remote Ollama, 철회 | 동의 없는 종류·수신자·범위 차단, 전송 직전 재평가, 로컬 실행 위치 미확인은 차단 |
| U07 | secret canary가 포함된 예외·헤더·설정·지원 번들 | 실제 비밀 제거, 허용 metadata만 출력, vault 실패 시 일반 설정에 저장하지 않음 |
| U08 | 동시 예약, 가격 미상, UNKNOWN→확정·중복/역순 usage, VRAM 부족 | limit 100에서 R UNKNOWN 60→최종 40 후 confirmed=40/unknown=0/available=60, 재수신·재시작에도 동일. 미산정 요청·무동의 CPU/외부 전환 차단 |
| P01 | start/pause/즉시 resume/stop/crash/delete, 포화 중 마지막 drop, finalized 뒤 orphan | resume은 pause ack+drain/seal 전 차단, 별도 제어 cutoff/누계 보존, E1/E2 혼입 없음. R1 봉인 뒤 C2는 후보 또는 명시적 새 R2, 기존 R1/hash/편집 불변 |
| P02 | 무작위 시계 offset/drift/gap 및 sample rate와 resample | 시간 단조성, 허용 오차, gap 유지, 파생→소스 참조 정합성 |

## 계약과 통합 시험

| ID | 시나리오 | 통과 조건 |
| --- | --- | --- |
| C01 | provider 지원/미지원, 부분 1/10 성공, timeout/취소, dependency 미설치 | 동일 DTO, partial+미처리 9/10 표시·부모 전체 Job 성공 금지. 정상 무음은 coverage complete의 빈 전사, 요약 미선택은 audio 완료 허용 |
| C02 | 가격·컨텍스트·처리 위치 미상, retryable=true/outcome_known=false, OOM/동의/예산 오류 | unknown은 Attempt UNKNOWN·Job BLOCKED(REMOTE_UNKNOWN), OOM→BLOCKED(RESOURCE), 동의→BLOCKED(CONSENT), 예산→BLOCKED(BUDGET). WAITING_USER는 UI 투영. SDK 자동 retry/download 우회 차단 |
| I01 | 정상 synthetic capture 중 STT hang/예외/worker kill | 원본 지속 저장, writer 진행 유지, AI job만 실패·재시도 가능, UI 상태 분리 |
| I02 | 모델 미설치·손상·GPU OOM 및 summary 실패 | 녹음 시작/정지 가능, 암묵 download/fallback 없음, 모델 오류와 capture health 분리 |
| I03 | 청크 게시 후 manifest 지연, FINALIZED R1=[C1]에 유효 orphan C2, 반복 복구 | 중복 없음, R1/hash/전사 불변. C2 자동 편입 금지, 명시 채택한 R2는 R1 전사를 전체 준비로 표시하지 않음 |
| I04 | lease 교체, pointer 직전 취소 barrier, 성공/취소 양 commit 순서, 취소 직후 crash | pointer·Job/Attempt 완료·outbox를 같은 transaction으로 확인. 취소 우선이면 active 불변·새 dispatch 0; 게시 우선이면 ALREADY_SUCCEEDED. 취소 의도 재시작 후 보존 |
| I05 | 편집/full-pass 경쟁, T1/S1 뒤 T2/S2 선택 후 S1 완료, 같은 T2의 옛 template 늦은 완료 | 전사/요약 선택 CAS, S2 유지·S1 후보+OUTDATED, 원 입력 seek 유지. 게시 성공과 active 선택을 구분 |
| I06 | AI·녹음 경쟁, 예약→dispatch→정산 각 kill, limit 10의 UNKNOWN 8 뒤 세션 A 삭제·새 B 예약 8 | recorder 우선, 삭제 뒤 exposure 8 유지·본문/비밀 제거, 새 8 요청 차단. ledger 손상·rollback은 엄격 모드 차단. 중복 정산은 U08 oracle |
| I07 | queued 철회, 검사 후 DNS/첫·후속 write 전 barrier에서 철회/삭제, 양 commit 순서, endpoint 변경 | 정책 commit 이후 미전달 신규 단위 0, 이전 OS/TLS buffer와 구분 계수. 실패한 정책 기록을 성공 표시하지 않음. 접수 불명 자동 retry 없음 |

## 장애 주입과 crash matrix

fault injector는 실제 사용자 저장소가 아닌 임시 fixture에서만 실행한다. callback 예외로 끝내지 않고 독립 writer 프로세스의 강제 종료와 재실행을 포함한다. 데이터 flush와 실제 전원 차단 시험은 분리한다.

| ID | 주입 지점 | 복구 후 기대 결과 |
| --- | --- | --- |
| F01 | 저장/AI queue 포화, consumer 정지, 포화→pause→즉시 resume→stop, 후속 성공 블록 없음 | known drop 최종 누계가 별도 제어 경로로 영속화, ack 전 resume 금지·E1/E2 혼입 0. AI tap 손실 별도, 미영속 crash 누계만 unknown |
| F02 | PCM/journal/descriptor 각각 append·flush·close 중 kill, 잘린 JSONL, 잘못된 hash, 중복·겹침·역행·다른 epoch·일부 fragment | payload A+B에 R(A)를 두 번 쓴 fixture 거부, offset/frame/identity 검증. PCM↔journal 잔존 조합의 연속 유효 prefix만 별도 salvage. 독립 input oracle과 2회 복구 비교·staging 덮어쓰기 금지 |
| F03 | bundle/SQLite/manifest 전후 kill, 마지막 DB 확정 뒤 manifest만 접근 거부 | FINALIZED와 media 유지, manifest_sync_pending 표시·project export 차단, 재시작 후 projection 재시도. 원본/DB rollback·중복 없음 |
| F04 | short write, ENOSPC, journal flush/close 실패, manifest 저장 실패 | 확정 원본 유지, 미확정 저장 성공 오표시 없음, 전체 저장 불가 시 중단. manifest-only 실패는 F03 판정 |
| F05 | DB busy/corrupt, 미래 schema/migration 중단, 두 복구기, 철회 후 동일 PC의 정상 과거 백업 복원 | 단일 소유권·미지원 쓰기 금지. 새 library 실행 세대의 grant/permit·자동 원격 재개 비활성, 유효 키 있어도 재동의 전 egress 0. ledger/삭제 이력 판정불가 보류 |
| F06 | 삭제 DB-only/journal-only/둘다/손상 fixture, 삭제↔복구/송신 barrier, 각 삭제 단계 kill | 어느 한 의도도 재채택 금지, 불완전 이력은 자동 복구 보류, 삭제 세대 재검사, 늦은 게시/신규 송신 0, 멱등 재삭제·성공 오표시 없음. 비용 ledger는 I06 |

## Windows 하드웨어 시험

| ID | matrix와 절차 | 측정과 기대 결과 |
| --- | --- | --- |
| W01 | 선정 backend, 지원 Windows build, USB/내장 mic, 출력 loopback, 44.1/48 kHz, mono/stereo | 전달 포맷·시계 품질 기록, 트랙 분리와 합성 impulse 정렬, 자체 queue dropout 0 목표 |
| W02 | Bluetooth 프로필 변경, 기본 장치 변경, 입력/출력 각각 분리·재연결 | 기존 정상 트랙 지속, 경고와 gap, 새 epoch/format, 무동의 장치 대체 없음 |
| W03 | pause/resume, 한 트랙 ack 지연/누락과 late callback, sleep/wake·wall clock 조정 | 모든 필수 capture+drain/seal ack 뒤만 PAUSED, cutoff 전 큐 저장·이후 신규 PCM/AI tap 0, stop timeout은 완료 아님. 새 epoch와 gap·clock domain 유지 |
| W04 | 1시간 baseline, 8시간 soak, 제한 부하의 AI 동시 실행, 디스크 경고 | 유실·drift·queue/writer latency·RSS·disk growth·UI 응답 기록, 아래 제안 예산 평가 |
| W05 | 표준 사용자 계정 vault, 다른 로그인 계정, vault 권한 실패 | 계정 범위와 실패 경로 확인, 평문 우회 저장 없음, 설정·export·logs에 key canary 없음 |

UI·장치 이벤트 알림의 측정 시작점은 실제 물리 장애인지 OS 통지 수신인지 구분해 기록한다. 자동 테스트에서 관측 불가능한 물리 지연을 추측해서 통과시키지 않는다. 장치 모델, driver, OS build, backend version, 포맷, workload와 trial 수를 증거에 포함한다.

## 정량 목표 제안

| 항목 | 초기 실험 목표 | 확정 조건 |
| --- | --- | --- |
| 청크 길이와 queue | 청크 2초, 저장 queue 4초부터 비교 | P0 목표 장치에서 writer 지연·flush 비용·메모리 측정 후 ADR07 확정 |
| 확정 청크 복구 | 단계별 process kill fixture에서 checksum 일치 100%, 중복 등록 0 | 확정의 경계와 flush 정책을 기록한 F02/F03 결과 |
| 유실 | 정상 기준 장비의 8시간 시험에서 app queue 유실 0, 원인 미표시 유실 0 | 장치가 보고한 유실은 따로 기록하고 제품 무손실 보장으로 확대하지 않음 |
| 시계 정렬 | 합성 ±200ppm 및 offset/gap에서 p95 절대 오차 20ms 이내 목표 | 독립 기준시각과 sample oracle로 평가, 실제 장치는 별도 측정·범위 확정 |
| 저장 지연과 경고 | queue health는 1초 이내, OS 장치 통지 후 UI 알림 2초 이내 목표 | p95/최대와 부하를 함께 기록, capture callback deadline은 backend별 별도 예산 |
| 종료와 취소 | 정상 stop 후 원본 확정 5초 이내, AI 취소 수신 후 2초 이내 응답 목표 | backlog와 모델별 한계 측정, 강제 AI 종료 시 부분 산출물 보호 |
| 메모리 | warmup 이후 장시간 증가 추세와 queue 상한 관측 | 고정 RSS 절댓값은 하드웨어·포맷·모델별 측정 후 확정 |

목표를 낮추거나 예외로 처리할 때는 기존 측정, 사용자 영향과 새 기준을 남긴다. 하드웨어 미측정 수치를 이미 충족한 제품 사양으로 홍보하지 않는다.

## AI 품질과 UX

| ID | 평가 | 통과 정의 |
| --- | --- | --- |
| M01 | 허가된 다국어·잡음·겹침 corpus, 회의·강의 요약, core 1/10 성공·빈/무주장·사용자 삽입 | WER/CER와 reference 구조 100%는 별도 지표. 부분 요약과 전체 성공 구분, 누락 분모·claim 의미 라벨의 사람 평가 프로토콜 적용, AU06 연결 |
| M02 | cold start, 모델 다운로드 중단·손상, VRAM 여유, CPU 허용/거부 | 지연·GPU peak·실시간 처리비 기록, local-only 모델 검증, 사용자 허용 없는 실행 위치 변경 없음 |
| E01 | 녹음→편집→요약→근거→export, 1/10 성공·정상 무음·요약 미선택·복구/삭제 | partial·실패 9/10은 전체 완료 금지, 정상 무음은 처리 complete, 요약 미선택은 audio 완료 허용. 사용자 삽입은 발화 증거 배지 금지·basis 유지 |
| E02 | P1부터 Narrator·키보드로 허용/거부/철회, CPU 거부, 예산 대기 취소, 원격 취소 미확인 설명, 복구 검토·닫기, ack 누락 | 수신자/범위/비용 읽기, 기본 거부·Esc 허용 금지, focus 복귀·gap 읽기·trap 없음. ack 미확인 정지를 완료로 읽지 않음. UI 입력/정책 기록/로컬 ack/원격 미확인 시점 구분 |

전사와 요약 모델의 품질은 단일 총점으로 판정하지 않는다. 한국어 CER과 영어 WER, 고유명사·숫자·일정 오류, unsupported claim과 충돌 근거를 별도 보고한다. AI 채점은 보조이며 사람이 검토한 라벨을 대체하지 않는다. 초기 corpus 수와 품질 임계값은 ML·UX·QA가 P1 전에 고정하고, 평가용 holdout을 튜닝에 재사용하지 않는다.

사람 평가 프로토콜은 원자 claim과 핵심 결정·할 일 단위로 고정한다. supported는 원문이 해당 주장을 실제 지지하는 경우, unsupported는 근거 부재·의미 확대, uncertain은 해석 불명, disputed는 상충 근거로 정의하고 user_assertion은 발화 사실과 분리한다. 예를 들어 “논의했다”만 있는 근거로 “확정했다”는 unsupported다. 비민감 고정 예시에 두 독립 평가자가 라벨을 붙이고 불일치 사유·조정 결과와 일치도를 기록한다. 무주장·빈 요약은 reference 비율을 만점으로 간주하지 않고 적용 불가와 핵심 항목 누락을 함께 집계한다. 누락률 분모는 corpus의 사람이 정의한 핵심 항목 수로 고정한다. 프로토콜·표본수·임계값 확정 전 G3 품질 게이트를 닫지 않는다.

## 보안과 릴리스

| ID | 시험 | 통과 정의 |
| --- | --- | --- |
| S01 | startup부터 SDK·worker·daemon DNS/접속 관측과 양성 대조, I07의 첫·후속 write/삭제 barrier | 동의 없는 egress 0, 과거 permit 사용 금지, 이미 handoff한 바이트 별도. observer가 통제된 허용 요청을 실제 탐지해야 무송신 결과를 인정 |
| S02 | canary secret, crash/exception/log/export/support bundle | 비밀 없음, 허용 필드 목록 일치, 실제 키와 사용자 녹음 사용 안 함 |
| S03 | path traversal·absolute path·reparse point, 악성 import, 삭제와 recovery 경쟁 | 지정 root 이탈 없음, 삭제 부활 없음, 파일·metadata 입력 한도와 version 검사 |
| S04 | 첫 다운로드·로드 기능부터 중단·서명/hash 불일치·오염 cache·라이선스 누락 | G1/G2/P1 필수. 검증 전 설치/로드 금지, 출처·digest·라이선스 일치. 미실행이면 기능 제외와 N/A 근거 필요 |
| REL01 | 깨끗한 Windows VM 설치·업데이트·제거, offline 첫 실행, EXE 권한 | 지원 환경 실행, 비밀/묵시 다운로드 없음, 사용자 미디어의 제거 정책 명확, rollback/복구 가능 |
| REL02 | 고정 commit clean build, artifact hash, SBOM/NOTICE/license, 코드 서명 결정 | 포함 파일 기준 목록과 조건 검토, provenance 기록, G0~G4 증거와 차단 이슈 0 |

기술적 secret 보관 시험과 라이선스 배포 검토는 서로 다른 승인 근거다. 서명 여부와 지원 Windows 버전은 ADR08의 결정으로 남긴다. 서명하지 않은 빌드는 그 상태와 사용자 설치 영향을 명확히 표시한다.

## 현 단계의 검증 기록

설계 당시 제품 시험 U01부터 REL02까지는 `NOT_RUN`이었다. 현재 자동 시험과 교차 검토는 [제품 진행 기록](implementation/product-results.md)에 실제 실행 범위·snapshot과 연결한다. Windows 실장비·실모델·유료 제공업체·clean VM을 fixture 결과로 대체하지 않는다. 문서 설계의 요구사항 추적·계약 검토 승인은 [설계 검토 종결 기록](reviews/design-signoff.md)에, 구현 검증은 [품질 체계](quality-system.md)의 증거 형식으로 각각 남긴다.
