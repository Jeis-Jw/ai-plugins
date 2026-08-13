---
title: capture 정책은 초기화 시 auto-loaded agent entry에 설치한다
created_at: 2026-08-13
summary: runtime hook을 제거하고 agent-facing wiki init이 CLAUDE.md와 AGENTS.md에 best-effort capture 정책을 설치해 primary 답변 우선·후보 있을 때만 제안·승인 전 write 금지를 유지한다.
tags: [wiki, capture, agent-policy, token-efficiency]
supersedes: [DEC-2026-08-06-024741-capture-checkpoint를-stop-hook-5중-게이트-배치당-1회로-도입]
relations:
  intents: [INT-2026-05-29-104710-ai-driven-documentation, INT-2026-05-29-104707-token-efficient-context-loading]
  ssot: [wiki-markdown-plugin, wiki-retrieval]
---

## 결정

wiki-markdown의 capture 실행 규칙은 runtime hook이 아니라 프로젝트 초기화 시 auto-loaded agent entry에 설치한다. raw wiki_cli.py init은 vault-only로 유지하고, agent-facing $wiki init은 vault 초기화 후 agent-policy workflow를 통해 CLAUDE.md와 AGENTS.md의 관리 블록을 멱등 갱신한다. agent는 본 작업과 primary 답변을 먼저 완료하고, 기존 context에서 genuine durable 후보가 있을 때만 같은 final 하단에 자연스러운 grouped capture 질문을 추가하며, 후보가 없으면 침묵하고 승인 전에는 쓰지 않는다.

## 취지

누락 방지라는 원래 목적을 유지하면서 hook continuation이 본 답변을 대체하는 UX와 매-turn prompt 주입 비용을 없앤다.

## 배경

Stop hook은 턴 종료를 차단하고 hook_prompt를 사용자 메시지처럼 continuation으로 주입해 본 답변이 사라지는 실패를 만들었다. edit 수와 git commit 문자열 기반 heuristic도 semantic durability를 판별하지 못했다. UserPromptSubmit은 본 답변 전 context로는 동작하지만 매 메시지 토큰 비용이 생긴다. 반면 CLAUDE.md와 AGENTS.md는 작업 시작 시 자동 로드되므로 긴 작업에서 규칙을 한 번만 제공한다.

## 고려한 대안

Stop hook 보정은 본 답변 대체 위험이 남아 반려한다. UserPromptSubmit 매-turn 주입은 반복 토큰 비용 때문에 반려한다. plugin rules 파일만 배포하는 안은 host가 generic rules를 자동 로드한다는 계약이 없어 반려한다.

## 트레이드오프

agent policy는 hard guarantee가 아닌 best-effort다. 대신 본 작업 우선, 낮은 토큰 비용, host-neutral한 entry file 계약, 기존 scaffold의 멱등성과 사용자 파일 보존을 얻는다. raw CLI 자동화 호환성을 위해 init 자체에는 agent file write를 넣지 않는다.

## 재평가 조건

Codex와 Claude가 user-visible continuation 없이 turn-close semantic audit을 수행하는 공식 non-blocking hook 계약을 제공하고 실제 누락률 개선이 반복 토큰 비용보다 크다는 근거가 생기면 runtime 집행을 재검토한다.
