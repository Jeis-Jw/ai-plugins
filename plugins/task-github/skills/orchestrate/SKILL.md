---
name: orchestrate
description: GitHub Issue 트리를 컨테이너 이슈에서 시작해 ready 리프 실행, review-tool relay, conflict-agent, 브랜치트리 머지업, 사람 게이트 STOP까지 자동 구동한다.
---

# orchestrate — Issue tree runner

선택한 **컨테이너** 이슈의 서브트리를 한 tick씩 진행한다.
GitHub가 SoT지만, 실행 중에는 `.task-github/orchestrate/{container}.json` write-through ledger를 우선 읽는다. GitHub 재조회는 시작/재개, 실패 복구, 긴 대기 후, CI/mergeability/reviewDecision 확인, 최종 closeout 검증 같은 boundary에서만 하고, `github_reads`에 reason을 남긴다. 같은 tick 안의 ready 판단은 `--from-ledger` decision으로 기록하고 GitHub read count를 늘리지 않는다.

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
    gear_of_labels,
    container_gear_promotion,
    ff_merge_command,
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
3. `container_done` → close 증거 guard 후 컨테이너 브랜치를 base로 머지업한다. **머지 경로는 컨테이너의 computed gear로 갈린다** — ledger item·`plan_tick` merge_container action이 `gear` 필드를 실어 온다(자식 위로 누적된 [[Gear Flow Policy]]의 cumulative gear). 컨테이너 브랜치는 순수 ref다 — worktree/checkout 없이 FF로만 전진한다:
   - **major(또는 승격된) 컨테이너**: 통합 PR을 만들어 리뷰 게이트를 태운다. epic/컨테이너 브랜치는 worker가 없어 PR이 자동 생성되지 않으므로 오케스트레이터가 직접 만든다.
     - 부모 이슈 있음: `gh pr create --base task/issue-{parent} --head task/issue-{container}` → review-tool relay/human gate → `merge {PR}` → 컨테이너 close.
     - 부모 이슈 없음: `gh pr create --base {base_branch} --head task/issue-{container}` → review-tool relay/human gate → `merge {PR}` → 루트 close + wiki task done 처리.
   - **sub-major(micro/normal) 컨테이너**: PR 없이 로컬 FF로 부모 ref를 전진시킨다. `orchestrator_ops.ff_merge_command(child_branch="task/issue-{container}", parent_branch="task/issue-{parent}")` = `git fetch . task/issue-{container}:task/issue-{parent}` — self-fetch refspec라 checkout 없이 부모 ref만 FF한다(non-FF면 git이 거부하고, checked-out 브랜치는 건드리지 않아 메인 워크트리 HEAD가 trunk 불변, [[DEC-2026-07-02-212109]]). 그 뒤 `git push origin task/issue-{parent}` → 컨테이너 close. 부모 없는 root 컨테이너는 base가 trunk이므로, sub-major라도 trunk 직접 FF push는 하지 않고 major와 같이 PR 경로를 탄다.

   FF 거부(non-FF) 시 오케스트레이터가 부모를 컨테이너 브랜치가 아닌 **리프 워크트리로** reverse-merge하도록 위임하고, 리프측에서 해소·재검증 후 재시도한다(§Recovery Guards).
4. `done_parents[]` → 각 부모를 그 item의 `gear`대로 위(major=PR→`merge`, sub-major=`ff_merge_command`→push)와 같이 처리하고 close한 뒤 re-tick한다. 같은 tick의 ready는 버린다.
5. `review_waiting[]` → review-tool이 설정돼 있으면 reviewer-agent relay, 없으면 STOP(`human_gate_review`). 사람 리뷰/머지 후 재실행.
6. `ready[]` → 최대 `--max-workers`개 work-agent에 위임.

실제 분기 결정은 `plan_tick(ready_state, review_tool=..., review_command=..., max_workers=..., pipeline=...)` 결과를 따른다.
`--pipeline`이거나 `--max-workers > 1`이면 foreground 병렬 batch로 worker를 호출하지 않는다. worker/reviewer는 issue별 background lane으로 dispatch하고, lane 하나가 완료될 때마다 ledger를 갱신한 뒤 즉시 re-tick한다. foreground batch는 모든 worker가 반환될 때까지 orchestrator 턴이 막혀 first-finisher PR review가 long-pole worker 뒤로 밀리므로 병렬 모드에서 금지한다.

v1 worker handoff. `BASE_BRANCH`는 `issue_base_branch(parent_number, base_branch)`로
계산한 expected PR base(§브랜치트리 참고, leaf spawn 전 이미 존재가 보장돼 있어야 함)다.
worker에게 항상 명시로 넘긴다 — standalone用 fallback(`.task-github.yml base_branch`)에
기대지 않는다:

```text
ORCHESTRATED=true BASE_BRANCH="task/issue-{parent}" task-github:start {N}
ORCHESTRATED=true BASE_BRANCH="task/issue-{parent}" task-github:run {N}
ORCHESTRATED=true BASE_BRANCH="task/issue-{parent}" task-github:done {N}
```
parent가 없는 root issue는 `BASE_BRANCH="$(.task-github.yml base_branch)"`.
`run`/`done`은 `ORCHESTRATED=true`인데 `BASE_BRANCH`가 비어 있으면 PR/worktree 생성 전에
hard STOP한다 — `main`으로 fallback하지 않는다.

work-agent는 start에서 gear를 판단/보고한다. 오케스트레이터는 gear label을 쓰지 않고
보고값을 review/merge 정책 판단에만 읽는다.

**리프 머지 엣지(v1).** ceremony는 리프 자체가 아니라 리프가 부모에 합류하는 **머지 엣지**의 속성이고, gear로 게이팅된다:
- **micro/normal 리프**: worker가 `done` 안에서 리프→부모 **로컬 FF** 머지를 직접 수행한다(PR 없음). 머지 후 verify report + commit SHA range를 close 증거로 남기고, `ff_merged` ledger 이벤트를 `--sha-range`와 함께 기록한다:
  ```bash
  python3 plugins/task-github/skills/orchestrate/scripts/orchestrate_ledger.py "$LEDGER" \
    --event ff_merged --issue {N} --base task/issue-{parent} --sha-range {A..B} --json
  ```
- **major 리프**: 오늘과 같이 PR을 만든다.

오케스트레이터는 micro/normal용 리프 머지 lane을 **더 이상 돌리지 않는다** — worker가 남긴 `ff_merged`(또는 no-code no-op `closed`) 증거로 re-tick할 뿐이다. major만 `review_waiting[]`을 거쳐 PR review/merge lane을 탄다.

## Gear Flow Policy

ceremony는 노드가 부모에 합류하는 **머지 엣지**의 속성이고 gear로 게이팅된다([[DEC-2026-07-02-224910]]). plan/verify/pr-review 뿐 아니라 **머지 경로**도 gear로 갈린다 — micro/normal은 로컬 FF(PR 없음), major는 PR+review 후 머지:

| gear | plan | verify | pr-review | 머지 경로 |
|---|---:|---:|---:|---|
| `gear:micro` | x | o | x | 로컬 FF (PR 없음) |
| `gear:normal` | o | o | x | 로컬 FF (PR 없음) |
| `gear:major` | o | o | o | PR + review → merge |

**컨테이너 gear는 자식 위로 누적된 승격값**이다 — 컨테이너 자신의 label은 무시하고, 머지 엣지에서 `orchestrator_ops.container_gear_promotion(child_gears)`로 새로 계산한다. base = 자식 중 최고 gear(micro<normal<major), 여기에 누적 승격: micro 자식 3개 이상이면 최소 normal로, normal 자식 2개 이상이면 major로 올린다(gear를 모르는 자식은 micro로 센다). 그래서 작은 작업이 쌓이면(normal×2→major, micro×3→normal) trunk에 닿기 전에 **항상** 리뷰 게이트를 한 번은 지난다. 컨테이너 머지업은 이 computed gear를 적용한다 — major(또는 승격된) 컨테이너는 통합 PR+review, sub-major는 로컬 FF forward(§루프 3).

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
- `base_branch(issue N)` = 그 이슈 PR의 expected base:
  - GitHub 부모 이슈 있음 → `task/issue-{parent}` (parent_issue_branch)
  - 부모 없음(root issue) → `.task-github.yml base_branch` (=trunk_branch, 보통 `main`)

자식 spawn 전 `ensure_branch(issue N)`로 부모 브랜치를 재귀 보장하고 remote push한다.
브랜치가 없으면 parent base에서 생성한다. 순서는 `orchestrator_ops.ensure_branch_chain(N, parents=..., base_branch=...)`가
root→leaf로 반환한다(순수 함수, git 실행은 안 함) — 호출부가 이 순서대로 실제 보장한다:

```bash
python3 - <<'PY'
import subprocess, sys
sys.path.insert(0, "plugins/task-github/skills/orchestrate/scripts")
import orchestrator_ops as ops

parents = {83: 82, 82: 81, 81: None}  # ledger issues[].parent에서 구성
# chain[:-1] — leaf(자기 자신)는 제외하고 조상만 보장한다.
# leaf branch(task/issue-83)는 worker의 `git worktree add -b`가 만든다. 여기서 미리 만들면
# 그 add가 "a branch named 'task/issue-83' already exists"로 실패한다.
for step in ops.ensure_branch_chain(83, parents=parents, base_branch="main")[:-1]:
    branch, base = step["branch"], step["base"]
    exists = subprocess.run(["git", "ls-remote", "--exit-code", "--heads", "origin", branch],
                             capture_output=True).returncode == 0
    if not exists:
        subprocess.run(["git", "branch", branch, base], check=True)
        subprocess.run(["git", "push", "origin", branch], check=True)
PY
```
leaf worker는 조상 체인(`chain[:-1]`)의 마지막 항목 = `parent_issue_branch`가 remote에 존재를 확인한 뒤에만 spawn한다. leaf 자신의 branch(`task/issue-{N}`)는 만들지 않는다 — worker가 `git worktree add -b`로 생성한다.

## PR Review Policy

PR은 **major 엣지에서만** 생성된다. micro/normal은 로컬 FF라 PR 자체가 없어 리뷰할 대상이 없다. 컨테이너는 computed gear가 major일 때만 통합 PR을 만들어 리뷰한다. review-mode는 존재하는 PR(=major 엣지)에만 적용된다:

- `skip`: 모든 PR 자동 머지.
- `gear`: `flow_policy(...)["pr-review"]`를 따른다.
- `all`: 모든 PR STOP(`human_gate_review`).

review-tool이 있으면 `compose_tool_command(review-tool, orchestrate.review-command, target args)`로 호출한다.
`approved`는 merge로, `changes-requested`는 `worker_feedback_handoff()`로 work-agent 재spawn한다.
round cap을 넘으면 STOP(`human_gate_review`).

`pr-review:false`인 작업은 worker verification + CI success + mergeState CLEAN이면 review 없이 merge한다. `pr-review:true`인 작업도 review 요청 전에 완료조건/런타임 evidence를 먼저 sanity check하고, 불가능하면 scope split/follow-up/blocker를 만든 뒤 review한다.

## Recovery Guards

- major 리프의 새 PR 생성 전 `head=task/issue-{N}` + expected `base`의 open/merged PR을 재조회한다.
- expected base가 아닌 open PR이 head-only 조회에서 발견되면 STOP(`state_mismatch`).
- parent/container 완료는 `subIssuesSummary.completed`만 믿지 않는다.
  `orchestrator_ops.child_merge_evidence(children, expected_base=...)`가 각 child의 세 close 증거 중 하나를 요구한다: `closed_no_pr`(no-code no-op close), `merged_pr:{base}`(major, PR merged), `ff_merged:{base, sha_range}`(micro/normal 로컬 FF — `sha_range`가 merged PR을 대체하는 필수 증거).
- 충돌은 **항상 리프측에서** 해소한다. 로컬 FF가 non-FF로 거부되거나 `gh pr merge`가 충돌하면, 부모를 리프 워크트리로 reverse-merge해 리프측에서 `conflict_action`/conflict-agent로 해소·재검증한 뒤 재시도한다 — 오케스트레이터의 메인 워크트리에서 해소하지 않는다. 의미적 모호 충돌 또는 자동 경로 없음은 STOP(`merge_conflict`)이다. FF는 fetch refspec일 뿐 checkout이 아니므로 메인 워크트리 HEAD는 trunk를 벗어나지 않는다([[DEC-2026-07-02-212109]] 불변식 유지).

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
- 상태/gear label write는 worker/reviewer 소유다. 오케스트레이터는 issue close, major 컨테이너/epic 머지업 PR 생성, sub-major 컨테이너의 `ff_merge_command` FF push, merge를 수행한다(코드 커밋은 worker 소유). 머지 경로는 gear로 갈린다 — micro/normal은 로컬 FF(PR 없음), major는 PR([[DEC-2026-07-02-224910]]가 [[DEC-2026-07-02-212109]]의 all-PR 균일성을 gear-gated PR로 부분 완화). FF는 fetch refspec일 뿐 checkout이 아니라 메인 워크트리 HEAD는 여전히 trunk 불변([[DEC-2026-07-02-212109]] 유지).
- decision/rejected/trial_error wiki capture는 자동 기록하지 않는다. 루트 완료 때 후보만 제시하고 사용자 확인을 받는다.
- `--max-workers` 기본은 commander 지시 > `.task-github.yml orchestrate.max-workers` > 시스템 기본값(3) 순으로 정한다. ledger는 spawned/failed뿐 아니라 root snapshot, derived issue/PR state, events를 보관한다. 문제 발생 시 `--reconcile-github`로 GitHub SoT를 다시 덮어쓴다.
