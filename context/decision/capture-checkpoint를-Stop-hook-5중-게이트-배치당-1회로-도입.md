---
schema: "context-decision/v1"
id: "ctx_15dd4d712c2441d5bcad5d5326879f99"
title: "capture checkpoint를 Stop hook 5중 게이트·배치당 1회로 도입"
summary: "semantic milestone 감사(§12.3)가 모델 재량만으로 누락되어 wiki-markdown 0.22.0에 Claude Code Stop hook을 도입 — 5중 게이트 전부 통과 시에만 발화하고 세션 state로 배치당 1회만 리마인드해 토큰 비용을 통제한다."
created_at: "2026-08-15T02:52:30+09:00"
captured_from: "import"
source_refs: ["file:wiki/context/decision/retired/DEC-2026-08-06-024741-capture-checkpoint를-stop-hook-5중-게이트-배치당-1회로-도입.md"]
tags: ["token-efficiency"]
scope: "ai-plugins/wiki-markdown"
decision_key: "capture-policy-surface"
revisit_when: ["실사용에서 발화 빈도가 체감 과다해지거나(하마화) MIN_EDITS 기본값 3이 부적절하다는 증거가 쌓이면 임계 재조정. Codex가 hook 표면을 제공하면 Claude 한정 해제 재검토."]
---

## 결정

semantic milestone 감사(§12.3)가 모델 재량만으로 누락되어 wiki-markdown 0.22.0에 Claude Code Stop hook을 도입 — 5중 게이트 전부 통과 시에만 발화하고 세션 state로 배치당 1회만 리마인드해 토큰 비용을 통제한다.

## 취지

캡처 제안 누락 해소와 토큰 비용 통제를 양립시킨다. proactive 감사 계약을 실제로 발화하게 만들되, 위키 시스템의 최우선 설계 제약인 토큰 효율을 훼손하지 않는다.

## 반려대안

- (1) 매턴 UserPromptSubmit 주입(caveman 방식) — 발화는 확실하나 매턴 토큰 비용과 나그로 '토큰 잡아먹는 하마' 우려에 정면 충돌, 반려. (2) description-only 현상 유지 — 미발화의 근본 원인이므로 반려. (3) Stop hook 무게이트 발화 — 잡담 세션·worker lane까지 리마인드가 붙어 비용 폭증, 반려.

## 트레이드오프

- Codex에는 대응 hook 표면이 없어 Claude Code 한정 — plugin-agent-neutrality 취지와 긴장이 있으나 mechanism 문서(knowledge-protocol §12)에 한정 사실을 명시해 완화. Bash 'git commit' substring 매칭은 오탐 가능(비용은 리마인더 1회라 수용).

## 재평가 조건

- 실사용에서 발화 빈도가 체감 과다해지거나(하마화) MIN_EDITS 기본값 3이 부적절하다는 증거가 쌓이면 임계 재조정. Codex가 hook 표면을 제공하면 Claude 한정 해제 재검토.
