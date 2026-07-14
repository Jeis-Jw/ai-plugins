# task-worker 설계 계약

## 불변식

1. **분해 품질을 비용 절감 수단으로 축소하지 않는다.** 독립 책임·위험·rollback 경계는 논리 node로 유지한다.
2. **병렬성을 보존한다.** planner는 모든 실행 가능 leaf를 `ready_actions[]`로 반환한다.
3. **동시 write를 격리한다.** 각 leaf는 stable branch/worktree identity를 갖는다.
4. **검증 사실만 재사용한다.** 변경된 scope·criteria·artifact revision은 기존 pin을 무효화한다.
5. **provider 상태를 core에 넣지 않는다.** Issue, PR, label, Studio track, wiki node는 adapter binding이다.
6. **review owner는 edge당 하나다.** review가 필요한 edge만 review lease를 갖고 reviewer dispatch 전에 permit을 소비한다.
7. **추가 agent hop을 만들지 않는다.** plugin 호출 경계와 execution episode 경계는 동일하지 않다.

## 0.2.0 경계

- 새 canonical schema는 `task-worker.definition/v1`, `task-worker.local-run/v1`이다.
- 기존 local artifact/run을 버리지 않도록 task-github v1 schema는 read-compatible하다.
- 새 artifact에는 provider-specific `record`를 허용하지 않는다.
- external delivery는 provider-neutral `external`로만 표현한다.
- provider adapter는 `task-worker.work-graph/v1` snapshot을 공급하고 `task-worker.ready-plan/v1`을 소비한다.
- planner는 모든 ready leaf와 자식 완료로 새 통합 상태가 생긴 container/root를 각각 `ready_actions[]`, `integration_candidates[]`로 반환한다.
- `capabilities`가 지원 command와 exact contract schema를 공개하며 adapter는 불일치 시 fail-closed한다.
- GitHub projection과 remote delivery 코드는 task-github에 남긴다.
- generic evidence cache와 command fingerprint는 별도 후속 기능이다. 0.2.0은 기존 task-github evidence gate를 이동하지 않고 execution core 중복 제거와 planner 위임을 완료한다.

## 상태 모델

```text
started → running → verified → done → closed
```

각 전이는 idempotent하다. `verify` event에는 구조화된 evidence를 붙인다. `ready`는 같은 artifact digest에 pin된 closed blocker만 완료로 인정하며, active run이 중복되면 fail-closed한다. provider snapshot에서는 unknown blocker를 미해결로 유지하고 dependency cycle이면 부분 ready set도 반환하지 않는다.

## 0.4.0 review lease

`review_leases[]`는 provider dependency가 아니라 reviewer 소유권 fencing이다. exact fields는 `schema, lease_id, owner, provider, episode_id, edge_id, requirement, criteria_digest, evidence_refs, digest`이며 canonical digest와 `lease_id`/`edge_id` 유일성을 검증한다.

- `owner=studio`: task-worker reviewer dispatch 금지, `externally-owned/skip` handoff 반환
- `owner=task-worker`: 기존 native/session-review 선택과 feedback loop 유지
- lease 없음: standalone 기존 local review policy 유지

lease는 review를 제거하지 않고 중복 dispatch만 막는다. node run, verification evidence, done, integration candidate gate는 기존 계약대로 실행한다.
