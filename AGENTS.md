## 저장소 커밋 정책

- 프로토콜이 요구하는 고정 prefix는 보존하고, 나머지는 변경 의도와 결과가 드러나는 의미 있는 한 줄 요약으로 작성한다. 기본 언어는 한국어로 하되 코드 식별자와 표준 기술 용어는 원문을 유지한다.

<!-- BEGIN agent-operating-policy (managed by wiki-markdown) -->
## Agent Operating Policy

- Profile: solo
- Scope: these auto-loaded entry files are the source for working-environment policy.
- Concurrency: Use git worktrees for concurrent tasks; do not let parallel agents edit the same working tree.
- Tracker: Use task-github for tracked work. Create the wiki root task work order FIRST, then project and bind the GitHub root Issue. Do not create wiki task nodes for Issue leaves. `dispatch: manual` creates/uses the Issue Tree without local worker runs; `dispatch: worker` executes the same ready set through task-worker. Persist TASK/root-Issue aliases in the task-worker binding so resume and closeout never depend on session context.
- Execution: task-worker owns provider-neutral decomposition, dependency planning, ready-set parallelism, worktree isolation, verification evidence, and integration gates. task-github owns only GitHub projection/delivery; wiki-markdown owns only durable work-definition and knowledge state. Do not reduce independent verification or root integration gates to save runs; remove only duplicate physical execution with valid pinned evidence.
- Knowledge capture: use wiki-markdown for product, system, and design knowledge; do not store working-environment operating policy in a consumer project's wiki vault.
- Durable context lifecycle: for substantive work or conversation where prior intent, decisions, lessons, or current state could affect judgment, run one scoped wiki recall before deciding and reuse it until scope, evidence, or anchors change. Keep new durable knowledge as ephemeral candidates; at a semantic milestone or closeout, deduplicate and either record approved items, propose one grouped capture, or report `none` with a short reason.
- Wiki vs runtime evidence: the wiki is a durable context/decision layer, not a runtime-debug companion. For a concrete runtime bug (a customer id, an API path, a wrong on-screen value), inspect code/API/DB/render evidence first; consult the wiki on a real design ambiguity, policy conflict, or durable lesson. Do not re-recall settled context for a small single-file edit or when speed is asked. Treat snapshot/observation as non-authoritative versus the newest decision.
- Design altitude: brainstorming defines decomposition and thin unit boundaries; unit-internal schema/API/DDL/prompt contracts belong in the unit issue body or in DEC/OBS captured during that unit's run. Do not create wiki task nodes for leaf issues.
- Capture authority: all wiki writes, including observations and living SSOT/runbook updates, need explicit user confirmation unless local policy explicitly opts into a narrower auto-write class. A request to record a specific item counts as confirmation; rejected or deferred candidates are not proposed again without new evidence.
- Knowledge value: evaluate candidates by future reuse, revisit/reversal cost, and impact on current state — not task size, execution/review cost, or the calling plugin. Small work may produce durable knowledge; large work may produce none. Run refresh once at the end of a batch, not per node.
- Ceremony scales to blast radius, not design-unit count: decompose for thinking, bundle for shipping. Bundle same-gear same-theme changes that share one rollback unit into a single PR; isolate irreversible or high-blast-radius work and give it adversarial review. A change outside a tracked flow still gets an effective gear by the same blast-radius test. Never bundle to slip an unreviewed change under a sibling's review, and don't turn each design decision into its own ship-cycle. (Mechanism: the gear→PR/review table in the task protocol where present.)
- Rationale commits: capture decisions, rejected alternatives, and other rationale records directly on main; code changes go via PR branches that reference the DEC id. task-github define commits its task node and rationale atomically, and define/start warn on a dirty wiki vault.
<!-- END agent-operating-policy (managed by wiki-markdown) -->
