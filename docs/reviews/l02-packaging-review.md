# L02 패키징 독립 검토

2026-11-15 / 작성 C00, 검토 recoryn-arch(w5:p2) / L-P02.

**REVIEW_READY — 현재 OPEN 0 (S0 0 / S1 0 / S2 0 / S3 0). L02-P01~P03은 작성자 수정 후 원 반례로 RECHECKED, 최종 CLOSED·통합 수락은 C00 책임이다.** 최초 발견·원 증거는 아래 보존한다. 과거 B23 작성 이력과 구분해 이번 C00 변경을 독립 검토했으며 제품 전체·라이선스 법률 판단·공식 릴리스를 승인하지 않는다.

## 범위와 교육

AGENTS/onboarding 순서의 설계 입력·통합 설계, workflow/최신 L 배정, 관련 릴리스·라이선스 리뷰/validation-plan, quality-system, 제품 계약/현재 증거/과거 P0 결과, case-space/push-units를 재확인했다. ONBOARDING_READY 뒤 지정 diff와 실제 파일을 읽었다. 쓰기는 이 문서뿐이며 대상 제품·시험·설정·Git/인덱스는 수정하지 않았다. 다른 worker 및 C00의 기존 변경을 보존했다. 인덱스 hash 관측창은 사용하지 않았다.

대상은 release_manager/spec/no-av hook/release_smoke/build_release, 지정 release 시험 추가분과 l02-stt-input-cases의 P 절이다. release_evidence/notices 및 L-P03 전용 변경은 독립 승인 범위 밖이다. source build_release/test_build_inputs에 공존하는 L-P03 변경을 L-P02 commit 검증으로 간주하지 않는다. C00이 정확한 L-P02 blob을 구성하고 별도 검증해야 한다.

## 최초 발견과 원 반례

| ID / 심각도 | 원 반례·실제 결과 | 수정 제안 |
| --- | --- | --- |
| L02-P01 / S2 | `_internal/vendor/av.libs/avcodec-62.dll`, `vendor/av/__init__.pyc`, `vendor/av-16.1.0.dist-info/METADATA`가 공유 정책 None, 정합 manifest의 verify ACCEPTED. 대소문자/양 구분자에서도 동일. 최상위 prefix만 검사해 spec·verify·smoke에 공통 누락. | 모든 디렉터리 구성요소에서 정확한 av/av.libs/dist-info 정책 적용; avatar/av-tools 등 구별. |
| L02-P02 / S2 | `_internal/nvidia/nvJitLink_120_0.dll`, `cusparse64_12.dll`이 verify ACCEPTED. D3의 NVIDIA runtime 제외가 최초 네 prefix만으로 제한됨. | 필요한 CUDA/cuDNN/TensorRT basename 종류 확대 및 독립 거부/유사이름 표. |
| L02-P03 / S2 | hook-added TOC의 목적 `vendor/avcodec-62.dll`, source `.../site-packages/av.libs/avcodec-62.dll`이 GUI/CLI 양쪽 COLLECT에 잔존. 목적지만 검사해 금지 출처의 flatten을 놓침. 실제 설치된 해시 포함 avcodec DLL의 존재도 별도 확인. | 출처 문자열과 목적지 모두 검사하고 기록 TOC도 빌더에서 재확인. UNC stat/probe 이전 문자열 판단, Qt FFmpeg 유지. |

최초 P01/P02의 합성 실제 manifest5개와 관측은 TEMP `recoryn-l02-policy-audit-u_4_sfll/evidence.json`에 보존했다. P03 최초 fake Analysis/COLLECT 관측은 `recoryn-l02-source-policy-2zuhnjdg/evidence.json`이다. 이 최초 TOC source는 합성 경로였고, 실제 파일 존재·실제 해시 포함 경로의 차단은 후단에서 검증했다. 후보에 실제 금지 구성요소가 있었다는 발견으로 혼동하지 않는다.

## 수정 후 재확인

P01은 디렉터리마다 av/av.libs 및 av-*.dist-info를 검사하도록 변경됐다. P02는 nvjitlink/cusparse/cufft/curand/cusolver/cupti/nvtoolsext/nvinfer/nvonnxparser/nvblas/nppc/nppi/npps를 추가했다. 최초 정합 manifest5개를 원 파일 그대로 새 verify에 전달하니 모두 LICENSE_EXCLUDED_COMPONENT로 거부됐다. NVIDIA13 대표와 avatar/av-tools/curses 허용3행도 독립 확인했다. 증거: TEMP `recoryn-l02-refusal-recheck-p1ogcy0t/evidence.json`.

원 정책 표를 구현 상수에서 import하지 않고 손으로 고정했다. 금지18개와 허용9개에 위치(루트/_internal/_internal/vendor), 구분자2, case2를 교차했다. 원 syntactic 금지216행은 basename-only 루트의 separator 변형이 같은 문자열이어서 고유 경로 분모가186이다: 패키지 경로3×12 + basename15×10. 허용은 패키지 경로2×12 + basename7×10 =94다. 단순 실행 개수216을 고유 coverage로 부풀리지 않았다. 독립 set와 이 산식을 대조한 실제 금지186/허용94에서 수정 후 누락0/오제외0이었다. 이는 고정 대표 이름 공간이며 임의 이름·모든 NVIDIA 바이너리의 전수 분류 증명이 아니다. 증거: TEMP `recoryn-l02-spec-audit-i_eb_x0j/evidence.json`.

P03 수정의 `excluded_source`는 site-packages 아래 상대 경로에 공유 정책을 적용하며 그 밖은 basename만 검사한다. 프로필 이름 `av` 때문에 정상 파일을 오제외하지 않는다. 실제 `.venv/Lib/site-packages/av.libs/avcodec-62-0796e49249259295c31f1add9f446a07.dll` source를 목적 `vendor/avcodec-62.dll`로 넣어 GUI/CLI에서 모두 제거됨을 확인했다. Qt `PySide6/avcodec-63.dll` source와 `C:/Users/av/README`는 양쪽에 유지됐다. 빌더의 `excluded_toc_rows`도 같은 원 source를 거부 목록에 올렸다. Path.stat을 예외로 막은 상태에서 UNC 문자열의 금지 source 판정이 성공해 probe0을 확인했다. 출처의 임의 rename/비표준 위치를 hash로 식별하는 분류기는 아니다. 증거: TEMP `recoryn-l02-source-recheck-apsx8czx/evidence.json`.

세 건 모두 **RECHECKED / CLOSED 후보**다. C00이 최초 발견을 타당하다고 수신하고 수정했으며, 검토자가 대상 코드를 직접 고치지 않았다.

## spec·stub·PATH·closure 판정

- GUI/CLI Analysis 후 필터가 hook이 추가한 binaries/datas의 목적지·출처에 적용된다. weights 후단 거부도 유지됐다. 빌더가 기록 TOC를 재확인하고 최종 verify와 frozen smoke가 파일 정책을 재검사한다. pure Python의 av 제외는 Analysis excludes와 graph에 의존하며 native/data 검사만으로 모든 PYZ 모듈을 검증한다고 주장하지 않는다.
- av stub은 import만 충족하며 `hasattr(av, "open")`은 False, `__path__`는 없고 실제 av.open 사용은 RECORYN_PYAV_NOT_BUNDLED AttributeError, 하위 import는 ImportError다. 기존 모듈은 바꾸지 않고 frozen smoke가 진짜 av 또는 hook 누락을 거부한다. 실제 frozen spawn child에서 stub·faster-whisper import와 무모델 배열 디코딩을 확인했다. 기존 av를 외부에서 악의적으로 위조하는 같은 사용자 프로세스 공격까지 방어하는 보장은 아니다.
- av pin 제거는 frozen 재배포 범위와 맞고 개발 환경의 av 제거를 주장하지 않는다. 실제 faster-whisper의 av 사용은 decode 함수에 있으며 Recoryn의 ndarray 경로를 별도 STT 검토와 연결한다. 모델/weights를 요청하지 않았다.
- isolated_path는 venv Scripts/base Python/DLLs와 Windows/System32만 남긴다. 현재 PyInstaller는 지정 interpreter로 실행되고 UPX도 꺼져 있어 Git 등 host tool은 필요하지 않다. 기존 성공 후보가 이 격리 PATH의 실행 가능성을 보여준다. 미래 외부 빌드 도구·GPU 구성까지 지원한다고 주장하지 않는다. 첫 빌드의 Git OpenSSL/hardlink 실패는 이 후보의 제품 실패로 합산하지 않는다.
- native_import_closure는 일반 PE IMPORT 이름의 bundle basename 또는 현재 System32 존재 및 API-set prefix를 확인한다. loader 검색 경로, export symbol/ABI/architecture, delay import·동적 LoadLibrary, 모든 OS 버전의 실행 가능성을 증명하지 않는다. 이번 후보의112 native에 별도 delay-import 검사도 수행해3개/미해결0을 확인했다. 동적 API·미사용 기능·GPU는 여전히 미검증이다.

## 직접 실행과 실제 후보

최초 지정 세 파일은91 PASS였다. 수정 도중111 PASS, 최종 workspace 세 파일113 PASS도 실행했으나 이 숫자에는 L-P03 notice snapshot node1개가 있다. L-P02 판정용으로 이를 명시 제외해 **112 PASS / 1 deselected / 2.11s**를 별도로 확인했다. C00의 전체 release147 PASS를 독립 실행한 것으로 주장하지 않는다.

```text
.venv/Scripts/python.exe -m pytest tests/release/test_release.py tests/release/test_spec.py tests/release/test_build_inputs.py -k "not snapshot_carries_pinned_notice_texts_but_no_other_packaging_data" -q -p no:cacheprovider --basetemp <고유 TEMP> -W error::ResourceWarning -W error::DeprecationWarning --tb=short
```

모든 pytest는 고유 TEMP basetemp/cache-off/offscreen을 사용했다. 최종 경로는 TEMP `recoryn-l02-scope-final-fffdaa7136944579bd6a040b94b680ef`다.

명명 mutant **M6_DROP_LICENSE_TOC_FILTER**를 TEMP spec 사본에서 `_allowed`가 True를 반환하도록 한 번 변이했다. 같은 `test_spec_drops_license_excluded_components_and_keeps_required_ones`는 정상1 PASS/0.27s/exit0, 변이1 FAIL/0.30s/exit1로 COLLECT 결과의 실제 assertion에서 실패했다. import/수집 오류가 아니다. child -I와 TEMP manager import guard, coverage 환경 제거를 사용했다. workspace spec/manager/test hash는 전후 같았고 인덱스는 읽거나 쓰지 않았다. 변이 SHA `5f883e8b8d80defd3604ba1bc7a8926a5089f6aa713a767091e2426a6df0f6ba`. 증거: TEMP `recoryn-l02-m6-final-u22npr4e/{evidence.json,normal.log,mutant.log}`. 앞선 준비1회는 동시 작성으로 바뀐 옛 needle assertion에서 중단된 invalid 실행이며 kill로 세지 않았다.

실제 `build/l02-1794718201/dist/Recoryn`의1044파일을 직접 verify하고 공유 정책과 별도 이름/디렉터리 scan에서 금지0, 일반 PE closure 미해결0을 확인했다. 원 후보는 새 발견 수정 전 snapshot이다. 검토 초기의 manager/spec/hook/smoke4파일은 inputs 사본과 정확히 같았지만 이후 수정된 manager/spec와 일치하는 최종 후보라는 주장은 하지 않는다.

기존 후보를 덮어쓰지 않고 그 CLI의 `--release-smoke`를 새 TEMP cwd에서 직접 실행해 exit0/PASS를 확인했다. spawn child의 NOT_BUNDLED_STUB, faster-whisper1.2.1, Qt6.12.0 offscreen, DECODED_16K_MONO_FLOAT32, optional diarization import/capability, 추론 없이 worker 시작/종료, 기본 DNS 전 차단, 분리 mic4410/system4800 frame·원본 export hash 보존이 확인됐다. 실제 캡처·모델 추론은 NOT_RUN이다. 증거: TEMP `recoryn-l02-candidate-audit-idvvslgt/{candidate-evidence.json,smoke.stdout.json,smoke.stderr.log}`.

## 재확인 바이트와 인계

| 파일 | SHA256 |
| --- | --- |
| packaging/release_manager.py | e7660f63aec885b994d7df43573a890e3c7b0b22a1c3e42e12dcbf0f04258a41 |
| packaging/recoryn.spec | 1c96b136ea098e54ed7e0f6cc5c8d2d5b15e9da0449bd7d838400bad6d6415a4 |
| packaging/rthook_no_av.py | 377fa520cc53b341a9c429ec5d14df21f6624fa65f2314b117724c8758c277d3 |
| packaging/release_smoke.py | e456d477eb4ddc7bcd92ea6bff5812e572e2ab856cadfab09d75505df6ac8689 |
| scripts/build_release.py（L-P03 공존 workspace） | 7b28b74471b12ec1a7d7bf7cdcce9eded18b8063489c4e8fdc5425fd9c0b2b6d |
| tests/release/test_release.py | c18cd26b3f7a8b875647fbf4fe1005c17ac0fd9d779ea5d48da1ce2814be8fd5 |
| tests/release/test_spec.py | a9e2fe903ab68871aadea6df3e5b79e91fed243cf8994b1cbe9784c493337dce |
| tests/release/test_build_inputs.py（L-P03 공존 workspace） | 3c796054b8b9a8adc6fc037ad009313f230e1f747b122434c7d205a3a6cd3078 |

현재 OPEN0이며 세 건의 원 반례는 재확인됐다. 최종 L-P02 전용 blob/전체 회귀·CI, C00이 만들 새 snapshot frozen 후보의 동일성·smoke는 통합 단계에 남긴다. L-P03 고지 완전성·G3/G4·clean VM·서명·실음성·실모델·GPU·모든 Windows 호환성·법률 적합성은 승인하지 않았다. 실제 사용자 AppData 설치, 네트워크/서비스/계정/유료 호출, 추가 위임·pane, 승인 UI 입력은 수행하지 않았다. **REVIEW_READY / OPEN 0**.
