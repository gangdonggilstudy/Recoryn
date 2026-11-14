# Recoryn 작업 배정표

현재 단계: 설계 작성 및 전문가 검토. 구현 배정 없음. 상태는 문서 작업에 한정한다. 오케스트레이터만 이 표를 수정한다. pane ID는 조회 시점의 식별자이며 재접속 후 재조회한다.

| 배정 ID | 역할 | 현재 pane | 소유 파일 | 수락 기준 | 상태 |
| --- | --- | --- | --- | --- | --- |
| D00 | 오케스트레이터와 통합 설계 | w5:p1 | AGENTS.md, README.md, docs/design-input-v1.md, docs/architecture-v1.md, docs/validation-plan.md, docs/quality-system.md, docs/collaboration/*, docs/reviews/design-signoff.md | 여섯 관점 통합, 요구사항 추적, 새 세션 규칙과 최종 문서 검증. Git 출판 결과는 별도 확인 | VERIFIED |
| D01 | 수석 아키텍트 | w5:p2 | docs/reviews/architecture.md | 경계, 상태 분리, 영속 계약, 마이그레이션과 취소 정책 | VERIFIED |
| D02 | Windows 오디오 전문가 | w5:p3 | docs/reviews/audio-recovery.md | 캡처 시계, 청크 저장·복구, 포화·장치·절전·디스크 장애 기준 | VERIFIED |
| D03 | ML 엔지니어와 UX 전문가 | w5:p4 | docs/reviews/ai-ux.md | 제공업체 계약, 근거 연결, 전사 버전, 비용·GPU·접근성 | VERIFIED |
| D04 | 보안 및 라이선스 전문가와 QA 릴리스 전문가 | w5:p5 | docs/reviews/security-qa.md | 동의, 비밀, 보존·삭제, 라이선스와 측정 가능한 검증 게이트 | VERIFIED |
| D11 | 독립 아키텍처 교차 검토 | w5:p2 | docs/reviews/cross-ai-ux.md | D03와 통합 계약·품질 체계의 반례와 종결 조건 | VERIFIED |
| D12 | 독립 오디오 교차 검토 | w5:p3 | docs/reviews/cross-architecture.md | D01와 통합 시간·저장 계약의 반례와 종결 조건 | VERIFIED |
| D13 | 독립 ML·UX 교차 검토 | w5:p4 | docs/reviews/cross-security-qa.md | D04와 정책·비용·취소·품질 계획의 반례와 종결 조건 | VERIFIED |
| D14 | 독립 보안·QA 교차 검토 | w5:p5 | docs/reviews/cross-audio-recovery.md | D02와 통합 장애·복구·보안 및 검증 게이트 확인 | VERIFIED |

모든 작업자는 `docs/design-input-v1.md`와 협업 규칙을 읽는다. D01~D04는 병렬로 독립 문서를 작성하고, 공용 계약 충돌은 문서에 결정 제안으로 남긴다. D00은 네 리뷰를 읽고 통합한 뒤 완료 보고와 수락 기준을 대조한다. 보류 결정은 통합 설계의 결정 기록에 소유자와 검증 조건을 남긴다.

D11~D14는 1차 작성자와 다른 세션의 교차 검토다. 검토자는 통합 문서와 타 담당 문서만 읽고 자신의 교차 검토 문서에 발견 사항을 기록한다. D00의 통합 수정 후 검토자가 같은 문서에 재확인을 남긴다. 설계 종결 기록은 D00 소유의 `docs/reviews/design-signoff.md`다. 검토 요청 자체는 검토 통과가 아니다.

설계 단계 결과: D01~D04 통합 및 D11~D14 재확인 완료. 24건의 문서상 발견 사항을 종결했다. 상세 근거와 한계는 [설계 검토 종결 기록](../reviews/design-signoff.md)에 둔다. 오케스트레이터가 최종 Git 검증과 push를 전담하며 실제 출판 결과는 commit과 원격 참조로 확인한다. 다음 구현 배정은 아직 없다. 제품 실행 검증은 모두 NOT_RUN이다.
