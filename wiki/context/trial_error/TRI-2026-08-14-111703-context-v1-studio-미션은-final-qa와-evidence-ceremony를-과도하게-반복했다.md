---
title: context v1 Studio 미션은 final QA와 evidence ceremony를 과도하게 반복했다
created_at: 2026-08-14
summary: 품질 게이트는 유효했지만 review 이전 full QA, 늦은 executable-criteria audit, 명령 단위 receipt가 214회 실행과 18 lane을 만들었다.
tags: [studio, workflow-economics, review-cycle, qa, evidence-reuse, context-v1]
search_terms: [studio economics, final QA, evidence ceremony, review cycle, receipt batching, executable criteria]
affects_paths: [plugins/studio/**, plugins/task-worker/**, .studio/**]
relations:
  decisions: [DEC-2026-07-10-133541-studio-최적화-우선순위-artifact-context-품질-hard-floor와-가중-효용, DEC-2026-07-10-133629-studio-실행-경계-mission-quality-context-gate-소유와-선택적-single-executor]
---

## 교훈

품질 hard floor와 독립 review는 유지하되 final-grade full QA는 hard review와 finding 수정 뒤 한 번만 수행한다. 구현 전에 모든 완료 조건이 production public surface를 직접 호출하는 executable selector를 갖는지 감사한다. 동일 HEAD의 관련 profile은 하나의 batch receipt로 묶고 tree 또는 digest equivalence가 입증된 경우 valid evidence를 재사용한다. Studio, task-worker, session-review, wiki는 같은 완료 사실을 복제하지 말고 하나의 IntegrationReceipt digest를 참조한다.

## 상황

context-core와 context-decision v1 미션은 최종 품질에는 성공했다. acceptance 43/43, supplemental QA 16/16 profile과 193 test invocation, hard review round 2 approved와 blocking 0이었다. 그러나 mission wall time은 591.8분, Studio lane 18개, unique agent 9개, task-worker run 7개였다. mission 시간창의 command receipt는 214건(pass 177, fail 33, error 4), profile 26종, 검토 HEAD 15개였고 core-suite 22회, context-v1-suite 20회, decision-suite 19회, git diff-check 22회 실행됐다. token과 model-call telemetry는 unavailable이므로 금액과 token ROI는 확정할 수 없다. 첫 root QA 169 invocation 뒤 hard review가 production preflight, two-stage direct capture, core-control exact apply validation, valid-only init noop의 blocker 4건을 찾아 수정 후 supplemental QA 193 invocation을 다시 수행했다. 관련 완료 작업은 TASK-2026-08-14-010606-context-core와-context-decision-v1-구현이다. fail과 error에는 의도한 tests-first RED 및 fixture와 protocol 교정도 포함되므로 전부 낭비로 간주하지 않는다.

## 피해야 할 것

hard review 전에 final-grade root QA와 verified 전이를 완료하는 것. acceptance registry 개수만 보고 budget, integrity, public adapter의 executable coverage를 충족했다고 간주하는 것. rebase나 tree-equivalent HEAD마다 full suite 전체를 fresh 실행하는 것. profile 하나마다 claim, receipt, evidence completion을 별도 ceremony로 만드는 것. 동일 QA, HEAD, gap 사실을 Studio receipt, task-worker evidence, session-review receipt, wiki TASK에 본문 복제하는 것. host capacity가 막힌 상태에서 같은 agent spawn을 반복하는 것.

## 대안 또는 우회

권장 순서는 executable-criteria audit, 3~4개 implementation track의 targeted red/green, 독립 hard review, finding 수정, final root full QA 1회, IntegrationReceipt 하나를 각 계층이 digest로 참조, closeout이다. P0/P1과 P2/P3의 독립 병렬화 및 worktree 격리는 유지한다. P4/P5와 distribution/integration은 동일 rollback unit이면 묶고, budget과 strict-integrity는 초기 acceptance coverage audit에 포함한다. 실행 계층은 affected-suite 또는 delta QA를 기본으로 하고 dependency나 shared-contract 변화 또는 불확실성이 있을 때만 full QA를 수행한다. 다음 run은 command receipt 214에서 100 안팎, wall time 25~40% 감소를 목표로 둘 수 있으나 model-call, token, elapsed telemetry를 함께 수집해야 검증 가능하다.

## 현재도 유효한가

2026-08-14 기준 유효하다. 과했던 것은 quality gate 자체가 아니라 순서, granularity, state replication이다. 독립 hard review는 실제 blocker 4건을 발견했으므로 유지한다. acceptance 43개, budget corpus, strict integrity, filesystem worktree 격리도 유지한다. 다음 개선에서는 품질 hard floor를 약화하지 않고 반복 QA, handoff, receipt ceremony만 줄여야 한다. 재평가 조건은 batch receipt나 evidence reuse가 결함 검출률을 낮추거나 shared-contract 변경에서 stale evidence를 통과시키는 경우다.
