# session-review

`session-review` coordinates a worker/reviewer loop inside a workspace. The
handshake is a snapshot written by the snapshot provider configured in
`.session-review.yml` (built-in, `wiki-markdown`, or `context-core`), the
review target is either a git diff or a document, and convergence lands by
squash-merging the review branch back to the worker branch after reviewer
approval. Separate/team review and audit
self-review require explicit user confirmation before completion; self turnkey
can complete without a second confirmation because that consent is part of the
initial profile.

## When to use

Use session-review when an addressable reviewer must remain independent across
feedback rounds, or when the result needs an auditable approval gate. Use a
normal same-agent check for simple bounded verification; recording overhead can
be reduced with fast mode, but reviewer separation is never removed.

The machine-readable source of truth is the first fenced `yaml` block inside
the snapshot's primary section (`## 현재 논의` for built-in/`wiki-markdown`,
`## 현재 맥락` for `context-core`). Helper code lives in
`scripts/session_review.py`; skills call it to enforce actor ownership, locks,
typed string fields, derived review posture, and the completion gate.

## Single CLI facade

All skill operations go through `scripts/session_review.py` only — skills never
call a provider CLI directly. Subcommands: `snapshot-save` / `snapshot-load` /
`snapshot-discard` (handshake I/O), `snapshot-dir` (the provider's snapshot
directory, for `git add`), `set-status` (rewrite the status block in place),
`validate-status` / `validate-turn` / `validate-complete` (gates), `render`
(status block), `doctor` (read-only provider/root/git readiness).
Mutate commands take `--slug` (path resolved
internally); read/validate commands (`status` / `validate-turn` /
`validate-status` / `validate-complete`) also accept `--file` or
`--status-json`, so fast mode runs the same machine gates without a snapshot.

Reviewer episode operations use the same facade:

- `lease-acquire`: returns `fresh|reuse` plus the updated status. `--slug`
  persists an audit snapshot; `--status-json` is the snapshot-free fast-mode
  transport.
- `emit-receipt`: emits `workflow-receipt/v1` from either transport.

## Snapshot provider (`.session-review.yml`)

`session-review` has **no plugin dependency**. The snapshot handshake is written
by whichever provider the workspace names in `.session-review.yml` (looked up
in the current directory, then at the git toplevel). Nothing is auto-discovered:
a `wiki-markdown` sitting next to this plugin is never used unless configured.

```yaml
# .session-review.yml
snapshot-provider: context-core   # builtin (default) | wiki-markdown | context-core
# snapshot-cli: /path/to/context_cli.py   # optional; located automatically when omitted
```

| provider | snapshot file | status section | notes |
|---|---|---|---|
| `builtin` (default) | `<vault>/snapshot/SNAP-<slug>.md` | `## 현재 논의` | built-in writer, same format/location as `wiki-markdown` (DEC-2026-06-18 — not a bespoke format); maintains `snapshot.md` only if it already exists |
| `wiki-markdown` | `<vault>/snapshot/SNAP-<slug>.md` | `## 현재 논의` | delegates to `wiki_cli.py snapshot save/load/discard`; vault = `WIKI_VAULT` or `./wiki` |
| `context-core` | `<root>/context/snapshot/<slug>.md` | `## 현재 맥락` | delegates to `context_cli.py` two-phase writes (`snapshot save/update/discard` → `transaction apply`); root = the git worktree (cwd); `context_cli.py init` must have run |

`snapshot-cli` is optional: when omitted, the configured provider's CLI is
located from this script's own path — monorepo sibling plugin, then the
installed plugin cache (any marketplace, newest version), then `PATH`. That
lookup is harness-agnostic (Claude Code and Codex) and runs **only** for the
provider you named; a configured provider whose CLI cannot be found is an
error, never a silent fallback.

### context-core mapping

The facade keeps one section vocabulary for every provider
(`--discussion/--background/--decided/--open-questions/--next/--references/--promotion-candidates`).
For `context-core` they map to `현재 맥락 / 참조 / 정해진 것 / 열린 항목 / 다음 단계 /
참조 / capture 후보` — `--background` has no counterpart and is folded into
`참조`. Non-primary sections are stored as `- ` lists (context-core's
convention). Because `context_cli snapshot save` caps the primary section at
1200 characters, a new snapshot is created from short seed sections and the real
content lands through `snapshot update --merge`, which has no cap; the required
`열린 항목`/`다음 단계` keep the seed text unless you pass `--open-questions` /
`--next`. `set-status` rewrites the status block in place for every provider;
context-core indexes frontmatter only, so its `doctor`/`load` stay clean after
such body-only writes (covered by tests).

## Environment overrides

- `SESSION_REVIEW_SNAPSHOT_PROVIDER` — overrides `snapshot-provider`
  (`builtin|wiki-markdown|context-core`).
- `SESSION_REVIEW_SNAPSHOT_CLI` — overrides `snapshot-cli` (path to the provider
  CLI).
- `SESSION_REVIEW_CLI` — explicit path to `session_review.py` (for skill
  invocation where the harness can't supply the plugin root).
- `WIKI_VAULT` — vault root for `builtin`/`wiki-markdown` (default `./wiki`).
  `--vault` on any subcommand overrides the provider root explicitly (for
  `context-core` that is the worktree holding `context/`).

## Read-only doctor

`session-review:doctor` never creates or edits `.session-review.yml`. It reports
the resolved provider (`provider`, `source` = env|config|default, `cli`,
`config`), provider-root readiness (vault existence/creatability, or
context-core initialization), and Git worktree/branch/HEAD/dirty state as JSON:

```bash
python3 plugins/session-review/scripts/session_review.py doctor --json
```

The built-in provider is a supported ready state. A configured provider whose
CLI is missing, an uninitialized context-core root, a missing Git worktree, or
an unusable vault fails readiness because the review loop cannot safely branch
or persist its handshake.

## Self-mode profiles

Self review has two independent axes:

- `self_automation`: `manual|auto-rounds|turnkey`
- `recording_mode`: `audit|fast`

Defaults are conservative: `self` uses `manual + audit`, and `separate` is
always audit. `auto-rounds` may use audit or fast, but still stops before
complete for user confirmation. `turnkey` is self-only and forces fast: no
snapshot, review branch, or round commits. It still requires the separated
reviewer selected by the lease; fast removes recording overhead, not reviewer separation. The final
complete commit carries the subagent verdict, resolved findings, and test
evidence.

Audit mode keeps the snapshot handshake and round commits. Its complete flow
lands the squash merge and snapshot discard in one `review: complete` commit,
so the transient snapshot does not survive in main history.

## Reviewer episode lease

Round 1 always acquires a fresh reviewer. Later rounds reuse that reviewer when
the scope digest, base ref, review strength, and round horizon are unchanged and
the harness can address the same `reviewer_ref`. A changed target ref is the
normal confirmation input and updates `lease_target_ref` without replacing the
reviewer. Scope, base, reviewer, strength, expiry, or addressability changes
produce a fresh decision with an explicit reason. Diff mode rejects identical
`base_ref` and `target_ref` before reviewer handoff.
The default horizon permits two reuse rounds after acquisition.

The status carries the lease id, optional reviewer ref, last reviewed ref,
scope/finding digests, started/updated timestamps, expiry round, and cumulative
`fresh_count`/`reuse_count`. A pre-lease snapshot is lazily migrated to
`fresh_required: true` with `fresh_fallback_reason: legacy_snapshot`; no
reviewer identity is invented. Review feedback records `reviewed_ref` and
`finding_digest` together.

Fast mode passes the returned status JSON directly to the reviewer. This drops
snapshot ceremony without weakening the same lease decision contract.

## Receipt schema v1

`emit-receipt` outputs the binding fields `schema`, `emitter`, `workflow`,
`run_id`, timestamps, `elapsed_ms`, `tokens`, `token_coverage`, `counters`, and
`quality`. Unknown token usage is always `tokens: null` with
`token_coverage: unavailable`; it is never estimated or replaced with zero.

## Status block consistency

The status block may carry these optional review-posture fields:

- `target_nature`: `code|spec|direction|process|general`
- `round_type`: `explore|converge|confirm|review`
- `review_posture`: optional override, `verify|challenge|co-design`
- `self_automation`: self-only, `manual|auto-rounds|turnkey`
- `recording_mode`: `audit|fast`

Defaults are conservative: `target_mode: "diff"` derives `target_nature:
"code"`, document/unknown targets fall back to `"general"`, and missing
`round_type` becomes `"review"`. The helper derives
`effective_review_posture` from `target_nature + round_type`; `confirm` is not a
posture and is represented only as `round_type: "confirm"` with a separate
lock-check path.

Reviewer verdict phases must carry `blocking_count` (int). `validate-status`
enforces `phase: "approved"` ⇒ `blocking_count == 0` and
`phase: "changes-requested"` ⇒ `blocking_count >= 1`, making the verdict
machine-verifiable rather than prose-only. Approved means no blocking feedback,
not "no further ideas"; co-design/challenge reviews may still leave
`[should-reflect-before-implementation]`, `[directional]`, `[nice-to-have]`, or
`[nit]` items for the worker synthesis and complete path. `validate-complete`
also rejects missing or nonzero `blocking_count`.

`recording_mode=fast` is self-only. `self_automation=turnkey` must use fast and
is the only profile where `validate-complete` does not require
`--user-confirmed`. Same-agent self-checks are not session-review.
