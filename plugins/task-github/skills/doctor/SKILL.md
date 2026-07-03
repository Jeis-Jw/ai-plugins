---
name: doctor
description: task-github 운영 전제와 wiki TASK↔GitHub ROOT linkage를 진단한다. 기본은 diagnose-only이며 상태를 바꾸지 않는다. "task-github:doctor", "doctor --json" 요청에 실행하라.
---

# doctor — diagnose only

prereq snapshot과 context bundle을 입력으로 받아 진단만 한다.

```bash
python3 "${TASK_GITHUB_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/doctor.py" --input /tmp/task-github-doctor.json --json
```

진단 항목:
- labels
- gh auth
- `.task-github.yml` parse/required keys (`mode`, `base_branch`, `orchestrate.review-mode`)
- dependency API
- `.worktrees/` ignore
- `.worktreeinclude`
- wiki/session-review availability
- nested repo guard
- context bundle link integrity

config 진단은 helper를 쓴다:

```bash
python3 "${TASK_GITHUB_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/task_config.py" validate --json
```

## 불변식

- 기본은 **read-only**. 라벨 생성, wiki `relate/complete/reopen`, GitHub comment/label/close를 하지 않는다.
- 복구가 필요하면 `reconcile --apply`로 넘어간다. `doctor --fix`는 명시 mutation alias로만 취급하고, 자동 silent mutation은 금지한다.
