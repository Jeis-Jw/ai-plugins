---
name: merge
description: PR을 머지하고 라벨·브랜치를 정리한다. 루트 이슈가 닫히면 연결된 위키 task 노드를 완료로 전이한다. 검증 없이 바로 머지하거나, task-github:review 후 머지할 때 사용한다. "task-github:merge", "머지해줘", "PR 합쳐줘" 등의 요청에 실행하라.
---

# merge — PR 머지 (PR 경로 전용)

PR 머지 + GitHub/로컬 정리. review와 분리되어 검증 없이/검증 후 둘 다에서 사용.

**이 스킬(`closeout.py`)은 PR 경로 전용이다.** 세리머니는 노드 속성이 아니라 **머지 엣지** 속성이고 gear로 게이트된다([[DEC-2026-07-02-224910]]):
- **micro/normal 리프는 PR이 없다** — done에서 부모 브랜치로 로컬 FF 머지하므로(NO PR) 이 스킬에 **도달하지 않는다**. close 근거는 검증 리포트 + 커밋 SHA 범위(머지된 PR을 대체).
- 이 스킬은 **major 리프 PR**과, **컨테이너/epic 머지업 PR**(컨테이너의 계산된 gear가 major일 때만)을 처리한다.
- 컨테이너가 PR을 만들어야 하는 시점(즉 언제 major로 승격되는지)은 [orchestrator_ops.container_gear_promotion](../orchestrate/SKILL.md) 규칙이 정본이다: base = children 최댓값(micro<normal<major), 그 위에 micro 3개↑→normal 승격, normal 2개↑→major 승격. 컨테이너 자신의 gear 라벨은 무시하고 children으로부터 매 머지 엣지마다 새로 계산한다.
- micro/normal close-candidate가 이 경로로 라우팅되면 **오류다** — 로컬 FF 경로(done)로 되돌린다.

## 입력

```
$ARGUMENTS:
  {PR_NUMBER}    # 머지할 PR. major 리프 PR과 컨테이너/epic 머지업 PR(gear major) 모두 같은 경로.
                 # micro/normal 리프는 PR이 없어 여기 오지 않는다.
```

## 절차

### Step 1. PR 확인
```bash
gh pr view {PR} --json number,title,headRefName,baseRefName,state,labels,body
```
연결 이슈와 루트 이슈를 확인한 뒤 공통 context bundle을 만든다. `merge`는 이 bundle의 `blockers`/`downstream`/`wiki_task`/`integrity`를 closeout 전후 브리핑 기준으로 사용한다.

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

### Step 3. merge preflight evidence 기록
게이트 통과 후 `merge_preflight.py`를 먼저 실행한다. 이 스크립트는 live PR head(`headRefOid`), mergeability, CI/check, reviewDecision을 한 번의 PR 조회 boundary에서 확인하고, 통과한 wiki gate 결과를 `gate_evidence`로 ledger에 기록한다. `headRefOid`가 기대값과 다르거나 required field가 빠지면 closeout으로 넘어가지 않는다. parent/root PR이면 ledger의 child `merge_evidence`/`gate_evidence`를 소비해 valid child path를 `changed-path-stale` target에서 제외하고, invalid/missing/overlap child path는 fallback target으로 검사한다.

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/merge_preflight.py" \
  --pr {PR} --orchestrate-ledger ".task-github/orchestrate/{ROOT}.json" --json
```

### Step 4. closeout 스크립트로 머지 + 정리 (git/gh 결정적 시퀀스)
preflight 통과 후, `closeout.py`가 연결이슈 해석·blocker 재확인·라벨 정리·머지·브랜치 정리·downstream 안내·루트 닫힘 감지를 한 번에 한다. wiki는 호출하지 않고 `task_to_complete`만 방출한다. 모든 머지는 `gh pr merge`(remote)이며 closeout은 로컬 `git checkout`을 하지 않는다 — 머지 후 base 브랜치 갱신은 `git fetch origin {base}:{base}`(base가 현재 HEAD면 `git pull --ff-only`)로 처리해 사령관의 메인 워크트리 HEAD가 trunk를 벗어나지 않는다([[DEC-2026-07-02-212109]]). merge 성공 뒤 base sync/branch cleanup 실패는 `sync_warnings`로만 보고한다. closeout은 merge fact만 기록하고 wiki gate를 다시 실행하지 않는다.

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
orchestrate 중이면 ledger를 같이 넘긴다:
```bash
RESULT=$(python3 "${CLAUDE_SKILL_DIR}/scripts/closeout.py" \
  --pr {PR} --orchestrate-ledger ".task-github/orchestrate/{ROOT}.json" --json)
```
`open_blockers`면 머지하지 않고 중단(에이전트가 사령관에 보고). `downstream` 배열은 머지 후 재검토 대상으로 안내한다.

> 컨테이너/epic 머지업 **PR**도 major 리프 PR과 같은 경로다. 단, 컨테이너는 자신의 계산된 gear([orchestrator_ops.container_gear_promotion](../orchestrate/SKILL.md))가 major일 때만 PR을 만든다 — sub-major 컨테이너는 로컬 FF로 부모에 forward하고 이 스킬을 거치지 않는다. major 컨테이너 머지업은 worker가 없어 PR이 자동 생성되지 않으므로, **orchestrate가 `gh pr create --base task/issue-{parent} --head task/issue-{container}`로 PR을 먼저 만든 뒤** preflight + closeout으로 넘긴다([orchestrate](../orchestrate/SKILL.md) container_done).

### Step 5. (위키 가용 시) task 노드 done 전이
`closeout.py` 출력의 `task_to_complete`가 비어있지 않으면(= 업무 루트 이슈가 이 머지로 close됨), 그 id로 task 노드를 done 전이한다:
```bash
TASK=$(printf '%s' "$RESULT" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("task_to_complete") or "")')
[ -n "$TASK" ] && wiki complete "$TASK"     # 활성 → wiki/task/done/
```
GitHub 이슈/PR 흐름이 상태 정본이고 위키 done/는 투영이다([wiki-bridge.md](../../rules/wiki-bridge.md) §5). task 노드 ID는 루트 이슈 `## Wiki Context`가 정본이며 `closeout.py`가 루트 본문에서 추출한다(한글 슬러그 보존). 리프 머지로 루트가 아직 안 닫혔으면 `task_to_complete`는 비어 전이하지 않는다.

### Step 6. Knowledge Capture Audit
최종 보고 전에 [knowledge-capture.md](../../rules/knowledge-capture.md)에 따라 감사한다.
- 이 머지로 완료된 업무에서 새 observation/decision/trial_error 후보가 생겼는지 확인한다.
- `blocking` downstream 안내가 운영상 새 교훈이나 runbook 변경을 요구하면 `proposed`로 보고한다.
- 후보가 없으면 `none`과 이유를 보고한다.

## 불변식 (PR 경로)
- 이 불변식은 **PR 경로**(major 리프 + major 컨테이너 머지업)에만 적용된다. micro/normal 리프의 로컬 FF 머지는 done/orchestrate 소관이며 여기 오지 않는다.
- `--merge`(머지 커밋) 방식.
- 이 스킬의 머지는 `gh pr merge`(remote) 하나다. 여기서는 로컬 `git checkout`/`git merge`를 하지 않는다 — 머지 후 base 갱신도 `git fetch origin {base}:{base}`로 처리해 메인 워크트리 HEAD가 trunk 불변([[DEC-2026-07-02-212109]]). (micro/normal 로컬 FF는 이 경로 밖에서 fetch refspec으로 처리되며, 이 역시 메인 워크트리 HEAD를 옮기지 않는다.)
- 상태 라벨 제거하되 `gear:*` 유지.
- 열린 `blocked_by`가 있으면 머지 금지. 머지 후 `blocking` downstream을 안내.
- 위키가 가용하면 `refresh --level integrity --strict`와 PR diff `changed-path-stale`를 통과해야 머지한다(integrity + drift만 차단; hygiene은 경고).
- default branch PR은 `Closes #N` 자동 close를 사용한다. non-default base PR은 merge 후 linked issue를 직접 close한다.
- task 노드 done 전이는 **루트 이슈가 실제 close될 때만**. 리프 하나 머지가 곧 업무 완료는 아니다.
- 최종 보고 전에 Knowledge Capture Audit 결과를 포함한다.
- context bundle/link integrity는 판단 입력이다. wiki 상태 변경은 closeout 결과의 `task_to_complete`를 받은 뒤 `wiki complete`로만 수행한다.
