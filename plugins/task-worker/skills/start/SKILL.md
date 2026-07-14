---
name: start
description: DefinitionArtifact의 ready leaf 또는 준비된 integration candidate를 stable branch/worktree identity에 pin한 local run으로 시작한다. "task-worker:start", "이 작업 시작해", "artifact node 시작" 요청에 사용한다.
---

# start

먼저 `status` 또는 `ready` 결과에서 node를 선택한다. 여러 ready leaf를 처리할 때는 하나만 고르지 말고 `orchestrate`로 병렬 dispatch한다.

```bash
python3 "${TASK_WORKER_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/definition_artifact.py" local-start \
  --artifact {ARTIFACT} --node {KEY_OR_NODE_ID} --state-dir .task-worker/local/runs
```

출력의 `identity.branch`, `identity.worktree`, run-state `path`를 그대로 사용한다. 기존 run이면 새 실행을 만들지 않고 같은 state를 반환한다. worktree 생성 전 사용자 소유 dirty change를 확인하고 덮어쓰지 않는다.

- `dispatch: manual`은 ready/manual set만 계산하고 local run을 만들지 않는다.
- child가 모두 닫힌 container/root는 `run_kind: integration`으로 시작할 수 있다. child가 열려 있으면 fail-closed한다.
