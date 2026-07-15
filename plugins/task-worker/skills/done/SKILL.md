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
- `owner=studio` review lease는 reviewer dispatch만 외부 소유다. verified/done/integration evidence와 provider delivery receipt를 억제하지 않는다.

`local-ff` merge/FF가 확인되면 아래 결정적 cleanup을 실행한다. primary, dirty, unmerged
worktree/branch는 항상 보존한다. Studio나 provider가 execution owner가 아니면 같은 cleanup을
중복 실행하지 않고 이 receipt를 소비한다.

```bash
python3 "${TASK_WORKER_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/cleanup.py" \
  --repo {REPO_ROOT} --base {TARGET_BRANCH} --branch {WORK_BRANCH} \
  --worktree {WORKTREE_PATH} --json
```

cleanup이 막히면 merge fact는 되돌리지 않고 run을 `cleanup_pending`으로 유지해 같은 명령으로
재개한다. 성공한 `task-worker.cleanup-receipt/v1`을 `cleanup_receipt_refs`에 연결한 뒤에만
`closeout` event와 최종 receipt를 기록한다.

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
