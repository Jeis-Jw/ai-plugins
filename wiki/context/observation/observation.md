---
title: Observations — 관찰
created_at: 2026-05-29
summary: 발견·관찰. 분류 전 임시 record. 후속 TRI/DEC/SSOT 갱신으로 승격되며 supersede.
tags: [meta]
audience: [human, agent]
---

# Observations — 관찰

발견·관찰. 분류 전 임시 record. 후속 TRI/DEC/SSOT 갱신으로 승격되며 supersede.

## 노트

- [[OBS-2026-06-02-200327-knowledge-capture-감사-어휘가-3계층에-중복-정의됨]] — task-github 사후 리뷰에서 recorded/proposed/none 어휘가 rules/knowledge-capture.md·agent-operating-model §1.1·DESIGN §13.1.1 3곳에 중복돼 이미 문구가 어긋난 drift를 발견. 해소: 플러그인이 위키 없이도 산출하는 어휘이므로 메커니즘(rules/knowledge-capture.md)을 정본으로 단일화하고, policy는 의무 규정+포인터, DESIGN은 포인터로 격하. policy를 정본으로 삼는 안은 graceful-degradation(불변식 20) 위반이라 기각. 리뷰 종합 판정은 '취지 충실'.
- [[OBS-2026-06-02-203000-refresh-strict-does-not-catch-empty-observation-body-sections]] — Review found observation records with all fixed body sections empty while wiki refresh --strict still returned no issues. This leaves Stage-2 recall with headers but no evidence.
