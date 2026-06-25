---
name: wiki
description: Manage an AI-native project wiki — capture intents, decisions, rejected alternatives, trial-error lessons, observations, current state (SSOT) and operating runbooks as a decision graph; query it; refresh integrity. Use whenever the user wants to record what was decided / why, retrieve related context before a decision, file an observation for later classification, retire or supersede a record, or run a wiki integrity check. Filesystem-primary, deterministic CLI — minimal tokens to stay consistent.
---

# Wiki

Drives one stdlib Python CLI, `wiki_cli.py`, against a local vault (default `wiki/`). Exit codes and `--json` are deterministic — branch on results without re-parsing prose.

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/wiki_cli.py" <subcommand> [args]
```

`${CLAUDE_SKILL_DIR}` is this skill's installed dir (substitute the absolute path in other harnesses).

> **This page is the runtime cheat-sheet.** The exhaustive contract — every field, all 13 refresh checks, the full exit-code matrix, YAML subset, NFC rules — lives in [`references/wiki-protocol.md`](references/wiki-protocol.md). Load it only when you need a detail not here.

Core loop: **`recall` before deciding, `capture` after deciding** (mechanism in `rules/knowledge-protocol.md`).

## When to use

- **Record durable knowledge**: "log this decision / intent / why we rejected X / this trap"; "found something, can't classify yet" → `observation`.
- **Document state/procedure**: current architecture → `ssot`; deploy/run procedure → `runbook`.
- **Retrieve before acting**: "what did we decide about X?", "related intents?", "tried before?", "who superseded this?".
- **Save/resume discussion**: "save this discussion" → `snapshot save`; "load previous context" → `snapshot load`.
- **Integrity/drift**: "check the wiki", "stale facts?", "broken links?", "what does this code change affect?".
- **Plan a unit of work** (work-definition/handoff bridge) → `task`.
- **Retire/supersede**: "mark deprecated", "supersede X with Y".

## When NOT to use (negative triggers — prefer code/runtime evidence)

The wiki is a **durable context/decision layer, not a runtime-debug companion**. Stay out of the way when:

- The user reports a **concrete runtime bug** (a customer id, an API path, a wrong screen value) — inspect **code → API → DB → render path first**; touch the wiki only on a real design ambiguity or policy conflict.
- The change is a **small single-file edit** and the active task/decisions are already in this session's context — don't re-`recall`.
- This session **already recalled** the active task + decisions — reuse that, don't widen recall again unless code/DB evidence conflicts or the user asks.
- The user asks for **speed** ("just find it", "don't explain, fix it") — runtime evidence outranks wiki lookup.

`snapshot`/`observation` are **non-authoritative** (may be stale vs the newest `decision`); never treat a loaded snapshot as current truth without checking it against decisions.

## Quick start

```bash
# 0. Init (idempotent). ($CLI is shorthand for this cheat-sheet's examples.)
CLI="${CLAUDE_SKILL_DIR}/scripts/wiki_cli.py"
python3 "$CLI" init

# 1. Capture WITH body in ONE call — fill §8 sections inline via --sec-<flag>.
#    (No skeleton→Read→Edit round-trip. --json returns which sections you filled
#     vs left empty + the --sec-<flag>→header map, so no file Read is needed.)
python3 "$CLI" capture decision --json \
  --title "Move auth to a BFF" --summary "Session tokens owned by the BFF." \
  --tags auth,architecture --intents signup-conversion-speed --tasks owner/repo#18 \
  --sec-decision "We move session ownership to a BFF." \
  --sec-intent  "Serves signup-conversion-speed by cutting client token handling." \
  --sec-background "..." --sec-tradeoffs "..." --sec-reeval "..."
#    --lite : fill only the core sections, prefill the rest with '해당 없음'
#             (and mark the doc so opt-in quality checks skip non-core sections).

# 2. Capture other types (relation args follow the per-type allow list).
python3 "$CLI" capture observation --json --title "Webhook timeout risk" \
  --summary "External webhooks may exceed the 30s budget." --tags webhook,reliability \
  --ssot webhook-architecture --affects-paths "src/webhook/**" --sec-observation "..." --sec-basis "..."
python3 "$CLI" capture task --json --title "Move payment session to the BFF" \
  --summary "Payment side of the BFF migration." --tags payment,architecture \
  --decisions move-auth-to-a-bff --sec-overview "..." --sec-basis "..." --sec-scope "..."
python3 "$CLI" complete TASK-...   # active → task/done/ (reopen to undo)

# 3. Relate / recall.
python3 "$CLI" relate DEC-... --add-tasks owner/repo#18
python3 "$CLI" recall "auth" --json                 # Stage 1: frontmatter only (~2KB guard)
python3 "$CLI" recall "auth" --stage 2 --section 취지 # Stage 2: one section
python3 "$CLI" recall "auth" --pack --json            # context pack: labels + section snippets, authority-ranked
python3 "$CLI" recall --backlinks-of INT-... --json   # what a hub spawned (incl. done tasks)
python3 "$CLI" recall --read DEC-...,INT-...           # batch read, input order preserved

# 4. Snapshot (staging, outside the graph).
python3 "$CLI" snapshot save --title "Auth migration discussion" \
  --summary "Checkpoint before deciding the boundary." --tags auth,discussion --discussion "..."
python3 "$CLI" snapshot save --slug auth-migration-discussion --merge --decided "..."  # update only given sections
python3 "$CLI" snapshot load auth-migration-discussion

# 5. Retire / supersede (keeps the file) — vs discard (mistake-undo, deletes it).
python3 "$CLI" retire DEC-... --type superseded --superseded-by DEC-new
python3 "$CLI" retire DEC-... --type deprecated
python3 "$CLI" discard DEC-... --dry-run   # preview: shows backlinks + would_block
python3 "$CLI" discard DEC-...             # delete a wrongly-created node (refuses if referenced; --force to override). git keeps history.

# 6. Integrity — tiered (see "refresh tiers" below).
python3 "$CLI" refresh --level integrity --strict --json   # hard gate: exit 6 only on integrity-tier issues
python3 "$CLI" refresh --level hygiene --json               # advisory (orphan/stale/tags …) — non-blocking
python3 "$CLI" refresh --check changed-path-stale --changed-path "src/auth/x.ts"
python3 "$CLI" refresh --fix index,retired-in-index        # whitelist-only auto-fix
```

## Type decision guide

| User signal | Type |
|-------------|------|
| "principle should outlive specific decisions" | `intent` (hub) |
| "we decided / picked / adopted" | `decision` |
| "considered but rejected" | `rejected_decision` |
| "trap / anti-pattern / lesson" | `trial_error` (explicit `## 교훈`) |
| "found something, not sure how to classify yet" | `observation` (promote later) |
| "how X currently is / behaves" | `ssot` (living) |
| "how we run/deploy X" | `runbook` (living) |
| "plan a unit of work — work-definition handoff" | `task` (third category) |
| "save this discussion to resume later" | `snapshot` CLI (staging, not a graph type) |

**Living vs Record.** `ssot`/`runbook` are *living* (updated in place; a second `capture` for the same slug exits `5`). `context/*` are *immutable + superseded*. **`task` is a third category**: body updated in place, carries relations, binary state by path (`task/` ↔ `task/done/`); finish with `complete`, never supersede. **`snapshot`** is staging outside the graph — excluded from `recall`/`refresh`; managed by `snapshot save/list/search/load/discard`.

## 1-call capture & the JSON payload

`capture` accepts `--sec-<flag>` for every section of the type — fill the body in the **same call**, no skeleton→Read→Edit. `capture --json` returns (additive):

| Field | Use |
|-------|-----|
| `sections` / `core_sections` | the type's headers; which are mandatory-substantive |
| `section_flags` | `{flag: header}` — which `--sec-<flag>` fills which header |
| `filled_sections` / `lite_sections` / `empty_sections` | authored prose · `--lite` `해당 없음` prefill · still blank — pick the next edit from `empty_sections`, **no Read needed** |
| `lite` / `index_changed` / `index_paths` | was `--lite` used · index files rewritten this call (for `git add`) |

`--lite` fills only core sections (`해당 없음` for the rest) and sets `lite: true` so opt-in `decision-quality`/`task-quality` checks skip non-core sections; its placeholdered headers appear in `lite_sections`, never `filled_sections`. Run those checks later to flag thin sections.

## refresh tiers (`--level`)

Checks are tiered: **integrity-hard** (graph/data correctness — block) vs **hygiene-warn** (regenerable/stylistic — advise). Every issue carries a `tier`.

- `--level integrity --strict` → exits `6` **only** on integrity issues (hygiene-only ⇒ exit `0`). **This is the merge/verify hard gate** (task-github depends on it).
- `--level hygiene` → surfaces advisories (orphan/stale/tags …); non-blocking.
- `--level all` (default) keeps prior behaviour. Pair `--check changed-path-stale --changed-path <list>` with a PR diff for code↔doc drift (also a hard gate).

> `refresh --strict` validates **structural integrity only** — not semantic freshness, stale snapshots, or code/wiki consistency. A clean strict run ≠ "the wiki is up to date."

## CLI cheat-sheet (one line each; full contract in `references/`)

| sub | gist | key flags |
|-----|------|-----------|
| `init` | create vault skeleton (idempotent) | `--dry-run` |
| `capture <type>` | create note, 1-call body, sync indexes | `--title --summary --tags` · `--sec-<flag>` · `--lite` · relations (`--intents/--ssot/--decisions/--tasks/…`) · `--supersedes` · `--dry-run` |
| `retire <bn>` | deprecate / supersede a record (keeps file) | `--type deprecated\|superseded` · `--superseded-by` |
| `discard <bn>` | **delete** a node (mistake-undo; git keeps history) | exact basename · `--dry-run` (preview) · `--force` (over backlinks) |
| `complete`/`reopen <bn>` | task → done / back | `--dry-run` |
| `relate <bn>` | add relations w/o editing frontmatter | `--add-intents/--add-decisions/--add-ssot/--add-tasks` |
| `snapshot save/list/search/load/discard` | staging I/O | `save`: `--title --summary --tags` · section flags · `--merge` |
| `recall` | read-only query | `[query]` · `--stage 1\|2\|3` · `--pack` · `--section` · `--type/--tag` · `--backlinks-of` · `--read a,b,c` · `--fuzzy` · `--include-retired` · `--days` (pack stale) |
| `refresh` | integrity report | `--level all\|integrity\|hygiene` · `--strict` · `--check <name,..>` · `--changed-path` · `--fix index,retired-in-index` |
| `schema` | introspect the type model (types/sections/flags/relations) | read-only · **no vault needed** · `--json` |

Need a type's sections/flags/relations? `schema --json` (or `capture <type> --dry-run --json` to also validate refs and preview the id/path — `dry_run: true`, nothing written). Don't guess or read a doc to learn the contract.

Common: `--vault <path>` (default `./wiki`), `--json`. Success `{"ok": true, ...}`; failure `{"ok": false, "error_code": "...", "message": "..."}`. Exit codes: `0` ok · `2` arg/usage · `3` no vault · `4` ref ambiguous/missing · `5` living-slug collision · `6` strict refresh found integrity issues. (Full per-subcommand matrix → `references/`.)

## Output interpretation

- `recall --json` is discriminated by `mode`: `stage1` / `stage2` / `stage3` / `read` / `backlinks` / `pack`, each with a `results` list (`--read` preserves input order). Stage-1 `truncated: true` ⇒ narrow with `--type`/`--tag`.
- `recall --pack` (`mode: pack`, `projection: deterministic`, `ranked_by: authority`) projects matched docs into one read: frontmatter + `relations` + the type's primary section snippet + additive labels `authority`/`freshness`/`use_as`/`warnings`. **No prose inference** — it extracts only fixed fields/headers. `freshness` is relation-aware: an un-anchored record is `authority_unknown` (never a false "stale"); `anchor_changed` flags a retired/superseded anchor. Authority ranking applies inside the pack only — default `stage1`/`2`/`3` are unchanged.
- `snapshot load --json` carries the same additive labels (`authority: staging`, `use_as: resume_context`, `freshness`, `warnings`): a snapshot is staging, not graph truth, so `freshness` reports whether the **records it references** (in its `관련 파일/문서` section) are still current — `anchor_changed` if one was retired/superseded, `authority_unknown` when none resolve. Don't over-trust a loaded snapshot whose anchors changed.
- `capture --json` → `empty_sections` = blank headers needing prose (`--lite` placeholders sit in `lite_sections`, not here); `index_paths` for `git add`; `dry_run: true` marks a `--dry-run` preview (validated, nothing written — `index_changed: false`).
- `schema --json` → `{types: {<type>: {sections, core_sections, section_flags, allowed_relations, prefix, id_form, …}}, relation_target_types, snapshot_sections, refresh_checks: {integrity, hygiene}}`. Deterministic projection of the registry; the authoritative source for what a type accepts.
- `refresh` issues are `{check, tier, path, field?, target?, message}` — group by `check`, gate on `tier == "integrity"`.
- Human output is Korean (matches section headers). Surface `--json` to other tools/skills.

## Four-layer separation

This plugin is the **mechanism** layer — agent-neutral. Working-environment operating policy (who captures what, worktree rules, GitHub-Issue flow, **when to prefer code over wiki**) belongs in auto-loaded entry files (`CLAUDE.md`/`AGENTS.md`); the `agent-policy` skill scaffolds them. Product/system knowledge lives in `wiki/`.

## References

- [`references/wiki-protocol.md`](references/wiki-protocol.md) — full schema / sections / lifecycle / exit codes / checks.
- `../../rules/knowledge-protocol.md` — mechanism layer.
- `../agent-policy/` — Claude/Codex operating-policy scaffold.
- `../../templates/` — per-type body skeletons.
