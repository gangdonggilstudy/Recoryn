# L04 재생 백엔드 독립 검토

2026-11-15, recoryn-desktop(w5:p3) 검토 / C00 작성·통합. 배정 L04, push L-P04. **최신 상태: REVIEW_READY / OPEN 1건(S2 L04-D04)**. 기존 D01·D02·D03·P01은 새 PCM snapshot에서 RECHECKED이며 최종 판정은 후단을 따른다. 아래 초기 WMF 검토와 OPEN 4건 기록은 이력으로 보존한다. NOT_RUN은 arch의 **L04-P01과 동일 발견**으로 중복 집계하지 않는다. 제품 전체 승인이 아니다.

## 교육·범위·동결 입력

AGENTS와 onboarding 순서의 설계 입력·통합 설계·workflow·배정표 L04·검증 계획·quality-system·제품 계약/현재 결과/과거 P0 결과·case-space·push-units를 재확인했다. 관련 product-ai-integration/product-desktop-audio 리뷰의 초기 OPEN과 후단 재확인을 구분했다. 추가 기준은 license-review D7, l04-media-backend-cases, license-results L-P04와 별도 재생 위치 결함이다. ONBOARDING_READY를 보고한 뒤 시작했다.

저장소 쓰기는 이 신규 문서뿐이다. 기존 staged/unstaged 변경을 보존했으며 제품·시험·설정·인덱스를 수정하지 않았다. 빌드·pytest·제품 UI 전체 실행·실음성 캡처·모델·다운로드·유료/실계정/실서비스·추가 위임·승인 UI 입력은 하지 않았다. 재생은 고유 TEMP의 합성 **무음 WAV**만 사용했고 매 QAudioOutput에 **setMuted(True), setVolume(0.0)**을 적용한 뒤 player에 연결하고 setSource했다. 실험 스크립트와 JSON도 TEMP에만 썼다.

과거 B21 작성 이력과 분리해 C00의 backend 전환·신규 smoke를 검토한다. 기존 UI 결함은 OPEN으로 재현할 뿐 자신의 과거 작성분을 최종 승인하지 않는다. 원본 불변·녹음/AI 분리·기본 무전송·Credential Manager 계약을 유지한다.

| 검토 snapshot | raw SHA-256 |
| --- | --- |
| packaging/rthook_media_backend.py | cde575a98f23bef4bbe9cc93d5c82db2a457f959fd48b9daef05dee6cedbfd8c |
| packaging/release_smoke.py | a869374ac2503cda61e1d659e1d7b60b41199009062e3c47e87ff7b304829aa7 |
| scripts/build_release.py | 7b28b74471b12ec1a7d7bf7cdcce9eded18b8063489c4e8fdc5425fd9c0b2b6d |
| src/recoryn/ui/ai_bridge.py | 3729dcfa48be282bedc1884c2ca4b17669ea8c29798f885dbf1431f347e4f809 |
| src/recoryn/ui/main.py | 952457b561732cb13b12002390944ee4bce3a50ee63b400b4040099666de11cd |
| src/recoryn/app/media.py | 25808336f6dafa3e555b780a1b64ed08ad37c5f718a15a17a9bda32c7fe7ba6d |
| src/recoryn/domain/__init__.py | d39b8f48e4f834656cbb204593c021f50cad4281e40ec7f96f9daa278cec6968 |
| docs/testing/l04-media-backend-cases.md | d6b97bcdbac6fa767cc058b924e5a09d2cb787c38d88296473d63baf96e4e24c |
| build/l04-1794733273/smoke.stdout.json | 8f81e94d5fa52883abc3cfd7dc37176b318e5f5c67a565bb00d9128f0453f533 |

후보는 `build/l04-1794733273/dist/Recoryn`이다. 제출 smoke JSON은 backend=windows, duration_ms=3000, position_ms=2593, LOADED_SEEKED_PLAYED_MUTED_SILENCE였다. 검토자는 EXE를 다시 실행하지 않았으며 제출 bytes/hash 확인과 .venv의 독립 Qt 실험을 구분한다.

## 제품 WAV 형식과 유한 실험

`app/media.py::_int16`은 s16le를 유지하고 s24le/s32le/f32le는16-bit signed PCM으로 변환한다. `prepare_clips.flush`의 WAV header는 **channels=format.channels, sample width=2, rate=format.sample_rate**다. 여기서 mono나16 kHz로 통일하지 않는다. `_checked_playback_path`는 derived WAV의 root/suffix/hash, 원본 chunk/range와 frame수를 검증한다. STT용 별도16 kHz mono 입력을 제품 재생 전체의 형식으로 간주할 수 없다. domain 허용 범위는 rate 1…768000, channels 1…64이며 확인한 재생 경로에는 mono/stereo 제한이 없다.

환경은 Windows / .venv Python 3.13.1 / Qt 6.12.0 / offscreen이다. backend마다 새 process에서 Qt import 전에 QT_MEDIA_BACKEND를 설정했다. Python socket connect/DNS audit을 거부했으며 native 전체 통신 관측이나 OS 무전송 증명은 하지 않았다. WAV는3초, payload 전 byte=0을 wave reader로도 확인했다. 구성 불가능 제외0, 16개 `(rate,channels)`가 유일하고 각 backend JSON의 실제16행과 대조했다.

| 대표 가족 | 독립 분모 | 실제 관측 |
| --- | --- | --- |
| 일반 format | {16000,44100,48000} × {1,2} = 6/backend | 양쪽6/6 LoadedMedia·NoError·hasAudio·3000ms, 로드 후2000ms seek 뒤350ms 기다리면 위치2000 초과 |
| 다채널 | 48000 Hz × {3,4,6,8,16,64} = 6/backend | WMF 3/4/6/8ch 진행,16ch 정지,64ch 로드 거부. FFmpeg는6행 로드·위치 진행.64ch rematrix 경고도 있어 음질/가청 출력 성공으로 해석하지 않음 |
| rate 경계 대표 | {1,8000,192000,768000} × mono = 4/backend | 양쪽4행 로드. WMF 1Hz는 짧은 대기 후 EndOfMedia, FFmpeg 1Hz는 위치 불진행. 극단 rate를 호환성 PASS로 처리하지 않음 |
| 로드 전 seek | 일반6 × backend2 = 12 | 전12행에서 LoadingMedia 중2000ms 지정이 유지되지 않고 약450ms 뒤1000ms 미만 |
| lifecycle | load 중 clear/play 중 clear/clear 후 재선택/이중stop × backend2 = 8 | clear3상태/backend는 NoMedia·StoppedState·empty source. 재선택은 로드 후 seek·진행 |
| generation callback | stale/fresh × backend2 = 4 | 실제 DesktopAI.seek/stop_playback callback으로 stale play=0, fresh play=1/backend |

16format×2backend=32행은 선언한 대표 집합이며 64×768000 전체 직적이나 모든 장치의 증명이 아니다. 로드와 진행을 별도로 기록했다. 기존 시험 수치와 합산하지 않는다. 추가16ch 반복은 새로운 format ID로 세지 않는다.

## L04-D01 / S2 / OPEN — 다채널 원본 형식을 유지한 재생 대상에서 WMF 진행 실패

**원 반례:** 48000 Hz,16ch,16-bit PCM,3초 완전 무음 WAV를 출력 연결 후 setSource하고 LoadedMedia를 기다린다. setPosition(1000)→play 후400ms마다4회 위치를 읽으면 WMF는 **[1000,1000,1000,1000], PlayingState, NoError**다. fresh player3반복 모두 같았다. 양성 대조8ch는 **[1324,1731,2144,2544]**로 진행했다. 같은16ch fixture의 FFmpeg는 최초 matrix에서2000→2341ms로 진행했다.64ch는 WMF **InvalidMedia / FormatError / Unsupported media, a codec is missing.**, FFmpeg LoadedMedia였다.

이는 무음이므로 가청 품질 차이 증명이 아니다. WMF16ch에서 앱에 보이는 진행이 멈추고64ch에서 로드가 실패한다는 좁은 차이다. 실제64ch 캡처나 FFmpeg64ch 정상 downmix까지 검증하지 않았다. C00이 공유한12~32ch 추가 관측과도 구분해, 본 검토자는16ch와64ch 원 반례만 직접 확인했다고 기록한다.

증거는 windows.json/ffmpeg.json/windows-recheck.json이다. derived가 채널 수를 보존하므로 D7의16-bit WAV 일반화에는 부족함이 있다. mono smoke는 이 결함을 잡지 못한다. 기존 _play에는 errorOccurred 표시 연결도 없어 진행 실패가 사용자에게 명확히 드러나지 않는다. 일반 mono/stereo 우회가 가능하므로 S2다.

재확인에는 지원 범위와 검증 bytes의 명시 변환·정확한 frame 대응이 필요하다. 원본을 변경하거나 STT 형식을 재생 전체 형식으로 가정해 닫지 않는다. 새 설계 재확인 전 OPEN이다.

## L04-D02 / S2 / OPEN — smoke가 실제 진행 없는 player를 통과시킴

`_playback_probe`는 LoadedMedia/NoError/hasAudio/3000±20ms를 확인한 뒤 setPosition(2000)→play→별도 loop600ms 대기, 마지막 **position>2000**만으로 seek와 진행을 성공 처리한다. load와 재생 loop를 나눈 점은 타당하지만 seek 직후 위치를 기준으로 진행량을 비교하지 않는다.

**원 반례:** 실제 Qt player의 메모리 내 subclass에 setPosition(v)는 실제 v+500 지정, play는 아무 동작 없음이라는 두 fault를 준다. 원 probe의 muted/volume0 출력·합성 무음은 그대로다. source/시험/config를 수정하지 않았다. 실제 player가 **StoppedState, position=2500**에 머무르는데도 실제 함수가 **LOADED_SEEKED_PLAYED_MUTED_SILENCE / duration=3000 / position=2500**을 반환했다.

실제 backend에서 이 두 fault가 함께 발생했다는 주장이 아니다. 목표인 정확한 seek 뒤 진행을, 잘못된 seek와 무재생으로도 통과할 수 있다는 독립 부정 대조다. import/수집 오류가 아니라 실제 함수의 성공 반환을 확인했다. oracle_fault.py/oracle-false-pass.json에 재현을 보존했다.

재확인은 seek 직후 정확한 위치/frame과 그 이후 독립 시점의 진행을 확인해야 한다. 절대 위치 초과, PlayingState 또는 새 sink에 bytes를 쓰기만 한 사실을 진행으로 대체하지 않는다. 새 oracle 재확인 전 OPEN이다.

## L04-P01 / S2 / OPEN — NOT_RUN이 필수 playback 게이트를 막지 않음

arch의 L04-P01과 동일 발견이다. `QMediaDevices.audioOutputs()`를 빈 집합으로 patch하고 실제 probe를 호출하면 **backend=windows, status=NO_AUDIO_OUTPUT_DEVICE_NOT_RUN**이다. probe가 NOT_RUN을 명시하는 부분 자체는 타당하다.

그러나 `release_smoke.run()` 반환은 playback 내용과 무관하게 최상위 **status:PASS**이며 scripts/build_release.py:223 이후는 최상위 status만 검사한다. 따라서 필수 frozen playback을 실행하지 못한 후보도 상위 smoke 성공 조건을 만족한다. 이 연결은 코드 읽기로 확인했으며 검토자가 빌드나 smoke.run 전체를 실행한 것은 아니다.

기존 후보는 실제2593ms로 진행했으므로 그 후보가 무장치였다고 주장하지 않는다. 향후 무장치 환경에서도 게이트가 통과하는 문제다. NOT_RUN은 보존하되 필수 게이트의 PASS/공개 허가로 승격되지 않아야 한다. 새 후보 재확인 전 OPEN이다.

## L04-D03 / S2 / OPEN — 기존 로드 전 seek 결함은 두 backend 공통

license-results의 별도 결함을 독립 재현했다. `DesktopAI._play`는 출력 연결 후 setSource→setPosition→play를 즉시 호출한다. 일반6format 전부 setSource 직후 LoadingMedia였다.

2000ms 지정 후 약450ms 뒤 위치는 WMF **[330,335,375,333,379,331]**, FFmpeg **[384,384,371,371,426,426]**다. 전부2000ms 뒤가 아닌0 부근에서 진행했다. 같은 fixture를 LoadedMedia 뒤 seek하면 일반6format 모두2000ms로 지정되고 이후 진행했다.

WMF 전환 고유 결함이 아니라 근거 위치 대신 clip 처음이 재생될 수 있는 기존 S2다. 후보 smoke는 로드 완료 후 seek하므로 기존 제품의 잘못된 순서를 검증하지 않는다. 새 PCM 경로에서도 요청 frame에서 시작했다는 증거와 원 반례 재확인이 필요하다. 설계 변경만으로 닫지 않는다.

## stop·재선택·세대 보호

실제 player에 DesktopAI.stop_playback을 unbound 호출했다. generation 증가와 stop→setSource(QUrl()) 후 양쪽 backend가 NoMedia/StoppedState/empty source로 정리됐다. load 중·play 중·이중stop 대기 뒤 이전 source 부활은 없었다. clear 후 다른 rate/channel의 무음 source도 로드 후 seek·진행했다.

실제 DesktopAI.seek의 완료 callback을 보류하고 stop_playback으로 세대를 바꾼 뒤 완료하면 play spy=0이었다. 같은 세대의 fresh callback은1회였다. operation/library만 fake로 사용해 장치와 UI 전체를 초기화하지 않았다. 이 유한 절차에서는 WMF 고유 stop/clear 회귀를 찾지 못했으나 임의 callback 순서 전수 증명은 아니다.

코드상 selection()은 panel.load만 하고 세대를 바꾸지 않는다. 삭제 전과 window close는 stop_playback을 호출한다. 따라서 모든 선택 변경이 세대를 무효화한다고 주장하지 않는다. 재선택 실험은 명시 stop/clear 후 다른 source 선택이며, 선택만으로 안전하다는 승인으로 확대하지 않는다.

## 증거와 재현

증거 root는 `C:\Users\gangd\AppData\Local\Temp\recoryn-l04-playback-review-68ae2c977da04b8883c6334cdc456419`다. 기존 build/원본 WAV를 수정하지 않았다. ResourceWarning-error로 실행했고 pytest/cacheprovider는 실행하지 않았다.

```powershell
$l04ReviewEvidence = 'C:\Users\gangd\AppData\Local\Temp\recoryn-l04-playback-review-68ae2c977da04b8883c6334cdc456419'
$env:PYTHONDONTWRITEBYTECODE = '1'
.venv/Scripts/python.exe -W error::ResourceWarning "$l04ReviewEvidence/probe.py" $l04ReviewEvidence windows
.venv/Scripts/python.exe -W error::ResourceWarning "$l04ReviewEvidence/probe.py" $l04ReviewEvidence ffmpeg
.venv/Scripts/python.exe -W error::ResourceWarning "$l04ReviewEvidence/recheck.py" $l04ReviewEvidence
.venv/Scripts/python.exe -W error::ResourceWarning "$l04ReviewEvidence/oracle_fault.py" $l04ReviewEvidence
```

probe.py는 import 전 backend 설정·무음 생성·출력 mute/volume0·로드 후 seek/play·로드 전 seek·stop/clear/재선택·세대 callback과 실제 probe 양성/무장치 대조를 포함한다. 네 명령 모두 exit0이지만 이는 모든 format 통과가 아니라 실패 상태까지 JSON으로 관측했다는 뜻이다. 재실행은 증거를 덮어쓰지 말고 scripts를 새 TEMP에 복사해 수행한다. 각 process의 audioOutputs는1개였고 청취·음질 확인은0회다.

| 증거 root 상대 파일 | raw SHA-256 |
| --- | --- |
| probe.py | 083c34abe7485767d0ec540d99d0c2029d7936a5270e6b03aec79545d6f15714 |
| windows.json | 6e647368bde4928d5174a43594a51c9c379086fa06adf4b70baff30c702b4bc6 |
| ffmpeg.json | 279d7347460ea216e155fc9968653aa529f03085a3f790478565046ec8da22ce |
| recheck.py | 4bf2d100340911b9a2d6e5ae129bfda332b57d54333f71c5afbbf5ae95d0ce9e |
| windows-recheck.json | 160b6b0ba5f20701d9cdb5cb165f9c39bd22beb27f4b6641775c2d5391195a53 |
| oracle_fault.py | b1c1729ce376224701ac5c5f546d6a252cd6a74d7af375223585e23c13284ab3 |
| oracle-false-pass.json | 32e00099479d618bbdf5a7aef3dd6658e0fcbb4d24967ffadeb6594c66e71671 |
| review-input-hashes.json | 7af4b78faffd1565b7be26b2e3b927157a2111fe6333c2b0b5c5ddccfc119652 |

## 설계 변경 수신과 최종 상태

C00은 WMF 다채널·진행 oracle·NOT_RUN 발견을 타당하다고 수신하고 추가 탐색을 중단해 원 후보 검토를 마감하라고 지시했다. 새 계획은 검증 bytes를 정확한 frame부터 QAudioSink로 전달하고3ch 이상 mono 평균, windowsmediaplugin 제외, rthook_media_backend.py 삭제다. 위 hash는 이 변경 **전** snapshot의 근거로 보존한다. 원 반례를 완화하거나 새 설계를 추정 PASS로 바꾸지 않는다.

새 source/hash/후보에 대한 같은 검토자의 재확인을 기다린다. 실제 음성·음질·장치 전환·장시간·N/KN·clean VM·native 전체 통신 관측·모델·G3/G4·법률 승인은 NOT_RUN/별도 게이트다.

**REVIEW_READY / OPEN 4건(S2 4: L04-D01·D02·D03 및 arch와 동일한 L04-P01). D03은 기존 제품 결함이다. 수정·재확인·최종 CLOSED 및 Git/CI는 C00이 통합한다.**

## PCM/QAudioSink 변경 재확인 — 기존 4건 RECHECKED, 신규 D04 OPEN

동일 검토자의 C00 명시 재배정이다. AGENTS·L04 변경 배정과 새 case 문서·license-results를 다시 읽고 ONBOARDING_READY를 보고했다. 쓰기는 이 문서 후단뿐이고 앞선 원 반례를 완화하거나 삭제하지 않았다. 실제 무음 재생은 QAudioSink의 volume=0.0과 readback 확인으로 수행했다. QAudioOutput을 쓰지 않는 새 경로에 이전 API의 setMuted를 호출한 것처럼 기록하지 않는다. 비무음 수치 fixture는 fake 경계에만 사용했다.

### 재확인 입력과 후보 연결

| 대상 | raw SHA-256 |
| --- | --- |
| src/recoryn/ui/pcm_playback.py | d0a5703132ecd4bf45cb7e35a816a9e9b0aa5ad0504af5f6b3e928d06d404885 |
| src/recoryn/ui/ai_bridge.py | 6dcaffe44ef6545c9b9f8140e0954fd2241fb9c23a4bf26e9a5fc962866c4998 |
| tests/unit/test_pcm_playback.py | 5336629e8a84f03fb0848881e04939bdd198e12bf7b73abb86ec119569276715 |
| tests/ui/test_live_ui.py | e106e2cac66fce9ab910012af4e363ec4236cd916704d52f2a3f05fe2852bcd0 |
| packaging/release_smoke.py | 8df877038951028594a0b0f429daa3e6773e1a5844db55fb705c2ce56e29c7fc |
| tests/release/test_smoke.py | bbe77100e3f8e7a64d238fea4354659a35c9dc0b507da67ca96084f8c3cf9661 |
| scripts/build_release.py | 2b1adc6719bd0819019f2b4d8daf15b49f28223a3b30ade62b8dd6d5847c1ace |
| docs/testing/l04-media-backend-cases.md | 710ee5c9c332df251b29d341e986c0cecab075f5e31c5e1c111d87d7cffdfc18 |
| build/l04b-1794734467/smoke.stdout.json | 35303b351394c9adee27bd975bbf0386ff2559277caaa03d5b69096bdc9ec55f |

제출 hash가 모두 일치했다. 새 후보 inputs의 pcm_playback/ai_bridge/release_smoke bytes도 위 세 hash와 일치했다. 후보 smoke는 PASS, 12입력 채널, start_frame=32000, positions=2208/2658이었다. 검토자는 EXE/빌드를 다시 실행하지 않았고, 미디어 플러그인0 전수 검토는 별도 arch 검토와 구분한다. C00의 전체7532 PASS도 작성자 보고이며 아래 독립 실행과 합산하지 않는다.

### 독립 분모·수치·거부·lease

별도 TEMP driver가 채널 {1…64} × rate {8000,44100,48000} × position {-1,0,1,10000}의 **64×3×4=768행**을 실행했다. 64frame마다 채널별 값이 다른 결정적 signed16 입력을 만들고, C≤2는 원 byte 꼬리, C>2는 `round(Fraction(frame합,채널수))`로 기대값을 계산했다. 제품 mix/recoryn.audio 도우미를 oracle로 import하지 않았다. 실제768 ID와 별도 기대 집합을 대조해 유일768·누락0·중복0이었다. 음수와 끝 초과는 제거하지 않고 clamp 결과를 확인했다. 이것은 유한 대표 가족이며 모든 rate·임의 긴 입력의 증명은 아니다.

추가 거부11행은 hash 불일치, 폭1/3/4, 비RIFF, 잘린 data, 채널65/0, rate0, IEEE float, 정확한 파일 상한+1 byte다. 모두 PLAYBACK_SOURCE_INVALID였다. 상한−1 및 정확한 상한은 수락했다. 양·음0.5/1.5 ties-to-even 손계산4행도 일치했다. 모든 수치 행에서 TEMP 원본 WAV bytes 불변을 확인했다.

실제 DesktopAI._verify_playback을 fake JobStore 경계와 연결해 `reader_start → prepare → complete → reader_finish`를 관측했다. prepare 직전 reader active를 assert했고 위치333ms/44100Hz는 frame14685였다. path 검사 뒤 TEMP 파일을 다른 내용으로 바꾸는 반례에서는 이전 digest로 prepare가 거부하고 `reader_start → fail → reader_finish`가 됐다. 종료 뒤 lease는 해제됐다. `_checked_playback_path`의 기존 chunk 검증 자체를 대체 승인한 것은 아니며, 새 prepare 호출이 lease 안에 놓이고 hash가 재확인되는 순서를 독립 확인한 것이다.

### 기존 발견 재확인

| 발견 | 원 반례를 새 경로에 적용한 결과 | 판정 |
| --- | --- | --- |
| L04-D01 다채널 | 아래 실제 무음 5형식에서 정확한 frame 절단·mono 출력·진행. 16/64채널 원 반례를 새 prepare/SinkPlayback에 적용 | RECHECKED |
| L04-D02 잘못된 위치+무재생 거짓 통과 | 원 fault의 p1=p2=2500을 progress_ok가 False로 판정. 실제 SinkPlayback에 fake QAudioSink processedUSecs=500000 고정을 적용하고 실제 probe를 호출하면 PLAYBACK_SINK_DID_NOT_ADVANCE로 거부 | RECHECKED |
| L04-D03 로드 전 seek | 새 경로에는 setSource/setPosition 비동기 순서가 없다. 비무음768행의 정확한 frame/byte 꼬리, bridge 위치 전달과 실제 sink 시작 frame을 확인 | RECHECKED |
| L04-P01 NOT_RUN | 실제 무장치 probe 결과는 NOT_RUN, overall_status는 PLAYBACK_NOT_VERIFIED. 별도 빌더 판정에서 top 미검증·위장PASS+NOT_RUN·playback누락·비dict·과거성공문자열의5거부와 정상1수락을 확인 | RECHECKED, arch와 동일 건 |

fault 재현은 새 source를 변조하지 않고 QAudioSink를 메모리 fake로 바꿔 수행했다. 실제 PCM 준비와 SinkPlayback.position_ms, 실제 probe를 지나 동일2500 위치를 반환했으므로 progress_ok 테이블만 다시 계산한 결과가 아니다. 정확한 시작 기준·실제 delta·상한을 같이 확인하는 새 oracle는 원 fault를 검출한다.

### 실제 무음 sink와 수명 경계

| rate / 입력 채널 / 길이 / 요청 위치 | 시작 frame / 출력 | 관측 p1 / p2(ms) |
| --- | --- | --- |
| 16000 / 12 / 3초 / 2000ms | 32000 / mono | 2208 / 2658 |
| 16000 / 16 / 3초 / 2000ms | 32000 / mono | 2210 / 2660 |
| 16000 / 64 / 3초 / 2000ms | 32000 / mono | 2210 / 2660 |
| 48000 / 16 / 3초 / 2000ms | 96000 / mono | 2206 / 2666 |
| 48000 / 64 / 1초 / 250ms | 12000 / mono | 446 / 896 |

64채널/48kHz는 제품 상한 안의1초 fixture로 실행했다. 전5행에서 payload 전부 무음, 원 파일 불변, sink volume0, 마지막까지 active와200ms 이상 진행을 확인했다. 실제 새 production probe도 별도 호출해 start_frame32000, 12채널, positions2198/2648로 통과했다. 이는 .venv 관측이며 저장된 frozen 후보의 관측과 구분한다.

0.1초 무음 입력의 실제 Idle 종료에서 sink/buffer 참조 해제, buffer 닫힘 또는 Qt 객체 삭제, position=None, active=False를 확인했다. 첫 driver는 이미 Qt가 삭제한 QBuffer의 isOpen()을 읽어 RuntimeError로 끝났다. 이는 검토 하네스 오류이며 제품 실패로 세지 않았다. shiboken6.isValid를 먼저 검사하도록 TEMP driver만 고친 실행이 위 최종 증거다. 중복 실행을 새 case로 합산하지 않는다.

fake 경계8개에서 정확한 buffer/format/position, 교체 시 기존 sink stop, 퇴역 sink의 늦은 Idle 무시, 현재 Idle 해제, 반복 stop, 무장치·미지원형식·시작오류의 실제 DesktopAI 상태 표시를 확인했다. 시작 시 오류3종은 안전한 코드로 표시하고 자원을 해제했다. 실제 seek 완료 callback의 세대가 stop으로 무효화되면 play0, 같은 세대의 fresh callback은 play1이었다. 세션 selection만으로 세대를 바꾸지 않는 기존 관측은 그대로이며 임의 경쟁 순서를 전수 검증했다고 하지 않는다.

### L04-D04 / S2 / OPEN — 시작 뒤 비동기 sink 오류가 표시·정리되지 않음

**새 원 반례:** 위 d0a570/6dcaffe snapshot의 실제 DesktopAI._play→SinkPlayback.start는 정상 성공하게 한다. 그 뒤 현재 sink의 상태를 **StoppedState**, 오류를 **IOError**로 바꾸고 stateChanged를 emit한다. 실제 `_state_changed`를 거치지만 상태 표시 호출은 **messages=[]**, sink 참조 유지=True, buffer 열린 상태=True, sink delete=False, active=False다. Idle이 아닌 비동기 오류에는 아무 처리도 없다. 수동 stop을 호출하면 해제된다.

기존8개 수명 대조의 정상 Idle·퇴역 신호·시작 오류는 통과하므로 이 반례는 시작 오류를 섞어 만든 실패가 아니다. actual Qt 장치를 분리한 실험은 하지 않았으며, 시작 후 발생 가능한 오류 event의 처리를 결정적으로 검증한 fake 경계다. 녹음/원본 저장에는 영향을 주지 않지만 재생이 중단됐음을 사용자에게 알리지 않고 자원도 남겨 S2로 판정한다.

원인은 `_state_changed`가 현재 sink의 IdleState만 처리하고, 시작 뒤 error 상태를 확인하거나 DesktopAI에 전달하지 않는 점이다. 수정 시 현재 sink 오류의 안전한 코드 표시와 자원 해제, 기존 sink의 늦은 오류가 새 sink/UI에 영향을 주지 않는지 재확인이 필요하다. 검토자는 제품을 수정하지 않고 C00에 원 반례를 보고했다. 원본 저장/reader/fence 실패와 혼동하지 않는다.

### 시험 oracle 검토와 제한

새 unit 시험은 정확한 Fraction 평균을 주 oracle로 유지하고, 기존 float 도우미와의1LSB 허용은 **정확한 .5 동률 frame에만** 한정한다. 이 허용이 정확한 기대 PCM 자체의 오차를 허용하지는 않는다. hand cases·크기/형식/hash 거부·수명/error 대조와 smoke의 실패 경계를 읽었다. UI 시험은 실제 재생 PCM(rate/channels/payload/start_frame)을 assert하고 파생 파일 변조와 원본 chunk 변조 시 호출 수가 늘지 않는 부정 assertion을 유지한다. 현재 읽은 assertion에서 약화를 발견하지 않았다.

이전 L-P03 TEMP의 test_live_ui.py를 직접 비교하려 했지만 PermissionError로 읽지 못했다. 권한 실패는 제품/시험 실패가 아니며, 따라서 이전 시험 전체 diff가 기대값 변경뿐이라는 작성자 주장을 독립적으로 bytes 대조했다고는 하지 않는다. C00이 해당 diff를 통합 시 확인해야 한다. 현재 시험에 시작 후 비동기 sink 오류 대조가 빠진 것은 D04로 남긴다.

### 재확인 증거·최종 상태

증거 root: `C:\Users\gangd\AppData\Local\Temp\recoryn-l04b-playback-review-285fa43125d54328af7dc0869e3efa8a`.

```powershell
$l04bReviewEvidence = 'C:\Users\gangd\AppData\Local\Temp\recoryn-l04b-playback-review-285fa43125d54328af7dc0869e3efa8a'
$env:PYTHONDONTWRITEBYTECODE = '1'
.venv/Scripts/python.exe -W error::ResourceWarning "$l04bReviewEvidence/independent.py" $l04bReviewEvidence
.venv/Scripts/python.exe -W error::ResourceWarning "$l04bReviewEvidence/real_sink.py" $l04bReviewEvidence
```

두 최종 명령은 exit0이며 pytest node 수가 아니다. independent driver는 D04를 관측한 JSON을 남기므로 exit0을 D04의 PASS로 해석하지 않는다. 재실행은 새 TEMP를 사용한다. 실험 전후 source/test/config8개 hash 및 인덱스 hash는 동일했다. 실제 sink 실행의 source hash도 d0a570이었다. 이후 C00 수정은 이 검토 snapshot과 별도로 재동결해야 한다.

| 증거 파일 | raw SHA-256 |
| --- | --- |
| independent.py | 47da6413ecac08420c839e9558cbf6dfacc0fd6dd8191045b43db043489410ca |
| independent.json | d6756d25f6c55ac52116f4c2e843a58704dfbf6d36c5032a52bfa81b99311a18 |
| real_sink.py | 49305f837e1bb6e3db210b82be0d94dae2d4807f8068f662158a711c6fca33b0 |
| real-sink.json | 08adb1c393c921a7df05fc6440a3d106bf72a3ca139a31664ec69f0912d86a44 |

**REVIEW_READY / 기존 D01·D02·D03·P01 RECHECKED / 최신 OPEN 1건(S2 L04-D04)**. C00의 수정과 같은 검토자의 D04 재확인을 기다린다. 실음성·청취 품질·장치 전환·장시간·clean VM·모델·G3/G4는 NOT_RUN이며, 전체7532 PASS나 후보 smoke로 이 새 OPEN을 상쇄하지 않는다. 최종 CLOSED·통합·Git·CI는 C00 책임이다.

## L04-D04 수정 재확인 — RECHECKED / 최신 OPEN 0

C00 명시 재배정으로 동일 검토자가 원 반례를 다시 실행했다. 앞선 OPEN·원 반례·초기 후보 기록은 이력으로 보존하며 **이 절이 최신 판정**이다. ONBOARDING_READY 뒤 허용된 리뷰 후단만 추가했다. 제품·시험·설정·인덱스 수정, Git 명령, 빌드·pytest·제품 UI 전체 실행, 실음성·모델·네트워크 서비스·유료 호출·추가 위임은 하지 않았다. 실제 sink는 합성 무음·volume0으로만 실행했다.

### 입력 동결

| 대상 | raw SHA-256 |
| --- | --- |
| src/recoryn/ui/pcm_playback.py | 7de15a2027036f8d6da62c8344ecb9b5d946379a72aeae66a3985bd2982432f0 |
| src/recoryn/ui/ai_bridge.py | 9b6dd9e32d7eb9f96cf514d30fb486976ad90e8fb2086ec0f99455140ed5044b |
| tests/unit/test_pcm_playback.py | 1bbf7cb6a1c93838ccbc48807feb6d8c5f1c1945ca8d35e2d155b00ba0d5a963 |
| docs/testing/l04-media-backend-cases.md | b5180f2511d538cb32add30aab0e4e8088f20b92f6ef3aeb21179411eae0531b |
| packaging/release_smoke.py | 8df877038951028594a0b0f429daa3e6773e1a5844db55fb705c2ce56e29c7fc |
| tests/ui/test_live_ui.py | e106e2cac66fce9ab910012af4e363ec4236cd916704d52f2a3f05fe2852bcd0 |
| tests/release/test_smoke.py | bbe77100e3f8e7a64d238fea4354659a35c9dc0b507da67ca96084f8c3cf9661 |

요청한 새4개·유지3개 hash가 일치했고 독립 실행 전후도 동일했다. 인덱스 raw hash도 실행 전후 같았다. C00의 관련275 PASS는 작성자 보고이며 독립 driver 결과와 합산하지 않는다. 기존 build/l04b-1794734467은 D04 수정 전 코드이므로 이 절의 수정 후 artifact 증거로 재사용하지 않는다.

### 원 D04 반례와 회귀 대조

실제 DesktopAI._play → SinkPlayback.start 경로에 정상 시작 후 **현재 sink의 StoppedState/IOError stateChanged**를 주입했다. 새 코드에서는 실제 `_report_playback`이 **“재생할 수 없습니다: PLAYBACK_OUTPUT_FAILED · 원본은 보존됩니다.”**를 정확히1회 표시했다. sink.stop1회·delete=True, buffer 닫힘, sink/buffer 참조=None, position=None, active=False였다. 같은 퇴역 sink에서 다시 Stopped/IOError 또는 Idle 신호를 보내도 표시 횟수는 늘지 않았다. 이전 원 반례의 messages=[]·열린 buffer·sink 참조 보유가 모두 해소됐다.

독립 유한 대조는 **현재/퇴역2 × Idle/Stopped2 × NoError/IOError2 = 8행**이다. 실제 유일 ID8개를 별도 기대 집합과 대조해 누락0·중복0이었다. 모든 행을 구성했고 거부 입력을 제외하지 않았다.

| 조건 | 기대/실제 |
| --- | --- |
| 현재 Idle, 오류 유무2행 | sink/buffer 해제, 보고 없음(자연 소진 정책) |
| 현재 Stopped/NoError | 해제, 오류 보고 없음 |
| 현재 Stopped/IOError | 해제, PLAYBACK_OUTPUT_FAILED1회 |
| 퇴역 sink의 Idle/Stopped × 오류 유무4행 | 새 sink/buffer/active 유지, 새 오류 표시 없음 |

자기 stop은 참조를 먼저 None으로 바꾸므로 동기 Stopped 신호를 재처리하지 않았다. 명시 stop→재선택→이전 sink 늦은 오류, 반복 stop에서도 거짓 오류 표시가 없었다. DesktopAI.stop_playback의 세대 증가도 유지됐다.

출력 장치 없음·미지원 형식·시작 직후 오류3행은 실제 DesktopAI 경로에서 각각 PLAYBACK_OUTPUT_UNAVAILABLE / PLAYBACK_FORMAT_UNSUPPORTED / PLAYBACK_OUTPUT_FAILED를1회 표시하고 참조를 해제했다. 새 unit 시험의 D04 오류 있음/없음 및 실제 DesktopAI 경로3행은 원 반례를 그대로 유지하며, 읽은 코드에서 oracle 완화를 발견하지 않았다.

실제 Qt sink에서는16kHz mono 0.1초 무음을 volume0으로 시작해650ms 뒤 자연 종료를 관측했다. 오류 callback=[], sink/buffer 참조 해제, buffer 삭제 또는 닫힘, position=None, active=False였다. 이어 실제16kHz 무음의 명시 stop,48kHz 무음 재선택·자연 종료, 반복 stop도 거짓 오류를 표시하지 않았다. 장치 분리·물리 I/O 실패를 실제 발생시킨 검증은 아니며 fake 오류 대조와 구분한다.

### 증거와 통합 조건

증거 root는 `C:\Users\gangd\AppData\Local\Temp\recoryn-l04-d04-recheck-463e3dc835e642d49e74b62b9337bffe`다. `.venv/Scripts/python.exe -W error::ResourceWarning <새 TEMP>/recheck.py <새 TEMP>`로 실행해 exit0을 확인했다. driver가 offscreen을 설정하고 Qt 출력은 무음·volume0만 사용했다. pytest case 수나 이전 전체 회귀와 더하지 않는다. 재실행은 새 TEMP를 사용한다.

| 증거 | raw SHA-256 |
| --- | --- |
| recheck.py | 26bd2961c9e3f65f296b194a671f3f44828b8b049659a439890f0661b86b3e0d |
| result.json | ff8ffee737cba2e60bf08f61a510825e4299b5a93a54c11cc488598e7c2dbaa2 |

이전 test_live_ui snapshot의 권한 제한은 그대로 이력으로 남긴다. C00은 git diff HEAD로 첫 성공 assertion1곳 강화·변조 거부2행 불변을 보충 확인했다고 보고했다. 이는 C00의 Git diff 보완 근거이며 본 검토자가 읽기 불가 snapshot을 직접 비교했다고 바꾸지 않는다.

**L04-D04 RECHECKED / 기존 D01·D02·D03·P01 RECHECKED 유지 / REVIEW_READY / 최신 OPEN 0건(S0·S1·S2·S3 모두0)**. 임의 callback 순서·청취 품질·장치 전환·장시간·clean VM·G3/G4를 전수 통과로 확대하지 않는다. 최종 CLOSED, 수정 코드와 일치하는 artifact 재생성·정확한 통합 tree 검증·Git·CI는 C00 책임이다.
