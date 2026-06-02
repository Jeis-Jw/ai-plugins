---
title: task-github 작업 종료 전 Knowledge Capture Audit 의무화
created_at: 2026-06-02
summary: 비 trivial task-github 작업은 종료 전에 위키 기록 후보를 감사하고 recorded/proposed/none 중 하나를 최종 보고나 Issue 코멘트에 남긴다.
tags: [task-github, wiki, knowledge-capture, policy]
relations:
  intents: [INT-2026-05-29-181219-task-decision-execution-traceability]
  ssot: [agent-operating-model]
---

## 결정

비 trivial `task-github` 작업은 종료 전 **Knowledge Capture Audit**를 의무적으로 수행한다. 감사 결과는 `recorded` / `proposed` / `none` 중 하나여야 하며, 최종 보고 또는 Issue 코멘트에 남긴다.

규약상 자동 캡처는 `observation`에 한정한다. `decision`, `rejected_decision`, `trial_error`, `intent`, `task` 같은 1급 노드와 observation 승격은 제안 후 확인한다. `ssot`/`runbook`은 living 문서 제자리 갱신 후보로 제안한다.

## 취지

작업 중 발생한 결정·반려·교훈·관찰이 코드와 문서 패치에는 반영되지만 위키 결정 그래프에는 남지 않는 문제를 막기 위함이다. 작업 상태는 GitHub에 있고, 장기 맥락은 위키에 있으므로, 종료 시점에 둘 사이의 지식 누락을 점검해야 한다([[INT-2026-05-29-181219-task-decision-execution-traceability]]).

## 배경

Issue dependency 규약을 추가하는 작업에서 "sub-issue는 분해 구조, Issue dependency는 실행 순서 정본" 같은 durable decision과 "`parallel`/`sequential` 라벨은 두지 않는다"는 rejected alternative가 생겼다. 그러나 최종 보고 전 기록 후보 감사가 없어 observation 자동 캡처도, 1급 기록 제안도 누락됐다.

## 고려한 대안

- 기존처럼 `run`의 observation 자동 캡처와 `verify`의 승격 제안만 둔다. 반려: `done`/`merge`나 일반 문서 패치 작업에서 누락되기 쉽고, 이슈 없는 작업에서는 작동하지 않는다.
- 모든 지식을 자동 캡처한다. 반려: decision/trial_error 같은 1급 노드는 의미 판정이 들어가므로 사령관 확인 없는 자동 승격 금지 원칙과 충돌한다.
- 종료 전 감사 결과를 `recorded`/`proposed`/`none`으로 강제한다. 채택: 자동 캡처 범위는 지키면서도 기록 후보 제안 누락을 막는다.

## 트레이드오프

작업 종료 보고가 조금 길어진다. 대신 장기 재사용 가능한 지식이 있을 때 위키 기록 후보가 빠지지 않고, 기록할 것이 없을 때도 그 판단 근거가 남는다.

## 재평가 조건

Knowledge Capture Audit가 반복적으로 형식적 문구만 늘리고 실제 기록 누락을 줄이지 못하면, 자동 캡처 기준이나 감사 출력 형식을 다시 조정한다.
