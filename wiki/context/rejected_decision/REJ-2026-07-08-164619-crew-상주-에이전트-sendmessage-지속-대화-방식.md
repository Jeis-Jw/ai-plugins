---
title: crew 상주 에이전트(SendMessage 지속 대화) 방식
created_at: 2026-07-08
summary: 팀원을 세션 내 상주 에이전트로 유지하며 SendMessage로 대화를 잇는 방식 — 기각, 소집형 채택.
tags: [studio, multi-agent, token-efficiency]
relations:
  intents: [INT-2026-07-08-164552-studio-살아있는-에이전트-팀]
---

## 대안

crew를 세션 상주 에이전트로 스폰해 두고 SendMessage continuation으로 라운드마다 이어 대화 — 컨텍스트 유지로 토큰 절약을 기대.

## 반려 사유

①LLM API는 무상태 — 상주도 매 추론마다 전체 컨텍스트를 재전송하므로 입력 총량은 fresh와 동일, 차이는 프롬프트 캐시 적중뿐. ②캐시 이득은 브로커 프롬프트를 transcript-first·persona-last·append-only로 배치하면 fresh로도 동일하게 회수된다(캐시는 같은 접두사면 에이전트 간에도 공유, 미팅 턴은 5분 TTL 내 연속). ③상주의 실비용: 세션 사망 시 상태 소실, N개 에이전트 lifecycle 관리, 워크플로 브로커 밖에서만 가능. 상태는 디스크(작업장·notes), 세션은 캐시라는 원칙으로 소집형 확정.

## 이 대안의 취지

매 턴 fresh 스폰의 transcript 재주입이 비효율이라는 직관.

## 재고 조건

워크플로 내에서 서브에이전트 continuation이 지원되고, R>5 장기 리추얼이 실제로 흔해져 중간 합성 압축으로도 비용이 안 잡힐 때.
