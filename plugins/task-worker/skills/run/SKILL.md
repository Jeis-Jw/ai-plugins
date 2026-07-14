---
name: run
description: 시작된 task-worker local run을 격리된 worktree에서 구현하고 running 상태로 전이한다. 기존 context와 artifact pin을 재사용하며 plugin 경계 때문에 fresh session을 만들지 않는다. "task-worker:run", "작업 실행해", "run-state 수행" 요청에 사용한다.
---

# run

## 절차

1. `recover`로 현재 상태와 다음 event를 확인한다.
2. artifact node의 body, affects_paths, 완료 조건만 compact context로 사용한다.
3. `identity`의 branch/worktree가 없으면 생성하고, 다른 active leaf와 같은 worktree를 쓰지 않는다.
4. 상태가 `started`이면 `run` event를 기록한다.
5. 구현 중 최소 검증을 수행하되 root/integration full QA를 leaf마다 반복하지 않는다.

```bash
python3 "${TASK_WORKER_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/definition_artifact.py" recover \
  --artifact {ARTIFACT} --run-state {RUN_STATE}
python3 "${TASK_WORKER_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/definition_artifact.py" local-event \
  --artifact {ARTIFACT} --run-state {RUN_STATE} --event run
```

코드·설정·제품별 검증 명령은 저장소의 완료 조건과 운영 정책을 따른다. 외부 mutation과 비용 gate는 caller 승인 없이 실행하지 않는다.
review lease는 reviewer dispatch의 소유권만 정한다. `owner=studio`여도 구현 run과 변경 범위 최소 검증은 그대로 수행한다.
