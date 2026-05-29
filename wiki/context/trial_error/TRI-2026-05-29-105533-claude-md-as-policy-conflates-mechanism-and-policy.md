---
title: CLAUDE.md에 운영 정책을 직접 적으면 mechanism과 policy가 섞인다
created_at: 2026-05-29
summary: v0의 3계층은 mechanism=plugin, 정책=CLAUDE.md, 지식=wiki. 그러나 CLAUDE.md에 정책을 직접 적으면 변경 빈도가 다른 두 자산이 한 파일에 섞임. v1은 정책을 wiki/ssot/agent-operating-model.md로 분리하고 CLAUDE.md를 그 ssot로의 포인터(agent entry)로 격하.
tags: [wiki, layering, lesson]
verified_at: 2026-05-29
relations:
  decisions: [DEC-2026-05-29-105318-four-layer-separation]
---

## 교훈

CLAUDE.md/AGENTS.md 같은 에이전트 진입점 파일은 **정책 자체**가 아니라 *정책 ssot로의 포인터*여야 한다. 정책 자체를 그 안에 적으면 변경 빈도가 다른 두 자산(안정 plugin 메커니즘 + 변동 운영 정책)이 한 파일에 묶여 함께 흔들린다.

## 상황

v0 §15는 mechanism=plugin / 정책=CLAUDE.md / 지식=wiki 의 3계층 분리를 제시. 그러나 CLAUDE.md에 "지식은 wiki/, 결정 전 조회, 결정·취지·반려·시행착오 기록, 위키 프로토콜 준수" 같은 정책을 직접 적도록 권장 → CLAUDE.md가 정책 정본이 됨. 정책 진화 시 위키가 추적하지 않음(dogfooding 깨짐).

## 피해야 할 것

- 운영 정책(역할 분리, leaf issue 규약, PR 리뷰 흐름, capture 권한)을 CLAUDE.md/AGENTS.md 본문에 직접 적기.
- agent별 도구 이름(Claude/Codex/Cursor)을 plugin 메커니즘 영역(CLI, frontmatter 스키마, 알고리즘)에 박기.

## 대안 또는 우회

- **mechanism/policy/agent entry/knowledge 4계층 분리** ([[DEC-2026-05-29-105318-four-layer-separation]]):
  - mechanism = plugin rules + spec ssot
  - policy = `wiki/ssot/agent-operating-model.md` (정본)
  - agent entry = CLAUDE.md/AGENTS.md (정책 ssot로의 짧은 포인터)
  - knowledge = wiki/* (실제 축적 내용)
- 정책 ssot를 wiki 안에 두면 운영 정책 진화도 위키 supersede/verified_at/refresh 메커니즘 안으로 들어옴 (dogfooding 회복).

## 현재도 유효한가

유효. 새 agent 도구 추가(Codex, Cursor, Cline 등) 시 plugin 메커니즘은 변경 없음. 운영 정책만 `agent-operating-model.md`에서 갱신.

