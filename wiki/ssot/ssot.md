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

## 노트

- [[agent-operating-model]] — 이전 4계층 설계에서 작업환경 운영정책 정본으로 쓰던 레거시 슬롯. 2026-06-03 이후 운영정책 statement는 CLAUDE.md/AGENTS.md 자동로드 entry 표면이 정본이고, 이 문서는 이관 기록과 구버전 참조 호환만 담당한다.
- [[session-review-plugin]] — worker/reviewer가 audit snapshot 또는 fast context와 reviewer lease로 리뷰를 수렴시키는 플러그인 설계 정본
- [[task-github-plugin]] — task-worker를 실행 엔진으로 사용하고 GitHub Issue tree·dependency·PR·merge·closeout을 projection/delivery adapter로 소유하는 설계 정본
- [[task-worker-plugin]] — provider-neutral 작업 정의·분해·병렬 실행·검증·evidence 재사용을 소유하고 외부 provider가 상태와 delivery를 투영하는 범용 작업 엔진 설계 정본
