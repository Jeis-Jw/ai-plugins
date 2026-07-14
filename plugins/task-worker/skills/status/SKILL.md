---
name: status
description: DefinitionArtifact와 local run ledger를 읽어 ready, blocked, active, completed 상태를 구조화해서 보여준다. 상태를 변경하지 않는다. "task-worker:status", "작업 상태 봐줘", "ready 작업 알려줘" 요청에 사용한다.
---

# status

읽기 전용이다. 단일 next action이 아니라 전체 ready set을 반환한다.

```bash
python3 "${TASK_WORKER_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/definition_artifact.py" ready \
  --artifact {ARTIFACT} --state-dir .task-worker/runs
```

`ready_actions[]`, `blocked[]`, `active[]`, `completed[]`를 그대로 보고한다. 여러 ready action을 임의로 직렬화하지 않는다. 중복 active run이나 schema ambiguity는 fail-closed 오류로 올린다.
