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
   - 등록 전 확인안에는 [quality-gates.md](../../rules/quality-gates.md) G3 기준을 포함한다: 근거, 완료 기준, 검증, 영향 경로/파일, 관련 intent/decision.
   - 기준이 비어 있으면 자동으로 보완하지 말고 `FLAG-to-human`으로 표시한 뒤 확인받는다.
4. 이슈 생성 — 테스트된 배치 헬퍼 사용:
```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/create_issue_tree.py" \
  --spec /tmp/task-github-issue-tree.json \
  --dry-run --json

RESULT=$(python3 "${CLAUDE_SKILL_DIR}/scripts/create_issue_tree.py" \
  --spec /tmp/task-github-issue-tree.json \
  --json)
ROOT=$(printf '%s' "$RESULT" | python3 -c "import sys,json;print(json.load(sys.stdin)['root_number'])")
```

spec 형식:
```json
{
  "root": {
    "title": "{title}",
    "body": "{body}\n\n## Wiki Context\n(define이 task 노드 연결 후 채움)"
  },
  "children": [
    {
      "key": "U1",
      "title": "{하위 이슈 제목}",
      "body": "{하위 이슈 본문}\n\n완료 기준: ...\n검증: ...\n영향 경로: src/area/**",
      "affects_paths": ["src/area/**"],
      "blocked_by": []
    },
    {
      "key": "U2",
      "title": "{후속 이슈 제목}",
      "body": "{후속 이슈 본문}\n\n완료 기준: ...\n검증: ...\n영향 경로: src/area-next/**",
      "affects_paths": ["src/area-next/**"],
      "blocked_by": ["U1"]
    }
  ]
}
```
헬퍼는 서브이슈 부모 연결을 **GraphQL `createIssue(parentIssueId)`** 로 통일한다. child마다 완료 기준, 검증 anchor, 영향 경로/파일 anchor, `affects_paths`가 필요하다. `affects_paths`가 겹치는 child는 한쪽 `blocked_by`를 선언해야 dry-run을 통과한다([quality-gates.md](../../rules/quality-gates.md) G3/G4). dependency는 REST Issue dependency API를 쓰며 `X-GitHub-Api-Version: 2026-03-10`을 고정한다. dependency API 실패 시 헬퍼가 child 이슈에 fallback 코멘트를 남긴다([dependencies.md](../../rules/dependencies.md)).
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
   - 하위 이슈마다 완료 기준, 검증 방법, 영향 경로/파일을 포함한다. path가 겹치는데 `blocked_by`가 없으면 [quality-gates.md](../../rules/quality-gates.md) G4에 따라 사령관 확인 또는 dependency 보완으로 승급한다.
   - brainstorm으로 나온 단위별 상세 설계(데이터 모델, DDL, API, 프롬프트 계약)는 **서브이슈 본문**에 둔다. 실행 중 새로 확정되는 장기 판단만 그때 `decision`/`observation`으로 캡처한다.
2. 사령관 확인
3. `/tmp/task-github-issue-tree.json` spec 작성
4. `create_issue_tree.py --dry-run --json`으로 계획 검증 후 실제 실행
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
- 단위 상세 설계는 서브이슈 본문 또는 해당 단위 실행 중 캡처되는 DEC/OBS에 둔다. 위키 리프 task 노드는 만들지 않는다. 이미 만들었다면 내용을 서브이슈로 이전한 뒤 task 노드를 `retire --type deprecated`한다.
- task 노드 캡처는 **제안 후 확인**. 위키 미가용이면 이슈만 만들고 task 노드는 스킵(정상).
- 등록 전 반드시 사령관 확인.
