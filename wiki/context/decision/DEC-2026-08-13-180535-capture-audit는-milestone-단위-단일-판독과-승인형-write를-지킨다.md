---
title: capture audit는 milestone 단위 단일 판독과 승인형 write를 지킨다
created_at: 2026-08-13
summary: semantic milestone 또는 closeout마다 현재 대화를 한 번만 감사하고 축약 candidate를 semantic owner에 전달하며 모든 durable write는 grouped proposal 승인 뒤에만 수행한다.
tags: [context-core, capture, routing, approval, token-efficiency]
search_terms: [one audit, semantic milestone, grouped proposal, approval gate, token budget, owner reread]
---

## 결정

context-core의 capture audit는 의미 있는 결정 시점 또는 closeout마다 최대 한 번 수행한다. 현재 대화는 auditor만 판독하고 addon semantic owner에는 축약된 candidate만 전달하며 addon이 원문을 다시 감사하지 않는다. 후보는 ephemeral이고 사용자에게 하나의 grouped proposal로 제시한다. 명시적 기록 요청이나 proposal 승인 전에는 SNAP·OBS·DEC를 포함한 durable write를 하지 않으며, core-only OBS fallback에서 DEC로의 이관도 별도 승인 없이 자동 수행하지 않는다.

## 취지

플러그인이 늘어나도 대화 재판독과 제안 횟수가 비례해 증가하지 않게 하고, 사용자가 저장할 맥락과 권위 상승을 통제하게 한다.

## 배경

세션당 한 번이라는 표현은 긴 세션의 중간 milestone을 놓칠 수 있고 addon별 탐색은 토큰과 중복 제안을 증가시킨다. 기존 wiki의 승인형 capture 강점과 one auditor-many owners 구조를 구현 계약으로 결합한다.

## 고려한 대안

세션 종료 때만 감사하는 방식은 긴 작업의 의미적 중간 산출물을 놓쳐 반려한다. 각 addon이 원문을 따로 읽는 방식은 비용과 분류 충돌 때문에 반려한다. 자동 write와 자동 promotion은 권위 오염 때문에 반려한다.

## 트레이드오프

agent policy 기반 감사 시점 선택은 완전한 hard guarantee가 아니다. 대신 runtime hook과 activity heuristic을 피하고 budget과 결과를 측정해 개선한다.

## 재평가 조건

누락률이나 중복 감사율이 허용 수준을 넘고 host가 안전한 semantic event surface를 제공하면 감사 trigger를 재검토한다.
