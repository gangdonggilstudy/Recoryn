# G12 / G-P12 요약 basis·근거 탐색·후보 선택 UI 독립 검토

상태: **독립 검토 완료 — S0 0 · S1 0 · S2 4 · S3 5 OPEN**. 검토자는 C00이 지정한 하위 에이전트(Claude)다. 작성자는 w5:p7 Claude다. 이 문서 외에는 저장소 파일을 쓰지 않았다. 코드 수정·Git 쓰기·네트워크·설치·실장비·모델·유료 호출·herdr 조작은 하지 않았다.

## 1. 대상·기준

- 대상 tree `be581445c62228a29e30227b0de92b9625d3076d` = HEAD `31bc88b`(G-P08 포함) + G-P12 13파일. `git diff 31bc88b be581445 --stat`는 13파일 +4,583/−110이다. `jobs/`·`storage/`·`app/status.py`의 차이는 0이다.
- 계약 `docs/testing/g12-basis-a11y-cases.md` LF SHA-256 `3377834e79199abc323ac77eaea5535c2d3200ddf65385438f51e03d63c8cd5d`(원문·§개정 요청·§구현 결과)를 읽었다. 배정표 G12 행의 C00 결정(재계산 basis 정본·provider_basis 참고, 두 영역, 후보 CAS, 분모 2,506, mutation 28, 기존 cancel 연결, 정책 control 접근성만, SUMMARY_PARTIAL=complete=false)을 기준으로 했다.
- 13파일 LF SHA-256 앞 12자리: models `31303a4e8a76`, store `8e6e519b8810`, content/__init__ `56777a186246`, app/ai `663dad9ca6c0`, ui/content `24ef65e8f9ae`, privacy `db7f4b75cec2`, ai_bridge `fb4ff495a0f1`, a11y `4cffff275548`, test_claim_basis `f8a064b62f21`, property `bf0aaf0645de`, integration `40e1a41328f1`, ui test `b67afb058d59`, 계약 `3377834e7919`.
- 실행 위치: `build/review-trees/g12a`(`git archive be581445 | tar -x`). PYTHONPATH는 사본 `src`로 고정했다. 자식 프로세스와 변이 사본의 `recoryn` import 출처가 사본임을 확인했다. 작업 트리의 GS-P02 미완성 변경은 쓰지 않았다. 반례·측정 스크립트와 로그는 `build/review-trees/g12a-probe/`에 있다.
- 공통 조건: Windows 11 Pro 10.0.26300, `.venv` Python, `QT_QPA_PLATFORM=offscreen`, `-p no:cacheprovider`, `-W error::ResourceWarning`, 고유 basetemp, `PYTHONDONTWRITEBYTECODE=1`.

## 2. 실행 증거

| 항목 | 명령·조건 | 결과 |
| --- | --- | --- |
| CI 동등 전체 회귀 | `python -m pytest -q -p no:cacheprovider -W error::ResourceWarning --cov=recoryn --cov-branch --cov-report=json:coverage.json --cov-fail-under=85` (basetemp `g12a-bt-full`) | **24,201 passed, 2 skipped, failures·errors 0**, 1,213.5초, 총 coverage 92.46%. skip 2건은 `tests/release/test_gpu_smoke.py:107`("this volume does not create 8.3 names")이다. basetemp를 8.3 이름이 없는 D: 볼륨에 둔 환경 탓이며, OS TEMP(C:) basetemp로 같은 파일을 다시 돌리면 103 passed·skip 0이다(G-P12 무관) |
| 묶음별 coverage | `python scripts/check_coverage.py coverage.json` | 전부 PASS(line/branch %): domain 99.18/97.89, capture 99.85/98.57, jobs 99.29/96.23, storage 95.92/91.20, security 98.11/94.43, content 98.96/99.01, all 93.82/88.47 |
| lint·format·type | `ruff check src tests scripts packaging` / `ruff format --check …` / `MYPYPATH=src python -m mypy src/recoryn scripts packaging` | All checks passed / 196 files already formatted / no issues in 92 source files |
| 신규 4파일 정상본 | 변이 하네스의 BASE 사본 | **1,753 passed, 41.91초**(60초 게이트 안) |
| 검토자 변이 6개 | 사본마다 하나만 적용, 신규 4파일 실행, import 출처 확인, 실패는 모두 AssertionError/`DID NOT RAISE`(수집·import 오류 0) | 검출 3(RM2 46·RM5 18·RM6 1) · 생존 3(RM1·RM3·RM4) |

## 3. 발견 사항

| ID | 심각도 | 상태 | 요약 |
| --- | --- | --- | --- |
| G12R-01 | S2 | OPEN | "근거 확인 불가"(basis 불일치·원 전사 hash 불일치) claim의 링크가 "재생 가능"으로 표시되고 Enter·Space·클릭에 재생·원 전사 표시를 한다. 계약 §3.2의 seek0 위반 |
| G12R-02 | S2 | OPEN | `claim_area`의 `problem is None` 가드를 어떤 시험도 보호하지 않는다(변이 RM1 생존). 이 한 줄이 회귀하면 변조·확인 불가 claim이 정상 "전사 참조" 영역에 표시된다 |
| G12R-03 | S2 | OPEN | 링크·후보 control에 키보드 초점이 있을 때 새 active 요약이 오면 열람을 교체하고 초점을 잃는다. 새 active 알림도 없다. 계약 §4.1 위반 |
| G12R-04 | S2 | OPEN | 후보 열람 중 poll이 선택 snapshot을 조용히 다시 잡는다. 늦은 결과가 active가 된 뒤의 명시 선택이 충돌·고지 없이 그 결과를 대체한다. 계약 §4.3의 "제시 때 캡처·조용한 대체 금지" 의도를 우회한다 |
| G12R-05 | S3 | OPEN | 저장 claim의 status·형식을 읽기 때 검증하지 않는다. 변조된 `supported`가 "상태 supported"·problem 없음·재생 가능으로 보인다. 형식 손상은 `_show_summary`가 잡지 않는 TypeError가 된다 |
| G12R-06 | S3 | OPEN | basis 미기록(legacy) claim이 "출처 기록 없음(원 전사에서 읽어 계산)"으로만 표시되고, 계산한 출처 값은 보이지 않는다(계약 §3.2) |
| G12R-07 | S3 | OPEN | 키보드·접근성 경미 4건: "이 요약 선택"만 Enter 미지원, 영역 개수가 browser 접근성 이름에 없음, 준비 취소와 Job 취소의 같은 문구, Announcer의 범위별 직전 1건 비교 |
| G12R-08 | S3 | OPEN | `view_generation`이 세션 변경 때만 증가한다. 같은 세션에서 다른 요약을 그려도 링크 key `claim:i:j@g`가 재사용된다(계약 §4.1·§4.2). 현재 동기 활성화 경로에서 실제 오동작은 재현되지 않았다 |
| G12R-09 | S3 | OPEN | 계약 규칙을 지키는 코드 중 시험이 없는 것: legacy 두 None key의 "현재 아님"(RM3 생존), autorepeat 무시(RM4 생존). 타 세션 대상 거부(RM6)는 의미 행 0, 보조 node 1개로만 검출 |

### G12R-01 (S2) 확인 불가 근거가 재생 가능으로 표시·실행됨

- 근거: `ui/content.py` `_claim_html`의 `playable`은 `found`·`provenance`·`timing_quality`만 본다. `view["problem"]`은 보지 않는다. `_claim_clicked`도 problem을 모른다. 그래서 `claim_evidence`가 `CONTENT_CLAIM_BASIS_MISMATCH`/`CONTENT_CLAIM_SOURCE_UNAVAILABLE`로 표시한 claim도 재생한다. `claim_evidence` docstring("never seekable")과 계약 §3.2("저장 basis 불일치·잘못된 값·source 읽기 실패는 '근거 확인 불가'/추가 검토, seek0")가 요구한 것과 다르다.
- 반례(`g12a-probe/probe_ui.py`, 결과 `probe_ui.out`). 실제 `ContentPanel`에서 링크에 초점을 두고 Enter를 눌렀다.
  - P1: 저장 basis를 transcript→user_assertion으로 변조(행 hash 재계산). 표시는 "출처 사용자 입력 · 원인: 근거 확인 불가 … 재생 가능"이다. seek 1회 `("mic", 1000, <원 전사>)`가 나간다.
  - P2: 원 전사 문장을 "CHANGED AFTER SUMMARY"로 변조. 요약의 `transcript_hash`와 맞지 않아 SOURCE_UNAVAILABLE이다. 그런데도 링크는 "재생 가능"이고 Enter가 seek 1회를 내며, 표에는 변조된 문장이 근거 행으로 선택된다.
  - Space와 마우스 클릭은 같은 `_claim_clicked` 경로다. P7에서 정상 claim의 `anchorClicked`가 seek를 내는 것을 확인했다. 확인 불가 claim에 Space·클릭을 따로 실행하지는 않았다.
- 영향과 심각도: claim은 "추가 검토 필요"에 있고 "근거 확인 불가"가 붙는다. 그래서 정상 근거로 게시된 것은 아니다. 전제는 행 hash를 다시 계산한 로컬 DB 변조다. 그러나 무결성 판정 결과가 탐색 경로에서 무시되어, 같은 줄에 "근거 확인 불가"와 "재생 가능"이 함께 뜨고 변조 문장을 재생 근거로 제시한다. 계약이 명시한 안전장치가 우회되므로 S2로 판정한다.
- 시험 공백: T04(`tests/unit/test_claim_basis.py` 271-281)는 problem 코드와 영역만, T10(289-301)은 problem 코드만 단언한다. seek0·링크 문구를 보는 UI 행이 없다.
- 권고: 링크 target에 problem을 함께 고정한다. problem이 있으면 "재생 불가·근거 확인 불가"로 표시하고, 활성화는 상태 안내만 하고 seek0으로 한다. T04·T10에 실제 키 입력 seek0 단언을 더한다.

### G12R-02 (S2) 확인 불가 claim을 검토 영역에 두는 가드가 무시험

- 검토자 변이 RM1: `claim_area`의 `problem is None`을 `True`로 바꿨다. 신규 4파일 **1,753 passed(생존)**.
- 의미: 저장 basis가 transcript이고 status가 uncertain/unreviewed이며 provider가 None/transcript인 claim에 problem이 붙는 경우가 있다. P2처럼 원 전사 hash가 맞지 않거나, 저장 basis는 transcript인데 계산값이 다른 경우다. 이 claim을 "추가 검토"로 보내는 것은 이 조건 하나뿐이다. 회귀하면 변조·확인 불가 근거가 "전사 참조 요약" 영역에 정상 claim처럼 표시되는데(S1 성격 결과), 2,506행 어느 것도 이를 잡지 못한다.
- 원인: T04는 basis를 user_assertion으로 바꿔 problem과 무관하게 검토 영역이 된다. T10과 보조 node는 `claim_area`를 부르지 않거나 provider 값만으로 검토 영역이 된다.
- 권고: T10(또는 보조 B형 표)에 "저장 transcript + uncertain + provider None + problem 존재 → review"를 손 oracle로 단언한다. UI에서 해당 claim이 `claims` browser에 없음을 확인한다.

### G12R-03 (S2) 초점 중 새 active가 열람을 덮고 알리지 않음

- 계약 §4.1: "browser/후보 control에 초점이 있거나 확인/편집 중이면 새 active 알림만 남기고 현재 열람을 유지한다."
- 구현: `_refresh_candidates`는 `_confirming`·편집 중일 때만 멈춘다. 열람하지 않고 active를 따라가는 중이면 `wanted = state["summary_id"]`로 새 요약을 바로 그린다. 초점 조건이 없고, `a11y.ANNOUNCEMENTS`에 "새 요약 도착" 종류도 없다.
- 반례 P5: Tab으로 `claim:0:0@1` 링크에 초점을 둔 뒤 다른 연결로 새 요약을 active로 만들고 poll(`load`)을 했다. 결과는 browser 초점은 유지, 화면은 SECOND로 교체(FIRST 사라짐), 초점 링크 ""(위치 상실), 알림 0이다.
- 영향: 화면 낭독기·키보드 사용자는 읽던 근거 위치를 잃고, 내용이 바뀐 사실을 듣지 못한다. 다음 Enter는 아무것도 하지 않아 잘못된 근거를 실행하지는 않는다. 접근성 경로의 명시 계약이 빠졌고 R 가족에는 초점 축이 없어 시험도 없다. S2로 판정한다.
- 권고: 초점이 두 browser나 후보 콤보에 있으면 표시 대상을 유지하고, polite "새 요약이 선택되었습니다" 알림을 1회 낸다. R에 초점 축 trace를 추가한다.

### G12R-04 (S2) 열람 중 snapshot의 조용한 재캡처

- 구현: `_refresh_candidates`는 poll마다 `self._candidate_snapshot = from_state(selection_state)`를 다시 잡는다. 열람 화면과 `candidate_info`는 그대로다(G12R-03과 같이 새 active 알림도 없다).
- 반례 P8(`g12a-probe/probe_rebase.py`, `probe_rebase.out`):
  1. BASE가 선택된 상태에서 BROWSED를 열람한다.
  2. 다른 연결의 늦은 결과 LATE가 CAS로 active가 된다.
  3. poll이 돈다. info는 그대로, 화면은 BROWSED, 알림 0이다.
  4. "이 요약 선택"을 누르고 Tab+Space로 Yes를 고른다.
  - 결과: BROWSED가 선택되고 LATE는 충돌 안내 없이 대체된다. 같은 변화가 확인 창이 열린 동안 일어나면 거부(C 가족)되는 것과 비대칭이다.
- 판단: 계약 §4.3은 snapshot을 "목록/버튼을 제시할 때" 잡고 사용자 기대값을 조용히 대체하지 말라고 한다. 열람 화면을 유지하면서 기대값만 새로 바꾸면 사용자는 LATE 도착을 모른 채 결정하게 된다. 최종 쓰기는 사용자가 확인한 그 후보이고 LATE는 후보로 남아 다시 고를 수 있다. 그래서 잘못된 게시(S1)는 아니고, CAS 보호 의도가 열람 구간에서 우회되는 S2로 판정한다. C 가족은 확인 창 안의 경쟁만 다룬다.
- 권고(택1): (가) 열람 중에는 제시 때 snapshot을 유지해 선택 시 충돌·재조회로 이끈다. (나) poll에서 active가 바뀌면 열람 정보에 "선택 요약이 바뀌었습니다"를 표시·알리고, 확인 창 문구에 현재 선택을 명시한다. C에 "확인 전 경쟁" trace를 추가한다.

### G12R-05 (S3) 저장 claim의 status·형식 미검증

- `claim_evidence`는 basis·provider_basis만 검사한다. 반례 P3(status를 `supported`로 변조, hash 재계산): problem None, 검토 영역, 표시 "상태 supported · … 원인: 출처·상태·어댑터 근거가 전사 참조 요건이 아님", 링크 재생 가능, Enter seek 1회. 계약 §4.1 셋째 행은 저장 손상 행을 "확인 불가로 구별"하라고 한다. Z 시험의 금지어 목록에도 `supported`가 있다.
- `segment_ids`가 정수이거나 `claims`가 null처럼 형식이 손상되면 `claim_evidence`에서 TypeError가 난다. `_show_summary`는 KeyError·StateConflict·ValidationError·AttributeError만 잡으므로, 예외가 poll 슬롯 밖으로 나간다. 반례 `probe_malformed.py`(`segment_ids=5`, hash 재계산): `ContentPanel.load`가 `TypeError: 'int' object is not iterable`를 던졌다. HEAD의 `_show_summary`도 같은 입력에서 TypeError이므로 G-P12가 새로 만든 회귀는 아니다. 다만 새 읽기 검증 경로가 이 경우를 "확인 불가"로 접을 기회를 놓쳤다.
- 전제가 같은 변조이고 정상 영역 승격은 없어 S3다. status 6값·형식 검사를 problem으로 접고 seek0에 합치기를 권고한다(G12R-01과 같은 수정).

### G12R-06 (S3) legacy basis 미기록 표시

P4(basis 필드 제거): 표시는 "출처 기록 없음(원 전사에서 읽어 계산)"이다. `computed_basis`(transcript)는 있지만 보여 주지 않는다. 계약 §3.2는 "현존 원 revision으로 읽기 계산한 출처임을 표시"라고 한다. 영역은 검토로 보수적이며 seek은 audio 근거라 계약 위반이 아니다. 계산값 표시를 권고한다.

### G12R-07 (S3) 키보드·접근성 경미 사항

1. `select_summary_button`에만 `a11y.activate_button`이 없다. 반례 P6: Enter로 확인 창 0회, Space로 1회. 다른 명시 버튼(취소·계속·탐색·동의·철회)은 Enter와 Space를 모두 받는다. 키보드로 선택 자체는 가능하다.
2. 두 영역의 개수는 별도 QLabel에만 있다. browser의 accessibleName·Description은 고정 문구다. Tab으로 들어간 낭독기 사용자는 개수를 듣지 못한다(계약 §4.1 "각 영역은 제목·개수·accessibleName/description").
3. `cancel`의 알림 문구는 준비 미접수 취소와 기존 Job 취소에서 같다(계약 §5.1 "구별"). 이후 tick의 Job 상태 알림으로 일부 구별된다.
4. `Announcer`는 범위별 직전 1건만 비교한다. 다른 알림(취소·충돌·준비 차단)이 끼어든 뒤 정책·reader 변화로 tick key만 바뀌면, 같은 Job 의미가 다시 알려질 수 있다(코드 판독).

### G12R-08 (S3) view_generation 갱신 범위

`load`는 세션이 바뀔 때만 `view_generation`을 올린다. 같은 세션에서 다른 후보·새 active를 그리면 `_claim_refs`는 비워지지만 key 형식 `claim:{claim}:{ref}@{gen}`은 같다. 그래서 늦게 전달된 옛 링크 신호가 새 요약의 같은 위치로 해석될 수 있는 구조다. 계약 §4.1("실제 표시 revision/세션이 바뀔 때만 view_generation을 갱신")·§4.2(target을 요약 revision까지 고정)와 다르다. 현재 활성화는 키 입력 시점의 문서에서 동기로 읽기 때문에 재현되는 오동작은 없었다. 표시 summary revision을 key에 넣거나 generation을 올리기를 권고한다.

### G12R-09 (S3) 생존 변이

- RM3: `summary_is_current`의 두 None 검사를 제거(두 None key = 현재). 1,753 passed. 계약 §4.3 "두 key가 None인 legacy도 … allow_outdated 확인을 요구"를 지키는 코드에 시험이 없다. D·C의 대상은 모두 key가 있다.
- RM4: `KeyActivation`의 `isAutoRepeat()` 무시를 제거. 1,753 passed. Enter·Space를 누르고 있으면 취소·철회·계속이 반복 실행될 수 있는 회귀를 못 잡는다.
- RM6: `select_summary_candidate`의 대상 세션 비교를 제거. 1 failed(`test_aux_other_session_targets_and_snapshots_are_refused`만). 계약 §4.3의 "타 세션 거부"가 2,506 의미 행 밖의 보조 node 하나에만 걸려 있다. 이 행을 D에 명명 행으로 넣거나, 계약에 보조 node 의존을 기록하기를 권고한다.
- 검출 확인: RM2(UI가 확인 뒤 snapshot을 다시 읽음) C 46건, RM5(작성자 M22 재실행: summary version 비교 제거) 18건(C 12·D 6, 작성자 보고와 같음).

## 4. 작성자 판단 요청에 대한 판정

### (1) `list_revisions`의 행별 세션 재확인 생략 — 타당(안전)

- 코드: `list_revisions`는 `root_mutex`(프로세스 내 RLock) 전 구간에서 시작 때 `_live`를 한 번 부른다. 행 SQL은 `WHERE session_id=?`라 모든 행이 같은 세션이므로, `checked_session` 분기의 "다른 세션" 경로는 이 호출에서 실행되지 않는다. Library의 삭제 의도 기록과 SQL 정리는 같은 `root_mutex`를 잡는다(`_progress_deletion`). 다른 프로세스는 `.writer.lock`(msvcrt `LK_NBLCK`) 때문에 같은 Library를 열 수 없다.
- 반례 탐색(`g12a-probe/probe_list_race.py`): 3개 스레드가 40개 요약 세션을 반복 조회하는 동안 reader를 잡은 채 `delete_session`(DELETE_PENDING)을 하고, 이어서 완료(DELETED_LOCAL)했다. 결과는 전체 목록 248회, 거부 1,406회(`Session has a deletion intent`), **부분 목록 0, 의도 게시 뒤 행 반환 0**이다. 두 번째 프로세스의 같은 root 열기는 `StateConflict Library already locked`였다.
- 행별 생략으로 줄어드는 비용은 `get_session` 1회당 약 0.3ms다(측정, 삭제 0~1000건에서 0.29~0.43ms). 반환값과 거부 경계는 같다.

### (2) 계약 해석

| 해석 | 판정 |
| --- | --- |
| Z를 UI 파일에 둠 | 타당. 두 영역 렌더링이 oracle 대상이며 ID 수 불변 |
| K "거부" = LIBRARY 동의 버튼 → 기본 No에서 Enter | 타당. 단 버튼 `destroyed` 행(소유 패널 파괴 뒤 다른 위젯에 키)은 거의 동어반복이다. 계약 §6.1의 "지연 명령 전달" fixture 취지에 맞추려면 파괴된 버튼의 늦은 `clicked` 신호 재전달이 더 강하다(S3 관찰, ID 없음) |
| E "편집 중" = 저장 실패로 보존된 미저장 편집, IME는 T15 | 타당 |
| F opener·fallback·지연 정의 | 타당. 동기 모달이라 "지연"이 늦은 poll이 되는 것도 맞다 |
| C "없음"·경쟁·"바뀐 세션" 정의 | 정의 자체는 타당하다. 다만 경쟁을 확인 창 안에서만 주입하므로, 확인 전(열람 중) 경쟁은 빠졌다 → G12R-04 |
| generation 없는 key를 현재 view로 해석(`test_ai_independent.py:356` 호환) | 타당. 렌더링된 anchor는 항상 `@gen`을 갖고 claim 문장은 escape되므로, 외부 입력이 이 경로로 들어오지 않는다(T07 확인) |
| P Job 상태(G-P07 결정표) | 타당. 부분=FAILED/TASK_FAILED+complete=false 후보, T25 확인 |

## 5. 중점 검토 항목별 판정

1. **잘못된 게시(S1 후보)**
   - 확인한 것(S1 0):
     - `select_summary_candidate`는 transaction 안에서 두 ID·두 version·요청 key(None 포함)를 모두 비교한다.
     - 다른 세션 대상·다른 세션 snapshot은 `CONTENT_SELECTION_SESSION_MISMATCH`로 거부된다. 변이 RM6(대상 세션 비교 제거)은 보조 node 1건으로만 검출됐다(G12R-09).
     - 부분 후보는 `CONTENT_SUMMARY_NOT_COMPLETE`이고, 삭제 의도 세션은 `_load`→`_live`→`get_session`에서 거부된다.
     - 이전 전사·설정 후보는 `allow_outdated`가 필요하며, UI는 확인 창 Yes 뒤에만 이 값을 넘긴다.
     - UI가 확인 뒤 snapshot을 다시 읽는 변이 RM2는 C 46건으로 검출됐다. 작성자 M22 재실행(RM5)은 18건으로 검출됐다.
     - 제품 코드의 요약 선택은 새 API만 쓴다(`select_summary` 호출 0).
     - provider_basis는 검토 영역으로 보내는 데만 쓰이고 정본을 덮지 않는다.
   - 남은 문제: 확인 불가 근거의 seek(G12R-01), 그 가드의 시험 공백(G12R-02), 열람 중 snapshot 재캡처(G12R-04).
2. **list_revisions 경쟁:** §4(1). 안전.
3. **접근성(실제 키 입력):**
   - 검증한 것: 시간 셀 Enter·Space, 링크 Tab·Shift+Tab·Enter·Space(작성자 trace), 확인 창 기본 No·Esc No(F 288행·실제 QMessageBox), 중복 청구 경고 문구(`_confirm_retry`·`_confirm_general`), 숨김·비활성 대상 소비, 정책 control 이름(실제 MainWindow).
   - 남은 문제: G12R-03·07. 실제 Narrator는 NOT_RUN(외부 게이트).
4. **대기 취소**
   - `cancel_button` → `cancelRequested` → 기존 `DesktopAI.cancel`(`_preparation_cancel`+`cancel_session` Task)이다. jobs·app의 새 API는 0이다(`app/ai.py` 차이는 Claim 변환 한 곳).
   - REMOTE_UNKNOWN 취소는 BLOCKED+cancel_requested로 남고 "취소 요청됨 · 원격 결과·비용 미확인"으로 알린다(T26). BLOCKED 계속·탐색 버튼은 G-P07 `show_ai_status`를 그대로 쓴다. 충돌은 없다.
5. **동의·비용 경계**
   - privacy 확인 창 4개는 같은 Yes|No·기본 No를 `a11y.confirm`으로 감쌌을 뿐이고, 반환 의미는 같다(`still_current`는 초점에만 쓰인다).
   - grant·철회·예산·시계·승계 호출 경로와 scope 처리는 그대로다. Enter 활성화 추가는 Space·클릭과 같은 기존 명령이다. 철회 알림은 영속화 뒤에만 나간다. 알림 sink는 grant·vault·ledger를 부르지 않는다.
   - 결론: 우회 0.
6. **범위 밖 관찰(Job 전이·journal)** — §6.
7. **시험 충분성**
   - 감사 시험이 실제 parametrize mark를 읽어 2,506 ID의 누락·중복·초과 0을 확인한다. B는 한 node에서 zip strict로 768행을 모두 돈다.
   - oracle은 손 표이며 제품 함수를 기대값에 쓰지 않는다.
   - 검토자 변이 6개 중 검출 3(RM2·RM5·RM6), 생존 3(RM1·RM3·RM4). 생존은 G12R-02·09로 보고했다.
   - 계약이 명시한 seek0(T04·T10), 초점 중 새 active(§4.1), 열람 중 경쟁(§4.3)은 대응 행이 없거나 단언이 약하다(G12R-01~04).
8. **전체 회귀·정적 검사** — §2.

## 6. 범위 밖 관찰 측정: 완료된 삭제와 Job 전이·목록 비용

- 대상 코드: `storage/library.py`·`jobs/__init__.py`. 이 tree와 HEAD 31bc88b의 차이는 0이다.
- 방법(`g12a-probe/journal_cost.py`·`journal_reads.py`): 새 Library에서 세션 N개를 만들고 각각 완료 삭제(DELETED_LOCAL)했다. 이어서 다른 세션에 묶인 Job으로 `claim`·`fail` 전이를 30회 하고, 그 중앙값을 냈다. 전체 회귀와 동시에 실행했으므로 절대값은 부하 영향을 받을 수 있다. 비례 관계는 분명하다.

| 완료 삭제 N | journal 파일 | Job `claim` 중앙값 | Job `fail` 중앙값 | `list_sessions` | `get_session` | `list_revisions` | N개 삭제 소요 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 0 | 1.26ms | 1.23ms | 0.29ms | 0.30ms | 0.40ms | — |
| 100 | 100 | 47.2ms | 46.3ms | 36.0ms | 0.29ms | 0.32ms | 2.9초 |
| 1000 | 1000 | 491.8ms | 486.8ms | 459.9ms | 0.43ms | 0.53ms | 242.8초 |

- 원인:
  - 완료 삭제의 journal 파일(`DELETE_REQUESTED`)이 남는다.
  - `Library.job_authority`는 전이마다 `_journal_prefetch`→`_read_journal`로 모든 파일을 열어 JSON을 검증한다. 그 뒤에야 cached index와 비교하므로 `reuse` 분기가 있어도 O(N) 읽기를 피하지 못한다.
  - `list_sessions`도 호출마다 전체를 검증한다.
  - 반면 `get_session`·ContentStore 읽기는 G-P15 index로 O(1)이다.
- 심각도 의견: **S2(성능, G-P15/G-P08 소유 후속)**. 데이터 손실이나 잘못된 게시는 없다. 그러나 다음과 같이 비용이 사용 기간에 따라 선형으로 커진다.
  - 완료 삭제 1건마다 세션 Job 전이 1회가 약 0.49ms 늘어난다. 요약 1건은 claim·reader·게시·종료로 여러 번 전이한다.
  - GUI 스레드의 세션 목록 갱신(`_render_sessions`→`list_sessions`)이 1000건에서 약 0.46초 멈춘다.
  - 삭제 자체도 건당 O(N)이라 누적 O(N²)이다.
  - G-P07 job_authority의 판정 의미는 맞다. journal 디렉터리 stamp가 그대로이면 검증된 index를 다시 쓰는 경로(이미 있는 `_index_current`의 listing 비교 같은 것)를 먼저 타게 하거나, 완료 tombstone의 journal 정리 정책을 정하는 것이 필요하다.
  - G-P12는 이 비용을 늘리지 않으며(오히려 `list_revisions` 행별 확인을 줄임), G-P12 푸시를 막는 항목이 아니다.

## 7. 반례·로그 위치

`build/review-trees/g12a-probe/`에 다음이 있다.

- 스크립트: `run_full.sh`, `probe_ui.py`, `probe_rebase.py`, `probe_malformed.py`, `probe_list_race.py`, `journal_cost.py`, `journal_reads.py`, `mutate.py`
- 출력: `full.log`, `checkcov.log`, `probe_ui.out`, `probe_rebase.out`, `probe_malformed.out`, `mutate.out`, `mut/report.json`, `mut/<변이>.log`

변이 사본은 실행 뒤 지웠고, 원본·변이 hash는 `mut/report.json`에 있다.

## 8. 미검증·한계

- 실제 Narrator 발화·Windows IME·고대비·확대 환경, 실제 음성·모델·네트워크·유료 호출은 하지 않았다.
- G12R-07(4)와 G12R-08의 늦은 신호 해석은 코드 판독이며 실행 trace는 없다.
- 변이는 검토자가 고른 6개(작성자 M22 재실행 포함)뿐이다. 작성자 28개 전체를 다시 실행하지 않았다.
- §6 측정은 전체 회귀와 동시에 실행해 부하가 섞였다. 반복 측정·다른 장치 측정은 없다.
- 유한 반례와 trace 밖의 GUI 이력은 증명하지 않는다.

## RECHECK 1 (G-P12 FIX1)

### R1.1 대상·방법

- 대상 tree `e47dcf73458d59b82081e6b73dbe9e18e019ac2a` = HEAD `8126c1f`(G-P08·GS-P02 포함) + G-P12 13파일이다.
- G-P12 변화(`git diff be581445 e47dcf73 -- <13파일>`)는 8파일 +743/−96이다.
- FIX1 변경 파일 LF SHA-256 앞 12자리: store `5c96cc0f7f3a`, ui/content `a486b6dcf481`, a11y `a2f63cf3a1b2`, ai_bridge `b5ba445f500f`, test_claim_basis `f73c72e2cfd9`, property `7f7a7f7a0fd9`, ui test `8bd2c129ef30`, 계약 `144fc42f496b`(전체 `144fc42f496ba758f52b48203936e38e6bb917acce7a2855696e6140b8ed7215`, 끝 §FIX1 확인).
- 실행 위치는 `build/review-trees/g12b`(`git archive e47dcf73 | tar -x`)다. PYTHONPATH는 사본 `src`로 고정했고, 반례·변이 사본의 import 출처가 사본임을 출력으로 확인했다.
- 반례는 `build/review-trees/g12b-probe/`에 있다.
  - 1차 스크립트 재적용: `probe_rebase.py`, `probe_malformed.py`, `probe_list_race.py`
  - 새 경로 확인: `probe_combo_intent.py`
  - 링크가 없어도 키 입력을 시도하는 새 판: `probe_fix1.py`(1차 P1~P6 포함, 출력 `probe_fix1.out`)
  - 측정: `journal_cost.py`, `journal_reads.py`
  - 변이: `mutate.py`(결과 `mut/report.json`)
- 전체 회귀의 basetemp는 OS TEMP(C:)에 두었다. 1차에서 D: 볼륨 때문에 생긴 8.3 skip 2건을 피하기 위해서다.

### R1.2 실행 증거

| 항목 | 결과 |
| --- | --- |
| CI 동등 전체 회귀(같은 명령, `-rs` 추가) | **24,567 passed, skip 0, failures·errors 0**, 1,839.2초(다른 검토의 전체 회귀와 동시 실행), 총 coverage 92.47% |
| `scripts/check_coverage.py` | 전부 PASS(line/branch %): domain 99.18/97.89, capture 99.85/98.57, jobs 99.29/96.23, storage 95.95/91.41, security 98.11/94.43, content 98.98/99.02, all 93.83/88.52 |
| ruff check / format --check / mypy | All checks passed / 198 files already formatted / no issues in 92 source files |
| 신규 4파일 정상본(변이 하네스 BASE) | **1,769 passed, 46.9초**(60초 게이트 안) |
| 검토자 변이 12개 재적용(1차 RM1~RM6 + FIX1 되돌림 FM1~FM6) | **12/12 검출.** 실패는 모두 AssertionError/`DID NOT RAISE`이고 수집·import 오류는 0이다. 세부는 아래 표 |

| 변이 | 결함 | 실패 node |
| --- | --- | --- |
| RM1 | `claim_area`의 problem 가드 제거 | X02 (1) |
| RM2 | 확인 뒤 snapshot 재읽기 | C 46 + X07 (47) |
| RM3 | 두 None key = 현재 | X14 (1) |
| RM4 | autorepeat 실행 | X15 (1) |
| RM5 | summary version 비교 제거(M22) | D·C 18 |
| RM6 | 대상 세션 비교 제거 | X16 + 보조 node (2) |
| FM1 | 확인 불가 claim에 링크 생성(G12R-01 되돌림) | X01~X04 (4) |
| FM2 | 초점 유지 제거(G12R-03) | X05·X06 (2) |
| FM3 | 열람 중 snapshot 재캡처(G12R-04) | X07 (1) |
| FM4 | 링크 key에서 렌더 세대 제거(G12R-08) | T08·X13 (2) |
| FM5 | 새 active 알림 제거 | X05·X06·X07 (3) |
| FM6 | 저장 status 검사 제거(G12R-05) | X03 (1) |

### R1.3 1차 발견 재확인

| ID | 판정 | 근거 |
| --- | --- | --- |
| G12R-01 (C00 S1 상향) | **RECHECKED** | P1(basis 변조)·P2(원 전사 변조)·P3(status `supported`), 추가로 basis `bogus`·중복 참조까지 확인했다. 해당 claim은 링크 0, "재생 가능" 0, 표시는 "근거 확인 불가 · 사유 · 재생·원문 이동 없음"뿐이다. Tab·Enter·Space와 옛 형식 key(`claim:0:0`, `claim:0:0@g`)의 seek 0, 표 행 선택 0이다. 되돌림 변이 FM1은 X01~X04에서 검출된다 |
| G12R-02 | RECHECKED | RM1이 X02에서 검출된다(1차에서는 생존) |
| G12R-03 | RECHECKED(잔여 → G12R-10) | P5: 초점 링크와 보던 요약 FIRST가 유지되고, polite "새 요약이 선택되었습니다 · 지금 보던 요약을 그대로 표시합니다" 1회다. 후보 콤보 초점도 같다(X06). FM2·FM5 검출 |
| G12R-04 | RECHECKED | P8: 늦은 결과 LATE가 대체되지 않는다. 열람 정보에 "열람을 시작한 뒤 선택 요약이 바뀌었습니다"가 붙고, polite 알림 뒤 Yes에서 assertive 충돌이 난다. FM3 검출 |
| G12R-05 | RECHECKED | 형식 손상 7종은 모두 load 예외 없이 "근거 확인 불가"·링크 0이다(claims null·dict·문자열 원소, segment_ids 정수·list 원소, 원 전사 segments 정수, provenance 누락). P3 표시에 `supported` 문자열 0. FM6 검출 |
| G12R-06 | RECHECKED | P4: "출처 기록 없음 · 원 전사에서 계산: 전사 참조". 원 전사가 정상이라 재생되는 것은 계약대로다 |
| G12R-07 | RECHECKED | (1) "이 요약 선택" Enter 1회·Space 1회로 확인 창이 열린다. (2) browser 접근성 이름에 개수가 들어간다(X10). (3) 취소 문구가 준비·기존 Job·둘 다를 구별한다(X11). (4) 세대 안 기억(X12) |
| G12R-08 | RECHECKED | key가 `@{generation}.{render}`다. FM4는 T08·X13에서 검출된다 |
| G12R-09 | RECHECKED | RM3·RM4·RM6이 X14·X15·X16에서 의미 행으로 검출된다 |

### R1.4 새 발견

| ID | 심각도 | 상태 | 요약 |
| --- | --- | --- | --- |
| G12R-10 | S3 | OPEN | 초점 때문에 유지한 요약의 안내가 사실과 어긋나고, 유지가 초점 이탈 뒤에도 풀리지 않는다. 삭제 의도 뒤의 선택 무안내·후보 전환 슬롯 예외도 남는다 |

G12R-10의 근거는 `probe_fix1.py` C·G1이다.

- **안내 불일치:** 보던 FIRST를 초점 때문에 유지하면, FIRST는 더는 선택 요약이 아니다(콤보 라벨 "후보"). 그런데 열람 정보 첫 문장은 "선택된 요약입니다. 이전 전사·설정 기준입니다."이고, 뒤에 "열람을 시작한 뒤 선택 요약이 바뀌었습니다"가 붙는다.
  - 원인: 유지 중에는 snapshot이 옛 값이라 `_show_candidate`가 FIRST를 snapshot의 선택으로 판정한다.
  - 같은 이유로 "이 요약 선택" 버튼도 비활성이다. FIRST를 다시 선택하려면 콤보에서 다른 후보로 갔다가 돌아와야 한다.
- **유지가 풀리지 않음:** 초점이 요약 영역을 떠난 뒤 새 active(THIRD)가 와도 FIRST가 계속 표시된다. 알림은 "지금 보던 요약을 그대로 표시합니다"로 정확하다. 계약 §4.1은 초점이 있는 동안만 유지하라고 하므로, 계약보다 보수적인 쪽이다.
- **조용한 무시:** 삭제 의도가 생긴 세션에서 "이 요약 선택"을 누르면 `store.summary`가 거부되고 아무 안내 없이 끝난다(G1). 쓰기는 0이다. 1차부터 있던 경로다.
- **슬롯 밖 예외(FIX1 신규 경로):** active가 바뀐 뒤(`_active_moved`) 세션에 삭제 의도가 생긴 상태에서 콤보로 다른 후보를 고르면, `_candidate_changed`가 try 밖에서 `selection_state`를 다시 읽는다. 그래서 `StateConflict: Session has a deletion intent`가 Qt 슬롯 밖으로 나간다(`probe_combo_intent.py`). 화면은 이전 후보에 머물고 쓰기는 0이다. 앱에 excepthook이 없어 stderr 출력으로 끝나며 종료되지는 않는다.
- 판정: 쓰기·게시 영향은 0이다. 확인 창과 CAS가 잘못된 선택을 막고, G1에서도 초점 링크 Enter는 seek 0·"근거 확인 불가"다. 그래서 S3로 둔다.
- 권고: 유지 중에는 "지금 보던 요약(선택 요약 아님)"으로 표시하고 선택 버튼을 활성화한다(선택 시 snapshot 충돌로 재확인). 초점이 떠나면 active 추종으로 돌아갈지 결정해 계약에 적는다. 거부 시 안내를 표시하고, `_candidate_changed`의 재캡처를 기존 try 안으로 옮긴다.

### R1.5 요청 판단

1. **기대값 변경 2건: 둘 다 타당하다.**
   - 변조된 `provider_basis`의 problem 코드 `BASIS_MISMATCH` → `RECORD_INVALID`
     - 원 전사와 비교한 불일치가 아니라 저장값 자체가 허용값 밖이므로 분류가 더 정확하다.
     - 계약 §3.2의 결과("확인 불가·seek0")는 같거나 더 엄격하다(refs도 비움).
     - §9의 코드는 "예시"이고 새 코드는 §FIX1에 기록돼 있다.
   - 알림 model "직전 1건" → "세대 안 기억"
     - 계약 §5.2의 "같은 poll 재알림 0·새 의미만 1회·옛 세대 0"에 1차보다 더 가깝다.
     - property 기대값도 손으로 쓴 집합 모델이고 제품 함수를 쓰지 않는다.
     - 다만 256개 FIFO 경계는 시험하지 않는다(생성 길이 최대 24). 현재 호출자는 같은 key를 다시 보내지 않는다. tick은 최신 Job의 새 version만, 취소·준비 차단은 증가 counter, 새 active는 version을 쓴다. 그래서 실영향은 없다고 본다.
2. **미룬 항목 "원 전사 행 hash까지 재계산된 변조 내용이 전사 보기에 그대로 보임": 설계상 한계로 판정한다(G12 OPEN 아님, 문서화 권고 S3 수준).**
   - 행 SHA-256은 우발 손상·부분 쓰기 검출용 자기 hash다. 같은 DB에 trigger를 지우고 쓸 수 있는 행위자는 hash도 다시 계산할 수 있다. 외부 기준점(키 있는 MAC·별도 보관 hash 사슬)이 없으면 막을 수 없다.
   - `docs/reviews/audio-recovery.md:140`도 SHA-256이 악의적 변조 방지가 아님을 이미 적고 있다.
   - G12 고유 위험(확인 불가 요약 근거를 통해 변조 전사를 근거 행으로 제시)은 FIX1에서 닫혔다. 요약 쪽은 `transcript_hash` 교차 확인으로 "확인 불가"가 된다.
   - 전사 보기·내보내기가 변조 검출을 약속하지 않도록 위협 모델 문서에 한 줄 남기기를 권고한다.
3. **새 경쟁**(`probe_fix1.py` G1~G3, `probe_list_race.py`)
   - G1(초점 유지 중 삭제 의도): 다음 poll의 `load`는 `active_transcript`에서 `StateConflict: Session has a deletion intent`를 던진다. 코드 판독상 1차 tree·HEAD와 같은 경로의 기존 동작이며 FIX1 회귀는 아니다. 초점 링크의 Enter는 seek 0, "근거 확인 불가 · 원 전사를 읽을 수 없어"다. 선택 시도는 쓰기 0(G12R-10의 조용한 무시). reader 종료 뒤 삭제는 DELETED_LOCAL로 완료된다.
   - G2(열람 snapshot 유지 중 다른 세션으로 이동했다 돌아옴): view generation이 올라가고 열람이 풀린다. snapshot은 새 세션 기준으로 다시 잡히며(현재 active LATE), 옛 snapshot이 섞이지 않는다. 세션 전환에서 거짓 "새 요약" 알림은 0이다.
   - G3(확인 창이 열린 동안 새 active와 poll): polite 알림 1회 뒤 Yes에서 assertive 충돌이 나고, 선택 쓰기는 0이다.
   - `list_revisions` 경쟁 재실행(GS-P02 포함 Library): 전체 217회, 거부 1,035회, 부분 목록 0, 의도 뒤 행 반환 0. 두 번째 프로세스는 잠금으로 거부된다.
   - 결론: 새 경쟁에서 잘못된 쓰기·게시·seek은 0이다.
4. **참고(§6 후속, GS-P02 이관 확인용):** HEAD 8126c1f에서 다시 쟀다.
   - Job `claim` 중앙값은 완료 삭제 0/100/300건에서 1.7/54.4/156.3ms, `list_sessions`는 1.0/36.7/105.1ms다. 여전히 선형이다.
   - GS-P02 push가 이 비용을 바꾸지 않았다. 전체 회귀와 동시에 측정했다.

### R1.6 결론

- G12R-01~09는 모두 RECHECKED다. 새 OPEN은 **S3 1건(G12R-10)**이다. S0·S1·S2 OPEN은 0이다.
- 미검증: 실제 Narrator·IME, 작성자 mutation 44개 전체 재실행(검토자 12개만 재실행), 256개 알림 기억 경계, K `destroyed` 버튼 행 강화(작성자가 미룸), 실제 DesktopAI 스레드 풀을 거치는 선택 경로.
