# Q-P02 상태·오디오 시험 통합 증거

2026-11-15. 통합자 Q00/root. 현재 상태 **VERIFIED — 두 독립 리뷰 RECHECKED, 격리 stage tree의 관련 5147 PASS 및 정적 검사 PASS**. 이 문서는 Q21/Q22의 작성자 결과와 root의 실제 통합 검증을 구분한다. commit/push와 해당 head의 원격 CI는 별도 게이트다.

## 단위와 선행 게이트

목적은 기존 Job 상태·fence/UNKNOWN 및 PCM/VAD/clock 계약의 유한 조합 누락을 보강하는 것이다. 생산 코드·기존 시험·의존성·CI는 변경하지 않는다. 기준 부모는 정책 commit `29e18b28d137f9478a139ec28ef086bb6d36e0d3`다. root가 해당 head의 [Q-P01 원격 CI](https://github.com/gangdonggilstudy/Recoryn/actions/runs/43608939380) success를 직접 확인했다. 기존 개발 snapshot `30703fe`의 1444 PASS/coverage/EXE 증거는 과거 결과이며 이번 새 시험의 결과로 대체하지 않는다.

정확한 manifest 7파일:

- tests/property/test_job_case_space.py
- tests/property/test_audio_case_space.py
- docs/testing/q21-state-cases.md
- docs/testing/q22-audio-cases.md
- docs/reviews/q21-test-design.md
- docs/reviews/q22-test-design.md
- docs/testing/q-core-results.md

Q21 작성/Q23 독립 검토, Q22 작성/Q24 독립 검토, root 통합이다. 후행 Q-P03 publication/security의 untracked 파일은 이 commit이나 검증 tree에 포함하지 않는다. 이 단위의 rollback은 해당 시험·문서 commit의 revert이며 제품 schema/runtime migration은 없다.

## 선언한 공간과 작성자 관측

| 영역 | 독립 분모 | 실제 유일 행 | 별도 pytest node |
| --- | --- | --- | --- |
| Q21 Job | H:6⁴ + D:2³ + F:8×2×3×2 + K:2⁴×2 = 1432 | 1432; 누락/중복 0; H의 유일 prefix 1555 | 1433: leaf1432+census1 |
| Q22 audio | 12가족의 합 3391; PCM raw1024 표현 중 동일 API singleton alias16을 별도 설명하여 canonical1008 | 3391; 누락/중복 0 | 3397: finite3391+census1+생성3+격리 mutation2 |
| 합계 | 4823 | 4823 | 4830; 기존 회귀와 구분 |

Q21의 UNKNOWN 우선순위 분기 제거는 정상 목표 node 1 PASS→동일 node의 기대 BLOCKED/REMOTE_UNKNOWN 대 실제 BACKOFF assertion FAIL이었다. Q22는 integer ties-to-even→truncate 및 VAD >=→>의 두 mutant가 각각 정상 1 PASS→목표 assertion 1 FAIL이었다. 모두 TEMP source 사본에서 수행했으며 원본 수정·import/수집 실패를 검출로 세지 않았다. Q22의 일반 pytest mutation harness는 child의 정확한 leaf만 선택하므로 자기 harness를 재귀 실행하지 않는다.

Q22 Hypothesis의 120/100/120 passing examples는 유한 3391행과 구별한다. 유한 대표값·Job 길이4 및 선택 retry3, PCM6frame/VAD5frame/제한 clock 이력 밖의 전수 검증을 주장하지 않는다. 자세한 oracle, 오차, 기존 node 대응, 명령과 원증거는 [Q21 설계](q21-state-cases.md), [Q22 설계](q22-audio-cases.md)에 있다.

## 동결 입력과 독립 검토

| 파일 | 작성자 제출 raw SHA-256 |
| --- | --- |
| test_job_case_space.py | f37901bba301beb797233d2ad606dd9540bb87572f251b9e56a94ff718ac3ef1 |
| test_audio_case_space.py | b52b3b7e75a86df2b84cc215d1510abf802f512d5eeace18f2b55d85c2a99e2e |

독립 판정은 [Q21 리뷰](../reviews/q21-test-design.md), [Q22 리뷰](../reviews/q22-test-design.md)에 기록했다. root는 두 리뷰의 대상 hash가 현재 두 시험·case 문서와 일치함을 확인했고 선언 범위의 OPEN S0/S1/S2 0건을 수락했다. Q21 리뷰 raw SHA는 `bd3a26c38ba7a486aa13a7d27e8f24c571fd98b7e550229afabecc254ec61549`, Q22 리뷰는 `7dbe2834a910ea6b36b53d2f3fb72a655ce778730b55063ad172a869152048c6`다. 기존 source tree Git object `21291eb8786d93bba9c8f7307b0cbaf05e7295ee`를 보존한다.

## Root 검증과 공개 상태

정확한 manifest만 stage한 검사 tree `6d588a7fecb0262723c258fa5a1297fad7a186b1`를 `git -c core.autocrlf=false archive`로 고유 TEMP `C:/Users/gangd/AppData/Local/Temp/recoryn-q-p02-tree-dd5uhkvo/tree`에 추출했다. 첫 추출은 Git의 Windows 줄바꿈 변환 때문에 blob raw hash와 달랐으므로 그 실행을 최종 바이트 증거로 쓰지 않고 변환을 끈 사본으로 재실행했다. 최종 manifest 파일은 `git show :<path>`의 blob bytes와 추출 파일 bytes가 같음을 검사했다. 후행 publication/security 두 새 시험 파일이 그 tree에 없음을 assertion으로 확인했다. cwd·pytest config·PYTHONPATH/MYPYPATH를 해당 snapshot으로 고정하고 실제 recoryn import origin도 snapshot/src 아래임을 별도 실행 확인했다.

Windows/CPython3.13.1에서 **5147 PASS / 16.18s**, error/failure/skip 0이었다. 새4830 node와 관련 기존317 node를 포함한다. 새 두 파일의 Ruff check/format 및 strict mypy 2파일도 PASS다. 검증은 cache-off·고유 basetemp·ResourceWarning-error·`--runxfail`로 실행했다. 전체 프로젝트 coverage 실행은 이 선택 실행으로 대체하지 않으며 원격 CI와 최종 Q-P03 전체 실행으로 따로 확인한다.

```text
D:/project/Recoryn/.venv/Scripts/python.exe -m pytest -c <snapshot>/pyproject.toml -o pythonpath=<snapshot>/src -q -p no:cacheprovider --runxfail --basetemp <evidence-root>/pytest-temp -W error::ResourceWarning --junitxml=<evidence-root>/pytest.xml tests/property/test_job_case_space.py tests/property/test_audio_case_space.py tests/unit/test_jobs.py tests/unit/test_domain.py tests/integration/test_job_publication.py tests/unit/test_audio.py tests/unit/test_wasapi.py tests/unit/test_media.py tests/property/test_queue_model.py tests/property/test_pcm_storage_oracle.py
```

`<evidence-root>`는 위 TEMP의 tree 상위다. report.json은 tree/base/manifest·실행 argv·exit·파일 SHA·JUnit 수를, pytest.xml/pytest.log 및 import-origin/ruff/format/mypy.log는 실제 출력을 보존한다. 검사 후 이 결과문서만 통합 증거로 갱신하며 실행 source/test·나머지6파일의 index blob이 검사 tree와 같음을 다시 확인한다. Markdown 상대 링크·공백 오류와 정확한 7경로 manifest를 최종 검사한다. 자기 문서의 hash/tree를 본문에 넣기 위한 순환 갱신은 하지 않는다.

실음성·장치·모델·네트워크 서비스·OS sleep·전원 장애/G3/G4는 NOT_RUN이다. Q-P02 remote ref와 CI head의 정본은 Git/실제 원격 run이며 Q-P03 문서 갱신에서 선행 증거로 연결할 수 있다. Q-P02 원격 CI PASS 전 Q-P03 공개는 보류한다.
