---
title: capture checkpoint를 Stop hook 5중 게이트·배치당 1회로 도입
created_at: 2026-08-06
summary: semantic milestone 감사(§12.3)가 모델 재량만으로 누락되어 wiki-markdown 0.22.0에 Claude Code Stop hook을 도입 — 5중 게이트 전부 통과 시에만 발화하고 세션 state로 배치당 1회만 리마인드해 토큰 비용을 통제한다.
tags: [token-efficiency]
relations:
  intents: [INT-2026-05-29-104710-ai-driven-documentation, INT-2026-05-29-104707-token-efficient-context-loading]
  tasks: [Jeis-Jw/ai-plugins#87]
---

## 결정

wiki-markdown 0.22.0에 Claude Code Stop hook `hooks/capture_checkpoint.py`를 추가한다. 턴 종료 시 durable 후보 감사 리마인더를 1회 주입하되, 5중 게이트를 전부 통과할 때만 발화한다: (1) `WIKI_MARKDOWN_CHECKPOINT=off` kill-switch, (2) `stop_hook_active` 루프 가드, (3) `<cwd>/wiki` vault 존재, (4) linked git worktree 제외(병렬 worker lane은 감사 대상 아님), (5) 산출물 임계 — 직전 발화 이후 Edit/Write/NotebookEdit tool use ≥3(`WIKI_MARKDOWN_CHECKPOINT_MIN_EDITS`) 또는 Bash `git commit` ≥1. 발화 시 세션별 state에 transcript 라인을 기록해 배치당 1회만 리마인드하고, 미발화 시 출력 0바이트다. 리마인더 본문은 '새 recall/탐색 금지, 기존 컨텍스트로 제안 또는 none 한 줄'을 지시해 후속 턴 비용도 캡한다.

## 취지

캡처 제안 누락 해소와 토큰 비용 통제를 양립시킨다. proactive 감사 계약을 실제로 발화하게 만들되, 위키 시스템의 최우선 설계 제약인 토큰 효율을 훼손하지 않는다.

## 배경

제안 규칙(milestone 감사)이 SKILL.md 내부에 있어 스킬을 호출하지 않으면 규칙 자체가 컨텍스트에 존재하지 않는 닭-달걀 구조였다. 상시 노출 표면은 스킬 description 한 줄과 정책 라인뿐이고, 완료-지향 모델은 사용자 요청이 끝나면 턴을 종료하므로 감사가 실측상 발화하지 않았다(산출물 있는 세션에서 제안 0회). caveman 플러그인이 hook 재주입으로 모드를 유지하는 것과 대조되어 hook 부재가 근본 원인으로 확인됐다.

## 고려한 대안

(1) 매턴 UserPromptSubmit 주입(caveman 방식) — 발화는 확실하나 매턴 토큰 비용과 나그로 '토큰 잡아먹는 하마' 우려에 정면 충돌, 반려. (2) description-only 현상 유지 — 미발화의 근본 원인이므로 반려. (3) Stop hook 무게이트 발화 — 잡담 세션·worker lane까지 리마인드가 붙어 비용 폭증, 반려.

## 트레이드오프

Codex에는 대응 hook 표면이 없어 Claude Code 한정 — plugin-agent-neutrality 취지와 긴장이 있으나 mechanism 문서(knowledge-protocol §12)에 한정 사실을 명시해 완화. Bash 'git commit' substring 매칭은 오탐 가능(비용은 리마인더 1회라 수용). state 파일은 /tmp 휘발이라 재부팅 시 배치 카운터가 리셋된다(수용).

## 재평가 조건

실사용에서 발화 빈도가 체감 과다해지거나(하마화) MIN_EDITS 기본값 3이 부적절하다는 증거가 쌓이면 임계 재조정. Codex가 hook 표면을 제공하면 Claude 한정 해제 재검토.
