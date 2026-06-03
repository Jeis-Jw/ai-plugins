---
name: agent-policy
description: Scaffold or update auto-loaded agent operating policy files for Claude and Codex. Use when a project needs working-environment policy such as concurrency/worktree rules, capture authority, task-github usage, or promotion triggers. Writes CLAUDE.md and/or AGENTS.md, and deliberately keeps operating policy out of the consumer project's wiki vault.
---

# Agent Policy

This skill installs concise, auto-loaded operating policy into a project.

Use it when a project using `wiki-markdown` or `task-github` needs rules for:

- agent roles and profile (`solo` or `team`)
- concurrent task isolation
- task tracker binding (`task-github` or none)
- design altitude: decomposition in brainstorm, unit-internal detail in the issue/run
- capture authority and promotion trigger defaults

The policy statement belongs in auto-loaded entry files, not in the consumer project's wiki vault. The wiki can store product/system knowledge; it should not be the place an agent must recall before it can know how to operate.

## Workflow

1. Inspect existing `CLAUDE.md` and `AGENTS.md`.
2. Elicit only missing choices:
   - target: `all`, `claude`, or `codex`
   - profile: `solo` or `team`
   - tracker: `task-github` or `none`
   - concurrency: `worktree` or `shared`
   - unit design altitude: keep the default unless the project has a stricter local rule
3. Run the bundled script with the selected options.
4. Review the diff. The script manages only the marked block and preserves all other content.

```bash
python3 <skill-dir>/scripts/scaffold_agent_policy.py \
  --target all \
  --profile solo \
  --tracker task-github \
  --concurrency worktree \
  --json
```

## Guardrails

- Do not write `wiki/ssot/agent-operating-model.md` in a consumer project.
- Do not replace entire `CLAUDE.md` or `AGENTS.md`.
- Keep the managed block short. Long rationale belongs in this plugin project's design records, not in every downstream prompt.
- If an existing project already has a long policy in wiki, migrate the operative rules into the entry files and leave the wiki document untouched unless the user asks to retire or rewrite it.

## Script Options

| Option | Values | Default |
|--------|--------|---------|
| `--target` | `all`, `claude`, `codex` | `all` |
| `--profile` | `solo`, `team` | `solo` |
| `--tracker` | `task-github`, `none` | `task-github` |
| `--concurrency` | `worktree`, `shared` | `worktree` |
| `--root` | project root path | current directory |
| `--dry-run` | report only | off |
| `--json` | machine output | off |
