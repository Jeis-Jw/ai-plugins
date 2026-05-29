---
title: 에이전트 운영 모델 (정책 정본)
created_at: 2026-05-29
summary: 이 위키를 사용하는 에이전트들의 운영 정책 정본. 4계층 분리(plugin_definition)에서 policy 계층에 해당. agent별 역할·캡처 권한·이벤트 흐름은 여기서 정의 — 비어있는 상태로 시작해 운영하며 점진 보강.
tags: [wiki, policy, ssot]
verified_at: 2026-05-29
---

## 현재 상태

> `wiki/*`는 지식 저장소이며, 그 안의 본 문서(`agent-operating-model.md`)는 **운영 정책의 정본**이다 — knowledge 계층과 policy 계층의 물리 위치는 같지만 역할이 다르다 (4계층 분리: [[plugin-definition]]).

**현재 본 ssot는 placeholder 상태다.** 운영하면서 실제 정책이 드러나는 시점에 채워나간다. 미작성 영역이라고 해서 plugin 메커니즘이 막히지는 않는다 — plugin은 정책 ssot의 존재 여부와 무관하게 작동한다.

작업관리·GitHub Issue/PR 운영 규약은 현재 의도적으로 보류 상태다. 위키 플러그인 메커니즘의 정본은 `plugin-definition/` 영역과 context record에 있으며, 본 문서는 그 메커니즘을 특정 작업관리 시스템에 묶지 않기 위한 정책 자리만 예약한다.

## 취지

Plugin 메커니즘과 운영 정책을 **다른 변경 빈도**로 분리하기 위한 정책 정본 자리. CLAUDE.md/AGENTS.md에 운영 정책을 직접 적으면 안정 자산(plugin spec)과 변동 자산(agent 운영 규약)이 한 파일에 묶여 함께 흔들린다 → [[TRI-2026-05-29-105533-claude-md-as-policy-conflates-mechanism-and-policy]].

본 ssot가 정책 정본이면, 운영 정책의 진화도 위키 메커니즘(supersede / verified_at / refresh) 안으로 들어와 추적 가능(dogfooding).

## 구성요소

채워나갈 자리 (수치·역할·일정은 운영 시점에 확정):

- **에이전트별 역할 분리** — 어떤 에이전트가 어떤 종류의 작업을 책임지는가
- **캡처 권한** — 누가 어떤 타입(INT/DEC/REJ/TRI/OBS/ssot/runbook)을 capture할 수 있는가
- **leaf issue 규약** — GitHub Issue ↔ 위키 record 연결 방식 (`## Wiki Context` 등)
- **PR 리뷰 흐름** — PR과 위키 결정의 cross-link 규칙
- **promotion 트리거** — 어떤 신호일 때 무엇으로 승격하는가 (plugin은 구조 검증만, 판정은 여기 — [[DEC-2026-05-29-105327-promotion-threshold-in-plugin-spec]])
- **GitHub template 규약** — `.github/ISSUE_TEMPLATE/*` 가 본 ssot와 동기되도록 운영

작성·갱신 시에는 일반 ssot처럼 제자리 수정 + `verified_at` 갱신. 운영 정책 자체의 결정/반려/교훈은 `wiki/context/`에 record로 capture해 본 ssot가 그 record들로 anchor됨.
