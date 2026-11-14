# P12 — domain/jobs 독립 코드 리뷰

작성일: 2026-11-14. 검토자: P02 오디오 담당. 대상 작성자: P01. 상태: **REVIEW_READY / P12-01(S2) OPEN / 원 작성자 수정 후 재확인 대기**. 검토한 범위에서 S0/S1은 발견·재현하지 않았다. 이 결과는 전체 구현 승인 또는 자신의 capture 코드 승인이 아니다.

## 범위와 snapshot

[구현 계약](../implementation/p0-contracts.md)을 기준으로 `src/recoryn/domain/__init__.py`, `src/recoryn/jobs/__init__.py`, `tests/unit/test_domain.py`, `tests/unit/test_jobs.py`, `tests/integration/test_job_publication.py`를 실제로 읽었다. 공유 DB 확인을 위해 storage의 schema/transaction 부분과 `test_app_service.py`의 AI 실패 격리 시험도 읽었다. 작성 중인 storage의 임시 lint/type 문제는 지적 대상에서 제외했다. 다른 담당의 소스·테스트는 수정하지 않았다.

| 파일 | 검토 시 SHA-256 |
| --- | --- |
| `src/recoryn/domain/__init__.py` | `D39B8F48E4F834656CBB204593C021F50CAD4281E40EC7F96F9DAA278CEC6968` |
| `src/recoryn/jobs/__init__.py` | `91DCCB66C77121348CAD46A3B1FF2A69377A4D510268869D33122AB99C329903` |
| `tests/unit/test_domain.py` | `4EF44EAADCEFC1C7FE3C53B58BF8C3CC66ACF7BA49E111DF670FEE38A4A59CAF` |
| `tests/unit/test_jobs.py` | `48AD7C094E6164A38C95ABA3C2D56750D41CFB27AA427FA9DB7DCE16FFEDA9A6` |
| `tests/integration/test_job_publication.py` | `C747B19A8B541E79A8F684529B3D2FEFE5F04D1292B3185FC7E3D08BA027C6D7` |
| `docs/implementation/p0-contracts.md` | `C3EE72F9291C5DDDB583A3ED5E58FA00DD63909FDDBC465CE1799E97404B0168` |

## 확인한 동작과 독립 oracle

- 취소/완료: `jobs` 156~166행의 `BEGIN IMMEDIATE`와 connection별 RLock 안에서 상태·fence 검사, attempt/job 갱신 및 event 삽입이 함께 commit된다. 267~328행은 취소가 먼저면 기존 토큰의 완료를 거부하고, 완료가 먼저면 취소가 성공 결과를 바꾸지 않는다. 독립 observer connection으로 직접 SQL 행을 읽어 두 순서를 확인했다.
- attempt/fence: `claim`은 새 UUID/attempt_no/fence를 만들고, `fail`은 이전 fence를 회수한다. 독립 실행에서 3회 attempt의 fence는 `[1,3,5]`, 모두 FAILED 이력이 남고 어떤 이전 토큰으로도 완료할 수 없었다. 두 connection의 동시 claim은 한 명만 성공했고 attempts 행 수는 1이었다.
- 공유 SQLite: 실제 `Library`와 두 `JobStore`를 함께 열어 `user_version=1`, sessions의 CREATED 행을 보존한 채 jobs를 변경했다. jobs는 `events`, storage는 `storage_events`를 사용하므로 현재 schema 이름 충돌은 없었다. 실제 연결은 별도이며 결과 판정은 Python 반환값만이 아니라 SQL 값도 대조했다.
- 부정 입력: fence의 `True/0/-1/1.0/"1"/2**63`를 별도 호출해 모두 ValidationError, Job 상태 불변을 확인했다. domain의 ASCII ID·불변 payload·frame 길이·bool 배제·fragment·nullable clock·스키마 guard와 합법 Session 전이도 코드를 확인하고 관련 실행 시험을 재실행했다.
- 정상 중복 완료와 취소는 terminal 결과를 보존한다. 다만 생성 요청의 dedup 경로에는 아래 재현 가능한 idempotency 공백이 있다.

## P12-01 · S2 · dedup으로 반환한 명시 job_id 요청의 재전달이 새 Job을 만듦

- 위치: `src/recoryn/jobs/__init__.py` 202~228행 `create`, 특히 217~222행. `tests/unit/test_jobs.py::test_cancel_queued_then_manual_new_job`은 다른 명시 ID의 dedup 반환까지만 확인하며 그 요청을 취소 후 재전달하지 않는다.
- 반례: `create("STT","input","original")` 후 `create("STT","input","request-id")`는 `original`을 반환한다. `original`을 취소하고 DB를 다시 연 뒤 **동일한 kind/input/job_id**를 재호출하면 이번에는 `request-id`라는 QUEUED Job이 생긴다. 초기 요청과 재전달 응답이 다르고 기존 취소 뒤 새 작업이 추가된다.
- 원인: 실제 jobs 행이 있는 명시 ID만 208~216행에서 바인딩된다. dedup으로 반환한 요청 ID는 저장하지 않으므로, 원 Job이 CANCELLED/FAILED로 바뀌어 dedup 대상에서 빠지면 이전 요청을 새로운 생성으로 취급한다. 활성 입력 dedup은 영속 명령 idempotency를 대신하지 못한다.
- 영향: 명시 job_id를 생성 재시도의 안정된 키로 사용하는 caller는 응답 유실·재시작 후 의도하지 않은 새 QUEUED 작업을 만들 수 있다. 이번 P0에는 실제 AI/원격 실행이 없어 S2로 분류한다. 새로 만든 Job을 사용자가 명시적으로 요청한 재실행과 구별할 계약이 필요하다.
- 해결 조건: 원 작성자는 dedup된 생성 요청의 identity→결과 바인딩/receipt를 보존해 동일 요청의 재전달이 원 Job을 반환하고 다른 입력의 ID 재사용은 충돌하게 해야 한다. terminal 이후 명시적 새 실행에는 새 identity를 사용한다. `job_id`를 명령 키로 보장하지 않는 의도라면 D00이 정본 API에서 그 한계를 명시하고 별도 생성 명령 idempotency 경계를 정해야 한다. 리뷰어가 공용 API를 임의 변경하지 않는다.
- 수락 oracle: 서로 다른 두 connection과 재시작에서 같은 생성 요청을 반복한 결과 ID 및 부작용 수가 안정적이어야 한다. 원 Job 취소/실패 뒤 기존 요청 재전달은 새 Job을 만들지 않고, 명시적 새 요청만 새 Job을 만들며 같은 요청 ID+다른 payload는 충돌한다. 원 작성자 수정 후 같은 P12 검토자가 재확인한다.

최소 재현(PowerShell, 저장소 루트에서 실행):

```powershell
$probeRoot = Join-Path $env:TEMP ('recoryn-p12-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $probeRoot | Out-Null
@'
import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd() / 'src'))
from recoryn.jobs import JobStore
p = Path(sys.argv[1]) / 'library.sqlite'
with JobStore(p) as s:
    s.create('STT', 'input', 'original')
    print('first:', s.create('STT', 'input', 'request-id').job_id)
    s.cancel('original')
with JobStore(p) as s:
    j = s.create('STT', 'input', 'request-id')
    print('replay:', j.job_id, j.state.value)
'@ | & ./.venv/Scripts/python.exe - $probeRoot
```

독립 실행의 실제 결과: `first=original`, `replay=request-id`, SQL rows=`[(original,CANCELLED),(request-id,QUEUED)]`. 안정된 생성 요청 재전달 oracle에는 FAIL이다.

## 실행 명령과 결과

환경: Windows, Python 3.13.1, `.venv/Scripts/python.exe`. 기존 공유 pytest temp 폴더나 다른 폴더의 ACL을 변경하지 않았다.

```powershell
$p12BaseTemp = Join-Path $env:TEMP ('recoryn-p12-pytest-' + [guid]::NewGuid().ToString('N'))
$env:PYTHONDONTWRITEBYTECODE = '1'
& ./.venv/Scripts/python.exe -m pytest -q tests/unit/test_domain.py tests/unit/test_jobs.py tests/integration/test_job_publication.py --basetemp $p12BaseTemp -p no:cacheprovider
```

결과: **156 passed in 0.65s**. 이는 이번 세션이 직접 실행한 결과이며 작성자의 자체 통과 보고를 복사하지 않았다. 위 S2 반례는 기존 시험에 없는 독립 검증이다.

추가 독립 probe 실행 명령:

```powershell
& ./.venv/Scripts/python.exe "$env:TEMP/recoryn-p12-probe-ae5cb438d6fa4a328be2ef0252ab0785/probe.py" "$env:TEMP/recoryn-p12-probe-ae5cb438d6fa4a328be2ef0252ab0785"
```

probe SHA-256=`CEE3159F5C8D6B09AD28FB36D0C6F0237FEAAE85C0C11D75E19D4E312D730065`. 위 명령은 실행 당시 새 UUID 디렉터리에서 최초 실행했으며 재실행 시에는 새 임시 경로로 script와 DB를 분리해야 한다. 결과는 아래와 같다.

| 독립 점검 | 실제 결과 |
| --- | --- |
| 취소 commit 우선 | `CANCEL_REQUESTED/NULL/cancel_requested=1`; 완료 거부 PASS |
| 완료 commit 우선 | `SUCCEEDED/artifact/cancel_requested=0`; 뒤 취소가 결과 유지 PASS |
| 3 attempt와 stale fence | `[1,3,5]`, 3 FAILED 이력, 이전 완료 모두 거부 PASS |
| 실제 Library와 공유 DB | sessions/PRAGMA 보존 PASS |
| 두 connection 동시 claim | 승자 1명, attempt 행 1개 PASS |
| 6종 fence 부정 입력 | 모두 거부·상태 불변 PASS |
| dedup된 생성 요청 취소 후 재전달 | 새 QUEUED Job 생성, P12-01 FAIL |
| 동일 fail 응답 재전달 | 첫 응답 BACKOFF, 재전달 StateConflict, 상태는 불변. API의 실패 명령 receipt 보장은 현재 없다는 관측이며 별도 S1로 집계하지 않음 |

## 남은 제한과 인계

실제 worker/model/원격 전송, 물리 전원 장애, 전체 회귀와 실장비는 이 리뷰로 검증하지 않았다. `recover_abandoned()`의 sole restarting coordinator 전제는 호출자가 보장해야 하며 실제 프로세스 생존 추정 기능은 없다. 실제 Library와의 공존은 검사했지만 작성 중인 storage 전체를 승인하지 않는다.

원 작성자가 P12-01을 수정하거나 D00이 API 보장 경계를 명시하면 동일 검토자가 수정 diff·새 digest·위 재전달 oracle을 재확인한다. 현재 집계는 **S0 0 / S1 0 / S2 1 OPEN**이며 이번 쓰기는 이 리뷰 파일 하나와 명시적으로 허용된 OS 임시 재현 산출물뿐이다. 리뷰 대상 소스·테스트·Git은 변경하지 않았다.

## P12-01 수정 후 독립 재확인 — 2026-11-14

현재 판정: **P12-01(S2) RECHECKED — 수정된 생성 요청의 영속 바인딩을 코드·독립 실행으로 확인**. 최초 OPEN 기록·반례·실패 결과·당시 hash는 위에 보존한다. 이 후단이 아래 digest에 대한 최신 P12 판정이며 전체 source snapshot의 최종 통합 승인은 별도다.

| 재확인 파일 | SHA-256 |
| --- | --- |
| `src/recoryn/jobs/__init__.py` | `FAD44ADCC9558DA2268112D1F29D4D351B1BE8A2D5B812DBCCB9735C6BBCD39F` |
| `src/recoryn/domain/__init__.py` | `D39B8F48E4F834656CBB204593C021F50CAD4281E40EC7F96F9DAA278CEC6968` |
| `tests/unit/test_jobs.py` | `B64A9868E410B672406245A5BAFA6B866C5D6083687DC3532C95A0E23BF38FD0` |
| `tests/integration/test_job_publication.py` | `C747B19A8B541E79A8F684529B3D2FEFE5F04D1292B3185FC7E3D08BA027C6D7` |

### 수정 코드와 원 해결 조건 대조

- `jobs` 88~89행은 명시적 create job_id를 영속 request identity로 정의한다. 134~139행의 `job_create_receipts`는 request ID primary key와 기존 Job FK를 갖고 실제 기존 Job ID를 backfill한다. Library의 user_version은 변경하지 않는다.
- `create` 210~246행은 동일한 `BEGIN IMMEDIATE` transaction 안에서 receipt를 먼저 조회한다. 기존 바인딩의 kind/input_key가 다르면 StateConflict이며, 동일하면 원 Job이 CANCELLED/FAILED여도 그 Job으로 재해석한다. 활성 입력 dedup으로 다른 Job을 반환할 때도 receipt를 INSERT한 뒤 commit한다.
- 새 Job 생성도 Job 행·receipt·event를 같은 transaction에서 기록한다. receipt 삽입이 실패하면 수락으로 반환하지 않고 rollback한다. 원 작성자가 추가한 terminal/restart, 상충 payload 경쟁, receipt 실패, concrete ID backfill 회귀의 실제 코드를 읽었다.
- 원 수락 oracle인 결과 ID 안정성·부작용 수·새 요청과 재전달의 구별·다른 payload 충돌을 직접 확인했다. `fail()` 호출 자체의 응답 receipt 보장까지 추가됐다고 확대 해석하지 않는다.

### 독립 실행 명령과 실제 결과

먼저 **최초 리뷰 때 사용한 probe.py를 수정 없이 복사**해 새 UUID 임시폴더에서 다시 실행했다. 복사본 SHA-256도 최초 값 `CEE3159F5C8D6B09AD28FB36D0C6F0237FEAAE85C0C11D75E19D4E312D730065`와 일치했다.

```powershell
$env:PYTHONDONTWRITEBYTECODE = '1'
& ./.venv/Scripts/python.exe "$env:TEMP/recoryn-p12-recheck-dd0482f8a38f40fea343de4efc698ee5/probe.py" "$env:TEMP/recoryn-p12-recheck-dd0482f8a38f40fea343de4efc698ee5"
```

원 반례 결과는 이제 **PASS**: `first=original`, `replay=original`, SQL rows=`[(original,CANCELLED)]`. 재시작 후 새 QUEUED Job이 생성되지 않았다. 동일 probe의 취소/완료 양 순서, `[1,3,5]` attempt fence, 동시 claim 한 명, fence 부정 입력 검사도 모두 PASS였다.

추가로 작성자 시험과 별개의 `receipt_probe.py`를 OS 임시폴더에 작성해 두 connection→원 Job 실패→재시작→동일 요청 replay→새 명시 run→옛 요청 replay 순서와 독립 SQL oracle을 실행했다. 다른 kind/input_key의 ID 재사용 두 건은 모두 StateConflict였다. 별도 DB에서는 receipt INSERT에 trigger 오류를 주입해 dedup 경로와 새 Job 생성 경로를 각각 확인했다.

```powershell
& ./.venv/Scripts/python.exe "$env:TEMP/recoryn-p12-receipts-671c21b8366b4a12b62938cf61834a36/receipt_probe.py" "$env:TEMP/recoryn-p12-receipts-671c21b8366b4a12b62938cf61834a36"
```

추가 probe SHA-256=`5E981F8B09747D2B66E6E72A5D3E11020138C89A27B593F159359261B4601172`. 결과: 실패한 원 Job replay PASS, 새 요청 분리 PASS, 다른 payload 충돌 2건 PASS, 두 receipt 오류 경로 rollback PASS. 오류 전후 `(jobs,receipts,events)`는 `(1,1,1)`로 같았고, 오류 trigger 제거 뒤 새 생성 성공 때만 `(2,2,2)`가 됐다. 원 Job의 receipt는 새 활성 Job이 있어도 원 Job을 계속 가리켰다. 위 probe는 fresh DB를 전제로 하므로 재실행에는 새 UUID 임시 경로가 필요하다.

관련 시험도 직접 재실행했다.

```powershell
$p12RecheckTemp = Join-Path $env:TEMP ('recoryn-p12-recheck-pytest-' + [guid]::NewGuid().ToString('N'))
$env:PYTHONDONTWRITEBYTECODE = '1'
& ./.venv/Scripts/python.exe -m pytest -q tests/unit/test_domain.py tests/unit/test_jobs.py tests/integration/test_job_publication.py --basetemp $p12RecheckTemp -p no:cacheprovider
```

실제 결과: **161 passed in 0.77s**, Windows/Python 3.13.1. 고유 임시폴더를 사용했으며 다른 폴더의 ACL을 변경하지 않았다. 원 작성자의 자체 통과 보고와 별개로 이 세션이 실행한 결과다.

### 남은 범위와 인계

- P12 원 발견 사항 **1/1건 RECHECKED**, 재확인한 digest의 P12 범위에서 미해결 S0/S1/S2 **0건**. 원 작성자 외의 동일 검토자가 수정 후 반례를 재실행했다. 최종 통합 snapshot이 바뀌면 영향 diff를 대조해야 한다.
- 이번 결과는 수정 후 저장한 생성 receipt에 대한 보장이다. 구 구현에서 애초에 저장하지 않았던 alias 이력을 복원하는 이행은 검증 범위에 포함하지 않는다. worker 실제 실행·원격 호출·전원 장애·전체 회귀·G3/G4는 이 결과로 통과하지 않는다.
- 기존 리뷰 본문을 그대로 보존하고 이 후단만 추가했다. 대상 소스·테스트·공용 계약·Git은 수정하지 않았다. CLOSED 집계와 최종 통합은 D00이 수행한다.
