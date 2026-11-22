# G01-A 녹음·저장 gap 보고서 독립 교차 검토

작성일: 2026-11-22. 검토자: w5:p8 Codex / G01-B 교차 검토. 대상 작성자: w5:p7 Claude. 이 문서는 지정된 신규 리뷰 파일 하나만 작성한 결과이며, G01-A/G01-B 원 보고서·제품·시험·공용 문서·Git 인덱스는 수정하지 않았다.

**검토 결과: 이견 5건. S0 0건 / S1 1건 / S2 2건 / S3 2건.** S1은 G1A-89의 선택 version/설정 키 누락을 경미한 메타데이터 문제로 본 등급 및 V-I05 전체 완료 판정에 관한 이견이다. 독립 반례 두 행에서 실제 늦은 요약 선택 덮어쓰기를 확인했다. G1A-11의 복구 후 사용자 경로 단절 S1에는 동의한다.

## 입력 고정과 확인 범위

검토 시작 전 `docs/reviews/g01-gap-recording.md`의 bytes에서 CR을 제거해 SHA256을 계산했다. 결과는 배정한 **`e7f4655aeefc80a4f9a0164d1f7610cacb41b5932eb94331546a25d9c1b5bd6f`**와 같았다. 시험 실행 후에도 같은 해시였다. 기준 HEAD는 `3f4ee9f2d56b5a7a97e8dccb49399b5637babd4e`였고 감사 대상 `src`, 선택 시험의 unit/integration/property/e2e/ui 경로에 `git diff --name-only` 출력이 없었다. 다른 세션의 L08/G01 문서·packaging 변경은 판정 입력에 섞지 않았다.

| 확인 항목 | 직접 확인한 범위·결과 |
| --- | --- |
| 요구 행 및 집계 | **129행 전수**. 설계 요구 107행, 시나리오 22행. DONE_VERIFIED 71 / DONE_UNTESTED 6 / PARTIAL 37 / MISSING 6 / EXTERNAL_GATE 8 / DEFERRED 1로 원문 집계와 일치 |
| DONE_VERIFIED 근거 대조 | **71/71행**: 설계 요구 61행 및 상위 행을 참조하는 시나리오 10행의 코드 위치·시험 assertion 방향을 정적으로 대조. G1A-35와 V-I05는 아래 이견 때문에 요구 전체 완료로 수락하지 않음. 나머지 **69행은 각 행에 적은 한정 범위에서 동의** |
| test node 실재 | 원문 인용의 고유 **219개 함수명/파일 전수 존재 확인**. DONE_VERIFIED 행의 직접 인용은 **195개 고유 기본 node**. 매개변수 전개 전 함수 수이며 시험 실행 case 수와 다름 |
| 코드 위치 실재 | `app/ui/domain/capture/audio/storage/jobs/content/diagnostics` 및 `cli.py`의 **240개 인용 위치 표현 / 23파일**을 기계 대조. 파일·행 범위 오류 0. 한 표현의 복수 범위는 표현 하나로 셈. 위치 존재만으로 요구 충족으로 계산하지 않고 코드와 assertion 의미를 추가로 읽음 |
| 직접 선택 실행 | DONE 인용 중 property 12개 기본 node를 제외한 183개와 추가 SRT E2E 1개, 합계 **184개 기본 node → 402 PASS**. property 12개는 정적 oracle/시험 구조 대조만 했으며 재실행 PASS로 주장하지 않음 |
| 독립 반례 | TEMP 아래 새 시험 3행: **2 FAIL / 1 PASS**. FAIL 2행은 선택 version 변경 후 후보 보존을 기대한 assertion 실패. PASS 1행은 복구 원본 존재와 CLI export 차단이라는 G1A-11 현재 편차 확인 |

원문 6199 PASS와 JUnit hash는 **작성자 보고 이력**이다. 이번에 6199개를 재실행하거나 그 과거 JUnit을 열어 검증한 것으로 쓰지 않는다. 이번 402개는 그 시험들과 겹치므로 합산하지 않는다.

증거 루트(이하 `R`): `C:/Users/gangd/AppData/Local/Temp/recoryn-g01ar-miqmtpy2`. `R/report.json`, `R/done-nodes.json`, `R/selected-command.json`, `R/existing.log`, `R/existing.xml`, `R/test_cross_review.py`에 선택·실행·반례를 남겼다. TEMP의 장기 보존은 보장하지 않으므로 핵심 재현 절차도 아래에 적었다.

선택 실행은 `R/selected-command.json`의 node 184개를 인자로 한 다음 형태다.

```powershell
# cwd: D:/project/Recoryn
.venv/Scripts/python.exe -B -m pytest <selected-command.json의 test node 184개> -q -p no:cacheprovider --basetemp C:/Users/gangd/AppData/Local/Temp/recoryn-g01ar-miqmtpy2/pytest-existing --tb=short -W error::ResourceWarning --junitxml C:/Users/gangd/AppData/Local/Temp/recoryn-g01ar-miqmtpy2/existing.xml
```

`QT_QPA_PLATFORM=offscreen`, `HF_HUB_OFFLINE=1`, `HF_HUB_DISABLE_TELEMETRY=1`, `DO_NOT_TRACK=1`, `PYTHONDONTWRITEBYTECODE=1`을 지정했다. 실제 결과는 **402 passed in 26.62s / exit 0**이며 JUnit도 tests=402, failures=0, errors=0, skipped=0이었다. 실제 장치·모델·네트워크·vault 쓰기·패키지 설치는 실행하지 않았다. mutation·coverage·전체 회귀를 추가 실행하지 않았다.

## 이견

### G01AR-01 / 대상 G1A-89·V-I05·GF-15 / S1: 선택 version 누락은 실제 잘못된 게시로 이어짐

**원 판정:** G1A-89 PARTIAL/S3, GF-15의 필드 보강 묶음. V-I05는 DONE_VERIFIED.

**근거:** `src/recoryn/content/store.py:488`의 요약 선택 조건은 현재 전사 ID와 요약 ID를 기대 ID와 비교한다. `:659`의 `_select`는 selection version을 올리지만 게시 API는 이 version을 입력받거나 검사하지 않는다. `:653`, `:726`의 stale도 전사 ID 비교뿐이다. `src/recoryn/app/ai.py:427`의 실행 준비는 expected revision ID를 캡처하며 별도 expected selection version/현재 설정 키를 게시 transaction에 전달하지 않는다.

독립 반례의 기대값은 `architecture-v1.md`의 ‘메타데이터와 산출물 버전’ 절에 있는 **전사 선택 version·요약 선택 version·설정 키를 같은 게시 transaction에서 비교하고 불일치 시 후보로 보존**한다는 요구에서 정했다. 구현의 ID 비교식을 oracle로 복사하지 않았다.

TEMP node `test_cross_review.py::test_selection_version_change_must_keep_late_result_a_candidate`의 두 행:

1. 초기 T1/S1에서 오래된 요약 Job을 claim하고 기대 T1/S1을 고정한다.
2. summary 행은 S2를 만들고 S1로 다시 선택한다. transcript 행은 T2로 편집한 뒤 T1을 다시 선택한다. 각 선택 API가 성공했음을 assertion으로 확인한다.
3. 오래된 Job이 `publish_summary(..., expected_transcript=T1, expected_summary=S1)`를 호출한다.
4. **기대:** 선택 version이 바뀌었으므로 늦은 결과는 후보이고 현재 요약 S1 유지.
5. **실제:** 두 경우 모두 active summary가 늦은 결과의 새 ID로 바뀌어 `active_summary["revision_id"] == S1` assertion이 FAIL했다.

기존 `tests/unit/test_content.py:60`의 `test_summary_is_pinned_stale_and_late_summary_cannot_replace` 및 `:711`의 `test_atomic_summary_late_candidate`는 현재 포인터가 **다른 ID로 남은 경우**를 확인한다. 선택을 다른 것으로 옮겼다가 같은 ID로 되돌린 이력을 확인하지 않는다. 따라서 그 시험 PASS가 selection version 요구 전체를 검증하지 않는다.

재현 명령:

```powershell
.venv/Scripts/python.exe -B -m pytest C:/Users/gangd/AppData/Local/Temp/recoryn-g01ar-miqmtpy2/test_cross_review.py --rootdir C:/Users/gangd/AppData/Local/Temp/recoryn-g01ar-miqmtpy2 -q -p no:cacheprovider --import-mode=importlib --basetemp C:/Users/gangd/AppData/Local/Temp/recoryn-g01ar-miqmtpy2/pytest-counterexample --tb=short
```

실제 결과는 **2 failed, 1 passed in 0.54s**. PASS 하나는 아래 G1A-11 확인이며 두 FAIL과 합산한 전체 3행이다. helper LF SHA256: `1c7a248517ce2cd38255e33d6545a4946536f2ddc2b44fb4b4984975eb9362f7`.

**제안 판정:** G1A-89는 **PARTIAL/S1**, V-I05는 ‘기존 ID CAS 부분은 검증됨, selection version/설정 키 전체 계약은 미충족’인 **PARTIAL/S1**로 제한한다. G1A-27/87/88/121/123의 원자 transaction·revision 보존·기존 ID CAS 자체를 모두 실패로 되돌릴 필요는 없다. GF-15의 S3 metadata 보강과 분리해 별도 우선 단위로 올리고, G01-B의 **G01B-024/F-SUM02**와 한 문제로 통합한다.

품질 체계는 ‘잘못된 게시·잘못된 버전 덮어쓰기’를 고위험으로 보고 S1 예에 둔다. 단순 표시 필드 추가인 S3로 분류하기 어렵다. 모델·계정·실장비 없이 실제 공개 API에서 재현했다.

### G01AR-02 / 대상 G1A-73·V-F06·GF-13 / S3: 미디어 제거 실패·멱등 재삭제의 기존 직접 시험을 놓침

**원 판정:** G1A-73 DONE_UNTESTED/S3. `MEDIA_REMOVAL_FAILED` 문자열 검색 0건을 직접 시험 부재의 근거로 제시.

**근거:** `tests/unit/test_storage.py:305`의 **`test_delete_intent_before_files_and_no_resurrection`**은 실제 `storage.library.remove_tree`를 다음 동작으로 바꾼다.

```python
def locked(path):
    assert (tmp_path / "deletion-journal/s.json").exists()
    raise PermissionError("injected locked media")
```

그 뒤 `delete_session("s")["state"] == "DELETE_PENDING"`, 숨긴 목록, 복구 재채택 0을 확인한다. 정상 remove_tree를 복구한 다음 같은 `delete_session("s")`를 다시 호출해 **DELETED_LOCAL**을 확인한다. 이 흐름은 `src/recoryn/storage/library.py:591`의 제거 예외→대기와 `:559`의 기존 journal 재사용 경로를 직접 지난다. 해당 node는 원문 G1A-71에도 인용돼 있고 작성자 선택 파일에도 포함돼 있다. 이번 402개 실행에서도 PASS했다.

**실제 대조 결과:** 에러 코드 문자열 literal을 시험이 쓰지 않아도 해당 분기 동작은 확인한다. `rg -n MEDIA_REMOVAL_FAILED tests` 0건만으로 직접 시험이 없다고 결론내리면 안 된다.

**제안 판정:** ‘제거 예외 후 대기·완료 오표시 금지·동일 프로세스 재삭제’는 위 node를 붙여 **DONE_VERIFIED**로 정정한다. ‘제거 syscall 도중 process kill·재시작 후 완료’까지 한 행에 유지하려면 **PARTIAL**로 분할 사유를 적는다. 기존 시험이 실제 kill을 대체하지는 않는다. G1A-72의 **재시작 후 UI/목록 진입점 누락은 그대로 PARTIAL**이며, 이 이견으로 닫지 않는다. GF-13의 새 시험 목적은 이미 있는 PermissionError 재시도 시험을 중복 작성하기보다 재시작·목록·제거 중단 경계에 둔다.

### G01AR-03 / 대상 G1A-93·GF-18 / S3: 전사 반복 내보내기는 기존 E2E가 직접 확인

**원 판정:** G1A-93 DONE_UNTESTED/S3, ‘두 번 내보내 비교하는 node가 없다’.

**근거:** `tests/e2e/test_ai_workflow.py:107`의 **`test_record_transcribe_summary_edit_and_repeatable_srt`**에서 `:118`은 고정 revision의 첫 SRT를 저장하고, 요약·사용자 편집 후 `:134`에서 **동일 원 revision을 다시 내보내 첫 문자열과 동일함**을 확인한다. 원본 chunk hash 불변도 함께 확인한다. `src/recoryn/content/store.py:735`의 전사 직렬화 경로에 대한 직접 재생성 시험이며 이번 선택 실행에도 추가해 PASS했다.

**제안 판정:** ‘고정 전사 revision SRT 재생성’은 이 node와 함께 **DONE_VERIFIED**. ‘오디오 export를 서로 다른 새 폴더로 두 번 수행했을 때 변동 메타데이터를 제외한 콘텐츠 일치’는 현재 인용 시험이 같은 목적지 덮어쓰기 거부만 확인하므로 **DONE_UNTESTED 유지**. TXT/VTT/JSON 반복까지 검증됐다는 확대도 하지 않는다. 요구를 둘 이상으로 나누거나 한 행을 PARTIAL로 쓰고 검증/미검증 하위 범위를 명시한다. G01-B의 **G01B-065**가 인용한 같은 E2E와 정합시킨다.

### G01AR-04 / 대상 G1A-35 / S2: 정본의 사전 할당 버퍼 요구가 행에서 빠짐

**원 판정:** G1A-35 DONE_VERIFIED. 행 요구는 ‘복사·제한 enqueue·buffer 반환·상한’이며 구현 설명에는 ‘사전 할당은 아님’이라고 적음.

**설계 근거:** `docs/architecture-v1.md:112`의 capture critical path 문단은 **사전 할당 버퍼 복사**를 요구한다. 현재 행은 이 조건을 요구 칸에서 빼고 나머지만 완료 처리했다.

**구현/시험 대조:** `src/recoryn/capture/wasapi.py:194` 부근의 `ct.string_at(pointer, size)`는 패킷별 bytes를 새로 만든다. `:386` 부근의 SILENT `bytes(size)`도 패킷별 할당이다. `src/recoryn/capture/queue.py:43`은 이 bytes를 가진 PCMBlock을 bounded deque에 넣지만 버퍼 pool/사전 할당을 제공하지 않는다. 인용한 `tests/integration/test_native_independent.py::test_sdk_slots_64bit_positions_copy_before_release_and_thread_lifetime`은 포인터 해제 전 복사·같은 스레드 수명을 확인한다. 사전 할당이나 buffer 재사용을 검증하는 assertion은 아니다.

**제안 판정:** G1A-35에 사전 할당 조건을 복원해 **PARTIAL/S2**로 하거나, 기존 row의 제한 큐/복사/반환은 DONE_VERIFIED로 유지하고 **사전 할당·pool 수명 요구를 별도 PARTIAL 행**으로 추가한다. 성능 실패가 실제 장비에서 발생했다고 주장하는 것은 아니다. 유실·callback 지연 위험과 연결되는 구현 차이를 S3 표시 문제로 숨기지 말고, C00이 설계 조건을 유지/변경할 근거를 결정해야 한다. 실제 장비 지연은 W04 외부 게이트로 남긴다.

후속 제안: `capture/wasapi.py`의 버퍼 수명·pool/상한과 `domain.PCMBlock`의 불변 소유 계약을 함께 설계하고, fake native에서 pool 포화·소비 지연·release 순서·bytes 불변을 시험한다. 현재 공유 코드 수정 권한을 뜻하지 않는다.

### G01AR-05 / 대상 §2 범위 경계·G1A-68/69·GF-11 및 G01-B 연결 / S2: 복원/import의 공통 경계가 서로의 범위로 넘어가 완전한 행이 없음

**근거:** G01-A §2는 ‘자동 보존 삭제 정책, 백업 복원·import 시 grant/permit 비활성화, 비용 ledger’를 G01-B로 넘겼다. G1A-68/69는 migration/backup 생성 부재를 기록하고, GF-11은 ‘동의 비활성화는 G01-B’라고 다시 넘긴다. 반면 본인의 G01-B **G01B-048**은 ‘백업/import 전체는 G01-A의 저장 계약과 연결’이라고 적었다. 그 결과 다음 end-to-end 요구의 구현/부재·책임·직접 시험이 한 행으로 닫히지 않는다.

- `docs/architecture-v1.md:188`: 정상 백업 복원·프로젝트 import에서 새 실행 세대, 가져온 grant/permit 비활성화, 키 참조 재연결 전 사용 금지, 삭제 의도·비용 정산 이력 완전성 불명이면 복구/엄격 예산 전송 보류.

**현재 코드로 따라간 결과:** `src/recoryn/cli.py:33`의 parser에는 backup/restore/import/retention 동작이 없고, `src/recoryn/storage/library.py:44`의 공개 서비스에도 해당 workflow가 없다. `src/recoryn/security/consent.py:52`의 **새 ConsentStore 생성 시 grant 세대 무효화**는 이미 구현·시험된 하위 계약이지만 이것만으로 복원 대상 검증·키 재연결·ledger/tombstone 완전성 검사 workflow 전체를 완료로 볼 수 없다. 현재 제품이 실제 무동의 복원 전송을 했다는 반례는 아니며 **미구현 workflow의 추적 누락**이다.

**제안 판정:** C00 통합안에 ‘backup 생성’과 ‘restore/import 안전한 실행 재개’를 각각 추적 행으로 두고 현재 workflow 부재는 **MISSING**, 기존 consent/ledger/tombstone 보호는 연결된 DONE 부분으로 구분한다. 소유권은 storage/app/security/UI를 가로지르는 후속 manifest에서 확정한다. 자동 외부 재개 방지 자체의 보안 중요도는 S0 성격이지만, 이번 **보고서 경계 누락 이견은 S2**로 집계하며 실제 보안 사고나 기존 보호 코드 실패로 부풀리지 않는다. 본인의 G01-B 보고서에도 보완이 필요한 공통 누락임을 명시한다. 보존 정책은 이미 G01B-050/F-LIFE01이 PARTIAL로 추적하므로 신규 누락으로 중복 집계하지 않고, 활성 writer 제외의 storage 책임만 통합 manifest에 명시한다.

## 동의하는 판정과 남은 해석

다음 DONE_VERIFIED 설계 요구 행 **60개**는 인용한 구체 계약 범위에서 동의한다. 모든 ID를 적어 확인 분모를 고정한다.

```text
G1A-01,02,03,04,05,
10,12,14,16,17,19,21,23,25,27,28,29,
30,32,34,38,40,41,43,45,
52,55,57,59,60,61,65,67,70,71,74,75,
85,87,88,90,92,100,110,111,112,
120,121,122,123,124,125,126,127,128,
130,131,132,133,134
```

시나리오 DONE 10개 중 **9개**(V-U01/U02/U03/U04/U05, V-I01/I04, V-F02/F04)는 행이 명시한 축소된 자동 시험 범위와 기존 다른 gap 행의 제한을 함께 읽는 조건으로 동의한다. 예를 들어 V-F02는 실제 kill 4개 관측 경계와 나머지 손상/예외 주입이며 모든 syscall 내부 kill을 실행했다는 뜻이 아니다. V-U03의 version/lease는 JobStore 계약 범위이며 미구현 ExecutionPlan/만료 lease 전부 완료가 아니다. V-I05는 G01AR-01 때문에 제외한다.

인용 시험이 여러 요구를 한 번에 완전히 입증한다는 해석은 하지 않는다. 다음 구현·미검증 분리는 원문에 동의한다.

- **G1A-11 S1:** 독립 `test_cross_review.py::test_recovered_media_is_present_but_cli_cannot_export`에서 abort한 writer의 유효 prefix를 recover해 원본 chunk 1개·INTERRUPTED를 확인한 뒤, 동일 세션 CLI export가 exit 1이고 완료 export.json이 없음을 직접 확인했다(PASS). 복구 bytes 보존과 사용자가 확정/내보내기/전사할 경로 부재를 구분한 S1 판정은 타당하다. 단, `app/desktop.py:216`의 close는 INTERRUPTED에서도 source close와 writer join을 수행한다. ‘INTERRUPTED를 처리하지 않는다’는 표현은 **정상 확정으로 전이하지 않는다**로 좁혀야 정확하다.
- **G1A-15 PARTIAL/S2:** `jobs/__init__.py:699` 이후는 REMOTE_UNKNOWN 외 known 오류를 BACKOFF/FAILED로 분류하고 CONSENT/AUTH/RESOURCE/BUDGET/CAPABILITY BLOCKED를 생성하지 않는다. `resume` 지원과 오류 발생 시 해당 blocked state에 들어가는 기능은 다르다. 현재 수동 새 작업이라는 우회가 있어 S2는 수용 가능하다. B의 오류 DTO/다음 action gap과 연결하되 상태 매핑의 원인을 별도 추적한다.
- **G1A-72 PARTIAL/S2:** 현재 삭제 intent를 숨기는 `storage/library.py:203`과 MainWindow의 메모리 pending 사전만으로 재시작 목록을 복원할 수 없다는 분석에 동의한다. B의 G01B-067은 같은 원인이며 서로 다른 두 기능 누락으로 중복 계산하지 않는다. 이번 검토에서는 원본·게시·송신 차단은 유지되고 같은 ID로 삭제 재호출 가능한 우회가 있다는 근거로 **A의 S2를 수용**한다. 본인의 B 보고서 S1은 C00 통합 시 S2로 정합시키는 것을 권한다. A 보고서에 대한 새 S1 이견으로 중복 집계하지 않는다.
- **G1A-36/39/42/44/51/62/63/64/68/69:** unknown tail·clock domain/UTC·정렬 제품 연결·gap 범위·동기화 폴더·복구 발견/명시 고아 채택·손상 DB inventory·migration/backup workflow의 부재/부분 구현 근거는 코드에서 따라갈 수 있었다. 실장비 미검증으로 이 개발 gap들을 숨기지 않은 구분에 동의한다.
- **G1A-76/135·V-W01~W04·V-Q·G1A-66:** 원본 VoiceLocal 소스, 실제 장치/성능, 전원 장애는 자동 시험의 코드·합성 통과로 대체할 수 없다. 현재 외부 게이트 유지에 동의한다.
- **G1A-17/26/53:** REMOTE_UNKNOWN의 취소 의도 보존, 단일 coordinator 기반 reader 복구, content DB 저장은 최신 제품 계약과 기존 구조를 함께 읽고 문서 정합을 C00 결정으로 남기는 것이 적절하다. `complete_with`의 외부 I/O 금지는 `jobs/__init__.py:553`에 명시된 **신뢰된 SQL-only callback 계약**이며 Python callback 전체를 OS sandbox로 강제했다는 검증으로 확대하지 않는다.

## G01-B와의 공통 경계 통합 제안

| 공통 요구 | G01-A | G01-B | 통합 시 주의 |
| --- | --- | --- | --- |
| 녹음·AI 분리 및 제어 ACK | G1A-01/04/19/21 | G01B-053/054/055 | 캡처 저장 지속·AI 프로세스·Qt lane 증거는 상호 보완. 같은 ‘R01 완료’를 단순 합산하지 않음 |
| 선택 version·늦은 요약 | G1A-89·V-I05 | G01B-024 | **G01AR-01의 실제 2 FAIL을 공통 원 반례로 연결**, S1 별도 단위 |
| 복구 후 사용 가능성 | G1A-11/24/62 | G01B-066 | 기존 세션 확정/attach라는 core 동작과 gap/후보 검토 UI를 분리하되 의존성 명시 |
| 재시작 삭제 대기 | G1A-72/73 | G01B-067 | storage pending 조회 API + UI 복원은 하나의 사용자 흐름. 제거 실패 기본 시험은 이미 존재 |
| 진단·support bundle | G1A-100/101/102/103 | G01B-052/070 | 모듈 가림 검증과 제품 기록/미리보기 연결은 다른 판정. core 미연결을 UI만의 문제로 축소하지 않음 |
| 보존·복원/import | §2·G1A-68/69·GF-11 | G01B-048/050 | 복원/import는 **G01AR-05의 상호 참조 공백 보완**. 보존은 기존 B 행을 유지하며 storage/app/security/UI 책임을 manifest에 명시 |
| 고정 revision export | G1A-93/111 | G01B-065 | 전사 SRT 반복 시험은 공유. 오디오 반복/요약 refs export는 별도 남은 요구 |
| 파생 오디오 | G1A-42/134 | G01B-006/055/056/063 | 일반 선형 resampler, L-P02 STT 16kHz 변환, drift 보정, 경계 overlap, 근거 재생 mapping을 서로 같은 완료 근거로 쓰지 않음 |

## 인계

대상 원문 해시를 바꾸지 않고 검토를 마쳤다. 71개 DONE 행의 실재·주장 범위를 전수 대조했으나 원문의 6199개 전부를 독립 재실행한 결과는 아니다. 시험 근거 누락 2건은 직접 기존 assertion을 찾았고, 선택 version S1은 TEMP 반례 2행에서 재현했다. 이견 **G01AR-01~05**는 작성자와 C00의 반영/수락 전까지 OPEN이다. 원 보고서의 판정 개수는 수정하지 않았으며 요구 분할과 집계는 C00 통합안에서 다시 산출해야 한다.

## G01-C 통합안 확인

2026-11-23, 확인자 w5:p8 Codex. 대상은 `docs/implementation/v1-gap-plan.md`, LF SHA256 **`9a75643e440b9c7d74c748a3c5da2eb016b24410f9acf9c34f3f9df80dbb9cf6`**다. 본인 G01-B(`1e3cd7c1…3e0b`)와 이 문서의 최초 교차 검토(`cbe2b493…fbac`), 상대 G01-B 교차 검토의 G01BR-01~23 및 통합안 확인 절을 함께 대조했다. 상대 리뷰의 현재 hash는 확인 절 추가로 `cc9557e4…082c`이며 통합안 입력 표의 `ff7ebe94…ac26`은 최초 제출 이력으로 해석했다. 기존 검토 내용은 고치지 않고 이 절만 추가한다.

### 반영 및 등급 결정 확인

- 선택 version 누락을 **S1 하나로 통합**하고 G-P03에 두 ABA 원 반례를 수락 기준으로 넣은 것은 G01AR-01/G01B-024를 정확히 반영한다. 설정 키의 **게시 시 현재값 비교**는 G-P03의 S1 계약이며, 설정 키의 단순 표시·OUTDATED 표시 보강을 S3로 남기는 것과 구분해야 한다. V-I05의 전체 DONE 판정은 구현 전까지 PARTIAL로 읽어야 한다.
- 복구 후 사용자 확정/내보내기 경로 S1, 사전 할당 하위 요구 PARTIAL/S2, 기존 삭제 실패·전사 SRT 반복 시험의 해당 하위 요구 DONE_VERIFIED 정정, 복원/import workflow 추가는 G01AR-01~05와 정합한다. backup 생성 자체는 이미 G1A-69가 있으므로 새 요구와 중복 계수하지 않는다는 상대 검토의 보강에도 동의한다.
- 재시작 삭제 대기는 본인의 교차 검토에서 우회 API를 근거로 S2를 수용했으나, **C00이 사용자에게 보이지 않는 삭제 잔여 원본을 핵심 기능 실패로 보아 S1로 정한 것**을 수용한다. G-P05로 한 원인·한 사용자 흐름을 배정하고 G-P04 뒤 직렬화한 것은 적절하다. 이전의 S2 제안과 달라진 결정을 이 절에서 명시하며 추가 S1 이견으로 남기지 않는다.
- G01BR-02~10의 S2 조정에 동의한다. 현재 관측된 근거만으로 원본 손상·자동 supported 승격·과소 비용 계상·잘못된 게시가 발생했다고 확장할 수 없다. GPU 정책 불이행·고정 자원 추정·basis 표시·접근성·완전한 계획 레코드 등은 남겨 둔 개발 요구이며 완료로 닫은 결정이 아니다. 비용 상한 S1은 별도 G-P06에 유지됐다.
- G1A-15는 설계대로 수정하고, 단일 coordinator 수명·DB content 저장·REMOTE_UNKNOWN 취소 의도 표현을 현 제품 계약과 정합시키는 GD-P01 결정, 에코 완화의 명시적 DEFERRED 결정은 C00 범위 결정으로 수용한다. 장치 ready와 첫 수락 PCM을 구별하는 REC 표시는 현재 구현 사실이 아닌 G-P07의 추가 구현/시험 조건이라는 상대 G01CR-01도 맞다.

### G01B-040의 S0→S1(최우선) 조정

**등급과 최우선 순서는 수용한다.** 원 감사의 S0는 요구가 깨질 때의 영향을 표시한 것이며 실제 무동의 송신 사고를 관측했다는 뜻이 아니었다. 현재 `security/consent.py:152`, `:191`과 `gateway.py:132`의 provider·정확한 endpoint·data type·execution generation·TTL·철회 검사는 존재한다. 같은 grant가 다른 세션에도 적용되는 계약 누락은 상대 P1 반례로 재현됐고, 기능·세션 범위·policy version 부재는 그대로다. 이 상태를 **권한 모델의 S1 계약 위반으로 분리하고 가장 먼저 구현**한다는 판단은 타당하다. 실제 권한 우회가 더 좁은 동의 안내를 넘어선 전송으로 이어지는 증거가 생기면 S0 재평가를 막는 결정으로 해석해서는 안 된다.

다만 다음 두 근거 보강 이견이 있다. 결정권은 C00에게 있고 S0·S1 이견은 없다.

| ID | 대상 | 심각도 | 근거·제안 |
| --- | --- | --- | --- |
| G01CC-B01 | 동의 범위 등급 결정의 ‘UI가 보여준 동의 범위를 넘어 보내지 않는다’ | S2 | `ui/privacy.py:49` 이하에는 수신 endpoint·데이터 종류 선택이 있지만 세션 한정/전체 세션·만료·정책 version을 고지한 scope 선택은 없다. 범위를 보여주지 않았다는 사실이 사용자의 전체 세션 동의를 입증하지는 않는다. **‘현 구현이 검사하는 provider/endpoint/data type 및 실행 세대/TTL/철회 경계는 유지되지만, 세션 범위의 사용자 의도는 UI에서 명시되지 않았다’**로 근거를 좁히는 것이 정확하다. G02는 바로 이 불명확성을 기본 세션 범위와 명시적 전체 선택으로 해결해야 한다. S1 조정 자체에 반대하는 이견은 아니다 |
| G01CC-B02 | 수동 모델 허용 결정과 S04의 관계 | S2 | 수동 로컬 디렉터리 허용(B13)을 유지하는 결정은 수용한다. 그러나 현재 bytes를 자체 해시해 표시하는 것은 신뢰된 digest·출처·license와 대조한 로드 검증과 다르다. **GD-P01/G-P13에서 수동 모델의 신뢰 책임·명시 확인·검증 상태 표시와 S04의 적용/예외를 정해야 한다.** ‘사용자 지정 모델’과 해시 표시만으로 기존 S04 전체가 완료됐다고 기록해서는 안 된다. 이는 수동 모델을 무조건 차단하자는 제안이 아니라, 설계 조건 변경의 근거·수락 기준 누락을 보강하자는 이견이다 |

### 인계

G01-C 확인 이견은 **2건(S0 0 / S1 0 / S2 2 / S3 0)**이다. 이미 상대 확인 절이 지적한 G-P07 표시 구현 범위, G-P03 설정 키의 영속 비교/schema 방식, 원 등급 칸과 backup 중복 표기는 별도 새 건수로 중복 집계하지 않았다. 본인의 두 보고에서 나온 기능 gap은 통합안 후속 단위 또는 ‘이후’에 연결돼 있으며, 아직 구현되지 않은 판정을 완료로 바꾸는 근거로 이 확인을 쓰지 않는다. 이어지는 G02 작업은 경우의 수·계약 문서만 작성하고 C00 승인 전 제품 코드는 수정하지 않는다.
