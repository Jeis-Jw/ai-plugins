---
title: gate MVP를 LLM-judge로 먼저 구축
created_at: 2026-06-12
summary: 품질 gate MVP를 의미판정 LLM-judge로 우선 구축하는 안. in-stack judge 천장·판정 불안정·prompt 의존으로 반려, 정적 룰 v0를 먼저.
tags: [plugin, quality, gate]
relations:
  intents: [INT-2026-05-29-104710-ai-driven-documentation]
---

## 대안

품질 gate의 MVP를 정적 룰이 아니라 의미판정 LLM-judge로 먼저 구축한다 — decision 타당성과 분해 MECE/altitude를 모델이 평가해 저품질을 걸러낸다.

## 반려 사유

운영 에이전트와 같은 스택으로 judge를 짜면 generator와 **blind spot을 공유**한다. generator가 체계적으로 틀리는 설계는 같은 모델의 judge도 통과시킨다(검증<생성 비대칭으로 일부는 잡지만 체계적 오류는 못 잡음). 또 LLM-judge는 판정 불안정 · prompt 품질 의존 · "그럴듯한 PASS" 위험이 있다. 반면 정적 룰은 결정적 · 저렴하고 구조적 결함(빈 근거 · 반려대안 0 · 완료기준 누락 · 범위 겹침)의 다수를 천장 없이 잡는다. 그래서 MVP는 정적 룰이 먼저고, LLM-judge는 v1로 미룬다.

## 이 대안의 취지

의미적으로 약한 결정·분해를 최대한 자동으로 잡아 사람 확인 비용을 줄이려는 것([[INT-2026-05-29-104710-ai-driven-documentation]]). 취지 자체는 유효하나, MVP 단계에서는 정적 룰이 더 안전하게 그 취지를 섬긴다.

## 재고 조건

다양성 판사(역할·context 분리, generator reasoning 미주입) · 정적 룰 병용 · evidence-first 판정(근거 인용 없는 PASS는 실패 처리) · calibration corpus(좋은/나쁜 결정·분해 fixture)로 in-stack 천장과 불안정을 충분히 낮출 수 있을 때, v1에서 LLM-judge를 FLAG-to-human으로 도입한다.
