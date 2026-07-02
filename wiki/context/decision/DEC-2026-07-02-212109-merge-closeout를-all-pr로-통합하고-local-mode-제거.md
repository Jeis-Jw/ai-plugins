---
title: merge closeout를 all-PR로 통합하고 local mode 제거
created_at: 2026-07-02
summary: orchestrate 컨테이너/epic 머지업을 PR화(gh pr create+merge)하고 run_local_closeout(local mode)+Integration Ledger를 제거해, 오케스트레이션 중 메인 워크트리 HEAD가 trunk를 벗어나지 않음을 구조적으로 보장한다. v2(DEC-2026-06-26-190009-orchestrate-v2-브랜치트리-에이전트-분해-공통플로우-재정의-task-github-yml)의 always-PR 원칙을 컨테이너 머지업까지 실현.
tags: [task-github, orchestrate, branch-topology, architecture]
relations:
  intents: [INT-2026-05-29-104712-parallel-safe-headless-operation]
  rejected_decisions: [REJ-2026-07-02-212018-local-closeout-mode-유지-worktree-격리-all-pr-통합-대신]
---

## 결정

컨테이너/epic 머지업도 리프처럼 PR로 처리한다 — orchestrate container_done이 `gh pr create --base task/issue-{parent} --head task/issue-{container}` 후 `gh pr merge`. closeout.py의 run_local_closeout(--mode local: `git checkout parent && git merge`)와 stacked Integration Ledger를 제거한다. pr-mode 사후 로컬 base 갱신은 `git checkout base && git pull` 대신 `git fetch origin base:base`(base==현재 HEAD면 `git pull --ff-only`)로 바꿔 checkout을 없앤다. 결과: 모든 머지가 remote(gh pr merge)로 균일해지고, 로컬 git merge/checkout이 사라져 메인 워크트리 HEAD가 base_branch(trunk)를 벗어나지 않음이 코드 구조로 보장된다.

## 취지

[[INT-2026-05-29-104712-parallel-safe-headless-operation]] 병렬·헤드리스 안전성. 오케스트레이터가 백그라운드로 여러 워크트리를 돌리는 동안 사령관의 메인 워크트리가 임의 브랜치로 checkout되지 않아야 한다. 로컬 머지를 제거하면 이 불변식이 guard가 아니라 '부재'로 성립한다. 동시에 [[DEC-2026-06-26-190009-orchestrate-v2-브랜치트리-에이전트-분해-공통플로우-재정의-task-github-yml]]가 세운 always-PR 머지업 원칙(리프 PR→부모, 컨테이너→조부모, root→main)을 컨테이너 단계까지 일관 실현한다.

## 배경

v2([[DEC-2026-06-26-190009-orchestrate-v2-브랜치트리-에이전트-분해-공통플로우-재정의-task-github-yml]])는 리프 always-PR과 브랜치트리 머지업을 세우면서 기존 `closeout --mode local` 스캐폴딩을 '레일 활성화'로 재사용했다. 그 결과 리프는 PR로 머지되지만(done:71 gh pr create) epic/컨테이너는 worker/PR을 받지 않아 컨테이너 머지업만 로컬 git merge(closeout.py:481)로 남았다. 이 로컬 경로 + pr-mode 사후 sync(closeout.py:595)의 checkout이 오케스트레이션 중 메인 트리 HEAD를 parent 브랜치로 옮기는 유일 원인이었다. leaf base를 parent 브랜치로 고정한 expected-pr-base 계약([[DEC-2026-07-02-205231-orchestrated-worker에-expected-pr-base-계약-강제]])과 같은 브랜치트리 정합 계열의 후속.

## 고려한 대안

[[REJ-2026-07-02-212018-local-closeout-mode-유지-worktree-격리-all-pr-통합-대신]] — local mode 유지 + 481 temp worktree 격리(checkout만 회피). 로컬 머지 machinery+불변식 guard 유지 부담으로 반려.

## 트레이드오프

얻음: 머지 경로 단일화(remote만), 메인 트리 HEAD 불변의 구조적 보장, run_local_closeout+Integration Ledger 삭제로 코드·테스트 표면 축소. 포기: 컨테이너 머지업마다 PR 1개 생성(깊은 스택서 PR 수 증가), 로컬 Integration Ledger 감사 흔적(대신 PR 이력이 통합 로그). blast radius = closeout.py + merge/orchestrate/define SKILL + workflow.md + tests(중간, v2 전체보다 작음).

## 재평가 조건

깊은 스택(컨테이너 다수)에서 머지업 PR 수가 노이즈/GitHub rate-limit으로 문제화하면 [[REJ-2026-07-02-212018-local-closeout-mode-유지-worktree-격리-all-pr-통합-대신]]의 worktree-격리 로컬 통합을 재검. Execution Contract에 topology/branch_policy JSON 필드가 도입되면 closeout_mode 필드 정리를 그 계약으로 흡수할지 재평가.
