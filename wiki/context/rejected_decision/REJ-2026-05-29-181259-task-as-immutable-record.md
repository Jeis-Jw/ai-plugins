---
title: task를 불변 record로 모델링
created_at: 2026-05-29
summary: task를 다른 record처럼 불변으로 두고 진행은 연결된 이슈에서만 본다 — 독립 사용 시 문서 내 상태 가시성이 없고 상태 변경마다 supersede가 비현실적이라 반려.
tags: [wiki, task, rejected]
relations:
  intents: [INT-2026-05-29-181219-task-decision-execution-traceability]
---

## 대안

`task`를 `decision`/`observation`처럼 **불변(record)** 으로 둔다. 캡처 시점에 요약·근거·이슈 링크를 고정하고, 이후 진행 상황은 연결된 이슈에서만 확인한다. task 문서 자체는 수정하지 않는다.

## 반려 사유

작업 플러그인 없이 위키만 쓸 때 **문서 안에서 진행/완료 여부를 볼 수 없다**(위키 자립성 위배). 또 상태가 바뀔 때마다 supersede로 새 record를 만들어야 해 `retired/`에 옛 버전이 쌓이고 비현실적이다.

## 이 대안의 취지

record 불변성으로 감사 추적성과 모델 단순성을 지키려 했다. (→ [[INT-2026-05-29-181219-task-decision-execution-traceability]])

## 재고 조건

작업 진행 상태를 위키에서 추적할 필요가 전혀 없고(완전히 외부 트래커에만 의존), task가 순수 감사 기록으로만 쓰인다면 불변 record가 다시 후보가 된다.
