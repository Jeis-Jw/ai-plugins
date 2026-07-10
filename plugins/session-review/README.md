# session-review

`session-review` coordinates a worker/reviewer loop inside a workspace. The
handshake is a `wiki-markdown` snapshot, the review target is either a git diff
or a document, and convergence lands by squash-merging the review branch back
to the worker branch after reviewer approval. Separate/team review and audit
self-review require explicit user confirmation before completion; self turnkey
can complete without a second confirmation because that consent is part of the
initial profile.

The machine-readable source of truth is the first fenced `yaml` block inside
the snapshot `## 현재 논의` section. Helper code lives in
`scripts/session_review.py`; skills call it to enforce actor ownership, locks,
typed string fields, derived review posture, and the completion gate.

## Single CLI facade

All skill operations go through `scripts/session_review.py` only — skills never
call `wiki_cli` directly. Subcommands: `snapshot-save` / `snapshot-load` /
`snapshot-discard` (handshake I/O), `set-status` (rewrite the status block in
place), `validate-status` / `validate-turn` / `validate-complete` (gates),
`render` (status block). Read/validate/mutate commands take `--slug`; the path
is resolved internally.

Reviewer episode operations use the same facade:

- `lease-acquire`: returns `fresh|reuse` plus the updated status. `--slug`
  persists an audit snapshot; `--status-json` is the snapshot-free fast-mode
  transport.
- `emit-receipt`: emits `workflow-receipt/v1` from either transport.

## Snapshot backend (hybrid)

The snapshot handshake uses `wiki-markdown` when available and a built-in writer
otherwise — both produce the **same** snapshot file format and location, so a
workspace with only `session-review` installed still works.

- `wiki-markdown` is the **recommended companion** (keeps the snapshot index and
  the rest of the decision graph). Without it, the built-in fallback covers the
  review loop on its own.
- Backend discovery is harness-agnostic (works in both Claude Code and Codex):
  `session_review.py` self-locates via its own path; no `CLAUDE_PLUGIN_ROOT`
  dependency in the resolver.

## Environment overrides

- `SESSION_REVIEW_WIKI_CLI` — explicit path to `wiki_cli.py`, or `none`/`off` to
  force the built-in backend.
- `SESSION_REVIEW_CLI` — explicit path to `session_review.py` (for skill
  invocation where the harness can't supply the plugin root).
- `WIKI_VAULT` — vault root (default `./wiki`).

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

Round 1 always acquires a fresh reviewer. Later rounds reuse that reviewer only
when the scope digest, target/base refs, review strength, and round horizon are
unchanged and the harness can address `reviewer_ref`. Otherwise the decision is
fresh with one of `scope_changed|ref_changed|risk_changed|round_expired|harness_unaddressable`.
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
