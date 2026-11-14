# BR23 전송·동의·비용 독립 검토

검토자 B13(ML·보안), 작성자 B14. B13 provider의 자기 승인 문서가 아니다. B14의 security/*, diagnostics/*, ui/privacy.py와 관련 unit/integration/UI 시험을 읽었다. 쓰기는 이 문서와 `tests/integration/test_egress_independent.py`에 한정했다. 실제 vault·DNS·소켓·TLS 서버·유료 API·사용자 음성은 실행하지 않았다. 실제 TLS 인증서 검증과 외부 daemon 후속 egress는 NOT_RUN이다.

## 계약과 초기 snapshot

AGENTS/onboarding/workflow/assignments, product-contracts의 기본 거부·정확한 provider/endpoint/data scope·세대·SendPermit·정수 비용·UNKNOWN 우선·비밀 제외를 기준으로 검토했다. B14 자체 105개 시험과 coverage는 독립 승인으로 인용하지 않는다.

| 초기 읽기 대상 (`src/recoryn/`) | SHA256 |
| --- | --- |
| security/consent.py | `8EE90D10E8CAC367B5A98ED5CDDE23EC8BD1AE6BF590C519792F56DFA08A0858` |
| security/gateway.py | `A5008241802099DC12E82C06F00E8D865832E542B3276D0EDF4A34AB570DC888` |
| security/ledger.py | `AAE43ACF576C006DB8680D70D2CBC6FF16BDDBB61EC3741462E73627AE93F4FA` |
| security/transport.py | `CEBAC3B2FDEFFAD1292BFD200ECBF6D065380AB24D0917795BA17FC8D88DA369` |
| security/vault.py | `ED4AF213C6590FA6962C080F2FCABE8BBEAA10580C06CEA0ED0186EF43AE233A` |
| security/_core.py | `2C71090DACE41D7B78C8C853779408EC6A0D8B0EB69AD22EBDE4FBEDE6BFD2E1` |
| security/_secrets.py | `D038B45A3DAE158DFC08BC59FCE7D26B3B90F2B7FD34C7318653A0F7A0EB0517` |
| diagnostics/__init__.py | `D4391B3A11FA2B93AB9E14062290B90FE47DA06320B0F75F04306A4118B9B71B` |
| ui/privacy.py | `ECF8E0BD67DE4E768BF793ECA45C3F7E58BC14FBAF3712920C2FF3A037CBD60B` |

## 발견 사항

### BR23-01 · S2 · PrivacyPanel.provider_config/config_key, 요약 설정 UI

반례: 요약 제공업체·모델·endpoint·예산·키·전사 동의를 설정해도 반환 ProviderConfig의 context_window_tokens는 항상 None이다. 사용자가 알려진 상한을 입력할 UI도 없다. B13 계획기는 의도적으로 CONTEXT_LIMIT_UNKNOWN으로 차단하므로 정상 UI로 요약에 도달할 수 없다. 초기 독립 `test_privacy_summary_supplies_explicit_bounded_context`는 None을 확인하고 FAIL했다.

해결 조건: 기본 미확인 상태를 보존하면서 사용자가 확인한 context/output 상한을 명시 입력하고 DTO·config key·실행에 전달한다. 임의의 서버 모델 상한을 기본 유효값으로 추측하지 않는다. 명시 8192 fixture 상한으로 실제 Gateway+fake transport 요약이 완료되고, 16384로 바꿀 때 작업 identity 변경·기존 동의 철회를 확인한다. B14 수정 API 통보에 따라 독립 반례에 해당 명시 입력 흐름을 추가했다.

### BR23-02 · S1 · PrivacyPanel.execution_context, Gateway·SendPermit 실행 세대

반례: model-A/key-A의 DTO·ExecutionContext·session gateway를 고정 → 모델을 B로 변경하거나 A 키를 삭제하고 B 키를 저장 → 선택 범위를 다시 허용 → 이전 DTO/context로 전사한다. 초기 두 독립 case는 성공하고 fake transport가 생성됐다. 이전 DTO는 model-A, 고정 헤더는 Bearer key-A였다. reservation_factory는 현재 allowed만 보고, Gateway는 dispatch 시점의 새 grant로 permit을 발급하여 철회된 계획을 되살린다. 재허용하지 않는 철회 대조군은 차단된다.

시험: `test_new_grant_cannot_revive_old_model_or_key_context[model/key]`. 초기 `--runxfail` 실행에서 두 FAIL/실제 complete=True를 확인했다. 새 동의는 새 실행 계획의 승인이지 이전 계획의 재승인이 아니다. provider/model/endpoint/key/비용 설정을 worker가 GUI에서 다시 읽어 해결해서도 안 된다.

해결 조건: 실행 시 고정한 grant/execution generation을 reservation 및 dispatch 직전 같은 조정 경계에서 비교하고, 중간 revoke→regrant에도 이전 작업을 차단한다. 예약 검사와 permit 신규 발급 사이의 변경도 검사한다. 새 작업만 새 권한으로 실행한다. B10/B14 추가 계약에 따라 context/output·요청 cap·전체 limit 변경도 이전 계획을 무효화하며, frozen 값은 새 GUI 값을 자동 채택하지 않는다. 단순히 헤더 dict를 변경하거나 오래된 키를 메모리에서 지우는 것만으로 종결하지 않는다.

## 독립 대조군과 검증 범위

| 경계 | 독립 oracle |
| --- | --- |
| 기본 차단·정확한 scope | 실제 기본 transport의 미동의 호출은 integration DNS/socket guard에 도달하지 않는다. provider/path/port/data/session 불일치는 transport 생성 0건이다. |
| 철회가 먼저 commit | 첫 _write 앞 event gate에서 scope/session 철회 → 연결은 닫히며 body write 0건, outcome_known=True다. |
| handoff가 먼저 | 첫 3바이트 write를 마친 뒤 scope/session 철회 commit → 다음 chunk 0건, 전달 bytes는 abc뿐, outcome_known=False·UNKNOWN=80이다. 긴 sleep 대신 event로 순서를 고정했다. |
| DNS/로컬 위치 | 전역·loopback IP가 섞인 응답을 fake resolver로 주면 socket 생성 전 거부한다. 실제 DNS rebinding·외부 daemon 트래픽을 관측한 것은 아니다. |
| TLS/proxy/redirect/header | fake socket/HTTP/TLS로 정확한 hostname·POST target·default-context 호출·auto reconnect 비활성·환경 proxy 무시·307 미추적을 관측한다. Host/Content-Length/CRLF/중복 Authorization/Proxy-Authorization 주입은 생성 전 거부한다. 실제 인증서 chain/hostname 검증은 NOT_RUN이다. |
| 비용·재시작·rollback | 동일 요청 중복 예약 1회, 두 60 예약/100 limit에 하나만 성공, UNKNOWN 80 재시작 유지·release 거부, 40 확정 중복 정산 후 available=60, 역행 witness로 dispatch 전 차단한다. 실제 가격/청구 상한을 보장하지 않는다. |
| GUI→worker | fake vault만 사용하고 생성 시 read 0건이다. 고정 헤더·명시 예약값 및 변경/철회 후 이전 factory 차단을 검사한다. 실제 Credential Manager는 호출하지 않는다. |
| 지원 번들 | generated diagnostics/environment 두 파일만 포함하고 원본 파일·전사·키·경로를 넣지 않는다. 등록된 synthetic canary는 출력에 없다. 모든 가능한 비밀 탐지의 증명은 아니다. |

최초 실행은 **7 PASS / 3 FAIL**(`--runxfail`)이었다. 후속 대조군 추가 시 **23 PASS / 3 strict XFAIL**을 확인했다. XFAIL은 미해결 기록이며 승인이나 pass가 아니다. 예산 설정 변경의 추가 계약 반례와 수정 후 재확인은 아래에 갱신한다. 시험 파일은 Ruff lint/format을 통과했다.

~~~powershell
$br23Temp = Join-Path ([IO.Path]::GetTempPath()) ('recoryn-br23-' + [guid]::NewGuid().ToString('N'))
.venv/Scripts/python.exe -m pytest tests/integration/test_egress_independent.py -p no:cacheprovider --basetemp $br23Temp -q -rx -W error::ResourceWarning
# OPEN 반례를 일반 실패로 확인하려면 --runxfail 추가
~~~

## 판정 및 남은 제한

현재 **BR23-01 S2, BR23-02 S1 OPEN**이다. 소스 수정은 B14/B10에 보고했고 검토자는 수정하지 않았다. 같은 검토자가 변경 코드·원 반례·새 digest를 대조한 후에만 종결한다. 실제 vault/TLS/제공업체/가격·native 플랫폼·긴 DNS 지연·전원 장애·G3/G4와 전체 제품 통합은 별도 검증이며 이 리뷰로 통과시키지 않는다.

## 수정 후 동일 검토자 재확인

2026-11-14, 수정자 B14 / 재확인자 B13. 초기 hash·반례·실패 기록은 위에 보존했다. 수정 후 code/원 반례를 대조하고 네 XFAIL case를 일반 회귀로 전환했다. 수정 대상 제품 파일은 검토자가 변경하지 않았다.

| ID | 판정 | 새 계약·독립 재확인 근거 |
| --- | --- | --- |
| BR23-01 | RECHECKED | context_window 기본 0(미확인)을 보존하고 명시 8192 입력이 ProviderConfig·config key에 전달된다. 실제 Gateway+ledger+fake Responses 응답으로 요약 완료·원 segment 참조를 확인했다. 16384 변경 시 key가 달라지고 동의가 철회된다. 기본 미확인 case는 CONTEXT_LIMIT_UNKNOWN, transport 0건으로 유지된다. max_output도 DTO/key와 설정 변경 철회에 포함된 코드를 대조했다. 모델의 실제 지원 상한을 검증한 것은 아니다. |
| BR23-02 | RECHECKED | ConsentBinding은 frozen execution/grant ID·epoch·정확한 scope를 담는다. factory는 고정 binding 검증과 예약을 같은 policy coordinator에서 수행한다. Gateway expected_grants는 for_session에도 보존되고, permit 발급의 같은 lock에서 expected epoch를 비교한다. 모델 변경·키 삭제/교체 후 재grant해도 이전 DTO/context는 전송 0건이며, 새 DTO/context만 새 모델·키로 성공한다. 별도 reserve 성공 직후 revoke→regrant를 삽입한 case도 permit 전 차단된다. 이전 gateway는 나중에 허용한 context scope로 확대되지 않는다. 비용 factory 없는 로컬 Ollama도 고정 gateway의 옛 모델 grant로는 재활성화되지 않는다. cap 변경 후 기존 frozen 헤더는 바뀌지 않지만 기존 factory는 차단된다. |

| 재확인 대상 | SHA256 |
| --- | --- |
| security/consent.py | `E6EDA682F676EF90D0E0FAE5DBCBEBF6871B346A59084B3277150A656D65F4A5` |
| security/gateway.py | `A3401E7D6C73A7AF28844A756ECFB6461BA4D2D2D3226EC78AFBA8574FE01DBB` |
| ui/privacy.py | `D0D75184F459337AA1FFA1C1184E4A195717C24E525CAD5FFE2DF8012A7AA443` |
| tests/integration/test_egress_independent.py | `CD4236BE2389E6119299C25F6E03F8153987EB29017514A5B3726094E264810C` |

위 수정 제품 3파일 digest는 강화 반례 실행 전후 같았다. 독립 **30 PASS**, B14 security/diagnostics/gateway/privacy 연관 시험 포함 **142 PASS**, skip/xfail 0, `-W error::ResourceWarning`, Ruff lint/format PASS다. 원 반례 외에 미확인 상한 유지·신규 계획 정상 실행·예약 후 permit 경쟁·local Ollama·뒤늦은 scope 확장을 추가 검증했다. B10 현 ai_bridge도 config/context/gateway를 GUI 호출 구간에서 고정한 뒤 worker에 전달함을 읽기 전용으로 확인했다.

고정 실행 계획의 호출자는 expected_grants를 보존하는 gateway를 전달해야 한다. 일반 Gateway의 expected_grants=None이 모든 과거 실행 계획을 자동 고정한다고 해석하지 않는다. 이 구분과 새 공개 ConsentBinding API의 공용 문서 반영은 B10에 보고한다. **BR23 2/2 RECHECKED, 해당 검토에 남은 OPEN S0/S1/S2 0건**이다. 이 판정은 B14 본인의 다른 독립 리뷰나 전체 제품 G2/G3/G4 및 실제 vault·TLS 인증·가격 확인의 승인이 아니다.

## R13 재부팅 후 현 snapshot 재확인 — 2026-11-14

R13은 온보딩과 현 staged/unstaged/untracked 변경을 읽고 위 후단 판정을 실제 파일과 다시 대조했다. consent.py·gateway.py·ui/privacy.py·독립 시험의 SHA256 4개는 위 재확인 표와 **바이트 단위로 모두 동일**했다. BR11 alignment.py와 BR30 manager.py/inference.py도 각 리뷰 후단 digest와 일치함을 확인했지만 해당 리뷰의 새 독립 승인으로 계산하지 않는다.

고유 TEMP basetemp, `-p no:cacheprovider -W error::ResourceWarning`로 `test_egress_independent.py`를 실행해 **30 PASS**를 확인했다. 네 digest는 이 실행 전과 후속 묶음 진입 전 확인에서 동일했다. 이어 security/diagnostics unit, gateway integration, privacy UI와 함께 재실행해 **BR23 관련 142 PASS, skip/xfail 0**이었다. 이때 B22 자체 시험 55개도 같은 명령에 포함해 전체 **197 PASS / 8.19s**였으며 B22는 자기 작성 검증이므로 BR23 독립 승인과 분리한다. provider/model/key 재허용이 이전 계획을 되살리지 않는 원 반례와 context/output 미확인 차단을 회귀로 확인했다.

BR23 두 지적의 RECHECKED를 유지한다. 실제 vault·TLS·서비스·후속 daemon 전송·음성·모델 실행은 수행하지 않았으며 전체 제품 완료·공식 릴리스 승인이 아니다. BR13은 R12/B21 작성 완료 뒤 root가 재배정할 때 최신 코드를 재검토한다. 과거 BR13 6/6 RECHECKED와 B21 체크포인트는 보존하며 작성 중 코드의 최종 승인으로 확대하지 않는다.

제출 직전에는 R00/R14의 새 runtime lifetime guard 연동으로 gateway.py와 ui/privacy.py가 변경된 것을 확인했다. 관측 hash는 각각 `68073632EB3894D4152DD61BC39D95A19364CA858AF20EDEFFCED91432894DB4`, `285CD7561DA2AE401A2F1C3857DCEDF0A03E0BFD6F0185717B4B7AE6F0C4C1DC`다. 따라서 197개 실행도 최종 동결 snapshot의 승인으로 쓰지 않는다. 위 기존 두 지적의 초기 재부팅 snapshot 재확인과 현재 작성 중 guard 연동의 독립 재검토를 구분한다. 새로운 연동은 작성 완료·root 재배정 후 다시 검토해야 한다.

## BR23 새 dispatch/고정 proof/DTO guard 독립 검토

R00이 R13에 별도 재배정했고 DTO의 1차 안정화를 알린 뒤 검토했다. 작성자 R14의 gateway/privacy와 R00의 LocalModelAttestation/require_endpoint를 읽기 전용 대조했다. R13이 작성한 B22 수정의 자기 승인이 아니다. ManagedOllama/OS Job helper 전체의 최종 검토는 R14가 별도 수행하므로 그 범위를 이 판정에 포함하지 않는다.

독립 시험 13건을 기존 파일에 추가했다. 가짜 transport의 실제 관측 event로 연결 전·첫 write 전·후속 write 전·결과 반환 경계를 선택하며 guard 호출 횟수를 구현대로 복제하지 않는다. 각 경계의 enter/exit 예외 8경우에 body 전달 목록·connection close·outcome_known·reserved/UNKNOWN exposure를 함께 확인했다. 첫 body를 쓰기 전 실패는 미전송을 유지하며, 첫 write의 guard exit가 실패해도 실제 일부 handoff가 있으면 UNKNOWN 80을 유지한다. guard가 consumer 예외를 suppress하려는 대조군에서도 부분 write 실패를 성공으로 삼지 않는다. private callback 예외 canary는 safe code로 가려진다.

PrivacyPanel에서 고정한 proof의 owner를 fake transport.open 중 무효화하고 새 proof를 panel에 주입했다. grant는 그대로 두었으므로 consent가 아닌 **이전 owner guard**가 첫 body를 0건으로 차단하는 것을 확인했다. base dispatch guard의 보존·for_session·정확 scope 거부와 이전 regrant 반례는 기존/작성자 관련 회귀로 함께 대조했다. worker 실행에서 GUI 상태를 다시 읽어 신규 proof를 채택하지 않는다.

DTO는 owner guard를 얻은 뒤 TTL을 검사해, lock 획득 중 만료된 proof가 consumer에 도달하지 않는다. 정상 callback 안의 consumer 예외는 동일 예외 객체로 전파하고 owner cleanup을 실행한다. callback은 repr/compare에서 제외되며 정적 proof의 기존 API와 TTL 검사는 유지된다. 운영 helper의 `_execution_guard`도 validation 예외 처리 영역 뒤에서 lock을 유지한 채 yield하여 consumer 예외를 검증 오류로 다시 쓰지 않는 구조임을 읽기 전용 확인했다. 운영 helper의 OS 소유·listener/file identity 반례 종결은 R14 책임이다.

최종 실행: **BR23 독립 43 PASS**, privacy UI/gateway 작성자 관련 시험 포함 **92 PASS / 3.59s**, skip/xfail 0, ResourceWarning 오류 처리. 아래 네 제품 digest는 실행 전후 프로그램 비교로 동일했다. 독립 시험 Ruff check/format PASS. 초기 hash 수집 명령의 PowerShell parameter binding 오류는 수정했으며, 최종 수집은 `Get-FileHash -Path $r13Paths`로 실행 전후 비교했다.

| 이번 독립 검토 snapshot | SHA256 |
| --- | --- |
| security/gateway.py | B98A134F9DEAEF3730EC6D4593BE4AD6C2F82F27BE40DB524443935DB9536983 |
| ui/privacy.py | 285CD7561DA2AE401A2F1C3857DCEDF0A03E0BFD6F0185717B4B7AE6F0C4C1DC |
| providers/contracts.py | 07325CF5F0D9273DED8B49B23664FAD1E83AD992476688ED1E641A306A28357B |
| providers/_common.py | 72C3FD838A3369C0C45FD848FFEADE5C617DC9820E4EC3A573D1D98CAC4FFB23 |
| tests/integration/test_egress_independent.py | 1EFEAB64296EB6CA7B0C3624467945C1C553B5D166EF93A34A6806EC3E696990 |

```powershell
$br23GuardRun = Join-Path $env:TEMP ('recoryn-br23-guard-' + [guid]::NewGuid().ToString('N'))
.venv/Scripts/python.exe -m pytest tests/integration/test_egress_independent.py tests/ui/test_privacy_ui.py tests/integration/test_gateway.py -q -p no:cacheprovider --basetemp $br23GuardRun -W error::ResourceWarning --tb=short
```

현재 판정: **새 Gateway/privacy/DTO guard 경계 REVIEW_READY, 추가 OPEN S0/S1/S2 발견 0건**, 기존 BR23-01/02 RECHECKED 유지. root/독립 helper 검토의 종결과 최종 codefreeze 후 통합 판정은 별도다. 실제 daemon·TLS·native 네트워크 전체·실계정/vault·모델·음성·배포는 미실행이며 guard 통과를 실제 처리 위치의 외부 독립 인증으로 확대하지 않는다.
