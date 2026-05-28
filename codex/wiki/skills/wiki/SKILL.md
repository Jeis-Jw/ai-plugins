---
name: wiki
description: Use when initializing, reading, creating, retiring, validating, or repairing an AI-native project wiki stored under wiki/. This skill manages SSOT/runbook living notes and context records for intents, decisions, rejected decisions, trial errors, and observations through the bundled wiki CLI.
---

# Wiki

## Overview

Use this skill to keep a project wiki as the AI-readable source of truth. The default vault is `wiki/`, not `docs/`. The bundled CLI enforces basename IDs, folder-derived indexes, record-only relations, retired record isolation, optional `search_terms`, path drift checks with `affects_paths`, and filesystem-only recall.

Run commands from the project root:

```bash
python3 <plugin>/skills/wiki/scripts/wiki_cli.py <command>
```

When this skill is installed as a plugin, `<plugin>` is the plugin root. In this repository it is `codex/wiki`.

## Workflow

1. Before making design or implementation choices, use `recall` to load the smallest useful context.
2. When a settled fact or current design changes, update or create a living `ssot` or `runbook` note.
3. When a decision, intent, rejected alternative, trap, or still-unclassified observation is settled, create a context record with `capture`.
4. When a context record is no longer active, use `retire`; do not edit indexes by hand.
5. Run `refresh --strict` before claiming the wiki is consistent.

## Commands

Initialize the vault:

```bash
python3 codex/wiki/skills/wiki/scripts/wiki_cli.py init
```

Create a living SSOT note:

```bash
python3 codex/wiki/skills/wiki/scripts/wiki_cli.py capture ssot \
  --title "Auth Architecture" \
  --summary "Current auth architecture." \
  --tags auth,architecture \
  --verified-at 2026-05-22
```

Create an intent and a decision linked to it:

```bash
python3 codex/wiki/skills/wiki/scripts/wiki_cli.py capture intent \
  --title "Signup Speed" \
  --summary "Reduce signup friction." \
  --tags growth,conversion

python3 codex/wiki/skills/wiki/scripts/wiki_cli.py capture decision \
  --title "Switch to BFF" \
  --summary "Move session ownership to the BFF." \
  --tags auth,architecture \
  --intents signup-speed \
  --tasks owner/repo#18
```

Create an observation linked to current knowledge:

```bash
python3 codex/wiki/skills/wiki/scripts/wiki_cli.py capture observation \
  --title "Webhook Timeout Risk" \
  --summary "External webhooks may exceed request time limits." \
  --tags webhook,reliability \
  --ssot webhook-architecture \
  --tasks owner/repo#42 \
  --affects-paths "src/webhook/**" \
  --search-terms timeout,latency
```

Recall by query, section, exact read, or backlink:

```bash
python3 codex/wiki/skills/wiki/scripts/wiki_cli.py recall auth --stage 1
python3 codex/wiki/skills/wiki/scripts/wiki_cli.py recall auth --stage 2 --section "취지"
python3 codex/wiki/skills/wiki/scripts/wiki_cli.py recall --read auth-architecture,DEC-2026-04-17-143052-switch-to-bff
python3 codex/wiki/skills/wiki/scripts/wiki_cli.py recall --backlinks-of INT-2026-01-10-090000-speed
```

Retire a record:

```bash
python3 codex/wiki/skills/wiki/scripts/wiki_cli.py retire DEC-2026-04-17-143052-old-auth \
  --type superseded \
  --superseded-by DEC-2026-05-01-090000-new-auth
```

Validate consistency or safely refresh derived indexes:

```bash
python3 codex/wiki/skills/wiki/scripts/wiki_cli.py refresh --strict
python3 codex/wiki/skills/wiki/scripts/wiki_cli.py refresh --fix index,retired-in-index
python3 codex/wiki/skills/wiki/scripts/wiki_cli.py refresh --changed-path src/auth/session.ts
```

## Protocol Rules

- `wiki/` is the default vault. Use `--vault <path>` only when the project explicitly stores the vault elsewhere.
- `ssot` and `runbook` are living notes: update them in place and never add `relations`.
- `context/intent`, `context/decision`, `context/rejected_decision`, `context/trial_error`, and `context/observation` are records: preserve old records and supersede or retire them.
- IDs are file basenames. Do not add an `id` frontmatter field.
- `search_terms` is optional and helps recall find a note without becoming a required schema field.
- `affects_paths` is optional on `ssot`, `runbook`, `trial_error`, and `observation`; refresh uses it for `changed-path-stale`.
- Indexes are derived from `summary`; do not edit `## 노트` manually.
- YAML frontmatter relations are canonical. Wikilinks are only human navigation aids.
- `relations.tasks` stores external task IDs such as `owner/repo#18`; the wiki plugin validates format only.
- Obsidian can view the vault, but the AI path is filesystem-only.

For the full design rationale and acceptance criteria, read `references/wiki-protocol.md`.
