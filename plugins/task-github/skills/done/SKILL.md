---
name: done
description: 작업을 종료한다. 코드 변경이 있으면 gear에 따라 PR 또는 로컬 FF로 닫고, 변경이 없으면 Issue를 바로 close한다. 위키가 있으면 코드 변경이 낡게 만든 문서를 점검한다. "task-github:done", "PR 만들어줘", "작업 마무리해줘", "이슈 닫아줘" 등의 요청에 실행하라.
---

# done — PR 생성 또는 close

작업 종료 + GitHub/로컬 상태 정리. 코드 변경 유무로 2경로.

## 입력

```
$ARGUMENTS: {N}
```

## 절차

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
if [ "$ORCHESTRATED" = "true" ] && [ -z "$BASE_BRANCH" ]; then
  gh issue comment {N} --body "[중단] orchestrated mode: BASE_BRANCH(expected merge base) 없음. 머지/PR 전 STOP, main fallback 금지."
  exit 1
fi
BASE_BRANCH=${BASE_BRANCH:-$(python3 plugins/task-github/scripts/task_config.py get base_branch 2>/dev/null || echo main)}
```

### 경로 판단
변경 유무는 리프의 base(부모 브랜치 `$BASE_BRANCH`)에 대해 판단한다 — orchestrate에서 리프 base는 `main`이 아니라 `task/issue-{parent}`이므로 `main` 고정 diff는 부모의 기머지 커밋을 오탐한다:
```bash
git worktree list
git diff "$BASE_BRANCH"...HEAD --name-only 2>/dev/null || git status --short
```

### 경로 A — 변경 있음 (기어로 분기)
머지 세리머니는 **리프가 아니라 머지 엣지의 속성**이고 기어로 게이팅한다(DEC-2026-07-02-224910). 이슈 기어를 읽어 분기한다:
- **micro / normal** — PR 없음. verify 후 리프 브랜치를 부모(BASE_BRANCH)로 **로컬 FF 머지**하고 SHA range 증거로 이슈를 close.
- **major** — 오늘처럼 PR 경로. 직렬 체인 안이라도 major는 **자기 브랜치 + PR**을 가진다(부모 브랜치에 직접 커밋 금지) — 리뷰된 diff가 게이트를 통과해야 의존 작업이 그 위에 쌓인다.

**trunk 예외:** BASE_BRANCH가 trunk(=`task/issue-*`가 아님, root 직속 리프)면 trunk가 사령관의 메인 워크트리에 체크아웃돼 있어 `git fetch . leaf:trunk`가 거부된다(git이 checked-out 브랜치 갱신을 막음, 이게 곧 [[DEC-2026-07-02-212109]] 불변식의 근거). 이 경우 micro/normal이라도 A-1 대신 **A-2(PR 경로)**를 탄다 — trunk로의 합류는 항상 PR이다.

```bash
GEAR=$(gh issue view {N} --json labels --jq '[.labels[].name]' \
  | python3 -c 'import json,sys; from pathlib import Path; sys.path.insert(0,"plugins/task-github/skills/orchestrate/scripts"); import orchestrator_ops as o; print(o.gear_of_labels(json.load(sys.stdin)) or "normal")')
# 머지 경로: major이거나 부모가 trunk(체크아웃돼 로컬 FF 불가)면 PR(A-2), 아니면 로컬 FF(A-1)
case "$BASE_BRANCH" in task/issue-*) PARENT_IS_TASK=1 ;; *) PARENT_IS_TASK=0 ;; esac
if [ "$GEAR" = "major" ] || [ "$PARENT_IS_TASK" = "0" ]; then ROUTE=pr; else ROUTE=ff; fi
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

ORCHESTRATED micro/normal FF 경로에서는 drift gate 통과 결과를 부모가 재사용할 수 있도록 `gate_evidence`를 먼저 ledger에 기록한다. evidence에는 canonical changed path list, `changed_paths_hash`, `checked_paths_hash`, `drift_surface_hash`, `tool_versions`, `gate_version`, 빈 `changed_path_stale_issues`가 모두 있어야 한다. required field가 빠지면 issue close/FF merge를 하지 않는다. 그 뒤 `ff_merged` event를 같은 closeout 구간에서 기록한다.

#### A-1) micro / normal — 로컬 FF 머지 (PR 없음) — `ROUTE=ff`
리프 브랜치를 부모 ref로 **checkout 없이** FF 전진시킨다(`ff_merge_command`; self-fetch refspec — main worktree HEAD는 트렁크를 떠나지 않는다, DEC-2026-07-02-212109 불변식 보존). 이 명령은 리프 worktree에서 실행한다:
```bash
FILES=$(git diff --name-only "$BASE_BRANCH"...HEAD | paste -sd,)
HEAD_SHA=$(git rev-parse HEAD)
FF_GATE_ARGS=(--ff-gate --issue {N} --head-sha "$HEAD_SHA" --changed-path "$FILES" --json)
[ "$ORCHESTRATED" = "true" ] && FF_GATE_ARGS+=(--orchestrate-ledger "$LEDGER")
python3 plugins/task-github/skills/merge/scripts/merge_preflight.py "${FF_GATE_ARGS[@]}" || exit 1

# git fetch . task/issue-{N}:{BASE_BRANCH} — checkout 없이 부모 ref 전진
git fetch . task/issue-{N}:"$BASE_BRANCH" || {
  # 부모가 움직여 non-FF로 거부됨 → 부모를 리프 worktree로 역머지, 리프-side에서 충돌 해결
  git merge "$BASE_BRANCH"
  # (충돌 해결 후) verify 재실행 → 통과하면 FF 재시도
  git fetch . task/issue-{N}:"$BASE_BRANCH"
}
git push origin "$BASE_BRANCH"
```
충돌은 **항상 리프-side**(리프 worktree의 역머지)에서 해결한다 — 오퍼레이터 main worktree에서 해결하지 않는다.

close 증거 = verify 리포트 + 커밋 SHA range(`git rev-parse`로 범위 산출), close:
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
**gear:* 라벨 유지.** ORCHESTRATED에서는 ledger에 `ff_merged` 이벤트 기록:
```bash
[ "$ORCHESTRATED" = "true" ] && python3 skills/orchestrate/scripts/orchestrate_ledger.py "$LEDGER" \
  --event ff_merged --issue {N} --base "$BASE_BRANCH" --sha-range "$SHA_RANGE"
```

#### A-2) major (또는 부모가 trunk) — PR 경로 — `ROUTE=pr`
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
4. 로컬 정리 — micro/normal(A-1)은 close까지 끝났고, major(A-2)는 PR 머지 후 정리된다:
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

**경로 A-2(major PR 경로)에서만 (`$PR`은 위 A-2에서 확보)**:
1. **(major) ADR 승격** — plan의 ADR 초안을 decision으로. micro/normal(A-1)은 plan/ADR 초안이 없으므로 승격할 ADR도 없다. 먼저 업무 루트 이슈를 확보([wiki-bridge.md](../../rules/wiki-bridge.md) §4 스니펫 (a))한 뒤 캡처:
```bash
read OWNER REPO < <(gh repo view --json owner,name --jq '"\(.owner.login) \(.name)"')
PARENT=$(gh api graphql -f query='query($o:String!,$r:String!,$n:Int!){ repository(owner:$o,name:$r){ issue(number:$n){ parent{ number } } } }' \
  -F o="$OWNER" -F r="$REPO" -F n={N} --jq '.data.repository.issue.parent.number // empty')
ROOT=${PARENT:-{N}}
wiki capture decision --title "..." --summary "..." --tags ... \
  --intents {INT} --tasks "$OWNER/$REPO#$ROOT" --rejected {REJ}
```
(필수 `--title/--summary/--tags` 채움; `--tasks`는 리프가 아닌 업무 루트 이슈.)
- 경로 A-2는 PR이 아직 안 머지됐다 — **task 노드 done 전이는 하지 않는다.** 전이는 `merge`가 루트 이슈 close 시 수행([wiki-bridge.md](../../rules/wiki-bridge.md) §5). 경로 A-1(micro/normal)은 리프 close일 뿐이므로 루트가 닫힐 때 `merge`/reconcile이 task 전이를 처리한다.

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

## 불변식
- 머지 세리머니는 머지 엣지의 속성이고 기어로 게이팅(DEC-2026-07-02-224910): **micro/normal = 로컬 FF 머지(PR 없음)**, **major = PR + 리뷰**. major는 직렬 체인 안이라도 자기 브랜치 + PR을 가진다.
- 로컬 FF(A-1)는 `git fetch . task/issue-{N}:{BASE_BRANCH}` — checkout 없이 부모 ref 전진. main worktree HEAD는 트렁크를 떠나지 않는다(DEC-2026-07-02-212109 불변식 보존). non-FF 거부 시 부모를 리프로 역머지해 **리프-side에서** 충돌 해결·verify 재실행 후 재시도.
- close 증거: micro/normal = verify 리포트 + 커밋 SHA range(머지된 PR 대체), major = 머지된 PR.
- ORCHESTRATED에서 BASE_BRANCH가 비면 STOP(main fallback 금지). ORCHESTRATED FF 성공 시 ledger에 `ff_merged` 이벤트 기록.
- 상태 라벨만 정리, `gear:*` 유지.
- 열린 `blocked_by`가 있으면 종료 금지. 종료 후 `blocking` downstream을 안내.
- 위키 드리프트는 **hard gate**(경로 A 한정) — done이 위키를 자동 수정하지는 않지만, stale 문서가 남아 있으면 종료하지 않는다.
- task 노드 done 전이: 경로 A-2(major)는 merge에 위임, A-1(micro/normal)은 루트가 닫힐 때 merge/reconcile이 처리, 경로 B는 **루트 이슈를 직접 close할 때만** done이 수행.
- ADR/major 승격은 A-2(major PR 경로) 한정 — micro는 plan이 없어 승격할 ADR도 없다.
- 최종 보고 전에 Knowledge Capture Audit 결과를 포함한다.
