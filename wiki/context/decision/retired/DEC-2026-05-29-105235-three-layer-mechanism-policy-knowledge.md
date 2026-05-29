---
title: CLAUDE.md/rules 3계층 분리 (v0)
created_at: 2026-05-29
summary: v0 시점 결정: 메커니즘=플러그인 rules, 정책=프로젝트 CLAUDE.md, 지식=wiki/ 3계층. 플러그인 이동성 확보가 목표.
tags: [wiki, layering, v0]
relations:
  intents: [INT-2026-05-29-104708-atomic-knowledge-records, INT-2026-05-29-104711-plugin-agent-neutrality]
retired_at: 2026-05-29
retired_type: superseded
superseded_by: DEC-2026-05-29-105318-four-layer-separation
---

## 결정

v0에서는 위키 시스템을 세 계층으로 분리했다. Mechanism은 플러그인 rules와 CLI, policy는 프로젝트 `CLAUDE.md`, knowledge는 `wiki/`에 축적되는 실제 문서였다.

이 결정은 플러그인 이동성과 프로젝트별 운영 규칙 분리를 목표로 했다.

## 취지

플러그인이 특정 프로젝트의 운영 정책을 끌고 다니지 않게 하고, 지식 저장소와 메커니즘을 분리하려는 의도였다. 안정 자산과 변동 자산을 나누는 방향 자체는 맞았다.

## 배경

초기에는 agent entry 파일인 `CLAUDE.md`가 프로젝트 운영 정책을 담는 자연스러운 위치로 보였다. 실제 agent가 시작할 때 읽는 파일이기 때문이다.

이후 운영 정책도 장기적으로 추적·검증되어야 하는 정본이라는 점이 드러났다.

## 고려한 대안

- 모든 규칙을 plugin spec에 포함: 프로젝트별 차이를 흡수하지 못해 반려했다.
- 모든 규칙을 `CLAUDE.md`에 포함: plugin 메커니즘과 정책이 분리되지 않아 이후 v1에서 대체했다.

## 트레이드오프

3계층은 단순하지만 `CLAUDE.md`가 policy 정본이 되어 변경 빈도가 다른 내용이 agent entry에 직접 쌓였다. 이로 인해 agent별 규칙과 plugin mechanism의 경계가 흐려졌다.

## 재평가 조건

이 결정은 [[DEC-2026-05-29-105318-four-layer-separation]]로 superseded되었다. 현재는 mechanism/policy/agent entry/knowledge 4계층을 따른다.
