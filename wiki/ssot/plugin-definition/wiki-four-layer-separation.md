---
title: 위키 4계층 분리
created_at: 2026-05-29
summary: mechanism/policy/agent entry/knowledge 4계층 분리 정본: plugin agent-neutral, promotion threshold는 plugin spec 의미 판정은 operating model, agent entry는 정책 ssot의 포인터. plugin-definition 영역의 sub-ssot.
tags: [wiki, layering, ssot]
verified_at: 2026-05-29
---

## 현재 상태

### 4계층 분리

| 계층 | 위치 | 담는 것 | 이동 단위 |
|------|------|---------|-----------|
| **mechanism** | `plugins/wiki-markdown/` + [[plugin-definition]] + sub-ssot들 | 타입집합·ID포맷·frontmatter 스키마·경로기반 active·파생 인덱스·관계 작성 규칙·조회 단계·생명주기 | 플러그인과 함께 |
| **policy** | [[agent-operating-model]] (`wiki/ssot/agent-operating-model.md`, 정본) | 에이전트 역할, 캡처 권한, 이벤트 흐름, leaf issue 규약, 운영 promotion triggers | 프로젝트마다 정본 |
| **agent entry** | 프로젝트 루트 `CLAUDE.md` / `AGENTS.md` | **정책 ssot로의 짧은 포인터** + 프로젝트별 튜닝 | 프로젝트마다 |
| **knowledge** | `wiki/*` | 실제 축적된 record/ssot/runbook | 프로젝트 귀속 |

→ [[DEC-2026-05-29-105318-four-layer-separation]]

### 모호성 한 줄

> `wiki/*`는 지식 저장소이며, 그 안의 `agent-operating-model.md`는 운영 정책의 정본이다 — knowledge 계층과 policy 계층의 *물리 위치*는 같지만 *역할*이 다르다.

### Plugin agent-neutrality

- CLI 인자/출력 메시지/frontmatter 필드명/알고리즘 명세에 Claude/Codex 등 **특정 도구 이름 없음**
- 본문 산문에서 agent-neutral 원칙 설명이나 policy 계층 예시를 위한 agent 이름 언급은 허용
- agent별 규약(역할 분리, leaf issue 규약, PR 리뷰 흐름)은 **operating model로 격리**

→ [[DEC-2026-05-29-105326-plugin-agent-neutral-cli-schema]]

### Promotion threshold — plugin vs policy 책임 분리

```
plugin은 capture된 문서가 타입별 구조 조건·스키마를 만족하는지만 검증한다.
의미적 승격 가치 판정(누가 무엇을 언제)은 agent-operating-model.md의 영역이다.
```

- 정식 record로 승격되는 정보는 **장기 재사용 가능성, 구조적 영향, 반복 가능성, 되돌리기 비용, 후속 작업자가 알아야 할 필요성** 중 하나 이상을 가져야 함 (추상 기준)
- 운영 트리거(leaf issue 작성 시 어떤 후보를 capture할지 등)는 policy 계층

→ [[DEC-2026-05-29-105327-promotion-threshold-in-plugin-spec]]

## 취지

이 4계층 분리가 추구하는 일급 원칙:

- [[INT-2026-05-29-104711-plugin-agent-neutrality]] — 안정 자산(mechanism)과 변동 자산(policy)을 결합하지 않음
- [[INT-2026-05-29-104708-atomic-knowledge-records]] — 변경 빈도가 다른 자산을 같은 단위에 묶지 않음

## 구성요소

이 영역에 응집된 결정 anchor:

- [[DEC-2026-05-29-105318-four-layer-separation]] — 4계층 자체
- [[DEC-2026-05-29-105326-plugin-agent-neutral-cli-schema]] — CLI/스키마 agent-neutral
- [[DEC-2026-05-29-105327-promotion-threshold-in-plugin-spec]] — plugin은 구조 검증, 판정은 policy

교훈 (왜 이 분리가 필요한가): [[TRI-2026-05-29-105533-claude-md-as-policy-conflates-mechanism-and-policy]].

반려 대안: [[REJ-2026-05-29-105459-plugin-spec-with-agent-names]] (plugin spec에 agent 이름 침투) / [[REJ-2026-05-29-105501-promotion-auto-judgment]] (promotion 자동 판정).

