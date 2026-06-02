---
title: Trial & Error — 시행착오
created_at: 2026-05-29
summary: 교훈·피해야 할 것·현재 유효성(record).
tags: [meta]
audience: [human, agent]
---

# Trial & Error — 시행착오

교훈·피해야 할 것·현재 유효성(record).

## 노트

- [[TRI-2026-05-29-105531-monolithic-design-doc-causes-status-ambiguity]] — v0(40KB) + v1(62KB) 두 monolithic 정의 문서가 wiki에 공존했더니 어느 게 현재 정본인지 AI가 추론해야 했다. atomic record 분해 + 단일 ssot 원칙을 위반하면 시스템 자체가 자기 원칙을 어김.
- [[TRI-2026-05-29-105532-flat-ssot-becomes-bloated-when-domain-grows]] — v0에서 ssot/는 평면 단일 폴더. 도메인이 커지면 한 폴더에 수십 개 파일이 쌓이고 인덱스도 비대화. v1은 nested 허용 + basename 전역 유일성 + 폴더 단위 독립 인덱스로 대응.
- [[TRI-2026-05-29-105533-claude-md-as-policy-conflates-mechanism-and-policy]] — v0의 3계층은 mechanism=plugin, 정책=CLAUDE.md, 지식=wiki. 그러나 CLAUDE.md에 정책을 직접 적으면 변경 빈도가 다른 두 자산이 한 파일에 섞임. v1은 정책을 wiki/ssot/agent-operating-model.md로 분리하고 CLAUDE.md를 그 ssot로의 포인터(agent entry)로 격하.
- [[TRI-2026-06-02-120200-작업-종료-전-지식-기록-감사를-생략하면-결정-그래프가-비게-된다]] — Codex가 task-github 규약 변경 중 durable decision과 rejected alternative를 만들고도 observation 캡처나 1급 기록 제안을 누락했다. 종료 전 Knowledge Capture Audit가 필요하다.
