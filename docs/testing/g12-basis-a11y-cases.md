# G12 / G-P12 요약 basis·검토 영역·키보드 근거 탐색 계약안

상태: **C00 계약 승인 대기 — 문서만 작성, 제품 구현·제품 시험·mutation 미실행**. 작성자 w5:p8 Codex. 이번 쓰기 허용은 이 문서 하나다. 아래 API·파일·분모·후보 선택 UI는 제안이며 독립 검토와 최종 통합은 별도다.

## 1. 정본·위험·구현 순서

- 정본은 `v1-gap-plan.md` G-P12/F-SUM01·F-A11Y01, G01B-021·022·068, G01BR-02·09·23, architecture의 근거/revision·UX와 관측, validation E01/E02, product-contracts B11/B13이다. 세 gap은 통합 결정에서 S2다. 실제 Narrator 미검증은 별도 EXTERNAL_GATE이며 자동 UI 시험으로 닫지 않는다.
- 구현은 **G-P02·G-P06·G-P07 push 뒤 C00 시작 신호**로 한다. G-P07이 추가할 content의 사유/계속 버튼·privacy의 탐색·bridge의 상태 읽기 모델을 보존하고 그 최종 tree/hash에서 착수한다.
- `ui/content.py`는 G-P07의 다음 행동과 이번 근거/후보 표시가 겹친다. `ui/privacy.py`·`ui/ai_bridge.py`·`app/ai.py`는 G-P02/P06/P07 이후 직렬로 수정한다. `content/store.py`의 G-P03 version/settings CAS와 화자 게시를 되돌리지 않는다. G-P11a/b가 먼저 같은 app/bridge를 수정했으면 그 DTO·정책/lease 경로 위에 basis 전달과 접근성 연결만 얹는다. 선후 통합은 C00가 정하며 동시에 같은 파일을 쓰지 않는다.
- source 보존·revision 불변·자동 supported 금지·근거 클릭의 외부 URL 실행 금지·동의/비용 정책 자동 완화 금지를 불변식으로 둔다. 후보 선택의 version 경쟁은 S1 성격의 부정 시험으로 보강하지만 이 문서를 원본 사고 관측으로 쓰지 않는다.

## 2. 직접 확인한 현재 경로와 한계

조사 시 HEAD는 `21a58bfa99c3ab4a381b92a092d5981adc5c9632`다. 작업 트리에는 G-P02/G-P04 변경이 섞여 있다. 다음은 소스/기존 시험을 읽은 사실이며 새 실행 증거가 아니다. 과거 보고의 줄 번호를 현재 줄 번호로 재사용하지 않았다.

| 현재 근거 | 직접 확인한 사실 |
| --- | --- |
| `src/recoryn/summarization/adapters.py:44` parse_claims | raw supported 등을 uncertain으로 낮추고, refs 없음은 unsupported/model_inference, 사용자 삽입은 user_assertion, unresolved 참조는 provider basis=model_inference로 만든다. raw JSON basis를 그대로 신뢰하는 경로가 아니다 |
| `src/recoryn/providers/contracts.py:268` SummaryClaim | basis는 transcript/user_assertion/model_inference만 허용한다. unresolved는 이 DTO의 basis 값이 아니다 |
| `src/recoryn/content/models.py` Claim | status는 uncertain/unreviewed/unsupported/disputed/user_assertion/model_inference이며 supported는 자동 DTO에서 거부한다. basis 입력 필드는 없다 |
| `src/recoryn/app/ai.py:537` | SummaryClaim을 Claim(text, refs, status)로 바꾸며 어댑터 결과의 basis를 버린다. checkpoint는 SummaryClaim의 basis를 이미 보존한다 |
| `src/recoryn/content/store.py:535` | refs의 실제 source provenance에서 unresolved > user_assertion > transcript(비어 있지 않은 refs) > model_inference(빈 refs) 순으로 저장 basis를 재계산한다 |
| 같은 파일 `_load`:281, `select_summary`:788 | JSON body/hash·schema_version=1 검사, 불변 body 저장. 기존 명시 선택은 ID CAS이며 version/settings snapshot을 인자로 받지 않는다 |
| `src/recoryn/ui/content.py:93`, `:98`, `_seek`, `_show_summary`, `_claim_clicked` | 검색표는 시간 셀 double click만 seek에 연결한다. claim은 status만 같은 목록에 출력한다. 링크는 원 요약의 transcript revision/segment를 참조하고 setOpenLinks/ExternalLinks=False다. basis 표시·검토 영역·요약 후보 선택 UI가 없다 |
| `src/recoryn/ui/ai_bridge.py` poll/cancel | status QLabel을 갱신하고 취소 요청과 UNKNOWN을 텍스트로 구별한다. 실제 키보드 전 경로·접근성 알림의 관측 증거는 별개다 |
| 설치된 `.venv/Lib/site-packages/PySide6/QtGui.pyi` | QAccessibleAnnouncementEvent와 QAccessible.updateAccessibility 선언이 있다. 선언 확인이지 Narrator가 이를 발화했다는 증거가 아니다 |

G03 검토의 “후보는 API로 선택 가능하나 UI는 없음”은 문서 이력이다. 이번에 기존 `list_revisions(..., "summary")`·`select_summary`와 현재 UI를 대조해 같은 공백을 확인했다. 모델·장치·서버·Narrator를 실행하지 않았다.

## 3. basis 정본과 저장 계약

### 3.1 서로 다른 세 개념

| 필드/개념 | 정본과 허용 값 | 의미 |
| --- | --- | --- |
| `basis` | **저장소가 고정 source revision의 provenance로 재계산**: transcript/user_assertion/unresolved/model_inference | 참조 출처의 구조적 분류. 참조가 있다는 이유로 claim 의미가 지지된다는 뜻은 아님 |
| 신규 `provider_basis` | optional: None 또는 transcript/user_assertion/model_inference | SummaryClaim.basis의 어댑터 결과를 별도 참고로 보존. raw 모델 문자열·사람 검증·권한이 아님 |
| `status` | 기존 content Claim의 6값 유지. 자동 supported 거부 | 의미 검토 상태. unresolved는 status에 넣지 않고 basis로 표현 |

**권고: 재계산을 정본으로 유지하면서 provider_basis도 보존한다.** 둘을 합치거나 provider 값으로 canonical basis를 덮지 않는다. 예: unresolved+user_assertion 혼합 참조를 어댑터가 user_assertion으로 내더라도 canonical basis는 unresolved이고 두 값을 함께 표시한다. audio 참조에 provider_basis=model_inference가 있으면 canonical transcript와 “어댑터: 모델 추론”을 함께 보여 주고 추가 검토 영역으로 보낸다.

| 실제 refs provenance 집합 | 저장 basis |
| --- | --- |
| 빈 집합 | model_inference |
| audio만 | transcript |
| user_assertion 포함, unresolved 없음 | user_assertion |
| unresolved 포함(다른 값과 혼합해도) | unresolved |

알 수 없는 segment ID는 기존 UNKNOWN_CLAIM_SEGMENT/REFERENCE_INVALID 경계에서 전체 해당 결과를 거부한다. 참조가 없는 주장과 존재하지 않는 참조를 정상인 것처럼 합치지 않는다. 원문의 의미 지지 여부를 이 표로 판정하지 않는다.

### 3.2 DTO·앱·저장·이전 revision

- content.Claim의 마지막에 `provider_basis: str | None = None`을 추가한다. 기존 3인자 직접 호출을 보존한다. 명시 bool/알 수 없는 값은 `INVALID_CLAIM_PROVIDER_BASIS`로 거부한다. None은 “어댑터 근거 미기록”이지 transcript라는 기본 추정이 아니다.
- app/ai.py의 결과→Claim 변환은 `provider_basis=item.basis`를 명시 전달한다. complete/partial/후보를 같은 경계로 처리하고 기존 checkpoint 복원 의미와 source revision/hash를 유지한다. 어댑터/외부 JSON schema·provider status 정규화는 바꾸지 않는다.
- `_create_summary`는 기존 canonical basis 산식을 유지하고 새 claim에 provider_basis를 추가한다. Job 완료·revision·선택·event는 기존 publish transaction 안에서 원자화한다. app에서 먼저 complete하고 나중에 metadata를 덧쓰지 않는다.
- 기존 summary body의 schema_version=1에 **선택적인 JSON 필드**를 추가한다. 새 SQL 표·user_version 변경·기존 body/hash 재작성은 없다. 신규 reader는 필드 미존재/None을 미기록으로 표시한다. 현재 구 reader가 부가 JSON 필드를 무시하는 호환과, 새 UI의 정확한 표시 지원은 별개다. 미래 top-level schema는 기존대로 거부한다.
- legacy revision은 원본 bytes/hash를 유지한다. 새 표시 모델은 원 revision refs와 저장 canonical basis를 대조한다. basis가 없으면 현존 원 revision으로 읽기 계산한 출처임을 표시하고 저장하지 않는다. 저장 basis 불일치·잘못된 값·source 읽기 실패는 “근거 확인 불가”/추가 검토, seek0으로 처리하며 자동 정정/지지 배지를 만들지 않는다.
- G-P09 인계: optional claim 필드의 v1 envelope 확장임을 기록하고 backup/import가 기존/신규 body와 hash를 그대로 옮기는지 회귀한다. migration registry 신규 표를 요구하는 변경은 아니다. G-P09 계약/제품 코드는 이번 쓰기 범위 밖이며 해당 인계는 C00가 통합한다.

## 4. 표시·근거 탐색·요약 후보 제안

### 4.1 두 표시 영역과 결정/할 일

claim 종류는 현재 저장된 summary template로 **결정 제안(decisions)/할 일 제안(tasks)/기타(meeting·lecture·key_points)**를 구별한다. 개별 claim에 없는 kind를 문장 추측으로 만들거나 새 모델 호출로 분류하지 않는다. 혼합 회의록의 개별 결정/할 일 구조화는 이번 범위 밖이다.

| 표시 영역 | 분기 조건 | 항상 보이는 설명 |
| --- | --- | --- |
| 전사 참조 요약 | canonical basis=transcript, status=uncertain 또는 unreviewed, provider_basis=None 또는 transcript, 읽기 검증 성공 | “전사 참조 — 의미 지지 미검증”; status·basis·어댑터 미기록/참고값 |
| 추가 검토 필요 | 그 밖의 유효 claim: unresolved/user_assertion/model_inference, unsupported/disputed 등, 어댑터 inference/assertion, source 확인 불가 | “확정된 사실/결정/할 일이 아닙니다”; 원인·각 basis·status·원 revision |
| 게시/정상 표시 금지 | 자동 supported, 불법 status/basis, 없는 refs 등 입력 계약 위반 | 기존 결과 보존+안전 오류. 저장된 손상 행의 열람은 확인 불가로 구별하고 새 정상 claim으로 승격하지 않음 |

두 영역 모두 자동 사실 검증을 약속하지 않는다. decisions/tasks의 제목은 각각 **“결정 제안 — 미확정”/“할 일 제안 — 미확정”**이다. unsupported 결정/할 일을 첫 영역으로 보내거나 확정 목록·승인 완료로 표시하지 않는다. 이번에는 사람 승인·supported 생성·소유자/기한 편집 workflow를 추가하지 않는다.

기존 `claims` QTextBrowser는 전사 참조 영역으로 유지하고 별도 review browser를 추가한다. 각 영역은 제목·개수·accessibleName/description을 가지며 빈 영역도 “0건/해당 없음”을 구별한다. 각 claim은 status, canonical basis, provider 참고/미기록, 고정 revision과 근거 링크를 텍스트로 갖는다. 색상만으로 구분하지 않는다. 0claim은 검증률100%·지지됨으로 표시하지 않고 coverage/partial/누락 안내를 유지한다.

같은 표시 내용의 poll은 setHtml/링크 목록을 다시 만들지 않는다. browser/후보 control에 초점이 있거나 확인/편집 중이면 새 active 알림만 남기고 현재 열람을 유지한다. 실제 표시 revision/세션이 바뀔 때만 view_generation을 갱신한다. 필요 재렌더는 살아 있는 고정 링크 identity로 초점을 보존하고, 단순 focus 복구를 링크 활성화로 취급하지 않는다. K의 Tab/활성화 trace 중간에도 poll을 넣어 다음 키가 뜻하지 않은 새 근거를 실행하지 않는지 확인한다.

### 4.2 안전한 마우스·키보드 근거 이동

- 표의 시간 셀은 **Enter/Space/기존 double click**을 하나의 seek 명령으로 연결한다. 한 입력에 signal1회, 방향키는 행/셀 이동만, Tab/Shift+Tab은 정해진 위젯 순서 이동만 한다. 편집 셀·IME/편집 중·dirty/pending 편집은 Enter/Space를 seek로 가로채지 않는다. 필터로 숨긴 행·없는 행·세션이 바뀐 옛 target은 seek0이다.
- claim browser는 키보드 링크 탐색을 명시 활성화한다. Tab/Shift+Tab으로 링크 진입/탈출, Enter와 **링크에 초점이 있을 때만 Space**로 같은 내부 명령을 실행한다. 방향키/비링크 Space는 native 이동/스크롤이며 재생하지 않는다. Qt 기본 동작만으로 통과를 추정하지 않고 실제 키 입력을 시험한다.
- 링크 target은 현재 화면 인덱스가 아니라 `(session, summary_revision, transcript_revision, segment_id, view_generation)`에 고정한다. 원 revision을 다시 읽어 검증하고 current active 전사로 refs를 바꾸지 않는다. 내부 opaque ID 외의 URL/잘못된 key는 무시한다. HTML text/status/label은 escape하고 외부 링크 열기는 계속 차단한다.
- canonical basis가 audio 참조를 포함해도 해당 segment의 provenance=audio, timing_quality!=unverified와 기존 source/derived 무결성 검사가 통과해야 seek한다. user_assertion/unresolved 참조는 원문만 보여 주고 “발화 위치 미확인”을 알린다. 유효 audio 혼합 참조만 해당 개별 근거로 이동 가능하며 claim 전체가 의미 지지됨으로 승격되지 않는다.
- dirty/IME/pending 편집 중 근거 이동은 입력을 버리거나 자동 저장하지 않고 “편집 저장 후 이동”을 표시한다. 저장 재시도는 기존 명시 동작을 쓴다. 정상 이동은 요청한 표의 시간 셀로 초점을 옮기고 실패는 원 링크에 둔다. 원 전사를 열람해도 active selection은 바꾸지 않는다.

### 4.3 요약 후보 선택 UI는 이번 단위에 포함 권고

G-P03에서 수용한 늦은 결과/중복 요청의 후보를 사용자가 고를 진입점이 없으므로 **포함을 제안**한다. 후보 콤보·“이 요약 선택” 버튼을 추가하고 **열람과 선택을 분리**한다. poll/목록 갱신/방향키로 열람하는 것은 선택 쓰기0이다. 선택됨/후보·부분/이전 전사·이전 설정/비교 불명·source revision을 표시한다. 처음 active가 없으면 임의 첫 항목을 active처럼 표시하지 않는다.

부분 결과는 열람·근거 탐색만 허용하고 전체 요약 선택 버튼은 비활성이다. complete인 이전 전사/설정 후보는 미확정/오래됨 안내를 유지하면서 명시 선택할 수 있다. 선택은 **항상 확인 창**, 기본/초기 초점 No·Esc 취소이며 이전 전사/설정임을 추가 고지한다. 선택해도 전사 active·요청 설정 키·옛 Job 결과/상태를 바꾸지 않는다.

기존 `select_summary(..., expected_active=...)`는 호환을 유지한다. 신규 제품 UI는 다음 **필수 snapshot API**만 쓴다.

```text
SummarySelectionExpectation(
  session_id, transcript_id, transcript_version,
  summary_id, summary_version, summary_settings_key
)  # 모든 필드 필수, 관측된 빈 ID/key는 None, version은 bool 아닌 비음수 int

select_summary_candidate(session_id, revision_id, *,
  expected: SummarySelectionExpectation, allow_outdated: bool = False) -> bool
```

snapshot은 목록/버튼을 제시할 때 `selection_state`에서 캡처한다. 확인 창 직전/직후에 새 값을 읽어 사용자의 기대값을 조용히 대체하지 않는다. transaction 안에서 현재 전사/요약의 **ID+두 version+요청 설정 키** 모두 비교한다. 같은 ID로 돌아온 ABA·확인 중 설정 변경도 False/선택 불변·재조회 후 재선택이다. stale 화면의 자동 CAS 재시도는 없다.

타 세션·삭제 intent/tombstone·불완전 후보는 거부한다. 이전 전사/설정/키 비교 불명 후보는 `allow_outdated=True`가 필요하며 UI의 명시 Yes 이후에만 전달한다. 정상 재선택도 기존과 같이 summary_version+1·선택 event1건으로 사용자 의도를 기록한다. target body/hash·requested settings는 불변이다. Job 게시가 뒤늦게 오면 G-P03 CAS로 후보가 된다. DB 실패는 selection/event 모두 롤백한다.

“현재”는 target의 source transcript ID가 snapshot의 transcript ID와 같고, target settings_key와 snapshot의 summary_settings_key가 **둘 다 기록돼 있으며 같은 값**일 때다. 그 밖에는 이전 전사/설정 또는 비교 불명으로 안내한다. 두 key가 None인 legacy도 검증된 현재 설정으로 추정하지 않고 allow_outdated 확인을 요구한다. 이 표시 분류와 별개로 CAS에서는 **None도 정확한 관측 값으로 비교**하므로 확인 중 None→새 key가 되면 선택을 거부한다.

UI는 브라우징 중인 후보를 poll 뒤에도 유지한다. 새 active가 생겼다는 이유로 확인/열람 중 화면을 덮지 않는다. 세션 변경/삭제 뒤 옛 callback은 새 화면이나 새 선택을 바꾸지 않는다. 오류는 재조회·재선택 안내이며 기존 결과는 유지한다.

## 5. 거부·철회·대기 취소·접근성 알림

### 5.1 조작과 초점

신규 `ui/a11y.py`는 키 활성화·약한 opener 참조·접근성 알림의 공통 adapter다. grant/cap/Job을 스스로 변경하지 않고, 검증한 기존 UI 명령을 호출한다. 표 편집·브라우저 스크롤과 전역 단축키를 가로채지 않는다.

| 동작 | 키보드 계약과 부수효과 |
| --- | --- |
| 동의/일반 모드 위험 확인의 거부 | Tab/방향키로 No, Enter/Space로 거부, Esc도 No/취소. Yes 기본 금지. 거부는 새 허가·모드 변경0이며 이미 있는 다른 범위 grant를 암묵 철회하지 않음 |
| 철회 | 해당 기능/범위의 명시 버튼으로 Tab 도달, Enter/Space1회로 기존 G-P02 철회. 철회 영속화/이미 handoff한 원격 결과를 각각 표시. 알림만으로 grant 발급 금지 |
| 예산/권한 대기 취소 | G-P07의 대기/작업 취소 명령으로 연결. Enter/Space1회. cap 증액·일반 모드 전환·재전송을 취소 동작에 섞지 않음. 준비 미접수 취소와 기존 Job 취소 구별 |
| CPU 전환 거부 | 기존 정책 control에서 GPU_ONLY를 키보드로 명시 유지/선택. 안내 닫기나 초점 이동을 CPU 허용으로 취급하지 않음. G-P11의 REMOTE 적용 제외/Ollama 정책 안내가 있으면 그대로 보존 |

확인 창 뒤에는 같은 세션/요청의 opener가 살아 있고 visible/enabled이며 사용자가 이후 다른 위치로 옮기지 않았을 때만 복귀한다. 그렇지 않으면 현재 패널의 안전한 탐색 위치로 복귀하거나 새 사용자 초점을 유지한다. 파괴된 QWidget을 접근하지 않는다. 늦은 task 완료·poll은 초점을 빼앗지 않는다. Tab 순서는 명시하되 숨김/비활성 widget을 건너뛰고 두 browser와 모달에서 trap이 없어야 한다.

### 5.2 접근성 이름과 동적 상태

표/근거 링크/두 영역/요약 후보/선택/거부·철회·취소 버튼/템플릿·정책 control은 목적을 알 수 있는 accessibleName과 필요한 description을 가진다. 링크는 “근거 1”만 읽지 않고 원 전사 version/시간·트랙·원문 보기 또는 재생 가능 여부를 식별한다. claim 텍스트는 화면에 표시하되 네트워크 URL·임의 오류 본문·비밀을 접근성 상태 메시지에 추가하지 않는다.

QAccessibleAnnouncementEvent와 updateAccessibility를 GUI thread의 주입 가능한 adapter로 사용한다. 메시지·대상·politeness를 시험에서 관측한다. 일반 진행은 polite, 중요한 차단/UNKNOWN은 assertive를 제안한다. 현재 설치 binding의 선언을 확인했지만 실제 OS 발화는 외부 게이트다. 모델 thread에서 Qt 객체를 직접 만지지 않는다.

알림 key는 session/view generation+Job/event version+상태 종류다. 같은 poll은 재알림0, 새 의미 변화만1회, 세대가 지난 callback은0회다. “입력 수신”, “정책 영속화”, “취소 요청”, “로컬 종료 ACK”, “원격 결과/비용 UNKNOWN”을 서로 다른 사실로 알린다. 로컬 ACK만으로 원격 취소 완료를 발화하지 않는다. 상태 읽기/알림이 작업 재개·본문 송신·vault 쓰기를 일으키지 않는다.

## 6. 경우의 수·독립 oracle·계층

### 6.1 유한 대표 분모

계획은 **12 family, 2,232 의미 행**이다. pytest node 수와 다르며 family별 Ω=F를 아래에 정한다. 거부/무관 축도 제거하지 않는다. 소멸/숨김 widget은 과거 target의 지연 명령을 현재 살아 있는 dispatcher에 전달하는 fixture다. 파괴된 QObject에 QTest.keyClick을 직접 호출하는 불가능/위험 fixture를 만들지 않는다.

| family / ID | 입력 Ω=F | 행 | 주 계층/독립 기대 |
| --- | --- | ---: | --- |
| B / G12-B-001…768 | claim종류3 × provider_basis{미기록,transcript,user_assertion,model_inference}4 × refs provenance 집합8 × 입력status8 | 768 | unit/표시 모델. canonical 표·추가 검토 분기·자동 supported/불법status 거부 |
| W / G12-W-001…140 | raw status7 × refs종류5 × raw basis{미기록,transcript,user_assertion,model_inference}4 | 140 | parser 계약. supported는 uncertain, 없는 refs는 전체 거부, raw basis로 정본 승격0 |
| P / G12-P-001…288 | provider_basis3 × source canonical4 × template종류3 × complete/partial2 × 결과순서{정상,선택ABA,취소먼저,삭제먼저}4 | 288 | 실제 SQLite+fake provider. 전달/후보/원자 게시/원본·선택 불변 |
| K / G12-K-001…240 | key{Tab,Enter,Space,방향키}4 × widget{시간표,claim링크,거부,철회,대기취소}5 × target상태4 × source target3 | 240 | Qt/dispatcher. 동작별 signal 수·키 의미·유효 target·쓰기/seek 여부 |
| E / G12-E-01…64 | key4 × 편집중2 × column{시간,편집문장}2 × filter{해당행표시,숨김,모두숨김,빈표}4 | 64 | Qt. 편집/IME 보존·숨김 seek0·활성화 중복0 |
| F / G12-F-001…144 | modal{LIBRARY동의,일반모드위험,요약선택}3 × exit{No,Esc,Yes}3 × opener상태4 × 이후사용자초점이동2 × 완료즉시/지연2 | 144 | Qt/fake store. 기본 거부·명시 Yes만 허용·초점 복귀/유지 |
| N / G12-N-01…64 | 상태종류8 × 동일poll/새version2 × 초점현재/다른위치2 × 현재/옛generation2 | 64 | 순수 model+Qt event adapter. 중복0·필요 알림1·초점 탈취0 |
| C / G12-C-001…360 | 후보목록{없음,하나,여럿}3 × target상태4 × 선택경쟁5 × 확인{Yes,No,Esc}3 × 같은/바뀐세션2 | 360 | Qt+store. 열람/선택 구분·현재 snapshot CAS·기본 취소 |
| R / G12-R-01…36 | 후보목록3 × active추종/후보열람2 × poll{불변,새요약,세션변경}3 × 미저장편집2 | 36 | Qt. 브라우징·검색/편집 유지·수동 선택 전 쓰기0 |
| D / G12-D-01…96 | CAS상황6 × target상태4 × allow_outdated2 × 삭제의도유무2 | 96 | SQLite 두 연결. 새 API 직접 호출도 우회 불가·event/버전 원자화 |
| T / G12-T-01…24 | §6.3 named24 | 24 | 타입/HTML/호환/실패·취소 경계 |
| Z / G12-Z-01…08 | 전사 empty/nonempty2 × 요약complete/partial2 × legacy미기록/새빈claims2 | 8 | unit/UI. 무주장·부분·coverage, 검증률/지지 거짓표시0 |
| **합계** | 768+140+288+240+64+144+64+360+36+96+24+8 | **2,232** | 계획, 실행0 |

B의 provenance8은 빈집합/audio/user_assertion/unresolved/audio+user_assertion/audio+unresolved/user_assertion+unresolved/셋모두다. 입력status8은 기존6값+supported+unresolved(잘못된 status)다. Claim 종류3은 decisions/tasks/기타이며 출력 영역은 §4.1 표의 **전사 참조/추가 검토/입력 거부**로 독립 계산한다. 영역을 임의 입력으로 줘 정상 표에 맞추는 oracle는 금지한다.

W의 raw status7은 미기록/uncertain/unsupported/disputed/user_assertion/supported/미등록값이다. refs5는 audio/빈값/user_assertion/unresolved/없는ID다. provider basis는 이 raw basis의 단순 복사가 아니라 기존 어댑터 정규화 결과라는 차이를 확인한다. B의 direct DTO supported 거부와 W의 raw supported→uncertain은 서로 다른 경계다.

K의 target상태4는 enabled/disabled/hidden/destroyed이며 source target3은 검증audio/사용자텍스트/없거나잘못된target이다. 버튼은 source 축과 무관한 독립 부수효과 불변을 검사한다. 표의 방향키는 행 선택, 링크의 방향키는 native 이동/스크롤, Tab은 이동이고 Enter/Space만 유효한 명령을 활성화한다. 각 key는 press/release 한 쌍을 한 입력으로 센다. Shift+Tab은 Tab 행의 역방향 trace이며 별도 행으로 중복 합산하지 않는다.

F의 opener4는 유효/비활성/파괴/세션변경이다. N의 상태8은 준비차단/queued/running/취소요청/로컬ACK/REMOTE_UNKNOWN/철회영속화/선택충돌이다. source text가 아닌 손으로 고정한 안전 문구/상태 토큰과 이벤트 수로 대조한다.

C/D의 target4는 complete현재/complete이전전사/complete이전설정/partial이다. C 경쟁5는 불변/요약ID변경/요약ABA/전사ABA/설정키변경이다. D CAS6은 불변/요약ID변경/요약ABA/전사ID변경/전사ABA/설정키변경이다. 없는 후보의 옛 Yes callback도 정상 선택으로 처리하지 않는 거부 행이다. 같은 ID를 다시 선택하면 version이 증가하는 사건도 ABA prefix로 구성한다.

### 6.2 독립 expected·상태열·경쟁

canonical 표·표시 분기·Tab/명령 계약은 손으로 쓴 고정 expected다. 제품의 basis 함수·UI renderer·provider parser·CAS helper를 expected에 import하지 않는다. 예문은 “논의했다”를 “확정했다”로 표시하지 않고, 사용자 삽입·미해결·무근거 주장과 audio refs를 구별하는 비민감 고정 문자열이다. 실제 의미 지지 정확도 평가 corpus나 사람이 붙인 supported 라벨을 새로 확보했다는 뜻은 아니다.

고정 revision/segment/time/track을 가진 source fixture와 두 SQLite 연결을 쓴다. fake player는 최종 `(track,time,revision)`과 호출 수만 기록한다. fake transport/vault/ledger는 UI 열람/키 이동/No/Esc/알림 시 호출0이며 승인 테스트도 실제 계정·vault 쓰기는 없다. claim 이동은 기존 playback 무결성 검사에 연결되는지 fake reader/player seam으로 확인한다.

P/C/D에서 목록 snapshot A → 확인 창 → 경쟁 B → 명시 선택/게시 A의 선형화와 반대 순서를 barrier/Event로 고정한다. 확인→선택 transaction, 취소/삭제→publish, 요약 선택→늦은 publish, 세션 변경→callback 모두 양쪽 순서를 관련 행의 trace로 수행한다. 파생 trace 수를 추가 의미 행으로 더하지 않는다. 정상 상태열도 `열람→Tab→활성화→원 revision 표시→다시 poll`, `거부→재시도 없이 유지`, `철회→취소요청→로컬ACK→UNKNOWN유지`로 검증한다. bound 밖 모든 GUI 이력을 전수 증명한다고 쓰지 않는다.

### 6.3 명명 부정/경계24행

T01 provider_basis=True / T02 미등록 provider_basis / T03 legacy provider_basis 미존재 / T04 stored canonical basis 불일치 / T05 미래 revision schema / T06 claim HTML/script escape / T07 외부 URL anchor / T08 옛 view generation link / T09 삭제된 source / T10 source 읽기·checksum 실패 / T11 사용자 삽입 시간 있음에도 seek 금지 / T12 audio timing_quality=unverified / T13 혼합 refs 중 audio만 개별 seek / T14 dirty 편집 중 link 이동 금지 / T15 IME 중 Space 입력 보존 / T16 Enter 기본+custom 중복 활성화 금지 / T17 빈 링크 목록 Tab 탈출 / T18 expectation version=True / T19 expectation 음수 version / T20 allow_outdated 비bool / T21 selection event 쓰기 실패→버전/선택 전부 롤백 / T22 worker thread 알림→GUI thread 전달 / T23 취소요청만 있고 ACK 없음→완료 알림0 / T24 None settings key를 관측 빈값으로 비교(검사 생략 금지).

각 family의 tuple/ID 목록과 실제 assertion 실행 ID를 별도 산출해 missing/duplicate/extra=0을 감사한다. 같은 의미 행의 unit/UI assertion을 두 번 더하지 않는다. pytest node·순수 행·Qt trace·mutation·실제 Narrator 미실행을 각각 보고한다.

## 7. 기존 시험과의 관계·신규 계층

| 실제 존재하는 기존 node/범위 | 유지/추가 확인 |
| --- | --- |
| `tests/unit/test_content.py::test_missing_and_non_audio_evidence_are_distinguished` | unresolved/model_inference canonical 구별을 유지하고 B로 혼합 provenance·provider 참고를 확장 |
| 같은 파일 `test_summary_is_pinned_stale_and_late_summary_cannot_replace`, `test_history_selection_cas_and_session` | 고정 source·stale·기존 ID CAS 호환. 새 필수 expectation API의 version/key 경쟁은 D에서 별도 검증 |
| 같은 파일 `test_atomic_summary_and_incomplete_source`, `test_atomic_cancel_completion_orders`, `test_delete_cascades_and_pending_intent_blocks_reads_and_writes` | partial·취소·삭제의 게시 보호 유지. 새 metadata가 transaction 밖으로 새지 않음 |
| `tests/unit/test_providers.py::test_context_only_claims_and_unresolved_basis`, `::test_invalid_refs_block_whole_core_and_never_mark_supported`, `::test_resume_cannot_promote_cached_claim_evidence` | provider의 unresolved→model_inference와 checkpoint 재개 정규화를 그대로 유지. B/W는 이를 canonical와 합치지 않음 |
| `tests/contract/test_provider_contracts.py::test_model_supported_label_is_not_human_evidence` | raw supported→uncertain. provider_basis 추가가 supported 허용 경로가 되지 않음 |
| `tests/ui/test_content_ui.py::test_refresh_preserves_browsed_revision_filter_and_selection`, `::test_busy_ai_cannot_discard_unsaved_edit_on_next_refresh` | 전사 열람/검색/dirty 입력 보존. R과 T14/T15로 새 summary browser/링크와 교차 |
| `tests/ui/test_live_ui.py::test_playback_verifies_derived_and_original_hashes_before_player` | 실제 재생 검증 경로 유지. 새 키보드가 player를 직접 호출하지 않음 |
| `tests/e2e/test_ai_workflow.py::test_cancel_revokes_publication_even_when_model_ignores_cancel` | 취소 무시 결과도 미게시. 이 시험만으로 키보드 취소·발화 완료를 검증했다고 하지 않음 |
| `tests/integration/test_selection_version_cas.py`, G-P02/P06/P07 시험 | G-P03 게시/설정 보호·동의 범위·비용·BLOCKED/UNKNOWN/다음 행동을 회귀. 새 UI가 완화하지 않음 |

새4파일은 다음과 같다. 생성 ID 집합과 독립 산술 감사를 구별하며, 공통 expected를 제품 함수에서 가져오지 않는다. 대형 B cube는 순수 모델로 batching하고 모든 행마다 QApplication/process를 새로 만들지 않는다. 실제 키 press/release·초점·modal·Qt 접근성 전달은 UI 계층에서 검증한다.

| 신규 파일 | 담당 의미 행/실행 |
| --- | --- |
| `tests/unit/test_claim_basis.py` | B/W/Z와 T의 데이터/HTML/타입 oracle. legacy bytes/hash 보존 |
| `tests/property/test_basis_a11y_case_space.py` | 전체 family의 독립 분모/ID 감사, N의 알림 상태 모델, claim/ref 재배열 시 정본 불변·반복 열람 쓰기0 속성 |
| `tests/integration/test_basis_publication.py` | P/D와 publication/candidate transaction·원본 hash·새 API 직접 호출/장애 주입 |
| `tests/ui/test_basis_a11y_ui.py` | K/E/F/N/C/R, B/Z의 실제 두 영역 표시·고정 revision 탐색, 관련 T. fake player/transport·키보드·접근성 adapter 기록 |

N·B처럼 여러 계층에 걸치는 행은 ID를 같은 의미 assertion에 연결한다. 전체 의미 행의 합집합이2,232인지 감사하고 각 계층에서 같은 ID를 다시 확인한 횟수를 의미 행 수에 더하지 않는다. 실제 node/trace 개수는 구현 후 따로 기록한다. 속성 시험의 seed/bound·재현 최소 예·race barrier 순서도 구현 증거에 남긴다.

## 8. mutation 계획

계획 **24개, 실행0**이다. 정상본 PASS 뒤 pyproject/src/tests/scripts/packaging을 함께 복사한 OS TEMP 사본에서 하나씩 변이한다. cwd/pythonpath/import origin과 원본/변이 hash를 확인한다. 목표 assertion FAIL만 검출이며 수집/import/권한/timeout은 invalid다. survived/invalid를 숨기거나 단순 mutant 수를 전체 결함 coverage라고 부르지 않는다.

| ID | 결함 | 독립 검출 목표 |
| --- | --- | --- |
| M01 | app의 provider_basis 전달 제거 | P의 저장 참고값·legacy None 구별 |
| M02 | canonical basis를 provider 값으로 대체 | B/P의 unresolved/혼합 refs 정본 |
| M03 | unresolved보다 user_assertion을 우선 | B의 혼합 집합 고정 표 |
| M04 | 빈 refs를 transcript로 저장 | B/Z의 추론/무주장 구별 |
| M05 | 자동 Claim에 supported 허용 | B/T 입력 거부·확정 배지0 |
| M06 | unsupported 결정/할 일을 일반 영역으로 표시 | B의 결정/할 일 추가 검토 제목 |
| M07 | provider inference/assertion의 검토 분기 제거 | B의 canonical transcript+provider inference |
| M08 | claim HTML escape 제거 | T06 외부 실행/해석0·문자열 보존 |
| M09 | claim refs를 현재 active 전사로 연결 | P/K의 고정 원 revision/time |
| M10 | nonaudio/unverified seek 보호 제거 | K/T11/T12 재생0 |
| M11 | 시간 셀 Enter/Space 연결 제거 | K의 유효 audio signal1 |
| M12 | custom 활성화 뒤 기본 이벤트도 실행 | E/T16 단일 signal·단일 선택 |
| M13 | claim 링크 Space 활성화 제거 | K 실제 key Space의 내부 이동1 |
| M14 | 방향키만으로 seek 실행 | K/E 이동 중 재생0 |
| M15 | 숨김/옛 행 target 검증 제거 | K/E의 숨김 target seek0 |
| M16 | 늦은 modal 완료가 무조건 opener focus | F의 새 초점/세션 보존 |
| M17 | Esc를 Yes로 처리 | F의 허가/선택 쓰기0 |
| M18 | 일반 모드 위험 확인 No를 허용으로 처리 | F의 예산 모드 불변·전송0 |
| M19 | 철회/대기 취소의 키 명령 연결 제거 | K의 명시 취소/철회1회·과도한 부수효과0 |
| M20 | 같은 poll의 상태 알림 반복 | N의 동일 version 알림0 |
| M21 | 로컬 ACK를 원격 취소 완료로 알림 | N/T23의 UNKNOWN/ACK 분리 |
| M22 | 후보 선택의 summary version 검사 제거 | D/C의 요약 ABA 거부 |
| M23 | 선택 commit 직전 expected를 현재 값으로 교체 | D/C의 전사/설정 경쟁·옛 기대값 보존 |
| M24 | 후보 열람/poll에서 active 자동 선택 | R의 pointer/version/event 쓰기0 |

## 9. 정확한 후속 쓰기 범위와 대안

제안은 **13파일 = source8 + 신규 시험4 + 이 문서1**이다. 현재 허용은 이 문서 하나이며 제품 쓰기는 계약 승인/시작 신호 뒤다. 기존 시험 파일은 수정 범위에 포함하지 않는다. 실제 실패 때문에 추가 fixture/기존 시험 변경이 필요하면 실패 node·원인·최소 파일을 먼저 보고한다.

| 구분 | 정확한 파일 | 변경 |
| --- | --- | --- |
| content3 | `src/recoryn/content/models.py`, `src/recoryn/content/store.py`, `src/recoryn/content/__init__.py` | optional provider_basis·canonical 보존·읽기 검증·필수 expectation DTO/후보 선택 transaction·export |
| app1 | `src/recoryn/app/ai.py` | 결과 basis 명시 전달만. G-P02/P06/P07/G11의 요청/자원/게시 흐름 유지 |
| UI 기존3 | `src/recoryn/ui/content.py`, `src/recoryn/ui/privacy.py`, `src/recoryn/ui/ai_bridge.py` | 두 영역·후보·키보드/초점·안전 알림·기존 명령 연결 |
| UI 신규1 | `src/recoryn/ui/a11y.py` | GUI thread 알림/세대·약한 opener·키 활성화 공통 adapter |
| 신규 시험4 | `tests/unit/test_claim_basis.py`, `tests/property/test_basis_a11y_case_space.py`, `tests/integration/test_basis_publication.py`, `tests/ui/test_basis_a11y_ui.py` | §7의 독립 oracle/계층 |
| 문서1 | `docs/testing/g12-basis-a11y-cases.md` | 실제 파일/hash·case/node·시험·mutation·NOT_RUN·리뷰 결과 |

ui/main.py·app/status.py·jobs·security·provider/summarization 어댑터·storage·CLI·export 본체·공용 설정은 범위 밖이다. G-P07 status 읽기 모델은 입력으로 사용하며 그 의미를 다시 정의하지 않는다. AIBridge가 이미 소유한 device policy control의 접근성 이름/기존 설정 탐색 연결은 bridge에서 처리하고 MainWindow의 녹음/삭제 상태를 바꾸지 않는다. source PCM/시간·Claim text·전사 편집 의미·동의/예산 schema는 변경하지 않는다.

새 후보 선택의 expectation 타입/flag 오류는 ValidationError, 불완전/미확인 오래됨 선택은 안전한 로컬 오류로 반환한다. 예시 코드는 `INVALID_SUMMARY_SELECTION_EXPECTATION`, `CONTENT_SUMMARY_NOT_COMPLETE`, `CONTENT_SUMMARY_OUTDATED_CONFIRMATION_REQUIRED`다. stale CAS 자체는 False다. 읽기 basis 불일치는 `CONTENT_CLAIM_BASIS_MISMATCH`로 검토 표시/seek0이다. 이들은 수동 UI/읽기 오류이며 새 Job BLOCKED 사유 표를 확장하지 않는다. provider 결과 입력 오류는 기존 FAILED·게시 롤백 계약을 유지한다.

| 대안 | 장점 | 한계/권고 |
| --- | --- | --- |
| 재계산 basis만 문서화/표시 | 가장 작은 변경, 기존 정본 그대로 | 어댑터 inference 의도가 다시 버려짐. 별도 provider_basis 보존 권고 |
| provider basis를 저장 정본으로 사용 | 경계 간 값 동일 | unresolved 정본 손실·source와 모순. 채택하지 않음 |
| 모든 자동 claim을 하나의 검토 목록에 배치 | 과장 가능성 작음 | unsupported 결정/할 일과 source 출처의 차이를 찾기 어려움. 두 영역+모두 미검증 문구 권고 |
| 사람 승인/supported workflow까지 추가 | 검토 완료 상태 제공 | actor·근거 변경·재검토·권한 계약이 추가 필요. 이번 범위에서 제외 |
| 후보 UI를 계속 후속으로 미룸 | CAS API 변경 최소 | G-P03의 보존 후보를 UI에서 고를 수 없음. 이번 포함 권고 |
| 기존 ID CAS를 후보 UI에서 재사용 | API 추가 없음 | 확인 창의 ABA/설정 경쟁을 놓침. 신규 필수 snapshot API 권고 |
| accessibleName만 설정 | 간단함 | 동적 상태/키보드/초점·Narrator 증거 부족. 실제 Qt 이벤트와 외부 수동 게이트 병행 |

## 10. 수락·외부 게이트·승인 요청

제품 시험은 기존 offscreen·bytecode 비활성·`-p no:cacheprovider`·OS TEMP 고유 basetemp로 선택 실행한다. 실제 음성/모델/네트워크/다운로드/계정/vault 쓰기는 없다. 신규4파일 정상본 PASS, skip0, 전체2,232 ID missing/duplicate/extra=0, mutation24개 정상/변이/invalid 구분, ruff check/format check·`python -m mypy src/recoryn scripts packaging`을 게이트로 둔다.

신규4파일 **합계60초 초과 시 축약 전에** 측정값·느린 family/node·행 보존 batching/fixture 개선안과 필요한 경우 축약안을 C00에게 보고한다. 오래된 테스트의 기대값을 무조건 완화해 시간을 맞추지 않는다. 키 입력/초점/UI 상태 시험을 순수 handler 호출만으로 대체하지 않는다.

회귀는 기존 content/provider 계약·G-P03의 selection version 통합·G-P02 동의/철회·G-P06 비용/일반 모드 위험 확인·G-P07 BLOCKED/계속/취소·tests/ui 전체와 AI workflow를 포함한다. G-P11이 선행했다면 그 정책/자원 시험도 포함한다. 가능한 경우 선행 HEAD+배정 파일만 담은 TEMP 사본 전체 오프라인 회귀를 한 번 수행한다. 원본 hash·자동 supported0·외부 URL 실행0·No/Esc 허가0·숨김/옛 target seek0·자동 후보 선택0을 별도 확인한다.

**Narrator 실사용은 NOT_RUN/외부 게이트**다. 후속 사용자 조작 검증에서 두 claim 영역/근거 읽기 순서·링크 Space/Enter·거부/철회·CPU 거부·예산 대기 취소·UNKNOWN/로컬ACK 구분·모달 초점 복귀·Tab trap을 실제 Windows/Narrator 버전과 발화/초점 기록으로 확인해야 한다. Qt 이벤트 방출/accessibleName 검사는 그 전제이며 실제 발화·읽기 품질 승인과 다르다. 이 문서 단계에서 OS 설정/보조기술 실행을 하지 않는다.

C00 승인 요청은 (a) canonical 재계산 유지+optional provider_basis 참고 보존/legacy 불변, (b) 두 검토 영역과 자동 supported·확정 결정/할 일 금지, (c) 실제 키/초점/GUI 알림 adapter·권한/취소 경계, (d) 요약 후보 UI 이번 포함과 신규 필수 expectation CAS API, (e) 13파일·2,232행·mutation24·회귀/60초/외부 Narrator 게이트다. 제품 코드·제품 시험·mutation은 아직 실행0이며 승인 뒤에도 별도 시작 신호를 기다린다.

## §개정 요청(0d846d6·G-P07 계약 반영)

### 대조 기준과 수행 범위

2026-11-24 C00의 읽기 위주 재대조 배정에 따른 **계약 개정 요청**이다. 작성자는 w5:p7 Claude다. 앞의 승인 원문 274행(LF SHA-256 `7ca21b8fc3c12d9ff2ebcf6153070ca757d558ed944b4599deedb65f3385314f`)은 한 바이트도 바꾸지 않았다. 원문의 "승인 대기" 표현은 당시 이력이다. 아래 추가 사항은 기존 승인과 구별하여 다시 결정받는다.

- 코드 근거: `git show 0d846d6:<경로>`로 읽었다. 0d846d6에는 G-P03 선택 version CAS, G-P04, G-P05·05b, G-P06·06b가 들어 있다.
- G-P07 근거: 작업 트리의 미추적 계약 `docs/testing/g07-blocked-reason-cases.md`(읽은 판 LF SHA-256 `ad1d16296e673a6e8f9bbe228d52d9f81a9b55cbaf9a73661167a7c8adb5f57c`, 624행)를 대조했다. 원문, §개정 요청(110코드·5종 사유·암묵 resume 금지), 착수·중간 기록, C00 범위 결정 절을 포함한다.
- 쓰지 않은 근거: 작업 트리 src의 미완성 G-P07 변경과 미푸시 G-P15 변경은 근거로 쓰지 않았다.
- 아래 `파일:행`은 0d846d6 객체의 줄번호다.
- 직접 한 일: 소스와 시험 소스 읽기, 원문이 인용한 기존 시험 node 14개의 존재 확인, 신규 4파일 이름의 충돌 확인, 분모 산술. **시험·mutation·정적 검사는 실행하지 않았다.**

### 1. G-P03 실제 API·content store와의 대조

| 원문 가정 | 0d846d6에서 직접 확인한 사실 | 판정·개정 요청 |
| --- | --- | --- |
| 후보 선택 snapshot의 6필드(§4.3) | `content/store.py:253-266` `selection_state`가 session_id, transcript_id, transcript_version, summary_id, summary_version, summary_settings_key를 한 번에 읽는다. version은 `content_selections`(149-150행)의 열이고, settings key는 `content_summary_requests`(247-251행)의 최근 요청값이다 | 원문의 `SummarySelectionExpectation` 필드와 정확히 같다. 이 dict에서 캡처한다는 원문을 유지한다 |
| 기존 명시 선택은 ID CAS(§2) | `select_summary`(788행)는 `_select`(756-781행)를 부른다. 활성 ID만 비교하고, 성공하면 `summary_version+1`과 선택 event 1건을 같은 transaction에 쓴다. version·settings 인자는 없다 | 원문 사실이 그대로다. 새 필수 expectation API가 계속 필요하다 |
| Job 게시의 version/settings CAS | `publish_summary`(673행~)는 expected_transcript_version·expected_summary_version·settings_key를 받는다. `_create_summary`의 선택 조건(551-571행)은 세 값과 활성 ID를 모두 본다. settings_key는 body의 선택 필드다(583-584행) | 원문의 "늦은 게시는 G-P03 CAS로 후보" 판단과 일치한다. 직접 API `create_summary`(793행)는 settings_key가 없다. 그래서 원문 §4.3의 legacy None 분류가 실제로 생긴다 |
| canonical basis 재계산(§3.1) | `_create_summary` 535-543행의 우선순위는 unresolved > user_assertion > transcript(비지 않은 refs) > model_inference다. 저장 dict는 text·segment_ids·status·basis 4개다 | 원문과 같다. 줄번호도 같다 |
| content Claim·provider DTO | `content/models.py`의 Claim은 text·segment_ids·status 3필드, status 6값이다. `providers/contracts.py:270-292`의 SummaryClaim은 basis 3값에 **status 4값**(uncertain/unsupported/disputed/user_assertion)이다 | provider_basis는 3값으로 충분하다. provider status가 content status보다 좁다는 점은 W의 정규화 행에서 그대로 확인한다. 분모 변화는 없다 |
| 파서 정규화(§2·§3.1 예) | `summarization/adapters.py:44-83` `parse_claims`의 동작: raw supported 등은 uncertain이 된다. 빈 refs는 unsupported/model_inference다. user_assertion 참조를 unresolved보다 먼저 판정한다. unresolved만 있으면 provider basis가 model_inference다 | 원문 §3.1 예("unresolved+user_assertion 혼합을 어댑터는 user_assertion")와 일치한다 |
| 결과→Claim에서 basis 소실(§2) | `app/ai.py:538`이 `Claim(item.text, item.segment_ids, item.status)`로 바꾼다(원문 :537 → :538). checkpoint 복원(482-491행)과 `_claim_dict`(adapters 324-330행)는 basis를 보존한다 | 원문 그대로다. 변경 지점은 538행 하나다 |
| 삭제 intent·tombstone 후보 거부(§4.3) | `ContentStore._live`(208-226행)는 `library.get_session`과 DB의 deleted_sessions·sessions를 함께 본다. `library.get_session`은 journal 의도까지 본다 | 기존 경로로 거부된다. 다만 먼저 걸리는 오류가 Library의 `Session has a deletion intent`일 수도, `CONTENT_SESSION_DELETED`/`MISSING`일 수도 있다. **D의 기대는 "거부·선택/version/event 불변"으로 쓰고 특정 코드에 묶지 않도록** 요청한다. G-P15가 Library 판정 방식(색인)을 바꿔도 결과는 같다 |
| 후보 목록(§4.3) | `list_revisions`(735-754행)가 selected·stale을 붙인다. complete·template·settings_key·coverage는 body에 있다 | 후보 분류(현재/이전 전사/이전 설정/비교 불명/부분)를 기존 읽기만으로 계산할 수 있다 |

### 2. G-P07 계약과의 접점

1. **상태 읽기 모델(N 가족):**
   - G-P07의 `app/status.py`는 다음을 구별한다: "실행 준비 차단(미접수)", "Job BLOCKED"(5종 사유), REMOTE_UNKNOWN, ABANDONED, FAILED, BACKOFF, 시도 한도 소진, 취소·삭제.
   - 원문 N의 상태 8개(준비차단/queued/running/취소요청/로컬ACK/REMOTE_UNKNOWN/철회영속화/선택충돌)에는 **알려진 BLOCKED, BACKOFF, ABANDONED, FAILED**가 없다.
   - 4개를 더해 **12상태**로 확장할 것을 요청한다.
   - 알림 문구와 행동 식별자는 G-P07 읽기 모델의 안전한 설명을 그대로 쓴다. G12는 사유 의미를 재정의하지 않는다.
   - politeness: BLOCKED·REMOTE_UNKNOWN·FAILED는 assertive, 나머지는 원문 그대로다. 같은 Job에서 사유만 바뀐 경우(예: BUDGET→CONSENT)도 "새 의미 변화"로 1회 알린다.
2. **행동 버튼(K 가족):**
   - G-P07은 content에 두 가지를 더한다(G-P07 §4).
     - 사유별 "조건 다시 확인 후 계속" 버튼
     - 설정 위치 탐색: `privacy.focus_blocked_action(kind, action_id)`, 모델·자원은 MainWindow 패널
   - 원문 K의 위젯 5개에 **"계속"과 "설정 탐색" 2개를 더해 7개**로 할 것을 요청한다.
   - 키 계약:
     - 탐색의 Enter/Space는 초점 이동만 한다. grant·ledger·Job·정책 쓰기는 0이다.
     - 계속은 한 입력에 정확히 1회만 실행하고, G-P07이 읽은 expected_job_id/version을 그대로 전달한다.
     - REMOTE_UNKNOWN에는 계속 버튼이 없다(G-P07 §4). 키 입력으로도 만들지 않는다.
3. **대기 취소(§5.1):**
   - 0d846d6과 G-P07 계약 어디에도 별도의 "대기 취소" 명령은 없다.
   - 실제 명령은 `AIBridge.cancel`(`ui/ai_bridge.py:504-519`)이다. 준비 취소 event를 세우고, 선택 세션 전체의 `cancel_session`을 큐에 넣는다.
   - `JobStore.cancel`(`jobs/__init__.py:391-413`)의 동작:
     - QUEUED와 알려진 BLOCKED는 CANCELLED가 된다.
     - RUNNING은 CANCEL_REQUESTED가 된다.
     - BLOCKED(REMOTE_UNKNOWN)는 BLOCKED를 유지하고 cancel_requested=1만 기록한다.
   - 원문 §5.1의 "예산/권한 대기 취소"는 **이 기존 명령에 키보드만 연결**하며, Job별 새 취소 API를 만들지 않는다.
   - UNKNOWN Job의 취소는 "취소 요청됨·결과/비용 미확인 유지"로만 알린다(원문 T23과 같은 계약). 명명 행 T26을 추가한다.
4. **부분 요약의 Job 코드(P 가족):**
   - `app/ai.py:566-569`는 부분 결과를 후보로 게시한 뒤 `ProviderError(result.error_code or "SUMMARY_PARTIAL")`를 던진다.
   - G-P07의 110코드에는 `SUMMARY_PARTIAL`이 없다. 따라서 승인 결정표에서는 미등록 known 코드로 보아 TASK_FAILED/FAILED가 된다.
   - G12의 부분 후보 표시는 Job 코드가 아니라 **revision의 `complete=false`와 coverage로 분류**한다(원문 §4.3과 정합).
   - P의 Job 상태 기대값은 G-P07 결정표로 갱신하며, 분모는 그대로다. 명명 행 T25를 추가한다.
   - `SUMMARY_PARTIAL`을 G-P07 F 목록에 등록할지는 G-P07의 결정 사항이다. G12는 어느 쪽에도 기대지 않는다(선택 결정 ⑥).
5. **암묵 resume 금지:**
   - G-P07은 `app/ai.py:103-111`의 같은 키 BLOCKED 자동 재개를 없앤다(G-P07 §개정 3, A 가족).
   - G12의 P 가족 "결과순서" 행은 일반 재요청이 BLOCKED Job을 재개하지 않는다는 전제로 기대값을 쓴다. G12는 새로운 계속 경로를 만들지 않는다.
6. **확인 창(F 가족):**
   - 0d846d6의 확인 창은 모두 `QMessageBox.question(Yes|No, 기본 No)`이다.
     - privacy: `_confirm_library`(411-428행), `_confirm_general`(727-739행), 비용 시계 재설정(884-893행), 이전 비용 이력 승계(959-968행)
     - bridge: `_confirm_retry`(`ui/ai_bridge.py:328-340`)
   - Yes|No 구성에서 Esc는 No(Qt의 escape 버튼 규칙)다. 원문 F의 "기본 거부"는 이미 성립하는 성질을 고정하는 시험이다.
   - 모달 3개(LIBRARY 동의/일반 모드 위험/요약 선택)에 **UNKNOWN 명시 재실행 확인(`_confirm_retry`, 중복 처리·과금 경고)**을 더해 **4개**로 할 것을 요청한다. G-P07은 REMOTE_UNKNOWN의 다음 행동으로 이 명시 새 요청을 남긴다.
   - G-P06 비용 확인 2개(시계 재설정·이력 승계)는 G-P06 소유 UI다. F에 넣을지는 C00이 결정한다(⑦). 넣으면 F는 6×3×4×2×2=288이다.
7. **장치 정책 control의 소유자(사실 정정):**
   - `device_policy`는 `ui/main.py:267-269`의 MainWindow가 만든다. AIBridge는 `ui/ai_bridge.py:169`에서 값을 읽기만 한다.
   - 원문 §9의 "AIBridge가 이미 소유한 device policy control"은 정정한다.
   - 선택지:
     - (가) AIBridge가 `window.device_policy`의 accessibleName/description만 설정한다. main.py 쓰기는 0이다.
     - (나) `ui/main.py`를 G12 범위에 더한다. G-P07·G-P11 뒤 직렬이다.
   - 권고는 (가)다. G-P11이 정책 control을 바꾸면 그 결과 위에 얹는다.

### 3. 공유 파일과 착수 순서

| 파일 | 이미 push됨 | 진행/대기 단위 | G12 |
| --- | --- | --- | --- |
| `src/recoryn/ui/content.py` | — | G-P07(사유·계속·탐색 표시) | 수정 |
| `src/recoryn/ui/privacy.py` | G-P02·G-P06 | G-P07(`focus_blocked_action`) | 수정 |
| `src/recoryn/ui/ai_bridge.py` | G-P02·G-P06 | G-P07, G-P11a, G-P11b | 수정 |
| `src/recoryn/app/ai.py` | G-P03·G-P06 | G-P07(`_admit`·expected_job), G-P11a/b(ResourceRequest) | 538행 변환만 |
| `src/recoryn/ui/main.py` | G-P04·G-P05·G-P05b | G-P07(REC·탐색) | 범위 밖(§2-7 (가)) |
| `src/recoryn/content/store.py`·`models.py`·`__init__.py` | G-P03 | — | 수정 |
| `src/recoryn/app/status.py` | — | G-P07 신규 | 읽기만 |

- G12의 기존 UI·app 4파일은 모두 G-P07과 겹친다. 원문 §1의 "G-P07 push 뒤 착수"를 유지한다.
- G-P07의 마지막 단계(삭제 권위 L 8행·M24)는 G-P15 push에 종속된다(G-P07 계약의 C00 범위 결정 절).
- `app/ai.py`·`ui/ai_bridge.py`는 G-P11a/b와도 겹친다.
- **권고 순서: G-P15 → G-P07 → G-P11a → G-P11b → G-P12.** 근거는 두 가지다.
  - G12 §5.1의 CPU 전환 거부와 strict Ollama 정책 안내는 P11a의 산출물이다.
  - lease/ACK 표시(INFERENCE_ACK_PENDING·RESOURCE_LEASE_HELD)는 P11b의 산출물이고, N의 "로컬ACK" 알림에 들어간다.
- 대안은 G-P11a → G-P12 → G-P11b다. a11y가 먼저 들어가지만, P11b가 G12의 접근성 adapter와 알림 세대 규칙을 보존할 의무를 진다. C00 결정 대상이다(⑤).
- 원문 §4.1의 poll 규칙("같은 표시 내용의 poll은 setHtml을 다시 만들지 않음")의 대상은 0d846d6 `ai_bridge.tick`(635-669행)이다. 진입점은 `ui/main.py:1079`이다. tick은 Job snapshot이 바뀌면 `panel.load`로 다시 그린다. G-P07이 이 tick을 읽기 모델로 바꾸므로, G12는 G-P07 이후의 tick 위에서 이 규칙을 구현한다.

### 4. 분모·mutation 변화 요청

| 가족 | 원문 | 개정 산식 | 개정 행 | 차이 |
| --- | ---: | --- | ---: | ---: |
| K | 240 | key4 × 위젯7(시간표·claim링크·거부·철회·대기취소·**계속·설정탐색**) × target상태4 × source target3 | 336 | +96 |
| F | 144 | 모달4(LIBRARY동의·일반모드위험·요약선택·**UNKNOWN 명시 재실행**) × exit3 × opener4 × 이후초점이동2 × 완료즉시/지연2 | 192 | +48 |
| N | 64 | 상태12(원문8 + **BLOCKED·BACKOFF·ABANDONED·FAILED**) × 동일poll/새version2 × 초점2 × generation2 | 96 | +32 |
| T | 24 | 원문24 + T25·T26 | 26 | +2 |
| 나머지 8가족(B·W·P·E·C·R·D·Z) | 1,760 | 원문 그대로. P는 Job 기대값만 G-P07 결정표로 갱신 | 1,760 | 0 |
| **합계** | **2,232** | 336+192+96+26+1,760 | **2,410** | **+178** |

- T25: 부분 요약 Job이 G-P07 결정표로 FAILED(TASK_FAILED)여도, 부분 후보는 revision `complete=false`로 분류한다. 전체 선택 버튼은 비활성이다.
- T26: BLOCKED(REMOTE_UNKNOWN)의 대기 취소 키 입력 뒤 상태는 BLOCKED+cancel_requested로 남는다. 알림은 "취소 요청·결과 미확인"이고, 완료 알림은 0이다.
- 신규 행의 독립 기대 근거는 다음과 같다.
  - 계속·탐색: 키 1입력당 명령 호출 수, Job state_version·attempt 수, grant/ledger fake 호출 수
  - UNKNOWN 재실행 모달: 새 Job 수와 transport 호출 수
  - BLOCKED 등 4상태: G-P07 읽기 모델 fake가 내는 고정 상태 토큰
  - 모두 손으로 쓴 표와 대조하며, 제품 status 함수를 expected에 import하지 않는다.

mutation은 원문 24개를 유지하고 다음 4개를 더해 **28개**를 요청한다.

| ID | 결함 | 독립 검출 목표 |
| --- | --- | --- |
| M25 | 설정 탐색 버튼의 Enter/Space가 계속 실행이나 정책 변경을 함께 수행 | K 탐색 행의 Job/grant/ledger/정책 쓰기 0 |
| M26 | 계속 버튼 한 입력에 기본+custom 활성화로 계속 2회 | K 계속 행의 명령 1회·attempt +1 |
| M27 | UNKNOWN 명시 재실행 확인에서 Esc를 Yes로 처리 | F 재실행 모달의 새 Job·전송 0 |
| M28 | 같은 Job의 BLOCKED 사유 변화를 동일 상태로 보아 알림 누락 | N 새 의미 변화 알림 1회 |

### 5. 쓰기 범위

- 원문 13파일(source 8 + 신규 시험 4 + 문서 1)을 유지한다. §2-7 (나)를 고르면 `ui/main.py`가 더해져 14파일이 된다.
- 신규 시험 4파일(`tests/unit/test_claim_basis.py`, `tests/property/test_basis_a11y_case_space.py`, `tests/integration/test_basis_publication.py`, `tests/ui/test_basis_a11y_ui.py`)은 0d846d6에 없다. 이름 충돌은 0이다.
- 원문 §7이 인용한 기존 node 14개는 0d846d6에 모두 있다. `tests/integration/test_selection_version_cas.py`도 있다.
- G-P07이 추가하는 `tests/ui/test_blocked_reason_ui.py` 등은 G12 회귀 목록에 더한다. G12는 그 파일들을 수정하지 않는다.

### 6. C00 결정 요청

1. 분모 2,232→**2,410**: K 위젯 7, F 모달 4, N 상태 12, T25·T26
2. mutation 24→**28**: M25~M28
3. 대기 취소를 기존 `AIBridge.cancel`/`cancel_session`에 연결하고 Job별 새 취소 API는 만들지 않는 것의 확인
4. 장치 정책 control: (가) bridge가 접근성 속성만 설정 / (나) `ui/main.py` 범위 추가. 권고 (가)
5. 착수 순서: G-P15 → G-P07 → G-P11a → G-P11b → G-P12. 대안은 P11a → G-P12 → P11b
6. (선택, G-P07 결정) `SUMMARY_PARTIAL`을 G-P07 F 목록에 등록할지. G12는 어느 쪽에도 기대지 않는다
7. (선택) G-P06 비용 확인 2개를 F에 포함할지. 포함하면 F는 288행, 합계는 2,506행이 된다

제품 코드·제품 시험·mutation은 여전히 실행 0이다. 이 절 추가 외에 저장소 파일을 수정하지 않았다.

## §구현 결과(G-P12, 8ca52f8 기준)

### 기준과 범위

- 작성자는 w5:p7 Claude다. 배정은 C00의 G-P12 착수 신호다. 승인 개정 `b1db1930…618d`의 내용은 다음과 같다.
  - 분모 2,506, mutation 28
  - 대기 취소는 기존 `AIBridge.cancel`/`cancel_session`에 연결
  - 장치 정책 control은 bridge가 접근성 속성만 설정
  - `SUMMARY_PARTIAL`은 revision `complete=false`로 분류
- 기준 HEAD는 `8ca52f8`이다. 시작 때 13파일 hash를 고정했다. 12파일은 HEAD와 같았고, 이 문서는 미추적(`b1db1930…`)이었다.
- 이 문서의 앞 내용(LF SHA-256 `b1db1930…618d`)은 한 바이트도 바꾸지 않았다. 이 절은 끝에 덧붙였다.
- 13파일 밖은 쓰지 않았다. 같은 작업 트리의 Codex G-P08 파일(`app/status.py`·`ui/main.py`·`storage/library.py` 등)은 읽기만 했다. 모든 실행은 그 변경을 쓰지 않는 격리 사본에서 했다.

### source 변경

| 파일 | 변경 |
| --- | --- |
| `content/models.py` | `Claim.provider_basis`(선택, `None`=미기록). 3값 외 값이나 str이 아닌 값은 `INVALID_CLAIM_PROVIDER_BASIS`다. status 6값과 자동 `supported` 거부는 그대로다 |
| `content/store.py` | `canonical_basis`(unresolved > user_assertion > transcript, 참조 없음=model_inference). 게시 때 basis를 원 전사 provenance에서 다시 계산하고, `provider_basis`는 값이 있을 때만 참고값으로 저장한다(legacy byte 불변). 읽기 전용 `claim_evidence`는 원 revision에서 재계산하고 `CONTENT_CLAIM_SOURCE_UNAVAILABLE`/`CONTENT_CLAIM_BASIS_MISMATCH`를 보이며 쓰기는 0이다. 필수 `SummarySelectionExpectation`과 `select_summary_candidate`는 transaction 안에서 두 ID·두 version·요청 설정 키를 모두 비교한다(None도 관측값으로 비교). 타 세션·partial·삭제 intent는 거부하고, 이전 전사·설정·비교 불명은 `allow_outdated`가 필요하다. 성공하면 summary_version+1·event 1건이다. `list_revisions`는 같은 mutex 구간에서 이미 확인한 세션의 행별 재확인만 생략한다(결과 동일, 아래 해석 7) |
| `content/__init__.py` | 새 이름 export |
| `app/ai.py` | 어댑터 basis는 `provider_basis`로만 전달한다. 정본은 store가 계산한다 |
| `ui/a11y.py`(신규) | `Announcer`: GUI thread 전달, 키 = generation+version+종류. 같은 poll 0회, 새 의미 1회, 옛 generation 0회, 초점 불변. `KeyActivation`: Enter/Space 한 입력에 1회, native 활성화와 이중 실행 없음, 숨김·비활성 대상은 0회. `focused_anchor`: Tab·Shift+Tab 링크 초점. `FocusReturn`: 창 단위 초점 기준. opener가 살아 있고 보이고 활성이며 같은 세션일 때만 복귀, 사용자가 옮긴 초점은 유지, 아니면 안전한 fallback. `confirm`: 정적 `QMessageBox.question` 유지, Yes\|No·기본 No |
| `ui/content.py` | 두 영역(전사 참조/추가 검토 필요). 각 영역에 제목·개수·이름·설명을 두고 0건을 구별한다. 결정·할 일 제목은 "— 미확정"이다. 링크는 `(session, summary rev, transcript rev, segment, view_generation)`에 고정하고, HTML escape하며 외부 링크를 차단한다. 시간 셀·링크 키보드를 지원하고, 편집·IME·dirty 중에는 이동하지 않는다. 후보 콤보는 열람만 하고, "이 요약 선택"은 항상 확인한다. snapshot은 제시 때 잡고 CAS로 비교한다. 지연 완료는 안전할 때만 초점을 복귀하고, 옛 세션 callback은 무시하며, 충돌은 assertive로 알린다. 같은 poll에는 재렌더·목록 재구성이 없다 |
| `ui/privacy.py` | 확인 창 4개를 `a11y.confirm`으로 바꿨다(세션 동일성·fallback 포함). 동의·철회·예산·시계·승계·정산·갱신 버튼에 Enter/Space를 연결했다. 철회·동의 버튼에 이름과 설명을 달았다. 철회 영속화를 polite로 알린다 |
| `ui/ai_bridge.py` | `_confirm_retry`를 `a11y.confirm`으로 바꿨다. Job 상태 알림(`job_announcement`·`announcement_text`·`announcement_version`), 준비 실패 알림, 취소 요청 알림을 추가했다(로컬 ACK와 원격 UNKNOWN 구별). 장치 정책 control에는 접근성 이름·설명만 붙이고 값은 바꾸지 않는다 |

### 구현 중 발견·정정

1. **장치 정책 이름 붙이기 시점**
   - `MainWindow`는 bridge를 만든 뒤(`ui/main.py` 115행) `device_policy`를 만든다(269행).
   - 그래서 생성자에서 이름을 붙이면 실제 앱에서는 실행되지 않는다. 다음 event-loop 차례와 tick에서 멱등하게 붙인다.
   - 실제 `MainWindow`로 확인했다(`ui/main.py` 쓰기 0).
2. **창 단위 초점:** 모달이 닫힌 직후에는 부모 창이 다시 활성화되기 전이라 `QApplication.focusWidget()`이 비어 있을 수 있다(offscreen에서 재현). 초점 판정은 그 창의 focus child를 쓴다.
3. **숨김 대상:** native `QPushButton`은 숨겨진 버튼에 직접 보낸 Space도 click한다. activation key는 숨김·비활성 대상에서 소비만 하고 실행하지 않는다.
4. **자기 검토 수정**(1차 mutation 뒤 적용. 최종 mutation·CI는 수정 후 hash로 다시 실행했다)
   - 바쁜 bridge가 선택 작업을 거부하면 안내하고 초점을 복귀한다.
   - 콘텐츠 작업 실패에 "준비 차단"이라는 이름을 붙이지 않는다.
   - 변하지 않은 후보 목록은 다시 만들지 않는다.
   - 선택된 요약은 "선택된 요약"으로 표시한다.
   - "재생 가능" 표시를 실제 활성화 판정(근거 문장 존재·audio·timing 검증)과 일치시켰다.
5. **계약 공백 보조 시험:** 타 세션 후보·타 세션 snapshot 거부, 변조된 `provider_basis`, basis 필드가 없는 기록을 보조 node로 추가했다.

### 계약 해석과 C00 판단 요청

1. **Z는 UI 계층에 두었다:** §7 표는 Z를 unit에 배정했다. 그러나 무주장·부분·legacy 표시는 실제 두 영역 렌더링으로만 확인할 수 있어 UI 파일에 두었다. ID 수는 그대로다.
2. **K "거부" 위젯**
   - privacy LIBRARY 동의 버튼으로 확인 창을 열고, 키보드로 거부(기본 No에서 Enter)한다.
   - 버튼 5종에서 source target 축은 의미가 없다. 그래서 각 3행은 source와 무관한 불변(명령 1회·다른 signal 0)을 확인한다(§6.1 문구).
   - `destroyed`의 정의는 다음과 같다.
     - 표: 세션을 바꾼 뒤의 옛 행
     - 링크: 이전 view generation의 링크(늦은 anchor signal 포함)
     - 버튼: 소유 패널을 파괴하고 남은 창에 키 전달
3. **E "편집 중"** = 저장 실패로 보존된 미저장 편집이다. IME 조합 중 Space 보존은 T15가 맡는다.
4. **F의 opener·fallback·timing**
   - opener: 모달이 열릴 때 초점을 가진 위젯(`confirm` 기본값). 요약 선택도 버튼을 명시하지 않고 이 규칙을 쓴다.
   - fallback: privacy는 해당 기능의 범위 목록, 요약 선택은 후보 목록, UNKNOWN 재실행은 전사 버전 목록이다.
   - 동기 모달 5개의 "지연"은 늦은 poll이다. 제품은 닫힐 때 복귀한다. 요약 선택의 "지연"은 보류한 쓰기의 늦은 완료다.
5. **C의 후보 목록과 경쟁**
   - "없음" = 선택된 요약만 있음.
   - "요약ID변경"·"요약ABA" = 다른 연결에서 게시한 늦은 결과가 선택되는 경우다. ABA는 다시 원래 ID로 돌아온다.
   - "바뀐 세션" = 확인 뒤, 완료 전에 다른 세션으로 이동한 경우다.
6. **N은 순수 model과 Qt 알림 adapter다**
   - Job 상태 9종은 손으로 만든 Job snapshot을 제품 mapping에 넣는다.
   - 비 Job 3종(준비 차단·철회 영속화·선택 충돌)은 announcer를 직접 쓴다.
   - 제품 호출 지점은 C(충돌 알림), T23·T26(실제 tick·키보드 취소)이 확인한다.
7. **공용 G-P03 store의 성능 변경**
   - `list_revisions`는 처음에 세션을 확인한 뒤, 같은 `root_mutex` 구간 안에서 그 세션 행마다 같은 파일시스템·journal 확인을 반복했다.
   - 행별 확인을 생략했다. 다른 세션 행이 섞이면 여전히 확인한다. 반환값은 같다.
   - `ContentPanel.load`가 한 번에 목록을 한 번만 읽는 변경과 함께, C family를 13.1초에서 8.3초로 줄였다.
   - 공용 store이므로 검토자 확인을 요청한다.
8. **기존 호출 호환:** `tests/integration/test_ai_independent.py:356`의 `_claim_clicked("claim:0:0")`는 범위 밖이다. generation이 없는 key는 현재 view로 해석해 유지했다.
9. **P의 Job 상태**(G-P07 결정표)
   - 부분 결과: FAILED/TASK_FAILED, revision은 `complete=false` 후보(T25)
   - 삭제 먼저: 게시 거부, FAILED/TASK_FAILED
   - 취소 먼저: CANCELLED, 게시 0
   - ABA: SUCCEEDED 후보, 선택 불변
10. **범위 밖 관찰(G-P08 소유 파일, 변경 안 함)**
    - 완료된 삭제는 `deletion-journal` 기록으로 남는다. 모든 Job 전이(`job_authority`)가 그 기록 전체를 다시 읽는다.
    - 그래서 삭제된 세션 수에 비례해 Job 전이가 느려진다. 처음에 삭제 행을 공용 라이브러리에 두었을 때 행당 수십 ms가 늘었다.
    - 시험은 삭제 행을 8행마다 교체하는 전용 라이브러리에서 실행해 행을 보존했다.
    - `ContentStore._live`→`library.get_session`의 경로 검사는 호출마다 약 1ms다.

### 시험

| 파일 | node | 의미 행 |
| --- | ---: | --- |
| `tests/unit/test_claim_basis.py` | 155 | B 768(한 node에서 batching, 행마다 실제 DTO→store→`claim_evidence`→영역 분류를 손 oracle과 대조), W 140(실제 parser→store), T01·02·03·04·05·10·18·19·20·24. 보조: 타 세션 거부, 변조·미기록 basis |
| `tests/property/test_basis_a11y_case_space.py` | 7 | 2,506 ID 감사(실제 parametrize mark를 읽어 누락·중복·초과 확인), 알림 상태 model(150예), basis 우선순위·재배열 불변(200예+store 30예), 열람·poll·이동 쓰기 0(25예) |
| `tests/integration/test_basis_publication.py` | 386 | P 288(실제 `AIService` 게시 경로+fake provider), D 96(두 연결, 직접 API), T21(event 쓰기 장애→전체 롤백), T25 |
| `tests/ui/test_basis_a11y_ui.py` | 1,205 | K 336, E 64, F 288(실제 `QMessageBox`를 키보드로 응답: Tab+Space=Yes, 기본 No에서 Enter, Esc), N 96, C 360, R 36, Z 8, T06·07·08·09·11·12·13·14·15·16·17·22·23·26. 보조 trace 3: Tab·Shift+Tab 링크와 poll 및 이름·설명, 실제 `MainWindow` 정책 이름, 바쁜 선택·변하지 않은 목록 |

- 기대값은 모두 손으로 쓴 표와 규칙이다. 제품의 basis 함수·영역 분류·parser·CAS·renderer를 기대값 계산에 쓰지 않는다.
- fake는 요약 제공자·재생기·background operation·확인 창 응답자만 바꾼다. store·AIService·JobStore·패널·bridge·tick은 제품 코드다.
- 키 입력은 모두 QTest의 press/release 한 쌍이다. 초점은 창 단위 focus child로 관측한다.

### 결과

- 모든 실행은 격리 사본에서 했다. 조건은 다음과 같다.
  - 사본 구성: `git archive 8ca52f8` + 13파일
  - PYTHONPATH = 사본 src, 자식 import 출처가 사본임을 확인
  - 공통 옵션: `-p no:cacheprovider`, OS TEMP 고유 basetemp, offscreen, `-W error::ResourceWarning`
  - 작업 트리의 G-P08 미완성 변경은 쓰지 않았다
- **신규 4파일 단독: 1,753 passed, 43.91초**(60초 게이트 안). family별 합계는 C 8.3초, P 14초, D 6.8초, F 6.1초, K 4.3초이고, 가장 긴 node는 B batch 2.43초다.
- **case ID 감사:** 개정 전체 2,506(B 768·W 140·P 288·K 336·E 64·F 288·N 96·C 360·R 36·D 96·T 26·Z 8)이 누락·중복·초과 0이고, skip은 0이다.
- **CI core 동등**(`.github/workflows/core.yml` 단계·flag 그대로, 최종 hash):
  - ruff check, format --check(189 files), mypy(91 source) 통과
  - 전체 pytest **23,028 passed**(failures·errors·skipped 0), 1,323.4초, JUnit LF SHA-256 `83f1e6d5…`
  - 총 coverage 92.47%
  - `scripts/check_coverage.py` 묶음별 예산 전부 PASS(line/branch %): domain 100/100, capture 99.85/98.57, jobs 99.29/96.23, storage 96.52/92.43, security 98.11/94.43, content 98.96/99.01, all 93.82/88.36
  - 새·변경 모듈 coverage: `content/models.py` 100%, `content/store.py` 99%, `ui/privacy.py` 95%, `ui/a11y.py` 94%, `ui/content.py` 91%, `app/ai.py` 90%, `ui/ai_bridge.py` 82%(미적중 대부분은 이번에 바꾸지 않은 기존 경로다. `ui/content.py` 803-822는 기존 내보내기 대화상자다)
  - CI 사본의 이 문서는 결과 절을 쓰기 전 판이다. 그 차이는 실행 대상이 아닌 문서뿐이다
- **mutation 28/28 검출, invalid 0**
  - mutant마다 새 격리 사본에 하나만 적용했고, import 출처가 사본임을 확인했다. 실행 대상은 신규 4파일이다.
  - 검출 기준: 목표 node가 assertion으로 실패하고, 수집·import·setup 오류가 0이며, exit 1.
  - 1차 실행(자기 검토 수정 전)과 최종 실행의 결과가 같다.

| ID | 결함 | 실패 | family별 실패 |
| --- | --- | ---: | --- |
| M01 | app의 provider_basis 전달 제거 | 144 | P 144 |
| M02 | canonical을 provider 값으로 | 138 | P 108, W 28, B batch, store property |
| M03 | user_assertion을 unresolved보다 우선 | 3 | B batch, 우선순위 property 2 |
| M04 | 빈 refs를 transcript로 | 68 | P 36, W 28, Z 2, B batch, property |
| M05 | 자동 supported 허용 | 1 | B batch |
| M06 | unsupported 결정·할 일을 전사 참조 영역에 | 1 | B batch |
| M07 | provider inference·assertion 검토 분기 제거 | 25 | P 24, B batch |
| M08 | HTML escape 제거 | 1 | T06 |
| M09 | 링크를 현재 active 전사로 | 9 | K 6, T08·T13, Tab trace |
| M10 | nonaudio·unverified seek 보호 제거 | 8 | K 6, T11·T12 |
| M11 | 시간 셀 Enter/Space 제거 | 5 | K 2, E 2, T16 |
| M12 | custom 뒤 기본 이벤트도 실행 | 18 | K 16, T13·T16 |
| M13 | 링크 Space 제거 | 3 | K 3 |
| M14 | 방향키 seek | 2 | K 1, E 1 |
| M15 | 숨김·옛 행 검증 제거 | 6 | E 4, K 2 |
| M16 | 늦은 완료가 무조건 opener에 초점 | 73 | F 73 |
| M17 | Esc를 Yes로 | 474 | F 288, C 180, K 6 |
| M18 | 일반 모드 No를 허용으로 | 32 | F 32 |
| M19 | 철회·대기 취소 키 연결 제거 | 13 | K 12, T26 |
| M20 | 같은 poll 알림 반복 | 49 | N 48, 알림 model |
| M21 | 로컬 ACK를 원격 취소 완료로 | 6 | N 6 |
| M22 | summary version 검사 제거 | 18 | C 12, D 6 |
| M23 | commit 직전 expected를 현재 값으로 | 77 | C 46, D 30, T24 |
| M24 | 열람·poll에서 자동 선택 | 141 | C 108, F 32, 열람 property |
| M25 | 설정 탐색이 계속도 실행 | 6 | K 6 |
| M26 | 계속 한 입력에 2회 | 6 | K 6 |
| M27 | UNKNOWN 재실행 Esc를 Yes로 | 48 | F 48 |
| M28 | BLOCKED 사유 변화를 같은 상태로 | 18 | N 18 |

### 미검증·한계

- 실제 Narrator 발화, Windows 실장비의 IME·화면 낭독기 조합, 고대비·확대 환경은 실행하지 않았다(외부 게이트). Qt 접근성 이벤트의 생성·대상·politeness만 시험했다.
- 실제 음성·모델·네트워크·유료 호출은 없다. 요약 제공자와 재생기는 fake다.
- 의미 지지 정확도 평가 corpus나 사람이 붙인 supported 라벨은 없다. 두 영역은 참조 출처 분류이지 사실 검증이 아니다.
- 유한 trace·property bound 밖의 모든 GUI 이력을 증명하지 않는다. 실제 tick 주기 아래의 알림 빈도와 지연은 측정하지 않았다.

## §FIX1(독립 검토 G12R-01~09 수정, 31bc88b 기준)

### 기준과 범위

- 작성자는 w5:p7 Claude다. 배정은 C00의 G-P12 우선 수정 요청이다. C00은 G12R-01을 S1로 올렸다.
- 근거 문서는 독립 검토 `docs/reviews/g12-basis-a11y-review.md`(LF SHA-256 `a44dd3ae…`)다. 반례는 `build/review-trees/g12a-probe/`에 있다.
- 기준 HEAD는 `31bc88b`다. 쓰기는 G-P12 13파일 안에서만 했다. 이 문서의 앞 내용(LF SHA-256 `3377834e…cd5d`)은 바꾸지 않았다.
- 모든 실행은 격리 사본에서 했다(`git archive 31bc88b` + 13파일). 작업 트리에 있는 G-P11c 미완성 변경(`jobs/runner.py`·`models/resources.py`·`app/status.py`)은 쓰지 않았다.

### 처리

| ID | 처리 |
| --- | --- |
| G12R-01(S1) | `claim_evidence`가 problem을 붙인 claim에는 근거 링크·`_claim_refs` key·원 전사 이동을 아예 만들지 않는다. 화면에는 "근거 확인 불가 · 사유 · 재생·원문 이동 없음"만 둔다. 키 입력·클릭·늦은 옛 신호 모두 seek 0이며, 근거 행 선택도 0이다 |
| G12R-02 | X02: 저장 transcript·uncertain·provider None·problem 있음 → 검토 영역, `claims` browser에 없음. 손 oracle과 실제 UI로 확인한다 |
| G12R-03 | 두 영역이나 후보 목록에 초점이 있으면 지금 보던 요약을 열람으로 유지한다. 재렌더가 없으므로 초점 링크도 유지된다. 새 active는 polite `NEW_ACTIVE_SUMMARY`로 1회 알린다. 확인 창이 열려 있거나 편집 중일 때도 같은 알림만 남긴다 |
| G12R-04 | 후보를 열람하는 동안에는 열람을 시작할 때 제시된 snapshot을 유지한다. active가 바뀌면 열람 정보에 "열람을 시작한 뒤 선택 요약이 바뀌었습니다. 선택하면 다시 확인합니다"를 표시하고 알린다. 선택은 그 snapshot으로 CAS하므로, 확인 창 안 경쟁과 같은 충돌 안내(assertive)와 재조회로 이어진다. 다른 후보로 옮기면 현재 선택을 다시 제시한다 |
| G12R-05 | 저장 claim의 형식(dict, text str, segment_ids 중복 없는 str list)과 값(status 6값, basis·provider_basis 허용값)을 읽을 때 검사한다. 어긋나면 `CONTENT_CLAIM_RECORD_INVALID`로 확인 불가(링크 0)다. `claims`가 list가 아니면 요약 전체를 확인 불가로 본다. TypeError가 poll 밖으로 새지 않는다 |
| G12R-06 | basis 미기록이면 "출처 기록 없음 · 원 전사에서 계산: …"으로 계산값을 보인다 |
| G12R-07 | "이 요약 선택"에 Enter를 연결했다. 두 영역 browser의 접근성 이름에 개수를 넣었다. 취소 알림을 "실행 준비(작업 미접수) 취소"와 "기존 AI 작업 N건 취소"로 구분했다. Announcer는 같은 세대 안에서 이미 알린 의미(최대 256)를 기억하므로, 다른 알림이 끼어들어도 같은 의미를 반복하지 않는다 |
| G12R-08 | 링크 key에 렌더 세대를 넣었다(`claim:i:j@view.render`). 같은 세션에서 다른 요약을 그리면 옛 링크는 아무것도 하지 않는다. generation이 없는 기존 호출(`claim:i:j`)은 현재 렌더로 해석한다 |
| G12R-09 | 의미 행을 추가했다: X14(두 None 설정 key는 현재 아님·확인 필요), X15(autorepeat는 한 번), X16(타 세션 대상 거부) |

### 분모·mutation 변경(C00 판단 요청)

- **분모 2,506 → 2,522:** 새 family X 16행(G12-X-01~16)을 더했다. 각 행은 검토 반례 P1~P8 또는 시험이 없던 규칙 하나에 대응한다.
  - P1~P5: X01~X06
  - P8: X07
  - P4: X08
  - P6: X09
  - R-07: X10~X12
  - R-08: X13
  - RM3·RM4·RM6: X14~X16
- **mutation 28 → 44:** M29~M44를 더했다.
  - M29~M33·M38~M44는 이번 수정을 하나씩 되돌린다.
  - M30·M34·M35·M36·M37은 검토자 RM1·RM3·RM4·RM6·RM2를 그대로 옮긴 것이다(RM5는 기존 M22).
  - 기존 M08·M20은 같은 결함을 새 코드 위치에 다시 적용했다.
- 기존 행의 기대값 변경은 두 건이다.
  - 변조된 `provider_basis`의 problem 코드: `BASIS_MISMATCH` → `RECORD_INVALID`(G12R-05 분류).
  - 알림 상태 model: "직전 1건" → "세대 안 기억"(G12R-07).

### 결과

- **검토자 반례 재적용**(같은 스크립트, PYTHONPATH = 수정 사본 src)
  - P1·P2·P3: 해당 claim의 링크 0개, "재생 가능" 0, Enter·Space·옛 형식 링크 신호의 seek 0이다.
  - P5: 초점 링크와 보던 요약이 유지된다.
  - P8: 늦은 결과(LATE)가 대체되지 않는다. polite 새 요약 알림 1건 뒤에 assertive 충돌 알림이 나온다.
  - 형식 손상: load가 예외 없이 "근거 확인 불가"를 보인다.
  - `probe_ui.py`는 링크가 있다고 가정하므로 링크가 없을 때도 같은 키 입력을 시도하도록 사본만 고쳐 썼다. 원본은 바꾸지 않았다.
  - P4: 원 전사가 정상이라 유효한 근거이며 재생된다(계약대로).
- **신규 4파일 단독: 1,769 passed, 44.32초**(60초 게이트 안).
- **case ID 감사:** 2,522(기존 2,506 + X 16)가 누락·중복·초과 0이다.
- **CI core 동등**(`31bc88b` + 13파일, 단계·flag 그대로)
  - ruff check, format --check(196 files), mypy(92 source) 통과
  - 전체 pytest **24,219 passed**(failures·errors·skipped 0), 1,653.9초, JUnit LF SHA-256 `6cc9ac43…`
  - 총 coverage 92.45%
  - 묶음별 예산 전부 PASS(line/branch %): domain 99.18/97.89, capture 99.85/98.57, jobs 99.29/96.23, storage 95.92/91.20, security 98.11/94.43, content 98.98/99.02, all 93.81/88.47
- **mutation 44/44 검출, invalid 0**
  - M29~M44는 각자의 X 행에서 검출됐다.
  - M37(RM2)은 C 47건·X07에서 검출됐다.
  - 기존 28개의 결과는 이전 실행과 같다. 단, M12는 "이 요약 선택"에도 Enter/Space 처리가 붙어 실패 수가 18에서 200으로 늘었다.

### 미룬 항목

- K `destroyed` 버튼 행을 "파괴된 버튼의 늦은 `clicked` 신호 재전달"로 강화하는 것(검토자 S3 관찰, ID 없음)
- bridge의 정책 코드 override(`ui/ai_bridge.py`의 `POLICY_CODES`) 제거. G-P11c(G11R-04) 뒤 후속이다
- 원 전사 자체가 행 hash까지 다시 계산되어 변조된 경우, 전사 보기는 그 내용을 그대로 보인다. 요약 근거는 hash 불일치로 확인 불가가 되지만, 외부 기준점이 없는 전사 보기 무결성은 G12 범위 밖이다
- 검토 §6의 완료 삭제 journal 비용은 C00 결정대로 GS-P02로 넘긴다
- 실제 Narrator 발화는 외부 게이트다

## §G-P12b 범위(b6da7e0 기준)

작성자는 w5:p9 Codex이며 w5:p7 리드가 구현을 배정했다. 독립 검증·검토와
C00의 통합은 별도다. 이 절 앞의 LF SHA-256은
`144fc42f496ba758f52b48203936e38e6bb917acce7a2855696e6140b8ed7215`이며 바꾸지 않는다.
근거는 독립 검토 재확인 1의 G12R-10 및 R1.5 G1이다.

### 결정과 쓰기 범위

- 현재 저장된 선택 ID로 선택됨과 버튼 활성 여부를 판단한다. 초점 때문에
  유지한 완전 요약이 현재 선택이 아니면 “지금 보던 요약 · 선택 요약 아님”으로
  표시하고 선택을 허용한다. 쓰기에는 기존 제시 snapshot을 사용하므로 충돌을
  알리고 재조회·재확인한다. 부분 결과는 계속 선택 불가다.
- 초점 유지와 사용자 직접 열람을 구분한다. 초점이 두 영역·후보 목록을 떠나면
  다음 poll에서 초점 유지만 풀고 현재 active 및 snapshot을 다시 잡는다.
  사용자가 직접 고른 열람은 초점과 무관하게 유지한다.
- 선택 또는 후보 전환의 읽기가 거부되면 기존 화면·열람·snapshot을 보존하고,
  “세션 삭제 진행 중이거나 요약을 읽을 수 없어 선택할 수 없음”을 안내한다.
  기존 `SELECTION_CONFLICT`를 assertive로 한 번 알린다. 선택 대상의 유효성이
  변경되어 재조회가 필요하다는 같은 종류의 알림이며 새 Job/정책 사유는 아니다.
  같은 세션·화면에서 반복된 같은 거부는 다시 알리지 않고 쓰기·재생은 0이다.
- `_candidate_changed`는 snapshot과 요약 읽기를 함께 try 안에서 끝낸 뒤에만
  화면 상태를 반영한다. 거부 시 콤보도 이전 열람으로 되돌려 Qt slot 밖 예외와
  서로 다른 콤보·본문 표시를 막는다.
- 쓰기는 `src/recoryn/ui/content.py`, `tests/ui/test_basis_a11y_ui.py`,
  `tests/property/test_basis_a11y_case_space.py`, 이 문서의 끝 추가만 허용된다.

### 새 family·손 oracle·분모

유한 대표 집합의 모든 조합을 실행한다. 기존 2,522행은 유지하고 Y 33행을 더해
**2,555행**이다. 거부 입력을 분모에서 빼지 않는다. 기대값 계산에 제품 함수를
사용하지 않는다. 실제 키 press/release, 창 단위 focus child, 실제 SQLite를 쓰고
외부 제공자·재생기·background operation seam만 기존 helper로 대체한다.

| ID | 축·행 수 | 손 oracle |
| --- | --- | --- |
| G12-Y-01~18 | 초점 {전사 참조 영역, 검토 영역, 후보 목록} × 완전/부분 × 다음 동작 {초점 유지 poll, 초점 이탈 poll, 선택 키} = 18 | 유지 중 이전 본문·링크/초점 보존, 선택됨 거짓 표시 0, 완전만 버튼 활성. 이탈 뒤 새 active·새 snapshot, 사용자 쓰기 0. 유지 완전 선택은 옛 snapshot 충돌·기존 active 보존·알림 1회, 부분은 모달·쓰기 0 |
| G12-Y-19~24 | 사용자 직접 열람 × 초점 {영역 안, 영역 밖} × 선택 변화 {없음, 다른 ID, ABA} = 6 | 키로 고른 본문은 유지하고 제시 snapshot도 불변, 열람/poll 쓰기 0. 현재 선택 표시와 버튼은 현재 DB 선택에 일치 |
| G12-Y-25~33 | 거부 지점 {선택 전 요약 읽기, 후보 전환 snapshot 읽기, 후보 전환 요약 읽기} × 오류 {실제 삭제 의도 StateConflict, KeyError, ValidationError} = 9 | slot 밖 예외 0, 이전 본문·콤보·열람·snapshot 보존, 안전 안내·assertive 1회(반복 거부도 1회), operation·DB 쓰기·seek 0 |

삭제 의도 행은 실제 session-bound 실행 Job으로 삭제를 보류한 임시 세션이다.
KeyError/ValidationError 행은 해당 읽기 seam에만 예외를 주입한다. 각 행의
조회 전후 SQLite 변경 누계와 선택 state·revision bytes를 비교한다. 사건 순서는
초점/열람 → 다른 연결 선택 → poll → 이탈/선택/거부로 고정하며 무한 GUI 이력의
전수 증명으로 확대하지 않는다.

### mutation·필수 게이트

새 변이 B01~B10은 각 TEMP 사본에 하나만 적용한다: B01 선택됨을 옛 snapshot으로,
B02 버튼 활성을 옛 snapshot으로, B03 초점 유지 해제 제거, B04 사용자 열람도
초점 이탈 때 해제, B05 초점 유지 중 snapshot 재캡처, B06 선택 전 읽기 거부 안내
제거, B07 거부 알림 제거, B08 후보 snapshot 읽기를 try 밖으로, B09 전환 거부 시
이전 열람/콤보 복귀 제거, B10 초점 해제 뒤 snapshot 갱신 제거. 각 변이는 위 Y행의
사용자 결과 assertion으로 검출해야 한다. 기존 M29~M44 중 수정 경로와 닿는
초점 유지·열람 snapshot·새 active 알림 변이도 재적용한다.

검증은 `git archive b6da7e0` + 위 4파일만 반영한 OS TEMP 사본에서 한다.
cwd/rootdir·PYTHONPATH 및 import 출처를 사본으로 고정하고 cacheprovider 비활성,
고유 OS TEMP basetemp, offscreen, ResourceWarning 오류화를 적용한다. 기존 신규
4시험 파일 합계 60초, 2,555 ID 누락·중복·초과 0, 지정 관련 회귀, 변이 목표
assertion 실패, core.yml의 정적 검사·전체 coverage·묶음 예산을 보고한다.
실제 Narrator·장비·모델·네트워크는 실행하지 않는다.

## §구현 결과(G-P12b, b6da7e0 기준)

### 기준·변경·시험 구성

- 시작 HEAD는 `b6da7e0`이고 배정 4파일의 diff는 0이었다. 시작 LF SHA-256은
  content.py `a486b6dcf48188f54b00d8ecd63e8bf829decaf8587f001770bca6b8a687fa05`,
  UI 시험 `8bd2c129ef30f13d34bb794c5a15db89472c04fffd45e840cde14bfce518c173`,
  property 시험 `7f7a7f7a0fd9816322d14fd7a7dd17689e8bd44e43cf5bbe67799ad96bd9d6d1`,
  문서 `144fc42f496ba758f52b48203936e38e6bb917acce7a2855696e6140b8ed7215`다.
- `content.py`만 제품 변경이다. 현재 읽은 선택 ID는 표시/버튼에 쓰고, 제시
  snapshot은 선택 CAS용으로 보존한다. `_summary_focus_held`는 직접 후보 열람과
  구별하며 초점 이탈 poll에서만 자동 추종으로 돌아간다. 후보 전환의 두 읽기가
  모두 성공하기 전에는 열람 상태를 바꾸지 않는다. 거부 시 이전 콤보로 돌아가고
  본문·snapshot은 그대로며 안전 안내와 기존 SELECTION_CONFLICT 알림을 낸다.
- Y 33행은 기존 `_x_world`, `k_panel`, `Sink`, `Modals`, 실제 키 입력 및 창의
  focus child를 사용한다. 부분 요약 축은 선택된 기존 body를 complete=false로
  만든 손상/legacy fixture다. 정상 제품 경로가 부분 요약을 선택한다고 주장하지
  않으며 이 저장 상태에서도 선택이 차단되는지를 확인한다.
- 읽기 거부의 실제 삭제 의도 행은 실행 Job 때문에 DELETE_PENDING으로 남긴다.
  snapshot 거부가 먼저면 요약 읽기 전에 거부된다. 별도 KeyError/ValidationError
  행은 각 읽기를 지정해 실패시킨다. 전환이 실패한 뒤 두 번째 키를 보내도 콤보와
  본문이 일치하고, 같은 거부 알림은 1회다. operation 호출·seek 및 SQLite 연결의
  변경 누계, 선택 행·revision body/hash는 전후 동일하다.
- 기존 시험 기대값은 바꾸지 않았다. property 감사의 분모에 Y를 더했고 기존
  2,522 ID를 유지했다. 제품 함수를 기대값 계산에 사용하지 않았다.

### 격리 실행과 완료된 결과

환경은 Windows 11 10.0.26300, Python 3.13.1, PySide6 6.12.0, pytest 9.2.0,
Hypothesis 6.170.15다. 모든 실행은 `git archive b6da7e0` + 배정 4파일의 새
OS TEMP 사본이다. 공통 옵션은 `-p no:cacheprovider -W error::ResourceWarning`,
고유 OS TEMP `--basetemp`, offscreen, bytecode 비활성, 사본 src의 PYTHONPATH다.
cwd/rootdir도 사본이며 parent 및 별도 spawn child의 import 출처를 확인했다.
시험·제품 코드는 이후 변경하지 않았다.

| 실행 | 실제 결과 |
| --- | --- |
| X 16 + Y 33 선택 실행 | 49 PASS, 3.57초 |
| 기존 신규 4시험 파일 첫 전체 실행 | 1,802 PASS, **71.42초로 60초 초과**. Y 33은 1.69초, C 17.28초·P 16.96초·D 9.62초. 초과를 보고한 뒤 아래 기준 비교를 했다 |
| 기준 제품 코드 비교 | `b6da7e0`의 content.py + 현재 시험, Y만 제외한 기존 1,769 PASS, 52.70초. C 9.58초·P 14.17초·D 5.40초. 이번에 수정하지 않은 통합 D도 최초 측정에서 느렸으므로 실행 환경 비용이 섞였다 |
| 변경 없이 같은 조건으로 재측정 | **1,802 PASS, 49.56초**. 행/fixture/assertion 축약·제품 변경 없음. 최초 초과 기록은 유지하며 부하 중 60초 SLA로 확대하지 않는다 |
| case ID 감사 | **2,555행**, 누락·중복·초과 0. Y=18+6+9, X=16 및 기존 모든 family 유지 |
| 지정 관련 회귀 | `tests/ui tests/integration/test_ai_independent.py tests/e2e tests/unit/test_content.py`: **2,939 PASS, 175.81초**. 실패·skip 0 |
| 정적 검사 | 전체 src/tests/scripts/packaging Ruff·format, `MYPYPATH=src` mypy src/recoryn/scripts/packaging PASS. 전체 회귀와 동일한 코드·시험 사본 |

첫 X/Y 실행의 새 Y 6실패는 비활성 선택 버튼을 경유한 시험 초점 설정이 원인이다.
후보 목록에 직접 초점을 두고 하나뿐인 초기 항목에 실제 방향키를 보내도록 고쳤다.
기존 X 행의 실패나 제품 기대값 변경은 없었다. 이후의 정상·변이·CI 실행은 모두
이 시험 수정과 format 뒤의 같은 코드·시험 hash다.

### mutation

정상 X/Y 49 PASS 뒤 새 B01~B10과 기존 M29~M44 **26/26 검출**, survived/invalid 0이다.
기존 요청 범위보다 넓게 FIX1의 16개를 모두 재적용했다. 사본마다 변이는 하나이며
import 출처·변이 전후 source hash·실패 node·로그를 남겼다. XML의 목표 실패가
AssertionError/pytest assertion 또는 DID NOT RAISE인지 별도 감사했다. 수집·import·
setup 오류는 0이고 각 mutant exit는 1이다. workspace에는 변이를 적용하지 않았다.

| 변이 | 실패 node 수 | 주요 목표 |
| --- | ---: | --- |
| B01 / B02 | 9 / 9 | Y 유지 완전 요약의 사실 표시 / 버튼 활성 |
| B03 / B04 | 6 / 4 | Y 초점 이탈 자동 추종 / 사용자 열람 유지(후자는 X07도 검출) |
| B05 | 18 | Y 초점 유지 snapshot 불변 |
| B06 / B07 | 3 / 9 | Y 선택 거부 안내 / 거부 알림 1회 |
| B08 / B09 | 4 / 6 | Y snapshot slot 거부 / 콤보 복귀(B08은 X 경로도 검출) |
| B10 | 6 | Y 초점 이탈 뒤 새 snapshot |
| M29~M36 | 4 / 1 / 20 / 23 / 1 / 1 / 1 / 1 | 각각 X01~04 / X02 / X05~06 / X07 / X03 / X14 / X15 / X16 |
| M37~M44 | 4 / 1 / 1 / 1 / 1 / 4 / 1 / 1 | 각각 X07 / X12 / X13 / X11 / X10 / X09 / X08 / X04 |

### 원 반례 재적용

`probe_fix1.py`와 `probe_combo_intent.py`를 원본 그대로 TEMP에 복사하고,
기준 제품 코드와 수정 제품 코드 각각에 재적용했다. PYTHONPATH는 각 사본 src다.
첫 실행은 stdout의 cp949 인코딩 때문에 JSON 출력 단계에서만 실패했다. 스크립트를
고치지 않고 `PYTHONIOENCODING=utf-8`로 다시 실행해 양쪽 모두 exit 0이었다.

- C: 초점 링크·FIRST 본문 보존은 그대로다. FIRST의 안내는 “선택 요약 아님”이고
  완전 요약의 버튼은 활성이다. 초점 이탈 뒤에는 기존 FIRST 대신 새 THIRD를
  표시하며 snapshot도 새 선택을 읽는다. 선택되지 않은 요약을 선택됨으로 쓰지 않는다.
- G1: 선택 읽기 거부에 안전 안내가 생겼고 seek 0, DELETE_PENDING→DELETED_LOCAL
  처리는 유지된다. 직접 `load()` 호출이 삭제 의도 StateConflict로 거부되는 것은
  기준과 동일한 기존 동작이며 이 배정에서 바꾸지 않았다.
- combo intent: 기준의 slot_errors=[StateConflict]가 **[]**로 바뀌고, 거부된 TWO가
  아닌 기존 ONE 본문·콤보를 유지한다. Y 거부 행은 이 경로의 알림 1회·쓰기 0도 본다.
- G2 세션 왕복 뒤 새 snapshot, G3 확인 중 새 active 알림→충돌 및 기존 active 보존은
  그대로다.

### 증거 위치·한계

TEMP 도구·보고 root는
`C:/Users/gangd/AppData/Local/Temp/recoryn-g12b-tools-vegy7_0i/`다.
원 리드 도구는 수정하지 않고 복사본의 BASE와 4파일 scope만 바꿔 사용했다.
`run.py new`, `run.py related`, `mutations.py D:/project/Recoryn`, `probes.py`,
`g12_ci.py D:/project/Recoryn`이 정확한 명령·선택·환경을 보존한다.
`initial.json`, `environment.json`, `mutations.json`, `assertion-audit.json`,
`probes.json`, `ci-input-map.json`, `child-import.txt`가 hash·node·로그를 연결한다.
신규 최종 사본은 `recoryn-g12-new-6e910f75b73c41cc9d85b1b8b56b6ddb`,
관련 사본은 `recoryn-g12-related-e6e747fcb51c407185b6c0212dbfa852`다(둘 다 OS TEMP).

실제 Narrator·IME·장비·음성·GPU·모델·외부 제공자·유료 호출은 NOT_RUN이다.
유한 Y 행과 기존 property bound 밖 GUI 이력은 증명하지 않는다. 작성자 자체
검증이며 독립 검토나 C00의 최종 종결을 대신하지 않는다. CI 전체 coverage와
묶음 예산의 최종 결과는 실행이 끝난 뒤 아래에 추가한다.

### CI core 동등 최종 결과·입력 동결

사본은 OS TEMP의 `recoryn-g12-ci-0277130c46e2413294383ddc9ee6feec`다.
소유 범위 밖의 작업 트리 변경은 반영하지 않았다. archive의 추적 파일 전체와
4파일 overlay **385개**를 실행 전후 LF 정규화로 비교해 차이 0이다. 정렬된
상대 경로→LF SHA-256 map을 compact JSON으로 직렬화한 tree SHA-256은
`c5165e15fb5ddb7fd93863ce9c7eadbab426e895cc3c7e0288cb70a73e73a7e8`이다.
문서는 범위 절을 추가한 판이며 이후 구현 결과 추가만 다르다. 코드·시험 3파일은
실행 전후와 최종 workspace가 모두 같다. 기존 문서 78,695바이트(LF)의 hash는
시작 값 `144fc42f…7215`와 같고 그대로 prefix로 남아 있다.

| CI 단계 | 실제 결과 |
| --- | --- |
| Ruff check src tests scripts packaging | PASS |
| Ruff format --check, 같은 범위 | PASS, 200파일 |
| MYPYPATH=src mypy src/recoryn scripts packaging | PASS, 92 source파일 |
| 전체 pytest, branch coverage·fail-under=85 | **24,689 PASS, 1,801.20초**, failures/errors/skipped 0, 총 결합 coverage 92.54% |
| scripts/check_coverage.py | 아래 7묶음 모두 PASS |

| 묶음 | line % | branch % |
| --- | ---: | ---: |
| domain | 99.18 | 97.89 |
| capture | 99.85 | 98.57 |
| jobs | 99.19 | 95.61 |
| storage | 95.95 | 91.41 |
| security | 98.11 | 94.43 |
| content | 98.98 | 99.02 |
| all | **93.90 (14,742/15,700)** | **88.56 (4,761/5,376)** |

핵심 6묶음은 line 95/branch 90, all은 85/80 기준이다. `ui/content.py`는
line 560/591, branch 154/178이며 결합 표시는 93%다. coverage의 결합 값과
분리된 line/branch를 혼동하지 않는다.

실제 cwd는 위 사본이고 실행 명령은 다음과 같다(`python`은 저장소의 기존
`.venv/Scripts/python.exe`). mypy/ruff cache를 사본에 제한한 옵션 외 검사·pytest
flag는 core.yml과 같다. 설치 금지에 따라 의존성 설치 단계는 실행하지 않았다.

```text
python -m ruff check --no-cache src tests scripts packaging
python -m ruff format --no-cache --check src tests scripts packaging
MYPYPATH=src python -m mypy --no-incremental --cache-dir <사본>/.mypy src/recoryn scripts packaging
python -m pytest -q -p no:cacheprovider -W error::ResourceWarning --basetemp <사본>/bt --cov=recoryn --cov-branch --cov-report=term-missing --cov-report=json:coverage.json --cov-fail-under=85 --junitxml <사본>/ci-junit.xml
python scripts/check_coverage.py coverage.json
```

추가 wheel 검사는 기존 설치 환경만 사용했다. 첫 실행은 pip 기본 cache의
쓰기 권한으로 실패했고, TEMP 실행 도구도 그 cp949 로그를 UTF-8로 읽다가
실패했다. 원 `ci-wheel.log`를 보존했다. 제품·시험을 바꾸지 않고 아래처럼
cache를 TEMP로 지정하고 캐시와 build isolation을 끈 재실행은 exit 0이다.
네트워크·의존성 설치·wheel 설치·배포는 하지 않았다. 원격 CI나 clean build
인증이 아니며 원 core.yml의 설치/빌드 격리 단계와의 차이를 명시한다.

```text
PIP_NO_INDEX=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_CACHE_DIR=<사본>/pip-cache PYTHONIOENCODING=utf-8
python -m pip wheel --no-deps --no-build-isolation --no-cache-dir --wheel-dir dist .
```

wheel은 325,028바이트, SHA-256
`b5dfee7f5114a87932a1f05140e479aedfbceb3901cd4252ccb40d995d278e80`다.
TEMP root의 `wheel-result.json`과 사본의 `ci-wheel-temp.log`가 성공 근거다.

| 증거 (LF SHA-256) | 값 |
| --- | --- |
| ci-junit.xml | `f004e6169a823e241ad92b7a466a67142224de2c54d3e7a068330f7bbc27769e` |
| coverage.json | `4cab098c2f64a89b8203a8e10a23090c30d5d24e0decfa97c76e68072c285db0` |
| 신규 최종 new.xml | `db1c1d351af2d5b15f64d485150fe014e43a5b742b542f37dbd50e9a7d5325d9` |
| 관련 related.xml | `1e3c27507d25b6ecd53d26a613b4225963fec7b409876041dda62ba913287555` |
| mutations.json | `b78f441936c07329f0a54f7cdecc23ff02befbcde69274e68a2700cb155cfb0c` |
| assertion-audit.json | `ac29a8da279bde8f5e03bbbfd05126904313dc81bd34f522ea6aec23b8e95389` |
| probes.json | `648a5624b90925f71b40a8ef4e3cc7e84ce6e1a2d5ad0b7b9bb303604265a5dc` |

최종 코드·시험의 LF SHA-256:

- `src/recoryn/ui/content.py`: `29c9978dc0cd0b7f966510e8f93db27b9a43f7733d2a9fd1f3d59d20b6e624d5`
- `tests/ui/test_basis_a11y_ui.py`: `53f209aba242f53644e5d5cac479c0c9bee4fcd32d508864e4062c59a88b3dbc`
- `tests/property/test_basis_a11y_case_space.py`: `44a2fd6d1cb7828185eeafd22f9c0911181072c8ebef6bc538bfdd5f66e513b7`

수락 기준 변경 요청은 없다. G1 직접 load 거부는 기존 범위 밖 동작으로 유지했다.
최종 상태는 작성자 **IMPLEMENTATION_READY**이며 독립 검증·검토 및 C00 종결은 대기다.
