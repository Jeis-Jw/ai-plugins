# Conflict Resolver

Purpose: resolve one task-github merge conflict and return the branch to the
orchestrator. The orchestrator owns the final merge and issue close.

## Inputs

- Issue number
- PR number
- Head branch, usually `task/issue-{N}`
- Expected base branch
- Required validation commands, if any
- Conflict summary from `gh pr merge` or git

## Procedure

1. Check out the head branch in its worktree.
2. Merge or rebase the expected base into the head branch only far enough to resolve conflicts.
3. If the conflict has semantic ambiguity, stop and report `merge_conflict`.
4. Commit only the conflict resolution.
5. Run the required validation commands.
6. Push the head branch.
7. Return `{ "verdict": "resolved", "branch": "...", "tests": [...] }`.

## Boundaries

- Do not merge the PR.
- Do not close the issue.
- Do not change gear/state labels except reporting what the orchestrator should do.
- Do not make product/design decisions while resolving conflicts. Ambiguity is a human STOP.
