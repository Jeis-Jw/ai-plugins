---
name: next
description: task-github context bundle에서 지금 해야 할 다음 행동 1개만 고른다. "task-github:next", "다음 뭐 하지" 요청에 실행하라.
---

# next — 다음 행동 1개

`status`와 같은 입력을 쓰되, 출력에서 `next_action`만 우선 브리핑한다.

```bash
python3 plugins/task-github/scripts/status_next.py --bundle /tmp/task-github-context.json --json
```

우선순위:
1. bridge mismatch → `reconcile`
2. 열린 blocker → `wait`
3. `changes-requested` → `run`
4. `in-review` → `review`
5. `in-progress` → `continue`
6. 열린 leaf → `start`

## 불변식

- read-only.
- 여러 후보를 나열하지 않고 사령관 steering을 줄이기 위해 하나만 고른다.
