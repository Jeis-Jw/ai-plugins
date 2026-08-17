---
schema: "context-decision/v1"
id: "ctx_6c1aee43e3cb400ab76dc79d0f2004fd"
title: "CLAUDE.md/rules 3계층 분리 (v0)"
summary: "v0 시점 결정: 메커니즘=플러그인 rules, 정책=프로젝트 CLAUDE.md, 지식=wiki/ 3계층. 플러그인 이동성 확보가 목표."
created_at: "2026-08-15T02:52:30+09:00"
captured_from: "import"
source_refs: ["file:wiki/context/decision/retired/DEC-2026-05-29-105235-three-layer-mechanism-policy-knowledge.md"]
tags: ["wiki","layering"]
scope: "ai-plugins/wiki-markdown"
decision_key: "agent-policy-layering"
revisit_when: ["이 결정은 [[DEC-2026-05-29-105318-four-layer-separation]]로 superseded되었다. 현재는 mechanism/policy/agent entry/knowledge 4계층을 따른다."]
---

## 결정

v0 시점 결정: 메커니즘=플러그인 rules, 정책=프로젝트 CLAUDE.md, 지식=wiki/ 3계층. 플러그인 이동성 확보가 목표.

## 취지

플러그인이 특정 프로젝트의 운영 정책을 끌고 다니지 않게 하고, 지식 저장소와 메커니즘을 분리하려는 의도였다. 안정 자산과 변동 자산을 나누는 방향 자체는 맞았다.

## 반려대안

- 모든 규칙을 plugin spec에 포함: 프로젝트별 차이를 흡수하지 못해 반려했다.
- 모든 규칙을 `CLAUDE.md`에 포함: plugin 메커니즘과 정책이 분리되지 않아 이후 v1에서 대체했다.

## 트레이드오프

- 3계층은 단순하지만 `CLAUDE.md`가 policy 정본이 되어 변경 빈도가 다른 내용이 agent entry에 직접 쌓였다. 이로 인해 agent별 규칙과 plugin mechanism의 경계가 흐려졌다.

## 재평가 조건

- 이 결정은 [[DEC-2026-05-29-105318-four-layer-separation]]로 superseded되었다. 현재는 mechanism/policy/agent entry/knowledge 4계층을 따른다.
