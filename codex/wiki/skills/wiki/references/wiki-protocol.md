# AI-Native Wiki Protocol

This reference condenses the implementation contract from `wiki/ssot/plugin_definition_v1.md`.

## Purpose

The wiki is the project's knowledge source of truth for AI agents. It stores current design state, operational procedures, durable intents, decisions, rejected alternatives, lessons, and observations so an agent can read minimal valid context before acting.

## Vault

- Default vault path: `wiki/`.
- Root index: `wiki/README.md`.
- Folder indexes: `<folder>/<folder-name>.md`, for example `wiki/ssot/ssot.md`.
- `ssot/` and `runbook/` may contain nested folders. Each folder index lists only direct child notes.
- Indexes are derived from note frontmatter `summary`.

## Types

- `ssot`: living current truth. File name is `<slug>.md`.
- `runbook`: living procedure. File name is `<slug>.md`.
- `context/intent`: record intent. ID format `INT-YYYY-MM-DD-HHMMSS-<slug>`.
- `context/decision`: record decision. ID format `DEC-YYYY-MM-DD-HHMMSS-<slug>`.
- `context/rejected_decision`: record rejected alternative. ID format `REJ-YYYY-MM-DD-HHMMSS-<slug>`.
- `context/trial_error`: record trap or lesson. ID format `TRI-YYYY-MM-DD-HHMMSS-<slug>`.
- `context/observation`: record observation that is not ready to classify as a decision, lesson, or living note. ID format `OBS-YYYY-MM-DD-HHMMSS-<slug>`.

Living notes are updated in place. Records are immutable in meaning and are retired or superseded.

## Frontmatter

Common fields:

```yaml
---
title: ...
created_at: 2026-05-28
summary: ...
tags: [...]
audience: [human, agent]
search_terms: [...]
---
```

Rules:

- No `id` field; basename is the ID.
- No `status` field; active/retired is represented by path.
- `search_terms` is optional and participates in Stage 1 recall.
- `verified_at` is allowed on `ssot`, `runbook`, `trial_error`, and `observation`.
- `affects_paths` is allowed on `ssot`, `runbook`, `trial_error`, and `observation`.
- Lifecycle fields are top-level: `supersedes`, `superseded_by`, `retired_at`, `retired_type`.
- `retired_type` is only `deprecated` or `superseded`.
- `relations` is allowed only on record types that write low-cardinality links.

## Relations

Canonical relations are YAML plain IDs, not body wikilinks.

- `decision.relations.intents`: winning intents.
- `decision.relations.rejected_decisions`: rejected alternatives related to the decision.
- `decision.relations.ssot`: impacted living SSOT note IDs.
- `decision.relations.tasks`: external task references.
- `rejected_decision.relations.intents`: losing intent served by the rejected alternative.
- `trial_error.relations.decisions`: related decisions.
- `trial_error.relations.tasks`: external task references.
- `observation.relations.ssot`: related SSOT notes.
- `observation.relations.runbook`: related runbooks.
- `observation.relations.decisions`: related decisions.
- `observation.relations.tasks`: external task references.

Hubs (`intent`, `ssot`, `runbook`) never store backlinks. Backlinks are derived by scanning record frontmatter.

## Sections

- `intent`: `## 취지`, `## 배경`
- `decision`: `## 결정`, `## 취지`, `## 배경`, `## 고려한 대안`, `## 트레이드오프`, `## 재평가 조건`
- `rejected_decision`: `## 대안`, `## 반려 사유`, `## 이 대안의 취지`, `## 재고 조건`
- `trial_error`: `## 교훈`, `## 상황`, `## 피해야 할 것`, `## 대안 또는 우회`, `## 현재도 유효한가`
- `observation`: `## 관찰`, `## 근거`, `## 영향`, `## 현재 처리`, `## 후속 분류 조건`
- `ssot`: `## 현재 상태`, `## 취지`, `## 구성요소`
- `runbook`: `## 목적`, `## 절차`, `## 주의점`

## Lifecycle

Active records live in their type folder. Retired records move to `retired/`.

`retired_type` is:

- `deprecated`: wrong or no longer valid.
- `superseded`: valid at the time but replaced by a newer record.

Supersede stores both sides:

- New record top-level `supersedes: [old-id]`.
- Old record top-level `superseded_by: new-id`, `retired_at`, and `retired_type: superseded`.

Observation uses the same two-value lifecycle. If an observation leads to a trial error, decision, or another observation, retire it as `superseded` with that successor as the primary replacement.

## CLI Contract

The bundled CLI supports:

- `init`: create the vault structure and derived indexes, including `context/observation`.
- `capture`: create a note, resolve friendly refs to basenames, validate task refs, validate v1 field scopes, and refresh indexes.
- `retire`: retire or supersede context records and refresh indexes.
- `recall`: Stage 1 summaries, Stage 2 sections, Stage 3 full reads, batch `--read a,b,c`, and derived backlinks.
- `refresh`: report integrity issues. With `--strict`, exit `6` when issues exist. `--fix` accepts only `index` and `retired-in-index`.

Refresh checks include:

- `stale`
- `supersede`
- `broken-rel`
- `task-ref`
- `orphan`
- `index`
- `retired-in-index`
- `active-ref-retired`
- `tags`
- `changed-path-stale`
- `duplicate-basename`
- `empty-lesson`

Exit codes:

- `0`: success.
- `2`: argument or usage error.
- `3`: vault missing.
- `4`: validation failure such as missing or ambiguous refs.
- `5`: living note slug already exists.
- `6`: strict refresh found issues.

## Deferred

`promote` and `sandbox save/load` remain deferred by the v1 design. Sandbox files are outside the canonical graph until explicitly promoted.
