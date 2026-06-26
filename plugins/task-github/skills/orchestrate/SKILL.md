---
name: orchestrate
description: GitHub Issue 트리를 컨테이너 이슈에서 시작해 ready 리프 실행, review-tool relay, conflict-agent, 브랜치트리 머지업, 사람 게이트 STOP까지 자동 구동한다.
---

# orchestrate — Issue tree runner

선택한 **컨테이너** 이슈의 서브트리를 GitHub 상태 기준으로 한 tick씩 진행한다.
GitHub가 SoT이며, spawned/failed set은 현재 실행 중인 in-memory liveness 보조값일 뿐이다.

## 입력

```
$ARGUMENTS:
  {container_issue}
  [--review gear|all|skip]   # 기본: .task-github.yml orchestrate.review-mode 또는 gear
  [--max-workers N]          # v1 기본 1
```

## 전제

1. `.task-github.yml`이 있어야 한다. 없으면 STOP: setup 먼저.
2. `mode: solo`만 허용한다. `team`이면 STOP.
3. `base_branch`는 필수다. GitHub default branch를 추론하지 않는다.
4. reviewer/conflict 자동화는 `review-tool`/`review-command`와 conflict-agent 경로가 있을 때만 실행한다. 없으면 STOP으로 퇴각한다.

설정 확인:

```bash
python3 plugins/task-github/scripts/task_config.py validate --json
```

결정론 판단 helper:

```python
from orchestrator_ops import (
    issue_branch,
    issue_base_branch,
    review_required,
    classify_pr_recovery,
    child_merge_evidence,
    compose_tool_command,
    review_verdict_action,
    conflict_action,
    worker_feedback_handoff,
    plan_tick,
)
```

## 루프

```bash
python3 plugins/task-github/skills/orchestrate/scripts/ready_leaves.py {container_issue} \
  --spawned "$SPAWNED" --failed "$FAILED" --json
```

분기 순서:

1. `ok:false` → `stop_reason` 브리핑 후 종료. 부분 ready-set 스폰 금지.
2. `stuck[]` → STOP. prior run 또는 failed worker는 자동 재시도하지 않는다.
3. `container_done` → PR/close 증거 guard 후 컨테이너 브랜치를 base로 머지.
   - 부모 이슈 있음: `task/issue-{container}` → `task/issue-{parent}` merge + 컨테이너 close.
   - 부모 이슈 없음: `task/issue-{container}` → `.task-github.yml base_branch` merge + 루트 close + wiki task done 처리.
4. `done_parents[]` → 각 부모를 base로 merge+close하고 re-tick. 같은 tick의 ready는 버린다.
5. `review_waiting[]` → review-tool이 설정돼 있으면 reviewer-agent relay, 없으면 STOP(`human_gate_review`). 사람 리뷰/머지 후 재실행.
6. `ready[]` → 최대 `--max-workers`개 work-agent에 위임.

실제 분기 결정은 `plan_tick(ready_state, review_tool=..., review_command=..., max_workers=...)` 결과를 따른다.

v1 worker handoff:

```text
task-github:start {N}
task-github:run {N}
task-github:done {N}
```

work-agent는 start에서 gear를 판단/보고한다. 오케스트레이터는 gear label을 쓰지 않고
보고값을 review/merge 정책 판단에만 읽는다.

## 브랜치트리

- 브랜치명: `task/issue-{N}`
- worktree 경로: `.worktrees/issue-{N}`
- `base_branch(issue N)`:
  - GitHub 부모 이슈 있음 → `task/issue-{parent}`
  - 부모 없음 → `.task-github.yml base_branch`

자식 spawn 전 `ensure_branch(issue N)`로 부모 브랜치를 재귀 보장하고 remote push한다.
브랜치가 없으면 parent base에서 생성한다.

## Review Policy

PR은 항상 생성한다. 리뷰만 정책으로 갈린다.

- `skip`: 모든 PR 자동 머지.
- `gear`: `gear:micro` 자동 머지, `gear:normal|major`는 STOP(`human_gate_review`).
- `all`: 모든 PR STOP(`human_gate_review`).

review-tool이 있으면 `compose_tool_command(review-tool, orchestrate.review-command, target args)`로 호출한다.
`approved`는 merge로, `changes-requested`는 `worker_feedback_handoff()`로 work-agent 재spawn한다.
round cap을 넘으면 STOP(`human_gate_review`).

## Recovery Guards

- 새 PR 생성 전 `head=task/issue-{N}` + expected `base`의 open/merged PR을 재조회한다.
- expected base가 아닌 open PR이 head-only 조회에서 발견되면 STOP(`state_mismatch`).
- parent/container 완료는 `subIssuesSummary.completed`만 믿지 않는다.
  각 child가 no-change close이거나 expected base로 merged된 PR 증거가 있어야 한다.
- `gh pr merge` 충돌은 conflict-agent가 있으면 위임한다. 의미적 모호 충돌 또는 자동 경로 없음은 STOP(`merge_conflict`)이다.

helper 기준:

```bash
python3 - <<'PY'
import sys
sys.path.insert(0, "plugins/task-github/skills/orchestrate/scripts")
import orchestrator_ops as ops
print(ops.issue_base_branch(parent_number=12, base_branch="main"))
PY
```

conflict-agent 산출물은 [agents/conflict-resolver.md](../../agents/conflict-resolver.md)를 따른다.

## 불변식

- 오케스트레이터는 직접 코딩하지 않는다.
- 상태/gear label write는 worker/reviewer 소유다. 오케스트레이터는 issue close와 merge만 수행한다.
- decision/rejected/trial_error wiki capture는 자동 기록하지 않는다. 루트 완료 때 후보만 제시하고 사용자 확인을 받는다.
- v1 `--max-workers 1` 기본. `ponytail:` 병렬 worker liveness는 per-worker timeout까지만, persistent spawned ledger는 실제 재실행 문제가 보일 때 추가.
