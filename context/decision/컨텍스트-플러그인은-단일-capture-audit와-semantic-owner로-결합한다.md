---
schema: "context-decision/v1"
id: "ctx_12a55ba002784ed0b7f0d9679b657c69"
title: "컨텍스트 플러그인은 단일 capture audit와 semantic owner로 결합한다"
summary: "context-core가 SNAP·OBS와 공통 발견·routing·묶음 제안을 소유하고, context-decision 등 addon이 후보를 더 구체적인 의미와 권위로 claim하여 중복 없이 기록한다."
created_at: "2026-08-15T02:52:30+09:00"
captured_from: "import"
source_refs: ["file:wiki/context/decision/retired/DEC-2026-08-13-164257-컨텍스트-플러그인은-단일-capture-audit와-semantic-owner로-결합한다.md"]
tags: ["context-core","context-decision"]
scope: "ai-plugins/context"
decision_key: "owner-coordinator-boundary"
revisit_when: ["context-decision 외 두 번째 addon이 실제 구현될 때 공통 candidate descriptor와 capability discovery 계약을 확정한다. 전문 owner 간 claim 충돌이 반복되거나 grouped proposal이 사용자 판단 비용을 줄이지 못하면 routing 우선순위를 재설계한다."]
---

## 결정

context-core가 SNAP·OBS와 공통 발견·routing·묶음 제안을 소유하고, context-decision 등 addon이 후보를 더 구체적인 의미와 권위로 claim하여 중복 없이 기록한다.

## 취지

대화와 작업에서 생기는 중요한 맥락을 플러그인마다 중복 탐색·제안하지 않고 한 번만 발견한 뒤, 설치된 기능에 따라 가장 정확한 의미와 권위로 보존한다. core만으로도 session handoff와 발견 보존이 가능하고 addon을 설치하면 기존 흐름을 깨지 않은 채 분류와 lifecycle이 확장되게 한다.

## 반려대안

- 단일 wiki 플러그인이 모든 type과 lifecycle을 소유하는 방식은 결합도가 커지고 독립 사용과 확장이 어렵다. 2. 각 addon이 대화를 별도로 audit하는 방식은 중복 제안·토큰 낭비·분류 충돌을 만든다. 3. 모든 후보를 먼저 OBS로 저장한 뒤 승격하는 방식은 동일 claim 중복과 evidence에서 authority로의 암묵적 상승을 만든다. 4. context-core가 전문 plugin의 schema까지 아는 registry 방식은 core를 범용 framework로 비대하게 만든다.

## 트레이드오프

- context-core가 통합 audit와 routing의 논리적 의존점이 된다. addon availability를 식별하는 최소 capability 계약과 공통 envelope가 필요하다. core만 설치된 상태에서 결정으로 보이는 내용은 결정 자체가 아니라 결정이 있었다는 비권위 OBS로만 보존하고 kind_hint를 남겨야 한다.

## 재평가 조건

- context-decision 외 두 번째 addon이 실제 구현될 때 공통 candidate descriptor와 capability discovery 계약을 확정한다. 전문 owner 간 claim 충돌이 반복되거나 grouped proposal이 사용자 판단 비용을 줄이지 못하면 routing 우선순위를 재설계한다.
