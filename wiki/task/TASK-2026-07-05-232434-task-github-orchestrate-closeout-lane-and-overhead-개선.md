---
title: task-github orchestrate closeout lane and overhead 개선
created_at: 2026-07-05
summary: same-parent sibling closeout 병렬화로 인한 reverse-merge/reverify/ledger chatter를 줄이기 위해 implementation worker와 BASE_BRANCH별 closeout lane을 분리한다.
tags: [task-github, orchestrate, closeout, performance]
relations:
  intents: [INT-2026-05-29-104712-parallel-safe-headless-operation]
  decisions: [DEC-2026-07-02-224910-orchestrate-세리머니를-merge-edge-gear로-이동-분해를-payoff-원리로-재정의, DEC-2026-07-02-212109-merge-closeout를-all-pr로-통합하고-local-mode-제거, DEC-2026-07-03-012207-define에-co-design-뒤-challenge-review-게이트-config-driven-지시-설정-하네스-off-default]
  tasks: [Jeis-Jw/ai-plugins#51]
---

## 개요
task-github orchestrate에서 implementation worker 병렬성은 유지하되, 같은 `BASE_BRANCH`를 전진시키는 closeout 순간만 parent-ref 단위로 직렬화한다. PR은 review/audit log가 필요한 edge에서만 사용하고, review skip에서는 major도 verify 후 FF closeout으로 닫되 위험 분류와 skip 근거를 ledger/report에 남긴다.

## 근거
copymachine Wave 3~8 실행에서 같은 parent branch 아래 sibling leaf들이 동시에 closeout되며 parent reverse-merge, 재검증, ledger 보정, status chatter가 반복됐다. 낭비의 원인은 구현 병렬화가 아니라 merge target ref 병렬화였으므로, lock key를 container node가 아닌 `BASE_BRANCH`로 둔다.

## 범위와 완료 기준
- ledger가 `ready_for_closeout`, `closeout_started`, `closeout_done`, `closeout_failed` 같은 closeout queue events를 표현한다.
- orchestrated worker는 review가 필요 없으면 모든 gear를 `ready_for_closeout`으로 넘기고, review가 필요하면 PR/review path로 넘긴다.
- closeout scheduler는 `BASE_BRANCH`별 FIFO one-shot closeout lane만 dispatch하고, 같은 base의 pending item은 이전 closeout 완료 후 re-tick에서 처리한다.
- ledger compact/summary output과 worker final report contract를 줄여 반복 출력 비용을 낮춘다.
- 실패 복구는 `resume-closeout` 또는 동등한 idempotent closeout path로 재시도 가능해야 한다.
- task-github plugin version, docs, tests, distribution manifests가 함께 갱신된다.
