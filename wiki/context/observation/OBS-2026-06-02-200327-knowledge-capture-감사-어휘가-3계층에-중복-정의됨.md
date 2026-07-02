---
title: Knowledge Capture 감사 어휘가 3계층에 중복 정의됨
created_at: 2026-06-02
summary: task-github 사후 리뷰에서 recorded/proposed/none 어휘가 rules/knowledge-capture.md·agent-operating-model §1.1·DESIGN §13.1.1 3곳에 중복돼 이미 문구가 어긋난 drift를 발견. 해소: 플러그인이 위키 없이도 산출하는 어휘이므로 메커니즘(rules/knowledge-capture.md)을 정본으로 단일화하고, policy는 의무 규정+포인터, DESIGN은 포인터로 격하. policy를 정본으로 삼는 안은 graceful-degradation(불변식 20) 위반이라 기각. 리뷰 종합 판정은 '취지 충실'.
tags: [task-github, knowledge-capture, doc-drift, review]
verified_at: 2026-07-03
affects_paths: [plugins/task-github/rules/knowledge-capture.md, wiki/ssot/agent-operating-model.md, plugins/task-github/DESIGN.md]
supersedes: [OBS-2026-06-02-195745-knowledge-capture-감사-어휘가-3계층에-중복-정의됨]
relations:
  decisions: [DEC-2026-06-02-120100-task-github-작업-종료-전-knowledge-capture-audit-의무화]
---

## 관찰

`recorded` / `proposed` / `none` 결과 어휘와 타입 판정 설명이 `plugins/task-github/rules/knowledge-capture.md`, `wiki/ssot/agent-operating-model.md` §1.1, `plugins/task-github/DESIGN.md` §13.1.1에 중복 정의되어 있었다. 세 문서는 같은 개념을 다루지만 문구와 ownership 해석이 달라질 수 있는 구조였다.

## 근거

사후 리뷰에서 `agent-operating-model.md`는 결과값 표를 policy 정본처럼 들고 있었고, `DESIGN.md`도 타입별 처리 요약을 직접 포함하고 있었다. 그러나 `task-github`는 위키가 없는 환경에서도 Knowledge Capture Audit 결과를 산출해야 하므로, 결과 어휘와 타입 판정은 위키 policy가 아니라 플러그인 메커니즘(`rules/knowledge-capture.md`) 쪽에 있어야 한다.

## 영향

중복 정의를 방치하면 `recorded`/`proposed`/`none`의 의미가 문서별로 갈라져, 스킬 구현과 위키 policy가 서로 다른 기준으로 감사 결과를 해석할 수 있다. 특히 위키를 사용할 수 없는 환경에서 policy 문서를 정본으로 삼으면 graceful degradation 원칙과 충돌한다.

## 현재 처리

어휘와 타입 판정의 정본을 `plugins/task-github/rules/knowledge-capture.md`로 단일화했다. `wiki/ssot/agent-operating-model.md`는 "비 trivial 작업은 감사한다"는 policy 의무와 포인터만 보유하고, `plugins/task-github/DESIGN.md`는 mechanism/policy 경계를 설명하는 참조용 포인터로 격하했다. 이전 observation `OBS-2026-06-02-195745-...`는 policy를 정본으로 보는 방향이라 이 record가 supersede한다.

## 재검증

2026-07-03 task-github 0.15.1 변경 이력 추가 후에도 Knowledge Capture Audit 어휘 정본은 `plugins/task-github/rules/knowledge-capture.md`에 남아 있고, `DESIGN.md`는 변경 이력/참조 역할만 수행함을 확인했다.

## 후속 분류 조건

이 문제가 반복되면 `trial_error`로 승격해 "운영 어휘는 실제 산출 주체가 있는 layer에 단일화해야 한다"는 교훈으로 남긴다. 현재는 문서 구조 drift를 발견하고 정리한 observation으로 유지한다.
