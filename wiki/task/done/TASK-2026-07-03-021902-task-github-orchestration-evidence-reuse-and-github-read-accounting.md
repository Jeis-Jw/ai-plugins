---
title: task-github orchestration evidence 재사용과 GitHub 조회 계측 개선
created_at: 2026-07-03
summary: ledger v3 evidence 재사용으로 orchestration의 반복 GitHub 조회와 상위 node drift 재검증을 줄인다.
tags: [task-github, orchestrate, ledger, evidence, workflow-efficiency]
relations:
  decisions: [DEC-2026-06-26-190009-orchestrate-v2-브랜치트리-에이전트-분해-공통플로우-재정의-task-github-yml, DEC-2026-07-02-212109-merge-closeout를-all-pr로-통합하고-local-mode-제거, DEC-2026-07-02-224910-orchestrate-세리머니를-merge-edge-gear로-이동-분해를-payoff-원리로-재정의]
  tasks: [Jeis-Jw/ai-plugins#39]
---

## 개요

`SNAP-task-github-orchestration-evidence-reuse-plan`을 실행 가능한 GitHub issue tree로 전환한다. 핵심은 GitHub SoT를 유지하면서 orchestration tick 안의 불필요한 read-after-write 조회와 상위 merge의 반복 `changed-path-stale` 검증을 줄이는 것이다.

이 task node는 업무 루트 단위 1개이며, 리프별 task node는 만들지 않는다.

## 근거

근거:
- #81 orchestration 경험에서 leaf/container/root merge 과정의 GitHub 재조회와 반복 wiki drift 검증 비용이 컸다.
- `SNAP-task-github-orchestration-evidence-reuse-plan`에서 ledger v3, read accounting, merge/gate evidence 분리, drift surface hash, PR head pinning, conservative fallback이 기획안으로 정리됐다.
- 기존 결정 `DEC-2026-06-26-190009`, `DEC-2026-07-02-212109`, `DEC-2026-07-02-224910`을 보존해야 한다. 즉 branch-tree/orchestrate v2, main worktree HEAD invariant, merge-edge gear 모델은 되돌리지 않는다.

## 범위와 완료 기준

GitHub issue tree로 `task-github` orchestration 비용 효율 개선을 구현한다. 안전 장치를 줄이는 작업이 아니라, 이미 검증된 사실을 ledger evidence로 승격해 상위 node가 엄격한 조건 아래 재사용하도록 만드는 작업이다.

완료 기준:
- GitHub read boundary와 reason enum이 orchestrate/merge 문서와 실행 helper에 반영된다.
- ledger v3가 `github_reads`, `read_decisions`, `merge_evidence`, `gate_evidence`를 분리해 저장한다.
- v2 ledger와 기존 `issues[N].ff_merged` consumer가 회귀하지 않는다.
- 상위/root merge에서 global wiki integrity strict는 유지되고, `changed-path-stale`만 valid child evidence 기준으로 scope down된다.
- drift surface hash mismatch, PR head mismatch, parent overlap, version drift, missing evidence는 full fallback 또는 STOP으로 처리된다.
- fixture로 정상 path의 GitHub read 수와 repeated `changed-path-stale` target 감소를 증명하고, invalid path에서는 감소하지 않음을 증명한다.

검증:
- `python3 -m unittest plugins/task-github/tests/test_orchestrate_ready_leaves.py plugins/task-github/tests/test_orchestrator_ops.py plugins/task-github/tests/test_closeout.py`
- 추가되는 신규 unit/fixture tests
- `python3 plugins/wiki-markdown/skills/wiki/scripts/wiki_cli.py refresh --level integrity --strict --json`
- `git diff --check`

영향 경로:
- `plugins/task-github/skills/orchestrate/**`
- `plugins/task-github/skills/merge/**`
- `plugins/task-github/skills/done/SKILL.md`
- `plugins/task-github/rules/quality-gates.md`
- `plugins/task-github/README.md`
- `plugins/task-github/tests/**`
