# BR44 root CI·패키지 metadata·복구 기록 독립 검토

검토자 R12 / 작성자 R00(root), 2026-11-14. **REVIEW_READY — BR44-01~03 RECHECKED, 이 검토의 미해결 0건**. 쓰기는 이 문서에만 한정했다. R12의 B21 작성물은 이 독립 판정의 대상이 아니며 BR13-07 재작업·재확인은 별도다. 최종 통합·commit·push는 root 책임이다.

## 범위와 방법

읽기 전용 대상은 `.github/workflows/core.yml`, `pyproject.toml`, `docs/implementation/product-contracts.md`의 owned guard 확장, `docs/implementation/product-results.md`의 재부팅 복구 기록이다. 의존성의 실제 연결을 위해 requirements 두 파일, 선택 화자 구분 capability, release entry/smoke, provider DTO/Gateway/Privacy guard와 협업 규칙을 추가로 읽었다. 대상 코드나 시험은 수정하지 않았다.

YAML은 로컬 PyYAML BaseLoader로 구문과 job/권한/고정 action SHA 구조를 확인했다. TOML은 표준 tomllib, marker는 packaging.Requirement로 읽었다. 새로운 구현 복제 시험은 만들지 않았다. 임의의 네트워크·장치·모델/weights·계정 변경 없이 기존 fake 계약 시험 한 case와 읽기 전용 metadata probe만 실행했다. 원격 GitHub Actions 실행·설치 재현·패키지 smoke/실모델 승인으로 확대하지 않는다.

## 발견 및 재확인

### BR44-01 / S2 — clean core CI에 NumPy 시험 의존성 누락

최초 `.github/workflows/core.yml`의 core 3.11/3.13은 requirements-dev만 설치하고 전체 pytest를 실행한다. 최초 requirements-dev와 pyproject dev extra에는 NumPy가 없었다. `tests/contract/test_diarization_contract.py:226`의 fake offline API 시험은 NumPy를 무조건 직접 import한다. Qt Essentials의 설치 metadata도 shiboken6만 요구하므로 core의 전이 의존성으로 NumPy가 설치된다고 볼 수 없었다. 개발 환경의 선택 AI 설치가 이 차이를 가린다.

기존 시험 `test_fake_offline_api_scope_overlap_and_source_immutability[rate]`를 별도 subprocess에서 실행하되 MetaPathFinder로 NumPy import만 차단하여 clean-core의 누락을 모사했다. **1 FAIL / ModuleNotFoundError**, 0.25초를 확인했다. 이것은 실제 깨끗한 Python 3.11 VM의 pip 설치 실행이 아니라 명시한 누락 조건의 재현이다. 로컬 패키지를 삭제·변경하거나 제품 코드를 바꾸지 않았다.

root 수정 후 requirements-dev와 pyproject dev extra 모두 `numpy==2.3.5`를 명시한다. 기본 runtime `dependencies=[]`는 유지되고 core에 sherpa/ONNX/Faster-Whisper 엔진이나 weights를 필수 설치하지 않는다. 설치된 NumPy distribution metadata의 Requires-Python은 `>=3.11`이다. 정본 두 파일의 명시 시험 의존성을 읽기 전용으로 재확인했고 import 차단 없는 동일 기존 case는 **1 PASS**, 0.36초였다. **RECHECKED**. 수정 후 clean runner 3.11/3.13의 실제 설치·원격 CI 통과는 root의 후속 실행 대상이다.

재현/재확인은 `.venv/Scripts/python.exe`, `-p no:cacheprovider`, 각 실행 고유 TEMP basetemp를 사용했다. 원 재현 prefix는 `recoryn-br44-clean-core-`, 재확인 prefix는 `recoryn-br44-recheck-`다. 재확인에는 `-W error::ResourceWarning`도 적용했다.

### BR44-02 / S3 — marker와 runtime 아키텍처 이름 불일치

최초 diarization extra marker는 `platform_machine == 'AMD64'`만 허용했지만 runtime `_platform_supported()`는 AMD64와 x86_64를 모두 허용했다. 최초 파일 읽기에서의 코드 차이이며 그 시점의 x86_64 실제 장비 실행이라고 주장하지 않는다.

root가 세 optional requirement의 marker를 `(platform_machine == 'AMD64' or platform_machine == 'x86_64')`로 수정했다. Python 3.11/3.12/3.13 × win32/linux × AMD64/x86_64/ARM64의 **18개 metadata 환경**을 평가해 runtime 선언과 모두 일치했다. Windows x64 및 Python>=3.12에서만 선택되고 Python3.11·ARM64·Linux에서는 선택되지 않는다. CPU만 지원한다는 runtime/문서 조건도 유지한다. **RECHECKED**. metadata 평가가 해당 OS/CPU·wheel의 실제 호환성 시험을 뜻하지 않는다.

### BR44-03 / S3 — product-results 구현 추적 표의 시점 미표시

복구 기록은 1137 PASS를 이전 snapshot으로 명시하고 후속 8/3/9개 실패 반례와 최종 재실행 필요를 보존한다. 반면 바로 뒤 `구현 추적` 표는 별도 과거 snapshot 표기가 없으며 선택 화자 구분을 아직 speaker label 데이터 경계만 존재한다고 쓰고, live 전사·Ollama UI·패키징 연결도 일괄 후속 작업으로 둔다. 현재 B21/B22/B23의 REVIEW_READY 또는 독립 재작업 상태와 직접 대조할 수 없다.

해결 조건: 표를 당시 이력으로 명시하거나 현재 작성/독립 검토/재작업 상태와 최종 미검증 범위를 연결해 갱신한다. 작성자 자체 PASS를 독립 승인·구현 전체 완료로 바꾸는 수정은 해결이 아니다. **OPEN**, root 문서 수정 후 같은 검토자가 재확인한다. 과도한 통과 주장은 현재 문서에서 발견하지 않았으며 이 항목은 현재 진행 상태의 가독성·추적성 문제다.

## 문제를 발견하지 않은 경계와 한계

| 경계 | 직접 확인한 내용 | 확대하지 않는 주장 |
| --- | --- | --- |
| CI core | Windows, Python3.11/3.13 matrix, 권한 contents:read, checkout credential 비보존, action 40자리 SHA 고정, lint/format/strict mypy/coverage의 line·branch 분리 검사와 wheel 생성 경로가 있다. | SHA의 공급망 진위·현재 원격 run 통과·실제 두 interpreter 설치를 이 리뷰로 인증하지 않는다. |
| optional CI | Python3.13에 명시 optional extras를 설치하고 계약/릴리스 fixture와 source `--release-smoke`를 실행하도록 배선했다. | CI의 dependency 설치 통신과 제품 기본 egress를 동일하게 취급하지 않는다. 실제 weights·장치·유료 호출은 설정에 없다. |
| source smoke | 코드상 native runtime import/production worker 무요청 시작·종료, 합성 두 트랙과 frame oracle, 원본 hash·파생 WAV, offscreen GUI, 미동의 Gateway의 DNS 이전 거부를 검사한다. native capture/vault 호출은 실패 fixture로 차단한다. | Python audit hook은 모든 native DLL/외부 daemon의 후속 트래픽 관측이 아니다. smoke 자체 출력도 이 한계를 명시한다. BR44에서 source smoke를 새로 실행하지 않았다. |
| 공용 guard 계약 | 선택 lifetime_guard와 TTL, static trusted fixture 호환, for_session의 dispatch_guard 보존, 고정 proof/scope, consent→ledger→owner 순서와 open/write/최종 응답 경계 설명이 읽은 DTO·Gateway·Privacy 코드와 일치한다. | 실제 helper 프로세스·Job·listener/ACK 반례 종결은 R14 등 별도 검토다. BR44가 B21 GUI나 owned helper 수명 전체를 승인하지 않는다. |
| 복구·결과 문서 | 과거 P0.1 379·중간 797/1137 및 실패 기록을 현재 최종 통과로 합산하지 않고 root 최종 digest/전체 회귀를 별도로 요구한다. 실제 음성·장비·모델·license·G3/G4·정식 릴리스는 미검증이다. | root가 보고한 1388 PASS/coverage와 이후 ACK 수정은 이 리뷰의 직접 실행 수치가 아니다. 최종 재실행 전 전체 완료로 쓰지 않는다. |
| Git 권한/대상 | 현재 branch main, origin은 `git@github.com:gangdonggilstudy/Recoryn.git`이다. 문서의 HTTPS 경로는 같은 host/owner/repository `https://github.com/gangdonggilstudy/Recoryn.git`를 가리킨다. worker Git/승인 대행 금지와 root만 최종 push한다는 권한이 일치한다. | SSH 권한 거부·HTTPS credential dry-run 성공은 root의 실행 보고다. 검토자는 credential을 읽거나 원격 쓰기/dry-run/push를 하지 않았고, dry-run을 실제 신규 commit/push 성공으로 인정하지 않는다. |

## 검토 snapshot

처음 읽은 파일과 root 수정 후 재확인 파일을 구분한다. root가 병렬 문서 정리 중이므로 저장소 전체 동결 승인은 아니다.

| 파일 | 초기 SHA256 | 1차 재확인 SHA256 |
| --- | --- | --- |
| .github/workflows/core.yml | 8B1101CD75D3462E04D689CA17EC0AEC67663AEF7E7CBC9B2B768DD7CCC1058B | 동일 |
| pyproject.toml | FCBBB16DFC202855471227A28ACD407AEA5CAD5695779E8CAD01EB106F59EDFD | F8921C4EE5A1D9ECD45BA25EFC279E49D7BB115D846232528CE53CA27791225B |
| requirements-dev.txt | 최초 NumPy 항목 없음(내용 대조) | 9264043029F6DF1B12D8A964ED156F0EC4D90BFF5E05A5DF064025B10C0AEF05 |
| product-contracts.md | B8E9259C6AC15D70520F6A5C48737A8B32685A3FED267A4FAF38E025FE5103EF | 동일 |
| product-results.md | 374153C30E39FC1731A3B97598B614A2828FC462C2EA1843A4F6E35AD93C250E | 동일, BR44-03 미해결 |

TOML/YAML 및 18 marker 환경의 로컬 읽기 전용 probe는 PASS다. 발견 2건의 RECHECKED는 명시한 metadata/기존 fake case 범위이며 원격 CI·clean Windows 설치·실제 모델/weights 라이선스·G3/G4/배포 승인과 분리한다. 최종 CLOSED와 서버 push는 root가 판단한다.

## BR44-03 후속 독립 재확인

root가 수정한 product-results.md SHA256 **6AAF70AF3458C0AFB3B4D57C07DBF64CD63B5B428782A0CB267F107FE5874091**을 원 해결 조건과 대조했다. `구현 추적` 표는 재부팅 후 현재 작성·독립 검토 snapshot임을 명시하고, B21 자체 350 PASS와 BR13-07 재작업·BR12/13 검토, B22/BR41의 ACK 반례 재확인, B23/BR42·첫 frozen smoke와 최신 코드에 따른 최종 후보 재생성, helper/guard의 독립 검토 상태를 각각 연결한다. 과거 379/797/1137과 중간 배정 수치를 합산하지 않으며 최종 동결·artifact·commit/원격 상태는 후단에 별도로 고정한다.

각 행은 실제 장비·OS sleep/Narrator·실모델/서비스·라이선스 법률 판단·clean VM/서명·G3/G4의 남은 한계를 보존한다. 현재 작성·독립 재작업 상태를 전체 제품 완료나 공식 릴리스 승인으로 확대하지 않는다. **BR44-03 RECHECKED**, 위 OPEN과 초기 hash는 발견 당시 이력이다. 이 문서·metadata 범위의 OPEN S0/S1/S2/S3은 0건이며 최종 CLOSED는 root가 판단한다. 현재 B21 재작업과 그 최종 승인·artifact의 동결은 이 판정 밖이다.
