---
title: plugin spec에 agent 이름(Claude/Codex) 침투
created_at: 2026-05-29
summary: CLI 인자/스키마/알고리즘 출력에 Claude/Codex 같은 특정 도구 이름 박는 안. 미래 도구 호환성 깨짐. agent별 규약은 operating model로 격리해 반려.
tags: [wiki, plugin, rejected]
---

## 대안

Plugin spec, CLI, schema, 알고리즘 출력에 Claude/Codex 같은 agent 이름을 직접 넣는 방식이다. 예를 들어 "Codex는 OBS만 capture" 같은 운영 규칙을 plugin mechanism에 포함하는 접근이다.

## 반려 사유

Agent 이름은 프로젝트와 시점에 따라 바뀌는 운영 정책이다. 이를 plugin schema나 CLI 계약에 넣으면 새로운 도구를 도입하거나 역할을 바꿀 때 메커니즘까지 수정해야 한다.

Plugin은 어떤 agent가 쓰든 같은 타입·관계·검증 규칙을 제공해야 한다. Agent별 운영은 `agent-operating-model.md`에 둔다.

## 이 대안의 취지

실제 운영에서 Claude/Codex 역할 분리가 중요했기 때문에, 이를 명시해 agent 오작동을 줄이려는 목적이었다. 작업 실행 중 decision capture 권한을 제한하려는 실용적 이유도 있었다.

## 재고 조건

특정 agent 전용 기능이 도저히 일반화할 수 없고 core plugin 동작에 필수라면 adapter나 policy wrapper로 제공한다. core plugin spec에는 agent 이름을 넣지 않는다.
