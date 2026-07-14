---
title: Studio 플러그인
created_at: 2026-07-14
summary: native-first 에이전트 팀과 명시적 외부 도구 라우팅, runtime별 agent 정책, 단일 review owner 및 evidence 재사용 설계 정본
tags: [studio, orchestration, routing, review, qa, evidence]
verified_at: 2026-07-14
affects_paths: [plugins/studio/**, plugins/task-worker/**, plugins/task-github/**]
---

## 현재 상태

Studio 0.5.0은 owner의 미션을 research, planning, strategy, design, architecture, implementation, creation, QA, independent review, critique, curation, summarization 역할로 분해하고 ready-set을 병렬 실행하는 상위 orchestration layer다. native harness만으로 전체 흐름을 완주하며 외부 plugin은 기능 필수가 아니다.

## 핵심 불변식

| 불변식 | 계약 |
|---|---|
| native-first | run parameter와 `.studio.yml`에 없는 외부 도구는 discovery/probe하지 않는다. |
| 선택 우선순위 | run parameter > `.studio.yml` > native. explicit unavailable은 STOP, configured unavailable은 설정 fallback을 따른다. |
| worker 단일 소유 | track마다 `native|task-worker|task-github` 하나만 lease한다. task-github 선택 시 task-worker를 별도 lease하지 않는다. |
| review 단일 소유 | review edge마다 `workflow-review-lease/v1` owner가 하나다. Studio와 worker가 같은 리뷰를 이중 dispatch하지 않는다. |
| 병렬성 보존 | 모든 ready action을 계산하고 독립 write-set은 별도 worktree에서 병렬 실행한다. |
| 검증 보존 | independent judgment와 통합 HEAD full gate를 제거하지 않는다. |
| 물리 실행 절감 | 같은 HEAD/command/environment/tool version의 valid evidence는 재사용하고 finding 수정은 delta QA한다. |
| compact handoff | criteria, open finding, changed paths, valid evidence, next action만 전달한다. transcript와 settled context를 다시 수집하지 않는다. |

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

## 경계

- [[task-worker-plugin]]: provider-neutral decomposition, ready-set, worktree execution, verification evidence, integration gate
- [[task-github-plugin]]: GitHub Issue/PR/CI/base-head transport와 merge/closeout
- [[session-review-plugin]]: 선택된 review episode의 독립 판단

Studio는 이 도구를 import하거나 미설정 상태에서 자동 탐색하지 않는다. agent-visible adapter로 선택하고 coarse result와 digest만 연결한다.
