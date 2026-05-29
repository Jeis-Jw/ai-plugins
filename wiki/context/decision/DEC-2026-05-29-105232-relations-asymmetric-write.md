---
title: 관계 정본 = YAML, 작성은 record만, 허브는 파생
created_at: 2026-05-29
summary: 관계 정본은 frontmatter YAML의 plain basename. record(decision/rejected/trial/observation)만 작성하고 허브(intent/ssot/runbook)는 백링크로 파생.
tags: [wiki, relations, architecture]
relations:
  intents: [INT-2026-05-29-104707-token-efficient-context-loading, INT-2026-05-29-104708-atomic-knowledge-records, INT-2026-05-29-104709-filesystem-primary-truth]
  rejected_decisions: [REJ-2026-05-29-105456-wikilink-as-relation-source, REJ-2026-05-29-105458-living-writes-relations]
---

## 결정

문서 관계의 정본은 frontmatter YAML의 plain basename이다. 본문 `[[wikilink]]`는 사람이 읽고 이동하기 위한 장식이며, 관계 그래프 검증의 정본으로 쓰지 않는다.

관계는 record 쪽에서만 작성한다. `intent`, `ssot`, `runbook` 같은 허브 문서는 `relations` 키를 갖지 않고, 역방향 탐색은 `recall --backlinks-of`가 YAML 관계를 스캔해 파생한다. 단, supersede 쌍은 lifecycle 정합성을 위해 양방향 top-level 필드로 저장한다.

## 취지

허브 문서가 자신을 참조하는 모든 record 목록을 직접 저장하면 헤더가 계속 비대해지고 drift가 발생한다. 관계 작성 책임을 record에만 두면 새 발견이나 결정이 생겼을 때 해당 record만 갱신하면 된다.

plain basename은 자동 검증과 파일 검색이 쉽고, Obsidian 문법에 의존하지 않는다. 이는 filesystem-primary 원칙과 맞다.

## 배경

대화 중 YAML relations에 `[[...]]`를 넣는 방안도 검토했다. 사람에게는 클릭 가능한 링크가 좋아 보였지만, YAML을 데이터 레이어로 쓰려면 마크업 문자열을 매번 파싱해야 하고 alias/section/embed 같은 변형을 금지해야 했다.

또한 `ssot`가 관련 decisions를 직접 들고 있는 구조도 검토했지만, living 문서가 점점 관계 허브로 비대해지는 문제가 있었다.

## 고려한 대안

- 본문 wikilink를 관계 정본으로 사용: 코드블록과 예시까지 오탐하고 스키마 검증이 어려워 반려했다.
- YAML relation 값을 quoted wikilink로 저장: Obsidian UX는 좋지만 데이터 레이어가 마크업에 종속되어 반려했다.
- living 문서도 relations 작성: 허브 문서 비대화와 양방향 drift 때문에 반려했다.

## 트레이드오프

사람이 YAML 헤더에서 바로 클릭 이동하기는 어렵다. 대신 인덱스와 본문에는 wikilink를 허용해 사람 탐색 편의를 남긴다.

백링크는 저장된 값이 아니라 파생 결과이므로 조회 시 스캔 비용이 든다. 하지만 1인 프로젝트 규모의 Markdown vault에서는 ripgrep/YAML 스캔 비용이 충분히 작다.

## 재평가 조건

vault 규모가 매우 커져 YAML 백링크 스캔이 병목이 되거나, 외부 인덱스가 정본으로 승격될 만큼 안정화되면 관계 저장 방식을 재검토한다.
