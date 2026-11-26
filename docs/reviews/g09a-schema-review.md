# G09a-S1-R1 — SQL 구조 기술자 독립 검토 및 FIX1 재확인

**REVIEW_READY / FIX1 RECHECKED / OPEN 0(S0·S1·S2·S3 각0).** 검토 w5:p8 Codex, 작성 pA·fixture/계약 X00. 기준은 `5dda55348d0eada1ac2f3fd031f781dd1a67d831`다. 최초 제출본의 독립 반례에서 S2 세 원인·네 행을 발견했고, 최신 FIX1에서 같은 probe bytes와 손 oracle로 해결을 직접 확인했다. 작성자의 자체 검증이나 X00의 인수 결과만으로 종결하지 않았다.

검토자는 초기 G09 계약·범위 제안 작성 이력이 있으나 **이번 schema.py·제출 시험·FIX1 제품 변경 및 새 손 wire를 작성하지 않았다**. 이 검토는 S1 두 API와 새 diff의 독립 검토이며, 기존 전체 G09 설계나 자신의 과거 문서의 최종 승인으로 계산하지 않는다. 제품·제출 시험·fixture·공용 case·배정표·Git 쓰기0, agent/pane·실제 장치/모델/서비스/음성·네트워크·설치·유료/vault 호출·승인 UI 대리 입력0이다. 저장소 쓰기는 이 리뷰와 `build/g09a-schema1-review/` 증거뿐이다.

## 1. 규칙 재인수·정확 입력

현재 AGENTS/onboarding, workflow·quality-system·case-space·push-units, assignments H02/H03 및 G09a-S1/R1, H02 인수 권한, 공용 case의 S1/FIX1 확정절과 `build/g09a-prep/x00-schema1-assignment.md`를 확인했다. X00만 공유 Git·배정표·공용 계약을 통합/commit/push한다. 승인된 caller-owned SQLite의 static SQL 기술 범위를 file inspector·실제 입장/권한·migration 지원으로 확대하지 않는다.

| overlay | 최초 R1 LF SHA-256 | FIX1 LF SHA-256 |
| --- | --- | --- |
| src/recoryn/schema.py | 5002fbe5526ab45edeb479bbacf1b1092d160a737933a912e79b90ced6bec14e | 7339edda533f22366482e027d8b4bae7db3388517339b5c2f59676db9d3bc71e |
| tests/unit/test_schema_catalog.py | 718ccd8f3118064cb30540a411a39c02da1e904eeb79f300c811ed274132eb92 | 01691ec0b04e5d03ccac0f500d6be3b95bbc1a58641c9d4f16d455c34f4f1904 |
| tests/fixtures/g09_schema_v1.json | 8b3611904a5db6371d2ebef831f7477a9cd8fa2c6b13ad55f0774417911dedbb | 동일,306337B |
| docs/testing/g09-migration-backup-cases.md | 7f4e1348023b3cd4fba4994ea4432fc3de2db1326c94ba83d6056bf7fa89bfab | 515572aa6d3fa95427b16c71d37b591fa943ca0d0ba4eef1a42d93ef86dd408c |

각 단계에서 공개 BASE archive+동결4만의 다른 고유 TEMP를 만들었다. 다른 dirty를 섞거나 원본 R1 증거에 FIX1을 덮지 않았다. 이하 **R:줄**은 최초 schema.py, **F:줄**은 FIX1 schema.py, **T:줄**은 FIX1 제출 시험이다. 공용 case는 원 S1 :599~656·FIX1 :659~722다.

- 최초 TEMP: `C:/Users/gangd/AppData/Local/Temp/recoryn-g09s1-review-om0lkiys/tree`
- FIX1 TEMP: `C:/Users/gangd/AppData/Local/Temp/recoryn-g09s1-r1-fix1-l_wym8st/tree`
- 읽기 쉬운 독립 증거: `build/g09a-schema1-review/r1-090da472fa/`

모든 실행은 기존 `D:/project/Recoryn/.venv/Scripts/python.exe`를 사용했다. 각 사본의 cwd/rootdir/pyproject 및 PYTHONPATH=사본 src, 고유 basetemp·no:cacheprovider·ResourceWarning error·offscreen·offline flags를 고정했다. 원/후 부모와 **실제 multiprocessing spawn** 자식의 recoryn/schema 경로가 해당 사본 src인지 직접 확인했다. 시스템 도구 불일치의 과거 로그를 이번 제품 실패/정적 PASS로 전용하지 않는다. Git status의 전역 ignore 읽기 권한 경고는 읽기 인프라 경고였고 범위를 넓히거나 승인 UI를 조작하지 않았다.

## 2. API·무쓰기·독립 oracle 확인

| 확인 관점 | 근거·직접 확인 범위 |
| --- | --- |
| public API·의존 | F:475~480의 expected_shape_wire 및 F:565~621의 component_shape_wire만 public top-level 함수다. stdlib import만 있고 다른 Recoryn 제품·fixture/build를 import/read하지 않는다. inspector/facade·관리 JSON·권한 stub 없음 |
| catalog의 독립성 | 제품 catalog는 고정 SQL을 파싱해 wire를 만든다. 제출 시험은 별도 hand golden bytes/FP와 비교하며 제품 parser/catalog를 expected 생성기로 호출하지 않는다. 정규 JSON/SHA는 프로토콜 연산이며 제품 helper 재사용이 아님 |
| caller-owned 연결 | F:483~489는 새 cursor만 만들고 닫는다. connection을 열거나 닫지 않는다. 독립 probe는 활성 caller transaction, sqlite3.Row row_factory, 읽기 전용 연결에서 동일한 wire와 연결/transaction 보존을 확인 |
| 실제 쓰기0 | 제출 시험의 authorizer/trace는 DDL/DML·transaction/savepoint·ATTACH/DETACH·허용 밖 PRAGMA를 감시한다. 독립 checked wrapper는 같은 종류 감시와 파일 bytes·total_changes·in_transaction·row_factory 불변, API 구간 sqlite3.connect/builtins.open/os.open 금지도 확인. setup SQL 쓰기는 API 호출 전에 분리 |
| unknown 요청 | component 미등재·주입 형태의 이름, bool/future version은 ValueError. 해당 독립 행은 API 동안 authorizer/trace 질의0도 단언 |
| component 경계 | 무관 table은 projection을 바꾸지 않음. 선택 component의 extra index/trigger, 필수 table 자리에 view, 필수 객체 부재는 거부. 다른 component 존재 허용을 전체 DB profile 인증으로 설명하지 않음 |
| 의미 보존 | 독립 CASCADE FK, Unicode trigger literal, 알려진 ASCII 인용/대소문자, 추가 괄호·산술·문자열 DEFAULT, STRICT의 INTEGER rowid alias 대조. custom collation/generated 문법은 명시 거부하고 BINARY/지원형으로 추정하지 않음 |

독립 probe의 DDL은 제출 시험의 **source-backed literal 입력**을 별도로 고정한 것으로, 제품의 SQL 생성기/기술 함수를 사용하지 않는다. expected는 읽기 전용 golden의 hand wire 또는 미리 정한 field/token 변경만으로 고정했다. 원20 probe/DDL bytes는 FIX1에서도 그대로 재사용했고 새 helper가 oracle를 계산하지 않았다. unknown/거부 행도 feasible 분모에 남겼다.

## 3. 최초 R1 발견 이력 — S2 세 건·네 실패 행

최초 정상 제출17은 통과했다. 독립20 중16 PASS·R16/17/18/19의4 call FAIL, XML error/skip0이었다. 원 시험의 실패를 지우거나 범위를 바꿔 통과시키지 않았다. 다음 세 항목은 제품 변경 전에 X00에게 보고됐고 **FIX1에서 RECHECKED**로 닫는다.

### G09S1R-01 — S2 / RECHECKED — PRAGMA collation 철자 정규화 누락

- 원 근거: R:496~503·533~540. parser는 collation을 NOCASE로 정규화하지만 실제 index_xinfo의 `row[4]`는 그대로 비교했다.
- 입력/독립 oracle: R16의 `result_ref TEXT NOT NULL COLLATE nocase`는 기존 negative FP04의490B/`eeef915f…`와 같아야 한다. R17의 `UNIQUE(job_id,result_ref COLLATE nocase)`는 column BINARY를 유지하고 unique의 두 번째 key만 NOCASE인 별도 hand490B다.
- 원 실제 결과: 둘 다 API의 ValueError `Unsupported component shape`; 지원 SQL 반환/정확 wire의 명시 목표에서 call FAIL. 실제 writer/connection 쓰기나 전송 오류가 아님.
- FIX1: F:496~499·514~523은 known BINARY/NOCASE/RTRIM만 uppercase로 대응한다. 원 wire를 BINARY로 바꾸거나 custom collation을 허용하지 않는다. 같은 R16/R17와 정식 FP05/06이 통과했고, uppercase 반환만 제거한 독립 M20은 FP05의 목표 assertion에서 실패했다.

### G09S1R-02 — S2 / RECHECKED — DEFAULT 괄호의 SQL/PRAGMA 관측 차이

- 원 근거: R:303~310·513~518. raw SQL의 DEFAULT `(1)` 토큰과 SQLite table_xinfo가 바깥 괄호를 생략한 기본값 문자열을 바로 비교했다.
- 입력/독립 oracle: content.summary_requests의 DEFAULT 1만 DEFAULT (1)로 변경. wire에는 `[[p,(],[n,1],[p,)]]`를 그대로 보존하며 별도 hand532B와 같아야 한다. 상수 접기나 단순 DEFAULT1과 동일 fingerprint로 만들면 안 된다.
- 원 실제 결과: 정상 SQL 생성 후 API ValueError, R18의 지원 SQL 반환 목표 call FAIL.
- FIX1: F:502~511·526~562는 **관측 비교용으로만** 바깥 한 겹을 대응시킨다. serialized wire 토큰은 유지한다. 원 R18/정식 FP07이 통과했고 중첩 `((1))`, 산술 `(1+1)`, 문자열 `('Keep')`의 독립 손 token 대조도 통과했다. 대응만 제거한 M21은 FP07의 명시 assertion에서 실패했다.

### G09S1R-03 — S2 / RECHECKED — STRICT의 암묵 PK NOT NULL과 선언의 혼동

- 원 근거: R:512~520. WITHOUT ROWID의 암묵 NN은 반영했지만 STRICT의 indexed TEXT PK가 SQLite 메타데이터에서 강제하는 NN을 반영하지 않았다.
- 입력/독립 oracle: jobs.receipts table 끝에 STRICT만 추가. wire는 strict=true이고 원 explicit_notnull=false·PK/autoindex는 그대로인 hand429B여야 한다.
- 원 실제 결과: SQL은 생성됐지만 API가 R19에서 ValueError로 거부했다.
- FIX1: F:530~539는 WITHOUT ROWID 또는 STRICT indexed PK의 관측 NN을 반영하며, wire의 명시 NN을 바꾸지 않는다. 원 R19/정식 FP08이 통과했다. 별도 g09.management STRICT 대조에서 explicit TEXT PK와 INTEGER rowid alias도 구분했다. STRICT implicit-NN 부분만 제거한 M22는 FP08의 명시 assertion에서 실패했다.

FIX1 AST 비교에서 변경된 기존 제품 함수는 **_index_keys·_verify_table 둘**, 새 private helper는 **_pragma_collation·_pragma_default 둘**뿐이다. 기존 public API/class/helper 및 catalog literal은 바뀌지 않았다. 이 세 거부의 해결이 lifecycle/권한 지원을 추가했다는 뜻은 아니다.

## 4. 입력 분모·실제 선택·손 oracle 감사

| 집합 | 유한 입력과 oracle | 직접 결과 |
| --- | --- | --- |
| 원 제출 SC12+FP4·감사1 | 공개된 literal20가 아닌 당시16 semantic. hand golden bytes/FP와 실제 SQL 기술·쓰기0 |17 PASS, pytest1.16초·command2.480초 |
| 원 독립20 | 요청 이름/버전5, 객체 경계5, 연결 소유3, literal/철자2, 의미 메타데이터5 |16 PASS/4 call FAIL, errors/skips0, command2.514초 |
| FIX1 정식 SC12+FP8·감사1 | 원16 ID/순서 유지 + FP05~08. ignored build에 의존하지 않는 새 hand wire 리터럴 |21 PASS, pytest0.64초·command1.088초 |
| FIX1 원 독립20 | 원 probe·DDL bytes와 expected 불변 |20 PASS, pytest0.38초·command0.805초 |
| FIX1 추가 경계6 | 중첩DEFAULT·산술·STRICT/rowid alias·custom collation 거부·문자열DEFAULT·generated 거부 |6 PASS, pytest0.27초·command0.711초 |

FIX1 XML의 정식20 ID를 **별도 손 목록 SC01~12·FP01~08**와 대조했다. 각1·누락/추가/중복0·순서 동일, 감사1을 semantic에 가산하지 않았다. 원16·추가4·보조20·보조6·변이3의 node/목적을 합쳐 새로운 제품 분모로 보고하지 않는다. 전체 a/b/CA 선택 수는 계약 이력이며 S1의 실행 건수가 아니다.

원 독립20의 명명 입력은 evidence의 plan/probe에 고정했다. R01/02/03/04/20은 요청 검증, R05~09는 projection/객체 경계, R10/16/17/18/19는 FK·메타데이터, R11~13은 caller 소유, R14/15는 Unicode/ASCII lexical다. 상태를 제품 parser로 다시 계산해 oracle를 맞추지 않았다.

독립 실행에서 실제쓰기0·caller ownership 단언은 정상과 기대 ValueError 경로 모두 수행했다. 이는 관측한 합성 TEMP 연결의 증거다. 모든 SQLite 구성·실 사용자 DB·임의 확장/OS 소유/시점의 부작용까지 증명했다고 하지 않는다. caller가 연 source의 정지 cut/동시성·WAL 소유는 S1 API가 발급하지 않는다.

## 5. 단일 변이 검토와 직접 재적용

원19의 manifest/patch·XML·call 감사와 FIX1 작성자 final/report를 읽었다. 19개의 서로 다른 실제 source 치환 위치에서 정상 대상 뒤 한 결함씩 적용했다. object 누락/추가·column/PK/UNIQUE 순서·NN/default/FK/CHECK·literal/trigger 순서·AUTOINCREMENT·partial NOT·collation·rowid/strict·WHEN·index unique·FK action의 의도와 목표는 맞는다.

단 **원19 중18개는 expected_shape_wire의 catalog wire 비교**, M14만 실제 component_shape_wire의 NOCASE 의미 손실 비교에서 검출됐다는 한계를 유지한다. 원19 검출을 실제 PRAGMA 메타데이터 guard 전체의 검출력으로 확대하지 않는다. 이 빈 곳에서 원 R16~19가 드러났다. FIX1은 해당 actual 경계의 신규3 site를 추가했다.

이번 독립 실행은 원19를 반복하지 않고 **정상 FIX1 21 PASS 후** 아래 새3만 각 별도 정확 BASE+4 사본에서 재적용했다. 각 사본은 schema.py 한 치환만 달라지고 시험/fixture/case는 고정이다. 부모/실제 spawn 경로도 사본 src임을 확인했다.

| 직접 변이 | 정식 target | mutant source LF SHA-256 | 실제 결과 |
| --- | --- | --- | --- |
| M20-collation | FP05 | b17b2005d006d1e21800f6527b6a5c8d1e1d76a173e730956589d3bce76e7172 | 명시 supported SQL acceptance assertion call FAIL1 |
| M21-default | FP07 | b8c7961cd370e58dbf74e17bedd4107f8a8c96c5981b84b5cf7d868b0a61d133 | 같은 목표 call FAIL1 |
| M22-strict | FP08 | 1b25da23b5380f091f51a486d87b4c7e0acaa7dc3d218454ed53c8499b703611 | 같은 목표 call FAIL1 |

**직접3/3 목표 검출, INVALID0·생존0.** 각 XML testcase1/failure1/error0/skip0이며 ValueError 자체를 uncaught error로 세지 않았다. 정식 시험 T:200 전후의 실제 API 한 호출을 ValueError로 포착한 다음 `supported named SQL must be accepted by the actual descriptor`라는 명시 assertion이 실패했다. collation 두 위치를 같은 site 두 kill로 중복 계산하지 않았다.

작성자 FIX1의 원19+새3=22 검출·관련5파일464 PASS·정적 PASS는 제출 증거로 대조했으며 **이번 직접22/464/정적 실행 결과로 재사용하지 않는다**. X00의 별도 `build/g09a-schema1-fix1-review-x00/results.json`에서도 원20 PASS·세 되돌림의 같은 목표 실패가 기록돼 있음을 확인했다. 이것은 p8 실행과 구분한다.

## 6. 증거·해시·미검증

주 증거 폴더는 `build/g09a-schema1-review/r1-090da472fa/`다. 원/후 plan, command/cwd/wall 결과 JSON, XML·로그·부모/spawn origin, 원 probe/DDL 및 추가6, 변이3의 before/after·목표·실행 JSON을 보존했다.

| 증거 | LF SHA-256 |
| --- | --- |
| summary.json | 405c84f47f55e08d7bb04545793049369078d5a57bf9e29c7dab10f46db4c0e1 |
| test_s1_review_probe.py(원/후 동일) | 35da83b3bd3249c76e8566e368bbf12d1fc8eda9e1ef69ecb68eb5dbb83ead45 |
| normal17.xml | 7b3384ee10c3dd998c6b701f9078f426eaf41ba3073b329ddeea844c19e1b5e7 |
| independent20.xml(원4실패 보존) | caa927c02272f622e54f38b343ec634af5115ff6a8510c6e64f3cf4ea58ca8c3 |
| fix1-normal21.xml | 071b1f01ed3f44dff6812498b635cc086bd461132c3fb8e577561a30fd9ddf35 |
| fix1-independent20.xml | ea2c17b020bb2f4ce6e818c79c3715c5c61c418b26e5affcdff9635007ac7d6d |
| fix1-controls6.xml | eb0f1e23fbe786938fc4a52c74b7b943d5b47c0a6bc92dea9f08f9115cd9ded1 |
| fix1-independent-mutation-results.json | dd86c538645f09a8cc0e1578c6814731bb690e2b0fcaae971247d0d83965316b |
| origins.json(R1) | 50a0036d3fd95fa935e8beff8b87a814a41176043991fabfeb2c57f1f4f50648 |
| fix1-origins.json | eec03714d7d32d66ef6473678ad5328390e4937d0e0c062fe5cb802cd0df662a |

probe는 Windows CRLF를 포함한 원 raw SHA `354bbe81dc78a94086e2aebad4e12859d2fc2e329278ccd2bb2a00f1a79919b5`도 원/후 동일하다. FIX1 준비 plan의 old_probe_lf 필드가 raw SHA로 계산된 이름 오류는 원 기록을 보존하고 summary.probe_identity에서 raw/LF를 명시해 바로잡았다. 제품·oracle bytes의 변경/불일치가 아니다.

대조한 외부 작성 증거의 LF는 pA `report.md=f3b958749117468b3e2a443d5edc46f2c4e19f5b469e69c3977859ba81736615`, `final.json=313d32b9b40ef04c16593f4c3c155cfe1f7f00be4db9a43197f98875684dc570`, X00 results `2058373b8bda8905123bd57527a77cc006d071014bd0ce0c4dc1792f94b32f0b`다. 작성자의 준비 경로/메타데이터 감사 도구 오류는 제품 call·변이 검출과 별도 기록돼 있고, 이번 p8 수행에는 해당 오류를 재사용하지 않았다.

**미검증:** 전체 core/coverage85·7묶음/offline wheel·새 전체 정적 검사·원19 변이 반복은 p8이 실행하지 않았다. X00의 정확 FIX1 전체 게이트가 진행 중이라는 지시에 따라 중복0이며 완료로 선언하지 않는다. 실제 inspector의 source 무쓰기·WAL/OS 소유·maintenance phase·복원/권한/금융·실장비·전원 장애·원격CI는 S1의 기술 API 통과로 인증되지 않는다.

판정은 이번 FIX1의 static SQL 두 API 범위에서 **RECHECKED 3 / OPEN 0**이다. 최종 통합·독립 증거 인수·전체/원격 게이트·commit/push는 X00가 수행한다. 보고 후 배정 밖 쓰기 없이 대기한다.
