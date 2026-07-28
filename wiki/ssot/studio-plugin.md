---
title: Studio 플러그인
created_at: 2026-07-14
summary: native-first 에이전트 팀과 명시적 외부 도구 라우팅, runtime별 agent 정책, 단일 review owner 및 evidence 재사용 설계 정본
tags: [studio, orchestration, routing, review, qa, evidence]
verified_at: 2026-07-29
affects_paths: [plugins/studio/**, plugins/task-worker/**, plugins/task-github/**]
---

## 현재 상태

Studio 0.10.0은 owner의 미션을 research, planning, strategy, design, architecture, implementation, creation, QA, independent review, critique, curation, summarization 역할로 분해하고 ready-set을 병렬 실행하는 상위 orchestration layer다. read-only brainstorm는 pinned bundled Codex app-server의 persistent Production controller를 사용한다. 모든 native crew는 역할 기반으로 인스턴스를 배정하고 인스턴스 수명은 동적 작업 단위 기준으로 관리한다.

Persistent brainstorm Production은 reducer가 phase/order/barrier/maxRounds/dryStop을
전이하고 runtime-owned store가 caller state를 차단하며 revision/digest/lock/atomic rename
fence를 적용한다. Controller는 admission 뒤 pending action마다 durable `request_sent`를
먼저 기록하고 `spawn`에서만 role thread를 만들며 이후 exact same-thread follow-up을
사용한다. action contract는
turn/generation/state digest/transition, canonical label, host-valid immutable `task_name`을
포함한다. exact schema result는 original handle에서 한 번만 repair하며 incomplete cancel은
`recovery_required`다. Physical host handle은 participant, critic, summarizer 역할 간
alias를 fail-closed하며 mixed cancel 결과를 actor별로 기록한다. 병렬 sibling 실패도 drain한
후 interrupt/delete하고, 시작된 workflow lease는 admission TTL 이후에도 정상 cleanup할 수
있다.

Native crew 인스턴스 하나는 명확한 단일 역할을 맡는다. 같은 역할이라도 독립 작업 단위가
여러 개면 별도 인스턴스를 둘 수 있지만 역할명·인원수·A/B 같은 예시 이름은 고정 topology가
아니다. 최초 배정에서만 spawn하고 같은 작업 단위의 의견교류, peer/review 대기, feedback
대응, 재작업, 재검증은 original physical handle에 follow-up한다.

`waiting-for-peer`와 `rework`는 active다. 담당 완료조건 충족과 outstanding peer/review
interaction 0이 함께 확인될 때만 terminal/cleanup한다. 독립 reviewer는 별도 역할·작업
단위·인스턴스로 배정하며 자기 review 단위가 끝날 때까지 유지한다. 이 계약은 brainstorm,
development/pairing, QA, review, critic 등 모든 native crew에 공통이다.

Producer는 owner intent·범위·완료조건을 정본으로 유지하는 Studio control plane이다.
role↔instance↔work-unit mapping과 상태를 관리하고 dependency·질문·산출물·review
feedback을 original instance 사이에 왜곡 없이 relay한다. owner와 전체 상태·gate를
대화하되 산출물을 직접 만들거나 crew 판단을 대리 합성하지 않고, 내부 workflow가 owner
요구를 재정의하거나 범위를 확대하지 못하게 한다.

현재 Production persistence 구현은 read-only brainstorm에 한정한다. 기존
Workflow/Runner, task-worker, task-github, worktree, execution-control을 그대로
사용하며 외부 executor나 continuation handle을 제공하지 않는 호환 경로에는 persistence를
주장하지 않는다. 작업 단위 간 기억과 민감 ContextPack 전송은 지원하지 않는다.

Production scale v1은 backlog item마다 `solo|standard|major`를 정적으로 선택한다. `solo`는
upstream criterion source와 기계적 measure가 있는 item만 crew 1명·1회로 처리한다.
`standard` brainstorm은 최소 cast·2 rounds·dryStop 1이며 outcome-linked 변화가 없으면
수렴한다. `major`는 기존 full ritual 4 rounds·dryStop 2를 보존한다. scale은 reviewer
independence와 직교하고 모든 profile이 QualityPlan hard floor와 통합 HEAD full gate를
그대로 유지한다.

## 초기화와 진단

`studio:init`은 `.studio/` 작업장과 `.studio.yml` 정책을 한 번에 생성한다. 동일 내용은
skip하고 다른 기존 파일은 `--force` 없이 변경하지 않으며, `--dry-run`은 plan과 config
validation만 반환한다. `--worker`와 `--reviewer`는 명시한 provider만 materialize하고
미지정 값은 native로 둔다. init은 provider plugin을 초기화·탐색·probe하거나 외부
서비스를 변경하지 않는다.

`studio:doctor`는 workspace/board와 config schema, 설정된 provider 이름만 읽기 전용으로
진단한다. 설정에 없는 provider는 probe하지 않으며, 선택된 외부 provider의 실제 capability
확인은 producer의 mission-scoped preflight에서 수행한다. `.studio.yml` 부재는 native와
세션 model/effort 상속이 유효하므로 warning이다. 기존 `config scaffold`는 config-only 호환
명령으로 유지한다.

## 핵심 불변식

| 불변식 | 계약 |
|---|---|
| native-first | run parameter와 `.studio.yml`에 없는 외부 도구는 discovery/probe하지 않는다. |
| 선택 우선순위 | run parameter > `.studio.yml` > native. explicit unavailable은 STOP, configured unavailable은 설정 fallback을 따른다. |
| worker 단일 소유 | track마다 `native|task-worker|task-github` 하나만 lease한다. task-github 선택 시 task-worker를 별도 lease하지 않는다. |
| cleanup 단일 소유 | native는 integrator가 정리하고 외부 worker는 cleanup receipt를 반환한다. merged-clean 대상만 정리하며 다른 owner가 반복하지 않는다. |
| review 단일 소유 | review edge마다 `workflow-review-lease/v1` owner가 하나다. Studio와 worker가 같은 리뷰를 이중 dispatch하지 않는다. |
| 병렬성 보존 | 모든 ready action을 계산하고 독립 write-set은 별도 worktree에서 병렬 실행한다. |
| 검증 보존 | independent judgment와 통합 HEAD full gate를 제거하지 않는다. |
| scale 분리 | production 규모는 item별로 결정하고 review owner/independence, task gear와 결합하지 않는다. |
| 물리 실행 절감 | 같은 HEAD/command/environment/tool version의 valid evidence는 재사용하고 finding 수정은 delta QA한다. |
| 실행 허가 | 실제 명령은 canonical permit/profile의 허용 범위를 dispatch·result·evidence 세 경계에서 모두 만족해야 한다. |
| compact handoff | criteria, open finding, changed paths, valid evidence, next action만 전달한다. transcript와 settled context를 다시 수집하지 않는다. |
| native crew lifecycle | 역할 기반으로 배정하고 작업 단위 기준으로 수명을 관리한다. 최초 spawn 뒤 같은 단위의 peer 대기·feedback·재작업·재검증은 original handle에 follow-up한다. |
| terminal gate | `waiting-for-peer`/`rework`는 active다. 담당 완료조건과 outstanding peer/review interaction 0이 함께 확인될 때만 cleanup한다. |
| producer control plane | owner intent·범위·완료조건과 role↔instance↔work-unit mapping을 관리하고 original instance 사이 메시지를 왜곡 없이 relay한다. 산출물 제작·판단 대리 합성은 금지한다. |
| persistence claim | verified native continuation handle이 있는 경로만 persistent라고 부른다. 외부 executor와 isolated Runner에는 persistence를 주장하지 않는다. |
| fallback fence | brainstorm은 명시적인 pre-dispatch `fallback_required`에서만 isolated Runner로 fallback한다. 첫 durable request 뒤에는 중간 fallback이나 replacement spawn을 금지한다. |
| delivery boundary | task-worker가 decomposition·ready-set·worktree·verification·integration gate를, task-github가 GitHub projection/delivery를 소유한다. Studio는 둘을 대체하지 않는다. |

## 도구 라우팅

라우팅 정본은 `studio-routing-plan/v1`이다. canonical fields는 `worker.selected`, `worker.provider`, `reviewer.owner`, `reviewer.provider`, `reviewer.dispatch`, `reviewer.selected`, `review_lease`, `action`, `digest`다.

- `activation:auto`: 설정된 후보의 사용 필요를 Studio가 판단한다. plugin discovery를 허용하는 값이 아니다.
- `activation:always|never`: 설정 후보를 항상 사용하거나 사용하지 않는다.
- `fallback:native|stop`: 설정 provider unavailable 시 동작이다. explicit run override에는 fallback을 적용하지 않고 STOP한다.
- capability는 선택된 provider만 `(mission_id, provider, environment_digest)`당 한 번 `studio-capability-snapshot/v1`으로 확인한다.

## Agent runtime 정책

현재 runtime profile은 `claude|codex`다. stable `agentId`별 model/effort를 설정하며 각 필드는 blank/null이면 다음 층으로 fallthrough한다.

```text
run override
> provider ritual > common ritual
> provider agent > common agent
> provider role > common role
> provider defaults > common defaults
> session inherit
```

runtime override는 policy profile 선택이며 실제 harness capability를 새로 만들지 않는다. non-null profile이 verified host runtime과 다르면 `runtime-capability-required`이며 dispatch하지 않는다. `studio-runtime-capability/v1`은 runtime/version과 advertised model/effort set을 정규화한다. 광고 집합이 있으면 resolved non-null 값을 fail-closed 검증하고, 없으면 지원 상태는 `unknown`이다. model/effort는 global provider allowlist로 추정하지 않는다. brainstorm/pairing broker에는 matching verified capability가 있을 때만 runtime을 넘기며 stable agentId와 `roleId || name` 정책 key를 사용한다. `role`은 표시용이다.

## Review lease

review가 필요한 edge만 exact `workflow-review-lease/v1`을 만든다. 필드는 `schema, lease_id, owner, provider, episode_id, edge_id, requirement, criteria_digest, evidence_refs, digest`다.

- `owner=studio`: Studio가 native 또는 session-review reviewer를 dispatch한다. task-worker/task-github는 `externally-owned/skip` permit과 handoff만 반환한다.
- `owner=task-worker`: Studio reviewer dispatch를 금지하고 worker/provider의 기존 review 흐름을 유지한다.
- Edge ledger는 capability 확인 전 `pending` reservation과 dispatch 가능한 `accepted` binding을 구분한다. Studio-owned `provider=session-review`가 unavailable이고 fallback이 native이면 cached capability로 `review-lease-replan-required`를 반환하고, 동일 mission/edge/lease identity에서 provider만 `native`로 바꾼 exact target lease를 authorization에 넣는다. 그 target만 pending→accepted 전이가 가능하며 accepted binding과 구형 digest-only binding은 immutable이다.
- task-github의 Studio-owned handoff에서도 PR 생성, CI/preflight, `in-review`/`review_waiting`, base/head transport, closeout lane은 유지한다. 동일 lease의 approved verdict와 필수 evidence 전에는 closeout을 금지한다.
- 리뷰가 없으면 lease가 없다.

## QA 배치

```text
개발 중 변경 범위 최소 검증
→ 통합 HEAD 전체 QA 1회
→ finding별 영향 범위 delta QA
```

full QA를 각 track에서 반복하지 않지만, shared contract/dependency surface/impact unknown/independence-required와 최종 통합 gate는 machine-readable reason으로 유지한다. Release artifact, device, production environment처럼 fresh execution 자체가 완료 조건인 검증은 기존 evidence와 다른 key로 실행한다.

## Native execution control

실행 정본은 `studio-verification-contract-set/v1`이며 exact digest는
`sha256:7df570d1faaba445865c74fd6dffff73178f0102cd3a5728183abf6791ce2b65`다.
Studio runtime 기본 artifact는 package 내부
`plugins/studio/contracts/studio-verification-contract-v1.json`이고,
repo 최상위 `tests/fixtures/studio-verification-contract-v1.json`은 task-worker가 소비하는
공유 golden source이자 Studio package artifact와의 distribution parity 기준이다.
leaf 검증에서만 `STUDIO_VERIFICATION_CONTRACT`로 같은 digest의 artifact를 주입한다.
Studio와 worker 어느 쪽도 schema 축약본이나 parity가 검증되지 않은 재직렬화 복제본을
정본으로 삼지 않는다.

- `execution-permit/v1`과 `command-profile/v1`은 executable/args/cwd/env와 command digest를 고정한다. 실제 명령은 `execution dispatch`에서 profile을 벗어나면 claim 전에 거부되고, command receipt와 verification evidence도 같은 binding을 다시 검증한다.
- 물리 key는 `head + command_digest + environment_digest + tool_version + purpose`의 canonical digest다. fresh gate에는 `fresh_requirement_id`를 추가한다. cycle/unit/target은 attribution이며 중복 실행 identity가 아니다.
- claim은 board lock 안에서 원자적으로 생성한다. active duplicate는 거부하고 성공 evidence는 재사용하며, 실패 retry가 `max_physical_runs`에 닿으면 owner-visible pause다.
- evidence 재사용은 physical identity뿐 아니라 criteria/path/surface/impact/purpose/independence까지 일치해야 한다. invalidation은 새 canonical digest로 한 번 기록한 뒤 되돌리지 않는다. final 독립 판단, integration HEAD full gate, release/device/production preflight는 fresh permit을 요구한다.
- capability 실패는 `(mission_id, capability_id, environment_digest)`에 한 번 기록해 병렬 track이 같은 probe를 반복하지 않는다. 외부 mutation은 passed preflight를 요구하고, 비용이 있으면 owner-approved authorization quota를 mutation 전에 원자 claim한다. consumption과 mutation receipt는 서로의 최종 ref/digest를 교차 검증한다.
- token telemetry는 permit의 `fail-closed|report-only`를 따른다. null/unavailable을 0으로 계산하지 않는다. closeout은 integration HEAD에 적용 가능한 verification/review/delivery/mutation/cleanup/user-change ref와 zero open finding을 reconciliation한 뒤에만 완료한다.
- broker receipt의 model call은 actual reducer result ledger와 교차 검증한다. 구현과 분리된
  reviewer가 승인한 sealed 4-scenario input/response tape에서 각 criterion floor 100점과
  quality degradation 0%를 확인했다. 동일 3인 cast의 기존 full 21 calls 대비 persistent
  standard 13 calls는 38.10%의 **profile 효율 하한**이며 native adapter, wall-time, token,
  physical process 절감 주장이 아니다. elapsed/token coverage는 unavailable이다.
- development 보정-loop 합성 E2E는 actual logical turns 5개를 유지하면서 fresh-thread
  topology baseline 5개 대비 persistent role thread 3개를 사용해 thread start를 40% 줄였다.
  모든 permit-bound verification은 pass했으며 target late write는 없었다. 이 수치는
  wall-time/token 또는 production workload 평균 절감 주장이 아니다.
- `execution summary`는 board를 변경하지 않고 logical check, physical run, full/delta QA, reuse/duplicate 방지, capability cache, token coverage, owner intervention, external spend를 `efficiency-summary/v1`로 투영한다.

이 control plane은 명령을 직접 실행하거나 provider API를 호출하지 않는다. Studio native harness와
선택적 external executor가 같은 permit/receipt 경계를 소비하며, product별 Render/Expo/Vite/Canvas
규칙이나 범용 CI scheduler는 core에 두지 않는다.

## 경계

- [[task-worker-plugin]]: provider-neutral decomposition, ready-set, worktree execution, verification evidence, integration gate
- [[task-github-plugin]]: GitHub Issue/PR/CI/base-head transport와 merge/closeout
- [[session-review-plugin]]: 선택된 review episode의 독립 판단

Studio는 이 도구를 import하거나 미설정 상태에서 자동 탐색하지 않는다. agent-visible adapter로 선택하고 coarse result와 digest만 연결한다.
