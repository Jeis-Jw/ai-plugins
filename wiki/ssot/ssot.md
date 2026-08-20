---
title: SSOT — 현재 유효한 설계 정본
created_at: 2026-05-29
summary: 주제 단위로 제자리 갱신되는 현재 상태(living).
tags: [meta]
audience: [human, agent]
---

# SSOT — 현재 유효한 설계 정본

주제 단위로 제자리 갱신되는 현재 상태(living).

## 하위 영역

비대화된 영역은 폴더로 분할되어 자체 폴더 인덱스가 overview 역할을 한다 ([[DEC-2026-05-29-105319-nested-ssot-runbook-with-global-unique-basename]] / [[DEC-2026-05-29-105321-folder-independent-index-derivation]]).

- [[plugin-definition]] — 위키 플러그인 메커니즘 정본 영역 (`ssot/plugin-definition/`): wiki-data-model / wiki-lifecycle / wiki-retrieval / wiki-external-tools-policy / wiki-four-layer-separation 5 sub-ssot
- [[context-plugin-definition]] — context-core/context-decision의 공통 저장·index·lifecycle·capture/recall·v1 구현 계약 영역 (`ssot/context-plugin-definition/`)

## 노트

- [[agent-operating-model]] — 이전 4계층 설계에서 작업환경 운영정책 정본으로 쓰던 레거시 슬롯. 2026-06-03 이후 운영정책 statement는 CLAUDE.md/AGENTS.md 자동로드 entry 표면이 정본이고, 이 문서는 이관 기록과 구버전 참조 호환만 담당한다.
- [[context-core-plugin]] — ai-plugins가 소유하던 context-core의 설계 이력과 context-plugins 독립 저장소로의 이관 provenance.
- [[context-decision-plugin]] — ai-plugins가 소유하던 context-decision의 설계 이력과 context-plugins 독립 저장소로의 이관 provenance.
- [[session-review-plugin]] — read-only doctor로 준비 상태를 확인하고 worker/reviewer가 audit snapshot 또는 fast context와 reviewer lease로 리뷰를 수렴시키는 플러그인 설계 정본
- [[studio-plugin]] — Codex와 Claude Code가 제공하는 subagent 기능으로 역할 기반 crew를 운용하는 orchestration skill. 영속 상태는 mission receipt 재개 인덱스 하나뿐이다.
- [[task-github-plugin]] — remote-free provider init 뒤 task-worker를 실행 엔진으로 사용하고 GitHub Issue tree·dependency·PR·merge·closeout을 projection/delivery adapter로 소유하는 설계 정본
- [[task-worker-plugin]] — provider-neutral 작업 정의·분해·병렬 실행·검증·evidence 재사용을 소유하고 외부 provider가 상태와 delivery를 투영하는 범용 작업 엔진 설계 정본
- [[wiki-markdown-plugin]] — AI-native 위키 메커니즘 정본 — 버전·진화·소유범위·구성의 단일 진입점. 그래프 타입 체계, 경로 기반 lifecycle(retire/discard), 3-stage recall+pack, refresh tiering, 초기화 시 auto-loaded agent policy로 설치하는 proactive capture 계약을 소유한다.
