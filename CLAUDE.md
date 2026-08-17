# CLAUDE.md

이 워크스페이스의 Claude용 에이전트 진입점(agent-entry 표면). 작업환경 운영 정책은 아래 `agent-operating-policy` 관리 블록이 정본이다.

## 프로파일

```
프로파일: solo
```
1인 개발자 + AI 에이전트 환경. 추적 작업은 task-worker 로컬 실행(`.task-worker.yml`)으로 수행하고 `task-github`는 이 repo에서 off — 명시 요청 시에만 GitHub projection에 쓴다. (기어 **라벨**은 프로파일 무관하게 공통 `gear:micro|normal|major` — `gear:full`은 없다.)

## 저장소 커밋 정책

- 프로토콜이 요구하는 고정 prefix는 보존하고, 나머지는 변경 의도와 결과가 드러나는 의미 있는 한 줄 요약으로 작성한다. 기본 언어는 한국어로 하되 코드 식별자와 표준 기술 용어는 원문을 유지한다.

## 메커니즘/근거 포인터

- **작업관리 ↔ 위키 결합 규약**: 아래 `agent-operating-policy` 관리 블록 및 Codex용 `AGENTS.md`
- **위키 메커니즘**: `plugins/wiki-markdown/` + `wiki/ssot/plugin-definition/`
- **작업 프로토콜 메커니즘**: `plugins/task-github/` (`rules/`·`DESIGN.md`)
- **정책 변경 근거**: 이 repo의 `wiki/context/decision/`에 dogfood 기록

## 4계층 분리

| 계층 | 위치 |
|------|------|
| mechanism | `plugins/wiki-markdown/`, `plugins/task-github/` |
| policy statement | 이 파일의 관리 블록, `AGENTS.md` |
| policy rationale | `wiki/context/decision/` |
| knowledge | `wiki/*` |

상세는 [[wiki-four-layer-separation]] 참조.

<!-- BEGIN agent-operating-policy (managed by wiki-markdown) -->
## Agent Operating Policy

- Profile: solo
- Scope: these auto-loaded entry files are the source for working-environment policy.
- Concurrency: Use git worktrees for concurrent tasks; do not let parallel agents edit the same working tree.
- Tracker: task-github is OFF in this repo — do not create, project, or bind GitHub Issues for tracked work unless the user explicitly asks for GitHub delivery. Use task-worker for tracked work: create the wiki root task work order FIRST, then define and execute the DefinitionArtifact locally per `.task-worker.yml` (`dispatch: worker`, `delivery: local-ff`). Do not create wiki task nodes for artifact leaves. Persist TASK/artifact aliases in the task-worker binding so resume and closeout never depend on session context.
- Execution: task-worker owns provider-neutral decomposition, dependency planning, ready-set parallelism, worktree isolation, verification evidence, and integration gates. wiki-markdown owns only durable work-definition and knowledge state; task-github (off here) is invoked only on explicit user request for GitHub projection/delivery. Do not reduce independent verification or root integration gates to save runs; remove only duplicate physical execution with valid pinned evidence.
- Knowledge capture: use wiki-markdown for product, system, and design knowledge; do not store working-environment operating policy in a consumer project's wiki vault.
- Durable context lifecycle: for substantive work or conversation where prior intent, decisions, lessons, or current state could affect judgment, run one scoped wiki recall before deciding and reuse it until scope, evidence, or anchors change. Keep new durable knowledge as ephemeral candidates. Finish the original task and primary answer first. At a semantic milestone or closeout, use existing context for an internal candidate audit. Only when genuine durable candidates exist, append one natural, optional grouped capture question at the bottom of the same final answer; otherwise add no user-facing audit, status, or `none` text.
- Wiki vs runtime evidence: the wiki is a durable context/decision layer, not a runtime-debug companion. For a concrete runtime bug (a customer id, an API path, a wrong on-screen value), inspect code/API/DB/render evidence first; consult the wiki on a real design ambiguity, policy conflict, or durable lesson. Do not re-recall settled context for a small single-file edit or when speed is asked. Treat snapshot/observation as non-authoritative versus the newest decision.
- Design altitude: brainstorming defines decomposition and thin unit boundaries; unit-internal schema/API/DDL/prompt contracts belong in the unit issue body or in DEC/OBS captured during that unit's run. Do not create wiki task nodes for leaf issues.
- Capture authority: all wiki writes, including observations and living SSOT/runbook updates, need explicit user confirmation unless local policy explicitly opts into a narrower auto-write class. A request to record a specific item counts as confirmation; rejected or deferred candidates are not proposed again without new evidence.
- Verified_at hygiene: a commit that stamps `verified_at` without any other body change must name the comparison method in its message (e.g. `schema --json` full-field diff); this is what makes a genuine reverification distinguishable from a stale stamp in the diff alone.
- Knowledge value: evaluate candidates by future reuse, revisit/reversal cost, and impact on current state — not task size, execution/review cost, or the calling plugin. Small work may produce durable knowledge; large work may produce none. Run refresh once at the end of a batch, not per node.
- Ceremony scales to blast radius, not design-unit count: decompose for thinking, bundle for shipping. Bundle same-gear same-theme changes that share one rollback unit into a single PR; isolate irreversible or high-blast-radius work and give it adversarial review. A change outside a tracked flow still gets an effective gear by the same blast-radius test. Never bundle to slip an unreviewed change under a sibling's review, and don't turn each design decision into its own ship-cycle. (Mechanism: the gear→PR/review table in the task protocol where present.)
- Rationale commits: capture decisions, rejected alternatives, and other rationale records directly on main; code changes go via PR branches that reference the DEC id. Define flows commit their task node and rationale atomically where the tracker supports it, and define/start warn on a dirty wiki vault.
<!-- END agent-operating-policy (managed by wiki-markdown) -->

<!-- BEGIN context-core-policy (managed by context-core) -->
## Durable context workflow

- Substantive work나 결정 수렴 전에 이전 맥락이 판단을 바꿀 수 있으면 Current context를 scoped index-first로 한 번 recall한다.
- 설치된 semantic owner가 있으면 후보와 관련 Current artifact의 실제 본문·scope·rationale를 비교한다. hash나 fingerprint로 의미 동일성 또는 충돌을 판정하지 않는다.
- capture 후보의 title·summary·search_terms에는 대화에서 쓰인 표현과 필요한 동의어를 bounded하게 남겨 이후 index recall을 돕되, index metadata를 의미 판정으로 사용하지 않는다.
- 기존 결정과의 conflict 또는 rationale change가 보이면 결론 전에 관련 artifact와 차이를 알리고 유지·수정·supersede 중 무엇인지 확인한다.
- Primary 요청과 답변을 먼저 끝낸다. semantic milestone 또는 closeout당 durable candidate audit은 최대 한 번 수행하고, 재사용 가치가 있는 후보가 있을 때만 grouped capture를 제안한다.
- Current DEC는 authoritative, OBS는 non-authoritative evidence, SNAP은 resume staging으로 취급한다.
- 사용자의 명시 승인 전에는 context artifact나 index를 쓰지 않는다.
<!-- END context-core-policy (managed by context-core) -->
