---
name: run
description: Issue 또는 record:none DefinitionArtifact local run을 수행한다. Issue 번호는 기존 경로, --artifact/--run-state는 pinned node를 GitHub Issue write 없이 실행한다. "task-github:run", "작업 수행해줘", "구현 시작해줘" 등의 요청에 실행하라.
---

# run — 실행

계획 또는 완료 조건을 기준으로 작업을 수행한다.

## 입력

```
$ARGUMENTS: {N} | --artifact {PATH} --run-state {RUN_JSON}
```

## 절차

### record:none DefinitionArtifact mode

`--artifact/--run-state`가 있으면 먼저 `recover` 결과가 `started` 또는 재개 가능한 `running`인지 확인한다. run-state가 node를 이미 pin하므로 `--node`를 재입력하지 않는다. 출력의 stable branch/worktree가 없으면 주입된 `BASE_BRANCH`에서 만든 뒤 idempotent `run` 전이를 기록하고 artifact node 완료 조건을 실행한다:

```bash
python3 "${TASK_GITHUB_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/definition_artifact.py" recover \
  --artifact {PATH} --run-state {RUN_JSON}
read BRANCH WORKTREE < <(python3 -c 'import json,sys; i=json.load(open(sys.argv[1]))["identity"]; print(i["branch"], i["worktree"])' {RUN_JSON})
if [ ! -d "$WORKTREE" ]; then
  git show-ref --verify --quiet "refs/heads/$BRANCH" \
    && git worktree add "$WORKTREE" "$BRANCH" \
    || git worktree add "$WORKTREE" -b "$BRANCH" "$BASE_BRANCH"
fi
python3 "${TASK_GITHUB_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/definition_artifact.py" local-event \
  --artifact {PATH} --run-state {RUN_JSON} --event run
```

helper가 revision/digest, local dependency, stable identity를 fail-closed로 검증한다. 이 모드에서는 아래 GitHub dependency/label/comment 절을 건너뛰고, 관찰은 위키에만 기록한다. 아래 `{N}` 절차는 변경 없는 legacy/projected Issue 경로다.

### Step 1. 작업 기준 확인 (세션 컨텍스트 우선)
- plan이 컨텍스트에 있으면 그대로 사용 (재조회 금지)
- 끊겼으면: `gh issue view {N} --comments`에서 "작업 계획" 코멘트 탐색
- 계획 있음 → 태스크 목록 기준
- 계획 없음 → 완료 조건 기준 (`plan:false` flow)

### Step 1.5. (orchestrated) run-notes 읽기 — 재도출 금지
`RUN_NOTES`가 주입돼 있으면(orchestrate 핸드오프), **작업 시작 전 먼저 읽는다.** 이 파일은 오케스트레이터가 시드한 gotcha와, **앞선 형제 워커가 남긴 검증된 사실**(안정 API 형태, env quirk, 발견된 버그)의 advisory 스크래치다(SoT 아님 — 상태는 ledger 소관). 여기 이미 있는 사실은 **재도출·재검증하지 않고 그대로 상속**한다:
```bash
[ -n "$RUN_NOTES" ] && [ -f "$RUN_NOTES" ] && cat "$RUN_NOTES"
```
> 목적: fan-out에서 형제 워커가 같은 SDK API·env·버그를 각자 재학습하는 낭비를 없앤다. 발견은 `done`에서 이 파일에 append한다.

### Step 2. dependency 차단 재확인
`start`를 우회해 `run`이 직접 호출될 수 있으므로 열린 blocker를 다시 확인한다:
```bash
read OWNER REPO < <(gh repo view --json owner,name --jq '"\(.owner.login) \(.name)"')
API_VERSION="2026-03-10"
OPEN_BLOCKERS=$(gh api -H "X-GitHub-Api-Version: $API_VERSION" \
  "repos/$OWNER/$REPO/issues/{N}/dependencies/blocked_by" \
  --jq '[.[] | select(.state == "open") | "#\(.number) \(.title)"] | join("\n")')

if [ -n "$OPEN_BLOCKERS" ]; then
  gh issue comment {N} --body "[중단] 열린 blocker가 있어 run을 중단합니다.

$OPEN_BLOCKERS"
  exit 1
fi
```
dependency API 조회가 실패하면 자동 실행하지 않고 사령관에게 수동 확인을 요청한다.

### Step 3. 재작업 감지
```bash
gh issue view {N} --json labels --jq '.labels[].name'
```
`changes-requested`면 재작업 모드로 진입(Issue·PR 라벨을 `in-progress`로):
```bash
gh issue edit {N} --remove-label "changes-requested" --add-label "in-progress"
PR=$(gh pr list --head task/issue-{N} --json number --jq '.[0].number')
[ -n "$PR" ] && gh pr edit $PR --remove-label "changes-requested" --add-label "in-progress"
```

**재작업 완료 후(커밋·push 시)** 라벨을 리뷰 대기 상태로 되돌린다([workflow.md](../../rules/workflow.md) 상태 전이와 일치):
```bash
# Issue: in-progress → in-review
gh issue edit {N} --remove-label "in-progress" --add-label "in-review"
# PR: in-progress 제거 (라벨 없는 '리뷰어 픽업 대기' 상태로 복귀; review가 다시 in-review 부착)
[ -n "$PR" ] && gh pr edit $PR --remove-label "in-progress"
```
> Issue와 PR의 전이가 비대칭이다: Issue는 `in-review`를 **달고**, PR은 라벨을 **떼어** 픽업 대기로 둔다(PR의 `in-review`는 review 스킬이 픽업 시 부착). 이 규약의 정본은 [workflow.md](../../rules/workflow.md) "상태 전이".

### Step 4. 워크트리 (소스 변경 시)
**모든 리프(micro/normal/major)는 자기 워크트리에서 작업한다** — 기어와 무관하게 `.worktrees/issue-{N}` + 자기 브랜치 `task/issue-{N}`, base = parent branch. 컨테이너/epic 브랜치는 순수 ref일 뿐 워크트리·체크아웃이 없고 FF로만 전진한다(DEC-2026-07-02-224910). 즉 여기서 워크트리를 만드는 주체는 항상 리프다.
```bash
touch .gitignore
grep -qxF ".worktrees/" .gitignore || printf "\n.worktrees/\n" >> .gitignore
if [ "$ORCHESTRATED" = "true" ] && [ -z "$BASE_BRANCH" ]; then
  gh issue comment {N} --body "[중단] orchestrated mode: BASE_BRANCH(expected PR base) 없음. main fallback 금지."
  exit 1
fi
BASE_BRANCH=${BASE_BRANCH:-$(python3 "${TASK_GITHUB_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/task_config.py" get base_branch 2>/dev/null || echo main)}  # orchestrate는 parent branch 주입, standalone은 .task-github.yml base_branch(없으면 main).
git worktree add .worktrees/issue-{N} -b task/issue-{N} "$BASE_BRANCH"
# .worktreeinclude 처리 + 잔재 점검 (git clean은 컨펌 후)
```
> ORCHESTRATED + 빈 BASE_BRANCH는 위처럼 hard STOP이다(main fallback 금지). 리프 base는 parent branch여야 하며, 머지 세리머니(micro/normal 로컬 FF, major PR)는 리프가 아니라 **머지 엣지**의 속성이다 — 이 워크트리 자체는 세 기어 모두 동일하다.

### Step 5. 작업 수행
- 계획 태스크 순차 실행
- 복잡/독립 태스크는 서브에이전트 위임
- **원자적 커밋**: `{type}: {요약} (#{N}) — {Why}`

#### Step 5.1. phase 리프 실행 (본문에 phase 체크리스트가 있으면)
여러 표면을 한 리프로 재합침한 이슈(define §절단 원리 재합침)는 본문에 phase 체크리스트를 갖는다. 이때:
- **phase별 원자적 커밋** — 각 phase 완료 시 커밋하고, 이슈 본문/코멘트의 체크박스를 갱신한다(중간 되돌림 지점).
- **phase별 표면 검증 + 마지막 full-verify** — 앞 phase는 그 표면만 검증, 마지막 phase에서 전체(typecheck/test/export/스모크)를 1회 돌린다.
- **phase별 세션 재진입 (compaction 방어).** 리프가 길어 한 세션에 다 담기 부담되면 phase 경계에서 워커 세션을 새로 이어받아도 된다 — **같은 이슈·브랜치(`task/issue-{N}`)·worktree를 그대로 유지**하고, 앞 phase에서 얻은 패턴·결정은 이슈 코멘트 또는 `RUN_NOTES`(orchestrated)로 승계한다. 세리머니(이슈·PR·closeout·머지엣지)는 **리프 1개분으로 1회 유지**된다 — 세션을 나눠도 새 이슈/브랜치/머지엣지를 만들지 않는다.

### Step 6. 예외 처리 (Issue 코멘트에 태그 기록)
| 상황 | 태그 | 행동 |
|------|------|------|
| 판단 필요 | `[질문]` | 사령관 확인 후 계속 |
| 아키텍처·방향 결정 | `[결정]` | Issue 코멘트 기록, verify에서 decision 승격 |
| 분류 전 발견 | `[관찰]` | 아래 위키 자동 캡처 |
| 실패·우회 | `[시행착오]` | Issue 코멘트 기록, verify에서 trial_error 승격 |
| 복구 불가 | `[중단]` | 실패 지점·원인·상태 기록 후 사령관 보고 |

### Step 7. (위키 가용 시) 관찰 자동 캡처
```bash
[ -d "./wiki" ] && echo "위키 가용"
```
`[관찰]`을 발견하면 즉시 자동 캡처(저위험). 먼저 **업무 루트 이슈 번호를 확보**한다([wiki-bridge.md](../../rules/wiki-bridge.md) §4 공통 스니펫 (a)):
```bash
read OWNER REPO < <(gh repo view --json owner,name --jq '"\(.owner.login) \(.name)"')
PARENT=$(gh api graphql -f query='query($o:String!,$r:String!,$n:Int!){ repository(owner:$o,name:$r){ issue(number:$n){ parent{ number } } } }' \
  -F o="$OWNER" -F r="$REPO" -F n={N} --jq '.data.repository.issue.parent.number // empty')
ROOT=${PARENT:-{N}}
wiki capture observation \
  --title "{관찰명}" --summary "{무엇을 발견}" --tags {태그들} \
  --tasks "$OWNER/$REPO#$ROOT" --affects-paths "src/<area>/**"
```
> `--tasks`는 업무 **루트 이슈**(`$ROOT`)를 쓴다 — 지식 노드가 task 노드와 같은 ref로 묶여야 추적이 이어진다. `{N}`이 단일 리프 업무면 부모가 없어 `$ROOT`=`{N}`.
- `[결정]`/`[시행착오]`는 코멘트 태그로만 남기고 **verify에서 승격 제안**(1급 노드는 제안 후 확인).
- 미가용 → Issue 코멘트 태그로만.

### Step 8. Knowledge Capture Audit
작업 종료 전 [knowledge-capture.md](../../rules/knowledge-capture.md)에 따라 감사한다.
- 자동 캡처한 observation이 있으면 `recorded`와 OBS ID를 남긴다.
- `[결정]`/`[시행착오]` 후보가 있으면 Issue 코멘트에 태그로 남겨 `verify`가 승격 제안하게 한다.
- 기록할 것이 없으면 `none`과 이유를 남긴다.

## 불변식
- 원자적 커밋(1커밋=1논리변경, WIP 금지).
- 워크트리 미커밋 변경 보존.
- Issue mode는 열린 GitHub `blocked_by`, record:none mode는 helper가 보고한 local blocker가 있으면 실행 금지.
- 코드 변경 워크트리 생성은 run 책임이다(start에서 만들지 않는다).
- Issue 리프는 `.worktrees/issue-{N}` + `task/issue-{N}`, record:none node는 run-state의 stable identity에서 작업한다. 컨테이너/epic 브랜치는 워크트리 없는 순수 ref다. ORCHESTRATED + 빈 BASE_BRANCH는 hard STOP.
- observation만 자동 캡처. decision/trial_error는 verify에서 확인 후 승격.
- Knowledge Capture Audit 결과를 남긴다.
