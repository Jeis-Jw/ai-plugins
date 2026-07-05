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
python3 "${TASK_GITHUB_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/task_config.py" validate --json
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
    select_closeout_jobs,
    gear_of_labels,
    container_gear_promotion,
    ff_merge_command,
)
```

## 루프

초기/재개 boundary:
```bash
LEDGER=".task-github/orchestrate/{container_issue}.json"
python3 "${TASK_GITHUB_ROOT:-$CLAUDE_PLUGIN_ROOT}/skills/orchestrate/scripts/ready_leaves.py" {container_issue} \
  --reconcile-github "$LEDGER" --json
```

**run-notes seed (초기 1회).** ledger가 *상태*를 write-through한다면, run-notes는 *지식*을 나른다. 오케스트레이터가 알려진 gotcha(대상 SDK/env 함정, 이전 웨이브 교훈, 안정 API 형태)를 시드하면 worker가 상속하고, 각 worker의 발견이 다음 worker로 이어진다 — N번 재도출을 1번 + (N-1) 싼 읽기로 줄인다:
```bash
NOTES=".task-github/orchestrate/{container_issue}-notes.md"
[ -f "$NOTES" ] || cat > "$NOTES" <<'EOF'
# run-notes — 공유 지식 (advisory, SoT 아님 — 상태는 ledger 소관)
> 각 worker가 run 시작에 읽고 done에 발견을 append. 형제 워커 재학습 방지용.

## seed (오케스트레이터)
- {알려진 gotcha / 검증된 SDK·API 형태 / env quirk}
EOF
```
handoff에 이 파일의 **절대경로**를 `RUN_NOTES`로 넘긴다(§worker handoff).

평상시 tick:
```bash
python3 "${TASK_GITHUB_ROOT:-$CLAUDE_PLUGIN_ROOT}/skills/orchestrate/scripts/ready_leaves.py" \
  --from-ledger "$LEDGER" --json
```

분기 순서:

1. `ok:false` → `stop_reason` 브리핑 후 종료. 부분 ready-set 스폰 금지.
2. `stuck[]` → STOP. prior run 또는 failed worker는 자동 재시도하지 않는다.
3. `container_done` → **머지업 전 pending-work 스캔(B-lite)** → close 증거 guard → 컨테이너 브랜치를 base로 머지업. 스캔은 이 웨이브 리프 워크트리에 **미커밋** 작업이 남았는지 본다 — 남아 있으면 통합이 in-flight 수정을 앞질러 머지돼 main에서 그 변경이 누락되는 near-miss가 생기므로, 조용히 넘기지 않고 STOP한다. (커밋된 미통합 작업은 이 스캔이 아니라 `child_merge_evidence`가 이미 게이트한다 — 자식마다 ff_merged/merged_pr/closed 증거가 있어야 container_done이 뜬다. 그래서 여기선 unpushed를 보지 않는다: micro/normal 리프는 로컬 FF라 애초에 push하지 않아 no-upstream이 정상이고, upstream diff로는 false-negative가 난다.)
   ```bash
   MAIN=$(git rev-parse --show-toplevel)   # 오케스트레이터 메인 워크트리 — 루프 밖에서 1회 확정(cwd 불변)
   PENDING=$(git worktree list --porcelain | sed -n 's/^worktree //p' | while read -r wt; do
     [ "$wt" = "$MAIN" ] && continue
     [ -n "$(git -C "$wt" status --porcelain 2>/dev/null)" ] && echo "$wt"
   done)
   [ -n "$PENDING" ] && { echo "[중단] pending_work — 미커밋 리프 워크트리:"; echo "$PENDING"; exit 1; }
   ```
   통과하면 머지업한다. **머지 경로는 컨테이너의 computed gear와 review mode로 갈린다** — ledger item·`plan_tick` merge_container action이 `gear` 필드를 실어 온다(자식 위로 누적된 [[Gear Flow Policy]]의 cumulative gear). 컨테이너 브랜치는 순수 ref다 — worktree/checkout 없이 FF로만 전진한다:
   - **review-required 컨테이너**: 통합 PR을 만들어 리뷰 게이트를 태운다. epic/컨테이너 브랜치는 worker가 없어 PR이 자동 생성되지 않으므로 오케스트레이터가 직접 만든다.
     - 부모 이슈 있음: `gh pr create --base task/issue-{parent} --head task/issue-{container}` → review-tool relay/human gate → `merge {PR}` → 컨테이너 close.
     - 부모 이슈 없음: `gh pr create --base {base_branch} --head task/issue-{container}` → review-tool relay/human gate → `merge {PR}` → 루트 close + wiki task done 처리.
   - **review-free 컨테이너**: PR 없이 로컬 FF로 부모 ref를 전진시킨다. `orchestrator_ops.ff_merge_command(child_branch="task/issue-{container}", parent_branch="task/issue-{parent}")` = `git fetch . task/issue-{container}:task/issue-{parent}` — self-fetch refspec라 checkout 없이 부모 ref만 FF한다(non-FF면 git이 거부하고, checked-out 브랜치는 건드리지 않아 메인 워크트리 HEAD가 trunk 불변, [[DEC-2026-07-02-212109]]). 그 뒤 `git push origin task/issue-{parent}` → 컨테이너 close. 부모 없는 root 컨테이너는 base가 trunk이므로, review-free라도 trunk 직접 FF push는 하지 않고 PR 경로를 탄다.

   FF 거부(non-FF) 시 오케스트레이터가 부모를 컨테이너 브랜치가 아닌 **리프 워크트리로** reverse-merge하도록 위임하고, 리프측에서 해소·재검증 후 재시도한다(§Recovery Guards).
4. `done_parents[]` → 각 부모를 그 item의 computed gear와 review mode대로 위(review-required=PR→`merge`, review-free=`ff_merge_command`→push)와 같이 처리하고 close한 뒤 re-tick한다. 같은 tick의 ready는 버린다.
5. `closeout_ready[]` → `BASE_BRANCH`별 FIFO closeout lane을 dispatch한다. 같은 base에 `closeout_started`가 있으면 새 closeout agent를 만들지 않고 pending으로 남긴다. 다른 base는 병렬 가능하다.
6. `review_waiting[]` → review-tool이 설정돼 있으면 reviewer-agent relay, 없으면 STOP(`human_gate_review`). 사람 리뷰/머지 후 재실행.
7. `ready[]` → 최대 `--max-workers`개 work-agent에 위임.

실제 분기 결정은 `plan_tick(ready_state, review_tool=..., review_command=..., max_workers=..., pipeline=...)` 결과를 따른다.
`--pipeline`이거나 `--max-workers > 1`이면 foreground 병렬 batch로 worker를 호출하지 않는다. worker/reviewer는 issue별 background lane으로 dispatch하고, lane 하나가 완료될 때마다 ledger를 갱신한 뒤 즉시 re-tick한다. foreground batch는 모든 worker가 반환될 때까지 orchestrator 턴이 막혀 first-finisher PR review가 long-pole worker 뒤로 밀리므로 병렬 모드에서 금지한다.

### worker handoff (v2 — 구조화 job spec)

worker에게 넘기는 것은 **고정 env 블록**이다 — 산문이 아니다. 이 env + 이슈 본문(완료조건·영향경로) + 위키 컨텍스트(주입된 DEC/SSOT) + run-notes가 **스펙의 전부**다. 오케스트레이터는 실행 세부를 산문으로 다시 서술하지 않는다 — 표준 플로우(start→run→done)는 **worker 스킬이 소유**한다. "신뢰가 안 가서 다 다시 쓴다"는 계약이 비어 있다는 신호였고, 이 블록이 그 계약이다.

주입 계약(각 키가 왜 필요한가):
- `TASK_GITHUB_ROOT` — 오케스트레이터가 자기 플러그인 루트를 **절대경로로** 해소해 넘긴다. cache 설치·Codex·리프 워크트리(다른 cwd)에서도 worker가 스크립트/게이트를 찾게 하는 이식성 키. worker 쪽은 `${TASK_GITHUB_ROOT:-$CLAUDE_PLUGIN_ROOT}`로 읽어 주입값이 항상 우선한다.
- `BASE_BRANCH` — `issue_base_branch(parent_number, base_branch)`로 계산한 expected merge base(leaf spawn 전 존재 보장, §브랜치트리). parent 없는 root는 `.task-github.yml base_branch`.
- `LEDGER` — write-through ledger **절대경로**. worker의 done이 `gate_evidence`/`ready_for_closeout`을 여기 기록하고, closeout lane이 `ff_merged`/`pr_merged`/`closeout_done`을 기록한다. 비면 done이 STOP(조용한 스킵 금지 — 이전 회귀의 근본원인).
- `RUN_NOTES` — 공유 지식 스크래치 **절대경로**(위 seed). worker가 run 시작에 읽고 done에 append해 형제 재학습을 막는다.
- `ORCHESTRATE_REVIEW_MODE` — `gear|all|skip`. `done`이 major edge에서 PR을 만들지, verify 후 FF closeout으로 넘길지 결정한다.

```bash
# 오케스트레이터가 자기 루트를 절대경로로 1회 해소
TG_ABS="${TASK_GITHUB_ROOT:-$CLAUDE_PLUGIN_ROOT}"
ORCH_ENV="ORCHESTRATED=true TASK_GITHUB_ROOT=$TG_ABS \
ORCHESTRATE_REVIEW_MODE={review_mode} \
BASE_BRANCH=task/issue-{parent} \
LEDGER=$(pwd)/.task-github/orchestrate/{container_issue}.json \
RUN_NOTES=$(pwd)/.task-github/orchestrate/{container_issue}-notes.md"
# leaf worker 3연속(같은 env)
$ORCH_ENV task-github:start {N}
$ORCH_ENV task-github:run {N}
$ORCH_ENV task-github:done {N}
```
`LEDGER`/`RUN_NOTES`는 반드시 **절대경로**(`$(pwd)` 기준) — worker는 자기 리프 워크트리(다른 cwd)에서 돌 수 있어 상대경로는 깨진다. parent 없는 root issue는 `BASE_BRANCH="$(.task-github.yml base_branch)"`. `run`/`done`은 `ORCHESTRATED=true`인데 `BASE_BRANCH`나 `LEDGER`가 비면 hard STOP — `main`/silent-skip으로 fallback하지 않는다.

**재도출·재서술 금지 지시(핸드오프 프롬프트에 명시).** worker를 spawn하는 프롬프트에 다음을 박는다: *"위 env + 이슈 본문 + 위키 컨텍스트 + run-notes가 스펙 전부다. run-notes/주입 DEC/SSOT에 이미 있는 사실(검증된 API·env·버그)은 재도출·재검증하지 말고 상속하라. 표준 플로우(start→run→done)는 네 스킬이 안다 — 여기서 다시 지시하지 않는다."* 오케스트레이터가 이슈마다 env·플로우·빌드스펙을 장문으로 재작성하면 토큰이 배가되고 스텝 누락 위험이 생긴다.

**도메인 스펙(공식·값·알고리즘)을 핸드오프 산문에 재서술 금지 — 이슈 본문이 정본이다.** 오케스트레이터 산문이 이슈 본문과 어긋나면 드리프트가 생긴다(Wave 2 #14: 산문 "Mifflin-St Jeor" vs 이슈 본문 "Harris-Benedict" — worker가 올바르게 본문을 따랐으나 산문은 낭비+오도). env 블록 + "이슈 본문이 정본" 지시만 남기고 이슈가 소유한 것을 되풀이하지 않는다.

**worker 최종 리턴은 평문(plain text).** spawn 프롬프트에 명시한다: *"최종 보고는 평문으로 반환하라 — 구조화 tool-call로 턴을 끝내지 말 것."* 대형·특수문자(한글 파일명 등) 출력이 구조화 리턴 파서를 깨 실제 작업이 끝났는데도 리턴만 트렁케이트되는 사례가 있었다(Wave 2 #13: 63 tool_use로 작업 완료, 구조화 리턴만 2회 파싱 실패). `done`은 부작용(FF·close·ledger 기록)을 **리턴 성형 전에** 완료·flush해, 리턴이 깨져도 상태가 SoT+ledger에 남게 한다.

work-agent는 start에서 gear를 판단/보고한다. 오케스트레이터는 gear label을 쓰지 않고
보고값을 review/merge 정책 판단에만 읽는다.

**리프 머지 엣지(v2).** ceremony는 리프 자체가 아니라 리프가 부모에 합류하는 **머지 엣지**의 속성이고, review 필요 여부로 merge transport가 갈린다:
- **review 불필요 edge(micro/normal, 또는 `--review=skip`의 major)**: worker는 구현/검증/커밋 뒤 부모 ref를 직접 전진시키지 않고 `ready_for_closeout` ledger 이벤트를 기록한다. closeout one-shot agent가 `BASE_BRANCH` lock을 잡고 `git fetch . child:parent` → push → issue close → `closeout_done`/`ff_merged` evidence를 기록한다.
  ```bash
  python3 "${TASK_GITHUB_ROOT:-$CLAUDE_PLUGIN_ROOT}/skills/orchestrate/scripts/orchestrate_ledger.py" "$LEDGER" \
    --event ready_for_closeout --issue {N} --base task/issue-{parent} \
    --head task/issue-{N} --head-sha {HEAD_SHA} --json
  ```
- **review 필요 edge(기본 major 또는 `--review=all`)**: worker가 PR을 만들고 `review_waiting`으로 넘긴다. PR 생성/리뷰 대기 동안 parent lock을 잡지 않는다. 승인 후 reviewer/orchestrator가 `ready_for_pr_closeout`을 기록하고, PR merge 순간만 `BASE_BRANCH` closeout lane이 lock을 잡는다.

ledger가 queue다. closeout subagent는 상주하지 않는 one-shot job이며, 완료 callback/re-tick 때 같은 base의 다음 pending item을 새 closeout subagent로 처리한다.

## Gear Flow Policy

ceremony는 노드가 부모에 합류하는 **머지 엣지**의 속성이고 review 필요 여부로 merge transport가 갈린다([[DEC-2026-07-02-224910]]). 기본 gear 정책은 micro/normal은 로컬 FF(PR 없음), major는 PR+review지만, `--review=skip`이면 major도 verify 후 FF closeout으로 간다:

| gear | plan | verify | pr-review | 머지 경로 |
|---|---:|---:|---:|---|
| `gear:micro` | x | o | x | 로컬 FF (PR 없음) |
| `gear:normal` | o | o | x | 로컬 FF (PR 없음) |
| `gear:major` | o | o | o | PR + review → merge (`--review=skip`이면 verify 후 FF closeout) |

**컨테이너 gear는 자식 위로 누적된 승격값**이다 — 컨테이너 자신의 label은 무시하고, 머지 엣지에서 `orchestrator_ops.container_gear_promotion(child_gears)`로 새로 계산한다. base = 자식 중 최고 gear(micro<normal<major), 여기에 누적 승격: micro 자식 3개 이상이면 최소 normal로, normal 자식 2개 이상이면 major로 올린다(gear를 모르는 자식은 micro로 센다). 그래서 기본 `gear` review mode에서는 작은 작업이 쌓이면(normal×2→major, micro×3→normal) trunk에 닿기 전에 리뷰 게이트를 한 번은 지난다. `--review=skip`에서는 이 게이트를 생략하되 computed gear와 skip 근거를 evidence에 남긴다.

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
   python3 "${TASK_GITHUB_ROOT:-$CLAUDE_PLUGIN_ROOT}/skills/orchestrate/scripts/orchestrate_ledger.py" "$LEDGER" --json
   python3 "${TASK_GITHUB_ROOT:-$CLAUDE_PLUGIN_ROOT}/skills/orchestrate/scripts/ready_leaves.py" {container_issue} --reconcile-github "$LEDGER" --json
   ```
2. `plan_tick(..., pipeline=True)`가 `dispatch_background_workers`를 반환하면 issue별 worker를 background로 띄우고 즉시 ledger에 spawned를 기록한다.
   ```bash
   python3 "${TASK_GITHUB_ROOT:-$CLAUDE_PLUGIN_ROOT}/skills/orchestrate/scripts/orchestrate_ledger.py" "$LEDGER" --spawned "4 6 7 8" --json
   ```
3. worker 완료 callback/notification을 받으면 해당 issue를 completed로 제거하고 바로 re-tick한다. 이 re-tick에서 완료된 PR은 `review_waiting[]`에 나타나며, 남은 worker가 계속 도는 중이어도 review lane을 background로 dispatch한다.
   ```bash
   python3 "${TASK_GITHUB_ROOT:-$CLAUDE_PLUGIN_ROOT}/skills/orchestrate/scripts/orchestrate_ledger.py" "$LEDGER" --completed "7" --json
   python3 "${TASK_GITHUB_ROOT:-$CLAUDE_PLUGIN_ROOT}/skills/orchestrate/scripts/ready_leaves.py" --from-ledger "$LEDGER" --json
   ```
4. worker failure/timeout callback은 failed로 기록하고 re-tick한다. `ready_leaves.py`는 `in-progress` + failed issue를 `stuck(reason=spawned_failed)`로 올려 자동 재시도를 막는다.

`--spawned`/`--failed` 직접 전달도 유지하되, 포맷은 comma/space mixed-separated issue numbers다(`"4,6 7"` 가능). pipeline 모드의 실행 중 상태는 ledger 파일이다. 성공한 write는 `orchestrate_ledger.py --event ...` 또는 closeout의 `--orchestrate-ledger`로 즉시 반영하고, read-after-write를 위해 GitHub를 다시 읽지 않는다. 사람이 보는 상태 출력은 기본적으로 `orchestrate_ledger.py "$LEDGER" --summary --json`을 사용하고, full JSON은 디버깅 때만 본다.

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
python3 - "${TASK_GITHUB_ROOT:-$CLAUDE_PLUGIN_ROOT}" <<'PY'
import subprocess, sys
sys.path.insert(0, sys.argv[1] + "/skills/orchestrate/scripts")
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

PR은 **review 필요한 edge에서만** 생성된다. micro/normal은 로컬 FF라 PR 자체가 없어 리뷰할 대상이 없고, major도 `--review=skip`이면 PR 없이 `ready_for_closeout`으로 간다. 컨테이너는 computed gear와 review mode가 모두 PR을 요구할 때만 통합 PR을 만들어 리뷰한다:

- `skip`: PR/review를 만들지 않고 verify 후 FF closeout으로 보낸다(gear/skip evidence 기록).
- `gear`: `flow_policy(...)["pr-review"]`를 따른다.
- `all`: 모든 PR STOP(`human_gate_review`).

review-tool이 있으면 `compose_tool_command(review-tool, orchestrate.review-command, target args)`로 호출한다.
`approved`는 `ready_for_pr_closeout` ledger event로, `changes-requested`는 `worker_feedback_handoff()`로 work-agent 재spawn한다.
round cap을 넘으면 STOP(`human_gate_review`).

**CRITICAL — 리뷰어/검증자 relay는 punt 금지.** review-tool relay agent(및 통합리뷰·verify 서브에이전트)는 **인라인으로 리뷰하고 자기 최종 메시지로 판정(approved/changes-requested)을 반환**한다. 백그라운드 서브에이전트를 spawn하고 자기 턴을 끝내지 말 것 — 자식 완료 알림은 **최상위 오케스트레이터만** 받으므로, spawn-후-punt한 relay는 판정을 영영 relay하지 못하고 자식 판정이 트랜스크립트에 갇힌다(Wave 2 #10 관찰: 백그라운드 relay가 중첩 백그라운드 리뷰어를 낳고 "완료"로 반환, approved 판정이 유실됨). 백그라운드 spawn-후-재호출(re-tick) 패턴은 **최상위 오케스트레이터 전용**이고, dispatch된 worker/reviewer lane은 **리프**(일하고 데이터 반환)여야 한다. 리뷰어가 꼭 팬아웃해야 하면 자기 턴 안에서 자식을 await한 뒤 판정을 반환한다 — 턴을 끝내며 자식 완료를 기대하지 말 것. (여기서 "인라인"=relay lane 자신의 턴 안이라는 뜻이다. 오케스트레이터가 그 lane을 background로 띄우는지 foreground로 부르는지는 §루프의 background-lane dispatch 규칙 + `plan_tick`이 이미 정한다 — 이 규칙은 그 결정을 되돌리지 않고, dispatch된 lane이 판정을 **자기 최종 메시지로** 반환하게만 한다.)

`pr-review:false`인 작업은 worker verification + CI success + mergeState CLEAN이면 review 없이 merge한다. `pr-review:true`인 작업도 review 요청 전에 완료조건/런타임 evidence를 먼저 sanity check하고, 불가능하면 scope split/follow-up/blocker를 만든 뒤 review한다.

## Recovery Guards

- review-required 리프의 새 PR 생성 전 `head=task/issue-{N}` + expected `base`의 open/merged PR을 재조회한다.
- expected base가 아닌 open PR이 head-only 조회에서 발견되면 STOP(`state_mismatch`).
- parent/container 완료는 `subIssuesSummary.completed`만 믿지 않는다.
  `orchestrator_ops.child_merge_evidence(children, expected_base=...)`가 각 child의 세 close 증거 중 하나를 요구한다: `closed_no_pr`(no-code no-op close), `merged_pr:{base}`(review-required PR merged), `ff_merged:{base, sha_range}`(review-free 로컬 FF — `sha_range`가 merged PR을 대체하는 필수 증거).
- 충돌은 **항상 리프측에서** 해소한다. 로컬 FF가 non-FF로 거부되거나 `gh pr merge`가 충돌하면, 부모를 리프 워크트리로 reverse-merge해 리프측에서 `conflict_action`/conflict-agent로 해소·재검증한 뒤 재시도한다 — 오케스트레이터의 메인 워크트리에서 해소하지 않는다. 의미적 모호 충돌 또는 자동 경로 없음은 STOP(`merge_conflict`)이다. FF는 fetch refspec일 뿐 checkout이 아니므로 메인 워크트리 HEAD는 trunk를 벗어나지 않는다([[DEC-2026-07-02-212109]] 불변식 유지).
- **파싱 실패 리턴 ≠ worker 실패.** worker의 최종 리턴이 파싱 실패해도 실패로 단정하지 말고 SoT를 조사한다(이슈 상태·브랜치·리프 워크트리·ledger 이벤트). 이미 완료된 단계는 재실행하지 말고 미완 단계만 마무리한다 — worker가 push는 마쳤는데 ledger 기록 직전 리턴만 깨질 수 있다(Wave 2 #13: SoT 조사로 일 안 날리고 수동 closeout으로 마무리). ledger가 non-dict로 깨져 있으면(load STOP) `--reconcile-github`로 GitHub SoT를 다시 덮고, **reconcile 먼저 → evidence 재기록 나중 → container_done 체크** 순서를 고정한다(reconcile가 뒤에 오면 evidence를 또 날린다).

helper 기준:

```bash
python3 - "${TASK_GITHUB_ROOT:-$CLAUDE_PLUGIN_ROOT}" <<'PY'
import sys
sys.path.insert(0, sys.argv[1] + "/skills/orchestrate/scripts")
import orchestrator_ops as ops
print(ops.issue_base_branch(parent_number=12, base_branch="main"))
PY
```

conflict-agent 산출물은 [agents/conflict-resolver.md](../../agents/conflict-resolver.md)를 따른다.

## 불변식

- 오케스트레이터는 직접 코딩하지 않는다.
- 상태/gear label write는 worker/reviewer 소유다. 오케스트레이터는 issue close, review-required 컨테이너/epic 머지업 PR 생성, review-free 컨테이너의 `ff_merge_command` FF push, merge/closeout dispatch를 수행한다(코드 커밋은 worker 소유). 머지 경로는 review 필요 여부로 갈린다 — review-free는 로컬 FF(PR 없음), review-required는 PR. FF는 fetch refspec일 뿐 checkout이 아니라 메인 워크트리 HEAD는 여전히 trunk 불변([[DEC-2026-07-02-212109]] 유지).
- decision/rejected/trial_error wiki capture는 자동 기록하지 않는다. 루트 완료 때 후보만 제시하고 사용자 확인을 받는다.
- **웨이브 동결**: 컨테이너 머지업 개시 전 pending-work 스캔(미커밋 리프 워크트리 → STOP `pending_work`; 커밋된 미통합은 `child_merge_evidence`가 별도 게이트), 개시 후 발견 수정은 웨이브에 끼우지 않고 새 micro 이슈로 뒤따른다([[workflow.md §6]]). base가 뒤처진 통합 PR은 dead-STOP이 아니라 `gh pr update-branch` 복구 후 재검증(merge Step 3).
- **핸드오프는 구조화 job spec(env 블록)** — 오케스트레이터가 실행 세부를 산문으로 재서술하지 않는다. `TASK_GITHUB_ROOT`(절대경로)·`BASE_BRANCH`·`LEDGER`(절대)·`RUN_NOTES`(절대)를 주입하고, worker 프롬프트에 "제공된 사실 재도출 금지, 플로우는 워커 스킬 소유"를 명시한다.
- **mechanism friction 집계(F)**: 루트 완료 보고에 이번 런의 워크플로 마찰(미해소 경로·스킵 스텝·수동 ledger 보정·재도출 지식)을 worker들의 friction 보고에서 모아 한 절로 남긴다 — consumer wiki가 아니라 런 보고에(운영/메커니즘 회고 채널).
- `--max-workers` 기본은 commander 지시 > `.task-github.yml orchestrate.max-workers` > 시스템 기본값(3) 순으로 정한다. ledger는 spawned/failed뿐 아니라 root snapshot, derived issue/PR state, events를 보관한다. 문제 발생 시 `--reconcile-github`로 GitHub SoT를 다시 덮어쓴다.
