---
title: wiki-markdown 개선: agent-facing 표면 재설계 우선 (Unit A/B/C + closeout)
created_at: 2026-06-25
summary: wiki 운용 마찰 본체는 신규기능이 아니라 SKILL/CLI 표면이 실체와 drift한 것 — 표면 재설계를 P0로, discard/projection/stale/closeout을 소수 추가
tags: [wiki-markdown, improvement, architecture]
relations:
  tasks: [Jeis-Jw/ai-plugins#20]
---

## 결정

wiki-markdown 개선의 최우선 레버를 신규 기능이 아니라 agent-facing 표면(SKILL.md + CLI 자기설명) 재설계로 둔다. P0 Unit A: compact SKILL, 기본 예제를 --sec-*/--lite/--stage/--level 중심으로 교체, command별 --json payload 예시, capture --json payload 확장(additive), negative trigger, --level 문서화. P1 Unit B: discard 가드 + body-file/STDIN. P1 Unit C: recall --pack(deterministic) + authority/stale additive label(relation-aware). P2 closeout: complete/reopen payload 강화(새 명령 아님). 상세는 docs/proposals/wiki-markdown-improvement-direction.md.

## 취지

두 에이전트(Claude/Codex) 실사용 피드백 마찰이 거의 전부 운용 표면(토큰·왕복·되돌리기)에 몰렸고, 시끄러운 요청 다수(--sec-*, --lite, capture index 자동동기화, recall --stage 압축)가 이미 구현돼 있으나 SKILL.md에 노출 안 됨. 따라서 체감 비용을 줄이는 최대 레버는 표면을 실체에 맞추는 것이다.

## 배경

session-review 3라운드(separate/hard; Claude worker, Codex reviewer) 전부 approved로 수렴. 실측 그라운딩으로 SKILL/CLI drift 3건(--sec-*, --lite, --level) 확정 — 특히 --level tier 모델은 task-github이 hard-gate로 의존하나 wiki SKILL 미문서. 17개 피드백 항목: 이미구현 4, 신규빈틈 4, 정책계층 3, 오진 1.

## 고려한 대안

(a) 요청대로 신규 기능부터 빌드 — 이미 구현된 것과 중복이라 기각. (b) stateful usage mode 6종 + context-lock — 무상태 filesystem-primary 설계와 충돌, ceremony 과다라 기각(모드는 SKILL/agent-policy 서술로 대체). (c) wiki closeout 새 명령 — task-github 경계 침범, complete/reopen payload 강화로 대체.

## 트레이드오프

표면 우선은 상시 토큰·왕복 비용을 즉시 줄이지만 신규 기능 산출은 적다. mechanism 추가(discard/projection/stale)는 P1로 미뤄 묶는 blast radius를 작게 유지. discard 같은 파괴적 기능에는 가드 + adversarial review 비용을 추가로 치른다.

## 재평가 조건

Unit A 후 benchmark 실측에서 명령/read/edit/토큰 절감이 baseline 가설표에 크게 못 미치면 우선순위 재검토. 또는 task-github와 wiki CLI 표면이 다시 drift하면 P0-선행 audit를 재실행한다.
