---
title: obsidian-cli를 AI 검색 주경로로
created_at: 2026-05-29
summary: AI 검색의 1차 경로로 obsidian-cli/Dataview/Bases를 쓰자는 안. 캐시 신선도 지연, 헤드리스 미동작, 데이터모델이 강점을 이미 대체. filesystem+ripgrep 단일로 반려.
tags: [wiki, obsidian, rejected]
---

## 대안

AI 검색과 관계 조회의 1차 경로를 obsidian-cli, Dataview, Bases, Obsidian 백링크 그래프에 두는 방식이다. Obsidian의 링크/메타데이터 인덱스를 활용해 사람이 쓰는 vault 경험과 AI 검색을 일치시키려는 접근이다.

## 반려 사유

AI가 문서를 쓴 직후 Obsidian 메타데이터 캐시가 최신이라는 보장이 없다. CI, git hook, 워크트리, 서버 환경처럼 GUI가 없는 헤드리스 환경에서도 동작해야 하는데 Obsidian 런타임 의존은 이 조건을 깨뜨린다.

또한 이 위키는 YAML relations, basename resolver, ripgrep으로 필요한 관계 질의를 이미 제공한다. 외부 도구를 정본으로 삼을 이유가 없다.

## 이 대안의 취지

Obsidian의 강한 탐색 UX와 백링크 기능을 그대로 활용하려는 목적이었다. 사람이 보는 그래프와 AI가 보는 그래프가 같아지면 직관적이라는 장점이 있다.

## 재고 조건

Obsidian 계열 도구가 헤드리스·즉시 일관성·표준 API를 안정적으로 제공하고, 플러그인 이식성을 해치지 않는다면 보조 검색 adapter로 검토할 수 있다. 정본 경로는 계속 filesystem-first여야 한다.
