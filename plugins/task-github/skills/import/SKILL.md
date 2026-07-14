---
name: import
description: 기존 GitHub Issue Tree를 DefinitionArtifact, work graph snapshot, provider binding으로 가져와 외부 개발자 위임 또는 task-worker 실행에 사용한다. "task-github:import", "이슈트리를 워커로 가져와", "기존 이슈트리 실행해" 요청에 사용한다.
---

# import

GitHub root Issue와 모든 sub-issue/dependency/body/label 상태를 한 번 읽어 task-worker의 immutable definition, normalized graph, compact context, persistent binding으로 저장한다.

```bash
python3 "${TASK_GITHUB_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/issue_tree_import.py" \
  --root {ROOT_ISSUE} --dispatch manual --state-root .task-worker/local --json
```

## 실행 방식

- `--dispatch manual`: Issue Tree만 업무 지시/분배 정본으로 사용한다. `manual_actions[]`를 반환하며 task-worker local run/worktree를 만들지 않는다.
- `--dispatch worker`: 같은 ready set을 task-github orchestrate가 bounded parallel로 실행한다. GitHub label/PR/merge/closeout은 계속 task-github가 소유한다.
- `--wiki-task TASK-...`: 기존 Wiki root TASK를 같은 binding alias에 연결한다. leaf별 Wiki TASK는 만들지 않는다.

이미 import한 root ref는 binding으로 재개한다. 동일 Issue Tree를 새 definition으로 중복 import하지 않는다. GitHub 상태가 바뀌면 adapter가 graph snapshot을 refresh한 뒤 binding revision을 갱신한다.
