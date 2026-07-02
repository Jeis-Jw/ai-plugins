---
title: local closeout mode 유지 + worktree 격리 (all-PR 통합 대신)
created_at: 2026-07-02
summary: 컨테이너 머지업을 로컬 git merge로 유지하되 temp worktree로 격리해 메인 트리 checkout만 회피하는 대안. 로컬 머지 machinery+불변식 guard 유지 부담으로 반려하고 all-PR 통합을 채택.
tags: [task-github, orchestrate, branch-topology]
relations:
  intents: [INT-2026-05-29-104712-parallel-safe-headless-operation]
---

## 대안

closeout local mode(`git checkout parent && git merge`)를 유지하되 481 실제 apply를 temp worktree에서 수행하고, 595 pr-sync도 `git fetch origin base:base`로 바꿔 메인 워크트리 HEAD를 안 건드린다. 컨테이너 머지업은 여전히 로컬 통합(PR 없음) + Integration Ledger.

## 반려 사유

checkout 불변식은 지켜지나 (a) 로컬 머지 경로(run_local_closeout)+Integration Ledger를 계속 유지·테스트해야 하고, (b) 'HEAD가 trunk 불변'을 코드 구조가 아니라 guard/assert로 지켜야 해 regression 표면이 남는다. all-PR(B)은 로컬 머지 자체가 없어 불변식이 구조적으로 성립 — 유지 부담·표면이 더 작다.

## 이 대안의 취지

컨테이너 머지업 PR 노이즈를 피하고 로컬 Integration Ledger 감사 흔적을 보존하려는 취지. 매우 깊은 스택에서 PR 수 절감으로 유효.

## 재고 조건

깊은 스택서 컨테이너 머지업 PR 수가 과해 노이즈/rate-limit 문제화하면 이 worktree-격리 로컬 통합을 재채택 검토.
