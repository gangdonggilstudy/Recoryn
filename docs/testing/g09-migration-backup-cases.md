# G09 / G-P09 schema migration·backup·복원/import 계약안

상태: **계약 승인 대기, 제품 구현·신규 시험·mutation 미실행**. 작성자 w5:p8 Codex. 이번 쓰기는 이 문서 하나다. 아래 API·schema·파일 목록·분모는 후속 구현 승인 요청이며, 독립 검토와 최종 통합은 별도다.

## 1. 정본·순서·위험

- 정본: `v1-gap-plan.md`의 G-P09/GF-11·G01AR-05, 등급 결정의 복원/import MISSING S2 및 G1A-69 백업 생성 통합. G01-A의 G1A-68·69·V-F05, G01AR-05와 architecture의 저장·복구/산출물 버전/비밀·데이터 수명 계약을 따른다.
- G-P03 content_summary_requests, G-P02 consent v2, G-P06 cost v2/witness, G-P08 health v2, G-P05 삭제 journal/tombstone 인계를 모두 포함한다. 아직 미커밋인 승인 계약은 구현 완료 증거로 세지 않는다.
- 구현은 **G-P02·G-P04·G-P05·G-P06·G-P08 push 뒤 C00 신호**로 시작한다. G-P08의 선행 G-P07도 포함된 최종 tree와 구성요소 fingerprint를 착수 때 다시 고정한다. 공유 storage/security/UI/CLI를 다른 단위와 동시에 수정하지 않는다. 다른 요청은 먼저 처리한다.
- workflow 부재는 S2지만 권한 부활·삭제 부활·UNKNOWN/금액 이력 손실·비밀 노출은 S1 관점에서 시험한다. 백업 복원은 실행 권한·삭제 이전 데이터·예산 잔액을 과거로 되돌릴 권한이 아니다.
- 실제 음성/장치·모델·네트워크·계정·vault 쓰기·설치 없이 계약을 작성한다. 실제 전원 장애·서버 청구 내역·같은 사용자 권한 공격에 대한 인증까지 보장하지 않는다.

## 2. 직접 확인한 현재 경계

다음은 작업 트리 소스와 승인 문서를 읽어 확인한 내용이다. 현재 미커밋 G-P02/G-P04가 섞여 있으므로 최종 push tree의 검증 결과로 대신 쓰지 않는다.

| 근거 | 현재 사실 | 필요한 변화 |
| --- | --- | --- |
| `storage/library.py` 초기화·`_check_version` | Library가 user_version=1을 소유, 지원 여부 확인 후 WAL/FULL·기본 표 생성 | 명시 유지보수 전이와 파일/구성요소 버전 정본 |
| `jobs/__init__.py`, `content/store.py` | 별도 표 additive 생성, content_summary_requests 존재. Job checkpoint 표는 사용 중 지연 생성 | 구성요소 등록·정확한 profile 검증, 실행 중 DDL 축소 |
| `storage/_coordination.py` | writer 경로도 user_version=1과 삭제 기록을 확인 | 새 형식과 유지보수 중 쓰기 차단을 같은 정본으로 검사 |
| `security/_core.py:219` | 공유 DB의 user_version 0/1만 허용. Coordinator·경로 방어 존재 | security-only/분리/같은 파일 구성을 일관되게 지원 |
| `security/consent.py` G-P02 | 새 ConsentStore 생성 때 execution_id 갱신. grant scope·기능·정책 v2 | 복원 전체 workflow와 키 참조 재연결까지 이것만으로 완료되지 않음 |
| `security/ledger.py`와 G-P06 계약 | witness 선행→DB commit, 불일치 안전 차단. G-P06은 v1 선검증·v2/legacy 상태 인계 | 임의 재서명/복사한 과거 잔액의 새 권위 승격 금지 |
| `cli.py`, `ui/main.py` | 일반 작업 경로가 먼저 Library를 열고 UI는 ConsentStore/CostLedger를 생성 | 유지보수·복원·미지원 경로를 일반 생성자보다 먼저 분기 |
| G-P05/G-P08 계약 | 삭제 이력 정합·최대 세대, 건강 상세3표·UNKNOWN_TAIL | backup 대상과 복원 검증에 빠뜨리지 않음 |

기존 백업/migration 기능이나 DB busy 시험이 완료돼 있다는 주장은 하지 않는다. 아래 계획의 수치는 과거 8025/9009 등의 PASS 숫자와 독립이다.

## 3. 버전 목록 정본

### 3.1 물리 파일 형식과 구성요소를 분리

신규 `recoryn/schema.py`를 Qt/SDK/장치/앱에 의존하지 않는 정본으로 둔다. **새 파일 형식 CURRENT_FILE_VERSION=2**를 제안한다. Library/Security/Job/Content/writer guard가 공통 검사를 사용한다. user_version은 물리 파일당 하나이며 동일 파일의 logical role 두 개가 각자 올리지 않는다.

- 형식2는 `recoryn_schema_components`와 `recoryn_maintenance`를 포함한다. 전자는 구성요소명/version/fingerprint/profile, 후자는 library_instance_id·operation/유지보수·복원 실행 상태·검증 보류 상태를 기록한다. 비밀은 없다.
- fingerprint는 임의 SQL 문장의 whitespace hash가 아니라 명시한 columns/type/null/PK/FK/index/제품 trigger와 내부 version의 정규 표현이다. 기존 `content_revision_immutable` 등 제품 trigger는 목록에 넣고 임의 view/trigger/virtual table은 수락하지 않는다.
- 형식1 Library, 형식0/1의 알려진 security-only profile 및 정상 additive 조합은 **legacy**다. component 일부가 정상적으로 아직 없던 과거 profile과, 같은 version에서 표가 유실된 상태를 구별한다. 정확한 지원 profile을 등록하고 임의 추정 CREATE로 수선하지 않는다.
- 형식2의 registry/표 불일치, 지원하지 않는 component version, registry 없는 형식2는 정상으로 열지 않는다. 형식>2는 원본 보존·명시 미지원. 형식0도 빈 새 DB인지 손상/유실인지 먼저 검사하며 witness나 기존 자료가 있으면 신규 DB로 만들지 않는다.
- 정상 open은 legacy에 **MIGRATION_REQUIRED**를 반환한다. UI/CLI의 명시 유지보수 workflow만 upgrade한다. 처음 만드는 빈 DB는 선택한 profile로 형식2를 원자 초기화할 수 있다. standalone JobStore/ContentStore/ConsentStore/CostLedger 조립도 등록된 component profile로 지원하며 전체 Library 표를 무조건 요구하지 않는다.
- 구버전 앱의 기존 user_version 0/1 guard가 형식2를 거부하도록 한다. v2 cost witness도 v1로 읽히지 않아야 한다. 자동 downgrade·구버전 동시 쓰기는 지원하지 않는다.

### 3.2 인계 구성요소 표

아래는 현 단위가 소유권을 인계받아 목록에 등록할 표다. 아직 없는 G-P06/G-P08의 정확한 DDL·fingerprint는 승인 계약을 기준으로 선행 push 후 확정한다. 내부 schema_version, 동의 정책 version, 비용 정책 version, 물리 user_version을 같은 번호로 간주하지 않는다.

| 구성요소 | 표/자료 | 인계·변환 규칙 |
| --- | --- | --- |
| library catalog 1 | sessions/chunks/storage_events/deleted_sessions, manifest·descriptor version1 | 기존 원본/hash·세션/삭제 세대 보존. DB 형식2가 media version2를 뜻하지 않음 |
| jobs core/reader/remote/checkpoint 1 | jobs/attempts/events/job_create_receipts/job_sessions/job_local_readers/job_remote_intents/job_checkpoints, 관련 index | 이력·fence·취소·UNKNOWN 보존. checkpoint 표의 알려진 legacy 부재는 명시 migration에서 빈 표 생성 |
| content core 1 | content_revisions/content_selections/content_events와 immutable trigger | 선택 version·candidate·내용·부모 관계 보존 |
| G-P03 summary request 1 | **content_summary_requests** | additive/user_version 불변 이력을 채택. 설정 키를 새로 추측하지 않음 |
| G-P02 consent 2 | **security_grants_v2/security_consent_meta**, execution/sessions/local_endpoints | 범위·정책·철회 보존. 가져온 권한은 비활성. 옛 security_grants는 backup·검증 뒤 명시 transaction에서 정리하며 v2로 승계하지 않음 |
| security cost legacy 1 | security_cost_meta/accounts/requests, predecessor digest | G-P06 witness 검증 대상이므로 임의 삭제 금지. LEGACY_UNSCOPED·전환 보류 상태 보존 |
| G-P06 cost 2 | **security_cost_accounts_v2/security_cost_requests_v2/security_cost_usage_events/security_cost_meta_v2** | 통화·기간·금액·event/version·quote 근거 보존. 네 표의 부분 유실을 새 예산으로 만들지 않음 |
| G-P06 witness protocol 2 | `<물리 DB명>.cost-witness`, v1 선검증·전환 상태 | DB와 paired snapshot. 혼합 버전/불일치에서 재서명 금지. v1 표와 v2 모두 계약된 검증 범위 유지 |
| G-P08 health 2 | **capture_health_runs/capture_health_tracks/capture_health_events** | legacy-only/v2 구분, OPEN/CLOSED·prefix·UNKNOWN_TAIL·detail_complete 보존 |
| G-P05 삭제 이력 1 | deletion-journal 전부와 deleted_sessions tombstone | 유효 D/J의 최대 세대 g, session 세대가 더 새로우면 충돌. 손상/미완성 이력은 보류. tombstone 자동 제거 금지 |
| G09 관리 1 | recoryn_schema_components/recoryn_maintenance | 유지보수 상태·operation ID·입력/출력 digest·복원 제한을 기록. 입력 package의 NORMAL/허용 플래그를 신뢰하여 활성화하지 않음 |

v1 grants 정리와 v1 cost 보존을 구분한다. v1 cost를 지워 witness를 정상화하지 않는다. legacy 비용의 통화/기간을 임의 USD/현재 월로 만들지 않는다. 유효한 v1-only cost는 목록에 LEGACY_UNSCOPED/전환 필요로 등록할 수 있으나 지출 가능 v2로 승격하지 않는다. G-P06의 명시 전환·정산 전까지 비용 기능을 보류한다.

## 4. 유지보수 프레임과 중단 복구

### 4.1 진입·권한·잠금

유지보수는 Session/Job enum이 아닌 app/root 상태다. 제안 상태는 NORMAL→QUIESCING→BACKUP_PREPARED→APPLYING→VERIFYING→COMPLETED이며, 중단은 NEEDS_RESUME, 검증 충돌은 QUARANTINED/RECONCILIATION_REQUIRED로 구별한다.

1. UI는 dry plan을 읽어 대상·버전·변경·backup 위치·재연결 필요·금융/삭제 보류를 제시한다. 승인 전에는 migration/restore를 시작하지 않는다. 기본 버튼은 취소, Esc는 취소다.
2. 사용자가 시작하면 새 capture/AI/내보내기/삭제 입장을 막고, 실제 source/writer/owned reader·작업자의 종료 ACK와 모든 DB transaction 종료를 확인한다. timeout이나 논리 CANCELLED를 물리 종료 증거로 쓰지 않는다. 권한 세대와 permit은 회수하고 자동 원격 재개를 막는다.
3. canonical 물리 파일 identity로 경로를 중복 제거한다. 같은 파일 구성은 연결·backup·version 전이를 한 번만 수행한다. 경로/동일성 확인은 로컬 경로 방어 뒤에 수행하며 UNC/재분석 경로를 먼저 resolve하지 않는다.
4. root 제어 lock→물리 DB의 정렬된 coordinator 순서로 잠근다. Library root owner와 security Coordinator의 잠금 순서를 모든 app 호출자가 따른다. 캡처 lock을 잡은 채 유지보수 DB lock을 기다리지 않는다. 합의된 모든 호출자가 quiescent라는 전제이며 임의 프로세스의 종료를 OS가 자동 증명한다는 주장은 아니다.
5. busy/cancel deadline 기본10초를 monotonic으로 관리한다. 같은 시각에 deadline이면 실패다. UI는 worker에서 진행·취소를 표시하고, live/busy이면 원본 변경 전에 MAINTENANCE_BUSY/DB_BUSY로 반환한다. 강제 kill/강제 unlock/실행 중 DB 교체는 없다.

### 4.2 검증·적용·재개·롤백

`plan_migration`, `enter_maintenance`, `apply_migration`, `resume_maintenance`, `rollback_maintenance`를 maintenance package의 공개 facade로 제안한다. `app/maintenance.py`가 실제 서비스 종료/재개와 UI/CLI를 조립한다.

- 먼저 원본 파일 세트와 schema를 **쓰기 없이** 검사한다. 활성 WAL을 무시하는 immutable 연결로 미래 버전을 놓치지 않는다. 정지·잠금된 DB의 main/WAL 등 전체 세트를 TEMP 진단 사본으로 읽어 WAL에만 있는 version도 확인할 수 있다. 이는 정상 backup 대체물이 아니며 원본 한 파일을 backup이라고 부르는 경로가 아니다. 미지원 원본에 WAL pragma/DDL/초기화 생성자를 먼저 적용하지 않는다.
- 인가된 기존 자료에만 SQLite backup API로 before-image를 만들고 integrity_check/foreign_key_check·구성요소·삭제/witness를 검증한다. DB 파일의 페이지 bytes와 backup 파일 bytes가 같다고 가정하지 않는다. 원본 미디어의 bytes/hash는 동일해야 한다.
- maintenance operation journal은 root의 관리 경로에 원자 게시한다. operation ID·physical DB map·전/후 profile·단계·파일 hash·pair witness·취소/복원 제한을 기록한다. 이 hash는 손상 탐지이며 서명/신뢰 권위가 아니다. journal은 일반 실행보다 먼저 확인한다.
- 각 물리 DB의 변경은 `BEGIN IMMEDIATE` 안에서 검증된 DDL·registry·마지막 user_version=2를 함께 commit한다. 단계는 고정 ID/전·후 fingerprint로 멱등이다. 서로 다른 두 DB를 하나의 SQLite transaction이라고 주장하지 않는다. 일부 commit 뒤 journal이 남으면 모든 일반 쓰기를 막고 명시 재개한다.
- transaction 미commit 중 crash는 SQLite rollback 후 전/후 fingerprint와 journal을 대조한다. commit 뒤 journal 갱신 전 crash는 이미 일치하는 단계를 다시 적용하지 않는다. journal 없는 부분 표·미래 version·hash 불일치는 추정 수선하지 않는다.
- G-P06 cost 전환이 필요하면 그 단위의 **v1 검증→witness 선행→DB commit** 절차만 호출한다. witness 게시 후 DB commit 실패는 자동 before-image 복원/새 witness 생성으로 숨기지 않는다. RECONCILIATION_REQUIRED와 지출 차단을 유지한다.
- 자동 롤백은 같은 operation의 before-image가 검증되고, 그 후 사용자 쓰기/지출이 없으며, cost witness가 전진하지 않았음을 증명할 때만 허용한다. 그 외에는 rollback 가능 상태라고 표시하지 않는다. 미디어는 migration으로 바꾸지 않는다. 롤백해도 옛 grant/permit을 다시 활성화하지 않고 새 실행/재연결을 요구한다.
- 완료 전 integrity/FK·profile·내용·선택·삭제·health·cost 노출을 재검증하고 완료 marker를 마지막에 게시한다. journal 정리 실패는 유지보수 보류로 표시한다. stale operation을 지워 NORMAL로 강제 전환하는 버튼은 없다.

구버전/현재 버전에서 남은 일반 CREATE TABLE IF NOT EXISTS를 무조건 repair로 실행하지 않는다. 첫 생성 및 승인된 새 component의 완전 부재만 허용하고, 이미 등록된 component의 부분 유실은 안전 실패다.

## 5. backup 형식·위치·정합

### 5.1 정상 backup bundle

기본은 root 밖의 **사용자 지정 로컬 새 디렉터리**다. 원본/대상 포함 관계, 기존 디렉터리 덮어쓰기, 재분석 경로·hardlink·UNC·네트워크/동기화 저장 위치는 거부한다. 같은 볼륨의 고유 staging에 쓴 뒤 검증된 새 이름으로 게시한다. 실패한 staging은 미완료로 남고 완료 marker 없이 정상 backup 목록에 넣지 않는다. 기존 사용자 경로를 재귀 삭제하지 않는다.

```text
<bundle>/backup.json                 # 마지막 완료 marker, 형식1
         inventory.jsonl             # 경로·byte·hash의 스트리밍 목록
         db/<physical_id>.sqlite     # 물리 DB당 1개, checkpoint된 독립 snapshot
         witness/<physical_id>.cost-witness
         deletion-journal/...
         sessions/<id>/...           # 검증된 원본·staging·manifest·파생 파일
```

manifest는 bundle ID, kind(full_library/project), source instance 식별, 선택 session 범위, logical role→physical_id map, component 목록·version, DB/witness 연결, 삭제/정산/건강 이력의 포함·완전성 상태, schema/media version을 포함한다. 파일별 상대 경로/byte/SHA-256은 정렬된 inventory.jsonl에 두고 manifest가 그 hash·행 수·총 bytes를 고정한다. inventory는 자신과 backup.json을 목록에 넣지 않는다. credential secret·실행 중 permit·키 본문·절대 source 경로는 넣지 않는다. credential **참조**가 있더라도 복원 후 재연결 전에는 사용하지 못한다.

backup.json은64KiB 이내, inventory 한 행은4KiB 이내, 파일 수는100,000 이하를 제안한다. 전체 inventory를64KiB JSON으로 한 번에 읽지 않는다. 계획 bytes·여유 공간을 preflight하고 실제 ENOSPC도 미완료로 처리한다. 사전 여유 공간 확인이 쓰기 성공을 보장하지 않는다. 공용 JSON 한도를 늘리지 않고 각 행·파일·정규화 경로/깊이를 제한한다.

- DB는 **sqlite3.Connection.backup**으로 복사한다. WAL commit을 포함한 snapshot을 받고 destination을 닫아 자체 WAL 의존이 없는지 재검증한다. 활성 main 파일만 복사하지 않는다.
- 분리 DB 두 개는 모든 입력·동의·원장·삭제 쓰기를 quiesce하고 잠근 동일 정지 cut에서 각각 backup한다. 같은 파일은 한 번만 backup한다. witness는 cost 상태 검증 후 같은 cut의 파일을 byte 그대로 보관한다. 복제 사본의 원장을 새 기준으로 재서명하지 않는다.
- SQLite backup progress는 bounded page와 deadline/cancel을 확인한다. BUSY 반복은 무한 대기가 아니다. uncommitted 소유 transaction을 임의 commit하거나 rollback해서 backup 성공으로 만들지 않는다.
- 원본 청크·검증 가능한 staging·삭제 journal·tombstone·content/Job·건강 이력·ledger/event를 함께 검사한다. staging 존재가 complete를 뜻하지 않는다. G-P08의 bounded JSON만 복사해 전체 건강 이력을 누락시키지 않는다.
- 정상 full backup도 삭제 대기/tombstone session의 잔여 미디어를 새로 복제하지 않는다. DB의 삭제 의도와 journal은 보존하고, 해당 미디어의 의도적 미포함을 inventory 범위에 기록한다. 비용 이력은 세션 삭제와 독립하므로 그대로 포함한다. 기존 backup의 자동 제거를 구현했다는 뜻은 아니다.
- backup 복원 뒤 일치는 원본 bytes/hash와 **논리 DB 내용/참조/노출**을 기준으로 한다. 새 실행/권한 비활성·관리 registry 등 명시 변경분을 제외한 불변식을 고정한다. SQLite 페이지 배치까지 같은 bytes라고 주장하지 않는다.

### 5.2 project bundle 범위

`backup --session ID`는 같은 형식의 project bundle을 만든다. 선택 session의 미디어·content/참조·관련 Job/health를 포함하고 범위 밖 자료/키 참조·라이브러리 전체 금융 내역은 내보내지 않는다. shared DB snapshot을 사용하더라도 게시 전에 project profile로 선택 범위를 검증한다. 삭제된/삭제 대기 session의 project 생성은 거부한다.

project는 금융 이력 전체를 갖지 않으므로 `cost_history=NOT_INCLUDED`, 전역 삭제 완전성도 해당 scope로만 표시한다. 빈 cost 표를 “예산 사용0”으로 대체하지 않는다. 기존 WAV/export.json은 이 새 DB/이력 bundle이 아니므로 **UNSUPPORTED_IMPORT_FORMAT**으로 구별한다. 일반 오디오 파일을 새 session으로 변환하는 import는 별도 후속 범위이며 이번 프로젝트 복원이라고 오인하지 않는다.

project DB의 active role map은 library/project profile이며, 원래 source가 공유 DB였다고 해서 제거한 security 표를 아직 존재하는 role로 선언하지 않는다. 출처 role 정보와 target의 실제 profile을 구별한다.

NOT_INCLUDED는 처음부터 설정하지 않은 component의 부재와 다르다. store 생성자가 이를 보고 빈 ledger/witness를 자동 생성해서는 안 된다. UI는 해당 보안 기능을 보류한 상태로 로컬 데이터를 보여 준다. project 대상 DB에 다른 세션이나 원래 공유 DB의 금융 표가 남아 있으면 게시를 거부한다.

## 6. 복원/import와 안전한 재개

### 6.1 새 대상에만 준비·검증·권한 제거

`restore_bundle`과 `import_bundle`은 **새 로컬 root**에만 실행한다. 기존 라이브러리 덮어쓰기/기존 session으로 merge/ID 충돌을 덮어쓰기 하는 동작은 제공하지 않는다. restore는 전체 backup을, import는 full/project를 독립 library namespace로 받아들인다. source bundle·현재 권위 자료는 변경하지 않는다.

1. 일반 Library/ConsentStore/CostLedger 생성 전 manifest 형식·크기·상대 경로·중복/대소문자 충돌·reparse/hardlink·hash·DB/FK/schema·media·삭제/witness를 TEMP/staging에서 검증한다. package의 SQL trigger/view를 임의 실행하지 않으며 등록된 제품 schema 외는 거부한다. `ATTACH`·extension load·임의 script 실행 경로가 없다.
2. 입력 bundle의 “정상/신뢰됨/허용됨” 표시를 실행 권한으로 수락하지 않는다. 새 library_instance_id와 복원 실행 epoch를 만들고, 실제 ConsentStore 실행 세대도 새로 발급한다. 이 세 ID는 다른 개념이며 backup 값을 재사용하지 않는다.
3. 가져온 grant/local endpoint 검증/permit/credential 재연결 상태는 비활성으로 만든다. 같은 PC의 credential 존재를 자동 재연결 근거로 쓰지 않는다. 자동 Job dispatch·provider probe·키 읽기·네트워크0이다. grant 기록 보존 여부와 실행 허용을 구별한다.
4. 복사된 미종료 Job은 자동 replay하지 않는다. 새 root의 독립 파일·writer lock·외부 경로/hardlink 없음이 검증된 **대상 복사본 소유권 확인** 뒤에만 imported-history로 분리한다. remote intent/불명확 outcome은 UNKNOWN/BLOCKED(REMOTE_UNKNOWN), local 미종료는 ABANDONED/BLOCKED로 정리하고 fence를 회수한다. 원래 프로세스의 종료를 증명했다고 쓰지 않는다. 대상 파일에 기존 reader가 없다는 확인 없이 active receipt를 0으로 바꾸지 않는다. 새 명시 실행에는 G-P07의 동일 계획/새 Job 규칙을 다시 적용한다.
5. 키 참조는 provider/endpoint/현재 복원 epoch에 대해 사용자가 명시 재연결한 뒤에만 읽는다. 새 grant·현재 요청 scope·새 captured permit은 별도로 필요하다. `ui/privacy.py`의 prepare 경로와 Gateway의 dispatch/write guard가 유지보수/복원 상태를 검사한다. 이 단위는 CredentialVault 구현/실제 vault 쓰기를 추가하지 않는다.

복원 실행 epoch·보류 상태는 `recoryn_maintenance`에 지속한다. crash 후 앱을 다시 열어도 새 동의를 요구하는 상태가 사라지지 않는다. 먼저 일반 생성자로 빈 DB/원장을 만들어 놓고 나중에 과거 이력을 확인하는 순서를 금지한다.

입력 bundle의 유지보수 operation/journal은 출처 이력일 뿐 target의 소유한 재개 증거로 쓰지 않는다. target은 새 operation ID와 실제 입력 fingerprint·물리 파일 map으로 자기 journal을 만든다. root의 보류 상태·현재 요청의 실행 epoch·선택한 권위 DB identity를 불변 admission snapshot으로 준비해 privacy/Gateway에 전달하고 write 직전 재검사한다. 오래된 UI의 relink 승인이나 기본 NORMAL 값으로 보류를 우회하지 않는다.

### 6.2 삭제·금융 권위 대조

| 경계 | 규칙 |
| --- | --- |
| 삭제 D/J | bundle과 사용자가 지정한 현재 권위 root의 유효 intent/tombstone을 대조. 동일 ID는 최대 세대 g, 새 tombstone은 과거 원본보다 우선. session generation>g·신원/형식 불일치는 충돌 |
| 삭제 완전성 불명 | 정상 inventory/자동 recover/adopt를 하지 않고 QUARANTINED. 0건 삭제 이력이나 빈 journal을 만들어 정상화하지 않음 |
| 비용 DB/witness 유효 | snapshot 시점의 정합 증거일 뿐 백업 이후 과금까지 최신이라는 증거는 아님. DB+witness가 함께 과거로 복사된 경우를 인증하지 못하는 한계 유지 |
| 현재 비용 권위가 더 최신 | request/event의 동일성·후속 정산을 대조. 같은 요청의 유효 UNKNOWN60→SETTLED40을 중복 합산하거나 금액 max60으로 덮지 않음. 현 권위의 확정 정산이 우선 |
| 비용 이력 없음/미포함/충돌 | confirmed/reserved/UNKNOWN·LEGACY_UNSCOPED를 보존하고 G-P06의 신규 지출을 **strict/일반 모두 보류**. USER_CAP으로 우회하지 않음 |
| 키/권한 | 원장 정합이 동의나 키 재연결을 대신하지 않음. 새 scope 동의·epoch·키 연결을 각각 확인 |

현재 권위에 있는 새 intent/tombstone을 적용한 뒤에는 그 session의 과거 media를 target의 활성 경로로 복사·채택하지 않는다. 입력 backup 자체는 수정하지 않고 target에 더 강한 삭제 기록을 보존한다. 삭제 대상이 아닌 원본의 동일성 oracle와 의도적으로 미포함한 삭제 자료의 oracle를 구별한다.

새 target에 복사한 옛 ledger를 자동으로 새로운 지출 권위로 삼거나 재서명하지 않는다. 권고안은 사용자가 **현재 권위 security DB를 명시 연결**하는 것이다. package가 제시한 외부 경로를 따라가지 않고 사용자가 고른 로컬 DB를 다시 검증한다. 이 DB를 복제해 이중 예산을 만드는 대신 기존 Coordinator/witness 아래 하나의 권위로 사용한다. 같은 물리 파일 구성의 권위 DB도 logical role map으로 처리한다. 새 ConsentStore 실행 세대가 이전 context를 무효화할 수 있다는 사실을 UI에서 안내한다.

연결한 현재 원장과 bundle의 요청/event가 충돌하거나 권위 자체가 없으면 G-P06의 명시 재구성·정산 완료 전까지 보류한다. package hash·사용자 cap·일반 모드 선택만으로 이력을 완전하다고 표시하지 않는다. 임의 통화 변환·누락 요청 삭제·노출액0 초기화·자동 환불·자동 합산은 없다. 모든 경우에 원격 기능까지 곧바로 복구된다고 보장하지 않으며, 원장이 불명확해도 검증된 **로컬 데이터 보기/보존**을 금융 송신과 구별한다.

최종 publish는 target 자체의 안전 검사와 위 제한을 반영한 marker를 마지막에 기록한다. 결과는 READY_LOCAL, READ_ONLY_QUARANTINE, RECONCILIATION_REQUIRED를 구별한다. READY_LOCAL도 자동 전송 허용이 아니다. 새 root가 원래 root에 미디어를 다시 채택하거나 원래 삭제 journal을 지우지 않는다.

## 7. UI·CLI·오류

- 새 유지보수 UI는 일반 stores를 열기 전 status/dry plan을 표시한다. MainWindow에서는 진행 중 작업 종료 필요, backup 위치·포함 범위·미완료 자료·키/동의 재설정·삭제/원장 보류를 보여 준다. 승인 기본값은 취소이며 Esc로 시작하지 않는다.
- CLI 제안: `maintenance status`, `maintenance migrate --backup-output PATH`, `maintenance resume OP_ID`, `maintenance rollback OP_ID`, `backup --output PATH [--session ID]`, `restore BUNDLE --output NEW_ROOT [--authority-root ROOT]`, `import BUNDLE --output NEW_ROOT [--authority-root ROOT]`. 유지보수 명령 분기는 기존 `with Library(...)`보다 앞이다.
- CLI의 쓰기 명령은 dry-plan 후 명시 `--yes` 또는 대화형 확인을 요구한다. 자동 실행 환경에서 확인 부재는 안전 종료다. 기존 root 덮어쓰기/force-unlock/unsafe-ledger 플래그는 없다.
- exit0은 요청된 단계 완료, exit2는 유지보수 재개/권위 확인이 필요한 보류, exit1은 입력/검증 실패다. 완료된 backup과 복원 뒤 READY_LOCAL/권한 재설정 필요를 JSON의 별도 필드로 구별한다. 완료 후 취소는 이미 게시한 정상 artifact를 삭제하지 않는다.
- 폐쇄 코드: MIGRATION_REQUIRED, UNSUPPORTED_SCHEMA, SCHEMA_COMPONENT_MISMATCH, MAINTENANCE_BUSY, DB_BUSY, MAINTENANCE_RESUME_REQUIRED, MIGRATION_ROLLBACK_UNSAFE, BACKUP_INCOMPLETE, BACKUP_VERIFY_FAILED, UNSUPPORTED_IMPORT_FORMAT, RESTORE_DELETE_HISTORY_UNKNOWN, RESTORE_LEDGER_UNRESOLVED, RESTORE_KEY_RELINK_REQUIRED, RESTORE_AUTHORITY_REQUIRED, RESTORE_GRANT_INACTIVE. 실제 예외 본문·SQL·키·전체 경로를 라벨/로그에 넣지 않는다.
- 재실행/더블 클릭은 operation ID·plan digest·단계 CAS로 멱등이다. 입력 snapshot/authority가 바뀌면 재검토를 요구한다. 미해결 상태에서 종료해도 다음 시작은 NORMAL로 돌아가지 않는다.

## 8. 입력 공간·분모·독립 oracle

### 8.1 family와 분모

계획은 **9개 family, feasible 의미 행 3,407개**다. actual pytest node·실제 kill 횟수와 구별한다. DB 배치 D는 L=library-only, S=security-only, P=서로 다른 library/security 두 파일, C=같은 물리 파일이다. component-only store fixture도 H에 별도 둔다.

| family / ID | Ω와 입력 | feasible F | 기대·측정 |
| --- | --- | ---: | --- |
| D / G09-D-0001…0960 | 배치4 × 버전{legacy,현재2,미래3,부분,손상}5 × 동작{open,migrate,resume,backup,restore,import}6 × 지정 fault hook8 =960 | 960 | 상태/권한·원본 보존. 이 family는 **fault 정책 입력 cube**이며 실제 도달 hook 수를 별도로 기록 |
| K / G09-K-001…155 | 배치4 × 쓰기 workflow5 × 실제 중단 경계8 =160 | **155** | 물리 중단·재개·marker·DB/witness 정합. L의 witness 경계5개만 제외 |
| R / G09-R-001…960 | 배치{P,C}2 × 삭제 상태5 × 원장 상태6 × 키 참조2 × 옛 active grant2 × {restore,import}2 × {strict,일반}2 =960 | 960 | 새 권한0·삭제 부활0·원장 노출/보류 유지 |
| A / G09-A-0001…1024 | 안전 재개 전제7개 bool의2^7 × 기능{STT,요약}2 × {restore,import}2 × 예산 모드2 =1024 | 1,024 | 모든 전제 참일 때만 fake egress 허용, 나머지는 첫 write 전0 |
| B / G09-B-001…198 | 배치4 × 동작6 × busy경계{root,security coordinator,SQLite}3 × 해제{deadline전,동시,미해제}3 =216 | **198** | L에는 security coordinator 없음18개 제외. 미래/부분/손상 조기 거부는 D/H에 포함 |
| H / G09-H-01…24 | §8.4 인계/schema named24 | 24 | 구성요소 fingerprint·UNKNOWN/선택/legacy 보존 |
| P / G09-P-01…32 | §8.4 악성/불완전 package named32 | 32 | 경로·크기·schema·이력 실패와 원본 불변 |
| W / G09-W-01…30 | 배치4 × DB상태{WAL없음,commit이WAL에만있음,미종료쓰기txn}3 × 미디어{없음,봉인prefix,staging}3 =36 | **30** | S에는 미디어없음만 가능:6개 제외. 정상 snapshot의 논리 내용과 원본 hash |
| O / G09-O-01…24 | 배치{P,C}2 × 경쟁6 × 양순서2 =24 | 24 | §8.3 linearization·중복 방지 |
| **합계** | 960+155+960+1024+198+24+32+30+24 | **3,407** | 계획 수치이며 실제 실행0 |

D는 원하는 hook을 주입하도록 설정하는 요청 입력이다. 미지원/손상/legacy open처럼 앞에서 거부되면 뒤 hook은 도달하지 않는다. 이 행을 분모에서 지우지 않되 **해당 중단 지점을 실행했다고 세지도 않는다**. open/current no-op에는 쓰기 단계가 없다. 실제 경계 도달과 kill은 K에서 확인한다.

R의 삭제 상태5는 완전한 무의도/현재 새 intent/현재 새 tombstone/journal 유실/손상·미완성이다. 원장6은 검증된 동일 상태/현재 유효 후속 정산/누락 witness/DB-witness 불일치/LEGACY_UNSCOPED/NOT_INCLUDED다. 두 논리 DB가 모두 있는 P/C로 제한해 grant·ledger 조합을 실물로 구성한다. 거부 대상 package도 hash를 새로 맞춘 적대 입력으로 구성하여 manifest checksum만 통과시키는 validator를 검출한다.

A의 7전제는 (1)삭제 이력 확인, (2)현재 비용 권위 연결, (3)witness 검증, (4)노출/기간 정합 확인, (5)키 참조 재연결, (6)새 scope 동의, (7)현재 실행의 새 binding/permit이다. fake 가격/요청은 G-P06에서 검증 가능한 fixture로 고정하며 production 빈 catalog/strict 기본값을 낮추지 않는다. 비용 인자 외 전제가 맞아도 옛 permit이나 같은 PC의 키만으로 egress하지 못한다.

### 8.2 실제 중단 K의 경계와 제약

hook8은 BEFORE_PREFLIGHT, AFTER_PREFLIGHT, AFTER_DB_BACKUP, DURING_DB_WRITE, AFTER_DB_COMMIT, AFTER_PAIRED_WITNESS_STAGED, BEFORE_COMPLETE_MARKER, AFTER_COMPLETE_MARKER다. 이는 정렬된 숫자 시간열이 아니라 **의미가 있는 관측 지점 이름**이다. G-P06 전환의 witness 선행→commit 순서를 뒤집지 않는다. 일반 backup의 paired witness hook은 검증한 동일 witness 파일 staging이며 새 서명이 아니다.

쓰기 workflow5는 migrate/그 operation의 resume/backup/restore/import다. fixture는 정상 지원 schema·완전한 소유 journal과 자료를 사용해 각 hook에 실제 도달하게 한다. L에는 금융 witness가 없어 5 workflow의 witness hook이 불가능하다. 그러므로 `4×5×8−5=155`다. 다른 layout에는 검증된 witness를 둔다. legacy 비용 전환의 혼합 witness 실패는 H에 따로 두며 정상 fixture로 추정 수선하지 않는다.

소유한 자식 PID·원자 ready marker/Event로 경계를 확인하고 kill한다. 저장된 입력 DB/미디어/witness hash와 부모의 독립 기대 상태를 기록한다. 정상 backup의 commit된 WAL 행 포함, mid-DDL rollback/commit 후 멱등 채택, 완료 marker 없는 target의 비활성, 완료 후 취소/kill의 이미 완성된 artifact 보존을 확인한다. 모든 가능한 SQLite syscall/전원 장애 지점을 전수로 시험했다는 뜻은 아니다.

B의 제외18은 L의 security lock 부재 `1×6×1×3`뿐이다. W의 제외6은 S에서 미디어 있음2종×DB상태3이다. 서로 다른 family의 제외를 다른 cube에서 빼지 않는다. 조건이 틀린 입력/불법 전이는 F에서 제거하지 않는다. 실제 fixture 구성이 달라지면 구현자가 분모를 조용히 축소하지 않고 원인과 대안을 C00에게 보고한다.

### 8.3 경쟁과 oracle

O의 경쟁6은 (1)유지보수 진입↔새 Job 입장, (2)backup freeze↔삭제 intent commit, (3)권한 세대 회수↔옛 permit write, (4)coordinator 두 개의 resume claim, (5)키 참조 relink↔실행 세대 변경, (6)target publish↔사용자 취소다. 내부 순서를 지키는 두 단일 선형화 지점을 barrier로 두 방향 실행한다. 이미 first write가 handoff됐으면 UNKNOWN을 보존하며 새 write를 차단한다. active task가 남아 있으면 유지보수를 성공시키지 않는다.

- schema expected는 독립 표·지원 profile 상수로 손으로 고정한다. 제품 catalog/마이그레이션 SQL을 그대로 expected 생성기로 import하지 않는다. 예상 표·컬럼·FK·불변 trigger와 실제 PRAGMA/sqlite_master를 별도 대조한다.
- backup/복원 비교는 독립 SQL 정렬 덤프와 원본 파일 checksum을 사용한다. 변경 허용 항목은 관리 registry·새 library/실행 ID·권한 비활성·imported Job fence/대상 receipt뿐이며 명시 전후 표를 만든다.
- 삭제 oracle는 유효한 intent/tombstone 집합의 합집합·ID별 최대 세대다. 기존 tombstone의 원본이 활성 목록·recovery adopt에 나타나면 실패다. 손상/부재를 빈 집합으로 보충하지 않는다.
- 비용 oracle는 request/event identity로 중복 제거하고 상태별 exposure를 독립 집계한다. UNKNOWN60에서 유효 final40은 confirmed40/unknown0이며, 유실·충돌이면 노출을 줄이지 못한다. v1/v2 witness가 맞는지와 이력 최신성은 별도 bool이다.
- fake transport는 DNS/접속/본문 쓰기, fake vault는 read/write 횟수를 기록한다. restore/import 직후 및 필요한 전제 하나라도 빠진 요청은0이다. source/target 모두 새 동의 없이 회수된 context를 되살리지 않는다.
- case ID/tuple manifest를 별도 목록과 대조해 missing/duplicate/extra=0을 요구한다. 의미 행·실제 node·도달 hook·actual kill·재실행을 따로 집계한다. 전체 raw Ω 합3,436 중 제외29, F=3,407이며 이 합을 전체 프로그램의 전수 증명으로 부르지 않는다.

### 8.4 named 경계

H01~24: 01 빈 새 profile / 02 정상 Library1 / 03 security0 legacy / 04 같은 파일 roles / 05 jobs-only profile / 06 content-only profile / 07 checkpoint 표 지연 부재 / 08 summary_requests 키 보존 / 09 content 불변 trigger·선택 version / 10 consent v2 scope/policy / 11 v1 grants 미승계·정리 / 12 cost4표 완전성 / 13 v1 witness 선검증 / 14 혼합 witness 전환 차단 / 15 LEGACY_UNSCOPED 유지 / 16 구버전0/1 guard의 형식2 거부 / 17 health3표·UNKNOWN_TAIL / 18 legacy-only health / 19 삭제 최대 세대 / 20 미래 component 불변 / 21 소유 journal 있는 부분 commit / 22 journal 없는 부분 표 / 23 새 실행·imported Job reader 분리 / 24 재열기·resume 멱등이다.

P01~32: 01 절대 경로 / 02 drive-relative / 03 UNC / 04 device 경로 / 05 `..` / 06 ADS / 07 symlink / 08 reparse / 09 hardlink / 10 대소문자 중복 경로 / 11 Windows trailing dot·space 충돌 / 12 기존 WAV/export.json 형식 / 13 크기 한도 초과 / 14 절단 manifest / 15 중복 JSON key / 16 파일 hash 불일치 / 17 누락 DB / 18 snapshot에 불명확한 WAL 의존 / 19 누락 witness / 20 손상 witness / 21 component downgrade / 22 임의 trigger / 23 임의 view / 24 extension·script 유도 schema / 25 삭제 journal 유실 / 26 미완성 삭제 tmp / 27 tombstone ID 충돌 / 28 bool 삭제 세대 / 29 session generation>g / 30 package의 active permit 주장 / 31 키 참조 자동 연결 주장 / 32 상충 cost event다. 파일/개수/manifest/payload 한도는 기존 안전 한도를 존중하며 구체 상한±1을 해당 named 입력에 포함한다. 거부 후 source·현재 권위 자료는 불변이다.

## 9. 기존 시험·추가 계층

| 기존 node/범위 | 보존·보강 |
| --- | --- |
| `tests/unit/test_storage.py::test_future_sqlite_schema_is_not_changed`, `test_future_manifest_not_overwritten` | 미래 버전 보존, DB/media 버전 구별 |
| `tests/unit/test_jobs.py::test_future_schema_rejected_without_changes`, `test_sqlite_schema_is_shared_without_owning_session_or_user_version` | 새 CURRENT=2 기준, 미래 대표3. JobStore가 공유 버전을 독단 변경하지 않음 |
| `tests/unit/test_content.py::test_closed_and_future_schema_fail_closed` 및 user_version assertion | 현재2/미래3 구별, content/summaryRequests 참조·선택 보존 |
| `tests/unit/test_security.py::test_future_schema_is_not_mutated` | security-only/같은 DB 미래 보존, 기존99 대표도 유지 가능 |
| 같은 파일 ledger rollback/누락·손상 witness/중단 witness 시험 | source mismatch를 backup/restore로 재서명하지 않음 |
| G-P02 `tests/unit/test_consent_scope.py` MIG | 새 세대·v1 미승계·정책/부분 schema·공유 원장 보존. 이전 user_version1 보존 assertion은 G09의 명시2 전환과 구별 |
| G-P03/G-P04/G-P05/G-P06/G-P08 회귀 | 설정 키·원본/reader/live·삭제 세대·원장/이벤트·health 상세를 각각 인계 |
| 기존 process crash/storage integrity/공급망·경로 시험 | 원본 prefix/hash·미래/손상·경로 방어의 기존 범위 유지. G09의 실제 phase 실행 증거로 중복 집계하지 않음 |

이번 계약 작성에서 위 시험을 재실행하지 않았다. 신규 시험8파일을 제안한다: `tests/unit/test_schema_catalog.py`, `tests/unit/test_maintenance.py`, `tests/property/test_maintenance_case_space.py`, `tests/integration/test_migration_backup.py`, `tests/integration/test_restore_import.py`, `tests/integration/test_maintenance_crash.py`, `tests/ui/test_maintenance_ui.py`, `tests/e2e/test_cli_maintenance.py`.

실제 SQLite·작은 합성 PCM·임시 디렉터리·fake clock/transport/vault를 사용한다. busy family는 결정적 fake deadline과 실제 SQLite 별도 연결의 BUSY 대조를 구별한다. actual kill은 소유 자식만 사용하고 source/client가 만든 staging과 import target을 혼동하지 않는다.

## 10. mutation 계획

계획 **32개**, 실행0이다. pyproject/src/tests/scripts/packaging을 OS TEMP 사본에 복사하고 cwd/pythonpath/import origin을 확인한다. 정상본 목표 PASS 뒤 한 변이씩 적용하고 목표 assertion FAIL만 검출로 센다. 수집/import 오류·권한 실패·timeout은 invalid다.

| ID | 의도적 결함 | 목표 |
| --- | --- | --- |
| M01 | 미래 user_version을 현재로 덮어쓰기 | D/H 원본 bytes 불변 |
| M02 | 열린 생성자가 부분 표를 임의 CREATE | D/H22 안전 보류 |
| M03 | 같은 DB roles를 두 번 migration/backup | D/H04 physical snapshot1회 |
| M04 | active main 파일만 backup | W의 WAL commit 행 보존 |
| M05 | DB snapshot과 다른 cut의 witness 사용 | W/R paired 검증 |
| M06 | live writer/reader가 있어도 maintenance 완료 | O의 busy·새 입장 차단 |
| M07 | before-image 검증 전 DDL 적용 | K의 phase/source 복구 |
| M08 | commit 뒤 phase journal 누락을 재적용 | K/H24 중복0 |
| M09 | 두 DB 일부 commit을 NORMAL로 표시 | K/D 유지보수 재개 필요 |
| M10 | witness 불일치를 재서명하여 정상화 | H13/14·R 차단 |
| M11 | v1 grant를 v2 활성 권한으로 복사 | H11/A 새 동의 필요 |
| M12 | 새 execution generation 생성 생략 | R/A 옛 binding 거부 |
| M13 | 같은 PC 키 참조를 자동 연결 | A/P31 vault read0 |
| M14 | package active permit/정상 flag 수락 | P30/A first write0 |
| M15 | 현재 tombstone보다 옛 media를 우선 | R 삭제 부활0 |
| M16 | 누락 deletion journal을 빈 디렉터리로 보충 | R/P25 보류 |
| M17 | 삭제 세대를 max 대신 min으로 병합 | H19/R 기존 의도 유지 |
| M18 | UNKNOWN을0/RELEASED로 바꿈 | R 독립 exposure |
| M19 | 같은 request final event 중복 합산 | R 비용 중복0 |
| M20 | 현재 SETTLED40을 과거 UNKNOWN60과 단순 합 | R 유효 후속 정산 우선 |
| M21 | NOT_INCLUDED ledger를 빈 예산으로 초기화 | R/A 지출 보류 |
| M22 | 일반 USER_CAP이 이력 보류를 우회 | A 두 모드 모두 guard |
| M23 | health 요약만 backup해 상세/tail 누락 | H17/W 전체표 보존 |
| M24 | content_summary_requests를 누락 | H08 설정 키 보존 |
| M25 | imported reader active를 증거 없이 지움 | H23/O 대상 소유권 검사 |
| M26 | source root/기존 target을 덮어쓰기 | P/D 경로·원본 불변 |
| M27 | symlink/대소문자 경로 충돌 허용 | P07~11 root 이탈0 |
| M28 | hash/권위 검증 전 완료 marker 게시 | K/P 완료 오표시0 |
| M29 | deadline 동일 시점에도 busy 재시도 | B 유한 상한·변경0 |
| M30 | rollback으로 전진 witness를 과거로 복원 | H14/K 명시 정산 보류 |
| M31 | credential relink의 epoch 비교 제거 | O/A stale relink 거부 |
| M32 | 형식2를 구버전 쓰기 가능하게 유지 | H16 구버전 안전 거부 |

## 11. 정확한 후속 쓰기 범위·대안·수락

요청은 **32파일 = source18 + 신규 시험8 + 기존 시험5 + 이 문서1**다. 구현 승인·선행 push·C00 착수 신호 전에는 제품 파일을 수정하지 않는다.

| 구분 | 정확한 파일 |
| --- | --- |
| 신규 공통/유지보수5 | `src/recoryn/schema.py`, `src/recoryn/maintenance/__init__.py`, `src/recoryn/maintenance/migration.py`, `src/recoryn/maintenance/backup.py`, `src/recoryn/maintenance/restore.py` |
| 신규 app/UI2 | `src/recoryn/app/maintenance.py`, `src/recoryn/ui/maintenance.py` |
| 저장·Job·content 수정4 | `src/recoryn/storage/library.py`, `src/recoryn/storage/_coordination.py`, `src/recoryn/jobs/__init__.py`, `src/recoryn/content/store.py` |
| 보안 수정4 | `src/recoryn/security/_core.py`, `src/recoryn/security/consent.py`, `src/recoryn/security/ledger.py`, `src/recoryn/security/gateway.py` |
| UI/CLI 수정3 | `src/recoryn/ui/main.py`, `src/recoryn/ui/privacy.py`, `src/recoryn/cli.py` |
| 신규 시험8 | `tests/unit/test_schema_catalog.py`, `tests/unit/test_maintenance.py`, `tests/property/test_maintenance_case_space.py`, `tests/integration/test_migration_backup.py`, `tests/integration/test_restore_import.py`, `tests/integration/test_maintenance_crash.py`, `tests/ui/test_maintenance_ui.py`, `tests/e2e/test_cli_maintenance.py` |
| 기존 시험5 | `tests/unit/test_storage.py`, `tests/unit/test_jobs.py`, `tests/unit/test_content.py`, `tests/unit/test_security.py`, `tests/unit/test_consent_scope.py` |
| 문서1 | `docs/testing/g09-migration-backup-cases.md` |

capture/audio·원본 serializer·vault·provider/model·공용 설정은 범위 밖이다. 기존 fixture 추가 수정이 필요하면 실제 실패와 필요한 범위를 C00에게 먼저 보고한다. 유지보수/SQLite 처리에서 장치나 추론을 호출하지 않는다.

| 대안 | 장점 | 한계/권고 |
| --- | --- | --- |
| user_version1 유지·component 표만 추가 | 기존 guard 적응 작음 | 구버전 쓰기 차단이 약함. 형식2+component 목록 권고 |
| 매번 open 때 자동 CREATE/ALTER | 호출자 간단 | 부분 손상/미래 버전·사용자 승인 없는 변환 위험. 명시 유지보수 권고 |
| main DB 파일/폴더 단순 복사 | 초기 구현 작음 | WAL·witness·여러 DB cut·삭제/health 누락. SQLite backup+검증 bundle 권고 |
| 기존 root에 restore/merge | 기존 경로 유지 | 삭제/원장 rollback·ID 충돌·부분 publish 범위 확대. 새 target만 권고 |
| 복사한 원장을 새 예산으로 재서명 | 복원 직후 지출 가능 | 백업 이후 노출 유실·분기 예산. 현 권위 연결/명시 정산 보류 권고 |
| 전부 zip archive로 지원 | 운반 편의 | 추출 크기/경로/충돌 범위 확대. 이번에는 새 로컬 directory bundle로 제한 |

후속 실행은 offscreen·오프라인·bytecode 비활성·`-p no:cacheprovider`·OS TEMP 고유 basetemp를 사용한다. 신규8파일·변경5기존파일, storage/jobs/content/security 회귀, G-P02/P03/P04/P05/P06/P08, tests/ui 전체·CLI/project export, ruff check/format check·`python -m mypy src/recoryn scripts packaging`을 포함한다. 가능하면 정확한 선행 HEAD+승인 파일만 담은 사본에서 전체 오프라인 회귀를 한 번 돌린다.

수락은 정상본 PASS, semantic ID3,407 missing/duplicate/extra=0, 제외29 독립 감사, 실제 도달 hook/kill과 조기 거부 분리, skip0, mutation32의 목표 assertion 결과·invalid 구분이다. 신규8파일 합계가60초를 넘으면 축약 전에 측정값·원인·행 보존 최적화안을 먼저 보고한다. 실행 시간·node·의미 행·tree/file hash·전원 장애 미검증을 분리한다.

현재는 문서/소스 조사·계약·분모 설계만 수행했다. 제품 변경0·시험 재실행0·mutation0이다. C00 승인 요청은 (a) 형식2와 component 정본/32파일, (b) 명시 유지보수·quiescence·부분 commit 재개/제한 롤백, (c) SQLite backup과 full/project directory bundle, (d) 새 root에만 restore/import·키/권한/Job 분리, (e) 삭제 권위·현재 원장 연결과 UNKNOWN/미완결 보류, (f) 계획3,407행/32 mutation·회귀·시간 게이트다.


## §개정 요청(6072ef1·G-P06 재확인 tree·G-P07/G-P08 개정·G-P15 반영)

### 1. 대조 기준과 현재 수행 범위

2026-11-23 재대조. 원문 LF SHA 46e9cc60cc63becb415b75a820d53252959881ca4a16804ce9b2a2970f689412의 원본46,899바이트를 그대로 두고 이 절만 덧붙였다. 제품·시험 수정0, 제품 시험/새 mutation 실행0이다. 아래 수치는 실행 결과가 아닌 개정 계획이다. C00의 기존 (a)~(f) 승인과 G-P09a→G-P09b 분할 조건을 유지하며, 이번 제안의 확정·구현 시작은 별도다.

- 제품 근거는 git show 6072ef1:<경로>와 git show 840f5961:<경로>에서 읽었다. HEAD 6072ef1dfbb5c69490812ca1b103e248dbf78743에는 G-P04·G-P05·G-P05b가 포함된다. 작업 트리의 G-P15 제품 코드는 근거로 쓰지 않았다.
- G-P06은 재확인 중인 tree 840f5961이며 독립 검토 CLOSED나 push 완료로 세지 않는다. 앞 단위의 PASS 숫자를 이번 직접 실행 결과로 옮기지 않는다.
- G-P07 개정 LF aea79c0ef55e5f417641412107a1b585134b2f3d450ab470c508a3aaaed81b85, G-P08 개정 LF 8ee33b46612d7b1cf90c4ae078a10e08ace70ef9c5f39834b44f8771b86ee017을 대조했다. 각각 4,947/1,024행 계약이며 구현 증거가 아니다.
- 작성 중 G-P15 문서의 이번 읽기 snapshot은 LF 01e54b7c0661cbc128580f860ca8ad6edc2f856a14cbf285c36e347895213174. 특히 §14.1~14.3의 PART2 설명을 사용했다. 문서의 ‘구현함’·실측 숫자는 작성자 보고이며 이번 검증이 아니다. 최종 push API가 달라지면 다시 고정한다.
- 조사 snapshot과 git show 출력은 OS TEMP의 recoryn-g09-g10-reconcile-240c48374b38498eab5d5af8dfc220a1에 보관했다. 이 절은 원문 §2의 과거 작업 트리 관측을 새 기준으로 보강한다.

### 2. 구성요소·권위 목록 보강

| 실제 근거 | 인계·개정 요청 |
| --- | --- |
| 6072ef1:src/recoryn/storage/library.py:211~270 | 삭제 정본은 검증된 deletion-journal 전체와 deleted_sessions 전체의 합집합이다. journal에는 schema_version·session_id·generation·DELETE_REQUESTED와 파일명 일치 검사가 있고, .tmp/누락/손상은 빈 이력이 아니다. DB의 DELETE_PENDING·DELETED_LOCAL을 모두 보존한다 |
| 같은 파일:1111~1119, :1178~1184 | deletion_generation(ID)는 pending/완료의 최대 세대를 주지만 pending_deletions()는 완료 tombstone을 의도적으로 제외한다. pending 목록을 backup의 전체 삭제 inventory로 사용하지 않는다. maintenance 내부의 검증된 DB/journal snapshot으로 전체 이력을 읽고 G-P05 조회·재시도 API 의미는 유지한다 |
| 같은 파일:1343~1389, :1409~1446 | 첫 삭제는 journal/DB 의도를 먼저 남기고 live면 DELETE_PENDING으로 보류한다. 제거 성공 뒤에도 journal과 DELETED_LOCAL은 남는다. backup·restore·migration이 보류를 취소하거나 완료 tombstone을 청소하지 않는다. 재시도는 기존 expected_generation 계약이며 restore가 자동 재시도하지 않는다 |
| 840f5961:src/recoryn/security/ledger.py:152~190 | cost v2의 네 실제 표 security_cost_accounts_v2/security_cost_requests_v2/security_cost_usage_events/security_cost_meta_v2를 등록한다. 계정 blocked·기간/통화/version, request별 quote·dispatch_id·state/금액, usage의 event identity/version, migration_state·adopted_providers·predecessor_v1_state_digest를 모두 보존한다 |
| 같은 파일:180~210, :353~379 | meta의 clock_high_water_utc와 clock_reset_audit를 fingerprint/논리 snapshot에 포함한다. audit 없는 구 v2는 별도 알려진 legacy profile로 인증 후에만 명시 전환한다. reset 이력이 있으면 witness의 clock_reset_protocol_version=1도 필수이며 제거·임의 재서명·v1으로 재해석하지 않는다 |
| 같은 파일:233~267, :748~779 | clock reset은 명시 확인·감사 사건을 필요로 하며 reset 후에는 같은 provider/currency의 모든 기간 SETTLED를 현재 예산에 보수 포함한다. backup/restore/migration을 reset으로 취급하거나 high-water/audit를 0 또는 빈 배열로 만들지 않는다 |
| G-P08 §4.2·§개정 요청의 건강 복구/ACK | capture_health_runs/tracks/events 세 표와 schema_version=2, health_version, checkpoint_seq·영속 prefix·안정된 UNKNOWN_TAIL ID·미상 count를 보존한다. bounded sessions.capture_health/manifest는 상세 정본의 대체가 아니다. legacy-only와 v2 부분 유실/미래 version을 구별한다 |
| G-P15 §14.1~14.3 | _intent_journal/_intent_names/_intent_stamp/_intent_settled, _coordination의 root별 약참조 callback은 **메모리 파생물**이다. persistent SQL index나 별도 삭제 권위 표를 새로 만든다는 설명이 아니다. backup 구성요소에 ‘색인 파일’을 발명하지 않는다 |

삭제 권위에는 원본 namespace도 필요하다. 새 library_instance_id·복원 epoch는 실행 신원이며 과거 삭제를 피하는 새 session 신원이 아니다. source instance/동일 계보의 세션 ID·세대 매핑을 유지하고 현재 권위와 일치하는 namespace에서 최대 g를 비교한다. legacy의 출처 동일성을 확인할 수 없으면 임의 ID 변경으로 충돌을 없애지 않고 QUARANTINED로 남긴다. 현 권위의 완료 tombstone이 과거 media보다 우선한다.

### 3. backup·restore·import·migration의 보강된 불변식

1. full backup은 완료 tombstone을 포함한 DB/journal 전체와 cost DB+witness·health 상세를 같은 정지 cut에서 받는다. 삭제 의도가 있는 미디어는 live 보류 잔여물까지 복제하지 않는다. partial file 제거를 복구 성공으로 채우지 않는다. project는 범위의 삭제 사실을 보존하되 전역 이력과 금융 최신성은 여전히 NOT_INCLUDED/미확인이다.
2. restore/import는 삭제 authority 합집합·최대 세대를 target publish 전에 적용한다. generation 충돌·missing journal/.tmp/손상은 기존 G-P05 닫힌 오류와 RESTORE_DELETE_HISTORY_UNKNOWN으로 표시하고, 빈 journal·빈 pending 목록으로 정상화하지 않는다. target에 새 grant·permit·endpoint 검증·key relink를 주지 않고 미종료 Job을 자동 replay하지 않는다.
3. cost는 같은 요청/event의 유효한 후속 정산을 우선하는 원문 규칙을 유지한다. UNKNOWN60→SETTLED40은 정상 정산에 따른 감소이며, 복원 때문에 UNKNOWN/지출을 삭제하는 것과 다르다. clone ledger를 새 authority로 승격하거나 USER_CAP으로 보류를 우회하지 않는다. 선택한 현재 권위가 source 요청/event를 누락·충돌하면 새 지출 보류다. 사용자가 DB를 고른 사실만으로 최신성을 인증했다고 표시하지 않는다.
4. 현재 권위에 clock reset 이력이 있으면 옛 backup의 빈 audit로 덮지 않는다. 정상 operation journal로 증명된 변경 외에는 raw high-water를 임의 max/min 병합하지 않는다(합법 reset은 낮출 수 있다). 권위·audit 계보를 확정하지 못하면 보류하며 새로운 witness를 만들어 풀지 않는다. 예: 이전/미래 기간의 확정액7+11, 현재 UNKNOWN5는 reset 뒤도 같은 provider/currency에 최소 확정18·미상5가 노출되어야 한다. 새 grant·새 root·새 실행·빈 cache로 이 금액이 줄지 않는다.
5. 알려진 schema에서의 **비용 시계/무결성 불능**과 원본/삭제/schema의 불능을 분리한다. G-P06 open_for_ui·privacy의 유료 전송 차단을 유지하여 비용 문제만으로 일반 앱 시작·녹음·로컬 기능을 막지 않는다(840f5961:ledger.py:214~229, ui/main.py의 생성 호출). 명시 유지보수 동안의 quiescence와 미래/부분 schema의 안전 보류를 ‘비용이 없으니 녹음 불가’로 혼동하지 않는다. 비용 component 격리와 전체 schema 불일치의 경계/전환 UI는 G-P09a/b 착수 때 C00 확인을 받으며 임의 자동 repair로 풀지 않는다.
6. G-P08 OPEN·UNKNOWN_TAIL·CLOSED에 남은 미상 gap을 그대로 복사한다. migration/backup만으로 건강 복구를 실행하거나 OPEN을 CLOSED/유실0으로 바꾸지 않는다. 별도 명시 recover에서만 G-P08의 안정된 tail·prefix를 반영한다. 건강 DEFERRED를 무시한 확정 성공·정상0 투영은 금지한다. source media bytes는 불변이다.
7. G-P15 파생 색인·mtime/stamp·callback·SealedChunk capability·writer/reader owner·claim은 직렬화/복원 권한이 아니다. 새 root에서는 기존 callback을 옮기지 않고 durable DB/journal을 전체 검증해 새 색인·root binding을 만든다. 같은 경로를 재사용해도 옛 stamp를 유효하다고 쓰지 않는다. 손상된 정본은 정상 cache나 ‘이름 있음’만으로 통과시키지 않는다. 관리 작업은 G-P15의 빠른 writer 판정 대신 전체 권위 검증을 사용한다.

### 4. 유지보수 ACK·공유 파일 순서

6072ef1:app/recording.py:61~68의 is_live는 현재 consumer 기준이다. G-P15 §3.4의 consumer+sealer+FIFO 수명으로 강화되면, consumer join만으로 backup/migration을 시작하지 않는다. 새 capture·Job·export·delete 입장을 먼저 닫고, source 해제 ACK와 모든 수락 저장 작업의 준비/게시/catalog 등록 ACK를 **모든 관련 lock 밖에서** 기다린다. sealer 실패·ACK_PENDING은 완료가 아니며, 정상 ACK 뒤의 INTERRUPTED 자료는 검증된 prefix로 보존한다.

G-P07의 입장/종료 ACK·명시 계속 규칙을 유지한다. 유지보수 이후 expected_job_id/version 없이 옛 BLOCKED/UNKNOWN Job을 재개하지 않는다. DB/journal 열거·해시·복구 검증은 GUI thread·capture gate·JobStore transaction 안에 넣지 않는다. 잠금 순서는 선행 단위 최종 계약을 다시 확인하고 coordinator/DB의 역순을 만들지 않는다.

6072ef1:storage/_coordination.py:23~55의 durable writer fallback, 840f5961:security/_core.py:219~231 및 consent.py:554의 0/1 guard도 형식2에 적응해야 한다. G-P15의 callback 성공이 maintenance/schema gate를 건너뛰는 조기 return이 되어서는 안 된다. callback 없음/해제/닫힌 Library fallback도 동일 guard를 거친다. 이 변경은 원문32파일의 _coordination.py·library.py·security 모듈 안에 포함한다. G-P15 기구 자체를 재구현하지 않는다.

G-P09a의 Library/maintenance core는 일반 owned-reader 등록·입장 gate를 제공하고, G-P09b는 기존 cli._export도 이 reader 수명에 연결한다. UI는 기존 worker→CLI 호출을 재사용한다. 그래야 G-P10 분할 구현 전에도 유지보수가 기존 내보내기의 실제 종료를 기다리며 두 단위의 의존성이 순환하지 않는다. 이후 G-P10은 같은 registry/receipt를 재사용하고 별도의 독립 reader 집합을 만들지 않는다. Job 표가 없는 standalone Library도 포함한다. 이는 원문32파일 안의 Library/CLI 연결이며 추가 source 파일은 필요하지 않다.

순서는 G-P02·G-P04·G-P05·G-P05b·G-P06·G-P07·G-P08 및 **G-P15 push 뒤** G-P09a→G-P09b, 각 단계 C00 신호로 제안한다. G-P08 개정 자체도 G-P15 ACK 위에서 연결한다. 착수 시 최종 tree·32파일 hash·삭제 권위 API·sealer ACK·형식 guard·cost witness 규격을 재고정한다.

### 5. 경우의 수·mutation 개정 요청

원문의 raw3,436−제외29=F3,407은 직접 산술 대조했고 기존9가족을 줄이지 않는다. 다음5가족405행을 더해 **14가족 F3,812(raw3,841−제외29)**을 제안한다. 모두 명시한 대표 경계의 곱이며 전체 프로그램의 직적 전수라고 주장하지 않는다.

| 신규 가족 | 입력 분할 | feasible 행 |
| --- | --- | ---: |
| J | 삭제 이력8 × 동작4(migrate/backup/restore/import) × library 배치3(L/P/C) | 96 |
| C | cost profile10 × 위 동작4 × security 배치3(S/P/C) | 120 |
| I | 파생 cache 상태5 × 동작5(open/migrate/backup/restore/import) × library 배치3 | 75 |
| Q | 저장/reader ACK 상태7 × 동작2(migrate/backup) × library 배치3 | 42 |
| T | health 상태6 × 동작4 × library 배치3 | 72 |

- J8: 무의도, DB-only pending, journal-only intent, 같은 g의 D/J pending, 완료 tombstone+같은 g journal, D/J 세대 불일치, session generation>g, 손상/미완성 journal. journal 완전 부재는 기존 R/P25가 따로 담당한다. 완료 tombstone의 pending 목록0건은 삭제 이력0건이 아니다. 독립 기대값은 D/J 합집합·ID별 최대 g와 고정 코드 표다.
- C10: 유효 v1-only, 인증 가능한 audit열 없는 구v2, v2 audit빈 배열, 미래 high-water+빈 audit, reset audit+과거/미래 SETTLED, reset audit+UNKNOWN, v2 부분표, DB/witness 불일치, reset witness 확장 누락, 미래 witness 확장. 실제 표와 witness bytes·revision·금액을 손으로 고정한다. 미래 high-water는 보존/유료 차단, reset 이력은 전기간 확정 보수 합산, 미상·충돌은 지출 보류다. schema 부재/미지원의 보류와 알려진 schema의 비용만 불능인 상태를 구별한다.
- I5: cache 없음, 정상 cache, 잘못된 빈 cache, 이전 root/epoch의 cache/callback, stamp 정상처럼 보이지만 journal 내용 손상. fixture의 durable D/J를 독립 정본으로 두며 새 target에 cache를 이식하지 않는다. source의 fast path를 expected로 다시 호출하지 않는다.
- Q7: consumer 활성, consumer 종료+sealer 활성, consumer 종료+미처리 FIFO, source 해제 미확인, 저장 실패+종료 미확인, source/consumer/sealer 전체 성공 ACK, 활성 export reader(다른 저장 작업은 종료). 전체 성공 ACK인6번째만 유지보수 진입 성공이며 나머지6은 BUSY/보류·source 불변이다. ACK를 확보한 실패 세션의 정상 복구는 기존 K/H에서 별도 다룬다.
- T6: legacy-only, 유효 OPEN+prefix, CLOSED+미상 gap, OPEN+이미 있는 안정 tail, 등록 v2의 부분/손상 자료, 미래 health version. 전자는 자료 그대로 보존, 후자2는 지원/완전성 보류이며 legacy0으로 fallback하지 않는다. 정상화 시 media hash·건강 상세 행·tail ID·None 유실량을 독립 덤프로 비교한다.
- 새 가족의 정상 입력이 blanket reject로 통과하지 않도록 유효 무의도/clock정상/전체 ACK/CLOSED 사례의 성공도 요구한다. 제품 분류기·catalog·렌더러로 oracle를 생성하지 않는다. 고유 ID/tuple manifest의 missing/duplicate/extra0, 실제 hook 도달·actual kill 분리는 원문 그대로다.

기존 mutation32에 **9개를 추가해41개**를 제안한다: M33 pending 목록을 전체 삭제 권위로 사용(J), M34 audit열/내용 삭제(C), M35 migration/restore가 high-water를 현재시각으로 덮음(C), M36 reset 후 전기간 확정액을 현재기간으로만 축소(C), M37 cache/stamp/callback을 target 권위로 복원(I), M38 consumer ACK만으로 quiescence 성공(Q), M39 reset witness 확장 누락을 재서명 수선(C), M40 health 미상/DEFERRED를 CLOSED·0으로 바꿈(T), M41 기존 export를 일반 reader registry에서 누락해 maintenance를 통과시킴(Q). 정상본 PASS 뒤 TEMP 사본의 목표 assertion 실패로 검출하고 수집/권한/timeout은 invalid다.

### 6. G-P09a/b 경계·분모 배분 제안과 결정 요청

원문 **32파일은 유지**한다. C00의 ‘착수 때 정확한 파일 경계·분모 배분을 먼저 확인’ 조건에 대한 준비안이며 지금 구현 권한이 아니다.

| 단위 | source 파일 | 시험·문서 | 파일 수 |
| --- | --- | --- | ---: |
| G-P09a | schema.py, maintenance/__init__.py·migration.py, app/maintenance.py, storage/library.py·_coordination.py, jobs/__init__.py, content/store.py, security/_core.py·consent.py·ledger.py·gateway.py(모두 src/recoryn 아래, 12개) | 신규5: unit/test_schema_catalog.py·test_maintenance.py, property/test_maintenance_case_space.py, integration/test_migration_backup.py·test_maintenance_crash.py. 기존5: unit/test_storage.py·test_jobs.py·test_content.py·test_security.py·test_consent_scope.py. 이 문서1 | 23 |
| G-P09b | maintenance/__init__.py·backup.py·restore.py, app/maintenance.py, ui/maintenance.py·main.py·privacy.py, cli.py(같은 source root, 8개) | 신규/공유6: property/test_maintenance_case_space.py, integration/test_migration_backup.py·test_maintenance_crash.py·test_restore_import.py, ui/test_maintenance_ui.py, e2e/test_cli_maintenance.py. 이 문서1 | 15 |

교집합은 facade/app source2+property/migration_backup/crash 시험3+문서1=6, 합집합23+15−6=32다. a는 before-image용 SQLite backup API를 migration core에 제공하고 b는 이를 공개 bundle workflow에서 재사용한다. b에서 추가 store 수정이 필요하면 착수 전에 범위 재확인을 요청한다.

원문 가족의 배분은 a: D480(open/migrate/resume)+K62(migrate/resume)+B99(같은3동작)+H 23행(H01~H22·H24)+O12(경쟁1/3/4)=676, b: 나머지2,731이다. 신규는 a:J24+C30+I30+Q21+T18=123, b:282. 따라서 **a799 + b3,013 =3,812**, 중복 소유 ID0이다. shared 시험 파일도 행 ID 소유자를 분리하고 b가 a 회귀를 재실행한 숫자를 새 분모에 더하지 않는다.

mutation의 주 소유자는 a: M01/02/03/06/07/08/09/10/11/12/17/24/29/30/32/33/34/35/38/39(20), b: 나머지21으로 제안한다. 각 단위에서 필요한 다른 쪽 회귀는 하되 같은 mutant의 여러 목표를 별개 검출로 세지 않는다.

a가 core API만 제공하고 b에서 UI/CLI를 연결하므로 **일반 사용자 경로의 legacy 강제 전환 활성화 시점도 착수 전에 C00 확인**이 필요하다. UI/CLI 복구 진입점이 없는 중간 push가 녹음 앱을 막는 상태로 통합하지 않는다. 최종 ‘legacy는 명시 migration’ 계약은 유지하되 단계별 연결 시점을 고정한다.

C00 결정 요청: ①전체 삭제 권위와 G-P15 파생 cache의 구분, ②G06 audit/high-water/witness·비용만 불능의 격리·건강 상세 인계, ③전체 저장 ACK/공통 gate와 G-P15 선행, ④F3,812·mutation41, ⑤32파일을 a23/b15(공유6)·분모799/3,013으로 나누는 안 및 활성화 시점. 신규8파일 합계60초 게이트는 유지하며 G06의120초 특례를 적용하지 않는다. 초과하면 축약 전에 측정값·안을 보고한다.

## §G-P09a 공개 GS11 인수와 X00 계약 결정 초안

기준은 공개 `494342a0a48322c09a1a4fd002ec1c3dec4cd47e`다. 기존 계약 LF SHA-256 `e961d3c177cc0f134d201887235075898168469d77431ba6626e6114e3a39d1b` 뒤에 덧붙인다. 최종 인수 e46be3b7, 독립 권위 검토 cfa939e7, 경우의 수 제안 cd8e9eef를 대조했다. 제품·시험은 변경하지 않았다. 이 절은 계약 결정과 범위 검토의 입력이다. 구현 배정은 독립 재확인과 선행 공개 CI를 확인한 뒤 별도로 낸다.

### D1·D2 공개 기준과 물리 형식

- a는 명시 plan/apply/resume/rollback 및 명시 current-only 입장을 제공한다. 알려진 일반 legacy 0/1 경로는 기존 호환을 유지한다. b는 실제 UI/CLI에서 일반 생성자보다 먼저 명시 유지보수·current-only 입장을 연결한다. 실행 중 유지보수 기록과 실패 폐쇄는 활성 operation을 소유하는 a에서도 적용한다.
- 물리 1의 등록표 부재 legacy와 등록된 현재 물리 2를 구분한다. legacy에는 전체 GS11 파생 DDL이 없는 알려진 옛 profile 및 아래 DDL 전체가 정확한 profile을 명시한다. 부분·틀린 DDL과 registry 없는 물리 2는 정상 입장을 거부한다. 등록된 물리 2에서 파생 DDL 전체 혹은 일부가 유실된 경우도 현재 형식 입장을 거부한다. 정확한 파생 DDL을 갖춘 입력의 빈 행 또는 잘못된 행은 원본 증거를 확인한 승인된 쓰기 단계에서 재구축할 수 있다. 명시 preflight에는 이 재구축을 적용하지 않는다.
- `storage_visible_sessions`는 `session_id TEXT PRIMARY KEY`와 sessions로 향하는 `ON DELETE CASCADE` FK를 갖는다. `storage_pending_deletions`는 별도 FK 없이 `session_id TEXT PRIMARY KEY`다. 이 두 TEXT 열에 별도 `NOT NULL` 선언이나 default는 없다. `storage_catalog_meta`는 `singleton INTEGER PRIMARY KEY CHECK(singleton=1)`, `version INTEGER NOT NULL`을 갖고 `INSERT OR IGNORE (1,0)`으로 시작한다. catalog version은 pagination 세대다.
- `storage_catalog_insert`와 `storage_catalog_delete`는 sessions의 해당 AFTER 사건에서 version을 증가시킨다. `storage_catalog_change`는 `state/state_version/generation` 중 하나가 실제 달라진 AFTER UPDATE에서 증가시킨다. `storage_visible_insert`는 sessions 삽입 시 해당 삭제 행이 없는 ID를 추가한다. `storage_visible_delete`는 deleted_sessions 삽입 시 visible에서 제거하고 pending에 삽입한다. 새 표 3개와 trigger 5개의 근거는 기준 `src/recoryn/storage/library.py:316–349`다.
- 삭제 정본은 canonical journal 전체와 `deleted_sessions` 전체다. 최대 세대와 완료 tombstone을 보존한다. 파생 행·메모리 receipt·cursor는 새 root로 권위를 옮기는 입력으로 세지 않는다. GS11의 런타임 raw 변경 거부를 유지하고, 새 대상의 최초 전체 검증을 열린 런타임의 무통지 변경 수용에 쓰지 않는다.

### D3 무쓰기 검사와 장기 작업 권위

- C0은 생성자 호출 없이 source 파일 세트를 검사한다. 열린 SQLite 연결의 원본 WAL·SHM·lock 생성, checkpoint, SQL 쓰기, 디렉터리 생성, rename, journal repair와 파생 갱신은 0이다. 원본 변경 없이 일관된 main/WAL 세트를 얻을 수 있을 때 TEMP 진단 사본을 이용할 수 있다. source가 진행 중이거나 일관성을 증명할 수 없으면 검사 보류를 반환한다. WAL 없는 immutable main 조회 결과로 profile을 확정하지 않는다. 원본 bytes와 실제 쓰기 시도 양쪽을 시험한다.
- canonical/staged 판정은 `storage/deletion_history.py`에서 디스크와 receipt를 변경하지 않는 공용 검사로 분리하는 안을 채택한다. 기존 Library도 같은 판정을 재사용하며 실제 actor 관측과 파생 갱신의 소유권은 Library에 남긴다. `schema.py`는 profile과 constructor-free source 검사를 소유한다. `app/maintenance.py`는 app 입장·실제 완료 관측을 조립한다. `maintenance/migration.py`가 operation proof, phase journal, before-image, DB별 commit 및 제한 롤백을 소유한다. 따라서 a23에 `storage/deletion_history.py` 한 파일을 포함하는 a24를 우선 검토 범위로 고정한다.
- 일반 GS11 receipt는 검사 시작 기준 30초와 dual clock 규칙을 그대로 적용한다. 유지보수는 승인된 operation의 현재 owner가 발급하는 작업 전용 process-local proof로 진행한다. proof는 operation ID·nonce·단계, root·물리 DB/role·witness identity, admission/owner/staged epoch, 전체 실제 ACK, prior negative floor 및 검증된 schema·D/J·staged·sidecar·witness 증거에 결속한다. 새 root·owner 교체·입장/actor 변경·취소·절전·시계 역행·단계 불일치가 확인되면 현재 proof로 진행할 수 없다. 재시작은 영속 journal에서 재개 자료를 읽고 현재 소유와 증거로 새 proof를 발급한다.
- 기존 10초는 입장 폐쇄 이후 ACK·소유 획득 예산이다. 정지 자료의 큰 작업에는 1회 실행 시도당 기본 3,600초의 별도 monotonic 협력적 기한을 적용한다. 경계에 이르면 다음 변경 단계에 입장하지 않는다. 이미 실행 중인 OS I/O는 실제 반환을 확인하며, 반환 후의 phase·증거로 보류 또는 재개 가능 상태를 판정한다. 3,600초는 강제 종료나 규모 성능의 보장이 아니다. 검증은 가짜 시계의 경계 증거와 실제 시간 결과를 구분한다.

### D4·D5 입장 폐쇄, 실제 ACK, 내구성 경계

- C1에서 새 capture/run·Job/재개·export/delete/recovery/history·송신 입장을 원자적으로 닫고 기존 수락분의 drain을 보존한다. 기존 capture·writer·sealer/FIFO 및 source ACK, 삭제 actor unwind, 등록 Job/processor/reader·전송 결과와 비용 정리, export와 history의 queued/running 작업을 실제로 회수한다. 신규 claim·게시·전송은 닫힌 상태를 따른다. 기존 종료 쓰기는 등록된 동일 run/attempt·epoch 범위에서만 허용하며 삭제 의도 fence도 적용한다.
- a는 명시 요청을 받을 때 live 또는 등록 미확정이면 `MAINTENANCE_BUSY`로 보류할 수 있다. 자동 stop을 성공 전제로 삼지 않는다. 이 경로도 모든 참여자의 신규 예약과 C1을 공통 소유 경계로 직렬화해야 한다. 같은 세션의 새 writer와 기존 drain을 구분할 실제 seam이 a24에서 증명되지 않으면 `app/recording.py`와 `storage/chunks.py`의 정확한 시작/첫 쓰기/계속 연결을 재배정 요청한다. a26은 검토 후보로 남긴다. b는 실제 UI/CLI/worker를 core에 연결하고 별도 실제 완료 시험을 책임진다.
- 소유 집합에는 동일 physical DB를 사용하는 모든 참여 root/store와 worker 시작 전 수락 예약도 포함한다. `close`·`cancel` 호출의 반환은 완료 요청 기록이다. 반환한 실제 작업의 ACK는 늦은 결과와 별도로 회수한다. 이미 완료한 요청/epoch/instance 결과로 새 작업의 단계·권위·ACK를 바꾸지 않는다. 실제 ACK와 신규 입장 폐쇄가 확인되기 전에는 before-image를 시작하지 않는다.
- ACK와 대량 검사는 GUI·runtime root mutex·Job transaction·보안 coordinator 밖에서 끝낸다. 장기 유지보수 소유 아래에서 정렬된 physical coordinator를 획득한다. per-DB commit에서는 이미 준비한 proof의 소유·epoch·단계 binding을 짧게 확인한다. DB 잠금 아래에서 runtime root lock을 역순으로 획득하지 않는다.

| 단계 | 확인과 허용되는 쓰기 |
| --- | --- |
| C0 | 승인 전 plan 및 source 검증. 원본 쓰기 0. |
| C1 | 사용자 승인 범위 확인, 입장 폐쇄, 기존 소유자의 실제 drain. 불명·기한 초과 시 before-image와 DDL 0. |
| C2 | 전체 실제 ACK 뒤 소유와 파일 identity를 결속하고 현재 전체 권위를 재검사한다. root·physical identity·role/version·권위·승인 범위 변경은 새 계획/승인을 요구한다. 증명된 기존 drain의 허용 tail은 동일 승인 범위에서 검증해 기록한다. |
| C2a/C3 | 승인된 operation을 PREPARING journal에 기록한다. before-image를 SQLite backup API로 만들어 검증하고 현재 정본·staged·witness를 다시 대조한다. |
| C4 | 준비한 proof와 전후 profile을 DB별로 확인하고 승인된 transaction만 commit한다. 다중 DB 일부 성공 또는 witness 전진 뒤 실패에는 영속 기록과 원본을 보존하고 재개/정산 보류를 표시한다. |
| C5/C6 | 소유를 유지한 상태에서 현재 전체 검증과 최종 짧은 identity/epoch/stamp 대조를 마치고 완료 marker를 마지막에 기록한다. 그 뒤 새 실행으로 stores를 연다. 새 정상 검사에서 일반 receipt 발급 조건을 충족할 때만 일반 권위가 생긴다. |
| CR | 재개·롤백도 새 소유·실제 ACK·현재 검증으로 시작한다. 새 삭제 세대/미완료 증거·witness 전진·미확정 외부 쓰기가 있으면 이전 이미지로 덮기를 거부하고 원본 및 진단 자료를 유지한다. |

- root의 `.deletion-stage-<32 ASCII hex>.json`, `.deletion-atomic-<32 ASCII hex>.json`, `.tmp-<32 ASCII hex>`는 대소문자 무시 ASCII 전체 일치로 판정한다. 알려진 orphan은 원위치 보존하고 정상 진행을 막는다. 읽기 전용 C0에서는 잘 검증한 부정 사실을 검사 결과에 제공할 수 있다. C0의 검사로 현재 runtime DB나 파생 상태에 쓰지 않는다. 현재 실제 actor 예외에는 공개 GS11과 같은 등록·instance·nonce·token·file ID가 모두 필요하며, 유지보수 C2는 actor 종료의 실제 ACK도 필요로 한다. 자기 writer가 아닌 inspector의 무단 청소는 0이다.
- 권위 결속은 협조하는 참여자의 배제와 명시한 관측 경계의 증거를 전제로 한다. 비협조적 외부 프로세스의 검증 뒤 변경과 무관측 ABA에 대한 파일시스템 원자 스냅샷과 전원 장애 내구성은 별도 검증 범위다.

### D6 경우의 수와 확인 조건

- a 정본 799와 C2 후보 24, b 정본 3,013을 분리한다. 이번 후보에서 별칭 AL12, 최종 관측 RC-01/03/04/05 네 행, 실제 history ACK HA8의 합계 24가 검토 대상이다. 따라서 장기 proof 및 무쓰기 보강을 더하기 전 a의 잠정 계획은 `799+24+24=847`이다. 어느 수도 실행 근거가 아니다.
- RC-02는 actor BUSY만으로도 거부될 수 있다. 실제 제품 경로에서 최종 cut/epoch의 독립 관측과 정상 대조를 노출할 수 있는 경우에만 포함한다. 이 행을 위해 BUSY 뒤 검사를 무조건 실행하도록 제품의 순서를 바꾸지 않는다. 누락 변이가 목표 assertion에서 검출되기 전에는 계획 분모나 변이 검출에 추가하지 않는다.
- 오래 걸리는 정지 작업의 양성 대조, 30초 일반 권위 만료, operation 기한·취소·owner 유실, source 쓰기 시도, C1 양순서와 기존 수락 원본 보존의 보강은 정확한 inputs/feasible/ID/목표 변이 및 a/b 소유를 추가 대조한다. 후보 신규 변이 4개는 기존 코드 위치와 중복을 제거한 뒤 확정한다. 신규 시험 묶음 60초 예산을 유지하며 fixture 준비와 실제 ACK 비용을 포함한다.

### 독립 검토 R1 반영 — G09D-01·02

- **G09D-01 획득 기한.** C1에서 입장을 원자적으로 닫는 시각부터 한 번만 10초를 잰다. 실제 ACK 대기와 모든 physical owner/coordinator 획득은 같은 기한의 남은 예산을 쓴다. 개별 lock의 기본 대기 시간을 더하지 않는다. 기한과 정확히 같거나 지난 시각에는 다음 획득 또는 변경 단계에 입장할 수 없다.
- **G09D-01 작업 기한.** C2에서 실제 ACK와 정지 소유를 확인한 직후, 첫 전체 검증 전에 현재 명시 attempt의 nonce와 3,600초 기한을 한 번 결속한다. 첫 전체 검사, before-image, DB 단계, 최종 검증 및 완료 marker 입장까지 이 기한에 속한다. 단계 이동·자동 재시도·SQLite backup progress는 기한을 갱신할 수 없다. 새 명시 apply/resume/rollback 요청만 현재 소유·증거와 함께 새 attempt 및 기한을 받는다.
- 만료·취소 시 신규 사용자 단계, DDL 및 완료 marker 입장은 0이다. 이미 허용된 I/O의 실제 반환은 회수한다. 입장한 마지막 marker I/O가 기한을 넘겨 반환해도 승인된 소유 아래 완료했고 출력과 marker가 유효하다면 완료 artifact를 보존한다. 남은 cleanup이 끝나지 않으면 그 정리만 보류로 기록한다. marker 입장 전 만료 또는 marker 실패·불명은 정상 완료로 표시할 수 없다. 필요한 작업 상태 기록, 실제 ACK 회수, 이미 승인된 종료 정리와 소유 해제만 계속하며, 자동 롤백·이전 witness 복원은 0이다.
- **G09D-02 접관 전 보류.** live·소유 미확정으로 기존 owner의 retire/중단을 시작하기 전에 보류하면 기존 owner가 핸들·수락 작업을 보유한다. 잠깐 만든 입장 예약이 있다면 같은 직렬화 경계 안에서 철회한다. before-image·DDL·작업 proof는 0이며, 취소된 epoch의 proof나 회수한 grant/permit을 되살리지 않는다.
- **G09D-02 접관 후 보류.** close/retire 또는 기존 drain을 시작한 뒤 timeout·취소·오류가 나면 G09 broker가 실제 owner·입장 gate·drain 등록을 계속 보유하고 호출 반환 뒤의 실제 ACK도 회수한다. 살아 있는 worker 아래에서 source를 닫거나 새 owner를 받지 않는다. 이미 수락한 원본·봉인·catalog 등록과 기존 outcome 정리는 동일 run/attempt 아래에서 끝낸다. 전체 실제 ACK와 안전한 source/operation 상태를 확인한 뒤에만 소유를 한 번 반환한다. 일부 DB commit·새 삭제 증거·witness 전진·현재 권위 불명 때문에 보류된 단계는 ACK 뒤에도 일반 NORMAL 입장을 열지 않으며 영속 journal과 현재 증거로 재개/정산을 요구한다.
- 보강에는 공통 획득 기한의 ACK 후 잔여분, 기한 직전·동일·직후, 단계/재시도의 갱신 거부, DB commit만 끝난 만료와 유효한 완료 marker가 늦게 반환한 경우, 접관 전·후 보류와 늦은 실제 ACK를 구분해 반영한다. 손 timeline과 실제 입장·반환·소유·원본 관측을 쓴다. 새 분모와 ID는 정확 범위 제안에서 확정한다.

### a26 경계와 902행 계획 — 독립 범위 검토용

G09D-01/02는 w5:pB의 독립 재확인에서 CLOSED였다. 기준은 공개 `494342a`이며 실제 구현 때 공개 GS05 기준을 새로 고정한다. GS05와 겹치는 `security/gateway.py`와 `security/ledger.py`, `app/desktop.py`의 source 시작/해제 및 삭제 확인을 새 기준에서 대조한다. 이 절은 계약 범위와 시험 계획이며 구현 배정 또는 실행 결과가 아니다.

a는 제품 15파일, 신규 시험 5파일, 기존 시험 5파일, 계약 1파일의 26파일이다. 아래 파일 목록은 역할과 함께 고정한다. `app/recording.py`는 worker/native 시작 전 start/resume 예약을 C1과 같은 경계에서 직렬화한다. `storage/chunks.py`는 같은 sid라도 새 writer의 첫 쓰기와 동일 run의 기존 drain을 구분한다. 두 접점에 기존 삭제 의도, payload/journal sync, source·sealer/FIFO ACK가 적용된다. b15 및 공유6을 유지하므로 고유 파일은 35다.

| 번호 | 파일 | 책임 |
| --- | --- | --- |
| 01 | `src/recoryn/schema.py` | 신규, 형식/role/profile 정본·constructor-free inspect/current-only |
| 02 | `src/recoryn/maintenance/__init__.py` | 신규, 명시 plan/apply/resume/rollback facade·타입 |
| 03 | `src/recoryn/maintenance/migration.py` | 신규, operation proof·단계 journal·이미지·commit/제한 rollback |
| 04 | `src/recoryn/app/maintenance.py` | 신규, 공통 입장/예약/실제 ACK broker 조립, UI 전체 배선 없음 |
| 05 | `src/recoryn/storage/library.py` | pure 판정 호출·투영/권위 publication 분리, 삭제/캡처/관리 gate·실제 owner 관측 |
| 06 | `src/recoryn/storage/_coordination.py` | 빠른 callback 및 닫힘/fallback의 같은 gate, 짧은 registry 관찰 |
| 07 | `src/recoryn/jobs/__init__.py` | 신규 claim/resume/게시와 실제 ACK/실패 정리의 구분·형식 guard |
| 08 | `src/recoryn/content/store.py` | profile/maintenance guard·기존 CAS/provenance 불변 |
| 09 | `src/recoryn/security/_core.py` | 물리 DB identity/role 및 형식 gate·coordinator 소유, C0에서 hold 금지 |
| 10 | `src/recoryn/security/consent.py` | profile/새 실행/입장·grant/permit 무승계, 종료와 신규 전송 구분 |
| 11 | `src/recoryn/security/ledger.py` | profile·witness/audit/high-water 보존, 기존 금융 정리 ACK |
| 12 | `src/recoryn/security/gateway.py` | 신규 송신 폐쇄·기존 handoff 결과/UNKNOWN·실제 connection 종료 관측 |
| 13 | `src/recoryn/storage/deletion_history.py` | 추가1, canonical/staged pure evidence와 현재 권위 publication 분리 |
| 14 | `tests/unit/test_schema_catalog.py` | 신규, literal DDL/profile·C0 입력 |
| 15 | `tests/unit/test_maintenance.py` | 신규, 단계/작업 proof·입장/ACK 상태·clock |
| 16 | `tests/property/test_maintenance_case_space.py` | 신규, 손 ID/tuple manifest·선택 실행 감사 |
| 17 | `tests/integration/test_migration_backup.py` | 신규, 실제 작은 SQLite/이미지·무쓰기·AL12 |
| 18 | `tests/integration/test_maintenance_crash.py` | 신규, 실제 소유/경쟁·RC4/HA8·단계 중단 |
| 19 | `tests/unit/test_storage.py` | 기존, 형식/소유/원본 oracle 보존·필요 fixture 최소 적응 |
| 20 | `tests/unit/test_jobs.py` | 기존, standalone/shared schema·실제 reader/fence oracle 유지 |
| 21 | `tests/unit/test_content.py` | 기존, 정확 profile·선택 CAS·불변 trigger 보존 |
| 22 | `tests/unit/test_security.py` | 기존, 미래/불일치·witness/UNKNOWN·비밀 경계 보존 |
| 23 | `tests/unit/test_consent_scope.py` | 기존, execution/scope/v1 미승계·schema fixture |
| 24 | `docs/testing/g09-migration-backup-cases.md` | X00가 확정할 계약/결과. 이 배정에서 직접 수정하지 않음 |
| 25 | `src/recoryn/app/recording.py` | 공통 입장에 worker/native 시작 전 start/resume 및 create_session→controller 등록 구간을 예약한다. root/instance/owner/run·epoch로 제한하고 실제 시작 실패 정리 또는 source·consumer·sealer ACK 뒤 회수한다. 기존 capture-control 사용과 무관 세션 제어 금지 유지. |
| 26 | `src/recoryn/storage/chunks.py` | 동일 sid에서도 실제 writer identity·epoch로 첫 쓰기와 기존 drain을 구분한다. 삭제 세대·PER_BLOCK payload/journal sync 및 catalog 등록 수명을 유지한다. _operation_lock→root→짧은 registry 순서와 root 밖 fsync/대기 경계를 보존한다. |

#### 시험 입력과 ID

이전 a 계획 847은 정본799, C2 24, AL12·RC4·HA8이다. RC-02는 독립 관측 접점이 생길 때까지 보류한다. 정확 범위 제안의 NW12·OP18·AD20(50행)과 기한·실패 출구 5행을 합해 **a902**로 검토한다. b3,013을 합친 3,915도 실행 전 계획이다. 아래에 명시된 55행의 공간에서 제외는 0이다. 중복 실행으로 새 ID를 늘리지 않는다. 제품 줄 근거는 공개 494342a로 고정한다.

#### 공통 손 oracle와 fixture

작은 합성 L 자료로 시작한다. 정상 session kept와 media bytes `b"\x01\x02"*480`, dead의 g7 완료 tombstone+같은 canonical journal, 건강 UNKNOWN_TAIL 한 행/lost_frames=None을 손 fixture로 만든다. 금융 경계 OP-10/AD-D의 Job remote 행만 P 배치의 witness/UNKNOWN60을 추가한다. 알려진 현재 profile은 **독립 literal DDL/행 목록**으로 만들고 제품 catalog/renderer/parser/fast path를 expected 생성에 사용하지 않는다. SQL 비교는 정렬된 논리 dump, 미디어/정본 파일은 bytes/hash와 위치로 비교한다. SQLite before-image의 페이지 bytes는 같아야 할 대상이 아니다.

C0의 source DB/main/WAL/SHM/lock/journal/media와 TEMP 진단 자료를 경로별로 나눠 쓰기 호출을 관측한다. 승인 전 source 쪽 mkdir/open-for-write/SQL mutation/checkpoint/rename/unlink 0이다. 입력 actor가 바꾼 정해진 bytes만 변경 허용 목록으로 분리한다. 같은 값 SQL·열었다 닫은 파일처럼 hash가 그대로인 쓰기 시도도 실패다. 파일 권한을 read-only로 바꿔 실패하게 한 것만으로 무쓰기 구현을 증명하지 않는다.

각 run/attempt/owner/operation의 실제 시작·반환·종료 ACK와 image-start/DDL/marker/gate-reopen 횟수를 독립 수집한다. Event는 잠금 밖이며 fake worker 객체의 상태값만 바꿔 실제 종료로 취급하지 않는다. 마지막 stamp observer는 pure 관측만 하고 제품 검증을 대행하지 않는다. 모든 작업은 test 소유 thread/future 및 작은 fake source/transport만 사용하고 finally에 유한 종료를 회수한다.

#### NW12 — 무쓰기 entry와 source cut

ID는 `G09a-X-NW-01P/01C ... 06P/06C`의 **손 literal12개**다. P=plan, C=current-only. 두 entry를 한 시험에서 돌려 하나의 pass로 세지 않는다.

| suffix 쌍 | 정확 source cut | 두 entry의 손 oracle |
| --- | --- | --- |
| 01P·01C | source root 자체 부재 | 검사 불가/없음, root·DB·lock·operation/image 생성0. 빈 profile 생성으로 승격0 |
| 02P·02C | main의 옛 version보다 높은 미래 version이 commit된 WAL에만 있음 | 미래 미지원·원본 source 쓰기0. main-only version으로 CURRENT/MIGRATION_REQUIRED/실행 허가0 |
| 03P·03C | 정지되고 소유가 확인된 현재2 자료, 필요한 commit은 WAL에 있고 source SHM은 없음 | source SHM/lock 생성0, 허용 TEMP 진단에서만 읽어 정확 current profile/facts. 결과는 read-only 검사 사실이며 normal receipt·permit 발급0. before-image/DDL0 |
| 04P·04C | 다른 실제 테스트 writer가 WAL transaction을 유지, 일관된 정지 cut 소유 미확인 | 검사 보류/BUSY, source 생성자/쓰기/강제 checkpoint·unlock0. 기존 writer를 kill/rollback하지 않음 |
| 05P·05C | 정상 legacy 파일 세트, `.security-lock`/root lock 파일 부재 | MIGRATION_REQUIRED 사실 반환, Coordinator.hold/lock O_CREAT0·source SQL/DDL0. 일반 legacy 호환 호출과 명시 current-only를 혼동하지 않음 |
| 06P·06C | 읽기용 source 세트를 TEMP에 준비하는 사이 별도 actor가 main 또는 WAL identity를 교체 | 일관 snapshot 채택0·검사 보류. actor가 바꾼 입력은 보존, inspector가 원상복구/새 파일 생성0. 진단 사본의 완료를 source authority로 승격0 |

03의 정상 양성은 정지/소유가 **독립적으로 입증된 fixture**만 사용한다. 현재 profile을 만든 setup 이후에는 source 파일을 더 만들지 않는다. SHM이 없으면 임의 immutable로 main만 읽는 구현은 02의 미래 oracle로 검출한다. 05는 같은 값 DDL/PRAGMA/lock 쓰기 시도까지 잡는 C0 대조이며 기존 C2-A03에도 같은 관측을 보강한다. 이 두 기존/새 입력은 파일 세트(미존재 lock을 명시한 축)와 entry가 다르다. exact closed code가 아직 없는 오류는 구현 전 타입 표로 확정하며, 광범위 Exception 발생만을 성공 oracle로 사용하지 않는다.

#### OP18 — 장기 양성과 30초/operation 기한 경계

ID는 `G09a-X-OP-01`~`18`의 다음 **18개 literal trace**다. clock span/precision=0의 결정적 fixture에서는 각 ns 수치를 손으로 고정한다. old ordinary receipt의 clock 조건은 별도의 정상 대조에서 관측한다. C1 gate가 닫힌 실제 일반 입장은 그 clock 조건이 True여도 계속 차단되며, C6의 새 정상 검사는 별도 발급이다. fake-clock 경계와 실제 wall은 별도로 보고한다.

| ID 끝 | 정확 trace | 손 oracle |
| --- | --- | --- |
| 01 | ordinary 검사 시작 뒤 29,999,999,999ns, operation 소유 정상 | old ordinary receipt의 clock 조건은 유효 경계 양성, operation의 허용 단계도 성공. blanket 거부 금지 |
| 02 | ordinary 시작 뒤 정확30,000,000,000ns, 정지/소유 proof 정상 | 일반 receipt 만료, operation은 자체 기한 안 계속·완료1. normal READY를 발명하지 않음 |
| 03 | ordinary 시작 뒤30,000,000,001ns, 나머지02와 같음 | 일반 만료·operation 성공·old receipt로 Job/송신 허가0 |
| 04 | C2 전체 읽기/검증이 실제 수행되고 가짜 시계42초 경과, known dead g7 유지 | 일반 publish receipt 없음과 negative floor 보존. 작업 전용 증거로 source/image 검증 후 정상 완료 가능, TTL/clock 고정0 |
| 05 | operation monotonic 3,599,999,999,999ns에서 다음 변경 단계 진입, 실제 반환도 기한 내 | 다음 단계/완료 양성, 기존10초/30초를 전체 작업 예산으로 오용0 |
| 06 | operation 정확3,600,000,000,000ns에서 다음 변경 단계 요청 | 다음 단계 쓰기/marker0, 영속 단계·image 보존·명시 재개 필요 |
| 07 | operation 기한+1ns에서 같은 요청 | 06과 같은 보류. 기한이 지난 것을 success/current-only 권한으로 바꾸지 않음 |
| 08 | 유효 기한 내 이미 시작한 backup I/O가 기한 뒤 실제 반환 | 실제 반환/핸들 종료 관측, 강제 kill/ACK 발명0. 다음 DDL/marker0, 검증 가능한 operation/이미지·원본 유지 |
| 09 | C3 뒤 같은 path의 owner/nonce가 교체, 옛 proof를 C4에 제출 | 옛 proof 진행0·현재 원본 보존, 새 소유/실제 ACK 전제 재요구 |
| 10 | P 배치에서 C3 뒤 witness의 physical identity만 교체 | 현재 proof 채택/완료0·재서명0·노출 UNKNOWN60 이상 보존, 과거 이미지로 덮기0 |
| 11 | 같은 operation proof를 잘못된 phase의 commit에 제출 | 해당 commit0, 이전 영속 단계 불변. 일치하는 다음 phase의 정상 대조는 기존 정상 trace 재사용 |
| 12 | C3 후 사용자 cancel, 아직 변경 단계 전 | 신규 DDL/완료0·ACK/소유 유지한 실제 unwind, canonical/media/witness 보존 |
| 13 | C3 후 suspend 통지로 owner/입장 epoch 무효 | 기존 proof 진행0·자동 resume0, 새 실제 소유/증거 필요 |
| 14 | operation 검사 사이 wall만 1ns 역행하고 monotonic은 1ns 전진한 관측 | 현재 proof로 신규 변경0·원본 보존, 일반 dual-clock 권한도 거부. 역행을 TTL 늘리기로 처리0 |
| 15 | 재시작한 실제 새 owner에 serialized old proof 전달, 이어 새 소유/ACK/증거로 명시 resume | 옛 proof의 단계 변경0. 새 process-local proof로만 검증된 journal의 다음 단계 재개1·중복 DDL0 |
| 16 | 정상 operation proof를 ordinary Job claim/permit 요청의 권한으로 제출 | 일반 snapshot 없으면 claim/새 송신0. operation 완료 양성을 유지하며 두 권한을 혼합0 |
| 17 | C1 ACK/소유 획득은9,999,999,999ns에 실제 완료, 이후 정지 작업42초 | 10초 획득 성공과 이후 큰 작업 양성, 단계마다 전체 기한 검증. 일반 receipt 만료를 정상화0 |
| 18 | C1 이후 정확10초에도 target 실제 ACK 미완료, 그 뒤 ACK 도착 | 첫 시도 before-image/DDL0·실제 ACK 회수/owner 수명 보존. 늦은 ACK를 첫 시도 성공으로 소급0, 사용자의 새 명시 요청은 가능 |

02~04는 fake clock으로 많은 실제초를 기다리지 않고 **실제 source 읽기·SQLite backup·commit/marker**를 수행하는 양성이다. 큰 H 자료를 fake-clock 성능으로 승인하지 않는다. 실제 42초 wall 예산을 성능 보장으로 요구하는 것이 아니며, 실제 wall은 해당 작업에서 별도로 측정한다. 15의 새 process/owner 검증은 구현 배정 후 실제 spawn import·소유를 확인하며 단순 `owner_id` 문자열 바꿔치기로 대체하지 않는다.

#### AD20 — 실제 입장 양순서와 기존 drain

다음20개의 손 literal ID를 계획한다. A=신규 예약이 C1보다 먼저, B=C1이 먼저. D의 A=실제 ACK가 C1보다 뒤, B=실제 ACK가 C1보다 앞이다. 시간 sleep이 아니라 해당 예약/실제 반환의 잠금 밖 Event로 선형화 순서를 만든다.

| ID | actor/동작 | A/B의 독립 oracle |
| --- | --- | --- |
| G09a-X-AD-A01A·A01B | 실제 RecordingService.start | A: worker 전에 예약이 보이므로 maintenance가 정지로 오인0, 기존 run은 원본 보존 후 실제 ACK. B: service worker/source 준비 시작0·신규 run0, 유지보수 정상 양성 |
| G09a-X-AD-A02A·A02B | 같은 service의 pause 뒤 resume | A: 새 run/epoch 예약이 보이고 옛 run ACK로 대체0. B: 새 epoch/worker/건강 run 생성0, 기존 녹음 원본 불변 |
| G09a-X-AD-A03A·A03B | 실제 JobStore.claim | A: 등록 attempt/reader 실제 종료 전 image0, fail/reader ACK 회수. B: claim/reader/dispatch0, 기존 QUEUED row와 fence 불변 |
| G09a-X-AD-A04A·A04B | 정확 expected_version의 실제 JobStore.resume | A: 예약 후 BLOCKED→QUEUED, 기존 fence=F·state_version=V이면 F+1·V+1. attempts 행과 attempt_count=N, 기존 attempt/checkpoint/history 보존. 실제 resume 전이 반환으로 이 작업의 ACK를 회수한다. 자동 claim·새 Job attempt·reader/worker·송신 0이며 C1 이후 별도 claim도 차단된다. B: resume 0. 기존 BLOCKED reason/version/fence와 과거 attempt/reader 상태 보존, 자동 replay 0. |
| G09a-X-AD-A05A·A05B | 같은 sid의 직접 ChunkWriter 첫 append | A: 실제 첫 쓰기 예약 소유 전부 추적, 종료/등록 전 image0. B: 새 staging/audio/journal/등록0. 이미 수락된 다른 writer의 drain ticket을 빌려 새 writer 시작0 |
| G09a-X-AD-D01A·D01B | actual consumer가 수락 PCM을 큐에서 아직 꺼내지 못한 run | A: C1 뒤 수락분 payload/journal sync와 봉인/등록 허용, ACK 전 image0. B: 완료 원본과 현재 증거 확인 후 image 가능. 양쪽 accepted PCM bytes=stored, 추가 submit은닫힌입장대로 |
| G09a-X-AD-D02A·D02B | 실제 sealer의 seal 이후/FIFO catalog 등록 전 | A: 이미 수락된 capability의 등록/실제 release까지 대기, `_seal_in_progress`/issued 수명표만 지워 ACK0. B: 이미 catalog 완료분은 중복 등록0, 정상 image |
| G09a-X-AD-D03A·D03B | 2개 fake source 중 두 번째 stop이 실제 반환 전 | A: 첫 source ACK만으로 image0, 두 번째 반환 뒤 current run sources_released·consumer/sealer 실제 종료 확인. B: 모두 종료 뒤 정상. 현재run 종료 중 들어온 수락 블록 보존, 이전run callback은폐기 |
| G09a-X-AD-D04A·D04B | 실제 삭제 actor가 기존 intent/staged의 정상 finally를 수행 중 | A: 정확등록 actor의 unwind/증거게시 뒤 ACK까지 image0. B: 현재g/tombstone·모든정본재검사 후진입. inspector cleanup0·새삭제입장0·원본부활0 |
| G09a-X-AD-D05A·D05B | 실제 Job reader+이미 handoff된 fake remote의 실패/UNKNOWN 정리 | A: 실패 반환/reader ACK/UNKNOWN60·witness 정리가 끝날 때까지 image0, gate가 종료 쓰기를 막지 않음. B: ACK뒤 동일노출보존·복제dispatch0. 새 network write0, ordinary grant·비용을 완화0 |

A01~02의 worker 시작 이전 예약 장벽과 A05의 첫 쓰기/계속 구분은 권고26의 핵심이다. D01~05는 core에 이미 등록된 실제 actor의 drain을 수동 제어하여 검증하며 **앱이 자동 stop을 성공시킨 것**으로 계산하지 않는다. 공개 명시 입장이 BUSY로 거부하는 선택도 허용하되, 소유 broker의 QUIESCING/drain seam에서는 실제 종료 쓰기가 보존되는 정상 대조가 필요하다. b의 실제 UI 버튼/CLI/native 서비스 전체 배선을 이20의 fake 통합으로 인증하지 않는다.

| 새 후보 | 단일 결함 목표 | 주 target/독립 FAIL | 중복 검토 |
| --- | --- | --- | --- |
| G09a-X-M01 | C0의 공용 source 검사 한 곳에서 Library(defer_history=True)를 호출 | NW05P/05C: source write-attempt=0 단언, 같은 bytes 여부와 별개 | C2-M02와 같은 실제 site면 원 ID에 합침. 새 무쓰기 reader의 다른 경로일 때만 별도 |
| G09a-X-M02 | 정상 operation도 ordinary TTL 만료를 이유로 거부 | OP02/04의 정상 완료1 및 image 논리보존 양성 | 단순 all-reject가 아닌 실제 권한 혼동. 일반 GS11 TTL mutant와 다름 |
| G09a-X-M03 | operation 기한 동일/초과에도 다음 변경 phase 진입 | OP06/07의 next-write0. OS 반환후기한누락은 OP08 | 기존 M29와 공통 deadline 한 site면 합침, 상수/검사만 다르다고 늘리지 않음 |
| G09a-X-M04 | C1 gate가 등록된 기존 drain/실패 정리까지 전부 차단 | AD-D01A/D05A의 수락 PCM 보존·실제 ACK/UNKNOWN60 정리 | M38(consumer만 보고 조기ACK)와 방향이 다름. 실제 같은 제거라면 DEDUP |
| G09a-X-M05 | service의 admission 예약을 worker.start 뒤로 옮김 | AD-A01A 또는 A02A의 start 전 실제 예약 관측, C2 image0 | 기존 M06/모든live검사제거와 같은 site인지 구현 뒤 확인. 공통 fail-closed가 결과만 가리면 예약 observer assertion 필요 |
| G09a-X-M06 | 같은 sid면 새 writer도 기존 writer drain ticket 수락 | AD-A05B의 새 staging/첫 write0·기존 D01A 정상 저장 양성 | G17a 삭제세대 fence 제거로 대체하지 않음. 다른실제writeridentity만 바꾸는 목표 |

#### 공통 기한과 실패 출구의 추가 5행

| ID | 사건과 손 oracle |
| --- | --- |
| `G09a-X-OP-19` | C1부터 실제 ACK가 8초를 사용한다. 다음 physical 획득은 같은 남은 2초만 받고 정확 10초에 추가 획득·before-image가 0이다. 먼저 얻은 소유는 안전한 종료 뒤 회수한다. |
| `G09a-X-OP-20` | 첫 전체 검사가 가짜 40초에 반환한다. 이후 단계 재시도를 거쳐 C2 기준 정확 3,600초에 다음 변경을 요구한다. attempt는 하나이며 첫 검사 시간 포함, 기한 갱신 0과 다음 쓰기 0을 확인한다. |
| `G09a-X-OP-21` | 최종 marker I/O를 기한 직전에 승인해 들어가고 기한 뒤 유효하게 반환한다. 출력·marker 보존, 완료 artifact 1, 남은 cleanup 별도 보류, 재작성·자동 rollback 0이다. |
| `G09a-X-OP-22` | C4 DB commit만 끝나고 정확 작업 기한에 C5 marker를 처음 요청한다. 기존 commit·단계 기록 보존, marker 입장·완료 0, 명시 재개 보류다. |
| `G09a-X-OP-23` | live owner를 발견하고 retire/stop 요청 전에 보류한다. 기존 owner·핸들·수락분은 유지하고 임시 예약만 같은 직렬화 아래 회수한다. before-image·DDL·proof 및 회수된 permit 재활성은 0이다. |

기존 OP-18의 timeout은 **접관 이후** trace다. 첫 요청이 반환한 뒤에도 broker가 gate·소유·drain 등록을 유지한다. 신규 입장·source close·before-image는 ACK 전에 0이다. 실제 late ACK를 회수하고 현재 안전 상태를 확인한 뒤에만 gate를 한 번 반환한다. 첫 시도 성공 소급과 자동 재시도는 0이다. C4 이후 불명/일부 commit이면 원래 부분 commit·부정 증거 oracle를 유지한다.

NW12의 primary는 `tests/integration/test_migration_backup.py::test_constructor_free_source_cut`이다. 같은 파일의 `test_operation_proof_scope`는 OP01~18, `test_maintenance_deadline_and_release`는 OP19~23을 맡는다. `tests/integration/test_maintenance_crash.py::test_admission_linearization`은 AD-A10, 같은 파일의 `test_existing_actor_drain`은 AD-D10을 맡는다. 각 행은 하나의 primary에만 속한다. 손 ID·tuple·node 목록과 정적 수집/선택 실행을 따로 대조하고 누락·중복·초과 0을 확인한다. 기존 호출·쓰기·소유 관측과 정상 양성 대조를 보존한다.

#### 추가 변이와 수락

원 a20, C2 후보6, HA 후보4, 정확 범위 제안의 X 후보6을 유지한다. 아래의 후보 4개는 각각 다른 위치에서 의미가 있을 때만 새 수에 포함한다.

| ID | 한 가지 결함과 목표 단언 |
| --- | --- |
| `G09a-X-M07` | 각 물리 획득에서 10초를 다시 부여하면 OP19의 동일 잔여 예산·획득 0 단언이 실패한다. |
| `G09a-X-M08` | 자동 단계 재시도에서 작업 기한을 갱신하면 OP20의 기한 불변 또는 다음 쓰기 0 단언이 실패한다. |
| `G09a-X-M09` | 늦게 성공한 유효 marker를 취소하면 OP21의 완료 artifact 보존 단언이 실패한다. |
| `G09a-X-M10` | 보류 반환 때 미종료 owner의 gate를 열면 OP18의 실제 ACK 전 신규 입장 0 단언이 실패한다. |

새로 도입한 시험만 60초를 적용하고 전체 검증은 정확 기준 및 26파일의 격리 사본에서 한다. 원 GS11·GS05, 기존 저장/Job/동의/비용/출처 회귀 및 core CI·coverage 7묶음·오프라인 wheel을 포함한다. 부모·실제 spawn import 출처와 원 범위 799/C2/AL·RC·HA·NW·OP·AD의 명시 ID를 각각 확인한다. 실제 코드 위치 중복·동치 확인 뒤 한 사본에 한 변이를 적용한다. 정상 통과 뒤 목표 call assertion 실패만 검출이며 import·수집·미도달·timeout·teardown은 별도다. 이 계획에서 실제 시험·Windows 실장비·서비스·전원 장애 검증을 실행하지 않았다.


# G09a-S1 구현 배정 — SQL 구조 기술자·정적 fingerprint

X00. 기준 `5dda55348d0eada1ac2f3fd031f781dd1a67d831`. 전체 G09a의 변경을 독립 검토할 수 있도록 **실행 권한이 없는 SQL 구조 기술자/정적 fingerprint 단위**를 먼저 구현한다. 제품 구현 배정은 이 단위에 한정한다. 나머지 a28 source·migration/관리 게시·실제 입장/송신·UI/CLI 구현은 별도 배정이다. 이 단위는 stub facade나 실패 시험만 선행 공개하는 것이 아니다.

## 1. 소유·정본

- 작성 pA, 검토 pB 또는 다른 비작성 Codex, 통합 X00. 자신 결과의 최종 승인0.
- **쓰기 두 파일만:** 신규 `src/recoryn/schema.py`, 신규 `tests/unit/test_schema_catalog.py`. 나머지 제품/시험/공용 문서/Git은 수정하지 않는다.
- X00가 제공하는 정본 `tests/fixtures/g09_schema_v1.json`은 읽기 전용이다. 독립 검토 report LF81f4417673681100a1c858a13bc6af6ca45f18a7e8975555c9c6d839e69c7644, inputs LF765e29ecb7d813d23f7dde0cf696fafa75a83706577383fc13e04dc3f4530902에서 hand shape15/target30·예정306337B·LF8b3611904a5db6371d2ebef831f7477a9cd8fa2c6b13ad55f0774417911dedbb·원 source 대조 일치를 확인했다. 제품은 이 fixture를 import/read해 기대 구조를 구현하지 않는다.
- 기존 G09 case596행/LF2974b644…를 보존한 X00의 끝 부록 중 S1 절을 계약으로 사용한다. 본문과 fixture의 component-local shape/wire는 이 단위의 완결 범위다. 전체 profile/권한/row/소유/회복이 지원됐다고 표시하지 않는다.

## 2. 기능·API

`schema.py`는 stdlib만 사용하고 다른 Recoryn 제품 모듈/보안/UI/maintenance를 import하지 않는다. 다음 두 API를 구현한다.

```text
expected_shape_wire(component: str, version: int) -> bytes
component_shape_wire(connection: sqlite3.Connection, component: str) -> bytes
```

첫 API는 제품이 소유한 고정 component catalog/version의 정규 bytes를 반환한다. 두 번째는 **이미 caller가 소유해 연 connection**에서 선택한 component의 실제 static SQL 구조를 읽어 `recoryn-shape-v1` bytes로 기술한다. 연결/파일을 열거나 닫지 않고 constructor·mkdir·트랜잭션 변경·DDL/DML/checkpoint·atomic 쓰기를 하지 않는다. known component 이외 이름은 조회 전에 거부한다. SQLite의 schema/PRAGMA 읽기만 허용하며 SQL 본문을 execute해서 의미를 추정하지 않는다. 생성한 SQL의 identifier는 catalog의 고정 known 이름을 안전하게 quote하고 임의 caller SQL/identifier를 실행하지 않는다.

정규성은 채택된 R2/pA 최종안 §3.4 및 golden shape_wire_contract 그대로다. column 순서/명시 NOT NULL·default/PK/FK·autoindex·CHECK·trigger token/문자열·partial index WHERE·collation·AUTOINCREMENT/rowid/strict의 의미를 보존한다. known keyword/공백/comment·known quoted identifier의 표기 차이는 정규화하되 literal case/Unicode·NOT/연산/괄호·collation을 합치지 않는다. unknown/미지원 문법/객체·누락 component 객체·모호한 기술은 **ValueError**로 거부하고 CURRENT/권한을 발급하지 않는다. 고정 source의 유효 문법을 blanket reject하지 않는다. component 투영은 전체 DB의 profile 인증이 아니다. 다른 component 객체의 존재는 현재 투영과 구분하고, 같은 component 이름의 잘못된 객체/관련 trigger를 무시하지 않는다.

파일 기반 constructor-free `inspect_schema`, 관리 JSON codec, plan/apply/resume/rollback·actual broker는 이번에 만들지 않는다. 뒤 단계의 함수를 stub/placeholder로 추가하지 않는다. 현재 module은 위 두 API와 그 구현의 완결된 helper/catalog만 제공한다. 일반0/1 생성자의 동작·프로젝트 import 경로는 변경하지 않는다.

## 3. 유한 경우의 수와 독립 oracle

S1 semantic ID는 **16**이다. 신규 SC12는 전체 a 분모에12를 더하는 별도 정상 입력이며 기존 FP4를 다시 가산하지 않는다. **현재 선택은 a980/b3014/합3994**다. 전체 선택 a968/b3014에 CA101을 전부 채택할 때1069/3014였고, SC12를 더하면 **a1081/b3014/합4095**가 된다. CA101의 독립 검토/후속 source 구현은 별도이며 이번에16 이외를 수집하지 않는다.

| ID | 고정 component / 입력 | 손 oracle |
| --- | --- | --- |
| G09a-X-SC-01 | library.core | golden의 exact hand wire/bytes/FP |
| G09a-X-SC-02 | storage.projection | 같음, table3/trigger5의 조건·순서 보존 |
| G09a-X-SC-03 | capture.health | 같음, table3/index2·실제 FK/UNIQUE |
| G09a-X-SC-04 | jobs.core | 같음, AUTOINCREMENT·partial NOT/attempt FK |
| G09a-X-SC-05 | jobs.receipts | 같음, explicit NOT NULL과 PK 구분 |
| G09a-X-SC-06 | jobs.checkpoints | 같음, UNIQUE(job_id,result_ref) |
| G09a-X-SC-07 | content.core | 같음, immutable trigger의 원 literal |
| G09a-X-SC-08 | content.summary_requests | 같음, default1·FK |
| G09a-X-SC-09 | security.consent | 같음, 정확 current local4/CHECK/PK |
| G09a-X-SC-10 | security.cost.legacy | 같음, 원 nullable/unique·가상 CHECK/FK0 |
| G09a-X-SC-11 | security.cost | 같음, meta9·usage/FK/CHECK |
| G09a-X-SC-12 | g09.management | 같음, 제안 metadata2표의 static shape·NULL CHECK |
| G09a-X-FP-01 | checkpoint의 whitespace/keyword case/known quoted identifier 정상 변형 | 원 hand490 bytes·FP08ad04f1…와 같음 |
| G09a-X-FP-02 | content RAISE literal만 소문자로 변경 | hand negative wire·FP47cb2a75…; 정상 catalog와 다름 |
| G09a-X-FP-03 | jobs dedup WHERE의 NOT만 제거 | hand negative wire·FP1a248d75…; 정상과 다름 |
| G09a-X-FP-04 | checkpoint result_ref+unique key의 BINARY→NOCASE | hand negative wire·FPeeef915f…; 정상과 다름 |

각 행은 실제 작은 TEMP SQLite connection에 **손 DDL**로 생성한다. 기존 source/golden의 hand 선언은 fixture 입력 근거로 쓸 수 있으나 제품 catalog/함수에서 DDL/expected를 생성하지 않는다. 정확 schema 객체의 raw SQL과 실제 authorizer/trace를 관측해 두 제품 API 호출 중 연결/쓰기/DDL/트랜잭션 변경0을 단언한다. 두 API 결과와 독립 hand bytes/FP를 비교한다. expected 계산에 제품 helper를 쓰지 않는다. SQLite fixture 생성은 API 호출 전이며 기술 단계와 분리한다. 16 ID의 literal/parameterized node가 각각1이며 static manifest와 선택 실행 집합을 별도 감사한다. 아직 없는 maintenance/CA/b의 skip·placeholder0이다.

변이 후보는 normal case의 component 누락/추가·column 순서·NN/PK·default·FK·unique key·CHECK·trigger literal/statement·AUTOINCREMENT·partial NOT·collation의 의미를 잃는 **서로 다른 실제 site**다. FP4의 한 결함을 여러 행에서 검출해 여러 kill로 세지 않는다. 구현 후 명명 표/patch·목표 ID·목표 assertion을 봉인한다. 정상 PASS→사본 한 변이→목표 call assertion FAIL만 kill, setup/import/timeout INVALID·다른 guard에 가리면 MASKED다. unsupported 입력 추가가 필요하면 ID/의미/변이 목표를 먼저 보고한다.

## 4. 검증·결과

시작 HEAD/쓰기2와 읽기 fixture hash 고정. `git archive 5dda553`+쓰기2+정본 fixture+현 case만의 새 OS TEMP 사본에서 cwd/rootdir/PYTHONPATH=사본, 부모/실제 spawn import 출처, no cacheprovider·고유basetemp·offscreen·ResourceWarning error·offline flags를 지킨다. 신규 단독16+감사·준비포함60초, 분모/수집/선택call 감사, 정상/단일변이 목표, 정적 ruff/format/mypy와 관련 기존 schema/security/storage/Jobs/Content 정상 회귀를 먼저 검증한다. 최종 정확 단위에서는 core.yml 전체/coverage85·7묶음/offlinewheel을 수행한다. 전체 회귀를 다른 작업과 중복으로 시작할 필요가 생기면 X00에 실행 상태를 보고한다.

실패/범위 밖 필요는 파일·원인·최소안 먼저 보고하고 기존 시험을 수정하지 않는다. 실제 모델/vault/GPU/네트워크/음성/유료/agent/pane/승인UI/Git쓰기0. 결과/로그는 `build/g09a-schema1/`와 새 TEMP에 보존한다. `G09a-S1 IMPLEMENTATION_READY / BASE / 두LF / fixtureLF / 16 ID·시간·실제쓰기0·변이·회귀·정적/CI / 미검증`으로 보고하고 독립 최종 승인은 하지 않는다.


# G09a-S1 FIX1 — 실제 SQLite 기술 경계 네 반례

X00. 기준5dda553, 구 source LF5002fbe5526ab45edeb479bbacf1b1092d160a737933a912e79b90ced6bec14e·test LF718ccd8f3118064cb30540a411a39c02da1e904eeb79f300c811ed274132eb92를 고정한다. p8 격리 `build/g09a-schema1-review/r1-090da472fa/independent20.xml`에서 정상17 PASS와 독립20 중16 PASS/4 FAIL을 직접 확인했다. actual 실패 R16/R17/R18/R19가 아래4개의 입력이다. 원 증거는 보존하며 판정/계약을 완화하지 않는다.

## 1. 범위·선행 상태

- **쓰기 재개 두 파일만:** `src/recoryn/schema.py`, `tests/unit/test_schema_catalog.py`. fixture는 기존306337B/LF8b361190… 그대로, case는 X00 append만. 기존 S1 기능/16행·읽기쓰기0·public 두 API를 유지한다. 기타 source/시험·공유/Git쓰기0.
- 구 전체 CI는 X00가 자기 runner/core 네 프로세스의 실제 명령줄·UTC 생성시각·부모를 확인해 종료하고 **INCOMPLETE_SUPERSEDED_FOR_S1_FIX1**로 보존했다. 구 ruff/format/mypy/관련481은 구 입력 결과이고 전체PASS/coverage/wheel로 확대0이다. PowerShell Stop-Process 인프라 오류 및 날짜검사 미일치는 실제 product 실패와 구분했고, 마지막 CIM 종료/부재를 확인했다.
- p8의 알림 도구 승인 UI에는 입력하지 않는다. 원 TEMP 반례 파일/plan/XML을 읽기 근거로 재사용한다. 새 report/증거는 `build/g09a-schema1-fix1/`와 새 TEMP에 둔다. 원151개/원보고·19변이 증거 덮기0.

## 2. 수정할 실제 경계

1. `PRAGMA index_xinfo`의 실제 collation 철자가 `nocase`여도 알려진 NOCASE와 같은 의미다. 실제 기술·index cross-check에서 **known collation만** canonical 대문자로 맞춘다. 원 SQL 의미를 BINARY로 바꾸거나 임의 custom collation을 허용하지 않는다. column 선언/unique key 두 위치를 모두 검증한다.
2. 원 SQL DEFAULT 괄호는 wire에 그대로 남긴다. SQLite PRAGMA가 바깥 괄호를 생략하는 관측 때문에 유효한 `(1)`을 거부하지 않는다. SQL 기술과 PRAGMA의 일관성 검사를 명시 구분하고, fingerprint를 만들 때 constant folding/괄호 제거0이다. 다른 literal/default 오류를 무조건 통과시키지 않는다.
3. STRICT의 TEXT PK가 SQLite 내부적으로 NOT NULL이어도 **선언의 explicit_notnull=false**를 보존한다. implicit enforcement와 wire의 명시 NOT NULL을 혼동하지 않는다. WITHOUT ROWID/INTEGER rowid alias·PK/NN/FK/autoindex 기존 검사도 보존하며 새로운 지원 입력이 필요하면 먼저 보고한다.

root가 코드를 대신 고치지 않는다. 실제 최소 수정 위치·단일 변이 목표를 작성자가 확인한다. unsupported SQL을 blanket accept하거나 PRAGMA 검증을 통째로 제거하지 않는다.

## 3. 계약 행·손 oracle

기존16 ID와 노드를 유지하고 **G09a-X-FP-05…08** 네 행을 같은 `test_component_shape_wire` primary에 추가한다. S1 의미20·감사1이며 전체 선택 a1087/b3014에4를 더해 **a1091/b3014/합4105**, 명시 비교 목록245다. 미래 CA/운영 행을 이 시험에 수집/skip하지 않는다.

| ID | 실제 SQL 입력 / 독립 기대 |
| --- | --- |
| FP-05 | checkpoint `result_ref TEXT NOT NULL COLLATE nocase`. column/unique key 모두 NOCASE로 기술. 기존 hand FP04와 같은490B, FP `eeef915f23b6ccd2e5ccb0f38733493024f80a26a29fc9a22c0e99c7396a4a13` |
| FP-06 | column은 원 BINARY, `UNIQUE(job_id,result_ref COLLATE nocase)`만 변경. unique 두 번째 key만 NOCASE,490B, FP `d287ca74a47a529e15c839cc7bd4ddf2b7b6ede66409f31402e145c821dc160a` |
| FP-07 | content_summary_requests의 `DEFAULT 1`을 `DEFAULT (1)`로 변경. default tokens는 `[[p,(],[n,1],[p,)]]`,532B, FP `b383b3000188c84d7fe0f2626297da93b2b21df0aa951e7b79626b2812138c98` |
| FP-08 | jobs.receipts의 테이블 끝에 `STRICT` 추가. strict=true, explicit_notnull=false·원 PK/autoindex 유지,429B, FP `8720648ff93d08c82388945223ca41fc406329add1c40e3e2fe056df2b71061e` |

FP는 모두 `recoryn-shape-v1:` 접두사를 가진다. 실제 hand wire 전체는 root가 제품/API 호출 없이 기존 독립 literal에서 해당 값만 손 변경하여 generic JSON/SHA로 고정한 자료를 아래 부록에 싣는다. 제품 helper로 expected를 만들지 않고 build JSON을 runtime에서 읽지 않는다. source DDL fixture는 손 literal이며 실제 API 호출 동안 authorizer/trace·files/txn/changes/caller ownership 검사와 원 oracle를 유지한다.

새3개 logical fault 후보는 known pragma collation canonical화 제거(FP05 또는06 한 목표), DEFAULT 관측 괄호 일관성 보완 되돌림(FP07), STRICT implicit NN 구분 제거(FP08)다. 같은 collation site를 두 kill로 세지 않는다. 원19도 같은 최신 입력에서 재실행한다. 이전 거부를 되돌리는 변이는 제품 ValueError를 그대로 uncaught error로 세지 않는다. 실제 API를 한 번 호출하고 **지원 SQL이 거부되지 않아야 한다는 명시 assertion**이 실패한 경우만 목표 검출이다. 예상 밖 TypeError/fixture/import/timeout·다른 guard의 거부는 INVALID/MASKED로 분리한다. 정상 통과/단일 사본·단일 변경/정확 목표 call 원칙은 불변이다.

## 4. 재검증·보고

git archive5dda+최신 두파일+고정fixture+새case만의 OS TEMP, cwd/rootdir/PYTHONPATH/부모와실spawn·고유basetemp/offscreen/no-cache/ResourceWarning error/offline 유지. 신규21/의미20 감사·준비포함60초, 독립R16~19 원본실패→수정통과, 최신22개 예정 단일변이의 실제고유site/목표를 봉인·검증한다. 관련 기존5파일·정적3종을 같은hash에서 수행한 뒤 전체CI 실행 전 X00에 상태를 알린다. root가 정확새사본 full/coverage7/wheel을 조립하므로 중복 전체0이다.

구간 결과를 선택해 이전 입력과 섞지 않는다. 실제 실패/필요한 범위 추가는 파일·원인·최소안을 먼저 보고한다. `G09a-S1 FIX1 READY / BASE / 두LF / case·fixtureLF / 20 ID·시간·쓰기0·회귀·원후·변이·정적 / 미검증`으로 보고하고 독립 최종승인0이다. actual 서비스/vault/모델/장치/음성/유료/네트워크/추가agent/pane/승인UI/Git쓰기0을 유지한다.


```json
{
  "FP-05": {
    "expected_wire_utf8": "{\"component\":\"jobs.checkpoints\",\"format\":\"recoryn-shape-v1\",\"objects\":[{\"autoincrement\":false,\"autoindexes\":[[\"u\",[[\"job_id\",\"ASC\",\"BINARY\"],[\"result_ref\",\"ASC\",\"NOCASE\"]]]],\"checks\":[],\"columns\":[[\"job_id\",\"TEXT\",true,null,0,0,\"BINARY\"],[\"attempt_id\",\"TEXT\",true,null,0,0,\"BINARY\"],[\"result_ref\",\"TEXT\",true,null,0,0,\"NOCASE\"]],\"foreign_keys\":[[[\"job_id\"],\"jobs\",[\"job_id\"],\"NO ACTION\",\"NO ACTION\",\"NONE\"]],\"kind\":\"table\",\"name\":\"job_checkpoints\",\"rowid\":true,\"strict\":false}],\"version\":1}",
    "bytes": 490,
    "fingerprint": "recoryn-shape-v1:eeef915f23b6ccd2e5ccb0f38733493024f80a26a29fc9a22c0e99c7396a4a13"
  },
  "FP-06": {
    "expected_wire_utf8": "{\"component\":\"jobs.checkpoints\",\"format\":\"recoryn-shape-v1\",\"objects\":[{\"autoincrement\":false,\"autoindexes\":[[\"u\",[[\"job_id\",\"ASC\",\"BINARY\"],[\"result_ref\",\"ASC\",\"NOCASE\"]]]],\"checks\":[],\"columns\":[[\"job_id\",\"TEXT\",true,null,0,0,\"BINARY\"],[\"attempt_id\",\"TEXT\",true,null,0,0,\"BINARY\"],[\"result_ref\",\"TEXT\",true,null,0,0,\"BINARY\"]],\"foreign_keys\":[[[\"job_id\"],\"jobs\",[\"job_id\"],\"NO ACTION\",\"NO ACTION\",\"NONE\"]],\"kind\":\"table\",\"name\":\"job_checkpoints\",\"rowid\":true,\"strict\":false}],\"version\":1}",
    "bytes": 490,
    "fingerprint": "recoryn-shape-v1:d287ca74a47a529e15c839cc7bd4ddf2b7b6ede66409f31402e145c821dc160a"
  },
  "FP-07": {
    "expected_wire_utf8": "{\"component\":\"content.summary_requests\",\"format\":\"recoryn-shape-v1\",\"objects\":[{\"autoincrement\":false,\"autoindexes\":[[\"pk\",[[\"session_id\",\"ASC\",\"BINARY\"]]]],\"checks\":[],\"columns\":[[\"session_id\",\"TEXT\",false,null,1,0,\"BINARY\"],[\"settings_key\",\"TEXT\",true,null,0,0,\"BINARY\"],[\"request_count\",\"INTEGER\",true,[[\"p\",\"(\"],[\"n\",\"1\"],[\"p\",\")\"]],0,0,\"BINARY\"]],\"foreign_keys\":[[[\"session_id\"],\"sessions\",[\"session_id\"],\"NO ACTION\",\"CASCADE\",\"NONE\"]],\"kind\":\"table\",\"name\":\"content_summary_requests\",\"rowid\":true,\"strict\":false}],\"version\":1}",
    "bytes": 532,
    "fingerprint": "recoryn-shape-v1:b383b3000188c84d7fe0f2626297da93b2b21df0aa951e7b79626b2812138c98"
  },
  "FP-08": {
    "expected_wire_utf8": "{\"component\":\"jobs.receipts\",\"format\":\"recoryn-shape-v1\",\"objects\":[{\"autoincrement\":false,\"autoindexes\":[[\"pk\",[[\"request_job_id\",\"ASC\",\"BINARY\"]]]],\"checks\":[],\"columns\":[[\"request_job_id\",\"TEXT\",false,null,1,0,\"BINARY\"],[\"job_id\",\"TEXT\",true,null,0,0,\"BINARY\"]],\"foreign_keys\":[[[\"job_id\"],\"jobs\",[\"job_id\"],\"NO ACTION\",\"NO ACTION\",\"NONE\"]],\"kind\":\"table\",\"name\":\"job_create_receipts\",\"rowid\":true,\"strict\":true}],\"version\":1}",
    "bytes": 429,
    "fingerprint": "recoryn-shape-v1:8720648ff93d08c82388945223ca41fc406329add1c40e3e2fe056df2b71061e"
  }
}
```

## G09 잔여 a 코어 공용 규범 채택

X00가 기존 승인·독립 검토와 G09NR-01/02의 재확인을 인수해 아래 규칙을 후속 G09 구현의 유효 계약으로 채택한다. 이 절은 보존한 앞 본문·S1 부록 뒤에 추가하며, 충돌하는 과거 초안·미정 표기에는 아래 유효 규범이 우선한다. 아래 조립 본문의 “후보”, “정본 인수·독립 확인 대기” 표현은 조립 당시 이력이며, 이 채택 절이 규범의 현재 상태를 정한다. 실제 구현·시험·공개 상태는 개별 배정과 Git/CI 증거로 구분한다.

선택한 계약 분모는 a1091/b3014·합4105, 명시 목록245다. 이는 실제 전체 실행 PASS 수가 아니다. 기존3982+SC12+CA107+새FP4의 결속, 기존 재사용과 후보7 미승인 구분을 유지한다. 전체 a28/b15 계획은 개별 작업자의 쓰기 권한이 아니며 각 구현은 X00의 명시 배정과 비작성자의 독립 검토를 거친다.

근거는 정본 조립 독립 검토 G09-NORM-R1, 두 줄 수정 G09-NORM-FIX1, p8의 두 항목 RECHECKED·새 OPEN0 및 데이터 wire delta 독립 검토다. 공용 본문과 versioned 손 fixture만으로 규칙을 읽을 수 있어야 하며 ignored build의 과거 제안은 계보 증거로 한정한다. 이 문서 채택은 실제 migration/admission·OS 소유·ACK/CR·운영 배선·실장비 또는4105행 실행 완료를 인증하지 않는다.


# G09 잔여 a 코어 유효 규범 조립안

**NORM_ASSEMBLY / 조립 필수 미정0·정본 인수와 독립 문서 확인 대기 / 이번 제품·시험 실행 PASS0.** 공개 source 기준은 `5dda55348d0eada1ac2f3fd031f781dd1a67d831`이다. 이 본문은 `docs/testing/g09-migration-backup-cases.md` 끝에 옮길 후보이며 기존 본문·S1 부록을 수정하지 않는다. 아래 규칙·literal 표와 versioned `tests/fixtures/g09_schema_v1.json`이 규범 자료다. ignored build의 옛 proposal/review는 계보 증거이며 그것을 추가로 읽어야 규범이 완성되는 구조로 사용하지 않는다. 본 조립은 새 구현 배정·공용 계약 최종 승인·자기 최종승인이 아니다. SC12 primary와 exact data container는 X00의 확정 답변을 인수했다.

## 1. 적용 순서·정확 선택·소유

현재 X00 선택은 **a1091/b3014·합4105, 명시 비교 목록245**다. 원14 family3812(a799/b3013)+보강103=원 a902/b3013·3915, 이후 REG/ACK/FIN/CT/ID/FX46(a45/b1)와 추가21(a21)로 원3982가 된다. 여기서 **원3982 / SC12(a12) / CA101+FIX1 추가6(a107) / S1 FIX1 새FP05~08(a4)**를 분리한다. 합은3982+12+107+4=4105, 명시 목록은55+46+21+12+107+4=245다. FP01~04는 원3982 안의 재사용4행이며 SC12+기존FP4+새FP4의 S1 의미20에서 다시 가산하지 않는다. 감사1은 semantic 분모 밖이다. semantic 행·pytest node·수집 수·actual mutation site·실행 PASS는 다른 수이며 이 조립의 신규 실행·수집·PASS는0이다.

원596행/LF `2974b644cc6638ebed78d85a76f7e30ca3c99146b39ff5aa659894d2153215cd`의 C00 결정·미관리0/1 호환·a/b 활성화·금융/삭제/건강/ACK를 유지한다. 이후의 유효 순서는 MAP/소유/추가21/a28 → schema R2/G1U/read reason/retention → resource FIX1 → CR/CA-FIX1 → typed FIX1 → preview digest FIX2 → CA107/S1 FIX1 FP4 선택 → exact data container 결정이다. 옛 NOT_RUN·분모·pending·초안 상태는 당시 이력이며 현재 규칙이 아니다. 과거 결과를 새 source의 PASS로 이전하지 않는다.

| a28 소유 | 정확 경로 |
| --- | --- |
| source16 | `src/recoryn/schema.py`; `src/recoryn/maintenance/__init__.py`; `src/recoryn/maintenance/migration.py`; `src/recoryn/app/maintenance.py`; `src/recoryn/storage/library.py`; `src/recoryn/storage/_coordination.py`; `src/recoryn/storage/deletion_history.py`; `src/recoryn/storage/chunks.py`; `src/recoryn/jobs/__init__.py`; `src/recoryn/content/store.py`; `src/recoryn/security/_core.py`; `src/recoryn/security/consent.py`; `src/recoryn/security/ledger.py`; `src/recoryn/security/gateway.py`; `src/recoryn/security/credentials.py`; `src/recoryn/app/recording.py` |
| 신규 시험5 | `tests/unit/test_schema_catalog.py`; `tests/unit/test_maintenance.py`; `tests/property/test_maintenance_case_space.py`; `tests/integration/test_migration_backup.py`; `tests/integration/test_maintenance_crash.py` |
| 기존 시험5 | `tests/unit/test_storage.py`; `tests/unit/test_jobs.py`; `tests/unit/test_content.py`; `tests/unit/test_security.py`; `tests/unit/test_consent_scope.py` |
| 정본2 | `docs/testing/g09-migration-backup-cases.md`; `tests/fixtures/g09_schema_v1.json` — X00 작성 |

기존 b15는 case, app/maintenance, maintenance/{__init__,backup,restore}, cli, ui/{main,maintenance,privacy}, e2e/test_cli_maintenance, integration/{maintenance_crash,migration_backup,restore_import}, property/test_maintenance_case_space, ui/test_maintenance_ui다. 확장자는 각 제품/시험 `.py`이며 case는 위 경로다. a28/b15 공유6·고유37을 유지한다. 운영 추가5(`security/credentials.py`, `ui/ai_bridge.py`, `app/ai.py`, `jobs/runner.py`, `app/desktop.py`, 모두 src/recoryn 아래)로 b20을 만들거나 조건부 `src/recoryn/providers/_common.py`를 추가하는 것은 별도 scope다. a가 UI/main·CLI·runner·desktop을 수정하거나 통제 core fake로 실제 운영 bootstrap을 인증하지 않는다.

현재 S1 구현 배정은 `schema.py`와 `test_schema_catalog.py` 두 파일의 `expected_shape_wire(component,version)` 및 caller-owned connection의 `component_shape_wire(connection,component)`뿐이다. 연결 open/close·constructor·mkdir·DDL/DML·트랜잭션 변경0, CURRENT/권한0이다. 후속 facade/관리 codec/broker를 S1 stub으로 넣지 않는다. S1 진행 구현·시험·전체 CI는 이번 조립과 분리한다.

## 2. schema·profile·독립 bootstrap

### 2.1 metadata DDL와 행

```sql
CREATE TABLE recoryn_schema_components (
    component TEXT PRIMARY KEY NOT NULL,
    version INTEGER NOT NULL CHECK (version > 0),
    fingerprint TEXT NOT NULL,
    profile TEXT NOT NULL
);
CREATE TABLE recoryn_maintenance (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    library_instance_id TEXT NOT NULL,
    operation_id TEXT,
    epoch INTEGER NOT NULL CHECK (epoch >= 0),
    commit_state TEXT NOT NULL CHECK (commit_state IN ('NORMAL','DB_COMMITTED')),
    input_digest TEXT,
    CHECK ((commit_state='NORMAL' AND operation_id IS NULL AND epoch=0 AND input_digest IS NULL)
        OR (commit_state='DB_COMMITTED' AND operation_id IS NOT NULL AND epoch>0 AND input_digest IS NOT NULL))
);
```

추가 index/FK/trigger는 없다. singleton INTEGER PK에 명시 NOT NULL/default를 발명하지 않고 행 검사에서 정확 한 행/singleton1을 요구한다. library_instance_id는 durable dataset Id이며 process/run/issuer ID가 아니다. INTEGER는 exact int, TEXT는 문자열, NULL은 NULL로 검사하고 bool/REAL/숫자문자열을 강제 변환하지 않는다. epoch=0..2^63−1, component version=1..2^63−1이다. DDL·전체 registry rows·내부 version·현재 identity/journal을 각각 검증한다.

| pointer | 정확 의미 |
| --- | --- |
| ABSENT | metadata 표 자체 없음. 정확 legacy0/1 또는 검증된 legacy CR target. 외부 floor/history를0으로 바꾸지 않음 |
| FRESH | singleton1/dataset, NORMAL, operation_id NULL, epoch0, input_digest NULL. 실제 true-fresh·선행 FRESH_INIT·전체 profile/물리2의 원자 초기화만 |
| COMMIT(M,d) | singleton1/dataset, DB_COMMITTED, operation M, 고정 양의 E_d/I_d. 승인 변경·component rows·물리2와 같은 DB transaction에서 commit |
| 그 밖 | SCHEMA_COMPONENT_MISMATCH. 부분 metadata를 legacy로 fallback/자동 repair하지 않음 |

기존 source를 fresh라고 선언하지 않는다. logical operation으로 초기화하면 COMMIT을 쓴다. DB pointer는 전체 phase/disposition/output/완료를 나타내지 않는다. C0/C1/C2/C3 source metadata 선행 CREATE/UPDATE0이다.

### 2.2 static shape와 명명 profile

`recoryn-shape-v1` root는 exact `{component,format,objects,version}`다. UTF-8/no BOM/no LF·sort_keys·compact·ensure_ascii=False·allow_nan=False, FP=`recoryn-shape-v1:`+SHA256(wire)다. objects는(name,kind)순이다. table exact keys는`kind,name,columns,autoindexes,checks,foreign_keys,autoincrement,rowid,strict`, index는`kind,name,table,origin,keys,unique,where`, trigger는`kind,name,table,timing,event,update_of,when,body`다.

column은`[name,type,explicit_notnull,default_tokens_or_null,pk_ordinal,hidden_flag,collation]`, key는`[name,ASC|DESC,collation]`, autoindex는`[pk|u,[key,...]]`, FK는`[source_columns,target_table,target_columns,on_update,on_delete,match]`다. INTEGER rowid PK에 autoindex를 발명하지 않는다. CHECK/FK/autoindex 집합은 완전 배열의 canonical UTF-8 bytes순이며, 열/PK/FK 내부 열/index key/trigger 문/UPDATE_OF/표현식/IN값의 의미 순서를 유지한다. 중복을 지우지 않는다. 무조건 where/when·없는 default는NULL, 명시 DEFAULT NULL은`[["k","NULL"]]`다.

token은 exact `[tag,value]`이며 k=ASCII 대문자 keyword, i=known ASCII identifier/function, s=원 Unicode literal, n=`0|[1-9][0-9]*`, p=연산/구두점이다. 닫힌 comment/공백과 known quoted identifier의 표기만 정규화한다. literal case/Unicode/backslash·NOT·괄호·연산/IN 순서·collation을 합치지 않는다. 허용 expr는 known identifier/OLD·NEW.column, 정수/string/NULL, 괄호, length, 산술/비교·AND/OR/NOT·IS [NOT] NULL·IN 상수열, 제한된`NOT EXISTS(SELECT 1 FROM known_table WHERE predicate)`다. 미등록 문법/객체·모호한 기술은 거부한다. S1 기술 API는 ValueError, 후속 inspection은 명시 reason mapping을 따른다.

S1 FIX1의 FP05~08은 다음 실제 기술 경계를 보강한다. 알려진 collation의 SQLite 관측 철자 `nocase`는 column과 unique key 모두 canonical `NOCASE`로 맞추되 custom collation을 허용하거나 BINARY로 바꾸지 않는다. SQL `DEFAULT (1)`의 괄호는 wire token에 그대로 남기고, PRAGMA가 바깥 괄호를 생략하는 관측과의 일관성 검사만 구분한다. `STRICT` TEXT PK의 implicit NOT NULL은 선언의 `explicit_notnull=false`와 별개다. PRAGMA 검증을 통째로 없애거나 기존 WITHOUT ROWID/rowid alias·PK/NN/FK/autoindex 검사를 완화하지 않는다. 기술 가능한 변형이라는 사실은 기존 current profile의 fingerprint와 같다는 뜻이 아니다.

versioned golden은 **306337B / LF `8b3611904a5db6371d2ebef831f7477a9cd8fa2c6b13ad55f0774417911dedbb`**를 유지한다. components12/legacy_variants3/target_profiles30/lexical_examples4/G1U map20의 hand model·wire·FP·expected rows가 정본 data다. 제품은 시험 fixture를 read/import해 catalog를 구현하지 않는다. 시험 expected는 제품 enum/parser/catalog/expected_shape_wire에서 생성하지 않는다. capture snapshot/절대경로/로그/자기 hash는 fixture에서 제외하되 schema 의미인 capture.health/실제 열/index origin=c는 보존한다.

검사 순서는 독립 literal의 metadata DDL→전체 actual object partition/role/내부 행 version으로 유일한 명명 profile 결정→각 static shape와 고정 FP→그 profile의 expected registry rows와 observed 전체 집합 비교다. observed profile/FP를 expected 선택에 쓰지 않고 g09.management의 자기 row hash로 DDL을 인증하지 않는다. current2 required 유실에 legacy 부재 예외를 적용하지 않는다. 실제 owner/ACK/현재 권위는 별도이므로 schema 사실만으로 입장0이다.

L=library.core+storage.projection+capture.health, J=jobs.core+jobs.receipts+jobs.checkpoints, C=content.core+content.summary_requests, CONS=security.consent, COST1=security.cost.legacy, COST2=security.cost.legacy+security.cost, G=g09.management다. current target은 G를 포함한다. 명명30은 F2_J, F2_L/LJ/LC/LJC, standalone S의 CONS/COST1/COST2/CONS_COST1/CONS_COST2, 이 security5를 L/LJ/LC/LJC 각각에 더한20이다. row는 component명순`[component,version,FP,profile]`다. powerset·L없는 shared Jobs+security/bare Content를 지원하지 않는다. COST1은 인증된 v1의 읽기/보존 profile이고 G06 전 v2 예산/송신 권한으로 올리지 않는다. COST2의 실제 paired witness2/audit/high-water/UNKNOWN/LEGACY_UNSCOPED 검증은 별도다.

legacy 명명형은 Library H0/G0·H3/G0·H3/G3+trigger5, Jobs R0K0/R0K1/R1K0/R1K1, Library-backed Content summary0/1, CONS2 local3/current4, cost1/cost2 meta8/meta9, 무타입8열/앞3PK G1U다. H0/G3·부분 schema를 정상화하지 않는다. target의 health/projection/checkpoint/summary/audit는 필수지만 과거 상세건강/무손실·alias receipt·settings/history·삭제 권위를 발명하지 않는다. receipt는 실제 job ID만 backfill한다. CONS2 내부 schema2, cost2 내부/witness protocol2, health payload/run2는 물리 user_version/component version과 별개다.

G1U B안은 security subprofile의 명명 범위다. whole-file G1U-only 물리0/1, L/LJ/LC/LJC+G1U-only 물리1은 같은 구성+CONS2로, G1U+CONS2(+지원cost)는 같은 current consent/cost로 명시 이행한다. CONS2 없는 G1U+cost는 미지원이다. old grant를 새 허용에 복사0, backup/검증 뒤 옛 표 정리·새 실행/재동의를 요구한다. G1U-only role은 consent1-legacy, G1U+CONS2는 consent이며 source G1U 표/행 검증을 생략하지 않는다. C0의 ALTER/CREATE/witness 재서명0이다.

전체 삭제 권위는 기존 canonical deletion journal·세대·tombstone 계약을 따른다. `storage_visible_sessions`, `storage_pending_deletions`, `storage_catalog_meta`와 해당 trigger는 재구축 가능한 파생 색인이며 전체 삭제 권위가 아니다. 캐시 일치/빈 pending 표만으로 삭제 이력·부정 floor를 지우거나 허가하지 않는다. health UNKNOWN_TAIL·실제 원본/선택/Job 이력과 원 금융 노출을 보존하며 없는 과거 사건을 새 정상 이력으로 만들지 않는다.

## 3. 값 타입·공개/내부 API

후속 API는 규범 계약이며 공개5dda/S1 구현 완료 주장이 아니다. 의존은 schema→stdlib, maintenance 타입→schema, migration→schema/coordination/maintenance 타입, app facade→실제 store/security/migration이다. schema→maintenance/security/UI, coordination→facade, 타입 선언의 migration eager import0이다.

| 타입 | exact 값/field |
| --- | --- |
| SchemaKind | EMPTY/KNOWN_LEGACY/CURRENT/INVALID/UNSUPPORTED/INDETERMINATE |
| SchemaReason | NONE/MIGRATION_REQUIRED/SCHEMA_COMPONENT_MISMATCH/UNSUPPORTED_SCHEMA/SCHEMA_INSPECTION_UNAVAILABLE |
| ComponentFact / SchemaInspection | `(name,version,fingerprint)` / `(kind,reason,physical_version:int|None,profile_id:str|None,components:tuple[ComponentFact,...])` |
| ManagementObjectKind / SchemaWireError | BINDINGS/PLAN/RECORD/PROGRESS/OUTPUT/COMPLETE / ValueError 하위형, 내부 kind=MALFORMED/LIMIT_EXCEEDED |
| DatasetLayout / RolePath | `(primary:Path,roles:tuple[RolePath,...])` / `(role,path:Path)`; role=library/jobs/content/consent/consent1-legacy/cost. caller complete/required/관리root 인자0 |
| OperationKind / Phase | APPLY/ROLLBACK / PREPARING/IMAGE_VERIFIED/APPLYING/VERIFYING/VERIFIED |
| Disposition / Completion | RUNNING/NEEDS_RESUME/QUARANTINED/RECONCILIATION_REQUIRED / INCOMPLETE/COMPLETED/ROLLED_BACK |
| MaintenancePlan | `(operation_id,kind,dataset_id,reverses_operation_id,targets,commit_order,approval_digest,plan_digest)`; plan_digest는 hash core 밖 |
| MaintenanceResult / CurrentDataInspection | `(operation_id,kind,phase,disposition,completion,output_digest)` / `(schemas,maintenance)`; 권위/ACK0 |
| MaintenanceError(RuntimeError) | code/phase|None/disposition|None만 안전 표시. code=MIGRATION_REQUIRED/UNSUPPORTED_SCHEMA/SCHEMA_COMPONENT_MISMATCH/MAINTENANCE_BUSY/DB_BUSY/MAINTENANCE_RESUME_REQUIRED/MIGRATION_ROLLBACK_UNSAFE |
| MaintenanceProposal / ApprovalIntent | `(request_nonce,kind,reverses_operation_id,layout,source_snapshot,change_contract,approval_digest)` / **`(proposal_digest,request_nonce)`** |
| EffectKind / CredentialStage | BIRTH/WORK_ACCEPT/NETWORK_O/NETWORK_WRITE / I/U/r/READ_ACCEPT/O/WRITE |
| CleanupStage / State | LEASE/AUTH_COPY/TICKET_CLAIM/DISPATCH_CACHE/CONNECTION_CLOSE/REQUEST_END / NOT_ENTERED/ENTERED/RETURNED/FAILED |
| CleanupDiagnostic | `(stages:tuple[tuple[CleanupStage,CleanupStageState],...],code:closed_security_code|None,outcome_known:bool)`; sanitized 진단이며 actual ACK/nonce/handle이 아님 |

```text
schema.inspect_schema(path: Path) -> SchemaInspection
schema.expected_shape_wire(component: str, version: int) -> bytes
schema.component_shape_wire(connection: sqlite3.Connection, component: str) -> bytes
schema.decode_management(raw: bytes, *, kind: ManagementObjectKind) -> ManagementDocument
schema.encode_management(document: ManagementDocument) -> bytes
MaintenanceFacade.plan(layout: DatasetLayout) -> MaintenanceProposal
MaintenanceFacade.plan_resume(layout: DatasetLayout, operation_id: str) -> MaintenanceProposal
MaintenanceFacade.plan_rollback(layout: DatasetLayout, reverses_operation_id: str) -> MaintenanceProposal
MaintenanceFacade.approve(proposal: MaintenanceProposal) -> ApprovalIntent
MaintenanceFacade.apply(proposal: MaintenanceProposal, *, approval: ApprovalIntent) -> MaintenanceResult
MaintenanceFacade.resume(layout: DatasetLayout, operation_id: str, *, approval: ApprovalIntent) -> MaintenanceResult
MaintenanceFacade.rollback(layout: DatasetLayout, reverses_operation_id: str, *, approval: ApprovalIntent) -> MaintenanceResult
MaintenanceFacade.inspect_current(layout: DatasetLayout) -> CurrentDataInspection
MaintenanceFacade.current_data(layout: DatasetLayout) -> CurrentDataLease
CurrentDataLease.close() -> None
```

plan/inspect는 C0 source/관리 쓰기0이다. current_data는 별도 actual admission/use의 opaque handle이며 진단 DTO가 아니다. legacy는 MIGRATION_REQUIRED, EMPTY를 CURRENT로 승격0이다. close 요청/반환만으로 전체 자식 ACK를 발명하지 않는다. INPUT/approval core는 hash용 typed record이며 위6종 이외의 새 durable path를 만들지 않는다.

```text
coordination._reserve_birth(kind: ProducerKind, candidate: BirthCandidate, *, parent: _FactoryReceipt|None) -> _BirthReservation
coordination._acquire_use(reservation: _BirthReservation, *, remaining: float) -> _PreparedUse
coordination._revalidate_use(prepared: _PreparedUse) -> _BoundUse
coordination._admit_effect(use: _BoundUse, kind: EffectKind) -> _EffectPermit
coordination._validate_fast(permit: _EffectPermit, owner_nonce: str, kind: EffectKind) -> None
coordination._finish_effect(permit: _EffectPermit, completion: _ActualEffectReceipt) -> None
coordination._close_use(use: _BoundUse, receipt: _ActualCloseReceipt) -> None
coordination._prepare_freeze(seal: _CompletenessSeal) -> _FreezePreparation
coordination._commit_c1(preparation: _FreezePreparation, seal: _CompletenessSeal) -> _RetiringOwner
coordination._publish_lease_completion(receipt: _LeaseCompletionReceipt) -> None
migration._await_actual_drain(owner: _RetiringOwner, *, remaining: float) -> _DrainReceipt
migration._acquire_exclusive(owner: _RetiringOwner, drain: _DrainReceipt, *, remaining: float) -> _MaintenanceUse
migration._apply(plan: MaintenancePlan, *, approval: _ApprovalReceipt, attempt: _Attempt, use: _MaintenanceUse) -> MaintenanceResult
migration._resume(plan: MaintenancePlan, *, approval: _ApprovalReceipt, attempt: _Attempt, use: _MaintenanceUse) -> MaintenanceResult
migration._rollback(plan: MaintenancePlan, *, approval: _ApprovalReceipt, attempt: _Attempt, use: _MaintenanceUse) -> MaintenanceResult
migration._publish_management(target: _FixedManagementSlot, document: ManagementDocument, *, authority: _ManagementWritePermit) -> _PublicationReceipt
migration._discover(layout: DatasetLayout, *, discovery: _DiscoveryAttempt) -> _DiscoverySnapshot
migration._read_management(slot: _FixedManagementSlot, *, discovery: _DiscoveryAttempt) -> ManagementDocument
app._assemble_core(layout: DatasetLayout, *, factory: _CoreFactoryReceipt) -> MaintenanceFacade
app._assemble_operating(layout: DatasetLayout, *, factory: _OperatingFactoryReceipt) -> MaintenanceFacade
CredentialService._prepare_call(kind: EffectKind, *, stage: CredentialStage) -> _CredentialCall
CredentialService._owned_call(call: _CredentialCall) -> ContextManager[None]
CredentialService._register_live_lease(claim: ReadClaim, accepted: _AcceptedRead, lease: CredentialLease) -> _LiveLeaseRef
CredentialLease._completion_receipt() -> _LeaseCompletionReceipt|None
EgressGateway._finish_cleanup(request: _RequestOwner, primary: SecurityError|None) -> _RequestCleanupReceipt
```

opaque 권위 정의는 storage/_coordination.py에 두고 security 타입을 runtime import하지 않는다. actual issuer instance/nonce 표가 발급하며 같은 field/dataclass/context는 권한0이다. 기존 public constructor/ticket/CredentialService/Gateway 인자·release()->None·원 CAS를 유지한다. factory None은 unclassified 호환이며 CORE/OPERATING seal0이다. stage context의 nested/thread 밖 누출·재사용0이다. actual operating receipt는 b 소관이며 a에서 genuine current CORE seal도 operating 입장으로 올리지 않는다.

## 4. 관리 wire·고정 path·NULL

관리 JSON은 **raw bytes == typed canonical encoding**만 수락한다. UTF-8/no BOM/no 마지막 LF·sort_keys/compact/ensure_ascii=False/allow_nan=False다. 공백/키순서 차이를 정규화해 수락하지 않는다. duplicate/unknown/missing key·surrogate·NaN/float/bool/문자열 int coercion·목록 중복 자동 dedup0이다. SQL shape의 표기 정규화와 다르다. depth는 root container를 1로 세고 중첩 object/array마다 1을 더하며 scalar는 깊이를 더하지 않는다. 최대16이며17부터 budget 거부다.

Id=ASCII 소문자 hex32, Digest=소문자 hex64, Seq/Epoch=exact int0..9223372036854775807, COMMIT epoch는 양수다. Identity exact `{kind,volume_hex,file_id_hex}`는 FILE/DIR·hex16·hex32다. SafeName은 원 Unicode scalar의 Windows 합법 단일 basename이며 빈값/NUL/separator/drive/ADS/dot/dotdot/device/trailing dot-space를 거부한다. casefold/NFKC로 실체를 발명하지 않고 actual identity/parent/name/history와 기존 link 방어를 확인한다.

| object | exact keys / tag |
| --- | --- |
| bindings | `{format,version,catalog_id,generation,anchor_identity,namespace_identity,entries}`; recoryn-management-bindings-v1/version1, 두 identity DIR |
| entry | `{db_id,dataset_id,state,current,history,roles,primary,genesis,operation_ref,epoch_floor}`; state PREPARED/BOUND/RETIRED |
| current / history item | `{name,identity}` / `{name,identity,retired_by}`; retired_by는 operation_ref |
| primary | `{kind,anchor_identity,namespace_identity,catalog_id}`; kind LIBRARY_ROOT/DB_PARENT, path field0 |
| operation_ref | NULL 또는 `{operation_id,plan_digest,link_nonce}` |
| genesis | `{kind:OPERATION,operation_id,plan_digest}` 또는 `{kind:FRESH_INIT,intent_id,layout}` |
| fresh layout / target | `{primary,targets}` / `{db_id,dataset_id,anchor_identity,namespace_identity,name,roles,profile_id,pre_identity}` |
| epoch_floor / credit | `{kind:UNCOMMITTED}` 또는 `{kind:KNOWN,value,credits}` / `{operation_id,plan_digest,sequence,record_digest}` |
| plan | `{format,operation_id,kind,dataset_id,reverses_operation_id,targets,approval_digest,commit_order}`; recoryn-maintenance-plan-v1 |
| plan target | `{db_id,roles,physical_binding,local_binding,pre_profile,pre_pointer,pre_state_digest,target_profile,target_epoch,input_digest,post_contract,pre_image_slot,sidecar_slots}` |
| physical_binding / local_binding | `{anchor_identity,parent_identity,name,identity}` / `{anchor_identity,namespace_identity,catalog_id,db_id,link_nonce}` |
| post_contract / post component | `{profile_id,physical_version,components,pointer,preservation_digest}` / `{component,version,fingerprint}` |
| INPUT core | `{format,dataset_id,db_id,roles,physical_binding,pre_profile,components,pre_pointer,pre_data_digest,deletion_digest,health_digest,sidecar_digests}`; recoryn-maintenance-input-v1 |
| source sidecar fact | `{kind,digest,identity}`; COST_WITNESS/현재 source FILE, DB 내 동일kind 중복0·기존 고정 paired-witness 위치 |
| planned slot / verified artifact ref | `{operation_id,db_id,kind}` / `{operation_id,db_id,kind,digest,identity}`; DB_IMAGE/COST_WITNESS·actual artifact FILE |
| progress | `{format,version,operation_id,plan_digest,sequence,record_digest}`; recoryn-maintenance-progress-v1/version1 |
| record | `{format,version,operation_id,plan_digest,sequence,prior_digest,phase,disposition,targets,binding_links,output_digest}`; recoryn-maintenance-record-v1/version1 |
| record target | `{db_id,source_cut,source_pointer,source_digest,pre_image,sidecars,credited_epoch,restore_effect}` |
| binding link / binding hash projection | `{db_id,anchor_identity,namespace_identity,catalog_id,link_nonce,binding_digest}` / `{db_id,dataset_id,current,primary,link_nonce}` |
| output / target | `{format,operation_id,plan_digest,targets}` / `{db_id,profile_id,physical_version,components,source_pointer,data_digest,media_digest,sidecar_digests,deletion_digest,health_digest}`; recoryn-maintenance-output-v1 |
| complete | `{format,operation_id,plan_digest,record_digest,output_digest}`; recoryn-maintenance-complete-v1 |

INPUT/current ComponentFact는 이름순 name/version/fingerprint 사실, post component는 위 component/version/fingerprint다. 현재 source/output sidecar_digests는 source 사실이며 record sidecars의 image artifact ref와 구별한다. C2 plan에 미래 image hash/identity를 요구하지 않는다. entries는(dataset_id,db_id), targets/binding_links/fresh targets는db_id, components는 component명, roles는 lexical unique, history는 완전 canonical bytes, credits는(operation_id,sequence,record_digest), artifact sidecars는(operation_id,db_id,kind), source sidecar는kind순이다. commit_order는 target db_id의 정확 순열이며 lookup sort와 별도로 고정한다. 중복 key/상충 binding/같은 physical의 복수 db_id 분할0이다.

| 상태/NULL | 허용 조건 |
| --- | --- |
| current.identity NULL / fresh pre_identity NULL | PREPARED+FRESH_INIT 실제 미생성만. BOUND의 NULL0 |
| UNCOMMITTED / KNOWN0 | 검증된 최초 준비만 / 실제 FRESH metadata0+genesis 검증과 credits[]. UNKNOWN 대체0 |
| 양의 KNOWN/credit | 같은 DB 실제 POST/restored-legacy가 지지하는 최대 E. PRE/타DB/계획E만으로 credit0 |
| pointer | `{kind:ABSENT}` / `{kind:FRESH,dataset_id,epoch:0}` / `{kind:COMMIT,dataset_id,operation_id,epoch,input_digest}`, COMMIT 양수 |
| source_cut | PRE/IMAGE_UNREBOUND/POST/UNRESOLVED. pointer/digest NULL은 UNRESOLVED+QUARANTINED/RECONCILIATION_REQUIRED만 |
| credited_epoch | POST만 고정 target E, 나머지 NULL. old O epoch는 R credit0 |
| pre_image | PREPARING은NULL 가능, IMAGE_VERIFIED 이후 전 target verified DB_IMAGE 필수 |
| restore_effect | APPLY NULL; ROLLBACK은 NOT_STARTED/INTENT_RECORDED/BACKUP_RETURNED/BACKUP_FAILED/NO_COPY_VERIFIED/UNKNOWN |
| prior/output | sequence0만 prior=NULL, 이후 정확q−1 digest. output_digest는 VERIFIED만 필수·그전NULL |
| binding_links | PREPARING NULL은 준비 prefix이며 image/source허가0. 전체 결속 뒤 완전 같은 목록 유지 |
| nonapplicable media/deletion/health | 정확 명명 profile에 해당 component가 없을 때만NULL |

binding_digest에 operation_ref/plan_digest·floor·미래 record/marker를 넣지 않는다. 정당한 후단 floor 갱신을 전체 catalog hash 차이만으로 foreign이라 하지 않는다. restore INTENT는 실제 API 실행 증거가 아니며 POST만 보고 BACKUP_RETURNED를 발명하지 않는다. APPLYING은 commit_order의 post-prefix·최대 한 허용 중간cut·나머지PRE, VERIFYING/VERIFIED는 전POST다. unknown을 PRE로 바꾸지 않는다.

### 고정 path·발견·atomic 게시

actual anchor의`.recoryn-maintenance/v1/bindings.json`, primary의 같은 namespace 아래`operations/<hex32>/plan.json`, `records/<q>.json`, `progress.json`, `images/<db_id>.sqlite`/`<db_id>.cost-witness`, `output.json`, `complete.json`만 계산한다. q는0 또는 leading-zero 없는 양의 십진/signed64다. Library root가 primary, standalone은DB parent, split은Library primary+각 별도DB parent다. serialized 임의 path/관리root를 따르지 않는다. secondary-only startup은 참조만으로 보류할 수 있지만 primary 추측open0, 명시한 완전 DatasetLayout의 actual anchor/namespace/name/history/roles를 대조한다.

C0는 read-only이며 constructor/mkdir/source open-for-write/lock O_CREAT/WAL/SHM/checkpoint0이다. 관련 namespace/header/catalog/current pointer/operation/history 흔적이 있는데 필수 자료가 없으면 UNKNOWN이며 새 빈 lineage로 초기화하지 않는다. 유효 catalog가 같은 parent의 다른DB만 관리함이 확인되면 무관 legacy의0/1 호환을 일괄 BUSY로 막지 않는다. current FileId뿐 아니라 저장name/과거ID의 현재 해석도 대조하고 교체를 새dataset으로 채택0이다. 모든 관련 operation/역R/nonterminal을 조사해 plan→연속records→progress→output/complete를 검증한다. head lag는 C0수선0·NEEDS_RESUME, gap/foreign은보류다. valid marker를 lag 때문에 삭제하지 않는다.

writer는 fixed slot·actual namespace/use·현재 identity/issuer/attempt에 결속한 private permit을 매 실제 쓰기 직전에 확인한다. operation은 원M/E/남은deadline, fresh는 actual birth/use+FRESH_INIT intent다. C0 discovery 예산은 한 attempt에서 공유하고 GUI/append hot path마다 전체scan하지 않는다. canonical bytes를 같은 namespace의 임시file에 완전write/flush/fsync하고 안전path/identity/소유를 재검증해 atomic replace한다. short write/오류/미완료 temp를 완성으로 올리지 않는다. inspector orphan 자동삭제0이며 전원장애 내구성 인증이 아니다. 기존 `_safe.atomic_json`의 LF/schema_version 부착을 그대로 전용하지 않는다.

## 5. preview 승인 core·비순환 hash

PreviewApprovalCore root는 exact `{format,request_nonce,kind,reverses_operation_id,layout_snapshot,source_snapshot,change_contract}`다. format=`recoryn-maintenance-approval-v1`, request_nonce=Id, kind APPLY/ROLLBACK, APPLY reverses=NULL·ROLLBACK은 검증한 원M이다. 관리 wire의 strict canonical bytes를 쓴다.

```text
proposal.approval_digest == intent.proposal_digest
 == durable_plan.approval_digest == SHA256(canonical(PreviewApprovalCore))
```

| projection | exact 필드·결속 사실 |
| --- | --- |
| layout_snapshot | `{primary_kind,primary_anchor,targets}`; LIBRARY_ROOT/DB_PARENT·actual DIR. db_id순 target=`{db_id,roles,physical_binding}`의 현재 source FILE/parent/name |
| source_snapshot | db_id순`{db_id,input,management_snapshot}`. input은 현재 INPUT core. 기존 binding의db/dataset ID 재사용, 최초legacy는 live issuer slot에 예약하고 C2a까지 고정·source/dir쓰기0 |
| UNMANAGED | `{kind:UNMANAGED}`; 관련자료/과거흔적 부재가 확인된 최초legacy만 |
| MANAGED | `{kind,namespace_identity,catalog_id,catalog_generation,binding_digest,epoch_floor,operation_ref,head_digest,record_tip_digest,complete_digest,history_digest}`. actual DIR/Id/Seq, UNKNOWN floor금지. head/tip/complete는 실제 부재만NULL·손상을NULL화0 |
| history projection | operation_id순`{operation_id,plan_digest,record_tip_digest,complete_digest,credited_epoch}`. 전chain/역참조 검증 뒤 hash, 해당DB 실제POST/restored-legacy만credit. actual부재 tip/complete만NULL, current FRESH/no-operation의 유효 빈이력만[] |
| change_contract | `{targets,commit_order,rollback_source}`. db_id순 target=`{db_id,target_profile,target_physical_version,components,preservation_digest,planned_epoch}`. 고정profile/component·APPLY2/R의 검증target0/1/2·검증floor의 고정 양E |
| rollback_source | APPLY NULL; ROLLBACK=`{operation_id,plan_digest,before_images}`. root reverses와 같은M·db_id순 검증된 원M artifact ref. 미래R-pre image가 아님 |

core에 자기 digest·새 durable plan_digest·미래 namespace/image identity/hash·private issuer/receipt/handle·secret/raw Path repr을 넣지 않는다. **기존** namespace/과거plan/head/history·원M 실제image ID는 현재사실로 포함할 수 있다. 이름만 재귀금지해 정상 MANAGED/ROLLBACK을 깨뜨리지 않는다. maintenance floor와 삭제g·witness revision/clock·consent/Job/runtime세대는 다른 권위다.

C0 plan은core bytes/actual preview instance/nonce를 issuer표에 보관한다. approve는 같은live instance/core의 명시 승인event 뒤만 원intent instance를 발급한다. 같은hash/field/JSON/다른facade/replay만으로 receipt0이다. apply/resume/rollback는 C1전에 현재source·head/tip/marker/history·계획의 같은core/CAS를 대조하고 변경이면 새preview/승인을 요구한다. resume의 원operation/예상phase/head도 preview slot에 결속한다. C1/actual drain 뒤 actual소유의 source/부정권위를 재검증하고 C2a에서 처음 새namespace actualID/link/durableplan을 만든다. 새operation 자신의 예정게시를 preview에 소급하지 않으며 기존입력/target/관리history 변경 예외로 삼지 않는다.

I_d는 고정 pre INPUT의 canonical hash다. 새 pointer/현재 I/output/record/marker를 I에 넣지 않고 옛 pointer의 옛 I는 과거 사실로 구분한다. data digest의 typed cell·명명 table/열/row 순서·중복 보존·metadata 두 표 제외·sqlite_sequence 보존은 아래 exact container로 구체화한다. raw 업무 내용/secret을 관리 journal/log에 넣지 않는다.

hash 순서는`현재pre사실→I→예정post COMMIT→actualC4/전체검증→output→output_digest→VERIFIEDrecorddigest→complete`다. plan은자기hash를core밖에 두고 output은자기hash/미래VERIFIED/marker/catalog완료hash/가변cleanup을 포함하지 않는다. creditrecord는자기digest/나중catalogcredit를 담지 않아 record→catalogfloorcredit→최종VERIFIED→marker의 순환0이다. marker후완료DB/journal/catalog재쓰기0, completion은유효marker/R연결에서 도출한다.

### 5.1 recoryn-data-v1 exact container

```text
Data = {format:"recoryn-data-v1", tables:[Table,...], sqlite_sequence:NULL|[Sequence,...]}
Table = {name:KnownTable, columns:[KnownColumn,...], rows:[[Cell,...],...]}
Sequence = {name:KnownAutoincrementTable, seq:["integer",CanonicalNonnegativeSigned64Decimal]}
```

root exact keys는 `{format,tables,sqlite_sequence}`, table은 `{name,columns,rows}`, sequence는 `{name,seq}`다. canonical UTF-8/no BOM/no 마지막 LF·sort_keys/compact·ensure_ascii=False·allow_nan=False bytes의 SHA256을 소문자 hex64로 쓴다. `recoryn-shape-v1:` prefix를 붙이지 않는다. duplicate/missing/unknown key·invalid UTF-8/surrogate·비유한 값·타입/의미 불일치를 정상화하지 않는다.

tables에는 현재 검증한 명명 profile의 실제 table을 known ASCII canonical 소문자 name의 UTF-8 bytes순으로 넣고 중복 name을 거부한다. 이름 문자열만으로 profile을 인증하지 않는다. columns는 실제 schema wire와 대조한 선언 순서의 모든 canonical column 이름이며 중복/누락/임의 정렬0이다. rows의 각 row는 columns와 순서·길이가 같은 typed-cell 배열이고, row 전체의 canonical UTF-8 bytes순으로 정렬한다. **같은 row 중복도 보존**하며 우연한 SELECT 반환 순서에 hash가 의존하지 않는다. hidden rowid를 업무 열/ID로 추가하지 않는다.

`recoryn_schema_components`와 `recoryn_maintenance`만 tables에서 제외하고 이들의 shape/expected rows/pre-pointer는 별도 input 사실로 결속한다. sqlite_sequence는 아래 별도 슬롯이다. 다른 실제 profile table/행이나 unknown object를 임의 cache로 무시해 CURRENT로 만들지 않는다.

| 실제 storage class | exact cell |
| --- | --- |
| NULL | `["null"]` |
| INTEGER | `["integer","정규 signed64 십진"]`; 0은 `0`, +/leading zero/`-0` 금지. bool/REAL/string coercion0 |
| REAL | `["real","IEEE754 binary64 big-endian 소문자 hex16"]`; 관측된 ±0 bit를 보존하고 NaN/±Inf 거부 |
| TEXT | `["text","원 Unicode scalar 문자열"]`; normalization/casefold/손실 대체 decoding0 |
| BLOB | `["blob","소문자 even hex"]`; 빈 blob은 빈 문자열이며 TEXT/NULL로 바꾸지 않음 |

sqlite_sequence는 **실제 engine table 부재면 NULL, 존재하면 sequence object 배열**이며 존재하되0행이면 `[]`다. name은 승인 profile의 실제 AUTOINCREMENT table이고 name순으로 정렬한다. seq는 실제 nonnegative signed64 INTEGER의 **typed cell `["integer","n"]`**이며 plain JSON int가 아니다. 중복 canonical name·미지원 이름·NULL/REAL/string/음수/범위 밖 seq를 정상 수락하지 않고 실제 행/부재를 합성하거나 max/0으로 수선하지 않는다. Jobs 자동증가 상태를 보존하되 그 값/hidden rowid를 새 권위나 업무 ID로 승격하지 않는다. typed cell을 인코딩할 수 있어도 원 업무 row·schema/삭제/건강/금융/consent/Job 불변식 검증은 별개다.

`pre_data_digest`/`data_digest`는 이 검증된 논리 stream의 hash다. media/deletion/health/sidecar 근거를 합쳐 생략하거나 raw file bytes 동일을 요구하지 않는다. metadata pointer 변화만으로 업무 data hash를 바꾸거나 hash가 같다고 현재 소유/권위를 발급하지 않는다.

이 stream 전체는 관리 JSON object가 아니므로 **관리8MiB 한도를 사용자 DB/전체 data hash stream 크기에 소급하지 않는다.** 실제 phase/기한·현재 소유 아래 bounded 처리/필요한 TEMP 정렬을 사용할 수 있으나 source 변경0·본문 로그0·실제 I/O 종료 회수를 유지한다. 업무 행/본문 전체 wire를 관리 JSON/journal/로그/지원 출력이나 새 영속 data artifact로 persist하지 않고 digest만 저장한다. 임시 정렬은 새 정본 data 파일이나 raw snapshot 영속화 scope가 아니며 임의 크기/시간/메모리 성능을 보장하지 않는다. C0 source/관리 쓰기0 규칙도 바뀌지 않는다.

## 6. 실제 registry·resource use·C1/drain

CORE_A_V1 고정 9port 는 LIBRARY_CONTROL/RECORDING_RUN/CHUNK_WRITER/JOB_ATTEMPT/CONTENT_ACCESS/CONSENT_SCOPE/GATEWAY_HANDOFF/LEDGER_TAIL/MAINTENANCE_PHASE 다. 실제 constructor/자식생성/all-birth inventory·issuer/parent instance/claim/nonce·root/physical/role/registry/admissionepoch 를 결속한다. callerbool/current-list/동일객체 required()/fakeidle/NoOp/counter0 에서 required/complete 를 만들지 않는다. actor0 은 생성 port 자체통제를 확인할 때만 허용한다. public Library/Jobs/Content/Consent/Ledger/Recording/ChunkWriter/CredentialService, Gatewayview/AuthBinding/Consent·Library 재생성도 첫 effect 전 sourcehook 을 통한다.

CORE_L_SINGLE 은동 DB Library/Jobs/Content/health/deletion·실 consumer/sealer/reader 의 shared-use/ADdrain 양성을, CORE_P_SPLIT_AUTH 는 library+별 consent/costDB/witness·실 GS05service/Gateway 에 fakevault/transport 만 주입한 native/callback/join/request/금전 tail 양성을 유지한다. genuine CORE 의 OPERATING 승격 0, unclassified0/1 호환은유지하되 그 maintenance seal 은 UNKNOWN/BUSY 다. coldlegacy 는승인후 trusted intake 하므로 옛 root 를신생으로 재라벨하거나 미등록 operatingowner 를흡수하지 않는다. blanketBUSY 만으로 원 AD-D05 reader+UNKNOWN60/witness 양성을 삭제하지 않는다.

협조적 resource-use protocol 이다. 실제 handle 의 volume/fileID/object-kind 와 ancestor/parent/name/role/epoch 를 재확인한다. key 는길이구분`(protocol-v1,volume-id,file-id,resource-kind)`이고 같은 DB 복수 store 는한 aggregate useS, alias 의 ancestorchain 도유지한다. backend 는기존 coordination 내부 Windows LockFileEx/UnlockFileEx 의실 S/Xbyte-range 와 전 process 공통고정사용자 Recoryn controlnamespace(source/backup/process/TEMP/callerlockpath 밖)다. header original-key/nonce/generation/state/integrity·안전 path/owner/identity 검증, livehandle 중 control 교체/삭제 0 이다. 실제 ABI/공유 handle 은후속검증이며 Pythonmutex/짧은 Coordinator/.writer.lock 만으로강등 0 이다. raw 비협조 OS ABA 를막는 sandbox/pin 이라는주장 0 이다.

| byte | 정상 / operation | 수명 |
| --- | --- | --- |
| 0 admission | birth/effect S / C1 전 try-onlyX | 해당 effectcut / retiring·operation·successorhandoff 까지연속 X |
| 1 resource use | actualDB/DIR S / DBmaintenance·협조교체 X | 실제 connection/actor/자식 lease 마지막 ACK/close 까지 |
| DIR2 namespace | 기존 lookup S / 미존재 create·binding 교체 X | lookup→actualDBuse 확정까지 |

birth 예약은비허가다. metadata latch 밖 actualuse 획득→identity/parent/role/epoch 재검증→use 유지첫 effect/publicreturn 을 결속한다. 미존재는가장가까운기존 parent/root/creation-anchor byte0S+directory-useS+parentbyte2X 와 parent/name/role/birthnonce provisional slot→create-new→actualfileID/use 확정까지 이전보호를먼저놓지않는다. 정상협조교체는같은 DIR/DBuseX 가필요하며 획득전 identitysample 만은소유증거가아니다.

C1 전 targetclosure 의모든 DB_KEY 와 creator 가써야하는 DIR/creation-anchor byte0X 를 canonicaltuple 순 try-only 준비한다. 하나라도실패면 C1/retire/header/image/DDL0·부분준비해제다. **준비중 generation/header 전진 0**이다. root→짧은 registrycut 에서 currentseal/inventory/identity/domain 과 t0/retiringowner/수락집합/gateclosed 를같이결속하고 latch 밖 g+1/CLOSEDheader 를게시한다. header-pending 오류는 post-C1 보류다. pre-C1abort 는 OPEN/g·원 owner/accepteduse 를보존, preparation 재사용 0·현재사실/freshpermit 만새시도가능이다. staleseal 을되살리지않으며 operating 거부만으로 currentCOREseal 을소비하지않아 core 양성을비교할수있다.

C1 후새 constructor/start/resume/claim/READ/FIFOcommand/O/write/dispatch/handoff 수락 0 이다. 기존 acceptednonce 의원 FIFO 순 drain/sealer/witness 유한 tail 은보존하며 queuepop/cancel/counter0 을실종료로세지않는다. 기존 handoff 를소급 0 으로만들지않고 UNKNOWN/노출/witness 를유지한다. actualdrain/connectionclose 뒤 admissionX+namespaceX 를보유한채마지막자체 useS 를내리고 DBuseX 를얻는다. 원자 S→Xupgrade 를가정하지않고새 normalownergap0 을유지한다. peerS 가남으면 BUSY 이며임의 peerclose/kill0 이다. accepteddata-generationtail 을 DB 소유 binding 교체로잘못분류해 selfsharedlock 과교착시키지않는다.

잠금순서는 OS 준비밖→기존 root→짧은 registrymemoryfast 검사/CAS→밖완료 publish 다. security 는밖준비→원 consent→ledger→serviceCAS→밖이다. nativeget/set/delete 동안 root/service/security/registry/admissiongate0, accepted-use/nonce 만유지한다. WORK_ACCEPT S 는 READ READING/FIFO 수락 cut 까지, NETWORK_O/WRITE S 는실제 open/writecall 까지다. U 소비후 C1-before-READ 면 get0, preacceptednative 는 C1 후 return/LIVE 자식등록 drain 양성을유지한다.

livelease 는 public/native_return 노출전`(processIssuer,serviceBirth,acceptedRead,claim,lease nonce,actual instance)`로등록한다. acceptedREAD 가등록 gap 소유를유지하며원 READING/CAS 를 mutex 밖으로옮기지않는다. release 는 per-leaseguard 한승자·ownslot/headerclear·callbackdetach·released=True→guard 밖원 callback 한번→실 return 뒤 exactnoncereceipt/ACK1 이다. duplicate/oldinstance/metadata 삭제/reads0 은새 slotACK0 이다. callback 실패는 CALLBACK_FAILED·owner/use 유지·자동재호출 0, publish 만실패하면 CALLBACK_DONEreceipt 재 publish 만허용한다. 원 None 반환/CAS/FIFO 보존, immutable/OS/외부복사 secretzeroization 보장 0 이다.

ACK02 유효 trace 는 **acceptedREAD/native-enter(reads1)→C1→native-return→bind/LIVE 자식등록→publicreturn/finallyreads0(leaseLIVE)→clear/callback 대기(ACK0)→callbackreturn→exactACK1→actor/connection 전체종료→image1**이다. 반환/LIVE 뒤 C1 의옛대체 trace 를현재 norm 으로복사하지않는다. request 종료와금전/outcome/witnesstail 완료는별개다. await_shutdown(timeout)뒤 executor.shutdown(wait=True)는비선점 join 이며 finite timeout/종료 ACK 가아니다.

Gatewaycleanup 은 LEASE/AUTH_COPY/TICKET_CLAIM/DISPATCH_CACHE/CONNECTION_CLOSE/REQUEST_END 각입장/실 return 을따로기록하고앞예외에도뒤단계를각한번시도한다. 원 primarySecurityError/code/outcome/UNKNOWN/witness 를보존하고 secondary 는 sanitizedreceipt 다. clear 성공과 callback 완료, leaseACK 와 request/connection/headertailACK 를구분한다. 본문성공이어도필수 cleanup 실패면정상 body/전체 ACK0·SECURITY_STATE_UNAVAILABLE, 현재미송신증거없으면 outcome_known=False 다. 미완료 connection/request 를강하게보유하고 image0, callback 반복/강제정산/UNKNOWN→RELEASED0 이다. 원 API 의미송신증거가있는 RESERVED 정리만허용하며기존 request 종료를새 O/handoff 권한으로쓰지않는다.

REG03 은 root/DB/epoch/domain/보이는 identity 가정상이고필수 producercoverage 만부족, REG07 은 genuine/current/완전 CORE 를 OPERATING 에제시해 domain 만다른입력이다. stale/foreign 방어를추가해목표를가리지않는다. 동일 currentCORE 로 operating 거부→core 양성을비교한다. 다른방어가변이를가리면 MASKED 이며방어를빼서 kill 을만들지않는다.

## 7. 단계·기한·bootstrap·CR

입장 전 stale 권위는 실제 입장/claim을 차단한다. 이미 입장한 뒤 늦은 무효화/손상/clock 실패는 정확 오류·단계·최종 게시0·원본 보존으로 판단하고, 그 전에 합법적으로 끝난 admission/manifest 읽기를 소급해0으로 요구하지 않는다. 원 AD-A04의 Job resume는 BLOCKED→QUEUED에서 fence F+1·state_version V+1이며 attempts/attempt_count N·기존 checkpoint/history를 보존한다. 실제 resume 반환으로 그 작업 ACK를 회수하고 자동 claim/새 attempt/reader/송신0, C1 후 별도 claim 차단을 유지한다.

일반 GS11READY 는검사시작부터엄격 L30 초·root/epoch/현재 negativecut 에결속한다. 별도 maintenanceproof 는현재 actual 소유/정지 ACK/source/부정권위/phase/plan/attempt 에결속하며 일반 receiptTTL 연장/재발급으로장기화하지않는다. capture 자기 fence/종료 ACK 를관리허가에전용하지않고관리실패로 STT/LLM 과독립한원녹음저장을깨뜨리지않는다.

C1t0 부터획득/정지/ACK/header/physicallock 의**공통 10 초잔여**를전파하고 Coordinator 내부 loop 로재발급 0 이다. actualdrain/정지소유후첫전체검사전에 C2 단일 3600 초를결속하며첫검사시간도포함하고 phase/backup/record 로갱신 0 이다. exact 경계의새 effect0 이다. 늦은비선점 I/O/join 은 caller 보류뒤 broker 가원 gate/use/owner 를실종료까지보유한다. lateACK 는원 nonce 만회수·첫호출성공소급/자동 apply/새 10 초 0 이다. marker 가기한전입장해기한후유효 return 하면완료 artifact 를보존하고남은 cleanup 만별도보류한다. 미입장 marker 는기한후 0 이다.

| cut | source/durable 규칙 |
| --- | --- |
| C0 | read-onlyProposal/진단, source/관리/lock 생성 0 |
| C1 | actualgate 폐쇄/수락집합/t0·sourcepointer 불변·owner 유지 |
| C2 | actualACK/drain/close/physical 소유·첫현재검증·sourcemetadata 불변 |
| C2a | actualnamespaceID→immutableplan/PREPARING→모든 localentry/link→완전 binding_links 검증. 누락이면 image/source/DDL0 |
| C3 | 닫힌검증 before-image/pairedwitness, sourcepointer/형식선행변경 0 |
| C4 | DB 별승인변경/전체 componentrows/user_version2/COMMIT(M,d,E,I)의같은 transaction. DBpost/journallag 는예정계약/identity/권위가맞는 prefix 만인수 |
| C5 | 전 POST/shape/data/원 media/삭제/health/witness/actualproof 검증, output→VERIFIED→마지막 marker. floor/BOUND/refs 는 VERIFIED/marker 전게시검증 |
| C6 | 완료 history/현재 source·권위검증, actualadmission/namespaceX 연속보유 X→새 successorS handoff·새 instance/등록후 normal |

첫 mkdir 만남은 namespace/freshPREPARED-unbound 는 UNKNOWN/QUARANTINED·자동재초기화/adopt0 이다. trustedfresh 는 actualbirth/use 로 source 생성전 PREPARED/FRESH_INIT/current.identityNULL/UNCOMMITTED 게시→exactprofile+FRESHmetadata0/물리 2transaction→actualfileID/BOUND/KNOWN0 게시검증→publicreturn 이다. fresh 에가짜 M/C1deadline 을만들지않는다. split 을한 atomictransaction 이라하지않고모든 link 전 image/source0 이다. 외 journal/activeoperation 은 DBNORMAL/ABSENT 보다우선한다.

E_d 는현재 pointer 와검증된해당 lineage 외부 actualfloor 최대+1, 이력부재가증명된최초 legacy 만초기 E1 이다. UNKNOWN→0, maxsigned64 의새 operation0 이다. 동일 logicalM/R resume 는 plan/map/E/commit_order 불변, 새 processactualissuer/소유/ACK/attempt/deadline 만재취득한다. DBpost/journallag 면재 DDL/재 epoch0, L-post/S-pre 같은예정 prefix 는 NEEDS_RESUME·남은것만진행한다. foreignidentity/권위/삭제/witness 전진은이양성 prefix 가아니다. 완료 M 의옛 output 과후속정상업무 data 의영구동일을요구하지않는다.

### CR: in-place Connection.backup

새 R 은원 M 에연결하고 Mimage/journal/marker 를보존하며 M/R 동시변경 0 이다. 실제 R-pre/currentwitness/부정 floor 와 I_R 을 R 쪽에보존한다. target 은원 M 검증 before-image 이며옛 imageI 를 R 입력으로복사하지않는다. stagingexchange/rename 의새 FileId 사후채택 0, actualsource/parent/name/targethandleidentity·namespace/useX 를유지한다.

닫힌 completesnapshot·WAL/SHM 불필요가확인된 image 만 readonly/immutable 로열고 activeWALimage 를 immutable 로읽지않는다. 새관리 destinationconnection 은 backup 입장시 in_transaction=False, BEGINIMMEDIATE 유지중 backup0 이다. source/image/targetpage-size/지원 SQLite 조건을검증하고임의변환 0 이다. `image_connection.backup(target_connection)`실 return/close/reopen 뒤 identity/integrity/FK/exact 논리내용/shape/version/현재부정권위를검증하며 targetfile 전체 bytes=imagebytes 를요구하지않는다.

| actualcut | 인수 |
| --- | --- |
| exactR-pre | 미완료. 원 R/E 유지·현재소유/새명시 attempt 로재개가능 |
| exactcurrent2image+oldOpointer | IMAGE_UNREBOUND. 별도 BEGINIMMEDIATEtransaction 의 COMMIT(R,E_R,I_R)재결속만남음·일반권위 0 |
| exactlegacy0/1+metadataABSENT+외 Rlineage | restorecut 완료·metadataCREATE0·외 floor/E/history 보존 |
| exactCOMMIT(R,d,E_R,I_R)+예정 target | 해당 DBcut 완료·재 backup/rebind/epoch0·남은 prefix/전검증 |
| 부분/불명/foreign/witness·삭제전진 | QUARANTINED/RECONCILIATION_REQUIRED·source/R-pre/Mimage/journal 보존·자동덮기 0 |

restoreintent/실 APIreturn/no-copy 는다른사실이다. 미실행 backup 을실행성공으로적지않고 targetpredicate/actual 소유를검증한동일내용특례만 NO_COPY_VERIFIED 다. image 복원/재결속과복수 DB 를한 SQLitetransaction 이라하지않는다. lateI/O 는원소유로회수·다음변경기한갱신 0 이다. legacyR 뒤새 N 은외 Rfloor 보다큰 E, oldgrant/lease/permit/UNKNOWN/삭제 floor 복원 0 이다. retention/compaction/inspector 자동 cleanup 은별도승인, 공간부족도원본/image/history 보존과보류다.

## 8. 오류·결과

| 조건 | 정확경계 |
| --- | --- |
| exactlegacy | KNOWN_LEGACY/MIGRATION_REQUIRED, current-only 도 MIGRATION_REQUIRED·미관리 0/1 호환유지 |
| knowncomponent/row 불일치 / future | INVALID/SCHEMA_COMPONENT_MISMATCH / UNSUPPORTED/UNSUPPORTED_SCHEMA·일괄 busy 변환 0 |
| read/coherentcut/예산불명 | INDETERMINATE/SCHEMA_INSPECTION_UNAVAILABLE, durableop 전 MAINTENANCE_BUSY·기지 op 는 MAINTENANCE_RESUME_REQUIRED+실 disposition |
| managedtyped 손상/필수자료유실 | MAINTENANCE_RESUME_REQUIRED/QUARANTINED, sourceCURRENT 여도 normal0·빈 journal 재생성 0 |
| foreignpointer/identity/lineage/floor | MAINTENANCE_RESUME_REQUIRED+RECONCILIATION_REQUIRED, rollback 은 MIGRATION_ROLLBACK_UNSAFE+RECONCILIATION_REQUIRED |
| physicalbusy / owner·ACK 불명 | DB_BUSY / MAINTENANCE_BUSY+실 phase·timeout 으로종료/소유반환발명 0 |
| floor max 의새 operation | 변경전 MAINTENANCE_BUSY·phase/dispositionNULL·자동 retry0. 동일 M/R maxE resume 는재계산 0 |
| 원 security/금융/삭제 reason 존재 | 원 code/outcome_known 우선·genericJSON/schema/transport 덮기 0 |

catch 순서는 MaintenanceError→SecurityError→명시 domain/inputadapter→unexpected 다. unexpected/TypeError/fixtureerror 를정상 INDETERMINATE PASS 로세지않는다. code/phase/disposition 만표시하고 rawpath/SQL/exception/secret 을로그/GUI/DB/설정/export/지원출력에남기지않는다. 진단/validwire/marker 는현재소유·입장 permit 이아니다.

## 9. 유한분모·oracle·수락

원 14family 는 raw3841−제외 29=3812 다. 제외는 K 의 L/paired-witnesshook5, B 의 L/securitylock18, W 의 S/media6 뿐이며불법/손상/future/거부입력을 feasible 에서빼지않는다. 원축순서의**오른쪽최속·제외후 denseordinal**, D/A4 자리·K/R/B/J/C/I/Q/T3 자리·H/P/W/O2 자리다. 기존 namedID/primary/의미를유지하고선택 C2/J/C/I/Q/Tnamespace 를사용한다. RC 실행행은 01/03/04/05 만·02 row/skip/placeholder0 이다.

base 소유는 D/B 의 OPEN/MIGRATE/RESUME 가 a, K 의 MIGRATE/RESUME 가 a, H23 만 b, O 의 maintenance-newjob/revoke-oldpermit/two-resume-claim 이 a, J/C/Q/T 의 MIGRATE 와 I 의 OPEN/MIGRATE 가 a 이며나머지 b 다. D RESTORE/IMPORT 와 J/C/I/T 의 b/H23 은 restore_import, K/Q 와 a O 는 maintenance_crash, H a 는 schema_catalog, R/A/P/b O 는 restore_import, W 는 migration_backup, 기타기본은 migration_backup 이다. 선택된 family 별함수/ID 의작은 rule 표와본문원입력으로연결하며임의재번호 0 이다.

REG7/ACK01–04/FIN3/CT16/ID5/FX10/추가 21 은 a, actualUI ACK05 만 b 다. a source 의 native/lease/cleanup/금융실패를 b 까지미루지않는다. C6/CR5/FP4/SP1/G1U7/LEASE3 의추가 21 은모두 a 다. SC12 증가 12·FP4 재사용, CA101+FIX1 추가 6 선택 107, API01~03 의 previewhash 관측증가 0 이다.

CAraw=feasible101/제외 0 은명명유한 unit/domain 이며무한 JSON/상태전체가아니다. raw/canonical 각 8MiB·depth16·단 discovery 원문누적 256MiB·operation100k/전 record1m 상한, 같은 file/alias/split 재읽기도같은 attempt 에가산한다. 무한선열거/list 후검사 0, 첫초과뒤 nextopen/parse0 을 calllist 로관측한다. C0 가짜 C1deadline0 이다. canonical-only 초과/depth16·17 은 boundedserializer/readerunit 이며 fullCURRENT 양성으로위장 0 이다. 백만 file 대신유한 lazyiterator 는 OS 소유/actualACK 인증이아니고선택된작은실 filesystem 양성을유지한다.

golden/handbytes·literalID·독립분모/제외/primary 를먼저고정하고제품 parser/enum/catalog 에서 expected 를만들지않는다. 정상 control→별고정 copy 단일 actualmutation→동일 ID 의목표 call/assertionFAIL 만 kill, root/import/선택/setup/TypeError/timeout/teardown 은 INVALID, 다른 guard 는 MASKED/NOT_KILLED 다. 원 fault110+CA58=의도 label168 이며 SC/추가 6 포함 uniqueactualsite/kill 은후속 dedup/실행으로확정한다. strict rawequality 가 duplicate/LF/coercion 변이를가려도다른방어를빼서 kill 을만들지않는다.

고정 BASEgitarchive+정확배정 file 만 OSTEMP, cwd/rootdir/pytest 설정/PYTHONPATH=copysrc·부모/실 spawnimport 출처·`-p no:cacheprovider`·고유 basetemp·offscreen·ResourceWarningerror·offline 을지킨다. 신규 8 시험 file 합계 60 초/준비포함기존계약과 S1 단독 20+감사게이트를유지하고초과는 oracle/분모축소전실시간/원인/개선안을 X00 에보고한다. core.ymlflag 그대로전체, coverage85+check_coverage7 묶음(domain/capture/jobs/storage/security/content/all), package line95/branch90·all line85/branch80, offlinewheel 을정확최종 tree 에서검증한다. 기존시험의내부가정실패는 file/실패/최소변경안먼저보고하며무단기대변경 0 이다.

후속단계는 purewire/constructor-freeinspection, broker/actualuse/sourcehook, migration/journal/CR 의검토가능경계로분할제안할수있으나새실행권한은없다. 공용반영·독립문서확인·정확새 BASE/manifest/소유·구현/통합/commit/push 는 X00 소관이다. 본조립저자의원 resource/CA 자기최종승인 0, 미실행 loss/recovery/performance/compatibility/powerloss/Windows 실운영보장 0 이다.

## 10. 선택 delta literal 표와 hand wire

SC01~12와 FP01~08의 정확 primary는 모두 `tests/unit/test_schema_catalog.py::test_component_shape_wire[각 literal ID]`다. SC12/기존FP4는 X00의 정상 수집·new16-r3 XML 확인 목록으로, 새FP05~08은 X00 FIX1 배정의 같은 함수/literal ID로 결속한다. 조립자는 진행 중 source/test/XML을 새로 읽지 않았으며 X00의 증거 인수와 이번 직접 실행을 구분한다. `tests/unit/test_schema_catalog.py::test_schema_catalog_case_manifest_is_literal`은 감사 node이며 semantic20/4105에 더하지 않는다. 기존 FP4의 함수 binding 변경은 증분0이고 새FP4만 증분4다.

다음은SC12/CA101/FIX1추가6의입력·oracle전기이며실행결과가아니다. 원3982전체row를재복사하지않는다. 기존exact재사용22는증분0이고row안새tuple/반복을숨기지않는다. SC12exactnode는진행S1입력을읽지않고X00봉인대응으로만결속한다.


### 10.1 Base14: exact selected axes / primary functions

| Family | Raw/F/excluded | Ordered axes / named base | ID / function |
| --- | --- | --- | --- |
| D | 960/960/0 | `[["layout",["L","S","P","C"]],["schema",["LEGACY","CURRENT2","FUTURE3","PARTIAL","CORRUPT"]],["action",["OPEN","MIGRATE","RESUME","BACKUP","RESTORE","IMPORT"]],["requested_hook",["BEFORE_PREFLIGHT","AFTER_PREFLIGHT","AFTER_DB_BACKUP","DURING_DB_WRITE","AFTER_DB_COMMIT","AFTER_PAIRED_WITNESS_STAGED","BEFORE_COMPLETE_MARKER","AFTER_COMPLETE_MARKER"]]]` | `{"prefix":"G09-D-","width":4,"function":"test_schema_policy_case"}` |
| K | 160/155/5 | `[["layout",["L","S","P","C"]],["workflow",["MIGRATE","RESUME","BACKUP","RESTORE","IMPORT"]],["actual_hook",["BEFORE_PREFLIGHT","AFTER_PREFLIGHT","AFTER_DB_BACKUP","DURING_DB_WRITE","AFTER_DB_COMMIT","AFTER_PAIRED_WITNESS_STAGED","BEFORE_COMPLETE_MARKER","AFTER_COMPLETE_MARKER"]]]` | `{"prefix":"G09-K-","width":3,"function":"test_workflow_crash_cut"}` |
| R | 960/960/0 | `[["layout",["P","C"]],["delete_state",["VERIFIED_NONE","CURRENT_NEW_INTENT","CURRENT_NEW_TOMBSTONE","JOURNAL_MISSING","CORRUPT_OR_INCOMPLETE"]],["ledger_state",["VERIFIED_SAME","CURRENT_VALID_SUCCESSOR_SETTLEMENT","WITNESS_MISSING","DB_WITNESS_MISMATCH","LEGACY_UNSCOPED","NOT_INCLUDED"]],["key_relinked",[false,true]],["old_active_grant",[false,true]],["workflow",["RESTORE","IMPORT"]],["mode",["STRICT","GENERAL"]]]` | `{"prefix":"G09-R-","width":3,"function":"test_restore_authority_matrix"}` |
| A | 1024/1024/0 | `[["delete_history",[false,true]],["cost_authority",[false,true]],["witness",[false,true]],["exposure_period",[false,true]],["key_relink",[false,true]],["new_scope_consent",[false,true]],["new_runtime_binding",[false,true]],["feature",["STT","SUMMARY"]],["workflow",["RESTORE","IMPORT"]],["budget_mode",["VERIFIED","USER_CAP"]]]` | `{"prefix":"G09-A-","width":4,"function":"test_reactivation_matrix"}` |
| B | 216/198/18 | `[["layout",["L","S","P","C"]],["action",["OPEN","MIGRATE","RESUME","BACKUP","RESTORE","IMPORT"]],["busy_boundary",["ROOT","SECURITY_COORDINATOR","SQLITE"]],["release",["BEFORE_DEADLINE","AT_DEADLINE","NOT_RELEASED"]]]` | `{"prefix":"G09-B-","width":3,"function":"test_busy_budget_case"}` |
| H | 24/24/0 | `{"versioned_case_named_line":218}` | `{"prefix":"G09-H-","width":2,"function":"test_handoff_case"}` |
| P | 32/32/0 | `{"versioned_case_named_line":220}` | `{"prefix":"G09-P-","width":2,"function":"test_package_rejection_case"}` |
| W | 36/30/6 | `[["layout",["L","S","P","C"]],["DB_state",["NO_WAL","COMMIT_ONLY_IN_WAL","OPEN_WRITE_TRANSACTION"]],["media",["ABSENT","SEALED_PREFIX","STAGING"]]]` | `{"prefix":"G09-W-","width":2,"function":"test_snapshot_set_matrix"}` |
| O | 24/24/0 | `[["layout",["P","C"]],["race",["MAINTENANCE_VS_NEW_JOB","BACKUP_FREEZE_VS_DELETE","REVOKE_VS_OLD_PERMIT_WRITE","TWO_COORDINATOR_RESUME_CLAIMS","KEY_RELINK_VS_EXECUTION_CHANGE","TARGET_PUBLISH_VS_CANCEL"]],["order",["A_FIRST","B_FIRST"]]]` | `{"prefix":"G09-O-","width":2,"function":{"a":"test_core_race_case","b":"test_restore_race_case"}}` |
| J | 96/96/0 | `[["delete_state",["NO_INTENT","DB_ONLY_PENDING","JOURNAL_ONLY_INTENT","SAME_G_DJ_PENDING","COMPLETED_TOMBSTONE_SAME_G_JOURNAL","DJ_GENERATION_CONFLICT","SESSION_GENERATION_AFTER_G","CORRUPT_OR_INCOMPLETE"]],["action",["MIGRATE","BACKUP","RESTORE","IMPORT"]],["layout",["L","P","C"]]]` | `{"prefix":"G09-J-","width":3,"function":"test_delete_history_matrix"}` |
| C | 120/120/0 | `[["cost_profile",["VALID_V1_ONLY","AUTHENTICATED_V2_META8","V2_EMPTY_AUDIT","FUTURE_HIGH_WATER_EMPTY_AUDIT","RESET_AUDIT_PAST_FUTURE_SETTLED","RESET_AUDIT_UNKNOWN","PARTIAL_V2","DB_WITNESS_MISMATCH","RESET_WITNESS_EXTENSION_MISSING","FUTURE_WITNESS_EXTENSION"]],["action",["MIGRATE","BACKUP","RESTORE","IMPORT"]],["layout",["S","P","C"]]]` | `{"prefix":"G09-C-","width":3,"function":"test_cost_profile_matrix"}` |
| I | 75/75/0 | `[["projection_state",["ABSENT","VALID","WRONG_EMPTY","OLD_ROOT_EPOCH_CACHE_CALLBACK","NORMAL_STAMP_CORRUPT_JOURNAL"]],["action",["OPEN","MIGRATE","BACKUP","RESTORE","IMPORT"]],["layout",["L","P","C"]]]` | `{"prefix":"G09-I-","width":3,"function":"test_projection_source_matrix"}` |
| Q | 42/42/0 | `[["ack_state",["CONSUMER_ACTIVE","CONSUMER_DONE_SEALER_ACTIVE","CONSUMER_DONE_FIFO_PENDING","SOURCE_ACK_UNKNOWN","STORE_FAILED_TERMINATION_UNKNOWN","ALL_SOURCE_CONSUMER_SEALER_ACK","EXPORT_READER_ACTIVE"]],["action",["MIGRATE","BACKUP"]],["layout",["L","P","C"]]]` | `{"prefix":"G09-Q-","width":3,"function":"test_store_ack_matrix"}` |
| T | 72/72/0 | `[["health_state",["LEGACY_ONLY_H0_G0","VALID_OPEN_PREFIX","CLOSED_UNKNOWN_GAP","OPEN_STABLE_TAIL_EXISTS","REGISTERED_PARTIAL_OR_CORRUPT","FUTURE_HEALTH"]],["action",["MIGRATE","BACKUP","RESTORE","IMPORT"]],["layout",["L","P","C"]]]` | `{"prefix":"G09-T-","width":3,"function":"test_health_handoff_matrix"}` |

### 10.2 Existing selected named115: preserve IDs, apply effective overrides

These 115 rows are already inside 3982, not an increment. NW12/OP23/AD20 remain in the preserved versioned base (55 rows). Only the named definitions absent there are transcribed; base3812 rows are not copied.

| ID / owner / primary | Literal input | Hand oracle | Fault labels |
| --- | --- | --- | --- |
| `G09a-C2-A01 / a / tests/integration/test_migration_backup.py::test_legacy_activation_contract[G09a-C2-A01]` | `{"literal_input_ko":"a 일반 정상 legacy1 호출"}` | `{"literal_oracle_ko":"기존 기능/원본/물리1 보존, 암묵2 전환0"}` | `["C2.M01"]` |
| `G09a-C2-A02 / a / tests/integration/test_migration_backup.py::test_legacy_activation_contract[G09a-C2-A02]` | `{"literal_input_ko":"a 일반 빈 store 생성"}` | `{"literal_oracle_ko":"기존 store별0/1 생성 계약 보존, registry2 임의 생성0"}` | `[]` |
| `G09a-C2-A03 / a / tests/integration/test_migration_backup.py::test_legacy_activation_contract[G09a-C2-A03]` | `{"literal_input_ko":"같은 legacy의 명시 plan"}` | `{"literal_oracle_ko":"MIGRATION_REQUIRED, source DDL/version/witness 변경0"}` | `["C2.M02"]` |
| `G09a-C2-A04 / a / tests/integration/test_migration_backup.py::test_legacy_activation_contract[G09a-C2-A04]` | `{"literal_input_ko":"정상 legacy의 명시 승인 apply"}` | `{"literal_oracle_ko":"before-image 검증 뒤 정확 profile2, 원래 논리 자료·media hash 보존"}` | `[]` |
| `G09a-C2-A05 / a / tests/integration/test_migration_backup.py::test_legacy_activation_contract[G09a-C2-A05]` | `{"literal_input_ko":"A04 commit 뒤 소유 journal 재개"}` | `{"literal_oracle_ko":"일치 단계 재적용0, 중복 rows/receipt/DDL0"}` | `[]` |
| `G09a-C2-A06 / a / tests/integration/test_migration_backup.py::test_legacy_activation_contract[G09a-C2-A06]` | `{"literal_input_ko":"a current-only helper로 legacy 검사"}` | `{"literal_oracle_ko":"정상 앱용 결과 MREQ·stores 생성0. 실제 UI/CLI 연결 완료로 세지 않음"}` | `[]` |
| `G09a-C2-R01 / a / tests/integration/test_migration_backup.py::test_component_only_profiles[G09a-C2-R01]` | `{"literal_input_ko":"jobs-only0+session binding의 명시 전환"}` | `{"literal_oracle_ko":"jobs role만, Library 권위 생성/요구0, 기존 Job/fence 보존"}` | `["C2.M03"]` |
| `G09a-C2-R02 / a / tests/integration/test_migration_backup.py::test_component_only_profiles[G09a-C2-R02]` | `{"literal_input_ko":"jobs-only1의 알려진 receipt 부재 profile"}` | `{"literal_oracle_ko":"명시 전환에서 job-ID receipt만 backfill, alias 이력 발명0·종료 Job 불변"}` | `["C2.M03"]` |
| `G09a-C2-R03 / a / tests/integration/test_migration_backup.py::test_component_only_profiles[G09a-C2-R03]` | `{"literal_input_ko":"Library-backed content, Job/security 없음"}` | `{"literal_oracle_ko":"role library+content, FK/trigger/CAS·설정 보존, 빈 ledger 자동생성0"}` | `[]` |
| `G09a-C2-R04 / a / tests/integration/test_migration_backup.py::test_component_only_profiles[G09a-C2-R04]` | `{"literal_input_ko":"bare content 표만 존재"}` | `{"literal_oracle_ko":"명시 profile 거부, source 변경/Library 표 추정 생성0"}` | `["C2.M04"]` |
| `G09a-C2-R05 / a / tests/integration/test_migration_backup.py::test_component_only_profiles[G09a-C2-R05]` | `{"literal_input_ko":"sessions(session_id) 한 열+Job 표만 존재"}` | `{"literal_oracle_ko":"완전 Library profile로 명시 migration 거부. a 일반 legacy 회귀와 구분"}` | `["C2.M04"]` |
| `G09a-C2-R06 / a / tests/integration/test_migration_backup.py::test_component_only_profiles[G09a-C2-R06]` | `{"literal_input_ko":"빈0 DB+기존 cost witness"}` | `{"literal_oracle_ko":"신규 EMPTY 인증0·witness 재서명0·빈 예산 생성0"}` | `[]` |
| `G09a-C2-S01 / a / tests/integration/test_maintenance_crash.py::test_root_protocol_refusal[G09a-C2-S01]` | `{"protocol":"ATOMIC","body_state":"IDENTIFIABLE_ORPHAN"}` | `{"normal_admission":0,"source_bytes_position_preserved":true,"automatic_repair_move_delete":0,"closed_result":"UNAVAILABLE"}` | `["C2.M05"]` |
| `G09a-C2-S02 / a / tests/integration/test_maintenance_crash.py::test_root_protocol_refusal[G09a-C2-S02]` | `{"protocol":"STAGE","body_state":"IDENTIFIABLE_ORPHAN"}` | `{"normal_admission":0,"source_bytes_position_preserved":true,"automatic_repair_move_delete":0,"closed_result":"UNAVAILABLE"}` | `[]` |
| `G09a-C2-S03 / a / tests/integration/test_maintenance_crash.py::test_root_protocol_refusal[G09a-C2-S03]` | `{"protocol":"LEGACY_TMP","body_state":"IDENTIFIABLE_ORPHAN"}` | `{"normal_admission":0,"source_bytes_position_preserved":true,"automatic_repair_move_delete":0,"closed_result":"UNAVAILABLE"}` | `[]` |
| `G09a-C2-S04 / a / tests/integration/test_maintenance_crash.py::test_root_protocol_refusal[G09a-C2-S04]` | `{"protocol":"ATOMIC","body_state":"TRUNCATED_ORPHAN"}` | `{"normal_admission":0,"source_bytes_position_preserved":true,"automatic_repair_move_delete":0,"closed_result":"UNAVAILABLE"}` | `[]` |
| `G09a-C2-S05 / a / tests/integration/test_maintenance_crash.py::test_root_protocol_refusal[G09a-C2-S05]` | `{"protocol":"STAGE","body_state":"TRUNCATED_ORPHAN"}` | `{"normal_admission":0,"source_bytes_position_preserved":true,"automatic_repair_move_delete":0,"closed_result":"UNAVAILABLE"}` | `[]` |
| `G09a-C2-S06 / a / tests/integration/test_maintenance_crash.py::test_root_protocol_refusal[G09a-C2-S06]` | `{"protocol":"LEGACY_TMP","body_state":"TRUNCATED_ORPHAN"}` | `{"normal_admission":0,"source_bytes_position_preserved":true,"automatic_repair_move_delete":0,"closed_result":"UNAVAILABLE"}` | `[]` |
| `G09a-C2-S07 / a / tests/integration/test_maintenance_crash.py::test_root_protocol_refusal[G09a-C2-S07]` | `{"protocol":"ATOMIC","body_state":"JSON_ARRAY_WRONG_TYPE"}` | `{"normal_admission":0,"source_bytes_position_preserved":true,"automatic_repair_move_delete":0,"closed_result":"UNAVAILABLE"}` | `["C2.M05"]` |
| `G09a-C2-S08 / a / tests/integration/test_maintenance_crash.py::test_root_protocol_refusal[G09a-C2-S08]` | `{"protocol":"STAGE","body_state":"JSON_ARRAY_WRONG_TYPE"}` | `{"normal_admission":0,"source_bytes_position_preserved":true,"automatic_repair_move_delete":0,"closed_result":"UNAVAILABLE"}` | `[]` |
| `G09a-C2-S09 / a / tests/integration/test_maintenance_crash.py::test_root_protocol_refusal[G09a-C2-S09]` | `{"protocol":"LEGACY_TMP","body_state":"JSON_ARRAY_WRONG_TYPE"}` | `{"normal_admission":0,"source_bytes_position_preserved":true,"automatic_repair_move_delete":0,"closed_result":"UNAVAILABLE"}` | `[]` |
| `G09a-C2-S10 / a / tests/integration/test_maintenance_crash.py::test_root_protocol_refusal[G09a-C2-S10]` | `{"actor_state":"CURRENT_EXACT_PENDING_ACK"}` | `{"normal_admission":0,"source_bytes_position_preserved":true,"automatic_repair_move_delete":0,"closed_result":"BUSY_ACK_PENDING"}` | `[]` |
| `G09a-C2-S11 / a / tests/integration/test_maintenance_crash.py::test_root_protocol_refusal[G09a-C2-S11]` | `{"actor_state":"STAGE_NONCE_MISMATCH"}` | `{"normal_admission":0,"source_bytes_position_preserved":true,"automatic_repair_move_delete":0,"closed_result":"UNAVAILABLE"}` | `["C2.M06"]` |
| `G09a-C2-S12 / a / tests/integration/test_maintenance_crash.py::test_root_protocol_refusal[G09a-C2-S12]` | `{"actor_state":"STAGE_OLD_ROOT_INSTANCE"}` | `{"normal_admission":0,"source_bytes_position_preserved":true,"automatic_repair_move_delete":0,"closed_result":"UNAVAILABLE"}` | `["C2.M06"]` |
| `G09a-GS11-AL-01 / a / tests/integration/test_migration_backup.py::test_gs11_alias_admission[G09a-GS11-AL-01]` | `{"protocol":"stage","case_variant":"upper_name","entry":"PLAN"}` | `{"history_status":"UNAVAILABLE","normal_permission":0,"before_image":0,"DDL":0,"complete_marker":0,"original_bytes_and_location_preserved":true,"negative_floor_preserved":true}` | `[]` |
| `G09a-GS11-AL-02 / a / tests/integration/test_migration_backup.py::test_gs11_alias_admission[G09a-GS11-AL-02]` | `{"protocol":"stage","case_variant":"upper_nonce","entry":"PLAN"}` | `{"history_status":"UNAVAILABLE","normal_permission":0,"before_image":0,"DDL":0,"complete_marker":0,"original_bytes_and_location_preserved":true,"negative_floor_preserved":true}` | `[]` |
| `G09a-GS11-AL-03 / a / tests/integration/test_migration_backup.py::test_gs11_alias_admission[G09a-GS11-AL-03]` | `{"protocol":"atomic","case_variant":"upper_name","entry":"PLAN"}` | `{"history_status":"UNAVAILABLE","normal_permission":0,"before_image":0,"DDL":0,"complete_marker":0,"original_bytes_and_location_preserved":true,"negative_floor_preserved":true}` | `[]` |
| `G09a-GS11-AL-04 / a / tests/integration/test_migration_backup.py::test_gs11_alias_admission[G09a-GS11-AL-04]` | `{"protocol":"atomic","case_variant":"upper_nonce","entry":"PLAN"}` | `{"history_status":"UNAVAILABLE","normal_permission":0,"before_image":0,"DDL":0,"complete_marker":0,"original_bytes_and_location_preserved":true,"negative_floor_preserved":true}` | `[]` |
| `G09a-GS11-AL-05 / a / tests/integration/test_migration_backup.py::test_gs11_alias_admission[G09a-GS11-AL-05]` | `{"protocol":"legacy","case_variant":"upper_name","entry":"PLAN"}` | `{"history_status":"UNAVAILABLE","normal_permission":0,"before_image":0,"DDL":0,"complete_marker":0,"original_bytes_and_location_preserved":true,"negative_floor_preserved":true}` | `[]` |
| `G09a-GS11-AL-06 / a / tests/integration/test_migration_backup.py::test_gs11_alias_admission[G09a-GS11-AL-06]` | `{"protocol":"legacy","case_variant":"upper_nonce","entry":"PLAN"}` | `{"history_status":"UNAVAILABLE","normal_permission":0,"before_image":0,"DDL":0,"complete_marker":0,"original_bytes_and_location_preserved":true,"negative_floor_preserved":true}` | `[]` |
| `G09a-GS11-AL-07 / a / tests/integration/test_migration_backup.py::test_gs11_alias_admission[G09a-GS11-AL-07]` | `{"protocol":"stage","case_variant":"upper_name","entry":"APPLY_PREIMAGE"}` | `{"history_status":"UNAVAILABLE","normal_permission":0,"before_image":0,"DDL":0,"complete_marker":0,"original_bytes_and_location_preserved":true,"negative_floor_preserved":true}` | `[]` |
| `G09a-GS11-AL-08 / a / tests/integration/test_migration_backup.py::test_gs11_alias_admission[G09a-GS11-AL-08]` | `{"protocol":"stage","case_variant":"upper_nonce","entry":"APPLY_PREIMAGE"}` | `{"history_status":"UNAVAILABLE","normal_permission":0,"before_image":0,"DDL":0,"complete_marker":0,"original_bytes_and_location_preserved":true,"negative_floor_preserved":true}` | `[]` |
| `G09a-GS11-AL-09 / a / tests/integration/test_migration_backup.py::test_gs11_alias_admission[G09a-GS11-AL-09]` | `{"protocol":"atomic","case_variant":"upper_name","entry":"APPLY_PREIMAGE"}` | `{"history_status":"UNAVAILABLE","normal_permission":0,"before_image":0,"DDL":0,"complete_marker":0,"original_bytes_and_location_preserved":true,"negative_floor_preserved":true}` | `[]` |
| `G09a-GS11-AL-10 / a / tests/integration/test_migration_backup.py::test_gs11_alias_admission[G09a-GS11-AL-10]` | `{"protocol":"atomic","case_variant":"upper_nonce","entry":"APPLY_PREIMAGE"}` | `{"history_status":"UNAVAILABLE","normal_permission":0,"before_image":0,"DDL":0,"complete_marker":0,"original_bytes_and_location_preserved":true,"negative_floor_preserved":true}` | `[]` |
| `G09a-GS11-AL-11 / a / tests/integration/test_migration_backup.py::test_gs11_alias_admission[G09a-GS11-AL-11]` | `{"protocol":"legacy","case_variant":"upper_name","entry":"APPLY_PREIMAGE"}` | `{"history_status":"UNAVAILABLE","normal_permission":0,"before_image":0,"DDL":0,"complete_marker":0,"original_bytes_and_location_preserved":true,"negative_floor_preserved":true}` | `[]` |
| `G09a-GS11-AL-12 / a / tests/integration/test_migration_backup.py::test_gs11_alias_admission[G09a-GS11-AL-12]` | `{"protocol":"legacy","case_variant":"upper_nonce","entry":"APPLY_PREIMAGE"}` | `{"history_status":"UNAVAILABLE","normal_permission":0,"before_image":0,"DDL":0,"complete_marker":0,"original_bytes_and_location_preserved":true,"negative_floor_preserved":true}` | `[]` |
| `G09a-GS11-RC-01 / a / tests/integration/test_maintenance_crash.py::test_gs11_last_observation[G09a-GS11-RC-01]` | `{"literal_partition_or_events":["명시 PLAN의 마지막 root/body 관측 완료 → 잠금 밖 장벽 → 새 root orphan을 외부 장애 입력으로 생성(root stamp 변화) → 최종 cut 결속/plan 반환"]}` | `{"literal_oracle_ko":"과거 깨끗한 cut을 CURRENT/실행 가능한 plan으로 채택0. history UNAVAILABLE·normal 입장0, source 원본 불변·새 orphan 보존. source 생성자/DDL/완료 marker0."}` | `[]` |
| `G09a-GS11-RC-03 / a / tests/integration/test_maintenance_crash.py::test_gs11_last_observation[G09a-GS11-RC-03]` | `{"literal_partition_or_events":["깨끗한 승인 plan → 새 입장 gate 폐쇄·모든 실제 ACK → apply 마지막 read 완료 → 새 orphan(root stamp 변화) → before-image 전 최종 검사"]}` | `{"literal_oracle_ko":"before-image/DDL/완료 marker0, 재계획/권위 확인 보류. 새 evidence와 old negative/canonical/media 보존. actor 예외나 자기 capture 예외로 통과0."}` | `[]` |
| `G09a-GS11-RC-04 / a / tests/integration/test_maintenance_crash.py::test_gs11_last_observation[G09a-GS11-RC-04]` | `{"literal_partition_or_events":["같은 operation의 before-image 작성·검증까지 정상 완료 → DDL/최종 commit 전 새 orphan → 현재 cut 재검사 → 명시 rollback 시도"]}` | `{"literal_oracle_ko":"정상 완료0·operation 보류/MAINTENANCE_RESUME_REQUIRED의 정확 단계 보존. 새 evidence 뒤 옛 before-image를 source에 복원해 정상화0, rollback은 MIGRATION_ROLLBACK_UNSAFE. before-image·operation journal·현재 evidence는 보존하며 no-op/완료로 위장0. 사건은 DDL 전이라 사용자 data/physical version 변경0."}` | `[]` |
| `G09a-GS11-RC-05 / a / tests/integration/test_maintenance_crash.py::test_gs11_last_observation[G09a-GS11-RC-05]` | `{"literal_partition_or_events":["정상 apply의 commit+완료 marker·실제 반환까지 먼저 확인 → 그 뒤 새 orphan → **다음** 명시 plan/입장 검사"]}` | `{"literal_oracle_ko":"이미 완성된 operation/image/artifact를 자동 삭제/rollback/미완료로 재작성0. 다음 입장은 history 불명으로 차단, 새 orphan bytes 보존·자동 재실행0. 지난 완료 당시 무관측 외부 변경까지 탐지했다고 소급 주장하지 않음."}` | `[]` |
| `G09a-GS11-HA-01 / a / tests/integration/test_maintenance_crash.py::test_history_ack_and_late_result[G09a-GS11-HA-01]` | `{"literal_partition_or_events":["history task 수락/queued → 명시 maintenance가 입장 폐쇄·owner close/retire 요청 → 아직 worker 미시작 → 이후 worker 실제 실행/거부 반환·ACK"]}` | `{"literal_oracle_ko":"queued 수락분도 소유돼 있으므로 ACK 전 MAINTENANCE_BUSY, before-image/DDL0. close/cancel bool로 ACK 발명0. 뒤 실행은 닫힌 publish guard로 새 권한0, 실제 반환/ACK 뒤에만 소유권 회수."}` | `["HA.M01","HA.M02"]` |
| `G09a-GS11-HA-02 / a / tests/integration/test_maintenance_crash.py::test_history_ack_and_late_result[G09a-GS11-HA-02]` | `{"literal_partition_or_events":["실제 reader running/마지막 publish 전 장벽 → 유지보수 입장 폐쇄·publish guard 무효화 → reader 미반환 대조 → release·실제 반환/ACK"]}` | `{"literal_oracle_ko":"미반환 때 before-image/DDL0. 실제 verify는 새 READY receipt 발급0·known dead(g7) 부정 사실 보존. stale 결과라도 실제 ACK bookkeeping은1회, 새 요청 admission은 닫힘."}` | `["HA.M01"]` |
| `G09a-GS11-HA-03 / a / tests/integration/test_maintenance_crash.py::test_history_ack_and_late_result[G09a-GS11-HA-03]` | `{"literal_partition_or_events":["옛 요청이 실제 READY 반환, 메시지만 대기 → 같은 root에서 maintenance epoch 전진 → **새 current 권위 재검사를 아직 장벽으로 보류** → 옛 READY 전달"]}` | `{"literal_oracle_ko":"옛 결과로 current 재검사/ACK/permit·DDL 완료를 대신0. 현재 recheck가 끝날 때까지 before-image/DDL0, operation epoch/단계 불변. root path가 같아도 옛 epoch는 현재가 아님."}` | `["HA.M03"]` |
| `G09a-GS11-HA-04 / a / tests/integration/test_maintenance_crash.py::test_history_ack_and_late_result[G09a-GS11-HA-04]` | `{"literal_partition_or_events":["옛 요청의 실제 일시 I/O 실패/UNAVAILABLE 반환·ACK → fault 해제·현재 epoch의 독립 fresh/recheck 성공 → 뒤늦게 옛 실패 메시지 전달"]}` | `{"literal_oracle_ko":"현재 검사 결과/operation 단계/권위 수명을 옛 실패로 덮어쓰기0·자동 rollback0·새 작업 생성0. 실패 이력은 진단에 보존할 수 있으나 현재 요청의 종료/재검사 필요를 발명0."}` | `["HA.M03"]` |
| `G09a-GS11-HA-05 / a / tests/integration/test_maintenance_crash.py::test_history_ack_and_late_result[G09a-GS11-HA-05]` | `{"literal_partition_or_events":["req1 실제 완료/ACK 처리 → 같은 root의 req2 실제 running → req1의 옛 완료를 중복 전달 → 유지보수 입장 요청 → req2 실제 종료/ACK"]}` | `{"literal_oracle_ko":"completed(req1) 재호출이 req2 inflight/reader count를 지우거나 ACK하지 않음. req2 미반환 때 BUSY·before-image0, 실제 req2 ACK 뒤에만 해제. root/epoch만 맞춘 오래된 request identity도 실패."}` | `[]` |
| `G09a-GS11-HA-06 / a / tests/integration/test_maintenance_crash.py::test_history_ack_and_late_result[G09a-GS11-HA-06]` | `{"literal_partition_or_events":["옛 root owner의 실제 reader 종료·ACK → old owner/store 정리·같은 path 재열기, 새 instance → 옛 READY 메시지 전달"]}` | `{"literal_oracle_ko":"새 instance에 옛 receipt/permit/owner 등록·callback 권한 이식0. 새 root의 독립 current 검사 필요, kept/media와 dead tombstone 보존. path/요청 숫자 같음은 신원 증명 아님."}` | `[]` |
| `G09a-GS11-HA-07 / a / tests/integration/test_maintenance_crash.py::test_history_ack_and_late_result[G09a-GS11-HA-07]` | `{"literal_partition_or_events":["reader running 중 maintenance를 사용자가 취소, source DDL 전 → owner retire/취소 요청 → reader는 아직 살아 있음 → 실제 반환/ACK → 늦은 메시지"]}` | `{"literal_oracle_ko":"취소 즉시 소유권 해제0, source/library를 살아 있는 reader 아래에서 닫거나 사용자 쓰기 입장을 열지 않음. ACK 뒤 취소 수명만1회 정리, 늦은 결과로 migration 시작/완료·자동 resume0."}` | `["HA.M02"]` |
| `G09a-GS11-HA-08 / a / tests/integration/test_maintenance_crash.py::test_history_ack_and_late_result[G09a-GS11-HA-08]` | `{"literal_partition_or_events":["current reader running → 실제 canonical read OSError → reader/finally 실제 종료·실패 결과/ACK → fault를 제거한 뒤 사용자가 **새 명시 plan** 요청"]}` | `{"literal_oracle_ko":"실패 결과도 실제 reader 종료 ACK로1회 처리, active history owner0. 첫 실패를 READY/정상 완료로 세지 않으며 source/negative floor 보존. 이후 새 검사 성공/정상 입장 가능, 이미 죽은 reader 때문에 영구 BUSY로 남지 않음. 자동 재개는 하지 않음."}` | `["HA.M04"]` |
| `G09a-GS05-REG-01 / a / tests/unit/test_maintenance.py::test_registration_completion_binding[G09a-GS05-REG-01]` | `{"partition":{"registry":"UNKNOWN","entries":0,"caller_complete":false,"seal":"ABSENT"},"events":["request actual maintenance entry before any retire"]}` | `{"literal_oracle":["MAINTENANCE_BUSY","retire=0","before_image=0","DDL=0","proof=0","existing_owner_and_handles_preserved"]}` | `[]` |
| `G09a-GS05-REG-02 / a / tests/unit/test_maintenance.py::test_registration_completion_binding[G09a-GS05-REG-02]` | `{"partition":{"registry":"UNKNOWN","entries":0,"caller_complete":true,"seal":"ABSENT"},"events":["submit complete=True/empty-list claim to same entry"]}` | `{"literal_oracle":["no completion promotion","MAINTENANCE_BUSY","retire=before_image=DDL=proof=0"]}` | `["GS05.REG-M01"]` |
| `G09a-GS05-REG-03 / a / tests/unit/test_maintenance.py::test_registration_completion_binding[G09a-GS05-REG-03]` | `{"partition":{"registry":"PARTIAL","entries":"known J only","hidden_required_actor":"registered producer expects service B","candidate_descriptor":"current owner-authenticated registration candidate; not yet completion-sealed","entry_domain":"CONTROLLED_CORE_ARENA","all_other_bindings":"current root/DB/epoch valid; only expected-set coverage fails"},"events":["current owner prepares authenticated registration candidate containing J only","validate each visible identity and all root/DB/epoch/domain bindings successfully","required producer set also contains B with accepted fake-native task","attempt completion sealing and C1 with B omitted"]}` | `{"literal_oracle":["completion_seal_issued=0 due to producer-set mismatch; not due to caller-boolean/auth/domain refusal","expected producer-set mismatch remains UNKNOWN","retire=before_image=DDL=0","B retains original owner/handles"]}` | `["GS05.REG-M02"]` |
| `G09a-GS05-REG-04 / a / tests/unit/test_maintenance.py::test_registration_completion_binding[G09a-GS05-REG-04]` | `{"partition":{"registry":"SEALED","seal_root":"root-A","request_root":"root-B","physical_database_set":"different"},"events":["submit genuine foreign owner-issued seal"]}` | `{"literal_oracle":["MAINTENANCE_BUSY","retire=before_image=DDL=proof=0","foreign owner/DB untouched"]}` | `["GS05.REG-M03"]` |
| `G09a-GS05-REG-05 / a / tests/unit/test_maintenance.py::test_registration_completion_binding[G09a-GS05-REG-05]` | `{"partition":{"registry":"SEALED","sealed_epoch":7,"current_epoch":8,"change":"participant instance replacement"},"events":["freeze registry at epoch7","replace participant under same root at epoch8","submit old seal"]}` | `{"literal_oracle":["MAINTENANCE_BUSY","retire=before_image=DDL=0","old ACK cannot certify new instance"]}` | `["GS05.REG-M04"]` |
| `G09a-GS05-REG-06 / a / tests/unit/test_maintenance.py::test_registration_completion_binding[G09a-GS05-REG-06]` | `{"partition":{"registry":"OWNER_SEALED","domain":"CONTROLLED_CORE_ARENA","producer_set":"complete explicit fixture set","root_DB_epoch":"exact current"},"events":["owner-controlled closed producer arena creates all participants","perform same public core entry with validated domain and coverage","complete actual accepted drain"]}` | `{"literal_oracle":["normal core entry and before_image exactly1","no operating GUI/native certification token emitted","real call counts and bound identities observed","UNKNOWN/foreign/partial inputs remain refused"]}` | `[]` |
| `G09a-GS05-REG-07 / a / tests/unit/test_maintenance.py::test_registration_completion_binding[G09a-GS05-REG-07]` | `{"partition":{"seal":"genuine current CORE_ARENA seal","root_DB_epoch":"all match","core_producers":"complete","entry_domain":"OPERATING_ROOT selected by trusted entry, not caller option","production_bootstrap":"UNESTABLISHED"},"events":["present valid core-limited seal to operating entry","hold root, DB, epoch and core coverage constant so only domain/provenance differs"]}` | `{"literal_oracle":["MAINTENANCE_BUSY","retire=before_image=DDL=proof=0","no GUI/native-safe certification emitted","same seal remains valid at controlled core entry REG06"],"same_still_current_CORE_seal_operating_then_core_positive":true}` | `["GS05.REG-M05"]` |
| `G09a-GS05-ACK-01 / a / tests/integration/test_maintenance_crash.py::test_registered_secret_actor_drain[G09a-GS05-ACK-01]` | `{"partition":{"actor":"actual CredentialService on fake vault","pending":1,"reads":0,"requests":0,"native_command":"accepted before C1; held"},"events":["close registered admission before new work","hold fake-native command or queued execution","release within shared acquire remainder","wait actual command/callback/executor return"]}` | `{"literal_oracle":["before_image0 until actual native ACK","new enqueue/request0 after C1","accepted command preserved","before_image1 only after real ACK and valid deadline"]}` | `["GS05.ACK-M01"]` |
| `G09a-GS05-ACK-02 / a / tests/integration/test_maintenance_crash.py::test_registered_secret_actor_drain[G09a-GS05-ACK-02]` | `{"partition":{"actor":"actual CredentialService native get on fake vault","pending":0,"reads":1,"requests":0,"registered_direct_lease_owner":"explicit"},"events":["test-owned registered actor starts real read_claim before C1","pause actual native get outside locks","close admission","release read and its lease/actor exit explicitly"],"effective_order":["ACCEPTED_NATIVE_READS1","C1","VAULT_RETURN","BIND_LIVE","EXISTING_NATIVE_RETURN_HOOK","PUBLIC_RETURN_READS0_LEASE_LIVE","CLEAR_CALLBACK_BLOCKED_ACK0","CALLBACK_RETURN_ACK1","ALL_ACTOR_EXIT_IMAGE1"]}` | `{"literal_oracle":["before_image0 while read or lease/actor is owned","no read/request/native start after C1","actual return and lease/actor ACK precede image","source data unchanged"]}` | `[]` |
| `G09a-GS05-ACK-03 / a / tests/integration/test_maintenance_crash.py::test_registered_secret_actor_drain[G09a-GS05-ACK-03]` | `{"partition":{"actor":"actual Gateway paid request on fake transport/vault","pending":0,"reads":0,"requests":1,"cut":"native lease returned before O"},"events":["hold current request after native return before O","close C1","resume old request to policy refusal and real lease/ticket/connection cleanup","observe end_request"]}` | `{"literal_oracle":["O_register=0","dispatch=0","handoff=0","before_image0 until request/lease owner ACK","before_image1 only after actual safe cleanup","existing money reservation preserved or released only by FIN proof rule"]}` | `[]` |
| `G09a-GS05-ACK-04 / a / tests/integration/test_maintenance_crash.py::test_registered_secret_actor_drain[G09a-GS05-ACK-04]` | `{"partition":{"actor":"actual CredentialService executor","pending":0,"reads":0,"requests":0,"command_done_callback":"blocked; executor thread alive","join_returned":false},"events":["native command returns and counter reaches0 before command.done exits","start actual await_shutdown in owned waiter","advance shared deadline to10s","broker returns pending/BUSY while waiter joins","release callback after deadline","join returns for same owner/attempt"]}` | `{"literal_oracle":["before_image=DDL=0 before join return","counter0 is not native join ACK","gate/owner/drain retained after caller return","late ACK reclaimed exactly1","first attempt never promoted retroactively","safe release once; explicit new attempt required for next work"]}` | `["GS05.ACK-M02"]` |
| `G09b-GS05-ACK-05 / b / tests/integration/test_maintenance_crash.py::test_registered_secret_actor_drain[G09b-GS05-ACK-05]` | `{"partition":{"phase":"C6","old_service":"permanently closing","old_tokens":"ticket/plan/ref/preflight from old owner","new_runtime":"explicit fresh factory"},"events":["complete registered old actual join","construct new core service/execution through chosen factory","present old token to new owner and late UI reply to closed view"],"required_environment":"ACTUAL_UI_OPERATING_RECONSTRUCTION_B_SCOPE_PENDING"}` | `{"literal_oracle":["new_service is not old_service","old_closing remains true","old ticket/ref/plan/preflight do not authorize","late old reply publish0","fresh current binding path has positive control without real network"],"core_fake_alone_completes_ACK05":false}` | `["GS05.ACK-M03"]` |
| `G09a-GS05-FIN-01 / a / tests/integration/test_maintenance_crash.py::test_registered_financial_tail[G09a-GS05-FIN-01]` | `{"partition":{"reservation":"RESERVED60","dispatch_id":null,"owner":"same registered run/attempt","unsent_evidence":"complete; no open/handoff","requests":0},"events":["close C1 before O","registered current owner invokes existing CostLedger.release once","await actual DB/witness tail completion"]}` | `{"literal_oracle":["release_call1","state RELEASED","reserved0 and UNKNOWN0 for this independent account","confirmed and limit unchanged","paired witness coherent","O=dispatch=handoff0","before_image0 before tail ACK then1"]}` | `[]` |
| `G09a-GS05-FIN-02 / a / tests/integration/test_maintenance_crash.py::test_registered_financial_tail[G09a-GS05-FIN-02]` | `{"partition":{"reservation":"RESERVED60","dispatch_id":null,"owner":"registered","unsent_evidence":"missing or not attributable to same attempt","requests":0},"events":["only request/counter state is known","attempt unsent cleanup"]}` | `{"literal_oracle":["release_call0","reservation remains RESERVED60","MAINTENANCE_BUSY before C2 (proposed exact core result; X00 approval required)","before_image=DDL0","no inferred settlement or remote retry"]}` | `["GS05.FIN-M02"]` |
| `G09a-GS05-FIN-03 / a / tests/integration/test_maintenance_crash.py::test_registered_financial_tail[G09a-GS05-FIN-03]` | `{"partition":{"old_actor":"registered cleanup token","new_request":"different request nonce/same job or service","capability_claim":"cleanup=True","C1":"closed"},"events":["old permitted tail remains pending","new request borrows cleanup token to attempt O/dispatch/handoff"]}` | `{"literal_oracle":["new O register=0","new dispatch=0","new handoff=0","old UNKNOWN60/witness cleanup still progresses","image0 until old true ACK","no broad cleanup bypass"]}` | `["GS05.FIN-M03","BASE.M18"]` |
| `G09a-X-CT-01A / a / tests/integration/test_maintenance_crash.py::test_constructor_birth_linearization[G09a-X-CT-01A]` | `{"profile":"CORE_L_SINGLE","constructor":"Library","order":"A","events":["valid known profile and independent literal schema/role fixture; issued prior seal and bound core owner","constructor birth reservation wins common metadata cut","pause before first resource effect/public exposure outside product critical locks","maintenance C1 attempts freeze using prior seal","complete or actually unwind accepted constructor, close/ACK owned resources, request fresh seal/explicit next operation"],"partition":{},"r3_refinement":["nonauthorizing birth before actual resource-use acquisition","old-seal maintenance first attempt BUSY/image0/DDL0","acquire use outside critical locks","revalidate original identity/parent/role/epoch before first effect","actual lifetime close/ACK then fresh seal/new explicit positive image1"],"r3_lifetime":"actual same-DB aggregate shared use through actual children and connection close; no exclusive-per-object; missing parent/name slot overlaps finalized DB S","r3_observer":"actual resource-effect entry or public exposure for lazy ctor; private allocation/RLock is not I/O"}` | `{"literal_oracle":["C1 observes creation reservation/UNSEALED or epoch mismatch","first maintenance attempt MAINTENANCE_BUSY, image=DDL=0","accepted constructor is not erased or forcibly killed","source observer: reservation precedes first resource-effect entry/public exposure","only actual birth completion/unwind + owned handle ACK retires registration","fresh valid post-drain attempt has normal image1 control; no old-attempt promotion"],"r3_observer":"actual resource-effect entry or public exposure for lazy ctor; private allocation/RLock is not I/O"}` | `["CTID.CT-M-01"]` |
| `G09a-X-CT-01B / a / tests/integration/test_maintenance_crash.py::test_constructor_birth_linearization[G09a-X-CT-01B]` | `{"profile":"CORE_L_SINGLE","constructor":"Library","order":"B","events":["valid known profile and independent literal schema/role fixture; issued prior seal and bound core owner","valid C1 freeze wins common metadata cut","new direct public constructor called with valid old parent/raw public reference","maintenance continues over previously accepted actors only"],"partition":{},"r3_refinement":["C1 actual admission X held continuously","new valid constructor arguments","birth/public return/first source-effect0","old frozen operation positive retained"],"r3_lifetime":"actual same-DB aggregate shared use through actual children and connection close; no exclusive-per-object; missing parent/name slot overlaps finalized DB S","r3_observer":"actual resource-effect entry or public exposure for lazy ctor; private allocation/RLock is not I/O"}` | `{"literal_oracle":["new birth reservation refused with proposed StateConflict(MAINTENANCE_BUSY)","first resource-effect entry/public instance return=0","new source writes/lock O_CREAT/SQL/executor/native/worker=0 where applicable","private allocation of RLock/empty Python object is not treated as resource I/O","original frozen operation has normal image1 after true old ACK","no existing accepted payload/drain removed"],"r3_observer":"actual resource-effect entry or public exposure for lazy ctor; private allocation/RLock is not I/O"}` | `[]` |
| `G09a-X-CT-02A / a / tests/integration/test_maintenance_crash.py::test_constructor_birth_linearization[G09a-X-CT-02A]` | `{"profile":"CORE_L_SINGLE","constructor":"JobStore","order":"A","events":["valid known profile and independent literal schema/role fixture; issued prior seal and bound core owner","constructor birth reservation wins common metadata cut","pause before first resource effect/public exposure outside product critical locks","maintenance C1 attempts freeze using prior seal","complete or actually unwind accepted constructor, close/ACK owned resources, request fresh seal/explicit next operation"],"partition":{},"r3_refinement":["nonauthorizing birth before actual resource-use acquisition","old-seal maintenance first attempt BUSY/image0/DDL0","acquire use outside critical locks","revalidate original identity/parent/role/epoch before first effect","actual lifetime close/ACK then fresh seal/new explicit positive image1"],"r3_lifetime":"actual same-DB aggregate shared use through actual children and connection close; no exclusive-per-object; missing parent/name slot overlaps finalized DB S","r3_observer":"actual resource-effect entry or public exposure for lazy ctor; private allocation/RLock is not I/O"}` | `{"literal_oracle":["C1 observes creation reservation/UNSEALED or epoch mismatch","first maintenance attempt MAINTENANCE_BUSY, image=DDL=0","accepted constructor is not erased or forcibly killed","source observer: reservation precedes first resource-effect entry/public exposure","only actual birth completion/unwind + owned handle ACK retires registration","fresh valid post-drain attempt has normal image1 control; no old-attempt promotion"],"r3_observer":"actual resource-effect entry or public exposure for lazy ctor; private allocation/RLock is not I/O"}` | `["CTID.CT-M-02"]` |
| `G09a-X-CT-02B / a / tests/integration/test_maintenance_crash.py::test_constructor_birth_linearization[G09a-X-CT-02B]` | `{"profile":"CORE_L_SINGLE","constructor":"JobStore","order":"B","events":["valid known profile and independent literal schema/role fixture; issued prior seal and bound core owner","valid C1 freeze wins common metadata cut","new direct public constructor called with valid old parent/raw public reference","maintenance continues over previously accepted actors only"],"partition":{},"r3_refinement":["C1 actual admission X held continuously","new valid constructor arguments","birth/public return/first source-effect0","old frozen operation positive retained"],"r3_lifetime":"actual same-DB aggregate shared use through actual children and connection close; no exclusive-per-object; missing parent/name slot overlaps finalized DB S","r3_observer":"actual resource-effect entry or public exposure for lazy ctor; private allocation/RLock is not I/O"}` | `{"literal_oracle":["new birth reservation refused with proposed StateConflict(MAINTENANCE_BUSY)","first resource-effect entry/public instance return=0","new source writes/lock O_CREAT/SQL/executor/native/worker=0 where applicable","private allocation of RLock/empty Python object is not treated as resource I/O","original frozen operation has normal image1 after true old ACK","no existing accepted payload/drain removed"],"r3_observer":"actual resource-effect entry or public exposure for lazy ctor; private allocation/RLock is not I/O"}` | `[]` |
| `G09a-X-CT-03A / a / tests/integration/test_maintenance_crash.py::test_constructor_birth_linearization[G09a-X-CT-03A]` | `{"profile":"CORE_L_SINGLE","constructor":"ContentStore","order":"A","events":["valid known profile and independent literal schema/role fixture; issued prior seal and bound core owner","constructor birth reservation wins common metadata cut","pause before first resource effect/public exposure outside product critical locks","maintenance C1 attempts freeze using prior seal","complete or actually unwind accepted constructor, close/ACK owned resources, request fresh seal/explicit next operation"],"partition":{},"r3_refinement":["nonauthorizing birth before actual resource-use acquisition","old-seal maintenance first attempt BUSY/image0/DDL0","acquire use outside critical locks","revalidate original identity/parent/role/epoch before first effect","actual lifetime close/ACK then fresh seal/new explicit positive image1"],"r3_lifetime":"actual same-DB aggregate shared use through actual children and connection close; no exclusive-per-object; missing parent/name slot overlaps finalized DB S","r3_observer":"actual resource-effect entry or public exposure for lazy ctor; private allocation/RLock is not I/O"}` | `{"literal_oracle":["C1 observes creation reservation/UNSEALED or epoch mismatch","first maintenance attempt MAINTENANCE_BUSY, image=DDL=0","accepted constructor is not erased or forcibly killed","source observer: reservation precedes first resource-effect entry/public exposure","only actual birth completion/unwind + owned handle ACK retires registration","fresh valid post-drain attempt has normal image1 control; no old-attempt promotion"],"r3_observer":"actual resource-effect entry or public exposure for lazy ctor; private allocation/RLock is not I/O"}` | `["CTID.CT-M-03"]` |
| `G09a-X-CT-03B / a / tests/integration/test_maintenance_crash.py::test_constructor_birth_linearization[G09a-X-CT-03B]` | `{"profile":"CORE_L_SINGLE","constructor":"ContentStore","order":"B","events":["valid known profile and independent literal schema/role fixture; issued prior seal and bound core owner","valid C1 freeze wins common metadata cut","new direct public constructor called with valid old parent/raw public reference","maintenance continues over previously accepted actors only"],"partition":{},"r3_refinement":["C1 actual admission X held continuously","new valid constructor arguments","birth/public return/first source-effect0","old frozen operation positive retained"],"r3_lifetime":"actual same-DB aggregate shared use through actual children and connection close; no exclusive-per-object; missing parent/name slot overlaps finalized DB S","r3_observer":"actual resource-effect entry or public exposure for lazy ctor; private allocation/RLock is not I/O"}` | `{"literal_oracle":["new birth reservation refused with proposed StateConflict(MAINTENANCE_BUSY)","first resource-effect entry/public instance return=0","new source writes/lock O_CREAT/SQL/executor/native/worker=0 where applicable","private allocation of RLock/empty Python object is not treated as resource I/O","original frozen operation has normal image1 after true old ACK","no existing accepted payload/drain removed"],"r3_observer":"actual resource-effect entry or public exposure for lazy ctor; private allocation/RLock is not I/O"}` | `[]` |
| `G09a-X-CT-04A / a / tests/integration/test_maintenance_crash.py::test_constructor_birth_linearization[G09a-X-CT-04A]` | `{"profile":"CORE_P_SPLIT_AUTH","constructor":"ConsentStore","order":"A","events":["valid known profile and independent literal schema/role fixture; issued prior seal and bound core owner","constructor birth reservation wins common metadata cut","pause before first resource effect/public exposure outside product critical locks","maintenance C1 attempts freeze using prior seal","complete or actually unwind accepted constructor, close/ACK owned resources, request fresh seal/explicit next operation"],"partition":{},"r3_refinement":["nonauthorizing birth before actual resource-use acquisition","old-seal maintenance first attempt BUSY/image0/DDL0","acquire use outside critical locks","revalidate original identity/parent/role/epoch before first effect","actual lifetime close/ACK then fresh seal/new explicit positive image1"],"r3_lifetime":"actual same-DB aggregate shared use through actual children and connection close; no exclusive-per-object; missing parent/name slot overlaps finalized DB S","r3_observer":"actual resource-effect entry or public exposure for lazy ctor; private allocation/RLock is not I/O"}` | `{"literal_oracle":["C1 observes creation reservation/UNSEALED or epoch mismatch","first maintenance attempt MAINTENANCE_BUSY, image=DDL=0","accepted constructor is not erased or forcibly killed","source observer: reservation precedes first resource-effect entry/public exposure","only actual birth completion/unwind + owned handle ACK retires registration","fresh valid post-drain attempt has normal image1 control; no old-attempt promotion"],"r3_observer":"actual resource-effect entry or public exposure for lazy ctor; private allocation/RLock is not I/O"}` | `["CTID.CT-M-04"]` |
| `G09a-X-CT-04B / a / tests/integration/test_maintenance_crash.py::test_constructor_birth_linearization[G09a-X-CT-04B]` | `{"profile":"CORE_P_SPLIT_AUTH","constructor":"ConsentStore","order":"B","events":["valid known profile and independent literal schema/role fixture; issued prior seal and bound core owner","valid C1 freeze wins common metadata cut","new direct public constructor called with valid old parent/raw public reference","maintenance continues over previously accepted actors only"],"partition":{},"r3_refinement":["C1 actual admission X held continuously","new valid constructor arguments","birth/public return/first source-effect0","old frozen operation positive retained"],"r3_lifetime":"actual same-DB aggregate shared use through actual children and connection close; no exclusive-per-object; missing parent/name slot overlaps finalized DB S","r3_observer":"actual resource-effect entry or public exposure for lazy ctor; private allocation/RLock is not I/O"}` | `{"literal_oracle":["new birth reservation refused with proposed StateConflict(MAINTENANCE_BUSY)","first resource-effect entry/public instance return=0","new source writes/lock O_CREAT/SQL/executor/native/worker=0 where applicable","private allocation of RLock/empty Python object is not treated as resource I/O","original frozen operation has normal image1 after true old ACK","no existing accepted payload/drain removed"],"r3_observer":"actual resource-effect entry or public exposure for lazy ctor; private allocation/RLock is not I/O"}` | `[]` |
| `G09a-X-CT-05A / a / tests/integration/test_maintenance_crash.py::test_constructor_birth_linearization[G09a-X-CT-05A]` | `{"profile":"CORE_P_SPLIT_AUTH","constructor":"CostLedger","order":"A","events":["valid known profile and independent literal schema/role fixture; issued prior seal and bound core owner","constructor birth reservation wins common metadata cut","pause before first resource effect/public exposure outside product critical locks","maintenance C1 attempts freeze using prior seal","complete or actually unwind accepted constructor, close/ACK owned resources, request fresh seal/explicit next operation"],"partition":{},"r3_refinement":["nonauthorizing birth before actual resource-use acquisition","old-seal maintenance first attempt BUSY/image0/DDL0","acquire use outside critical locks","revalidate original identity/parent/role/epoch before first effect","actual lifetime close/ACK then fresh seal/new explicit positive image1"],"r3_lifetime":"actual same-DB aggregate shared use through actual children and connection close; no exclusive-per-object; missing parent/name slot overlaps finalized DB S","r3_observer":"actual resource-effect entry or public exposure for lazy ctor; private allocation/RLock is not I/O"}` | `{"literal_oracle":["C1 observes creation reservation/UNSEALED or epoch mismatch","first maintenance attempt MAINTENANCE_BUSY, image=DDL=0","accepted constructor is not erased or forcibly killed","source observer: reservation precedes first resource-effect entry/public exposure","only actual birth completion/unwind + owned handle ACK retires registration","fresh valid post-drain attempt has normal image1 control; no old-attempt promotion"],"r3_observer":"actual resource-effect entry or public exposure for lazy ctor; private allocation/RLock is not I/O"}` | `["CTID.CT-M-05"]` |
| `G09a-X-CT-05B / a / tests/integration/test_maintenance_crash.py::test_constructor_birth_linearization[G09a-X-CT-05B]` | `{"profile":"CORE_P_SPLIT_AUTH","constructor":"CostLedger","order":"B","events":["valid known profile and independent literal schema/role fixture; issued prior seal and bound core owner","valid C1 freeze wins common metadata cut","new direct public constructor called with valid old parent/raw public reference","maintenance continues over previously accepted actors only"],"partition":{},"r3_refinement":["C1 actual admission X held continuously","new valid constructor arguments","birth/public return/first source-effect0","old frozen operation positive retained"],"r3_lifetime":"actual same-DB aggregate shared use through actual children and connection close; no exclusive-per-object; missing parent/name slot overlaps finalized DB S","r3_observer":"actual resource-effect entry or public exposure for lazy ctor; private allocation/RLock is not I/O"}` | `{"literal_oracle":["new birth reservation refused with proposed StateConflict(MAINTENANCE_BUSY)","first resource-effect entry/public instance return=0","new source writes/lock O_CREAT/SQL/executor/native/worker=0 where applicable","private allocation of RLock/empty Python object is not treated as resource I/O","original frozen operation has normal image1 after true old ACK","no existing accepted payload/drain removed"],"r3_observer":"actual resource-effect entry or public exposure for lazy ctor; private allocation/RLock is not I/O"}` | `[]` |
| `G09a-X-CT-06A / a / tests/integration/test_maintenance_crash.py::test_constructor_birth_linearization[G09a-X-CT-06A]` | `{"profile":"CORE_L_SINGLE","constructor":"RecordingService","order":"A","events":["valid known profile and independent literal schema/role fixture; issued prior seal and bound core owner","constructor birth reservation wins common metadata cut","pause before first resource effect/public exposure outside product critical locks","maintenance C1 attempts freeze using prior seal","complete or actually unwind accepted constructor, close/ACK owned resources, request fresh seal/explicit next operation"],"partition":{},"r3_refinement":["nonauthorizing birth before actual resource-use acquisition","old-seal maintenance first attempt BUSY/image0/DDL0","acquire use outside critical locks","revalidate original identity/parent/role/epoch before first effect","actual lifetime close/ACK then fresh seal/new explicit positive image1"],"r3_lifetime":"actual same-DB aggregate shared use through actual children and connection close; no exclusive-per-object; missing parent/name slot overlaps finalized DB S","r3_observer":"actual resource-effect entry or public exposure for lazy ctor; private allocation/RLock is not I/O"}` | `{"literal_oracle":["C1 observes creation reservation/UNSEALED or epoch mismatch","first maintenance attempt MAINTENANCE_BUSY, image=DDL=0","accepted constructor is not erased or forcibly killed","source observer: reservation precedes first resource-effect entry/public exposure","only actual birth completion/unwind + owned handle ACK retires registration","fresh valid post-drain attempt has normal image1 control; no old-attempt promotion"],"r3_observer":"actual resource-effect entry or public exposure for lazy ctor; private allocation/RLock is not I/O"}` | `["CTID.CT-M-06"]` |
| `G09a-X-CT-06B / a / tests/integration/test_maintenance_crash.py::test_constructor_birth_linearization[G09a-X-CT-06B]` | `{"profile":"CORE_L_SINGLE","constructor":"RecordingService","order":"B","events":["valid known profile and independent literal schema/role fixture; issued prior seal and bound core owner","valid C1 freeze wins common metadata cut","new direct public constructor called with valid old parent/raw public reference","maintenance continues over previously accepted actors only"],"partition":{},"r3_refinement":["C1 actual admission X held continuously","new valid constructor arguments","birth/public return/first source-effect0","old frozen operation positive retained"],"r3_lifetime":"actual same-DB aggregate shared use through actual children and connection close; no exclusive-per-object; missing parent/name slot overlaps finalized DB S","r3_observer":"actual resource-effect entry or public exposure for lazy ctor; private allocation/RLock is not I/O"}` | `{"literal_oracle":["new birth reservation refused with proposed StateConflict(MAINTENANCE_BUSY)","first resource-effect entry/public instance return=0","new source writes/lock O_CREAT/SQL/executor/native/worker=0 where applicable","private allocation of RLock/empty Python object is not treated as resource I/O","original frozen operation has normal image1 after true old ACK","no existing accepted payload/drain removed"],"r3_observer":"actual resource-effect entry or public exposure for lazy ctor; private allocation/RLock is not I/O"}` | `[]` |
| `G09a-X-CT-07A / a / tests/integration/test_maintenance_crash.py::test_constructor_birth_linearization[G09a-X-CT-07A]` | `{"profile":"CORE_L_SINGLE","constructor":"ChunkWriter","order":"A","events":["valid known profile and independent literal schema/role fixture; issued prior seal and bound core owner","constructor birth reservation wins common metadata cut","pause before first resource effect/public exposure outside product critical locks","maintenance C1 attempts freeze using prior seal","complete or actually unwind accepted constructor, close/ACK owned resources, request fresh seal/explicit next operation"],"partition":{},"r3_refinement":["nonauthorizing birth before actual resource-use acquisition","old-seal maintenance first attempt BUSY/image0/DDL0","acquire use outside critical locks","revalidate original identity/parent/role/epoch before first effect","actual lifetime close/ACK then fresh seal/new explicit positive image1"],"r3_lifetime":"actual same-DB aggregate shared use through actual children and connection close; no exclusive-per-object; missing parent/name slot overlaps finalized DB S","r3_observer":"actual resource-effect entry or public exposure for lazy ctor; private allocation/RLock is not I/O"}` | `{"literal_oracle":["C1 observes creation reservation/UNSEALED or epoch mismatch","first maintenance attempt MAINTENANCE_BUSY, image=DDL=0","accepted constructor is not erased or forcibly killed","source observer: reservation precedes first resource-effect entry/public exposure","only actual birth completion/unwind + owned handle ACK retires registration","fresh valid post-drain attempt has normal image1 control; no old-attempt promotion"],"r3_observer":"actual resource-effect entry or public exposure for lazy ctor; private allocation/RLock is not I/O"}` | `["CTID.CT-M-07"]` |
| `G09a-X-CT-07B / a / tests/integration/test_maintenance_crash.py::test_constructor_birth_linearization[G09a-X-CT-07B]` | `{"profile":"CORE_L_SINGLE","constructor":"ChunkWriter","order":"B","events":["valid known profile and independent literal schema/role fixture; issued prior seal and bound core owner","valid C1 freeze wins common metadata cut","new direct public constructor called with valid old parent/raw public reference","maintenance continues over previously accepted actors only"],"partition":{},"r3_refinement":["C1 actual admission X held continuously","new valid constructor arguments","birth/public return/first source-effect0","old frozen operation positive retained"],"r3_lifetime":"actual same-DB aggregate shared use through actual children and connection close; no exclusive-per-object; missing parent/name slot overlaps finalized DB S","r3_observer":"actual resource-effect entry or public exposure for lazy ctor; private allocation/RLock is not I/O"}` | `{"literal_oracle":["new birth reservation refused with proposed StateConflict(MAINTENANCE_BUSY)","first resource-effect entry/public instance return=0","new source writes/lock O_CREAT/SQL/executor/native/worker=0 where applicable","private allocation of RLock/empty Python object is not treated as resource I/O","original frozen operation has normal image1 after true old ACK","no existing accepted payload/drain removed"],"r3_observer":"actual resource-effect entry or public exposure for lazy ctor; private allocation/RLock is not I/O"}` | `[]` |
| `G09a-X-CT-08A / a / tests/integration/test_maintenance_crash.py::test_constructor_birth_linearization[G09a-X-CT-08A]` | `{"profile":"CORE_P_SPLIT_AUTH","constructor":"CredentialService","order":"A","events":["valid known profile and independent literal schema/role fixture; issued prior seal and bound core owner","constructor birth reservation wins common metadata cut","pause before first resource effect/public exposure outside product critical locks","maintenance C1 attempts freeze using prior seal","complete or actually unwind accepted constructor, close/ACK owned resources, request fresh seal/explicit next operation"],"partition":{},"r3_refinement":["nonauthorizing birth before actual resource-use acquisition","old-seal maintenance first attempt BUSY/image0/DDL0","acquire use outside critical locks","revalidate original identity/parent/role/epoch before first effect","actual lifetime close/ACK then fresh seal/new explicit positive image1"],"r3_lifetime":"actual same-DB aggregate shared use through actual children and connection close; no exclusive-per-object; missing parent/name slot overlaps finalized DB S","r3_observer":"actual resource-effect entry or public exposure for lazy ctor; private allocation/RLock is not I/O"}` | `{"literal_oracle":["C1 observes creation reservation/UNSEALED or epoch mismatch","first maintenance attempt MAINTENANCE_BUSY, image=DDL=0","accepted constructor is not erased or forcibly killed","source observer: reservation precedes first resource-effect entry/public exposure","only actual birth completion/unwind + owned handle ACK retires registration","fresh valid post-drain attempt has normal image1 control; no old-attempt promotion"],"r3_observer":"actual resource-effect entry or public exposure for lazy ctor; private allocation/RLock is not I/O"}` | `["CTID.CT-M-08"]` |
| `G09a-X-CT-08B / a / tests/integration/test_maintenance_crash.py::test_constructor_birth_linearization[G09a-X-CT-08B]` | `{"profile":"CORE_P_SPLIT_AUTH","constructor":"CredentialService","order":"B","events":["valid known profile and independent literal schema/role fixture; issued prior seal and bound core owner","valid C1 freeze wins common metadata cut","new direct public constructor called with valid old parent/raw public reference","maintenance continues over previously accepted actors only"],"partition":{},"r3_refinement":["C1 actual admission X held continuously","new valid constructor arguments","birth/public return/first source-effect0","old frozen operation positive retained"],"r3_lifetime":"actual same-DB aggregate shared use through actual children and connection close; no exclusive-per-object; missing parent/name slot overlaps finalized DB S","r3_observer":"actual resource-effect entry or public exposure for lazy ctor; private allocation/RLock is not I/O"}` | `{"literal_oracle":["new birth reservation refused with proposed StateConflict(MAINTENANCE_BUSY)","first resource-effect entry/public instance return=0","new source writes/lock O_CREAT/SQL/executor/native/worker=0 where applicable","private allocation of RLock/empty Python object is not treated as resource I/O","original frozen operation has normal image1 after true old ACK","no existing accepted payload/drain removed"],"r3_observer":"actual resource-effect entry or public exposure for lazy ctor; private allocation/RLock is not I/O"}` | `[]` |
| `G09a-X-ID-01 / a / tests/integration/test_migration_backup.py::test_constructor_physical_binding[G09a-X-ID-01]` | `{"profile":null,"constructor":null,"order":null,"events":["submit direct JobStore using case-variant path on Windows fixture","all logical path strings differ as intended but independent handle/stat identity is same"],"partition":{"kind":"supported case-normalized spelling alias","actor":"JobStore","source":"same existing physical DB ID independently observed","gate":"C1 closed","policy_proposed":"support this case alias and deduplicate to same owner/gate","constructor_authorization":"trusted entry requests the same valid role/owner via alias; the physical closed gate, not a forged/missing owner token, is the refusal cause"},"r3_refinement":["independent same actual file ID, valid core owner/role/domain","C1 X -> same DB gate/group despite supported case alias","connect0 and MAINTENANCE_BUSY","without C1 normal same-physical multistore shared join1"]}` | `{"literal_oracle":["owner/role/domain authorization remains valid; alias lookup cannot fall into unclassified compatibility","same physical owner/gate key observed","StateConflict(MAINTENANCE_BUSY)","sqlite/connect/first-effect entry0","original DB/schema/media bytes unchanged"],"r3_observer":null}` | `["CTID.ID-M-01"]` |
| `G09a-X-ID-02 / a / tests/integration/test_migration_backup.py::test_constructor_physical_binding[G09a-X-ID-02]` | `{"profile":null,"constructor":null,"order":null,"events":["independent read-only stat adapter supplies the literal rejected metadata","invoke constructor path validation before DB/lock creation"],"partition":{"kind":"unsupported hardlinked regular-file metadata","actor":"JobStore","lstat_literal":{"regular_file":true,"nlink":2,"reparse":false},"gate":"not the refusal cause"},"r3_refinement":["independent readonly-stat literal preserved","UNSAFE_PATH and first effect0","one common unsafe-identity fault site targets both rows; not two mutants","no actual privileged OS fixture claim"]}` | `{"literal_oracle":["proposed exact SecurityError(UNSAFE_PATH) before first effect","no birth completion/seal/SQL/open-for-write","source unchanged"],"r3_observer":null}` | `["CTID.ID-M-02"]` |
| `G09a-X-ID-03 / a / tests/integration/test_migration_backup.py::test_constructor_physical_binding[G09a-X-ID-03]` | `{"profile":null,"constructor":null,"order":null,"events":["independent read-only stat adapter supplies literal reparse flag","invoke constructor path validation before DB/lock creation"],"partition":{"kind":"unsupported reparse metadata","actor":"JobStore","lstat_literal":{"file_attributes":1024},"gate":"not the refusal cause"},"r3_refinement":["independent readonly-stat literal preserved","UNSAFE_PATH and first effect0","one common unsafe-identity fault site targets both rows; not two mutants","no actual privileged OS fixture claim"]}` | `{"literal_oracle":["proposed exact SecurityError(UNSAFE_PATH) before first effect","no birth completion/seal/SQL/open-for-write","source unchanged"],"r3_observer":null}` | `["CTID.ID-M-02"]` |
| `G09a-X-ID-04 / a / tests/integration/test_migration_backup.py::test_constructor_physical_binding[G09a-X-ID-04]` | `{"profile":null,"constructor":null,"order":null,"events":["first trusted constructor reserves missing-file birth before create","second trusted-factory request invokes the actual public constructor for same pending parent/name; owner/domain authorization is valid so only pending birth conflict refuses","complete first actual creation then verify actual file identity; later explicit valid second store may join same physical group"],"partition":{"kind":"nonexistent DB birth","actor":"two JobStore constructors","physical_key":"known parent identity P17 + normalized name + role","first_birth_nonce":"N1","second_nonce":"N2","constructor_authorization":"both invocations are legitimate trusted-factory birth requests; caller-token/auth failure is not the second refusal cause"},"r3_refinement":["P17/name/role N1 provisional","parent-wide namespace X actually held","legitimate N2 same target BUSY/create0/SQL0","N1 create-new -> actual file identity -> DB shared use","only now provisional slot/name X retired","later N2 new store normal shared join1"]}` | `{"literal_oracle":["one primary pending birth for target role/name","second pending duplicate StateConflict(MAINTENANCE_BUSY), source create/SQL0 for that second call","C1 cannot image while first pending","same original reservation binds real created file ID; no path-only rebind","normal fresh post-completion admission uses actual shared owner identity"],"r3_observer":null}` | `["CTID.ID-M-03"]` |
| `G09a-X-ID-05 / a / tests/integration/test_migration_backup.py::test_constructor_physical_binding[G09a-X-ID-05]` | `{"profile":null,"constructor":null,"order":null,"events":["hold constructor after readonly candidate identity sample/birth metadata but BEFORE actual physical parent pin/use authorization","test-owned actor replaces parent in this explicitly unpinned interval","constructor attempts physical bind/first-effect admission"],"partition":{"kind":"parent identity replacement at pre-pin cut","actor":"JobStore","observed_parent_before":"P17","observed_parent_after":"P18","target_DB":"not yet created","gate":"not independently closed"},"r3_refinement":["readonly sample/birth -> cooperating parent P17 to P18 -> BEFORE actual ancestor-directory use S","acquire actual use then compare original binding","mismatch first effect0; no silent rebind","actor changed source remains preserved","unchanged-parent fresh-plan positive"],"r3_infeasible_trace_not_added":"successful cooperating parent replacement AFTER directory-use S already held"}` | `{"literal_oracle":["StateConflict(MAINTENANCE_BUSY) on changed parent","no mkdir/SQLite/create/lock side effect under replacement parent","birth not silently rebound to P18","original and replacement data kept; only actor-whitelisted rename/creation permitted","fresh explicit plan/identity and normal unchanged-parent control succeed"],"r3_observer":null}` | `["CTID.ID-M-04"]` |
| `G09a-X-FX-PC-01A / a / tests/integration/test_maintenance_crash.py::test_peer_birth_anchor_linearization[G09a-X-FX-PC-01A]` | `{"partition":{"A_required_DB_missing":false,"A_profile":"known complete Library1/core target","A_seal_current":true,"A_producer_set_complete":true,"B_target":"distinct T/B not in A database set","B_birth_port":"trusted controlled Library port","shared_existing_anchor":"T observed independently as same volume/directory-file-id","same_control_namespace":true,"gate_range":0,"B_gate":"DIR_S","B_namespace_X_at_observation":false,"A_gate_attempt":"SAME_DIR_X_TRY_ONLY"},"events_ko":["B에서 T byte0 S를 얻고 namespace X 획득과 첫 mkdir 전 잠금 밖 Event에서 대기","A의 유효한 실제 C1 준비가 같은 T byte0 X를 try-only로 요청하여 목표 충돌 관측; namespace lookup 오류로 먼저 가리지 않음","첫 A 보류 뒤 B가 namespace X·create-new·현재 identity/use 확정까지 보호를 겹쳐 완료","B birth gate 회수 뒤 A가 새 명시 준비로 정상 C1/actual drain/image를 수행"]}` | `{"first_A_C1_commit":0,"first_A_header_write":0,"first_A_retire":0,"first_A_before_image":0,"first_A_DDL":0,"B_forced_stop":0,"B_provisional_released_before_actual_use":0,"fresh_A_positive_before_image":1}` | `["FX.FX-M-PC-01A"]` |
| `G09a-X-FX-PC-01B / a / tests/integration/test_maintenance_crash.py::test_peer_birth_anchor_linearization[G09a-X-FX-PC-01B]` | `{"partition":{"A_required_DB_missing":false,"A_profile":"known complete Library1/core target","A_seal_current":true,"B_target":"distinct T/B","same_existing_anchor_key":"T_DIRECTORY_BYTE0","A_first":"ACTUAL_C1_WITH_DB_AND_DIR_X","A_pause":"HEADER_PENDING_OUTSIDE_LATCH_BEFORE_CONTROL_WRITE","header_contents_before_A_write":"OPEN/g","B_header_read_without_S_allowed":false,"B_second":"DIR_S_BEFORE_FIRST_MKDIR"},"events_ko":["A가 실제 closure의 DB/DIR X를 준비하고 실제 C1을 commit","A는 latch 밖 header 게시 전 Event에서 대기하여 header OPEN/g와 actual X가 공존; A의 실제 stage/기존 관측으로 증명","B의 정상 trusted birth가 같은 T S를 요청; S 없이 header를 읽게 하지 않으며 CLOSED header 거부로 DIR S 목표를 가리지 않음","관측 뒤 A header 게시·원 accepted drain/actual close/유효 image를 정상 완료","A 안전한 소유 반환 뒤 B는 새 nonce의 새 명시 birth를 시도"]}` | `{"B_first_mkdir":0,"B_create_or_SQL":0,"B_public_return":0,"A_positive_before_image":1,"B_old_preparation_revived":0,"B_fresh_later_birth_positive":1}` | `["FX.FX-M-PC-01B"]` |
| `G09a-X-FX-AB-01 / a / tests/integration/test_maintenance_crash.py::test_freeze_preparation_abort[G09a-X-FX-AB-01]` | `{"partition":{"header_before":{"state":"OPEN","generation":7},"inventory_changed":false,"owner_changed":false,"physical_identity_changed":false,"prepared_all_X":true,"cancel_before_local_C1":true},"events_ko":["유효한 A에서 실제 admission X와 현재 header/identity 검증을 준비","local C1 cut 직전 명시 취소","abort된 동일 FreezePreparation의 재사용을 시도","기존 owner가 현재 binding으로 새 kind/nonce effect permit과 정상 effect를 수행","동일하게 current인 seal 사실을 새 preparation에서 재검증"]}` | `{"header_after":{"state":"OPEN","generation":7},"header_write":0,"C1_commit":0,"t0_issued":0,"retire":0,"before_image":0,"old_preparation_reuse":0,"old_effect_permit_next_work":0,"owner_use_accepted_preserved":true,"fresh_effect_positive":1,"new_preparation_current_facts_positive":1}` | `["FX.FX-M-AB-01"]` |
| `G09a-X-FX-AB-02 / a / tests/integration/test_maintenance_crash.py::test_freeze_preparation_abort[G09a-X-FX-AB-02]` | `{"partition":{"header_generation":7,"sealed_registry_epoch":7,"new_registry_epoch":8,"prepared_all_X":true,"birth":"legitimate additional JobStore for same complete fixed core profile","new_birth_source_effect_before_abort":0},"events_ko":["current seal로 실제 X/identity/header 준비","local C1 전 정상 JobStore birth 예약이 같은 registry cut에서 membership을 전진","옛 seal의 local C1 재검사가 거부되어 준비만 해제","원 수락 birth를 실제 완료 또는 안전 unwind","old seal/preparation은 거부하고 현재 inventory의 fresh seal/새 effect/새 명시 시도만 허용"]}` | `{"C1_commit":0,"header_write":0,"header_generation_after":7,"retire":0,"before_image":0,"old_seal_admitted":0,"old_preparation_reuse":0,"old_owner_use_preserved":true,"new_birth_forced_erase":0,"fresh_seal_normal_positive":1}` | `["FX.FX-M-AB-02"]` |
| `G09a-X-FX-HP-01 / a / tests/integration/test_maintenance_crash.py::test_committed_freeze_header_pending[G09a-X-FX-HP-01]` | `{"partition":{"actual_C1_committed":true,"t0_issued_once":true,"header_IO":"raises before verified CLOSED/g+1","observed_header_may_still_be":"OPEN/g","actual_admission_X_retained":true},"events_ko":["실제 local C1/t0/retiring accepted set을 같은 cut에 결속","latch 밖 header 게시 하나가 실패","호출자 보류 뒤에도 broker의 actual X/owner/drain 보유 관측","같은10초 만료와 늦은 actual 종료를 관측"]}` | `{"classified_as_pre_C1_abort":0,"new_effect":0,"before_image":0,"operation_proof_success":0,"header_generation_reset":0,"deadline_restart":0,"owner_or_X_dropped_before_actual_ACK":0,"late_ACK_reclaimed_exact_owner_only":true,"original_call_retroactive_success":0}` | `["FX.FX-M-HP-01"]` |
| `G09a-GS05-FX-CB-01 / a / tests/integration/test_maintenance_crash.py::test_gateway_cleanup_failure_receipts[G09a-GS05-FX-CB-01]` | `{"partition":{"actual_Gateway_and_CredentialService":true,"fake_vault_transport_only":true,"plan_check":null,"valid_issued_lease":true,"before_O_event":"public CredentialService.begin_shutdown with no new native call","primary_code":"AUTH_REQUIRED","primary_outcome_known":true,"actual_transport_open":0,"actual_write":0,"current_same_owner_unsent_proof_complete":true,"reservation_state":"RESERVED","reserved_amount":60,"single_injected_failure":"original lease release callback raises"},"events_ko":["정상 actual native read가 lease/auth copy까지 만든 뒤 O 전 public service shutdown","원 O auth 검사에서 AUTH_REQUIRED/True를 얻음","원 callback에서만 예외를 발생","독립 auth finally·뒤 cleanup들의 실제 입장/종료 receipt를 관측"]}` | `{"public_primary":["AUTH_REQUIRED",true],"own_secret_after_successful_clear":null,"own_headers_after_successful_clear_count":0,"Gateway_auth_copy_count":0,"callback_ACK":0,"full_request_ACK":0,"before_image":0,"release_callback_calls":1,"native_repeat":0,"ticket_discard_attempt":1,"dispatch_cache_cleanup_attempt":1,"end_request_attempt":1,"forced_reserved_settlement":0,"incomplete_owner_retained":true}` | `["FX.FX-M-CB-01"]` |
| `G09a-GS05-FX-CB-02 / a / tests/integration/test_maintenance_crash.py::test_gateway_cleanup_failure_receipts[G09a-GS05-FX-CB-02]` | `{"partition":{"actual_Gateway_and_CredentialService":true,"fake_vault_transport_only":true,"transport_open":1,"write_positive":true,"response_over_limit":true,"primary_code":"RESPONSE_TOO_LARGE","primary_outcome_known":false,"cost_state":"UNKNOWN","exposure":60,"callback":"raises","connection_close":"returns normally"},"events_ko":["정상 유효 handoff와 actual fake write로 UNKNOWN60 유지","과대 응답에서 원 SecurityError 변환 완료","cleanup callback만 예외","header 제거·뒤 ticket/cache/connection close/end_request를 각각 실제 관측"]}` | `{"public_primary":["RESPONSE_TOO_LARGE",false],"Gateway_auth_copy_count":0,"own_slot_clear_completed":true,"callback_ACK":0,"connection_close_enter":1,"connection_close_return_OK":1,"end_request_enter":1,"full_request_ACK":0,"before_image":0,"UNKNOWN_exposure_after":60,"witness_coherent":true,"secondary_receipt_separate":true,"native_callback_repeat":0,"incomplete_owner_retained":true}` | `["FX.FX-M-CB-02","BASE.M18"]` |
| `G09a-GS05-FX-CB-03 / a / tests/integration/test_maintenance_crash.py::test_gateway_cleanup_failure_receipts[G09a-GS05-FX-CB-03]` | `{"partition":{"fake_vault_transport_only":true,"body_success_bytes_utf8":"ok","actual_handoff":true,"cost_state":"UNKNOWN","exposure":60,"callback":"raises","other_cleanup":"returns normally"},"events_ko":["정상 실제 fake open/write/read가 성공 bytes를 준비","원 finally의 callback만 실패","본문 성공과 required cleanup 실패를 adapter에서 분리"]}` | `{"normal_bytes_return":0,"public_error":["SECURITY_STATE_UNAVAILABLE",false],"Gateway_auth_copy_count":0,"callback_ACK":0,"connection_close_return_OK":1,"full_request_ACK":0,"before_image":0,"UNKNOWN_exposure_after":60,"secondary_receipt_sanitized":true,"native_callback_repeat":0,"incomplete_owner_retained":true}` | `["FX.FX-M-CB-03"]` |
| `G09a-GS05-FX-CL-01 / a / tests/integration/test_maintenance_crash.py::test_connection_close_completion_receipts[G09a-GS05-FX-CL-01]` | `{"partition":{"fake_vault_transport_only":true,"primary_code":"RESPONSE_TOO_LARGE","primary_outcome_known":false,"cost_state":"UNKNOWN","exposure":60,"callback":"returns normally","connection_close":"raises before verified close completion"},"events_ko":["actual fake handoff/과대 응답으로 원 primary를 준비","lease callback·auth copy 정리는 정상 완료","실제 close만 실패","end_request/cache0과 실제 미완료 connection/request receipt를 독립 관측"]}` | `{"public_primary":["RESPONSE_TOO_LARGE",false],"lease_ACK":1,"Gateway_auth_copy_count":0,"connection_close_enter":1,"connection_close_return_OK":0,"connection_close_error_receipt":1,"end_request_enter":1,"requests_counter_after":0,"full_request_ACK":0,"before_image":0,"UNKNOWN_exposure_after":60,"actual_connection_owner_retained":true,"auto_retry_close_within_attempt":0}` | `["FX.FX-M-CL-01"]` |
| `G09a-GS05-FX-CL-02 / a / tests/integration/test_maintenance_crash.py::test_connection_close_completion_receipts[G09a-GS05-FX-CL-02]` | `{"partition":{"fake_vault_transport_only":true,"body_success_bytes_utf8":"ok","callback":"returns normally","connection_close":"entered and blocked on actual Event","maintenance_C1":"commits after NETWORK_O_WRITE gates released","fake_acquire_deadline":"t0+10 once"},"events_ko":["성공 body 뒤 actual close call을 Event에서 대기","실제 C1이 기존 accepted request를 retire하고 원 actual 종료를 기다림","같은 획득기한 만료 때 caller 보류와 broker 소유 연속 보유를 관측","Event를 풀어 실제 close/원 request의 늦은 완료를 회수"]}` | `{"close_enter_before_release":1,"close_return_before_release":0,"request_ACK_before_actual_close":0,"before_image_first_attempt":0,"owner_or_X_drop_before_actual_ACK":0,"deadline_restart":0,"late_close_ACK_exactly_once":1,"first_maintenance_call_retroactive_image":0,"normal_old_request_late_return_not_new_handoff":true}` | `["FX.FX-M-CL-02"]` |
| `G09a-X-C6-01 / a / tests/integration/test_maintenance_crash.py::test_core_secret_successor[G09a-X-C6-01]` | `{"profile":"CORE_P_SPLIT_AUTH","event":"SUCCESSFUL_CORE_OPERATION_THEN_C6_FRESH_FACTORY","old_tokens":["TICKET","CREDENTIAL_REF","PLAN","PREFLIGHT","COMPLETION_ACK"],"old_retirement_completed":true,"old_completion_replay_while_new_lease_live":true,"new_current_consent_explicit":true}` | `{"new_service_is_old":false,"old_closing_remains_true":true,"old_token_authority":0,"old_ACK_closes_new_lease":0,"fresh_explicit_binding_positive":true,"automatic_network_grant":0,"UI_bootstrap_certification":0}` | `["BASE.M12","GS05.ACK-M03"]` |
| `G09a-X-CR-01 / a / tests/integration/test_maintenance_crash.py::test_rollback_profile_pointer[G09a-X-CR-01]` | `{"target_case":"KNOWN_LEGACY1_L","before_image":"SAME_ORIGINAL_OPERATION_VERIFIED","old_grant_UNKNOWN_reactivation":false,"API":"IN_PLACE_SQLITE_BACKUP_EXACT_IDENTITY_R_PRE_CURRENT2_REBIND"}` | `{"restored_physical_version":1,"metadata_tables":0,"external_CR_floor_preserved":true,"source_media_logical_dump_preserved":true}` | `["SC.CR-01"]` |
| `G09a-X-CR-02 / a / tests/integration/test_maintenance_crash.py::test_rollback_profile_pointer[G09a-X-CR-02]` | `{"target_case":"KNOWN_LEGACY0_STANDALONE_JOBS","before_image":"SAME_ORIGINAL_OPERATION_VERIFIED","old_grant_UNKNOWN_reactivation":false,"API":"IN_PLACE_SQLITE_BACKUP_EXACT_IDENTITY_R_PRE_CURRENT2_REBIND"}` | `{"restored_physical_version":0,"metadata_tables":0,"external_CR_floor_preserved":true,"job_fence_history_checkpoint_preserved":true,"invented_Library_authority":0}` | `["SC.CR-02"]` |
| `G09a-X-CR-03 / a / tests/integration/test_maintenance_crash.py::test_rollback_profile_pointer[G09a-X-CR-03]` | `{"target_case":"KNOWN_CURRENT2_IMAGE_OLD_O_TO_NEW_R","before_image":"SAME_ORIGINAL_OPERATION_VERIFIED","old_grant_UNKNOWN_reactivation":false,"API":"IN_PLACE_SQLITE_BACKUP_EXACT_IDENTITY_R_PRE_CURRENT2_REBIND"}` | `{"final_pointer":"COMMIT(R,d)","fixed_R_epoch_above_floor":true,"I_source":"actual_R_pre_not_image_old_I","old_pointer_authority":0,"marker_last_DB_rewrite_after_marker":0}` | `["SC.CR-03"]` |
| `G09a-X-CR-04 / a / tests/integration/test_maintenance_crash.py::test_rollback_profile_pointer[G09a-X-CR-04]` | `{"target_case":"P_L_RESTORED_LEGACY1_S_PRE_CURRENT2_PREFIX","before_image":"SAME_ORIGINAL_OPERATION_VERIFIED","old_grant_UNKNOWN_reactivation":false,"API":"IN_PLACE_SQLITE_BACKUP_EXACT_IDENTITY_R_PRE_CURRENT2_REBIND"}` | `{"disposition":"NEEDS_RESUME","same_R_map_epochs_on_resume":true,"L_reapply_restore":0,"remaining_S_only":true}` | `["SC.CR-04"]` |
| `G09a-X-CR-05 / a / tests/integration/test_maintenance_crash.py::test_rollback_profile_pointer[G09a-X-CR-05]` | `{"target_case":"NEW_CR_CURRENT_COHERENT_ADVANCED_WITNESS","before_image":"SAME_ORIGINAL_OPERATION_VERIFIED","old_grant_UNKNOWN_reactivation":false,"advance_cut":"AFTER_OWNED_PROCESS_AND_HANDLES_STOPPED_OFFLINE_COHERENT_CURRENT_PAIR_AT_NEW_CR;NOT_COOPERATIVE_IO_THROUGH_LIVE_X","API":"IN_PLACE_SQLITE_BACKUP_EXACT_IDENTITY_R_PRE_CURRENT2_REBIND"}` | `{"rollback_allowed":false,"recommended_error":"MIGRATION_ROLLBACK_UNSAFE","current_witness_and_exposure_preserved":true,"old_image_or_witness_restore":0,"earlier_generic_digest_refusal_is_target_kill":false}` | `["BASE.M30"]` |
| `G09a-X-FP-01 / a / tests/unit/test_schema_catalog.py::test_component_shape_wire[G09a-X-FP-01]` | `{"wire_case":"NORMAL_CHECKPOINT_SQL_FORMAT_ONLY","component":"jobs.checkpoints"}` | `{"expected_fingerprint":"recoryn-shape-v1:08ad04f16fc95966ba8c2c01a4c563500fab44faec263d2c7efdddd72d7c27d5","normal_profile_accepted":true,"changed_semantics_profile_accepted":null,"product_or_DB_used_to_generate_expected":false,"versioned_hand_wire":"tests/fixtures/g09_schema_v1.json#/lexical_examples/NORMAL_CHECKPOINT_SQL_FORMAT_ONLY"}` | `["SC.FP-01"]` |
| `G09a-X-FP-02 / a / tests/unit/test_schema_catalog.py::test_component_shape_wire[G09a-X-FP-02]` | `{"wire_case":"NEGATIVE_LITERAL_CASE","component":"content.core"}` | `{"expected_fingerprint":"recoryn-shape-v1:47cb2a757b46912db1733875877770b219a06fa8f2f46ffa598ca63909d5469f","normal_profile_accepted":false,"changed_semantics_profile_accepted":false,"product_or_DB_used_to_generate_expected":false,"versioned_hand_wire":"tests/fixtures/g09_schema_v1.json#/lexical_examples/NEGATIVE_LITERAL_CASE"}` | `["SC.FP-02"]` |
| `G09a-X-FP-03 / a / tests/unit/test_schema_catalog.py::test_component_shape_wire[G09a-X-FP-03]` | `{"wire_case":"NEGATIVE_WHERE_NOT_REMOVAL","component":"jobs.core"}` | `{"expected_fingerprint":"recoryn-shape-v1:1a248d75da1c9d537fa74f6fa33f3e9d3793aecf5d5a94b1a1dbfbec02a5ca16","normal_profile_accepted":false,"changed_semantics_profile_accepted":false,"product_or_DB_used_to_generate_expected":false,"versioned_hand_wire":"tests/fixtures/g09_schema_v1.json#/lexical_examples/NEGATIVE_WHERE_NOT_REMOVAL"}` | `["SC.FP-03"]` |
| `G09a-X-FP-04 / a / tests/unit/test_schema_catalog.py::test_component_shape_wire[G09a-X-FP-04]` | `{"wire_case":"NEGATIVE_COLLATION","component":"jobs.checkpoints"}` | `{"expected_fingerprint":"recoryn-shape-v1:eeef915f23b6ccd2e5ccb0f38733493024f80a26a29fc9a22c0e99c7396a4a13","normal_profile_accepted":false,"changed_semantics_profile_accepted":false,"product_or_DB_used_to_generate_expected":false,"versioned_hand_wire":"tests/fixtures/g09_schema_v1.json#/lexical_examples/NEGATIVE_COLLATION"}` | `["SC.FP-04"]` |
| `G09a-X-SP-01 / a / tests/integration/test_maintenance_crash.py::test_metadata_journal_binding[G09a-X-SP-01]` | `{"layout":"L","schema":"CURRENT2_EXACT","journal":"VALID_CURRENT_M_PLAN_MAP","data_identity_role_authority":"ALL_MATCH","only_change":"POINTER_OPERATION_FOREIGN_X_NOT_PRE_O_OR_POST_M"}` | `{"normal_entry":0,"next_mutation":0,"evidence_preserved":true,"exact_public_code":"MAINTENANCE_RESUME_REQUIRED","same_pointer_positive":true,"disposition":"RECONCILIATION_REQUIRED"}` | `["SC.SP-01"]` |
| `G09a-X-G1U-01 / a / tests/unit/test_schema_catalog.py::test_named_legacy_profile_policy[G09a-X-G1U-01]` | `{"source_profile":"L_G1U_ONLY","physical_version":1,"G1U":"UNTYPED8_FIRST3_PK","policy":"X00_SELECTED_B_NAMED_SOURCE_TARGET_MAP"}` | `{"explicit_migration_supported":true,"target_profile":"F2_L_CONS","C0_CREATE_repair":0,"old_grant_transferred":0,"fresh_execution_explicit_consent_required":true,"cost_witness_UNKNOWN_preserved":true}` | `["SC.G1U-EMBED"]` |
| `G09a-X-G1U-02 / a / tests/unit/test_schema_catalog.py::test_named_legacy_profile_policy[G09a-X-G1U-02]` | `{"source_profile":"LJ_G1U_ONLY","physical_version":1,"G1U":"UNTYPED8_FIRST3_PK","policy":"X00_SELECTED_B_NAMED_SOURCE_TARGET_MAP"}` | `{"explicit_migration_supported":true,"target_profile":"F2_LJ_CONS","C0_CREATE_repair":0,"old_grant_transferred":0,"fresh_execution_explicit_consent_required":true,"cost_witness_UNKNOWN_preserved":true}` | `["SC.G1U-EMBED"]` |
| `G09a-X-G1U-03 / a / tests/unit/test_schema_catalog.py::test_named_legacy_profile_policy[G09a-X-G1U-03]` | `{"source_profile":"LC_G1U_ONLY","physical_version":1,"G1U":"UNTYPED8_FIRST3_PK","policy":"X00_SELECTED_B_NAMED_SOURCE_TARGET_MAP"}` | `{"explicit_migration_supported":true,"target_profile":"F2_LC_CONS","C0_CREATE_repair":0,"old_grant_transferred":0,"fresh_execution_explicit_consent_required":true,"cost_witness_UNKNOWN_preserved":true}` | `["SC.G1U-EMBED"]` |
| `G09a-X-G1U-04 / a / tests/unit/test_schema_catalog.py::test_named_legacy_profile_policy[G09a-X-G1U-04]` | `{"source_profile":"LJC_G1U_ONLY","physical_version":1,"G1U":"UNTYPED8_FIRST3_PK","policy":"X00_SELECTED_B_NAMED_SOURCE_TARGET_MAP"}` | `{"explicit_migration_supported":true,"target_profile":"F2_LJC_CONS","C0_CREATE_repair":0,"old_grant_transferred":0,"fresh_execution_explicit_consent_required":true,"cost_witness_UNKNOWN_preserved":true}` | `["SC.G1U-EMBED"]` |
| `G09a-X-G1U-05 / a / tests/unit/test_schema_catalog.py::test_named_legacy_profile_policy[G09a-X-G1U-05]` | `{"source_profile":"STANDALONE_G1U_CONS2","physical_version":0,"G1U":"UNTYPED8_FIRST3_PK","policy":"X00_SELECTED_B_NAMED_SOURCE_TARGET_MAP"}` | `{"explicit_migration_supported":true,"target_profile":"F2_S_CONS","C0_CREATE_repair":0,"old_grant_transferred":0,"fresh_execution_explicit_consent_required":true,"cost_witness_UNKNOWN_preserved":true}` | `["SC.G1U-CONS"]` |
| `G09a-X-G1U-06 / a / tests/unit/test_schema_catalog.py::test_named_legacy_profile_policy[G09a-X-G1U-06]` | `{"source_profile":"STANDALONE_G1U_CONS2_COST2_VALID_WITNESS","physical_version":0,"G1U":"UNTYPED8_FIRST3_PK","policy":"X00_SELECTED_B_NAMED_SOURCE_TARGET_MAP"}` | `{"explicit_migration_supported":true,"target_profile":"F2_S_CONS_COST2","C0_CREATE_repair":0,"old_grant_transferred":0,"fresh_execution_explicit_consent_required":true,"cost_witness_UNKNOWN_preserved":true}` | `["SC.G1U-COST"]` |
| `G09a-X-G1U-07 / a / tests/unit/test_schema_catalog.py::test_named_legacy_profile_policy[G09a-X-G1U-07]` | `{"source_profile":"STANDALONE_G1U_COST2_NO_CONS2","physical_version":0,"G1U":"UNTYPED8_FIRST3_PK","policy":"X00_SELECTED_B_NAMED_SOURCE_TARGET_MAP"}` | `{"explicit_migration_supported":false,"target_profile":null,"C0_CREATE_repair":0,"old_grant_transferred":0,"fresh_execution_explicit_consent_required":true,"cost_witness_UNKNOWN_preserved":true}` | `["SC.G1U-NOCONS"]` |
| `G09a-X-LEASE-01 / a / tests/unit/test_maintenance.py::test_credential_lease_completion_binding[G09a-X-LEASE-01]` | `{"event":"CONCURRENT_DUPLICATE_RELEASE","legitimate_live_lease":true,"callback_blocked_outside_guard":true}` | `{"release_owner_winners":1,"callback_total":1,"extra_duplicate_ACK":0,"ACK_before_callback_return":0,"new_lease_untouched":true}` | `["LS.DUP"]` |
| `G09a-X-LEASE-02 / a / tests/unit/test_maintenance.py::test_credential_lease_completion_binding[G09a-X-LEASE-02]` | `{"event":"CALLBACK_DONE_PUBLISH_FAIL_THEN_RECEIPT_ONLY_RETRY","slots_and_callback_actually_completed":true}` | `{"callback_total":1,"native_repeat":0,"use_until_actual_publish":true,"exact_ACK_total":1,"released_bool_is_authority":false}` | `["LS.PUB"]` |
| `G09a-X-LEASE-03 / a / tests/unit/test_maintenance.py::test_credential_lease_completion_binding[G09a-X-LEASE-03]` | `{"event":"VALID_CONSUMED_CLAIM_THEN_C1_BEFORE_READ_ACCEPT","claim_fresh_unread_same_owner":true,"grant_cost_scope_current":true}` | `{"new_READING_accept":0,"vault_get":0,"new_live_lease":0,"new_O_handoff":0,"preaccepted_native_drain_positive_retained":true}` | `["LS.READ"]` |

### 10.3 Selected SC12 + CA101 + typed FIX1 extra6 (119 rows; S1 FIX1 extra4 below)

| ID / owner / primary | Literal input | Hand oracle | Domain / single fault intention |
| --- | --- | --- | --- |
| `G09a-X-SC-01 / a / tests/unit/test_schema_catalog.py::test_component_shape_wire[G09a-X-SC-01]` | `{"component":"library.core","version":1,"fixture_setup":"HAND_DDL_SMALL_SQLITE_CALLER_CONNECTION_BEFORE_PRODUCT_CALL"}` | `{"exact_hand_fixture_pointer":"tests/fixtures/g09_schema_v1.json#/components/library.core","wire_bytes":1760,"expected_fingerprint":"recoryn-shape-v1:582f0b08f997d875adecfb581a6f2c38de3056815c146f5d588f1e4d61ebda47","connection_open_close_and_write0":true,"authority0":true}` | `{"domain":"SELECTED_SMALL_TEMP_SQLITE_CONNECTION_DOMAIN_NOT_EXECUTED_HERE","fault":"S1.EXACT_COMPONENT_STATIC_SHAPE","single_fault":"Lose one actually declared object/column/NN/PK/default/FK/index/CHECK/trigger/rowid/strict semantic; actual unique sites follow separate S1 sealing, not invented kill labels"}` |
| `G09a-X-SC-02 / a / tests/unit/test_schema_catalog.py::test_component_shape_wire[G09a-X-SC-02]` | `{"component":"storage.projection","version":1,"fixture_setup":"HAND_DDL_SMALL_SQLITE_CALLER_CONNECTION_BEFORE_PRODUCT_CALL"}` | `{"exact_hand_fixture_pointer":"tests/fixtures/g09_schema_v1.json#/components/storage.projection","wire_bytes":3157,"expected_fingerprint":"recoryn-shape-v1:5e2e65aad65986131f63687f8f24a114c392ce16eda9a2e34856e3458bafd9b3","connection_open_close_and_write0":true,"authority0":true}` | `{"domain":"SELECTED_SMALL_TEMP_SQLITE_CONNECTION_DOMAIN_NOT_EXECUTED_HERE","fault":"S1.EXACT_COMPONENT_STATIC_SHAPE","single_fault":"Lose one actually declared object/column/NN/PK/default/FK/index/CHECK/trigger/rowid/strict semantic; actual unique sites follow separate S1 sealing, not invented kill labels"}` |
| `G09a-X-SC-03 / a / tests/unit/test_schema_catalog.py::test_component_shape_wire[G09a-X-SC-03]` | `{"component":"capture.health","version":2,"fixture_setup":"HAND_DDL_SMALL_SQLITE_CALLER_CONNECTION_BEFORE_PRODUCT_CALL"}` | `{"exact_hand_fixture_pointer":"tests/fixtures/g09_schema_v1.json#/components/capture.health","wire_bytes":2648,"expected_fingerprint":"recoryn-shape-v1:5f180b67a914f29c7d55a131978d5807fc7f42ac19d477bc7a960ad1f5073622","connection_open_close_and_write0":true,"authority0":true}` | `{"domain":"SELECTED_SMALL_TEMP_SQLITE_CONNECTION_DOMAIN_NOT_EXECUTED_HERE","fault":"S1.EXACT_COMPONENT_STATIC_SHAPE","single_fault":"Lose one actually declared object/column/NN/PK/default/FK/index/CHECK/trigger/rowid/strict semantic; actual unique sites follow separate S1 sealing, not invented kill labels"}` |
| `G09a-X-SC-04 / a / tests/unit/test_schema_catalog.py::test_component_shape_wire[G09a-X-SC-04]` | `{"component":"jobs.core","version":1,"fixture_setup":"HAND_DDL_SMALL_SQLITE_CALLER_CONNECTION_BEFORE_PRODUCT_CALL"}` | `{"exact_hand_fixture_pointer":"tests/fixtures/g09_schema_v1.json#/components/jobs.core","wire_bytes":3911,"expected_fingerprint":"recoryn-shape-v1:2a9a2a799001d3377a969193eaed1955de89a9adfaf0a851a77af9811352de0a","connection_open_close_and_write0":true,"authority0":true}` | `{"domain":"SELECTED_SMALL_TEMP_SQLITE_CONNECTION_DOMAIN_NOT_EXECUTED_HERE","fault":"S1.EXACT_COMPONENT_STATIC_SHAPE","single_fault":"Lose one actually declared object/column/NN/PK/default/FK/index/CHECK/trigger/rowid/strict semantic; actual unique sites follow separate S1 sealing, not invented kill labels"}` |
| `G09a-X-SC-05 / a / tests/unit/test_schema_catalog.py::test_component_shape_wire[G09a-X-SC-05]` | `{"component":"jobs.receipts","version":1,"fixture_setup":"HAND_DDL_SMALL_SQLITE_CALLER_CONNECTION_BEFORE_PRODUCT_CALL"}` | `{"exact_hand_fixture_pointer":"tests/fixtures/g09_schema_v1.json#/components/jobs.receipts","wire_bytes":430,"expected_fingerprint":"recoryn-shape-v1:07e734ac1586231964d4236f8d90b812d5ddf8cdb038605115c6656828b69153","connection_open_close_and_write0":true,"authority0":true}` | `{"domain":"SELECTED_SMALL_TEMP_SQLITE_CONNECTION_DOMAIN_NOT_EXECUTED_HERE","fault":"S1.EXACT_COMPONENT_STATIC_SHAPE","single_fault":"Lose one actually declared object/column/NN/PK/default/FK/index/CHECK/trigger/rowid/strict semantic; actual unique sites follow separate S1 sealing, not invented kill labels"}` |
| `G09a-X-SC-06 / a / tests/unit/test_schema_catalog.py::test_component_shape_wire[G09a-X-SC-06]` | `{"component":"jobs.checkpoints","version":1,"fixture_setup":"HAND_DDL_SMALL_SQLITE_CALLER_CONNECTION_BEFORE_PRODUCT_CALL"}` | `{"exact_hand_fixture_pointer":"tests/fixtures/g09_schema_v1.json#/components/jobs.checkpoints","wire_bytes":490,"expected_fingerprint":"recoryn-shape-v1:08ad04f16fc95966ba8c2c01a4c563500fab44faec263d2c7efdddd72d7c27d5","connection_open_close_and_write0":true,"authority0":true}` | `{"domain":"SELECTED_SMALL_TEMP_SQLITE_CONNECTION_DOMAIN_NOT_EXECUTED_HERE","fault":"S1.EXACT_COMPONENT_STATIC_SHAPE","single_fault":"Lose one actually declared object/column/NN/PK/default/FK/index/CHECK/trigger/rowid/strict semantic; actual unique sites follow separate S1 sealing, not invented kill labels"}` |
| `G09a-X-SC-07 / a / tests/unit/test_schema_catalog.py::test_component_shape_wire[G09a-X-SC-07]` | `{"component":"content.core","version":1,"fixture_setup":"HAND_DDL_SMALL_SQLITE_CALLER_CONNECTION_BEFORE_PRODUCT_CALL"}` | `{"exact_hand_fixture_pointer":"tests/fixtures/g09_schema_v1.json#/components/content.core","wire_bytes":1957,"expected_fingerprint":"recoryn-shape-v1:03fff360eba1dc0649b608b7211124650705e1cd065993648f933e83470dc731","connection_open_close_and_write0":true,"authority0":true}` | `{"domain":"SELECTED_SMALL_TEMP_SQLITE_CONNECTION_DOMAIN_NOT_EXECUTED_HERE","fault":"S1.EXACT_COMPONENT_STATIC_SHAPE","single_fault":"Lose one actually declared object/column/NN/PK/default/FK/index/CHECK/trigger/rowid/strict semantic; actual unique sites follow separate S1 sealing, not invented kill labels"}` |
| `G09a-X-SC-08 / a / tests/unit/test_schema_catalog.py::test_component_shape_wire[G09a-X-SC-08]` | `{"component":"content.summary_requests","version":1,"fixture_setup":"HAND_DDL_SMALL_SQLITE_CALLER_CONNECTION_BEFORE_PRODUCT_CALL"}` | `{"exact_hand_fixture_pointer":"tests/fixtures/g09_schema_v1.json#/components/content.summary_requests","wire_bytes":512,"expected_fingerprint":"recoryn-shape-v1:4d3e4230d431ce3674ceb0aaf238720d273825fb9fb4202cf3c430eaec65ee6d","connection_open_close_and_write0":true,"authority0":true}` | `{"domain":"SELECTED_SMALL_TEMP_SQLITE_CONNECTION_DOMAIN_NOT_EXECUTED_HERE","fault":"S1.EXACT_COMPONENT_STATIC_SHAPE","single_fault":"Lose one actually declared object/column/NN/PK/default/FK/index/CHECK/trigger/rowid/strict semantic; actual unique sites follow separate S1 sealing, not invented kill labels"}` |
| `G09a-X-SC-09 / a / tests/unit/test_schema_catalog.py::test_component_shape_wire[G09a-X-SC-09]` | `{"component":"security.consent","version":2,"fixture_setup":"HAND_DDL_SMALL_SQLITE_CALLER_CONNECTION_BEFORE_PRODUCT_CALL"}` | `{"exact_hand_fixture_pointer":"tests/fixtures/g09_schema_v1.json#/components/security.consent","wire_bytes":2837,"expected_fingerprint":"recoryn-shape-v1:6a9f50c4185781c91dace5df925d6f4977d6c17499502db0b5531861dc5996e0","connection_open_close_and_write0":true,"authority0":true}` | `{"domain":"SELECTED_SMALL_TEMP_SQLITE_CONNECTION_DOMAIN_NOT_EXECUTED_HERE","fault":"S1.EXACT_COMPONENT_STATIC_SHAPE","single_fault":"Lose one actually declared object/column/NN/PK/default/FK/index/CHECK/trigger/rowid/strict semantic; actual unique sites follow separate S1 sealing, not invented kill labels"}` |
| `G09a-X-SC-10 / a / tests/unit/test_schema_catalog.py::test_component_shape_wire[G09a-X-SC-10]` | `{"component":"security.cost.legacy","version":1,"fixture_setup":"HAND_DDL_SMALL_SQLITE_CALLER_CONNECTION_BEFORE_PRODUCT_CALL"}` | `{"exact_hand_fixture_pointer":"tests/fixtures/g09_schema_v1.json#/components/security.cost.legacy","wire_bytes":1156,"expected_fingerprint":"recoryn-shape-v1:d6b3887b884e0f2a3300c213c665ad44b7c649755328c8b165aa307a8fee874b","connection_open_close_and_write0":true,"authority0":true}` | `{"domain":"SELECTED_SMALL_TEMP_SQLITE_CONNECTION_DOMAIN_NOT_EXECUTED_HERE","fault":"S1.EXACT_COMPONENT_STATIC_SHAPE","single_fault":"Lose one actually declared object/column/NN/PK/default/FK/index/CHECK/trigger/rowid/strict semantic; actual unique sites follow separate S1 sealing, not invented kill labels"}` |
| `G09a-X-SC-11 / a / tests/unit/test_schema_catalog.py::test_component_shape_wire[G09a-X-SC-11]` | `{"component":"security.cost","version":2,"fixture_setup":"HAND_DDL_SMALL_SQLITE_CALLER_CONNECTION_BEFORE_PRODUCT_CALL"}` | `{"exact_hand_fixture_pointer":"tests/fixtures/g09_schema_v1.json#/components/security.cost","wire_bytes":5487,"expected_fingerprint":"recoryn-shape-v1:1cb2ff7b81b6a8545b28204f8308904678677e2dc7341e1755b93ac919be59aa","connection_open_close_and_write0":true,"authority0":true}` | `{"domain":"SELECTED_SMALL_TEMP_SQLITE_CONNECTION_DOMAIN_NOT_EXECUTED_HERE","fault":"S1.EXACT_COMPONENT_STATIC_SHAPE","single_fault":"Lose one actually declared object/column/NN/PK/default/FK/index/CHECK/trigger/rowid/strict semantic; actual unique sites follow separate S1 sealing, not invented kill labels"}` |
| `G09a-X-SC-12 / a / tests/unit/test_schema_catalog.py::test_component_shape_wire[G09a-X-SC-12]` | `{"component":"g09.management","version":1,"fixture_setup":"HAND_DDL_SMALL_SQLITE_CALLER_CONNECTION_BEFORE_PRODUCT_CALL"}` | `{"exact_hand_fixture_pointer":"tests/fixtures/g09_schema_v1.json#/components/g09.management","wire_bytes":1608,"expected_fingerprint":"recoryn-shape-v1:a9e56d69fe77d280595c42a2f18d64bc80b93b0c38c323942208e349cbbb1d1e","connection_open_close_and_write0":true,"authority0":true}` | `{"domain":"SELECTED_SMALL_TEMP_SQLITE_CONNECTION_DOMAIN_NOT_EXECUTED_HERE","fault":"S1.EXACT_COMPONENT_STATIC_SHAPE","single_fault":"Lose one actually declared object/column/NN/PK/default/FK/index/CHECK/trigger/rowid/strict semantic; actual unique sites follow separate S1 sealing, not invented kill labels"}` |
| `G09a-X-CAW-01 / a / tests/unit/test_schema_catalog.py::test_management_wire_types[G09a-X-CAW-01]` | `{"fixture":"HAND_BINDINGS_B1","kind":"BINDINGS"}` | `DECODE_EXACT_FIELDS; ENCODE_EQUALS_HAND_BYTES; CURRENT_AUTHORITY=0` | `{"domain":"SMALL_REAL_FILESYSTEM_WIRE_POSITIVE","fault":"CA.WIRE.CANONICAL_ENCODER","single_fault":"OMIT_REQUIRED_NAMESPACE_IDENTITY_FROM_ENCODER_OUTPUT"}` |
| `G09a-X-CAW-02 / a / tests/unit/test_schema_catalog.py::test_management_wire_types[G09a-X-CAW-02]` | `{"base":"HAND_BINDINGS_B1","raw_insertion_after_open_brace":"\"format\":\"recoryn-management-bindings-v1\",","other_keys":"ALL_ORIGINAL_KEYS_RETAINED_EXACTLY"}` | `DUPLICATE_KEY_REJECTED_WITH_OTHERWISE_COMPLETE_VALID_DOCUMENT; WRITES=0` | `{"domain":"TYPED_READER_UNIT","fault":"CA.WIRE.DUPLICATE_KEY","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CAW-03 / a / tests/unit/test_schema_catalog.py::test_management_wire_types[G09a-X-CAW-03]` | `{"base":"HAND_BINDINGS_B1","add":{"complete":true}}` | `UNKNOWN_KEY_REJECTED; AUTHORITY=0` | `{"domain":"TYPED_READER_UNIT","fault":"CA.WIRE.FIELD_SET","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CAW-04 / a / tests/unit/test_schema_catalog.py::test_management_wire_types[G09a-X-CAW-04]` | `{"base":"HAND_BINDINGS_B1","omit":"generation"}` | `MISSING_KEY_REJECTED; DEFAULT_GENERATION_NOT_CREATED` | `{"domain":"TYPED_READER_UNIT","fault":"CA.WIRE.FIELD_SET","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CAW-05 / a / tests/unit/test_schema_catalog.py::test_management_wire_types[G09a-X-CAW-05]` | `{"base":"HAND_BINDINGS_B1","version":true}` | `EXACT_INT_REJECTS_BOOL` | `{"domain":"TYPED_READER_UNIT","fault":"CA.WIRE.EXACT_INT","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CAW-06 / a / tests/unit/test_schema_catalog.py::test_management_wire_types[G09a-X-CAW-06]` | `{"base":"HAND_BINDINGS_B1","raw_version_token":"1.0"}` | `REAL_TOKEN_REJECTED_NO_COERCION` | `{"domain":"TYPED_READER_UNIT","fault":"CA.WIRE.EXACT_INT","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CAW-07 / a / tests/unit/test_schema_catalog.py::test_management_wire_types[G09a-X-CAW-07]` | `{"base":"HAND_BINDINGS_B1","version":"1"}` | `STRING_REJECTED_NO_INT_CAST` | `{"domain":"TYPED_READER_UNIT","fault":"CA.WIRE.EXACT_INT","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CAW-08 / a / tests/unit/test_schema_catalog.py::test_management_wire_types[G09a-X-CAW-08]` | `{"base":"HAND_BINDINGS_B1","version":null}` | `NULL_REJECTED_NO_DEFAULT` | `{"domain":"TYPED_READER_UNIT","fault":"CA.WIRE.EXACT_INT","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CAW-09 / a / tests/unit/test_schema_catalog.py::test_management_wire_types[G09a-X-CAW-09]` | `{"base":"HAND_BINDINGS_B1","generation":-1}` | `SIGNED64_LOWER_BOUND_REJECTED` | `{"domain":"TYPED_READER_UNIT","fault":"CA.WIRE.INT_RANGE","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CAW-10 / a / tests/unit/test_schema_catalog.py::test_management_wire_types[G09a-X-CAW-10]` | `{"base":"HAND_BINDINGS_B1","generation":9223372036854775808}` | `SIGNED64_UPPER_BOUND_REJECTED_BEFORE_ANY_WRITE` | `{"domain":"TYPED_READER_UNIT","fault":"CA.WIRE.INT_RANGE","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CAW-11 / a / tests/unit/test_schema_catalog.py::test_management_wire_types[G09a-X-CAW-11]` | `{"base":"HAND_BINDINGS_B1","catalog_id":"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"}` | `LOWER_HEX32_REQUIRED_NO_CASEFOLD` | `{"domain":"TYPED_READER_UNIT","fault":"CA.WIRE.ID","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CAW-12 / a / tests/unit/test_schema_catalog.py::test_management_wire_types[G09a-X-CAW-12]` | `{"base":"HAND_PROGRESS_P1","record_digest":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}` | `EXACT_HEX64_REJECTED` | `{"domain":"TYPED_READER_UNIT","fault":"CA.WIRE.DIGEST","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CAW-13 / a / tests/unit/test_schema_catalog.py::test_management_wire_types[G09a-X-CAW-13]` | `{"base":"HAND_BINDINGS_B1","raw_prefix_hex":"efbbbf"}` | `BOM_REJECTED` | `{"domain":"TYPED_READER_UNIT","fault":"CA.WIRE.ENCODING","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CAW-14 / a / tests/unit/test_schema_catalog.py::test_management_wire_types[G09a-X-CAW-14]` | `{"base":"HAND_BINDINGS_B1","raw_suffix_hex":"0a"}` | `TRAILING_LF_REJECTED_NO_AUTO_STRIP` | `{"domain":"TYPED_READER_UNIT","fault":"CA.WIRE.TRAILING_LF","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CAW-15 / a / tests/unit/test_schema_catalog.py::test_management_wire_types[G09a-X-CAW-15]` | `{"raw_hex":"7b22ff223a307d"}` | `UTF8_REJECTED_BEFORE_DTO` | `{"domain":"TYPED_READER_UNIT","fault":"CA.WIRE.ENCODING","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CAW-16 / a / tests/unit/test_schema_catalog.py::test_management_wire_types[G09a-X-CAW-16]` | `{"base":"HAND_BINDINGS_B1","entry_current_name_json_token":"\"\\ud800\""}` | `NON_SCALAR_REJECTED_BEFORE_PATH_USE` | `{"domain":"TYPED_READER_UNIT","fault":"CA.WIRE.SCALAR","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CAW-17 / a / tests/unit/test_schema_catalog.py::test_management_wire_types[G09a-X-CAW-17]` | `{"base":"HAND_BINDINGS_B1","raw_generation_token":"NaN"}` | `NONFINITE_TOKEN_REJECTED` | `{"domain":"TYPED_READER_UNIT","fault":"CA.WIRE.EXACT_INT","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CAW-18 / a / tests/unit/test_schema_catalog.py::test_management_wire_types[G09a-X-CAW-18]` | `{"raw":"[]"}` | `OBJECT_REQUIRED_NOT_EMPTY_CATALOG` | `{"domain":"TYPED_READER_UNIT","fault":"CA.WIRE.ROOT_OBJECT","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CAW-19 / a / tests/unit/test_schema_catalog.py::test_management_wire_types[G09a-X-CAW-19]` | `{"base":"HAND_BINDINGS_B1","anchor_identity_kind":"FILE"}` | `DIR_KIND_REQUIRED_NO_ROLE_CONVERSION` | `{"domain":"TYPED_READER_UNIT","fault":"CA.WIRE.IDENTITY_KIND","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CAW-20 / a / tests/unit/test_schema_catalog.py::test_management_wire_types[G09a-X-CAW-20]` | `{"base":"HAND_BINDINGS_B1","anchor_volume_hex":"000000000000000"}` | `HEX16_VOLUME_REQUIRED` | `{"domain":"TYPED_READER_UNIT","fault":"CA.WIRE.IDENTITY_WIDTH","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CAW-21 / a / tests/unit/test_schema_catalog.py::test_management_wire_types[G09a-X-CAW-21]` | `{"base":"HAND_BINDINGS_B1","anchor_file_id_hex":"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"}` | `LOWER_HEX32_FILE_ID_REQUIRED` | `{"domain":"TYPED_READER_UNIT","fault":"CA.WIRE.IDENTITY_WIDTH","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CAW-22 / a / tests/unit/test_schema_catalog.py::test_management_wire_types[G09a-X-CAW-22]` | `{"base":"HAND_BINDINGS_B1","entry_current_name":"../other.db"}` | `BASENAME_REJECTED; ARTIFACT_OPEN=0` | `{"domain":"TYPED_READER_UNIT","fault":"CA.WIRE.SAFE_NAME","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CAW-23 / a / tests/unit/test_schema_catalog.py::test_management_wire_types[G09a-X-CAW-23]` | `{"base":"HAND_BINDINGS_B1","entry_roles":["jobs","jobs"]}` | `DUPLICATE_ROLE_REJECTED_NO_SET_DEDUP` | `{"domain":"TYPED_READER_UNIT","fault":"CA.WIRE.LIST_UNIQUENESS","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CAW-24 / a / tests/unit/test_schema_catalog.py::test_management_wire_types[G09a-X-CAW-24]` | `{"base":"HAND_BINDINGS_B1","entries":"SAME_ENTRY_TWICE"}` | `DUPLICATE_DB_ID_REJECTED_NO_LAST_WINS` | `{"domain":"TYPED_READER_UNIT","fault":"CA.WIRE.LIST_UNIQUENESS","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CAN-01 / a / tests/unit/test_schema_catalog.py::test_management_tagged_null[G09a-X-CAN-01]` | `{"pointer":{"kind":"ABSENT"},"cut":"PRE"}` | `ABSENT_ACCEPTED; EPOCH_NOT_INVENTED; AUTHORITY=0` | `{"domain":"TYPED_READER_UNIT","fault":"CA.NULL.POINTER","single_fault":"COERCE_ABSENT_TO_FRESH_EPOCH0"}` |
| `G09a-X-CAN-02 / a / tests/unit/test_schema_catalog.py::test_management_tagged_null[G09a-X-CAN-02]` | `{"cut":"PRE","pointer":null,"source_digest":"dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"}` | `PRE_NULL_REJECTED_NOT_ABSENT` | `{"domain":"TYPED_READER_UNIT","fault":"CA.NULL.POINTER","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CAN-03 / a / tests/unit/test_schema_catalog.py::test_management_tagged_null[G09a-X-CAN-03]` | `{"cut":"POST","pointer":"VALID_COMMIT_M","source_digest":null}` | `POST_NULL_DIGEST_REJECTED` | `{"domain":"TYPED_READER_UNIT","fault":"CA.NULL.POINTER","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CAN-04 / a / tests/unit/test_schema_catalog.py::test_management_tagged_null[G09a-X-CAN-04]` | `{"cut":"UNRESOLVED","pointer":null,"source_digest":null,"disposition":"RECONCILIATION_REQUIRED"}` | `DIAGNOSTIC_RECORD_ACCEPTED; MUTATION_NORMAL_ENTRY=0` | `{"domain":"TYPED_READER_UNIT","fault":"CA.NULL.UNRESOLVED","single_fault":"TREAT_UNRESOLVED_AS_KNOWN_PRE_FOR_NORMAL_ENTRY"}` |
| `G09a-X-CAN-05 / a / tests/unit/test_schema_catalog.py::test_management_tagged_null[G09a-X-CAN-05]` | `{"pointer":{"kind":"FRESH","dataset_id":"11111111111111111111111111111111","epoch":0}}` | `FRESH_ZERO_ACCEPTED_NO_OPERATION_ID` | `{"domain":"TYPED_READER_UNIT","fault":"CA.NULL.FRESH","single_fault":"COERCE_FRESH_EPOCH0_TO_COMMIT_OR_EPOCH1"}` |
| `G09a-X-CAN-06 / a / tests/unit/test_schema_catalog.py::test_management_tagged_null[G09a-X-CAN-06]` | `{"pointer":{"kind":"FRESH","dataset_id":"11111111111111111111111111111111","epoch":1}}` | `FRESH_NONZERO_REJECTED` | `{"domain":"TYPED_READER_UNIT","fault":"CA.NULL.FRESH","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CAN-07 / a / tests/unit/test_schema_catalog.py::test_management_tagged_null[G09a-X-CAN-07]` | `{"pointer":"OTHERWISE_VALID_COMMIT","epoch":0}` | `COMMIT_EPOCH_ZERO_REJECTED` | `{"domain":"TYPED_READER_UNIT","fault":"CA.NULL.COMMIT","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CAN-08 / a / tests/unit/test_schema_catalog.py::test_management_tagged_null[G09a-X-CAN-08]` | `{"cut":"POST","target_epoch":7,"credited_epoch":6}` | `POST_CREDIT_MUST_EQUAL_PLANNED_E_NOT_ANY_POSITIVE` | `{"domain":"TYPED_READER_UNIT","fault":"CA.NULL.CREDIT","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CAN-09 / a / tests/unit/test_schema_catalog.py::test_management_tagged_null[G09a-X-CAN-09]` | `{"cut":"PRE","credited_epoch":7}` | `PRE_CREDIT_REJECTED` | `{"domain":"TYPED_READER_UNIT","fault":"CA.NULL.CREDIT","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CAN-10 / a / tests/unit/test_schema_catalog.py::test_management_tagged_null[G09a-X-CAN-10]` | `{"phase":"VERIFYING","output_digest":"dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"}` | `PRE_VERIFIED_OUTPUT_MUST_BE_NULL` | `{"domain":"TYPED_READER_UNIT","fault":"CA.NULL.OUTPUT","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CAN-11 / a / tests/unit/test_schema_catalog.py::test_management_tagged_null[G09a-X-CAN-11]` | `{"phase":"VERIFIED","output_digest":null}` | `VERIFIED_REQUIRES_ACTUAL_OUTPUT_DIGEST` | `{"domain":"TYPED_READER_UNIT","fault":"CA.NULL.OUTPUT","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CAN-12 / a / tests/unit/test_schema_catalog.py::test_management_tagged_null[G09a-X-CAN-12]` | `{"sequence":0,"prior_digest":"dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"}` | `FIRST_RECORD_PRIOR_MUST_BE_NULL` | `{"domain":"TYPED_READER_UNIT","fault":"CA.NULL.CHAIN","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CAN-13 / a / tests/unit/test_schema_catalog.py::test_management_tagged_null[G09a-X-CAN-13]` | `{"sequence":1,"prior_digest":null}` | `NEXT_RECORD_REQUIRES_EXACT_PREDECESSOR_DIGEST` | `{"domain":"TYPED_READER_UNIT","fault":"CA.NULL.CHAIN","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CAN-14 / a / tests/unit/test_schema_catalog.py::test_management_tagged_null[G09a-X-CAN-14]` | `{"kind":"APPLY","restore_effect":"BACKUP_RETURNED"}` | `APPLY_EFFECT_MUST_BE_NULL` | `{"domain":"TYPED_READER_UNIT","fault":"CA.NULL.RESTORE_EFFECT","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CAN-15 / a / tests/unit/test_schema_catalog.py::test_management_tagged_null[G09a-X-CAN-15]` | `{"kind":"ROLLBACK","restore_effect":null}` | `ROLLBACK_REQUIRES_CLOSED_EFFECT_VALUE` | `{"domain":"TYPED_READER_UNIT","fault":"CA.NULL.RESTORE_EFFECT","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CAN-16 / a / tests/unit/test_schema_catalog.py::test_management_tagged_null[G09a-X-CAN-16]` | `{"phase":"PREPARING","binding_links":null}` | `PREPARATION_FACT_ACCEPTED; IMAGE=SOURCE_MUTATION=0` | `{"domain":"TYPED_READER_UNIT","fault":"CA.NULL.LINKS","single_fault":"ALLOW_IMAGE_WITH_NULL_BINDING_LINKS"}` |
| `G09a-X-CAN-17 / a / tests/unit/test_schema_catalog.py::test_management_tagged_null[G09a-X-CAN-17]` | `{"phase":"IMAGE_VERIFIED","one_pre_image":null}` | `ALL_TARGET_VERIFIED_IMAGE_REFS_REQUIRED` | `{"domain":"TYPED_READER_UNIT","fault":"CA.NULL.IMAGE","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CAN-18 / a / tests/unit/test_schema_catalog.py::test_management_tagged_null[G09a-X-CAN-18]` | `{"state":"BOUND","genesis":"FRESH_INIT","current_identity":null}` | `NULL_ONLY_PREPARED_UNCREATED_FRESH; PUBLIC_RETURN=0` | `{"domain":"TYPED_READER_UNIT","fault":"CA.NULL.BINDING","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CAB-01 / a / tests/unit/test_schema_catalog.py::test_management_discovery_budget[G09a-X-CAB-01]` | `{"axis":"RAW_OBJECT_BYTES","observed":8388607,"limit":8388608,"at_or_below_is_budget_pass_only":true}` | `BUDGET_PASS_ONLY; FULL_TYPED_CURRENT_NOT_ASSERTED` | `{"domain":"BOUNDED_READER_ITERATOR_UNIT","fault":"CA.BUDGET.RAW_OBJECT_BYTES","single_fault":"INVERT_THIS_SINGLE_EXCESS_COMPARISON; ASSERT_BUDGET_PASS_OR_STOP_AT_THIS_DECLARED_UNIT_BOUNDARY"}` |
| `G09a-X-CAB-02 / a / tests/unit/test_schema_catalog.py::test_management_discovery_budget[G09a-X-CAB-02]` | `{"axis":"RAW_OBJECT_BYTES","observed":8388608,"limit":8388608,"at_or_below_is_budget_pass_only":true}` | `BUDGET_PASS_ONLY; FULL_TYPED_CURRENT_NOT_ASSERTED` | `{"domain":"BOUNDED_READER_ITERATOR_UNIT","fault":"CA.BUDGET.RAW_OBJECT_BYTES","single_fault":"INVERT_THIS_SINGLE_EXCESS_COMPARISON; ASSERT_BUDGET_PASS_OR_STOP_AT_THIS_DECLARED_UNIT_BOUNDARY"}` |
| `G09a-X-CAB-03 / a / tests/unit/test_schema_catalog.py::test_management_discovery_budget[G09a-X-CAB-03]` | `{"axis":"RAW_OBJECT_BYTES","observed":8388609,"limit":8388608,"at_or_below_is_budget_pass_only":true}` | `BUDGET_STOP; NO_NEXT_OPEN_OR_PARSE; WRITES=0` | `{"domain":"BOUNDED_READER_ITERATOR_UNIT","fault":"CA.BUDGET.RAW_OBJECT_BYTES","single_fault":"INVERT_THIS_SINGLE_EXCESS_COMPARISON; ASSERT_BUDGET_PASS_OR_STOP_AT_THIS_DECLARED_UNIT_BOUNDARY"}` |
| `G09a-X-CAB-04 / a / tests/unit/test_schema_catalog.py::test_management_discovery_budget[G09a-X-CAB-04]` | `{"axis":"CANONICAL_OBJECT_BYTES","observed":8388607,"limit":8388608,"at_or_below_is_budget_pass_only":true}` | `BUDGET_PASS_ONLY; FULL_TYPED_CURRENT_NOT_ASSERTED` | `{"domain":"BOUNDED_READER_ITERATOR_UNIT","fault":"CA.BUDGET.CANONICAL_OBJECT_BYTES","single_fault":"INVERT_THIS_SINGLE_EXCESS_COMPARISON; ASSERT_BUDGET_PASS_OR_STOP_AT_THIS_DECLARED_UNIT_BOUNDARY"}` |
| `G09a-X-CAB-05 / a / tests/unit/test_schema_catalog.py::test_management_discovery_budget[G09a-X-CAB-05]` | `{"axis":"CANONICAL_OBJECT_BYTES","observed":8388608,"limit":8388608,"at_or_below_is_budget_pass_only":true}` | `BUDGET_PASS_ONLY; FULL_TYPED_CURRENT_NOT_ASSERTED` | `{"domain":"BOUNDED_READER_ITERATOR_UNIT","fault":"CA.BUDGET.CANONICAL_OBJECT_BYTES","single_fault":"INVERT_THIS_SINGLE_EXCESS_COMPARISON; ASSERT_BUDGET_PASS_OR_STOP_AT_THIS_DECLARED_UNIT_BOUNDARY"}` |
| `G09a-X-CAB-06 / a / tests/unit/test_schema_catalog.py::test_management_discovery_budget[G09a-X-CAB-06]` | `{"axis":"CANONICAL_OBJECT_BYTES","observed":8388609,"limit":8388608,"at_or_below_is_budget_pass_only":true}` | `BUDGET_STOP; NO_NEXT_OPEN_OR_PARSE; WRITES=0` | `{"domain":"BOUNDED_READER_ITERATOR_UNIT","fault":"CA.BUDGET.CANONICAL_OBJECT_BYTES","single_fault":"INVERT_THIS_SINGLE_EXCESS_COMPARISON; ASSERT_BUDGET_PASS_OR_STOP_AT_THIS_DECLARED_UNIT_BOUNDARY"}` |
| `G09a-X-CAB-07 / a / tests/unit/test_schema_catalog.py::test_management_discovery_budget[G09a-X-CAB-07]` | `{"axis":"DEPTH","observed":16,"limit":16,"at_or_below_is_budget_pass_only":true}` | `BUDGET_PASS_ONLY; FULL_TYPED_CURRENT_NOT_ASSERTED` | `{"domain":"BOUNDED_READER_ITERATOR_UNIT","fault":"CA.BUDGET.DEPTH","single_fault":"INVERT_THIS_SINGLE_EXCESS_COMPARISON; ASSERT_BUDGET_PASS_OR_STOP_AT_THIS_DECLARED_UNIT_BOUNDARY"}` |
| `G09a-X-CAB-08 / a / tests/unit/test_schema_catalog.py::test_management_discovery_budget[G09a-X-CAB-08]` | `{"axis":"DEPTH","observed":17,"limit":16,"at_or_below_is_budget_pass_only":true}` | `BUDGET_STOP; NO_NEXT_OPEN_OR_PARSE; WRITES=0` | `{"domain":"BOUNDED_READER_ITERATOR_UNIT","fault":"CA.BUDGET.DEPTH","single_fault":"INVERT_THIS_SINGLE_EXCESS_COMPARISON; ASSERT_BUDGET_PASS_OR_STOP_AT_THIS_DECLARED_UNIT_BOUNDARY"}` |
| `G09a-X-CAB-09 / a / tests/unit/test_schema_catalog.py::test_management_discovery_budget[G09a-X-CAB-09]` | `{"axis":"DISCOVERY_RAW_BYTES","observed":268435455,"limit":268435456,"at_or_below_is_budget_pass_only":true}` | `BUDGET_PASS_ONLY; FULL_TYPED_CURRENT_NOT_ASSERTED` | `{"domain":"BOUNDED_READER_ITERATOR_UNIT","fault":"CA.BUDGET.DISCOVERY_RAW_BYTES","single_fault":"INVERT_THIS_SINGLE_EXCESS_COMPARISON; ASSERT_BUDGET_PASS_OR_STOP_AT_THIS_DECLARED_UNIT_BOUNDARY"}` |
| `G09a-X-CAB-10 / a / tests/unit/test_schema_catalog.py::test_management_discovery_budget[G09a-X-CAB-10]` | `{"axis":"DISCOVERY_RAW_BYTES","observed":268435456,"limit":268435456,"at_or_below_is_budget_pass_only":true}` | `BUDGET_PASS_ONLY; FULL_TYPED_CURRENT_NOT_ASSERTED` | `{"domain":"BOUNDED_READER_ITERATOR_UNIT","fault":"CA.BUDGET.DISCOVERY_RAW_BYTES","single_fault":"INVERT_THIS_SINGLE_EXCESS_COMPARISON; ASSERT_BUDGET_PASS_OR_STOP_AT_THIS_DECLARED_UNIT_BOUNDARY"}` |
| `G09a-X-CAB-11 / a / tests/unit/test_schema_catalog.py::test_management_discovery_budget[G09a-X-CAB-11]` | `{"axis":"DISCOVERY_RAW_BYTES","observed":268435457,"limit":268435456,"at_or_below_is_budget_pass_only":true}` | `BUDGET_STOP; NO_NEXT_OPEN_OR_PARSE; WRITES=0` | `{"domain":"BOUNDED_READER_ITERATOR_UNIT","fault":"CA.BUDGET.DISCOVERY_RAW_BYTES","single_fault":"INVERT_THIS_SINGLE_EXCESS_COMPARISON; ASSERT_BUDGET_PASS_OR_STOP_AT_THIS_DECLARED_UNIT_BOUNDARY"}` |
| `G09a-X-CAB-12 / a / tests/unit/test_schema_catalog.py::test_management_discovery_budget[G09a-X-CAB-12]` | `{"axis":"OPERATION_ENTRIES","observed":99999,"limit":100000,"at_or_below_is_budget_pass_only":true}` | `BUDGET_PASS_ONLY; FULL_TYPED_CURRENT_NOT_ASSERTED` | `{"domain":"BOUNDED_READER_ITERATOR_UNIT","fault":"CA.BUDGET.OPERATION_ENTRIES","single_fault":"INVERT_THIS_SINGLE_EXCESS_COMPARISON; ASSERT_BUDGET_PASS_OR_STOP_AT_THIS_DECLARED_UNIT_BOUNDARY"}` |
| `G09a-X-CAB-13 / a / tests/unit/test_schema_catalog.py::test_management_discovery_budget[G09a-X-CAB-13]` | `{"axis":"OPERATION_ENTRIES","observed":100000,"limit":100000,"at_or_below_is_budget_pass_only":true}` | `BUDGET_PASS_ONLY; FULL_TYPED_CURRENT_NOT_ASSERTED` | `{"domain":"BOUNDED_READER_ITERATOR_UNIT","fault":"CA.BUDGET.OPERATION_ENTRIES","single_fault":"INVERT_THIS_SINGLE_EXCESS_COMPARISON; ASSERT_BUDGET_PASS_OR_STOP_AT_THIS_DECLARED_UNIT_BOUNDARY"}` |
| `G09a-X-CAB-14 / a / tests/unit/test_schema_catalog.py::test_management_discovery_budget[G09a-X-CAB-14]` | `{"axis":"OPERATION_ENTRIES","observed":100001,"limit":100000,"at_or_below_is_budget_pass_only":true}` | `BUDGET_STOP; NO_NEXT_OPEN_OR_PARSE; WRITES=0` | `{"domain":"BOUNDED_READER_ITERATOR_UNIT","fault":"CA.BUDGET.OPERATION_ENTRIES","single_fault":"INVERT_THIS_SINGLE_EXCESS_COMPARISON; ASSERT_BUDGET_PASS_OR_STOP_AT_THIS_DECLARED_UNIT_BOUNDARY"}` |
| `G09a-X-CAB-15 / a / tests/unit/test_schema_catalog.py::test_management_discovery_budget[G09a-X-CAB-15]` | `{"axis":"RECORD_ENTRIES_ALL_DIRS","observed":999999,"limit":1000000,"at_or_below_is_budget_pass_only":true}` | `BUDGET_PASS_ONLY; FULL_TYPED_CURRENT_NOT_ASSERTED` | `{"domain":"BOUNDED_READER_ITERATOR_UNIT","fault":"CA.BUDGET.RECORD_ENTRIES_ALL_DIRS","single_fault":"INVERT_THIS_SINGLE_EXCESS_COMPARISON; ASSERT_BUDGET_PASS_OR_STOP_AT_THIS_DECLARED_UNIT_BOUNDARY"}` |
| `G09a-X-CAB-16 / a / tests/unit/test_schema_catalog.py::test_management_discovery_budget[G09a-X-CAB-16]` | `{"axis":"RECORD_ENTRIES_ALL_DIRS","observed":1000000,"limit":1000000,"at_or_below_is_budget_pass_only":true}` | `BUDGET_PASS_ONLY; FULL_TYPED_CURRENT_NOT_ASSERTED` | `{"domain":"BOUNDED_READER_ITERATOR_UNIT","fault":"CA.BUDGET.RECORD_ENTRIES_ALL_DIRS","single_fault":"INVERT_THIS_SINGLE_EXCESS_COMPARISON; ASSERT_BUDGET_PASS_OR_STOP_AT_THIS_DECLARED_UNIT_BOUNDARY"}` |
| `G09a-X-CAB-17 / a / tests/unit/test_schema_catalog.py::test_management_discovery_budget[G09a-X-CAB-17]` | `{"axis":"RECORD_ENTRIES_ALL_DIRS","observed":1000001,"limit":1000000,"at_or_below_is_budget_pass_only":true}` | `BUDGET_STOP; NO_NEXT_OPEN_OR_PARSE; WRITES=0` | `{"domain":"BOUNDED_READER_ITERATOR_UNIT","fault":"CA.BUDGET.RECORD_ENTRIES_ALL_DIRS","single_fault":"INVERT_THIS_SINGLE_EXCESS_COMPARISON; ASSERT_BUDGET_PASS_OR_STOP_AT_THIS_DECLARED_UNIT_BOUNDARY"}` |
| `G09a-X-CAB-18 / a / tests/unit/test_schema_catalog.py::test_management_discovery_budget[G09a-X-CAB-18]` | `{"first_bytes":268435450,"same_item_reread_bytes":7}` | `TOTAL=268435457; STOP_NOT_RESET` | `{"domain":"BOUNDED_READER_ITERATOR_UNIT","fault":"CA.BUDGET.ATTEMPT_SCOPE","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CAB-19 / a / tests/unit/test_schema_catalog.py::test_management_discovery_budget[G09a-X-CAB-19]` | `{"first_bytes":268435450,"same_identity_alias_reread_bytes":7}` | `TOTAL=268435457; IDENTITY_ALIAS_NOT_FREE` | `{"domain":"BOUNDED_READER_ITERATOR_UNIT","fault":"CA.BUDGET.ATTEMPT_SCOPE","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CAB-20 / a / tests/unit/test_schema_catalog.py::test_management_discovery_budget[G09a-X-CAB-20]` | `{"primary_bytes":134217728,"secondary_bytes":134217729}` | `TOTAL=268435457; SECOND_ANCHOR_NOT_NEW_BUDGET` | `{"domain":"BOUNDED_READER_ITERATOR_UNIT","fault":"CA.BUDGET.ATTEMPT_SCOPE","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CAB-21 / a / tests/unit/test_schema_catalog.py::test_management_discovery_budget[G09a-X-CAB-21]` | `{"records_per_dir":[500000,500001]}` | `TOTAL=1000001; FIRST_EXCESS_THEN_NEXT_OPEN0` | `{"domain":"BOUNDED_READER_ITERATOR_UNIT","fault":"CA.BUDGET.ENTRY_SCOPE","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CAB-22 / a / tests/unit/test_schema_catalog.py::test_management_discovery_budget[G09a-X-CAB-22]` | `{"stream":"4194304 U+00E9 UTF8 PAIRS THEN ASCII x","raw_bytes":8388609,"decoded_scalars":4194305}` | `RAW_LIMIT_REJECTS_DESPITE_SCALAR_COUNT_BELOW_LIMIT` | `{"domain":"BOUNDED_READER_ITERATOR_UNIT","fault":"CA.BUDGET.RAW_OBJECT_BYTES","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CAB-23 / a / tests/unit/test_schema_catalog.py::test_management_discovery_budget[G09a-X-CAB-23]` | `{"reader_event":"OSError_AFTER_VALID_PREFIX"}` | `INDETERMINATE; SCHEMA_INSPECTION_UNAVAILABLE; WRITES=0` | `{"domain":"BOUNDED_READER_ITERATOR_UNIT","fault":"CA.BUDGET.READ_UNKNOWN","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CAB-24 / a / tests/unit/test_schema_catalog.py::test_management_discovery_budget[G09a-X-CAB-24]` | `{"reader_event":"SAME_NAME_IDENTITY_CHANGED_BETWEEN_READS"}` | `INDETERMINATE; NO_STITCHED_CURRENT; WRITES=0` | `{"domain":"BOUNDED_READER_ITERATOR_UNIT","fault":"CA.BUDGET.READ_UNKNOWN","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CAB-25 / a / tests/unit/test_schema_catalog.py::test_management_discovery_budget[G09a-X-CAB-25]` | `{"stage":"C0","attempt_deadline":null,"all_limits":"SMALL_VALID"}` | `READ_DIAGNOSTIC_ONLY; NO_C1_START_TIME_OR_SOURCE_WRITE` | `{"domain":"BOUNDED_READER_ITERATOR_UNIT","fault":"CA.BUDGET.DEADLINE","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CAB-26 / a / tests/unit/test_schema_catalog.py::test_management_discovery_budget[G09a-X-CAB-26]` | `{"stage":"POST_C1_CONTROL","t0":0,"now":10,"operation_deadline":3600}` | `NO_NEW_DISCOVERY_EFFECT; SAME_T0; HELD_OWNER_NOT_ACKED` | `{"domain":"BOUNDED_READER_ITERATOR_UNIT","fault":"CA.BUDGET.DEADLINE","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CAB-27 / a / tests/unit/test_schema_catalog.py::test_management_discovery_budget[G09a-X-CAB-27]` | `{"stage":"C2_CONTROL","operation_t0":0,"now":3600}` | `NO_NEW_CONTROL_EFFECT; DEADLINE_NOT_REISSUED; EVIDENCE_HELD` | `{"domain":"BOUNDED_READER_ITERATOR_UNIT","fault":"CA.BUDGET.DEADLINE","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CAE-01 / a / tests/unit/test_maintenance.py::test_maintenance_epoch_floor[G09a-X-CAE-01]` | `{"new_operation":true,"known_floor":9223372036854775806}` | `TARGET_E=9223372036854775807; NO_WRAP` | `{"domain":"MAINTENANCE_PREPARATION_UNIT","fault":"CA.EPOCH.OVERFLOW","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CAE-02 / a / tests/unit/test_maintenance.py::test_maintenance_epoch_floor[G09a-X-CAE-02]` | `{"new_operation":true,"known_floor":9223372036854775807}` | `REFUSE_BEFORE_PUBLICATION_SQL_FIRST_MUTATION; RESET=0; MAINTENANCE_BUSY_PHASE_NULL_DISPOSITION_NULL; AUTO_RETRY0` | `{"domain":"MAINTENANCE_PREPARATION_UNIT","fault":"CA.EPOCH.OVERFLOW","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CAE-03 / a / tests/unit/test_maintenance.py::test_maintenance_epoch_floor[G09a-X-CAE-03]` | `{"new_operation":true,"known_floor":"UNKNOWN"}` | `REFUSE; NO_UNCOMMITTED_OR_ZERO_SUBSTITUTION; MANAGED_TRACE_RESUME_REQUIRED_QUARANTINED` | `{"domain":"MAINTENANCE_PREPARATION_UNIT","fault":"CA.EPOCH.UNKNOWN","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CAE-04 / a / tests/unit/test_maintenance.py::test_maintenance_epoch_floor[G09a-X-CAE-04]` | `{"kind":"APPLY","same_operation":"M","planned_E":9223372036854775807,"already_committed":true}` | `SAME_M_E; DUPLICATE_COMMIT=0; FLOOR_PLUS_ONE_NOT_CALLED` | `{"domain":"MAINTENANCE_PREPARATION_UNIT","fault":"CA.EPOCH.RESUME","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CAE-05 / a / tests/unit/test_maintenance.py::test_maintenance_epoch_floor[G09a-X-CAE-05]` | `{"kind":"ROLLBACK","same_operation":"R","planned_E":9223372036854775807,"legacy_target_metadata":"ABSENT","verified_post":true}` | `SAME_R_E; LEGACY_METADATA_CREATE=0; REBACKUP=0` | `{"domain":"MAINTENANCE_PREPARATION_UNIT","fault":"CA.EPOCH.RESUME","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CABT-01 / a / tests/integration/test_maintenance_crash.py::test_management_first_enrollment[G09a-X-CABT-01]` | `{"source":"KNOWN_LEGACY1","namespace":"EMPTY_DIR_FROM_INTERRUPTED_FIRST_MKDIR"}` | `UNKNOWN_QUARANTINED; AUTO_ENROLL=IMAGE=SOURCE_WRITES=0` | `{"domain":"SMALL_FILESYSTEM_INTEGRATION_PLAN","fault":"CA.BOOT.EMPTY_NAMESPACE","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CABT-02 / a / tests/integration/test_maintenance_crash.py::test_management_first_enrollment[G09a-X-CABT-02]` | `{"catalog":"PREPARED_FRESH_INIT_NULL_ID_UNCOMMITTED","source":"ABSENT"}` | `NO_AUTO_CREATE_OR_PUBLIC_RETURN; EXPLICIT_INTAKE_REQUIRED` | `{"domain":"SMALL_FILESYSTEM_INTEGRATION_PLAN","fault":"CA.BOOT.UNBOUND","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CABT-03 / a / tests/integration/test_maintenance_crash.py::test_management_first_enrollment[G09a-X-CABT-03]` | `{"source":"EXACT_CURRENT2_FRESH_E0","catalog":"PREPARED_NULL_ID_UNCOMMITTED"}` | `NORMAL_RETURN=0; PRESERVE_SOURCE; NO_ADOPT_BY_DATASET_STRING` | `{"domain":"SMALL_FILESYSTEM_INTEGRATION_PLAN","fault":"CA.BOOT.UNBOUND","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CABT-04 / a / tests/integration/test_maintenance_crash.py::test_management_first_enrollment[G09a-X-CABT-04]` | `{"order":["ACTUAL_BIRTH_USE","PREPARED_FRESH_INIT_BEFORE_SOURCE","EXACT_PROFILE_METADATA0_TXN","ACTUAL_FILE_ID","BOUND_KNOWN0_PUBLISH_VERIFY","PUBLIC_RETURN"],"profile":"F2_J"}` | `PUBLIC_RETURN1_ONLY_AFTER_ACTUAL_BOUND_VERIFY; ACK_OR_NETWORK_AUTHORITY=0` | `{"domain":"SMALL_FILESYSTEM_INTEGRATION_PLAN","fault":"CA.BOOT.PUBLIC_RETURN","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CABT-05 / a / tests/integration/test_maintenance_crash.py::test_management_first_enrollment[G09a-X-CABT-05]` | `{"source":"EXACT_CURRENT2","catalog":"ABSENT_WITH_ENROLLED_POINTER"}` | `NORMAL_CREATE=0; RESUME_REQUIRED_QUARANTINED; NO_NEW_LINEAGE` | `{"domain":"SMALL_FILESYSTEM_INTEGRATION_PLAN","fault":"CA.BOOT.MISSING","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CABT-06 / a / tests/integration/test_maintenance_crash.py::test_management_first_enrollment[G09a-X-CABT-06]` | `{"source":"KNOWN_LEGACY1","catalog":"TRUNCATED_RELEVANT_BINDINGS"}` | `UNKNOWN_NOT_EMPTY; ENROLL=SOURCE_MANAGEMENT_WRITES=0` | `{"domain":"SMALL_FILESYSTEM_INTEGRATION_PLAN","fault":"CA.BOOT.MISSING","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CABT-07 / a / tests/integration/test_maintenance_crash.py::test_management_first_enrollment[G09a-X-CABT-07]` | `{"source":"KNOWN_UNMANAGED_LEGACY1_A","catalog":"VALID_FOR_OTHER_DB_B","name_id_history_operation_overlap":false,"unrelated_fact":"INDEPENDENTLY_CONFIRMED"}` | `READ_COMPATIBILITY_PRESERVED; NO_GLOBAL_BLANKET_BUSY; ENROLL_AUTHORITY=0` | `{"domain":"SMALL_FILESYSTEM_INTEGRATION_PLAN","fault":"CA.BOOT.UNRELATED","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CABT-08 / a / tests/integration/test_maintenance_crash.py::test_management_first_enrollment[G09a-X-CABT-08]` | `{"source":"SPLIT_SECONDARY","catalog":"VALID_PRIMARY_ID_AND_OP_REF","complete_layout":false}` | `NORMAL_ENTRY=0; PRIMARY_PATH_GUESS_OPEN=0; SOURCE_WRITES=0` | `{"domain":"SMALL_FILESYSTEM_INTEGRATION_PLAN","fault":"CA.BOOT.SECONDARY","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CAS-01 / a / tests/integration/test_maintenance_crash.py::test_management_split_links[G09a-X-CAS-01]` | `{"layout":"P","primary":"PLAN_PREPARING_VALID","secondary_link":"MISSING","targets":"ALL_EXACT_PRE"}` | `IMAGE=SOURCE_MUTATION=0; SAME_M_EXPLICIT_RESUME_ONLY` | `{"domain":"SMALL_FILESYSTEM_INTEGRATION_PLAN","fault":"CA.SPLIT.ALL_LINKS","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CAS-02 / a / tests/integration/test_maintenance_crash.py::test_management_split_links[G09a-X-CAS-02]` | `{"layout":"P","all_local_links":"VALID","primary_binding_links":null}` | `IMAGE=SOURCE_MUTATION=0; PARTIAL_PUBLICATION_NOT_ATOMIC` | `{"domain":"SMALL_FILESYSTEM_INTEGRATION_PLAN","fault":"CA.SPLIT.ALL_LINKS","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CAS-03 / a / tests/integration/test_maintenance_crash.py::test_management_split_links[G09a-X-CAS-03]` | `{"layout":"P","all_local_links":"PRESENT","secondary_link_nonce":"FOREIGN"}` | `RECONCILIATION_REQUIRED; IMAGE=SOURCE_MUTATION=0` | `{"domain":"SMALL_FILESYSTEM_INTEGRATION_PLAN","fault":"CA.SPLIT.LINK_BINDING","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CAS-04 / a / tests/integration/test_maintenance_crash.py::test_management_split_links[G09a-X-CAS-04]` | `{"layout":"P","targets":"EXACT_PRE","primary_complete_links":"VALID","all_local_links":"EXACT","resume":"SAME_M_CURRENT_ACTUAL_OWNER"}` | `IMAGE1_AFTER_REAL_DRAIN; SAME_M_E; SOURCE_METADATA_PREWRITE=0` | `{"domain":"SMALL_FILESYSTEM_INTEGRATION_PLAN","fault":"CA.SPLIT.RESUME","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CAS-05 / a / tests/integration/test_maintenance_crash.py::test_management_split_links[G09a-X-CAS-05]` | `{"layout":"P","explicit_role_paths":"COMPLETE","secondary_primary_namespace":"DIFFERENT_DIR_ID"}` | `RESUME_REQUIRED_RECONCILIATION_REQUIRED; FOREIGN_OPEN=0` | `{"domain":"SMALL_FILESYSTEM_INTEGRATION_PLAN","fault":"CA.SPLIT.LINK_BINDING","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CAS-06 / a / tests/integration/test_maintenance_crash.py::test_management_split_links[G09a-X-CAS-06]` | `{"layout":"P","head_sequence":2,"valid_contiguous_last_record":3,"marker":"ABSENT","same_plan":true}` | `C0_NEEDS_RESUME; POINTER_REPAIR_WRITES=0; SAME_M_E_ON_EXPLICIT_RESUME` | `{"domain":"SMALL_FILESYSTEM_INTEGRATION_PLAN","fault":"CA.SPLIT.HEAD_LAG","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CAF-01 / a / tests/unit/test_maintenance.py::test_management_floor_credit[G09a-X-CAF-01]` | `{"catalog_floor":5,"actual_valid_own_DB_POST_epoch":7,"new_operation":true}` | `FLOOR7_NEW_E8; NO_CATALOG_UPPER_CAP_OR_RESET` | `{"domain":"JOURNAL_FLOOR_UNIT","fault":"CA.FLOOR.MAX_ACTUAL","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CAF-02 / a / tests/unit/test_maintenance.py::test_management_floor_credit[G09a-X-CAF-02]` | `{"planned_E":8,"record_cut":"PRE","catalog_credit_claim":8}` | `NO_CREDIT8; NO_FLOOR_ADVANCE_FROM_PLAN; MUTATION=0` | `{"domain":"JOURNAL_FLOOR_UNIT","fault":"CA.FLOOR.ACTUAL_CREDIT","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CAF-03 / a / tests/unit/test_maintenance.py::test_management_floor_credit[G09a-X-CAF-03]` | `{"db_id":"A","credit_record_db_id":"B","epoch":7}` | `FOREIGN_CREDIT_REJECTED_NOT_KNOWN7` | `{"domain":"JOURNAL_FLOOR_UNIT","fault":"CA.FLOOR.ACTUAL_CREDIT","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CAF-04 / a / tests/unit/test_maintenance.py::test_management_floor_credit[G09a-X-CAF-04]` | `{"kind":"KNOWN","value":7,"required_positive_credit":"MISSING"}` | `UNKNOWN; NO_UNCOMMITTED_OR_ZERO; WRITES=0` | `{"domain":"JOURNAL_FLOOR_UNIT","fault":"CA.FLOOR.ACTUAL_CREDIT","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CAF-05 / a / tests/unit/test_maintenance.py::test_management_floor_credit[G09a-X-CAF-05]` | `{"legacy_metadata":"ABSENT","completed_R_floor":7,"new_apply":"N"}` | `NEW_N_E8; LEGACY_ABSENT_NOT_ZERO; OLD_R_IMAGE_AND_HISTORY_PRESERVED` | `{"domain":"JOURNAL_FLOOR_UNIT","fault":"CA.FLOOR.LEGACY_RETAIN","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CAF-06 / a / tests/unit/test_maintenance.py::test_management_floor_credit[G09a-X-CAF-06]` | `{"floor":{"kind":"KNOWN","value":0,"credits":[]},"actual_fresh_genesis":"MISSING"}` | `KNOWN0_REJECTED_NOT_FRESH_PROOF` | `{"domain":"JOURNAL_FLOOR_UNIT","fault":"CA.FLOOR.ZERO_GENESIS","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CAF-07 / a / tests/unit/test_maintenance.py::test_management_floor_credit[G09a-X-CAF-07]` | `{"kind":"KNOWN","value":7,"credits":"SAME_OPERATION_SEQUENCE_DIGEST_TWICE"}` | `DUPLICATE_REJECTED_NO_SET_DEDUP` | `{"domain":"JOURNAL_FLOOR_UNIT","fault":"CA.FLOOR.CREDIT_UNIQUENESS","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CAM-01 / a / tests/integration/test_maintenance_crash.py::test_management_marker_binding[G09a-X-CAM-01]` | `{"output_preparation":"POST_VERIFIED","future_verified_record":"NOT_YET_CREATED","marker":"NOT_YET_CREATED"}` | `OUTPUT_HAS_NO_SELF_DIGEST_FUTURE_RECORD_OR_MARKER; ORDER_OUTPUT_THEN_RECORD_THEN_MARKER` | `{"domain":"SMALL_FILESYSTEM_PUBLICATION_PLAN","fault":"CA.MARKER.NONCIRCULAR","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CAM-02 / a / tests/integration/test_maintenance_crash.py::test_management_marker_binding[G09a-X-CAM-02]` | `{"marker":"WELL_TYPED","referenced_verified_record":"MISSING"}` | `COMPLETION0; RESUME_REQUIRED_QUARANTINED; MARKER_NOT_DELETED` | `{"domain":"SMALL_FILESYSTEM_PUBLICATION_PLAN","fault":"CA.MARKER.BINDING","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CAM-03 / a / tests/integration/test_maintenance_crash.py::test_management_marker_binding[G09a-X-CAM-03]` | `{"marker_output_digest":"DIFFERENT_FROM_ACTUAL_OUTPUT","record":"VALID_VERIFIED"}` | `COMPLETION0; EVIDENCE_PRESERVED; NO_NORMAL_ENTRY` | `{"domain":"SMALL_FILESYSTEM_PUBLICATION_PLAN","fault":"CA.MARKER.BINDING","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CAM-04 / a / tests/integration/test_maintenance_crash.py::test_management_marker_binding[G09a-X-CAM-04]` | `{"targets":"ALL_POST","local_floor_publish":"FAIL_BEFORE_VERIFIED_MARKER"}` | `MARKER_ADMISSION0; NO_POST_MARKER_REPAIR_DESIGN; SAME_M_E_RESUME` | `{"domain":"SMALL_FILESYSTEM_PUBLICATION_PLAN","fault":"CA.MARKER.FLOOR_ORDER","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CAM-05 / a / tests/integration/test_maintenance_crash.py::test_management_marker_binding[G09a-X-CAM-05]` | `{"valid_complete":"OLD_M","actual_new_owner":"VERIFIED_CURRENT_C6","legal_business_write":"SUCCEEDED_AFTER_COMPLETION"}` | `HISTORY_ARTIFACT_VALID; NO_PERMANENT_OUTPUT_DATA_EQUALITY; CURRENT_AUTHORITY_RECHECK_REQUIRED` | `{"domain":"SMALL_FILESYSTEM_PUBLICATION_PLAN","fault":"CA.MARKER.HISTORICAL_OUTPUT","single_fault":"CHANGE_ONLY_THE_NAMED_TYPED_GUARD_OR_ORDER_AT_THE_TARGET; CONCRETE_SITE_PENDING_IMPLEMENTATION"}` |
| `G09a-X-CAM-06 / a / tests/integration/test_maintenance_crash.py::test_management_marker_binding[G09a-X-CAM-06]` | `{"base":"HAND_OUTPUT_O1","add":{"output_digest":"eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"}}` | `ROOT_UNKNOWN_SELF_DIGEST_KEY_REJECTED_AT_TARGET_GUARD; IF_GUARD_REMOVED_KEYSET_RETURNS_UNREJECTED` | `{"domain":"OUTPUT_ROOT_KEYSET_UNIT","fault":"CA.MARKER.NONCIRCULAR","single_fault":"REMOVE_ONLY_OUTPUT_ROOT_ALLOWED_KEY_GUARD; NESTED_EMPTY_TARGET_FAILURE_IS_MASKED_NOT_KILL"}` |
| `G09a-X-CAW-25 / a / tests/unit/test_schema_catalog.py::test_management_wire_types[G09a-X-CAW-25]` | `{"partition":"Canonical hand B1 plus exactly one ASCII space after root open","raw_utf8":"{ \"anchor_identity\":{\"file_id_hex\":\"11111111111111111111111111111111\",\"kind\":\"DIR\",\"volume_hex\":\"0000000000000000\"},\"catalog_id\":\"33333333333333333333333333333333\",\"entries\":[{\"current\":{\"identity\":null,\"name\":\"jobs.db\"},\"dataset_id\":\"55555555555555555555555555555555\",\"db_id\":\"44444444444444444444444444444444\",\"epoch_floor\":{\"kind\":\"UNCOMMITTED\"},\"genesis\":{\"intent_id\":\"66666666666666666666666666666666\",\"kind\":\"FRESH_INIT\",\"layout\":{\"primary\":{\"anchor_identity\":{\"file_id_hex\":\"11111111111111111111111111111111\",\"kind\":\"DIR\",\"volume_hex\":\"0000000000000000\"},\"catalog_id\":\"33333333333333333333333333333333\",\"kind\":\"DB_PARENT\",\"namespace_identity\":{\"file_id_hex\":\"22222222222222222222222222222222\",\"kind\":\"DIR\",\"volume_hex\":\"0000000000000000\"}},\"targets\":[{\"anchor_identity\":{\"file_id_hex\":\"11111111111111111111111111111111\",\"kind\":\"DIR\",\"volume_hex\":\"0000000000000000\"},\"dataset_id\":\"55555555555555555555555555555555\",\"db_id\":\"44444444444444444444444444444444\",\"name\":\"jobs.db\",\"namespace_identity\":{\"file_id_hex\":\"22222222222222222222222222222222\",\"kind\":\"DIR\",\"volume_hex\":\"0000000000000000\"},\"pre_identity\":null,\"profile_id\":\"F2_J\",\"roles\":[\"jobs\"]}]}},\"history\":[],\"operation_ref\":null,\"primary\":{\"anchor_identity\":{\"file_id_hex\":\"11111111111111111111111111111111\",\"kind\":\"DIR\",\"volume_hex\":\"0000000000000000\"},\"catalog_id\":\"33333333333333333333333333333333\",\"kind\":\"DB_PARENT\",\"namespace_identity\":{\"file_id_hex\":\"22222222222222222222222222222222\",\"kind\":\"DIR\",\"volume_hex\":\"0000000000000000\"}},\"roles\":[\"jobs\"],\"state\":\"PREPARED\"}],\"format\":\"recoryn-management-bindings-v1\",\"generation\":0,\"namespace_identity\":{\"file_id_hex\":\"22222222222222222222222222222222\",\"kind\":\"DIR\",\"volume_hex\":\"0000000000000000\"},\"version\":1}","raw_sha256":"bcec7bc53931996b932ddc0d174f08d45a96442acf353019c9efae2a71a33d9f"}` | `MALFORMED; source_writes0; counterpart B1 accepted; raw equality target` | `{"domain":"SAME_EXPLICIT_NAMED_SMALL_WIRE_OR_CONTROLLED_CORE_CUT_SELECTED_NOT_EXECUTED","fault":"CA.WIRE.RAW_CANONICAL_EQUALITY","single_fault":"Remove only strict raw==typed-canonical comparison"}` |
| `G09a-X-CAW-26 / a / tests/unit/test_schema_catalog.py::test_management_wire_types[G09a-X-CAW-26]` | `{"partition":"Canonical hand B1 root first two keys swapped; all values and spacing unchanged","raw_utf8":"{\"catalog_id\":\"33333333333333333333333333333333\",\"anchor_identity\":{\"file_id_hex\":\"11111111111111111111111111111111\",\"kind\":\"DIR\",\"volume_hex\":\"0000000000000000\"},\"entries\":[{\"current\":{\"identity\":null,\"name\":\"jobs.db\"},\"dataset_id\":\"55555555555555555555555555555555\",\"db_id\":\"44444444444444444444444444444444\",\"epoch_floor\":{\"kind\":\"UNCOMMITTED\"},\"genesis\":{\"intent_id\":\"66666666666666666666666666666666\",\"kind\":\"FRESH_INIT\",\"layout\":{\"primary\":{\"anchor_identity\":{\"file_id_hex\":\"11111111111111111111111111111111\",\"kind\":\"DIR\",\"volume_hex\":\"0000000000000000\"},\"catalog_id\":\"33333333333333333333333333333333\",\"kind\":\"DB_PARENT\",\"namespace_identity\":{\"file_id_hex\":\"22222222222222222222222222222222\",\"kind\":\"DIR\",\"volume_hex\":\"0000000000000000\"}},\"targets\":[{\"anchor_identity\":{\"file_id_hex\":\"11111111111111111111111111111111\",\"kind\":\"DIR\",\"volume_hex\":\"0000000000000000\"},\"dataset_id\":\"55555555555555555555555555555555\",\"db_id\":\"44444444444444444444444444444444\",\"name\":\"jobs.db\",\"namespace_identity\":{\"file_id_hex\":\"22222222222222222222222222222222\",\"kind\":\"DIR\",\"volume_hex\":\"0000000000000000\"},\"pre_identity\":null,\"profile_id\":\"F2_J\",\"roles\":[\"jobs\"]}]}},\"history\":[],\"operation_ref\":null,\"primary\":{\"anchor_identity\":{\"file_id_hex\":\"11111111111111111111111111111111\",\"kind\":\"DIR\",\"volume_hex\":\"0000000000000000\"},\"catalog_id\":\"33333333333333333333333333333333\",\"kind\":\"DB_PARENT\",\"namespace_identity\":{\"file_id_hex\":\"22222222222222222222222222222222\",\"kind\":\"DIR\",\"volume_hex\":\"0000000000000000\"}},\"roles\":[\"jobs\"],\"state\":\"PREPARED\"}],\"format\":\"recoryn-management-bindings-v1\",\"generation\":0,\"namespace_identity\":{\"file_id_hex\":\"22222222222222222222222222222222\",\"kind\":\"DIR\",\"volume_hex\":\"0000000000000000\"},\"version\":1}","raw_sha256":"7dbba5118ded4d8ce5c22d3090835431732d5d2f57e1a7f0ea46a3d3f920dda4"}` | `MALFORMED; encoder hand B1 unchanged; writes0` | `{"domain":"SAME_EXPLICIT_NAMED_SMALL_WIRE_OR_CONTROLLED_CORE_CUT_SELECTED_NOT_EXECUTED","fault":"CA.WIRE.RAW_CANONICAL_EQUALITY","single_fault":"Same raw equality site as CAW25: dedup before any kill count"}` |
| `G09a-X-API-01 / a / tests/integration/test_migration_backup.py::test_maintenance_preview_admission[G09a-X-API-01]` | `{"partition":"Known normal legacy source, no management namespace/image"}` | `Proposal returned; namespace/image/SQL/management writes0; no future namespace/file identity lookup` | `{"domain":"SAME_EXPLICIT_NAMED_SMALL_WIRE_OR_CONTROLLED_CORE_CUT_SELECTED_NOT_EXECUTED","fault":"API.PREVIEW_NO_FUTURE_IDENTITY","single_fault":"Replace preview with durable-plan/future-ID prerequisite or early namespace creation"}` |
| `G09a-X-API-02 / a / tests/integration/test_migration_backup.py::test_maintenance_preview_admission[G09a-X-API-02]` | `{"partition":"Caller-created same-field intent but no issuing facade approval slot"}` | `Approval refused; C1/image/DDL/namespace mutation0` | `{"domain":"SAME_EXPLICIT_NAMED_SMALL_WIRE_OR_CONTROLLED_CORE_CUT_SELECTED_NOT_EXECUTED","fault":"API.ACTUAL_APPROVAL_ISSUER","single_fault":"Compare fields instead of actual issuer slot/preview instance"}` |
| `G09a-X-API-03 / a / tests/integration/test_migration_backup.py::test_maintenance_preview_admission[G09a-X-API-03]` | `{"partition":"Actual C1/drain ownership done; at C2a current source witness exists, future image slot absent"}` | `Create durable plan/I from current sidecar FILE facts plus planned slots; no early image or future image-ID lookup; no source write before all links` | `{"domain":"SAME_EXPLICIT_NAMED_SMALL_WIRE_OR_CONTROLLED_CORE_CUT_SELECTED_NOT_EXECUTED","fault":"API.CURRENT_SIDECAR_NO_FUTURE_IMAGE","single_fault":"Require future artifact ref instead of current source fact"}` |
| `G09a-X-SP-02 / a / tests/integration/test_maintenance_crash.py::test_metadata_journal_binding[G09a-X-SP-02]` | `{"partition":"SP01 valid remaining facts and sole foreign pointer, request rollback; valid rollback/M image context required as normal counterpart"}` | `MIGRATION_ROLLBACK_UNSAFE + RECONCILIATION_REQUIRED; restore0; preserve evidence/source` | `{"domain":"SAME_EXPLICIT_NAMED_SMALL_WIRE_OR_CONTROLLED_CORE_CUT_SELECTED_NOT_EXECUTED","fault":"SC.SP.ROLLBACK_EXACT_CODE","single_fault":"Return ordinary resume code for rollback-specific refusal"}` |

### 10.4 Hand wire values (not product-generated expected)

B1 is a valid typed PREPARED/FRESH_INIT/UNCOMMITTED wire fact, not an actual enrollment, source creation or runtime permission. Its canonical UTF-8 is 1726 bytes, SHA256 `83bb6f081d0c9f86854da76644fae5127c22dd733cd64eb1f1c72bdd28c289e6`.

```json
{"anchor_identity":{"file_id_hex":"11111111111111111111111111111111","kind":"DIR","volume_hex":"0000000000000000"},"catalog_id":"33333333333333333333333333333333","entries":[{"current":{"identity":null,"name":"jobs.db"},"dataset_id":"55555555555555555555555555555555","db_id":"44444444444444444444444444444444","epoch_floor":{"kind":"UNCOMMITTED"},"genesis":{"intent_id":"66666666666666666666666666666666","kind":"FRESH_INIT","layout":{"primary":{"anchor_identity":{"file_id_hex":"11111111111111111111111111111111","kind":"DIR","volume_hex":"0000000000000000"},"catalog_id":"33333333333333333333333333333333","kind":"DB_PARENT","namespace_identity":{"file_id_hex":"22222222222222222222222222222222","kind":"DIR","volume_hex":"0000000000000000"}},"targets":[{"anchor_identity":{"file_id_hex":"11111111111111111111111111111111","kind":"DIR","volume_hex":"0000000000000000"},"dataset_id":"55555555555555555555555555555555","db_id":"44444444444444444444444444444444","name":"jobs.db","namespace_identity":{"file_id_hex":"22222222222222222222222222222222","kind":"DIR","volume_hex":"0000000000000000"},"pre_identity":null,"profile_id":"F2_J","roles":["jobs"]}]}},"history":[],"operation_ref":null,"primary":{"anchor_identity":{"file_id_hex":"11111111111111111111111111111111","kind":"DIR","volume_hex":"0000000000000000"},"catalog_id":"33333333333333333333333333333333","kind":"DB_PARENT","namespace_identity":{"file_id_hex":"22222222222222222222222222222222","kind":"DIR","volume_hex":"0000000000000000"}},"roles":["jobs"],"state":"PREPARED"}],"format":"recoryn-management-bindings-v1","generation":0,"namespace_identity":{"file_id_hex":"22222222222222222222222222222222","kind":"DIR","volume_hex":"0000000000000000"},"version":1}
```

HAND_PROGRESS_P1

```json
{"format":"recoryn-maintenance-progress-v1","operation_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","plan_digest":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","record_digest":"cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc","sequence":0,"version":1}
```

HAND_RECORD_R1

```json
{"binding_links":null,"disposition":"RUNNING","format":"recoryn-maintenance-record-v1","operation_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","output_digest":null,"phase":"PREPARING","plan_digest":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","prior_digest":null,"sequence":0,"targets":[{"credited_epoch":null,"db_id":"44444444444444444444444444444444","pre_image":null,"restore_effect":null,"sidecars":[],"source_cut":"PRE","source_digest":"dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd","source_pointer":{"kind":"ABSENT"}}],"version":1}
```

HAND_OUTPUT_O1

```json
{"format":"recoryn-maintenance-output-v1","operation_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","plan_digest":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","targets":[]}
```

HAND_OUTPUT_O1 has empty targets only for the CAM06 root-keyset validator unit. It is not a valid completed operation or publication positive; a later empty-target rejection is MASKED, not a target kill. Other phases/cuts require their complete valid counterparts before applying the named negative delta.

### 10.5 S1 FIX1: FP05-08 (4 new rows)

아래4행은 원3982/CA107/SC12와 별도인 S1 FIX1 증가4다. p8 R16~19의 actual FAIL4를 X00가 XML/source로 확인해 배정한 입력이며 조립자는 진행 중 제품·시험·runtime 증거를 읽거나 재실행하지 않았다. 원 S1 의미16+추가4=의미20, 감사1을 포함한 수집 목표는21이다. 구 full은 `INCOMPLETE_SUPERSEDED_FOR_S1_FIX1`로 보존하고 구 정적/481·19변이 결과를 최신 full PASS/coverage/wheel로 이전하지 않는다. X00가 자기4 PID의 실제 신원을 확인해 종료한 사실과 이 조립의 PID 조작0을 구분하며 새 full은 수정 입력 봉인 뒤 별도다.

새 logical fault 의도는 known PRAGMA collation canonical화 제거(FP05 또는06), DEFAULT 괄호 관측 일관성 보완 되돌림(FP07), STRICT implicit NN 혼동(FP08)의3개다. 같은 collation site를 두 kill로 세지 않는다. 원19+새3의 예정22는 같은 최신 입력에서 실제 site/목표를 봉인·실행한 뒤 판정한다. 실제 API를 한 번 호출하고 “지원 SQL이 거부되지 않아야 한다”는 명시 assertion이 실패해야 목표 검출이며 uncaught ValueError/TypeError/fixture/import/timeout/다른 guard 거부를 kill로 바꾸지 않는다. 원 정상 대조·읽기쓰기0·독립 hand oracle·60초 게이트를 유지한다.

| ID / owner / primary | Exact SQL input | Hand bytes / fingerprint / assertion | Fault intention |
| --- | --- | --- | --- |
| `G09a-X-FP-05 / a / tests/unit/test_schema_catalog.py::test_component_shape_wire[G09a-X-FP-05]` | `{"component":"jobs.checkpoints","SQL_change":"result_ref TEXT NOT NULL COLLATE nocase","column_collation":"NOCASE","unique_second_key_collation":"NOCASE"}` | `{"bytes":490,"fingerprint":"recoryn-shape-v1:eeef915f23b6ccd2e5ccb0f38733493024f80a26a29fc9a22c0e99c7396a4a13","supported_SQL_must_not_be_rejected":true,"write0":true,"authority0":true}` | `S1.FIX1.KNOWN_PRAGMA_COLLATION_CASE` |
| `G09a-X-FP-06 / a / tests/unit/test_schema_catalog.py::test_component_shape_wire[G09a-X-FP-06]` | `{"component":"jobs.checkpoints","SQL_change":"column remains BINARY; UNIQUE(job_id,result_ref COLLATE nocase)","column_collation":"BINARY","unique_second_key_collation":"NOCASE"}` | `{"bytes":490,"fingerprint":"recoryn-shape-v1:d287ca74a47a529e15c839cc7bd4ddf2b7b6ede66409f31402e145c821dc160a","supported_SQL_must_not_be_rejected":true,"write0":true,"authority0":true}` | `S1.FIX1.KNOWN_PRAGMA_COLLATION_CASE` |
| `G09a-X-FP-07 / a / tests/unit/test_schema_catalog.py::test_component_shape_wire[G09a-X-FP-07]` | `{"component":"content.summary_requests","SQL_change":"request_count INTEGER NOT NULL DEFAULT (1)","default_tokens":[["p","("],["n","1"],["p",")"]]}` | `{"bytes":532,"fingerprint":"recoryn-shape-v1:b383b3000188c84d7fe0f2626297da93b2b21df0aa951e7b79626b2812138c98","supported_SQL_must_not_be_rejected":true,"write0":true,"authority0":true}` | `S1.FIX1.DEFAULT_PARENS_PRAGMA_CONSISTENCY` |
| `G09a-X-FP-08 / a / tests/unit/test_schema_catalog.py::test_component_shape_wire[G09a-X-FP-08]` | `{"component":"jobs.receipts","SQL_change":"job_create_receipts table suffix STRICT","strict":true,"explicit_notnull_of_TEXT_PK":false}` | `{"bytes":429,"fingerprint":"recoryn-shape-v1:8720648ff93d08c82388945223ca41fc406329add1c40e3e2fe056df2b71061e","supported_SQL_must_not_be_rejected":true,"write0":true,"authority0":true}` | `S1.FIX1.STRICT_IMPLICIT_VS_EXPLICIT_NN` |

G09a-X-FP-05 hand wire

```json
{"component":"jobs.checkpoints","format":"recoryn-shape-v1","objects":[{"autoincrement":false,"autoindexes":[["u",[["job_id","ASC","BINARY"],["result_ref","ASC","NOCASE"]]]],"checks":[],"columns":[["job_id","TEXT",true,null,0,0,"BINARY"],["attempt_id","TEXT",true,null,0,0,"BINARY"],["result_ref","TEXT",true,null,0,0,"NOCASE"]],"foreign_keys":[[["job_id"],"jobs",["job_id"],"NO ACTION","NO ACTION","NONE"]],"kind":"table","name":"job_checkpoints","rowid":true,"strict":false}],"version":1}
```

G09a-X-FP-06 hand wire

```json
{"component":"jobs.checkpoints","format":"recoryn-shape-v1","objects":[{"autoincrement":false,"autoindexes":[["u",[["job_id","ASC","BINARY"],["result_ref","ASC","NOCASE"]]]],"checks":[],"columns":[["job_id","TEXT",true,null,0,0,"BINARY"],["attempt_id","TEXT",true,null,0,0,"BINARY"],["result_ref","TEXT",true,null,0,0,"BINARY"]],"foreign_keys":[[["job_id"],"jobs",["job_id"],"NO ACTION","NO ACTION","NONE"]],"kind":"table","name":"job_checkpoints","rowid":true,"strict":false}],"version":1}
```

G09a-X-FP-07 hand wire

```json
{"component":"content.summary_requests","format":"recoryn-shape-v1","objects":[{"autoincrement":false,"autoindexes":[["pk",[["session_id","ASC","BINARY"]]]],"checks":[],"columns":[["session_id","TEXT",false,null,1,0,"BINARY"],["settings_key","TEXT",true,null,0,0,"BINARY"],["request_count","INTEGER",true,[["p","("],["n","1"],["p",")"]],0,0,"BINARY"]],"foreign_keys":[[["session_id"],"sessions",["session_id"],"NO ACTION","CASCADE","NONE"]],"kind":"table","name":"content_summary_requests","rowid":true,"strict":false}],"version":1}
```

G09a-X-FP-08 hand wire

```json
{"component":"jobs.receipts","format":"recoryn-shape-v1","objects":[{"autoincrement":false,"autoindexes":[["pk",[["request_job_id","ASC","BINARY"]]]],"checks":[],"columns":[["request_job_id","TEXT",false,null,1,0,"BINARY"],["job_id","TEXT",true,null,0,0,"BINARY"]],"foreign_keys":[[["job_id"],"jobs",["job_id"],"NO ACTION","NO ACTION","NONE"]],"kind":"table","name":"job_create_receipts","rowid":true,"strict":true}],"version":1}
```

## 11. 조립 확인 결과·인수 경계

SC12 primary와 data container의 두 확인 사항은 모두 X00 확정 답변으로 닫혔다. 원 R2 typed-cell/순서/중복/metadata 제외/engine 상태 보존 규칙과 필수 충돌은 발견하지 않았다. 선택 semantic 분모4105를 줄이거나 새 skip으로 해결한 것이 아니다.

| 항목 | 정확한 누락·요청 / 최소 처리 |
| --- | --- |
| NA-01 CLOSED — SC12의 실제 primary | X00가 전달한 `test_component_shape_wire[G09a-X-SC-01]`부터 `-12`까지 정확12 node로 결속했다. FP01~04도 같은 함수의 각 literal parameter다. 감사 node는 분모 제외, semantic 증분0이다. 이 조립이 XML/시험을 다시 실행·검증했다는 뜻은 아니다. |
| NA-02 CLOSED — data digest exact container | X00 결정 LF `e9d07b08f77674156845b9f51b5795c5101678bc93794b209f949bc5d090aa5c`의 root=`{format,tables,sqlite_sequence}`, table=`{name,columns,rows}`, sequence=`{name,seq}`를 §5.1에 옮겼다. actual engine 부재NULL/존재빈[]를 구분하고 seq는 nonnegative signed64의 typed INTEGER cell이다. 원 R2 cell/순서/중복 보존과 metadata 두 표 제외를 유지한다. 관리8MiB를 전체 data stream/DB 크기에 적용하지 않으며 raw 본문 영속화·로그0이다. |

이는 X00의 명시 결정 인수이며 질문 UI 대리 입력·진행 S1 파일 조회·범위 밖 구현으로 해소한 것이 아니다. source에서 이미 구현됐다는 주장도 아니다. 관리 wire/preview/data의 손 자료는 본문과 미래 시험의 독립 hand literal로 닫을 수 있어 versioned golden 변경·추가 정본 data file scope는 요청하지 않는다.

### 11.1 기존 행의 관측 재사용과 미승인 새 tuple 후보

기존 D/H/CR의 실제 정상 pre/post 자료·복원 보존 관측에는 같은 source 행/열/storage class·metadata 분리·실제 sqlite_sequence/자동증가 상태와 hash 결속을 추가 단언할 수 있다. 기존 image/source 비교에 새 dump 형식을 적용하는 관측 보강 자체는 증분0이다. source에 원래 없는 REAL/BLOB/중복/특정 engine 상태·8MiB 초과 자료나 새 반환 순서/새 장애를 fixture에 추가하면 같은 tuple라고 부르지 않는다. 실제 기존 fixture가 해당 입력을 포함하는지는 후속 코드/증거 인수 때 확인하며 이번에 포함됐다고 추정하지 않았다. C4/G06의 승인된 업무 변경 때문에 pre/post data가 달라질 수 있으므로 모든 migration에 data hash 불변을 일괄 요구하지 않는다.

다음은 원 fixture에서 관측되지 않을 때 고려할 **미승인 후보7개**이며 formal semantic ID·분모·새 파일·실행/PASS 증분은 모두0이다. 각 후보는 formatter/row-sort/hash-consumer의 단위 경계를 명시하며 빈 tables·고립 cell 모델을 정상 profile/CURRENT/실제 DB/소유 양성으로 위장하지 않는다. 제안 위치는 기존 소유 `tests/unit/test_maintenance.py`의 후속 data digest 단위 시험이고 현재 S1 두 API에 넣지 않는다.

| 후보 label | 독립 입력 / 손 목표 | 단일 fault 의도 |
| --- | --- | --- |
| DATA-CAND-01 | root key/serializer 단위의 sqlite_sequence=NULL. 실제 engine 부재의 표현은NULL이며[]로 바꾸지 않음 | NULL을빈배열로 바꿈 |
| DATA-CAND-02 | 같은 serializer 단위의 sqlite_sequence=[]. 존재빈 상태는[]이며NULL과 다른 bytes/digest | 빈배열을NULL로 바꿈 |
| DATA-CAND-03 | sequence 단위 `{name:"events",seq:["integer","0"]}`. exact typed integer 보존 | typed cell을plain int로 unwrap |
| DATA-CAND-04 | 위 정상 counterpart에서 seq만 plain JSON int0. 올바른 typed cell로 강제 변환하지 않고 거부·유효 digest 채택0 | plain int coercion 허용 |
| DATA-CAND-05 | row-sort 단위 `b,a,a` 세 typed TEXT row. canonical 결과는 `a,a,b`로 두 중복을 유지 | 중복 row를set으로 제거 |
| DATA-CAND-06 | typed cell 단위 REAL의 `8000000000000000`(-0 bit). 원16hex를 그대로 보존 | -0을+0 bit로 정규화 |
| DATA-CAND-07 | hash-consumer 단위의 손 canonical 반복 stream 총8388609B를 작은 유한 chunk로 공급. 관리 object가 아니므로 관리8MiB 거부를 적용하지 않고 전체 SHA를 계산 | 관리8MiB cap을 data stream에 잘못 적용 |

이 후보들은 다른 정상 counterpart를 선행 setup으로 명시하고 실제 단일 site/목표를 구현 후 봉인해야 한다. parser/phase/소유의 다른 방어가 목표를 가리면 MASKED, import/setup/예상 밖 오류는 INVALID다. 실제 supported profile에서 별도 source tuple가 필요하면 그 feasible/제외·literalID/primary/hand oracle/단일 mutation을 먼저 인수한다. 후보7을 선택4105/명시245에 더하지 않는다.

원 resource/CA의 본인 초안 자체를 최종 독립 승인하지 않았고, 승인된 X00 override와 pA 교차 인수만 조립했다. 독립 문서 확인·공유 정본 반영·새 BASE/정확 scope/구현 배정은 X00 소관이다. source5dda의 정적 근거만 사용했으며 실제 codec·bootstrap·issuer·OS 소유·source closure·C1/ACK·migration/복원·late I/O·금융/삭제/건강·성능/전체 CI/coverage/wheel은 미검증이다. 이번 제품 import·DB/OS/API/시험/수집/변이·기존/공유/제품/Git 쓰기·네트워크/설치/실장치/음성/모델/vault/유료·추가 agent/pane/승인UI0이다. 실제 S1 결과를 본 조립의 새 PASS로 계산하지 않는다.

## 2026-11-27 D12: 관리 wire 타입 기반의 첫 제품 증분

이 절은 원 v1 유지보수 계약을 축소하지 않고 구현 증분을 구분한다. 첫 제품 단위는 current-F2 범위의 순수 관리 wire codec·canonical DTO 기반이다. 앱의 실제 plan/apply/resume/rollback, FILE/owner/receipt/chain/epoch floor/marker/ACK 권위와 G09a 전체 구현 완료는 후속 과제다. 아래 API가 반환한 DTO는 typed 사실이며 실제 현재성·작업 권한·파일 존재·검증 완료 증명서가 아니다.

기준 공개는 0c42fc397b3d0abec0e29e3a15f46a1475558a8b이며 복구 CI45924795426의 core3.11/core3.13/optional-runtime 실제 성공은 X00가 인수했다. 그 성공은 이 새 타입 증분의 새 실행 결과가 아니다. 최초 제품 source 후보는 S7 LF6ecc3973d01e31caa45e268bf7887e996a1e8d92650e8b1cd75d53cd6a395cc5다. 최종 제품 tree·검증·공개 상태는 이 단위의 독립 검토와 Git/원격 CI로 따로 결속한다. 이 절 작성 시 후보 결속/신규 시험은 진행 중이며 새 제품 full/coverage/wheel PASS를 주장하지 않는다.

### 공개 API·타입·오류의 한정 채택

기존 S1 공개 API인 schema.expected_shape_wire/component_shape_wire 두 개를 보존한다. 앞선 계획 표의 inspect_schema는 후속 인터페이스이며 공개0c42와 이번 S7 source에 구현돼 있지 않다. 이 증분에 stub을 추가하거나 기존 구현으로 기록하지 않는다. 추가 공개 API는 다음과 같다.

```text
schema.decode_management(raw: bytes, *, kind: ManagementObjectKind) -> ManagementDocument
schema.encode_management(document: ManagementDocument) -> bytes
```

ManagementObjectKind는 정확 BINDINGS/PLAN/RECORD/PROGRESS/OUTPUT/COMPLETE 여섯 Enum 값이다. decode는 정확 kind, 정확 bytes, wire budget, 해당 body 순으로 검사한다. encode는 정확한 root class 여섯 개만 받고 duck getter/coercion으로 root를 바꾸지 않는다. Python 함수 인자 binding의 TypeError와 함수 내부 wire 오류를 구분한다. 내부 오류는 단일 SchemaWireError(ValueError)의 MALFORMED/LIMIT_EXCEEDED이며 표준 str/repr/args는 closed kind만 표시한다. 원 S1의 builtin ValueError 의미는 바꾸지 않는다. immutable 문자열·suppressed exception context의 메모리 소거를 보장하지 않는다.

canonical root 여섯 개는 BindingsDocument/PlanDocument/RecordDocument/ProgressDocument/OutputDocument/CompleteDocument다. 아래 canonical DTO34는 recoryn.schema의 실제 module/qualname를 가진 frozen/slots 값이며 공유 Identity와 pointer class를 별도 body별로 복제하지 않는다. private 과거 DTO/pickle의 자동 호환을 보장하지 않는다. 원 component-shape의 SQL 읽기와 관리 codec의 무I/O는 별도 경계다.

| canonical DTO | ordered field:type |
| --- | --- |
| `ManagementIdentity` | `kind:Literal['FILE', 'DIR'], volume_hex:str, file_id_hex:str` |
| `BindingPrimary` | `kind:Literal['LIBRARY_ROOT', 'DB_PARENT'], anchor_identity:ManagementIdentity, namespace_identity:ManagementIdentity, catalog_id:str` |
| `OperationRef` | `operation_id:str, plan_digest:str, link_nonce:str` |
| `HistoricalBinding` | `name:str, identity:ManagementIdentity, retired_by:OperationRef` |
| `CurrentBinding` | `name:str, identity:ManagementIdentity \| None` |
| `OperationGenesis` | `kind:Literal['OPERATION'], operation_id:str, plan_digest:str` |
| `FreshBindingTarget` | `db_id:str, dataset_id:str, anchor_identity:ManagementIdentity, namespace_identity:ManagementIdentity, name:str, roles:tuple[str, ...], profile_id:str, pre_identity:None` |
| `FreshBindingLayout` | `primary:BindingPrimary, targets:tuple[FreshBindingTarget, ...]` |
| `FreshGenesis` | `kind:Literal['FRESH_INIT'], intent_id:str, layout:FreshBindingLayout` |
| `UncommittedFloor` | `kind:Literal['UNCOMMITTED']` |
| `EpochCredit` | `operation_id:str, plan_digest:str, sequence:int, record_digest:str` |
| `KnownEpochFloor` | `kind:Literal['KNOWN'], value:int, credits:tuple[EpochCredit, ...]` |
| `BindingEntry` | `db_id:str, dataset_id:str, state:Literal['PREPARED', 'BOUND', 'RETIRED'], current:CurrentBinding, history:tuple[HistoricalBinding, ...], roles:tuple[str, ...], primary:BindingPrimary, genesis:OperationGenesis \| FreshGenesis, operation_ref:OperationRef \| None, epoch_floor:UncommittedFloor \| KnownEpochFloor` |
| `BindingsDocument` | `format:Literal['recoryn-management-bindings-v1'], version:int, catalog_id:str, generation:int, anchor_identity:ManagementIdentity, namespace_identity:ManagementIdentity, entries:tuple[BindingEntry, ...]` |
| `ProgressDocument` | `format:Literal['recoryn-maintenance-progress-v1'], version:int, operation_id:str, plan_digest:str, sequence:int, record_digest:str` |
| `AbsentPointer` | `kind:Literal['ABSENT']` |
| `FreshPointer` | `kind:Literal['FRESH'], dataset_id:str, epoch:int` |
| `CommitPointer` | `kind:Literal['COMMIT'], dataset_id:str, operation_id:str, epoch:int, input_digest:str` |
| `PhysicalBinding` | `anchor_identity:ManagementIdentity, parent_identity:ManagementIdentity, name:str, identity:ManagementIdentity` |
| `LocalBinding` | `anchor_identity:ManagementIdentity, namespace_identity:ManagementIdentity, catalog_id:str, db_id:str, link_nonce:str` |
| `PostComponent` | `component:str, version:int, fingerprint:str` |
| `PostContract` | `profile_id:str, physical_version:int, components:tuple[PostComponent, ...], pointer:WirePointer, preservation_digest:str` |
| `PlannedSlot` | `operation_id:str, db_id:str, kind:Literal['DB_IMAGE', 'COST_WITNESS']` |
| `PlanTarget` | `db_id:str, roles:tuple[str, ...], physical_binding:PhysicalBinding, local_binding:LocalBinding, pre_profile:str, pre_pointer:WirePointer, pre_state_digest:str, target_profile:str, target_epoch:int, input_digest:str, post_contract:PostContract, pre_image_slot:PlannedSlot, sidecar_slots:tuple[PlannedSlot, ...]` |
| `PlanDocument` | `format:Literal['recoryn-maintenance-plan-v1'], operation_id:str, kind:WireOperationKind, dataset_id:str, reverses_operation_id:str \| None, targets:tuple[PlanTarget, ...], approval_digest:str, commit_order:tuple[str, ...]` |
| `ArtifactRef` | `operation_id:str, db_id:str, kind:Literal['DB_IMAGE', 'COST_WITNESS'], digest:str, identity:ManagementIdentity` |
| `BindingLink` | `db_id:str, anchor_identity:ManagementIdentity, namespace_identity:ManagementIdentity, catalog_id:str, link_nonce:str, binding_digest:str` |
| `RecordTarget` | `db_id:str, source_cut:Literal['PRE', 'IMAGE_UNREBOUND', 'POST', 'UNRESOLVED'], source_pointer:AbsentPointer \| FreshPointer \| CommitPointer \| None, source_digest:str \| None, pre_image:ArtifactRef \| None, sidecars:tuple[ArtifactRef, ...], credited_epoch:int \| None, restore_effect:Literal['NOT_STARTED', 'INTENT_RECORDED', 'BACKUP_RETURNED', 'BACKUP_FAILED', 'NO_COPY_VERIFIED', 'UNKNOWN', None]` |
| `RecordDocument` | `format:Literal['recoryn-maintenance-record-v1'], version:int, operation_id:str, plan_digest:str, sequence:int, prior_digest:str \| None, phase:Literal['PREPARING', 'IMAGE_VERIFIED', 'APPLYING', 'VERIFYING', 'VERIFIED'], disposition:Literal['RUNNING', 'NEEDS_RESUME', 'QUARANTINED', 'RECONCILIATION_REQUIRED'], targets:tuple[RecordTarget, ...], binding_links:tuple[BindingLink, ...] \| None, output_digest:str \| None` |
| `ComponentFact` | `name:str, version:int, fingerprint:str` |
| `SourceSidecar` | `kind:Literal['COST_WITNESS'], digest:str, identity:ManagementIdentity` |
| `OutputTarget` | `db_id:str, profile_id:str, physical_version:int, components:tuple[ComponentFact, ...], source_pointer:AbsentPointer \| FreshPointer \| CommitPointer, data_digest:str, media_digest:str \| None, sidecar_digests:tuple[SourceSidecar, ...], deletion_digest:str \| None, health_digest:str \| None` |
| `OutputDocument` | `format:Literal['recoryn-maintenance-output-v1'], operation_id:str, plan_digest:str, targets:tuple[OutputTarget, ...]` |
| `CompleteDocument` | `format:Literal['recoryn-maintenance-complete-v1'], operation_id:str, plan_digest:str, record_digest:str, output_digest:str` |

명시 alias8은 아래와 같다. RestoreEffect는 여섯 문자열과 None을 Literal 내부에 두며 별도 Union matcher 확장을 요구하지 않는다.

| alias | exact definition |
| --- | --- |
| `BindingGenesis` | `OperationGenesis \| FreshGenesis` |
| `EpochFloor` | `UncommittedFloor \| KnownEpochFloor` |
| `ManagementDocument` | `BindingsDocument \| PlanDocument \| RecordDocument \| ProgressDocument \| OutputDocument \| CompleteDocument` |
| `RestoreEffect` | `Literal["NOT_STARTED", "INTENT_RECORDED", "BACKUP_RETURNED", "BACKUP_FAILED", "NO_COPY_VERIFIED", "UNKNOWN", None]` |
| `WireDisposition` | `Literal["RUNNING", "NEEDS_RESUME", "QUARANTINED", "RECONCILIATION_REQUIRED"]` |
| `WireOperationKind` | `Literal["APPLY", "ROLLBACK"]` |
| `WirePhase` | `Literal["PREPARING", "IMAGE_VERIFIED", "APPLYING", "VERIFYING", "VERIFIED"]` |
| `WirePointer` | `AbsentPointer \| FreshPointer \| CommitPointer` |

원 component fact의 name과 향후 PostComponent의 component, ArtifactRef/SourceSidecar와 실제 slot/handle을 임의로 합치지 않는다. RECORD의 output_digest는 hex64이고 pre_image 등은 ArtifactRef5다. 단계별 local 문법과 외부 actual object equality를 섞지 않는다.

### 지원 경계와 원 경우의 수

OUTPUT의 이번 실제 지원은 기존 current-F2 profile 조건이다. 별도 private LEGACY_JOBS_R0K0 OUTPUT 분기는 코드·독립 검토가 완료됐어도 이번 source에 합치거나 공용 registry/profile로 채택하지 않는다. legacy 원 정상 기대는 그대로 남기고 MALFORMED로 바꾸지 않는다. actual inspector의 DB metadata/receipt/checkpoint 부재·빈/비빈 data equality·LOP01/02는 이 증분에서 닫지 않는다. profile의 typed 지원과 실제 운영 입력의 지원을 구분한다.

원70은 CAW26/CAN18/CAM6/SC12/FP8을 유지한다. 이번 실제 대상은 원 S1 의미20을 보존하고 local CAW26/CAN14의40을 추가하는 계획이다. 보류10은 CAN08/13/14/15와 CAM01~06이다. 실제 계획 E·이전 record digest·APPLY/ROLLBACK plan·marker/workflow oracle가 필요한 행은 pure codec의 다른 거부로 통과 처리하지 않는다. CAM06의 empty O1 root-keyset unit도 실제 공통 접점 추가를 이번에 승인하지 않아 보류한다. 미구현 행의 placeholder/skip/xfail/성공stub을 만들지 않는다.

CAN04의 diagnostic UNRESOLVED/RECONCILIATION_REQUIRED typed 수락과 no-I/O는 실제 normal-entry 거부의 완료 증거가 아니다. CAN03/04/10/11/17/18의 부정은 다른 phase/ref/cut 불일치에 가리지 않는 완전한 정상 counterpart에서 고정한다. CAN10의 VERIFYING+nonNULL output은 PREPARING 부정과 다른 tuple이다. CAW12는 원282B/record_digest63 손 raw를 kind=PROGRESS로 보내 actual digest guard에 결속한다. 과거 BINDINGS 도메인의 선행 거부를 그 목표 검출로 쓰지 않는다.

원4105/명시245는 승인된 전체 계획이며 이 증분의 실제 PASS 수가 아니다. 후보269/독립82·private legacy296/독립29를 새 formal 분모나 새 제품 tree PASS로 소급하지 않는다. 원269 node의 의미는 실제 제품 node·보존 S1·같은 의미의 재사용으로 대응시키고 중복 primary 증분0을 기록한다. 추가 API 보강은 literal 입력/기대/선택을 실행 전에 고정한다. 제품 encoder/Enum/registry 계산을 expected로 복제하지 않는다.

### 제품 단위와 검증·잔여 과제

정확 제품 단위는 schema.py, test_schema_catalog.py, 신규 unit API 시험, 신규 property case-space 감사, 신규 wire literal fixture, .gitattributes, 이 문서, v1-gap-plan, assignments, 신규 독립 review의10파일이다. 기존 S1 함수·20 tuple·readonly 연결·golden을 보존한다. 새 fixture의 bytes는 -text 경로 규칙으로 고정한다. 제품과 시험은 build/prototype/test-only adapter의 runtime 의존을 두지 않는다.

정적 ID/primary 감사와 이번 실제 선택 집합의 실행 감사를 구분한다. 단독 ID/property/not-ui에서 비선택 행의 실행을 요구하지 않는다. 실제 selected call1과 setup/teardown 실패는 별도로 확인한다. 동일 site 재확인은 새 unique fault가 아니다. 정상 control 뒤 실제 지정 단계/반환 후 목표 assertion FAIL만 mutation 검출이며 다른 guard는 MASKED, 수집·하네스·timeout은 INVALID다.

정확 BASE archive+승인 파일 tree에서 실제 선택·관련 회귀·원 S1·단일 목표 변이·관리 I/O0·부모/실제 spawn 출처를 확인한다. CI와 같은 Ruff/format/mypy 및 정확 최종 tree의 full core/coverage7/offline wheel과 wheel schema bytes·import/spawn 출처를 연결한다. source/test/fixture가 달라지면 과거 성공을 재사용한 새 성공으로 쓰지 않는다. 로컬3.13/AST3.11은 실제3.11 runtime을 대신하지 않으며 새 공개 SHA의 세 원격 CI를 별도로 인수한다.

실제 유지보수·정상 후속 write·FILE/owner/chain/rollback/VERIFIED/ACK·공용 legacy profile·실서비스/vault/실장비·모델/전원 장애 내구성·메모리 소거는 남은 과제다. 타입 기반만 진행한 상태와 전체 설계 구현·Windows 실장비 완료를 구분한다. 이 순수 증분의 rollback에 사용자 DB/data/witness/grant 복원을 섞지 않는다.

## G09a D13: legacy OUTPUT local wire 조합 증분

이 절은 D12의 current-F2 첫 제품 범위 뒤에 추가할 다음 증분의 계약이다. D12의 legacy 제외·당시 검증 전 스냅샷은 그 시점의 사실로 보존한다. 여기서는 caller가 선언한 **OUTPUT local typed 조합** 하나만 추가한다. 실제 whole-file profile/SQLite/등록/복구 지원을 채택한 것이 아니다. 이 절과 구현·회귀·독립 검토를 같은 정확8파일 단위로 통합하며 실제 PASS·공개 SHA·원격 CI는 해당 tree의 실행 결과로 별도 확인한다.

공개 호출은 `decode_management(raw, kind=ManagementObjectKind.OUTPUT)`와 `encode_management(output_document)`다. 다른 kind·공개 함수/Enum/DTO/alias/signature는 변경하지 않는다. OUTPUT target의 기존10 field와 정렬/unique·타입·정수·canonical·byte/depth budget·닫힌 오류 정책을 유지하면서, 다음 조건을 **모두** 만족하는 한 조합만 허용한다.

| field | 정확한 local 허용 조건 |
| --- | --- |
| profile_id | 정확 문자열 `LEGACY_JOBS_R0K0` |
| physical_version | exact int `0` 또는 `1`; bool·다른 값은 거부 |
| source_pointer | exact `AbsentPointer` / wire `{ "kind": "ABSENT" }` |
| components | 정확1개: name `jobs.core`, version exact int1, fingerprint `recoryn-shape-v1:2a9a2a799001d3377a969193eaed1955de89a9adfaf0a851a77af9811352de0a` |
| media_digest/deletion_digest/health_digest | 모두 NULL |
| sidecar_digests | 빈 배열 / typed 빈 tuple |
| data_digest | 기존 소문자 hex64 문법. 빈 anchor의 digest 하나로 제한하지 않음 |
| db_id/operation_id/plan_digest | 기존 OUTPUT 문법·typed 필드 조건 유지. 실제 DB/plan과의 equality 검증은 아님 |

BINDINGS/PLAN의 F2 profile 목록30, S1 `target_profiles`/expected registry, COMPLETE와 기존 F2 OUTPUT 경로는 그대로다. namespace별 local wire 허용표와 actual whole-file 지원표를 동일시하지 않는다. source diff는 `_mo_target` 한 함수로 한정하고 함수 밖 bytes/AST/signature·import/helper/class/상수/alias를 보존한다.

손 입력27은 정상 P1/P0/T1과 부정 N01~N24다. P1/P0는 기존 synthetic 빈 anchor 입력의 physical1/0 표현이며 새 실제 DB 지원 조합의 증거가 아니다. T1은 P1의 data_digest만 다른 유효 hex64로 바꾼 문법 양성이다. 세 정상은 actual public decode 반환·field 보존·exact raw 왕복을 요구한다. 부정24는 원 구체 오류와 constructor/encode 단계의 독립 oracle를 유지한다. N21의 직접 constructor Python binding TypeError를 wire의 SchemaWireError/MALFORMED와 구분한다. constructor 거부6은 encode0, 생성21은 encode 정상3/거부18이며 이 단계 수를 입력 분모에 더하지 않는다.

원70/active40/보류10(CAN08/13/14/15·CAM01~06) 및 전체4105/명시245의 formal 분모·primary는 증가0이다. 아래27개는 그 formal ID를 대체하지 않는 local 보강 node다. 기존322를 유지하고27개를 더한 선택349(catalog61/API285/property3), 전체30467+27=예상30494는 실제 수집/phase/XML 각1로 대조해야 한다. 기존 독립 F2 OUTPUT/COMPLETE control2는 같은 raw의 기존 node를 재사용한다. 과거 private296/독립29·목표2 및 공개322를 새 tree PASS로 합산하지 않는다.

정상/변이 입력은 `tests/fixtures/g09_management_wire_literals_v1.json`에 고정한다. source나 제품 함수로 expected를 생성하지 않으며 기존 모든 raw/hand model/ID/기대·S1 의미20·원 감사·회귀를 보존한다. 제품 시험 primary는 `tests/unit/test_management_wire_api.py::test_legacy_output_wire[ID]`다. 각 raw의 실제 bytes/SHA와 원 oracle는 아래 표 및 versioned fixture로 결속한다.

| ID | bytes | SHA-256 | wire oracle | constructor/encode oracle |
| --- | --- | --- | --- | --- |
| P1 | 630 | `682f8f9f4c7f1ed1a8da8139d04c75a114fb4088374bfbd07bd7f10ed21c55d1` | RETURN_AND_EXACT_ROUNDTRIP | RETURN_AND_ENCODE_RAW |
| P0 | 630 | `61a61dba720bbbd7a794f9f421083fe80e80246fc70c58dfe5627eb5936a0850` | RETURN_AND_EXACT_ROUNDTRIP | RETURN_AND_ENCODE_RAW |
| T1 | 630 | `72046bf820fc9de5fa5c4e175534612b5385359b1a5ab0ca73f3ba80b56f3bc7` | RETURN_AND_EXACT_ROUNDTRIP | RETURN_AND_ENCODE_RAW |
| N01 | 630 | `5cad06a717aee673a59990e1e30b7a90fbb0879af6dca0b40d7f798f27e1d222` | EXACT_SCHEMA_WIRE_ERROR_MALFORMED | RETURN_THEN_ENCODER_MALFORMED |
| N02 | 630 | `608dabe9d5c4afc3f98a0ced1d7473159da38979bdfcae2f25e8d7fa4b1badc2` | EXACT_SCHEMA_WIRE_ERROR_MALFORMED | RETURN_THEN_ENCODER_MALFORMED |
| N03 | 633 | `a8f33df8567cc270ade4c9c1e394837baf5b0fa6744f5f20d4de608f20a3b267` | EXACT_SCHEMA_WIRE_ERROR_MALFORMED | SCHEMA_WIRE_ERROR_BEFORE_ENCODE |
| N04 | 632 | `0892d7770a966ec0a46336ce7126c46015fdb397c9d6bcdd7ba23f96c177e619` | EXACT_SCHEMA_WIRE_ERROR_MALFORMED | SCHEMA_WIRE_ERROR_BEFORE_ENCODE |
| N05 | 617 | `82ef7202f936130c468803b82e38393b9b40aa7057cc614d5e96085a774b2ab1` | EXACT_SCHEMA_WIRE_ERROR_MALFORMED | SCHEMA_WIRE_ERROR_BEFORE_ENCODE |
| N06 | 687 | `9551b2340743e985382c703ac763e755a03fdbcda01a48cb1ecee5d0b66d1fda` | EXACT_SCHEMA_WIRE_ERROR_MALFORMED | RETURN_THEN_ENCODER_MALFORMED |
| N07 | 820 | `cc058e88a8c7b3386f94b2277a26b4dcfa4e3b39ddcbdf67f03f0c9cdd8fe67d` | EXACT_SCHEMA_WIRE_ERROR_MALFORMED | RETURN_THEN_ENCODER_MALFORMED |
| N08 | 500 | `632b1e95a52efd8d527ae14585254200632ad6c4b9a424c2c1a1f13c38b4500f` | EXACT_SCHEMA_WIRE_ERROR_MALFORMED | RETURN_THEN_ENCODER_MALFORMED |
| N09 | 634 | `56fc221a7639e085891d9284bcb1708a5185f2e370fecc624e457e5497f65b3a` | EXACT_SCHEMA_WIRE_ERROR_MALFORMED | RETURN_THEN_ENCODER_MALFORMED |
| N10 | 630 | `9d6f6b20b438723e9e937feffd4e909553c9396a19e6b5d444047b0bbab188c0` | EXACT_SCHEMA_WIRE_ERROR_MALFORMED | RETURN_THEN_ENCODER_MALFORMED |
| N11 | 630 | `2b6d572a645b0c2418d70f858ee1efb3171aad3f303e4931062770de34a82bb7` | EXACT_SCHEMA_WIRE_ERROR_MALFORMED | RETURN_THEN_ENCODER_MALFORMED |
| N12 | 765 | `6e4726e9880644c024fb29ff5eb17ea1051befb8fcca6c1ca63b66ee2c5dd548` | EXACT_SCHEMA_WIRE_ERROR_MALFORMED | RETURN_THEN_ENCODER_MALFORMED |
| N13 | 766 | `55d38aab3547230442dc3370214432802226c38d245594b71fc5bad104715d0a` | EXACT_SCHEMA_WIRE_ERROR_MALFORMED | RETURN_THEN_ENCODER_MALFORMED |
| N14 | 621 | `08d018f643d8b7da17a1871029c7bc5c656ba2e5431f6e8585a4c3433623df9a` | EXACT_SCHEMA_WIRE_ERROR_MALFORMED | RETURN_THEN_ENCODER_MALFORMED |
| N15 | 618 | `43d04ddb9afae9eb96e43481aed1afa15495ff9d813f6026302494e080880c17` | EXACT_SCHEMA_WIRE_ERROR_MALFORMED | RETURN_THEN_ENCODER_MALFORMED |
| N16 | 692 | `0fdbb3a8330f16f6d9d5c438bca6cc2261d52d5031c251e7aa16977f7b8d82d1` | EXACT_SCHEMA_WIRE_ERROR_MALFORMED | RETURN_THEN_ENCODER_MALFORMED |
| N17 | 692 | `92fef03566290797c735eb6202e2d3f3e2d02299e253cb5c6fe32363190abfe4` | EXACT_SCHEMA_WIRE_ERROR_MALFORMED | RETURN_THEN_ENCODER_MALFORMED |
| N18 | 692 | `136f72483ea6b9af74b8e544596d67c20353c6ac069077e4f694d93271574e94` | EXACT_SCHEMA_WIRE_ERROR_MALFORMED | RETURN_THEN_ENCODER_MALFORMED |
| N19 | 837 | `f7298229844c022db9b2390cf4f823b4ff6253f5d78c691c9d077cc718e21c57` | EXACT_SCHEMA_WIRE_ERROR_MALFORMED | RETURN_THEN_ENCODER_MALFORMED |
| N20 | 632 | `bef6c575be9ed8efd58cfda3da48e8fb4f4f45a90dab9ddddd1e87022c82d1cc` | EXACT_SCHEMA_WIRE_ERROR_MALFORMED | SCHEMA_WIRE_ERROR_BEFORE_ENCODE |
| N21 | 657 | `38eca8c7fe46e564da5e6e25aa6be808163fced570ae3c51d5e5a966254c47ba` | EXACT_SCHEMA_WIRE_ERROR_MALFORMED | PYTHON_TYPE_ERROR_BEFORE_ENCODE |
| N22 | 629 | `6f3571b91f2aede7692ea6d60b7be8fd6e4a6a4bbf85d825bca0fb4b44722f13` | EXACT_SCHEMA_WIRE_ERROR_MALFORMED | RETURN_THEN_ENCODER_MALFORMED |
| N23 | 761 | `e5db57f83ca3319957b20410495c6372b9e286eed09f82dd3912a70832f0ca66` | EXACT_SCHEMA_WIRE_ERROR_MALFORMED | RETURN_THEN_ENCODER_MALFORMED |
| N24 | 633 | `d33c3917e68dec2bd879ae37459b62c70dbc257244ab2998528645cedb440022` | EXACT_SCHEMA_WIRE_ERROR_MALFORMED | SCHEMA_WIRE_ERROR_BEFORE_ENCODE |

MW1은 legacy physical membership에2만 추가한 단일 site를 N01이 검출해야 한다. MW2는 legacy exact-FP 비교 한 곳만 제거한 site를 N11이 검출해야 한다. 정상 control 이후 실제 public API 반환·지정 assertion FAIL만 검출로 세며 MASKED·수집/setup/timeout/관측 INVALID는 분리한다. 같은 원 site의 재확인이며 고유 fault 수를 늘리지 않는다.

필수 gate는 준비 포함 선택349 wall60초·단독 legacy/property/not-ui 및 실제 selected call/XML 각1·부모/실spawn의 source/공개 함수/공유 identity·관리 API I/O0·S1 readonly SQLite/연결 보존, 정적3종·관련 회귀·두 단일site, 동결 새 제품 결속 독립 검토와 공용 append 독립 검토다. X00가 최종 정확8 tree full core/coverage7/offline wheel87 raw·실제 wheel 부모/spawn·실제 commit/tree/메시지/trailer0·normal push/ref·새 SHA CI3을 종결한다. 선행60f4의 세 CI 실제 성공 전 의존 공개는 금지한다. 검증 실패·예산 초과 시 원 반례와 결과를 보존하고 분모/단언/게이트를 낮추지 않는다.

이 조합의 ABSENT/NULL/빈 sidecars/profile/digest는 실제 SQLite 표·metadata/receipt/checkpoint·media/삭제/건강·내용/현재성/권한의 부재 또는 일치를 증명하지 않는다. LOP01/02·다른 R/K/physical·nonempty/post·actual inspector/profile·plan/chain/FILE/owner/receipt/witness/ACK/등록/복원·실장비는 미종결이다. 이 codec 수락은 어떤 I/O·등록·삭제·복구 허가도 발급하지 않는다. rollback은 순수 코드/문서 단위이며 DB/data/grant 복원을 섞지 않는다.

## D14: private logical current profile 후보의 유한 계약

이 단위는 `_current_profile_candidate`가 공급된 **논리 owned-object 목록**에서 명명 current30 후보와 고정 expected를 제공하는 범위다. actual 파일/SQLite reader·engine 투영·schema CURRENT·입장 권위의 완성이 아니다. 공개7cdf/tree316fc를 고정 BASE로 삼고, 작성2와 root 선택감사 보조1을 격리 검증한다. 이 계약의 기술만으로 제품/시험 통과나 새 공개를 주장하지 않는다.

### domain·타입·오류

`schema._current_profile_candidate(logical_objects: tuple[tuple[str,str],...]) -> _CurrentProfileSpec | None`은 private다. caller profile/FP·complete/required·catalog override·Path/connection/owner 인자를 추가하지 않는다. `_CurrentProfileSpec`은 frozen/slots/repr=False이며 필드 순서는 `profile_id`, `components`, `owned_objects`, `registry_rows`다. components는(name,version,고정FP) tuple, owned_objects는(name,kind) tuple, registry_rows는(component,version,FP,profile) tuple이며 정렬/중첩 불변을 유지한다.

outer/pair는 exact tuple, pair 길이는2, name/kind는 exact str, name은 nonempty, kind는 table/index/view/trigger다. 잘못된 typed 입력·빈 이름·같은 name 중복(같은/다른kind)은 정확 builtin ValueError다. unknown의 유효 이름·명명형과 다른 전체 목록·빈 tuple은 None이다. catalog의 중복 profile/name/signature·row/component 모순은 닫힌 RuntimeError이며 NO_MATCH로 숨기지 않는다. raw 입력/path/SQL을 오류/repr에 붙이지 않는다. subclass/duck getter/coercion/strip/casefold/dedup을 허용하지 않고 실제 call 구간 getter/iteration/hash/equality/string/coercion0을 확인한다.

고정 생산 literal12 component/정확30 구성만 사용하며 fixture/build/observed profile·FP를 expected로 되돌려 인증하지 않는다. 시험 expected는 versioned golden306337B와 별도 hand model/literal에서 얻고 제품 parser/catalog/encoder에서 생성하지 않는다. 정상30의 전체 component/version/FP/owned pair/registry rows를 비교한다. 원S1 두 공개 함수/기존 함수·데코레이터/parser/catalog·codec API6/DTO34/alias8과 원SC12/FP8·관리349/raw fixture를 보존한다.

### private51의 정확 primary

private51은 실제 DB/workflow primary와 다른 직접 함수 입력이다. formal70/4105/명시245 증분0이며 같은 입력의 재관측과 실제 운영 PASS를 혼합하지 않는다. 정상30/spec, 유효불일치8/None, typed부정13/ValueError다. 아래 primary는 `tests/unit/test_schema_catalog.py::test_private_current_profile_candidate[ID]`에 대응한다. 정상 순서는 독립 hand의 명명30 배열이고, 이후 입력은 정상 F2_J의 명시 한 차원만 바꾼다(vector3은 별도 component-vector 변화다).

PRIVATE-CP34는 원 손자료의 중복 입력 계약 미결 기대를 D14의 정확 builtin ValueError로 명시 적응하며, 원 hand bytes/oracle와 미결 이력은 보존한다.

| ID | explicit supplied input | expected |
| --- | --- | --- |
| PRIVATE-CP01 | F2_J | spec: F2_J |
| PRIVATE-CP02 | F2_L | spec: F2_L |
| PRIVATE-CP03 | F2_LC | spec: F2_LC |
| PRIVATE-CP04 | F2_LC_CONS | spec: F2_LC_CONS |
| PRIVATE-CP05 | F2_LC_CONS_COST1 | spec: F2_LC_CONS_COST1 |
| PRIVATE-CP06 | F2_LC_CONS_COST2 | spec: F2_LC_CONS_COST2 |
| PRIVATE-CP07 | F2_LC_COST1 | spec: F2_LC_COST1 |
| PRIVATE-CP08 | F2_LC_COST2 | spec: F2_LC_COST2 |
| PRIVATE-CP09 | F2_LJ | spec: F2_LJ |
| PRIVATE-CP10 | F2_LJC | spec: F2_LJC |
| PRIVATE-CP11 | F2_LJC_CONS | spec: F2_LJC_CONS |
| PRIVATE-CP12 | F2_LJC_CONS_COST1 | spec: F2_LJC_CONS_COST1 |
| PRIVATE-CP13 | F2_LJC_CONS_COST2 | spec: F2_LJC_CONS_COST2 |
| PRIVATE-CP14 | F2_LJC_COST1 | spec: F2_LJC_COST1 |
| PRIVATE-CP15 | F2_LJC_COST2 | spec: F2_LJC_COST2 |
| PRIVATE-CP16 | F2_LJ_CONS | spec: F2_LJ_CONS |
| PRIVATE-CP17 | F2_LJ_CONS_COST1 | spec: F2_LJ_CONS_COST1 |
| PRIVATE-CP18 | F2_LJ_CONS_COST2 | spec: F2_LJ_CONS_COST2 |
| PRIVATE-CP19 | F2_LJ_COST1 | spec: F2_LJ_COST1 |
| PRIVATE-CP20 | F2_LJ_COST2 | spec: F2_LJ_COST2 |
| PRIVATE-CP21 | F2_L_CONS | spec: F2_L_CONS |
| PRIVATE-CP22 | F2_L_CONS_COST1 | spec: F2_L_CONS_COST1 |
| PRIVATE-CP23 | F2_L_CONS_COST2 | spec: F2_L_CONS_COST2 |
| PRIVATE-CP24 | F2_L_COST1 | spec: F2_L_COST1 |
| PRIVATE-CP25 | F2_L_COST2 | spec: F2_L_COST2 |
| PRIVATE-CP26 | F2_S_CONS | spec: F2_S_CONS |
| PRIVATE-CP27 | F2_S_CONS_COST1 | spec: F2_S_CONS_COST1 |
| PRIVATE-CP28 | F2_S_CONS_COST2 | spec: F2_S_CONS_COST2 |
| PRIVATE-CP29 | F2_S_COST1 | spec: F2_S_COST1 |
| PRIVATE-CP30 | F2_S_COST2 | spec: F2_S_COST2 |
| PRIVATE-CP31 | catalog-delta/extra | None |
| PRIVATE-CP32 | catalog-delta/missing | None |
| PRIVATE-CP33 | catalog-delta/kind | None |
| PRIVATE-CP34 | catalog-delta/duplicate | builtin ValueError |
| PRIVATE-CP35 | catalog-delta/foreign-component-object | None |
| PRIVATE-CP36 | catalog-role/jobs-with-security-no-library | None |
| PRIVATE-CP37 | catalog-role/bare-content | None |
| PRIVATE-CP38 | catalog-role/cost2-without-v1 | None |
| PRIVATE-CP39 | outer list | builtin ValueError |
| PRIVATE-CP40 | pair list | builtin ValueError |
| PRIVATE-CP41 | pair length1 | builtin ValueError |
| PRIVATE-CP42 | name int | builtin ValueError |
| PRIVATE-CP43 | kind bool | builtin ValueError |
| PRIVATE-CP44 | unregistered kind string | builtin ValueError |
| PRIVATE-CP45 | empty tuple | None |
| PRIVATE-CP46 | empty name | builtin ValueError |
| PRIVATE-CP47 | duplicate name different kind | builtin ValueError |
| PRIVATE-CP48 | outer tuple subclass | builtin ValueError |
| PRIVATE-CP49 | pair tuple subclass | builtin ValueError |
| PRIVATE-CP50 | name str subclass | builtin ValueError |
| PRIVATE-CP51 | kind str subclass | builtin ValueError |

별도 node `test_private_current_profile_literal_audit`와 `test_private_current_profile_order_and_immutability`는 semantic51에서 분리한다. 알려진 private 선택은53이다. bounded permutation은 같은primary의 순서/불변성 관측이며 새 미명시 literal을 param loop에 숨기지 않는다. subclass constructor/준비와 실제 call window를 나누고 직전 counter reset·call 뒤 getter/coercion0을 관측한다. 예기치 않은 getter/fixture 예외를 ValueError 성공으로 세지 않는다.

### 원349와 sibling53의 결속

관리 fixture의 planned349·formal70·활성/보류/원primary는 그대로다. 기존 세 시험 파일을 함께 추적하는 property 감사에는 원349와 **exact sibling53**만 union으로 허용한다. 다른 path/함수·CP00/CP54/자리수가 다른CP1 등 unknown은 불허다. 기존 selected==state·unique·skip/xfail 금지·actual call각1·codec I/O guard는 유지한다. 이 보조파일의 새pytest node는0이다. known union402는 실제 수집/PASS가 아니며 정확 입력으로 collect/actual phase/XML각1을 따로 확인한다.

작성2는 schema.py/test_schema_catalog.py, root 보조1은 test_management_wire_case_space.py로 소유를 분리한다. 최종 product/test 입력은 정확3으로 명시하고 다른 fixture/module/원oracle를 자동 포함하지 않는다. 원53의 준비 포함60초와 combined402의 실제 wall/누락·중복·source hash를 구분한다. full 신규 기대30547=기준30494+53은 수집 전 산술이며 실제 full PASS가 아니다.

### 변이·순서·한계

우선4 site는 equality→subset/extra, kind 무시/valid kind변경, duplicate guard 제거/중복입력, fixed FP 한 곳 변조/완전spec 비교다. 정상 control 뒤 같은 source hash 사본에서 한 site만 바꾸고 실제 private call/capture 후 목표 assertion FAIL만 검출로 센다. 앞 guard MASKED·setup/import/선택/timeout INVALID를 분리한다. source/span/목표 line을 고정하기 전 kill을 선언하지 않는다.

실제 collector가 공급하지 않은 사실·두 DB를 합친 값은 pure 함수가 알아낼 수 없다. raw sqlite_*를 몰래 제거하거나 engine 미검증을 CURRENT로 올리지 않는다. autoindex/sequence/stat·CPC02/03·CPH-ENGINE-01·public observer/EMPTY/readonly cut/오류 mapping은 후속 OPEN이다. metadata DDL·내부 행 version·actual S1 FP·observed registry 전체·pointer/identity/WAL·owner/ACK·금융/삭제/journal/floor·입장권위는 이 후보로 검증되지 않는다. None은 public INVALID/UNSUPPORTED나 정상 legacy 거부가 아니다.

검증은 고정BASE+정확overlay·TEMP cwd/rootdir/config/PYTHONPATH·부모/실spawn actual function source/hash·새helper call SQL/I-O0·선택/unique/call/XML각1 및 독립 제품 검토를 요구한다. 원S1 회귀는 실제 기존 TEMP fixture(SQLite 파일)를 원함수/기대 그대로 사본에서 사용한다. 초기 memory-only 지시가 이를 차단한 실패와 metadata 직렬화 오류는 원본/새 시도 이름으로 보존하며 성공으로 소급하지 않는다. 사용자/서비스DB·실제 readonly/WAL probe·실음성/모델/유료 호출은 별도다.

X00의 명시 activation은 같은 immutable BASE에서 격리 후보 작성만 선행CI대기 중 병행하도록 했다. 공유 통합/commit/push 전 실제 같은SHA 선행CI3 성공을 확인하며, source/문서/독립결과가 닫힌 정확tree에서 full/coverage7/offline wheel을 직렬 검증한다. 공개 후 새SHA CI3도 별도다. 작성자는 자기 결과를 최종 승인하지 않는다.


## D15: S1 private 읽기 오류 경계와 공개 호환

이 증분은 기존 `component_shape_wire(connection, component)`의 읽기/검증 몸체를 private `_component_shape_wire_read(connection, expected)`로 분리한다. public 서명·docstring·catch 밖 `_expected(component)`와 기존 sqlite3.Error→정확 ValueError('Unsupported component shape')/from None은 보존한다. private는 내부 trusted expected model을 받으며 현재 cleanup을 거쳐 밖에 남은 SQLite 오류를 직접 전파한다. 다른 public API/DTO·inspect_schema·오류 classifier/reason·retry/rollback/connection 소유권을 추가하지 않는다. 새 frame/줄 번호까지 원본과 같다고 주장하지 않는다.

`_read`의 cursor 생성은 try 전이며 실패하면 close 시도0이다. 생성 뒤 row_factory/execute/fetch는 finally close1을 시도한다. close 오류가 앞 오류나 반환을 가리는 원 우선순위를 보존하며 최초 오류 보존/native 자원 회수 성공을 새로 보장하지 않는다. from None은 표시 억제이며 __context__/traceback/비밀 삭제가 아니다. 숨은 context를 정식 classifier API로 쓰거나 raw SQL/path/오류 객체를 출력하는 기능은 없다.

### 유한 손 입력과 primary

다음20은 관리 fixture/formal70·전체4105/명시245와 구분되는 로컬 seam 입력이다. primary는 모두 `tests/unit/test_schema_catalog.py::test_private_schema_read_error_seam[<label>]`이다. 원 S1/golden/관리 wire 입력·단언·private current53을 고치지 않는다.

| label | 발생 경계·독립 손 기대 |
| --- | --- |
| READ_OK | 직접 _read rows 정상 반환·close 정상1 |
| UNKNOWN_COMPONENT | public lookup의 정확 shape 오류·cursor0 |
| MISSING_REQUIRED | 두 번째 schema rows=[] 뒤 shape 오류·close 정상2 |
| CURSOR_ERROR | 첫 cursor 생성의 SQLite E·close0 |
| ROW_FACTORY_ERROR | 첫 setter의 E 뒤 close 정상1 |
| EXECUTE_ERROR | 첫 execute의 E 뒤 close 정상1 |
| FETCH_ERROR | 첫 fetch의 E 뒤 close 정상1 |
| CLOSE_ONLY | 첫 rows 성공 뒤 close C·정상반환0 |
| OTHER_SQLITE_ERROR | OperationalError 외 DatabaseError E도 private identity/public 닫힌 오류 |
| DUAL_SQLITE | execute E 뒤 close C가 생존·C.context E·public closed.context C |
| CLOSE_NONSQLITE | RuntimeError C를 원 identity로 전파 |
| DUAL_CLOSE_NONSQLITE | SQLite E 뒤 RuntimeError C/context E를 전파 |
| NONSQLITE_VALUEERROR | 주입 ValueError E identity 유지·새 shape 오류로 덮지 않음 |
| INTERRUPT | 실제 case call 내부 KeyboardInterrupt E·close 정상1 |
| EXPECTED_OUTSIDE | public actual lookup의 subclass hash E·catch 밖 전파/cursor0 |
| INDEX_READ_ERROR | _index_keys 첫 index_xinfo execute E·close 정상1 |
| TABLE_READ_ERROR | _verify_table 첫 table_xinfo execute E·close 정상1 |
| PRIVATE_WIRE_OK | 정상7read 뒤 private/public wire490·close 정상7 |
| LAST_STAMP_ERROR | 정상6read 뒤 마지막 fetch E·close 정상7·최종 wire0 |
| LAST_STAMP_CHANGED | 마지막 rows7→8·read/close 정상7 뒤 shape 오류·최종 wire0 |

READ_OK·UNKNOWN_COMPONENT·EXPECTED_OUTSIDE·INDEX_READ_ERROR·TABLE_READ_ERROR는 각 단일 caller route다. 나머지15는 private/public 각 route를 새 fake/cursor/expected model·E/C·counter로 실행하므로 caller 관측35다. 같은20 parameter를35 pytest node로 바꾸지 않는다. 별도 `test_private_schema_read_error_seam_literal_audit`1은 손 literal/hash/목록을 감사하며 제품 call0이다. 의미20·node21·caller35와 재관측/변이 control은 서로 다른 수치다.

정상 counterpart는 원 SC06 jobs.checkpoints DDL와 고정 golden306337B/SHA8b3611904a5db6371d2ebef831f7477a9cd8fa2c6b13ad55f0774417911dedbb의 hand model/wire490/FP를 재사용한다. 기대값을 제품 parser/catalog/encoder에서 생성하지 않는다. fake는 stamp7→sqlite_schema table/autoindex→table_xinfo→foreign_key_list→index_list→index_xinfo→stamp7의 고정 SQL/rows를 공급하고 실제 DB를 열지 않는다. fake DDL cell은 원 입력 literal이며 SQLite가 저장한 bytes나 referenced jobs의 실재·whole DB를 인증하지 않는다.

주입 E/C 생성 초기 cause/context None·suppress False와 call 후 chain을 구분한다. E/C는 동일 객체 identity로, 제품이 생성한 SHAPE/PUBLIC_CLOSED는 실제 capture한 exact type/args/str/repr/cause/context/suppress로 검사한다. expected 예외를 미리 만들거나 context를 심지 않는다. 활성 except 밖의 새 route로 context 오염을 막으며 subclass hash/KeyboardInterrupt를 setup/수집에서 실행하지 않는다. 마지막 오류/변화는 실제 read7/cleanup 이후를 확인하고 선행 내부 canonical _wire까지0으로 요구하지 않는다.

### 원402 결속·단일 site·검증 경계

기존 planned349/private53=402와 신규21은 교집합0이고 허용 union은423이다. property 보조는 새 exact21만 유한 allow한다. wildcard/파일 전체 허용·unknown label 수락은 하지 않으며 원 selected==state·unique·skip/xfail/actual call 감사와 fixture349를 유지한다. S1 21은402 안에 이미 포함되므로 다시 더하지 않는다. 예상 전체30568=기존30547+새21은 실제 collect 전 산술이다.

단일 site6은 private SQLite catch 삽입, public handler 제거, public handler Exception 확대, _read close 제거, public expected lookup을 try 안으로 이동, 마지막 stamp 비교 뒤 거부만 생략이다. 실제 source/span·정상 control·목표 assertion을 사본별로 고정하고 import/setup/teardown/timeout INVALID·앞 guard MASKED·생존을 목표 FAIL과 분리한다. public handler 제거를 Error→DatabaseError 축소 전수 검증으로 표현하지 않는다.

M04의 close 제거는 정상7read/full trace에도 영향을 준다. 정상 사본 PRIVATE_WIRE_OK 양 route와 READ_OK PASS를 먼저 보존하고, mutant의 영향 없는 기존 UNKNOWN_COMPONENT control PASS 뒤 READ_OK의 실제 rows 반환/close event 단언 FAIL을 검출한다. mutant PRIVATE_WIRE_OK 단언을 완화해 control PASS를 만들지 않는다. 다른 site의 정상 PRIVATE_WIRE_OK control은 유지한다. 원 계획의 M04 control 모순 정정은 별도 이력으로 보존한다.

작성 source/unit2와 root property1은 별도 소유이며 정확3 입력·원 archive449/비overlay446 raw·부모/실spawn actual source·기존 단언/역 AST를 확인한다. archive raw와 Git-show LF를 혼동한 준비/종료감사 오류를 원본/새 감사 이름으로 보존하며 LF 일치로 비소유 raw 불일치를 숨기지 않는다. 신규21 준비 포함60초·combined423 wall·전체/core 시간을 별도로 측정한다. 선택/unique/phase/XML 각1·route35·신규 fake call 실제 I/O0과 기존 S1의 자기 격리 TEMP 파일DB 회귀를 구분한다.

비작성자 제품 검토·정확 최종7 tree의 단일 full/core·coverage7·offline wheel·copy/wheel 부모/실spawn 함수5 출처와 원 smoke3+seam 정상2, 선행/새 SHA 실제 CI3은 별도 gate다. 계약·허용 node·작성자 보고·정적 검토만으로 PASS를 선언하지 않는다. 실제 SQLite busy/corrupt/permission·원 driver 오류 mapping·raw engine/WAL/readonly cut·whole-file/current·metadata/pointer·owner/ACK/입장/C1/CR·금융/삭제/실장비·전체 G09a/v1은 이 seam으로 닫히지 않는다.
