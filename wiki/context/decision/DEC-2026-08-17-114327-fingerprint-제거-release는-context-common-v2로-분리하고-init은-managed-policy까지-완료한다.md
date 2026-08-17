---
title: Fingerprint 제거 release는 context-common/v2로 분리하고 init은 managed policy까지 완료한다
created_at: 2026-08-17
summary: Fingerprint를 제거한 0.2.0을 protocol v2로 격리하고 명시적 init이 storage, area와 host managed policy를 한 흐름으로 적용한다.
tags: [context-core, context-decision, init, policy, protocol]
supersedes: [DEC-2026-08-14-173233-명시적-init-호출은-필요한-repository-bootstrap을-한-번에-완료한다]
relations:
  ssot: [context-core-plugin, context-decision-plugin, context-v1-implementation]
---

## 결정

`context-core`와 `context-decision` 0.2.0에서 `claim_fingerprint`와 `source_claim_fingerprint`를 제거하고 공통 wire/storage handshake를 `context-common/v2`로 올린다. 0.1.x와 0.2.0 혼합 설치는 호환으로 간주하지 않고 preflight에서 fail-closed한다. legacy artifact에 제거된 field가 남아 있으면 묵시적으로 무시하거나 자동 삭제하지 않으며, 별도의 검토·승인된 migration 뒤 derived index를 rebuild한다.

`context-core:init`은 canonical core storage와 현재 host의 managed policy를 한 호출에서 적용한다. `context-decision:init`은 exact compatible core를 확인한 뒤 필요한 core storage, decision area와 현재 host managed policy를 같은 호출에서 순서대로 적용한다. 활성 host mapping은 `codex → AGENTS.md`, `claude-code → CLAUDE.md`다. init은 policy target과 bytes를 모든 storage write 전에 preflight하고, 안전하지 않으면 전체 write 0으로 실패한다. ready 상태와 최신 policy에서는 모든 phase가 noop이다.

managed policy는 substantive 판단 전에 scoped Current recall과 실제 본문·rationale 비교를 요구하고, conflict나 rationale change를 결론 전에 알린다. 원래 요청을 먼저 완료한 뒤 semantic milestone에서만 grouped capture를 제안하며 사용자 승인 전 durable write를 금지한다.

plugin 설치·활성화·업데이트, partial/invalid repository 자동 복구와 일반 DEC·OBS·SNAP/user-content mutation은 init 권한에 포함하지 않는다. 일반 mutation의 exact digest 승인 경계는 유지한다.

## 취지

Fingerprint는 문장 동일성만 안정적으로 식별할 뿐 같은 의미의 다른 문장이나 유사하지만 다른 의미를 판정하지 못한다. 이 field를 제거하면서 기존 `context-common/v1`을 계속 광고하면 0.1.x와 0.2.0이 호환되는 것처럼 보이지만 실제 artifact와 lifecycle shape는 서로 처리할 수 없다. breaking boundary를 v2로 명시해 잘못된 혼합 실행을 preflight에서 차단한다.

이 플러그인의 목적은 저장소만 만드는 것이 아니라 대화 중 기존 맥락을 능동적으로 recall하고 실제 본문을 비교해 충돌과 취지 변화를 알려주는 것이다. managed policy가 init에서 빠지면 기본 초기화 뒤에도 이 흐름이 자동 로드되지 않는다. 사용자가 플러그인 init을 명시적으로 요청한 것을 fixed storage와 marker-bounded 운영지침을 함께 준비하는 의도로 해석해 한 흐름으로 완료한다.

## 배경

이전 결정은 repository bootstrap과 plugin 설치 권한을 분리하면서 선택적 agent policy 설치도 init 밖에 두었다. 이후 구현과 사용 흐름을 검토한 결과, plugin 설치·활성화와 달리 managed policy는 이 플러그인의 핵심 대화 lifecycle을 작동시키는 repository-local fixed artifact이며 init에서 함께 적용해야 초기화 직후 기대한 기능이 동작한다.

정책 설치는 임의 host mutation이 아니라 exact root basename 하나의 marker-bounded block으로 제한한다. preflight, byte/mode 보존, symlink 거부, structured error, atomic replace와 idempotent noop 계약으로 기존 사용자 파일을 보호한다.

## 고려한 대안

1. `context-common/v1`을 유지한다: 실제로 호환되지 않는 버전을 호환 가능하다고 광고하므로 반려한다.
2. legacy fingerprint field를 조용히 무시한다: 제거 의도가 불명확해지고 구형·신형 artifact가 혼재하므로 반려한다.
3. policy를 별도 `--install-policy` flag나 preview 승인으로 분리한다: storage는 준비되지만 핵심 recall·비교·알림 흐름이 기본 활성화되지 않아 init의 제품 의미가 불완전해지므로 반려한다.
4. managed policy 기능 자체를 제거한다: background runtime hook 없이 매 대화에서 proactive workflow를 자동 로드할 표면이 없어지므로 반려한다.
5. init이 plugin 설치·활성화까지 수행한다: host 환경 scope를 임의 변경하므로 계속 반려한다.

## 트레이드오프

0.1.x artifact는 별도 migration 없이는 0.2.0에서 바로 사용할 수 없다. init이 `AGENTS.md` 또는 `CLAUDE.md`도 변경하므로 policy preflight 실패가 storage bootstrap까지 차단하며, host를 식별할 수 없으면 어떤 write도 하지 않는다. 대신 설치 직후 핵심 대화 흐름이 일관되게 작동하고 protocol 호환성과 사용자 승인 범위가 명확해진다.

background daemon이나 runtime hook은 만들지 않고 host의 auto-loaded entry file에 의존한다. 기존 파일의 marker 밖 bytes와 mode를 보존하고 신규 파일은 canonical mode로 생성하지만, repository별 agent policy 자체를 원하지 않는 사용자를 위한 storage-only user-facing init은 현재 제공하지 않는다.

## 재평가 조건

fingerprint 없이 0.1.x artifact를 안전하게 변환하는 versioned migration이 마련되거나, protocol major보다 정확한 상호 capability negotiation이 도입되면 호환 경계를 재검토한다. host가 repository별 agent policy를 별도 권한과 native API로 제공하거나 managed policy의 recall 비용·오탐이 실제 사용에서 과도하다고 확인되면 설치 표면을 재평가한다. init policy preflight가 정상 repository bootstrap을 반복적으로 방해한다는 운영 근거가 쌓이면 storage-only escape hatch를 검토한다.
