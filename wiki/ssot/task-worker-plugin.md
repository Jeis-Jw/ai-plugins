---
title: task-worker 플러그인
created_at: 2026-07-14
summary: provider-neutral 작업 정의·분해·병렬 실행·검증·evidence 재사용을 소유하고 외부 provider가 상태와 delivery를 투영하는 범용 작업 엔진 설계 정본
tags: [task-worker, workflow, orchestration, execution, evidence]
verified_at: 2026-07-15
affects_paths: [plugins/task-worker/**, plugins/task-github/**]
---

## 현재 상태

### 설계 및 구현 상태

이 문서는 `task-worker` 플러그인의 **아키텍처와 구현 상태 정본**이다. 2026-07-14에 0.1.0으로 독립 플러그인을 만들었고, 0.2.0에서 task-github 위임 전환, 0.3.0에서 설정·binding·resume·evidence 실행 계약, 0.4.0에서 단일 review owner permit, 0.5.0에서 canonical execution control, 0.6.0에서 안전한 workspace init·doctor까지 완료했다.

0.6.0이 독립적으로 소유하는 범위는 다음과 같다.

- `task-worker.definition/v1` immutable DefinitionArtifact와 stable node id
- dependency·parent cycle fail-closed 검증
- 단일 next action이 아닌 전체 `ready_actions[]` planner
- provider-neutral `task-worker.work-graph/v1` snapshot 검증과 `task-worker.ready-plan/v1`
- 자식 완료로 새 통합 상태가 생긴 container/root의 `integration_candidates[]`
- node별 stable branch/worktree identity와 execution lease
- local run `start → run → verify → done → closeout` lifecycle
- child 완료 뒤 container/root를 `run_kind: integration`으로 실행하는 통합 gate
- verify event의 구조화 evidence와 `workflow-receipt/v1`
- `.task-worker.yml` provider-neutral 실행 설정
- `dispatch: worker|manual`과 `delivery: local-ff|external` 독립 축
- `task-worker.provider-binding/v1`과 digest-pinned context/work-graph checkpoint
- TASK ID, GitHub root ref, definition id 기반 세션 간 `resume`
- definition/node/HEAD/command/environment/tool version fingerprint 기반 성공 evidence 재사용
- provider closeout event의 idempotent receipt 기록
- exact `workflow-review-lease/v1` binding, digest/conflict validation, `task-worker.review-permit/v1`
- 기존 `task-github.definition/v1`, `task-github.local-run/v1` 입력 호환
- define/plan/start/run/verify/done/status/orchestrate public skill
- exact schema/command를 공개하는 `capabilities` contract
- provider 비탐색 `task-worker:init`과 config/state/policy 준비 상태를 읽기 전용 진단하는 `task-worker:doctor`
- `local|manual|quality|minimal` preset과 제품별 명령을 추측하지 않는 TODO/fail-closed policy skeleton

새 canonical artifact는 provider-specific `record`를 허용하지 않으며 external delivery는 generic `external`로 표현한다. task-worker runtime에는 GitHub 또는 Studio 실행 dependency가 없다.

task-github 0.25.0은 `task_worker_bridge.py`를 통해 이 JSON CLI contract, review permit과 execution-control handshake를 소비한다. task-github의 구 `definition_artifact.py`는 CLI forwarder만 남았고 DefinitionArtifact 생성, local lifecycle, generic ready planner의 중복 구현은 제거됐다. 기존 GitHub Issue Tree도 import하면 WorkGraphSnapshot·context·provider binding으로 고정해 `manual|worker` 두 dispatch에서 재사용한다.

canonical execution-control contract는 `studio-verification-contract-set/v1`, digest `sha256:7df570d1faaba445865c74fd6dffff73178f0102cd3a5728183abf6791ce2b65`로 고정한다. `STUDIO_VERIFICATION_CONTRACT`가 없으면 `tests/fixtures/studio-verification-contract-v1.json`을 읽고, schema·root canonical digest가 하나라도 다르면 실행 전에 중단한다.

`scripts/execution_control.py`는 command profile/impact rule을 읽어 허용된 profile·QA mode만 선택하고, profile과 다른 argv·forbidden argv·machine-readable reason 없는 full QA를 거부한다. physical identity는 contract B1에 따라 `head + command_digest + environment_digest + tool_version + purpose + optional fresh_requirement_id`만 hash한다. `definition_id`, `node_id`, `cycle_id`, `unit_id`, `target`, profile id는 attribution이며 identity에 섞지 않는다.

execution claim, capability probe, external spend occurrence는 file lock과 atomic replace로 중복 실행을 막는다. 성공 execution은 immutable command receipt와 verification evidence의 digest/source binding이 맞을 때만 재사용하며, active duplicate와 physical run cap은 owner-visible machine-readable STOP을 반환한다. token telemetry가 `null/unavailable`이면 `fail-closed`는 pause하고 `report-only`만 null을 유지한 채 통과한다. GitHub PR/merge preflight evidence는 provider semantics가 필요하므로 계속 task-github adapter가 소유한다.

분리 replay에서 다음 결과를 보존했다.

- 작업 분해와 dependency graph
- ready leaf 집합과 병렬 실행 가능성
- worktree·branch 격리
- gear 및 merge-edge 품질 gate
- verification coverage와 P0/P1 검출
- 통합 candidate의 최종 검증
- 사용자 소유 변경 보존

task-worker 동작 확인은 `plugins/task-worker/DESIGN.md`, 소스와 테스트를 우선한다. GitHub projection·gear·review·merge·closeout 동작은 `plugins/task-github/DESIGN.md`와 task-github 소스·테스트가 runtime truth다.

검증 근거:

- task-worker 단독 contract와 planner 회귀 테스트
- task-github projection resume, ready-leaf replay, bridge missing/mismatch fail-closed 테스트
- 저장소 전체 Python 회귀
- Codex plugin validator와 두 플러그인의 public skill validator

관련 GitHub adapter/facade 정본은 [[task-github-plugin]]이다.

### 역할

`task-worker`는 GitHub, Studio, wiki, session-review를 모르는 **provider-neutral 작업 실행 엔진**이다. 작업 정의를 실행 가능한 그래프로 만들고, ready action을 병렬 dispatch하며, worktree에서 산출물을 만들고 검증하고, 재사용 가능한 evidence와 delivery 요청을 반환한다.

`task-worker`는 단일 worker agent를 뜻하지 않는다. 플러그인 내부 용어는 다음처럼 구분한다.

| 용어 | 의미 |
|---|---|
| workflow engine | 그래프·상태·gate·evidence를 처리하는 task-worker core |
| worker lane | 한 ready node를 점유해 구현·검증하는 실행 episode |
| reviewer provider | 독립 검토가 필요한 edge에 연결되는 선택적 외부 도구 |
| graph provider | local artifact 또는 외부 시스템에서 WorkGraphSnapshot을 공급하는 adapter |
| delivery provider | 검증된 변경을 FF, PR, merge 등으로 전달하는 adapter |

### 핵심 불변식

| 불변식 | 계약 |
|---|---|
| 논리 구조 보존 | 효율화를 이유로 독립 책임·위험·dependency 단위를 합치지 않는다. |
| 병렬성 보존 | planner는 단일 next action이 아니라 `ready_actions[]`를 반환한다. |
| 격리 | 동시에 실행되는 변경 node는 서로 다른 worktree와 execution lease를 사용한다. |
| 사실 재사용 | 동일 physical identity이고 criteria/path/surface/impact/purpose/independence가 적용 가능한 immutable receipt/evidence만 재사용한다. |
| 판단 갱신 | scope·ref·risk·criteria가 바뀌면 기존 증거를 무효화하고 필요한 판단을 새로 한다. |
| 통합 검증 | 병합으로 새 상태가 만들어지면 leaf evidence가 있어도 integration gate를 생략하지 않는다. |
| no extra hop | plugin delegation 자체를 이유로 fresh agent/session을 추가하지 않는다. |
| provider neutrality | Issue·PR·label·Studio track·wiki node 같은 외부 식별자를 core schema에 넣지 않는다. |
| fail closed | graph 불완전, dependency cycle, stale lease, evidence ambiguity에서는 부분 ready set을 실행하지 않는다. |
| review owner fencing | Studio-owned edge에서는 reviewer dispatch만 externally-owned handoff로 전환하고 run/verify/done/integration gate를 유지한다. |
| owner gate | 결제·배포·외부 mutation 등 명시된 owner gate는 executor가 우회하지 않는다. |

### 범위

task-worker가 소유한다.

- immutable DefinitionArtifact revision과 stable node id
- 분해 품질 규칙과 dependency 의미
- provider-neutral risk·review metadata 보존과 integration candidate 판정
- WorkGraphSnapshot 검증
- local run state와 recovery
- ready action planning과 bounded parallel dispatch
- execution lease, worktree, branch 격리
- worker lane의 compact context packet
- 변경 범위 기반 검증 계획
- command profile, execution fingerprint, duplicate guard
- VerificationReceipt와 evidence invalidation
- conflict resolution을 child worktree에서 수행하는 규칙
- local-git delivery와 provider-neutral delivery request
- workflow telemetry receipt

command profile의 프로젝트별 argv 정의는 config/tool layer가 소유한다. core는 argv를 profile에서만 만들고 impact rule의 profile·QA mode 제한을 적용한다. HEAD·command·environment·tool version·purpose 또는 fresh requirement가 바뀌면 physical identity가 달라진다. criteria/path/surface/impact/independence 변경은 identity가 아니라 evidence applicability/invalidation으로 처리한다. GitHub gear label과 merge-edge review 계산은 task-github adapter가 기존 호환 계약으로 유지한다.

task-worker가 소유하지 않는다.

- GitHub Issue·dependency API·label·assignee·comment
- PR 생성, GitHub CI, reviewDecision, remote Issue close
- Studio mission·track·QualityPlan·owner budget 정본
- session-review의 reviewer lease·snapshot·review branch 상태 머신
- wiki task·decision·SSOT 승격
- 제품별 test command 자체

### 의존성 방향

task-worker core는 다른 workflow plugin에 hard dependency를 갖지 않는다.

```text
Studio ───────────────▶ task-worker
task-github ──────────▶ task-worker
local user ───────────▶ task-worker
session-review ◀──── optional reviewer provider
```

task-worker는 provider를 직접 발견하거나 외부 상태를 임의 조회하지 않는다. caller가 digest가 고정된 input packet을 제공하고 task-worker는 action·event·receipt를 반환한다. 외부 provider mutation은 caller 또는 adapter가 수행한다.

### 설정 경계

provider-neutral 실행 설정은 `.task-worker.yml`을 정본으로 한다.

- gear별 plan/verify/review requirement
- max workers와 resource lock class
- command profiles와 impact rules
- evidence invalidation policy
- retry·flake reproduction policy
- local delivery mode
- telemetry 요구 수준

현재 schema는 `mode`, `state-root`, `dispatch`, `delivery`, planning/verify/review tool, `orchestrate`, `define`, `evidence`, `recovery`다. 예시는 `plugins/task-worker/config.example.yml`이며 consumer workspace의 실제 파일은 local config로 취급한다.

workspace onboarding은 다음 계약을 따른다.

| preset | dispatch | delivery | command/impact policy | telemetry |
|---|---|---|---|---|
| `local` | `worker` | `local-ff` | TODO skeleton | token optional |
| `manual` | `manual` | `external` | TODO skeleton | token optional |
| `quality` | `worker` | `local-ff` | TODO skeleton | token required |
| `minimal` | `worker` | `local-ff` | disabled | token optional |

`task-worker:init`은 `.task-worker.yml`, local state directory, 선택한 preset의 policy skeleton과 `.task-worker/local/` gitignore만 다룬다. 같은 내용은 skip하고 다른 기존 config/policy는 `--force` 없이는 전체 적용을 중단한다. `--dry-run`은 적용 예정 결과만 반환한다. GitHub·Wiki·Studio·reviewer provider를 자동 탐색하거나 초기화하지 않는다.

TODO skeleton은 제품별 command를 추측하지 않은 상태를 명시한다. JSON parsing은 가능하지만 command profile/impact rule canonical loader에는 실패하므로 약한 QA를 실행 허가로 오인하지 않는다. `task-worker:doctor`는 config validation, state-root, policy 존재·TODO·canonical validity를 구분해 보고한다. 이 준비 상태는 실행 명령 선택에만 영향을 주며 분해·병렬성·independent review·integration gate를 축소하지 않는다.

GitHub repository, label, PR, merge, issue projection 설정은 `.task-worker.yml`에 넣지 않는다. 기존 `.task-github.yml`의 generic execution 항목은 migration 기간 동안 task-github가 task-worker config로 번역하며, 호환 기간 종료 뒤 명시적으로 이동한다.

### 완료 상태

task-worker node의 `done`은 외부 시스템이 닫혔다는 뜻이 아니다.

- local delivery: 검증과 local closeout까지 성공하면 `completed`
- external delivery: 검증 후 `ready_for_delivery`; provider receipt가 돌아온 뒤 `completed`
- review-required edge: `ready_for_review`; reviewer verdict와 delivery receipt가 모두 유효해야 `completed`

remote PR merge나 Issue close를 task-worker가 추정해서 완료 처리하지 않는다.

### provider binding과 Wiki 관계

task-worker core는 provider ref를 opaque alias/data로 저장할 뿐 Wiki/GitHub API를 호출하지 않는다. Wiki TASK는 작업지시·취지의 durable root 문서이고 task-worker binding은 실행 pin과 재개 위치다. Wiki `relations.tasks`에는 `task-worker:DEFINITION`을 연결할 수 있다.

작업 종료 시 adapter가 Wiki `complete` 또는 GitHub Issue close를 수행하고 receipt를 `provider-event`로 기록한다. 따라서 세션이 바뀌어도 TASK ID나 `owner/repo#N` alias로 binding을 찾아 미완료 provider closeout을 이어갈 수 있다. Wiki에는 runtime 중간 상태를 복제하지 않고 active/done만 투영한다.

## 취지

### 목적

task-worker의 목적은 **작업을 잘 분해하고, 독립 가능한 결과를 병렬로 만들며, 검증 강도를 유지한 채 불필요한 physical run과 context reload만 제거하는 것**이다.

최적화 대상은 논리 작업 수나 품질 gate 수가 아니다. 동일 상태·동일 목적의 명령 재실행, 상위 node의 하위 검증 반복, provider 상태 재조회, fresh agent의 repository 재탐색이 대상이다.

### 보존하는 엔지니어링 방법론

- 분해는 병렬 이득, 위험 격리, 정보 가치 경계, 병렬 해금이 있을 때 수행한다.
- 검증·문서·runbook 자체를 별도 leaf로 만들지 않고 산출물 node의 완료 조건에 포함한다.
- 같은 write-set·테스트·맥락을 공유하는 작업은 phase로 묶고, 독립 소유·독립 검증·독립 rollback이 가능한 경우만 나눈다.
- dependency는 직접 제약만 표현하고 transitive·방어적 blocker를 만들지 않는다.
- 형제 lane은 실제 shared resource가 없으면 병렬로 실행한다.
- ceremony는 node 개수에 비례시키지 않고 merge edge의 gear와 risk에 비례시킨다.
- leaf delta 검증, parent contract 검증, root integration 검증을 구분한다.
- major 또는 명시적 independence requirement에는 독립 review provider를 사용할 수 있다.

### 효율화 원칙

한 문장 원칙은 다음과 같다.

> 사실은 재사용하고, 판단은 위험이 변할 때 새로 한다.

이를 위해 논리 작업 그래프, evidence 그래프, physical execution plan을 분리한다.

```text
WorkGraph
  → valid evidence 계산
  → missing evidence의 ready action set
  → 병렬 physical execution
  → integration/review/delivery gate
```

작업 node가 10개여도 같은 command를 10번 실행할 이유는 없다. 반대로 physical run을 줄이기 위해 독립 작업 node를 합치거나 root integration QA를 생략해서도 안 된다.

### 플러그인 분리의 목적

기존 task-github는 provider-neutral local workflow와 GitHub projection/delivery라는 서로 다른 변경 이유를 함께 갖고 있다. task-worker 추출은 GitHub 기능을 줄이기 위한 것이 아니라 다음을 가능하게 하기 위한 것이다.

- GitHub 없는 local workflow에서도 같은 분해·실행·검증 방법론 사용
- Studio가 GitHub를 강제하지 않고 task-worker를 executor로 선택
- task-github가 remote API·projection·delivery 문제에 집중
- task-github와 Studio가 같은 execution/evidence 로직을 중복 구현하지 않음
- session-review를 필요 경계에서만 선택적으로 연결

### 금지되는 최적화

- leaf 수를 줄이는 것을 효율 KPI로 사용
- single `next_action` planner로 ready set을 직렬화
- 모든 node를 한 worktree에서 처리
- parent/root가 child full suite를 무조건 재실행
- 동일 HEAD·command라는 이유만으로 independent proof까지 차단
- telemetry 누락 때문에 필수 safety QA 중단
- plugin 호출마다 새 agent를 소집
- compact handoff를 근거로 stale 환경정보 재확인을 영구 금지
- generic receipt가 provider-specific 의미를 대체하도록 확장

### 성공 기준

품질 hard floor가 유지되는 상태에서 다음이 감소해야 한다.

- 동일 execution fingerprint·동일 purpose의 중복 command
- 변경 없는 scope의 재빌드·재검증
- worker당 repository/context 재탐색
- parent/root의 child evidence 재검증
- orchestration tick당 provider read
- finding 수정당 fresh worker/reviewer 생성

P0/P1 결함 검출률, integration defect escape, production gate, user-owned change 보존은 악화되면 안 된다.

## 구성요소

### 1. DefinitionArtifact

작업 정의의 provider-neutral 정본이다.

필수 속성:

- `definition_id`, `revision`, `digest`, `previous_digest`
- stable node id
- objective와 acceptance criteria
- parent/child decomposition
- direct `blocked_by`
- gear와 risk hints
- affected paths 또는 scope hints
- review·delivery requirement
- owner gate와 external mutation constraints

외부 provider reference는 artifact 본문에 박지 않고 projection binding으로 분리한다.

### 2. WorkGraphSnapshot

실행 시점의 검증된 그래프 입력이다.

```json
{
  "schema": 1,
  "graph_ref": "provider-neutral-ref",
  "snapshot_digest": "sha256:...",
  "definition_digest": "sha256:...",
  "nodes": [],
  "edges": [],
  "provider_capabilities": [],
  "captured_at": "ISO-8601"
}
```

planner는 graph가 불완전하거나 dependency cycle·stable id 충돌·definition mismatch가 있으면 아무 node도 dispatch하지 않는다.

### 3. DecompositionPolicy

절단 사유는 네 가지다.

1. **병렬 이득**: 독립 worker가 점유해 끝까지 완료할 수 있음
2. **위험 격리**: 독립 rollback 또는 별도 owner gate가 필요함
3. **정보 가치 경계**: 앞 결과가 뒤 계획을 바꾸거나 뒤만 revert할 현실적 가능성이 있음
4. **병렬 해금**: 공통 계약 artifact가 다른 lane을 실제로 열어줌

다음 조건이면 묶는 것이 기본이다.

- 같은 파일·shared component를 수정
- 동일 검증 명령과 UI context를 공유
- 앞 node의 상세 context가 뒤 node 수행에 계속 필요
- 산출물보다 closeout·review 고정비가 큼

### 4. Planner와 ReadyActionSet

planner 입력은 WorkGraphSnapshot, run ledger, valid evidence, resource lease다. 출력은 단일 행동이 아닌 집합이다.

```json
{
  "ready_actions": [],
  "blocked_actions": [],
  "closeout_actions": [],
  "integration_gates": [],
  "stop_reason": null
}
```

- ready node는 dependency·lease·owner gate·runtime capability를 모두 만족해야 한다.
- partial graph/API failure에서는 일부 ready node만 조용히 실행하지 않는다.
- lane 내부는 `worker → optional review → delivery` 순서로 직렬화한다.
- 형제 lane은 실제 공유 자원 lock이 없으면 병렬이다.
- closeout은 base/delivery target 단위로만 직렬화한다.

### 5. Worker lane과 ContextPacket

worker lane은 한 node의 execution lease를 가진다. 전달 context는 전체 transcript가 아니라 canonical packet이다.

```json
{
  "node_id": "...",
  "definition_digest": "sha256:...",
  "objective": "...",
  "acceptance_criteria": [],
  "constraints": {},
  "changed_paths": [],
  "valid_evidence": [],
  "known_environment": {},
  "delivery_requirement": {},
  "owner_gates": []
}
```

known fact에는 source, digest, TTL 또는 invalidation trigger를 붙인다. worker는 유효한 사실을 재도출하지 않지만 stale·충돌·불충분 근거가 있으면 reason과 함께 재확인할 수 있다.

### 6. Worktree·branch manager

- 병렬 변경 node마다 전용 worktree와 branch를 사용한다.
- main worktree HEAD는 orchestration 때문에 trunk를 벗어나지 않는다.
- conflict는 child worktree에서 reverse merge 후 해소하고 영향 검증을 재실행한다.
- 사용자 소유 dirty change가 있는 worktree를 자동 정리·덮어쓰기하지 않는다.
- branch/worktree cleanup은 merge 성공과 별도 상태로 기록하며 cleanup 실패로 이미 성공한 delivery를 실패 처리하지 않는다.

### 7. EdgePolicy

검증·review 강도는 node가 아니라 merge/delivery edge의 누적 위험으로 계산한다.

기본 정책:

| gear | plan | leaf verify | independent review | delivery |
|---|---:|---:|---:|---|
| micro | 선택 | 변경 범위 sanity | 없음 | local FF 가능 |
| normal | 필수 | 변경 범위 검증 | 선택 | local FF 또는 provider delivery |
| major | 필수 | 변경+contract 검증 | 필수 기본 | 격리된 review delivery |

container gear는 child의 최고 gear와 누적 risk로 승격한다. concrete PR·merge 방식은 delivery provider가 실현하며 core는 GitHub PR을 전제하지 않는다.

### 8. VerificationPlanner

검증은 세 계층으로 나눈다.

| 계층 | 검증 |
|---|---|
| leaf | changed test, typecheck, scope-specific command |
| parent/container | merge conflict, interface, shared contract |
| root/integration | 전체 통합본 기준 QualityPlan gate |

finding 수정은 영향받은 scope와 실패 조건만 delta 검증한다. 공유 contract·dependency·toolchain이 바뀌면 영향 범위를 확대한다.

### 9. Evidence와 duplicate guard

`ExecutionFingerprint`:

```text
head + command_digest + environment_digest + tool_version + purpose
+ fresh_requirement_id (fresh-required일 때만)
```

`ExecutionPurpose`:

```text
delta-proof | integration-proof | independent-proof | flake-reproduction
```

definition/node/cycle/unit/target/profile id는 attribution only다. 동일 physical identity라도 criteria, covered path, surface, impact, independence가 맞지 않으면 evidence를 재사용하지 않는다. independent proof나 fresh release artifact는 purpose 또는 fresh requirement를 달리해 별도 실행을 보존한다.

`VerificationReceipt` 필수 필드:

- state/base ref와 scope/criteria digest
- changed paths와 command profile
- environment/tool digest
- coverage와 result
- output artifact digest
- timestamp와 token coverage
- invalidation triggers
- independence class

무효화 조건:

- state/base 변경
- relevant path 또는 shared contract 변경
- dependency/lockfile/toolchain 변경
- environment digest 변경
- conflict resolution 또는 generated artifact 변경
- criteria coverage 부족·ambiguous evidence

### 10. Run ledger와 recovery

local ledger는 event-sourced write-through state다. provider remote state를 복제하는 DB가 아니라 task-worker가 직접 수행한 claim, dispatch, evidence, failure, delivery request를 기록한다.

- successful write는 즉시 ledger에 반영
- resume은 definition/snapshot digest를 재검증
- stale lease는 자동 실행하지 않음
- 같은 finding의 자동 retry는 execution fingerprint 또는 failure class가 바뀔 때만 허용
- run cap 초과는 owner-visible gate를 만들되 필수 safety verification을 자동 삭제하지 않음

### 11. Provider-neutral event

```text
node_claimed
execution_started
evidence_reused
verification_completed
finding_opened
ready_for_review
ready_for_delivery
delivery_completed
execution_failed
execution_blocked
```

event에는 idempotency key, node/run/lease id, state digest, evidence refs를 포함한다. task-github 같은 provider adapter가 이를 외부 상태로 투영한다.

### 12. Public skill surface

| skill | 책임 |
|---|---|
| `task-worker:init` | provider 비탐색 workspace config/state와 안전한 preset 초기화 |
| `task-worker:doctor` | config/state/command-impact policy 준비 상태 읽기 전용 진단 |
| `task-worker:define` | DefinitionArtifact 생성·revision |
| `task-worker:plan` | node 실행 계획과 완료 조건 정리 |
| `task-worker:start` | execution lease·worktree 시작 |
| `task-worker:run` | node 구현 실행 |
| `task-worker:verify` | evidence 생성·재사용 판정 |
| `task-worker:done` | local completion 또는 delivery request 생성 |
| `task-worker:status` | local run/graph 상태와 ready set |
| `task-worker:orchestrate` | provider-neutral graph의 병렬 실행 |

독립 review 자체는 session-review 또는 다른 reviewer provider의 책임이다. task-worker는 review requirement와 packet/receipt contract만 제공한다.

### 13. Telemetry

항상 다음을 구분해 기록한다.

- logical nodes와 physical runs
- ready action과 dispatched action
- evidence eligible/reused/invalidated
- duplicate prevented
- full/delta/integration verification
- elapsed time
- token value와 coverage (`null/unavailable` 허용, 0으로 치환 금지)
- owner intervention과 external mutation

telemetry 누락은 선택적 추가 실행을 제한할 수 있지만 필수 품질·안전 gate를 제거하는 근거가 될 수 없다.

### 14. Conformance fixture

canonical fixture는 기본 `tests/fixtures/studio-verification-contract-v1.json`, leaf 검증 override는 `STUDIO_VERIFICATION_CONTRACT=/private/tmp/studio-verification-contract-v1.json`이다. root digest와 golden input/nested instance digest를 그대로 소비하며 consumer가 fixture를 재작성하지 않는다.

분리 구현은 최소 다음을 replay한다.

- 다중 앱 병렬 polish와 integration QA
- mobile environment 소수 파일 delta QA
- stacked issue tree의 ready leaf·merge-up·evidence reuse
- same-parent sibling closeout
- shared write-set을 잘못 분해한 negative fixture
- GitHub 없는 `record:none` local lifecycle
- session-review가 없는 review-required STOP/fallback
- 사용자 dirty change와 worktree cleanup
