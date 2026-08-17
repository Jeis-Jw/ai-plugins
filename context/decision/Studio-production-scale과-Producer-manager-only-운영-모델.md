---
schema: "context-decision/v1"
id: "ctx_24769192f0f94a7b9354493eac3f2e19"
title: "Studio production scale과 Producer manager-only 운영 모델"
summary: "Producer는 항상 manager로 남고 backlog item별 production scale이 제작 crew·ritual·rounds·critic을 정하며 verification independence·task gear·parallelism은 직교한다."
created_at: "2026-08-15T02:52:30+09:00"
captured_from: "import"
source_refs: ["file:wiki/context/decision/retired/DEC-2026-07-26-031028-studio-production-scale과-producer-manager-only-운영-모델.md"]
tags: ["studio","producer"]
scope: "ai-plugins/studio"
decision_key: "production-scale-model"
revisit_when: ["static 분류가 반복적으로 잘못되어 quality floor 미달이나 불필요한 multi-role 호출을 만들면 admission signal과 triage run을 재설계한다. criterion source와 기계적 measure가 없는 item은 solo 1회 비용 주장의 대상에서 제외하고 정의 crew 1회 + 실행 crew 1회로 계측한다."]
---

## 결정

Producer는 항상 manager로 남고 backlog item별 production scale이 제작 crew·ritual·rounds·critic을 정하며 verification independence·task gear·parallelism은 직교한다.

## 취지

Owner가 상위 mission만 주면 Studio 내부에서 필요한 일을 정의하고 적절한 조직 형태를 선택해 끝까지 완주하게 한다. 살아있는 상호작용은 목적이 아니라 evidence-bearing delta를 만드는 품질 수단이다. 추가 관점이 결과를 바꾸지 못하는 item에는 solo production을 선택해 작은 일도 Studio 안에서 과도한 리추얼 없이 처리한다. Producer가 직접 작업하거나 Owner에게 routine routing을 돌려주는 우회는 허용하지 않는다.

## 반려대안

- 소형 작업을 Studio 밖에서 직접 처리하는 안은 mission 안에서 일의 정의가 일어난다는 취지를 깨므로 기각했다. 소형을 task-github micro로 보내는 안은 Studio를 대형 전용 상위 레이어로 쪼개고 optional tool에 핵심 routing을 의존시켜 기각했다. Producer가 micro 작업을 직접 처리하는 안은 manager-only hard invariant를 깨므로 기각했다. track 전체에 하나의 scale을 주는 안은 가장 큰 item의 profile을 작은 item에 전파해 현재 낭비를 재현하므로 기각했다. reviewer를 production cast에 넣는 안은 scale과 delivery/review 축을 결합하므로 verification edge로 분리했다.

## 재평가 조건

- static 분류가 반복적으로 잘못되어 quality floor 미달이나 불필요한 multi-role 호출을 만들면 admission signal과 triage run을 재설계한다. criterion source와 기계적 measure가 없는 item은 solo 1회 비용 주장의 대상에서 제외하고 정의 crew 1회 + 실행 crew 1회로 계측한다.
