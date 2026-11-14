# P11 독립 storage 코드 리뷰

2026-11-14 / 검토자 P11(P01 아키텍트) / 대상 작성자 P03 / 상태: **발견 OPEN, 원 작성자 수정 및 동일 P11 재확인 필요**.
P01 domain/jobs 자체 검증과 구분한 독립 리뷰다. 이 배정에서는 타인 소스·테스트·Git을 수정하지 않았다. 작성 중 임시 lint/type 문제는 지적 대상에서 제외했다.

## 범위와 검토 snapshot

읽은 코드: `src/recoryn/storage/{__init__,_safe,chunks,library}.py`. [P0 계약](../implementation/p0-contracts.md), 관련 integration/property 테스트와 CLI export의 청크 소비 경로도 대조했다. `tests/unit/test_storage.py`는 검토 시점에 아직 없었다.
P03가 작성 중이므로 초기 읽기와 재현 사이의 수정을 구분했다. 아래 발견은 최종 재현 시점의 코드에서 확인했으며, 이후 수정은 재확인 전 해결로 판단하지 않는다.

| 파일 | 최종 재현 시 SHA-256 |
| --- | --- |
| `storage/chunks.py` | `BB7511994CF4270D14B18DDABB5BE1795E8AD939685E79CF646C3EF67FCAC69A` |
| `storage/library.py` | `F3F4527E4BA6E9BD159D98DED7CA62E67298353EA2CC72EB5AF6A03F3A47AADF` |
| `storage/_safe.py` | `F11224971DEA5BC1EE55C12010CE01461C3403D237A22E286492E651C73C9378` |
| `storage/__init__.py` | `D44F1663957C4840A0A7F666F1464ADEFD8DD83D1DA892206C21ED84C031C7C3` |

## P11-01 / S1 / 삭제 성공 후 지연 writer가 원본을 다시 생성

- 위치: `chunks.py:42`의 `has_active_writer`, `:309`의 `_open`, `:323`의 `append`; `library.py:531`의 `delete_session` 및 active writer 검사.
- 반례: 세션 생성 → `writer = ChunkWriter(root, block, 'delayed')`만 수행 → `delete_session` → 같은 writer의 `append(block); seal()`. constructor는 계약대로 첫 블록을 추가하지 않으며 writer registry도 `_open` 때에만 등록한다. 삭제는 이 writer를 보지 못하고 성공하지만 이후 `_open/append/seal`에 삭제 세대 검사가 없다.
- 실제 결과: 삭제 응답 `state=DELETED_LOCAL, deleted=true` 뒤 `audio.pcm`이 다시 존재했다. recover는 tombstone을 보고 DELETE_PENDING을 반환하므로 카탈로그 부활은 막지만, 사용자 삭제 완료 이후 새 물리 사본 생성은 막지 못한다.
- 해결 조건: 지연/기존 writer의 수락·게시와 삭제 intent를 공통 조정 경계로 묶고 삭제 세대가 바뀐 writer의 신규 파일 생성·append·seal을 차단한다. constructor registry 추가만으로 동시 `_open` 경합이 해결되는지도 검증해야 한다. 삭제 성공 이후에는 폐기된 writer가 미디어를 재생성할 수 없어야 한다.
- 회귀 조건: 위 순차 반례와 `_open` 직전 barrier에서 삭제가 먼저 확정된 경우 모두 신규 미디어 0. 이미 열린 writer가 있으면 삭제는 pending을 유지하고 중단 확인 뒤만 완료한다. 원본 삭제 후 stale bundle 재채택 차단 시험만으로 대체하지 않는다.

## P11-02 / S2 / 마지막 fragment 누락을 완성 bundle로 검증

- 위치: `chunks.py:138`의 `_next`, `:175`의 `scan_prefix`, `:371`의 `seal`.
- 반례: 한 frame의 `PCMBlock(fragment_index=0, fragment_count=2)`만 append한 뒤 seal→verify_bundle→register_chunk→finalize_session을 호출한다. `_next`는 다음 sequence가 올 때 이전 fragment 완료를 검사하지만 journal 끝에는 마지막 `fragment_index + 1 == fragment_count` 검사가 없다.
- 실제 결과: `seal`과 `verify_bundle`이 모두 성공하고 `FINALIZED, manifest_sync_pending=false, frame_count=1`을 반환했다. 저장된 frame 자체는 검증되지만 알려진 미완성 packet이 정상 bundle과 구별되지 않는다.
- 해결 조건: 완성 bundle은 마지막 packet fragment 완결성을 검사한다. 복구가 검증된 fragment prefix를 보존하는 것은 허용하되 미완성 fragment·미상 유실 범위를 명시하고 정상 봉인/준비와 구분한다. 다른 chunk에서 packet을 이어받는 정책이라면 현재 “첫 fragment=0” 조건과 일관된 별도 계약이 필요하다.
- 회귀 조건: count=2의 index=0만 있는 경우 정상 seal/strict verify 거부 또는 명시적 partial/gap. 복구는 검증된 bytes를 보존하며 반복 실행 시 중복이 없어야 한다. FINALIZED 자체가 무손실 보장은 아니라는 제한과 별개인 fragment 검증 문제다.

## P11-03 / S2 / 손상 manifest가 DB 기반 재생성을 영구 차단

- 위치: `_safe.py:192`의 `atomic_json`(기존 파일 `schema(read_json(...))`), `library.py:338`의 `write_manifest`, `recover_session`의 projection 재시도.
- 반례: 유효 원본·DB가 있는 FINALIZED 세션의 `manifest.json`만 `{`로 손상시킨 뒤 recover_session을 두 번 호출한다.
- 실제 결과: 두 번 모두 `warnings=['MANIFEST_SYNC_PENDING']`, manifest 내용은 계속 `{`였다. 기존 manifest 파싱이 실패하면 새 DB snapshot 작성 단계에 도달하지 않으므로 재시도로 회복되지 않는다. export도 write_manifest를 먼저 호출해 차단된다.
- 해결 조건: 업무 상태의 기준인 DB와 검증된 원본에서 손상 projection을 재생성하는 manifest 전용 절차를 둔다. 기존 손상본은 필요시 격리하고 pending/retry 상태를 일관되게 기록한다. 공통 atomic_json의 보호를 통째로 제거하여 미지원 미래 schema나 삭제 journal 손상을 조용히 덮는 방식은 피한다.
- 회귀 조건: malformed manifest와 누락 manifest 모두 DB·원본 불변인 채 재생성·재export 가능. 미래 schema/삭제 이력 판정불가의 fail-closed 정책은 유지한다.

## 실행 재현과 독립 oracle

실제 합성 bytes는 s16le mono 1 frame의 `01 00`, `02 00`처럼 손으로 확인 가능한 값이다. SyntheticSource 또는 작성자의 계산식을 정답으로 사용하지 않았다. 별도 OS 임시 폴더만 사용했고 ACL을 변경하지 않았다.
재현 스크립트는 `C:/Users/gangd/AppData/Local/Temp/recoryn-p11-39fb8b77a64a4d3cbddd3d396e260cd0/repro.py`에 보존했다. SHA-256: `7617368CB1B1CC184596C9F9236354A7DFBF9FF914B71B055BB72D1176F92B03`.

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
$caseRoot = Join-Path $env:TEMP ('recoryn-p11-' + [guid]::NewGuid().ToString('N'))
& .venv/Scripts/python.exe "$env:TEMP/recoryn-p11-39fb8b77a64a4d3cbddd3d396e260cd0/repro.py" $caseRoot
```

최종 실행 종료 코드 0. 증거 폴더: `C:/Users/gangd/AppData/Local/Temp/recoryn-p11-1d8658e7680e4ac6adc9fce87044011e`, 출력은 그 아래 `result.txt`다. 임시 증거가 사라져도 위 세 반례의 API 순서와 입력으로 시험을 다시 만들 수 있다.

```text
ORDER: expected_samples=[1,2], actual_samples=[1,2], chunk_ids=[z_early,a_late]
DUPLICATE_REJECTED: StateConflict / Overlapping source sequence ranges
DUPLICATE: unique_frames=1, actual_frames=1, chunk_count=1
DELETE_LATE_WRITER: deleted=true, media_exists_after_delete=true
INCOMPLETE_FRAGMENT: index=0/count=2, seal_and_verify_accepted=true, FINALIZED
CORRUPT_PROJECTION: MANIFEST_SYNC_PENDING twice, remaining_manifest="{"
PREFIX_CONTROL: first_recovered=1, second_recovered=0, frames=1, pcm=0100
```

chronological order와 중복 범위 등록은 재현 시 보강된 코드에서 통과했으므로 열린 발견으로 세지 않았다. 역순 chunk 이름을 실제 WAV로 내보내 `01 00 02 00`을 확인했다. 같은 source 범위의 다른 chunk ID는 등록이 거부되고 반복 recovery 후에도 1 frame이었다. torn JSONL 뒤 검증된 prefix 복구도 첫 1건·둘째 0건이며 원본 bytes가 일치했다.

관련 테스트도 직접 실행했다. 작성자 자체 통과 로그를 복사한 결과가 아니다.

```powershell
$testRoot = Join-Path $env:TEMP ('recoryn-p11-pytest-' + [guid]::NewGuid().ToString('N'))
& .venv/Scripts/python.exe -m pytest tests/integration/test_storage_integrity.py tests/integration/test_process_crash.py tests/property/test_pcm_storage_oracle.py --basetemp $testRoot -p no:cacheprovider -q
```

결과: **21 passed in 5.00s**. subprocess kill 3단계·writer lock, 원본 bytes/hash, journal 손상·prefix·반복 복구, manifest-only 실패, 삭제 후 stale bundle 차단을 포함한다. 이 통과 결과가 위 누락 반례까지 검증했다는 뜻은 아니다.

## 판단과 남은 제한

**S1 1건(P11-01), S2 2건(P11-02/03), 모두 OPEN.** 원 작성자 수정과 동일 리뷰어 재확인 전 storage 독립 리뷰를 통과 처리하지 않는다. 공용 파일·대상 소스·테스트·Git을 수정하거나 재위임하지 않았다.
실제 Windows 오디오, 물리 전원 차단/저장장치 고장, 공격자의 동시 reparse 교체, 모든 삭제·reader/Job 경합, 대용량 장시간 성능은 미검증이다. `.writer.lock`, WAL/FULL, 파일 fsync·rename의 관측을 전원 장애 내구성 보장으로 확대하지 않는다.

## P11 수정 후 독립 재확인 — 2026-11-14

재확인자: 원 리뷰어 P11. 대상은 P03의 storage 수정본과 해당 회귀 시험이다. 자신의 jobs/domain 구현이나 P12 결과를 승인하지 않았다. 위 발견·당시 digest·실패 출력은 보존하며 아래 상태가 이번 snapshot의 최신 판정이다.
추가 전 리뷰 본문 8,914 bytes의 SHA-256은 `1C331D3E73EB62BB67D32763D0D5BA9B3098346573F79A87035AEDF856713CB5`다.

### 재확인 snapshot

| 파일 | SHA-256 |
| --- | --- |
| `storage/_coordination.py` | `6BC1CF66A153847C52D7EB4B61577A33BD9C5DD611E519E3E5D8D6FD8AA9EBA6` |
| `storage/chunks.py` | `080EFD3D22F4AF0CB1A32ECB81538E5C6F9FC76DC4B468C774850758183F2CF8` |
| `storage/library.py` | `030620D823EA784D9F1934CFCEDC9902941D21635819B104E6D3175C665B84A2` |
| `storage/_safe.py` | `F11224971DEA5BC1EE55C12010CE01461C3403D237A22E286492E651C73C9378` |
| `storage/__init__.py` | `D44F1663957C4840A0A7F666F1464ADEFD8DD83D1DA892206C21ED84C031C7C3` |
| `tests/unit/test_storage.py` | `6E2714C11191EB2ABFE2CFF3668978A7F0ABC1B0B9D6B5E2896E72AE880B66E6` |
| `tests/integration/test_storage_integrity.py` | `73CDFA537590323A2B866B6ECB9212725F3C0CA2101C4E2D35113F39FF11A7F3` |
| `tests/integration/test_process_crash.py` | `35B2C2338D5EE71B24B0A3A2D9EFDA6A27ADFE3821990C76A0CA656FA418F58A` |
| `tests/property/test_pcm_storage_oracle.py` | `E3A1CC36CBC657D7A05352624B5EB6F688602E9AB365AC152AE806208D8736BD` |

### P11-01 — RECHECKED

`_coordination.py::root_mutex/check_write_allowed`와 `Library.__init__`의 공통 root RLock, `ChunkWriter.append/seal/_open`의 tombstone·DB 삭제 세대 검사를 읽었다. 공개 append/seal은 검사를 포함한 파일 수락·게시 구간을 잠그며 delete_session도 같은 잠금을 사용한다.
독립 probe에서 원 순차 반례의 append/seal/새 writer를 모두 거부했다. 추가로 별도 thread의 실제 `_open` 호출을 Event 앞에 지연시키고 삭제 성공 뒤 해제하여 StateConflict와 신규 미디어 0을 확인했다. 반대 순서는 공개 append가 공통 경계 안에서 `_open` 직전 대기할 때 삭제를 요청했다. 삭제는 그 경계를 넘지 못했고 append 완료 뒤 DELETE_PENDING을 반환했으며 이후 append/seal은 거부됐다. abort 뒤 재삭제가 완료되고 미디어는 남지 않았다.
관련 실행 시험: `test_p11_late_writer_is_fenced_after_delete`, `test_p11_open_delete_barrier`의 양 순서, 독립 integration의 `test_delayed_writer_cannot_recreate_media_after_successful_delete`.
남은 제한: 같은 프로세스의 협력 thread 조정과 Library OS writer lock 전제를 검증한 것이다. 임의의 외부 프로세스·동일 사용자 공격자의 경로 교체까지 보호한다고 확대하지 않는다.

### P11-02 — RECHECKED

`chunks.py::_seal`은 마지막 fragment 완결을 검사하고 `scan_prefix(strict=True)`도 미완성 packet을 거부한다. 일반 prefix scan은 마지막 완료 packet 시점의 count/bytes/frames/hash로 되돌린다. `Library._salvage/recover_session`은 기존 staging을 바꾸지 않고 불완전 꼬리를 채택하지 않았다는 경고를 유지한다.
독립 probe 두 경우 모두 정상 seal과 strict prefix 검증이 거부됐다. 앞선 완료 packet이 없으면 첫 복구는 recovered=0·quarantined=1, 두 번째도 recovered=0이었다. 완료 1 frame 뒤 미완성 fragment를 붙인 경우는 첫 recovered=1·둘째 0, 회수 PCM=`01 00`, `STAGING_TAIL_NOT_ADOPTED` 경고였다. 두 경우 모두 staging의 PCM/journal SHA-256이 그대로여서 채택하지 않은 검증 bytes도 보존됨을 확인했다.
관련 실행 시험: `test_p11_incomplete_fragment_is_not_normal_bundle` 양 경우, `test_strict_bundle_boundary_errors`의 fragment 변조, prefix 반복 복구 시험.
남은 제한: 회수 가능 prefix는 완료 packet까지만 정상 artifact로 게시한다. 미완성 packet bytes의 원본 staging 보존을 그 구간의 재생·복원 완료로 해석하지 않는다.

### P11-03 — RECHECKED

`Library.write_manifest`의 manifest 전용 손상본 격리와 DB projection 재생성을 읽었다. 유효 JSON의 미지원 schema는 별도로 거부하며 공통 `atomic_json`·삭제 journal의 보호는 유지한다. 복구 projection 실패 시 pending을 DB에 남기는 처리도 확인했다.
독립 probe에서 `{` 손상본을 정확히 보존한 quarantine 1개, 복구 두 번의 pending 경고 없음, 원본 파일 hash·세션 상태/버전·청크 목록 불변을 확인했다. manifest를 없앤 경우도 재생성됐고 실제 WAV 재export 결과는 `01 00`이었다. 이후 schema_version=2인 유효 manifest는 write_manifest가 거부했고 원 bytes가 유지됐으며 recover는 pending을 보고했다.
관련 실행 시험: `test_p11_malformed_and_missing_projection_rebuilt`, `test_malformed_manifest_is_rebuilt_from_verified_db_and_media`, `test_future_manifest_not_overwritten`, 삭제 이력 fail-closed·manifest-only 실패 시험.
남은 제한: quarantine 생성/교체 각 syscall의 실제 전원 차단 내구성과 모든 접근 권한 실패 조합을 검증한 것은 아니다.

### 독립 실행 명령·증거

기존 실패 스크립트는 수정하지 않고 별도 assertion 기반 probe를 OS 임시 폴더에 작성했다. script: `C:/Users/gangd/AppData/Local/Temp/recoryn-p11-recheck-3053e8cf5c8e441a8b6c2569c5036b32/recheck.py`, SHA-256 `289AB4855B782474456A303352353892536BB0AA3DC4A82C6DDAE5D4EC49FB89`.
같은 폴더의 `result.txt`에 실제 출력을 보존했다. 다시 실행할 때는 새 caseRoot를 사용한다.

```powershell
$env:PYTHONPATH = (Resolve-Path src).Path
$caseRoot = Join-Path $env:TEMP ('recoryn-p11-recheck-' + [guid]::NewGuid().ToString('N'))
& .venv/Scripts/python.exe "$env:TEMP/recoryn-p11-recheck-3053e8cf5c8e441a8b6c2569c5036b32/recheck.py" $caseRoot
$testRoot = Join-Path $env:TEMP ('recoryn-p11-recheck-pytest-' + [guid]::NewGuid().ToString('N'))
& .venv/Scripts/python.exe -m pytest tests/unit/test_storage.py tests/integration/test_storage_integrity.py tests/integration/test_process_crash.py tests/property/test_pcm_storage_oracle.py --basetemp $testRoot -p no:cacheprovider -q
```

probe 종료 코드 0, `ALL_RECHECK_ORACLES_PASS`. pytest는 이번 리뷰어가 직접 실행하여 **122 passed in 9.61s**였다. P03의 자체 94개 통과 보고를 복사하지 않았다. 실제 실장비·마이크·시스템 오디오는 호출하지 않았고 다른 폴더 ACL도 바꾸지 않았다.
추가 독립 byte oracle는 늦은 chunk를 먼저 등록하고 이름도 역순으로 둬도 목록 sequence=[0,1]·WAV samples=[1,2]임을 확인했다. 같은 source 범위의 overlap은 거부되고 recovery로 중복 채택되지 않았다.
UNC는 filesystem probe 전에 거부되는지 검사했다. mapped drive는 GetDriveTypeW를 0/1/4로 대체하여 unknown/remote 판정의 거부를 확인했으며 실제 네트워크 드라이브에 접속하지 않았다. traversal·절대 경로·ADS·역슬래시 부정 입력도 거부됐다. 이는 실제 모든 mount/UNC 환경의 호환성 시험은 아니다.

### 범위 한정 결론

**P11-01~03: 3/3 RECHECKED, 이 세 발견의 미해결 0건(S0/S1 0건).** 코드와 실행 반례의 해결을 확인했다. 원 기록은 보존하며 최종 CLOSED/통합 상태 반영은 D00이 수행한다. jobs 승인, 전체 P0 완료, G3 장치·성능 및 G4 배포 통과를 대신 선언하지 않는다.
이번 쓰기는 이 리뷰 후단과 허용된 OS 임시 재현 산출물뿐이다. storage·타인 테스트·공용 문서·Git은 수정하지 않았다.
