---
name: reconcile
description: context bundle의 bridge mismatch를 명시적으로 복구한다. 기본은 dry-run plan이고, --apply가 있을 때만 wiki CLI로 relate/complete/reopen을 실행한다.
---

# reconcile — explicit mutation

context bundle의 `integrity.errors`를 복구 계획으로 변환한다.

```bash
# dry-run plan
python3 plugins/task-github/scripts/reconcile.py --bundle /tmp/task-github-context.json --json

# apply gate 통과 후에만 mutation
python3 plugins/task-github/scripts/reconcile.py --bundle /tmp/task-github-context.json --apply --json
```

지원 action:
- `task_relation_missing_root` → `wiki relate {TASK} --add-tasks owner/repo#ROOT`
- `root_closed_task_active` → `wiki complete {TASK}`
- `root_open_task_done` → `wiki reopen {TASK}`

## 불변식

- `--apply` 없이는 mutation 없음.
- wiki 파일을 직접 쓰지 않고 wiki CLI만 호출한다.
- branch/worktree/PR metadata로 wiki TASK를 대체하지 않는다.
