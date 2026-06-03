---
title: 위키 4계층 분리
created_at: 2026-05-29
summary: mechanism/policy statement/policy rationale/knowledge 4계층 분리 정본: plugin은 agent-neutral mechanism, 작업환경 policy statement는 CLAUDE.md/AGENTS.md 자동로드 표면, policy rationale은 프로젝트가 정한 이력 위치, wiki vault는 knowledge 저장소. plugin-definition 영역의 sub-ssot.
tags: [wiki, layering, ssot]
verified_at: 2026-06-03
---

## 현재 상태

### 4계층 분리

| 계층 | 위치 | 담는 것 | 이동 단위 |
|------|------|---------|-----------|
| **mechanism** | `plugins/wiki-markdown/` + [[plugin-definition]] + sub-ssot들 | 타입집합·ID포맷·frontmatter 스키마·경로기반 active·파생 인덱스·관계 작성 규칙·조회 단계·생명주기 | 플러그인과 함께 |
| **policy statement** | `CLAUDE.md` / `AGENTS.md` operating policy block, 필요 시 `.claude/` | 에이전트 역할, 동시성/worktree 규약, 캡처 권한, leaf issue 규약, 운영 promotion triggers | 프로젝트마다 자동로드 |
| **policy rationale** | 프로젝트가 정한 운영 이력 위치. 이 플러그인 개발 repo는 `wiki/context/decision/` | 왜 이 정책을 택했는가, 무엇을 대체했는가 | 프로젝트마다 선택 |
| **knowledge** | `wiki/*` | 제품·서비스·시스템 지식과 작업이 낳은 record/ssot/runbook/task | 프로젝트 귀속 |

→ [[DEC-2026-06-03-103000-운영정책-statement는-자동로드-agent-entry에-둔다]]

### 모호성 한 줄

> 소비 프로젝트의 `wiki/*`는 지식 저장소다. 작업환경 운영정책 statement는 wiki recall에 의존하지 않는 자동로드 entry 표면에 둔다. 이 플러그인 개발 repo가 policy 변경 근거를 wiki `decision`으로 남기는 것은 플러그인 설계 자체를 dogfood하는 예외다.

### Plugin agent-neutrality

- CLI 인자/출력 메시지/frontmatter 필드명/알고리즘 명세에 Claude/Codex 등 **특정 도구 이름 없음**
- 본문 산문에서 agent-neutral 원칙 설명이나 policy 계층 예시를 위한 agent 이름 언급은 허용
- agent별 규약(역할 분리, leaf issue 규약, PR 리뷰 흐름)은 **자동로드 operating policy statement로 격리**

→ [[DEC-2026-05-29-105326-plugin-agent-neutral-cli-schema]]

### Promotion threshold — plugin vs policy 책임 분리

```
plugin은 capture된 문서가 타입별 구조 조건·스키마를 만족하는지만 검증한다.
의미적 승격 가치 판정(누가 무엇을 언제)은 자동로드 operating policy statement의 영역이다.
```

- 정식 record로 승격되는 정보는 **장기 재사용 가능성, 구조적 영향, 반복 가능성, 되돌리기 비용, 후속 작업자가 알아야 할 필요성** 중 하나 이상을 가져야 함 (추상 기준)
- 운영 트리거(leaf issue 작성 시 어떤 후보를 capture할지 등)는 policy statement 계층

→ [[DEC-2026-05-29-105327-promotion-threshold-in-plugin-spec]]

## 취지

이 4계층 분리가 추구하는 일급 원칙:

- [[INT-2026-05-29-104711-plugin-agent-neutrality]] — 안정 자산(mechanism)과 변동 자산(policy)을 결합하지 않음
- [[INT-2026-05-29-104708-atomic-knowledge-records]] — 변경 빈도가 다른 자산을 같은 단위에 묶지 않음

## 구성요소

이 영역에 응집된 결정 anchor:

- [[DEC-2026-06-03-103000-운영정책-statement는-자동로드-agent-entry에-둔다]] — policy statement 자동로드 재배치
- [[DEC-2026-05-29-105326-plugin-agent-neutral-cli-schema]] — CLI/스키마 agent-neutral
- [[DEC-2026-05-29-105327-promotion-threshold-in-plugin-spec]] — plugin은 구조 검증, 판정은 policy

이전 4계층 결정과 CLAUDE.md 장문정책 반려 교훈은 새 결정으로 superseded되었다.

반려 대안: [[REJ-2026-05-29-105459-plugin-spec-with-agent-names]] (plugin spec에 agent 이름 침투) / [[REJ-2026-05-29-105501-promotion-auto-judgment]] (promotion 자동 판정).
