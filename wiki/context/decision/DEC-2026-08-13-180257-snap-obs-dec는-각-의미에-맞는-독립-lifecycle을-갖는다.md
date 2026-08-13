---
title: SNAP OBS DEC는 각 의미에 맞는 독립 lifecycle을 갖는다
created_at: 2026-08-13
summary: SNAP은 현재 handoff를 제자리 갱신 후 discard하고, OBS와 DEC는 의미 불변 record로서 같은 claim의 대체나 명시적 무효화 때만 retired로 전이한다.
tags: [context-core, context-decision, lifecycle, snapshot, observation, decision]
search_terms: [snapshot discard, observation invalidated, decision superseded, semantic claim, artifact lifecycle]
---

## 결정

SNAP은 graph authority가 아닌 현재 session handoff staging으로서 같은 artifact를 제자리 갱신하고 열린 논의가 모두 흡수되면 discard하며 archive나 promoted 상태를 두지 않는다. OBS는 비권위 evidence record이고 DEC는 결정·취지·반려대안의 권위 record이며, 두 타입 모두 semantic claim을 제자리에서 바꾸지 않는다. 같은 claim을 새 artifact가 인수하면 superseded로, 더는 유효하지 않으나 successor가 없으면 OBS는 invalidated, DEC는 withdrawn으로 retired 전이한다. 단순히 오래된 것은 상태 전이가 아니라 freshness 경고다. SNAP·OBS에서 다른 산출물이 나왔다는 사실만으로 원천 artifact를 종료하지 않으며 동일 claim을 인수했을 때만 supersede한다.

## 취지

임시 handoff, 비권위 evidence, 권위 결정의 의미 차이를 보존하면서 불필요한 상태와 자동 승격을 만들지 않는다.

## 배경

기존 wiki-markdown은 SNAP을 update-in-place+discard staging으로, OBS와 DEC를 active/retired record로 다룬다. 새 구조는 이 강점을 유지하되 OBS의 무효와 DEC의 철회를 domain 언어로 구분한다.

## 고려한 대안

모든 artifact에 current·archived·promoted 상태를 공통 적용하는 방식은 의미가 다른 lifecycle을 억지로 통합하므로 반려한다. SNAP archive는 Git 이력 및 생성된 정식 artifact와 중복되어 v1에서 반려한다. 모든 OBS를 DEC 생성 시 자동 retire하는 방식은 evidence와 choice를 혼동하므로 반려한다.

## 트레이드오프

artifact별 retire reason과 validation이 필요하다. 대신 recall은 권위와 현재성을 정확히 표현할 수 있고 addon이 core의 공통 status enum에 종속되지 않는다.

## 재평가 조건

Git이 없는 저장 환경에서 snapshot 이력 요구가 반복되거나 OBS·DEC 외 여러 owner가 동일 retire semantics를 실제로 공유하게 되면 공통 lifecycle primitive를 추출한다.
