---
title: 컨텍스트 플러그인은 단일 capture audit와 semantic owner로 결합한다
created_at: 2026-08-13
summary: context-core가 SNAP·OBS와 공통 발견·routing·묶음 제안을 소유하고, context-decision 등 addon이 후보를 더 구체적인 의미와 권위로 claim하여 중복 없이 기록한다.
tags: [context-core, context-decision, capture, routing, plugin-architecture]
search_terms: [one auditor many semantic owners, OBS fallback, grouped proposal, capture candidate]
---

## 결정

가칭 context-core를 컨텍스트 생태계의 공통 기반으로 둔다. context-core는 SNAP의 저장·로드·검색, OBS의 기록·읽기·검색·무효화, 세션당 한 번의 durable candidate audit, 설치된 semantic owner로의 routing, 그리고 한 번의 grouped capture proposal을 소유한다. context-decision은 결정 후보를 claim하고 DEC를 결정·취지·반려대안의 원자적 묶음으로 기록하며 scope·supersede·conflict·revisit와 결정 전용 recall을 소유한다. 향후 work·knowledge·docs 계열 addon도 같은 capture candidate 계약을 소비하되 각자의 schema·권위·lifecycle만 소유한다. 사용자 지정 type이 최우선이며, 그다음 설치된 전문 owner가 claim하고, 전문 owner가 없으면서 재사용할 발견·증거인 경우에만 context-core가 OBS로 제안한다. 같은 claim을 OBS와 전문 type에 중복 기록하지 않는다.

## 취지

대화와 작업에서 생기는 중요한 맥락을 플러그인마다 중복 탐색·제안하지 않고 한 번만 발견한 뒤, 설치된 기능에 따라 가장 정확한 의미와 권위로 보존한다. core만으로도 session handoff와 발견 보존이 가능하고 addon을 설치하면 기존 흐름을 깨지 않은 채 분류와 lifecycle이 확장되게 한다.

## 배경

기존 wiki-markdown은 참고용 첫 실험으로 본다. 새 구조의 본질은 모든 context를 하나의 위키 type 체계에 고정하는 것이 아니라 공통 observe/capture 행위와 domain별 semantic ownership을 분리하는 데 있다. SNAP은 세션 handoff용 staging이고 OBS는 재사용 가능한 비권위 evidence다. 모든 context가 OBS인 것은 아니지만 모든 durable context 후보는 한 번의 관찰 과정에서 발견될 수 있다.

## 고려한 대안

1. 단일 wiki 플러그인이 모든 type과 lifecycle을 소유하는 방식은 결합도가 커지고 독립 사용과 확장이 어렵다. 2. 각 addon이 대화를 별도로 audit하는 방식은 중복 제안·토큰 낭비·분류 충돌을 만든다. 3. 모든 후보를 먼저 OBS로 저장한 뒤 승격하는 방식은 동일 claim 중복과 evidence에서 authority로의 암묵적 상승을 만든다. 4. context-core가 전문 plugin의 schema까지 아는 registry 방식은 core를 범용 framework로 비대하게 만든다.

## 트레이드오프

context-core가 통합 audit와 routing의 논리적 의존점이 된다. addon availability를 식별하는 최소 capability 계약과 공통 envelope가 필요하다. core만 설치된 상태에서 결정으로 보이는 내용은 결정 자체가 아니라 결정이 있었다는 비권위 OBS로만 보존하고 kind_hint를 남겨야 한다. 나중에 context-decision이 이를 DEC로 만들 때도 별도 승인이 필요하다. 하나의 발언에서 독립 의미를 가진 OBS·DEC·TASK가 함께 나올 수 있지만 동일 claim의 이중 저장은 금지한다.

## 재평가 조건

context-decision 외 두 번째 addon이 실제 구현될 때 공통 candidate descriptor와 capability discovery 계약을 확정한다. 전문 owner 간 claim 충돌이 반복되거나 grouped proposal이 사용자 판단 비용을 줄이지 못하면 routing 우선순위를 재설계한다. core가 addon schema·workflow를 알기 시작하거나 공통 search가 domain 의미를 침범하면 plugin 경계를 재검토한다.
