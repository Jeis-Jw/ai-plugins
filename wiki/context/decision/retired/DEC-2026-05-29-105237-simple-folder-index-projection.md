---
title: 단순 폴더 인덱스 파생 (v0)
created_at: 2026-05-29
summary: v0 시점 결정: 각 폴더 인덱스는 그 폴더 내 .md(retired/ 제외)의 summary를 모아 자동 생성. 하위 폴더 재귀 정책 미명세.
tags: [wiki, index, v0]
relations:
  intents: [INT-2026-05-29-104707-token-efficient-context-loading, INT-2026-05-29-104710-ai-driven-documentation]
retired_at: 2026-05-29
retired_type: superseded
superseded_by: DEC-2026-05-29-105321-folder-independent-index-derivation
---

## 결정

v0에서는 각 폴더 인덱스가 해당 폴더의 활성 `.md` 문서 summary를 모아 `- [[basename]] — summary` 목록으로 자동 생성된다고만 정의했다. 하위 폴더가 없다는 전제에 가까워 재귀 정책은 명확하지 않았다.

## 취지

인덱스를 사람이 직접 편집하지 않고 frontmatter에서 파생해 누락과 drift를 줄이려는 결정이었다. 인덱스는 상세 관계가 아니라 후보군 필터 역할만 해야 한다는 원칙을 구현했다.

## 배경

초기에는 ssot/runbook이 평면 구조였으므로 "폴더 내 문서"라는 표현만으로 충분했다. 이후 nested 폴더를 허용하면서 상위 인덱스가 하위 문서를 재귀 수집할지 명확히 해야 했다.

## 고려한 대안

- 기존 표현 유지: nested 도입 후 해석 차이가 생겨 반려했다.
- 상위 인덱스 재귀 수집: 인덱스 비대화와 중복으로 반려했다.

## 트레이드오프

v0 결정은 단순했지만 nested 구조의 의미를 충분히 설명하지 못했다. v1에서는 "재귀=폴더 발견, 비재귀=노트 수집"으로 알고리즘을 명시한다.

## 재평가 조건

이 결정은 [[DEC-2026-05-29-105321-folder-independent-index-derivation]]로 superseded되었다. 현재는 폴더 단위 독립 인덱스 파생을 따른다.
