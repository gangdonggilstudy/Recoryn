# Recoryn 설계 교차 검토 종결 기록

작성일: 2026-11-14. 현재 상태: **G0 설계 문서 검증 완료**. 독립 교차 검토의 24건을 수정하고 원 검토자의 문서상 재확인을 받아 종결했다. 이 기록의 PASS는 설계 문서에만 적용하며 제품 실행 시험을 뜻하지 않는다.

## 범위와 역할

오케스트레이터 D00이 사용자 요구사항, 아키텍처, 검증 계획과 협업 규칙을 통합했다. 기존 Recoryn 작업 세션 네 개에서 여섯 전문가 관점을 적용해 1차 검토를 작성하고, 다른 세션의 산출물 및 D00 공용 문서를 2차로 교차 검토했다.

| 작성 배정 | 1차 문서 | 독립 교차 검토 배정과 문서 |
| --- | --- | --- |
| D01 아키텍트 | [아키텍처](architecture.md) | D12 오디오의 [교차 검토](cross-architecture.md) |
| D02 오디오 | [오디오와 복구](audio-recovery.md) | D14 보안·QA의 [교차 검토](cross-audio-recovery.md) |
| D03 ML·UX | [AI와 UX](ai-ux.md) | D11 아키텍트의 [교차 검토](cross-ai-ux.md) |
| D04 보안·QA·릴리스 | [보안과 QA](security-qa.md) | D13 ML·UX의 [교차 검토](cross-security-qa.md) |

1차 문서는 검토 제안과 대안을 보존한다. 통합 정본은 [아키텍처](../architecture-v1.md), 시험 ID 정본은 [검증 계획](../validation-plan.md), 역할·게이트 정본은 [품질 체계](../quality-system.md)다. D01 CLOSED는 통합 FINALIZED에 대응하며, D02 독자 컨테이너와 manifest 선행 게시 대안은 초기 채택안이 아니다. 정량값의 차이는 측정 후보이며 실측 성능 차이가 아니다.

## 발견 사항과 수정 근거

총 24건의 발견 제안에는 같은 위험을 다른 관점에서 지적한 중복 항목이 포함된다. 실제 구현 결함이나 실행 재현 결과가 아니라 문서 계약의 공백과 반례다. 각 항목은 D00 수정 후 FIXED, 원 검토자 재확인 후 RECHECKED를 거쳤으며 아래 CLOSED는 D00의 문서상 통합 종결을 뜻한다. 제품 실행 검증의 완료를 뜻하지 않는다.

| ID | 지적 요지 | D00 수정과 시험 연결 | 상태 |
| --- | --- | --- | --- |
| D11-01 | 취소·게시 transaction 경계 | A 상태 계약의 fence·삭제·포인터·Job/Attempt/outbox 공통 transaction, I04 | CLOSED |
| D11-02 | 늦은 요약 선택 덮어쓰기 | A 메타데이터의 독립 summary selection CAS·OUTDATED, I05 | CLOSED |
| D11-03 | 비용 중복 정산 | request/reservation/event별 ledger, limit 100→최종 40 oracle, U08/I06 | CLOSED |
| D11-04 | 편집 문장의 음성 provenance | user_assertion/unresolved·발화 배지 금지, U04/M01/E01과 D03/AU06 매핑 | CLOSED |
| D11-05 | 부분 결과와 준비 상태 | complete/coverage와 부모 Job 성공 구분, C01/M01/E01 | CLOSED |
| D11-06 | Job/Attempt 실행 설정 경계 | 의미 설정과 실행 조정·checkpoint 호환 키, U03/I02/M02 | CLOSED |
| D11-07 | 오류→상태·UI 매핑 | unknown 우선순위와 BLOCKED(reason)/WAITING_USER 투영, C02 | CLOSED |
| D12-01 | manifest 실패 후 최종 상태 | DB 확정 뒤 FINALIZED 유지·projection pending·project export 차단, F03/F04 | CLOSED |
| D12-02 | pause와 drain/seal 경계 | 트랙별 cutoff·누계·별도 제어 ack, pending pause·resume 차단, P01/F01/W03 | CLOSED |
| D12-03 | FINALIZED 뒤 고아 채택 | 기본 후보, 명시 채택 시 새 AudioRevision·readiness 재계산, I03/P01 | CLOSED |
| D12-04 | capture와 arrival 시각 혼합 | nullable sample-correlated 시각과 arrival 분리·오류 표본 제외, U02/P02 | CLOSED |
| D12-05 | journal 독립 장애 시험 누락 | PCM/journal/descriptor torn write·중복·fragment의 prefix oracle, F02/F04 | CLOSED |
| D13-01 | 철회→첫 송신 경합 | SendPermit와 철회·dispatch 공통 직렬화, 정책 영속화·in-flight 구분, I07/S01 | CLOSED |
| D13-02 | 과거 백업의 grant 부활 | 복원/import는 새 실행 세대·재동의, F05/I07 | CLOSED |
| D13-03 | 취소와 pointer 경합 | 공통 transaction과 취소 우선/게시 우선 판정, I04/I05 | CLOSED |
| D13-04 | 삭제로 비용 예약 소실 | library ledger의 최소 비민감 exposure 유지·손상 차단, I06/F06 | CLOSED |
| D13-05 | coverage와 전체 성공 분리 | partial revision과 부모 전체 Job 실패/대기 구분, C01/M01/E01 | CLOSED |
| D13-06 | 사실성 평가 oracle | claim 라벨·논의/확정 예시·독립 평가자·누락 분모, M01 평가 프로토콜 | CLOSED |
| D13-07 | 접근성 부정 흐름 | P1부터 동의 거부/철회·CPU 거부·예산 취소·복구와 Narrator, E02 | CLOSED |
| D14-01 | journal 논리 prefix 검증 | 연속 offset·frame alignment·유일 fragment·무payload 구분, F02 | CLOSED |
| D14-02 | 삭제 DB/journal 이중 기록 | journal 영속 게시→DB 접수·삭제 세대, 어느 한 의도 우선·판정불가 보류, F05/F06 | CLOSED |
| D14-03 | 삭제/철회와 새 전송 경합 | 정책 coordinator 직렬화·새 write 차단·handoff 이후 한계, I07/F06/S01 | CLOSED |
| D14-04 | pause/stop privacy cutoff | 모든 필수 트랙의 capture+drain/seal ack·late callback gate, P01/W03/E02 | CLOSED |
| D14-05 | 다운로드 검증 게이트 지연 | S04를 첫 다운로드·로드 전 G1/G2/P1로 분리, REL01/02는 배포 게이트 | CLOSED |

표의 A는 통합 아키텍처를 뜻한다. 원 검토의 문제·심각도·반례·당시 digest는 각 교차 검토 파일에 유지한다. 변경 뒤 재확인은 같은 검토자가 해당 파일에 기록하고 D00이 그 결과를 이 표와 연결한다.

## 현 단계 검사와 남은 게이트

문서 정적 검사는 UTF-8, 상대 링크, 표 열 수, 코드 블록과 공백을 확인한다. 내용 검사는 R01~R06과 추가 기능의 추적, 상태·저장·복구·전송·삭제 계약의 일관성을 대상으로 한다. 독립 재확인 결과와 동결 snapshot digest를 아래에 기록했다. 후속 내용 변경 시 관련 항목을 다시 연다.

정적 검사는 PowerShell에서 읽기 전용 Python 검사로 UTF-8 해석, replacement 문자·연속 물음표 손상·공백, 코드 fence, fence 밖 표 열 수와 상대 링크 존재를 확인하고, 시나리오 ID 유일성과 CLOSED 수를 검사했다. 네 교차 검토 파일의 최신 snapshot 해시가 실제 세 정본의 SHA-256과 일치하는지 확인했으며 해시 길이 오류도 없다. 이 검사는 외부 링크 가용성·앱 동작·무전송을 시험한 것이 아니다.

제품의 유닛·속성·통합·장애 주입·network·모델·Credential Manager·접근성·Windows 실장비·VM·물리 전원 장애 시험은 모두 **NOT_RUN**이다. VoiceLocal 소스 분석과 migration도 미수행이다. 설계 리뷰의 반례 작성은 실행 증거가 아니다.

구현 전에 정할 담당과 게이트는 ADR06~ADR10을 따른다. serializer golden fixture와 crash 동작은 G1/G2, 오디오 backend·장비·수치 예산과 AI 품질 corpus/임계값은 G3, 실제 배포물·의존성·모델 라이선스와 설치·서명은 G4에서 검증한다. 이 보류 자체가 해당 기능의 합격이나 제품 준비 상태를 뜻하지 않는다.

## 독립 재확인 결과

| 원 검토자 | 재확인 | 문서상 남은 OPEN | 근거 |
| --- | --- | --- | --- |
| D11 아키텍트 | 7/7 RECHECKED | 0 | [D11 후속 재확인](cross-ai-ux.md) |
| D12 오디오 | 5/5 RECHECKED | 0 | [D12 후속 재확인](cross-architecture.md) |
| D13 ML·UX | 7/7 RECHECKED | 0 | [D13 후속 재확인](cross-security-qa.md) |
| D14 보안·QA | 5/5 RECHECKED | 0 | [D14 후속 재확인](cross-audio-recovery.md) |

네 검토자는 같은 최종 정본을 대조했다. 각 교차 검토 문서 앞의 OPEN 및 과거 digest는 최초 발견 이력이며 후단의 재확인 결과가 해당 snapshot의 최신 판정이다. D14의 해시 전사 오기는 원 검토자가 수정·실제 파일 대조를 완료했고 최종 기록은 아래 값과 일치한다.

| 정본 | 동결 SHA-256 |
| --- | --- |
| architecture-v1.md | `E08450D0899A5DCF4DDE5745B6BC58B1A7B6F0B2BF0867CAC4FF405D96DA7ABD` |
| validation-plan.md | `DF1551A71C3BF55C6A4466B68443EFDE1673A7C22A1BBB867A69DD6F527601AB` |
| quality-system.md | `FE0AD8FF751143A6DC9AF77A510F56186E78DA0D22B2559CC532958442E2B044` |

D00은 위 문서상 해결과 최종 정적 검사를 근거로 G0를 종결한다. 제품 G1~G4는 미완료다. 최종 원격 push의 실행 결과는 Git commit과 원격 참조 확인으로 보고하며 이 문서의 G0 판정을 push 성공의 증거로 사용하지 않는다.
