---
title: session-review 스냅샷 백엔드 하이브리드화
created_at: 2026-06-19
summary: session-review가 wiki-markdown 있으면 위임, 없으면 동일 포맷 내장 writer로 fallback. 타 워크스페이스 이식성 확보.
tags: [session-review, architecture, portability]
relations:
  ssot: [session-review-plugin]
---

## 결정

session-review의 스냅샷 핸드셰이크를 하이브리드 백엔드로 한다. wiki-markdown(wiki_cli) 발견 시 위임(현 동작·DEC-2026-06-18 유지), 없으면 session_review.py 내장 writer가 동일 frontmatter+섹션 포맷·동일 위치(wiki/snapshot/SNAP-<slug>.md)로 기록. 경로 해석은 스크립트 __file__ 자기위치 기반으로 하니스 무관(Claude Code·Codex).

## 취지

내 플러그인을 쓰는 다른 워크스페이스에서 session-review만 설치돼도 리뷰 루프가 동작해야 한다. CLAUDE_PLUGIN_ROOT 전용 경로는 Codex에서 깨지므로 하니스 무관 자기위치가 필요.

## 배경

self-flow 도그푸드(2026-06-19)에서 서브에이전트 리뷰어가 friction 6건 보고: status 손편집, wiki 하드의존, 모노레포 경로 하드코딩 등. DEC-2026-06-18 재평가조건의 'self 모드 비중 증가'가 실제로 도래.

## 고려한 대안

(1) wiki 하드 prerequisite + 문서화만: 단독 사용 불가. (2) 완전 standalone(bespoke 포맷): DEC-2026-06-18 위반. (3) 하이브리드(채택): 동일 포맷 fallback이라 bespoke 아님, wiki 있으면 그대로.

## 트레이드오프

얻음: 이식성, 단독 동작, DEC-2026-06-18 합치(동일 포맷). 잃음: 내장 writer가 wiki snapshot 포맷 일부를 중복 보유(스키마 변경 시 동기화 필요).

## 재평가 조건

wiki snapshot frontmatter/섹션 스키마가 바뀌어 내장 writer와 어긋날 때. Codex 플러그인 경로 규약이 표준화되어 자기위치 휴리스틱이 불필요해질 때.

