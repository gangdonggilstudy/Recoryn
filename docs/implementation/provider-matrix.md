# B13 Provider 기능·API 검증 행렬

확인일: 2026-11-14. 상태: **B13 구현 REVIEW_READY / BR14-01·02 동일 검토자 RECHECKED**([독립 보안 검토](../reviews/product-provider-security.md)). **모든 실제 모델 추론·실서비스·유료 API 시험은 NOT_RUN**이다. 문서의 모델 예시를 기본 유효 모델로 복사하지 않는다. model ID는 사용자 설정이며 실제 지원·계정·요금·품질·보존 조건은 별도 확인 대상이다.

## 구현 경로

| 제공업체 / 클래스 | 구현한 입력·기능 | wire 및 출력 검사 | 범위·한계 |
| --- | --- | --- | --- |
| Faster-Whisper / FasterWhisperProvider | 명시적 로컬 모델 디렉터리, PCM WAV 전사, segment 시간, 언어 hint/자동 감지 | 실행 시 lazy import·WhisperModel; model.bin/config.json/tokenizer.json 확인, local_files_only=True, cpu/cuda 명시 | package/모델 실제 로드 NOT_RUN. 자동 다운로드·CPU fallback 없음. 내부 VAD는 끄며 B12 전처리와 이중 적용하지 않는다. 네이티브 realtime이라고 주장하지 않는다. |
| Ollama / OllamaSummarizer | 텍스트 요약, 5개 템플릿, 긴 입력 계층 처리 | POST /api/chat, stream=false, format=json, options.num_ctx/num_predict; done/stop과 message.content JSON 검사 | STT 미지원. loopback만으로 로컬 실행을 판정하지 않는다. endpoint/model/artifact digest·cloud_disabled·만료가 묶인 LocalModelAttestation과 B14의 승인·grant가 필요하다. |
| OpenAI / OpenAITranscriber | PCM WAV 파일 전사. 기본 JSON text는 clip 단위 시간 표시 | POST /v1/audio/transcriptions multipart; 원본 경로 대신 audio.wav 파일명, audio 데이터 권한 | verbose segment mode는 문서로 확인한 whisper-1 선택에만 제공한다. 문서의 모델별 제한·폐기 일정은 사용 시 재확인한다. word timestamp/diarization/streaming 미구현이며 지원한다고 선언하지 않는다. |
| OpenAI / OpenAISummarizer | text 요약·근거·긴 입력 | POST /v1/responses, input/instructions, max_output_tokens, store=false, stream=false, truncation=disabled; completed/output message의 output_text | STT와 다른 객체/endpoint/권한이다. 서버 JSON schema 강제 모드에 의존하지 않고 클라이언트에서 엄격 검증한다. store=false가 공급자의 모든 로그/보관 삭제를 보장하지 않는다. |
| Anthropic / AnthropicSummarizer | text 요약·근거·긴 입력 | POST /v1/messages, system/messages/max_tokens, stream=false; anthropic-version=2026-10-21 기본, end_turn/content text | B13 STT는 미지원. 버전은 ProviderConfig.api_version으로 명시 변경 가능하다. 최신 문서의 인증 header는 호출자의 vault/Gateway 설정으로 공급하며 어댑터가 키를 저장하지 않는다. |
| Gemini / GeminiTranscriber | WAV inlineData 음성→생성형 텍스트 전사 | POST /v1beta/models/{사용자model}:generateContent; inlineData.mimeType/data, maxOutputTokens, STOP/candidate text | 정확한 segment alignment라고 표시하지 않고 전체 clip 시간이다. Files API·외부 URI fetch·Live API·화자 신원 추정은 미구현. |
| Gemini / GeminiSummarizer | text 요약·근거·긴 입력 | 같은 generateContent REST, systemInstruction/contents, generationConfig.responseMimeType/maxOutputTokens; STOP와 JSON 검사 | audio와 text는 별도 객체·data type이다. 최신 audio 가이드의 Interactions 예제를 generateContent payload와 혼용하지 않는다. |

## 공개 API와 안전한 기본값

- providers/contracts.py의 frozen DTO를 providers에서 export한다. ProviderConfig(provider_id, model, endpoint="", execution_location="remote", timeout_seconds=60, max_response_bytes=4MiB, context_window_tokens=None, max_output_tokens=1024, max_requests=128, local_attestation=None, api_version="2026-10-21").
- FasterWhisperProvider(model_path: Path, *, device="cpu", compute_type=None, timeout_seconds=300, model_factory=None). 생성자는 장치/파일/모델을 열지 않는다. 로컬 모델 및 audio 경로는 절대 경로이며 링크/reparse/hardlink를 거부한다. 모델 가중치·tokenizer의 신뢰/라이선스·정확한 의존성 버전은 B10 ModelManager와 설치 증거에 의존한다.
- 나머지 어댑터는 (gateway: GatewayLike, config: ProviderConfig). transcribe(STTRequest, context=None) 또는 summarize(SummaryRequest, context=None)를 호출한다. capabilities()는 어댑터 기능 선언이고 설치·실제 모델 검증 성공의 뜻이 아니다.
- STTRequest(audio_path, language=None, offset_ms=0, track_id="audio", audio_revision_id=""). 원본 hash/offset/범위/내용에서 segment ID를 재현하고 원본 WAV를 수정하지 않는다. 업로드는 WAV만 구현했다. 앱 상한은 remote 8MiB/local 128MiB이며 공급자의 더 큰 지원량과 구별한다.
- SummaryRequest(transcript_revision_id, segments: tuple[TranscriptSegment,...], template="meeting", output_language="ko", chunk_chars=4000, overlap_segments=1, checkpoint=None). 템플릿은 meeting/lecture/key_points/decisions/tasks다. 긴 segment는 원 ID와 문자 span을 보존해 나눈다.
- ExecutionContext(cancel=Event(), progress=None, reservation_factory=None, headers={}). callback은 (provider_id, 정확한 endpoint, data_type, body bytes 수)마다 **새** 예약 ID를 반환한다. 같은 ID를 여러 하위 요청에 재사용하지 않는다. header repr는 비밀을 표시하지 않으며 키 생성·저장은 B14 vault 책임이다.
- GatewayLike.request의 첫 4개 인자는 positional-only protocol로 정의해 B14의 target/endpoint 이름 차이를 흡수한다. 실제 HTTP는 이 protocol 하나뿐이며 네트워크 SDK import·직접 socket·자동 retry는 없다. B10이 Gateway.for_session(session_id, generation)을 주입한다.

## 긴 문서·근거·취소·실패

context_window_tokens 미상은 CONTEXT_LIMIT_UNKNOWN으로 실행을 막는다. caller가 검증한 모델/런타임 한도를 공급해야 한다. 내장 계획은 출력 여유·고정 여유를 남긴 UTF-8 byte 기반 보수적 입력 추정이며 실제 tokenizer의 정확한 토큰 수나 호환성을 보장하지 않는다. wire envelope도 실행 전 검사하고 초과 입력을 조용히 자르지 않는다.

core와 overlap context를 나누고 모든 core 문자 span을 coverage로 기록한다. context-only claim의 중복 게시는 제외한다. 중간 요약과 최종 통합도 원 segment ID를 유지하고, 합성 입력이 크면 추가 계층으로 묶는다. 병합으로 그룹 수를 줄일 수 없으면 CONTEXT_LIMIT이며 무한 호출하지 않는다. 하위 호출 예산·취소·진행은 각 호출에 적용된다.

원 전사/모델/endpoint/템플릿/설정의 digest와 completed chunk/claims/coverage를 checkpoint에 보존한다. resume은 digest·chunk·span·reference에 더해 fresh-output `parse_claims`와 동일한 원본 provenance·core 소유·status/basis 분류를 재검증한다. 정규화 결과와 다른 캐시는 CHECKPOINT_MISMATCH로 거부하고 완료 core를 다시 보내지 않는다. checkpoint는 모델 사실성이나 외부에서 만든 캐시의 진위를 인증하지 않는다. 실패·취소된 뒤에는 이전의 유효 core 결과와 missing span을 반환하고 전체 complete를 거짓으로 둔다. 모든 core가 있어도 최종 통합 실패는 전체 완료가 아니다.

model의 reference는 허용 집합에 존재해야 한다. 유효 ID가 의미상 지지라는 뜻은 아니며 자동 claim은 uncertain이다. 무근거는 unsupported/model_inference, 사용자 삽입은 user_assertion, unresolved 발화 근거는 model_inference로 구분한다. 모델의 supported 라벨을 사람 검증으로 승격하지 않는다.

원문 core 호출은 transcript, 중간 요약 통합은 context, STT는 audio data type을 사용하므로 별도 grant가 필요하다. LocalModelAttestation은 신뢰된 모델/서버 관리자가 만든 증거의 전달물이며 그 자체가 데몬의 후속 egress를 입증하는 수단이 아니다. 불명 로컬 실행은 차단한다.

취소는 Event 협력 취소이며 로컬 generator의 다음 경계·Gateway의 handoff 경계에서 검사한다. 이미 실행 중인 native inference 또는 원격 청구/저장을 중단·회수했다고 보장하지 않는다. DTO timeout은 작업 기한, Gateway.timeout은 blocking IO timeout이다. B14 공개 request에는 per-request timeout 인자가 없으므로 B10이 같은 정책으로 설정해야 한다. 원격 결과 불명은 outcome_known=False로 보존하고 자동 재송신하지 않는다. 원시 예외·본문 대신 안전한 ProviderError.code만 표시한다.

## 공식 1차 자료

- [Faster-Whisper 공식 소스](https://github.com/SYSTRAN/faster-whisper/blob/master/faster_whisper/transcribe.py): local_files_only 및 로컬 tokenizer 경로/없을 때의 fallback을 확인했다. tokenizer.json을 필수 확인하는 이유다. 라이선스와 버전별 CUDA 호환성 검토는 별도다.
- [Ollama chat](https://docs.ollama.com/api/chat), [인증 및 로컬 API 경유 cloud 예시](https://docs.ollama.com/api/authentication): chat JSON·완료 표시와 loopback/실제 처리 위치의 차이를 확인했다.
- [OpenAI transcription REST](https://developers.openai.com/api/reference/resources/audio/subresources/transcriptions/methods/create), [file transcription 가이드](https://developers.openai.com/api/docs/guides/speech-to-text), [Responses REST](https://developers.openai.com/api/reference/resources/responses/methods/create): multipart, 모델별 response format·timestamp, text output·출력 상한·완료 상태를 확인했다.
- [Anthropic Messages REST](https://platform.claude.com/docs/en/api/messages/create): 현재 버전 header·요청·완료/중단 text 응답 형태를 확인했다.
- [Gemini GenerateContent REST](https://aistudio.google.com/api-reference/generate-content), [audio 가이드](https://aistudio.google.com/docs/audio): audio/text 입력, inline data, 출력 상한·candidate 완료 상태를 확인했다. 가이드는 inline 총 요청 20MB를 설명하며 이 구현은 더 작은 앱 상한을 적용한다.

## 검증 상태

초기 자체 provider·계약 시험은 125 passed였고 BR14-01/02 수정 회귀 5개를 추가하여 **130개**다. 변경 전 자체 반례 실행은 4 FAIL / 1 PASS, 변경 후 자체+BR14 독립 보안 시험 파일 재실행은 **148 passed**다(독립 검토자의 재확인과는 별개인 작성자 실행). fake factory·fake Gateway·합성 WAV 외에, 실제 B14 ConsentStore/Gateway의 session binding을 fake transport로 검사하여 미동의·세션 철회 시 transport 생성 0건을 확인했다. 실제 endpoint에는 접속하지 않았다. 중단·형식 오류·모델의 허위 supported 라벨·범위 밖 reference·UNKNOWN·비용 예약 중복·재개 digest 변경, 캐시의 근거 분류 승격·백엔드 예외의 깨진 __str__를 포함한다.

이후 B14 동일 검토자의 강화된 독립 재확인 기록은 **19 PASS / 자체 unit·contract 포함 149 PASS**, skip/xfail 0이다. 정상 provenance checkpoint의 무전송 재개와 generator 예외 후 partial 보존·반복 호출 lock 해제도 포함한다. 두 발견 사항은 해당 검토 범위에서 종결됐으며 전체 제품 통합·G3/G4 통과를 뜻하지 않는다. runtime 재확인 digest는 transcription/adapters.py `b25c8abcac995f9bc7cb042ffecf59e6d86755085d61789d206b975abda24304`, summarization/adapters.py `c5b1663d13cb5df7f43ca2da1b492b878c023c405180a4090bcd983e3ef9fcb4`다.

148개 실행의 분리 coverage는 providers line **98.98% / branch 96.77%**, transcription **97.88% / 96.77%**, summarization **96.73% / 91.67%**다. 새 8개 runtime 파일은 Ruff lint/format과 mypy strict를 통과했다. 측정 JSON: C:/Users/gangd/AppData/Local/Temp/recoryn-b13-review-green-22a76dc77a634b4ebf7ade6c5f37d37f/coverage.json. 임시 증거의 수명은 저장소와 별도이며 아래 명령으로 다시 실행할 수 있다.

~~~powershell
$b13Run = Join-Path ([IO.Path]::GetTempPath()) ('recoryn-b13-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $b13Run | Out-Null
$env:COVERAGE_FILE = Join-Path $b13Run 'coverage.data'
$b13Report = 'json:' + (Join-Path $b13Run 'coverage.json')
.venv/Scripts/python.exe -m pytest tests/unit/test_providers.py tests/contract tests/integration/test_provider_security_independent.py -p no:cacheprovider --basetemp (Join-Path $b13Run 'fixtures') --cov=recoryn.providers --cov=recoryn.transcription --cov=recoryn.summarization --cov-report term-missing --cov-report $b13Report -q -W error::ResourceWarning
.venv/Scripts/python.exe -m ruff check src/recoryn/providers src/recoryn/transcription src/recoryn/summarization tests/unit/test_providers.py tests/contract
.venv/Scripts/python.exe -m mypy src/recoryn/providers src/recoryn/transcription src/recoryn/summarization
~~~

실제 Faster-Whisper/Ollama/OpenAI/Anthropic/Gemini 실행은 모두 NOT_RUN이고 실제 모델 다운로드·키·사용자 음성 송신·유료 호출은 0건이다. 공급자별 실제 가격·usage 정산과 모든 server/runtime 버전의 호환성을 검증한 것이 아니다. optional Faster-Whisper 의존성의 설치·고정 버전은 B10 소유이며 B13이 공용 설정을 변경하지 않았다. 공식 문서 확인과 fixture 통과를 실제 서비스 호환성·음성 품질 평가로 확대하지 않는다.
