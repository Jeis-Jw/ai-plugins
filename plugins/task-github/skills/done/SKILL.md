---
name: done
description: 작업을 종료한다. 코드 변경이 있으면 PR을 생성하고 로컬을 정리하며, 변경이 없으면 Issue를 바로 close한다. 위키가 있으면 코드 변경이 낡게 만든 문서를 점검한다. "task-github:done", "PR 만들어줘", "작업 마무리해줘", "이슈 닫아줘" 등의 요청에 실행하라.
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

### 경로 판단
```bash
git worktree list
git diff main...HEAD --name-only 2>/dev/null || git status --short
```

### 경로 A — 변경 있음 (PR 생성)
1. 미커밋 변경 커밋: `{type}: {요약} (#{N}) — {Why}`
2. **드리프트 hard gate** ([quality-gates.md](../../rules/quality-gates.md) G1) — PR 생성 전에 이번 브랜치가 낡게 만든 위키 문서 탐지:
```bash
if [ -d "./wiki" ]; then
  FILES=$(git diff --name-only main...HEAD | paste -sd,)
  DRIFT=$(wiki refresh --check changed-path-stale --changed-path "$FILES" --json)
  printf '%s' "$DRIFT" | python3 -c 'import json,sys; sys.exit(1 if json.load(sys.stdin).get("issues") else 0)' || {
    printf '%s\n' "$DRIFT"
    exit 1
  }
  HYG=$(wiki refresh --level hygiene --json)  # 경고 surface (비차단)
fi
```
`changed-path-stale`(drift) 이슈가 있으면 PR을 만들지 않고 done을 중단한다. 리포트된 ssot/runbook/trial_error/observation은 `verified_at` 갱신 또는 supersede 대상이며, 자동 변경하지 않고 보완 후 다시 `done`을 실행한다. `HYG`의 hygiene 이슈는 done을 막지 않고 리포트로만 남긴다.
3. 라벨 전이:
```bash
gh issue edit {N} --remove-label "in-progress" --add-label "in-review"
```
**기어 라벨 유지.**
4. Push + PR — **PR 번호를 변수로 확보**:
```bash
git push -u origin task/issue-{N}
PR=$(gh pr create --title "{type}: {요약} (#{N})" --body "Closes #{N}

## 구현 결과
...
## 테스트 증거
...
## 검토 포인트
..." | grep -oE '[0-9]+$')
echo "PR #$PR"
```
5. downstream 확인 — PR 머지 전까지 downstream은 아직 GitHub상 blocked 상태일 수 있다:
```bash
BLOCKING=$(gh api -H "X-GitHub-Api-Version: $API_VERSION" \
  "repos/$OWNER/$REPO/issues/{N}/dependencies/blocking" \
  --jq '[.[] | select(.state == "open") | "#\(.number) \(.title)"] | join("\n")')
[ -n "$BLOCKING" ] && printf 'PR 머지 후 재검토할 downstream:\n%s\n' "$BLOCKING"
```
6. 로컬 정리:
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

**경로 A에서만 (PR 생성됨, `$PR`은 위 4단계에서 확보)**:
1. **(major) ADR 승격** — plan의 ADR 초안을 decision으로. 먼저 업무 루트 이슈를 확보([wiki-bridge.md](../../rules/wiki-bridge.md) §4 스니펫 (a))한 뒤 캡처:
```bash
read OWNER REPO < <(gh repo view --json owner,name --jq '"\(.owner.login) \(.name)"')
PARENT=$(gh api graphql -f query='query($o:String!,$r:String!,$n:Int!){ repository(owner:$o,name:$r){ issue(number:$n){ parent{ number } } } }' \
  -F o="$OWNER" -F r="$REPO" -F n={N} --jq '.data.repository.issue.parent.number // empty')
ROOT=${PARENT:-{N}}
wiki capture decision --title "..." --summary "..." --tags ... \
  --intents {INT} --tasks "$OWNER/$REPO#$ROOT" --rejected {REJ}
```
(필수 `--title/--summary/--tags` 채움; `--tasks`는 리프가 아닌 업무 루트 이슈.)
- 경로 A는 PR이 아직 안 머지됐다 — **task 노드 done 전이는 하지 않는다.** 전이는 `merge`가 루트 이슈 close 시 수행([wiki-bridge.md](../../rules/wiki-bridge.md) §5).

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
- PR은 코드 변경이 있을 때만 생성.
- 상태 라벨만 정리, `gear:*` 유지.
- 열린 `blocked_by`가 있으면 종료 금지. 종료 후 `blocking` downstream을 안내.
- 위키 드리프트는 **hard gate**(경로 A 한정) — done이 위키를 자동 수정하지는 않지만, stale 문서가 남아 있으면 종료하지 않는다.
- task 노드 done 전이: 경로 A는 merge에 위임, 경로 B는 **루트 이슈를 직접 close할 때만** done이 수행.
- 최종 보고 전에 Knowledge Capture Audit 결과를 포함한다.
