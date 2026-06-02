---
title: Knowledge Capture 감사 어휘가 3계층에 중복 정의됨
created_at: 2026-06-02
summary: task-github 사후 리뷰에서 recorded/proposed/none 결과 어휘 표가 rules/knowledge-capture.md, ssot/agent-operating-model.md §1.1, DESIGN.md §13.1.1 세 곳에 중복돼 drift 위험을 발견. 단일 SSOT 원칙대로 policy(agent-operating-model)를 정본으로 두고 나머지는 포인터로 단일화한다. 관련 결정 DEC-2026-06-02-120100. 리뷰 종합 판정은 '취지 충실'.
tags: [task-github, knowledge-capture, doc-drift, review]
affects_paths: [plugins/task-github/rules/knowledge-capture.md, wiki/ssot/agent-operating-model.md, plugins/task-github/DESIGN.md]
retired_at: 2026-06-02
retired_type: superseded
superseded_by: OBS-2026-06-02-200327-knowledge-capture-감사-어휘가-3계층에-중복-정의됨
---

## 관찰

Knowledge Capture Audit 결과 어휘(`recorded`/`proposed`/`none`)가 `rules/knowledge-capture.md`, `wiki/ssot/agent-operating-model.md`, `DESIGN.md` 세 곳에 중복 정의되어 있었다. 이 record는 처음에 단일 SSOT 원칙만 보고 policy(`agent-operating-model.md`)를 정본으로 삼는 방향을 제안했다.

## 근거

`agent-operating-model.md`는 위키와 task-github 결합 policy의 정본이므로, 처음 판단에서는 감사 어휘도 policy에 두고 plugin rules/DESIGN은 포인터로 낮추는 안을 적었다. 당시 summary에도 "policy(agent-operating-model)를 정본으로 둔다"고 기록했다.

## 영향

이 판단은 부분적으로 맞지만 layer 경계를 충분히 보지 못했다. Knowledge Capture Audit 결과 어휘는 위키가 없어도 task-github가 산출해야 하는 메커니즘 출력이므로, policy를 정본으로 삼으면 graceful degradation과 충돌할 수 있다.

## 현재 처리

이 record는 `OBS-2026-06-02-200327-knowledge-capture-감사-어휘가-3계층에-중복-정의됨`로 supersede됐다. 후속 record는 결과 어휘와 타입 판정 정본을 `rules/knowledge-capture.md`에 두고, policy는 감사 의무만 규정하는 방식으로 판단을 바로잡았다.

## 후속 분류 조건

동일한 layer ownership 혼동이 반복되면 mechanism/policy 경계에 대한 `trial_error`로 승격한다. 현재 record 자체는 superseded 상태이므로 후속 판단은 active successor를 기준으로 한다.
