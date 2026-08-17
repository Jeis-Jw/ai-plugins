---
title: context 무결성은 검색 경고와 대상 write 경계로 분리한다
created_at: 2026-08-17
summary: 포맷·파생 index drift는 warning과 즉시 수리로 처리하고 fail-closed는 실제 target write의 CAS·path·lock·approval 안전 경계에 한정한다.
tags: [context-core, context-decision, integrity, index, fail-closed]
search_terms: [write boundary, repository_state, index fallback, lazy-clean, doctor, preflight]
supersedes: [DEC-2026-08-17-114327-fingerprint-제거-release는-context-common-v2로-분리하고-init은-managed-policy까지-완료한다]
relations:
  ssot: [context-core-plugin, context-decision-plugin, context-storage-retrieval]
---

## 결정

`context-core`와 `context-decision`의 fail-closed 경계를 corpus 전체 정합성이 아니라 실제 write 대상의 안전 경계로 한정한다.

`claim_fingerprint`와 `source_claim_fingerprint`를 제거하고 `context-common/v2`로 분리한 호환성 경계, exact provider 수동 의존, 명시적 init의 storage·area·managed policy 통합, 일반 artifact mutation의 exact approval digest는 유지한다. 서로 다른 protocol이나 source, disabled core, path·symlink 위험, 대상 artifact CAS 불일치, duplicate ID, 대상 area index precondition 불일치, lifecycle 충돌, atomic replace/root lock 실패는 계속 write 0으로 중단한다.

반면 `schema_removed_field`를 포함한 포맷-only drift는 non-blocking warning이며 `repository_state`를 invalid로 만들지 않는다. 제거된 field는 해당 artifact가 이후 명시적으로 승인된 write의 대상이 될 때 canonical renderer가 자연스럽게 제거하는 lazy-clean으로 처리하고, read나 init이 user artifact를 자동 변환하지 않는다.

`context.index.md`와 area index는 artifact에서 다시 만들 수 있는 파생물이다. missing·ghost·wrong path/state 같은 index-only drift는 recall에서 fallback 결과와 warning을 제공하고, `refresh --fix index` 한 번으로 별도 approval 없이 즉시 rebuild한다. artifact 본문과 lifecycle은 이 경로에서 절대 수정하지 않는다. `--strict-index`는 index 엄격성을 필요한 호출만 opt-in하는 경계로 유지한다.

doctor는 요청 시 상태와 warning을 보여 주는 read-only 진단 도구다. init과 addon preflight는 corpus 전체가 `ready`인지 요구하지 않고 현재 작업에 필요한 root·area·target만 검사한다. populated repository에서 root index만 빠진 상태는 doctor와 init이 같은 repairable 상태로 판정하고 init이 파생 index를 복구할 수 있어야 한다. addon은 core가 실제로 absent이거나 source·enabled·protocol이 맞지 않을 때, 또는 blocking issue가 작업 대상과 겹칠 때만 중단한다.

write precondition은 대상 artifact의 exact CAS bytes, 대상 area index, repository-wide duplicate ID, path traversal·symlink guard, atomic replace, root lock과 승인 digest 1회 사용을 검증한다. 무관한 artifact의 포맷·lifecycle 오염은 해당 write를 막지 않는다.

## 취지

Markdown schema와 index는 관련 맥락을 더 적은 I/O와 토큰으로 찾고 안전하게 저장하기 위한 수단이다. 재생성 가능한 파생물이나 과거 포맷 잔재가 정상 recall·init·독립 write를 멈추게 하면 무결성 기계가 제품 목적을 역전한다.

따라서 read는 가능한 결과와 명시적 warning을 우선하고, write만 손실 가능성이 있는 exact 대상 경계에서 보수적으로 막는다. 이 분리는 recall의 기존 `index_fallback:true`와 `--strict-index` opt-in 설계를 doctor·init·addon preflight·refresh에도 일관되게 적용한다.

## 배경

소스 감사와 temp repository runtime 검증에서 제거된 legacy field `claim_fingerprint` 잔재 8건이 `repository_state=invalid`를 만들어 init과 addon preflight 전체를 차단했다. 이 게이트가 보호한 write나 데이터는 없었고, 관련 없는 작업 한 건만 중단시켰다. 동시에 미지·오타 field는 통과해 blocking 기준도 대칭적이지 않았다.

derived index의 missing·ghost row 역시 artifact 원문이나 Git 이력을 훼손하지 않는데도 일반 artifact와 같은 preview→digest approval→apply 절차를 요구했다. root index만 없는 populated 상태에서는 doctor가 absent를, init이 partial을 반환해 같은 저장소를 서로 다르게 판정했다.

기존 recall은 index가 깨져도 corpus scan fallback으로 결과를 반환하고 warning을 노출하며 엄격함은 `--strict-index` 호출에만 적용한다. 이 동작이 이번 경계 재정의의 선례다.

## 고려한 대안

1. corpus 전체가 clean일 때만 모든 operation을 허용한다: 무관한 포맷 잔재와 파생 index drift가 제품 전체를 멈추고 실제 손실 방지와 연결되지 않아 반려한다.
2. legacy field를 warning 없이 묵살한다: 운영자가 drift를 발견하거나 정리할 계기를 잃으므로 반려한다.
3. read 또는 init에서 user artifact를 자동 migration한다: 명시 승인 없는 본문·lifecycle mutation이 되므로 반려한다.
4. derived index rebuild에도 artifact approval digest를 요구한다: 재생성 가능한 캐시를 user-authored record와 같은 권위로 취급해 비용만 늘리므로 반려한다.
5. CAS·duplicate ID·path guard·atomic replace·root lock·approval digest도 완화한다: 저장 손실과 승인 우회를 직접 막는 경계이므로 반려한다.
6. 새 schema version, migration identifier 또는 별도 repair daemon을 도입한다: 현재 문제를 푸는 데 불필요한 표면과 운영 부담을 만들므로 반려한다.

## 트레이드오프

warning-only drift는 다음 authorized rewrite까지 repository에 남을 수 있고, doctor clean을 운영상 강제 gate로 사용하던 흐름은 별도 `--strict-index` 또는 대상별 검증으로 바꿔야 한다. index fallback은 정상 index lookup보다 느리지만 결과를 잃지 않으며, 명시적 `refresh --fix index`가 즉시 정상 성능을 회복한다.

target-scoped write validation은 무관한 오염을 함께 청소하지 않는다. 대신 한 파일의 문제로 독립 mutation이 정지하지 않고, 실제 target CAS·area index·duplicate ID·path safety·approval 경계는 그대로 보존된다.

이 결정은 `context-common/v2` 호환성 차단, exact core distribution identity, managed policy init, user artifact approval ceremony를 완화하지 않는다. 자동 수리는 derived index에만 허용한다.

## 재평가 조건

warning으로 강등한 포맷 drift가 실제 잘못된 artifact 선택, 승인 우회, 데이터 손실 또는 lifecycle corruption을 일으킨 재현 사례가 나오면 그 issue를 작업 대상 경계의 blocking check로 승격한다. target-scoped validation으로 duplicate ID나 cross-area reference 위험을 안정적으로 검출할 수 없다는 증거가 생기면 필요한 최소 scan 범위를 확대한다.

corpus 규모에서 fallback 또는 full duplicate scan 비용이 실측 병목이 되면 기존 index shape 안에서 incremental repair를 검토한다. 새 schema·identifier·daemon은 현재 계약으로 해결할 수 없다는 측정 근거가 생기기 전에는 도입하지 않는다.
