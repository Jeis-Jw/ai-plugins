---
title: 본문 wikilink를 관계 정본으로
created_at: 2026-05-29
summary: 관계 정본을 본문 [[wikilink]]로 두자는 안. 코드블록 오탐, 파싱 모호, 양방향 정합성 검사 곤란, obsidian-cli 절단 전제 붕괴로 반려. YAML plain ID가 정본.
tags: [wiki, relations, rejected]
---

## 대안

본문이나 frontmatter의 `[[basename]]` wikilink를 관계 그래프의 정본으로 삼는 방식이다. Obsidian에서 클릭 가능한 링크와 AI가 읽는 관계가 동일해 보인다는 장점이 있다.

## 반려 사유

Wikilink는 Markdown 본문, 예시, 코드블록, 설명 문장에 자유롭게 등장할 수 있어 관계 정본으로 파싱하면 오탐이 많다. alias, section, embed 같은 Obsidian 문법 변형까지 허용하면 자동 검증이 복잡해진다.

YAML plain basename은 값 자체가 문서 ID이므로 존재 검사, relation type 검사, 백링크 파생이 단순하다.

## 이 대안의 취지

사람이 Obsidian에서 바로 클릭 이동할 수 있게 하고, 중복된 관계 표기를 줄이려는 목적이었다. 특히 "헤더 relations도 링크면 본문에 별도 연관관계 섹션을 반복하지 않아도 된다"는 기대가 있었다.

## 재고 조건

Obsidian 호환성이 AI 자동화보다 우선되는 프로젝트라면 재검토할 수 있다. 이 플러그인의 기본 정책은 AI/스크립트가 읽는 구조화 데이터는 plain basename, 사람이 읽는 본문/인덱스는 wikilink 허용이다.
