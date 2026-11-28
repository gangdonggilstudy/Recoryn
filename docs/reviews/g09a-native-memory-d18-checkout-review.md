# G09a-NATIVE-MEMORY-D18-CHECKOUT-R1 독립 검토

검토자 w5:p8 / 한 경로 보정 작성자 X00. **checkout 정책·동결 증거 대조 한정 CLOSED / 새 OPEN0**. source/시험/oracle의 기존 의미나 원 QA 도구를 자기 최종 승인하지 않는다.

## 1. 대상·범위·수행 구분

기준 실제 공개는 `38eb7c47b158940c1deeeb0a0fdfb1950df12b3c`이며, 원인 보정 attr-only tree는 `50d69f454017d8afff18160d2df597071244bc0a`다. 예정 게시 범위는 `.gitattributes`와 이 독립 리뷰 정확2이며 source/test/fixture·H03·다른 문서는 제외한다. 이는 실패한 같은 D18 단위의 CI 보정이고 후속 D19 제품을 공개할 허가가 아니다.

직접 수행한 것은 고정20파일의 raw/LF/bytes·evidence-seal 대조, Git read-only blob/diff/check-attr/ls-tree, stdlib AST/XML/JSON/hash 및 원/보정 checkout455씩의 파일 읽기·바이트 비교다. 작성자 helper·제품을 import/실행하거나 DB/SQL·pytest/수집/변이/full·네트워크·설치·추가 위임을 실행하지 않았다. Git index/object/branch 쓰기0이고 새 쓰기는 이 문서와 지정 inputs.json뿐이다. D19 진행 자료·다른 작업자 폴더는 읽지 않았다.

root가 실행한 checkout/기존 native4 결과와 본인의 저장 증거 대조를 구분한다. 원 로컬 LF full30846 PASS는 root failure-intake의 역사적 참조 e9b4beb4…로만 유지하며 본인이 전체 결과를 재승인/재실행하지 않았다.

## 2. 실제 원격 실패의 근거

고정 `run.json`/`job.json`/`fetch.json`은 main/push/core.yml, run46137122734, commit38eb7c47, job140954786120/core(3.13)의 **completed/failure**에 결속된다. 원 로그104,837B/raw `c3bf7c077e3aac1f8bd19a3f5569bfb0808ecc0581b9cf5ab4d5649e68750925`와 fetch·intake hash가 일치한다.

- `core313-full.log:929`: **4 failed, 30842 passed in 2141.96s**.
- :745/771/797/823: 모두 `tests/unit/test_schema_catalog.py:5578` raw length assertion.
- :921/923/925/927: 기존 native4 각 시험이 `186320 == 181424`에서 실패한다.

공개/checkout unit의 `_native_memory_fixture`:5572~5617 중 raw 길이 gate는5578이며 canonical hash도 그대로다. `_native_memory_call`의 fixture loader 호출5720은 첫 `sqlite3.connect`5846보다 앞이다. **해당4시험의 연결 전 gate 실패는 원 로그+이 source 순서의 도출**이다. 원격 native method/connection을 직접 계측한 것이 아니고 원격 전체 시험에서 DB연결0이라고 주장하지 않는다.

원격 fixture 파일 자체를 내려받아 SHA를 잰 것은 아니다. 로그의 실제 길이/보이는 CRLF 표현과 Git blob을 CRLF로 확장한 값, 아래 실제 Windows checkout의 동일 결과를 결합해 원인을 확인한다. 원격 CRLF SHA c3e37c8c…는 이 도출/로컬 재현값이지 원격 파일 직접 측정값이 아니다. 원 로컬 LF full PASS와 실제 원격4FAIL을 서로 덮지 않는다.

## 3. 후보 한 줄과 Git blob 보존

Git tree diff를 직접 읽어 **`.gitattributes` 한 파일·한 삽입**만 확인했다. 후보는 원 attr 전체 340B 뒤에 다음 한 줄을 붙인 406B이며 build 후보 raw와 attr-tree blob이 같다.

```gitattributes
tests/fixtures/g09_inventory_native_memory_literals_v1.json -text
```

후보 raw SHA는 `158ec746fbed67c3dca01c429e14e2632146e8cf65105ba7e264293ffeefad1e`다. 기존 upstream license·Qt·CT2의 -text와 golden `g09_schema_v1.json`/management fixture -text 규칙은 원 prefix 그대로다. JSON 전체 wildcard, 전역 autocrlf/eol 설정, 제품/시험·손 expected·hash/길이 assertion은 변경0이다.

Git `check-attr --source`의 native fixture text는 old38eb에서 **unspecified**, attr-only tree에서 **unset**이었다. source/schema.py·기존 unit·native/golden/management fixture의 old/fixed **Git blob raw 전체가 동일**함도 직접 읽어 확인했다. sourceec/unit9732/fixturea728의 의미를 새로 승인한 것이 아니라 checkout 보정으로 이 bytes가 바뀌지 않는지만 확인했다.

## 4. 실제 Windows checkout455 두 개의 직접 대조

동결 helper를 실행하지 않고 AST/문자열로 읽었다. root는 공유 index 대신 old/fixed 별도 index, 각 tree의 GIT_ATTR_SOURCE, `core.autocrlf=true`/`core.eol=crlf`/`core.safecrlf=false`/빈 core.attributesfile로 실제 checkout-index를 만들었다. 원과 attr-only tree는 각각455개다.

그455개 경로를 Git ls-tree와 proof map에 결속하고 **각 checkout의 실제 파일을 읽어** 길이/raw SHA가 저장 map과 같은지 확인했다. 두 실제 bytes를 경로별로 비교한 차이는 `.gitattributes`와 native fixture 정확2이며, **다른453개는 raw 바이트 전체 동일**하다. 기존 canonical golden/management fixture도 두 조건에서 원 raw를 보존한다.

| native fixture | bytes | raw SHA256 | LF hash |
| --- | ---: | --- | --- |
| old checkout | 186,320 | c3e37c8c26fb5795513291b67c65bd681bd627040859516e6b12b651ef76e35f | a7285387… |
| fixed checkout / Git blob | 181,424 | a7285387178335c6ada4f0159e612149c32711efee74d55359f53e2898a2bbef | 동일 |

old의 CRLF4,896개를 LF로 바꾸면 fixed/Git blob의 **전체 bytes와 정확히 같다**. 새 expected나 fixture 수선이 아니다. source/test의 checkout은 두 조건 모두 CRLF 표현이며 raw가 각각 f7ccba1b…/2406b089…로 동일하고 LF hash는 원 ec384a2a…/9732ba45…다. 이 raw/LF 차이를 source blob 변화라고 쓰지 않는다.

root checkout-proof의 공유 index before/after는 모두 `fbc128b2544a062d4dcc6b2e4ee5dd027925bce40bb6e973ce7aa318daaa3a53`다. helper의 명시 private index·시작/끝 index 및 cached diff 확인을 읽었고 private index 원파일 hash도 seal과 같다. 이는 root 실행 시점의 보존 증거이며 본인의 현재 index/refs 전체 상태를 새로 인증한 것은 아니다. 본인은 read-only Git 명령만 사용했다.

## 5. 기존4 시험의 저장 XML·5관측 대조

root의 동일4 node만 선택한 old/fixed 실행은 로컬 Python3.13.1/SQLite3.45.3이며 full 재실행0이다. 각 cwd는 해당 checkout이고 PYTHONPATH는 그 src/root를 먼저 둔다. 새 테스트나 손 oracle를 작성·수정한 것이 아니다.

| 동결 XML | 실제 testcase/각1 | failure/error/skip | 저장 native 기록 |
| --- | ---: | --- | ---: |
| old-native4.xml | 4 | 4/0/0 — 모두 raw186320/181424·5578 gate | 0 |
| fixed-native4.xml | 4 | 0/0/0 | 5 |

XML raw는 old `09eaae612858448f3227d627c8a2475a2ea8a35b51e66aca26ea5f35d8c405a1`, fixed `12037a8bb0742526349ce7de0ffe82c118e31ebd065d4881b895f75155be65db`이며 seal/results와 일치한다. 네 testcase 이름과 각1/중복0을 직접 확인했다.

fixed XML의 원 property JSON5를 읽어 **모든 key/value가 results.json의 actual_existing_observations와 전체 동일**함을 확인했다. 순서는 empty-direct, empty-forward, empty-row2, r08-positive, r08-text33이며 각 source_file 실제값은 `D:\project\Recoryn\build\g09a-native-memory-d18-checkout-repair\fixed-checkout\src\recoryn\schema.py`와 같다. 그 사본 source raw/LF hash도 직접 대조했다. loader와 원 assertion을 보정하지 않고 기존 fixture/원 source 경로로 돌아왔다는 한정 증거다.

저장값은 완료5/native connection각1·D16/matcher합3/3이며 caller/connection·원함수/연결 factory 복원 flag true, forbidden I/O 목록은 비어 있다. direct는 helper-return row3/text95·계약도출 fetch7/close4와 native telemetry UNOBSERVED를 유지한다. forwarding4의 원 비용/음성 LIMIT·3251/3260·R08 identity11도 저장값 그대로다. 이를 원 시험의 의미나 모든 native 경로·원격 method의 독립 재승인으로 확대하지 않는다.

## 6. 한정 판정·남은 gate

**새 OPEN0**이다. 원 CI의 canonical raw gate 실패는 실제 checkout EOL 변환으로 재현됐고, 기존 canonical fixture와 같은 한 경로 -text 정책이 Git blob·source/test/oracle를 바꾸지 않은 채 그 원인을 없앤다는 동결 증거가 일치한다.

다음은 여전히 X00의 별도 gate다.

- 위455개는 **attr-only 재현 tree**의 수다. 새 공개 review를 포함한 최종 exact2 tree는 별도로 고정·검증해야 한다. 공유 H03나 D19 자료를 끼우지 않는다.
- root가 실제 선행 green6622 CI3와 failed38eb의 최종 job 상태를 게시 직전에 다시 확인한다. 원38eb CI3를 성공이라고 쓰지 않는다.
- 최종 exact2·전체 메시지/trailer0·일반 push/ref·**새SHA CI3**는 미검증이다. 이4개 로컬 PASS는 새 remote CI나 실3.11 성공이 아니다. frozen old run의 다른 job 상태를 현재 최종 상태로 확대하지 않았다.
- 이 same-unit 실패 보정은 다른 의존 기능/DB/모델 관측을 활성화하거나 public 검사·CURRENT/EMPTY/owner/ACK·실장비 권위를 승인하지 않는다.

원 CI 실패·원 LF local full PASS·초기/원 로그는 그대로 보존한다. 본인 source/QA/test/oracle의 기존 의미 자기승인0이다. 공개 리뷰와 지정 입력2를 끝 hash로 동결하고 root의 exact2 통합·새CI 검증을 기다린다.
