# Recoryn 전문가 팀 품질 및 교차 검증 체계

상태: 활성 품질 정책. 이 문서는 시험과 검토의 책임, 실행 순서 및 증거 기준을 정한다. 설계 시점의 교차 검토는 [설계 종결 기록](reviews/design-signoff.md), 구현·CI의 실제 실행 범위는 [코어 증거](implementation/p0-results.md)와 [제품 진행 기록](implementation/product-results.md)에 남긴다. 정책의 목표와 실제 검증을 구별한다.

Recoryn의 품질 판단은 요구사항 → 위험 → 계약 → 시험 → 독립 검토 → 통합 검증 → 배포의 연결로 이루어진다. 작성자 자체 검증, 자동 시험, 전문가 교차 검토는 각각 다른 결함을 찾으므로 하나의 통과 결과로 서로를 대체하지 않는다.

## 전문가 팀과 독립성

| 역할 | 설계 및 작성 책임 | 다른 담당자가 확인할 핵심 내용 |
| --- | --- | --- |
| 수석 아키텍트 | domain 계약, 상태, 동시성, 스키마와 migration | 오디오 담당이 시간·저장 경계를, QA가 전이·호환성과 실패 시나리오를 검토 |
| Windows 오디오 전문가 | 캡처, 시계, queue, 청크, 복구 | 아키텍트가 저장 계약을, QA가 유실·지속성 및 실제 장치 증거를 검토 |
| ML 시스템 엔지니어 | STT/요약, 모델·GPU, 근거와 품질 corpus | 보안이 전송·모델 경계를, UX가 초안·근거·오류 해석을 검토 |
| 보안 및 라이선스 전문가 | 비밀, 동의, 삭제, 다운로드와 배포 조건 | ML이 제공업체 우회 경로를, QA가 공격·누출·공급망 부정 시험을 검토 |
| UX 전문가 | 상태 안내, 접근성, 복구·편집·재생 흐름 | 오디오가 표시의 사실성을, ML이 confidence와 근거 표현을, QA가 조작성 검토 |
| QA 및 릴리스 전문가 | 시험 설계, 독립 oracle, matrix, CI와 패키지 증거 | 관련 기술 담당이 관측·허용 오차를, 보안이 로그·배포 노출을 검토 |
| 오케스트레이터 | 배정, 계약 통합, 결과 대조, 최종 commit/push | 독립 검토자가 통합 문서와 위험 종결의 근거를 확인 |

한 세션이 여러 페르소나를 맡아도 여러 독립 검토자로 계산하지 않는다. 작성 세션과 교차 검토 세션은 달라야 한다. 오케스트레이터가 직접 작성한 통합 계약도 다른 세션의 검토를 받는다. 검토 독립성은 별도 실행의 장점일 뿐 같은 모델을 쓴 리뷰가 인간 전문가나 하드웨어 시험을 대체하지 않는다.

데이터 손실, 무동의 전송, 비밀 유출, 삭제 복원, 잘못된 버전 덮어쓰기는 고위험 변경이다. 해당 도메인 담당과 보안 또는 QA의 두 관점이 필요하며, 가능한 경우 서로 다른 검토 세션을 배정한다. 가용 세션이 부족하면 검토를 순서대로 수행하고 독립 검토가 없던 범위는 공개한다.

## 변경 단위 검증 순서

1. 오케스트레이터가 요구사항 ID, 위험, 작성자, 소유 파일, 독립 검토자와 수락 기준을 배정한다.
2. 작성자가 경계와 실패 동작을 명시하고 영향을 받는 시험을 선택한다. 고위험 변경은 실행 전에 부정 시나리오를 정의한다.
3. 작성자가 구현과 의미 있는 시험을 제출한다. 오류 수정은 가능한 경우 수정 전 재현 실패와 수정 후 통과를 남긴다.
4. 독립 검토자가 요구사항과 명세를 먼저 읽고 반례를 만든다. 자체 검증 로그를 복사해 승인하지 않는다. 고위험 변경은 핵심 재현을 별도 실행한다.
5. 발견 사항을 심각도와 함께 기록하고 작성자가 수정한다. 검토자가 해결 근거를 재확인한다.
6. 오케스트레이터가 통합 diff와 필수 게이트, 미실행·skip·보류 범위를 확인한다. 최종 변경 뒤의 commit 또는 tree digest와 증거를 연결한다.
7. 오케스트레이터가 검증한 결과만 commit/push한다. 릴리스는 같은 commit에서 만든 패키지의 별도 게이트를 요구한다.

## 시험 계층과 책임

| 계층 | 대상과 대표 반례 | 실행 환경 | 작성 / 교차 검토 |
| --- | --- | --- | --- |
| 정적 검사 | 타입, lint, domain의 Qt/SDK 의존, secrets와 정책 우회 호출 | 오프라인 일반 runner | 작성 담당 / 아키텍트·보안 |
| 유닛 | PCM 길이·포맷, 시간 단위, 상태 전이, 동의 scope, 비용 예약, SRT 경계 | fake clock과 작은 임시 파일 | 각 모듈 담당 / 해당 경계의 다른 전문가 |
| 속성 및 모델 기반 | 임의 pause/disconnect/crash/retry 조합, 정렬 단조성, 삭제 불변식 | 고정 seed 및 실패 입력 재생 | 아키텍트·QA / 오디오·보안 |
| 계약 | 모든 어댑터의 기능·오류·취소·진행 보고 및 미설치 경로 | fake provider, 고정 응답 | ML / 아키텍트·보안 |
| 통합 | 실제 SQLite·파일, worker 종료, revision 게시, queued consent 철회 | subprocess와 실제 임시 저장소 | 아키텍트·오디오 / QA·보안 |
| 장애 및 동시성 | 저장 단계별 kill, short write/ENOSPC, queue 포화, 늦은 결과, lock 경쟁 | 제어 가능한 fault injector | 오디오·QA / 아키텍트·보안 |
| UI 및 E2E | 녹음→정지→복구→전사→근거 재생→내보내기, 키보드와 읽기 도구 | Qt 테스트와 Windows 데스크톱 | UX / QA·오디오 |
| 실제 Windows 장치 | WASAPI, Bluetooth, 장치 변경, sleep, 긴 세션 | 통제된 실제 장비 | 오디오 / QA |
| AI 품질 및 성능 | 한국어 CER/다국어 WER, claim 근거·상충, 메모리·초기 실행 | 라이선스 corpus와 고정 환경 | ML / UX·QA |
| 보안 및 릴리스 | 네트워크 무전송, vault, 경로 탈출, SBOM, clean VM 설치·제거 | 격리 VM·통제된 network observer | 보안·릴리스 / 아키텍트·QA |

작은 문구·레이아웃 수정에 구현을 그대로 따라 하는 시험을 추가하지 않는다. 사용자 결과나 실패 계약을 검증하는 가장 작은 적절한 계층을 선택한다. 유닛에서는 장치·모델·클라우드를 호출하지 않으며 계약 mock을 통과했다고 실제 제공업체 호환성을 선언하지 않는다.

## 유닛과 속성 시험 설계

사용자 지시에 따라 시험의 충분성은 [경우의 수 설계](testing/case-space.md)의 유한 분모·상태/결정/순서 모델과 독립 oracle로 판단한다. 위험에 필요한 시험은 적극 적용하며 작은 표현 변경에 불필요한 구현 복제 시험을 만드는 것과 구분한다. 작성자는 입력 동치류·경계·제약, 실행 가능한 조합 수, 기존 시험의 대응, 추가 시험과 미검증 범위를 먼저 제출한다. 무한 입력에 대한 생성 시험·제한 깊이 열거를 전수 증명으로 확대하지 않는다.

각 시험은 요구사항, 입력, 기대 결과를 갖는다. 기대 결과는 코드의 같은 계산식을 복제하지 않고 손계산 가능한 값, 독립 기준 구현, 불변식 또는 고정된 외부 형식으로 정한다. 예를 들어 48,000 frame과 48 kHz의 1초, 44.1→16 kHz 변환의 길이·오차 범위, 서로 다른 채널 수의 frame byte 계산을 기준으로 삼는다.

재현 가능한 fake clock, 고정 seed, 합성 PCM impulse·sine·무음·중복 경계, 임시 파일 fixture와 fake provider를 사용한다. 동시성은 긴 sleep 대신 barrier, event와 가짜 시계로 순서를 제어한다. `random.seed`만으로 OS scheduling까지 결정된다고 가정하지 않는다. 실패 입력과 seed, event 순서를 증거에 남긴다.

핵심 불변식은 다음과 같다.

- AI 예외와 취소는 이미 확정된 원본 청크를 변경하지 않는다.
- 확정 청크는 bytes/frames/checksum이 맞고 중복 등록으로 늘어나지 않는다.
- 알려진 frame은 보존·유실 계수로 설명되며 미상 유실은 별도 표시된다.
- 시계 reset을 넘어서는 선형 정렬을 수행하지 않으며 시간 단위가 혼합되지 않는다.
- 취소·실패 attempt의 늦은 결과가 active revision을 바꾸지 않는다.
- 동의 없는 요청은 DNS·연결·SDK 호출 전에 차단된다. 동의 scope 확대가 암묵적으로 일어나지 않는다.
- deletion intent가 있는 세션을 복구 스캔으로 재등록하지 않는다.
- 내보낸 claim 참조는 고정 revision에 존재하며 경로는 허용 root 안에 있다.

제안 도구는 pytest, Hypothesis와 coverage.py다. pytest marker로 계층을 선택하고, Hypothesis stateful test로 작업 순서를 생성하며 branch coverage로 실행되지 않은 분기까지 확인한다. 버전과 plugin은 첫 코드 배정에서 고정한다. [pytest 구성](https://docs.pytest.org/en/stable/explanation/goodpractices.html), [marker](https://docs.pytest.org/en/stable/example/markers.html), [Hypothesis stateful](https://hypothesis.readthedocs.io/en/latest/stateful.html), [branch coverage](https://coverage.readthedocs.io/en/latest/branch.html)

## 테스트 코드와 실행 구성 제안

```text
tests/
  unit/{domain,audio,jobs,security,exports}/
  property/
  contract/providers/
  integration/{storage,recovery,workers,privacy}/
  ui/
  e2e/
  hardware/windows/
  benchmarks/
  release/
  fixtures/synthetic/
  conftest.py
```

marker 제안은 `unit`, `property`, `contract`, `integration`, `ui`, `e2e`, `hardware`, `benchmark`, `release`, `live_provider`다. 네트워크는 기본 차단한다. 유료 live provider 시험은 별도 동의·전용 테스트 키·낮은 한도·비민감 corpus로만 실행하며 PR의 필수 무과금 시험을 대체하지 않는다. hardware/live marker가 빠진 필수 시험이 skip되면 pass로 집계하지 않는다.

커버리지 초기 제안은 핵심 domain/storage/jobs/security의 line 95% 및 branch 90%, 전체 line 85% 및 branch 80%다. 실제 측정 전 목표 예산이며 첫 코드 도입 시 QA와 아키텍트가 fixture와 분모를 고정한다. 생성 코드·vendor 제외와 branch 제외는 사유를 검토받는다. domain 시간 계산, 삭제, 동의, 게시 경쟁의 필수 시나리오는 커버리지 수치와 무관하게 통과해야 한다.

일부 핵심 모듈에는 비교 연산 반전, 동의 검사 제거, checksum 검증 제거, active revision 비교 제거 같은 의도적인 결함을 넣어 기존 시험이 실패하는지 확인하는 mutation 점검을 제안한다. 도구·Windows 지원은 도입 전에 확인하며 전체 mutation 비율 자체를 초기 릴리스 기준으로 삼지 않는다. 실제 원본이나 사용자 환경에서 결함 주입을 실행하지 않는다.

## CI와 게이트

commit·push는 [푸시 단위 규칙](collaboration/push-units.md)의 계획·명시 stage·동결 증거·독립 검토·원격 확인을 따른다. 여러 작성자의 변경이 있다는 이유만으로 미검증 묶음을 통합하지 않는다. 각 단위의 시험 충분성은 line/branch 외에 선언한 경우의 수 분모와 관측된 실행을 대조한다.

| 게이트 | 시점 | 필수 결과 |
| --- | --- | --- |
| G0 설계 | 구현 배정 전 | 요구사항 추적, 계약 일치, 소유권, 교차 검토와 심각한 이슈 종결 |
| G1 변경 | 코드 PR 또는 통합 전 | 정적 검사, 관련 유닛·속성·계약, privacy·recovery 핵심 회귀, 독립 리뷰 |
| G2 통합 | 주요 병합과 정기 실행 | 실제 파일/DB/worker 장애, UI 자동 시험, 전체 오프라인 회귀 |
| G3 장치와 품질 | 백엔드 채택·마일스톤 | 명시한 Windows 장치 matrix, 장시간·절전, AI 평가와 성능 예산 |
| G4 릴리스 | 배포 전 | 동일 commit의 패키지 hash, clean VM 설치/제거, 서명 결정, 라이선스·SBOM·보안 |

첫 코드부터 Windows runner를 필수로 두고 순수 domain은 보조 OS에서 실행해 경계 가정을 검사할 수 있다. 지원 Python·Windows 버전은 ADR08에서 확정한 matrix만 주장한다. CI cache key는 OS·Python·lockfile로 분리한다. 비신뢰 PR에는 운영 비밀을 제공하지 않고 self-hosted hardware runner의 신뢰 범위를 제한한다. 패키지는 깨끗한 환경과 고정 의존성으로 만들고 build provenance 및 차이를 기록한다. 재빌드 hash가 일치하지 않으면 차이를 기록하며 bit-for-bit 재현성을 주장하지 않는다.

nightly 확대 시험과 GPU/장비 시험은 가용성에 따라 예약한다. G1 실패를 무조건 rerun해 성공한 한 번만 남기지 않는다. flaky 시험은 결함 ID·책임자·기한과 영향을 기록하고 필수 계약이 검증되지 않으면 해당 게이트를 막는다. 환경 실패, 기대 실패와 실제 제품 실패를 따로 집계한다.

## 발견 사항과 증거

심각도 `S0`는 무동의 전송·비밀 유출·원본 대량 손실처럼 배포를 즉시 막는 위험, `S1`은 복구 불가·잘못된 게시·핵심 기능 실패, `S2`는 우회 가능한 기능·품질 문제, `S3`는 경미한 문서·표시 문제다. 분류는 영향·재현 조건으로 결정한다. 열린 S0/S1은 해당 단계의 통과와 push를 막는다. 낮은 심각도의 보류는 이유·담당·기한과 오케스트레이터의 수용을 기록하며 제품 원칙 위반은 예외 처리하지 않는다.

발견 상태는 `OPEN → FIXED → RECHECKED → CLOSED`이며 수정자와 재확인자를 기록한다. 사실상 열린 항목을 단순히 보류 ADR로 옮겨 닫지 않는다. 미결정 성능 예산처럼 구현 전 실험이 필요한 항목은 영향받는 게이트와 필요한 증거를 명시한다.

```text
검증 ID / 요구사항 및 위험 ID:
작성자 / 독립 검토자 / 최종 통합자:
commit 또는 최종 tree·파일 digest:
환경: OS build, Python·의존성·모델·driver, 장치·포맷
절차 또는 정확한 실행 명령과 seed:
기대 결과 / 실제 결과 / 허용 오차와 근거:
PASS / FAIL / BLOCKED / NOT_RUN / NOT_APPLICABLE:
로그·보고서·산출물 경로 및 digest:
발견 ID / 해결 변경 / 재확인:
남은 제한과 다음 게이트:
```

증거는 Git에 민감 녹음을 올리지 않고 비민감 요약·hash·참조만 남긴다. 실행 로그가 없으면 시험 통과로 기록하지 않는다. 문서 리뷰는 체크한 버전과 지적·해결 근거를 남기며 하드웨어 증거란을 채우지 않는다. 릴리스 근거가 변경되면 관련 게이트를 다시 열고 재검증한다.

## 현재 설계의 교차 검토 배정

1차 D01~D04 작성 후 다음 2차 리뷰를 실시한다. 각 리뷰는 타 담당 문서와 통합 설계·검증 계획의 경계를 확인한다. 상세 소유권은 [배정표](collaboration/assignments.md)에 기록한다.

| 배정 | 검토 세션 관점 | 교차 검토 대상 |
| --- | --- | --- |
| D11 | 아키텍트 | AI·UX 계약, 통합 상태/작업/버전과 검증 체계 |
| D12 | 오디오 | 아키텍처의 시계·저장·복구와 통합 청크 계약 |
| D13 | ML·UX | 보안·QA의 endpoint/실행 위치/취소/비용과 시험 가능성 |
| D14 | 보안·QA | 오디오 장애/지속성·삭제·network 및 통합 검증 게이트 |

오케스트레이터는 네 교차 검토의 발견 사항을 통합하고 수정 후 해당 검토자에게 재확인을 받는다. 새 세션에는 [온보딩](collaboration/onboarding.md)과 이 문서를 함께 읽게 하고, 구현 배정에도 같은 작성·검토 분리를 적용한다.
