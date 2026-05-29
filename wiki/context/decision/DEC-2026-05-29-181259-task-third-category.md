---
title: task를 record/living과 나란한 제3 범주로 신설
created_at: 2026-05-29
summary: 결정과 취지를 이슈에 잇는 작업 브릿지 노드 task를 신설 — 제자리 갱신과 관계 보유를 조합한 순수 잎, relations는 intents/decisions/tasks/ssot, ID는 TASK 프리픽스, 경로는 wiki/task.
tags: [wiki, task, data-model]
relations:
  intents: [INT-2026-05-29-181219-task-decision-execution-traceability]
  rejected_decisions: [REJ-2026-05-29-181259-task-as-immutable-record, REJ-2026-05-29-181259-task-as-living-relax-invariant]
  ssot: [wiki-data-model]
---

## 결정

위키에 `record`/`living`과 나란한 **제3 범주로 `task` 타입을 신설**한다. task는 작업의 요약·근거를 담아 외부 이슈에 잇는 **브릿지 노드**다.

- **성질 조합**: 제자리 갱신(living의 성질) + 관계 보유(record의 성질).
- **그래프 위치**: **순수 잎** — outbound 관계만 가지며, 어떤 타입도 task를 가리키지 않는다.
- **허용 관계**: `intents` / `decisions` / `tasks`(외부 이슈) / `ssot`.
- **ID**: 프리픽스 `TASK` (`TASK-YYYY-MM-DD-HHMMSS-<slug>`).
- **경로**: `wiki/task/`.

## 취지

결정 그래프와 작업 실행을 잇는 최소 단위가 필요했다([[INT-2026-05-29-181219-task-decision-execution-traceability]]). task는 record/living 어느 쪽에도 깔끔히 안 맞는다 — 불변이면 자립 진행 표시가 불가하고, living이면 관계 불변식을 훼손한다. 그래서 제3 범주가 가장 정합적이다.

## 배경

작업관리 플러그인(task-github)이 GitHub 이슈로 작업을 수행하는데, 위키 결정과 그 작업 사이에 **1급 연결 노드**가 없었다. `intent`/`ssot`는 hub라 `--tasks` 역링크를 못 가져 에픽↔intent가 단방향이 되는데, task(record 성질)는 이슈 링크(`relations.tasks`)를 들 수 있어 **양방향 다리**가 된다. 역방향 조회("이 결정이 낳은 작업")는 task의 outbound 관계를 **파생 백링크**로 잡으면 되므로, 다른 타입 스키마는 손대지 않는다(순수 가산).

## 고려한 대안

- [[REJ-2026-05-29-181259-task-as-immutable-record]] — task를 불변 record로.
- [[REJ-2026-05-29-181259-task-as-living-relax-invariant]] — task를 living으로 두고 불변식 완화.

둘 다 반려.

## 트레이드오프

타입 체계에 범주를 하나 더해 CLI·스키마·문서 복잡도가 늘지만, **결정↔작업 추적**이라는 핵심 가치를 얻고 기존 7타입과 불변식은 무손상이다(순수 가산).

## 재평가 조건

task가 실사용에서 거의 안 쓰이거나, 외부 트래커 연계 없이 위키 단독으로만 작업을 관리하게 되면 범주 통합/축소를 재검토한다.
