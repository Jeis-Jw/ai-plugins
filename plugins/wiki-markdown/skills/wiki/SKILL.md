---
name: wiki
description: Manage an AI-native project wiki — capture intents, decisions, rejected alternatives, trial-error lessons, observations, current state (SSOT) and operating runbooks as a decision graph; query it; refresh integrity. Use whenever the user wants to record what was decided / why, retrieve related context before a decision, file an observation for later classification, retire or supersede a record, or run a wiki integrity check. Filesystem-primary, deterministic CLI — minimal tokens to stay consistent.
---

# Wiki

This skill drives a single Python CLI, `wiki_cli.py`, against a local vault (default `wiki/`). All invocations follow the pattern below; exit codes and JSON output are deterministic so the agent can react to results without re-parsing prose.

```bash
python3 <skill-dir>/scripts/wiki_cli.py <subcommand> [args]
```

`<skill-dir>` is the installed location of this skill — Claude Code exposes it as `${CLAUDE_SKILL_DIR}`; in other harnesses, substitute the absolute path.

## When to use

Invoke this skill whenever the user asks to:

- **Record durable knowledge**: "log this decision", "save the intent", "note why we rejected X", "record this trap", "we found something but don't know how to classify it yet"
- **Document state or procedure**: "write up the current auth architecture", "document the deploy procedure"
- **Retrieve context before acting**: "what did we decide about X?", "show related intents", "anything we tried before?", "who superseded this?", "batch-read these records"
- **Save or resume unresolved conversation context**: "save this discussion", "load the previous context", "search discussion snapshots"
- **Run integrity / drift checks**: "check the wiki", "find stale facts", "any broken links?", "regenerate indexes", "what does this code change affect?"
- **Initialize a vault**: "set up the wiki", "create the knowledge base"
- **Retire or supersede**: "mark this decision deprecated", "supersede X with Y"

Per the mechanism design principle in `rules/knowledge-protocol.md`, always **`recall` before deciding** and **`capture` after deciding**.

## Quick start

```bash
# 0. Initialize the vault (idempotent; includes context/observation).
python3 "${CLAUDE_SKILL_DIR}/scripts/wiki_cli.py" init

# 1. Record an intent (a hub; backlink target).
python3 "${CLAUDE_SKILL_DIR}/scripts/wiki_cli.py" capture intent \
  --title "Signup conversion speed" \
  --summary "Minimize friction in the signup funnel to lift conversion." \
  --tags growth,conversion

# 2. Record a decision (winning intent + work item link).
#    --intents accepts slug fragments; capture resolves to the full basename.
python3 "${CLAUDE_SKILL_DIR}/scripts/wiki_cli.py" capture decision \
  --title "Move auth to a BFF" \
  --summary "Session tokens are owned by the BFF." \
  --tags auth,architecture \
  --intents signup-conversion-speed \
  --tasks owner/repo#18

# 3. Record an observation (pre-classification; may promote later to TRI/DEC).
python3 "${CLAUDE_SKILL_DIR}/scripts/wiki_cli.py" capture observation \
  --title "Webhook timeout risk" \
  --summary "External webhooks may exceed our 30s budget; currently unbounded." \
  --tags webhook,reliability \
  --ssot webhook-architecture \
  --affects-paths "src/webhook/**" \
  --tasks owner/repo#42

# 3b. Record a task (bridge node: a unit of work linked to decisions + an issue).
python3 "${CLAUDE_SKILL_DIR}/scripts/wiki_cli.py" capture task \
  --title "Move payment session to the BFF" \
  --summary "Payment-side of the BFF migration; driven by the move-to-BFF decision." \
  --tags payment,architecture \
  --decisions move-auth-to-a-bff \
  --intents signup-conversion-speed \
  --tasks owner/repo#42
# Finish it (active → task/done/) when the linked issue closes; reopen to undo.
python3 "${CLAUDE_SKILL_DIR}/scripts/wiki_cli.py" complete TASK-2026-04-17-143052-move-payment-session-to-the-bff
python3 "${CLAUDE_SKILL_DIR}/scripts/wiki_cli.py" reopen   TASK-2026-04-17-143052-move-payment-session-to-the-bff

# Add a relation to an existing node without hand-editing frontmatter.
python3 "${CLAUDE_SKILL_DIR}/scripts/wiki_cli.py" relate DEC-2026-04-17-143052-move-auth-to-a-bff --add-tasks owner/repo#18
python3 "${CLAUDE_SKILL_DIR}/scripts/wiki_cli.py" relate TASK-2026-04-17-143052-move-payment-session-to-the-bff --add-decisions move-auth-to-a-bff

# 4. Recall (3-stage + batch read + backlinks).
python3 "${CLAUDE_SKILL_DIR}/scripts/wiki_cli.py" recall "auth" --json
python3 "${CLAUDE_SKILL_DIR}/scripts/wiki_cli.py" recall "auth" --stage 2 --section 취지
python3 "${CLAUDE_SKILL_DIR}/scripts/wiki_cli.py" recall --backlinks-of INT-2026-04-17-143052-signup-conversion-speed --json
python3 "${CLAUDE_SKILL_DIR}/scripts/wiki_cli.py" recall --read DEC-2026-04-17-143052-move-auth-to-a-bff,INT-2026-04-17-143052-signup-conversion-speed

# 5. Save/load unresolved conversation context outside the canonical graph.
python3 "${CLAUDE_SKILL_DIR}/scripts/wiki_cli.py" snapshot save \
  --title "Auth migration discussion" \
  --summary "Context checkpoint before deciding the auth migration boundary." \
  --tags auth,discussion \
  --discussion "Current thread summary..." \
  --open-questions "Which service owns refresh rotation?"
python3 "${CLAUDE_SKILL_DIR}/scripts/wiki_cli.py" snapshot list auth --json
python3 "${CLAUDE_SKILL_DIR}/scripts/wiki_cli.py" snapshot load auth-migration-discussion

# 6. Retire / supersede.
python3 "${CLAUDE_SKILL_DIR}/scripts/wiki_cli.py" retire DEC-... --type superseded --superseded-by DEC-new
python3 "${CLAUDE_SKILL_DIR}/scripts/wiki_cli.py" retire DEC-... --type deprecated

# 7. Integrity (report-only by default; --fix is whitelisted).
python3 "${CLAUDE_SKILL_DIR}/scripts/wiki_cli.py" refresh --strict --json
python3 "${CLAUDE_SKILL_DIR}/scripts/wiki_cli.py" refresh --check changed-path-stale --changed-path "src/auth/x.ts,src/payment/y.ts"
python3 "${CLAUDE_SKILL_DIR}/scripts/wiki_cli.py" refresh --check decision-quality,task-quality --json
python3 "${CLAUDE_SKILL_DIR}/scripts/wiki_cli.py" refresh --fix index,retired-in-index
```

## Type decision guide

| User signal | Type | Why |
|-------------|------|-----|
| "The principle should outlive specific decisions" | `intent` | Root of the graph; decisions and rejections point at it. |
| "We decided / picked / adopted" | `decision` | Carries the winning intent, trade-offs, and re-evaluation triggers. |
| "We considered this but rejected" | `rejected_decision` | Carries the losing intent so it can be reconsidered later. |
| "Trap / anti-pattern / lesson / avoid next time" | `trial_error` | Lesson must be explicit (the `## 교훈` is checked). |
| "Found something but not sure if it's a decision, lesson, or SSOT update yet" | `observation` | Pre-classification record; gets retired as `superseded` when a successor TRI/DEC/SSOT-update is captured. |
| "How is X currently structured / behaving" | `ssot` | Living, updated in place. |
| "How do we run / deploy / operate X" | `runbook` | Living, procedural. |
| "A unit of work driven by decisions, optionally linked to external work" | `task` | Third category — handoff/context bridge node. Carries relations (intents/decisions/ssot/tasks); binary active/done state by path. |
| "Save this ongoing discussion so another session can resume it" | `snapshot` CLI | Staging layer outside the canonical graph; searchable/loadable but excluded from `recall`/`refresh` graph checks until explicitly captured/promoted later. |

**Living vs Record.** `ssot` and `runbook` are *living* — updated in place per topic. A second `capture` for the same slug exits `5` (conflict). `context/*` types are *immutable + superseded* — never edited; replace with a new record.

**Observation vs trial_error.** A `trial_error` has an explicit lesson. An `observation` is a finding too early to classify. When the classification firms up, capture a successor (TRI/DEC/SSOT-update) and `retire` the observation as `superseded` with the successor as primary replacement.

**Task (third category).** `task` is neither living nor record: its body is updated in place (living-like) and it carries relations (record-like), but its lifecycle is **binary by path** — active `task/` vs done `task/done/`. It's a *pure leaf* handoff/context bridge: it points outward (`intents`/`decisions`/`ssot`/`tasks`) and nothing points back at it (reverse is derived backlinks — `recall --backlinks-of <DEC>` surfaces the tasks a decision spawned, **including completed ones by default** — done is a valid terminal state, not a retired one). Finish a task with `complete` (→ `task/done/`), undo with `reopen`. A task never supersedes; an *invalid* task is `retire --type deprecated` (which, like any retired doc, then needs `--include-retired` to appear in backlinks). `--tasks` links it to external work items such as GitHub issues/PRs; the wiki validates the ref shape but never reads or synchronizes that system.

**Snapshot (staging layer).** `snapshot` is not a wiki graph type. Files live under `snapshot/active`, `snapshot/archived`, or `snapshot/promoted`, use `SNAP-YYYY-MM-DD-HHMMSS-<slug>` basenames, and are managed by `snapshot save/list/search/load/archive`. Default saves are append-only; `snapshot save --continues <ref>` links a follow-up checkpoint, and `snapshot save --update <ref>` rewrites an active snapshot only when explicitly requested. Snapshot files are searchable by snapshot commands but excluded from `recall`, relation resolution, `refresh --strict`, and duplicate-basename checks.

## Workflow (when you encounter a decision / intent / observation)

1. **`recall` first** — "Is there existing decision / intent / rejection / trial / observation on this topic?" Always look before deciding.
   ```bash
   recall "<topic>" --json   # Stage 1: frontmatter only, ~2KB guard
   ```
2. **`capture` the skeleton** — Pick the right type. `--title --summary --tags` are required; relation args follow the per-type allow list (see "Relations" below).
3. **Fill the §8 fixed body sections** — Restate the user's input in prose under each header. **Don't add / remove / rename section headers** — Stage-2 recall depends on this fixed structure.
4. **Supersede if needed** — When replacing an existing record, pass `--supersedes <old>` on capture, or run `retire ... --type superseded --superseded-by ...` afterward. A successor must be an active `context/*` record.
5. **`refresh` periodically** — After large changes or on request. In CI, pair `--check changed-path-stale` with the git diff.

## CLI contract (summary)

| sub | required | key options | exit codes |
|-----|----------|-------------|------------|
| `init` | — | `--dry-run` | `0` ok, `1` FS error |
| `capture` | `<type>` `--title` `--summary` `--tags` | `--slug` `--intents` `--ssot` `--runbook` `--rejected` `--decisions` `--tasks` `--supersedes` `--verified-at` `--audience` `--affects-paths` `--search-terms` `--dry-run` | `0` ok · `2` arg/scope violation (hub-with-relations, living-supersede, verified_at/affects_paths on wrong type, observation→intent relation, successor not a record, placeholder input) · `3` no vault · `4` ref ambiguous/missing/bad task format · `5` living slug global collision |
| `retire` | `<basename>` `--type deprecated\|superseded` | `--superseded-by <ref>` (required for superseded; must be an **active context/* record**), `--dry-run` | `0` · `2` arg / successor-not-record / task-with-superseded · `3` · `4` |
| `complete` | `<basename>` | `--dry-run` | `0` · `2` not-a-task · `3` · `4` missing / already-done |
| `reopen` | `<basename>` | `--dry-run` | `0` · `2` not-a-task · `3` · `4` missing / not-done |
| `relate` | `<basename>` | `--add-intents` `--add-decisions` `--add-ssot` `--add-tasks` `--dry-run` | `0` · `2` relation_not_allowed / empty · `3` · `4` missing / ambiguous / bad task format |
| `snapshot save` | `--title` `--summary` `--tags` | `--slug` `--continues <ref>` `--update <ref>` `--search-terms` fixed section options | `0` · `2` missing/placeholder input · `3` · `4` snapshot ref missing/ambiguous · `5` basename conflict overflow |
| `snapshot list/search` | — / `<query>` | `--include-archived` `--include-promoted` `--all` `--limit N` | `0` · `3` |
| `snapshot load` | `<ref>` | slug fragments accepted | `0` · `3` · `4` missing/ambiguous |
| `snapshot archive` | `<ref>` | active snapshots only | `0` · `3` · `4` missing/ambiguous · `5` destination collision |
| `recall` | — or `<query>` | `--type` `--tag` (repeatable) `--section` `--stage` `--limit` `--backlinks-of` `--read <a,b,c>` `--fuzzy` `--include-retired` | `0` always (zero hits is success), `4` only when `--read` target is missing |
| `refresh` | — | `--check <name,..>` (13 + `all`) `--days N` `--path <sub>` `--changed-path <p,..>` `--fix index,retired-in-index` `--strict` | `0` · `2` (unknown `--check`, `--fix` whitelist violation, bare `--fix`) · `6` (strict + ≥1 issue) |

Common: `--vault <path>` (default `./wiki`), `--json` (machine output). JSON success: `{"ok": true, ...}`. Failure: `{"ok": false, "error_code": "...", "message": "..."}`. `refresh` always returns `{"issues": [...]}` (and exits `6` under `--strict`); with `--fix` the payload adds `"fixed": [...]`.

### Friendly reference resolution

`capture` relation args (`--intents`, `--ssot`, `--runbook`, …) and `--supersedes`, plus `retire --superseded-by`, accept either:
- a full basename: `DEC-2026-04-17-143052-move-auth-to-a-bff`, or
- a slug fragment: `move-auth-to-a-bff`.

The CLI resolves fragments to the canonical basename; ambiguous fragments exit `4`. Matching checks exact basename first, then slug exact, slug prefix, and slug substring, all NFC-normalized so Korean/CJK + Latin mixed slugs work. Missing refs include candidate basenames in the error message. **Storage is always the full basename.**

The positional `retire <basename>` and `recall --read` default to **exact** basename matching for safety. Pass `--fuzzy` on `recall --read` to opt into fragment resolution.

`--tasks` entries are external work refs (`owner/repo#N`, `github:owner/repo#N`); the wiki validates format only — it does not verify the external work item exists. GitHub shares one number space across issues and PRs, so a PR is referenced with the same `#N` form. Human-edited quoted refs such as `["owner/repo#N"]` are accepted and normalized by CLI writes.

### Refresh checks (13 + optional quality flags)

| Check | Subjects | Detects |
|-------|----------|---------|
| `stale` | living + `verified_at`-bearing `trial_error` | `verified_at` older than `--days` (default 90) |
| `supersede` | all | supersede pair consistency in both directions |
| `broken-rel` | all (excluding `tasks`) | `relations.*` points at no real wiki doc |
| `task-ref` | `tasks` | supported external work ref format |
| `orphan` | active records | not referenced from anywhere |
| `index` | index files | drift vs the derived set |
| `retired-in-index` | index files | retired record still listed |
| `active-ref-retired` | active docs | `relations.*` points at a retired target |
| `tags` | when vocabulary exists | tag outside `ssot/tag-vocabulary.md` (skipped if absent) |
| `changed-path-stale` | living + `trial_error` + `observation` | `affects_paths` glob hits `--changed-path` (or `git diff`) without a `verified_at` refresh |
| `duplicate-basename` | every `.md` in the vault | global basename uniqueness (NFC-aware) |
| `empty-lesson` | `trial_error` | `## 교훈` blank or placeholder |
| `schema` | all | frontmatter integrity — required fields, ISO date validity, placeholder values, forbidden fields (`id` / `status` / `classified_as`), `relations` key on living, lifecycle nested in `relations`, disallowed relation sub-keys, relation target-type mismatch (incl. index-pointing), `verified_at` / `affects_paths` on wrong types |
| `decision-quality` | active `decision` | optional FLAG-to-human: missing intent link or non-substantive intent/background/alternatives/trade-off/reevaluation sections |
| `task-quality` | active `task` | optional FLAG-to-human: missing intent/decision link, rationale, completion criteria, verification, or affected path/file anchor |

`refresh --check all` runs the 13 integrity checks only. `decision-quality` and `task-quality` are explicit opt-in checks so v0 quality flags do not become default blockers. Unknown `--check` names or empty `--check ""` exit `2` so CI catches typos immediately.

### `refresh --fix` whitelist

- Allowed: `--fix index`, `--fix retired-in-index`, or a comma combination.
- **Bare `--fix` exits `2`.** Any non-whitelisted token (e.g. `--fix broken-rel`, `--fix stale`) exits `2` — repairs that require semantic judgment are reserved for explicit `capture` / `Edit`.
- The `fixed` array in JSON output reports every change (no silent mutation).

### Slug input tips

- Automatic: derived from `--title` via NFC normalization + kebab-case.
- Manual: `--slug` must satisfy `slugify(s) == s` (Unicode alnum + `-` only, no leading / trailing / consecutive `-`, no `.`).
- Use `--slug=<value>` for slugs that *could* start with `-` (argparse would otherwise treat them as options).
- Korean / CJK is NFC-normalized to keep macOS NFD vs other-OS NFC from breaking resolution.

## Recommended patterns

- **Capture a trial_error alongside the decision** that surfaced it: `capture trial_error --decisions <DEC-...>` immediately after the decision.
- **Use observation for pre-classification finds**: `capture observation --ssot <ssot> --affects-paths "src/<area>/**"`. When classification firms up, capture the successor and `retire --type superseded --superseded-by`.
- **Use snapshot for discussion checkpoints**: `snapshot save` when the user says to save the current conversation context but the content is not yet ready to become an `observation`, `decision`, `ssot`, or `runbook`.
- **Audit an intent's win/loss footprint**: `recall --backlinks-of <INT-...>` returns the decisions that won *and* the rejections, side-by-side.
- **Trace a decision to the work it spawned**: `recall --backlinks-of <DEC-...>` surfaces the `task` nodes that point at it — "what work did this decision produce?" — and keeps showing them after they're completed (done tasks stay in default backlinks; only `retire`d docs need `--include-retired`). Capture the task with `--decisions <DEC>` and, when external work exists, `--tasks owner/repo#N` or `--tasks github:owner/repo#N` so the link exists.
- **Add a missing relation without frontmatter edits**: use `relate`. Task nodes may add semantic relations (`--add-decisions`, `--add-intents`, `--add-ssot`) and external tasks. Immutable records only accept `--add-tasks`; capture a successor record for semantic changes.
- **Run `refresh` right after `retire ... --type superseded`** to confirm both sides of the supersede edge.
- **Manage the tag vocabulary**: drop allowed tags under an `## 어휘` section in `wiki/ssot/tag-vocabulary.md`. The `tags` check then flags vocabulary violations; absent the file, the check is skipped.
- **Re-verification**: stamp living notes with `--verified-at YYYY-MM-DD`; `refresh --check stale --days 90` reports anything past the threshold.
- **Code-change drift**: anchor relevant docs with `--affects-paths "src/<area>/**"`. Feed PR diffs (or `git diff --name-only HEAD`) to `refresh --check changed-path-stale --changed-path <list>` to surface affected docs.
- **Batch reads**: when reading a known set, `recall --read a,b,c` preserves input order and packs into one response.

## Four-layer separation (§15)

This plugin is the **mechanism** layer — agent-neutral. Working-environment operating policy (who captures what, when to isolate worktrees, GitHub-Issue flow, promotion triggers, etc.) belongs in auto-loaded agent entry files such as `CLAUDE.md`, `AGENTS.md`, or `.claude/`. The optional `agent-policy` skill scaffolds those files idempotently. Accumulated product/system knowledge lives in `wiki/`; this skill does not create a consumer project's `wiki/ssot/agent-operating-model.md`.

## References

- `references/wiki-protocol.md` — Full schema / sections / lifecycle / CLI contract in one place.
- `../../rules/knowledge-protocol.md` — Mechanism layer; ships with the plugin.
- `../agent-policy/` — Optional Claude/Codex operating-policy scaffold for auto-loaded entry files.
- `../../templates/` — Per-type body skeletons (human reference).

## Output interpretation tips

- `--json` payloads are safe for `json.loads` — recommended whenever another skill or chain consumes the result.
- Human output is Korean by default (matches the section header convention). Surface JSON to users when they want a structured view.
- `recall --json` Stage 1 returning `truncated: true` means more results were dropped; pass the hint through and ask the user for `--type` / `--tag` narrowing.
- `refresh` issues come as `{check, path, field?, target?, message}`. Group by `check` when summarizing.
- `recall --read a,b,c` JSON `results` preserve input order.
