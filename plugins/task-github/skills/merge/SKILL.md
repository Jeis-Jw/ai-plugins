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

### Step 2. (위키 가용 시) 머지 전 hard gate
```bash
[ -d "./wiki" ] && echo "위키 가용"
```
가용 시 [quality-gates.md](../../rules/quality-gates.md) G1을 적용한다. **closeout 스크립트보다 먼저** 통과해야 한다(스크립트는 wiki를 모른다 — 게이트 판단은 에이전트 몫):
```bash
STRICT=$(wiki refresh --level integrity --strict --json) || {
  printf '%s\n' "$STRICT"
  exit 1
}
FILES=$(gh pr diff {PR} --name-only | paste -sd,)
DRIFT=$(wiki refresh --check changed-path-stale --changed-path "$FILES" --json)
printf '%s' "$DRIFT" | python3 -c 'import json,sys; sys.exit(1 if json.load(sys.stdin).get("issues") else 0)' || {
  printf '%s\n' "$DRIFT"
  exit 1
}
HYG=$(wiki refresh --level hygiene --json)  # 경고 surface (비차단)
```
`refresh --level integrity --strict`가 비0 종료하거나, `changed-path-stale` 이슈가 있으면 머지하지 않는다(integrity 깨짐 + 코드-문서 drift만 차단). `HYG`의 hygiene 이슈(orphan/stale/tags 등)는 머지를 막지 않고 머지 후 보고로만 남긴다. stale 문서는 `verified_at` 갱신 또는 supersede 대상이며, 자동 변경하지 않고 사령관에게 보완 경로를 보고한다.

### Step 3. closeout 스크립트로 머지 + 정리 (git/gh 결정적 시퀀스)
게이트 통과 후, `closeout.py`가 연결이슈 해석·blocker 재확인·라벨 정리·머지·브랜치 정리·downstream 안내·루트 닫힘 감지를 한 번에 한다. wiki는 호출하지 않고 `task_to_complete`만 방출한다.
```bash
# 1) dry-run으로 계획 확인 (머지·변경 없음, 읽기 전용)
python3 "${CLAUDE_SKILL_DIR}/scripts/closeout.py" --pr {PR} --dry-run --json

# 2) 확인되면 실제 실행
RESULT=$(python3 "${CLAUDE_SKILL_DIR}/scripts/closeout.py" --pr {PR} --json) || {
  printf '%s\n' "$RESULT"   # error_code: open_blockers / no_linked_issue / merge_failed ...
  exit 1
}
printf '%s\n' "$RESULT"
```
`open_blockers`면 머지하지 않고 중단(에이전트가 사령관에 보고). `downstream` 배열은 머지 후 재검토 대상으로 안내한다.

### Step 4. (위키 가용 시) task 노드 done 전이
`closeout.py` 출력의 `task_to_complete`가 비어있지 않으면(= 업무 루트 이슈가 이 머지로 close됨), 그 id로 task 노드를 done 전이한다:
```bash
TASK=$(printf '%s' "$RESULT" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("task_to_complete") or "")')
[ -n "$TASK" ] && wiki complete "$TASK"     # 활성 → wiki/task/done/
```
GitHub 이슈/PR 흐름이 상태 정본이고 위키 done/는 투영이다([wiki-bridge.md](../../rules/wiki-bridge.md) §5). task 노드 ID는 루트 이슈 `## Wiki Context`가 정본이며 `closeout.py`가 루트 본문에서 추출한다(한글 슬러그 보존). 리프 머지로 루트가 아직 안 닫혔으면 `task_to_complete`는 비어 전이하지 않는다.

### Step 5. Knowledge Capture Audit
최종 보고 전에 [knowledge-capture.md](../../rules/knowledge-capture.md)에 따라 감사한다.
- 이 머지로 완료된 업무에서 새 observation/decision/trial_error 후보가 생겼는지 확인한다.
- `blocking` downstream 안내가 운영상 새 교훈이나 runbook 변경을 요구하면 `proposed`로 보고한다.
- 후보가 없으면 `none`과 이유를 보고한다.

## 불변식
- `--merge`(머지 커밋) 방식.
- 상태 라벨 제거하되 `gear:*` 유지.
- 열린 `blocked_by`가 있으면 머지 금지. 머지 후 `blocking` downstream을 안내.
- 위키가 가용하면 `refresh --level integrity --strict`와 PR diff `changed-path-stale`를 통과해야 머지한다(integrity + drift만 차단; hygiene은 경고).
- Issue는 PR의 `Closes #N`으로 자동 close.
- task 노드 done 전이는 **루트 이슈가 실제 close될 때만**. 리프 하나 머지가 곧 업무 완료는 아니다.
- 최종 보고 전에 Knowledge Capture Audit 결과를 포함한다.
