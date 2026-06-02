---
title: Knowledge capture audit gap in task-github workflow
created_at: 2026-06-02
summary: During a task-github rules update, Codex changed durable workflow decisions but did not capture an observation or propose decision/trial_error records before the final report.
tags: [task-github, wiki, knowledge-capture, workflow]
affects_paths: [plugins/task-github/**, wiki/ssot/agent-operating-model.md]
retired_at: 2026-06-02
retired_type: superseded
superseded_by: TRI-2026-06-02-120200-작업-종료-전-지식-기록-감사를-생략하면-결정-그래프가-비게-된다
---

## 관찰

task-github의 dependency 규약을 추가하는 동안 durable decision과 rejected alternative가 발생했지만, 최종 보고 전 위키 기록 후보를 감사하지 않았다. 특히 `observation`은 자동 캡처 가능한 범위였는데도 기록되지 않았고, `decision`/`trial_error` 후보도 제안되지 않았다.

## 근거

대화 중 "subissue는 분해 구조이고 Issue dependency는 실행 순서 정본"이라는 결정, "`parallel`/`sequential` 라벨은 두지 않는다"는 반려, "start/run/done/merge에서 열린 blocker를 차단한다"는 운영 규칙이 확정됐다. 이 내용은 `plugins/task-github/DESIGN.md`, `rules/dependencies.md`, 여러 `skills/*/SKILL.md`에 반영됐다.

## 영향

지식 기록 감사가 명시적 종료 게이트가 아니면, 규약 변경 작업은 문서에는 반영되어도 위키 결정 그래프에는 남지 않을 수 있다. 그러면 후속 에이전트가 왜 그 규칙이 생겼는지 recall로 찾지 못하고 같은 논의를 반복할 수 있다.

## 현재 처리

`wiki/ssot/agent-operating-model.md`와 `plugins/task-github/rules/knowledge-capture.md`에 Knowledge Capture Audit를 추가하는 보강 작업으로 대응 중이다. 감사 결과는 `recorded`/`proposed`/`none` 중 하나로 보고하도록 규약화한다.

## 후속 분류 조건

보강 규칙이 유지되면 이 관찰은 `trial_error`로 승격해 "기록 후보 감사를 종료 게이트로 두지 않으면 durable decision이 휘발된다"는 교훈을 남긴다. 동시에 GitHub Issue dependency 정본화는 별도 `decision`으로 캡처할 수 있다.
