---
title: Studio native crew를 역할 기반으로 배정하고 작업 단위 기준으로 유지
created_at: 2026-07-27
summary: 역할별 original instance를 작업 단위 완료까지 유지하고 후속 의견·검수·재작업을 같은 handle에 전달한다.
tags: [studio, native-crew, persistent-crew, orchestration]
relations:
  rejected_decisions: [REJ-2026-07-08-164619-crew-상주-에이전트-sendmessage-지속-대화-방식]
  ssot: [studio-plugin]
---

## 결정

Studio의 모든 native crew subagent는 **역할 기반으로 인스턴스를 배정하고, 그 인스턴스의
수명·지속·종료를 배정된 작업 단위 기준으로 관리**한다. 인스턴스 하나는 명확한 단일
역할을 맡는다. 같은 역할이라도 독립 작업 단위가 여러 개면 별도 인스턴스를 둘 수 있지만
인원수·역할명·A/B 같은 예시 이름을 topology로 고정하지 않는다.

최초 배정에서만 spawn한다. 같은 작업 단위의 후속 의견교류, 다른 crew 검수 대기,
검수 결과 대응, 재작업, 재검증은 original physical handle에 follow-up한다.
`waiting-for-peer`와 `rework`는 active이며 회의·turn·run 종료는 terminal 사유가 아니다.
담당 완료조건 충족과 outstanding peer/review interaction 0이 함께 확인될 때만
terminal로 전이하고 cleanup한다.

독립 판단이 필요한 reviewer는 별도 역할·작업 단위·인스턴스로 배정한다. reviewer도 자기
review 단위가 끝날 때까지 유지한다. 예를 들어 서로 다른 작업 단위를 맡은 같은 developer
역할 인스턴스가 둘일 수 있다. 한 단위의 review finding은 그 단위의 original developer에게
follow-up하고 같은 review 흐름으로 재확인한다. review 대기 중 developer도 active다.

이 lifecycle은 brainstorm, development/pairing, QA, review, critic 등 모든 native crew에
공통이다. 다만 현재 별도 Production persistence 구현은 verified native host의 read-only
brainstorm controller에 한정한다. 기존 Workflow/Runner, task-worker, task-github,
worktree, execution-control을 그대로 사용하며 continuation handle을 제공하지 않는 외부
executor에는 persistence를 주장하지 않는다.

## Producer 책임

Producer는 owner 요구사항의 총괄 책임자이자 Studio control plane/메시지 중계자다.
owner intent·범위·완료조건을 정본으로 유지하고 상황에 맞는 role/crew instance를 작업
단위에 배정한다. role↔instance↔work-unit mapping과 active/waiting-for-peer/rework/
terminal 상태를 관리하며 dependency·질문·crew 산출물·review feedback을 해당 original
instance 사이에 왜곡 없이 relay한다.

Producer는 전체 진행·대기·완료 상태와 gate를 owner와 대화하고 내부 workflow가 owner
요구를 재정의하거나 범위를 확대하지 못하게 한다. 개발·리뷰 산출물을 직접 만들거나 crew
판단을 대신 합성하지 않는다.

## 구현 경계

- `persistent_brainstorm_broker.mjs` reducer가 brainstorm phase/action/barrier와 actor
  lifecycle의 정본이며 Producer는 action/result를 exact relay한다.
- read-only brainstorm는 최초 action에서만 spawn하고 이후 original handle에 follow-up한다.
- 새 write runtime, sandbox/store/patch helper, WorkUnit controller·claim·canary·benchmark를
  추가하지 않는다.
- task-worker의 decomposition·ready-set·worktree·verification·integration gate와
  task-github의 GitHub projection/delivery 책임을 흡수하지 않는다.

## 재평가 조건

- native host가 original-handle continuation을 안정적으로 제공하지 못함.
- role↔instance↔work-unit mapping이 owner 완료조건 또는 review independence를 훼손함.
- terminal gate가 outstanding peer/review interaction을 누락해 조기 cleanup함.
