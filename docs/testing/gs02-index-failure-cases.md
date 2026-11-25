# GS-P02 삭제 의도 색인 실패·settle 경우의 수와 계약안

2026-11-25, 작성 w5:p8 Codex. **계약 승인 대기 / 제품·시험 수정 0 / 시험·mutation 실행 0.** C00이 승인한 S3 PLAN의 GS-P02(G15c)를 구현하기 위한 제안이다. 이번 쓰기는 본 문서 하나에 한정한다.

## 1. 요구와 착수 경계

대상은 다음 세 문제다.

1. G15R-05: job_authority가 journal을 읽은 뒤의 시각으로 색인을 settled로 표시한다. 목록을 만들기 전에는 settle되지 않았던 관찰이 긴 읽기 뒤 settle된 증거로 승격될 수 있다.
2. 삭제 이력 전체 검증이 실패하면 색인이 None으로 남고, GUI tick의 chunks/get_session이 같은 실패를 root mutex 안에서 반복 검증한다. 같은 settle된 stamp의 검증 실패를 재사용해 빠르게 fail closed해야 한다.
3. _live에서 호출되는 settle 전 journal 이름 목록은 root mutex 안에서 만들어진다. GC-P02 구조 판정과의 경계를 명확히 해야 한다. 다른 경로의 순회·본문 읽기·remove_tree를 같은 예외로 허용하지 않는다.

착수 순서는 C00 결정대로 **G-P08 push → GS-P02 → G-P17a → G-P09a**다. G-P08 push 전에는 제품·시험을 수정하지 않는다. 착수 시 G08 최종 commit과 변경 파일 hash를 다시 고정하고, 아래 근거와 다른 부분을 먼저 재대조한다. 현재 작업 트리의 G08/G11b를 통합된 구현으로 계산하지 않는다.

## 2. 읽기 근거와 관측 출처

제품·기존 시험의 줄번호는 git show b925520:<경로> 기준이다. 과거 실행 숫자는 문서 인용이며 이번 새 측정이 아니다.

| 근거 | 직접 확인한 내용 또는 문서 인용 |
| --- | --- |
| src/recoryn/storage/library.py:125~137 | 내부 _history_version, 검증된 _intent_journal/stamp/names/settled, capture 전용 _journal_listing이 존재한다. |
| src/recoryn/storage/library.py:196~287 | job_authority는 root 밖 journal 선읽기 뒤 root 안에서 version/stamp를 대조한다. 그러나 :236의 settle 계산 시각은 선읽기 뒤이고 :255가 기존 색인에도 그 결과를 쓴다. yield 동안 호출자의 짧은 Job transaction을 보호하는 기존 계약은 이번에 바꾸지 않는다. |
| src/recoryn/storage/library.py:338~367 | _read_journal은 본문·schema·이름·세대를 검증한다. _journal_prefetch는 root 밖에서 이를 읽되 실패를 None으로 돌려준다. parser를 별도로 복제할 필요가 없다. |
| src/recoryn/storage/library.py:369~405 | stamp는 dev/ino/mtime_ns, _STAMP_SETTLE_NS는 2.5초다. _list_journal은 목록 전 시각과 목록 뒤 stamp를 검사한다. _index_current는 settled 전 이름을 다시 열거한다. |
| src/recoryn/storage/library.py:408~434 | 전체 색인 재검증과 실패 뒤 None 설정이 있다. 검증 실패를 재사용하는 상태는 없다. |
| src/recoryn/storage/library.py:448~492 | capture는 이름과 자기 세션 DB 행만 본다. 다른 세션의 손상 본문 때문에 녹음을 중단시키지 않는다. .tmp는 자기 세션의 미완료 의도일 수 있어 거부한다. |
| src/recoryn/storage/library.py:501~529 | 관리 조회는 prefetched 이력을 사용한다. 실패/충돌이면 root 안 재읽기 경로가 있다. 전체 관리 검증을 실패 cache로 생략하는 변경은 허용하지 않는다. |
| src/recoryn/storage/library.py:538~550, :593~607 | _live의 실패는 닫힌 이력 확인 불가이고 get_session/chunks 계열에서 쓰인다. list_sessions는 별도 선읽기로 전체 검증한다. |
| docs/reviews/g15-seal-mutex-review.md:307~324(RECHECK 1) | G15R-05 반례: 목록 뒤 같은 tick의 의도 추가, 3초 지연, job_authority 뒤 append 수락. 단일 writer 계약 밖의 외부 변경 조건이라는 S3 한정을 함께 인계한다. |
| docs/reviews/g15-seal-mutex-review.md:328~337(RECHECK 1) | 외부 손상 시 GUI tick root 보유 0.5~0.6초는 검토자 관측이다. 실패 cache는 settle 규칙을 따르고 capture에는 적용하지 말 것, 이름 목록 예외는 deletion-journal만이라는 권고다. |
| docs/testing/g15-seal-mutex-cases.md:1211~1224 | 첫 검증/settle 전 비용, 제자리 내용 수선의 cache 한계, 좁은 이름 열거 예외와 mutex 밖 목록 대안이 이미 구분돼 있다. |
| tests/integration/test_seal_mutex.py:1053, :1144, :1219 | 외부 변경 fail closed, tick/녹음, 다른 세션 journal I/O 오류와 capture 독립성 시험이 있다. 새 cache·G15R-05 자체 oracle는 별도 보강한다. |
| tests/integration/test_pending_deletion_restart.py:1122~1144 | GC-P02는 scandir/listdir로 바꾼 무거운 순회까지 관찰한다. 기존 관리 동작의 구조 단언을 약화하지 않는다. |

G08의 건강 DEFERRED, G17의 sync ACK, G09의 schema/backup은 다른 계약이다. 삭제 권위 확인 불가를 이들 상태의 성공·유효 권한으로 해석하지 않는다.

## 3. 권고 계약

### 3.1 권위와 메모리 상태

- DB deleted_sessions와 deletion-journal이 정본이다. 이 단위에서 새 DB 표·파일·schema version·backup 구성요소를 만들지 않는다.
- 정상 색인과 검증 실패 cache는 모두 **Library 인스턴스의 일시 메모**다. failure cache를 journal 손상 수선이나 tombstone 삭제의 근거로 사용하지 않는다. 실패 cache가 유효하면 관리 조회는 기존의 DELETION_HISTORY_UNAVAILABLE로 거부하고 Job 권위 조회는 HISTORY_UNAVAILABLE을 반환한다. 실패를 빈 dict·빈 이름 집합·VALID로 바꾸지 않는다.
- 실패 cache에는 닫힌 분류와 관찰 metadata만 둔다. 예외 객체·repr·임의 경로·원문 journal bytes·비밀을 보존하지 않는다. 구현상 최소 개념은 stamp, 목록 전 관찰 시각, _history_version, 관찰 세대, 실패 분류다. None을 정상 빈 이력과 같은 의미로 재사용하지 않는다.
- 기존 정상 색인의 stamp와 실패 cache의 stamp를 혼용하지 않는다. 검증 실패를 채택하면 그 관찰에 대응하는 정상 관리 색인은 무효다. capture 이름 cache는 별개다.

### 3.2 settle과 관찰 게시

관찰의 순서는 공통으로 다음을 따른다.

1. 검증/목록을 시작하기 전에 stamp S0와 관찰 시각 t0, 내부 history version V0 및 관찰 세대 E0를 캡처한다.
2. 필요한 이름 목록/본문을 관찰한다. 전체 본문 선읽기의 기존 root 밖 경로를 유지한다.
3. 게시 구간에서 현재 stamp·history version·관찰 세대가 S0/V0/E0와 일치하는지 재확인한다. 일치하지 않으면 그 결과를 색인이나 실패 cache의 최신 관찰로 게시하지 않는다. 재시도는 기존처럼 bounded로 하고 소진 시 fail closed다.
4. settled는 **t0 - S0.mtime_ns > 2,500,000,000**일 때만 참이다. 정확히 경계는 false다. 미래 mtime·시계 역행/불확실성은 settle 근거가 아니다. 읽기가 오래 걸려 종료 시점에 경계를 넘었어도 false다.

job_authority의 fresh/reuse 양쪽에 같은 규칙을 적용한다. reuse라고 관찰 전 시각 검사를 생략하거나 기존 false를 목록 뒤 시각으로 true로 바꾸지 않는다. 기존 true를 재사용하려면 현재 stamp/version에 대응하는 기존 유효 관찰이어야 한다.

E0는 DB version이 아니라 오래된 메모리 검증 결과의 역순 게시를 막는 내부 토큰이다. 동일 S/V에서 검증 성공·실패가 경쟁해도 더 오래 시작한 결과가 새 관찰을 덮지 않도록 한다. 구현은 기존 증거의 재사용이나 이에 동등한 내부 세대 방식 중 단순한 것을 택하되, 독립 race oracle를 통과해야 한다. DB transaction·JobStore API·잠금 순서를 추가하지 않는다.

### 3.3 실패 cache의 사용·무효화·수선

| 조건 | _live 계열 읽기 | 전체 관리 재조회/Job 권위 | capture |
| --- | --- | --- | --- |
| 현재 S/V/E에 일치하는 settled 실패 관찰 | stat/짧은 metadata 대조 뒤 즉시 이력 확인 불가. journal 본문 재읽기 0 | cache를 성공으로 보지 않는다. 명시 관리 재조회는 아래 fresh 검증을 수행한다. Job 권위는 적합한 실패 관찰이면 HISTORY_UNAVAILABLE로 답할 수 있다. | 관리 실패 cache를 보지 않음 |
| 아직 settle 전 실패 | settled 실패 cache로 재사용하지 않음. 새 관찰은 기존 fail-closed 의미를 유지 | fresh 관찰, 오류를 허용으로 바꾸지 않음 | 기존 이름/자기 DB 규칙 |
| stamp 또는 history version 변경 | 예전 실패 cache 무효. 예전 성공/실패를 새 권위로 게시하지 않음 | fresh 관찰. 변경 중 관찰은 폐기/유한 재시도 | 자기 의도는 즉시 거부 |
| 같은 stamp에서 본문/권한만 수선 | 자동 성공 승격 없음. 기존 실패가 남는 것은 보수적 | list_sessions/pending_deletions 등 **사용자가 요청한 새 관리 조회**는 실패 cache를 우회해 본문 전체를 검증한다. 성공 관찰을 안전하게 게시한 뒤 실패 cache 해제 | 다른 세션의 본문 수선 여부를 검사하지 않음 |
| close/reopen | 메모리 cache 폐기 | 새 열기에서 전체 검증. 손상된 채 열면 기존처럼 실패 | 이전 인스턴스의 cache를 승계하지 않음 |

시간 TTL 만료만으로 성공으로 바꾸거나 실패를 빈 이력으로 치환하지 않는다. 정상 관리 조회는 전체 본문 검증 계약을 보존한다. list_sessions/pending_deletions가 실패 cache로 본문 검증을 건너뛰면 제자리 손상 감지 계약이 약해지므로 금지한다. 명시 새로고침이 성공하면 같은 stamp의 권한/내용 수선도 회복할 수 있어야 하며 “재시작만 가능”으로 숨기지 않는다.

구현상 새 public API를 추가하지 않고 기존 관리 재조회 경로를 수선/관찰 게시 경로로 재사용하는 것을 권고한다. private 선읽기 결과를 관찰 metadata가 있는 내부 DTO로 정리할 수 있다. 외부에서 사용하는 journal parser·별도 lock·두 번째 Library를 만들지 않는다.

### 3.4 이름 목록 위치: 권고 A와 대안 B

**권고 A — 좁은 이름 목록 예외를 명시한다.** 작은 GS-P02에서는 기존 capture/_live 잠금 의미를 유지한다. root mutex 안에서 허용할 유일한 열거는 검증한 root/deletion-journal의 **직접 항목 이름**을 얻는 한 단계 목록이다. 항목을 열거나 stat/is_file/is_dir로 조사하지 않고 재귀하지 않는다. 이 경계는 이미 G15에서 사용 중이며 새 광범위 예외가 아니다.

- 예외는 정확한 deletion-journal 디렉터리 정체성과 이름 열거만 해당한다. basename만 같은 다른 디렉터리·자식 디렉터리·sessions·staging·derived·unknown root에는 적용하지 않는다.
- Path.iterdir/os.scandir/os.listdir 중 표현만 바꿔 본문 순회를 예외로 위장할 수 없다. read_json·open·hash·remove_tree와 항목별 metadata probe는 이 예외가 아니다.
- 기존 GC-P02 관리 동작에서 무거운 순회 0이라는 단언은 그대로 둔다. 새 GS02 구조 시험은 _live의 현재 이름 목록에만 좁은 예외를 인정하고, 같은 방식으로 다른 디렉터리를 열거한 mutant를 거부한다.
- 이 예외 자체가 이름 목록의 실시간 상한이나 첫 손상 검증의 root 보유를 해결했다는 뜻은 아니다.

**대안 B — 관리 경로의 이름 목록도 mutex 밖으로 이동한다.** 목록 전 시각·stamp/version 스냅샷→root 밖 목록→root 안 stamp/version 재확인을 지켜야 한다. 새 검증이 불가능한 순간 fail closed하며, 오래된 목록을 최신으로 승격하지 않는다. 현재 여러 _live 호출이 기존 root/transaction 안에 있으므로 단순히 lock을 풀었다가 되잡는 수정은 금지한다. 이 안을 고르면 호출자별 preflight/재검증 범위와 파일 수를 먼저 다시 승인받는다. capture 임계 경로의 lock 해제는 별도 I1 계약 없이 수행하지 않는다.

### 3.5 성능 범위와 남는 한계

이번 권고 A는 **settled된 동일 실패가 반복되는 hot 조회**의 전체 검증 비용을 없애는 단위다. 첫 외부 손상 발견·settle 전·계속 변하는 stamp에서 한 번의 전체 검증이 root mutex를 오래 잡는 기존 경로까지 모두 밖으로 옮겼다고 주장하지 않는다. 원문 0.5~0.6초와 새 hot 측정을 반드시 나란히 기록한다. 이 잔여는 C00의 명시 수용 대상이다. GS-P01의 GUI 안전 read model/worker 이동은 별도 단위이며 GS02 제품 코드에서 ui/main.py를 바꾸지 않는다.

구조 측정에서 기존 cold fallback의 전체 검증은 별도 잔여로 분류한다. 이를 “이름 목록 예외”로 숨기거나 기존 GC-P02 관리 동작의 금지 호출을 면제하지 않는다. 이번에 추가하는 hot 조회·선읽기 완료 경로의 구조 oracle와, A안에서 남기는 cold 관측값을 따로 보고한다.

새 failure cache는 capture에서 사용하지 않는다. 다른 세션의 JSON 손상/PermissionError가 있어도 자기 세션의 이름·DB 의도가 없고 .tmp가 없으면 append/seal/등록은 기존처럼 계속된다. 자기 세션의 DB-only/journal-only/tombstone·의도 미확인은 계속 거부한다. 저장 원본 bytes와 계수의 회계는 완화하지 않는다.

## 4. 입력 분할·feasible 분모

계획은 **280행 / ID 누락·중복 0을 구현 시 감사**한다. 현재는 산술과 ID 범위만 설계한 것이며 PASS 수가 아니다. 시간·stamp·경쟁은 fake clock/barrier로 제어하고 실제 디스크 시각 정밀도가 전수를 보장한다고 가정하지 않는다.

| family / ID | 입력 분할 | feasible 행 | 독립 oracle |
| --- | --- | ---: | --- |
| J / GS02-J-001..060 | 관찰 시작 age 5종 {-1ns, T-1ns, T, T+1ns, 10T} × 읽기 소요 {0,T+1} × {fresh,reuse} × 변화 {없음,stamp 변경,내부 version 변경} | 5×2×2×3=60 | 손으로 고정한 경계 표. 시작 age가 T보다 큰 행만 settle 후보이며, 종료 후 경계 통과는 승격 사유가 아니다. 변경 관찰은 게시 불가. |
| N / GS02-N-001..072 | 오류 {invalid JSON,schema 불일치,미인식 이름,.tmp,본문 PermissionError,unsafe 항목} × {settled,unsettled} × 조회 {get_session,chunks} × 호출 수 {1,2,20} | 6×2×2×3=72 | 거부 코드/DB·원본 불변. settled 이후 hot 호출의 본문 읽기 횟수는 첫 유효 실패 검증을 제외하면 0. unsettled 관찰은 cache로 덮지 않음. 호출 수는 첫/두 번째/반복 경계다. |
| I / GS02-I-001..042 | 다음 사건 {같은 관찰,stamp 변경,내부 게시 version 변경,이름만 변경한 같은 tick,같은 stamp 내용 수선 후 fresh 관리 조회,close/reopen,오래된 결과 뒤늦게 게시} × 기존 상태 {정상,settled 실패,unsettled 실패} × {관리 읽기,Job 권위} | 7×3×2=42 | 새 의도 누락 허용 0, 오래된 관찰 역순 게시 0. fresh 관리 수선은 새 검증 성공 이후만 cache 해제. 상태에 맞게 실제 fixture를 구성하며 빈 cache를 실패 상태로 가장하지 않음. |
| L / GS02-L-001..036 | 호출자 {get_session,chunks,job_authority,writer} × stamp {settled,unsettled,변경됨} × 항목 {정상 타 세션 의도,미인식 타 항목,.tmp} | 4×3×3=36 | root 보유 중 모든 FS 호출의 경로·종류와 hot/선읽기/cold 출처를 수집. hot·선읽기 완료 경로의 A안 예외는 정확한 journal 직접 이름 목록뿐. 기존 cold 전체 검증은 별도 잔여 측정이지 이름 예외가 아니다. writer는 타 본문을 읽지 않고 .tmp는 거부. |
| C / GS02-C-001..024 | 타 세션 오류 N의6종 × {1트랙,2트랙} × 관리 실패 관찰이 {다음 append 전,다음 append 후} | 6×2×2=24 | .tmp/이름·권위 확인 불가 조건은 별도 명시 거부. 다른 타 본문 오류는 capture 관리 cache 미참조, writer_error 없음, 저장 bytes=수락 bytes, 거부 이유/유실 회계 정확. 실제 장치 없음. |
| R / GS02-R-001..030 | 경쟁 {G15R-05 같은 tick+긴 선읽기,자기 의도 게시,DB-only 삭제,실패 관찰과 수선 성공,명시 무효화와 오래된 성공} × {A먼저,B먼저} × 최종 소비자 {읽기,Job,writer} | 5×2×3=30 | 선형화 순서의 손으로 쓴 허용/거부 표. G15R-05는 목록 뒤 시각으로 settled가 되면 실패. 내부 삭제 뒤 새 write/Job 입장 0. |
| O / GS02-O-001..016 | 종료 전 메모 상태 {정상,settled 실패,unsettled 실패,capture 이름 cache} × 재열기 {같은 프로세스,새 프로세스} × 미디어 {없음,검증 청크 있음} | 4×2×2=16 | cache 비영속·인스턴스 격리, 손상 그대로면 새 열기 fail closed, 수선 뒤 새 열기는 검증 후 성공, 원본 bytes 불변. 자식 import는 격리 src 고정/확인. |
| 합계 | family는 관찰 목적이 달라 중복 PASS로 합치지 않음 | **280** | 새 보강 행은 별도 GS02-X 접두사로만 추가·감사 |

feasible 제한/해석:

- J의 음수 age는 미래 mtime 대표다. fake clock으로 제어한다. stamp 변경·version 변경은 실제 관찰 뒤 순서로 주입하므로 모든 조합이 구성 가능하다.
- 같은 tick 변화는 “stamp가 같으면 무엇이든 검출한다”는 보장이 아니다. settle 전 이름을 재관찰해야 하는 경계 및 긴 선읽기의 잘못된 settle을 검증한다. 이미 settle된 제자리 내용 변경은 기존 G15 한계이며 I의 fresh 관리 조회가 수선/손상을 다시 읽는다.
- C의 .tmp는 타 세션이라고 증명할 수 없는 미완료 의도다. 따라서 “다른 세션 오류면 무조건 capture 성공”이라는 잘못된 oracle를 쓰지 않는다. unsafe는 journal 디렉터리 자체가 아닌 타 항목이며, 디렉터리 자체를 검증할 수 없는 경우는 fail closed 별도 부정 행으로 보강한다.
- 기존 오류 cache가 없는 정상 상태에서 “같은 관찰”은 검증 성공 재사용 oracle이며, 실패를 새로 만든 것으로 세지 않는다. 세 상태는 각각 실제 준비 단계로 구별한다.
- close/reopen에서 손상이 그대로라 constructor가 거부되면 정상 거부로 판정하고, 해당 fixture를 수선한 뒤 새 인스턴스를 열어 정상 복귀를 확인한다. 열기 실패를 성공 인스턴스로 가장하지 않는다.

## 5. 독립 oracle·상태 모델·장애 지점

### 5.1 oracle

1. settled의 진실 표는 시작 age의 정수 경계로 손으로 작성한다. 제품 settle 함수를 호출해 기대값을 계산하지 않는다. fake 읽기 지연을 늘리는 metamorphic 변환은 시작 근거를 바꾸지 않으므로 false→true를 만들면 안 된다.
2. 주어진 DB 삭제 행과 journal fixture의 세션별 의도 집합을 별도로 만든다. 색인 내부 dict를 기대 집합으로 읽지 않는다. DB-only/journal-only/둘 다/tombstone·없는 세션의 기존 job_authority 의미를 유지한다.
3. 본문 open/read_json·이름 열거·stamp 조회를 별도 spy로 센다. cache hot 20회가 JSON parser를 다시 부르면 실패한다. 다른 세션 본문 오류가 writer를 막는지도 같은 경계에서 관찰한다.
4. 실제 합성 PCM은 블록마다 다른 바이트 패턴을 사용하고 트랙별 순서·frame·수락/저장 bytes를 대조한다. 트랙 합계만 같아 상쇄되는 오류를 허용하지 않는다. 거부 0을 주장할 행과 .tmp 등 명시 거부 행을 구분한다.
5. FS 계수기는 lock 보유 thread·대상 경로·동작·hot/선읽기/cold 출처를 함께 기록한다. 단순히 scandir 함수명 전체를 예외 처리하면 안 된다. hot·선읽기 완료 경로에서 새 이름 목록 예외가 sessions/staging 순회나 journal 본문 읽기를 허용하는 mutant를 실패시킨다. 기존 cold fallback은 §3.5의 잔여로 분리하며 기존 GC-P02의 구조 단언을 변경하지 않는다.

### 5.2 상태 모델

관찰 상태는 VALID_INDEX / FAILED_UNSETTLED / FAILED_SETTLED / INVALIDATED / CLOSED로 나눈다. 정상 관찰→실패→동일 stamp hot 거부→fresh 관리 수선→정상 관찰, 실패→자기 세션 삭제 의도→writer 거부, 실패→close→새 열기를 실제 API 순서로 실행한다. model은 이력 권위와 관찰 수명을 검증하며 제품 cache 내부 필드를 그대로 복제하지 않는다.

### 5.3 checkpoint·중단

barrier 위치는 시작 stamp/time 직후, 이름 목록 직후, 본문 읽기 직후, root 재확인 직전, 관찰 게시 직후다. 각 위치에서 내부 의도 게시·외부 같은 tick 추가·명시 수선·종료를 교차한다. G15R-05의 원 순서인 “목록→같은 stamp 의도 추가→긴 지연→Job 관찰 게시→append”를 독립 fixture로 고정한다.

cache는 영속되지 않으므로 이 단위에서 새 파일 journal/복구 protocol을 만들지 않는다. 프로세스 종료 뒤 삭제 journal·DB·원본이 같고 다음 열기의 검증 결과가 그 정본으로 결정되는지 확인한다. SQLite·원본·tombstone 쓰기 경로는 기존 G05/G15 불변식을 그대로 회귀한다.

## 6. 기존 시험과 관계·성능 수락

- 기존 G15 IDX-FAIL/IDX-UI/IDX-IO, fc-unsettled-listing-not-reused, G07 삭제 권위/Job 입장·종료 ACK, G05 pending/retry·GC-P02 구조 판정, G08 건강 비차단/종료 ACK를 회귀한다. 구현 전 G08 최종 tree에서 실제 node를 다시 고정한다.
- 새 파일 2개는 합계 **60초 목표**다. 초과하면 측정값·원인을 먼저 보고하고 분모를 임의 축소하지 않는다. 280행은 전체 외부 입력 공간의 전수 증명이 아니라 위 feasible 대표 조합이다.
- 성능은 cold 실패 검증, settled hot cache, unsettled 반복, stamp 변화의 네 상태를 분리해 보고한다. 검토자 N=1,000 삭제 이력 조건의 tick 대리 측정을 1·2트랙에 적용하고, cache hot 100회 root 보유·p50/p99·최장을 기록한다. 다른 측정/무거운 시험을 동시에 돌렸는지도 기록한다.
- CI의 필수 판정은 **settled hot 전체 본문 재읽기 0·FS 구조·fail closed·의도 뒤 write 0·트랙별 수락 바이트 보존**이다. 이 PC의 hot root 50ms 이하를 진단 목표로 두되 실제 디스크 scheduling의 단일 시간 초과만으로 구조가 정상인 시험을 불안정하게 만들지 않는다. 지연 주입은 본문 재읽기를 500ms 지연시키고 hot 경로가 그 함수를 호출하지 않았음을 직접 단언한다.
- root 보유가 길어질 수 있는 첫 cold 실패·settle 전 반복과 이름 열거 비용은 측정값으로 공개한다. 승인 A안에서 이 잔여를 해결했다고 주장하지 않는다. 같은 시각이거나 미래인 디렉터리 mtime은 캐시 효율보다 fail closed를 우선한다.
- 실제 UI의 선택/공통 실패 안내와 worker read model은 GS-P01이다. GS02의 tick 대리 측정만으로 실제 Qt/Narrator 안내까지 검증됐다고 쓰지 않는다.

## 7. mutation 계획 18개

| ID | 결함 주입 | 검출 표적 |
| --- | --- | --- |
| M01 | job_authority가 읽기 뒤 시각으로 settle | J 긴 지연, R 원 반례 |
| M02 | reuse 관찰만 목록 전 시각 검사를 생략 | J reuse |
| M03 | 정확히 T도 settled로 변경 | J age=T |
| M04 | 게시 직전 stamp 대조 제거 | J/I/R stamp 경쟁 |
| M05 | 게시 직전 history version 대조 제거 | I/R 내부 삭제 게시 |
| M06 | unsettled 실패를 hot cache로 재사용 | N unsettled, I 같은 tick |
| M07 | 실패 cache의 stamp 불일치 무시 | I 변경 뒤 재검증 |
| M08 | 실패 cache를 빈 정상 이력으로 반환 | N 코드/권위 oracle |
| M09 | 관리 실패 cache를 writer에도 적용 | C 타 본문 오류·트랙 보존 |
| M10 | writer가 자기 DB-only 삭제를 무시 | R 자기 의도 뒤 append 거부 |
| M11 | fresh 관리 조회가 실패 cache로 본문 검증 생략 | I 수선/제자리 손상 재조회 |
| M12 | 성공 fresh 관찰 뒤 실패 cache 미해제 | I 수선 후 정상 복귀 |
| M13 | cache를 다른 root/Library 또는 reopen에 승계 | O 인스턴스·재열기 격리 |
| M14 | GS02 구조 예외를 모든 scandir/경로에 적용 | L 다른 경로/본문 spy 음성 대조 |
| M15 | hot 실패 조회마다 전체 _read_journal 재실행 | N20·지연 spy·hot 계수 |
| M16 | 실패 cache만 종료 뒤 시각으로 settle | N/J 실패 관찰 경계 |
| M17 | 오래된 성공/실패가 더 새 관찰을 덮어씀 | I/R 관찰 역순 race |
| M18 | error 객체/repr를 cache·안전 오류에 보존/반영 | N canary 코드·메타데이터 oracle |

임시 사본에는 pyproject·src·tests를 함께 복사하고 PYTHONPATH를 사본 src로 고정한다. 자식 import 경로도 확인한다. 단순 예외나 fixture 오류를 KILLED로 세지 않고 각 mutant의 의미 단언 실패 node·변이 hash·출력을 남긴다. 현재 mutation 실행은 0이다.

## 8. 정확한 제안 쓰기 범위와 확인 명령

권고 A의 **4파일**을 제안한다.

1. src/recoryn/storage/library.py: 내부 관찰 metadata·실패 cache·fresh 수선 연결·job_authority settle 정정. DB schema·외부 Job API·새 thread는 변경하지 않는다.
2. tests/unit/test_index_failure.py(신규): J/N/I/L과 순수 관찰/spy oracle.
3. tests/integration/test_index_failure.py(신규): C/R/O, 실제 Library·Job·합성 writer·tick 대리, 격리 자식·재열기·원본 보존.
4. docs/testing/gs02-index-failure-cases.md: 실제 분모·node·시간·변이·측정·미해결 기록.

기존 시험 파일을 바꿔야 할 실제 실패가 나오면 먼저 보고한다. 특히 GC-P02 기존 동작의 구조 판정을 바꾸는 것은 위 범위에 없다. 대안 B로 public read/쓰기 preflight의 범위가 커지면 별도 파일·API 승인을 받은 뒤 착수한다. storage/chunks.py·_coordination.py는 후속 G-P17a 소유이고, ui/main.py는 GS-P01/G16 소유다.

G08 최종 commit+위4파일만인 OS TEMP archive 사본에서 신규·관련·tests/ui 전체, 18변이, ruff check/format, mypy src/recoryn scripts packaging, ResourceWarning 오류화 및 CI 동등 전체 coverage/check_coverage를 확인한다. 시험은 offscreen·no cacheprovider·고유 TEMP basetemp를 사용한다. coverage threshold·공용 설정은 바꾸지 않는다. Git 쓰기·네트워크·장치·vault 쓰기·설치·하위 에이전트는 수행하지 않는다.

## 9. 대안과 C00 결정 요청

| 대안 | 장점 | 한계/판정 |
| --- | --- | --- |
| A: settled 실패 cache + journal 이름만 좁은 예외 | Library 내부의 작은 변경, capture I1/잠금 의미 유지, hot 반복 전체 검증 제거 | cold/settle 전 장기 보유는 남음. 권고안이며 이 잔여의 명시 수용이 필요 |
| B: 관리 이름/본문 관찰의 완전한 root 밖 preflight | 구조 규칙이 단순하고 cold 경합도 줄일 여지 | 중첩 _live/transaction 호출자의 재검증 설계·범위 확대 필요. 무조건 lock을 풀면 I1/원자성 약화 |
| 모든 실패를 TTL cache | 구현이 짧음 | settle 전 같은 tick 변화·명시 수선 의미가 흐려져 채택하지 않음 |
| 모든 journal 오류를 capture에도 적용 | 전역 상태가 단순해 보임 | 타 세션 손상으로 녹음 중단, G05R-04/G15 회귀이므로 금지 |
| 실패를 빈 목록으로 처리 | 화면이 계속 동작함 | 삭제 의도 부재로 오판해 부활·전송/게시 허용 가능, 금지 |

C00 결정 요청:

1. **A안의 정확한 좁은 이름 목록 예외와 cold/settle 전 비용 잔여를 수용할지**, 또는 B안으로 범위를 확대할지 결정한다. 권고는 A이며, 화면의 전체 비차단은 GS-P01 read model 단위와 구분한다.
2. **settled 동일 실패 cache·fresh 관리 재조회 우회/수선·같은 tick/미래 mtime fail closed·capture 미적용**을 승인할지 결정한다. 제자리 수선은 새로고침 성공 관찰 또는 reopen 뒤 반영한다.
3. **관찰 시작 시각과 stamp/version/관찰 세대 검증**, job_authority의 fresh/reuse 동일 규칙, 기존 Job transaction 보호·닫힌 오류 코드 유지에 동의하는지 결정한다.
4. **4파일·계획280행·mutation18·신규2파일60초 게이트·G08 push 뒤 착수**를 승인할지 결정한다. 제품 API/공용 계약의 추가 변경이 필요하면 구현 전에 별도로 요청한다.

이 문서는 실행 결과나 구현 완료 보고가 아니다. 독립 검토·최종 등급·정확한 tree 검증과 commit/push는 C00이 담당한다.

## 10. 계약 문서 자체 점검

J60+N72+I42+L36+C24+R30+O16=280행, family ID 범위 중복·누락0, mutation M01~M18의 누락·중복0, 제안 쓰기 범위4파일을 문서 산식으로 확인했다. UTF-8·끝 개행을 확인했다. 이 점검은 제품 시험이나 변이 실행이 아니며, 새 PASS 실적은0이다.


## 11. 구현 착수·C00 보충 반영

C00이 A안과 §9의1~4를 승인했고 G-P08 push 31bc88b26304eea569d0735857fe0ca0e90b8778 뒤 GS-P02를 배정했다. 기준 library.py bytes가 해당 commit과 같고 신규 시험2파일이 없음을 확인했다. 쓰기는 승인4파일뿐이다. 기존 관리 API는 그대로이며 작은 내부 관찰 DTO와 인스턴스별 실패 memo를 사용한다.

현재 줄283~375의 job_authority가 전이마다 _journal_prefetch로 전체 본문을 다시 읽는 것을 직접 확인했다. C00 보충에 따라 같은 범위에서 **정상 색인 재사용**도 포함한다. _journal_prefetch 호출 자체는 유지해 기존 race fixture와 off-root preflight 지점을 보존하며, Job 기본 관찰은 검증된 현재 색인/settled 실패를 재사용하고 명시 관리 조회는 fresh 관찰을 요구한다. 원 parser와 DB/Job transaction 잠금 순서를 복제하지 않는다. 관찰 시작 시각·stamp·history version·관찰 세대를 검증하고, names 구성 같은 O(N) 준비는 root 밖에서 한다.

G08판 constructor는 손상 journal에서 인스턴스 열기를 허용하되 관리 읽기를 거부한다(:272~276). §3의 '기존처럼 실패'는 안전한 관리 거부를 포함하는 것으로 정정한다. 이를 새로 constructor 예외로 바꾸지 않는다. 정상·실패 cache 모두 영속하지 않는다.

기존280행/J60 N72 I42 L36 C24 R30 O16은 유지한다. C00 보충 측정은 별도 GS02-X-PERF-{0,100,1000}으로 감사하고 정상본/기준본의 실제 Job 전이·본문 읽기 횟수·시간을 비교한다. 새 trial은 fake clock·실제 TEMP Library/합성 PCM만 쓰며 네트워크·실장치·모델을 사용하지 않는다. 신규2파일60초를 초과하면 분모 축약 전에 보고한다. 변이18개는 원 계획 의도대로 실제 단언 실패를 확인한다.


## 12. 구현 중 재대조와 보충 요청의 경계

정상 Job 관찰까지 현재 색인을 재사용한 첫 구현에서 기존 G-P07 시험2건이 실제로 실패했다: tests/integration/test_blocked_reason_flow.py의 test_in_place_corrupt_history_is_not_hidden_by_an_unchanged_directory_index(같은 directory stamp 본문 손상을 Job마다 검출)와 test_authority_enumeration_is_outside_root_job_transaction_and_job_lock(root 안 이름 열거도 금지). 새로운 전체 본문 O(1) 재사용은 이 신선도 요구를 만족하지 못한다. 기존 단언은 변경하지 않았다. C00 보충의 정상 Job O(N) 제거는 정책 재결정이 필요하다고 이 창에 보고하고 별도 계약 분리를 요청했다. C00 결정 전에는 **성공 Job 관찰의 전체 본문 검증을 유지**한다. §11의 정상 색인 재사용 시도와 GS02-X-PERF3행 계획은 이 경계 때문에 구현 결과로 집계하지 않는다. 삭제0/100/1000 성능은 TEMP 독립 측정으로 보고한다.

승인 A의 settled 실패 memo만 Job에서도 재사용하고, 관리 list/pending 등의 fresh 관찰은 실패 memo를 우회한다. Job 선읽기의 모든 열거는 기존처럼 root 밖이며, _live/capture의 정확한 journal 이름 목록만 A의 좁은 예외다. fresh 관찰의 이름 재확인도 선읽기 중 root 밖에서 한다. 본문 오류는 닫힌 metadata만 남기고 성공 색인을 무효화한다.

관찰 시작 ticket과 **최신 게시 ticket**을 구분한다. 새 관찰이 시작됐다는 이유만으로 아직 유효한 실패 memo를 폐기하지 않으며, 더 새 관찰이 이미 게시된 뒤에는 이전 결과를 게시하지 않는다. 이 방식은 같은 stamp/version에서 역순 게시를 막는 승인된 내부 세대 방식이며, 두 선읽기가 서로 재시작시켜 불필요하게 HISTORY_UNAVAILABLE을 반복하는 것을 피한다. 실제 예약 ticket보다 미래인 token도 거부한다. 명시 색인 게시·내부 의도 게시·close는 ticket을 갱신/무효화한다. 새 DB version·thread·lock은 없다.

신규 시험은 계획280행을 유지한다. 별도 보강은 GS02-X-AGE-1..5(실패 관찰도 완료 시각으로 settle하지 않음)와 GS02-X-CONTEXT-1..3(종료된 owner의 권위 context가 호출자 transaction 예외를 잡거나 두 번 yield하지 않음)이다. 첫 fixture 준비 오류(collection2건)는 수정했고, 1ns 실제 mtime 변경은 NTFS에서 같은 stamp였으므로 변경 사건만1,000ns로 바꾸고 os.stat 실제값을 assert했다. 시작 age -1/T±1 경계는 fake clock 정수로 계속 독립 검증한다. L의 변경된 정상 이력도 cold 전체 재검증 잔여로 분류하며, 그 경우조차 read/metadata 대상은 정확한 journal 직접 항목으로 제한한다. 다른 root/sessions 순회를 cold 예외로 숨기지 않는다.

중간 실행은 related2.xml 기준 신규280+기존406=686PASS/16.75초다. 이후 게시 ticket·context 예외 보강을 포함한 최종 정상본으로 시간·mutation·전체 회귀를 다시 측정한다. 중간값을 최종 검증으로 옮기지 않는다.


## 13. 최종 검증 전 고정 범위

보강 ID는 X-AGE5 + X-CONTEXT3 + X-AUTH3(닫힘·이력 미확인·미래 ticket 게시 거부) + X-FRESH3(완료된 fresh 선읽기보다 더 새 관찰이 게시된 경우)로14행이다. **계획280+보강14=294**를 별도로 감사한다. 선읽기가 이미 본문 전체를 읽었고 같은 stamp/version의 더 새 관찰이 게시됐다면 그 최신 검증 결과를 사용하거나 최신 실패로 거부하며, 단순 ticket 경쟁만으로 root 안 O(N) 본문 재읽기를 새로 만들지 않는다. stamp/version 변경의 기존 cold fallback 잔여는 그대로 구분한다.

중간 정상288행은9.12초, 변이 M01~M18은 전부 의미 단언으로 검출됐다(오류/collection 실패0). 이후 X-AUTH/FRESH 보강과 해당 경로를 포함한 **최종294행·18변이**를 새 사본에서 다시 실행한다. 변이 M13은 종료된 인스턴스의 실패 memo를 남기는 수명 결함으로 구체화했고, O는 실제 같은/새 프로세스 재열기·원본 보존을 따로 확인한다. 정상294행 검증과 원본280 ID 감사, 시간 게이트, coverage 및 전체 회귀가 끝난 값만 최종 결과 절에 기록한다.


## 14. 최종 구현·실행 결과

기준은 **31bc88b26304eea569d0735857fe0ca0e90b8778 + 승인4파일**이다. 부모·자식 import가 final/tree/src인 것을 child-origin.log로 확인했다. 제품1/시험2파일의 LF hash는 검증 시작 이후 변하지 않았고 문서는 결과 절만 추가한다. 다른 작업자의 G-P12 파일은 사본에 넣지 않았다.

### 14.1 변경 동작과 실제 oracle

- _JournalObservation은 시작시각/stamp/history version/예약 ticket·최신 게시 ticket을 연결한다. 관찰 시작 이후 걸린 시간으로 settle하지 않는다. 정확히2.5초/미래mtime는 unsettled다. 이미 더 새로 게시된 관찰을 오래된 결과가 덮지 못한다.
- settled 실패는 _live의 get_session/chunks와 Job의 실패 권위 경로에서 본문 재읽기 없이 닫힌 코드로 재사용한다. 성공/실패 stamp를 섞지 않고, 실패 캐시는 capture에 적용하지 않는다. fresh 관리 조회 성공으로 같은 stamp의 수선도 반영한다. 이름 열거 예외는 정확한 journal 직접 이름뿐이다.
- 새 public API·DB/schema·백업 구성요소·thread·추가 lock 없음. Job transaction 동안 root를 보호하는 기존 계약은 그대로다. context에서 호출자의 예외를 잡아 두 번 yield하는 일도 방지했다.
- G15R-05 독립 반례(같은 tick의 자기 의도 추가+긴 선읽기): 기준본 VALID/settled=True/실제 append ACCEPTED, 최종본 HISTORY_UNAVAILABLE/settled=False/append 거부였다. control 원본 파일은 보존한다. probe-normal.py와 isolated-probes.json이 명령/결과를 보관한다.

### 14.2 경우의 수·회귀·정적·coverage

계획 **280행(J60+N72+I42+L36+C24+R30+O16)** 누락·중복·추가0, 별도 보강14행, 총 **294PASS**다. 신규2파일은 **9.330초(runner)** 로60초 예산 이내다(case-audit.json·new.xml). 정상본294PASS, 변이 **M01~M18 18/18 검출**, 오류/collection 실패0이다. Source hash·실패 node는 mutation-results.json·M01~18.xml/log에 있다. 계획280을294로 바꿔 중복 집계하지 않았다.

관련 회귀 **2,919PASS**(그중 tests/ui 전체 **1,465PASS**), G15 IDX **49PASS/53deselected**다. 마지막 CI 동등 전체는 **22,744PASS / 실패0 / 오류0 / skip0 / 경고0**, **1622.901초(runner)** 다. ruff check·format·mypy src/recoryn scripts packaging 모두 PASS했다. pytest명령은 no:cacheprovider·ResourceWarning 오류화·고유TEMP basetemp·offscreen·PYTHONPATH 사본src를 사용했다. coverage 대상은 사본 src/recoryn의78파일뿐이고 임시 fixture 파일0이다.

```text
domain: line=99.18%/95% branch=97.89%/90% PASS
capture: line=99.85%/95% branch=98.57%/90% PASS
jobs: line=99.29%/95% branch=96.23%/90% PASS
storage: line=96.05%/95% branch=91.43%/90% PASS
security: line=98.11%/95% branch=94.43%/90% PASS
content: line=99.59%/95% branch=98.75%/90% PASS
all: line=93.72%/85% branch=88.24%/80% PASS
```

### 14.3 C00 보충: 정상 Job 경로는 계약 분리가 필요

**정상 claim의 O(N)은 미해결로 남긴다.** G-P07의 test_in_place_corrupt_history_is_not_hidden_by_an_unchanged_directory_index는 directory stamp가 그대로여도 본문 손상을 매 입장에 검출하도록 요구한다. 정상 색인을 단순 재사용하면 이 실제 시험이 실패한다. Root 안 이름 목록까지 사용한 시도는 test_authority_enumeration_is_outside_root_job_transaction_and_job_lock도 실패했다. 기존 시험/JobStore 파일은 승인 범위 밖이며, 이 요구를 약화하는 정책 변경을 하지 않았다. C00에 별도 계약 분리를 요청했고 승인 없는 성공 cache는 적용하지 않았다.

직접 측정한 JobStore.complete(:610)는 _transaction()만 사용하므로 해당 선읽기를 거치지 않는다. 코드 재대조상 _session_transaction(:202, acknowledgement 인자)을 거치는 것은 claim(:319)·reader_started(:390)·block_pending(:476)·resume(:523)·fail(:782, acknowledgement=True)다. 따라서 이 측정만으로 모든 종료 경로나 모든 전이를 일반화하지 않는다. **claim의 N 의존 비용**과 complete의 다른 경로를 각각 확인한 것이다. 아래는 각각3claim+3complete, 본문 호출3회였다. 단독 재측정은 이 작업의 다른 무거운 검증을 종료한 뒤 순차 실행했으며, 다른 세션/OS 부하는 통제하지 않았다. 소수 표본의 기술 측정이며 개선/회귀의 인과 보장이 아니다.

| 삭제 이력 수 | 기준 claim 중앙값(ms) | 최종 claim 중앙값(ms) | 기준 complete 중앙값(ms) | 최종 complete 중앙값(ms) |
| --- | ---: | ---: | ---: | ---: |
| 0 | 1.592 | 1.943 | 0.816 | 0.609 |
| 100 | 48.328 | 45.256 | 0.825 | 0.669 |
| 1000 | 605.839 | 598.982 | 0.619 | 0.672 |

정상 입장의 개선에는 파일 본문 검증의 신선도/변경 감지/불변성 증명 또는 별도 권위 형식에 대한 계약 결정이 필요하다. 현재의 같은-stamp 손상 검출을 유지하면서 본문을 안 읽는 O(1) 성공 cache라고 주장하지 않는다. 단순 entry metadata 재사용도 보존할 검출 범위를 먼저 정해야 한다. 이것이 C00 보충의 범위 밖 보고이며 본 GS02 원 승인 범위의 실패 cache 결과와 구분한다.

### 14.4 cold 잔여·settled hot·녹음 측정

단독 재측정은 N=1,000 완료 tombstone+journal, 기본 queue256, 1·2트랙 합성 PCM이다. 첫 cold 검증에는 본문 함수500ms 지연을 주입했고 **PCM 제출 전**에 수행했다. 따라서 cold 중 녹음 유실0을 보장한 측정이 아니다. 이후 hot100회 동안 producer를 돌려 본문 재읽기0과 트랙별 수락/저장 bytes 및 거부 회계를 확인했다.

| 트랙 | cold(500ms 주입 포함,s) | hot p50(ms) | p99(ms) | 최장(ms) | hot root 최장(ms) | 본문 재읽기 | 거부 | 저장 frame |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 1.099 | 0.276 | 2.855 | 14.337 | 0.849 | 0 | 0 | 96000 |
| 2 | 1.017 | 0.253 | 1.007 | 8.318 | 1.003 | 0 | 0 | 192000 |

수락 PCM bytes는 각각 실제 청크와 일치했다. .tmp는 별도 C행에서 명시 거부를 확인했고, 나머지 타 본문 오류는 capture를 막지 않았다. Cold/settle 전 검증은 여전히 root를 오래 잡을 수 있다. 정확한 journal 이름 목록도 N에 비례할 수 있다. 이 잔여는 승인 A의 수용 범위이며 전체 GUI 비차단은 GS-P01, writer fsync 지연은 G-P17이다. 이전 동시 부하 측정(큰 queue4096, 제출과 cold 중첩)은 상위 폴더 fixed-probe-results.json이며 위 단독/기본 큐 측정과 혼합하지 않는다.

### 14.5 최종 파일·인계

| 파일(본 문서 제외) | SHA-256(LF) |
| --- | --- |
| src/recoryn/storage/library.py | 572094e82c5a25bd175a3f6973ac7a40582953a5164a8ae07ae0542e345b2966 |
| tests/unit/test_index_failure.py | 1f452fd37261dbaf949dec1fdc72d3b5269715b4e81e940689d3f2b11137796b |
| tests/integration/test_index_failure.py | 1b831a5e0ee672bb12d8496ac82147c2935a622ea8ff134285ff0160d7193590 |

본 문서 SHA는 IMPLEMENTATION_READY와 gs02-ready-manifest.json에 기록한다. 최종 근거 폴더: C:/Users/gangd/AppData/Local/Temp/recoryn-gs02-l9td9r1u/final

핵심은 validation-results.json·new/related/idx/full.xml·coverage-full.json·coverage.log·case-audit.json·mutation-results.json·child-origin.log·isolated-probes.json이다. 초기 원인/중간 실행과 probe-normal.py·hot-default.py 원본은 상위 recoryn-gs02-l9td9r1u에 보존했다. 최종4파일 manifest/범위 감사도 같은 final 폴더에 둔다. 실제 장치·모델·네트워크·계정·vault·설치·Git 쓰기·하위 에이전트는 사용하지 않았다. 독립 검토와 최종 통합은 C00이 담당한다. G-P17a/G-P09a에는 새 영속 구성요소가 없고, 이 메모는 재열기/복원 후 새로 검증해야 함을 인계한다.

## 15. FIX1 계약 정정·재검증 계획

2026-11-25 C00의 GS02R-01(S1 상향)·02(S2)·03(S3) 수정 결정을 적용한다. 앞 절은 1차 이력이다. ‘권한 실패도 보수적으로 유지’는 **해당 호출에서 fail closed하되 영구 memo로 두지 않음**으로 정정한다. OSError/PermissionError는 다음 호출에서 재검증한다. 내용 손상(ValueError·schema·형식 위반)만 memo로 남기며, 예외 객체/본문은 보관하지 않는다.

settle 전 내용 실패도 관찰 시작 version·stamp·게시 세대·시각이 맞고 **전후 이름 목록이 같았으며 현재 이름 목록도 같을 때** 재사용한다. 미래 mtime·시계 역행은 재사용하지 않는다. 같은 tick의 이름 추가/제거는 재검증하고, 제자리 내용 수선은 기존과 같이 fresh 관리 조회로 반영한다. capture는 이 실패 memo를 사용하지 않는다. 첫 cold 본문 검증이 root 안에 남는 것은 반복 검증 제거와 구분해 측정한다.

job_authority도 관리 경로와 같은 ‘더 새 완료 관찰 재사용’ 함수를 사용한다. version·stamp·관찰 세대·Library 생존이 같은 snapshot인 경우에만 최신 성공/실패를 사용하고, 실제 의도/세대/root 변경은 재시도/보류한다. 일시 I/O 실패를 최신 결과로 받은 그 호출은 거부하되 다음 호출을 막지 않는다.

settle 전 Job의 실패 관찰 재사용은 이름 목록도 root 밖에서 만든 뒤 root 안에서 후보 identity·version·stamp를 재확인한다. _live/capture에 허용한 좁은 이름 목록 예외를 Job에 확대하지 않는다. 기존 L36의 Job 행은 root 안 이름 열거도 0으로 강화한다.

독립 oracle 추가 계획은 `GS02-F1-IO` 12행(일시 오류2×시각2×get/chunks/Job3), `GS02-F1-LIFE` 4행(열기/갱신×트랙1/2의 생성·정지·원본 보존), `GS02-F1-NAMES` 24행(같음/추가/제거/stamp변경×settle전/경계/미래×read/Job), `GS02-F1-AUTH` 12행(최신 성공/내용실패/I/O실패×동일/stamp변경/version변경/종료), `GS02-F1-PCM` 2행(트랙1/2·1000이력·외부 내용손상 병행)이다. **추가54행, 기존 계획280+54=334행, 기존 별도 보강14를 더한 실행 예정348행**이다. 기존 N72의 기대를 내용/I/O로 나누고, L36은 settle 전 동일 이름 내용 실패의 반복 본문 읽기 금지를 강화한다. 기존 case ID는 유지한다.

변이는 기존18개를 현 계약으로 재대조하고, I/O를 memo로 승격·settle 전 실패 재사용 제거·이름 비교 제거·최신 Job 관찰 재사용 제거·최신 실패를 성공으로 대체·Job 이름 비교를 root 안으로 되돌림의 여섯 종류를 추가한다(총24). 기존 M06의 ‘settle 전 무조건 재사용’은 승인된 새 동작과 구분해 **이름 증명 없이 재사용**하는 결함으로 정정한다. 변이별 collection/권한/timeout은 검출로 세지 않는다. 지정4파일만 담은 HEAD 31bc88b TEMP archive/PYTHONPATH 고정 사본에서 반례·관련·UI·CI 동등 전체와 coverage·정적 검사 후 실측을 아래에 기록한다. 여기까지는 실행 결과가 아니다.

## 16. FIX1 작성자 검증 결과

### 16.1 입력·수정·독립 재확인 경계

검토 입력은 `4a6b2953`이며 검토 문서 LF SHA256은 `fb00d48024fd0bbfa2cfcecc2340ec8e56f4bc4592b9793d3222d294b38ab8c3`으로 직접 대조했다. 재검증 사본은 **31bc88b archive + 지정4파일**이다. 공유 작업 트리의 G-P12 등 변경은 넣지 않았다. 부모·자식 import가 사본 src 아래임을 sentinel과 재열기 시험으로 확인했다. `new1`의 NTFS ns fixture/건강 요약 접근 오류 및 중간 소스의 결과는 최종 PASS에 넣지 않는다. Job 이름 비교를 root 밖으로 보강하기 전 전체 실행은 중단했으며, 최종 소스로 별도 `*-final` 전체 검증을 수행한다.

| 지적·C00 등급 | 실제 수정 근거 | 작성자 oracle |
| --- | --- | --- |
| GS02R-01 / S1 | `library.py:137`, `:433`, `:487`, `:518`: content_failure bool과 실제 전후 이름 metadata를 분리. OSError는 memo 미발급, 내용 실패만 발급. 예외 객체·본문 미보관 | F1-IO12의 오류 1회→다음 호출 회복. F1-LIFE4는 열기 오류 뒤 녹음 생성, stop 자체가 만난 1회 공유 거부 뒤 accepting 유지·다음 stop 성공·원본 bytes 보존. |
| GS02R-02 / S2 | `library.py:433`, `:487`: settle 전 내용 실패는 같은 stamp/version/게시 세대와 이름 목록으로 재사용. 미래 mtime는 제외. Job 선읽기의 이름 비교는 root 밖, 재확인만 root 안. capture에 memo 적용 안 함 | N72·L36 기대를 승인 계약으로 개정, F1-NAMES24·PCM2. 변경 없는 손상 본문은 첫 cold 1회, 후속 tick은 내용 재읽기 0. L의 Job 행은 root 안 열거 0. |
| GS02R-03 / S3 | `library.py:299`, `:507`, `:673`: Job과 관리 조회가 같은 최신 완료 관찰 재사용 함수를 사용. 최신 성공/실패에 맞춰 현재 색인으로 답변. version/stamp/수명 변경은 공유하지 않음 | F1-AUTH12의 최신 성공/내용 실패/일시 I/O 실패와 실제 stamp/version/종료. 독립 경쟁 probe 3개 reader+20회 Job 권위에서 VALID20, 거짓 거부0. |

이 표는 작성자의 수정·시험 확인이다. 지적의 RECHECKED/CLOSED 판정은 C00 지정 독립 검토자가 한다.

### 16.2 경우의 수·mutation·개별 검증

기존 J60+N72+I42+L36+C24+R30+O16=280, FIX1 추가 IO12+LIFE4+NAMES24+AUTH12+PCM2=54로 계획 **334행**이다. 기존 보강 X14를 분리한 실제 신규2파일은 **348 PASS**, 계획 ID 누락·중복0/보강 외 추가0이다. 최종 소스의 단독 `new4.xml` 실행은 pytest **26.29초**, 60초 예산 이내다.

정상 control348 PASS, **M01~24 모두 assertion 검출(24/24)**, error/collection 실패0이다. M19=I/O memo 승격, M20=settle 전 재사용 제거, M21=이름 대조 제거, M22=Job 최신 관찰 공유 제거, M23=최신 실패를 VALID로 치환, M24=Job 이름 비교를 root 안으로 이동이다. 기존 M06은 새 계약의 이름 증명 생략으로 대조했다. source hash·실패 node·명령은 mutation-results.json/M01~24.xml/log에 남겼다.

검토자 G1·G2·G4·G5·G6·G8과 같은 결함 의도는 각각 M01·M09·M11·M07·M05·M15로 재검출했다. G3의 ‘settle 전 재사용 자체 금지’는 C00가 변경한 계약이며, 새 이름 증명 결함은 M06/M21로 검사한다. 검토자가 동등으로 분류한 G7을 새 검출 개수에 넣지 않았다. 검토자 8변이를 원문 그대로 전부 재실행했다고 주장하지 않는다.

최종 소스의 관련 회귀는 **2,919 PASS(tests/ui 전체 포함, 158.01초)**, G-P15 IDX는 **49 PASS/53 deselected(125.32초)**다. ruff check·format193파일·mypy91 source files 모두 PASS다. 전체 최종 coverage 결과는 다음 절에 확정 기록한다.

### 16.3 검토자 반례·녹음 측정

`build/review-trees/gs02a-probe/`의 일시 오류(open/refresh), cache 규칙, G15R-05, 3-reader 경쟁, 1/2트랙 외부 손상 등 7개 실행이 최종 소스에서 exit0이었다. `-I` 실행 뒤 사본 src를 넣었으며 실제 원본 스크립트는 변경하지 않았다.

- open: 한 번의 읽기 공유 거부 뒤 create_session·녹음 생성·get/chunks·stop이 fresh 수동 조회 없이 성공했다.
- refresh: 첫 get만 DELETION_HISTORY_UNAVAILABLE, 이후4 get·5 chunks·stop 성공. 단독 LIFE4는 stop을 첫 오류 지점으로도 고정했다.
- G15R-05: 같은 tick 외부 의도+긴 선읽기 뒤 append 거부와 settle=False 유지.
- 경쟁: 완료 이력1000·fresh reader3개·Job 권위20회에서 **VALID20/HISTORY_UNAVAILABLE0**, **32.96초**, reader 오류0. 이 수치를 정상 O(N) 해결로 해석하지 않는다.

외부 내용 손상 측정은 검토자와 같은 N1000·실시간12초·250ms tick 대리·기본 queue256·3초 뒤 미인식 이름 추가다. 다른 무거운 작성자 검증은 동시에 돌리지 않았으며 타 세션/OS 부하는 통제하지 않았다.

| 트랙 | 거부 블록 | 저장 frame | 보존 | tick root p50(ms) | 첫 cold root(ms) / 50ms 이상 횟수 | writer 오류 |
| --- | ---: | ---: | --- | ---: | --- | --- |
| 1 | 0 | 576,000 | 수락=저장 | 2.01 | 468.53 / 1 | 없음 |
| 2 | 0 | 1,152,000 | 수락=저장 | 2.00 | 423.01 / 1 | 없음 |

반복 cold 4~5회는 1회로 줄었다. **첫 cold O(H) 검증은 여전히 root 안에 남는다.** _live의 기존 중첩 root 호출자를 잠깐 풀어 상태 원자성을 깨는 방식은 사용하지 않았다. 이름 확인도 H에 비례할 수 있어 무조건 비차단/무손실을 보장하지 않는다. 이 잔여의 worker/read-model/성공 검증 정책은 GS-P01·GS-P11 계약으로 인계한다.

이 스크립트는 지속적인 내용 손상을 수선하지 않고 stop을 부르므로 stop은 기존과 같이 DELETION_HISTORY_UNAVAILABLE다. 이는 일시 I/O 1회로 memo가 고착된 결함과 다르다. worker 저장 실패는 없고 모든 수락 프레임은 보존됐다. 정식 PCM2는 명시 수선/fresh 검증 뒤 stop 성공과 bytes·거부 회계를 확인한다.

### 16.4 전체 최종 결과·파일

상태: **FIX1_READY — 작성자 검증 완료, 독립 재확인 대기.** 최종 소스의 CI 동등 전체는 **22,798 PASS / 실패0 / 오류0 / skip0 / 경고0**, pytest **1,374.29초**다. 명령은 `python -m pytest -q -p no:cacheprovider -W error::ResourceWarning --cov=recoryn --cov-branch --cov-report=json:<TEMP>/coverage.json --cov-report=term-missing --cov-fail-under=85 --basetemp <TEMP>/full-final-temp --junitxml <TEMP>/full-final.xml`이며, 뒤이어 `python scripts/check_coverage.py <TEMP>/coverage.json`이 exit0이었다. PYTHONPATH는 사본 src, QT_QPA_PLATFORM은 offscreen, bytecode 쓰기는 껐다. pytest combined coverage는 **92.32%**이며 아래 line/branch 집계와 구분한다.

```text
domain: line=99.18%/95% branch=97.89%/90% PASS
capture: line=99.85%/95% branch=98.57%/90% PASS
jobs: line=99.29%/95% branch=96.23%/90% PASS
storage: line=95.95%/95% branch=91.41%/90% PASS
security: line=98.11%/95% branch=94.43%/90% PASS
content: line=99.59%/95% branch=98.75%/90% PASS
all: line=93.71%/85% branch=88.24%/80% PASS
```

| 파일(본 문서 제외) | SHA-256(LF) |
| --- | --- |
| src/recoryn/storage/library.py | 7e9a1c126409bfdd2a39de04aa93a64f8e3c972943d1f830567069ca29958f79 |
| tests/unit/test_index_failure.py | d01155a3bd55e45ae3d8025cd5c020339663e33bb55ab383b808ef35f627c637 |
| tests/integration/test_index_failure.py | 28ce40270ba97a9c6d0433af08bd594c60c483d73186bbb4db66b1fa0ba08485 |

최종 입력 감사에서 기준 archive 대비 변경은 지정4파일뿐이며 범위 밖0이었다. coverage 대상78파일은 모두 사본 src/recoryn 아래이고 임시 fixture 혼입0이다. 결과 문서 확정 전후 제품·시험3파일 hash가 실행 사본과 같음을 대조했다.

이번에 추가한 영속 표/파일·공개 API·thread·lock은 0이다(내부 관찰 DTO/함수는 변경). 최초 cold 전체 검증과 정상 성공 입장의 O(N) 문제는 이 수정으로 닫았다고 하지 않는다. 실제 장치·모델·네트워크·계정·vault·설치·Git 쓰기·하위 에이전트 사용0이다. 독립 재확인과 최종 통합은 C00이 수행한다.

근거 폴더: `C:/Users/gangd/AppData/Local/Temp/recoryn-gs02-fix1-ccxcsq3d`. 최종 증거는 new4.xml, mutation-results.json, review-probes.json, related-final.xml, idx-final.xml, full-final.xml, coverage.json, coverage-final.log, validation-results.json, bundle-results.json이다. 중단/중간 실행은 최종 PASS로 집계하지 않는다.
