# L04 패키징·증거 독립 검토

2026-11-15 / 배정 L04·push L-P04 / 작성 C00(w5:p6), 검토 recoryn-arch(w5:p2).

**REVIEW_READY / OPEN 1 (S0 0, S1 0, S2 1, S3 0).** L04-P01은 재생 장치가 없는 환경의 smoke 게이트 누락이며 작성자 수정·동일 반례 재확인이 필요하다. 제출된 후보의 FFmpeg 제외·106개 native 대응과 산출물 hash는 아래와 같이 일치했다. 이 문서는 후보 전체/법률/G4 또는 검토자의 과거 B23 작성분을 자체 승인하지 않는다.

## 교육·범위·방법

AGENTS/onboarding 순서, 설계 입력/통합 설계, workflow/최신 L04 배정, 관련 L02·L03 리뷰와 validation-plan, quality-system, 제품 계약/현재 증거/과거 P0 결과, case-space/push-units를 재확인했다. 정본은 license-review D7, l04-media-backend-cases와 license-results의 L-P04 절이다. ONBOARDING_READY로 범위·독립 분모 계획과 미검증을 보고했다.

현 status/diff의 staged·unstaged 변경을 보존했다. 쓰기는 이 신규 리뷰 파일뿐이다. **제품·시험·설정·Git/인덱스를 수정하지 않았고, 빌드·pytest·제품 EXE·실제 Qt/오디오를 실행하지 않았다.** 읽기 전용 파일/JSON/hash/PE 검사와 부작용 없는 정책 함수·분리한 AST의 계산만 사용했다. Python은 `.venv/Scripts/python.exe -B -W error::ResourceWarning -`이며 bytecode도 쓰지 않았다. 외부 다운로드·모델·네트워크·유료·계정·위임·pane·승인 UI 입력은 수행하지 않았다.

## L04-P01 / S2 / OPEN — 재생 NOT_RUN을 상위 smoke와 빌더가 PASS로 수락

원 바이트 `packaging/release_smoke.py` SHA256은 `a869374ac2503cda61e1d659e1d7b60b41199009062e3c47e87ff7b304829aa7`이며 제출 후보의 inputs 사본과 같다. `_playback_probe`는 출력 장치가 없으면 아래 결과를 반환한다.

```python
{"backend": "windows", "status": "NO_AUDIO_OUTPUT_DEVICE_NOT_RUN"}
```

그러나 `run()`은 이 반환값을 그대로 `playback`에 넣고 최상위 `status`를 무조건 `PASS`로 반환한다. `scripts/build_release.py`(SHA `7b28b74471b12ec1a7d7bf7cdcce9eded18b8063489c4e8fdc5425fd9c0b2b6d`)는 `result.get("status") != "PASS"`만 거부한다. 따라서 필수 WAV 로드/seek/재생이 미실행이어도 frozen smoke 게이트가 통과한다. 이는 cases 문서의 “출력 장치가 없으면 NOT_RUN으로 기록하고 통과로 세지 않는다”와 충돌한다.

원 반례는 `ast.parse`로 원 `run`의 유일한 Return 노드를 추출해 동일 표현식을 함수로 감싼 뒤, `playback`에 위 장치 없음 결과, `child_result={}`, 정상 frames와 fake qVersion을 공급한 순수 계산이다. 실제 관측은 다음과 같다.

```text
original_run_report.status = PASS
original_run_report.playback.status = NO_AUDIO_OUTPUT_DEVICE_NOT_RUN
builder_status_gate_accepts = True
```

Qt·제품·장치·빌드를 실행한 재현은 아니며, 최종 보고식과 빌더 조건의 잘못된 결합을 검증한 반례다. probe 뒤 return 이전에 재생 성공을 요구하는 guard가 없는 것도 원 코드에서 대조했다. 재현 준비 첫 회는 Return이 with 안에 있는 것을 놓친 AST 검색 assertion으로 중단됐고 제품 실패로 세지 않았다. 유일한 Return 노드를 찾은 수정된 검토 계산에서 위 반례를 얻었다.

제안: 상위 smoke에 필수 재생 결과의 성공 여부를 반영해 non-PASS/명시 NOT_RUN으로 내보내고, 빌더도 필수 재생 성공값을 검증한다. 장치 없음 fake 결과가 smoke 성공·빌드 게이트 수락으로 이어지지 않는 원 반례를 추가하되 정상 성공은 유지한다. 환경 미충족을 제품 재생 실패로 꾸미지 말고, 미검증 결과를 통과로 세지 않는다. 대상 수정은 C00에 반환했다.

제출된 실제 후보 smoke 기록은 `LOADED_SEEKED_PLAYED_MUTED_SILENCE`, duration3000ms, position2593ms이므로 이 후보에서 장치 없음 반례가 발생했다는 주장은 아니다. 이번 발견은 다른 환경에서도 증거 게이트가 정직하게 실패/미검증을 보존하는가에 관한 것이다.

## 독립 분모와 금지·허용 판정

기대값은 구현 EXCLUDED_*나 기존 시험 표에서 생성하지 않고 D7의 DLL/플러그인 종류와 유지해야 할 WMF/Qt 구성요소를 기준으로 고정했다.

| 공간 | 별도 분모 | 실제 관측 |
| --- | --- | --- |
| 목적지 금지 | FFmpeg 라이브러리8종 × 버전 대표3(`1`, `63`, `999-hash`) + plugin 기본/debug 대표2 =26이름. 배치2 × 구분자2 × case2 →208 | 208 차단, 누락0 |
| 목적지 허용 | 독립 유지/near-miss12경로 × 배치2 × 구분자2 × case2 →96 | 96 허용, 오제외0 |
| TOC 목적·출처 | 라이브러리8종+plugin1 =9 × 출처 위치2 × 구분자2 × case2 × 금지 배치3(source만/dest만/양쪽) →216 | 216 차단, 누락0 |

총 **520개 제한된 정책 결정 행**이다. 목적지304개와 TOC216개의 tuple case ID 유일성을 별도 확인했고 누락·중복0이었다. 배치는 `_internal/`, `_internal/vendor/plugins/`, 출처 위치는 `C:/venv/Lib/site-packages/PySide6/`와 `C:/external/vendor/`다. 모든 조합을 실행했으며 제품이 거부해야 하는 행을 feasible 조건으로 빼지 않았다.

허용12개는 `plugins/windowsmediaplugin.dll`, `Qt6Multimedia.dll`, `Qt6MultimediaWidgets.dll`, `QtMultimedia.pyd`, `avcodecs/README`, `tools/swscale.txt`, `postprocessing/filters.dll`, `plugins/ffmpeg-notes.txt`, `notes/avcodec.txt`, `avformat_notes.txt`, `avfiltering/filters.dll`, `myavcodec-63.dll`이다. 208 금지는 실제 major 번호에 결합된 규칙인지 확인하는 대표값 검사이며 모든 이름/버전/문자열의 전수 증명은 아니다. prefix를 공유하는 임의 문서 이름까지 허용하는 정책이라는 주장도 하지 않는다.

이 수는 pytest node나 새 회귀 PASS 수가 아니다. 정책의 목적/출처 논리 결정을 읽기 전용으로 대조한 실제 행 수이며 기존 test_release의 금지10/허용7행과 합산하지 않는다.

## hook·spec·시험 oracle

- spec의 GUI/CLI 공통 runtime_hooks 순서는 `rthook_no_av.py` 다음 `rthook_media_backend.py`다. 실제 build.log도 양쪽 Analysis에서 이 custom hook 순서, 그 뒤 PySide6 자동 runtime hook을 기록했다. media hook은 Qt import 없이 `os.environ["QT_MEDIA_BACKEND"]="windows"`로 덮어쓴다. 실제 PyInstaller PySide6 hook은 plugin path 등을 설정하며 이 값을 되돌리지 않는다.
- 상속 환경 없음/빈 문자열/ffmpeg/windows/darwin의5분할을 exact hook의 parsed assignment/function/call 본문과 fake os.environ에 공급해 모두 windows로 고정됨을 확인했다. 실제 세션 환경은 바꾸지 않았다. frozen spawn도 매 프로세스 hook을 거치고 부모의 windows 값을 상속한다. 개발 source import 이후의 Qt backend 변경을 보장하는 hook은 아니다.
- 기존 `_allowed`는 목적/출처 모두 검사하고 Analysis가 추가한 binaries/datas에도 적용한다. 최종 기록 TOC의 빌더 재검사, verify, frozen smoke의 공유 정책 검사도 유지됐다. source를 무해한 목적지로 평탄화한 swscale 반례가 새 spec 시험에 있다.
- test_release의 이전 Qt FFmpeg 허용2행을 D7 금지로 옮기고 WMF/Qt/near-miss를 유지한 것은 정책 변경에 맞다. 성공 판정을 약화한 것으로 보지 않는다. spec의 예상 COLLECT equality·GUI/CLI·runtime hook 순서, 기록 TOC의 정확한 거부 목록도 유지됐다.
- test_evidence의 FFmpeg PATENT_REVIEW_REQUIRED 기대를 삭제한 대신, native 대응표에서 제거된 FFmpeg가 재유입되면 UNMAPPED/license_gaps와 verify 양쪽에서 거부되는2행을 추가했다. 원래의 unknown native·고지 손상·Intel/Microsoft 미확인 oracle는 남아 있다. 분류 DECLARED와 법률 확인 완료를 구분한다. 단, 장치 없음→smoke PASS의 원 반례는 현재 시험에서 검증하지 않아 L04-P01로 남겼다.

## 실제 후보·고지·귀속 읽기 전용 대조

대상 `build/l04-1794733273/dist/Recoryn`의 실제 파일은 **1047개**다. manifest 자신을 제외한1046개 record의 경로 집합이 실제 파일 집합과 같고 중복0, size/hash 불일치0이었다. 제시한 NOTICE/SBOM/native-origins/provenance4개 raw hash도 모두 일치했다.

이전 `build/l03-final-1794720823/dist/Recoryn`의 native112와 새 native106의 차집합은 정확히 아래6개이며 새로 추가된 native는0이다.

```text
_internal/PySide6/avcodec-63.dll
_internal/PySide6/avformat-63.dll
_internal/PySide6/avutil-61.dll
_internal/PySide6/plugins/multimedia/ffmpegmediaplugin.dll
_internal/PySide6/swresample-7.dll
_internal/PySide6/swscale-10.dll
```

새 native 실제 집합 = native-origins의106개 고유 경로 = native-map의106개 고유 경로다. 모든 파일의 실제 SHA/size와 component/license/license_status가 대응표/산출물과 같고 UNMAPPED0이었다. 상태는 DECLARED91 / CONDITIONS_UNCONFIRMED2 / REDISTRIBUTABLE_PROPRIETARY13이다. “전부 명시 분류”는 “전부 조건 확인·법률 승인”과 다르다. 두 EXE의 origin attribution은 기존처럼 REVIEW_REQUIRED로 남아 있으며 이를 ANALYSIS_TOC 확인 완료로 표현하지 않는다.

새 후보 전 파일 경로에서 FFmpeg basename0, LGPL-2.1 사본0, SBOM FFmpeg component0을 확인했다. 새 native106개의 일반+delay PE import에서도 FFmpeg 참조0, 번들/System32/API-set 기준 미해결0이었다(delay import3개 포함). 이는 정적 이름 해석이며 동적 LoadLibrary·ABI/export·다른 Windows/장치의 실행 증명은 아니다.

NOTICE의 `No FFmpeg code is distributed.`와 WMF 재생 설명, FFmpeg gate `NOT_DISTRIBUTED_L01_D1_D7`는 이번 감사 파일 집합과 맞았다. SOURCES.json에도 LGPL-2.1 항목이 없고 NOTICE에 LGPL-2.1/PATENT_REVIEW_REQUIRED 행이 없다. Intel/Microsoft·Qt corresponding source·clean VM·서명·장치 등 미결 gate는 유지됐다. 전체 소스/바이너리의 임의 숨김 코드까지 부재를 증명하거나 모든 코덱 특허 부재를 법률 판단한 것은 아니다.

provenance에 기록된 inputs 파일 hash 전부가 실제 inputs 사본과 일치했고 analysis-toc SHA도 일치했다. 정책/spec/hook/evidence/native-map/SOURCES6개 핵심 workspace 파일도 제출 후보 inputs와 같았다. 저장된 smoke는 windows backend와 duration/position을 보고하지만 **검토자가 재생을 재실행한 결과는 아니다**. 별도 재생 독립 검토·최종 정확 tree 회귀/CI는 C00의 통합 게이트다.

## 바이트와 인계

지시한 입력10개 raw SHA는 전부 일치했다. 판정의 핵심 바이트는 다음과 같다.

| 대상 | SHA256 |
| --- | --- |
| release_manager.py | e256aa28bb02c1c86d7abb16c8d73b4d0ea6e956d65948956a2f1948dab9a25c |
| recoryn.spec | 5e02f9142cd03d84476a36dd9b2f4589fdcbe6dcc17c19ffd2d2b3eb4fb45027 |
| rthook_media_backend.py | cde575a98f23bef4bbe9cc93d5c82db2a457f959fd48b9daef05dee6cedbfd8c |
| release_evidence.py | 1b92fe916fa78e6726a67de6a4ceb078e768ba47f12bbdce5aaab720684e8eb7 |
| native-map.json | 53b7d6d609f587620087dd784d52d27eb2d20a47c2fd8853c8310bb7c528b44e |
| SOURCES.json | af76d99ae19d1003a5806aafc4be545bdc4fd2e24058a09a59360dd0bbf65a62 |
| 후보 NOTICE.txt | e12f388495f8c28ba8f3639a4e5383f49eb3aeb1607991eb8b8d6edec104c839 |
| 후보 sbom.cdx.json | 943768abc4dff8561a6c877e5c83076d8c1e7b3be3619876d277ce303741da53 |
| 후보 native-origins.json | d1471614e570ad2c6213f7a10b32c6d2d8bfaee63faebda34a642db7d8ad5b9e |
| 후보 build-provenance.json | 2139d0b9fa9c87c3625e06510bdc2c8d38fe57ceca0fcf8f16ca12100d2f6735 |

L04-P01은 원 반례·영향·제안과 함께 C00에 전달했다. 대상·시험·Git/인덱스를 고치거나 별도 빌드를 하지 않았다. 실제 음성/모델/계정/네트워크/물리 청취·Windows N/KN·전체 법률/G4는 이번 검토로 통과 처리하지 않는다. **REVIEW_READY / OPEN 1(S2: L04-P01)**. 작성자 FIXED 보고 뒤 동일 반례를 이 문서 후단에서 재확인한다.

## L04 재확인 — 새 PCM sink 후보

2026-11-15, C00가 설계와 패키징을 수정해 지정한 raw hash 및 `build/l04b-1794734467/dist/Recoryn`을 읽기 전용으로 재확인했다. 리뷰어는 빌드·smoke·Qt·시험을 실행하지 않았다.

### L04-P01 원 NOT_RUN 반례 재확인

새 `release_smoke.overall_status(playback)`는 오직 `PCM_SINK_PLAYED_MUTED_FROM_EXACT_FRAME`에서 PASS를 준다. 장치 없음 `NO_AUDIO_OUTPUT_DEVICE_NOT_RUN`, 비어 있는 dict, 이전 WMF 성공 표식은 `PLAYBACK_NOT_VERIFIED`다. `run()`은 이 값을 최상위 status에 반영한다. 빌더는 별도 `smoke_verdict`로 최상위 PASS와 playback dict 내부의 성공 표식을 각각 확인한다.

원 반례 `{status: PASS, playback: {status: NO_AUDIO_OUTPUT_DEVICE_NOT_RUN}}`가 독립적으로 빌더에 거부되는 hand-written 표 6행을 읽었다. 기존 smoke success 표식과 함께 `test_smoke.py::test_not_run_or_unverified_playback_is_never_a_pass`, `test_build_inputs.py::test_builder_requires_verified_playback_in_smoke`에 원 NOT_RUN 행이 보인다. 이 원 oracle는 약화되지 않았다. 코드·시험을 실행하지 않았으므로 **코드 경로 및 독립 테스트 설계 RECHECKED**이고, 새 테스트의 실제 실행 결과는 C00의 별도 정확 tree 증거에 맡긴다.

### 금지·허용 정책과 hook 재확인

L04 case-space의 결정표가 `windowsmediaplugin.dll`을 금지에, Qt Multimedia 본체/Widgets/PYD는 허용에 추가한다. native-map 112→105 분모도 일치했다. spec은 media backend runtime hook 없이 `rthook_no_av.py` 하나를 지정하며 `release_manager`의 `windowsmediaplugin` basename 규칙을 destinations/sources 후단 필터·TOC 확인·verify/smoke가 공유한다. 지정 입력 hash로 검사한 WMF 플러그인 규칙은 `QT_MEDIA_BACKEND_UNUSED_RECORYN_PCM_PLAYBACK`이다. `rthook_media_backend.py`는 작업 트리에 없다. 따라서 삭제된 hook이 WMF를 재선택하는 경로를 더는 제공하지 않는다.

### 실제 후보 차이·귀속·고지

이전 `build/l03-final-1794720823` native112와 새 후보 native105의 차집합은 정확히 7개이며 추가 native0이다.

```text
_internal/PySide6/avcodec-63.dll
_internal/PySide6/avformat-63.dll
_internal/PySide6/avutil-61.dll
_internal/PySide6/plugins/multimedia/ffmpegmediaplugin.dll
_internal/PySide6/plugins/multimedia/windowsmediaplugin.dll
_internal/PySide6/swresample-7.dll
_internal/PySide6/swscale-10.dll
```

후보1046파일/manifest1045 native-origin105 records, native-map105 unique rows다. 각 native path의 실제 bytes hash/size/component/license/status가 map과 origins에 일치하고 중복·불일치0이다. 새 multimedia plugin 경로는0, native map의 unmapped는0이다. 제시한 NOTICE/SBOM/native-origins/provenance hash가 전부 일치했다. provenance의 FFmpeg gate는 `NOT_DISTRIBUTED_L01_D1_D7`, hardware/clean VM/signing 등 별도 gate는 계속 NOT_RUN/REVIEW_REQUIRED다.

NOTICE에는 FFmpeg 및 Windows Media Foundation media backend plugin 모두 비배포로 적고, Recoryn 자체 verified PCM 재생을 설명한다. LGPL-2.1 원문/SOURCES 항목과 NOTICE의 LGPL-2.1·FFmpeg patent row는 없으며 SBOM에도 FFmpeg component가 없다. 이는 이 후보 파일·증거의 일치 판정이며 법률 적합성 승인으로 넓히지 않는다.

후보의 제출 smoke 기록 `build/l04b-1794734467/smoke.stdout.json`은 SHA256 `35303b351394c9adee27bd975bbf0386ff2559277caaa03d5b69096bdc9ec55f`이고, playback에는 `PCM_SINK_PLAYED_MUTED_FROM_EXACT_FRAME`, 12 입력 채널, 정확한 시작 frame32000, 위치2208/2658ms를 기록한다. 저장된 관측상 새 후보는 성공이다. 본 리뷰어는 해당 재생을 실행하거나 청취하지 않았다.

### 최종 읽기 바이트

| 대상 | SHA256 |
| --- | --- |
| release_manager.py | 8cde36b6a37175d61a172a489ac6930e9bd543fef5d1fd579f9381c89888471e |
| recoryn.spec | 411e70efd03b99750046551d69d964e779d3f8a7029c123f03071586045f8c5c |
| release_smoke.py | 8df877038951028594a0b0f429daa3e6773e1a5844db55fb705c2ce56e29c7fc |
| release_evidence.py | c40e02e539b9b1f8dac94fdb69d5a751109fc5b5ceee4f3f3a085cebf13085ca |
| build_release.py | 2b1adc6719bd0819019f2b4d8daf15b49f28223a3b30ade62b8dd6d5847c1ace |
| native-map.json | 7a6a2516d3ef994d31eb75cbe30a9a6d5f67d40175668dc9ffcbf5eed2d04a3d |
| SOURCES.json | af76d99ae19d1003a5806aafc4be545bdc4fd2e24058a09a59360dd0bbf65a62 (unchanged) |
| test_release.py | 0f5e0c4e1fe45b257e5caa7903c4ef7f52b3c0bbee916c39af2f7a2f78d807a0 |
| test_spec.py | 42cdc31c2b680ee7472a388e8264634165181004060eb4a370c6dff93bdf5123 |
| test_build_inputs.py | 3c9be390c6c1165cb25843c57c88270e9c6652094f11751fc413128af3769da5 |
| test_evidence.py | f20fc1356b72d46d513828b6ec0a34ccd289b8b49630a9bab0f636b878e5b08e |
| tests/release/test_smoke.py | bbe77100e3f8e7a64d238fea4354659a35c9dc0b507da67ca96084f8c3cf9661 |
| candidate NOTICE.txt | ecb4e22ee4be6663e2fb7033b72eccb91bd62f6486346813fcf7978bdc8b9171 |
| candidate SBOM | ad331b2b88335831fdfb833a90674421e3170e90e939cf6adff0ec832b0d803a |
| candidate native-origins | 3ae59c1b339104ec573de26b2ebac00fc906d83c0f2cf1b91e5d61ca3c298667 |
| candidate provenance | e5c9c7ce17a183a5810a88497e7bc49e9ddf641527a985c25fd71ba381e57e63 |

이번 수정 범위에서 다른 열린 패키징 발견은 나오지 않았다. L04-P01 원 반례는 **RECHECKED / CLOSED 후보**로 판정한다. 저장된 후보 성공 evidence와 hook·정책·oracle 코드를 확인했으며, 물리 재생·pytest·정확한 L-P04 stage tree/원격 CI는 이 재확인으로 대체하지 않는다. 별도 desktop reviewer의 재생 경계 검토 및 C00 통합 게이트는 계속 적용된다. **REVIEW_READY / OPEN 0 (S0 0, S1 0, S2 0, S3 0)**. L-P04 독립 검토의 최종 통합 수락은 C00 책임이다.
