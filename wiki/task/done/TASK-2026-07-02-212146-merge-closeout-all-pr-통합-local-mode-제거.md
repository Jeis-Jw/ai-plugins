---
title: merge closeout all-PR 통합 · local mode 제거
created_at: 2026-07-02
summary: orchestrate 컨테이너/epic 머지업을 PR화하고 local closeout mode+Integration Ledger를 제거하는 업무. DEC-2026-07-02-212109-merge-closeout를-all-pr로-통합하고-local-mode-제거 근거, 병렬·헤드리스 안전성 취지.
tags: [task-github, orchestrate, branch-topology]
relations:
  intents: [INT-2026-05-29-104712-parallel-safe-headless-operation]
  decisions: [DEC-2026-07-02-212109-merge-closeout를-all-pr로-통합하고-local-mode-제거]
  tasks: [Jeis-Jw/ai-plugins#35]
---

## 개요

orchestrate 머지 경로를 all-PR로 통일해 오케스트레이션 중 사령관의 메인 워크트리 HEAD가 trunk를 벗어나지 않게 한다. 상세 실행·완료 체크는 연결된 루트 이슈에 둔다.

## 근거

[[DEC-2026-07-02-212109-merge-closeout를-all-pr로-통합하고-local-mode-제거]]가 결정. v2 always-PR 원칙([[DEC-2026-06-26-190009-orchestrate-v2-브랜치트리-에이전트-분해-공통플로우-재정의-task-github-yml]])을 컨테이너 머지업까지 실현하고, [[INT-2026-05-29-104712-parallel-safe-headless-operation]] 병렬·헤드리스 안전성을 로컬 머지 제거로 구조적으로 보장한다.

## 범위와 완료 기준

범위: closeout.py에서 로컬 `git checkout`/`git merge` 경로(run_local_closeout) 제거, pr-sync를 `git fetch origin base:base`로, orchestrate container_done을 PR 생성+gh pr merge로, merge/orchestrate/define SKILL·workflow.md의 local-merge/Integration Ledger 서술 정리, tests 갱신. 완료 기준: pytest plugins/task-github/tests 그린 + dogfood stacked 트리 orchestrate에서 머지 tick마다 `git symbolic-ref --short HEAD`==main 유지.
