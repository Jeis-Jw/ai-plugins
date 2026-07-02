---
title: orchestrated worker에 expected PR base 계약 강제
created_at: 2026-07-02
summary: stacked issue tree에서 leaf PR이 parent issue branch 대신 main을 base로 열리던 버그를, orchestrator→worker handoff에 expected PR base(BASE_BRANCH)를 명시 전달하고 orchestrated mode에서 base 누락 시 PR/worktree 생성 전 hard STOP하는 계약으로 차단한다. orchestrate v2(DEC-2026-06-26-190009) 브랜치트리 설계의 fallback 공백을 메운다.
tags: [task-github, orchestrate, branch-topology]
---

## 결정

orchestrator는 issue_base_branch로 계산한 expected PR base를 ORCHESTRATED=true BASE_BRANCH=... 로 start/run/done 모두에 명시 전달한다. run/done은 orchestrated인데 BASE_BRANCH가 비면 main으로 fallback하지 않고 PR/worktree 생성 전에 STOP한다. ensure_branch_chain(순수 함수)이 root→leaf 조상 branch 체인을 반환하고 호출부가 spawn 전에 parent/root branch를 ls-remote→branch→push로 보장한다.

## 취지

orchestrated stacked topology에서 leaf PR이 항상 parent issue branch를 base로 삼아 브랜치트리 머지업이 성립하게 한다. main 직접 타겟은 root branch 최종 closeout에서만.

## 배경

기존에 orchestrator는 expected base를 계산할 수 있었지만 handoff에 넘기지 않았고, run/done의 BASE_BRANCH fallback이 standalone과 orchestrated를 구분하지 않아 leaf가 main을 base로 삼았다(예: #83 parent #82 → task/issue-83->main). 계약을 명시화하고 fallback을 orchestrated에서 금지해 stacked topology 위반을 생성 시점에 차단한다.

## 고려한 대안

(1) Execution Contract JSON에 topology/branch_policy 필드 추가 — fallback 버그와 무관, 별도 스코프로 보류. (2) orchestrator_ops에 실제 git 실행 코드 추가 — 이 모듈은 순수 함수 전용 관례라 거부, git은 SKILL.md bash 절차에 유지. (3) base_branch→trunk_branch 함수/필드 rename — 일관성·호환 위해 거부, issue_base_branch가 이미 issue별 expected base 의미를 담아 문서 용어만 보정.

## 트레이드오프

orchestrated worker는 BASE_BRANCH 없이는 진행 불가(hard STOP)로 자율성이 준다. standalone은 영향 없음. shell guard는 마크다운 bash 절차라 실행 단위 테스트가 없어 dogfood로 검증.

## 재평가 조건

Execution Contract에 topology/branch_policy JSON 필드를 도입하면 이 handoff env 계약을 그 계약으로 흡수/대체할지 재평가.
