<!-- BEGIN agent-operating-policy (managed by wiki-markdown) -->
## Agent Operating Policy

- Profile: solo
- Scope: these auto-loaded entry files are the source for working-environment policy.
- Concurrency: Use git worktrees for concurrent tasks; do not let parallel agents edit the same working tree.
- Tracker: Use task-github for tracked work. The wiki work-definition (task node) is the work order/instruction, created FIRST; the GitHub root issue is the execution view, created and linked afterward. On a plan/prepare-work request, task-github:define detects the wiki, uses or waits for that task node (capturing it first if absent), and confirms before creating the linked issue. With only one plugin present, each does its own part standalone (wiki: the work-definition doc; task-github: an issue from session context).
- Knowledge capture: use wiki-markdown for product, system, and design knowledge; do not store working-environment operating policy in a consumer project's wiki vault.
- Design altitude: brainstorming defines decomposition and thin unit boundaries; unit-internal schema/API/DDL/prompt contracts belong in the unit issue body or in DEC/OBS captured during that unit's run. Do not create wiki task nodes for leaf issues.
- Capture authority: observations may be recorded when low-risk; decisions, rejected alternatives, trial-error records, and promotions need explicit user confirmation.
- Rationale commits: capture decisions, rejected alternatives, and other rationale records directly on main; code changes go via PR branches that reference the DEC id. task-github define commits its task node and rationale atomically, and define/start warn on a dirty wiki vault.
<!-- END agent-operating-policy (managed by wiki-markdown) -->
