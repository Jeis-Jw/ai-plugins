---
name: define
description: 업무를 GitHub Issue(루트 + 트리)로 등록하고, 위키가 있으면 결정·취지를 잇는 task 노드를 1:1로 만들어 연결한다. 자동 분해 금지 — 기준 없이 분해하지 않는다. "define", "이슈 만들어줘", "서브이슈 만들어줘", "define 10 도메인별로" 등의 요청에 실행하라.
---

# define — 업무 정의 (작업정의 task 노드 → 루트 이슈)

작업을 Issue(단일 또는 트리)로 구조화하고, 필요하면 하위 작업 간 GitHub Issue dependency를 정의한다. **위키가 있으면 업무 단위로 task 노드를 1:1 연결**한다. **등록 전 반드시 사령관 확인.**

> **업무 1개 = 위키 task 노드 1개 + 루트 이슈 1개.** task 노드는 업무(루트) 단위이며 **리프마다 만들지 않는다.** ([wiki-bridge.md](../../rules/wiki-bridge.md) §4)
>
> **순서: 작업정의(위키 task)가 수행(이슈)보다 먼저.** 위키 가용 시 이슈 생성 **전에** 작업정의 task 노드를 확보(있으면 링크, 없으면 capture)하고, 이슈 생성은 사령관 "진행" 확인으로 게이트한다. 위키 미가용이면 세션 컨텍스트로 이슈만 만든다(정상). 조율은 task-github가 한다 — 위키는 task-github를 모른다([wiki-bridge.md](../../rules/wiki-bridge.md) §1).

## 입력 (3모드)

```
$ARGUMENTS:
  (없음)        # 모드 A: 대화 맥락을 업무로 등록
  {N}           # 모드 B: 해당 이슈 open 후 분해 기준 요청
  {N} {기준}    # 모드 C: 기준에 따라 서브이슈로 분해
```

## 절차

### 시작 전 — dirty wiki vault 점검 (위키 가용 시)
업무 정의·캡처 전에 메인 vault에 **미커밋 rationale 레코드**가 남아 있으면 경고한다. 잔여 미커밋 레코드는 이번 define의 새 레코드와 공유 context 인덱스에서 엉켜 작업별 분리 커밋을 막는다([wiki-bridge.md](../../rules/wiki-bridge.md) §8):
```bash
if [ -d "./wiki" ]; then
  DIRTY=$(git status --porcelain -- wiki/context wiki/task 2>/dev/null)
  [ -n "$DIRTY" ] && printf '[경고] 미커밋 wiki rationale 레코드가 있습니다 — 정의 전 메인에 커밋/정리 권장(작업별 분리 커밋·dangling 방지):\n%s\n' "$DIRTY"
fi
```
경고는 **차단이 아니다**(최소 적용분). 잔여 레코드가 이번 업무의 근거가 아니라면 먼저 커밋한 뒤 진행한다.

### 모드 A — 대화 맥락 등록 (작업정의 task 노드 → 루트 이슈)

1. 대화 내용 정리 (루트/서브 판단)
2. **(위키 가용 시) 관련 결정 recall** — 이 업무가 어떤 결정·취지에서 나오는지 파악:
```bash
[ -d "./wiki" ] && wiki recall "{업무 키워드}" --stage 1 --limit 10 --json
```
3. **(위키 가용 시) 작업정의 task 노드 확보 — 이슈보다 먼저.** 위키는 작업정의 문서를 만드는 주체이고, define은 그 문서를 *확보*한 뒤에야 수행 이슈로 넘어간다:
   - **기존 소스 탐색** — 이 업무의 작업정의 노드가 이미 있는지 본다(활성 task 중 이슈 미연결인 것; 같은 세션에서 위키로 막 만들었다면 그게 소스):
   ```bash
   [ -d "./wiki" ] && wiki recall "{업무 키워드}" --type task --stage 1 --json
   ```
   - **있으면** → 그 노드를 소스로 사용(아래 6에서 이슈 역링크). `TASK={그 basename}`.
   - **없으면** → 작업정의 노드를 **먼저 생성**(제안 후 확인). 이슈 번호가 아직 없으므로 `--tasks` 없이 캡처하고 6에서 잇는다:
   ```bash
   TASK=$(wiki capture task \
     --title "{업무명}" --summary "{왜 이 업무가 생겼나 한 줄}" --tags {태그들} \
     --decisions {관련 DEC} --intents {상위 INT} --json \
     | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
   echo "작업정의 task 노드 $TASK (이슈보다 먼저)"
   ```
   > **대기 vs 트리거**: 단일 에이전트면 위 capture로 즉시 생성한다(트리거). 다른 세션/사람이 위키 작업정의를 만들기로 했다면, 노드가 생길 때까지 **대기**한 뒤 다음으로 간다.
   > 위키 미가용이면 3 전체 스킵 — 이슈만 만들고 task 노드는 두지 않는다(정상).
4. **진행 확인 (이슈 생성 게이트)** — 생성 구조(루트 이슈 + 연결할 작업정의 task 노드 + 결정/취지)를 사령관에게 보여주고 **"진행?" 확인**.
   - 확인안에는 [quality-gates.md](../../rules/quality-gates.md) G3 기준을 포함한다: 근거, 완료 기준, 검증, 영향 경로/파일, 관련 intent/decision.
   - 트리가 2개 이상 리프면 **Topology Decision 섹션도 필수 포함**한다(아래 "트리 깊이 / 토폴로지 결정 게이트" 참조).
   - 기준이 비어 있으면 자동으로 보완하지 말고 `FLAG-to-human`으로 표시한 뒤 확인받는다.
   - 트리에 container(epic)가 있으면 확인안에 **Container Independence Check** 섹션(아래 §트리 깊이/토폴로지)을 포함한다.
5. 이슈 생성 — 테스트된 배치 헬퍼 사용:
```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/create_issue_tree.py" \
  --spec /tmp/task-github-issue-tree.json \
  --dry-run --strict-deps --json

RESULT=$(python3 "${CLAUDE_SKILL_DIR}/scripts/create_issue_tree.py" \
  --spec /tmp/task-github-issue-tree.json \
  --strict-deps --json)
ROOT=$(printf '%s' "$RESULT" | python3 -c "import sys,json;print(json.load(sys.stdin)['root_number'])")
```

spec 형식:
```json
{
  "root": {
    "title": "{title}",
    "body": "{body}\n\n## Wiki Context\n(define이 task 노드 역링크 후 채움)",
    "execution_contract": {
      "wiki_task": "{TASK-... 또는 null}",
      "topology": "flat|stacked",
      "gate": "pr",
      "parent_branch": "main 또는 task/root-{ROOT}",
      "leaf_policy": {
        "risk_class": "micro|normal|major|irreversible|db|public-api|security|data-loss",
        "self_flow_verified": false,
        "hard_self_flow_verified": false
      },
      "required_checks": [["python3", "-m", "pytest", "plugins/task-github/tests/", "-q"]],
      "closeout_mode": "pr"
    }
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
헬퍼는 `root.execution_contract`가 있으면 root issue body에 parser-safe fenced block(`task-github-execution`)으로 materialize한다. unknown key는 버리고 stable key만 남긴다. 이 contract는 **실행 방법(how)** 이며 wiki task의 작업정의(why/what)를 대체하지 않는다. 위키에는 쓰지 않는다. `required_checks`는 shell string이 아니라 argv array만 local closeout에서 실행된다.

헬퍼는 서브이슈 부모 연결을 **GraphQL `createIssue(parentIssueId)`** 로 통일한다. **리프** child마다 완료 기준, 검증 anchor, 영향 경로/파일 anchor, `affects_paths`가 필요하다. `affects_paths`가 겹치는 리프는 한쪽 `blocked_by`를 선언해야 dry-run을 통과한다([quality-gates.md](../../rules/quality-gates.md) G3/G4). dependency는 REST Issue dependency API를 쓰며 `X-GitHub-Api-Version: 2026-03-10`을 고정한다. orchestrate 대상 tree는 `--strict-deps`라 dependency API 실패 시 `dep_create_failed`로 중단한다. comment fallback은 수동 define에서만 허용된다([dependencies.md](../../rules/dependencies.md)).

#### 트리 깊이 / 토폴로지 결정 게이트
이슈트리 shape는 정리가 아니라 **브랜치 분기 전략**이다([workflow.md](../../rules/workflow.md) §8: *자식 PR base = 부모 브랜치*). 결정 시점에 적용한다:

| 조건 | 권장 구조 |
|---|---|
| 코드 산출 + 병렬 트랙 ≥2 + 트랙별 경로 분리 | **트랙 = 서브트리(epic)** · `topology=stacked` · 트랙별 통합 브랜치 |
| 단일 surface / 순차 / 문서 산출 | **평면(flat)** · `topology=flat` |

> **Vertical slice ≠ flat.** Vertical slice는 product goal이 하나라는 뜻이지, issue tree가 flat이어야 한다는 뜻이 아니다. 구현 ownership, affected paths, integration branch가 나뉘면 vertical slice라도 stacked topology를 우선 검토한다.

- **서브트리(중간 노드/epic)는 child에 `parent` 키**로 만든다(값 = 부모 child의 `key`, 생략·null = 루트 직속). 헬퍼가 위상정렬로 root→epic→leaf를 한 번에 생성하고, `blocked_by`는 레벨을 넘어 동작한다. epic은 **브랜치 컨테이너**라 `affects_paths`·완료기준 게이트가 면제되고, 리프는 그대로 풀 게이트.
- **container/epic 승격 기준** — 아래 중 해당하면 승격을 검토한다: 해당 묶음만의 integration branch가 의미 있다 / leaf들이 같은 domain·path를 공유한다 / 다른 domain leaf가 이 묶음의 완료를 기다린다 / 병렬 subagent·worker에게 맡기기 좋은 단위다 / leaf 2개 이상이 같은 완료 목표를 향한다.
- **container/epic 비승격 기준** — leaf가 1개뿐이다 / 단순 label·category일 뿐 branch boundary가 없다 / 완료 기준이 leaf 완료의 단순 합 외에 없다. 이 경우 epic으로 감싸지 않는다.
- **결정 시점 안내(사령관 확인안에 포함)**: "리프 PR base = 부모 브랜치. 트랙별 독립 브랜치를 원하면 트랙을 `parent`로 묶어 epic으로 둔다."
- `topology=stacked`인데 epic이 0개(전 리프가 루트 직속)면 dry-run이 `stacked_without_epics` **경고**를 낸다(트랙 격리 없음 — 의도면 `topology=flat`).
- **`topology=flat` under-structuring 경고**: 아래 5개 신호 중 **2개 이상**이면 dry-run이 `flat_maybe_understructured` 경고(+`suggested_epics` 후보 클러스터)를 낸다.
  - leaf 6개 이상
  - `affects_paths`가 3개 이상 경로 클러스터로 갈라짐
  - title에 `backend`/`mobile`/`auth`/`wallet`/`ops`/`infra`/`api`/`ui` 같은 domain 키워드가 2개 이상 반복(같은 키워드가 leaf 2개 이상에서 등장하는 키워드가 2개 이상)
  - `blocked_by`가 클러스터 경계를 넘는 것이 2개 이상
  - root body에 "vertical slice"/"E2E"/"onboarding" 언급 + 클러스터 2개 이상
  - 경고가 뜨면 **flat 하나만 제시하지 말고 flat/stacked 최소 2안**(장단점 + 권고)을 사령관 확인안에 포함한다. `suggested_epics`(클러스터 경로 키)를 참고해 의미 있는 epic 이름(예: Auth/Account, Wallet/Store, Receive/QR, E2E/Ops)으로 번역해 제시한다.
- **확인 질문(topology가 불명확할 때만)**: "이 작업은 트랙별 parent branch를 둘까요?" / "{도메인들}을 container issue로 묶는 구조로 생성할까요, 단순 flat backlog로 유지할까요?" — 사령관이 이미 명확히 말했으면 묻지 않고 그 기준으로 생성한다.

#### `blocked_by`는 기본적으로 sibling-only
container는 카테고리가 아니라 **독립 실행 가능한 work package**다. container가 unblock되면 내부 리프는 외부 dependency 없이 진행 가능해야 한다. 그래서 `blocked_by`는 **같은 parent를 가진 sibling끼리만** 건다(root 직속 container ↔ root 직속 container, 같은 container 내부 리프 ↔ 리프). 헬퍼가 `parent`가 다른 두 노드 사이 `blocked_by`를 감지하면 **`cross_parent_dependency_detected`로 거부**하고, override가 필요하면 해당 child에 `cross_parent_dependency_reason`(non-empty string)을 명시해야 통과한다.

공유 약속(API contract 등)이 필요해서 다른 container의 리프에 의존하고 싶어지면, `blocked_by`를 걸지 말고 **contract container를 sibling으로 승격**한다:

```jsonc
// 나쁜 구조 — leaf가 다른 container 내부 leaf에 직접 의존 (cross_parent_dependency_detected)
"children": [
  {"key": "BE", "title": "[BE] 백엔드", "body": "..."},
  {"key": "FE", "title": "[FE] 모바일", "body": "..."},
  {"key": "BE-PAY", "parent": "BE", "title": "...", "body": "완료 기준:...\n검증:...\n영향 경로: apps/api/pay/**", "affects_paths": ["apps/api/pay/**"]},
  {"key": "FE-PAY", "parent": "FE", "title": "...", "body": "완료 기준:...\n검증:...\n영향 경로: apps/mobile/pay/**", "affects_paths": ["apps/mobile/pay/**"], "blocked_by": ["BE-PAY"]}
]

// 좋은 구조 — Contract container를 먼저 두고, 후속 container가 그것에 blocked_by
"children": [
  {"key": "CONTRACT", "title": "[Contract] API 계약", "body": "완료 기준:...\n검증:...\n영향 경로: docs/api-contract.md", "affects_paths": ["docs/api-contract.md"]},
  {"key": "BE", "title": "[BE] 백엔드", "body": "...", "blocked_by": ["CONTRACT"]},
  {"key": "FE", "title": "[FE] 모바일", "body": "...", "blocked_by": ["CONTRACT"]},
  {"key": "BE-PAY", "parent": "BE", "title": "...", "body": "완료 기준:...\n검증:...\n영향 경로: apps/api/pay/**", "affects_paths": ["apps/api/pay/**"]},
  {"key": "FE-PAY", "parent": "FE", "title": "...", "body": "완료 기준:...\n검증:...\n영향 경로: apps/mobile/pay/**", "affects_paths": ["apps/mobile/pay/**"]}
]
```
`CONTRACT`가 leaf 1개뿐이어도, sibling container를 unblock하는 execution gate라면 container로 둘 수 있다. 다른 parent의 node가 필요해 보이는 순간 dependency를 추가하지 말고, sibling container 승격 / container boundary 재설계 / leaf 이동 / body checklist화 중 하나로 tree를 재검토한다.

#### Container Independence Check (등록 전 확인안에 포함)
```markdown
## Container Independence Check
- 각 container는 단순 카테고리가 아니라 독립 실행 가능한 work package인가?
- container가 unblock되면 내부 leaf들이 외부 dependency 없이 진행 가능한가?
- 다른 parent의 node에 `blocked_by`를 걸고 있지는 않은가?
- cross-parent dependency가 필요해 보이는 경우, contract/spec container로 승격할 수 있는가?
- leaf 크기는 PR/worktree 단위인가, 아니면 너무 작은 checklist 수준인가?
```

**사령관 확인안 필수 섹션** — 이슈 생성 전 확인안에 아래를 포함한다(모드 A 4단계, 모드 C 2단계 공통):

```markdown
## Topology Decision
- 선택: flat | stacked
- 이유:
- 병렬 트랙 수:
- 경로/소유권 분리:
- cross-track dependency:
- parent branch / integration boundary 필요 여부:
```
`flat`을 선택했다면 사유를 구체적으로 밝힌다(단일 surface인가? 대부분 순차 작업인가? 중간 integration branch가 의미 없는가?). 위 5-신호 경고가 떴는데 flat을 그대로 확정하려면 그 사유를 확인안에 남긴다.

**Topology Rationale 기록** — 루트 이슈 body에 (Execution Contract 근처) 채택한 topology의 근거를 짧게 남긴다. 나중에 orchestrate/run/merge가 왜 이 구조인지 복원할 수 있게 한다:

```markdown
## Topology Rationale
이 tree는 {product 성격}이지만 {도메인들}의 ownership과 dependency가 분리되어 stacked topology로 정의한다.
리프 PR base는 각 container branch를 기준으로 한다.
```

6. **(위키 가용 시) 이슈 ↔ 작업정의 노드 연결** — task 노드는 3에서 이미 확보됨. 이제 이슈 번호를 task 노드에 **역링크**하고, 루트 이슈 본문에 task 노드를 기록한다. merge/done이 이 본문의 `[[TASK-...]]`를 읽어 완료 전이하므로 실제 ID를 박아야 한다([wiki-bridge.md](../../rules/wiki-bridge.md) §4):
```bash
# (a) task 노드에 루트 이슈 역링크 (capture가 --tasks 없이 만들었으므로 여기서 연결)
wiki relate "$TASK" --add-tasks "$OWNER/$REPO#$ROOT"

# (b) 루트 이슈 본문의 ## Wiki Context를 실제 ID로 갱신
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
> 위키 미가용이면 (a)(b) 전체를 스킵 — 이슈만 만들고 역링크는 두지 않는다(정상). `{관련 DEC}`/`{상위 INT}`는 캡처에 쓴 것과 동일하게 채운다(없으면 보조 줄 생략).
7. **(위키 가용 시) rationale 원자적 커밋** — 3에서 만든 task 노드 + 이번 업무의 근거 `DEC`/`REJ`/`INT`를 **메인에 바로 커밋**한다. 워크트리 생성(=`start`) 전에 vault를 깨끗이 두어 이후 작업별 커밋을 자명하게 만든다. rationale는 메인에 남고 코드 PR은 `DEC` ID로 참조한다([wiki-bridge.md](../../rules/wiki-bridge.md) §8):
```bash
if [ -d "./wiki" ]; then
  git add wiki/context wiki/task
  if ! git diff --cached --quiet -- wiki/context wiki/task; then
    git commit -m "docs(wiki): {업무} rationale + task 노드 (#$ROOT)"
    echo "rationale 메인 커밋 — 워크트리 생성 전 vault clean"
  fi
fi
```
> 이 커밋은 **시작 전 dirty-vault 점검으로 vault가 깨끗했음을 전제**한다. 점검이 무관한 잔여 레코드를 경고했는데 정리하지 않았다면 함께 커밋될 수 있으니 경고를 먼저 해소하라. 자동 커밋이 부담되면 이 단계를 생략하고 dirty-vault 경고만으로도 규약을 채택할 수 있다(최소 적용분).
8. **기어 라벨 안 붙임** — 기어 판단은 `start`에서.

### 모드 B — 분해 기준 요청
`open {N}`으로 현황 보여주고, 어떤 기준으로 분해할지 사령관에게 묻는다.

### 모드 C — 기준에 따라 분해
1. 기준(도메인/계층/단계 등)에 따라 서브이슈 목록 제시
   - 각 하위 이슈의 `blocked_by` 목록도 함께 제시한다.
   - dependency가 없으면 병렬 가능으로 표시한다.
   - 예: `#B blocked_by #A` = B는 A 완료 뒤 시작.
   - `blocked_by`는 sibling(같은 parent)끼리만 건다. 다른 container의 leaf가 필요해 보이면 contract container를 sibling으로 승격해 재구성한다(§트리 깊이/토폴로지의 sibling-only 규칙).
   - 하위 이슈마다 완료 기준, 검증 방법, 영향 경로/파일을 포함한다. path가 겹치는데 `blocked_by`가 없으면 [quality-gates.md](../../rules/quality-gates.md) G4에 따라 사령관 확인 또는 dependency 보완으로 승급한다.
   - brainstorm으로 나온 단위별 상세 설계(데이터 모델, DDL, API, 프롬프트 계약)는 **서브이슈 본문**에 둔다. 실행 중 새로 확정되는 장기 판단만 그때 `decision`/`observation`으로 캡처한다.
2. 사령관 확인 — 리프가 2개 이상이면 [Topology Decision](#트리-깊이--토폴로지-결정-게이트) 섹션을 포함한다.
3. `/tmp/task-github-issue-tree.json` spec 작성
4. `create_issue_tree.py --dry-run --strict-deps --json`으로 계획 검증 후 실제 실행
5. **task 노드는 새로 만들지 않는다** — 루트의 task 노드를 자식들이 공유. (분해는 구조 변경이지 새 업무가 아님)

### 전 모드 — Knowledge Capture Audit
업무 정의 과정에서 새 결정·반려·관찰이 생기면 [knowledge-capture.md](../../rules/knowledge-capture.md)에 따라 처리한다.
- 자동 분해 기준, dependency 방향, rejected split 기준처럼 장기 운영 판단이면 `decision`/`rejected_decision` 후보로 제안한다.
- 분류 전 발견은 `observation`으로 자동 캡처할 수 있다.
- 후보가 없으면 `none`과 이유를 등록 전 확인안에 포함한다.

## 불변식
- **자동 분해 금지** — 기준 없이 분해하지 않는다. 기준은 사령관이 준다.
- **작업정의(위키 task)가 수행(이슈)보다 먼저** — 위키 가용 시 이슈 생성 전에 task 노드를 확보한다(있으면 링크, 없으면 capture; 다른 세션이 만들면 대기). 이슈 생성은 "진행" 확인으로 게이트하고, 연결은 `wiki relate --add-tasks`로 역링크한다.
- 하위 작업 선후관계는 GitHub Issue dependency가 정본이다. `parallel`/`sequential` 라벨은 만들지 않는다.
- **container는 카테고리가 아니라 실행 단위, `blocked_by`는 sibling-only** — 다른 parent의 node에 걸린 `blocked_by`는 `cross_parent_dependency_detected`로 거부한다. 공유 선행조건은 contract/spec container를 sibling으로 승격해 해소하고, override가 불가피하면 `cross_parent_dependency_reason`을 명시한다.
- **기어 라벨을 붙이지 않는다** — define은 구조 생성만(기어는 start의 책임).
- **task 노드는 업무(루트) 1:1** — 리프·서브이슈마다 만들지 않는다.
- **Execution Contract는 루트 이슈 body 전용** — `schema_version` + stable keys를 가진 fenced block으로 materialize하고, contract 부재 시 context bundle은 `topology/gate/parent_branch=null`, `default_source=profile+gear`로 보고한다.
- orchestrate 대상 tree는 dependency 생성 실패를 fallback comment로 숨기지 않고 `dep_create_failed`로 실패 처리한다.
- 단위 상세 설계는 서브이슈 본문 또는 해당 단위 실행 중 캡처되는 DEC/OBS에 둔다. 위키 리프 task 노드는 만들지 않는다. 이미 만들었다면 내용을 서브이슈로 이전한 뒤 task 노드를 `retire --type deprecated`한다.
- **granularity 정지 규칙**: 리프 = **PR(또는 워크트리) 단위**. 그보다 작은 sub-PR 스텝은 이슈가 아니라 **리프 본문 체크리스트**에 둔다. 중간 노드(epic) 자격 = **브랜치 분기 의미가 있을 때만**(독립 통합 브랜치로 격리할 가치가 있는 병렬 트랙). 단일 리프뿐인 트랙은 epic으로 감싸지 않는다 — 과분해도 과소분해(트랙을 한 리프로 뭉갬)도 피한다.
- task 노드 캡처는 **제안 후 확인**. 위키 미가용이면 이슈만 만들고 task 노드는 스킵(정상).
- **rationale는 메인 직접 커밋** — task 노드 + 근거 `DEC`/`REJ`/`INT`를 define이 메인에 원자적 커밋하고, 시작 시 dirty-vault를 경고한다(차단 아님). 코드 PR은 `DEC` ID로 참조([wiki-bridge.md](../../rules/wiki-bridge.md) §8).
- 등록 전 반드시 사령관 확인.
