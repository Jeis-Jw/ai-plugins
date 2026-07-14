---
name: done
description: verified task-worker local run을 delivery 정책에 맞게 완료하고 closeout receipt를 만든다. local-ff와 external delivery 요청을 구분한다. "task-worker:done", "작업 마무리해", "run-state 닫아줘" 요청에 사용한다.
---

# done

`verified` 상태와 검증 evidence를 확인한 뒤 마무리한다.

- `local-ff`: 대상 branch로 안전하게 FF한 뒤 `done`, cleanup 뒤 `closeout`.
- `external`: 임의로 PR/merge를 수행하지 않는다. adapter에 delivery request를 넘기고 provider receipt가 확인된 뒤 닫는다.
- 사용자 소유 dirty change, branch, worktree를 무단 삭제하지 않는다.
- binding에 provider가 있으면 closeout 결과를 provider adapter에 전달하고 성공 receipt를 `provider-event`로 기록한다. task-worker core가 Wiki/GitHub API를 직접 호출하지 않는다.

```bash
python3 "${TASK_WORKER_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/definition_artifact.py" local-event \
  --artifact {ARTIFACT} --run-state {RUN_STATE} --event done
python3 "${TASK_WORKER_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/definition_artifact.py" local-event \
  --artifact {ARTIFACT} --run-state {RUN_STATE} --event closeout
python3 "${TASK_WORKER_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/definition_artifact.py" receipt \
  --run-state {RUN_STATE} --workflow task-worker --out .task-worker/local/receipts/{RUN_ID}.json
python3 "${TASK_WORKER_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/definition_artifact.py" provider-event \
  --ref {DEFINITION_OR_TASK_REF} --provider {ADAPTER} --event completed \
  --receipt {PROVIDER_RECEIPT_JSON} --state-root .task-worker/local
```
