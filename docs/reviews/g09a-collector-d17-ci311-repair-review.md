# D17 CI311 credential UI 시험 완료 시점 보정 검토

판정: **보정 test의 독립 검토 CLOSED / 새 OPEN0**. 같은 D17의 원격 CI 실패를 고치는 시험 전용 변경이다. 제품·기존 helper·timeout·기존 단언은 바꾸지 않는다. 실제 수정 commit의 Python3.11/3.13 CI 성공은 아직 미검증이다. D18은 그 게이트가 닫힐 때까지 보류한다.

## 문제와 변경

게시 commit `deb32a4433415899ee343a89039a9f14bb3de930`의 [원격 run46114304584](https://github.com/gangdonggilstudy/Recoryn/actions/runs/46114304584)는 Python3.11.9에서1 FAIL/30841 PASS였다. 실패는 `tests/ui/test_privacy_ui.py::test_credentials_are_endpoint_bound_fail_closed_and_never_in_config_key`의 `VAULT_WRITE_FAILED` 단언이다. 실제 표시가 아직 키 변경 접수 pending이었다. 같은 run의 core3.13·optional-runtime 성공은 이311 실패를 소급 종결하지 않는다. 원 로그 SHA256은 `412ba4f1952fc386b9e5da587a0789ca14156a6f97a360d6bd31c76d61bb0ebd`다.

CredentialService는 native 작업의 pending을 줄인 뒤 완료 callback을 호출한다. 시험의 일반 settle helper는 native idle과 view pending을 기다리므로 key callback의 실제 GUI 반영 전에도 끝날 수 있다. 원격 당시의 정확한 스케줄을 사후 계측했다는 뜻은 아니다. 아래 실제 지연 재현은 로그와 일관된 가능한 인터리빙을 보여 준다.

변경은 기존 `spin_privacy` import1과 실패 test의 원 exact 상태 단언 앞 `spin_privacy(lambda: control.status.text() == "VAULT_WRITE_FAILED")` 호출1뿐이다. 기존 기본 timeout5초를 사용하며 고정 sleep·timeout 증가·단언 완화·skip/xfail은 없다. callback이 해당 상태를 끝내 반영하지 않으면 bounded wait가 실패한다. 원 상태/secret 비노출/endpoint binding·동의 거부 등을 포함한 Assert AST53개와 원 제품 source·기존 helper는 모두 보존했다. 새 영구 node/ID/분모 증가는0이다.

후보 test raw/LF SHA256은 `cf1503e7c0602ee33464b78c80f64ad8bd08022815d266ef37584bec084a72b9`다. 두 삽입을 역변환하면 원 Git blob `e6a1021bebe85d41d51a701b063889b75dd2a00cbc5bda454eeeda4a33ad6b73`가 정확히 복구된다.

## 독립성과 실제 검증

보정 작성자는 pB다. pA는 원 GS05 test/helper/privacy/credentials 작성 이력으로, p8은 이전 privacy.py 작성 이력으로 각각 독립 검토를 실행 전에 중단했다. 두 세션은 공식 리뷰·시험 실행0이었다. X00은 해당 원 UI/credential 코드와 보정 후보의 비작성자로서 코드·기존 callback 계측을 직접 검토하고 새 deb32a4 archive/TEMP에서 다음 유한 검증을 실행했다. 이 리뷰는 X00이 작성한 제품 코드의 자기 승인이 아니다.

작성자의 callback 계측을 고정 bytes로 복사해 검토에 사용했다. 실제 fake vault 실패로 만들어진 원 KeyResult를 원 done callback에 그대로 전달하되, native pending0 이후 전달 직전만 Event gate로 보류했다. 기대 상태/예외를 stub으로 반환하지 않았다. 원/제거 실패 이후에도 finally에서 gate를 해제해 실제 done·Qt slot·원 teardown을 완료했다.

| 독립 실행 | 실제 결과 |
| --- | --- |
| 원 node, done 전달 보류 | pending0/backend idle인데 GUI pending인 상태에서 원 exact assertion 목표FAIL1 |
| 후보 node, 같은 보류 | bounded wait 진입 뒤 실제 원 callback·GUI slot 반영, PASS1 |
| 후보에서 wait 한 site 제거 | 같은 원 exact assertion 목표FAIL1 |
| 후보 모듈 전체 | 기존18 node PASS |

이는 실행21건 중 후보19 PASS·목표FAIL2이며 새 semantic 분모가 아니다. 각 XML의 testcase ID는 각1이고 error/skip/계측 INVALID는0이다. 후보 지연 실행에서 실제 동일 KeyResult 객체, command nonce·selection generation 일치, 다른 worker/GUI thread, GUI slot 처리 후 exact 오류 표시를 확인했다. 모든 wrapper 복원과 gate release·실제 callback 정리를 확인했다. timeout·수집 실패를 목표FAIL로 세지 않았다.

후보 사본 전체의 Ruff check·format check가 통과했다. 작성자의 별도 mypy100 source files PASS는 작성자 근거로 구별한다. X00은 새 archive의452파일에서 owned test 외451 raw를 보존하고, 부모/실제 spawn의 copy-src import 출처와 공유 index·공유 test 불변을 대조했다. fake vault를 강제하고 socket/DNS guard를 사용했으며 실Credential Manager·외부전송·음성·모델·유료 호출·도구 설치는0이다.

## 증거와 한계

작성자 증거는 `build/g09a-collector-d17-ci311-repair/`의57seal+final이다. report SHA는 `24f7c258c1749399f6c2bc13a931852aa987a47bd53b1c69ccc8a415a3c7be2e`, final SHA는 `25619ae2924d03cc82348b60a7ea8f0054921bb8671d46aeec2d075fd227f2f4`다. X00은57raw·원53단언·최소 diff와 XML 벡터를 직접 확인했다.

독립 증거는 `build/g09a-collector-d17-ci311-repair-review-x00-r2/`의 prepared/results·argv/cwd·XML·실제 callback event·origin/로그에 있다. 최초 독립 사전검사에서 archive CRLF test와 Git LF blob의 raw를 같다고 둔 단언이 제품/시험 call0에서 중단됐다. 첫 script/archive·preflight-invalid를 별도 보존하고, owned test의 Git blob 비교와 archive LF 동등성을 분리한 새 r2에서 최초21 실행을 수행했다. 비소유451 raw는 정규화하지 않았다. 이 사전 오류는 제품 FAIL이나 실제311 성공으로 바꾸지 않는다.

로컬은 기존 Python3.13.1이며 실제3.11·새 수정 tree의 전체30842/coverage7/wheel·새 원격CI는 NOT_RUN이다. 원 D17 전체 PASS1회·게시·실제311 FAIL과 본21 유한 검증의 범위를 구별한다. 제품 변경0인 시험 완료 시점 보정이므로 원 전체를 로컬에서 반복해 성공을 고르지 않으며, 정확2파일 통합 tree의 선택 모듈/정적 검사 후 새 같은SHA의 Windows3.11/3.13·optional CI3을 실제로 확인해야 한다. 실패하면 보정 단위는 다시 OPEN이다. 기존 실패를 재실행 성공으로 지우거나 새로운 기능을 섞지 않는다.

이 보정은 해당 시험의 GUI 완료 단정을 정확한 시점으로 옮기는 한정 변경이다. 모든 UI 처리·실장비·실Credential Manager·운영 안전·D18 native 성공을 보장하지 않는다. 공유 Git/통합·일반게시 및 새 같은SHA CI 게이트는 X00이 담당한다.
