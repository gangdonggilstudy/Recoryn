# GC-P01 CI core 작업 시간 제한 독립 검토

2026-11-23, 검토자 Claude(C00 지정 하위 에이전트, G-P02 검토 A와 같은 검토자). 작성자는 C00이며 검토자는 이 변경을 작성하지 않았다.

**S0/S1/S2 발견 없음. OPEN 1건: S3 1건(근거 주석 문구).** 취소 원인은 시험 실패나 hang이 아니라 15분 작업 제한이라는 판단이 로그와 맞는다. 40분은 관측된 러너 속도 편차와 증가 여지를 고려하면 타당하다. 워크플로의 다른 부분에는 영향이 없다. 최종 수용은 C00가 결정한다.

## 1. 입력과 확인 방법

- 대상 tree는 **`84c8b6df5f24d5ac07ac86a2085327302e212ad7`**(`git cat-file -t` = tree), 기준은 HEAD `66f0a85`다.
- `git diff --stat 66f0a85 84c8b6df` 결과는 2파일, 4 insertions / 1 deletion이다.
  - `.github/workflows/core.yml`: `core` job의 `timeout-minutes: 15`가 `40`으로 바뀌고 근거 주석 2줄이 추가됐다.
  - `docs/collaboration/assignments.md`: GC01 행이 1행 추가됐다.
- `git ls-tree 84c8b6df .github/workflows/`에는 `core.yml` 하나뿐이다.
- 근거 로그(`build/ci-evidence/`)는 읽기만 했다. LF SHA256 앞 16자는 다음과 같다.

| 로그 | SHA256(앞 16자) |
| --- | --- |
| `run-45098064324-core311.log` | `f8b470f0ae25e27c` |
| `run-45098064324-core313.log` | `f979c3ca4467b4da` |
| `run-45076718852-core313-attempt1.log` | `825b6773c96da69b` |
| `run-45076718852-core313-attempt2.log` | `c7e8535ebb69aec9` |

- 원격 CI 조회, 네트워크, 시험 실행, git 쓰기는 하지 않았다. 판단은 위 로그와 tree 내용을 직접 읽은 결과다.

## 2. 관점별 판단

### 2.1 취소 원인: 시간 제한이 맞다

core (3.11) 로그(`run-45098064324-core311.log`)를 직접 읽었다.

- **시간 정렬**: 첫 줄(runner 시작)이 `02:04:16.80Z`, pytest의 KeyboardInterrupt가 `02:19:17.23Z`, `##[error]The operation was canceled.`가 `02:19:19.38Z`다. 작업 시작 후 정확히 15분 시점이며 job 단위 `timeout-minutes: 15`와 맞는다.
- **실패 아님**: 411행 `8450 passed in 839.97s (0:13:59)` 바로 앞에 `!!! KeyboardInterrupt !!!`가 있다. 즉 취소 신호로 중단된 요약이다. 시험 단계의 진행 줄 117개는 모두 `.`만 포함하며 `F`/`E`/`s` 문자가 없다(awk/grep으로 확인).
- **hang 아님**: 진행 표시가 끝까지 2~15초 간격으로 이어졌다(`[ 90%]` 02:18:51, `[ 91%]` 02:18:59, `[ 92%]` 02:19:05, `[ 93%]` 02:19:15, 이어 26개 점 출력 후 중단). 중단 위치 `src/recoryn/audio/processing.py:20`은 그 순간 실행 중이던 코드일 뿐이다.
- **다른 취소 원인 배제**: 워크플로에 `concurrency:` 그룹이 없어 새 push에 의한 자동 취소 경로가 없다.
- **한계**: GitHub UI annotation("exceeded the maximum execution time")은 저장 로그에 없다. 수동 취소는 로그만으로 완전히 배제할 수 없지만, 15분 정각 정렬로 보아 시간 제한으로 판단한다.

core (3.13) 로그는 `9039 passed, 6 warnings in 621.54s (0:10:21)`, coverage 92.33%다. 작업은 02:04:17 시작, 02:15:51 정리 완료로 약 11분 34초다. 3.13의 `[ 93%]` 시점은 시험 시작 후 약 595초였고 3.11은 840초였다. 따라서 이 run에서 3.11은 약 1.41배 느렸다.

### 2.2 40분의 적절성

**추정**:
- 3.11 전체 시험 시간 ≈ 840초 × (621.5/595) ≈ **877초(14.6분)**다. 설치·lint·mypy 약 1분과 coverage/wheel 단계를 더하면 작업 전체는 약 **16분**이다.
- 같은 commit에 가까운 이전 run 45076718852의 3.13 두 시도는 거의 같은 시험 수에서 **638.97초(8025 node)와 379.00초(8025 node)**였다. 러너 속도 편차가 최대 약 1.7배다.
- 3.11이 느린 러너에 걸리면 약 877초 × 1.7 ≈ 25분 시험, 작업 약 26~27분이 될 수 있다.

**판단**:
- 40분은 3.11의 평상시 추정(약 16분)의 약 2.5배이고, 최악 편차 추정(약 27분)보다 약 13분 여유가 있다. 승인된 단위들(G-P06 등)이 큰 case-space 시험을 계속 추가한다.
  - 참고: 이전 run의 3.13 379초 → G-P02 run 621.54초로, 새 시험 1,014 node가 CI(coverage 포함)에서 수 분을 더한 것으로 보인다. 편차가 섞여 있어 정확한 분리는 불가하다.
- 30분은 최악 편차와 증가를 함께 견디기 어렵다. 따라서 **40분은 타당하다**.
- hang 발견 지연 비용: 한 시험이 멈추면 matrix 두 작업이 각각 최대 40분 러너 시간을 쓰고 결과가 늦게 나온다. 현재 pytest 설정(`pyproject.toml` addopts, `requirements-dev.txt`)에는 시험별 시간 제한(pytest-timeout)이나 `faulthandler_timeout`이 없다. 다만 이번 변경 전에도 같은 위험이 있었고, 바뀐 것은 상한 시간뿐이다.

**대안 제안(결함 아님, 채택은 C00 결정)**:
1. pytest 내장 `faulthandler_timeout`(예: 600초)을 ini에 둔다. 한 시험이 그 시간을 넘으면 모든 thread의 stack이 로그에 남는다. 새 의존성이 없고 시험을 중단시키지 않는다.
2. 시험 단계에 step 단위 `timeout-minutes`(예: 30)를 따로 둔다. 설치·lint와 시험 지연이 구분되고, 시험 단계가 멈췄을 때 coverage·wheel 단계가 실행되지 않은 사실이 분명해진다.
3. 시험 단계에 `--durations=25`를 추가해 run마다 느린 시험 목록을 남긴다. 큰 case-space 시험의 증가 추세를 추적할 수 있다.
4. 장기안: 대형 case-space 가족(GATE/TRACE 등)에 marker를 붙여 별도 job으로 나누거나, coverage 측정을 한 Python 버전에서만 수행해 3.11 시간을 줄인다. coverage 결과가 버전별로 달라지는지 먼저 확인해야 하므로 지금 적용하라는 권고는 아니다.

### 2.3 다른 부분 영향 없음

- 변경은 `jobs.core.timeout-minutes` 값과 그 위 주석뿐이다. `runs-on`, matrix(3.11/3.13), `fail-fast: false`, 단계 명령, env, `permissions: contents: read`, action pin SHA는 바뀌지 않았다(변경 전후 YAML 대조).
- `optional-runtime` job의 `timeout-minutes: 20`과 단계도 그대로다.
- 다른 워크플로 파일은 없다.
- 주석은 YAML 주석이므로 실행 의미가 없다. 들여쓰기도 `timeout-minutes`와 같은 job 수준이라 YAML 구조를 바꾸지 않는다.
- 배정표 GC01 행의 수치(3.11 93% 취소·실패 아님, 3.13 9039 PASS·10분 21초)는 로그와 같다.

## 3. 발견

### GC01-01 / S3 / OPEN — 근거 주석의 "passed 15 min" 표현이 시험 통과로 읽힐 수 있다

- **근거**: 주석 `The offline suite took 10m21s on 3.13 and passed 15 min on 3.11 after G-P02`의 "passed"는 "15분을 넘겼다"는 뜻으로 보인다. 그러나 바로 앞의 시험 결과 서술과 겹쳐 "3.11에서 통과했다"로 오독될 수 있다. 실제로는 93%에서 취소됐다.
- **기대**: 예를 들어 `took 10m21s on 3.13; 3.11 hit the 15-min job limit at 93% (run 45098064324, canceled, not failed)`처럼 사실을 그대로 쓴다. 가능하면 러너 편차 근거(같은 코드의 3.13 379초/639초)도 한 줄로 남긴다.
- **영향**: 실행 의미는 없고 근거 기록의 정확성 문제다.

## 4. 관찰(이 단위 범위 밖)

- 3.13 run의 `9039 passed, 6 warnings`는 `-W error::ResourceWarning` 설정에도 경고 6건이 남은 결과다. 이미 배정표 G02b 행(ResourceWarning 6건, G02-MIG-09 경로 추정)에 후속으로 기록되어 있어 여기서는 새로 세지 않는다.

## 5. 결론

**GC01 REVIEW_READY / OPEN 1 (S0 0 / S1 0 / S2 0 / S3 1).** 취소 원인 판단과 40분 상한은 근거가 충분하다. GC01-01 주석 문구 수정과 §2.2 대안 채택 여부는 C00가 결정한다.
