---
title: parallel sequential 라벨로 하위 작업 실행 순서 표현
created_at: 2026-06-02
summary: 하위 작업의 병렬/직렬 가능성을 parallel/sequential 라벨로 표시하는 방식. 혼합 DAG를 표현하기 어렵고 GitHub Issue dependencies와 중복되므로 반려.
tags: [task-github, github, dependency, label]
relations:
  intents: [INT-2026-05-29-181219-task-decision-execution-traceability]
---

## 대안

하위 작업 이슈에 `parallel` 또는 `sequential` 라벨을 붙여 형제 sub-issue를 동시에 처리할 수 있는지, 순서대로 처리해야 하는지를 표시한다.

## 반려 사유

병렬/직렬은 이분법이 아니라 DAG다. 예를 들어 A와 B는 병렬 가능하지만 C는 A와 B가 모두 끝난 뒤 시작해야 하는 구조는 단일 라벨로 정확히 표현하기 어렵다. 또한 GitHub에 Issue dependencies가 이미 있으므로 라벨은 GitHub native 관계와 중복된다.

## 이 대안의 취지

작업자가 sub-issue 목록을 볼 때 실행 가능 순서를 빠르게 파악하게 하려는 취지였다. 단순 선형 작업에서는 라벨 방식이 가볍고 직관적일 수 있다.

## 재고 조건

GitHub Issue dependencies를 사용할 수 없는 환경이 장기간 기본값이 되고, fallback 코멘트만으로는 실행 순서를 충분히 보존하지 못할 때 임시 라벨을 다시 검토한다.
