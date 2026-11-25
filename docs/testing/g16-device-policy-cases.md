# G16 / G-P16 장치 실행 정책 저장·복원 계약안

상태: **구현 완료 — G16 IMPLEMENTATION_READY, 독립 검토·C00 통합 대기**. 계약 작성 w5:p8 Codex(기준 `90c612378e0cdb991319098124f9139fac4817fd`), 구현 Claude(C00 배정 G-P16, 기준 `b6da7e0`). C00 결정 ①–⑤를 승인 조건(실제 진입점 `run()` 배선 시험)과 함께 반영했다. 1–9절은 승인된 계약안이며 구현·설계 결정·실행 결과는 §10이다. Narrator 실사용·실장비·다른 PC 복원·실제 G-P09 backup 대조는 외부 게이트로 남는다.

## 1. 요구·위험·직접 확인한 근거

정본은 `docs/implementation/v1-gap-plan.md`의 G-P16 행과 G-P11 재대조에 대한 C00 결정 ⑤(나)다. 장치 정책을 비밀이 아닌 일반 설정으로 저장한다. 매번 CPU_ONLY로 초기화하여 사용자가 고른 Ollama 실행 정책을 잃는 문제를 해결하되, 저장된 정책을 전송 동의·모델 확인·비용 승인으로 사용하지 않는다. 녹음은 설정 I/O·AI 실패와 독립한다.

다음 줄번호는 작업 트리 src가 아니라 **`git show 90c6123:<경로>`로 읽은 코드**다. 미완성 G-P15b·G-P07 변경을 커밋된 구현처럼 인용하지 않는다.

| 기준 근거 | 직접 확인한 사실과 계약 영향 |
| --- | --- |
| `90c6123:src/recoryn/ui/main.py:267` | 콤보박스 항목은 CPU_ONLY, GPU_ONLY, GPU_WITH_CPU_FALLBACK_ALLOWED 순이다. 저장·복원 연결이 없어 CPU_ONLY가 초기값이다 |
| `90c6123:src/recoryn/models/resources.py:61` | 실제 정책 문자열은 위 세 가지다. AUTO 문자열은 허용되지 않는다. GPU_ONLY는 GPU 부재 시 거부하고 fallback 정책만 CPU를 허용한다 |
| `90c6123:src/recoryn/ui/ai_bridge.py:169` | 전사 준비 때 GUI에서 정책을 읽어 worker closure로 전달한다. 새 설정을 작업 도중 위젯에서 다시 읽는 경로를 만들지 않는다 |
| `90c6123:src/recoryn/ui/ai_bridge.py:222` | 로컬 STT 키는 모델 digest와 **선택된 실제 device**로 구성된다. 정책 enum·저장 revision을 추가하지 않는다. 실제 device가 달라지면 기존 계획 키가 달라지는 사실과 구별한다 |
| `90c6123:src/recoryn/ui/ai_bridge.py:286` | 요약은 privacy의 실행 준비를 사용한다. 설정 복원이 동의·비용 준비를 생략하게 해서는 안 된다 |
| `90c6123:src/recoryn/ui/main.py:79`, `:101` | 녹음 제어와 미확정 목록용 worker pool이 있다. 설정 디스크 I/O를 GUI나 녹음 제어 pool의 긴 작업으로 넣지 않는다 |
| `90c6123:src/recoryn/ui/main.py:1155`, `90c6123:src/recoryn/cli.py:21` | 기본 library root는 LOCALAPPDATA 아래지만 명시 root도 지원한다. 아래 권고의 사용자·PC 설정 위치는 library root 선택과 독립한다 |
| `90c6123:src/recoryn/storage/_safe.py:73`, `:95`, `:155`, `:192` | 중복 키·타입·크기 검사, 로컬 경로·열기 identity 검사, 임시 파일/fsync/replace 패턴이 있다. 마지막 helper는 기존 JSON의 schema를 먼저 검증하므로 손상 파일을 묵시 수선하는 수단으로 사용하지 않는다. 디렉터리 fsync/전원 장애 내구성 보장은 없다 |
| `90c6123:docs/architecture-v1.md:91`, `:205`, `:235` | 의미 Job과 실행 조정을 구별하고, CPU 무동의 전환을 막으며, 키·헤더·본문을 일반 설정/로그/지원 번들에 넣지 않는다 |

계약 근거는 별도로 구분한다. G-P11 `§개정 요청` 2·3·6은 Ollama strict 차단, 정책 저장의 후속 분리, 명시 계속의 새 snapshot을 요구한다. G-P07 §3.5와 실행 결과의 `execution_policy` 탐색 행동은 정책 위치로 이동할 뿐 값을 변경·저장하지 않는다. 둘 다 90c6123에 구현되어 있다는 뜻이 아니다. G-P09 §3·§5와 개정은 backup 구성요소 정본을 정하므로 아래 제외 결정을 인계한다.

주요 위험은 이전 정책 소실(S2), 손상 설정의 권한 완화·기존 작업 변경(S2), 설정 오류가 녹음 시작을 막는 회귀(S1)다. 정책 설정은 같은 사용자 권한의 악성 프로그램에 맞서는 보안 권위가 아니다.

## 2. 권고 계약: 범위·형식·API

### 2.1 저장 범위와 정책 이름

**사용자·PC 단위, library root와 독립한 일반 설정 파일**을 권고한다. Windows 위치는 `%LOCALAPPDATA%/Recoryn/preferences/device-policy.json`이다. LOCALAPPDATA가 없거나 안전한 로컬 절대 경로로 판정할 수 없으면 임의 cwd/모델 폴더로 대체하지 않고 CPU_ONLY·저장 위치 확인 필요를 표시한다. OS 경로 resolver는 주입 가능하게 하여 시험이 실제 사용자 설정을 읽거나 쓰지 않게 한다. 실행 중 임의 파일 경로를 입력받아 로드하지 않는다.

파일은 UTF-8 JSON, 최대 **4,096 bytes**이며 허용 필드는 다음 둘뿐이다.

```json
{"schema_version":1,"execution_policy":"CPU_ONLY"}
```

- v1 수락은 version의 정확한 int 1(bool 제외), policy의 정확한 str 세 enum 중 하나를 요구한다. 누락·추가 키·중복 키·NaN·잘못된 UTF-8·비객체·초과 길이는 거부하고 float를 v1 version/policy로 수락하지 않는다. **parse 가능한 객체의 version이 정확한 int이고 1보다 크면 v1의 나머지 키·policy 타입 검사보다 먼저 FUTURE_VERSION으로 보존**한다. 미래 형식의 추가 필드·다른 policy 구조를 v1 손상으로 오인해 재설정으로 덮지 않는다. 이 헤더 검사에는 JSON의 합법적 float를 전역 거부하는 기존 strict_json을 그대로 쓰지 않는다. 미래 본문에 `[0.5]` 같은 값이 있어도 실행 정책으로 해석하지 않고 보존한다. 추가 키의 값이 비밀이어도 파서 오류/로그에 값을 복사하지 않는다.
- UI의 **AUTO는 GPU_WITH_CPU_FALLBACK_ALLOWED의 표시 별칭**이다. 네 번째 정책을 만들지 않고 파일·ResourceRequest에는 기존 enum을 쓴다. literal `AUTO` 저장 입력은 타입상 문자열이어도 미지원 값이다. UI는 “AUTO — GPU 우선, CPU 사용 허용”으로 뜻을 드러낸다.
- CPU_ONLY/GPU_ONLY는 이 PC의 owned 추론 약속이다. REMOTE에는 “이 PC의 장치 정책 적용 안 됨”, Ollama에는 G-P11의 server_unknown/사전 차단을 그대로 표시한다. 저장 성공을 GPU 실행 가능·서버 GPU 보장으로 표시하지 않는다.

### 2.2 읽기 결과와 안전 실패

신규 `app/device_policy.py`에 frozen `PolicyPreference`와 `PolicyReadResult`, `PolicyWriteResult`, `DevicePolicyStore`를 제안한다. `load()`는 예외가 MainWindow 생성으로 전파되지 않는 안전 결과를 반환한다. `save(policy, *, observed_revision)`·`reset_invalid(policy, *, observed_revision, confirmed)`는 worker에서만 파일을 변경한다. revision은 안전하게 읽은 원본의 digest/identity 또는 ABSENT를 나타내는 충돌 검사용 값이며 Job/config identity가 아니다. 임의 caller가 전달한 blob을 그대로 저장하지 않는다.

| 입력/상황 | 현재 실행 기본값·상태 | 원본 설정 처리 |
| --- | --- | --- |
| 파일 없음 | CPU_ONLY / DEFAULT | 읽기만으로 파일 생성하지 않음 |
| 정상 v1 | 저장한 enum / RESTORED | 읽기·복원은 저장 이벤트가 아님 |
| 손상·타입/알 수 없는 enum·옛 미지원 version | CPU_ONLY / INVALID | 자동 재작성·삭제 없음. 사용자 명시 재설정 전 보존 |
| 미래 version | CPU_ONLY / FUTURE_VERSION | 읽기 전용. save/reset 모두 덮어쓰기 거부, 지원 버전 앱 또는 사용자의 별도 파일 정리 안내 |
| I/O·경로·잠금 문제 | CPU_ONLY / UNAVAILABLE | 녹음·로컬 CPU 요청 가능. 설정 원문/예외 경로를 오류 본문으로 노출하지 않음 |
| 다른 앱/worker가 원본을 바꿈 | 현재 메모리 값 유지 / CONFLICT | observed revision 불일치 저장 거부·재조회 안내. 새 파일을 옛 UI 확인으로 덮지 않음 |

이 상태는 **설정 표시 상태**이며 새 Job 오류 코드가 아니다. 초기 확인 중에는 CPU_ONLY와 “설정 확인 중”을 보여 준다. 초기 설정에 의존하는 AI 준비는 미접수 안내로 잠시 보류할 수 있으나 녹음·정지·복구·삭제 UI를 보류하지 않는다. 사용자가 확인 중 명시 정책을 선택하면 그 선택을 현재 실행에 적용하고 옛 load 응답은 폐기한다. 파일 오류가 ResourceRequest에 None/임의 enum을 넣는 사유가 되지 않는다.

### 2.3 쓰기·경쟁·실패

정상 설정에서 사용자가 콤보박스를 **실제로 활성화한 선택**을 저장한다. 프로그램의 초기 복원·poll·탭 탐색은 저장하지 않는다. 바뀐 정책은 현재 실행의 새 요청에 즉시 적용하고 “저장 중”으로 표시한다. 저장 실패에는 “현재 실행: <정책> · 저장 안 됨, 다음 시작에 유지되지 않을 수 있음”을 표시한다. 이미 캡처된 작업 정책을 롤백하거나 녹음을 중단하지 않는다. 사용자가 명시 선택한 AUTO와 손상 파일에서 자동으로 AUTO를 복원하는 것을 구별한다.

- 설정 전용 직렬 worker와 사용자·PC 설정 위치의 **협력 프로세스 간 잠금**을 사용한다. 잠금 대기는 monotonic 상한 2초, GUI·Library root mutex·JobStore/security transaction 밖이다. 새 의존성 설치 없이 표준 라이브러리의 OS 잠금으로 구성한다. 같은 경로의 load/save/reset은 이 경계를 공유하고, revision 재검사와 replace 사이에 협력 writer가 끼지 못하게 한다. 악성 동일 권한 앱의 임의 파일 치환을 완전히 방어한다는 주장은 하지 않는다.
- 읽기와 쓰기 전에 비로컬 namespace/UNC/네트워크 매핑을 판정하여 거부하고, 로컬 경로의 구성요소·reparse/hardlink·열기 identity를 확인한다. 비로컬 경로를 먼저 realpath/stat으로 해석하지 않는다. 기존 작은 안전 파일 helper를 재사용하되 private Library journal/잠금을 복제하지 않는다.
- 검증된 새 payload만 같은 디렉터리의 고유 TEMP 파일에 쓰고 short write 검사→file fsync→원자 replace 순으로 게시한다. 이전 파일은 replace 전까지 유지된다. 성공은 완전한 v1 파일 게시까지이며 전원 장애 내구성 보장은 아니다. TEMP 정리 실패는 알려 주되 원본 설정이나 임의 경로를 지우지 않는다.
- 손상/옛 형식 설정은 일반 선택만으로 덮지 않는다. “설정 재설정”에서 현재 정책·손상 파일 교체 범위를 안내하고 기본 No·Esc 취소를 거쳐야 한다. 같은 revision과 지원 가능한 대상인지 worker에서 다시 검사한다. 미래 version과 검사할 수 없는 경로는 이 동작으로 우회하지 않는다.
- 같은 프로세스 저장은 선택 순서대로 직렬 처리한다. load 응답·save 응답에 UI generation을 붙여 늦은 응답이 새 선택·새 저장 상태를 덮지 못하게 한다. 다른 앱의 revision 충돌은 자동 덮어쓰기 재시도로 숨기지 않는다. 닫힌 창으로 돌아온 callback은 무시하며 저장 결과를 AI 자동 실행 신호로 쓰지 않는다.

## 3. 실행 snapshot·동의·계획 동일성

MainWindow는 안전한 현재 enum과 메모리 generation을 제공하고 G-P11a의 ResourceRequest 조립은 준비 시 이를 **한 번** 캡처한다. 저장 중/저장 실패도 현재 사용자가 고른 유효 enum을 바꾸지 않는다. QUEUED/RUNNING의 request/Attempt는 이후 UI 변경·디스크 재읽기로 수정하지 않는다. 디스크 저장 revision·시각·schema version·policy enum을 결과 config_key에 추가하지 않는다.

G-P07의 명시 계속은 현재 정책을 새 실행 snapshot으로 캡처하되 expected_job_id/version과 같은 입력·의미 키 검사, 실제 reader 종료 ACK를 유지한다. BLOCKED 일반 재요청은 자동 resume하지 않고, REMOTE_UNKNOWN은 계속으로 재개하지 않는다. **정책만 바뀌고 같은 의미/실제 device인 경우** 처리한 실시간 청크 재전송·요약 checkpoint 상실이 없어야 한다. 로컬 STT에서 실제 device가 달라지는 경우는 기존 `digest:device` 계약에 따라 CONTINUE_PLAN_CHANGED일 수 있으며 G-P16이 키에서 device를 제거하지 않는다.

G-P11 표의 REMOTE 적용 제외, Ollama CPU_ONLY/GPU_ONLY 차단, LOCAL_SHERPA의 GPU 미지원, profile UNKNOWN 실행 허용을 재정의하지 않는다. CPU_ONLY로 안전 실패하면 Ollama가 차단된다는 사실과 정책 설정 위치를 명확히 알린다. 경고를 없애려고 AUTO를 자동 선택하지 않는다. 정책 복원은 live STT checkbox, 모델 확인, grant/SendPermit, 키 reference, 가격/예산·UNKNOWN 정산 상태를 복원하지 않는다.

## 4. UI·비밀·G-P09 인계

기존 AI 실행 정책 control에 접근성 이름 “AI 실행 정책”, 설명 “새 요청에 적용, 진행 중인 작업은 기존 정책 유지”를 둔다. 현재 실행 정책과 저장 상태를 별도 label로 표시한다. 저장 중/손상/미래/저장 실패를 색만으로 구별하지 않는다. Tab/화살표/Enter/Space로 선택하고 설정 재설정은 별도 버튼·기본 거부 확인이다. 같은 상태 poll은 새 알림·디스크 쓰기를 만들지 않는다. G-P07 `execution_policy` 탐색은 탭/초점 이동만 하며 저장하지 않는다. G-P12의 접근성 adapter가 먼저 있으면 그 API에 연결하고 새 알림 체계를 중복 구현하지 않는다. Narrator 실사용 검증은 외부 게이트다.

파일은 policy/version만 담는다. credential 값·reference·provider endpoint·본문·모델 경로·grant·비용 상태·사용자 식별자를 추가하지 않는다. Credential Manager/SQLite에 정책을 중복 저장하지 않는다. 로드 오류의 원문 JSON/예외 문자열을 로그·진단·export에 넣지 않는다. 정책 같은 안전 enum의 상태 설명과 비밀/원문 기록을 구별한다.

**G-P09 backup 구성요소에는 넣지 않는 안을 권고**한다. 사용자·PC 자원 설정이므로 library/project bundle·restore/import·미디어 export·지원 번들로 옮기지 않는다. 같은 PC에서 다른 library를 열거나 restore하면 현재 PC의 유효 설정을 쓰고, 설정이 없는 새 PC라면 CPU_ONLY다. 어느 경우에도 가져온 bundle 값으로 현재 정책·grant·permit을 승격하지 않는다. G-P09b에 다음을 인계한다: preferences 디렉터리 제외, bundle에 해당 이름/필드가 있어도 정책으로 자동 채택 금지, 새 root의 권한 세대 규칙 유지. G-P16은 새 DB component/migration을 요구하지 않는다. 실제 G-P09 backup/restore 통합 대조는 그 단위의 후속 시험이며 여기서 fake PASS로 완료 처리하지 않는다.

## 5. 입력 분할·계획 분모

유한 대표 8가족을 전수로 계획한다. 각 가족 안의 Ω=F이며 거부 입력도 분모에 포함한다. 가족끼리 입력 축을 모두 곱한 전체 시스템 전수라고 주장하지 않는다. 각 ID는 한 의미 trace이고 내부 여러 assertion/같은 행의 계층 교차 확인을 중복 합산하지 않는다.

| 가족 / 유일 ID | 대표 입력 Ω=F | 계획 행 | 독립 oracle |
| --- | --- | ---: | --- |
| L / G16-L-001…096 | 파일 입력24 × library A/B2 × 첫 열기/재시작2 | 96 | 같은 PC의 다른 library에서도 저장 enum, 오류는 CPU_ONLY와 정확한 상태, 읽기 부수효과0 |
| P / G16-P-01…32 | 경로8 × read/save2 × 권한 정상/거부2 | 32 | 비로컬 접근0, 링크 거부, 오류가 창/녹음으로 전파되지 않음 |
| W / G16-W-001…108 | 기존 enum3 × 새 enum3 × 쓰기 결과6 × 같은 실행/재시작2 | 108 | 완전한 옛/새 JSON만 존재, 실패 과장0, 현재 명시 선택과 다음 시작 값을 구별 |
| S / G16-S-001…180 | 옛 정책3 × 새 정책3 × Job 단계5 × backend4 | 180 | 불변 snapshot·같은 의미 키·명시 계속·UNKNOWN 금지·독립 권한 검사 |
| R / G16-R-01…72 | 명명 순서8 × 옛 정책3 × 새 정책3 | 72 | 늦은 load/save callback이 새 선택을 덮지 않음, 창 닫힘·협력 writer 충돌 |
| F / G16-F-01…32 | 기존 설정 상태8 × 동작4 | 32 | 미래/검사불가 보존, 손상 재설정은 확인·revision 일치만, No/Esc 쓰기0 |
| U / G16-U-01…80 | UI 상태10 × 실제 키4 × 동일poll/새 의미2 | 80 | label·초점·중복 알림·저장 호출 수와 fail safe 안내 |
| N / G16-N-01…36 | 정책3 × load/change/reset3 × canary 종류4 | 36 | 저장 allowlist, secret/vault/SQLite/전송/모델 factory0, 녹음 독립 |
| **합계** | 96+32+108+180+72+32+80+36 | **636** | 구현·실행0 |

L24는 순서대로 파일 없음/정상CPU/정상GPU/정상fallback/빈파일/깨진JSON/잘못된UTF-8/중복키/배열/version누락/version0/version2/version=True/version="1"/policy누락/policy=None/policy=True/policy=1/미지원문자열/literal AUTO/추가키/정상JSON+공백 총4095/총4096/총4097 bytes다. 마지막 경계는 valid JSON 뒤 허용 공백으로 길이만 바꾼다. 이름이 다른 invalid 입력을 하나의 “전부 예외” assertion으로 합치지 않는다.

P8은 fixed 로컬/상대/UNC/extended namespace/device namespace/network mapping/reparse/hardlink다. 권한 거부 flag는 거부 경로에서는 도달하지 않아야 하는 가짜 OS 응답이며 그 조합을 제외하지 않는다. removable/RAM disk·상위 링크 변형은 같은 허용/거부 규칙의 속성 보강으로 별도 ID 접두사에 기록한다.

W6은 성공/TEMP열기거부/short write/fsync실패/replace실패/협력잠금timeout이다. fault hook에 도달하지 않는 멱등 경로라면 호출0도 검증한다. 재시작은 새 store 인스턴스로 실제 TEMP 파일을 읽으며 기존 메모리 enum을 expected로 사용하지 않는다. 별도 정리 경고 보강은 G16-X- ID로 구분하며, rename 뒤 이미 사라진 TEMP의 unlink 실패를 불가능한 기본 조합으로 넣지 않는다.

S의 단계5는 준비/QUEUED/RUNNING/알려진 BLOCKED/REMOTE_UNKNOWN, backend4는 CT2-STT/SHERPA-화자/OLLAMA-요약/REMOTE-STT다. 각 행은 변경 전 요청, 사용자 선택, 변경 후 새 요청 또는 명시 계속의 trace다. 실제 장치 선택과 정책 enum을 분리한 손작성 기대표를 쓴다. 같은 의미 키 유지 행과 실제 device 변경으로 계속 거부되는 행을 함께 관측한다. 지원되지 않는 정책/backend도 거부 행이다. G-P11 자원 탐지 조합 전체를 여기서 재계수하지 않는다.

R8은 (1) load응답→선택→save응답, (2) 선택→load응답→save응답, (3) 선택→save응답→옛load응답, (4) 선택1/저장1완료→선택2/저장2완료, (5) 선택1→선택2→옛save1응답→save2응답, (6) 두 저장은 순서대로 commit했으나 GUI 응답2→응답1, (7) 저장 중 창닫힘→늦은 응답, (8) 다른 프로세스의 revision 변경→옛revision 저장 거부다. 정책쌍이 같아도 중복 이벤트/알림·쓰기 수를 관측한다. 앞3개는 선택<save라는 DAG의 linear extension 3개이며, 나머지5개는 명명 경합 trace다. 모든 길이의 명령열 전수라고 부르지 않는다.

F8은 미래기본/미래+추가필드/미래+v1과다른policy타입/깨진JSON/현재형식타입오류/UTF-8오류/경로·권한검사불가/정상설정, 동작4는 load/일반선택저장/확인한재설정/취소한재설정이다. 취소는 No/Esc를 같은 trace 안에서 각각 확인한다. 오류가 겹치면 비로컬·경로검사→bounded read→문법/중복/객체형식→version 타입·미래판정→현재version의 필드집합·policy 타입·enum 순으로 안전 판정하며, 읽을 수 없는 파일을 정상 부재로 취급하지 않는다. 미래3상태 모두 FUTURE_VERSION이고 모든 쓰기/재설정 경로에서 원본 bytes를 보존한다.

U10은 확인중/기본값/복원됨/저장중/저장됨/손상/미래/저장실패/충돌/창닫힘이다. 키4는 Tab/Enter/Space/화살표이며 실제 Qt 입력으로 control·reset·탐색을 통과한다. N4는 key 값/credential reference/grant 표식/비용·본문 표식이다. 작은 비민감 canary를 전달한 오류와 관련 패널 fake를 두고 저장 파일·오류 label·캡처 로그·내보내기/지원 번들 경계에 원문이 없음을 확인한다.

## 6. 독립 oracle·기존 시험·계층

- load 기대표는 제품 parser/enum 변환/정책 표를 import하지 않고 문자열과 고정 bytes로 손작성한다. 파일 hash는 표준 hashlib를 쓸 수 있으나 제품 serializer를 expected 파일 생성에 사용하지 않는다. 저장한 payload의 **정확한 두 키와 타입**, 다음 인스턴스가 읽은 값, 이전 파일 bytes 불변을 함께 대조한다.
- ResourceRequest fake는 요청마다 캡처한 enum을 기록한다. Job 상태·config_key·checkpoint·청크 호출 수·grant/비용 fake의 호출 수를 독립 관찰한다. 정책만 바꾼 실시간 요청에서 이미 처리한 청크 재전송0, 같은 의미 요약 checkpoint 유지가 핵심이다. REMOTE/Ollama의 권한 차단과 UNKNOWN 재전송 금지는 설정 성공과 별개로 검사한다.
- Event/barrier로 R의 순서를 강제하고 GUI thread의 파일/잠금 호출을 spy로 거부한다. 잠금 경합은 두 store thread와 소유 subprocess로 검사하며 자식 PYTHONPATH와 import origin이 TEMP 사본임을 확인한다. 잠금 timeout은 fake monotonic으로 경계를 검증하고 CI 속도에 의존하는 짧은 sleep assertion을 만들지 않는다.
- 작은 실제 TEMP 파일·fault writer로 W/F/P를 검증한다. 실제 사용자 설정·Credential Manager·GPU·weights·Ollama 서버·네트워크·설치를 사용하지 않는다. fake recorder의 start/submit/stop이 설정 손상·저장 대기 중에도 완료됨을 N에서 확인한다. 이것을 실제 장치 검증으로 집계하지 않는다.
- `90c6123:tests/unit/test_models.py::test_gpu_policy_has_no_silent_fallback`은 scheduler의 기존 세 정책 동작이며 저장/재시작 검증은 아니다. `tests/ui/test_gpu_runtime_ui.py::test_gpu_only_without_gpu_shows_the_reason`은 기존 오류 표시 회귀다. G-P11a의 신규 `test_resource_policy_ui.py`와 G-P07의 `test_blocked_reason_ui.py`는 선행 구현 후 실제 node를 연결한다. 아직 없는 시험 결과를 PASS로 옮기지 않는다.

신규3파일은 unit에 L/P의 순수 분할·독립 ID manifest, integration에 W/R/F/N의 파일·재시작·협력 process, UI에 S/U·일부 N의 실제 Qt/fake service를 배치한다. 같은 ID의 교차 assertion을 중복 집계하지 않는다. 계획 manifest 636과 수집/실제 assertion ID를 비교해 missing/duplicate/extra=0, skip0을 수락 조건으로 한다. 보강 행은 G16-X- 접두사로 분리한다. 새3시험 합계 **60초** 게이트, 초과 시 축약 전에 측정값·최적화/축약안을 C00에 보고한다.

## 7. mutation 계획

정상본 PASS 뒤 OS TEMP의 pyproject/src/tests/scripts/packaging 사본에서 하나씩 실행한다. PYTHONPATH를 사본 src로 고정하고 자식 import origin도 확인한다. assertion 실패만 검출이며 수집/import/권한/timeout은 invalid다. 실제 workspace 파일을 변이하지 않는다.

| ID | 명명 결함 | 검출 목표 |
| --- | --- | --- |
| M01 | 정상 저장값을 읽지 않고 항상 CPU_ONLY | L/W 재시작 |
| M02 | 손상 입력을 AUTO로 복원 | L/F 안전 기본값 |
| M03 | version의 bool을 int로 수락 | L 정확한 타입 |
| M04 | literal AUTO·미지원 enum을 정상 저장 | L/N 정확한 allowlist |
| M05 | 미래 version을 v1으로 자동 덮어씀 | F 원본 bytes 보존 |
| M06 | TEMP/replace 없이 원본 직접 쓰기 | W 중단 전후 완전한 파일 |
| M07 | short write/fsync 실패를 저장 성공으로 표시 | W/U 정확한 결과 |
| M08 | 늦은 load 응답의 generation 검사 제거 | R 새 선택 보존 |
| M09 | 옛 save 응답이 새 상태를 덮음 | R/UI 최신 상태 |
| M10 | 정책 enum·저장 revision을 config_key에 추가 | S 청크 재전송0/checkpoint 유지 |
| M11 | 실행 중 ResourceRequest를 현재 UI 값으로 수정 | S queued/running snapshot |
| M12 | 정책 선택으로 BLOCKED를 암묵 resume | S G-P07 명시 계속 |
| M13 | REMOTE_UNKNOWN 계속 허용 | S UNKNOWN/dispatch0 |
| M14 | 복원 완료를 AI 자동 실행·grant 복원으로 연결 | N 독립 권한·호출0 |
| M15 | 임의 필드/오류 원문을 설정·로그에 기록 | L/N canary·두 키 schema |
| M16 | 설정 I/O·잠금 대기를 GUI/녹음 제어 경로로 이동 | R/N thread spy·녹음 독립 |
| M17 | 협력 잠금/revision 재검사 제거 | R/F 두 writer·미래 파일 보호 |
| M18 | 저장 실패로 MainWindow 생성/녹음·기존 snapshot 실패 | N 창/원본·진행 작업 보존 |

## 8. 정확한 제안 쓰기 범위·착수 순서

**9파일**을 제안한다. 지금 허용은 이 문서 하나다. 구현은 **G-P07 → G-P11a push 뒤 C00 신호**로 착수한다. G-P11b·G-P12·G-P13과 ai_bridge가 겹치므로 동시에 쓰지 않고 C00가 순서를 고정한다. G-P11b/G-P12가 먼저 들어오면 그 snapshot·a11y·ACK 변경을 보존한다.

| 종류 | 파일 |
| --- | --- |
| 신규 source1 | `src/recoryn/app/device_policy.py` |
| 기존 UI2 | `src/recoryn/ui/main.py`, `src/recoryn/ui/ai_bridge.py` — 설정 control·worker·snapshot 조립만 |
| 신규 시험3 | `tests/unit/test_device_policy.py`, `tests/integration/test_device_policy.py`, `tests/ui/test_device_policy_ui.py` |
| 신규 시험 격리1 | `tests/ui/conftest.py` — 정책 resolver를 각 시험 TEMP로 격리, 제품 초기화/실제 load를 무조건 성공 fake로 우회하지 않음 |
| 선행 UI fixture1 | `tests/ui/test_resource_policy_ui.py` — G-P11a 뒤 초기 load 대기·명시 선택 fixture만 적응 |
| 문서1 | `docs/testing/g16-device-policy-cases.md` |

90c6123에는 tests/ui/conftest.py가 없음을 확인했다. G-P11a 착수 후 새 파일 충돌 여부를 다시 확인한다. 목록 밖 기존 fixture의 실제 실패가 나오면 최소 변경과 근거를 먼저 요청한다. jobs/failures·models/resources·app/ai·security·storage·cli·G-P09 문서는 이번 쓰기 범위 밖이며 기존 API로 snapshot 연결이 불가능하면 구현 전에 보고한다.

수락: 새3시험·case ID/시간·mutation18, tests/ui 전체·G-P02/P02b/P03/P06/P07/P11a 회귀, ruff check/format·`python -m mypy src/recoryn scripts packaging`, 정확한 선행 HEAD+허용파일 TEMP 사본에서 전체 오프라인 회귀와 CI 동등 coverage 전 묶음이다. 시험은 `QT_QPA_PLATFORM=offscreen`, `-p no:cacheprovider`, 고유 OS TEMP basetemp, `-W error::ResourceWarning`을 사용한다. 별도 독립 검토와 C00 통합이 필요하다.

## 9. 대안·C00 결정 요청

| 대안 | 장점 | 한계/권고 |
| --- | --- | --- |
| 매번 CPU_ONLY·저장 안 함 | 가장 단순 | 승인된 G-P16 문제를 해결하지 못함 |
| 사용자·PC JSON / 권고 | 작은 명시 schema·정확한 타입/버전·다른 library에도 같은 PC 정책 | worker·협력 잠금·오류 상태 필요, 다른 PC로 자동 이식하지 않음 |
| library 내부 설정·backup 포함 | 프로젝트별 선택·복원 편의 | PC 자원 설정이 다른 PC로 옮겨져 혼동, root별 초기값 소실. 선택하면 G-P09 component/restore 검증 추가와 분모 재산정 필요 |
| QSettings/레지스트리 | Qt 저장 기능 재사용 | 저장 위치·형식/미래 version·타입 검증을 별도 정의해야 함. headless 단위 시험·명시 backup 제외 증거가 복잡 |
| SQLite/Credential Manager | 기존 store 재사용 가능 | 비밀 아닌 한 enum에 DB migration/비밀 저장소 의존을 추가함. 녹음 시작을 그 오류와 결합할 이유 없음 |

C00 결정 요청: **①사용자·PC JSON 위치·AUTO 별칭·기본 CPU_ONLY, ②비동기 복원/저장과 현재 선택·저장 결과 분리, 손상 명시 재설정/미래 보존·협력 잠금, ③정책은 새 snapshot에만·config_key 불변 및 G-P07 계속 경계, ④G-P09 backup 구성요소 제외와 후속 인계, ⑤9파일·636행·mutation18·새3시험60초·직렬 착수**. 최종 문서 점검에서 미래 형식의 추가 필드/타입도 보존하는 F 8행을 더해 중간 보고의 628행을 636행으로 보완했다. 이 문서 작성으로 제품 구현/보안/실장비 검증이 완료된 것은 아니다.

## 10. 구현 결과 (G-P16, 기준 `b6da7e0`)

### 10.1 C00 결정과 적용

| 결정 | 적용 |
| --- | --- |
| ① 사용자·PC JSON·AUTO 별칭·기본 CPU_ONLY | `%LOCALAPPDATA%/Recoryn/preferences/device-policy.json`(`user_location`), 두 키 v1 payload, 화면 별칭 “AUTO — GPU 우선, CPU 사용 허용”. 파일·ResourceRequest에는 세 enum만 쓴다 |
| ② 비동기 복원/저장·현재 선택과 저장 결과 분리·손상 명시 재설정·미래 보존·협력 잠금 | 설정 전용 QThreadPool(최대 1), “현재 실행: <정책>”과 저장 상태를 한 label 안에서 분리한 문장, 손상일 때만 활성인 “설정 재설정”(기본 아니요), FUTURE_VERSION은 save/reset 모두 REFUSED, OS byte-range 잠금(msvcrt/fcntl)·monotonic 2초 상한 |
| ③ 새 snapshot에만·config_key 불변·G-P07 명시 계속=새 snapshot | bridge의 `_selected_policy()` 요청당 1회 캡처를 유지한다. config_key와 CT2 `digest:device` 키에 정책·revision을 넣지 않는다. 계속은 기존 G-P07 경로가 현재 선택을 새 snapshot으로 캡처한다 |
| ④ G-P09 backup 제외 | 설정은 library root 밖 사용자·PC 위치다. DB component/migration을 추가하지 않는다. G-P09b 인계는 §4 그대로다 |
| ⑤ 9파일·636행·mutation 18·새3시험 60초·직렬 착수 | §10.5–10.7. `tests/ui/test_resource_policy_ui.py`는 적응이 필요 없어 변경하지 않았다 |

### 10.2 파일별 구현

- `src/recoryn/app/device_policy.py`(신규): `PolicyPreference`·`PolicyReadResult`·`PolicyWriteResult`·`DevicePolicyStore`(+`PolicyIo`, `PolicyLock`)와 GUI 측 `PolicyController`·`PolicyView`·`status_text`. 읽기 판정은 §5 F 순서(크기 → 문법·중복 키·UTF-8·NaN → 객체 → version 누락 → 정확한 int>1 미래 → 미지원 version → 필드 집합 → policy enum)다. UNC·`\\?\`·`\\.\`는 문자열만으로, 네트워크·알 수 없는 드라이브는 `GetDriveTypeW`(0/1/4)만으로 거부하고 열지 않는다. 로컬 경로는 `storage._safe.check_path`로 reparse/hardlink를 거부한다. 쓰기는 같은 디렉터리의 고유 TEMP → short write 검사 → fsync → `os.replace`다. replace의 공유 위반은 **그 호출 안에서만** 잠금 상한까지 재시도하고 실패는 FAILED이며 지속 상태를 남기지 않는다(GS02R-01 교훈). TEMP 정리 실패는 `WRITE_FAILED_TEMP_LEFT`로 구분한다. 같은 bytes면 쓰지 않고 SAVED(멱등)다. revision은 sha256(원본)+크기 또는 ABSENT다. 읽기는 잠금 파일·디렉터리를 만들지 않는다.
- `src/recoryn/ui/main.py`: `PolicyComboBox`, `default_policy_store()`, `user_window()`, `MainWindow(policy_store=...)`, 상태 label·재설정 버튼, 설정 worker, 닫기 처리.
- `src/recoryn/ui/ai_bridge.py`: 접근성 설명만 변경(“새 요청에 적용, 진행 중인 작업은 기존 정책 유지”, AUTO 의미, 저장 위치, 기존 “자동으로 바뀌지 않음” 유지). `_selected_policy()`는 그대로 `currentText()`(enum)를 캡처한다.
- `tests/ui/conftest.py`(신규): tests/ui의 모든 MainWindow가 창마다 TEMP의 실제 `DevicePolicyStore`를 쓰도록 `default_policy_store`만 교체한다. 제품 초기화와 실제 load/save는 그대로 실행되며 LOCALAPPDATA도 TEMP다.

### 10.3 설계 결정 (C00 승인, 조건 포함)

1. **store=None은 메모리 전용**: store 없이 만든 창은 `default_policy_store()`가 정하며 기본값 None은 읽기·쓰기 0, “이 창은 설정을 저장하지 않음”(NO_STORE)이다. 통합 시험·도구가 만드는 창은 사용자 설정을 건드리지 않는다.
2. **실제 진입점 배선(C00 조건)**: `run()` → `user_window(library)` → `MainWindow(library, policy_store=DevicePolicyStore.for_user())`. G16-X-01은 LOCALAPPDATA를 TEMP로 돌리고 `QApplication.exec`만 대체해 `run()`을 두 번 실행한다. 첫 실행은 DEFAULT/CPU_ONLY에서 실제 ↓ 키로 GPU_ONLY를 저장하고 파일이 정확히 v1 GPU_ONLY bytes다. 두 번째 실행은 RESTORED/GPU_ONLY다. “run()이 None을 넘기는” 변이 M19를 검출한다.
3. **conftest**는 factory만 창별 TEMP 실제 store로 바꾼다. 항상 성공하는 fake로 우회하지 않는다.
4. **콤보 AUTO 별칭·enum 호환**: 표시 텍스트는 별칭, `currentText()`는 item data(enum), `setCurrentText(enum|표시 문자열)`은 data를 먼저 찾는다. 기존 호출부와 G-P11/G-P07/G-P12 시험은 수정 없이 통과한다.
5. **프로그램 선택 규칙**: `currentIndexChanged`는 사용자·프로그램 모두 현재 실행에 즉시 적용하고 generation을 올린다. 늦은 초기 load 응답은 그 선택을 덮지 않고 저장도 하지 않는다(G16-X-02). 복원 값 적용은 guard로 선택 이벤트를 다시 만들지 않는다.
6. **저장은 사용자 `activated`에서만**: Qt는 닫힌 콤보의 화살표 키에도 `activated`를 내므로 키보드 선택도 사용자 선택으로 저장한다(U Arrow 행). 복원·poll(tick)·Tab·G-P07 `execution_policy` 탐색은 저장하지 않는다(U Tab/same 행, S 준비 행의 탐색 확인).
7. **worker 측 revision 사슬**: load가 FIFO로 먼저 관측 revision을 기록하고, 직렬로 대기한 저장은 앞 저장의 새 revision을 이어받는다. CONFLICT 이후 이미 대기하던 저장은 자동 덮어쓰기 대신 CONFLICT로 보고한다. 사용자가 충돌 표시를 본 뒤 다시 고르면 새 관측 revision으로 저장한다.
8. **늦은 응답**: 저장 응답은 최신 ticket만 반영하고, load 응답은 그 뒤 저장 요청이 있으면 상태를 덮지 않는다. 닫힌 창의 응답은 무시하되 이미 시작된 쓰기는 shutdown의 `waitForDone`으로 끝까지 완료한다(U CLOSED 행의 파일은 v1 CPU_ONLY).
9. **손상·미래 파일에서의 일반 선택**: 현재 실행에는 적용하고, 저장 요청은 worker의 store가 잠금 안에서 다시 판정해 거부한다(RESET_REQUIRED/FUTURE_VERSION, 원본 bytes 불변). 그 사이 표시는 잠시 “저장 중”이다. 재설정은 손상 상태에서만 활성이며 확인(기본 아니요·Esc) 뒤 같은 revision일 때만 교체한다.
10. **알림**: G-P12 adapter(`a11y.qt_announce`, POLITE/ASSERTIVE)를 쓰고 같은 (상태, 정책)은 다시 알리지 않는다. 손상·미래·위치 문제·저장 실패·충돌은 ASSERTIVE다. 상태는 문장으로 구별한다. CPU_ONLY/GPU_ONLY에는 “로컬 Ollama 요약은 이 정책에서 차단됩니다(필요하면 AUTO를 직접 선택)”을 덧붙이며 AUTO를 자동 선택하지 않는다.

### 10.4 시험 fixture 해석·편차

- U의 Enter/Space는 실제 키로 재설정 버튼에 도달한다. Enter=예, Space=아니요 응답으로 배치했고 두 키 모두 확인창 1회·중복 실행 0이다. No/Esc 각각의 쓰기 0은 F 취소 행이 같은 trace에서 확인한다.
- U 행은 같은 창의 콜백(`_policy_submit`, `_show_policy`)에 행마다 새 PolicyController를 묶어 상태를 만든다. 생성자 배선은 S 환경·CLOSED 창·X-01이 실제 생성자로 확인한다. U store는 GUI thread 호출을 즉시 실패시키는 감시를 둔다.
- S의 CT2 장치 계획은 이 fixture의 GPU 없음 손작성 표(CPU_ONLY/AUTO→cpu, GPU_ONLY→DEVICE_UNAVAILABLE)로 `scheduler.prepare`를 대체한다. G-P11 자원 탐지는 재계수하지 않는다. 거부 조합의 옛 capture는 같은 backend의 허용 정책으로 접수한 뒤 거부 capture를 보관한다(G11 Ua 주석의 “이 빌드 이전 capture”). CT2 행은 같은 의미 키를 공유하므로 행별 request nonce를 bridge가 기억하는 방식으로 둔다.
- 구현으로 확인한 G-P07 동작: CAPABILITY(PV)로 BLOCKED된 Ollama 작업도 명시 계속 대상이다. 현재 선택이 AUTO이면 새 snapshot으로 재접수되고, CPU_ONLY/GPU_ONLY이면 준비 전 PV로 기존 Job BLOCKED가 유지된다(T30 규칙과 같음). 초기 시험 기대값의 오류였고 제품 변경은 없다.
- P의 network mapping은 `GetDriveTypeW` 응답(4)을 fake로 주어 마운트 표 조회 1회 외 접근 0을 확인한다(실제 공유 미사용). reparse는 실제 NTFS junction, hardlink는 실제 hardlink다.
- W 잠금 timeout은 fake monotonic이다. 실제 프로세스 간 잠금 경합은 보강 X-04(자식 import origin=사본 src), 두 store 동시 저장은 X-05다.
- N의 녹음 독립은 실제 `RecordingService`·Library에 fake PCM block을 넣어 설정 worker가 막힌 동안 start/submit/stop 완료를 본다. 실제 장치 검증으로 집계하지 않는다.
- 보강 행(분모 636 밖): X-01 진입점 배선, X-02 프로그램 선택 호환, X-03 복원 시 AI 요청·준비·Job·dispatch 0과 접근성 이름/설명/별칭, X-04 프로세스 간 잠금, X-05 동시 저장, X-06 LOCALAPPDATA 없음(CPU_ONLY·위치 확인 필요·cwd 대체 0), X-07 NaN/Infinity·float version(미래로 오인 0), X-08 그 사이 다른 앱이 고친 손상 파일의 확인 재설정=CONFLICT와 미확인 재설정 I/O 0, X-09 TEMP 정리 실패 보고(`WRITE_FAILED_TEMP_LEFT`, 그 TEMP만 남김), X-10 충돌 전에 대기한 두 저장의 쓰기 0, X-11 worker 응답 누락의 안전 실패.

### 10.5 시험 배치·case ID 감사·시간

| 파일 | 정식 행 | 보강·manifest | 수집 node |
| --- | --- | --- | ---: |
| `tests/unit/test_device_policy.py` | L96·P32 | 분모 manifest 1 | 129 |
| `tests/integration/test_device_policy.py` | W108·R72·F32·N36 | X-02·X-04–X-11, manifest 1 | 258 |
| `tests/ui/test_device_policy_ui.py` | S180·U80 | X-01·X-03, manifest 1 | 263 |
| 합계 | **636** | 14 | **650** |

수집된 매개변수 ID를 손으로 쓴 계획 집합(L/W/S 세 자리, 나머지 두 자리)과 대조한 감사 결과 missing 0·duplicate 0·extra 0·skip 0이다(가족별 F32·L96·N36·P32·R72·S180·U80·W108). 신규 3파일은 정확한 사본에서 650 passed, **19.93초**다(60초 게이트). 기대값은 모두 손작성 bytes·문자열·표이며 제품의 parser·enum 표·label·serializer로 만들지 않는다. N은 vault·SQLite 호출을 **설정 worker thread에서만** 실패시키는 감시로 load·save·reset 전 구간을 덮고(녹음 thread의 SQLite는 허용), 저장 경로에 SQLite 호출을 넣은 즉석 변이를 N 24행이 검출했다.

### 10.6 mutation

OS TEMP의 `pyproject.toml`·`src`·`tests`·`scripts`·`packaging` 사본에서 한 번에 하나씩 적용했다. PYTHONPATH는 사본 src이며 매 변이 전에 `recoryn.__file__`이 사본 아래인지 확인했다. 판정은 pytest 종료 코드 1·failed>0·error 0·assertion 실패 줄 존재일 때만 KILLED다. 작업 트리 파일은 변이하지 않았다.

| ID | 명명 결함(적용 위치) | 결과 | 검출 행(예) |
| --- | --- | --- | --- |
| M01 | 정상 값을 읽어도 항상 CPU_ONLY (`_observe`) | KILLED 118 | L 정상 입력·W 재시작 |
| M02 | 손상 입력을 AUTO로 복원 (`_observe`) | KILLED 80 | L 손상 입력 |
| M03 | version bool을 int로 수락 (`classify`) | KILLED 4 | L version=True |
| M04 | literal AUTO·미지원 enum 저장 (`PolicyPreference`) | KILLED 36 | N AUTO 저장 거부 |
| M05 | 미래 version을 일반 저장으로 덮음 (`_write_locked`) | KILLED 3 | F 미래 3상태 선택 저장 |
| M06 | TEMP/replace 없이 원본 직접 쓰기 | KILLED 72 | W short write·fsync·TEMP 거부, N |
| M07 | 쓰기 실패를 SAVED로 표시 | KILLED 60 | W 실패 결과, N 저장 실패 |
| M08 | 늦은 load 응답 guard(ticket·generation) 제거 | KILLED 19 | R 선택→load, X-02 |
| M09 | 옛 save 응답이 최신 상태를 덮음 | KILLED 9 | R 선택1→선택2→옛 응답 |
| M10 | 정책을 config_key·CT2 키에 추가 (bridge) | KILLED 16 | S 명시 계속 재접수 |
| M11 | 선택 시 capture된 ResourceRequest를 현재 값으로 수정 | KILLED 144 | S QUEUED/RUNNING/BLOCKED capture 동일성 |
| M12 | 선택이 BLOCKED를 암묵 계속 (`_policy_activated`) | KILLED 26 | S 선택 단독 요청·준비 0 |
| M13 | REMOTE_UNKNOWN 계속 허용 (bridge) | KILLED 2 | S REMOTE_UNKNOWN 계속 거부 |
| M14 | 복원 완료를 AI 실행으로 연결 (`_show_policy`) | KILLED 1 | X-03 |
| M15 | 손상 파일 원문을 로그에 기록 | KILLED 24 | N canary·로그 |
| M16 | 설정 I/O를 GUI thread에서 실행 (`_policy_submit`) | KILLED 80 | U(store의 GUI thread 감시) |
| M17 | revision 재검사 제거 | KILLED 15 | R 다른 프로세스 변경 |
| M18 | 저장 실패를 예외로 전파 (controller) | KILLED 21 | U 저장 실패, N |
| M19 (C00 조건) | `run()`이 store None을 넘김 (`user_window`) | KILLED 1 | X-01 |

19/19 KILLED, error 0이다. UI 대상 M10–M14·M16·M19는 최종 UI 시험본, integration 대상 M01–M09·M15·M17·M18은 X-06–X-11 추가 직전 integration 시험본으로 실행했다(그 뒤 변경은 시험 함수 추가뿐이다). 첫 회차에서 M12는 생존했다. 기본 fixture에서 동의 준비가 CONSENT_REQUIRED로 멈춰 암묵 계속이 재접수까지 가지 않았고, S가 “선택 자체가 요청·준비를 만들지 않음”을 관측하지 않았다. S에 동의 준비가 가능한 상태에서도 선택 단독으로는 요청·준비·config가 0임을 확인하는 단계를 넣어 검출했다. M19는 처음에 FileNotFoundError(무효 판정)로 실패해, X-01이 창의 store 경로를 먼저 assertion으로 확인하도록 고쳤다. M13은 S의 REMOTE_UNKNOWN 행 중 계속 대상이 설정되는 2행에서만 검출된다. REMOTE_UNKNOWN 계속 금지의 주 검증은 G-P07 시험이다. 보강 즉석 변이로 저장 경로의 SQLite 호출(N 24행)과 멱등 생략 제거(R 같은 정책쌍·W 51행)도 검출됨을 확인했다.

### 10.7 회귀·coverage·정적 검사

정확한 사본은 `git archive b6da7e0`에 허용 9파일만 덮어쓴 OS TEMP 트리다. 기준 트리와의 차이는 신규 6파일과 `main.py`·`ai_bridge.py` 2개뿐이다(`test_resource_policy_ui.py`는 기준과 동일). PYTHONPATH와 `recoryn.__file__`은 사본 src이고, 자식 프로세스 import origin은 X-04가 확인한다. `QT_QPA_PLATFORM=offscreen`, `-p no:cacheprovider`, 고유 TEMP basetemp, `-W error::ResourceWarning`을 썼다.

| 검사 | 결과 |
| --- | --- |
| CI 동등 전체(`--cov=recoryn --cov-branch --cov-fail-under=85`) | **25,306 passed**, failures·errors·skipped 0, 1,567.0초, 전체 coverage 92.62% |
| `scripts/check_coverage.py coverage.json` | domain·capture·jobs·storage·security·content·all 전부 PASS(all line 93.96%·branch 88.66%) |
| `src/recoryn/app/device_policy.py` coverage | 95.89%. 미실행은 비 Windows `fcntl` 분기, `try_lock`의 예외 정리 분기, 경로 검사 예외 변환 일부, store 없는 창의 사용자 선택 분기 |
| tests/ui 전체(conftest 포함) | 2,949 passed, 121.0초 |
| 신규 3파일 | 650 passed, 19.93초 |
| ruff check·ruff format --check | 통과(205파일) |
| `python -m mypy src/recoryn scripts packaging` | 93 source files, issue 0 |

G-P02/P02b/P03/P05/P06/P07/P11a/P12 회귀는 전체 실행에 포함된다. 기존 `MainWindow(library)` 호출부(tests/integration 등)는 store 없음이므로 사용자 설정을 읽거나 쓰지 않는다. 시험 중 GUI 진입점 `run()`을 부르는 것은 X-01뿐이며 LOCALAPPDATA를 TEMP로 돌린다.

### 10.8 남은 위험·미검증

- 외부 게이트: Narrator 등 화면 읽기 프로그램 실사용, 실제 네트워크 드라이브·로밍 프로필·다른 Windows 사용자, GPU 실장비에서 GPU_ONLY 계속 시 키 변화, 다른 PC로 옮긴 library의 실제 복원, 실제 G-P09 backup/restore 대조(G-P09b 인계).
- 저장 완료는 완전한 v1 파일의 replace 성공까지다. 디렉터리 fsync가 없어 전원 장애 내구성은 보장하지 않는다.
- 잠금은 협력 잠금이다. 잠금을 존중하지 않는 같은 권한 프로그램의 파일 치환은 revision 재검사 범위에서만 감지하며 완전 방어를 주장하지 않는다.
- 손상·미래 파일에서 일반 선택을 하면 worker 판정 전까지 잠시 “저장 중”이 보인 뒤 거부 상태로 돌아온다.
- U 행은 행마다 controller를 새로 묶는 fixture를 쓴다. 생성자 배선은 S·CLOSED·X-01이 따로 고정한다.
