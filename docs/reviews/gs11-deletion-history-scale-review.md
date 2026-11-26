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
