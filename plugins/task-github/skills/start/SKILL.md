---
name: start
description: 리프 Issue를 점유하거나 task-worker DefinitionArtifact node의 local run을 시작한다. 이슈 번호/제목은 기존 Issue 모드, --artifact/--node는 GitHub 기록 없는 local facade다. "task-github:start", "작업 시작하자", "start 10" 등의 요청에 실행하라.
---

# start — 리프 Issue 점유 + 기어 판단

리프 Issue를 점유하거나 record:none local run을 시작한다. **Issue mode에서 기어를 판단하고 `gear:*` 라벨을 부여**하는 유일한 지점이다.

## 입력 (3모드)

```
$ARGUMENTS:
  "제목" [설명]   # 모드 A: 리프 이슈 생성 + 즉시 점유
  {N}            # 모드 B: 기존 이슈 점유
  --artifact {PATH} --node {KEY|NODE_ID} [--run-id {ID}]  # 모드 C: record:none local
```

## 절차

### 모드 C — local DefinitionArtifact facade

canonical artifact에는 provider `record` 필드가 없다. local facade 선택을 확인하고 immutable revision/node를 task-worker run에 pin한다. GitHub 기록을 선택한 작업은 full projection 뒤 기존 Issue 번호 모드로 진입한다.

```bash
python3 "${TASK_GITHUB_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/task_worker_bridge.py" local-start \
  --artifact {PATH} --node {KEY|NODE_ID} --state-dir .task-github/local/runs \
  ${RUN_ID:+--run-id "$RUN_ID"}
```

출력의 `path`를 `RUN_STATE`로, stable `identity.branch/worktree`를 다음 `run`에 전달한다. 이 모드에서는 `gh issue create/edit/comment`, assignee, label을 전부 건너뛴다. lifecycle과 dependency 규약은 [workflow.md](../../rules/workflow.md)의 DefinitionArtifact 절을 따른다. 아래 모드 A/B는 변경 없는 legacy Issue 경로다.

### 시작 전 — dirty wiki vault 점검 (위키 가용 시)
워크트리 생성 전 메인 vault에 **미커밋 rationale 레코드**가 있으면 경고한다(**차단 아님**). 잔여 레코드가 워크트리 코드 작업과 공유 인덱스에서 엉키는 것을 막는다([wiki-bridge.md](../../rules/wiki-bridge.md) §8):
```bash
if [ -d "./wiki" ]; then
  DIRTY=$(git status --porcelain -- wiki/context wiki/task 2>/dev/null)
  [ -n "$DIRTY" ] && printf '[경고] 미커밋 wiki rationale 레코드가 있습니다 — 워크트리 생성 전 메인에 커밋 권장:\n%s\n' "$DIRTY"
fi
```

### 모드 A — 리프 이슈 생성 + 즉시 점유 (micro 단발 전용)

> **이 모드는 micro 단발 작업 전용이다.** 판단이 normal/major면 — 즉 업무가 결정·취지를 동반하거나 분해가 필요하면 — **`define`으로 전환**해 루트 이슈 + 위키 task 노드를 먼저 만든 뒤 그 리프를 `start {N}`(모드 B)로 점유한다. (모드 A로 바로 시작하면 task 노드 1:1 다리를 우회한다 → [wiki-bridge.md](../../rules/wiki-bridge.md) §4)

1. **기어 판단** (파급력 기준). **micro면 이 모드 계속, 아니면 위 안내대로 `define` 권유.**
2. 이슈 생성 — **번호를 변수로 확보**(이후 단계가 `$N`을 쓴다):
```bash
N=$(gh issue create --title "{title}" --body "{body}" | grep -oE '[0-9]+$')
echo "이슈 #$N"
```
3. 점유 (모드 A는 micro 전용이므로 `gear:micro`):
```bash
gh issue edit $N --add-assignee @me --add-label "in-progress" --add-label "gear:micro"
```
> 라벨은 항상 `gear:micro|normal|major` 중 하나 — **`gear:full`은 존재하지 않는다.** flow option도 gear별로 계산한다(§task-protocol §1·§3).
> **기어는 이제 머지 엣지도 고른다**(DEC-2026-07-02-224910): `micro`/`normal` → 부모로 로컬 FF 머지(PR 없음), `major` → PR + 리뷰 후 머지. 즉 정직한 파급력 기어 판단이 곧 ceremony/overhead를 직접 통제한다(같은 판단 기준은 그대로 유지).
4. 다음 단계 권장 — micro이므로 `run {N}` 또는 직접 편집 후 `done {N}`. (micro 단발이라 대화 요약 코멘트·위키 task 노드 주입은 생략 — 그 맥락이 필요한 업무면 애초에 define 경로로 갔어야 한다.)

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

점유 직전/직후 브리핑은 공통 context bundle을 우선 사용한다:
```bash
python3 "${TASK_GITHUB_ROOT:-$CLAUDE_PLUGIN_ROOT}/scripts/context_bundle.py" --input snapshot.json
```
`blockers`/`downstream`/`wiki_task`/`worktree_path`는 이후 `plan`/`run`에 넘기는 세션 컨텍스트의 기준 shape다. `integrity.errors`가 있으면 점유 전 보고하고, 링크 복구가 필요하면 별도 reconcile 지시를 받는다.

## 불변식
- Issue mode 기어 판단·라벨 부여의 **단일 책임 지점**. (record:none local mode는 라벨 없음)
- 컨테이너 이슈는 작업 대상이 아니다(차단).
- 열린 `blocked_by`가 있는 이슈는 작업 대상이 아니다(차단).
- 점유 중복 방지 — 타인 점유 Issue는 사령관 확인 없이 시작 금지.
- start는 위키를 **읽기만**(recall) — task 노드 생성은 define의 책임.
- 시작 시 **dirty wiki vault를 경고**(차단 아님) — 미커밋 rationale 레코드가 워크트리 작업과 엉키는 것을 예방([wiki-bridge.md](../../rules/wiki-bridge.md) §8).
- start는 워크트리를 만들지 않는다. 코드 작업 워크트리는 run 책임이다.
- task-github가 만든 context bundle은 wiki task를 대체하지 않는다. Issue mode wiki task는 ROOT 이슈에, record:none mode는 DefinitionArtifact 업무 정의에 연결된다.
