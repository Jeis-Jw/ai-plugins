---
title: session-review: task-github 개선방향 초안
created_at: 2026-06-25
summary: task-github 개선방향(I integration / II bridge / III ergo) co-design explore 라운드 핸드오프
tags: [session-review, review, direction]
type: snapshot
updated_at: 2026-06-26
---
## 현재 논의

```yaml
phase: "approved"
active_actor: "none"
lock_since: null
next_actor: "worker"
target_mode: "document"
target_nature: "direction"
target_ref: "docs/task-github-improvement-directions.md"
base_ref: "32e07e6bf89872c082e29ed04790caaa670aa0b7"
responding_to: "9564ee377f14e5cb15b2ae29bc2b1b43ab1cc0a7"
round: 3
round_type: "confirm"
flow_mode: "separate"
review_strength: "normal"
blocking_count: 0
```

### 리뷰 피드백 (round 1)

판정: `approved`, `blocking_count=0`. 대전제 위반으로 막을 항목은 없다. 다만 구현 전 반영해야 할 강한 권고가 있다.

1. [directional] 대전제 stress-test 결과: 방향 I/III는 순수 task-github 내부라 안전하다. 방향 II도 task-github 쪽 resolver/reconcile로만 두고, wiki 변경은 `wiki CLI`의 `recall/relate/complete/reopen`만 통하면 안전하다. 금지선은 명확하다: branch/worktree/PR metadata가 wiki TASK를 대체하거나, wiki가 GitHub 상태를 직접 해석하기 시작하면 제2 브릿지다.

2. [should-reflect-before-implementation] 방향 I의 `local-merge`는 PR `Closes #N` 자동 closeout을 우회한다. 따라서 `closeout.py`를 PR 전용이 아니라 `integration closeout`으로 일반화해야 한다. 입력은 `--mode pr|local` 정도로 나누되, 공통 출력은 `{issue, root, root_closed, task_to_complete, downstream, merged}`를 유지한다. local-merge도 issue close/comment/label cleanup/downstream 안내/root 완료 감지를 반드시 수행해야 wiki TASK 투영이 깨지지 않는다.

3. [should-reflect-before-implementation] stacked의 리뷰 게이트 위치는 "리프→컨테이너는 싸게, 컨테이너→main은 단일 관문"에 동의한다. 단, 이것을 "리프는 무검증"으로 해석하면 안 된다. 리프 local-merge 전에는 최소 leaf verify + drift gate + blocker 재확인이 필요하고, `gear:major`/비가역/보안/데이터성 leaf는 컨테이너 merge 전에도 self-flow 또는 PR gate를 요구해야 한다. 최종 container→main gate는 전체 diff의 release gate다.

4. [should-reflect-before-implementation] integration mode는 `profile+gear` 자동 산출을 기본 추천값으로 쓰되, 실제 실행값은 root issue 생성 시점에 materialize해야 한다. 즉 `define` 결과물 또는 root issue body에 `topology`, `gate`, `parent_branch`, `leaf_policy`를 명시해 다음 세션이 재추론하지 않게 한다. per-work flag는 override 수단으로 두는 편이 맞다. 자동 추론만 두면 gear 재판단이나 profile drift로 같은 root의 실행 전략이 바뀐다.

5. [directional] 방향 II의 linkage doctor는 YAGNI가 아니다. 다만 v1은 read-only `doctor --json` + opportunistic reconcile 정도가 적절하다. `--fix`는 별도 명시 옵션으로 두고, fix도 wiki 직접 쓰기가 아니라 `wiki relate/complete/reopen` 호출만 허용해야 한다. doctor가 검사할 최소 불변식은 (a) root issue Wiki Context의 TASK 존재, (b) task `relations.tasks`가 root issue를 가리킴, (c) root closed ↔ task done 투영 일치다.

6. [directional] 놓친 방향 하나를 추가하자: `task-github status/next`는 라벨 bootstrap보다 가치가 크다. 출력은 ready leaf 목록, blockers, root↔TASK bridge 상태, branch/worktree 존재, topology/gate mode, next action을 한 번에 보여줘야 한다. 이게 실제 call-pattern과 재조회 비용을 줄인다.

7. [nice-to-have] branch topology 명명은 root/leaf를 구분하는 편이 좋다. 예: `task/root-{ROOT}`와 `task/issue-{LEAF}`. dependency DAG의 정본은 계속 GitHub Issue dependencies이고, branch ancestry는 실행 편의 정보일 뿐이라는 문구를 설계에 박아두면 혼동을 줄인다.

### 리뷰 보강 (round 1 follow-up)

사용자 지적 반영: reviewer 역할도 단순 안전성 검토가 아니라 co-design 입력을 보태야 한다. 아래는 기존 I/II/III를 깨지 않고 얹을 수 있는 추가 개선안이다.

8. [directional] 방향 I에 `Execution Contract`를 추가하자. root issue 생성 시 task-github가 machine-readable 블록을 남긴다: `wiki_task`, `topology`, `gate`, `parent_branch`, `leaf_policy`, `required_checks`, `closeout_mode`. 이건 wiki TASK의 대체물이 아니라 GitHub ROOT 이슈의 실행 계약이다. 다음 세션이 profile/gear를 재추론하지 않고 같은 전략을 이어갈 수 있다.

9. [directional] 방향 I에 `Integration Ledger`를 root issue comment로 두자. leaf local-merge 때마다 task-github가 root issue에 leaf issue, commit SHA, 검증 증거, drift 결과, downstream 상태를 append/update한다. stacked topology에서 PR이 없으면 leaf 히스토리가 흩어질 수 있는데, 이 ledger가 GitHub 내부 실행 로그 역할을 한다. wiki에는 넣지 않는다.

10. [should-reflect-before-implementation] `local-merge`는 반드시 `merge simulation` 단계를 가져야 한다. 임시 worktree나 clean checkout에서 parent branch 또는 main에 실제 병합될 상태를 만들고 tests + `changed-path-stale` + integrity gate를 돌린 뒤에만 반영한다. 이게 없으면 "로컬이라 빠름"이 아니라 "리뷰/CI 없는 main 오염"이 된다.

11. [directional] 방향 II의 resolver는 link만 풀지 말고 `context bundle`을 출력해야 한다. 예: `{issue, root, wiki_task, topology, gate, parent_branch, blockers, downstream, worktree_path}`. open/start/done/merge/status가 같은 JSON read-model을 쓰면 반복 gh/wiki 조회와 regex 복붙이 같이 줄어든다.

12. [directional] 방향 III의 `status`는 `next`까지 포함해야 한다. 단순 목록보다 "지금 할 수 있는 다음 행동"이 가치다: ready leaf, blocked leaf, review needed, root branch behind main, orphan worktree, bridge mismatch, closeout pending. 이건 사용자의 steering 대기시간을 줄이는 핵심 UX다.

13. [directional] `setup doctor`를 추가 후보로 둔다. repo-local prerequisites를 한 번에 점검한다: labels 존재, gh auth/repo, dependency API 가능 여부, `.worktrees/` ignore, `.worktreeinclude`, wiki availability, session-review availability, default integration config. 실패해도 독립 동작은 유지하고 capability matrix만 보여준다.

14. [nice-to-have] nested repo guard를 넣을 가치가 있다. task-github가 실행 전에 `git rev-parse --show-toplevel`와 `gh repo view`를 확인해 root issue repo와 실제 code repo가 다를 때 명시적으로 알려준다. 이건 bridge를 늘리는 게 아니라 잘못된 repo에서 branch/worktree를 만드는 사고를 줄이는 실행 안전장치다.

15. [directional] 최종 수렴안은 I/II/III를 병렬 feature가 아니라 네 개의 얇은 unit으로 자르는 편이 좋다: A `resolve/context bundle`, B `Execution Contract + config materialization`, C `local/stacked integration closeout`, D `status/next + doctor`. 이 순서면 bridge 안정화가 먼저 깔리고, 그 위에 integration mode와 UX가 붙는다.

### 리뷰 피드백 (round 2)

판정: `changes-requested`, `blocking_count=1`. 큰 방향은 수렴됐다. A→B→C→D 절단, closeout 확장, root body Execution Contract, stacked+local 한정 Ledger, label bootstrap 강등은 모두 동의한다. 단 confirm 전에 safety contract 모순 1건은 고쳐야 한다.

1. [blocking] Unit D의 `doctor`: "read-only `--json` 기본 + opportunistic reconcile"은 서로 충돌한다. `doctor`가 기본 read-only라면 reconcile은 수행하면 안 된다. reconcile은 `wiki complete/reopen/relate` 또는 GitHub comment/label/close 같은 상태 변경을 유발할 수 있어 `--fix`/`--apply`/별도 `reconcile` 명령으로 명시 분리해야 한다. 수렴안 문구를 `doctor --json = diagnose only`, `doctor --fix` 또는 `reconcile --apply = explicit mutation`, `open/merge의 opportunistic reconcile도 dry-run report 후 apply gate`처럼 바꿔야 confirm 가능하다.

2. [should-reflect-before-implementation] Unit B의 Execution Contract는 root issue body "경량 블록" 수준을 넘어서 parser-safe contract여야 한다. fenced block + `schema_version` + stable keys + unknown-key ignore 규칙을 명시하자. Unit A가 B보다 먼저 구현되므로 context bundle의 `topology/gate/parent_branch`는 contract 부재 시 `null/default_source`를 낼 수 있어야 한다.

3. [should-reflect-before-implementation] Unit C의 `merge simulation`에서 `tests`는 모호하다. Unit B의 `required_checks`를 읽어 실행한다고 연결해야 한다. 그렇지 않으면 local-merge마다 agent가 테스트를 재해석하고, "검증된 로컬 머지"의 의미가 세션별로 흔들린다.

4. [directional] Q3 major leaf는 `self-flow 기본`에 동의하되, `비가역/DB migration/public API/security/data-loss risk`는 `leaf_policy`에 의해 PR 또는 hard self-flow를 강제하는 rule table이 필요하다. 단순 `PR은 override`라고만 쓰면 major 안에서도 위험도가 섞인다.

5. [directional] Integration Ledger append-only는 동의한다. 다만 `status/next`가 최신 상태를 빠르게 읽으려면 각 Ledger comment에 stable marker와 machine-readable event block을 넣고, root issue body에는 latest summary/cache를 두지 않을지 결정해야 한다. append-only만 있으면 긴 root issue에서 next 계산이 느려질 수 있다.

6. [directional] A/B/C/D는 confirm 후보로 충분히 좋다. blocking #1만 고치면 다음 라운드는 confirm으로 가도 된다. 추가 scope 확장은 하지 않는 편이 맞다.

### 리뷰 피드백 (round 3)

판정: `approved`, `blocking_count=0`. confirm 라운드 기준으로 lock 가능하다.

1. [directional] round 2 blocking이 해소됐다. `doctor --json`은 diagnose-only, `reconcile --apply`/`doctor --fix`는 explicit mutation으로 분리됐고, `open`/`merge`의 opportunistic reconcile도 dry-run report → apply gate로 바뀌어 silent mutation 위험이 사라졌다.

2. [directional] should-reflect 정밀화도 반영됐다. Execution Contract는 parser-safe fenced block + `schema_version` + stable keys + unknown-key ignore로 명확해졌고, Unit A의 contract 부재 fallback도 정의됐다.

3. [directional] local-merge 안전계약도 충분히 잠겼다. merge simulation은 `required_checks`를 실행하도록 연결됐고, leaf gate는 `leaf_policy` rule table로 위험도별 self-flow/PR 강제가 가능해졌다.

4. [directional] Integration Ledger는 stacked+local 한정, append-only + stable marker/event block으로 정리되어 대전제 안에서 실행 로그 역할에 머문다. wiki TASK를 대체하지 않는다는 red line도 유지된다.

5. [nice-to-have] 구현 계획 단계에서는 A/B/C/D를 다시 쪼개더라도 이 방향 문서는 lock된 direction으로 보고, 새 기능 확장은 별도 후보로 분리하는 편이 좋다.

## 리뷰 요청 (작업자→리뷰어, round 1 · explore)

**대상**: `docs/task-github-improvement-directions.md` (개선방향 초안, target_nature=direction)

**목적**: 대전제 ―① 두 플러그인 독립 동작 ② wiki `TASK` 노드 ↔ github `ROOT` 이슈 단일 1:1 브릿지― 를 유지하면서 효율/기능을 개선할 **방향**을 co-design으로 정한다. round_type=explore이므로 수렴보다 **확장·검증**이 우선.

**co-design 계약**: `approved`는 `blocking_count=0`을 뜻하지 "의견 없음"이 아니다. 강한 권고는 `[should-reflect-before-implementation]`/`[directional]`로 남겨라.

**특히 봐줄 것** (문서 §5):
1. **대전제 안전성 stress-test (최우선)** — 세 방향 중 역방향 의존/제2 브릿지를 만드는 게 있나?
2. 방향 I 리뷰 게이트 위치 — 리프→컨테이너 로컬머지 / 컨테이너→main 단일 관문, 동의?
3. integration mode 자동(profile+gear) vs 명시(per-work flag) 무게중심
4. 방향 II "linkage doctor"가 YAGNI인가
5. 놓친 방향 추가 (premise 안에서)

리뷰어는 대상 문서를 읽고 `review` 스킬로 피드백을 남긴다.

## 배경

target_mode=document, target_ref=docs/task-github-improvement-directions.md, base_ref=32e07e6bf89872c082e29ed04790caaa670aa0b7, review_branch=review/task-github-directions, 대전제=플러그인 독립+TASK↔ROOT 단일 브릿지(유지)

## 정해진 것

round3 confirm approved: 4-unit direction locked as A resolve/context-bundle, B Execution Contract/config materialization, C local/stacked integration closeout, D status/next + doctor/reconcile. Safety contracts locked: plugin independence, TASK↔ROOT sole bridge, doctor diagnose-only vs explicit reconcile mutation, required_checks-backed merge simulation, leaf_policy risk gates, GitHub-only Integration Ledger.

## 아직 열린 질문

없음 — direction lock 가능. 구현 중 새 범위는 별도 task/decision 후보로 분리한다.

## 다음에 볼 것

worker가 confirm approval을 받아 direction lock 처리하고, 필요하면 구현 계획/issue 정의 단계로 전환한다.

## 관련 파일/문서

docs/task-github-improvement-directions.md

## 승격 후보
