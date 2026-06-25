---
title: wiki-markdown 개선 구현 루트 — Unit A/B/C (+closeout)
created_at: 2026-06-25
summary: 확정 방향(DEC)에 따른 wiki-markdown 표면 재설계 + mechanism 빈틈 구현의 루트 작업. 순서 A→(B|C)→closeout
tags: [wiki-markdown, improvement]
relations:
  decisions: [DEC-2026-06-25-182926-wiki-markdown-개선-agent-facing-표면-재설계-우선-unit-a-b-c-closeout]
  tasks: [Jeis-Jw/ai-plugins#20]
---

## 개요

wiki-markdown 0.12.0 운용 효율 개선의 루트 work-order. 상세 분해·근거는 DEC와 docs/proposals/wiki-markdown-improvement-direction.md, 실행 체크리스트는 연결된 GitHub 루트 이슈. 순서: Unit A(표면/P0) → B(write UX)/C(read·authority UX) → closeout(P2).

## 근거

DEC(agent-facing 표면 재설계 우선)에서 파생. session-review 3라운드 수렴 결과를 실행으로 옮긴다. gear:normal — 대부분 유닛 저~중 blast radius. 단 Unit B discard는 durable 지식 삭제라 파괴적 → 가드 + adversarial review를 별도로 둔다.

## 범위와 완료 기준

범위: plugins/wiki-markdown/skills/wiki(SKILL.md, wiki_cli.py), references, templates, 그리고 agent-policy(negative trigger gate). Unit A=compact SKILL + 예제 교체 + capture --json payload(additive) + --level 문서화 + negative trigger + 선행 bounded drift audit. Unit B=discard(가드) + body-file/STDIN. Unit C=recall --pack(deterministic) + authority/stale additive label. closeout=complete/reopen payload 강화(별도 P2). 완료: 각 유닛 이슈 close + Unit A benchmark 가설표 실측 + task-github CLI 표면 drift 0. 세부 실행은 GitHub 루트 이슈.
