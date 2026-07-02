---
name: review
description: 열린 PR이 연결된 Issue의 완료 조건을 충족하는지 검증한다. 위키가 있으면 PR이 반려된 대안으로 회귀하지 않는지 교차 점검한다. --auto-merge 플래그 사용 시 APPROVED 판정 후 task-github:merge를 자동 실행한다. "task-github:review", "PR 확인해줘", "PR 머지해도 돼?", "PR 검토해줘" 등의 요청에 실행하라.
---

# review — PR 검증

열린 PR을 `pr-verifier` 서브에이전트로 검증(복수는 병렬)하고 판정별로 라벨 전이. **머지는 하지 않는다**(merge 스킬에 위임, `--auto-merge` 예외).

> **merge-edge-gear 모델(DEC-2026-07-02-224910)에서 review는 MAJOR 엣지에서만 돈다.** PR은 major 리프와, 자식 누적 기어가 major로 승격된 컨테이너(`container_gear_promotion`)에만 존재한다. micro/normal 엣지는 PR도 review도 없다 — 이들의 게이트는 verify + 커밋 SHA range 증거(로컬 FF 머지)다. 즉 이 스킬은 "PR이 이미 열려 있다"는 major 엣지 전제에서 동작한다. 아래 PR 검증 절차 자체는 그대로다.

## 입력

```
$ARGUMENTS: [PR_NUMBER] [--auto-merge]
  없음            # 열린 PR 전체
  {PR}            # 단건
  --auto-merge    # APPROVED 시 자동 merge
```

## 절차

### Step 1. 대상 PR 결정
```bash
# 단건
gh pr view {PR} --json number,title,headRefName,state
# 전체
gh pr list --state open --json number,title,headRefName
```

### Step 2. in-review 부착 (중복 검토 방지)
```bash
gh pr edit {PR} --add-label "in-review"
```
**gear:* 안 건드림.**

### Step 3. 연결 Issue 추출 + verify 결과 로드
```bash
# PR 본문의 Closes #N 또는 브랜치명 task/issue-{N}에서 연결 이슈 번호 확보
ISSUE=$(gh pr view {PR} --json body,headRefName \
  --jq '(try (.body|capture("[Cc]loses #(?<n>[0-9]+)").n) catch empty) // (try (.headRefName|capture("issue-(?<n>[0-9]+)").n) catch empty)')
gh issue view "$ISSUE" --comments | awk '/## 검증 결과/,/^---$/'
```
- verify 코멘트 있음 → pr-verifier **spot-check 모드** (의심 2~3건만)
- 없음 → **전수 검증 모드**

### Step 4. (위키 가용 시) Wiki Context 전달
```bash
[ -d "./wiki" ] && echo "위키 가용"
```
가용 시 — 연결 Issue의 `## Wiki Context`에서 task 노드의 근거 결정을 추출해 pr-verifier에 전달. PR 변경이 **이미 반려된 대안(rejected_decision)으로 회귀**하지 않는지 교차 점검하게 한다.

### Step 5. pr-verifier 배정 (PR별, 병렬)

### Step 6. 판정별 행동 (`$ISSUE`는 Step 3에서 확보)
- **APPROVED + --auto-merge** → `task-github:merge {PR}` 자동 실행
- **APPROVED** → PR·Issue `in-review` 제거, 머지 안내
- **CHANGES_REQUESTED** → Issue+PR `in-review`→`changes-requested`
- **NEEDS_REVIEW** → `in-review` 제거, 사령관 판단 요청

## 불변식
- review는 판정·라벨까지, 머지는 merge가.
- team 프로파일은 `--auto-merge` 명시 필요(solo는 자동 허용).
- 위키는 **읽기만**(recall) — 교차 점검 용도.
