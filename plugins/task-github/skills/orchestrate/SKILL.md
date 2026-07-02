---
name: orchestrate
description: GitHub Issue 트리를 컨테이너 이슈에서 시작해 ready 리프 실행, review-tool relay, conflict-agent, 브랜치트리 머지업, 사람 게이트 STOP까지 자동 구동한다.
---

# orchestrate — Issue tree runner

선택한 **컨테이너** 이슈의 서브트리를 한 tick씩 진행한다.
GitHub가 SoT지만, 실행 중에는 `.task-github/orchestrate/{container}.json` write-through ledger를 우선 읽는다. GitHub 재조회는 시작/재개, 실패 복구, 긴 대기 후, CI/mergeability/reviewDecision 확인, 최종 closeout 검증 같은 boundary에서만 한다.

## 입력

```
$ARGUMENTS:
  {container_issue}
  [--review gear|all|skip]   # 기본: .task-github.yml orchestrate.review-mode 또는 gear
  [--max-workers N]          # 기본: .task-github.yml orchestrate.max-workers 또는 3
  [--pipeline]               # worker/review lane을 background dispatch하고 완료 이벤트마다 re-tick
```

## 전제

1. `.task-github.yml`이 있어야 한다. 없으면 STOP: setup 먼저.
2. `mode: solo`만 허용한다. `team`이면 STOP.
3. `base_branch`는 필수다. GitHub default branch를 추론하지 않는다.
4. reviewer/conflict 자동화는 `review-tool`/`review-command`와 conflict-agent 경로가 있을 때만 실행한다. 없으면 STOP으로 퇴각한다.
5. flow option 우선순위는 commander 지시 > `.task-github.yml` `orchestrate.gear-options`/`orchestrate.max-workers` > 시스템 기본값이다. `max-workers`는 `review-mode`와 같은 우선순위 규칙을 따른다: commander가 `--max-workers`를 명시하면 그 값, 없으면 config의 `orchestrate.max-workers`, 그것도 없으면 시스템 기본값 3.

설정 확인:

```bash
python3 plugins/task-github/scripts/task_config.py validate --json
```

결정론 판단 helper:

```python
from orchestrator_ops import (
    issue_branch,
    issue_base_branch,
    flow_policy,
    plan_required,
    verify_required,
    pr_review_required,
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

초기/재개 boundary:
```bash
LEDGER=".task-github/orchestrate/{container_issue}.json"
python3 plugins/task-github/skills/orchestrate/scripts/ready_leaves.py {container_issue} \
  --reconcile-github "$LEDGER" --json
```

평상시 tick:
```bash
python3 plugins/task-github/skills/orchestrate/scripts/ready_leaves.py \
  --from-ledger "$LEDGER" --json
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

실제 분기 결정은 `plan_tick(ready_state, review_tool=..., review_command=..., max_workers=..., pipeline=...)` 결과를 따른다.
`--pipeline`이거나 `--max-workers > 1`이면 foreground 병렬 batch로 worker를 호출하지 않는다. worker/reviewer는 issue별 background lane으로 dispatch하고, lane 하나가 완료될 때마다 ledger를 갱신한 뒤 즉시 re-tick한다. foreground batch는 모든 worker가 반환될 때까지 orchestrator 턴이 막혀 first-finisher PR review가 long-pole worker 뒤로 밀리므로 병렬 모드에서 금지한다.

v1 worker handoff:

```text
task-github:start {N}
task-github:run {N}
task-github:done {N}
```

work-agent는 start에서 gear를 판단/보고한다. 오케스트레이터는 gear label을 쓰지 않고
보고값을 review/merge 정책 판단에만 읽는다.

## Gear Flow Policy

기본값:

| gear | plan | verify | pr-review |
|---|---:|---:|---:|
| `gear:micro` | x | o | x |
| `gear:normal` | o | o | x |
| `gear:major` | o | o | o |

설정 예:

```yaml
orchestrate:
  gear-options:
    micro:
      plan: false
      verify: true
      pr-review: false
    normal:
      plan: true
      verify: true
      pr-review: false
    major:
      plan: true
      verify: true
      pr-review: true
```

값은 `true/false` 또는 `o/x`를 받는다. 비어 있으면 시스템 기본값을 쓴다. commander가 현재 실행에서 명시 지시한 값이 있으면 그 지시가 설정과 기본값보다 우선한다.

## Pipeline Mode

pipeline lane은 `worker → review → merge` 순서만 issue 내부에서 직렬화한다. 형제 lane끼리는 dependency, parent/container branch merge, shared index conflict처럼 실제 공유 자원이 있을 때만 동기화한다.

1. ledger 초기화/로드:
   ```bash
   LEDGER=".task-github/orchestrate/{container_issue}.json"
   python3 plugins/task-github/skills/orchestrate/scripts/orchestrate_ledger.py "$LEDGER" --json
   python3 plugins/task-github/skills/orchestrate/scripts/ready_leaves.py {container_issue} --reconcile-github "$LEDGER" --json
   ```
2. `plan_tick(..., pipeline=True)`가 `dispatch_background_workers`를 반환하면 issue별 worker를 background로 띄우고 즉시 ledger에 spawned를 기록한다.
   ```bash
   python3 plugins/task-github/skills/orchestrate/scripts/orchestrate_ledger.py "$LEDGER" --spawned "4 6 7 8" --json
   ```
3. worker 완료 callback/notification을 받으면 해당 issue를 completed로 제거하고 바로 re-tick한다. 이 re-tick에서 완료된 PR은 `review_waiting[]`에 나타나며, 남은 worker가 계속 도는 중이어도 review lane을 background로 dispatch한다.
   ```bash
   python3 plugins/task-github/skills/orchestrate/scripts/orchestrate_ledger.py "$LEDGER" --completed "7" --json
   python3 plugins/task-github/skills/orchestrate/scripts/ready_leaves.py --from-ledger "$LEDGER" --json
   ```
4. worker failure/timeout callback은 failed로 기록하고 re-tick한다. `ready_leaves.py`는 `in-progress` + failed issue를 `stuck(reason=spawned_failed)`로 올려 자동 재시도를 막는다.

`--spawned`/`--failed` 직접 전달도 유지하되, 포맷은 comma/space mixed-separated issue numbers다(`"4,6 7"` 가능). pipeline 모드의 실행 중 상태는 ledger 파일이다. 성공한 write는 `orchestrate_ledger.py --event ...` 또는 closeout의 `--orchestrate-ledger`로 즉시 반영하고, read-after-write를 위해 GitHub를 다시 읽지 않는다.

`ready_leaves.py`는 `ok:false`에서도 유효 JSON을 stdout에 출력한다. 호출부는 `subprocess.check_output`로 exit 1을 치명 처리하지 말고 stdout JSON의 `stop_reason`을 먼저 읽는다. `api_failure`처럼 JSON 생성 자체는 됐지만 외부 조회가 실패한 경우만 hard STOP으로 다룬다.

## 브랜치트리

- 브랜치명: `task/issue-{N}`
- worktree 경로: `.worktrees/issue-{N}`
- `base_branch(issue N)`:
  - GitHub 부모 이슈 있음 → `task/issue-{parent}`
  - 부모 없음 → `.task-github.yml base_branch`

자식 spawn 전 `ensure_branch(issue N)`로 부모 브랜치를 재귀 보장하고 remote push한다.
브랜치가 없으면 parent base에서 생성한다.

## PR Review Policy

PR은 항상 생성한다. 리뷰만 정책으로 갈린다.

- `skip`: 모든 PR 자동 머지.
- `gear`: `flow_policy(...)["pr-review"]`를 따른다.
- `all`: 모든 PR STOP(`human_gate_review`).

review-tool이 있으면 `compose_tool_command(review-tool, orchestrate.review-command, target args)`로 호출한다.
`approved`는 merge로, `changes-requested`는 `worker_feedback_handoff()`로 work-agent 재spawn한다.
round cap을 넘으면 STOP(`human_gate_review`).

`pr-review:false`인 작업은 worker verification + CI success + mergeState CLEAN이면 review 없이 merge한다. `pr-review:true`인 작업도 review 요청 전에 완료조건/런타임 evidence를 먼저 sanity check하고, 불가능하면 scope split/follow-up/blocker를 만든 뒤 review한다.

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
- `--max-workers` 기본은 commander 지시 > `.task-github.yml orchestrate.max-workers` > 시스템 기본값(3) 순으로 정한다. ledger는 spawned/failed뿐 아니라 root snapshot, derived issue/PR state, events를 보관한다. 문제 발생 시 `--reconcile-github`로 GitHub SoT를 다시 덮어쓴다.
