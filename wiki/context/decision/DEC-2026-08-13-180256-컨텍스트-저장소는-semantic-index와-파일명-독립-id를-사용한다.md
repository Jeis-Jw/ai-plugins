---
title: 컨텍스트 저장소는 semantic index와 파일명 독립 ID를 사용한다
created_at: 2026-08-13
summary: 폴더가 artifact 의미를 정하고 자유로운 문서 파일명과 immutable internal ID를 분리하며 context.index.md와 영역별 semantic index를 문서에서 파생해 실제 1차 검색면으로 사용한다.
tags: [context-core, context-decision, storage, index, identity]
search_terms: [context.index.md, snapshot.index.md, observation.index.md, decision.index.md, index-first recall, document-authoritative]
---

## 결정

새 컨텍스트 저장소는 context/context.index.md를 영역 catalog로, context/snapshot/snapshot.index.md·context/observation/observation.index.md·context/decision/decision.index.md를 영역별 index로 사용한다. 개별 문서 파일명에는 SNAP·OBS·DEC prefix나 timestamp를 강제하지 않고 사람이 읽기 좋은 slug를 사용한다. artifact type은 폴더와 schema가 결정하고, 정체성과 관계는 파일명과 분리된 immutable internal ID가 소유한다. 개별 Markdown 문서가 정본이며 index의 generated entries는 문서 frontmatter에서 결정적으로 재생성한다. 기본 recall은 index에서 후보를 좁힌 뒤 선택된 문서만 읽고, stale index는 경고와 폴더 scan fallback으로 복구한다.

## 취지

Obsidian graph와 파일 검색에서 영역을 명확히 드러내면서 rename 안전성과 token-efficient recall을 함께 확보한다.

## 배경

기존 wiki-markdown은 의미가 드러나는 폴더 index를 갖지만 record basename을 ID로 사용하고 실제 recall은 모든 문서 frontmatter를 스캔한다. 새 플러그인은 기존 방식을 참고하되 파일명 규격과 검색 비용을 분리한다.

## 고려한 대안

_index.md는 구현 충돌은 적지만 Obsidian과 파일 검색에서 영역 구분력이 낮아 반려한다. basename을 정본 ID로 유지하는 방식은 자유로운 rename과 동일 basename의 영역별 공존을 깨뜨려 반려한다. index를 정본으로 삼는 방식은 drift와 수동 편집 위험 때문에 반려한다.

## 트레이드오프

immutable ID 필드와 index drift 검사가 추가된다. 영역 index는 동시 capture 시 Git hot file이 될 수 있으나 v1에서는 deterministic regeneration으로 해결하고 sharding이나 database는 도입하지 않는다.

## 재평가 조건

영역 index가 반복적으로 병합 충돌을 만들거나 문서 수 증가로 index parse 비용이 병목이 되면 shard index나 local derived cache를 검토한다.
