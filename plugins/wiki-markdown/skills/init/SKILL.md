---
name: init
description: Initialize or upgrade wiki-markdown in a project. Use when the user asks to initialize, set up, or bootstrap a project wiki, create the wiki vault, or install and refresh wiki-markdown's auto-loaded operating policy in CLAUDE.md and AGENTS.md.
---

# Initialize Wiki

Initialize the deterministic wiki vault and the auto-loaded agent policy as one user-facing
operation. Keep the raw CLI vault-only.

## Workflow

1. Read existing `CLAUDE.md`, `AGENTS.md`, their managed `agent-operating-policy` blocks, and
   relevant project configuration. Read `../agent-policy/SKILL.md` completely before choosing
   scaffold options.
2. Infer `target`, `profile`, `tracker`, and `concurrency` from current project evidence. Ask one
   compact question only when a materially consequential choice remains unknown; never accept the
   scaffold script's defaults blindly.
3. Resolve the plugin root. `WIKI_MARKDOWN_ROOT` wins; Claude Code may provide
   `CLAUDE_PLUGIN_ROOT`; on hosts that provide neither, set `WIKI_MARKDOWN_ROOT` to the installed
   `wiki-markdown` plugin root containing this skill.
4. Initialize or reconcile the vault:

   ```bash
   python3 "${WIKI_MARKDOWN_ROOT:-$CLAUDE_PLUGIN_ROOT}/skills/wiki/scripts/wiki_cli.py" init --json
   ```

5. Run the existing policy scaffold with the resolved options:

   ```bash
   python3 "${WIKI_MARKDOWN_ROOT:-$CLAUDE_PLUGIN_ROOT}/skills/agent-policy/scripts/scaffold_agent_policy.py" \
     --target <all|claude|codex> \
     --profile <solo|team> \
     --tracker <task-github|none> \
     --concurrency <worktree|shared> \
     --json
   ```

6. Review the resulting diff. Confirm the vault exists, each selected entry file has exactly one
   managed block, and content outside the block is preserved. Report created, updated, and
   unchanged targets.

## Guardrails

- Treat explicit invocation of this skill as authority to create the vault and selected managed
  policy blocks, not to rewrite unrelated project policy or product knowledge.
- Keep raw `wiki_cli.py init` vault-only so direct CLI automation never writes agent entry files.
- Never create `wiki/ssot/agent-operating-model.md` in a consumer project.
- Never replace an entire `CLAUDE.md` or `AGENTS.md`; let the scaffold script manage only its
  marker-delimited block.
- If the user explicitly requests vault-only initialization, run only the raw CLI and state that
  the auto-loaded policy was not installed.
