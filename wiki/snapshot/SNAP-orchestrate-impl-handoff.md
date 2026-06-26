---
title: orchestrate 구현 핸드오프 (approved 기획)
created_at: 2026-06-26
summary: 이슈트리 절차적 자동수행 오케스트레이터 — approved 설계 구현 착수용 핸드오프
tags: [orchestrate, handoff, task-github, impl]
type: snapshot
---
## 현재 논의

## 무엇

이슈트리(직렬·병렬 혼합) 절차적 자동수행 오케스트레이터. 루트이슈에서 시작해
task-github 규칙대로 트리 전체를 자동 실행. **정본 설계 = plugins/task-github/skills/orchestrate/PLAN.md** (2라운드 co-design 리뷰 approved, blocking 0).

## 확정 설계 핵심

- 역할 2개: root(main thread, 루프+컨테이너close+사람게이트 STOP) / worker×N(Agent 서브에이전트, 리프 start→run→done, 상태라벨 전담, 요약리턴). 오케스트레이터 서브에이전트 없음.
- 직렬/병렬 = blocked_by 엣지 + sub-issue 선언. 루프가 매 tick GitHub 재유도(캐싱 금지, GitHub=SoT).
- **opt-in 별도 스킬** — 기존 start/run/done 단일이슈 플로우 불변. orchestrate는 명시 호출시만.

## 리뷰로 확정된 결정 (구현시 준수)

- B1: leaf gear는 define/분해 시점 선결 → ready_leaves가 gear 싣고 루프가 spawn 전 gear:major STOP. 실행주체 = create_issue_tree.py child spec에 gear 필드 + execute에서 gh issue edit --add-label gear:{v}.
- B2: stuck[] = in-progress 리프 ∩ NOT(루프 self-spawn-set), 결정론적. 자동재시도 금지, 사람게이트 STOP. reason: prior_run|spawned_failed.
- S1: ready_leaves.py는 신규 walk를 처음부터 짜지 말 것 — open/SKILL.md GraphQL subIssues+subIssuesSummary, closeout.py(_parent/_open_blockers/_blocking/_detect_root_task) 재사용.
- S2: 컨테이너 완료 = subIssuesSummary{total,completed} total==completed. done_containers는 walk 부산물.
- C3: 컨테이너 close는 root가 done_containers로 직접. closeout은 root-close 감지만.
- D2 불변식: 상태라벨 전이 worker 전담, root는 컨테이너close+STOP만 → 라벨경합 0.
- 사람 게이트: review/merge/gear:major/stuck = 자동금지 STOP. 자동화 = gear:micro|normal 리프의 start/run/done.
- N1: subIssues 커서 페이지네이션 필수. N2: API 실패시 부분 ready-set 스폰 금지, 전체 STOP.
- D3: 진행 단조성(closed leaf+done_containers 증가) 가드 + max-iter backstop. 분기순서 stuck>done_containers>spawn.

## 배경

정본 설계 = plugins/task-github/skills/orchestrate/PLAN.md (main 9c9d188). 2라운드 co-design 리뷰 approved, blocking 0. 리뷰 핸드셰이크는 complete 후 폐기됨.

## 정해진 것



## 아직 열린 질문



## 다음에 볼 것

다른 세션이 이 스냅샷을 snapshot-load 후 구현 착수.
구현 carryover (PLAN §5 기준):
1. scripts/ready_leaves.py — root#→{ready[](gear포함), blocked[], stuck[], done_containers[], root_done}. open/closeout prior art 재사용. self-check fixture(§4 예시트리 tick0 ready=={1-1,2-1-1,2-2}).
2. skills/orchestrate/SKILL.md — root 루프(PLAN §5.2). worker=기존 start/run/done 재사용. 사람게이트.
3. create_issue_tree.py — child spec gear 필드 + gear 라벨 부여(B1 실행주체).
정본 설계는 PLAN.md를 직접 읽을 것.

## 관련 파일/문서

plugins/task-github/skills/orchestrate/PLAN.md

## 승격 후보
