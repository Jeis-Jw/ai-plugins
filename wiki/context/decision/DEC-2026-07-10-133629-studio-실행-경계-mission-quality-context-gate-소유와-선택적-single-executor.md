---
title: Studio 실행 경계 — mission·quality·context·gate 소유와 선택적 single executor
created_at: 2026-07-10
summary: Studio가 mission·quality·context·owner gate를 소유하고 track별 외부 workflow는 단일 선택 executor로 위임한다. task-github와 wiki-markdown은 각각 reference adapter와 optional promotion provider이며 hard dependency가 아니다.
tags: [studio, architecture, context, workflow-adapter, plugin-design]
relations:
  intents: [INT-2026-07-08-164552-studio-살아있는-에이전트-팀]
  rejected_decisions: [REJ-2026-07-08-164619-studio를-이슈트리-오케스트레이션-확장으로-만드는-안]
---

## 결정

Studio는 mission 계약, QualityPlan, Context Kernel, track 상태, evidence 기반 완료 판정, owner gate의 정본을 소유한다. 실행은 track마다 정확히 하나의 executor lease만 허용하며 studio-native 또는 external-workflow 중 하나를 선택한다. 외부 workflow에는 WorkPacket으로 목적·완료조건·필요 맥락·예산·gate를 전달하고 ResultEnvelope로 결과물 reference·verification·ContextDelta·비용·blocker를 회수한다. task-github를 첫 reference adapter로 제공하되 외부 issue/branch/PR 상태를 Studio에 복제하지 않고 안정적인 reference와 capability snapshot만 보관한다. wiki-markdown은 승인된 decision·rejected alternative·SSOT 승격을 위한 optional promotion provider이며, 없을 때는 로컬 outbox에 후보를 보존한다. 두 플러그인 모두 Studio의 hard dependency가 아니다.

## 취지

Studio의 미션 드리븐 팀 모델과 품질·맥락 수명주기를 유지하면서, 코드 배송이 무거운 track만 검증된 외부 실행 레일에 위임한다. executor가 바뀌어도 owner가 보는 mission, 품질 기준, 맥락, gate 계약은 일관되게 유지한다.

## 배경

기존 Studio 코어 결정은 작업형 pairing과 worktree 격리를 정의했고, 기존 REJ는 Studio 전체를 이슈트리 순차 처리기로 환원하는 안을 기각하면서 코드 중심 대형 미션에는 작업형 run의 선택적 백엔드 위임을 재고 조건으로 남겼다. 이번 결정은 바로 그 재고 조건을 충족한다. Studio를 task-github 위에 올리거나 일의 정의를 외부로 넘기지 않고, Studio가 정의한 track의 실행만 adapter를 통해 위임한다. 따라서 REJ의 반려 사유인 일의 정의 외부화, producer의 처리 루프 매몰, 상호작용의 파이프라인 환원을 되살리지 않는다.

## 고려한 대안

Studio 전체를 task-github orchestrate의 미션 레이어로 만드는 안은 기존 REJ 사유와 충돌해 기각한다. 외부 workflow 상태를 Studio board에 전부 복제하는 안은 이중 정본과 동기화 오류를 만들어 기각한다. 한 track에 native와 external executor를 동시에 허용하는 안은 중복 실행·상충 결과·예산 이중 사용 위험 때문에 기각한다. wiki-markdown을 필수 장기 기억 저장소로 두는 안은 설치 환경을 제한하므로 채택하지 않는다. 반대로 외부 실행·영구 승격 확장점 자체를 두지 않는 안은 대형 코드 mission의 배송 레일과 cross-mission 지식 재사용을 포기하므로 채택하지 않는다.

## 트레이드오프

adapter 계약과 capability preflight가 추가되어 구현 표면이 늘고, 외부 workflow의 세부 상태를 복제하지 않으므로 Studio 단독 화면에서 완전한 진행률을 보여주기 어렵다. reference가 stale해질 수 있어 실행 직전 capability·reference 재검증이 필요하다. wiki provider가 없으면 mission 간 장기 지식 재사용은 보장하지 않고 로컬 outbox handoff까지만 지원한다. single executor lease는 안전하지만 executor 전환 시 명시적 release·handoff가 필요하다.

## 재평가 조건

외부 workflow가 mission 정의나 품질 판정까지 소유해야만 해결되는 실제 사례가 반복되면 소유권 경계를 재검토한다. reference-only 연동으로 운영에 필요한 상태를 복원할 수 없으면 최소 projection을 추가하되 외부 정본을 복제하지 않는 원칙을 유지한다. 두 종류를 넘는 adapter에서 WorkPacket·ResultEnvelope 공통분모가 지나치게 약해지면 adapter별 extension contract를 도입한다. task-github 미설치 환경에서 native 실행이 정상 동작하지 않거나 wiki 미설치 시 context 후보가 유실되면 optional dependency 설계를 실패로 보고 수정한다.
