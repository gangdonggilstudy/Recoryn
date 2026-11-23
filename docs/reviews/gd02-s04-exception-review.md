# GD02-R / GD-P02 S04·ADR17·B13 독립 검토

판정: **REVIEW_READY — OPEN 1건(S3 1), S0/S1/S2 0건**. 검토자 w5:p8 Codex. 작성자 C00의 문서 전용 변경을 검토했다. 검토자는 G-P13 계약 작성에 참여했으며, 이번 판정은 그 계약의 정본 반영/문서 정합성 검토다. G-P13 제품 구현의 독립 승인이나 실제 모델/라이선스 검증이 아니다.

## 1. 고정 입력·확인 방법

- 기준 HEAD: `21a58bfa99c3ab4a381b92a092d5981adc5c9632`.
- 검토 tree: **`cad2c6065235b97d8e01ba9e80d7a47124d5f1ea`**.
- `git diff --stat 21a58bf cad2c6065235b97d8e01ba9e80d7a47124d5f1ea` 결과는 **4파일, +4/−3**다. architecture ADR17, validation S04, product-contracts B13 각각1행 교체와 assignments GD02 한 행 추가다.
- 판정 근거는 `git diff --unified=5 ...`와 **`git show cad2c6065235b97d8e01ba9e80d7a47124d5f1ea:<경로>`**로 읽었다. 아래 줄 번호는 이 tree 기준이다. 작업 트리의 G-P02/G-P04·미커밋 계약 문서를 제품 완료 증거로 섞지 않았다.
- 승인된 G13 계약 입력은 `docs/testing/g13-manual-model-cases.md`, LF SHA256 **`56dc2fefa06329df440552a8a948aa8a625b7f5786a9a75c1fbd8f3ab4aa0007`**로 직접 대조했다. 계약의 “승인 대기” 이력 표제와 별개로 최신 C00 채팅의 승인(a)~(e)를 결정 근거로 사용했다.
- 수정은 이 검토 문서 하나다. 제품/시험/정본·배정표 수정0, Git 쓰기0, 제품 시험 재실행0, 실제 모델·장치·네트워크·설치·법률 판정0이다.

## 2. 발견

### GD02-01 — OPEN / S3: provider-matrix의 설치 증거 설명에 수동 예외 구분이 없음

**근거/재현**

```text
git show cad2c6065235b97d8e01ba9e80d7a47124d5f1ea:docs/implementation/provider-matrix.md
git diff 21a58bf cad2c6065235b97d8e01ba9e80d7a47124d5f1ea -- docs/implementation/provider-matrix.md
```

두 번째 명령의 실제 출력은 비어 있다. 해당 문장의 포괄 설명은 **기준 commit에도 있던 것**이며 신규 runtime 결함으로 판정하지 않는다.

- `docs/implementation/provider-matrix.md:20`은 FasterWhisperProvider 전체를 설명하며 “모델 가중치·tokenizer의 신뢰/라이선스·정확한 의존성 버전은 B10 ModelManager와 설치 증거에 의존한다”고 쓴다. 수동 경로의 예외/사용자 확인 증거와 관리 설치의 증거를 구분하지 않는다.
- 같은 tree의 `docs/validation-plan.md:113`, `docs/architecture-v1.md:288`, `docs/implementation/product-contracts.md:99`는 **관리 설치가 아닌 로컬 Whisper도 사용자 책임·license 미확인 확인 아래 허용**한다고 결정했다. 이 경로는 관리 설치 증거가 없다는 이유만으로 차단하지 않는다는 G13 §3.1/§3.2와 C00 승인(b)의 의미다.
- provider-matrix `:3,9`는 실제 모델 NOT_RUN을 올바르게 구별하지만 `:20`에는 정본의 새 예외 연결이 없다. 여러 문서를 함께 읽을 때 수동 모델도 설치 증거가 필수인지, 확인만으로 이미 공급망 인증이 됐다는 뜻인지 모호하게 남는다.

**기대**

provider 공개 경계 설명에서도 **관리 manifest 대조와 수동 Whisper 사용자 책임 확인을 구별**하고 S04/ADR17을 참조해야 한다. 사용자 확인은 게시자 인증·법률 승인·재배포 허가가 아니며, 새 gate는 G-P13 구현 예정이라는 구분을 유지해야 한다.

**제안**

C00의 문서 변경 또는 명시 후속 문서 단위에서 provider-matrix `:20`에 다음 취지의 한정을 추가한다.

> 관리 설치 모델의 검증 계약은 고정한 manifest/설치 증거를 따른다. 수동 로컬 Whisper의 허용·검증 예외는 validation S04/ADR17에 따르며 사용자 책임 확인을 관리 공급망 인증으로 집계하지 않는다. 새 확인·고정 bytes 검증 경로의 구현은 G-P13이다.

현재 API signature를 미래의 bundle API로 먼저 고치거나 실제 gate가 이미 구현됐다고 적을 필요는 없다. 기존25파일 G-P13 목록에 이 문서는 없으므로 작성자가 임의로 끼워 넣지 말고 C00가 동기화 소유/단위를 정하면 된다. **정책 결정에는 동의하며 문서 연결 누락만 S3로 남긴다.**

## 3. 동의한 범위와 근거

| 관점 | 검토 tree 근거 | 판단 |
| --- | --- | --- |
| 관리 설치/로드 검증 | validation-plan `:113`, G13 §3.1/§3.2 | 사용자가 검토해 고정한 manifest·선언 파일 size/hash/license를 대조하고 설치 폴더의 자기 기술만으로 신뢰를 올리지 않음. digest와 게시자/법률 인증을 구별해 승인 방향과 일치 |
| 수동 Whisper 예외 | validation-plan `:113`, ADR17 `architecture:288`, B13 `product-contracts:99` | 사용자 지정/출처 인증 안 됨·최초 및 digest/출처/고지 변경 확인·실행 bytes 고정/직전 재검사가 반영됨. ADR17은 최초/digest를 요약하지만 더 넓은 변경 사유를 금지하지 않으며 상세 S04가 규정하므로 별도 모순으로 세지 않음 |
| license 미확인 책임 | validation-plan `:113,117`, G13 §3.1 | 사용자 책임/license 미확인을 명시하고 법률 검토와 구별함. USER_ACKNOWLEDGED를 실제 법률 승인으로 올린 새 문장은 없음. 실제 가중치 조건 검토는 여전히 별도 |
| 화자 strict 검증 | validation-plan `:113`, ADR17 `:288`, G13 §3.1 | 예외는 Whisper로 한정. manifest/model/license hash·ONNX 외부 데이터 거부가 완화되지 않음 |
| 일반 경로/전송 요구 | validation-plan S01~S03 `:110-112`, architecture `:199-205` | 수동 예외가 경로/reparse·입력 한도·기본 무전송·capability 검증을 면제하지 않음. local_files_only/자동 다운로드 금지는 B13에도 유지 |
| GPU runtime·fallback | license-review D10 `:69`, L-P07 행 `:81`, l07-gpu-runtime-cases `:7-8,22,27`, architecture `:203,205` | 런타임 약관 동의·고정 wheel/catalog·검증 후 활성화는 다른 대상이라 면제되지 않음. S04의 “묵시 fallback 없음”은 명시 CPU 허용 정책 안의 fallback을 금지하는 새 결정으로 읽지 않음 |
| 설계 결정과 구현 구별 | ADR17 `:288`, validation-plan `:3,113`, B13 `:99` | ADR는 “예외로 결정”과 “구현은 G-P13”을 함께 명시. S04는 시험 통과 정의 문서이며 제품 gate 완료/PASS를 선언하지 않음 |
| 실제 AI/배포 게이트 | validation-plan M02 `:98`, REL01/REL02 `:114-115`, architecture ADR05/09 `:276,280` | 모델 성능/품질·실장비·clean VM·SBOM/실제 license 조건이 이번 예외로 완료되지 않음. 기존 L 문서의 역사적 NOT_RUN/PASS를 재실행 관측처럼 쓰지 않음 |
| 배정/범위 | assignments `:30`, diff stat | GD02 문서 전용4파일 범위에 맞음. tree의 일반 reviewer 표현은 최신 사용자 배정으로 이 검토자에게 구체화됨. 다른 배정의 상태를 이번 delta의 완료/변경으로 세지 않음 |

## 4. 문서 검사와 제한

- changed4파일 전체의 Markdown 표 열 수를 `git show` bytes에서 감사해 모두 일치했다. 새로운 외부 링크/경로 링크 변경은 없으며 S04·B13·ADR17 식별자는 같은 tree에 존재한다.
- provider-matrix는 target/base diff가 비어 있다는 점과 LF hash `119d623a2e2d3e76123d14c07e45650e047146a087956b7017ea4d67d3753047`을 대조했다. G13 계약 hash도 승인 입력과 일치했다.
- 테스트/모델/GPU/계정/인터넷을 실행하지 않았다. 문서 정합성·표 형식 확인을 S04 제품 안전 gate 통과로 보고하지 않는다.

최종 **OPEN 1: GD02-01/S3**. S0 0·S1 0·S2 0·S3 1이다. 정본에 반영한 G13 정책 내용에는 이견이 없으며 provider-matrix 한정/연결의 처리만 C00 결정·후속 확인 대상으로 남긴다.

## RECHECK

재확인 대상은 **`50406e8077f241def62b05a689b3ee96cc6a94ae`**, 직전 검토 tree는 `cad2c6065235b97d8e01ba9e80d7a47124d5f1ea`다. 아래 명령과 새 tree의 `git show <tree>:<경로>`로 판정했다. 기존 1차 검토는 이력으로 보존한다.

```text
git diff --stat cad2c6065235b97d8e01ba9e80d7a47124d5f1ea 50406e8077f241def62b05a689b3ee96cc6a94ae
git diff cad2c6065235b97d8e01ba9e80d7a47124d5f1ea 50406e8077f241def62b05a689b3ee96cc6a94ae
```

실제 차이는 **2파일, +2/−2**다. provider-matrix의 FasterWhisper 설명 한 행과 assignments GD02의 허용 범위 한 행만 바뀌었다. 기존 S04·ADR17·B13의 결정 문구는 유지됐다.

| 발견 | 판정 | 새 tree 근거와 결과 |
| --- | --- | --- |
| GD02-01 / 기존 S3 | **RECHECKED** | `docs/implementation/provider-matrix.md:20`이 관리 설치의 ModelManager/설치 증거와 사용자 지정 디렉터리의 S04 예외를 분리했다. 수동은 사용자 책임·license 미확인 확인, 실행 bytes 고정·실행 직전 재검사를 따르며 **구현 G-P13**이라고 쓴다. 확인을 출처 인증/공급망 검증 완료로 올리지 않는다는 문장도 추가했다. 1차의 포괄 설명/연결 누락이 해소됨 |

`docs/collaboration/assignments.md:30`에 provider-matrix 한 문장이 작성자 C00의 범위로 추가돼 이번 수정의 소유도 일치한다. 새 provider 설명을 같은 tree의 validation S04 `:113`, architecture ADR17 `:288`, product-contracts B13 `:99`와 다시 대조했다. 수동 예외의 대상/조건·화자 strict 유지·실제 구현 예정 구분과 충돌하지 않는다. GPU 런타임/다운로드 정책을 바꾸는 delta도 없다.

문서 표 형식과 기존 세 정본의 미변경을 확인했다. 새 발견은 없다. 제품/시험/모델/GPU/네트워크를 실행하지 않았으며, 재확인은 문서 반영의 종결이다. G-P13 구현·실모델·법률/릴리스 게이트 통과가 아니다.

**재확인 최종 OPEN 0건. GD02-01 RECHECKED.** S0 0·S1 0·S2 0·S3 0이다.
