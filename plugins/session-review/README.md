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
