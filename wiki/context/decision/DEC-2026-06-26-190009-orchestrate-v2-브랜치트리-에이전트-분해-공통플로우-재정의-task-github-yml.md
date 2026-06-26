---
title: orchestrate v2 — 브랜치트리 + 에이전트 분해 + 공통플로우 재정의 + .task-github.yml
created_at: 2026-06-26
summary: 이슈트리 자동수행 orchestrate를 공통 플로우(worktree·PR 필수) 위 브랜치트리 머지업 + 전문 에이전트 분해로 설계. 정본=PLAN.md r5.
tags: [orchestrate, task-github, architecture, branch-tree, config]
---

## 결정

orchestrate를 '공통 플로우(open→start→run→done→[review]→merge→close)를 이슈트리 위에서 자동 구동하는 레이어'로 설계한다. 핵심 결정: (1) 플로우는 모드 무관 공통 — worktree·PR 필수화(micro의 worktree/PR 스킵 폐기, 리뷰 스킵만 허용). (2) 이슈트리 미러 브랜치트리 + always-PR 머지업: 리프 PR→부모브랜치, 컨테이너 done→조부모, root→main. (3) 역할 분해 — 서브에이전트 work-agent(start→run→done까지, 머지 안 함)/reviewer-agent(session-review separate)/conflict-agent(test-gated); 오케스트레이터(메인스레드)는 결정론 머지·close·게이트·root완료 위키만. (4) verify=같은세션 자기검증/review=별개세션 독립검증, 위임은 .task-github.yml의 planning-tool/verify-tool/review-tool(비면 하네스). (5) 신규 .task-github.yml(워크스페이스 루트) 정본 config: mode(solo/team 글로벌), *-tool, orchestrate.review-mode(gear/all/skip, 우선순위 --review>config>gear). (6) orchestrate=solo 전용 게이트. (7) next 스킬 제거(status 중복). 정본 설계=plugins/task-github/skills/orchestrate/PLAN.md r5.

## 취지

사람이 세션을 열어 next→실행 반복하던 이슈트리 수동 드라이브를 절차적 자동수행으로. 동시에 코드 통합(머지)을 완료 플로우에 포함 — 컨테이너 브랜치=rollback/리뷰 단위, 충돌을 토픽 응집 형제끼리 일찍 국소 해소.

## 배경

초기 PLAN(r1~r4)은 '평평한 루프 + 단일 worker + 컨테이너=이슈상태, LLM 역할 하나'였고 기존 단일이슈 플로우 불변 전제였다. r5 co-design에서 (a) 플러그인이 이미 parent_branch/topology=stacked/Execution Contract/closeout --mode local 스캐폴딩 보유 확인 → 브랜치트리는 외래이식 아닌 레일 활성화, (b) always-PR이 micro 직접커밋 race·auto-close 미발화를 동시 해소, (c) 결정론=인라인/판단=서브에이전트 원칙으로 역할 분해, (d) 플로우를 모드 무관 공통으로 승격 = 플러그인 전체 규칙 변경임을 사용자가 명시. 단일역할(r1~r4 §3)·micro-light·CLAUDE.md 프로파일 프로즈를 개정.

## 고려한 대안

- **A. orchestrate-only 범위** — 새 규칙을 orchestrate 모드에만. 사람-드라이브와 발산해서 기각, 공통 플로우로.
- **B. sparse 브랜치트리** — rollback 단위(root+gear:major)에만 브랜치. 완료=머지업 일관성 위해 풀 미러 채택.
- **C. config를 CLAUDE.md/AGENTS.md 프로즈에 유지** — harness 중복·파싱 취약으로 `.task-github.yml` 별도 파일.
- **D. completion-agent 분리** — root 완료=루프 종료상태라 메인스레드 직접 처리로 폐기.
- 상세 근거는 트레이드오프 절 및 PLAN.md §11.2 논의 로그.

## 트레이드오프

기각: (1) 풀 1:1 브랜치 미러 모든 tier — 과분해, sparse(rollback 단위)는 논의했으나 사용자가 완료=머지업 일관성 위해 풀 미러 채택하되 컨테이너 자체는 결정론 머지로 경량화. (2) work-agent self-merge(micro) — 행동 분산·머지권한 2곳으로 더 복잡, 머지 단일지점(오케스트레이터)로. (3) 별도 completion-agent — root 완료=루프 종료상태라 메인스레드 직접. (4) gear 의미적 오분류 게이트(judgment_needed STOP) — B1 신뢰모델 유지하고 surfaced 대안으로 보류. (5) config를 CLAUDE.md 프로즈에 유지 — Claude+Codex 중복·스크립트 파싱 취약으로 .task-github.yml 별도 파일 채택. 비용: 플러그인 전체(start/run/done/merge/define/open + rules/DESIGN + 신규 config) 갱신 = major blast radius.

## 재평가 조건

v1(브랜치트리+always-PR+work-agent+결정론 머지/게이트, reviewer/conflict는 STOP 슬롯)와 v2(reviewer-agent=session-review, conflict-agent) staging. gear 의미적 오분류가 실제 문제화하면 judgment_needed STOP로 전환. multi-worker liveness/배치 barrier 비효율은 --max-workers 1 넘어설 때 재검. mode ambient 효과가 config 로드만으로 부족하면 재검.
