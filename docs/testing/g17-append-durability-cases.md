# G-P17 녹음 append의 동기화 단위와 내구성 — 계약안

상태: **계약 제안 / C00·제품 결정 대기 / 제품·시험 미수정**. 작성자 w5:p8 Codex. 기준 `b92552059ef3b19b038e97cba3e3c44996fc5ee1`. 구현 착수는 **G-P08 push 및 C00 시작 신호 뒤**다. G-P08 독립 검토 수정 요청이 오면 그것을 우선한다.

이번 쓰기 범위는 이 문서 하나다. 아래 제품·시험 파일 목록은 앞으로의 승인 요청이며 지금의 쓰기 권한이 아니다. 실제 장치·전원 차단·HDD·백신 검사는 실행하지 않았다. 계약 분모와 목표는 실측 결과가 아니다.

## 1. 요구·위험과 권고의 요지

정본은 [통합 계획](../implementation/v1-gap-plan.md)의 G-P17(S2), [G-P15 계약과 결과](g15-seal-mutex-cases.md) §17, [G-P08 계약과 결과](g08-track-health-cases.md)다. 원본을 변환하거나 버려서 처리량을 맞추지 않으며, AI가 녹음 저장을 막지 않는 제품 불변식을 유지한다.

권고는 두 단계다.

1. **G-P17a: 내구성 의미를 유지한 mutex 축소.** 블록별 payload sync → journal sync의 완료를 기다리는 기본 `PER_BLOCK`은 유지하고, 파일 fsync와 기다림을 root mutex 밖으로 옮긴다. 삭제 의도와 실제 미디어 쓰기의 순서는 같은 mutex에서 다시 확인한다. 이것만으로 소비자 처리량 문제가 해결됐다고 보고하지 않는다.
2. **G-P17b: 명시 선택하는 `BATCHED` 묶음 동기화.** 소비자는 허용된 미디어 쓰기까지만 하고, 기존 sealer thread가 제한된 동기화 요청도 처리한다. 별도 건강·동기화 thread는 추가하지 않는 안을 권고한다. 기본 제안은 트랙별 **N=100블록 또는 T=1초 중 먼저 도달한 시점에 동기화 요청**이다. 이는 요청 주기이며 1초 전원 장애 손실 상한이 아니다. 기본값은 사용자 결정 전까지 `PER_BLOCK`으로 유지한다.

`BATCHED`를 실행하려면 해당 실행의 명시 확인을 받는다. 실행 중 자동 전환, 디스크가 느리다는 이유로 기본 완화, 가져온 설정의 자동 적용은 하지 않는다. 사용자 확인 없이 기존 내구성 의미를 낮추지 않는 것이 권고다. C00이 사용자 결정을 받아 기본을 바꾸려면 그 결정과 정본 문구를 별도 기록한다.

원본 수락 후 조용한 손실·삭제 부활·거짓 정지 성공은 S1 경계다. 현재의 디스크 처리량에 따른 `QUEUE_DROP`은 S2 개선 대상이며, 이미 거부된 블록을 저장된 것으로 표시하지 않는다.

## 2. 직접 확인한 근거와 인용의 구별

아래 코드 줄은 작업 트리가 아닌 `git show b925520:<path>`로 직접 읽었다.

| 위치 | 직접 확인한 사실 |
| --- | --- |
| `storage/chunks.py:411-414,447-451` | `append`는 root mutex를 잡고 삭제 권위를 확인한 뒤 payload write·sync와 journal write·sync 두 번을 모두 끝낸다. |
| `storage/chunks.py:456-462` | 프레임·바이트·이전 블록 상태는 현재 두 sync 성공 뒤 증가한다. 반환 시점을 바꾸면 이 의미도 명시해야 한다. |
| `storage/_safe.py:155-167,178-189` | 파일은 `buffering=0`으로 연다. `write_all`은 short write를 반복하며 `sync`는 flush 후 `os.fsync`다. 무버퍼 조건을 유지해야 mutex 밖 flush가 뒤늦은 새 쓰기로 변하지 않는다. |
| `storage/chunks.py:43-49,493-517` | 열린 파일 또는 SEALING writer는 활성이다. 준비는 mutex 밖, 최종 삭제 검사·rename은 안에서 한다. |
| `storage/chunks.py:540-576` | seal 준비는 payload·journal·descriptor를 sync하고 검증한다. **descriptor 생성·쓰기도 현재 mutex 밖**이다. 게시 검사는 준비 뒤 다시 한다. |
| `storage/_coordination.py:40-59` | root mutex를 유지한 삭제 권위 확인과 이어지는 쓰기가 I1의 선형화 근거다. 열린 Library의 색인을 재사용한다. |
| `storage/_coordination.py:60-85` | 열린 Library가 없으면 기존 durable 의도·DB 세대 검사로 내려간다. 확인 불가는 허용이 아니다. |
| `storage/library.py:448-474` | `_writer_intent`는 자기 세션의 의도 이름과 DB 행을 확인한다. 다른 세션 journal 본문을 읽어 capture를 중단시키지 않는다. |
| `storage/library.py:1026-1064` | 복구 salvage는 세션 claim으로 보호되지만 `_live` 확인 뒤 mutex를 풀고 private `_append`·`_seal`을 호출한다. 파일 제거와 상호 배제되는 것과 삭제 의도 뒤 새 바이트 쓰기 금지는 서로 다른 성질이다. |
| `storage/library.py:1677-1708` | 초기 삭제는 root mutex 안에서 먼저 의도를 게시·투영한다. 활성 writer/claim 때문에 제거가 보류되더라도 의도는 남는다. |
| `app/recording.py:229-259,282-313` | 소비자 하나가 모든 트랙 append를 직렬 처리한다. 봉인은 제한 FIFO로 넘겨 기존 sealer 하나가 검증·게시·등록한다. |

따라서 단순히 `sync()` 호출 두 개를 `with root_mutex` 아래에서 빼는 패치는 충분하지 않다. 단일 소비자가 여전히 fsync를 기다리고, 잘못 나누면 payload sync 사이에 생긴 삭제 의도 뒤 journal을 쓰게 된다. seal descriptor·복구 private 경로까지 포함한 아래 I1 정의도 기존의 “tracks 게시 0”보다 넓다. 이 확대를 C00 결정 항목으로 올린다.

CI 원문은 네트워크 조회 없이 로컬 `build/ci-evidence/g15-core3.13.log`를 읽었다. run 식별자·배경은 C00 보고를 인용한다. 원문 JSON에서 직접 확인한 값은 다음과 같다. 새로 벤치마크한 값이 아니다.

| 로그 줄 / G15-LAT-MEASURE | 입력 조건 | 소비자 root p99 / 최대 | 거부 블록 |
| --- | --- | --- | ---: |
| `:777` | 1트랙, seal 지연 0.2초, append sync 주입 5ms | 0.7931초 / 1.0436초 | 46 |
| `:1053` | 2트랙, seal·append 추가 지연 0 | 0.2131초 / 0.4986초 | 648 |

첫 행에는 **5ms 지연 주입**이 있다는 점을 보존한다. 이를 순수 디스크 단독 p99 측정으로 바꾸어 쓰지 않는다. G-P15b가 소비자 보유·거부를 측정값으로 바꾸고 구조·sealer·보존 판정을 유지했다는 사실은 그 문서 §17.2를 인용한다.

G-P08은 아직 push 전이므로 기준 코드와 섞지 않는다. 참고한 **검토 tree `bd060c4d`**에서는 `app/recording.py:344-379`가 기회성 건강 checkpoint를 DB에 기록하고, `:573-627`이 소비자·sealer ACK 뒤 `finish_capture_health`로 CLOSED를 기록한다. `storage/library.py:1340-1480`은 OPEN의 `UNKNOWN_TAIL`을 복구한다. 구현 착수 때 G-P08 최종 push의 API·줄·hash를 다시 고정한다.

## 3. 공통 불변식·선형화·잠금

### 3.1 I1의 정확한 범위

범위는 Library의 OS 소유 잠금으로 보호되는 **협조하는 단일 writer 프로세스**다. root RLock은 프로세스 간 잠금이 아니다. Library 없이 직접 쓰는 ChunkWriter의 기존 durable fallback은 유지하지만, 소유권을 무시하는 별도 프로세스/외부 파일 변경까지 원자적으로 봉쇄했다고 주장하지 않는다. 별도 Library의 동시 쓰기는 기존 소유 잠금으로 거부하고, 재시작 시험은 이전 소유 프로세스 종료를 확인한 뒤 진행한다.

삭제 의도 D는 canonical Library의 의도 게시/투영과 색인 갱신이 같은 root mutex 구간에서 다른 writer에 관측 가능해진 지점이다. DB-only·journal-only·tombstone·이력 확인 불가도 각각 차단 권위로 취급하며, G-P15 색인·기존 durable fallback을 재사용한다. 별도 journal 파서·전역 잠금·우회 권위를 만들지 않는다.

**D 뒤 새 미디어 쓰기·게시 0**: 그 세션에 payload·blocks.jsonl·descriptor 바이트 쓰기, 미디어 디렉터리 생성, rename 및 catalog 새 청크 등록을 시작하지 않는다. 삭제 자체의 journal/tombstone 기록은 이 금지의 대상이 아니다. D 전에 허용해 OS에 넘긴 바이트의 **fsync 완료는 새 논리 바이트 쓰기가 아니므로 허용**한다. 이를 금지하면 이미 시작한 I/O를 되돌릴 수 없고 정의 자체를 시험할 수 없다. “물리 디스크에 D 뒤 단 한 번도 write가 없음”으로 주장하지 않는다.

동기화가 D 뒤 끝나더라도 새 bundle·catalog·건강 CLOSED·durability DB 행을 게시하지 않는다. 삭제 재시도는 writer·sync handle·sealer의 종료 ACK까지 DELETE_PENDING으로 남는다. 완료 tombstone은 보존하며 늦은 완료·복구가 디렉터리나 세션 행을 다시 만들지 않는다.

### 3.2 순서 계약

- `PER_BLOCK`: root 안 **검사+payload write** → 밖 payload fsync → root 안 **재검사+journal write** → 밖 journal fsync → 해당 블록 완료. 사이에 D가 생기면 이후 write를 거부하고 staging의 검증 가능한 prefix만 남긴다. 첫 쓰기만 확인하고 다음 쓰기를 허용하지 않는다.
- `BATCHED`: root 안 **검사+payload write+journal write**를 하나의 짧은 구간에서 수행한다. 둘 사이 short write/오류면 완료로 세지 않고 실패를 전달한다. 밖에서 요청 cutoff의 payload fsync → journal fsync를 완료한다. journal이 먼저 캐시에 기록돼도 sync-confirmed prefix는 두 sync 완료 전 증가하지 않는다. 체크섬 prefix 검증은 유지한다.
- seal descriptor·복구 salvage도 **실제 생성·쓰기/rename과 같은 root 구간에서 권위를 확인**한다. 큰 read·checksum·PCM 변환·fsync·claim 대기는 밖이다. 복구 claim만으로 삭제 의도 검사를 생략하지 않는다. private `_append`·`_seal`을 호출하는 경로도 같은 write guard로 수렴시킨다.
- payload·journal·descriptor의 파일 fsync가 root mutex를 소유한 채 호출되는 횟수는 0이다. SQLite 메타데이터 commit의 기존 비용까지 제거했다고 주장하지 않는다.
- source callback·`submit`에서 파일/DB I/O나 동기화 대기를 하지 않는다. G-P08의 건강 기록용 thread도 추가하지 않는다.

### 3.3 writer 수명과 잠금 순서

17a의 같은 writer 작업 직렬화가 필요하면 **writer 전용 작업 잠금 → root → 짧은 registry 잠금** 순서만 허용한다. 삭제는 root에서 활성 여부만 보고 대기를 반환하며 writer 작업 잠금을 기다리지 않는다. root·`_writers_lock`·RecordingService `_gate`를 가진 채 fsync/다른 작업 ACK/queue 공간을 기다리지 않는다. 역순 재진입이 필요한 코드는 구현 전에 보고한다.

17b의 비동기 sync는 파일 offset을 바꾸지 않는 별도 고정 handle lease를 사용한다. pin/dup 성공·identity 확인은 짧게, 실제 fsync는 모든 제품 잠금 밖이다. append는 진행 중 fsync를 기다리지 않는다. close/abort는 새 요청을 막고, lease 종료를 root 밖에서 기다린다. 진행 중 lease가 하나라도 있으면 `has_active_writer`와 서비스 `is_live`는 참이다. timeout 후 파일을 닫거나 비활성으로 표시하지 않는다. callback·권위 함수 안에서 사용자 코드를 호출하거나 긴 잠금을 얻지 않는다.

## 4. 내구성 상태와 묶음 동기화

### 4.1 네 가지 사실을 분리한다

| 표식 | 뜻 | 뜻하지 않는 것 |
| --- | --- | --- |
| A 수락 | queue.offer가 True인 PCM frame | 파일 기록·sync 완료 |
| W 기록 | 해당 writer의 payload+journal 논리 쓰기 완료 | 전원 장애 내구성 |
| S 동기화 확인 | 고정 cutoff의 payload fsync 뒤 journal fsync가 모두 성공 | 장치 캐시·디렉터리 entry까지 전원 장애 무손실 |
| P 봉인/게시 | 기존 검증·descriptor sync·rename·등록 완료 | 미수락 블록 보존·하드웨어 고장 면역 |

cutoff의 단위는 트랙·epoch·writer별 frame/byte/sequence이며 서로 다른 트랙 시간을 더해 “몇 초 안전”으로 표시하지 않는다. A는 queue 수락 시점에 아는 **트랙·epoch 합계**이고, 아직 배정하지 않은 미래 chunk의 A를 만들어내지 않는다. 같은 트랙·epoch에서 중복 없는 writer별 prefix를 합한 S ≤ W ≤ A가 성립해야 한다. raw sequence 차이를 frame 수로 대신 쓰지 않는다. 중간 실패는 실제 byte/검증 prefix를 따로 남기며 실패한 append를 W 완료로 올리지 않는다. journal 없는 PCM 꼬리는 원본으로 자동 채택하지 않는다.

`SyncReceipt`는 version, capture_run_id, writer nonce, track/epoch/chunk ID, 요청 counter, cutoff sequence/frame/PCM bytes/journal offset를 가진 내부 typed 값이다. bool≠int, 음수·넘침·다른 run·잘못된 offset·S>W·역행을 거부한다. 생성 뒤 뒤늦게 증가한 W를 읽어 cutoff를 바꾸지 않는다. 권위 확인은 현재 canonical 상태로 하고, 일반 세션/건강 version 증가를 삭제 fence 변화로 오인하지 않는다. 이전 실행 receipt는 새 실행에서 사용할 수 없다.

### 4.2 17b의 제한과 ACK

- `N=100`, `T=1초`는 권고 preset이다. 트랙별 첫 dirty 시점에 deadline을 고정하며 매 append마다 deadline을 미루지 않는다. 무음/입력 정지 중에도 기존 소비자 제어 tick이 만료를 확인한다. fragment/epoch 경계는 유지한다.
- 기존 sealer가 sync와 seal을 처리한다. writer마다 **in-flight 1개 + 최신 미처리 cutoff 1개**만 유지하고 오래된 미처리 cutoff를 합친다. active writer ≤2, seal FIFO 4, in-flight seal 1이라는 기존 상한 위에 키별 요청 수 상한을 둔다. epoch를 무제한 키로 축적하지 않는다.
- seal 순서는 기존 FIFO를 지킨다. sync는 트랙별 공정 순서로 처리하고, seal 지속 유입으로 한 트랙의 동기화가 영구 기아가 되지 않게 한다. source/소비자는 fsync 완료를 기다리지 않으며 기존 제한 seal FIFO의 backpressure는 유지한다.
- 같은 writer에서 fsync와 append가 겹쳐도 receipt는 요청 cutoff까지만 인정한다. 더 많은 바이트가 함께 flush됐을 가능성을 안전 근거로 사용하지 않는다. 기존 `sync`가 무버퍼 파일이라는 조건을 확인하며, buffered wrapper를 끼운 경로는 허용하지 않는다. 기록 완료 W와 strict 호출 완료는 별도 관찰값이며, 기존 append의 성공 반환은 여전히 두 sync 뒤다.
- 소비자의 `_STOP`은 종료 요청일 뿐 완료 증거가 아니다. sealer는 seal FIFO·pending sync map·in-flight lease를 모두 처리한 뒤에만 종료 ACK를 낸다. 마지막 seal과 같은 writer의 미처리 sync를 합칠 때도 최종 cutoff 확인을 생략하지 않는다.
- seal은 최종 cutoff 전체 S 확인 뒤에만 descriptor를 확정·게시한다. 이미 S가 최종 cutoff와 같을 때만 중복 payload/journal sync를 생략할 수 있다. descriptor sync·검증을 없애지 않는다. handle pin과 capability의 writer 결속은 G-P15b 그대로 유지한다.
- pause·suspend·stop·실패 정리의 ACK는 모든 수락 PCM의 저장 작업, sync, sealer FIFO, 등록까지 포함한다. 시간 초과는 기존 `WRITER_ACK_PENDING`, OPEN/종료 확인 대기이며 정지 성공이나 CLOSED가 아니다. 새 run은 이전 종료 ACK 전 시작하지 않는다.
- sync 오류는 저장 실패로 전달하고 수락을 중단한다. `BATCHED`를 몰래 더 느슨한 모드로 바꾸거나 실패를 성공으로 무시하지 않는다. 저장 가능한 prefix와 원본 staging을 보존한다.

### 4.3 손실 창과 사용자 표시

묶음 모드는 append 반환 의미가 달라진다. `PER_BLOCK` 완료는 두 sync 확인 뒤이고, `BATCHED` 완료는 W까지다. 내부 반환은 typed append 결과 또는 별도 S snapshot으로 구분하며 기존 직접 호출자는 기본 PER_BLOCK 의미를 유지한다.

전원 장애의 미확인 suffix는 **해당 트랙 A−S**다. 여기에는 입력 queue, 기록 대기, 진행 중 sync, seal FIFO가 포함된다. `T`만으로 제한되지 않으며, 벽시계 지연과 오디오 길이도 구분한다. 확인된 최대 sequence/frames와 마지막 성공 이후 경과 시간을 실제 관측값으로 표시한다. 누적 정보·legacy가 불명이면 `미상`이다. “최대 1초만 유실”이나 fsync 성공만으로 “전원 장애 안전”을 표시하지 않는다.

권고 UI 문구:

- 기본: `블록별 동기화 — 저장장치 전원 장애 무손실을 보장하지 않습니다.`
- 묶음 선택 확인: `묶음 동기화를 사용하면 전송 대기·동기화 중인 원본이 비정상 종료나 전원 장애에서 유실될 수 있습니다. 1초는 요청 간격이며 유실 상한이 아닙니다.` 기본 No, Esc 취소.
- 진행: `기록됨 / 동기화 확인 대기`, `트랙별 마지막 동기화 확인`, `동기화 지연 — 종료 확인 전 앱을 닫지 마세요`. 파일 write 뒤 곧바로 `안전하게 저장됨`이라고 표시하지 않는다.
- 정상 종료: 기존 파일 완료와 별도로 `동기화·봉인·등록 완료`를 표시할 수 있다. 전원 장애 내구성 보장 문구는 사용하지 않는다.

선택은 새 capture run snapshot에만 적용한다. AI `config_key`와 무관하며 실시간 청크 재전송을 일으키지 않는다. UI는 진행 중 정책 변경을 다음 실행으로 명시하고, 정책/내구성 확인을 녹음 동의·원격 동의와 혼동하지 않는다. 이 단위는 G-P16 일반 설정 파일을 수정하지 않는다.

## 5. G-P08 건강·복구, 스키마와 다른 단위

- `QUEUE_DROP`은 실제 offer 거부 frame을 한 번만 계상한다. sync 대기 중인 수락 PCM은 실제 유실로 확정하지 않는다. 원래의 app queue 유실·장치 보고 유실도 합산하지 않는다.
- G-P08의 영속 건강 checkpoint는 관측 누계이지 오디오 파일의 S가 아니다. 건강 A가 앞섰다고 오디오 S를 올리거나, S에 맞추려고 이미 알려진 유실 누계를 깎지 않는다. 기존 건강 payload의 닫힌 schema_version=2는 유지한다.
- 권고 additive 표 **`capture_durability_watermarks` 1개**: session/run/track/epoch/chunk 복합 identity, policy version/mode/N/T, request counter, S cutoff와 상태를 보관한다. 세션 FK cascade를 사용한다. sync receipt를 건강 checkpoint와 같은 짧은 metadata transaction에서 CAS 반영할 수 있지만, 원시 payload에는 임의 필드를 넣지 않는다. 정본은 현재 파일 검증과 확인된 receipt이며 DB 숫자만으로 flush 사실을 만들어내지 않는다.
- Library 기록 API는 현재 run·expected_health_version·삭제 권위를 확인한다. stale 건강 version이면 새 snapshot에 같은 확인 receipt를 다시 연결할 수 있으나 cutoff를 늘리지 않는다. D 뒤 late receipt는 DB 게시하지 않는다. callback/submit은 DB를 쓰지 않는다.
- OPEN 비정상 종료의 `UNKNOWN_TAIL`은 계속 `lost_frames=None`으로 남는다. **건강 누계의 마지막 영속 prefix**와 **오디오의 마지막 sync-confirmed prefix**를 상세 결과에서 별도로 보여준다. S 이후 바이트가 복구 검증을 통과하면 채택할 수 있으나, 그 전체가 사전에 동기화 확인됐다고 소급하지 않는다. 재복구 멱등·원본 bytes 불변을 유지한다.
- clean CLOSED는 모든 수락 저장 작업과 최종 S·등록 ACK 뒤에만 기록한다. 누락/손상/미래 version receipt는 `DURABILITY_UNKNOWN` 표시와 판정 보류이며 0손실이나 빈 완료로 해석하지 않는다. legacy 데이터에는 새 확인 이력을 발명하지 않는다. 표시 상태를 G-P07 Job 오류 코드 표에 자동 등록하지 않는다.
- **G-P09 인계**: 위 표, component `capture_durability` version 1, policy/receipt의 역사성, 구버전 reader 차단 필요를 형식 2 구성요소 목록에 추가한다. 실제 구버전 앱이 새 동기화 의미를 읽고 쓸 수 없으면 maintenance로만 명시 전환한다. 미래 버전 보존·부분 migration 재개는 G-P09가 소유한다. backup의 imported receipt는 실행 권한이 아니며 새 실행에서 재사용하지 않는다. 삭제 journal·tombstone 정본을 그대로 보존한다.
- 새 표의 추가는 **G-P09a의 명시 migration 프레임을 사용하는 안**을 권고한다. 형식 1 DB에 표만 추가했다고 구버전 앱 차단이 생겼다고 주장하지 않는다. G-P09a가 아직 없으면 17a를 먼저 닫고, DB가 필요한 17b는 그 프레임과 component 목록 승계 뒤 시작한다. C00이 다른 순서를 원하면 실제 구버전 열기/쓰기를 포함한 호환 oracle와 버전 전략을 재승인받는다.
- **G-P10 인계**: export의 health 참조와 별도로 `capture-durability.jsonl` 상세 및 digest/row/version 참조를 남기는 additive 안이다. 미지원 필드를 기존 reader가 거부한다면 버전 2 조정은 C00과 먼저 고정한다. G-P10의 최종 export marker·분할 frame 합·reader ACK 규칙을 유지한다. export/backup은 active sync가 있으면 live/종료 대기로 거부한다.
- 구현 순서는 **G-P08 push → G-P17a → 제품 선택 승인 및 G-P09a migration 프레임 승계 → G-P17b**를 제안한다. G-P09와 G-P10이 먼저 구현에 들어가면 표/내보내기 변경을 다시 인계하고 공유 파일을 직렬화한다. G-P11b의 inference·models·runner·AI bridge는 이 계약의 쓰기 범위에 없다.

## 6. 입력 분할과 계획 분모

정책, identity, 삭제 권위, 오류 입력은 거부 행도 feasible 집합에 포함한다. 아래는 서로 다른 case ID family의 **합집합 분모 2,608행**이다. 모든 차원을 한 번에 곱한 전수나 pairwise coverage라고 부르지 않는다. 각 family의 제한 밖 교차 조합은 미검증이다. 구현 함수·생성기와 별개로 아래 산식으로 기대 ID 집합을 만든다.

| ID family / 범위 | 독립 구성 | F | 17a | 17b |
| --- | --- | ---: | ---: | ---: |
| P / `G17-P-001..020` | 정책/확인 20개 고정 행: 기본·명시 batch·취소·실행 중 변경·옛 정책·미래/손상/타입·상수 경계 | 20 | 0 | 20 |
| W / `G17-W-001..064` | 모드2 × writer 관찰상태8 × 명령4(append/sync/seal/abort) | 64 | 32 | 32 |
| D / `G17-D-001..120` | 모드2 × 미디어 쓰기4 × 차단 권위5 × W/S 대비 권위 변화3위치 | 120 | 60 | 60 |
| HB / `G17-HB-001..066` | strict 사슬6위치 + batch 사슬5위치, 각각 트랙수2 × 삭제권위3 | 66 | 36 | 30 |
| C / `G17-C-001..156` | 모드2 × 트랙수2 × crash checkpoint13 × persistence 모사3 | 156 | 78 | 78 |
| F / `G17-F-001..104` | 모드2 × 트랙수2 × 아래 operation별 결함26 | 104 | 42 | 62 |
| T / `G17-T-001..100` | batch만: 트랙수2 × dirty 블록수5 × 경과시각5 × 진행/입력정지2 | 100 | 0 | 100 |
| L / `G17-L-001..112` | 모드2 × 트랙수2 × 종료/제어 사건7 × 미완료 종류4 | 112 | 56 | 56 |
| H / `G17-H-001..072` | S/W 관계4 × 건강 checkpoint binding3 × OPEN/CLOSED/UNCLEAN3 × 트랙수2 | 72 | 0 | 72 |
| Q / `G17-Q-001..120` | **가상 시각 모델** 모드2 × 트랙수2 × sync 지연5 × 지연분포3 × 무부하/경쟁2 | 120 | 60 | 60 |
| U / `G17-U-001..030` | 모드2 × 표시상태5 × live/복구/export3 | 30 | 0 | 30 |
| M / `G17-M-0001..1600` | 모드2 × 트랙수2 × 길이0~3, alphabet7의 모든 시도열: 4×(1+7+49+343) | 1,600 | 800 | 800 |
| V / `G17-V-001..032` | receipt 타입·identity·counter·cutoff·역행·중복·충돌 32개 고정 음성/경계 행 | 32 | 0 | 32 |
| B / `G17-B-001..012` | legacy/정상/미래/손상4 × 열기/복구/export3 | 12 | 0 | 12 |
| **CI 의미 행 합계** | | **2,608** | **1,164** | **1,444** |

분할의 구체 정의:

- W 상태8은 NEW, OPEN_IDLE, OPEN_SYNCING, SEALING_SYNCING, SEALED_WAIT_REGISTER, PUBLISHED_RELEASED, ABORTED_DRAINING, FAILED_DRAINING이다. strict와 batch의 append 허용/대기 차이를 손으로 쓴 표에 넣는다. terminal abort는 멱등, pending handle은 활성이다. 명령이 불법인 상태도 거부 행으로 남긴다.
- D의 쓰기4는 capture payload, capture journal, seal descriptor 생성/쓰기, recovery private media write다. 권위5는 DB-only, journal-only, DB+journal, terminal tombstone, 확인 불가다. 위치3은 `권위<W`, `W<권위<S`, `W<S<권위`이며 W는 검사와 바이트 쓰기가 한 mutex 구간인 사건이다. 검사와 write 사이에 D를 끼우는 실행 불가능 조합은 만들지 않고, 둘을 분리하는 mutant로 그 보호를 검증한다.
- HB strict의 chain은 WP<SP<WJ<SJ<C(완료 receipt), D의 삽입 위치6개다. batch는 (WP,WJ) 원자 구간<SP<SJ<C로 D 위치5개다. 무제약 두 chain형 syntactic 12위치 중 batch WP/WJ 사이 1위치는 같은 mutex 때문에 불가능하여 제외한다. 결과는 (6+5)×2×3=66이다. 삭제권위3은 정상 의도, DB-only, tombstone이다. D family가 나머지 권위도 확인한다.
- F의 26은 쓰기3(payload/journal/descriptor)×4(short-write 후 완성/0 반환/ENOSPC/EBADF)=12, sync3×3(EIO/EBADF/지연 ACK timeout)=9, handle lease 획득·해제 실패2, receipt DB busy·commit 실패·손상3의 합이다. fsync에 short write를 주입하는 불가능한 직적을 분모로 쓰지 않는다.
- F의 17a는 strict의 쓰기·sync 21종×트랙수2=42행이다. 17b가 도입하는 lease/receipt DB 5종은 strict의 10행도 17b로 미룬다. 따라서 17b는 batch 52행+이 strict 10행=62행이며, 아직 없는 API를 17a에서 시험한 것으로 세지 않는다.
- T의 dirty 수는 {0,N−1,N,N+1,2N+1}, 시각은 {0,T−ε,T,T+ε,2T}, N=100·ε=1ns다. strict의 즉시 동기화는 W/L/M에서 확인한다. T는 시간 요청이 idle에서도 발생하고 연속 입력에 의해 deadline이 밀리지 않는지를 검증한다.
- L의 사건7은 pause/stop/부분 시작 실패/restart/suspend/delete/sealer 실패다. 미완료4는 없음/현재 dirty/진행 sync/seal FIFO다. 첫 source가 PCM을 준 뒤 시작 실패하는 fixture로 실패+dirty 행도 실제 구성한다.
- H의 S/W는 S=0, 0<S<W, S=W, S>W(거부)다. 건강 binding은 같은 run의 이전 version(재조회·CAS), 같은 version, 다른 run/epoch를 섞은 참조(거부)다. **같은 run에서 건강 A가 S보다 앞선 정상 관측을 거부하지 않는다.** identity 불일치를 거부해야 하는 행을 feasible에서 빼지 않는다.
- Q의 지연은 {0,50,100,200,500ms}, 분포는 모든 호출/10호출마다 한 번/첫 호출만이다. 가상 scheduler의 event log로 큐·FIFO·cutoff를 계산한다. 실제 디스크 성능 시험으로 집계하지 않는다.
- M의 alphabet은 accept/append/sync_ok/sync_error/delete/seal/close다. illegal 명령도 명시 거부로 관찰한다. 길이3을 넘는 trace의 정당성은 이 분모로 보장하지 않는다. 더 긴 trace는 seed를 남긴 속성 보강으로 분리한다.
- Q/M은 독립 모델끼리만 대조하는 시험이 아니다. 실제 제품 객체를 fake clock·제어 가능한 파일 I/O로 구동하고 그 결과/trace를 손으로 정한 모델과 비교한다. 정상 모델만 실행한 수, 수집만 된 node, 모델에만 주입한 mutation을 제품 검증 수로 세지 않는다.

추가 실시간 측정은 아래 **E 20행**, Windows 하드웨어/백신은 **X 16행**으로 분리한다. 따라서 전체 계획 목록은 CI 의미 2,608 + 측정20 + 외부16 = **2,644개 식별 행**이지만, 서로 다른 수락 의미를 가진 세 집합을 하나의 PASS 비율로 합치지 않는다. 아직 실행된 행은 0이다.

### 6.1 고정 P20·V32와 상태 oracle

정책 DTO의 공개 preset은 version 1의 `PER_BLOCK(N=1,T=0)`과 `BATCHED(N=100,T=1_000_000_000ns)`뿐이다. 사용자에게 임의 N/T 입력란을 만들지 않는다. 타입과 지원 preset을 직접 검증하며, 잘못된 입력을 다른 모드로 자동 변환하지 않는다. UI의 기존 기본 PER_BLOCK 선택은 유지하고 오류를 표시한다.

P의 손으로 쓴 20행은 다음과 같다. 숫자 순서가 ID suffix다.

| ID | 입력/사건 | 독립 기대 |
| --- | --- | --- |
| P01 | 선택 없는 새 실행 | PER_BLOCK |
| P02 | PER_BLOCK 명시 선택 | 두 sync 완료 뒤 append 완료 |
| P03 | BATCHED·명시 Yes | 해당 새 run만 batch |
| P04 | BATCHED·No | 기존 PER_BLOCK 선택 유지, batch 시작 0 |
| P05 | BATCHED·Esc | P04와 같은 취소 결과 |
| P06 | 확인 없는 batch 실행 준비 | batch 거부, 자동 동의 0 |
| P07 | 모르는 mode 문자열 | DTO 거부·UI 오류 |
| P08 | 미래 policy version | 기존 값 보존·사용 거부 |
| P09 | bool version | 타입 거부 |
| P10 | mode 누락 | DTO 거부 |
| P11 | batch N=0 | preset 거부 |
| P12 | batch N=True | 타입 거부 |
| P13 | batch N=99 | 미지원 preset 거부 |
| P14 | batch T=0 | preset 거부 |
| P15 | batch T<0 | 범위 거부 |
| P16 | batch T=True | 타입 거부 |
| P17 | 활성 run에서 정책 바꿈 | 현재 snapshot 불변·다음 실행으로 명시 |
| P18 | PAUSED 뒤 새 run에 확인된 변경 | 새 run snapshot만 변경 |
| P19 | 복원/이전 실행의 batch 기록 | 이번 실행의 확인으로 승계하지 않음 |
| P20 | sync 오류 후 정책 처리 | 저장 실패, 묵시 fallback/성공 0 |

V32의 고정 입력은 다음 목록 순서다. 기준은 검증된 같은 run의 receipt이며 한 원인만 바꾼다. V14만 동일 receipt의 멱등 수락이고 나머지는 거부·기존 S 불변이다. V13은 낮은 요청 counter, V27~29는 더 높은 counter에 줄어든 cutoff를 넣어 원인을 분리한다.

1. run 누락, 2. 다른 run, 3. writer nonce 누락, 4. 다른 writer nonce, 5. 다른 track, 6. 다른 epoch, 7. 다른 chunk, 8. 미래 receipt version,
9. bool version, 10. bool counter, 11. 음수 counter, 12. counter가 signed 64-bit 상한 초과, 13. 낮은 counter, 14. 같은 counter·같은 cutoff의 중복,
15. 같은 counter·다른 cutoff, 16. bool sequence, 17. 음수 sequence, 18. bool frame 수, 19. 음수 frame 수, 20. bool byte 수, 21. 음수 byte 수, 22. bool journal offset,
23. 음수 journal offset, 24. 요청 snapshot W보다 큰 cutoff, 25. frame/byte 크기 불일치, 26. 그 writer snapshot에 없는 sequence, 27. 새 counter의 frame 역행, 28. 새 counter의 byte 역행,
29. 새 counter의 journal offset 역행, 30. 다른 policy snapshot, 31. 알 수 없는 추가 필드, 32. DTO 대신 None.

W의 8상태×4명령은 아래 표를 양 모드에서 사용하되 OPEN_SYNCING의 append만 모드에 따라 다르다. `대기`는 root/registry/gate 밖 대기이며 barrier로 확인하고 실제 timeout으로 합격을 대신하지 않는다.

| 상태 | append | request_sync | seal | abort |
| --- | --- | --- | --- | --- |
| NEW | 유효 첫 블록 기록 | 빈 상태 no-op | 빈 청크 거부 | 멱등 닫기 |
| OPEN_IDLE | 해당 모드로 진행 | 현재 cutoff 요청 | 최종 cutoff 확인 뒤 게시 | 새 입력 금지·닫기 |
| OPEN_SYNCING | strict: 같은 writer 순서 대기 / batch: 새 쓰기 허용 | 최신 요청 하나로 합침 | 기존 lease 완료 뒤 최종 cutoff | 종료 요청 후 lease ACK 대기 |
| SEALING_SYNCING | 거부 | 이미 진행 중인 최종 cut 재사용 | 중복 seal 거부 | 게시 금지·lease ACK 대기 |
| SEALED_WAIT_REGISTER | 거부 | 확인된 최종 cut 멱등 | 중복 seal 거부 | 등록 포기·capability 해제, 원본 bundle은 복구 대상으로 보존 |
| PUBLISHED_RELEASED | 거부 | 최종 확인 멱등 | 중복 seal 거부 | 멱등 닫기·기존 bytes 불변 |
| ABORTED_DRAINING | 거부 | 새 요청 거부 | 거부 | ACK 전 활성·ACK 뒤 닫힘 |
| FAILED_DRAINING | 거부 | 새 요청 거부 | 거부 | 원 오류 보존·ACK 뒤 닫힘 |

`OPEN_SYNCING`의 strict 행은 비동기 모드 허용이 아니라 다른 호출자가 같은 writer의 진행 중 fsync와 겹치는 직접 호출 시험이다. 한 소유자만 사용하던 기존 RecordingService의 정상 append 흐름은 그대로다.

## 7. 독립 oracle와 크래시 checkpoint

### 7.1 공통 oracle

시험은 production `scan_prefix`/receipt 산식/전이표를 import해 기대값을 만들지 않는다. 합성 블록의 고유 바이트 패턴·수기 sequence 목록과 독립 SHA-256으로 원본을 비교한다. 제품 복구 함수를 실제 동작으로 호출할 수 있으나, 기대 prefix는 fault 시점에 시험이 정한 허용 목록이다.

- D/HB: D 뒤 권위 대상 세션의 신규 write/create/rename/catalog insert trace 0, 기존 바이트 불변, 최종 삭제·tombstone 유지·재복구 부활 0. D 전 write의 뒤늦은 sync는 허용하되 새 바이트와 구분한다. 무관한 세션은 계속 녹음한다.
- byte 회계: 제출=수락+offer 거부, `QUEUE_DROP`=실제 거부 frame 1회, 정상 drain 뒤 저장 frame=수락 frame. 실패/kill은 저장된 검증 prefix와 미확인 suffix를 나누며 이를 정상 drain의 등식으로 숨기지 않는다.
- receipt: 독립 event log의 **실제로 완료된 payload/journal sync pair cutoff**까지만 S가 간다. 최신 W/A를 복사한 값은 거부한다. 다른 트랙·epoch·run을 합산하거나 counter를 두 번 더하지 않는다.
- 상태: 활성 handle/FIFO가 있으면 종료 ACK·CLOSED·삭제 완료 0. reader·복구·내보내기 live 거부, 뒤늦은 완료는 terminal/새 run 불변이다.
- 메모리: queue/FIFO 및 writer별 pending 요청 수가 고정 상한 이하다. 재료를 조용히 버리거나 큐를 무제한 늘려 성능 목표를 맞추지 않는다.

### 7.2 C family의 13지점

| 지점 | checkpoint | 기대의 핵심 |
| --- | --- | --- |
| C01 | offer 수락 뒤 consume 전 | queue의 수락을 디스크 저장으로 세지 않음, health tail 미상 |
| C02 | payload short write 중 | journal과 일치하는 이전 prefix만 채택 |
| C03 | payload write 뒤 sync 전 | 새 S 없음; 살아남은 원문 중 검증 prefix만 채택 |
| C04 | payload sync 뒤 | strict는 새 journal 전, batch는 journal이 이미 기록됨; mode별 고정 목록 비교 |
| C05 | journal partial write 중 | 잘린 JSONL 이후 채택 0 |
| C06 | journal write 완료·journal sync 전 | 새 S를 주장하지 않음 |
| C07 | 두 sync 완료·DB receipt 전 | 실제 바이트로 복구할 수 있으나 DB에서 확인 이력을 발명하지 않음 |
| C08 | receipt+health checkpoint commit 뒤 | 같은 cutoff 유지, 재복구 멱등 |
| C09 | seal FIFO 전달·처리 전 | staging 검증 prefix 유지, 미게시를 완료로 표시하지 않음 |
| C10 | descriptor write 뒤 sync 전 | 손상/누락 descriptor를 완성 증거로 삼지 않음 |
| C11 | rename 뒤 catalog 전 | 검증된 고아 bundle만 채택, 중복 0 |
| C12 | catalog commit 뒤 writer release 전 | catalog와 실제 bytes 일치, 재등록 중복 0 |
| C13 | source·저장 작업 ACK 뒤 health CLOSED 전 | 데이터는 확인된 범위로 남고 OPEN 복구 표식은 과소 추정하지 않음 |

각 지점을 모드2·트랙수2·persistence3으로 구성한다. persistence는 (i) 실제 소유 subprocess kill, OS cache는 남음, (ii) 시험 가상 파일의 sync 완료 prefix만 남김, (iii) 미확인 suffix의 tear/reorder다. (ii)(iii)는 **모의 전원 장애**이지 실제 전원 차단이 아니다. 실제 kill은 52행, 모델 모사는 104행이다. READY marker는 임시 파일+원자 replace 뒤 부모가 확인하고 kill한다. PID 소유·자식 import 경로·기한·재시작 권위 해제를 검증하며 fixture 부분 읽기나 timeout을 제품 결함 검출로 세지 않는다.

실제 전원 장애에서 directory entry·SQLite·장치 cache가 서로 어느 순서로 남는지는 외부 게이트다. 이 문서의 가상 persistence 모델은 그런 장치 보장을 새로 만들어내지 않는다.

## 8. 측정 계획과 수락 기준

### 8.1 E: 느린 디스크 모사 20행

`G17-E-01..20` = 모드2 × 트랙수2 × fsync 추가 지연 {0,50,100,200,500ms}. 합성 48kHz·10ms PCM, 기존 queue 크기·chunk_frames·FIFO 설정을 고정하고, epoch 시작·source 준비·recording cutoff를 barrier로 맞춘다. 각 행 기본 6초 입력 창에 같은 입력을 전/후 구현에 공급한다. 지연 injector는 어느 FD/단계의 호출인지 기록한다. sealer/descriptor까지 지연시키는 조건과 append sync만 지연시키는 조건을 섞지 않는다. **이 20행은 입력 창의 모든 미디어 fsync에 동일 지연**을 주는 안이며, append만 지연하는 기존 G15 수치는 별도 비교 이력이다.

입력 cutoff 뒤에는 새로 시작하는 fsync의 **인공 지연만 해제**하고 정상 디스크 조건으로 accepted PCM을 전부 drain한다. 이미 시작한 지연 호출은 그 지연을 끝낸다. 입력 창 측정과 drain 측정은 따로 출력한다. 이는 500ms 지연이 지속되는 장치에서 종료까지 6초라는 시험이 아니다. 지연을 유지하면 PER_BLOCK의 수백 pending 블록 정리에 행당 수분이 필요할 수 있으므로, 그 지속 지연·종료 시험은 Q의 가상 시각 모델과 별도 확대 측정에 맡긴다. 관측 script의 기한 초과는 INCOMPLETE이며, 수락 데이터를 버려서 정상 종료 PASS로 바꾸지 않는다.

CI에서는 거부·append p50/p95/p99/최장·root 보유·sync ACK 지연·A−S·queue/FIFO 고점·실제 sync 호출 수·저장 frame·thread별 작업을 출력한다. 분모는 offered **블록/프레임** 및 실제 호출 수를 함께 기록하며 처리한 블록만으로 p99를 좋게 만들지 않는다. 거부 0과 소비자 write 비용은 **측정값**이다. 다음 구조/보존은 CI에서도 hard assertion이다.

1. append/미디어 sync의 root 소유 0, BATCHED 소비자의 fsync/receipt 대기 0. 허용된 bounded FIFO backpressure는 구분한다.
2. root 안 journal 전체 열거/본문 읽기·hash·verify·ACK 기다림 0. G-P15 색인 및 GC-P02 관리 구조 판정을 보존한다.
3. D 뒤 신규 쓰기/게시 0, 정상 drain의 수락 bytes 전량 보존·회계 일치, 제한 queue/FIFO/pending 상한, thread/handle 누수 0.
4. 기존 G-P15 sealer 0.5초 기준을 임의 완화하지 않는다. 그 기준은 제어된 file I/O 지연까지 포함하는 행과 분리한다. 주입 fsync 때문에 실제 wall time이 넘는 경우 구조·역할 구분으로 설명하고 C00 승인 없이 예전 단언을 삭제하지 않는다.

목표는 지원 로컬 저장장치에서 1·2트랙 모두 거부 0이다. 다만 **500ms fsync의 2트랙 지속 0거부는 이 설계만으로 보장할 수 없다**. 기본 2초 청크에서 2트랙은 초당 약 1청크이고 seal마다 미확인 PCM/journal/descriptor 3회가 모두 필요하면 serial service demand만 1.5초/초다. 동기화 중복 제거를 해도 실제 장치 처리량에 상한이 있다. queue 확대·자동 chunk 길이 변경으로 이를 숨기지 않는다. 실패 행은 sync 대기 원인/CPU 검증/실제 write/등록 commit을 분해하여 C00이 목표 미달로 판단한다. 안전 불변식 PASS만으로 성능 목표 완료를 승인하지 않는다.

권고 시간 게이트: 신규 pytest 파일 합계 **60초 목표**, 초과하면 행을 줄이기 전에 측정과 최적화/예산안을 보고한다. E는 별도 측정 script로 운영하며 기본 6초×20=120초 + setup/drain을 고려해 **CI 관측 step 300초 예산 요청**이다. 이를 pytest 분모에서 실행한 것으로 기록하지 않는다. 60초 이상 장기 주입·동시 부하는 별도 확대 측정이며 여기의 6초 창으로 지속 처리량을 증명하지 않는다.

### 8.2 X: 실제 Windows 저장장치/백신 외부 게이트 16행

`G17-X-01..16` = 로컬 SSD/HDD2 × 기존 백신의 평상시 실시간 검사/사용자가 승인한 해당 시험 폴더 검사 병행2 × 트랙수2 × 모드2. 합성 PCM으로 **각 10분**, 먼저 장치·파일시스템·여유 공간·전원 정책·백신 상태를 기록한다. 실제 캡처나 모델이 없어도 가능한 저장 계층 시험이며, 지금은 실행하지 않는다. 백신 끄기·예외 추가·설치·네트워크/SMB 경로 지원 확대는 하지 않는다. 외부 승인 없이 다른 디렉터리나 실제 사용자 미디어를 검사하지 않는다.

0거부를 목표로 같은 회계·불변식과 지연 분포를 남긴다. 특정 HDD/백신에서 미달하면 지원 조건·권장 설정·내구성 선택의 제품 결정을 요청한다. 실제 전원 차단은 별도 장비·사용자 승인 후 수행하는 추가 게이트이며 X16에도 실행 완료로 포함하지 않는다.

## 9. 기존 시험·정본과의 관계

| 기존 근거 | 이번 검증의 관계 |
| --- | --- |
| `tests/unit/test_storage.py`의 `test_p11_late_writer_is_fenced_after_delete`, `test_delete_and_recover_do_not_race_live_writer` | D/HB의 기존 삭제·복구 경계. 더 넓은 미디어 write trace는 신규 시험에서 추가한다. |
| `tests/integration/test_process_crash.py::test_actual_process_kill_preserves_exact_prefix` | 기본 PER_BLOCK 직접 호출 호환·기존 4지점 유지. 모의 전원 장애 결과로 바꾸지 않는다. |
| `tests/property/test_pcm_storage_oracle.py`, `tests/integration/test_storage_integrity.py` | checksum·검증 prefix·원본 bytes 유지. |
| `tests/unit/test_seal_phases.py`, `tests/integration/test_seal_mutex.py` | G15 봉인 capability·writer 활성·FIFO 실패 정리·구조·회계 유지. 소비자 보유/거부의 기존 측정값을 새 성능 PASS로 재해석하지 않는다. |
| `tests/integration/test_unfinished_recovery.py::test_management_never_blocks_another_recording`, `test_repeated_live_refusals_preserve_every_recording_block` | 관리 작업과 녹음의 독립, accepted bytes 보존. 환경 부하의 writer 지연을 관리 작업 실패로 오인하지 않는다. |
| G-P05 pending/retry 및 GC-P02 구조 시험 | 삭제 의도 먼저·활성 owner 보류·tombstone 영구·root 밖 열거/제거 유지. |
| G-P08 `tests/integration/test_health_crash.py`·`test_track_health.py`, `tests/ui/test_track_health_ui.py` | 건강 checkpoint·미상 tail·ACK·실제 offer 유실 계상 유지. 새 오디오 S 표식과 혼동하는 mutant를 추가한다. |
| architecture의 저장과 복구·시간과 오디오 계약, validation-plan의 fault injector 지침 | 파일 완료와 전원 장애 내구성 구별. 정책을 바꾸면 C00이 정본 문구를 별도 반영한다. |

위 node의 존재·최종 파라미터는 착수 시 새 기준으로 재대조한다. 기존 fixture가 실제로 실패하면 해당 실패·최소 diff를 C00에게 보고하고 범위 승인을 받는다. 지금 승인되지 않은 기존 시험을 고치지 않는다.

## 10. mutation 계획 32개

정상본 PASS 뒤 pyproject·src·tests·scripts를 함께 TEMP로 복사하고 `PYTHONPATH=사본/src` 및 자식 import를 확인한다. 한 번에 하나만 변형한다. 목표 단언 실패만 KILLED이며 import/수집/permission/timeout은 INVALID다. 아래 M ID는 경우의 수 M family와 혼동하지 않도록 실행 기록에서 `G17-MUT-xx`를 사용한다.

| MUT | 의도적 결함 | 독립 검출 표적 |
| --- | --- | --- |
| 01 | fsync를 root mutex 안으로 회귀 | root 소유를 감시하는 구조 oracle |
| 02 | capture write의 삭제 검사 제거 | D의 D<W write trace 0 |
| 03 | strict journal 재검사 제거 | HB의 SP<D<WJ |
| 04 | descriptor 쓰기 guard 제거 | D-seal descriptor |
| 05 | recovery private writer guard 제거 | D-recovery / 원본 부활 |
| 06 | 진행 sync 중 active 거짓 | delete pending·활성 lease |
| 07 | fsync 끝 전 handle 해제 | F lease·L abort/stop |
| 08 | root를 쥔 채 writer ACK 기다림 | 잠금 순서 spy의 직접 단언, timeout으로 세지 않음 |
| 09 | payload sync 생략 | 독립 sync event log·C persistence |
| 10 | journal sync를 payload보다 먼저 | event 순서 oracle |
| 11 | journal sync 완료 전에 S 증가 | C06 / H |
| 12 | snapshot cutoff 대신 최신 W로 receipt | sync 중 append HB·V |
| 13 | A를 S로 복사 | C01 / H |
| 14 | 다른 run/epoch receipt 허용 | V identity·L restart |
| 15 | bool을 counter/frame으로 허용 | V 타입 음성 |
| 16 | 중복 receipt의 frame을 재합산 | V 중복·M 명령열 |
| 17 | pending sync를 무제한 append | Q/L bounded key·요청 수 |
| 18 | N 경계를 >로 바꿈 | T의 N 정확 경계 |
| 19 | idle 시간 trigger 제거 | T 입력정지·L pause |
| 20 | append마다 deadline 재설정 | T 연속 입력 |
| 21 | batch 소비자가 sync 완료 대기 | thread 역할/대기 spy |
| 22 | 최종 S 전 seal 게시 | C/H의 S<W 게시 차단 |
| 23 | worker/lease ACK 전 종료 성공 | L 지연 ACK·C13 |
| 24 | 건강 CLOSED를 source/저장 ACK 전에 | G08 회귀·L/H |
| 25 | fsync EIO 뒤 계속 수락 | F·INTERRUPTED·원본 prefix |
| 26 | queue 거부와 backend 보고 이중 합산 | Q byte 회계·G08 |
| 27 | UNKNOWN_TAIL None을 0으로 | C/H·복구 표시 |
| 28 | 건강 checkpoint의 A를 오디오 S로 취급 | H 혼합 cut |
| 29 | recovery가 미확인 tail/기존 bytes 덮어씀 | C 독립 bytes/checksum |
| 30 | legacy에 동기화 확인 이력 생성 | B legacy 표시·원본 불변 |
| 31 | W 시점에 안전 저장 완료 표시 | U 실제 UI/출력 assertion |
| 32 | 확인 없이 기본 batch/자동 fallback | P 취소·기본 No·실행 snapshot |

## 11. 제안 쓰기 범위·push 경계

제품 결정과 구현 승인을 받기 전에는 아래 파일을 수정하지 않는다. G-P08 최종 push와 G-P11b 작업 범위를 확인하고 기준/hash를 다시 고정한다. shared file을 동시에 수정하지 않는다.

**G-P17a — 8파일 / CI 의미 1,164행 / MUT 01~10 중 해당 경계와 strict 관련 표적을 먼저 실행**

1. `src/recoryn/storage/chunks.py`: guarded 미디어 쓰기, 밖 sync, writer 수명·동일 writer 직렬화.
2. `src/recoryn/storage/_coordination.py`: 기존 권위 API 계약/연결의 최소 보강. 색인·journal 정본을 복제하지 않음.
3. `src/recoryn/storage/library.py`: private salvage 경로의 공통 guard 연결만; G-P08·G-P05·G-P07 권위 보존.
4. `tests/unit/test_append_durability.py`(신규): writer 상태·동기화 순서 oracle.
5. `tests/integration/test_append_fencing.py`(신규): D/HB 및 삭제 부활 경계.
6. `tests/integration/test_append_durability_crash.py`(신규): C/F의 strict 행.
7. `tests/property/test_append_durability_model.py`(신규): strict M/Q 모델 행.
8. `docs/testing/g17-append-durability-cases.md`: 실제 분모/관측/결과.

**G-P17b — 19파일(17a와 8개 공유) / 새 의미 1,444행 + 17a 회귀 / MUT 32개 전체**

위 17a의 8파일과 아래 11파일이다. 전체 합집합은 **19파일**이다. strict용 기존 행을 보존하면서 같은 시험 파일에 batch 행을 추가한다.

1. `src/recoryn/domain/durability.py`(신규): policy·cutoff·receipt typed 값과 검증.
2. `src/recoryn/app/recording.py`: W/S 분리, 기존 sealer의 bounded sync 요청·ACK·건강 연결.
3. `src/recoryn/app/desktop.py`: 실행 policy snapshot 전달, 기존 generation/epoch PCM 수락 규칙 보존.
4. `src/recoryn/app/recovery.py`: 건강 prefix와 오디오 S·미확인 suffix 분리 표시.
5. `src/recoryn/app/status.py`: 안전 단정 없는 표시 read model.
6. `src/recoryn/ui/main.py`: 명시 선택/확인·상태·worker 조회; GUI에서 sync/DB 열거 안 함.
7. `src/recoryn/cli.py`: 복구/상세 export에 버전·확인 범위 참조, live 거부 유지.
8. `tests/integration/test_append_pipeline.py`(신규): 실제 RecordingService·sealer·표와 G08 ACK 통합.
9. `tests/ui/test_append_durability_ui.py`(신규): 실제 확인 창·상태·동적 알림·취소.
10. `tests/e2e/test_append_durability_export.py`(신규): 실제 합성 저장→종료/복구→내보내기 바이트·표시.
11. `scripts/measure_append_durability.py`(신규): 합성 PCM·지연 주입·E20 및 외부 X용 비민감 측정.

G-P17b 시점에 G-P09 migration 정본 파일이나 G-P10 exporter가 추가 파일로 분리되어 이 목록으로 불가능하면, 구현 전에 재대조하여 정확한 범위를 다시 승인받는다. 기본 app-wide 설정 저장, `ui/ai_bridge.py`, AI/모델/runner, vault, package, 공용 설정은 범위 밖이다. 정본 설계 문서의 제품 문구는 C00 문서 단위로 인계한다.

## 12. 대안과 결정 요청

| 대안 | 장점 | 비용·한계 | 권고 |
| --- | --- | --- | --- |
| 현행 유지 | 구현/동기화 의미 변화 없음 | CI에서 보인 소비자 정지·QUEUE_DROP 지속 | 비교 기준으로만 유지 |
| 17a: per-block fsync 밖 | 삭제 순서·기본 완료 의미 보존, 다른 작업의 root 경합 완화 | 소비자 fsync 대기는 남아 처리량 해법 전체가 아님 | 우선 구현 권고 |
| 동기식 N/T 묶음 | 코드가 비교적 작고 sync 횟수 감소 | 소비자가 여전히 각 묶음 fsync를 기다림; 2트랙·느린 디스크에서 다시 queue 포화 | 주안으로 채택하지 않음 |
| 17b: 기존 sealer의 비동기 묶음 | 새 thread 없이 소비자의 sync 대기 제거, bounded 요청과 명시 cutoff | handle 수명·공정성·S 기록 추가, 전원 장애 미확인 창 확대, 장치 용량 한계 유지 | 명시 opt-in으로 조건부 권고 |
| 별도 sync thread/병렬 worker | sealer와 flush 대기 분리 가능 | 종료·삭제 lease 복잡도와 thread 증가; 장치가 직렬이면 효과 미보장 | 실제 병목 증거 뒤 후속 검토 |
| queue 확대/긴 청크/flush 생략 | 단기 거부를 줄일 수 있음 | 메모리·미확인 tail·복구 시간 증가, 자동 변경은 제품 의미 완화 | 묵시 적용 금지 |
| write-through/장치별 동기화 정책 | 플랫폼 특정 최적화 여지 | 권한·호환·hardware 검증 별도, Windows 전원 장애 무손실의 자동 증거가 아님 | 외부 실험 후 별도 계약 |

C00·사용자 결정 요청:

1. **단계/기본**: 17a 우선·PER_BLOCK 기본 유지, 17b는 매 실행 명시 opt-in을 승인하는가. 묶음을 앱 기본으로 바꾸는 선택은 사용자 제품 결정과 정본 개정을 먼저 받는다.
2. **I1 범위/수명**: D 뒤 새 미디어 write/create/게시 0, 기존 write의 sync 완료 허용, descriptor·private recovery guard 보강과 활성 lease 수명을 승인하는가.
3. **묶음 정책**: N=100/T=1초 요청 preset·기존 sealer 활용·bounded coalescing·트랙 공정 순서를 승인하는가. 이 값이 전원 장애 최대 손실 시간이 아님을 UI/문서에 명시한다.
4. **보존/인계·순서**: additive watermark 표 1개·건강 schema 2 유지·G-P09 구성요소와 G-P10 상세 참조 인계를 승인하는가. 표를 만드는 17b는 G-P09a 프레임 승계 뒤 시작하는 안이다. 전원 장애의 실제 장치 검증 전 “무손실 보장”은 하지 않는다.
5. **범위/게이트**: 17a 8 + 17b 19(공유8, 합집합19파일), 의미 분모 2,608(1,164+1,444)·mutation32·신규 시험60초 목표·E20 관측 step300초를 승인하는가. 실제 HDD/백신 X16·전원 차단은 별도 외부 게이트다.

이 계약 단계에서는 Git 쓰기·제품·시험 수정·하위 에이전트·pane 생성·실제 장치·네트워크·다운로드·설치를 수행하지 않았다. 계약 및 분모를 승인받아도 구현·성능 목표·실제 전원 장애 검증 완료로 기록하지 않는다.

## 13. 계약 자체 점검

문서의 family ID 범위를 별도 산식으로 열거해 **2,608 / 중복 0**, 17a **1,164** + 17b **1,444**를 확인했다. P 고정 20행과 mutation 01~32의 누락·중복도 없고, 파일 경계는 8·19(공유8, 합집합19)로 일치한다. Markdown 상대 링크 3개가 존재하며 UTF-8/LF·끝 개행·공백을 확인했다. 점검 기록은 OS TEMP `recoryn-g17-contract-kig3_wma/audit.json`이다.

이 점검은 문서의 산술·형식 점검이다. **제품 시험 실행 0 / mutation 실행 0 / E·X 신규 측정 0**이며, CI 수치는 §2의 기존 원문 증거와 구별한다. 작성자는 이 계약을 단독 승인하지 않는다.


## 14. G-P08 FIX1의 부가 기록 비차단 결정 인계

G-P08 독립 검토 뒤 C00이 확정한 결정은 “건강 기록 실패는 녹음을 멈추지 않음”이다. G-P17 구현 착수 시 G-P08 최종 push와 이 결정을 함께 대조한다. 위 계약의 실제 payload/journal/descriptor write·fsync 실패는 저장 실패라는 의미를 유지하지만, watermark/건강 checkpoint의 DB 기록·호환 요약 실패를 같은 오류로 승격하지 않는다.

- RAM에서 확인한 sync cutoff와 DB에 마지막으로 영속 기록한 cutoff는 별도 사실이다. DB 저장 실패 시 그 실행의 영속 관측은 DEFERRED/미상이며, 실제 sync가 끝난 PCM의 수락·writer·sealer를 중단하지 않는다. 확인하지 못한 DB prefix를 0손실로 표시하지 않는다.
- source·consumer·sealer·sync handle의 저장 종료 ACK와 건강 CLOSED 기록은 구분한다. 부가 기록이 보류돼도 저장 ACK 자체를 WRITER_ACK_PENDING으로 바꾸지 않는다. 건강 판정이 여전히 보류라면 확정/내보내기는 보류 상태를 정직하게 반환하고, 이미 확정된 원본의 상태를 되돌리지 않는다.
- §6 F의 receipt DB busy·commit 실패·손상 행은 위 비차단/미상 oracle를 적용한다. 물리 sync 오류 행은 계속 저장 실패·원본 prefix 보존 oracle다. 입력 분할·계획 분모 2,608행과 mutation32, 17a/17b 파일 경계는 이 명료화로 바뀌지 않는다.
- G-P08의 호환 요약은 byte budget을 지키며 큰 legacy 원문 값은 canonical run의 optional legacy_projection으로 보존한다. 이 필드는 G-P17의 새 watermark 표와 별개이고, G-P09가 두 구성요소와 reader version을 함께 인계받아야 한다.

이 절은 앞선 G-P08의 C00 결정을 인용한 의존성 정리다. G-P17의 기본 정책 변경·묶음 선택·내구성 손실 창과 구현 승인은 여전히 §12의 결정 요청 상태다. 제품·시험 구현이나 실제 전원 장애 검증을 수행했다는 뜻이 아니다.

## 15. G-P17a 구현 계약 확정과 입력 행 대응

### 15.1 C00 승인·기준·범위

앞 절의 제안·미실행 표시는 계약 작성 당시 이력이다. C00은 ①17a 우선·PER_BLOCK 기본 유지 ②삭제 의도 뒤 미디어 쓰기·게시 금지와 동기화 수명 ③17b 매 실행 opt-in ④watermark·G-P09/G-P10 인계 ⑤분모 2,608·mutation32를 승인했고, GS-P02 push 뒤 G-P17a 구현 시작을 지시했다. 현재 단위는 **17a만**이며, 17b의 묶음 정책·새 watermark 표·UI·기본값 변경을 구현하지 않는다.

착수 기준은 `8126c1f46e2e36350041754ec41b4b38775db6f0`이다. 시작 때 제품 3파일이 해당 commit과 LF hash까지 같은지 확인했다. 승인된 신규 시험 4파일은 없었다. 동시 G-P12·G-P11c 변경은 격리 사본에 넣지 않는다.

| 파일 | 착수 LF SHA-256 / 상태 |
| --- | --- |
| `src/recoryn/storage/chunks.py` | `e289f3fd8b3f83b58b059cd537211eb12de2007b198e4cade03dd26dce4df6d5` |
| `src/recoryn/storage/_coordination.py` | `46d76a8f86ef7438a12dea7f5a201d87244b1c89e37707878c47a8e23eabb8c9` |
| `src/recoryn/storage/library.py` | `7e9a1c126409bfdd2a39de04aa93a64f8e3c972943d1f830567069ca29958f79` |
| `tests/unit/test_append_durability.py` | 신규 |
| `tests/integration/test_append_fencing.py` | 신규 |
| `tests/integration/test_append_durability_crash.py` | 신규 |
| `tests/property/test_append_durability_model.py` | 신규 |
| 이 문서 | 계약 원문 `1fb8679bd85df3386d86f5a37d89d0b886a73c67bee51734538179c90ff7cd2c` |

`library.py`의 최초 허용 변경은 private salvage에서 공통 writer guard를 연결하는 부분이다. 외부 SQLite 잠금 관찰을 함께 고치려면 public `register_chunk`의 대기 구간 변경이 필요하므로 별도 C00 목적 확장을 요청했다. 승인 전 해당 구간을 변경하지 않는다. 기존 저장소 시험의 open/delete 경쟁 기대값 적응도 별도 승인 요청이다.

### 15.2 실제 구현의 순서와 수명

한 writer의 append·sync·seal·abort를 writer 작업 RLock으로 직렬화한다. root mutex는 삭제 권위 재확인·실제 payload/journal/descriptor bytes·rename·짧은 RAM 갱신에만 쓴다. payload sync와 journal sync, descriptor sync, read-back 검증, 작업 잠금 및 종료 ACK 대기는 root 밖이다. 짧은 writer registry에서는 활성 상태·capability만 관찰한다.

append는 `WP → SP → WJ → SJ → 완료` 순서이며, WJ 직전과 완료 직전에 권위를 다시 확인한다. WP 뒤 D가 오면 이미 쓴 payload의 SP 완료는 허용하지만 새 journal bytes는 금지된다. 새 의도 뒤 실패한 append를 성공으로 반환하지 않는다. 원본 tail은 recovery의 검증 가능한 prefix로만 채택한다. 불완전 handle 쌍도 정리가 끝날 때까지 active로 남긴다.

abort는 closing을 먼저 표시하고 root·registry를 해제한 뒤 writer 작업 잠금을 기다린다. 진행 중 sync의 handle을 먼저 닫지 않는다. descriptor read-back 중에는 FileIO가 닫혔어도 seal-in-progress가 active를 유지한다. 기존 explicit hold는 unhold까지 유지하고, SealedChunk는 catalog 등록 뒤 release하는 기존 수명을 보존한다. private salvage도 public append/seal의 같은 실제-write guard를 사용한다. library 없는 writer의 SQLite 읽기는 timeout=0으로 불확인을 즉시 거부한다.

이 변경으로 소비자 thread는 여전히 블록마다 두 sync를 직렬로 기다린다. 다른 작업의 root 경합을 줄이는 것과 소비자 처리량 개선은 구별한다. 처리량 개선의 BATCHED는 17b이고, 이 단위의 성공 조건으로 승격하지 않는다.

### 15.3 계획 1,164행과 실행 node의 대응·독립 oracle

| family | 17a 행 수 | 실제 파일·관측 |
| --- | ---: | --- |
| W | 32 | unit: 손으로 쓴 8상태×4명령 기대 표. 실제 writer와 parked sync/abort를 실행하고 활성 lease·ACK·bytes를 대조 |
| D | 60 | fencing: 역할4×실제 DB/journal/tombstone/이력 불명5×시점3. D 이후 create/write/publish 로그 0과 catalog 0, recovery 원본 불변 |
| HB | 36 | fencing: 엄격 WP/SP/WJ/SJ/완료 순서의 D 삽입6×트랙2×권위3. 파일 bytes·journal sequence를 손으로 쓴 허용 prefix와 비교 |
| C | 78 | crash: 트랙2×checkpoint13×영속 모사3. 실제 소유한 자식 kill 후 각 사본에서 Library 복구·재복구·알려진 bytes 비교 |
| F | 42 | crash: 실제 short/zero/ENOSPC/EBADF write와 sync EIO/EBADF/미완료 ACK. 원본 prefix·errno·활성 handle·조기 완료 금지 |
| L | 56 | fencing: 트랙2×제어7×미완료4. 실제 DesktopRecorder·RecordingService·PowerCoordinator, fake source만 사용. 종료 ACK와 bytes·다음 epoch·삭제 부활 금지 |
| Q | 60 | property: 트랙2×지연5×분포3×경합2. 정수 시각 독립 FIFO oracle와 실제 bounded queue/writer 대조 |
| M | 800 | property: 트랙2×길이0~3의 7명령 모든 trace. 제품 predicate를 읽지 않는 상태·FIFO 모델과 실제 queue/writer 응답·bytes·sync 순서를 비교 |
| 합계 | **1,164** | unit32 + fencing152 + crash120 + property860 |

별도 보강 `G17-X-01`은 read-back이 진행 중일 때 일찍 unhold해도 active가 사라지지 않는지 확인한다. 이 1행을 기존 분모에 섞지 않는다. 따라서 신규 4파일 실행 node는 **1,165**다.

C family는 **26개 실제 kill**(트랙2×checkpoint13)의 snapshot을 공유하고, 각 persistence 변형에서 별도 사본·복구·oracle를 실행해 78행을 만든다. 78번 kill이라고 보고하지 않는다. Windows venv launcher와 실제 interpreter PID를 혼동하지 않도록 실제 base interpreter를 실행하고, marker PID와 소유 Popen PID·사본 import를 확인한 뒤 자신이 만든 process handle만 kill/wait한다. marker의 일시 PermissionError만 기한 안 재시도한다.

C08은 17a의 엄격 sync 완료와 기존 G-P08 건강 checkpoint 사이 중단이다. 아직 없는 17b watermark receipt DB를 검증했다고 집계하지 않는다. OS cache 보존·sync-prefix·torn-tail은 파일 사본의 주입 모사이며 실제 전원 차단 증거가 아니다. F의 22~26·48~52는 17b receipt/lease 행이므로 17a 실행 ID에서 의도적으로 제외한다. 17a는 F001~021·F027~047이다.

### 15.4 착수 중 확인한 기존 기대값·추가 범위 요청

`tests/unit/test_storage.py::test_p11_open_delete_barrier[False]`는 open이 root를 선점했다면 append 전체가 항상 성공한다고 단언한다. 기존 구현은 append의 두 fsync까지 root를 쥐므로 그 순서가 고정됐다. 17a에서는 WP 뒤 SP 동안 삭제 의도가 들어오면 WJ를 거부해야 하므로 성공 또는 삭제 승리의 두 순서가 가능하다. 실패는 실제 기존 시험 실행으로 확인했고, 이 한 시험만 새 선형화 순서에 맞추는 최소 적응 승인을 요청했다. DELETE_PENDING·봉인 거부·재삭제 성공·부활 0의 기존 단언은 유지한다.

또 다른 기존 시험 `test_p11_late_writer_is_fenced_after_delete`에서 closing 오류가 삭제 오류보다 먼저 나오는 회귀를 확인해 제품에서 canonical 삭제 권위 검사를 먼저 하도록 수정했다. 삭제 후 writer의 실패 코드를 일반 closing 오류로 덮지 않는다.

실행·mutation·측정의 최종 수치와 승인 답변은 다음 절에 기록한다. 위 구현 설명 자체는 독립 검토나 Windows 전원 장애 검증 완료를 뜻하지 않는다.

## 16. G-P17a 직접 실행 증거

### 16.1 신규 시험·ID 감사·mutation

OS TEMP 증거 폴더는 `C:/Users/gangd/AppData/Local/Temp/recoryn-g17a-kegmd5tq`다. `tree/`는 Git archive 기준 commit에 승인 파일만 얹은 사본이며 PYTHONPATH를 사본 src로 고정한다. 제품 import와 C actor의 자식 import를 모두 확인한다. 시험은 offscreen·no cache·고유 basetemp·ResourceWarning 오류 승격으로 실행한다.

최초 신규 4파일 합계는 **1,165 PASS / 39.55초**(`allnew.xml`). 계획 1,164행의 family별 실제 ID를 XML에서 따로 열거해 누락 0·중복 0을 확인했다(`case-audit.json`). 이후 별도 보강 X02(라이브러리 없이 SQLite 읽기가 잠긴 경우 root-held busy wait 금지)가 1 PASS이며, 최종 합계 시간은 아래 최종 실행으로 다시 고정한다. X01·X02는 계획 분모에 합치지 않는다.

임시 변이 사본에는 pyproject·src·tests·scripts·packaging을 함께 복사했다. 해당 사본 src를 PYTHONPATH로 고정하고, 결함 하나만 주입해 기존 선택 시험을 실행했다. 수집 오류·timeout은 검출로 세지 않는다. MUT08 최초 선택은 fixture 정리에서만 실패해 유효 검출에서 제외했고, W012의 본문 oracle로 다시 실행했다. 이 재실행은 본문에서 root-held 작업 잠금 대기를 잡고, fixture 정리에서도 같은 위반을 덧보고한다.

| 변이 | 주입한 결함 | 검출한 독립 관측 |
| --- | --- | --- |
| MUT01 | payload fsync를 root 안으로 | W: sync hook에서 root 보유 금지 |
| MUT02 | 실제 미디어 write guard 제거 | D: 의도 뒤 payload/journal bytes 검출 |
| MUT03 | SP 뒤 journal 재확인 제거 | HB: D 이후 새 journal bytes·prefix 위반 |
| MUT04 | descriptor create/write guard 제거 | D descriptor: 의도 뒤 create/write 검출 |
| MUT05 | recovery-work만 guard 예외 | D recovery: 의도 뒤 private salvage bytes 검출 |
| MUT06 | 열린 sync writer를 inactive로 | W: parked handle의 active lease 위반 |
| MUT07 | abort의 작업 직렬화 제거 | W012: sync ACK 전 handle close 금지 |
| MUT08 | root를 잡고 writer 작업 잠금 대기 | W012: OperationProbe의 잠금 순서 본문 단언 |
| MUT09 | payload sync 생략 | M0010: 성공 append의 SP·SJ 실제 완료 로그 |
| MUT10 | SJ 뒤 SP로 역전 | M0010: 손으로 정한 payload→journal 완료 순서 |

**10/10 검출**, 정상본 결과와 구별한다(`mutation-results.json`, `mut-01.log`~`mut-10.log`). 새 read-back/unhold·SQLite fallback 보강은 별도 행이며 mutation 분모를 늘려 주장하지 않는다. 파일 fsync 수는 기존 회귀에서도 append당2·seal당3을 유지하는지 확인한다.

### 16.2 느린 디스크 모사: 처리량 관측과 root 구조 판정

실제 장치 없이 합성 PCM 48kHz·mono·480frame/블록을 트랙별 100Hz로 6초 제출했다. 기본 queue256·16MiB, chunk96,000frame, 기존 seal FIFO4를 유지했다. 각 media sync에 0/50/100/200/500ms 대기를 주입하고, 6초 입력 종료 때 새 지연 주입을 중단한다. 이미 시작한 지연은 끝까지 기다린 뒤 수락분을 모두 drain한다. 따라서 아래 값은 지속적인 디스크 6초 실험과 종료 후 정상 drain의 관측이며, 영구 지연 디스크의 최대 정지 시간 보장이 아니다.

모든 계측 대상 media sync에서 root·writer registry·coordination registry·RecordingService gate 보유가 0이었다. 모든 행에서 저장 원본 bytes=수락 payload, 저장frame=수락×480, 건강 dropped_frames=거부×480, 완료 뒤 worker 없음이 통과했다. root 보유 최대는 create/write·짧은 상태 구간의 계측값이다. 17a의 처리량 목표를 새로 0거부로 바꾸지 않는다.

| 트랙 | sync 지연 ms | 수락 블록 | 거부 블록 | 저장 frame | root 최대 ms | submit 최대 ms |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 0 | 600 | 0 | 288000 | 10.398 | 0.070 |
| 1 | 50 | 314 | 286 | 150720 | 9.083 | 0.226 |
| 1 | 100 | 285 | 315 | 136800 | 11.053 | 0.239 |
| 1 | 200 | 271 | 329 | 130080 | 11.835 | 0.221 |
| 1 | 500 | 262 | 338 | 125760 | 10.429 | 0.220 |
| 2 | 0 | 1200 | 0 | 576000 | 4.346 | 0.074 |
| 2 | 50 | 312 | 888 | 149760 | 25.294 | 0.250 |
| 2 | 100 | 285 | 915 | 136800 | 18.006 | 0.244 |
| 2 | 200 | 271 | 929 | 130080 | 21.328 | 0.234 |
| 2 | 500 | 262 | 938 | 125760 | 23.168 | 0.251 |

대기 없는 모사에서는 1·2트랙 거부 0이었다. 지연 조건에서는 소비자 자체의 두 sync 직렬 대기가 queue를 채우므로 거부가 남는다. **17a만으로 소비자 처리량 문제를 해결했다고 판정하지 않는다.** 해당 개선은 승인된 17b의 명시 opt-in·내구성 구분·별도 검증 대상이다. 계측 wrapper와 다른 선택 회귀가 일부 겹친 로컬 실행이므로 디스크 단독 benchmark 수치로 일반화하지 않는다. 원자료는 `measure.py`, `measurement.json`, `measure.log`다.

실제 HDD·백신 검사·전원 차단은 **NOT_RUN(외부 게이트)**이다. os.fsync 완료와 장치 전원 장애 무손실을 동일시하지 않는다.

### 16.3 최종 신규 시험·기존 회귀에서 발견한 경계

최종 신규 4파일은 **1,168 PASS / pytest 39.36초(프로세스 wall 39.83초)**이며 단독 선택 실행으로 60초 예산을 만족했다(`newfinal2.xml`, `final-checks.json`). 계획 1,164는 그대로이고 별도 보강은 X01~X04 네 행이다. X02는 library 없는 SQLite 읽기 잠금 시 즉시 안전 거부·미디어 생성 0, X03은 실제 I/O 전에 권위 확인이 거부되면 기존 확인 prefix를 보존하고 명시 수선 뒤 그 prefix만 봉인, X04는 sync ENOSPC 뒤 close도 실패해도 primary errno와 확인된 prefix를 보존한다. W의 abort 경쟁은 명령이 직렬화를 시도하거나 조기 종료한 사실을 확인한 뒤 parked sync를 풀어 스케줄링 행운에 기대지 않도록 했다.

첫 관련 묶음은 **396 PASS / 1 FAIL / 291.89초**였다(`related2.xml`). 유일한 실패는 §15.4의 승인 요청 중인 기존 open/delete 기대값이다. 기존 `test_p11_late_writer_is_fenced_after_delete`, fsync 수·한 번 read-back·capability 결속·삭제·seal·등록 수명·G-P15 구조와 대량 tombstone 회귀는 통과했다.

최초 전체 시도에서는 GS02-C-013~016 네 행도 실패했다. 실제 I/O 시작 전의 권위 거부까지 writer의 I/O 실패로 처리한 것이 원인이었다. 새 write가 전혀 시작하지 않은 거부는 기존 확인 prefix·handle을 유지하고, 실제 I/O 시작 후 실패만 failed/정리로 처리하도록 제품을 고쳤다. 기존 GS-P02 시험은 변경하지 않았다. 이 수정 뒤 해당 4행을 포함한 **971 PASS / 28.59초**(`repair-prefix.xml`)와 최종 신규 1,168행이 통과했다. 손상 권위는 계속 해당 호출의 쓰기를 거부하며, 자동 수선·새 write·삭제 부활 허용으로 바꾼 것이 아니다.

이후 쓰기 전 거부의 원본 prefix 의미를 독립 모델에도 반영했고, 최종 mutation 10/10을 다시 확인했다. 최초 전체 실행은 구버전 제품의 중간 증거여서 중단했으며, 완료된 전체 회귀·coverage PASS로 집계하지 않는다. 최종 사본의 CI 동등 결과는 별도로 아래에 기록한다.

### 16.4 외부 SQLite 쓰기 잠금의 별도 관찰과 범위

`sqlite-observation.py`는 실제 TEMP SQLite 연결로 외부 `BEGIN IMMEDIATE`를 유지하고, 같은 Library의 이미 발급된 SealedChunk 등록과 다른 세션 append를 겹쳤다. media fsync를 root 밖으로 옮겨도 변경하지 않은 `register_chunk`의 SQLite busy 대기는 남는다. 직접 측정은 **등록 thread root 보유 1.200초 / 다른 세션 append 1.107초 대기 / 잠금 해제 뒤 등록 성공**이었다(`sqlite-observation.json`). 초기 scope의 private salvage 변경만으로는 이 public 등록 경로를 고칠 수 없다.

C00에 요청한 최소 확장은 `register_chunk`의 짧은 등록 시도에서 SQLite busy timeout을 0으로 두고, BUSY/LOCKED만 기존 기한 안에서 root 밖 재시도하며, 매 시도 삭제 권위·capability·중복 등록 조건을 다시 확인하는 목적이다. SealedChunk 활성 ACK를 앞당기거나 connection을 root 밖 여러 thread에서 사용하지 않는다. 승인 전에는 이 경로를 바꾸지 않았다. 건강 checkpoint 등 다른 SQLite 쓰기 경로 전체를 고쳤다고 주장하지 않는다.

### 16.5 기존 경쟁 시험의 최소 적응 승인 요청(미적용)

필요한 추가 파일은 `tests/unit/test_storage.py` 하나, 허용 목적은 `test_p11_open_delete_barrier`의 `deletion_first=False` 분기 한 곳뿐이다. 현재 배정의 8파일 밖이므로 아직 수정하지 않았다. 다음이 제안 diff의 전부다.

```diff
-                future.result(timeout=5)
+                try:
+                    future.result(timeout=5)
+                except StateConflict as error:
+                    assert str(error) == "Writer session has a deletion intent"
                 assert deletion_future.result(timeout=5)["state"] == "DELETE_PENDING"
```

append가 두 sync와 최종 확인까지 먼저 끝나면 기존처럼 성공이다. WP 뒤 SP 중 D가 먼저 게시되면 새 journal bytes를 쓰지 않고 canonical 삭제 오류로 거부되는 것도 올바른 순서다. 다른 예외를 허용하지 않는다. `DELETE_PENDING`, 뒤의 seal 거부, abort·재삭제 성공, 최종 staging/final 폴더 없음 단언은 모두 유지한다. 새 D/HB 96행이 D 이후 실제 create/write/publish 0과 원본 prefix를 별도로 검증하므로 이 적응으로 I1을 약화하지 않는다.

범위 승인 전에는 제안으로만 보관한다. 전체 검증에서 이 기존 기대값만 실패하더라도 이를 PASS로 세거나 `IMPLEMENTATION_READY`로 보고하지 않는다. `register_chunk` 목적 확장과는 별개 결정이다. 그 경로는 C00이 후속으로 분리할 수도 있다.

## 17. G-P17a 검증 종료 보고·범위 결정 대기

현재 상태는 **SCOPE_NEEDED**다. 승인된 8파일의 구현·시험·측정은 작성했지만, 정상본 전수 PASS 조건은 기존 경쟁 시험 1건의 승인된 의미 적응이 필요해 닫지 않았다. 독립 검토·통합 승인으로 기록하지 않는다.

### 17.1 정확한 사본과 최종 실행

`tree2/`는 기준 `8126c1f` archive에 G-P17a 승인 파일만 얹었다. archive의 기존 파일 **375개**를 다시 대조해 범위 밖 차이 0, 제품·시험 7파일은 작업 트리와 바이트 일치를 확인했다(`archive-scope-final.json`). PYTHONPATH는 사본 src로 고정했고, 부모·자식·변이 사본의 실제 import 경로를 각각 확인했다. 최종 실행 중 제품·시험은 변경하지 않았다. 이 결과 절의 추가는 실행 의미를 바꾸지 않는 보고다.

| 확인 | 직접 실행 결과 |
| --- | --- |
| 신규 4파일 단독 | **1,168 PASS / 39.36초**, wall39.83초, skip0 / 계획1,164·별도4 / 누락·중복0 |
| 임시 사본 MUT01~10 | **10/10 검출** / 본문 단언·실제 I/O 로그 / 수집 오류·timeout을 검출로 집계하지 않음 |
| 전체 오프라인·CI 동등 전수(같은 실행 1회) | **23,965 PASS / 1 FAIL / skip0 / 1,621.21초**, 프로세스 wall1,631.78초 |
| 유일한 전수 실패 | `tests/unit/test_storage.py::test_p11_open_delete_barrier[False]` — §16.5의 미적용 기존 기대값, 실제 예외 `StateConflict: Writer session has a deletion intent` |
| tests/ui 전체 | **1,465 PASS**, skip0 |
| tests/integration 전체 | **4,058 PASS**, skip0 |
| tests/property 전체 | **14,445 PASS**, skip0 |
| pytest coverage 하한 | **92.36% / 85% 통과** |
| check_coverage | 아래 **7묶음 PASS**. pytest의 단일 실패를 숨긴 전체 PASS로 해석하지 않음 |
| coverage 파일 경계 | **임시 fixture·범위 밖 source 파일 0**. report의 모든 측정 파일이 사본 `src/recoryn/` 안 |
| ruff check | src/recoryn·scripts·packaging·tests 전체 PASS |
| ruff format --check | 위 전체 **197파일 통과** |
| mypy | `src/recoryn scripts packaging` **91 source files 통과** |

전수 명령은 다음과 같다. offscreen·PYTHONDONTWRITEBYTECODE와 고유 TEMP basetemp를 사용했다. skip/deselect·xfail이나 coverage 설정 완화는 없다.

```text
python -m pytest -q -p no:cacheprovider -W error::ResourceWarning --cov=recoryn --cov-branch --cov-report=json:coverage.json --cov-fail-under=85 --basetemp=<고유 TEMP> --junitxml=<TEMP>/ci2.xml
python scripts/check_coverage.py coverage.json
python -m ruff check --no-cache src/recoryn scripts packaging tests
python -m ruff format --no-cache --check src/recoryn scripts packaging tests
python -m mypy src/recoryn scripts packaging
```

`check_coverage.py` 실제 출력 전문:

```text
domain: line=99.18%/95% branch=97.89%/90% PASS
capture: line=99.85%/95% branch=98.57%/90% PASS
jobs: line=99.29%/95% branch=96.23%/90% PASS
storage: line=96.11%/95% branch=91.40%/90% PASS
security: line=98.11%/95% branch=94.43%/90% PASS
content: line=99.59%/95% branch=98.75%/90% PASS
all: line=93.76%/85% branch=88.26%/80% PASS
```

각 명령의 returncode·시간은 `final-checks.json`에 있다. pytest만 returncode1이고 coverage·ruff·format·mypy는 0이다. 전수 실패 1건이 있으므로 최종 wrapper도 실패를 그대로 반환한다. 해당 oracle를 승인 없이 바꾸거나 제외하지 않았다. JUnit을 독립 집계한 값은 `ci2-audit.json`이다.

### 17.2 변경 파일의 LF SHA-256

승인 범위는 여전히 아래 제품·시험 7파일과 이 문서, **8파일**이다. 문서 자신의 LF hash는 이 창의 최종 보고에 쓴다. 공유 G-P12·G-P11c 파일과 기존 `tests/unit/test_storage.py`는 수정하지 않았다.

| 파일 | SHA-256(CR 제거 LF) |
| --- | --- |
| `src/recoryn/storage/chunks.py` | `ef000edf10866b6a46e423f8c35f2a2e6f5f3b130c2957477649f69df03cb7c5` |
| `src/recoryn/storage/_coordination.py` | `5bac3d361ddfdc49ab1434cab577e13b60f311c0c1c539a64a05a63ffe89be5d` |
| `src/recoryn/storage/library.py` | `d5f34d459773db766737944e86e4933013e055734acce0fb5d5f34c217393013` |
| `tests/unit/test_append_durability.py` | `246ac6dedf4e5a32b6382868f6383b82174b09a38a7d7687c0b2e0cf291c2f07` |
| `tests/integration/test_append_fencing.py` | `ffbadb00c23f6f05be78fff77fffcda89a0de1e1b2b828a651352f442931a497` |
| `tests/integration/test_append_durability_crash.py` | `a373684703c7403d0ae1e7c974444c36a58d2c05a143b1f4478c01594e132822` |
| `tests/property/test_append_durability_model.py` | `62c64a2d5f535c666dca86332fe2ce2200e27b9e51e3ac592d5e186e239f3e96` |

### 17.3 C00 결정이 필요한 두 범위와 남는 한계

1. **필수: 기존 시험 한 곳의 범위 추가.** `tests/unit/test_storage.py::test_p11_open_delete_barrier`만 §16.5대로 적응할 수 있도록 승인하거나 C00이 별도 시험 단위로 적용해야 한다. 현재 사용자 배정이 8파일로 한정돼 있어 작업자가 임의 적용하지 않았다. 기존 단언을 약화하지 않으며, 실제 PER_BLOCK WP/SP/WJ/SJ와 D의 두 합법 순서를 인정하는 수정이다. 적용 후 정상본 전수 PASS를 다시 확인하기 전에는 `IMPLEMENTATION_READY`로 보고하지 않는다.
2. **별도 선택: public 등록 목적 확장 또는 후속 분리.** `8126c1f:storage/library.py:932`의 `register_chunk`가 `:403`의 `BEGIN IMMEDIATE`를 root 안에서 기다리는 현상은 §16.4에서 재현했다. 현재 library 허용 목적은 “private salvage 경로의 공통 guard 연결만”이므로 public 등록은 변경하지 않았다. 승인하면 같은 파일의 해당 등록 시도만 busy0·root 밖 bounded 재시도로 보강하고 삭제 권위·활성 ACK 회귀를 추가한다. 후속 분리 결정도 가능하다. 기존 건강 DB는 별도 `_health_transaction`에서 이미 busy0을 사용하므로 public 등록 관찰과 혼동하지 않는다.

PER_BLOCK의 소비자 직렬 sync 대기·느린 디스크의 큐 거부는 측정 결과 그대로 남는다(§16.2). 이를 17a의 처리량 해결로 표시하지 않는다. 17b의 BATCHED·watermark·매 실행 opt-in, GS-P11의 권위 snapshot, G-P09a migration, 실제 HDD·백신·전원 차단은 이번 구현 범위나 검증 완료로 집계하지 않는다.

Git 쓰기·공유 설정·타 작업자 파일 수정·하위 에이전트·pane·네트워크·다운로드·실제 장치·음성·모델·계정·vault 쓰기·설치는 수행하지 않았다.

## 18. C00 범위 확장 승인과 등록 대기 계약(구현 계속)

C00은 §16.5의 기존 경쟁 시험 diff를 그대로 승인했고 `tests/unit/test_storage.py`를 추가했다. 다른 예외·단언 변경은 허용하지 않는다. public `register_chunk`의 SQLite busy 대기도 이번 17a 목적에 포함했다. 총 **9파일**이며 앞선 SCOPE_NEEDED는 승인 전 이력이다. 기준은 기존 `8126c1f`를 유지하고, 동시에 진행된 G-P12·G-P11c·G-P16 등의 작업 트리는 사본에 섞지 않는다.

등록은 각 root-held 시도 **전체**에 busy_timeout=0을 적용한다(권위 읽기·BEGIN·입장 검증·commit까지). 원래 timeout을 되돌리고 root를 놓은 뒤에만 최대10ms씩 재시도한다. 재시도 기한은 진입 때의 기존 연결 busy_timeout 값이다. SQLITE_BUSY/LOCKED와 그 확장 코드만 재시도하고 다른 오류·속성 없는 가짜 오류는 즉시 전달한다. 매 시도 현재 삭제 권위·claim·상태·중복/overlap·미해제 capability를 재확인한다. 성공/실패 전에는 Library가 writer의 capability를 대신 해제하지 않는다. 부모 recorder의 기존 FIFO와 release-after-registration ACK는 바꾸지 않는다.

### 18.1 추가 입력 분할·독립 oracle(기존 1,164행과 별도)

새 R 행은 승인 확장 목적의 보강 행이고, 기존 계획 1,164를 다시 계산해 늘리지 않는다.

| R ID | 입력 | 독립 oracle |
| --- | --- | --- |
| R01~02 | 1·2트랙, 실제 외부 SQLite EXCLUSIVE 3초, 원 검토와 같은 1.5초 전·2초 후 10ms source | 거부·root 보유 실측, 수락 원본 전량 일치, busy 대기 root 구조/시간 상한. 소비자 자체 seal 지연의 QUEUE_DROP은 측정값 |
| R03~04 | 1·2트랙, 등록 busy 중 pause/stop | ACK_PENDING·OPEN·active/capability 유지, 잠금 해제 뒤 등록 완료·release·CLOSED |
| R05~06 | 1·2트랙, 등록 busy 중 journal-only 삭제 의도 | 재시도에서 현재 권위 거부, D 뒤 catalog INSERT0·원본 부활0 |
| R07 | 등록 busy 중 capability 해제 | 재사용 거부·catalog0, 이전 capability 사실을 다음 시도에 승계하지 않음 |
| R08 | 기존 busy 기한60ms, 실제 외부 잠금 지속 | 기한 내 BUSY 실패·rollback·timeout 원복·명시 release 전 active 유지 |
| R09 | 실제 query_only 연결 | READONLY 즉시 전달·재시도0·catalog0·timeout 원복 |
| R10~12 | LOCKED·확장 BUSY2종 1회 주입 후 정상 | 정확히 재시도·root/registry/gate 없는 대기·원래 timeout 복원·행1건 |
| R13~14 | 1·2트랙, 복수 chunk FIFO가 등록 busy 뒤 풀림 | 제출 순서 그대로 등록·중복0·수락 원본 보존·마지막 ACK 뒤만 release/CLOSED |

합계 **R14행**, 기존 별도 X01~04와 구별한다. R01/02는 거부 0을 로컬 실측 목표로 삼되, CI의 확정 성질은 SQLite busy가 root를 보유하지 않는다는 구조·시간 상한과 수락 원본 회계 일치다. 실제 미디어 write/fsync가 느린 경우의 소비자 처리량 문제는 여전히 17b 대상이다. 일시 건강 DB 보류를 저장 실패나 거짓 CLOSED로 바꾸지 않는다.

추가 mutation 계획(이전 MUT01~10과 별도): REG01 busy0 제거, REG02 재시도 대기를 root 안으로, REG03 재시도 권위 확인 제거, REG04 매 시도 capability 확인 제거, REG05 FIFO 등록 전에 release, REG06 SQLITE_BUSY 아닌 오류 재시도, REG07 기한 검사 제거. 실제 검사에서 구조·정확한 코드·완료 사실의 단언으로 검출하며 timeout만으로 죽은 변이는 유효 검출로 세지 않는다.

## 19. 범위 확장 뒤 직접 실행 결과

앞선 §17의 SCOPE_NEEDED·단일 FAIL은 승인 전 이력이다. §18의 C00 승인에 따라 기존 시험 한 곳을 그대로 적응했고 public 등록 대기도 구현했다. 이 절의 결과는 **8126c1f + 승인 9파일**인 새 TEMP `C:/Users/gangd/AppData/Local/Temp/recoryn-g17a-final-jdt98qb5/tree`에서 실행했다. 이후 main의 G-P12·G-P11c·G-P16 등 변경을 끌어온 결과가 아니다.

### 19.1 신규 시험·분모·시간 게이트

신규 4파일 **1,182 PASS / 70.48초 / warning0 / skip0**(`gate.xml`, `gate.log`). 기존 1,164행의 누락0·중복0을 재감사했다. 기존 X4와 새 R14는 별도이며 승인된 기존 분모를 늘렸다고 기록하지 않는다(`case-audit.json`).

| 파일 | node | testcase 시간 합(초) |
| --- | ---: | ---: |
| unit/test_append_durability | 36 | 0.489 |
| integration/test_append_fencing | 166 | 37.468 |
| integration/test_append_durability_crash | 120 | 26.305 |
| property/test_append_durability_model | 860 | 5.356 |
| 합계 | **1,182** | **69.618** (pytest 전체70.48) |

R14는 25.139초이며 R01·02의 실제 외부 잠금 측정이 10.491·13.309초다. 각각 원 검토와 같은 1.5초 입력 → 3초 외부 잠금 → 2초 후 관찰과 정상 stop/복구·원본 확인까지 포함한다. 이 실행에는 같은 세션의 다른 시험을 병행하지 않았으며, 다른 작업자 부하는 통제하지 않았다.

기존 60초를 넘었으므로 **행·oracle를 줄이지 않고 90초 예산 승인을 C00에 요청했다**. 승인 전 시간 게이트를 PASS라고 쓰지 않는다. 단순히 추가 R 행을 기존 분모 밖으로 표기했다고 시간에서 빼지 않는다. C00의 후속 결정은 아래 최종 결과에 기록한다.

### 19.2 외부 SQLite EXCLUSIVE 3초: 1·2트랙 실측

1.5초 전·3초 잠금·2초 후라는 원 G08 조건, 트랙별 48kHz mono·480frame/10ms, 기본 queue256·chunk96,000frame·FIFO4를 유지했다. 원본은 합성 bytes이며 장치를 열지 않았다. 건강 checkpoint의 DB 오류는 DEFERRED로 남기고 저장·수락은 계속됐다.

| 트랙 | 실제 잠금 초 | 수락 block | 거부 block | 저장 frame | 잠금과 겹친 sealer root 최대 ms | writer root 최대 ms | 전체 root 최대 ms |
| ---: | ---: | --- | --- | ---: | ---: | ---: | ---: |
| 1 | 3.000478 | {'mic': 650} | {'mic': 0} | 312000 | 3.453 | 4.506 | 4.506 |
| 2 | 3.000525 | {'mic': 651, 'system': 651} | {'mic': 0, 'system': 0} | 624960 | 3.809 | 5.441 | 5.441 |

두 행 모두 수락한 원본 bytes 전량 일치, frame 합 일치, dropped_frames=거부×480을 확인했다. stop 뒤 FINALIZED이며 건강 요약은 `RECOVERED_UNCLEAN / has_unknown=True`였다. DB 관측 공백을 미상 없음으로 덮거나 거짓 CLOSED로 표시하지 않는다(`health-after-sqlite.json`). R03/04·R13/14의 짧은 busy 구간에서는 종료 ACK 전 OPEN·활성 capability를 유지하고, 실제 등록 종료 뒤만 CLOSED/해제됨을 확인했다.

정확한 입력 횟수는 스케줄링 결과이므로 650/651을 고정 기대값으로 복사하지 않는다. 각 source의 수락 목록 자체와 저장 bytes를 독립 대조한다. CI에서는 Root의 SQL busy 대기를 0.5초 상한과 락 소유 구조로 판정하고, 소비자 자체의 실제 디스크 지연에 따른 QUEUE_DROP은 측정값으로 남긴다. 이는 §16.2의 처리량 한계를 숨기지 않으려는 구분이다.

직접 대조군으로 G08 검토자의 원 `probe_lock_realtime.py`를 수정 전 등록 경로(`.../recoryn-g17a-kegmd5tq/tree2`, library hash `d5f34d45…3013`)에 다시 실행했다. 같은 3초 잠금·2트랙에서 mic/system 수락536/532·거부115/119, sealer root **1,648.1ms**, stop FINALIZED였다(`before-register-control.log`). 이 대조군은 현재 전수 검증과 병행한 부하 조건이며, 수정 후 gate 측정과 완전히 같은 시스템 부하는 아니다. 과거 문서의 2,277~2,381ms를 이번에 직접 측정한 값으로 옮기지 않으며, 단일 수치로 일반적인 속도 배율을 보장하지 않는다.

### 19.3 임시 사본 mutation 재확인

pyproject·src·tests·scripts·packaging을 함께 복사하고 각 사본 src를 PYTHONPATH로 고정했다. 기존 writer MUT01~10 **10/10**, 추가 REG01~07 **7/7**, 합계 **17/17**을 검출했다. 17b의 나머지 계획 mutation을 실행한 것처럼 집계하지 않는다.

| 변이 | 실제 검출 |
| --- | --- |
| REG01 busy0 제거 | R08: 60ms 기한의 완료 단언 실패(부모가 관측 뒤 lock을 풀어 정리), process timeout이 아님 |
| REG02 sleep을 root 안으로 | R10: 실제 대기 함수에서 root 소유 금지 단언 |
| REG03 재시도 삭제 권위 확인 제거 | R05: journal-only D 뒤 즉시 안전 거부·catalog0 oracle 위반 |
| REG04 매 시도 capability 확인 제거 | R07: 대기 중 해제된 capability를 거부하지 못함 |
| REG05 등록 전 release | R03: ACK_PENDING 상태인데 active writer가 사라짐을 본문에서 검출 |
| REG06 non-busy 오류도 재시도 | R09: 실제 SQLITE_READONLY의 즉시 실패 단언 |
| REG07 기한 무시 | R08: 60ms 기한을 넘겨도 끝나지 않음. cleanup에서 lock을 풀어 자식 thread 종료 |

REG07은 기한 검사와 음수 sleep 방지 경로를 함께 바꾼 한 의미 변이다(기한 없는 10ms 재시도). 오류 타입이 우연히 ValueError로 바뀐 것을 검출로 세지 않는다. 원자료는 `mutation-results.json`, `reg-mutations.json`, `mut-*.log`다. 수집 오류·실행 프로세스 timeout은 유효 검출에서 제외한다.

### 19.4 파일·사본 경계

archive의 기준 파일375개를 다시 대조해 승인 9파일 밖 차이0을 확인했다(`scope-audit.json`). `tests/unit/test_storage.py`는 기준8126c1f 원문에 §16.5 diff 한 곳만 적용한 문자열과 일치하는지 따로 확인했다. 새 Root interval 계측은 시험 helper에만 있고 제품에 건강·동기화 thread를 추가하지 않았다. code·시험은 전수 실행 중 동결했다. 최종 CI 동등 결과와 9파일 LF hash는 다음 절에 붙인다.

### 19.5 CI 측정의 도달성 보강(행 축소 없음)

R01/02는 실제 PER_BLOCK 디스크를 쓰고 기본 chunk200블록/트랙을 유지한다. 매우 느린 디스크에서는 source가 6.5초 동안 수락해도 잠금 구간(1.5~4.5초) 안에 sealer의 등록까지 도달하지 않을 수 있다. 이때 sealer Root 관찰이 없다는 이유로 제품 실패를 선언하거나 busy 검증을 했다고 기록하지 않는다. 등록 BEGIN 시각을 별도로 계측해 관찰 유무를 명시한다. 구간 안 등록이 있으면 Root 보유 상한을 판정하고, 없으면 NOT_OBSERVED로 남긴다. 수락 원본 보존·회계 일치는 모든 경우 필수다. 이는 측정 사례의 도달성 구분이며 0거부/처리량 보장을 추가하지 않는 원 계약을 따른다.

핵심 busy 회귀는 R03/04의 작은 청크가 실제 잠금 중 등록을 확실히 유발하고 ACK/활성/OPEN을 확인하며, R08은 실제 잠금에서 기한·Root 보유를 확인한다. R10~12에는 각 실제 연결의 PRAGMA를 읽어 **모든 시도의 busy_timeout이 정확히0**이라는 독립 literal oracle를 추가한다. 따라서 R01/02의 부하로 등록이 구간 밖에 밀려도 busy0 제거·root-held sleep 변이를 놓치지 않는다. 기존 1,164·X4·R14와 요청90초 예산은 유지한다. 이전 전수 시도는 이 보강 전 시험이므로 중단하고 최종 사본을 다시 실행한다. 제품 코드는 이 보강으로 변경하지 않았다.

### 19.6 기존 GS-P02 wall clock fixture와 등록 기한의 분리

전수 시도에서 GS02-C-001 등을 단독 재현한 실제 오류는 `time.monotonic` AttributeError였다. GS-P02 fixture는 journal의 관찰 나이만 조작하려고 library 모듈의 `time`을 `time_ns` 하나인 SimpleNamespace로 바꾼다. 새 등록 기한이 그 wall-clock 이름 공간에 의존한 것이 원인이었다. 기존 시험은 변경하지 않는다.

등록의 기한·기다림은 명시적으로 가져온 monotonic clock/wait 함수를 사용하도록 분리했다. journal 관찰 나이의 벽시계·역행 주입이 I/O 재시도 기한을 멈추거나 늘리면 안 되므로 서로 독립한 의존성으로 둔다. 제품의 실제 기한 산술·기존 timeout·10ms 대기·busy0·권위 확인은 바꾸지 않는다. R10의 기다림 spy도 이 전용 함수 경계에서 root/registry 비소유를 확인한다. 이 수정은 승인된 public 등록 목적 안이며 GS-P02 시험·시계 규칙을 우회하거나 범위를 추가하지 않았다. 오류가 나온 전수 시도는 PASS로 세지 않고 새 사본으로 다시 검증한다.

### 19.7 최종 동결본의 선택 실행 재확인

monotonic 의존성 분리 뒤 GS-P02 unit/integration·기존 storage·seal phases **491 PASS / 69.39초**였다(`clock-related.xml`). 이 시간은 기존 회귀 포함이며 신규 네 파일 예산과 합치지 않는다. 승인된 `test_p11_open_delete_barrier` 두 분기도 **2 PASS / 0.44초**로 별도 확인했다. 기존 시험은 지정된 분기의 정확한 삭제 오류 수용 외에는 변경하지 않았다.

이후 최종 동결본의 신규 네 파일은 **1,182 PASS / 88.44초 / warning0 / skip0**(`gate3.xml`)다. unit0.886·fencing49.267·crash31.667·property5.733초, testcase 합87.553초다. 70.48→77.02→88.44초의 실제 측정을 이력으로 남긴다. 다른 세션의 시스템 부하는 통제하지 않았으며 어떤 행도 빼지 않았다. **90초 예산 요청은 여전히 C00 결정 대기**다. 기존60초를 통과했다고 쓰지 않는다.

등록 clock/wait 분리·CI 관측 도달성 보강 후 writer MUT01~10 **10/10**, REG01·REG01b·REG02~07 **8/8**, 합계 **18/18 변이 검출**을 다시 확인했다. REG01b는 busy_timeout=50ms로 잘못 둬도 R10의 실제 연결 PRAGMA literal0 단언이 잡는 추가 변형이다. 17개의 의미 결함/18개 변형을 원 계약 전체32의 완료로 세지 않는다. 수집 오류·process timeout을 유효 검출로 세지 않았고, REG07은 부모의 bounded-completion 본문 단언이 잡은 뒤 fixture가 외부 잠금을 풀어 모든 작업을 끝냈다.

최종 잠금 측정(`measurements-final.json`, `gate3.xml`)은 다음과 같다. 두 행 모두 실제 잠금 구간 안의 등록 BEGIN을 직접 관찰했다.

| 트랙 | 실제 잠금 초 | 구간 내 등록 시도 | 수락 block | 거부 block | 저장 frame | sealer root 최대 ms(구간 겹침) | writer root 최대 ms | 전체 root 최대 ms |
| ---: | ---: | ---: | --- | --- | ---: | ---: | ---: | ---: |
| 1 | 3.000555 | 182 | {'mic': 650} | {'mic': 0} | 312000 | 4.879 | 8.486 | 8.486 |
| 2 | 3.000528 | 124 | {'mic': 650, 'system': 650} | {'mic': 0, 'system': 0} | 624000 | 4.330 | 4.200 | 4.499 |

모든 수락 원본 bytes·frame 회계가 일치하고, live는 accepting·storage_failed=False·health DEFERRED였다. 제품·시험 8파일이 이 최종 사본과 일치함을 확인하고 전수 재실행 동안 동결했다. 문서는 결과를 추가하는 허용된 보고 파일이다. 앞선 중단 전수들은 성공 횟수로 세지 않는다. 최종 전수·coverage·정적 검사의 완료 수치는 아래 최종 절에서만 확정한다.

### 19.8 원 측정 스크립트의 수정 후 동시 부하 결과

G08의 같은 `probe_lock_realtime.py`를 수정 후 최종 tree에도 직접 실행했다. 두 트랙·1.5+3+2초·외부 EXCLUSIVE 잠금3초 조건 그대로이며, 최종 전수 검증과 동시 부하 상태다. 수정 전/후 모두 원 스크립트를 바꾸지 않았으므로 자체 R 측정과 구별하는 추가 증거다.

| 경로 | mic 수락/거부 | system 수락/거부 | sealer root 최대 | stop |
| --- | --- | --- | ---: | --- |
| 등록 수정 전 대조군 | 536/115 | 532/119 | 1,648.1ms | FINALIZED |
| 등록 수정 후 동시 부하 | 625/26 | 555/96 | 56.6ms | FINALIZED |

수정 후에는 accepting=True·storage_failed=False·health DEFERRED였다(`after-register-control.log`). readonly SQL로 catalog와 원본 bytes를 따로 대조해 mic300,000frame·system266,400frame, 각 수락 목록 수×480과 일치하고 원본 bytes도 전량 일치함을 확인했다(`after-register-control-audit.json`).

**수정 후 동시 부하에서도 큐 거부26·96은 남았다.** 단독 신규 gate의 거부0만 골라 전체 조건에 일반화하지 않는다. 원 스크립트 meter는 Library mutex 경로를 계측하며 R 측정은 공통 media Root도 함께 계측하므로 지표 범위도 동일시하지 않는다. 두 대조 실행의 시스템 부하를 통제하지 않아 속도 배율·인과 기여율을 주장하지 않는다. 초 단위 Root SQL busy 대기가 사라졌다는 관측과, PER_BLOCK 소비자의 fsync 대기·부하에 따른 처리량 한계가 남는다는 관측을 함께 보존한다. 17a는 17b를 완료한 것이 아니다.

## 20. G17a IMPLEMENTATION_READY — 최종 정상본 전수 PASS

작성 역할 결과를 독립 검토에 넘기는 상태다. **시간 예산 예외(기존60초 초과, 최신88.44초·요청90초)는 C00 결정 대기**이며, 이 조건을 승인됐다고 해석하지 않는다. 앞선 SCOPE_NEEDED와 중단/실패 시도는 이력이다. 범위 2건은 C00이 승인했고 제품·시험에 적용했다. 독립 검토·통합 commit/push는 작성자가 수행하지 않았다.

### 20.1 기준·파일·핵심 동작

기준 **8126c1f46e2e36350041754ec41b4b38775db6f0 + 승인9파일**이다. 새 main의 다른 단위를 검증한 결과로 일반화하지 않는다. archive의 기존375파일 대조와 제품·시험8파일 일치 감사에서 범위 밖 변경0이었다. PYTHONPATH를 사본 src로 고정했고 실제 부모·자식·변이 import 경로도 확인했다. 제품·시험은 최종 전수 동안 동결했다.

- PER_BLOCK payload sync → journal sync 완료 의미를 유지하며 media fsync와 writer 작업/종료 대기는 Root·registry·capture gate 밖이다. 실제 media write·descriptor·rename은 Root 안에서 canonical 삭제 권위를 다시 확인한다. private salvage도 같은 guard를 통한다.
- 등록 시도 전체는 실제 SQLite busy_timeout=0이고, 원래 timeout을 복원한 뒤 Root 밖에서만 BUSY/LOCKED를 기존 기한 안 재시도한다. 권위·capability·claim·상태·중복/overlap을 매 시도 다시 확인한다. Mono 기한은 journal 관찰용 wall clock과 독립한다.
- Library는 등록 대기 중 capability를 임의로 해제하지 않는다. 실제 FIFO 등록·종료 ACK가 끝나기 전에는 OPEN·active와 WRITER_ACK_PENDING을 유지한다. journal-only D 뒤 등록0, 원본 부활0과 현재 권위 검사를 확인했다.
- 기존 `test_p11_open_delete_barrier`는 승인된 한 분기에서 성공 또는 정확한 `Writer session has a deletion intent`만 허용한다. 다른 기존 단언은 보존했다.

### 20.2 최종 실행 결과

TEMP 증거는 `C:/Users/gangd/AppData/Local/Temp/recoryn-g17a-final-jdt98qb5`다. 정상 전수는 `ci3.xml`·`ci3.log`, 각 명령의 code/시간은 `ci3-results.json`, 독립 집계는 `ci3-audit.json`이다.

| 확인 | 최종 직접 결과 |
| --- | --- |
| 신규4파일 단독 | **1,182 PASS / 88.44초 / warning0·skip0** (`gate3.xml`) |
| 경우의 수 감사 | 원래1,164·X4·R14 각각 **누락0·중복0**. singleton docstring ID↔node도 별도 감사 |
| 기존 GS-P02·storage·seal 회귀 선택 | **491 PASS / 69.39초** |
| 승인된 storage 두 경쟁 분기 | **2 PASS / 0.44초** |
| 임시 사본 mutation | **18/18**(writer10 + 등록8변형/7의미). process timeout/수집 실패로 센 변이0 |
| 전체 오프라인·CI 동등 전수 | **23,980 PASS / failed0·errors0·skip0 / 1,999.71초**, process wall2,013.76초 |
| tests/ui 전체 | **1,465 PASS** |
| tests/integration 전체 | **4,072 PASS** |
| tests/property 전체 | **14,445 PASS** |
| pytest coverage | **92.37% / 85% 통과** |
| check_coverage | **7묶음 PASS**, 아래 실제 출력 |
| coverage 경계 | 임시 fixture·사본 밖 source 측정 파일0 |
| ruff check | src/recoryn·scripts·packaging·tests 전체 PASS |
| ruff format --check | 위 **197파일 PASS** |
| mypy | `src/recoryn scripts packaging`, **91 source files PASS** |

전수·coverage·ruff·format·mypy 명령은 §17.1과 같다. no cache·ResourceWarning 오류 승격·offscreen·고유 TEMP basetemp를 썼다. 최종 다섯 명령 returncode는 모두0이다. 중단했던 실행을 전수 성공 횟수에 더하지 않았다.

`check_coverage.py` 최종 출력 전문:

```text
domain: line=99.18%/95% branch=97.89%/90% PASS
capture: line=99.85%/95% branch=98.57%/90% PASS
jobs: line=99.29%/95% branch=96.23%/90% PASS
storage: line=96.15%/95% branch=91.46%/90% PASS
security: line=98.11%/95% branch=94.43%/90% PASS
content: line=99.59%/95% branch=98.75%/90% PASS
all: line=93.77%/85% branch=88.27%/80% PASS
```

### 20.3 최종 전수 안의 실제 외부 잠금 측정

이 표는 마지막 전수 실행 안의 R01/02 측정이며, 앞선 단독 gate 수치와 혼합하지 않는다. 두 행 모두 구간 내 실제 등록 BEGIN을 관찰했다. 각 트랙의 수락 목록과 원본 bytes·frame 합·거부 회계를 확인했다.

| 트랙 | 실제 잠금 초 | 구간 내 등록 시도 | 수락 block | 거부 block | 저장 frame | sealer Root 최대 ms(잠금 겹침) | writer Root 최대 ms | 전체 Root 최대 ms |
| ---: | ---: | ---: | --- | --- | ---: | ---: | ---: | ---: |
| 1 | 3.000681 | 178 | {'mic': 651} | {'mic': 0} | 312480 | 4.015 | 6.130 | 24.982 |
| 2 | 3.001382 | 155 | {'mic': 650, 'system': 650} | {'mic': 0, 'system': 0} | 624000 | 4.383 | 6.241 | 6.241 |

원 G08 스크립트의 추가 동시 부하 측정에서는 수정 후 거부26·96이 남았다는 §19.8도 보존한다. 이 차이를 지우고 "어떤 부하에서도0거부"·"소비자 처리량 해결"로 요약하지 않는다. 이번 결과는 Root의 초 단위 등록 busy 대기를 제거하고 수락 원본을 보존했다는 근거다. PER_BLOCK 소비자 자체의 sync 대기는 남고, 실제 HDD·백신·전원 차단 검증은 NOT_RUN이다. BATCHED·watermark·UI 변경과 17b는 이번 완료로 집계하지 않는다.

### 20.4 변경9파일 LF SHA-256

문서 자신의 hash는 자기 참조를 피하려고 이 창의 최종 보고에 쓴다. 나머지8파일은 다음과 같으며, 전수 사본과 일치한다.

| 파일 | SHA-256(CR 제거 LF 기준) |
| --- | --- |
| `src/recoryn/storage/chunks.py` | `ef000edf10866b6a46e423f8c35f2a2e6f5f3b130c2957477649f69df03cb7c5` |
| `src/recoryn/storage/_coordination.py` | `5bac3d361ddfdc49ab1434cab577e13b60f311c0c1c539a64a05a63ffe89be5d` |
| `src/recoryn/storage/library.py` | `c391a4e146d39f81e5e01884917b2e827c5f5d2aa0f90fcc55d154177385ff45` |
| `tests/unit/test_append_durability.py` | `225e90f4fcc3e27cc4ad81086d79ea5b9c88bbc6ba9e8e80212c2d9850c1843c` |
| `tests/integration/test_append_fencing.py` | `7b0e2995ce26d055bdb99949b44a3d03a8492cfff0d23061b3635b24d9d114df` |
| `tests/integration/test_append_durability_crash.py` | `a373684703c7403d0ae1e7c974444c36a58d2c05a143b1f4478c01594e132822` |
| `tests/property/test_append_durability_model.py` | `62c64a2d5f535c666dca86332fe2ce2200e27b9e51e3ac592d5e186e239f3e96` |
| `tests/unit/test_storage.py` | `c1c96ede0eb2ea19e34c91bdd1f12aea238d48a86eea272cf078b9e5dd792a68` |

아홉 번째 파일은 `docs/testing/g17-append-durability-cases.md`다. 승인 범위 밖 제품·시험·설정·문서와 공유 Git은 수정하지 않았다. 네트워크·설치·다운로드·실제 장치/음성/모델·vault 쓰기·하위 에이전트·pane도 사용하지 않았다.

### 20.5 C00에게 인계하는 미해결

- **시간 예산 결정:** 기존60초를 충족하지 못했다. 최종 신규4파일88.44초, 계획행 축소0, R14의 실제 잠금 관측과 teardown을 포함한다. 90초 요청은 아직 승인 전이다. 코드/정상본/coverage/정적 검사는 위와 같이 PASS이며, 시간 예외를 숨긴 전체 수락 완료로 쓰지 않는다.
- **독립 검토·통합:** C00 지정 검토자가 수정과 원 반례를 재검토하고, C00만 commit/push한다. 이 보고는 작성자 단독 최종 승인이 아니다.
- **범위 밖:** 일반 DB transaction 전체의 busy 정책을 바꾸지 않았다. 등록의 기존 기한 초과는 기존 저장 실패·부분 원본 보존 경로이며, 처리량·외부 장치 전원 내구성은 후속17b/외부 게이트다.

## 21. G17a FIX1 — G17R-01·02 수정과 재검증

### 21.1 권한·기준·독립 oracle

C00은 G17R-01·02(S1)를 같은 9파일 범위에서 고치도록 배정했고 신규 4파일 단독 예산을 90초로 승인했다. 최초 9파일이 검토 tree `2fd2bbf8`와 LF 해시까지 모두 같음을 직접 대조했다(`review-input-audit.json`). 검증 기준은 `47530a2`이며 TEMP archive에 승인 9파일만 넣었다. 공유 작업 트리의 G-P13·G-P11d·G-P12b 변경은 섞지 않았다. GS-P11a 제품·시험은 수정하지 않았다.

수정 전 다음 입력·기대를 고정하고, 기존 계획 1,164행은 유지했다. 보강은 `G17-F1-*` 별도로 감사한다.

- COST: 실제 열린 Library의 연속 append N회는 최초 파일 생성의 별도 검사 외에 전체 권위 검사 N회다. 두 sync 뒤에는 같은 프로세스 의도 세대·Library 동일성·closing을 확인한다. 블록 사이에 token을 재사용하지 않는다. owner 닫힘/교체·삭제 게시·abort는 거부하며, Library 없는 writer/기존 fake callback은 전체 검사를 유지한다.
- IO: seal read-back의 journal/payload/descriptor와 등록 identity의 descriptor/payload에 최초 읽기 PermissionError를 주입한다. 일시 오류가 해소되면 accepting·추가 submit·writer 오류 없음·수락 bytes/frame 보존·정상 종료를 대조한다. 기한 초과는 원 예외 동일성·등록0·원본 보존·복구 성공, 다른 OSError·무결성 오류는 호출1회·대기0이다.
- 경합: payload/journal fsync 안 삭제 barrier는 해당 세대 변화 뒤 새 쓰기/완료0·부활0을 확인한다. 재시도는 Root/registry/capture gate 밖이며 active seal과 실제 종료 ACK를 유지한다. 무통지 외부 프로세스 변조를 블록 중간에 즉시 검출한다고 보장하지 않는다.
- 측정: 검토자의 원 스크립트로 HEAD/수정본 순서를 교대한다. 수락=저장, 큐 거부, 역할별 Root 보유를 실제 값으로 기록하고 HDD·백신·전원 장애는 외부 게이트로 남긴다. 처리량 해결은 17b의 문제다.

### 21.2 구현 경계

G17R-01: Library가 기존 약한 참조 권위 callback에 순수 의도 세대 callback을 함께 등록한다. WP 직전 전체 검사 뒤 `(Library callback identity, _history_version)`을 포착한다. WJ/완료 직전에는 같은 cut·closing만 비교하며, cut이 다르거나 제공되지 않으면 전체 검사로 돌아간다. `_publish_intent`가 Root 안에서 세대를 먼저 올리므로 같은 프로세스의 새 의도가 중간에 허용되지 않는다. owner 닫힘/교체도 같은 token으로 통과하지 못한다. Library 없는 writer와 기존 fake는 종전의 세 차례 검사를 유지한다.

G17R-02: `retry_sealed_read`를 자기가 봉인한 bundle의 read-back과 발급된 capability의 등록 identity 재읽기에만 적용했다. PermissionError 또는 Windows sharing/lock violation(winerror32/33)만 1초 monotonic 기한·회당 최대10ms 간격으로 재시도한다. Root/registry/RecordingService gate 밖에서 기다리며 writer 작업 잠금·active seal은 유지한다. 내용·형식 오류와 다른 OSError는 즉시 전파한다. 기한 초과는 마지막 원 예외를 유지하고 등록하지 않는다. 이후 seal/등록의 기존 Root 가드가 삭제 의도·해제된 capability를 다시 판정한다. PER_BLOCK의 payload sync→journal sync 완료 의미와 두 번의 sync는 그대로다.

D/HB의 DB/journal 직접 주입 fixture는 같은 프로세스의 정식 게시 cut을 모사하도록 의도 세대도 올린다. 기존 I1·원본 보존·미등록·부활0 단언은 유지했다. 단순 fake callback은 세대를 제공하지 않으므로 기존 전체 검사 oracle도 계속 실행한다.

### 21.3 시험 oracle 정정과 재현 결과

격리 신규 시험 첫 실행은 1,203 PASS·1 FAIL, pytest93.66초(process94.21초)였다. G17-R-02에서 2트랙 큐 거부7블록(4+3)이 있었고 저장=수락은 일치했다. 주입한 EXCLUSIVE3초가 건강 checkpoint를 DEFERRED로 만들었는데, 시험은 마지막 영속 dropped0을 최종 메모리3,360frame과 같다고 잘못 요구했다. 제품 건강 코드는 바꾸지 않았다.

이 시험은 실제 offer 결과와 최종 메모리 dropped의 정확 일치를 계속 요구한다. OBSERVED면 영속 누계도 정확히 같아야 하고, DEFERRED면 영속 has_unknown=True·영속값≤최종 관찰값을 별도 확인한다. 두 값을 측정에 남겼다. 수락 bytes/frame·sealer Root 상한·ACK·실제 SQLite 재시도 구조 단언은 그대로다. 행·분모를 줄이지 않았다.

기한 초과 복구는 위치에 따라 독립적으로 판정한다. read-back 전 미게시 staging은 recovered1/adopted0, 게시 뒤 등록 identity 실패 bundle은 recovered0/adopted1이어야 한다. 두 경우 모두 등록 실패 당시 catalog0과 원본 prefix 일치, 이후 복구된4frame·PCM 일치를 확인한다.

TEMP 증거는 `C:/Users/gangd/AppData/Local/Temp/recoryn-g17a-fix1-_dx_wnz1`이다. 부모·자식 import는 사본 src로 고정했다(`origin.txt`). 아래는 검토자 `probe_g17.py`를 수정 없이 HEAD/수정본 순서를 교대해 직접 실행한 결과다. 다른 자체 pytest·변이를 동시에 돌리지 않았으며, 다른 세션/OS의 디스크 부하는 통제하지 못했다.

| 회차 | 조건 | HEAD 거부 | FIX1 거부 | 수락=저장 |
| --- | --- | --- | --- | --- |
| 1 | 1트랙 / sync 5ms / tombstone 0 | [0] | [0] | 양쪽 일치 |
| 2 | 1트랙 / sync 5ms / tombstone 0 | [43] | [0] | 양쪽 일치 |
| 3 | 1트랙 / sync 5ms / tombstone 0 | [270] | [230] | 양쪽 일치 |
| 4 | 1트랙 / sync 5ms / tombstone 0 | [204] | [215] | 양쪽 일치 |
| 5 | 2트랙 / sync 0ms / tombstone 0 | [36, 361] | [2, 90] | 양쪽 일치 |
| 6 | 2트랙 / sync 0ms / tombstone 1000 | [0, 14] | [0, 0] | 양쪽 일치 |

HEAD 거부0이었던 첫5ms 조건에서 수정본도0이었다. 뒤 포화 회차는 수정본230/215 대 HEAD270/204로 양쪽 모두 거부가 있었다. 모든 행의 수락 PCM/frame 보존·정상 종료는 일치했다. 네 회차 전부 무거부 또는 모든 포화 회차에서 더 나았다고 주장하지 않는다. 2트랙 무지연/삭제1000건도 표의 값을 그대로 보고한다. 두 sync의 소비자 대기가 사라지는 것은 아니며17b의 처리량 문제가 남는다. 실제 HDD·백신·전원 장애는 NOT_RUN이다.

검토자의 identity·read-back PermissionError 원 스크립트도 각각 exit0, storage_failed=False·60블록 수락·거부0·수락240frame=복구catalog240frame이었다. 원 스크립트는 stop 대신 join_writer 뒤 관리 복구하므로 INTERRUPTED는 그 명시 복구의 상태다. 정식 IO5행은 오류 해소 뒤 다시6블록을 제출해 accepting·writer 오류 없음·정상 FINALIZED·48frame·전체 PCM 일치를 별도로 확인했다.

정상 gate2의 SQLite EXCLUSIVE3초 측정은 1/2트랙 모두 거부0·수락651블록/트랙·저장312,480/624,960frame·원본 일치였다. 잠금 중 sealer Root 최장은4.439/3.621ms, 전체 Root 최장은9.566/19.012ms, writer Root 최장은9.566/5.944ms였다. 건강은 DEFERRED·has_unknown=True로 표시됐다(`gate2-metrics.json`).

### 21.4 ID 감사·변이·단독 시간

기존 계획1,164 + 이전 보강18 + FIX1 별도22 = 신규4파일 **1,204 node**다. FIX1은 COST2·READ(오류5×해소/만료2)10·OWNER1·CLOSE2·IO5·EXPIRE2로22다. 제품 parser/cache/성공 문자열로 expected를 만들지 않았다. OWNER 단일 node는 `test_continuation_owner_close_cannot_reuse_an_open_library_receipt`와 명시 매핑했다. F의17b 전용 제외(022~026)는 유지했다. JUnit에서 독립 산식의 계획1,164행 누락·예상 밖 ID·중복0과 보강22행을 확인했다(`case-audit.json`).

격리 정상본 단독은 **1,204 PASS, pytest96.76초(process97.29초)**다. 파일 testcase 합은 unit1.551 / fencing56.147 / crash32.226 / property5.825초, 추가22행만2.785초였다. 승인90초를6.76초 초과하여 C00에게100초 예산안을 질문했고 답 전에는 승인으로 기록하지 않는다. 행 축소는 없다. 최초 실패 실행93.66초와 정상본을 구분한다.

기존 writer10/10·등록8/8 재검출, FIX1 F01~F12 **12/12** 검출이다(`mutation-results.json`, `reg-mutations.json`, `fix-mutations.json`, `F12.log`). 합친30회는 재대조·동일 의미를 포함한 실행 건수이며30개의 독립 결함이라고 세지 않는다. F01/02는 journal/완료 fence 생략, F03 세대 변경 무시, F04 closing 무시, F05/06 read-back/identity 재시도 제거, F07 기한 제거, F08 다른 OSError까지 재시도, F09 전체 재검사 비용 회귀, F10 active+unhold 양쪽의 in-flight flag 무시, F11 Root 안 read-back 재시도, F12 무결성 오류까지 재시도다. AssertionError/정확 DID NOT RAISE로 검출했고 수집·timeout을 검출로 세지 않았다.

**추가 생존과 보완을 구분한다.** F10 최초 형태(기존 A4처럼 active 식의 `or _seal_in_progress`만 제거)는 기존 read-back 시험에서 SURVIVED였다. 그 구간에는 `_sealing=True`가 남아 있어 이 시험만으로 차이를 보지 못했다. 이를 전체 상태 공간의 동치라고 보았던 초기 추정은 철회했다. 원 생존은 `F10-active-clause-only-survived.log`·`fix-mutations-first-attempt.json`에 보존했다.

TEMP의 독립 barrier 반례(`test_final_handoff_probe.py`)는 capability 게시 뒤 `seal_chunk` finally 진입 직전, Root/registry를 놓은 지점에 seal thread를 멈춘다. 다른 thread가 게시된 capability를 얻어 release한 뒤 active·삭제 보류를 확인한다. `_sealing=False`여도 `_seal_in_progress=True`가 실제 함수 종료 ACK까지 보호해야 한다. 정상본은 **1 PASS·0.38초**(active 유지·DELETE_PENDING·final bytes 유지·종료 뒤 inactive), active 단일 항만 제거한 사본은 active=False AssertionError로 검출됐다(0.49초). 원 생존·복합 F10·새 단일 항 검출을 섞지 않는다(`normal-handoff.log`, `active-clause-only-handoff.log`, `handoff-results.json`, `handoff-probe.py`). 이 TEMP 보강1행은 제출4파일의1,204행/기존1,164에 합산하지 않는다.

정적 검사는 ruff check·format·mypy 모두 exit0(209 files already formatted,93 source files)이다. 전수·coverage는 진행 중이며 종료 뒤 다음 절에 실제 결과를 추가한다. 문서 추가절의 PowerShell 전달 인코딩 오류는 확인 후 기존§1~20 바이트를 보존하고 이§21만 UTF-8로 바로잡았다. 제품·시험 코드와 검증 입력에는 영향이 없다.

### 21.5 최종 CI 동등 전수·정적 결과

고정 `47530a2 + 승인9파일` TEMP 사본에서 다음 명령을 직접 실행했다. `PYTHONPATH=사본/src`, `QT_QPA_PLATFORM=offscreen`, `PYTHONDONTWRITEBYTECODE=1`, 고유 OS TEMP basetemp와 별도 coverage data를 사용했다. 부모·자식 import 경로, coverage 파일의 소속을 대조했다.

```text
python -m pytest -q -p no:cacheprovider -W error::ResourceWarning --cov=recoryn --cov-branch --cov-report=json:coverage.json --cov-fail-under=85 --basetemp=<고유 TEMP> --junitxml=<TEMP>/ci.xml
python scripts/check_coverage.py coverage.json
python -m ruff check --no-cache src/recoryn tests scripts packaging
python -m ruff format --no-cache --check src/recoryn tests scripts packaging
python -m mypy --no-incremental src/recoryn scripts packaging
```

**26,510 PASS / failure0·error0·skip0 / 경고 요약 없음**, pytest **2,203.40초**, process **2,220.03초**, 전체 combined coverage **92.68%**다. JUnit을 직접 합산했다: contract56·e2e81·integration4,786·property14,452·release363·UI2,949·unit3,823. 신규4파일1,204행과 관련 G-P04/05/07/08/15·기존 UI 회귀를 모두 포함한다. coverage.json의 파일 전부가 `src/recoryn/` 아래이며 TEMP fixture·작업 트리 src 혼입0이다(`final-audit.json`).

check_coverage 출력 전문:

```text
domain: line=99.18%/95% branch=97.89%/90% PASS
capture: line=99.85%/95% branch=98.57%/90% PASS
jobs: line=99.19%/95% branch=95.61%/90% PASS
storage: line=96.21%/95% branch=91.55%/90% PASS
security: line=98.11%/95% branch=94.43%/90% PASS
content: line=98.98%/95% branch=99.02%/90% PASS
all: line=94.03%/85% branch=88.70%/80% PASS
```

ruff check·format check·mypy 모두 PASS(209파일 이미 형식 적합,93 source files). 정상 gate2에서 검증한 제품·시험8파일이 전수 사본 및 현재 제출본과 LF 기준으로 같음을 다시 확인했다. 기준 archive와 사본의 제품·시험·문서 차이는 승인9파일뿐이다. FIX1 자체 수정은 그중 제품3·시험2·문서1의6파일이며 crash/property/test_storage의3파일은 1차 제출 그대로다. 기존 test_storage의 승인된 좁은 두 순서 허용5줄도 추가로 넓히지 않았다.

### 21.6 append 비용 추가 대조

전수와 coverage 종료 후 다른 자체 시험·변이 없이 검토자 `probe_g17_append_cost2.py`를 수정 없이 실행했다. 한 writer에서480frame×2,000 append, sync 앞5ms, 완료 tombstone0, HEAD→FIX1·FIX1→HEAD의 두 쌍이다. 원시 값은 `append-cost.json`·`cost-<회차>-<variant>.log`에 보존했다.

| 순서 | HEAD 중앙값 / p99 / Root 합계÷append(ms) | FIX1 중앙값 / p99 / Root 합계÷append(ms) |
| --- | --- | --- |
| HEAD→FIX1 | 16.220 / 21.411 / 16.553 | 15.708 / 19.107 / 0.623 |
| FIX1→HEAD | 15.410 / 18.499 / 15.693 | 15.749 / 18.659 / 0.660 |

수정본이 매 회 더 빠르다고 일반화하지 않는다. 이 두 쌍에서 기존 약1ms 증가가 반복되지 않았고, 전체 권위 검사 회수는 정식 COST node가4회 append→4회로 직접 확인했다(standalone은12회). Root가 두 sync를 보유하지 않는 목적도 계수/시간으로 확인했다. 소비자는 여전히 두 sync를 기다리므로 느린 디스크에서 영구 거부0을 보장하거나17b 처리량 완료라고 닫지 않는다.

### 21.7 제출 파일·해시·남는 게이트

아래8파일의 LF SHA256은 전수 사본과 제출본이 같다. 문서 자체 해시는 최종 append 후 이 창과 TEMP `delivery-hashes-final.json`에 보고한다. 1차 보고§1~20의 원 바이트는 그대로 보존했다.

| 파일 | SHA256(LF) |
| --- | --- |
| `src/recoryn/storage/chunks.py` | `e499f0bdd5c7bb8c2b427836159edda5508ec0d3a63df3be9b6e9b158986f316` |
| `src/recoryn/storage/_coordination.py` | `b0d86a066d80f6e1af45a80e31cd90101d9ca060dacd4ea18e17551a414fda15` |
| `src/recoryn/storage/library.py` | `df54dcb336db11c472eb3197b867a82061d29f8ae96aa5e62cc14c38a732d3dd` |
| `tests/unit/test_append_durability.py` | `791dada1b800fbd6bf6a9e254313771dcafb4aaacbb8aad30a16f05288087113` |
| `tests/integration/test_append_fencing.py` | `9596e2909bde4eecfc301ae4ecc6a2705d6220dd4650a2f8e0f5c092271bf60e` |
| `tests/integration/test_append_durability_crash.py` | `a373684703c7403d0ae1e7c974444c36a58d2c05a143b1f4478c01594e132822` |
| `tests/property/test_append_durability_model.py` | `62c64a2d5f535c666dca86332fe2ce2200e27b9e51e3ac592d5e186e239f3e96` |
| `tests/unit/test_storage.py` | `c1c96ede0eb2ea19e34c91bdd1f12aea238d48a86eea272cf078b9e5dd792a68` |

- 정상본 단독96.76초는 승인90초를6.76초 초과한다. C00에게100초 예산을 요청한 상태이며 답 전에는 시간 게이트 PASS로 간주하지 않는다. 행 축소0이다.
- G17R-01·02의 수정과 위 자체 검증 결과를 제출하며 최종 RECHECK/수용은 독립 검토자·C00이 한다. 단일 active 항의 최초 생존과 새 TEMP 반례 검출도 모두 공개했다.
- 실제 HDD·백신·전원 차단은 NOT_RUN, PER_BLOCK 처리량·BATCHED 제품 결정은17b/외부 게이트다.
- GS-P11a는 계약 재대조·시험 설계 상태로 돌아간다. G-P17a push·C00 시작 신호 전 library.py를 GS-P11a 목적으로 수정하지 않는다.


## 22. G-P17a FIX2 — 재확인 시험 oracle 보강

### 22.1 C00 결정과 입력 분할

G17R-03(S2)은 외부 SQLite 배타 잠금으로 건강 checkpoint가 연기된 뒤 메모리 상태가 OBSERVED로 돌아와도 영속 기록은 미상일 수 있는 경우다. C00 지시에 따라 영속 `has_unknown`을 판정 기준으로 삼는다. False이면 영속 drop과 실제 offer 거부로 센 정확 메모리 누계가 같아야 한다. True이면 영속 drop은 정확 누계를 넘지 않아야 하며 완전한 0 유실로 표시하면 안 된다. 메모리가 DEFERRED이면 영속 has_unknown은 반드시 True다. 수락 원본 바이트·frame 회계, 종료 ACK, 등록 재시도의 root 보유 조건은 유지한다. 정상 stop 뒤 영속 누계를 완전히 수선하지 않는 제품 문제는 G-P08b(S2) 인계이며 이 단위에서 건강 제품 코드를 고치지 않는다.

G17R-04(S3)은 봉인 게시 뒤 capability 해제부터 seal 호출 종료까지의 창이다. 기존 read-back 시험에서는 `_sealing`과 `_seal_in_progress`가 함께 참이어서 후자 하나를 제거한 A4를 검출하지 못했다. TEMP 반례를 정식 `G17-F2-A4` 행으로 옮겨 registry 진입 직전 worker를 멈추고 capability를 해제한다. 독립 기대는 삭제가 DELETE_PENDING으로 남고 파일이 보존되며, 봉인 호출 종료 뒤에만 active가 해제되는 것이다. `_seal_in_progress` 항 하나만 제거한 변이로 대조한다.

기존 계획 분모 1,164행은 그대로다. 이전 보강 40행에 G17-F2-A4 1행을 추가해 신규 네 시험 파일의 실행 node는 1,205개가 된다. G17-R-01/02의 1·2트랙 분할은 유지하며, 새 시험 시간 예산은 C00 승인 100초다. 실제 HDD·백신·전원 장애는 계속 외부 게이트다.


### 22.2 직접 재현과 정상본·변이 대조

증거 폴더는 OS TEMP `recoryn-g17a-fix2-qqmtd6x0`다. 기준 HEAD는 `f4f94b7fb2b0f3a1d3fe79cfbdc81c72facea17e`이며 archive에 승인 G-P17a 9파일만 복사했다. GS-P06·G-P13·G-P12b 작업 트리 변경은 포함하지 않았다. 부모·자식의 chunks import가 사본 src인 것을 `imports.log`로 확인했다. FIX2 자체 수정은 시험2파일과 이 문서의 끝 절뿐이다. 제품3파일, crash/property/test_storage 파일은 FIX1 해시 그대로다.

- 새 네 파일: 첫 실행 **1,205 PASS / 102.79초**, 다른 자체 검증을 겹치지 않은 재측정 **1,205 PASS / 71.45초**(process 71.913초). 첫 초과 측정도 보존했으며 행 축소는 없다. C00 승인 예산은100초다. `gate.xml`, `gate2.xml`, `gate*-result.json` 참조.
- 경우의 수 감사: 계획1,164행 관측1,164, 누락·예상외·중복0. 보강41행을 포함한 실행 node는1,205다. 새 A4 행은 함수 docstring의 ID로 식별한다(`case-audit.json`).
- 정상 A4는 위 gate에서 PASS. TEMP 사본에서 `has_active_writer`의 `or w._seal_in_progress` 한 항만 제거하면 같은 정식 node의 active 단언에서 **1 FAIL / 0.50초**로 검출됐다. 기존 `_sealing` 항은 그대로다(`A4.log`, `A4-result.json`).
- R03 결정적 재현(`prove-r03.py`, `r03-controlled.log`): 실제 queue offer의 byte 용량을 매11번째 블록에만 일시0으로 주어, 실제 큐 거부 회계와 원본 writer·sealer를 그대로 거쳤다. 2트랙 각각591블록 수락·59거부, 저장567,360frame으로 수락과 일치했다. 정확 메모리 drop56,640frame, 마지막 영속 drop8,640frame·has_unknown=True, 종료 후 메모리 상태OBSERVED였다. 새 정식 R02의 미상 분기·상세 불완전·count_complete=False·known_loss_frames=None 단언이 통과했다. 이전 메모리 상태 분기의 정확 일치 기대라면 8,640≠56,640으로 실패한다. 이는 새 계획행이 아닌 TEMP 대조 증거다. 외부 잠금3.000초 동안 등록시도180회, sealer root 최장3.241ms였다.
- 재측정 gate의 외부 잠금3초 정상 경로는 1·2트랙 모두 거부0, 저장312,480/625,920frame으로 수락과 일치했다. 등록시도191/182회, sealer root 최장5.022/4.729ms. 메모리 누계와 영속 미상 표시는 독립으로 검증했다.
- ruff check·format check(209파일), mypy(93source) PASS. `-p no:cacheprovider`, `-W error::ResourceWarning`, offscreen, 고유 basetemp를 썼다. 최종 전체 회귀·coverage 결과는 다음 절에 기록한다.

- R03의 정확 분기 대조(`prove-r03-exact.py`, `r03-exact.log`): 같은 정식 R02 함수를 쓰되 SQLite 배타 잠금만 제거하고 관찰 창은 유지했다. sequence43에서 트랙별1블록만 실제 offer 용량 거부를 유도했다. 각각649수락·1거부, 저장623,040frame으로 수락과 일치했고, 메모리OBSERVED·영속has_unknown=False·양쪽drop960frame이었다. 따라서 미상 분기뿐 아니라 has_unknown=False일 때의 정확 일치 분기도 실제 제품 경로로 통과했다. 출력의 상속된 `lock_seconds` 필드는 이 대조에서는 잠금이 아닌 3초 관찰 창이다.


### 22.3 CI 동등 전체 회귀 최종 결과

고정 `f4f94b7 + G-P17a 9파일` 사본에서 아래 명령을 직접 실행했다. PYTHONPATH는 사본 src, 부모·자식 import는 사본, coverage data·basetemp는 고유 OS TEMP로 고정했다.

```text
python -m pytest -q -p no:cacheprovider -W error::ResourceWarning --cov=recoryn --cov-branch --cov-report=json:coverage.json --cov-fail-under=85 --basetemp=<고유 TEMP>/ci-bt --junitxml=<TEMP>/ci.xml
python scripts/check_coverage.py coverage.json
```

**26,551 PASS / failure0·error0·skip0 / 경고 요약 없음**, pytest **1,950.75초**, process **1,964.58초**, combined coverage **92.70%**다. JUnit을 직접 합산하면 contract56·e2e81·integration4,801·property14,452·release363·UI2,949·unit3,849다. coverage.json의 80개 파일 모두 사본 src/recoryn 아래이며 TEMP fixture·작업 트리 소스 혼입0이다. `ci.log/xml`, `ci-result.json`, `coverage.log`, `final-audit.json`에 원시 증거를 보존했다.

check_coverage 출력 전문:

```text
domain: line=99.18%/95% branch=97.89%/90% PASS
capture: line=99.85%/95% branch=98.57%/90% PASS
jobs: line=99.20%/95% branch=95.65%/90% PASS
storage: line=96.21%/95% branch=91.55%/90% PASS
security: line=98.11%/95% branch=94.43%/90% PASS
content: line=98.98%/95% branch=99.02%/90% PASS
all: line=94.05%/85% branch=88.75%/80% PASS
```

정상본 신규 네 파일 전수1,205 PASS, 계획1,164행 감사0, A4 단일항 변이 검출, R03의 미상/정확 분기 대조, 전체 오프라인·UI 회귀, ruff·format·mypy가 모두 완료됐다. 새 시간 예산100초는 다른 자체 검증과 겹치지 않은 재측정71.45초로 확인했고, 초회102.79초도 이력으로 남겼다. 기존 mutation은 FIX1 이력에 보존하며 FIX2에서 모두 새로 재실행했다고 집계하지 않는다. 이번 새 변이 실행은 A4 한 항 제거1건이다.

### 22.4 제출 범위와 남은 경계

단위 전체는 승인9파일이며, FIX2에서 추가로 바꾼 것은 test_append_durability.py·test_append_fencing.py·이 문서의 끝 절3파일이다. 아래 제품·시험8파일은 전체 검증 사본과 제출 파일이 바이트 단위로 같다. 제품3파일과 나머지 시험3파일은 FIX1에서 변하지 않았다. 문서의 FIX1 전체 내용은 원 바이트 prefix로 보존했다(LF SHA256 `b9d82752aedbd6c5734ab9e287ee8711194764e0dc17e12101a6894ee10b6b82`). 문서 자체 최종 LF SHA256은 이 창과 TEMP `delivery-hashes.json`에 보고한다.

| 파일 | SHA256(LF) |
| --- | --- |
| `src/recoryn/storage/chunks.py` | `e499f0bdd5c7bb8c2b427836159edda5508ec0d3a63df3be9b6e9b158986f316` |
| `src/recoryn/storage/_coordination.py` | `b0d86a066d80f6e1af45a80e31cd90101d9ca060dacd4ea18e17551a414fda15` |
| `src/recoryn/storage/library.py` | `df54dcb336db11c472eb3197b867a82061d29f8ae96aa5e62cc14c38a732d3dd` |
| `tests/unit/test_append_durability.py` | `c10ff966d28b51cf84e819d18352c93418abf3497d4c38a3c06c4588db63c5fb` |
| `tests/integration/test_append_fencing.py` | `57e116486a8c0d025f8c4acfcc6cc2b7070e92ff52b3e39fd4db8dda255d2b0e` |
| `tests/integration/test_append_durability_crash.py` | `a373684703c7403d0ae1e7c974444c36a58d2c05a143b1f4478c01594e132822` |
| `tests/property/test_append_durability_model.py` | `62c64a2d5f535c666dca86332fe2ce2200e27b9e51e3ac592d5e186e239f3e96` |
| `tests/unit/test_storage.py` | `c1c96ede0eb2ea19e34c91bdd1f12aea238d48a86eea272cf078b9e5dd792a68` |

- G17R-03·04의 작성자 대응을 제출한다. 독립 RECHECK·수용은 검토자/C00의 역할이며 이 문서로 자체 최종 승인하지 않는다.
- 정상 stop 뒤 연기된 건강 누계의 최종 수선은 C00 지정 G-P08b(S2) 후속 그대로다. FIX2의 건강 제품 코드 수정0이다.
- PER_BLOCK 기본·내구성 의미는 바뀌지 않았다. 처리량 개선 완료를 주장하지 않으며17b·실제 HDD/백신/전원 장애 외부 게이트는 그대로다.
- GS-P06 10파일은 중단 시점 LF 해시와10/10 동일하다(`gs06-preservation.json`). GS-P06으로 복귀하며 기존 SCOPE_NEEDED(app/media.py 경계와 B008 실현 가능 상한) 결정 요청은 유지한다. GS-P11a의 library.py 구현은 G-P17a push·C00 시작 신호 전까지 착수하지 않는다.
