---
name: status
description: Issue/root context bundle을 읽어 ready/blocked/review/bridge mismatch/closeout pending 상태와 다음 행동 1개를 JSON으로 요약한다. "task-github:status", "상태 봐줘" 요청에 실행하라.
---

# status — 작업 상태 개관

`open`과 같은 조회를 수행한 뒤 `scripts/context_bundle.py`로 만든 bundle을 `status_next.py`에 넣어 요약한다.

```bash
python3 plugins/task-github/scripts/status_next.py --bundle /tmp/task-github-context.json --json
```

## 출력

- `ready`: 열린 blocker와 bridge mismatch가 없는지
- `blocked`: 열린 `blocked_by`
- `review_needed`: `in-review` 상태
- `bridge_mismatch`: context bundle의 link integrity errors
- `closeout_pending`: review/merge 대기
- `mode`: `topology`/`gate`
- `next_action`: 반드시 1개

## 불변식

- read-only. GitHub/wiki 상태를 바꾸지 않는다.
- bridge mismatch를 발견하면 자동 reconcile하지 않고 `next_action.kind=reconcile`만 제안한다.
