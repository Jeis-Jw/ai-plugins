---
title: task-github 효율·연계 개선 (4-unit A→B→C→D)
created_at: 2026-06-26
summary: session-review 3라운드 합의로 lock된 task-github 개선 작업지시. 대전제(플러그인 독립 + TASK↔ROOT 단일 브릿지) 유지. A→B→C→D 순서. 상세 근거: docs/task-github-improvement-directions.md
tags: [task-github, integration, wiki-bridge, self-merge]
---

## 개요

`task-github` 플러그인을 더 편하고·효율적이고·위키와 잘 연계되도록 개선한다. 4개 얇은 unit으로 절단했고 구현 순서는 **A → B → C → D**다.

| unit | 무엇 | 해결 |
|------|------|------|
| **A** resolve / context-bundle | 링크 리졸버 1개 → `{issue,root,wiki_task,topology,gate,parent_branch,blockers,downstream,worktree_path}` JSON read-model. open/start/done/merge/status 공유 → 반복 gh/wiki 조회 + regex 복붙 제거. 링크 정합 불변식 검사 포함. | 위키↔task 연계 약점(토대) |
| **B** Execution Contract + config materialization | integration 전략(topology/gate/parent_branch/leaf_policy/required_checks/closeout_mode)을 root 이슈 생성 시 **parser-safe fenced block**(+ `schema_version` + stable keys + unknown-key ignore)으로 materialize. profile+gear 자동 추천 기본값, per-work flag override. contract 부재 시 A가 `null`+`default_source`. | self/통합 "편히 설정", 재추론 drift 차단 |
| **C** local / stacked integration closeout | `closeout.py` → `--mode pr\|local` 일반화(공통 출력 `{issue,root,root_closed,task_to_complete,downstream,merged}`). local-merge는 **merge simulation**(임시 clean checkout에서 B의 `required_checks` + `changed-path-stale` + integrity gate 통과 후에만 반영) 필수. leaf 검증 비우지 않음 + `leaf_policy` rule table(비가역/DB/public API/security/data-loss → PR·hard self-flow 강제). 리프→컨테이너 로컬, 컨테이너→main 단일 release gate. Integration Ledger(stacked+local 한정, root issue append-only comment + stable marker/event block). | self 로컬머지 + 통합 브랜치 |
| **D** status / next + doctor / reconcile | `status`/`next`(ready/blocked leaf·review needed·bridge mismatch·closeout pending·**다음 행동 1개**, A read-model 재사용). `doctor --json` = diagnose-only(read), `reconcile --apply`/`doctor --fix` = explicit mutation(wiki CLI만), open/merge opportunistic reconcile도 dry-run→apply gate. label bootstrap·nested repo guard 흡수. | 효율·네비게이션 |

branch 명명: root=`task/root-{ROOT}`, leaf=`task/issue-{LEAF}`. dependency 정본은 GitHub Issue dependencies, branch ancestry는 실행 편의 정보.

## 근거

session-review 3라운드 co-design 합의(explore → converge → confirm)로 **Codex `approved`** 확정. 경로: round1 approved+15아이디어 → round2 4-unit 재구성·blocking 1(doctor 안전계약) → round3 confirm approved(lock).

**대전제(불변)**: ① 두 플러그인 독립 동작(`wiki-markdown` ⊥ `task-github`, 역방향 의존 금지) ② 유일 브릿지 = wiki `TASK` 노드 ↔ github `ROOT` 이슈 (1:1).

**red line**: branch/worktree/PR metadata가 wiki `TASK`를 대체 금지, wiki가 GitHub 상태 직접 해석 금지. 신규 산출물(Execution Contract, Integration Ledger)은 GitHub(root issue body/comment)에만, wiki 변경은 wiki CLI(`recall/relate/complete/reopen`)로만.

상세 근거·라운드 기록: `docs/task-github-improvement-directions.md`.

## 범위와 완료 기준

**범위**: `plugins/task-github/**`(skills/rules/scripts/DESIGN). 위키 측 변경 없음(브릿지는 task-github 단방향). 새 기능 확장은 별도 후보로 분리(scope 동결).

**구현 순서/의존**: A(토대) → B(A 위) → C(A+B 위) → D(A 위). 

**완료 기준**:
1. A/B/C/D 각 unit 구현 + 검증(unit별 완료조건은 구현 시 정의).
2. 각 unit은 **PR 없이 self 검증 후 `develop`에 머지**(C의 local-merge 안전계약 — merge simulation·drift·integrity gate 준수).
3. 4 unit 전부 develop 반영 후 **task-github 플러그인 minor 버전 업**(`0.7.0` → `0.8.0`; `.claude-plugin/plugin.json` + `.codex-plugin/plugin.json` + 루트 `marketplace.json` 동기) + DESIGN/README 갱신.
4. `develop` → `main` 머지 + 원격 push(논스톱).
