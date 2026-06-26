---
title: orchestrate 구현 핸드오프 (approved 기획 + fast review 보정)
created_at: 2026-06-26
summary: 이슈트리 절차적 자동수행 오케스트레이터 — approved 설계에 fast self-review 보정을 반영한 구현 착수용 핸드오프
tags: [orchestrate, handoff, task-github, impl]
type: snapshot
---
## 현재 논의

## 무엇

이슈트리(직렬·병렬 혼합) 절차적 자동수행 오케스트레이터. 루트이슈에서 시작해
task-github 규칙대로 트리 전체를 자동 실행. **정본 설계 = plugins/task-github/skills/orchestrate/PLAN.md** (2라운드 co-design 리뷰 approved, 이후 fast self-review blocker 1개 반영).

## 확정 설계 핵심

- 역할 2개: root(main thread, 루프+컨테이너close+사람게이트 STOP) / worker×N(Agent 서브에이전트, 리프 start→run→done, 상태라벨 전담, 요약리턴). 오케스트레이터 서브에이전트 없음.
- 직렬/병렬 = blocked_by 엣지 + sub-issue 선언. 루프가 매 tick GitHub 재유도(캐싱 금지, GitHub=SoT).
- **opt-in 별도 스킬** — 기존 start/run/done 단일이슈 플로우 불변. orchestrate는 명시 호출시만.

## 리뷰로 확정된 결정 (구현시 준수)

- B1: leaf gear는 define/분해 시점 선결 → ready_leaves가 gear 싣고 루프가 spawn 전 gear:major STOP. 실행주체 = create_issue_tree.py child spec에 gear 필드 + execute에서 gh issue edit --add-label gear:{v}. missing/multiple/unknown gear는 default 없이 invalid_gear[] STOP. define/SKILL.md뿐 아니라 DESIGN.md/start/SKILL.md의 gear 부여 책임 문구도 같은 커밋에서 예외 정렬.
- B2: stuck[] = in-progress 리프 ∩ NOT(active spawned worker), 결정론적. GitHub만으로는 판정 불가하므로 root 루프가 spawned_set/failed_set을 ready_leaves.py에 넘긴다. worker spawn은 tick barrier: batch가 return/fail/timeout될 때까지 다음 ready_leaves tick 금지. timeout/fail은 failed_set에 넣고 STOP 브리핑. 자동재시도 금지. reason: prior_run|spawned_failed.
- S1: ready_leaves.py는 신규 walk를 처음부터 짜지 말 것 — open/SKILL.md GraphQL subIssues+subIssuesSummary, closeout.py(_parent/_open_blockers/_blocking/_detect_root_task) 재사용.
- S2: 컨테이너 완료 = subIssuesSummary{total,completed} total==completed. done_containers는 walk 부산물.
- C3: 컨테이너 close는 root가 done_containers로 직접. closeout.py 위임 아님. close 직전 열린 blocked_by/dependency 조회 실패 guard를 통과해야 하며, 실패하면 STOP 브리핑. close가 1개라도 발생하면 같은 tick의 ready[]는 버리고 re-tick. closeout은 root-close 감지만.
- D2 불변식: 상태라벨 전이 worker 전담, root는 컨테이너close+STOP만 → 라벨경합 0.
- 사람 게이트: review/merge/gear:major/invalid_gear/stuck = 자동금지 STOP. 자동화 = gear:micro|normal 리프의 start/run/done.
- N1: subIssues 커서 페이지네이션 필수. N2: API 실패시 부분 ready-set 스폰 금지, `errors[]`/`stop_reason`으로 드러내고 전체 STOP.
- N3: orchestrate/gear-bearing tree는 모든 `blocked_by` dependency 생성 성공이 선행조건. create_issue_tree.py의 comment-only fallback은 수동 define에는 남겨도, orchestrate 대상에서는 `dep_create_failed`로 실패 처리하고 non-runnable로 둔다.
- D3: 진행 단조성(closed leaf+done_containers 증가) 가드 + max-iter backstop. 분기순서 stuck>done_containers>review_waiting>invalid_gear>gear:major>spawn. v1 spawn은 `--max-workers 1` 기본, foreground/in-memory 실행만 지원(`/loop` unattended와 persistent ledger 제외).

## 배경

정본 설계 = plugins/task-github/skills/orchestrate/PLAN.md. 2라운드 co-design 리뷰 approved 뒤, 구현 전 fast self-review와 explore co-design feedback을 반영해 PLAN r3로 보정함.

## 정해진 것



## 아직 열린 질문



## 다음에 볼 것

다른 세션이 이 스냅샷을 snapshot-load 후 구현 착수.
구현 carryover (PLAN §5 기준):
1. skills/orchestrate/scripts/ready_leaves.py — root# + spawned_set/failed_set → {ok/errors|stop_reason, ready[](gear포함), blocked[], review_waiting[], invalid_gear[], stuck[], done_containers[], root_done}. root issue는 done_containers[] 제외. open/closeout prior art 재사용. v1 API scope는 blocked_by 중심. self-check는 tick0 ready, invalid_gear, dependency API failure, done_containers+ready branch-priority 4개.
2. skills/orchestrate/SKILL.md — root 루프(PLAN §5.2). worker=기존 start/run/done 재사용. 사람게이트. worker batch tick barrier, timeout/fail STOP, `--max-workers 1` 기본. container close 후 re-tick.
3. create_issue_tree.py — child spec gear 필드 + gear 라벨 부여(B1 실행주체). orchestrate/gear-bearing tree에서는 dependency 생성 실패를 comment fallback으로 넘기지 말고 `dep_create_failed`로 실패 처리. 같은 커밋에서 define/SKILL.md spec 예시, DESIGN.md, start/SKILL.md의 기존 gear 책임 문구도 orchestrate tree 예외로 갱신.
정본 설계는 PLAN.md를 직접 읽을 것.

## 관련 파일/문서

plugins/task-github/skills/orchestrate/PLAN.md

## 승격 후보
