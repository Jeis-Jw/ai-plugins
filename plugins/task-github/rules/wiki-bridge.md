# 위키 브릿지 규약 (mechanism)

> 이 룰은 task-github → `wiki-markdown` 연동의 **메커니즘**(감지·호출·반응)만 정의한다.
> **정책**(누가·언제·어떤 타입을 캡처/승격하는가)은 자동로드 agent-entry 파일(`CLAUDE.md` / `AGENTS.md`)의 operating policy 블록에 있다.
> 이 분리는 위키의 4계층 원칙(plugin은 agent-neutral, 작업환경 정책은 자동로드 표면, 소비 프로젝트 wiki는 지식 저장소)을 따른다. [DESIGN.md](../DESIGN.md) §2·§6 참조.

---

## 1. 감지 (availability)

프로젝트 로컬 vault 디렉토리 존재로 판정한다:
```bash
[ -d "./wiki" ] && echo "위키 가용" || echo "위키 미가용(스킵)"
```
- **가용**: 아래 호출 규약대로 위키를 연동한다.
- **미가용**: 모든 위키 호출을 **스킵(오류 아님)**. 지식은 Issue 코멘트 태그로만 남기고, 나중에 위키 구축 시 수동 이관 가능.

> **불변식**: 위키 미감지는 정상 경로다. 어떤 스킬도 위키 부재로 중단되지 않는다(그레이스풀 디그레이데이션).

---

## 2. 호출 (invocation)

위키는 `wiki-markdown` 플러그인의 **`wiki` 스킬**로 구동한다. 같은 세션에 두 플러그인이 있으면, task-github 스킬은 필요한 위키 작업을 **`wiki` 스킬에 위임**한다(자기 `${CLAUDE_SKILL_DIR}`로 CLI 경로를 해석하므로 task-github는 설치 위치에 결합되지 않는다).

위키 CLI는 결정적이다 — JSON 출력 + exit code로 분기한다(파싱 불필요):
- 성공: `{"ok": true, ...}` / exit 0
- 실패: `{"ok": false, "error_code": "...", "message": "..."}` / exit ≠ 0

호출하는 주요 명령(개념):
```bash
# 지식 주입 (읽기)
wiki recall "{키워드}" --stage 1 --limit 10 --json
wiki recall --backlinks-of {DEC-...} --json        # "이 결정이 낳은 작업/지식"
wiki recall --read {basename} --json

# 작업 브릿지 노드
wiki capture task --title "..." --summary "..." --tags ... \
  --decisions {DEC-...} --intents {INT-...} --tasks owner/repo#{N}
wiki complete {TASK-...}      # 활성 → wiki/task/done/  (루트 이슈 close 시)
wiki reopen   {TASK-...}      # done → 활성              (이슈 재오픈 시)

# 지식 승격 (모든 capture는 --title/--summary/--tags 필수 — 생략 시 exit 2)
wiki capture decision    --title "..." --summary "..." --tags ... --intents {INT-...} --tasks owner/repo#{루트}
wiki capture trial_error --title "..." --summary "..." --tags ... --decisions {DEC-...} --tasks owner/repo#{루트}
wiki capture observation --title "..." --summary "..." --tags ... --tasks owner/repo#{루트} --affects-paths "src/<area>/**"

# 드리프트 / 무결성
wiki refresh --check changed-path-stale --changed-path "{변경파일 csv}" --json
wiki refresh --strict --json
```
> 위 블록은 **개념 예시**다(`...` 자리표시자 포함). 실제 호출 시 `--title`/`--summary`/`--tags`는 항상 채운다 — 위키 `capture`는 이 셋이 없으면 exit 2다. `--tasks`는 업무 **루트 이슈** 번호([§4](#4-task-노드--업무이슈-11-다리)).

---

## 3. 위키 타입 모델 (반드시 준수)

`wiki-markdown`의 타입은 다음과 같다. **이전 wiki-obsidian의 decision/fact/lesson/pattern이 아니다.**

| 타입 | 용도 | `--tasks` 역링크 |
|------|------|:---:|
| `intent` | durable 원칙(hub) | ✗ (관계 금지) |
| `decision` | 결정 | ✅ |
| `rejected_decision` | 반려 대안 | ✗ (intents만) |
| `trial_error` | 시행착오(교훈 필수) | ✅ |
| `observation` | 분류 전 발견 | ✅ |
| `ssot` / `runbook` | 현재상태/절차(living) | ✗ (관계 금지) |
| **`task`** | **작업 브릿지 노드** | ✅ |

> **불변식(타입별 관계 제약)**: `--tasks`(외부 이슈 `owner/repo#N` 역링크)는 **decision / trial_error / observation / task** 에만 허용. `intent`/`rejected_decision`/`ssot`/`runbook`에 `--tasks`를 주면 exit 2(스키마 위반). 에픽↔intent는 단방향이며, 역추적은 그 intent를 가리키는 decision/task를 경유한다.

---

## 4. task 노드 — 업무↔이슈 1:1 다리

**업무 1개 = 위키 task 노드 1개 + GitHub 루트 이슈 1개.** task 노드는 업무 단위이며 **리프마다 만들지 않는다.**
단위별 상세 설계는 서브이슈 본문 또는 그 단위 실행 중 캡처되는 `decision`/`observation`에 둔다. brainstorm 산출물을 리프 task 노드로 옮기지 않는다.

```
   intent ◄── decision ◄── task 노드 ──relations.tasks──► GitHub 루트 이슈
  (취지)     (결정·근거)   (업무 요약)   ◄──"## Wiki Context"──  (업무 상세)
                              │
                          상태: 활성(wiki/task/) / 완료(wiki/task/done/)
```

- **task 노드 → 이슈**: `relations.tasks: [owner/repo#<루트이슈>]` (task는 record 성질이라 이 역링크를 **가질 수 있다** — 이것이 task 노드를 신설한 이유).
- **task 노드 → 결정/취지**: `--decisions` / `--intents` (이 업무가 어떤 결정·취지에서 나왔나).
- **이슈 → task 노드**: 루트 이슈 본문 `## Wiki Context`에 task 노드 basename을 **메인**, 결정/취지를 **보조**로.
- **리프/서브이슈 → 상세 설계**: 서브이슈 본문이 정본이다. 이미 리프 task 노드를 만들었다면 내용을 서브이슈로 이전하고 task 노드는 deprecated로 retire한다.
- **역방향 조회(결정→작업)**: `recall --backlinks-of {DEC}`로 "이 결정이 낳은 작업"을 조회(완료된 task도 기본 포함 — done은 유효한 terminal 상태).
- **task 노드 ID 조회(이슈→task)**: **루트 이슈 본문 `## Wiki Context`가 정본 경로다.** `recall --backlinks-of {owner/repo#N}`은 **쓰지 않는다** — 위키는 외부 이슈 ref(`owner/repo#N`)를 역링크 대상으로 찾지 못한다(`tasks`는 형식만 검증되는 외부 참조).

루트 이슈 `## Wiki Context` 포맷(정확한 규약은 자동로드 operating policy):
```markdown
## Wiki Context
**메인**: [[TASK-2026-…-payment-bff]] — 이 업무의 정의(요약·근거)
**보조**:
- [[DEC-2026-…-move-auth-to-bff]] — 근거가 된 결정
- [[INT-2026-…-signup-speed]] — 상위 취지
```

### 공통 조회 스니펫 (스킬이 재사용)

**(a) 작업 중인 `{N}`에서 업무 루트 이슈 번호 얻기** — `{N}`이 리프면 부모, 아니면 자신:
```bash
read OWNER REPO < <(gh repo view --json owner,name --jq '"\(.owner.login) \(.name)"')
PARENT=$(gh api graphql -f query='query($o:String!,$r:String!,$n:Int!){ repository(owner:$o,name:$r){ issue(number:$n){ parent{ number } } } }' \
  -F o="$OWNER" -F r="$REPO" -F n={N} --jq '.data.repository.issue.parent.number // empty')
ROOT=${PARENT:-{N}}
```

**(b) 루트 이슈에서 연결 task 노드 ID 얻기** — 본문 `## Wiki Context`의 `[[TASK-...]]` 파싱:
```bash
TASK=$(gh issue view "$ROOT" --json body --jq '.body' \
  | grep -oE 'TASK-[0-9]{4}-[0-9]{2}-[0-9]{2}-[0-9]{6}-[A-Za-z0-9-]+' | head -1)
```
캡처의 `--tasks`에는 `"$OWNER/$REPO#$ROOT"`를, `complete`/`reopen`에는 `"$TASK"`를 쓴다. 위키 미가용이거나 `## Wiki Context`가 없으면 `$TASK`는 빈 값 — 해당 위키 단계만 스킵(작업 막지 않음).

---

## 5. 상태 정본 — 하나만

위키 task 상태(활성/done)와 GitHub 이슈 상태가 같은 사실을 이중으로 들면 드리프트한다. 그래서:

| 모드 | 정본 | task-github의 동기화 |
|------|------|---------------------|
| 독립 (위키만) | 위키 | (이슈 없음 — 동기화 대상 없음) |
| 연동 (task-github) | **GitHub 루트 이슈** | 이슈 close 시 `complete`(→`done/`), 재오픈 시 `reopen`. 밖에서 닫힌 경우 reconcile |

- 위키가 추적하는 건 **이진(활성/done)** 뿐. 상세 phase(in-progress/in-review/changes-requested)는 위키가 복제하지 않고 이슈에 위임 → 복제 안 하니 드리프트 없음.
- **reconcile**: out-of-band(밖에서 닫힌 이슈)는 task-github가 `gh`로 읽어 위키 task 상태를 정렬한다. **위키 CLI는 `gh`를 모른다** — reconcile 주체는 task-github.

---

## 6. 호출 지점 요약 (스킬별)

| 스킬 | 위키 동작 |
|------|----------|
| `setup` | `./wiki/` 없고 위키 플러그인 있으면 `wiki init` 제안 |
| `open` | 루트 이슈 `## Wiki Context` → task 노드·결정 `recall --read` 브리핑 |
| `define` | 관련 결정 recall → `capture task`(루트 이슈와 1:1 연결) → `## Wiki Context` 기록 |
| `start` | 부모 루트의 task 노드 + 결정/취지를 세션 컨텍스트로 주입 |
| `plan` | task의 `decisions`/`intents` 읽기 + 키워드 recall로 trial_error/observation 주입 |
| `run` | `[관찰]` 발견 시 `capture observation`(자동) |
| `verify` | 태그→타입 캡처(제안), observation 승격 검토, `refresh --strict` 게이트(리포트) |
| `done` | PR diff → `refresh --check changed-path-stale`; major면 ADR → `capture decision` |
| `review` | pr-verifier에 연결 task의 `decisions` 전달(반려 대안 회귀 점검) |
| `merge` | 루트 이슈 close 시 task `complete`; 영향 record `verified_at` 갱신 안내 |

---

## 7. 캡처 강도 (mechanism 기본)

| 대상 | 방식 | 근거 |
|------|------|------|
| `observation` | **자동** | 저위험·분류 전 |
| `task` 생성, `decision`/`intent`/`rejected`/`trial_error`, 승격 | **제안 후 확인** | 그래프 1급 노드, 되돌리기 비용 |

> 구체적 임계·권한은 mechanism이 아니라 **policy**의 몫이다. 정책은 `CLAUDE.md` / `AGENTS.md` 같은 자동로드 표면에 둔다. 위키는 자동 승격을 반려했다(`REJ-…-promotion-auto-judgment`).

---

*위키 타입/CLI가 바뀌면 이 파일과 [DESIGN.md](../DESIGN.md) §6·§13을 동기화하라. 타입·관계의 정본은 위키 `wiki-data-model`이다.*
