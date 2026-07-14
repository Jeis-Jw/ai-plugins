---
name: done
description: Issue 또는 task-worker DefinitionArtifact local run을 종료한다. Issue 번호는 기존 PR/FF/close 경로, --artifact/--run-state는 Issue write 없이 delivery와 closeout을 수행하는 facade다. "task-github:done", "PR 만들어줘", "작업 마무리해줘", "이슈 닫아줘" 등의 요청에 실행하라.
---

# done — PR 생성 또는 close

작업 종료 + GitHub/로컬 상태 정리. 코드 변경 유무로 2경로.

## 입력

```
$ARGUMENTS: {N} | --artifact {PATH} --run-state {RUN_JSON}
```

## 절차

### local DefinitionArtifact facade

`--artifact/--run-state`가 있으면 `recover.next_event`를 확인한다. `done`이면 evidence를 기록하고, PR merge 뒤 재진입한 `closeout`이면 done 전이를 반복하지 않는다. run-state가 node와 stable branch/worktree를 이미 pin한다:

```bash
python3 "${TASK_GITHUB_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/task_worker_bridge.py" recover \
  --artifact {PATH} --run-state {RUN_JSON}
python3 "${TASK_GITHUB_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/task_worker_bridge.py" local-event \
  --artifact {PATH} --run-state {RUN_JSON} --event done --evidence '{테스트/드리프트 결과 JSON object}'
```

run-state의 delivery를 그대로 수행한다:

- `local-ff`: stable branch를 configured base에 FF delivery한 뒤 `local-event --event closeout`.
- `external`: task-github facade는 stable branch를 push하고 **Issue closing keyword 없는** PR을 만든다. merge 전에는 state를 `done`으로 두고, merge 확인 뒤 `closeout`한다.

delivery 완료 뒤 closeout과 receipt를 기록한다:

```bash
python3 "${TASK_GITHUB_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/task_worker_bridge.py" local-event \
  --artifact {PATH} --run-state {RUN_JSON} --event closeout --evidence '{delivery 결과 JSON object}'
python3 "${TASK_GITHUB_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/task_worker_bridge.py" receipt \
  --run-state {RUN_JSON} --workflow task-github
```

`record:none`에서는 `gh issue create/edit/comment/close`, Issue dependency/label/assignee를 호출하지 않는다. PR delivery 자체는 허용된다. 위키 drift와 Knowledge Capture Audit는 동일하게 적용한다. 아래 `{N}` 절차는 변경 없는 legacy/projected Issue 경로다.

### dependency 차단 재확인
완료 처리 전에 열린 blocker를 다시 확인한다. blocker가 열려 있으면 이 이슈를 PR/close로 넘기지 않는다:
```bash
read OWNER REPO < <(gh repo view --json owner,name --jq '"\(.owner.login) \(.name)"')
API_VERSION="2026-03-10"
OPEN_BLOCKERS=$(gh api -H "X-GitHub-Api-Version: $API_VERSION" \
  "repos/$OWNER/$REPO/issues/{N}/dependencies/blocked_by" \
  --jq '[.[] | select(.state == "open") | "#\(.number) \(.title)"] | join("\n")')

if [ -n "$OPEN_BLOCKERS" ]; then
  gh issue comment {N} --body "[중단] 열린 blocker가 있어 done을 중단합니다.

$OPEN_BLOCKERS"
  exit 1
fi
```
dependency API 조회가 실패하면 자동 종료하지 않고 사령관에게 수동 확인을 요청한다([dependencies.md](../../rules/dependencies.md)).

### BASE_BRANCH 확보 (모든 기어 공통 — 경로 판단·드리프트·머지 전에 먼저)
orchestrate에서는 부모 브랜치가 base다. orchestrated에서 BASE_BRANCH가 비면 절대 진행하지 않고 STOP(main fallback 금지). 이후 모든 diff/머지는 이 값을 base로 쓴다:
```bash
# orchestrated 필수 계약: BASE_BRANCH(머지 base) + LEDGER(closeout/gate_evidence 기록처).
# 둘 중 하나라도 비면 STOP — ledger/게이트 스텝의 조용한 스킵을 코드로 막는다(cache 설치 회귀 방지).
if [ "$ORCHESTRATED" = "true" ]; then
  [ -z "$BASE_BRANCH" ] && { gh issue comment {N} --body "[중단] orchestrated: BASE_BRANCH(expected merge base) 없음. 머지/PR 전 STOP, main fallback 금지."; exit 1; }
  [ -z "$LEDGER" ] && { gh issue comment {N} --body "[중단] orchestrated: LEDGER(ledger 절대경로) 없음. gate_evidence/closeout 기록 불가 — 조용한 스킵 금지."; exit 1; }
fi
# 스크립트 루트 해소(cache/vendored/Codex 공통): TASK_GITHUB_ROOT(핸드오프 주입/명시) > CLAUDE_PLUGIN_ROOT. 미해소면 STOP.
[ -f "${TASK_GITHUB_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/task_config.py" ] || { echo "[중단] task-github 플러그인 루트 미해소 — TASK_GITHUB_ROOT 또는 CLAUDE_PLUGIN_ROOT 필요."; exit 1; }
BASE_BRANCH=${BASE_BRANCH:-$(python3 "${TASK_GITHUB_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/task_config.py" get base_branch 2>/dev/null || echo main)}
```

### 경로 판단
변경 유무는 리프의 base(부모 브랜치 `$BASE_BRANCH`)에 대해 판단한다 — orchestrate에서 리프 base는 `main`이 아니라 `task/issue-{parent}`이므로 `main` 고정 diff는 부모의 기머지 커밋을 오탐한다:
```bash
git worktree list
git diff "$BASE_BRANCH"...HEAD --name-only 2>/dev/null || git status --short
```

### 경로 A — 변경 있음 (review 필요 여부로 분기)
머지 세리머니는 **리프가 아니라 머지 엣지의 속성**이고 review 필요 여부로 게이팅한다(DEC-2026-07-02-224910). 이슈 기어와 현재 review mode를 읽어 분기한다:
- **review 불필요(micro/normal, 또는 `--review=skip`/policy override의 major)** — PR 없음. verify/commit 후 부모 ref 직접 전진 대신 `ready_for_closeout` ledger event를 남기고 종료한다. 실제 FF/push/issue close는 orchestrator의 `BASE_BRANCH`별 closeout lane이 처리한다.
- **review 필요(기본 major)** — PR 경로. PR은 review/audit log 표면이고, PR 생성/리뷰 대기 동안 parent lock을 잡지 않는다. 승인 후 merge 순간만 closeout lane이 `BASE_BRANCH` lock을 잡는다.

**trunk 예외:** BASE_BRANCH가 trunk(=`task/issue-*`가 아님, root 직속 리프)면 trunk가 사령관의 메인 워크트리에 체크아웃돼 있어 `git fetch . leaf:trunk`가 거부된다(git이 checked-out 브랜치 갱신을 막음, 이게 곧 [[DEC-2026-07-02-212109]] 불변식의 근거). 이 경우 micro/normal이라도 A-1 대신 **A-2(PR 경로)**를 탄다 — trunk로의 합류는 항상 PR이다.

```bash
GEAR=$(gh issue view {N} --json labels --jq '[.labels[].name]' \
  | TG="${TASK_GITHUB_ROOT:-$CLAUDE_PLUGIN_ROOT}" python3 -c 'import json,os,sys; sys.path.insert(0, os.environ["TG"]+"/skills/orchestrate/scripts"); import orchestrator_ops as o; print(o.gear_of_labels(json.load(sys.stdin)) or "normal")')
# 머지 경로: review 필요한 major이거나 부모가 trunk(체크아웃돼 로컬 FF 불가)면 PR(A-2), 아니면 FF closeout(A-1)
case "$BASE_BRANCH" in task/issue-*) PARENT_IS_TASK=1 ;; *) PARENT_IS_TASK=0 ;; esac
if [ "$GEAR" = "major" ] && [ "${ORCHESTRATE_REVIEW_MODE:-gear}" != "skip" ]; then ROUTE=pr; else ROUTE=ff; fi
[ "$PARENT_IS_TASK" = "0" ] && ROUTE=pr
```

1. 미커밋 변경 커밋: `{type}: {요약} (#{N}) — {Why}`
2. **드리프트 hard gate** ([quality-gates.md](../../rules/quality-gates.md) G1) — 종료 전에 이번 브랜치가 낡게 만든 위키 문서 탐지:
```bash
if [ -d "./wiki" ]; then
  FILES=$(git diff --name-only "$BASE_BRANCH"...HEAD | paste -sd,)
  DRIFT=$(wiki refresh --check changed-path-stale --changed-path "$FILES" --json)
  printf '%s' "$DRIFT" | python3 -c 'import json,sys; sys.exit(1 if json.load(sys.stdin).get("issues") else 0)' || {
    printf '%s\n' "$DRIFT"
    exit 1
  }
  HYG=$(wiki refresh --level hygiene --json)  # 경고 surface (비차단)
fi
```
`changed-path-stale`(drift) 이슈가 있으면 종료하지 않고 done을 중단한다. 리포트된 ssot/runbook/trial_error/observation은 `verified_at` 갱신 또는 supersede 대상이며, 자동 변경하지 않고 보완 후 다시 `done`을 실행한다. `HYG`의 hygiene 이슈는 done을 막지 않고 리포트로만 남긴다. (BASE_BRANCH는 경로 판단 전에 이미 확보했다.)

ORCHESTRATED review-free FF 경로에서는 drift gate 통과 결과를 부모가 재사용할 수 있도록 `gate_evidence`를 먼저 ledger에 기록한다. evidence에는 canonical changed path list, `changed_paths_hash`, `checked_paths_hash`, `drift_surface_hash`, `tool_versions`, `gate_version`, 빈 `changed_path_stale_issues`가 모두 있어야 한다. required field가 빠지면 `ready_for_closeout`을 기록하지 않는다. 실제 FF/issue close 뒤 `ff_merged`/`closeout_done` event는 closeout lane이 기록한다.

외부 `workflow-review-lease/v1`이 있는 edge에서는 `review-mode=skip`으로 FF closeout을 만들지 않는다. `owner=studio`여도 PR 생성·base/head transport·CI/preflight·`review_waiting`은 유지하고 reviewer dispatch만 억제한다. 동일 lease의 approved verdict와 필수 evidence가 ledger에 기록되기 전에는 `ready_for_pr_closeout`이나 merge를 수행하지 않는다.

#### A-1) review 불필요 — FF closeout (PR 없음) — `ROUTE=ff`
ORCHESTRATED worker는 리프 브랜치를 부모 ref로 직접 전진시키지 않는다. gate evidence를 남긴 뒤, closeout lane의 FIFO queue에 올린다. closeout one-shot agent가 `BASE_BRANCH` lock을 잡고 checkout 없는 FF(`ff_merge_command`; self-fetch refspec — main worktree HEAD는 트렁크를 떠나지 않는다, DEC-2026-07-02-212109 불변식 보존)를 수행한다:
```bash
FILES=$(git diff --name-only "$BASE_BRANCH"...HEAD | paste -sd,)
HEAD_SHA=$(git rev-parse HEAD)
FF_GATE_ARGS=(--ff-gate --issue {N} --head-sha "$HEAD_SHA" --changed-path "$FILES" --json)
[ "$ORCHESTRATED" = "true" ] && FF_GATE_ARGS+=(--orchestrate-ledger "$LEDGER")
python3 "${TASK_GITHUB_ROOT:-$CLAUDE_PLUGIN_ROOT}/skills/merge/scripts/merge_preflight.py" "${FF_GATE_ARGS[@]}" || exit 1

if [ "$ORCHESTRATED" = "true" ]; then
  python3 "${TASK_GITHUB_ROOT:-$CLAUDE_PLUGIN_ROOT}/skills/orchestrate/scripts/orchestrate_ledger.py" "$LEDGER" \
    --event ready_for_closeout --issue {N} --base "$BASE_BRANCH" --head task/issue-{N} --head-sha "$HEAD_SHA" \
    ${GEAR:+--gear "$GEAR"} $([ "$GEAR" = "major" ] && printf '%s' --review-skipped) --json
  # 여기서 직접 merge/close하지 않는다. run-notes/friction/final report만 남기고 반환한다.
else
  git fetch . task/issue-{N}:"$BASE_BRANCH" || {
    git merge "$BASE_BRANCH"
    # 충돌 해결 후 verify 재실행 → 통과하면 FF 재시도
    git fetch . task/issue-{N}:"$BASE_BRANCH"
  }
  git push origin "$BASE_BRANCH"
fi
```
**부모 브랜치를 checkout하지 말 것.** 실제 로컬 FF는 closeout lane에서 반드시 `git fetch . task/issue-{N}:{BASE_BRANCH}`(비체크아웃 ref 갱신)로만 한다. `git checkout {BASE_BRANCH}; git merge --ff-only`로 우회하면 부모가 이 워크트리(또는 메인 워크트리)에 체크아웃돼, 이후 다른 리프의 self-fetch refspec FF가 전부 거부되고 메인 워크트리 HEAD가 trunk를 이탈한다([[DEC-2026-07-02-212109]] 불변식 위반, Wave 2 #15 관찰). ref 갱신은 원자적이라 병렬 리프의 non-FF 경합도 자연 직렬화된다 — checkout 기반이 유일한 오염원이다.

충돌은 **항상 리프-side**(리프 worktree의 역머지)에서 해결한다 — 오퍼레이터 main worktree에서 해결하지 않는다.

Standalone(non-ORCHESTRATED) FF 경로에서는 close 증거 = verify 리포트 + 커밋 SHA range(`git rev-parse`로 범위 산출), close와 `ff_merged` 기록까지 여기서 수행한다. ORCHESTRATED에서는 아래 스텝을 실행하지 않는다. closeout lane이 `BASE_BRANCH` lock을 잡은 뒤 FF/close/ledger 기록을 수행한다:
```bash
BEFORE=$(git rev-parse "origin/$BASE_BRANCH@{1}" 2>/dev/null || git merge-base task/issue-{N} "$BASE_BRANCH")
AFTER=$(git rev-parse task/issue-{N})
SHA_RANGE="$BEFORE..$AFTER"
gh issue comment {N} --body "## 결과 (local FF → $BASE_BRANCH)

verify 리포트: ...
SHA range: $SHA_RANGE"
gh issue edit {N} --remove-label "in-progress" --remove-label "in-review" --remove-label "changes-requested"
gh issue close {N}
```
**gear:* 라벨 유지.** Standalone에서 ledger가 있을 때만 `ff_merged` 이벤트 기록:
```bash
[ "$ORCHESTRATED" != "true" ] && [ -n "$LEDGER" ] && python3 "${TASK_GITHUB_ROOT:-$CLAUDE_PLUGIN_ROOT}/skills/orchestrate/scripts/orchestrate_ledger.py" "$LEDGER" \
  --event ff_merged --issue {N} --base "$BASE_BRANCH" --sha-range "$SHA_RANGE"
```

#### A-2) review 필요 (또는 부모가 trunk) — PR 경로 — `ROUTE=pr`
1. 라벨 전이:
```bash
gh issue edit {N} --remove-label "in-progress" --add-label "in-review"
```
**기어 라벨 유지.**
2. Push + PR — **PR 번호를 변수로 확보**:
```bash
git push -u origin task/issue-{N}
PR=$(gh pr create --base "$BASE_BRANCH" --title "{type}: {요약} (#{N})" --body "Closes #{N}

## 구현 결과
...
## 테스트 증거
...
## 검토 포인트
..." | grep -oE '[0-9]+$')
echo "PR #$PR"
```
리뷰 + merge는 남겨둔다(review/merge가 처리).

3. downstream 확인 — 머지 전까지 downstream은 아직 GitHub상 blocked 상태일 수 있다:
```bash
BLOCKING=$(gh api -H "X-GitHub-Api-Version: $API_VERSION" \
  "repos/$OWNER/$REPO/issues/{N}/dependencies/blocking" \
  --jq '[.[] | select(.state == "open") | "#\(.number) \(.title)"] | join("\n")')
[ -n "$BLOCKING" ] && printf '머지 후 재검토할 downstream:\n%s\n' "$BLOCKING"
```
4. 로컬 정리 — A-1 standalone은 close까지 끝났고, ORCHESTRATED A-1과 A-2는 closeout 이후 정리된다:
```bash
git worktree remove .worktrees/issue-{N} 2>/dev/null || true
git checkout main && git branch -d task/issue-{N} 2>/dev/null || true
```

### 경로 B — 변경 없음 (직접 close)
```bash
gh issue comment {N} --body "## 결과

..."
gh issue edit {N} --remove-label "in-progress" --remove-label "in-review" --remove-label "changes-requested"
gh issue close {N}

BLOCKING=$(gh api -H "X-GitHub-Api-Version: $API_VERSION" \
  "repos/$OWNER/$REPO/issues/{N}/dependencies/blocking" \
  --jq '[.[] | select(.state == "open") | "#\(.number) \(.title)"] | join("\n")')
[ -n "$BLOCKING" ] && printf '이 이슈 close 후 재검토할 downstream:\n%s\n' "$BLOCKING"
```
**gear:* 라벨 유지.**

### (위키 가용 시) 위키 처리 — 경로별로 다르다
```bash
[ -d "./wiki" ] && echo "위키 가용"
```

**경로 A-2(review 필요 PR 경로)에서만 (`$PR`은 위 A-2에서 확보)**:
1. **(major) ADR 승격** — plan의 ADR 초안을 decision으로. review-free A-1은 승격할 ADR이 없으면 건너뛴다. 먼저 업무 루트 이슈를 확보([wiki-bridge.md](../../rules/wiki-bridge.md) §4 스니펫 (a))한 뒤 캡처:
```bash
read OWNER REPO < <(gh repo view --json owner,name --jq '"\(.owner.login) \(.name)"')
PARENT=$(gh api graphql -f query='query($o:String!,$r:String!,$n:Int!){ repository(owner:$o,name:$r){ issue(number:$n){ parent{ number } } } }' \
  -F o="$OWNER" -F r="$REPO" -F n={N} --jq '.data.repository.issue.parent.number // empty')
ROOT=${PARENT:-{N}}
wiki capture decision --title "..." --summary "..." --tags ... \
  --intents {INT} --tasks "$OWNER/$REPO#$ROOT" --rejected {REJ}
```
(필수 `--title/--summary/--tags` 채움; `--tasks`는 리프가 아닌 업무 루트 이슈.)
- 경로 A-2는 PR이 아직 안 머지됐다 — **task 노드 done 전이는 하지 않는다.** 전이는 `merge`가 루트 이슈 close 시 수행([wiki-bridge.md](../../rules/wiki-bridge.md) §5). 경로 A-1은 리프 close일 뿐이므로 루트가 닫힐 때 `merge`/reconcile이 task 전이를 처리한다.

**경로 B에서만 (변경 없이 close)**:
- PR이 없으므로 **드리프트 점검은 건너뛴다**(코드 변경 자체가 없음).
- 방금 close한 `{N}`이 **업무의 루트 이슈**라면(단일 리프 업무이거나, 루트 자체를 변경 없이 종료) 연결 task 노드를 직접 완료 전이. 루트 본문 `## Wiki Context`에서 TASK ID를 읽는다([wiki-bridge.md](../../rules/wiki-bridge.md) §4 스니펫 (a)(b)):
```bash
read OWNER REPO < <(gh repo view --json owner,name --jq '"\(.owner.login) \(.name)"')
PARENT=$(gh api graphql -f query='query($o:String!,$r:String!,$n:Int!){ repository(owner:$o,name:$r){ issue(number:$n){ parent{ number } } } }' \
  -F o="$OWNER" -F r="$REPO" -F n={N} --jq '.data.repository.issue.parent.number // empty')
# {N}이 리프(부모 있음)면 업무 미완료 — task 전이 안 함. {N} 자신이 루트일 때만 전이.
if [ -z "$PARENT" ]; then
  TASK=$(gh issue view {N} --json body --jq '.body' \
    | grep -oE 'TASK-[0-9]{4}-[0-9]{2}-[0-9]{2}-[0-9]{6}-[^][:space:]).,]+' | head -1)
  [ -n "$TASK" ] && wiki complete "$TASK"     # 활성 → wiki/task/done/
fi
```
  `{N}`이 컨테이너의 리프 중 하나일 뿐이면(부모 있음) task 전이는 하지 않는다(업무 미완료) — 마지막 자식까지 끝나 루트가 닫힐 때 `merge`/reconcile이 처리.

### Knowledge Capture Audit
최종 보고 전에 [knowledge-capture.md](../../rules/knowledge-capture.md)에 따라 감사한다.
```bash
[ -d "./wiki" ] && wiki recall "{작업 키워드}" --stage 1 --limit 10 --json
```
- 작업 중 자동 캡처한 observation이 있으면 `recorded`와 OBS ID를 보고한다.
- decision/rejected_decision/trial_error/ssot/runbook 후보가 있으면 제목·요약·태그·관계와 함께 `proposed`로 보고한다.
- 없으면 `none`과 이유를 보고한다.

### (orchestrated) run-notes append — 다음 형제 워커에 상속
`RUN_NOTES`가 있으면, 이번 작업에서 얻은 **재사용 가능한 사실**(검증한 SDK/API 형태, env quirk, 발견한 버그와 회피법)을 append한다. 다음 형제 워커가 Step 1.5에서 읽어 재도출을 피한다. advisory 스크래치일 뿐이라 wiki 캡처를 대체하지 않는다(장기 판단은 위 Audit에서 별도 승격 제안):
```bash
[ -n "$RUN_NOTES" ] && cat >> "$RUN_NOTES" <<EOF

## #{N} ($(date -u +%FT%TZ))
- {검증한 사실 / env quirk / 버그·회피법 — 다음 워커가 재도출 안 하도록}
EOF
```

### mechanism friction 보고 (F)
최종 보고 끝에 **워크플로 자체의 마찰**을 한 줄로 남긴다 — 미해소 스크립트 경로, 스킵한 게이트/스텝, 수동 보정한 ledger 이벤트, 재도출한 지식이 있었는지. 없으면 `none`. (제품 지식 아닌 메커니즘 회고 채널 — consumer wiki에 넣지 않는다.)

## 불변식
- 머지 세리머니는 머지 엣지의 속성이고 review 필요 여부로 게이팅(DEC-2026-07-02-224910): **review-free = FF closeout(PR 없음)**, **review-required = PR + 리뷰**. `--review=skip`이면 major도 review-free로 간다.
- 로컬 FF(A-1)는 closeout lane에서 `git fetch . task/issue-{N}:{BASE_BRANCH}` — checkout 없이 부모 ref 전진. main worktree HEAD는 트렁크를 떠나지 않는다(DEC-2026-07-02-212109 불변식 보존). non-FF 거부 시 부모를 리프로 역머지해 **리프-side에서** 충돌 해결·verify 재실행 후 재시도.
- close 증거: FF closeout = verify 리포트 + 커밋 SHA range(머지된 PR 대체), PR closeout = 머지된 PR.
- ORCHESTRATED에서 BASE_BRANCH가 비면 STOP(main fallback 금지). ORCHESTRATED worker는 `ready_for_closeout`을 기록하고, closeout lane이 FF 성공 시 `ff_merged`/`closeout_done` 이벤트를 기록한다.
- 상태 라벨만 정리, `gear:*` 유지.
- 열린 `blocked_by`가 있으면 종료 금지. 종료 후 `blocking` downstream을 안내.
- 위키 드리프트는 **hard gate**(경로 A 한정) — done이 위키를 자동 수정하지는 않지만, stale 문서가 남아 있으면 종료하지 않는다.
- task 노드 done 전이: 경로 A-2는 merge에 위임, A-1은 루트가 닫힐 때 merge/reconcile이 처리, 경로 B는 **루트 이슈를 직접 close할 때만** done이 수행.
- ADR/major 승격은 A-2(review 필요 PR 경로) 한정 — micro는 plan이 없어 승격할 ADR도 없다.
- 최종 보고 전에 Knowledge Capture Audit 결과를 포함한다.
