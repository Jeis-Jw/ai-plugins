---
title: task-github 플러그인
created_at: 2026-07-14
summary: task-worker를 실행 엔진으로 사용하고 GitHub Issue tree·dependency·PR·merge·closeout을 projection/delivery adapter로 소유하는 설계 정본
tags: [task-github, github, workflow, adapter, orchestration]
verified_at: 2026-07-14
affects_paths: [plugins/task-github/**]
---

## 현재 상태

### 설계 및 구현 상태

이 문서는 task-worker 분리 이후 `task-github` 플러그인의 **아키텍처와 구현 상태 정본**이다. task-github 0.23.0은 task-worker 0.4.0을 실행 엔진으로 사용하며 다음 두 역할을 가진다.

1. **GitHub provider adapter**: Issue tree·dependency·label·assignee·PR·CI·reviewDecision·merge·Issue close를 소유한다.
2. **호환 facade**: 기존 `task-github:*` 사용자 명령을 유지하면서 내부 실행을 task-worker에 위임한다.

task-github를 단순 기록기나 Issue comment writer로 축소하지 않는다. GitHub remote lifecycle의 idempotency, reconciliation, gear, review, merge/closeout 일관성은 task-github 고유 책임으로 남는다.

현재 구현은 다음 경계를 코드로 강제한다.

- `scripts/task_worker_bridge.py`: sibling/cache/`TASK_WORKER_ROOT` discovery, capability preflight, exact contract 검증, JSON CLI 위임
- `scripts/github_projection.py`: GitHub projection checkpoint와 coverage binding
- `scripts/definition_artifact.py`: 기존 호출자를 위한 얇은 forwarder이며 실행 코어를 포함하지 않음
- `ready_leaves.py`: GitHub tree를 WorkGraphSnapshot으로 변환하고 task-worker planner 결과에 GitHub gear/closeout 의미만 결합
- `scripts/issue_tree_import.py`: 기존 Issue Tree를 immutable definition, normalized graph, compact context, persistent binding으로 가져오고 `manual|worker` dispatch를 선택
- `scripts/task_config.py`: `.task-github.yml` provider config를 검증하고 `.task-worker.yml` execution config로 위임, legacy combined config는 warning fallback
- task-worker 누락·contract mismatch·dependency cycle은 부분 실행 없이 fail-closed
- Studio-owned review lease는 PR/CI/base-head transport를 유지한 externally-owned ledger handoff로 전환하고 approved verdict 전 closeout을 차단

### 현재 정본

- 이 문서: 분리 후 architecture와 상태
- [[task-worker-plugin]]: provider-neutral execution contract
- `plugins/task-github/DESIGN.md`: GitHub adapter/facade 상세
- task-github source/tests: runtime truth

task-worker 위임은 subprocess contract call이며 추가 agent/session hop을 만들지 않는다. ready planner는 단일 action이 아니라 전체 ready set을 반환하므로 기존 병렬성도 보존한다.

### 핵심 불변식

| 불변식 | 계약 |
|---|---|
| GitHub SoT | `record:github`/legacy mode에서는 Issue tree와 dependency가 실행 순서·remote 상태의 정본이다. |
| local ledger | task-github가 성공시킨 remote write를 즉시 반영하는 write-through cache이며 별도 SoT가 아니다. |
| full projection | root·descendant·dependency 전체 materialization이 확인되기 전 실행하지 않는다. |
| idempotent resume | remote write 뒤 local checkpoint 실패 시 marker와 remote state로 같은 Issue/edge를 재사용한다. |
| no hidden scheduler | ready 계산·worker 실행·evidence 정책을 task-github가 별도로 재구현하지 않는다. |
| no extra hop | task-github facade 호출 때문에 worker agent/session을 한 단계 더 만들지 않는다. |
| GitHub lifecycle ownership | PR/CI/reviewDecision/merge/Issue close는 task-worker가 아니라 task-github가 판정한다. |
| boundary reconcile | GitHub 조회는 시작·실패·비동기 CI/mergeability·장기 대기·최종 closeout 같은 경계에서 수행한다. |
| graceful read-only | task-worker가 없어도 setup/open/doctor와 안전한 read-only status는 가능하게 한다. |
| execution dependency | run/verify/orchestrate 같은 execution 기능은 task-worker capability가 없으면 명시적으로 STOP한다. |
| dispatch separation | `manual`도 동일 Issue Tree/dependency/ready 계산을 유지하되 local worker run을 만들지 않는다. |
| review transport 보존 | `owner=studio`에서도 PR·CI·review_waiting·base/head·closeout lane을 유지하고 reviewer dispatch만 억제한다. |

### 범위

task-github가 소유한다.

- GitHub repository setup, auth, capability 진단
- DefinitionArtifact의 GitHub full-tree projection
- stable node marker와 projection checkpoint
- Issue/sub-issue/dependency 생성·resume
- Issue tree snapshot과 pagination
- GitHub node를 WorkGraphSnapshot으로 변환
- label, assignee, comment, issue state projection
- PR 생성, CI/checks, mergeability, reviewDecision
- GitHub branch push와 remote delivery
- review-required edge의 PR lifecycle
- GitHub gear label과 cumulative container gear를 PR/FF merge edge에 결합
- merge 성공, linked Issue close, label cleanup
- GitHub remote state와 local projection reconcile
- root/container closeout과 downstream 상태 투영
- task-worker event/receipt의 GitHub reference binding
- 기존 task-github public skill compatibility facade
- 기존 Issue Tree import와 root Issue/TASK alias 기반 세션 재개

task-github가 소유하지 않는다.

- DefinitionArtifact 의미·revision schema
- provider-neutral 분해 payoff·ready·integration 판단
- generic ready planner
- worker worktree 실행과 command selection
- generic verification·evidence reuse·duplicate guard
- session-review reviewer lease와 review 상태 머신
- Studio mission·QualityPlan·budget 정본
- wiki 지식 그래프와 capture policy

### 의존성 정책

task-github의 execution 기능은 task-worker에 의존하지만 plugin packaging이 자동 dependency 설치를 지원한다고 가정하지 않는다.

- 실행 시작 전 task-worker capability·version·contract schema preflight
- 상대경로 또는 다른 plugin cache 내부 경로 하드코딩 금지
- 안정적인 executable discovery 또는 명시 `TASK_WORKER_ROOT` 사용
- marketplace/bundle에서는 두 plugin을 함께 설치하는 profile 제공
- task-worker 미설치 시 execution skill은 `dependency_missing`으로 STOP
- pure GitHub read/setup/doctor 기능은 가능한 범위에서 독립 동작

task-github는 session-review와 Studio에 hard dependency를 갖지 않는다. review provider와 higher-level orchestrator는 agent-visible optional tool layer다.

### 상태 소유

| 상태 | 정본 |
|---|---|
| 작업 정의·revision | task-worker DefinitionArtifact |
| generic node execution | task-worker run ledger |
| GitHub node/dependency | GitHub |
| projection checkpoint | task-github local projection state |
| PR·CI·reviewDecision·merge | GitHub |
| verification evidence | task-worker receipt |
| review episode | 선택된 reviewer provider |
| Studio mission/track | Studio |

같은 상태를 양쪽 plugin에 복제하지 않고 stable reference와 digest로 연결한다.

## 취지

### 목적

task-github의 목적은 GitHub Issue tree를 단순 backlog가 아니라 **작업 분해·dependency·병렬 실행·검증·delivery가 연결된 실행 view**로 사용하는 것이다.

task-worker 분리는 이 목적을 줄이지 않는다. 오히려 GitHub에 종속되지 않는 실행 방법론을 task-worker에 모으고, task-github가 GitHub native semantics를 더 정확하게 집행하도록 책임을 정리한다.

### 보존하는 주요 취지

- 이슈 트리는 독립 책임과 dependency를 표현한다.
- dependency가 없는 ready leaf는 병렬 실행한다.
- 작업 node는 worktree와 branch로 격리한다.
- child 검증 evidence는 parent/root가 재사용한다.
- parent는 interface/merge 검증, root는 integration gate를 담당한다.
- gear와 누적 risk에 따라 PR·review ceremony를 적용한다.
- remote write와 local state가 어긋나면 reconcile한다.
- merge 성공과 local cleanup 실패를 구분한다.
- 사용자 소유 변경과 main worktree HEAD를 보호한다.

### 분리로 제거하려는 낭비

- task-github와 Studio가 각각 execution planner를 구현하는 중복
- GitHub 없는 작업도 Issue/PR 모델에 맞추는 비용
- parent/root가 child full suite를 반복하는 비용
- 동일 GitHub 상태를 매 tick 전체 재조회하는 비용
- task-github agent가 generic worker 지침을 매번 재작성하는 비용
- plugin 내부에서 provider-neutral schema와 GitHub schema가 함께 변경되는 blast radius

### task-worker와의 관계

task-github는 task-worker를 내부 라이브러리처럼 복사하지 않는다. 양쪽은 versioned JSON contract로 연결한다.

```text
GitHub Issue tree
  → task-github projection adapter
  → WorkGraphSnapshot
  → task-worker ready plan·execution·verification
  → ExecutionEvent / VerificationReceipt
  → task-github GitHub mutation·delivery·closeout
```

task-worker는 GitHub를 모르고, task-github는 generic execution 판단을 재구현하지 않는다.

### 운영 모드

| 목적 | record/projection | dispatch | 실행 주체 |
|---|---|---|---|
| 로컬 작업 | none | worker | task-worker |
| 이슈 트리만 만들어 외부 위임 | github | manual | 외부 개발자, GitHub가 remote SoT |
| 이슈 트리를 자동 실행 | github | worker | task-github facade → task-worker |

세 모드는 별도 workflow 구현이 아니라 같은 DefinitionArtifact/WorkGraph를 사용한다. `manual`에서 특정 node를 worker로 인계할 때는 먼저 GitHub assignee/label ownership을 해제·확인해 이중 실행을 막고 binding의 dispatch/graph revision을 갱신한다.

### facade를 유지하는 이유

사용자가 GitHub workflow를 선택했을 때 `task-worker:*`와 `task-github:*`를 수동으로 번갈아 호출하게 해서는 안 된다. 다음 기존 표면은 유지한다.

- `task-github:define`
- `task-github:start`
- `task-github:run`
- `task-github:verify`
- `task-github:done`
- `task-github:status`
- `task-github:orchestrate`
- `task-github:review`
- `task-github:merge`

facade는 같은 execution episode 안에서 task-worker 계약을 사용한다. 새 agent를 중간 relay로 추가하지 않는다.

### 비목표

- task-github를 Issue 기록 전용 도구로 축소
- GitHub의 PR·CI·reviewDecision·merge 의미를 task-worker generic event로 대체
- task-worker run ledger를 GitHub와 경쟁하는 두 번째 remote SoT로 사용
- Studio가 task-github 내부 Issue/PR 상태를 전부 복제
- 모든 작업에 GitHub recording을 강제
- 모든 edge에 PR 또는 independent review 강제
- session-review를 task-github의 필수 dependency로 변경

### 성공 기준

- 기존 GitHub issue-tree fixture의 ready set·dependency·merge 결과가 동일
- GitHub API read는 reconcile boundary로 제한
- local/full-tree projection resume가 exactly-once 성질 유지
- task-worker evidence 재사용으로 parent 중복 verification 감소
- task-github facade 호출이 추가 agent run을 만들지 않음
- task-worker 미설치·version mismatch가 silent fallback 없이 명확히 차단
- task-worker 없이도 GitHub read/setup/doctor capability는 가능한 범위에서 유지
- P0/P1 독립 검증과 root integration gate 유지

## 구성요소

### 1. GitHubProjectionAdapter

task-worker DefinitionArtifact를 GitHub root Issue, descendant Issue, dependency edge로 materialize한다.

- stable node marker를 Issue body에 기록
- create intent를 local projection state에 먼저 기록
- remote create 성공 뒤 external ref를 checkpoint
- 실패 후 resume 시 marker와 dependency를 확인해 중복 생성 방지
- root, 모든 child, 모든 direct dependency가 materialize되어야 full coverage
- partial coverage에서는 실행을 시작하지 않음
- pagination 누락을 silent empty tree로 처리하지 않음

projection binding 예시:

```json
{
  "definition_id": "...",
  "revision": 1,
  "definition_digest": "sha256:...",
  "node_refs": {"node-a": "github:owner/repo/issues/12"},
  "edge_refs": {},
  "coverage": "full"
}
```

### 2. GitHubGraphAdapter

GitHub Issue tree와 dependency를 task-worker `WorkGraphSnapshot`으로 변환한다.

- sub-issue는 decomposition 구조
- Issue dependency는 실행 순서 제약
- label은 gear·flow·remote phase projection
- assignee는 GitHub claim view
- GitHub ref는 adapter binding에만 두고 task-worker core node id와 분리
- dependency API failure, cycle, truncated pagination이면 `ok:false`

같은 tick에서는 write-through ledger를 우선 읽는다. GitHub 재조회는 다음 boundary에서만 수행한다.

- startup/resume
- remote write 실패 또는 timeout
- CI/checks/mergeability/reviewDecision
- 장기 대기 뒤 freshness 확인
- final closeout

### 3. Compatibility facade

| skill | task-github 고유 책임 | task-worker 위임 |
|---|---|---|
| `setup` | repo/auth/label/GitHub 준비 | 없음 |
| `define` | optional wiki bridge, GitHub projection | artifact·분해 contract |
| `open` | Issue/root/PR read model | 없음 |
| `start` | assignee/label/remote binding | lease·worktree 시작 |
| `plan` | Issue context와 결정 ref 주입 | 실행 계획 |
| `run` | remote ref·provider constraint 주입 | node 실행 |
| `verify` | GitHub dependency 상태·comment projection | evidence 계획·receipt |
| `done` | PR/FF delivery 준비·Issue projection | ready_for_delivery |
| `status` | GitHub remote composite | local ready/run state |
| `orchestrate` | GitHub adapter loop | planner·worker dispatch |
| `review` | PR/Issue acceptance binding | review evidence 소비 |
| `merge` | PR/CI/merge/Issue close | delivery receipt 소비 |
| `doctor` | auth/API/config/dependency 진단 | task-worker capability 진단 |
| `reconcile` | GitHub/projection/wiki bridge 복구 | generic run-state는 참조만 |

### 4. Adapter loop

```text
1. capability preflight
2. GitHub reconcile boundary에서 graph snapshot 생성
3. task-worker planner에 snapshot+ledger/evidence 전달
4. ready_actions를 같은 execution episode에서 dispatch
5. task-worker event/receipt를 local ledger에 반영
6. GitHub mutation이 필요한 event를 idempotent projection
7. review/delivery boundary 처리
8. completed lane마다 즉시 re-tick
9. root integration·closeout gate
```

planner가 반환한 ready set을 task-github가 임의로 직렬화하거나 다시 계산하지 않는다. 다만 GitHub rate limit, branch base closeout 같은 provider resource lock은 adapter가 추가할 수 있으며 reason을 남긴다.

### 5. GitHub mutation projection

task-worker event를 다음처럼 투영한다.

| task-worker event | GitHub projection |
|---|---|
| `node_claimed` | assignee + `in-progress` |
| `verification_completed` | structured evidence comment/reference |
| `finding_opened` | `changes-requested` 또는 blocked 상태 |
| `ready_for_review` | PR + review request |
| `ready_for_delivery` | closeout lane enqueue |
| `delivery_completed` | merge evidence + Issue close |
| `execution_failed` | failure class와 retry gate |
| `execution_blocked` | blocked reason과 owner/human gate |

projection은 동일 idempotency key를 두 번 적용하지 않는다.

### 6. DeliveryAdapter

task-github가 concrete GitHub delivery를 소유한다.

#### review-free edge

- task-worker가 검증된 commit range와 `ready_for_delivery` receipt 반환
- task-github closeout lane이 provider branch ref를 FF
- remote push, Issue close, merge evidence 기록
- 같은 base target만 직렬화하고 다른 base는 병렬 가능

#### review-required edge

- PR 생성 또는 기존 PR resume
- required checks와 mergeability 확인
- configured review provider 또는 human gate 처리
- approval 뒤 `ready_for_pr_closeout`
- PR merge 성공을 primary completion signal로 사용
- linked non-default-base Issue 직접 close
- label cleanup과 downstream projection

merge 성공 뒤 local sync·branch/worktree cleanup 실패는 warning-tier다. remote delivery 성공을 되돌리지 않는다.

### 7. ReviewProvider 경계

task-worker는 `review_required`와 review packet requirement만 계산한다. task-github는 PR edge에서 provider를 선택한다.

- session-review가 설정되면 독립 review workflow에 PR/diff/criteria/evidence ref 전달
- 설정이 없고 review가 필수면 human gate STOP
- review-free gear에서는 session-review를 자동 소집하지 않음
- reviewer verdict를 task-worker evidence로 위조하지 않고 별도 ReviewReceipt로 유지
- 같은 finding 수정은 reviewer provider의 lease 정책을 존중

### 8. Closeout과 reconciliation

closeout 성공 조건:

- required verification/review evidence 유효
- dependency blocker 없음
- expected base와 actual PR base 일치
- CI/checks/mergeability 충족
- merge 또는 FF 성공 evidence
- linked Issue 상태 전이 성공 또는 명시적 recovery state

cleanup 성공은 closeout 성공 조건과 분리한다.

reconcile은 다음 mismatch만 복구한다.

- local projection checkpoint와 remote Issue/edge
- local closeout queue와 PR/Issue 상태
- task-worker delivery request와 GitHub delivery receipt binding
- optional wiki TASK bridge의 binary completion projection

generic task-worker run state를 GitHub label로 완전 복제하지 않는다.

### 9. 설정

`.task-github.yml`에는 GitHub-specific 설정만 남기는 것이 목표다.

- repository/base branch
- Issue/label conventions
- projection mode와 strict dependency policy
- PR creation/merge strategy
- required GitHub checks
- review provider binding
- closeout/push policy
- GitHub capability requirements
- legacy config translation 기간

gear, impact rule, generic command profile, evidence invalidation은 `.task-worker.yml`로 이동한다.

### 10. Dependency preflight

execution skill 시작 전 확인한다.

- task-worker 설치·발견
- task-worker contract schema/version compatibility
- requested skill/capability 존재
- WorkGraphSnapshot과 receipt schema 지원
- repository GitHub auth와 dependency API
- worktree/branch prerequisites
- configured review provider의 실제 사용 가능성

실패는 machine-readable reason으로 STOP하며 task-github 내부 legacy engine으로 조용히 fallback하지 않는다. migration 기간에만 명시 feature flag로 기존 engine을 선택할 수 있고 결과 receipt에 engine을 기록한다.

### 11. Studio 연동

Studio는 다음 두 경로를 선택할 수 있다.

```text
GitHub 없는 track: Studio → task-worker
GitHub track:      Studio → task-github facade → task-worker
```

Studio는 task-github Issue/PR 내부 상태를 복제하지 않고 external ref, coarse status, evidence/delivery receipts만 받는다. 한 track에 Studio-native와 task-github/task-worker executor를 동시에 두지 않는다.

### 12. Migration과 호환

1. task-worker contract와 conformance fixture 추출
2. `record:none` local lifecycle을 task-worker로 이동
3. task-github facade가 task-worker를 선택적으로 호출
4. GitHubGraphAdapter와 DeliveryAdapter 분리
5. orchestrate planner·evidence 중복 구현 제거
6. 기존 public skill과 `.task-github.yml` legacy translation 유지
7. replay parity 확인 뒤 legacy engine 제거

big-bang 이동을 금지한다. 각 단계에서 기존 task-github fixture와 local fixture가 동시에 통과해야 다음 단계로 진행한다.

### 13. 검증 fixture

- DefinitionArtifact full-tree projection과 failure resume
- dependency API failure 시 partial ready-set 금지
- 50개 초과 child pagination
- ready sibling 병렬 dispatch parity
- same-parent closeout lane과 다른 base 병렬성
- PR base mismatch 복구
- child evidence parent reuse
- merge success 후 cleanup warning
- task-worker missing/version mismatch STOP
- task-worker event의 idempotent GitHub projection
- legacy `task-github:*` facade 결과 호환
- Studio external ref/receipt integration
