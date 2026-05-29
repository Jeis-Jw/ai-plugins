---
title: 플러그인 agent 중립성
created_at: 2026-05-29
summary: Plugin 메커니즘은 특정 AI 도구(Claude/Codex 등) 이름을 박지 않는다. 미래 도구 교체에도 메커니즘이 흔들리지 않게.
tags: [wiki, plugin, principle]
---

## 취지

Plugin 메커니즘은 특정 AI 도구(Claude, Codex 등) 이름을 깊숙이 박지 않는다. 미래에 도구를 교체하거나 다중 도구를 함께 쓸 때도 위키 메커니즘(타입·ID·관계 그래프)이 그대로 유지되도록 한다.

## 배경

- 위키 메커니즘은 **안정 자산** — 한 번 정착되면 잘 안 바뀐다.
- agent별 운영 규약(역할 분리, leaf issue 규약, PR 리뷰 흐름 등)은 **변동 자산** — 도구 교체나 워크플로 진화로 자주 바뀐다.
- 둘을 한 곳에 섞으면 변경 빈도가 다른 자산이 결합되어, 안정 자산이 변동 자산을 따라 함께 흔들린다.

따라서 plugin spec(CLI 인자/스키마/알고리즘 출력)에는 agent 이름이 들어가지 않는다. agent별 규약은 운영 정책 정본(`agent-operating-model.md`)으로 격리한다.

