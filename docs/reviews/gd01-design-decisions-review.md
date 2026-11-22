# GD01-R — GD-P01 설계 결정 반영 독립 검토

2026-11-23, 검토자 w5:p8 Codex. 작성자는 C00다. 검토 결과는 **OPEN 2건: S2 1·S3 1, S0/S1 0**이다. 결정 방향에는 동의하며, 시작 실패의 ACK 조건과 lease 대체 후 남은 필수 필드 서술을 보강할 필요가 있다. 문서 검토이며 제품 구현·실장비 검증의 승인이 아니다.

## 1. 대상 고정과 검토 방법

- 대상 tree: `27a35d8e33084a3fed9394639d0833d48f0ba3d1`.
- 비교 HEAD: `9d46b4a9a38de6f9c6fea38db35a440cbad7779f`.
- 직접 실행한 `git diff --stat HEAD 27a35d8e33084a3fed9394639d0833d48f0ba3d1`: **3파일, +14/−6**. architecture +11/−4, assignments +1/−0, 통합 계획 +2/−2다. 제품 코드·시험 변경은 없다.
- 판정 원문·관련 코드·기존 계약은 모두 `git show 27a35d8e:<경로>`로 읽었다. 아래 file:line은 따로 표시한 경우를 제외하면 **이 tree 기준**이다. 작업 트리의 G-P02·G-P04 변경은 대상 구현 증거로 쓰지 않았다.
- 두 G01 보고서, 양쪽 교차 검토와 G01-C 확인, validation-plan, product-contracts B11·B12·B13을 대조했다. 이후 배정에서 승인된 G-P04 재개 제외·G-P05 경계 분리·G-P06 가격 항목 분리·G-P07 REC 강화는 대화의 C00 결정 및 해당 계약 문서와 구분해서 확인했다. 이들 미커밋 계약 문서를 대상 tree의 일부라고 주장하지 않는다.

대상 파일의 LF 기준 SHA-256을 직접 계산했다.

| 파일 | SHA-256 |
| --- | --- |
| `docs/architecture-v1.md` | `25740b64da9eda18c32b375a5b165911c60f8599b33d9b83e085e3ed148eb8ef` |
| `docs/implementation/v1-gap-plan.md` | `97b54113e672439d78fdea58c64911bcd04f263bf2ce9bb8a3671c5594ec262a` |
| `docs/collaboration/assignments.md` | `47f8aa8445847f9921a4ce3637542eb2a840261ca2ba06512c8da4e8835a7d40` |

## 2. 발견

### GD01-01 — ADR11의 시작 실패→PAUSED에 종료 ACK 조건이 빠짐

- **심각도: S2 / OPEN.** 대상: `docs/architecture-v1.md:81`과 `:282`(ADR11).
- **근거:** ADR11은 “장치 시작이 실패하면 … PAUSED로 둔다”라고 조건 없이 적는다. 같은 설계의 `:79`는 모든 필수 트랙의 입력 gate 중단과 writer drain/seal 완료 뒤만 PAUSED라고 정의한다. `docs/validation-plan.md:73` W03과 `docs/implementation/product-contracts.md:91`도 ACK/장치 해제 timeout을 완료로 보지 않는다.
- **실제 코드 경로:** `src/recoryn/app/desktop.py:86-90`에서 RECORDING을 먼저 영속한다. `:156-165`의 시작 실패 처리는 `_close_sources()`가 성공한 뒤에만 `recording.pause()`를 호출한다. `:167-175`에서 source.stop이 실패하면 `CAPTURE_ACK_PENDING`이 발생하고, pause를 건너뛰어 `CAPTURE_START_FAILED_ACK_PENDING`으로 반환한다. 이 경로를 PAUSED라고 쓰는 것은 현재 동작에도 맞지 않는다.
- **재현 가능한 정적 반례:** 해당 tree의 `tests/unit/test_desktop.py:14-36` FakeSource 두 개를 사용해 첫 source의 `fail_stop=True`, 둘째 source의 `fail_start=True`로 두고 두 트랙 start를 호출하는 입력이다. 첫 트랙은 수락 후 stop ACK를 못 주고, 두 번째 시작이 실패한다. 코드 추적 결과는 `CAPTURE_START_FAILED_ACK_PENDING`, `recording.pause()` 미호출, 영속 상태 RECORDING 유지다. 이 조합을 이번 검토에서 실행한 시험 결과로 세지는 않았다. 근거 읽기 명령은 `git show 27a35d8e:src/recoryn/app/desktop.py`와 `git show 27a35d8e:tests/unit/test_desktop.py`다.
- **기존 시험의 확인 범위:** `tests/integration/test_desktop_independent.py::test_partial_start_failure_waits_for_all_source_stops_and_keeps_media`의 `:96-102`는 source 종료가 완료된 시작 실패의 PAUSED·48frame 보존을 확인한다. `tests/unit/test_desktop.py::test_stop_timeout_never_acknowledges_paused`의 `:65-75`와 통합 시험 `test_missing_stop_ack_preserves_source_ownership_and_library_lock`의 `:107-128`은 ACK 미완료 시 RECORDING과 소유권 유지를 확인한다. 소스를 대조한 것이며 이번 배정에서 재실행하지 않았다.
- **기대·제안:** 본문과 ADR11에 “시작 실패 시 모든 장치 해제 ACK와 writer drain/seal이 끝나면 PAUSED로 두어 부분 원본을 보존한다. ACK가 끝나지 않으면 종료 확인 대기를 유지하고 PAUSED/정지 성공으로 표시하지 않는다”를 적는다. ACK 대기의 REC 억제는 G-P07의 구현 조건으로 남긴다. 현재 제품의 ACK 보호를 바꾸거나 모든 시작 실패를 억지로 PAUSED로 만드는 수정은 필요 없다.

### GD01-02 — ADR12로 대체한 lease 만료 시각이 본문에는 여전히 필수 정보

- **심각도: S3 / OPEN.** 대상: `docs/architecture-v1.md:87`과 `:283`(ADR12).
- **근거:** 본문 첫 문장은 여전히 모든 작업이 “lease owner와 만료 시각 … 을 갖는다”라고 요구한다. 바로 다음 문장과 ADR12는 **만료 시각 대신 단일 재시작 coordinator 증명 방식을 설계로 채택**한다. `docs/implementation/v1-gap-plan.md:41`의 결정도 현재 동작을 설계에 반영한다는 것이므로, 현 v1.0의 필수 계약에 만료 시각이 남아 있으면 G1A-26 문서 편차가 완전히 닫히지 않는다. 후속 문장이 대체 방식을 설명해 즉각적인 구현 위험은 낮지만 필수 schema/수락 기준을 두 가지로 읽을 수 있다.
- **대조:** `docs/reviews/g01-gap-recording.md:98` G1A-26의 원인도 만료 시각 부재다. `docs/implementation/product-contracts.md:62`의 B11 reader 수명 확장(문서상 B12 절 안)은 `recover_abandoned(coordinator_exclusive=True)`와 단일 재시작 증거를 요구한다. `src/recoryn/jobs/__init__.py:723-729`는 호출자가 이전 task/reader 프로세스의 종료를 확인해야 하며, flag는 명시 확인 진술이고 OS 생존 검사가 아니라고 한정한다. 통합 계획 `:75`도 고아 reader 종료 증명 **자동화**를 후속으로 남겼다.
- **기대·제안:** 첫 문장의 현 v1.0 필수 정보는 owner/fence와 재시작 coordinator의 종료 확인 전제로 정리하고, 만료 기반 lease는 다중 프로세스 worker 도입 시 재검토 항목으로 분리한다. ADR12의 “증명”도 호출자의 명시 종료 확인을 전제로 하며 flag 자체가 자동 증명은 아니라는 한 문장을 덧붙이면 범위가 명확하다. 기존 모듈 표의 “lease”나 validation U03/I04의 owner/fence 교체 시험 자체를 삭제할 필요는 없다. 종료 증명 자동화 구현을 이번 문서 단위로 추가하라는 제안이 아니다.

## 3. 동의하는 반영과 확인 범위

| 결정/변경 | 대조 근거 | 판정과 한계 |
| --- | --- | --- |
| ADR11의 RECORDING 선행·부분 원본 보존 | 통합 계획 `:40`, G1A-22/GF-08, G01CR-01 | 상태 결정에는 동의. ACK 예외 표현만 GD01-01로 보강 |
| ADR11의 REC 조건 | architecture `:81,282`, G-P07의 승인된 현재 run·양의 수락·전체 장치 준비 조건 | `:282`에 **구현과 시험은 G-P07**이라고 명시해 구현 완료로 오인하지 않음. 시작·재개 token/epoch·저장 실패/ACK 억제 세부 계약은 G07에 유지 |
| ADR12의 coordinator 방식 | 통합 계획 `:41`, G1A-26, B11 reader 수명 확장 `product-contracts:62` | 채택 방향에는 동의. 필수 정보 서술은 GD01-02로 정리 |
| ADR13의 content DB 저장 | architecture `:126,128-142`, 통합 계획 `:42`, G1A-53, product-contracts `:58` | JSON 폴더 2개를 배치도에서 제거하고 `content_revisions`와 export를 구별함. SQLite를 기준으로 한 기존 내용과 일치 |
| ADR14의 CANCEL_UNCONFIRMED 대응 | architecture `:87,96,285`, 통합 계획 `:43`, G1A-17, `jobs/__init__.py:649-672` | 개념상의 취소 미확인을 기존 REMOTE_UNKNOWN+cancel_requested로 대응. UNKNOWN 유지·자동 재전송/재개 거부와 일치하며 별도 enum 도입을 요구하지 않음 |
| ADR15의 에코 완화 연기 | architecture `:120,257-264,286`, 통합 계획 `:44`, G1A-46/GF-20, 양쪽 G01-C 확인 | 선택 파생 처리의 원본 불변 제약은 유지하면서 v1.0 이후로 명시 연기. 구현 완료로 닫지 않음 |
| ADR16의 BLOCKED 설계 유지 | architecture `:75,97-100,287`, 통합 계획 `:39,67`, G1A-15/GF-03, G01B-071/F-UX02, G01BR-20 | 현재 FAILED 편차를 인정하고 **구현 정정 예정/G-P07**이라고 명시. 사유 기록 뒤 다음 행동 UI를 연결하는 순서도 보존 |
| ADR17의 수동 모델·S04 | architecture `:288`, 통합 계획 `:45,73`, B13 `product-contracts:99`, validation S04 `:113`, G01BR-05·G01CC-B02 | 수동 폴더 허용과 신뢰된 출처/digest/license 검증은 구별됨. S04 적용/예외 결정을 **G-P13로 보류**한다고 기록했으므로 이번 단위가 S04를 통과·면제한 것으로 보지 않음. 실행 전 digest·표시 요구도 G-P13 구현/검증으로 추적 필요 |
| G-P04의 확정 경로·재개 제외 | 통합 계획 `:57,75`, architecture `:73,114`, C00의 G-P04 승인 | 재부팅 전후 단조 시계 직접 연결을 피하고 GF-06과 함께 다룬다는 범위 분리는 타당. 상태 표의 명시 사용자 재녹음·새 epoch는 이 기능이 이미 구현됐다는 뜻이 아님 |
| 요약 후보 UI·실제 가격 항목·G-P05 분리 경계 | 통합 계획 `:75`, C00의 G-P03/G-P06/G-P05 결정 | API 후보 선택을 UI 기능으로 과장하지 않음. 실제 가격 항목은 G-P06 뒤 공식 근거 고정 단위. reader 종료 증명 자동화와 별도 DB-only 삭제 경계도 미해결 후속으로 남김 |
| 모듈 경계·B11/B12/B13 | architecture `:28-45`, product-contracts `:58,62,91,99` | 새 제품 책임·네트워크 경로·저장 테이블을 구현한 단위가 아님. 기존 content DB·reader ACK·수동 모델 계약이 이미 있어 product-contracts를 수정하지 않은 것 자체는 누락으로 보지 않음 |

ADR17에 남은 S04의 적용/예외는 미결 요구다. 이번 문서가 그 결정을 끝냈다는 주장이나 신뢰된 모델 검증 전체 완료 주장은 찾지 못했다. 일반적인 기능 허용을 보안 검증 완료로 승격하지 않는 조건으로 보류를 수용한다.

## 4. 링크·표 형식과 검증 결과

3파일의 내용을 해당 tree에서 직접 읽고 저장소 파일 목록과 대조하는 읽기 전용 스크립트를 실행했다.

- 상대 Markdown 링크 **31회 출현**, 해당 tree 안의 대상 누락 **0**. 중복 출현을 포함한 수이며 고유 링크 31개라는 뜻은 아니다.
- 외부 HTTPS 링크 **9회 출현**은 문법/구분만 확인했다. 네트워크로 도달성·원문 최신성을 확인하지 않았다.
- fenced code 밖의 Markdown 표 열 수 불일치 **0**, 닫히지 않은 코드 펜스 **0**.
- 신규 ADR ID ADR11~17과 본문 참조 ADR11~14가 일치한다. ADR15~17은 결정 기록 표에서 직접 읽을 수 있다.
- assignments의 신규 GD01 행은 C00 작성·본 검토 파일 한정·검토 대기를 명시한다. 기존 G04 행의 “확정·재개” 명칭은 GD01 추가 전부터 있던 표기이며 이번 검토에서 G-P04 재개 구현의 증거로 쓰지 않았다. 정본 수락 범위는 갱신된 통합 계획과 C00 승인 계약이다.

읽기 명령 예시는 `git diff --stat HEAD 27a35d8e33084a3fed9394639d0833d48f0ba3d1`, `git diff HEAD 27a35d8e -- docs/architecture-v1.md docs/implementation/v1-gap-plan.md docs/collaboration/assignments.md`, `git show 27a35d8e:docs/architecture-v1.md`다. 링크 검사는 `git ls-tree -r --name-only 27a35d8e`의 파일 집합에 정규화한 상대 경로를 대조했다. 외부 내용 조회·Git 쓰기·제품 코드/시험 수정은 하지 않았다.

기존 제품 시험 재실행·새 반례 시험 작성·mutation은 **미실행**이다. 코드/기존 assertion의 소스 대조와 문서 구조 감사 결과를 제품 동작 PASS 숫자로 바꾸지 않았다. 지정한 신규 검토 문서만 작성했으며 대상 3파일과 G01 원 보고서는 수정하지 않았다.

## 5. 종결 조건

- GD01-01: 본문과 ADR11에 PAUSED의 ACK/drain 완료 조건 및 ACK 대기 예외를 반영.
- GD01-02: 현 v1.0의 필수 필드에서 만료 시각 요구와 ADR12 대체 방식의 관계를 일관되게 정리. coordinator 증명 자동화를 완료한 것으로 읽히지 않게 전제 명시.
- C00의 수정/수용 뒤 재확인 전까지 **OPEN 2건(S0 0·S1 0·S2 1·S3 1)**이다. 다른 설계 결정에 추가 이견은 없다.

## RECHECK

2026-11-23, 같은 검토자 w5:p8 Codex. 대상은 새 tree **`99a482cc9355f9070970717c57b6020e6a2d4e5e`**다. 1차 검토 원문은 보존하고 이 절만 추가했다. 추가 전 검토 문서의 LF SHA-256이 최초 제출값 `d1ed49e701770964be213b2299db92ee1ee5aef68b1270219484b8619e3fa811`과 일치함을 확인했다.

### 변경 범위와 근거

직접 실행한 `git diff --stat 27a35d8e33084a3fed9394639d0833d48f0ba3d1 99a482cc9355f9070970717c57b6020e6a2d4e5e`와 전체 diff는 **architecture-v1.md 1파일, +4/−4**다. 새 tree의 architecture LF SHA-256은 **`1dfad6ef81e9d7e84015cf6241e970342e787cb06776067a810cbd84aac4ff5c`**다. 아래 행 번호는 새 tree 기준이다.

`git show 99a482cc:<경로>`로 수정 본문·ADR과 코드·계약을 다시 읽었다. 통합 계획·assignments·`app/desktop.py`·`jobs/__init__.py`가 1차 tree와 바이트 단위로 같음도 대조했다. 작업 트리의 다른 단위 변경을 재확인 대상에 섞지 않았다.

| 원 발견 | 재확인 판정 | 직접 확인한 근거 |
| --- | --- | --- |
| GD01-01 / S2 | **RECHECKED** | `docs/architecture-v1.md:81,282` 모두 PAUSED의 전제에 모든 장치 해제 ACK와 writer drain/seal 완료를 명시했다. 본문은 ACK 미완료 시 `CAPTURE_START_FAILED_ACK_PENDING`·RECORDING 유지·종료 확인 대기이며 PAUSED/정지 성공 표시 금지를 적었다. 이는 같은 문서 `:79`의 PAUSED 정의, `validation-plan.md:73` W03, `product-contracts.md:91`의 timeout 미완료 원칙과 일치한다. 원 정적 반례의 경로인 `app/desktop.py:156-175`에서 장치 해제 ACK 실패가 pause 호출을 건너뛰는 사실을 이제 문서가 구별한다. REC 조건은 ADR11의 확인 조건에서 여전히 **G-P07 구현·시험 예정**으로 남아 있다 |
| GD01-02 / S3 | **RECHECKED** | `docs/architecture-v1.md:87`의 필수 정보에서 만료 시각을 제거하고 owner/fence를 유지했다. v1.0은 만료 시각 없이 이전 작업·reader 종료의 명시 확인 뒤 회수한다고 정리했으며 호출자 진술과 OS 생존 검사 자동 증명을 구별했다. ADR12 `:283`에도 같은 한정과 자동화 후속을 적었다. `jobs/__init__.py:723-729`의 명시 확인 전제, `product-contracts.md:62`의 reader 수명 계약, 통합 계획 `:41,75`의 채택/후속 구분과 일치한다. 만료 기반 lease는 다중 프로세스 worker 도입 시 재검토로 분리됐다 |

### 회귀 확인과 한계

- 바뀐 네 문서 행과 주변 상태/provider 오류 표·ADR13~17을 다시 대조했다. 1차에서 동의한 DB content 저장·UNKNOWN 취소 표현·에코 연기·BLOCKED 정정 예정·S04 보류는 바뀌지 않았다. 새 발견 GD01-03 이후로 등록할 이견은 없다.
- 새 tree의 대상 3문서에 링크·표·펜스 감사를 다시 실행했다. 상대 링크 31회 출현의 대상 누락 0, 표 열 수 불일치 0, 미종결 코드 펜스 0이다. 외부 HTTPS 링크 9회는 네트워크 조회하지 않았다.
- 제품 코드·시험 변경이 없는 문서 재확인이므로 제품 시험·정적 검사·새 반례 실행·mutation은 수행하지 않았다. 원 정적 반례와 기존 assertion을 코드로 재대조한 것이며 독립 실행 PASS로 보고하지 않는다. coordinator 종료 확인 자동화, G-P07 REC/BLOCKED 구현 및 실장비 게이트를 이번 문서 검토로 닫지 않는다.

재확인 결과 **GD01-01·GD01-02 모두 RECHECKED, 신규 발견 0, OPEN 0(S0 0·S1 0·S2 0·S3 0)**이다. 문서 통합의 최종 결정은 C00가 맡는다.
