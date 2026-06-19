# session-review

`session-review` coordinates a worker/reviewer loop inside a workspace. The
handshake is a `wiki-markdown` snapshot, the review target is either a git diff
or a document, and convergence lands by squash-merging the review branch back
to the worker branch only after reviewer approval and explicit user
confirmation.

The machine-readable source of truth is the first fenced `yaml` block inside
the snapshot `## 현재 논의` section. Helper code lives in
`scripts/session_review.py`; skills call it to enforce actor ownership, locks,
typed string fields, and the completion gate.

## Single CLI facade

All skill operations go through `scripts/session_review.py` only — skills never
call `wiki_cli` directly. Subcommands: `snapshot-save` / `snapshot-load` /
`snapshot-discard` (handshake I/O), `set-status` (rewrite the status block in
place), `validate-status` / `validate-turn` / `validate-complete` (gates),
`render` (status block). Read/validate/mutate commands take `--slug`; the path
is resolved internally.

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

## Status block consistency

The status block may carry `blocking_count` (int). `validate-status` enforces
`phase: "approved"` ⇒ `blocking_count == 0`, making the approve decision
machine-verifiable rather than prose-only.
