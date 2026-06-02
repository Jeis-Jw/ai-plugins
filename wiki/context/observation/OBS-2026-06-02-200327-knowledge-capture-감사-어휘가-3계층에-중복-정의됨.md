---
title: Knowledge Capture 감사 어휘가 3계층에 중복 정의됨
created_at: 2026-06-02
summary: task-github 사후 리뷰에서 recorded/proposed/none 어휘가 rules/knowledge-capture.md·agent-operating-model §1.1·DESIGN §13.1.1 3곳에 중복돼 이미 문구가 어긋난 drift를 발견. 해소: 플러그인이 위키 없이도 산출하는 어휘이므로 메커니즘(rules/knowledge-capture.md)을 정본으로 단일화하고, policy는 의무 규정+포인터, DESIGN은 포인터로 격하. policy를 정본으로 삼는 안은 graceful-degradation(불변식 20) 위반이라 기각. 리뷰 종합 판정은 '취지 충실'.
tags: [task-github, knowledge-capture, doc-drift, review]
verified_at: 2026-06-02
affects_paths: [plugins/task-github/rules/knowledge-capture.md, wiki/ssot/agent-operating-model.md, plugins/task-github/DESIGN.md]
supersedes: [OBS-2026-06-02-195745-knowledge-capture-감사-어휘가-3계층에-중복-정의됨]
relations:
  decisions: [DEC-2026-06-02-120100-task-github-작업-종료-전-knowledge-capture-audit-의무화]
---

## 관찰

## 근거

## 영향

## 현재 처리

## 후속 분류 조건

