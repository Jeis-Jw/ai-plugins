---
title: 위키 플러그인 정의 (영역 인덱스)
created_at: 2026-05-29
summary: AI-Native 위키 메커니즘 정본 영역 — 데이터 모델/라이프사이클/조회/외부 도구/4계층이 sub-ssot로 분할되어 응집. 이 폴더 인덱스 자체가 overview 역할.
tags: [wiki, plugin, meta]
audience: [human, agent]
---

# 위키 플러그인 정의

이 워크스페이스의 AI-Native 위키 **메커니즘 정본**은 `plugins/wiki-markdown/` (marketplace plugin `jeis-ai-plugins/wiki-markdown@0.6.0`)이다. 본 영역(`wiki/ssot/plugin-definition/`)은 그 메커니즘의 **결정 그래프 anchor**와 **영역 라우팅** 역할을 하며, 5개 sub-ssot로 응집되어 있다. 메커니즘 세부는 plugin source(`SKILL.md`, `rules/knowledge-protocol.md`, `skills/wiki/references/wiki-protocol.md`) + 본 위키의 active decisions가 정본이다.

## 일급 원칙 (intent anchor)

이 위키가 추구하는 7개 원칙. 각 sub-ssot가 자기 ## 취지로 관련 원칙을 anchor한다:

- [[INT-2026-05-29-104707-token-efficient-context-loading]] — 토큰 효율적 계층 조회
- [[INT-2026-05-29-104708-atomic-knowledge-records]] — 지식 원자성
- [[INT-2026-05-29-104709-filesystem-primary-truth]] — 파일시스템 정본
- [[INT-2026-05-29-104710-ai-driven-documentation]] — AI 주도 문서화
- [[INT-2026-05-29-104711-plugin-agent-neutrality]] — 플러그인 agent 중립성
- [[INT-2026-05-29-104712-parallel-safe-headless-operation]] — 병렬·헤드리스 안전성
- [[INT-2026-05-29-104713-single-canonical-current-state]] — 정본은 현재 상태 하나

## 영역 라우팅 (sub-ssot)

| sub-ssot | 다루는 영역 |
|----------|-------------|
| [[wiki-data-model]] | 타입 체계 + ID 체계 + 관계 모델 (그래프의 정적 구조) |
| [[wiki-lifecycle]] | Active/Retired + supersede + retire 2값 모델 |
| [[wiki-retrieval]] | 인덱스 파생 + 3-stage recall + search_terms + refresh 검사 |
| [[wiki-external-tools-policy]] | Obsidian 0 의존 + wikilink 정책 |
| [[wiki-four-layer-separation]] | mechanism/policy statement/policy rationale/knowledge + agent-neutral + promotion threshold |

영역 외 ssot:

- [[agent-operating-model]] (`wiki/ssot/`) — 레거시 운영정책 슬롯. 현재 policy statement 정본은 `CLAUDE.md`/`AGENTS.md`.

## 구성요소

- **Plugin 위치**: `plugins/wiki-markdown/`
- **단일 CLI**: `skills/wiki/scripts/wiki_cli.py` (init / capture / retire / recall / refresh)
- **계약 문서**: `skills/wiki/SKILL.md`, `skills/wiki/references/wiki-protocol.md`, `rules/knowledge-protocol.md`
- **템플릿**: `templates/{intent,decision,rejected_decision,trial_error,observation,ssot,runbook}.md`

## 진화 추적

본 위키 자체의 설계 진화:

- **v0** (2026-05-22) — monolithic 정의 문서 (`plugin_definition_v0.md`, 40KB, 702줄)
- **v1** (2026-05-28) — monolithic 정의 문서 (`plugin_definition_v1.md`, 62KB, 1013줄)
- **현재** (2026-05-29) — record 분해 + 5 sub-ssot로 응집 (본 영역)

원본 monolithic 문서: `backup/wiki-ssot-pre-v1-2026-05-29/`.

전환에서 얻은 교훈:
- [[TRI-2026-05-29-105531-monolithic-design-doc-causes-status-ambiguity]] — monolithic 정의 문서가 정본 모호화를 일으킴
- [[TRI-2026-05-29-105532-flat-ssot-becomes-bloated-when-domain-grows]] — 영역 분할의 근거
- [[DEC-2026-06-03-103000-운영정책-statement는-자동로드-agent-entry에-둔다]] — policy statement 자동로드 재배치

## 노트

- [[wiki-data-model]] — 위키 그래프의 정적 구조 정본: 5종 record + 2종 living + 1종 task(제3 범주) 타입 체계, basename 정본 ID, YAML 관계 모델(비대칭 작성). plugin-definition 영역의 sub-ssot.
- [[wiki-external-tools-policy]] — 외부 도구(Obsidian 등)와의 경계 정본: AI 검색 정본은 filesystem 단일(ripgrep+YAML), wikilink는 사람용 장식, .obsidian/ gitignore. plugin-definition 영역의 sub-ssot.
- [[wiki-four-layer-separation]] — mechanism/policy statement/policy rationale/knowledge 4계층 분리 정본: plugin은 agent-neutral mechanism, 작업환경 policy statement는 CLAUDE.md/AGENTS.md 자동로드 표면, policy rationale은 프로젝트가 정한 이력 위치, wiki vault는 knowledge 저장소. plugin-definition 영역의 sub-ssot.
- [[wiki-lifecycle]] — Record와 Living의 라이프사이클 정본: 경로 기반 active/retired, deprecated/superseded 2값 retire 모델, supersede pair 양방향 저장, task 이진 상태(활성/done) + 정본 위임. plugin-definition 영역의 sub-ssot.
- [[wiki-retrieval]] — 인덱스 파생과 조회 표면 정본: 폴더 단위 독립 인덱스, 3-stage recall + batch read, search_terms recognized optional, affects_paths + changed-path-stale, refresh --fix 화이트리스트. plugin-definition 영역의 sub-ssot.
