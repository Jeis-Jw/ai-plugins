---
title: wiki↔task-github 계획 플로우 조율 구현
created_at: 2026-06-19
summary: doc-first 조율(작업정의 먼저, 수행 이슈 나중)을 두 플러그인에 구현. PR #12.
tags: [task-github, wiki-markdown, coordination]
relations:
  decisions: [DEC-2026-06-19-115758-위키-task-github-계획-플로우-작업정의-먼저-수행-이슈-나중]
  tasks: [Jeis-Jw/ai-plugins#12]
---

## 개요

doc-first 계획 플로우 조율을 wiki-markdown ↔ task-github에 구현한다. 근거는 연결된 결정(`relations.decisions`), 구현은 PR #12.

## 근거

작업정의(wiki task)가 수행(GitHub 이슈)보다 먼저여야 하고, 그 조율은 task-github 쪽에만 두어 wiki 순수성(비대칭 불변식)을 보존한다. 상세 근거·대안은 연결된 DEC.

## 범위와 완료 기준

**범위 (PR #12)**
- `task-github:define`를 doc-first로 반전(작업정의 task 먼저 확보 → 진행 확인 → 이슈 생성 → `relate --add-tasks` 역링크).
- 운영정책 정본(`agent-policy` scaffold `tracker_line`) + CLAUDE.md/AGENTS.md 관리블록 재렌더.
- `wiki-bridge.md`(§2/§4/§6) / `DESIGN.md`(§6.4/§7.3) 동기화. wiki `SKILL.md` task 타입 표현 명확화.
- wiki-markdown 무변경(순수).

**완료 기준**
- PR #12 머지.
- `define`가 doc-first로 동작(작업정의 선행, 진행 확인 게이트, `relate` 역링크).
- wiki-markdown 테스트 통과(현재 133/133).
- CLAUDE.md/AGENTS.md 정책블록 양쪽에 doc-first 순서 반영.
