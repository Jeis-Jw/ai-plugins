# task-worker 설계 계약

## 불변식

1. **분해 품질을 비용 절감 수단으로 축소하지 않는다.** 독립 책임·위험·rollback 경계는 논리 node로 유지한다.
2. **병렬성을 보존한다.** planner는 모든 실행 가능 leaf를 `ready_actions[]`로 반환한다.
3. **동시 write를 격리한다.** 각 leaf는 stable branch/worktree identity를 갖는다.
4. **검증 사실만 재사용한다.** 변경된 scope·criteria·artifact revision은 기존 pin을 무효화한다.
5. **provider 상태를 core에 넣지 않는다.** Issue, PR, label, Studio track, wiki node는 adapter binding이다.
6. **추가 agent hop을 만들지 않는다.** plugin 호출 경계와 execution episode 경계는 동일하지 않다.

## 0.1.0 경계

- 새 canonical schema는 `task-worker.definition/v1`, `task-worker.local-run/v1`이다.
- 기존 local artifact/run을 버리지 않도록 task-github v1 schema는 read-compatible하다.
- 새 artifact에는 provider-specific `record`를 허용하지 않는다.
- external delivery는 provider-neutral `external`로만 표현한다.
- GitHub projection과 remote delivery 코드는 task-github에 남긴다.
- generic evidence cache와 command fingerprint는 후속 task-worker 단계에서 확장한다. 0.1.0은 artifact pin과 lifecycle evidence를 먼저 독립시킨다.

## 상태 모델

```text
started → running → verified → done → closed
```

각 전이는 idempotent하다. `verify` event에는 구조화된 evidence를 붙인다. `ready`는 같은 artifact digest에 pin된 closed blocker만 완료로 인정하며, active run이 중복되면 fail-closed한다.
