---
title: Studio Native Crew Lifecycle과 Persistent Brainstorm Production 적용
created_at: 2026-07-28
summary: Studio 0.10.0의 read-only persistent brainstorm를 Production으로 승격하고 모든 native crew의 인스턴스 수명을 작업 단위 기준으로 관리한다.
tags: [studio, persistent-crew, native-subagent, production]
relations:
  ssot: [studio-plugin]
  decisions: [DEC-2026-07-27-020408-studio-brainstorm을-workflow-scoped-persistent-crew로-운영]
  tasks: [Jeis-Jw/ai-plugins#79]
---

## 개요

Read-only brainstorm reducer/store를 pinned bundled Codex app-server에 연결한다. 동시에
brainstorm, development/pairing, QA, review, critic 등 모든 native crew에 역할 기반
배정·작업 단위 기준 instance lifecycle·original-handle continuation 계약을 적용한다.
별도 write runtime은 만들지 않고 기존 Workflow/Runner, task-worker, task-github,
worktree, execution-control을 그대로 사용한다.

## 완료 기준

- 인스턴스는 명확한 단일 역할로 동적 작업 단위에 배정하며 최초 배정에서만 spawn한다.
- 같은 작업 단위의 후속 의견교류, peer/review 대기, feedback 대응, 재작업, 재검증은
  original physical handle에 follow-up한다.
- `waiting-for-peer`와 `rework`는 active다. 담당 완료조건 충족과 outstanding
  peer/review interaction 0이 함께 확인될 때만 terminal/cleanup한다.
- 독립 reviewer는 별도 역할·작업 단위·인스턴스로 배정하고 자기 review 단위가 끝날 때까지
  유지한다.
- Producer는 owner intent·범위·완료조건과 role↔instance↔work-unit mapping을 관리하고,
  dependency·질문·산출물·review feedback을 original instance 사이에 왜곡 없이 relay한다.
  산출물을 직접 만들거나 crew 판단을 대신 합성하지 않는다.
- read-only brainstorm Production은 exact admission·same-handle follow-up·cleanup 계약을
  유지한다. continuation handle을 제공하지 않는 외부 executor/isolated Runner에는
  persistence를 주장하지 않는다.

## 범위 제외

새 app-server write runtime, sandbox/store/patch helper/WorkUnit controller·claim·canary·
benchmark, 고정 A/B topology, Runner 제거, PCMS 제품 변경, 민감 ContextPack 전송,
cross-work-unit memory, 공개 배포는 제외한다.

## 검증 계약

- 관련 문서와 routing 계약이 brainstorm-only lifecycle 또는 개발 run마다 replacement
  spawn을 지시하지 않는지 확인한다.
- read-only persistent brainstorm broker/controller 회귀를 유지한다.
- sealed replay는 full 21 calls 대비 standard 13 calls(38.10%), criterion floor 100,
  quality degradation 0%를 검증한다. 이는 profile 효율 근거이며 외부 executor persistence,
  wall-time, token 절감을 주장하지 않는다.
