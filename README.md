# Recoryn

Recoryn은 Windows에서 마이크와 시스템 소리를 분리 녹음하고, 로컬 AI 또는 사용자가 선택한 제공업체로 전사·요약하는 오픈소스 데스크톱 앱을 목표로 합니다. 녹음 보존, 외부 전송에 대한 사용자 통제, 원본 시간 위치까지 확인할 수 있는 기록을 우선합니다.

현재는 **설계 단계**입니다. 실행 가능한 앱, VoiceLocal 소스 이관, Windows 장치 검증은 아직 제공되지 않습니다. 저장소 소스 라이선스는 [Apache 2.0](LICENSE)이며, 향후 번들 의존성과 모델의 배포 조건은 별도로 검토합니다.

## 설계 문서

- [아키텍처와 전문가 검토 v1.0](docs/architecture-v1.md)
- [사용자 설계 요구사항](docs/design-input-v1.md)
- [검증 계획과 릴리스 게이트](docs/validation-plan.md)
- [전문가 팀의 품질 및 교차 검증 체계](docs/quality-system.md)
- 전문가 검토: [아키텍처](docs/reviews/architecture.md), [오디오와 복구](docs/reviews/audio-recovery.md), [AI와 UX](docs/reviews/ai-ux.md), [보안과 QA](docs/reviews/security-qa.md)

## 세션 협업

새 세션은 [AGENTS.md](AGENTS.md)와 [온보딩](docs/collaboration/onboarding.md)부터 읽고, [협업 규칙](docs/collaboration/workflow.md)과 [작업 배정표](docs/collaboration/assignments.md)에 따라 작업합니다. 작업 세션은 지정 파일만 수정하며, 오케스트레이터가 결과 통합과 최종 검증 후 commit 및 push를 수행합니다.
