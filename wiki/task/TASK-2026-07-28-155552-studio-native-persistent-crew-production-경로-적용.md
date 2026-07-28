---
title: Studio Native Persistent Crew Production 경로 적용
created_at: 2026-07-28
summary: Studio 0.9.0의 read-only persistent brainstorm를 검증된 Codex native host adapter와 production admission 경로로 승격한다.
tags: [studio, persistent-crew, native-subagent, production]
relations:
  ssot: [studio-plugin]
  decisions: [DEC-2026-07-27-020408-studio-brainstorm을-workflow-scoped-persistent-crew로-운영]
  tasks: [Jeis-Jw/ai-plugins#79]
---

## 개요

현재 deterministic canary reducer/store/driver와 same-handle lifecycle을 실제 Codex native collaboration host에 연결한다. Producer는 canonical state를 수정하지 않고 opaque ref와 action/receipt만 relay하며, 구현·검증·통합 산출물은 별도 crew가 격리 worktree에서 수행한다.

## 근거

기존 결정은 verified spawn/followup/wait_barrier/interrupt_cancel/structured_result가 있는 read-only brainstorm에만 workflow-scoped persistence를 허용한다. 현재 main c5dab461의 production default는 isolated Codex Runner이며, caller self-declared capability와 deterministic harness만으로는 production admission 근거가 부족하다. 첨부 owner 작업 의뢰가 fresh capability provenance, host lifecycle, fallback fence, live synthetic canary, 독립 audit closure를 완료 조건으로 확정했다.

## 범위와 완료 기준

단일 major rollback unit으로 capability provenance와 freshness/digest/runtime binding, native host action adapter, bounded concurrency와 exact structured-result repair, cancellation/recovery/late-result fence, producer routing 및 pre-dispatch Runner fallback을 구현한다. pairing/write native 전환, Runner 제거, PCMS 제품 변경, 민감 ContextPack 전송, 공개 배포는 제외한다. 기존·추가 deterministic tests, 합성 비민감 fixture의 fresh native live canary, 30%/5% 품질 게이트, tokens null/unavailable 보존, wiki integrity/drift, 독립 리뷰, version/manifest/docs 정합성을 모두 통과해야 release-ready다.
