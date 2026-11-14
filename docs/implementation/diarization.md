# B22 선택적 로컬 화자 분리 계약

상태: **R13 / B22 REVIEW_READY, 작성자 자체 검증 완료·독립 승인 대기**. B10이 기존 공개 API·버전 제안을 채택했다. 실제 모델 추론·품질·음성·다운로드·daemon 실행은 NOT_RUN이다. B21이 UI와 새 revision 게시를 통합한다. 기존 전사·녹음·공용 설정은 B22가 수정하지 않는다.

## 공개 API

`recoryn.diarization`은 다음 frozen DTO와 클래스를 공개한다. 생성자/import는 파일·모델·프로세스를 열지 않는다. 예외는 기존 ProviderError의 안전한 code만 사용한다.

```python
DiarizationConfig(manifest_path: Path, manifest_sha256: str,
                  license_accepted: bool = False, device: str = "cpu",
                  num_threads: int = 1, num_speakers: int | None = None,
                  threshold: float = 0.5, max_audio_ms: int = 300_000,
                  timeout_seconds: float = 300)
DiarizationRequest(audio_path: Path, offset_ms: int = 0, track_id: str = "mic")
SpeakerTurn(start_ms: int, end_ms: int, speaker: str,
            track_id: str = "mic", uncertain: bool = True)
DiarizationResult(turns: tuple[SpeakerTurn, ...], complete: bool,
                  cancelled: bool = False, error_code: str | None = None,
                  audio_sha256: str = "", model_manifest_sha256: str = "",
                  warnings: tuple[str, ...] = ())
LocalDiarizationProcess(config)
provider.capabilities() -> dict  # cpu, formats, input bound, dependency state, NOT_RUN
provider.diarize(request, context: ExecutionContext | None = None) -> DiarizationResult
provider.close() -> None
assign_speakers(segments: Sequence[content.Segment], turns: Sequence[SpeakerTurn],
                *, min_coverage: float = 0.8) -> tuple[content.Segment, ...]
```

실행은 CPU만 명시 허용한다. GPU나 자동 fallback은 없다. 입력은 **16kHz mono 16bit PCM WAV, 최대 5분**이며 더 큰 값으로 상한을 올릴 수 없다. 다중 채널·다른 포맷·긴 세션의 변환/선택 범위는 B21 파생 오디오가 담당하고 원본을 수정하지 않는다. 여러 구간을 따로 처리한 화자 ID를 같은 신원으로 연결하지 않는다. timeout은 owned child 종료 확인을 포함하며 종료 ack 실패는 완료가 아니다.

턴의 시간은 request.offset_ms를 더한 고정 세션 시간이며 track_id를 유지한다. 익명 라벨에는 입력·모델·설정 scope가 포함된다. 같은 사람의 신원을 식별하거나 다른 입력의 화자를 연결하는 기능이 아니다. 모든 라벨은 uncertain 추정이다. 서로 다른 화자의 턴이 겹치면 OVERLAP_UNCERTAIN을 함께 보고한다.

assign_speakers는 새 tuple/Segment를 파생하고 원문·ID·시간·provenance·트랙을 수정하지 않는다. 기존 명시 speaker는 보존한다. audio/model 시간 품질에서만, 단일 화자 구간이 문장 범위의 최소 비율을 덮고 경쟁 화자 겹침이 없을 때 익명 라벨을 추가한다. 사용자 삽입·unresolved·clip/unverified 시간·0길이·경쟁 화자는 자동 승격하지 않는다. B21은 complete 결과만 별도 revision으로 게시하고 model/manifest/audio hash·추정 표시·선택 범위를 coverage에 남겨야 한다. B22 함수는 DB나 active revision을 쓰지 않는다.

## 파일·라이선스·외부 데이터

런타임 pin은 **sherpa-onnx==2.0.1**, ONNX 바이트 감사는 **onnx==1.23.2**, 변환은 기존 local-ai와 같은 **numpy==2.3.5**다. 설치/lock/배포는 B10 소유다. 현재 구현은 **Windows x64, Python 3.12 이상, CPU만** 허용하며 Python 3.11·다른 플랫폼은 명시 미지원이다. ONNX의 abi3 wheel 설명은 Python 3.12 이후이며 이 버전의 [공식 배포 메타데이터](https://pypi.org/pypi/onnx/1.23.2/json)와 [sherpa 배포 메타데이터](https://pypi.org/pypi/sherpa-onnx/2.0.1/json)를 대조했다. 패키지·버전·플랫폼 미지원은 capability/안전한 오류로 표시하며 자동 설치하지 않는다. 이 조건은 어댑터의 실행 제한이며 모든 Python/Windows 조합의 검증 완료 주장이 아니다.

사용자가 신뢰한 manifest의 **실제 바이트 SHA256**를 외부 설정으로 고정하고 라이선스 동의를 명시해야 한다. hash 자체가 배포자를 인증하거나 라이선스 적합성을 법률 판단하는 것은 아니다. schema_version=1만 허용한다. 필수 모델은 segmentation.onnx, embedding.onnx이며 각각 license 파일의 digest도 확인한다.

```json
{"schema_version":1,"runtime":"sherpa-onnx","runtime_version":"2.0.1","models":{
  "segmentation":{"file":"segmentation.onnx","size":1,"sha256":"<64 lowercase hex>",
    "license_id":"<확인한 조건>","license_url":"https://publisher.example/license",
    "license_file":"LICENSE.segmentation.txt","license_sha256":"<64 lowercase hex>"},
  "embedding":{"file":"embedding.onnx","size":1,"sha256":"<64 lowercase hex>",
    "license_id":"<확인한 조건>","license_url":"https://publisher.example/license",
    "license_file":"LICENSE.embedding.txt","license_sha256":"<64 lowercase hex>"}}}
```

이는 형식 예시이며 유효한 가중치/hash/라이선스를 제공하지 않는다. 각 ONNX 최대 128MiB, manifest/license 각 64KiB, 모델 총 256MiB다. 경로는 명시 로컬 파일만 허용하고 symlink/reparse/hardlink·UNC·탈출 경로를 거부한다. 검증한 bytes를 child 소유 임시 경로에 고정해 원본 검증 후 재열기 경쟁을 줄인다. ONNX는 load_model_from_string의 protobuf 경로로 파싱하고 중첩 message의 모든 TensorProto에 external_data 또는 EXTERNAL data_location이 있으면 거부한다. 모델 pickle/임의 Python/remote code/외부 custom-op library/네트워크/자동 다운로드 경로를 제공하지 않는다.

## 프로세스와 실패 계약

한 인스턴스는 동시에 한 번만 실행하며 bounded owned spawn child를 사용한다. child는 시작 gate에서 기다리고 parent가 Windows Job Object에 할당한 뒤에만 모델을 읽는다. job handle은 비상속이며 KILL_ON_JOB_CLOSE, 한 프로세스, commit memory 1GiB를 적용한다. 설정 실패는 gate를 열지 않고 실패한다. 부모가 죽거나 취소/timeout이면 자기 child만 종료하고 ack를 기다린다. Python thread watchdog만으로 native GIL 작업의 부모 종료를 보장하지 않는다. 다른 플랫폼은 동등한 lifetime guard가 없으면 명시 미지원이다.

실행 오류·취소는 complete=False와 안전한 code이며 원문을 게시하지 않는다. native 출력은 유한·유효 시간·익명 cluster 수·턴 개수·트랙·입력 길이 경계로 검사한다. 완료 전 native의 부분 출력이 실제로 어떤 범위를 처리했는지 확인되지 않으므로 취소된 오프라인 결과를 완성 화자 분리로 취급하지 않는다. 모델 메모리 사용·5분 wall time·정확도는 실측하지 않았다.

`process.py`는 부모에서 WAV 포맷·크기·hash를 고정하고 child에서 다시 같은 hash를 확인한다. 모델·라이선스·ONNX 파싱과 native import는 guard 할당 후 child에서 수행한다. 응답은 최대 1MiB의 JSON `send_bytes/recv_bytes`이며 객체 `recv()`나 모델 pickle 역직렬화를 사용하지 않는다. Python spawn의 신뢰된 내부 시작 인자 전달과 외부 모델 로딩을 구분한다. 부모는 결과의 audio/manifest hash·track·offset 범위를 재검사하며 취소·timeout 관측 뒤 늦은 성공을 반환하지 않는다. 취소의 부분 턴은 게시하지 않는다.

`close()`는 최종 종료이며 닫은 인스턴스는 다시 실행하지 않는다. 취소를 child Event에 전달한 후 소유 child만 종료·join하고 ACK 뒤에 process/Job/Pipe 핸들을 닫는다. ACK 실패는 `DIARIZATION_ACK_PENDING` 예외와 소유 핸들을 유지하며 성공·취소 완료로 반환하지 않는다. 동시 호출은 한 인스턴스의 lock과 요청별 timeout/취소로 제한한다. 프로세스 이름·전체 PID 검색이나 공유 서버 종료를 하지 않는다.

capability는 네이티브 import 없이 distribution metadata만 읽어 missing/unsupported/installed를 구분한다. `model_state=not_checked`, 품질 `NOT_RUN`을 보존하며 의존성 설치를 모델 준비로 표시하지 않는다. 실제 모델 설치/검증은 명시 실행 시에만 한다. Python fake의 DNS/socket guard 통과는 실제 가중치·SDK 전체의 OS 네트워크 격리 인증이 아니다.

## 공식 근거와 검증 상태

- [sherpa v2.0.1 Python 예제](https://github.com/k2-fsa/sherpa-onnx/blob/v2.0.1/python-api-examples/offline-speaker-diarization.py), [바인딩](https://github.com/k2-fsa/sherpa-onnx/blob/v2.0.1/sherpa-onnx/python/csrc/offline-speaker-diarization.cc): segmentation/embedding/clustering 조합, sample_rate, process callback·정렬 결과를 확인했다. 예제의 다운로드 명령은 실행하지 않았다.
- [embedding CPU 설정](https://github.com/k2-fsa/sherpa-onnx/blob/v2.0.1/sherpa-onnx/python/csrc/speaker-embedding-extractor.cc), [릴리스](https://github.com/k2-fsa/sherpa-onnx/releases/tag/v2.0.1), [공식 모델 설명](https://k2-fsa.github.io/sherpa/onnx/speaker-diarization/models.html): 원 모델과 변환물의 조건은 별도 확인 대상이다. sherpa 소스 Apache-2.0을 모든 모델의 조건으로 확대하지 않는다.
- [ONNX v1.23.2 loader](https://github.com/onnx/onnx/blob/v1.23.2/onnx/__init__.py), [TensorProto](https://github.com/onnx/onnx/blob/v1.23.2/onnx/onnx.proto), [배포 메타데이터](https://pypi.org/project/onnx/1.23.2/): bytes parsing과 외부 데이터의 분리를 확인했다.
- [Windows Job Object](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects), [extended limits](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_extended_limit_information), [할당 권한](https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-assignprocesstojobobject): lifetime guard의 근거다. 실제 모델/배포 환경의 nested Job 호환성은 NOT_RUN이다.

모델 조건의 근거도 분리한다. 원 [pyannote segmentation-3.0 모델 카드](https://huggingface.co/pyannote/segmentation-3.0)는 MIT 표시와 파일 접근 조건을 별도로 제시한다. sherpa 공식 모델 안내는 이를 ONNX로 변환한 모델과 두 종류의 embedding 예시를 제공한다. [sherpa v2.0.1 소스 라이선스](https://github.com/k2-fsa/sherpa-onnx/blob/v2.0.1/LICENSE), [ONNX v1.23.2 소스 라이선스](https://github.com/onnx/onnx/blob/v1.23.2/LICENSE), [3D-Speaker 저장소 라이선스](https://github.com/modelscope/3D-Speaker/blob/main/LICENSE)는 Apache-2.0이다. 이 저장소 라이선스를 사용자가 확보한 개별 embedding/변환 artifact의 조건으로 대체하지 않는다. 실제 artifact·동봉 license bytes·digest·획득 조건의 독립 검토와 재배포 판단은 미완료다. 계정 로그인·접근 동의·weights 다운로드를 수행하지 않았다.

## R13 자체 검증과 root 통합 제안

온보딩 시 복구 입력은 기존 5개 소스, Job guard unit 9개와 이 문서였다. 이를 보존하고 공개 `__init__.py`·`process.py`, unit 보강과 contract 시험을 추가했다. 2026-11-14 Windows / Python 3.13.1에서 **B22 자체 55 PASS**, BR23 관련 142개와 묶은 실행은 **197 PASS / 8.19s, skip/xfail 0**이었다. 시험 파일·런타임의 Ruff check/format과 mypy strict를 함께 확인한다. 작성 세션이 B22의 독립 검토나 최종 승인을 대신하지 않는다.

타입 검사 지적과 프로세스 생성 실패 시 Pipe 정리 경계를 고친 최종 바이트로 B22를 다시 실행해 **55 PASS / 3.99s**를 확인했고, Ruff check/format·mypy strict **9파일 PASS**다. BR23 대상 gateway/privacy는 root/다른 작성자가 새 guard를 연결 중이므로 그 197개 실행을 제품 전체 동결 snapshot 승인으로 쓰지 않는다. 해당 변경은 [BR23 후단 기록](../reviews/product-egress-review.md)에 별도로 남겼다.

| B22 제출 파일 | SHA256 |
| --- | --- |
| diarization/__init__.py | A28FEB2B9B17DF2C9FAE3173A6DB1C704EA888B5E7D84B3791801FEC67613AD7 |
| diarization/contracts.py | 28CBD034BC35913425FCACC93C42F046D8275FD99216AFEC891A1FAB7654EA8F |
| diarization/assignment.py | 09C20DCC6ABE76CBA84780DF50C33FA4DA469B4B40DCFEB153B4189EA88B7498 |
| diarization/backend.py | CEF7A55AF28B058F6DE6AE8EB27C059291D4CF85554DAFADB1FFC644390F3AF3 |
| diarization/models.py | 74F17D9BE78A4BA5FE7A27AE956912ACE5CF58F481C0962B41C9E0B87D8387E3 |
| diarization/_job.py | 6AAEC80963187DC5DB8D9C01929999CC3FB869B2CA7F31203C40AE29F7FDB1E1 |
| diarization/process.py (최초 REVIEW_READY; BR41 수정 전) | A035FA671B755F7C7C8785C7CB00A00679122923FF5CB91597D5BDD207AC4C42 |
| tests/unit/test_diarization.py | 466FFF083EBFD8EBD7BD12CC642D6FA851EB516DE614F7489835A4433E6912F0 |
| tests/contract/test_diarization_contract.py | C5440826DD8886B0A4ECE0F73E02570F503279BC2AE1C26DEFFDD39B657F1855 |

검증 범위는 잘못된 manifest/라이선스/hash/미래 schema/경로·hardlink, 중첩 ONNX external tensor, 미설치·미지원 의존성/장치/timeout 설정, fake SDK의 공식 CPU 설정·callback 취소·비유한/범위 밖/잘못된 cluster 출력, 익명 scope·겹침·시간·원본 파일 불변, 보수적 라벨 할당, 파생 revision과 동시 사용자 편집 CAS다. 실제 소유 fake child에서는 성공·timeout·취소·close 뒤 종료 ACK, guard 실패 시 닫힌 gate, 부모 supervisor 강제 종료 후 Windows Job의 child 종료 신호를 관측했다. 마지막 시험은 테스트가 만든 해당 supervisor만 종료하며 사용자 세션·서버를 건드리지 않는다.

```powershell
$r13Run = Join-Path $env:TEMP ('recoryn-r13-' + [guid]::NewGuid().ToString('N'))
.venv/Scripts/python.exe -m pytest tests/unit/test_diarization.py tests/contract/test_diarization_contract.py tests/integration/test_egress_independent.py tests/unit/test_security.py tests/unit/test_diagnostics.py tests/integration/test_gateway.py tests/ui/test_privacy_ui.py -q -p no:cacheprovider --basetemp $r13Run -W error::ResourceWarning --tb=short
.venv/Scripts/python.exe -m ruff check src/recoryn/diarization tests/unit/test_diarization.py tests/contract/test_diarization_contract.py
.venv/Scripts/python.exe -m ruff format --check src/recoryn/diarization tests/unit/test_diarization.py tests/contract/test_diarization_contract.py
.venv/Scripts/python.exe -m mypy src/recoryn/diarization tests/unit/test_diarization.py tests/contract/test_diarization_contract.py
```

root 제안: `diarization` 선택 extra로 위 3종 pin과 Python>=3.12 marker를 통합한다. B22는 pyproject/requirements/UI를 수정하지 않았다. B21은 사용자가 선택한 파생 WAV·고정 offset/track·실행 설정과 `complete` 결과를 받아 별도 revision으로 게시한다. 원 전사·active 선택은 CAS로 보호하며 source_ranges/checkpoint에 선택 범위·audio/manifest hash·익명 추정/겹침 경고를 보존한다. 턴이 없는 정상 완료도 처리 범위는 request와 파생 WAV 길이에서 명시하고 화자 없음과 실패를 구분한다. 긴 입력을 여러 요청으로 처리할 때 speaker ID를 같은 인물로 연결하지 않는다.

미검증: 실제 sherpa/ONNX import·모델 실행·DER/겹침 품질·CPU 메모리/지연·가중치 조건·nested Job이 다른 배포 환경과 만나는 경우·UI 전체 연결·패키지·G3/G4. BR13은 R12 REVIEW_READY 뒤 root 재배정에서 수행하며 현재 작성 중 B21을 최종 승인하지 않는다.

## BR41-01 수정 제출 — 독립 재확인 대기

R11 독립 검토자가 cleanup ACK 중 외부 cancel/instance close/deadline을 바꾼 deterministic 반례 3건을 보고했다. 작성자 R13도 수정 전 **3 FAIL**을 재현했다. reply 직후 `_check`는 통과했지만 `finally._reap`가 기다리는 동안 바뀐 상태를 최종 반환에서 재검사하지 않아 성공이 나갔다.

수정은 `process.py`의 성공 경로를 decode → `_reap`의 child/handle ACK → `_check(execution, deadline)` → 결과 반환으로 바꿨다. `finally`의 멱등 정리는 유지하고 ACK 실패 시 성공을 반환하지 않는다. 이 수정의 process.py SHA256은 **9060D883F8C6DC35C2B5B2EB0B4135D4D6D684B2BDFC7FBC1D078E209C75A0CC**다. 독립 원 반례 3건은 **3 PASS / 0.25s**, 자체 unit/contract 55개도 통과했다. Ruff check/format·mypy strict 9파일 PASS다.

독립 전체와 자체 묶음은 **77 PASS / 1 FAIL / 4.64s**였다. 남은 실패는 별도 R11 `real_job_parent_death` 시험에서 supervisor 종료 전에 Popen child가 이미 종료되어 Windows wait값이 258 대신 0인 경우다. 해당 시험은 venv `sys.executable`을 직접 Popen한다. 로컬 CPython `popen_spawn_win32`는 제품 multiprocessing spawn 때 venv redirector를 우회해 base Python을 쓰는 경로가 있으므로 이 차이를 R11/root에 보고했다. 독립 시험을 작성자가 수정하거나 이 실패를 skip/xfail/제품 통과로 바꾸지 않는다. R11의 동일 반례·현재 digest 재확인이 필요하며 본인의 FIXED 주장을 RECHECKED/CLOSED로 최종 승인하지 않는다.
