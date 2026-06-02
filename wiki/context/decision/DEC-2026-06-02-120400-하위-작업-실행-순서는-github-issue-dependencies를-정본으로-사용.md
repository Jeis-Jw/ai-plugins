---
title: 하위 작업 실행 순서는 GitHub Issue dependencies를 정본으로 사용
created_at: 2026-06-02
summary: sub-issue는 작업 분해 구조만 표현하고, 하위 작업의 선후관계와 blocked 상태는 GitHub Issue dependencies의 blocked_by/blocking 관계를 정본으로 사용한다.
tags: [task-github, github, dependency, workflow]
relations:
  intents: [INT-2026-05-29-181219-task-decision-execution-traceability]
  rejected_decisions: [REJ-2026-06-02-120300-parallel-sequential-라벨로-하위-작업-실행-순서-표현]
---

## 결정

`task-github`에서 sub-issue 간 실행 선후관계는 GitHub **Issue dependencies**를 정본으로 사용한다. `sub-issue`는 "무엇으로 분해했는가"를 나타내는 트리 구조이고, `blocked_by`/`blocking`은 "무엇이 먼저 끝나야 하는가"를 나타내는 실행 제약이다.

dependency가 없는 형제 리프 이슈는 병렬 가능으로 간주한다. 열린 `blocked_by`가 있으면 `start`/`run`/`done`/`merge`에서 차단한다.

## 취지

작업 분해 구조와 실행 순서 제약을 분리해 GitHub의 native 기능을 task-github 운영 정본으로 쓰기 위함이다. 위키는 결정과 취지를 기록하고, 실제 작업 상태와 dependency 관계는 GitHub가 가진다([[INT-2026-05-29-181219-task-decision-execution-traceability]]).

## 배경

큰 작업을 sub-issue로 쪼개더라도 형제 이슈들이 항상 순차 실행되어야 하는 것은 아니다. 일부는 병렬 가능하고 일부는 선행 작업 완료 후 진행해야 한다. GitHub에는 Issue dependencies 기능이 있어 `blocked_by`/`blocking` 관계를 공식 메타데이터와 API로 표현할 수 있다.

## 고려한 대안

- [[REJ-2026-06-02-120300-parallel-sequential-라벨로-하위-작업-실행-순서-표현]] — 라벨로 병렬/직렬을 표시하는 방식. 혼합 DAG를 정확히 표현하기 어렵고 GitHub native dependency와 중복되어 반려.

## 트레이드오프

GitHub dependency 자체의 강제력은 시각화와 메타데이터에 가깝다. 따라서 task-github 스킬이 REST API를 조회해 열린 blocker를 차단해야 한다. 대신 GitHub UI/API와 같은 정본을 공유하고, 별도 라벨 체계를 만들지 않아도 된다.

## 재평가 조건

GitHub Issue dependencies가 대상 환경에서 안정적으로 제공되지 않거나 API 권한/플랜 제약 때문에 반복적으로 사용할 수 없다면 fallback 정책을 강화한다. 단, fallback도 라벨보다 dependency 코멘트나 명시적 수동 확인을 우선한다.
