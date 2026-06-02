---
name: define
description: 업무를 GitHub Issue(루트 + 트리)로 등록하고, 위키가 있으면 결정·취지를 잇는 task 노드를 1:1로 만들어 연결한다. 자동 분해 금지 — 기준 없이 분해하지 않는다. "define", "이슈 만들어줘", "서브이슈 만들어줘", "define 10 도메인별로" 등의 요청에 실행하라.
---

# define — 업무 정의 (루트 이슈 + 위키 task 노드)

작업을 Issue(단일 또는 트리)로 구조화하고, 필요하면 하위 작업 간 GitHub Issue dependency를 정의한다. **위키가 있으면 업무 단위로 task 노드를 1:1 연결**한다. **등록 전 반드시 사령관 확인.**

> **업무 1개 = 루트 이슈 1개 + 위키 task 노드 1개.** task 노드는 업무(루트) 단위이며 **리프마다 만들지 않는다.** ([wiki-bridge.md](../../rules/wiki-bridge.md) §4)

## 입력 (3모드)

```
$ARGUMENTS:
  (없음)        # 모드 A: 대화 맥락을 업무로 등록
  {N}           # 모드 B: 해당 이슈 open 후 분해 기준 요청
  {N} {기준}    # 모드 C: 기준에 따라 서브이슈로 분해
```

## 절차

### 모드 A — 대화 맥락 등록 (루트 이슈 + task 노드)
1. 대화 내용 정리 (루트/서브 판단)
2. **(위키 가용 시) 관련 결정 recall** — 이 업무가 어떤 결정·취지에서 나오는지 파악:
```bash
[ -d "./wiki" ] && wiki recall "{업무 키워드}" --stage 1 --limit 10 --json
```
3. 생성 구조(루트 이슈 + 연결할 결정/취지 + task 노드 요약)를 사령관에게 보여주고 **확인**
4. 이슈 생성:
```bash
# 레포 정보 (owner/repo + repository node id 확보)
read OWNER REPO < <(gh repo view --json owner,name --jq '"\(.owner.login) \(.name)"')
API_VERSION="2026-03-10"
REPO_ID=$(gh api graphql -f query='query($o:String!,$r:String!){ repository(owner:$o,name:$r){ id } }' -F o="$OWNER" -F r="$REPO" --jq '.data.repository.id')

# 루트 이슈 — 생성과 동시에 번호를 확보 (이후 단계가 ROOT를 쓴다)
ROOT=$(gh issue create --title "{title}" --body "{body}

## Wiki Context
(define이 task 노드 연결 후 채움)" | grep -oE '[0-9]+$')
echo "루트 이슈 #$ROOT"

# (분해 시) 서브이슈 — 부모 node id 확보 후 GraphQL 연결.
# 생성한 번호는 dependency 연결에서 다시 쓰므로 변수로 보관한다.
PARENT_ID=$(gh api graphql -f query='query($o:String!,$r:String!,$n:Int!){ repository(owner:$o,name:$r){ issue(number:$n){ id } } }' -F o="$OWNER" -F r="$REPO" -F n=$ROOT --jq '.data.repository.issue.id')
CHILD=$(gh api graphql -f query='mutation($rid:ID!,$pid:ID!,$t:String!,$b:String!){ createIssue(input:{ repositoryId:$rid, parentIssueId:$pid, title:$t, body:$b }){ issue { number url } } }' -F rid="$REPO_ID" -F pid="$PARENT_ID" -F t="{제목}" -F b="{본문}" --jq '.data.createIssue.issue.number')
```

분해 기준이 단계/선후관계/공유 계약을 포함하면 각 하위 작업의 dependency도 함께 생성한다([dependencies.md](../../rules/dependencies.md)):
```bash
# 예: 이 하위 이슈 $CHILD가 선행 이슈 $BLOCKER 완료 뒤에만 시작 가능할 때
BLOCKER_ID=$(gh api -H "X-GitHub-Api-Version: $API_VERSION" \
  "repos/$OWNER/$REPO/issues/$BLOCKER" --jq '.id')

gh api -X POST -H "X-GitHub-Api-Version: $API_VERSION" \
  "repos/$OWNER/$REPO/issues/$CHILD/dependencies/blocked_by" \
  -F issue_id="$BLOCKER_ID" \
  || gh issue comment "$CHILD" --body "[관찰] dependency API 실패: 이 이슈는 #$BLOCKER 완료 뒤 진행되어야 한다. GitHub dependency가 기록되지 않았으므로 start 전 수동 확인 필요."
```
5. **(위키 가용 시) task 노드 생성 + 연결** (제안 후 확인) — **생성한 TASK ID를 확보해 루트 이슈 본문에 실제로 기록**한다. merge/done이 이 본문의 `[[TASK-...]]`를 읽어 완료 전이하므로(읽는 쪽의 전제), 여기서 반드시 실제 ID를 박아야 한다([wiki-bridge.md](../../rules/wiki-bridge.md) §4):
```bash
# (a) task 노드 생성 — --json 결과에서 실제 TASK ID 추출
TASK=$(wiki capture task \
  --title "{업무명}" --summary "{왜 이 업무가 생겼나 한 줄}" --tags {태그들} \
  --decisions {관련 DEC} --intents {상위 INT} --tasks "$OWNER/$REPO#$ROOT" --json \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
echo "task 노드 $TASK"

# (b) 루트 이슈 본문의 ## Wiki Context를 실제 ID로 갱신
#     (define이 4단계에서 넣어둔 placeholder 줄을 실제 링크로 치환)
BODY=$(gh issue view "$ROOT" --json body --jq '.body')
NEW_BODY=$(printf '%s' "$BODY" | python3 -c "
import sys,re
b=sys.stdin.read()
ctx='''## Wiki Context
**메인**: [[$TASK]] — 이 업무의 정의(요약·근거)
**보조**:
- [[{관련 DEC}]] — 근거가 된 결정
- [[{상위 INT}]] — 상위 취지'''
# 기존 ## Wiki Context 블록을 통째로 교체(없으면 끝에 추가)
b2=re.sub(r'## Wiki Context.*?(?=\n## |\Z)', ctx+'\n', b, flags=re.S)
print(b2 if '## Wiki Context' in b else b.rstrip()+'\n\n'+ctx+'\n')
")
gh issue edit "$ROOT" --body "$NEW_BODY"
```
> 위키 미가용이면 (a)(b) 전체를 스킵 — 이슈만 만들고 task 노드는 두지 않는다(정상). `{관련 DEC}`/`{상위 INT}`는 캡처에 쓴 것과 동일하게 채운다(없으면 보조 줄 생략).
6. **기어 라벨 안 붙임** — 기어 판단은 `start`에서.

### 모드 B — 분해 기준 요청
`open {N}`으로 현황 보여주고, 어떤 기준으로 분해할지 사령관에게 묻는다.

### 모드 C — 기준에 따라 분해
1. 기준(도메인/계층/단계 등)에 따라 서브이슈 목록 제시
   - 각 하위 이슈의 `blocked_by` 목록도 함께 제시한다.
   - dependency가 없으면 병렬 가능으로 표시한다.
   - 예: `#B blocked_by #A` = B는 A 완료 뒤 시작.
2. 사령관 확인
3. 각 서브이슈를 GraphQL로 생성 (부모 연결)
4. 필요한 dependency를 REST Issue dependency로 생성
5. **task 노드는 새로 만들지 않는다** — 루트의 task 노드를 자식들이 공유. (분해는 구조 변경이지 새 업무가 아님)

### 전 모드 — Knowledge Capture Audit
업무 정의 과정에서 새 결정·반려·관찰이 생기면 [knowledge-capture.md](../../rules/knowledge-capture.md)에 따라 처리한다.
- 자동 분해 기준, dependency 방향, rejected split 기준처럼 장기 운영 판단이면 `decision`/`rejected_decision` 후보로 제안한다.
- 분류 전 발견은 `observation`으로 자동 캡처할 수 있다.
- 후보가 없으면 `none`과 이유를 등록 전 확인안에 포함한다.

## 불변식
- **자동 분해 금지** — 기준 없이 분해하지 않는다. 기준은 사령관이 준다.
- 하위 작업 선후관계는 GitHub Issue dependency가 정본이다. `parallel`/`sequential` 라벨은 만들지 않는다.
- **기어 라벨을 붙이지 않는다** — define은 구조 생성만(기어는 start의 책임).
- **task 노드는 업무(루트) 1:1** — 리프·서브이슈마다 만들지 않는다.
- task 노드 캡처는 **제안 후 확인**. 위키 미가용이면 이슈만 만들고 task 노드는 스킵(정상).
- 등록 전 반드시 사령관 확인.
