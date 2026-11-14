# P13 독립 capture 검토

작성일: 2026-11-14. 검토자 P13(P03 저장 엔지니어), 작성자 P02. **검토한 snapshot에서 신규 S0~S3 발견 0건**. P03 storage 자체 검증·P11 수정 승인을 대신하지 않는다.

## 범위와 정적 대조

[구현 계약](../implementation/p0-contracts.md), [품질 체계](../quality-system.md), capture 소스와 단위 시험, 독립 queue model, app의 포화·pause/resume·fragment cutoff 통합 시험을 읽었다. capture 소스/테스트와 공용 파일은 수정하지 않았다.

| 검토 항목 | 확인한 계약·실제 반례 결과 |
| --- | --- |
| slot + byte 상한 | 두 조건을 같은 Condition lock 아래 검사한다. slot 여유가 있어도 bytes 초과 시 신규 block만 거부하며 기존 FIFO를 보존했다. s24 mono 3 bytes와 s16 stereo 8 bytes로 11 bytes를 정확히 채운 뒤 4 bytes를 거부하는 독립 oracle를 실행했다. 일부 drain 뒤에도 잔여 bytes가 부족하면 거부하고 충분한 drain 뒤 재수락했다. |
| frame/byte 회계 | 독립 probe에서 accepted frames=4/bytes=15, dropped frames=2/bytes=8, high-water bytes=11이 손계산과 일치했다. snapshot은 누적치이며 queued와 분리된다. |
| closed/EOF/privacy | full queue에서도 close가 별도 control 경로로 완료된다. accepted는 drain되고 이후 EOFError, open empty는 Empty다. close 이후 offer는 False이며 누적 loss를 늘리지 않았다. |
| 동시 offer/close | 같은 lock이 수락·유실·close의 선형화 경계다. close 우선/offer 우선 두 순서를 Event로 강제했다. 3 producers와 close를 동시에 시작한 64회에서 결과·FIFO·frame 회계가 24개 가능한 연산 순서로 만든 독립 oracle 중 하나와 일치했다. 특정 scheduling 순서를 가정하지 않았다. |
| 불변 PCM | domain frozen PCMBlock/AudioFormat과 bytes payload를 전달하며 수락 후 내용 변환이 없다. probe에서 frozen field 변경과 bytearray payload가 거부됐다. type·frame byte 검증은 domain 경계다. |
| 합성 포맷·시계·품질 | s24 mono 44.1kHz의 7 frames를 3/3/1로 나눠 sample bytes를 손계산과 비교했다. 시작 31ns의 sample 상관 시각은 31/68058/136085ns, frame positions는 0/3/6이었다. arrival와 합성 capture 시각은 같고 quality는 SYNTHETIC이며 실제 장치 정밀도로 표시하지 않는다. |
| cutoff와 저장 경계 | 통합 시험에서 포화 후 마지막 drop 누계 영속화, pause ack 전 RECORDING 유지·resume 거부, close 뒤 신규 submit 거부, 새 epoch 분리와 정상 트랙별 원본을 확인했다. 완전한 fragment group이 끝난 뒤만 chunk rotation한다. queue 자체에 세션/track 정책 책임을 잘못 추가하지 않았다. |

## 직접 실행한 독립 검증

다음 pytest 명령은 작성자의 로그를 복사하지 않고 P13에서 별도 UUID basetemp로 실행했다. 결과는 **68 passed in 0.82s**, ResourceWarning 오류 없음이다. property test는 고정 입력 재현 설정으로 100개 생성 예를 사용한다.

~~~powershell
$p13TestRoot = Join-Path ([IO.Path]::GetTempPath()) ('recoryn-p13-' + [guid]::NewGuid().ToString('N'))
.venv/Scripts/python.exe -m pytest tests/unit/test_capture.py tests/property/test_queue_model.py tests/integration/test_app_service.py::test_pause_resume_preserves_separate_track_epochs_and_privacy tests/integration/test_app_service.py::test_full_queue_close_preserves_last_drop_and_cutoff tests/integration/test_app_service.py::test_rotation_waits_for_the_complete_fragment_group -p no:cacheprovider --basetemp $p13TestRoot -q -W error::ResourceWarning
~~~

추가로 별도 Python stdin probe를 실행했다. 정답은 SyntheticSource나 queue 내부 상태 계산을 호출해 만들지 않았다. byte 경계는 표의 3+8=11, 합성 s24 bytes는 000080 000081 000082 000083 000084 000085 000086이다. 동시성 oracle는 {offer(frame=1), offer(3), offer(5), close}의 24개 permutation을 열거하여 slot=2/byte=20의 허용 순서·수락/유실 frame·FIFO tuple을 만들고, Barrier로 시작한 실제 64개 결과와 대조했다. 강제 두 순서는 producer를 Event에서 대기시키고 close 전/후에 해제했다. 스레드는 모두 bounded join으로 종료를 확인했다.

~~~text
{"byte_and_slot_boundaries":"PASS","forced_close_orders":2,
 "racing_offer_close_trials":64,"legal_order_oracle":"24 permutations",
 "source_s24_pcm_time_quality":"PASS","immutable_block":"PASS"}
~~~

## 검토 snapshot SHA-256

- src/recoryn/capture/__init__.py: ADFD9314E8580FA89543FC69C2E12E628F20F6237577EC318FB4791009A79353
- src/recoryn/capture/queue.py: 55FD01AAEF85D960DDF17484CB4B026E103E97162EF840BC262AEEE7EC1350DC
- src/recoryn/capture/synthetic.py: E8DE84E7CA153D4612F999C0AF956E88C77A621C3F689A3FC278530D84012AF2
- tests/unit/test_capture.py: DE42AAC13D5CDBE0F39E782605F98890027CD23B25631A87345B01B4A0254E14
- tests/property/test_queue_model.py: B16599D433A9BD426AC9CB4DAF81EBAB81748AC6DAA6B59E7ADC6C8D68032F15
- tests/integration/test_app_service.py: F9BA4A195327BA2594A79547DEEBF0ABB98B2C8E9999D39073A756F27D7E9FCE

## 판정과 미검증 사항

이번 반례와 읽은 계약에서 해결을 요구할 신규 결함은 발견하지 않았다. P0.1의 이 capture snapshot에 대한 독립 코드/회귀 검토 결과이며 전체 제품이나 실제 장치의 합격이 아니다. 파일이 바뀌면 관련 검토를 재개해야 한다.

Python lock/GIL은 callback 지연 상한이나 hard realtime을 보장하지 않는다. 합성 source는 wall clock·하드웨어 캡처·드리프트 측정이 아니다. source의 명시적인 큰 block_frames에 따른 자원 사용, 모든 OS scheduling, 실제 WASAPI/장치 전환/절전·성능·8시간 캡처 및 물리 전원 장애는 미검증이다. 모델·클라우드·GUI 접근성도 이 검토 범위 밖이다. 단위·property·제어된 통합 결과를 W01~W05/G3/G4 통과로 확대하지 않는다.
