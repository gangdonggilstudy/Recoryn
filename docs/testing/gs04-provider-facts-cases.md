# GS-P04 제공업체 사실·템플릿·관리 설치 UI 계약안

상태: **GS04 CONTRACT_DRAFT r2 — 리드 수정 3건 반영, C00 결정·독립 검토 전, 구현·시험 실행 없음**. 작성자 w5:p9 Codex, 작업 리드 w5:p7, 통합·Git 작성자 C00. 이 문서는 구현 배정이나 실제 제공업체 인증이 아니다. 현재 쓰기는 이 신규 문서 하나다.

## 1. 기준과 현재 근거

제품·시험의 기준은 **6156b65(G-P17a)**다. 아래 `경로:줄`은 모두 `git show 6156b65:<경로>`로 읽은 위치다. 작업 트리의 capture·storage·app/desktop 변경과 G-P12b 4파일은 이 기준의 구현으로 계산하지 않았다.

예외 입력은 작업 트리에만 있는 [s3-bundle-plan.md](../implementation/s3-bundle-plan.md)의 P04 행(:61), 중복 제외(:69), 공유 파일(:78~80), 승인 요청(:88)이다. 읽은 LF SHA256은 `028490188016735a12c253c4f56c454348772cb540b4830f153673cfa4f8239f`. 이 계획의 b925520 인용 줄을 제품 근거로 전용하지 않고 아래에서 다시 대조했다.

| 항목 | 6156b65에서 읽은 근거 | 이미 있는 것 / 남은 것 |
| --- | --- | --- |
| G01BR-11, S2 기능 | `docs/architecture-v1.md:194~201`; `docs/reviews/g01-gap-ai-security-ui-review.md:64`; `src/recoryn/providers/contracts.py:130~138,371~382` | frozen `ProviderCapabilities`, 정적 `capabilities()`, `actual_service_status="NOT_RUN"`가 있다. 명명된 describe/probe 프로토콜·제공업체 증거 수준·시각/목적지 수명은 없다. providers/transcription/summarization에서 `def probe\|DECLARED\|OBSERVED`의 고정 commit 검색은 0건이다. **PARTIAL, 기능 S2 유효**. 리뷰의 판정 정정 S3와 기능 구현을 구분한다. |
| 정적 지원 범위 | `src/recoryn/transcription/adapters.py:128~131,310~321,423~424`; `src/recoryn/summarization/adapters.py:87~104,333~346` | STT는 Faster-Whisper/OpenAI/Gemini, 요약은 Ollama/OpenAI/Anthropic/Gemini다. Anthropic STT 등 없는 조합을 probe 성공으로 지원 승격하지 않는다. OpenAI timestamp 기본값은 false이며 모델별 별도 조건이 있다. |
| G01BR-13, 템플릿 | 리뷰 `:66`; `src/recoryn/summarization/adapters.py:25~31`; `src/recoryn/providers/contracts.py:329~353`; `tests/unit/test_providers.py:243~259,294~310,598~607` | 다섯 템플릿과 요청 검증이 있다. 요약 wire와 checkpoint 변경 시험도 있다. 독립 literal 기대 집합과 다섯 템플릿 전체의 wire 대응은 없다. |
| 템플릿 리뷰의 시점 보정 | `tests/integration/test_selection_version_cas.py:586~608,654~680`; `tests/unit/test_content.py:76` | 현재는 lecture·key_points를 쓰는 회귀도 있다. 과거의 “meeting/tasks만 사용”은 현재 전체 tests의 사실로 반복하지 않는다. 이것들은 집합의 정확성이나 네 adapter의 다섯 prompt 대응을 assert하지 않는다. **구현 있음, 집합 oracle 공백 S3 유효**. |
| G01BR-13, 관리 다운로드 UI | 리뷰 `:66`; `src/recoryn/ui/models.py:215~232,561~582,594~612`; `tests/ui/test_models_ui.py:32~87,91~118,121~163,166~252` | manifest preview, 별도 `approval`, 새 manifest의 승인 초기화, 승인 없는 download 거부가 있다. 해당 UI 시험의 네 함수는 Ollama helper용이다. G13은 아래 별도 대조처럼 실행 전 확인이다. **사용자 흐름 단언 공백 S3 유효**. 유효 A 뒤 형식 오류 B를 고르면 plan=None·approval=false지만 A preview가 남는다(:567~573). download는 거부되지만 현재 계획 표시가 정직하지 않은 M9 공백도 있으며, 실패 분기 수정은 C00 결정 G 대상이다. |
| 관리 설치의 하위 방어 | `src/recoryn/models/manager.py:159~164`; `tests/unit/test_models.py:32~40,43~56,59~78,115~122` | 승인 없을 때 downloader 금지·root 미생성, 파일 검증, 취소/이어받기, 변경 계획 거부 시험이 이미 있다. 이 하위 방어를 새 UI 행으로 재작성하지 않는다. |
| G01BR-16(d), 서버 신뢰 안내 | 리뷰 `:74`; `docs/architecture-v1.md:219~221`; `src/recoryn/ui/privacy.py:86~123,517~543,682~729`; `src/recoryn/models/ollama.py:30,63~65,165,199` | loopback/모델/owned proof에 대한 실제 차단은 있다. PrivacyPanel의 endpoint 선택 화면에 사용자 서버의 신뢰 범위·후속 전송 안내는 없다. **MISSING S3 유효**. (a)~(c)와 G01BR-17 비밀 수명 개선은 이 항목의 완료로 합산하지 않는다. |
| 동의·전송 경계 | `docs/implementation/product-contracts.md:103~113,142~150`; `src/recoryn/security/consent.py:35~38,80~135,346~363,651~677`; `src/recoryn/ui/privacy.py:118~123,571~592` | capability는 stt/summary/diarization만 허용한다. data_type은 identifier이고 기존 UI는 audio/transcript/context다. `provider_metadata`를 기존 grant에 포함된 것으로 간주할 수 없다. |
| probe에 필요한 추가 경계 | `src/recoryn/providers/contracts.py:174~186`; `src/recoryn/security/transport.py:25~28,78~98`; `src/recoryn/security/gateway.py:217~268,295~307`; `src/recoryn/security/cost_catalog.py:6`; `src/recoryn/security/cost.py:96~119` | 현재 HTTP는 POST 고정이다. SendPermit에는 method가 없고, 클라우드는 ledger/예약을 요구하며 가격 catalog는 비어 있다. 모델 목록 조회를 POST 추론·예약 면제로 끼워 넣을 수 없다. GET 경계와 원격 비용 정책은 승인 대상이다. |
| G16과 별개의 축 | `docs/testing/g16-device-policy-cases.md:29~41`; `src/recoryn/models/resources.py:95~99`; `src/recoryn/models/gpu_inventory.py:97~132,206~246` | AUTO는 G16 계약의 표시 별칭이고 자원 OBSERVED는 GPU/RAM 관측이다. 제공업체 응답 관측·실제 처리 위치나 모델 품질의 증거가 아니다. |

### 1.1 G-P13과의 행별 중복 대조

G13 문서의 최초 “계약 대기” 문장을 현재 구현 상태로 오인하지 않는다. `docs/testing/g13-manual-model-cases.md:66~90,114~158,166~175`와 다음 **실제 시험의 단언**을 읽었다. 아래 “재사용”은 기존 node/ID의 회귀 대상으로 지정한다는 뜻이며 이번에 실행했다는 뜻은 아니다.

| 닫힌 단언 / 경계 | 실제 node·ID와 6156b65 위치 | GS04 처리 |
| --- | --- | --- |
| 확인 화면의 bytes/key에 대한 Yes만 기록, 새 실행/restore의 옛 승인 차단 | `tests/ui/test_manual_model_ui.py::test_a_confirmation_records_only_the_shown_bytes_after_an_explicit_yes`의 `G13-C-001…144` (`:219~300`) | 전부 재사용. 이 C family의 Whisper source는 manual, 화자는 user_pin(`:234`)이다. 이를 관리 **다운로드** 승인 시험으로 계산하지 않는다. No/Esc 축도 fake modal 답변이며 실제 Esc 키 시험이라고 확대하지 않는다(`:261~277`). |
| 관리 설치 source의 실행 전 preview, 별도 확인란과 확인 기록의 구분 | 같은 파일 `test_keys_and_polls_show_one_honest_model_state`의 `G13-U-002,005,008,011,014,017` (`:303~315,348~429`) | UNCONFIRMED/Whisper/managed의 Tab·Enter·Space·Esc·poll·late 여섯 행이다. source/digest·“출처 인증 안 됨” 표시, checkbox만으로 기록하지 않음, 늦은 답변 차단을 재사용한다. 새 M은 `approval/preview/download`를 대상으로 하며 `confirm_ack/confirm_preview/confirm_model`의 이 단언을 복제하지 않는다. |
| 이미 확인된 관리 모델 재표시·변조 거부 | `G13-U-074,077,080,083,086,089` 및 `G13-U-110,113,116,119,122,125` (같은 축과 단언) | MANAGED_PIN_MATCH와 CHANGED_INVALID의 Whisper/managed 행을 재사용. P04로 모델 신뢰 등급이나 license 판정을 새로 만들지 않는다. |
| 설치 폴더 이름의 형제 prefix가 managed로 승격되지 않음 | 같은 파일 `test_t10_a_sibling_with_the_managed_root_as_prefix_is_not_managed`, `G13-T-10` (`:432~442`) | 재사용. 서버 metadata나 probe 관측으로 MANAGED_PIN_MATCH를 만들 수 없다. |
| installed.json과 모델 동시 변경, 외부 pin 없음, terms 변경 거부 | `tests/unit/test_manual_models.py::test_t11_consistent_installed_change_still_mismatches_the_pin` `G13-T-11` (`:657~673`), `test_t12_no_reference_no_self_approval` `G13-T-12` (`:676~682`), `test_t15_terms_change_alone_needs_a_new_confirmation` `G13-T-15` (`:713~726`) | 재사용. 새 preview fixture가 기존 installed.json을 자기 인증시키지 않는다. |
| 실제 설치 상태 재검사와 오래된 실행 증명 거부 | 같은 파일 `test_a_managed_install_judged_invalid_now_never_runs_on_its_old_confirmation` `G13-X-09` (`:1087~1102`), `test_a_deleted_installed_json_stops_a_queued_job` `G13-X-10` (`:1105~1111`) | 재사용. provider OBSERVED가 이 거부를 우회하지 않는다. |
| 확인 registry의 메모리 수명·기록 조건 | `src/recoryn/models/artifacts.py:289~355`; `tests/property/test_manual_model_case_space.py::test_a_confirmation_lives_only_in_its_run_generation` (`:161~193`) | 모델 실행 확인은 원래 registry가 권위다. provider 관측 cache와 저장소·타입을 합치지 않는다. |
| G13 자체 ID 분모 | `tests/property/test_manual_model_case_space.py::test_the_twelve_family_denominator_is_exact` (`:25~84`) | 기존 1,660행의 ID 감사는 G13 소유다. X 보강 행과 GS04 신규 분모를 이 숫자에 더하거나 같은 ID로 다시 생성하지 않는다. |
| 관리 설치 승인 거부·취소/이어받기 | `tests/unit/test_models.py::test_no_install_without_explicit_approval`, `::test_cancel_resume_exact_prefix_and_no_activation` (`:32~40,59~78`) | manager 직접 호출에 대한 단언은 재사용. 새 M은 실제 ModelPanel에서 해당 경계로 전달되는 UI 의도만 확인한다. |

따라서 관리 **다운로드**의 manifest 선택→계획 표시→별도 download approval→거부/취소/허용에는 새 M이 필요하다. 실행 전 G13 preview/확인을 새로 구현할 필요는 없다. ADR17 수동 Whisper 예외(`docs/architecture-v1.md:288`)는 공급망 검증 완료가 아니며, 관리 설치 UI 시험·제공업체 사실 시험과 각각 따로 집계한다.

## 2. 결정안

### 2.1 describe와 probe의 권위

1. 기존 `capabilities()`와 STTProvider/SummaryProvider의 실행 API는 보존한다. 별도 `ProviderFacts` facade의 `describe(provider_id, kind)`가 정적 선언을 감싸며 **구성·호출·import만으로 I/O가 없다**. 기존 static capability를 없었다고 처리하지 않는다. 다섯 provider descriptor는 미지원 kind에도 DECLARED(false)를 명시하며, 아예 descriptor가 없는 대상의 UNKNOWN과 구분한다.
2. 신규 enum **ProviderEvidenceLevel**은 DECLARED/OBSERVED/UNKNOWN이다. 제공업체용 frozen DTO와 메모리 cache에만 쓴다. 값(value: true/false/unknown), 사실 종류(fact_id), 증거 수준은 다른 필드다. `DECLARED`는 adapter가 선언한 기능이고, `OBSERVED`는 **이 앱이 표시된 목적지·모델·시점에서 해당 응답을 관측했다**는 좁은 뜻이다. `UNKNOWN`은 유효한 관측 없음이며 “미지원 확정”이 아니다.
3. probe는 명시 버튼으로 요청한 **메타데이터 조회 한 번**이다. 녹음·전사·요약의 숨은 선행 호출, 주기적 poll, 앱 시작, endpoint 입력, 목록 열기, describe에서 실행하지 않는다. 생성 요청·음성/전사 전송·모델 load/download·설치·결제·GPU 조사·native import는 하지 않는다.
4. v1 관측 fact는 `metadata_response_received=true`와 `selected_model_listed=true/false`뿐이다. 정상이고 완전한 목록에서만 false를 낸다. 불완전/형식 불명 응답은 UNKNOWN이다. 모델 목록에 없다고 STT/요약 불가를 단정하지 않는다. static의 transcription/summarization/timestamps/formats를 HTTP 성공으로 OBSERVED로 승격하지 않는다. 처리 위치·GPU·다운스트림 무전송·가격·모델 품질·게시자/계정 인증을 관측 fact로 만들지 않는다.
5. fake probe의 정상 응답은 제품의 이 결정/표시 동작만 검증한다. `actual_service_status`는 **NOT_RUN 유지**다. 실제 서비스·계정 검증은 별도 외부 게이트이며, fake/loopback 결과를 이 상태의 성공으로 바꾸지 않는다.

### 2.2 허가·데이터 종류·Gateway 제안

| 요청/응답 요소 | 전송 데이터 분류와 동의 | v1 제한 |
| --- | --- | --- |
| 목적지 host/port/path, DNS·연결·조회 발생 사실 | `provider_metadata`라는 **신규 data_type**의 명시 동의에 포함 | exact 전체 metadata endpoint를 별도 표시·승인한다. 추론 endpoint와 origin이 같다는 이유로 경로 승인을 상속하지 않는다. DNS도 동의 전 0회다. |
| 모델 목록 조회 | 같은 `provider_metadata`, capability는 선택한 기존 **stt 또는 summary** | 새로운 capability 문자열 `probe`를 몰래 도입하지 않는다. operation을 바꾸면 별도 동의다. v1은 고정 GET, body `b""`, query 없음이다. 모델 ID는 로컬에서 목록과 비교하며 송신하지 않는다. 모델 ID를 path/query/body에 보내는 후속 방식은 새 계약 대상이다. |
| Authorization/x-api-key/x-goog-api-key 등 해당 route에 필요한 최소 header | 같은 metadata 동의 화면에서 “인증 정보가 이 목적지로 전송됨”을 별도 열로 고지 | 동의가 키 읽기/저장을 만들지 않는다. 정확한 probe endpoint용 Credential Manager 항목만 요청 직전에 읽는다. 추론 endpoint의 키를 자동 복사하지 않는다. 가짜 vault로만 시험한다. |
| 받은 모델 목록·오류 body | 응답 데이터, 송신 동의를 다른 제공업체/후속 요청으로 확대하지 않음 | 원본 응답은 bounded parser에서만 사용한다. 선택한 모델의 포함 여부·안전한 고정 code만 DTO에 남기고 전체 계정 모델 목록/원시 오류를 cache·UI·DB·로그에 남기지 않는다. |
| audio/transcript/context·중간 요약·session 내용 | 각 기존 별도 동의의 대상이며 **probe에는 포함하지 않음** | 기존 이 세 grant만으로 metadata 조회를 허용하지 않고 metadata grant도 추론을 허용하지 않는다. |

권고 binding은 `(provider, normalized exact metadata endpoint, capability, provider_metadata, session scope/session_id, session_generation, policy_version, grant_id/epoch)`다. v1 probe UI는 선택한 세션 범위만 지원하며 library scope를 자동 채택하지 않는다. 세션 미선택·다른 세션/종류/옛 epoch·library-only grant·철회에는 UNKNOWN과 설명을 보이며 vault read/DNS/open/write **각각 0회**다. 사용자가 “허용”한 뒤에도 별도 “관측 요청” 동작이 필요하다. 허용/취소/단순 preview 자체는 전송하지 않는다.

`ConsentStore`의 기존 generic data_type와 `capture_bindings`/`SendPermit`를 사용한다. probe용 immutable plan은 추가로 provider·metadata endpoint·추론 endpoint/model·adapter/API/route revision·method=GET·body digest·credential revision·UI 요청 세대·응답 한도를 고정한다. metadata는 빈 body이므로 **모델/route revision은 기존 body digest만으로 보호되지 않는다**. 별도 plan token과 worker dispatch_guard가 매 경계에 같은 plan인지 검사한다. 내부 실행 permission은 기존 SendPermit가, 표시 관측의 identity는 새 plan이 담당한다.

현재 public POST API를 임의 `method=` API로 일반화하지 않는 안을 권고한다. **가칭 `Gateway.probe_metadata`와 `MetadataTransport.open_metadata`를 additive하게 분리**하고 fixed GET/empty body/metadata type을 강제한다. 기존 `Gateway.request`는 `provider_metadata`를 거부한다. 따라서 같은 permit의 method는 data_type→GET이라는 닫힌 대응으로 묶이며 POST 추론·다른 data_type으로 재생할 수 없다. GET 미지원 transport에서는 직접 HTTP fallback 없이 UNKNOWN이다. 이 변경은 C00/B14 소유 경계 승인 전 구현하지 않는다.

동의 검증→plan/비용 정책→요청 직전 최소 credential resolve→기존 coordinator/owner guard 아래 open→첫 header handoff/각 write→최종 응답 승인 순서를 보존한다. 철회가 open/write보다 앞선 순서는 새 전송 0회다. 이미 header가 handoff된 뒤의 철회/취소에서는 보낸 bytes 회수를 주장하지 않고 남은 전송·재시도 0, 관측 UNKNOWN으로 둔다. GET의 body 길이가 0이어도 header 전송 경계를 건너뛰지 않는다. redirect/proxy/암묵 retry는 금지한다. 환경 proxy도 사용하지 않는다.

**원격 정책:** 현재 catalog/예약 계약에 metadata 비용이 정의돼 있지 않다. 클라우드/외부 HTTPS probe는 동의가 있어도 `UNKNOWN · 조회 경로·비용 정책 확인 필요`로 **무전송**이다. “모델 목록은 무료”를 가정하거나 ledger를 제거하지 않는다. 외부 metadata 송신을 열려면 route/API 근거·비용 처리·예약 binding을 별도 승인받는다. 이 문서는 cost/ledger 수정 권한을 제안하지 않는다.

**loopback 정책:** owned Ollama에 대해서도 자동 송신하지 않는다. metadata route가 별도 승인되고, 현재의 pinned local/cloud-disabled owner 증명과 같은 origin/모델인 경우만 probe 후보가 된다. 추론 proof의 `/api/chat` exact endpoint 검사를 완화하지 않는다. metadata 전용 guard가 승인된 companion route와 원 proof의 owner/lifetime을 함께 검사한다. 사용자 소유 daemon·cloud hint·만료/불명 proof에는 metadata도 무전송이다. “내가 신뢰함” checkbox나 probe 응답으로 attestation을 만들지 않는다.

현재 저장소 근거만으로 생산용 metadata URL·응답 schema의 최신 유효성을 확정할 수 없다. 초기 production route registry는 **비어 있음**을 권고한다. 시험 전용 descriptor/응답은 주입하되 제품 registry에 섞지 않는다. C00가 정본 route를 승인하기 전 제품 probe는 UNKNOWN/0회이며, fake에서 기능을 닫았다는 이유로 G01BR-11 전체를 완료 처리하지 않는다. 실제 제공업체 호출은 이 계약의 작성·구현 시험 모두에서 금지다.

비밀 값·그 hash·전체 header·vault reference는 ProbeResult/일반 설정/DB/관측 cache/예외/로그에 넣지 않는다. 비교에는 값과 무관한 메모리 credential revision token만 사용한다. 새 probe 경로의 resolver 수명은 P05와 먼저 합의하며 기존 `ExecutionContext`의 비밀 수명 개선까지 완료했다고 하지 않는다. 원문 예외 대신 고정 code를 사용한다. Python/SDK 메모리의 완전 zeroization을 보장하는 계약도 아니다.

### 2.3 전이·관측 수명

정적 선언과 최근 관측을 별도 행으로 표시한다. 하나의 enum 값을 덮어써서 선언과 관측을 서로 소실시키지 않는다. 관측의 key는 provider, exact probe endpoint, 선택한 추론 endpoint/model, capability, adapter/API/route revision, 세션/실행 세대, 동의 epoch, credential revision이다. 모델/목적지 변경 후 옛 key를 다시 선택해도 이전 callback으로 재생하지 않는다.

| 사건 | 정적 선언 | 관측 상태/효과 |
| --- | --- | --- |
| 최초 표시·describe | 알려진 기능 DECLARED, 없는 descriptor는 UNKNOWN | UNKNOWN, 전송 없음 |
| 허가 없는/미지원 경로의 요청 | 유지 | UNKNOWN, vault/DNS/open/write 0 |
| 현재 key의 유효한 완전 응답 | 유지 | 해당 두 fact만 OBSERVED(true/false), 관측 UTC와 monotonic 완료 시각 기록 |
| 실패·취소·불완전/초과 응답·오래된 callback | 유지 | 현재 요청의 관측 UNKNOWN; static 지원을 false로 바꾸지 않음. 다른 최신 요청의 결과는 옛 callback으로 지우지도 않음 |
| 관측 후 경과 `0 ≤ age < 300초` | 유지 | 같은 key에서만 OBSERVED 유지. 읽기/poll은 갱신 요청이 아님 |
| `age = 300초` 또는 그 이상 | 유지 | UNKNOWN, “관측 만료”; 자동 재조회 없음 |
| endpoint/model/adapter/API/route·credential·consent 세대 변경, 새 앱/세션 실행 | 새 descriptor에 맞게 다시 표시 | 즉시 UNKNOWN, 새 요청·필요한 재동의. cache 영속 저장/restore 없음 |
| monotonic 역행·NaN/무한/잘못된 시각 | 유지 | UNKNOWN, 이전 관측을 무기한 연장하지 않음 |
| G16 정책 선택·자원 OBSERVED/UNKNOWN 변경 | **어느 것도 provider 근거로 변환하지 않음** | provider key가 같으면 유효 관측 유지. CPU/GPU 정책·자원 lease·설정 파일도 변경하지 않음 |

권고 TTL은 **300초**, 실제 상태의 300초 보장이 아니라 UI에서 최근 관측으로 보여 주는 상한이다. deadline/epoch와 별개다. fake clock으로 299.999/300/300.001을 확인한다. callback은 immutable 요청 세대/취소 토큰을 대조하고 창 종료·다른 요청 뒤에는 버린다. 동일 key의 진행 중 요청은 하나로 합치며 UI poll/반복 버튼으로 추가 송신하지 않는다. 모델 준비/녹음 제어 lane과 별개의 bounded worker를 사용하고 GUI thread에서는 네트워크·vault를 호출하지 않는다.

리드 결정: **같은 key의 진행 중 반복은 항상 합친다. 최초 요청 이후 새 요청 token은 앞 요청이 사용자 취소·실패·만료로 끝났거나 identity가 바뀐 뒤에만 만든다.** 새 token 생성 가능 상태가 되어도 송신은 다음 명시 요청 때만 한다. 취소로 끝난 요청의 worker 응답이 늦게 와도 새 요청의 cache·UI를 변경하지 못한다.

### 2.4 표시 문구와 로컬 서버 신뢰 안내

| 상태/위치 | 권고 한국어 문구 |
| --- | --- |
| 정적 기능 | `기능 선언: 요약 지원 · adapter 선언, 실제 서비스 미검증` |
| OBSERVED | `최근 관측: 이 앱이 [목적지]에서 [시각]에 모델 목록 응답을 받았습니다 · 인증·실행 보장 아님` |
| 모델 없음 | `최근 목록 관측: 선택한 모델이 목록에 없었습니다 · 기능 미지원 판정 아님` |
| UNKNOWN | `최근 관측 없음 · 별도 전송 허용 후 관측 요청이 필요합니다` |
| 관측 만료/거부 | `관측 만료 · 다시 요청하려면 목적지와 허용 범위를 확인하세요` / `관측하지 않았습니다 · 전송 허용 없음` |
| 지원 route/원격 비용 불명 | `관측하지 않았습니다 · 조회 경로·비용 정책 확인 필요` |
| 사용자 지정 서버 | `이 주소는 연결 대상입니다. loopback 주소만으로 실제 추론 위치나 서버의 후속 전송을 확인할 수 없습니다. 사용자 지정 서버의 설정과 신뢰 범위는 사용자가 확인해야 합니다.` |
| loopback 예외의 한계 | `loopback 예외는 원격 주소·redirect·proxy 전송을 허용하지 않습니다.` |
| Ollama 보충 | `Ollama는 cloud 모델 경로를 사용할 수 있습니다. 목록 응답은 로컬 추론·외부 무전송의 증거가 아닙니다. 로컬 실행 증명이 없으면 추론은 차단됩니다.` |

PrivacyPanel의 provider/endpoint/model 설정 바로 아래, **grant/probe 동작 전에** 표시한다. Ollama 기본값·사용자 지정 v4/v6 loopback·cloud hint·원격 주소 편집에서도 보이게 하며, probe 실패/OBSERVED 여부로 숨기지 않는다. owned 서버에는 “앱 소유 서버 증명과 모델 실행 조건은 별도 확인”을 덧붙이고 모든 서버가 사용자 지정이라고 오표시하지 않는다. 일반 cloud 기본 endpoint에는 로컬 서버 안내를 표시하지 않는다. 원격 주소 입력 거부와 안내의 가시성은 별개다.

읽기 가능한 label/접근성 이름과 Tab 순서를 제공한다. 문구는 선택/변경 시 한 번 안내하고 poll마다 반복하지 않는다. URL/키 열기, 서버 재시작·환경 변경·모델 설치·grant·CPU/GPU 정책 변경은 안내의 부수 효과가 아니다. “서버 인증됨”, “안전 확인”, “로컬 보장” 같은 문구는 사용하지 않는다.

### 2.5 G16·G13과 타입/저장/표시 분리

- ProviderEvidenceLevel/ProviderFactSnapshot는 providers의 새 타입이다. `models.resources`의 문자열 상수·GpuObservation·MemoryObservation을 import/alias하거나 그 인스턴스를 provider 근거로 받지 않는다. 이름이 같아도 schema/constructor를 공유하지 않는다.
- provider cache는 메모리에만 있고 G16의 device-policy.json, 자원 snapshot/lease, G13 ConfirmationRegistry, installed.json에 저장하지 않는다. provider OBSERVED가 GPU_ONLY의 거부나 모델 확인을 풀 수 없다.
- “제공업체 기능 선언/최근 관측”, “이 PC의 실행 정책”, “GPU/RAM 관측”, “모델 출처·실행 확인”은 제목과 상태 라벨을 구분한다. provider 상태를 바꿔도 세 enum 정책·저장 revision·이미 실행 중인 Job·기록된 consent/비용/모델 확인은 불변이다.

## 3. 입력 분할·feasible 분모·family·독립 oracle

아래는 **계약 승인 후 만들 시험의 계획**이며 실제 수집/PASS 수가 아니다. 전체 직교곱을 가장하지 않고 위험이 다른 관계를 9개 family로 나눈다. 유효 대표값뿐 아니라 거부될 입력도 분모에 남긴다. 한 의미 ID의 여러 단언·교차 계층·helper/meta 감사 node는 행을 늘리지 않는다.

### 3.1 축과 분모

| family / ID(끝 포함) | 입력 분할과 순서 | feasible | 손 oracle·주 단언 |
| --- | --- | ---: | --- |
| D / GS04-D-001…090 | provider 5 × kind 2 × 정책 3 × 자원 관측 3 | 90 | literal 지원 표, 정책/자원과 독립, describe I/O0·NOT_RUN 유지 |
| T / GS04-T-001…021 | 독립 템플릿 집합 1 + template 5 × 요약 adapter 4 | 21 | literal 5개 set의 정확한 equality; wire의 실제 instruction 대응 |
| M / GS04-M-001…036 | 아래 UI trace 9 × 관리 모델 kind 2 × 입력 방식 2 | 36 | 실제 preview/approval/download/cancel의 사용자 의도와 fake installer 호출; 오류 선택 뒤 옛 계획 표시 제거 |
| L / GS04-L-001…042 | 서버 설정 profile 7 × 표시 시점 2 × 제공업체 증거 수준 3 | 42 | 고정 안내 문구·가시성·경고/차단 불변; 표시만으로 어떤 전송/허가도 없음 |
| S / GS04-S-001…063 | 관측 전 상태 3 × 아래 사건 21 | 63 | 명시 전이 표·시계 경계·static 유지·메모리 수명 |
| N / GS04-N-001…288 | kind 2 × grant 9 × 목적지/소유 4 × 인증 조건 2 × route 2 | 288 | 허용된 synthetic owned loopback의 정확한 metadata grant만 최대 한 요청; 나머지는 guard에 따라 사전 차단 |
| C / GS04-C-001…033 | plan 치환 필드 11 × dispatch 경계 3 | 33 | 옛 plan/token/permit 재생 차단. 이미 보낸 bytes와 새 전송을 구분 |
| H / GS04-H-001…014 | 명명 UI/worker 이력 7 × 응답 종류 2 | 14 | 응답 역전·취소·close·중복 요청의 현재 결과·부수효과 수 |
| P / GS04-P-001…020 | 비민감 canary 종류 5 × 관찰 표면 4 | 20 | secrets/전체 목록/오류 원문이 결과·표시·로그·영속 영역에 남지 않음 |
| **합계** | **90+21+36+42+63+288+33+14+20** | **607** | 계획 ID 누락·중복·초과 0, skip/xfail로 분모를 줄이지 않음 |

**D:** provider 순서는 faster_whisper/openai/anthropic/gemini/ollama, kind는 stt/summary, 정책은 CPU_ONLY/GPU_ONLY/GPU_WITH_CPU_FALLBACK_ALLOWED, 자원은 UNKNOWN/OBSERVED-empty/OBSERVED-GPU다. static 지원의 손 표는 `{faster_whisper:{stt}, openai:{stt,summary}, anthropic:{summary}, gemini:{stt,summary}, ollama:{summary}}`. 미지원 3쌍도 27행으로 포함한다. OpenAI STT는 기본 timestamps=false config, Faster-Whisper timestamps=true, 그 외 기본 false, STT formats=(wav,), 요약 formats=()를 직접 적는다. 실제 GPU 관측기를 실행하지 않는다. 자원 DTO를 provider DTO 입력으로 넘기면 거부하는 타입 경계도 이 family의 각 해당 row에서 함께 확인한다.

**T:** T-001은 `{"meeting","lecture","key_points","decisions","tasks"}`와 제품 표 key의 정확한 equality다. T-002…021은 위 순서 × Ollama/OpenAI/Anthropic/Gemini 순서다. prompt 기대 문자열도 `adapters.TEMPLATES`를 읽어 expected를 만들지 않고 다음 literal로 쓴다: meeting=`Summarize discussion, explicit decisions, open questions, and actions.`, lecture=`Summarize concepts, explanations, examples, and unresolved questions.`, key_points=`Extract key points and preserve material qualifications and contradictions.`, decisions=`Extract explicit decisions; distinguish proposed, discussed, rejected and decided.`, tasks=`Extract explicit actions; do not invent an owner or due date.` 작은 전사와 각 adapter의 fake Gateway 응답을 주입하고 실제 송신될 wire의 해당 필드를 직접 확인한다. 이는 prompt 라우팅 시험이고 생성 요약의 품질 oracle가 아니다. 기존 잘못된 template DTO 거부 시험은 재사용한다.

**M:** kind 순서는 whisper/diarization, 입력은 mouse/keyboard다. trace 순서는 다음과 같고 ID는 trace가 가장 느리게 변한다.

| trace | 실제 ModelPanel에서 수행할 동작 | 손 oracle |
| --- | --- | --- |
| M1 | 최초 manifest 파일 선택 취소 후 download 시도 | plan 없음, installer0, grant/vault/native0 |
| M2 | 유효 manifest 선택·preview 읽기만 | 표시한 model/kind/license URL/파일 URL/전체 SHA256/총 bytes/저장 위치가 fixture literal과 같음, approval false, installer0 |
| M3 | 승인란 미선택 상태에서 download | 안내 표시, installer0 |
| M4 | 승인란 선택 후 해제하고 download | 선택/해제 자체가 설치가 아니며 installer0 |
| M5 | A를 표시·승인한 뒤 다른 유효 B를 선택하고 새 승인 없이 download | B preview, approval false, A/B installer0. G13 실행 확인은 기록하지 않음 |
| M6 | 승인 후 fake installer를 barrier에서 멈추고 UI 취소 버튼 | 최초 installer1, 같은 Event의 cancel=true, 활성화/성공 신호0. manager 내부의 부분 파일/이어받기 oracle는 기존 시험 재사용 |
| M7 | 현재 계획 표시·별도 승인 후 download | installer1에 **표시한 frozen plan**, approved=true, 해당 작업에 전달된 unset cancel Event; 다른 grant/모델 실행 확인/native0 |
| M8 | 모델 작업이 이미 진행 중인 동안 manifest 교체/download 시도 | 기존 task/plan/cancel 소유 유지, 추가 installer0; 기존 작업 완료/실패 결과를 새 모델의 성공으로 표시하지 않음 |
| M9 | 유효 A 표시·승인 → 형식 오류 B 선택 → download | A를 현재 계획으로 보이는 preview가 없음(비우거나 `계획 없음`), plan=None, approval false, 형식 오류/계획 없음 안내, installer0 |

M9의 ID는 `GS04-M-033…036`이다. `6156b65:src/recoryn/ui/models.py:561~573`은 실패 때 plan을 없애고 승인을 해제하지만 preview를 초기화하지 않으므로 이 oracle를 충족하지 않는다. 이는 소스 대조 결과이며 이번에 시험을 실행한 실패 보고는 아니다. §5·§6 G의 제한된 제품 변경 승인이 필요하다.

fake QFileDialog는 사용자 파일 대신 TEMP의 synthetic manifest만 반환한다. 승인란은 Space, 버튼은 실제 mouse 또는 Space로 누르고 창 활성/초점을 확인한다. slot 직접 호출만으로 UI 입력을 대체하지 않는다. 이 흐름에는 기존 제품의 추가 Yes/No modal이 없으므로 새로운 modal을 계약상 발명하지 않는다. 취소는 파일 선택 취소·승인 해제·진행 중 취소로 명확히 나눈다.

**L:** profile 순서는 owned IPv4 loopback Ollama/custom IPv4 loopback/custom IPv6 loopback/cloud-hint loopback/custom remote HTTPS Ollama/default OpenAI/default Anthropic이다. 시점은 설정 선택 직후/전송 허용 화면 열람 직전, 증거 수준은 UNKNOWN/DECLARED/OBSERVED fake다. 앞5개는 서버 신뢰 범위·Ollama 보충 안내, 뒤2개는 로컬 안내 숨김이 손 표다. 모든 profile에서 증거 수준이 신뢰/실제 위치 권한을 바꾸지 않는다. remote Ollama가 실행 가능한 정상 config라는 가정은 하지 않으며 UI 입력 거부 상태에서도 안내를 확인한다.

**S:** 이전 관측은 UNKNOWN/OBSERVED(true)/OBSERVED(false)다. 사건 순서는 정상 목록에 모델 있음/정상 완전 목록에 없음/transport 실패/응답 schema 오류/age299.999/age300/age300.001/probe endpoint 변경/추론 endpoint 변경/model 변경/adapter revision 변경/API revision 변경/route revision 변경/credential revision 변경/consent epoch 변경/새 앱 실행/취소/미지원 route/응답 byte cap 초과/monotonic 역행/부정확한 시각(NaN 대표)이다. 첫 두 사건만 새 OBSERVED를 만든다. age299.999는 기존 관측이 있을 때 유지하며 UNKNOWN을 승격하지 않는다. 나머지는 UNKNOWN이다. identity 사건은 **해당 필드 하나만** 바꿔 검사한다. 응답은 최대1MiB, 초과는 전체 폐기한다. 사건1/2의 유효 JSON은 공백을 덧붙여 정확히 cap 크기로 만들고, 사건19는 cap+1로 고정한다. 경계 단언을 별도 의미 행으로 부풀리지 않는다. 정적 선언은 모든 사건에서 유지한다.

**N:** kind=stt/summary; grant 순서는 없음/audio만/transcript만/context만/현재 metadata/옛 epoch metadata/다른 capability metadata/다른 session metadata/library-only metadata. 목적지는 검증된 owned loopback/외부 HTTPS·비용 정책 불명/redirect 응답 fixture/소유 증명 없는 loopback, 인증 조건은 불필요/필수인데 plan의 credential reference 없음, route는 fixture 승인 descriptor/descriptor 없음이다. 모델명은 synthetic `fixture-model`이며 STT kind는 이 metadata 동의의 목적 표식이지 Ollama STT 지원을 뜻하지 않는다.

유일한 성공 대표는 현재 metadata grant+owned loopback+인증 불필요+fixture descriptor의 두 kind 행이다. 이 두 행은 유효한 ConsentRequest kind binding의 하위 경계 시험이며, UI에 없는 Ollama STT 선택을 새로 제공하는 시험은 아니다. 각 행에서 metadata open/header handoff1, inference/download0과 정상 모델 목록 fact만 확인한다. redirect profile은 **최초 연결은 승인된 owned fixture와 동일**하고 응답이 다른 origin을 가리키는 입력이다. 이 profile의 나머지 gate가 유효한 두 행은 최초 open/write1, redirect 대상 DNS/open/write0, 결과 UNKNOWN이다. 다른 모든 사전 거부 행은 vault/DNS/open/write0이다. 필수 reference 부재는 비밀 값을 읽지 않고 계획 검증 단계에서 거부하며 외부 HTTPS에는 비용 불명 차단이 먼저 적용된다. reference가 있어도 실제 key가 없는 경우와 key가 있는 fake 경로의 정확한 수신처·비밀 수명은 P에서 검증한다.

N의 사전 gate는 실제 ConsentStore/Gateway와 fake MetadataTransport를 결합한다. 성공/redirect 네 행에서는 동일 ID의 추가 단언으로 실제 DirectTransport의 metadata 경로도 fake socket/HTTP connection에 연결하여 method=GET, 빈 body, 정확한 수신처·header와 환경 proxy 함정의 호출0을 확인한다. 실제 DNS·socket 송신은 만들지 않는다. POST용 기존 proxy 시험을 GET의 직접 증거로 대신하지 않는다.

**C:** provider/metadata endpoint path/추론 endpoint/GET→POST/model/operation kind/data_type/session_id/session_generation/grant-epoch/body bytes의 11치환을 open 전/첫 header handoff 전/응답 수신 후 cache 승인 전에 각각 주입한다. 다른 필드는 그대로 두고 한 필드만 바꾼 replacement plan/권한 상태를 fault fixture로 제시하며 frozen 객체를 in-place 수정하는 정상 API를 만들지 않는다. 모델 등 SendPermit 필드가 아닌 변경도 plan guard가 잡아야 한다. 비교 tuple은 제품 helper로 다시 만들지 않고 fixture의 고정 literal로 대조한다.

경계별 손 oracle는 아래와 같다. 수는 요청 시작부터 거부 처리 완료까지의 **누적 횟수**다. fixture는 DNS 응답 주소 하나·연결 성공 하나로 고정한다. DNS 열은 resolver 호출, open 열은 성공한 연결, header 열은 요청 줄+header의 handoff, body write 열은 **비어 있지 않은 payload의 전송**, 관측 게시는 cache·UI에 새 관측을 적용한 횟수다. 최초 목적지 이외의 DNS/open/header/body와 retry는 모든 행에서 0이다.

| 치환을 주입할 경계 | DNS | open(연결) | header handoff | body write | 관측 게시 |
| --- | ---: | ---: | ---: | ---: | ---: |
| open 전 검증 직전 | 0 | 0 | 0 | 0 | 0 |
| open 성공 뒤, 첫 header handoff 검증 직전 | 1 | 1 | 0 | 0 | 0 |
| 정상 응답 수신 뒤, cache 승인 검증 직전 | 1 | 1 | 1 | 0 | 0 |

이는 `6156b65:src/recoryn/security/transport.py:31~45,53~64,78~88`의 연결/header 분리를 따른다. 제안하는 GET 경로도 **빈 body를 이유로 header 경계를 생략하지 않는다**. 유효 요청은 `write(b"")` 또는 동등한 명시 handoff를 정확히 한 번 통과하며 그 직전에 permit/plan을 재검사한다. 표의 둘째 행은 이 handoff 전에 차단하고 연결을 닫으며, 셋째 행은 이미 handoff된 header 1회를 회수했다고 주장하지 않고 관측 게시만 막는다. 빈 write 호출은 header를 보내기 위한 경계이지 body payload 전송 1회가 아니다.

**H:** 이력 순서는 open 전 취소/header handoff 후 취소/endpoint A→B→A 변경 후 옛 응답/model A→B→A 변경 후 옛 응답/**refresh1 header handoff 후 사용자 취소 → refresh2 명시 요청 → refresh2 응답 → refresh1의 늦은 응답**/창 종료 후 응답/같은 key 진행 중 버튼·poll 반복이다. 응답 축은 유효 fixture/잘못된 JSON이다. 1·2는 취소 이후 신규 송신/자동 retry0, 3·4·6은 옛 UI/cache 변경0, 7은 같은 key의 진행 요청1·poll/반복 버튼의 추가 송신0이다. Event/barrier로 순서를 고정하고 실제 Qt 입력·창 단위 초점을 사용한다.

H5(`GS04-H-009…010`)의 두 행은 **refresh2 응답**의 유효/잘못된 JSON을 나누며 refresh1의 늦은 응답은 항상 유효한 fixture다. refresh1은 사용자 취소로 논리적으로 끝난 뒤에만 같은 key의 refresh2가 새 token을 받는다. refresh1 header1·refresh2 header1은 각각 명시 요청의 결과이며 자동 retry가 아니다. refresh1의 늦은 응답으로 인한 cache·UI 변경은 각각 0이고 refresh2 결과만 남는다. refresh2가 잘못된 응답이면 UNKNOWN을 유지하며 refresh1의 유효한 늦은 응답으로 채우지 않는다. H7(`GS04-H-013…014`)에서는 사용자 취소·실패·만료·identity 변경이 없으므로 새 token/refresh2 자체를 만들지 않는다.

**P:** canary는 fake auth key/선택하지 않은 계정 모델명/원시 오류의 비밀 표식/민감한 redirect URL/응답의 audio·transcript 표식, 표면은 DTO+repr/화면+a11y+고정 오류/캡처 로그/임시 DB·설정·지원 출력이다. 각각 작고 비민감한 synthetic 값이다. 각 행은 허용/미동의/reference만 있고 key 없음의 짧은 trace다. fake vault의 현재 key가 있는 허용 descriptor에서 최소 header만 최초 수신처로 한 번 전달되고, 미동의 경로에서는 vault 읽기0이다. 동의와 reference는 있지만 fake vault가 None을 반환하면 읽기1·DNS/open/write0·UNKNOWN이다. header 문자열을 기대 DTO로 복사하지 않는다. 요청 전용 임시 header 생존 범위 이후 참조가 결과/cache/Task 저장 필드에 남지 않음을 확인하되 OS 메모리 zeroization을 주장하지 않는다. 전체 모델 목록 대신 선택 모델 포함 여부만 남고 모든 surface에 canary가 없는 것이 oracle다.

### 3.2 제외 사유와 ID 감사

- 전역 `provider×kind` 10쌍 중 미지원 3쌍은 D에 포함했다. T는 실제 요약 adapter 4개만 가능하므로 STT 전용 Faster-Whisper 요약 wire는 제외하며 D가 그 거부를 담당한다.
- M은 관리 다운로드 UI의 whisper/diarization 두 kind만 대표한다. 수동 로컬 모델·license/출처 확인·sealed bundle은 G13 재사용이다. manager의 `other` kind와 모든 manifest 문법/다운로드 fault를 M의 새 승인 축으로 복제하지 않는다.
- L은 유효 endpoint/server 조합 7개를 명명했으며 “owned 증명인 원격 서버” 같은 불가능한 양성 조합을 만들지 않는다. 잘못된 remote/local 증명은 N의 거부로 유지한다.
- N의 redirect는 동의 없는 최초 송신을 허용하는 예외가 아니다. scope/동의/비용 gate를 먼저 만족해야 초기 요청이 가능하다. proxy·실제 DNS 재바인딩 전수는 기존 보안 회귀를 재사용하며 metadata GET 경로가 동일 검증을 쓰는지를 C와 후속 회귀에서 대조한다.
- 실제 제공업체·실제 계정/키·모델·GPU·가격·다운로드, 임의 서버/모델의 무한 집합은 제외한다. fixture 응답은 `{"models":[{"id":"fixture-model"}]}` 등 **시험 전용 schema**이며 어떤 vendor의 현행 API 정본이라고 부르지 않는다. 완전 목록의 정의가 확보되지 않은 route는 UNKNOWN이다.
- 각 family의 위에 적힌 축 순서대로 Cartesian product의 오른쪽 축부터 증가시키며 1부터 세 자리 ID를 준다. T는 예외적으로 집합 oracle를 001에 먼저 둔다. expected manifest는 이 문서의 상수 분모로 손작성하며 제품 enum/registry/TEMPLATES를 expected ID·값 생성에 import하지 않는다. D의 입력 fake 자원 등은 실제 조사 함수를 호출하지 않는다.
- 단언 실행 ID와 expected ID **607개**의 missing/duplicate/extra=0을 수락 조건으로 한다. ID 표만 생성한 경우에는 실행 증거가 아니며 실제 assertion/node 매핑도 별도로 감사한다. G13 및 기존 manager 회귀 ID는 재사용 목록이지 GS04 분모의 일부가 아니다. 생성 속성/짧은 상태열 반복 횟수와 ID 감사 자체의 node는 607에 더하지 않는다. 결정 G에서 M9를 보류하면 그 네 ID와 알려진 공백을 따로 기록하고 승인된 수락 분모 603을 감사한다.

## 4. mutation 계획

정상본 시험 뒤 **격리 사본 하나에 변이 하나**를 적용한다. 목표 assertion 실패만 검출로 인정하고 import/수집 오류·timeout·다른 원인의 실패는 INVALID다. 아래 범위가 family 내 모든 행을 덮는다. 모든 행에서 mutant가 죽어야 한다는 뜻은 아니며, 행별 manifest에 적용 대상과 정상 기대값·목표 node를 연결한다. 단순히 시험 파일에서 expected를 반대로 바꾸는 변이는 사용하지 않는다.

| 변이 | 되돌릴 제품 행동 | 대상 행·목표 assertion |
| --- | --- | --- |
| Q01 | 정적 선언을 OBSERVED/실제 서비스 성공으로 승격 | D 전행: I/O0·DECLARED·NOT_RUN 유지 |
| Q02 | provider 상태를 GPU 관측/실행 정책으로부터 채움 | D 전행, L 전행: 세 정책×세 자원에서도 동일 literal provider 결과, 자원 타입 입력 거부·다른 store 불변 |
| Q03 | 템플릿 하나 삭제/추가 또는 key 교체 | T-001: literal set 정확히 5개 |
| Q04 | 템플릿 분기 하나를 meeting으로 고정 | T-002…021: hand-written prompt wire equality(그 분기의 non-meeting 행) |
| Q05 | 관리 preview의 license/URL/hash/공간/저장 경로 한 필드 생략 | M2의 4행: 전체 표시 fixture equality |
| Q06 | approval gate 우회 또는 checkbox만으로 설치 | M1…M4의 각4행: 의도 이전 installer0·안내 |
| Q07 | manifest 교체 시 approval 초기화 제거 | M5의 4행: B preview·approval false·installer0 |
| Q08 | 취소 Event 전달 누락 | M6의 4행: 같은 Event set·성공/활성화0 |
| Q09 | 화면과 다른 plan/approved 값 전달 또는 busy gate 제거 | M7/M8 각4행: 표시 plan identity·installer1/추가0 |
| Q10 | trust 안내를 숨김/OBSERVED이면 로컬 보장으로 바꿈 | L 전행: profile별 정확한 가시성·경계 문구, 권한/추론 차단 불변 |
| Q11 | 목록 성공으로 모든 capability true, 모델 없음/오류를 미지원 확정으로 처리 | S의 사건1…4, N 성공/redirect 행: 두 관측 fact만 바뀌고 선언 불변 |
| Q12 | TTL 검사 제거 또는 `age <= 300` 수락 | S 사건5…7의 각3행: 299.999 유지, 300/300.001 UNKNOWN |
| Q13 | key/세대 변화의 cache 무효화 생략 | S 사건8…16의 각3행, C 전행: 변경 후 UNKNOWN·옛 결과 게시0 |
| Q14 | 취소·미지원 route·초과 응답·불량 시계를 관측으로 채택 | S 사건17…21의 각3행: UNKNOWN·cap/시계 경계 |
| Q15 | audio/transcript/context 또는 잘못된 scope/epoch grant로 metadata 허용 | N 전행: 손 gate 표의 vault/DNS/open/write 수 |
| Q16 | metadata 허용만으로 자동 조회 또는 불명 route/외부 비용/owner 검사를 생략 | N 전행, L 전행: preview/허용 자체 전송0·사전 거부0 |
| Q17 | metadata permit를 POST·다른 body/종류/모델에 재생 | C 전행, N 전행: 고정 GET/빈 body/plan guard와 data_type별 API 격리 |
| Q18 | 각 경계의 철회/plan 재검사나 최종 승인 검사 생략 | C 전행, H1…H6 각2행: 변경 뒤 전송0/늦은 게시0·최신 결과 보존 |
| Q19 | GET에서 redirect/proxy/retry를 허용 | N redirect 행, H의 취소/실패 행: 최초 handoff 수와 후속 목적지 송신0/재시도0 |
| Q20 | 요청 중복 합치기·창/token guard 제거 | H 전행: 동일 진행1·창 종료 후 변경0·최신 응답만 유지 |
| Q21 | 원시 응답/예외/header/vault 값을 DTO·로그·DB·UI로 복사 | P 전행: canary 부재·최소 header 수신처와 vault read 경계 |
| Q22 | choose_manifest 실패 분기의 preview 초기화 제거 | M9(`GS04-M-033…036`) 4행: 옛 A preview가 현재 계획으로 남지 않음·plan=None·approval false·안내·installer0 |

Q02/Q10/Q16의 권한·자원·모델 확인 불변 단언은 기존 G11/G13/G16 회귀와 함께 확인하되 그 기존 의미 행은 새 ID로 중복 생성하지 않는다. 여러 결함을 한 변이에 섞지 않으며 Q05/Q09/Q13/Q14/Q17/Q18/Q21의 “또는” 항목은 실제 실행 시 `Qxx-a…`로 각각 분리하여 목표 assertion을 기록한다. 이 표의 22개는 **변이 종류 계획**이고 실행 건수·검출 수가 아니다. Q18의 C 목표 횟수는 §3.1 경계별 누적 literal 표를 사용하고, Q20의 H5/H7은 취소 뒤 새 token 허용과 진행 중 합치기를 각각 확인한다.

## 5. 구현 단계 쓰기 범위·공유 소유권·시간 예산 제안

현재 배정은 문서 하나이며 아래는 **재배정 요청 목록**이다. 제품·시험 파일을 미리 고치지 않았다. 공개 API 변경은 C00가 B14/P05 소유 경계와 함께 승인해야 한다.

| 후속 단위 제안 | 정확한 파일 | 목적과 경계 |
| --- | --- | --- |
| P04-S2 제공업체 사실/guarded probe | `src/recoryn/providers/contracts.py`, `src/recoryn/providers/__init__.py`, 신규 `src/recoryn/providers/facts.py` | provider 전용 DTO/facade/메모리 cache·고정 plan. 기존 capabilities·실행 protocol 유지. production route는 승인 전 비활성 |
| 같은 S2의 보안 경계 | `src/recoryn/security/gateway.py`, `src/recoryn/security/transport.py` | fixed GET metadata API·guarded header handoff. 기존 추론 POST·ledger·consent schema를 완화하지 않음 |
| S2 표시/명시 요청 | `src/recoryn/ui/privacy.py` | 선언/최근 관측 분리, 별도 metadata 동의와 요청·worker 수명. 기존 stt/summary 준비를 metadata로 재사용하지 않음 |
| S2 신규 시험 | 신규 `tests/unit/test_provider_facts.py`, `tests/contract/test_provider_probe.py`, `tests/ui/test_provider_facts_ui.py`, `tests/property/test_provider_facts_case_space.py` | D/S/P, N/C, H, 9 family ID 감사. L/T/M ID는 후속 S3 전까지 예정 목록과 실제 수집을 명시적으로 분리 |
| P04-S3 템플릿/설치 UI/안내 | 신규 `tests/unit/test_summary_templates.py`, `tests/ui/test_managed_install_ui.py`, `tests/ui/test_local_server_notice_ui.py`; `src/recoryn/ui/privacy.py`; **결정 G의 추가 요청 `src/recoryn/ui/models.py`** | T/M/L. T와 M1~M8은 시험 보강, 서버 안내는 privacy.py 변경. M9는 **choose_manifest 형식 오류 실패 분기의 preview 초기화만** 제품 수정 요청. C00 승인 전에는 수정하지 않는다. S2와 privacy.py 작성 순서를 직렬화 |
| 계약/결과 | `docs/testing/gs04-provider-facts-cases.md` | 승인 결정·수정 분모·실행 결과·미검증 append. 다른 공용 계약/배정표는 C00 소유 |

**수정 제외:** `ui/models.py`는 **결정 G를 C00가 승인한 경우의 choose_manifest 형식 오류 실패 분기 preview 초기화만 예외**이고 나머지는 제외한다. `models/artifacts.py`, `models/manager.py`, `models/resources.py`, `models/gpu_inventory.py`, `app/device_policy.py`, `ui/main.py`, `ui/ai_bridge.py`, `app/inference.py`, `providers/_common.py`, `transcription/adapters.py`, `summarization/adapters.py`, `security/consent.py`, `security/cost.py`, `security/ledger.py`, `security/vault.py`, storage/DB schema·capture는 수정하지 않는다. ModelPanel 또는 보안 API에서 기존 시험이 내부 구현 가정으로 깨지면 **파일·실패·변경안을 먼저 보고하고 재배정 전 수정하지 않는다**. metadata 추가에 consent schema 변경이나 클라우드 비용 확장이 필요하면 이 범위로 억지 구현하지 않는다.

| 공유 영역 | 충돌·의존성 조정 |
| --- | --- |
| G-P11b 자원/worker | resources/gpu_inventory·lease/ACK·추론 lane은 읽기만 한다. provider 사실은 자원 요구 추정/실행 가능성 판정 입력으로 사용하지 않는다. probe 때문에 lease·native child·nvidia-smi를 만들지 않는다. |
| G-P13 모델 확인 | models/artifacts·ui/models의 source pin/확인/worker 종료를 재작성하지 않는다. 리드의 r2 지시에서 G-P13은 이미 푸시됐고 ui/models.py의 소유가 비어 있음을 확인했지만, 실패 분기 재배정 승인 권한은 **C00**에게 있다. 결정 G 승인 시에만 그 분기의 preview를 초기화한다. M은 독립 신규 시험 파일에서 기존 ModelPanel을 사용하며 작은 synthetic fixture만 공유한다. |
| G-P16 정책 | ui/main·ai_bridge·device_policy 설정 저장은 제외한다. 정책 복원·변경이 provider grant·cache를 만들어서는 안 되며 provider 관측도 정책을 변경하지 않는다. |
| B14/P05·P01 | gateway/transport의 additive metadata API와 probe 전용 credential resolver 수명은 B14/P05의 사전 합의가 필요하다. 기존 추론 비밀 수명 개선은 P05에 남긴다. privacy.py는 P01/P05/G16 후속 소유와 C00가 직렬 배정한다. |

추천 분할의 의미 분모는 **S2 508행(D90+S63+N288+C33+H14+P20), S3 99행(T21+M36+L42)**이다. L은 S2 표시 DTO 뒤에 연결하고 T/M1~M8은 시험 보강으로 준비 가능하나 **M9는 기존 제품으로 oracle를 충족하지 않아 결정 G의 제한된 수정이 필요하다**. 분리 통합 시 감사 manifest도 각 승인 단위의 실제 행을 먼저 검사하고, 두 단위가 합쳐진 tree에서 607을 확인한다. 아직 없는 S3 행을 수집된 것으로 보거나 skip placeholder로 만들지 않는다.

신규 **7시험 파일 합계 60초**를 수락 게이트로 제안한다. 예산은 D/S/P 8초, N/C 16초, H 6초, T 4초, M 12초, L 8초, ID 감사 2초, 여유4초다. 이는 미측정 목표다. fake clock/한 번 만든 synthetic fixture/가벼운 QApplication을 재사용하되 cache·승인·세션은 행마다 초기화한다. 초과하면 측정값과 같은 부하의 기준 시간을 먼저 보고하며 축 삭제로 맞추지 않는다. mutation 전체·관련 회귀·CI 시간은 이 신규 시험 게이트와 별도다.

구현 검증은 승인된 고정 기준에 `git archive <기준>`+배정 파일만 OS TEMP 새 사본에 얹고, PYTHONPATH와 pytest rootdir를 그 사본으로 고정한다. 부모/실제 생성되는 spawn 자식의 import origin을 확인한다. 옵션은 `-p no:cacheprovider`, 고유 TEMP `--basetemp`, `QT_QPA_PLATFORM=offscreen`, `-W error::ResourceWarning`이다. 각 변이는 별도 사본이다. CI 동등은 그 승인 기준 `.github/workflows/core.yml`의 Ruff/format/mypy/전체 pytest `--cov` 85와 `scripts/check_coverage.py` 묶음 line95/branch90·offline wheel 단계/flag를 그대로 따른다. 이 계약 작성에서는 실행하지 않았다.

관련 회귀는 기존 provider unit/contract, gateway/security/consent scope, privacy UI, models UI, G13 unit/property/UI/bundle, G11 자원 정책, G16 device-policy unit/UI/integration, AI 독립 회귀를 기준 tree에서 선정한다. 기존 node를 재사용하고 새 분모로 옮기지 않는다. 독립 보안 검토·리드 재검증·C00 통합 승인 없이 자기 결과를 최종 승인하지 않는다.

## 6. 대안과 C00 결정 요청

| 결정 | 권고 | 대안·승인할 경계 |
| --- | --- | --- |
| A. 단위 분할 | **S2 508행과 S3 99행 분리**, privacy.py는 직렬 작성 | 하나의 큰 단위로 할 경우 API·동의·UI·보안 검토가 모두 닫혀야 통합 가능. 리뷰 S3 판정 정정만으로 S2 완료 처리하지 않음 |
| B. 이번 probe 범위 | fixed GET/empty body·metadata 전용 동의·guarded fake/loopback 시험 계약을 먼저 승인. **생산용 route는 정본 검토 전 비활성** | 표시 모델만 먼저 구현하는 안도 가능. 결정 G 포함 시 D/S/P/T/M/L **272행**, 송신·경합 N/C/H **335행** 후속. G01BR-11의 허가 후 실제 probe 기능은 계속 PARTIAL이며 607 전체 검증으로 보고하지 않음 |
| C. 관측 만료 | monotonic 완료 후 **300초 미만**, 경계/identity/epoch 변경 즉시 UNKNOWN | 60초 또는 명시 새 요청까지. 무기한 선택 시에도 identity/권한/재시작 무효화는 생략할 수 없으며 TTL 행/oracle를 승인 수치에 맞게 수정 |
| D. 동의/API | 기존 stt/summary capability + 신규 `provider_metadata` data_type, session-only, **별도 fixed GET API** | 별도 capability `probe`/다목적 method API는 consent 정책·SendPermit method binding까지 재설계가 필요하므로 별도 배정. audio/transcript grant 포괄 허용은 대안으로 두지 않음 |
| E. 실제 지원 route/원격 | 초기 빈 production registry, 외부 HTTPS/비용 불명 probe는 무전송. owned loopback도 route 승인·별도 동의·기존 proof 필요 | 정본 route/schema·허용 데이터·비용·owner guard가 승인된 후 하나씩 활성화. 최신 API 검토는 별도 배정이며 실제 호출/계정/다운로드는 이번에도 금지 |
| F. 비밀 수명/공유 파일 | probe 전용 최소 resolver를 B14/P05와 합의한 후 S2 배정 | 합의 전에는 표시 모델/S3까지만. 기존 ExecutionContext·vault/ledger를 임의 수정해 범위를 늘리지 않음 |
| G. 형식 오류 선택 뒤 계획 preview | **M9 4행과 choose_manifest 실패 분기의 preview 초기화 수정**을 S3에 포함. approval false·plan=None·기존 오류 안내/다운로드 거부는 보존 | 알려진 공백으로 남기고 계획된 M36행 중 M9(`GS04-M-033…036`)를 이번 수락 범위에서 제외할 수 있다. 그러면 실행 대상 M32·S3 95·전체603(표시 대안268+335), 제품6+시험7+본문1=14파일이며 Q22도 후속으로 보류한다. M9는 미검증/미해결로 명시하고 G01BR-13의 정직한 preview까지 닫혔다고 하지 않는다. G-P13 푸시 완료·소유 공백은 재배정 근거일 뿐 **승인은 C00 몫**이다. |

C00에는 **A~G**의 선택과 정확한 구현 시작 기준·**G 포함 시 15파일(제품7+신규시험7+본문1)**의 소유/직렬 순서 확정을 요청한다. G를 보류하면 위 대안의 14파일·603행으로 수락 범위를 명시적으로 다시 고정한다. 새 route나 비용 API가 추가되면 분모·mutation·파일 범위를 먼저 개정한다. 아직 승인되지 않은 대안을 구현 허가로 해석하지 않는다.

## 7. 미검증과 인계

- **이번 결과는 읽기·계약 작성만**이다. pytest/collect-only/mutation/ruff/mypy/coverage/wheel은 **미실행**이다. 607은 결정 G 포함 시 계획 의미 행이며 새 PASS 수를 보고하지 않는다. M9는 6156b65 소스상 oracle 미충족인 알려진 공백이고 아직 수정하지 않았다. G12b 등 이전 실행 수를 이 계약 근거로 합산하지 않는다.
- 실제 서비스/API·가격·계정 인증·유료 호출·Credential Manager 실제 읽기/쓰기·모델 다운로드/실행·실제 GPU/서버·Ollama cloud 차단의 실환경 검증은 NOT_RUN이다. fake 또는 loopback fixture 통과는 해당 외부 게이트를 대체하지 않는다.
- 실제 Windows 키보드/스크린리더, 타 프로세스의 서버 재시작·후속 전송, DNS/네트워크 전체 관찰·비밀 메모리 제거 보장은 별도 미검증이다. loopback 주소·목록 응답·owned 증명·장치 정책·관리 모델 확인을 서로의 인증으로 사용하지 않는다.
- G-P13 재사용 시험은 존재/단언을 읽어 확인했으며 이번 실행 결과가 아니다. ADR17 수동 모델의 사용자 책임 확인과 관리 공급망 검증 완료 집계는 분리한다.
- C00의 A~G 결정, B14/P05 API 합의, 독립 검토, 새 기준에서 정확한 파일 배정이 남아 있다. 문서 밖 구현 필요 사항은 이 계약으로 보고했으며 실제 범위 밖 쓰기는 하지 않았다.

검토용 pinned source 사본·읽기 감사는 리드가 지정한 `scratchpad/codex/p9-out/gs04-6156b65/`에 둔다. 이 임시 자료의 보존/접근 수명은 저장소 계약 문서와 다르다.

## §GS-P04a 확정 범위(C00 결정, 기준 de27a81)

시작 HEAD는 `de27a81f57f5e80e71fa4f65b0b4b0565e37dee4`다. 위 r2의 LF SHA256 `a3a9dee4205956c14605a5451edc4e58b3b3aa22500518cc5264c75c482d70a6` 바이트를 보존하고 이 절부터 덧붙인다. 작성자는 구현/자체 검증, 리드는 독립 검증, C00는 별도 독립 검토·통합·commit/push를 맡는다.

### 확정 결정과 04a 경계

- A 분할 승인, B 표시 우선, C TTL 300초 미만·identity/epoch 변경 즉시 UNKNOWN, G M9 수정 승인이다. D/E/F는 **04b 설계로만 승인**됐으며 이번 제품 코드에 구현하지 않는다. 생산 registry는 빈 불변 mapping이고 probe/네트워크 요청 버튼·metadata 동의·GET/plan guard·vault 접근·Job/모델 실행 경로를 만들지 않는다.
- P20은 raw bytes/원시 오류/redirect URL/선택하지 않은 모델명/인증 echo·audio/transcript 표식이라는 다섯 canary × DTO+repr/화면+a11y/로그/임시 DB·설정·지원 출력의 네 표면이다. fake 입력을 순수 parser에 주입한다. 모든 행에서 vault 읽기·socket·DNS 0이다. header 수신처·vault None 읽기1은 04b로 보류한다.
- S63은 fake clock과 fake 입력으로 관측 상태기계를 검사한다. parser는 최대1MiB bytes와 시험이 주입한 descriptor(list/id/완전성 필드)를 받고 완전한 목록만 관측한다. vendor schema/생산 route는 없다. 실패/취소/미지원은 입력 결과 종류이며 I/O가 아니다. 관측 시각/목적지/model/adapter/API/route/credential/consent/실행 세대가 달라지거나 시계가 부정확하면 UNKNOWN이다. 서로 다른 자원 관측 타입을 수락하지 않는다.
- UNKNOWN 문구는 **`최근 관측 없음 · 이 버전은 제공업체에 확인 요청을 보내지 않습니다`**다. r2의 별도 허가/관측 요청 안내는 이번 버전에 없는 기능을 암시하므로 쓰지 않는다. L의 OBSERVED는 시험 주입 관측 표시일 뿐 실제 서비스 검증이 아니며 actual_service_status는 NOT_RUN이다.
- D는 **(b) facts.py 표 + 같은 ID의 실제 adapter.capabilities 대조**를 채택한다. 프로토콜/contracts.py를 변경하거나 UI 표시 때문에 모델 config/실행 준비를 요구하지 않고, 표의 drift는 일곱 지원쌍의 실제 adapter와 손 literal oracle 양쪽으로 검출한다. 미지원 세 쌍도 D에 포함한다. socket/DNS/vault/native import 0이며 faster_whisper/ctranslate2/torch 신규 sys.modules 항목0이다.
- 기존 ID 번호를 유지한다. 보류는 **N-001…288, C-001…033, H-001…014 = 335행**이며 collect/skip/placeholder를 만들지 않는다. 새 수락 분모는 **D90+S63+P20+T21+M36+L42=272**다. 실제 단언을 실행한 ID와 독립 manifest의 누락·중복·초과0을 감사한다.

| 실제 시험 파일·node | 독점 소유 family/ID | 행 |
| --- | --- | ---: |
| `tests/unit/test_provider_facts.py::test_declarations_match_literals_and_adapters` | GS04-D-001…090 | 90 |
| 같은 파일 `::test_observation_lifetime` | GS04-S-001…063 | 63 |
| `tests/ui/test_provider_facts_ui.py::test_fake_inputs_leave_no_private_material` | GS04-P-001…020 | 20 |
| `tests/unit/test_summary_templates.py::test_five_template_set`, `::test_template_wire` | GS04-T-001, GS04-T-002…021 | 21 |
| `tests/ui/test_managed_install_ui.py::test_managed_install_intent` | GS04-M-001…036 | 36 |
| `tests/ui/test_local_server_notice_ui.py::test_server_notice_and_facts` | GS04-L-001…042 | 42 |
| `tests/property/test_provider_facts_case_space.py` | 272 ID 독립 감사(meta node, 의미 행 추가 없음) | — |

### 04a mutation·쓰기·검증

04a 변이는 Q01~Q14/Q21/Q22만이다. 구체 변이 표는 구현 결과와 함께 이 절 아래에 고정한다. 정적 선언 승격(Q01-a)/실제 서비스 상태 승격(Q01-b), 자원 문자열 타입 허용(Q02-a), 템플릿 key 삭제(Q03-a)/추가(Q03-b)/교체(Q03-c), non-meeting 분기 meeting 고정(Q04), preview 필드별 누락(Q05-a…f), 승인 gate 우회(Q06-a)/checkbox만으로 설치(Q06-b), 새 manifest 승인 초기화 제거(Q07), cancel 전달 누락(Q08), 다른 plan 전달(Q09-a)/approved false(Q09-b)/busy gate 제거(Q09-c), 안내 숨김(Q10-a)/관측 시 로컬 보장(Q10-b), 목록 성공의 기능 승격(Q11-a)/목록 없음 UNKNOWN 대신 false 지원 판정(Q11-b)/schema 실패 관측 채택(Q11-c), TTL 검사 제거(Q12-a)/300초 수락(Q12-b), identity 각 필드 무효화 누락(Q13-a…), 취소/미지원/초과/역행/시각 검증 제거(Q14-a…), raw 입력 로그 노출(Q21), 오류 선택 뒤 preview 초기화 제거(Q22)를 각각 별도 사본에 적용한다. Q11의 N·Q13의 C 등 송신/plan guard 대상은 제외한다. 정상본 뒤 목표 assertion 실패만 검출이며 수집/import/timeout은 INVALID다. 구현에 없는 동작은 변이 대상 코드로 억지 추가하지 않고 같은 결함의 실제 코드 지점과 목표 assertion을 결과에 명시한다.

쓰기 허용은 신규 `providers/facts.py`, `providers/__init__.py` export 추가, `ui/privacy.py` 표시/안내와 기본값 있는 keyword-only 주입, `ui/models.py` choose_manifest 형식 오류 실패 분기 preview 초기화, 위 신규 시험6개, 이 문서 append뿐이다. contracts.py가 필요해지거나 기존 시험 수정이 필요하면 먼저 보고한다. gateway/transport/consent/cost/ledger/vault·adapter·ui/main/ai_bridge·models/artifacts/manager/resources/gpu_inventory·app은 수정하지 않는다.

신규6파일 합계60초, 272 ID 감사, 지정 관련 회귀, 모든 04a 단일 mutation, 기준 core.yml 동등 정적 검사/전체 coverage·묶음 예산/offline wheel을 **git archive de27a81 + 허용 파일만**으로 만든 OS TEMP 사본에서 검증한다. PYTHONPATH/rootdir/import origin(생성되는 spawn 자식 포함)을 사본으로 고정하고 기존 cache 비활성·고유 basetemp·offscreen·ResourceWarning error 옵션을 유지한다. 실제 네트워크·설치·서비스·vault·모델·GPU 검증은 하지 않는다. 시작 hash·실행 JSON/log는 지정 `scratchpad/codex/p9-out/gs04a/`에 둔다.

### 04a 구현 지점과 고정한 단일 변이 46개

DTO/enum/descriptor/cache는 모두 신규 facts.py 안에 있으며 contracts.py를 변경하지 않았다. public describe는 표를 읽고, parse_observation은 주입 bytes를 두 bool 사실로 줄인다. ObservationState.bind/accept/snapshot은 메모리 상태와 fake clock만 다룬다. PrivacyPanel은 기본값 있는 keyword-only `provider_facts` 주입과 세 label을 추가하며, 1초 UI timer의 순수 재표시로 관측 만료를 반영한다. 기존 실행 준비·동의·비용·vault API를 사실 조회에 사용하지 않는다. M9 제품 변경은 실패 분기의 `self.preview.clear()` 한 줄뿐이다.

아래는 추상 r2 변이를 현재 구현의 실제 지점으로 구체화한 목록이다. Q11은 04a에 존재하는 목록 사실/완전성만 다루며, N의 송신이나 추론 capability 승격 경로는 없다. S의 실패/취소/미지원 사건에는 **정상 bytes가 함께 있어도 결과 종류가 우선**하도록 시험한다. S16은 같은 상태 객체의 실행 세대 변경과 새 cache 생성 둘 다 검사하고, S21은 accept 시각과 snapshot 시각의 오류를 구분한다.

| 단일 변이 | 개수 | 실제 되돌림·목표 assertion ID |
| --- | ---: | --- |
| Q01-a/b | 2 | 선언을 OBSERVED로 / actual_service_status를 성공처럼 변경 → D001의 DECLARED / NOT_RUN |
| Q02-a | 1 | 자원 문자열/객체가 provider evidence로 들어오는 타입 gate 제거 → D001의 거부 단언 |
| Q03-a/b/c | 3 | 템플릿 삭제/추가/key 교체 → T001의 literal set |
| Q04 | 1 | 실제 core wire의 템플릿을 meeting으로 고정 → T006 prompt equality |
| Q05-a…f | 6 | license ID/license URL/파일 URL/SHA256/총 bytes/저장 경로 각각 누락 → M005 전체 preview equality |
| Q06-a/b | 2 | 미선택 download gate 제거 / checkbox만으로 설치 → M009 안내·M013 installer0 |
| Q07 | 1 | 새 manifest 승인 초기화 제거 → M017 승인 false |
| Q08 | 1 | 다른 cancel Event 전달 → M021 작업 Event identity |
| Q09-a/b/c | 3 | 다른 plan 전달/approved false/busy 중 manifest 교체 허용 → M025 표시 plan·승인 / M029 기존 task·plan |
| Q10-a/b | 2 | 서버 안내 숨김/관측 문구를 로컬 보장으로 변경 → L001 가시성 / L003 인증·실행 보장 아님 |
| Q11-a/b/c | 3 | 미등재를 true로 승격/미등재 관측을 UNKNOWN으로/불완전 목록 채택 → S002 포함 여부·증거 수준 / S004 거부 |
| Q12-a/b | 2 | TTL gate 제거/300초 수락 → S027 만료 |
| Q13-a…i | 9 | endpoint/inference endpoint/model/adapter/API/route/credential/consent/session generation을 각각 identity 비교에서 제외 → S008…016 옛 key accept 거부 |
| Q14-a…h | 8 | CANCELLED/UNSUPPORTED/TRANSPORT_FAILED 입력 무시, 크기 cap 제거, 역행 gate 제거, observed_at 검증 제거, snapshot clock 검증 제거, descriptor 없음 관측 채택 → S017/S018/S003/S019/S041/S021 |
| Q21 | 1 | raw bytes/error/redirect tuple을 로그에 기록 → P003 canary 부재 |
| Q22 | 1 | M9 preview 초기화 되돌림 → M033 옛 A preview 없음 |
| 합계 | **46** | 정상본 통과 뒤 각각 독립 사본·목표 assertion 실패만 검출 |

각 사본의 변경 input 파일은 목표 제품 파일 하나뿐이며, 04a에서 원래 고치지 않는 template·ModelPanel의 기존 경계를 변이할 때도 **OS TEMP 시험 사본에만** 적용한다. 원본 adapters 등 금지 파일은 쓰지 않는다. 결과 JSON에는 실제 target node/강조된 assertion·원본/변이 hash·부모/spawn import 출처를 남긴다.

### GS04a 구현 결과 — 작성자 검증 완료, 독립 검토 대기

**GS04a IMPLEMENTATION_READY / 기준 de27a81f57f5e80e71fa4f65b0b4b0565e37dee4 / Windows Python 3.13.1**. 공유 HEAD가 도중 GS-P06의 `5aa988e`로 이동했지만, 검증은 지시한 시작 기준을 유지했다. 아래는 실행한 결과이며 새 HEAD 재검증·독립 최종 승인을 뜻하지 않는다.

| 검증 | 실제 결과 |
| --- | --- |
| 신규6파일 합계60초 게이트 | **273 PASS**, pytest 2.32초 / 프로세스 wall 3.16초. 의미 ID272와 meta 감사1이다. 60초 미만이므로 기준 시간 추가 측정 조건은 발생하지 않음 |
| 분모·실행 감사 | D90/S63/P20/T21/M36/L42 **272/272**. 실제 assertion 완료와 file/node 소유를 대조해 missing/duplicate/extra **0/0/0**. N/C/H 수집·skip·placeholder0 |
| 지정 관련 회귀13파일 | **2,559 PASS**, pytest 79.61초 / wall 82.08초. 요청한 provider unit/contract·privacy/models UI·G13 4파일·G16 3파일·독립 보안/AI를 모두 포함. 기존 시험 수정0 |
| 04a 단일 mutation | **46/46 목표 assertion 실패 검출**, INVALID0/SURVIVED0. 사본마다 변경 input 파일1, 정상본 대비 다른 입력 변경0, 부모/spawn import 출처 확인 |
| 전체 Ruff / format | `ruff check src tests scripts packaging`, `ruff format --check` PASS, 222파일 format 일치. cache는 사용하지 않음 |
| 전체 mypy | MYPYPATH=src, `src/recoryn scripts packaging`, no-incremental·사본 cache 경로, **96 source files PASS** |
| CI 동등 전체 pytest | **28,547 PASS**, fail/error/skip0, pytest **2,391.48초** / wall 2,405.99초. `--cov=recoryn --cov-branch --cov-report=term-missing --cov-report=json:coverage.json --cov-fail-under=85` 포함 |
| coverage 묶음 | `scripts/check_coverage.py` **7묶음 PASS**. 전체 line94.20% / branch88.88%, pytest combined92.86% |
| offline wheel | `pip wheel --no-deps --no-build-isolation --no-cache-dir --wheel-dir dist .`, PIP_NO_INDEX=1로 **PASS**. 의존성 설치·다운로드0. wheel 내 facts.py와 검증 소스 일치 |

coverage line/branch는 domain99.18/97.89, capture99.85/98.57, jobs99.20/95.65, storage96.21/91.55, security98.11/94.43, content98.98/99.02, all94.20/88.88(%)다. 앞6묶음의 예산은95/90, all은85/80이다. line/branch 수치를 의미 행·mutation·독립 검토의 대체 근거로 사용하지 않는다.

원격 core job의 dependency install은 금지된 설치/네트워크 때문에 실행하지 않았고, 이미 있는 .venv의 Python3.13.1을 사용했다. wheel은 build isolation을 끄고 인덱스를 차단해 설치 없이 검증했다. CI와 동일한 lint/format/type/test/coverage 예산을 적용했고, pytest에만 사본 rootdir·고유 TEMP basetemp·JUnit 경로를 추가했다. QT_QPA_PLATFORM=offscreen, HF_HUB_OFFLINE=1, HF_HUB_DISABLE_TELEMETRY=1, `-p no:cacheprovider -W error::ResourceWarning`를 유지했다.

검증 입력은 **git archive 시작 HEAD + 허용11파일, 총414파일**이다. raw SHA와 LF SHA로 대조했으며 다른 세션의 capture/storage/app 변경은 들어가지 않았다. 부모와 실제 spawn 자식이 facts/privacy/models/resources를 모두 사본 src에서 import했다. 별도의 깨끗한 interpreter에서는 providers import 전부터 DNS/socket·Credential Manager와 native AI import를 막고 10개 provider/kind 조합을 확인했다. DNS/socket/vault/CFM 접근0, Faster-Whisper/CT2/Torch/ONNX Runtime/Sherpa/Transformers/Tokenizers 신규 module0이었다.

초기 새 UI 시험의 mouse 클릭이 checkbox indicator를 벗어난 문제는 새 helper가 실제 indicator를 클릭하게 고쳐 해결했다. 기존 제품 시험은 바꾸지 않았다. 변이 최초 요약 분류기는 pytest xunit2에 없는 type 속성을 읽어 오분류했으므로, 보존한 JUnit의 **단일 목표 node·강조된 assertion·AssertionError/DID NOT RAISE·error/skip0·변경 파일1·import 출처**로 46건을 재감사했다. 원본 log/JUnit/최초 분류도 보존했으며 최종 정본은 `mutation-verified.json`이다. 수집 오류·timeout·다른 assertion을 검출로 세지 않았다.

검증한 Python 소스의 LF SHA256은 다음과 같다. 이 결과 절은 CI 이후 문서에만 append했으며, 아래10파일은 최종 CI 사본과 같다. 문서 자체의 최종 hash는 채팅 보고와 `final.json`에 남겨 자기 hash를 본문에 되쓰는 순환을 피한다.

| 파일 | SHA256(LF) |
| --- | --- |
| src/recoryn/providers/facts.py | `2421f9e7c092d52fbb986861e06194851df4e279a6e0532ec8af1fe9dbff045b` |
| src/recoryn/providers/__init__.py | `ac0b0635bf8b3b79d148623b557ae429071b9f058fdb03a6455e968863606bca` |
| src/recoryn/ui/privacy.py | `8c125e6fe30a2aacd1769caed7e7ac341d74331441eb761cc47393ed39a87401` |
| src/recoryn/ui/models.py | `715f60b90afb2dc9732057226b5a19a44e2d5b1be799ad1cfef4f1b76b7b119f` |
| tests/unit/test_provider_facts.py | `24cf177f82a02c2cb223b5c88bce0030c68e0dce7c9e93bf66a02a255a0c1a41` |
| tests/unit/test_summary_templates.py | `ce661c3d33a6880cd24280617229421b418478dcc95fc28be73693cb5091c75d` |
| tests/ui/test_managed_install_ui.py | `163133769bdc6ca515403dba640c2882e5a3f204b7256a6e295c692fb853632e` |
| tests/ui/test_local_server_notice_ui.py | `6afae05f771ab4cb2d3f4acab5c76bda0d7b13b1f08519b0b1dae21efa4ade5a` |
| tests/ui/test_provider_facts_ui.py | `13a4168dedb3923df9354105db481bf463799c60cb5f4f38e9f0e6897a1242f2` |
| tests/property/test_provider_facts_case_space.py | `93a998709864422824b6e009187383fdb424a50ec0034f6775412143a7e693ba` |

최종 증거는 지정 `scratchpad/codex/p9-out/gs04a/`의 `final.json`, `start.json`, `scope-audit.json`, `archive-raw-audit.json`, `id-audit.json`, `mutation-verified.json`, `clean-import.json`과 log/JUnit/coverage/wheel이다. 최종 CI는 `r-gs04a-ci-9dd56deca0.json`, 최종 관련 회귀는 `r-gs04a-related-2f67c80a09.json`, 신규 게이트는 `r-gs04a-gate-97fa4d6587.json`이다. frozen-source에는 검증한 소스를 별도로 보존했다.

판단 요청은 리드 독립 검증·C00 별도 검토와 통합 판정이다. contracts.py 등 범위 추가 요청은 없다. 새 HEAD 재검증은 별도 지시를 기다린다. **미검증/보류:** 04b N288/C33/H14의335행, 실제 서비스·계정·유료 호출·외부 송신·모델/다운로드·GPU·실제 Credential Manager·Narrator/실장비, Python3.11 matrix와 optional-runtime 설치 job. fake/fixture 통과를 실제 서비스 인증·실제 처리 위치·후속 무전송 보장으로 확대하지 않는다. commit/push는 수행하지 않았다.

## §GS-P04a FIX1

기준은 **5aa988eefacc5c249e0a3abbd534e6666894a672(GS-P06)**이다. 시작 시 허용11파일 hash를 다시 고정했고 직전 제출과 일치했다. 이 절 앞의 LF SHA256 `fd06f8e4851d23ca58e7f13f81af7aa283b94d2b93640d1d3639aba727d347a8` 바이트를 보존한다. 쓰기는 기존11파일뿐이며 다른 세션의 pyproject/app/storage 등 변경은 검증 사본에 넣지 않는다.

### 확정 수정·분모와 손 oracle

1. Ollama는 기존 전체 안내를 유지한다. 그 외 API 제공업체는 **비어 있거나 해당 provider/kind/model의 기본 endpoint인 경우만** 일반 안내를 숨긴다. 사용자 지정 IPv4/IPv6 loopback·원격 HTTPS에는 연결 대상/실제 추론 위치와 후속 전송의 한계/사용자 확인/redirect·proxy 경계의 일반 문장을 보이고 Ollama cloud 문장은 보이지 않는다. 잘못된 URL의 기존 입력 검증을 완화하지 않으며, 유효한 기본값으로 판정하지 못하는 입력은 일반 안내로 남긴다. Faster-Whisper/요약 끔은 서버 API가 아니므로 제외한다.
2. 기본 endpoint는 **실제 adapter의 I/O 없는 생성자 `.endpoint`**에서 유도한다. adapters/contracts.py는 고치지 않는다. Gemini는 현재 model을 반영한다. D의 동일 ID에서 손으로 쓴 기본 URL과 fake config로 생성한 adapter의 endpoint를 대조하고, L의 Gemini 기본 profile에서는 모델 변경/명시 endpoint/빈 endpoint도 확인한다. 송신·native AI import·vault 접근0이며 생산 metadata registry는 계속 빈 상태다.
3. 기존 L-001…042를 보존하고 profile8 OpenAI 요약 custom IPv4, 9 OpenAI STT custom loopback, 10 Gemini 요약 custom HTTPS, 11 Anthropic 요약 custom HTTPS, 12 Gemini 요약 기본값을 추가한다. **L=12×2×3=72, L-043…072 신규30행**, 합계 **D90+S63+P20+T21+M36+L72=302**다. OpenAI 요약 custom IPv6도 profile8의 추가 경계 단언으로 확인한다. 기존 file/node 소유를 유지한다. N288/C33/H14=335행은 계속 보류·수집0이다.
4. 정적 manifest 감사는 실행 선택과 무관하게 여섯 시험 모듈의 parametrize ID를 읽어 독립 literal302와 누락·중복·초과0을 확인한다. 실행 감사는 이번 session의 **실제로 발생한 GS04 call report**와 함수 진입 시 기록한 EXECUTED를 비교한다. 실패한 call도 포함하고, deselected/미실행/setup 실패는 call로 세지 않는다. session당 recorder 하나만 등록하므로 일부 선택·목표 assertion 실패에도 무관한 teardown error를 덧붙이지 않는다. 정상본의 assertion 완료는 정상 JUnit PASS와 함께 판정한다.
5. L의 OBSERVED 행에서 fake clock만 300초로 넘긴 뒤 **실제 활성 timer tick**으로 라벨이 만료되는지 확인한다(직접 refresh/timeout.emit으로 대체하지 않음). 시험에서 timer 간격만 줄이고 시작은 제품이 맡는다. 기존 L ID에 관측 주입→실제 설정 키 입력/context 변경·fake key 저장·동의 grant/revoke/delete→UNKNOWN 단언을 추가한다. 각 동작 전 관측을 새로 주입해 독립적으로 검사하고, 실제 vault가 아닌 fixture backend만 사용한다. P20의 vault 읽기·DNS/socket0 계약은 유지한다.
6. UI 선언 전체 문자열을 literal로 확인하고, OBSERVED(false)의 `선택한 모델이 목록에 없었습니다 · 기능 미지원 판정 아님` 문구를 확인한다. S의 schema 오류 사건에 완전성 값1/"yes"를 넣어 truthy를 완전한 목록으로 받지 않는 oracle를 보강한다. 새 의미 ID는 L30 외에 늘리지 않는다.

### FIX1 mutation·검증 계획

기존46개에 사용자 지정 non-Ollama 안내 숨김 **Q23**, non-Ollama에 Ollama cloud 문장 표시 **Q24**를 추가한다. 리드 변이 **L01(timer 미시작), L03(설정 세대 증가 제거), L04(권한/키 동작 세대 증가 제거), L07(미등재 문구 제거), L08(지원/미지원 반전), L15(완전성 truthy 허용)**도 같은 기존 ID의 목표 assertion으로 검출한다. 필수54개와 이미 검출됐던 리드 L02/L09/L13/L14의 재확인4개, **총58개**를 각각 독립 사본에서 재실행한다. 리드 L05는 별도 select_session invalidate가 있어 동등 변이로 분류한다는 리드 결정을 유지하며 검출 건수로 세지 않는다. 수집/import/setup/timeout/감사 error는 검출이 아니고, 목표 assertion 실패와 error0만 검출이다.

`git archive 5aa988e + 허용11파일`의 새 TEMP 사본에서 신규6파일60초/302 ID 감사, 감사 파일 단독·`-m property`·`-m "not ui"`·core.yml의 contract 부분 job 명령, 지정 관련13파일, 단일 변이58개, 전체 core 동등 lint/format/mypy/pytest coverage·묶음 예산/offline wheel을 확인한다. PYTHONPATH/rootdir·부모/spawn import 출처·cache 비활성·고유 basetemp·offscreen·ResourceWarning error 규칙은 그대로다. 증거 위치는 지정 `scratchpad/codex/p9-out/gs04a-fix1/`이다. 아래 결과를 적기 전에는 FIX1 PASS 수를 주장하지 않는다.

### FIX1 확인 결과·전체 CI 정체 보고

정적 manifest는 의미 ID가 있는 다섯 시험 모듈의 parametrize 표를 읽고, 여섯 번째 파일이 분모를 감사한다. D90/S63/P20/T21/M36/L72=302의 누락·중복·초과0, N/C/H 수집0이다. 아래 정상본·변이의 Python10파일은 동일한 최종 hash이고 기준은 5aa988e다.

| 검증 | 확인 결과 |
| --- | --- |
| 신규6파일 | 303 PASS, pytest4.38초 / wall5.37초, 60초 이내 |
| 정적 감사 단독 | 1 PASS, error/skip0 |
| `-m property` | 1 PASS, 302 deselected, error/skip0 |
| `-m "not ui"` | 175 PASS, 128 deselected, error/skip0 |
| core.yml contract 부분 job | 504 PASS, pytest34.44초 / wall35.10초, error/skip0 |
| 관련13파일 | 2,559 PASS, pytest67.22초 / wall68.48초, fail/error/skip0 |
| 리드 반례 | 지정 probe 7 PASS, custom 서버5건 포함 |
| mutation | 기존46 + 새2 + 리드10 = 58/58 목표 assertion 검출, INVALID/SURVIVED/error0 |
| 전체 lint/format/mypy | PASS, format224파일·mypy96 source files |
| 전체 pytest coverage | **미완료**: G17 기존 시험 실행 중 장시간 진전 없음. PASS/FAIL 판정 불가 |
| coverage 묶음·offline wheel | 전체 pytest 미완료로 아직 실행하지 않음 |

| 변이 구분 | ID | 목표 행·손 oracle | 결과 |
| --- | --- | --- | --- |
| 새 안내 | Q23/Q24 | L043 non-Ollama 사용자 지정 안내 표시/Ollama 문장 부재 | 2/2 검출 |
| 리드 변이 | L01 | L003 실제 timer tick 뒤 관측 만료 | 검출 |
| 리드 변이 | L03/L04 | L003 실제 설정 키 입력 및 grant/revoke/save/delete 후 UNKNOWN | 2/2 검출 |
| 리드 변이 | L07 | L021 모델 미등재·기능 미지원 판정 아님 literal | 검출 |
| 리드 변이 | L08 | L001 UI 선언 전체 literal | 검출 |
| 리드 변이 | L15 | S004 완전성1/yes 거부 | 검출 |
| 리드 변이 재확인 | L02/L09/L13/L14 | L001 중복 알림0/UNKNOWN literal, D019 timestamp, S004 중복 모델 거부 | 4/4 검출 |

58개 변이는 각각 별도 archive 사본에서 한 수정만 적용했다. 저장된 JUnit의 목표 node·강조된 assertion 실패·error/skip0, 실제 변경 파일 하나, 최종11파일 입력 hash와 부모/spawn import 출처를 재감사했다. 정상본의 일부 선택 실행과 변이의 실패 call 모두 실행 감사 teardown 오류0이다. 새 clean interpreter에서는 describe/default_endpoint의 10 provider-kind 쌍에 대해 DNS/socket/vault/CFM 접근0, native AI import 시도0 및 새 module0을 확인했다.

전체 CI 사본은 `C:/Users/gangd/AppData/Local/Temp/r-gs04a-ci-a5ae7d2332`다. `git archive 5aa988e + 허용11파일`, 총418개 입력의 raw/LF hash 일치와 실행 중 입력 불변을 확인했다. 부모/실제 spawn 자식 모두 사본 src에서 import했다. core.yml의 lint/format/type/pytest coverage flag·offscreen·ResourceWarning error를 유지했고, rootdir/PYTHONPATH/고유 TEMP basetemp를 사본에 고정했다. 설치·네트워크는 실행하지 않았다.

전체 pytest는 06:37:15 시작했고, 06:39:25에 생성된 마지막 tmp_path가 `test_registration_busy_keeps_l0`이며 06:52까지 다음 tmp_path가 생기지 않았다. 이 폴더의 소유 시험은 기준의 `tests/integration/test_append_fencing.py:633`의 `test_registration_busy_keeps_live_capabilities_and_withholds_pause_ack`(G17-R-03 추정)이다. 전체 실행의 traceback은 얻지 못했으므로 정확한 정체 지점과 GS04a 인과관계는 **미확정**이다. 해당 시험·app/recording.py·storage는 수정하지 않았다.

별도 원본 기준과 수정본 사본에서 G17-R-03 단독 coverage 실행은 각각1 PASS(3.90/3.81초)였다. 파일 전체 진단은 양쪽 모두 총60초 watchdog 시점에 R02의 기존 scan_prefix/manifest 처리 중 종료됐다. 이 진단은 모듈 전체 시간 제한이므로 R02 실패나 G17-R-03 교착의 증거로 세지 않는다. 전체 실행만 12분 넘게 같은 마지막 tmp_path에 머문 상태다. 요청된 “막히면 멈추고 먼저 보고” 절차에 따라 이 세션이 시작한 CI 실행을 Ctrl-C로 중단했다. PID49392의 종료를 확인했으며 다른 세션이나 pane은 조작하지 않았다.

전체 CI 완료 전이므로 **GS04a FIX1 READY는 보류**한다. 판단 요청은 리드/C00의 기존 G17 정체 원인 확인 및 같은 기준 재검증 방식 결정이다. scope 밖 구현·기존 시험 수정은 하지 않았다. Python3.11 matrix, optional-runtime 설치, 04b335행, 실제 서비스/계정/유료 호출/모델/GPU/실제 Credential Manager/Narrator도 미검증이다.

증거는 `scratchpad/codex/p9-out/gs04a-fix1/`의 interrupted.json, start.json, id-audit.json, mutation-verified.json, archive-raw-audit.json, clean-import.json, 원본 CI 단계 JSON/log, hang-{base,fixed,base-file,fixed-file}.{json,log}, frozen-source에 보존한다. 문서는 이전 fd06f8e4…727d347a8 전체 바이트와 r2 prefix를 보존해 덧붙였다. commit/push는 하지 않았다.
