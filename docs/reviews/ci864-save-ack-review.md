# CI864 — 저장 시험 완료 대기의 독립 재확인

작성 역할은 p8의 시험 한 함수 수정, 독립 실행 검토는 pB, 이 문서의 전사는 X00다. pB는 GS05 제품·시험 작성자가 아니며 이전 GS05 계약·d127 교차 독립 검토 이력이 있다. 기존 private API 손 준비는 동결했고 현재 API 후보를 읽거나 승인하지 않았다.

상태는 **로컬 ACK 공백 보강 CLOSED / 새 OPEN0 / 정확 통합 문서·원격 복구 판정 별도**다. X00는 작성자29seal/무계측125건과 독립38seal/19선택을 인수했다. 정확 tree·이 문서 전사 검토·원격 CI 성공을 이 제목의 CLOSED에 포함하지 않는다.

대상은 공개 `864e238961dc00807114d3dd6ce14f2e2eb5ee79`의 `tests/ui/test_secret_lifetime_ui.py::test_save_admission`이다. 같은 commit의 [CI45914988082](https://github.com/gangdonggilstudy/Recoryn/actions/runs/45914988082)에서 core3.11은 GS05-S-2-0의 원412행이 기대 VAULT_WRITE_FAILED 대 접수·확인 중 문구로 실패했고, 30,165건은 통과했다. core3.13과 optional-runtime은 성공했다. 원격 실패를 문서 전용 commit의 결과라는 이유로 무시하지 않는다.

CredentialService는 native 완료 뒤 pending/queue를 내리고 나서 실제 done(KeyResult)를 호출한다. idle은 GUI reply 소비 ACK를 보장하지 않는다. 수정은 save 직후 nonce·generation을 캡처하고 접수된 outcome에서 kind=stt/tag=key/같은 nonce·generation의 실제 reply를 기존 bounded spin으로 기다리는 것뿐이다. 기대 문구·timeout·sleep·S16/원70 Assert AST·다른 함수/공통 helper·제품을 변경하지 않는다. outcome0 접수 거부는 ACK 대기0이며, view1/2/3은 옛 reply 수신과 stale/closed 화면 거부를 분리한다.

pB의 사전 손 순서와 독립 thread trace는 원 key_done의 실제 emit 직전을 event로 유보했다. 원 조사 ack_probe나 ui_world wrapper를 복사하지 않았고 실제 메모리 fake native 오류·KeyResult·원 emit/GUI slot을 그대로 실행했다. 후보의 실제 ACK predicate 진입과 정확 nonce·generation이 해제 조건이며, 예상 status를 해제 조건으로 쓰지 않았다. 동일 KeyResult 객체가 실제 GUI slot에 전달되는 것을 관측했다.

| 직접 선택 | 결과 |
| --- | --- |
| 후보 원S16 정상 대조 | 16 PASS |
| original target + 독립 barrier | 원412행 표시 assertion FAIL1, teardown error0 |
| 후보 target + 같은 barrier | PASS1, 원 표시 단언 전에 VAULT_WRITE_FAILED |
| 추가 ACK 조건 한 site만 비활성 target | 같은 표시 assertion FAIL1, error0 |

직접19선택은 PASS17·의도한 원실패1·한site 목표실패1이다. error·skip·MASKED·INVALID0, 준비·종료 감사를 포함해17.887189초다. 원 반례와 같은 ACK site의 재확인을 새 고유 fault 두 개로 세지 않는다. 정상16에도 관측 trace와 spin 위임은 있었지만 barrier hold는0이며 원 predicate·native·slot이 실제 실행됐다.

검사한 preview의 raw SHA는 `cc5df104a87b737c31da1635ed4f53a9e266df0727be9b77c74d2d84cd7d9a81`, LF SHA는 `c6cc0deff1c307df3e7183dc1eabb50697a6241ecfdb9bcecfd90cce90458f3d`다. 모든 source/비소유 파일·원조사36seal·손준비2는 불변이며 parent/실제 spawn/pytest cwd·rootdir·config·PYTHONPATH가 고유 사본을 가리켰다. pinned Python3.13.1·offscreen/offline/no cacheprovider/ResourceWarning error를 사용했다. 실제 vault·장치·네트워크·모델·새 agent/pane·승인 UI·공유/Git 쓰기0이다.

독립 제출은 `build/ci864-save-ack-cross-review/report.md` LF `5832f3f7af61646dd1fc5edd94c144f3bf6a6ad6dd8142bbd88c7d4e2f94d679`, evidence LF `d460ac76fe57a6c38cb08ce25c190a9187a8e13c114c2bc75d69e01ac650b331`, 원38파일 seal LF `5867cfdea7269bbed3e3e436f3b4a94bbba5d4343244751b879b18e0b55c36f4`다. X00가 실제38파일 raw/LF·XML4·오류0·변이 단일site·공유 시험 LF 일치를 직접 대조한 기록은 `build/g09a-prep/x00-ci864-cross-review-intake.json`이다. 이 로컬 증거를 전체 core/coverage/wheel 실행으로 확대하지 않는다.

X00의 정확 archive864+복구4파일 사본에서 CI 대상 Ruff check/format과 mypy src/recoryn·scripts·packaging은 모두 통과했다. 결과는 `build/ci864-exact4-static/result.json`이다. 임의로 시험 파일까지 넓힌 mypy의 기존5건 FAIL은 별도 보존하고 이번 국소 변경의 새 타입 오류0과 구분해 수락했다. 기존 오류를 고치는 추가 범위나 ignore를 도입하지 않았다. 제품 src/비소유 파일은 archive raw와 같고 로컬 full/coverage/wheel을 새로 실행했다고 주장하지 않는다.

로컬 결정적 반례는 원격 실패와 부합하는 시험 공백을 보이지만, 원격3.11 당시 상세 사건 순서는 미확정이다. 실제 로컬3.11·다른 helper 호출처의 전체 회귀·실장비·실vault는 미검증이다. 정확 복구4파일 전사·tree·commit 전체 메시지/trailer0·원격 ref·복구판 실제3작업 성공을 추가 gate로 둔다. 다른 G09 제품 기능 공개는 복구 원격 성공 전까지 보류한다.
