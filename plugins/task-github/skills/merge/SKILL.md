---
name: merge
description: PR을 머지하고 라벨·브랜치를 정리한다. 루트 이슈가 닫히면 연결된 위키 task 노드를 완료로 전이한다. 검증 없이 바로 머지하거나, task-github:review 후 머지할 때 사용한다. "task-github:merge", "머지해줘", "PR 합쳐줘" 등의 요청에 실행하라.
---

# merge — PR 머지

PR 머지 + GitHub/로컬 정리. review와 분리되어 검증 없이/검증 후 둘 다에서 사용.

## 입력

```
$ARGUMENTS: {PR_NUMBER}
```

## 절차

### Step 1. PR 확인
```bash
gh pr view {PR} --json number,title,headRefName,baseRefName,state,labels,body
```

### Step 2. 연결 Issue·브랜치 추출 (변수로 확보)
```bash
# PR 본문 Closes #N 또는 브랜치명 task/issue-{N}에서 연결 이슈 번호
ISSUE=$(gh pr view {PR} --json body,headRefName \
  --jq '(try (.body|capture("[Cc]loses #(?<n>[0-9]+)").n) catch empty) // (try (.headRefName|capture("issue-(?<n>[0-9]+)").n) catch empty)')
HEADREF=$(gh pr view {PR} --json headRefName --jq .headRefName)
echo "연결 이슈 #$ISSUE / 브랜치 $HEADREF"
```
> 분해된 업무라면 이 `$ISSUE`가 컨테이너의 리프일 수 있다. Step 5의 task 전이는 **업무 루트**가 닫힐 때만 하므로, 부모를 거슬러 루트를 따로 확인한다(아래).

### Step 3. 라벨 정리 (상태만, gear 유지)
```bash
gh pr edit {PR} --remove-label "in-review" --remove-label "in-progress" --remove-label "changes-requested" 2>/dev/null || true
gh issue edit "$ISSUE" --remove-label "in-review" --remove-label "in-progress" --remove-label "changes-requested" 2>/dev/null || true
```

### Step 4. 머지 + 브랜치 정리
```bash
gh pr merge {PR} --merge --delete-branch
git branch -d "$HEADREF" 2>/dev/null || true
git checkout main && git pull
```

### Step 5. (위키 가용 시) task 노드 done 전이 + 드리프트 확정
```bash
[ -d "./wiki" ] && echo "위키 가용"
```
가용 시:
1. **task 노드 완료 전이** — 이 머지로 **업무 루트 이슈가 close되면** 연결 task 노드를 done으로:
```bash
# (a) 업무 루트 찾기: $ISSUE의 부모가 있으면 그게 루트, 없으면 $ISSUE 자신이 루트
read OWNER REPO < <(gh repo view --json owner,name --jq '"\(.owner.login) \(.name)"')
PARENT=$(gh api graphql -f query='query($o:String!,$r:String!,$n:Int!){ repository(owner:$o,name:$r){ issue(number:$n){ parent{ number } } } }' \
  -F o="$OWNER" -F r="$REPO" -F n="$ISSUE" --jq '.data.repository.issue.parent.number // empty')
ROOT=${PARENT:-$ISSUE}

# (b) 루트가 닫혔는지 확인 (컨테이너면 모든 자식 close 후 닫힘)
STATE=$(gh issue view "$ROOT" --json state --jq .state)

# (c) 닫혔으면, 루트 이슈 본문 ## Wiki Context에서 연결 task 노드 ID를 읽어 완료 전이
if [ "$STATE" = "CLOSED" ]; then
  # task 노드 ID의 정본 경로는 루트 이슈 본문의 ## Wiki Context (define이 기록).
  # (wiki recall --backlinks-of 는 외부 이슈 ref를 역링크로 찾지 못한다 — 본문 파싱이 정본.)
  TASK=$(gh issue view "$ROOT" --json body \
    --jq '.body' | grep -oE 'TASK-[0-9]{4}-[0-9]{2}-[0-9]{2}-[0-9]{6}-[A-Za-z0-9-]+' | head -1)
  [ -n "$TASK" ] && wiki complete "$TASK"     # 활성 → wiki/task/done/
fi
```
GitHub 이슈가 상태 정본이고 위키 done/는 투영이다([wiki-bridge.md](../../rules/wiki-bridge.md) §5). task 노드 ID는 루트 이슈 `## Wiki Context`가 정본 — `--backlinks-of`는 외부 이슈 ref(`owner/repo#N`)를 역링크 대상으로 찾지 못하므로 쓰지 않는다([wiki-bridge.md](../../rules/wiki-bridge.md) §4).
2. **영향 record 갱신 안내** — done의 drift 리포트에 걸렸던 ssot/runbook은 `verified_at` 갱신 또는 supersede **안내**(자동 변경 안 함).

## 불변식
- `--merge`(머지 커밋) 방식.
- 상태 라벨 제거하되 `gear:*` 유지.
- Issue는 PR의 `Closes #N`으로 자동 close.
- task 노드 done 전이는 **루트 이슈가 실제 close될 때만**. 리프 하나 머지가 곧 업무 완료는 아니다.
