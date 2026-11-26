# GS-P11a 삭제 이력 권위와 관리 경로 독립 검토

검토자 X00(w5:p9). 구현 w5:p8, 접근성 시험 패치 w5:pB. 제품·제출 시험을 작성하지 않았다. 현재는 독립 경계 대조와 공개 기준 26파일 합성 사본을 검증 중이다.

## 인수 범위와 기준

- 작성자 기준 `b77cc102a9db818a8c1d1a2840933ffa28e1b14c`. 동결 26파일 목록 LF SHA-256 `bb1ecdb5613628e341cdd74f33de69074ef59cdd7edf152887ff1fe3e8405f87`. 작성자 `final.json` LF SHA-256 `300be01e35de0f9c100e9603fc47d7fbcf6c1d209e290c69df08ffa80868c541`.
- 제품8, 신규 시험4, 기존 시험13, 계약1. 접근성 시험은 승인 패치 LF `1e2e8a65e2e844c6a3796b7d11228a9e79cdafb83de8a29c725d1521d89ec689`의 제출 blob LF `c36ac6dc761f5d2548096d25c54f8792bddc64b3c883244ae5e96500b6560a13`을 인수했다. GS05가 사용 중인 공유 파일을 복사하거나 바꾸지 않았다.
- X00 검증 기준은 원격 CI가 성공한 공개 `b30b3a7b7223fa20ca19ae17fe1975aa80e598f2`다. `git archive` 사본에 26파일을 적용했다. 두 기준 사이 13파일 변경과 제출 범위의 교집합은 0이다. 공개판의 GS04a 제품과 시험을 포함한 별도 전체 검증을 실행한다. 제출 문서는 작성자 CI 사본에 실행 결과만 덧붙인 내용임을 바이트로 대조했다.

## 독립 경계 대조

| 경계 | 코드와 직접 확인 |
| --- | --- |
| 긍정 권위와 음성 삭제 사실 | `storage/deletion_history.py:69,264,275,319,361`은 검사 시작의 두 시계와 제한된 게시 조건을 쓴다. 정상 delta와 negative floor는 새 검사 시각을 만들지 않는다. `storage/library.py:669,715`는 root의 유효 권위에서 짧은 Job transaction을 허용하고 commit 직전에 만료를 확인한다. 손 clock으로 30초 직전 정상 삭제가 있더라도 정확히 30초에 목록과 새 게시가 거부되며, Job과 reader 상태는 거부로 변하지 않고 실제 reader 종료 ACK만 적용되는 것을 확인했다. |
| 미완료 파일과 자기 녹음의 분리 | `storage/library.py:3441`의 알려진 staged 파일 분류, 권한 예외의 instance·nonce·등록 수명·file ID를 대조했다. `app/recording.py:128,142,864`의 명시 종료 문맥은 실제 source/writer/sealer 상태와 해당 run에 묶이며 `storage/library.py:1175`에서 재검증된다. 별도 TEMP의 세 파일명 계열에서 최초 및 fresh 전역 거부, 식별 대상 조회 거부, 무관 세션 조회 성공, canonical journal·DB 삭제 상태 생성0, 원본 bytes 보존을 직접 확인했다. |
| 목록과 취소 | `storage/library.py:1345,1417`은 최대128행의 keyset을 사용하며 cursor를 instance 및 catalog 버전에 묶는다. 손 기대 `east,north`와 `west`의 페이지 순서, 삭제 후 옛 cursor 거부, 재열기 후 다른 instance의 cursor 거부, 삭제한 ID 미표시를 직접 확인했다. `app/history.py`의 단일 in-flight와 최신 요청 합침, `ui/main.py:607,623,1460`의 명시 검사 무효화·종료 시 세대·실제 worker ACK 경계를 읽어 대조했다. |

독립 검사 5건은 작성자의 시험 fixture를 import하지 않았다. 부모와 실제 spawn import가 같은 사본의 `src`를 가리키는 것을 확인했다. `build/gs11a-x00-review/state.json`에 검증 상태와 정확 파일 해시를 기록하며, 실행 폴더의 `independent-final.log`에 별도 검사 결과를 보존했다.

## 검증 결과와 운영 제약

- 작성자 제출본에서 신규 510건(정본390·기존 보강79·coverage35·파일명6), ID 누락·중복·초과0, 준비 포함335.86초를 확인했다. 승인 상한은360초다. 정상 대조27건과 단일 변이31건의 목표 assertion 실패, 정확 해시를 대조했다.
- 작성자 기준 전체29,046 PASS·coverage 7묶음·오프라인 wheel PASS. 전체 storage line95.23%·branch90.02%다. X00 공개 기준 사본의 ruff·format·mypy·GS04a 교차 회귀303건은 PASS이며, 전체 검증 결과는 완료 뒤 추가한다.
- 대문자 파일명 수정 전 실제 규모 측정에서 1만 건 최초 열기52.83초와 10만 건618.76초에 관리 권위가 확보되지 않았다. Job·목록은 거부됐고 1·2트랙 모사 녹음은 수락 원본을 저장했다. 1천 건 별도 프로파일에서 format-1 journal 파일 열기 비용이 컸다. 최신 해시 대량 실측이나 실장비 보장은 남아 있다. 30초를 늘리지 않으며 G-P09와 GS-P11c에 정본·파생물 구분 및 대량 이력의 운영 한계를 인계한다.

## 공개 기준 첫 전체 실행

- `b30b3a7`+26에서 **29,348 PASS·1 FAIL·error/skip0**. 실패는 `tests/ui/test_local_server_notice_ui.py::test_server_notice_and_facts[GS04-L-003]`의 실제 Qt 타이머 만료 표시다. 이 파일의 단독 포함 GS04a 교차 회귀303건과 7묶음 coverage, wheel의 제품8파일 바이트 대조는 통과했다. 첫 실행은 `build/gs11a-x00-review/recoryn-gs11a-x00-173qgum5/`에 보존했다.
- 앞선 별도 시험에서 정확한 300초와 활성 timer 상태에도 한 차례 `QTest.qWait(5)`가 실제 이벤트 처리로 1초 넘게 걸린 뒤, 실행 대기 중인 timer callback을 처리할 다음 이벤트 순서 전에 poll이 끝났다. 공개 기준 결과에도 같은 표시 실패가 발생했다. 이번 첫 실행의 개별 timer tick은 계측하지 않았다.
- 추가 범위는 같은 시험의 `qWait` 반환 직후 실제 이벤트 처리 한 번이다. 기존 fake clock 300초, timer 시작 경로, 1초 poll, 표시 oracle 및 ID를 보존한다. pB가 격리 패치를 작성하고 X00이 대조한다. GS05 공유 파일의 수정은 합성 사본에 복사하지 않는다. 추가 패치를 포함한 공개 기준 전체 재검증이 끝나기 전 공개하지 않는다.

## 만료 시험 적응과 27파일 재검증

- pB 패치 LF SHA-256 `4025e756f4236ba7480c4dda08be2851b5effd2598ea1772e8c727fdbc60074d`, 증거 JSON LF SHA-256 `acdede6a16fcc34328138e8b471581b3f7115688ac8ffa6e7c9612d336e583b4`. 실제 추가 호출과 주석만 제거하면 공개판 원본과 바이트가 일치한다. GS05의 다른 fixture 이행과 interval 변경은 가져오지 않았다.
- pB의 같은 사본에서 L72 전부 PASS, timer 시작을 제거한 L01은 원 만료 표시 assertion에서 실패했다. 실제 이벤트 처리 지연을 같은 방식으로 주입한 두 사본에서 원본 FAIL·수정본 PASS였다. 초기 하네스에서 타깃 이벤트가 이미 실행된 결과는 INVALID로 보존했다.
- X00은 이 시험 blob LF SHA-256 `194544a7ef9210bbd19dbf952cb2cbf395990c99d02a1100164da02f2e39e70c`만 더해 `b30b3a7`+27을 다시 만들었다. 두 공유 시험은 TEMP에서 계속 분리한다. 새 사본에서 독립 권위 검사 5건이 통과했다. 전체 재검증 결과는 별도 최종 판정에서 확인한다.

## 최종 합성 판정

- **VERIFIED · OPEN 0.** 공개 기준 `b30b3a7`에 27파일을 적용한 동일 격리 사본에서 전체 **29,349 PASS**, 실패·오류·skip 0을 확인했다. 독립 권위 검사 5건과 GS04a 교차 회귀 303건도 통과했다. `ruff check`, `ruff format --check`, mypy, 부모와 실제 spawn 자식의 import 출처 확인을 마쳤다.
- Coverage는 7묶음이 모두 통과했다. Storage는 line 95.23%와 branch 90.02%였다. 오프라인 wheel을 만들고 제품 8파일의 바이트가 시험한 사본과 일치함을 확인했다. Wheel SHA-256은 `82faa7e7af19c39adfb3214f1369936f6c421ce3b9226ae0eb11109bbc9ca040`이다.
- 동일 실행의 증거는 `build/gs11a-x00-review/recoryn-gs11a-x00-h14u_uk5/`에 있다. 공개 전 선행 `b30b3a7`의 원격 CI 세 작업이 모두 성공했음을 확인했다. 이 단위의 원격 CI는 공개 뒤 확인한다. 대문자 파일명 수정 이후 대량 실제 clock 재측정과 Windows 실장비 검증은 남아 있다.

## 원격 CI와 G12 시험 준비 회복

- 공개 `494342a`의 [원격 CI 45810798432](https://github.com/gangdonggilstudy/Recoryn/actions/runs/45810798432)에서 Python 3.13 core는 **29,258 PASS·91 FAIL**이었다. 실패는 전부 `tests/integration/test_basis_publication.py`에 있고, Job이 `QUEUED`에 남은 25행과 provider 시작 장벽을 통과하지 못한 66행이다. `optional-runtime`은 성공했고, 이 기록 시점의 Python 3.11은 진행 중이다.
- 해당 파일은 모듈 공용 Library에서 테스트를 반복하고 최초 정상 삭제 권위의 수명은 30초다. X00의 공개 archive 대조에서 G12-P-194는 정상 통과, 시계만 31초 전진시킨 대조는 기존 `gate.entered.wait(5)` 단언에서 실패, 동일 시계에서 정상 준비의 공개 fresh를 적용한 대조는 통과했다. 증거는 `build/gs11a-x00-review/basis-ci-expiry-probe-v2/`에 있다.
- 작업자 w5:pA의 수정 후보 LF SHA-256은 `394855cafc03414d03e48b159ade4bbfaab90468f2e4d0a69e8be91b933ae2e9`다. 두 준비 경로에서 Job을 시작하기 직전에 공개 fresh를 수행하고 정확 READY를 확인하는 네 줄만 추가했다. 추가한 두 쌍을 지우면 원 파일 바이트와 같다. 해당 후보를 얹고 같은 31초 만료 주입을 했을 때 G12-P-194가 통과했다. 삭제·선택·취소 경쟁을 일으킨 뒤 준비를 갱신하는 변화는 없다.
- 수정 후보의 정확한 전체 격리 검증은 진행 중이다. 선행 원격 실패 상태에서의 회복 전용 커밋 공개는 사용자 예외 승인과 전체 검증이 필요하다. GS05와 G09의 공개는 회복 기준의 원격 CI 성공 뒤 진행한다.

### Python 3.11 완료와 별도 확정 경계

Python 3.11 원격 코어의 최종 결과는 **29,261 PASS·88 FAIL**이다. G12 출판 87건 외에 `G04-F3-PERF-finalize-900` 한 건이 실패했다. 확정 소요 38.3346초, 관리 스레드의 최장 root 보유 0.012484초, 관리 장기 보유 0건이며 최종 권위 검사에서 `DELETION_HISTORY_UNAVAILABLE`를 반환했다. 앞의 3.11 진행 표기를 이 최종 기록으로 갱신한다.

공개 기준의 작은 실제 1묶음 대조에서 정상 `FINALIZED`, 게시 경계 직전 가짜 시계 31초 전진 시 오류와 `FINALIZING` 및 1묶음 보존, 같은 시각의 명시 fresh 대조는 `FINALIZED`였다. 이 마지막 대조는 원인 확인이다. 실제 UI history 확인과 확정 Task는 단일 직렬 pool을 공유하는 데다 CLI가 따로 history Task를 실행하지 않아 fixture에서만 동시 갱신하는 조치는 제품 경계를 검증하지 못한다. G12 준비 수정과 별도로 관리 최종 게시의 실제 새 권위 확인을 검토한다. 원격 로그와 대조는 `build/gs11a-x00-review/f3-recovery-plan.md`에 연결했다.

## CI 복구 최종14의 독립 검토 인수

공개494342a에 library LF `9f1e625c073afb9ef619e0f2d36af3f0c7b8ad6c396ebf3086ea28c4b3f8c939`, unfinished 시험 LF `9c9747d5bfe950e427d9b10b21deac3e27353b3f9bb488f6ae9e4470deeb7f3b`, publication 시험 LF `dad7ac1c18d461267df4e92986bf5a58264b5165ec850c3471062012b5e4bb07`만 적용한 후보를 대상으로 한다. GS05 변경은 제외한다. 첫 binding을 FINALIZING 전이·실제 seal admission과 claim·최종 commit까지 보존하며, 자동 감사는 정상 clock의 L30 경과에만 수행한다. 일반 권위 수명과 최초 입장·명시 무효화·source ACK 계약을 완화하지 않는다.

작성 pA 및 X00의 후보를 pB가 독립 검토했다. 최초 R1의 무효화/clock 반례, R2의 첫 binding 유실, 구13의 마지막 독립 검사와 실제 seal 입장 사이 경합은 수정 이력과 구분해 보존한다. 최종 검토 `build/gs11a-x00-review/f3-r4-cross-review.md` LF `0606aaf9299ed1a2269581de8dbaae3479c72e3ae866a3b2aeab5fbbe40696b5`는 제품 OPEN0이다. 같은 구13 반례에서 admission/claim/manifest 각1이 최종14에서는 각0이며 새 receipt는 실제 유효하고 FINALIZED event0·PCM bytes를 보존했다. 독립 AUTH14 PASS와 M09 목표 assertion FAIL, 자기 capture/API 기본 호출 대조도 확인했다. 이 판정을 전체 회귀나 원격 CI 성공으로 확대하지 않는다.

D96 준비의 독립 검토 `build/gs11a-x00-review/g12-d96-review.md` LF `5e9aa9f42a276d2c206e8f7f27816f332dcf137929cb852600faf1e0af6f6695`는 OPEN0이다. P/T/D 정상 준비의 공개 fresh+정확 READY 세 쌍만 추가하고 기존44단언·386 ID를 보존했다. 독립8행 및 D 직접2변이에서 준비 뒤 새 감사0을 확인했다. 첫 하네스 INVALID는 검출이나 정상 성공 수와 구분했다.

X00은 공유/실행 사본의 세 해시와 최종 AUTH14·원 PERF/캡처7·관련771 PASS, 최종 단일10변이의 목표 assertion FAIL을 실제 XML과 대조했다. 새 전체 기대는29363이며 전체 CI 동등·coverage7·wheel은 진행 중이다. 원격 Python3.11/3.13과 실제 장비 검증도 남아 있다.

앞의 “사용자 예외 승인 필요” 표기는 절차 해석을 정정한다. [협업 규칙](../collaboration/workflow.md)의 최종 검증 후 오케스트레이터 push 승인과 [푸시 단위 규칙](../collaboration/push-units.md)의 CI 실패 원인 수정·재검증 절차에 따라, 실패 원인에 한정한 이번 복구는 정확 tree의 필수 검증과 독립 판정이 닫힌 뒤 공개할 수 있다. 실패 부모 자체의 CI 성공을 요구하는 순환 조건으로 처리하지 않는다. 다음 의존 단위 GS05/G09의 공개는 복구본 원격 CI의 실제 성공까지 보류한다.

## CI 복구의 로컬 종결과 통합 범위

위 최종3파일에서 **29,363 PASS·실패/오류/skip0**, 수집/실행 JUnit 전체 ID 각각1회를 X00이 대조했다. AUTH14·원 PERF/캡처7·관련771·publication386, 단일10변이 목표 call assertion FAIL·INVALID0, Ruff/format/mypy와 coverage7·offline wheel이 통과했다. process wall2340.344초, Storage line95.20%/branch90.16%, 전체 line94.14%/branch88.79%다. wheel `62c3c2174aca0881bf29c38f3f13143bc3b8fd63c17002a5961e655e89ba9d17`의 package Python85개와 package member bytes를 검사 사본과 대조했다. 비소유 archive426파일과 공유 GS05 원32는 유지됐다.

최종 작성자 증거 LF는 report `af93c570595b93aba7a67e0672a83e93afe553b9e5349e9ba2f0062a5051193c`, evidence `adf4905d1f02c4ad0db006867504276b05bbbd6787f431d9205dc71cae5c5cda`이며 위치는 `build/gs11a-f3-r3/`다. root의 별도 읽기 인수는 `build/gs11a-x00-review/recovery-final-acceptance.json`에 있다. pB의 코드 R4·D96 독립 검토 OPEN0과 문서 검토 LF `6497d0255887844d3389792700cf25b9ef3c11d4e74dfae6600111eba5c7ec6f`를 인수했다. p8의 구13 직접 반례 기록 LF `5a77b15d2699d1c8d1d3ffddb9b4132bcbcf37ab979235e64c124f3590662e26`는 최종14 성공과 분리해 보존한다.

로컬 제품 판정은 **VERIFIED·OPEN0**이다. 통합 후보는 제품/시험3파일, 이 리뷰, gs11 case 문서, 해당 CI 복구 배정만 반영한 assignments의 총6파일이다. 다른 GS05/G09 파일과 미공개 배정은 포함하지 않는다. 정확 tree/부모/실제 commit 메시지와 trailer0·push/ref/복구 원격 CI는 아직 별도 확인해야 한다. 최신 문서 추가와 통합 후보를 pB에게 대조받은 뒤 X00만 Git을 작성한다. 원격3.11/3.13/optional-runtime 새 성공과 실장비·실서비스·내구성은 현재 미검증이다.
