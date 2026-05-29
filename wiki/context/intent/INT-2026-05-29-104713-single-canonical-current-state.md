---
title: 정본은 현재 상태 하나
created_at: 2026-05-29
summary: Living(ssot/runbook) 정본은 현재 상태 하나여야 한다. 이력은 git과 context 결정들이 별도로 보유한다 — 정본에 시점 분기를 두지 않는다.
tags: [wiki, architecture, principle]
---

## 취지

Living 문서(ssot/runbook)는 **현재 상태 하나**여야 한다. 같은 주제의 정본이 둘 이상 공존하면 AI는 어느 게 정본인지 추론해야 하고, 그 모호함은 잘못된 결정의 원천이 된다.

## 배경

- 같은 주제의 v0/v1 정본이 wiki에 공존하면(예: 이 위키의 `plugin_definition_v0.md` + `plugin_definition_v1.md`), AI가 어느 게 현재 정본인지 모호해진다.
- 이력은 *별도 채널*이 보유한다: git 커밋 히스토리 + context/decision 그래프(왜 바뀌었나).
- ssot 본문은 *지금 어떻게*만 담는다. *왜/어떻게 변해왔나*는 context record들의 supersede 체인이 추적.

따라서 living은 **제자리 갱신**이고, 주제가 소멸할 때만 삭제한다(삭제 근거도 context/ 결정으로). 별도 retire/v1/v2 같은 분기를 두지 않는다.

