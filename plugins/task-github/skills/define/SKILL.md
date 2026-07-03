---
name: define
description: 업무를 GitHub Issue(루트 + 트리)로 등록하고, 위키가 있으면 결정·취지를 잇는 task 노드를 1:1로 만들어 연결한다. 자동 분해 금지 — 기준 없이 분해하지 않는다. "define", "이슈 만들어줘", "서브이슈 만들어줘", "define 10 도메인별로" 등의 요청에 실행하라.
---

# define — 업무 정의 (작업정의 task 노드 → 루트 이슈)

작업을 Issue(단일 또는 트리)로 구조화하고, 필요하면 하위 작업 간 GitHub Issue dependency를 정의한다. **위키가 있으면 업무 단위로 task 노드를 1:1 연결**한다. **등록 전 반드시 사령관 확인.**

> **업무 1개 = 위키 task 노드 1개 + 루트 이슈 1개.** task 노드는 업무(루트) 단위이며 **리프마다 만들지 않는다.** ([wiki-bridge.md](../../rules/wiki-bridge.md) §4)
>
> **순서: 작업정의(위키 task)가 수행(이슈)보다 먼저.** 위키 가용 시 이슈 생성 **전에** 작업정의 task 노드를 확보(있으면 링크, 없으면 capture)하고, 이슈 생성은 사령관 "진행" 확인으로 게이트한다. 위키 미가용이면 세션 컨텍스트로 이슈만 만든다(정상). 조율은 task-github가 한다 — 위키는 task-github를 모른다([wiki-bridge.md](../../rules/wiki-bridge.md) §1).
>
> **분해는 payoff가 있을 때만.** 리프로 쪼개는 것은 **절단 payoff > 리프 고정비**(worker spawn + 세리머니, ~20분+)일 때만 한다. payoff가 없으면 **묶는다(기본)**. 크기 자체는 절단 사유가 아니고 하드캡도 없다 — 큰 유닛 하나가 여러 리프보다 나을 수 있다. 절단 사유는 아래 "절단 원리 / 토폴로지 결정 게이트" 4개 중 하나여야 한다.

## 입력 (3모드)

```
$ARGUMENTS:
  (없음)        # 모드 A: 대화 맥락을 업무로 등록
  {N}           # 모드 B: 해당 이슈 open 후 분해 기준 요청
  {N} {기준}    # 모드 C: 기준에 따라 서브이슈로 분해
  --review      # (모드 무관) co-design 확인 후·이슈생성 전 challenge review 게이트를 켠다(기본 off)
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

#### challenge review (기본 off, `--review`)
co-design(위 4의 토폴로지 제안 확인, [[DEC-2026-07-02-190102]])가 **정착된 분해 제안**을 확정한 **뒤**, GitHub 이슈트리를 만들기 **전** 지점이다. 여기서 fresh-context 적대적 서브에이전트가 **분해 제안 문서**(이슈가 아직 없다 — PR도 아니다)를 감사한다. define이 이미 가르치는 분해 규칙의 **강제(enforcement) 층**이며, merge-edge-gear 작업을 낳은 과분해·가짜/전이 blocker·검증/문서 리프화 병리를 자동 감사한다([[DEC-2026-07-03-012207]]).

- **(a) 기본 off.** `--review` 인자 또는 이번 실행의 명시적 사령관 지시가 있을 때만 켠다. 없으면 이 절 전체를 스킵하고 5로 간다.
- **(b) 도구 해소 — 지시 > 설정(`define.review-tool`) > 하네스.** 순수 헬퍼 `orchestrator_ops.resolve_review_tool(enabled, directive_tool, config_tool)`가 `{"mode": "off"|"tool"|"harness", "tool": ...}`를 준다. `mode=="tool"`이면 `compose_tool_command(tool, define.review-command, extra=제안)`으로 relay 커맨드를 만든다(세 번째 인자 `extra`에 분해 제안 ref를 넘긴다). 설정은 `.task-github.yml`의 `define.review-tool`/`define.review-command`이며 `scripts/task_config.py`로 읽는다(orchestrate의 review-tool 패턴과 동형; unknown define 키 경고, `define.review-command`는 `define.review-tool`을 요구).
- **(c) terminal=하네스 = 진짜 challenge.** 도구가 없으면(=harness) **fresh-context 적대적 challenge 서브에이전트**를 띄운다(refute 스탠스, default-reject). co-design 에이전트가 자기 제안을 다시 읽는 것이 **아니다**(그건 연극이다). 근거 기준: **4 절단규칙**(병렬 이득/위험 격리/정보 가치 경계/병렬 해금) + **blocker 직접의존만**(transitive·방어 금지) + **검증·문서·runbook 리프 금지**(완료조건 흡수) + **container=수요 있는 delivery lane** + **gear 정직성** + **위키 결정그래프**(제안 리프가 REJ/DEC로 회귀하는가 — `wiki recall`로 교차). 
- **(d) target = 분해 제안 문서**(git PR이 아니다 — 이슈 생성 전의 제안). 그래서 **내장(built-in) 하네스가 주 경로**다. 외부 도구는 **제안 artifact를 받을 수 있을 때만** 쓴다 — session-review는 PR/git 지향이라 doc-review 모드 없이는 define의 자연스러운 reviewer가 아니다(`define.review-tool`을 session-review로 가리키는 것을 과대선전하지 말 것; 내장이 주 경로).
- **(e) ONE 라운드.** co-design에 **이미 present인 사람**이 **blocking** 판정을 판결한다 — auto-loop 없음. severity bar: **blocking만 게이트**, advisory는 로그만.
- **(f) complexity nudge(off-default 유지).** 제안 트리의 leaf 수/깊이가 임계를 넘는 복잡 신호가 뜨면(plan 시점 task-count warn 재사용) `--review` 권장 **비차단 warn**을 낸다. 여전히 기본 off이며, nudge는 최고가치 케이스(크고 복잡한 트리)를 조용히 스킵하지 않게만 한다.
- **(g) 코드 레벨 강제 — `define.review-required`.** (a)~(f)는 실행 에이전트에게 challenge review를 하라고 지시하는 **프롬프트**일 뿐이라, 에이전트가 그 step을 그냥 건너뛰어도 감지할 코드가 없었다(자체 dogfood 리뷰에서 발견한 gap). `.task-github.yml`의 `define.review-required: true`는 이걸 **agent-compliance 문제에서 코드 precondition으로** 바꾼다: `create_issue_tree.py`가 이 설정을 직접 읽어(agent가 무엇을 넘기든 무관), spec에 `challenge_review: {"verdict": "approved", "findings": [...]}`가 없거나 `verdict != "approved"`이면 `challenge_review_missing`/`challenge_review_blocked`로 **이슈 생성 자체를 거부**한다(dry-run 포함). `review-required=false`(기본)면 이 검사는 스킵되고 기존 동작과 동일하다. `.task-github.yml`이 invalid이거나 `define.review-required`가 boolean이 아니면 `config_invalid`로 fail-closed한다. `--review`/(a)~(f)로 challenge를 돌렸다면, 그 판정을 spec의 `challenge_review`에 실어야 실제로 통과한다.

`resolve_review_tool` 호출 — 플러그인의 다른 곳과 같은 sys.path shim 패턴:
```bash
python3 - <<'PY'
import sys
sys.path.insert(0, "plugins/task-github/skills/orchestrate/scripts")
import orchestrator_ops as ops
# enabled = --review 또는 사령관 지시. directive/config_tool = 지시>설정 순.
r = ops.resolve_review_tool(enabled=True, directive_tool=None, config_tool=None)  # → {"mode": "harness", "tool": None}
if r["mode"] == "tool":
    print(ops.compose_tool_command(r["tool"], None, extra="분해 제안"))  # tool relay 커맨드
else:
    print(r["mode"])  # "harness" = 내장 challenge 서브에이전트, "off" = 스킵
PY
```

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
  "challenge_review": {
    "verdict": "approved",
    "findings": []
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

`challenge_review`는 `define.review-required=true`일 때만 검사된다(§challenge review (g)). `false`(기본)면 있어도 없어도 무시된다.

헬퍼는 서브이슈 부모 연결을 **GraphQL `createIssue(parentIssueId)`** 로 통일한다. **리프** child마다 완료 기준, 검증 anchor, 영향 경로/파일 anchor, `affects_paths`가 필요하다. `affects_paths`가 겹치는 리프는 한쪽 `blocked_by`를 선언해야 dry-run을 통과한다([quality-gates.md](../../rules/quality-gates.md) G3/G4). dependency는 REST Issue dependency API를 쓰며 `X-GitHub-Api-Version: 2026-03-10`을 고정한다. orchestrate 대상 tree는 `--strict-deps`라 dependency API 실패 시 `dep_create_failed`로 중단한다. comment fallback은 수동 define에서만 허용된다([dependencies.md](../../rules/dependencies.md)).

#### 절단 원리 / 토폴로지 결정 게이트
이슈트리 shape는 정리가 아니라 **브랜치 분기 전략**이다([workflow.md](../../rules/workflow.md) §8: *자식 PR base = 부모 브랜치*). 결정 시점에 적용한다.

**절단 원리 — 기본은 묶기.** 리프 1개는 자기 worktree(`.worktrees/issue-N`) + 자기 브랜치 + 세리머니(spawn·plan·verify·merge edge)를 지불한다. 대략 **~20분+의 고정비**다. 리프로 쪼개는 것은 **절단 payoff가 이 고정비를 넘을 때만** 정당하다. 넘지 않으면 한 유닛으로 **묶는다**. **크기는 절단 사유가 아니다** — 하드캡도 없다. 큰 유닛 하나가 여러 리프보다 저렴하고 명료할 수 있다.

**절단 사유는 아래 4개뿐.** 하나도 해당하지 않으면 자르지 않는다.

1. **병렬 이득** — 서로 독립적인 조각이라 동시에 굴리면 벽시계 시간을 번다. 단, **각 조각이 normal 이상**일 때만 자른다. micro짜리는 병렬로 벌어봐야 고정비에 못 미치므로 **부모에 흡수**하거나 여러 개를 **sweep 리프**(한 리프에서 연달아 처리) 하나로 묶는다.
2. **위험 격리** — 비가역·고위험 조각은 **크기와 무관하게** 격리해 별도 리뷰/롤백 단위로 둔다. 작다고 흡수하지 않는다.
3. **정보 가치 경계**(직렬 절단용) — "**A의 검증 결과가 B의 계획을 바꾸나?**" 또는 "**B만 revert 하는 게 현실적인가?**" 둘 중 하나라도 yes면 A│B로 자른다. **개념이 다르다는 것만으로는 자르지 않는다** — 정보가 흐르거나 롤백이 갈릴 때만.
4. **병렬 해금**(선행 spec 리프) — lane 간 계약을 **선행 spec 리프**로 뽑아 병렬 lane들을 동시에 풀어준다. 산출물은 **바인딩 가능한 artifact**(타입/stub 등 실제로 붙일 수 있는 것)여야 하고, 이 리프는 **자기 크기와 무관하게** 존재 정당성을 갖는다. **lane 내부**에서만 쓰는 계약은 리프로 뽑지 말고 **이슈 본문**에 둔다.

| 조건 | 권장 구조 |
|---|---|
| 절단 사유 ①(병렬 이득) + 트랙별 경로 분리 | **트랙 = 서브트리(container)** · `topology=stacked` · 트랙별 통합 브랜치 |
| 절단 사유 없음 / 단일 surface / 순차 흐름 | **평면(flat)** · `topology=flat` (또는 한 유닛으로 묶기) |

> **Vertical slice ≠ flat.** Vertical slice는 product goal이 하나라는 뜻이지, issue tree가 flat이어야 한다는 뜻이 아니다. 구현 ownership, affected paths, integration branch가 나뉘면(=절단 사유 ①) vertical slice라도 stacked topology를 우선 검토한다.

- **검증·문서·runbook은 리프로 두지 않는다** — 별도 조각처럼 보여도 절단 payoff가 없다. 해당 유닛의 **완료조건으로 흡수**한다(리프 본문의 "검증:" anchor, done/verify가 소비).
- **container(중간 노드/epic)는 child에 `parent` 키**로 만든다(값 = 부모 child의 `key`, 생략·null = 루트 직속). 헬퍼가 위상정렬로 root→container→leaf를 한 번에 생성하고, `blocked_by`는 레벨을 넘어 동작한다. container는 **순수 브랜치 ref**(worktree·checkout 없음, FF로만 전진)라 `affects_paths`·완료기준 게이트가 면제되고, 리프는 자기 worktree를 갖고 그대로 풀 게이트.
- **container = 수요가 만드는 독립 delivery lane.** 카테고리·라벨이 아니다. 승격은 아래 수요가 있을 때만: 병렬 lane 격리(절단 사유 ①)가 필요하다 / 직렬 staging·통합 검증 지점이 의미 있다 / 다른 lane이 이 lane의 완료를 기다린다. **리프 1개만 남는 container는 접는다**(delivery lane이 아니라 이름표). **깊이 제약은 없다 — 깊이는 결과이지 목표가 아니다**(수요가 겹치면 자연히 깊어질 뿐).
- **결정 시점 안내(사령관 확인안에 포함)**: "리프 PR base = 부모 브랜치. 병렬 lane을 격리하려면 트랙을 `parent`로 묶어 container로 둔다."
- `topology=stacked`인데 epic이 0개(전 리프가 루트 직속)면 dry-run이 `stacked_without_epics` **경고**를 낸다(트랙 격리 없음 — 의도면 `topology=flat`).
- **`topology=flat` under-structuring 경고**: 아래 5개 신호 중 **2개 이상**이면 dry-run이 `flat_maybe_understructured` 경고(+`suggested_epics` 후보 클러스터)를 낸다.
  - leaf 6개 이상
  - `affects_paths`가 3개 이상 경로 클러스터로 갈라짐
  - title에 `backend`/`mobile`/`auth`/`wallet`/`ops`/`infra`/`api`/`ui` 같은 domain 키워드가 2개 이상 반복(같은 키워드가 leaf 2개 이상에서 등장하는 키워드가 2개 이상)
  - `blocked_by`가 클러스터 경계를 넘는 것이 2개 이상
  - root body에 "vertical slice"/"E2E"/"onboarding" 언급 + 클러스터 2개 이상
  - 경고가 뜨면 **flat 하나만 제시하지 말고 flat/stacked 최소 2안**(장단점 + 권고)을 사령관 확인안에 포함한다. `suggested_epics`(클러스터 경로 키)를 참고해 의미 있는 epic 이름(예: Auth/Account, Wallet/Store, Receive/QR, E2E/Ops)으로 번역해 제시한다.
- **확인 질문(topology가 불명확할 때만)**: "이 작업은 트랙별 parent branch를 둘까요?" / "{도메인들}을 container issue로 묶는 구조로 생성할까요, 단순 flat backlog로 유지할까요?" — 사령관이 이미 명확히 말했으면 묻지 않고 그 기준으로 생성한다.

#### `blocked_by`는 직접 의존만, 그리고 기본적으로 sibling-only
`blocked_by`에는 **직접 선행조건만** 건다. A→B→C면 C는 **B만** 걸고 A는 걸지 않는다 — transitive edge는 헬퍼가 이미 함의하므로 중복이고, "혹시 몰라서" 거는 **방어적 선언은 금지**다(ready 판정과 병렬 스케줄을 좁힌다).

container는 카테고리가 아니라 **독립 실행 가능한 delivery lane**이다. container가 unblock되면 내부 리프는 외부 dependency 없이 진행 가능해야 한다. 그래서 `blocked_by`는 **같은 parent를 가진 sibling끼리만** 건다(root 직속 container ↔ root 직속 container, 같은 container 내부 리프 ↔ 리프). 헬퍼가 `parent`가 다른 두 노드 사이 `blocked_by`를 감지하면 **`cross_parent_dependency_detected`로 거부**하고, override가 필요하면 해당 child에 `cross_parent_dependency_reason`(non-empty string)을 명시해야 통과한다.

공유 약속(lane 간 계약)이 필요해서 다른 container의 리프에 의존하고 싶어지면(절단 사유 ④ 병렬 해금), `blocked_by`를 걸지 말고 **선행 spec/contract 리프를 sibling으로 승격**한다. 이 리프의 산출물은 **바인딩 가능한 artifact**(타입/stub 등)여야 하고, 그래야 뒤따르는 lane들이 실제로 병렬로 풀린다. 반대로 **lane 내부에서만 쓰는 계약은 리프로 뽑지 말고 그 lane 리프의 이슈 본문**에 둔다:

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
여기서 `CONTRACT`는 자식 없는 **선행 spec 리프**(sibling leaf)이지 리프 1개짜리 container가 아니다 — 병렬 해금(절단 사유 ④)이라는 존재 이유가 있어 **자기 크기와 무관하게** 정당하다("리프 1개 남는 container는 접는다"와 충돌하지 않는다: container를 씌우지 않았다). 다른 parent의 node가 필요해 보이는 순간 dependency를 추가하지 말고, 선행 spec 리프 승격(바인딩 가능 artifact) / container boundary 재설계 / leaf 이동 / body checklist화 중 하나로 tree를 재검토한다.

#### Container Independence Check (등록 전 확인안에 포함)
```markdown
## Container Independence Check
- 각 container는 단순 카테고리가 아니라 독립 실행 가능한 delivery lane인가? (리프 1개만 남으면 접기)
- container가 unblock되면 내부 leaf들이 외부 dependency 없이 진행 가능한가?
- 다른 parent의 node에 `blocked_by`를 걸고 있지는 않은가? `blocked_by`가 직접 선행조건만인가(transitive·방어적 선언 없음)?
- cross-parent dependency가 필요해 보이는 경우, 선행 spec/contract 리프(바인딩 가능 artifact)로 승격할 수 있는가?
- 각 리프 절단이 4개 사유(병렬 이득/위험 격리/정보 가치 경계/병렬 해금) 중 하나로 정당한가? 사유 없이 크기만으로 쪼갠 리프는 부모에 흡수했는가? 검증·문서·runbook을 리프로 두지 않고 완료조건으로 흡수했는가?
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

> **태스크 과다는 STOP이 아니라 warn.** plan/define 시점에 리프·컨테이너 수가 많아 보여도 define은 **차단하지 않는다** — 위 경고(`flat_maybe_understructured`/`stacked_without_epics`)와 마찬가지로 확인안에 신호를 남기고 사령관 확인으로 진행한다. 절단 사유가 없는 리프를 묶으면 자연히 줄어들 뿐, 개수 상한으로 막지 않는다.

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
8. **기어 라벨 안 붙임** — 리프 기어 판정은 `start`가 리프에 대해 한다. define은 **컨테이너에도 gear 라벨을 강제하지 않는다**: 컨테이너의 기어는 라벨이 아니라 merge edge에서 `orchestrate`가 자식 기어를 누적(`container_gear_promotion`)해 결정한다(자식 최댓값 기준 + micro×3→normal, normal×2→major 승격, 컨테이너 자신의 라벨은 무시). 즉 작은 작업이 쌓이면 트렁크에 닿기 전 반드시 리뷰 게이트(major)를 한 번 통과한다([workflow.md](../../rules/workflow.md), DEC-2026-07-02-224910).

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
- **절단은 payoff가 있을 때만** — 리프 절단은 절단 payoff > 리프 고정비(worker spawn+세리머니, ~20분+)일 때만. 크기는 절단 사유가 아니고 하드캡도 없다. 사유는 4개뿐: ①병렬 이득(각 normal 이상; micro는 흡수/sweep) ②위험 격리(크기 무관) ③정보 가치 경계("A 검증이 B 계획을 바꾸나?"/"B만 revert가 현실적인가?" yes면 절단) ④병렬 해금(선행 spec 리프, 산출물=바인딩 가능 artifact, 크기 무관). 사유 없으면 묶는다. 검증·문서·runbook은 리프가 아니라 완료조건으로 흡수한다.
- **container는 카테고리가 아니라 독립 delivery lane, `blocked_by`는 직접 의존·sibling-only** — container는 병렬 lane 격리 또는 직렬 staging/통합검증 지점이라는 수요가 만든다(리프 1개만 남으면 접는다; 깊이 제약 없음—깊이는 결과). `blocked_by`는 직접 선행조건만(transitive·방어적 선언 금지)이고, 다른 parent의 node에 걸리면 `cross_parent_dependency_detected`로 거부한다. 공유 선행조건은 선행 spec 리프를 sibling으로 승격해 해소하고, override가 불가피하면 `cross_parent_dependency_reason`을 명시한다.
- **기어 라벨을 붙이지 않는다** — define은 구조 생성만. 리프 기어는 `start`가 판정하고, 컨테이너 기어는 merge edge에서 `orchestrate`가 자식 누적(`container_gear_promotion`)으로 결정한다(define은 컨테이너에 gear 라벨을 강제하지 않는다).
- **plan 시점 태스크 과다는 STOP이 아니라 warn** — 리프·컨테이너 수가 많아 보여도 차단하지 않는다. 확인안에 신호를 남기고 사령관 확인으로 진행한다(개수 상한 없음).
- **challenge review는 co-design 뒤·이슈생성 전, off-default, terminal=하네스** — `--review`/사령관 지시로만 켠다. 도구 해소는 지시>설정(`define.review-tool`)>하네스이며, 도구가 없으면 STOP이 아니라 내장 fresh-context 적대적 challenge 서브에이전트로 퇴각한다. 대상은 분해 제안 문서(PR 아님), ONE 라운드, blocking만 게이트([[DEC-2026-07-03-012207]]).
- **`define.review-required=true`면 challenge review는 에이전트 순응이 아니라 코드 precondition이다** — `create_issue_tree.py`가 `.task-github.yml`을 직접 읽어, spec의 `challenge_review.verdict=="approved"`가 없으면 `challenge_review_missing`/`challenge_review_blocked`로 이슈 생성을 거부한다(에이전트가 §challenge review 단계를 건너뛰어도 감지된다). `false`(기본)면 검사 없음 — 순수 프롬프트 지시로 남는다.
- **task 노드는 업무(루트) 1:1** — 리프·서브이슈마다 만들지 않는다.
- **Execution Contract는 루트 이슈 body 전용** — `schema_version` + stable keys를 가진 fenced block으로 materialize하고, contract 부재 시 context bundle은 `topology/gate/parent_branch=null`, `default_source=profile+gear`로 보고한다.
- orchestrate 대상 tree는 dependency 생성 실패를 fallback comment로 숨기지 않고 `dep_create_failed`로 실패 처리한다.
- 단위 상세 설계는 서브이슈 본문 또는 해당 단위 실행 중 캡처되는 DEC/OBS에 둔다. 위키 리프 task 노드는 만들지 않는다. 이미 만들었다면 내용을 서브이슈로 이전한 뒤 task 노드를 `retire --type deprecated`한다.
- **granularity 정지 규칙**: 리프 = **절단 payoff가 고정비를 넘는 최소 단위**(자기 worktree + merge edge를 지불할 값어치). payoff 없는 sub-step은 이슈가 아니라 **리프 본문 체크리스트**에 둔다. container 자격 = **delivery lane 수요가 있을 때만**(병렬 lane 격리 또는 직렬 staging/통합검증 지점). 단일 리프뿐인 lane은 container로 감싸지 않는다 — 과분해도 과소분해(lane을 한 리프로 뭉갬)도 피한다.
- task 노드 캡처는 **제안 후 확인**. 위키 미가용이면 이슈만 만들고 task 노드는 스킵(정상).
- **rationale는 메인 직접 커밋** — task 노드 + 근거 `DEC`/`REJ`/`INT`를 define이 메인에 원자적 커밋하고, 시작 시 dirty-vault를 경고한다(차단 아님). 코드 PR은 `DEC` ID로 참조([wiki-bridge.md](../../rules/wiki-bridge.md) §8).
- 등록 전 반드시 사령관 확인.
