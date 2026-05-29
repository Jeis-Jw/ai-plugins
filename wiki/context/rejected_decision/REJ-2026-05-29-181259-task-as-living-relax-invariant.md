---
title: task를 living으로 두고 living-관계금지 불변식 완화
created_at: 2026-05-29
summary: task를 ssot처럼 living으로 두되 관계를 갖도록 기존 불변식을 완화하는 안 — 핵심 불변식을 훼손하므로 제3 범주 신설이 더 깨끗하여 반려.
tags: [wiki, task, rejected]
relations:
  intents: [INT-2026-05-29-181219-task-decision-execution-traceability]
---

## 대안

`task`를 `ssot`/`runbook`처럼 **living**(제자리 갱신)으로 두되, "living 문서는 `relations` 키를 갖지 않는다"는 불변식을 완화해 task만 예외로 관계를 갖게 한다.

## 반려 사유

위키 그래프의 핵심 불변식(관계는 record만 작성, 허브/living은 백링크로 파생)을 훼손한다. 기존 living(ssot/runbook)의 의미까지 흔들 위험이 있어, 차라리 task를 **별도 제3 범주로 명시 신설**하는 편이 모델이 더 깨끗하다.

## 이 대안의 취지

기존 타입 체계를 최소 변경으로 재사용하려 했다. (→ [[INT-2026-05-29-181219-task-decision-execution-traceability]])

## 재고 조건

제3 범주 도입이 CLI·스키마·문서에 과한 복잡도를 안기는 것으로 드러나면, "living + 관계"를 일반화하는 재정의를 다시 검토한다.
