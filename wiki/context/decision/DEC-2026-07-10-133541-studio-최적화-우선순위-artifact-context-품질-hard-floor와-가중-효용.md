---
title: Studio 최적화 우선순위 — artifact·context 품질 hard floor와 가중 효용
created_at: 2026-07-10
summary: 결과물과 컨텍스트 품질을 각각 hard floor로 보장하고, 통과한 후보만 품질에 최고 비중을 둔 token·elapsed·avoidable owner intervention 가중 효용으로 비교한다.
tags: [studio, quality, context, optimization, plugin-design]
relations:
  intents: [INT-2026-07-08-164552-studio-살아있는-에이전트-팀]
---

## 결정

Studio의 최적화는 2단계로 수행한다. ① artifact quality와 context quality를 독립적인 hard floor로 두고 둘 중 하나라도 required criterion을 충족하지 못하면 완료·통합·비용 최적화 후보에서 제외한다. ② hard floor를 통과한 후보만 quality를 가장 큰 양의 비중으로, token 사용량·elapsed time·불필요한 owner intervention을 비용 항으로 둔 가중 효용으로 비교한다. QualityPlan은 실행 전에 결과물 기준·컨텍스트 기준·필수 evidence를 고정하고, 완료 판정은 실제 verification과 source anchor를 요구한다. Owner gate 자체는 비용으로 벌점화하지 않으며, 계약상 불필요했던 질문·재확인만 avoidable intervention으로 계측한다.

## 취지

Studio의 팀 상호작용이 토큰을 많이 쓰는 연극이 아니라 실제 결과물과 재사용 가능한 맥락의 품질 향상으로 이어지게 한다. 품질 미달을 싼 실행으로 상쇄하지 못하게 하면서, 같은 품질 수준에서는 토큰·대기·owner 개입을 줄이는 방향으로 운영한다.

## 배경

기존 품질 체계는 critic, delta anchor, baseline 비교로 허위 품질 신호를 차단했지만, 결과물 품질과 다음 run에 전달되는 컨텍스트 품질을 별도 완료조건으로 표현하지 않았고 비용·시간·개입의 우선순위도 명시하지 않았다. Context Kernel과 외부 executor를 도입하면 실행 경로마다 비용 특성이 달라지므로 비교 가능한 우선순위 계약이 필요하다. 기존 DEC-2026-07-08-164718의 evidence 기반 판정과 owner gate를 유지하면서 최적화 목적함수를 보완한다.

## 고려한 대안

비용 또는 토큰 최소화를 최우선으로 두는 안은 싼 품질 미달 실행을 선택할 수 있어 기각했다. elapsed time을 최우선으로 두는 안은 검증·맥락 회수를 생략하도록 유도해 기각했다. 모든 항목을 처음부터 단일 점수로 합치는 안은 낮은 품질이 낮은 비용으로 상쇄될 수 있어 기각했다. 품질만 보고 비용을 계측하지 않는 안은 품질 동률 구간에서 반복 실행과 owner 개입 낭비를 제어하지 못해 채택하지 않았다.

## 트레이드오프

QualityPlan 작성과 evidence 수집 비용이 추가되고, artifact/context 품질 척도 및 가중치는 도메인별 보정이 필요하다. hard floor가 과도하면 탐색형 run을 조기에 차단할 수 있으므로 발산 단계와 완료·통합 단계의 기준을 구분해야 한다. avoidable intervention 판정은 자의적일 수 있어 계약상 필수 gate와 운영상 재질문을 명확히 분리해야 한다.

## 재평가 조건

artifact/context quality floor가 실제 downstream 결함이나 재작업을 예측하지 못하는 사례가 누적되면 기준과 evidence를 재설계한다. QualityPlan 작성·검증 오버헤드가 소형 mission 비용을 지배하면 gear별 축약 프로필을 도입한다. 토큰·시간·owner 개입 가중치가 품질 통과 후보의 선택을 반복적으로 왜곡하면 가중치와 정규화를 조정하되 hard floor는 별도로 유지한다.
