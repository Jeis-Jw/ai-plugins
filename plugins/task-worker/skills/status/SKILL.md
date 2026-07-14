---
name: status
description: DefinitionArtifact와 local run ledger를 읽어 ready, blocked, active, completed 상태를 구조화해서 보여준다. 상태를 변경하지 않는다. "task-worker:status", "작업 상태 봐줘", "ready 작업 알려줘" 요청에 사용한다.
---

# status

읽기 전용이다. 단일 next action이 아니라 전체 ready set을 반환한다.

```bash
python3 "${TASK_WORKER_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/definition_artifact.py" ready \
  --artifact {ARTIFACT} --state-dir .task-worker/local/runs
```

`ready_actions[]`, `manual_actions[]`, `blocked[]`, `active[]`, `completed[]`, `integration_candidates[]`를 그대로 보고한다. 여러 ready action을 임의로 직렬화하지 않는다. 중복 active run이나 schema ambiguity는 fail-closed 오류로 올린다.

세션이 바뀌었으면 artifact/run path를 대화에서 복원하지 말고 persistent binding을 조회한다.

```bash
python3 "${TASK_WORKER_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/definition_artifact.py" resume \
  --ref {task-worker:DEFINITION|TASK-ID|owner/repo#N} --state-root .task-worker/local
```

provider adapter가 공급한 `task-worker.work-graph/v1` 상태는 `plan-graph --snapshot`으로 같은 planner를 사용한다. `integration_candidates[]`는 구현 leaf가 아니라 별도 integration gate 대상이다.
