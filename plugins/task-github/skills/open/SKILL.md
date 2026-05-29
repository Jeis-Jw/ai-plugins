---
name: open
description: GitHub Issue를 읽어 세션에 로드한다. 상태를 변경하지 않는 읽기 전용 도구. 연결된 위키 task 노드·결정도 함께 브리핑한다. "open 10", "이슈 10번 보자", "10번 이슈 열어줘" 등의 요청에 실행하라.
---

# open — Issue 읽기 전용 로드

Issue를 세션에 적재하고 브리핑한다. **상태(라벨·Assignee)를 절대 변경하지 않는다.**

## 입력

```
$ARGUMENTS: {이슈번호}   # 필수
```

## 절차

### Step 1. Issue 조회
```bash
gh issue view {N} --json title,state,body,labels,assignees,number,milestone
```

### Step 2. 트리 관계 조회 (GraphQL)
```bash
gh api graphql -f query='
query {
  repository(owner: "{OWNER}", name: "{REPO}") {
    issue(number: {N}) {
      parent { number title state }
      subIssues(first: 50) { nodes { number title state } }
      subIssuesSummary { total completed percentCompleted }
    }
  }
}'
```

### Step 3. 연결 PR 확인
```bash
gh pr list --search "{N}" --json number,title,state,headRefName
```

### Step 4. (위키 가용 시) Wiki Context 브리핑
```bash
[ -d "./wiki" ] && echo "위키 가용"
```
가용 시 — Issue 본문의 `## Wiki Context` 섹션을 파싱해 연결된 위키 노드를 읽어 함께 보여준다(읽기만):
- 루트 이슈면: `wiki recall --read {TASK-...},{DEC-...} --json`로 task 노드·결정 브리핑
- 리프 이슈면: 부모 루트의 task 노드로 거슬러 표시
- 자세한 규약은 [wiki-bridge.md](../../rules/wiki-bridge.md) §4.

### Step 5. 브리핑 출력
- 제목·상태·번호
- 상태 라벨 / 기어 라벨 **분리 표시**
- 부모/자식 관계 + 진행률
- 연결된 PR
- (위키) Wiki Context: task 노드 + 근거 결정
- 컨테이너/리프 판별 → 다음 행동 제안 (`define`/`start`)

## 불변식
- **부작용 0.** 읽기 전용. 라벨·Assignee·상태 변경 금지. 위키도 `recall`(읽기)만.
- `start`/`define` 진입 전 안전한 미리보기 역할.
