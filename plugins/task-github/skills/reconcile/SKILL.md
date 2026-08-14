---
name: reconcile
description: task-github status나 doctor가 wiki TASK↔GitHub bridge mismatch를 보고했고 사용자가 정합성 복구를 요청했을 때 reconcile plan을 만든다. 기본은 dry-run이며 명시적 --apply가 있을 때만 relate, complete 또는 reopen을 실행한다. 정상 linkage나 일반 상태 조회에는 사용하지 않는다.
---

# reconcile — explicit mutation

context bundle의 `integrity.errors`를 복구 계획으로 변환한다.

```bash
# dry-run plan
python3 "${TASK_GITHUB_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/reconcile.py" --bundle /tmp/task-github-context.json --json

# apply gate 통과 후에만 mutation
python3 "${TASK_GITHUB_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/reconcile.py" --bundle /tmp/task-github-context.json --apply --json
```

지원 action:
- `task_relation_missing_root` → `wiki relate {TASK} --add-tasks owner/repo#ROOT`
- `root_closed_task_active` → `wiki complete {TASK}`
- `root_open_task_done` → `wiki reopen {TASK}`

## 불변식

- `--apply` 없이는 mutation 없음.
- wiki 파일을 직접 쓰지 않고 wiki CLI만 호출한다.
- branch/worktree/PR metadata로 wiki TASK를 대체하지 않는다.
