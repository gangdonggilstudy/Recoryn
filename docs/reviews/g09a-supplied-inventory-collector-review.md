# G09a-COLLECTOR-D17-PRODUCT-R1 독립 제품 검토

판정: **검토한 private collector 경계의 새 OPEN 0**. 비작성자 pA가 고정 prep8과 정확3의 combined697을 각각 한 번 실행했다. 제품·원시험·손 oracle 수정은 없다. 최종 tree·전체 CI·공개 승인은 X00 별도이며, 본 보고는 제품 전체나 실제 파일 권위를 승인하지 않는다.

## 1. 기준과 원자료 보존

기준은 공개 `5af8482f9e4725f385b530bd64e43eda67178fbd`, tree `0fbc24662a6f2196d06d8a94b1012d11a60a96fb`다. 고정 archive451 manifest `1240efc84d186b5c0acec79688fe781504de9612ebd1a52213beb91136862b24`와 tar를 확인하여 새 TEMP `recoryn-d17-review-r1-3yg6xoiw/tree`에 구성했다. 공유 작업 트리나 다른 dirty 제품은 사용하지 않았다. 정확3은 다음과 같으며 raw/LF가 각각 같다.

| 경로 | SHA256 |
| --- | --- |
| src/recoryn/schema.py | ec384a2a7e91e4d9b510ff4f7df66e897dab442b3db967cc7dc483a931a14563 |
| tests/unit/test_schema_catalog.py | 8829ee5d0511a291b0c956b20dc6c27ada159f6a48c538eb3c99e14287a85105 |
| tests/property/test_management_wire_case_space.py | 8beacd0e1999be6d36c47be38dbf033d56d63c61c871a478b1c3856494fc28b6 |

source/unit의 BASE LF prefix와 원 AST 200/85개는 불변이다. archive CRLF raw와 Git/LF를 혼동하지 않았다. 나머지 archive448은 raw byte 동일하다. 작성자 delivery `5e5f18e4…876631`의 원306, 기존 prep plan `e3aeaf93…a80868`/inputs `9c4812a2…c7e4e1`은 시작·종료 및 후단 감사에서 불변이다. 모든 쓰기는 신규 run-r1과 자기 TEMP에 한정했다.

계약은 D17 FIX2 `0ac4903f…`, prep의 비작성자 closed-binding `d643f967…`, empty 독립 literal `2de82d5d…`/binding `0b543177…`, root companion combined 허가 `cadd1ad1…`에 결속했다. 과거 PREP-OPEN1·원109의 OPEN4·손자료 순서 정정과 R1 OPEN 이력은 지우지 않는다. 이들의 종결 근거와 이번 실제 제품 관측을 구분한다.

## 2. 정적 검토와 실제 관측

검토 source의 행 번호는 정확 source ec384a2a 기준이다. `schema.py:3194`는 exact budget 및 정수 범위를 cursor 생성 전에 검증한다. `:3223`의 cursor 생성은 try 밖이고 생성된 cursor의 close는 `:3263` finally다. 읽기/cleanup 예외를 broad catch로 접지 않으므로 생성 전 E에는 close0, 읽기 E와 close F가 겹치면 실제 F 객체가 밖으로 나온다. 원 S1 읽기 seam·공개 오류 변환·D16 및 matcher의 AST는 BASE prefix로 보존된다.

`schema.py:3228`의 description shape/meta → `:3237` Unicode → `:3238` 고정 이름 → `:3240` 비용 순서가 FIX1과 일치한다. `:3245`는 남은 row+1/최대128의 실제 fetch 요청을 사용하고, `:3250`은 초과 슬롯을 tuple/cell 해석 전에 거부한다. caller connection/TX/factory/handler 설정을 변경하거나 연결을 닫는 문장은 없다. 자기 cursor factory=None/close만 사용한다. `:3284`부터 고정 query로 수집하고 raw table/index 이름만 정렬하며 응답 행·셀·중복을 D16에 보존한다. `:3342` 끝 stamp 확인 뒤 `:3345`에서 실제 D16에 전달한다.

독립 시험은 원 prep의 완전 program/patch/손 기대를 그대로 읽는다. 제품 parser·enum·반환값으로 expected를 만들지 않는다. 제품 함수/반환/raise를 대체하지 않고 실제 code object/globals 및 trace의 call/인자/return을 관측했다. 정상 결과5는 별도 empty 손 literal과 비교하고 실제 project/collector의 반환 identity를 함께 검사했다. 예외 E/F는 fresh 객체를 공급하여 실제 전파 identity를 검사했다.

| 원 prep 입력 | 손 oracle와 실제 관측 | 결과 |
| --- | --- | --- |
| shared_empty_equality_control | 실제 project1/matcher1, 인자 `((),())`/`()`, 반환 identity·독립 결과5, cursor4/close4, fetch 요청 `[4,3] [3] [3,2] [2,1]` | PASS |
| meta_before_unicode | meta 불일치가 먼저 CAPABILITY, fetch0/close1/project0 | PASS |
| surrogate_before_fixed | header surrogate가 이름 불일치보다 먼저 INVALID_RESPONSE, fetch0/close1/project0 | PASS |
| fixed_before_header_budget | 적법한 다른 header가 비용보다 먼저 CAPABILITY, fetch0/close1/project0 | PASS |
| protocol_typeerror_not_budget | cursor()의 실제 E_protocol TypeError identity, 열린 cursor0/close0/project0 | PASS |
| fetch_E_then_close_F | 실제 E_read 뒤 F_close 순서, 반환 예외는 F identity, close 시도1/성공0/project0 | PASS |
| row_after_remaining_zero | 끝 요청1의 초과 row에서 LIMIT, close4/project0, 손 fetch vector 보존 | PASS |
| changed_final_stamp | 끝 stamp 변화에서 SCHEMA_CHANGED, close4/project0/matcher0 | PASS |

8개 모두 실제 collector 진입·입력 불변·금지 I/O trap0을 확인했다. caller 속성의 object identity와 connection close/commit/rollback/handler 변경0, 자기 cursor factory/close 횟수를 각 행에서 검사한다. 원 protocol 예외 전파도 정상 시험의 통과 결과이며, 실제 pytest FAIL로 오인하지 않는다.

## 3. 선택·실행·출처 감사

| 실행 | collect/unique/XML | setup/call/teardown | 시간 |
| --- | --- | --- | --- |
| 독립 prep8 | 8/8/8 | 24개 전부 PASS | 실행 0.686초, 준비 포함 2.427초 |
| combined697 | 697/697/697 | 2091개 전부 PASS | 실행 5.665초 |

두 실행은 각각 collection1/실행1이며 skip·xfail·error·실제 FAIL은0이다. 원 명시 selector와 실제 collection, 실행 collection, XML의 qa_nodeid 집합을 대조했다. combined는 schema_catalog409 + management_wire_api285 + property3 =697이고, 승인 selector577 + CINV119/감사1=120의 합집합과 같다. 독립8은 별도 모듈이며 기존 property 분모에 추가하지 않았다. `expected697.json`, 각 `collection.json`/`reports.jsonl`/XML 및 `evidence-audit.json`에 근거가 있다.

준비 포함 시간은 runner 시작부터 원306/입력 확인, TEMP 복사·해시·출처, 실제 parent/spawn, collect와 독립8 실행/XML 감사까지다. 계획/시험 코드 작성은 실행 예산 밖이다. 독립8의 목표15초/상한60초를 충족한다. 전체 유한 runner는 13.174초이며 이 값을 독립8 예산과 섞지 않는다.

부모 PID36220/실제 spawn PID47808은 서로 다르고 모두 자기 TEMP의 schema ec384a2a를 import했다. 5개 관측 함수의 code filename/globals/unwrap identity를 확인했다. 실제 독립 pytest PID16508과 combined PID26836도 같은 source다. cwd/rootdir는 사본 tree, config는 그 pyproject.toml, PYTHONPATH는 사본 src와 소유 support다. independent 모듈은 root 밖 소유 support에 있어 nodeid가 `::test_independent_d17[...]`로 기록되며 정확8 집합으로 따로 감사했다.

`-B`, UTF8, `-p no:cacheprovider`, 고유 TEMP basetemp, `-W error::ResourceWarning`, offscreen/offline 환경을 사용했다. Ruff check/format은 같은 사본의 정확3, mypy는 같은 source에서 모두 exit0이다. cache는 TEMP다. 기존 S1 파일 SQLite 회귀는 사본의 원 pytest TEMP fixture만 사용했으며, 독립 collector는 protocol double만 사용했다.

## 4. 변이·오류 이력과 남은 gate

독립 변이 실행은 **0**이다. `mutation-proposals.json`의 IR-M01/02는 각각 한 span의 정역 hash·control·실제 call 도달 target·목표 assertion을 계산한 제안2건이다. 원 source 파일을 바꾸거나 mutant를 실행하지 않았다. M01은 끝 stamp 차이 검사를 무력화하여 changed_final_stamp의 `REVIEW_REAL_PROJECT_CALLS`를 겨냥하고 정상 empty를 control로 한다. M02는 bounded fetch를128로 바꾸어 정상 empty의 `REVIEW_BOUNDED_FETCH_REQUESTS`를 겨냥하고 cursor 생성 전 protocol 예외를 control로 한다. 별도 X00 exact 채택 전 실행하지 않는다. 실제 call 목표 assertion FAIL만 kill이며 선택 오류·error·timeout·미도달은 INVALID/MASKED로 분리해야 한다. 작성자 mutation10의 실제 판정을 이번 독립 kill 수로 계산하지 않았다.

후단 감사 첫 스크립트가 작성자 delivery의 `raw_sha256`를 `raw_SHA256`로 읽어 KeyError1이 났다. `audit_evidence-attempt1.py`와 `post-audit-attempt1-error.json`을 보존하고 key 한 곳만 교정하여 stdlib 증거 감사만 다시 수행했다. 봉인 helper도 보고서의 특정 한국어 단어가 5회를 넘어야 한다는 임의 조건 때문에 AssertionError1이 났다(실제4회·UTF8 정상). 원 helper와 오류를 `seal_review-attempt1.py`/`seal-attempt1-error.json`에 보존하고 UTF8/BOM/대체문자 검사와 한국어 존재 확인으로 교정했다. 제품 import/시험 실행0인 후단 helper 오류2건은 제품 FAIL이나 mutant INVALID가 아니다. 최초 실행·XML·oracle·선택은 전혀 바꾸거나 재실행하지 않았다. 보조 읽기에서 없는 `pytest-config.json`을 요청한 경로 오기는 실제 `configuration.json` 읽기로 해결했으며 원 실행 증거에 영향0이다.

새 제품 OPEN0이며 소스 수정 요청은 없다. full/coverage7/wheel/실3.11/CI는 실행0이다. 실제 snapshot/file cut·WAL/SHM 무쓰기·arbitrary virtual module 효과·native 취소/메모리 강제한도·공개 오류 mapping·registry/pointer·CURRENT/EMPTY·운영 owner/ACK·실서비스는 미검증이다. 동일 stamp나 정상 공급 변환을 그 권위 증명으로 확대하지 않는다. X00의 정확 tree/최종 검증·독립 변이 채택 및 통합 판단을 기다리며 제출물을 동결한다.

## 후속: X00 채택 IR-M01/02 독립 민감도 검증

이 절 앞은 원 R1 report.md의 raw9535 bytes 정확prefix다. 원 R1의 판정·원8/697·예산·후단 오류2와 당시 ‘독립 변이 실행0’ 기록은 그 시점의 이력으로 유지한다. 다음은 별도 명시 활성화 뒤 `build/g09a-collector-d17-independent-mutation2/`에서 추가한 결과이며 원 보고서를 덮지 않는다.

정확 source ec384a2a/unit8829ee5d/root8beacd0e와 BASE5af8482/tree0fbc2466의 site별 새 TEMP에서 지정2 node 정상 PASS를 먼저 확인했다. 각 사본에 승인 한 span만 적용한 뒤 mutant control PASS/target 실제 assertion FAIL을 확인했다. 원 reviewer 시험/손 기대 byte는 동일하다.

| 채택 변이 | 실제 control | 실제 target | 관측·목표 |
| --- | --- | --- | --- |
| IR-M01, source :3343의 끝 stamp 검사 무력화 | shared_empty_equality_control PASS | changed_final_stamp call FAIL | 실제 project1/matcher1·Projection 정상 반환, 손 project0 위반을 REVIEW_REAL_PROJECT_CALLS(:214)가 검출 |
| IR-M02, source :3245의 bounded fetch →128 | protocol_typeerror_not_budget PASS | shared_empty_equality_control call FAIL | 실제 fetch7의 요청 모두128, 손 request vector 위반을 REVIEW_BOUNDED_FETCH_REQUESTS(:228)가 검출 |

mutant 전체 SHA는 각각 `5fc2c23726bbf35fb68757b84a6ec94ba82b5ba06ca745c35e68bdfc696e0a71`, `2f8cb5c95145a6ee8841dbaef2216e6fc1e429f24f3e50eacabfa46e5a0c1517`이고 한 span 역복원 SHA는 원 ec384a2a 전체와 같다. 정상4 PASS·변이 control2 PASS·지정 target2 AssertionError FAIL이다. 각 실행 collection2/XML2/phase6을 확인했으며 setup/teardown error·skip·xfail0, INVALID0·새 MASKED0이다. target 실제 본문/return identity·product exception0·입력불변·strict I/O0, 정상/변이 각각 부모/실spawn·pytest import 출처·globals/unwrap이 확인됐다. 유한 runner는 준비 포함9.700703초다.

원 R1 60+self·준비2·작성자306·변이279 및 비소유448 raw는 불변이다. 원8/697/full/coverage/wheel/실3.11/CI 전수는 반복하지 않았다. 두 site는 작성자10의 stamp/fetch 축과 중첩한 독립 검증이며 formal ID/분모·고유 물리지점 수를 늘리지 않는다.

**CM05는 여전히 MASKED1이다.** 작성자 positive-counterpart cleanup 검출과 원 R1의 정상 F_close identity PASS가 있어도, CM05 E/F mutant body 미도달을 이번2가 닫지 않는다. 실제 E/F mutation kill을 주장하지 않는다. 이번 선택 범위의 새 제품 OPEN0이며 원 source 수정 요청0이다. 자세한 call/XML/profile/hash는 새 report/final/delivery에 있으며 정확 tree/full/원격/최종 승인은 X00 별도 gate다.

## 후속: trace 호환성 실패·좌표 대응·FIX2 독립 종결

이 절 앞은 원 공식 후보 e88fb7bf의 **전체 raw12269 bytes 정확prefix**다. 원 R1/독립2·당시 unit/선정·오류·시간·한계는 각 시점의 기록으로 유지한다. 다음은 X00 별도 활성화 뒤 새unitda9d3b71044a836e4f0f74e674a24da56fbfc982a8025d0b6399a976578d3c8a의 정확 observer 경계를 비작성자 pA가 재확인한 결과다.

원 unit8829는 기존 CTracer가 active인 full flags와 충돌하는 None-only 단언이 있었다. 원 제품/pytest 실행 전 metadata 지적과 작성자의 원 CINV001 coverage 재현을 구분한다. 작성자 초기 selected85% 거부·중간119 계측 실패/cleanup timeout 및 중간 통과도 원806에 그대로 있다. pA의 raw38 직접비교 감사 실패는 원 CINV001 test PASS 뒤 source AST 위치와 coverage statement 좌표를 동일시한 별도 measurement binding OPEN이었다. root가 고정 parser.py의 multiline 정규화와3195/3196/3197→3195를 명시했고, saved A 재실행0으로 원38·canonical36/원3branch를 대조하여 그 결속만 닫았다. 원 실패/OPEN은 지우지 않았다.

원 unit38e의 실제 CINV116에서는 두 helper가 H→K 각1회 뒤 초기 H로 돌아가 재호출236/176회·return H를 보였고, 원 제품/손 단언 완료 뒤 최신 local 복원 관측에서 call FAIL이 났다. 이는 trigger 미도달/INVALID가 아닌 실제 active-frame callback 불일치였다. 원26/self와 정확 source/unit/log/XML/profile은 그대로다. FIX2는 not-relaying pop 이전 initial에 등록된 frame의 최신 continuation을 복원용 기록에도 보존하는 한 span이다. 단일 span 역복원으로 원38e 전체 raw/AST, 모든 Assert AST·다른 정의/oracle 보존을 확인했다. sourceec와 root8be는 변하지 않았다.

FIX2 작성자의 최초 regression runner는 manual plugin에 coverage를 켜 priorNone 사전조건에서 막힌 INVALID1이다. 그 실행은 원 본문/H cut 미도달이며 원 R2의 실제 callback FAIL과 구분한다. 이후 작성자392/self·120/697cov/정적3·source10 변이의9목표/CM05 MASKED1·동결 plugin CINV116 PASS는 root433cbcb9가 인수한 작성자 증거로 남긴다. 이를 pA 독립 실행 수로 세지 않았다.

새 정확3(sourceec/unitda9/root8be)에서 원 plugin SHA1e70d730의 bytes/관측단언을 바꾸지 않고 기존 두 node를 각각 한 번 실행했다. CINV001cov는 실제 CTracer와 canonical36·원3branch·budget3195 정상복귀, 두 helper의 global identity/map0·원 결과5/호출/입력·I/O0을 확인해 PASS했다. 준비 포함6.872805초다. 원38 raw좌표와 mapped2는 별도 보존되며 budget-valid4는 A에서 직접 저장된 counter가 아니라 관측한 생성2/collector2와 고정 source 관계의 도출 기대다. raise3199/rowtext3260 미도달은 유지한다.

CINV116nocov는 같은 control/target·G→A→B·H→K cut으로 PASS했다. 각 helper는 실제 :5226 설치 cut에서 transfer1, H 재호출0, return K/global G·map0을 보였다. source11 named non-generator frame과 직접 budget_valid4·CAPABILITY 같은객체·예외 뒤 close3264/return·원 손 기대/I-O0도 유지됐다. 준비 포함1.634567초다. 각 node collection/unique/XML1·phase3 PASS, error/skip/xfail·새runner INVALID0이다. 실제 parent/spawn·pytest import/code/globals/unwrap·사본 cwd/rootdir/config/PYTHONPATH·정확3/비소유448 raw와 원봉인 불변을 확인했다.

이로써 **선택한 D17TR-01 coverage/local 복원 경계는 독립 CLOSED·새OPEN0**이다. source 원 R1/독립2는 같은 source와 외부코드 조건의 과거 증거이지 새unit 재실행이 아니다. source mutation의 CM05 E/F mutant body 미도달 MASKED1은 이 종결로 닫지 않으며 실제 E/F mutation kill을 주장하지 않는다. source3260의 새 native-driver 도달도 이번에 검증하지 않았다.

종결은 실제 CTracer 및 명시 G/A/B/H→K의 두 node에 한정한다. 임의 tracer/local None/generator/coroutine/thread·모든 frame 지원이나 제품 전체·native/파일/WAL/snapshot/owner/ACK·운영 입장 권위는 승인하지 않는다. 한정 coverage에85% floor를 적용하지 않았고 full30842의85%·coverage7·wheel·실3.11·새CI는 X00의 정확 새tree 후속 gate다. source/기대/분모·공유/Git 수정·697/120/변이 전수 재실행0, 자기최종승인0으로 새 공식후보를 제공한다.
