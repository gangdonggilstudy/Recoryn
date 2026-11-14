# BR14 제공업체 독립 보안·QA 검토

검토자: B14. 대상 작성자: B13. 최초 확인일: 2026-11-14. 최초 판정: **OPEN — S1 1건, S2 1건**. 현재 두 건은 후단 재확인 기록의 **RECHECKED**다. 전체 제품 최종 승인은 B10 책임이다.

## 범위와 근거

AGENTS, onboarding, workflow, assignments, product-contracts, quality-system, provider-matrix와 B13 runtime 8파일 및 기존 provider/contract 시험을 읽었다. 쓰기는 이 문서와 [독립 반례](../../tests/integration/test_provider_security_independent.py)에 한정했다. B14 자신이 작성한 Gateway/vault/PrivacyPanel의 승인이 아니다.

실제 SQLite ConsentStore/CostLedger/Gateway에 fake low-level transport를 주입했다. 모델 경계는 fake factory, 입력은 100ms 합성 PCM WAV와 canary 문자열이다. integration 자동 fixture가 DNS/socket 접근을 금지한다. 실제 SDK 모델 로드·weights·장치·키·유료 API·사용자 데이터 송신은 모두 NOT_RUN이다.

최초 발견 snapshot SHA-256(프로그램 ReadAllBytes 대응 `Path.read_bytes()`로 산출):

| 파일 (`src/recoryn/` 기준) | SHA-256 |
| --- | --- |
| providers/contracts.py | 289df70e55e625f551d9384bec7073b4e20b362c702d870f7f51246c31890251 |
| providers/_common.py | 14733236f8e52edea435ae407976248e6d010274980e569ad62137a6ad8e2184 |
| providers/__init__.py | 8f0a73d3ff7946c196db14c6e21cbf5eb25804e30c9ad3c96418b810bdadd628 |
| transcription/adapters.py | e70f9cee18a7012bcb8eb1fdaca87df6cfaad029bd1d0c9883094efb07d68f1f |
| transcription/__init__.py | 6b7f5050fafd2e961fa412efbffb58f25d549586609139e5a5707562aaf902c1 |
| summarization/adapters.py | 25485c7614cc42dbe6fc912bafbfb7ef1f9504f6d30ac7dd716d59a5b2561256 |
| summarization/planning.py | fc0d54eb0aea149def5be072a649d48ad617984a2e9c2832615d4d99bf4af355 |
| summarization/__init__.py | 95788b1cb2d4ad6f86d9bb00612f8e3e7ca68296926172d4d709eac29bea3d9d |

## 발견 사항

### BR14-01 · S1 · OPEN — 재개 checkpoint의 의미적 근거 분류를 신뢰함

- 위치: `summarization/adapters.py::_Summarizer.summarize`의 checkpoint.completed 검증. digest·core coverage·참조 집합은 검사하지만 claim의 status/basis를 원본 provenance 및 무참조 규칙과 대조하지 않는다.
- 반례: 정상 1-core 결과의 checkpoint에서 claim만 `SummaryClaim('claim', ('s1',), 'uncertain', 'transcript')`로 교체한다. source provenance가 `user_assertion` 또는 `unresolved`여도 새 호출 없이 `complete=True`이고 basis가 transcript다. 무참조 claim을 같은 분류로 교체해도 unsupported/model_inference가 사라진다. 원문·설정·plan digest·coverage는 바꾸지 않았다.
- 영향: 손상되거나 잘못 복원한 checkpoint를 재개하는 공개 경계에서 사용자 삽입·미확정 발화·모델 추론의 증거 분류가 승격된다. 원문 참조 ID의 존재 검사는 의미 분류의 검사가 아니다. 제품의 근거 구분 불변식이므로 G1 종결을 막는다.
- 독립 시험: `test_resume_revalidates_claim_basis_from_source_provenance` 2경우, `test_resume_rejects_unsupported_claim_masquerading_as_transcript` 1경우: **3 FAIL**.
- 해결 조건: 재개 전에 신규 parse와 같은 provenance/status/basis 규칙으로 재검증·정규화하거나 CHECKPOINT_MISMATCH로 거부한다. 부정 cache claim을 부분 후보·새 checkpoint에도 그대로 재노출하지 않아야 한다. 정상 재개·원문 core 재전송 없음은 유지한다. claim 내용 전체의 진위를 hash만으로 보증한다는 요구는 아니다.

### BR14-02 · S2 · OPEN — backend 예외 문자열화 실패가 안전 오류 경계를 벗어남

- 위치: `transcription/adapters.py::FasterWhisperProvider.transcribe`의 `except Exception`, `str(exc).lower()`로 OOM을 분류하는 부분.
- 반례: fake model.transcribe가 사용자 정의 예외를 던지고 그 예외의 `__str__`가 RuntimeError(canary)를 던지게 한다. transcribe는 STTResult(PROVIDER_FAILED)를 반환하지 않고 원시 RuntimeError를 밖으로 전파한다. 실제 모델은 로드하지 않았다.
- 영향: 비정상 optional backend 예외를 안전한 코드로 변환한다는 공개 계약 위반이다. 상위 앱의 별도 generic catch가 있을 수 있으므로 전체 UI 비밀 유출이나 실모델 재현으로 확대하지 않는다.
- 독립 시험: `test_local_backend_exception_with_broken_str_still_returns_safe_result`: **1 FAIL**.
- 해결 조건: 예외 문자열화 자체도 보호하거나 안전한 타입 기반 분류로 바꿔 PROVIDER_FAILED/RESOURCE_EXHAUSTED를 반환한다. lock 해제·기존 partial 결과 보존·OOM 분류 회귀를 확인한다.

## 통과한 독립 경계와 한계

- 정확 provider/endpoint/data type 및 삭제-session 불일치: adapter가 실제 Gateway를 통해 transport 생성 전에 차단한다. 합성 원본 파일은 byte 동일하다.
- ledger를 주입한 cloud dispatch에서 예약이 없으면 BUDGET_REQUIRED다. 부분 write 실패는 원시 canary 없이 REMOTE_OUTCOME_UNKNOWN/outcome_known=False이고, UNKNOWN 70/100은 ledger 재개 후 잔여 30이다. 추가 재시도 없이 transport 1회였다.
- Ollama는 loopback 주소만으로 통과하지 않는다. proof 없음/cloud 허용/만료/model 불일치/endpoint 불일치 5경우가 로컬 실행 미검증으로 차단된다. proof가 실제 daemon egress를 입증하는지는 B10 모델 관리자·실행 환경의 별도 검토다.
- 원문은 system instructions 대신 JSON 데이터에 들어가며 supported 모델 라벨은 uncertain으로 정규화된다. 이 확인이 prompt injection의 의미적 성공률 평가나 claim의 사실 검증은 아니다.
- 긴 입력은 transcript core 완료 뒤 context 동의가 없으면 최종 합성만 차단한다. coverage는 보존되고 complete=False다. context 허용 후 checkpoint 재개는 합성 1회만 보내며 원문 core canary를 합성 body에 포함하지 않는다. template 변경은 CHECKPOINT_MISMATCH로 전송 전에 차단한다.
- 로컬 tokenizer 파일 누락은 optional model import 전에 MODEL_MISSING이다. fake factory에는 local_files_only=True가 전달된다. 정적 검색상 직접 socket/HTTP SDK 호출이나 모델 자동 다운로드 경로를 발견하지 못했다. 설치된 전체 의존성의 모든 숨은 동작을 입증한 것은 아니다.
- 원격 실청구/모델 품질·음성 품질/실제 provider 버전 호환성/강제 native inference 취소는 NOT_RUN이다. DTO timeout과 Gateway blocking timeout 일치는 B10 통합 계약이다. 이 리뷰는 B14 자신의 전송 구현을 재승인하지 않는다.

## 실행 기록

Windows / Python 3.13.1 / `.venv`, 고유 TEMP basetemp, `-p no:cacheprovider`. 최초 18개 독립 반례 결과는 **14 PASS / 4 FAIL**, 실패를 skip/xfail 처리하지 않았다. B13 작성자에게 두 발견을 전달했고 수정 후 동일 검토자가 재확인한다.

```powershell
$br14Run = Join-Path $env:TEMP ('recoryn-br14-' + [guid]::NewGuid().ToString('N'))
.venv/Scripts/python.exe -m pytest tests/integration/test_provider_security_independent.py --basetemp $br14Run -p no:cacheprovider -q
.venv/Scripts/python.exe -m ruff check tests/integration/test_provider_security_independent.py
.venv/Scripts/python.exe -m ruff format --check tests/integration/test_provider_security_independent.py
$env:MYPYPATH = 'src'
.venv/Scripts/python.exe -m mypy tests/integration/test_provider_security_independent.py
```

Ruff lint/format 및 mypy 검사 PASS. 단독 mypy의 src 탐색 실패는 MYPYPATH=src로 해결했으며 제품 결함으로 세지 않았다. 공용 설정·제품 코드·Git 인덱스는 수정하지 않았다. **최초 G1 판정은 OPEN S1 때문에 미통과였다. G2 전체 통합과 G3/G4 실제 실행은 이 기록으로 통과 처리하지 않는다.**

추가 조합 실행: `pytest tests/unit/test_providers.py tests/contract tests/integration/test_provider_security_independent.py --basetemp <unique TEMP> -p no:cacheprovider -q --tb=short` → **139 PASS / 같은 4 FAIL**. 기존 125개는 모두 통과하고 독립 반례의 실패는 유지됐다.

## 수정 후 동일 검토자 독립 재확인

2026-11-14, 수정자 B13 / 재확인자 B14. 위 최초 반례·snapshot·실패 결과는 보존한다. 제품 코드는 작성자가 수정했으며 검토자는 지정 독립 시험과 이 문서만 변경했다.

| ID | 판정 | 실제 새 문구/코드와 대조 및 실행 근거 |
| --- | --- | --- |
| BR14-01 | **RECHECKED** | checkpoint 채택 전에 fresh parse_claims에 원본 provenance·허용 refs·core 집합을 공급하고, 정규화 DTO와 캐시 DTO가 다르면 CHECKPOINT_MISMATCH로 거부한다. 원래 3반례가 PASS다. 잘못된 claim/coverage/completed가 반환 결과·새 checkpoint에 남지 않고 추가 Gateway 호출도 0건임을 강화해 확인했다. user_assertion/unresolved 정상 checkpoint는 분류와 내용 그대로 재개되며 추가 호출 0건이다. 긴 문서 최종 합성만 재개하는 정상 경로도 PASS다. |
| BR14-02 | **RECHECKED** | OOM 분류 안의 문자열화 자체를 try/except로 보호해 실패 시 PROVIDER_FAILED로 반환한다. 원래 broken __str__ 반례가 PASS다. 추가 독립 generator 반례에서 50ms partial 결과를 유지하고 연속 2회 호출이 같은 결과를 반환해 lock 해제도 확인했다. 작성자 OOM 대조 회귀를 포함한 조합 실행이 PASS다. |

재확인 SHA-256(초기 표에서 바뀐 runtime 2파일과 최종 독립 시험):

| 파일 (`src/recoryn/` 기준, 시험은 저장소 기준) | SHA-256 |
| --- | --- |
| transcription/adapters.py | b25c8abcac995f9bc7cb042ffecf59e6d86755085d61789d206b975abda24304 |
| summarization/adapters.py | c5b1663d13cb5df7f43ca2da1b492b878c023c405180a4090bcd983e3ef9fcb4 |
| tests/integration/test_provider_security_independent.py | 41cae4ab4fee96b6a2033fb78ebb6a0627bdaf26e43e9b7259e8cd9da42d167e |

현재 최종 실행: 독립 **19 PASS**, 작성자 unit/contract 포함 **149 PASS**, `-W error::ResourceWarning` 적용, skip/xfail 0. 명령은 위 pytest에 `tests/unit/test_providers.py tests/contract`와 `-W error::ResourceWarning --tb=short`를 추가했으며 고유 TEMP basetemp를 사용했다. Ruff lint/format 및 MYPYPATH=src mypy PASS. 위 재확인 표의 64자리 digest는 실제 파일 바이트와 프로그램 비교했다.

**BR14 범위에 남은 OPEN S0/S1/S2는 0건**이며 이 검토 범위의 반례와 수정 재확인은 완료했다. B14 자신의 보안 구현·B10의 전체 G1/G2 최종 통합을 대신 승인하지 않는다. 실제 모델·SDK 추론·유료 endpoint·가격·키·native 장비·외부 daemon의 egress 격리 및 G3/G4는 여전히 NOT_RUN이다.
