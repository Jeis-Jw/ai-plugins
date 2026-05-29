---
title: search_terms recognized optional field
created_at: 2026-05-29
summary: v1 신규: 전 타입 선택 필드. capture 기본 생성 X, refresh 누락 검사 X, recall Stage 1 매칭 O. summary+tags+본문 외 검색 escape hatch.
tags: [wiki, search, v1]
relations:
  intents: [INT-2026-05-29-104707-token-efficient-context-loading]
---

## 결정

`search_terms`를 전 타입에서 허용되는 선택 필드로 둔다. `capture`가 기본 생성하지 않고, `refresh`도 누락을 문제로 보지 않는다. 단, `recall` Stage 1 매칭 표면에는 포함한다.

즉 `search_terms`는 권장/필수 필드가 아니라 검색 누락을 보완하기 위한 recognized optional escape hatch다.

## 취지

기본 검색 표면은 `summary`, `tags`, 본문 ripgrep이다. 대부분의 경우 이 세 가지면 충분하며, 모든 문서에 키워드 필드를 강제하면 작성 부담과 tag 중복이 늘어난다.

하지만 운영 중 특정 용어로 검색이 반복적으로 실패할 수 있으므로, 수동 보정할 수 있는 통로는 남긴다.

## 배경

v1.5 논의에서 `keywords`/`search_terms`를 추가할지 YAGNI인지 의견이 갈렸다. 최종 합의는 메커니즘은 제공하되 작성 의무는 두지 않는 것이다.

이렇게 하면 검색 친화성을 확장할 수 있으면서도 초기 운영 마찰을 만들지 않는다.

## 고려한 대안

- 필수 `keywords` 필드: 모든 문서 작성 부담이 늘어 반려했다.
- 필드 미도입: 검색 누락을 보정할 공식 표면이 없어 반려했다.
- `tags`만 사용: 분류 어휘와 검색 동의어가 섞여 tag 품질이 낮아질 수 있어 보완이 필요했다.

## 트레이드오프

선택 필드이므로 검색 품질이 자동으로 좋아지지는 않는다. 검색 누락 사례를 운영자가 인지하고 수동으로 추가해야 한다.

필드가 남용되면 tags와 중복될 수 있다. `search_terms`는 분류가 아니라 검색 동의어·약어·과거 명칭 보강에만 쓰는 것이 좋다.

## 재평가 조건

운영 데이터상 `search_terms`가 자주 필요하고 누락 비용이 크다면 v2에서 권장 필드 또는 생성 보조 규칙으로 격상할 수 있다.
