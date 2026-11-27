# G09 잔여 a 코어 규범·전사 독립 검토

**G09-NORM-PUBLICATION-R1 / 전사·wrapper OPEN0.** 지정 문서3파일 단위의 내용은 정적 검토상 수락 가능하다. 실제 BASE 채택·공개는 **S1 최종 commit 공개 및 그 동일 SHA의 원격 CI3개 성공 뒤** X00가 별도 수행한다. 현재 build 후보를 공용 case에 반영하거나 push한 결과가 아니다.

검토자는 w5:p8이다. 과거 원 G09 계약 작성 이력이 있으므로 자신의 과거 설계 전체를 최종 승인하지 않았다. 원 norm/delta/hand/data 검토·FIX1 재확인 증거를 재사용하고, 이번에는 X00의 wrapper와 append·prefix/suffix·Markdown/link만 독립 대조했다. 제품 import·DB·OS 실험·시험/변이·네트워크·Git 실행/쓰기는0이다. 허용된 이 versioned 리뷰와 build의 입력 감사2파일만 작성했다.

## 1. 규범과 구현 상태의 분리

후보의 채택 wrapper는 `build/g09a-norm-publication/adoption-header.md`(1447B, raw/LF SHA-256 `8a17b9d0594fc37f739f580b04c76c740dfde3d50ade44f358deee78d4ed7ba6`)다. 후보 case:724~731에 정확히 들어갔다.

- wrapper:3/후보:726은 기존 독립 검토·두 지적 재확인을 인수한 **후속 구현의 유효 계약**을 정한다. 보존한 옛 조립 본문의 “후보·정본 인수/독립 확인 대기”는 당시 이력으로 구분하며 실제 구현·시험·공개 상태와 혼합하지 않는다.
- wrapper:5/후보:728은4105를 실제 실행 PASS로 세지 않고 기존 재사용·미승인 후보7을 구별한다. a28/b15 계획을 개별 작업자의 쓰기 권한으로 부여하지 않는다.
- wrapper:7/후보:730은 공용 본문과 versioned 손 fixture를 규범 자료로 삼고 ignored build의 과거 제안은 계보로 한정한다. migration/admission·OS 소유·ACK/CR·운영 배선·실장비·4105행 실행 완료를 인증하지 않는다.

승인 규범을 채택하는 문구로 과거 pending 상태를 현재 구현 완료로 바꾸는 회귀는 발견하지 못했다. 새로운 helper/등록/승인/보존 규칙이나 제품 지원·scope를 이 wrapper에서 추가하지 않았다. 아래 suffix가 승인본과 raw bytes가 같으므로 다른 규범의 전사 변경/누락도 없다.

## 2. 정확한 append 감사

후보는 **원 case120519B + LF + wrapper1447B + LF + FIX1 본문219773B =341741B/1458행**과 raw bytes가 정확히 같다. 두 separator는 각각 한 byte `0a`이며 다른 삽입/삭제/정규화가 없다.

| 구성 | byte 구간(0-based, 끝 제외) | SHA-256 |
| --- | --- | --- |
| 원 case 전체 prefix | `[0,120519)` | `515572aa6d3fa95427b16c71d37b591fa943ca0d0ba4eef1a42d93ef86dd408c` |
| 첫 LF | `[120519,120520)` | 한 byte0a |
| 채택 wrapper | `[120520,121967)` | `8a17b9d0594fc37f739f580b04c76c740dfde3d50ade44f358deee78d4ed7ba6` |
| 둘째 LF | `[121967,121968)` | 한 byte0a |
| FIX1 suffix | `[121968,341741)` | `c7b20f74ae64b12b148a91c9bb373e20dca8e6a71c9060067790a7b9a93df244` |

보존된 원102856B/596행 하위 prefix의 LF SHA는 `2974b644cc6638ebed78d85a76f7e30ca3c99146b39ff5aa659894d2153215cd`, S1 앞111259B prefix는 `7f4e1348023b3cd4fba4994ea4432fc3de2db1326c94ba83d6056bf7fa89bfab`로 같다. 실제 공용 [case](../testing/g09-migration-backup-cases.md)는 여전히120519B/SHA515572aa…408c이며 이 검토자가 append하지 않았다.

고정 후보 `build/g09a-norm-publication/g09-migration-backup-cases.md`의 raw/LF SHA는 모두 `ced46e046118402b6d35742c7cefcbb308b26fd96007041300f4c7791646a005`다. `manifest.json`의 raw SHA는 `7b1380e35c490b1a1c77afd18ea59ef3502e5414b55cf766761f8ec393f68efd`, LF SHA는 `f702641f4eb67af89d0c14ca0676d2ad67a05bc1ca2befae68ee373c0363b9e2`이며 후보/prefix/suffix/wrapper 길이와 hash 참조가 실제 bytes와 일치한다. 이 값은 현재 별도 build 후보의 관측이며 미래 Git archive의 bytes를 검증한 결과가 아니다.

## 3. 원 발견2와 FIX1 종결

| 지적 | 원 발견·최소 수정 | FIX1·이번 전사 판정 |
| --- | --- | --- |
| G09NR-01, S2 | depth16 상한은 있으나 root1/중첩container+1/scalar0 정의가 전사 본문에 없었음 | FIX1:151에 승인된 정의를 추가. 이번 후보:883에 같은 줄이 그대로 있음. root+array15개는16, array16개는17이라는 손 반례가 문서에서 결정됨. **RECHECKED 유지** |
| G09NR-02, S2 | W30 primary 파일 규칙이 원 migration_backup에서 restore_import로 잘못 안내됨 | FIX1:348의 W→migration_backup 정정이 이번 후보:1080에 그대로 있음. 원 W30 ID·tuple·owner b·함수·분모 보존. **RECHECKED 유지** |

원 FIX1의 “726행 중151·348만 변경·다른724행 raw 동일, manifest의 의미/ID/분모/primary/scope 불변” 재확인 결과를 재사용한다. 이번에 그 수정안을 다시 만들거나 원보고를 고치지 않았다. DATA-WIRE-R1의 exact key/type/hash·seq·metadata 제외·관리8MiB와 업무 stream 분리·같은 hash와 actual authority의 구별도 승인 suffix 그대로다.

## 4. 분모·독립 oracle·링크 재사용 범위

원3982+SC12+CA107+새FP4=4105, a1091/b3014, 명시245, delta123, raw4134−제외29라는 **계약 집계**를 유지한다. 기존22 재사용·기존FP01~04는 증분0, 후보7은 미승인/분모0이다. S1 의미20/감사1과 전체 계약4105도 구별한다. 이 수치는 기존 독립 정적 감사의 재사용이며 이번에 전체3982/CA101/hand literal·pytest node를 다시 계산/수집/실행한 것이 아니다. 새 ID·tuple·분모·PASS 증분은0이다.

후보 전체의 Markdown fence16쌍은 닫혀 있고, 원 prefix·wrapper·suffix 경계에서 fence가 섞이지 않는다. 후보에는 Markdown inline link와 reference-link 정의가 없으며 wrapper에 ignored build 링크를 규범 완성을 위한 의존성으로 추가하지 않았다. 버전 관리 대상 fixture는 실제 `tests/fixtures/g09_schema_v1.json`306337B/LF `8b3611904a5db6371d2ebef831f7477a9cd8fa2c6b13ad55f0774417911dedbb`로 유지된다. renderer/접근성이나 미래 구현 파일의 존재를 시험한 결과는 아니다.

이번 리뷰에서 사용하는 build 경로·hash는 **검토 계보/동결 입력 증거**다. 공용 규칙은 채택 후 case 본문과 versioned fixture에 담겨야 하며, build 원보고를 추가로 읽어야 계약이 완성되는 구조로 승인하지 않았다.

| 재사용한 독립 증거 | LF SHA-256 |
| --- | --- |
| `build/g09a-normative-review/report.md` | `88a32a98c37cc1190b6482090d5ebdc9b93b28fc4c4a6f967fa6e9506af813ab` |
| `build/g09a-normative-review/inputs.json` | `4a4501fa420e034e10d55d4ebc06f51fd704a1f86f71e2b678242350b2fba773` |
| `build/g09a-normative-review/fix1-report.md` | `47e76bb771bae0d8cd8fe008905875dce8c723ab3816b9b91986cfe4b992935b` |
| `build/g09a-normative-review/fix1-inputs.json` | `ad7aa50135fc22bc73946eb0a55e42775af0292ffc9002cd2853eeb7558f81f2` |
| `build/g09a-data-wire-review/report.md` | `ea594f1a745b1d7c0c76d42c151f28e8096c2480ea9d6639bfe1c701940e260d` |
| `build/g09a-data-wire-review/inputs.json` | `c9f312dcd2c0911f1c75962b1cd4cebd4445a20a8195c58a697e5baadd6ed1de` |

## 5. 정확 문서 단위·선행 공개 gate

제안 문서 단위는 다음3파일뿐이다.

1. `docs/testing/g09-migration-backup-cases.md` — X00가 최종 gate 뒤 수행할 append.
2. `docs/reviews/g09a-normative-review.md` — 이번 독립 전사 검토.
3. `docs/collaboration/assignments.md` — X00의 배정·인수 기록.

fixture·`.gitattributes`·제품·시험은 이 문서 단위에 포함하지 않는다. 이번에는 위 리뷰와 `build/g09a-norm-publication/review-inputs.json`만 작성했다. 공용 case/배정표·기존 개별 보고는 바꾸지 않았다.

manifest의 `a593e08c2a6aeab529720b7d4c5ef275998b5546`은 **검토 입력 시점의 미공개 S1 후보**이며 실제 BASE로 채택하지 않는다. source 근거5dda553도 분석 앵커다. S1 최종 commit이 실제 공개되고 **그 동일 SHA**의 원격 CI3개가 성공한 뒤 X00가 문서 단위의 실제 BASE를 정해야 한다. 현재 `PENDING_DO_NOT_PUBLISH`를 유지하며 선행 gate를 이 검토의 OPEN0으로 대체하지 않는다. 실제 commit SHA를 본문에 넣기 위해 반복 commit하는 방식도 요구하지 않는다.

원 overlay/S1 local 검증·coverage/wheel 통지는 그 해당 증거의 이력일 뿐 이 문서 후보의 새 실행 PASS가 아니다. S1 상태를 네트워크로 재조회하거나 진행 중 전체 CI에 간섭하지 않았다. 최종 실제 case diff/tree·message/trailer·commit/push·새 원격 결과는 X00의 별도 gate다.

## 6. 판정·미검증

**전사·wrapper OPEN0.** 지정 수정2의 종결이 보존됐고 원 prefix/승인 suffix와 다르게 바뀐 규범은 없다. 내용상 공용 문서3파일 단위 인수가 가능하되 실제 BASE 채택/공개는 §5의 선행 gate 뒤다. 원 G09 설계 전체·자신의 과거 결과·후속 제품 구현을 새로 최종 인증하지 않는다.

제품 import·DB/OS 실험·시험/변이·네트워크·Git 읽기/쓰기·다른 공용 파일 쓰기·새 agent/pane·승인 UI 입력은0이다. 지정 파일 읽기·hash/prefix/문자열/JSON/링크 대조만 수행했다. 실제 codec/inspector·helper/registry/issuer·OS 소유/actual ACK/CR/운영 배선, 전체4105 구현·실행·회귀·성능·실장비·CI/coverage/wheel과 S1 공개/원격 gate는 미검증이다.

고정 입력과 byte 구간·링크 감사·재사용/직접확인 경계는 `build/g09a-norm-publication/review-inputs.json`에 기록했다. LF SHA-256: `3726450800f8f521bbdeaf98ea0c8130b5c244be2031be8c4b9d1e243ed68357`. 실제 문서 통합·공개는 X00가 수행한다.
