# GS04-R1 제공업체 사실 표시 독립 검토

검토자 w5:p8 Codex. 작성자 X00(w5:p9)과 별도 세션에서 검토한다. GS11a 승인 17파일은 동결하고 수정하지 않았다. 검토 대상·입력 원본·LF 해시는 `build/gs04r1-evidence-0e07f4e54e/input.json` 및 `input/`에 보존했다. LF 해시는 CR 바이트를 제거한 뒤 SHA-256으로 계산했다.

## H-P02 문서 교차 확인 — 문서 수락 가능, OPEN 0

- 대상은 `55a89e27c6dcf9c71568bc5bc47c404d4677d47e`다. 기준 `7420a4e247274f3a6ed3c67e842c3406a566df0e` 대비 문서 4파일만 변경(207 추가/9 삭제)이며 제품·시험 변경 0, `git diff --check` 성공, 공유 index 변경 0을 직접 확인했다. 각 tree blob은 검토 시작 시 보존한 4문서와 LF 기준 모두 일치했다. 증거는 `h-p02-tree.json`이다.
- 권한: `docs/collaboration/assignments.md:7`·`:9`·`:11`·`:13`과 `docs/collaboration/orchestrator-handoff-h02.md:7`·`:8`·`:10`·`:16`·`:21`을 대조했다. TRANSFER_EFFECTIVE → ORCHESTRATOR_ACCEPTED 뒤 X00 단일 Git·배정·공용 계약 작성, Claude 작성·검토 중지, 작업자는 명시 배정 파일만 수정하는 절차가 일치한다. 새 X00 인수·배정 문단에 기존 C00 권한을 병행시키는 문구는 없다.
- manifest: assignments `:11`의 4파일과 실제 diff 목록이 같다. H02 `:9`·`:52` 이후의 기존 인계 목록은 인수 시 보존할 변경을 설명하고, 새 assignments `:11`은 H-P02에서 g09/g10/g14·GS04·GS11을 제외함을 명시한다. 승인 계약·제품을 인계 문서 커밋에 섞는 배정으로 해석하지 않는다.
- 선행 CI: assignments `:9`와 H02 `:9`·`:32`는 G-P17c CI 통과 전 후속 push 금지를 유지한다. GS-P06의 취소 이력을 성공으로 바꾸지 않는다. 원격 main·CI 조회 결과는 X00/C00 보고를 문서에서 대조한 것이며, 이 검토자가 원격을 재조회하거나 CI를 재실행한 결과가 아니다. 실제 push 때의 CI 통과 확인은 X00에게 남는 게이트다.
- 독립성·기존 승인: assignments `:13`·`:66`·`:69`는 GS04 작성자 X00/검토자 p8, GS11 승인 17파일 동결, 21파일·360초 미승인을 구분한다. 이전 428건·332.52초를 최신 440건 결과로 소급하지 않는 문구도 있다. 리뷰 쓰기는 이 파일 하나다. H02 원문 LF `76a0e5e8102fbc6992c8ab1b7d710ab70f766f7a7679f730eb04881b3c8f3a6b` 보존을 직접 확인했다.
- 4문서의 Markdown 상대 파일 링크 26개는 모두 실재한다(`h-p02-links.json`). `s3-bundle-plan.md`는 이 검토자의 과거 분석이므로 그 분석 자체의 독립 최종 승인은 하지 않는다. X00 인수·배정 추가분과 전환 절차의 교차 확인에 한정한다. 새 배정과 기존 승인 범위 사이의 충돌은 발견하지 않았다.

H-P02는 위 범위에서 **문서 수락 가능 / OPEN 0**이다. 이는 GS04 제품 수락 또는 원격 CI 통과 선언이 아니다. 최종 통합·commit/push와 선행 CI 확인은 X00이 수행한다.

## GS04 대상·격리와 근거 구분

기준 HEAD는 `7420a4e247274f3a6ed3c67e842c3406a566df0e`, 대상은 배정된 11파일이다. Git archive 기준의 410개 파일에 지정 11파일만 얹었다. 실제 사본은 `runtime.json`의 root이며, baseline/overlay 원본 바이트 대조 불일치 0, GS11 신규 모듈 혼입 0이다(`archive-audit.json`). cwd·rootdir·PYTHONPATH는 이 사본을 가리키며 부모와 실제 spawn 자식의 facts/privacy import가 모두 사본 src임을 `origin.log`로 확인했다. 실행 Python은 기존 `.venv`의 3.13.1이다.

처음 저장소 밖 증거 폴더에 둔 독립 시험을 pytest에 직접 넘긴 실행은 설정 탐색이 작업 트리의 pyproject로 향했다. 해당 첫 반례·변이 결과는 `invalid-origin/`에 보존하고 수락 근거에서 제외했다. 이후 독립 시험도 별도 archive 사본 안에 넣고 `-c <사본>/pyproject.toml`을 명시했으며, 각 변이에서 facts/privacy 파일의 사본 src 소속을 단언했다. 아래 독립 시험·변이 수는 이 재실행 결과다. 제품 전체 회귀는 처음부터 사본 내부 시험과 설정으로 실행했다.

이 문서에서 직접 실행은 `build/gs04r1-evidence-0e07f4e54e/`의 log/XML/JSON에 근거한다. 작성자·기존 리드의 28,839건·변이 58개 수치는 직접 재현한 개수에 합산하지 않는다. 생산 metadata route·네트워크 probe는 이번 단위에 없으며 실제 서비스 인증 결과로 판정하지 않는다.

## 요구별 독립 확인

| 관점 | 기준 파일:줄·시험·관측 |
| --- | --- |
| 선언·실서비스 상태·G16 분리 | `src/recoryn/providers/facts.py:21`, `:34`, `:50`, `:55`의 표·enum과 실제 adapter capabilities를 읽었다. 독립 `test_literal_declarations` 10쌍은 손 literal로 지원·입력 형식·timestamp를 확인하고 DECLARED/NOT_RUN을 단언한다. 자원/정책 문자열을 제공업체 enum으로 받지 않는 기존 D90도 통과했다. |
| 기본 주소·Gemini·사용자 서버 | facts `:71`은 실제 adapter 생성자의 endpoint를 읽는다. 독립 기본 주소 6행·UI 안내 10행·Gemini 모델 변경/모델 빈값/빈 endpoint 전이를 확인했다. privacy `:431`·`:433`의 Ollama/일반 문구 분리 때문에 non-Ollama custom IPv4/IPv6/HTTPS에는 일반 신뢰 안내만 나오며 cloud 문구는 없다. 기본 주소 또는 빈 endpoint에서는 불필요한 일반 안내가 숨겨진다. |
| 관측·완전성·수명 | facts `:179`·`:201`·`:238`·`:249`·`:264`를 대조했다. 독립 완전성 1/yes/False/None/list/dict 6행은 UNKNOWN이며, 정확한 TTL 300초 경계와 늦은 identity를 거부했다. metadata 목록 성공은 모델 등재 사실 두 bool만 보존하고 기능 지원이나 실제 인증으로 승격하지 않는다. |
| 실제 timer·실제 사용자 동작 | privacy `:289`·`:374`·`:621`·`:1058`과 독립 `test_real_timer_and_unlisted_literal`, `test_real_ui_events_invalidate` 8행. 실제 활성 Qt timer를 기다려 만료 라벨을 확인했다. model/endpoint/context·세션 전환·grant/revoke/save/delete는 각각 새 관측 뒤 실제 control/버튼으로 UNKNOWN 전환을 확인했다. fake backend만 쓰고 실제 vault는 사용하지 않았다. 선언 전체 literal과 미등재 literal도 단언했다. |
| 무전송·정보 축소 | facts `:16` 생산 registry는 불변 빈 mapping이다. `clean.log`의 새 interpreter에서 10쌍 describe/default 조회 시 socket/DNS·vault·native AI import 시도 0, 전부 NOT_RUN이다. parser와 UI P20은 raw 응답·오류·redirect·다른 모델명·인증/원문 canary가 DTO/repr/UI/a11y/log/임시 파일에 남지 않음을 확인한다. 이 검사들이 실제 서비스/TLS/계정 검증을 대신하지는 않는다. |
| M9·문서 보존 | HEAD 대비 `src/recoryn/ui/models.py:572` 제품 diff는 `self.preview.clear()` 한 줄뿐이다. M033~036의 기존 유효/승인 계획 뒤 잘못된 manifest 선택 시 preview 없음·plan None·승인 해제·installer 0을 확인했다. r2 SHA `a3a9dee4…d70a6`은 현재 LF 원문의 처음 58,128바이트, FIX1 이전 `fd06f8e4…347a8`은 처음 74,583바이트와 정확히 일치한다(`prefix-audit.json`). |

## 분모·시험·mutation

`new.xml`의 실제 call ID를 작성자 생성기/SIZES import 없이 별도 literal 범위와 대조했다. **D90/S63/P20/T21/M36/L72=302**, 누락·중복·초과 0, 보류 N/C/H 0이다(`literal-id-audit.json`). 의미 행 302와 meta 감사 1node를 구분한다. D의 정책/자원 축은 선언 비간섭·타입 분리를 확인하는 반복이며 실제 GPU/장치 실행 검증이 아니다. L의 fake 관측을 실제 서비스 인증으로 세지 않는다.

| 직접 실행 | 결과 |
| --- | --- |
| 신규 6파일 | 303 PASS, error/skip 0. command wall 4.078초, 60초 이내 |
| 정적 감사 단독 | 1 PASS, error/skip 0 |
| `-m property` | 1 PASS, 302 deselected, error/skip 0 |
| `-m "not ui"` | 175 PASS, 128 deselected, error/skip 0 |
| 독립 손 oracle | 최종 44 PASS, error/skip 0, command wall 3.265초(`independent-final.json/xml/log`). 대상은 `test_independent.py`이며 작성자 시험 fixture/기대 표를 import하지 않음. 빈 모델 추가 전 정상 44건 및 추가 경계 선택 실행 2건도 별도 로그로 보존 |
| 관련 회귀 | G13 `test_model_bundle.py`를 포함한 지정 13파일 **2,559 PASS**, error/skip 0, command wall 89.788초(`related-correct.json/xml/log`). `test_model_runtime_independent.py`를 대신 포함했던 추가 13파일 실행은 2,046 PASS로 별도 보존한다(`probes.json`) |
| 정적 검사 | ruff check PASS, format 224파일 PASS, mypy 96 source files PASS |

독립 변이는 별도 사본에서 하나씩 적용했다. **19개 목표 assertion FAIL / error 0**, 동등 1개를 분리했다(`mutations-verified.json`). 검출된 원인과 정상 oracle는 다음과 같다.

| ID | 단일 결함 | 목표 독립/기존 node | 판정 |
| --- | --- | --- | --- |
| R01/R02/R03/R17 | 지원 선언 제거 / NOT_RUN 승격 / enum 검증 제거 / timestamp 제거 | 독립 literal 선언 10쌍 | 4개 검출 |
| R04 | 완전성 truthy 허용(1/yes) | 독립 only_literal_true | 검출 |
| R05/R06/R07 | TTL 경계 늦춤 / 이전 identity 응답 허용 / bind 무효화 제거 | 독립 expiry·late identity·실제 model 변경 | 3개 검출 |
| R08/R09/R10/R11 | timer 미시작 / 설정 세대 증가 제거 / 권한 세대 증가 제거 / 미등재 문구 제거 | 독립 실제 timer·context 변경·grant | 4개 검출 |
| R12/R13/R14/R15 | UI 지원 반전 / custom 안내 숨김 / non-Ollama cloud 안내 / Gemini 모델 고정 | 독립 UI 안내·기본 주소 | 4개 검출 |
| R16 | M9 preview 초기화 제거 | 작성자 M033 | assertion FAIL, teardown error 0 |
| R18 | parser의 모델 ID 집합 누적 제거 | 작성자 S004 | assertion FAIL, teardown error 0 |
| R20 | NOT_RUN 승격, 부분 선택 감사 검증용 | 작성자 D001 단독 | assertion FAIL, teardown error 0 |
| R19 | select_session의 명시 invalidate 한 줄 제거 | 독립 실제 세션 변경 | 합법 세션 전환 범위에서 동등: 이어지는 refresh의 FactIdentity.session_generation 변경→bind 무효화가 같은 효과를 냄. 검출 수에 넣지 않음 |

정상본 PASS와 실패 내용을 확인했으며 수집·import·timeout·오류만으로 검출한 변이는 없다. R16/R18/R20은 실제 call assertion 실패 뒤에도 선택 실행 감사 teardown 오류가 0이다. 위 19개는 작성자 전체 58개 변이의 재실행 완료를 뜻하지 않는다.

## GS04 전체 CI 동등 검증 — 완료

2026-11-26 기준 사본의 `.github/workflows/core.yml:33`·`:35`·`:40`·`:46`·`:48`·`:50`과 대조했다. 모든 명령은 `runtime.json`에 argv로 보존했다. 전체 오프라인 회귀와 coverage 실행은 **같은 한 번의 전체 실행**이며 두 번의 전체 PASS로 합산하지 않는다.

```text
python -m pytest -q -p no:cacheprovider -W error::ResourceWarning
  --rootdir <사본> --basetemp <고유 OS TEMP>
  --junitxml <증거>/full.xml
  --cov=recoryn --cov-branch --cov-report=term-missing
  --cov-report=json:coverage.json --cov-fail-under=85
python scripts/check_coverage.py coverage.json
python -m ruff check src tests scripts packaging
python -m ruff format --check src tests scripts packaging
python -m mypy src/recoryn scripts packaging
PIP_NO_INDEX=1 python -m pip wheel --no-deps --no-build-isolation
  --no-cache-dir --wheel-dir dist .
```

cwd/rootdir는 `C:/Users/gangd/AppData/Local/Temp/recoryn-gs04r1-22y9uo4j`, PYTHONPATH/MYPYPATH는 그 src다. offscreen·HF offline·telemetry off·bytecode off를 유지했다. 의존성 설치·네트워크 조회를 수행하지 않기 위해 기존 `.venv`를 사용하고 wheel의 build isolation을 끄고 인덱스를 차단했다. 이는 설치 단계를 포함한 원격 matrix 전체 재현 선언이 아니다.

- **28,839 PASS, failure/error/skip 0**, pytest 1,917.10초 / command wall 1,930.611초. ResourceWarning 보고 0. `full.xml/log` 참조.
- 전체 combined coverage **92.8674%**, line **94.2080%**, branch **88.8777%**. 다음은 `check_coverage.py` 직접 출력 전문이다.

```text
domain: line=99.18%/95% branch=97.89%/90% PASS
capture: line=99.73%/95% branch=98.29%/90% PASS
jobs: line=99.20%/95% branch=95.65%/90% PASS
storage: line=96.21%/95% branch=91.55%/90% PASS
security: line=98.11%/95% branch=94.43%/90% PASS
content: line=98.98%/95% branch=99.02%/90% PASS
all: line=94.21%/85% branch=88.88%/80% PASS
```

- offline wheel `recoryn-0.2.0.dev2-py3-none-any.whl` 생성 성공. SHA-256 `6e680cb925cb4536dff0d06d87b64836e60c1d8c83f0f22e37400df5fbc9768b`. wheel 내부 `recoryn/providers/facts.py`는 검증 사본 소스와 원본 바이트가 같다. wheel을 설치하거나 실제 서비스를 실행하지 않았다.
- `final_audit.py`가 대상 11파일의 시작 입력/검증 사본/작업 트리 LF 해시 일치를 확인했고 GS11a 17파일 동결 해시도 일치했다. 전체 coverage JSON과 최종 결과는 `coverage.json`·`final.json`에 보존했다.

## 최종 판정·미검증

**GS04-R1: 검토 범위에서 수락 가능 / 제품 OPEN 0(S0 0·S1 0·S2 0·S3 0). H-P02: 문서 수락 가능 / OPEN 0.** 재현해 제안할 새 결함이 없어 발견 ID를 만들지 않았다. 작성자 소스·시험·계약을 수정하지 않았으며 Git 쓰기도 수행하지 않았다. 최종 commit/push는 X00의 책임이며 실제 선행 CI 게이트를 별도 확인해야 한다.

미검증은 Python 3.11 matrix·새 optional runtime 설치·원격 CI 재실행, 04b의 N/C/H 335행·실제 metadata route, 실제 장치/모델/서비스/계정/TLS/유료 호출/Credential Manager/Narrator다. 생산 registry가 비어 있고 actual_service_status가 NOT_RUN인 경계를 유지한다. 이 결과를 실제 서비스 인증, GS04b 완료 또는 v1.0 전체 구현 완료로 집계하지 않는다. GS11a는 별도 재개 지시까지 동결을 유지한다.
