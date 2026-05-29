---
title: 5종 record + 2종 living 타입 체계
created_at: 2026-05-29
summary: ssot/runbook(living) + context의 intent/decision/rejected_decision/trial_error/observation(record)으로 분리. fact·pattern·overview·planning은 흡수/이관.
tags: [wiki, taxonomy, architecture]
relations:
  intents: [INT-2026-05-29-104708-atomic-knowledge-records, INT-2026-05-29-104707-token-efficient-context-loading]
---

## 결정

위키 문서 타입은 Living 2종(`ssot`, `runbook`)과 Record 5종(`intent`, `decision`, `rejected_decision`, `trial_error`, `observation`)으로 고정한다. Living은 제자리 갱신되는 현재 정본이고, Record는 불변에 가깝게 쌓인 뒤 필요하면 retire/supersede된다.

`fact`, `pattern`, `overview`, `planning` 같은 별도 타입은 만들지 않는다. 각각은 `ssot`, `trial_error`, 인덱스/README, GitHub 작업관리 또는 운영 모델로 흡수한다.

## 취지

타입 수는 AI가 일관되게 분류할 수 있을 정도로 작아야 하지만, 생명주기가 다른 정보는 섞지 않아야 한다. "지금 어떻게 동작하는가"와 "왜 그렇게 됐는가"를 분리하는 것이 핵심이다.

`observation`은 실행 중 발견했지만 아직 결정이나 교훈으로 분류하기 이른 사실을 담기 위해 추가했다. 이 타입이 없으면 애매한 발견이 decision/trial_error로 과잉 승격되거나 사라진다.

## 배경

초기 구조는 `intent / decision / rejected_decision / trial_error` 중심이었다. 이후 Codex 실행 중 발견되는 리스크, 문서 불일치, flaky 현상처럼 아직 결론이 나지 않은 정보를 안전하게 보존할 통로가 필요하다는 점이 드러났다.

또한 `ssot`와 `runbook`은 장기 record와 다르게 현재 상태를 직접 설명하므로, 같은 lifecycle을 적용하면 정본이 여러 개로 갈라진다.

## 고려한 대안

- 모든 지식을 하나의 `context` record로 통합: 분류 부담은 줄지만 조회와 lifecycle이 흐려져 반려했다.
- `fact`, `pattern`, `overview` 추가: 타입 수가 늘고 기존 타입으로 흡수 가능해 반려했다.
- `observation` 없이 `trial_error`로 흡수: 교훈이 없는 발견까지 trial_error가 되어 의미가 약해져 반려했다.

## 트레이드오프

타입 체계가 작아도 신규 작성자는 분류를 고민해야 한다. 이 부담은 `observation`을 escape hatch로 제공하고, 후속 분류는 retire/supersede로 처리해 줄인다.

Living은 과거 내용을 보존하지 않으므로 히스토리는 git과 관련 record를 통해 추적해야 한다. 대신 현재 정본을 읽는 비용은 낮아진다.

## 재평가 조건

운영 중 `observation`으로도 흡수되지 않는 반복적 정보군이 생기고, 별도 lifecycle과 검증 규칙이 필요해지면 타입 추가를 재검토한다.
