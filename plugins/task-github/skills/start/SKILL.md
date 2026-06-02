---
name: start
description: 리프 Issue를 점유해 작업을 시작한다. 이슈 번호를 인자로 받으면 해당 이슈를 점유하고, 제목을 받으면 리프 이슈를 생성 후 즉시 점유한다. 기어를 판단해 gear 라벨을 부여하고, 연결된 위키 task 노드의 맥락을 주입한다. "task-github:start", "작업 시작하자", "start 10" 등의 요청에 실행하라.
---

# start — 리프 Issue 점유 + 기어 판단

리프 Issue를 점유하고 작업 세션을 시작한다. **기어를 판단하고 `gear:*` 라벨을 부여**하는 유일한 지점.

## 입력 (2모드)

```
$ARGUMENTS:
  "제목" [설명]   # 모드 A: 리프 이슈 생성 + 즉시 점유
  {N}            # 모드 B: 기존 이슈 점유
```

## 절차

### 모드 A — 리프 이슈 생성 + 즉시 점유 (micro 단발 전용)

> **이 모드는 micro 단발 작업 전용이다.** 판단이 normal/major(solo의 full)면 — 즉 업무가 결정·취지를 동반하거나 분해가 필요하면 — **`define`으로 전환**해 루트 이슈 + 위키 task 노드를 먼저 만든 뒤 그 리프를 `start {N}`(모드 B)로 점유한다. (모드 A로 바로 시작하면 task 노드 1:1 다리를 우회한다 → [wiki-bridge.md](../../rules/wiki-bridge.md) §4)

1. **기어 판단** (파급력 기준). **micro면 이 모드 계속, 아니면 위 안내대로 `define` 권유.**
2. 이슈 생성 — **번호를 변수로 확보**(이후 단계가 `$N`을 쓴다):
```bash
N=$(gh issue create --title "{title}" --body "{body}" | grep -oE '[0-9]+$')
echo "이슈 #$N"
```
3. (코드 변경 시) 워크트리 생성:
```bash
git worktree add .claude/worktrees/issue-$N -b task/issue-$N
# .worktreeinclude 처리
if [ -f .worktreeinclude ]; then
  while IFS= read -r f; do [ -n "$f" ] && [ -f "$f" ] && cp "$f" ".claude/worktrees/issue-$N/$f"; done < .worktreeinclude
fi
```
4. 점유 (모드 A는 micro 전용이므로 `gear:micro`):
```bash
gh issue edit $N --add-assignee @me --add-label "in-progress" --add-label "gear:micro"
```
> 라벨은 항상 `gear:micro|normal|major` 중 하나 — **`gear:full`은 존재하지 않는다.** solo의 `full` 판단도 라벨은 파급력대로 normal/major를 붙인다(§task-protocol §1·§2).
5. 다음 단계 권장 — micro이므로 `run {N}` 또는 직접 편집 후 `done {N}`. (micro 단발이라 대화 요약 코멘트·위키 task 노드 주입은 생략 — 그 맥락이 필요한 업무면 애초에 define 경로로 갔어야 한다.)

### 모드 B — 기존 이슈 점유
1. 이슈 현황 + 트리 관계 + dependency 확인 (open과 동일 조회)
2. **컨테이너 차단**: 자식 있으면 작업 불가 안내
3. **dependency 차단**: 열린 `blocked_by`가 있으면 작업 불가 안내
```bash
read OWNER REPO < <(gh repo view --json owner,name --jq '"\(.owner.login) \(.name)"')
API_VERSION="2026-03-10"
OPEN_BLOCKERS=$(gh api -H "X-GitHub-Api-Version: $API_VERSION" \
  "repos/$OWNER/$REPO/issues/{N}/dependencies/blocked_by" \
  --jq '[.[] | select(.state == "open") | "#\(.number) \(.title)"] | join("\n")')

if [ -n "$OPEN_BLOCKERS" ]; then
  echo "차단: 이 이슈는 아직 열린 blocker가 있습니다."
  printf '%s\n' "$OPEN_BLOCKERS"
  exit 1
fi
```
dependency API 조회가 실패하면 자동 점유하지 않는다. 사령관에게 수동 확인 필요성을 보고하고, override 지시가 있을 때만 `[결정] dependency override` 코멘트를 남긴 뒤 진행한다([dependencies.md](../../rules/dependencies.md)).
4. 점유 가능 판단:
   - `in-progress`/`in-review` → 차단
   - `changes-requested` + 타인 Assignee → 경고 후 확인
   - 그 외 → 가용
5. 점유 + 기어 라벨 부여/유지:
```bash
gh issue edit {N} --add-assignee @me --add-label "in-progress"
# 기어 라벨 없으면 재판단 후 부여; 있으면 유지(재판단 결과가 다르면 사령관 확인 후 교체)
```
6. 기어별 다음 단계 권장 호출 제시

### (전 모드) 위키 task 맥락 주입 — normal/major
```bash
[ -d "./wiki" ] && echo "위키 가용"
```
가용 시 — 점유한 리프의 **부모 루트에 연결된 task 노드**와 그 근거 결정/취지를 세션 컨텍스트로 주입(재조회 최소화):
- 부모 루트 이슈 본문 `## Wiki Context`에서 task 노드 basename 추출
- `wiki recall --read {TASK-...} --json`로 업무 정의·근거 확보 → plan/run이 재사용
- 자세한 규약은 [wiki-bridge.md](../../rules/wiki-bridge.md).

## 불변식
- 기어 판단·라벨 부여의 **단일 책임 지점**. (기존 gear 라벨 있으면 유지, 없으면 부여)
- 컨테이너 이슈는 작업 대상이 아니다(차단).
- 열린 `blocked_by`가 있는 이슈는 작업 대상이 아니다(차단).
- 점유 중복 방지 — 타인 점유 Issue는 사령관 확인 없이 시작 금지.
- start는 위키를 **읽기만**(recall) — task 노드 생성은 define의 책임.
