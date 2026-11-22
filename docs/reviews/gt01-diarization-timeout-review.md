# GT01 화자 구분 timeout 시험 독립 검토

- 작성일: 2026-11-23
- 검토자: w5:p7 Claude(GT01 독립 검토). 작성자: C00(GT-P01).
- 대상: 작업 트리의 `tests/unit/test_diarization.py` 변경(`git diff -- tests/unit/test_diarization.py`, 5삽입/2삭제). 기준 commit은 `0305306e256a39562244f63e42a627fc2e79bde9`다.
- 제품 코드, 시험, 설정, Git 인덱스는 수정하지 않았다. 저장소에서는 이 문서 하나만 새로 썼다. 반례 probe는 OS TEMP에만 두었다.

**판정: 원인 분석·계약 유지·assertion 보존은 동의한다. 다만 GT-P01의 목표인 "자식 시작 시간 분리"는 달성하지 못했다. OPEN 3건(S2 1건, S3 2건), S0·S1 0건.**
- 1.5초 → 6초 변경은 여유를 늘린 완화다. 자식 시작이 약 6초를 넘으면 같은 모양으로 다시 실패한다.
- 제품 변경 없이 시험 쪽에서 시간 제한을 자식 시작 뒤부터 세는 방법이 있고, 재현으로 확인했다(GT01R-01).
- 자기 작성 결과가 아니므로 이 문서가 최종 승인은 아니다. C00 수정 뒤 같은 probe로 재확인이 필요하다.

## 1. 검토 입력과 실행

| 파일 | SHA256(CR 제거·LF 기준) | 비고 |
| --- | --- | --- |
| `tests/unit/test_diarization.py`(작업 트리) | `fb10e9897e3a12cac7045290694b9274db8dfacc3a3c37568d268e15883626fb` | 검토 대상 |
| `tests/unit/test_diarization.py`(HEAD) | `466fff083ebfd8ebd7bd12cc642d6fa851eb516de614f7489835a4433e6912f0` | 변경 전 |
| `src/recoryn/diarization/process.py` | `9060d883f8c6dc35c2b5b2eb0b4135d4d6d684b2bdfc7fbc1d078e209c75a0cc` | HEAD와 같다(`git diff --quiet HEAD -- src/recoryn/diarization`) |

- 아래 행 번호는 위 파일 기준이다.
- 환경: Windows 11, `.venv` CPython 3.13.1, logical CPU 32개. `-p no:cacheprovider`, 실행마다 다른 OS TEMP basetemp, `-W error::ResourceWarning`을 썼다.
- 실제 모델·장치·네트워크·설치는 쓰지 않았다. fake 자식은 `_hung_child`의 사본이다.

### 1.1 작업 트리 시험

`test_owned_hung_child_ack_before_return` 3개 모드: **3 passed in 7.07s**.

| 모드 | 소요 시간 |
| --- | ---: |
| timeout | 6.07s |
| close | 0.37s |
| cancel | 0.36s |

### 1.2 probe

- probe 파일: `C:\Users\gangd\AppData\Local\Temp\claude\e47d15555ed7cfa9\d9354f5a-75d0-44dc-8069-db32589569d1\scratchpad\gt01probe\test_gt01_probe.py`, LF sha256 `636e14915e85a2cf1ff48e978dbdbffd0db91390b6f0b36221ee3149b7f6c73d`
- 기록: `C:\Users\gangd\AppData\Local\Temp\recoryn-gt01-c8c2c17fd8e8420386242da7ccf9c58d.jsonl`, LF sha256 `57db5b5102c999172b5fe5fceee875532e24084512a25c54614db9c8da4dd825`
- 구성:
  - 원 시험 timeout 모드의 본문과 assertion을 그대로 옮겼다.
  - 바꾼 것은 세 가지뿐이다: 시간 제한과 시작 표시 대기, 자식 시작 지연 D(시작 표시 전에 `time.sleep(D)`), 시험 쪽 시계 shim 사용 여부.
  - 시작 표시 대기 루프에서 실패할 때 worker 생존 여부와 결과 코드를 기록하게 했다. 원 시험에는 이 기록이 없다(GT01R-02).
- 결과: **3 failed, 16 passed in 41.67s.** 실패 3건은 아래 표의 예상 실패 행이다.
- TEMP는 영구 보존을 보장하지 않는다. 그래서 주요 수치를 아래에 함께 적었다.

**유휴 상태 자식 시작 시간**(cancel 모드, `diarize()` 진입부터 시작 표시 관측까지, 10회): 0.270~0.314초, 중앙값 약 0.277초.

**결정적 지연 주입 결과**(시각은 `diarize()` 진입 기준 초):

| 변형 | 시간 제한 / 표시 대기 | D=0 | D=2 | D=7 |
| --- | --- | --- | --- | --- |
| 원본(HEAD) | 1.5 / 8 | PASS, 표시 0.28, 반환 1.57 | **FAIL**: 표시 전 반환 1.59, worker 종료, 결과 TIMEOUT | **FAIL**: 같은 모양, 반환 1.59 |
| GT-P01(작업 트리) | 6 / 15 | PASS, 반환 6.08 | PASS, 표시 2.29, 반환 6.08 | **FAIL**: 표시 전 반환 6.08, worker 종료, 결과 TIMEOUT |
| 대안: 표시 시각부터 세는 시계 | 1.5 / 15 | PASS, 반환 1.87 | PASS, 표시 2.28, 반환 3.87 | **PASS**: 표시 7.29, 반환 8.89 |

## 2. 관점별 판정

### (a) 원인 분석이 코드와 맞는가 — 맞다(기전은 재현으로 확인, 실제 실패 줄은 미확인)

provider deadline은 `process.py:148`에서 `diarize()` 진입 직후 계산된다. 그 뒤에 오는 단계가 모두 같은 예산을 쓴다.
- 잠금 획득(`:151-153`)
- capability 확인(`:159`)
- 음성 snapshot hash(`:167`)
- spawn(`:169-183`)과 보호 장치 부착(`:184`)
- 자식 Python 기동과 시험 모듈 import(unpickle 때 `_hung_child`가 있는 시험 모듈을 import한다)

시간이 다 되면 다음 순서로 진행된다.
1. `_check`(`:185` gate 열기 직전, 또는 `:188` 대기 루프)가 `TIMEOUT`을 낸다.
2. `:205-206`이 TIMEOUT 결과를 만든다.
3. `finally`의 `_reap`(`:209-214`, `:228-232`)가 자식을 terminate한다.
4. worker thread가 끝난다.
5. 시험의 시작 표시 대기 루프(`test_diarization.py:243-245`)가 `worker.is_alive()`에서 실패한다.

probe의 D=2(원본)와 D=7(GT-P01) 행이 정확히 이 모양(worker 종료, 결과 TIMEOUT, 시작 표시 없음)으로 실패했다. 따라서 C00의 원인 분석은 코드와 일치한다.

확인하지 못한 것:
- L-P08 1판 실패의 traceback이나 assertion 줄은 [라이선스 결과](../implementation/license-results.md) `:615-618`에 없다. OS TEMP의 JUnit 파일에서도 찾지 못했다. 그래서 실제 실패가 이 줄이었는지는 직접 확인하지 못했다. 기록과 재현이 같은 기전을 가리킨다는 데까지만 말할 수 있다.
- 유휴 시작 시간은 약 0.28초이므로, 1.5초에서 실패하려면 시작이 5배 넘게 느려져야 한다. 이 저장소의 pytest는 단일 프로세스로 돈다(`pyproject.toml:49`, xdist 없음). 32 logical CPU에서 전체 시험 두 개의 CPU 경쟁만으로는 이 지연을 설명하기 어렵다. 프로세스 생성·디스크·실시간 검사 같은 다른 요인일 수 있으나 기록이 없어 확인하지 못했다. 그래서 6초가 실제 부하에서 충분한지 수치로 말할 수 없다(GT01R-01).

### (b) 6초가 원래 계약을 여전히 시험하는가 — 그렇다

- 원래 계약: 협조적 취소를 무시하는 자식이 매달린 동안 timeout이 발동하고, provider가 반환 전에 자식 종료를 확인한다.
- `_hung_child`는 시작 표시를 쓴 뒤 30초 동안 취소 이벤트를 보지 않는다(`:146-147`). 6초 timeout은 그 30초 안에서 발동한다. 유휴 기준으로 자식은 timeout 전 약 5.7초 동안 매달려 있다.
- 시작 표시 전에 timeout이 나면 시험은 통과하지 않고 실패한다. probe의 GT-P01 D=7 행이 이를 보여 준다. 그래서 거짓 통과 경로가 늘지 않는다.
- `worker.join(8)`(`:255`)의 여유는 다음과 같다. join은 시작 표시 시각 t_s에 시작하고, worker는 약 6+reap초에 반환한다. 여유는 t_s+2−reap초, 유휴 측정으로 약 2.2초다. reap가 최악(`join(2)` 소진)이어도 t_s−0.05초로 양수다.

### (c) assertion이 약해졌는가 — 아니다

diff는 상수 두 개(`:226`의 1.5→6.0, `:242`의 8→15)와 주석 3줄뿐이다. 판정 assertion(`:256-259`)은 바이트가 같다.
- worker 종료
- 오류 없음
- `TIMEOUT`/`CANCELLED` 코드
- 미완료
- `_process is None`
- 자식 handle 신호 상태

### (d) 더 나은 대안 — 있다(제품 변경 없음)

- 시험이 `process` 모듈의 `time` 참조를 시계 shim으로 바꾸면 된다. shim은 시작 표시가 생기기 전까지 0을 돌려주고, 그 뒤로는 표시 시각부터 흐른 시간을 돌려준다.
- 그러면 provider deadline이 자식이 매달린 시점부터 세어진다. 자식 시작 시간은 시험의 시작 표시 대기(15초)만 쓰게 된다.
- probe에서 1.5초 제한으로도 D=7까지 통과했다. 제안 코드와 주의점은 GT01R-01에 있다.

### (e) 부하 재현 — CPU 부하 대신 결정적 지연 주입으로 대체

- 인위적 CPU 부하는 걸지 않았다. 같은 장비에서 C00과 Codex 세션이 시험을 돌리고 있을 수 있고, 부하를 걸면 그 세션들의 시간 의존 시험이 바로 이 유형으로 흔들릴 수 있다.
- 대신 자식 시작 지연을 결정적으로 주입해 1.5초판과 6초판을 비교했다(§1.2 표).
- 이 방식은 자식 쪽 지연만 흉내 낸다. 부모 쪽 지연(spawn 호출 자체가 느린 경우)은 재현하지 않았다. 다만 두 지연 모두 같은 deadline 예산을 쓰므로 결론은 같다.

## 3. 발견 사항

### GT01R-01 / S2 / OPEN: 여유만 늘렸고 자식 시작 시간을 분리하지 않음

근거:
- [통합 계획](../implementation/v1-gap-plan.md) `:82`는 GT-P01의 목표를 "시간 제한에서 자식 시작 시간을 분리"로 정했다.
- 작업 트리 변경은 같은 예산을 1.5초에서 6초로 늘렸을 뿐이다(`test_diarization.py:226`).
- 자식 시작이 약 6초를 넘으면 원래와 같은 모양으로 실패한다(§1.2 GT-P01 D=7).
- 유휴 시작 시간(0.28초) 대비 여유는 약 5배에서 약 21배로 커졌다. 하지만 실제 부하에서 시작이 얼마나 늦어지는지 측정치가 없다(§2(a)). 그래서 6초가 충분하다는 근거는 없다.

영향: 전체 검증 게이트의 간헐 실패가 줄지만 남는다. 재실행으로 우회할 수 있는 품질 문제여서 S2로 분류했다. 실패를 재실행 성공으로 지우지 않는다는 원칙(license-results `:618`)을 지키려면 원인을 닫는 편이 낫다.

제안 수정(시험만, 제품 변경 없음):

```python
import types


class _MarkerClock:
    """Start the provider deadline only once the hung child is proven running."""

    def __init__(self, marker: Path) -> None:
        self.marker, self.origin = marker, None

    def monotonic(self) -> float:
        if self.origin is None:
            if not self.marker.exists():
                return 0.0
            self.origin = time.monotonic()
        return time.monotonic() - self.origin


# test_owned_hung_child_ack_before_return 안, provider 생성 전
clock = _MarkerClock(request.audio_path.with_suffix(".started"))
monkeypatch.setattr(process, "time", types.SimpleNamespace(monotonic=clock.monotonic))
...
assert clock.origin is not None  # the provider really consulted the test clock
```

주의점:
1. `process.py`가 모듈 전역 `time`을 통해 `time.monotonic`을 쓴다는 구현 세부(`:11`, `:148`, `:219`)에 기댄다. 나중에 `from time import monotonic`으로 바뀌면 shim이 조용히 무력해진다. 마지막 `clock.origin` assertion은 그 경우 시험을 크게 실패시키려고 넣었다.
2. 시작 표시 전에는 provider가 timeout하지 않는다. 그래서 시작 상한은 시험의 표시 대기(15초)와 `worker.is_alive()` 검사가 맡는다. 자식이 표시 전에 죽으면 provider는 `DIARIZATION_PROCESS_FAILED`(`:203-204`)로 돌아오므로 매달리지 않는다.
3. "provider deadline은 자식 시작까지 포함한다"는 제품 성질은 이 시험이 원래부터 검사하지 않는다. 필요하면 시작 표시를 쓰지 않는 자식으로 TIMEOUT을 확인하는 별도 행을 둔다.
4. 이 방식이면 timeout 값을 1.5초로 되돌려 시험 시간을 줄일 수 있다. 측정한 timeout 모드 시간은 6.07초인데, shim과 1.5초 조합은 probe에서 표시+1.6초였다. cancel·close 모드에도 같은 shim을 적용하면 세 모드의 시작 상한이 모두 15초로 같아진다.

6초판을 임시 완화로 수용한다면 GT-P01을 "분리 완료"로 표시하지 말아야 한다. [품질 체계](../quality-system.md) `:112`에 따라 보류 이유·담당·기한과 C00 수용을 기록한다.

### GT01R-02 / S3 / OPEN: 시작 표시 대기 실패가 원인을 남기지 않음

근거: `test_diarization.py:244`의 `assert worker.is_alive() and time.monotonic() < deadline`은 메시지가 없다. 실패하면 다음을 구별할 수 없다.
- provider가 먼저 반환했는가, 아니면 표시 대기 시간이 다 됐는가
- provider가 반환했다면 결과 코드가 무엇인가

L-P08 1판 실패의 원인이 추론으로 남은 직접 이유다(§2(a)). probe는 같은 지점에서 `alive=False result=TIMEOUT`을 남겨 원인을 바로 보여 줬다.

제안 수정:

```python
assert worker.is_alive(), f"provider returned before the child marker: {results or errors}"
assert time.monotonic() < deadline, "child marker did not appear within the start-up bound"
```

### GT01R-03 / S3 / OPEN: 표시 대기 8→15초의 실제 효과가 주석·배정표와 다름

근거: 주석(`:223-225`)은 6초만 설명한다. 배정표 `assignments.md:30`은 "시작 표시 대기 8→15초"라고 적었다. 실제 효과는 모드마다 다르다.
- **timeout 모드:** provider가 약 6초에 먼저 반환한다. 그래서 `is_alive` 검사가 15초보다 먼저 실패하며, 15초 상한은 작동하지 않는다. 변경 전 8초도 1.5초 때문에 작동하지 않았다.
- **cancel·close 모드:** 시간 제한 10초(`:226`)가 먼저 다 된다. 그래서 실제 시작 상한은 8초에서 15초가 아니라 **8초에서 10초**로 바뀌었다.

제안 수정: 주석에 위 관계를 적는다. 또는 표시 대기를 `config.timeout_seconds`에서 유도해 의미를 드러낸다. GT01R-01의 shim을 세 모드에 모두 적용하면 15초가 세 모드의 실제 시작 상한이 되어 이 불일치가 사라진다.

## 4. OPEN 아닌 관찰

1. **좁은 경합:** gate를 연 뒤 시작 표시를 쓰기 전에 timeout이 나는 경우가 있다. 이때 자식이 terminate 전 `join(0.05)` 창(`:229`) 안에 표시를 쓰면, 시험은 표시를 보고 진행한다. 그 뒤 `provider._process`가 이미 None이면 `child.pid`에서 AttributeError로 실패한다. 아직 정리 중이면 통과할 수도 있다. 창이 수십 ms라 드물다. GT01R-01의 shim을 쓰면 표시 전 timeout이 없으므로 사라진다.
2. **6초가 다루지 않는 다른 부하 실패:** 극단적 부하에서 `terminate` 뒤 `join(2)`가 끝나지 않을 수 있다. 그러면 `_reap`가 `finally`에서 `DIARIZATION_ACK_PENDING`을 올리고(`:233-235`), 그 예외가 반환값을 대신해 `errors`에 들어간다. 이는 제품의 올바른 보수적 동작이며 세 모드 공통이다. 이번 변경의 범위가 아니다.
3. **시험 시간:** timeout 모드가 약 1.6초에서 약 6.1초로 늘었다. 전체 시험마다 약 4.5초가 더 든다.

## 5. 확인하지 않은 것

- L-P08 1판 실패의 실제 traceback(기록·TEMP JUnit 모두 없음)
- 실제 CPU·디스크 부하에서의 시작 시간 분포와 1.5초판·6초판 비교(§2(e) 사유)
- 다른 장비·다른 Python 빌드에서의 시작 시간
- 제안한 shim을 실제 시험 파일에 적용한 결과(시험 파일 수정 금지). probe의 "대안" 행이 같은 코드를 시험 사본에서 실행한 결과다.

## RECHECK(2026-11-23, GT-P01 2판)

- 검토자는 같다(w5:p7 Claude). 위 1판 검토 내용은 그대로 두고 이 절만 덧붙였다. 1판 검토 문서의 LF sha256은 `157c57bdd58c08f134fd300d5eca52893f7408f9e3340151ccfcaf3ade874267`이다.
- 대상: 작업 트리 `tests/unit/test_diarization.py` 2판. LF sha256은 `f9c6ff8c3ab9d1fa0ea01a60cd0d0f59aad676e0d181de274420a5d3a0ed0e0d`이고, HEAD 대비 diff는 +73/−3줄이다. `src/recoryn/diarization/process.py`는 그대로다(`9060d883…a0cc`, HEAD와 같다).
- 아래 행 번호는 2판 파일 기준이다.

**판정: GT01R-01·02·03 RECHECKED. 새 발견 GT01R-04(S3) 1건 OPEN. S0·S1·S2 OPEN 0건.**

### R.1 실행

작업 트리:
- `tests/unit/test_diarization.py` 2회 실행: 매번 **21 passed**(7.83s, 7.71s)
- `ruff check`, `ruff format --check`: 통과

독립 mutation과 지연 주입:
- OS TEMP 사본에서 실행했다. 사본 루트는 `%TEMP%\recoryn-gt01-recheck-ad7f2c2995144586854b982756c127f7`, 보고서 sha256은 `18d08e7bc0ddc7ed3a8b3e25643b7242022ab062c546141f92e710b80edc7bae`다.
- X1·X5는 처음에 시계 생성 줄까지 지우는 잘못된 mutant였다. 그래서 setattr 한 줄만 지우도록 고쳐 다시 돌렸다. 재실행 사본은 `%TEMP%\recoryn-gt01-recheck-471569b2ef344d3682ddcce4063dc7fa`, 보고서 sha256은 `ef46d387010d4abd843cdc09f9f1f7378fd61ad6ca25bd522cd7bbcc5277dda2`다. 처음 X5의 cancel·close NameError는 mutant를 잘못 만든 결과이므로 아래 표에 넣지 않았다.
- 스크립트: `C:\Users\gangd\AppData\Local\Temp\claude\e47d15555ed7cfa9\d9354f5a-75d0-44dc-8069-db32589569d1\scratchpad\gt01_recheck.py`
- 매 변형 뒤 두 파일의 복원 hash가 원본과 같았다.

변형:
- X1: 느린 시작 시험에서 시계 대체(setattr) 한 줄 삭제
- X2: 제품 `_check`의 시간 검사를 `if False:`로 무력화
- X3: 제품이 import 때 묶어 둔 `_monotonic`을 쓰게 바꿈. 모듈 `time`을 우회하는 리팩터를 흉내 낸 것이다
- X4: `_MarkerClock`의 정지(표시 전 0 반환) 제거
- X5: 본 시험의 시계 대체 setattr 삭제 + 자식 시작 지연 2초 주입
- P7·P12·P16: `_hung_child`가 시작 표시를 쓰기 전에 각각 7·12·16초 쉬게 함. 시계 대체는 그대로다

| 변형 | timeout | cancel | close | 느린 시작 시험 | 판정 |
| --- | --- | --- | --- | --- | --- |
| V0 정상 | PASS 1.90s | PASS 0.41s | PASS 0.39s | PASS 3.92s | 21 passed |
| X1(C00 mutant 1 재현) | PASS | PASS | PASS | **FAIL**: 시작 표시 없음(1.59s) | 검출 |
| X2(C00 mutant 2 재현) | **FAIL**: `join(8)` 뒤에도 worker 생존 | PASS | PASS | **FAIL**: `DIARIZATION_PROCESS_FAILED`(32.35s) | 검출 |
| X3 | **FAIL**: `calls > 0` | **FAIL**: `calls > 0` | **FAIL**: `calls > 0` | **FAIL**: 시작 표시 없음 | 검출 |
| X4 | PASS | PASS | PASS | **FAIL**: 시작 표시 없음 | 검출(느린 시작 시험만) |
| X5 | **FAIL**: "provider returned before the child marker: [DiarizationResult(... error_code='TIMEOUT' ...)]" | **FAIL**: `calls > 0` | **FAIL**: `calls > 0` | 선택 안 함 | 검출 |
| P7 | PASS 8.91s | PASS 7.40s | PASS 7.38s | 선택 안 함 | 시작 7초 허용 |
| P12 | PASS 13.93s | PASS 12.41s | PASS 12.38s | 선택 안 함 | 시작 12초 허용 |
| P16 | **FAIL** 15.02s: "child marker did not appear within 15 s" | 선택 안 함 | 선택 안 함 | 선택 안 함 | 시작 상한 15초 작동 |

### R.2 항목별 재확인

**GT01R-01 / RECHECKED**
- 자식 시작 시간이 provider 시간 제한에서 분리됐다.
  - timeout 1.5초에서 시작이 7초(P7)·12초(P12) 늦어도 세 모드 모두 통과한다. 1판 probe에서 HEAD는 2초, 6초판은 7초에서 실패했다.
  - 실패는 시작 상한 15초를 넘을 때만 나며(P16), 원인 메시지가 남는다.
- 결정적 지연 행 `test_slow_child_start_does_not_use_the_provider_deadline`(`:311-331`)이 추가됐다. 이 행은 X1·X3·X4를 모두 잡는다. 특히 X4(시계 정지 제거)는 유휴 상태에서 본 시험 세 모드를 통과하므로 이 행만 잡는다. 그래서 이 행이 GT-P01의 핵심 성질을 지키는 유일한 결정적 시험이다.
- 리팩터 보호: `clock.calls > 0`(`:302`)이 있다. 진입 deadline 계산(`process.py:148`)이 항상 시계를 한 번 읽으므로 세 모드 모두에서 성립한다. X3에서 세 모드가 이 assertion으로 크게 실패했다. 모듈 `time`의 다른 속성을 쓰도록 바뀌면 `SimpleNamespace`에 그 속성이 없어 역시 실패한다.
- origin 확인을 timeout 모드로 한정한 C00의 근거는 코드와 맞다. `_check`는 취소·종료를 시계보다 먼저 검사한다(`process.py:217-218`이 `:219`보다 앞). 그래서 시작 표시 뒤 첫 `_check` 전에 취소가 오면 시계를 다시 읽지 않고 CANCELLED로 돌아간다. 이 경우 cancel·close에서 origin이 None일 수 있다.

**GT01R-02 / RECHECKED**
- 대기 assertion이 둘로 나뉘고 메시지가 붙었다(`:283-284`).
- X5에서 조기 반환 메시지에 결과 코드 TIMEOUT이 그대로 나왔다. P16에서는 15초 상한 메시지가 나왔다.
- 다음 실패는 원인을 스스로 남긴다.

**GT01R-03 / RECHECKED**
- 시계 대체를 세 모드에 모두 적용해 15초(`:281`)가 세 모드의 실제 시작 상한이 됐다.
  - P12에서 cancel·close가 통과했다. 시계 대체가 없었다면 시간 제한 10초가 먼저 다 됐을 시간이다.
  - P16 timeout은 15.02초에 상한 메시지로 실패했다.
- 새 주석(`:261-263`, `:281`)은 이 관계와 맞다. 다만 1판 주석이 남아 있다(GT01R-04).

### R.3 새 발견

#### GT01R-04 / S3 / OPEN: 1판 주석이 남아 2판 코드와 모순됨

근거: `test_diarization.py:256-258`에 1판 주석이 그대로 있다.

> The provider deadline starts before spawn, so it also covers child start-up. 1.5 s expired before the child wrote its marker under a loaded full run (GT-P01); 6 s still fires while the hung child ignores cancellation.

모순되는 점:
- 바로 아래 `:259`의 timeout 모드 값은 1.5초다.
- `:261-263`의 새 주석은 같은 배경을 다시 설명하며, 시계가 시작 표시 뒤부터 흐른다고 말한다.
- 그래서 주석 두 개가 같은 줄을 서로 다르게 설명한다. "6 s"는 이제 어디에도 없다.

같은 이유로 배정표 `docs/collaboration/assignments.md:30`의 GT01 행도 1판 내용("1.5→6초, 시작 표시 대기 8→15초. 단독 3회 PASS")을 적고 있다.

영향: 동작에는 영향이 없다. 다음 독자가 6초 값을 찾거나, 시작 시간이 아직 예산에 들어간다고 오해할 수 있다.

제안 수정:
- `:256-258`의 세 줄을 지운다(`:261-263`이 대체한다).
- 배정표 행은 통합 때 2판 내용(시계 대체, timeout 1.5초 복귀, 느린 시작 행, mutation 결과)으로 고친다.

### R.4 OPEN 아닌 관찰

1. **표시 뒤 창:** timeout 모드에서는 provider가 시작 표시 뒤 첫 시계 읽기부터 1.5초 뒤에 반환한다. 시험 thread는 이 안에 `provider._process`를 읽고 handle을 열어야 한다(`:286-289`).
   - 창의 길이: HEAD는 1.5초에서 시작 시간을 뺀 값, 1판은 약 5.7초, 2판은 1.5초다.
   - 2판의 창은 자식 시작과 무관하고, 같은 프로세스 안 thread 지연에만 기댄다. 그래서 원래 실패 유형보다 훨씬 덜 민감하다.
   - 더 굳히려면 시작 표시 전에 `provider._process.pid`가 생기는 것을 기다렸다가 handle을 먼저 연다. 시계가 표시 전에는 멈춰 있으므로 안전하다.
2. **확인 범위:** 느린 시작 시험은 자식 handle의 종료 신호(`WaitForSingleObject`)를 확인하지 않는다. 반환 전 종료 확인은 본 시험이 맡으므로 중복은 필요 없다.
3. **시험 시간:** timeout 모드는 1판 약 6.1초에서 약 1.9초로 줄었다. 느린 시작 행이 약 3.9초를 더한다.

### R.5 확인하지 않은 것

- 실제 CPU·디스크 부하에서의 반복 실행. 1판과 같은 사유이며, P7·P12·P16의 결정적 지연 주입으로 대체했다.
- C00이 보고한 5회 연속 PASS의 재현. 작업 트리에서 2회 연속 PASS만 확인했다.
