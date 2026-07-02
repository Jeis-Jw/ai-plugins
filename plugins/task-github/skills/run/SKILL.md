---
name: run
description: Issue 기반으로 작업을 수행한다. 계획이 있으면 그 태스크 목록을, 없으면 Issue 완료 조건을 기준으로 작업한다. 작업 중 발견한 관찰은 위키에 자동 기록한다. "task-github:run", "작업 수행해줘", "구현 시작해줘" 등의 요청에 실행하라.
---

# run — 실행

계획 또는 완료 조건을 기준으로 작업을 수행한다.

## 입력

```
$ARGUMENTS: {N}
```

## 절차

### Step 1. 작업 기준 확인 (세션 컨텍스트 우선)
- plan이 컨텍스트에 있으면 그대로 사용 (재조회 금지)
- 끊겼으면: `gh issue view {N} --comments`에서 "작업 계획" 코멘트 탐색
- 계획 있음 → 태스크 목록 기준
- 계획 없음 → 완료 조건 기준 (`plan:false` flow)

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
```bash
touch .gitignore
grep -qxF ".worktrees/" .gitignore || printf "\n.worktrees/\n" >> .gitignore
if [ "$ORCHESTRATED" = "true" ] && [ -z "$BASE_BRANCH" ]; then
  gh issue comment {N} --body "[중단] orchestrated mode: BASE_BRANCH(expected PR base) 없음. main fallback 금지."
  exit 1
fi
BASE_BRANCH=${BASE_BRANCH:-$(python3 plugins/task-github/scripts/task_config.py get base_branch 2>/dev/null || echo main)}  # orchestrate는 parent branch 주입, standalone은 .task-github.yml base_branch(없으면 main).
git worktree add .worktrees/issue-{N} -b task/issue-{N} "$BASE_BRANCH"
# .worktreeinclude 처리 + 잔재 점검 (git clean은 컨펌 후)
```

### Step 5. 작업 수행
- 계획 태스크 순차 실행
- 복잡/독립 태스크는 서브에이전트 위임
- **원자적 커밋**: `{type}: {요약} (#{N}) — {Why}`

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
- 열린 `blocked_by`가 있으면 실행 금지.
- 코드 변경 워크트리 생성은 run 책임이다(start에서 만들지 않는다).
- observation만 자동 캡처. decision/trial_error는 verify에서 확인 후 승격.
- Knowledge Capture Audit 결과를 남긴다.
