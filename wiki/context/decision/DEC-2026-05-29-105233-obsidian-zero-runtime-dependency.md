---
title: Obsidian 런타임 의존 0
created_at: 2026-05-29
summary: AI 검색 정본은 filesystem 단일(ripgrep+YAML). obsidian-cli/Dataview/Bases는 AI 파이프라인 제외. wikilink는 사람용 장식.
tags: [wiki, obsidian, architecture]
relations:
  intents: [INT-2026-05-29-104709-filesystem-primary-truth, INT-2026-05-29-104712-parallel-safe-headless-operation, INT-2026-05-29-104710-ai-driven-documentation]
  rejected_decisions: [REJ-2026-05-29-105457-obsidian-cli-primary-search]
---

## 결정

위키 플러그인의 AI 검색과 검증 경로는 filesystem + YAML + ripgrep으로 고정한다. Obsidian, obsidian-cli, Dataview, Bases, 백링크 그래프는 사람용 보조 도구일 뿐 플러그인 런타임 의존성이 아니다.

`[[basename]]` wikilink 문법은 유지하되, 관계 정본은 아니다. wikilink는 파일 이동에 강하고 Obsidian에서 클릭 탐색을 제공하는 human UX layer로 취급한다.

## 취지

이 위키는 Codex/Claude/CI/워크트리 같은 헤드리스 환경에서 동작해야 한다. GUI 도구나 캐시 기반 인덱스를 정본으로 삼으면 자동화 직후 조회 누락, 환경 차이, vendor lock-in이 생긴다.

Obsidian 호환성은 포기하지 않지만, 설계가 Obsidian UX에 끌려가면 AI-native 목적이 흐려진다.

## 배경

초기 대화에서는 wikilink를 문서 관계로 활용하는 방안과 Obsidian 링크 기능 활용 가능성을 검토했다. 결론은 AI가 Obsidian 링크 엔진을 직접 쓰는 것이 아니라, Markdown 문자열과 파일명을 해석한다는 점이었다.

따라서 정본 모델은 Obsidian-compatible이 아니라 filesystem-primary여야 한다.

## 고려한 대안

- obsidian-cli를 1차 검색 경로로 사용: 캐시 신선도와 헤드리스 미동작 위험으로 반려했다.
- Dataview/Bases를 관계 질의 표면으로 사용: 사람에게는 편하지만 플러그인 이식성을 깨서 반려했다.
- wikilink를 관계 정본으로 사용: 파싱 모호성과 코드블록 오탐으로 반려했다.

## 트레이드오프

Obsidian의 백링크/그래프 뷰와 플러그인 검증 결과가 완전히 같은 의미를 갖지는 않는다. 사용자는 Obsidian을 viewer로 사용할 수 있지만, 오류 판단과 자동화는 YAML 정본을 따른다.

GitHub Markdown에서는 Obsidian wikilink가 일반 링크처럼 렌더링되지 않을 수 있다. 이 시스템은 GitHub Wiki/웹 렌더링보다 AI 자동화와 로컬 파일 정본을 우선한다.

## 재평가 조건

Obsidian 또는 다른 도구가 헤드리스, 즉시 일관성, 표준 파일 기반 API를 안정적으로 제공하고 플러그인 이식성을 해치지 않는다면 보조 통합을 재검토할 수 있다. 정본 경로 전환은 별도 결정이 필요하다.
