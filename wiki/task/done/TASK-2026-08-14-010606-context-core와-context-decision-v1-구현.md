---
title: context-core와 context-decision v1 구현
created_at: 2026-08-14
summary: filesystem·Markdown 기반 context-core와 수동 core 의존 context-decision의 Phase 0~5 구현·검증을 단일 계약과 acceptance gate로 완료한다.
tags: [context-core, context-decision, v1, implementation, acceptance]
relations:
  ssot: [context-v1-implementation, context-core-plugin, context-decision-plugin, context-storage-retrieval]
  decisions: [DEC-2026-08-13-233319-context-decision은-context-core를-사용자가-직접-설치한-뒤에만-동작한다]
---

## 개요

Phase 0~5로 context-core와 context-decision v1을 구현한다. Phase 0은 Codex·Claude Code owner discovery, exact plugin inventory·doctor handshake, index/Unicode/lock·crash mechanism spike다. Phase 1은 stdlib-only context-common storage/index/recall/coordinator/CLI, Phase 2는 SNAP·OBS owner, Phase 3은 DEC owner, Phase 4는 audit·routing·grouped approval, Phase 5는 양 host manifest·README·demo·package proof다. context-core는 유일한 physical writer와 root/SNAP/OBS owner이고 context-decision은 DEC semantic owner이며 filesystem을 직접 쓰지 않는다.

## 근거

구현 정본은 context-v1-implementation과 context-core-plugin/context-decision-plugin/context-storage-retrieval이다. context-decision은 marketplace=jeis-ai-plugins, plugin=context-core, selector=context-core@jeis-ai-plugins, source=Jeis-Jw/ai-plugins의 manual hard dependency다. schema/capabilities 외 operation은 exact source·enabled·context-common/v1·doctor repository_state=ready를 read-only preflight하며 core_missing, core_source_mismatch, core_disabled, core_incompatible, core_uninitialized, partial_core_init에서 repository·host configuration write 0으로 fail-closed한다. native dependency, 자동 install/enable/update, 내장 core와 cache-path 추측은 금지한다.

## 범위와 완료 기준

산출물은 두 plugin의 manifest/skills/stdlib CLI/templates/tests, 하나의 host-independent protocol fixture, deterministic index·transaction·lifecycle·routing contracts, README/demo와 package validation이다. acceptance는 init idempotence, index-first Stage 1 I-O budget, SNAP·OBS·DEC lifecycle/slot/conflict, preview+exact digest apply, crash resume·strict integrity, 양 host portability, manual dependency 오류 matrix와 distribution metadata 0을 포함한다. release gate는 strict integrity, fixture matrix, token/I-O evidence 및 product flow proof다. 기존 wiki 자동 migration, vector/DB/daemon, generic addon SDK, 자동 semantic conflict 판정, PCMS sync/control plane은 범위 밖이다. 이 root TASK는 DefinitionArtifact와 후속 leaf binding 전의 work order일 뿐 세부 leaf TASK를 만들지 않는다. GitHub Issue/PR, publish, release, push는 이 작업 범위에서 수행하지 않는다.

### 완료 기록

2026-08-14에 main `7db74d6b893aed11fbec970cf4bc00dbd76804b9`를 기준으로 task-worker root run `run-5c35e07309b7-f0975b827bc5`가 `closed`로 종료됐다. supplemental QA `.task-worker/local/evidence/context-v1-supplemental-root-qa-7db74d6b893a.json`은 16/16 profile 통과, 193 test invocation, acceptance 43/43을 기록한다. session-review round 2는 `approved`, blocking 0이며 receipt는 `.task-worker/local/evidence/context-v1-session-review-receipt.json`이다. GitHub Issue/PR, push, publish, release는 수행하지 않았다.

이 완료 판정은 fixture·static contract·현재 macOS local runtime 검증 범위다. Claude Code live plugin inventory, Linux runtime, 실제 설치된 Codex `context-core` live operational path는 미검증으로 남기며 dual-host live 완료로 판정하지 않는다.
