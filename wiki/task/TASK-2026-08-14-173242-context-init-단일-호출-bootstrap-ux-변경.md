---
title: context init 단일 호출 bootstrap UX 변경
created_at: 2026-08-14
summary: core init을 즉시 적용하고 decision init이 필요한 core bootstrap까지 연계하도록 두 plugin의 init 계약을 수정·검증한다.
tags: [context-core, context-decision, init, bootstrap, implementation]
relations:
  ssot: [context-core-plugin, context-decision-plugin, context-v1-implementation]
  decisions: [DEC-2026-08-17-222516-context-무결성은-검색-경고와-대상-write-경계로-분리한다]
---

## 개요

`context-core:init`을 한 번의 명시적 호출로 실제 초기화하는 idempotent command로 바꾸고, `context-decision:init`이 exact compatible core가 설치된 환경에서는 필요한 core initialization과 decision area registration을 한 번에 완료하도록 구현한다. plugin 설치·활성화·업데이트는 자동화하지 않는다.

## 근거

사용자는 init 호출 자체가 사용 가능한 상태를 만드는 실행 의사라고 명확히 했고, core와 decision을 모두 설치한 뒤 두 init 명령을 호출하는 경로는 불필요하다고 결정했다. 기존 manual hard dependency의 목적은 host environment와 install scope 보호이며, fixed repository bootstrap의 중복 승인을 유지하는 것이 아니다.

## 범위와 완료 기준

범위는 `plugins/context-core/**`, `plugins/context-decision/**`, `tests/context-v1/**`, 관련 marketplace/distribution contract와 `wiki/ssot/context-core-plugin.md`, `wiki/ssot/context-decision-plugin.md`, `wiki/ssot/context-plugin-definition/**`의 새 init 계약이다.

완료 기준: (1) core absent에서 `context-core:init` 한 번으로 doctor가 ready가 되고 ready 재호출은 noop이다. (2) 기존 valid data는 삭제·덮어쓰기 하지 않고 partial·invalid는 fail-closed한다. (3) exact installed/enabled/compatible core 아래 `context-decision:init` 한 번으로 absent core와 decision area가 순서대로 초기화된다. (4) core missing/source mismatch/disabled/incompatible은 repository·host write 0과 정확한 수동 설치 안내를 유지한다. (5) 일반 capture mutation의 exact digest approval과 sole-writer coordinator는 유지한다. (6) skills, CLI, README, protocol, SSOT와 acceptance fixtures/tests가 일치한다. (7) core/decision/context-v1 full suites, distribution proof, product flow, wiki integrity, 독립 hard review와 frozen candidate final QA를 통과한다.

GitHub Issue/PR, push, publish, release, 자동 plugin 설치·활성화·업데이트, agent policy 자동 설치와 partial-state 자동 repair는 범위 밖이다. 구현·문서·테스트는 하나의 rollback unit으로 local-ff 통합한다.
